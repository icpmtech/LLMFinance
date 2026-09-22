"""Rotas do módulo de publicações de atos societários (`/societario/*`).

Fonte: ``publicacoes.mj.pt`` (Instituto dos Registos e do Notariado / Ministério
da Justiça) — os atos de registo comercial das entidades portuguesas
(constituição, alterações, prestação de contas, nomeações, dissoluções, …).

A **pesquisa do portal exige reCAPTCHA v2** validado no servidor, pelo que a
recolha é *assistida*: uma pessoa resolve o captcha no browser e o coletor trata
da paginação, do detalhe e da indexação (esses passos não são protegidos).
Ver `collectors/publicacoes_mj.py` para o detalhe do fluxo.

Leitura (pública)
- `GET  /societario/meta`                — metadados (tipos, distritos, captcha, limites)
- `GET  /societario/status`              — volumetria do índice (entidades, anos, atos)
- `GET  /societario/search`              — pesquisar publicações indexadas
- `GET  /societario/targets`             — entidades com contratos no BASE (alvos da recolha)
- `GET  /societario/companies/{nif}`     — publicações de uma entidade

Escrita (sessão)
- `POST /societario/collect`             — recolha assistida (token de captcha ou página de resultados)
- `POST /societario/ingest`              — indexar publicações já recolhidas
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import societario_service
from api.auth_routes import CurrentSession, require_session
from collectors.publicacoes_mj import CaptchaRequiredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/societario", tags=["societario"])

Session = Annotated[CurrentSession, Depends(require_session)]


class SocietarioCollectRequest(BaseModel):
    """Pedido de recolha assistida.

    Indique ``recaptcha_token`` (acabado de resolver, válido ~2 minutos) ou
    ``result_html`` (o HTML da página de resultados já pesquisada no browser),
    acompanhado dos ``cookies`` da sessão do portal (ex.: ``ASP.NET_SessionId``).
    """

    nif: Optional[str] = Field(None, description="NIF/NIPC da entidade (critério preferencial)")
    entidade: Optional[str] = Field(None, description="Firma/denominação a pesquisar")
    tipo: str = Field("0", description="Tipo de publicação (0 = todos os actos)")
    distrito: Optional[str] = Field(None, description="Código do distrito/ilha (ex.: '13' = Porto)")
    concelho: Optional[str] = Field(None, description="Código do concelho (requer o distrito)")
    data_ini: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD)")
    data_fim: Optional[str] = Field(None, description="Data final (AAAA-MM-DD)")
    recaptcha_token: Optional[str] = Field(None, description="Token do reCAPTCHA resolvido por uma pessoa")
    result_html: Optional[str] = Field(None, description="HTML da página de resultados já pesquisada")
    cookies: Optional[Dict[str, str]] = Field(None, description="Cookies da sessão do portal")
    with_details: bool = Field(True, description="Abrir o detalhe de cada publicação (dados societários)")
    max_pages: int = Field(50, ge=1, le=500, description="Máximo de páginas da grelha a percorrer")
    ingest: bool = Field(True, description="Indexar o resultado em `finance_publicacoes_mj`")
    min_interval: float = Field(1.0, ge=0, le=10, description="Intervalo mínimo entre pedidos (segundos)")


class SocietarioIngestRequest(BaseModel):
    """Indexação de publicações já recolhidas."""

    items: List[Dict[str, Any]] = Field(default_factory=list, description="Publicações (formato `PublicacaoMJ.to_dict()`)")
    replace_for_nif: Optional[str] = Field(
        None, description="Se indicado, remove os registos desta entidade que não constem da lista"
    )


class SocietarioCollectEntitiesRequest(BaseModel):
    """Recolha automática de publicações para entidades indexadas (via 2captcha)."""

    nifs: Optional[List[str]] = Field(None, description="Lista explícita de NIFs/NIPC a pesquisar")
    limit: Optional[int] = Field(None, ge=1, le=200, description="Máximo de entidades a recolher do índice")
    min_contracts: int = Field(1, ge=1, description="Mínimo de contratos para uma entidade ser elegível")
    exclude_collected: bool = Field(True, description="Ignorar entidades que já têm publicações recolhidas")
    data_ini: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD); se omitida, pesquisa sem filtro temporal")
    data_fim: Optional[str] = Field(None, description="Data final (AAAA-MM-DD)")
    tipo: str = Field("0", description="Tipo de publicação (0 = todos os actos)")
    with_details: bool = Field(True, description="Abrir o detalhe de cada publicação")
    max_pages: int = Field(50, ge=1, le=500, description="Máximo de páginas da grelha por entidade")
    min_interval: float = Field(1.0, ge=0, le=10, description="Intervalo mínimo entre pedidos ao portal (segundos)")
    recaptcha_timeout: int = Field(180, ge=30, le=600, description="Timeout para resolução do reCAPTCHA (segundos)")
    ingest: bool = Field(True, description="Indexar o resultado em `finance_publicacoes_mj`")
    stop_on_captcha: bool = Field(False, description="Parar imediatamente se o captcha for rejeitado")


class SocietarioCollectResponse(BaseModel):
    criteria: Dict[str, Any] = Field(default_factory=dict)
    collected: int = 0
    pages: int = 0
    declared_total: int = 0
    with_details: bool = False
    items: List[Dict[str, Any]] = Field(default_factory=list)
    ingest: Optional[Dict[str, Any]] = None


@router.get("/meta")
def societario_meta() -> Dict[str, Any]:
    """Metadados do módulo: tipos de publicação, distritos, captcha e limites."""
    return societario_service.meta()


@router.get("/status")
def societario_status() -> Dict[str, Any]:
    """Volumetria do índice de publicações (entidades, intervalo de datas, atos)."""
    res = societario_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def societario_search(
    q: Optional[str] = Query(None, description="Texto livre (entidade, firma, acto, texto integral)"),
    nif: Optional[str] = Query(None),
    entidade: Optional[str] = Query(None),
    acto: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None),
    distrito: Optional[str] = Query(None),
    concelho: Optional[str] = Query(None),
    natureza_juridica: Optional[str] = Query(None),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_documento: Optional[bool] = Query(None),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Pesquisa publicações de atos societários indexadas."""
    res = societario_service.search(
        q=q,
        nif=nif,
        entidade=entidade,
        acto=acto,
        tipo=tipo,
        distrito=distrito,
        concelho=concelho,
        natureza_juridica=natureza_juridica,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/targets")
def societario_targets(
    limit: int = Query(50, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    min_contracts: int = Query(1, ge=1),
    exclude_collected: bool = Query(
        True, description="Excluir as entidades que já têm publicações recolhidas"
    ),
) -> Dict[str, Any]:
    """Entidades portuguesas com contratos no Portal BASE, ordenadas por volume.

    Serve para escolher os alvos da recolha assistida.
    """
    res = societario_service.targets(
        limit=limit, from_=from_, min_contracts=min_contracts, exclude_collected=exclude_collected
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/companies/{nif}")
def societario_company(
    nif: str,
    size: int = Query(100, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Publicações de atos societários de uma entidade."""
    res = societario_service.company_publicacoes(nif, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return {**res, "nif": nif}


@router.post("/collect", response_model=SocietarioCollectResponse)
def societario_collect(req: SocietarioCollectRequest, session: Session) -> SocietarioCollectResponse:
    """Recolha assistida das publicações de uma entidade.

    Requer uma pesquisa previamente autorizada pelo portal (``recaptcha_token`` ou
    ``result_html``); a paginação e o detalhe são recolhidos automaticamente.
    """
    try:
        res = societario_service.collect(
            nif=req.nif,
            entidade=req.entidade,
            tipo=req.tipo,
            distrito=req.distrito,
            concelho=req.concelho,
            data_ini=req.data_ini,
            data_fim=req.data_fim,
            recaptcha_token=req.recaptcha_token,
            result_html=req.result_html,
            cookies=req.cookies,
            with_details=req.with_details,
            max_pages=req.max_pages,
            min_interval=req.min_interval,
            ingest_result=req.ingest,
        )
    except CaptchaRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha na recolha de publicações do MJ")
        raise HTTPException(status_code=502, detail=f"Erro na recolha: {exc}") from exc
    return SocietarioCollectResponse(**{k: v for k, v in res.items() if k in SocietarioCollectResponse.model_fields})


@router.post("/ingest")
def societario_ingest(req: SocietarioIngestRequest, session: Session) -> Dict[str, Any]:
    """Indexa publicações de atos societários já recolhidas."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Nenhuma publicação recebida.")
    res = societario_service.ingest(req.items, replace_for_nif=req.replace_for_nif)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.post("/collect-entities")
def societario_collect_entities(req: SocietarioCollectEntitiesRequest, session: Session) -> Dict[str, Any]:
    """Recolha automática de publicações para entidades indexadas (2captcha).

    Itera pelas entidades do índice ``finance_entities``, pesquisa cada NIP no
    portal do MJ e indexa as publicações encontradas. Requer uma API key da
    2captcha (variável ``TWOCAPTCHA_API_KEY``).
    """
    try:
        return societario_service.collect_entities(
            nifs=req.nifs,
            limit=req.limit,
            min_contracts=req.min_contracts,
            exclude_collected=req.exclude_collected,
            data_ini=req.data_ini,
            data_fim=req.data_fim,
            tipo=req.tipo,
            with_details=req.with_details,
            max_pages=req.max_pages,
            min_interval=req.min_interval,
            recaptcha_timeout=req.recaptcha_timeout,
            ingest_result=req.ingest,
            stop_on_captcha=req.stop_on_captcha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha na recolha automática de publicações do MJ por entidades")
        raise HTTPException(status_code=502, detail=f"Erro na recolha automática: {exc}") from exc
