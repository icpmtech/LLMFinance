/**
 * Módulo **Devedores** — listas públicas de devedores das Finanças e da
 * Segurança Social.
 *
 * - **Recolha** (`/devedores/collect`, `…/jobs`) — descarrega os PDF oficiais das
 *   Finanças (12 escalões), guarda o **PDF** e **um `.json` por ficheiro** (com a
 *   **data da recolha**) e indexa em `finance_devedores`;
 * - **Pesquisa** (`/devedores/search`, `…/devedor/{nif}`) — usada na área de
 *   pesquisa e na ficha de cada pessoa/empresa do PessoasIQ.
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

export type DevedoresEntidade = "financas" | "seguranca_social";
export type DevedoresTipo = "singulares" | "coletivos";

export interface DevedoresMeta {
  module: string;
  export_dir: string;
  export_dir_env: string;
  pdf_dir: string;
  json_dir: string;
  index: string;
  indice?: { index?: string; registos?: number; recolhas_index?: string; error?: string };
  recolhas: number;
  ficheiros: number;
  registos_recolhidos: number;
  ultima_recolha?: string | null;
  fontes: { financas: number; seguranca_social: number };
  notes: string;
}

export interface DevedoresFicheiroFonte {
  ficheiro: string;
  entidade: DevedoresEntidade;
  tipo: DevedoresTipo;
  tipo_label: string;
  escalao: string;
  valor_min?: number | null;
  valor_max?: number | null;
  url: string;
  recolhido: boolean;
  collected_at?: string | null;
  registos?: number | null;
  lista_atualizada_em?: string | null;
}

export interface DevedoresFontes {
  entidades: Record<string, string>;
  tipos: Record<string, string>;
  financas: {
    pagina: string;
    base: string;
    ficheiros: DevedoresFicheiroFonte[];
    total: number;
    recolhidos: number;
  };
  seguranca_social: {
    url: string;
    escaloes: { chave: string; escalao: string; valor_min?: number | null; valor_max?: number | null }[];
    tipos: { chave: string; tipo: string }[];
    recolhido: boolean;
    nota: string;
  };
  ficheiros_recolhidos: string[];
}

export interface DevedoresRecolha {
  recolha_id: string;
  ficheiro: string;
  base: string;
  entidade: DevedoresEntidade;
  tipo: DevedoresTipo;
  tipo_label?: string | null;
  escalao: string;
  valor_min?: number | null;
  valor_max?: number | null;
  lista_atualizada_em?: string | null;
  collected_at: string;
  registos: number;
  paginas?: number | null;
  pdf_bytes?: number | null;
  pdf_sha256?: string | null;
  pdf_path?: string | null;
  json_path?: string | null;
  source_url?: string | null;
  last_modified?: string | null;
}

export interface DevedoresRecolhas {
  dir: string;
  dir_env: string;
  generated_at?: string | null;
  total: number;
  registos: number;
  items: DevedoresRecolha[];
}

export interface DevedorRegisto {
  doc_id: string;
  nif: string;
  nome: string;
  entidade: DevedoresEntidade;
  entidade_label?: string | null;
  tipo: DevedoresTipo;
  tipo_label?: string | null;
  escalao: string;
  valor_min?: number | null;
  valor_max?: number | null;
  ficheiro: string;
  base?: string | null;
  source_url?: string | null;
  lista_atualizada_em?: string | null;
  collected_at: string;
  pagina?: number | null;
  score?: number | null;
}

export interface DevedoresKpis {
  registos: number;
  devedores_distintos: number;
  ficheiros: number;
  singulares: number;
  coletivos: number;
  financas: number;
  seguranca_social: number;
  ultima_lista?: string | null;
  ultima_recolha?: string | null;
}

export interface DevedoresFaceta {
  key: string | number;
  count: number;
  valor_min?: number | null;
}

export interface DevedoresSearchResponse {
  total: number;
  page: number;
  size: number;
  items: DevedorRegisto[];
  facets: {
    tipo: DevedoresFaceta[];
    entidade: DevedoresFaceta[];
    escalao: DevedoresFaceta[];
    ficheiro: DevedoresFaceta[];
    lista_atualizada_em: DevedoresFaceta[];
    collected_at: DevedoresFaceta[];
  };
  kpis: DevedoresKpis;
  error?: string;
}

export interface DevedoresSearchParams {
  q?: string;
  nif?: string;
  entidade?: string;
  tipo?: string;
  escalao?: string[];
  valor_minimo?: number;
  ficheiro?: string;
  lista_atualizada_em?: string;
  collected_from?: string;
  collected_to?: string;
  sort?: "relevancia" | "nome" | "escalao" | "recolha" | "lista";
  order?: "asc" | "desc";
  page?: number;
  size?: number;
}

export interface DevedorFicha {
  nif: string;
  nome?: string | null;
  total: number;
  entidades: string[];
  escaloes: string[];
  maior_valor_min?: number | null;
  devedor: boolean;
  items: DevedorRegisto[];
  error?: string;
}

export interface DevedoresJob {
  job_id: string;
  status: "running" | "done" | "error";
  started_at: string;
  finished_at?: string | null;
  payload: Record<string, unknown>;
  progress: {
    phase: string;
    ficheiros_done: number;
    registos: number;
    current?: { ficheiro?: string; escalao?: string } | null;
  };
  result?: {
    registos?: number;
    errors?: { ficheiro?: string; error: string }[];
    falhas?: string[];
    entidades?: Record<string, { registos?: number; errors?: { ficheiro?: string; error: string }[]; error?: string }>;
  } | null;
  error?: string | null;
  already_running?: boolean;
  message?: string;
}

// --- chamadas ---------------------------------------------------------------

export async function devedoresMeta(): Promise<DevedoresMeta> {
  const res = await fetch(`${API_BASE}/devedores/meta`, { signal: AbortSignal.timeout(30000) });
  return ler<DevedoresMeta>(res, "Metadados dos devedores");
}

export async function devedoresFontes(): Promise<DevedoresFontes> {
  const res = await fetch(`${API_BASE}/devedores/fontes`, { signal: AbortSignal.timeout(30000) });
  return ler<DevedoresFontes>(res, "Fontes dos devedores");
}

export async function devedoresRecolhas(): Promise<DevedoresRecolhas> {
  const res = await fetch(`${API_BASE}/devedores/files`, { signal: AbortSignal.timeout(30000) });
  return ler<DevedoresRecolhas>(res, "Recolhas de devedores");
}

export function devedoresPdfUrl(base: string): string {
  return `${API_BASE}/devedores/files/${encodeURIComponent(base)}/pdf`;
}

export async function devedoresSearch(params: DevedoresSearchParams): Promise<DevedoresSearchResponse> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([chave, valor]) => {
    if (valor === undefined || valor === null || valor === "") return;
    if (Array.isArray(valor)) {
      valor.forEach((item) => query.append(chave, String(item)));
      return;
    }
    query.set(chave, String(valor));
  });
  const res = await fetch(`${API_BASE}/devedores/search?${query.toString()}`, {
    signal: AbortSignal.timeout(60000),
  });
  return ler<DevedoresSearchResponse>(res, "Pesquisa de devedores");
}

export async function devedorPorNif(nif: string): Promise<DevedorFicha> {
  const res = await fetch(`${API_BASE}/devedores/devedor/${encodeURIComponent(nif)}`, {
    signal: AbortSignal.timeout(30000),
  });
  return ler<DevedorFicha>(res, "Ficha de devedor");
}

export interface DevedoresCollectPayload {
  entidades?: DevedoresEntidade[];
  ficheiros?: string[];
  forcar?: boolean;
  escaloes_ss?: string[];
  tipos_ss?: string[];
  max_paginas?: number;
}

export async function devedoresCollect(payload: DevedoresCollectPayload): Promise<DevedoresJob> {
  const res = await fetch(`${API_BASE}/devedores/collect`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30000),
  });
  return ler<DevedoresJob>(res, "Recolha de devedores");
}

export async function devedoresJobs(): Promise<{ total: number; items: DevedoresJob[] }> {
  const res = await fetch(`${API_BASE}/devedores/jobs`, { signal: AbortSignal.timeout(30000) });
  return ler<{ total: number; items: DevedoresJob[] }>(res, "Trabalhos de devedores");
}

export async function devedoresJob(jobId: string): Promise<DevedoresJob> {
  const res = await fetch(`${API_BASE}/devedores/jobs/${encodeURIComponent(jobId)}`, {
    signal: AbortSignal.timeout(30000),
  });
  return ler<DevedoresJob>(res, "Trabalho de devedores");
}

export async function devedoresIngest(bases?: string[]): Promise<{ ficheiros: number; registos: number; errors: unknown[] }> {
  const res = await fetch(`${API_BASE}/devedores/ingest`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ bases: bases ?? null }),
    signal: AbortSignal.timeout(600000),
  });
  return ler(res, "Indexação dos devedores");
}
