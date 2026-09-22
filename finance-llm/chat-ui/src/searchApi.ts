/**
 * Cliente da pesquisa unificada (`/search/*`) — a pesquisa «estilo Google» do IQ OS.
 *
 * Uma pergunta, resultados de todas as áreas: dados recolhidos (scraping),
 * contratos públicos (Portugal e Espanha), entidades de Espanha (órgãos
 * adjudicantes e empresas adjudicatárias), empresas, marcas, firmas, notícias de
 * mercado, tickers e CRM (este último só com sessão, porque é privado por
 * utilizador).
 */
import { API_BASE } from "./api";

export type SearchScopeId =
  | "all"
  | "scraped"
  | "contracts"
  | "contracts_es"
  | "entities_es"
  | "entities"
  | "trademarks"
  | "firmas"
  | "news"
  | "market"
  | "crm";

export type SearchScope = { id: SearchScopeId; label: string; hint?: string; session?: boolean };

export type SearchItem = {
  scope: Exclude<SearchScopeId, "all">;
  id: string;
  title: string;
  subtitle: string;
  snippet: string;
  url: string;
  date: string | null;
  badges: string[];
  extra: Record<string, unknown>;
  /**
   * Vista interna que abre este resultado. `mode` distingue o que se leva à
   * app de destino (ex.: `organo`/`adjudicatario` nos contratos de Espanha,
   * onde o argumento é o **nome** da entidade e não o id de um documento).
   */
  open: { view: string; arg: string; mode?: string } | null;
  score?: number | null;
};

export type SearchFacets = {
  sources?: { key: string; count: number }[];
  tags?: { key: string; count: number }[];
  days?: { key: string; count: number }[];
};

export type SearchGroup = {
  scope: Exclude<SearchScopeId, "all">;
  label: string;
  total: number;
  items: SearchItem[];
  took_ms: number;
  error: string | null;
  facets?: SearchFacets;
};

export type UnifiedSearchResult = {
  query: string;
  scope: SearchScopeId;
  size: number;
  offset: number;
  took_ms: number;
  total: number;
  groups: SearchGroup[];
  scopes: SearchScope[];
  facets: SearchFacets;
  error?: string;
};

export type SearchSuggestion = {
  text: string;
  scope: SearchScopeId;
  hint?: string;
  arg?: string;
  kind?: string;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
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

export function unifiedSearch(params: {
  q: string;
  scope?: SearchScopeId;
  size?: number;
  offset?: number;
}) {
  const query = new URLSearchParams();
  query.set("q", params.q ?? "");
  query.set("scope", params.scope ?? "all");
  query.set("size", String(params.size ?? 8));
  query.set("offset", String(params.offset ?? 0));
  return request<UnifiedSearchResult>(`/search/unified?${query.toString()}`);
}

export function searchSuggest(q: string, limit = 8) {
  const query = new URLSearchParams({ q, limit: String(limit) });
  return request<{ query: string; items: SearchSuggestion[] }>(`/search/suggest?${query.toString()}`);
}

export function searchScopes() {
  return request<{ items: SearchScope[] }>("/search/scopes");
}

/** Ligações externas de recurso, quando não há resultados internos. */
export function externalSearchUrl(q: string) {
  return `https://duckduckgo.com/?q=${encodeURIComponent(q)}`;
}
