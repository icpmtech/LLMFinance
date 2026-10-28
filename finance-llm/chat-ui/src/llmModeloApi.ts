/**
 * Cliente do **modelo de contratos** (`/llm/modelo/*`).
 *
 * O modelo é o resultado do fine-tuning LoRA (Qwen2.5-0.5B-Instruct) treinado
 * com pares extraídos dos índices `contratos`, `finance_entities` e
 * `finance_subvencoes` — ver `docs/modelo-contratos.md`.
 */
import { API_BASE } from "./api";
import { getToken } from "./authApi";

export type PontoTreino = {
  step: number;
  perda: number;
  perplexidade: number;
  tokens: number;
  segundos: number;
  /** Instante absoluto (epoch, segundos) — distingue «em curso» de «parou». */
  ts?: number;
};

export type ModeloEstado = {
  modelo_base: string;
  adaptador: string;
  adaptador_disponivel: boolean;
  pausado: boolean;
  treino: {
    estado?: string;
    modelo_base?: string;
    adaptador?: string;
    lora?: { r?: number; alpha?: number; targets?: string[] };
    dados?: {
      ficheiro?: string;
      pares_treino?: number;
      pares_holdout?: number;
      fontes?: string[];
    };
    treino?: {
      passos?: number;
      passos_planeados?: number;
      epocas?: number;
      lr?: number;
      batch_size?: number;
      grad_accum?: number;
      max_length?: number;
      tokens?: number;
      perda_final?: number | null;
      segundos?: number;
      concluido_em?: string;
    };
  };
  metricas: {
    pontos: number;
    ultima_perda: number | null;
    ultima_perplexidade: number | null;
    tokens: number | null;
    curva: PontoTreino[];
  };
  fonte_dados: { ficheiro: string; indices: string[]; exportador: string };
  verificado_em: string;
};

export type RespostaModelo = {
  resposta: string;
  modelo: string;
  adaptador: string | null;
  prompt_tokens: number;
  tokens_gerados: number;
  tokens: { token: string; id: number; probabilidade?: number; entropia?: number }[];
  confianca_media: number | null;
  verificacao: { suportados?: string[]; inventados?: string[]; confianca?: number; motivo?: string };
  passos: { fase: string; titulo: string; detalhe: string; dados: Record<string, unknown> }[];
  evidencias: { fonte?: string; titulo?: string; texto?: string; doc_id?: string }[];
  skills: string[];
  prompt_sistema: string;
  duracao_s: number;
};

export type PedidoChat = {
  instrucao: string;
  dados?: string;
  max_tokens?: number;
  temperatura?: number;
  prompt_id?: string | null;
  sistema?: string | null;
  usar_rag?: boolean;
  usar_memoria?: boolean;
  usar_skills?: boolean;
  raciocinio?: boolean;
};

export type MatrizAdaptador = {
  disponivel: boolean;
  motivo?: string;
  camadas?: number[];
  modulos?: string[];
  valores?: number[][];
  detalhe?: Record<string, { A: number; B: number; produto: number }>;
  minimo?: number;
  maximo?: number;
  media?: number;
  lora_r?: number;
  lora_alpha?: number;
  escala?: number;
  parametros?: number;
  tamanho_bytes?: number;
  adaptado_em?: string;
};

export type AmostraDePesos = {
  camada: number;
  modulo: string;
  formas: { A: number[]; B: number[] };
  norma: { A: number; B: number; produto: number };
  A: number[][];
  B: number[][];
};

export type Ligacoes = {
  fontes: { id: string; indice: string; pares: number; fracao: number }[];
  dataset: { ficheiro: string | null; pares: number; pares_treino?: number; pares_holdout?: number };
  treino: { passos?: number; passos_planeados?: number; tokens?: number; segundos?: number; perda_final?: number };
  adaptador: { nome: string; lora_r?: number; parametros?: number };
};

export type ItemMemoria = {
  id: string;
  tipo: "memoria" | "skill";
  titulo: string;
  instrucao?: string;
  dados?: string;
  resposta?: string;
  gatilhos?: string[];
  origem?: string;
  usos?: number;
  criado_em?: string;
};

export type PromptSistema = {
  id: string;
  nome: string;
  texto: string;
  predefinido?: boolean;
};

export type SkillExecutavel = {
  nome: string;
  descricao: string;
  gatilhos: string[];
  tipo: string;
};

export type EstadoFeedback = {
  total: number;
  uteis: number;
  corrigidos: number;
  por_utilizar: number;
  nota_media: number | null;
};

export type EstadoRetreino = {
  a_correr: boolean;
  passo: number;
  passos: number;
  perda: number | null;
  iniciado: string | null;
  concluido: string | null;
  pares: number;
  erro: string | null;
  /** Quantos backups do adaptador existem (um por adaptação). */
  versoes?: number;
  feedback?: EstadoFeedback;
  ultimo_resultado?: {
    estado: string;
    pares?: number;
    passos?: number;
    perda_antes?: number;
    perda_depois?: number;
    delta?: number;
    segundos?: number;
    mensagem?: string;
    backup?: string;
    concluido_em?: string;
  } | null;
};

export type AmostraAvaliacao = {
  instrucao: string;
  dados: string;
  gabarito: string;
  gerado: string;
  f1: number;
  numeros: number | null;
};

