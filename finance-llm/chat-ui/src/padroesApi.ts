/**
 * Cliente da API de **deteção de padrões** — `/padroes/*`.
 *
 * O módulo cruza contratos públicos (`contratos`, `contratos_es`), empresas,
 * cargos (PessoasIQ), insolvências (CIRE) e notícias (RSS + recolha + redes
 * sociais) para sinalizar o que foge ao padrão:
 *
 * - **não supervisionado**: Isolation Forest, LOF, K-Means, One-Class SVM,
 *   DBSCAN e z-score robusto (MAD) por CPV;
 * - **supervisionado**: Gradient Boosting para a probabilidade de aditivo;
 * - **grafo**: adjudicante→adjudicatária, laços societários e insolvências partilhadas.
 */
import { API_BASE } from "./api";
import type { ContractGraphBuildResponse } from "./types";

/** Parâmetros comuns a todos os pedidos de análise. */
export type PadroesParams = {
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  cpv?: string | null;
  per_year?: number;
  contamination?: number;
  seed?: number;
};

/** Resumo (KPIs) de uma análise. */
export type PadroesOverview = {
  pais: string;
  pais_label: string;
  indice: string;
  contratos_analisados: number;
  valor_analisado?: number | null;
  valor_mediano?: number | null;
  anos?: [number, number] | null;
  taxa_ajuste_direto?: number | null;
  desvio_mediano?: number | null;
  contratos_com_aditivo?: number;
  taxa_aditivo?: number | null;
  dias_ate_decisao_mediano?: number | null;
  contratos_sinalizados: number;
  taxa_sinalizacao?: number | null;
  entidades: number;
  entidades_sinalizadas: number;
  cpvs: number;
  cobertura?: {
    documents_matching?: number;
    documents_sampled?: number;
    coverage?: number;
    anos?: number[];
    por_ano?: number;
  };
};

/** Linha da tabela por CPV. */
export type PadroesCpv = {
  cpv: string;
  descricao?: string | null;
  contratos: number;
  valor_total?: number | null;
  valor_mediano?: number | null;
  desvio_mediano?: number | null;
  taxa_ajuste_direto?: number | null;
  taxa_aditivo?: number | null;
  dias_ate_decisao_mediano?: number | null;
  contratos_sinalizados: number;
  relevancia?: number | null;
};

/** Sinal (razão) que explica uma sinalização. */
export type PadroesRazao = {
  padrao: string;
  detalhe: string;
  label?: string | null;
  severidade?: string | null;
  origem?: string | null;
  /** Totais por trás do sinal (ex.: processos no CIRE, itens lidos). */
  total?: number | null;
  itens?: number | null;
};

/** Contrato sinalizado. */
export type PadroesAnomalia = {
  id?: string | null;
  pais?: string;
  ano?: number | null;
  objeto?: string | null;
  cpv?: string | null;
  cpv_grupo?: string | null;
  cpv_desc?: string | null;
  valor?: number | null;
  preco_base?: number | null;
  valor_efetivo?: number | null;
  ratio_base?: number | null;
  ratio_efetivo?: number | null;
  procedimento?: string | null;
  ajuste_direto?: boolean;
  n_concorrentes?: number | null;
  dias_decisao?: number | null;
  dias_assinatura?: number | null;
  dias_publicacao?: number | null;
  adjudicante?: string | null;
  adjudicante_nif?: string | null;
  adjudicatarios?: { nif?: string; nome?: string }[];
  score: number;
  z_cpv?: number | null;
  votos: number;
  detetores: string[];
  razoes: PadroesRazao[];
  severidade?: string | null;
};

/** Empresa/entidade adjudicatária com score. */
export type PadroesEntidade = {
  nif: string;
  nome?: string | null;
  contratos: number;
  valor_total?: number | null;
  valor_mediano?: number | null;
  adjudicantes_distintos: number;
  parte_do_maior_adjudicante?: number | null;
  taxa_ajuste_direto?: number | null;
  desvio_mediano?: number | null;
  contratos_sinalizados: number;
  taxa_sinalizacao?: number | null;
  anos?: number[];
  score?: number | null;
  motivos: string[];
  insolvente: boolean;
  cpv_principal?: string | null;
  padrao?: string;
};

/** Grafo de relações (o mesmo formato do estúdio de grafos, para reutilizar o canvas). */
export type PadroesRelacoes = ContractGraphBuildResponse & {
  lacos: PadroesLaco[];
  concentracao: PadroesConcentracao[];
  insolventes: PadroesInsolvencia[];
  pessoas: PadroesPessoa[];
};

export type PadroesLaco = {
  tipo: string;
  detalhe: string;
  adjudicante?: string | null;
  empresa?: string | null;
  empresa_2?: string | null;
  pessoa?: string | null;
  contratos?: number;
  valor?: number | null;
  processo?: string | null;
  data?: string | null;
  empresas_nif?: string[];
};

export type PadroesConcentracao = {
  adjudicante: string;
  empresa: string;
  empresa_nif?: string;
  parte_do_valor?: number | null;
  contratos: number;
  valor?: number | null;
  contratos_do_adjudicante: number;
};

export type PadroesInsolvencia = {
  nif: string;
  nome?: string | null;
  especie?: string | null;
  ato?: string | null;
  data?: string | null;
  tribunal?: string | null;
  processo?: string | null;
};

export type PadroesPessoa = {
  pessoa: string;
  pessoa_nif: string;
  empresas: string[];
  empresas_nif: string[];
  cargos?: Record<string, string>;
  tipo?: string;
};

