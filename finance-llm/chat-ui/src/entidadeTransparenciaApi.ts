/**
 * Cliente do módulo **Entidade para a Transparência** (`/entidade-transparencia/*`).
 *
 * A EPT publica as declarações únicas dos titulares de cargos políticos e altos
 * cargos públicos. A pesquisa segue a cascata da própria plataforma —
 * **entidade → cargo → nome do titular** — e cada declaração abre com as
 * secções normalizadas (dados pessoais, rendimentos, ativo, passivo e registo
 * de interesses). A ficha de cada titular liga ao PessoasIQ (`/pessoas-iq`).
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

/** Uma opção do catálogo (entidade, cargo, órgão ou titular). */
export type EptOpcao = { id: string; nome: string };

/** Meta/proveniência do módulo. */
export type EptMeta = {
  fonte: string;
  fonte_url: string;
  api_url: string;
  descricao: string;
  cascata: string[];
  pasta: string;
  catalogo: string;
  normalizados: string;
  indices: string[];
  manifesto: {
    atualizado_em?: string | null;
    totais: Record<string, number>;
    catalogo: Record<string, number | string | null>;
    titulares: number;
  };
  endpoints: Record<string, string>;
  naturezas: Record<string, string>;
  estados: Record<string, string>;
  elasticsearch: boolean;
};

/** Volumetria do módulo. */
export type EptStats = {
  titulares: number;
  declaracoes: number;
  titularidades: number;
  entidades?: number | null;
  cargos?: number | null;
  orgaos?: number | null;
  com_registo_interesses?: number | null;
  atualizado_em?: string | null;
  fonte_indexada: boolean;
  titulares_indexados?: number | null;
  declaracoes_indexadas?: number | null;
  indice_desatualizado?: boolean;
};

/** Trabalho de recolha/indexação. */
export type EptJob = {
  job_id: string;
  tipo: "recolher" | "indexar" | "exportar" | "validar";
  status: "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  payload?: Record<string, unknown>;
  progress?: {
    phase?: string;
    entidades_total?: number;
    entidades_done?: number;
    titulares_total?: number;
    titulares_done?: number;
    declaracoes?: number;
    registos?: number;
    current?: string | null;
  };
  result?: Record<string, unknown> | null;
  error?: string | null;
  already_running?: boolean;
  message?: string;
};

/** Resumo de uma declaração na lista. */
export type EptDeclaracaoResumo = {
  declaracao_id: string;
  titular_id?: string | null;
  titular?: string | null;
  ano?: number | null;
  natureza?: string | null;
  estado?: string | null;
  entidade?: string | null;
  orgao?: string | null;
  cargo?: string | null;
  inicio?: string | null;
  fim?: string | null;
  entrega?: string | null;
  tem_registo_interesses?: boolean;
  doc_id?: string;
};

/** Campo de uma secção da declaração. */
export type EptCampo = { chave: string; rotulo: string; valor: string | number | boolean | null };

/** Tabela de uma secção (registo de interesses, rendimentos, …). */
export type EptTabela = {
  chave: string;
  nome: string;
  colunas?: Record<string, string>;
  registos: Record<string, string>[];
  total?: number;
};

/** Secção normalizada (pode conter subsecções). */
export type EptSecao = {
  chave: string;
  titulo: string;
  campos: EptCampo[];
  tabelas: EptTabela[];
  subsecoes: EptSecao[];
};

/** Declaração completa. */
export type EptDeclaracao = EptDeclaracaoResumo & {
  secoes: EptSecao[];
  interesses: { tipo: string; valores: Record<string, string> }[];
  secoes_inacessiveis?: string[];
  texto?: string;
  fonte?: string;
  url_publica?: string;
  recolhido_em?: string | null;
  ao_vivo?: boolean;
};

/** Correspondência com a ficha do PessoasIQ. */
export type EptPessoaMatch = {
  encontrado: boolean;
  pessoa?: { nif?: string | null; nome?: string | null; fonte?: string | null; partido?: string | null; pontuacao?: number } | null;
  candidatos: { nif?: string | null; nome?: string | null; fonte?: string | null; partido?: string | null; pontuacao: number }[];
  ambiguo?: boolean;
};

