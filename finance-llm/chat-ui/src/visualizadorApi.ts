/**
 * Cliente do módulo **Visualizador** (`/visualizador/*`).
 *
 * O Visualizador é a camada de BI: cada tipo da Ontologia é um *dataset* com
 * dimensões, medidas e filtros declarados; o backend agrega no Elasticsearch (ou
 * em memória, nos datasets locais) e devolve linhas prontas a desenhar.
 *
 * O tipo de gráfico, as fórmulas e a disposição vivem no cliente — o backend só
 * responde a "dimensões × medidas".
 */
import { API_BASE } from "./api";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------
export type VisualMeasureKind =
  | "contagem"
  | "soma"
  | "media"
  | "minimo"
  | "maximo"
  | "distintos"
  | "mediana"
  | "p90";

export type VisualDimension = {
  id: string;
  label: string;
  type: "keyword" | "enum" | "number" | "date" | "boolean" | "text";
  field: string;
  nested?: string | null;
  unit?: string | null;
  enum?: string[] | null;
  values_from?: string | null;
  sortable?: boolean;
  searchable?: boolean;
  filterable?: boolean;
  pk?: boolean;
  groupable?: boolean;
  primary?: boolean;
  from?: string;
  /** Intervalo em dimensões de data (`dia` | `semana` | `mes` | `trimestre` | `ano`). */
  interval?: string;
};

export type VisualMeasure = {
  id: string;
  label?: string;
  kind: VisualMeasureKind;
  field?: string | null;
  nested?: string | null;
  unit?: string | null;
  format?: string | null;
  prop?: string | null;
  source?: string;
};

export type VisualFormula = {
  id: string;
  label: string;
  expression: string;
  format?: string;
  unit?: string | null;
};

export type VisualSuggestion = {
  title: string;
  dimension: string;
  dimension_label?: string;
  interval?: string | null;
  measure: string;
  measure_label?: string;
  chart: string;
};

export type DatasetSummary = {
  id: string;
  label: string;
  description?: string | null;
  domain?: string | null;
  icon?: string | null;
  kind: "es" | "aggregation" | "derived" | "local";
  index?: string | null;
  requires_session?: boolean;
  aggregation: boolean;
  records: boolean;
  dimensions: number;
  measures: number;
  available: boolean;
  note?: string | null;
  suggestions: VisualSuggestion[];
  defaults: {
    dimension?: string | null;
    dimension_interval?: string | null;
    measure?: string | null;
    table_dimension?: string | null;
    limit?: number;
  };
  source?: string;
  notes?: string[];
};

export type VisualDomain = {
  id: string;
  label: string;
  description?: string;
  accent?: string;
  datasets: string[];
};

export type ChartTypeInfo = {
  id: string;
  label: string;
  dimensions: number;
  time?: boolean;
  measures?: number;
};

export type VisualizadorMeta = {
  datasets: DatasetSummary[];
  domains: VisualDomain[];
  measure_kinds: { id: VisualMeasureKind; label: string; needs_field: boolean; additive: boolean }[];
  intervals: { id: string; label: string }[];
  chart_types: ChartTypeInfo[];
  limits: {
    max_dimensions: number;
    max_measures: number;
    max_formulas: number;
    max_rows: number;
    default_limit: number;
    notes: string[];
  };
  ontology: string;
  generated_at: string;
};

export type DatasetDetail = {
  dataset: DatasetSummary;
  dimensions: VisualDimension[];
  measures: VisualMeasure[];
  filters: VisualDimension[];
  defaults: DatasetSummary["defaults"];
  suggestions: VisualSuggestion[];
  count_field?: string | null;
  source?: string;
};

export type VisualDimensionSpec = string | { id: string; interval?: string };

export type VisualMeasureSpec =
  | string
  | { id?: string; kind?: VisualMeasureKind; field?: string; label?: string; format?: string };

