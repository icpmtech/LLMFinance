/**
 * Cliente do módulo Contribuintes (`/contribuintes/*`).
 *
 * `finance_contribuintes` é um índice **derivado**: um documento por NIF/NIPC,
 * agregado a partir de todos os índices da plataforma (contratos públicos PT e
 * ES, cadastro de entidades, publicações societárias, CIRE, PessoasIQ, firmas,
 * marcas e CRM). A sincronização pode ser manual (botão) ou agendada por cron
 * (`/contribuintes/schedule`).
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o token
 * da sessão (necessário para sincronizar e alterar o agendamento).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type ContribuinteFacet = { key: string; label?: string; count: number };

export type ContribuinteSourceBlock = {
  label?: string;
  count?: number;
  value?: number;
  first?: string | null;
  last?: string | null;
  names?: string[];
  roles?: string[];
  country?: string;
  parts?: Record<string, { count?: number; value?: number; first?: string | null; last?: string | null; names?: string[] }>;
  detail?: Record<string, unknown>;
};

/** Contribuinte (um documento do índice, por NIF/NIPC). */
export type Contribuinte = {
  nif: string;
  doc_id?: string;
  name?: string | null;
  names?: string[];
  name_norm?: string;
  type?: string;
  type_label?: string;
  is_company?: boolean;
  nif_valid?: boolean;
  country?: string;
  sources?: string[];
  source_labels?: string[];
  roles?: string[];
  contracts_count?: number;
  contracts_as_adjudicante?: number;
  contracts_as_adjudicatario?: number;
  contracts_value?: number;
  contracts_first_date?: string | null;
  contracts_last_date?: string | null;
  contratos_es_count?: number;
  contratos_es_value?: number;
  contratos_es_last_date?: string | null;
  entities_contracts_count?: number;
  entities_value?: number;
  societario_count?: number;
  societario_last_date?: string | null;
  cire_count?: number;
  cire_last_date?: string | null;
  cire_roles?: string[];
  trademarks_count?: number;
  firmas_count?: number;
  people_roles_count?: number;
  people_companies_count?: number;
  crm_account?: boolean;
  records_total?: number;
  first_seen?: string | null;
  last_seen?: string | null;
  location?: Record<string, string>;
  run_id?: string;
  synced_at?: string;
  score?: number;
  error?: string;
  /** Só presente na ficha (`GET /contribuintes/{nif}`): evidência por fonte. */
  [key: string]: unknown;
};

export type ContribuintesSearchResult = {
  query?: string | null;
  total: number;
  items: Contribuinte[];
  from?: number;
  size?: number;
  page?: number;
  sort?: string;
  error?: string;
};

export type ContribuintesRunSummary = {
  run_id?: string;
  trigger?: string;
  started_at?: string;
  finished_at?: string;
  duration_s?: number;
  status?: string;
  full?: boolean;
  unique?: number;
  written?: number;
  write_errors?: number;
  deleted?: number;
  page_size?: number;
  sources?: Record<string, { label?: string; index?: string; nifs?: number; pages?: number }>;
  errors?: { source?: string; spec?: string; error?: string }[];
};

export type ContribuintesStatus = {
  index?: string;
  documents?: number;
  running?: boolean;
  error?: string;
  types?: ContribuinteFacet[];
  countries?: ContribuinteFacet[];
  sources?: ContribuinteFacet[];
  roles?: ContribuinteFacet[];
  /** Distritos e concelhos conhecidos (localização do contribuinte ou dos contratos). */
  districts?: ContribuinteFacet[];
  municipalities?: ContribuinteFacet[];
  /** Contribuintes com localização (distrito) preenchida. */
  with_location?: number;
  /** Matriz tipo × distrito (para o grafo de tipos e localização). */
  types_by_district?: ContribuintesTypeByDistrict[];
  companies?: number;
  with_contracts?: number;
  with_cire?: number;
  invalid_nif?: number;
  contracts_value?: number;
  last_seen?: string | null;
  last_run?: ContribuintesRunSummary | null;
  history?: ContribuintesRunSummary[];
  schedule?: { enabled?: boolean; cron?: string | null; timezone?: string | null };
};

/** Um distrito com a repartição por tipo de contribuinte (e valor contratual). */
export type ContribuintesTypeByDistrict = {
  key: string;
  count: number;
  value?: number;
  types?: ContribuinteFacet[];
};

export type ContribuintesSchedulerState = {
  available?: boolean;
  enabled?: boolean;
  active?: boolean;
  cron?: string | null;
  timezone?: string | null;
  next_run_time?: string | null;
  jobs?: { id: string; name: string; next_run_time?: string | null }[];
  error?: string | null;
};

export type ContribuintesSchedule = {
  enabled: boolean;
  cron: string;
  timezone: string;
  sources?: string[] | null;
  page_size?: number;
  last_run?: ContribuintesRunSummary | null;
  history?: ContribuintesRunSummary[];
  scheduler?: ContribuintesSchedulerState;
};

