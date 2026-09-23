export const API_BASE =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";

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
  Person,
  PeopleGraphResponse,
  PeopleIngestResponse,
  ImportFileType,
  ImportDataType,
  ImportPreviewRow,
  ImportPreviewResponse,
  ImportIngestRequest,
  ImportIngestResponse,
  ImportStatusResponse,
} from "./types";

export type { ContractAnalyticsResponse, ContractAnalyticsFilters, CompanySearchResponse, CompanyDetail, CompanyContractsResponse, CompanyAnalyticsResponse };
export type { ImportFileType, ImportDataType, ImportPreviewRow, ImportPreviewResponse, ImportIngestRequest, ImportIngestResponse, ImportStatusResponse };
export type { PeopleSearchResponse, Person, PeopleGraphResponse, PeopleIngestResponse };

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

export async function getContractRegionalAnalytics(year?: number): Promise<ContractRegionalResponse> {
  const params = new URLSearchParams({ size: "30" });
  if (year !== undefined) params.set("year", String(year));
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
  const payload = { ...request, from: request.from ?? 0, size: request.size ?? 20 };
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
  const payload = { ...request, from: request.from ?? 0, size: request.size ?? 20 };
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

export async function getEntityDetail(nif: string): Promise<EntityDetail> {
  const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(nif)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter ficha da empresa: ${res.status} - ${text}`);
  }
  return res.json();
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
    size?: number;
    from?: number;
  },
): Promise<PeopleSearchResponse> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (opts?.nif) params.set("nif", opts.nif);
  if (opts?.companyNif) params.set("company_nif", opts.companyNif);
  if (opts?.role) params.set("role", opts.role);
  if (opts?.isCompany !== undefined) params.set("is_company", String(opts.isCompany));
  params.set("size", String(opts?.size ?? 20));
  params.set("from", String(opts?.from ?? 0));
  const res = await fetch(`${API_BASE}/people/search?${params}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao pesquisar pessoas: ${res.status} - ${text}`);
  }
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

export async function getPersonGraph(nif: string): Promise<PeopleGraphResponse> {
  const res = await fetch(`${API_BASE}/people/${encodeURIComponent(nif)}/graph`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao obter grafo da pessoa: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function getCompanyPeopleGraph(companyNif: string): Promise<PeopleGraphResponse> {
  const res = await fetch(
    `${API_BASE}/people/company/${encodeURIComponent(companyNif)}/graph`,
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

