/**
 * Cliente do módulo de inteligência de mercado (`/mercado/*`).
 *
 * O módulo cruza **CPV + CAE + contratos + empresas + entidades** para comparar
 * empresas dentro do mesmo mercado, medir dependências recíprocas com as
 * entidades públicas, seguir a evolução temporal na malha
 * empresa → contrato → entidade → CPV → CAE e simular alterações na rede
 * (World Model) com a sensibilidade medida pelo motor Lorenz.
 *
 * Serve **qualquer área** (prefixos de CPV), região, entidade e período — a
 * saúde é apenas uma das áreas predefinidas.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type MercadoEscopoParams = {
  area?: string;
  cpv?: string;
  ano_de?: number;
  ano_ate?: number;
  regiao?: string;
  nif?: string;
  valor_min?: number;
  valor_max?: number;
  texto?: string;
};

export type MercadoMeta = {
  modulo: string;
  titulo: string;
  descricao: string;
  arquitetura: { camada: string; label: string; detalhe: string }[];
  indicadores: { id: string; label: string; formula: string; nota: string }[];
  eventos: { id: string; label: string }[];
  tabela_cae_cpv: MercadoRegraCaeCpv[];
  graus: Record<string, number>;
  parametros: Record<string, number>;
  limites: string[];
  indices: Record<string, string>;
};

export type MercadoRegraCaeCpv = {
  cae: string;
  cpv: string;
  grau: string;
  nota?: string | null;
  fonte?: string | null;
};

export type MercadoCompatibilidade = {
  grau: string;
  score: number;
  motivo: string;
  regra?: MercadoRegraCaeCpv | null;
  cae?: string | null;
};

export type MercadoDependencia = {
  hhi: number;
  maior_quota: number;
  n_entidades: number;
  entropia?: number;
  hhi_normalizado?: number;
};

export type MercadoEvolucao = {
  anos: number[];
  valores: number[];
  variacao?: number | null;
  cagr?: number | null;
  declive?: number | null;
  n_anos: number;
};

export type MercadoAlerta = { tipo: string; severidade: string; detalhe: string };

export type MercadoContraparte = { nif?: string; nome?: string; valor?: number; contratos?: number; quota?: number };

export type MercadoCpvClasse = {
  classe: string;
  divisao?: string;
  valor: number;
  contratos: number;
  quota?: number;
  compradores?: number;
  fornecedores?: number;
  hhi?: number;
  quota_top1?: number;
  dominante?: MercadoContraparte | null;
  alternativas?: MercadoContraparte[];
};

export type MercadoEmpresaMercado = {
  nif: string;
  nome?: string | null;
  valor: number;
  contratos: number;
  quota: number;
  cae_principal?: string | null;
  cae_label?: string | null;
  caes: string[];
  compatibilidade: string;
  compatibilidade_score: number;
  compatibilidade_motivo?: string | null;
};

export type MercadoQualidade = { grau: string; empresas: number; com_cae: number; cobertura: number; motivo: string };

export type MercadoItem = {
  id: string;
  cpv_classe: string;
  cpv_divisao?: string;
  valor: number;
  contratos: number;
  compradores: number;
  empresas: MercadoEmpresaMercado[];
  empresas_analisadas: number;
  empresas_com_cae: number;
  empresas_compativeis: number;
  cobertura_cae: number;
  cobertura_valor_compativel: number;
  hhi: number;
  quota_lider: number;
  lider?: MercadoEmpresaMercado | null;
  caes_dominantes: { cae: string; label?: string | null; empresas: number; valor: number }[];
  anos: { de?: number | null; ate?: number | null };
  qualidade: MercadoQualidade;
};

export type MercadoMercados = {
  mercados: MercadoItem[];
  total_documentos: number;
  notas: string[];
  erro?: string;
};

export type MercadoBenchmarkEmpresa = {
  nif: string;
  nome: string;
  contratos: number;
  valor: number;
  valor_mediano: number;
  valor_p90: number;
  quota: number;
  entidades_distintas: number;
  maior_entidade?: MercadoContraparte | null;
  dependencia: MercadoDependencia;
  evolucao: MercadoEvolucao;
  cpv_principal?: MercadoCpvClasse | null;
  n_cpvs: number;
  cae_principal?: string | null;
  cae_label?: string | null;
  caes: string[];
  compatibilidade: string;
  compatibilidade_score: number;
  compatibilidade_motivo?: string | null;
  taxa_sem_concurso: number;
  alertas: MercadoAlerta[];
  perfil: string;
  posicao: number;
  erro?: string | null;
};

export type MercadoBenchmark = {
  mercado: {
    cpv?: string | null;
    cpv_label?: MercadoCpvClasse | null;
    area?: string | null;
    area_label?: string | null;
    ano_de?: number | null;
    ano_ate?: number | null;
    regiao?: string | null;
    valor: number;
    contratos: number;
    empresas: number;
    empresas_compativeis: number;
    hhi: number;
    quota_lider: number;
    mediana_valor: number;
    cobertura_cae: number;
  };
  empresas: MercadoBenchmarkEmpresa[];
  avisos: string[];
  limites: { entidades_por_empresa: number; cpvs_por_empresa: number; nota: string };
  notas: string[];
  erro?: string;
};

export type MercadoDependencias = {
  empresas: {
    nif: string;
    nome: string;
    valor: number;
    contratos: number;
    entidades_distintas: number;
    dependencia: MercadoDependencia;
    maior_entidade?: MercadoContraparte | null;
    carteira: MercadoContraparte[];
  }[];
  entidades: {
    nif: string;
    nome: string;
    valor: number;
    contratos: number;
    fornecedores: number;
    dependencia: MercadoDependencia;
    maior_fornecedor?: MercadoContraparte | null;
    alternativas: MercadoContraparte[];
    cpv_principal?: MercadoCpvClasse | null;
    cpvs: MercadoCpvClasse[];
    critico: boolean;
  }[];
  totais: { empresas: number; entidades: number; entidades_criticas: number; empresas_dependentes: number };
  notas: string[];
  erro?: string;
};

export type MercadoGrafoNo = {
  id: string;
  key: string;
  label: string;
  dimension: string;
  type: string;
  role: string;
  count: number;
  total_value: number;
  value: number;
  quota_max?: number;
  cae?: string | null;
  cae_label?: string | null;
  compatibilidade?: string | null;
  data?: string | null;
  fim?: string | null;
  empresa?: string | null;
  entidade?: string | null;
  cpv?: string | null;
};

export type MercadoGrafo = {
  nodes: MercadoGrafoNo[];
  edges: { source: string; target: string; count: number; value: number; relacao: string; quota?: number | null }[];
  meta: { dimension_a: string; dimension_b?: string; metric?: string; nodes_returned?: number; edges_returned?: number; notas?: string[] };
  erro?: string;
};

export type MercadoEvento = {
  evento: string;
  disponivel: boolean;
  motivo?: string;
  alvo?: string | MercadoContraparte | { nif?: string; nome?: string } | null;
  medicao?: Record<string, unknown>;
  hipoteses?: string[];
  notas?: string[];
  evidencia?: Record<string, unknown>[];
};

export type MercadoSensibilidade = {
  disponivel: boolean;
  motivo?: string;
  periodos?: string[];
  parametros?: {
    disponivel: boolean;
    motivo?: string;
    sigma?: number;
    beta?: number;
    rho?: number;
    rho_critico?: number;
    margem?: number;
    razao_fornecedores_compradores?: number;
    autocorrelacao_valor?: number;
    dependencia_atual?: number;
    dependencia_mediana?: number;
    regime?: "amplificador" | "dissipador";
    nota?: string;
  };
  estado?: {
    periodos: string[];
    cru: number[][];
    coordenadas: number[][];
    escala: { mediana: number[]; mad: number[] };
    rotulos?: string[];
  };
  mapa?: { disponivel: boolean; motivo?: string; A?: number[][]; b?: number[]; r2?: number; raio_espectral?: number; pares?: number; nota?: string };
  divergencia?: {
    disponivel: boolean;
    motivo?: string;
    perturbacao_inicial?: number;
    passos?: number;
    direcoes?: number;
    D?: number[];
    D_normalizada?: number[];
    lambda_empirico?: number;
    regime?: "sensivel" | "dissipador";
    nota?: string;
  };
  lorenz?: {
    trajetoria: number[][];
    lyapunov: { lambda: number; tempo_total: number; intervalos: number; perturbacao: number; serie: Record<string, number>[]; regime: string; nota: string };
  } | null;
  nota?: string;
};

export type MercadoCenarios = {
  escopo: Record<string, unknown>;
  gerado_em: string;
  eventos: MercadoEvento[];
  sensibilidade: MercadoSensibilidade;
  duracao_s: number;
  notas: string[];
};

export type MercadoEmpresaFicha = {
  nif: string;
  nome: string;
  cae: { cae_principal?: string | null; cae_principal_label?: string | null; caes?: string[]; nome_registo?: string | null };
  compatibilidade: MercadoCompatibilidade;
  contratos: number;
  valor: number;
  entidades: MercadoContraparte[];
  entidades_distintas: number;
  cpvs: MercadoCpvClasse[];
  dependencia: MercadoDependencia;
  evolucao: MercadoEvolucao;
  taxa_sem_concurso: number;
  alertas: MercadoAlerta[];
  perfil: string;
  evidencias?: MercadoEvidencias;
  erro?: string;
};

export type MercadoEvidenciaContrato = {
  idcontrato: string;
  objeto?: string | null;
  valor: number;
  valor_efetivo: number;
  data?: string | null;
  ano?: number | null;
  procedimento?: string | null;
  cpv?: string | null;
  adjudicante?: string;
  adjudicatario?: string;
};

/** Resposta de `/mercado/evidencias` (mesmo formato das evidências do módulo Lorenz). */
export type MercadoEvidencias = {
  total: number;
  itens: MercadoEvidenciaContrato[];
  erro?: string | null;
};

