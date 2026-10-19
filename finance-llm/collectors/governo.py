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

Enriquecimento
--------------
* **DRE** — cada linha tem uma ligação «Despacho» para o Diário da República. O
  detalhe é lido pela API do DRE: título, número, sumário, texto integral,
  data de publicação, emissor, série, páginas e URL do PDF.
* **Perfis oficiais** — a página de cada membro publica a biografia, a
  fotografia e o cargo, extraídos do componente ``OfficialProfile``.

Saídas
------
* ``data/governo/governo_nomeacoes.json`` — payload completo (áreas, membros e
  nomeações), incluindo metadados e estatísticas.
* ``data/governo/governo_nomeacoes.jsonl`` — uma nomeação por linha.
* ``data/governo/governo_composicao.json`` — membros da composição.
* Elasticsearch:
  - ``finance_governo_nomeacoes`` — uma nomeação por documento;
  - ``finance_governo_composicao`` — um membro do Governo por documento;
  - ``finance_governo_ministerios`` — um ministério por documento (titular,
    secretários de Estado e totais);
  - ``finance_scraped`` — os mesmos registos, para aparecerem na pesquisa do
    módulo de recolha (``source_id`` ``governo-*``).

Uso::

    python -m collectors.governo
    python -m collectors.governo --no-elastic
    python -m collectors.governo --areas financas,saude --no-composicao
    python -m collectors.governo --timeline 2025-06-05 --delay 0.8
    python -m collectors.governo --no-dre --no-perfis
    python -m collectors.governo --dre-limit 20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE_URL = "https://portugal.gov.pt"
NOMEACOES_PATH = "/gc24/governo/nomeacoes"
COMPOSICAO_PATH = "/gc24/governo/composicao"
DEFAULT_TIMELINE = "2025-06-05"

#: O portal usa nomes de área diferentes na composição e no índice de
#: nomeações. Normaliza-se para a chave do índice (a que liga as duas fontes).
AREA_SLUG_ALIASES = {
    "ministro-adjunto-e-da-coesao-territorial": "coesao-territorial",
}

SINK_DIR = ROOT / "data" / "governo"
DEFAULT_JSON = SINK_DIR / "governo_nomeacoes.json"
DEFAULT_JSONL = SINK_DIR / "governo_nomeacoes.jsonl"
COMPOSICAO_JSON = SINK_DIR / "governo_composicao.json"

INDEX_NOMEACOES = "finance_governo_nomeacoes"
INDEX_COMPOSICAO = "finance_governo_composicao"
INDEX_MINISTERIOS = "finance_governo_ministerios"
SOURCE_NOMEACOES = "governo-nomeacoes"
SOURCE_COMPOSICAO = "governo-composicao"
SOURCE_MINISTERIOS = "governo-ministerios"
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
# Diário da República (detalhe dos Despachos)
# ---------------------------------------------------------------------------
DRE_MODULE_VERSION_URL = "https://diariodarepublica.pt/dr/moduleservices/moduleversioninfo"
DRE_DETAIL_ACTION = (
    "https://diariodarepublica.pt/dr/screenservices/dr/"
    "Legislacao_Conteudos/Conteudo_Detalhe/DataActionGetAllConteudoDetalheData"
)
#: Versão da API do módulo `dr` (OutSystems). Muda quando o DRE é publicado;
#: o coletor avisa se a resposta vier vazia e a versão pode ser passada por CLI.
DRE_API_VERSION = "B3l5BYZxaLmWUxGR3tmKGw"


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    return " ".join(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True).split())


def _dre_session() -> requests.Session:
    """Sessão para a API do DRE (o token CSRF é comparado com o cookie)."""
    session = requests.Session()
    token = secrets.token_urlsafe(18)
    session.cookies.set(
        "nr2Users",
        f"crf%3d{quote(token, safe='')}%3buid%3d0%3bunm%3d",
        domain="diariodarepublica.pt",
        path="/",
    )
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "OutSystems-Locale": "pt-PT",
            "x-csrftoken": token,
        }
    )
    return session