export type ResultadoAvaliacao = {
  id?: string;
  modelo_base?: string;
  adaptador?: string;
  conjunto?: { pares?: number; ficheiro?: string; origem?: string[]; holdout_total?: number };
  base?: { perplexidade?: number; exactidao_token?: number; perda_por_token?: number };
  treinado?: { perplexidade?: number; exactidao_token?: number; perda_por_token?: number } | null;
  delta?: { perplexidade?: number; exactidao_token?: number; f1_medio?: number };
  f1_medio?: number | null;
  fidelidade_numerica?: number | null;
  amostras?: AmostraAvaliacao[];
  duracao_s?: number;
  criado_em?: string;
  documento?: string | null;
  origem?: string;
  geracao?: { f1_medio: number; fidelidade_numerica: number | null; amostras: AmostraAvaliacao[] };
  nota?: string;
};

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  const resposta = await fetch(`${API_BASE}${caminho}`, { ...init, headers });
  if (!resposta.ok) {
    let detalhe = `${resposta.status} ${resposta.statusText}`;
    try {
      const corpo = await resposta.json();
      if (corpo?.detail) detalhe = String(corpo.detail);
    } catch {
      /* corpo não-JSON: fica o estado HTTP */
    }
    throw new Error(detalhe);
  }
  return (await resposta.json()) as T;
}

export function getModeloEstado(): Promise<ModeloEstado> {
  return pedir<ModeloEstado>("/llm/modelo");
}

export function getMatriz(): Promise<MatrizAdaptador> {
  return pedir<MatrizAdaptador>("/llm/modelo/matriz");
}

export function getAmostraDePesos(camada: number, modulo: string): Promise<AmostraDePesos> {
  return pedir<AmostraDePesos>(`/llm/modelo/matriz/${camada}/${modulo}`);
}

export function getLigacoes(): Promise<Ligacoes> {
  return pedir<Ligacoes>("/llm/modelo/ligacoes");
}

export function getSkills(): Promise<{ skills: SkillExecutavel[]; total: number }> {
  return pedir("/llm/modelo/skills");
}

export function listarMemorias(tipo?: "memoria" | "skill"): Promise<{ itens: ItemMemoria[]; total: number }> {
  return pedir(`/llm/modelo/memoria${tipo ? `?tipo=${tipo}` : ""}`);
}

export function guardarMemoria(payload: {
  tipo: "memoria" | "skill";
  titulo: string;
  instrucao?: string;
  dados?: string;
  resposta?: string;
  gatilhos?: string[];
}): Promise<{ id: string; ok: boolean }> {
  return pedir("/llm/modelo/memoria", { method: "POST", body: JSON.stringify(payload) });
}

export function apagarMemoria(id: string): Promise<{ ok: boolean }> {
  return pedir(`/llm/modelo/memoria/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getPrompts(): Promise<{ prompts: PromptSistema[]; total: number }> {
  return pedir("/llm/modelo/prompts");
}

export function guardarPrompt(payload: { prompt_id?: string; nome: string; texto: string }) {
  return pedir<{ id: string; ok: boolean }>("/llm/modelo/prompts", { method: "POST", body: JSON.stringify(payload) });
}

export function getEstadoRag(): Promise<{ disponivel: boolean; documentos: number | string; indice?: string }> {
  return pedir("/llm/modelo/rag");
}

export function indexarRag(payload: { max_por_fonte?: number; fontes?: string[] } = {}) {
  return pedir<{ total: number; fontes: Record<string, { lidos: number; escritos: number }> }>("/llm/modelo/rag", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function pesquisarRag(q: string, k = 5) {
  return pedir<{ itens: { fonte?: string; titulo?: string; texto?: string; doc_id?: string }[]; total: number }>(
    `/llm/modelo/rag/pesquisa?q=${encodeURIComponent(q)}&k=${k}`,
  );
}

export function enviarFeedback(payload: {
  instrucao: string;
  dados?: string;
  resposta?: string;
  correcao?: string;
  nota?: number;
  skills?: string[];
  usou_rag?: boolean;
  raciocinio?: boolean;
}) {
  return pedir<{ id: string; ok: boolean; pares_de_treino: number }>("/llm/modelo/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getEstadoFeedback(): Promise<EstadoFeedback> {
  return pedir<EstadoFeedback>("/llm/modelo/feedback");
}

export function getEstadoRetreino(): Promise<EstadoRetreino> {
  return pedir<EstadoRetreino>("/llm/modelo/retreinar");
}

export function pedirRetreino(payload: { passos?: number; lr?: number } = {}) {
  return pedir<{ estado: string; passos?: number; ja_estava_a_correr?: boolean }>("/llm/modelo/retreinar", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCurvaTreino(limite = 400): Promise<{ pontos: PontoTreino[]; total: number }> {
  return pedir(`/llm/modelo/metricas?limite=${limite}`);
}

export function perguntarAoModelo(payload: PedidoChat): Promise<RespostaModelo> {
  return pedir<RespostaModelo>("/llm/modelo/chat", { method: "POST", body: JSON.stringify(payload) });
}

export function correrAvaliacao(payload: { limite?: number; gerar?: number; holdout?: number; seed?: number } = {}) {
  return pedir<ResultadoAvaliacao>("/llm/modelo/avaliar", { method: "POST", body: JSON.stringify(payload) });
}

export function listarAvaliacoes(size = 20): Promise<{ avaliacoes: ResultadoAvaliacao[]; total: number }> {
  return pedir(`/llm/modelo/avaliacoes?size=${size}`);
}
