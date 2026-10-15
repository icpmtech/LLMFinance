/**
 * Cliente do **Estúdio de relatórios** (`/reports/studio/*`).
 *
 * Área de criação de relatórios, reservada a administradores e gestores de
 * relatórios: modelos (`templates`), fontes de dados com dimensões e medidas
 * (`sources`), relatórios (blocos, gráficos, tabelas e grafos), ajuda da IA,
 * geração do PDF e publicação — no catálogo da plataforma (`site`) ou na loja —
 * com preço.
 *
 * Como no resto do módulo, o token é injetado pelo `installAuthFetch()`, mas os
 * **downloads** passam por `fetch` + `blob` (um `<a href>` não leva o
 * `Authorization`).
 */
import { API_BASE } from "./api";

// ------------------------------------------------------------------ contexto
export type StudioAccess = {
  studio: boolean;
  email: string;
  name: string;
  role: string;
  manager: boolean;
  channels: { id: string; label: string }[];
  reports: { total: number; drafts: number; published: number; with_pdf: number };
};

export type StudioLimits = {
  max_blocks: number;
  max_dimensions: number;
  max_measures: number;
  max_kpi: number;
  max_rows: number;
  max_graph_edges: number;
  max_text: number;
  widths: number[];
};

export type StudioOption = { id: string; label: string; hint?: string };

export type StudioSourceDimension = { id: string; label: string; type?: string | null; unit?: string | null };
export type StudioSourceMeasure = { id: string; label: string; kind?: string; format?: string; unit?: string | null };

export type StudioSource = {
  id: string;
  label: string;
  description: string;
  domain: string;
  icon: string;
  kind: string;
  recommended: boolean;
  dimensions: StudioSourceDimension[];
  measures: StudioSourceMeasure[];
  defaults: { dimension?: string; measure?: string; limit?: number; dimension_interval?: string | null };
  suggestions: { chart: string; title: string; dimensions: unknown[]; measures: unknown[] }[];
};

export type StudioSources = {
  sources: StudioSource[];
  groups: { id: string; label: string; hint?: string; sources: string[] }[];
  block_types: StudioOption[];
  chart_types: StudioOption[];
  ai_modes: StudioOption[];
  limits: StudioLimits;
  problems: string[];
  available: boolean;
  generated_at: string;
};

export type StudioState = {
  module: string;
  sources: number;
  available: boolean;
  templates: number;
  block_types: string[];
  chart_types: string[];
  limits: StudioLimits;
  reports: { total: number; drafts: number; published: number; with_pdf: number };
  managers: string[];
  problems: string[];
  pdf: boolean;
  ai: boolean;
};

// --------------------------------------------------------------------- blocos
export type StudioBlockType = "heading" | "text" | "note" | "ai" | "kpi" | "chart" | "table" | "graph";

export type StudioBlock = {
  id: string;
  type: StudioBlockType;
  title: string;
  text: string;
  prompt: string;
  source: string;
  dimensions: string[];
  measures: string[];
  filters: Record<string, unknown> | string;
  search: string;
  chart: string;
  limit: number;
  top_n: number;
  width: number;
  format: string;
};

export type StudioPublication = {
  published: boolean;
  price: number;
  list_price: number;
  at: string;
  by: string;
  package_id?: string;
  product_id?: string;
};

export type StudioFile = {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: string;
  created_at: string;
};

export type StudioReport = {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  summary: string;
  template: string;
  tags: string[];
  theme: string;
  targets_note: string;
  blocks: StudioBlock[];
  publication: { site: StudioPublication; loja: StudioPublication };
  published: boolean;
  channels: string[];
  status: string;
  status_label: string;
  status_style: string;
  files: StudioFile[];
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
  stats: {
    blocks: number;
    charts: number;
    tables: number;
    ai: number;
    has_pdf: boolean;
    sources: string[];
  };
  auto_key?: string;
};

export type StudioTemplate = {
  id: string;
  name: string;
  description: string;
  subtitle: string;
  icon: string;
  tags: string[];
  blocks: StudioBlock[];
  block_count: number;
  warnings: string[];
  available: boolean;
};

export type StudioTemplates = { templates: StudioTemplate[]; total: number; sources: number };

export type StudioReportList = {
  items: StudioReport[];
  total: number;
  labels: Record<string, string>;
  styles: Record<string, string>;
  templates: { id: string; name: string }[];
  targets: StudioOption[];
  stats: { total: number; drafts: number; published: number; with_pdf: number };
};

// ------------------------------------------------------------------ execução
export type StudioResultColumn = {
  key: string;
  label: string;
  type: string;
  format?: string | null;
  unit?: string | null;
  measure_kind?: string;
};

export type StudioRunBlock = {
  id: string;
  type: string;
  title: string;
  text?: string;
  chart?: string;
  width?: number;
  skipped?: boolean;
  error?: string | null;
  dataset?: { id?: string; label?: string };
  dimensions?: { id: string; label?: string; format?: string | null }[];
  measures?: { id: string; label?: string; kind?: string; format?: string | null }[];
  columns?: StudioResultColumn[];
  rows?: Record<string, unknown>[];
  totals?: Record<string, number | null>;
  notes?: string[];
  graph?: {
    nodes: { id: string; side: string; value: number }[];
    edges: { source: string; target: string; value: number }[];
    measure: string;
    origin?: string;
    target?: string;
    labels?: { origin?: string; target?: string };
  };
};

export type StudioRun = {
  report: StudioReport;
  blocks: StudioRunBlock[];
  problems: string[];
  generated_at: string;
};

export type StudioAssist = {
  mode: string;
  text: string;
  factual: string;
  blocks: StudioBlock[];
  ai?: boolean;
  backend?: { kind?: string; provider?: string; model?: string } | null;
  notes: string[];
  warnings: string[];
  generated_at: string;
};

