/**
 * Cliente do módulo **Grandes Litigantes** (`/grandes-litigantes/*`).
 *
 * Lista anual das sociedades comerciais que intentaram mais de 200 ações,
 * procedimentos ou execuções (Portaria n.º 200/2011, de 20 de maio; n.º 3 do
 * artigo 13.º do Regulamento das Custas Processuais). A consulta pública vive no
 * Portal CITIUS e publica apenas a **faixa** de processos (entre 201 e 500, ou
 * 501 e superior), nunca o número exato por sociedade.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type GrandeLitigante = {
  doc_id?: string;
  nipc: string;
  nipc_digitos?: string;
  denominacao: string;
  denominacao_fold?: string;
  ano: number;
  acoes_texto?: string;
  acoes_min?: number;
  faixa: "201-500" | "501+";
  faixa_label?: string;
  fonte?: string;
  fonte_label?: string;
  source_url?: string;
  collected_at?: string;
  recolha_id?: string;
  ingested_at?: string;
  score?: number;
};

export type GrandesLitigantesSearchResult = {
  total: number;
  page: number;
  size: number;
  items: GrandeLitigante[];
  facets: {
    ano: { key: number; count: number }[];
    faixa: { key: string; count: number }[];
  };
  kpis: {
    registos: number;
    sociedades_distintas: number;
    faixa_201_500: number;
    faixa_501: number;
    anos: number[];
    ano_mais_recente?: number;
  };
};

export type GrandesLitigantesMeta = {
  module: string;
  dir: string;
  dir_env: string;
  json_dir: string;
  index: string;
  recolhas_index: string;
  indice: {
    index?: string;
    registos?: number;
    recolhas_index?: string;
    error?: string;
  };
  recolhas: number;
  registos_recolhidos: number;
  anos: number[];
  ano_mais_recente?: number;
  ultima_recolha?: string | null;
  fonte: {
    id: string;
    label: string;
    url: string;
  };
  faixas: Record<string, string>;
  notes: string;
};

export type GrandesLitigantesFicha = {
  nipc: string;
  nipc_digitos?: string;
  denominacao?: string | null;
  total: number;
  lista: boolean;
  anos: number[];
  items: GrandeLitigante[];
  source_url: string;
};

export type GrandesLitigantesRecolha = {
  recolha_id: string;
  fonte: string;
  source_url: string;
  anos: number[];
  ano_principal?: number;
  total_portal?: number;
  registos: number;
  paginas: number;
  duracao_ms: number;
  collected_at: string;
  json_path: string;
  run_id?: string;
};

export type GrandesLitigantesRecolhas = {
  dir: string;
  dir_env: string;
  generated_at?: string;
  total: number;
  registos: number;
  items: GrandesLitigantesRecolha[];
};

export type GrandesLitigantesSnapshot = {
  base: string;
  bytes: number;
  modificado_em?: string;
  path: string;
};

export type GrandesLitigantesSnapshotDetail = {
  base?: string;
  total?: number;
  registos?: GrandeLitigante[];
  [key: string]: any;
};

export type GrandesLitigantesCollectRequest = {
  termo?: string;
  tipo?: "nipc" | "nome";
  max_paginas?: number;
  indexar?: boolean;
};

export type GrandesLitigantesJob = {
  job_id: string;
  status: string;
  started_at?: string;
  finished_at?: string | null;
  payload?: GrandesLitigantesCollectRequest;
  progress?: {
    phase?: string;
    pagina?: number;
    registos?: number;
    paginas?: number;
    total_portal?: number;
  };
  result?: any;
  error?: string | null;
  already_running?: boolean;
  message?: string;
};

export type GrandesLitigantesIngestRequest = {
  bases?: string[];
};

/* ---------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      const raw = (body && (body.detail || body.error)) || null;
      if (typeof raw === "string") detail = raw;
      else if (raw) detail = JSON.stringify(raw);
    } catch {
      /* corpo não-JSON: fica o código */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function queryString(params: Record<string, any>): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value.forEach((v) => qs.append(key, String(v)));
    } else {
      qs.set(key, String(value));
    }
  });
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/* ------------------------------------------------------------------ API */

export type GrandesLitigantesFontesResponse = {
  fonte: GrandesLitigantesMeta["fonte"];
  faixas: Record<string, string>;
  enquadramento: any;
  ligacoes: { url: string; label?: string }[];
};

export function getGrandesLitigantesMeta() {
  return request<GrandesLitigantesMeta>("/grandes-litigantes/meta");
}

export function getGrandesLitigantesFontes() {
  return request<GrandesLitigantesFontesResponse>("/grandes-litigantes/fontes");
}

export type GrandesLitigantesSearchParams = {
  q?: string;
  nipc?: string;
  ano?: number;
  faixa?: string[];
  sort?: "relevancia" | "nome" | "ano" | "faixa" | "nipc";
  order?: "asc" | "desc";
  page?: number;
  size?: number;
};

export function searchGrandesLitigantes(params: GrandesLitigantesSearchParams = {}) {
  return request<GrandesLitigantesSearchResult>(`/grandes-litigantes/search${queryString(params)}`);
}

export function getGrandesLitigantesSociedade(nipc: string) {
  return request<GrandesLitigantesFicha>(`/grandes-litigantes/sociedade/${encodeURIComponent(nipc)}`);
}

export function getGrandesLitigantesRecolhas() {
  return request<GrandesLitigantesRecolhas>("/grandes-litigantes/recolhas");
}

export function getGrandesLitigantesSnapshots() {
  return request<{ dir: string; total: number; items: GrandesLitigantesSnapshot[] }>("/grandes-litigantes/snapshots");
}

export function getGrandesLitigantesSnapshot(base: string, limitItems = 25) {
  return request<GrandesLitigantesSnapshotDetail>(
    `/grandes-litigantes/snapshots/${encodeURIComponent(base)}?limit_items=${limitItems}`
  );
}

export function startGrandesLitigantesCollect(payload: GrandesLitigantesCollectRequest = {}) {
  return request<GrandesLitigantesJob>("/grandes-litigantes/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function ingestGrandesLitigantes(bases?: string[]) {
  return request<{ total: number; indexados: number; resultados: any[] }>("/grandes-litigantes/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bases }),
  });
}

export function getGrandesLitigantesJobs() {
  return request<{ total: number; items: GrandesLitigantesJob[] }>("/grandes-litigantes/jobs");
}

export function getGrandesLitigantesJob(jobId: string) {
  return request<GrandesLitigantesJob>(`/grandes-litigantes/jobs/${encodeURIComponent(jobId)}`);
}

export function downloadGrandesLitigantesCsv(params: GrandesLitigantesSearchParams & { maximo?: number }): Promise<void> {
  const suffix = queryString(params).replace(/^\?/, "");
  return fetch(`${API_BASE}/grandes-litigantes/export.csv${suffix ? `?${suffix}` : ""}`)
    .then(async (res) => {
      if (!res.ok) throw new Error(`Exportação falhou (HTTP ${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `grandes-litigantes${params.ano ? `-${params.ano}` : ""}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
}

/* ---------------------------------------------------------------- rótulos */

export function faixaLabel(faixa?: string): string {
  if (faixa === "201-500") return "Entre 201 e 500";
  if (faixa === "501+") return "501 ou superior";
  return faixa || "—";
}

export function processosLabel(item?: GrandeLitigante): string {
  return item?.faixa_label || faixaLabel(item?.faixa);
}
