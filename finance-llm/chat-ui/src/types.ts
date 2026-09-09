export type Role = "user" | "assistant" | "system";

export interface Message {
  id: string;
  role: Role;
  content: string;
  timestamp: string;
  sources?: Source[];
  tools?: ToolCall[];
}

export interface Source {
  name: string;
  url?: string;
  value?: string;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  output?: string;
}

export type ModelBackend = "gpt2" | "mistral" | "bloomberg";

export interface RagDocument {
  doc_id: string;
  title: string;
  filename: string;
  pages: number;
  indexed: boolean;
  size_bytes?: number;
  created_at?: number;
  updated_at?: number;
  converter?: "auto" | "markitdown" | "pymupdf";
}

export interface RagDocumentUpdate {
  title: string;
}

export interface RagDocumentHistoryItem {
  action: string;
  detail: string;
  timestamp: number;
}

export interface RagDocumentHistoryResponse {
  doc_id: string;
  history: RagDocumentHistoryItem[];
}

export interface RagSource {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  page?: number;
  text: string;
  score?: number;
}

export interface RagChatRequest {
  question: string;
  top_k?: number;
  max_new_tokens?: number;
  temperature?: number;
  doc_id?: string;
  stream?: boolean;
}

export interface RagChatResponse {
  answer: string;
  sources: RagSource[];
  model_used?: string;
  elapsed_seconds?: number;
}

export interface RagExplainResponse {
  question: string;
  answer_preview: string;
  model_used?: string;
  documents_used: string[];
  pages_used: number[];
  retrieval_scores: number[];
  analysis: string;
}

export interface RagDocumentGraphNode {
  id: string;
  doc_id: string;
  page?: number;
  text_preview: string;
  section?: string;
  chunk_index: number;
}

export interface RagDocumentGraphEdge {
  source: string;
  target: string;
  weight: number;
}

export interface RagDocumentGraphResponse {
  doc_id: string;
  title: string;
  nodes: RagDocumentGraphNode[];
  edges: RagDocumentGraphEdge[];
}

export interface UploadPdfResponse {
  doc_id: string;
  title: string;
  filename: string;
  pages: number;
  indexed: boolean;
  message: string;
}

export interface ChatRequest {
  messages: { role: Role; content: string; timestamp?: string }[];
  model?: string;
  backend?: ModelBackend;
  stream?: boolean;
}

export interface ChatResponse {
  message: {
    role: Role;
    content: string;
    timestamp?: string;
  };
  sources: Source[];
  tools: ToolCall[];
}

export interface YahooSearchResult {
  symbol: string;
  name?: string;
  exchange?: string;
  quote_type?: string;
  sector?: string;
  industry?: string;
}

export interface TickerSearchResponse {
  query: string;
  tickers: string[];
  yahoo_results: YahooSearchResult[];
}

export interface TickerInfo {
  ticker: string;
  name?: string;
  currency?: string;
  price?: number;
  market_cap?: number;
  pe?: number;
  eps?: number;
  dividend_yield?: number;
  roe?: number;
  sector?: string;
  industry?: string;
  website?: string;
  country?: string;
  employees?: number;
  summary?: string;
  exchange?: string;
  quote_type?: string;
  beta?: number;
  target_mean_price?: number;
  target_high_price?: number;
  target_low_price?: number;
  recommendation?: string;
  recommendation_mean?: number;
  number_of_analysts?: number;
  kpis?: Record<string, number>;
}

export interface HistoryPoint {
  date: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
}

export interface TickerHistory {
  ticker: string;
  period: string;
  points: HistoryPoint[];
}

export interface Financials {
  ticker: string;
  income_statement: Record<string, Record<string, number>>;
  balance_sheet: Record<string, Record<string, number>>;
  cash_flow: Record<string, Record<string, number>>;
  quarterly_income_statement?: Record<string, Record<string, number>>;
  quarterly_balance_sheet?: Record<string, Record<string, number>>;
  quarterly_cash_flow?: Record<string, Record<string, number>>;
}

export interface Holders {
  ticker: string;
  institutional: Record<string, unknown>;
  mutual_fund: Record<string, unknown>;
  major: Record<string, unknown>;
  insider_transactions: Record<string, unknown>;
  insider_purchases: Record<string, unknown>;
  error?: string;
}

export interface Sustainability {
  ticker: string;
  esg: Record<string, unknown>;
  error?: string;
}

