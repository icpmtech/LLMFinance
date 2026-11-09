"""Serviços do módulo "Test market scenarios - AI tools for trading".

O módulo funciona sobre dados reais do Yahoo Finance (reutilizando a infra de
`portfolio_service`) e calcula:

* templates de cenários macro/recessão/inflação/etc;
* stress-test da carteira contra cenários históricos e simulados;
* backtest simples de estratégias de trading;
* gerador de sinais de trading com LLM opcional (com fallback para heurística);
* simulador de ordens "what-if";
* simulador de choques de mercado com Monte Carlo.

Todas as funções têm entradas/resultados JSON-serializáveis para os endpoints
FastAPI. O LLM é invocado de forma tolerante a falhas: se nenhum fornecedor
cloud estiver disponível, a resposta mantém a análise heurística.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from api import portfolio_service

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
DEFAULT_SCENARIOS = {
    "recession": {
        "label": "Recessão leve (2008-lite)",
        "description": "Queda generalizada dos ativos de risco, voo para qualidade.",
        "shocks": {"equity": -0.35, "credit_spread": 2.5, "rates": -1.5, "volatility": 1.8},
        "factor_correlation": 0.75,
        "probability": 0.15,
    },
    "inflation": {
        "label": "Inflação persistente",
        "description": "Subida de taxas reais, valor real a sofrer, commodities a beneficiar.",
        "shocks": {"equity": -0.15, "rates": 2.5, "inflation": 0.03, "commodity": 0.25, "volatility": 0.4},
        "factor_correlation": 0.55,
        "probability": 0.20,
    },
    "rate_hike": {
        "label": "Ciclo agressivo de subida de taxas",
        "description": "Fed/ECB sobem taxas rapidamente; growth cai, financeiro sobe parcialmente.",
        "shocks": {"equity": -0.18, "rates": 3.0, "growth": -0.12, "value": 0.06, "volatility": 0.5},
        "factor_correlation": 0.50,
        "probability": 0.18,
    },
    "tech_bubble_burst": {
        "label": "Estouro de bolha tecnológica",
        "description": "Valorização extrema do growth reverte; small/value resistem.",
        "shocks": {"growth": -0.45, "momentum": -0.30, "value": -0.05, "small": -0.10, "volatility": 1.5},
        "factor_correlation": 0.65,
        "probability": 0.12,
    },
    "bull_market": {
        "label": "Bull market alimentado por juros baixos",
        "description": "Cenário benigno: taxas em queda, volatilidade baixa, equity em rally.",
        "shocks": {"equity": 0.35, "rates": -1.0, "volatility": -0.25, "credit_spread": -0.5},
        "factor_correlation": 0.30,
        "probability": 0.20,
    },
    "geopolitical_shock": {
        "label": "Choque geopolítico / energia",
        "description": "Petróleo e gás disparam; defensivos (utilities, ouro) sobem.",
        "shocks": {"commodity": 0.45, "equity": -0.15, "defensive": 0.12, "volatility": 1.2},
        "factor_correlation": 0.40,
        "probability": 0.15,
    },
}

SECTOR_SENSITIVITY: Dict[str, Dict[str, float]] = {
    "Technology": {"growth": 1.3, "rates": 1.1, "value": -0.6, "momentum": 1.0, "volatility": 1.2},
    "Financial Services": {"rates": 0.9, "credit_spread": -1.2, "value": 0.8, "volatility": 0.9},
    "Healthcare": {"defensive": 1.0, "value": 0.3, "rates": -0.2, "volatility": 0.4},
    "Consumer Cyclical": {"equity": 1.2, "growth": 0.7, "rates": 0.9, "volatility": 1.1},
    "Consumer Defensive": {"defensive": 0.9, "equity": 0.4, "value": 0.5, "volatility": 0.3},
    "Energy": {"commodity": 1.4, "equity": 0.8, "rates": -0.3, "volatility": 1.2},
    "Utilities": {"defensive": 1.1, "rates": -1.0, "value": 0.4, "volatility": 0.3},
    "Communication Services": {"equity": 1.0, "growth": 0.8, "value": -0.2, "volatility": 0.9},
    "Industrials": {"equity": 1.1, "rates": 0.5, "value": 0.3, "volatility": 0.8},
    "Basic Materials": {"commodity": 1.1, "equity": 0.8, "inflation": 0.9, "volatility": 0.9},
    "Real Estate": {"rates": 1.4, "value": 0.5, "equity": 0.7, "volatility": 1.0},
    "default": {"equity": 1.0, "volatility": 1.0, "rates": 0.5, "growth": 0.5, "value": 0.0, "momentum": 0.5, "commodity": 0.4, "defensive": 0.3, "inflation": 0.5, "credit_spread": -0.5, "small": 0.5},
}


def _sector_sensitivity(sector: str, factor: str) -> float:
    return SECTOR_SENSITIVITY.get(sector, SECTOR_SENSITIVITY["default"]).get(factor, SECTOR_SENSITIVITY["default"].get(factor, 0.0))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    return portfolio_service._safe_float(value, default)


def _normalise_weights(weights: List[float]) -> np.ndarray:
    arr = np.array(weights, dtype=float)
    if arr.sum() == 0 or np.isnan(arr.sum()):
        arr = np.ones_like(arr) / len(arr)
    return arr / arr.sum()


def _ticker_sector(ticker: str, rows: List[Dict[str, Any]]) -> str:
    return next((r.get("sector") or "" for r in rows if r.get("ticker") == ticker), "")


def _ticker_beta(ticker: str, rows: List[Dict[str, Any]]) -> float:
    return _safe_float(next((r.get("beta") for r in rows if r.get("ticker") == ticker), None), 1.0) or 1.0


# ---------------------------------------------------------------------------
# Dados de mercado
# ---------------------------------------------------------------------------
def get_aligned_returns(
    tickers: List[str],
    period: str = "2y",
    interval: str = "1d",
) -> Tuple[pd.DataFrame, List[str]]:
    """Devolve DataFrame de retornos diários com datas como índice."""
    prices, valid = portfolio_service.aligned_history(tickers, period=period, interval=interval)
    if prices.empty or len(valid) == 0:
        return pd.DataFrame(), []
    cols = [f"{t}_Close" for t in valid]
    returns = prices[cols].pct_change(fill_method=None).dropna()
    returns.columns = valid
    return returns, valid


def _history_points(ticker: str, period: str = "1y", interval: str = "1d") -> List[Dict[str, Any]]:
    """Lista de pontos {date, close} para um ticker."""
    df = portfolio_service._fetch_history(ticker, period=period, interval=interval)
    if df.empty or "Close" not in df.columns or "Date" not in df.columns:
        return []
    points = []
    for _, row in df.iterrows():
        date = row["Date"]
        date_str = date.isoformat() if hasattr(date, "isoformat") else str(date)
        close = _safe_float(row.get("Close"))
        if close is not None:
            points.append({"date": date_str, "close": close})
    return points


# ---------------------------------------------------------------------------
# Cenários / stress-test
# ---------------------------------------------------------------------------
def list_scenario_templates() -> List[Dict[str, Any]]:
    """Lista todos os templates de cenário disponíveis."""
    return [
        {
            "id": key,
            "label": cfg["label"],
            "description": cfg["description"],
            "probability": cfg["probability"],
            "shocks": cfg["shocks"],
            "factor_correlation": cfg["factor_correlation"],
        }
        for key, cfg in DEFAULT_SCENARIOS.items()
    ]


def _scenario_impact_on_ticker(ticker: str, sector: str, scenario: Dict[str, Any], ticker_beta: float) -> float:
    """Estima retorno percentual de um ativo sob um cenário (aproximação heurística)."""
    shocks = scenario.get("shocks", {})
    base = 0.0
    for factor, shock in shocks.items():
        sens = _sector_sensitivity(sector, factor)
        if factor == "equity":
            # Beta ajusta a magnitude do choque de mercado.
            base += shock * ticker_beta * sens
        else:
            base += shock * sens
    # Volatilidade implícita: aumenta drawdown proporcionalmente à exposição
    vol_shock = shocks.get("volatility", 0.0)
    if vol_shock:
        base -= 0.05 * vol_shock * max(0.0, _sector_sensitivity(sector, "volatility"))
    return base


def stress_test_portfolio(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
    scenario_id: Optional[str] = None,
    custom_shocks: Optional[Dict[str, float]] = None,
    horizon_days: int = 252,
) -> Dict[str, Any]:
    """Stress-test da carteira contra um cenário (template ou custom)."""
    tickers, w = portfolio_service._get_tickers_and_weights(tickers, weights)
    rows = portfolio_service.enrich_tickers(tickers)

    scenario = None
    if scenario_id and scenario_id in DEFAULT_SCENARIOS:
        scenario = DEFAULT_SCENARIOS[scenario_id]
    elif custom_shocks:
        scenario = {
            "label": "Cenário personalizado",
            "description": "Choques definidos pelo utilizador.",
            "shocks": custom_shocks,
            "factor_correlation": 0.5,
            "probability": None,
        }
    else:
        return {"error": "Indica um cenário (scenario_id) ou choques personalizados (custom_shocks).", "tickers": tickers}

    impacts = []
    portfolio_impact = 0.0
    for i, t in enumerate(tickers):
        sector = _ticker_sector(t, rows) or "default"
        beta = _ticker_beta(t, rows)
        impact = _scenario_impact_on_ticker(t, sector, scenario, beta)
        annualized = impact
        # Escalar para o horizonte pedido (aproximado diário).
        scaled = annualized * (horizon_days / TRADING_DAYS)
        impacts.append(
            {
                "ticker": t,
                "sector": sector,
                "weight": round(float(w[i]), 4),
                "beta": round(beta, 2),
                "scenario_return": round(scaled * 100, 2),
                "annualized_return": round(annualized * 100, 2),
            }
        )
        portfolio_impact += float(w[i]) * scaled

    # Volatilidade esperada no cenário: aumenta com correlação e vol shock.
    returns, valid = get_aligned_returns(tickers, period="1y")
    base_vol = 0.15
    if not returns.empty and len(valid) > 0:
        port_ret = (returns[valid].values @ w).flatten() if set(valid).issubset(returns.columns) else []
        if len(port_ret):
            base_vol = float(np.std(port_ret) * math.sqrt(TRADING_DAYS))
    vol_multiplier = 1.0 + abs(scenario.get("shocks", {}).get("volatility", 0.0)) * scenario.get("factor_correlation", 0.5)
    scenario_vol = base_vol * vol_multiplier

    # VaR paramétrico no cenário stressado.
    var_95 = -1.645 * scenario_vol
    cvar_95 = -2.06 * scenario_vol

    return {
        "scenario_id": scenario_id or "custom",
        "scenario_label": scenario["label"],
        "scenario_description": scenario["description"],
        "horizon_days": horizon_days,
        "probability": scenario.get("probability"),
        "portfolio_impact_pct": round(portfolio_impact * 100, 2),
        "scenario_volatility_pct": round(scenario_vol * 100, 2),
        "var_95_pct": round(var_95 * 100, 2),
        "cvar_95_pct": round(cvar_95 * 100, 2),
        "tickers": impacts,
        "shocks": scenario.get("shocks"),
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Backtest simples de estratégias
# ---------------------------------------------------------------------------
def _sma_signal(series: pd.Series, fast: int, slow: int) -> pd.Series:
    fast_sma = series.rolling(window=fast).mean()
    slow_sma = series.rolling(window=slow).mean()
    return (fast_sma > slow_sma).astype(int).diff().fillna(0)


def _rsi_signal(series: pd.Series, window: int = 14, oversold: float = 30, overbought: float = 70) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    position: pd.Series = pd.Series(0, index=series.index)
    for i in range(1, len(rsi)):
        if rsi.iloc[i] < oversold:
            position.iloc[i] = 1
        elif rsi.iloc[i] > overbought:
            position.iloc[i] = 0
        else:
            position.iloc[i] = position.iloc[i - 1]
    return position.diff().fillna(0)


def _momentum_signal(series: pd.Series, lookback: int = 90) -> pd.Series:
    momentum = series.pct_change(periods=lookback)
    position = (momentum > 0).astype(int)
    return position.diff().fillna(0)


def backtest_strategy(
    tickers: List[str],
    strategy: str = "sma-cross",
    weights: Optional[List[float]] = None,
    initial_cash: float = 100_000.0,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Backtest simples sobre histórico real com rebalanceamento diário."""
    params = params or {}
    if not tickers:
        return {"error": "Indica pelo menos um ticker para testar a estratégia."}

    returns, valid = get_aligned_returns(tickers, period="2y")
    if returns.empty or len(valid) == 0:
        return {"error": "Dados históricos insuficientes.", "tickers": tickers}

    w = _normalise_weights(weights if weights and len(weights) == len(valid) else [1.0] * len(valid))
    w_series = pd.Series(w, index=valid)

    strategy_signals: Dict[str, pd.Series] = {}
    for t in valid:
        close = portfolio_service._fetch_history(t, period="2y", interval="1d")
        if close.empty or "Close" not in close.columns:
            continue
        series = close.set_index("Date")["Close"].dropna()
        if strategy == "sma-cross":
            signal = _sma_signal(series, params.get("fast", 20), params.get("slow", 50))
        elif strategy == "rsi-mean-reversion":
            signal = _rsi_signal(series, params.get("window", 14), params.get("oversold", 30), params.get("overbought", 70))
        elif strategy == "momentum":
            signal = _momentum_signal(series, params.get("lookback", 90))
        else:
            return {"error": f"Estratégia desconhecida: {strategy}. Usa sma-cross, rsi-mean-reversion ou momentum.", "tickers": tickers}
        strategy_signals[t] = signal

    # Construir série de posições: 1 = comprado, 0 = neutro. O portfólio assume
    # pesos fixos entre os ativos que estão com sinal positivo.
    active_mask = pd.DataFrame(0, index=returns.index, columns=valid, dtype=float)
    for t in valid:
        signal = strategy_signals.get(t)
        if signal is None:
            continue
        position = (signal.cumsum().clip(lower=0) > 0).astype(int)
        active_mask[t] = position.reindex(returns.index, method="ffill").fillna(0)

    # Peso efetivo: normalizado entre os ativos ativos num dado dia.
    active_weights = active_mask.multiply(w_series, axis=1)
    row_sums = active_weights.sum(axis=1).replace(0, np.nan)
    normalized_weights = active_weights.div(row_sums, axis=0).fillna(0)

    strategy_returns = (normalized_weights.shift(1) * returns).sum(axis=1).dropna()
    buyhold_returns = (w_series * returns).sum(axis=1)

    strategy_cum = (1 + strategy_returns).cumprod()
    buyhold_cum = (1 + buyhold_returns).cumprod()

    def _metrics(r: pd.Series) -> Dict[str, Any]:
        if r.empty or r.std() == 0:
            return {"total_return": 0.0, "annualized_return": 0.0, "volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "trades": 0}
        total = float((1 + r).prod() - 1)
        ann_ret = float(r.mean() * TRADING_DAYS)
        vol = float(r.std() * math.sqrt(TRADING_DAYS))
        sharpe = ann_ret / vol if vol else 0.0
        cum = (1 + r).cumprod()
        mdd = float((cum / cum.cummax() - 1).min())
        return {
            "total_return_pct": round(total * 100, 2),
            "annualized_return_pct": round(ann_ret * 100, 2),
            "volatility_pct": round(vol * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(mdd * 100, 2),
        }

    strategy_metrics = _metrics(strategy_returns)
    buyhold_metrics = _metrics(buyhold_returns)
    strategy_metrics["trades"] = sum(int((signal != 0).sum()) for signal in strategy_signals.values())

    equity_curve = [
        {"date": str(date), "strategy": float(strategy_cum.iloc[i]), "buyhold": float(buyhold_cum.iloc[i])}
        for i, date in enumerate(strategy_cum.index)
    ]

    return {
        "strategy": strategy,
        "tickers": valid,
        "weights": [round(float(x), 4) for x in w.tolist()],
        "initial_cash": initial_cash,
        "final_value_strategy": round(initial_cash * float(strategy_cum.iloc[-1]), 2),
        "final_value_buyhold": round(initial_cash * float(buyhold_cum.iloc[-1]), 2),
        "strategy_metrics": strategy_metrics,
        "buyhold_metrics": buyhold_metrics,
        "equity_curve": equity_curve,
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Sinais de trading (IA com fallback heurístico)
# ---------------------------------------------------------------------------
def _build_signal_prompt(ticker: str, indicators: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    info = next((r for r in rows if r.get("ticker") == ticker), {})
    price = info.get("price") or indicators.get("last_price")
    rsi = indicators.get("rsi14")
    macd = indicators.get("macd")
    signal = indicators.get("macd_signal")
    sma20 = indicators.get("sma20")
    sma50 = indicators.get("sma50")
    return (
        f"Analisa o ativo {ticker} ({info.get('name', ticker)}).\n"
        f"Preço atual: {price}\n"
        f"Indicadores técnicos: RSI(14)={rsi}, MACD={macd}, sinal MACD={signal}, "
        f"SMA20={sma20}, SMA50={sma50}, beta={info.get('beta')}.\n"
        "Dá uma recomendação de trading em português europeu (Comprar, Vender ou Neutro), "
        "justifica em 2-3 linhas e estima confiança (0-100%). Responde apenas com JSON: "
        '{"signal": "comprar|vender|neutro", "confidence": 0-100, "rationale": "...", "time_horizon": "curto prazo|médio prazo", "stop_loss": "...", "take_profit": "..."}'
    )


def _heuristic_signal(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Sinal heurístico quando LLM não está disponível."""
    rsi = indicators.get("rsi14")
    macd = indicators.get("macd")
    signal = indicators.get("macd_signal")
    price = indicators.get("last_price")
    sma20 = indicators.get("sma20")
    sma50 = indicators.get("sma50")

    score = 0
    reasons = []
    if rsi is not None and rsi < 30:
        score += 2
        reasons.append("RSI sobrevendido")
    elif rsi is not None and rsi > 70:
        score -= 2
        reasons.append("RSI sobrecomprado")
    if macd is not None and signal is not None and macd > signal:
        score += 1
        reasons.append("MACD acima do sinal")
    elif macd is not None and signal is not None:
        score -= 1
        reasons.append("MACD abaixo do sinal")
    if price is not None and sma20 is not None and price > sma20:
        score += 1
        reasons.append("preço acima da SMA20")
    if price is not None and sma50 is not None and price > sma50:
        score += 1
        reasons.append("preço acima da SMA50")
    elif price is not None and sma50 is not None:
        score -= 1
        reasons.append("preço abaixo da SMA50")

    if score >= 2:
        sig = "comprar"
        confidence = min(95, 50 + score * 10)
    elif score <= -2:
        sig = "vender"
        confidence = min(95, 50 - score * 10)
    else:
        sig = "neutro"
        confidence = max(40, 50 - abs(score) * 5)

    stop = None
    target = None
    if price:
        if sig == "comprar":
            stop = round(price * 0.95, 2)
            target = round(price * 1.08, 2)
        elif sig == "vender":
            stop = round(price * 1.05, 2)
            target = round(price * 0.92, 2)

    return {
        "signal": sig,
        "confidence": confidence,
        "rationale": "; ".join(reasons) if reasons else "Indicadores mistos sem direção clara.",
        "time_horizon": "curto prazo",
        "stop_loss": stop,
        "take_profit": target,
        "source": "heuristic",
    }


async def _try_llm_signal(prompt: str) -> Optional[Dict[str, Any]]:
    """Tenta obter sinal via LLM cloud. Devolve None se indisponível."""
    try:
        from api import ontology_ai

        backend = ontology_ai.available_backend(None)
        if backend.get("kind") != "cloud":
            return None
        text = await ontology_ai.ask_model(
            backend,
            system=(
                "És um analista técnico de mercado. Responde sempre em JSON válido "
                "com os campos signal, confidence, rationale, time_horizon, stop_loss, take_profit. "
                "Não incluas Markdown."
            ),
            prompt=prompt,
            max_tokens=512,
            temperature=0.2,
        )
        parsed = _extract_json(text)
        if parsed and "signal" in parsed:
            parsed["signal"] = _normalise_signal(parsed["signal"])
            parsed["source"] = "llm"
            return parsed
    except Exception as exc:
        logger.debug("LLM signal indisponível: %s", exc)
    return None


def _normalise_signal(value: str) -> str:
    v = str(value).lower().strip()
    if v in {"comprar", "buy", "long"}:
        return "comprar"
    if v in {"vender", "sell", "short"}:
        return "vender"
    return "neutro"


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrai o primeiro objeto JSON de uma resposta."""
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1]
        match = json.loads(text)
        if isinstance(match, dict):
            return match
    except Exception:
        pass
    # Procurar objeto entre chaves.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return None


def _compute_indicators(ticker: str) -> Dict[str, Any]:
    """Indicadores técnicos simples para alimentar o sinal."""
    df = portfolio_service._fetch_history(ticker, period="6mo", interval="1d")
    if df.empty or "Close" not in df.columns:
        return {"error": "Sem dados históricos"}
    close = df["Close"].astype(float)
    dates = df["Date"].astype(str).tolist()

    def sma(window: int) -> float:
        return float(close.rolling(window=window).mean().iloc[-1])

    def ema(span: int) -> pd.Series:
        return close.ewm(span=span, adjust=False).mean()

    def rsi(window: int = 14) -> float:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=window).mean()
        avg_loss = loss.rolling(window=window).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return float(100 - (100 / (1 + rs)).iloc[-1])

    ema12 = ema(12)
    ema26 = ema(26)
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    return {
        "ticker": ticker,
        "last_price": float(close.iloc[-1]),
        "sma20": sma(20),
        "sma50": sma(50),
        "rsi14": rsi(14),
        "macd": float(macd_line.iloc[-1]),
        "macd_signal": float(macd_signal.iloc[-1]),
        "dates": dates[-60:],
        "prices": close.tail(60).tolist(),
    }


async def generate_trading_signal(
    tickers: List[str],
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Gera sinais de trading para uma lista de tickers."""
    if not tickers:
        return {"error": "Indica pelo menos um ticker."}
    rows = portfolio_service.enrich_tickers(tickers)
    signals = []
    for t in tickers:
        indicators = _compute_indicators(t)
        if "error" in indicators:
            signals.append({"ticker": t, "error": indicators["error"]})
            continue
        llm_result = None
        if use_llm:
            prompt = _build_signal_prompt(t, indicators, rows)
            llm_result = await _try_llm_signal(prompt)
        result = llm_result or _heuristic_signal(indicators)
        result["ticker"] = t
        result["indicators"] = indicators
        signals.append(result)

    return {
        "signals": signals,
        "count": len(signals),
        "llm_enabled": use_llm,
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Simulador "what-if" de ordens
# ---------------------------------------------------------------------------
def simulate_orders(
    tickers: List[str],
    weights: Optional[List[float]] = None,
    orders: Optional[List[Dict[str, Any]]] = None,
    initial_value: float = 100_000.0,
) -> Dict[str, Any]:
    """Simula o impacto de ordens de compra/venda numa carteira."""
    if not tickers:
        return {"error": "Indica pelo menos um ticker base."}
    tickers, w = portfolio_service._get_tickers_and_weights(tickers, weights)
    rows = portfolio_service.enrich_tickers(tickers)
    prices = {r["ticker"]: _safe_float(r.get("price"), 0.0) or 0.0 for r in rows}

    orders = orders or []
    # Valor inicial da carteira (posições atuais).
    current_shares = {t: (initial_value * float(w[i])) / prices[t] if prices[t] else 0.0 for i, t in enumerate(tickers)}
    cash = 0.0
    trades = []
    for order in orders:
        ticker = str(order.get("ticker") or "").upper()
        side = str(order.get("side") or "").lower()
        quantity = float(order.get("quantity") or 0)
        price = _safe_float(order.get("price"), prices.get(ticker)) or prices.get(ticker) or 0.0
        if not ticker or ticker not in prices or not price or quantity <= 0:
            continue
        notional = quantity * price
        fee_rate = float(order.get("fee_rate") or 0.001)
        fees = notional * fee_rate
        if side == "buy":
            cash -= notional + fees
            current_shares[ticker] = current_shares.get(ticker, 0.0) + quantity
        elif side == "sell":
            cash += notional - fees
            current_shares[ticker] = max(0.0, current_shares.get(ticker, 0.0) - quantity)
        trades.append({"ticker": ticker, "side": side, "quantity": quantity, "price": price, "fees": round(fees, 2)})

    final_value = cash + sum(current_shares.get(t, 0.0) * prices.get(t, 0.0) for t in tickers)
    new_weights = []
    for t in tickers:
        val = current_shares.get(t, 0.0) * prices.get(t, 0.0)
        new_weights.append(round(val / final_value, 4) if final_value else 0.0)

    return {
        "initial_value": round(initial_value, 2),
        "final_value": round(final_value, 2),
        "cash_remaining": round(cash, 2),
        "pnl_pct": round((final_value / initial_value - 1) * 100, 2),
        "trades": trades,
        "holdings": [
            {
                "ticker": t,
                "shares": round(current_shares.get(t, 0.0), 4),
                "price": prices.get(t),
                "weight": new_weights[i],
                "value": round(current_shares.get(t, 0.0) * prices.get(t, 0.0), 2),
            }
            for i, t in enumerate(tickers)
        ],
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Simulador de choques com Monte Carlo
# ---------------------------------------------------------------------------
def monte_carlo_shock_simulation(
    tickers: List[str],
    weights: Optional[List[float]] = None,
    horizon_days: int = 60,
    simulations: int = 500,
    shock_probability: float = 0.05,
    shock_mean: float = -0.03,
    shock_std: float = 0.05,
) -> Dict[str, Any]:
    """Simula trajetórias de preço com choques aleatórios e devolve percentis."""
    tickers, w = portfolio_service._get_tickers_and_weights(tickers, weights)
    returns, valid = get_aligned_returns(tickers, period="2y")
    if returns.empty or len(valid) == 0:
        return {"error": "Dados históricos insuficientes para Monte Carlo.", "tickers": tickers}

    w_valid = _normalise_weights([w[tickers.index(t)] if t in tickers else 0.0 for t in valid])
    port_returns = (returns[valid].values @ w_valid).flatten()
    mu = float(port_returns.mean())
    sigma = float(port_returns.std())

    rows = portfolio_service.enrich_tickers(tickers)
    current_value = sum(
        _safe_float(next((r.get("price") for r in rows if r.get("ticker") == t), 0.0), 0.0) * w_valid[i]
        for i, t in enumerate(valid)
    )
    if current_value <= 0:
        current_value = 100_000.0

    np.random.seed(42)
    daily_returns = np.random.normal(mu, sigma, size=(simulations, horizon_days))
    shocks = np.random.binomial(1, shock_probability, size=(simulations, horizon_days))
    shock_sizes = np.random.normal(shock_mean, shock_std, size=(simulations, horizon_days))
    daily_returns += shocks * shock_sizes

    cumulative = np.cumprod(1 + daily_returns, axis=1)
    values = current_value * cumulative

    percentiles = [5, 25, 50, 75, 95]
    paths = {p: np.percentile(values, p, axis=0).tolist() for p in percentiles}

    # Cenário extremo (pior 1%).
    worst_final = np.percentile(values[:, -1], 1)
    best_final = np.percentile(values[:, -1], 99)
    prob_loss = float(np.mean(values[:, -1] < current_value))

    return {
        "initial_value": round(current_value, 2),
        "horizon_days": horizon_days,
        "simulations": simulations,
        "shock_probability": shock_probability,
        "shock_mean_pct": round(shock_mean * 100, 2),
        "shock_std_pct": round(shock_std * 100, 2),
        "median_final_value": round(float(np.median(values[:, -1])), 2),
        "worst_1pct_final_value": round(float(worst_final), 2),
        "best_1pct_final_value": round(float(best_final), 2),
        "probability_of_loss_pct": round(prob_loss * 100, 2),
        "var_95_pct": round(float(np.percentile(values[:, -1] / current_value - 1, 5) * 100), 2),
        "paths": {
            "dates": [(datetime.utcnow() + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(horizon_days)],
            "percentiles": {str(p): [round(v, 2) for v in vals] for p, vals in paths.items()},
        },
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Sumário combinado do módulo
# ---------------------------------------------------------------------------
def scenarios_summary(
    tickers: Optional[List[str]] = None,
    weights: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Dados agregados para a página inicial do módulo."""
    tickers, w = portfolio_service._get_tickers_and_weights(tickers, weights)
    rows = portfolio_service.enrich_tickers(tickers)
    returns, valid = get_aligned_returns(tickers, period="1y")
    vol = 0.15
    if not returns.empty and len(valid) > 0:
        w_valid = _normalise_weights([w[tickers.index(t)] if t in tickers else 0.0 for t in valid])
        port_ret = (returns[valid].values @ w_valid).flatten()
        vol = float(np.std(port_ret) * math.sqrt(TRADING_DAYS))

    return {
        "tickers": [{"ticker": r["ticker"], "name": r.get("name"), "price": r.get("price"), "sector": r.get("sector")} for r in rows],
        "weights": [round(float(x), 4) for x in w.tolist()],
        "portfolio_volatility_pct": round(vol * 100, 2),
        "scenario_count": len(DEFAULT_SCENARIOS),
        "templates": list_scenario_templates(),
        "as_of": datetime.utcnow().isoformat() + "Z",
    }
