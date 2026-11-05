"""Rotas de gestão de carteiras, watchlists e ordens (`/portfolio/*`).

Cada conta tem o seu índice Elasticsearch (ver `api/portfolio_store.py`), pelo que
todas estas rotas exigem sessão válida — sem sessão não há índice onde escrever.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, require_session
from api import portfolio_service, portfolio_store

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class PositionIn(BaseModel):
    ticker: str
    name: Optional[str] = None
    weight: float = 0.0
    quantity: float = 0.0
    avg_price: float = 0.0
    target_price: float = 0.0
    note: str = ""


class PortfolioIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    currency: str = "USD"
    benchmark: str = "^GSPC"
    cash: float = portfolio_store.DEFAULT_CASH
    tags: List[str] = []
    tickers: List[PositionIn] = []


class PortfolioPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    currency: Optional[str] = None
    benchmark: Optional[str] = None
    cash: Optional[float] = None
    tags: Optional[List[str]] = None


class AddTickerIn(BaseModel):
    ticker: str
    name: Optional[str] = None
    weight: float = 0.0
    quantity: float = 0.0
    avg_price: float = 0.0
    target_price: float = 0.0
    note: str = ""
    fill_price: bool = Field(False, description="Preencher avg_price com a cotação actual quando não indicado.")


class WatchlistIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    items: List[PositionIn] = []


class WatchItemIn(BaseModel):
    ticker: str
    name: Optional[str] = None
    target_price: float = 0.0
    note: str = ""


class OrderIn(BaseModel):
    portfolio_id: str
    ticker: str
    side: str = Field(..., description="buy | sell")
    quantity: float = Field(..., gt=0)
    order_type: str = Field("market", description="market | limit")
    limit_price: float = 0.0
    fees: float = 0.0
    price: Optional[float] = Field(None, description="Preço de execução; sem ele usa a cotação ao vivo.")


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _owner(session: CurrentSession) -> str:
    return str(session.user.id)


def _raise_if_error(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("error"):
        raise HTTPException(status_code=int(result.get("status") or 400), detail=result["error"])
    return result


def _live_price(ticker: str) -> float:
    quote = portfolio_service._fetch_live_quote(ticker)
    price = portfolio_service._safe_float(quote.get("price"))
    if price:
        return float(price)
    info = portfolio_service._fetch_info(ticker)
    return float(portfolio_service._safe_float(info.get("price")) or 0.0)


# ---------------------------------------------------------------------------
# Pesquisa de tickers
# ---------------------------------------------------------------------------
@router.get("/search", summary="Pesquisar tickers no Yahoo Finance")
def portfolio_search(
    session: Session,
    q: str = Query(..., min_length=1, description="Símbolo ou nome da empresa"),
    limit: int = Query(12, ge=1, le=50),
) -> Dict[str, Any]:
    return portfolio_store.search_tickers(q, limit=limit)


# ---------------------------------------------------------------------------
# Carteiras
# ---------------------------------------------------------------------------
@router.get("/portfolios", summary="Listar carteiras do utilizador")
def list_portfolios(session: Session) -> Dict[str, Any]:
    return portfolio_store.list_portfolios(_owner(session))


@router.post("/portfolios", status_code=201, summary="Criar carteira")
def create_portfolio(body: PortfolioIn, session: Session) -> Dict[str, Any]:
    return _raise_if_error(
        portfolio_store.create_portfolio(
            _owner(session),
            name=body.name,
            description=body.description,
            currency=body.currency,
            benchmark=body.benchmark,
            cash=body.cash,
            tickers=[t.model_dump() for t in body.tickers],
            tags=body.tags,
        )
    )


@router.get("/portfolios/{portfolio_id}", summary="Detalhe de uma carteira")
def get_portfolio(portfolio_id: str, session: Session) -> Dict[str, Any]:
    portfolio = portfolio_store.get_portfolio(_owner(session), portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")
    return portfolio


@router.patch("/portfolios/{portfolio_id}", summary="Actualizar carteira")
def patch_portfolio(portfolio_id: str, body: PortfolioPatch, session: Session) -> Dict[str, Any]:
    return _raise_if_error(
        portfolio_store.update_portfolio(
            _owner(session), portfolio_id, {k: v for k, v in body.model_dump().items() if v is not None}
        )
    )


@router.delete("/portfolios/{portfolio_id}", summary="Apagar carteira")
def delete_portfolio(portfolio_id: str, session: Session) -> Dict[str, Any]:
    return _raise_if_error(portfolio_store.delete_portfolio(_owner(session), portfolio_id))


@router.post("/portfolios/{portfolio_id}/tickers", summary="Adicionar ticker a uma carteira")
def add_ticker(portfolio_id: str, body: AddTickerIn, session: Session) -> Dict[str, Any]:
    avg_price = body.avg_price
    if body.fill_price and not avg_price:
        avg_price = _live_price(body.ticker)
    name = body.name
    if not name:
        info = portfolio_service._fetch_info(body.ticker)
        name = info.get("name") or None
    return _raise_if_error(
        portfolio_store.add_ticker(
            _owner(session),
            portfolio_id,
            ticker=body.ticker,
            weight=body.weight,
            quantity=body.quantity,
            avg_price=avg_price,
            name=name or "",
            target_price=body.target_price,
            note=body.note,
        )
    )


@router.delete("/portfolios/{portfolio_id}/tickers/{ticker}", summary="Remover ticker de uma carteira")
def remove_ticker(portfolio_id: str, ticker: str, session: Session) -> Dict[str, Any]:
    return _raise_if_error(portfolio_store.remove_ticker(_owner(session), portfolio_id, ticker))


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
@router.get("/watchlists", summary="Listar watchlists do utilizador")
def list_watchlists(session: Session) -> Dict[str, Any]:
    return portfolio_store.list_watchlists(_owner(session))


@router.post("/watchlists", status_code=201, summary="Criar watchlist")
def create_watchlist(body: WatchlistIn, session: Session) -> Dict[str, Any]:
    return _raise_if_error(
        portfolio_store.create_watchlist(
            _owner(session),
            name=body.name,
            description=body.description,
            items=[i.model_dump() for i in body.items],
        )
    )


@router.delete("/watchlists/{watchlist_id}", summary="Apagar watchlist")
def delete_watchlist(watchlist_id: str, session: Session) -> Dict[str, Any]:
    return _raise_if_error(portfolio_store.delete_watchlist(_owner(session), watchlist_id))


@router.post("/watchlists/{watchlist_id}/items", summary="Adicionar ticker a uma watchlist")
def add_watch_item(watchlist_id: str, body: WatchItemIn, session: Session) -> Dict[str, Any]:
    name = body.name
    if not name:
        info = portfolio_service._fetch_info(body.ticker)
        name = info.get("name") or None
    return _raise_if_error(
        portfolio_store.add_watchlist_item(
            _owner(session),
            watchlist_id,
            ticker=body.ticker,
            name=name or "",
            target_price=body.target_price,
            note=body.note,
        )
    )


@router.delete("/watchlists/{watchlist_id}/items/{ticker}", summary="Remover ticker de uma watchlist")
def remove_watch_item(watchlist_id: str, ticker: str, session: Session) -> Dict[str, Any]:
    return _raise_if_error(portfolio_store.remove_watchlist_item(_owner(session), watchlist_id, ticker))


# ---------------------------------------------------------------------------
# Ordens
# ---------------------------------------------------------------------------
@router.get("/orders", summary="Listar ordens do utilizador")
def list_orders(
    session: Session,
    portfolio_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    return portfolio_store.list_orders(_owner(session), portfolio_id=portfolio_id, limit=limit)


@router.post("/orders", status_code=201, summary="Registar e executar uma ordem")
def place_order(body: OrderIn, session: Session) -> Dict[str, Any]:
    price = body.price
    if price is None:
        price = _live_price(body.ticker)
    result = portfolio_store.place_order(
        _owner(session),
        portfolio_id=body.portfolio_id,
        ticker=body.ticker,
        side=body.side,
        quantity=body.quantity,
        order_type=body.order_type,
        limit_price=body.limit_price,
        price=price,
        fees=body.fees,
    )
    _raise_if_error(result)
    if result.get("status") == "rejected":
        raise HTTPException(status_code=409, detail="Ordem rejeitada: caixa insuficiente ou posição inexistente.")
    return result


@router.post("/orders/{order_id}/cancel", summary="Cancelar uma ordem pendente")
def cancel_order(order_id: str, session: Session) -> Dict[str, Any]:
    return _raise_if_error(portfolio_store.cancel_order(_owner(session), order_id))
