"""Backend FastAPI para a Chat UI do FinanceLLM."""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Body, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response

from api.models import (
    ActionsResponse,
    AddTickerRequest,
    AddTickerResponse,
    CalendarResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ContractAnalyticsRequest,
    ContractAnalyticsResponse,
    ContractAnalyzeRequest,
    ContractAutocompleteResponse,
    ContractChatRequest,
    ContractGraphBuildResponse,
    ContractGraphResponse,
    ContractChatResponse,
    ContractIngestRequest,
    ContractIngestResponse,
    ContractItem,
    ImportDataType,
    ImportFileType,
    ImportIngestRequest,
    ImportIngestResponse,
    ImportOptions,
    ImportPreviewResponse,
    ImportPreviewRow,
    ContractSearchRequest,
    ContractSearchResponse,
    ContractRegionalResponse,
    ContractRelationsResponse,
    ContractStatusResponse,
    ContractYearsResponse,
    GraphDimensionOption,
    GraphDimensionsResponse,
    FavoriteItem,
    FavoriteListResponse,
    FavoriteMutationResponse,
    WorkspaceFolderRequest,
    WorkspaceHistoryRequest,
    WorkspaceResponse,
    CompanyAnalyticsResponse,
    CompanyContractsResponse,
    CompanyDetail,
    CompanyEnrichmentResponse,
    CompanyFirmasResponse,
    CompanySearchRequest,
    CompanySearchResponse,
    CompanyTrademarksResponse,
    ElasticAnalyzeNewsResponse,
    ElasticAutocompleteResponse,
    ElasticDeleteResponse,
    ElasticIngestNewsResponse,
    ElasticIngestPricesResponse,
    ElasticIngestRequest,
    ElasticNewsGraphResponse,
    ElasticSearchGlobalResponse,
    ElasticSearchNewsResponse,
    ElasticSearchPricesResponse,
    ElasticSearchResult,
    ElasticStatus,
    ElasticSuggestion,
    ElasticTickerListResponse,
    EntityCountryStat,
    EntityDetailResponse,
    EntityIngestRequest,
    EntityIngestResponse,
    EntityItem,
    EntitySearchRequest,
    EntitySearchResponse,
    EntityStatsResponse,
    FinancialsResponse,
    FirmaIngestRequest,
    FirmaIngestResponse,
    FirmaItem,
    FirmaSearchRequest,
    FirmaSearchResponse,
    ForecastPoint,
    ForecastRequest,
    ForecastResponse,
    ForecastSeries,
    ForecastSignal,
    HistoryPoint,
    HoldersResponse,
    NewsItem,
    NewsResponse,
    OptionsResponse,
    RecommendationsResponse,
    SecFiling,
    SecFilingsResponse,
    SentimentBlendedResponse,
    SustainabilityResponse,
    TechnicalExplanation,
    TechnicalPoint,
    TechnicalResponse,
    TickerHistoryResponse,
    TickerInfoResponse,
    TickerSearchResponse,
    TrademarkIngestRequest,
    TrademarkIngestResponse,
    TrademarkItem,
    TrademarkSearchRequest,
    TrademarkSearchResponse,
    YahooSearchResult,
)
from api.agent import run_chat, stream_chat
from api.elasticsearch_ingest import (
    get_elastic_status,
    ingest_ticker_all,
    ingest_ticker_news,
    ingest_ticker_prices,
    search_ticker_news,
    search_ticker_prices,
)
from api.elasticsearch_client import (
    GRAPH_DIMENSIONS,
    autocomplete_suggestions,
    build_contract_graph,
    bulk_index_contracts_from_jsonl,
    clear_favorites,
    contracts_autocomplete,
    contracts_status,
    delete_favorite,
    delete_folder,
    export_contracts_to_excel,
    export_contracts_to_pdf,
    get_contract_analytics,
    get_contract_by_id,
    get_contract_network,
    get_contract_regional_analytics,
    get_contract_relationships,
    get_company_by_nif,
    get_company_contracts,
    get_company_firmas,
    get_company_trademarks,
    get_entity_by_nif,
    get_entity_stats,
    get_es_client,
    get_workspace,
    index_company_firmas,
    index_company_trademarks,
    list_contract_years,
    list_entity_countries,
    list_favorites,
    save_favorite,
    save_folder,
    save_history,
    search_all_tickers,
    search_companies,
    get_company_analytics,
    search_contracts,
    search_entities,
    search_firmas,
    search_trademarks,
    CONTRACTS_INDEX,
    ENTITIES_INDEX,
    FIRMAS_INDEX,
    TRADEMARKS_INDEX,
)
from api.rag_service import get_contracts_chat_answer
from api.contract_agent import analyze_contract
from api.import_service import ingest_rows, parse_file
from api.tools import (
    _normalize_ticker,
    add_ticker,
    get_actions,
    get_calendar,
    get_financials,
    get_holders,
    get_news,
    get_options,
    get_recommendations,
    get_sec_filings_yahoo,
    get_stock_history,
    get_stock_info,
    get_sustainability,
    get_technical_indicators,
    explain_technical_indicators,
    yahoo_search,
)
from forecasting.arima_model import run_full_pipeline

from sentiment.feature_engineering import generate_sentiment_blended_forecast


from api.rag_routes import router as rag_router
from api.auth_routes import router as auth_router


ROOT = Path(__file__).resolve().parents[1]
FORECAST_DIR = ROOT / "data" / "forecasting"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pré-carrega o modelo de tradução em background para evitar bloquear o primeiro pedido.
    import threading
    def _preload_translation():
        try:
            from api.news_nlp import _TranslationModel
            _TranslationModel.translate("warmup")
        except Exception:
            pass
    threading.Thread(target=_preload_translation, daemon=True).start()
    yield


app = FastAPI(
    title="FinanceLLM API",
    version="0.4.0",
    description="API de chat, previsão de séries temporais e RAG FinanceLLM (GPT-2, Mistral e BloombergGPT-style).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(rag_router)
app.include_router(auth_router)


# Servir a React SPA da chat-ui (build estático)
from fastapi.staticfiles import StaticFiles

UI_BUILD_DIR = ROOT / "chat-ui" / "dist"
if UI_BUILD_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=UI_BUILD_DIR / "assets"), name="assets")


# --- Diretório de empresas (entidades) derivado de contratos ---

