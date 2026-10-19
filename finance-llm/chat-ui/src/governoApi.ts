/**
 * Cliente do módulo **Governo** (`/governo/*`).
 *
 * O Governo é recolhido do `portugal.gov.pt` em três peças que se ligam entre si:
 * os **ministérios** (18 — 17 pastas e a Presidência do Conselho), os **membros**
 * da composição (59) e as **nomeações** dos gabinetes (1 021 despachos do Diário
 * da República, com o rendimento bruto e líquido de cada designação).
 *
 * A partir delas o backend constrói o **grafo de relações** (ministério →
 * membro → gabinete → nomeações → pessoas/empresas) e as **fichas**: a de cada
 * membro do Governo (detalhe, remunerações do gabinete e relações) e a de cada
 * pessoa de entidade (cargos, empresas e a ligação ao Governo, quando existe).
 */
import { API_BASE } from "./api";
import type { StudioGraph } from "./components/graph/graphStudio";

/* ------------------------------------------------------------------- tipos */

/** Cartão de um membro do Governo na lista. */
export type GovernoMembroResumo = {
  id: string;
  nome: string;
  nome_oficial?: string | null;
  cargo: string;
  grupo?: string | null;
  area_slug: string;
  area_nome?: string | null;
  foto?: string | null;
  periodo_inicio?: string | null;
  periodo_fim?: string | null;
};

/** Uma pasta do Governo (ministério ou Presidência do Conselho). */
export type GovernoArea = {
  area_slug: string;
  area: string;
  tipo?: string | null;
  titular?: string | null;
  cargo?: string | null;
  secretarios_count?: number | null;
  nomeacoes_count?: number | null;
  url?: string | null;
};

export type GovernoStats = {
  ministerios: number;
  membros: number;
  nomeacoes: number;
  composicao: number;
  scraped: number;
};

type GovernoGraph = {
  nodes: StudioGraph["nodes"];
  edges: StudioGraph["edges"];
  meta: StudioGraph["meta"];
};

export type GovernoOverview = {
  stats: GovernoStats;
  areas: GovernoArea[];
  membros: GovernoMembroResumo[];
  graph: GovernoGraph;
};

/** Linha de remuneração: um despacho de nomeação de alguém do gabinete. */
export type GovernoRemuneracaoLinha = {
  id: string;
  funcao?: string | null;
  nome?: string | null;
  rendimento_bruto_eur?: number | null;
  rendimento_liquido_eur?: number | null;
  data_nomeacao?: string | null;
  dre_url?: string | null;
  dre_titulo?: string | null;
  dre_sumario?: string | null;
};

export type GovernoRemuneracoes = {
  total: number;
  total_bruto_eur: number;
  total_liquido_eur: number;
  media_bruta_eur?: number | null;
  media_liquida_eur?: number | null;
  min_bruta_eur?: number | null;
  max_bruta_eur?: number | null;
  por_funcao: { funcao: string; total: number; bruto: number; liquido: number }[];
  linhas: GovernoRemuneracaoLinha[];
};

/** Relação mostrada na ficha (ministério, gabinete, pessoa ou despacho). */
export type GovernoRelacao = {
  tipo: "ministerio" | "gabinete" | "pessoa" | "dre" | string;
  label?: string | null;
  cargo?: string | null;
  papel?: string | null;
  url?: string | null;
  area_slug?: string | null;
  total?: number | null;
  total_bruto_eur?: number | null;
  nif?: string | null;
  cargos?: number | null;
  empresas?: number | null;
  data?: string | null;
  sumario?: string | null;
};

export type GovernoPessoaCargo = {
  role?: string | null;
  role_org?: string | null;
  company_nif?: string | null;
  company_name?: string | null;
  date?: string | null;
  event?: string | null;
  acto?: string | null;
  tribunal?: string | null;
};

