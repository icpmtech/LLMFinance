"""Sentimento diário de mercado — série por ticker em `finance_sentiment_daily`.

O módulo de sentimento (`api/sentiment_service.py`) analisa **texto**; este módulo
transforma esse motor numa **série de mercado**: para cada ticker e cada dia,
agrega as notícias indexadas (`finance_news`) num documento em
`finance_sentiment_daily` e expõe a leitura de conjunto — série, panorama,
rankings de variação e heatmap ticker × dia.

Decisões que evitam leituras erradas:

* **Duas médias**: `sentiment_mean` (bruta, todos os documentos) e
  `sentiment_signal` (só documentos com termos de sentimento, ponderada pela
  evidência `min(acertos, 3)/3`). Um dia cheio de títulos sem léxico aparece
  «neutro» na média bruta por diluição, não por ausência de tom — a leitura do
  painel usa a de sinal, com a `coverage` ao lado.
* **Idempotência**: o documento é escrito com id `ticker|data`, pelo que
  reconstruir um dia **atualiza** em vez de duplicar. Reprocessar é seguro.
* **Notícias já classificadas**: quando o texto está vazio usa-se o rótulo
  gravado na notícia (`sentiment`: positivo/neutro/negativo) convertido em
  polaridade convencional (±0,5), em vez de a descartar.
* **Preço à parte**: a relação tom × preço (`correlation`, `divergences`) usa as
  cotações da plataforma (`finance_prices`) e, quando faltam, as do Yahoo
  Finance; diz sempre a amostra, a fonte e que correlação não é causalidade.

Nada aqui é inventado: os números vêm sempre de notícias reais indexadas e a
`coverage` diz quantas tinham vocabulário de sentimento reconhecido.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api import sentiment_service as sentiment
from api.elasticsearch_client import (
    SENTIMENT_DAILY_INDEX,
    delete_sentiment_daily as _delete_daily,
    index_price_points as _index_prices,
    index_sentiment_daily as _index_daily,
    list_indexed_tickers as _list_price_tickers,
    list_news_tickers as _list_news_tickers,
    list_sentiment_daily_tickers as _list_daily_tickers,
    search_news as _search_news,
    search_prices as _search_prices,
    search_sentiment_daily as _search_daily,
)
from api.elasticsearch_ingest import (
    ingest_ticker_news as _ingest_news_async,
    ingest_ticker_prices as _ingest_prices_async,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_DIR = ROOT / "data" / "sentiment_market"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

MAX_NEWS_PER_TICKER = 400
MAX_TICKERS = 200
MAX_HEATMAP_TICKERS = 24
DEFAULT_DAYS = 30

# Lista de tickers seguidos (a que o utilizador acrescenta à mão).
WATCHLIST_PATH = SETTINGS_DIR / "tickers.json"
_TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.^=\-]{0,11}$")
MAX_WATCHLIST = 60
LABEL_TO_POLARITY = {"positivo": 0.5, "negativo": -0.5, "neutro": 0.0, "positive": 0.5, "negative": -0.5, "neutral": 0.0}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "cron": "30 6 * * *",
    "timezone": "Europe/Lisbon",
    "days": 3,
    "engine": "lexicon",
    "max_news_per_ticker": 300,
}

_lock = threading.RLock()


# --------------------------------------------------------------------------
# Configuração (ficheiro JSON, como nos restantes módulos novos)
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now() -> str:
    """Data/hora atual em ISO 8601 UTC (a mesma usada nos documentos e relatórios)."""
    return _now()


def _read_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Definições do sentimento de mercado ilegíveis (%s); a usar as por omissão.", exc)
        return dict(DEFAULT_SETTINGS)
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        settings.update({key: value for key, value in raw.items() if value is not None})
    return settings


def _write_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, ensure_ascii=False, indent=2)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(SETTINGS_PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover
        raise last if last else OSError(f"Não foi possível gravar {SETTINGS_PATH}.")


def settings() -> Dict[str, Any]:
    return _read_settings()


def save_settings(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Grava a agenda e os parâmetros da construção da série."""
    with _lock:
        current = _read_settings()
        if "enabled" in payload:
            current["enabled"] = bool(payload.get("enabled"))
        if "cron" in payload:
            current["cron"] = str(payload.get("cron") or "").strip()
        if "timezone" in payload:
            current["timezone"] = str(payload.get("timezone") or "Europe/Lisbon").strip() or "Europe/Lisbon"
        if "days" in payload:
            current["days"] = _clamp(payload.get("days"), 1, 90, 3)
        if "engine" in payload:
            engine = str(payload.get("engine") or "lexicon").strip().lower()
            current["engine"] = engine if engine in ("lexicon", "neural", "auto") else "lexicon"
        if "max_news_per_ticker" in payload:
            current["max_news_per_ticker"] = _clamp(payload.get("max_news_per_ticker"), 20, MAX_NEWS_PER_TICKER, 300)
        _write_settings(current)
        logger.info("Definições do sentimento de mercado guardadas por %s: %s", actor or "—", current)
        return current


# --------------------------------------------------------------------------
# Tickers seguidos (lista do utilizador)
# --------------------------------------------------------------------------
def _read_watchlist() -> Dict[str, Any]:
    if not WATCHLIST_PATH.exists():
        return {"tickers": [], "updated_at": None, "actor": None}
    try:
        raw = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Lista de tickers ilegível (%s); a começar vazia.", exc)
        return {"tickers": [], "updated_at": None, "actor": None}
    tickers = raw.get("tickers") if isinstance(raw, dict) else raw
    return {
        "tickers": [str(code).strip().upper() for code in (tickers or []) if str(code).strip()],
        "updated_at": raw.get("updated_at") if isinstance(raw, dict) else None,
        "actor": raw.get("actor") if isinstance(raw, dict) else None,
    }


