/**
 * Cliente da API do módulo **ESG** — `/esg/*`.
 *
 * O módulo dá a cada empresa um score de 0 a 100 (pilares Ambiente, Social e
 * Governação), com cobertura e confiança, série de três anos, benchmark de
 * setor e dimensão, indicadores declarados nos relatórios de sustentabilidade
 * e análise da carteira de fornecedores.
 *
 * Nada aqui certifica empresas: os indicadores de contratação pública são
 * proxies e o cartão do modelo explica pesos, limiares e fontes.
 */
import { API_BASE } from "./api";

export type EsgPilarId = "e" | "s" | "g";

export type EsgNivel = "lider" | "avancado" | "intermedio" | "inicial" | "fraco" | "sem_dados";

export type EsgPilar = {
  id: EsgPilarId;
  label: string;
  peso: number;
  cor: string;
  descricao: string;
};

export type EsgComponenteDef = {
  id: string;
  label: string;
  peso: number;
  pior: number;
  melhor: number;
  unidade: string;
  descricao: string;
  metodo: string;
};

export type EsgCartao = {
  versao: string;
  rotulo: string;
  aviso: string;
  pilares: (EsgPilar & { componentes: EsgComponenteDef[] })[];
  niveis: { id: EsgNivel; label: string; min: number; cor: string }[];
  dimensoes: { id: string; label: string; min: number; max: number | null }[];
  min_par_benchmark: number;
  indicadores: EsgIndicadorDef[];
  fontes: EsgFonte[];
};

export type EsgIndicadorDef = {
  codigo: string;
  label: string;
  pilar: EsgPilarId;
  unidade: string;
  pior: number | null;
  melhor: number | null;
  grupo: string;
  descricao: string;
  fonte_sugerida: string;
  pontuavel: boolean;
};

export type EsgFonte = {
  id: string;
  label: string;
  tipo: "interna" | "declarada" | "referencia" | string;
  url: string;
  uso: string;
};

export type EsgTaxonomiaObjetivo = {
  id: number;
  label: string;
  curto: string;
  cor: string;
  descricao?: string;
  n_atividades?: number;
  atividades?: { id: number; nome: string }[];
  tipos?: string[];
  n?: number;
};

export type EsgTaxonomiaAtividade = {
  id: number;
  nome: string;
  setor_id?: number;
  setor: string;
  nace: string[];
  objetivos: { id: number; tipo: string; label?: string | null; curto?: string | null; cor?: string | null }[];
  url?: string;
  match?: string;
  nace_match?: string | null;
  especificidade?: number;
};

export type EsgTaxonomiaSalvaguarda = {
  id: string;
  label: string;
  descricao: string;
  fonte?: string | null;
  indicadores: string[];
  status: "evidência parcial" | "evidência limitada" | "sem evidência" | string;
};

export type EsgTaxonomiaDnsh = {
  objetivo: number;
  label: string;
  cor: string;
  indicadores: string[];
  status: "com indicador" | "sem evidência" | string;
};

export type EsgTaxonomiaEmpresa = {
  fonte: EsgTaxonomiaFonte;
  nace: string;
  secao: string;
  match: string | null;
  elegivel: boolean;
  alinhamento: "sem_dados" | "nao_elegivel" | "elegivel_nao_verificado" | string;
  alinhamento_label: string;
  cobertura_verificacao: number;
  n_atividades: number;
  atividades: EsgTaxonomiaAtividade[];
  objetivos: EsgTaxonomiaObjetivo[];
  dnsh: EsgTaxonomiaDnsh[];
  salvaguardas: EsgTaxonomiaSalvaguarda[];
  ods: { id: number; label: string; cor: string; grupos: string[] }[];
  materialidade: { tema: string; relevancia: string; origem: string }[];
  avisos: string[];
  url_compass: string;
};

export type EsgTaxonomiaFonte = {
  id: string;
  label: string;
  url: string;
  api: string;
  sincronizado_em: string;
  aviso: string;
};

export type EsgNormaRelato = {
  id: string;
  label: string;
  url: string;
  uso: string;
  ambito: string;
};

export type EsgOds = {
  id: number;
  label: string;
  cor: string;
  grupos: string[];
};

export type EsgPasso = {
  id: number;
  label: string;
  descricao: string;
  no_iqos: string;
};

