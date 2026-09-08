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


class ForecastPoint(BaseModel):
    date: str
    price: float
    lower: Optional[float] = None
    upper: Optional[float] = None


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


class RagExplainResponse(BaseModel):
    question: str
    answer_preview: str
    model_used: Optional[str] = None
    documents_used: List[str] = []
    pages_used: List[int] = []
    retrieval_scores: List[float] = []
    analysis: str
