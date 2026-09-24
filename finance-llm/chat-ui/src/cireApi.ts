/**
 * Cliente do módulo CIRE (`/cire/*`) — insolvências e revitalizações de empresas.
 *
 * Fonte: portal do CITIUS (Ministério da Justiça) → «Publicidade do PER, do
 * PEAP, do PEVE e da insolvência». O módulo recolhe a lista de resultados da
 * pesquisa, grava-a em **JSON** (`data/cire/runs`) e só depois a importa para o
 * Elasticsearch (`finance_cire`), onde é pesquisável.
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o token
 * da sessão (necessário para recolher, importar e apagar recolhas).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Interveniente de um processo (insolvente, administrador, credor, …). */
export type CireInterveniente = {
  papel: string;
  nome: string;
  nif?: string | null;
};

/** Publicação do CIRE (um documento do índice). */
export type CirePublicacao = {
  pub_id: string;
  doc_id?: string;
  referencia: string;
  data_publicacao?: string | null;
  data_propositura?: string | null;
  tribunal?: string | null;
  tribunal_comarca?: string | null;
  tribunal_sede?: string | null;
  ato?: string | null;
  processo?: string | null;
  processo_numero?: string | null;
  juizo?: string | null;
  especie?: string | null;
  tipo?: string | null;
  insolvente?: string | null;
  intervenientes?: CireInterveniente[];
  nifs?: string[];
  has_documento?: boolean;
  documento_url?: string | null;
  run_id?: string;
  ingested_at?: string;
  extra?: Record<string, unknown>;
};

export type CireFacet = { key: string; count: number };

export type CireSearchResult = {
  query?: string | null;
  total: number;
  items: CirePublicacao[];
  from?: number;
  size?: number;
  error?: string;
  facets?: {
    tipo?: CireFacet[];
    tribunal_comarca?: CireFacet[];
    tribunal?: CireFacet[];
    especie?: CireFacet[];
    ato?: CireFacet[];
    ano?: CireFacet[];
    mes?: CireFacet[];
    papel?: CireFacet[];
  };
};

export type CireStatus = {
  index?: string;
  documents?: number;
  nifs?: number;
  insolventes?: number;
  referencias?: number;
  min_date?: string | null;
  max_date?: string | null;
  with_documento?: number;
  by_tipo?: CireFacet[];
  by_ano?: CireFacet[];
  by_mes?: CireFacet[];
  by_especie?: CireFacet[];
  top_comarcas?: CireFacet[];
  top_tribunais?: CireFacet[];
  top_actos?: CireFacet[];
  error?: string;
};

export type CireMeta = {
  module: string;
  source: string;
  source_label: string;
  source_url: string;
  index: string;
  storage: string;
  page_size: number;
  captcha_required: boolean;
  max_window_days: number;
  default_window_days: number;
  min_request_interval: number;
  dias: { value: string; label: string }[];
  grupos_actos: { value: string; label: string }[];
  notes: string;
};

export type CireOptions = {
  tribunais: { value: string; label: string }[];
  actos: { value: string; label: string }[];
  grupos_actos: { value: string; label: string }[];
  dias: { value: string; label: string }[];
  error?: string;
};

/** Critérios da recolha (os campos do formulário do portal). */
export type CireCollectCriteria = {
  desde?: string | null;
  ate?: string | null;
  dias?: string | null;
  nif?: string | null;
  nome?: string | null;
  numero_processo?: string | null;
  tribunal?: string | null;
  grupo_actos?: string | null;
  acto?: string | null;
  max_pages?: number;
  max_items?: number | null;
  window_days?: number | null;
  min_interval?: number;
  proxy?: string | null;
  /** Reprocessar mesmo que o intervalo já tenha sido recolhido. */
  force?: boolean;
  /** Gravar/importar uma recolha por janela de datas (períodos longos). */
  split_runs?: boolean;
  index?: boolean;
};