def _sync_dre_csrf(session: requests.Session) -> None:
    """O DRE roda o token CSRF no cookie `nr2Users`; o cabeçalho tem de o seguir."""
    raw = session.cookies.get("nr2Users") or ""
    match = re.search(r"crf=([^;]+)", unquote(raw))
    if match:
        session.headers["x-csrftoken"] = match.group(1)


def _dre_module_version(session: requests.Session) -> str:
    response = session.get(DRE_MODULE_VERSION_URL, timeout=30)
    response.raise_for_status()
    _sync_dre_csrf(session)
    token = str(response.json().get("versionToken") or "").strip()
    if not token:
        raise RuntimeError("O DRE não devolveu o versionToken do módulo.")
    return token


def fetch_dre_detail(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    module_version: str = "",
    api_version: str = DRE_API_VERSION,
) -> Dict[str, Any]:
    """Lê o detalhe de um Despacho na API do Diário da República."""
    parts = [part for part in url.split("?")[0].rstrip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"URL do DRE inválido: {url!r}")
    tipo, key = parts[-2], parts[-1]
    session = session or _dre_session()
    module_version = module_version or _dre_module_version(session)
    payload = {
        "versionInfo": {"moduleVersion": module_version, "apiVersion": api_version},
        "viewName": "Legislacao_Conteudos.Conteudo_Detalhe",
        "screenData": {
            "variables": {
                "Tipo": tipo,
                "Key": key,
                "_tipoInDataFetchStatus": 1,
                "_keyInDataFetchStatus": 1,
            }
        },
        "clientVariables": {},
    }
    response = session.post(
        DRE_DETAIL_ACTION,
        json=payload,
        timeout=30,
        headers={"Referer": url},
    )
    response.raise_for_status()
    _sync_dre_csrf(session)
    if "application/json" not in str(response.headers.get("content-type") or ""):
        raise RuntimeError("O DRE devolveu HTML em vez de JSON (sessão/CSRF inválidos).")
    data = response.json()
    detail = (data.get("data") or {}).get("DetalheConteudo") or {}
    if not detail or not detail.get("Id"):
        changed = (data.get("versionInfo") or {}).get("hasApiVersionChanged")
        hint = " A versão da API do DRE mudou." if changed else ""
        raise RuntimeError(f"Detalhe vazio devolvido pelo DRE.{hint}")
    return detail


