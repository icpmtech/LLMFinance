export const API_BASE =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

import type {
  Actions,
  AddTickerRequest,
  AddTickerResponse,
  Calendar,
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
  Financials,
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
  ForecastRequest,
  ForecastResponse,
  RagChatRequest,
  RagChatResponse,
  RagDocument,
  RagDocumentGraphResponse,
  RagDocumentHistoryResponse,
  RagDocumentUpdate,
  RagExplainResponse,
  RagSource,
  UploadPdfResponse,
} from "./types";



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
  size = 20,
): Promise<ElasticSearchGlobalResponse> {
  const params = new URLSearchParams({ q: q.trim(), size: String(size) });
  const res = await fetch(`${API_BASE}/elastic/search/global?${params}`);
  if (!res.ok) throw new Error(`Erro na pesquisa global: ${res.status}`);
  return res.json();
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

