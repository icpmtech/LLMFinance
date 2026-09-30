"""Rotas do módulo **Deteção de padrões** (`/padroes/*`).

Responde à pergunta «o que é atípico na contratação pública, em quem e com que
relações?» cruzando contratos (PT/ES), empresas, cargos, insolvências e notícias.

- `GET /padroes/meta`                      — padrões, algoritmos, fontes e parâmetros
- `GET /padroes/analysis`                  — análise completa (KPIs, CPV, anomalias, entidades, rede, modelo)
- `GET /padroes/anomalies`                 — só os contratos sinalizados (filtros por score/detetor)
- `GET /padroes/entities`                  — só as empresas/entidades com score
- `GET /padroes/relations`                 — grafo de relações, laços e concentração
- `GET /padroes/news`                      — menções em notícias das entidades sinalizadas
- `GET /padroes/entity/{nif}`              — dossiê de uma entidade (contratos, sinais, cargos, CIRE, notícias)
- `GET /padroes/empresas/sugestoes`        — nome/marca/NIF -> empresas com contratos
- `GET /padroes/empresas/analise`          — análise de uma empresa (portefólio, CPV, regras, relações)
- `POST /padroes/empresas/browser`         — ler páginas externas e indexá-las    (sessão)
- `POST /padroes/empresas/ia`              — ficha analítica por IA (com browser)  (sessão)
- `POST /padroes/empresas/guardar`         — guardar a análise no Elasticsearch   (sessão)
- `GET /padroes/empresas/guardadas`        — análises guardadas                    (sessão)
- `GET /padroes/empresas/relatorio`        — relatório PDF/Excel/CSV
- `POST /padroes/cache/clear`              — limpar a cache de análises            (sessão)

A leitura é pública (como nos restantes módulos); só a manutenção da cache exige
sessão. Um `refresh=true` na análise também exige sessão, porque reconstrói tudo.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import padroes_global as universo  # «global» é palavra reservada em Python
from api import padroes_regras as regras
from api import padroes_service as service
from api import padroes_empresa_ia as empresa_ia
from api import padroes_report as empresa_report
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/padroes", tags=["padroes"])

Session = Annotated[CurrentSession, Depends(require_session)]

PAIS_PATTERN = "^(PT|ES|pt|es)$"


def _analysis(
    pais: str,
    ano_from: Optional[int],
    ano_to: Optional[int],
    cpv: Optional[str],
    per_year: int,
    contamination: float,
    seed: int,
    refresh: bool,
) -> Dict[str, Any]:
    payload = service.analyze(
        pais=pais,
        ano_from=ano_from,
        ano_to=ano_to,
        cpv=cpv,
        per_year=per_year,
        contamination=contamination,
        seed=seed,
        use_cache=not refresh,
    )
    if payload.get("error") and payload.get("paises") is None and "país desconhecido" in str(payload.get("error")):
        raise HTTPException(status_code=400, detail=payload["error"])
    return payload


class RegraPayload(BaseModel):
    """Regra de deteção (condição ou conjunto de condições sobre um contrato)."""

    id: Optional[str] = Field(None, description="Identificador; em falta é criado um novo")
    label: str = Field("", description="Nome da regra")
    descricao: Optional[str] = Field(None, description="Porque é que este sinal importa")
    severidade: str = Field("aviso", description="info | aviso | alerta")
    modo: str = Field("todas", description="todas = E (todas as condições); alguma = OU")
    condicoes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Lista de {campo, operador, valor}; `valor` pode ser um número, texto ou {"campo": "x", "fator": 0.6}',
    )
    ativo: bool = True


class TemplatePayload(BaseModel):
    """Template de regras: um conjunto temático que se aplica de uma vez."""

    id: Optional[str] = None
    nome: str = Field(..., min_length=2, description="Nome do template")
    descricao: Optional[str] = None
    regras: Optional[List[str]] = Field(None, description="Ids das regras; em falta usa as ativas")


@router.get("/meta", summary="Catálogo de padrões, algoritmos e fontes")
def padroes_meta() -> Dict[str, Any]:
    """O que o motor sabe procurar, com que algoritmos e sobre que índices."""
    return service.meta()


@router.get("/analysis", summary="Análise completa de padrões")
def padroes_analysis(
    pais: str = Query("PT", pattern=PAIS_PATTERN, description="PT (Portal BASE) ou ES (PLACSP)"),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100, description="Ano mínimo (omissão: todos)"),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100, description="Ano máximo (omissão: atual)"),
    cpv: Optional[str] = Query(None, max_length=12, description="Prefixo de CPV (ex.: «45» obras)"),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000, description="Contratos lidos por ano"),
    contamination: float = Query(0.02, ge=0.005, le=0.2, description="Proporção esperada de anomalias"),
    seed: int = Query(42, ge=0, le=10_000, description="Semente (reprodutibilidade)"),
    refresh: bool = Query(False, description="Ignorar a cache e recalcular (exige sessão)"),
    session: Optional[CurrentSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """Corre (ou reutiliza da cache) a análise não supervisionada + supervisionada."""
    if refresh and session is None:
        raise HTTPException(status_code=401, detail="Recalcular a análise exige sessão.")
    return _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, refresh)


@router.get("/anomalies", summary="Contratos sinalizados")
def padroes_anomalies(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    contamination: float = Query(0.02, ge=0.005, le=0.2),
    seed: int = Query(42, ge=0, le=10_000),
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Score mínimo de consenso"),
    detector: Optional[str] = Query(None, description="isolation_forest | lof | kmeans | one_class_svm"),
    padrao: Optional[str] = Query(None, description="Filtrar por padrão (ex.: aditivo_valor)"),
    limit: int = Query(100, ge=1, le=400),
) -> Dict[str, Any]:
    """Contratos com score alto e pelo menos dois detetores de acordo."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, False)
    if payload.get("error"):
        return payload
    items: List[Dict[str, Any]] = payload.get("anomalias") or []
    if min_score > 0:
        items = [item for item in items if (item.get("score") or 0) >= min_score]
    if detector:
        items = [item for item in items if detector in (item.get("detetores") or [])]
    if padrao:
        items = [item for item in items if any(r.get("padrao") == padrao for r in item.get("razoes") or [])]
    return {
        "pais": payload.get("pais"),
        "total": len(items),
        "limiar_consenso": (payload.get("deteccao") or {}).get("limiar_consenso"),
        "algoritmos": (payload.get("deteccao") or {}).get("algoritmos"),
        "items": items[:limit],
        "overview": payload.get("overview"),
    }


