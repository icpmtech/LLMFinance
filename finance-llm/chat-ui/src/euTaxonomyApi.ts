/**
 * Cliente da API do módulo **EU Taxonomy Navigator** — `/eu-taxonomy/*`.
 *
 * Leitura aberta: panorama, pesquisa e ficha de atividade.
 * Escrita (recolha/tradução): requer sessão, como nos restantes módulos.
 */
import { API_BASE } from "./api";

function query(params: Record<string, unknown>) {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return `?${entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&")}`;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Erro ${res.status}`);
  }
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Erro ${res.status}`);
  }
  return res.json();
}

export type EuTaxonomySource = {
  id: string;
  label: string;
  url: string;
  api: string;
  synced_at: string;
  aviso: string;
};

export type EuTaxonomyObjective = {
  objective_id: number;
  objective_name_en: string;
  objective_name_pt: string;
  objective_short_en: string;
  objective_short_pt: string;
  contribution_type_en: string;
  contribution_type_pt: string;
};

export type EuTaxonomyActivity = {
  kind: "activity";
  activity_id: number;
  name_en: string;
  name_pt: string | null;
  sector_id: number;
  sector_en: string;
  sector_pt: string;
  description_en: string;
  description_pt: string | null;
  nace_codes: string[];
  objectives: EuTaxonomyObjective[];
  url: string;
  synced_at: string;
};

export type EuTaxonomySectorCount = {
  sector_en: string;
  sector_pt: string;
  count: number;
};

export type EuTaxonomyPanorama = {
  source: EuTaxonomySource;
  totals: { activities: number; objectives: number; sectors: number };
  objectives: {
    id: number;
    name_en: string;
    name_pt: string;
    short_en: string;
    short_pt: string;
    color: string;
  }[];
  sectors: EuTaxonomySectorCount[];
};

export type EuTaxonomySearchResponse = {
  total: number;
  items: (EuTaxonomyActivity | Record<string, unknown>)[];
  facets: {
    kinds: { key: string; count: number }[];
    sectors: { key: string; count: number }[];
    objectives: { id: number; count: number }[];
  };
};

export async function getEuTaxonomyStatus() {
  return getJson<{ index: string; snapshot_exists: boolean; es_available: boolean; count?: number; error?: string }>(
    "/eu-taxonomy/status",
  );
}

export async function getEuTaxonomyPanorama() {
  return getJson<EuTaxonomyPanorama>("/eu-taxonomy/panorama");
}

export async function searchEuTaxonomy(params: {
  q?: string;
  kind?: "activity" | "objective" | "sector";
  sector?: string;
  objective_id?: number;
  nace?: string;
  size?: number;
  from?: number;
  sort?: "relevance" | "name" | "sector";
}) {
  return getJson<EuTaxonomySearchResponse>(`/eu-taxonomy/pesquisa${query(params)}`);
}

export async function getEuTaxonomyActivity(activityId: number) {
  return getJson<EuTaxonomyActivity>(`/eu-taxonomy/atividade/${activityId}`);
}

export async function coletarEuTaxonomy(payload: { force?: boolean; translate?: boolean } = {}) {
  return postJson<{
    run_id?: string;
    snapshot_path?: string;
    source?: EuTaxonomySource;
    totals?: Record<string, number>;
    index?: { indexed_count: number; error_count: number; error?: string };
    translated_names?: number;
    translated_descriptions?: number;
    error?: string;
  }>("/eu-taxonomy/coletar", { force: false, translate: true, ...payload });
}

export type EuTaxonomyTraducaoEstado = {
  estado: "nunca_correu" | "a_correr" | "concluido" | "erro" | string;
  done: number;
  total: number;
  percent: number;
  started_at?: string;
  finished_at?: string | null;
  translated_names?: number;
  translated_descriptions?: number;
  indexed_count?: number;
  erro?: string;
  ja_em_curso?: boolean;
  error?: string;
};

export async function traduzirEuTaxonomy() {
  return postJson<EuTaxonomyTraducaoEstado>("/eu-taxonomy/traduzir", {});
}

export async function getEuTaxonomyTraducaoEstado() {
  return getJson<EuTaxonomyTraducaoEstado>("/eu-taxonomy/traducao/estado");
}
