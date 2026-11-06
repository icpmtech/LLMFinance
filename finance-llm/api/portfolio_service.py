"""Serviços de portfólio financeiro — dados reais do Yahoo Finance + notícias do sistema.

O módulo expõe funções puras de cálculo e funções que vão buscar dados. Todas as
leituras ao Yahoo usam cache em memória (TTL curto) para não repetir pedidos a
cada componente da SPA. As notícias vêm do índice finance_news do Elasticsearch
quando disponível; senão usam a API de notícias do Yahoo como fallback.
"""
from __future__ import annotations

import json
import logging
import math
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO_PATH = ROOT / "data" / "portfolio_default.json"

CACHE_TTL_SECONDS = 45.0

# Notícias: a tradução para português corre em segundo plano e fica em cache uma
# semana (o texto de uma notícia não muda). O interruptor permite desligá-la num
# ambiente sem modelo nem fornecedor de IA disponível.
NEWS_TRANSLATION_TTL = 7 * 24 * 3600.0
NEWS_TRANSLATE_ENABLED = os.getenv("PORTFOLIO_NEWS_TRANSLATE", "1").strip().lower() not in {"0", "false", "no"}
# Quantos títulos por ciclo: o modelo local é lento, o que importa é ir enchendo
# a cache sem martelar a máquina.
NEWS_TRANSLATION_MAX = 8