@router.get("/entities", summary="Empresas/entidades com score")
def padroes_entities(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    contamination: float = Query(0.02, ge=0.005, le=0.2),
    seed: int = Query(42, ge=0, le=10_000),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    insolventes: bool = Query(False, description="Só entidades com processo no CIRE"),
    limit: int = Query(100, ge=1, le=300),
) -> Dict[str, Any]:
    """Ranking de adjudicatárias (LOF no espaço de features da entidade)."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, False)
    if payload.get("error"):
        return payload
    items: List[Dict[str, Any]] = payload.get("entidades") or []
    if min_score > 0:
        items = [item for item in items if (item.get("score") or 0) >= min_score]
    if insolventes:
        items = [item for item in items if item.get("insolvente")]
    return {
        "pais": payload.get("pais"),
        "total": len(items),
        "modelo": payload.get("modelo_entidades"),
        "items": items[:limit],
    }


@router.get("/relations", summary="Rede de relações e concentração")
def padroes_relations(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    seed: int = Query(42, ge=0, le=10_000),
) -> Dict[str, Any]:
    """Grafo adjudicante→adjudicatária, laços societários, concentração e CIRE."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, 0.02, seed, False)
    if payload.get("error"):
        return payload
    relations = payload.get("relacoes") or {}
    return {
        "pais": payload.get("pais"),
        "nodes": relations.get("nodes") or [],
        "edges": relations.get("edges") or [],
        "meta": relations.get("meta") or {},
        "lacos": relations.get("lacos") or [],
        "concentracao": relations.get("concentracao") or [],
        "insolventes": relations.get("insolventes") or [],
        "pessoas": relations.get("pessoas") or [],
    }


