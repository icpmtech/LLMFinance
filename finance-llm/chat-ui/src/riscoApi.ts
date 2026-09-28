/**
 * Cliente da API de **Empresas & Risco** — `/risco/*`.
 *
 * O módulo dá a cada empresa adjudicatária um **nível de risco** de 0 a 100
 * (regras calibradas nos dados + ML não supervisionado sobre a população de
 * referência), associa-lhe os contratos, compara várias empresas e desenha o
 * grafo analítico 360 (compradores, órgãos sociais, processos do CIRE).
 *
 * Nada aqui julga empresas: o número é uma **prioridade de análise** calculada
 * com dados públicos do portal — o `cartao_modelo` explica os pesos e limiares.
 */
import { API_BASE } from "./api";
import type { ContractGraphBuildResponse } from "./types";

/** Níveis possíveis, do mais baixo ao mais alto. */
export type RiscoNivel = "baixo" | "moderado" | "elevado" | "muito_elevado" | "critico";

/** Um componente do risco (o que puxa o número para cima ou para baixo). */
export type RiscoComponente = {
  id: string;
  label: string;
  peso: number;
  peso_efetivo?: number;
  contributo?: number;
  descricao?: string;
  metodo?: string;
  unidade?: string;
  /** Pontos 0–100 do componente; `null` quando não há dados. */
  pontos: number | null;
  evidencia: string[];
  disponivel: boolean;
};

/** Modelo de anomalia (IsolationForest) da empresa face às suas pares. */
export type RiscoMl = {
  disponivel: boolean;
  motivo?: string;
  algoritmo?: string;
  n_referencia?: number;
  features?: string[];
  percentil?: number | null;
  score_bruto?: number | null;
  mediana_referencia?: number | null;
  nota?: string;
};

/** Cartão do modelo: pesos, limiares, faixas e o aviso obrigatório. */
export type RiscoCartaoModelo = {
  versao: string;
  rotulo: string;
  aviso: string;
  limiar_aditivo: number;
  componentes: {
    id: string;
    label: string;
    peso: number;
    limiar_zero: number;
    limiar_saturacao: number;
    unidade: string;
    metodo: string;
    descricao: string;
  }[];
  niveis: { id: RiscoNivel; label: string; max: number; cor: string }[];
  metodos: Record<string, { label: string; descricao: string }>;
};

/** O risco calculado de uma empresa. */
export type RiscoAvaliacao = {
  score: number | null;
  nivel: RiscoNivel | null;
  nivel_label: string;
  cor: string;
  faixa?: string;
  cobertura: number;
  confianca: string;
  metodo: "triagem" | "detalhado" | string;
  metodo_label?: string;
  componentes: RiscoComponente[];
  fatores: RiscoComponente[];
  features: Record<string, number | string | null | undefined | number[]>;
  ml?: RiscoMl | null;
  modelo_supervisionado?: {
    disponivel: boolean;
    auc?: number | null;
    lift_top_decile?: number | null;
    rotulo?: string | null;
    aviso?: string | null;
    contratos?: number | null;
  } | null;
  cartao_modelo?: RiscoCartaoModelo;
  avisos?: string[];
  gerado_em?: string;
};

/** Risco de um contrato concreto (o que liga os contratos ao risco da empresa). */
export type RiscoContrato = {
  id?: string | null;
  ano?: number | null;
  data_publicacao?: string | null;
  objeto?: string | null;
  valor?: number | null;
  valor_efetivo?: number | null;
  ratio_base?: number | null;
  ratio_efetivo?: number | null;
  procedimento?: string | null;
  ajuste_direto?: boolean;
  cpv?: string | null;
  cpv_desc?: string | null;
  n_concorrentes?: number | null;
  dias_assinatura?: number | null;
  dias_publicacao?: number | null;
  z_cpv?: number | null;
  adjudicante?: string | null;
  adjudicante_nif?: string | null;
  severidade?: string | null;
  sinais?: string[];
  risco?: { score: number | null; nivel: string | null; nivel_label: string; cor: string; razoes: string[] } | null;
};

