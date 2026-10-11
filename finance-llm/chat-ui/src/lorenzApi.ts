/**
 * Cliente do módulo Lorenz 1963 (`/lorenz/*`) — dinâmica da contratação pública.
 *
 * O módulo mede o **estado observado** (contratos, valor, concentração,
 * dispersão), a **sensibilidade às condições iniciais** (mapa discreto ajustado
 * à série, divergência `D_t`, expoente de Lyapunov) e a **propagação** de uma
 * perturbação no grafo comprador↔fornecedor (atrasos de 7/30/60 dias), com
 * evidências verificáveis. Serve **qualquer área** (prefixos de CPV), região,
 * entidade e intervalo de anos — a saúde é apenas uma das áreas predefinidas.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type LorenzEscopoParams = {
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

export type LorenzArea = {
  id: string;
  label: string;
  cpv_prefixos: string[];
  descricao?: string;
};

export type LorenzMeta = {
  modulo: string;
  titulo: string;
  descricao: string;
  arquitetura: { camada: string; label: string; detalhe: string }[];
  areas: LorenzArea[];
  parametros: Record<string, unknown>;
  atrasos_dias: number[];
  ambitos: { id: string; label: string; detalhe?: string }[];
  indices: Record<string, string>;
  documentos?: number | null;
  limites: { top_compradores: number; top_cpvs: number; nota?: string };
  notas: string[];
};

export type LorenzPeriodo = {
  periodo: string;
  contratos: number;
  valor: number;
  valor_efetivo: number;
  p50: number;
  p95: number;
  p99: number;
  cauda: number;
  compradores: number;
  fornecedores: number;
  quota_top1: number;
  hhi_top: number;
  cobertura_top: number;
  ajuste_direto: number;
  taxa_ajuste_direto: number;
  top_fornecedores: { nif: string; valor: number; contratos: number; quota: number }[];
};

export type LorenzEstado = {
  periodos: string[];
  cru: number[][];
  coordenadas: number[][];
  escala: { mediana: number[]; mad: number[] };
  rotulos?: string[];
};

export type LorenzParametros = {
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

export type LorenzKpis = {
  periodos: number;
  primeiro_periodo?: string | null;
  ultimo_periodo?: string | null;
  contratos: number;
  valor: number;
  valor_medio: number;
  taxa_ajuste_direto: number;
  compradores_analisados: number;
  compradores_fragies: number;
  quota_top1_media: number;
  hhi_medio: number;
  fornecedor_mais_exposto?: { nome: string; nif: string; valor: number; quota_max: number; compradores: number } | null;
  cpvs_single_source: number;
  cpvs_analisados: number;
  dependencia_media: number;
  regime_dados?: "sensivel" | "dissipador" | null;
  lambda_empirico?: number | null;
  regime_lorenz?: "amplificador" | "dissipador" | null;
  margem_caos?: number | null;
  lambda_lorenz?: number | null;
  coordenadas?: number[] | null;
};

export type LorenzAlerta = {
  origem: "dependencia" | "cpv" | "amplificacao";
  tipo: string;
  severidade: "alta" | "média" | "baixa";
  entidade: string;
  nif?: string | null;
  medida: string;
  detalhe?: string;
  evidencia?: Record<string, unknown>;
};

export type LorenzComprador = {
  nif?: string | null;
  nome: string;
  valor: number;
  contratos: number;
  quota_top1: number;
  hhi_top: number;
  cobertura_top: number;
  n_fornecedores_top?: number;
  taxa_ajuste_direto: number;
  critico?: boolean;
  fragilidade?: number;
  alternativa_top1?: number;
  fornecedores?: LorenzFornecedorRelacao[];
  cpvs?: LorenzCpvMistura[];
  top_fornecedor?: LorenzFornecedorRelacao | null;
};

export type LorenzFornecedorRelacao = {
  nif?: string | null;
  nome: string;
  valor: number;
  contratos: number;
  quota: number;
};

export type LorenzCpvMistura = {
  codigo: string;
  classe: string;
  divisao: string;
  valor: number;
  contratos: number;
  quota: number;
};

/** Fornecedor com a exposição agregada (quem depende dele e quanto). */
export type LorenzFornecedor = {
  nif?: string | null;
  nome: string;
  valor: number;
  contratos: number;
  n_compradores?: number;
  dependencia_media?: number;
  quota_max?: number;
  compradores?: {
    nif?: string | null;
    nome: string;
    valor: number;
    quota: number;
    contratos: number;
  }[];
  criticos?: { nif?: string | null; nome: string; quota: number; valor: number; contratos: number }[];
};