export type VisualQueryRequest = {
  dataset: string;
  dimensions?: VisualDimensionSpec[];
  measures?: VisualMeasureSpec[];
  formulas?: VisualFormula[];
  filters?: Record<string, unknown>;
  search?: string | null;
  sort?: { by?: string; order?: "asc" | "desc" };
  limit?: number;
  inner_limit?: number;
  top_n?: number | null;
  others?: boolean;
  missing_label?: string | null;
};

export type QueryColumn = {
  key: string;
  label: string;
  type: "dimension" | "measure" | "formula";
  data_type?: string;
  unit?: string | null;
  format?: string | null;
  measure_kind?: VisualMeasureKind;
  expression?: string;
  interval?: string | null;
};

export type QueryRow = Record<string, string | number | null> & {
  _key?: string;
  _labels?: Record<string, string>;
  _series?: Record<string, string | number | null>[];
};

export type QueryResult = {
  dataset: DatasetSummary;
  dimensions: VisualDimension[];
  measures: VisualMeasure[];
  formulas: VisualFormula[];
  columns: QueryColumn[];
  rows: QueryRow[];
  totals: Record<string, number | null>;
  meta: {
    documents?: number;
    groups?: number;
    elapsed_ms?: number;
    truncated?: boolean;
    notes?: string[];
    index?: string | null;
    source?: string;
  };
  error?: string | null;
};

export type VisualRecord = {
  dataset: string;
  total: number;
  items: Record<string, unknown>[];
  columns: { key: string; label: string }[];
  exact?: boolean;
  notes?: string[];
  error?: string | null;
};

export type DashboardSummary = {
  id: string;
  name: string;
  description?: string | null;
  dataset?: string | null;
  tags: string[];
  visuals: number;
  owner_id?: string | null;
  owner_email?: string | null;
  mine: boolean;
  created_at?: string;
  updated_at?: string;
};

/** Configuração de um visual (o que se guarda num dashboard). */
export type VisualConfig = {
  id: string;
  title: string;
  chart: string;
  /** Dimensões: 0 (KPI) a 3. */
  dimensions: { id: string; interval?: string }[];
  measures: VisualMeasureSpec[];
  formulas: VisualFormula[];
  limit: number;
  top_n: number;
  others: boolean;
  sort: { by: string; order: "asc" | "desc" };
  /** Largura na grelha de 12 colunas. */
  width: number;
};

