/**
 * Cliente do módulo **Remunerações da Administração Pública** (`/remuneracoes-ap/*`).
 *
 * O modelo vem do quadro consolidado que a DGAEP publica por ano: a Tabela
 * Remuneratória Única, as carreiras com as suas posições remuneratórias, os
 * cargos dirigentes e a base legal. Este cliente só lê e simula; a recolha
 * (`/refresh`) exige sessão de escrita e é chamada a partir da própria página.
 */
import { API_BASE } from "./api";

/** Pedido à API com erro legível (o `fetch` já leva o token da sessão). */
async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(`${API_BASE}${path}`, init);
  if (!resposta.ok) {
    const detalhe = await resposta.text().catch(() => "");
    throw new Error(`${resposta.status} — ${detalhe || resposta.statusText}`);
  }
  return (await resposta.json()) as T;
}

/** Uma linha da Tabela Remuneratória Única. */
export type NivelTru = { nivel: number; valor: number | null; nota?: string | null };

/** Parâmetros de referência do ano (BRAP e limites da tabela). */
export type ParametrosAp = {
  ano: number;
  brap: number | null;
  brap_nota?: string | null;
  nivel_minimo?: number | null;
  nivel_maximo?: number | null;
  versao?: string | null;
};

/** Uma posição remuneratória dentro de uma carreira. */
export type PosicaoAp = {
  posicao: string;
  nivel: number | null;
  niveis?: number[];
  niveis_texto?: string | null;
  remuneracao: number | null;
};

/** Uma carreira/categoria com as suas posições. */
export type CarreiraAp = {
  seccao?: string | null;
  carreira: string;
  categoria: string;
  variante?: string | null;
  titulo?: string | null;
  minimo?: number | null;
  maximo?: number | null;
  posicoes: PosicaoAp[];
};

/** Um cargo dirigente (ou equiparado). */
export type DirigenteAp = {
  seccao?: string | null;
  ambito?: string | null;
  grupo?: string | null;
  cargo: string;
  indice?: number | null;
  indice_texto?: string | null;
  nivel?: number | null;
  niveis?: number[];
  niveis_texto?: string | null;
  remuneracao: number | null;
};

/** Notas da DGAEP de uma secção do quadro. */
export type NotasAp = { seccao: string; titulo?: string; texto: string[] };

/** Base legal por carreira (estrutura da carreira, remuneratória e outras). */
export type BaseLegalAp = { seccao: string; cabecalho: string[]; linhas: Record<string, string>[] };

/** Volumetria e proveniência do módulo. */
export type RemuneracoesApStats = {
  anos: number[];
  ano: number | null;
  versao?: string | null;
  contagens: Record<string, number>;
  nivel_minimo?: number | null;
  nivel_maximo?: number | null;
  parametros?: ParametrosAp | null;
};

export type RemuneracoesApMeta = {
  fonte: string;
  fonte_url: string;
  url_base: string;
  ficheiros: Record<string, string>;
  anos: number[];
  ano: number | null;
  secoes: string[];
  secoes_carreiras: string[];
  parametros?: ParametrosAp | null;
  stats: RemuneracoesApStats;
  pagamentos_por_ano: number;
  unidade: string;
  nota: string;
};

/** O resultado do simulador de uma posição. */
export type RemuneracoesApSimulacao = {
  ano: number;
  origem: {
    via?: string;
    nivel?: number | null;
    carreira?: string | null;
    categoria?: string | null;
    posicao?: string | null;
    seccao?: string | null;
    nota?: string | null;
  };
  remuneracao_base_mensal: number;
  pagamentos_por_ano: number;
  remuneracao_base_anual: number;
  posicoes_disponiveis: { posicao?: string; nivel?: number | null; remuneracao?: number | null; carreira?: string | null; categoria?: string | null }[];
  notas: string[];
  error?: string;
};

/* ------------------------------------------------------------------ leitura */

export function getRemuneracoesApMeta(): Promise<RemuneracoesApMeta> {
  return pedir<RemuneracoesApMeta>("/remuneracoes-ap/meta");
}

export function getRemuneracoesApParametros(ano?: number): Promise<ParametrosAp> {
  return pedir<ParametrosAp>(`/remuneracoes-ap/parametros${ano ? `?ano=${ano}` : ""}`);
}

export function getRemuneracoesApNiveis(ano?: number): Promise<{
  ano: number;
  total: number;
  itens: NivelTru[];
  parametros: ParametrosAp;
  notas: string[];
}> {
  return pedir(`/remuneracoes-ap/niveis${ano ? `?ano=${ano}` : ""}`);
}

export function getRemuneracoesApSerie(ano?: number): Promise<{ anos: number[]; itens: { nivel: number; valores: Record<string, number | null> }[] }> {
  return pedir(`/remuneracoes-ap/serie${ano ? `?ano=${ano}` : ""}`);
}

export function getRemuneracoesApCarreiras(
  params: { ano?: number; q?: string; seccao?: string; size?: number; page?: number } = {},
): Promise<{ ano: number; total: number; page: number; size: number; itens: CarreiraAp[] }> {
  return pedir(`/remuneracoes-ap/carreiras${consulta(params)}`);
}

export function getRemuneracoesApDirigentes(params: { ano?: number; q?: string; ambito?: string } = {}): Promise<{
  ano: number;
  total: number;
  itens: DirigenteAp[];
  ambitos: string[];
}> {
  return pedir(`/remuneracoes-ap/dirigentes${consulta(params)}`);
}

export function getRemuneracoesApNotas(params: { ano?: number; seccao?: string } = {}): Promise<{ ano: number; total: number; itens: NotasAp[] }> {
  return pedir(`/remuneracoes-ap/notas${consulta(params)}`);
}

export function getRemuneracoesApBaseLegal(params: { ano?: number; q?: string } = {}): Promise<{ ano: number; total: number; tabelas: BaseLegalAp[] }> {
  return pedir(`/remuneracoes-ap/base-legal${consulta(params)}`);
}

export function getRemuneracoesApSeccoes(ano?: number): Promise<{ ano: number; itens: string[] }> {
  return pedir(`/remuneracoes-ap/seccoes${ano ? `?ano=${ano}` : ""}`);
}

export function simularRemuneracaoAp(params: {
  ano?: number;
  nivel?: number;
  carreira?: string;
  categoria?: string;
  posicao?: string;
  pagamentos?: number;
}): Promise<RemuneracoesApSimulacao> {
  return pedir(`/remuneracoes-ap/simular${consulta(params)}`);
}

/* ------------------------------------------------------------- recolha/índice */

export function recolherRemuneracoesAp(forcar = false): Promise<{ anos: unknown[]; erros: unknown[]; indexado?: unknown }> {
  return pedir(`/remuneracoes-ap/refresh${forcar ? "?forcar=true" : ""}`, { method: "POST" });
}

function consulta(params: Record<string, string | number | undefined>): string {
  const ativos = Object.entries(params).filter(([, valor]) => valor !== undefined && valor !== "" && valor !== null);
  if (!ativos.length) return "";
  return "?" + ativos.map(([chave, valor]) => `${chave}=${encodeURIComponent(String(valor))}`).join("&");
}
