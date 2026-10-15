"""Rotas da vista de mercado (`/market/*`).

- `GET /market/by-country` — os tickers conhecidos, agrupados por país, com a
  cotação do dia, agregados por país e a origem do país de cada linha.
- `GET /market/logo/{ticker}` — a marca da empresa (extraída do site oficial).
- `GET /market/meta` — fonte, ressalva de preço, dimensão do universo e limites.

O endereço `/market` (sem barra) é a página da aplicação e não uma rota da API:
fica para o *catch-all* do `api.main`, que devolve a SPA (ver
`api/spa_routes.py`, segmento `market`). É o mesmo desenho de `/mercado`.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

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


@router.get(
    "/logo/{ticker}",
    summary="Logótipo da empresa de um ticker (imagem)",
    response_class=FileResponse,
    responses={404: {"description": "Sem logótipo para este ticker."}},
)
async def market_logo(ticker: str, forcar: bool = Query(False, description="Voltar a procurar a marca no site, ignorando a última tentativa.")) -> Response:
    """Marca da empresa, extraída do **site oficial** e guardada no servidor.

    A imagem vem da mesma cache dos logótipos das empresas
    (`data/empresas/logos/`), alimentada pela extracção do site que o Yahoo
    Finance dá para o ticker — não se pede a marca a nenhum serviço de terceiros.

    Sem logótipo guardado e sem site conhecido responde 404: é o sinal que o
    frontend usa para mostrar as iniciais em vez de uma imagem partida. Um site
    que não renda marca não volta a ser visitado antes de `retry_days`.

    A rota é `async` de propósito: uma tabela cheia abre dezenas de pedidos de
    imagem ao mesmo tempo, e a espera pelo lugar é feita no event loop em vez de
    ocupar uma thread do servidor por pedido.
    """
    encontrado = await market_view.logo_async(ticker, forcar=bool(forcar))
    if not encontrado:
        raise HTTPException(status_code=404, detail="Sem logótipo para este ticker.")
    caminho, tipo = encontrado
    return FileResponse(
        caminho,
        media_type=tipo,
        headers={
            "Cache-Control": "public, max-age=604800",
            "Content-Disposition": f'inline; filename="{caminho.name}"',
        },
    )