@router.get("/news", summary="Menções em notícias das entidades sinalizadas")
def padroes_news(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    seed: int = Query(42, ge=0, le=10_000),
    limit: int = Query(8, ge=1, le=20, description="Entidades a procurar"),
) -> Dict[str, Any]:
    """Procura menções (RSS, recolha e redes sociais) das empresas mais sinalizadas."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, 0.02, seed, False)
    if payload.get("error"):
        return payload
    entities = [entity for entity in (payload.get("entidades") or []) if entity.get("nome") or entity.get("nif")]
    targets: List[tuple] = []
    for entity in entities[:limit]:
        name = entity.get("nome") or ""
        if len(str(name)) >= 4:
            targets.append((f"{name} ({entity.get('nif')})", name))
    if not targets:
        return {"pais": payload.get("pais"), "items": [], "procuradas": []}
    items = service.news_mentions(targets)
    return {
        "pais": payload.get("pais"),
        "procuradas": [name for _, name in targets],
        "total": len(items),
        "items": items,
    }


@router.get("/entity/{nif}", summary="Dossiê de uma entidade")
def padroes_entity(
    nif: str,
    pais: str = Query("PT", pattern=PAIS_PATTERN),
) -> Dict[str, Any]:
    """Contratos, sinais, cargos sociais, processos CIRE e notícias de uma entidade."""
    dossier = service.entity_dossier(nif, pais=pais)
    if dossier.get("error") and "Elasticsearch" in str(dossier["error"]):
        raise HTTPException(status_code=503, detail=dossier["error"])
    return dossier


# ---------------------------------------------------------------------------
# Pesquisa e análise de uma empresa (adjudicatária)
# ---------------------------------------------------------------------------
@router.get("/empresas/sugestoes", summary="Sugestões de empresas a analisar")
def padroes_empresas_sugestoes(
    q: str = Query(..., min_length=2, max_length=120, description="Nome da empresa, marca ou NIF"),
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    limit: int = Query(8, ge=1, le=20),
) -> Dict[str, Any]:
    """Resolve o texto (nome ou NIF) em empresas com contratos.

    Devolve a empresa principal e candidatos alternativos: quem escreve «psg»
    tem de conseguir escolher entre várias sociedades com o mesmo prefixo.
    """
    resolvido = service.resolver_empresa(q, pais=pais)
    if resolvido.get("error") and "Elasticsearch" in str(resolvido["error"]):
        raise HTTPException(status_code=503, detail=resolvido["error"])
    if resolvido.get("error"):
        return {"pais": pais.upper(), "query": q, "items": [], "candidatos": [], "detail": resolvido["error"]}
    principal = {
        "nif": resolvido.get("nif"),
        "nome": resolvido.get("nome"),
        "alias": resolvido.get("alias") or [],
        "contratos": resolvido.get("contratos"),
        "valor": resolvido.get("valor"),
        "papeis": resolvido.get("papeis") or [],
        "concelho": resolvido.get("concelho"),
        "fonte": resolvido.get("fonte"),
        "principal": True,
    }
    itens = [principal] + [{**item, "principal": False} for item in resolvido.get("candidatos") or []]
    return {
        "pais": resolvido.get("pais") or pais.upper(),
        "query": q,
        "nif_detetado": bool(resolvido.get("nif_detetado")),
        "items": itens[:limit],
        "candidatos": resolvido.get("candidatos") or [],
    }


@router.get("/empresas/analise", summary="Análise de uma empresa e dos seus contratos")
def padroes_empresas_analise(
    nif: Optional[str] = Query(None, min_length=2, max_length=15, description="NIF da empresa (preferido)"),
    nome: Optional[str] = Query(None, min_length=2, max_length=120, description="Nome, se não houver NIF"),
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    max_contratos: int = Query(400, ge=10, le=1000, description="Contratos analisados (mais recentes primeiro)"),
    refresh: bool = Query(False, description="Ignorar a cache e recalcular (exige sessão)"),
    session: Optional[CurrentSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """Portefólio, CPV, regras cumpridas, pares e relações de uma empresa.

    A régua de cada CPV vem de uma amostra do próprio setor, pelo que «atípico»
    significa atípico entre pares — não apenas «valor alto».
    """
    if not nif and not nome:
        raise HTTPException(status_code=400, detail="Indique `nif` ou `nome`.")
    if refresh and session is None:
        raise HTTPException(status_code=401, detail="Recalcular a análise exige sessão.")
    payload = service.analise_empresa(
        nif=nif,
        nome=nome,
        pais=pais,
        ano_from=ano_from,
        ano_to=ano_to,
        max_contratos=max_contratos,
        use_cache=not refresh,
    )
    erro = str(payload.get("error") or "")
    if "Elasticsearch" in erro:
        raise HTTPException(status_code=503, detail=erro)
    if "país desconhecido" in erro:
        raise HTTPException(status_code=400, detail=erro)
    return payload


@router.post("/cache/clear", summary="Limpar a cache de análises")
def padroes_cache_clear(session: Session) -> Dict[str, Any]:
    """Liberta as análises em memória (o próximo pedido recalcula)."""
    removed = service.clear_cache()
    return {"removidas": removed, "por": session.user.email}


# ---------------------------------------------------------------------------
# Empresa: browser, IA, persistência e relatório
# ---------------------------------------------------------------------------
class EmpresaBrowserPayload(BaseModel):
    """Páginas externas a ler no browser do IQ OS."""

    urls: List[str] = Field(default_factory=list, description="Endereços http(s) a ler")
    limite: int = Field(6, ge=1, le=20, description="Máximo de páginas lidas")
    indexar: bool = Field(True, description="Guardar o texto lido em `finance_scraped`")


class EmpresaIaPayload(BaseModel):
    """Pedido de ficha analítica (IA), com análise e browser opcionais."""

    nif: Optional[str] = Field(None, description="NIF da empresa")
    nome: Optional[str] = Field(None, description="Nome, se não houver NIF")
    pais: str = Field("PT", description="PT (Portal BASE) ou ES (PLACSP)")
    ano_from: Optional[int] = Field(None, ge=1900, le=2100)
    ano_to: Optional[int] = Field(None, ge=1900, le=2100)
    max_contratos: int = Field(400, ge=10, le=1000)
    urls: List[str] = Field(default_factory=list, description="Páginas a ler antes de escrever a ficha")
    com_browser: bool = Field(False, description="Ler as `urls` e indexá-las antes da ficha")
    backend: Optional[str] = Field(None, description="Modelo a usar (ex.: openai:gpt-4o-mini)")
    guardar: bool = Field(False, description="Guardar a análise e a ficha no Elasticsearch")
    notas: Optional[str] = Field(None, max_length=8000, description="Notas do analista (vão para o registo)")


class EmpresaGuardarPayload(BaseModel):
    """Guardar uma análise no Elasticsearch (recalcula se não vier pronta)."""

    nif: Optional[str] = None
    nome: Optional[str] = None
    pais: str = "PT"
    ano_from: Optional[int] = Field(None, ge=1900, le=2100)
    ano_to: Optional[int] = Field(None, ge=1900, le=2100)
    max_contratos: int = Field(400, ge=10, le=1000)
    titulo: Optional[str] = Field(None, max_length=200)
    notas: Optional[str] = Field(None, max_length=8000)
    ficha_ia: Optional[str] = Field(None, description="Ficha já redigida, se existir")
    analise: Optional[Dict[str, Any]] = Field(None, description="Análise já obtida (evita recalcular)")
    browser: Optional[List[Dict[str, Any]]] = Field(None, description="Páginas lidas no browser")


class EmpresasPayload(BaseModel):
    """Comparação de várias empresas (por NIF, por nome, ou ambos)."""

    nifs: List[str] = Field(default_factory=list, description="NIF/NIPC das empresas")
    nomes: List[str] = Field(default_factory=list, description="Nomes (resolvidos pelo cadastro)")
    pais: str = Field("PT", description="PT (Portal BASE) ou ES (PLACSP)")
    ano_from: Optional[int] = Field(None, ge=1900, le=2100)
    ano_to: Optional[int] = Field(None, ge=1900, le=2100)
    max_contratos: int = Field(service.CONTRATOS_POR_EMPRESA, ge=20, le=400, description="Contratos por empresa")
    max_empresas: int = Field(6, ge=2, le=service.MAX_EMPRESAS_CONJUNTO, description="Máximo de empresas comparadas")
    formato: str = Field("json", description="json | pdf | xlsx | csv (o relatório é descarregado)")


def _download(filename: str, content: bytes, media_type: str) -> Response:
    """Devolve o relatório como transferência (nome do ficheiro em ASCII)."""
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/empresas/analise-multipla", summary="Comparar várias empresas (contratos, cruzamentos e rede)")
async def padroes_empresas_analise_multipla(payload: EmpresasPayload) -> Any:
    """Compara várias empresas: números alinhados, cruzamentos e rede do conjunto.

    Cada empresa corre a análise normal (com cache). A resposta devolve as linhas
    comparáveis, os cruzamentos (adjudicantes, pessoas e processos partilhados), a
    distribuição por CPV e o **grafo do conjunto** (empresas ligadas pelo
    comprador, pelo mercado, pelo gerente e pelo processo).

    Com `formato` diferente de `json`, devolve o relatório pronto a descarregar.
    """
    if not payload.nifs and not payload.nomes:
        raise HTTPException(status_code=400, detail="Indique `nifs` ou `nomes` (pelo menos duas empresas).")
    if len(payload.nifs) + len(payload.nomes) < 2:
        raise HTTPException(status_code=400, detail="Uma comparação precisa de pelo menos duas empresas.")

    conjunto = await run_in_threadpool(
        service.analise_empresas,
        nifs=payload.nifs,
        nomes=payload.nomes,
        pais=payload.pais,
        ano_from=payload.ano_from,
        ano_to=payload.ano_to,
        max_contratos=payload.max_contratos,
        max_empresas=payload.max_empresas,
    )
    erro = str(conjunto.get("error") or "")
    if erro:
        if "Elasticsearch" in erro:
            raise HTTPException(status_code=503, detail=erro)
        if "país desconhecido" in erro:
            raise HTTPException(status_code=400, detail=erro)
        raise HTTPException(status_code=404, detail=erro)

    formato = (payload.formato or "json").strip().lower()
    if formato == "json":
        return conjunto
    relatorio = empresa_report.empresas_report(conjunto, format=formato)
    if relatorio.get("error"):
        raise HTTPException(status_code=400, detail=str(relatorio["error"]))
    return _download(relatorio["filename"], relatorio["content"], relatorio["media_type"])


@router.post("/empresas/multipla/relatorio", summary="Relatório da comparação (PDF, Excel ou CSV)")
async def padroes_empresas_multipla_relatorio(
    payload: EmpresasPayload,
    formato: str = Query("pdf", pattern="^(pdf|xlsx|csv)$"),
) -> Response:
    """Emite o relatório de comparação (o mesmo conteúdo de `analise-multipla`)."""
    if not payload.nifs and not payload.nomes:
        raise HTTPException(status_code=400, detail="Indique `nifs` ou `nomes`.")
    conjunto = await run_in_threadpool(
        service.analise_empresas,
        nifs=payload.nifs,
        nomes=payload.nomes,
        pais=payload.pais,
        ano_from=payload.ano_from,
        ano_to=payload.ano_to,
        max_contratos=payload.max_contratos,
        max_empresas=payload.max_empresas,
    )
    if conjunto.get("error"):
        raise HTTPException(status_code=404, detail=str(conjunto["error"]))
    relatorio = empresa_report.empresas_report(conjunto, format=formato)
    if relatorio.get("error"):
        raise HTTPException(status_code=400, detail=str(relatorio["error"]))
    return _download(relatorio["filename"], relatorio["content"], relatorio["media_type"])


@router.post("/empresas/browser", summary="Ler páginas externas no browser do IQ OS")
def padroes_empresas_browser(payload: EmpresaBrowserPayload, session: Session) -> Dict[str, Any]:
    """Lê páginas públicas, extrai o texto útil e indexa-o em `finance_scraped`.

    O que aqui se lê passa a ser pesquisável no IQ OS como qualquer outra
    recolha; reler a mesma página **substitui** o documento (a identidade é o
    URL), pelo que a recolha não acumula duplicados.
    """
    resultado = empresa_ia.browser_ler(payload.urls, limite=payload.limite, indexar=payload.indexar)
    if payload.urls and not resultado.get("paginas"):
        raise HTTPException(status_code=400, detail="Nenhuma página foi lida.")
    return {"por": session.user.email, **resultado}


@router.post("/empresas/ia", summary="Ficha analítica da empresa (IA + browser)")
async def padroes_empresas_ia(payload: EmpresaIaPayload, session: Session) -> Dict[str, Any]:
    """Escreve a ficha de risco da empresa com o modelo configurado.

    Junta três camadas: a **análise** do motor de padrões (contratos, CPV,
    regras, relações), o **cadastro** das entidades contratantes e — quando
    pedido — o **texto** de páginas lidas no browser. Sem modelo disponível
    devolve a ficha factual (mesmos números, sem redação por IA).
    """
    if not payload.nif and not payload.nome:
        raise HTTPException(status_code=400, detail="Indique `nif` ou `nome`.")

    analise = await run_in_threadpool(
        service.analise_empresa,
        nif=payload.nif,
        nome=payload.nome,
        pais=payload.pais,
        ano_from=payload.ano_from,
        ano_to=payload.ano_to,
        max_contratos=payload.max_contratos,
    )
    erro = str(analise.get("error") or "")
    if erro:
        if "Elasticsearch" in erro:
            raise HTTPException(status_code=503, detail=erro)
        raise HTTPException(status_code=404, detail=erro)

    browser: Dict[str, Any] = {}
    if payload.com_browser and payload.urls:
        browser = await run_in_threadpool(empresa_ia.browser_ler, payload.urls, limite=empresa_ia.MAX_PAGINAS, indexar=True)

    nifs = [str(item.get("nif")) for item in (analise.get("adjudicantes") or []) if item.get("nif")]
    entidades = await run_in_threadpool(empresa_ia.dados_entidades, nifs)
    ia = await empresa_ia.ficha_ia(
        analise,
        paginas=browser.get("paginas") or [],
        entidades=entidades,
        session=session,
        backend=payload.backend,
    )

    guardado = None
    if payload.guardar:
        guardado = await run_in_threadpool(
            _guardar_analise,
            {
                "nif": analise.get("nif"),
                "nome": analise.get("nome"),
                "pais": analise.get("pais"),
                "analise": analise,
                "notas": payload.notas,
                "ficha_ia": ia.get("text"),
                "ia": {
                    "provider": (ia.get("backend") or {}).get("provider"),
                    "model": (ia.get("backend") or {}).get("model"),
                    "text": ia.get("text"),
                },
                "browser": ia.get("paginas") or [],
                "fontes": [pagina.get("url") for pagina in ia.get("paginas") or []],
            },
            session,
        )

    return {
        "nif": analise.get("nif"),
        "nome": analise.get("nome"),
        "pais": analise.get("pais"),
        "ia": ia,
        "browser": {
            "lidas": browser.get("lidas", 0),
            "indexadas": browser.get("indexadas", 0),
            "indice": browser.get("indice"),
            "paginas": [
                {"url": pagina.get("url"), "titulo": pagina.get("titulo"), "chars": pagina.get("chars"), "ok": pagina.get("ok"), "erro": pagina.get("erro")}
                for pagina in browser.get("paginas") or []
            ],
        },
        "entidades": entidades,
        "guardado": guardado,
        "pedido": payload.model_dump(exclude={"urls"}),
    }


def _guardar_analise(payload: Dict[str, Any], session: CurrentSession) -> Dict[str, Any]:
    """Guarda a análise (com autor e notas) e devolve o resultado do índice."""
    from api.elasticsearch_client import save_analise_empresa  # noqa: PLC0415

    return save_analise_empresa(
        {
            **payload,
            "autor": getattr(session.user, "name", None) or session.user.email,
            "autor_email": session.user.email,
        }
    )


@router.post("/empresas/guardar", summary="Guardar a análise de uma empresa no Elasticsearch")
async def padroes_empresas_guardar(payload: EmpresaGuardarPayload, session: Session) -> Dict[str, Any]:
    """Guarda (ou substitui) a análise de uma empresa.

    O id do documento é `pais:nif`, pelo que voltar a guardar a mesma empresa
    atualiza a fotografia anterior em vez de criar duplicados.
    """
    analise = payload.analise
    if not analise:
        if not payload.nif and not payload.nome:
            raise HTTPException(status_code=400, detail="Indique `nif`/`nome` ou envie a `analise`.")
        analise = await run_in_threadpool(
            service.analise_empresa,
            nif=payload.nif,
            nome=payload.nome,
            pais=payload.pais,
            ano_from=payload.ano_from,
            ano_to=payload.ano_to,
            max_contratos=payload.max_contratos,
        )
        if analise.get("error"):
            raise HTTPException(status_code=404, detail=str(analise["error"]))

    resultado = await run_in_threadpool(
        _guardar_analise,
        {
            "nif": analise.get("nif"),
            "nome": analise.get("nome"),
            "pais": analise.get("pais") or payload.pais,
            "titulo": payload.titulo,
            "notas": payload.notas,
            "analise": analise,
            "ficha_ia": payload.ficha_ia,
            "browser": payload.browser or [],
        },
        session,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/empresas/guardadas", summary="Análises de empresas guardadas")
def padroes_empresas_guardadas(
    nif: Optional[str] = Query(None, description="Filtrar por NIF"),
    nome: Optional[str] = Query(None, description="Filtrar por nome"),
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN),
    limit: int = Query(50, ge=1, le=200),
    session: Session = None,
) -> Dict[str, Any]:
    """Lista as análises guardadas (mais recentes primeiro), sem a fotografia completa."""
    from api.elasticsearch_client import list_analises_empresa  # noqa: PLC0415

    resultado = list_analises_empresa(nif=nif, nome=nome, pais=pais, limit=limit)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/empresas/guardada/{doc_id}", summary="Análise guardada (completa)")
def padroes_empresas_guardada(doc_id: str, session: Session = None) -> Dict[str, Any]:
    """Devolve a análise guardada, com a fotografia completa e a ficha de IA."""
    from api.elasticsearch_client import get_analise_empresa  # noqa: PLC0415

    resultado = get_analise_empresa(doc_id)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=f"Análise não encontrada: {doc_id}")
    return resultado


@router.delete("/empresas/guardada/{doc_id}", summary="Apagar uma análise guardada")
def padroes_empresas_guardada_apagar(doc_id: str, session: Session) -> Dict[str, Any]:
    """Apaga a análise guardada (`pais:nif`)."""
    from api.elasticsearch_client import delete_analise_empresa  # noqa: PLC0415

    resultado = delete_analise_empresa(doc_id)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=str(resultado["error"]))
    return {**resultado, "por": session.user.email}


@router.get("/empresas/relatorio", summary="Relatório da empresa (PDF, Excel ou CSV)")
async def padroes_empresas_relatorio(
    formato: str = Query("pdf", pattern="^(pdf|xlsx|csv)$", description="pdf, xlsx ou csv"),
    nif: Optional[str] = Query(None, max_length=15),
    nome: Optional[str] = Query(None, max_length=120),
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    max_contratos: int = Query(400, ge=10, le=1000),
    doc_id: Optional[str] = Query(None, description="Usar uma análise já guardada (`pais:nif`)"),
    ficha_ia: bool = Query(False, description="Incluir a ficha redigida por IA (mais lento)"),
    backend: Optional[str] = Query(None, description="Modelo para a ficha de IA"),
    session: Optional[CurrentSession] = Depends(optional_session),
) -> Response:
    """Emite o relatório da empresa com a marca do IQ OS.

    Sem `doc_id` a análise é feita agora (usa a cache quando existe); com
    `doc_id` usa-se a fotografia guardada no Elasticsearch, garantindo que o
    relatório de hoje diz o mesmo que a análise de ontem.
    """
    ficha = None
    guardada: Dict[str, Any] = {}
    if doc_id:
        if session is None:
            raise HTTPException(status_code=401, detail="Ler uma análise guardada exige sessão.")
        from api.elasticsearch_client import get_analise_empresa  # noqa: PLC0415

        guardada = await run_in_threadpool(get_analise_empresa, doc_id)
        if guardada.get("error"):
            raise HTTPException(status_code=404, detail=f"Análise não encontrada: {doc_id}")
        analise = guardada.get("analise") or {}
        ficha = guardada.get("ficha_ia") or None
    else:
        if not nif and not nome:
            raise HTTPException(status_code=400, detail="Indique `nif` ou `nome` (ou `doc_id`).")
        analise = await run_in_threadpool(
            service.analise_empresa,
            nif=nif,
            nome=nome,
            pais=pais,
            ano_from=ano_from,
            ano_to=ano_to,
            max_contratos=max_contratos,
        )
    erro = str(analise.get("error") or "")
    if erro:
        status = 503 if "Elasticsearch" in erro else 404
        raise HTTPException(status_code=status, detail=erro)

    nifs = [str(item.get("nif")) for item in (analise.get("adjudicantes") or []) if item.get("nif")]
    entidades = await run_in_threadpool(empresa_ia.dados_entidades, nifs)

    if ficha_ia and not ficha:
        resultado_ia = await empresa_ia.ficha_ia(analise, entidades=entidades, session=session, backend=backend)
        ficha = resultado_ia.get("text")

    relatorio = empresa_report.empresa_report(
        analise,
        format=formato,
        ficha_ia=ficha,
        paginas=guardada.get("browser") or None,
        notas=[guardada.get("notas")] if guardada.get("notas") else None,
        entidades=entidades,
    )
    if relatorio.get("error"):
        raise HTTPException(status_code=400, detail=str(relatorio["error"]))
    return _download(relatorio["filename"], relatorio["content"], relatorio["media_type"])


# ---------------------------------------------------------------------------
# Regras e templates
# ---------------------------------------------------------------------------
@router.get("/regras", summary="Regras de deteção e templates")
def padroes_regras_listar() -> Dict[str, Any]:
    """Regras guardadas (editáveis), templates, campos e operadores disponíveis."""
    return regras.listar()


@router.get("/regras/campos", summary="Campos e operadores que uma regra pode usar")
def padroes_regras_campos() -> Dict[str, Any]:
    """Catálogo de campos, operadores, severidades e padrões não avaliáveis."""
    return regras.catalogo()


@router.post("/regras", status_code=201, summary="Criar ou atualizar uma regra")
def padroes_regras_guardar(payload: RegraPayload, session: Session) -> Dict[str, Any]:
    """Cria uma regra nova (sem `id`) ou atualiza a existente."""
    try:
        regra = regras.guardar(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service.clear_cache()
    return regra


@router.patch("/regras/{regra_id}/ativo", summary="Ligar/desligar uma regra")
def padroes_regras_alternar(
    regra_id: str,
    ativo: Optional[bool] = Query(None, description="Em falta inverte o estado atual"),
    session: Session = None,  # noqa: ARG001 - exige sessão
) -> Dict[str, Any]:
    """Liga ou desliga uma regra sem apagar a definição."""
    try:
        regra = regras.alternar(regra_id, ativo)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"regra não encontrada: {regra_id}") from exc
    service.clear_cache()
    return regra


@router.post("/regras/{regra_id}/duplicar", status_code=201, summary="Duplicar uma regra")
def padroes_regras_duplicar(regra_id: str, session: Session) -> Dict[str, Any]:
    """Cria uma cópia editável de uma regra (útil para afinar predefinições)."""
    try:
        return regras.duplicar(regra_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"regra não encontrada: {regra_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/regras/{regra_id}", summary="Apagar uma regra")
def padroes_regras_apagar(regra_id: str, session: Session) -> Dict[str, Any]:
    """Remove uma regra do registo."""
    if not regras.apagar(regra_id):
        raise HTTPException(status_code=404, detail=f"regra não encontrada: {regra_id}")
    service.clear_cache()
    return {"apagada": regra_id}


@router.post("/regras/repor", summary="Repor as regras predefinidas")
def padroes_regras_repor(
    manter_personalizadas: bool = Query(False, description="Manter as regras criadas pelo utilizador"),
    session: Session = None,  # noqa: ARG001 - exige sessão
) -> Dict[str, Any]:
    """Repõe o conjunto de fábrica (e os templates predefinidos)."""
    resultado = regras.repor_default(manter_personalizadas=manter_personalizadas)
    service.clear_cache()
    return resultado


@router.get("/regras/templates", summary="Listar templates de regras")
def padroes_regras_templates() -> Dict[str, Any]:
    """Templates disponíveis (predefinidos e criados pelo utilizador)."""
    estado = regras.listar()
    return {"templates": estado["templates"], "total_regras": len(estado["regras"])}


@router.post("/regras/templates", status_code=201, summary="Guardar um template de regras")
def padroes_regras_template_guardar(payload: TemplatePayload, session: Session) -> Dict[str, Any]:
    """Guarda o conjunto de regras indicado (ou o que está ativo) como template."""
    try:
        template = regras.guardar_template(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return template


@router.post("/regras/templates/{template_id}/aplicar", summary="Aplicar um template")
def padroes_regras_template_aplicar(template_id: str, session: Session) -> Dict[str, Any]:
    """Ativa as regras do template e desliga as restantes."""
    try:
        resultado = regras.aplicar_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"template não encontrado: {template_id}") from exc
    service.clear_cache()
    return resultado


@router.delete("/regras/templates/{template_id}", summary="Apagar um template")
def padroes_regras_template_apagar(template_id: str, session: Session) -> Dict[str, Any]:
    """Remove um template (as regras ficam como estão)."""
    if not regras.apagar_template(template_id):
        raise HTTPException(status_code=404, detail=f"template não encontrado: {template_id}")
    return {"apagado": template_id}


@router.get("/regras/hits", summary="Contratos que cumprem as regras ativas")
def padroes_regras_hits(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    severidade: Optional[str] = Query(None, description="info | aviso | alerta"),
    regra: Optional[str] = Query(None, description="Filtrar por id de regra"),
    limit: int = Query(100, ge=1, le=300),
) -> Dict[str, Any]:
    """Contratos sinalizados **pelas regras** (independentemente dos modelos)."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, 0.02, 42, False)
    if payload.get("error"):
        return payload
    items: List[Dict[str, Any]] = payload.get("regras_hits") or []
    if severidade:
        items = [item for item in items if item.get("severidade") == severidade]
    if regra:
        items = [item for item in items if regra in (item.get("regras") or [])]
    return {
        "pais": payload.get("pais"),
        "total": len(items),
        "regras": (payload.get("regras") or {}).get("ativas") or [],
        "items": items[:limit],
        "overview": payload.get("overview"),
    }