export type MercadoPares = {
  alvo: { nif: string; nome?: string | null; cpvs: string[]; cae?: Record<string, unknown> };
  mercado: MercadoBenchmark["mercado"];
  pares: MercadoBenchmarkEmpresa[];
  avisos: string[];
  notas: string[];
  erro?: string;
};

/* ----------------------------------------------------------------- pedidos */

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(`${API_BASE}${caminho}`, init);
  const texto = await resposta.text();
  let dados: unknown = null;
  try {
    dados = texto ? JSON.parse(texto) : null;
  } catch {
    dados = null;
  }
  if (!resposta.ok) {
    const detalhe = (dados as { detail?: string } | null)?.detail;
    throw new Error(detalhe || `Erro ${resposta.status} em ${caminho}`);
  }
  return dados as T;
}

function comCorpo(metodo: "POST" | "PUT", corpo?: unknown): RequestInit {
  return {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  };
}

/** Constrói a query string do escopo (só os campos preenchidos). */
export function queryEscopo(params: MercadoEscopoParams & Record<string, string | number | boolean | undefined>): string {
  const busca = new URLSearchParams();
  Object.entries(params).forEach(([chave, valor]) => {
    if (valor === undefined || valor === null || valor === "") return;
    busca.set(chave, String(valor));
  });
  const texto = busca.toString();
  return texto ? `?${texto}` : "";
}

