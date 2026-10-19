/**
 * Cliente do diretório de empresas da RigorBiz (`/rigorbiz/*`).
 *
 * O diretório é alimentado pela recolha do site `rigorbiz.pt` para
 * `data/rigorbiz` e indexado em `finance_rigorbiz`. Cada empresa traz
 * nome, NIF, CAE, descrição da atividade e localização.
 */
import { API_BASE } from "./api";

export type RigorbizCompany = {
  name?: string;
  nif?: string;
  cae_code?: string;
  cae_description?: string;
  location?: string;
  path?: string;
  source?: string;
  source_url?: string;
  collected_at?: string;
};

export type RigorbizSearchResult = {
  total: number;
  items: RigorbizCompany[];
  offset: number;
  size: number;
  source?: string;
  index?: string | null;
  error?: string;
};

export type RigorbizMeta = {
  local_count: number;
  jsonl: string;
  json: string;
  elasticsearch_available: boolean;
  elasticsearch_count: number;
  index: string;
};

export type RigorbizQuery = {
  q?: string;
  cae?: string;
  location?: string;
  sort?: string;
  size?: number;
  offset?: number;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
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

export function getRigorbizMeta() {
  return request<RigorbizMeta>("/rigorbiz/meta");
}

export function searchRigorbizCompanies(query: RigorbizQuery = {}) {
  const params = new URLSearchParams();
  const put = (name: string, value: string | number | undefined) => {
    if (value === undefined || value === null || value === "") return;
    params.set(name, String(value));
  };
  put("q", query.q?.trim());
  put("cae", query.cae);
  put("location", query.location);
  put("sort", query.sort);
  put("size", query.size);
  put("offset", query.offset);
  const suffix = params.toString();
  return request<RigorbizSearchResult>(`/rigorbiz/search${suffix ? `?${suffix}` : ""}`);
}

export function getRigorbizCompany(nif: string) {
  return request<RigorbizCompany>(`/rigorbiz/${encodeURIComponent(nif)}`);
}
