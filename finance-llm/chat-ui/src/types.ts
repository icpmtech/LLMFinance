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
  ticker?: string;
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

export interface NewsEntity {
  name: string;
  type: string;
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
  analyzed_at?: string;
  sentiment?: string;
  language?: string;
  translated_title?: string;
  translated_summary?: string;
  summary_pt?: string;
  topics?: string[];
  entities?: NewsEntity[];
}

export interface ElasticSearchNewsResponse {
  ticker: string;
  total: number;
  items: ElasticSearchNewsItem[];
  query?: string;
  error?: string;
}

export interface ElasticSearchGlobalItem {
  ticker: string;
  title?: string;
  summary?: string;
  publisher?: string;
  published?: string;
  url?: string;
  source?: string;
  score?: number;
  sentiment?: string;
  topics?: string[];
}

export interface ElasticSearchGlobalResponse {
  query: string;
  total: number;
  items: ElasticSearchGlobalItem[];
  error?: string;
}

export type ElasticSuggestionType = "ticker" | "title" | "publisher" | "topic";

export interface ElasticSuggestion {
  text: string;
  type: ElasticSuggestionType;
  ticker?: string;
  count?: number;
}

export interface ElasticAutocompleteResponse {
  query: string;
  suggestions: ElasticSuggestion[];
  error?: string;
}

export interface ElasticAnalyzeNewsResponse {
  ticker: string;
  analyzed_count: number;
  total_items: number;
  errors?: number;
  message?: string;
  error?: string;
}

export interface NewsGraphEdge {
  source: string;
  target: string;
  weight?: number;
}

export interface NewsGraphNode {
  id: string;
  type: "noticia" | "entidade" | string;
  label: string;
  entity_type?: string;
  ticker?: string;
  sentiment?: string;
  published?: string;
  url?: string;
}

