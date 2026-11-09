"""Rotas do módulo "Test market scenarios - AI tools for trading".

Endpoints sob `/portfolio/scenarios/*`. O módulo partilha o prefixo do
portfólio para reaproveitar autenticação e escopo, mas é apresentado no
frontend como aplicação própria (`trading-scenarios`).
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, optional_session
from api import portfolio_scenarios_service, portfolio_service

router = APIRouter(prefix="/portfolio/scenarios", tags=["portfolio-scenarios"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


class ScenariosScopeRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="Tickers a analisar.")
    weights: Optional[List[float]] = Field(None, description="Pesos (mesma ordem dos tickers).")
    portfolio_id: Optional[str] = Field(None, description="Carteira guardada do utilizador.")
    watchlist_id: Optional[str] = Field(None, description="Watchlist guardada do utilizador.")


class StressTestRequest(ScenariosScopeRequest):
    scenario_id: Optional[str] = Field(None, description="ID do cenário (recession, inflation, rate_hike, ...).")
    custom_shocks: Optional[Dict[str, float]] = Field(None, description="Choques personalizados por fator.")
    horizon_days: int = Field(252, ge=1, le=1260)


class BacktestRequest(ScenariosScopeRequest):
    strategy: str = Field("sma-cross", description="sma-cross | rsi-mean-reversion | momentum")
    initial_cash: float = Field(100_000.0, gt=0)
    params: Optional[Dict[str, Any]] = Field(None, description="Parâmetros específicos da estratégia.")


class SignalRequest(ScenariosScopeRequest):
    use_llm: bool = Field(True, description="Tenta usar LLM; senão cai em heurística.")


class WhatIfRequest(ScenariosScopeRequest):
    initial_value: float = Field(100_000.0, gt=0)
    orders: List[Dict[str, Any]] = Field(default_factory=list, description="Ordens: {ticker, side, quantity, price?, fee_rate?}")


class MonteCarloRequest(ScenariosScopeRequest):
    horizon_days: int = Field(60, ge=7, le=252 * 3)
    simulations: int = Field(500, ge=100, le=5000)
    shock_probability: float = Field(0.05, ge=0.0, le=1.0)
    shock_mean: float = Field(-0.03, ge=-0.5, le=0.5)
    shock_std: float = Field(0.05, ge=0.0, le=1.0)


def _resolve_scope(
    *,
    tickers: Optional[List[str]],
    weights: Optional[List[float]],
    portfolio_id: Optional[str],
    watchlist_id: Optional[str],
    session: Optional[CurrentSession],
) -> Dict[str, Any]:
    """Resolve escopo: explícito, carteira, watchlist ou default."""
    if tickers:
        return {"tickers": [t.strip().upper() for t in tickers if t.strip()], "weights": weights, "meta": {"source": "request"}}

    user_id = str(session.user.id) if session else ""
    if user_id and portfolio_id:
        from api import portfolio_store

        scope = portfolio_store.portfolio_scope(user_id, portfolio_id)
        if scope:
            portfolio = scope["portfolio"]
            return {
                "tickers": scope["tickers"],
                "weights": scope["weights"],
                "meta": {
                    "source": "portfolio",
                    "portfolio_id": portfolio["id"],
                    "portfolio_name": portfolio.get("name"),
                    "currency": portfolio.get("currency"),
                },
            }
    if user_id and watchlist_id:
        from api import portfolio_store

        scope = portfolio_store.watchlist_scope(user_id, watchlist_id)
        if scope:
            return {
                "tickers": scope["tickers"],
                "weights": scope.get("weights"),
                "meta": {"source": "watchlist", "watchlist_id": watchlist_id, "watchlist_name": scope.get("name")},
            }

    default = portfolio_service._load_default_portfolio()
    return {
        "tickers": [p["ticker"] for p in default],
        "weights": [p.get("weight", 1.0) for p in default],
        "meta": {"source": "default"},
    }


def _with_scope(payload: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    payload["scope"] = meta
    return payload


@router.get("/templates", summary="Templates de cenários disponíveis")
def list_templates() -> List[Dict[str, Any]]:
    return portfolio_scenarios_service.list_scenario_templates()


@router.post("/summary", summary="Sumário do módulo de cenários")
def scenarios_summary(
    session: Session,
    body: ScenariosScopeRequest = Body(default_factory=ScenariosScopeRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_scenarios_service.scenarios_summary(tickers=resolved["tickers"], weights=resolved["weights"]),
        resolved["meta"],
    )


@router.post("/stress", summary="Stress-test da carteira contra cenário")
def stress_test(
    session: Session,
    body: StressTestRequest = Body(default_factory=StressTestRequest),
) -> Dict[str, Any]:
    if not body.scenario_id and not body.custom_shocks:
        raise HTTPException(status_code=422, detail="Define scenario_id ou custom_shocks.")
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_scenarios_service.stress_test_portfolio(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            scenario_id=body.scenario_id,
            custom_shocks=body.custom_shocks,
            horizon_days=body.horizon_days,
        ),
        resolved["meta"],
    )


@router.post("/backtest", summary="Backtest de estratégia de trading")
def backtest(
    session: Session,
    body: BacktestRequest = Body(default_factory=BacktestRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    if body.strategy not in {"sma-cross", "rsi-mean-reversion", "momentum"}:
        raise HTTPException(status_code=422, detail="strategy deve ser sma-cross, rsi-mean-reversion ou momentum")
    return _with_scope(
        portfolio_scenarios_service.backtest_strategy(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            strategy=body.strategy,
            initial_cash=body.initial_cash,
            params=body.params,
        ),
        resolved["meta"],
    )


@router.post("/signals", summary="Sinais de trading com IA / heurística")
async def trading_signals(
    session: Session,
    body: SignalRequest = Body(default_factory=SignalRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    tickers = resolved["tickers"]
    result = await portfolio_scenarios_service.generate_trading_signal(
        tickers=tickers,
        use_llm=body.use_llm,
    )
    return _with_scope(result, resolved["meta"])


@router.post("/what-if", summary="Simulador de ordens what-if")
def what_if(
    session: Session,
    body: WhatIfRequest = Body(default_factory=WhatIfRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_scenarios_service.simulate_orders(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            orders=body.orders,
            initial_value=body.initial_value,
        ),
        resolved["meta"],
    )


@router.post("/monte-carlo", summary="Simulador de choques com Monte Carlo")
def monte_carlo(
    session: Session,
    body: MonteCarloRequest = Body(default_factory=MonteCarloRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_scenarios_service.monte_carlo_shock_simulation(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            horizon_days=body.horizon_days,
            simulations=body.simulations,
            shock_probability=body.shock_probability,
            shock_mean=body.shock_mean,
            shock_std=body.shock_std,
        ),
        resolved["meta"],
    )