/** Modelo supervisionado (risco de aditivo). */
export type PadroesRisco = {
  disponivel: boolean;
  motivo?: string;
  rotulo?: string;
  aviso?: string;
  contratos?: number;
  positivos?: number;
  prevalencia?: number | null;
  auc?: number | null;
  average_precision?: number | null;
  lift_top_decile?: number | null;
  importancias?: { feature: string; importancia?: number | null }[];
  top_contratos?: {
    id?: string | null;
    objeto?: string | null;
    adjudicatario?: string | null;
    adjudicatario_nif?: string | null;
    adjudicante?: string | null;
    ano?: number | null;
    cpv?: string | null;
    valor?: number | null;
    probabilidade?: number | null;
    teve_aditivo?: boolean;
  }[];
  validacao?: string;
};

/** Padrão do catálogo (o que o motor procura). */
export type PadroesCatalogo = {
  id: string;
  label: string;
  tipo: string;
  metodo: string;
  features: string[];
  descricao: string;
  ativo?: boolean;
  severidade?: string | null;
  origem?: string | null;
  editavel?: boolean;
};

export type PadroesDeteccao = {
  algoritmos: string[];
  contaminacao: number;
  semente: number;
  limiar_consenso?: number | null;
  aviso?: string | null;
  features: string[];
  features_excluidas?: string[];
  nota: string;
};

/** Análise completa. */
export type PadroesAnalysis = {
  error?: string;
  pais: string;
  pais_label: string;
  paises?: Record<string, string>;
  filtros: { ano_from?: number | null; ano_to?: number | null; cpv?: string | null; per_year?: number };
  gerado_em?: string;
  duracao_s?: number | null;
  overview: PadroesOverview;
  cpvs: PadroesCpv[];
  anomalias: PadroesAnomalia[];
  entidades: PadroesEntidade[];
  relacoes: PadroesRelacoes;
  risco_aditivo: PadroesRisco;
  deteccao: PadroesDeteccao;
  padroes: PadroesCatalogo[];
  regras?: { ativas: PadroesRegraResumo[]; total_regras: number; templates: PadroesTemplate[] };
  regras_hits?: PadroesRegraHit[];
  modelo_entidades?: { n?: number; metricas?: Record<string, unknown>; error?: string };
};

export type PadroesMeta = {
  padroes: PadroesCatalogo[];
  algoritmos: Record<string, { id: string; label: string; uso: string }[]>;
  fontes: { pais: string; label: string; indice: string; documentos?: number | null; anos?: number[] | null }[];
  indices: Record<string, string>;
  params: { sample_per_year: number; contaminacao: number; cache_ttl_s: number };
  aviso: string;
};

/** Menção em notícias. */
export type PadroesNoticia = {
  entidade: string;
  entidade_nome: string;
  fonte?: string | null;
  canal: string;
  titulo?: string | null;
  url?: string | null;
  data?: string | null;
  sentimento?: string | null;
  sentimento_score?: number | null;
  resumo?: string | null;
};