/** Resumo do portefólio da empresa (mesma forma em todos os módulos). */
export type RiscoResumo = {
  contratos?: number | null;
  valor_total?: number | null;
  valor_mediano?: number | null;
  desvio_mediano?: number | null;
  taxa_ajuste_direto?: number | null;
  taxa_aditivo?: number | null;
  adjudicantes_distintos?: number | null;
  concentracao_adjudicante?: number | null;
  contratos_com_sinais?: number | null;
  contratos_atipicos_cpv?: number | null;
  insolvente?: boolean;
};

/** Relações da empresa (compradores, pessoas, insolvências, menções). */
export type RiscoRelacoes = {
  cargos_sociais?: { nif?: string; nome?: string; cargos?: { role?: string; role_org?: string }[] }[];
  insolvencias?: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
  noticias?: { titulo?: string; fonte?: string; data?: string; url?: string }[];
  empresas?: { nif?: string; nome?: string; contratos?: number; adjudicante?: string }[];
  intervenientes_cire?: { nif?: string; nome?: string; cargos?: { role?: string }[] }[];
};

/** Resultado da pontuação de uma empresa (triagem ou dossiê). */
export type RiscoEmpresa = {
  pais: string;
  pais_label?: string;
  nif: string;
  nome: string;
  ficha?: Record<string, unknown> | null;
  contratos_total?: number | null;
  contratos_analisados?: number | null;
  anos?: number[] | null;
  cadastro?: Record<string, unknown> | null;
  risco: RiscoAvaliacao;
  /** Linha comparável do dossiê (sem contratos) — presente quando `detalhado`. */
  analise?: RiscoLinha | null;
  /** Dossiê completo: contratos associados, com risco por contrato. */
  contratos?: RiscoContrato[] | null;
  /** Processos do CIRE em que a empresa é **a insolvente** (não credora). */
  insolvencias?: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string; papel?: string }[] | null;
  contratos_resumo?: { total: number; por_nivel: Record<string, number>; mais_50: number } | null;
  resumo?: RiscoResumo | null;
  sinais?: { padrao?: string; label?: string | null; severidade?: string | null; contratos?: number; taxa?: number | null; exemplos?: { id?: string; objeto?: string; ano?: number; valor?: number; detalhe?: string }[] }[] | null;
  relacoes?: RiscoRelacoes | null;
  adjudicantes?: { nif?: string | null; nome?: string | null; contratos?: number; valor?: number }[] | null;
  por_cpv?: { cpv?: string; descricao?: string | null; contratos?: number; valor?: number }[] | null;
  por_procedimento?: { procedimento?: string; contratos?: number; valor?: number }[] | null;
  cache?: boolean;
};

/** Linha comparável de uma empresa (forma de `padroes._linha_conjunto`). */
export type RiscoLinha = {
  nif?: string | null;
  nome?: string | null;
  pais?: string | null;
  pais_label?: string | null;
  anos?: number[] | null;
  contratos_total?: number | null;
  contratos_analisados?: number | null;
  resumo?: {
    contratos?: number | null;
    valor_total?: number | null;
    valor_mediano?: number | null;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    taxa_aditivo?: number | null;
    adjudicantes_distintos?: number | null;
    concentracao_adjudicante?: number | null;
    contratos_com_sinais?: number | null;
    contratos_atipicos_cpv?: number | null;
    insolvente?: boolean;
  } | null;
  severidade?: string | null;
  sinais?: { padrao?: string; label?: string | null; severidade?: string | null; contratos?: number; exemplo?: string | null; detalhe?: string | null }[];
  adjudicantes?: { nif?: string | null; nome?: string | null; contratos?: number; valor?: number }[];
  por_cpv?: { cpv?: string; descricao?: string | null; contratos?: number; valor?: number }[];
  por_procedimento?: { procedimento?: string; contratos?: number; valor?: number }[];
  por_ano?: { ano?: number; contratos?: number; valor?: number }[];
  relacoes?: {
    cargos_sociais?: { nif?: string; nome?: string; cargos?: { role?: string; role_org?: string }[] }[];
    insolvencias?: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
    noticias?: { titulo?: string; fonte?: string; data?: string; url?: string }[];
    empresas?: { nif?: string; nome?: string; contratos?: number; adjudicante?: string }[];
  } | null;
  /** Só na comparação: o risco calculado para a empresa. */
  risco?: RiscoAvaliacao | null;
  /** Insolvências da empresa (CIRE, papel «Insolvente»). */
  insolvencias?: number | null;
  erro?: string | null;
};

