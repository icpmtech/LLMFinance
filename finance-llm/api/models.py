"""Esquemas Pydantic para a API FinanceLLM Chat."""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any


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


class ChatResponse(BaseModel):
    message: ChatMessage
    sources: List[Source] = []
    tools: List[ToolCall] = []
    chart: Optional[dict] = None


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


class RagChatRequest(BaseModel):
    question: str
    top_k: int = 5
    max_new_tokens: int = 64
    temperature: float = 0.1
    doc_id: Optional[str] = None
    stream: bool = False


class RagChatResponse(BaseModel):
    answer: str
    sources: List[RagSource] = []
    model_used: Optional[str] = None


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
    cpv_code: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    size: int = 20
    from_: int = Field(0, alias="from")


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
