"""Motor do módulo **SEC** — recolha, indexação e análise de filings EDGAR.

Funcionalidades:
- Pesquisar empresas/tickers e obter o CIK (Central Index Key) da SEC.
- Listar os filings mais recentes de uma empresa via EDGAR API.
- Descarregar o texto integral dos documentos (8-K, 10-K, 10-Q, 20-F, etc.).
- Indexar metadados e factos extraídos no Elasticsearch.
- Ingestão em bulk a partir dos arquivos ZIP diários da SEC.
- Análise agregada por tipo de documento, ano e ticker.

Toda a comunicação com a SEC segue as políticas da EDGAR:
- User-Agent institucional no cabeçalho.
- Throttle de ~100 ms entre pedidos.
- Sem autenticação: os dados são públicos.
"""
from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests

from api.elasticsearch_client import (
    SEC_FILINGS_INDEX,
    SEC_FACTS_INDEX,
    SEC_RECOLHAS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 900

_INDICES_GARANTIDOS = False
_INDICES_LOCK = threading.Lock()

ROOT = Path(__file__).resolve().parents[1]

# User-Agent institucional obrigatório para a SEC.
# A SEC rejeita pedidos sem User-Agent ou com User-Agent genérico.
# Exemplo: "Sample Company Name AdminContact@example.com"
_SEC_USER_AGENT = "Sabemos Studio IQ OS sec@sabemos.studio"
_SEC_HEADERS = {
    "User-Agent": _SEC_USER_AGENT,
    "Accept": "application/json",
}
# A SEC fornece dados JSON em www.sec.gov; data.sec.gov exige headers idênticos.
# Submissions e XBRL vivem em data.sec.gov; documentos e catálogos em www.sec.gov.
_SEC_BASE = "https://www.sec.gov"
_SEC_DATA_BASE = "https://data.sec.gov"

_FILING_TYPES = {"8-K", "10-K", "10-Q", "20-F", "40-F", "6-K", "S-1", "424B2", "DEF 14A"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(value: Any) -> str:
    """Texto simples para compor identificadores."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60]
    return text or "sem-tema"


def _garantir_indices() -> Optional[Any]:
    global _INDICES_GARANTIDOS
    es = get_es_client()
    if not es:
        return None
    if not _INDICES_GARANTIDOS:
        with _INDICES_LOCK:
            if not _INDICES_GARANTIDOS:
                try:
                    ensure_indices(es)
                    _INDICES_GARANTIDOS = True
                except Exception:
                    pass
    return es


def _es_doc(index: str, doc_id: str) -> Optional[Dict[str, Any]]:
    es = _garantir_indices()
    if not es:
        return None
    try:
        return es.get(index=index, id=doc_id).get("_source")
    except Exception:
        return None


def _search_index(
    index: str,
    body: Dict[str, Any],
    q: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = es.search(index=index, body={**body, "size": size, "from": from_})
        hits = response.get("hits", {}).get("hits", [])
        total = response.get("hits", {}).get("total", {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        return {"total": total_value, "items": [h.get("_source") for h in hits]}
    except Exception as exc:
        logger.warning("Pesquisa SEC falhou: %s", exc)
        return {"error": f"Elasticsearch: {exc}"}


def _cache_key(prefix: str, *args: Any) -> Tuple[Any, ...]:
    return (prefix,) + tuple(args)


def _cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        expires, value = entry
        if time.time() > expires:
            _CACHE.pop(key, None)
            return None
        return value


def _cache_set(key: Tuple[Any, ...], value: Dict[str, Any], ttl: int = 300) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time() + ttl, value)


# ---------------------------------------------------------------------------
# Recolha da SEC (EDGAR)
# ---------------------------------------------------------------------------

def _sec_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """GET para a SEC com throttling básico e cache curta."""
    url = path if path.startswith("http") else f"{_SEC_BASE}{path}"
    try:
        # Throttle mínimo para respeitar os limites da SEC.
        time.sleep(0.12)
        resp = requests.get(url, headers=_SEC_HEADERS, params=params, timeout=30)
        if resp.status_code == 403:
            logger.warning("SEC devolveu 403 em %s — User-Agent pode estar em falta ou bloqueado.", url)
            return None
        resp.raise_for_status()
        if "application/json" in resp.headers.get("Content-Type", ""):
            return resp.json()
        return resp.text
    except Exception as exc:
        logger.warning("Falha ao obter %s: %s", url, exc)
        return None


def search_companies_sec(q: str, max_results: int = 20) -> Dict[str, Any]:
    """Pesquisar empresas na SEC pelo nome ou ticker.

    Utiliza o ficheiro público `company_tickers.json` (cik -> ticker/name).
    """
    q = (q or "").strip().upper()
    if not q:
        return {"items": [], "total": 0}

    cache_key = _cache_key("company_tickers")
    tickers = _cache_get(cache_key)
    if tickers is None:
        # O ficheiro oficial tem vindo em /files/company_tickers.json, mas a
        # SEC moveu-o várias vezes. Tentamos ambos.
        data = _sec_get("/files/company_tickers.json")
        if data is None:
            data = _sec_get("/Archives/edgar/daily-index/cik-company-tickers.json")
        if not isinstance(data, list):
            # Formato atual: dicionário numérico com cik_str/ticker/title.
            if isinstance(data, dict):
                data = [
                    {
                        "cik": item.get("cik_str") or item.get("cik"),
                        "ticker": item.get("ticker", ""),
                        "name": item.get("title", "") or item.get("name", ""),
                    }
                    for item in data.values()
                ]
            else:
                return {"error": "Não foi possível carregar o catálogo de tickers da SEC"}
        tickers = {"data": data}
        _cache_set(cache_key, tickers, ttl=3600)

    data = tickers.get("data", [])
    results: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        ticker = (item.get("ticker") or "").upper()
        name = (item.get("name") or "").upper()
        cik = item.get("cik")
        if not cik:
            continue
        if q not in ticker and q not in name:
            continue
        key = f"{cik}-{ticker}"
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "cik": str(cik).zfill(10),
            "cik_int": int(cik),
            "ticker": ticker,
            "name": name.title(),
        })
        if len(results) >= max_results:
            break
    return {"items": results, "total": len(results), "query": q}


def filings_for_company(cik: str, limit: int = 40, form_types: Optional[List[str]] = None) -> Dict[str, Any]:
    """Filings recentes de uma empresa via submissions API.

    https://data.sec.gov/submissions/CIK{cik}.json
    """
    cik = str(cik).zfill(10)
    cache_key = _cache_key("submissions", cik, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Resolver ticker/nome a partir do catálogo em cache.
    catalog = _cache_get(_cache_key("company_tickers"))
    if catalog and isinstance(catalog.get("data"), list):
        for item in catalog["data"]:
            if str(item.get("cik", "")).zfill(10) == cik:
                ticker = (item.get("ticker") or "").upper()
                name = (item.get("name") or "").title()
                break
        else:
            ticker = ""
            name = ""
    else:
        ticker = ""
        name = ""

    submissions = _sec_get(f"{_SEC_DATA_BASE}/submissions/CIK{cik}.json")
    if not isinstance(submissions, dict):
        return {"error": "Não foi possível obter submissions da SEC"}

    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", []) or recent.get("description", [])

    allowed = {f.upper() for f in (form_types or [])} or _FILING_TYPES
    items: List[Dict[str, Any]] = []
    for i, form in enumerate(forms):
        if i >= len(dates) or i >= len(accessions) or i >= len(primary_docs):
            break
        if form not in allowed:
            continue
        acc = str(accessions[i]).replace("-", "").replace(" ", "")
        doc = str(primary_docs[i])
        if doc and not doc.startswith("/"):
            doc = "/" + doc
        url = f"{_SEC_BASE}/Archives/edgar/data/{int(cik)}/{acc}{doc}" if doc else None
        if not url:
            continue
        items.append({
            "cik": cik,
            "ticker": ticker,
            "company_name": name,
            "accession_number": accessions[i],
            "form": form,
            "date": dates[i],
            "description": (descriptions[i] if i < len(descriptions) else None) or form,
            "primary_document": primary_docs[i],
            "url": url,
        })
        if len(items) >= limit:
            break

    result = {"items": items, "total": len(items), "cik": cik, "ticker": ticker, "company_name": name}
    _cache_set(cache_key, result, ttl=300)
    return result


def fetch_filing_text(url: str) -> Dict[str, Any]:
    """Descarrega o texto integral de um documento SEC (HTML/TXT).

    Converte tags HTML para texto simples e devolve os primeiros 100k caracteres.
    """
    if not url:
        return {"text": "", "error": "URL em falta"}
    text = _sec_get(url)
    if text is None:
        return {"text": "", "error": "Não foi possível obter o documento"}
    if not isinstance(text, str):
        return {"text": str(text)[:100000], "error": None}

    # Limpeza simples de HTML.
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    # Quebrar camelCase/XBRL tokens para melhor legibilidade.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"text": text[:100000], "error": None}


# ---------------------------------------------------------------------------
# Indexação Elasticsearch
# ---------------------------------------------------------------------------

def index_filings(items: List[Dict[str, Any]], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Indexa metadados de filings no Elasticsearch."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}
    if not items:
        return {"indexed_count": 0}

    actions = []
    for item in items:
        doc_id = f"{item.get('cik', '')}-{item.get('accession_number', '')}"
        doc = {
            "_op_type": "index",
            "_index": SEC_FILINGS_INDEX,
            "_id": re.sub(r"[^a-zA-Z0-9_-]", "_", doc_id)[:64],
            "_source": {
                **item,
                "indexed_at": _now(),
                "autor_id": user_id,
            },
        }
        actions.append(doc)

    try:
        from elasticsearch.helpers import bulk
        success, errors = bulk(es, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0}


# ---------------------------------------------------------------------------
# XBRL / companyfacts
# ---------------------------------------------------------------------------

# Métricas XBRL mais úteis para análise financeira rápida.
_FACTS_PRIORITIES = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "NetIncomeLoss": "net_income",
    "NetIncomeLossAvailableToCommonStockholdersBasic": "net_income",
    "EarningsPerShareBasic": "eps",
    "EarningsPerShareDiluted": "eps_diluted",
    "Assets": "assets",
    "Liabilities": "liabilities",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "StockholdersEquity": "equity",
    "LongTermDebt": "long_term_debt",
    "OperatingIncomeLoss": "operating_income",
}


def company_facts(cik: str) -> Dict[str, Any]:
    """Obtém factos XBRL estruturados da SEC via companyfacts API.

    https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
    """
    cik = str(cik).zfill(10)
    cache_key = _cache_key("companyfacts", cik)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = f"{_SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    data = _sec_get(url)
    if not isinstance(data, dict):
        return {"error": "Não foi possível obter companyfacts da SEC"}

    facts = data.get("facts", {})
    taxonomy = "us-gaap"
    concepts = facts.get(taxonomy) or facts.get("ifrs-full") or facts.get("dei") or {}
    if not concepts:
        return {"error": "Nenhum conceito XBRL encontrado"}

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for concept_name, concept in concepts.items():
        priority = _FACTS_PRIORITIES.get(concept_name)
        if not priority:
            continue
        label = concept.get("label", concept_name)
        description = concept.get("description")
        for unit_key, entries in concept.get("units", {}).items():
            if not isinstance(entries, list):
                continue
            for entry in entries[-60:]:  # últimos 5 anos aproximadamente
                end = entry.get("end")
                if not end:
                    continue
                val = entry.get("val")
                if val is None:
                    continue
                accn = entry.get("accn", "")
                form = entry.get("form", "")
                fy = entry.get("fy")
                fp = entry.get("fp")
                key = (concept_name, unit_key, end, val)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append({
                    "cik": cik,
                    "ticker": "",
                    "company_name": data.get("entityName", ""),
                    "concept": concept_name,
                    "category": priority,
                    "label": label,
                    "description": description,
                    "unit": unit_key,
                    "value": val,
                    "end": end,
                    "start": entry.get("start"),
                    "fy": fy,
                    "fp": fp,
                    "form": form,
                    "accession_number": accn,
                })

    result = {
        "cik": cik,
        "company_name": data.get("entityName", ""),
        "taxonomy": taxonomy,
        "total_concepts": len(concepts),
        "facts": sorted(normalized, key=lambda x: (x["concept"], x["end"]), reverse=True),
    }
    _cache_set(cache_key, result, ttl=1800)
    return result


def _enrich_facts_with_ticker(facts: List[Dict[str, Any]], cik: str) -> None:
    """Preenche o ticker/nome a partir do catálogo em cache."""
    catalog = _cache_get(_cache_key("company_tickers"))
    if not catalog or not isinstance(catalog.get("data"), list):
        return
    for item in catalog["data"]:
        if str(item.get("cik", "")).zfill(10) == str(cik).zfill(10):
            ticker = (item.get("ticker") or "").upper()
            name = (item.get("name") or "").title()
            for fact in facts:
                fact["ticker"] = ticker
                fact["company_name"] = fact["company_name"] or name
            break


def index_company_facts(cik: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Indexa factos XBRL da empresa no Elasticsearch."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    data = company_facts(cik)
    if data.get("error"):
        return data

    facts = data.get("facts", [])
    if not facts:
        return {"cik": cik, "indexed_facts": 0}

    _enrich_facts_with_ticker(facts, cik)

    try:
        from elasticsearch.helpers import bulk
        actions = []
        for fact in facts:
            fact_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{cik}-{fact['concept']}-{fact['end']}-{fact.get('form','')}")[:64]
            actions.append({
                "_op_type": "index",
                "_index": SEC_FACTS_INDEX,
                "_id": fact_id,
                "_source": {
                    **fact,
                    "indexed_at": _now(),
                    "autor_id": user_id,
                },
            })
        success, errors = bulk(es, actions, raise_on_error=False, refresh=True)
        return {"cik": cik, "indexed_facts": success, "errors": len(errors)}
    except Exception as exc:
        return {"error": f"Falha ao indexar factos XBRL: {exc}"}


def _extract_facts(text: str, filing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Heurística simples: extrai frases com números e termos financeiros."""
    facts = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    keywords = ["revenue", "net income", "earnings", "total assets", "liabilities", "cash", "eps", "million", "billion"]
    for sentence in sentences:
        lower = sentence.lower()
        if any(k in lower for k in keywords) and re.search(r"\$?\d{1,3}(,\d{3})*(\.\d+)?\s*(million|billion|thousand)?", sentence):
            facts.append({
                "text": sentence[:500],
                "category": "financial_metric",
            })
        if len(facts) >= 50:
            break
    return facts


def index_filing_text(item: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Descarrega, extrai factos e indexa o documento."""
    if not item.get("url"):
        return {"error": "URL em falta"}
    fetched = fetch_filing_text(item["url"])
    if fetched.get("error"):
        return {"error": fetched["error"]}

    text = fetched["text"]
    facts = _extract_facts(text, item)
    doc_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{item.get('cik', '')}-{item.get('accession_number', '')}")[:64]
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    # Indexar o texto como documento principal.
    try:
        es.index(
            index=SEC_FILINGS_INDEX,
            id=doc_id,
            body={
                **item,
                "text": text[:50000],
                "facts_count": len(facts),
                "indexed_at": _now(),
                "autor_id": user_id,
            },
        )
    except Exception as exc:
        return {"error": f"Falha ao indexar texto: {exc}"}

    # Indexar factos extraídos.
    if facts:
        try:
            from elasticsearch.helpers import bulk
            fact_actions = []
            for idx, fact in enumerate(facts):
                fact_id = f"{doc_id}-fact-{idx}"
                fact_actions.append({
                    "_op_type": "index",
                    "_index": SEC_FACTS_INDEX,
                    "_id": fact_id,
                    "_source": {
                        "cik": item.get("cik"),
                        "ticker": item.get("ticker"),
                        "company_name": item.get("company_name"),
                        "accession_number": item.get("accession_number"),
                        "form": item.get("form"),
                        "date": item.get("date"),
                        "filing_id": doc_id,
                        "text": fact["text"],
                        "category": fact["category"],
                        "indexed_at": _now(),
                        "autor_id": user_id,
                    },
                })
            bulk(es, fact_actions, raise_on_error=False, refresh=True)
        except Exception as exc:
            logger.warning("Falha ao indexar factos SEC: %s", exc)

    return {"indexed": True, "facts_count": len(facts), "characters": len(text)}


def index_filings_for_cik(cik: str, limit: int = 20, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Pipeline completo: obtém filings, indexa metadados e descarrega/analisa texto."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    recolha_id = str(uuid.uuid4())
    filings = filings_for_company(cik, limit=limit)
    if filings.get("error"):
        return filings
    items = filings.get("items", [])

    indexed_meta = index_filings(items, user_id=user_id)
    analyzed = 0
    for item in items:
        try:
            res = index_filing_text(item, user_id=user_id)
            if res.get("indexed"):
                analyzed += 1
        except Exception as exc:
            logger.warning("Falha ao analisar filing %s: %s", item.get("accession_number"), exc)

    run_doc = {
        "id": recolha_id,
        "fonte": "sec_edgar",
        "url": f"https://www.sec.gov/edgar/search/#/entityNo={cik.zfill(10)}",
        "data": _now(),
        "total_docs": len(items),
        "autor_id": user_id,
        "parametros": {"cik": cik, "limit": limit},
        "detalhes": {"indexed_meta": indexed_meta, "analyzed": analyzed},
    }
    try:
        es.index(index=SEC_RECOLHAS_INDEX, id=recolha_id, body=run_doc)
    except Exception as exc:
        logger.warning("Falha ao registar recolha SEC: %s", exc)

    return {
        "cik": cik,
        "total": len(items),
        "indexed": indexed_meta.get("indexed_count", 0),
        "analyzed": analyzed,
        "recolha_id": recolha_id,
    }


# ---------------------------------------------------------------------------
# Bulk ingestion from SEC daily ZIP archives
# ---------------------------------------------------------------------------

BULK_DIR = ROOT / "data" / "sec_bulk"
BULK_DIR.mkdir(parents=True, exist_ok=True)

SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
COMPANYFACTS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"

_FILING_TYPES_BULK = {
    "8-K", "8-K/A", "10-K", "10-K/A", "10-Q", "10-Q/A",
    "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A",
    "S-1", "S-1/A", "424B2", "424B3", "424B4", "424B5",
    "DEF 14A", "DEFA14A", "SC 13G", "SC 13G/A", "SC 13D", "SC 13D/A",
}


def _download_sec_zip(url: str, dest: Path, chunk_size: int = 256 * 1024) -> bool:
    """Download a SEC bulk ZIP with streaming and throttling."""
    try:
        time.sleep(0.12)
        with requests.get(url, headers={"User-Agent": _SEC_USER_AGENT, "Accept": "application/zip"}, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as exc:
        logger.warning("Falha ao descarregar %s: %s", url, exc)
        return False


def _ensure_bulk_zip(url: str, filename: str) -> Optional[Path]:
    dest = BULK_DIR / filename
    if dest.exists():
        return dest
    if _download_sec_zip(url, dest):
        return dest
    return None


def _parse_submissions_bulk(zip_path: Path, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
    """Yield normalized filing items from the submissions bulk ZIP."""
    count = 0
    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        for name in names:
            if limit is not None and count >= limit:
                break
            if not name.startswith("CIK") or not name.endswith(".json"):
                continue
            try:
                data = json.loads(z.read(name))
            except Exception:
                continue
            cik = str(data.get("cik", "")).zfill(10)
            tickers = data.get("tickers") or []
            ticker = str(tickers[0]).upper() if tickers else ""
            company_name = (data.get("name") or "").title()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            descriptions = recent.get("primaryDocDescription", []) or recent.get("description", [])
            report_dates = recent.get("reportDate", [])
            is_xbrl = recent.get("isXBRL", [])

            for i, form in enumerate(forms):
                if limit is not None and count >= limit:
                    break
                if form not in _FILING_TYPES_BULK:
                    continue
                if i >= len(dates) or i >= len(accessions) or i >= len(primary_docs):
                    break
                acc = str(accessions[i]).replace("-", "").replace(" ", "")
                doc = str(primary_docs[i])
                if doc and not doc.startswith("/"):
                    doc = "/" + doc
                url = f"{_SEC_BASE}/Archives/edgar/data/{int(cik)}/{acc}{doc}" if doc else None
                if not url:
                    continue
                count += 1
                yield {
                    "cik": cik,
                    "ticker": ticker,
                    "company_name": company_name,
                    "accession_number": accessions[i],
                    "form": form,
                    "date": dates[i] or report_dates[i] if i < len(report_dates) else dates[i],
                    "report_date": report_dates[i] if i < len(report_dates) else None,
                    "description": (descriptions[i] if i < len(descriptions) else None) or form,
                    "primary_document": primary_docs[i],
                    "is_xbrl": bool(is_xbrl[i]) if i < len(is_xbrl) else False,
                    "url": url,
                }


def _parse_companyfacts_bulk(zip_path: Path, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
    """Yield normalized XBRL facts from the companyfacts bulk ZIP."""
    count = 0
    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        for name in names:
            if limit is not None and count >= limit:
                break
            if not name.startswith("CIK") or not name.endswith(".json"):
                continue
            try:
                data = json.loads(z.read(name))
            except Exception:
                continue
            cik = str(data.get("cik", "")).zfill(10)
            company_name = data.get("entityName", "")
            facts = data.get("facts", {})
            seen = set()
            for taxonomy, concepts in facts.items():
                if not isinstance(concepts, dict):
                    continue
                for concept_name, concept in concepts.items():
                    priority = _FACTS_PRIORITIES.get(concept_name)
                    label = concept.get("label", concept_name)
                    description = concept.get("description")
                    for unit_key, entries in concept.get("units", {}).items():
                        if not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if limit is not None and count >= limit:
                                break
                            end = entry.get("end")
                            if not end:
                                continue
                            val = entry.get("val")
                            if val is None:
                                continue
                            key = (cik, taxonomy, concept_name, unit_key, end, val)
                            if key in seen:
                                continue
                            seen.add(key)
                            count += 1
                            yield {
                                "cik": cik,
                                "ticker": "",
                                "company_name": company_name,
                                "concept": concept_name,
                                "category": priority,
                                "label": label,
                                "description": description,
                                "unit": unit_key,
                                "value": val,
                                "end": end,
                                "start": entry.get("start"),
                                "fy": entry.get("fy"),
                                "fp": entry.get("fp"),
                                "form": entry.get("form", ""),
                                "accession_number": entry.get("accn", ""),
                            }


def bulk_download_submissions(user_id: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Download and parse the submissions bulk ZIP into Elasticsearch."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    path = _ensure_bulk_zip(SUBMISSIONS_ZIP_URL, "submissions.zip")
    if not path:
        return {"error": "Não foi possível descarregar submissions.zip"}

    recolha_id = str(uuid.uuid4())
    try:
        from elasticsearch.helpers import bulk
        actions = []
        total = 0
        for item in _parse_submissions_bulk(path, limit=limit):
            doc_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{item['cik']}-{item['accession_number']}")[:64]
            actions.append({
                "_op_type": "index",
                "_index": SEC_FILINGS_INDEX,
                "_id": doc_id,
                "_source": {
                    **item,
                    "indexed_at": _now(),
                    "autor_id": user_id,
                    "source": "bulk_submissions",
                },
            })
            total += 1
            if len(actions) >= 2500:
                bulk(es, actions, raise_on_error=False, refresh=False)
                actions = []
        if actions:
            bulk(es, actions, raise_on_error=False, refresh=False)
        try:
            es.indices.refresh(index=SEC_FILINGS_INDEX)
        except Exception:
            pass
        run_doc = {
            "id": recolha_id,
            "fonte": "sec_bulk_submissions",
            "url": SUBMISSIONS_ZIP_URL,
            "data": _now(),
            "total_docs": total,
            "autor_id": user_id,
            "parametros": {"limit": limit},
        }
        try:
            es.index(index=SEC_RECOLHAS_INDEX, id=recolha_id, body=run_doc)
        except Exception as exc:
            logger.warning("Falha ao registar recolha bulk submissions: %s", exc)
        return {"recolha_id": recolha_id, "indexed": total}
    except Exception as exc:
        return {"error": f"Falha ao indexar submissions: {exc}", "indexed": 0}


def bulk_download_submissions_limited(limit: int = 1000, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper for testing with a limit."""
    return bulk_download_submissions(user_id=user_id, limit=limit)


def bulk_download_companyfacts(user_id: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Download and parse the companyfacts bulk ZIP into Elasticsearch."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    path = _ensure_bulk_zip(COMPANYFACTS_ZIP_URL, "companyfacts.zip")
    if not path:
        return {"error": "Não foi possível descarregar companyfacts.zip"}

    recolha_id = str(uuid.uuid4())
    try:
        from elasticsearch.helpers import bulk
        actions = []
        total = 0
        for fact in _parse_companyfacts_bulk(path, limit=limit):
            fact_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{fact['cik']}-{fact['concept']}-{fact['end']}-{fact.get('form', '')}")[:64]
            actions.append({
                "_op_type": "index",
                "_index": SEC_FACTS_INDEX,
                "_id": fact_id,
                "_source": {
                    **fact,
                    "indexed_at": _now(),
                    "autor_id": user_id,
                    "source": "bulk_companyfacts",
                },
            })
            total += 1
            if len(actions) >= 5000:
                bulk(es, actions, raise_on_error=False, refresh=False)
                actions = []
        if actions:
            bulk(es, actions, raise_on_error=False, refresh=False)
        try:
            es.indices.refresh(index=SEC_FACTS_INDEX)
        except Exception:
            pass
        run_doc = {
            "id": recolha_id,
            "fonte": "sec_bulk_companyfacts",
            "url": COMPANYFACTS_ZIP_URL,
            "data": _now(),
            "total_docs": total,
            "autor_id": user_id,
            "parametros": {"limit": limit},
        }
        try:
            es.index(index=SEC_RECOLHAS_INDEX, id=recolha_id, body=run_doc)
        except Exception as exc:
            logger.warning("Falha ao registar recolha bulk companyfacts: %s", exc)
        return {"recolha_id": recolha_id, "indexed": total}
    except Exception as exc:
        return {"error": f"Falha ao indexar companyfacts: {exc}", "indexed": 0}


def bulk_download_companyfacts_limited(limit: int = 1000, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper for testing with a limit."""
    return bulk_download_companyfacts(user_id=user_id, limit=limit)


def bulk_ingest_both(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Run both bulk downloads in sequence."""
    submissions = bulk_download_submissions(user_id=user_id)
    companyfacts = bulk_download_companyfacts(user_id=user_id)
    return {
        "submissions": submissions,
        "companyfacts": companyfacts,
    }


def bulk_ingest_both_limited(limit: int = 1000, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Run both bulk downloads in sequence, limiting the number of records for testing."""
    submissions = bulk_download_submissions_limited(limit=limit, user_id=user_id)
    companyfacts = bulk_download_companyfacts_limited(limit=limit, user_id=user_id)
    return {
        "submissions": submissions,
        "companyfacts": companyfacts,
    }


def bulk_status() -> Dict[str, Any]:
    """Report the presence and size of locally cached bulk ZIP files."""
    status: Dict[str, Any] = {"dir": str(BULK_DIR)}
    for key, filename in (("submissions", "submissions.zip"), ("companyfacts", "companyfacts.zip")):
        path = BULK_DIR / filename
        if path.exists():
            status[key] = {"exists": True, "size_bytes": path.stat().st_size, "size_mb": round(path.stat().st_size / (1024 * 1024), 2)}
        else:
            status[key] = {"exists": False}
    return status


# ---------------------------------------------------------------------------
# Pesquisa e análise
# ---------------------------------------------------------------------------

def search_filings(
    q: Optional[str] = None,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
    cik: Optional[str] = None,
    year: Optional[int] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    """Pesquisa nos filings indexados."""
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters: List[Dict[str, Any]] = []
    if q:
        query["bool"]["must"] = [
            {
                "multi_match": {
                    "query": q,
                    "fields": ["company_name^3", "ticker^2", "form", "description", "text"],
                    "operator": "and",
                }
            }
        ]
    if ticker:
        filters.append({"term": {"ticker": ticker.upper()}})
    if form:
        filters.append({"term": {"form": form}})
    if cik:
        filters.append({"term": {"cik": cik.zfill(10)}})
    if year:
        filters.append({"prefix": {"date": str(year)}})
    if filters:
        query["bool"]["filter"] = filters

    return _search_index(
        SEC_FILINGS_INDEX,
        {"query": query, "sort": [{"date": {"order": "desc"}}]},
        q=q,
        size=size,
        from_=from_,
    )


def search_facts(
    q: Optional[str] = None,
    ticker: Optional[str] = None,
    form: Optional[str] = None,
    category: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    """Pesquisa em factos extraídos dos filings."""
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters: List[Dict[str, Any]] = []
    if q:
        query["bool"]["must"] = [
            {
                "multi_match": {
                    "query": q,
                    "fields": ["text^2", "company_name", "ticker", "form"],
                    "operator": "and",
                }
            }
        ]
    if ticker:
        filters.append({"term": {"ticker": ticker.upper()}})
    if form:
        filters.append({"term": {"form": form}})
    if category:
        filters.append({"term": {"category": category}})
    if filters:
        query["bool"]["filter"] = filters

    return _search_index(
        SEC_FACTS_INDEX,
        {"query": query, "sort": [{"date": {"order": "desc"}}]},
        q=q,
        size=size,
        from_=from_,
    )


def filing_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    """Devolve um filing indexado pelo ID do Elasticsearch."""
    return _es_doc(SEC_FILINGS_INDEX, doc_id)


def analytics() -> Dict[str, Any]:
    """Agregações simples por tipo de form e ano."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = es.search(
            index=SEC_FILINGS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_form": {"terms": {"field": "form", "size": 20}},
                    "by_year": {
                        "date_histogram": {
                            "field": "date",
                            "calendar_interval": "year",
                            "format": "yyyy",
                            "min_doc_count": 1,
                        }
                    },
                    "by_ticker": {"terms": {"field": "ticker", "size": 20}},
                },
            },
        )
        return {
            "by_form": [
                {"value": b["key"], "count": b["doc_count"]}
                for b in resp["aggregations"]["by_form"]["buckets"]
            ],
            "by_year": [
                {"value": b["key_as_string"], "count": b["doc_count"]}
                for b in resp["aggregations"]["by_year"]["buckets"]
            ],
            "by_ticker": [
                {"value": b["key"], "count": b["doc_count"]}
                for b in resp["aggregations"]["by_ticker"]["buckets"]
            ],
        }
    except Exception as exc:
        return {"error": f"Falha nas agregações: {exc}"}


def meta() -> Dict[str, Any]:
    """Metadados e status do módulo SEC."""
    es = _garantir_indices()
    status: Dict[str, Any] = {"indices": {}}
    if es:
        for name in (SEC_FILINGS_INDEX, SEC_FACTS_INDEX, SEC_RECOLHAS_INDEX):
            try:
                status["indices"][name] = (
                    es.indices.stats(index=name)
                    .get("indices", {})
                    .get(name, {})
                    .get("total", {})
                    .get("docs", {})
                )
            except Exception:
                status["indices"][name] = {"count": 0}
    return {
        "modulo": "sec",
        "versao": "1.0.0",
        "fonte": "U.S. Securities and Exchange Commission (SEC) EDGAR",
        "url": "https://www.sec.gov/edgar",
        "user_agent": _SEC_USER_AGENT,
        "status": status,
    }