# ---------------------------------------------------------------------------
# Dashboard global (o universo inteiro, por ano, com pesquisa e filtros)
# ---------------------------------------------------------------------------
class GlobalSincronizarPayload(BaseModel):
    """Sincronização do universo: que país e que anos agregar."""

    pais: str = Field("PT", description="PT (Portal BASE) ou ES (PLACSP)")
    anos: Optional[List[int]] = Field(
        None,
        description="Anos a agregar; em falta usa os últimos 12 com contratos",
    )


def _global_pais(pais: str) -> str:
    chave = str(pais or "").upper()
    if chave not in service.COUNTRIES:
        raise HTTPException(status_code=400, detail=f"país desconhecido: {pais} (use PT ou ES)")
    return chave


@router.get("/global/meta", summary="Estado do universo: índice, anos materializados e sincronização")
def padroes_global_meta(pais: str = Query("PT", pattern=PAIS_PATTERN)) -> Dict[str, Any]:
    """O que está materializado do universo e como está o processo de sincronização."""
    return universo.meta(_global_pais(pais))


@router.get("/global/estado", summary="Estado do processo de sincronização do universo")
def padroes_global_estado() -> Dict[str, Any]:
    """Progresso/resultado da sincronização em segundo plano (para a página acompanhar)."""
    return universo.estado()