export type GovernoFichaMembro = {
  kind: "membro";
  id: string;
  membro: {
    id: string;
    nome: string;
    nome_oficial?: string | null;
    cargo: string;
    grupo?: string | null;
    area_slug?: string | null;
    area_nome?: string | null;
    periodo_inicio?: string | null;
    periodo_fim?: string | null;
    foto?: string | null;
    biografia?: string | null;
    url?: string | null;
  };
  ministerio?: GovernoArea | null;
  remuneracoes: GovernoRemuneracoes;
  relacoes: GovernoRelacao[];
  pessoa?: Record<string, unknown> | null;
  grafo: GovernoGraph;
};

export type GovernoFichaPessoa = {
  kind: "pessoa";
  id: string;
  pessoa: {
    nif: string;
    nome: string;
    is_company?: boolean;
    roles_count: number;
    companies_count: number;
    companies: { nif: string; name?: string | null }[];
    latest_roles: GovernoPessoaCargo[];
    first_seen?: string | null;
    last_seen?: string | null;
  };
  governo?: { id: string; nome: string; cargo: string; area_slug?: string | null; url?: string | null } | null;
  grafo: GovernoGraph;
};

export type GovernoFicha = GovernoFichaMembro | GovernoFichaPessoa;

/* -------------------------------------------------------------- utilidades */

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

function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Euros em pt-PT (sem decimais acima de mil). */
export function euros(valor?: number | null): string {
  if (valor === undefined || valor === null || Number.isNaN(valor)) return "—";
  return new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: Math.abs(valor) >= 1000 ? 0 : 2,
  }).format(valor);
}

/** Data ISO (`2025-06-05`) escrita à portuguesa. */
export function dataCurta(valor?: string | null): string {
  if (!valor) return "—";
  const [ano, mes, dia] = String(valor).slice(0, 10).split("-");
  if (!ano || !mes || !dia) return String(valor);
  return `${dia}/${mes}/${ano}`;
}

/* ------------------------------------------------------------------- rotas */

/** Visão geral: totais, pastas do Governo, membros e grafo de relações. */
export function fetchGovernoOverview(): Promise<GovernoOverview> {
  return request<GovernoOverview>("/governo/overview");
}

/** Grafo ministério → membro → gabinete (só o grafo). */
export function fetchGovernoGraph(): Promise<{ graph: GovernoGraph; stats: GovernoStats }> {
  return request<{ graph: GovernoGraph; stats: GovernoStats }>("/governo/graph");
}

/** Lista/pesquisa os membros do Governo. */
export function fetchGovernoMembros(params: {
  q?: string;
  area?: string;
  size?: number;
  offset?: number;
} = {}): Promise<{ total: number; items: GovernoMembroResumo[] }> {
  return request<{ total: number; items: GovernoMembroResumo[] }>(
    `/governo/membros${queryString({ q: params.q, area: params.area, size: params.size, offset: params.offset })}`,
  );
}

/** Ficha de um membro do Governo (detalhe, remunerações, relações e grafo). */
export function fetchGovernoMembro(id: string): Promise<GovernoFichaMembro> {
  return request<GovernoFichaMembro>(`/governo/ficha/${encodeURIComponent(id)}`);
}

/** Ficha de uma pessoa de entidade (cargos, empresas, grafo e ligação ao Governo). */
export function fetchGovernoPessoa(nif: string): Promise<GovernoFichaPessoa> {
  return request<GovernoFichaPessoa>(`/governo/pessoa/${encodeURIComponent(nif)}`);
}

/** Pesquisa membros do Governo e pessoas com o mesmo nome. */
export function fetchGovernoPesquisa(
  q: string,
  size = 12,
): Promise<{ q: string; membros: GovernoMembroResumo[]; pessoas: Record<string, unknown>[] }> {
  return request<{ q: string; membros: GovernoMembroResumo[]; pessoas: Record<string, unknown>[] }>(
    `/governo/pesquisa${queryString({ q, size })}`,
  );
}
