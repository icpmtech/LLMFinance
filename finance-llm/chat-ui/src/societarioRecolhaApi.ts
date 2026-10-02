/**
 * Módulo **Recolha Societária** — recolha massiva de publicações de atos
 * societários (MJ) para ficheiros `.json` e indexação no Elasticsearch.
 *
 * Duas passagens independentes:
 *
 * 1. **Alvos e recolha** (`/societario/recolha/targets`, `…/jobs`) — escolher as
 *    empresas pelos **anos dos contratos** e/ou por firma/NIF, recolher em lote
 *    (reCAPTCHA por 2captcha) e gravar um JSON por entidade;
 * 2. **Ficheiros e indexação** (`…/exports`, `…/exports/ingest`) — ver o que está
 *    exportado e indexar em `finance_publicacoes_mj` (alimentando o PessoasIQ).
 */
import { API_BASE } from "./api";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function ler<T>(res: Response, contexto: string): Promise<T> {
  if (!res.ok) {
    const texto = await res.text();
    throw new Error(`${contexto}: ${res.status} - ${texto}`);
  }
  return res.json() as Promise<T>;
}

// --- tipos -----------------------------------------------------------------

export type RecolhaPapel = "ambos" | "adjudicatario" | "adjudicante";

export interface RecolhaMeta {
  module: string;
  export_dir: string;
  export_dir_env: string;
  index: string;
  files: number;
  publications_exported: number;
  notes: string;
}

export interface RecolhaAno {
  year: number;
  contracts: number;
}

export interface RecolhaAnos {
  years: RecolhaAno[];
  min?: number | null;
  max?: number | null;
}

export interface RecolhaAlvo {
  nif: string;
  name?: string | null;
  /** Contratos no cadastro de entidades (todos os anos). */
  contracts_count?: number | null;
  total_value?: number | null;
  /** Contratos **no período** escolhido (só quando há filtro de anos). */
  period_contracts?: number | null;
  period_value?: number | null;
  /** Publicações societárias já indexadas. */
  publications_count: number;
}

export interface RecolhaAlvos {
  items: RecolhaAlvo[];
  total: number;
  from: number;
  size: number;
  /** Empresas candidatas encontradas no período (antes dos filtros de nome/valor). */
  period_entities?: number | null;
  /** Verdadeiro quando o período tem mais candidatas do que as consideradas. */
  period_truncated?: boolean;
  period_size?: number | null;
  filters?: Record<string, unknown>;
}

export interface RecolhaFiltros {
  ano_ini?: number | null;
  ano_fim?: number | null;
  papel?: RecolhaPapel;
  q?: string;
  nifs?: string[];
  min_contracts?: number;
  min_value?: number | null;
  exclude_collected?: boolean;
  limit?: number;
  from?: number;
}

export interface RecolhaJobRequest extends RecolhaFiltros {
  max_entities?: number;
  tipo?: string;
  with_details?: boolean;
  max_pages?: number;
  data_ini?: string | null;
  data_fim?: string | null;
  min_interval?: number;
  /** Pausa (s) quando o portal do MJ limita os pedidos, antes de tentar de novo. */
  rate_limit_pause?: number;
  rate_limit_retries?: number;
  recaptcha_timeout?: number;
  stop_on_captcha?: boolean;
  api_key?: string;
  proxy?: string;
  debug?: boolean;
  ingest?: boolean;
}

export interface RecolhaProgresso {
  phase?: string;
  entities_done?: number;
  entities_total?: number;
  publications?: number;
  files?: number;
  /** Publicações já encontradas na entidade em curso (antes de acabar). */
  publications_live?: number;
  /** Páginas da grelha já lidas na entidade em curso. */
  pages_read?: number;
  /** Registos já gravados no JSON da entidade em curso. */
  saved_total?: number;
  /** Instante do último sinal de vida do trabalho (ISO). */
  last_activity?: string | null;
  current?: {
    nif: string;
    name?: string | null;
    saved?: number;
    page?: number;
    stage?: string;
    details_done?: number;
    details_total?: number;
    publications?: number;
    pages_read?: number;
  } | null;
}

export interface RecolhaJob {
  job_id: string;
  status: "running" | "paused" | "stopped" | "done" | "error" | string;
  started_at?: string | null;
  finished_at?: string | null;
  stop_requested?: boolean;
  payload?: RecolhaJobRequest;
  progress?: RecolhaProgresso;
  result?: {
    entities?: number;
    entities_with_publications?: number;
    publications?: number;
    files?: number;
    /** Entidades que ficaram por recolher por rate-limit do portal. */
    rate_limited?: number;
    ingested?: boolean;
    export_dir?: string;
    errors?: { nif?: string; name?: string | null; error: string }[];
    message?: string;
  } | null;
  error?: string | null;
  already_running?: boolean;
  message?: string;
}

export interface RecolhaFicheiro {
  nif: string;
  name?: string | null;
  file: string;
  total?: number | null;
  bytes?: number | null;
  updated_at?: string | null;
  mtime?: string | null;
}

