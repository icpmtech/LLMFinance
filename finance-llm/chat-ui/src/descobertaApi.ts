/**
 * Cliente da **Descoberta** (`/descoberta/*`) — o painel de controlo de uma empresa.
 *
 * Dá-se um NIF (ou um nome) e o painel devolve tudo o que a plataforma sabe
 * sobre essa empresa (cadastro, contratos, rede de relações, pessoas, registos,
 * risco, marcas e firmas, subvenções, devedores, mercado e notícias), o **grafo
 * de informação** que a liga a essa evidência e a projeção sobre a **ontologia**
 * do IQ OS. A análise citada é escrita pelo **Hermes**, seguindo as skills da
 * biblioteca partilhada.
 */
import { API_BASE } from "./api";
import type { ContractGraphBuildResponse } from "./types";
import type { HermesEvidence, HermesMetric, HermesStep } from "./hermesApi";
import type { SkillRef } from "./types";

/* ------------------------------------------------------------------- tipos */

export type DescobertaFonte = {
  id: string;
  label: string;
  grupo: string;
  descricao: string;
  ontologia: string | null;
  tipo: string;
};

export type FonteEstado = {
  id: string;
  label: string;
  grupo: string;
  ontologia?: string | null;
  tipo?: string | null;
  estado: "ok" | "vazio" | "erro" | "tempo";
  total: number;
  ms?: number;
  erro?: string | null;
};

export type DescobertaKpis = {
  contratos: number;
  valor_total: number;
  adjudicantes: number;
  valor_mediano?: number | null;
  taxa_ajuste_direto?: number | null;
  maior_adjudicante?: { nif?: string; nome: string; contratos: number; valor: number } | null;
  concentracao_maior?: number | null;
  risco?: string | null;
  risco_pontos?: number | null;
  insolvencias: number;
  pessoas: number;
  marcas: number;
  firmas: number;
  subvencoes_valor: number;
  noticias: number;
  sinais: { padrao: string; detalhe: string; total?: number; itens?: number }[];
};

export type DescobertaGrafo = ContractGraphBuildResponse & {
  nif?: string;
  nome?: string;
  meta: ContractGraphBuildResponse["meta"] & { camadas?: Record<string, number>; valor_das_camadas?: number };
};

/** Barra/valores de um gráfico de decisão (o `detalhe` mostra sempre o número cru). */
export type DecisaoValor = { id: string; label: string; valor: number | null; detalhe: string };

export type DecisaoAtencao = {
  severidade: "alerta" | "aviso" | "info";
  titulo: string;
  detalhe: string;
  verificar: string;
};

export type DecisaoContagem = { faixa: string; contratos: number; valor: number; quota: number };
export type DecisaoEscalao = { escalao: string; contratos: number; valor: number; quota: number };

export type DescobertaDecisao = {
  nif: string;
  nome: string;
  leitura: string;
  resumo: {
    contratos: number;
    contratos_lidos: number;
    valor_total: number;
    adjudicantes: number;
    anos: number[];
    taxa_ajuste_direto: number | null;
    hhi: number | null;
    insolvencias: number;
    confianca_risco?: string | null;
    cobertura_risco?: number | null;
  };
  evolucao: { ano: number; contratos: number; valor: number; adjudicantes: number; novos_adjudicantes: number }[];
  concentracao: {
    adjudicantes: number;
    valor_total: number;
    top: { nif?: string; nome: string; contratos: number; valor: number; quota: number }[];
    curva: { ordem: number; nome: string; valor: number; quota: number; quota_acumulada: number }[];
    hhi: number | null;
    top1: number | null;
    top3: number | null;
  };
  cpv: { cpv: string; descricao: string; contratos: number; valor: number; quota: number }[];
  procedimento: {
    taxa_ajuste_direto: number | null;
    itens: {
      procedimento: string;
      contratos: number;
      valor: number;
      quota: number;
      quota_valor: number;
      ajuste_direto: boolean;
    }[];
  };
  escaloes: DecisaoEscalao[];
  precos: {
    mediana: number | null;
    itens: DecisaoContagem[];
    com_ratio: number;
    taxa_aditivo: number | null;
    mediana_efetiva: number | null;
  };
  concorrencia: {
    mediana: number | null;
    media: number | null;
    itens: DecisaoContagem[];
    com_dados: number;
  };
  prazos: {
    itens: { fase: string; dias: number | null; campo: string }[];
    mediana_decisao_publicacao: number | null;
    mediana_publicacao: number | null;
    com_dados: number;
  };
  risco: {
    score: number | null;
    nivel: string | null;
    nivel_label: string | null;
    cor: string | null;
    confianca: string | null;
    cobertura: number | null;
    metodo_label: string | null;
    componentes: {
      id: string;
      label: string;
      pontos: number | null;
      peso: number;
      contributo: number | null;
      disponivel: boolean;
      unidade: string | null;
      evidencia: string[];
    }[];
    fatores: { label?: string; pontos?: number | null; contributo?: number | null }[];
  };
  perfil: DecisaoValor[];
  atencao: DecisaoAtencao[];
  sinais: { padrao: string; detalhe: string; total?: number; itens?: number }[];
};