/** Recolha gravada em disco (`data/cire/runs`). */
export type CireRun = {
  run_id: string;
  source?: string;
  criteria?: Record<string, unknown>;
  collected?: number;
  declared_total?: number;
  pages?: number;
  page_size?: number;
  duration_s?: number;
  created_at?: string;
  finished_at?: string;
  indexed?: number;
  indexed_at?: string | null;
  index_count?: number;
  /** Documentos ignorados na importação por já existirem no índice. */
  skipped_existing?: number;
  /** Janelas que a recolha ignorou por já terem sido processadas. */
  skipped_windows?: CireCoverageWindow[];
  /** Avisos da recolha (ex.: «janela já processada»). */
  warnings?: string[];
  file?: string;
  meta_file?: string;
  errors?: string[];
  stopped?: boolean;
  /** Recolhas por janela (quando a recolha é dividida). */
  runs?: string[];
  split_runs?: boolean;
  parent_run_id?: string;
  windows?: { desde?: string | null; ate?: string | null; total?: number; pages?: number; collected?: number; error?: string }[];
};

/** Janela de datas já recolhida (usada nos avisos de repetição). */
export type CireCoverageWindow = {
  desde: string;
  ate: string;
  run_id?: string;
  collected?: number;
  total?: number;
  finished_at?: string;
  motivo?: string;
};

/** Recolha em curso (job em segundo plano). */
export type CireJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "skipped";
  stage?: string;
  criteria?: CireCollectCriteria;
  page?: number | null;
  pages?: number;
  collected?: number;
  declared_total?: number;
  indexed?: number;
  index_total?: number;
  windows?: number;
  window?: { desde?: string | null; ate?: string | null } | null;
  run_id?: string;
  file?: string;
  error?: string | null;
  errors?: string[];
  /** Documentos ignorados na importação por já existirem no índice. */
  skipped_existing?: number;
  /** Janelas ignoradas por já terem sido processadas. */
  skipped_windows?: CireCoverageWindow[];
  window_index?: number;
  window_total?: number;
  runs_done?: number;
  /** Recolhas (janelas) já gravadas nesta operação. */
  runs?: string[];
  /** Avisos da recolha (ex.: «janela já processada»). */
  warnings?: string[];
  stop_requested?: boolean;
  finished?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type CireIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  /** Documentos já existentes no índice (não foram reescritos). */
  skipped_existing?: number;
  /** Documentos candidatos a indexação (recebidos - ignorados). */
  candidates?: number;
  deleted_stale?: number;
  error_details?: unknown[];
  error?: string;
};

export type CireSearchParams = {
  q?: string;
  referencia?: string;
  processo?: string;
  nif?: string;
  tribunal?: string;
  tribunal_comarca?: string;
  tipo?: string;
  ato?: string;
  especie?: string;
  insolvente?: string;
  papel?: string;
  data_from?: string;
  data_to?: string;
  has_documento?: boolean;
  size?: number;
  from?: number;
};

/* -------------------------------------------------------------- grafo ------ */

/** Nó do grafo das insolvências (uma entidade, tribunal, comarca, tipo, ato, mês…). */
export type CireGraphNode = {
  id: string;
  key: string;
  label: string;
  dimension: string;
  type: string;
  role?: string;
  /** Publicações distintas em que o valor aparece. */
  count: number;
  /** Intervenções (menções) do valor em todas as publicações. */
  mentions: number;
  nif?: string | null;
};

/** Aresta: co-ocorrência na mesma publicação ou ligação entre duas dimensões. */
export type CireGraphEdge = {
  source: string;
  target: string;
  count: number;
  mentions: number;
};

export type CireGraphMeta = {
  dimension_a: string;
  dimension_b?: string | null;
  metric: string;
  mode?: string;
  complete?: boolean;
  directed?: boolean;
  scan_capped?: boolean;
  sample_limit?: number | null;
  documents_scanned: number;
  documents_matching: number;
  nodes_total: number;
  edges_total: number;
  kept_nodes: number;
  kept_edges: number;
  omitted_edges: number;
  truncated_documents?: number;
  generated_at?: string;
  limits?: Record<string, number>;
  notes: string[];
  filters: Record<string, unknown>;
};

export type CireGraphResponse = {
  nodes: CireGraphNode[];
  edges: CireGraphEdge[];
  meta: CireGraphMeta;
  error?: string;
};

