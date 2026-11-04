/**
 * Cliente do módulo «Lista Pública de Execuções» (`/execucoes/*`).
 *
 * Fonte: portal do CITIUS (Ministério da Justiça) → *Lista Pública de
 * Execuções* (executados em relação aos quais não se conseguiu encontrar bens
 * penhoráveis suficientes).
 *
 * O módulo recolhe os registos do portal, grava-os em JSON
 * (`data/execucoes/runs`) e só depois importa para o Elasticsearch
 * (`finance_execucoes`), onde são pesquisáveis.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type ExecucaoExtra = {
  valor_execucao?: number | null;
  comarca?: string | null;
  tribunal?: string | null;
  unidade_organica?: string | null;
  agente_execucao?: string | null;
  estado?: string | null;
};

export type Execucao = {
  pub_id: string;
  doc_id?: string;
  nome_executado: string;
  numero_processo?: string | null;
  data_entrada?: string | null;
  source?: string;
  run_id?: string;
  ingested_at?: string;
  extra?: ExecucaoExtra | null;
};

export type ExecucaoFacet = { key: string; count: number };

export type ExecucaoSearchResult = {
  query?: string | null;
  total: number;
  items: Execucao[];
  from?: number;
  size?: number;
  valor_total?: number;
  valor_medio?: number | null;
  valor_maximo?: number | null;
  error?: string;
  facets?: {
    estado?: ExecucaoFacet[];
    comarca?: ExecucaoFacet[];
    tribunal?: ExecucaoFacet[];
    agente_execucao?: ExecucaoFacet[];
    ano?: ExecucaoFacet[];
    mes?: ExecucaoFacet[];
  };
};

export type ExecucaoStatus = {
  index?: string;
  documents?: number;
  min_date?: string | null;
  max_date?: string | null;
  valor_total?: number;
  valor_medio?: number | null;
  valor_maximo?: number | null;
  by_estado?: ExecucaoFacet[];
  by_comarca?: ExecucaoFacet[];
  by_tribunal?: ExecucaoFacet[];
  by_agente?: ExecucaoFacet[];
  error?: string;
};

export type ExecucaoMeta = {
  module: string;
  source: string;
  source_label: string;
  source_url: string;
  index: string;
  storage: string;
  page_size: number;
  captcha_required: boolean;
  dias_opcoes: Record<string, string>;
  notas?: string;
};

export type ExecucaoOption = { value: string; label: string };

export type ExecucaoOptions = {
  alfabeto: ExecucaoOption[];
  error?: string;
};

export type ExecucaoCollectCriteria = {
  nome?: string | null;
  documento?: string | null;
  tipo_documento?: string | null;
  numero_processo?: string | null;
  dias?: string;
  letras?: string[] | null;
  max_pages_per_letra?: number;
  max_items?: number | null;
  min_interval?: number;
  proxy?: string | null;
  index?: boolean;
};

export type ExecucaoRun = {
  run_id: string;
  source?: string;
  criteria?: Record<string, unknown>;
  collected?: number;
  declared_total?: number;
  pages?: number;
  duration_s?: number;
  letras?: number;
  created_at?: string;
  finished_at?: string;
  indexed?: number;
  indexed_at?: string | null;
  index_count?: number;
  skipped_existing?: number;
  file?: string;
  meta_file?: string;
  errors?: string[];
  stopped?: boolean;
};

export type ExecucaoJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "empty";
  stage?: string;
  criteria?: ExecucaoCollectCriteria;
  page?: number | null;
  pages?: number | null;
  declared_total?: number | null;
  collected?: number;
  letra?: string | null;
  duration_s?: number;
  indexed?: number;
  index_total?: number;
  run_id?: string;
  error?: string | null;
  errors?: string[];
  skipped_existing?: number;
  stop_requested?: boolean;
  finished?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type ExecucaoIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  skipped_existing?: number;
  candidates?: number;
  error?: string;
};

export type ExecucaoSearchParams = {
  q?: string;
  nome_executado?: string;
  numero_processo?: string;
  tribunal?: string;
  comarca?: string;
  unidade_organica?: string;
  agente_execucao?: string;
  estado?: string;
  data_from?: string;
  data_to?: string;
  valor_min?: number;
  valor_max?: number;
  size?: number;
  from?: number;
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

function toQueryString(params: Record<string, unknown>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value
        .filter((item) => item !== undefined && item !== null && item !== "")
        .forEach((item) => query.append(key, String(item)));
      return;
    }
    query.set(key, String(value));
  });
  return query.toString();
}

/* -------------------------------------------------------------------- API */

export function getExecucoesMeta() {
  return request<ExecucaoMeta>("/execucoes/meta");
}

export function getExecucoesOptions(refresh = false) {
  return request<ExecucaoOptions>(`/execucoes/options${refresh ? "?refresh=true" : ""}`);
}

export function getExecucoesStatus() {
  return request<ExecucaoStatus>("/execucoes/status");
}

export function searchExecucoes(params: ExecucaoSearchParams = {}) {
  const suffix = toQueryString(params);
  return request<ExecucaoSearchResult>(`/execucoes/search${suffix ? `?${suffix}` : ""}`);
}

export function listExecucoesRuns(limit = 50) {
  return request<{ items: ExecucaoRun[]; total: number; directory: string }>(`/execucoes/runs?limit=${limit}`);
}

export function getExecucoesRun(runId: string, withItems = false) {
  return request<ExecucaoRun & { items?: Execucao[] }>(
    `/execucoes/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteExecucoesRun(runId: string, dropIndex = false) {
  return request<{ run_id: string; removed: string[]; index?: { deleted?: number; error?: string } }>(
    `/execucoes/runs/${encodeURIComponent(runId)}${dropIndex ? "?drop_index=true" : ""}`,
    { method: "DELETE" },
  );
}

export function startExecucoesCollect(criteria: ExecucaoCollectCriteria) {
  return request<ExecucaoJob>("/execucoes/collect", withBody("POST", criteria));
}

export function listExecucoesJobs() {
  return request<{ jobs: ExecucaoJob[] }>("/execucoes/jobs");
}

export function getExecucoesJob(jobId: string) {
  return request<ExecucaoJob>(`/execucoes/jobs/${encodeURIComponent(jobId)}`);
}

export function stopExecucoesJob(jobId: string) {
  return request<ExecucaoJob>(`/execucoes/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

export function ingestExecucoes(
  payload: { run_id?: string; items?: Execucao[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<ExecucaoIngestResult>("/execucoes/ingest", withBody("POST", payload));
}
