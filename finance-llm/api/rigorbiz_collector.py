"""Recolha total de empresas do diretório Rigorbiz.

O site da Rigorbiz expõe resultados de pesquisa via POST
``procurar-empresas/_empresas_procurar_get_list.php`` em HTML paginado
(10 itens por página). Este módulo percorre **todas** as páginas disponíveis,
respeitando limites de velocidade, guarda checkpoint e pode retomar de onde
parou.

Exporta para:
- ``data/rigorbiz/rigorbiz_empresas.json`` (array, útil para leitura humana)
- ``data/rigorbiz/rigorbiz_empresas.jsonl`` (linhas, usado para indexação)
- ``data/rigorbiz/rigorbiz_collector_state.json`` (checkpoint com última página)
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.rigorbiz.pt"
SEARCH_PAGE = f"{BASE_URL}/procurar-empresas/"
LIST_ENDPOINT = f"{BASE_URL}/procurar-empresas/_empresas_procurar_get_list.php"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "rigorbiz"
JSON_PATH = DATA_DIR / "rigorbiz_empresas.json"
JSONL_PATH = DATA_DIR / "rigorbiz_empresas.jsonl"
CHECKPOINT_PATH = DATA_DIR / "rigorbiz_collector_state.json"

DEFAULT_DELAY = 4.0  # segundos entre páginas (evita 429)
PAGE_SIZE = 10
MAX_RETRIES = 5
RETRY_BACKOFF = 15.0  # segundos adicionais após erro 429

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]

_HEADERS = {
    "User-Agent": _USER_AGENTS[0],
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE_URL,
    "Referer": SEARCH_PAGE,
}


class RigorbizCollector:
    """Cliente de recolha paginada do diretório Rigorbiz."""

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        session: Optional[requests.Session] = None,
        rotate_user_agent: bool = True,
    ):
        self.delay = max(0.3, float(delay))
        self.rotate_user_agent = rotate_user_agent
        self.session = session or requests.Session()
        self.session.headers.update(self._headers())
        # Pedido inicial para obter cookies (PHPSESSID, js_verified, csrf_token)
        self._warmup()

    def _headers(self) -> Dict[str, str]:
        headers = dict(_HEADERS)
        if self.rotate_user_agent:
            headers["User-Agent"] = random.choice(_USER_AGENTS)
        return headers

    def _warmup(self) -> None:
        try:
            resp = self.session.get(SEARCH_PAGE, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Aviso: warmup Rigorbiz falhou (%s). A continuar mesmo assim.", exc)

    def _parse_list_html(self, html: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        soup = BeautifulSoup(html, "html.parser")
        items: List[Dict[str, Any]] = []
        for li in soup.select("li.clearfix.follow-company"):
            a = li.select_one("h3.name a")
            name = a.get_text(strip=True) if a else ""
            path = a.get("href", "") if a else ""
            nif_el = li.select_one("p.regno")
            nif = nif_el.get_text(strip=True) if nif_el else ""
            desc_el = li.select_one("p.desc")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            loc_el = li.select_one("p.location")
            location = ""
            if loc_el:
                location = loc_el.get_text(" ", strip=True).replace("\xa0", " ")
                location = re.sub(r"\s+", " ", location)
            cae_match = re.search(r"(\d{4,5})\s*-\s*(.+)", desc)
            items.append(
                {
                    "name": name,
                    "nif": nif,
                    "cae_code": cae_match.group(1) if cae_match else "",
                    "cae_description": cae_match.group(2).strip() if cae_match else desc,
                    "location": location,
                    "path": path,
                    "source": "rigorbiz",
                    "source_url": BASE_URL + path if path else "",
                }
            )
        footer = soup.select_one(".search-results-footer")
        total: Optional[int] = None
        if footer and footer.has_attr("data-totalrows"):
            try:
                total = int(footer["data-totalrows"])
            except ValueError:
                pass
        return items, total

    def fetch_page(self, page: int, query: str = "") -> Tuple[List[Dict[str, Any]], Optional[int]]:
        body = {
            "ksearch": query,
            "ft_localizacao": "",
            "ft_cae": "",
            "ft_const_dt_ini": "",
            "ft_const_dt_fim": "",
            "ft_insol_dt_ini": "",
            "ft_insol_dt_fim": "",
            "ft_insol_tipo": "",
            "ft_vigilancias": "",
            "ft_situacao": "",
            "page": max(1, int(page)),
            "sort_fld": 1,
            "sort_dir": 1,
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self.rotate_user_agent:
                    self.session.headers.update({"User-Agent": random.choice(_USER_AGENTS)})
                resp = self.session.post(LIST_ENDPOINT, data=body, timeout=30)
                resp.raise_for_status()
                return self._parse_list_html(resp.text)
            except Exception as exc:
                status_429 = hasattr(exc, "response") and getattr(exc.response, "status_code", None) == 429
                logger.warning("Erro página %s (tentativa %s/%s): %s", page, attempt, MAX_RETRIES, exc)
                if attempt == MAX_RETRIES:
                    raise
                wait = RETRY_BACKOFF * attempt + (random.uniform(2, 8) if status_429 else 0)
                logger.info("Aguardar %.1fs antes de retentar...", wait)
                time.sleep(wait)
        return [], None  # nunca atingido, mas mantém type checker feliz

    def fetch_all(
        self,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        query: str = "",
        on_page: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """Percorre todas as páginas até esgotar resultados ou atingir ``max_pages``.

        ``on_page`` é chamado a cada página com ``(page, items, total, accumulated)``.
        """
        results: List[Dict[str, Any]] = []
        total: Optional[int] = None
        page = max(1, int(start_page))
        while True:
            if max_pages is not None and page >= start_page + max_pages:
                logger.info("Atingido limite de %s páginas", max_pages)
                break
            try:
                items, page_total = self.fetch_page(page, query=query)
            except Exception as exc:
                logger.error("Erro na página %s após %s tentativas: %s", page, MAX_RETRIES, exc)
                break
            if page_total is not None and total is None:
                total = page_total
                logger.info("Total disponível no site: %s", total)
            if not items:
                logger.info("Sem resultados na página %s. A terminar.", page)
                break
            results.extend(items)
            logger.info("Página %s: +%s itens (total acumulado %s)", page, len(items), len(results))
            if on_page:
                try:
                    on_page(page, items, total, len(results))
                except Exception as cb_exc:
                    logger.warning("Callback de página falhou: %s", cb_exc)
            page += 1
            # Pausa com jitter entre páginas para imitar tráfego humano.
            jitter = random.uniform(0.5, 2.0)
            time.sleep(self.delay + jitter)
        return results

    def fetch_sample(
        self,
        max_pages: int = 1000,
        query: str = "",
        start_page: int = 1,
    ) -> List[Dict[str, Any]]:
        """Recolhe ``max_pages`` páginas (10 itens cada)."""
        return self.fetch_all(start_page=start_page, max_pages=max_pages, query=query)


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _existing_nifs() -> set:
    nifs: set = set()
    if JSONL_PATH.exists():
        with JSONL_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if item.get("nif"):
                        nifs.add(item["nif"])
                except json.JSONDecodeError:
                    continue
    return nifs


def _save_results(items: Iterable[Dict[str, Any]], append: bool = True) -> None:
    _ensure_data_dir()
    # Append to JSONL
    mode = "a" if append else "w"
    with JSONL_PATH.open(mode, encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    # Rewrite compact JSON array
    all_items = list(_read_jsonl())
    with JSON_PATH.open("w", encoding="utf-8") as fh:
        json.dump(all_items, fh, ensure_ascii=False, indent=2)


def _read_jsonl() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not JSONL_PATH.exists():
        return items
    with JSONL_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _load_checkpoint() -> Dict[str, Any]:
    if not CHECKPOINT_PATH.exists():
        return {"last_page": 0, "total": None, "completed": False}
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_page": 0, "total": None, "completed": False}


def _save_checkpoint(state: Dict[str, Any]) -> None:
    _ensure_data_dir()
    CHECKPOINT_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_all(
    delay: float = DEFAULT_DELAY,
    query: str = "",
    pages_per_batch: int = 100,
) -> Dict[str, Any]:
    """Recolhe **todas** as empresas, retomando do checkpoint anterior.

    Guarda checkpoint a cada ``pages_per_batch`` páginas para permitir
    interrupção segura e retomada posterior. O processo para ao detetar
    429 persistentes para não ser bloqueado.
    """
    existing = _existing_nifs()
    checkpoint = _load_checkpoint()
    if checkpoint.get("completed"):
        logger.info("Recolha já marcada como concluída (%s itens).", len(existing))
        return {
            "ok": True,
            "collected": 0,
            "unique_total": len(existing),
            "jsonl": str(JSONL_PATH),
            "json": str(JSON_PATH),
            "completed": True,
        }
    last_page = int(checkpoint.get("last_page", 0))
    # Quando parámos por rate-limit, a última página processada com sucesso pode
    # ter sido guardada no checkpoint. Começamos 1 página depois.
    start_page = last_page + 1 if last_page > 0 else 1
    if existing:
        logger.info("A retomar da página %s com %s NIFs já guardados.", start_page, len(existing))

    collector = RigorbizCollector(delay=delay)
    all_items: List[Dict[str, Any]] = []
    total_announced: Optional[int] = checkpoint.get("total")
    consecutive_429 = 0
    max_consecutive_429 = 3

    def on_page(page: int, items: List[Dict[str, Any]], total: Optional[int], accumulated: int) -> None:
        nonlocal total_announced, consecutive_429
        if total is not None:
            total_announced = total
        consecutive_429 = 0
        if page % pages_per_batch == 0:
            _save_checkpoint({"last_page": page, "total": total_announced, "completed": False})
            _save_results(all_items, append=True)
            all_items.clear()

    try:
        items = collector.fetch_all(start_page=start_page, query=query, on_page=on_page)
    except requests.exceptions.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 429:
            consecutive_429 += 1
            logger.error("Rate limit (429) detetado. A parar para não ser bloqueado.")
            if consecutive_429 >= max_consecutive_429:
                raise
        else:
            raise
    all_items.extend(items)
    if all_items:
        _save_results(all_items, append=True)
    unique_total = len(_read_jsonl())
    completed = bool(total_announced and unique_total >= total_announced)
    _save_checkpoint({"last_page": 0 if completed else (start_page + len(items) // PAGE_SIZE), "total": total_announced, "completed": completed})
    return {
        "ok": True,
        "collected": len(items),
        "unique_total": unique_total,
        "total_announced": total_announced,
        "jsonl": str(JSONL_PATH),
        "json": str(JSON_PATH),
        "completed": completed,
    }


def collect_sample(max_pages: int = 1000, delay: float = DEFAULT_DELAY, query: str = "") -> Dict[str, Any]:
    """Recolhe uma amostra e devolve metadados."""
    existing = _existing_nifs()
    collector = RigorbizCollector(delay=delay)
    items = collector.fetch_sample(max_pages=max_pages, query=query)
    new_items = [i for i in items if i.get("nif") and i["nif"] not in existing]
    if new_items:
        _save_results(new_items, append=True)
    return {
        "ok": True,
        "collected": len(new_items),
        "sampled_total": len(items),
        "jsonl": str(JSONL_PATH),
        "json": str(JSON_PATH),
        "unique_total": len(_read_jsonl()),
    }


def get_items(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    items = _read_jsonl()
    if limit:
        return items[:limit]
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if mode == "all":
        result = collect_all(delay=DEFAULT_DELAY)
    else:
        pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
        result = collect_sample(max_pages=pages, delay=DEFAULT_DELAY)
    print(json.dumps(result, ensure_ascii=False, indent=2))
