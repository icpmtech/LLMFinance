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

export function getCurvaTreino(limite = 400): Promise<{ pontos: PontoTreino[]; total: number }> {
  return pedir(`/llm/modelo/metricas?limite=${limite}`);
}

export function perguntarAoModelo(payload: {
  instrucao: string;
  dados: string;
  max_tokens?: number;
  temperatura?: number;
}): Promise<RespostaModelo> {
  return pedir<RespostaModelo>("/llm/modelo/chat", { method: "POST", body: JSON.stringify(payload) });
}

export function correrAvaliacao(payload: { limite?: number; gerar?: number; holdout?: number; seed?: number } = {}) {
  return pedir<ResultadoAvaliacao>("/llm/modelo/avaliar", { method: "POST", body: JSON.stringify(payload) });
}

export function listarAvaliacoes(size = 20): Promise<{ avaliacoes: ResultadoAvaliacao[]; total: number }> {
  return pedir(`/llm/modelo/avaliacoes?size=${size}`);
}
