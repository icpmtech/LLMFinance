/**
 * Cliente da API dos contratos públicos de França (DECP) — `/contracts-fr/*`.
 *
 * O índice `contratos_fr` é alimentado pelo pipeline `collectors/contratos_fr.py`
 * a partir dos ficheiros JSON do DECP em `data/contratos-franca/decp-*.json`.
 */
import { API_BASE } from "./api";

/**
 * Pedido que outra aplicação do IQ OS deixa à app «Contratos França»:
 * um contrato concreto (`doc`), um acheteur, um adjudicatário ou texto livre.
 */
export type ContratosFrEntry = {
  doc?: string;
  acheteur?: string;
  adjudicatario?: string;
  q?: string;
  /** Filtro de local de execução (usado pela vista de mapa para abrir a lista). */
  lieu_execution_code?: string;
  lieu_execution_type?: string;
};

/** Chave de `localStorage` onde fica o pedido pendente. */
export const CONTRATOS_FR_OPEN_KEY = "finance-llm-contratos-fr-entry";

/**
 * Evento disparado ao deixar um pedido, para a app o aplicar **sem remontar**.
 */
export const CONTRATOS_FR_ENTRY_EVENT = "finance-llm-contratos-fr-entry";

/** Deixa um pedido para a app de contratos de França. */
export function writeContratosFrEntry(entry: ContratosFrEntry): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CONTRATOS_FR_OPEN_KEY, JSON.stringify(entry));
  window.dispatchEvent(new Event(CONTRATOS_FR_ENTRY_EVENT));
}

/** Lê e limpa o pedido pendente. */
export function takeContratosFrEntry(): ContratosFrEntry | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(CONTRATOS_FR_OPEN_KEY);
  if (!raw) return null;
  window.localStorage.removeItem(CONTRATOS_FR_OPEN_KEY);
  try {
    const parsed = JSON.parse(raw) as ContratosFrEntry;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return { doc: raw };
  }
}

export type ContratoFrFacet = { value: string | number; count: number; label?: string };
export type ContratoFrFacets = Record<string, ContratoFrFacet[]>;

export type ContratoFrStats = {
  valor_sum?: number | null;
  valor_avg?: number | null;
  valor_docs?: number;
  valor_estime_sum?: number | null;
  valor_estime_docs?: number;
};

export type ContratoFrCpv = { code: string; nom?: string };
export type ContratoFrTitulaire = { type_identifiant?: string; id?: string; nom?: string };

/** Documento normalizado de um contrato de França. */
export type ContratoFrItem = {
  doc_id?: string;
  pais?: string;
  fonte?: string;
  filename?: string;
  id?: string;
  nature?: string;
  objet?: string;
  code_cpv?: string;
  cpv?: ContratoFrCpv[];
  procedure?: string;
  ccag?: string;
  offres_recues?: number;
  type_groupement?: string;
  lieu_execution_code?: string;
  lieu_execution_type?: string;
  lieu_execution_nom?: string;
  duree_mois?: number;
  date_notification?: string;
  date_notification_raw?: string;
  date_publication?: string;
  date_publication_raw?: string;
  montant?: number;
  montant_estime?: number;
  valor?: number;
  forme_prix?: string;
  acheteur_id?: string;
  acheteur_nom?: string;
  adjudicatario_id?: string;
  adjudicatario_type_identifiant?: string;
  adjudicatario_nom?: string;
  uid?: string;
  titulaires?: ContratoFrTitulaire[];
  considerations_sociales?: string[];
  considerations_environnementales?: string[];
  modalites_execution?: string[];
  techniques?: string[];
  types_prix?: string[];
  source?: string;
  taux_avance?: number;
  origine_ue?: number;
  origine_france?: number;
  marche_innovant?: boolean;
  attribution_avance?: boolean;
  sous_traitance_declaree?: boolean;
  ano?: number;
  score?: number;
};

export type ContratoFrSearchRequest = {
  q?: string;
  ano?: number;
  nature?: string;
  procedure?: string;
  acheteur?: string;
  acheteur_id?: string;
  adjudicatario?: string;
  adjudicatario_id?: string;
  cpv_code?: string;
  lieu_execution_code?: string;
  lieu_execution_type?: string;
  min_value?: number;
  max_value?: number;
  start_date?: string;
  end_date?: string;
  date_field?: string;
  size?: number;
  from?: number;
  sort_by?: string;
  sort_order?: string;
  with_facets?: boolean;
};

