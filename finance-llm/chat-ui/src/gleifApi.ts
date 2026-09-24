/**
 * Cliente do módulo **GLEIF / LEI** (`/gleif/*`).
 *
 * O GLEIF publica o *Golden Copy* dos registos LEI (Legal Entity Identifier):
 * quem é quem no sistema financeiro global — nome legal, endereço, jurisdição,
 * forma jurídica, estado e datas do registo, e identificadores associados
 * (BIC, MIC, OCID, QCC, S&P Global).
 *
 * Os dados vivem em dois sítios: a **golden copy local**
 * (`data/gleif/lei.jsonl`) e o índice Elasticsearch `finance_gleif_lei`.
 * A ingestão pode vir da API oficial do GLEIF (por país) ou dos ficheiros
 * Golden Copy (ZIP/CSV/XML do LEI-CDF) — ver `POST /gleif/ingest`.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Faceta (contagem por valor de um campo). */
export type GleifFacet = { key: string; count: number };

/** Cartão de resultado: os campos que a lista mostra. */
export type GleifLei = {
  lei: string;
  legal_name: string;
  other_names?: string[];
  transliterated_names?: string[];
  country?: string | null;
  region?: string | null;
  region_name?: string | null;
  city?: string | null;
  address_lines?: string[];
  postal_code?: string | null;
  hq_city?: string | null;
  hq_region?: string | null;
  hq_country?: string | null;
  status?: string | null;
  registration_status?: string | null;
  category?: string | null;
  legal_form?: string | null;
  legal_form_other?: string | null;
  jurisdiction?: string | null;
  managing_lou?: string | null;
  corroboration_level?: string | null;
  conformity_flag?: string | null;
  registered_as?: string | null;
  registered_at?: string | null;
  validated_as?: string | null;
  initial_registration_date?: string | null;
  last_update_date?: string | null;
  next_renewal_date?: string | null;
  creation_date?: string | null;
  bic?: string | null;
  mic?: string | null;
  ocid?: string | null;
  qcc?: string | null;
  gem?: string | null;
  spglobal?: string | null;
  source?: string | null;
  ingested_at?: string | null;
};

export type GleifSearchParams = {
  q?: string;
  country?: string;
  region?: string;
  status?: string;
  category?: string;
  legal_form?: string;
  verification?: string;
  lou?: string;
  city?: string;
  sort?: "relevance" | "name" | "updated" | "registered";
  size?: number;
  from?: number;
};

export type GleifSearchResult = {
  query?: string | null;
  total: number;
  from: number;
  size: number;
  items: GleifLei[];
  facets: Record<string, GleifFacet[]>;
  facet_labels?: Record<string, string>;
  took_ms?: number;
};

export type GleifSuggestion = {
  lei: string;
  name: string;
  label: string;
  country?: string | null;
  city?: string | null;
  status?: string | null;
};

export type GleifMapRegion = {
  key: string;
  label: string;
  count: number;
  active?: number;
  cities?: number;
  last_update?: string | null;
  /** Nível `grid`: coordenadas do centro da célula e cidade dominante. */
  city?: string | null;
  lat?: number;
  lon?: number;
};

export type GleifMapLevel = "country" | "region" | "grid";

export type GleifMapResult = {
  level: GleifMapLevel;
  metric: string;
  field: string;
  /** Nível `grid`: precisão da célula geohash. */
  precision?: number;
  regions: GleifMapRegion[];
  index_total: number;
  returned_total: number;
  /** Registos sem valor no campo agregado (ex.: sem região ou sem ponto). */
  missing?: number;
  missing_label?: string;
  /** Registos que correspondem aos filtros ativos. */
  matched?: number;
  took_ms?: number;
};

export type GleifJob = {
  id: string;
  status: "running" | "done" | "error";
  source?: string;
  countries?: string[];
  phase?: string;
  note?: string;
  total?: number;
  records?: number;
  indexed?: number;
  errors?: number;
  truncated?: boolean;
  error?: string;
  duration_s?: number;
  started_at?: string;
  finished_at?: string;
};

export type GleifStatus = {
  index: string;
  file: { path: string; exists: boolean; records: number; bytes: number; modified?: string | null };
  golden_copy_files: { name: string; path: string; bytes: number; modified: string }[];
  facets?: Record<string, GleifFacet[]>;
  timeline?: { year: string; count: number }[];
  meta?: {
    last_run?: Record<string, unknown> | null;
    history?: Record<string, unknown>[];
    golden_copy?: { path?: string; at?: string } | null;
  };
  elasticsearch: { available: boolean; count?: number; error?: string };
  error?: string;
};

export type GleifMeta = {
  module: string;
  label: string;
  index: string;
  file: string;
  golden_copy_dir: string;
  sources: { id: string; label: string }[];
  levels: { id: string; label: string }[];
  default_countries: string[];
  facets: { id: string; label: string; field: string }[];
  pt_regions: Record<string, string>;
  last_run?: Record<string, unknown> | null;
  countries: string[];
};

export type GleifIngestRequest = {
  source: "api" | "file" | "golden-copy" | "golden-copy-download";
  countries?: string[];
  path?: string;
  limit?: number;
  replace?: boolean;
  download?: boolean;
  wait?: boolean;
};