@router.post("/global/sincronizar", summary="Agregar o universo por ano (processo em segundo plano)")
def padroes_global_sincronizar(payload: GlobalSincronizarPayload, session: Session) -> Dict[str, Any]:
    """Arranca a agregação do índice inteiro, ano a ano, e materializa o resultado.

    É um **processo**: corre em segundo plano (uma sincronização de cada vez) e o
    progresso acompanha-se em `/padroes/global/estado`. Para correr tudo de forma
    síncrona (manutenção e testes) usa-se `/padroes/global/sincronizar/agora`.
    """
    iniciado = universo.iniciar_sincronizacao(payload.pais, anos=payload.anos)
    if iniciado.get("aviso"):
        raise HTTPException(status_code=409, detail=iniciado["aviso"])
    return iniciado


@router.post("/global/sincronizar/agora", summary="Agregar o universo e esperar pelo fim (síncrono)")
async def padroes_global_sincronizar_agora(payload: GlobalSincronizarPayload, session: Session) -> Dict[str, Any]:
    """Corre a sincronização do universo de forma síncrona e devolve o resumo."""
    resultado = await run_in_threadpool(universo.sincronizar, payload.pais, anos=payload.anos)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=resultado["error"])
    return resultado


@router.get("/global", summary="Dashboard global do universo (por ano, mês e topos)")
def padroes_global_dashboard(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    granularidade: str = Query("mes", description="dia | semana | mes | ano"),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
) -> Dict[str, Any]:
    """Métricas do **universo inteiro** (sem amostra): contratos, valor, mediana,
    ajuste direto, aditivos, contratos sem concorrentes, série temporal e topos."""
    return universo.dashboard(
        _global_pais(pais),
        granularidade=granularidade,
        ano_from=ano_from,
        ano_to=ano_to,
    )


