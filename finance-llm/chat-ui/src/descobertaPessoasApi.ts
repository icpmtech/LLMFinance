/**
 * Cliente da **Descoberta de Pessoas** (`/descoberta/pessoas/*`) — quem está por
 * trás das empresas.
 *
 * Dão-se uma ou várias empresas (NIF ou nome) e o painel devolve **quem** nelas
 * tem cargos: órgãos sociais, capital, papéis nos processos do CIRE e a rede de
 * cada pessoa para fora do pedido. Com duas ou mais empresas, a leitura que só
 * aí existe é *quem as liga* — quem se senta nas duas. A ficha de uma pessoa
 * junta todos os cargos dela no universo da plataforma.
 */
import { API_BASE } from "./api";
import type { HermesEvidence, HermesMetric, HermesStep } from "./hermesApi";
import type { ContractGraphBuildResponse, SkillRef } from "./types";

/* ------------------------------------------------------------------- tipos */

export type PessoaClasse = "gestao" | "capital" | "processo" | "outro";

export type PessoaRiscoComponente = {
  id: string;
  label: string;
  peso: number;
  unidade: string;
  descricao: string;
  metodo: string;
  pontos: number | null;
  evidencia: string[];
  disponivel: boolean;
  peso_efetivo?: number;
  contributo?: number;
};

/** Risco da pessoa (0–100), na mesma escala do risco das empresas. */
export type PessoaRisco = {
  score: number | null;
  nivel: string | null;
  nivel_label: string;
  cor: string;
  faixa?: string | null;
  cobertura: number;
  confianca: string;
  metodo: string;
  metodo_label: string;
  componentes: PessoaRiscoComponente[];
  fatores: { id: string; label: string; pontos: number | null; contributo: number | null }[];
};

/** Titular com cargo nos dois lados de um contrato. */
export type PessoasConflito = {
  nif: string;
  nome: string;
  classe: PessoaClasse;
  classe_label: string;
  empresa: { nif: string; nome: string; titulo: string };
  contraparte: { nif: string; nome: string; dentro_do_pedido: boolean };
  direcao: string;
  direcoes: string[];
  contratos: number;
  valor: number;
  severidade: "alerta" | "aviso" | "info";
  titulo: string;
};

export type PessoasFonte = {
  id: string;
  label: string;
  grupo: string;
  descricao: string;
  indice?: string | null;
  estado: "ok" | "vazio" | "erro" | "tempo";
  total: number;
  ms?: number | null;
  erro?: string | null;
  nota?: string | null;
};

/** Cargo como o registo o publica (`role`), mais o título limpo e a classe. */
export type PessoaCargo = {
  role: string;
  titulo: string;
  role_org: string;
  evento: string;
  data: string;
  ato: string;
  publicacao: string;
  quota?: number | null;
  causa: string;
  tribunal: string;
  classe?: PessoaClasse;
};

export type PessoaEmpresa = {
  nif: string;
  nome: string;
  cargos: PessoaCargo[];
  cargos_total: number;
  cargo_atual: string;
  titulo?: string;
  role_org: string;
  evento?: string;
  desde: string;
  ultimo: string;
  ato: string;
  classes: PessoaClasse[];
  classe?: PessoaClasse;
  classe_label?: string;
  no_pedido?: boolean;
};

export type PessoaCirePapel = {
  processo: string;
  especie: string;
  ato: string;
  tribunal: string;
  data: string;
  papel: string;
  empresa?: string;
  empresa_nif?: string;
};

export type PessoaDevedores = {
  total: number;
  devedor: boolean;
  entidades: string[];
  escaloes: string[];
  maior_valor_min?: number | null;
};

export type PessoasPessoa = {
  nif: string;
  nome: string;
  is_company: boolean;
  classe: PessoaClasse;
  classe_label: string;
  cargo_atual: string;
  titulo: string;
  titulos: string[];
  role_org: string;
  ato: string;
  desde: string;
  ultimo: string;
  gestao: boolean;
  capital: boolean;
  processo: boolean;
  ligacao: boolean;
  quota?: number | null;
  cargos_pedido: number;
  cargos_universo: number;
  empresas_pedido: number;
  empresas_universo: number;
  origens: string[];
  empresas: PessoaEmpresa[];
  outras_empresas: { nif: string; nome: string }[];
  cire: PessoaCirePapel[];
  devedores?: PessoaDevedores | null;
  risco: PessoaRisco;
  conflitos: number;
  evidencia: string[];
};

export type PessoasEmpresa = {
  nif: string;
  nome: string;
  pessoas: number;
  lidas: number;
  truncado: boolean;
  processos: number;
  processos_total: number;
  cire_pessoas: number;
  estado?: string | null;
  erro?: string | null;
  cire_erro?: string | null;
  ms?: number | null;
};

export type PessoasKpis = {
  empresas: number;
  empresas_com_pessoas: number;
  empresas_sem_pessoas: number;
  pessoas: number;
  cargos: number;
  gestao: number;
  capital: number;
  processo: number;
  em_varias: number;
  universo_multi: number;
  acumulacao: number;
  processos: number;
  cire_pessoas: number;
  devedores: number;
  conflitos: number;
  conflitos_graves: number;
  risco_alto: number;
  risco_critico: number;
  risco_medio: number | null;
  risco_max: number | null;
  cargo_top: { cargo: string; pessoas: number; empresas: number; classe: PessoaClasse } | null;
  profundidade: number | null;
};

export type PessoasLigacao = {
  nif: string;
  nome: string;
  is_company: boolean;
  empresas: { nif: string; nome: string; cargo: string; role_org: string }[];
  empresas_pedido: number;
  cargos: number;
  titulo: string;
  titulos: string[];
  classe: PessoaClasse;
  classe_label: string;
};

