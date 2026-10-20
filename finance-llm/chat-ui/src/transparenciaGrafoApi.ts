/**
 * Cliente do módulo **Grafo da Transparência** (`/transparencia-grafo/*`).
 *
 * Transforma as declarações únicas da Entidade para a Transparência numa rede de
 * **pessoas → cargos → entidades públicas** e nas **empresas** do registo de
 * interesses (atividades, filiação, sociedades, apoios e serviços). Cada empresa
 * traz a sede geocodificada, o que alimenta o mapa das sedes.
 */
import { API_BASE } from "./api";

type Params = Record<string, string | number | boolean | null | undefined>;

function queryString(params: Params = {}): string {
  const partes = Object.entries(params)
    .filter(([, valor]) => valor !== undefined && valor !== null && valor !== "")
    .map(([chave, valor]) => `${encodeURIComponent(chave)}=${encodeURIComponent(String(valor))}`);
  return partes.length ? `?${partes.join("&")}` : "";
}

async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  if (!resposta.ok) {
    const detalhe = await resposta.text().catch(() => "");
    throw new Error(`${resposta.status} — ${detalhe || resposta.statusText}`);
  }
  return (await resposta.json()) as T;
}

function enviar<T>(path: string, corpo?: unknown): Promise<T> {
  return pedir<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo ?? {}),
  });
}

/* ------------------------------------------------------------------- tipos */

export type TgTipoNo = "pessoa" | "cargo" | "entidade" | "empresa";

export type TgTipoInfo = { label: string; curto: string; cor: string };
export type TgRelacaoInfo = { label: string; curto: string };

export type TgMeta = {
  fonte: string;
  fonte_url: string;
  descricao: string;
  pasta: string;
  declaracoes: string;
  ficheiros: Record<string, string>;
  indices: string[];
  tipos: Record<string, TgTipoInfo>;
  relacoes: Record<string, TgRelacaoInfo>;
  precisoes: Record<string, string>;
  manifesto: {
    atualizado_em?: string | null;
    declaracoes_lidas?: number | null;
    totais: Record<string, number>;
    relacoes: Record<string, number>;
  };
  endpoints: Record<string, string>;
  elasticsearch: boolean;
};

export type TgStats = {
  nos: number;
  arestas: number;
  pessoas?: number;
  cargos?: number;
  entidades?: number;
  empresas?: number;
  com_geo?: number;
  atualizado_em?: string | null;
  declaracoes_lidas?: number | null;
  relacoes?: Record<string, number>;
  concelhos?: { concelho: string; lat: number; lon: number; empresas: number }[];
  indice?: { nos: number | null; arestas: number | null };
  fonte_indexada?: boolean;
  indice_desatualizado?: boolean;
};

/** Nó no formato dos grafos partilhados (ver `ContractGraphBuildNode`). */
export type TgNo = {
  id: string;
  key: string | null;
  label: string;
  dimension: string;
  type: TgTipoNo | string;
  count: number;
  total_value: number;
  grau: number;
  peso: number;
  nif?: string | null;
  concelho?: string | null;
  lat?: number | null;
  lon?: number | null;
  precisao_geo?: string | null;
  anos?: number[];
  declaracoes?: number;
};

export type TgAresta = {
  source: string;
  target: string;
  count: number;
  value: number;
  relation: string;
  relacao: string;
  anos?: number[];
};

export type TgGrafoResposta = {
  nodes: TgNo[];
  edges: TgAresta[];
  meta: {
    total_nos?: number;
    total_arestas?: number;
    total_empresas?: number;
    documents_scanned?: number;
    documents_matching?: number;
    sample_limit?: number;
    filtros?: Record<string, unknown>;
    tipos?: Record<string, TgTipoInfo>;
    relacoes?: Record<string, TgRelacaoInfo>;
  };
  error?: string;
};

export type TgVizinho = {
  no: TgNo;
  sentido: "entrada" | "saida";
  relacao: string;
  relacao_label: string;
  peso: number;
  anos: number[];
  detalhe: Record<string, unknown>;
};

