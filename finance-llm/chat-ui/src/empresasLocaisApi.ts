/**
 * Cliente do módulo **Empresas locais** (`/empresas-locais/*`).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type EmpresaLocal = {
  doc_id?: string;
  designacao: string;
  designacao_keyword?: string | null;
  entidade_local?: string | null;
  entidade_local_keyword?: string | null;
  entidade_dominante?: string | null;
  entidade_dominante_keyword?: string | null;
  participacao_pct?: number | null;
  setor?: string | null;
  setor_keyword?: string | null;
  data_constituicao?: string | null;
  observacoes?: string | null;
  observacoes_keyword?: string | null;
  slug?: string | null;
  fonte?: string | null;
  ingested_at?: string | null;
  updated_at?: string | null;
};

export type EmpresasLocaisResponse = {
  total: number;
  page: number;
  size: number;
  items: EmpresaLocal[];
  entidades?: { key: string; count: number }[];
  setores?: { key: string; count: number }[];
  origem?: string;
  error?: string | null;
};

export type EmpresasLocaisStats = {
  index?: string;
  documents?: number;
  por_entidade?: { key: string; count: number }[];
  por_setor?: { key: string; count: number }[];
  origem?: string;
  error?: string;
};

export type EmpresaLocalFicha = EmpresaLocal & {
  error?: string;
};

export type EmpresasLocaisRecolherResponse = {
  recolhido_em: string;
  total: number;
  indexacao: { indexed: number; errors?: number; error?: string };
  fonte?: string;
  error?: string;
};

/* ------------------------------------------------------------------ pedidos */

type Params = Record<string, string | number | boolean | undefined | null>;

function queryString(params: Params): string {
  const search = new URLSearchParams();
  for (const [chave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    search.set(chave, String(valor));
  }
  const texto = search.toString();
  return texto ? `?${texto}` : "";
}

async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detalhe = await res.text().catch(() => "");
    throw new Error(`${res.status} — ${detalhe || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function getEmpresasLocais(params?: {
  q?: string;
  entidade_local?: string;
  setor?: string;
  page?: number;
  size?: number;
}): Promise<EmpresasLocaisResponse> {
  return pedir<EmpresasLocaisResponse>(
    `/empresas-locais${queryString({ ...(params ?? {}) })}`,
  );
}

export function getEmpresasLocaisStats(): Promise<EmpresasLocaisStats> {
  return pedir<EmpresasLocaisStats>("/empresas-locais/stats");
}

export function getEmpresaLocal(doc_id: string): Promise<EmpresaLocalFicha> {
  return pedir<EmpresaLocalFicha>(`/empresas-locais/${encodeURIComponent(doc_id)}`);
}

export function recolherEmpresasLocais(forcar = false): Promise<EmpresasLocaisRecolherResponse> {
  return pedir(`/empresas-locais/recolher${queryString({ forcar })}`, { method: "POST" });
}

/* ------------------------------------------------------------------ formato */

export function dataFormatada(data?: string | null): string {
  if (!data) return "—";
  const [ano, mes, dia] = data.split("-");
  if (!ano || !mes || !dia) return data;
  return `${dia}/${mes}/${ano}`;
}

export function participacaoFormatada(pct?: number | null): string {
  if (pct === undefined || pct === null) return "—";
  return `${pct.toFixed(2).replace(/\.00$/, "")}%`;
}