export type PessoasCargoBarra = { cargo: string; pessoas: number; empresas: number; classe: PessoaClasse };

export type PessoasAtencao = {
  severidade: "alerta" | "aviso" | "info";
  titulo: string;
  detalhe: string;
  verificar: string;
};

export type PessoasGrafo = ContractGraphBuildResponse & {
  meta: ContractGraphBuildResponse["meta"] & { camadas?: Record<string, number>; valor_das_camadas?: number };
};

export type PessoasPainel = {
  pais: string;
  gerado_em: string;
  ms: number;
  pedido: { empresas: number; analisadas: number; max_empresas: number; fontes: string[] };
  empresas: PessoasEmpresa[];
  pessoas: PessoasPessoa[];
  kpis: PessoasKpis;
  cargos: PessoasCargoBarra[];
  ligacoes: PessoasLigacao[];
  conflitos: PessoasConflito[];
  grafo: PessoasGrafo | null;
  grafo_pessoas: PessoasGrafo | null;
  atencao: PessoasAtencao[];
  fontes: PessoasFonte[];
  leitura: string;
  avisos: string[];
};

export type PessoasMeta = {
  fontes: { id: string; label: string; grupo: string; descricao: string; indice?: string }[];
  grupos: string[];
  pais: string[];
  classes: { id: PessoaClasse; label: string }[];
  orgaos_gestao: string[];
  risco: {
    metodo: string;
    metodo_label: string;
    componentes: { id: string; label: string; peso: number; unidade: string; descricao: string; metodo: string }[];
  };
  limites: Record<string, number>;
};

/** Resposta da análise do Hermes sobre o conjunto de pessoas. */
export type PessoasAnalise = {
  pergunta: string;
  empresas: string[];
  profundidade: string;
  skill_imposta?: string | null;
  text: string;
  mode: "ai" | "factual" | "empty" | string;
  evidence: HermesEvidence[];
  metrics: HermesMetric[];
  steps: HermesStep[];
  skill?: SkillRef | null;
  followups?: string[];
  warnings?: string[];
  notes?: string[];
  elapsed_seconds?: number;
  generated_at?: string;
};

export type PessoaFicha = {
  nif: string;
  nome: string;
  encontrada: boolean;
  erro?: string | null;
  is_company: boolean;
  classe: PessoaClasse;
  classe_label: string;
  cargos_total: number;
  empresas_total: number;
  primeiro: string;
  ultimo: string;
  origens: string[];
  empresas: PessoaEmpresa[];
  quotas: { empresa: string; empresa_nif: string; quota: number; data: string }[];
  perfil: {
    partido: string;
    cargo_publico: string;
    legislatura: string;
    biografia: string;
    foto: string;
    tags: string[];
  } | null;
  nas_empresas_pedido: string[] | null;
  avisos: string[];
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

/* ------------------------------------------------------------------- rotas */

export function getPessoasMeta(): Promise<PessoasMeta> {
  return request<PessoasMeta>("/descoberta/pessoas/meta");
}

export type PessoasOpcoes = {
  nomes?: string[];
  pais?: string;
  maxEmpresas?: number;
  fontes?: string[];
  incluirGrafo?: boolean;
  incluirDevedores?: boolean;
  incluirConflitos?: boolean;
};

export function descobrirPessoas(nifs: string[], opcoes: PessoasOpcoes = {}): Promise<PessoasPainel> {
  const {
    nomes = [],
    pais = "PT",
    maxEmpresas = 6,
    fontes,
    incluirGrafo = true,
    incluirDevedores = true,
    incluirConflitos = true,
  } = opcoes;
  return request<PessoasPainel>("/descoberta/pessoas/descobrir", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      empresas: nifs,
      nomes,
      pais,
      max_empresas: maxEmpresas,
      fontes: fontes?.length ? fontes : undefined,
      incluir_grafo: incluirGrafo,
      incluir_devedores: incluirDevedores,
      incluir_conflitos: incluirConflitos,
    }),
  });
}

export type AnalisePessoasPedido = PessoasOpcoes & {
  pergunta?: string;
  profundidade?: "rapida" | "profunda";
  skillId?: string;
  backend?: string;
  sources?: string[];
};

/** Análise citada do conjunto de pessoas pelo Hermes. */
export function analisarPessoas(nifs: string[], pedido: AnalisePessoasPedido = {}): Promise<PessoasAnalise> {
  const {
    nomes = [],
    pais = "PT",
    maxEmpresas = 6,
    pergunta,
    profundidade = "rapida",
    skillId,
    backend,
    sources,
  } = pedido;
  return request<PessoasAnalise>("/descoberta/pessoas/analise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      empresas: nifs,
      nomes,
      pais,
      max_empresas: maxEmpresas,
      pergunta,
      profundidade,
      skill_id: skillId || undefined,
      backend,
      sources: sources?.length ? sources : undefined,
    }),
  });
}

export function getFichaPessoa(nif: string, empresas: string[] = []): Promise<PessoaFicha> {
  return request<PessoaFicha>(
    `/descoberta/pessoas/pessoa/${encodeURIComponent(nif)}${query({ empresas: empresas.join(",") })}`,
  );
}

/** NIFs de um endereço `/descoberta-pessoas?nifs=a,b`, se a página tiver sido aberta por link direto. */
export function nifsDoEndereco(): string[] {
  if (typeof window === "undefined") return [];
  const valor = new URLSearchParams(window.location.search).get("nifs") || "";
  return valor
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