export type ContratoFrSearchResponse = {
  query?: string | null;
  total: number;
  items: ContratoFrItem[];
  facets?: ContratoFrFacets;
  stats?: ContratoFrStats;
  from?: number;
  size?: number;
  error?: string;
};

export type ContratoFrSuggestion = { text: string; type: string; count: number };

export type ContratoFrStatus = {
  available?: boolean;
  total: number;
  years: number[];
  years_detail?: { year: number; count: number }[];
  natures?: { nature: string; count: number }[];
  error?: string;
};

export type ContratoFrMeta = {
  sources: { filename: string; ano: number | null; mes: number | null; size_mb: number; processed: boolean }[];
  indexed_years: number[];
  processed_dir: string;
};

export type ContratoFrAnalyticsRow = {
  key: string;
  count: number;
  total_value?: number | null;
  description?: string | null;
};

export type ContratoFrAnalyticsResponse = {
  total_contracts: number;
  total_value?: number | null;
  avg_value?: number | null;
  max_value?: number | null;
  by_year: ContratoFrAnalyticsRow[];
  by_month: ContratoFrAnalyticsRow[];
  value_distribution: ContratoFrAnalyticsRow[];
  top_entities: ContratoFrAnalyticsRow[];
  top_cpv: ContratoFrAnalyticsRow[];
  procedures: ContratoFrAnalyticsRow[];
  formes_prix: ContratoFrAnalyticsRow[];
  localizacao?: { types: ContratoFrAnalyticsRow[]; codes: ContratoFrAnalyticsRow[] } | null;
  year?: number | null;
  error?: string;
};

export type ContratoFrAnalyticsRequest = {
  q?: string;
  ano?: number;
  nature?: string;
  procedure?: string;
  acheteur?: string;
  acheteur_id?: string;
  adjudicatario?: string;
  adjudicatario_id?: string;
  cpv_code?: string;
  lieu_execution_code?: string;
  lieu_execution_type?: string;
  min_value?: number;
  max_value?: number;
  start_date?: string;
  end_date?: string;
  date_field?: string;
};

export type ContratoFrImportJob = {
  id: string;
  filename?: string;
  limit?: number | null;
  index?: boolean;
  force?: boolean;
  state: "queued" | "running" | "done" | "error";
  stage?: string;
  docs?: number;
  indexed?: number;
  errors?: number;
  message?: string;
  finished?: boolean;
  created_at?: string;
  updated_at?: string;
};

async function readJson<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? ` — ${body.detail}` : "";
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(`${label}: ${res.status}${detail}`);
  }
  return res.json() as Promise<T>;
}

/** Volumetria do índice `contratos_fr`. */
export async function getContratosFrStatus(): Promise<ContratoFrStatus> {
  const res = await fetch(`${API_BASE}/contracts-fr/status`);
  return readJson<ContratoFrStatus>(res, "Erro ao obter estado dos contratos de França");
}

/** Ficheiros DECP disponíveis e JSONLs normalizados. */
export async function getContratosFrMeta(): Promise<ContratoFrMeta> {
  const res = await fetch(`${API_BASE}/contracts-fr/meta`);
  return readJson<ContratoFrMeta>(res, "Erro ao obter metadados dos contratos de França");
}

