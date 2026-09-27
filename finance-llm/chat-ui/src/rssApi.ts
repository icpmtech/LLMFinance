/**
 * Cliente do leitor de RSS do IQ OS (`/rss/*`).
 *
 * O leitor trata de **fontes** (feeds RSS/Atom) agrupadas em **pastas** e dos
 * **artigos** recolhidos, com os estados lido/favorito/guardado. As integrações
 * levam um artigo ao Office, ao sentimento, ao CRM e ao RAG, e a IA resume um
 * artigo ou prepara um boletim.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------ tipos */

export type RssFeedStatus = "nunca" | "ok" | "sem_novidades" | "nao_modificado" | "erro";

export type RssFolder = {
  id: string;
  name: string;
  color: string;
  order: number;
  feeds?: number;
  unread?: number;
  created_at?: string;
  updated_at?: string;
};

export type RssFeed = {
  id: string;
  url: string;
  title: string;
  site_url?: string;
  description?: string;
  language?: string;
  icon_url?: string;
  folder_id?: string | null;
  folder_name?: string;
  tags: string[];
  enabled: boolean;
  articles?: number;
  unread?: number;
  last_fetch_at?: string | null;
  last_status?: RssFeedStatus;
  last_status_label?: string;
  last_error?: string;
  status_label?: string;
  status_tone?: string;
  etag?: string;
  last_modified?: string;
  added_by?: string;
  created_at?: string;
  updated_at?: string;
};

export type RssArticle = {
  id: string;
  feed_id: string;
  feed_title?: string;
  feed_icon?: string;
  folder_id?: string | null;
  guid?: string;
  title: string;
  url?: string;
  author?: string;
  summary?: string;
  content?: string;
  digest?: string;
  digest_at?: string | null;
  has_digest?: boolean;
  published_at?: string | null;
  fetched_at?: string;
  image_url?: string;
  categories?: string[];
  /** Etiquetas do artigo (editáveis). */
  tags?: string[];
  /** Etiquetas herdadas da fonte (não editáveis aqui). */
  feed_tags?: string[];
  read: boolean;
  favorite: boolean;
  saved: boolean;
  reading_minutes?: number;
  has_content?: boolean;
  feed_url?: string;
  feed_site_url?: string;
  /** Só nos artigos relacionados. */
  score?: number;
};

export type RssSettings = {
  auto_fetch: boolean;
  cron: string;
  timezone: string;
  max_articles_per_feed: number;
  retention_days: number;
  mark_read_on_open: boolean;
  default_tags: string[];
  rules: RssRule[];
};

/** Regra automática: termo encontrado no artigo → ações e etiquetas. */
export type RssRule = {
  id: string;
  term: string;
  actions: string[];
  tags: string[];
  enabled: boolean;
  hits?: number;
  created_at?: string;
};

export type RssTag = { tag: string; feeds: number; articles: number };

export type RssSeriesPoint = { day: string; articles: number };

export type RssSchedule = {
  running: boolean;
  error?: string | null;
  job_id?: string;
  scheduled?: boolean;
  cron: string;
  timezone: string;
  auto_fetch: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_result?: Record<string, unknown> | null;
  settings?: RssSettings;
};

export type RssOverview = {
  feeds: { total: number; enabled: number; with_error: number; last_fetch_at?: string | null };
  folders: number;
  articles: { total: number; unread: number; favorite: number; saved: number; tagged: number; today: number; week: number };
  series: RssSeriesPoint[];
  top_feeds: RssFeed[];
  rules: RssRule[];
  per_feed: RssFeed[];
  recent: RssArticle[];
  activity: { id: string; action: string; subject: string; actor: string; detail: string; at: string }[];
  settings: RssSettings;
  trending: { term: string; articles: number }[];
  schedule: RssSchedule;
  folders_detail: RssFolder[];
};

export type RssCatalogue = {
  folders: RssFolder[];
  feeds: RssFeed[];
  tags: string[];
  status_labels: Record<string, string>;
  status_tones: Record<string, string>;
  colors: string[];
  settings: RssSettings;
  defaults: RssSettings;
  limits: { max_articles_per_feed: number; retention_days: number; summary_chars: number; rules: number };
  rule_actions: { id: string; label: string }[];
  totals: { feeds: number; folders: number; articles: number; unread: number; favorite: number; saved: number };
  suggestions: string[];
};

export type RssSuggestion = {
  id: string;
  title: string;
  url: string;
  site_url?: string;
  category: string;
  language?: string;
  hint?: string;
  tags?: string[];
  subscribed: boolean;
};

export type RssArticleList = {
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  unread: number;
  unread_by_feed: Record<string, number>;
  items: RssArticle[];
};

export type RssSearchHit = {
  kind: "article" | "feed";
  id: string;
  title: string;
  subtitle: string;
  published_at?: string | null;
  read?: boolean;
  unread?: number;
};