def _write_watchlist(payload: Dict[str, Any]) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = WATCHLIST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(WATCHLIST_PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover
        raise last if last else OSError(f"Não foi possível gravar {WATCHLIST_PATH}.")


def watchlist() -> List[str]:
    """Tickers que o utilizador segue, pela ordem em que os acrescentou."""
    return _read_watchlist()["tickers"]


def add_ticker(ticker: str, actor: str = "") -> List[str]:
    """Acrescenta um ticker à lista de seguidos (idempotente)."""
    code = str(ticker or "").strip().upper()
    if not code:
        raise KeyError("Indique o ticker.")
    with _lock:
        current = _read_watchlist()
        codes = current["tickers"]
        if code not in codes:
            if len(codes) >= MAX_WATCHLIST:
                raise ValueError(f"A lista já tem {MAX_WATCHLIST} tickers; retire algum antes de acrescentar outro.")
            codes = codes + [code]
            _write_watchlist({"tickers": codes, "updated_at": _now(), "actor": actor or None})
        return codes


def remove_ticker(ticker: str, actor: str = "") -> List[str]:
    """Retira um ticker da lista de seguidos (a série guardada fica)."""
    code = str(ticker or "").strip().upper()
    with _lock:
        current = _read_watchlist()
        codes = [item for item in current["tickers"] if item != code]
        if codes != current["tickers"]:
            _write_watchlist({"tickers": codes, "updated_at": _now(), "actor": actor or None})
        return codes


def normalise_ticker(ticker: str) -> str:
    """Valida o formato do símbolo (ex.: `EDP.LS`, `BRK-B`, `^GSPC`)."""
    code = str(ticker or "").strip().upper()
    if not code:
        raise KeyError("Indique o ticker.")
    if not _TICKER_RE.match(code):
        raise KeyError(
            f"«{code}» não parece um símbolo válido. Use letras e números, com o sufixo do mercado quando for caso disso (ex.: EDP.LS, AAPL)."
        )
    return code


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _iso_day(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def tone_of(polarity: float) -> str:
    """Etiqueta do tom (os mesmos limiares do motor de sentimento)."""
    return sentiment.label_for(float(polarity or 0.0))


def _weighted_mean(pairs: Sequence[Tuple[float, float]]) -> float:
    """Média ponderada (valor, peso); devolve 0.0 quando não há peso."""
    total = sum(weight for _value, weight in pairs if weight)
    if not total:
        return 0.0
    return sum(value * weight for value, weight in pairs if weight) / total


# --------------------------------------------------------------------------
# Análise das notícias de um ticker
# --------------------------------------------------------------------------
# Tokens do início do título usados para reconhecer a mesma história.
DEDUPE_PREFIX_TOKENS = 8
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")


def _fold_text(value: Any) -> str:
    """Texto em minúsculas, sem acentos e sem pontuação."""
    lowered = unicodedata.normalize("NFKD", str(value or "").lower())
    stripped = "".join(char for char in lowered if not unicodedata.combining(char))
    return _NON_WORD_RE.sub(" ", stripped).strip()


def title_key(title: Any) -> str:
    """Chave de história: os primeiros tokens do título normalizado.

    Serve para reconhecer a **mesma notícia publicada em vários sítios** (título
    igual ou quase), que de outra forma valeria por várias no tom do dia.
    """
    tokens = _fold_text(title).split()
    return " ".join(tokens[:DEDUPE_PREFIX_TOKENS])


def _dedupe_rows(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Devolve as histórias distintas e quantas notícias eram repetições."""
    seen: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for position, row in enumerate(rows):
        key = title_key(row.get("title")) or f"sem-titulo-{position}"
        if key in seen:
            duplicates += 1
            continue
        seen[key] = row
    return list(seen.values()), duplicates


def _news_text(item: Dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("translated_title") or "").strip()
    summary = str(
        item.get("summary_pt") or item.get("translated_summary") or item.get("summary") or ""
    ).strip()
    return sentiment.clean_text(" ".join(part for part in (title, summary) if part))


def analyze_news_items(items: Iterable[Dict[str, Any]], *, engine: str = "lexicon") -> List[Dict[str, Any]]:
    """Classifica as notícias de um ticker (polaridade, tom, evidência e metadados)."""
    rows: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = _news_text(item)
        if text:
            analysis = sentiment.analyze_text(text)
            polarity = float(analysis.get("polarity") or 0.0)
            hits = int(analysis.get("hits") or 0)
            label = str(analysis.get("label") or tone_of(polarity))
            source_engine = engine
        else:
            # Sem texto (título vazio): aproveita o rótulo já gravado na notícia.
            stored = str(item.get("sentiment") or "").strip().lower()
            polarity = LABEL_TO_POLARITY.get(stored, 0.0)
            hits = 0
            label = stored if stored in ("positivo", "negativo", "neutro") else tone_of(polarity)
            source_engine = "stored"
        rows.append(
            {
                "title": str(item.get("title") or item.get("translated_title") or "(sem título)")[:300],
                "url": str(item.get("url") or ""),
                "source": str(item.get("publisher") or item.get("source") or "—")[:120],
                "published": str(item.get("published") or ""),
                "day": _iso_day(item.get("published")),
                "polarity": round(polarity, 3),
                "label": label,
                "hits": hits,
                "engine": source_engine,
                "topics": [str(topic) for topic in (item.get("topics") or []) if topic][:8],
                "sentiment": str(item.get("sentiment") or ""),
            }
        )
    return rows


def aggregate_day(ticker: str, day: str, rows: Sequence[Dict[str, Any]], *, engine: str = "lexicon") -> Optional[Dict[str, Any]]:
    """Constrói o documento diário de um ticker a partir das notícias do dia.

    Uma notícia sindicada (mesmo título em vários sítios) conta **uma vez** no tom
    do dia: o `news_count` continua a dizer quantas notícias havia, mas as medidas
    de tom (média, sinal, rácios, cobertura) usam as histórias distintas
    (`unique_articles`) e o número de repetições fica em `duplicates`.
    """
    docs = [row for row in rows if row.get("day") == day]
    if not docs:
        return None
    unique_docs, duplicates = _dedupe_rows(docs)
    polarities = [float(row["polarity"]) for row in unique_docs]
    count = len(polarities)
    mean = sum(polarities) / count
    variance = sum((value - mean) ** 2 for value in polarities) / count
    signal_docs = [row for row in unique_docs if int(row.get("hits") or 0) > 0]
    signal = _weighted_mean(
        [(float(row["polarity"]), min(int(row["hits"]), 3) / 3) for row in signal_docs]
    ) if signal_docs else 0.0
    positives = sum(1 for row in unique_docs if row.get("label") == "positivo")
    negatives = sum(1 for row in unique_docs if row.get("label") == "negativo")
    reading = signal if signal_docs else mean
    # Temas pela história (contada uma vez); fontes por todas as notícias, porque
    # dizem quem cobriu a história.
    topics = Counter(topic for row in unique_docs for topic in (row.get("topics") or []))
    sources = Counter(row.get("source") or "—" for row in docs)
    ordered = sorted(unique_docs, key=lambda row: float(row["polarity"]))
    highlights = [
        {
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "polarity": row["polarity"],
            "label": row["label"],
        }
        for row in (list(reversed(ordered))[:3] + ordered[:3])
    ]
    return {
        "ticker": ticker.upper(),
        "date": day,
        "news_count": len(docs),
        "unique_articles": count,
        "duplicates": duplicates,
        "sentiment_mean": round(mean, 4),
        "sentiment_signal": round(signal, 4),
        "sentiment_std": round(variance ** 0.5, 4),
        "positive_count": positives,
        "negative_count": negatives,
        "positive_ratio": round(positives / count, 4),
        "negative_ratio": round(negatives / count, 4),
        "documents_with_signal": len(signal_docs),
        "coverage": round(len(signal_docs) / count, 4),
        "label": tone_of(reading),
        "engine": engine,
        "topics": [term for term, _ in topics.most_common(8)],
        "sources": [name for name, _ in sources.most_common(6)],
        "articles": len(docs),
        "highlights": highlights,
        "generated_at": _now(),
        "updated_at": _now(),
    }


# --------------------------------------------------------------------------
# Construção da série
# --------------------------------------------------------------------------
def known_tickers(*, es: Any = None) -> List[str]:
    """Tickers a considerar: os **seguidos**, os do mercado e os que têm notícias."""
    tickers: List[str] = [code for code in watchlist()]
    for source in (_list_news_tickers(es), _list_price_tickers(es)):
        if isinstance(source, dict):
            items = source.get("items") or source.get("tickers") or []
        else:
            items = source or []
        for entry in items:
            code = str(entry.get("ticker") if isinstance(entry, dict) else entry).strip().upper()
            if code and code not in tickers:
                tickers.append(code)
    return tickers[:MAX_TICKERS]


def _window(days: int, end: Optional[datetime] = None) -> Tuple[str, str]:
    end_date = (end or datetime.now(timezone.utc)).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)
    return start_date.isoformat(), end_date.isoformat()


def build_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    engine: str = "lexicon",
    max_news: int = 300,
    existing: Optional[set] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Constrói (e grava) os dias de um ticker no intervalo pedido."""
    result = _search_news(ticker, start_date=start_date, end_date=end_date, size=max(10, min(max_news, MAX_NEWS_PER_TICKER)), es=es)
    if result.get("error"):
        return {"ticker": ticker, "error": result["error"], "documents": []}
    rows = analyze_news_items(result.get("items") or [], engine=engine)
    days = sorted({row["day"] for row in rows if row.get("day")})
    documents: List[Dict[str, Any]] = []
    skipped = 0
    for day in days:
        if existing and f"{ticker.upper()}|{day}" in existing:
            skipped += 1
            continue
        document = aggregate_day(ticker, day, rows, engine=engine)
        if document:
            documents.append(document)
    return {
        "ticker": ticker,
        "news": len(rows),
        "days": days,
        "documents": documents,
        "skipped": skipped,
        "total_news_reported": result.get("total"),
    }


def _prune_stale(
    tickers: Sequence[str],
    written_days: Dict[str, set],
    failed: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    es: Any = None,
) -> int:
    """Apaga os dias da série que deixaram de ter notícias na janela reconstruída.

    Só toca nos tickers que foram reconstruídos **sem erro**: um ticker cuja
    pesquisa de notícias falhou não pode ver a série apagada por engano.
    """
    wanted = {str(code).upper() for code in tickers} - {str(code).upper() for code in failed}
    if not wanted:
        return 0
    stored = _search_daily(start_date=start_date, end_date=end_date, size=10000, es=es)
    if stored.get("error"):
        return 0
    stale: Dict[str, List[str]] = {}
    for item in stored.get("items") or []:
        code = str(item.get("ticker") or "").upper()
        day = _iso_day(item.get("date"))
        if not code or not day or code not in wanted:
            continue
        if day in (written_days.get(code) or set()):
            continue
        stale.setdefault(code, []).append(day)
    removed = 0
    for code, days in stale.items():
        result = _delete_daily(code, dates=days, es=es)
        if result.get("error"):
            logger.warning("Dias obsoletos de %s não foram apagados: %s", code, result["error"])
            continue
        removed += int(result.get("deleted") or 0)
    return removed


def build(
    *,
    days: Optional[int] = None,
    tickers: Optional[Sequence[str]] = None,
    only_missing: bool = False,
    engine: Optional[str] = None,
    max_news: Optional[int] = None,
    prune: bool = True,
    es: Any = None,
) -> Dict[str, Any]:
    """Agrega as notícias em documentos diários por ticker (idempotente).

    Com `prune`, os dias da janela que deixaram de ter notícias são apagados — a
    série deixa de guardar números de uma janela antiga.
    """
    settings_now = settings()
    window_days = _clamp(days if days is not None else settings_now.get("days"), 1, 90, 3)
    start_date, end_date = _window(window_days)
    engine_name = (engine or str(settings_now.get("engine") or "lexicon")).lower()
    if engine_name not in ("lexicon", "neural", "auto"):
        engine_name = "lexicon"
    limit_news = _clamp(
        max_news if max_news is not None else settings_now.get("max_news_per_ticker"), 20, MAX_NEWS_PER_TICKER, 300
    )
    chosen = [str(code).strip().upper() for code in (tickers or []) if str(code).strip()] or known_tickers(es=es)
    if not chosen:
        return {
            "window": {"days": window_days, "start": start_date, "end": end_date},
            "tickers": 0,
            "news": 0,
            "documents": 0,
            "errors": ["Sem tickers: não há notícias nem preços indexados."],
            "details": [],
        }

    existing: set = set()
    if only_missing:
        stored = _search_daily(start_date=start_date, end_date=end_date, size=10000, es=es)
        existing = {
            f"{str(item.get('ticker')).upper()}|{_iso_day(item.get('date'))}"
            for item in stored.get("items") or []
            if item.get("ticker")
        }

    documents: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []
    errors: List[str] = []
    written_days: Dict[str, set] = {}
    failed: List[str] = []
    total_news = 0
    for code in chosen:
        outcome = build_ticker(
            code,
            start_date,
            end_date,
            engine=engine_name,
            max_news=limit_news,
            existing=existing if only_missing else None,
            es=es,
        )
        if outcome.get("error"):
            errors.append(f"{code}: {outcome['error']}")
            failed.append(code)
        # Dias com notícias **agora** (escritos ou já existentes com `only_missing`).
        written_days[code] = set(outcome.get("days") or [])
        total_news += int(outcome.get("news") or 0)
        documents.extend(outcome.get("documents") or [])
        details.append(
            {
                "ticker": code,
                "news": outcome.get("news") or 0,
                "days": len(outcome.get("days") or []),
                "skipped": outcome.get("skipped") or 0,
            }
        )

    written = {"indexed": 0, "errors": 0}
    if documents:
        written = _index_daily(documents, es=es)
        if written.get("error"):
            errors.append(str(written["error"]))

    pruned = 0
    if prune and not written.get("error"):
        pruned = _prune_stale(chosen, written_days, failed, start_date, end_date, es=es)

    return {
        "window": {"days": window_days, "start": start_date, "end": end_date},
        "tickers": len(chosen),
        "tickers_with_news": sum(1 for item in details if item["news"]),
        "news": total_news,
        "documents": written.get("indexed") or 0,
        "skipped": sum(int(item.get("skipped") or 0) for item in details),
        "pruned": pruned,
        "errors": errors,
        "engine": engine_name,
        "details": sorted(details, key=lambda item: -item["news"])[:60],
    }


# --------------------------------------------------------------------------
# Leitura: série, panorama, rankings e heatmap
# --------------------------------------------------------------------------
def series(*, ticker: Optional[str] = None, days: int = 90, es: Any = None) -> Dict[str, Any]:
    """Série diária: valor de sinal ponderado pelas notícias, com cobertura."""
    start_date, end_date = _window(_clamp(days, 1, 365, 90))
    stored = _search_daily(ticker=ticker, start_date=start_date, end_date=end_date, size=10000, es=es)
    if stored.get("error"):
        return {"error": stored["error"], "items": [], "days": 0}
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for item in stored.get("items") or []:
        day = _iso_day(item.get("date"))
        if day:
            by_day.setdefault(day, []).append(item)
    rows: List[Dict[str, Any]] = []
    for day in sorted(by_day):
        items = by_day[day]
        value_pairs = [
            (float(item.get("sentiment_signal") if item.get("sentiment_signal") is not None else item.get("sentiment_mean") or 0.0), max(1.0, float(item.get("news_count") or 0)))
            for item in items
        ]
        news = sum(int(item.get("news_count") or 0) for item in items)
        rows.append(
            {
                "day": day,
                "sentiment": round(_weighted_mean(value_pairs), 4),
                "news": news,
                "tickers": len(items),
                "coverage": round(
                    _weighted_mean([(float(item.get("coverage") or 0.0), max(1.0, float(item.get("news_count") or 0))) for item in items]),
                    4,
                ),
                "label": tone_of(_weighted_mean(value_pairs)),
            }
        )
    return {
        "ticker": ticker.upper() if ticker else None,
        "start": start_date,
        "end": end_date,
        "days": len(rows),
        "items": rows,
    }


def _ticker_stats(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Estatísticas de um ticker numa janela (a partir dos documentos diários)."""
    news = sum(int(item.get("news_count") or 0) for item in items)
    value = _weighted_mean(
        [
            (
                float(item.get("sentiment_signal") if item.get("sentiment_signal") is not None else item.get("sentiment_mean") or 0.0),
                max(1.0, float(item.get("news_count") or 0)),
            )
            for item in items
        ]
    )
    coverage = _weighted_mean([(float(item.get("coverage") or 0.0), max(1.0, float(item.get("news_count") or 0))) for item in items])
    positives = sum(int(item.get("positive_count") or 0) for item in items)
    negatives = sum(int(item.get("negative_count") or 0) for item in items)
    return {
        "days": len(items),
        "news": news,
        "sentiment": round(value, 4),
        "coverage": round(coverage, 4),
        "positive_ratio": round(positives / news, 4) if news else 0.0,
        "negative_ratio": round(negatives / news, 4) if news else 0.0,
        "label": tone_of(value),
        "last_date": max((_iso_day(item.get("date")) or "" for item in items), default="") or None,
    }


def overview(*, days: int = DEFAULT_DAYS, limit: int = MAX_HEATMAP_TICKERS, es: Any = None) -> Dict[str, Any]:
    """Panorama do sentimento de mercado: KPIs, série, heatmap e rankings."""
    window_days, start_date, end_date, previous_start, previous_end = _window_pair(days)

    current = _search_daily(start_date=start_date, end_date=end_date, size=10000, es=es)
    previous = _search_daily(start_date=previous_start, end_date=previous_end, size=10000, es=es)
    if current.get("error"):
        return {"error": current["error"], "kpis": {}, "series": [], "heatmap": {"days": [], "rows": []}, "ranking": {"up": [], "down": []}, "tickers": []}

    current_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for item in current.get("items") or []:
        code = str(item.get("ticker") or "").upper()
        if code:
            current_by_ticker.setdefault(code, []).append(item)
    previous_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for item in previous.get("items") or []:
        code = str(item.get("ticker") or "").upper()
        if code:
            previous_by_ticker.setdefault(code, []).append(item)

    tickers: List[Dict[str, Any]] = []
    for code, items in current_by_ticker.items():
        stats = _ticker_stats(items)
        before = _ticker_stats(previous_by_ticker.get(code) or []) if previous_by_ticker.get(code) else None
        delta = round(stats["sentiment"] - before["sentiment"], 4) if before else None
        tickers.append(
            {
                "ticker": code,
                **stats,
                "previous": before["sentiment"] if before else None,
                "previous_news": before["news"] if before else 0,
                "delta": delta,
                "basis": "delta" if before else "nivel",
            }
        )
    tickers.sort(key=lambda item: -item["news"])

    news_total = sum(int(item["news"]) for item in tickers)
    market_value = _weighted_mean([(item["sentiment"], max(1.0, item["news"])) for item in tickers])
    coverage = _weighted_mean([(item["coverage"], max(1.0, item["news"])) for item in tickers])
    positives = _weighted_mean([(item["positive_ratio"], max(1.0, item["news"])) for item in tickers])
    negatives = _weighted_mean([(item["negative_ratio"], max(1.0, item["news"])) for item in tickers])
    deltas = [item["delta"] for item in tickers if item["delta"] is not None]
    last_date = max((item.get("last_date") or "" for item in tickers), default="")

    # Heatmap: os tickers com mais notícias × todos os dias da janela.
    heat_rows: List[Dict[str, Any]] = []
    heat_days = sorted({_iso_day(item.get("date")) or "" for item in current.get("items") or [] if _iso_day(item.get("date"))})
    for code, items in sorted(current_by_ticker.items(), key=lambda pair: -sum(int(entry.get("news_count") or 0) for entry in pair[1]))[: max(1, limit)]:
        by_day = {_iso_day(item.get("date")): item for item in items}
        cells = []
        for day in heat_days:
            entry = by_day.get(day)
            if entry is None:
                cells.append({"day": day, "value": None, "news": 0, "label": None, "coverage": None})
                continue
            value = float(entry.get("sentiment_signal") if entry.get("sentiment_signal") is not None else entry.get("sentiment_mean") or 0.0)
            cells.append(
                {
                    "day": day,
                    "value": round(value, 4),
                    "news": int(entry.get("news_count") or 0),
                    "label": str(entry.get("label") or tone_of(value)),
                    "coverage": round(float(entry.get("coverage") or 0.0), 4),
                }
            )
        stats = _ticker_stats(items)
        heat_rows.append({"ticker": code, "cells": cells, "sentiment": stats["sentiment"], "news": stats["news"], "label": stats["label"]})

    # Rankings: variação quando há janela anterior; senão, pelo nível.
    with_delta = [item for item in tickers if item["delta"] is not None]
    if with_delta:
        ranking_up = sorted(with_delta, key=lambda item: -float(item["delta"]))[:5]
        ranking_down = sorted(with_delta, key=lambda item: float(item["delta"]))[:5]
    else:
        ranking_up = sorted(tickers, key=lambda item: -item["sentiment"])[:5]
        ranking_down = sorted(tickers, key=lambda item: item["sentiment"])[:5]

    topics: Counter = Counter()
    sources: Counter = Counter()
    for item in current.get("items") or []:
        topics.update(str(term) for term in (item.get("topics") or []) if term)
        sources.update(str(name) for name in (item.get("sources") or []) if name)

    return {
        "window": {"days": window_days, "start": start_date, "end": end_date, "previous_start": previous_start, "previous_end": previous_end},
        "kpis": {
            "tickers": len(tickers),
            "news": news_total,
            "sentiment": round(market_value, 4),
            "coverage": round(coverage, 4),
            "positive_ratio": round(positives, 4),
            "negative_ratio": round(negatives, 4),
            "label": tone_of(market_value),
            "trend": round(sum(deltas) / len(deltas), 4) if deltas else None,
            "tickers_with_delta": len(deltas),
            "last_date": last_date or None,
        },
        "series": series(days=window_days, es=es).get("items") or [],
        "heatmap": {"days": heat_days, "rows": heat_rows},
        "ranking": {"up": ranking_up, "down": ranking_down, "basis": "delta" if with_delta else "nivel"},
        "tickers": tickers,
        "topics": [{"term": term, "news": count} for term, count in topics.most_common(12)],
        "sources": [{"source": name, "news": count} for name, count in sources.most_common(10)],
        "state": state(es=es),
    }


def ticker_detail(ticker: str, *, days: int = 90, es: Any = None) -> Dict[str, Any]:
    """Série e destaques de um ticker."""
    code = str(ticker or "").strip().upper()
    if not code:
        raise KeyError("Indique o ticker.")
    start_date, end_date = _window(_clamp(days, 3, 365, 90))
    stored = _search_daily(ticker=code, start_date=start_date, end_date=end_date, size=5000, es=es)
    if stored.get("error"):
        return {"ticker": code, "error": stored["error"], "items": [], "stats": {}}
    items = stored.get("items") or []
    # Ordem cronológica: é o que a interface desenha.
    items = sorted(items, key=lambda item: str(item.get("date") or ""))
    if not items:
        return {
            "ticker": code,
            "items": [],
            "stats": {},
            "highlights": [],
            "window": {"days": days, "start": start_date, "end": end_date},
            "message": "Sem série para este ticker. Construa a série (Recolher agora) ou escolha outro período.",
        }
    stats = _ticker_stats(items)
    best = max(items, key=lambda item: float(item.get("sentiment_signal") or 0.0))
    worst = min(items, key=lambda item: float(item.get("sentiment_signal") or 0.0))
    highlights: List[Dict[str, Any]] = []
    blocks: List[Tuple[Dict[str, Any], str]] = []
    if _iso_day(best.get("date")) == _iso_day(worst.get("date")):
        # Um só dia com série: não repetir os mesmos destaques como melhor e pior.
        blocks.append((best, "único dia com série"))
    else:
        blocks.append((best, "melhor dia"))
        blocks.append((worst, "pior dia"))
    for entry, kind in blocks:
        for highlight in (entry.get("highlights") or [])[:3]:
            highlights.append({**highlight, "day": _iso_day(entry.get("date")), "reason": kind})
    return {
        "ticker": code,
        "window": {"days": days, "start": start_date, "end": end_date},
        "stats": stats,
        "items": [
            {
                "day": _iso_day(item.get("date")),
                "sentiment": round(float(item.get("sentiment_signal") if item.get("sentiment_signal") is not None else item.get("sentiment_mean") or 0.0), 4),
                "mean": round(float(item.get("sentiment_mean") or 0.0), 4),
                "news": int(item.get("news_count") or 0),
                "unique": int(item.get("unique_articles") or item.get("news_count") or 0),
                "duplicates": int(item.get("duplicates") or 0),
                "coverage": round(float(item.get("coverage") or 0.0), 4),
                "label": str(item.get("label") or ""),
                "topics": list(item.get("topics") or []),
            }
            for item in items
        ],
        "best": {"day": _iso_day(best.get("date")), "value": round(float(best.get("sentiment_signal") or 0.0), 4)},
        "worst": {"day": _iso_day(worst.get("date")), "value": round(float(worst.get("sentiment_signal") or 0.0), 4)},
        "highlights": highlights,
    }


def state(*, es: Any = None) -> Dict[str, Any]:
    """Estado da série guardada: volume, cobertura e última atualização."""
    listed = _list_daily_tickers(es=es)
    items = listed.get("items") or []
    documents = int(listed.get("total") or 0)
    return {
        "documents": documents,
        "tickers": len(items),
        "first_date": min((item.get("first_date") or "" for item in items), default="") or None,
        "last_date": max((item.get("last_date") or "" for item in items), default="") or None,
        "covered_news": sum(int(item.get("news") or 0) for item in items),
        "top": sorted(items, key=lambda item: -int(item.get("news") or 0))[:12],
        "settings": settings(),
        "index": SENTIMENT_DAILY_INDEX,
    }


def coverage(*, es: Any = None) -> Dict[str, Any]:
    """Que tickers têm notícias mas ainda não têm série (o que falta construir)."""
    news_tickers = _list_news_tickers(es=es)
    entries = news_tickers.get("items") if isinstance(news_tickers, dict) else news_tickers
    with_news: Dict[str, int] = {}
    for entry in entries or []:
        code = str(entry.get("ticker") if isinstance(entry, dict) else entry).strip().upper()
        if code:
            with_news[code] = int(entry.get("news") or 0) if isinstance(entry, dict) else 0
    stored = _list_daily_tickers(es=es).get("items") or []
    built = {str(item.get("ticker")).upper() for item in stored if item.get("ticker")}
    missing = sorted([code for code in with_news if code not in built], key=lambda code: -with_news[code])
    return {"with_news": len(with_news), "built": len(built), "missing": missing[:40], "missing_total": len(missing)}


# --------------------------------------------------------------------------
# Preço e relação com o tom
# --------------------------------------------------------------------------
# Abaixo disto a correlação é demasiado frágil para se ler como relação.
PRICE_MIN_PAIRS = 8
# ±5 % de variação na janela ≈ ±1 na escala de tom (só para medir a divergência).
PRICE_REFERENCE_MOVE = 5.0
PRICE_CAVEAT = (
    "Correlação não é causalidade: com poucos dias, uma relação alta pode ser coincidência. "
    "A amostra (n) e a cobertura do vocabulário estão sempre à vista."
)


def _price_rows(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normaliza pontos de preço (dia + fecho), sem repetições e por ordem.

    Os campos OHLC que vierem são mantidos: é o formato que o índice de cotações
    da plataforma usa.
    """
    by_day: Dict[str, Dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        day = _iso_day(item.get("date"))
        if not day:
            continue
        try:
            close = float(item.get("close"))
        except (TypeError, ValueError):
            continue
        if close != close:  # NaN
            continue
        volume = item.get("volume")
        try:
            volume_value: Optional[int] = int(float(volume)) if volume is not None else None
        except (TypeError, ValueError):
            volume_value = None
        row: Dict[str, Any] = {"date": day, "close": round(close, 4), "volume": volume_value}
        for field in ("open", "high", "low"):
            raw = item.get(field)
            try:
                row[field] = round(float(raw), 4) if raw is not None else None
            except (TypeError, ValueError):
                row[field] = None
        by_day[day] = row
    return [by_day[day] for day in sorted(by_day)]


def _store_price_rows(ticker: str, rows: Sequence[Dict[str, Any]], *, es: Any = None) -> Dict[str, Any]:
    """Guarda as cotações obtidas na plataforma (idempotente por ticker|dia).

    É o que permite ao ranking de divergência ler sem ir ao Yahoo outra vez.
    """
    if not rows:
        return {"indexed": 0, "errors": 0}
    try:
        result = _index_prices(ticker, [dict(row) for row in rows], period="1y", es=es)
    except Exception as exc:  # pragma: no cover - Elasticsearch
        logger.warning("Cotações de %s não ficaram guardadas: %s", ticker, exc)
        return {"indexed": 0, "errors": len(rows), "error": str(exc)}
    return {
        "indexed": int(result.get("indexed_count") or 0),
        "errors": int(result.get("errors") or 0),
        "error": result.get("error"),
    }


def _live_price_rows(ticker: str, days: int) -> List[Dict[str, Any]]:
    """Cotações do Yahoo Finance (a mesma fonte da app de mercados)."""
    try:
        from api.tools import get_stock_history
    except Exception as exc:  # pragma: no cover - depende do ambiente
        logger.debug("Ferramentas de mercado indisponíveis: %s", exc)
        return []
    period = "1y" if days <= 300 else "2y"
    try:
        frame = get_stock_history(ticker, period=period, interval="1d")
    except Exception as exc:
        logger.warning("Cotações de %s não obtidas no Yahoo: %s", ticker, exc)
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for _index, row in frame.iterrows():
            rows.append(
                {
                    "date": row.get("Date"),
                    "open": row.get("Open"),
                    "high": row.get("High"),
                    "low": row.get("Low"),
                    "close": row.get("Close"),
                    "volume": row.get("Volume"),
                }
            )
    except Exception as exc:  # pragma: no cover - histórico inesperado
        logger.debug("Leitura do histórico de %s falhou: %s", ticker, exc)
        return []
    return _price_rows(rows)


def price_points(
    ticker: str,
    days: int = DEFAULT_DAYS,
    *,
    es: Any = None,
    live: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Fechos de um ticker na janela: primeiro a plataforma, depois o Yahoo (se pedido).

    Com `live=True`, as cotações em falta vão ao Yahoo e ficam **guardadas** na
    plataforma (`persist=True`), para as leituras seguintes serem locais.
    """
    code = str(ticker or "").strip().upper()
    if not code:
        raise KeyError("Indique o ticker.")
    window_days, start_date, end_date, _previous_start, _previous_end = _window_pair(days)
    stored = _search_prices(code, start_date=start_date, end_date=end_date, size=2000, es=es)
    points = _price_rows(stored.get("points") or [])
    source = "plataforma" if points else None
    saved = {"indexed": 0, "errors": 0}
    # Índice quase vazio (o habitual: só alguns tickers têm cotações guardadas) ou
    # janela sem cobertura: vale a pena ir buscar as cotações em falta.
    if live and len(points) < max(2, round(window_days * 0.4)):
        # Normalizar outra vez é barato e garante o formato certo (o histórico
        # pode vir com repetições ou sem fecho).
        fetched = _price_rows(_live_price_rows(code, window_days))
        live_rows = [row for row in fetched if start_date <= row["date"] <= end_date]
        if live_rows:
            points = live_rows
            source = "yahoo"
            if persist:
                saved = _store_price_rows(code, live_rows, es=es)
    return {
        "ticker": code,
        "window": {"days": window_days, "start": start_date, "end": end_date},
        "source": source,
        "points": points,
        "total": len(points),
        "stored": saved,
        "error": stored.get("error"),
        "message": None if points else "Sem cotações guardadas na plataforma para este ticker na janela.",
    }


def _pearson(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Correlação de Pearson (None quando há menos de 3 pares ou sem variância)."""
    rows = [(float(x), float(y)) for x, y in pairs if x is not None and y is not None]
    if len(rows) < 3:
        return None
    xs = [x for x, _y in rows]
    ys = [y for _x, y in rows]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in rows)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x <= 0 or variance_y <= 0:
        return None
    return round(covariance / ((variance_x ** 0.5) * (variance_y ** 0.5)), 4)


def _ranks(values: Sequence[float]) -> List[float]:
    """Posições (empates com a média das posições) — para a correlação de Spearman."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def _strength(coefficient: Optional[float]) -> str:
    if coefficient is None:
        return "indeterminada"
    magnitude = abs(coefficient)
    if magnitude >= 0.7:
        return "forte"
    if magnitude >= 0.4:
        return "moderada"
    if magnitude >= 0.2:
        return "fraca"
    return "sem relação aparente"


def _significance(coefficient: Optional[float], count: int) -> Dict[str, Any]:
    """Estatística t sem scipy: |t| ≥ 2 corresponde a p ≈ 0,05 em amostras pequenas."""
    if coefficient is None or count < 4 or abs(coefficient) >= 1:
        return {"t": None, "significant": None}
    statistic = coefficient * ((count - 2) / max(1e-9, 1 - coefficient ** 2)) ** 0.5
    return {"t": round(statistic, 3), "significant": abs(statistic) >= 2.0}


def correlation(
    ticker: str,
    days: int = DEFAULT_DAYS,
    *,
    es: Any = None,
    live: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Relação entre o tom das notícias e a variação diária do preço.

    Alinha os dias que têm **as duas coisas** (tom e variação de fecho) e mede a
    correlação no mesmo dia, com um dia de avanço (o tom do dia anterior contra a
    variação do dia seguinte) e a divergência da janela.
    """
    code = str(ticker or "").strip().upper()
    if not code:
        raise KeyError("Indique o ticker.")
    price = price_points(code, days, es=es, live=live, persist=persist)
    sentiment = series(ticker=code, days=price["window"]["days"], es=es)
    closes = {row["date"]: row["close"] for row in price["points"]}
    ordered = sorted(closes)
    changes: Dict[str, float] = {}
    for index in range(1, len(ordered)):
        previous = closes[ordered[index - 1]]
        if previous:
            changes[ordered[index]] = round((closes[ordered[index]] / previous - 1) * 100, 4)

    pairs: List[Dict[str, Any]] = []
    for item in sentiment.get("items") or []:
        day = item.get("day")
        day = _iso_day(day)
        if day and day in changes:
            pairs.append(
                {
                    "day": day,
                    "sentiment": float(item.get("sentiment") or 0.0),
                    "change_pct": changes[day],
                    "close": closes[day],
                    "news": int(item.get("news") or 0),
                    "coverage": float(item.get("coverage") or 0.0),
                    "label": item.get("label"),
                }
            )

    same_day = _pearson([(item["sentiment"], item["change_pct"]) for item in pairs])
    spearman = (
        _pearson(list(zip(_ranks([item["sentiment"] for item in pairs]), _ranks([item["change_pct"] for item in pairs]))))
        if len(pairs) >= 3
        else None
    )
    lag_pairs = [(pairs[index - 1]["sentiment"], pairs[index]["change_pct"]) for index in range(1, len(pairs))]
    lag = _pearson(lag_pairs)

    window_change = round((closes[ordered[-1]] / closes[ordered[0]] - 1) * 100, 4) if len(ordered) >= 2 and closes[ordered[0]] else None
    window_sentiment = (
        round(_weighted_mean([(item["sentiment"], max(1.0, float(item["news"]))) for item in pairs]), 4) if pairs else None
    )
    normalized = None if window_change is None else round(max(-1.0, min(1.0, window_change / PRICE_REFERENCE_MOVE)), 4)
    gap = None if (normalized is None or window_sentiment is None) else round(window_sentiment - normalized, 4)
    if len(pairs) < PRICE_MIN_PAIRS:
        reading = "amostra_insuficiente"
    elif gap is None:
        reading = "indeterminada"
    elif abs(gap) < 0.25:
        reading = "alinhado"
    elif gap > 0:
        reading = "tom_acima_do_preco"
    else:
        reading = "preco_acima_do_tom"

    return {
        "ticker": code,
        "window": price["window"],
        "price_source": price.get("source"),
        "price_stored": price.get("stored"),
        "price_days": len(ordered),
        "sentiment_days": len(sentiment.get("items") or []),
        "pairs": len(pairs),
        "enough_data": len(pairs) >= PRICE_MIN_PAIRS,
        "min_pairs": PRICE_MIN_PAIRS,
        "same_day": {
            "r": same_day,
            "spearman": spearman,
            "n": len(pairs),
            "strength": _strength(same_day),
            "direction": None if same_day is None else ("positiva" if same_day >= 0 else "negativa"),
            **_significance(same_day, len(pairs)),
        },
        "lag1": {"r": lag, "n": len(lag_pairs), "strength": _strength(lag), **_significance(lag, len(lag_pairs))},
        "window_move": {
            "sentiment": window_sentiment,
            "change_pct": window_change,
            "normalized_change": normalized,
            "gap": gap,
            "reading": reading,
        },
        "series": pairs,
        "price_message": price.get("message"),
        "caveat": PRICE_CAVEAT,
        "error": price.get("error") or sentiment.get("error"),
    }


def divergences(
    days: int = DEFAULT_DAYS,
    *,
    limit: int = 12,
    es: Any = None,
    live: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Tickers em que o tom e o preço andam em sentidos diferentes.

    Para comparar as duas escalas, a variação da janela é normalizada por
    `PRICE_REFERENCE_MOVE` (±5 % ≈ ±1 em tom): a diferença (`gap`) mede o
    desalinhamento, não uma previsão.
    """
    window_days, start_date, end_date, _previous_start, _previous_end = _window_pair(days)
    current, error = _window_tickers(start_date, end_date, es)
    if error:
        return {"error": error, "items": [], "total": 0, "with_prices": 0, "caveat": PRICE_CAVEAT}
    cap = _clamp(limit, 1, 30, 12)
    items: List[Dict[str, Any]] = []
    with_prices = 0
    indexed = 0
    for code, docs in current.items():
        price = price_points(code, window_days, es=es, live=live, persist=persist)
        indexed += int((price.get("stored") or {}).get("indexed") or 0)
        rows = price["points"]
        if len(rows) < 2 or not rows[0]["close"]:
            continue
        with_prices += 1
        stats = _ticker_stats(docs)
        change = round((rows[-1]["close"] / rows[0]["close"] - 1) * 100, 4)
        normalized = round(max(-1.0, min(1.0, change / PRICE_REFERENCE_MOVE)), 4)
        gap = round(stats["sentiment"] - normalized, 4)
        items.append(
            {
                "ticker": code,
                "sentiment": stats["sentiment"],
                "label": stats["label"],
                "news": stats["news"],
                "days": stats["days"],
                "coverage": stats["coverage"],
                "change_pct": change,
                "normalized_change": normalized,
                "gap": gap,
                "reading": "alinhado" if abs(gap) < 0.25 else ("tom_acima_do_preco" if gap > 0 else "preco_acima_do_tom"),
                "price_source": price.get("source"),
                "price_days": len(rows),
            }
        )
    items.sort(key=lambda item: -abs(float(item["gap"])))
    return {
        "window": {"days": window_days, "start": start_date, "end": end_date},
        "items": items[:cap],
        "total": len(items),
        "tickers_with_series": len(current),
        "with_prices": with_prices,
        "stored": indexed,
        "reference_move": PRICE_REFERENCE_MOVE,
        "caveat": PRICE_CAVEAT,
        "message": (
            None
            if with_prices
            else "Nenhum destes tickers tem cotações guardadas na plataforma — peça a leitura ao Yahoo Finance."
        ),
    }


# --------------------------------------------------------------------------
# Seguir tickers: notícias e cotações a pedido, com a série logo a seguir
# --------------------------------------------------------------------------
def _await(coro_factory: Any, *, timeout: float = 240) -> Any:
    """Corre uma corrotina a partir de código síncrono (mesmo com ciclo a correr)."""
    import asyncio
    import concurrent.futures

    async def run() -> Any:
        return await coro_factory()

    try:
        return asyncio.run(run())
    except RuntimeError:
        # Já existe um ciclo de eventos (rota async): corre num ciclo próprio.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(run())).result(timeout=timeout)


def _suggest_tickers(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Sugestões do Yahoo Finance quando um símbolo não devolve nada."""
    try:
        from api.tools import yahoo_search
    except Exception as exc:  # pragma: no cover - depende do ambiente
        logger.debug("Pesquisa de mercados indisponível: %s", exc)
        return []
    try:
        results = yahoo_search(query, max_results=limit) or []
    except Exception as exc:
        logger.warning("Sugestões para %s falharam: %s", query, exc)
        return []
    return [
        {"ticker": item.get("symbol"), "name": item.get("name"), "exchange": item.get("exchange")}
        for item in results[:limit]
        if item.get("symbol")
    ]


def follow_ticker(
    ticker: str,
    *,
    actor: str = "",
    ingest_news: bool = True,
    ingest_prices: bool = True,
    days: Optional[int] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Segue um ticker: acrescenta à lista, traz notícias e cotações e constrói a série.

    É o que permite **análise dinâmica**: a partir do símbolo, o módulo vai buscar
    notícias (Yahoo) e cotações, agrega o tom do dia e devolve tudo explicado. Não
    inventa nada quando não há dados — diz o que faltou e sugere símbolos próximos.
    """
    code = normalise_ticker(ticker)
    window_days = _clamp(days if days is not None else settings().get("days"), 1, 90, 3)
    report: Dict[str, Any] = {
        "ticker": code,
        "window": {"days": window_days},
        "news": None,
        "prices": None,
        "series": None,
        "errors": [],
        "suggestions": [],
    }

    if ingest_news:
        try:
            outcome = _await(lambda: _ingest_news_async(code, backend="heuristic", auto_analyze=True))
            report["news"] = {
                "indexed": int(getattr(outcome, "indexed_count", 0) or 0),
                "total": int(getattr(outcome, "total_items", 0) or 0),
                "analyzed": int(getattr(outcome, "analyzed_count", 0) or 0),
                "error": getattr(outcome, "error", None),
            }
            if report["news"]["error"]:
                report["errors"].append(f"notícias: {report['news']['error']}")
        except Exception as exc:
            report["errors"].append(f"notícias: {exc}")

    if ingest_prices:
        try:
            price = price_points(code, max(window_days, 30), es=es, live=True, persist=True)
            report["prices"] = {
                "source": price.get("source"),
                "points": price.get("total"),
                "stored": price.get("stored"),
                "error": price.get("error"),
            }
        except Exception as exc:
            report["errors"].append(f"cotações: {exc}")

    series_result = build(days=window_days, tickers=[code], es=es)
    detail = next((item for item in (series_result.get("details") or []) if item.get("ticker") == code), None)
    report["series"] = {
        "days": int((detail or {}).get("days") or 0),
        "news": series_result.get("news"),
        "documents": series_result.get("documents"),
        "pruned": series_result.get("pruned"),
    }
    report["detail"] = detail
    report["errors"].extend(series_result.get("errors") or [])

    report["watchlist"] = add_ticker(code, actor=actor)
    report["followed"] = True

    # Nada de notícias nem cotações: quase sempre é o símbolo errado.
    if not (report["news"] or {}).get("indexed") and not (report["prices"] or {}).get("points"):
        report["suggestions"] = _suggest_tickers(code)
        if not report["suggestions"]:
            report["errors"].append(
                "Não encontrei notícias nem cotações para este símbolo no Yahoo Finance — confirme o código e o mercado (ex.: EDP.LS)."
            )
    return report


def unfollow_ticker(ticker: str, actor: str = "") -> Dict[str, Any]:
    """Deixa de seguir um ticker (a série já construída mantém-se)."""
    code = normalise_ticker(ticker)
    tickers = remove_ticker(code, actor=actor)
    return {"ticker": code, "removed": code not in tickers, "watchlist": tickers}


def tickers_status(*, days: int = DEFAULT_DAYS, es: Any = None) -> Dict[str, Any]:
    """Estado por ticker: seguido ou não, dias de série, notícias e cotações guardadas."""
    window_days, start_date, end_date, _previous_start, _previous_end = _window_pair(days)
    followed = watchlist()
    stored = _list_daily_tickers(es=es).get("items") or []
    within, _error = _window_tickers(start_date, end_date, es)
    order: List[str] = []
    for code in [item for item in followed] + [str(entry.get("ticker") or "").upper() for entry in stored]:
        code = str(code).strip().upper()
        if code and code not in order:
            order.append(code)
    rows: List[Dict[str, Any]] = []
    for code in order:
        documents = within.get(code) or []
        price = _search_prices(code, size=1, es=es)
        rows.append(
            {
                "ticker": code,
                "followed": code in followed,
                "documents": len(documents),
                "news": sum(int(item.get("news_count") or 0) for item in documents),
                "stories": sum(int(item.get("unique_articles") or item.get("news_count") or 0) for item in documents),
                "last_date": max((_iso_day(item.get("date")) or "" for item in documents), default="") or None,
                "label": _ticker_stats(documents)["label"] if documents else None,
                "price_points": int(price.get("total") or 0),
                "price_error": price.get("error"),
            }
        )
    rows.sort(key=lambda item: (not item["followed"], -int(item["documents"]), item["ticker"]))
    return {
        "window": {"days": window_days, "start": start_date, "end": end_date},
        "watchlist": followed,
        "total": len(rows),
        "items": rows[:80],
        "max_watchlist": MAX_WATCHLIST,
    }


# --------------------------------------------------------------------------
# Alertas e boletim
# --------------------------------------------------------------------------
ALERT_KINDS: Dict[str, str] = {
    "subida": "Movimento em alta",
    "descida": "Movimento em baixa",
    "viragem": "Viragem de sinal",
    "extremo": "Dia extremo",
    "cobertura": "Tom pouco sustentado",
}

SEVERITY_LABELS: Dict[str, str] = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
_SEVERITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}

# Limiares dos alertas (o dia extremo e a cobertura baixa são sobre o documento diário).
EXTREME_READING = 0.6
LOW_COVERAGE = 0.25


def _severity(magnitude: float, *, high: float, medium: float) -> str:
    if magnitude >= high:
        return "alta"
    if magnitude >= medium:
        return "media"
    return "baixa"


def _window_pair(days: int) -> Tuple[int, str, str, str, str]:
    """Janela atual e a imediatamente anterior (sem sobreposição)."""
    window_days = _clamp(days, 3, 180, DEFAULT_DAYS)
    start_date, end_date = _window(window_days)
    previous_end = (datetime.fromisoformat(end_date) - timedelta(days=window_days)).date().isoformat()
    previous_start = (datetime.fromisoformat(previous_end) - timedelta(days=window_days - 1)).date().isoformat()
    return window_days, start_date, end_date, previous_start, previous_end


def _window_tickers(start_date: str, end_date: str, es: Any = None) -> Tuple[Dict[str, List[Dict[str, Any]]], Optional[str]]:
    """Documentos da série agrupados por ticker, ou o erro de leitura."""
    stored = _search_daily(start_date=start_date, end_date=end_date, size=10000, es=es)
    if stored.get("error"):
        return {}, str(stored["error"])
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in stored.get("items") or []:
        code = str(item.get("ticker") or "").upper()
        if code:
            grouped.setdefault(code, []).append(item)
    return grouped, None


def _alert_weight(item: Dict[str, Any]) -> float:
    """Magnetude para ordenar: o dia extremo vale pelo valor do próprio dia."""
    magnitude = item.get("value") if str(item.get("kind")) == "extremo" else item.get("delta")
    if magnitude is None:
        magnitude = item.get("value") if item.get("value") is not None else item.get("delta")
    return -abs(float(magnitude or 0.0))


def alerts(
    *,
    days: int = DEFAULT_DAYS,
    min_delta: float = 0.25,
    min_news: int = 2,
    limit: int = 12,
    es: Any = None,
) -> Dict[str, Any]:
    """Alertas de movimentos: variações, viragens de sinal, dias extremos e cobertura.

    Nada aqui é «sinal de compra»: são leituras de tom das notícias que merecem
    atenção, com o critério à vista e o número de notícias que as sustenta.
    """
    window_days, start_date, end_date, previous_start, previous_end = _window_pair(days)
    try:
        threshold = max(0.05, min(1.0, float(min_delta)))
    except (TypeError, ValueError):
        threshold = 0.25
    minimum_news = _clamp(min_news, 1, 50, 2)
    cap = _clamp(limit, 1, 60, 12)

    current, error = _window_tickers(start_date, end_date, es)
    if error:
        return {"error": error, "items": [], "total": 0, "counts": []}
    previous, _ = _window_tickers(previous_start, previous_end, es)

    items: List[Dict[str, Any]] = []
    for code, docs in current.items():
        stats = _ticker_stats(docs)
        before = _ticker_stats(previous[code]) if previous.get(code) else None
        delta = round(stats["sentiment"] - before["sentiment"], 4) if before else None
        base: Dict[str, Any] = {
            "ticker": code,
            "sentiment": stats["sentiment"],
            "label": stats["label"],
            "news": stats["news"],
            "coverage": stats["coverage"],
            "last_date": stats["last_date"],
            "previous": before["sentiment"] if before else None,
            "delta": delta,
        }

        if delta is not None and stats["news"] >= minimum_news and abs(delta) >= threshold:
            kind = "subida" if delta > 0 else "descida"
            items.append(
                {
                    **base,
                    "kind": kind,
                    "kind_label": ALERT_KINDS[kind],
                    "severity": _severity(abs(delta), high=0.5, medium=0.35),
                    "detail": (
                        f"Tom passou de {before['sentiment']:+.3f} para {stats['sentiment']:+.3f} "
                        f"com {stats['news']} notícia(s)."
                    ),
                }
            )

        if (
            before is not None
            and before["news"] >= minimum_news
            and stats["news"] >= minimum_news
            and before["label"] != stats["label"]
        ):
            items.append(
                {
                    **base,
                    "kind": "viragem",
                    "kind_label": ALERT_KINDS["viragem"],
                    "severity": "alta",
                    "detail": f"Leitura passou de «{before['label']}» para «{stats['label']}».",
                }
            )

        if stats["news"] >= minimum_news and stats["coverage"] < LOW_COVERAGE:
            share = round(stats["coverage"] * 100)
            detail = (
                "Nenhuma notícia tem vocabulário de sentimento: a leitura é «sem tom», não «neutra»."
                if share <= 0
                else f"Só {share} % das notícias têm vocabulário de sentimento — o tom pode ser diluição, não ausência de tom."
            )
            items.append(
                {
                    **base,
                    "kind": "cobertura",
                    "kind_label": ALERT_KINDS["cobertura"],
                    "severity": "media",
                    "detail": detail,
                }
            )

        strongest = None
        for doc in docs:
            if int(doc.get("news_count") or 0) < 1:
                continue
            if strongest is None or abs(float(doc.get("sentiment_signal") or 0.0)) > abs(
                float(strongest.get("sentiment_signal") or 0.0)
            ):
                strongest = doc
        if strongest is not None:
            value = float(strongest.get("sentiment_signal") or 0.0)
            if abs(value) >= EXTREME_READING and stats["news"] >= minimum_news:
                day = _iso_day(strongest.get("date"))
                top = (strongest.get("highlights") or [{}])[0] or {}
                headline = f" — «{top.get('title')}»" if top.get("title") else "."
                items.append(
                    {
                        **base,
                        "kind": "extremo",
                        "kind_label": ALERT_KINDS["extremo"],
                        "severity": _severity(abs(value), high=0.8, medium=0.7),
                        "day": day,
                        "value": round(value, 4),
                        "detail": (
                            f"{'Dia muito positivo' if value > 0 else 'Dia muito negativo'} em {day} "
                            f"({int(strongest.get('news_count') or 0)} notícia(s)){headline}"
                        ),
                    }
                )

    items.sort(key=lambda item: (_SEVERITY_ORDER.get(str(item.get("severity")), 3), _alert_weight(item)))
    counts = Counter(str(item["kind"]) for item in items)
    return {
        "window": {
            "days": window_days,
            "start": start_date,
            "end": end_date,
            "previous_start": previous_start,
            "previous_end": previous_end,
        },
        "thresholds": {
            "min_delta": threshold,
            "min_news": minimum_news,
            "extreme": EXTREME_READING,
            "low_coverage": LOW_COVERAGE,
        },
        "kinds": [{"id": key, "label": label} for key, label in ALERT_KINDS.items()],
        "items": items[:cap],
        "total": len(items),
        "counts": [
            {"kind": kind, "label": ALERT_KINDS.get(kind, kind), "count": total}
            for kind, total in counts.most_common()
        ],
        "generated_at": _now(),
    }


def brief(*, days: int = 7, min_delta: float = 0.25, es: Any = None) -> Dict[str, Any]:
    """Boletim do mercado num formato pronto a ler (e a guardar no Office)."""
    window_days = _clamp(days, 1, 30, 7)
    panorama = overview(days=window_days, limit=MAX_HEATMAP_TICKERS, es=es)
    if panorama.get("error"):
        return {"error": panorama["error"], "markdown": "", "alerts": {"items": []}}
    alert_payload = alerts(days=max(window_days, 7), min_delta=min_delta, es=es)
    series = panorama.get("series") or []
    ranking = panorama.get("ranking") or {}
    basis = str(ranking.get("basis") or "nivel")
    with_delta = [item for item in (panorama.get("tickers") or []) if item.get("delta") is not None]
    if with_delta:
        movers_up = sorted(with_delta, key=lambda item: -float(item["delta"]))[:5]
        movers_down = sorted(with_delta, key=lambda item: float(item["delta"]))[:5]
    else:
        # Sem janela anterior: o boletim mostra o nível de tom, dizendo-o.
        movers_up = (ranking.get("up") or [])[:5]
        movers_down = (ranking.get("down") or [])[:5]
    payload: Dict[str, Any] = {
        "window": panorama.get("window"),
        "kpis": panorama.get("kpis"),
        "series": series,
        "ranking": ranking,
        "best": max(series, key=lambda item: float(item.get("sentiment") or 0.0)) if series else None,
        "worst": min(series, key=lambda item: float(item.get("sentiment") or 0.0)) if series else None,
        "movers": {"up": movers_up, "down": movers_down, "basis": basis},
        "alerts": alert_payload,
        "topics": (panorama.get("topics") or [])[:6],
        "sources": (panorama.get("sources") or [])[:5],
        "generated_at": _now(),
    }
    payload["markdown"] = brief_markdown(payload)
    return payload


def brief_markdown(payload: Dict[str, Any], *, title: str = "Boletim de sentimento de mercado") -> str:
    """Texto do boletim (Markdown, pronto para Office ou para copiar)."""
    kpis = payload.get("kpis") or {}
    window = payload.get("window") or {}
    movers = payload.get("movers") or {}
    alert_payload = payload.get("alerts") or {}
    trend = kpis.get("trend")
    trend_text = "—" if trend is None else f"{float(trend):+.3f}"
    lines = [
        f"# {title}",
        "",
        f"**Janela:** {window.get('start')} a {window.get('end')} ({window.get('days')} dias) · **gerado em** {payload.get('generated_at') or _now()}",
        "",
        "## Resumo",
        "",
        f"- **Tom ponderado do mercado:** {float(kpis.get('sentiment') or 0):+.3f} ({kpis.get('label') or '—'})",
        f"- **Notícias analisadas:** {kpis.get('news', 0)} · **tickers com série:** {kpis.get('tickers', 0)}",
        f"- **Cobertura:** {round(float(kpis.get('coverage') or 0) * 100, 1)} % (notícias com vocabulário de sentimento)",
        f"- **Positivas / negativas:** {round(float(kpis.get('positive_ratio') or 0) * 100, 1)} % / {round(float(kpis.get('negative_ratio') or 0) * 100, 1)} %",
        f"- **Tendência vs janela anterior:** {trend_text}"
        + ("" if kpis.get("tickers_with_delta") else " (sem histórico anterior na plataforma)"),
    ]
    best = payload.get("best")
    worst = payload.get("worst")
    if best and worst:
        lines.append(
            f"- **Melhor dia:** {best.get('day')} ({float(best.get('sentiment') or 0):+.3f}) · "
            f"**pior dia:** {worst.get('day')} ({float(worst.get('sentiment') or 0):+.3f})"
        )
    lines.append("")

    up = movers.get("up") or []
    down = movers.get("down") or []
    if up or down:
        basis_label = (
            "variação vs janela anterior"
            if movers.get("basis") == "delta"
            else "nível de tom (sem histórico anterior)"
        )
        lines.extend(["## Movimentos", "", f"_Critério: {basis_label}._", "", "| Ticker | Tom | Δ | Notícias |", "| --- | --- | --- | --- |"])
        for item in up:
            delta = "—" if item.get("delta") is None else f"{float(item['delta']):+.3f}"
            lines.append(f"| {item['ticker']} | {float(item['sentiment']):+.3f} | {delta} | {item['news']} |")
        for item in down:
            delta = "—" if item.get("delta") is None else f"{float(item['delta']):+.3f}"
            lines.append(f"| {item['ticker']} | {float(item['sentiment']):+.3f} | {delta} | {item['news']} |")
        lines.append("")

    items = alert_payload.get("items") or []
    lines.extend(["## Alertas", ""])
    if items:
        for item in items:
            day = f" ({item['day']})" if item.get("day") else ""
            lines.append(f"- **[{SEVERITY_LABELS.get(str(item.get('severity')), item.get('severity'))}] {item.get('ticker')}{day} — {item.get('kind_label')}:** {item.get('detail')}")
        counts = alert_payload.get("counts") or []
        if counts:
            lines.append("")
            lines.append("_Resumo dos alertas: " + ", ".join(f"{entry['label']} {entry['count']}" for entry in counts) + "._")
    else:
        thresholds = alert_payload.get("thresholds") or {}
        lines.append(
            f"_Sem movimentos acima dos limiares (Δ ≥ {thresholds.get('min_delta')}, "
            f"mínimo de {thresholds.get('min_news')} notícias, leitura extrema ≥ {thresholds.get('extreme')})._"
        )
    lines.append("")

    topics = payload.get("topics") or []
    if topics:
        lines.extend(["## Temas mais frequentes", ""])
        lines.extend([f"- **{item['term']}** — {item['news']} notícia(s)" for item in topics])
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "_Método: o tom de cada dia é a média ponderada pela evidência dos documentos com termos de sentimento "
            "(o peso satura em 3 acertos); a cobertura indica a fração de notícias com vocabulário reconhecido, e os "
            "dias com cobertura baixa aparecem como alerta para não se ler diluição como neutralidade. Notícias com o "
            "mesmo título (sindicadas) contam uma vez. A série é idempotente por `ticker|dia` e as notícias sem texto "
            "usam o rótulo já gravado._",
            "",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Relatório (Office)
# --------------------------------------------------------------------------
def report_markdown(payload: Dict[str, Any], *, title: str = "Sentimento de mercado") -> str:
    """Relatório Markdown do panorama (para o Office ou um dossiê)."""
    kpis = payload.get("kpis") or {}
    window = payload.get("window") or {}
    trend = kpis.get("trend")
    trend_text = "—" if trend is None else f"{float(trend):+.3f}"
    lines = [
        f"# {title}",
        "",
        f"**Janela:** {window.get('start')} a {window.get('end')} ({window.get('days')} dias) · **gerado em** {_now()}",
        "",
        "## Indicadores",
        "",
        "| Indicador | Valor |",
        "| --- | --- |",
        f"| Tom ponderado | {float(kpis.get('sentiment') or 0):+.3f} ({kpis.get('label', '—')}) |",
        f"| Tickers com série | {kpis.get('tickers', 0)} |",
        f"| Notícias analisadas | {kpis.get('news', 0)} |",
        f"| Cobertura (com termos de sentimento) | {round(float(kpis.get('coverage') or 0) * 100, 1)} % |",
        f"| Positivas / negativas | {round(float(kpis.get('positive_ratio') or 0) * 100, 1)} % / {round(float(kpis.get('negative_ratio') or 0) * 100, 1)} % |",
        f"| Tendência vs janela anterior | {trend_text} |",
        "",
    ]
    ranking = payload.get("ranking") or {}
    basis = "variação vs janela anterior" if ranking.get("basis") == "delta" else "nível de tom (sem histórico anterior)"
    lines.extend(
        [
            "## Maiores subidas",
            "",
            f"_Critério: {basis}._",
            "",
            "| Ticker | Tom | Δ | Notícias |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in ranking.get("up") or []:
        delta = "—" if item.get("delta") is None else f"{item['delta']:+.3f}"
        lines.append(f"| {item['ticker']} | {item['sentiment']:+.3f} | {delta} | {item['news']} |")
    lines.extend(["", "## Maiores descidas", "", "| Ticker | Tom | Δ | Notícias |", "| --- | --- | --- | --- |"])
    for item in ranking.get("down") or []:
        delta = "—" if item.get("delta") is None else f"{item['delta']:+.3f}"
        lines.append(f"| {item['ticker']} | {item['sentiment']:+.3f} | {delta} | {item['news']} |")

    heat = payload.get("heatmap") or {}
    days = heat.get("days") or []
    if days and heat.get("rows"):
        lines.extend(["", "## Heatmap (ticker × dia)", "", "| Ticker | " + " | ".join(day[5:] for day in days) + " |", "| --- |" + " --- |" * len(days)])
        for row in heat["rows"]:
            cells = []
            for cell in row.get("cells") or []:
                cells.append("—" if cell.get("value") is None else f"{cell['value']:+.2f}")
            lines.append(f"| {row['ticker']} | " + " | ".join(cells) + " |")

    topics = payload.get("topics") or []
    if topics:
        lines.extend(["", "## Temas mais frequentes", ""])
        lines.extend([f"- **{item['term']}** — {item['news']} notícia(s)" for item in topics])
    lines.extend(
        [
            "",
            "---",
            "",
            "_Notas de método: a leitura usa a média ponderada pela evidência dos documentos com termos de sentimento "
            "(o peso satura em 3 acertos); a cobertura indica a fração de notícias com vocabulário reconhecido e as "
            "notícias sem texto usam o rótulo já gravado. Notícias com o mesmo título (sindicadas) contam uma vez no "
            "tom do dia. A série é idempotente por `ticker|dia`._",
            "",
        ]
    )
    return "\n".join(lines)


def export_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Linhas para CSV (uma por ticker) a partir do panorama."""
    rows: List[Dict[str, Any]] = []
    for item in payload.get("tickers") or []:
        rows.append(
            {
                "ticker": item["ticker"],
                "sentiment": item["sentiment"],
                "label": item["label"],
                "delta": item.get("delta"),
                "previous": item.get("previous"),
                "news": item["news"],
                "days": item["days"],
                "coverage": item["coverage"],
                "positive_ratio": item["positive_ratio"],
                "negative_ratio": item["negative_ratio"],
                "last_date": item.get("last_date"),
            }
        )
    return rows