@app.post("/companies/search", response_model=CompanySearchResponse)
def companies_search(req: CompanySearchRequest):
    """Pesquisa empresas/entidades presentes nos contratos indexados."""
    res = search_companies(
        q=req.q,
        role=req.role,
        region=req.region,
        min_contracts=req.min_contracts,
        min_value=req.min_value,
        max_value=req.max_value,
        year=req.year,
        size=req.size,
        from_=req.from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return CompanySearchResponse(
        query=res.get("query"),
        total=res.get("total", 0),
        items=res.get("items", []),
        from_=req.from_,
        size=req.size,
        unique_adjudicantes=res.get("unique_adjudicantes", 0),
        unique_adjudicatarios=res.get("unique_adjudicatarios", 0),
    )


# Catch-all da SPA para sub-rotas de /companies devem ser registradas ANTES
# do endpoint dinâmico GET /companies/{nif}, senão o path "search" é
# interpretado como NIF.
@app.get("/companies")
@app.get("/companies/search")
@app.get("/companies/dashboard")
def serve_companies_spa_page():
    return FileResponse(str(UI_BUILD_DIR / "index.html"))


def _accepts_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


@app.get("/companies/{nif}", response_model=CompanyDetail)
def companies_detail(request: Request, nif: str, year: Optional[int] = Query(None)):
    """Detalhes de uma entidade (por NIF), incluindo resumo de papéis e contratos recentes."""
    if UI_BUILD_DIR.is_dir() and _accepts_html(request):
        return FileResponse(str(UI_BUILD_DIR / "index.html"))
    company = get_company_by_nif(nif)
    if company.get("error"):
        raise HTTPException(status_code=502, detail=company.get("error"))

    recent = get_company_contracts(nif=nif, role="all", size=10, from_=0)
    company["recent_contracts"] = recent.get("items", [])

    contracts_list = recent.get("items", [])
    seen_adjudicantes = set()
    seen_adjudicatarios = set()
    top_adjudicantes = []
    top_adjudicatarios = []
    for c in contracts_list:
        for a in c.get("adjudicantes", {}).get("parsed", []):
            key = a.get("nif") or a.get("nome", "").lower().strip()
            if key and key not in seen_adjudicantes:
                seen_adjudicantes.add(key)
                top_adjudicantes.append({"nif": a.get("nif"), "nome": a.get("nome", ""), "tipo": "adjudicante"})
        for a in c.get("adjudicatarios", {}).get("parsed", []):
            key = a.get("nif") or a.get("nome", "").lower().strip()
            if key and key not in seen_adjudicatarios:
                seen_adjudicatarios.add(key)
                top_adjudicatarios.append({"nif": a.get("nif"), "nome": a.get("nome", ""), "tipo": "adjudicatario"})
    company["top_adjudicantes"] = top_adjudicantes[:10]
    company["top_adjudicatarios"] = top_adjudicatarios[:10]

    # Enriquecimento: marcas do INPI e firmas do RNPC já indexadas na ficha da empresa.
    company_name = company.get("name")
    try:
        trademarks = get_company_trademarks(company_nif=nif, company_name=company_name, size=50)
        company["trademarks"] = trademarks.get("items", [])
        company["trademarks_total"] = trademarks.get("total", 0)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Falha ao ler marcas de {nif}: {exc}")

    try:
        firmas = get_company_firmas(company_nif=nif, company_name=company_name, size=50)
        company["firmas"] = firmas.get("items", [])
        company["firmas_total"] = firmas.get("total", 0)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Falha ao ler firmas de {nif}: {exc}")

    return CompanyDetail(**company)


@app.get("/companies/{nif}/contracts", response_model=CompanyContractsResponse)
def companies_contracts(
    nif: str,
    role: Optional[str] = Query("all"),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Contratos de uma entidade específica."""
    res = get_company_contracts(nif=nif, role=role, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return CompanyContractsResponse(
        nif=res.get("nif"),
        name=res.get("name"),
        role=res.get("role"),
        total=res.get("total", 0),
        items=[ContractItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.get("/companies/{nif}/analytics", response_model=CompanyAnalyticsResponse)
def companies_analytics(
    nif: str,
    role: Optional[str] = Query("all"),
    year: Optional[int] = Query(None),
):
    """Dashboard de analytics para uma empresa/entidade."""
    res = get_company_analytics(nif=nif, role=role, year=year)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return CompanyAnalyticsResponse(**res)


# --- Marcas (INPI) e firmas (RNPC/PNS) por empresa ---

@app.get("/companies/{nif}/trademarks", response_model=CompanyTrademarksResponse)
def companies_trademarks(
    nif: str,
    q: Optional[str] = Query(None, description="Filtrar pelo nome da marca"),
    size: int = Query(100, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Marcas do INPI já indexadas na ficha da empresa."""
    res = get_company_trademarks(company_nif=nif, q=q, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return CompanyTrademarksResponse(
        nif=nif,
        name=res.get("company_name"),
        total=res.get("total", 0),
        items=[TrademarkItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.get("/companies/{nif}/firmas", response_model=CompanyFirmasResponse)
def companies_firmas(
    nif: str,
    q: Optional[str] = Query(None, description="Filtrar pelo nome da firma"),
    size: int = Query(100, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Firmas/nomes comerciais do RNPC já indexados na ficha da empresa."""
    res = get_company_firmas(company_nif=nif, q=q, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return CompanyFirmasResponse(
        nif=nif,
        name=res.get("company_name"),
        total=res.get("total", 0),
        items=[FirmaItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.post("/companies/{nif}/enrich", response_model=CompanyEnrichmentResponse)
def companies_enrich(
    nif: str,
    include_trademarks: bool = Query(True, description="Obter marcas do INPI"),
    include_firmas: bool = Query(True, description="Obter firmas do RNPC (PNS)"),
    max_trademarks: int = Query(50, ge=1, le=200),
    max_firmas: int = Query(20, ge=1, le=20),
    trademark_detail_limit: int = Query(10, ge=0, le=100, description="Nº de marcas com detalhe completo"),
):
    """Obtém dados do INPI (marcas) e/ou RNPC (firmas) e guarda-os na ficha da empresa no Elasticsearch.

    Os nomes das empresas do portal base incluem sufixos societários e pontuação que
    fazem falhar a pesquisa por semelhança dos serviços públicos; por isso são testadas
    variantes do nome até haver resultados.
    """
    company = get_company_by_nif(nif)
    name = company.get("name") if not company.get("error") else None
    if not name:
        entity = get_entity_by_nif(nif)
        name = entity.get("name") if not entity.get("error") else None
    if not name:
        raise HTTPException(status_code=404, detail=f"Empresa {nif} não encontrada")

    response = CompanyEnrichmentResponse(nif=nif, name=name)

    if include_trademarks:
        from collectors.inpi_marcas import search_trademarks_with_fallback
        from collectors.name_utils import rank_items_by_similarity

        try:
            data = search_trademarks_with_fallback(
                name,
                nif=nif,
                include_detail=True,
                max_results=max_trademarks,
                detail_limit=trademark_detail_limit,
            )
            docs = data.get("trademarks", [])
            # Ordena pela semelhança do titular com o nome da empresa e descarta
            # marcas de titulares claramente diferentes (acontece quando a pesquisa
            # teve de recorrer a um termo genérico).
            docs = rank_items_by_similarity(
                docs, name, key="holder_name", similarity_field="holder_similarity"
            )
            result = index_company_trademarks(nif, name, docs)
            matched = data.get("matched_term")
            response.trademarks = TrademarkIngestResponse(
                nif=nif,
                name=name,
                fetched=len(docs),
                indexed_count=result.get("indexed_count", 0),
                errors=result.get("errors", 0),
                message=(
                    f"{len(docs)} marcas obtidas do INPI (termo: {matched})."
                    if matched
                    else f"Sem marcas no INPI para «{name}» (testados {len(data.get('tried', []))} termos)."
                ),
                error=result.get("error"),
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(f"Enriquecimento INPI falhou para {name}: {exc}")
            response.trademarks = TrademarkIngestResponse(nif=nif, name=name, error=str(exc))

    if include_firmas:
        from collectors.pns_firmas import fetch_firmas_for_company
        from collectors.name_utils import rank_items_by_similarity

        try:
            data = fetch_firmas_for_company(name, include_detail=True, max_results=max_firmas)
            docs = data.get("firmas", [])
            docs = rank_items_by_similarity(docs, name, key="nome")
            result = index_company_firmas(nif, name, docs)
            matched = data.get("matched_term")
            response.firmas = FirmaIngestResponse(
                nif=nif,
                name=name,
                fetched=len(docs),
                indexed_count=result.get("indexed_count", 0),
                errors=result.get("errors", 0),
                message=(
                    f"{len(docs)} firmas obtidas do RNPC (termo: {matched})."
                    if matched
                    else f"Sem firmas no RNPC para «{name}» (testados {len(data.get('tried', []))} termos)."
                ),
                error=result.get("error"),
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(f"Enriquecimento RNPC falhou para {name}: {exc}")
            response.firmas = FirmaIngestResponse(nif=nif, name=name, error=str(exc))

    return response


@app.post("/trademarks/ingest", response_model=TrademarkIngestResponse)
def trademarks_ingest(req: TrademarkIngestRequest):
    """Obtém marcas do INPI por nome/titular e indexa-as para a empresa indicada."""
    from collectors.inpi_marcas import InpiMarcasClient, search_trademarks_by_entity

    try:
        client = InpiMarcasClient()
        trademarks = search_trademarks_by_entity(
            client,
            nome=req.name,
            nif=req.nif or "",
            intervencao="TIT",
            include_detail=req.include_detail,
            max_results=req.max_results,
        )
        docs = [tm.to_dict() for tm in trademarks]
        result = index_company_trademarks(req.nif, req.name, docs)
        return TrademarkIngestResponse(
            nif=req.nif,
            name=req.name,
            fetched=len(docs),
            indexed_count=result.get("indexed_count", 0),
            errors=result.get("errors", 0),
            message=result.get("error") or f"{len(docs)} marcas obtidas do INPI.",
            error=result.get("error"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro na ingestão de marcas: {exc}")


@app.get("/trademarks/search", response_model=TrademarkSearchResponse)
def trademarks_search(
    q: Optional[str] = Query(None),
    holder_name: Optional[str] = Query(None),
    nice_class: Optional[str] = Query(None),
    mark_type: Optional[str] = Query(None),
    current_phase: Optional[str] = Query(None),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Pesquisa marcas indexadas no Elasticsearch."""
    res = search_trademarks(
        q=q,
        holder_name=holder_name,
        nice_class=nice_class,
        mark_type=mark_type,
        current_phase=current_phase,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return TrademarkSearchResponse(
        query=q,
        total=res.get("total", 0),
        items=[TrademarkItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.post("/trademarks/search", response_model=TrademarkSearchResponse)
def trademarks_search_post(req: TrademarkSearchRequest):
    """Pesquisa marcas indexadas no Elasticsearch (variante POST)."""
    res = search_trademarks(
        q=req.q,
        holder_name=req.holder_name,
        nice_class=req.nice_class,
        mark_type=req.mark_type,
        current_phase=req.current_phase,
        size=req.size,
        from_=req.from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return TrademarkSearchResponse(
        query=req.q,
        total=res.get("total", 0),
        items=[TrademarkItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", req.size),
    )


@app.post("/firmas/ingest", response_model=FirmaIngestResponse)
def firmas_ingest(req: FirmaIngestRequest):
    """Obtém firmas/nomes comerciais do RNPC (Pesquisa de Nomes Existentes) e indexa-as."""
    from collectors.pns_firmas import fetch_firmas_for_company

    try:
        data = fetch_firmas_for_company(
            req.name,
            cae=req.cae,
            concelho=req.concelho,
            include_detail=req.include_detail,
            max_results=req.max_results,
        )
        docs = data.get("firmas", [])
        result = index_company_firmas(req.nif, req.name, docs)
        return FirmaIngestResponse(
            nif=req.nif,
            name=req.name,
            fetched=len(docs),
            indexed_count=result.get("indexed_count", 0),
            errors=result.get("errors", 0),
            message=result.get("error") or f"{len(docs)} firmas obtidas do RNPC.",
            error=result.get("error"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro na ingestão de firmas: {exc}")


@app.get("/firmas/search", response_model=FirmaSearchResponse)
def firmas_search(
    q: Optional[str] = Query(None),
    concelho: Optional[str] = Query(None),
    cae: Optional[str] = Query(None),
    situacao: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Pesquisa firmas/nomes comerciais indexados no Elasticsearch."""
    res = search_firmas(
        q=q, concelho=concelho, cae=cae, situacao=situacao, min_score=min_score, size=size, from_=from_
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return FirmaSearchResponse(
        query=q,
        total=res.get("total", 0),
        items=[FirmaItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.post("/firmas/search", response_model=FirmaSearchResponse)
def firmas_search_post(req: FirmaSearchRequest):
    """Pesquisa firmas/nomes comerciais indexados no Elasticsearch (variante POST)."""
    res = search_firmas(
        q=req.q,
        concelho=req.concelho,
        cae=req.cae,
        situacao=req.situacao,
        min_score=req.min_score,
        size=req.size,
        from_=req.from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return FirmaSearchResponse(
        query=req.q,
        total=res.get("total", 0),
        items=[FirmaItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", req.size),
    )


@app.get("/enrichment/indices")
def enrichment_indices():
    """Estado dos índices de enriquecimento (marcas INPI e firmas RNPC)."""
    client = get_es_client()
    if not client:
        raise HTTPException(status_code=502, detail="Elasticsearch indisponível")
    out = {"elasticsearch": True, "indices": {}}
    for index in (TRADEMARKS_INDEX, FIRMAS_INDEX, ENTITIES_INDEX):
        try:
            if client.indices.exists(index=index):
                count = client.count(index=index).get("count", 0)
                out["indices"][index] = {"exists": True, "count": count}
            else:
                out["indices"][index] = {"exists": False, "count": 0}
        except Exception as exc:
            out["indices"][index] = {"exists": False, "error": str(exc)}
    return out


# --- Cadastro de entidades do portal base (pesquisa de empresas) ---

@app.post("/entities/ingest", response_model=EntityIngestResponse)
def entities_ingest(req: EntityIngestRequest = Body(default=EntityIngestRequest())):
    """Importa o `entidades.json` do portal base para o Elasticsearch.

    A leitura é feita em streaming, pelo que o ficheiro (~74 MB, ~214 mil entidades)
    não é carregado integralmente em memória.
    """
    from api.entities_service import ENTITIES_JSON, iter_normalized_entities
    from api.elasticsearch_client import index_entities

    path = Path(req.path) if req.path else ENTITIES_JSON
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Ficheiro de entidades não encontrado: {path}")

    result = index_entities(
        iter_normalized_entities(path),
        chunk_size=req.chunk_size,
        max_records=req.max_records,
        refresh=req.refresh,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return EntityIngestResponse(
        indexed_count=result.get("indexed_count", 0),
        total=result.get("total", 0),
        errors=result.get("errors", 0),
        message=result.get("message"),
    )


@app.get("/entities/search", response_model=EntitySearchResponse)
def entities_search_get(
    q: Optional[str] = Query(None, description="Nome da empresa ou NIF"),
    country: Optional[str] = Query(None, description="País (ex.: Portugal)"),
    only_with_nif: Optional[bool] = Query(None, description="Apenas entidades com NIF válido"),
    min_contracts: Optional[int] = Query(None, ge=0),
    max_contracts: Optional[int] = Query(None, ge=0),
    min_value: Optional[float] = Query(None, ge=0),
    max_value: Optional[float] = Query(None, ge=0),
    role: Optional[str] = Query("all", pattern="^(all|adjudicante|adjudicatario)$"),
    sort_by: Optional[str] = Query(
        "total_value",
        pattern="^(name|contracts_count|total_value|as_adjudicante_value|as_adjudicante_count|as_adjudicatario_count)$",
    ),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Pesquisa de empresas no cadastro de entidades importado."""
    res = search_entities(
        q=q,
        country=country,
        only_with_nif=only_with_nif,
        min_contracts=min_contracts,
        max_contracts=max_contracts,
        min_value=min_value,
        max_value=max_value,
        role=role,
        sort_by=sort_by,
        sort_order=sort_order,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return EntitySearchResponse(
        query=q,
        total=res.get("total", 0),
        items=[EntityItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", size),
    )


@app.post("/entities/search", response_model=EntitySearchResponse)
def entities_search_post(req: EntitySearchRequest):
    """Pesquisa de empresas no cadastro de entidades (variante POST)."""
    res = search_entities(
        q=req.q,
        country=req.country,
        only_with_nif=req.only_with_nif,
        min_contracts=req.min_contracts,
        max_contracts=req.max_contracts,
        min_value=req.min_value,
        max_value=req.max_value,
        role=req.role,
        sort_by=req.sort_by,
        sort_order=req.sort_order,
        size=req.size,
        from_=req.from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return EntitySearchResponse(
        query=req.q,
        total=res.get("total", 0),
        items=[EntityItem(**item) for item in res.get("items", [])],
        from_=res.get("from", 0),
        size=res.get("size", req.size),
    )


@app.get("/entities/stats", response_model=EntityStatsResponse)
def entities_stats():
    """Estatísticas do cadastro de entidades (totais, países, com/sem NIF)."""
    res = get_entity_stats()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return EntityStatsResponse(**res)


@app.get("/entities/countries")
def entities_countries():
    """Lista de países disponíveis no cadastro de entidades."""
    return {"countries": list_entity_countries()}


@app.get("/entities/autocomplete")
def entities_autocomplete(q: str = Query(..., min_length=1), size: int = Query(10, ge=1, le=30)):
    """Sugestões de empresas a partir do cadastro de entidades."""
    res = search_entities(q=q, size=size, sort_by="contracts_count", sort_order="desc")
    return {
        "query": q,
        "suggestions": [
            {"nif": it.get("nif"), "name": it.get("name"), "country": it.get("country")}
            for it in res.get("items", [])
        ],
    }


@app.get("/entities/{nif}", response_model=EntityDetailResponse)
def entities_detail(nif: str):
    """Ficha da empresa do cadastro de entidades, com o enriquecimento já guardado."""
    entity = get_entity_by_nif(nif)
    if entity.get("error") and not entity.get("name"):
        raise HTTPException(status_code=404, detail=entity["error"])

    name = entity.get("name")

    try:
        trademarks = get_company_trademarks(company_nif=nif, company_name=name, size=50)
        entity["trademarks"] = trademarks.get("items", [])
        entity["trademarks_total"] = trademarks.get("total", 0)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Falha ao ler marcas de {nif}: {exc}")

    try:
        firmas = get_company_firmas(company_nif=nif, company_name=name, size=50)
        entity["firmas"] = firmas.get("items", [])
        entity["firmas_total"] = firmas.get("total", 0)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Falha ao ler firmas de {nif}: {exc}")

    entity.pop("error", None)
    return EntityDetailResponse(**entity)


# Servir a React SPA da chat-ui (build estático) — deve ser registrado DEPOIS das rotas de API
# para que os endpoints JSON sejam resolvidos antes do catch-all da SPA.

@app.get("/forecast")
@app.get("/trading")
@app.get("/ticker-detail")
@app.get("/rag")
@app.get("/elastic")
@app.get("/contracts")
@app.get("/contracts/dashboard")
@app.get("/contracts/search")
@app.get("/empresas-iq")
@app.get("/search")
@app.get("/import")
def serve_spa_page():
    return FileResponse(str(UI_BUILD_DIR / "index.html"))


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "FinanceLLM API",
        "models": ["gpt2", "mistral", "bloomberg"],
        "features": ["chat", "forecast", "rag", "elasticsearch"],
        "rag_model": None,
    }


@app.get("/health")
def health():
    return {"status": "healthy", "models": ["gpt2", "mistral", "bloomberg"], "features": ["chat", "forecast", "rag", "elasticsearch"]}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    result = run_chat(req.messages, backend=backend)
    return ChatResponse(
        message=result["message"],
        sources=result["sources"],
        tools=result["tools"],
    )


@app.post("/chat/stream")
def chat_stream_post(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )


@app.get("/chat/stream")
def chat_stream_get(_payload: Annotated[str, Query(...)], backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    payload = json.loads(_payload)
    req = ChatRequest(**payload)
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )


@app.get("/tickers")
def list_tickers(query: str = Query("", min_length=0)):
    """Devolve lista de tickers conhecidos, com filtro opcional."""
    tickers_path = ROOT / "data" / "tickers_extended.json"
    tickers = json.loads(tickers_path.read_text(encoding="utf-8")) if tickers_path.exists() else []
    q = query.strip().upper()
    if q:
        tickers = [t for t in tickers if q in t.upper()]
    return {"tickers": tickers}


@app.post("/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest):
    """Executa o pipeline ARIMA para o ticker pedido e devolve previsões + séries."""
    order_str = (req.order or "2,1,2").strip().lower()
    if order_str == "auto":
        order = (2, 1, 2)
    else:
        try:
            order = tuple(int(x) for x in order_str.split(","))
        except Exception:
            raise HTTPException(status_code=400, detail="Ordem ARIMA inválida. Use o formato p,d,q (ex: 2,1,2) ou 'auto'.")

    ticker = _normalize_ticker(req.ticker)
    try:
        info = get_stock_info(ticker)
        result = run_full_pipeline(
            ticker=ticker,
            period=req.period,
            order=order,
            train_ratio=req.train_ratio,
            future_steps=req.future_days,
            save_plot=True,
        )
        data = result.to_dict()
        forecast_points = [
            ForecastPoint(date=f["date"], price=f["price"], lower=f.get("lower"), upper=f.get("upper"))
            for f in data["forecast"]
        ]
        series = [ForecastSeries(date=s["date"], value=s["value"], type=s["type"]) for s in data["series"]]
        plot_url = None
        if result.plot_path:
            plot_url = f"/forecast/plot/{result.plot_path.name}"
        return ForecastResponse(
            ticker=ticker,
            order=result.order,
            train_days=data["train_days"],
            test_days=data["test_days"],
            rmse=result.rmse,
            mape=result.mape,
            ljung_box_pvalue=result.ljung_box_pvalue,
            last_train_date=data["last_train_date"],
            last_test_date=data["last_test_date"],
            currency=info.get("currency", "USD"),
            company_name=info.get("name", ticker),
            forecast=forecast_points,
            series=series,
            plot_url=plot_url,
            plot_path=str(result.plot_path) if result.plot_path else None,
            model_summary=result.model_summary,
            explanation=result.generate_explanation(
                currency=info.get("currency", "USD"),
                company_name=info.get("name", ticker),
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar previsão para {ticker}: {exc}")


@app.post("/sentiment/analyze/{ticker}", response_model=SentimentBlendedResponse)
def sentiment_analyze(
    ticker: str,
    backend: str = Query("kronos", pattern="^(arima|kronos)$"),
    future_days: int = Query(5, ge=1, le=30),
    period: str = Query("1y", min_length=2),
    include_features: bool = Query(True),
):
    """Executa o pipeline de análise de sentimento e blended forecast para um ticker."""
    ticker = _normalize_ticker(ticker)
    try:
        result = generate_sentiment_blended_forecast(
            ticker=ticker,
            future_days=future_days,
            period=period,
            backend=backend,
            include_features=include_features,
        )
        if result.get("error"):
            raise HTTPException(status_code=500, detail=f"Erro no pipeline de sentimento para {ticker}: {result['error']}")

        base_forecast = [ForecastPoint(date=f["date"], price=f["price"]) for f in result.get("base_forecast", [])]
        adjusted_forecast = [
            ForecastPoint(date=f["date"], price=f["price"], lower=f.get("lower"), upper=f.get("upper"))
            for f in result.get("adjusted_forecast", [])
        ]
        signals = result.get("signals", {})
        return SentimentBlendedResponse(
            ticker=ticker,
            base_model=result.get("base_model", backend),
            period=period,
            future_days=future_days,
            base_forecast=base_forecast,
            adjusted_forecast=adjusted_forecast,
            signals=ForecastSignal(
                sentiment_signal=signals.get("sentiment_signal", 0.0),
                macro_signal=signals.get("macro_signal", 0.0),
                earnings_signal=signals.get("earnings_signal", 0.0),
                blended_signal=signals.get("blended_signal", 0.0),
                weights=signals.get("weights", {}),
            ),
            features=result.get("features", {}),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro no pipeline de sentimento para {ticker}: {exc}")


@app.get("/forecast/plot/{filename}")
def forecast_plot(filename: str):
    """Serve o gráfico de previsão gerado."""
    path = FORECAST_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Gráfico não encontrado.")
    return FileResponse(path, media_type="image/png")


@app.get("/tickers/search/yahoo", response_model=TickerSearchResponse)
def yahoo_ticker_search(query: str = Query(..., min_length=1, description="Termo a pesquisar no Yahoo Finance")):
    """Pesquisa tickers/empresas diretamente no Yahoo Finance."""
    results = yahoo_search(query, max_results=12)
    return TickerSearchResponse(
        query=query,
        tickers=[r["symbol"] for r in results],
        yahoo_results=[YahooSearchResult(**r) for r in results],
    )


@app.get("/tickers/{ticker}/info", response_model=TickerInfoResponse)
def ticker_info(ticker: str):
    """Devolve informação fundamental de um ticker."""
    ticker = _normalize_ticker(ticker)
    info = get_stock_info(ticker)
    if info.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao obter info de {ticker}: {info['error']}")
    return TickerInfoResponse(
        ticker=ticker,
        name=info.get("name"),
        currency=info.get("currency"),
        price=info.get("price"),
        market_cap=info.get("market_cap"),
        pe=info.get("pe"),
        eps=info.get("eps"),
        dividend_yield=info.get("dividend_yield"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        website=info.get("website"),
        country=info.get("country"),
        employees=info.get("employees"),
        summary=info.get("summary"),
        exchange=info.get("exchange"),
        quote_type=info.get("quote_type"),
        beta=info.get("beta"),
        target_mean_price=info.get("target_mean_price"),
        target_high_price=info.get("target_high_price"),
        target_low_price=info.get("target_low_price"),
        recommendation=info.get("recommendation"),
        recommendation_mean=info.get("recommendation_mean"),
        number_of_analysts=info.get("number_of_analysts"),
        roe=info.get("roe"),
        kpis=info.get("kpis", {}),
    )


@app.get("/tickers/{ticker}/history", response_model=TickerHistoryResponse)
def ticker_history(
    ticker: str,
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
):
    """Devolve histórico de preços de um ticker."""
    import pandas as pd

    ticker = _normalize_ticker(ticker)
    df = get_stock_history(ticker, period=period)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Sem histórico para {ticker} no período {period}.")
    # Normalizar colunas
    cols = {c.lower(): c for c in df.columns}
    points = []
    for _, row in df.iterrows():
        date = row.get("Date")
        if pd.isna(date):
            continue
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")
        else:
            date = str(date)[:10]
        points.append(
            HistoryPoint(
                date=date,
                open=float(row[cols.get("open", "Open")]) if not pd.isna(row.get(cols.get("open", "Open"))) else None,
                high=float(row[cols.get("high", "High")]) if not pd.isna(row.get(cols.get("high", "High"))) else None,
                low=float(row[cols.get("low", "Low")]) if not pd.isna(row.get(cols.get("low", "Low"))) else None,
                close=float(row[cols.get("close", "Close")]) if not pd.isna(row.get(cols.get("close", "Close"))) else None,
                volume=float(row[cols.get("volume", "Volume")]) if not pd.isna(row.get(cols.get("volume", "Volume"))) else None,
            )
        )
    return TickerHistoryResponse(ticker=ticker, period=period, points=points)


@app.get("/tickers/{ticker}/financials", response_model=FinancialsResponse)
def ticker_financials(ticker: str):
    """Devolve demonstrações financeiras anuais (income statement, balance sheet, cash flow)."""
    ticker = _normalize_ticker(ticker)
    data = get_financials(ticker)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao obter financials de {ticker}: {data['error']}")
    return FinancialsResponse(
        ticker=ticker,
        income_statement=data.get("income_statement", {}),
        balance_sheet=data.get("balance_sheet", {}),
        cash_flow=data.get("cash_flow", {}),
        quarterly_income_statement=data.get("quarterly_income_statement", {}),
        quarterly_balance_sheet=data.get("quarterly_balance_sheet", {}),
        quarterly_cash_flow=data.get("quarterly_cash_flow", {}),
    )


@app.get("/tickers/{ticker}/sec-filings", response_model=SecFilingsResponse)
def ticker_sec_filings(ticker: str, days: int = Query(365, ge=30, le=3650)):
    """Devolve os SEC filings publicados no Yahoo Finance para o ticker."""
    ticker = _normalize_ticker(ticker)
    filings = get_sec_filings_yahoo(ticker, max_age_days=days)
    return SecFilingsResponse(
        ticker=ticker,
        filings=[SecFiling(**f) for f in filings],
    )


@app.post("/tickers/add", response_model=AddTickerResponse)
def add_new_ticker(req: AddTickerRequest):
    """Adiciona um ticker à lista local, validando-o contra o Yahoo Finance."""
    result = add_ticker(req.ticker)
    return AddTickerResponse(**result)


@app.get("/tickers/{ticker}/holders", response_model=HoldersResponse)
def ticker_holders(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_holders(ticker)
    return HoldersResponse(**data)


@app.get("/tickers/{ticker}/sustainability", response_model=SustainabilityResponse)
def ticker_sustainability(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_sustainability(ticker)
    return SustainabilityResponse(**data)


@app.get("/tickers/{ticker}/recommendations", response_model=RecommendationsResponse)
def ticker_recommendations(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_recommendations(ticker)
    return RecommendationsResponse(**data)


@app.get("/tickers/{ticker}/calendar", response_model=CalendarResponse)
def ticker_calendar(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_calendar(ticker)
    return CalendarResponse(**data)


@app.get("/tickers/{ticker}/news", response_model=NewsResponse)
def ticker_news(ticker: str, max_items: int = Query(10, ge=1, le=50)):
    ticker = _normalize_ticker(ticker)
    data = get_news(ticker, max_items=max_items)
    return NewsResponse(news=[NewsItem(**n) for n in data.get("news", [])], **{k: v for k, v in data.items() if k != "news"})


@app.get("/tickers/{ticker}/options", response_model=OptionsResponse)
def ticker_options(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_options(ticker)
    return OptionsResponse(**data)


@app.get("/tickers/{ticker}/actions", response_model=ActionsResponse)
def ticker_actions(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_actions(ticker)
    return ActionsResponse(**data)


@app.get("/tickers/{ticker}/technical", response_model=TechnicalResponse)
def ticker_technical(ticker: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$")):
    """Devolve indicadores técnicos calculados a partir do histórico de preços."""
    ticker = _normalize_ticker(ticker)
    data = get_technical_indicators(ticker, period=period)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao calcular indicadores para {ticker}: {data['error']}")
    keys = [
        "price", "volume", "sma20", "sma50", "sma200", "ema12", "ema26",
        "rsi14", "macd", "macd_signal", "macd_histogram", "bb_upper", "bb_middle",
        "bb_lower", "atr14", "obv",
    ]
    points = []
    dates = data.get("dates", [])
    for i, d in enumerate(dates):
        kwargs = {"date": d}
        for k in keys:
            kwargs[k] = data.get(k, [])[i] if i < len(data.get(k, [])) else None
        points.append(TechnicalPoint(**kwargs))
    return TechnicalResponse(ticker=ticker, period=period, points=points)


@app.get("/tickers/{ticker}/technical/explain", response_model=TechnicalExplanation)
def ticker_technical_explain(ticker: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$")):
    """Gera um resumo textual simples do que cada painel técnico indica."""
    ticker = _normalize_ticker(ticker)
    data = get_technical_indicators(ticker, period=period)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao calcular indicadores para {ticker}: {data['error']}")
    explanation = explain_technical_indicators(data)
    return TechnicalExplanation(ticker=ticker, period=period, **explanation)


@app.get("/elastic/status", response_model=ElasticStatus)
def elastic_status():
    """Devolve o estado de ligação ao Elasticsearch."""
    return get_elastic_status()


@app.post("/elastic/ingest/prices/{ticker}", response_model=ElasticIngestPricesResponse)
async def elastic_ingest_prices(
    ticker: str,
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
    interval: str = Query("1d", pattern="^(1d|1wk|1mo)$"),
):
    """Obtém histórico de preços via yfinance e indexa no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_prices(ticker, period=period, interval=interval)


@app.post("/elastic/ingest/news/{ticker}", response_model=ElasticIngestNewsResponse)
async def elastic_ingest_news(
    ticker: str,
    auto_analyze: bool = Query(True, description="Executar análise NLP automaticamente após ingestão"),
    backend: str = Query("gpt2", pattern="^(gpt2|mistral)$", description="Modelo de NLP a utilizar"),
):
    """Obtém notícias via yfinance e indexa no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_news(ticker, backend=backend, auto_analyze=auto_analyze)


@app.post("/elastic/ingest/{ticker}")
async def elastic_ingest_ticker(
    ticker: str,
    req: ElasticIngestRequest = ElasticIngestRequest(),
):
    """Indexa preços e notícias de um ticker no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_all(ticker, period=req.period, interval=req.interval)


@app.get("/elastic/search/prices/{ticker}", response_model=ElasticSearchPricesResponse)
def elastic_search_prices(
    ticker: str,
    start_date: str = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data final (YYYY-MM-DD)"),
    size: int = Query(1000, ge=1, le=10000),
):
    """Pesquisa preços indexados por ticker e intervalo de datas."""
    ticker = _normalize_ticker(ticker)
    return search_ticker_prices(ticker, start_date=start_date, end_date=end_date, size=size)


@app.get("/elastic/search/news/{ticker}", response_model=ElasticSearchNewsResponse)
async def elastic_search_news(
    ticker: str,
    q: str = Query(None, description="Termo de pesquisa no título/resumo"),
    start_date: str = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data final (YYYY-MM-DD)"),
    size: int = Query(50, ge=1, le=500),
):
    """Pesquisa notícias indexadas por ticker e texto."""
    ticker = _normalize_ticker(ticker)
    return await search_ticker_news(ticker, q=q, start_date=start_date, end_date=end_date, size=size)


@app.get("/elastic/search/global", response_model=ElasticSearchGlobalResponse)
async def elastic_search_global(
    q: str = Query(..., min_length=1, description="Termo de pesquisa global"),
    from_: int = Query(0, ge=0, alias="from", description="Offset de resultados"),
    size: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None, description="Filtrar por fonte (publisher)"),
    sentiment: Optional[str] = Query(None, description="Filtrar por sentimento"),
    topic: Optional[str] = Query(None, description="Filtrar por tópico"),
):
    """Pesquisa global tipo Google em todas as notícias indexadas por texto."""
    result = search_all_tickers(
        q,
        from_=from_,
        size=size,
        source=source,
        sentiment=sentiment,
        topic=topic,
    )
    if result.get("error"):
        return ElasticSearchGlobalResponse(query=q, total=0, error=result["error"])

    items = [
        ElasticSearchResult(
            ticker=item.get("ticker", ""),
            title=item.get("title"),
            summary=item.get("summary"),
            publisher=item.get("publisher"),
            published=item.get("published"),
            url=item.get("url"),
            source=item.get("source"),
            score=item.get("score"),
            sentiment=item.get("sentiment") or item.get("sentiment_label"),
            topics=item.get("topics") or [],
        )
        for item in result.get("items", [])
    ]
    return ElasticSearchGlobalResponse(
        query=q,
        total=result.get("total", 0),
        items=items,
    )


@app.get("/elastic/search/autocomplete", response_model=ElasticAutocompleteResponse)
async def elastic_search_autocomplete(
    q: str = Query(..., min_length=1, description="Prefixo para autocomplete"),
    size: int = Query(12, ge=1, le=50),
):
    """Sugestões de autocomplete (tickers, títulos, publishers, tópicos)."""
    result = autocomplete_suggestions(q, size=size)
    if result.get("error"):
        return ElasticAutocompleteResponse(query=q, error=result["error"])

    suggestions = [
        ElasticSuggestion(
            text=s.get("text", ""),
            type=s.get("type", "title"),
            ticker=s.get("ticker"),
            count=s.get("count"),
        )
        for s in result.get("suggestions", [])
    ]
    return ElasticAutocompleteResponse(query=q, suggestions=suggestions)


@app.get("/elastic/tickers", response_model=ElasticTickerListResponse)
def elastic_list_tickers():
    """Lista os tickers com dados de preços indexados no Elasticsearch."""
    from api.elasticsearch_client import list_indexed_tickers
    return ElasticTickerListResponse(tickers=list_indexed_tickers())


@app.delete("/elastic/tickers/{ticker}", response_model=ElasticDeleteResponse)
def elastic_delete_ticker(ticker: str):
    """Apaga todos os dados de preços e notícias de um ticker no Elasticsearch."""
    from api.elasticsearch_client import delete_ticker_data
    ticker = _normalize_ticker(ticker)
    result = delete_ticker_data(ticker)
    return ElasticDeleteResponse(
        ticker=result.get("ticker", ticker),
        prices_deleted=result.get("prices_deleted"),
        news_deleted=result.get("news_deleted"),
        error=result.get("error"),
    )


@app.post("/elastic/analyze/news/{ticker}", response_model=ElasticAnalyzeNewsResponse)
def elastic_analyze_news(
    ticker: str,
    q: str = Query(None, description="Termo de pesquisa no título/resumo"),
    start_date: str = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data final (YYYY-MM-DD)"),
    size: int = Query(50, ge=1, le=200),
    backend: str = Query("gpt2", pattern="^(gpt2|mistral)$"),
):
    """Analisa notícias indexadas com NLP (classificação, tradução PT, sumário, entidades)."""
    from api.elasticsearch_client import fetch_news_for_analysis, index_analyzed_news_items
    from api.news_nlp import analyze_news_batch

    ticker = _normalize_ticker(ticker)
    items = fetch_news_for_analysis(ticker, q=q, start_date=start_date, end_date=end_date, size=size)
    if not items:
        return ElasticAnalyzeNewsResponse(
            ticker=ticker,
            analyzed_count=0,
            total_items=0,
            message="Nenhuma notícia encontrada para análise.",
        )

    batch = [{"title": it.get("title", ""), "summary": it.get("summary", ""), "ticker": ticker} for it in items]
    analyses = analyze_news_batch(batch, backend=backend, ticker=ticker)
    result = index_analyzed_news_items(ticker, items, analyses)

    # Reconstrói e guarda o grafo de entidades/notícias para refletir a análise atualizada.
    try:
        from api.elasticsearch_client import fetch_news_for_analysis, save_news_graph
        from api.news_nlp import build_news_entity_graph

        analyzed_items = fetch_news_for_analysis(ticker, q=q, start_date=start_date, end_date=end_date, size=size)
        graph = build_news_entity_graph(ticker, analyzed_items)
        save_news_graph(ticker, graph)
    except Exception as exc:
        # O grafo é opcional; não falha a análise se algo correr mal aqui.
        import logging
        logging.getLogger(__name__).warning(f"Falha ao reconstruir grafo para {ticker}: {exc}")

    return ElasticAnalyzeNewsResponse(
        ticker=result.get("ticker", ticker),
        analyzed_count=result.get("indexed_count", 0),
        total_items=result.get("total_items", len(items)),
        errors=result.get("errors", 0),
        message=f"Analisadas e indexadas {result.get('indexed_count', 0)} notícias.",
        error=result.get("error"),
    )


@app.get("/elastic/graph/news/{ticker}", response_model=ElasticNewsGraphResponse)
def elastic_news_graph(
    ticker: str,
    source: str = Query("es", pattern="^(es|build)$"),
):
    """Devolve grafo de notícias e entidades (carregado do ES ou construído a partir das notícias)."""
    from api.elasticsearch_client import fetch_news_for_analysis, load_news_graph, save_news_graph
    from api.news_nlp import build_news_entity_graph

    ticker = _normalize_ticker(ticker)
    if source == "es":
        graph = load_news_graph(ticker)
        if graph:
            return ElasticNewsGraphResponse(
                ticker=graph.get("ticker", ticker),
                graph_type=graph.get("graph_type", "news_entities"),
                node_count=len(graph.get("nodes", [])),
                edge_count=len(graph.get("edges", [])),
                nodes=graph.get("nodes", []),
                edges=graph.get("edges", []),
            )

    items = fetch_news_for_analysis(ticker, size=200)
    if not items:
        return ElasticNewsGraphResponse(ticker=ticker, graph_type="news_entities", node_count=0, edge_count=0)

    graph = build_news_entity_graph(ticker, items)
    save_news_graph(ticker, graph)
    return ElasticNewsGraphResponse(
        ticker=ticker,
        graph_type="news_entities",
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        nodes=graph.get("nodes", []),
        edges=graph.get("edges", []),
    )


# --- Contratos públicos ---

@app.post("/contracts/ingest", response_model=ContractIngestResponse)
def contracts_ingest(req: ContractIngestRequest):
    """Indexa contratos normalizados para o Elasticsearch."""
    year = req.year
    years = [year] if year else list_contract_years()
    if not years:
        raise HTTPException(status_code=404, detail="Nenhum JSONL de contratos encontrado")

    total_indexed = 0
    total_total = 0
    total_errors = 0
    messages = []
    for y in years:
        jsonl_path = ROOT / "data" / "processed" / "contratos" / f"contratos_{y}.jsonl"
        if not jsonl_path.exists():
            continue
        res = bulk_index_contracts_from_jsonl(
            jsonl_path=jsonl_path,
            chunk_size=req.chunk_size,
            max_records=req.max_records,
        )
        if res.get("error"):
            raise HTTPException(status_code=502, detail=res.get("error"))
        total_indexed += res.get("indexed_count", 0)
        total_total += res.get("total", 0)
        total_errors += res.get("errors", 0)
        messages.append(f"{y}: {res.get('indexed_count', 0)} indexados")

    return ContractIngestResponse(
        indexed_count=total_indexed,
        total=total_total,
        errors=total_errors,
        message="; ".join(messages) if messages else None,
    )


@app.post("/contracts/search", response_model=ContractSearchResponse)
def contracts_search(req: ContractSearchRequest):
    """Pesquisa contratos públicos no Elasticsearch."""
    res = search_contracts(
        q=req.q,
        year=req.year,
        entity=req.entity,
        nif=req.nif,
        counterparty_nif=req.counterparty_nif,
        region=req.region,
        cpv_code=req.cpv_code,
        min_price=req.min_price,
        max_price=req.max_price,
        start_date=req.start_date,
        end_date=req.end_date,
        size=req.size,
        from_=req.from_,
        sort_by=req.sort_by,
        sort_order=req.sort_order,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractSearchResponse(
        query=res.get("query"),
        total=res.get("total", 0),
        items=[ContractItem(**item) for item in res.get("items", [])],
        from_=req.from_,
        size=req.size,
    )


@app.post("/contracts/chat", response_model=ContractChatResponse)
def contracts_chat(req: ContractChatRequest):
    """Responde perguntas sobre contratos públicos usando RAG."""
    try:
        answer, sources = get_contracts_chat_answer(
            question=req.question,
            top_k=req.top_k,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
        )
        return ContractChatResponse(answer=answer, sources=sources)
    except Exception as exc:
        return ContractChatResponse(
            answer=f"Erro ao responder: {exc}",
            sources=[],
            error=str(exc),
        )


@app.get("/contracts/status", response_model=ContractStatusResponse)
def contracts_status_endpoint():
    """Devolve contagem total e anos indexados de contratos."""
    res = contracts_status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractStatusResponse(total=res.get("total", 0), years=res.get("years", []))


@app.get("/contracts/years", response_model=ContractYearsResponse)
def contracts_years():
    """Devolve anos disponíveis e total indexado por ano."""
    res = list_contract_years()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractYearsResponse(
        available=res.get("available", []),
        indexed=[{"year": item["year"], "count": item["count"]} for item in res.get("indexed", [])],
    )


@app.get("/contracts/autocomplete", response_model=ContractAutocompleteResponse)
def contracts_autocomplete_endpoint(q: str = Query(..., min_length=1), size: int = Query(12, ge=1, le=50)):
    """Autocomplete de entidades e CPV para contratos."""
    res = contracts_autocomplete(q=q, size=size)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractAutocompleteResponse(query=q, suggestions=res.get("suggestions", []))


@app.get("/contracts/analytics", response_model=ContractAnalyticsResponse)
def contracts_analytics(
    q: Optional[str] = Query(None),
    year: Optional[int] = Query(None, description="Ano para filtrar as agregações"),
    entity: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    cpv_code: Optional[str] = Query(None),
    region: Optional[str] = Query(None, description="Região NUTS (código ou string completa)"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    top_entities: int = Query(8, ge=1, le=50),
    top_cpv: int = Query(8, ge=1, le=50),
):
    """Devolve analytics/aggregações para o dashboard de contratos."""
    res = get_contract_analytics(
        q=q, year=year, entity=entity, nif=nif, cpv_code=cpv_code, region=region,
        min_price=min_price, max_price=max_price, start_date=start_date, end_date=end_date,
        top_entities=top_entities, top_cpv=top_cpv,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return ContractAnalyticsResponse(**res)


@app.get("/contracts/analytics/regional", response_model=ContractRegionalResponse)
def contracts_regional_analytics(year: Optional[int] = Query(None), size: int = Query(30, ge=1, le=100)):
    """Agrega contratos por região NUTS."""
    result = get_contract_regional_analytics(year=year, size=size)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return ContractRegionalResponse(**result)


@app.get("/contracts/analytics/network", response_model=ContractGraphResponse)
def contracts_network(
    limit: int = Query(500, ge=1, le=2000),
    region: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    role: Optional[str] = Query("all"),
):
    """Devolve a rede de entidades ligadas por contratos, filtrável por região e entidade."""
    result = get_contract_network(limit=limit, region=region, nif=nif, role=role)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return ContractGraphResponse(**result)


@app.get("/contracts/analytics/relations", response_model=ContractRelationsResponse)
def contracts_relations(
    limit: int = Query(1000, ge=1, le=2000),
    region: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    counterparty_nif: Optional[str] = Query(None),
    role: Optional[str] = Query("all"),
):
    """Devolve relações agregadas entre adjudicantes e adjudicatários, filtráveis."""
    result = get_contract_relationships(
        limit=limit,
        region=region,
        nif=nif,
        counterparty_nif=counterparty_nif,
        role=role,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return ContractRelationsResponse(**result)


# --- Grafos dinâmicos (construtor por dimensões) ---

@app.get("/contracts/analytics/graph/dimensions", response_model=GraphDimensionsResponse)
def contracts_graph_dimensions():
    """Lista as dimensões disponíveis para construir grafos de contratos."""
    return GraphDimensionsResponse(
        dimensions=[
            GraphDimensionOption(key=key, label=spec["label"], type=spec["type"])
            for key, spec in GRAPH_DIMENSIONS.items()
        ]
    )


@app.get("/contracts/analytics/graph", response_model=ContractGraphBuildResponse)
def contracts_graph(
    dimension_a: str = Query(..., description="Dimensão dos nós (ex.: adjudicante, cpv_classe, regiao)"),
    dimension_b: Optional[str] = Query(
        None,
        description="Dimensão das arestas. Igual a dimension_a cria uma rede de co-ocorrência; "
        "omisso devolve apenas nós.",
    ),
    metric: str = Query("valor", pattern="^(valor|contratos)$"),
    mode: str = Query(
        "auto",
        pattern="^(auto|exato|amostra)$",
        description="`exato` usa agregações (todos os contratos, sem amostragem) quando só há uma "
        "dimensão; com arestas percorre todos os contratos até ao teto do servidor.",
    ),
    q: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    region: Optional[str] = Query(None),
    cpv_code: Optional[str] = Query(None),
    min_value: Optional[float] = Query(None, ge=0),
    max_value: Optional[float] = Query(None, ge=0),
    limit: int = Query(60, ge=0, le=10_000, description="Nós a manter (0 = todos)"),
    edge_limit: int = Query(400, ge=0, le=30_000, description="Arestas a manter (0 = todas)"),
    sample: int = Query(3000, ge=0, le=400_000, description="Contratos analisados (0 = todos)"),
    sample_order: str = Query("valor", pattern="^(valor|recentes)$"),
):
    """Constrói um grafo de contratos a partir de dimensões (entidades, CPV, território, tempo).

    Devolve nós e arestas agregados com contagem de contratos e valor, permitindo
    montar redes de entidades, hierarquias CPV, fluxos de valor e mapas de território.
    """
    result = build_contract_graph(
        dimension_a=dimension_a,
        dimension_b=dimension_b,
        metric=metric,
        mode=mode,
        q=q,
        year=year,
        region=region,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        limit=limit,
        edge_limit=edge_limit,
        sample=sample,
        sample_order=sample_order,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return ContractGraphBuildResponse(**result)


# --- Preferências do utilizador (favoritos, pastas do dossier e histórico) ---
# Guardadas no Elasticsearch (índice finance_user_state) para não se perderem ao
# recarregar a página ou ao mudar de origem (localhost vs 127.0.0.1).

@app.get("/favorites", response_model=FavoriteListResponse)
def favorites_list():
    """Lista as fichas favoritas (entidades e contratos)."""
    result = list_favorites()
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteListResponse(**result)


@app.put("/favorites", response_model=FavoriteMutationResponse)
def favorites_save(item: FavoriteItem):
    """Marca uma ficha como favorita (idempotente)."""
    payload = item.model_dump()
    payload["added_at"] = datetime.utcnow().isoformat() + "Z"
    result = save_favorite(payload)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(**result)


@app.delete("/favorites/{kind}/{item_id}", response_model=FavoriteMutationResponse)
def favorites_delete(kind: str, item_id: str):
    """Remove uma ficha dos favoritos."""
    if kind not in {"entity", "contract"}:
        raise HTTPException(status_code=400, detail="kind tem de ser 'entity' ou 'contract'")
    result = delete_favorite(kind, item_id)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(**result)


@app.delete("/favorites", response_model=FavoriteMutationResponse)
def favorites_clear():
    """Remove todos os favoritos."""
    result = clear_favorites()
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(**result)


@app.get("/workspace", response_model=WorkspaceResponse)
def workspace_get():
    """Devolve o dossier: pastas de fichas e histórico de consultas."""
    result = get_workspace()
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return WorkspaceResponse(**result)


@app.put("/workspace/folders/{folder_id}", response_model=FavoriteMutationResponse)
def workspace_save_folder(folder_id: str, folder: WorkspaceFolderRequest):
    """Guarda (ou substitui) uma pasta do dossier com as suas fichas."""
    payload = folder.model_dump()
    payload["id"] = folder_id
    result = save_folder(payload)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(**result)


@app.delete("/workspace/folders/{folder_id}", response_model=FavoriteMutationResponse)
def workspace_delete_folder(folder_id: str):
    """Apaga uma pasta do dossier."""
    result = delete_folder(folder_id)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(**result)


@app.put("/workspace/history", response_model=FavoriteMutationResponse)
def workspace_save_history(req: WorkspaceHistoryRequest):
    """Guarda o histórico de fichas consultadas."""
    result = save_history(req.items)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return FavoriteMutationResponse(ok=True)


# --- Importação de entidades e contratos ---

@app.post("/import/preview", response_model=ImportPreviewResponse)
def import_preview(
    file: UploadFile = File(...),
    data_type: ImportDataType = Form("auto"),
):
    """Recebe um ficheiro .zip/.xlsx/.json e devolve pré-visualização das linhas."""
    try:
        content = file.file.read()
        result = parse_file(file.filename or "upload", content, data_type=data_type.value)
        return ImportPreviewResponse(
            data_type=ImportDataType(result["data_type"]),
            file_type=ImportFileType(result["file_type"]),
            filename=result["filename"],
            rows=[ImportPreviewRow(**row) for row in result["rows"]],
            total_rows=result["total_rows"],
            sample_schema=result["sample_schema"],
            errors=result["errors"],
            warnings=result["warnings"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao processar ficheiro: {exc}")


@app.post("/import/ingest", response_model=ImportIngestResponse)
def import_ingest(req: ImportIngestRequest):
    """Indexa as linhas pré-visualizadas (contratos no ES; entidades em ficheiro JSONL)."""
    try:
        res = ingest_rows(
            rows=[row.model_dump() if hasattr(row, "model_dump") else row.dict() for row in req.rows],
            data_type=req.data_type.value,
            options=(req.options.model_dump() if hasattr(req.options, "model_dump") else req.options.dict()),
        )
        return ImportIngestResponse(
            success=res.get("success", False),
            indexed_count=res.get("indexed_count", 0),
            total=res.get("total", 0),
            errors=res.get("errors", 0),
            linked_entities=res.get("linked_entities", 0),
            duplicate_count=res.get("duplicate_count", 0),
            deleted_count=res.get("deleted_count", 0),
            duplicate_ids=res.get("duplicate_ids", []),
            message=res.get("message"),
            error=res.get("error"),
            details=res.get("details", {}),
        )
    except Exception as exc:
        return ImportIngestResponse(success=False, error=str(exc), indexed_count=0, total=0, errors=0, linked_entities=0)


@app.get("/contracts/{idcontrato}", response_model=ContractItem)
def contract_detail(idcontrato: str):
    """Devolve um contrato individual para a ficha EmpresasIQ."""
    result = get_contract_by_id(idcontrato)
    if result.get("error"):
        raise HTTPException(status_code=result.get("status_code", 502), detail=result["error"])
    return ContractItem(**result)


@app.post("/contracts/{idcontrato}/analyze")
def analyze_contract_endpoint(idcontrato: str, req: ContractAnalyzeRequest = Body(...)):
    """Analisa um contrato com IA (Ollama/OpenAI/local) e ferramentas de pesquisa."""
    result = get_contract_by_id(idcontrato)
    if result.get("error"):
        raise HTTPException(status_code=result.get("status_code", 502), detail=result["error"])

    contract = result
    answer = analyze_contract(
        contract,
        question=req.question,
        model=req.model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        use_web_search=req.use_web_search,
        use_related_contracts=req.use_related_contracts,
    )
    return answer


@app.post("/contracts/export/excel")
def contracts_export_excel(req: ContractAnalyticsRequest = Body(...)):
    """Exporta contratos filtrados para Excel."""
    try:
        data = export_contracts_to_excel(
            q=req.q, year=req.year, entity=req.entity, nif=req.nif, cpv_code=req.cpv_code,
            min_price=req.min_price, max_price=req.max_price, start_date=req.start_date, end_date=req.end_date,
            max_records=10000,
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=contratos.xlsx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/contracts/export/pdf")
def contracts_export_pdf(req: ContractAnalyticsRequest = Body(...)):
    """Exporta contratos filtrados para PDF."""
    try:
        data = export_contracts_to_pdf(
            q=req.q, year=req.year, entity=req.entity, nif=req.nif, cpv_code=req.cpv_code,
            min_price=req.min_price, max_price=req.max_price, start_date=req.start_date, end_date=req.end_date,
            max_records=500,
        )
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=contratos.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