def parse_dre_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza o detalhe do DRE para os campos guardados na nomeação."""
    diario = detail.get("DiarioRepublica") or {}
    return {
        "dre_id": str(detail.get("Id") or ""),
        "dre_titulo": _html_to_text(detail.get("Titulo") or ""),
        "dre_numero": _html_to_text(detail.get("Numero") or ""),
        "dre_publicacao": _html_to_text(detail.get("Publicacao") or ""),
        "dre_sumario": _html_to_text(detail.get("Sumario") or detail.get("Resumo") or ""),
        "dre_texto": _html_to_text(detail.get("Texto") or detail.get("TextoFormatado") or "")[:60000],
        "dre_data_publicacao": _parse_date(detail.get("DataPublicacao") or ""),
        "dre_emissor": _html_to_text(detail.get("Emissor") or ""),
        "dre_serie": _html_to_text(detail.get("Serie") or ""),
        "dre_pagina": _html_to_text(detail.get("Pagina") or ""),
        "dre_pdf_url": str(detail.get("URL_PDF") or "").strip(),
        "dre_diario_pdf_url": str(diario.get("URL_PDF") or "").strip(),
        "dre_tipo": _html_to_text(detail.get("TipoDiploma") or ""),
    }


# ---------------------------------------------------------------------------
# Perfis oficiais (biografias)
# ---------------------------------------------------------------------------
def _norm_name(value: Any) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _find_component(node: Any, name: str) -> Optional[Dict[str, Any]]:
    if isinstance(node, dict):
        if node.get("componentName") == name:
            return node
        for value in node.values():
            found = _find_component(value, name)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_component(value, name)
            if found:
                return found
    return None


def parse_member_profile(html: str, *, preferred_name: str = "") -> Dict[str, Any]:
    """Extrai nome, cargo, biografia e fotografia do perfil oficial.

    Alguns cargos têm histórico (quem passou pelo lugar). Quando a composição
    indica o titular, escolhe-se o item com o mesmo nome; sem correspondência,
    fica o mandato mais recente.
    """
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    component = _find_component(data, "OfficialProfile")
    if not component:
        return {}
    context = (component.get("fields") or {}).get("data", {}).get("contextItem") or {}
    items = (context.get("officialsHistory") or {}).get("targetItems") or []
    # O Primeiro-Ministro publica os dados diretamente no `contextItem`; os
    # ministros e secretários de Estado usam `officialsHistory.targetItems`.
    item = None
    wanted = _norm_name(preferred_name)
    if items and wanted:
        for candidate in items:
            name = (
                ((candidate.get("official") or {}).get("targetItem") or {})
                .get("fullName", {})
                .get("jsonValue", {})
                .get("value")
            )
            if _norm_name(name) == wanted:
                item = candidate
                break
    if item is None and items:
        item = max(
            items,
            key=lambda candidate: str(
                ((candidate.get("startDate") or {}).get("jsonValue") or {}).get("value") or ""
            ),
        )
    if item is None:
        item = context
    bio_html = ((item.get("bio") or {}).get("jsonValue") or {}).get("value") or ""
    photo = ((item.get("bioPhoto") or {}).get("jsonValue") or {}).get("value") or {}
    name = (
        ((item.get("official") or {}).get("targetItem") or {})
        .get("fullName", {})
        .get("jsonValue", {})
        .get("value")
    )
    role = ((item.get("governmentRole") or {}).get("jsonValue") or {}).get("value")
    start = ((item.get("startDate") or {}).get("jsonValue") or {}).get("value")
    end = ((item.get("endDate") or {}).get("jsonValue") or {}).get("value")
    parent = context.get("parent") or {}
    area = (
        ((item.get("governmentTitle") or {}).get("jsonValue") or {}).get("value")
        or ((parent.get("governmentTitle") or {}).get("jsonValue") or {}).get("value")
    )
    return {
        "nome_oficial": _html_to_text(str(name or "")),
        "cargo_oficial": _html_to_text(str(role or "")),
        "area_nome": _html_to_text(str(area or "")),
        "biografia": _html_to_text(bio_html),
        "foto_biografia": str(photo.get("src") or "") if isinstance(photo, dict) else "",
        "perfil_inicio": _parse_date(str(start or "")),
        "perfil_fim": _parse_date(str(end or "")),
    }


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
            area_slug = AREA_SLUG_ALIASES.get(area_slug, area_slug)
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
# Enriquecimento (DRE e perfis oficiais)
# ---------------------------------------------------------------------------
def enrich_nomeacoes(
    records: List[Dict[str, Any]],
    *,
    delay: float = 0.25,
    limit: Optional[int] = None,
    session: Optional[requests.Session] = None,
    module_version: str = "",
    api_version: str = DRE_API_VERSION,
) -> Dict[str, int]:
    """Acrescenta a cada nomeação o detalhe do Despacho publicado no DRE."""
    targets = records[:limit] if limit else records
    if not targets:
        return {"ok": 0, "erros": 0}
    session = session or _dre_session()
    module_version = module_version or _dre_module_version(session)
    cache: Dict[str, Dict[str, Any]] = {}
    ok = erros = 0
    for index, record in enumerate(targets, 1):
        url = str(record.get("dre_url") or "").strip()
        if not url:
            continue
        if url in cache:
            record.update(cache[url])
            ok += 1
            continue
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                fields = parse_dre_detail(
                    fetch_dre_detail(url, session=session, module_version=module_version, api_version=api_version)
                )
                record.pop("dre_erro", None)
                record.update(fields)
                cache[url] = fields
                ok += 1
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 — um despacho falhado não trava os outros
                last_error = exc
                # Timeouts e falhas de ligação são transitórios; uma pausa
                # curta costuma resolver sem repetir toda a recolha.
                time.sleep(1.0 + attempt)
        if last_error is not None:
            record["dre_erro"] = str(last_error)[:300]
            erros += 1
        if index % 50 == 0:
            logger.info("DRE: %s/%s despachos (%s erros)", index, len(targets), erros)
        time.sleep(max(0.0, delay))
    return {"ok": ok, "erros": erros}


def enrich_membros(members: List[Dict[str, Any]], *, delay: float = 0.3) -> Dict[str, int]:
    """Acrescenta a cada membro a biografia e a fotografia do perfil oficial."""
    cache: Dict[str, Dict[str, Any]] = {}
    ok = erros = 0
    for index, member in enumerate(members, 1):
        url = str(member.get("url") or "").split("?")[0]
        if not url:
            continue
        if url in cache:
            member.update(cache[url])
            ok += 1
            continue
        try:
            fields = parse_member_profile(fetch_http(url), preferred_name=str(member.get("nome") or ""))
            if not fields:
                raise RuntimeError("Perfil sem componente OfficialProfile.")
            member.update(fields)
            cache[url] = fields
            ok += 1
        except Exception as exc:  # noqa: BLE001 — um perfil falhado não trava os outros
            member["perfil_erro"] = str(exc)[:300]
            erros += 1
        if index % 20 == 0:
            logger.info("Perfis: %s/%s membros (%s erros)", index, len(members), erros)
        time.sleep(max(0.0, delay))
    return {"ok": ok, "erros": erros}


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def collect(
    *,
    timeline: str = DEFAULT_TIMELINE,
    areas_filter: Optional[Iterable[str]] = None,
    include_composicao: bool = True,
    delay: float = 0.5,
    enrich_dre: bool = True,
    enrich_perfis: bool = True,
    dre_delay: float = 0.25,
    dre_limit: Optional[int] = None,
    perfil_delay: float = 0.3,
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

    dre_stats = {"ok": 0, "erros": 0}
    if enrich_dre and nomeacoes:
        try:
            dre_stats = enrich_nomeacoes(nomeacoes, delay=dre_delay, limit=dre_limit)
            logger.info("DRE: %s detalhes, %s erros", dre_stats["ok"], dre_stats["erros"])
        except Exception as exc:  # noqa: BLE001 — o resto da recolha já está feito
            logger.warning("Enriquecimento DRE falhou: %s", exc)
            errors.append({"area_slug": "dre", "url": DRE_DETAIL_ACTION, "erro": str(exc)})

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

    perfil_stats = {"ok": 0, "erros": 0}
    if enrich_perfis and members:
        try:
            perfil_stats = enrich_membros(members, delay=perfil_delay)
            logger.info("Perfis: %s biografias, %s erros", perfil_stats["ok"], perfil_stats["erros"])
        except Exception as exc:  # noqa: BLE001 — as nomeações já estão recolhidas
            logger.warning("Enriquecimento dos perfis falhou: %s", exc)
            errors.append({"area_slug": "perfis", "url": COMPOSICAO_PATH, "erro": str(exc)})

    ministerios = build_ministerios(areas, members, nomeacoes)
    return {
        "generated_at": _now(),
        "governo": "XXIV Governo Constitucional",
        "timeline": timeline,
        "fontes": {"nomeacoes": nomeacoes_url, "composicao": comp_url},
        "areas": areas,
        "ministerios": ministerios,
        "membros": members,
        "nomeacoes": nomeacoes,
        "stats": {
            "areas": len(areas),
            "ministerios": len(ministerios),
            "membros": len(members),
            "nomeacoes": len(nomeacoes),
            "dre_detalhes": dre_stats["ok"],
            "dre_erros": dre_stats["erros"],
            "perfis": perfil_stats["ok"],
            "perfis_erros": perfil_stats["erros"],
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


def build_ministerios(
    areas: List[Dict[str, Any]],
    members: List[Dict[str, Any]],
    nomeacoes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Consolida cada área de governo num registo de ministério.

    O registo junta o titular, os secretários de Estado, o número de nomeações
    e as ligações oficiais — é a vista «todos os ministérios» do módulo.
    """
    by_area: Dict[str, List[Dict[str, Any]]] = {}
    for member in members:
        slug = AREA_SLUG_ALIASES.get(str(member.get("area_slug") or ""), str(member.get("area_slug") or ""))
        if member.get("grupo") == "Primeiro-Ministro":
            slug = "primeiro-ministro"
        by_area.setdefault(slug, []).append(member)
    totals = _count_by(nomeacoes, "area_slug")

    ministerios: List[Dict[str, Any]] = []
    for area in areas:
        slug = str(area.get("area_slug") or "")
        people = by_area.get(slug, [])
        titular = next(
            (m for m in people if m.get("grupo") in ("Ministros", "Primeiro-Ministro")),
            None,
        )
        secretarios = [m for m in people if m.get("grupo") == "Secretários de Estado"]
        ministerios.append(
            {
                "area": area.get("area", ""),
                "area_slug": slug,
                "descricao": area.get("descricao", ""),
                "tipo": "Primeiro-Ministro" if slug == "primeiro-ministro" else "Ministério",
                "titular": titular.get("nome", "") if titular else "",
                "cargo": titular.get("cargo", "") if titular else "",
                "secretarios_count": len(secretarios),
                "nomeacoes_count": totals.get(slug, 0),
                "url": area.get("url", ""),
                "membros": [
                    {
                        "nome": member.get("nome", ""),
                        "cargo": member.get("cargo", ""),
                        "grupo": member.get("grupo", ""),
                    }
                    for member in ([titular] if titular else []) + secretarios
                ],
            }
        )
    return ministerios


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
        "dre_id": {"type": "keyword"},
        "dre_titulo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "dre_numero": {"type": "keyword"},
        "dre_sumario": {"type": "text"},
        "dre_texto": {"type": "text"},
        "dre_data_publicacao": {"type": "date"},
        "dre_emissor": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "dre_serie": {"type": "keyword"},
        "dre_pagina": {"type": "keyword"},
        "dre_pdf_url": {"type": "keyword"},
        "dre_diario_pdf_url": {"type": "keyword"},
        "dre_tipo": {"type": "keyword"},
        "dre_erro": {"type": "keyword"},
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
        "nome_oficial": {"type": "keyword"},
        "cargo_oficial": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "area_nome": {"type": "keyword"},
        "biografia": {"type": "text"},
        "foto_biografia": {"type": "keyword"},
        "perfil_inicio": {"type": "date"},
        "perfil_fim": {"type": "date"},
        "perfil_erro": {"type": "keyword"},
        "scraped_at": {"type": "date"},
    },
}