export type EsgTaxonomiaPanorama = {
  fonte: EsgTaxonomiaFonte;
  objetivos: EsgTaxonomiaObjetivo[];
  total_atividades: number;
  setores: { setor: string; n: number }[];
  salvaguardas: { id: string; label: string; descricao: string; indicadores: string[]; fonte?: string }[];
  dnsh: { objetivo: number; indicadores: string[] }[];
  normas_relato: EsgNormaRelato[];
  ods: EsgOds[];
  passos: EsgPasso[];
  materialidade: Record<string, string[]>;
};

export type EsgComponente = {
  id: string;
  pilar: EsgPilarId;
  label: string;
  peso: number;
  peso_efetivo: number;
  contributo: number | null;
  valor: number | null;
  unidade: string;
  descricao: string;
  metodo: string;
  /** Pontos 0–100 do componente; `null` quando não há dados. */
  pontos: number | null;
  disponivel: boolean;
  evidencia: string[];
};

export type EsgPilarDetalhe = EsgPilar & {
  score: number | null;
  cobertura: number;
  componentes: EsgComponente[];
};

export type EsgBenchmark = {
  disponivel: boolean;
  motivo?: string;
  n_pares?: number;
  minimo?: number;
  percentil?: number | null;
  posicao?: string;
  mediana?: number | null;
  media?: number | null;
  p25?: number | null;
  p75?: number | null;
  mediana_pilares?: Record<string, number | null>;
  historico_pares?: Record<string, number | null>;
  setor?: string;
  dimensao?: string;
  nota?: string;
};

export type EsgEmpresaBase = {
  nif: string;
  nome: string;
  names?: string[];
  pais: string;
  tipo?: string | null;
  cae_principal?: string | null;
  cae_label?: string | null;
  setor?: string | null;
  setor_label?: string | null;
  setor_fonte?: string | null;
  dimensao?: string | null;
  dimensao_label?: string | null;
  local?: { pais?: string; distrito?: string; concelho?: string; freguesia?: string } | null;
  roles?: string[];
  devedor?: boolean;
  devedores_escalao?: string | null;
  insolvencias?: number;
  contratos_registados?: number | null;
};

export type EsgHistoricoItem = {
  ano: number;
  score: number | null;
  nivel: EsgNivel | null;
  nivel_label: string;
  cobertura: number;
  pilares: Record<string, number | null>;
  contratos: number;
  valor: number;
  n_indicadores: number;
};

export type EsgIndicadorValor = {
  codigo: string;
  label?: string | null;
  pilar?: EsgPilarId | null;
  unidade?: string | null;
  valor: number;
  ano?: number | null;
  fonte?: string | null;
  verificacao?: string | null;
};

export type EsgIndicadorScore = {
  score: number | null;
  n: number;
  detalhes: { codigo: string; label: string; grupo?: string; valor: number; unidade?: string; pontos: number }[];
};

export type EsgContratoEvidencia = {
  id?: string | null;
  ano?: number | null;
  objeto?: string | null;
  valor?: number | null;
  data?: string | null;
  adjudicante?: string | null;
  cpv?: string | null;
  cpv_desc?: string | null;
  procedimento?: string | null;
  ajuste_direto?: boolean;
  ecologico?: boolean;
  n_concorrentes?: number | null;
  dias_publicacao?: number | null;
};

export type EsgFornecedor = {
  nif?: string | null;
  nome: string;
  contratos: number;
  valor: number;
  peso?: number | null;
  ultima_data?: string | null;
  cpv_principal?: string | null;
  cpvs?: { cpv: string; contratos: number }[];
  ecologicos: number;
  ajuste_direto: number;
  sociais: number;
  taxa_ecologicos?: number | null;
  taxa_ajuste_direto?: number | null;
  taxa_sociais?: number | null;
  score?: number | null;
  nivel?: EsgNivel | null;
  nivel_label?: string | null;
  cor?: string | null;
  pilares?: Record<string, number | null>;
  cobertura?: number | null;
  dimensao?: string | null;
  dimensao_label?: string | null;
  setor?: string | null;
  setor_label?: string | null;
  ano?: number | null;
  tem_score?: boolean;
};

export type EsgCarteira = {
  comprador?: { nif: string; nome?: string | null };
  resumo: {
    n_fornecedores: number;
    valor_total?: number | null;
    valor_com_score?: number | null;
    cobertura_score?: number | null;
    score_medio_ponderado?: number | null;
    top10_peso?: number | null;
    n_sem_score?: number;
    n_fracos?: number;
  };
  distribuicao: {
    niveis: { id: string; label: string; cor: string; n: number; valor: number; peso_n?: number | null; peso_valor?: number | null }[];
  };
  fornecedores: EsgFornecedor[];
  alertas: string[];
  metodologia?: string;
  gerado_em?: string;
  contratos_lidos?: number;
  contratos_registados?: number | null;
};