export type LorenzCpvClasse = {
  classe: string;
  divisao: string;
  valor: number;
  contratos: number;
  fornecedores: LorenzFornecedorRelacao[];
  compradores?: number;
  quota_top1: number;
  hhi: number;
  cobertura_top: number;
  dominante?: LorenzFornecedorRelacao | null;
  alternativas?: LorenzFornecedorRelacao[];
  fragilidade: number;
  single_source: boolean;
};

export type LorenzAmplificador = {
  nif?: string | null;
  nome: string;
  valor: number;
  contratos: number;
  compradores: number;
  alcance: number;
  exposicao: number;
  quota_max: number;
  dificuldade_media: number;
  amplificacao: number;
  contribuintes: {
    comprador: string;
    nif?: string | null;
    quota: number;
    valor: number;
    dificuldade_substituicao: number;
    contribuicao: number;
  }[];
};

export type LorenzPropagacao = {
  disponivel: boolean;
  motivo?: string;
  origem: { nif?: string | null; nome: string; valor: number; contratos: number };
  atraso_dias: number;
  perda_capacidade: number;
  premio_urgencia: number;
  diretos: {
    comprador_nif?: string | null;
    comprador_nome: string;
    quota: number;
    valor: number;
    contratos: number;
    exposto: number;
    dificuldade_substituicao: number;
    sobrecusto_estimado: number;
    criticidade: number;
    critico: boolean;
    alternativas: { nif?: string | null; nome: string; quota: number; cpv?: string; valor_no_cpv?: number }[];
  }[];
  segunda_ordem: {
    nif?: string | null;
    nome: string;
    valor_realocado: number;
    nova_quota_estimada: number;
    nova_dependencia: boolean;
    n_compradores: number;
    compradores: { nome: string; acrescimo: number; cpv?: string }[];
  }[];
  novos_fragies: LorenzPropagacao["segunda_ordem"];
  impacto_total_estimado: number;
  mitigacoes: {
    entidade: string;
    acao: string;
    quota_atual: number;
    quota_alvo: number;
    alternativas?: { nome: string; nif?: string | null; cpv?: string; quota_no_cpv: number }[];
  }[];
  hipoteses: string[];
  cenarios?: {
    atraso_dias: number;
    premio: number;
    impacto_total: number;
    compradores_afetados: number;
    criticos: number;
    novos_fragies: number;
    fator_vs_7d?: number | null;
  }[];
  sensibilidade?: {
    pontos: { perda: number; impacto: number; afetados: number; novos_fragies: number }[];
    inclinacao: number;
    unidade?: string;
    nota?: string;
  };
  evidencias?: LorenzEvidencias;
};

export type LorenzEvidencias = {
  total: number;
  itens: {
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
  }[];
  erro?: string | null;
};

export type LorenzDinamica = {
  mapa: {
    disponivel: boolean;
    motivo?: string;
    A?: number[][];
    b?: number[];
    r2?: number;
    raio_espectral?: number;
    pares?: number;
    nota?: string;
  };
  divergencia: {
    disponivel?: boolean;
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
    parametros: LorenzParametros;
    semente: number[];
    trajetoria: number[][];
    lyapunov: { lambda: number; tempo_total: number; intervalos: number; perturbacao: number; regime: string; nota?: string };
  } | null;
};

export type LorenzPanorama = {
  escopo: Record<string, unknown>;
  gerado_em: string;
  kpis: LorenzKpis;
  serie: { granularidade: string; total_documentos: number; periodos: LorenzPeriodo[] };
  estado: LorenzEstado;
  dinamica: LorenzDinamica;
  dependencias: {
    compradores: LorenzComprador[];
    fornecedores: LorenzFornecedor[];
    alertas: LorenzAlerta[];
    alertas_por_origem?: Record<string, number>;
    limiares: { critico: number; fragil: number };
  };
  cpvs: { classes: LorenzCpvClasse[]; single_source: number; notas: string[] };
  amplificadores: LorenzAmplificador[];
  cenarios_atraso: LorenzPropagacao["cenarios"];
  cobertura: Record<string, number | null>;
  hipoteses: string[];
  tempos: Record<string, number>;
  duracao_s: number;
  notas: string[];
  grafo?: LorenzGrafo;
  erro?: string;
};