MINISTERIOS_MAPPING: Dict[str, Any] = {
    "dynamic": True,
    "properties": {
        "item_id": {"type": "keyword"},
        "source_id": {"type": "keyword"},
        "source_name": {"type": "keyword"},
        "run_id": {"type": "keyword"},
        "area": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "area_slug": {"type": "keyword"},
        "tipo": {"type": "keyword"},
        "titular": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "cargo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
        "secretarios_count": {"type": "integer"},
        "nomeacoes_count": {"type": "integer"},
        "url": {"type": "keyword"},
        "membros": {"type": "flattened"},
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


def _ministerio_doc(record: Dict[str, Any], run_id: str, scraped_at: str) -> Dict[str, Any]:
    item_id = f"{SOURCE_MINISTERIOS}:{_stable_id(record.get('area_slug'))}"
    return {
        **record,
        "item_id": item_id,
        "source_id": SOURCE_MINISTERIOS,
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
    ministerios = [_ministerio_doc(row, run_id, scraped_at) for row in payload.get("ministerios", [])]

    _ensure_index(client, INDEX_NOMEACOES, NOMEACOES_MAPPING)
    _ensure_index(client, INDEX_COMPOSICAO, COMPOSICAO_MAPPING)
    _ensure_index(client, INDEX_MINISTERIOS, MINISTERIOS_MAPPING)

    result: Dict[str, Any] = {
        "run_id": run_id,
        "nomeacoes": _bulk(client, INDEX_NOMEACOES, nomeacoes),
        "composicao": _bulk(client, INDEX_COMPOSICAO, membros),
        "ministerios": _bulk(client, INDEX_MINISTERIOS, ministerios),
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
                    "summary": doc.get("dre_sumario") or f"{doc.get('membro', '')} · {doc.get('area', '')}".strip(" ·"),
                    "text": doc.get("dre_texto", ""),
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
                    "text": doc.get("biografia", ""),
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
        result["scraped_ministerios"] = index_scraped_items(
            SOURCE_MINISTERIOS,
            SOURCE_NAME,
            run_id,
            [
                {
                    "item_id": doc["item_id"],
                    "title": f"{doc.get('area', '')} — {doc.get('titular', '')}".strip(" —"),
                    "summary": f"{doc.get('secretarios_count', 0)} secretários de Estado · {doc.get('nomeacoes_count', 0)} nomeações",
                    "text": doc.get("descricao", ""),
                    "url": doc.get("url", ""),
                    "tags": ["governo", "ministerios", "politica"],
                    "data": doc,
                    "scraped_at": scraped_at,
                }
                for doc in ministerios
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
    parser.add_argument("--no-dre", action="store_true", help="Não enriquecer as nomeações com o detalhe do DRE.")
    parser.add_argument("--no-perfis", action="store_true", help="Não enriquecer os membros com a biografia oficial.")
    parser.add_argument("--delay", type=float, default=0.5, help="Pausa entre páginas de áreas (segundos).")
    parser.add_argument("--dre-delay", type=float, default=0.25, help="Pausa entre pedidos ao DRE (segundos).")
    parser.add_argument("--dre-limit", type=int, default=None, help="Máximo de despachos a enriquecer (testes).")
    parser.add_argument("--perfil-delay", type=float, default=0.3, help="Pausa entre perfis oficiais (segundos).")
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
        enrich_dre=not args.no_dre,
        enrich_perfis=not args.no_perfis,
        dre_delay=args.dre_delay,
        dre_limit=args.dre_limit,
        perfil_delay=args.perfil_delay,
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
        "Gravado: %s nomeações (%s com DRE), %s membros (%s com biografia) em %s, %s, %s",
        payload["stats"]["nomeacoes"],
        payload["stats"]["dre_detalhes"],
        payload["stats"]["membros"],
        payload["stats"]["perfis"],
        paths["json"],
        paths["jsonl"],
        paths["composicao"],
    )

    if not args.no_elastic:
        try:
            result = index_payload(payload, include_scraped=not args.no_scraped)
            logger.info(
                "Elasticsearch: nomeações=%s, composição=%s, ministérios=%s (%s, %s, %s)",
                result.get("nomeacoes", {}).get("indexed_count", 0),
                result.get("composicao", {}).get("indexed_count", 0),
                result.get("ministerios", {}).get("indexed_count", 0),
                INDEX_NOMEACOES,
                INDEX_COMPOSICAO,
                INDEX_MINISTERIOS,
            )
        except Exception as exc:  # noqa: BLE001 — os ficheiros já estão gravados
            logger.error("Indexação no Elasticsearch falhou: %s", exc)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