export type TgNoDetalhe = {
  no: {
    no_id: string;
    tipo: string;
    subtipo?: string | null;
    nome: string;
    ref_id?: string | null;
    nif?: string | null;
    nif_entidade?: string | null;
    url?: string | null;
    anos?: number[];
    declaracoes?: number;
    grau?: number;
    peso?: number;
    local_sede?: string | null;
    concelho?: string | null;
    precisao_geo?: string | null;
    lat?: number | null;
    lon?: number | null;
    detalhes?: Record<string, unknown>;
  };
  vizinhos: TgVizinho[];
  total_vizinhos: number;
  error?: string;
};

export type TgEmpresa = {
  no_id: string;
  nome: string;
  tipo: string;
  nif?: string | null;
  local_sede?: string | null;
  concelho?: string | null;
  precisao_geo?: string | null;
  precisao_label?: string | null;
  lat?: number | null;
  lon?: number | null;
  ligacoes: number;
  anos: number[];
  detalhes: Record<string, unknown>;
};

export type TgEmpresasResposta = {
  total: number;
  offset: number;
  limit: number;
  items: TgEmpresa[];
};

export type TgMapaResposta = {
  total: number;
  com_geo: number;
  sem_geo: number;
  /** Entidades do mesmo tipo/filtro que não têm coordenadas (não vão ao mapa). */
  sem_geo_itens: TgEmpresa[];
  pontos: TgEmpresa[];
  concelhos: {
    concelho: string;
    lat: number;
    lon: number;
    empresas: number;
    ligacoes: number;
  }[];
  total_concelhos: number;
  precisoes: Record<string, string>;
};

export type TgJob = {
  job_id: string;
  tipo: "construir" | "indexar";
  status: "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  payload?: Record<string, unknown>;
  progress?: {
    phase?: string;
    current?: string | null;
    declaracoes?: number;
    titularidades?: number;
    registos?: number;
  };
  result?: Record<string, unknown> | null;
  error?: string | null;
};

/* ------------------------------------------------------------------- calls */

export const getTgMeta = () => pedir<TgMeta>("/transparencia-grafo/meta");
export const getTgStats = () => pedir<TgStats>("/transparencia-grafo/stats");

export const getTgGrafo = (params: {
  tipo?: string;
  relacao?: string;
  q?: string;
  ano?: number | null;
  nif?: string;
  foco?: string;
  profundidade?: number;
  min_peso?: number;
  limit?: number;
  edge_limit?: number;
}) => pedir<TgGrafoResposta>(`/transparencia-grafo/grafo${queryString(params)}`);

export const getTgNo = (noId: string) =>
  pedir<TgNoDetalhe>(`/transparencia-grafo/nos/${encodeURIComponent(noId)}`);

export const getTgEmpresas = (params: {
  q?: string;
  concelho?: string;
  com_geo?: boolean;
  tipo?: string;
  ordenar?: string;
  limit?: number;
  offset?: number;
}) => pedir<TgEmpresasResposta>(`/transparencia-grafo/empresas${queryString(params)}`);

export const getTgMapa = (params: { q?: string; concelho?: string; tipo?: string; limite_pontos?: number }) =>
  pedir<TgMapaResposta>(`/transparencia-grafo/mapa${queryString(params)}`);

export const construirTg = (payload: { forcar?: boolean; indexar?: boolean; limite_declaracoes?: number | null }) =>
  enviar<TgJob>("/transparencia-grafo/construir", payload);

export const indexarTg = () => enviar<TgJob>("/transparencia-grafo/indexar");

export const getTgJob = (jobId: string) => pedir<TgJob>(`/transparencia-grafo/jobs/${encodeURIComponent(jobId)}`);

export const tgExportUrl = (params: { vista?: string; q?: string; concelho?: string; tipo?: string; no_tipo?: string }) =>
  `${API_BASE}/transparencia-grafo/export.csv${queryString(params)}`;