export type StudioPublishResult = {
  report: StudioReport;
  target: string;
  package?: Record<string, unknown>;
  product?: Record<string, unknown>;
};

// --------------------------------------------------------------------- HTTP
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload?.detail) detail = payload.detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

// ----------------------------------------------------------------- contexto
export const getStudioMe = () => request<StudioAccess>("/reports/studio/me");
export const getStudioState = () => request<StudioState>("/reports/studio/state");
export const getStudioSources = () => request<StudioSources>("/reports/studio/sources");
export const getStudioTemplates = () => request<StudioTemplates>("/reports/studio/templates");

// ----------------------------------------------------------------- relatórios
export const listStudioReports = (params: { q?: string; status?: string; channel?: string } = {}) => {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.status) search.set("status", params.status);
  if (params.channel) search.set("channel", params.channel);
  const suffix = search.toString();
  return request<StudioReportList>(`/reports/studio/reports${suffix ? `?${suffix}` : ""}`);
};

export const getStudioReport = (id: string) => request<StudioReport>(`/reports/studio/reports/${encodeURIComponent(id)}`);

export const createStudioReport = (payload: { template?: string; title?: string; blocks?: StudioBlock[] }) =>
  request<{ report: StudioReport; warnings: string[] }>("/reports/studio/reports", withBody("POST", payload));

export const saveStudioReport = (id: string, payload: Partial<StudioReport>) =>
  request<{ report: StudioReport; warnings: string[] }>(`/reports/studio/reports/${encodeURIComponent(id)}`, withBody("PUT", payload));

export const deleteStudioReport = (id: string) =>
  request<{ removed: boolean; reports: StudioReportList["stats"] }>(`/reports/studio/reports/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const duplicateStudioReport = (id: string, title?: string) =>
  request<{ report: StudioReport }>(`/reports/studio/reports/${encodeURIComponent(id)}/duplicate`, withBody("POST", { title }));

// ------------------------------------------------------------------- execução
export const runStudioDraft = (payload: { report?: Partial<StudioReport>; blocks?: StudioBlock[]; block_ids?: string[] }) =>
  request<StudioRun>("/reports/studio/query", withBody("POST", payload));

export const runStudioReport = (id: string, blockIds?: string[]) =>
  request<StudioRun>(`/reports/studio/reports/${encodeURIComponent(id)}/run`, withBody("POST", { block_ids: blockIds }));

// ------------------------------------------------------------------- PDF
export const generateStudioPdf = (id: string) =>
  request<{ report: StudioReport; file: StudioFile }>(`/reports/studio/reports/${encodeURIComponent(id)}/pdf`, { method: "POST" });

export async function downloadStudioFile(reportId: string, fileId: string, filename: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/reports/studio/reports/${encodeURIComponent(reportId)}/files/${encodeURIComponent(fileId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`Não foi possível descarregar (${response.status}).`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "relatorio.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const deleteStudioFile = (reportId: string, fileId: string) =>
  request<{ removed: boolean; report: StudioReport }>(
    `/reports/studio/reports/${encodeURIComponent(reportId)}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );

// ---------------------------------------------------------------- publicação
export type StudioPublishPayload = {
  target: "site" | "loja" | "todos";
  price?: number;
  list_price?: number;
  delivery_days?: number;
  max_targets?: number;
  code?: string;
  badge?: string;
  note?: string;
  short_description?: string;
  description?: string;
  targets_note?: string;
};

export const publishStudioReport = (id: string, payload: StudioPublishPayload) =>
  request<StudioPublishResult>(`/reports/studio/reports/${encodeURIComponent(id)}/publish`, withBody("POST", payload));

export const unpublishStudioReport = (id: string, target: "site" | "loja") =>
  request<{ report: StudioReport; target: string }>(
    `/reports/studio/reports/${encodeURIComponent(id)}/unpublish`,
    withBody("POST", { target }),
  );

// ----------------------------------------------------------------------- IA
export const studioAssist = (payload: {
  mode: "sumario" | "texto" | "insights" | "blocos";
  report?: string;
  block?: string;
  source?: string;
  prompt?: string;
  blocks?: StudioBlock[];
}) => request<StudioAssist>("/reports/studio/ai", withBody("POST", payload));

export const studioReportAssist = (
  id: string,
  payload: { mode: "sumario" | "texto" | "insights" | "blocos"; block?: string; prompt?: string; source?: string },
) => request<StudioAssist>(`/reports/studio/reports/${encodeURIComponent(id)}/ai`, withBody("POST", payload));

// --------------------------------------------------------------- utilitários
export function studioMoney(value: number | undefined | null): string {
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" }).format(Number(value || 0));
}

export function studioNumber(value: unknown, format = ""): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(number)) return String(value);
  if (format === "currency") return studioMoney(number);
  if (format === "integer") return number.toLocaleString("pt-PT", { maximumFractionDigits: 0 });
  return number.toLocaleString("pt-PT", { maximumFractionDigits: 2 });
}

export function studioCompact(value: number | null | undefined): string {
  const number = Number(value || 0);
  const abs = Math.abs(number);
  if (abs >= 1_000_000_000) return `${(number / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mM`;
  if (abs >= 1_000_000) return `${(number / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M`;
  if (abs >= 1_000) return `${(number / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil`;
  return number.toLocaleString("pt-PT", { maximumFractionDigits: 2 });
}

export function studioBytes(value: number | undefined | null): string {
  const total = Number(value || 0);
  if (total < 1024) return `${total} B`;
  if (total < 1024 * 1024) return `${(total / 1024).toFixed(0)} KB`;
  return `${(total / (1024 * 1024)).toFixed(1)} MB`;
}

export function studioDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