export type OntologiaTipo = {
  id: string;
  label: string;
  grupo?: string | null;
  declarado: boolean;
  indice_usado?: string | null;
  fontes_declaradas: string[];
  origem_declarada: boolean;
  instancias: number;
  exemplos: { id: string; label: string; valor?: number | null; detalhe?: string }[];
};

export type OntologiaLigacao = {
  id: string;
  label: string;
  from: string;
  to: string;
  declarado: boolean;
  quantidade: number;
  evidencia: string;
};

export type DescobertaOntologia = {
  ontologia: string;
  ontologia_id?: string | null;
  tipos: OntologiaTipo[];
  ligacoes: OntologiaLigacao[];
  catalogo: {
    tipos: { id: string; label: string; grupo?: string | null; fontes: string[]; materializado: boolean }[];
    ligacoes: { id: string; label: string; from: string; to: string; materializado: boolean }[];
  };
  cobertura: {
    tipos_instanciados: number;
    tipos_declarados_usados: number;
    percent_tipos: number | null;
    ligacoes_materializadas: number;
    ligacoes_declaradas: number;
    percent_ligacoes: number | null;
  };
  lacunas: { tipos: string[]; ligacoes: string[] };
  camadas: Record<string, number>;
};

export type DescobertaRecolha = {
  nif: string;
  nome: string;
  pais: string;
  secoes: Record<string, Record<string, unknown>>;
  fontes: FonteEstado[];
  recolhidas: number;
  em_falta: string[];
  ms: number;
  kpis: DescobertaKpis;
  grafo?: DescobertaGrafo;
  ontologia?: DescobertaOntologia;
  decisao?: DescobertaDecisao;
  error?: string;
};

export type DescobertaMeta = {
  fontes: DescobertaFonte[];
  grupos: string[];
  plataforma: { id: string; label: string; hint?: string }[];
  skills: { total: number; ativas: number; usos: number };
  limites: { fontes: number; paralelo: number; timeout_fonte: number; nos_grafo: number };
};

export type DescobertaSkill = {
  id: string;
  nome: string;
  quando?: string | null;
  passos: number;
  verificacoes: number;
  ferramentas: string[];
  usos: number;
  ativa: boolean;
  origem?: string | null;
};

export type DescobertaSkills = {
  total: number;
  ativas: number;
  skills: DescobertaSkill[];
  status?: Record<string, unknown>;
  pergunta?: string;
  sugerida?: SkillRef | null;
  score?: number;
};

export type DescobertaAlvo = {
  nif?: string | null;
  nome?: string | null;
  alias?: string[];
  contratos?: number | null;
  valor?: number | null;
  papeis?: string[];
  concelho?: string | null;
  fonte?: string | null;
  principal?: boolean;
};

