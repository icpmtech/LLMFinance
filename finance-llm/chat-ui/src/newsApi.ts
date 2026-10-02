/**
 * Cliente do módulo de notícias do IQ OS (`/news/*`).
 *
 * Duas coisas: **recolher** notícias para o Elasticsearch (por ticker e por tema)
 * e **pesquisar** as que já lá estão, com filtros e facetas. Tudo entra no índice
 * `finance_news`, o mesmo que o sentimento de mercado, a Pesquisa total e o RAG
 * usam — recolher aqui alimenta também esses módulos.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------ tipos */

/** Uma notícia indexada (os campos variam conforme passou ou não pelo NLP). */
export type NewsDoc = {
  id: string;
  ticker: string;
  topic?: string | null;
  title: string;
  summary?: string | null;
  publisher?: string | null;
  published?: string | null;
  url?: string | null;
  source?: string | null;
  ingested_at?: string | null;
  analyzed_at?: string | null;
  sentiment?: string | null;
  language?: string | null;
  translated_title?: string | null;
  translated_summary?: string | null;
  summary_pt?: string | null;
  topics?: string[];
  entities?: { name: string; type?: string }[];
  score?: number | null;
};

/** Valor + contagem de uma faceta (ticker, fonte, tema, sentimento ou dia). */
export type NewsFacetBucket = { value: string | null; count: number };

export type NewsFacets = {
  tickers: NewsFacetBucket[];
  publishers: NewsFacetBucket[];
  sentiments: NewsFacetBucket[];
  topics: NewsFacetBucket[];
  labels: NewsFacetBucket[];
  days: NewsFacetBucket[];
};

export type NewsSearchResult = {
  total: number;
  page: number;
  size: number;
  pages: number;
  items: NewsDoc[];
  facets: NewsFacets;
  error?: string;
};

export type NewsStats = {
  index: string;
  documents: number;
  tickers: number;
  publishers: number;
  analyzed: number;
  analyzed_share: number | null;
  with_sentiment: number;
  sentiments: NewsFacetBucket[];
  topics: NewsFacetBucket[];
  top_tickers: NewsFacetBucket[];
  top_publishers: NewsFacetBucket[];
  first_published?: string | null;
  last_published?: string | null;
  last_ingest?: string | null;
  error?: string;
};

export type NewsSearchFilters = {
  q?: string;
  tickers?: string[];
  topic?: string;
  publisher?: string;
  sentiment?: string;
  start?: string;
  end?: string;
  analyzed?: boolean;
  sort?: "recent" | "oldest" | "relevance";
  page?: number;
  size?: number;
};

/** Resultado da recolha de um alvo (um ticker ou um tema). */
export type NewsCollectTarget = {
  target: string;
  kind: "ticker" | "topic";
  indexed: number;
  total: number;
  analyzed: number;
  error?: string | null;
};

export type NewsCollectResult = {
  ok: boolean;
  tickers: string[];
  topics: string[];
  max_items: number;
  indexed: number;
  analyzed: number;
  results: NewsCollectTarget[];
  stats: NewsStats;
};

/* ---------------------------------------------------------------- pedidos */

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

/* -------------------------------------------------------------- pesquisa */

/**
 * Pesquisa nas notícias indexadas. As facetas vêm calculadas sobre o **mesmo**
 * filtro, pelo que os números dos filtros correspondem sempre ao que está à vista.
 */
export function searchNews(filters: NewsSearchFilters = {}) {
  const query = new URLSearchParams();
  if (filters.q) query.set("q", filters.q);
  if (filters.tickers?.length) query.set("tickers", filters.tickers.join(","));
  if (filters.topic) query.set("topic", filters.topic);
  if (filters.publisher) query.set("publisher", filters.publisher);
  if (filters.sentiment) query.set("sentiment", filters.sentiment);
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  if (filters.analyzed !== undefined) query.set("analyzed", filters.analyzed ? "true" : "false");
  query.set("sort", filters.sort ?? "recent");
  query.set("page", String(filters.page ?? 1));
  query.set("size", String(filters.size ?? 20));
  return request<NewsSearchResult>(`/news/search?${query.toString()}`);
}

/** Panorama do índice de notícias (volume, tickers, fontes, janela, análise). */
export function getNewsStats() {
  return request<NewsStats>("/news/stats");
}

/**
 * Recolhe notícias do Yahoo para o Elasticsearch.
 *
 * Sem `tickers` nem `topics`, o servidor usa os **favoritos** guardados no painel
 * de mercado. Por ticker a notícia leva o NLP completo; por tema, o léxico bilingue.
 */
export function collectNews(payload: { tickers?: string[]; topics?: string[]; max_items?: number } = {}) {
  return request<NewsCollectResult>("/news/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** URL do índice, para ligar ao Elasticsearch a partir do módulo. */
export const newsIndexName = "finance_news";