_translation_lock = threading.Lock()
_translation_state: Dict[str, bool] = {"running": False}


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class _TimedCache:
    """Cache em memória simples com TTL."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None or time.time() > entry.expires_at:
                if entry is not None:
                    del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl: float = CACHE_TTL_SECONDS) -> None:
        with self._lock:
            self._store[key] = _CacheEntry(value, time.time() + ttl)

    def invalidate(self, pattern: Optional[str] = None) -> None:
        with self._lock:
            if pattern is None:
                self._store.clear()
            else:
                for key in list(self._store.keys()):
                    if pattern in key:
                        del self._store[key]


_CACHE = _TimedCache()


# ---------------------------------------------------------------------------
# Utilidades de cálculo
# ---------------------------------------------------------------------------
def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _annualised_volatility(returns: pd.Series, trading_days: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.std() * math.sqrt(trading_days))


def _weighted_returns(df: pd.DataFrame, weights: np.ndarray) -> pd.Series:
    """Devolve série de retornos diários de uma carteira normalizada."""
    normalized = weights / weights.sum()
    returns = df.pct_change(fill_method=None).dropna()
    if returns.empty:
        return pd.Series(dtype=float)
    return (returns * normalized).sum(axis=1)


# ---------------------------------------------------------------------------
# Leitura Yahoo Finance (com cache)
# ---------------------------------------------------------------------------
def _yf_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)


def _fetch_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    cache_key = f"history:{ticker}:{period}:{interval}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    from api.tools import get_stock_history

    df = get_stock_history(ticker, period=period, interval=interval)
    _CACHE.set(cache_key, df, ttl=CACHE_TTL_SECONDS)
    return df


def _fetch_info(ticker: str) -> Dict[str, Any]:
    cache_key = f"info:{ticker}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    from api.tools import get_stock_info

    info = get_stock_info(ticker)
    _CACHE.set(cache_key, info, ttl=CACHE_TTL_SECONDS * 4)
    return info


def _fetch_live_quote(ticker: str) -> Dict[str, Any]:
    cache_key = f"live:{ticker}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    from api.sentiment_market import live_quote

    quote = live_quote(ticker)
    _CACHE.set(cache_key, quote, ttl=CACHE_TTL_SECONDS)
    return quote


def _fetch_news_from_es(
    tickers: Optional[List[str]] = None,
    q: Optional[str] = None,
    size: int = 12,
    hours: int = 72,
) -> List[Dict[str, Any]]:
    """Tenta notícias do índice finance_news do Elasticsearch."""
    try:
        from api.es.mercados import search_all_news

        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        result = search_all_news(
            q=q,
            tickers=tickers,
            sort="recent",
            page=1,
            size=size,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        items = result.get("items") or []
        # Normalizar campos para o frontend. `title`/`summary` ficam no original;
        # `title_pt`/`summary_pt` trazem a versão portuguesa já guardada no índice.
        normalized = []
        for item in items:
            normalized.append(
                {
                    "id": item.get("id") or item.get("_id") or f"{item.get('ticker')}-{item.get('published')}",
                    "title": item.get("title") or "Sem título",
                    "title_pt": item.get("translated_title") or "",
                    "summary": item.get("summary") or "",
                    "summary_pt": item.get("summary_pt") or item.get("translated_summary") or "",
                    "publisher": item.get("publisher") or item.get("source") or "",
                    "published": item.get("published") or item.get("published_at") or "",
                    "url": item.get("url") or "#",
                    "ticker": item.get("ticker") or "",
                    "sentiment": item.get("sentiment") or "neutro",
                    "topics": item.get("topics") or [],
                }
            )
        return normalized
    except Exception as exc:
        logger.warning("Notícias do Elasticsearch indisponíveis para portfólio: %s", exc)
        return []


def _fetch_yahoo_news(ticker: str, size: int = 6) -> List[Dict[str, Any]]:
    """Fallback de notícias por ticker via Yahoo Finance."""
    try:
        from api.tools import get_news

        result = get_news(ticker)
        items = result.get("news") or []
        out = []
        for item in items[:size]:
            out.append(
                {
                    "id": f"yahoo-{ticker}-{item.get('published')}",
                    "title": item.get("title") or "Sem título",
                    "summary": item.get("summary") or "",
                    "publisher": item.get("publisher") or "Yahoo Finance",
                    "published": item.get("published") or "",
                    "url": item.get("link") or "#",
                    "ticker": ticker,
                    "sentiment": "neutro",
                    "topics": [],
                }
            )
        return out
    except Exception as exc:
        logger.warning("Notícias do Yahoo indisponíveis para %s: %s", ticker, exc)
        return []


def _news_translation_key(text: str) -> str:
    return "newstrans:" + hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()


def _cached_translation(text: str) -> Optional[str]:
    if not text:
        return None
    value = _CACHE.get(_news_translation_key(text))
    return value if isinstance(value, str) and value.strip() else None


def _store_translation(source: str, translated: Optional[str]) -> None:
    target = (translated or "").strip()
    if target and target != source.strip():
        _CACHE.set(_news_translation_key(source), target, ttl=NEWS_TRANSLATION_TTL)


def _translate_news_batch(texts: List[str]) -> None:
    """Traduz títulos em segundo plano (fornecedor de IA e, se falhar, modelo local).

    Corre fora do pedido: o modelo local leva dezenas de segundos por título e o
    fornecedor pode estar sem quota. O resultado fica em cache, pelo que a página
    passa a mostrar o português nas visitas seguintes sem custo nenhum.
    """
    pendentes = [t for t in texts if t and not _cached_translation(t)][:NEWS_TRANSLATION_MAX]
    if not pendentes:
        return
    try:
        from api.news_traducao import traduzir_textos

        resultado = traduzir_textos(pendentes)
        for origem, destino in (resultado.get("translations") or {}).items():
            _store_translation(origem, destino)
    except Exception as exc:  # pragma: no cover - depende do fornecedor
        logger.debug("Tradução por IA indisponível para notícias: %s", exc)

    faltam = [t for t in pendentes if not _cached_translation(t)]
    if not faltam:
        return
    try:
        from api.news_nlp import _translate_en_to_pt

        for texto in faltam:
            _store_translation(texto, _translate_en_to_pt(texto))
    except Exception as exc:  # pragma: no cover - depende do modelo local
        logger.debug("Tradução local indisponível para notícias: %s", exc)


def _schedule_news_translation(texts: List[str]) -> None:
    """Arranca a tradução em segundo plano (um único trabalho de cada vez)."""
    if not NEWS_TRANSLATE_ENABLED:
        return
    with _translation_lock:
        if _translation_state["running"]:
            return
        _translation_state["running"] = True

    def _run() -> None:
        try:
            _translate_news_batch(texts)
        finally:
            with _translation_lock:
                _translation_state["running"] = False

    threading.Thread(target=_run, name="portfolio-news-pt", daemon=True).start()


def _apply_news_translations(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta o português já traduzido e agenda o que falta.

    `title`/`summary` mantêm o original; `title_pt`/`summary_pt` trazem a versão
    portuguesa quando existe. A página mostra a portuguesa e o original como
    recurso, sem nunca esperar pela tradução.
    """
    faltam: List[str] = []
    for item in items:
        titulo = str(item.get("title") or "")
        resumo = str(item.get("summary") or "")
        item["title_pt"] = item.get("title_pt") or _cached_translation(titulo) or ""
        if resumo:
            item["summary_pt"] = item.get("summary_pt") or _cached_translation(resumo) or ""
        if not item["title_pt"] and titulo:
            faltam.append(titulo)
    if faltam:
        _schedule_news_translation(faltam)
    return items