/** Item da pesquisa tipo motor de busca. */
export type RiscoPesquisaItem = {
  nif: string;
  nome: string;
  names?: string[];
  pais?: string | null;
  pais_label?: string | null;
  tipo?: string | null;
  roles?: string[];
  local?: { concelho?: string; distrito?: string; pais?: string } | null;
  contratos?: number | null;
  valor?: number | null;
  fontes?: string[];
  contratos_total?: number | null;
  contratos_analisados?: number | null;
  anos?: number[] | null;
  risco?: RiscoAvaliacao | null;
  erro?: string | null;
};

export type RiscoPesquisa = {
  query: string;
  total: number;
  /** Quantas empresas ficaram disponíveis para navegar (com risco calculado). */
  disponiveis?: number;
  /** `true` quando nenhuma empresa casou com todas as palavras do pedido. */
  parcial?: boolean;
  from?: number;
  size?: number;
  ordenar?: string;
  nivel?: string | null;
  detalhado?: boolean;
  itens: RiscoPesquisaItem[];
  facetas?: { nivel: RiscoNivel | string; label: string; cor: string; total: number }[];
  sugestoes?: RiscoSugestao[];
  cartao_modelo?: RiscoCartaoModelo;
  avisos?: string[];
  error?: string;
};

export type RiscoSugestao = {
  nif: string;
  nome: string;
  tipo?: string | null;
  tipo_label?: string | null;
  contratos?: number | null;
  fontes?: string[];
};

export type RiscoSugestoes = { query: string; itens: RiscoSugestao[] };

export type RiscoMeta = {
  modulo: string;
  versao: string;
  cartao_modelo: RiscoCartaoModelo;
  metodos: Record<string, { label: string; descricao: string }>;
  ml: { disponivel: boolean; algoritmos: string[]; biblioteca?: string | null; features: string[] };
  fontes: string[];
  cache: { ttl_segundos: number; entradas: number };
  ia?: Record<string, unknown>;
};

/** Comparação de várias empresas com risco, cruzamentos e rede. */
export type RiscoComparacao = {
  pais?: string;
  pais_label?: string;
  empresas: RiscoLinha[];
  ranking?: { nif?: string | null; nome?: string | null; risco?: RiscoAvaliacao | null }[];
  totais?: Record<string, number | null>;
  cruzamentos?: {
    adjudicantes?: { nif?: string; nome?: string; empresas?: string[]; contratos?: number; valor?: number }[];
    pessoas?: { nif?: string; nome?: string; cargos?: string[]; empresas?: string[] }[];
    processos?: { processo?: string; especie?: string; tribunal?: string; data?: string; empresas?: string[] }[];
    cpv?: { cpv?: string; descricao?: string; empresas?: string[] }[];
  } | null;
  por_cpv?: { cpv?: string; descricao?: string | null; contratos?: number; valor?: number; empresas?: number }[];
  grafo?: ContractGraphBuildResponse | null;
  risco_resumo?: {
    empresas: number;
    com_risco: number;
    score_medio: number | null;
    score_maximo: number | null;
    por_nivel: Record<string, number>;
    criticas: { nif?: string | null; nome?: string | null; score?: number | null }[];
  };
  cartao_modelo?: RiscoCartaoModelo;
  avisos?: string[];
  error?: string;
};

/** Grafo analítico 360 de uma empresa. */
export type RiscoGrafo360 = {
  nif: string;
  nome: string;
  pais: string;
  grafo: ContractGraphBuildResponse;
  lacos?: { tipo?: string; detalhe?: string; nome?: string | null }[];
  resumo?: {
    valor_total?: number | null;
    valor_mediano?: number | null;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    adjudicantes_distintos?: number | null;
    taxa_aditivo?: number | null;
    anos?: number[];
  };
  sinais?: { padrao?: string; detalhe?: string; total?: number; itens?: number }[];
  /** Processos em que a empresa é **a insolvente**. */
  insolvencias?: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
  /** Todos os processos do CIRE em que a empresa aparece (credor/requerente incluídos). */
  processos_cire?: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
  nota?: string;
  cargos_sociais?: { nif?: string; nome?: string; cargos?: { role?: string; role_org?: string }[] }[];
  intervenientes_processos?: { nif?: string; nome?: string; papel?: string; processo?: string }[];
  noticias?: { titulo?: string; fonte?: string; data?: string; url?: string }[];
  contratos_total?: number | null;
  error?: string;
};