/** Empresa nos resultados da pesquisa do módulo (alvo + estado dos dados). */
export interface RecolhaEmpresaItem extends RecolhaAlvo {
  /** Já existe ficheiro JSON exportado. */
  exported?: boolean;
  exported_total?: number | null;
  exported_updated_at?: string | null;
}

export interface RecolhaEmpresas {
  q: string;
  total?: number;
  items: RecolhaEmpresaItem[];
}

/** De onde vieram as publicações mostradas na ficha de empresa. */
export type RecolhaOrigemDados = "export" | "index" | "none";

/** Ficha de uma empresa no módulo: o que existe e os próprios dados. */
export interface RecolhaEmpresaFicha {
  nif: string;
  name?: string | null;
  contracts_count?: number | null;
  total_value?: number | null;
  indexed_publications: number;
  exported: boolean;
  exported_total?: number | null;
  exported_updated_at?: string | null;
  source: RecolhaOrigemDados;
  items: (RecolhaPublicacaoResumo & { has_documento?: boolean; documento_url?: string | null })[];
  items_total: number;
  has_data: boolean;
}

/** Opções de recolha de uma empresa (reutiliza as do trabalho massivo). */
export interface RecolhaEmpresaRequest {
  with_details?: boolean;
  max_pages?: number;
  tipo?: string;
  data_ini?: string | null;
  data_fim?: string | null;
  min_interval?: number;
  rate_limit_pause?: number;
  rate_limit_retries?: number;
  recaptcha_timeout?: number;
  stop_on_captcha?: boolean;
  api_key?: string;
  proxy?: string;
  debug?: boolean;
  ingest?: boolean;
}


export interface RecolhaExportacoes {
  dir: string;
  total: number;
  publications: number;
  bytes: number;
  generated_at?: string | null;
  items: RecolhaFicheiro[];
}

export interface RecolhaPublicacaoResumo {
  pub_id?: string;
  data_publicacao?: string | null;
  acto?: string | null;
  tipo?: string | null;
  tipo_label?: string | null;
  firma?: string | null;
  entidade?: string | null;
  /** Presentes no ficheiro JSON (usados na pré-visualização da ficha). */
  has_documento?: boolean;
  documento_url?: string | null;
}

export interface RecolhaFicheiroConteudo {
  nif: string;
  name?: string | null;
  collected_at?: string | null;
  total?: number;
  items_total?: number;
  criteria?: Record<string, unknown> | null;
  items: RecolhaPublicacaoResumo[];
}

export interface RecolhaIngestao {
  entities: number;
  requested: number;
  indexed: number;
  people: number;
  details: {
    nif: string;
    name?: string | null;
    publications?: number;
    people?: number;
    deleted_stale?: number;
    skipped?: boolean;
    reason?: string;
  }[];
  errors: { nif?: string; error: string }[];
}

// --- leitura ---------------------------------------------------------------

export async function getRecolhaMeta(): Promise<RecolhaMeta> {
  const res = await fetch(`${API_BASE}/societario/recolha/meta`, { signal: AbortSignal.timeout(30000) });
  return ler<RecolhaMeta>(res, "Erro ao obter os metadados da recolha");
}

export async function getRecolhaAnos(): Promise<RecolhaAnos> {
  const res = await fetch(`${API_BASE}/societario/recolha/years`, { signal: AbortSignal.timeout(60000) });
  return ler<RecolhaAnos>(res, "Erro ao obter os anos dos contratos");
}

export async function getRecolhaAlvos(filtros: RecolhaFiltros = {}): Promise<RecolhaAlvos> {
  const params = new URLSearchParams();
  if (filtros.ano_ini) params.set("ano_ini", String(filtros.ano_ini));
  if (filtros.ano_fim) params.set("ano_fim", String(filtros.ano_fim));
  if (filtros.papel) params.set("papel", filtros.papel);
  if (filtros.q) params.set("q", filtros.q);
  (filtros.nifs || []).forEach((nif) => params.append("nifs", nif));
  if (filtros.min_contracts) params.set("min_contracts", String(filtros.min_contracts));
  if (filtros.min_value) params.set("min_value", String(filtros.min_value));
  if (filtros.exclude_collected !== undefined) params.set("exclude_collected", String(filtros.exclude_collected));
  if (filtros.limit) params.set("limit", String(filtros.limit));
  if (filtros.from) params.set("from", String(filtros.from));
  const res = await fetch(`${API_BASE}/societario/recolha/targets?${params}`, {
    signal: AbortSignal.timeout(90000),
  });
  return ler<RecolhaAlvos>(res, "Erro ao listar os alvos da recolha");
}

export async function getRecolhaJobs(): Promise<{ total: number; items: RecolhaJob[] }> {
  const res = await fetch(`${API_BASE}/societario/recolha/jobs`, { signal: AbortSignal.timeout(30000) });
  return ler<{ total: number; items: RecolhaJob[] }>(res, "Erro ao obter os trabalhos de recolha");
}