function listaNifs(nifs?: string[] | string | null): string | undefined {
  if (!nifs) return undefined;
  const lista = (Array.isArray(nifs) ? nifs : String(nifs).split(",")).map((item) => item.trim()).filter(Boolean);
  return lista.length ? lista.join(",") : undefined;
}

/* ------------------------------------------------------------- metamodelo */

export function getMercadoMeta() {
  return pedir<MercadoMeta>("/mercado/meta");
}

export function getMercadoTabela() {
  return pedir<{ regras: MercadoRegraCaeCpv[]; parametros: Record<string, number>; graus: Record<string, number> }>("/mercado/tabela");
}

export function guardarMercadoTabela(regras: MercadoRegraCaeCpv[], parametros?: Record<string, number>) {
  return pedir<{ ok: boolean; regras: MercadoRegraCaeCpv[]; parametros: Record<string, number> }>(
    "/mercado/tabela",
    comCorpo("PUT", { regras, parametros }),
  );
}

export function getMercadoCompatibilidade(cae: string, cpv: string) {
  return pedir<MercadoCompatibilidade>(`/mercado/compatibilidade?cae=${encodeURIComponent(cae)}&cpv=${encodeURIComponent(cpv)}`);
}

/* ------------------------------------------------------------------ análise */

export function getMercadoMercados(params: MercadoEscopoParams & { top?: number }) {
  return pedir<MercadoMercados>(`/mercado/mercados${queryEscopo(params)}`);
}