/** Parecer de risco escrito por IA (ou factual, sem modelo). */
export type RiscoParecer = {
  mode: "ai" | "factual";
  text: string;
  backend?: { kind?: string; provider?: string; model?: string } | null;
  notes?: string[];
  warnings?: string[];
  factos?: Record<string, unknown>;
};

export type RiscoPesquisaParams = {
  q: string;
  pais?: string;
  nivel?: string;
  ordenar?: "relevancia" | "risco" | "valor" | "contratos";
  size?: number;
  from?: number;
  detalhado?: boolean;
};

async function readJson<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? ` — ${body.detail}` : "";
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(`${label}: ${res.status}${detail}`);
  }
  return res.json() as Promise<T>;
}

function query(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Cartão do modelo de risco (componentes, pesos, limiares e avisos). */
export async function getRiscoMeta(): Promise<RiscoMeta> {
  const res = await fetch(`${API_BASE}/risco/meta`);
  return readJson<RiscoMeta>(res, "Erro ao obter o cartão do modelo de risco");
}

/** Pesquisa de empresas com nível de risco (tipo motor de busca). */
export async function pesquisarRisco(params: RiscoPesquisaParams): Promise<RiscoPesquisa> {
  const res = await fetch(`${API_BASE}/risco/pesquisa${query({ ...params })}`);
  return readJson<RiscoPesquisa>(res, "Erro na pesquisa de empresas");
}

/** Sugestões (nome/NIF) para a caixa de pesquisa. */
export async function sugerirRisco(q: string, size = 8): Promise<RiscoSugestoes> {
  const res = await fetch(`${API_BASE}/risco/sugestoes${query({ q, size })}`);
  return readJson<RiscoSugestoes>(res, "Erro nas sugestões");
}

/** Risco de uma empresa (triagem rápida ou dossiê completo). */
export async function getRiscoEmpresa(
  pais: string,
  nif: string,
  params: { detalhado?: boolean; ano_from?: number | null; ano_to?: number | null; max_contratos?: number } = {},
): Promise<RiscoEmpresa> {
  const res = await fetch(`${API_BASE}/risco/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}${query(params)}`);
  return readJson<RiscoEmpresa>(res, "Erro ao obter o risco da empresa");
}

/** Grafo analítico 360 (compradores, órgãos sociais, processos do CIRE). */
export async function getRiscoGrafo(pais: string, nif: string): Promise<RiscoGrafo360> {
  const res = await fetch(`${API_BASE}/risco/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}/grafo`);
  return readJson<RiscoGrafo360>(res, "Erro ao obter o grafo 360");
}

/** Parecer de risco escrito por IA (com recuo factual). Exige sessão. */
export async function pedirParecerRisco(payload: {
  nif?: string;
  nome?: string;
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  detalhado?: boolean;
  backend?: string | null;
}): Promise<{ nif?: string; nome?: string; pais?: string; risco?: RiscoAvaliacao; ia: RiscoParecer }> {
  const res = await fetch(`${API_BASE}/risco/empresa/ia`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson(res, "Erro ao pedir o parecer de risco");
}

/** Risco de várias empresas lado a lado, com cruzamentos e rede. */
export async function compararRisco(payload: {
  nifs?: string[];
  nomes?: string[];
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  detalhado?: boolean;
}): Promise<RiscoComparacao> {
  const res = await fetch(`${API_BASE}/risco/comparar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<RiscoComparacao>(res, "Erro ao comparar empresas");
}

/** Limpa a cache de risco (exige sessão). */
export async function limparCacheRisco(): Promise<{ removidas: number }> {
  const res = await fetch(`${API_BASE}/risco/cache/clear`, { method: "POST" });
  return readJson(res, "Erro ao limpar a cache de risco");
}
