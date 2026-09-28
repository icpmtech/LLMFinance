"""Rotas do módulo **Empresas & Risco** (`/risco/*`).

Responde a «que empresas adjudicatárias merecem ser olhadas primeiro, e porquê?»
com um nível de risco de 0 a 100 (ML + regras), os contratos que o sustentam,
comparação de várias empresas e grafos analíticos 360.

- `GET  /risco/meta`                        — cartão do modelo, features, fontes e dependências
- `GET  /risco/pesquisa`                    — pesquisa tipo motor de busca, com risco por empresa
- `GET  /risco/sugestoes`                   — sugestões (nome/NIF) para a caixa de pesquisa
- `GET  /risco/empresa/{pais}/{nif}`        — risco + análise da empresa (triagem ou dossiê)
- `GET  /risco/empresa/{pais}/{nif}/grafo`  — grafo analítico 360 (compradores, pessoas, CIRE)
- `POST /risco/empresa/ia`                  — parecer de risco por IA                  (sessão)
- `POST /risco/comparar`                    — risco de várias empresas + cruzamentos + rede
- `POST /risco/cache/clear`                 — limpar a cache de risco                  (sessão)

A leitura é pública (como nos restantes módulos); só o parecer por IA e a
manutenção da cache exigem sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import padroes_service as padroes
from api import risco_ia as ia
from api import risco_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risco", tags=["risco"])

Session = Annotated[CurrentSession, Depends(require_session)]

PAIS_PATTERN = "^(PT|ES|pt|es)$"
NIVEL_PATTERN = "^(baixo|moderado|elevado|muito_elevado|critico)$"
ORDENAR_PATTERN = "^(relevancia|risco|valor|contratos)$"

LIMITE_ANOS = 1990


class EmpresaIaPayload(BaseModel):
    """Pedido do parecer de risco escrito por IA."""

    nif: Optional[str] = Field(None, description="NIF da empresa (alternativa a `nome`)")
    nome: Optional[str] = Field(None, description="Nome da empresa (resolvido para NIF)")
    pais: str = Field("PT", description="PT (Portal BASE) ou ES (PLACSP)")
    ano_from: Optional[int] = Field(None, ge=LIMITE_ANOS, le=2100)
    ano_to: Optional[int] = Field(None, ge=LIMITE_ANOS, le=2100)
    detalhado: bool = Field(True, description="Usar o dossiê completo (réguas de CPV + anomalia ML)")
    backend: Optional[str] = Field(None, description="Fornecedor de IA a usar; em falta escolhe o configurado")


class CompararPayload(BaseModel):
    """Pedido de comparação de várias empresas (NIF ou nome)."""

    nifs: List[str] = Field(default_factory=list, description="NIFs das empresas")
    nomes: List[str] = Field(default_factory=list, description="Nomes das empresas (resolvidos para NIF)")
    pais: str = Field("PT", description="PT (Portal BASE) ou ES (PLACSP)")
    ano_from: Optional[int] = Field(None, ge=LIMITE_ANOS, le=2100)
    ano_to: Optional[int] = Field(None, ge=LIMITE_ANOS, le=2100)
    detalhado: bool = Field(True, description="Risco pelo dossiê completo (mais lento, mais preciso)")


def _validar_pais(pais: Optional[str]) -> None:
    if pais and service.pais_codigo(pais) not in padroes.COUNTRIES:
        raise HTTPException(
            status_code=400, detail=f"país desconhecido: {pais} (use {' ou '.join(padroes.COUNTRIES)})"
        )


def _ou_erro(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o erro do motor em resposta HTTP (503 se for o Elasticsearch)."""
    erro = str(payload.get("error") or "")
    if not erro:
        return payload
    if "Elasticsearch" in erro:
        raise HTTPException(status_code=503, detail=erro)
    if "desconhecido" in erro:
        raise HTTPException(status_code=400, detail=erro)
    raise HTTPException(status_code=404, detail=erro)


@router.get("/meta", summary="Cartão do modelo de risco, features e fontes")
def risco_meta() -> Dict[str, Any]:
    """Explica o número: componentes, pesos, limiares, faixas e avisos."""
    return {**service.meta(), "ia": ia.disponivel()}


@router.get("/pesquisa", summary="Pesquisa de empresas com nível de risco")
async def risco_pesquisa(
    q: str = Query(..., min_length=2, description="Nome, marca ou NIF da empresa"),
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN, description="Filtrar por país"),
    nivel: Optional[str] = Query(None, pattern=NIVEL_PATTERN, description="Filtrar por nível de risco"),
    ordenar: str = Query("relevancia", pattern=ORDENAR_PATTERN, description="relevancia | risco | valor | contratos"),
    size: int = Query(10, ge=1, le=30, description="Empresas pontuadas por pedido"),
    from_: int = Query(0, ge=0, le=500, alias="from"),
    detalhado: bool = Query(False, description="Risco pelo dossiê completo (mais lento)"),
) -> Dict[str, Any]:
    """Pesquisa no cadastro e devolve as empresas com risco, prontas a ordenar.

    Por omissão a lista vem por **relevância** (nome mais próximo do pedido);
    `ordenar=risco` passa a ordená-la pelo nível de risco. A pontuação corre em
    paralelo e fica em cache: a primeira consulta a uma empresa custa mais, as
    seguintes são imediatas.
    """
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.pesquisa,
            q,
            pais=pais,
            nivel=nivel,
            ordenar=ordenar,
            size=size,
            from_=from_,
            detalhado=detalhado,
        )
    )


