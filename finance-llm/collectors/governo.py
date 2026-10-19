"""Recolha das nomeações e da composição do Governo (portugal.gov.pt).

Usa o **motor de recolha do IQ OS** (`api.scraper_service`) para descarregar as
páginas e guarda o resultado em **JSON**, **JSONL** e **Elasticsearch**.

Fontes
------
* ``/gc24/governo/nomeacoes`` — índice das áreas de governo. Cada área tem uma
  página própria (ex.: ``/gc24/governo/nomeacoes/financas``) com uma tabela por
  membro do Governo: função, nome, rendimento bruto/líquido, data de nomeação e
  publicação em Diário da República.
* ``/gc24/governo/composicao?gc_timeline=YYYY-MM-DD`` — membros do Governo em
  funções nessa data (Primeiro-Ministro, ministros e secretários de Estado). A
  lista é renderizada no browser, pelo que usa o *fetcher* ``dynamic`` e espera
  pelo seletor dos cartões.

Saídas
------
* ``data/governo/governo_nomeacoes.json`` — payload completo (áreas, membros e
  nomeações), incluindo metadados e estatísticas.
* ``data/governo/governo_nomeacoes.jsonl`` — uma nomeação por linha.
* ``data/governo/governo_composicao.json`` — membros da composição.
* Elasticsearch:
  - ``finance_governo_nomeacoes`` — uma nomeação por documento;
  - ``finance_governo_composicao`` — um membro do Governo por documento;
  - ``finance_scraped`` — os mesmos registos, para aparecerem na pesquisa do
    módulo de recolha (``source_id`` ``governo-nomeacoes``/``governo-composicao``).

Uso::

    python -m collectors.governo
    python -m collectors.governo --no-elastic
    python -m collectors.governo --areas financas,saude --no-composicao
    python -m collectors.governo --timeline 2025-06-05 --delay 0.8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE_URL = "https://portugal.gov.pt"
NOMEACOES_PATH = "/gc24/governo/nomeacoes"
COMPOSICAO_PATH = "/gc24/governo/composicao"
DEFAULT_TIMELINE = "2025-06-05"

SINK_DIR = ROOT / "data" / "governo"
DEFAULT_JSON = SINK_DIR / "governo_nomeacoes.json"
DEFAULT_JSONL = SINK_DIR / "governo_nomeacoes.jsonl"
COMPOSICAO_JSON = SINK_DIR / "governo_composicao.json"

INDEX_NOMEACOES = "finance_governo_nomeacoes"
INDEX_COMPOSICAO = "finance_governo_composicao"
SOURCE_NOMEACOES = "governo-nomeacoes"
SOURCE_COMPOSICAO = "governo-composicao"
SOURCE_NAME = "Governo de Portugal — nomeações e composição"

logger = logging.getLogger("governo")

#: Cartões da composição (componente de pesquisa do portal).
COMPOSITION_WAIT_SELECTOR = ".search-composite-group .govinfo"


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _absolute(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return BASE_URL + ("" if url.startswith("/") else "/") + url


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _parse_eur(value: str) -> Optional[float]:
    """Converte «5 144,36 €» em ``5144.36``."""
    text = re.sub(r"[^\d,.-]", "", str(value or ""))
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: str) -> Optional[str]:
    """Converte ``dd/mm/aaaa`` (ou ISO) em ``aaaa-mm-dd``."""
    text = str(value or "").strip()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def _clean_name(value: str) -> tuple[str, bool]:
    """Remove a nota «(1)» do nome e diz se os encargos são do serviço de origem."""
    text = " ".join(str(value or "").split())
    noted = bool(re.search(r"\s*\(1\)\s*$", text))
    return re.sub(r"\s*\(1\)\s*$", "", text).strip(), noted


def _stable_id(*parts: Any) -> str:
    raw = "::".join(str(p or "") for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _text(node: Any) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


# ---------------------------------------------------------------------------
# Descarregamento (motor de recolha do IQ OS)
# ---------------------------------------------------------------------------
def fetch_http(url: str, *, timeout: int = 45) -> str:
    """Descarrega uma página com o *fetcher* HTTP do módulo de recolha."""
    from api import scraper_service as scraper

    options = {"impersonate": "chrome", "timeout": timeout}
    with scraper._open_session("http", options) as session:
        page = scraper._session_fetch(session, "http", url, options)
        return page.html_content


def fetch_dynamic(url: str, *, wait_selector: str, timeout: int = 90) -> str:
    """Descarrega uma página renderizada no browser (conteúdo JavaScript)."""
    from api import scraper_service as scraper

    options = {"headless": True, "network_idle": True, "timeout": timeout}
    with scraper._open_session("dynamic", options) as session:
        page = session.fetch(
            url,
            wait_selector=wait_selector,
            wait_selector_state="attached",
            wait=1500,
            timeout=timeout * 1000,
        )
        return page.html_content


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_area_links(html: str, *, source_url: str = "") -> List[Dict[str, str]]:
    """Lê o índice de nomeações: título, descrição e URL de cada área."""
    soup = BeautifulSoup(html, "html.parser")
    areas: List[Dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select('a.navigation-link[href*="/governo/nomeacoes/"]'):
        href = str(anchor.get("href") or "").strip()
        if not href or "legislacao-aplicavel" in href or href in seen:
            continue
        seen.add(href)
        item = anchor.find_parent("li")
        title = _text(item.select_one(".navigation-title")) if item else ""
        subtitle = _text(item.select_one(".navigation-subtitle")) if item else ""
        url = _absolute(href)
        areas.append(
            {
                "area": title or _slug_from_url(url).replace("-", " ").title(),
                "area_slug": _slug_from_url(url),
                "descricao": subtitle,
                "url": url,
            }
        )
    return areas


def parse_nomeacoes(
    html: str,
    *,
    area: str,
    area_slug: str,
    source_url: str,
) -> List[Dict[str, Any]]:
    """Extrai as linhas das tabelas de uma página de área.

    Cada tabela pertence a um membro do Governo (o título imediatamente antes)
    e tem as colunas: função, nome, rendimento bruto, rendimento líquido, data
    de nomeação e publicação em DRE.
    """
    soup = BeautifulSoup(html, "html.parser")
    records: List[Dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for table in soup.find_all("table"):
        heading = table.find_previous(["h2", "h3", "h4"])
        membro = _text(heading)
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 6:
                continue
            nome, encargos = _clean_name(_text(cells[1]))
            if not nome:
                continue
            link = cells[5].find("a")
            funcao = _text(cells[0])
            dre_url = _absolute(str(link.get("href") or "")) if link else ""
            key = (membro, funcao, nome, _text(cells[4]), dre_url)
            if key in seen:
                # A página repete por vezes a mesma linha em dois blocos.
                continue
            seen.add(key)
            records.append(
                {
                    "area": area,
                    "area_slug": area_slug,
                    "membro": membro,
                    "funcao": funcao,
                    "nome": nome,
                    "rendimento_bruto": _text(cells[2]),
                    "rendimento_liquido": _text(cells[3]),
                    "rendimento_bruto_eur": _parse_eur(_text(cells[2])),
                    "rendimento_liquido_eur": _parse_eur(_text(cells[3])),
                    "data_nomeacao": _parse_date(_text(cells[4])),
                    "data_nomeacao_texto": _text(cells[4]),
                    "dre_publicacao": _text(cells[5]),
                    "dre_url": dre_url,
                    "encargos_servico_origem": encargos,
                    "url": source_url,
                }
            )
    return records


def parse_composicao(html: str, *, source_url: str) -> List[Dict[str, Any]]:
    """Extrai os cartões da composição do Governo (grupo, nome, cargo, período)."""
    soup = BeautifulSoup(html, "html.parser")
    members: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for group in soup.select(".search-composite-group"):
        group_name = _text(group.select_one(".group-heading .template-name")) or "Membros do Governo"
        for item in group.select(".item"):
            anchor = item.select_one("a[href]")
            url = _absolute(str(anchor.get("href") or "")) if anchor else ""
            image = item.select_one("img")
            nome = _text(item.select_one(".govtype")) or (str(image.get("alt") or "") if image else "")
            cargo = _text(item.select_one("h4.title"))
            if not nome or not cargo:
                continue
            key = f"{nome}|{cargo}|{url}"
            if key in seen:
                continue
            seen.add(key)
            times = item.select(".period time")
            periodos = [str(t.get("datetime") or "") for t in times]
            sec_link = item.select_one(".secretaries-count a")
            sec_text = _text(sec_link)
            count_match = re.search(r"\((\d+)\)", sec_text)
            area_slug = ""
            parts = [p for p in url.split("/") if p]
            if "area-de-governo" in parts:
                idx = parts.index("area-de-governo")
                if idx + 1 < len(parts):
                    area_slug = parts[idx + 1]
            members.append(
                {
                    "grupo": group_name,
                    "nome": nome,
                    "cargo": cargo,
                    "area_slug": area_slug,
                    "url": url,
                    "foto": _absolute(str(image.get("src") or "")) if image else "",
                    "periodo_inicio": _parse_date(periodos[0]) if periodos else None,
                    "periodo_fim": _parse_date(periodos[1]) if len(periodos) > 1 else None,
                    "secretarios_count": int(count_match.group(1)) if count_match else None,
                    "secretarios_url": _absolute(str(sec_link.get("href") or "")) if sec_link else "",
                    "url_fonte": source_url,
                }
            )
    return members


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def collect(
    *,
    timeline: str = DEFAULT_TIMELINE,
    areas_filter: Optional[Iterable[str]] = None,
    include_composicao: bool = True,
    delay: float = 0.5,
    nomeacoes_url: str = BASE_URL + NOMEACOES_PATH,
    composicao_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Recolhe as áreas, as nomeações e (opcionalmente) a composição."""
    timeline = (timeline or DEFAULT_TIMELINE).strip()
    chosen = {a.strip().lower() for a in (areas_filter or []) if str(a).strip()}
    area_html = fetch_dynamic(nomeacoes_url, wait_selector='a.navigation-link[href*="/governo/nomeacoes/"]')
    areas = parse_area_links(area_html, source_url=nomeacoes_url)
    if chosen:
        areas = [a for a in areas if a["area_slug"].lower() in chosen]
    if not areas:
        raise RuntimeError("Não foi possível encontrar áreas de governo na página de nomeações.")

    nomeacoes: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for index, area in enumerate(areas):
        if index:
            time.sleep(max(0.0, delay))
        try:
            html = fetch_http(area["url"])
            rows = parse_nomeacoes(
                html,
                area=area["area"],
                area_slug=area["area_slug"],
                source_url=area["url"],
            )
            nomeacoes.extend(rows)
            logger.info("Nomeações %s: %s linhas", area["area_slug"], len(rows))
        except Exception as exc:  # noqa: BLE001 — uma área falhada não trava as outras
            logger.warning("Falha em %s: %s", area["url"], exc)
            errors.append({"area_slug": area["area_slug"], "url": area["url"], "erro": str(exc)})

    members: List[Dict[str, Any]] = []
    comp_url = composicao_url or f"{BASE_URL}{COMPOSICAO_PATH}?gc_timeline={timeline}"
    if include_composicao:
        try:
            html = fetch_dynamic(comp_url, wait_selector=COMPOSITION_WAIT_SELECTOR)
            members = parse_composicao(html, source_url=comp_url)
            logger.info("Composição: %s membros", len(members))
        except Exception as exc:  # noqa: BLE001 — a composição é complementar
            logger.warning("Falha na composição (%s): %s", comp_url, exc)
            errors.append({"area_slug": "composicao", "url": comp_url, "erro": str(exc)})

    return {
        "generated_at": _now(),
        "governo": "XXIV Governo Constitucional",
        "timeline": timeline,
        "fontes": {"nomeacoes": nomeacoes_url, "composicao": comp_url},
        "areas": areas,
        "membros": members,
        "nomeacoes": nomeacoes,
        "stats": {
            "areas": len(areas),
            "membros": len(members),
            "nomeacoes": len(nomeacoes),
            "membros_por_grupo": _count_by(members, "grupo"),
            "nomeacoes_por_area": _count_by(nomeacoes, "area_slug"),
            "erros": errors,
        },
    }