/** Dossiê de uma entidade. */
export type PadroesDossie = {
  error?: string;
  nif: string;
  nome?: string | null;
  pais: string;
  contratos_total: number;
  contratos: {
    id?: string | null;
    ano?: number | null;
    objeto?: string | null;
    valor?: number | null;
    preco_base?: number | null;
    ratio_base?: number | null;
    ratio_efetivo?: number | null;
    procedimento?: string | null;
    ajuste_direto?: boolean;
    cpv?: string | null;
    cpv_desc?: string | null;
    n_concorrentes?: number | null;
    adjudicante?: string | null;
    adjudicante_nif?: string | null;
    dias_decisao?: number | null;
    dias_assinatura?: number | null;
    dias_publicacao?: number | null;
    data_publicacao?: string | null;
  }[];
  resumo: {
    valor_total?: number | null;
    valor_mediano?: number | null;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    adjudicantes_distintos?: number;
    taxa_aditivo?: number | null;
    anos?: number[];
  };
  sinais: PadroesRazao[];
  cargos_sociais: { nif?: string; nome?: string; cargos: { role?: string; role_org?: string; acto?: string; data?: string }[] }[];
  intervenientes_cire: { nif?: string; nome?: string; cargos: { role?: string; role_org?: string; acto?: string; data?: string }[] }[];
  insolvencias: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
  /** Total de processos no CIRE (a lista é uma amostra) e de pessoas ligadas ao NIF. */
  insolvencias_total?: number;
  pessoas_total?: number;
  /** Quem mais aparece nos processos desta empresa (nome, NIF e papel). */
  intervenientes_processos?: {
    processo: string;
    nif: string;
    nome?: string | null;
    papel?: string | null;
  }[];
  /** Grafo do dossiê (mesma forma do estúdio de grafos). */
  grafo?: ContractGraphBuildResponse | null;
  /** Ligações detetadas nos processos (quem aparece ao lado de quem). */
  lacos?: {
    tipo: string;
    detalhe: string;
    nif?: string | null;
    nome?: string | null;
    processo?: string | null;
    papel?: string | null;
  }[];
  noticias: PadroesNoticia[];
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

/** Catálogo de padrões, algoritmos e fontes. */
export async function getPadroesMeta(): Promise<PadroesMeta> {
  const res = await fetch(`${API_BASE}/padroes/meta`);
  return readJson<PadroesMeta>(res, "Erro ao obter o catálogo de padrões");
}

/** Análise completa (KPIs, CPV, anomalias, entidades, rede e modelo). */
export async function getPadroesAnalysis(params: PadroesParams = {}, refresh = false): Promise<PadroesAnalysis> {
  const res = await fetch(`${API_BASE}/padroes/analysis${query({ ...params, refresh: refresh || undefined })}`);
  return readJson<PadroesAnalysis>(res, "Erro na análise de padrões");
}

/** Contratos sinalizados (com filtros). */
export async function getPadroesAnomalies(
  params: PadroesParams & { min_score?: number; detector?: string; padrao?: string; limit?: number } = {},
): Promise<{ total: number; items: PadroesAnomalia[]; limiar_consenso?: number | null; algoritmos?: string[] }> {
  const res = await fetch(`${API_BASE}/padroes/anomalies${query(params)}`);
  return readJson(res, "Erro ao obter contratos sinalizados");
}

/** Ranking de entidades adjudicatárias. */
export async function getPadroesEntities(
  params: PadroesParams & { min_score?: number; insolventes?: boolean; limit?: number } = {},
): Promise<{ total: number; items: PadroesEntidade[]; modelo?: Record<string, unknown> }> {
  const res = await fetch(`${API_BASE}/padroes/entities${query(params)}`);
  return readJson(res, "Erro ao obter entidades");
}

/** Rede de relações, laços, concentração e insolvências. */
export async function getPadroesRelations(params: PadroesParams = {}): Promise<PadroesRelacoes> {
  const res = await fetch(`${API_BASE}/padroes/relations${query(params)}`);
  return readJson<PadroesRelacoes>(res, "Erro ao obter a rede de relações");
}

/** Menções em notícias das entidades sinalizadas. */
export async function getPadroesNews(
  params: PadroesParams & { limit?: number } = {},
): Promise<{ total: number; items: PadroesNoticia[]; procuradas: string[] }> {
  const res = await fetch(`${API_BASE}/padroes/news${query(params)}`);
  return readJson(res, "Erro ao procurar notícias");
}

/** Dossiê completo de uma entidade. */
export async function getPadroesDossie(nif: string, pais = "PT"): Promise<PadroesDossie> {
  const res = await fetch(`${API_BASE}/padroes/entity/${encodeURIComponent(nif)}${query({ pais })}`);
  return readJson<PadroesDossie>(res, "Erro ao obter o dossiê da entidade");
}

/** Limpar a cache de análises (requer sessão). */
export async function clearPadroesCache(): Promise<{ removidas: number }> {
  const res = await fetch(`${API_BASE}/padroes/cache/clear`, { method: "POST" });
  return readJson(res, "Erro ao limpar a cache");
}

/* ----------------------------------------------------------------- empresa */

/** Sugestão de empresa a analisar (nome, NIF, contratos e papel no cadastro). */
export type PadroesEmpresaSugestao = {
  nif: string;
  nome?: string | null;
  alias?: string[];
  contratos?: number | null;
  valor?: number | null;
  valor_adjudicatario?: number | null;
  papeis?: string[];
  concelho?: string | null;
  fonte?: string | null;
  principal?: boolean;
};

/** Resposta da pesquisa de empresas (a primeira é a proposta principal). */
export type PadroesEmpresaSugestoes = {
  pais: string;
  query: string;
  nif_detetado?: boolean;
  items: PadroesEmpresaSugestao[];
  candidatos?: PadroesEmpresaSugestao[];
  detail?: string;
};

/** Contrato dentro da análise de uma empresa (com as regras que cumpre). */
export type PadroesEmpresaContrato = {
  id?: string | null;
  ano?: number | null;
  data_publicacao?: string | null;
  objeto?: string | null;
  valor?: number | null;
  preco_base?: number | null;
  valor_efetivo?: number | null;
  ratio_base?: number | null;
  ratio_efetivo?: number | null;
  procedimento?: string | null;
  ajuste_direto?: boolean;
  cpv?: string | null;
  cpv_grupo?: string | null;
  cpv_desc?: string | null;
  n_concorrentes?: number | null;
  dias_decisao?: number | null;
  dias_assinatura?: number | null;
  dias_publicacao?: number | null;
  adjudicante?: string | null;
  adjudicante_nif?: string | null;
  z_cpv?: number | null;
  severidade?: string | null;
  razoes: PadroesRazao[];
};

/** Sinal agregado na análise da empresa (padrão + contratos + exemplos). */
export type PadroesEmpresaSinal = {
  padrao: string;
  label?: string | null;
  severidade?: string | null;
  descricao?: string | null;
  contratos: number;
  taxa?: number | null;
  exemplos: { id?: string | null; objeto?: string | null; ano?: number | null; valor?: number | null; detalhe?: string | null }[];
};

/** Análise de uma empresa adjudicatária. */
export type PadroesEmpresaAnalise = {
  error?: string;
  cache?: boolean;
  pais: string;
  pais_label?: string;
  nif: string;
  nome: string;
  candidatos?: PadroesEmpresaSugestao[];
  ficha?: { nif?: string; nome?: string | null; alias?: string[]; papeis?: string[]; contratos?: number | null; valor?: number | null; concelho?: string | null } | null;
  filtros: { ano_from?: number | null; ano_to?: number | null };
  contratos_total: number;
  contratos_analisados: number;
  anos?: [number, number] | null;
  resumo: {
    contratos: number;
    valor_total?: number | null;
    valor_mediano?: number | null;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    taxa_aditivo?: number | null;
    adjudicantes_distintos?: number;
    cpvs?: number;
    contratos_com_sinais?: number;
    contratos_atipicos_cpv?: number;
    insolvente?: boolean;
    concentracao_adjudicante?: number | null;
    escaloes?: Record<string, number>;
  };
  por_ano: { ano: number; contratos: number; valor?: number | null }[];
  por_cpv: {
    cpv: string;
    descricao?: string | null;
    contratos: number;
    valor?: number | null;
    ajuste_direto?: number;
    aditivos?: number;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    taxa_aditivo?: number | null;
  }[];
  por_procedimento: { procedimento: string; contratos: number; valor?: number | null }[];
  adjudicantes: { nif?: string | null; nome?: string | null; contratos: number; valor?: number | null }[];
  sinais: PadroesEmpresaSinal[];
  contratos: PadroesEmpresaContrato[];
  reguas_cpv: {
    cpv: string;
    contratos: number;
    valor_mediano?: number | null;
    desvio_mediano?: number | null;
    taxa_ajuste_direto?: number | null;
    taxa_aditivo?: number | null;
  }[];
  relacoes: {
    empresas: { nif: string; nome?: string | null; adjudicante?: string | null; contratos: number; valor?: number | null }[];
    cargos_sociais: PadroesDossie["cargos_sociais"];
    intervenientes_cire: PadroesDossie["intervenientes_cire"];
    insolvencias: PadroesDossie["insolvencias"];
    noticias: PadroesNoticia[];
  };
  regras_ativas: PadroesRegraResumo[];
  aviso?: string;
};

/** Pesquisa empresas (nome, marca ou NIF) para depois analisar uma delas. */
export async function sugerirPadroesEmpresas(
  q: string,
  params: { pais?: string; limit?: number } = {},
): Promise<PadroesEmpresaSugestoes> {
  const res = await fetch(`${API_BASE}/padroes/empresas/sugestoes${query({ q, ...params })}`);
  return readJson<PadroesEmpresaSugestoes>(res, "Erro ao procurar empresas");
}

/** Analisa uma empresa: portefólio, CPV, regras cumpridas, pares e relações. */
export async function analisarPadroesEmpresa(
  params: { nif?: string; nome?: string; pais?: string; ano_from?: number | null; ano_to?: number | null; max_contratos?: number; refresh?: boolean },
): Promise<PadroesEmpresaAnalise> {
  const res = await fetch(`${API_BASE}/padroes/empresas/analise${query({ ...params, refresh: params.refresh || undefined })}`);
  return readJson<PadroesEmpresaAnalise>(res, "Erro na análise da empresa");
}

/* ------------------------------------------------- IA, browser e persistência */

/** Página lida no browser do IQ OS. */
export type PadroesBrowserPagina = {
  url: string;
  titulo?: string | null;
  chars?: number | null;
  status?: number | null;
  ok: boolean;
  erro?: string | null;
};

/** Resultado da leitura de páginas externas (com indexação em `finance_scraped`). */
export type PadroesBrowserResposta = {
  paginas: PadroesBrowserPagina[];
  lidas: number;
  indexadas: number;
  indice?: string | null;
  pareadas?: string[];
  por?: string;
  error?: string;
  detail?: string;
};

/** Ficha analítica da empresa (IA, com recuo factual). */
export type PadroesEmpresaIA = {
  mode: "ai" | "factual";
  text: string;
  backend?: { kind?: string | null; provider?: string | null; model?: string | null } | null;
  notes?: string[];
  warnings?: string[];
  paginas?: { url: string; titulo?: string | null; chars?: number | null }[];
  factos?: Record<string, unknown>;
};

/** Resposta de `POST /padroes/empresas/ia`. */
export type PadroesEmpresaIAResposta = {
  error?: string;
  nif?: string | null;
  nome?: string | null;
  pais?: string | null;
  ia: PadroesEmpresaIA;
  browser?: { lidas?: number; indexadas?: number; indice?: string | null; paginas?: PadroesBrowserPagina[] };
  entidades?: Record<string, { nif?: string; nome?: string | null; tipo?: string | null; concelho?: string | null }>;
  guardado?: { saved?: boolean; doc_id?: string; error?: string } | null;
};

/** Análise guardada no Elasticsearch (listagem sem a fotografia completa). */
export type PadroesEmpresaGuardada = {
  doc_id: string;
  nif: string;
  nome?: string | null;
  pais?: string | null;
  titulo?: string | null;
  notas?: string | null;
  criado_em?: string | null;
  atualizado_em?: string | null;
  autor?: string | null;
  autor_email?: string | null;
  anos?: number[];
  contratos_total?: number | null;
  contratos_analisados?: number | null;
  valor_total?: number | null;
  severidade?: string | null;
  sinais?: string[];
  insolvente?: boolean;
  ia?: boolean;
  ia_modelo?: string | null;
  ia_provider?: string | null;
  fontes?: string[];
  analise?: PadroesEmpresaAnalise | null;
  ficha_ia?: string | null;
  browser?: PadroesBrowserPagina[] | null;
};

/** Lê páginas externas (site da empresa, imprensa) e indexa o texto lido. Requer sessão. */
export async function browserPadroesEmpresa(urls: string[], limite = 6): Promise<PadroesBrowserResposta> {
  const res = await fetch(`${API_BASE}/padroes/empresas/browser`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls, limite }),
  });
  return readJson<PadroesBrowserResposta>(res, "Erro ao ler as páginas");
}

