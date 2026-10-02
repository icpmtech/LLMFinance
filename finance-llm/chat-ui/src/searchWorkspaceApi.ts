/**
 * Portfólio da Pesquisa total: pesquisas guardadas, favoritos e ferramentas de
 * análise da pesquisa (custos, ontologia e relatórios).
 *
 * As escritas exigem sessão (o portfólio é de quem o faz); as leituras são
 * públicas mas devolvem só o que é do utilizador quando há sessão. O token vai no
 * cabeçalho `Authorization`, injetado pelo `installAuthFetch` — por isso aqui usa-se
 * `fetch` normal, como nos outros clientes da plataforma.
 */
import { API_BASE } from "./api";

export type SavedSearch = {
  id: string;
  name: string;
  query: string;
  scope: string;
  filters: Record<string, string>;
  description?: string;
  results_total?: number | null;
  owner_id?: string | null;
  created_at?: string | null;
  last_run_at?: string | null;
};

export type FavoriteEntry = {
  kind: string;
  id: string;
  label: string;
  sublabel?: string | null;
  url?: string | null;
  open?: { view: string; arg: string; mode?: string } | null;
  added_at?: string | null;
};

export type AnalysisBucket = {
  key: string;
  count: number;
  total_value: number;
  description?: string | null;
};

export type LinkedCompany = {
  nif: string;
  name: string;
  contracts_total?: number | null;
  total_value?: number | null;
  contracts_in_search?: number;
  value_in_search?: number;
  adjudicante?: boolean;
  adjudicatario?: boolean;
};

export type LinkedPerson = {
  nif: string;
  name: string;
  role?: string;
  company_nif?: string;
  company_name?: string;
  source?: string;
};

export type ContractsAnalysis = {
  query: string;
  generated_at: string;
  totals: {
    contracts: number;
    value: number;
    contracts_pt: number;
    value_pt: number;
    contracts_es: number;
    value_es: number;
    avg_value: number;
    max_value: number;
    distinct_adjudicantes: number;
    distinct_adjudicatarios: number;
  };
  by_year: AnalysisBucket[];
  by_cpv: AnalysisBucket[];
  value_distribution: AnalysisBucket[];
  procedure_types: AnalysisBucket[];
  contract_types: AnalysisBucket[];
  top_adjudicatarios: AnalysisBucket[];
  top_adjudicantes: AnalysisBucket[];
  linked: { companies: LinkedCompany[]; people: LinkedPerson[] };
  caveats: string[];
};

export type SearchGraphNode = {
  id: string;
  label: string;
  type: string;
  type_label: string;
  scope?: string | null;
  subtitle?: string;
  url?: string;
  nif?: string;
  value?: number | null;
  depth?: number;
};

export type SearchGraphEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  kind: string;
  weight?: number;
};

export type SearchGraph = {
  term: string;
  scope: string;
  nodes: SearchGraphNode[];
  edges: SearchGraphEdge[];
  legend: { type: string; label: string; style: string }[];
  totals: { nodes: number; edges: number; by_type: Record<string, number>; results: number };
  mermaid: string;
  caveats?: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
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

/* ------------------------------------------------------------- portfólio */

export function fetchPortfolio(): Promise<{ items: SavedSearch[]; total: number }> {
  return request("/search/portfolio");
}

export function savePortfolio(payload: {
  name?: string;
  query: string;
  scope?: string;
  filters?: Record<string, string>;
  description?: string;
  results_total?: number;
}): Promise<{ ok: boolean; id: string; name: string }> {
  return request("/search/portfolio", { method: "POST", body: JSON.stringify(payload) });
}

export function deletePortfolio(itemId: string): Promise<{ ok: boolean }> {
  return request(`/search/portfolio/${encodeURIComponent(itemId)}`, { method: "DELETE" });
}

/* ------------------------------------------------------------- favoritos */

export function fetchFavorites(): Promise<{ items: FavoriteEntry[]; total: number }> {
  return request("/search/favorites");
}

export function fetchFavoriteKeys(): Promise<{ keys: string[]; total: number }> {
  return request("/search/favorites/check");
}

export function saveFavorite(item: {
  kind: string;
  id: string;
  label: string;
  sublabel?: string;
  url?: string;
  open?: { view: string; arg: string; mode?: string } | null;
}): Promise<{ ok: boolean }> {
  return request("/search/favorites", { method: "POST", body: JSON.stringify(item) });
}

export function deleteFavorite(kind: string, itemId: string): Promise<{ ok: boolean }> {
  return request(`/search/favorites/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`, {
    method: "DELETE",
  });
}

/* ------------------------------------------- análise, ontologia e relatórios */

export function getContractsAnalysis(params: {
  q: string;
  top?: number;
  links?: boolean;
}): Promise<ContractsAnalysis> {
  const query = new URLSearchParams({
    q: params.q,
    top: String(params.top ?? 8),
    links: String(params.links ?? true),
  });
  return request(`/search/analysis/contracts?${query.toString()}`);
}

export function getSearchGraph(params: {
  q: string;
  scope?: string;
  filters?: Record<string, string>;
  size?: number;
}): Promise<SearchGraph> {
  const query = new URLSearchParams({
    q: params.q,
    scope: params.scope ?? "all",
    size: String(params.size ?? 12),
  });
  if (params.filters && Object.keys(params.filters).length) {
    query.set("filters", JSON.stringify(params.filters));
  }
  return request(`/search/graph?${query.toString()}`);
}

export type SearchChatSource = {
  n: number;
  title: string;
  subtitle?: string;
  scope?: string;
  url?: string;
  value?: number | null;
};

export type SearchChatAnswer = {
  question: string;
  answer: string | null;
  provider?: string | null;
  model?: string | null;
  sources?: SearchChatSource[];
  context_items?: number;
  analysis_included?: boolean;
  caveats?: string[];
  error?: string;
};

export type SearchChatStatus = {
  available: boolean;
  provider?: string | null;
  model?: string | null;
  note?: string | null;
};

/** Fornecedor de IA que responderá ao chat desta pesquisa. */
export function getSearchChatStatus(): Promise<SearchChatStatus> {
  return request("/search/chat/status");
}

/** Pergunta ao chat de IA sobre os resultados da pesquisa. */
export function askSearchChat(params: {
  q: string;
  question: string;
  scope?: string;
  filters?: Record<string, string>;
  history?: { role: "user" | "assistant"; content: string }[];
  includeAnalysis?: boolean;
}): Promise<SearchChatAnswer> {
  return request("/search/chat", {
    method: "POST",
    body: JSON.stringify({
      q: params.q,
      question: params.question,
      scope: params.scope ?? "all",
      filters: params.filters ?? {},
      history: params.history ?? [],
      include_analysis: params.includeAnalysis ?? true,
    }),
  });
}

/** Gera e descarrega o relatório da pesquisa (PDF ou Excel). */
export async function downloadSearchReport(
  format: "pdf" | "excel",
  params: { q: string; limit?: number },
): Promise<void> {
  const response = await fetch(`${API_BASE}/search/report/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ q: params.q, limit: params.limit }),
  });
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
  const blob = await response.blob();
  const header = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(header);
  const filename = match?.[1] ?? `pesquisa.${format === "pdf" ? "pdf" : "xlsx"}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}