@router.get("/sugestoes", summary="Sugestões de empresas para a caixa de pesquisa")
def risco_sugestoes(
    q: str = Query(..., min_length=2, description="Nome ou NIF (mínimo 2 caracteres)"),
    size: int = Query(8, ge=1, le=20),
) -> Dict[str, Any]:
    """Sugestões do cadastro (nome, NIF, tipo e nº de contratos)."""
    return service.sugestoes(q, size=size)


@router.get("/empresa/{pais}/{nif}", summary="Risco e análise de uma empresa")
async def risco_empresa(
    pais: str,
    nif: str,
    detalhado: bool = Query(False, description="Dossiê completo (réguas de CPV + anomalia ML)"),
    ano_from: Optional[int] = Query(None, ge=LIMITE_ANOS, le=2100),
    ano_to: Optional[int] = Query(None, ge=LIMITE_ANOS, le=2100),
    max_contratos: int = Query(200, ge=20, le=2000, description="Contratos lidos para as features"),
) -> Dict[str, Any]:
    """Nível de risco da empresa, componentes, features e (no dossiê) a análise completa."""
    _validar_pais(pais)
    payload = await run_in_threadpool(
        service.risco_empresa,
        nif=nif,
        pais=service.pais_codigo(pais),
        ano_from=ano_from,
        ano_to=ano_to,
        detalhado=detalhado,
        max_contratos=max_contratos,
    )
    return _ou_erro(payload)


@router.get("/empresa/{pais}/{nif}/grafo", summary="Grafo analítico 360 da empresa")
async def risco_grafo(
    pais: str,
    nif: str,
) -> Dict[str, Any]:
    """Rede 360: contratos por comprador, órgãos sociais, processos do CIRE e co-intervenientes."""
    _validar_pais(pais)
    payload = await run_in_threadpool(service.grafo360, nif=nif, pais=service.pais_codigo(pais))
    return _ou_erro(payload)


@router.post("/empresa/ia", summary="Parecer de risco por IA (com recuo factual)")
async def risco_empresa_ia(payload: EmpresaIaPayload, session: Session) -> Dict[str, Any]:
    """Escreve o parecer de risco da empresa com o modelo configurado.

    O número vem do motor (não é alterado pela IA); o texto explica o que o puxa
    para cima, o que o contém, o que verificar a seguir e as limitações. Sem
    modelo disponível devolve o parecer factual com os mesmos números.
    """
    _validar_pais(payload.pais)
    if not payload.nif and not payload.nome:
        raise HTTPException(status_code=400, detail="Indique `nif` ou `nome`.")

    risco = await run_in_threadpool(
        service.risco_empresa,
        nif=payload.nif,
        nome=payload.nome,
        pais=service.pais_codigo(payload.pais),
        ano_from=payload.ano_from,
        ano_to=payload.ano_to,
        detalhado=payload.detalhado,
        max_contratos=400 if payload.detalhado else 200,
    )
    risco = _ou_erro(risco)
    analise = risco.get("analise") if isinstance(risco.get("analise"), dict) else None
    # A linha do dossiê não traz contratos (pesam muito): a IA recebe os números
    # agregados e os sinais, que é o que consegue citar sem inventar.
    texto = await ia.parecer(
        risco.get("risco") or {},
        analise=analise,
        session=session,
        backend=payload.backend,
    )
    return {
        "nif": risco.get("nif"),
        "nome": risco.get("nome"),
        "pais": risco.get("pais"),
        "risco": risco.get("risco"),
        "ia": texto,
        "por": session.user.email,
    }


@router.post("/comparar", summary="Comparar o risco de várias empresas")
async def risco_comparar(payload: CompararPayload) -> Dict[str, Any]:
    """Risco lado a lado (com ranking, cruzamentos e rede) de até 12 empresas."""
    _validar_pais(payload.pais)
    if not payload.nifs and not payload.nomes:
        raise HTTPException(status_code=400, detail="Indique pelo menos uma empresa (NIF ou nome).")
    return _ou_erro(
        await run_in_threadpool(
            service.comparar,
            nifs=payload.nifs,
            nomes=payload.nomes,
            pais=service.pais_codigo(payload.pais),
            ano_from=payload.ano_from,
            ano_to=payload.ano_to,
            detalhado=payload.detalhado,
        )
    )


@router.post("/cache/clear", summary="Limpar a cache de risco")
def risco_cache_clear(session: Session) -> Dict[str, Any]:
    """Apaga os riscos em cache (útil depois de afinar limiares ou regras)."""
    total = service.clear_cache()
    padroes.clear_cache()
    return {"removidas": total, "por": session.user.email}
