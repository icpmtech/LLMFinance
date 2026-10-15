"""Rotas da vista de mercado (`/market/*`).

- `GET /market/by-country` — os tickers conhecidos, agrupados por país, com a
  cotação do dia, agregados por país e a origem do país de cada linha.
- `GET /market/meta` — fonte, ressalva de preço, dimensão do universo e limites.

O endereço `/market` (sem barra) é a página da aplicação e não uma rota da API:
fica para o *catch-all* do `api.main`, que devolve a SPA (ver
`api/spa_routes.py`, segmento `market`). É o mesmo desenho de `/mercado`.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api import market_view
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/market", tags=["mercado"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _num(value: Any, fallback: int, *, minimo: int, maximo: int) -> int:
    try:
        numero = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimo, min(maximo, numero))


@router.get("/by-country", summary="Tickers da plataforma agrupados por país")
def market_by_country(
    tickers: Optional[str] = Query(None, description="Tickers separados por vírgula; sem valor, usa o universo da plataforma."),
    limit: int = Query(market_view.DEFAULT_TICKERS, ge=1, le=market_view.MAX_TICKERS, description="Quantos tickers ler (o universo tem ~90)."),
    workers: int = Query(market_view.DEFAULT_WORKERS, ge=1, le=12, description="Leituras ao Yahoo em paralelo."),
    refresh: bool = Query(False, description="Ignorar a cópia em memória e voltar a ler."),
) -> Dict[str, Any]:
    """Cotações do dia por país.

    O país vem do Yahoo Finance (o mesmo campo que a ficha do ticker mostra), com
    o sufixo do mercado como alternativa e `desconhecido` como último recurso —
    cada linha diz de onde veio. Uma cotação que falhe fica com `error` e não com
    um valor suposto.
    """
    codes = [part.strip() for part in (tickers or "").replace(";", ",").split(",") if part.strip()]
    return market_view.by_country(
        tickers=codes or None,
        limit=_num(limit, market_view.DEFAULT_TICKERS, minimo=1, maximo=market_view.MAX_TICKERS),
        workers=_num(workers, market_view.DEFAULT_WORKERS, minimo=1, maximo=12),
        refresh=bool(refresh),
    )


@router.get("/meta", summary="Fonte, ressalva e limites da vista de mercado")
def market_meta() -> Dict[str, Any]:
    """O que a página precisa de saber sobre a fonte, sem ir buscá-la."""
    return market_view.meta()