export async function getRecolhaJob(jobId: string): Promise<RecolhaJob> {
  const res = await fetch(`${API_BASE}/societario/recolha/jobs/${encodeURIComponent(jobId)}`, {
    signal: AbortSignal.timeout(30000),
  });
  return ler<RecolhaJob>(res, "Erro ao obter o trabalho de recolha");
}

export async function getRecolhaExportacoes(): Promise<RecolhaExportacoes> {
  const res = await fetch(`${API_BASE}/societario/recolha/exports`, { signal: AbortSignal.timeout(30000) });
  return ler<RecolhaExportacoes>(res, "Erro ao listar os ficheiros exportados");
}

/** Pesquisa empresas (firma ou NIF) para obter dados societários. */
export async function getRecolhaEmpresas(q: string, limit = 10): Promise<RecolhaEmpresas> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  const res = await fetch(`${API_BASE}/societario/recolha/empresas?${params}`, {
    signal: AbortSignal.timeout(60000),
  });
  return ler<RecolhaEmpresas>(res, "Erro ao pesquisar empresas");
}

/** Ficha de uma empresa no módulo: o que existe e os dados a mostrar. */
export async function getRecolhaEmpresa(nif: string, limitItems = 20): Promise<RecolhaEmpresaFicha> {
  const res = await fetch(
    `${API_BASE}/societario/recolha/empresas/${encodeURIComponent(nif)}?limit_items=${limitItems}`,
    { signal: AbortSignal.timeout(60000) },
  );
  return ler<RecolhaEmpresaFicha>(res, "Erro ao obter a ficha da empresa");
}

export async function getRecolhaFicheiro(nif: string, limitItems = 20): Promise<RecolhaFicheiroConteudo> {
  const res = await fetch(
    `${API_BASE}/societario/recolha/exports/${encodeURIComponent(nif)}?limit_items=${limitItems}`,
    { signal: AbortSignal.timeout(30000) },
  );
  return ler<RecolhaFicheiroConteudo>(res, "Erro ao ler o ficheiro exportado");
}

/** Pausa, retoma ou para um trabalho de recolha em curso (corre no servidor). */
async function controlarRecolhaJob(
  jobId: string,
  acao: "pause" | "resume" | "stop",
  contexto: string,
): Promise<RecolhaJob> {
  const res = await fetch(
    `${API_BASE}/societario/recolha/jobs/${encodeURIComponent(jobId)}/${acao}`,
    { method: "POST", credentials: "include", headers: JSON_HEADERS },
  );
  return ler<RecolhaJob>(res, contexto);
}

export function pausarRecolhaJob(jobId: string): Promise<RecolhaJob> {
  return controlarRecolhaJob(jobId, "pause", "Erro ao pausar a recolha");
}

export function retomarRecolhaJob(jobId: string): Promise<RecolhaJob> {
  return controlarRecolhaJob(jobId, "resume", "Erro ao retomar a recolha");
}

export function pararRecolhaJob(jobId: string): Promise<RecolhaJob> {
  return controlarRecolhaJob(jobId, "stop", "Erro ao parar a recolha");
}

// --- escrita ---------------------------------------------------------------

export async function startRecolhaJob(payload: RecolhaJobRequest): Promise<RecolhaJob> {
  const res = await fetch(`${API_BASE}/societario/recolha/jobs`, {
    method: "POST",
    credentials: "include",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  return ler<RecolhaJob>(res, "Erro ao arrancar a recolha");
}

export async function ingerirRecolhaExportacoes(payload: {
  nifs?: string[];
  with_people?: boolean;
  only_missing?: boolean;
}): Promise<RecolhaIngestao> {
  const res = await fetch(`${API_BASE}/societario/recolha/exports/ingest`, {
    method: "POST",
    credentials: "include",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  return ler<RecolhaIngestao>(res, "Erro ao indexar os ficheiros exportados");
}

/** Recolhe os dados societários de uma empresa (trabalho em segundo plano). */
export async function obterDadosEmpresa(
  nif: string,
  opcoes: RecolhaEmpresaRequest = {},
): Promise<RecolhaJob> {
  const res = await fetch(`${API_BASE}/societario/recolha/empresas/${encodeURIComponent(nif)}/obter`, {
    method: "POST",
    credentials: "include",
    headers: JSON_HEADERS,
    body: JSON.stringify(opcoes),
  });
  return ler<RecolhaJob>(res, "Erro ao arrancar a recolha da empresa");
}

export async function apagarRecolhaFicheiro(nif: string): Promise<{ nif: string; removed: boolean }> {
  const res = await fetch(`${API_BASE}/societario/recolha/exports/${encodeURIComponent(nif)}`, {
    method: "DELETE",
    credentials: "include",
  });
  return ler<{ nif: string; removed: boolean }>(res, "Erro ao apagar o ficheiro exportado");
}