def _count_by(items: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Escrita em ficheiro
# ---------------------------------------------------------------------------
def write_outputs(
    payload: Dict[str, Any],
    *,
    json_path: Path = DEFAULT_JSON,
    jsonl_path: Path = DEFAULT_JSONL,
    composicao_path: Path = COMPOSICAO_JSON,
) -> Dict[str, str]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    written = 0
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in payload.get("nomeacoes", []):
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    composicao_path.parent.mkdir(parents=True, exist_ok=True)
    composicao_path.write_text(
        json.dumps(payload.get("membros", []), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "json": str(json_path),
        "jsonl": str(jsonl_path),
        "composicao": str(composicao_path),
        "jsonl_registos": str(written),
    }


# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------
NOMEACOES_MAPPING: Dict[str, Any] = {
    "dynamic": True,
    "properties": {
        "item_id": {"type": "keyword"},
        "source_id": {"type": "keyword"},
        "source_name": {"type": "keyword"},
        "run_id": {"type": "keyword"},
        "area": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "area_slug": {"type": "keyword"},
        "membro": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "funcao": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "rendimento_bruto": {"type": "keyword"},
        "rendimento_liquido": {"type": "keyword"},
        "rendimento_bruto_eur": {"type": "double"},
        "rendimento_liquido_eur": {"type": "double"},
        "data_nomeacao": {"type": "date"},
        "data_nomeacao_texto": {"type": "keyword"},
        "dre_publicacao": {"type": "keyword"},
        "dre_url": {"type": "keyword"},
        "encargos_servico_origem": {"type": "boolean"},
        "url": {"type": "keyword"},
        "scraped_at": {"type": "date"},
    },
}

COMPOSICAO_MAPPING: Dict[str, Any] = {
    "dynamic": True,
    "properties": {
        "item_id": {"type": "keyword"},
        "source_id": {"type": "keyword"},
        "source_name": {"type": "keyword"},
        "run_id": {"type": "keyword"},
        "grupo": {"type": "keyword"},
        "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "cargo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "area_slug": {"type": "keyword"},
        "url": {"type": "keyword"},
        "foto": {"type": "keyword"},
        "periodo_inicio": {"type": "date"},
        "periodo_fim": {"type": "date"},
        "secretarios_count": {"type": "integer"},
        "secretarios_url": {"type": "keyword"},
        "url_fonte": {"type": "keyword"},
        "scraped_at": {"type": "date"},
    },
}


def _ensure_index(client: Any, index: str, mapping: Dict[str, Any]) -> None:
    if not client.indices.exists(index=index):
        client.indices.create(
            index=index,
            settings={"number_of_shards": 1, "number_of_replicas": 0},
            mappings=mapping,
        )


def _nomeacao_doc(record: Dict[str, Any], run_id: str, scraped_at: str) -> Dict[str, Any]:
    item_id = f"{SOURCE_NOMEACOES}:{_stable_id(record.get('area_slug'), record.get('membro'), record.get('funcao'), record.get('nome'), record.get('data_nomeacao'), record.get('dre_url'))}"
    return {
        **record,
        "item_id": item_id,
        "source_id": SOURCE_NOMEACOES,
        "source_name": SOURCE_NAME,
        "run_id": run_id,
        "scraped_at": scraped_at,
    }


def _composicao_doc(record: Dict[str, Any], run_id: str, scraped_at: str) -> Dict[str, Any]:
    item_id = f"{SOURCE_COMPOSICAO}:{_stable_id(record.get('nome'), record.get('cargo'), record.get('periodo_inicio'))}"
    return {
        **record,
        "item_id": item_id,
        "source_id": SOURCE_COMPOSICAO,
        "source_name": SOURCE_NAME,
        "run_id": run_id,
        "scraped_at": scraped_at,
    }


def _bulk(client: Any, index: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from elasticsearch.helpers import bulk

    actions = [{"_index": index, "_id": doc["item_id"], "_source": doc} for doc in docs]
    if not actions:
        return {"indexed_count": 0, "error_count": 0}
    success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
    error_list = errors if isinstance(errors, list) else []
    return {
        "indexed_count": int(success),
        "error_count": len(error_list),
        "errors": [str(error)[:300] for error in error_list[:5]],
    }


def index_payload(payload: Dict[str, Any], *, include_scraped: bool = True) -> Dict[str, Any]:
    """Indexa as nomeações e a composição nos índices dedicados e no `finance_scraped`."""
    from api.elasticsearch_client import ensure_indices, get_es_client, index_scraped_items

    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    scraped_at = payload.get("generated_at") or _now()

    nomeacoes = [_nomeacao_doc(row, run_id, scraped_at) for row in payload.get("nomeacoes", [])]
    membros = [_composicao_doc(row, run_id, scraped_at) for row in payload.get("membros", [])]

    _ensure_index(client, INDEX_NOMEACOES, NOMEACOES_MAPPING)
    _ensure_index(client, INDEX_COMPOSICAO, COMPOSICAO_MAPPING)

    result: Dict[str, Any] = {
        "run_id": run_id,
        "nomeacoes": _bulk(client, INDEX_NOMEACOES, nomeacoes),
        "composicao": _bulk(client, INDEX_COMPOSICAO, membros),
    }
    if include_scraped:
        result["scraped_nomeacoes"] = index_scraped_items(
            SOURCE_NOMEACOES,
            SOURCE_NAME,
            run_id,
            [
                {
                    "item_id": doc["item_id"],
                    "title": f"{doc.get('nome', '')} — {doc.get('funcao', '')}".strip(" —"),
                    "summary": f"{doc.get('membro', '')} · {doc.get('area', '')}".strip(" ·"),
                    "url": doc.get("dre_url") or doc.get("url", ""),
                    "tags": ["governo", "nomeacoes", "politica"],
                    "data": doc,
                    "scraped_at": scraped_at,
                }
                for doc in nomeacoes
            ],
            trigger="script",
            es=client,
        )
        result["scraped_composicao"] = index_scraped_items(
            SOURCE_COMPOSICAO,
            SOURCE_NAME,
            run_id,
            [
                {
                    "item_id": doc["item_id"],
                    "title": f"{doc.get('nome', '')} — {doc.get('cargo', '')}".strip(" —"),
                    "summary": doc.get("grupo", ""),
                    "url": doc.get("url", ""),
                    "tags": ["governo", "composicao", "politica"],
                    "data": doc,
                    "scraped_at": scraped_at,
                }
                for doc in membros
            ],
            trigger="script",
            es=client,
        )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Recolha das nomeações e da composição do Governo.")
    parser.add_argument("--timeline", default=DEFAULT_TIMELINE, help="Data da composição (aaaa-mm-dd).")
    parser.add_argument("--areas", default="", help="Áreas a recolher (lista separada por vírgulas); vazio = todas.")
    parser.add_argument("--no-composicao", action="store_true", help="Não recolher a composição do Governo.")
    parser.add_argument("--delay", type=float, default=0.5, help="Pausa entre páginas de áreas (segundos).")
    parser.add_argument("--out", default=str(DEFAULT_JSON), help="Ficheiro JSON de saída.")
    parser.add_argument("--no-elastic", action="store_true", help="Não indexar no Elasticsearch.")
    parser.add_argument("--no-scraped", action="store_true", help="Não indexar também em finance_scraped.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    areas_filter = [a for a in args.areas.split(",") if a.strip()]
    payload = collect(
        timeline=args.timeline,
        areas_filter=areas_filter,
        include_composicao=not args.no_composicao,
        delay=args.delay,
    )
    if not payload.get("nomeacoes") and not payload.get("membros"):
        logger.warning("Sem dados recolhidos.")
        return 1

    out = Path(args.out)
    paths = write_outputs(
        payload,
        json_path=out,
        jsonl_path=out.with_suffix(".jsonl"),
        composicao_path=out.parent / "governo_composicao.json",
    )
    logger.info(
        "Gravado: %s nomeações, %s membros (%s, %s, %s)",
        payload["stats"]["nomeacoes"],
        payload["stats"]["membros"],
        paths["json"],
        paths["jsonl"],
        paths["composicao"],
    )

    if not args.no_elastic:
        try:
            result = index_payload(payload, include_scraped=not args.no_scraped)
            logger.info(
                "Elasticsearch: nomeações=%s, composição=%s (%s, %s)",
                result.get("nomeacoes", {}).get("indexed_count", 0),
                result.get("composicao", {}).get("indexed_count", 0),
                INDEX_NOMEACOES,
                INDEX_COMPOSICAO,
            )
        except Exception as exc:  # noqa: BLE001 — os ficheiros já estão gravados
            logger.error("Indexação no Elasticsearch falhou: %s", exc)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
