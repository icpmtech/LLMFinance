"""Testes da reparação de cadeias TLS incompletas (`collectors/tls_chain.py`).

O CITIUS serve o certificado sem o intermédio correto (emissor ``YR2``, cadeia
com ``YR1``), o que dá ``unable to get local issuer certificate``. O que aqui se
protege é o que torna essa reparação segura e invisível para os coletores:

- só se tenta reparar quando o erro é realmente de **cadeia incompleta**;
- o *bundle* gerado é o ``certifi`` + os emitentes obtidos no AIA (e reaproveita-se);
- o cliente do CIRE repete o pedido com o novo ``verify``, sem devolver erro.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors import citius_cire, tls_chain  # noqa: E402


class _RespostaFalsa:
    def __init__(self, texto: str) -> None:
        self.content = texto.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


def _erro_tls(mensagem: str) -> requests.exceptions.SSLError:
    return requests.exceptions.SSLError(
        requests.exceptions.SSLError(f"HTTPSConnectionPool: SSLError(SSLCertVerificationError(1, '[SSL: "
                                     f"CERTIFICATE_VERIFY_FAILED] {mensagem} (_ssl.c:1016)'))")
    )


def test_is_chain_failure_distingue_cadeia_de_nome() -> None:
    assert tls_chain.is_chain_failure(
        _erro_tls("certificate verify failed: unable to get local issuer certificate")
    )
    assert tls_chain.is_chain_failure(
        _erro_tls("certificate verify failed: unable to get issuer certificate")
    )
    assert not tls_chain.is_chain_failure(
        _erro_tls("certificate verify failed: Hostname mismatch, certificate is not valid for 'x'")
    )
    assert not tls_chain.is_chain_failure(requests.exceptions.ConnectionError("reset"))
    assert not tls_chain.is_chain_failure(ValueError("outro"))


def test_bundle_junta_certifi_e_emitentes_e_reaproveita(tmp_path, monkeypatch) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID
    import datetime as dt

    monkeypatch.setattr(tls_chain, "_CACHE_DIR", tmp_path)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Emitente de teste")])
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agora = dt.datetime.now(dt.timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - dt.timedelta(days=1))
        .not_valid_after(agora + dt.timedelta(days=30))
        .sign(chave, hashes.SHA256())
    )

    caminho = tls_chain._bundle_path("exemplo.pt", 443, [certificado])
    texto = Path(caminho).read_text(encoding="utf-8")
    assert texto.startswith(Path(tls_chain.certifi.where()).read_text(encoding="utf-8"))
    assert certificado.public_bytes(Encoding.PEM).decode("ascii") in texto
    assert tls_chain._bundle_path("exemplo.pt", 443, [certificado]) == caminho


def test_cliente_cire_repete_pedido_com_o_bundle_do_aia(monkeypatch) -> None:
    tentativas: list[dict] = []

    class _SessaoFalsa:
        headers: dict = {}
        proxies: dict = {}

        def get(self, url, **kwargs):
            tentativas.append(kwargs)
            if len(tentativas) == 1:
                raise _erro_tls("unable to get local issuer certificate")
            return _RespostaFalsa("<html>Cire</html>")

        def close(self) -> None:
            return None

    monkeypatch.setattr(tls_chain, "_cache", {})
    monkeypatch.setattr(tls_chain, "verify_for", lambda *a, **k: "/tmp/citius.pem")

    with citius_cire.CireClient(min_interval=0.0, session=_SessaoFalsa()) as cliente:
        assert "Cire" in cliente.fetch_form()

    assert [t.get("verify") for t in tentativas] == [True, "/tmp/citius.pem"]
    assert cliente.verify == "/tmp/citius.pem"


def test_cliente_cire_nao_repara_erros_que_nao_sejam_de_cadeia(monkeypatch) -> None:
    chamadas: list[str] = []

    class _SessaoFalsa:
        headers: dict = {}
        proxies: dict = {}

        def get(self, url, **kwargs):
            chamadas.append(url)
            raise _erro_tls("Hostname mismatch, certificate is not valid for 'outro.pt'")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        tls_chain, "verify_for", lambda *a, **k: pytest.fail("não devia tentar reparar")
    )

    with pytest.raises(citius_cire.CireError):
        with citius_cire.CireClient(min_interval=0.0, session=_SessaoFalsa()) as cliente:
            cliente.fetch_form()
    assert len(chamadas) == 3  # as tentativas normais, sem reparação