export type Dashboard = {
  id?: string;
  name: string;
  description?: string;
  dataset: string | null;
  filters: Record<string, unknown>;
  visuals: VisualConfig[];
  layout?: Record<string, unknown>;
  theme?: string;
  tags?: string[];
  owner_id?: string | null;
  owner_email?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type DashboardList = {
  total: number;
  items: DashboardSummary[];
  shared: number;
  note?: string | null;
  stats?: { dashboards: number; visuals: number; datasets: { dataset: string; dashboards: number }[]; storage: string } | null;
};

/** Dashboard-modelo pronto a usar (galeria de templates). */
export type VisualTemplate = {
  id: string;
  name: string;
  description?: string | null;
  domain?: string | null;
  icon?: string | null;
  tags: string[];
  dataset: string;
  dataset_label: string;
  requires_session: boolean;
  available: boolean;
  note?: string | null;
  /** Registos indexados na fonte (`null` quando não é possível saber). */
  records?: number | null;
  /** Fonte com pouquíssimos registos: o dashboard nasceria vazio. */
  sparse?: boolean;
  data_note?: string | null;
  visuals: VisualConfig[];
  filters: Record<string, unknown>;
  warnings: string[];
};

export type TemplateList = {
  total: number;
  items: VisualTemplate[];
  domains: { id: string; label: string; templates: string[] }[];
};

// ---------------------------------------------------------------------------
// Transporte
// ---------------------------------------------------------------------------
/**
 * Constrói o pedido de consulta a partir da configuração de um visual.
 *
 * Vive aqui (e não nos componentes) porque é usado tanto pelos cartões do editor
 * como pela exportação em lote de um dashboard.
 */
export function buildQuery(
  config: VisualConfig,
  datasetId: string,
  filters: Record<string, unknown>,
  search: string,
): VisualQueryRequest {
  const dimensions = config.dimensions
    .filter((entry) => entry.id)
    .map((entry) => (entry.interval ? { id: entry.id, interval: entry.interval } : { id: entry.id }));
  return {
    dataset: datasetId,
    dimensions: config.chart === "kpi" ? [] : dimensions,
    measures: config.measures,
    formulas: config.formulas.filter((formula) => formula.expression.trim()),
    filters,
    search: search.trim() || null,
    limit: config.limit,
    top_n: config.top_n > 0 ? config.top_n : null,
    others: config.others,
    sort: config.sort.by ? { by: config.sort.by, order: config.sort.order } : undefined,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
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
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

/** Catálogo de datasets, tipos de gráfico, intervalos e limites. */
export function getVisualizadorMeta(): Promise<VisualizadorMeta> {
  return request(`/visualizador/meta`);
}

/** Dimensões, medidas, filtros e sugestões de um dataset. */
export function getVisualizadorDataset(datasetId: string): Promise<DatasetDetail> {
  return request(`/visualizador/datasets/${encodeURIComponent(datasetId)}`);
}

/** Consulta analítica: dimensões × medidas (+ fórmulas). */
export function runVisualQuery(payload: VisualQueryRequest): Promise<QueryResult> {
  return request(`/visualizador/query`, withBody("POST", payload));
}

/** Registos individuais (drill-through / tabela de detalhe). */
export function getVisualRecords(payload: {
  dataset: string;
  filters?: Record<string, unknown>;
  search?: string | null;
  sort?: unknown;
  size?: number;
  from?: number;
}): Promise<VisualRecord> {
  return request(`/visualizador/records`, withBody("POST", payload));
}

/** Valores distintos de uma dimensão (seletores de filtros). */
export function getVisualValues(payload: {
  dataset: string;
  field: string;
  q?: string;
  filters?: Record<string, unknown>;
  limit?: number;
}): Promise<{ dataset: string; field: string; total: number; items: (string | number)[]; truncated: boolean; error?: string | null }> {
  return request(`/visualizador/values`, withBody("POST", payload));
}

/** Exporta o resultado de uma consulta (`csv` ou `xlsx`) e devolve o ficheiro. */
export async function exportVisualQuery(
  format: "csv" | "xlsx",
  payload: VisualQueryRequest,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/visualizador/export/${format}`, withBody("POST", payload));
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* sem JSON */
    }
    throw new Error(detail);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const blob = await response.blob();
  return { blob, filename: match ? match[1] : `visualizador.${format}` };
}

/** Dashboards guardados pelo utilizador. */
export function listVisualizadorDashboards(): Promise<DashboardList> {
  return request(`/visualizador/dashboards`);
}

export function getVisualizadorDashboard(id: string): Promise<Dashboard> {
  return request(`/visualizador/dashboards/${encodeURIComponent(id)}`);
}

export function saveVisualizadorDashboard(payload: Dashboard): Promise<Dashboard> {
  return request(`/visualizador/dashboards`, withBody("POST", payload));
}

export function duplicateVisualizadorDashboard(id: string, name?: string): Promise<Dashboard> {
  return request(`/visualizador/dashboards/${encodeURIComponent(id)}/duplicate`, withBody("POST", { name }));
}

export function deleteVisualizadorDashboard(id: string): Promise<{ removed: boolean; id: string }> {
  return request(`/visualizador/dashboards/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Dashboards-modelo (templates) validados contra o catálogo atual. */
export function getVisualizadorTemplates(): Promise<TemplateList> {
  return request(`/visualizador/templates`);
}

/** Cria um dashboard do utilizador a partir de um template. */
export function createDashboardFromTemplate(
  templateId: string,
  name?: string,
): Promise<{ dashboard: Dashboard; warnings: string[] }> {
  return request(`/visualizador/templates/${encodeURIComponent(templateId)}/dashboard`, withBody("POST", { name }));
}
