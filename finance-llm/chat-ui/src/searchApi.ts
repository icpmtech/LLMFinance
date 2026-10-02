/**
 * Cliente da pesquisa unificada (`/search/*`) — a pesquisa «estilo Google» do IQ OS.
 *
 * Uma pergunta, resultados de todas as áreas: dados recolhidos (scraping),
 * contratos públicos (Portugal e Espanha), entidades de Espanha (órgãos
 * adjudicantes e empresas adjudicatárias), empresas, marcas, firmas, notícias de
 * mercado (`finance_news`), imprensa recolhida dos jornais, tickers e CRM (este
 * último só com sessão, porque é privado por utilizador).
 */
import { API_BASE } from "./api";

export type SearchScopeId =
  | "all"
  | "scraped"
  | "social"
  | "contracts"
  | "contracts_es"
  | "entities_es"
  | "entities"
  | "pessoas"
  | "politicos"
  | "wikipedia"
  | "trademarks"
  | "firmas"
  | "news"
  | "imprensa"
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
  /** Imagem do item (itens recolhidos trazem a que a fonte extraiu). */
  image?: string;
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
  /** Jornais/fontes pelo nome legível (com o `source_id` para filtrar). */
  publishers?: { key: string; count: number; id?: string }[];
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
  /**
   * Facetas com contagem para o painel de filtros do âmbito (ex.: tipo de
   * publicação nas redes, partido nos políticos, jornal na imprensa). Cada
   * valor leva `key` (o que se filtra) e `label` (o que se lê).
   */
  filters?: SearchFilter[];
};

export type SearchFilterValue = { key: string; label?: string; count: number };

export type SearchFilter = { name: string; label: string; values: SearchFilterValue[] };

export type UnifiedSearchResult = {
  query: string;
  scope: SearchScopeId;
  size: number;
  offset: number;
  /** Filtros ativos (nome → valor), como foram enviados. */
  filters?: Record<string, string>;
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
  /**
   * Filtros (facetas) do âmbito, ex.: `{ tipo: "video" }` nas redes sociais ou
   * `{ partido: "PS" }` nos políticos.
   */
  filters?: Record<string, string> | null;
}) {
  const query = new URLSearchParams();
  query.set("q", params.q ?? "");
  query.set("scope", params.scope ?? "all");
  query.set("size", String(params.size ?? 8));
  query.set("offset", String(params.offset ?? 0));
  if (params.filters && Object.keys(params.filters).length) {
    query.set("filters", JSON.stringify(params.filters));
  }
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
