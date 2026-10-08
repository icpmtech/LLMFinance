export const API_BASE =
  (typeof window !== "undefined" && window.location.hostname === "localhost" && window.location.port === "4180"
    ? "/api"
    : import.meta.env.VITE_API_URL) || "http://127.0.0.1:8002";

import type {
  Actions,
  AddTickerRequest,
  AddTickerResponse,
  Calendar,
  CompanyAnalyticsResponse,
  CompanyContractsResponse,
  CompanyDetail,
  CompanySearchRequest,
  CompanySearchResponse,
  ContractAutocompleteResponse,
  ContractAnalyzeRequest,
  ContractAnalyzeResponse,
  ContractDocumentResponse,
  ContractIngestRequest,
  ContractIngestResponse,
  ContractSearchRequest,
  ContractSearchResponse,
  ContractStatusResponse,
  ContractYearsResponse,
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
  ElasticStatus,
  ElasticTickerListResponse,
  ElasticIndicesListResponse,
  CompanyEnrichmentResponse,
  EntityDetail,
  EntityIngestRequest,
  EntityIngestResponse,
  EntitySearchRequest,
  EntitySearchResponse,
  EntityEnrichmentResponse,
  EntityRelationsResponse,
  EntityRoleSummaryRequest,
  EntityRoleSummaryResponse,
  EntityStats,
  Financials,
  FirmaSearchResponse,
  Holders,
  News,
  Options,
  Recommendations,
  SecFilingsResponse,
  Sustainability,
  TechnicalAnalysis,
  TechnicalExplanation,
  TickerHistory,
  TickerInfo,
  TickerSearchResponse,
  TrademarkSearchResponse,
  ForecastRequest,
  ForecastResponse,
  SentimentBlendedResponse,
  RagChatRequest,
  RagChatResponse,
  RagDocument,
  RagDocumentGraphResponse,
  RagDocumentHistoryResponse,
  RagDocumentUpdate,
  RagExplainResponse,
  RagSource,
  SkillRef,
  UploadPdfResponse,
  ContractAnalyticsResponse,
  ContractAnalyticsFilters,
  ContractChatRequest,
  ContractChatResponse,
  ContractGraphRequest,
  ContractGraphBuildResponse,
  ContractGraphResponse,
  ContractRegionalResponse,
  ContractRelationsResponse,
  CompanySocietarioResponse,
  SocietarioCompanyPeopleResponse,
  ContractItem,
  GraphDimensionsResponse,
  PeopleSearchResponse,
  PeopleAutocompleteItem,
  PeopleFiltersResponse,
  PeopleFacet,
  Person,
  PeopleGraphResponse,
  PeopleIngestResponse,
  PeoplePresenceResponse,
  PeopleCireIngestRequest,
  PeopleCireIngestResult,
  PeopleCireJobResponse,
  PeopleSocialCollectResponse,
  PeopleSocialResponse,
  People360Response,
  PoliticianProfile,
  NodeSummaryResponse,
  ImportFileType,
  ImportDataType,
  ImportPreviewRow,
  ImportPreviewResponse,
  ImportIngestRequest,
  ImportIngestResponse,
  ImportStatusResponse,
  TranslateRequest,
  TranslateResponse,
  TickerTranslationResponse,
} from "./types";

export type { ContractAnalyticsResponse, ContractAnalyticsFilters, CompanySearchResponse, CompanyDetail, CompanyContractsResponse, CompanyAnalyticsResponse };
export type { ImportFileType, ImportDataType, ImportPreviewRow, ImportPreviewResponse, ImportIngestRequest, ImportIngestResponse, ImportStatusResponse };
export type { PeopleSearchResponse, Person, PeopleGraphResponse, PeopleIngestResponse, PeoplePresenceResponse };
export type { PeopleAutocompleteItem, PeopleFiltersResponse, PeopleFacet };
export type { PeopleCireIngestRequest, PeopleCireIngestResult, PeopleCireJobResponse };
export type { PeopleSocialCollectResponse, PeopleSocialResponse, People360Response, PoliticianProfile };
export type { NodeSummaryResponse };

export function getPlotUrl(plot_url: string): string {
  if (plot_url.startsWith("http://") || plot_url.startsWith("https://")) {
    return plot_url;
  }
  if (plot_url.startsWith("/")) {
    return `${API_BASE}${plot_url}`;
  }
  return `${API_BASE}/forecast/plot/${encodeURIComponent(plot_url)}`;
}


export async function searchLocalTickers(query: string): Promise<string[]> {
  const res = await fetch(
    `${API_BASE}/tickers?${new URLSearchParams({ query: query.trim() })}`,
  );
  if (!res.ok) throw new Error(`Erro ao procurar tickers: ${res.status}`);
  const data: TickerSearchResponse = await res.json();
  return data.tickers ?? [];
}

export async function searchYahooTickers(query: string): Promise<TickerSearchResponse> {
  const res = await fetch(
    `${API_BASE}/tickers/search/yahoo?${new URLSearchParams({ query: query.trim() })}`,
  );
  if (!res.ok) throw new Error(`Erro na pesquisa Yahoo: ${res.status}`);
  return res.json();
}

export async function getTickerInfo(ticker: string): Promise<TickerInfo> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/info`);
  if (!res.ok) throw new Error(`Erro ao obter info: ${res.status}`);
  return res.json();
}

export async function getTickerHistory(ticker: string, period = "1y"): Promise<TickerHistory> {
  const res = await fetch(
    `${API_BASE}/tickers/${encodeURIComponent(ticker)}/history?period=${period}`,
  );
  if (!res.ok) throw new Error(`Erro ao obter histórico: ${res.status}`);
  return res.json();
}

export async function getTickerFinancials(ticker: string): Promise<Financials> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/financials`);
  if (!res.ok) throw new Error(`Erro ao obter financials: ${res.status}`);
  return res.json();
}

export async function getTickerSecFilings(ticker: string, days = 365): Promise<SecFilingsResponse> {
  const res = await fetch(
    `${API_BASE}/tickers/${encodeURIComponent(ticker)}/sec-filings?days=${days}`,
  );
  if (!res.ok) throw new Error(`Erro ao obter SEC filings: ${res.status}`);
  return res.json();
}

export async function getTickerHolders(ticker: string): Promise<Holders> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/holders`);
  if (!res.ok) throw new Error(`Erro ao obter holders: ${res.status}`);
  return res.json();
}

export async function getTickerSustainability(ticker: string): Promise<Sustainability> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/sustainability`);
  if (!res.ok) throw new Error(`Erro ao obter sustentabilidade: ${res.status}`);
  return res.json();
}

export async function getTickerRecommendations(ticker: string): Promise<Recommendations> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/recommendations`);
  if (!res.ok) throw new Error(`Erro ao obter recomendações: ${res.status}`);
  return res.json();
}

export async function getTickerCalendar(ticker: string): Promise<Calendar> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/calendar`);
  if (!res.ok) throw new Error(`Erro ao obter calendário: ${res.status}`);
  return res.json();
}

