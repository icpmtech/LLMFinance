/**
 * Cliente da **Pesquisa PessoasIQ** (`/pessoas-iq/pesquisa/*`).
 *
 * Pesquisa Google-like de pessoas agregando várias fontes: cadastro de pessoas,
 * políticos, devedores, executivos municipais, membros do Governo e titulares
 * da Entidade para a Transparência.
 */
import { API_BASE } from "./api";

export type PesquisaPessoasFonte = {
  id: string;
  label: string;
  hint: string;
  icon: string;
};

export type PesquisaPessoasOpen = {
  view: string;
  arg: string;
};

export type PesquisaPessoasItem = {
  id: string;
  nome: string;
  nif?: string | null;
  fonte: string;
  subtitulo: string;
  snippet: string;
  badges: string[];
  extra: Record<string, unknown>;
  open: PesquisaPessoasOpen | null;
};

export type PesquisaPessoasGrupo = {
  id: string;
  label: string;
  hint: string;
  icon: string;
  total: number;
  items: PesquisaPessoasItem[];
  facets: Record<string, unknown>;
  error?: string | null;
};

export type PesquisaPessoasResponse = {
  q: string;
  fonte: string;
  page: number;
  size: number;
  total: number;
  grupos: PesquisaPessoasGrupo[];
  fontes_disponiveis: PesquisaPessoasFonte[];
  timestamp: string;
};

export type PesquisaPessoasSuggestItem = {
  text: string;
  fonte: string;
  arg?: string | null;
  hint?: string | null;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
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

/** Catálogo de fontes disponíveis para a pesquisa. */
export async function getPesquisaPessoasFontes(): Promise<{ fontes: PesquisaPessoasFonte[] }> {
  return request<{ fontes: PesquisaPessoasFonte[] }>("/pessoas-iq/pesquisa/fontes");
}

/** Sugestões enquanto se escreve na caixa de pesquisa. */
export async function suggestPessoas(q: string, limit = 8): Promise<{ q: string; items: PesquisaPessoasSuggestItem[] }> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return request<{ q: string; items: PesquisaPessoasSuggestItem[] }>(`/pessoas-iq/pesquisa/suggest?${params.toString()}`);
}

/** Pesquisa unificada de pessoas. */
export async function pesquisarPessoas(params: {
  q: string;
  fonte?: string;
  page?: number;
  size?: number;
}): Promise<PesquisaPessoasResponse> {
  const query = new URLSearchParams();
  query.set("q", params.q ?? "");
  query.set("fonte", params.fonte ?? "todas");
  query.set("page", String(params.page ?? 1));
  query.set("size", String(params.size ?? 20));
  return request<PesquisaPessoasResponse>(`/pessoas-iq/pesquisa?${query.toString()}`);
}