export type RssArticleFilters = {
  feed_id?: string | null;
  folder_id?: string | null;
  q?: string | null;
  unread?: boolean | null;
  favorite?: boolean | null;
  saved?: boolean | null;
  tag?: string | null;
  since?: string | null;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type RssSentimentResult = {
  ok: boolean;
  analysis: Record<string, unknown>;
  title?: string;
  url?: string;
};

export type RssAiInfo = { provider?: string; provider_label?: string; model?: string };

/* --------------------------------------------------------------- pedidos */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
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

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, typeof value === "boolean" ? (value ? "true" : "false") : String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/* -------------------------------------------------------------- catálogo */

export const getRssCatalogue = () => request<RssCatalogue>("/rss/catalogue");
export const getRssOverview = () => request<RssOverview>("/rss/overview");
export const searchRss = (q: string, limit = 30) => request<{ query: string; items: RssSearchHit[] }>(`/rss/search${queryString({ q, limit })}`);

/* ----------------------------------------------------------------- pastas */

export const listRssFolders = () => request<{ total: number; items: RssFolder[] }>("/rss/folders");
export const createRssFolder = (payload: Partial<RssFolder>) =>
  request<{ saved: boolean; folder: RssFolder }>("/rss/folders", withBody("POST", payload));
export const patchRssFolder = (folderId: string, payload: Partial<RssFolder>) =>
  request<{ saved: boolean; folder: RssFolder }>(`/rss/folders/${encodeURIComponent(folderId)}`, withBody("PATCH", payload));
export const deleteRssFolder = (folderId: string) =>
  request<{ deleted: boolean; feeds_moved: number }>(`/rss/folders/${encodeURIComponent(folderId)}`, { method: "DELETE" });

/* ----------------------------------------------------------------- fontes */

export const listRssFeeds = (folderId?: string | null, q?: string) =>
  request<{ total: number; items: RssFeed[] }>(`/rss/feeds${queryString({ folder_id: folderId, q })}`);
export const getRssFeed = (feedId: string) => request<{ feed: RssFeed }>(`/rss/feeds/${encodeURIComponent(feedId)}`);
export const createRssFeed = (payload: { url: string; folder_id?: string | null; title?: string; tags?: string[]; fetch?: boolean; discover?: boolean }) =>
  request<{ ok: boolean; feed: RssFeed; added: number; feed_url: string; discovered: boolean; candidates: string[]; error?: string }>(
    "/rss/feeds",
    withBody("POST", payload),
  );
export const patchRssFeed = (feedId: string, payload: Partial<RssFeed>) =>
  request<{ saved: boolean; feed: RssFeed }>(`/rss/feeds/${encodeURIComponent(feedId)}`, withBody("PATCH", payload));
export const deleteRssFeed = (feedId: string) =>
  request<{ deleted: boolean; articles_removed: number }>(`/rss/feeds/${encodeURIComponent(feedId)}`, { method: "DELETE" });
export const fetchRssFeed = (feedId: string, force = false) =>
  request<{ status: string; added: number; updated: number; articles?: number; error?: string | null; feed: RssFeed }>(
    `/rss/feeds/${encodeURIComponent(feedId)}/fetch${queryString({ force })}`,
    { method: "POST" },
  );
export const fetchAllRssFeeds = (force = false) =>
  request<{ feeds: number; added: number; errors: number; items: { feed_id: string; title: string; status: string; added: number; error?: string | null }[] }>(
    `/rss/fetch${queryString({ force })}`,
    { method: "POST" },
  );
export const readAllRssFeedArticles = (feedId: string) =>
  request<{ updated: number }>(`/rss/feeds/${encodeURIComponent(feedId)}/read-all`, { method: "POST" });
export const purgeReadRssFeedArticles = (feedId: string) =>
  request<{ removed: number }>(`/rss/feeds/${encodeURIComponent(feedId)}/purge-read`, { method: "POST" });

/* ---------------------------------------------------------------- artigos */

export const listRssArticles = (filters: RssArticleFilters = {}) => request<RssArticleList>(`/rss/articles${queryString(filters)}`);
export const getRssArticle = (articleId: string, markRead = false) =>
  request<{ article: RssArticle; related: RssArticle[] }>(`/rss/articles/${encodeURIComponent(articleId)}${queryString({ mark_read: markRead })}`);
export const patchRssArticle = (articleId: string, payload: { read?: boolean; favorite?: boolean; saved?: boolean; tags?: string[] }) =>
  request<{ saved: boolean; article: RssArticle }>(`/rss/articles/${encodeURIComponent(articleId)}`, withBody("PATCH", payload));
export const relatedRssArticles = (articleId: string, limit = 5) =>
  request<{ total: number; items: RssArticle[] }>(`/rss/articles/${encodeURIComponent(articleId)}/related${queryString({ limit })}`);
export const readAllRssArticles = (payload: { feed_id?: string | null; folder_id?: string | null; q?: string | null } = {}) =>
  request<{ updated: number }>("/rss/articles/read-all", withBody("POST", payload));
export const purgeReadRssArticles = (payload: { feed_id?: string | null } = {}) =>
  request<{ removed: number }>("/rss/articles/purge-read", withBody("POST", payload));

/* ------------------------------------------------------------ integrações */

export const rssArticleToOffice = (articleId: string) =>
  request<{ ok: boolean; document_id: string; document: { id: string; title: string } }>(
    `/rss/articles/${encodeURIComponent(articleId)}/office`,
    { method: "POST" },
  );
export const rssArticleSentiment = (articleId: string) =>
  request<RssSentimentResult>(`/rss/articles/${encodeURIComponent(articleId)}/sentiment`, { method: "POST" });
export const rssArticleToCrm = (articleId: string, accountId?: string | null) =>
  request<{ ok: boolean; item: { id: string; subject: string } }>(
    `/rss/articles/${encodeURIComponent(articleId)}/crm`,
    withBody("POST", { account_id: accountId ?? null }),
  );
export const rssArticleToRag = (articleId: string) =>
  request<{ ok: boolean; doc_id: string; chunks: number; title: string }>(`/rss/articles/${encodeURIComponent(articleId)}/rag`, { method: "POST" });
export const rssArticleDigest = (articleId: string, provider?: string, model?: string) =>
  request<{ ok: boolean; digest: string; ai?: RssAiInfo; title?: string }>(
    `/rss/articles/${encodeURIComponent(articleId)}/digest`,
    withBody("POST", { provider, model }),
  );
export const rssDigestCollection = (payload: {
  article_ids?: string[];
  feed_id?: string | null;
  folder_id?: string | null;
  q?: string | null;
  unread?: boolean;
  limit?: number;
  provider?: string;
  model?: string;
  save_to_office?: boolean;
}) =>
  request<{ ok: boolean; digest: string; markdown: string; articles: number; article_ids: string[]; ai?: RssAiInfo; office?: { ok: boolean; document_id?: string; error?: string } }>(
    "/rss/articles/digest",
    withBody("POST", payload),
  );

/* ------------------------------------------------------ OPML e sugestões */

export const rssOpmlUrl = () => `${API_BASE}/rss/opml`;

export const importRssOpml = (opml: string, folderId?: string | null, fetchLimit = 12) =>
  request<{ ok: boolean; folders_created: number; feeds_created: number; fetched: number; pending: number; skipped_total: number }>(
    "/rss/opml/import",
    withBody("POST", { opml, folder_id: folderId ?? null, fetch_limit: fetchLimit }),
  );

export const getRssSuggestions = () =>
  request<{ categories: string[]; total: number; items: RssSuggestion[] }>("/rss/suggestions");

export const subscribeRssSuggestions = (payload: { ids?: string[]; urls?: string[]; folder_id?: string | null }) =>
  request<{ subscribed: number; failed: string[]; items: { ok: boolean; feed?: RssFeed; error?: string }[] }>(
    "/rss/suggestions/subscribe",
    withBody("POST", payload),
  );

/* ---------------------------------------------------- regras e etiquetas */

export const getRssRules = () =>
  request<{ total: number; items: RssRule[]; actions: { id: string; label: string }[] }>("/rss/rules");
export const saveRssRules = (rules: RssRule[], applyNow = false) =>
  request<{ saved: boolean; rules: RssRule[]; applied: number; matched: number }>("/rss/rules", withBody("PUT", { rules, apply_now: applyNow }));
export const applyRssRules = (onlyUnread = true) =>
  request<{ applied: number; matched: number }>("/rss/rules/apply", withBody("POST", { only_unread: onlyUnread }));
export const getRssTags = () => request<{ total: number; items: RssTag[] }>("/rss/tags");

/* ------------------------------------------------------------- exportação */

/** Ligação de descarregamento dos artigos (CSV para Excel, Markdown para ler). */
export function rssExportUrl(filters: RssArticleFilters = {}, format: "csv" | "md" = "csv"): string {
  return `${API_BASE}/rss/export${queryString({ ...filters, format })}`;
}

/* ---------------------------------------------------------------- agenda */

export const getRssSchedule = () => request<RssSchedule>("/rss/schedule");
export const saveRssSchedule = (payload: Partial<RssSettings>) =>
  request<{ saved: boolean; settings: RssSettings; schedule: RssSchedule }>("/rss/schedule", withBody("PUT", payload));
export const reloadRssSchedule = () => request<RssSchedule>("/rss/schedule/reload", { method: "POST" });

/* ------------------------------------------------------------- utilidades */

/** Endereço do sítio de onde veio a fonte (para mostrar sem o esquema). */
export function rssHost(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return String(url).replace(/^https?:\/\//, "").split("/")[0];
  }
}