export interface ElasticNewsGraphResponse {
  ticker: string;
  graph_type: string;
  node_count: number;
  edge_count: number;
  nodes: NewsGraphNode[];
  edges: NewsGraphEdge[];
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
  backend?: "arima" | "kronos";
  use_sentiment?: boolean;
  include_features?: boolean;
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

export interface ForecastSignal {
  sentiment_signal: number;
  macro_signal: number;
  earnings_signal: number;
  blended_signal: number;
  weights: Record<string, number>;
}

export interface SentimentBlendedResponse {
  ticker: string;
  base_model: string;
  period: string;
  future_days: number;
  base_forecast: ForecastPoint[];
  adjusted_forecast: ForecastPoint[];
  signals: ForecastSignal;
  features: Record<string, unknown>;
  error?: string;
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

// --- Contratos públicos ---

export interface ContractPartyParsed {
  nif?: string;
  nome?: string;
}

export interface ContractParty {
  raw?: string;
  parsed: ContractPartyParsed[];
}

export interface ContractCpv {
  code?: string;
  description?: string;
}

export interface ContractEntity {
  name?: string;
  type?: string;
  nif?: string;
  code?: string;
}

export interface ContractItem {
  idcontrato?: string;
  nAnuncio?: string;
  TipoAnuncio?: string;
  idprocedimento?: string;
  tipoContrato?: string;
  tipoprocedimento?: string;
  objectoContrato?: string;
  descContrato?: string;
  adjudicantes?: ContractParty | ContractParty[];
  adjudicatarios?: ContractParty | ContractParty[];
  dataPublicacao?: string;
  dataCelebracaoContrato?: string;
  precoContratual?: number;
  PrecoTotalEfetivo?: number;
  precoBaseProcedimento?: number;
  cpv: ContractCpv[];
  localExecucao?: string;
  Ano?: number;
  NUTs?: string;
  regime?: string;
  concorrentes?: string | string[];
  search_text?: string;
  entities: ContractEntity[];
  score?: number;
  doc_id?: string;
}

export interface ContractSearchRequest {
  q?: string;
  year?: number;
  entity?: string;
  nif?: string;
  counterparty_nif?: string;
  region?: string;
  cpv_code?: string;
  min_price?: number;
  max_price?: number;
  start_date?: string;
  end_date?: string;
  size?: number;
  from?: number;
  sort_by?: "relevance" | "dataPublicacao" | "dataCelebracaoContrato" | "precoContratual" | "objectoContrato" | "tipoContrato" | "adjudicantes" | "adjudicatarios";
  sort_order?: "asc" | "desc";
}

export interface ContractAnalyticsFilters {
  q?: string;
  year?: number;
  entity?: string;
  nif?: string;
  cpv_code?: string;
  min_price?: number;
  max_price?: number;
  start_date?: string;
  end_date?: string;
  top_entities?: number;
  top_cpv?: number;
}

export interface ContractSearchResponse {
  query?: string;
  total: number;
  items: ContractItem[];
  from: number;
  size: number;
  error?: string;
}

export interface ContractStatusResponse {
  total: number;
  years: number[];
  error?: string;
}

export interface ContractYearInfo {
  year: number;
  count: number;
}

export interface ContractYearsResponse {
  available: number[];
  indexed: ContractYearInfo[];
  error?: string;
}

export interface ContractIngestRequest {
  year?: number;
  max_records?: number;
  chunk_size?: number;
}

export interface ContractIngestResponse {
  indexed_count: number;
  total: number;
  errors?: number;
  message?: string;
  error?: string;
}

export interface ContractAutocompleteSuggestion {
  text: string;
  type: "entity" | "cpv" | string;
  count?: number;
}

export interface ContractAutocompleteResponse {
  query?: string;
  suggestions: ContractAutocompleteSuggestion[];
  error?: string;
}

export interface ContractChatRequest {
  question: string;
  top_k?: number;
  max_new_tokens?: number;
  temperature?: number;
}

export interface ContractChatSource {
  idcontrato?: string;
  objectoContrato?: string;
  adjudicante?: string;
  adjudicatario?: string;
  precoContratual?: number;
  score?: number;
}

export interface ContractChatResponse {
  answer: string;
  sources: ContractChatSource[];
  model_used?: string;
  error?: string;
}

export interface ContractAnalyzeRequest {
  question?: string;
  model?: string;
  max_tokens?: number;
  temperature?: number;
  use_web_search?: boolean;
  use_related_contracts?: boolean;
}

export interface ContractAnalyzeSource {
  title?: string;
  url?: string;
  snippet?: string;
}

export interface ContractAnalyzeResponse {
  analysis: string;
  sources?: ContractAnalyzeSource[];
  model_used?: string;
  error?: string;
}

export interface ContractAnalyticsRow {
  key: string;
  count: number;
  total_value?: number;
  description?: string;
}

export interface ContractAnalyticsResponse {
  total_contracts: number;
  total_value?: number;
  avg_value?: number;
  max_value?: number;
  by_year: ContractAnalyticsRow[];
  by_month: ContractAnalyticsRow[];
  value_distribution: ContractAnalyticsRow[];
  top_entities: ContractAnalyticsRow[];
  top_cpv: ContractAnalyticsRow[];
  procedure_types: ContractAnalyticsRow[];
  contract_types: ContractAnalyticsRow[];
  year?: number;
  error?: string;
}

export interface ContractRegionalRow {
  key: string;
  count: number;
  total_value?: number;
}

export interface ContractRegionalResponse {
  total_contracts: number;
  total_value?: number;
  regions: ContractRegionalRow[];
  error?: string;
}

export interface ContractGraphResponse {
  nodes: { id: string; label: string; type: string; count?: number; total_value?: number; contract_id?: string }[];
  edges: { source: string; target: string; count: number; value: number }[];
  error?: string;
}

export interface ContractRelation {
  source: string;
  source_name: string;
  target: string;
  target_name: string;
  count: number;
  total_value: number;
}

export interface ContractRelationsResponse {
  relations: ContractRelation[];
  error?: string;
}

export interface CompanyRoleSummary {
  contracts_count: number;
  total_value: number;
  avg_value?: number;
  first_year?: number;
  last_year?: number;
}

export interface CompanySummary {
  nif?: string;
  name: string;
  normalized_name?: string;
  contracts_total: number;
  total_value: number;
  adjudicante?: CompanyRoleSummary;
  adjudicatario?: CompanyRoleSummary;
}

export interface CompanyDetail extends CompanySummary {
  top_adjudicantes: ContractPartyParsed[];
  top_adjudicatarios: ContractPartyParsed[];
  recent_contracts: ContractItem[];
}

export interface CompanySearchRequest {
  q?: string;
  role?: "all" | "adjudicante" | "adjudicatario";
  region?: string;
  min_contracts?: number;
  min_value?: number;
  max_value?: number;
  year?: number;
  size?: number;
  from?: number;
}

export interface CompanySearchResponse {
  query?: string;
  total: number;
  items: CompanySummary[];
  from: number;
  size: number;
  error?: string;
}

export interface CompanyContractsResponse {
  nif?: string;
  name?: string;
  role?: string;
  total: number;
  items: ContractItem[];
  from: number;
  size: number;
  error?: string;
}

export interface CompanyAnalyticsResponse {
  company: CompanySummary;
  total_contracts: number;
  total_value?: number;
  avg_value?: number;
  max_value?: number;
  by_year: ContractAnalyticsRow[];
  by_month: ContractAnalyticsRow[];
  by_cpv: ContractAnalyticsRow[];
  top_partners: ContractAnalyticsRow[];
  by_procedure_type: ContractAnalyticsRow[];
  by_contract_type: ContractAnalyticsRow[];
  by_value_range: ContractAnalyticsRow[];
  year?: number;
  error?: string;
}

// --- Importação de entidades e contratos ---

export type ImportFileType = "zip" | "xlsx" | "json";
export type ImportDataType = "contracts" | "entities" | "auto";

export interface ImportPreviewRow {
  id?: string;
  name?: string;
  nif?: string;
  objectoContrato?: string;
  precoContratual?: number;
  dataCelebracaoContrato?: string;
  adjudicante?: string;
  adjudicatario?: string;
  raw: Record<string, unknown>;
}

export interface ImportPreviewResponse {
  data_type: ImportDataType;
  file_type: ImportFileType;
  filename: string;
  rows: ImportPreviewRow[];
  total_rows: number;
  sample_schema: string[];
  errors: string[];
  warnings: string[];
}

export interface ImportIngestRequest {
  data_type: ImportDataType;
  file_type: ImportFileType;
  filename: string;
  rows?: ImportPreviewRow[];
  options?: {
    link_entities?: boolean;
    max_records?: number;
    skip_validation?: boolean;
    hard_reprocess?: boolean;
  };
}

export interface ImportIngestResponse {
  success: boolean;
  indexed_count: number;
  total: number;
  errors: number;
  linked_entities: number;
  duplicate_count?: number;
  deleted_count?: number;
  duplicate_ids?: string[];
  message?: string;
  error?: string;
  details?: Record<string, number | string>;
}

export interface ImportStatusResponse {
  ready: boolean;
  data_type?: ImportDataType;
  filename?: string;
  stage?: "parsing" | "normalizing" | "indexing" | "linking" | "done" | "error";
  progress?: number;
  message?: string;
  error?: string;
}