@router.get("/global/pesquisa", summary="Pesquisa tipo Google no universo, com filtros e facetas")
def padroes_global_pesquisa(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    q: Optional[str] = Query(None, max_length=300, description="Texto livre (objeto, descrição, partes)"),
    data_from: Optional[str] = Query(None, max_length=10, description="AAAA-MM-DD"),
    data_to: Optional[str] = Query(None, max_length=10, description="AAAA-MM-DD"),
    campo_data: str = Query("publicacao", description="publicacao | decisao | assinatura"),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    empresa: Optional[str] = Query(None, max_length=160, description="Adjudicatária (NIF ou nome)"),
    adjudicante: Optional[str] = Query(None, max_length=160, description="Comprador (NIF ou nome)"),
    cpv: Optional[str] = Query(None, max_length=12, description="Código CPV (prefixo)"),
    procedimento: Optional[str] = Query(None, max_length=80, description="Tipo de procedimento"),
    valor_min: Optional[float] = Query(None, ge=0),
    valor_max: Optional[float] = Query(None, ge=0),
    concorrentes_min: Optional[int] = Query(None, ge=0, le=100),
    concorrentes_max: Optional[int] = Query(None, ge=0, le=100),
    so_aditivo: bool = Query(False, description="Só contratos com aditivo (efetivo > 1,15 × contratado)"),
    so_ajuste_direto: bool = Query(False, description="Só ajuste direto"),
    granularidade: str = Query("mes", description="dia | semana | mes | ano"),
    facets: bool = Query(True, description="Série e topos (agregados caros); as páginas seguintes podem dispensá-los"),
    size: int = Query(25, ge=1, le=100),
    from_: int = Query(0, ge=0, le=10000, alias="from"),
) -> Dict[str, Any]:
    """O «Google» do universo: texto livre + filtros de período, empresa,
    concorrentes, CPV e valor. As facetas e os KPIs são calculados por agregação
    sobre os **2,2 M** contratos portugueses (ou 4 M espanhóis), não sobre amostra."""
    return universo.pesquisa(
        _global_pais(pais),
        q=q,
        data_from=data_from,
        data_to=data_to,
        campo_data=campo_data,
        ano_from=ano_from,
        ano_to=ano_to,
        empresa=empresa,
        adjudicante=adjudicante,
        cpv=cpv,
        procedimento=procedimento,
        valor_min=valor_min,
        valor_max=valor_max,
        concorrentes_min=concorrentes_min,
        concorrentes_max=concorrentes_max,
        so_aditivo=so_aditivo,
        so_ajuste_direto=so_ajuste_direto,
        granularidade=granularidade,
        facets=facets,
        size=size,
        from_=from_,
    )
