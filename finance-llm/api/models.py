"""Esquemas Pydantic para a API IQ OS Chat."""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any, TYPE_CHECKING


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "finance-llm"
    backend: str = "gpt2"
    stream: bool = False


class Source(BaseModel):
    name: str
    url: Optional[str] = None
    value: Optional[str] = None


class ToolCall(BaseModel):
    tool: str
    input: dict
    output: Optional[str] = None


class SkillRef(BaseModel):
    """Skill (método) aplicada a uma resposta pelos assistentes do IQ OS."""

    id: Optional[str] = None
    name: Optional[str] = None
    when: Optional[str] = None
    steps: List[str] = []
    checks: List[str] = []
    tools: List[str] = []


class AgentGraphNode(BaseModel):
    """Nó de um grafo de agente dinâmico."""

    id: str
    label: Optional[str] = None
    kind: Literal["prompt", "tool", "rag", "conditional", "supervisor", "output"] = "prompt"
    prompt: Optional[str] = None
    tools: List[str] = []
    output_key: Optional[str] = None
    next: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None


class AgentGraphEdge(BaseModel):
    """Ligação entre nós de um grafo de agente dinâmico."""

    source: str
    target: str
    condition: Optional[Dict[str, Any]] = None


class AgentGraphDefinition(BaseModel):
    """Definição de grafo (nodes + edges). Se vazio, o motor usa um agente ReAct simples."""

    nodes: List[AgentGraphNode] = []
    edges: List[AgentGraphEdge] = []


class AgentToolRef(BaseModel):
    """Referência a uma ferramenta disponível no IQ OS."""

    tool_id: str
    provider: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    enabled: bool = True


class AgentConfig(BaseModel):
    """Configuração persistente de um agente dinâmico LangGraph."""

    agent_id: Optional[str] = None
    owner_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: List[str] = []
    backend: Optional[str] = None
    model: Optional[str] = None
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    system_prompt: Optional[str] = None
    graph: AgentGraphDefinition = Field(default_factory=AgentGraphDefinition)
    tools: List[AgentToolRef] = []
    rag_index: Optional[str] = None
    rag_mode: Optional[str] = Field(default=None, pattern="^(dense|hybrid|hybrid_rerank|crag|crag_rerank)$")
    enabled: bool = True
    is_public: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentConfigListResponse(BaseModel):
    """Lista de configurações de agentes dinâmicos."""

    agents: List[AgentConfig] = []
    total: int = 0


class AgentRunRequest(BaseModel):
    """Pedido de execução de um agente dinâmico."""

    agent_id: str
    message: str
    context: Optional[Dict[str, Any]] = None
    stream: bool = False
    thread_id: Optional[str] = None


class AgentRunMessage(BaseModel):
    """Mensagem no histórico de execução de um agente."""

    role: Literal["user", "assistant", "tool", "system"]
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None


class AgentRunStep(BaseModel):
    """Passo intermédio de execução (tool call / nó / fontes)."""

    kind: Literal["node", "tool", "tool_result", "rag", "thought", "error"]
    name: Optional[str] = None
    content: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class AgentRunResponse(BaseModel):
    """Resposta de execução de um agente dinâmico."""

    agent_id: str
    thread_id: str
    message: AgentRunMessage
    steps: List[AgentRunStep] = []
    sources: List["RagSource"] = []
    elapsed_seconds: Optional[float] = None
    error: Optional[str] = None
    uses: int = 0
    quality: Optional[str] = None
    enabled: bool = True
    created: bool = False
    merged: bool = False
    mode: Optional[str] = None


class ChatResponse(BaseModel):
    message: ChatMessage
    sources: List[Source] = []
    tools: List[ToolCall] = []
    chart: Optional[dict] = None
    skill: Optional[SkillRef] = None


class ForecastRequest(BaseModel):
    ticker: str
    future_days: int = 5
    period: str = "5y"
    order: str = "2,1,2"
    train_ratio: float = 0.85
    backend: Literal["arima", "kronos"] = "arima"
    use_sentiment: bool = False
    include_features: bool = True


class ForecastSignal(BaseModel):
    sentiment_signal: float = 0.0
    macro_signal: float = 0.0
    earnings_signal: float = 0.0
    blended_signal: float = 0.0
    weights: Dict[str, float] = {}


class ForecastPoint(BaseModel):
    date: str
    price: float
    lower: Optional[float] = None
    upper: Optional[float] = None


class SentimentBlendedResponse(BaseModel):
    ticker: str
    base_model: str
    period: str
    future_days: int
    base_forecast: List[ForecastPoint] = []
    adjusted_forecast: List[ForecastPoint] = []
    signals: ForecastSignal = Field(default_factory=ForecastSignal)
    features: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ForecastSeries(BaseModel):
    date: str
    value: float
    type: str


class ForecastResponse(BaseModel):
    ticker: str
    order: tuple[int, int, int]
    train_days: int
    test_days: int
    rmse: float
    mape: float
    ljung_box_pvalue: Optional[float] = None
    last_train_date: str
    last_test_date: str
    currency: str = "USD"
    company_name: Optional[str] = None
    forecast: List[ForecastPoint]
    series: List[ForecastSeries]
    plot_url: Optional[str] = None
    plot_path: Optional[str] = None
    model_summary: Optional[str] = None
    explanation: Optional[str] = None


