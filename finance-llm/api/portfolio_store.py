"""Persistência de carteiras, watchlists e ordens — um índice por utilizador.

Cada conta tem o seu próprio índice Elasticsearch (`finance_portfolio_<slug>`),
criado à primeira utilização. Dentro do índice convivem três tipos de documento,
distinguidos pelo campo `kind`:

* `portfolio` — carteira com posições (`tickers`), saldo de caixa e moeda base;
* `watchlist` — lista de acompanhamento (`items`), sem valor de carteira;
* `order` — ordem registada contra uma carteira (compra/venda, mercado/limite).

O isolamento por índice garante que uma conta nunca vê nem consegue escrever nos
dados de outra, mesmo que os `_id` dos documentos coincidam.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from elasticsearch import Elasticsearch, NotFoundError

from api.es.core import get_es_client

logger = logging.getLogger(__name__)

INDEX_PREFIX = "finance_portfolio_"

ORDER_SIDES = {"buy", "sell"}
ORDER_TYPES = {"market", "limit"}
ORDER_STATUS = {"pending", "filled", "cancelled", "rejected"}

DEFAULT_CASH = 100_000.0


# ---------------------------------------------------------------------------
# Índice por utilizador
# ---------------------------------------------------------------------------
def user_index(user_id: str) -> str:
    """Nome do índice do utilizador (um índice por conta)."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(user_id or "").lower()).strip("_")
    return f"{INDEX_PREFIX}{(slug or 'anonimo')[:80]}"


def _mappings() -> Dict[str, Any]:
    return {
        "properties": {
            "kind": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "description": {"type": "text"},
            "currency": {"type": "keyword"},
            "benchmark": {"type": "keyword"},
            "cash": {"type": "double"},
            "initial_cash": {"type": "double"},
            "tags": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            # Posições da carteira.
            "tickers": {
                "type": "nested",
                "properties": {
                    "ticker": {"type": "keyword"},
                    "name": {"type": "keyword"},
                    "weight": {"type": "double"},
                    "quantity": {"type": "double"},
                    "avg_price": {"type": "double"},
                    "target_price": {"type": "double"},
                    "note": {"type": "text"},
                    "added_at": {"type": "date"},
                },
            },
            # Itens da watchlist.
            "items": {
                "type": "nested",
                "properties": {
                    "ticker": {"type": "keyword"},
                    "name": {"type": "keyword"},
                    "target_price": {"type": "double"},
                    "note": {"type": "text"},
                    "added_at": {"type": "date"},
                },
            },
            # Ordens.
            "order_id": {"type": "keyword"},
            "portfolio_id": {"type": "keyword"},
            "ticker": {"type": "keyword"},
            "side": {"type": "keyword"},
            "order_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "quantity": {"type": "double"},
            "limit_price": {"type": "double"},
            "filled_price": {"type": "double"},
            "filled_quantity": {"type": "double"},
            "notional": {"type": "double"},
            "fees": {"type": "double"},
            "placed_at": {"type": "date"},
            "executed_at": {"type": "date"},
        }
    }