/** Ficha do titular. */
export type EptTitular = {
  titular: {
    titular_id: string;
    nome: string;
    nome_normalizado?: string;
    declaracoes_total?: number;
    anos?: number[];
    naturezas?: string[];
    entidades?: string[];
    cargos?: string[];
    orgaos?: string[];
    ultima_declaracao?: string | null;
  };
  posicoes: {
    titularidade_id: string;
    entidade_id?: string | null;
    entidade?: string | null;
    cargo?: string | null;
    inicio?: string | null;
    fim?: string | null;
  }[];
  declaracoes: { total: number; items: EptDeclaracaoResumo[]; ao_vivo?: boolean };
  pessoa: EptPessoaMatch;
  fonte?: string;
  fonte_url?: string;
};

export type EptTitulares = {
  total: number;
  page?: number;
  size?: number;
  items: (EptOpcao & { declaracoes_total?: number; anos?: number[]; entidades?: string[]; cargos?: string[] })[];
  fonte?: string;
};

export type EptDeclaracoes = {
  total: number;
  items: EptDeclaracaoResumo[];
  page: number;
  size: number;
  facetas?: {
    anos?: { valor: number; total: number }[];
    naturezas?: { valor: string; total: number }[];
    entidades?: { valor: string; total: number }[];
    cargos?: { valor: string; total: number }[];
    com_registo_interesses?: number;
  };
  fonte?: string;
};

/* ---------------------------------------------------------------- funções */

export function getEptMeta(): Promise<EptMeta> {
  return pedir("/entidade-transparencia/meta");
}

export function getEptStats(): Promise<EptStats> {
  return pedir("/entidade-transparencia/stats");
}

/** Passo 1: entidades/órgãos. */
export function getEptEntidades(params: { q?: string; forcar?: boolean; limite?: number } = {}): Promise<{ total: number; items: EptOpcao[] }> {
  return pedir(`/entidade-transparencia/entidades${queryString({ limite: 10000, ...params })}`);
}

/** Passo 2: cargos da entidade escolhida. */
export function getEptCargos(params: { entidade_id?: string; q?: string } = {}): Promise<{ total: number; items: EptOpcao[] }> {
  return pedir(`/entidade-transparencia/cargos${queryString(params)}`);
}

/** Órgãos (filtro auxiliar). */
export function getEptOrgaos(params: { entidade_id?: string; cargo_id?: string } = {}): Promise<{ total: number; items: EptOpcao[] }> {
  return pedir(`/entidade-transparencia/orgaos${queryString(params)}`);
}

/** Passo 3: titulares (cascata) ou pesquisa por nome. */
export function getEptTitulares(
  params: { entidade_id?: string; cargo_id?: string; orgao_id?: string; q?: string; page?: number; size?: number; forcar?: boolean } = {},
): Promise<EptTitulares> {
  return pedir(`/entidade-transparencia/titulares${queryString(params)}`);
}

export function getEptTitular(titularId: string, opts: { ao_vivo?: boolean; limite?: number } = {}): Promise<EptTitular> {
  return pedir(`/entidade-transparencia/titular/${encodeURIComponent(titularId)}${queryString(opts)}`);
}

export function recolherEptTitular(titularId: string): Promise<EptJob> {
  return enviar(`/entidade-transparencia/titular/${encodeURIComponent(titularId)}/recolher`);
}

export type EptRecolherParams = {
  entidade_id?: string;
  cargo_id?: string;
  orgao_id?: string;
  titular_id?: string;
  limite_titulares?: number;
  limite_declaracoes?: number;
  forcar?: boolean;
  indexar?: boolean;
};

export function recolherEpt(params: EptRecolherParams = {}): Promise<EptJob> {
  return enviar("/entidade-transparencia/recolher", params);
}

export function indexarEpt(forcar = false): Promise<EptJob> {
  return enviar("/entidade-transparencia/indexar", { forcar });
}

export function exportarEpt(entidades?: string[]): Promise<EptJob> {
  return enviar("/entidade-transparencia/exportar", { entidades });
}

export function getEptExportIndice(): Promise<{
  gerado_em: string;
  totais: { entidades: number; titulares: number; declaracoes: number };
  entidades: { entidade_id: string; entidade: string; ficheiro: string; titulares: number; declaracoes: number }[];
}> {
  return pedir("/entidade-transparencia/exportar/indice");
}

