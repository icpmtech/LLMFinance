/**
 * Módulo **Recolha de Empresas** — recolha massiva de diretórios web
 * (ex.: Iberinform.pt) para ficheiros `.json` organizados por distrito/concelho.
 *
 * Os trabalhos correm em segundo plano; a UI pode consultar o estado pelo
 * `job_id` e listar as exportações existentes.
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

export interface EmpresasRecolhaMeta {
  module: string;
  export_dir: string;
  export_dir_env: string;
  districts: string[];
}

export interface EmpresasRecolhaResult {
  ok: boolean;
  distrito: string;
  concelho: string;
  start_page: number;
  max_pages: number;
  run_id: string;
  source_id: string;
  file: string;
  items_count: number;
  meta: Record<string, unknown>;
  error?: string;
}

export interface EmpresasRecolhaRequest {
  distrito: string;
  concelho: string;
  start_page?: number;
  max_pages?: number;
  detail?: boolean;
  delay?: number;
  ingest?: boolean;
}

export interface EmpresasRecolhaJob {
  job_id: string;
  status: "pending" | "running" | "done" | "error" | string;
  started_at?: string | null;
  finished_at?: string | null;
  payload?: EmpresasRecolhaRequest;
  result?: EmpresasRecolhaResult | null;
  error?: string | null;
}

export interface EmpresasRecolhaExportFile {
  distrito?: string | null;
  concelho?: string | null;
  file: string;
  path: string;
  bytes: number;
  mtime: string;
}

export interface EmpresasRecolhaExports {
  total: number;
  files: EmpresasRecolhaExportFile[];
  export_dir: string;
}

export interface EmpresasRecolhaExportContent {
  distrito: string;
  concelho: string;
  start_page: number;
  max_pages: number;
  run_id: string;
  source_id: string;
  collected_at: string;
  meta: Record<string, unknown>;
  items: EmpresasRecolhaItem[];
  path: string;
}

export interface EmpresasRecolhaItem {
  item_id?: string;
  url?: string;
  title?: string;
  summary?: string;
  text?: string;
  detail?: boolean;
  data?: Record<string, unknown>;
}

// --- API -------------------------------------------------------------------

export async function getEmpresasRecolhaMeta(): Promise<EmpresasRecolhaMeta> {
  return ler<EmpresasRecolhaMeta>(await fetch(`${API_BASE}/empresas-recolha/meta`), "meta");
}

export async function getEmpresasRecolhaConcelhos(distrito: string): Promise<{ distrito: string; concelhos: string[] }> {
  return ler<{ distrito: string; concelhos: string[] }>(
    await fetch(`${API_BASE}/empresas-recolha/concelhos/${encodeURIComponent(distrito)}`),
    "concelhos",
  );
}

export async function listEmpresasRecolhaJobs(limit = 20): Promise<{ jobs: EmpresasRecolhaJob[] }> {
  return ler<{ jobs: EmpresasRecolhaJob[] }>(
    await fetch(`${API_BASE}/empresas-recolha/jobs?limit=${limit}`),
    "jobs",
  );
}

export async function getEmpresasRecolhaJob(jobId: string): Promise<EmpresasRecolhaJob> {
  return ler<EmpresasRecolhaJob>(await fetch(`${API_BASE}/empresas-recolha/jobs/${encodeURIComponent(jobId)}`), "job");
}

export async function startEmpresasRecolhaJob(req: EmpresasRecolhaRequest): Promise<{ job_id: string; status: string }> {
  return ler<{ job_id: string; status: string }>(
    await fetch(`${API_BASE}/empresas-recolha/jobs`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),
    "start job",
  );
}

export async function runEmpresasRecolhaSync(req: EmpresasRecolhaRequest): Promise<EmpresasRecolhaResult> {
  return ler<EmpresasRecolhaResult>(
    await fetch(`${API_BASE}/empresas-recolha/sync`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),
    "sync",
  );
}

export async function listEmpresasRecolhaExports(
  distrito?: string,
  concelho?: string,
  limit = 100,
): Promise<EmpresasRecolhaExports> {
  const params = new URLSearchParams();
  if (distrito) params.set("distrito", distrito);
  if (concelho) params.set("concelho", concelho);
  params.set("limit", String(limit));
  return ler<EmpresasRecolhaExports>(
    await fetch(`${API_BASE}/empresas-recolha/exports?${params.toString()}`),
    "exports",
  );
}

export async function readEmpresasRecolhaExport(path: string): Promise<EmpresasRecolhaExportContent> {
  return ler<EmpresasRecolhaExportContent>(
    await fetch(`${API_BASE}/empresas-recolha/exports/view?path=${encodeURIComponent(path)}`),
    "export view",
  );
}

export async function previewEmpresaDetail(url: string): Promise<EmpresasRecolhaItem> {
  return ler<EmpresasRecolhaItem>(
    await fetch(`${API_BASE}/empresas-recolha/detail`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ url }),
    }),
    "detail",
  );
}