# ---------------------------------------------------------------------------
# Carteira default
# ---------------------------------------------------------------------------
def _load_default_portfolio() -> List[Dict[str, Any]]:
    """Lê carteira default de data/portfolio_default.json ou usa benchmark global."""
    if DEFAULT_PORTFOLIO_PATH.exists():
        try:
            raw = json.loads(DEFAULT_PORTFOLIO_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list) and raw:
                return raw
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Carteira default ilegível: %s", exc)
    return [
        {"ticker": "AAPL", "name": "Apple Inc.", "weight": 0.20},
        {"ticker": "MSFT", "name": "Microsoft Corp.", "weight": 0.20},
        {"ticker": "NVDA", "name": "NVIDIA Corp.", "weight": 0.15},
        {"ticker": "JPM", "name": "JPMorgan Chase & Co.", "weight": 0.15},
        {"ticker": "GOOGL", "name": "Alphabet Inc.", "weight": 0.15},
        {"ticker": "XOM", "name": "Exxon Mobil Corp.", "weight": 0.10},
        {"ticker": "JNJ", "name": "Johnson & Johnson", "weight": 0.05},
    ]


def _normalise_weights(weights: List[float]) -> np.ndarray:
    arr = np.array(weights, dtype=float)
    if arr.sum() == 0:
        arr = np.ones_like(arr) / len(arr)
    return arr / arr.sum()


def _get_tickers_and_weights(requested: Optional[List[str]], weights: Optional[List[float]]) -> Tuple[List[str], np.ndarray]:
    default = _load_default_portfolio()
    if requested:
        tickers = [t.strip().upper() for t in requested if t.strip()]
    else:
        tickers = [p["ticker"] for p in default]
    if not tickers:
        tickers = [p["ticker"] for p in default]

    if weights and len(weights) == len(tickers):
        w = _normalise_weights(weights)
    else:
        if len(tickers) <= len(default):
            mapping = {p["ticker"]: p.get("weight", 1.0) for p in default}
            w = _normalise_weights([mapping.get(t, 1.0) for t in tickers])
        else:
            w = _normalise_weights([1.0] * len(tickers))
    return tickers, w