export function eptEntidadeJsonUrl(entidadeId: string): string {
  return `${API_BASE}/entidade-transparencia/entidades/${encodeURIComponent(entidadeId)}/export.json`;
}

export function eptExportIndiceUrl(): string {
  return `${API_BASE}/entidade-transparencia/exportar/indice`;
}

/** Uma verificação da validação (catálogo, cascata ou detalhes). */
export type EptVerificacao = {
  ok?: boolean | null;
  ao_vivo?: number;
  guardados?: number;
  guardadas?: number;
  verificados?: number;
  verificadas?: number;
  em_falta?: number;
  a_mais?: number;
  nomes_divergentes?: number;
  datas_divergentes?: number;
  divergentes?: number;
  divergencias?: number;
  ilegiveis?: number;
  nota?: string;
  amostra?: Record<string, unknown[]>;
};

/** Relatório de validação do catálogo e dos detalhes contra a plataforma. */
export type EptValidacao = {
  gerado_em: string;
  terminado_em?: string | null;
  estado: "ok" | "divergencias";
  fonte: string;
  fonte_url?: string;
  parametros?: Record<string, unknown>;
  resumo: {
    entidades_ao_vivo?: number;
    cargos_ao_vivo?: number;
    titulares_ao_vivo?: number;
    titularidades_ao_vivo?: number;
    entidades_guardadas?: number;
    titulares_guardados?: number;
    fichas_de_titular_guardadas?: number;
    declaracoes_guardadas?: number;
    divergencias: number;
    verificacoes?: Record<string, EptVerificacao>;
  };
  catalogos?: Record<string, EptVerificacao>;
  cascata?: EptVerificacao & Record<string, EptVerificacao | undefined>;
  titularidades?: EptVerificacao;
  detalhes?: { titulares?: EptVerificacao; declaracoes?: EptVerificacao };
  errors?: { fonte?: string; error?: string }[];
  ficheiro?: string;
};

export type EptValidarParams = {
  limite_titulares?: number | null;
  limite_declaracoes?: number | null;
  pausa?: number | null;
};

export function getEptValidacao(): Promise<EptValidacao> {
  return pedir("/entidade-transparencia/validar");
}

export function validarEpt(params: EptValidarParams = {}): Promise<EptJob> {
  return enviar("/entidade-transparencia/validar", params);
}

export function getEptJob(jobId: string): Promise<EptJob> {
  return pedir(`/entidade-transparencia/jobs/${encodeURIComponent(jobId)}`);
}

export function getEptJobs(): Promise<{ total: number; items: EptJob[] }> {
  return pedir("/entidade-transparencia/jobs");
}

export type EptDeclaracoesParams = {
  q?: string;
  titular_id?: string;
  titular?: string;
  entidade?: string;
  cargo?: string;
  orgao?: string;
  ano?: number;
  natureza?: string;
  com_interesses?: boolean;
  sort?: "recent" | "relevance" | "name" | "ano";
  page?: number;
  size?: number;
};

export function getEptDeclaracoes(params: EptDeclaracoesParams = {}): Promise<EptDeclaracoes> {
  return pedir(`/entidade-transparencia/declaracoes${queryString(params as Params)}`);
}

export function getEptDeclaracao(declaracaoId: string, incluirRaw = false): Promise<EptDeclaracao> {
  return pedir(`/entidade-transparencia/declaracoes/${encodeURIComponent(declaracaoId)}${queryString({ incluir_raw: incluirRaw })}`);
}

export type EptPessoaDeclaracoes = {
  nif: string;
  pessoa: { nif?: string | null; nome?: string | null; partido?: string | null } | null;
  titular?: { titular_id?: string | null; nome?: string | null; pontuacao?: number } | null;
  /** Dois titulares praticamente empatados: a ligação por nome não decide. */
  ambiguo?: boolean;
  candidatos?: { titular_id: string; nome: string; pontuacao: number; exato?: boolean }[];
  total_candidatos?: number;
  total: number;
  items: EptDeclaracaoResumo[];
};

export function getEptPessoa(nif: string, size = 100): Promise<EptPessoaDeclaracoes> {
  return pedir(`/entidade-transparencia/pessoa/${encodeURIComponent(nif)}${queryString({ size })}`);
}

export function eptExportUrl(params: EptDeclaracoesParams = {}): string {
  return `${API_BASE}/entidade-transparencia/export.csv${queryString(params as Params)}`;
}