export function getMercadoBenchmark(params: MercadoEscopoParams & { nifs?: string[] | string; limite?: number }) {
  const { nifs, ...resto } = params;
  return pedir<MercadoBenchmark>(`/mercado/benchmark${queryEscopo({ ...resto, nifs: listaNifs(nifs) })}`);
}

export function getMercadoEmpresa(nif: string, params: MercadoEscopoParams = {}) {
  return pedir<MercadoEmpresaFicha>(`/mercado/empresa/${encodeURIComponent(nif)}${queryEscopo(params)}`);
}

export function getMercadoPares(nif: string, params: MercadoEscopoParams & { limite?: number } = {}) {
  return pedir<MercadoPares>(`/mercado/pares${queryEscopo({ ...params, nif })}`);
}

export function getMercadoDependencias(params: MercadoEscopoParams & { nifs?: string[] | string }) {
  const { nifs, ...resto } = params;
  return pedir<MercadoDependencias>(`/mercado/dependencias${queryEscopo({ ...resto, nifs: listaNifs(nifs) })}`);
}

export function getMercadoGrafo(params: MercadoEscopoParams & { nifs?: string[] | string; contratos?: number }) {
  const { nifs, ...resto } = params;
  return pedir<MercadoGrafo>(`/mercado/grafo${queryEscopo({ ...resto, nifs: listaNifs(nifs) })}`);
}

export function getMercadoCenarios(
  params: MercadoEscopoParams & {
    nif?: string;
    entidade_nif?: string;
    fornecedor_nif?: string;
    horizonte_dias?: number;
    forca_relativa?: number;
    variacao_precos?: number;
  },
) {
  return pedir<MercadoCenarios>(`/mercado/cenarios${queryEscopo(params)}`);
}

export function getMercadoSensibilidade(params: MercadoEscopoParams) {
  return pedir<MercadoSensibilidade>(`/mercado/sensibilidade${queryEscopo(params)}`);
}

export function getMercadoEvidencias(
  params: MercadoEscopoParams & { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; limite?: number },
) {
  return pedir<MercadoEvidencias>(`/mercado/evidencias${queryEscopo(params)}`);
}

/* ---------------------------------------------------------------- execuções */

export function getMercadoExecucoes(limite = 20) {
  return pedir<{ itens: Record<string, unknown>[] }>(`/mercado/execucoes?limite=${limite}`);
}

export function guardarMercadoExecucao(payload: MercadoEscopoParams & { titulo?: string; nifs?: string[]; limite?: number }) {
  return pedir<{ ok: boolean; run_id: string; titulo: string }>("/mercado/execucoes", comCorpo("POST", payload));
}

export function obterMercadoExecucao(runId: string) {
  return pedir<Record<string, unknown>>(`/mercado/execucoes/${encodeURIComponent(runId)}`);
}