/** Dimensão disponível para construir o grafo. */
export type CireGraphDimension = {
  key: string;
  label: string;
  short: string;
  type: string;
  /** Contagens exatas por agregação do Elasticsearch (sem varrer documentos). */
  aggable?: boolean;
};

/** Receita pronta (pergunta frequente sobre as insolvências). */
export type CireGraphRecipe = {
  id: string;
  label: string;
  description: string;
  dimension_a: string;
  dimension_b: string | null;
  metric: "publicacoes" | "mencoes";
  view: string;
  limit: number;
};

export type CireGraphDimensions = {
  dimensions: CireGraphDimension[];
  metrics: { key: string; label: string }[];
  recipes: CireGraphRecipe[];
  limits: Record<string, number>;
};

/** Critérios do grafo (equivalentes aos filtros da pesquisa + dimensões). */
export type CireGraphParams = {
  dimension_a: string;
  dimension_b?: string | null;
  metric?: "publicacoes" | "mencoes";
  mode?: "auto" | "exato" | "amostra";
  q?: string;
  tipo?: string;
  especie?: string;
  ato?: string;
  comarca?: string;
  tribunal?: string;
  papel?: string;
  nif?: string;
  data_from?: string;
  data_to?: string;
  has_documento?: boolean;
  min_count?: number;
  limit?: number;
  edge_limit?: number;
  sample?: number;
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

export function getCireMeta() {
  return request<CireMeta>("/cire/meta");
}

export function getCireOptions(refresh = false) {
  return request<CireOptions>(`/cire/options${refresh ? "?refresh=true" : ""}`);
}

export function getCireStatus() {
  return request<CireStatus>("/cire/status");
}

/** Pesquisa as publicações já indexadas (só devolve o que está no Elasticsearch). */
export function searchCire(params: CireSearchParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key === "from" ? "from" : key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<CireSearchResult>(`/cire/search${suffix}`);
}

/** Publicações de um NIF/NIPC interveniente (qualquer papel). */
export function getCireInterveniente(nif: string, size = 100, from = 0) {
  return request<CireSearchResult>(`/cire/intervenientes/${encodeURIComponent(nif)}?size=${size}&from=${from}`);
}

/** Dimensões, métricas e receitas disponíveis para o grafo do CIRE. */
export function getCireGraphDimensions() {
  return request<CireGraphDimensions>("/cire/graph/dimensions");
}

/** Constrói o grafo das insolvências (rede de entidades, comarcas, tipos, tempo). */
export function getCireGraph(params: CireGraphParams) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  return request<CireGraphResponse>(`/cire/graph?${query.toString()}`);
}

export function listCireRuns(limit = 50) {
  return request<{ items: CireRun[]; total: number; directory: string }>(`/cire/runs?limit=${limit}`);
}

/** Janelas/dias já recolhidos (para avisar antes de repetir a recolha). */
export function getCireCoverage() {
  return request<{ windows: CireCoverageWindow[]; total: number; days: string[] }>("/cire/coverage");
}

export function getCireRun(runId: string, withItems = false) {
  return request<CireRun & { items?: CirePublicacao[] }>(
    `/cire/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteCireRun(runId: string) {
  return request<{ run_id: string; removed: string[] }>(`/cire/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

/** Arranca uma recolha em segundo plano (grava JSON e, se `index`, importa). */
export function startCireCollect(criteria: CireCollectCriteria) {
  return request<CireJob>("/cire/collect", withBody("POST", criteria));
}

export function listCireJobs() {
  return request<{ jobs: CireJob[] }>("/cire/jobs");
}

export function getCireJob(jobId: string) {
  return request<CireJob>(`/cire/jobs/${encodeURIComponent(jobId)}`);
}

export function stopCireJob(jobId: string) {
  return request<CireJob>(`/cire/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

/** Importa para o Elasticsearch uma recolha gravada (por omissão, a mais recente).
 *
 * Os documentos que já existem no índice são ignorados; `update_existing` força
 * a reescrita.
 */
export function ingestCire(
  payload: { run_id?: string; items?: CirePublicacao[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<CireIngestResult>("/cire/ingest", withBody("POST", payload));
}

/** Rótulo legível do tipo de processo. */
export function cireTipoLabel(tipo?: string | null): string {
  return tipo || "—";
}