def ensure_user_index(user_id: str, es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    """Cria o índice do utilizador se ainda não existir e devolve o cliente."""
    client = es or get_es_client()
    if not client:
        return None
    index = user_index(user_id)
    try:
        if not client.indices.exists(index=index):
            client.indices.create(index=index, mappings=_mappings())
    except Exception as exc:  # pragma: no cover - depende do servidor
        logger.warning("Não foi possível preparar o índice %s: %s", index, exc)
        return None
    return client


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _get(client: Elasticsearch, index: str, doc_id: str) -> Optional[Dict[str, Any]]:
    try:
        hit = client.get(index=index, id=doc_id)
    except NotFoundError:
        return None
    doc = dict(hit.get("_source") or {})
    doc["id"] = hit.get("_id")
    return doc


def _save(client: Elasticsearch, index: str, doc_id: str, body: Dict[str, Any]) -> None:
    client.index(index=index, id=doc_id, document=body, refresh=True)


def _delete(client: Elasticsearch, index: str, doc_id: str) -> bool:
    try:
        client.delete(index=index, id=doc_id, refresh=True)
        return True
    except NotFoundError:
        return False


def _search(
    client: Elasticsearch,
    index: str,
    filters: List[Dict[str, Any]],
    size: int = 200,
    sort: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    body: Dict[str, Any] = {
        "query": {"bool": {"filter": filters}},
        "size": max(1, min(int(size), 1000)),
        "sort": sort or [{"updated_at": {"order": "desc", "missing": "_last"}}],
    }
    resp = client.search(index=index, body=body)
    out = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        doc = dict(hit.get("_source") or {})
        doc["id"] = hit.get("_id")
        out.append(doc)
    return out


# ---------------------------------------------------------------------------
# Carteiras
# ---------------------------------------------------------------------------
def list_portfolios(user_id: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"items": [], "error": "Elasticsearch indisponível"}
    docs = _search(client, user_index(user_id), [{"term": {"kind": "portfolio"}}])
    return {"items": [_portfolio_public(d) for d in docs]}


def _portfolio_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    tickers = doc.get("tickers") or []
    return {
        "id": doc.get("id"),
        "name": doc.get("name") or "Carteira",
        "description": doc.get("description") or "",
        "currency": doc.get("currency") or "USD",
        "benchmark": doc.get("benchmark") or "^GSPC",
        "cash": float(doc.get("cash") or 0.0),
        "initial_cash": float(doc.get("initial_cash") or 0.0),
        "tags": doc.get("tags") or [],
        "tickers": tickers,
        "ticker_count": len(tickers),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def get_portfolio(user_id: str, portfolio_id: str) -> Optional[Dict[str, Any]]:
    client = ensure_user_index(user_id)
    if not client:
        return None
    doc = _get(client, user_index(user_id), portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return None
    return _portfolio_public(doc)


def create_portfolio(
    user_id: str,
    name: str,
    description: str = "",
    currency: str = "USD",
    benchmark: str = "^GSPC",
    cash: float = DEFAULT_CASH,
    tickers: Optional[List[Dict[str, Any]]] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    portfolio_id = _new_id("pf")
    now = _now()
    body = {
        "kind": "portfolio",
        "owner_id": user_id,
        "name": name or "Nova carteira",
        "description": description,
        "currency": (currency or "USD").upper(),
        "benchmark": benchmark or "^GSPC",
        "cash": float(cash),
        "initial_cash": float(cash),
        "tags": tags or [],
        "tickers": [_normalise_position(t) for t in (tickers or [])],
        "created_at": now,
        "updated_at": now,
    }
    _save(client, user_index(user_id), portfolio_id, body)
    body["id"] = portfolio_id
    return _portfolio_public(body)


def _normalise_position(raw: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(raw.get("ticker") or "").strip().upper()
    return {
        "ticker": ticker,
        "name": raw.get("name") or ticker,
        "weight": float(raw.get("weight") or 0.0),
        "quantity": float(raw.get("quantity") or 0.0),
        "avg_price": float(raw.get("avg_price") or 0.0),
        "target_price": float(raw.get("target_price") or 0.0),
        "note": raw.get("note") or "",
        "added_at": raw.get("added_at") or _now(),
    }


def update_portfolio(user_id: str, portfolio_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return {"error": "Carteira não encontrada", "status": 404}
    for field in ("name", "description", "currency", "benchmark", "tags"):
        if field in changes and changes[field] is not None:
            doc[field] = changes[field]
    if changes.get("cash") is not None:
        doc["cash"] = float(changes["cash"])
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, portfolio_id, doc)
    return _portfolio_public({**doc, "id": portfolio_id})


def delete_portfolio(user_id: str, portfolio_id: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return {"error": "Carteira não encontrada", "status": 404}
    _delete(client, index, portfolio_id)
    return {"deleted": portfolio_id}


# ---------------------------------------------------------------------------
# Posições (adicionar/remover tickers)
# ---------------------------------------------------------------------------
def add_ticker(
    user_id: str,
    portfolio_id: str,
    ticker: str,
    weight: float = 0.0,
    quantity: float = 0.0,
    avg_price: float = 0.0,
    name: str = "",
    target_price: float = 0.0,
    note: str = "",
) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return {"error": "Carteira não encontrada", "status": 404}

    code = str(ticker or "").strip().upper()
    if not code:
        return {"error": "Ticker em falta", "status": 422}

    positions = doc.get("tickers") or []
    for position in positions:
        if position.get("ticker") == code:
            # Já existe: acumula quantidade e recalcula o preço médio.
            if quantity:
                old_qty = float(position.get("quantity") or 0.0)
                old_avg = float(position.get("avg_price") or 0.0)
                new_qty = old_qty + float(quantity)
                if new_qty > 0:
                    position["avg_price"] = round(
                        (old_qty * old_avg + float(quantity) * float(avg_price or old_avg)) / new_qty, 6
                    )
                position["quantity"] = new_qty
            if weight:
                position["weight"] = float(weight)
            if target_price:
                position["target_price"] = float(target_price)
            if note:
                position["note"] = note
            if name:
                position["name"] = name
            doc["tickers"] = positions
            doc["updated_at"] = _now()
            doc.pop("id", None)
            _save(client, index, portfolio_id, doc)
            return _portfolio_public({**doc, "id": portfolio_id})

    positions.append(
        _normalise_position(
            {
                "ticker": code,
                "name": name or code,
                "weight": weight,
                "quantity": quantity,
                "avg_price": avg_price,
                "target_price": target_price,
                "note": note,
            }
        )
    )
    doc["tickers"] = positions
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, portfolio_id, doc)
    return _portfolio_public({**doc, "id": portfolio_id})


def remove_ticker(user_id: str, portfolio_id: str, ticker: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return {"error": "Carteira não encontrada", "status": 404}

    code = str(ticker or "").strip().upper()
    before = len(doc.get("tickers") or [])
    doc["tickers"] = [p for p in (doc.get("tickers") or []) if p.get("ticker") != code]
    if len(doc["tickers"]) == before:
        return {"error": "Ticker não existe na carteira", "status": 404}
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, portfolio_id, doc)
    return _portfolio_public({**doc, "id": portfolio_id})


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
def list_watchlists(user_id: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"items": [], "error": "Elasticsearch indisponível"}
    docs = _search(client, user_index(user_id), [{"term": {"kind": "watchlist"}}])
    return {"items": [_watchlist_public(d) for d in docs]}


def _watchlist_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    items = doc.get("items") or []
    return {
        "id": doc.get("id"),
        "name": doc.get("name") or "Watchlist",
        "description": doc.get("description") or "",
        "items": items,
        "item_count": len(items),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def create_watchlist(user_id: str, name: str, description: str = "", items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    watchlist_id = _new_id("wl")
    now = _now()
    body = {
        "kind": "watchlist",
        "owner_id": user_id,
        "name": name or "Nova watchlist",
        "description": description,
        "items": [_normalise_watch_item(i) for i in (items or [])],
        "created_at": now,
        "updated_at": now,
    }
    _save(client, user_index(user_id), watchlist_id, body)
    body["id"] = watchlist_id
    return _watchlist_public(body)


def _normalise_watch_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(raw.get("ticker") or "").strip().upper()
    return {
        "ticker": ticker,
        "name": raw.get("name") or ticker,
        "target_price": float(raw.get("target_price") or 0.0),
        "note": raw.get("note") or "",
        "added_at": raw.get("added_at") or _now(),
    }


def add_watchlist_item(
    user_id: str,
    watchlist_id: str,
    ticker: str,
    name: str = "",
    target_price: float = 0.0,
    note: str = "",
) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, watchlist_id)
    if not doc or doc.get("kind") != "watchlist":
        return {"error": "Watchlist não encontrada", "status": 404}

    code = str(ticker or "").strip().upper()
    if not code:
        return {"error": "Ticker em falta", "status": 422}
    items = doc.get("items") or []
    for item in items:
        if item.get("ticker") == code:
            if target_price:
                item["target_price"] = float(target_price)
            if note:
                item["note"] = note
            doc["items"] = items
            doc["updated_at"] = _now()
            doc.pop("id", None)
            _save(client, index, watchlist_id, doc)
            return _watchlist_public({**doc, "id": watchlist_id})

    items.append(_normalise_watch_item({"ticker": code, "name": name, "target_price": target_price, "note": note}))
    doc["items"] = items
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, watchlist_id, doc)
    return _watchlist_public({**doc, "id": watchlist_id})


def remove_watchlist_item(user_id: str, watchlist_id: str, ticker: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, watchlist_id)
    if not doc or doc.get("kind") != "watchlist":
        return {"error": "Watchlist não encontrada", "status": 404}

    code = str(ticker or "").strip().upper()
    before = len(doc.get("items") or [])
    doc["items"] = [i for i in (doc.get("items") or []) if i.get("ticker") != code]
    if len(doc["items"]) == before:
        return {"error": "Ticker não existe na watchlist", "status": 404}
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, watchlist_id, doc)
    return _watchlist_public({**doc, "id": watchlist_id})


def delete_watchlist(user_id: str, watchlist_id: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, watchlist_id)
    if not doc or doc.get("kind") != "watchlist":
        return {"error": "Watchlist não encontrada", "status": 404}
    _delete(client, index, watchlist_id)
    return {"deleted": watchlist_id}


# ---------------------------------------------------------------------------
# Ordens
# ---------------------------------------------------------------------------
def list_orders(user_id: str, portfolio_id: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"items": [], "error": "Elasticsearch indisponível"}
    filters: List[Dict[str, Any]] = [{"term": {"kind": "order"}}]
    if portfolio_id:
        filters.append({"term": {"portfolio_id": portfolio_id}})
    docs = _search(
        client,
        user_index(user_id),
        filters,
        size=limit,
        sort=[{"placed_at": {"order": "desc", "missing": "_last"}}],
    )
    return {"items": [_order_public(d) for d in docs]}


def _order_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc.get("id"),
        "order_id": doc.get("order_id") or doc.get("id"),
        "portfolio_id": doc.get("portfolio_id"),
        "ticker": doc.get("ticker"),
        "side": doc.get("side"),
        "order_type": doc.get("order_type"),
        "status": doc.get("status"),
        "quantity": float(doc.get("quantity") or 0.0),
        "limit_price": float(doc.get("limit_price") or 0.0),
        "filled_price": float(doc.get("filled_price") or 0.0),
        "filled_quantity": float(doc.get("filled_quantity") or 0.0),
        "notional": float(doc.get("notional") or 0.0),
        "fees": float(doc.get("fees") or 0.0),
        "placed_at": doc.get("placed_at"),
        "executed_at": doc.get("executed_at"),
    }


def place_order(
    user_id: str,
    portfolio_id: str,
    ticker: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    limit_price: float = 0.0,
    price: Optional[float] = None,
    fees: float = 0.0,
) -> Dict[str, Any]:
    """Regista e executa uma ordem contra a carteira.

    O preço de execução vem do mercado (`price`, cotação ao vivo). Uma ordem
    limite só é executada quando o preço de mercado a satisfaz; fora isso fica
    `pending` e pode ser cancelada. Compras debitam caixa e somam posição;
    vendas creditam caixa e reduzem posição.
    """
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, portfolio_id)
    if not doc or doc.get("kind") != "portfolio":
        return {"error": "Carteira não encontrada", "status": 404}

    code = str(ticker or "").strip().upper()
    side_norm = str(side or "").lower()
    type_norm = str(order_type or "market").lower()
    if not code:
        return {"error": "Ticker em falta", "status": 422}
    if side_norm not in ORDER_SIDES:
        return {"error": "side deve ser buy ou sell", "status": 422}
    if type_norm not in ORDER_TYPES:
        return {"error": "order_type deve ser market ou limit", "status": 422}
    if quantity <= 0:
        return {"error": "quantity deve ser positiva", "status": 422}

    market_price = float(price or 0.0)
    if market_price <= 0:
        return {"error": "Preço de mercado indisponível para este ticker", "status": 409}

    order_id = _new_id("ord")
    now = _now()
    status = "filled"
    fill_price = market_price
    if type_norm == "limit" and limit_price > 0:
        if side_norm == "buy" and market_price > limit_price:
            status = "pending"
        if side_norm == "sell" and market_price < limit_price:
            status = "pending"
        fill_price = min(market_price, limit_price) if side_norm == "buy" else max(market_price, limit_price)

    positions = doc.get("tickers") or []
    position = next((p for p in positions if p.get("ticker") == code), None)
    cash = float(doc.get("cash") or 0.0)
    notional = 0.0
    filled_qty = 0.0

    if status == "filled":
        notional = round(fill_price * quantity, 6)
        if side_norm == "buy":
            total_cost = notional + float(fees or 0.0)
            if cash < total_cost:
                status = "rejected"
            else:
                cash -= total_cost
                filled_qty = quantity
                if position is None:
                    positions.append(
                        _normalise_position({"ticker": code, "name": code, "quantity": quantity, "avg_price": fill_price})
                    )
                else:
                    old_qty = float(position.get("quantity") or 0.0)
                    old_avg = float(position.get("avg_price") or 0.0)
                    new_qty = old_qty + quantity
                    position["avg_price"] = round((old_qty * old_avg + quantity * fill_price) / new_qty, 6)
                    position["quantity"] = new_qty
        else:
            if position is None or float(position.get("quantity") or 0.0) < quantity:
                status = "rejected"
            else:
                cash += notional - float(fees or 0.0)
                filled_qty = quantity
                position["quantity"] = round(float(position.get("quantity") or 0.0) - quantity, 6)
                if position["quantity"] <= 0:
                    positions = [p for p in positions if p.get("ticker") != code]

    body = {
        "kind": "order",
        "owner_id": user_id,
        "order_id": order_id,
        "portfolio_id": portfolio_id,
        "ticker": code,
        "side": side_norm,
        "order_type": type_norm,
        "status": status,
        "quantity": float(quantity),
        "limit_price": float(limit_price or 0.0),
        "filled_price": fill_price if filled_qty else 0.0,
        "filled_quantity": filled_qty,
        "notional": notional if filled_qty else 0.0,
        "fees": float(fees or 0.0),
        "placed_at": now,
        "executed_at": now if filled_qty else None,
    }
    _save(client, index, order_id, body)

    if filled_qty:
        doc["tickers"] = positions
        doc["cash"] = round(cash, 6)
        doc["updated_at"] = now
        doc.pop("id", None)
        _save(client, index, portfolio_id, doc)

    body["id"] = order_id
    return _order_public(body)


def cancel_order(user_id: str, order_id: str) -> Dict[str, Any]:
    client = ensure_user_index(user_id)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    index = user_index(user_id)
    doc = _get(client, index, order_id)
    if not doc or doc.get("kind") != "order":
        return {"error": "Ordem não encontrada", "status": 404}
    if doc.get("status") != "pending":
        return {"error": "Só ordens pendentes podem ser canceladas", "status": 409}
    doc["status"] = "cancelled"
    doc["updated_at"] = _now()
    doc.pop("id", None)
    _save(client, index, order_id, doc)
    return _order_public({**doc, "id": order_id})


# ---------------------------------------------------------------------------
# Pesquisa de tickers (Yahoo Finance)
# ---------------------------------------------------------------------------
def search_tickers(query: str, limit: int = 12) -> Dict[str, Any]:
    """Pesquisa tickers por símbolo ou nome no Yahoo Finance."""
    term = str(query or "").strip()
    if not term:
        return {"items": []}
    try:
        from api.tools import _yahoo_search

        payload = _yahoo_search(term, news_count=0, quotes_count=max(1, min(int(limit), 10)))
    except Exception as exc:
        logger.warning("Pesquisa de tickers indisponível para %r: %s", term, exc)
        return {"items": [], "error": str(exc)}

    items = []
    for quote in payload.get("quotes") or []:
        symbol = quote.get("symbol")
        if not symbol:
            continue
        items.append(
            {
                "ticker": str(symbol).upper(),
                "name": quote.get("shortname") or quote.get("longname") or symbol,
                "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
                "type": quote.get("quoteType") or "",
                "sector": quote.get("sector") or "",
                "industry": quote.get("industry") or "",
            }
        )
    return {"items": items[: max(1, int(limit))]}