export type EsgEmpresa = EsgEmpresaBase & {
  name: string;
  score: number | null;
  nivel: EsgNivel | null;
  nivel_label: string;
  cor: string;
  cobertura: number;
  confianca: string;
  pilares: Record<string, number | null>;
  contratos: number;
  valor: number;
  adjudicantes: number;
  fornecedores_count?: number | null;
  ano: number;
  anos: number;
  modelo_versao: string;
  gerado_em: string;
  atualizado_em: string;
  fontes: string[];
  avisos: string[];
  empresa: EsgEmpresaBase;
  score_detalhe: {
    score: number | null;
    nivel: EsgNivel | null;
    nivel_label: string;
    cor: string;
    cobertura: number;
    confianca: string;
    pilares: Record<string, number | null>;
    pilares_detalhe: EsgPilarDetalhe[];
    componentes: EsgComponente[];
    fatores: EsgComponente[];
    features: Record<string, unknown>;
    indicadores_score: Record<string, EsgIndicadorScore>;
    n_indicadores: number;
    avisos: string[];
    modelo_versao: string;
    gerado_em: string;
  };
  pilares_detalhe: EsgPilarDetalhe[];
  componentes: EsgComponente[];
  historico: EsgHistoricoItem[];
  benchmark: EsgBenchmark;
  indicadores: {
    ano: number;
    valores: EsgIndicadorValor[];
    fontes: string[];
    score: Record<string, EsgIndicadorScore>;
    catalogo_versao: string;
  };
  evidencias: {
    contratos: EsgContratoEvidencia[];
    cpv_top: { divisao: string; label: string; valor: number; peso: number | null; contratos: number }[];
    compradores: { nif?: string | null; nome?: string | null; contratos: number; valor: number; peso: number }[];
    insolvencias: { especie?: string; ato?: string; data?: string; tribunal?: string; processo?: string }[];
    por_ano: { ano: number; contratos: number; valor: number }[];
  };
  fornecedores?: EsgCarteira | null;
  taxonomia?: EsgTaxonomiaEmpresa;
  taxonomia_elegivel?: boolean;
  taxonomia_alinhamento?: string;
  taxonomia_nace?: string;
  taxonomia_objetivos?: number[];
  taxonomia_atividades?: number[];
  taxonomia_cobertura_verificacao?: number;
  ods?: number[];
  cartao_modelo?: EsgCartao;
};

export type EsgEmpresaResumo = {
  nif: string;
  nome: string;
  pais: string;
  setor?: string | null;
  setor_label?: string | null;
  dimensao?: string | null;
  dimensao_label?: string | null;
  score: number | null;
  nivel: EsgNivel | null;
  nivel_label: string;
  cor: string;
  cobertura: number;
  confianca: string;
  pilares: Record<string, number | null>;
  contratos?: number | null;
  valor?: number | null;
  ano?: number | null;
  benchmark?: EsgBenchmark | null;
  posicao?: number;
  taxonomia_elegivel?: boolean;
  taxonomia_alinhamento?: string;
  taxonomia_objetivos?: number[];
  ods?: number[];
};

export type EsgAnalitica = {
  disponivel: boolean;
  total?: number;
  motivo?: string;
  como_popular?: string;
  media_score?: number | null;
  media_cobertura?: number | null;
  media_pilares?: Record<string, number | null>;
  ultima_atualizacao?: string | null;
  niveis?: { id: EsgNivel; label: string; cor: string; n: number; score_medio: number | null }[];
  setores?: { setor: string; n: number; score_medio: number | null; cobertura_media: number | null }[];
  dimensoes?: { dimensao: string; n: number; score_medio: number | null }[];
  distritos?: { distrito: string; n: number; score_medio: number | null }[];
  anos?: { ano: number; n: number; score_medio: number | null }[];
  destaques_positivos?: EsgEmpresaResumo[];
  destaques_negativos?: EsgEmpresaResumo[];
  taxonomia?: {
    avaliadas: number;
    sem_dados: number;
    elegiveis: number;
    alinhamento: { id: string; label: string; n: number }[];
    objetivos: EsgTaxonomiaObjetivo[];
    ods: EsgOds[];
    fonte: EsgTaxonomiaFonte;
  };
  filtros?: Record<string, unknown>;
};

