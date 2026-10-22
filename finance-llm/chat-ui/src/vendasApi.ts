/**
 * Cliente do módulo «Venda de Bens Penhorados» (`/vendas/*`).
 *
 * Fontes:
 * - portal do CITIUS (Ministério da Justiça) → *Venda de Bens Penhorados em
 *   Processos Executivos* (tribunal, datas, tipo de bem, estado, valor base).
 * - e-leiloes.pt → vendas promovidas pelos agentes de execução, com processo,
 *   executados, gestor, fotos e geolocalização.
 *
 * O módulo recolhe os bens de ambos os portais, grava-os em JSON
 * (`data/vendas_penhorados/runs`) e só depois importa para o Elasticsearch
 * (`finance_vendas_penhorados`), onde são pesquisáveis.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type VendaInterveniente = {
  papel?: string;
  nome: string;
  nif?: string | null;
  morada?: string | null;
  telefone?: string | null;
};

export type VendaExecutado = {
  nome?: string;
  nif?: string | null;
  requerido?: string | null;
};

export type VendaGestor = {
  nome?: string;
  tipo?: string;
  cedula?: string;
  email?: string;
  telefone?: string;
  comarca?: string;
};

export type VendaPenhorada = {
  venda_id: string;
  doc_id?: string;
  fonte: "citius" | "eleiloes";
  referencia?: string | null;
  tribunal?: string | null;
  tribunal_sede?: string | null;
  comarca_judicial?: string | null;
  processo?: string | null;
  processo_numero?: string | null;
  juizo?: string | null;
  especie?: string | null;
  tipo_bem?: string | null;
  subtipo_bem?: string | null;
  modalidade?: string | null;
  estado?: string | null;
  titulo?: string | null;
  descricao?: string | null;
  valor_base?: number | null;
  valor_minimo?: number | null;
  valor_abertura?: number | null;
  lance_atual?: number | null;
  data_venda?: string | null;
  data_inicio?: string | null;
  data_fim?: string | null;
  distrito?: string | null;
  concelho?: string | null;
  freguesia?: string | null;
  morada?: string | null;
  codigo_postal?: string | null;
  lat?: number | null;
  lon?: number | null;
  intervenientes?: VendaInterveniente[];
  executados?: VendaExecutado[];
  gestor?: VendaGestor | null;
  fotos?: string[];
  onus?: unknown[];
  detalhe_url?: string | null;
  url?: string | null;
  data_atualizacao?: string | null;
  run_id?: string;
  ingested_at?: string;
  extra?: Record<string, unknown>;
};

export type VendaFacet = { key: string; count: number };

export type VendaSearchResult = {
  query?: string | null;
  total: number;
  items: VendaPenhorada[];
  from?: number;
  size?: number;
  valor_total?: number;
  valor_medio?: number | null;
  valor_maximo?: number | null;
  error?: string;
  facets?: {
    fonte?: VendaFacet[];
    tipo_bem?: VendaFacet[];
    modalidade?: VendaFacet[];
    estado?: VendaFacet[];
    distrito?: VendaFacet[];
    concelho?: VendaFacet[];
    tribunal?: VendaFacet[];
    data_venda?: VendaFacet[];
  };
};

export type VendaStatus = {
  index?: string;
  documents?: number;
  min_date?: string | null;
  max_date?: string | null;
  valor_total?: number;
  valor_medio?: number | null;
  valor_maximo?: number | null;
  by_fonte?: VendaFacet[];
  by_tipo_bem?: VendaFacet[];
  by_modalidade?: VendaFacet[];
  by_estado?: VendaFacet[];
  by_distrito?: VendaFacet[];
  by_concelho?: VendaFacet[];
  by_tribunal?: VendaFacet[];
  error?: string;
};

export type VendaMeta = {
  module: string;
  source: string;
  source_label: string;
  source_url: string;
  index: string;
  storage: string;
  page_size: number;
  captcha_required: boolean;
  default_window: { desde: string; ate: string };
  max_details: number;
  notas?: string;
};

export type VendaOption = { value: string; label: string };

export type VendaOptions = {
  tribunais: VendaOption[];
  tipos_bem: VendaOption[];
  modalidades: VendaOption[];
  estados: VendaOption[];
  error?: string;
};

export type VendaCollectCriteria = {
  fontes?: string[];
  tribunais?: string[] | null;
  desde?: string | null;
  ate?: string | null;
  tipo_bem?: string | null;
  modalidade?: string | null;
  estado?: string | null;
  max_pages_per_tribunal?: number;
  max_pages_eleiloes?: number;
  max_details?: number;
  max_items?: number | null;
  min_interval?: number;
  partial_every?: number;
  workers?: number;
  proxy?: string | null;
  index?: boolean;
};

export type VendaRun = {
  run_id: string;
  source?: string;
  criteria?: Record<string, unknown>;
  collected?: number;
  declared_total?: number;
  pages?: number;
  details?: number;
  duration_s?: number;
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

export type VendaJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "empty";
  stage?: string;
  criteria?: VendaCollectCriteria;
  page?: number | null;
  pages?: number | null;
  declared_total?: number | null;
  collected?: number;
  details?: number;
  tribunal?: string | null;
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

export type VendaIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  skipped_existing?: number;
  candidates?: number;
  error_details?: unknown[];
  error?: string;
};

export type VendaSearchParams = {
  q?: string;
  fonte?: string;
  referencia?: string;
  processo?: string;
  tribunal?: string;
  tribunal_comarca?: string;
  comarca_judicial?: string;
  tipo_bem?: string;
  modalidade?: string;
  estado?: string;
  distrito?: string;
  concelho?: string;
  morada?: string;
  nome?: string;
  nif?: string;
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

export function getVendasMeta() {
  return request<VendaMeta>("/vendas/meta");
}

export function getVendasOptions(refresh = false) {
  return request<VendaOptions>(`/vendas/options${refresh ? "?refresh=true" : ""}`);
}

export function getVendasStatus() {
  return request<VendaStatus>("/vendas/status");
}

export function searchVendas(params: VendaSearchParams = {}) {
  const suffix = toQueryString(params);
  return request<VendaSearchResult>(`/vendas/search${suffix ? `?${suffix}` : ""}`);
}

export function listVendasRuns(limit = 50) {
  return request<{ items: VendaRun[]; total: number; directory: string }>(`/vendas/runs?limit=${limit}`);
}

export function getVendasRun(runId: string, withItems = false) {
  return request<VendaRun & { items?: VendaPenhorada[] }>(
    `/vendas/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteVendasRun(runId: string, dropIndex = false) {
  return request<{ run_id: string; removed: string[]; index?: { deleted?: number; error?: string } }>(
    `/vendas/runs/${encodeURIComponent(runId)}${dropIndex ? "?drop_index=true" : ""}`,
    { method: "DELETE" },
  );
}

export function startVendasCollect(criteria: VendaCollectCriteria) {
  return request<VendaJob>("/vendas/collect", withBody("POST", criteria));
}

export function listVendasJobs() {
  return request<{ jobs: VendaJob[] }>("/vendas/jobs");
}

export function getVendasJob(jobId: string) {
  return request<VendaJob>(`/vendas/jobs/${encodeURIComponent(jobId)}`);
}

export function stopVendasJob(jobId: string) {
  return request<VendaJob>(`/vendas/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

export function ingestVendas(
  payload: { run_id?: string; items?: VendaPenhorada[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<VendaIngestResult>("/vendas/ingest", withBody("POST", payload));
}

/** Rótulo legível da fonte. */
export function vendaFonteLabel(fonte?: string | null): string {
  if (fonte === "citius") return "CITIUS";
  if (fonte === "eleiloes") return "e-leilões.pt";
  return fonte || "Desconhecida";
}
