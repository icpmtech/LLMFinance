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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
PREFIX_STATE_PATH = DATA_DIR / "rigorbiz_prefix_state.json"

DEFAULT_DELAY = 12.0  # segundos entre páginas (o site bloqueia ritmos altos)
PAGE_SIZE = 10
MAX_RETRIES = 5
RETRY_BACKOFF = 20.0  # segundos adicionais após erro 429
MAX_DELAY = 90.0  # teto do throttle adaptativo

#: O site devolve no máximo 200 resultados por pesquisa (20 páginas de 10).
#: Acima disso a página repete a última — daí a recolha ser particionada por
#: prefixo de nome (`ksearch` é pesquisa por prefixo).
MAX_RESULTS_PER_QUERY = 200
MAX_PAGES_PER_QUERY = MAX_RESULTS_PER_QUERY // PAGE_SIZE

#: Alfabeto dos prefixos. O site procura por prefixo do nome e ignora acentos.
PREFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
#: Primeiros caracteres que aparecem em nomes reais ('!', '#', '&', …).
PREFIX_SEEDS = list(PREFIX_ALPHABET) + ["!", "#", "&", "*", "+", "-", ".", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
#: Profundidade máxima de expansão (prefixo "abc" → "abcd"). Nomes portugueses
#: partilham prefixos longos («ACABAMENTOS…», «SOCIEDADE…»), daí ir até 8.
MAX_PREFIX_DEPTH = 8

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
        self.base_delay = max(0.3, float(delay))
        self.delay = self.base_delay
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
                # Sucesso: alivia o throttle suavemente até ao mínimo configurado.
                self.delay = max(self.base_delay, self.delay * 0.97)
                return self._parse_list_html(resp.text)
            except Exception as exc:
                status_429 = hasattr(exc, "response") and getattr(exc.response, "status_code", None) == 429
                logger.warning("Erro página %s (tentativa %s/%s): %s", page, attempt, MAX_RETRIES, exc)
                if status_429:
                    # O site é sensível ao ritmo: sobe o intervalo entre pedidos.
                    self.delay = min(MAX_DELAY, self.delay * 1.6)
                    # Respiro extra: rajadas depois de um bloqueio voltam a bloquear.
                    time.sleep(random.uniform(20, 45))
                if attempt == MAX_RETRIES:
                    raise
                wait = RETRY_BACKOFF * attempt + (random.uniform(2, 8) if status_429 else 0)
                logger.info("Aguardar %.1fs antes de retentar (delay agora %.1fs)...", wait, self.delay)
                time.sleep(wait)
        return [], None  # nunca atingido, mas mantém type checker feliz

    def fetch_all(
        self,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        query: str = "",
        on_page: Optional[Callable[[int, List[Dict[str, Any]], Optional[int], int], None]] = None,
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
    # Deduplicate JSONL by NIF (keep last occurrence) and rewrite files
    _deduplicate_jsonl()


def _deduplicate_jsonl() -> None:
    """Remove NIFs duplicados do JSONL, mantendo a entrada mais recente."""
    if not JSONL_PATH.exists():
        return
    seen: Dict[str, Dict[str, Any]] = {}
    with JSONL_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            nif = str(item.get("nif") or "").strip()
            if nif:
                seen[nif] = item
    deduped = list(seen.values())
    with JSONL_PATH.open("w", encoding="utf-8") as fh:
        for item in deduped:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    with JSON_PATH.open("w", encoding="utf-8") as fh:
        json.dump(deduped, fh, ensure_ascii=False, indent=2)


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
        # `utf-8-sig` tolera o BOM que alguns editores (PowerShell) acrescentam.
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"last_page": 0, "total": None, "completed": False}


def _save_checkpoint(state: Dict[str, Any]) -> None:
    _ensure_data_dir()
    CHECKPOINT_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_all(
    delay: float = DEFAULT_DELAY,
    query: str = "",
    pages_per_batch: int = 100,
    index_to_es: bool = True,
    index_batch_size: int = 100,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    resume: bool = True,
) -> Dict[str, Any]:
    """Recolhe **todas** as empresas, retomando do checkpoint anterior.

    - O checkpoint é gravado a cada página concluída (barato), pelo que uma
      paragem abrupta nunca repete páginas já lidas.
    - Os itens são gravados/indexados em lotes de ``index_batch_size``.
    - ``should_stop`` permite parar graciosamente (usado pelo runner de UI).
    """
    existing = _existing_nifs()
    checkpoint = _load_checkpoint()
    if resume and checkpoint.get("completed"):
        logger.info("Recolha já marcada como concluída (%s itens).", len(existing))
        return {
            "ok": True,
            "collected": 0,
            "unique_total": len(existing),
            "indexed": 0,
            "jsonl": str(JSONL_PATH),
            "json": str(JSON_PATH),
            "completed": True,
        }
    if resume:
        last_page = int(checkpoint.get("last_page", 0))
        start_page = last_page + 1
    else:
        start_page = 1
    logger.info("A recolher a partir da página %s (%s NIFs já guardados).", start_page, len(existing))

    collector = RigorbizCollector(delay=delay)
    buffer: List[Dict[str, Any]] = []
    total_announced: Optional[int] = checkpoint.get("total")
    indexed_total = 0
    collected_total = 0
    last_page = start_page - 1
    stopped = False

    def _emit(**kwargs) -> None:
        if on_progress:
            try:
                on_progress(kwargs)
            except Exception as cb_exc:
                logger.debug("Progress callback ignorado: %s", cb_exc)

    def _flush() -> None:
        nonlocal indexed_total
        if not buffer:
            return
        if index_to_es:
            try:
                from api.rigorbiz_indexer import index_items
                indexed_total += int(index_items(buffer).get("indexed") or 0)
            except Exception as exc:
                logger.warning("Indexação de lote falhou: %s", exc)
        _save_results(buffer, append=True)
        buffer.clear()

    def on_page(page: int, items: List[Dict[str, Any]], total: Optional[int], accumulated: int) -> bool:
        nonlocal total_announced, collected_total, last_page
        if total is not None:
            total_announced = total
        collected_total += len(items)
        last_page = page
        buffer.extend(items)
        _save_checkpoint({"last_page": page, "total": total_announced, "completed": False})
        if len(buffer) >= index_batch_size:
            _flush()
        _emit(
            kind="page",
            page=page,
            items=len(items),
            collected=collected_total,
            unique_total=len(existing) + collected_total,
            indexed=indexed_total,
            total_announced=total_announced,
        )
        if should_stop and should_stop():
            logger.info("Paragem pedida — a terminar após a página %s.", page)
            return True
        return False

    class _StopRequested(Exception):
        pass

    # Adaptador: `fetch_all` espera um callback opcional; aqui interrompemos
    # levantando uma exceção própria para conservar o progresso já gravado.
    def _page_hook(page: int, items: List[Dict[str, Any]], total: Optional[int], accumulated: int) -> None:
        if on_page(page, items, total, accumulated):
            raise _StopRequested()

    try:
        collector.fetch_all(start_page=start_page, query=query, on_page=_page_hook)
    except _StopRequested:
        stopped = True
    except requests.exceptions.HTTPError as exc:
        if getattr(exc.response, "status_code", None) != 429:
            raise
        logger.error("Rate limit (429) persistente — recolha interrompida para evitar bloqueio.")
        stopped = True
    finally:
        _flush()

    unique_total = len(_read_jsonl())
    completed = bool(total_announced and unique_total >= total_announced)
    if completed:
        _save_checkpoint({"last_page": 0, "total": total_announced, "completed": True})
    _emit(
        kind="done",
        page=last_page,
        indexed=indexed_total,
        collected=collected_total,
        unique_total=unique_total,
        completed=completed,
        stopped=stopped,
        total_announced=total_announced,
    )
    return {
        "ok": True,
        "collected": collected_total,
        "unique_total": unique_total,
        "indexed": indexed_total,
        "total_announced": total_announced,
        "last_page": last_page,
        "stopped": stopped,
        "jsonl": str(JSONL_PATH),
        "json": str(JSON_PATH),
        "completed": completed,
    }


# ---------------------------------------------------------------- prefixos
def _load_prefix_state() -> Dict[str, Any]:
    """Estado da recolha por prefixos (fila, feitos e estatísticas)."""
    if not PREFIX_STATE_PATH.exists():
        return {"queue": list(PREFIX_SEEDS), "done": [], "current": None, "stats": {}}
    try:
        state = json.loads(PREFIX_STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"queue": list(PREFIX_SEEDS), "done": [], "current": None, "stats": {}}
    if not state.get("queue") and not state.get("done"):
        state["queue"] = list(PREFIX_SEEDS)
    return state


def _save_prefix_state(state: Dict[str, Any]) -> None:
    _ensure_data_dir()
    PREFIX_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_by_prefix(
    delay: float = DEFAULT_DELAY,
    index_to_es: bool = True,
    index_batch_size: int = 100,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    max_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Recolhe o diretório inteiro particionando o nome por prefixos.

    O site devolve no máximo 200 resultados por pesquisa, pelo que cada prefixo
    com mais resultados é dividido em prefixos mais longos. A fila fica em
    ``data/rigorbiz/rigorbiz_prefix_state.json``, o que permite retomar sempre
    do mesmo ponto.
    """
    started = time.monotonic()
    state = _load_prefix_state()
    existing = _existing_nifs()
    collector = RigorbizCollector(delay=delay)
    buffer: List[Dict[str, Any]] = []
    collected_total = 0
    indexed_total = 0
    pages_total = 0
    stopped = False
    current: Optional[str] = None
    seen_prefixes = set(state.get("done") or [])

    def _emit(**kwargs) -> None:
        if on_progress:
            try:
                on_progress(kwargs)
            except Exception as exc:  # noqa: BLE001 — o progresso nunca derruba a recolha
                logger.debug("Progress callback ignorado: %s", exc)

    def _flush() -> None:
        nonlocal indexed_total
        if not buffer:
            return
        if index_to_es:
            try:
                from api.rigorbiz_indexer import index_items

                indexed_total += int(index_items(buffer).get("indexed") or 0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Indexação de lote falhou: %s", exc)
        _save_results(buffer, append=True)
        buffer.clear()

    queue: List[str] = list(state.get("queue") or PREFIX_SEEDS)

    while queue:
        if should_stop and should_stop():
            logger.info("Paragem pedida — a guardar a fila (%s prefixos).", len(queue))
            stopped = True
            break
        if max_seconds is not None and (time.monotonic() - started) > max_seconds:
            logger.info("Limite de tempo atingido — a guardar a fila.")
            stopped = True
            break

        prefix = queue.pop(0)
        if prefix in seen_prefixes:
            continue
        current = prefix

        try:
            first_items, total = collector.fetch_page(1, query=prefix)
        except Exception as exc:  # noqa: BLE001 — 429 persistente
            logger.error("Prefixo '%s' falhou (%s); devolvido à fila.", prefix, exc)
            queue.insert(0, prefix)
            _save_prefix_state({"queue": queue, "done": sorted(seen_prefixes), "current": prefix, "stats": {}})
            time.sleep(collector.delay)
            continue

        if total is not None and total > MAX_RESULTS_PER_QUERY and len(prefix) < MAX_PREFIX_DEPTH:
            # Demasiados resultados: divide o prefixo e ignora esta página.
            children = [prefix + ch for ch in PREFIX_ALPHABET]
            queue[:0] = children
            logger.info("Prefixo '%s' tem %s resultados → a dividir em %s sub-prefixos.", prefix, total, len(children))
            _save_prefix_state(
                {"queue": queue, "done": sorted(seen_prefixes), "current": prefix,
                 "stats": {"collected": collected_total, "indexed": indexed_total, "pages": pages_total}}
            )
            _emit(kind="expand", prefix=prefix, total=total, queue=len(queue), collected=collected_total,
                  indexed=indexed_total, unique_total=len(existing) + collected_total)
            continue

        # Prefixo com ≤200 resultados: esgota a paginação (máx. 20 páginas).
        pages = min(MAX_PAGES_PER_QUERY, max(1, ((total or len(first_items)) + PAGE_SIZE - 1) // PAGE_SIZE))
        page_failed = False
        for page in range(1, pages + 1):
            if should_stop and should_stop():
                logger.info("Paragem pedida no prefixo '%s' (página %s).", prefix, page)
                stopped = True
                # O prefixo fica por concluir: volta à fila para retomar depois.
                queue.insert(0, prefix)
                page_failed = True
                break
            try:
                items, page_total = (first_items, total) if page == 1 else collector.fetch_page(page, query=prefix)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Prefixo '%s' página %s falhou: %s", prefix, page, exc)
                queue.insert(0, prefix)
                page_failed = True
                break
            if not items:
                break
            pages_total += 1
            collected_total += len(items)
            buffer.extend(items)
            if len(buffer) >= index_batch_size:
                _flush()
            logger.info(
                "Prefixo '%s' página %s/%s: +%s itens (%s recolhidas, %s indexadas)",
                prefix, page, pages, len(items), collected_total, indexed_total,
            )
            _emit(kind="page", prefix=prefix, page=page, items=len(items), collected=collected_total,
                  indexed=indexed_total, unique_total=len(existing) + collected_total,
                  queue=len(queue), total=total)
            if page < pages:
                time.sleep(collector.delay + random.uniform(0.3, 1.2))

        if page_failed:
            _flush()
            _save_prefix_state(
                {"queue": queue, "done": sorted(seen_prefixes), "current": prefix,
                 "stats": {"collected": collected_total, "indexed": indexed_total, "pages": pages_total}}
            )
            continue

        seen_prefixes.add(prefix)
        _flush()
        _save_prefix_state(
            {"queue": queue, "done": sorted(seen_prefixes), "current": prefix,
             "stats": {"collected": collected_total, "indexed": indexed_total, "pages": pages_total}}
        )

    _flush()
    state = _load_prefix_state()
    state.update(
        {
            "queue": queue,
            "done": sorted(seen_prefixes),
            "current": current,
            "stats": {"collected": collected_total, "indexed": indexed_total, "pages": pages_total},
        }
    )
    _save_prefix_state(state)
    unique_total = len(_read_jsonl())
    completed = not queue
    _emit(
        kind="done",
        prefix=current,
        page=0,
        collected=collected_total,
        indexed=indexed_total,
        unique_total=unique_total,
        queue=len(queue),
        completed=completed,
        stopped=stopped,
    )
    return {
        "ok": True,
        "mode": "prefix",
        "collected": collected_total,
        "unique_total": unique_total,
        "indexed": indexed_total,
        "pages": pages_total,
        "queue_remaining": len(queue),
        "prefixes_done": len(seen_prefixes),
        "stopped": stopped,
        "completed": completed,
        "jsonl": str(JSONL_PATH),
    }


def collect_sample(
    max_pages: int = 1000,
    delay: float = DEFAULT_DELAY,
    query: str = "",
    index_to_es: bool = True,
) -> Dict[str, Any]:
    """Recolhe uma amostra, deduplica e indexa opcionalmente."""
    existing = _existing_nifs()
    collector = RigorbizCollector(delay=delay)
    items = collector.fetch_sample(max_pages=max_pages, query=query)
    new_items = [i for i in items if i.get("nif") and i["nif"] not in existing]
    if new_items:
        _save_results(new_items, append=True)
    indexed = 0
    if index_to_es and new_items:
        try:
            from api.rigorbiz_indexer import index_items
            indexed = int(index_items(new_items).get("indexed") or 0)
        except Exception as exc:
            logger.warning("Indexação da amostra falhou: %s", exc)
    return {
        "ok": True,
        "collected": len(new_items),
        "sampled_total": len(items),
        "indexed": indexed,
        "jsonl": str(JSONL_PATH),
        "json": str(JSON_PATH),
        "unique_total": len(_read_jsonl()),
        "duplicates_skipped": len(items) - len(new_items),
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
