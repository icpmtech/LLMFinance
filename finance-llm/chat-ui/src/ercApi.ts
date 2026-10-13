/**
 * Cliente do módulo **ERC · Portal da Transparência** (`/erc/*`).
 *
 * O portal da ERC (`portaltransparencia.erc.pt`) publica as **entidades
 * proprietárias de órgãos de comunicação social** (OCS), as **pessoas** dos seus
 * órgãos sociais, os **OCS detidos** e a **estrutura de propriedade** (quem detém
 * quem).
 *
 * O backend **recolhe** a listagem e as fichas (`POST /erc/recolher`), **indexa**
 * os JSONL em `finance_erc_entidades`, `finance_erc_pessoas` e `finance_erc_ocs`
 * (`POST /erc/indexar`) e serve o painel, a pesquisa e as fichas. Sem
 * Elasticsearch, a lista e as fichas continuam a funcionar a partir do disco.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Uma ligação de capital (detentor ou detida). */
export type ErcParticipacao = {
  id?: string | null;
  nome: string;
  e_empresa?: boolean;
  e_pessoa?: boolean;
  /** `detentor` = a contraparte detém o sujeito; `detida` = é detida por ele. */
  tipo_relacao: "detentor" | "detida";
  tipo_detencao?: string | null;
  percentagem?: string | null;
  percentagem_valor?: number | null;
  direitos_voto?: string | null;
  direitos_voto_valor?: number | null;
};

/** Uma pessoa nos órgãos sociais de uma entidade. */
export type ErcPessoaOrgao = {
  id?: string | null;
  nome: string;
  tipo_orgao?: string | null;
  funcao?: string | null;
};

/** Uma empresa onde a pessoa tem cargos. */
export type ErcOrgao = {
  id?: string | null;
  nome: string;
  tipo_orgao?: string | null;
  funcao?: string | null;
};

/** Um órgão de comunicação social detido. */
export type ErcOcs = {
  doc_id?: string;
  designacao: string;
  tipo?: string | null;
  entidade_proprietaria?: string | null;
  entidade_proprietaria_id?: string | null;
  distrito?: string | null;
};

/** Ficha de uma entidade proprietária de OCS. */
export type ErcEntidade = {
  doc_id: string;
  nome: string;
  slug?: string | null;
  url?: string | null;
  tipo_sociedade?: string | null;
  actividade_principal?: string | null;
  distrito?: string | null;
  contabilidade_organizada?: boolean | null;
  detem_ocs?: boolean | null;
  capital_social?: string | null;
  capital_social_eur?: number | null;
  nr_registo?: string | null;
  n_ocs?: number | null;
  n_pessoas?: number | null;
  n_detentores?: number | null;
  n_detidas?: number | null;
  pessoas?: ErcPessoaOrgao[];
  pessoas_nomes?: string[];
  ocs?: ErcOcs[];
  ocs_designacoes?: string[];
  detentores?: ErcParticipacao[];
  detidas?: ErcParticipacao[];
  recolhido_em?: string | null;
};

/** Ficha de uma pessoa regulada. */
export type ErcPessoa = {
  doc_id: string;
  nome: string;
  slug?: string | null;
  url?: string | null;
  actividade_principal?: string | null;
  distrito?: string | null;
  detem_ocs?: boolean | null;
  n_empresas?: number | null;
  n_participacoes?: number | null;
  orgaos?: ErcOrgao[];
  empresas?: string[];
  participacoes?: ErcParticipacao[];
  participacoes_nomes?: string[];
  recolhido_em?: string | null;
};

export type ErcFaceta = { key: string | number; count: number };

export type ErcLista<T> = {
  total: number;
  page?: number;
  size?: number;
  items: T[];
  origem?: "elasticsearch" | "jsonl";
  error?: string;
};

export type ErcMeta = {
  fonte: string;
  portal: string;
  data_dir: string;
  indices: { entidades: string; pessoas: string; ocs: string; recolhas: string };
  contagens: {
    entidades: number;
    pessoas: number;
    ocs: number;
    recolhas: number;
    distritos: number;
    tipos_orgao: string[];
  };
  listagem: { cached_at?: string | null; total_portal?: number | null };
  ficheiros: Record<string, string>;
};

export type ErcResumo = {
  entidades: number;
  pessoas: number;
  ocs: number;
  entidades_sem_ocs: number;
  entidades_com_pessoas: number;
  pessoas_com_cargos: number;
  pessoas_com_participacoes: number;
  distritos: ErcFaceta[];
  tipos_sociedade: ErcFaceta[];
  actividades: ErcFaceta[];
  funcoes: ErcFaceta[];
  tipos_ocs: ErcFaceta[];
};

export type ErcEntidadeResumo = {
  id: string;
  nome: string;
  slug?: string | null;
  tipo_sociedade?: string | null;
  actividade_principal?: string | null;
  distrito?: string | null;
};

export type ErcJob = {
  job_id: string;
  tipo: "recolher" | "indexar";
  status: "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  already_running?: boolean;
  message?: string;
  error?: string | null;
  progress?: {
    phase?: string;
    entidades_total?: number;
    entidades_done?: number;
    pessoas_total?: number;
    pessoas_done?: number;
    registos?: number;
    current?: string | null;
    listagem_em_cache?: boolean;
  };
  result?: Record<string, unknown> | null;
};

