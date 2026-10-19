"""Cliente para a API pública do Arquivo.pt.

Documentação: https://github.com/arquivo/pwa-technologies/wiki/APIs
Endpoints usados:
- `GET https://arquivo.pt/textsearch` — pesquisa de texto completo.
- `GET https://arquivo.pt/wayback/cdx` — listagem de capturas (CDX).
- `GET https://arquivo.pt/textextracted` — texto extraído de uma captura.

A API não exige autenticação. Respeitamos o rate-limit usando um intervalo
mínimo configurável entre pedidos.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://arquivo.pt"
TEXTSEARCH_URL = f"{BASE_URL}/textsearch"
CDX_URL = f"{BASE_URL}/wayback/cdx"
TEXTEXTRACTED_URL = f"{BASE_URL}/textextracted"

DEFAULT_MAX_ITEMS = 50
DEFAULT_MAX_PAGES = 10
DEFAULT_MIN_INTERVAL = 0.5
DEFAULT_TIMEOUT = 30.0

# A pesquisa de texto do Arquivo.pt recusa termos que parecem URLs/domínios
# (`400`, a remeter para o CDX), por isso esses casos são detetados antes do
# pedido e encaminhados para o índice de capturas.
_URL_QUERY_RE = re.compile(
    r"^(?:https?://)?[a-z0-9][a-z0-9._-]*\.[a-z]{2,}(?:[/?#].*)?$", re.IGNORECASE
)


def looks_like_url_query(q: str) -> bool:
    """Diz se a pesquisa é um URL/domínio em vez de termos de texto."""
    value = (q or "").strip()
    if not value or " " in value:
        return False
    return bool(_URL_QUERY_RE.match(value))


def _domain_from_url(url: str) -> str:
    """Extrai o domínio (host) de um URL, sem credenciais nem porta."""
    try:
        netloc = urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url
    return netloc.rsplit("@", 1)[-1].split(":")[0].lower()


def _host_key_to_domain(host_key: str) -> str:
    """Converte uma hostKey do Arquivo.pt (`(pt,gov,)`) num domínio."""
    # Exemplos de hostKey: "(eu,rockproject,)" ou "(pt,cm-castromarim,algarvedigital,)"
    cleaned = host_key.strip("()")
    parts = [p for p in cleaned.split(",") if p]
    if not parts:
        return ""
    return ".".join(reversed(parts))


def _parse_tstamp(tstamp: str) -> Optional[str]:
    """Converte timestamp do Arquivo.pt (YYYYmmddHHMMSS) para ISO 8601."""
    value = (tstamp or "").strip()
    if len(value) >= 8:
        try:
            dt = datetime.strptime(value[:14], "%Y%m%d%H%M%S")
            return dt.isoformat()
        except ValueError:
            pass
    return None


class ArquivoClient:
    """Cliente simples para a API do Arquivo.pt com rate-limit básico."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request = 0.0
        self._client: Optional[httpx.Client] = None

    def _client_instance(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        return self._client

    def _wait(self) -> None:
        """Garante intervalo mínimo entre pedidos consecutivos."""
        if self.min_interval <= 0:
            return
        now = time.time()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        self._wait()
        response = self._client_instance().get(url, params=params)
        self._last_request = time.time()
        response.raise_for_status()
        return response

    def search(
        self,
        q: str,
        *,
        offset: int = 0,
        max_items: int = DEFAULT_MAX_ITEMS,
        title_max_length: int = 300,
        snippet_max_length: int = 300,
        dedup_value: int = 2,
        dedup_field: str = "title",
        site: Optional[str] = None,
        type: Optional[str] = None,
        collection: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pesquisa no índice de texto do Arquivo.pt.

        Parâmetros:
            q: termos de pesquisa.
            offset: paginação.
            max_items: máximo de resultados (máx. recomendado 200).
            site: filtrar por domínio (ex.: "portugal.gov.pt").
            type: filtro de tipo (ex.: "html", "pdf").
            collection: filtro de coleção.
            from_ts: timestamp inicial (YYYYmmddHHMMSS).
            to_ts: timestamp final (YYYYmmddHHMMSS).
        """
        params: Dict[str, Any] = {
            "q": q,
            "offset": max(0, offset),
            "maxItems": min(max(1, max_items), 200),
            "titleMaxLength": title_max_length,
            "snippetMaxLength": snippet_max_length,
            "dedupValue": dedup_value,
            "dedupField": dedup_field,
        }
        if site:
            params["site"] = site
        if type:
            params["type"] = type
        if collection:
            params["collection"] = collection
        if from_ts:
            params["from"] = from_ts
        if to_ts:
            params["to"] = to_ts

        response = self._get(TEXTSEARCH_URL, params)
        return response.json()

    def cdx(
        self,
        url: str,
        *,
        output: str = "json",
        limit: Optional[int] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        match_type: Optional[str] = None,
        filter_: Optional[str] = None,
        collapse: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta o CDX (índice de capturas) do Arquivo.pt.

        Devolve lista de dicionários com os campos padrão do CDX.
        """
        params: Dict[str, Any] = {"url": url, "output": output}
        if limit is not None:
            params["limit"] = limit
        if from_ts:
            params["from"] = from_ts
        if to_ts:
            params["to"] = to_ts
        if match_type:
            params["matchType"] = match_type
        if filter_:
            params["filter"] = filter_
        if collapse:
            params["collapse"] = collapse

        response = self._get(CDX_URL, params)
        lines = [line.strip() for line in response.text.strip().splitlines() if line.strip()]
        if not lines:
            return []

        # Formato atual: NDJSON — uma captura por linha.
        if lines[0].startswith("{"):
            results: List[Dict[str, Any]] = []
            for line in lines:
                try:
                    results.append(json.loads(line))
                except ValueError:
                    logger.debug("Linha CDX ignorada: %s", line[:120])
            return results

        # Formato antigo: cabeçalho (lista JSON ou campos separados por espaço)
        # seguido de linhas com valores na mesma ordem.
        try:
            keys = json.loads(lines[0]) if lines[0].startswith("[") else lines[0].split(" ")
            results = []
            for line in lines[1:]:
                if line.startswith("["):
                    values = json.loads(line)
                else:
                    values = line.split(" ")
                results.append({k: v for k, v in zip(keys, values) if k})
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("Resposta CDX inesperada: %s", exc)
            return []

    def extracted_text(self, url: str, tstamp: str) -> Optional[str]:
        """Devolve o texto extraído de uma captura (se disponível)."""
        # A API do Arquivo.pt para texto extraído aceita `m=<url>/<tstamp>`.
        m = f"{url}/{tstamp}"
        try:
            response = self._get(TEXTEXTRACTED_URL, {"m": m})
            return response.text
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "ArquivoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def normalize_search_result(item: Dict[str, Any], q: Optional[str] = None) -> Dict[str, Any]:
    """Normaliza um item da API do Arquivo.pt para o formato do índice local."""
    tstamp = item.get("tstamp") or ""
    original_url = item.get("originalURL") or ""
    host_key = item.get("hostKey") or ""
    domain = _host_key_to_domain(host_key) or _domain_from_url(original_url)
    capture_date = _parse_tstamp(tstamp)

    doc: Dict[str, Any] = {
        "title": item.get("title") or "",
        "url": original_url,
        "domain": domain,
        "tstamp": tstamp,
        "capture_date": capture_date,
        "digest": item.get("digest") or "",
        "mime_type": item.get("mimeType") or "",
        "collection": item.get("collection") or "",
        "link_to_archive": item.get("linkToArchive") or "",
        "link_to_no_frame": item.get("linkToNoFrame") or "",
        "link_to_screenshot": item.get("linkToScreenshot") or "",
        "link_to_extracted_text": item.get("linkToExtractedText") or "",
        "link_to_metadata": item.get("linkToMetadata") or "",
        "link_to_original_file": item.get("linkToOriginalFile") or "",
        "snippet": (item.get("snippet") or "").replace("<em>", "").replace("</em>", ""),
        "host_key": host_key,
    }
    if q:
        doc["query"] = q
    # Preservar campos originais para referência.
    doc["raw"] = dict(item)
    return doc


def normalize_cdx_result(item: Dict[str, Any], url: Optional[str] = None) -> Dict[str, Any]:
    """Normaliza um item do CDX para o formato do índice local."""
    tstamp = item.get("timestamp") or ""
    original_url = item.get("url") or url or ""
    capture_date = _parse_tstamp(tstamp)

    path = urlparse(original_url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    title = slug.replace("-", " ").replace("_", " ").strip()

    return {
        "title": title or _domain_from_url(original_url),
        "url": original_url,
        "domain": _domain_from_url(original_url),
        "tstamp": tstamp,
        "capture_date": capture_date,
        "digest": item.get("digest") or "",
        "mime_type": item.get("mime") or "",
        "status": item.get("status") or "",
        "length": item.get("length") or 0,
        "filename": item.get("filename") or "",
        "collection": item.get("collection") or "",
        "link_to_archive": f"{BASE_URL}/wayback/{tstamp}/{original_url}" if tstamp else "",
        "link_to_no_frame": f"{BASE_URL}/noFrame/replay/{tstamp}/{original_url}" if tstamp else "",
        "link_to_original_file": f"{BASE_URL}/noFrame/replay/{tstamp}id_/{original_url}" if tstamp else "",
        "host_key": item.get("urlkey") or "",
    }


def collect_url(
    url: str,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> Dict[str, Any]:
    """Recolhe capturas de um URL/domínio através do CDX do Arquivo.pt.

    Usado quando a pesquisa é um domínio ou endereço — caso em que a API de
    texto responde `400` e remete para o índice de capturas.
    """
    target = url.strip()
    if not target.lower().startswith(("http://", "https://")):
        target = f"https://{target}"

    after_scheme = target.split("://", 1)[-1]
    # Um caminho explícito pede prefixo; um domínio isolado pede o domínio todo.
    match_type = "prefix" if "/" in after_scheme.rstrip("/") else "domain"

    client = ArquivoClient(min_interval=min_interval)
    try:
        rows = client.cdx(
            target,
            limit=max(1, min(max_items, 200)),
            from_ts=from_ts,
            to_ts=to_ts,
            match_type=match_type,
        )
    finally:
        client.close()

    items = [normalize_cdx_result(row, url=target) for row in rows]
    return {
        "query": url,
        "site": None,
        "type": None,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "pages": 1 if items else 0,
        "offset": len(items),
        "collected": len(items),
        "estimated_total": len(items),
        "next_offset": None,
        "items": items,
    }


def collect_search(
    q: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    site: Optional[str] = None,
    type: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> Dict[str, Any]:
    """Recolhe resultados da pesquisa do Arquivo.pt até ao limite configurado.

    Devolve resumo com total estimado, itens recolhidos e próxima página.
    """
    if looks_like_url_query(q):
        result = collect_url(
            q,
            max_items=max_items * max_pages,
            from_ts=from_ts,
            to_ts=to_ts,
            min_interval=min_interval,
        )
        result["fallback"] = "cdx"
        return result

    client = ArquivoClient(min_interval=min_interval)
    all_items: List[Dict[str, Any]] = []
    offset = 0
    pages = 0
    estimated = 0
    next_page: Optional[str] = None

    try:
        while pages < max_pages:
            try:
                result = client.search(
                    q=q,
                    offset=offset,
                    max_items=max_items,
                    site=site,
                    type=type,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
            except httpx.HTTPStatusError as exc:
                # A API de texto recusa termos que interpreta como URL; nesse
                # caso a recolha continua pelo índice de capturas.
                if exc.response.status_code == 400 and pages == 0:
                    fallback = collect_url(
                        q,
                        max_items=max_items * max_pages,
                        from_ts=from_ts,
                        to_ts=to_ts,
                        min_interval=min_interval,
                    )
                    fallback["fallback"] = "cdx"
                    return fallback
                raise
            estimated = result.get("estimated_nr_results") or estimated
            next_page = result.get("next_page")
            items = result.get("response_items") or []
            if not items:
                break
            for item in items:
                all_items.append(normalize_search_result(item, q=q))
            pages += 1
            offset += len(items)
            if not next_page:
                break
    finally:
        client.close()

    return {
        "query": q,
        "site": site,
        "type": type,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "pages": pages,
        "offset": offset,
        "collected": len(all_items),
        "estimated_total": estimated,
        "next_offset": offset if next_page else None,
        "items": all_items,
    }
