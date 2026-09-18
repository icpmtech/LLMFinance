/**
 * Cliente do módulo de recolha (`/scraper/*`) — o «web scraping» do IQ OS.
 *
 * Permite definir **fontes** (URL + *fetcher* + seletores + campos + cron),
 * executá-las manualmente ou por agendamento, e pesquisar os itens recolhidos
 * (gravados em JSONL e indexados no Elasticsearch em `finance_scraped`).
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o token
 * da sessão (necessário para escrever definições e disparar execuções).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type ScraperFetcher = "http" | "dynamic" | "stealth";
export type ScraperSelectorKind = "css" | "xpath" | "text" | "regex";
export type ScraperCast = "text" | "int" | "float" | "bool" | "date";

export type ScraperField = {
  name: string;
  label?: string;
  selector: string;
  type: ScraperSelectorKind;
  attr?: string | null;
  /** Recolher todas as ocorrências (lista) em vez da primeira. */
  all?: boolean;
  join?: string;
  cast?: ScraperCast;
  max_length?: number;
};

export type ScraperSelector = { selector: string; type: ScraperSelectorKind };

export type ScraperPagination = ScraperSelector & { attr: string; max_pages: number };

export type ScraperRun = {
  run_id: string;
  source_id: string;
  source_name?: string;
  status: "running" | "completed" | "failed";
  trigger: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  items_count: number;
  indexed_count: number;
  error_count: number;
  pages: number;
  errors?: string[];
  running?: boolean;
};

export type ScraperSource = {
  id: string;
  name: string;
  description?: string;
  url: string;
  enabled: boolean;
  fetcher: ScraperFetcher;
  list: ScraperSelector;
  fields: ScraperField[];
  pagination: ScraperPagination;
  options: Record<string, unknown>;
  schedule: { cron: string; timezone: string };
  respect_robots: boolean;
  tags: string[];
  id_fields: string[];
  title_field?: string;
  summary_field?: string;
  text_field?: string;
  tags_field?: string;
  created_at?: string;
  updated_at?: string;
  last_run?: ScraperRun | null;
  running?: boolean;
  active_run_id?: string | null;
};

export type ScraperItem = {
  item_id: string;
  source_id?: string;
  source_name?: string;
  run_id?: string;
  title: string;
  summary?: string;
  text?: string;
  url?: string;
  tags?: string[];
  data?: Record<string, unknown>;
  scraped_at?: string;
  trigger?: string;
};

export type ScraperFacets = {
  sources: { key: string; count: number }[];
  tags: { key: string; count: number }[];
  days: { key: string; count: number }[];
};

export type ScraperSearchResult = {
  total: number;
  items: ScraperItem[];
  facets: ScraperFacets;
  error?: string;
};

export type ScraperMeta = {
  fetchers: { id: ScraperFetcher; label: string; options: Record<string, unknown> }[];
  selector_kinds: ScraperSelectorKind[];
  casts: ScraperCast[];
  cron_presets: { cron: string; label: string }[];
  default_timezone: string;
  index: string;
};

export type ScraperStatus = {
  scrapling: boolean;
  scrapling_error?: string;
  fetchers: Record<string, boolean>;
  playwright?: boolean;
  elasticsearch: boolean;
  indexed_items?: number;
  indexed_sources?: { key: string; count: number }[];
  scheduler: { available: boolean; jobs: { id: string; source_id: string; name: string; next_run_time: string | null }[]; jobs_total: number; error?: string | null };
};

export type ScraperStats = {
  sources_total: number;
  sources_enabled: number;
  runs_total: number;
  runs_completed: number;
  items_scraped: number;
  items_indexed: number;
  items_by_source: Record<string, number>;
  last_run?: ScraperRun | null;
  active_runs: Record<string, string>;
};

export type ScraperPreview = {
  ok: boolean;
  error?: string;
  pages: number;
  total: number;
  items: ScraperItem[];
  fields?: string[];
};

/** Candidato a contentor de item, medido pela análise da página. */
export type ScraperCandidate = {
  selector: string;
  count: number;
  text_ratio: number;
  title_ratio: number;
  link_ratio: number;
  image_ratio: number;
  score: number;
  samples: string[];
};

/** Proposta de definição (IA e/ou heurística) para um URL. */
export type ScraperSuggestion = {
  ok: boolean;
  error?: string;
  url: string;
  title?: string;
  analysis: ScraperCandidate[];
  heuristic?: Partial<ScraperSource> | null;
  definition: Partial<ScraperSource> | null;
  origin: "ai" | "heuristica" | null;
  ai: { provider: string; provider_label?: string; model: string; notes?: string } | null;
  ai_error?: string | null;
  preview?: ScraperPreview | null;
};

