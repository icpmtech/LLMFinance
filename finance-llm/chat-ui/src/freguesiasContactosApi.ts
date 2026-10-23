/**
 * Cliente do módulo **Contactos das juntas de freguesia** (`/freguesias/contactos/*`).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type FreguesiaContacto = {
  doc_id?: string;
  municipio?: string | null;
  municipio_keyword?: string | null;
  freguesia: string;
  freguesia_keyword?: string | null;
  codigo_ine: string;
  nif?: string | null;
  nome_presidente?: string | null;
  nome_presidente_keyword?: string | null;
  morada?: string | null;
  codigo_postal?: string | null;
  localidade?: string | null;
  descricao_postal?: string | null;
  email?: string | null;
  telefone?: string | null;
  slug?: string | null;
  fonte?: string | null;
  ingested_at?: string | null;
  updated_at?: string | null;
};

export type FreguesiasContactosResponse = {
  total: number;
  page: number;
  size: number;
  items: FreguesiaContacto[];
  municipios?: { key: string; count: number }[];
  origem?: string;
  error?: string | null;
};

export type FreguesiasContactosStats = {
  index?: string;
  documents?: number;
  por_municipio?: { key: string; count: number }[];
  origem?: string;
  error?: string;
};

export type FreguesiaContactoFicha = FreguesiaContacto & {
  error?: string;
};

export type FreguesiasContactosRecolherResponse = {
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

export function getFreguesiasContactos(params?: {
  q?: string;
  municipio?: string;
  codigo_ine?: string;
  page?: number;
  size?: number;
}): Promise<FreguesiasContactosResponse> {
  return pedir<FreguesiasContactosResponse>(
    `/freguesias/contactos${queryString({ ...(params ?? {}) })}`,
  );
}

export function getFreguesiasContactosStats(): Promise<FreguesiasContactosStats> {
  return pedir<FreguesiasContactosStats>("/freguesias/contactos/stats");
}

export function getFreguesiaContacto(codigo_ine: string): Promise<FreguesiaContactoFicha> {
  return pedir<FreguesiaContactoFicha>(`/freguesias/contactos/${encodeURIComponent(codigo_ine)}`);
}

export function recolherFreguesiasContactos(forcar = false): Promise<FreguesiasContactosRecolherResponse> {
  return pedir(`/freguesias/contactos/recolher${queryString({ forcar })}`, { method: "POST" });
}

/* ------------------------------------------------------------------ formato */

export function telefoneFormatado(telefone?: string | null): string {
  if (!telefone) return "—";
  if (telefone.startsWith("+351") && telefone.length === 13) {
    const n = telefone.slice(4);
    return `+351 ${n.slice(0, 3)} ${n.slice(3, 6)} ${n.slice(6, 9)}`;
  }
  if (telefone.length === 9) {
    return `${telefone.slice(0, 3)} ${telefone.slice(3, 6)} ${telefone.slice(6, 9)}`;
  }
  return telefone;
}

export function moradaCompacta(morada?: string | null, localidade?: string | null, cp?: string | null): string {
  const partes = [morada, localidade ? `${cp ?? ""} ${localidade}`.trim() : cp].filter(Boolean);
  return partes.join(", ") || "—";
}