/** Pesquisa contratos de França (com facetas). */
export async function searchContratosFr(req: ContratoFrSearchRequest): Promise<ContratoFrSearchResponse> {
  const res = await fetch(`${API_BASE}/contracts-fr/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return readJson<ContratoFrSearchResponse>(res, "Erro na pesquisa de contratos de França");
}

/* --------------------------------------------------------------- mapa (OSM) */

export type ContratoFrMapRegion = {
  code: string;
  label: string;
  /** `departamento` | `regiao` | `pais` (ausente em entradas sem posição). */
  level?: string;
  /** Como a posição foi obtida: `centroide`, `prefeitura`, `grupo-postal`, … */
  precision?: string;
  lat?: number;
  lon?: number;
  offshore?: boolean;
  contracts: number;
  value: number;
  kind?: string;
};

export type ContratoFrMapResponse = {
  total: number;
  /** Soma de `montant` (com queda para `montant_estime`) do conjunto filtrado. */
  value: number;
  value_docs: number;
  /** Contratos com valor indicativo do DECP (≥ 1 000 G€) que dominam a soma. */
  value_outliers: { contracts: number; value: number };
  regions: ContratoFrMapRegion[];
  offshore: ContratoFrMapRegion[];
  countries: ContratoFrMapRegion[];
  not_plotted: ContratoFrMapRegion[];
  levels: Record<string, number>;
  warnings: string[];
  error?: string;
};

export type ContratoFrMapFilters = {
  q?: string;
  ano?: number;
  nature?: string;
  procedure?: string;
  acheteur?: string;
  adjudicatario?: string;
  cpv_code?: string;
  lieu_execution_code?: string;
  lieu_execution_type?: string;
  min_value?: number;
  max_value?: number;
  start_date?: string;
  end_date?: string;
  date_field?: string;
};

/** Contratos agregados por local de execução (departamento/região), para o mapa. */
export async function getContratosFrMap(filters: ContratoFrMapFilters = {}): Promise<ContratoFrMapResponse> {
  const params = new URLSearchParams();
  for (const [chave, valor] of Object.entries(filters)) {
    if (valor === undefined || valor === null || valor === "") continue;
    params.set(chave, String(valor));
  }
  const query = params.toString();
  const res = await fetch(`${API_BASE}/contracts-fr/map${query ? `?${query}` : ""}`);
  return readJson<ContratoFrMapResponse>(res, "Erro no mapa dos contratos de França");
}

/* ------------------------------------------------------- tradução (IA, FR→PT) */

export type ContratoFrTranslationResponse = {
  /** Mapa texto original → tradução (só o que foi traduzido com sucesso). */
  translations: Record<string, string>;
  requested: number;
  cached: number;
  translated: number;
  failed: number;
  ai?: { provider?: string; provider_label?: string; model?: string };
  status?: { cached: number; path: string };
  error?: string;
};

/**
 * Traduz textos de contratos de França (FR→PT) com o fornecedor de IA da
 * plataforma. O mesmo texto só é traduzido uma vez (cache no servidor).
 */
export async function translateContratosFr(texts: string[], options: { provider?: string; model?: string } = {}): Promise<ContratoFrTranslationResponse> {
  const res = await fetch(`${API_BASE}/contracts-fr/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts, ...options }),
  });
  return readJson<ContratoFrTranslationResponse>(res, "Erro na tradução dos contratos de França");
}

/** Sugestões de acheteurs, adjudicatários e CPV. */
export async function autocompleteContratosFr(q: string, size = 10): Promise<{ suggestions: ContratoFrSuggestion[] }> {
  const params = new URLSearchParams({ q, size: String(size) });
  const res = await fetch(`${API_BASE}/contracts-fr/autocomplete?${params}`);
  return readJson<{ suggestions: ContratoFrSuggestion[] }>(res, "Erro no autocomplete");
}

/** Entidades de França (acheteurs e titulaires). */
export async function getContratosFrEntities(
  q = "",
  kind: "acheteur" | "adjudicatario" | "all" = "all",
  ano?: number,
  size = 20,
  from = 0
): Promise<{ total: number; items: any[]; query?: string | null; kind?: string | null }> {
  const params = new URLSearchParams({ q, kind, size: String(size), from: String(from) });
  if (ano !== undefined) params.set("ano", String(ano));
  const res = await fetch(`${API_BASE}/contracts-fr/entities?${params}`);
  return readJson(res, "Erro ao obter entidades");
}

/** Detalhe de um contrato pelo `_id`. */
export async function getContratoFr(docId: string): Promise<ContratoFrItem> {
  const res = await fetch(`${API_BASE}/contracts-fr/${encodeURIComponent(docId)}`);
  return readJson<ContratoFrItem>(res, "Erro ao obter contrato");
}

/** Arranca a importação de um ficheiro DECP. Requer sessão. */
export async function importContratosFr(req: {
  filename?: string;
  limit?: number;
  index?: boolean;
  force?: boolean;
}): Promise<ContratoFrImportJob> {
  const res = await fetch(`${API_BASE}/contracts-fr/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return readJson<ContratoFrImportJob>(res, "Erro ao arrancar a importação");
}

/** Importações em curso e recentes. */
export async function getContratosFrImports(): Promise<{ jobs: ContratoFrImportJob[] }> {
  const res = await fetch(`${API_BASE}/contracts-fr/imports`);
  return readJson<{ jobs: ContratoFrImportJob[] }>(res, "Erro ao obter importações");
}

/** Dashboard/analítica de contratos de França. */
export async function getContratosFrAnalytics(req: ContratoFrAnalyticsRequest): Promise<ContratoFrAnalyticsResponse> {
  const params = new URLSearchParams();
  Object.entries(req).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    params.set(k, String(v));
  });
  const res = await fetch(`${API_BASE}/contracts-fr/analytics?${params}`);
  return readJson<ContratoFrAnalyticsResponse>(res, "Erro na analítica de contratos de França");
}