/** Ficha analítica da empresa por IA (com browser e gravação opcionais). Requer sessão. */
export async function analisarPadroesEmpresaIA(payload: {
  nif?: string;
  nome?: string;
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  max_contratos?: number;
  urls?: string[];
  com_browser?: boolean;
  backend?: string;
  guardar?: boolean;
  notas?: string;
}): Promise<PadroesEmpresaIAResposta> {
  const res = await fetch(`${API_BASE}/padroes/empresas/ia`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<PadroesEmpresaIAResposta>(res, "Erro na ficha de IA");
}

/** Guarda (ou substitui) a análise de uma empresa no Elasticsearch. Requer sessão. */
export async function guardarPadroesEmpresa(payload: {
  nif?: string;
  nome?: string;
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  max_contratos?: number;
  titulo?: string;
  notas?: string;
  ficha_ia?: string;
  analise?: PadroesEmpresaAnalise;
  browser?: PadroesBrowserPagina[];
}): Promise<{ saved?: boolean; doc_id?: string; index?: string; atualizado_em?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/padroes/empresas/guardar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson(res, "Erro ao guardar a análise");
}

/** Análises de empresas guardadas (mais recentes primeiro). Requer sessão. */
export async function listarPadroesEmpresasGuardadas(
  params: { nif?: string; nome?: string; pais?: string; limit?: number } = {},
): Promise<{ items: PadroesEmpresaGuardada[]; total: number }> {
  const res = await fetch(`${API_BASE}/padroes/empresas/guardadas${query(params)}`);
  return readJson(res, "Erro ao listar as análises guardadas");
}

/** Análise guardada (completa). Requer sessão. */
export async function obterPadroesEmpresaGuardada(docId: string): Promise<PadroesEmpresaGuardada> {
  const res = await fetch(`${API_BASE}/padroes/empresas/guardada/${encodeURIComponent(docId)}`);
  return readJson<PadroesEmpresaGuardada>(res, "Erro ao abrir a análise guardada");
}

/** Apaga uma análise guardada. Requer sessão. */
export async function apagarPadroesEmpresaGuardada(docId: string): Promise<{ apagada?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/padroes/empresas/guardada/${encodeURIComponent(docId)}`, { method: "DELETE" });
  return readJson(res, "Erro ao apagar a análise guardada");
}

export type PadroesRelatorioFormato = "pdf" | "xlsx" | "csv";

/** Relatório da empresa (PDF, Excel ou CSV) — devolve o blob e o nome do ficheiro. */
export async function exportPadroesEmpresaRelatorio(
  params: {
    formato: PadroesRelatorioFormato;
    nif?: string;
    nome?: string;
    pais?: string;
    ano_from?: number | null;
    ano_to?: number | null;
    max_contratos?: number;
    doc_id?: string;
    ficha_ia?: boolean;
  },
  fallback = "iq-os-padroes.pdf",
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/padroes/empresas/relatorio${query({ ...params, ficha_ia: params.ficha_ia || undefined })}`);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await res.blob(), filename: match ? match[1] : fallback };
}