/* -------------------------------------------------------------- utilidades */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = (body && (body.detail || body.error)) || detail;
    } catch {
      /* corpo não-JSON: fica o código */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/* ------------------------------------------------------------------- API */

/** Metadados do módulo (índice, ficheiro, origens, facetas). */
export function getGleifMeta(): Promise<GleifMeta> {
  return request<GleifMeta>("/gleif/meta");
}

/** Estado do índice e da golden copy local (volumetria e distribuições). */
export function getGleifStatus(refresh = false): Promise<GleifStatus> {
  return request<GleifStatus>(`/gleif/status${refresh ? "?refresh=true" : ""}`);
}

/** Pesquisa registos LEI (nome, LEI, NIF de registo, BIC, cidade) com filtros. */
export function searchGleif(params: GleifSearchParams): Promise<GleifSearchResult> {
  return request<GleifSearchResult>(
    `/gleif/search${queryString({
      q: params.q,
      country: params.country,
      region: params.region,
      status: params.status,
      category: params.category,
      legal_form: params.legal_form,
      verification: params.verification,
      lou: params.lou,
      city: params.city,
      sort: params.sort,
      size: params.size,
      from: params.from,
    })}`,
  );
}

/** Sugestões para a caixa de pesquisa (nome, LEI, país e cidade). */
export function suggestGleif(q: string, size = 8): Promise<{ query: string; suggestions: GleifSuggestion[] }> {
  return request(`/gleif/suggest${queryString({ q, size })}`);
}

/** Ficha completa de um LEI. */
export function getGleifRecord(lei: string): Promise<GleifLei> {
  return request<GleifLei>(`/gleif/records/${encodeURIComponent(lei)}`);
}

/** Agregado por país/região — a base do mapa OpenStreetMap. */
export function getGleifMap(params: {
  level?: GleifMapLevel;
  metric?: string;
  country?: string;
  region?: string;
  status?: string;
  category?: string;
  /** Nível `grid`: precisão da célula geohash (6 ≈ 1,2 km). */
  precision?: number;
  size?: number;
}): Promise<GleifMapResult> {
  return request<GleifMapResult>(`/gleif/map${queryString({ ...params })}`);
}

/** Ingestões em curso e recentes. */
export function getGleifJobs(): Promise<{ jobs: GleifJob[] }> {
  return request<{ jobs: GleifJob[] }>("/gleif/jobs");
}

/** Estado de uma ingestão. */
export function getGleifJob(jobId: string): Promise<GleifJob> {
  return request<GleifJob>(`/gleif/jobs/${encodeURIComponent(jobId)}`);
}

/** Arranca uma ingestão (devolve um `job_id` quando corre em segundo plano). */
export function startGleifIngest(req: GleifIngestRequest): Promise<{ job_id?: string; status?: string } & Partial<GleifJob>> {
  return request("/gleif/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(req),
  });
}

/** Esvazia o índice de registos LEI. */
export function deleteGleifIndex(): Promise<{ deleted?: boolean; error?: string }> {
  return request("/gleif/index", { method: "DELETE", credentials: "include" });
}

/** Endereço de exportação da golden copy local em CSV. */
export function gleifExportUrl(limit = 5000): string {
  return `${API_BASE}/gleif/export.csv?limit=${limit}`;
}

/* ------------------------------------------------------------- etiquetas */

/** Rótulos das facetas devolvidos pelo backend (fallback local). */
export const FACET_LABELS: Record<string, string> = {
  country: "País da sede",
  region: "Região",
  status: "Estado",
  category: "Categoria",
  legal_form: "Forma jurídica",
  verification: "Corroboração",
  lou: "LOU emissor",
};

/** Tradução legível do estado do registo/entidade do GLEIF. */
export const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Ativa",
  INACTIVE: "Inativa",
  ISSUED: "Emitido",
  LAPSED: "Caducado",
  RETIRED: "Retirado",
  ANNULLED: "Anulado",
  MERGED: "Fundido",
  PENDING_ARCHIVAL: "Pendente de arquivo",
  PENDING_TRANSFER: "Pendente de transferência",
  PENDING: "Pendente",
};

/** Tradução legível da categoria de entidade. */
export const CATEGORY_LABELS: Record<string, string> = {
  GENERAL: "Empresa/genérico",
  BRANCH: "Sucursal",
  FUND: "Fundo",
  SOLE_PROPRIETOR: "Empresário individual",
  RESERVED: "Reservado",
  INTERNATIONAL_ORGANIZATION: "Organização internacional",
};

/** Tradução legível do nível de corroboração. */
export const CORROBORATION_LABELS: Record<string, string> = {
  FULLY_CORROBORATED: "Totalmente corroborado",
  PARTIALLY_CORROBORATED: "Parcialmente corroborado",
  ENTITY_SUPPLIED_ONLY: "Fornecido pela entidade",
};

/** Tradução legível da origem dos dados. */
export const SOURCE_LABELS: Record<string, string> = {
  api: "API oficial do GLEIF",
  "golden-copy": "Ficheiro Golden Copy",
  "golden-copy-download": "Golden Copy descarregado",
  file: "Golden copy local",
};

/** Estados de registo que a UI pinta a verde («válido»). */
export const ACTIVE_STATUSES = new Set(["ACTIVE", "ISSUED"]);

export function statusLabel(value?: string | null): string {
  if (!value) return "—";
  return STATUS_LABELS[value] || value;
}

export function categoryLabel(value?: string | null): string {
  if (!value) return "—";
  return CATEGORY_LABELS[value] || value;
}

export function corroborationLabel(value?: string | null): string {
  if (!value) return "—";
  return CORROBORATION_LABELS[value] || value;
}

/** Rótulo legível da origem dos dados de um documento/tarefa. */
export function sourceLabel(value?: string | null): string {
  if (!value) return "—";
  return SOURCE_LABELS[value] || value;
}

/** Data ISO em formato curto (`2026-09-23`). */
export function shortDate(value?: string | null): string {
  if (!value) return "—";
  return String(value).slice(0, 10);
}
