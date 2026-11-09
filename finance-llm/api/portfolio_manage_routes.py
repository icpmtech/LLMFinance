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
from datetime import datetime

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


class UpdateTickerIn(BaseModel):
    name: Optional[str] = None
    weight: Optional[float] = None
    quantity: Optional[float] = None
    avg_price: Optional[float] = None
    target_price: Optional[float] = None
    note: Optional[str] = None


class CsvRowIn(BaseModel):
    symbol: str
    side: Optional[str] = Field(None, description="buy | sell | deposit")
    quantity: Optional[float] = None
    price: Optional[float] = None
    fees: Optional[float] = 0.0
    date: Optional[str] = None
    note: Optional[str] = None


class CsvImportIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    currency: str = "USD"
    deposit_cash: bool = Field(True, description="Usar DEPOSIT como caixa inicial da carteira.")
    future_dates_as_today: bool = Field(True, description="Tratar datas futuras como hoje.")
    rows: List[CsvRowIn] = []



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


@router.get("/sources", summary="Carteiras e watchlists do utilizador (com tickers)")
def portfolio_sources(session: Session) -> Dict[str, Any]:
    """Universo de dados do utilizador: escolhe-se a carteira onde os módulos se baseiam."""
    owner = _owner(session)
    portfolios = portfolio_store.list_portfolios(owner).get("items") or []
    watchlists = portfolio_store.list_watchlists(owner).get("items") or []
    return {
        "portfolios": portfolios,
        "watchlists": watchlists,
        "has_portfolio": bool(portfolios),
        "has_watchlist": bool(watchlists),
    }


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


def _parse_csv_date(value: Optional[str], future_as_today: bool = True) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(value, fmt)
            today = datetime.utcnow().date()
            if future_as_today and dt.date() > today:
                dt = datetime.combine(today, dt.time())
            return dt.isoformat() + "Z"
        except ValueError:
            continue
    return None


def _import_csv_positions(rows: List[CsvRowIn], deposit_cash: bool, future_as_today: bool, fill_missing_price: bool = True) -> Dict[str, Any]:
    positions: Dict[str, Dict[str, Any]] = {}
    cash = 0.0
    skipped: List[Dict[str, Any]] = []
    # Cache local de cotações para não bater no Yahoo a cada linha.
    price_cache: Dict[str, float] = {}

    def _row_price(symbol: str, explicit: Optional[float]) -> Optional[float]:
        price = float(explicit or 0.0)
        if price > 0:
            return price
        if not fill_missing_price:
            return None
        if symbol not in price_cache:
            try:
                price_cache[symbol] = _live_price(symbol)
            except Exception:
                price_cache[symbol] = 0.0
        cached = price_cache.get(symbol, 0.0)
        return cached if cached > 0 else None

    # Ordenar por data para que BUYs acumulem antes dos SELLs correspondentes.
    sorted_rows = sorted(rows, key=lambda r: (_parse_csv_date(r.date or "", future_as_today) or "", r.symbol or ""))
    for idx, row in enumerate(sorted_rows, start=1):
        symbol = str(row.symbol or "").strip().upper()
        if not symbol or symbol.startswith("$") or symbol == "CASH_TX":
            side = str(row.side or "deposit").lower()
            if deposit_cash and side == "deposit" and row.quantity:
                cash += float(row.quantity)
            continue
        side = str(row.side or "").strip().lower() or ("buy" if row.quantity else "")
        qty = float(row.quantity or 0.0)
        price = _row_price(symbol, row.price)
        fees = float(row.fees or 0.0)
        if side not in {"buy", "sell"}:
            if side:
                skipped.append({"row": idx, "symbol": symbol, "reason": f"tipo desconhecido: {side}"})
            continue
        if qty <= 0 or price is None or price <= 0:
            skipped.append({"row": idx, "symbol": symbol, "reason": "quantidade/preço inválidos"})
            continue
        added_at = _parse_csv_date(row.date, future_as_today) or portfolio_store._now()
        current = positions.get(symbol)
        if side == "buy":
            if current is None:
                positions[symbol] = {
                    "ticker": symbol,
                    "name": symbol,
                    "quantity": qty,
                    "avg_price": price,
                    "fees": fees,
                    "added_at": added_at,
                    "note": row.note or "",
                }
            else:
                old_qty = float(current["quantity"])
                old_avg = float(current["avg_price"])
                total_cost = old_qty * old_avg + qty * price + fees
                new_qty = old_qty + qty
                current["quantity"] = new_qty
                current["avg_price"] = round(total_cost / new_qty, 6) if new_qty > 0 else old_avg
                current["fees"] = float(current.get("fees", 0.0)) + fees
                current["note"] = current.get("note", "") + (f"; {row.note}" if row.note else "")
                current["added_at"] = added_at
        elif side == "sell":
            if current is None:
                # SELL sem posição prévia: assume-se short-cover (ignora, mas regista).
                skipped.append({"row": idx, "symbol": symbol, "reason": "venda sem posição prévia"})
                continue
            if current["quantity"] < qty:
                # Venda parcial até ao limite existente.
                qty = current["quantity"]
            current["quantity"] -= qty
            current["note"] = current.get("note", "") + (f"; {row.note}" if row.note else "")
            if current["quantity"] <= 0:
                positions.pop(symbol, None)
    return {"positions": list(positions.values()), "cash": cash, "skipped": skipped}


@router.post("/import-csv", status_code=201, summary="Importar carteira a partir de CSV")
def import_portfolio_csv(body: CsvImportIn, session: Session) -> Dict[str, Any]:
    parsed = _import_csv_positions(
        body.rows,
        deposit_cash=body.deposit_cash,
        future_as_today=body.future_dates_as_today,
        fill_missing_price=True,
    )
    if not parsed["positions"] and parsed["cash"] <= 0:
        raise HTTPException(status_code=422, detail="O CSV não continha posições nem depósitos válidos.")
    result = portfolio_store.create_portfolio(
        _owner(session),
        name=body.name,
        currency=(body.currency or "USD").upper(),
        cash=max(float(parsed["cash"]), 0.0),
        tickers=[portfolio_store._normalise_position(p) for p in parsed["positions"]],
    )
    if result.get("error"):
        raise HTTPException(status_code=int(result.get("status") or 400), detail=result["error"])
    return {"portfolio": result, "imported": len(parsed["positions"]), "cash": parsed["cash"], "skipped": parsed["skipped"]}


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


@router.patch("/portfolios/{portfolio_id}/tickers/{ticker}", summary="Editar posição de uma carteira")
def update_ticker(portfolio_id: str, ticker: str, body: UpdateTickerIn, session: Session) -> Dict[str, Any]:
    return _raise_if_error(
        portfolio_store.update_ticker(
            _owner(session),
            portfolio_id,
            ticker=ticker,
            **{k: v for k, v in body.model_dump().items() if v is not None},
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