export type EsgMeta = {
  cartao_modelo: EsgCartao;
  status: {
    disponivel: boolean;
    motivo?: string;
    indices: Record<string, { existe: boolean; total: number; erro?: string }>;
    ultima_atualizacao?: string | null;
    ultimas_execucoes?: Record<string, unknown>[];
    modelo_versao: string;
  };
  setores: { id: string; label: string; nota: string }[];
  cpv_taxonomia: { divisao: string; label: string; verde?: boolean; social?: boolean; circular?: boolean; marrom?: boolean }[];
  indicadores: EsgIndicadorDef[];
  fontes: EsgFonte[];
  taxonomia: EsgTaxonomiaPanorama;
  aviso: string;
};

export type EsgSugestao = {
  nif: string;
  nome: string;
  pais: string;
  tipo?: string | null;
  local?: Record<string, unknown>;
  contratos?: number | null;
  valor?: number | null;
};

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(data?.detail || `Erro ${res.status} em ${path}`);
  }
  return data as T;
}

export async function getEsgMeta(): Promise<EsgMeta> {
  return getJson<EsgMeta>("/esg/meta");
}

export async function getEsgStatus() {
  return getJson<EsgMeta["status"]>("/esg/status");
}

export async function searchEsg(params: {
  q: string;
  pais?: string;
  setor?: string;
  dimensao?: string;
  nivel?: string;
  ordenar?: string;
  pilar?: string;
  size?: number;
  from?: number;
  incluir_nao_indexadas?: boolean;
}) {
  return getJson<{ itens: EsgEmpresaResumo[]; total: number; origem: string; parcial?: boolean; nota?: string; motivo?: string }>(
    `/esg/pesquisa${query(params)}`,
  );
}

export async function suggestEsg(q: string, size = 8) {
  return getJson<{ sugestoes: EsgSugestao[] }>(`/esg/sugestoes${query({ q, size })}`);
}

export async function getEsgRanking(params: {
  pais?: string;
  setor?: string;
  dimensao?: string;
  nivel?: string;
  ano?: number;
  ordenar?: string;
  pilar?: string;
  size?: number;
  from?: number;
}) {
  return getJson<{ itens: EsgEmpresaResumo[]; total: number; ordenar?: string; pilar?: string; filtros?: Record<string, unknown> }>(
    `/esg/ranking${query(params)}`,
  );
}

export function esgRankingCsvUrl(params: {
  pais?: string;
  setor?: string;
  dimensao?: string;
  nivel?: string;
  ano?: number;
  ordenar?: string;
  limite?: number;
}) {
  return `${API_BASE}/esg/ranking.csv${query(params)}`;
}

export async function getEsgAnalitica(params: {
  pais?: string;
  setor?: string;
  dimensao?: string;
  nivel?: string;
  ano?: number;
  q?: string;
} = {}) {
  return getJson<EsgAnalitica>(`/esg/analitica${query(params)}`);
}

export type EsgMapaEmpresa = {
  nif: string;
  nome: string;
  pais: string;
  distrito: string | null;
  concelho: string | null;
  score: number | null;
  nivel: EsgNivel | null;
  nivel_label: string | null;
  cor: string | null;
  cobertura: number | null;
  setor_label: string | null;
  dimensao_label: string | null;
  valor: number | null;
  contratos: number | null;
};

export type EsgMapaRegiao = {
  pais: string;
  distrito: string;
  n: number;
  score_medio: number | null;
  cobertura_media: number | null;
  valor: number;
  nivel: EsgNivel | null;
  nivel_label: string | null;
  cor: string;
  niveis: { id: EsgNivel; label: string; cor: string; n: number }[];
  empresas: string[];
};

export type EsgMapaResposta = {
  disponivel: boolean;
  total: number;
  motivo?: string | null;
  como_popular?: string;
  truncado?: boolean;
  com_localizacao?: number;
  sem_localizacao?: number;
  empresas: EsgMapaEmpresa[];
  regioes: EsgMapaRegiao[];
  filtros?: Record<string, unknown>;
};

export async function getEsgMapa(
  params: { pais?: string; setor?: string; dimensao?: string; nivel?: string; ano?: number; q?: string; limite?: number } = {},
) {
  return getJson<EsgMapaResposta>(`/esg/mapa${query(params)}`);
}