export type DescobertaResolucao = {
  query: string;
  nif_detetado?: boolean;
  items: DescobertaAlvo[];
  candidatos?: DescobertaAlvo[];
  detail?: string;
  pais?: string;
};

export type DescobertaAnalise = {
  pergunta: string;
  nif: string;
  profundidade: string;
  depth_label?: string;
  skill_imposta?: string | null;
  text: string;
  mode: "ai" | "factual" | "empty" | string;
  skill?: SkillRef | null;
  evidence: HermesEvidence[];
  metrics: HermesMetric[];
  steps: HermesStep[];
  followups?: string[];
  warnings?: string[];
  notes?: string[];
  elapsed_seconds?: number;
  generated_at?: string;
};

export type AnalisePedido = {
  pergunta?: string;
  profundidade?: "rapida" | "profunda";
  sources?: string[];
  fontes?: string[];
  backend?: string;
  skill_id?: string | null;
  pais?: string;
  nome?: string;
  fontes_recolha?: string[];
};

/* ----------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function withBody(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/* ------------------------------------------------------------------- rotas */

export function getDescobertaMeta(): Promise<DescobertaMeta> {
  return request<DescobertaMeta>("/descoberta/meta");
}

export function listarSkillsDescoberta(pergunta?: string): Promise<DescobertaSkills> {
  return request<DescobertaSkills>(`/descoberta/skills${query({ q: pergunta })}`);
}

export function resolverEmpresa(q: string, size = 8): Promise<DescobertaResolucao> {
  return request<DescobertaResolucao>(`/descoberta/resolver${query({ q, size })}`);
}

export type RecolhaOpcoes = {
  pais?: string;
  nome?: string;
  fontes?: string[];
  incluirGrafo?: boolean;
  incluirOntologia?: boolean;
  incluirDecisao?: boolean;
};

export function descobrirEmpresa(nif: string, opcoes: RecolhaOpcoes = {}): Promise<DescobertaRecolha> {
  const { pais = "PT", nome, fontes, incluirGrafo = true, incluirOntologia = true, incluirDecisao = true } = opcoes;
  return request<DescobertaRecolha>(
    `/descoberta/empresa/${encodeURIComponent(nif)}${query({
      pais,
      nome,
      fontes: fontes?.length ? fontes.join(",") : undefined,
      incluir_grafo: incluirGrafo,
      incluir_ontologia: incluirOntologia,
      incluir_decisao: incluirDecisao,
    })}`,
  );
}

export function getDecisaoEmpresa(nif: string, opcoes: RecolhaOpcoes = {}): Promise<DescobertaDecisao> {
  const { pais = "PT", nome } = opcoes;
  return request<DescobertaDecisao>(
    `/descoberta/empresa/${encodeURIComponent(nif)}/decisao${query({ pais, nome })}`,
  );
}

export function getGrafoEmpresa(nif: string, opcoes: RecolhaOpcoes = {}): Promise<DescobertaGrafo> {
  const { pais = "PT", nome } = opcoes;
  return request<DescobertaGrafo>(
    `/descoberta/empresa/${encodeURIComponent(nif)}/grafo${query({ pais, nome })}`,
  );
}

export function getOntologiaEmpresa(nif: string, opcoes: RecolhaOpcoes = {}): Promise<DescobertaOntologia> {
  const { pais = "PT", nome } = opcoes;
  return request<DescobertaOntologia>(
    `/descoberta/empresa/${encodeURIComponent(nif)}/ontologia${query({ pais, nome })}`,
  );
}

export function analisarEmpresa(nif: string, pedido: AnalisePedido = {}): Promise<DescobertaAnalise> {
  return request<DescobertaAnalise>(
    `/descoberta/empresa/${encodeURIComponent(nif)}/analise`,
    withBody(pedido),
  );
}

/** NIF de um endereço `/descoberta/<NIF>`, se a página tiver sido aberta por link direto. */
export function nifDoEndereco(): string {
  const match = window.location.pathname.match(/^\/descoberta\/(\d{9})/);
  return match ? match[1] : "";
}
