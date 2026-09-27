/**
 * Cliente do módulo «Citação e Notificação Edital» (`/citacoes/*`).
 *
 * Fonte: portal do CITIUS (Ministério da Justiça) → *Citação e Notificação
 * Edital*: as citações/notificações publicadas por édito quando o citando não é
 * encontrado, com tribunal, ato, referência, processo, espécie, data,
 * intervenientes (exequente, executado, réu, requerido, …) e o documento em PDF.
 *
 * O módulo recolhe a lista de resultados da pesquisa (**pelo nome do
 * interveniente**), grava-a em **JSON** (`data/citacoes/runs`) e só depois a
 * importa para o Elasticsearch (`finance_citacoes_edital`), onde é pesquisável.
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o token
 * da sessão (necessário para recolher, importar e apagar recolhas).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Interveniente de um édito (exequente, executado, réu, credor, …). */
export type CitacoesInterveniente = {
  papel: string;
  nome: string;
  nif?: string | null;
};

/** Édito de citação/notificação (um documento do índice). */
export type CitacoesEdito = {
  pub_id: string;
  doc_id?: string;
  referencia: string;
  data_publicacao?: string | null;
  tribunal?: string | null;
  tribunal_comarca?: string | null;
  tribunal_sede?: string | null;
  ato?: string | null;
  tipo?: string | null;
  processo?: string | null;
  processo_numero?: string | null;
  juizo?: string | null;
  especie?: string | null;
  citado?: string | null;
  papeis?: string[];
  intervenientes?: CitacoesInterveniente[];
  has_documento?: boolean;
  documento_url?: string | null;
  run_id?: string;
  ingested_at?: string;
  extra?: Record<string, unknown>;
};

export type CitacoesFacet = { key: string; count: number };

export type CitacoesSearchResult = {
  query?: string | null;
  total: number;
  items: CitacoesEdito[];
  from?: number;
  size?: number;
  error?: string;
  facets?: {
    tipo?: CitacoesFacet[];
    tribunal_comarca?: CitacoesFacet[];
    tribunal?: CitacoesFacet[];
    ato?: CitacoesFacet[];
    especie?: CitacoesFacet[];
    papel?: CitacoesFacet[];
    ano?: CitacoesFacet[];
    mes?: CitacoesFacet[];
  };
};

export type CitacoesStatus = {
  index?: string;
  documents?: number;
  referencias?: number;
  processos?: number;
  tribunais?: number;
  citados?: number;
  min_date?: string | null;
  max_date?: string | null;
  with_documento?: number;
  by_tipo?: CitacoesFacet[];
  by_ano?: CitacoesFacet[];
  by_mes?: CitacoesFacet[];
  by_papel?: CitacoesFacet[];
  top_comarcas?: CitacoesFacet[];
  top_tribunais?: CitacoesFacet[];
  top_actos?: CitacoesFacet[];
  error?: string;
};

export type CitacoesMeta = {
  module: string;
  source: string;
  source_label: string;
  source_url: string;
  index: string;
  storage: string;
  page_size: number;
  captcha_required: boolean;
  nome_required: boolean;
  /** Meses recolhidos por omissão («últimos 6 meses»). */
  default_months: number;
  max_months: number;
  min_request_interval: number;
  dias: { value: string; label: string }[];
  notes: string;
};

export type CitacoesOptions = {
  tribunais: { value: string; label: string }[];
  dias: { value: string; label: string }[];
  error?: string;
};

/** Critérios da recolha (os campos do formulário do portal). */
export type CitacoesCollectCriteria = {
  nome: string;
  tribunal?: string | null;
  dias?: string | null;
  /** Últimos N meses (0 = tudo). Por omissão, 6. */
  meses?: number | null;
  max_pages?: number;
  max_items?: number | null;
  min_interval?: number;
  proxy?: string | null;
  index?: boolean;
};

/** Recolha gravada em disco (`data/citacoes/runs`). */
export type CitacoesRun = {
  run_id: string;
  source?: string;
  criteria?: Record<string, unknown>;
  collected?: number;
  declared_total?: number;
  declared_pages?: number;
  pages?: number;
  page_size?: number;
  older_than_cutoff?: number;
  duration_s?: number;
  created_at?: string;
  finished_at?: string;
  indexed?: number;
  indexed_at?: string | null;
  index_count?: number;
  /** Documentos ignorados na importação por já existirem no índice. */
  skipped_existing?: number;
  file?: string;
  meta_file?: string;
  errors?: string[];
  stopped?: boolean;
};

/** Recolha em curso (job em segundo plano). */
export type CitacoesJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "empty";
  stage?: string;
  criteria?: CitacoesCollectCriteria;
  page?: number | null;
  pages?: number;
  collected?: number;
  declared_total?: number;
  declared_pages?: number;
  older_than_cutoff?: number;
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

export type CitacoesIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  /** Documentos já existentes no índice (não foram reescritos). */
  skipped_existing?: number;
  /** Documentos candidatos a indexação (recebidos - ignorados). */
  candidates?: number;
  error_details?: unknown[];
  error?: string;
};

export type CitacoesSearchParams = {
  q?: string;
  referencia?: string;
  processo?: string;
  tribunal?: string;
  tribunal_comarca?: string;
  tipo?: string;
  ato?: string;
  especie?: string;
  citado?: string;
  nome?: string;
  papel?: string;
  data_from?: string;
  data_to?: string;
  has_documento?: boolean;
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

/* -------------------------------------------------------------------- API */

export function getCitacoesMeta() {
  return request<CitacoesMeta>("/citacoes/meta");
}

export function getCitacoesOptions(refresh = false) {
  return request<CitacoesOptions>(`/citacoes/options${refresh ? "?refresh=true" : ""}`);
}

export function getCitacoesStatus() {
  return request<CitacoesStatus>("/citacoes/status");
}

/** Pesquisa os éditos já indexados (só devolve o que está no Elasticsearch). */
export function searchCitacoes(params: CitacoesSearchParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<CitacoesSearchResult>(`/citacoes/search${suffix}`);
}

export function listCitacoesRuns(limit = 50) {
  return request<{ items: CitacoesRun[]; total: number; directory: string }>(`/citacoes/runs?limit=${limit}`);
}

export function getCitacoesRun(runId: string, withItems = false) {
  return request<CitacoesRun & { items?: CitacoesEdito[] }>(
    `/citacoes/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteCitacoesRun(runId: string) {
  return request<{ run_id: string; removed: string[] }>(`/citacoes/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

/** Arranca uma recolha em segundo plano (grava JSON e, se `index`, importa). */
export function startCitacoesCollect(criteria: CitacoesCollectCriteria) {
  return request<CitacoesJob>("/citacoes/collect", withBody("POST", criteria));
}

export function listCitacoesJobs() {
  return request<{ jobs: CitacoesJob[] }>("/citacoes/jobs");
}

export function getCitacoesJob(jobId: string) {
  return request<CitacoesJob>(`/citacoes/jobs/${encodeURIComponent(jobId)}`);
}

export function stopCitacoesJob(jobId: string) {
  return request<CitacoesJob>(`/citacoes/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

/** Importa para o Elasticsearch uma recolha gravada (por omissão, a mais recente).
 *
 * Os documentos que já existem no índice são ignorados; `update_existing` força
 * a reescrita.
 */
export function ingestCitacoes(
  payload: { run_id?: string; items?: CitacoesEdito[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<CitacoesIngestResult>("/citacoes/ingest", withBody("POST", payload));
}

/** Rótulo legível do tipo de édito. */
export function citacoesTipoLabel(tipo?: string | null): string {
  return tipo || "Édito";
}