export async function getEsgEmpresa(
  pais: string,
  nif: string,
  params: { ano?: number; historico_anos?: number; incluir_fornecedores?: boolean; indexar?: boolean } = {},
) {
  return getJson<EsgEmpresa>(
    `/esg/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}${query(params)}`,
  );
}

export async function getEsgHistorico(pais: string, nif: string, anos = 3) {
  return getJson<{
    empresa: EsgEmpresaBase;
    ano: number;
    historico: EsgHistoricoItem[];
    benchmark: EsgBenchmark;
    pilares: Record<string, number | null>;
    score: number | null;
    nivel: EsgNivel | null;
    nivel_label: string;
    cobertura: number;
    confianca: string;
    avisos: string[];
    cartao_modelo: EsgCartao;
  }>(`/esg/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}/historico${query({ anos })}`);
}

export async function getEsgFornecedores(
  pais: string,
  nif: string,
  params: { limite?: number; calcular_em_falta?: boolean; max_calcular?: number } = {},
) {
  return getJson<EsgCarteira>(
    `/esg/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}/fornecedores${query(params)}`,
  );
}

export async function getEsgIndicadores(pais: string, nif: string, ano?: number) {
  return getJson<{ nif: string; pais: string; total: number; itens: Record<string, unknown>[] }>(
    `/esg/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}/indicadores${query({ ano })}`,
  );
}

export async function getEsgTaxonomia() {
  return getJson<EsgTaxonomiaPanorama>("/esg/taxonomia");
}

export async function getEsgTaxonomiaAtividades(params: {
  q?: string;
  setor?: string;
  objetivo?: number;
  nace?: string;
  size?: number;
  from?: number;
} = {}) {
  return getJson<{ total: number; itens: EsgTaxonomiaAtividade[]; filtros: Record<string, unknown> }>(
    `/esg/taxonomia/atividades${query(params)}`,
  );
}

export async function getEsgTaxonomiaEmpresa(pais: string, nif: string) {
  return getJson<{
    empresa: EsgEmpresaBase;
    ano: number;
    taxonomia: EsgTaxonomiaEmpresa;
    avisos: string[];
    cartao_modelo: { versao: string; aviso: string };
  }>(`/esg/empresa/${encodeURIComponent(pais)}/${encodeURIComponent(nif)}/taxonomia`);
}

export async function analisarCarteiraEsg(payload: {
  nifs?: string[];
  nomes?: string[];
  pais?: string;
  calcular_em_falta?: boolean;
}) {
  const res = await fetch(`${API_BASE}/esg/carteira/analise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => ({}))) as {
    itens?: {
      nif: string;
      nome?: string | null;
      pais?: string | null;
      setor?: string | null;
      setor_label?: string | null;
      dimensao?: string | null;
      dimensao_label?: string | null;
      score: number | null;
      nivel?: EsgNivel | null;
      nivel_label?: string | null;
      cor?: string | null;
      pilares?: Record<string, number | null>;
      cobertura?: number | null;
      confianca?: string | null;
      contratos?: number | null;
      valor?: number | null;
      erro?: string;
    }[];
    resumo?: {
      n: number;
      com_score?: number;
      score_medio?: number | null;
      cobertura_media?: number | null;
      distribuicao?: { id: string; label: string; cor: string; n: number }[];
    };
    alertas?: string[];
    metodologia?: string;
    detail?: string;
  };
  if (!res.ok) throw new Error(data?.detail || `Erro ${res.status}`);
  return data;
}

export async function ingerirIndicadoresEsg(payload: {
  nif: string;
  nome?: string;
  pais?: string;
  ano: number;
  fonte?: string;
  url?: string;
  verificacao?: "declarada" | "externa";
  origem?: string;
  indicadores: Record<string, number>;
  recalcular?: boolean;
}, token?: string | null) {
  const res = await fetch(`${API_BASE}/esg/indicadores`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: string };
  if (!res.ok) throw new Error(data?.detail || `Erro ${res.status}`);
  return data;
}

export async function calcularLoteEsg(payload: {
  nifs?: string[];
  pais?: string;
  limite?: number;
  min_contratos?: number;
  anos?: number;
  max_contratos?: number;
}, token?: string | null) {
  const res = await fetch(`${API_BASE}/esg/calcular`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown> & { detail?: string };
  if (!res.ok) throw new Error(data?.detail || `Erro ${res.status}`);
  return data;
}