export type LorenzGrafo = {
  nodes: {
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
  }[];
  edges: { source: string; target: string; count: number; value: number; quota?: number }[];
  meta: Record<string, unknown>;
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
export function queryEscopo(params: LorenzEscopoParams & Record<string, string | number | boolean | undefined>): string {
  const busca = new URLSearchParams();
  Object.entries(params).forEach(([chave, valor]) => {
    if (valor === undefined || valor === null || valor === "") return;
    busca.set(chave, String(valor));
  });
  const texto = busca.toString();
  return texto ? `?${texto}` : "";
}

/* ------------------------------------------------------------- metamodelo */

export function getLorenzMeta() {
  return pedir<LorenzMeta>("/lorenz/meta");
}

export function getLorenzAreas() {
  return pedir<{ areas: LorenzArea[]; parametros: Record<string, unknown> }>("/lorenz/areas");
}

export function guardarLorenzAreas(areas: LorenzArea[], parametros?: Record<string, unknown>) {
  return pedir<{ ok: boolean; areas: LorenzArea[]; parametros: Record<string, unknown> }>(
    "/lorenz/areas",
    comCorpo("PUT", { areas, parametros }),
  );
}

/* ------------------------------------------------------------------ análise */

export function getLorenzPanorama(params: LorenzEscopoParams & { grafo?: boolean }) {
  return pedir<LorenzPanorama>(`/lorenz/panorama${queryEscopo(params)}`);
}

export function getLorenzSerie(params: LorenzEscopoParams & { granularidade?: "ano" | "trimestre" }) {
  return pedir<{
    granularidade: string;
    total_documentos: number;
    periodos: LorenzPeriodo[];
    estado: LorenzEstado;
    parametros_estimados: LorenzParametros;
    erro?: string;
  }>(`/lorenz/serie${queryEscopo(params)}`);
}

export function getLorenzGrafo(params: LorenzEscopoParams & { top_compradores?: number; limite_fornecedores?: number }) {
  return pedir<LorenzGrafo>(`/lorenz/grafo${queryEscopo(params)}`);
}

export function getLorenzCpv(params: LorenzEscopoParams & { top_cpvs?: number }) {
  return pedir<{ classes: LorenzCpvClasse[]; single_source: number; notas: string[] }>(`/lorenz/cpv${queryEscopo(params)}`);
}

export function getLorenzEntidades(params: LorenzEscopoParams & { top_compradores?: number }) {
  return pedir<{
    compradores: LorenzComprador[];
    fornecedores: LorenzFornecedor[];
    alertas: LorenzAlerta[];
    amplificadores: LorenzAmplificador[];
    limiares: { critico: number; fragil: number };
  }>(`/lorenz/entidades${queryEscopo(params)}`);
}

export function getLorenzPropagacao(params: LorenzEscopoParams & { fornecedor_nif?: string; fornecedor_nome?: string; atraso_dias?: number }) {
  return pedir<LorenzPropagacao>(`/lorenz/propagacao${queryEscopo(params)}`);
}

export function getLorenzCenarios(params: LorenzEscopoParams & { fornecedor_nif?: string }) {
  return pedir<{
    cenarios: { fornecedor: LorenzPropagacao["origem"] | null; cenarios: NonNullable<LorenzPropagacao["cenarios"]> };
    sensibilidade: NonNullable<LorenzPropagacao["sensibilidade"]>;
  }>(`/lorenz/cenarios${queryEscopo(params)}`);
}

export function getLorenzEvidencias(
  params: LorenzEscopoParams & { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; limite?: number },
) {
  return pedir<LorenzEvidencias>(`/lorenz/evidencias${queryEscopo(params)}`);
}

/* ---------------------------------------------------------------- execuções */

export function getLorenzExecucoes(limite = 20) {
  return pedir<{ itens: Record<string, unknown>[] }>(`/lorenz/execucoes?limite=${limite}`);
}

export function guardarLorenzExecucao(payload: LorenzEscopoParams & { titulo?: string }) {
  return pedir<{ ok: boolean; run_id: string; titulo: string; kpis?: LorenzKpis }>("/lorenz/execucoes", comCorpo("POST", payload));
}

export function obterLorenzExecucao(runId: string) {
  return pedir<Record<string, unknown>>(`/lorenz/execucoes/${encodeURIComponent(runId)}`);
}
