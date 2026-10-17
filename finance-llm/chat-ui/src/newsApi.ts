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
  /** Contagem por tema da plataforma (`value` = id do tema). */
  themes?: NewsFacetBucket[];
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
  /** Tema da plataforma (contratação pública, contratos, fundos europeus…). */
  theme?: string;
  publisher?: string;
  sentiment?: string;
  start?: string;
  end?: string;
  analyzed?: boolean;
  sort?: "recent" | "oldest" | "relevance";
  page?: number;
  size?: number;
};

/** Um tema da plataforma: o que a pesquisa filtra e o que os botões mostram. */
export type NewsTheme = {
  id: string;
  label: string;
  description: string;
  terms: string[];
  tags: string[];
  category: string;
};

/** O que a publicação de uma notícia no blog devolve. */
export type NewsPublishResult = {
  saved: boolean;
  /** Verdadeiro quando a notícia já tinha artigo: o `artigo` é o que existe. */
  duplicado: boolean;
  artigo: { id: string; title: string; slug: string; status: string };
  /** Caminho do editor do blog (`/cms/blog?id=…`). */
  url: string;
  tema?: string | null;
  /** Verdadeiro quando o artigo ficou em português por tradução de IA. */
  traduzido?: boolean;
  ia?: NewsAiInfo;
  /** Aviso quando a tradução não foi possível (o artigo sai com o original). */
  aviso?: string;
  /** Capa do artigo: o id do media guardado no CMS e o URL de onde veio a imagem. */
  capa?: { id: string; origem: string } | null;
  /** Porque é que o artigo ficou sem capa (a imagem da notícia não serviu). */
  aviso_capa?: string;
  resumo: string;
};

/** Fornecedor/modelo de IA que fez a tradução (o configurado na plataforma). */
export type NewsAiInfo = {
  provider?: string;
  provider_label?: string;
  model?: string;
};

/** Resultado de traduzir uma notícia para PT. */
export type NewsTranslationResult = {
  id: string;
  /** Título em português (igual ao original quando já estava em PT). */
  titulo: string;
  resumo: string;
  original_titulo: string;
  original_resumo: string;
  traduzido: boolean;
  /** Verdadeiro quando a tradução ficou guardada na ficha da notícia. */
  guardada: boolean;
  ia?: NewsAiInfo;
  status?: { cached?: number; path?: string };
  resumo_curto: string;
};

/** Campos que a publicação aceita (o `id` da notícia chega; o resto é opcional). */
export type NewsPublishPayload = {
  id: string;
  theme?: string;
  title?: string;
  excerpt?: string;
  markdown?: string;
  tags?: string[];
  category_ids?: string[];
  /** Traduzir para PT antes de escrever o artigo (por omissão, sim). */
  traduzir?: boolean;
  provider?: string;
  model?: string;
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
 * filtro — incluindo `themes`, a contagem de cada tema da plataforma, calculada
 * sem o tema ativo (para se poder saltar de um para o outro).
 */
export function searchNews(filters: NewsSearchFilters = {}) {
  const query = new URLSearchParams();
  if (filters.q) query.set("q", filters.q);
  if (filters.tickers?.length) query.set("tickers", filters.tickers.join(","));
  if (filters.topic) query.set("topic", filters.topic);
  if (filters.theme) query.set("theme", filters.theme);
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

/** Temas da plataforma (contratação pública, contratos, fundos europeus…). */
export function getNewsThemes() {
  return request<{ total: number; items: NewsTheme[] }>("/news/themes");
}

/**
 * Traduz uma notícia para português com o **fornecedor de IA configurado**.
 *
 * O que a notícia já tiver em PT (tradução do NLP da recolha) não volta ao
 * modelo. Com `guardar` (por omissão), a tradução fica na ficha da notícia — o
 * cartão passa a mostrá-la sem repetir a chamada. Sem fornecedor configurado a
 * resposta é 409 com a instrução para o definir em Definições → Fornecedores de IA.
 */
export function translateNews(
  id: string,
  payload: { provider?: string; model?: string; guardar?: boolean } = {},
) {
  return request<NewsTranslationResult>(`/news/${encodeURIComponent(id)}/traduzir`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * Publica uma notícia no blog como **artigo rascunho**.
 *
 * Basta o `id` da notícia: o servidor lê-a do índice, **traduz para PT** com o
 * fornecedor de IA configurado quando ela ainda não tiver tradução, e escreve o
 * título, o resumo, a fonte e a ligação para o original. A mesma notícia não dá
 * dois artigos — a segunda chamada devolve o que já existe (`duplicado: true`).
 */
export function publishNewsAsPost(payload: NewsPublishPayload) {
  return request<NewsPublishResult>("/news/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
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
