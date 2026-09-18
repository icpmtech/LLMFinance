/**
 * Cliente do módulo **Pesquisa 360** (`/search360/*`).
 *
 * O metamodelo de análise e exploração: federa as fontes da plataforma
 * (Elasticsearch + ontologia) com a Wikipédia, Wikidata, Banco Mundial,
 * dados.gov.pt, OpenAlex, Crossref e a web aberta, e devolve tudo na mesma
 * forma — resultados normalizados, dossiê do tema, biblioteca de pastas e
 * ficheiros, grafo de navegação, indicadores e síntese com citações.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type Search360Source = {
  id: string;
  label: string;
  family: string;
  description: string;
  icon: string;
  accent: string;
  kinds: string[];
  capabilities: string[];
  requires_key: boolean;
  default?: boolean;
  available?: boolean;
  engines?: string[];
};

export type Search360Meta = {
  sources: Search360Source[];
  indexes: { index: string; label: string; kind: string; documents: number }[];
  cache: { entries: number; ttl_seconds: number };
  families: string[];
  about: { name: string; description: string; capabilities: string[] };
};

export type Search360Item = {
  id: string;
  source_id: string;
  source_label: string;
  source_family: string;
  kind: string;
  title: string;
  subtitle?: string | null;
  snippet?: string | null;
  url?: string | null;
  date?: string | null;
  icon: string;
  badges: string[];
  score: number;
  also_in?: string[];
  data: Record<string, unknown>;
};

export type Search360Plan = {
  term: string;
  strategy: "entidade" | "tema" | "investigação";
  keywords: string[];
  tickers: string[];
  nifs: string[];
  sources: string[];
  source_labels?: string[];
  steps: { source_id: string; label: string; family: string; why: string; capabilities: string[] }[];
  auto: boolean;
  macro_hint: boolean;
};

export type Search360Facets = Record<string, { value: string; count: number }[]>;

export type Search360SearchResult = {
  term: string;
  plan: Search360Plan;
  items: Search360Item[];
  facets: Search360Facets;
  per_source: { source_id: string; label: string; family: string; items: number; ms: number; ok: boolean }[];
  warnings: string[];
  entities: Record<string, unknown>[];
  stats: {
    items: number;
    sources_queried: number;
    sources_with_results: number;
    ms: number;
    by_kind?: { value: string; count: number }[];
  };
  generated_at: string;
  cached?: boolean;
};

export type Search360LibraryFolder = {
  id: string;
  label: string;
  icon: string;
  accent: string;
  count: number;
  subfolders: { id: string; label: string; kind: string; files: Search360LibraryFile[] }[];
};

export type Search360LibraryFile = {
  id: string;
  label: string;
  kind: string;
  icon: string;
  url?: string | null;
  date?: string | null;
  source_id: string;
  snippet?: string | null;
  badges: string[];
};

export type Search360GraphNode = {
  id: string;
  label: string;
  kind: string;
  depth: number;
  value: number;
  color: string;
  icon: string;
  source_id?: string | null;
  source_label?: string | null;
  url?: string | null;
  date?: string | null;
  snippet?: string | null;
};

export type Search360Graph = {
  term: string;
  nodes: Search360GraphNode[];
  edges: { source: string; target: string; label: string; value: number }[];
  legend: { kind: string; label: string; count: number; color: string }[];
  totals: { nodes: number; edges: number };
};

export type Search360Metric = {
  indicator: string;
  label: string;
  country: string;
  points: { year: number; value: number }[];
  first: { year: number; value: number };
  last: { year: number; value: number };
  change: number;
  change_pct: number | null;
  url?: string | null;
};

export type Search360Synthesis = {
  term: string;
  text: string;
  mode: "ai" | "factual" | "empty";
  backend: { kind: string; provider?: string | null; model?: string | null };
  evidence: { n: number; title: string; source: string; url?: string | null; date?: string | null; kind: string }[];
  notes: string[];
  warnings: string[];
};

export type Search360Topic = {
  term: string;
  plan: Search360Plan;
  items: Search360Item[];
  facets: Search360Facets;
  per_source: Search360SearchResult["per_source"];
  warnings: string[];
  stats: Search360SearchResult["stats"];
  library: { term: string; folders: Search360LibraryFolder[]; totals: { folders: number; files: number } };
  graph: Search360Graph;
  metrics: Search360Metric[];
  synthesis?: Search360Synthesis;
  generated_at: string;
  cached?: boolean;
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

function withBody(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/* ------------------------------------------------------------------- rotas */

export function getSearch360Meta(): Promise<Search360Meta> {
  return request<Search360Meta>("/search360/meta");
}

