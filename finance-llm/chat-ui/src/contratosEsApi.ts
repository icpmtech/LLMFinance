/**
 * Cliente da API dos contratos públicos de Espanha (PLACSP) — `/contracts-es/*`.
 *
 * O índice `contratos_es` é alimentado pelo pipeline `collectors/contratos_es.py`
 * a partir dos ZIPs/ATOM do portal de contratação espanhol (`contrataciondelestado.es`).
 */
import { API_BASE } from "./api";

/**
 * Pedido que outra aplicação do IQ OS (ex.: a Pesquisa total) deixa à app
 * «Contratos Espanha»: um contrato concreto (`doc`) ou uma pesquisa já focada
 * numa entidade — órgão adjudicante (`organo`), empresa adjudicatária
 * (`adjudicatario`) ou texto livre (`q`).
 */
export type ContratosEsEntry = {
  doc?: string;
  organo?: string;
  adjudicatario?: string;
  q?: string;
  /** Código NUTS (ex.: «ES300»), usado pelo mapa de contratos. */
  nuts?: string;
};

/** Chave de `localStorage` onde fica o pedido pendente. */
export const CONTRATOS_ES_OPEN_KEY = "finance-llm-contratos-es-entry";

/**
 * Evento disparado ao deixar um pedido, para a app o aplicar **sem remontar**
 * (caso já esteja aberta numa janela: a entrada é lida no arranque da página).
 */
export const CONTRATOS_ES_ENTRY_EVENT = "finance-llm-contratos-es-entry";

/** Deixa um pedido para a app de contratos de Espanha (lido no arranque). */
export function writeContratosEsEntry(entry: ContratosEsEntry): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CONTRATOS_ES_OPEN_KEY, JSON.stringify(entry));
  window.dispatchEvent(new Event(CONTRATOS_ES_ENTRY_EVENT));
}

/** Lê e limpa o pedido pendente (para não se repetir ao voltar à app). */
export function takeContratosEsEntry(): ContratosEsEntry | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(CONTRATOS_ES_OPEN_KEY);
  if (!raw) return null;
  window.localStorage.removeItem(CONTRATOS_ES_OPEN_KEY);
  try {
    const parsed = JSON.parse(raw) as ContratosEsEntry;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    // Formato antigo: a chave guardava apenas o `_id` do contrato.
    return { doc: raw };
  }
}


/** Valor de uma faceta (código ou rótulo, contagem e, no caso dos CPV, descrição). */
export type ContratoEsFacet = { value: string | number; count: number; label?: string };

/** Facetas devolvidas pela pesquisa (ano, tipo, órgão, CPV, …). */
export type ContratoEsFacets = Record<string, ContratoEsFacet[]>;

export type ContratoEsStats = {
  valor_adjudicado_sum?: number | null;
  valor_adjudicado_avg?: number | null;
  valor_adjudicado_docs?: number;
  valor_base_sum?: number | null;
  valor_base_docs?: number;
};

export type ContratoEsCpv = { code: string; nombre?: string };

/** Documento normalizado de um contrato de Espanha. */
export type ContratoEsItem = {
  doc_id?: string;
  fonte?: "licitaciones" | "menores" | string;
  pais?: string;
  ano?: number;
  ano_fonte?: number;
  id_expediente?: string;
  estado?: string;
  estado_label?: string;
  enlace?: string;
  organo_id?: string;
  organo_nombre?: string;
  organo_ciudad?: string;
  organo_cp?: string;
  organo_web?: string;
  organo_email?: string;
  organo_tipo?: string;
  tipo_contrato?: string;
  tipo_contrato_label?: string;
  subtipo_contrato?: string;
  objeto?: string;
  descripcion?: string;
  cpv?: ContratoEsCpv[];
  valor_estimado?: number;
  valor_presupuesto?: number;
  valor_base?: number;
  valor_adjudicado?: number;
  valor_adjudicado_con_iva?: number;
  moneda?: string;
  fecha_adjudicacion?: string;
  fecha_publicacion?: string;
  fecha_actualizacion?: string;
  fecha_limite?: string;
  hora_limite?: string;
  resultado?: string;
  resultado_label?: string;
  num_ofertas?: number;
  adjudicatario_nombre?: string;
  adjudicatario_nif?: string;
  adjudicatario_nuts?: string;
  adjudicatario_nacionalidad?: string;
  procedimiento?: string;
  procedimiento_label?: string;
  urgencia?: string;
  sistema_contratacion?: string;
  idioma?: string;
  localidad?: string;
  nuts?: string;
  duracion_valor?: number;
  duracion_unidad?: string;
  num_lotes?: number;
  documentos?: string[];
  es_menor?: boolean;
  score?: number;
};

/** Filtros aceitos pela pesquisa (`POST /contracts-es/search`). */
export type ContratoEsSearchRequest = {
  q?: string;
  ano?: number;
  fonte?: string;
  tipo?: string;
  estado?: string;
  procedimiento?: string;
  organo?: string;
  organismo_id?: string;
  adjudicatario?: string;
  adjudicatario_nif?: string;
  localidad?: string;
  nuts?: string;
  cpv_code?: string;
  min_value?: number;
  max_value?: number;
  start_date?: string;
  end_date?: string;
  date_field?: string;
  solo_menores?: boolean;
  size?: number;
  from?: number;
  sort_by?: string;
  sort_order?: string;
};

export type ContratoEsSearchResponse = {
  query?: string | null;
  total: number;
  items: ContratoEsItem[];
  facets?: ContratoEsFacets;
  stats?: ContratoEsStats;
  from?: number;
  size?: number;
  error?: string;
};