/** Descarrega um ficheiro já obtido (blob do backend). */
export function guardarFicheiroPadroes(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* -------------------------------------------- comparação de várias empresas */

/** Uma empresa na comparação (sem os contratos, que ficam no dossiê). */
export type PadroesEmpresaLinha = {
  nif: string;
  nome?: string | null;
  pais?: string | null;
  pais_label?: string | null;
  ficha?: PadroesEmpresaAnalise["ficha"];
  anos?: [number, number] | null;
  contratos_total?: number | null;
  contratos_analisados?: number | null;
  resumo: {
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
  severidade?: string | null;
  sinais: PadroesEmpresaSinal[];
  adjudicantes: { nif?: string | null; nome?: string | null; contratos: number; valor?: number | null }[];
  por_cpv: PadroesEmpresaAnalise["por_cpv"];
  por_procedimento: PadroesEmpresaAnalise["por_procedimento"];
  por_ano: PadroesEmpresaAnalise["por_ano"];
  relacoes: PadroesEmpresaAnalise["relacoes"];
  aviso?: string | null;
};

/** Cruzamento entre as empresas comparadas (adjudicante, pessoa, processo ou CPV). */
export type PadroesCruzamento = {
  nif?: string | null;
  nome?: string | null;
  empresas: string[];
  empresas_nome: string[];
  n_empresas: number;
  contratos?: number;
  valor?: number | null;
  cargos?: string[];
  processo?: string | null;
  especie?: string | null;
  tribunal?: string | null;
  data?: string | null;
  cpv?: string;
  descricao?: string | null;
};

/** Resultado da comparação de várias empresas. */
export type PadroesEmpresasConjunto = {
  error?: string;
  pais: string;
  pais_label?: string;
  filtros?: Record<string, unknown>;
  gerado_em?: string;
  empresas: PadroesEmpresaLinha[];
  totais: {
    empresas: number;
    empresas_pedidas: number;
    contratos: number;
    contratos_total_portal: number;
    valor_total?: number | null;
    valor_mediano?: number | null;
    insolventes: number;
    com_sinais: number;
    adjudicantes_comuns: number;
    pessoas_comuns: number;
    processos_comuns: number;
    cpvs_comuns: number;
  };
  cruzamentos: {
    adjudicantes: PadroesCruzamento[];
    pessoas: PadroesCruzamento[];
    processos: PadroesCruzamento[];
    cpvs: PadroesCruzamento[];
  };
  por_cpv: { cpv: string; descricao?: string | null; contratos: number; valor?: number | null; empresas: number }[];
  grafo: ContractGraphBuildResponse;
  avisos: string[];
  aviso?: string;
};

/** Compara várias empresas (contratos, cruzamentos e rede do conjunto). */
export async function compararPadroesEmpresas(payload: {
  nifs?: string[];
  nomes?: string[];
  pais?: string;
  ano_from?: number | null;
  ano_to?: number | null;
  max_contratos?: number;
  max_empresas?: number;
}): Promise<PadroesEmpresasConjunto> {
  const res = await fetch(`${API_BASE}/padroes/empresas/analise-multipla`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<PadroesEmpresasConjunto>(res, "Erro na comparação de empresas");
}

/** Relatório da comparação (PDF, Excel ou CSV). */
export async function exportPadroesEmpresasRelatorio(
  payload: {
    nifs?: string[];
    nomes?: string[];
    pais?: string;
    ano_from?: number | null;
    ano_to?: number | null;
    max_contratos?: number;
    max_empresas?: number;
  },
  formato: PadroesRelatorioFormato,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${API_BASE}/padroes/empresas/multipla/relatorio?formato=${formato}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await res.blob(), filename: match ? match[1] : `iq-os-padroes-comparacao.${formato}` };
}

/* ------------------------------------------------------------------ regras */

/** Campo derivado que uma regra pode testar. */
export type PadroesCampo = {
  id: string;
  label: string;
  tipo: "numero" | "texto";
  unidade?: string;
  escopo?: "contrato" | "cpv" | "global";
};

export type PadroesOperador = { id: string; label: string; tipos: string[] };
export type PadroesSeveridade = { id: string; label: string };

/** Valor de uma condição: número, texto ou referência a outro campo (com fator). */
export type PadroesCondicaoValor = number | string | { campo: string; fator?: number };

export type PadroesCondicao = { campo: string; operador: string; valor: PadroesCondicaoValor };

/** Regra editável guardada no registo. */
export type PadroesRegra = {
  id: string;
  label: string;
  descricao?: string | null;
  severidade: "info" | "aviso" | "alerta" | string;
  modo: "todas" | "alguma";
  condicoes: PadroesCondicao[];
  ativo: boolean;
  origem?: string | null;
  tipo?: string;
  editavel?: boolean;
  criado_em?: string | null;
};

/** Regra com a condição já legível e a contagem de contratos que cumpre. */
export type PadroesRegraResumo = {
  id: string;
  label: string;
  descricao?: string | null;
  severidade?: string | null;
  ativo: boolean;
  origem?: string | null;
  condicao: string;
  condicoes: PadroesCondicao[];
  contratos?: number;
};

export type PadroesTemplate = {
  id: string;
  nome: string;
  descricao?: string | null;
  regras: string[];
  origem?: string | null;
  criado_em?: string | null;
};

export type PadroesRegrasState = {
  regras: PadroesRegra[];
  templates: PadroesTemplate[];
  campos: PadroesCampo[];
  operadores: PadroesOperador[];
  severidades: PadroesSeveridade[];
  padroes_nao_avaliaveis: { id: string; label: string; tipo: string; metodo: string; descricao: string }[];
  updated_at?: string | null;
  limites?: { regras: number; templates: number };
};

/** Contrato que cumpre pelo menos uma regra ativa. */
export type PadroesRegraHit = {
  id?: string | null;
  ano?: number | null;
  objeto?: string | null;
  valor?: number | null;
  cpv?: string | null;
  cpv_grupo?: string | null;
  procedimento?: string | null;
  adjudicante?: string | null;
  adjudicante_nif?: string | null;
  adjudicataria?: string | null;
  adjudicataria_nif?: string | null;
  severidade?: string | null;
  regras: string[];
  rotulos: string[];
  detalhes: string[];
};

/** Regras guardadas + catálogo (campos/operadores/severidades). */export async function getPadroesRegras(): Promise<PadroesRegrasState> {
  const res = await fetch(`${API_BASE}/padroes/regras`);
  return readJson<PadroesRegrasState>(res, "Erro ao obter as regras");
}

/** Cria (sem `id`) ou atualiza uma regra. Requer sessão. */
export async function savePadroesRegra(payload: Partial<PadroesRegra>): Promise<PadroesRegra> {
  const res = await fetch(`${API_BASE}/padroes/regras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<PadroesRegra>(res, "Erro ao guardar a regra");
}

/** Liga/desliga uma regra (sem `ativo` inverte o estado). Requer sessão. */
export async function togglePadroesRegra(id: string, ativo?: boolean): Promise<PadroesRegra> {
  const res = await fetch(`${API_BASE}/padroes/regras/${encodeURIComponent(id)}/ativo${query({ ativo })}`, {
    method: "PATCH",
  });
  return readJson<PadroesRegra>(res, "Erro ao alterar a regra");
}

/** Duplica uma regra (para afinar uma predefinição sem a perder). */
export async function duplicatePadroesRegra(id: string): Promise<PadroesRegra> {
  const res = await fetch(`${API_BASE}/padroes/regras/${encodeURIComponent(id)}/duplicar`, { method: "POST" });
  return readJson<PadroesRegra>(res, "Erro ao duplicar a regra");
}

/** Apaga uma regra. Requer sessão. */
export async function deletePadroesRegra(id: string): Promise<{ apagada: string }> {
  const res = await fetch(`${API_BASE}/padroes/regras/${encodeURIComponent(id)}`, { method: "DELETE" });
  return readJson(res, "Erro ao apagar a regra");
}

/** Repõe as regras predefinidas (e os templates de fábrica). Requer sessão. */
export async function resetPadroesRegras(manterPersonalizadas = false): Promise<{ regras: number; templates: number }> {
  const res = await fetch(`${API_BASE}/padroes/regras/repor${query({ manter_personalizadas: manterPersonalizadas })}`, {
    method: "POST",
  });
  return readJson(res, "Erro ao repor as regras predefinidas");
}

/** Guarda um template (usa as regras indicadas ou as ativas). Requer sessão. */
export async function savePadroesTemplate(payload: {
  id?: string;
  nome: string;
  descricao?: string;
  regras?: string[];
}): Promise<PadroesTemplate> {
  const res = await fetch(`${API_BASE}/padroes/regras/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<PadroesTemplate>(res, "Erro ao guardar o template");
}

/** Aplica um template: ativa as suas regras e desliga as restantes. */
export async function applyPadroesTemplate(id: string): Promise<{ nome?: string; ativas: string[] }> {
  const res = await fetch(`${API_BASE}/padroes/regras/templates/${encodeURIComponent(id)}/aplicar`, { method: "POST" });
  return readJson(res, "Erro ao aplicar o template");
}

/** Apaga um template. */
export async function deletePadroesTemplate(id: string): Promise<{ apagado: string }> {
  const res = await fetch(`${API_BASE}/padroes/regras/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
  return readJson(res, "Erro ao apagar o template");
}

/** Contratos que cumprem as regras ativas (independentemente dos modelos). */
export async function getPadroesRegrasHits(
  params: PadroesParams & { severidade?: string; regra?: string; limit?: number } = {},
): Promise<{ total: number; items: PadroesRegraHit[]; regras: PadroesRegraResumo[] }> {
  const res = await fetch(`${API_BASE}/padroes/regras/hits${query(params)}`);
  return readJson(res, "Erro ao obter os contratos das regras");
}

/* --------------------------------------------------- universo (global) */

/** Granularidades da série temporal do universo. */
export type PadroesGlobalGranularidade = "dia" | "semana" | "mes" | "ano";

/** Formas de contar um conjunto de partes (adjudicatárias ou adjudicantes). */
export type PadroesGlobalParte = {
  nif?: string | null;
  nome?: string | null;
  contratos: number;
  valor?: number | null;
};

/** Valor de uma faceta (CPV, procedimento, …). */
export type PadroesGlobalFaceta = {
  cpv?: string | null;
  procedimento?: string | null;
  descricao?: string | null;
  contratos: number;
  valor?: number | null;
};

/** Métricas de **todo o universo** num ano (calculadas por agregação, sem amostra). */
export type PadroesGlobalAno = {
  pais: string;
  ano: number;
  contratos: number;
  valor?: number | null;
  valor_medio?: number | null;
  valor_mediano?: number | null;
  valor_maximo?: number | null;
  valor_base?: number | null;
  contratos_com_base?: number;
  ajuste_direto: { contratos: number; total: number; taxa?: number | null; valor?: number | null; taxa_valor?: number | null };
  aditivos?: number;
  valor_aditivos?: number | null;
  taxa_aditivo?: number | null;
  sem_concorrentes?: number;
  taxa_sem_concorrentes?: number | null;
  ofertas_media?: number | null;
  ofertas_mediana?: number | null;
  sem_ofertas?: number;
  procedimentos: PadroesGlobalFaceta[];
  cpvs: PadroesGlobalFaceta[];
  adjudicatarias: PadroesGlobalParte[];
  adjudicantes: PadroesGlobalParte[];
  meses: { data?: string | null; contratos: number; valor?: number | null }[];
};

/** Ponto da série temporal (dia, semana, mês ou ano). */
export type PadroesGlobalPonto = { periodo: string; contratos: number; valor?: number | null };

/** Estado do processo de sincronização do universo. */
export type PadroesGlobalEstado = {
  a_correr: boolean;
  pais?: string | null;
  progresso?: string | null;
  inicio?: string | null;
  fim?: string | null;
  resultado?: {
    pais?: string;
    anos?: number[];
    documentos?: number;
    indexados?: number;
    duracao_s?: number | null;
    gerado_em?: string | null;
    indice?: string;
  } | null;
  erro?: string | null;
};

/** Dashboard global: o universo inteiro, ano a ano. */
export type PadroesGlobalDashboard = {
  error?: string;
  pais?: string;
  pais_label?: string;
  indice?: string;
  vazio?: boolean;
  granularidade?: PadroesGlobalGranularidade;
  granularidades?: { id: PadroesGlobalGranularidade; label: string }[];
  meta?: {
    anos?: number[];
    documentos?: number;
    duracao_s?: number | null;
    gerado_em?: string | null;
    versao?: number;
  };
  estado?: PadroesGlobalEstado;
  filtros?: { ano_from?: number | null; ano_to?: number | null };
  totais?: {
    contratos: number;
    documentos_universo?: number | null;
    valor?: number | null;
    valor_medio?: number | null;
    valor_mediano?: number | null;
    valor_base?: number | null;
    contratos_com_base?: number;
    aditivos?: number;
    taxa_aditivo?: number | null;
    valor_aditivos?: number | null;
    sem_concorrentes?: number;
    taxa_sem_concorrentes?: number | null;
    ajuste_direto?: { contratos: number; valor?: number | null; taxa?: number | null; taxa_valor?: number | null };
    anos?: number[];
  };
  serie?: PadroesGlobalPonto[];
  por_ano?: PadroesGlobalAno[];
  top_cpv?: PadroesGlobalFaceta[];
  top_adjudicatarias?: PadroesGlobalParte[];
  procedimentos?: PadroesGlobalFaceta[];
  aviso?: string;
  gerado_em?: string | null;
};

/** Estado e catálogo do dashboard global. */
export type PadroesGlobalMeta = {
  error?: string;
  pais?: string;
  pais_label?: string;
  indice?: string;
  indice_materializado?: string;
  documentos?: number | null;
  guardado?: boolean;
  materializado_em?: string | null;
  anos?: number[];
  documentos_universo?: number | null;
  duracao_s?: number | null;
  estado?: PadroesGlobalEstado;
  granularidades?: { id: PadroesGlobalGranularidade; label: string }[];
  anos_padrao?: number;
  aviso?: string;
};

/** Contrato devolvido pela pesquisa do universo. */
export type PadroesGlobalContrato = {
  id?: string | null;
  ano?: number | null;
  data_publicacao?: string | null;
  objeto?: string | null;
  cpv?: string | null;
  cpv_grupo?: string | null;
  cpv_desc?: string | null;
  valor?: number | null;
  preco_base?: number | null;
  valor_efetivo?: number | null;
  ratio_base?: number | null;
  ratio_efetivo?: number | null;
  procedimento?: string | null;
  ajuste_direto?: boolean;
  n_concorrentes?: number | null;
  adjudicante?: string | null;
  adjudicante_nif?: string | null;
  adjudicataria?: string | null;
  adjudicataria_nif?: string | null;
  dias_assinatura?: number | null;
  dias_publicacao?: number | null;
};

/** Resultado da pesquisa tipo Google no universo (com filtros e facetas). */
export type PadroesGlobalPesquisa = {
  error?: string;
  pais?: string;
  pais_label?: string;
  granularidade?: PadroesGlobalGranularidade;
  granularidades?: { id: PadroesGlobalGranularidade; label: string }[];
  total?: number;
  items?: PadroesGlobalContrato[];
  kpis?: {
    contratos?: number;
    valor?: number | null;
    valor_medio?: number | null;
    valor_mediano?: number | null;
    valor_maximo?: number | null;
    ajuste_direto?: { contratos: number; total: number; taxa?: number | null; valor?: number | null; taxa_valor?: number | null };
    aditivos?: number | null;
    valor_aditivos?: number | null;
    taxa_aditivo?: number | null;
    sem_concorrentes?: number;
    ofertas_media?: number | null;
  };
  serie?: PadroesGlobalPonto[];
  facetas?: {
    cpvs: PadroesGlobalFaceta[];
    adjudicatarias: PadroesGlobalParte[];
    adjudicantes: PadroesGlobalParte[];
    procedimentos: PadroesGlobalFaceta[];
  };
  pagina?: { size: number; from: number };
  filtros?: Record<string, unknown>;
  gerado_em?: string;
};

/** Filtros aceites pela pesquisa do universo. */
export type PadroesGlobalFiltros = {
  pais?: string;
  q?: string;
  data_from?: string;
  data_to?: string;
  campo_data?: "publicacao" | "decisao" | "assinatura";
  ano_from?: number | null;
  ano_to?: number | null;
  empresa?: string;
  adjudicante?: string;
  cpv?: string;
  procedimento?: string;
  valor_min?: number | null;
  valor_max?: number | null;
  concorrentes_min?: number | null;
  concorrentes_max?: number | null;
  so_aditivo?: boolean;
  so_ajuste_direto?: boolean;
  granularidade?: PadroesGlobalGranularidade;
  size?: number;
  from?: number;
};

/** Dashboard global do universo (lê o que já está materializado). */
export async function getPadroesGlobal(
  params: { pais?: string; granularidade?: PadroesGlobalGranularidade; ano_from?: number | null; ano_to?: number | null } = {},
): Promise<PadroesGlobalDashboard> {
  const res = await fetch(`${API_BASE}/padroes/global${query(params)}`);
  return readJson<PadroesGlobalDashboard>(res, "Erro ao obter o dashboard global");
}

/** Estado do universo: o que está materializado e como corre a sincronização. */
export async function getPadroesGlobalMeta(pais = "PT"): Promise<PadroesGlobalMeta> {
  const res = await fetch(`${API_BASE}/padroes/global/meta${query({ pais })}`);
  return readJson<PadroesGlobalMeta>(res, "Erro ao obter o estado do universo");
}

/** Progresso do processo de sincronização do universo. */
export async function getPadroesGlobalEstado(): Promise<PadroesGlobalEstado> {
  const res = await fetch(`${API_BASE}/padroes/global/estado`);
  return readJson<PadroesGlobalEstado>(res, "Erro ao obter o estado da sincronização");
}

/** Arranca a agregação do universo em segundo plano. */
export async function sincronizarPadroesGlobal(payload: {
  pais?: string;
  anos?: number[];
}): Promise<PadroesGlobalEstado> {
  const res = await fetch(`${API_BASE}/padroes/global/sincronizar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJson<PadroesGlobalEstado>(res, "Erro ao sincronizar o universo");
}

/** Pesquisa tipo Google no universo, com filtros de período, empresa e concorrentes. */
export async function pesquisarPadroesGlobal(filtros: PadroesGlobalFiltros): Promise<PadroesGlobalPesquisa> {
  const res = await fetch(`${API_BASE}/padroes/global/pesquisa${query(filtros)}`);
  return readJson<PadroesGlobalPesquisa>(res, "Erro na pesquisa do universo");
}