export function suggestSearch360(q: string, limit = 6): Promise<{ term: string; plan: Search360Plan; suggestions: { label: string; hint?: string; kind?: string; source?: string; value?: string }[] }> {
  return request(`/search360/suggest?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export function searchSearch360(options: {
  term: string;
  sources?: string[];
  limit?: number;
}): Promise<Search360SearchResult> {
  return request<Search360SearchResult>("/search360/search", withBody({ term: options.term, sources: options.sources, limit: options.limit ?? 6 }));
}

export function getSearch360Topic(options: {
  term: string;
  sources?: string[];
  limit?: number;
  country?: string;
  synthesis?: boolean;
  backend?: string;
}): Promise<Search360Topic> {
  return request<Search360Topic>(
    "/search360/topic",
    withBody({
      term: options.term,
      sources: options.sources,
      limit: options.limit ?? 6,
      country: options.country ?? "PRT",
      synthesis: options.synthesis ?? true,
      backend: options.backend,
    }),
  );
}

export function getSearch360Library(options: { term: string; sources?: string[]; limit?: number }): Promise<{
  term: string;
  folders: Search360LibraryFolder[];
  totals: { folders: number; files: number };
}> {
  return request("/search360/library", withBody({ term: options.term, sources: options.sources, limit: options.limit ?? 6 }));
}

export function getSearch360Graph(options: { term: string; sources?: string[]; limit?: number; nodes?: number }): Promise<Search360Graph> {
  return request<Search360Graph>("/search360/graph", withBody({ term: options.term, sources: options.sources, limit: options.limit ?? 6, nodes: options.nodes ?? 45 }));
}

export function getSearch360Synthesis(options: { term: string; sources?: string[]; limit?: number; country?: string; backend?: string }): Promise<Search360Synthesis> {
  return request<Search360Synthesis>(
    "/search360/ai/synthesis",
    withBody({ term: options.term, sources: options.sources, limit: options.limit ?? 6, country: options.country ?? "PRT", backend: options.backend }),
  );
}

/* ---------------------------------------------------- projetos e dossiês */

export type Search360Project = {
  id: string;
  name: string;
  description?: string | null;
  color?: string;
  tags?: string[];
  kind?: string;
  owner?: string | null;
  created_at?: string;
  updated_at?: string;
  dossier_count?: number;
};

export type Search360SavedDossier = {
  id: string;
  title: string;
  term?: string | null;
  project_id?: string | null;
  tags: string[];
  notes?: string | null;
  author?: string | null;
  created_at?: string;
  updated_at?: string;
  saved_at?: string | null;
  sources?: number | null;
  items?: number | null;
  metrics: number;
  evidence: number;
  synthesis_mode?: string | null;
  generated_at?: string | null;
};

export type Search360StoredDossier = Search360SavedDossier & {
  snapshot: Search360Topic;
  history?: { generated_at?: string; items?: number }[];
};

export function listSearch360Projects(): Promise<{ ontology: string; total: number; items: Search360Project[]; dossiers_total: number; dossiers_without_project: number }> {
  return request("/search360/projects");
}

export function saveSearch360Project(payload: {
  id?: string;
  name: string;
  description?: string;
  color?: string;
  tags?: string[];
}): Promise<{ saved: boolean; project: Search360Project }> {
  return request("/search360/projects", withBody(payload));
}

export function deleteSearch360Project(projectId: string): Promise<{ removed: boolean; id: string; dossiers_kept: number }> {
  return request(`/search360/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

export function listSearch360Dossiers(options: { projectId?: string; term?: string; limit?: number } = {}): Promise<{
  ontology: string;
  total: number;
  items: Search360SavedDossier[];
}> {
  const params = new URLSearchParams();
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.term) params.set("term", options.term);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return request(`/search360/dossiers${query ? `?${query}` : ""}`);
}

export function getSearch360Dossier(dossierId: string): Promise<Search360StoredDossier> {
  return request(`/search360/dossiers/${encodeURIComponent(dossierId)}`);
}

export function saveSearch360Dossier(payload: {
  id?: string;
  title?: string;
  term?: string;
  project_id?: string | null;
  tags?: string[];
  notes?: string;
  topic?: Search360Topic;
}): Promise<{ saved: boolean; dossier: Search360StoredDossier; summary: Search360SavedDossier }> {
  return request("/search360/dossiers", withBody(payload));
}

export function updateSearch360Dossier(
  dossierId: string,
  payload: { title?: string; notes?: string; tags?: string[]; project_id?: string | null },
): Promise<{ saved: boolean; dossier: Search360StoredDossier; summary: Search360SavedDossier }> {
  return request(`/search360/dossiers/${encodeURIComponent(dossierId)}`, { ...withBody(payload), method: "PATCH" });
}

export function refreshSearch360Dossier(dossierId: string): Promise<{
  updated: boolean;
  dossier: Search360StoredDossier;
  summary: Search360SavedDossier;
  previous_generated_at?: string | null;
}> {
  return request(`/search360/dossiers/${encodeURIComponent(dossierId)}/refresh`, withBody({}));
}

export function deleteSearch360Dossier(dossierId: string): Promise<{ removed: boolean; id: string }> {
  return request(`/search360/dossiers/${encodeURIComponent(dossierId)}`, { method: "DELETE" });
}

/** Endereço de exportação (abre no browser com o token da sessão no cabeçalho? não: descarrega pela API). */
export function search360DossierExportUrl(dossierId: string, format: "md" | "json" = "md"): string {
  return `${API_BASE}/search360/dossiers/${encodeURIComponent(dossierId)}/export?format=${format}`;
}

/* ---------------------------------------------------------------- utilidades */
/** Rótulo legível de um tipo de conteúdo (igual ao do servidor). */
export const KIND_LABELS: Record<string, string> = {
  entity: "Entidades",
  article: "Artigos",
  document: "Documentos",
  dataset: "Conjuntos de dados",
  metric: "Indicadores",
  news: "Notícias",
  file: "Ficheiros",
  topic: "Temas",
  summary: "Sínteses",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

/** Cor por tipo de conteúdo (a mesma do grafo do servidor). */
export const KIND_COLORS: Record<string, string> = {
  topic: "#38bdf8",
  entity: "#2dd4bf",
  article: "#94a3b8",
  document: "#93c5fd",
  dataset: "#fbbf24",
  metric: "#34d399",
  news: "#fb7185",
  file: "#a78bfa",
  summary: "#60a5fa",
};

/** Sugestões de temas para começar (mostradas quando não há pesquisa). */
export const TOPIC_STARTERS = [
  "energia renovável em Portugal",
  "contratos públicos de saúde",
  "obras públicas por região",
  "inflação em Portugal",
  "marcas registadas de tecnologia",
  "EDP",
];