# ---------------------------------------------------------------------------
# Dados de mercado por ticker
# ---------------------------------------------------------------------------
def enrich_tickers(tickers: List[str]) -> List[Dict[str, Any]]:
    """Devolve info + cotação ao vivo para cada ticker."""
    rows = []
    for ticker in tickers:
        info = _fetch_info(ticker)
        quote = _fetch_live_quote(ticker)
        rows.append(
            {
                "ticker": ticker,
                "name": info.get("name") or quote.get("name") or ticker,
                "currency": info.get("currency") or quote.get("currency") or "USD",
                "exchange": info.get("exchange") or quote.get("exchange") or "",
                "sector": info.get("sector") or "",
                "industry": info.get("industry") or "",
                "price": _safe_float(quote.get("price"), _safe_float(info.get("price"))),
                "previous_close": _safe_float(quote.get("previous_close")),
                "change": _safe_float(quote.get("change")),
                "change_pct": _safe_float(quote.get("change_pct")),
                "volume": _safe_float(quote.get("volume")),
                "market_cap": _safe_float(info.get("market_cap")),
                "pe": _safe_float(info.get("pe")),
                "eps": _safe_float(info.get("eps")),
                "dividend_yield": _safe_float(info.get("dividend_yield")),
                "beta": _safe_float(info.get("beta")),
                "target_mean_price": _safe_float(info.get("target_mean_price")),
                "recommendation": info.get("recommendation") or "",
                "recommendation_mean": _safe_float(info.get("recommendation_mean")),
                "number_of_analysts": info.get("number_of_analysts"),
                "kpis": info.get("kpis") or {},
                "error": info.get("error") or quote.get("error"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Histórico alinhado entre tickers
# ---------------------------------------------------------------------------
def aligned_history(
    tickers: List[str], period: str = "1y", interval: str = "1d"
) -> Tuple[pd.DataFrame, List[str]]:
    """Devolve DataFrame com colunas [ticker_Close, ...] e datas como índice."""
    series_map: Dict[str, pd.Series] = {}
    valid_tickers: List[str] = []
    for ticker in tickers:
        df = _fetch_history(ticker, period=period, interval=interval)
        if df.empty or "Close" not in df.columns:
            continue
        ts = df.set_index("Date")["Close"].rename(f"{ticker}_Close")
        series_map[ticker] = ts
        valid_tickers.append(ticker)
    if not series_map:
        return pd.DataFrame(), []
    df = pd.concat(series_map.values(), axis=1).dropna()
    # Normalizar para base 100 no primeiro dia para comparar evolução.
    normalized = df.div(df.iloc[0]) * 100
    return normalized, valid_tickers


# ---------------------------------------------------------------------------
# Sumário de portfólio
# ---------------------------------------------------------------------------
def portfolio_summary(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    positions: Optional[List[Dict[str, Any]]] = None,
    cash: float = 0.0,
    currency: Optional[str] = None,
) -> Dict[str, Any]:
    """Sumário da carteira.

    Com `positions` (as posições guardadas: ticker, quantidade e preço médio) o
    valor passa a ser o **dinheiro real investido** — quantidade × cotação, mais
    a caixa — e a variação é ponderada pelo valor de mercado. Sem posições fica
    o comportamento antigo (pesos relativos sobre a cotação), usado pela carteira
    de demonstração.
    """
    tickers, w = _get_tickers_and_weights(tickers, weights)
    rows = enrich_tickers(tickers)

    total_value = sum((r["price"] or 0) * w[i] for i, r in enumerate(rows) if i < len(w))
    total_change_pct = 0.0
    if total_value > 0:
        total_change_pct = float(
            sum(
                ((r["change_pct"] or 0) * w[i])
                for i, r in enumerate(rows)
                if i < len(w)
            )
        )

    invested_value = 0.0
    cash_value = float(cash or 0.0)
    if positions:
        by_ticker = {str(p.get("ticker") or "").upper(): p for p in positions}
        invested_value = 0.0
        weighted_change = 0.0
        for row in rows:
            position = by_ticker.get(row["ticker"])
            if not position:
                continue
            quantity = float(position.get("quantity") or 0.0)
            avg_price = float(position.get("avg_price") or 0.0)
            price = float(row.get("price") or 0.0)
            market_value = round(quantity * price, 4)
            cost_basis = round(quantity * avg_price, 4) if avg_price > 0 else 0.0
            row["quantity"] = quantity
            row["avg_price"] = avg_price
            row["market_value"] = market_value
            row["cost_basis"] = cost_basis
            row["unrealized_pnl"] = round(market_value - cost_basis, 4) if cost_basis else 0.0
            row["unrealized_pnl_pct"] = (
                round((market_value / cost_basis - 1) * 100, 4) if cost_basis and cost_basis > 0 else 0.0
            )
            invested_value += market_value
            weighted_change += market_value * float(row.get("change_pct") or 0.0)

        if invested_value > 0:
            total_change_pct = weighted_change / invested_value
            w = np.array(
                [
                    (float((by_ticker.get(r["ticker"]) or {}).get("quantity") or 0.0) * float(r.get("price") or 0.0))
                    / invested_value
                    for r in rows
                ],
                dtype=float,
            )
            for index, row in enumerate(rows):
                row["weight"] = round(float(w[index]), 6) if index < len(w) else 0.0
        total_value = invested_value + cash_value

    # Notícias do sistema (primeiro) + fallback Yahoo.
    news = _fetch_news_from_es(tickers=tickers, size=12, hours=72)
    if len(news) < 6:
        for ticker in tickers[:3]:
            news.extend(_fetch_yahoo_news(ticker, size=4))
    seen = set()
    deduped = []
    for n in news:
        key = n.get("title", "").strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        deduped.append(n)

    return {
        "portfolio_value": round(total_value, 4),
        "portfolio_change_pct": round(total_change_pct, 4),
        "currency": currency or (rows[0].get("currency", "USD") if rows else "USD"),
        "tickers": rows,
        "weights": [round(float(x), 6) for x in w.tolist()],
        "cash": round(cash_value, 4),
        "invested_value": round(invested_value, 4),
        "positioned": bool(positions),
        "news": deduped[:16],
        "benchmark": {"ticker": "^GSPC", "name": "S&P 500"},
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Attribution (Brinson simplificado)
# ---------------------------------------------------------------------------
def portfolio_attribution(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    benchmark_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    tickers, w = _get_tickers_and_weights(tickers, weights)
    rows = enrich_tickers(tickers)

    # Histórico dos últimos 6 meses para retornos.
    history, valid_tickers = aligned_history(tickers, period="6mo")
    if history.empty or len(valid_tickers) < 2:
        return {"error": "Precisa de pelo menos 2 tickers com histórico para calcular attribution.", "tickers": tickers}

    # Retorno de cada ticker no período.
    perf = {}
    for t in valid_tickers:
        col = f"{t}_Close"
        if col in history.columns:
            start = history[col].iloc[0]
            end = history[col].iloc[-1]
            perf[t] = (end / start - 1) if start else 0.0

    # Setores como agrupamento.
    sectors: Dict[str, List[str]] = {}
    info_map = {r["ticker"]: r for r in rows}
    for t in valid_tickers:
        sector = info_map.get(t, {}).get("sector") or "Outros"
        sectors.setdefault(sector, []).append(t)

    # Brinson simplificado: atribuição por setor.
    sector_rows = []
    total_active_return = 0.0
    for sector, members in sectors.items():
        pf_weight = sum(w[tickers.index(t)] for t in members if t in tickers)
        pf_return = sum(
            perf.get(t, 0.0) * (w[tickers.index(t)] / pf_weight if pf_weight else 0)
            for t in members
            if t in tickers
        )
        # Benchmark dentro do setor: igualmente ponderado.
        bench_weight = 1.0 / len(sectors)
        bench_return = sum(perf.get(t, 0.0) for t in members) / len(members) if members else 0.0

        allocation_effect = (pf_weight - bench_weight) * (bench_return - sum(perf.values()) / len(perf))
        selection_effect = pf_weight * (pf_return - bench_return)
        currency_effect = 0.0

        sector_rows.append(
            {
                "sector": sector,
                "portfolio_weight": round(pf_weight, 4),
                "benchmark_weight": round(bench_weight, 4),
                "portfolio_return": round(pf_return, 4),
                "benchmark_return": round(bench_return, 4),
                "allocation_effect": round(allocation_effect, 4),
                "selection_effect": round(selection_effect, 4),
                "currency_effect": round(currency_effect, 4),
                "total_effect": round(allocation_effect + selection_effect + currency_effect, 4),
                "tickers": members,
            }
        )
        total_active_return += allocation_effect + selection_effect

    # Top contributors / detractors.
    contributions = []
    for i, t in enumerate(tickers):
        if t in perf:
            contributions.append(
                {
                    "ticker": t,
                    "weight": round(float(w[i]), 4),
                    "return_pct": round(perf[t] * 100, 4),
                    "contribution_pct": round(perf[t] * w[i] * 100, 4),
                    "name": info_map.get(t, {}).get("name", t),
                }
            )
    contributions.sort(key=lambda x: x["contribution_pct"], reverse=True)

    return {
        "period": "6mo",
        "portfolio_return": round(sum(perf.get(t, 0.0) * w[i] for i, t in enumerate(tickers)) * 100, 4),
        "active_return": round(total_active_return * 100, 4),
        "currency": "USD",
        "sectors": sector_rows,
        "top_contributors": contributions[:10],
        "bottom_contributors": contributions[-10:][::-1],
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Risco
# ---------------------------------------------------------------------------
def portfolio_risk(tickers: Optional[List[str]] = None, weights: Optional[List[float]] = None) -> Dict[str, Any]:
    tickers, w = _get_tickers_and_weights(tickers, weights)
    rows = enrich_tickers(tickers)

    history, valid_tickers = aligned_history(tickers, period="1y")
    # Uma carteira de um único ativo é válida: a volatilidade, o VaR e o beta
    # calculam-se na mesma (a contribuição marginal é 100%). Só sem histórico é
    # que não há métricas.
    if history.empty or len(valid_tickers) < 1:
        return {"error": "Histórico insuficiente para métricas de risco.", "tickers": tickers}

    # Apenas tickers válidos.
    mask = np.array([t in valid_tickers for t in tickers])
    w_valid = _normalise_weights(w[mask].tolist())
    valid_cols = [f"{t}_Close" for t in valid_tickers]
    prices = history[valid_cols]
    returns = prices.pct_change(fill_method=None).dropna()

    # Métricas da carteira.
    port_returns = (returns.values @ w_valid).flatten()
    port_vol = _annualised_volatility(pd.Series(port_returns))
    port_mean = float(np.mean(port_returns) * 252)

    # VaR histórico 95% e 99%.
    var_95 = float(np.percentile(port_returns, 5))
    var_99 = float(np.percentile(port_returns, 1))
    cvar_95 = float(port_returns[port_returns <= var_95].mean()) if any(port_returns <= var_95) else var_95

    # Beta vs S&P 500 (^GSPC).
    bench = _fetch_history("^GSPC", period="1y")
    beta = 0.0
    tracking_error = 0.0
    if not bench.empty and "Close" in bench.columns:
        bench_returns = bench.set_index("Date")["Close"].pct_change(fill_method=None).dropna()
        aligned_dates = returns.index.intersection(bench_returns.index)
        if len(aligned_dates) > 30:
            p = pd.Series(port_returns, index=returns.index).loc[aligned_dates]
            b = bench_returns.loc[aligned_dates]
            cov = np.cov(p, b)[0, 1]
            bench_var = np.var(b)
            beta = float(cov / bench_var) if bench_var else 0.0
            tracking_error = float((p - b).std() * math.sqrt(252))

    # Risco por factor (proxy via betas parciais com proxies).
    factor_proxies = {
        "Style": "VTV",  # value
        "Industry": "XLI",
        "Currency": "UUP",
        "Market": "^GSPC",
        "Country": "VEU",
    }
    factor_exposures = []
    for factor, proxy in factor_proxies.items():
        try:
            proxy_df = _fetch_history(proxy, period="1y")
            if proxy_df.empty or "Close" not in proxy_df.columns:
                continue
            proxy_returns = proxy_df.set_index("Date")["Close"].pct_change(fill_method=None).dropna()
            aligned = returns.index.intersection(proxy_returns.index)
            if len(aligned) < 30:
                continue
            p = pd.Series(port_returns, index=returns.index).loc[aligned]
            f = proxy_returns.loc[aligned]
            cov = np.cov(p, f)[0, 1]
            fac_var = np.var(f)
            exposure = float(cov / fac_var) if fac_var else 0.0
            factor_exposures.append({"factor": factor, "exposure": round(exposure, 4), "proxy": proxy})
        except Exception as exc:
            logger.debug("Factor %s ignorado: %s", factor, exc)

    # Risco por posição (contribution à volatilidade).
    cov_matrix = returns.cov().values * 252
    port_var = float(w_valid @ cov_matrix @ w_valid.T)
    marginal_risk = []
    for i, t in enumerate(valid_tickers):
        if port_var and port_var > 0:
            marginal = float((cov_matrix @ w_valid)[i]) / math.sqrt(port_var)
            contrib = float(w_valid[i] * (cov_matrix @ w_valid)[i]) / port_var if port_var else 0.0
        else:
            marginal = 0.0
            contrib = 0.0
        marginal_risk.append(
            {
                "ticker": t,
                "weight": round(float(w_valid[i]), 4),
                "volatility": round(math.sqrt(cov_matrix[i, i]), 4),
                "marginal_risk": round(marginal, 4),
                "risk_contribution_pct": round(contrib * 100, 4),
                "name": next((r["name"] for r in rows if r["ticker"] == t), t),
            }
        )
    marginal_risk.sort(key=lambda x: x["risk_contribution_pct"], reverse=True)

    return {
        "portfolio_volatility": round(port_vol, 4),
        "portfolio_volatility_pct": round(port_vol * 100, 4),
        "expected_return_annual": round(port_mean * 100, 4),
        "beta": round(beta, 4),
        "tracking_error": round(tracking_error, 4),
        "tracking_error_pct": round(tracking_error * 100, 4),
        "var_95_daily": round(var_95 * 100, 4),
        "var_99_daily": round(var_99 * 100, 4),
        "cvar_95_daily": round(cvar_95 * 100, 4),
        "sharpe_ratio": round(port_mean / port_vol, 4) if port_vol else 0.0,
        "total_active_risk_pct": round(port_vol * 100, 4),
        "factor_exposures": factor_exposures,
        "idiosyncratic_risk_pct": round(port_vol * 100 * 0.45, 4),  # proxy: 45% da vol é idiossincrática
        "marginal_risk": marginal_risk,
        "currency": "USD",
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Otimização / resiliência
# ---------------------------------------------------------------------------
def portfolio_optimize(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    objective: str = "sharpe",
) -> Dict[str, Any]:
    tickers, w = _get_tickers_and_weights(tickers, weights)
    rows = enrich_tickers(tickers)

    history, valid_tickers = aligned_history(tickers, period="2y")
    if history.empty or len(valid_tickers) < 2:
        return {"error": "Precisa de pelo menos 2 tickers com histórico para otimizar a carteira.", "tickers": tickers}

    w_valid = _normalise_weights(w[[t in valid_tickers for t in tickers]].tolist())
    valid_cols = [f"{t}_Close" for t in valid_tickers]
    prices = history[valid_cols]
    returns = prices.pct_change(fill_method=None).dropna()
    if returns.empty or returns.shape[1] < 2:
        return {"error": "Retornos insuficientes.", "tickers": valid_tickers}

    mean_returns = returns.mean() * 252
    cov_matrix = returns.cov() * 252

    n = len(valid_tickers)
    bounds = [(0.0, 0.35) for _ in range(n)]
    constraints = {"type": "eq", "fun": lambda x: np.sum(x) - 1}
    initial_guess = np.array([1.0 / n] * n)

    from scipy.optimize import minimize

    def _neg_sharpe(x: np.ndarray) -> float:
        p_ret = float(mean_returns.values @ x)
        p_vol = float(math.sqrt(x @ cov_matrix.values @ x))
        return -(p_ret / p_vol) if p_vol else 0.0

    def _neg_return(x: np.ndarray) -> float:
        return -float(mean_returns.values @ x)

    def _min_volatility(x: np.ndarray) -> float:
        return float(math.sqrt(x @ cov_matrix.values @ x))

    objective_map = {
        "sharpe": _neg_sharpe,
        "return": _neg_return,
        "risk": _min_volatility,
        "resilience": _min_volatility,
    }
    fun = objective_map.get(objective, _neg_sharpe)
    result = minimize(fun, initial_guess, method="SLSQP", bounds=bounds, constraints=constraints)

    optimal = result.x if result.success else initial_guess
    optimal = _normalise_weights(optimal.tolist())

    opt_return = float(mean_returns.values @ optimal)
    opt_vol = float(math.sqrt(optimal @ cov_matrix.values @ optimal))

    # Métricas fundamentais para maximizar LTG EPS & sales growth.
    fundamental_scores = []
    for i, t in enumerate(valid_tickers):
        info = next((r for r in rows if r["ticker"] == t), {})
        kpis = info.get("kpis") or {}
        ltg_eps = _safe_float(kpis.get("earningsGrowth"), 0.0) or _safe_float(kpis.get("revenueGrowth"), 0.0)
        sales_growth = _safe_float(kpis.get("revenueGrowth"), 0.0)
        total_risk = math.sqrt(cov_matrix.values[i, i])
        score = (ltg_eps + sales_growth) / (1 + total_risk)
        fundamental_scores.append(
            {
                "ticker": t,
                "ltg_eps_growth": round(ltg_eps, 4),
                "sales_growth": round(sales_growth, 4),
                "active_total_risk": round(total_risk, 4),
                "score": round(score, 6),
                "name": info.get("name", t),
            }
        )
    fundamental_scores.sort(key=lambda x: x["score"], reverse=True)

    constraints_out = [
        {"field": "Security", "group": "Relative", "min": 0, "max": 35, "unit": "Wt%"},
        {"field": "Turnover", "group": "Portfolio", "min": 0, "max": 20, "unit": "%"},
        {"field": "Trade Size", "group": "Init. Portfolio", "min": 0.25, "max": 2, "unit": "%"},
    ]

    return {
        "objective": objective,
        "optimal_weights": [round(float(x), 6) for x in optimal.tolist()],
        "expected_return_annual": round(opt_return * 100, 4),
        "expected_volatility": round(opt_vol * 100, 4),
        "sharpe_ratio": round(opt_return / opt_vol, 4) if opt_vol else 0.0,
        "current_weights": [round(float(x), 6) for x in w_valid.tolist()],
        "current_expected_return": round(float(mean_returns.values @ w_valid) * 100, 4),
        "current_expected_volatility": round(float(math.sqrt(w_valid @ cov_matrix.values @ w_valid)) * 100, 4),
        "tickers": [
            {"ticker": t, "name": next((r["name"] for r in rows if r["ticker"] == t), t)} for t in valid_tickers
        ],
        "fundamental_scores": fundamental_scores,
        "constraints": constraints_out,
        "currency": "USD",
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Previsão (forecast) de preço
# ---------------------------------------------------------------------------
def portfolio_forecast(
    tickers: Optional[List[str]] = None,
    future_days: int = 30,
    use_sentiment: bool = False,
) -> Dict[str, Any]:
    tickers, _ = _get_tickers_and_weights(tickers, None)
    forecasts = []
    for ticker in tickers[:5]:  # limitar para não bloquear
        try:
            from forecasting.arima_model import run_full_pipeline
            from api.tools import _normalize_ticker

            raw_result = run_full_pipeline(
                ticker=_normalize_ticker(ticker),
                future_steps=future_days,
                period="5y",
                order=(2, 1, 2),
                train_ratio=0.85,
            )
            result = raw_result.to_dict() if hasattr(raw_result, "to_dict") else raw_result
            points = []
            for p in result.get("forecast", []):
                points.append(
                    {
                        "date": p.get("date"),
                        "price": _safe_float(p.get("price")),
                        "lower": _safe_float(p.get("lower")),
                        "upper": _safe_float(p.get("upper")),
                    }
                )
            series = []
            for s in result.get("series", []):
                series.append(
                    {
                        "date": s.get("date"),
                        "value": _safe_float(s.get("value")),
                        "type": s.get("type", "history"),
                    }
                )
            forecasts.append(
                {
                    "ticker": ticker,
                    "rmse": _safe_float(result.get("rmse")),
                    "mape": _safe_float(result.get("mape")),
                    "currency": result.get("currency", "USD"),
                    "company_name": result.get("company_name") or result.get("ticker"),
                    "forecast": points,
                    "series": series,
                    "last_train_date": result.get("last_train_date"),
                    "last_test_date": result.get("last_test_date"),
                    "model_summary": result.get("model_summary") or "ARIMA",
                }
            )
        except Exception as exc:
            logger.warning("Forecast ARIMA falhou para %s: %s", ticker, exc)
            forecasts.append(
                {
                    "ticker": ticker,
                    "error": str(exc),
                    "forecast": [],
                    "series": [],
                }
            )

    # Notícias para contexto.
    news = _fetch_news_from_es(tickers=tickers, size=10, hours=72)
    if len(news) < 4:
        for t in tickers[:2]:
            news.extend(_fetch_yahoo_news(t, size=4))

    return {
        "future_days": future_days,
        "use_sentiment": use_sentiment,
        "forecasts": forecasts,
        "news": news[:12],
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Relatórios (dados agregados para PDF/HTML)
# ---------------------------------------------------------------------------
def portfolio_reporting(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    positions: Optional[List[Dict[str, Any]]] = None,
    cash: float = 0.0,
    currency: Optional[str] = None,
) -> Dict[str, Any]:
    tickers, w = _get_tickers_and_weights(tickers, weights)
    summary = portfolio_summary(
        tickers=tickers, weights=w.tolist(), positions=positions, cash=cash, currency=currency
    )
    attribution = portfolio_attribution(tickers=tickers, weights=w.tolist())
    risk = portfolio_risk(tickers=tickers, weights=w.tolist())
    optimize = portfolio_optimize(tickers=tickers, weights=w.tolist(), objective="sharpe")

    history, valid_tickers = aligned_history(tickers, period="1y")
    series = []
    if not history.empty:
        for date, row in history.iterrows():
            series.append(
                {
                    "date": date.isoformat() if isinstance(date, datetime) else str(date),
                    **{t: round(row.get(f"{t}_Close", 0), 4) for t in valid_tickers},
                }
            )

    return {
        "title": "Relatório de Carteira",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "currency": summary.get("currency", "USD"),
        "summary": summary,
        "attribution": attribution,
        "risk": risk,
        "optimization": optimize,
        "performance_series": series,
        "benchmark": {"ticker": "^GSPC", "name": "S&P 500"},
    }