/* ----------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

/* -------------------------------------------------------------------- API */

export function getScraperMeta() {
  return request<ScraperMeta>("/scraper/meta");
}

export function getScraperStatus() {
  return request<ScraperStatus>("/scraper/status");
}

export function getScraperStats() {
  return request<ScraperStats>("/scraper/stats");
}

export function listScraperSources() {
  return request<{ total: number; items: ScraperSource[] }>("/scraper/sources");
}

export function getScraperSource(id: string) {
  return request<{ item: ScraperSource }>(`/scraper/sources/${encodeURIComponent(id)}`);
}

export function createScraperSource(payload: Partial<ScraperSource>) {
  return request<{ item: ScraperSource }>("/scraper/sources", withBody("POST", payload));
}

export function updateScraperSource(id: string, payload: Partial<ScraperSource>) {
  return request<{ item: ScraperSource }>(`/scraper/sources/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function deleteScraperSource(id: string, purgeItems = false) {
  const suffix = purgeItems ? "?purge_items=true" : "";
  return request<{ ok: boolean; deleted: string; purged?: { deleted?: number } }>(
    `/scraper/sources/${encodeURIComponent(id)}${suffix}`,
    withBody("DELETE"),
  );
}

export function runScraperSource(id: string) {
  return request<{ run_id: string; status: string; already_running?: boolean }>(
    `/scraper/sources/${encodeURIComponent(id)}/run`,
    withBody("POST"),
  );
}

export function previewScraperSource(source: Partial<ScraperSource>, limit = 5, maxPages = 1) {
  return request<ScraperPreview>("/scraper/preview", withBody("POST", { source, limit, max_pages: maxPages }));
}

/**
 * Pede uma proposta de definição para um URL: o backend analisa a página e,
 * se houver fornecedor de IA configurado, usa-o para escolher os seletores
 * (com a heurística determinística como reserva).
 */
export function suggestScraperSource(payload: {
  url: string;
  hint?: string;
  fetcher?: ScraperFetcher;
  options?: Record<string, unknown>;
  provider?: string;
  model?: string;
  useAi?: boolean;
}) {
  return request<ScraperSuggestion>(
    "/scraper/suggest",
    withBody("POST", {
      url: payload.url,
      hint: payload.hint,
      fetcher: payload.fetcher,
      options: payload.options ?? {},
      provider: payload.provider,
      model: payload.model,
      use_ai: payload.useAi !== false,
    }),
  );
}

export function listScraperRuns(sourceId?: string, limit = 50) {
  const params = new URLSearchParams();
  if (sourceId) params.set("source_id", sourceId);
  params.set("limit", String(limit));
  return request<{ total: number; items: ScraperRun[] }>(`/scraper/runs?${params.toString()}`);
}

export function getScraperRun(runId: string, sourceId?: string) {
  const params = new URLSearchParams();
  if (sourceId) params.set("source_id", sourceId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<{ item: ScraperRun }>(`/scraper/runs/${encodeURIComponent(runId)}${suffix}`);
}

export function getScraperRunItems(runId: string, sourceId: string, limit = 100, offset = 0) {
  const params = new URLSearchParams({ source_id: sourceId, limit: String(limit), offset: String(offset) });
  return request<{ run_id: string; total: number; items: ScraperItem[]; offset?: number }>(
    `/scraper/runs/${encodeURIComponent(runId)}/items?${params.toString()}`,
  );
}

export type ScraperSearchParams = {
  q?: string;
  sourceId?: string;
  tags?: string[];
  dateFrom?: string;
  dateTo?: string;
  size?: number;
  offset?: number;
  sort?: "recent" | "oldest" | "relevance";
};

export function searchScraperItems(params: ScraperSearchParams = {}) {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.sourceId) query.set("source_id", params.sourceId);
  for (const tag of params.tags ?? []) query.append("tag", tag);
  if (params.dateFrom) query.set("date_from", params.dateFrom);
  if (params.dateTo) query.set("date_to", params.dateTo);
  query.set("size", String(params.size ?? 20));
  query.set("offset", String(params.offset ?? 0));
  query.set("sort", params.sort ?? "recent");
  return request<ScraperSearchResult>(`/scraper/search?${query.toString()}`);
}

export function getScraperJobs() {
  return request<ScraperStatus["scheduler"]>("/scraper/jobs");
}

export function reloadScraperJobs() {
  return request<ScraperStatus["scheduler"]>("/scraper/jobs/reload", withBody("POST"));
}