export async function getTickerNews(ticker: string, maxItems = 10): Promise<News> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/news?max_items=${maxItems}`);
  if (!res.ok) throw new Error(`Erro ao obter notícias: ${res.status}`);
  return res.json();
}

export async function getTickerOptions(ticker: string): Promise<Options> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/options`);
  if (!res.ok) throw new Error(`Erro ao obter opções: ${res.status}`);
  return res.json();
}

export async function getElasticStatus(): Promise<ElasticStatus> {
  const res = await fetch(`${API_BASE}/elastic/status`);
  if (!res.ok) throw new Error(`Erro ao obter estado Elasticsearch: ${res.status}`);
  return res.json();
}

export async function ingestElasticPrices(
  ticker: string,
  period = "1y",
  interval = "1d",
): Promise<ElasticIngestPricesResponse> {
  const params = new URLSearchParams({ period, interval });
  const res = await fetch(
    `${API_BASE}/elastic/ingest/prices/${encodeURIComponent(ticker)}?${params}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar preços: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function ingestElasticNews(ticker: string): Promise<ElasticIngestNewsResponse> {
  const res = await fetch(
    `${API_BASE}/elastic/ingest/news/${encodeURIComponent(ticker)}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar notícias: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function ingestElasticTicker(
  ticker: string,
  request: ElasticIngestRequest,
): Promise<{ ticker: string; prices: ElasticIngestPricesResponse; news: ElasticIngestNewsResponse }> {
  const res = await fetch(`${API_BASE}/elastic/ingest/${encodeURIComponent(ticker)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar ticker: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function searchElasticPrices(
  ticker: string,
  startDate?: string,
  endDate?: string,
  size = 1000,
): Promise<ElasticSearchPricesResponse> {
  const params = new URLSearchParams();
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  params.append("size", String(size));
  const res = await fetch(
    `${API_BASE}/elastic/search/prices/${encodeURIComponent(ticker)}?${params}`,
  );
  if (!res.ok) throw new Error(`Erro ao pesquisar preços: ${res.status}`);
  return res.json();
}

export async function searchElasticNews(
  ticker: string,
  q?: string,
  startDate?: string,
  endDate?: string,
  size = 50,
): Promise<ElasticSearchNewsResponse> {
  const params = new URLSearchParams();
  if (q) params.append("q", q);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  params.append("size", String(size));
  const res = await fetch(
    `${API_BASE}/elastic/search/news/${encodeURIComponent(ticker)}?${params}`,
  );
  if (!res.ok) throw new Error(`Erro ao pesquisar notícias: ${res.status}`);
  return res.json();
}

export async function searchElasticGlobal(
  q: string,
  options: { from?: number; size?: number; source?: string; sentiment?: string; topic?: string } = {},
): Promise<ElasticSearchGlobalResponse> {
  const params = new URLSearchParams({ q: q.trim() });
  if (options.from !== undefined) params.append("from", String(options.from));
  if (options.size !== undefined) params.append("size", String(options.size));
  if (options.source) params.append("source", options.source);
  if (options.sentiment) params.append("sentiment", options.sentiment);
  if (options.topic) params.append("topic", options.topic);
  const res = await fetch(`${API_BASE}/elastic/search/global?${params}`);
  if (!res.ok) throw new Error(`Erro na pesquisa global: ${res.status}`);
  return res.json();
}

export async function searchTrademarks(
  q: string = "",
  options: { holder_name?: string; nice_class?: string; mark_type?: string; current_phase?: string; size?: number; from?: number } = {},
): Promise<TrademarkSearchResponse> {
  const params = new URLSearchParams();
  if (q.trim()) params.append("q", q.trim());
  if (options.holder_name) params.append("holder_name", options.holder_name);
  if (options.nice_class) params.append("nice_class", options.nice_class);
  if (options.mark_type) params.append("mark_type", options.mark_type);
  if (options.current_phase) params.append("current_phase", options.current_phase);
  params.append("size", String(options.size ?? 50));
  if (options.from !== undefined) params.append("from", String(options.from));
  const res = await fetch(`${API_BASE}/trademarks/search?${params}`);
  if (!res.ok) throw new Error(`Erro ao pesquisar marcas: ${res.status}`);
  return res.json();
}

export async function searchFirmas(
  q: string = "",
  options: { concelho?: string; cae?: string; situacao?: string; size?: number; from?: number } = {},
): Promise<FirmaSearchResponse> {
  const params = new URLSearchParams();
  if (q.trim()) params.append("q", q.trim());
  if (options.concelho) params.append("concelho", options.concelho);
  if (options.cae) params.append("cae", options.cae);
  if (options.situacao) params.append("situacao", options.situacao);
  params.append("size", String(options.size ?? 50));
  if (options.from !== undefined) params.append("from", String(options.from));
  const res = await fetch(`${API_BASE}/firmas/search?${params}`);
  if (!res.ok) throw new Error(`Erro ao pesquisar firmas: ${res.status}`);
  return res.json();
}

export async function searchScrapedItems(
  q: string = "",
  options: { source_id?: string; size?: number; offset?: number; sort?: "recent" | "oldest" | "relevance" } = {},
): Promise<{ total: number; items: any[]; query?: string; error?: string }> {
  const params = new URLSearchParams();
  if (q.trim()) params.append("q", q.trim());
  if (options.source_id) params.append("source_id", options.source_id);
  params.append("size", String(options.size ?? 30));
  params.append("offset", String(options.offset ?? 0));
  params.append("sort", options.sort ?? (q.trim() ? "relevance" : "recent"));
  const res = await fetch(`${API_BASE}/scraper/search?${params}`);
  if (!res.ok) throw new Error(`Erro ao pesquisar recolhas: ${res.status}`);
  return res.json();
}

type CrmRecord = {
  id: string;
  kind: string;
  name?: string;
  company_name?: string;
  title?: string;
  stage?: string;
  value?: number;
  updated_at?: string;
  created_at?: string;
  [key: string]: unknown;
};

export async function searchCrmRecords(
  kind: "accounts" | "contacts" | "deals" | "activities",
  q: string = "",
  options: { size?: number; from?: number } = {},
): Promise<{ total: number; items: CrmRecord[]; query?: string; error?: string }> {
  const params = new URLSearchParams();
  if (q.trim()) params.append("q", q.trim());
  params.append("size", String(options.size ?? 50));
  if (options.from !== undefined) params.append("from", String(options.from));
  const res = await fetch(`${API_BASE}/crm/${kind}?${params}`, { credentials: "include" });
  if (!res.ok) {
    if (res.status === 401) return { total: 0, items: [], error: "Sessão necessária" };
    throw new Error(`Erro ao listar CRM ${kind}: ${res.status}`);
  }
  const data = await res.json();
  return {
    total: data.total ?? 0,
    items: (data.items ?? data.records ?? []) as CrmRecord[],
    query: data.query,
    error: data.error,
  };
}

export async function autocompleteElastic(
  q: string,
  size = 12,
): Promise<ElasticAutocompleteResponse> {
  const params = new URLSearchParams({ q: q.trim(), size: String(size) });
  const res = await fetch(`${API_BASE}/elastic/search/autocomplete?${params}`);
  if (!res.ok) throw new Error(`Erro no autocomplete: ${res.status}`);
  return res.json();
}

export async function listElasticTickers(): Promise<ElasticTickerListResponse> {
  const res = await fetch(`${API_BASE}/elastic/tickers`);
  if (!res.ok) throw new Error(`Erro ao listar tickers indexados: ${res.status}`);
  return res.json();
}

export async function listElasticIndices(): Promise<ElasticIndicesListResponse> {
  const res = await fetch(`${API_BASE}/elastic/indices`);
  if (!res.ok) throw new Error(`Erro ao listar índices ES: ${res.status}`);
  return res.json();
}

export async function deleteElasticTicker(ticker: string): Promise<ElasticDeleteResponse> {
  const res = await fetch(`${API_BASE}/elastic/tickers/${encodeURIComponent(ticker)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Erro ao apagar dados: ${res.status}`);
  return res.json();
}

export async function analyzeElasticNews(
  ticker: string,
  q?: string,
  startDate?: string,
  endDate?: string,
  size = 50,
  backend: "heuristic" | "gpt2" | "mistral" = "heuristic",
): Promise<ElasticAnalyzeNewsResponse> {
  const params = new URLSearchParams();
  if (q) params.append("q", q);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  params.append("size", String(size));
  params.append("backend", backend);
  const res = await fetch(
    `${API_BASE}/elastic/analyze/news/${encodeURIComponent(ticker)}?${params}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao analisar notícias: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getElasticNewsGraph(
  ticker: string,
  source: "es" | "build" = "es",
): Promise<ElasticNewsGraphResponse> {
  const params = new URLSearchParams({ source });
  const res = await fetch(
    `${API_BASE}/elastic/graph/news/${encodeURIComponent(ticker)}?${params}`,
  );
  if (!res.ok) throw new Error(`Erro ao obter grafo: ${res.status}`);
  return res.json();
}

export async function getTickerActions(ticker: string): Promise<Actions> {
  const res = await fetch(`${API_BASE}/tickers/${encodeURIComponent(ticker)}/actions`);
  if (!res.ok) throw new Error(`Erro ao obter actions: ${res.status}`);
  return res.json();
}

export async function getTickerTechnical(
  ticker: string,
  period = "1y"
): Promise<TechnicalAnalysis> {
  const res = await fetch(
    `${API_BASE}/tickers/${encodeURIComponent(ticker)}/technical?period=${period}`
  );
  if (!res.ok) throw new Error(`Erro ao obter análise técnica: ${res.status}`);
  return res.json();
}

export async function getTickerTechnicalExplain(
  ticker: string,
  period = "1y"
): Promise<TechnicalExplanation> {
  const res = await fetch(
    `${API_BASE}/tickers/${encodeURIComponent(ticker)}/technical/explain?period=${period}`
  );
  if (!res.ok) throw new Error(`Erro ao obter explicação técnica: ${res.status}`);
  return res.json();
}

export async function addTicker(ticker: string): Promise<AddTickerResponse> {
  const res = await fetch(`${API_BASE}/tickers/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker } as AddTickerRequest),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao adicionar ticker: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function runForecast(request: ForecastRequest): Promise<ForecastResponse> {
  const res = await fetch(`${API_BASE}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

export async function analyzeSentiment(
  ticker: string,
  backend: "arima" | "kronos" = "kronos",
  futureDays = 5,
  period = "1y",
  includeFeatures = true,
): Promise<SentimentBlendedResponse> {
  const params = new URLSearchParams({
    backend,
    future_days: String(futureDays),
    period,
    include_features: String(includeFeatures),
  });
  const res = await fetch(
    `${API_BASE}/sentiment/analyze/${encodeURIComponent(ticker)}?${params}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ${res.status}: ${text}`);
  }
  return res.json();
}

export async function uploadPdf(
  file: File,
  converter: "auto" | "markitdown" | "pymupdf" = "auto",
): Promise<UploadPdfResponse> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams({ converter });
  const res = await fetch(`${API_BASE}/rag/upload?${params}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro no upload: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function listRagDocuments(): Promise<RagDocument[]> {
  const res = await fetch(`${API_BASE}/rag/documents`);
  if (!res.ok) throw new Error(`Erro ao listar documentos: ${res.status}`);
  const data = await res.json();
  return data.documents ?? [];
}

export async function getRagDocument(docId: string): Promise<RagDocument> {
  const res = await fetch(`${API_BASE}/rag/documents/${encodeURIComponent(docId)}`);
  if (!res.ok) throw new Error(`Erro ao obter documento: ${res.status}`);
  return res.json();
}

export async function updateRagDocument(
  docId: string,
  payload: RagDocumentUpdate,
): Promise<RagDocument> {
  const res = await fetch(`${API_BASE}/rag/documents/${encodeURIComponent(docId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao atualizar documento: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function deleteRagDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rag/documents/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Erro ao apagar documento: ${res.status}`);
}

export async function reprocessRagDocument(
  docId: string,
  converter: "auto" | "markitdown" | "pymupdf" = "auto",
): Promise<UploadPdfResponse> {
  const params = new URLSearchParams({ converter });
  const res = await fetch(
    `${API_BASE}/rag/documents/${encodeURIComponent(docId)}/reprocess?${params}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao reprocessar documento: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getRagDocumentHistory(
  docId: string,
): Promise<RagDocumentHistoryResponse> {
  const res = await fetch(`${API_BASE}/rag/documents/${encodeURIComponent(docId)}/history`);
  if (!res.ok) throw new Error(`Erro ao obter histórico: ${res.status}`);
  return res.json();
}

export async function getRagDocumentGraph(
  docId: string,
  topK = 5,
  timeoutMs = 90000,
): Promise<RagDocumentGraphResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(
      `${API_BASE}/rag/documents/${encodeURIComponent(docId)}/graph?top_k=${topK}`,
      { signal: controller.signal },
    );
    if (!res.ok) throw new Error(`Erro ao obter grafo: ${res.status}`);
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function askRag(request: RagChatRequest, timeoutMs = 120000): Promise<RagChatResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/rag/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Erro RAG: ${res.status} - ${text}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function explainRagAnswer(request: RagChatRequest): Promise<RagExplainResponse> {
  const res = await fetch(`${API_BASE}/rag/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao explicar: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function streamRagAnswer(
  request: RagChatRequest,
  onToken: (token: string) => void,
  onSources: (sources: RagSource[]) => void,
  onSkill?: (skill: SkillRef) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/rag/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(`Erro streaming RAG: ${res.status} - ${text}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let lines: string[];
    while ((lines = buffer.split("\n\n")).length > 1) {
      const raw = lines.shift()!;
      buffer = lines.join("\n\n");
      const match = raw.match(/^event: (\w+)\ndata: (.+)$/ms);
      if (!match) continue;
      const [, event, data] = match;
      const parsed = JSON.parse(data);
      if (event === "sources") onSources(parsed);
      else if (event === "skill") onSkill?.(parsed as SkillRef);
      else if (event === "done") return;
      else if (parsed.token) onToken(parsed.token);
    }
  }
}

export async function translateText(
  request: TranslateRequest,
  signal?: AbortSignal,
  timeoutMs = 300000,
): Promise<TranslateResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      credentials: "include",
      signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Erro ao traduzir: ${res.status} - ${text}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function getTickerTranslation(ticker: string): Promise<TickerTranslationResponse | null> {
  const res = await fetch(`${API_BASE}/translate/${encodeURIComponent(ticker)}`, {
    credentials: "include",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao carregar tradução: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function sendBloombergChat(
  messages: { role: "user" | "assistant" | "system"; content: string }[],
): Promise<string> {
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const question = lastUser?.content || "";
  const res = await askRag({ question });
  return res.answer;
}

// --- Contratos públicos ---

export async function getContractStatus(): Promise<ContractStatusResponse> {
  const res = await fetch(`${API_BASE}/contracts/status`);
  if (!res.ok) throw new Error(`Erro ao obter estado dos contratos: ${res.status}`);
  return res.json();
}


export async function getContractAnalytics(
  filters: ContractAnalyticsFilters = {},
): Promise<ContractAnalyticsResponse> {
  const {
    q,
    year,
    entity,
    nif,
    cpv_code,
    procedure_type,
    contract_type,
    role,
    ecological,
    region,
    min_price,
    max_price,
    start_date,
    end_date,
    top_entities = 8,
    top_cpv = 8,
  } = filters;
  const params = new URLSearchParams();
  if (q) params.append("q", q);
  if (year !== undefined) params.append("year", String(year));
  if (entity) params.append("entity", entity);
  if (nif) params.append("nif", nif);
  if (cpv_code) params.append("cpv_code", cpv_code);
  if (procedure_type) params.append("procedure_type", procedure_type);
  if (contract_type) params.append("contract_type", contract_type);
  if (role && role !== "all") params.append("role", role);
  if (ecological) params.append("ecological", "true");
  if (region) params.append("region", region);
  if (min_price !== undefined) params.append("min_price", String(min_price));
  if (max_price !== undefined) params.append("max_price", String(max_price));
  if (start_date) params.append("start_date", start_date);
  if (end_date) params.append("end_date", end_date);
  params.append("top_entities", String(top_entities));
  params.append("top_cpv", String(top_cpv));
  const res = await fetch(`${API_BASE}/contracts/analytics?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter analytics de contratos: ${res.status}`);
  return res.json();
}

export async function getContract(id: string): Promise<ContractItem> {
  const res = await fetch(`${API_BASE}/contracts/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Erro ao obter contrato: ${res.status}`);
  return res.json();
}

export async function analyzeContract(
  id: string,
  request: ContractAnalyzeRequest,
): Promise<ContractAnalyzeResponse> {
  const res = await fetch(`${API_BASE}/contracts/${encodeURIComponent(id)}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error(`Erro ao analisar contrato: ${res.status}`);
  return res.json();
}

/** Ligações oficiais, peça do procedimento (lida) e valores do contrato. */
export async function getContractDocument(
  id: string,
  fetchPiece = true,
): Promise<ContractDocumentResponse> {
  const params = new URLSearchParams({ fetch: String(fetchPiece) });
  const res = await fetch(`${API_BASE}/contracts/${encodeURIComponent(id)}/document?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter a peça do contrato: ${res.status}`);
  return res.json();
}

/** Descarrega o dossiê do contrato em PDF (gera a análise se não for fornecida). */
export async function downloadContractReport(
  id: string,
  request: ContractAnalyzeRequest & { analysis?: string },
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/contracts/${encodeURIComponent(id)}/report/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error(`Erro ao gerar o relatório PDF: ${res.status}`);
  return res.blob();
}

/**
 * Agregado regional (NUTS). O `year` continua a ser o 1º parâmetro para não
 * quebrar as chamadas existentes; `filters` acrescenta o resto dos filtros da
 * análise, para que a distribuição regional acompanhe a pesquisa.
 */
export async function getContractRegionalAnalytics(
  year?: number,
  filters: ContractAnalyticsFilters = {},
  size = 30,
): Promise<ContractRegionalResponse> {
  const params = new URLSearchParams({ size: String(size) });
  const effectiveYear = year ?? filters.year;
  if (effectiveYear !== undefined) params.set("year", String(effectiveYear));
  if (filters.q) params.set("q", filters.q);
  if (filters.entity) params.set("entity", filters.entity);
  if (filters.nif) params.set("nif", filters.nif);
  if (filters.cpv_code) params.set("cpv_code", filters.cpv_code);
  if (filters.procedure_type) params.set("procedure_type", filters.procedure_type);
  if (filters.contract_type) params.set("contract_type", filters.contract_type);
  if (filters.role && filters.role !== "all") params.set("role", filters.role);
  if (filters.ecological) params.set("ecological", "true");
  if (filters.region) params.set("region", filters.region);
  if (filters.min_price !== undefined) params.set("min_price", String(filters.min_price));
  if (filters.max_price !== undefined) params.set("max_price", String(filters.max_price));
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  const res = await fetch(`${API_BASE}/contracts/analytics/regional?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter mapa regional: ${res.status}`);
  return res.json();
}

export async function getContractNetwork(
  limit = 500,
  region?: string,
  nif?: string,
  role = "all",
): Promise<ContractGraphResponse> {
  const params = new URLSearchParams({ limit: String(limit), role });
  if (region) params.set("region", region);
  if (nif) params.set("nif", nif);
  const res = await fetch(`${API_BASE}/contracts/analytics/network?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter rede de entidades: ${res.status}`);
  return res.json();
}

export async function getContractRelations(
  limit = 1000,
  region?: string,
  nif?: string,
  counterpartyNif?: string,
): Promise<ContractRelationsResponse> {
  const params = new URLSearchParams({ limit: String(limit), role: "all" });
  if (region) params.set("region", region);
  if (nif) params.set("nif", nif);
  if (counterpartyNif) params.set("counterparty_nif", counterpartyNif);
  const res = await fetch(`${API_BASE}/contracts/analytics/relations?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter relações: ${res.status}`);
  return res.json();
}

/** Dimensões disponíveis para construir grafos de contratos. */
export async function getGraphDimensions(): Promise<GraphDimensionsResponse> {
  const res = await fetch(`${API_BASE}/contracts/analytics/graph/dimensions`);
  if (!res.ok) throw new Error(`Erro ao obter dimensões de grafo: ${res.status}`);
  return res.json();
}

/** Constrói um grafo de contratos por dimensões (nós e arestas agregados). */
export async function buildContractGraph(
  request: ContractGraphRequest,
): Promise<ContractGraphBuildResponse> {
  const params = new URLSearchParams({
    dimension_a: request.dimension_a,
    metric: request.metric ?? "valor",
    mode: request.mode ?? "auto",
    limit: String(request.limit ?? 60),
    edge_limit: String(request.edge_limit ?? 400),
    sample: String(request.sample ?? 3000),
    sample_order: request.sample_order ?? "valor",
  });
  if (request.dimension_b) params.set("dimension_b", request.dimension_b);
  if (request.q) params.set("q", request.q);
  if (request.year !== undefined) params.set("year", String(request.year));
  if (request.region) params.set("region", request.region);
  if (request.cpv_code) params.set("cpv_code", request.cpv_code);
  if (request.min_value !== undefined) params.set("min_value", String(request.min_value));
  if (request.max_value !== undefined) params.set("max_value", String(request.max_value));
  const res = await fetch(`${API_BASE}/contracts/analytics/graph?${params}`);
  if (!res.ok) {
    let message = `Erro ao construir grafo: ${res.status}`;
    try {
      const payload = await res.json();
      const detail = (payload as { detail?: unknown }).detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { loc?: unknown; msg?: string };
        const loc = Array.isArray(first.loc) ? first.loc : [];
        const field = loc.length > 0 ? String(loc[loc.length - 1]) : "parâmetro";
        message = `Parâmetro inválido «${field}»: ${first.msg ?? "valor não aceite"}.`;
      } else if (typeof detail === "string") {
        message = detail;
      }
    } catch {
      // resposta sem corpo JSON: mantém a mensagem genérica
    }
    if (res.status === 422) {
      message +=
        " Se acabou de atualizar o frontend, reinicie o backend (uvicorn na porta 8002) para aplicar os novos limites.";
    }
    throw new Error(message);
  }
  return res.json();
}

export async function exportContractsExcel(
  filters: ContractAnalyticsFilters = {},
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/contracts/export/excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao exportar Excel: ${res.status} - ${text}`);
  }
  return res.blob();
}

export async function exportContractsPdf(
  filters: ContractAnalyticsFilters = {},
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/contracts/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao exportar PDF: ${res.status} - ${text}`);
  }
  return res.blob();
}

export async function getContractYears(): Promise<ContractYearsResponse> {
  const res = await fetch(`${API_BASE}/contracts/years`);
  if (!res.ok) throw new Error(`Erro ao obter anos de contratos: ${res.status}`);
  return res.json();
}

export async function ingestContracts(
  request: ContractIngestRequest,
): Promise<ContractIngestResponse> {
  const res = await fetch(`${API_BASE}/contracts/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar contratos: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function previewImportFile(
  file: File,
  dataType: ImportDataType = "auto",
): Promise<ImportPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("data_type", dataType);
  const res = await fetch(`${API_BASE}/import/preview`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro na pré-visualização: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function ingestImport(
  request: ImportIngestRequest,
): Promise<ImportIngestResponse> {
  const res = await fetch(`${API_BASE}/import/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao importar: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function uploadAndImportFile(
  file: File,
  dataType: ImportDataType = "auto",
  options: ImportIngestRequest["options"] = { link_entities: true },
): Promise<ImportIngestResponse> {
  const preview = await previewImportFile(file, dataType);
  const request: ImportIngestRequest = {
    data_type: preview.data_type,
    file_type: preview.file_type,
    filename: preview.filename,
    rows: preview.rows,
    options,
  };
  return ingestImport(request);
}

export async function searchContracts(
  request: ContractSearchRequest,
): Promise<ContractSearchResponse> {
  const res = await fetch(`${API_BASE}/contracts/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar contratos: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function autocompleteContracts(
  q: string,
  size = 12,
): Promise<ContractAutocompleteResponse> {
  const params = new URLSearchParams({ q: q.trim(), size: String(size) });
  const res = await fetch(`${API_BASE}/contracts/autocomplete?${params}`);
  if (!res.ok) throw new Error(`Erro no autocomplete de contratos: ${res.status}`);
  return res.json();
}

export async function chatContracts(
  request: ContractChatRequest,
  timeoutMs = 120000,
): Promise<ContractChatResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/contracts/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Erro no chat de contratos: ${res.status} - ${text}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

// --- Diretório de empresas (entidades) ---

export async function searchCompanies(
  request: CompanySearchRequest = {},
): Promise<CompanySearchResponse> {
  let caeValue = request.cae;
  if (Array.isArray(caeValue)) {
    caeValue = caeValue.join(",");
  }
  const payload = {
    ...request,
    cae: caeValue || undefined,
    from: request.from ?? 0,
    size: request.size ?? 20,
  };
  const res = await fetch(`${API_BASE}/companies/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar empresas: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getCompanyDetail(nif: string, year?: number): Promise<CompanyDetail> {
  const params = new URLSearchParams();
  if (year !== undefined) params.append("year", String(year));
  const res = await fetch(`${API_BASE}/companies/${encodeURIComponent(nif)}?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter detalhes da empresa: ${res.status}`);
  return res.json();
}

export async function getCompanyContracts(
  nif: string,
  role = "all",
  from = 0,
  size = 20,
): Promise<CompanyContractsResponse> {
  const params = new URLSearchParams({ role, from: String(from), size: String(size) });
  const res = await fetch(`${API_BASE}/companies/${encodeURIComponent(nif)}/contracts?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter contratos da empresa: ${res.status}`);
  return res.json();
}

export async function getCompanyAnalytics(
  nif: string,
  role = "all",
  year?: number,
): Promise<CompanyAnalyticsResponse> {
  const params = new URLSearchParams({ role });
  if (year !== undefined) params.append("year", String(year));
  const res = await fetch(`${API_BASE}/companies/${encodeURIComponent(nif)}/analytics?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter analytics da empresa: ${res.status}`);
  return res.json();
}

/**
 * Dashboard agregado por papel (adjudicantes, adjudicatários ou empresas).
 *
 * Devolve indicadores de volume/valor, distribuições (ano, NUTS, CPV,
 * procedimento, tipo de contrato), contrapartes, ranking e concentração.
 */
export async function getEntityRoleSummary(
  request: EntityRoleSummaryRequest = {},
): Promise<EntityRoleSummaryResponse> {
  const payload = {
    role: "all",
    top_n: 25,
    min_contracts: 1,
    ...request,
  };
  const res = await fetch(`${API_BASE}/companies/role-summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter o resumo por papel: ${res.status} - ${text}`);
  }
  return res.json();
}

// --- Cadastro de entidades (pesquisa de empresas) ---

export async function searchEntities(
  request: EntitySearchRequest = {},
): Promise<EntitySearchResponse> {
  let caeValue = request.cae;
  if (Array.isArray(caeValue)) {
    caeValue = caeValue.join(",");
  }
  const payload = {
    ...request,
    cae: caeValue || undefined,
    from: request.from ?? 0,
    size: request.size ?? 20,
  };
  const res = await fetch(`${API_BASE}/entities/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar empresas: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function enrichEntity(
  nif: string,
  payload: Record<string, unknown> = {},
): Promise<EntityEnrichmentResponse> {
  const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(nif)}/enrich`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Falha ao enriquecer ${nif}: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getEntityDetail(nif: string): Promise<EntityDetail> {
  const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(nif)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter ficha da empresa: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Ontologia da entidade: relações guardadas em `finance_world_relations`. */
export async function getEntityRelations(nif: string, size = 50): Promise<EntityRelationsResponse> {
  const params = new URLSearchParams({ size: String(size) });
  const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(nif)}/relations?${params}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter relações da entidade: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Relatório PDF da entidade (enriquecimento web + CPV + relações). */
export async function downloadEntityReport(nif: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(nif)}/report.pdf`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao gerar o relatório PDF: ${res.status} - ${text}`);
  }
  return res.blob();
}

export async function getEntityStats(): Promise<EntityStats> {
  const res = await fetch(`${API_BASE}/entities/stats`);
  if (!res.ok) throw new Error(`Erro ao obter estatísticas de entidades: ${res.status}`);
  return res.json();
}

export async function entityAutocomplete(
  q: string,
  size = 10,
): Promise<{ query: string; suggestions: { nif?: string; name: string; country?: string }[] }> {
  const params = new URLSearchParams({ q: q.trim(), size: String(size) });
  const res = await fetch(`${API_BASE}/entities/autocomplete?${params}`);
  if (!res.ok) throw new Error(`Erro no autocomplete de empresas: ${res.status}`);
  return res.json();
}

export async function ingestEntities(
  request: EntityIngestRequest = {},
): Promise<EntityIngestResponse> {
  const res = await fetch(`${API_BASE}/entities/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao importar entidades: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Obtém marcas (INPI) e firmas (RNPC) e guarda-as na ficha da empresa. */
export async function enrichCompany(
  nif: string,
  options: {
    include_trademarks?: boolean;
    include_firmas?: boolean;
    max_trademarks?: number;
    max_firmas?: number;
    trademark_detail_limit?: number;
  } = {},
): Promise<CompanyEnrichmentResponse> {
  const params = new URLSearchParams({
    include_trademarks: String(options.include_trademarks ?? true),
    include_firmas: String(options.include_firmas ?? true),
    max_trademarks: String(options.max_trademarks ?? 40),
    max_firmas: String(options.max_firmas ?? 15),
    trademark_detail_limit: String(options.trademark_detail_limit ?? 8),
  });
  const res = await fetch(`${API_BASE}/companies/${encodeURIComponent(nif)}/enrich?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao enriquecer empresa: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Publicações de atos societários de uma entidade (Ministério da Justiça). */
export async function getCompanySocietarioPublicacoes(
  nif: string,
  from = 0,
  size = 100,
): Promise<CompanySocietarioResponse> {
  const params = new URLSearchParams({
    from: String(from),
    size: String(size),
  });
  const res = await fetch(
    `${API_BASE}/societario/companies/${encodeURIComponent(nif)}?${params}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter publicações societárias: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Pessoas/cargos extraídos das publicações societárias de uma entidade. */
export async function getCompanySocietarioPeople(
  nif: string,
): Promise<SocietarioCompanyPeopleResponse> {
  const res = await fetch(
    `${API_BASE}/societario/companies/${encodeURIComponent(nif)}/people`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter pessoas societárias: ${res.status} - ${text}`);
  }
  return res.json();
}

/**
 * Valida, no PessoasIQ, quais destes NIF já têm ficha indexada (`finance_people`).
 * Serve para marcar as pessoas do societário que ainda faltam alimentar.
 */
export async function checkPeopleIndexed(
  nifs: string[],
): Promise<PeoplePresenceResponse> {
  const res = await fetch(`${API_BASE}/people/exists`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nifs }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao validar o índice de pessoas: ${res.status} - ${text}`);
  }
  return res.json();
}

export interface SocietarioTimelineResponse {
  nif: string;
  total: number;
  backend_used: string;
  markdown: string;
  error?: string;
}

export async function generateCompanySocietarioTimeline(
  nif: string,
  opts?: { backend?: string; max_tokens?: number; temperature?: number },
): Promise<SocietarioTimelineResponse> {
  const res = await fetch(
    `${API_BASE}/societario/companies/${encodeURIComponent(nif)}/timeline`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        backend: opts?.backend,
        max_tokens: opts?.max_tokens ?? 2048,
        temperature: opts?.temperature ?? 0.3,
      }),
    },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao gerar timeline societária: ${res.status} - ${text}`);
  }
  return res.json();
}

export interface SocietarioCollectEntitiesResponse {
  entities: number;
  collected: number;
  ingested: number;
  deleted_stale: number;
  with_details: boolean;
  items: Array<Record<string, unknown>>;
  errors: Array<{ nif?: string; name?: string; error: string }>;
  message?: string;
}

/** Recolhe publicações societárias do MJ para um NIF via recolha automática (2captcha). */
export async function collectSocietarioForNif(
  nif: string,
  opts?: { max_pages?: number; min_interval?: number; recaptcha_timeout?: number; stop_on_captcha?: boolean; api_key?: string; proxy?: string; debug?: boolean },
): Promise<SocietarioCollectEntitiesResponse> {
  const res = await fetch(`${API_BASE}/societario/collect-entities`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nifs: [nif],
      max_pages: opts?.max_pages ?? 50,
      min_interval: opts?.min_interval ?? 10,
      recaptcha_timeout: opts?.recaptcha_timeout ?? 180,
      stop_on_captcha: opts?.stop_on_captcha ?? false,
      ingest: true,
      api_key: opts?.api_key,
      proxy: opts?.proxy,
      debug: opts?.debug ?? true,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao recolher dados societários: ${res.status} - ${text}`);
  }
  return res.json();
}

// --- Pessoas e cargos (societário) ---

export async function searchPeople(
  q?: string,
  opts?: {
    nif?: string;
    companyNif?: string;
    role?: string;
    isCompany?: boolean;
    /** `cire` (papéis de insolvência) ou `societario` (cargos das publicações). */
    origin?: "cire" | "societario" | "";
    /** Sub-string do campo `source` (ex.: `parlamento`, `wikipedia`). */
    source?: string;
    /** Partido político (sub-string, sem distinção de maiúsculas). */
    party?: string;
    /** Tag a exigir no campo `tags` (ex.: `politica`, `deputados`). */
    tag?: string;
    minRoles?: number;
    minCompanies?: number;
    sort?: "relevance" | "roles" | "recent" | "name";
    size?: number;
    from?: number;
  },
): Promise<PeopleSearchResponse> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (opts?.nif) params.set("nif", opts.nif);
  if (opts?.companyNif) params.set("company_nif", opts.companyNif);
  if (opts?.role) params.set("role", opts.role);
  if (opts?.origin) params.set("origin", opts.origin);
  if (opts?.source) params.set("source", opts.source);
  if (opts?.party) params.set("party", opts.party);
  if (opts?.tag) params.set("tag", opts.tag);
  if (opts?.minRoles) params.set("min_roles", String(opts.minRoles));
  if (opts?.minCompanies) params.set("min_companies", String(opts.minCompanies));
  if (opts?.sort) params.set("sort", opts.sort);
  params.set("size", String(opts?.size ?? 20));
  params.set("from", String(opts?.from ?? 0));
  const res = await fetch(`${API_BASE}/people/search?${params}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar pessoas: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Sugestões (nome/NIF/cargo) enquanto se escreve na pesquisa de pessoas. */
export async function autocompletePeople(
  q: string,
  opts?: { limit?: number; isCompany?: boolean; signal?: AbortSignal },
): Promise<PeopleAutocompleteItem[]> {
  const params = new URLSearchParams();
  params.set("q", q);
  params.set("limit", String(opts?.limit ?? 8));
  if (opts?.isCompany !== undefined) params.set("is_company", String(opts.isCompany));
  const res = await fetch(`${API_BASE}/people/autocomplete?${params}`, {
    signal: opts?.signal ?? AbortSignal.timeout(15000),
  });
  if (!res.ok) throw new Error(`Erro no autocomplete: ${res.status}`);
  const data = (await res.json()) as { items?: PeopleAutocompleteItem[] };
  return data.items ?? [];
}

/** Opções de filtro (cargos, origens, tipos) para a pesquisa de pessoas. */
export async function getPeopleFilters(): Promise<PeopleFiltersResponse> {
  const res = await fetch(`${API_BASE}/people/filters`, { signal: AbortSignal.timeout(30000) });
  if (!res.ok) throw new Error(`Erro ao obter filtros: ${res.status}`);
  return res.json();
}

export async function getPerson(nif: string): Promise<Person> {
  const res = await fetch(`${API_BASE}/people/${encodeURIComponent(nif)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter pessoa: ${res.status} - ${text}`);
  }
  return res.json();
}

// --- Empresas no PessoasIQ (pesquisar por empresa: empresa + pessoas + grafo) ---

export interface PeopleCompanyItem {
  nif: string;
  name?: string | null;
  /** Pessoas distintas com cargos nesta empresa. */
  people_count: number;
  /** Cargos registados nesta empresa. */
  roles_count: number;
}

export interface PeopleCompaniesResponse {
  total: number;
  items: PeopleCompanyItem[];
  note?: string | null;
  error?: string | null;
}

export interface CompanyPersonRole {
  role?: string | null;
  role_org?: string | null;
  event?: string | null;
  date?: string | null;
  acto?: string | null;
  publication_id?: string | null;
}

export interface CompanyPerson {
  nif: string;
  name: string;
  is_company: boolean;
  /** Cargos desta pessoa nesta empresa. */
  cargos_empresa?: number;
  cargo?: string | null;
  role_org?: string | null;
  event?: string | null;
  date?: string | null;
  acto?: string | null;
  publication_id?: string | null;
  roles_total?: number;
  companies_total?: number;
  origin?: string | null;
  roles?: CompanyPersonRole[];
}

export interface PeopleCompanyResponse {
  nif: string;
  name?: string | null;
  total: number;
  people: CompanyPerson[];
  error?: string | null;
}

/**
 * Empresas com pessoas/cargos no PessoasIQ (pesquisa por empresa).
 *
 * A empresa pode não ter ficha própria no índice de pessoas: o vínculo é o
 * cargo das pessoas nessa empresa, por isso aparece na mesma.
 */
export async function searchPeopleCompanies(
  q: string,
  size = 8,
): Promise<PeopleCompaniesResponse> {
  const params = new URLSearchParams({ q, size: String(size) });
  const res = await fetch(`${API_BASE}/people/companies?${params}`, {
    signal: AbortSignal.timeout(30000),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar empresas: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Ficha de empresa no PessoasIQ: a empresa e as pessoas com cargos nela. */
export async function getCompanyPeople(
  nif: string,
  size = 200,
): Promise<PeopleCompanyResponse> {
  const res = await fetch(
    `${API_BASE}/people/companies/${encodeURIComponent(nif)}?size=${size}`,
    { signal: AbortSignal.timeout(45000) },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter a empresa: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getPersonGraph(nif: string): Promise<PeopleGraphResponse> {
  const res = await fetch(`${API_BASE}/people/${encodeURIComponent(nif)}/graph`, {
    signal: AbortSignal.timeout(45000),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter grafo da pessoa: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getCompanyPeopleGraph(companyNif: string): Promise<PeopleGraphResponse> {
  const res = await fetch(
    `${API_BASE}/people/company/${encodeURIComponent(companyNif)}/graph`,
    { signal: AbortSignal.timeout(45000) },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter grafo da empresa: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getCompanyCombinedGraph(
  companyNif: string,
  opts?: { includePeople?: boolean; includeContracts?: boolean; contractLimit?: number },
): Promise<PeopleGraphResponse> {
  const params = new URLSearchParams();
  if (opts?.includePeople !== undefined) params.set("include_people", String(opts.includePeople));
  if (opts?.includeContracts !== undefined) params.set("include_contracts", String(opts.includeContracts));
  if (opts?.contractLimit !== undefined) params.set("contract_limit", String(opts.contractLimit));
  const query = params.toString() ? `?${params}` : "";
  const res = await fetch(
    `${API_BASE}/people/company/${encodeURIComponent(companyNif)}/graph/full${query}`,
    { signal: AbortSignal.timeout(45000) },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter grafo combinado: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function ingestPeopleForCompany(nif: string): Promise<PeopleIngestResponse> {
  const res = await fetch(`${API_BASE}/people/ingest/${encodeURIComponent(nif)}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar pessoas/cargos: ${res.status} - ${text}`);
  }
  return res.json();
}

/**
 * Indexa no PessoasIQ as pessoas que constam dos processos de insolvência do CIRE.
 * A ingestão é longa (corre em segundo plano): devolve o trabalho a acompanhar com
 * `getPeopleCireJob`.
 */
export async function ingestPeopleFromCire(
  opts?: PeopleCireIngestRequest,
): Promise<PeopleCireJobResponse> {
  const res = await fetch(`${API_BASE}/people/ingest-cire`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      limit: opts?.limit ?? null,
      include_companies: opts?.include_companies ?? false,
      papeis: opts?.papeis ?? null,
      wait: opts?.wait ?? false,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao indexar pessoas do CIRE: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Progresso de um trabalho de ingestão de pessoas do CIRE. */
export async function getPeopleCireJob(jobId: string): Promise<PeopleCireJobResponse> {
  const res = await fetch(`${API_BASE}/people/ingest-cire/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter o progresso da ingestão do CIRE: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Trabalhos de ingestão de pessoas do CIRE (mais recentes primeiro). */
export async function getPeopleCireJobs(): Promise<PeopleCireJobResponse[]> {
  const res = await fetch(`${API_BASE}/people/ingest-cire/jobs`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter as ingestões do CIRE: ${res.status} - ${text}`);
  }
  return res.json();
}

// --- Dados públicos da pessoa (redes sociais + internet) e análise 360 ---

/**
 * Vai buscar o que é público sobre a pessoa: LinkedIn, TikTok, Facebook e internet.
 * Guarda imagens, vídeos e textos ligados à ficha e devolve o que cada fonte conseguiu.
 */
export async function collectPersonSocial(
  nif: string,
  opts?: { sources?: string[]; limit?: number },
): Promise<PeopleSocialCollectResponse> {
  const res = await fetch(`${API_BASE}/people/${encodeURIComponent(nif)}/social-collect`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sources: opts?.sources ?? ["internet", "linkedin", "tiktok", "facebook"],
      limit: opts?.limit ?? 6,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter dados públicos: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Conteúdos já recolhidos sobre a pessoa (imagens, vídeos e textos). */
export async function getPersonSocial(nif: string, size = 100): Promise<PeopleSocialResponse> {
  const res = await fetch(
    `${API_BASE}/people/${encodeURIComponent(nif)}/social?size=${encodeURIComponent(String(size))}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter os conteúdos recolhidos: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Análise 360: ficha, insolvências, presença digital, risco, grafo e ficha analítica. */export async function getPerson360(
  nif: string,
  opts?: { withAi?: boolean; cireSize?: number; socialSize?: number; backend?: string },
): Promise<People360Response> {
  const params = new URLSearchParams();
  if (opts?.withAi !== undefined) params.set("with_ai", String(opts.withAi));
  if (opts?.cireSize !== undefined) params.set("cire_size", String(opts.cireSize));
  if (opts?.socialSize !== undefined) params.set("social_size", String(opts.socialSize));
  if (opts?.backend) params.set("backend", opts.backend);
  const res = await fetch(
    `${API_BASE}/people/${encodeURIComponent(nif)}/360?${params.toString()}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter a análise 360: ${res.status} - ${text}`);
  }
  return res.json();
}

// --- Resumo de um nó do grafo (IA + pesquisa na web) ---

/** Resumo já gravado de um nó (não gera nada nem gasta tokens). */
export async function getNodeSummary(opts: {
  nodeId?: string;
  nif?: string;
  name?: string;
}): Promise<NodeSummaryResponse> {
  const params = new URLSearchParams();
  if (opts.nodeId) params.set("node_id", opts.nodeId);
  if (opts.nif) params.set("nif", opts.nif);
  if (opts.name) params.set("name", opts.name);
  const res = await fetch(`${API_BASE}/people/summary?${params.toString()}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter o resumo do nó: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Perfil político enriquecido de uma pessoa (técnico + biográfico + notícias + grafo). */
export async function getPoliticianProfile(
  nif: string,
  opts?: { backend?: string; reuseHours?: number },
): Promise<PoliticianProfile> {
  const params = new URLSearchParams();
  if (opts?.backend) params.set("backend", opts.backend);
  if (opts?.reuseHours !== undefined) params.set("reuse_hours", String(opts.reuseHours));
  const res = await fetch(
    `${API_BASE}/people/${encodeURIComponent(nif)}/politician/profile?${params.toString()}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter o perfil político: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Gera/reativa o enriquecimento político de uma pessoa. */
export async function enrichPolitician(
  nif: string,
  opts?: { backend?: string; save?: boolean; reuseHours?: number; limitPartyNews?: number; maxCoParty?: number },
): Promise<PoliticianProfile> {
  const res = await fetch(`${API_BASE}/people/${encodeURIComponent(nif)}/politician/enrich`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      backend: opts?.backend ?? null,
      save: opts?.save ?? true,
      reuse_hours: opts?.reuseHours ?? 0,
      limit_party_news: opts?.limitPartyNews ?? 12,
      max_co_party: opts?.maxCoParty ?? 20,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao enriquecer o perfil político: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Notícias e artigos sobre o partido do político. */
export async function getPoliticianPartyNews(
  nif: string,
  limit = 12,
): Promise<{ party?: string | null; total: number; items: Record<string, any>[]; warnings?: string[] }> {
  const res = await fetch(
    `${API_BASE}/people/${encodeURIComponent(nif)}/politician/party-news?limit=${encodeURIComponent(String(limit))}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter notícias do partido: ${res.status} - ${text}`);
  }
  return res.json();
}

/** Grafo de relações políticas: partido, cargos, colegas e eventos/notícias. */
export async function getPoliticianGraph(nif: string, opts?: { maxCoParty?: number; limitPartyNews?: number }): Promise<PeopleGraphResponse> {
  const params = new URLSearchParams();
  if (opts?.maxCoParty !== undefined) params.set("max_co_party", String(opts.maxCoParty));
  if (opts?.limitPartyNews !== undefined) params.set("limit_party_news", String(opts.limitPartyNews));
  const res = await fetch(
    `${API_BASE}/people/${encodeURIComponent(nif)}/politician/graph?${params.toString()}`,
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter o grafo político: ${res.status} - ${text}`);
  }
  return res.json();
}

/**
 * Gera o resumo de um nó (factos do IQ OS + pesquisa na web + modelo) e guarda-o
 * sempre em `finance_node_summaries`.
 */
export async function generateNodeSummary(opts: {
  nodeId?: string;
  nif?: string;
  name?: string;
  kind?: string;
  limit?: number;
  pages?: number;
  reuseHours?: number;
  backend?: string;
}): Promise<NodeSummaryResponse> {
  const res = await fetch(`${API_BASE}/people/summary`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      node_id: opts.nodeId ?? null,
      nif: opts.nif ?? null,
      name: opts.name ?? null,
      kind: opts.kind ?? null,
      limit: opts.limit ?? 6,
      pages: opts.pages ?? 2,
      reuse_hours: opts.reuseHours ?? 0,
      backend: opts.backend ?? null,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao gerar o resumo do nó: ${res.status} - ${text}`);
  }
  return res.json();
}

