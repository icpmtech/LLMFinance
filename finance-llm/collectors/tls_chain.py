"""Reparação de cadeias TLS incompletas (perseguição do AIA «caIssuers»).

O ``www.citius.mj.pt`` (CITIUS) passou a servir o certificado do servidor
**sem o emitente intermédio correto**: o certificado é emitido por ``YR2``
(Let's Encrypt) mas a cadeia enviada traz o ``YR1``, o par de chaves anterior.
O resultado é ``requests`` → ``SSLError``
``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``, embora o
certificado seja legítimo — os browsers não se queixam porque descarregam o
emitente pela extensão **AIA** (*Authority Information Access* → ``caIssuers``).

Este módulo faz o mesmo que os browsers: quando um pedido falha por cadeia
incompleta, descarrega o(s) emitente(s) indicados no AIA, junta-os ao ``certifi``
num *bundle* temporário e devolve esse caminho para repetir o pedido com
``verify=<bundle>``.

A verificação continua **estrita**:

- o nome do servidor é validado (``check_hostname``);
- a cadeia tem de terminar numa raiz de confiança do ``certifi``;
- os certificados descarregados entram apenas como **elos intermédios** — os
  autoassinados que não constem do ``certifi`` são descartados, para que uma
  resposta forjada nunca se transforme em raiz de confiança.

Uso (num cliente ``requests``)::

    except requests.exceptions.SSLError as exc:
        novo = tls_chain.verify_for(url, proxy=self.proxy)
        if novo:
            self.verify = novo
            continue  # repetir o pedido
"""
from __future__ import annotations

import hashlib
import logging
import socket
import ssl
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import certifi
import requests

logger = logging.getLogger(__name__)

#: Cadeia máxima aceite (folga para raízes cruzadas do Let's Encrypt).
MAX_CHAIN = 5
DEFAULT_TIMEOUT = 15.0

#: Cache dos *bundles* gerados (só em memória; o ficheiro é reaproveitado em disco).
_CACHE_DIR = Path(tempfile.gettempdir()) / "iqos-tls"
_cache: Dict[str, Optional[str]] = {}
_lock = threading.Lock()

_MISS = object()

_CHAIN_ERRORS = (
    "unable to get local issuer certificate",
    "unable to get issuer certificate",
)


def is_chain_failure(exc: BaseException) -> bool:
    """Indica se o erro TLS é de **cadeia incompleta** (e não, p.ex., de nome)."""
    if not isinstance(exc, requests.exceptions.SSLError):
        return False
    text = str(exc)
    return "CERTIFICATE_VERIFY_FAILED" in text and any(m in text for m in _CHAIN_ERRORS)


def verify_for(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    proxy: Optional[str] = None,
) -> Optional[str]:
    """Devolve o caminho de um bundle de CAs que valida a cadeia TLS de ``url``.

    ``None`` quando não há nada a reparar (a cadeia valida com o ``certifi``) ou
    quando a reparação não é possível — nos dois casos o erro original deve subir.

    O resultado fica em cache por ``host:porta``, mas o *bundle* guardado é
    revalidado: se o portal trocar de emitente, a cache é refeita.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return None
    port = parts.port or (443 if parts.scheme == "https" else 80)
    key = f"{host}:{port}"
    with _lock:
        cached = _cache.get(key, _MISS)
    if cached is not _MISS:
        if cached is None or _verifies(host, port, cached, timeout):
            return cached
        with _lock:
            _cache.pop(key, None)
    path = None
    if not _verifies(host, port, certifi.where(), timeout):
        path = _repair(host, port, timeout, proxy)
    with _lock:
        _cache[key] = path
    return path


# ------------------------------------------------------------------ internos
def _repair(host: str, port: int, timeout: float, proxy: Optional[str]) -> Optional[str]:
    try:
        leaf = _leaf_der(host, port, timeout)
        if leaf is None:
            return None
        extra = _issuer_chain(leaf, timeout, proxy)
        if not extra:
            return None
        bundle = _bundle_path(host, port, extra)
        if not _verifies(host, port, bundle, timeout):
            logger.warning(
                "Cadeia TLS de %s continua inválida mesmo com os emitentes do AIA.", host
            )
            return None
        logger.info(
            "Cadeia TLS de %s incompleta no servidor; emitente obtido pelo AIA (%s).", host, bundle
        )
        return bundle
    except Exception as exc:  # noqa: BLE001 — a reparação é best-effort
        logger.debug("Não foi possível reparar a cadeia TLS de %s: %s", host, exc)
        return None


def _leaf_der(host: str, port: int, timeout: float) -> Optional[bytes]:
    """Certificado apresentado pelo servidor (sem validar: só para ler o AIA)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def _issuer_chain(leaf_der: bytes, timeout: float, proxy: Optional[str]) -> List[object]:
    """Emitentes que o próprio certificado indica no AIA (folha → raiz)."""
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID

    chain: List[object] = []
    seen = set()
    cert = x509.load_der_x509_certificate(leaf_der)
    seen.add(cert.subject.public_bytes())
    for _ in range(MAX_CHAIN):
        if cert.subject == cert.issuer:
            break
        url = _ca_issuers_url(cert, AuthorityInformationAccessOID.CA_ISSUERS)
        if not url:
            break
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                proxies={"http": proxy, "https": proxy} if proxy else None,
            )
            resp.raise_for_status()
            issuer = x509.load_der_x509_certificate(resp.content)
        except Exception as exc:  # noqa: BLE001
            logger.debug("AIA %s indisponível: %s", url, exc)
            break
        # Autoassinado só serve de raiz, e as raízes de confiança são as do `certifi`.
        if issuer.subject == issuer.issuer:
            break
        fingerprint = issuer.subject.public_bytes()
        if fingerprint in seen:
            break
        seen.add(fingerprint)
        chain.append(issuer)
        cert = issuer
    return chain


def _ca_issuers_url(cert: object, oid: object) -> Optional[str]:
    from cryptography import x509

    try:
        aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
    except x509.ExtensionNotFound:
        return None
    for description in aia:
        if description.access_method != oid:
            continue
        uri = description.access_location.value
        if isinstance(uri, str) and uri.startswith(("http://", "https://")):
            return uri
    return None


def _bundle_path(host: str, port: int, extra: List[object]) -> str:
    """Grava (ou reaproveita) ``certifi`` + emitentes num ficheiro PEM."""
    from cryptography.hazmat.primitives.serialization import Encoding

    base = Path(certifi.where()).read_text(encoding="utf-8")
    pems = "".join(cert.public_bytes(Encoding.PEM).decode("ascii") for cert in extra)
    digest = hashlib.sha256((base + pems).encode("utf-8")).hexdigest()[:16]
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{host}-{port}-{digest}.pem"
    if not path.exists():
        path.write_text(base + pems, encoding="utf-8")
    return str(path)


def _verifies(host: str, port: int, cafile: str, timeout: float) -> bool:
    """Confirma que ``cafile`` valida a cadeia servida por ``host:port``."""
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except (ssl.SSLError, OSError):
        return False