export type ContratoEsSuggestion = { text: string; type: string; count: number };

export type ContratoEsStatus = {
  available?: boolean;
  total: number;
  years: number[];
  years_detail?: { year: number; count: number }[];
  fontes?: { fonte: string; count: number }[];
  error?: string;
};

export type ContratoEsMeta = {
  zips: { fonte: string; ano: number; zip: string }[];
  normalized: { fonte: string; ano: number; jsonl: string }[];
  indexed_years: number[];
  fontes: string[];
  codigos: {
    tipo_contrato: Record<string, string>;
    estado: Record<string, string>;
    resultado: Record<string, string>;
    procedimiento: Record<string, string>;
  };
};

/** Linha analítica (anos, tipos, CPV, entidades…). */
export type ContratoEsAnalyticsRow = {
  key: string;
  count: number;
  total_value?: number | null;
  description?: string | null;
};

/** Resposta do endpoint analítico `/contracts-es/analytics`. */
export type ContratoEsAnalyticsResponse = {
  total_contracts: number;
  total_value?: number | null;
  avg_value?: number | null;
  max_value?: number | null;
  by_year: ContratoEsAnalyticsRow[];
  by_month: ContratoEsAnalyticsRow[];
  value_distribution: ContratoEsAnalyticsRow[];
  top_entities: ContratoEsAnalyticsRow[];
  top_cpv: ContratoEsAnalyticsRow[];
  procedure_types: ContratoEsAnalyticsRow[];
  contract_types: ContratoEsAnalyticsRow[];
  year?: number | null;
  error?: string;
};

/** Filtros aceites pelo endpoint `/contracts-es/analytics`. */
export type ContratoEsAnalyticsRequest = {
  q?: string;
  ano?: number;
  fonte?: string;
  tipo?: string;
  estado?: string;
  procedimiento?: string;
  organo?: string;
  organismo_id?: string;
  adjudicatario?: string;
  adjudicatario_nif?: string;
  localidad?: string;
  nuts?: string;
  cpv_code?: string;
  min_value?: number;
  max_value?: number;
  start_date?: string;
  end_date?: string;
  date_field?: string;
  solo_menores?: boolean;
};

/** Trabalho de importação (normalização + indexação) em segundo plano. */
export type ContratoEsImportJob = {
  id: string;
  fonte: string;
  ano: number;
  limit?: number | null;
  index?: boolean;
  state: "queued" | "running" | "done" | "error";
  stage?: string;
  docs?: number;
  indexed?: number;
  atoms_done?: number;
  atoms_total?: number;
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

/** Volumetria do índice `contratos_es`. */
export async function getContratosEsStatus(): Promise<ContratoEsStatus> {
  const res = await fetch(`${API_BASE}/contracts-es/status`);
  return readJson<ContratoEsStatus>(res, "Erro ao obter estado dos contratos de Espanha");
}

/** ZIPs disponíveis, JSONLs normalizados e listas de códigos CODICE. */
export async function getContratosEsMeta(): Promise<ContratoEsMeta> {
  const res = await fetch(`${API_BASE}/contracts-es/meta`);
  return readJson<ContratoEsMeta>(res, "Erro ao obter metadados dos contratos de Espanha");
}

/** Pesquisa contratos de Espanha (com facetas). */
export async function searchContratosEs(req: ContratoEsSearchRequest): Promise<ContratoEsSearchResponse> {
  const res = await fetch(`${API_BASE}/contracts-es/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return readJson<ContratoEsSearchResponse>(res, "Erro na pesquisa de contratos de Espanha");
}

/** Sugestões de órgãos, adjudicatários e CPV. */
export async function autocompleteContratosEs(q: string, size = 10): Promise<{ suggestions: ContratoEsSuggestion[] }> {
  const params = new URLSearchParams({ q, size: String(size) });
  const res = await fetch(`${API_BASE}/contracts-es/autocomplete?${params}`);
  return readJson<{ suggestions: ContratoEsSuggestion[] }>(res, "Erro no autocomplete");
}

/** Detalhe de um contrato pelo `_id` do documento. */
export async function getContratoEs(docId: string): Promise<ContratoEsItem> {
  const res = await fetch(`${API_BASE}/contracts-es/${encodeURIComponent(docId)}`);
  return readJson<ContratoEsItem>(res, "Erro ao obter contrato");
}

/** Arranca a importação de um ano (normaliza os ZIPs e indexa). Requer sessão. */
export async function importContratosEs(req: {
  fonte: string;
  ano: number;
  limit?: number;
  index?: boolean;
  force?: boolean;
}): Promise<ContratoEsImportJob> {
  const res = await fetch(`${API_BASE}/contracts-es/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return readJson<ContratoEsImportJob>(res, "Erro ao arrancar a importação");
}

/** Importações em curso e recentes. */
export async function getContratosEsImports(): Promise<{ jobs: ContratoEsImportJob[] }> {
  const res = await fetch(`${API_BASE}/contracts-es/imports`);
  return readJson<{ jobs: ContratoEsImportJob[] }>(res, "Erro ao obter importações");
}

/** Dashboard/analítica de contratos de Espanha. */
export async function getContratosEsAnalytics(req: ContratoEsAnalyticsRequest): Promise<ContratoEsAnalyticsResponse> {
  const params = new URLSearchParams();
  Object.entries(req).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    params.set(k, String(v));
  });
  const res = await fetch(`${API_BASE}/contracts-es/analytics?${params}`);
  return readJson<ContratoEsAnalyticsResponse>(res, "Erro na analítica de contratos de Espanha");
}
