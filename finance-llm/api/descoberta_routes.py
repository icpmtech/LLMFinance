"""Rotas do painel de **Descoberta** de uma empresa (`/descoberta/*`).

Dá-se um NIF (ou um nome) e o painel devolve tudo o que a plataforma sabe
sobre essa empresa, o **grafo de informação** que a relaciona com a evidência e
a projeção dessa malha sobre a **ontologia** do IQ OS. A análise citada é
escrita pelo **Hermes** (`api.hermes_service`), com as skills da plataforma.

- `GET  /descoberta/meta`                    — fontes disponíveis, grupos e limites
- `GET  /descoberta/skills`                  — skills do Hermes e a sugerida para uma pergunta
- `GET  /descoberta/resolver`                — resolve um nome/NIF na empresa certa
- `GET  /descoberta/empresa/{nif}`           — recolha completa + grafo + ontologia + decisão
- `GET  /descoberta/empresa/{nif}/grafo`     — só o grafo de informação
- `GET  /descoberta/empresa/{nif}/ontologia` — só a projeção sobre a ontologia
- `GET  /descoberta/empresa/{nif}/decisao`   — evolução, concentração, preços, perfil e pontos de atenção
- `POST /descoberta/empresa/{nif}/analise`   — análise citada pelo Hermes
- `GET  /descoberta/conjunto`                — comparação de várias empresas (números, cruzamentos e rede)
- `POST /descoberta/conjunto`                — igual, com a lista de empresas no corpo

O trabalho pesado (recolha paralela por fonte, grafo, ontologia e decisão) está
em `api.descoberta_service`, `api.descoberta_decisao` e `api.descoberta_conjunto`;
aqui só se expõe o resultado.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from api import descoberta_conjunto as conjunto_service
from api import descoberta_service as service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/descoberta", tags=["descoberta"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

#: Limites de empresas por pedido no painel de conjunto (validados na rota).
MIN_EMPRESAS = conjunto_service.MIN_EMPRESAS
MAX_EMPRESAS = conjunto_service.MAX_EMPRESAS


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de leitura dos dados privados (CRM) quando há sessão."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _fontes_param(valor: Optional[str]) -> Optional[List[str]]:
    """Aceita a lista de fontes como texto separado por vírgulas."""
    if not valor:
        return None
    ids = [parte.strip() for parte in str(valor).replace(";", ",").split(",") if parte.strip()]
    if not ids:
        return None
    desconhecidas = [fonte_id for fonte_id in ids if fonte_id not in service.FONTE_BY_ID]
    if desconhecidas:
        raise HTTPException(status_code=422, detail=f"Fontes desconhecidas: {', '.join(desconhecidas)}.")
    return ids


def _pais(valor: Optional[str]) -> str:
    """Valida o país pedido.

    A plataforma só lê os portais de Portugal e de Espanha. Um código
    desconhecido devolveria zero contratos e um painel vazio, como se a empresa
    não tivesse contratação — é um pedido inválido e diz-se que é.
    """
    codigo = str(valor or service.PAIS_DEFAULT).strip().upper()
    if codigo not in service.PAISES_SUPORTADOS:
        raise HTTPException(
            status_code=422,
            detail=f"País não suportado: {codigo or '(vazio)'}. Use um de: {', '.join(service.PAISES_SUPORTADOS)}.",
        )
    return codigo


def _pedido_lista(valor: Any) -> Optional[List[str]]:
    """Aceita uma lista ou um texto com vírgulas/pontos e vírgulas."""
    if valor is None:
        return None
    if isinstance(valor, (list, tuple, set)):
        itens = [str(parte).strip() for parte in valor]
    else:
        itens = [parte.strip() for parte in str(valor).replace(";", ",").split(",")]
    limpos = [item for item in itens if item]
    return limpos or None


def _lista(valor: Optional[str]) -> Optional[List[str]]:
    """Igual a `_pedido_lista`, para os parâmetros de query."""
    return _pedido_lista(valor)


async def _conjunto(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valida o pedido de comparação e devolve o conjunto (ou 422 legível).

    Os limites são verificados aqui (e não só no esquema da rota) porque o
    corpo do `POST` é livre.
    """
    limite = payload.get("max_empresas")
    try:
        limite = int(limite) if limite not in (None, "") else 6
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="`max_empresas` tem de ser um número.") from exc
    if limite < MIN_EMPRESAS or limite > MAX_EMPRESAS:
        raise HTTPException(
            status_code=422,
            detail=f"`max_empresas` tem de estar entre {MIN_EMPRESAS} e {MAX_EMPRESAS}.",
        )
    try:
        return await run_in_threadpool(
            conjunto_service.conjunto,
            nifs=_pedido_lista(payload.get("nifs")),
            nomes=_pedido_lista(payload.get("nomes")),
            pais=_pais(payload.get("pais")),
            max_empresas=limite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/meta", summary="Fontes, grupos e limites do painel de descoberta")
def descoberta_meta() -> Dict[str, Any]:
    """Catálogo das fontes que a descoberta recolhe e as fontes de investigação do Hermes."""
    return service.meta()


@router.get("/skills", summary="Skills que o Hermes segue (e a que serviria uma pergunta)")
def descoberta_skills(
    q: Annotated[Optional[str], Query(max_length=200, description="Pergunta para pré-visualizar a skill")] = None,
) -> Dict[str, Any]:
    """Biblioteca partilhada por Hermes, Chat IA e RAG, mais a skill sugerida para `q`."""
    return service.skills(q)


@router.get("/resolver", summary="Resolve um nome ou NIF na empresa certa")
def descoberta_resolver(
    q: Annotated[str, Query(min_length=2, max_length=120, description="Nome da empresa ou NIF")],
    size: Annotated[int, Query(ge=1, le=20)] = 8,
) -> Dict[str, Any]:
    """Devolve a empresa principal e candidatos alternativos (para o utilizador escolher)."""
    return service.resolver(q, size=size)


@router.get("/empresa/{nif}", summary="Recolha completa de uma empresa")
async def descoberta_empresa(
    nif: str,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    nome: Annotated[Optional[str], Query(max_length=200, description="Nome, quando já é conhecido")] = None,
    fontes: Annotated[Optional[str], Query(description="Fontes a recolher (vírgulas); por omissão, todas")] = None,
    incluir_grafo: bool = True,
    incluir_ontologia: bool = True,
    incluir_decisao: bool = True,
) -> Dict[str, Any]:
    """Recolhe todas as fontes para o NIF e devolve a recolha com o grafo, a ontologia e a decisão."""
    recolha = await run_in_threadpool(
        service.recolher,
        nif,
        pais=_pais(pais),
        nome=nome,
        apenas=_fontes_param(fontes),
    )
    if recolha.get("error"):
        raise HTTPException(status_code=422, detail=recolha["error"])
    if incluir_grafo:
        recolha["grafo"] = service.grafo(recolha)
    if incluir_ontologia:
        recolha["ontologia"] = service.ontologia(recolha, recolha.get("grafo") or service.grafo(recolha))
    if incluir_decisao:
        recolha["decisao"] = service.decisao(recolha)
    return recolha


@router.get("/empresa/{nif}/decisao", summary="Painel de decisão da empresa")
async def descoberta_decisao(
    nif: str,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    nome: Annotated[Optional[str], Query(max_length=200)] = None,
) -> Dict[str, Any]:
    """Evolução, concentração de compradores, CPV, procedimento, escalões, preços, perfil e atenção.

    Tudo calculado a partir da recolha — nenhum número vem de um modelo de IA.
    """
    recolha = await run_in_threadpool(service.recolher, nif, pais=_pais(pais), nome=nome)
    if recolha.get("error"):
        raise HTTPException(status_code=422, detail=recolha["error"])
    return service.decisao(recolha)


@router.get("/empresa/{nif}/grafo", summary="Grafo de informação da empresa")
async def descoberta_grafo(
    nif: str,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    nome: Annotated[Optional[str], Query(max_length=200)] = None,
) -> Dict[str, Any]:
    """Malha empresa ↔ adjudicantes, CPV, pessoas, processos, marcas, firmas e imprensa."""
    recolha = await run_in_threadpool(service.recolher, nif, pais=_pais(pais), nome=nome)
    if recolha.get("error"):
        raise HTTPException(status_code=422, detail=recolha["error"])
    return {**service.grafo(recolha), "nif": nif, "nome": recolha.get("nome"), "fontes": recolha.get("fontes")}


@router.get("/empresa/{nif}/ontologia", summary="Projeção da empresa sobre a ontologia")
async def descoberta_ontologia(
    nif: str,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    nome: Annotated[Optional[str], Query(max_length=200)] = None,
) -> Dict[str, Any]:
    """Tipos de objeto instanciados, tipos de ligação materializados e cobertura."""
    recolha = await run_in_threadpool(service.recolher, nif, pais=_pais(pais), nome=nome)
    if recolha.get("error"):
        raise HTTPException(status_code=422, detail=recolha["error"])
    return service.ontologia(recolha, service.grafo(recolha))


@router.get("/conjunto", summary="Compara várias empresas (NIFs ou nomes)")
async def descoberta_conjunto_get(
    nifs: Annotated[Optional[str], Query(description="NIFs separados por vírgulas")] = None,
    nomes: Annotated[Optional[str], Query(description="Nomes separados por vírgulas")] = None,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    max_empresas: Annotated[int, Query(ge=MIN_EMPRESAS, le=MAX_EMPRESAS)] = 6,
) -> Dict[str, Any]:
    """Números alinhados, cruzamentos, rede do conjunto e pontos de atenção agregados.

    Cada empresa é recolhida e analisada com o mesmo motor do painel individual,
    pelo que os números coincidem com os do painel de cada uma.
    """
    return await _conjunto(
        {
            "nifs": _lista(nifs),
            "nomes": _lista(nomes),
            "pais": pais,
            "max_empresas": max_empresas,
        }
    )


@router.post("/conjunto", summary="Compara várias empresas (corpo JSON)")
async def descoberta_conjunto_post(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Igual a `GET /descoberta/conjunto`, com a lista no corpo.

    O corpo aceita `nifs` (lista ou texto com vírgulas), `nomes`, `pais` e
    `max_empresas`.
    """
    payload = payload or {}
    return await _conjunto(payload)


@router.post("/empresa/{nif}/analise", summary="Análise da empresa pelo Hermes")
async def descoberta_analise(
    nif: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Escreve a análise citada da empresa, com os factos calculados na plataforma.

    O corpo aceita `pergunta`, `profundidade` (`rapida` | `profunda`), `fontes`
    (fontes da Pesquisa 360), `backend`, `skill_id` (método a impor), `pais`,
    `nome` e `fontes_recolha` (fontes da descoberta a recolher). Sem pergunta, o
    Hermes recebe a pergunta padrão da descoberta, ancorada nos números da recolha.
    """
    payload = payload or {}
    recolha = await run_in_threadpool(
        service.recolher,
        nif,
        pais=_pais(payload.get("pais")),
        nome=payload.get("nome"),
        apenas=_fontes_param(payload.get("fontes_recolha")),
    )
    if recolha.get("error"):
        raise HTTPException(status_code=422, detail=recolha["error"])

    fontes_hermes = payload.get("sources") or payload.get("fontes")
    if isinstance(fontes_hermes, str):
        fontes_hermes = [parte.strip() for parte in fontes_hermes.split(",") if parte.strip()]
    try:
        return await service.analisar(
            recolha,
            pergunta=payload.get("pergunta"),
            profundidade=payload.get("profundidade"),
            fontes=fontes_hermes,
            backend=payload.get("backend"),
            skill_id=payload.get("skill_id"),
            session=session,
            scope=_scope(session),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
