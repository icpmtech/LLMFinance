/**
 * Cliente do módulo «Publicidade da Composição da Massa Insolvente».
 *
 * Fonte: portal do CITIUS (Ministério da Justiça) → anúncios do
 * Administrador Judicial nos termos do art.º 152.º do CIRE.
 * API backend: `/massa-insolvente/*`.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Ativo descrito num anúncio de massa insolvente. */
export type MassaAtivo = {
  tipo?: string | null;
  descricao?: string | null;
  quantidade?: string | null;
  localizacao?: string | null;
};

/** Anúncio de composição da massa insolvente. */
export type MassaPublicacao = {
  pub_id: string;
  doc_id?: string;
  referencia?: string | null;
  processo?: string | null;
  processo_numero?: string | null;
  especie?: string | null;
  tipo?: string | null;
  tribunal?: string | null;
  tribunal_comarca?: string | null;
  tribunal_sede?: string | null;
  juizo?: string | null;
  insolvente?: string | null;
  insolventes?: string[];
  area_negocio?: string | null;
  data_atualizacao?: string | null;
  descricao?: string | null;
  valor_avaliacao?: number | null;
  moeda?: string | null;
  ativos?: MassaAtivo[];
  ativo_tipos?: string[];
  localizacoes?: string[];
  url?: string | null;
  run_id?: string;
  ingested_at?: string;
};

export type MassaFacet = { key: string; count: number };

export type MassaSearchResult = {
  query?: string | null;
  total: number;
  items: MassaPublicacao[];
  from?: number;
  size?: number;
  error?: string;
  facets?: {
    tipo?: MassaFacet[];
    tribunal_comarca?: MassaFacet[];
    tribunal?: MassaFacet[];
    especie?: MassaFacet[];
    ativo_tipo?: MassaFacet[];
    localizacao?: MassaFacet[];
    area_negocio?: MassaFacet[];
    ano?: MassaFacet[];
    mes?: MassaFacet[];
  };
};

export type MassaStatus = {
  index?: string;
  documents?: number;
  processos?: number;
  insolventes?: number;
  comarcas?: number;
  min_date?: string | null;
  max_date?: string | null;
  valor_stats?: { count?: number; min?: number; max?: number; avg?: number; sum?: number } | null;
  by_tipo?: MassaFacet[];
  by_ano?: MassaFacet[];
  by_mes?: MassaFacet[];
  by_especie?: MassaFacet[];
  by_comarca?: MassaFacet[];
  top_comarcas?: MassaFacet[];
  top_tribunais?: MassaFacet[];
  by_ativo_tipo?: MassaFacet[];
  top_localizacoes?: MassaFacet[];
  top_areas_negocio?: MassaFacet[];
  error?: string;
};

export type MassaMeta = {
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
  notes: string;
};

export type MassaOptions = {
  tipos_ativo: { value: string; label: string }[];
  localizacoes: { value: string; label: string }[];
  areas_negocio: { value: string; label: string }[];
  dias: { value: string; label: string }[];
  error?: string;
};

export type MassaCollectCriteria = {
  desde?: string | null;
  ate?: string | null;
  dias?: string | null;
  tipo_ativo?: string | null;
  localizacao?: string | null;
  area_negocio?: string | null;
  max_pages?: number;
  max_items?: number | null;
  window_days?: number | null;
  min_interval?: number;
  proxy?: string | null;
  force?: boolean;
  split_runs?: boolean;
  index?: boolean;
};

export type MassaCoverageWindow = {
  desde: string;
  ate: string;
  run_id?: string;
  collected?: number;
  total?: number;
  finished_at?: string;
  motivo?: string;
};

export type MassaRun = {
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
  skipped_existing?: number;
  skipped_windows?: MassaCoverageWindow[];
  warnings?: string[];
  file?: string;
  meta_file?: string;
  errors?: string[];
  stopped?: boolean;
  runs?: string[];
  split_runs?: boolean;
  parent_run_id?: string;
  windows?: { desde?: string | null; ate?: string | null; total?: number; pages?: number; collected?: number; error?: string }[];
};

export type MassaJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "skipped";
  stage?: string;
  criteria?: MassaCollectCriteria;
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
  skipped_existing?: number;
  skipped_windows?: MassaCoverageWindow[];
  window_index?: number;
  window_total?: number;
  runs_done?: number;
  runs?: string[];
  warnings?: string[];
  stop_requested?: boolean;
  finished?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type MassaIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  skipped_existing?: number;
  candidates?: number;
  deleted_stale?: number;
  error_details?: unknown[];
  error?: string;
};

export type MassaSearchParams = {
  q?: string;
  processo?: string;
  tipo?: string;
  especie?: string;
  tribunal?: string;
  tribunal_comarca?: string;
  insolvente?: string;
  ativo_tipo?: string;
  localizacao?: string;
  area_negocio?: string;
  data_from?: string;
  data_to?: string;
  valor_min?: number;
  valor_max?: number;
  size?: number;
  from?: number;
};

/* ------------------------------------------------------------------- fetch */

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

export function getMassaMeta() {
  return request<MassaMeta>("/massa-insolvente/meta");
}

export function getMassaOptions(refresh = false) {
  return request<MassaOptions>(`/massa-insolvente/options${refresh ? "?refresh=true" : ""}`);
}

export function getMassaStatus() {
  return request<MassaStatus>("/massa-insolvente/status");
}

export function searchMassa(params: MassaSearchParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key === "from" ? "from" : key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<MassaSearchResult>(`/massa-insolvente/search${suffix}`);
}

export function listMassaRuns(limit = 50) {
  return request<{ items: MassaRun[]; total: number; directory: string }>(`/massa-insolvente/runs?limit=${limit}`);
}

export function getMassaCoverage() {
  return request<{ windows: MassaCoverageWindow[]; total: number; days: string[] }>("/massa-insolvente/coverage");
}

export function getMassaRun(runId: string, withItems = false) {
  return request<MassaRun & { items?: MassaPublicacao[] }>(
    `/massa-insolvente/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteMassaRun(runId: string) {
  return request<{ run_id: string; removed: string[] }>(`/massa-insolvente/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

export function startMassaCollect(criteria: MassaCollectCriteria) {
  return request<MassaJob>("/massa-insolvente/collect", withBody("POST", criteria));
}

export function listMassaJobs() {
  return request<{ jobs: MassaJob[] }>("/massa-insolvente/jobs");
}

export function getMassaJob(jobId: string) {
  return request<MassaJob>(`/massa-insolvente/jobs/${encodeURIComponent(jobId)}`);
}

export function stopMassaJob(jobId: string) {
  return request<MassaJob>(`/massa-insolvente/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

export function ingestMassa(
  payload: { run_id?: string; items?: MassaPublicacao[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<MassaIngestResult>("/massa-insolvente/ingest", withBody("POST", payload));
}

/** Rótulo legível do tipo de processo. */
export function massaTipoLabel(tipo?: string | null): string {
  return tipo || "—";
}

export function formatCurrency(value?: number | null, moeda = "€"): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${moeda}`;
}