export type ErcRecolherParams = {
  limite?: number;
  pausa?: number;
  trabalhadores?: number;
  com_pessoas?: boolean;
  com_estrutura?: boolean;
  com_ocs?: boolean;
  com_financeiro?: boolean;
  guardar_html?: boolean;
  forcar?: boolean;
  saltar_existentes?: boolean;
  indexar?: boolean;
};

export type ErcEntidadeQuery = {
  q?: string;
  distrito?: string;
  tipo_sociedade?: string;
  page?: number;
  size?: number;
};

export type ErcPessoaQuery = {
  q?: string;
  distrito?: string;
  empresa?: string;
  funcao?: string;
  page?: number;
  size?: number;
};

export type ErcOcsQuery = {
  q?: string;
  tipo?: string;
  distrito?: string;
  proprietaria?: string;
  page?: number;
  size?: number;
};

/* ------------------------------------------------------------------ pedidos */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = (body && (body.detail || body.error)) || detail;
    } catch {
      /* corpo não-JSON: fica o código */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/* -------------------------------------------------------------------- API */

/** Estado do módulo: pastas, contagens em disco e índices usados. */
export function getErcMeta(): Promise<ErcMeta> {
  return request<ErcMeta>("/erc/meta");
}

/** Painel: contagens, distritos, tipos de sociedade e funções. */
export function getErcResumo(): Promise<ErcResumo> {
  return request<ErcResumo>("/erc/resumo");
}

/** Entidades anunciadas pelo portal (listagem completa, com cache em disco). */
export function getErcListagem(refrescar = false): Promise<{ total: number; items: ErcEntidadeResumo[] }> {
  return request(`/erc/listagem${refrescar ? "?refrescar=true" : ""}`);
}

/** Recolhe o portal em segundo plano (entidades, pessoas e OCS). */
export function recolherErc(params: ErcRecolherParams = {}): Promise<ErcJob> {
  return post<ErcJob>("/erc/recolher", params);
}

/** Indexa o que está em disco nos índices `finance_erc_*` (segundo plano). */
export function indexarErc(params: { forcar?: boolean } = {}): Promise<ErcJob> {
  return post<ErcJob>("/erc/indexar", params);
}

export function getErcJobs(): Promise<{ total: number; items: ErcJob[] }> {
  return request("/erc/jobs");
}

export function getErcJob(jobId: string): Promise<ErcJob> {
  return request<ErcJob>(`/erc/jobs/${encodeURIComponent(jobId)}`);
}

/** Pesquisa entidades proprietárias de OCS. */
export function buscarEntidades(params: ErcEntidadeQuery = {}): Promise<ErcLista<ErcEntidade>> {
  return request<ErcLista<ErcEntidade>>(`/erc/entidades${queryString({ ...params })}`);
}

/** Ficha da entidade: dados gerais, pessoas, OCS e estrutura de propriedade. */
export function getErcEntidade(entidadeId: string): Promise<ErcEntidade> {
  return request<ErcEntidade>(`/erc/entidades/${encodeURIComponent(entidadeId)}`);
}

/** Pesquisa pessoas reguladas. */
export function buscarPessoas(params: ErcPessoaQuery = {}): Promise<ErcLista<ErcPessoa>> {
  return request<ErcLista<ErcPessoa>>(`/erc/pessoas${queryString({ ...params })}`);
}

/** Ficha da pessoa: cargos (órgãos sociais) e participações diretas. */
export function getErcPessoa(pessoaId: string): Promise<ErcPessoa> {
  return request<ErcPessoa>(`/erc/pessoas/${encodeURIComponent(pessoaId)}`);
}

/** Pesquisa órgãos de comunicação social detidos. */
export function buscarOcs(params: ErcOcsQuery = {}): Promise<ErcLista<ErcOcs>> {
  return request<ErcLista<ErcOcs>>(`/erc/ocs${queryString({ ...params })}`);
}

/** Endereço do CSV (abre num separador; o backend define o ficheiro). */
export function ercExportUrl(tipo: "entidades" | "pessoas" | "ocs" = "entidades"): string {
  return `${API_BASE}/erc/export.csv${queryString({ tipo })}`;
}

/* ------------------------------------------------------------- formatação */

/** Contagem com separador de milhares. */
export function count(valor?: number | null): string {
  return valor === undefined || valor === null ? "—" : valor.toLocaleString("pt-PT");
}

/** Percentagem de detenção (`50,000` → `50%`). */
export function percentagem(valor?: string | number | null, numero?: number | null): string {
  const n = typeof valor === "number" ? valor : numero;
  if (n === undefined || n === null || Number.isNaN(n)) return valor ? `${valor}%` : "—";
  return `${n.toLocaleString("pt-PT", { maximumFractionDigits: 3 })}%`;
}

/** Rótulo do sentido de uma ligação de capital, tal como o portal o apresenta. */
export function relacaoLabel(item: Pick<ErcParticipacao, "tipo_relacao" | "tipo_detencao">): string {
  const base = item.tipo_relacao === "detentor" ? "Detentor" : "Detida";
  return item.tipo_detencao ? `${base} · ${item.tipo_detencao}` : base;
}

/** Data ISO abreviada (`2024-06-01` → `01/06/2024`). */
export function shortDate(iso?: string | null): string {
  if (!iso) return "—";
  const partes = String(iso).slice(0, 10).split("-");
  if (partes.length !== 3) return String(iso);
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}
