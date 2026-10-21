/**
 * Cliente do módulo **Contactos das câmaras municipais** (`/municipios/contactos/*`).
 *
 * A fonte é o Excel `contactos presidente CM 04092026.xlsx`, normalizado e
 * indexado no Elasticsearch. A pesquisa é do tipo Google: procura por município,
 * presidente, e-mail, morada, telefone ou código INE.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type MunicipioContacto = {
  doc_id?: string;
  distrito?: string | null;
  distrito_keyword?: string | null;
  municipio: string;
  municipio_keyword?: string | null;
  codigo_ine: string;
  nif?: string | null;
  nome_presidente?: string | null;
  nome_presidente_keyword?: string | null;
  morada?: string | null;
  codigo_postal?: string | null;
  localidade?: string | null;
  email?: string | null;
  telefone?: string | null;
  site?: string | null;
  site_domain?: string | null;
  slug?: string | null;
  fonte?: string | null;
  ingested_at?: string | null;
  updated_at?: string | null;
};

export type MunicipiosContactosResponse = {
  total: number;
  page: number;
  size: number;
  items: MunicipioContacto[];
  distritos?: { key: string; count: number }[];
  origem?: string;
  error?: string | null;
};

export type MunicipiosContactosStats = {
  index?: string;
  documents?: number;
  por_distrito?: { key: string; count: number }[];
  origem?: string;
  error?: string;
};

export type MunicipioContactoFicha = MunicipioContacto & {
  error?: string;
};

export type MunicipiosContactosRecolherResponse = {
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

export function getMunicipiosContactos(params?: {
  q?: string;
  distrito?: string;
  codigo_ine?: string;
  page?: number;
  size?: number;
}): Promise<MunicipiosContactosResponse> {
  return pedir<MunicipiosContactosResponse>(
    `/municipios/contactos${queryString({ ...(params ?? {}) })}`,
  );
}

export function getMunicipiosContactosStats(): Promise<MunicipiosContactosStats> {
  return pedir<MunicipiosContactosStats>("/municipios/contactos/stats");
}

export function getMunicipioContacto(codigo_ine: string): Promise<MunicipioContactoFicha> {
  return pedir<MunicipioContactoFicha>(`/municipios/contactos/${encodeURIComponent(codigo_ine)}`);
}

export function recolherMunicipiosContactos(forcar = false): Promise<MunicipiosContactosRecolherResponse> {
  return pedir(`/municipios/contactos/recolher${queryString({ forcar })}`, { method: "POST" });
}

/* ------------------------------------------------------------------ formato */

export function telefoneFormatado(telefone?: string | null): string {
  if (!telefone) return "—";
  // Nacional português: 9 dígitos → 3-3-3
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