class YahooSearchResult(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    quote_type: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class TickerSearchResponse(BaseModel):
    query: str
    tickers: List[str]
    yahoo_results: List[YahooSearchResult] = []


class TickerInfoResponse(BaseModel):
    ticker: str
    name: Optional[str] = None
    currency: Optional[str] = None
    price: Optional[float] = None
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    roe: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    employees: Optional[int] = None
    summary: Optional[str] = None
    exchange: Optional[str] = None
    quote_type: Optional[str] = None
    beta: Optional[float] = None
    target_mean_price: Optional[float] = None
    target_high_price: Optional[float] = None
    target_low_price: Optional[float] = None
    recommendation: Optional[str] = None
    recommendation_mean: Optional[float] = None
    number_of_analysts: Optional[int] = None
    kpis: Dict[str, Any] = {}


class HistoryPoint(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


class TickerHistoryResponse(BaseModel):
    ticker: str
    period: str
    points: List[HistoryPoint]


class FinancialsResponse(BaseModel):
    ticker: str
    income_statement: Dict[str, Any] = {}
    balance_sheet: Dict[str, Any] = {}
    cash_flow: Dict[str, Any] = {}
    quarterly_income_statement: Dict[str, Any] = {}
    quarterly_balance_sheet: Dict[str, Any] = {}
    quarterly_cash_flow: Dict[str, Any] = {}


class HoldersResponse(BaseModel):
    ticker: str
    institutional: Dict[str, Any] = {}
    mutual_fund: Dict[str, Any] = {}
    major: Dict[str, Any] = {}
    insider_transactions: Dict[str, Any] = {}
    insider_purchases: Dict[str, Any] = {}
    error: Optional[str] = None


class SustainabilityResponse(BaseModel):
    ticker: str
    esg: Dict[str, Any] = {}
    error: Optional[str] = None


class RecommendationsResponse(BaseModel):
    ticker: str
    recommendations: Dict[str, Any] = {}
    recommendations_summary: Dict[str, Any] = {}
    upgrades_downgrades: Dict[str, Any] = {}
    error: Optional[str] = None


class CalendarResponse(BaseModel):
    ticker: str
    calendar: Dict[str, Any] = {}
    earnings_dates: Dict[str, Any] = {}
    error: Optional[str] = None


class NewsItem(BaseModel):
    title: Optional[str] = None
    publisher: Optional[Any] = None
    published: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class NewsResponse(BaseModel):
    ticker: str
    news: List[NewsItem] = []
    error: Optional[str] = None


class OptionsResponse(BaseModel):
    ticker: str
    expiration_dates: List[str] = []
    chains: List[Dict[str, Any]] = []
    error: Optional[str] = None


class ActionsResponse(BaseModel):
    ticker: str
    actions: Dict[str, Any] = {}
    splits: Dict[str, Any] = {}
    dividends: Dict[str, Any] = {}
    error: Optional[str] = None


class TechnicalPoint(BaseModel):
    date: str
    price: Optional[float] = None
    volume: Optional[float] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    ema12: Optional[float] = None
    ema26: Optional[float] = None
    rsi14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    atr14: Optional[float] = None
    obv: Optional[float] = None


class TechnicalResponse(BaseModel):
    ticker: str
    period: str
    points: List[TechnicalPoint] = []
    error: Optional[str] = None


class TechnicalExplanation(BaseModel):
    ticker: str
    period: str
    summary: str
    price_trend: str
    sma_analysis: str
    rsi_analysis: str
    macd_analysis: str
    bb_analysis: str
    atr_analysis: str
    obv_analysis: str
    combined_signal: str
    error: Optional[str] = None


class SecFiling(BaseModel):
    date: str
    type: str
    title: str
    url: Optional[str] = None


class SecFilingsResponse(BaseModel):
    ticker: str
    filings: List[SecFiling] = []
    error: Optional[str] = None


class AddTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1)


class AddTickerResponse(BaseModel):
    ticker: str
    added: bool
    message: str


class UploadPdfResponse(BaseModel):
    doc_id: str
    title: str
    filename: str
    pages: int
    indexed: bool
    message: str


class RagSource(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    page: Optional[int] = None
    text: str
    score: Optional[float] = None
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None


class RagChatRequest(BaseModel):
    question: str
    top_k: int = 5
    max_new_tokens: int = 64
    temperature: float = 0.1
    doc_id: Optional[str] = None
    stream: bool = False
    # Fornecedor de IA para redigir a resposta ("provider:modelo"). Vazio = modelo
    # local do RAG (BloombergGPT-style), que é o comportamento de sempre.
    backend: Optional[str] = None
    # Estratégia de recuperação.
    mode: Optional[str] = Field(default="hybrid", pattern="^(dense|hybrid|hybrid_rerank|crag|crag_rerank)$")


class RagChatResponse(BaseModel):
    answer: str
    sources: List[RagSource] = []
    model_used: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    skill: Optional[SkillRef] = None
    mode: Optional[str] = None


class RagDocument(BaseModel):
    doc_id: str
    title: str
    filename: str
    pages: int
    indexed: bool
    size_bytes: int = 0
    created_at: float = 0.0
    updated_at: Optional[float] = None
    converter: Optional[str] = None


class RagDocumentUpdate(BaseModel):
    title: str = Field(..., min_length=1)


class RagDocumentsResponse(BaseModel):
    documents: List[RagDocument] = []


# --- Elasticsearch schemas ---

class ElasticStatus(BaseModel):
    available: bool
    version: Optional[str] = None
    cluster_name: Optional[str] = None
    message: str


class ElasticIngestPricesResponse(BaseModel):
    ticker: str
    indexed_count: int
    total_points: int
    period: str = "1y"
    interval: str = "1d"
    message: Optional[str] = None
    error: Optional[str] = None


class ElasticIngestNewsResponse(BaseModel):
    ticker: str
    indexed_count: int
    total_items: int
    analyzed_count: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class ElasticSearchPoint(BaseModel):
    ticker: str
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    period: Optional[str] = None
    ingested_at: Optional[str] = None


class ElasticSearchPricesResponse(BaseModel):
    ticker: str
    total: int
    points: List[ElasticSearchPoint] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error: Optional[str] = None


class NewsEntity(BaseModel):
    name: str
    type: str


class ElasticSearchNewsItem(BaseModel):
    ticker: str
    title: Optional[str] = None
    summary: Optional[str] = None
    publisher: Optional[str] = None
    published: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    ingested_at: Optional[str] = None
    analyzed_at: Optional[str] = None
    sentiment: Optional[str] = None
    language: Optional[str] = None
    translated_title: Optional[str] = None
    translated_summary: Optional[str] = None
    summary_pt: Optional[str] = None
    topics: List[str] = []
    entities: List[NewsEntity] = []


class ElasticSearchNewsResponse(BaseModel):
    ticker: str
    total: int
    items: List[ElasticSearchNewsItem] = []
    query: Optional[str] = None
    error: Optional[str] = None


class ElasticAnalyzeNewsResponse(BaseModel):
    ticker: str
    analyzed_count: int
    total_items: int
    errors: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


class ElasticNewsGraphResponse(BaseModel):
    ticker: str
    graph_type: str = "news_entities"
    node_count: int = 0
    edge_count: int = 0
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    error: Optional[str] = None


class ElasticTickerListResponse(BaseModel):
    tickers: List[str] = []


class ElasticIndexItem(BaseModel):
    index: str
    label: str
    docs: Optional[int] = None
    size: Optional[str] = None
    health: Optional[str] = None
    status: Optional[str] = None


class ElasticIndicesListResponse(BaseModel):
    indices: List[ElasticIndexItem] = []
    error: Optional[str] = None


class ElasticDeleteResponse(BaseModel):
    ticker: str
    prices_deleted: Optional[int] = None
    news_deleted: Optional[int] = None
    error: Optional[str] = None


class ElasticIngestRequest(BaseModel):
    period: str = "1y"
    interval: str = "1d"


class ElasticSearchResult(BaseModel):
    ticker: str
    title: Optional[str] = None
    summary: Optional[str] = None
    publisher: Optional[str] = None
    published: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None
    sentiment: Optional[str] = None
    topics: List[str] = []


class ElasticSearchGlobalResponse(BaseModel):
    query: str
    total: int
    items: List[ElasticSearchResult] = []
    error: Optional[str] = None


class ElasticSuggestion(BaseModel):
    text: str
    type: Literal["ticker", "title", "publisher", "topic"]
    ticker: Optional[str] = None
    count: Optional[int] = None


class ElasticAutocompleteResponse(BaseModel):
    query: str
    suggestions: List[ElasticSuggestion] = []
    error: Optional[str] = None


class RagExplainResponse(BaseModel):
    question: str
    answer_preview: str
    model_used: Optional[str] = None
    documents_used: List[str] = []
    pages_used: List[int] = []
    retrieval_scores: List[float] = []
    analysis: str
    mode: Optional[str] = None


class RagDocumentGraphNode(BaseModel):
    id: str
    doc_id: str
    page: Optional[int] = None
    text_preview: str
    section: Optional[str] = None
    chunk_index: int = 0


class RagDocumentGraphEdge(BaseModel):
    source: str
    target: str
    weight: float


class RagDocumentGraphResponse(BaseModel):
    doc_id: str
    title: str
    nodes: List[RagDocumentGraphNode] = []
    edges: List[RagDocumentGraphEdge] = []


# --- Contratos públicos ---

class ContractEntity(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    nif: Optional[str] = None
    code: Optional[str] = None


class ContractCpv(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None


class ContractPartyParsed(BaseModel):
    nif: Optional[str] = None
    nome: Optional[str] = None


class ContractParty(BaseModel):
    raw: Optional[List[str]] = None
    parsed: List[ContractPartyParsed] = []


class ContractItem(BaseModel):
    idcontrato: Optional[str] = None
    nAnuncio: Optional[str] = None
    TipoAnuncio: Optional[str] = None
    idINCM: Optional[str] = None
    idprocedimento: Optional[str] = None
    tipoContrato: Optional[List[str]] = None
    tipoprocedimento: Optional[str] = None
    objectoContrato: Optional[str] = None
    descContrato: Optional[str] = None
    adjudicantes: Optional[ContractParty] = None
    adjudicatarios: Optional[ContractParty] = None
    dataPublicacao: Optional[str] = None
    dataCelebracaoContrato: Optional[str] = None
    precoContratual: Optional[float] = None
    PrecoTotalEfetivo: Optional[float] = None
    precoBaseProcedimento: Optional[float] = None
    cpv: List[ContractCpv] = []
    localExecucao: Optional[List[str]] = None
    Ano: Optional[int] = None
    NUTs: Optional[List[str]] = None
    regime: Optional[str] = None
    regimeCadastro: Optional[str] = None
    regimeContratacao: Optional[str] = None
    regimeExecucao: Optional[str] = None
    entidade: Optional[str] = None
    entidadeDesc: Optional[str] = None
    tipoFimContrato: Optional[str] = None
    search_text: Optional[str] = None
    entities: List[ContractEntity] = []
    score: Optional[float] = None
    doc_id: Optional[str] = None
    # Detalhe publicado no portal (e peças do procedimento)
    prazoExecucao: Optional[float] = None
    fundamentacao: Optional[str] = None
    fundamentAjusteDireto: Optional[str] = None
    ProcedimentoCentralizado: Optional[str] = None
    numAcordoQuadro: Optional[str] = None
    DescrAcordoQuadro: Optional[str] = None
    dataDecisaoAdjudicacao: Optional[str] = None
    dataFechoContrato: Optional[str] = None
    justifNReducEscrContrato: Optional[str] = None
    CritMateriais: Optional[str] = None
    concorrentes: Optional[str] = None
    linkPecasProc: Optional[str] = None
    Observacoes: Optional[str] = None
    ContratEcologico: Optional[str] = None
    adjudicatarioPMEs: Optional[str] = None
    Lotes: Optional[str] = None
    TipoCriterioAdjudicacao: Optional[str] = None


class ContractDocumentLink(BaseModel):
    label: str
    url: str
    kind: Optional[str] = None
    host: Optional[str] = None


class ContractDocumentValue(BaseModel):
    label: str
    value: Any = None
    source: Optional[str] = None


class ContractDocumentPiece(BaseModel):
    name: str
    kind: Optional[str] = None
    text: Optional[str] = None


class ContractDocumentFact(BaseModel):
    label: str
    value: Any = None
    source: Optional[str] = None
    document: Optional[str] = None


class ContractDocumentResponse(BaseModel):
    contract_id: Optional[str] = None
    links: List[ContractDocumentLink] = []
    values: List[ContractDocumentValue] = []
    pieces: List[ContractDocumentPiece] = []
    highlights: List[ContractDocumentFact] = []
    note: Optional[str] = None
    error: Optional[str] = None


class ContractIngestRequest(BaseModel):
    year: Optional[int] = None
    max_records: Optional[int] = None
    chunk_size: int = 1000


class ContractIngestResponse(BaseModel):
    indexed_count: int
    total: int
    errors: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


class ContractSearchRequest(BaseModel):
    q: Optional[str] = None
    year: Optional[int] = None
    entity: Optional[str] = None
    nif: Optional[str] = None
    counterparty_nif: Optional[str] = None
    region: Optional[str] = None
    cpv_code: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    size: int = 20
    from_: int = Field(0, alias="from")
    sort_by: Optional[Literal["relevance", "dataPublicacao", "dataCelebracaoContrato", "precoContratual", "objectoContrato", "tipoContrato", "adjudicantes", "adjudicatarios"]] = "dataPublicacao"
    sort_order: Optional[Literal["asc", "desc"]] = "desc"


class ContractAnalyticsRequest(BaseModel):
    q: Optional[str] = None
    year: Optional[int] = None
    entity: Optional[str] = None
    nif: Optional[str] = None
    cpv_code: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top_entities: int = 8
    top_cpv: int = 8


class ContractSearchResponse(BaseModel):
    query: Optional[str] = None
    total: int = 0
    items: List[ContractItem] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    error: Optional[str] = None


class ContractAutocompleteResponse(BaseModel):
    query: Optional[str] = None
    suggestions: List[Dict[str, Any]] = []
    error: Optional[str] = None


class ContractStatusResponse(BaseModel):
    total: int = 0
    years: List[int] = []
    error: Optional[str] = None


class ContractYearInfo(BaseModel):
    year: int
    count: int


class ContractYearsResponse(BaseModel):
    available: List[int] = []
    indexed: List[ContractYearInfo] = []
    error: Optional[str] = None


class ContractChatRequest(BaseModel):
    question: str
    top_k: int = 5
    max_new_tokens: int = 256
    temperature: float = 0.1


class ContractAnalyzeRequest(BaseModel):
    question: Optional[str] = None
    model: str = ""  # vazio = usar provider/modelo padrão do sistema
    max_tokens: int = 1024
    temperature: float = 0.3
    use_web_search: bool = True
    use_related_contracts: bool = True


class ContractReportRequest(ContractAnalyzeRequest):
    """Pedido do relatório PDF (mesmos parâmetros da análise; a análise é gerada se faltar)."""

    analysis: Optional[str] = None


# --- Contratos franceses (DECP / data.gouv.fr) ------------------------------

class ContratoFrTitulaire(BaseModel):
    type_identifiant: Optional[str] = None
    id: Optional[str] = None
    nom: Optional[str] = None


class ContratoFrCpv(BaseModel):
    code: Optional[str] = None
    nom: Optional[str] = None


class ContratoFrImportRequest(BaseModel):
    filename: Optional[str] = None
    limit: Optional[int] = None
    force: bool = False
    index: bool = True


class ContratoFrIngestRequest(BaseModel):
    filename: Optional[str] = None
    limit: Optional[int] = None
    force: bool = False


class ContratoFrImportResponse(BaseModel):
    indexed_count: int = 0
    total: int = 0
    errors: int = 0
    path: Optional[str] = None
    seconds: Optional[float] = None
    error: Optional[str] = None


class ContratoFrSearchRequest(BaseModel):
    q: Optional[str] = None
    ano: Optional[int] = None
    nature: Optional[str] = None
    procedure: Optional[str] = None
    acheteur: Optional[str] = None
    acheteur_id: Optional[str] = None
    adjudicatario: Optional[str] = None
    adjudicatario_id: Optional[str] = None
    cpv_code: Optional[str] = None
    lieu_execution_code: Optional[str] = None
    lieu_execution_type: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_field: Optional[Literal["date_notification", "date_publication"]] = "date_publication"
    size: int = 20
    from_: int = Field(0, alias="from")
    sort_by: Optional[Literal["relevance", "date_notification", "date_publication", "montant", "valor", "ano"]] = "date_publication"
    sort_order: Optional[Literal["asc", "desc"]] = "desc"
    with_facets: bool = True


class ContratoFrAnalyticsRequest(BaseModel):
    q: Optional[str] = None
    ano: Optional[int] = None
    nature: Optional[str] = None
    procedure: Optional[str] = None
    acheteur: Optional[str] = None
    acheteur_id: Optional[str] = None
    adjudicatario: Optional[str] = None
    adjudicatario_id: Optional[str] = None
    cpv_code: Optional[str] = None
    lieu_execution_code: Optional[str] = None
    lieu_execution_type: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_field: Optional[Literal["date_notification", "date_publication"]] = "date_publication"
    top_acheteurs: int = 10
    top_adjudicatarios: int = 10
    top_cpv: int = 10
    value_buckets: int = 10


class ContratoFrEntitySearchRequest(BaseModel):
    q: Optional[str] = None
    kind: Optional[Literal["acheteur", "adjudicatario"]] = None
    ano: Optional[int] = None
    min_count: int = 1
    size: int = 20
    from_: int = Field(0, alias="from")


class ContratoFrAutocompleteRequest(BaseModel):
    q: str
    size: int = 10


class ContractChatSource(BaseModel):
    idcontrato: Optional[str] = None
    objectoContrato: Optional[str] = None
    adjudicante: Optional[str] = None
    adjudicatario: Optional[str] = None
    precoContratual: Optional[float] = None
    score: Optional[float] = None


class ContractChatResponse(BaseModel):
    answer: str
    sources: List[ContractChatSource] = []
    model_used: Optional[str] = None
    error: Optional[str] = None


class ImportFileType(str, Enum):
    zip = "zip"
    xlsx = "xlsx"
    json = "json"


class ImportDataType(str, Enum):
    contracts = "contracts"
    entities = "entities"
    auto = "auto"


class ImportPreviewRow(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    nif: Optional[str] = None
    objectoContrato: Optional[str] = None
    precoContratual: Optional[float] = None
    dataCelebracaoContrato: Optional[str] = None
    adjudicante: Optional[str] = None
    adjudicatario: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class ImportPreviewResponse(BaseModel):
    data_type: ImportDataType
    file_type: ImportFileType
    filename: str
    rows: List[ImportPreviewRow] = []
    total_rows: int = 0
    sample_schema: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []


class ImportOptions(BaseModel):
    link_entities: bool = True
    max_records: Optional[int] = None
    skip_validation: bool = False
    hard_reprocess: bool = False


class ImportIngestRequest(BaseModel):
    data_type: ImportDataType
    file_type: ImportFileType
    filename: str
    rows: List[ImportPreviewRow] = []
    options: ImportOptions = Field(default_factory=ImportOptions)


class ImportIngestResponse(BaseModel):
    success: bool = False
    indexed_count: int = 0
    total: int = 0
    errors: int = 0
    linked_entities: int = 0
    duplicate_count: int = 0
    deleted_count: int = 0
    duplicate_ids: List[str] = []
    message: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ContractAnalyticsRow(BaseModel):
    key: str
    count: int
    total_value: Optional[float] = None
    avg_value: Optional[float] = None
    description: Optional[str] = None


class ContractAnalyticsResponse(BaseModel):
    total_contracts: int = 0
    total_value: Optional[float] = None
    avg_value: Optional[float] = None
    max_value: Optional[float] = None
    # Cardinalidade distinta (exata) do universo filtrado.
    distinct_adjudicantes: int = 0
    distinct_adjudicatarios: int = 0
    distinct_cpv: int = 0
    by_year: List[ContractAnalyticsRow] = []
    by_month: List[ContractAnalyticsRow] = []
    value_distribution: List[ContractAnalyticsRow] = []
    top_entities: List[ContractAnalyticsRow] = []
    top_adjudicantes: List[ContractAnalyticsRow] = []
    top_adjudicatarios: List[ContractAnalyticsRow] = []
    top_cpv: List[ContractAnalyticsRow] = []
    procedure_types: List[ContractAnalyticsRow] = []
    contract_types: List[ContractAnalyticsRow] = []
    year: Optional[int] = None
    error: Optional[str] = None


class ContractRegionalRow(BaseModel):
    key: str
    count: int = 0
    total_value: Optional[float] = None


class ContractRegionalResponse(BaseModel):
    total_contracts: int = 0
    total_value: Optional[float] = None
    region_count: int = 0
    regions: List[ContractRegionalRow] = []
    error: Optional[str] = None


class ContractGraphResponse(BaseModel):
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    error: Optional[str] = None


class ContractGraphBuildResponse(BaseModel):
    """Grafo construído dinamicamente a partir de dimensões dos contratos."""

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    error: Optional[str] = None


class GraphDimensionOption(BaseModel):
    key: str
    label: str
    type: str


class GraphDimensionsResponse(BaseModel):
    dimensions: List[GraphDimensionOption] = []
    error: Optional[str] = None


# --- Preferências do utilizador: favoritos, pastas (dossier) e histórico ---

class FavoriteParty(BaseModel):
    nif: str
    label: str
    role: Optional[str] = None


class FavoriteItem(BaseModel):
    """Ficha guardada como favorita (entidade ou contrato)."""

    kind: Literal["entity", "contract"]
    id: str
    label: str
    sublabel: Optional[str] = None
    value: Optional[float] = None
    parties: List[FavoriteParty] = []


class FavoriteListResponse(BaseModel):
    items: List[Dict[str, Any]] = []
    total: int = 0
    error: Optional[str] = None


class FavoriteMutationResponse(BaseModel):
    ok: bool = False
    id: Optional[str] = None
    kind: Optional[str] = None
    deleted: Optional[int] = None
    error: Optional[str] = None


class WorkspaceFolder(BaseModel):
    id: str
    name: str
    createdAt: Optional[str] = None
    items: List[Dict[str, Any]] = []


class WorkspaceResponse(BaseModel):
    """Dossier: pastas de fichas e histórico de consultas."""

    folders: List[WorkspaceFolder] = []
    history: List[Dict[str, Any]] = []
    error: Optional[str] = None


class WorkspaceFolderRequest(BaseModel):
    id: str
    name: str = "Pasta"
    createdAt: Optional[str] = None
    items: List[Dict[str, Any]] = []


class WorkspaceHistoryRequest(BaseModel):
    items: List[Dict[str, Any]] = []


class ContractRelationsResponse(BaseModel):
    relations: List[Dict[str, Any]] = []
    error: Optional[str] = None


# --- Diretório de empresas (entidades) derivado de contratos ---

class CompanyRoleSummary(BaseModel):
    contracts_count: int = 0
    total_value: float = 0.0
    avg_value: Optional[float] = None
    first_year: Optional[int] = None
    last_year: Optional[int] = None


class CompanySummary(BaseModel):
    nif: Optional[str] = None
    name: str
    normalized_name: Optional[str] = None
    contracts_total: int = 0
    total_value: float = 0.0
    adjudicante: Optional[CompanyRoleSummary] = None
    adjudicatario: Optional[CompanyRoleSummary] = None


class CompanyDetail(CompanySummary):
    top_adjudicantes: List[ContractPartyParsed] = []
    top_adjudicatarios: List[ContractPartyParsed] = []
    recent_contracts: List[ContractItem] = []
    trademarks: List["TrademarkItem"] = []
    trademarks_total: int = 0
    firmas: List["FirmaItem"] = []
    firmas_total: int = 0
    societario_timeline: Optional[Dict[str, Any]] = None


class CompanySearchRequest(BaseModel):
    q: Optional[str] = Field(None, alias="query")
    role: Optional[Literal["all", "adjudicante", "adjudicatario"]] = "all"
    region: Optional[str] = None
    min_contracts: int = 1
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    year: Optional[int] = None
    size: int = 20
    from_: int = Field(0, alias="from")

    model_config = {"populate_by_name": True}


class CompanySearchResponse(BaseModel):
    query: Optional[str] = None
    total: int = 0
    items: List[CompanySummary] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    # NIF distintos encontrados pelos filtros (contagens reais de adjudicantes e
    # adjudicatários). `total` refere-se apenas à lista de entidades devolvida,
    # limitada aos NIF mais relevantes por papel.
    unique_adjudicantes: int = 0
    unique_adjudicatarios: int = 0
    error: Optional[str] = None


class CompanyContractsResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    total: int = 0
    items: List[ContractItem] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    error: Optional[str] = None


class CompanyAnalyticsRow(BaseModel):
    key: str
    count: int
    total_value: Optional[float] = None
    description: Optional[str] = None


class EntityRoleSummaryCounterparty(BaseModel):
    key: str
    count: int = 0
    total_value: Optional[float] = None
    description: Optional[str] = None


class EntityConcentration(BaseModel):
    top1: Optional[float] = None
    top5: Optional[float] = None
    top10: Optional[float] = None
    top25: Optional[float] = None
    covered_entities: int = 0


class EntityRoleSummaryRequest(CompanySearchRequest):
    """Filtros do dashboard de entidades (papel + janela temporal/geográfica)."""

    min_contracts: int = 1
    top_n: int = 25


class EntityRoleSummaryResponse(BaseModel):
    role: str = "all"
    query: Optional[str] = None
    year: Optional[int] = None
    region: Optional[str] = None
    total_contracts: int = 0
    total_value: float = 0.0
    avg_value: Optional[float] = None
    max_value: Optional[float] = None
    unique_entities: Optional[int] = None
    unique_adjudicantes: int = 0
    unique_adjudicatarios: int = 0
    avg_value_per_entity: Optional[float] = None
    top_entities: List[CompanySummary] = []
    counterparties: List[EntityRoleSummaryCounterparty] = []
    by_year: List[CompanyAnalyticsRow] = []
    by_region: List[CompanyAnalyticsRow] = []
    by_cpv: List[CompanyAnalyticsRow] = []
    by_procedure_type: List[CompanyAnalyticsRow] = []
    by_contract_type: List[CompanyAnalyticsRow] = []
    by_value_range: List[CompanyAnalyticsRow] = []
    concentration: Optional[EntityConcentration] = None
    error: Optional[str] = None


class CompanyAnalyticsResponse(BaseModel):
    company: CompanySummary
    total_contracts: int = 0
    total_value: Optional[float] = None
    avg_value: Optional[float] = None
    max_value: Optional[float] = None
    by_year: List[CompanyAnalyticsRow] = []
    by_month: List[CompanyAnalyticsRow] = []
    by_cpv: List[CompanyAnalyticsRow] = []
    top_partners: List[CompanyAnalyticsRow] = []
    by_procedure_type: List[CompanyAnalyticsRow] = []
    by_contract_type: List[CompanyAnalyticsRow] = []
    by_value_range: List[CompanyAnalyticsRow] = []
    year: Optional[int] = None
    error: Optional[str] = None


# --- Marcas do INPI (enriquecimento da ficha da empresa) ---

class TrademarkEntity(BaseModel):
    name: Optional[str] = None
    nif: Optional[str] = None
    role: Optional[str] = None


class TrademarkPhase(BaseModel):
    phase: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class TrademarkDocument(BaseModel):
    doc_id: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None


class TrademarkItem(BaseModel):
    nord: Optional[int] = None
    process_number: Optional[str] = None
    mark_name: Optional[str] = None
    mark_type: Optional[str] = None
    modality: Optional[str] = None
    holder_name: Optional[str] = None
    holder_nif: Optional[str] = None
    company_nif: Optional[str] = None
    application_date: Optional[str] = None
    current_phase: Optional[str] = None
    phase_start_date: Optional[str] = None
    phase_end_date: Optional[str] = None
    nice_classes: List[str] = []
    entities: List[TrademarkEntity] = []
    phases: List[TrademarkPhase] = []
    documents: List[TrademarkDocument] = []
    source_query: Optional[str] = None
    ingested_at: Optional[str] = None
    doc_id: Optional[str] = None
    score: Optional[float] = None
    holder_similarity: Optional[float] = None


class CompanyTrademarksResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    total: int = 0
    items: List[TrademarkItem] = []
    from_: int = Field(0, alias="from")
    size: int = 100
    error: Optional[str] = None


class TrademarkSearchRequest(BaseModel):
    q: Optional[str] = None
    holder_name: Optional[str] = None
    nice_class: Optional[str] = None
    mark_type: Optional[str] = None
    current_phase: Optional[str] = None
    size: int = 20
    from_: int = Field(0, alias="from")


class TrademarkSearchResponse(BaseModel):
    query: Optional[str] = None
    total: int = 0
    items: List[TrademarkItem] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    error: Optional[str] = None


class TrademarkIngestRequest(BaseModel):
    nif: Optional[str] = Field(None, description="NIF da empresa (para associar as marcas)")
    name: str = Field(..., description="Nome da empresa/titular a pesquisar no INPI")
    max_results: Optional[int] = Field(None, ge=1, le=200, description="Limite de marcas a obter")
    include_detail: bool = Field(True, description="Carregar o detalhe completo de cada marca")


class TrademarkIngestResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    fetched: int = 0
    indexed_count: int = 0
    errors: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


# --- Firmas / nomes comerciais RNPC (Pesquisa de Nomes Existentes) ---

class FirmaItem(BaseModel):
    nome: Optional[str] = None
    nipc: Optional[str] = None
    company_nif: Optional[str] = None
    numero_certificado: Optional[str] = None
    certificado_admissibilidade: Optional[str] = None
    concelho: Optional[str] = None
    concelho_sede: Optional[str] = None
    situacao: Optional[str] = None
    situacao_detalhe: Optional[str] = None
    cae_principal: Optional[str] = None
    score: Optional[float] = None
    search_query: Optional[str] = None
    source: Optional[str] = None
    ingested_at: Optional[str] = None
    doc_id: Optional[str] = None
    name_similarity: Optional[float] = None


class CompanyFirmasResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    total: int = 0
    items: List[FirmaItem] = []
    from_: int = Field(0, alias="from")
    size: int = 100
    error: Optional[str] = None


class FirmaSearchRequest(BaseModel):
    q: Optional[str] = None
    concelho: Optional[str] = None
    cae: Optional[str] = None
    situacao: Optional[str] = None
    min_score: Optional[float] = None
    size: int = 20
    from_: int = Field(0, alias="from")


class FirmaSearchResponse(BaseModel):
    query: Optional[str] = None
    total: int = 0
    items: List[FirmaItem] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    error: Optional[str] = None


class FirmaIngestRequest(BaseModel):
    name: str = Field(..., description="Nome/firma a pesquisar no Registo Nacional de Pessoas Colectivas")
    nif: Optional[str] = Field(None, description="NIF da empresa na nossa base (associação)")
    cae: Optional[str] = Field(None, description="Filtrar por C.A.E. (opcional)")
    concelho: Optional[str] = Field(None, description="Código de concelho do serviço (opcional)")
    max_results: Optional[int] = Field(None, ge=1, le=20, description="Limite de firmas (máx. 20)")
    include_detail: bool = Field(True, description="Carregar ficha de detalhe (CAE, concelho da sede)")


class FirmaIngestResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    fetched: int = 0
    indexed_count: int = 0
    errors: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


class CompanyEnrichmentResponse(BaseModel):
    """Resultado combinado do enriquecimento de uma empresa (marcas INPI + firmas RNPC)."""

    nif: Optional[str] = None
    name: Optional[str] = None
    trademarks: Optional[TrademarkIngestResponse] = None
    firmas: Optional[FirmaIngestResponse] = None
    error: Optional[str] = None


# --- Cadastro de entidades do portal base (finance_entities) ---

class EntityItem(BaseModel):
    nif: Optional[str] = None
    name: str
    country: Optional[str] = None
    country_code: Optional[str] = None
    has_nif: bool = False
    contracts_count: int = 0
    as_adjudicante_count: int = 0
    as_adjudicatario_count: int = 0
    total_value: float = 0.0
    as_adjudicante_value: float = 0.0
    source: Optional[str] = None
    ingested_at: Optional[str] = None
    doc_id: Optional[str] = None


class EntityDetailResponse(EntityItem):
    """Ficha da entidade com o enriquecimento já guardado (marcas INPI + firmas RNPC)."""

    trademarks: List["TrademarkItem"] = []
    trademarks_total: int = 0
    firmas: List["FirmaItem"] = []
    firmas_total: int = 0
    error: Optional[str] = None


class EntitySearchRequest(BaseModel):
    q: Optional[str] = Field(None, alias="query")
    country: Optional[str] = None
    only_with_nif: Optional[bool] = None
    min_contracts: Optional[int] = None
    max_contracts: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    role: Optional[Literal["all", "adjudicante", "adjudicatario"]] = "all"
    sort_by: Optional[Literal[
        "name", "contracts_count", "total_value",
        "as_adjudicante_value", "as_adjudicante_count", "as_adjudicatario_count",
    ]] = "total_value"
    sort_order: Optional[Literal["asc", "desc"]] = "desc"
    size: int = 20
    from_: int = Field(0, alias="from")

    model_config = {"populate_by_name": True}


class EntitySearchResponse(BaseModel):
    query: Optional[str] = None
    total: int = 0
    items: List[EntityItem] = []
    from_: int = Field(0, alias="from")
    size: int = 20
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


class EntityCountryStat(BaseModel):
    country: str
    count: int = 0
    total_value: float = 0.0


class EntityStatsResponse(BaseModel):
    total: int = 0
    with_nif: int = 0
    without_nif: int = 0
    total_value: float = 0.0
    total_contracts: int = 0
    adjudicante_count: int = 0
    adjudicatario_count: int = 0
    countries: List[EntityCountryStat] = []
    error: Optional[str] = None


class EntityIngestRequest(BaseModel):
    path: Optional[str] = Field(None, description="Caminho alternativo do entidades.json")
    max_records: Optional[int] = Field(None, ge=1, description="Limite de registos a indexar")
    chunk_size: int = Field(2000, ge=100, le=10000, description="Tamanho dos lotes de indexação")
    refresh: bool = Field(True, description="Refrescar o índice no fim para leitura imediata")


class EntityIngestResponse(BaseModel):
    indexed_count: int = 0
    total: int = 0
    errors: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


# Resolver as referências antecipadas usadas em CompanyDetail / EntityDetailResponse.
CompanyDetail.model_rebuild()
EntityDetailResponse.model_rebuild()