export type ContribuintesMeta = {
  index: string;
  title: string;
  description: string;
  sources: { id: string; label: string; index: string; fields: string[]; roles: string[] }[];
  types: { id: string; label: string }[];
  schedule: { enabled: boolean; cron: string; timezone: string };
  page_size: number;
  last_run?: ContribuintesRunSummary | null;
  /** Relatórios disponíveis (PDF/Excel/CSV) e a marca usada. */
  reports?: ContribuintesReportsMeta;
};

/** Formatos de relatório disponíveis no backend. */
export type ContribuintesReportFormat = "pdf" | "xlsx" | "csv";

export type ContribuintesReportsMeta = {
  formats: { id: ContribuintesReportFormat; label: string; media_type: string; available: boolean; embeds_logo: boolean }[];
  brand: string;
  tagline: string;
  logo: string;
  logo_available: boolean;
};

export type ContribuintesJob = {
  id: string;
  status: "running" | "ok" | "error";
  trigger?: string;
  started_at?: string;
  finished_at?: string;
  progress?: Record<string, unknown>;
  summary?: ContribuintesRunSummary | null;
  error?: string | null;
};

export type ContribuintesSearchParams = {
  q?: string;
  source?: string;
  role?: string;
  type?: string;
  country?: string;
  is_company?: boolean;
  has_contracts?: boolean;
  sort?: string;
  page?: number;
  size?: number;
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

export function getContribuintesMeta() {
  return request<ContribuintesMeta>("/contribuintes/meta");
}

export function getContribuintesStatus() {
  return request<ContribuintesStatus>("/contribuintes/status");
}

export function getContribuintesSchedule() {
  return request<ContribuintesSchedule>("/contribuintes/schedule");
}

/** Pesquisa contribuintes (nome/NIF) com filtros por fonte, papel, tipo e país. */
export function searchContribuintes(params: ContribuintesSearchParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString();
  return request<ContribuintesSearchResult>(`/contribuintes/search${suffix ? `?${suffix}` : ""}`);
}

export function getContribuinte(nif: string) {
  return request<Contribuinte>(`/contribuintes/${encodeURIComponent(nif)}`);
}

export function autocompleteContribuintes(q: string, size = 8) {
  const query = new URLSearchParams({ q, size: String(size) });
  return request<{ items: Contribuinte[] }>(`/contribuintes/autocomplete?${query.toString()}`);
}

/** Arranca a sincronização (todas as fontes, ou só as indicadas). */
export function startContribuintesSync(body: { sources?: string[]; page_size?: number; wait?: boolean } = {}) {
  return request<{ job_id?: string; status?: string; started_at?: string; summary?: ContribuintesRunSummary; error?: string }>(
    "/contribuintes/sync",
    withBody("POST", body),
  );
}

export function listContribuintesJobs() {
  return request<{ jobs: ContribuintesJob[]; running: boolean }>("/contribuintes/jobs");
}

export function getContribuintesJob(jobId: string) {
  return request<ContribuintesJob>(`/contribuintes/jobs/${encodeURIComponent(jobId)}`);
}

/** Define o cron da sincronização automática. */
export function saveContribuintesSchedule(body: {
  enabled?: boolean;
  cron?: string;
  timezone?: string;
  sources?: string[];
  page_size?: number;
}) {
  return request<ContribuintesSchedule>("/contribuintes/schedule", withBody("PUT", body));
}

export function deleteContribuintesIndex() {
  return request<{ deleted?: number; error?: string }>("/contribuintes/index", { method: "DELETE" });
}

/* --------------------------------------------------------------- relatórios */

/** Lê o nome do ficheiro do cabeçalho `Content-Disposition`. */
async function download(path: string, fallback: string): Promise<{ blob: Blob; filename: string }> {
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
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const blob = await response.blob();
  return { blob, filename: match ? match[1] : fallback };
}

/** Relatório da ficha de um contribuinte (PDF, Excel ou CSV). */
export function exportContribuinteReport(nif: string, format: ContribuintesReportFormat) {
  return download(
    `/contribuintes/export/${encodeURIComponent(nif)}?format=${format}`,
    `iq-os-contribuinte-${nif}.${format}`,
  );
}

/** Relatório da lista de contribuintes que corresponde à pesquisa atual. */
export function exportContribuintesReport(params: ContribuintesSearchParams, format: ContribuintesReportFormat, limit = 1000) {
  const query = new URLSearchParams({ format, limit: String(limit) });
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  return download(`/contribuintes/export?${query.toString()}`, `iq-os-contribuintes.${format}`);
}

/** Descarrega um ficheiro já obtido (blob do backend). */
export function saveContribuintesReport(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Reexporta o tipo dos contribuintes para autocompletar em caixas de pesquisa. */
export type ContribuintesSuggestion = Pick<Contribuinte, "nif" | "name" | "type" | "type_label" | "sources" | "contracts_count">;