export interface Recommendations {
  ticker: string;
  recommendations: Record<string, unknown>;
  recommendations_summary: Record<string, unknown>;
  upgrades_downgrades: Record<string, unknown>;
  error?: string;
}

export interface Calendar {
  ticker: string;
  calendar: Record<string, unknown>;
  earnings_dates: Record<string, unknown>;
  error?: string;
}

export interface NewsItem {
  title?: string;
  publisher?: string;
  published?: string;
  url?: string;
  summary?: string;
}

export interface News {
  ticker: string;
  news: NewsItem[];
  error?: string;
}

export interface ElasticStatus {
  available: boolean;
  version?: string;
  cluster_name?: string;
  message: string;
}

export interface ElasticIngestRequest {
  period?: string;
  interval?: string;
}

export interface ElasticIngestPricesResponse {
  ticker: string;
  indexed_count: number;
  total_points: number;
  period: string;
  interval: string;
  message?: string;
  error?: string;
}

export interface ElasticIngestNewsResponse {
  ticker: string;
  indexed_count: number;
  total_items: number;
  message?: string;
  error?: string;
}

export interface ElasticSearchPoint {
  ticker: string;
  date: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  period?: string;
  ingested_at?: string;
}

export interface ElasticSearchPricesResponse {
  ticker: string;
  total: number;
  points: ElasticSearchPoint[];
  start_date?: string;
  end_date?: string;
  error?: string;
}

export interface ElasticSearchNewsItem {
  ticker: string;
  title?: string;
  summary?: string;
  publisher?: string;
  published?: string;
  url?: string;
  source?: string;
  ingested_at?: string;
}

export interface ElasticSearchNewsResponse {
  ticker: string;
  total: number;
  items: ElasticSearchNewsItem[];
  query?: string;
  error?: string;
}

export interface ElasticTickerListResponse {
  tickers: string[];
}

export interface ElasticDeleteResponse {
  ticker: string;
  prices_deleted?: number;
  news_deleted?: number;
  error?: string;
}

export interface Options {
  ticker: string;
  expiration_dates: string[];
  chains: Record<string, unknown>[];
  error?: string;
}

export interface Actions {
  ticker: string;
  actions: Record<string, unknown>;
  splits: Record<string, unknown>;
  dividends: Record<string, unknown>;
  error?: string;
}

export interface TechnicalPoint {
  date: string;
  price?: number;
  volume?: number;
  sma20?: number;
  sma50?: number;
  sma200?: number;
  ema12?: number;
  ema26?: number;
  rsi14?: number;
  macd?: number;
  macd_signal?: number;
  macd_histogram?: number;
  bb_upper?: number;
  bb_middle?: number;
  bb_lower?: number;
  atr14?: number;
  obv?: number;
}

export interface TechnicalAnalysis {
  ticker: string;
  period: string;
  points: TechnicalPoint[];
  error?: string;
}

export interface TechnicalExplanation {
  ticker: string;
  period: string;
  summary: string;
  price_trend: string;
  sma_analysis: string;
  rsi_analysis: string;
  macd_analysis: string;
  bb_analysis: string;
  atr_analysis: string;
  obv_analysis: string;
  combined_signal: string;
  error?: string;
}

export interface SecFiling {
  date: string;
  type: string;
  title: string;
  url?: string;
}

export interface SecFilingsResponse {
  ticker: string;
  filings: SecFiling[];
  error?: string;
}

export interface AddTickerRequest {
  ticker: string;
}

export interface AddTickerResponse {
  ticker: string;
  added: boolean;
  message: string;
}

export interface ForecastRequest {
  ticker: string;
  future_days?: number;
  period?: string;
  order?: string;
  train_ratio?: number;
}

export interface ForecastPoint {
  date: string;
  price: number;
  lower?: number;
  upper?: number;
}

export interface ForecastSeries {
  date: string;
  value: number;
  type: string;
}

export interface ForecastResponse {
  ticker: string;
  order: [number, number, number];
  train_days: number;
  test_days: number;
  rmse: number;
  mape: number;
  ljung_box_pvalue?: number;
  last_train_date: string;
  last_test_date: string;
  currency: string;
  company_name?: string;
  forecast: ForecastPoint[];
  series: ForecastSeries[];
  plot_url?: string;
  plot_path?: string;
  model_summary?: string;
  explanation?: string;
}
