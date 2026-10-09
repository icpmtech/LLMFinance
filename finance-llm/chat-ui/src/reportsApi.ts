/**
 * Cliente do módulo «Relatórios» (`/reports/*`).
 *
 * Áreas: catálogo e pedidos do cliente, pagamento por MB Way, backoffice de
 * produção (`/reports/backoffice/*`) e configuração na administração
 * (`/reports/admin/*`).
 *
 * O token é injetado pelo `installAuthFetch()` (patch do `window.fetch`), pelo
 * que aqui se usa `fetch` normal — mas os **downloads** têm de passar por
 * `fetch` + `blob`: um `<a href>` direto não leva o cabeçalho `Authorization` e
 * devolveria 401.
 */
import { API_BASE } from "./api";

export type ReportsTarget = { name: string; nif: string };

export type ReportsPackage = {
  id: string;
  code: string;
  title: string;
  subtitle: string;
  note: string;
  price: number;
  list_price: number;
  badge: string;
  max_targets: number;
  delivery_days: number;
  active: boolean;
  features: string[];
};

export type ReportsPaymentMethod = { id: string; label: string; hint: string };

export type ReportsPublicSettings = {
  mbway_number: string;
  mbway_holder: string;
  mbway_enabled: boolean;
  mbway_api: boolean;
  iban: string;
  payment_instructions: string;
  vat_rate: number;
  methods: ReportsPaymentMethod[];
};

export type ReportsPayment = {
  method: string;
  method_label: string;
  status: string;
  status_label: string;
  status_style: string;
  mbway_phone: string;
  mbway_number: string;
  mbway_reference: string;
  requested_at: string;
  paid_at: string;
  confirmed_by: string;
  note: string;
  automatic: boolean;
  provider_request_id?: string;
};

export type ReportsFile = {
  id: string;
  name: string;
  size: number;
  mime: string;
  uploaded_at: string;
  uploaded_by: string;
};

export type ReportsHistoryItem = {
  id: string;
  at: string;
  by: string;
  kind: string;
  message: string;
  from_status: string;
  to_status: string;
  visibility?: string;
};

export type ReportsRequest = {
  id: string;
  reference: string;
  status: string;
  status_label: string;
  status_style: string;
  status_hint: string;
  next_statuses: { id: string; label: string; style: string }[];
  flow: { id: string; label: string; done: boolean }[];
  package_id: string;
  package_title: string;
  package_subtitle: string;
  targets: ReportsTarget[];
  targets_label: string;
  notes: string;
  requester: { email: string; name: string };
  assigned_to: string;
  amounts: { subtotal: number; vat: number; total: number };
  payment: ReportsPayment;
  files: ReportsFile[];
  created_at: string;
  updated_at: string;
  payment_instructions: string;
  internal_note: string;
  history: ReportsHistoryItem[];
};

export type ReportsCatalogue = {
  packages: ReportsPackage[];
  settings: ReportsPublicSettings;
  my_open: number;
  unread: number;
  statuses: Record<string, string>;
};

export type ReportsSummary = {
  total: number;
  by_status: Record<string, number>;
  labels: Record<string, string>;
  styles: Record<string, string>;
  payments: Record<string, string>;
  unread: number;
  to_pay: number;
  in_progress: number;
  ready: number;
  methods: ReportsPaymentMethod[];
};

export type ReportsNotification = {
  id: string;
  user_email: string;
  title: string;
  body: string;
  kind: string;
  request_id: string;
  request_reference: string;
  read: boolean;
  created_at: string;
};

export type ReportsStats = {
  total: number;
  by_status: Record<string, number>;
  labels: Record<string, string>;
  revenue: number;
  pending_payment: number;
  awaiting_confirm: number;
  open: number;
};

export type ReportsBackofficeInbox = {
  items: ReportsRequest[];
  total: number;
  stats: ReportsStats;
  labels: Record<string, string>;
  styles: Record<string, string>;
  payment_labels: Record<string, string>;
  payment_styles: Record<string, string>;
  statuses: { id: string; label: string }[];
  unread: number;
  activity: { id: string; action: string; reference: string; actor: string; detail: string; at: string }[];
  me: { email: string; name: string };
};

export type ReportsAdminSettings = ReportsPublicSettings & {
  mbway_provider: string;
  mbway_api_url: string;
  mbway_api_set: boolean;
  mbway_api_hint: string;
  auto_confirm_mbway_api: boolean;
  default_delivery_days: number;
  backoffice_users: string[];
  notify_extra_emails: string[];
  updated_at: string;
  updated_by: string;
};

export type ReportsAdminPayload = {
  settings: ReportsAdminSettings;
  catalogue: ReportsPackage[];
  stats: ReportsStats;
  payments: Record<string, string>;
  methods: ReportsPaymentMethod[];
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

export function money(value: number | undefined | null): string {
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR" }).format(Number(value || 0));
}

export function bytes(value: number | undefined | null): string {
  const total = Number(value || 0);
  if (total < 1024) return `${total} B`;
  if (total < 1024 * 1024) return `${(total / 1024).toFixed(0)} KB`;
  return `${(total / (1024 * 1024)).toFixed(1)} MB`;
}

export function shortDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Converte o tom devolvido pela API (`sky`, `emerald`, …) numa variante do `Badge`. */
export function badgeVariant(style: string): "default" | "success" | "warning" | "info" | "danger" | "outline" | "secondary" {
  switch ((style || "").toLowerCase()) {
    case "emerald":
    case "teal":
      return "success";
    case "amber":
      return "warning";
    case "sky":
    case "violet":
    case "indigo":
      return "info";
    case "rose":
      return "danger";
    case "zinc":
    case "slate":
      return "secondary";
    default:
      return "default";
  }
}

// ------------------------------------------------------------------ cliente
export const getReportsCatalogue = () => request<ReportsCatalogue>("/reports/catalogue");
export const getReportsSummary = () => request<ReportsSummary>("/reports/summary");
export const getMyReports = (status = "") =>
  request<{ items: ReportsRequest[]; total: number }>(`/reports/requests${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const getReport = (id: string) => request<ReportsRequest>(`/reports/requests/${encodeURIComponent(id)}`);

export const createReport = (payload: { package_id: string; targets: ReportsTarget[]; notes: string; mbway_phone: string }) =>
  request<ReportsRequest>("/reports/requests", withBody("POST", payload));

export const declareReportPayment = (id: string, payload: { method: string; mbway_phone: string; note: string }) =>
  request<{ request: ReportsRequest; automatic: { ok: boolean; configured: boolean; message: string; request_id?: string } }>(
    `/reports/requests/${encodeURIComponent(id)}/payment`,
    withBody("POST", payload),
  );

export const getReportPaymentStatus = (id: string) =>
  request<{ ok: boolean; automatic: boolean; paid?: boolean; message?: string; request: ReportsRequest }>(
    `/reports/requests/${encodeURIComponent(id)}/payment/status`,
  );

export const cancelReport = (id: string, message = "") =>
  request<ReportsRequest>(`/reports/requests/${encodeURIComponent(id)}/cancel`, withBody("POST", { message }));

export async function downloadReportFile(requestId: string, fileId: string, filename: string): Promise<void> {
  const response = await fetch(`${API_BASE}/reports/requests/${encodeURIComponent(requestId)}/files/${encodeURIComponent(fileId)}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Não foi possível descarregar (${response.status}).`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "relatorio";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const getReportsNotifications = (limit = 30) =>
  request<{ items: ReportsNotification[]; unread: number }>(`/reports/notifications?limit=${limit}`);
export const markReportsNotificationsRead = (ids?: string[]) =>
  request<{ marked: number; unread: number }>("/reports/notifications/read", withBody("POST", ids ? { ids } : {}));

// --------------------------------------------------------------- backoffice
export const getReportsBackofficeMe = () =>
  request<{ backoffice: boolean; role: string; email: string; unread: number; stats: Partial<ReportsStats> }>("/reports/backoffice/me");

export const getReportsInbox = (params: { status?: string; q?: string; mine?: boolean } = {}) => {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.q) search.set("q", params.q);
  if (params.mine) search.set("mine", "true");
  const suffix = search.toString();
  return request<ReportsBackofficeInbox>(`/reports/backoffice/inbox${suffix ? `?${suffix}` : ""}`);
};

export const getReportsBackofficeRequest = (id: string) =>
  request<ReportsRequest>(`/reports/backoffice/requests/${encodeURIComponent(id)}`);

export const patchReportsRequest = (id: string, payload: { status: string; note?: string; assigned_to?: string | null; internal?: boolean }) =>
  request<ReportsRequest>(`/reports/backoffice/requests/${encodeURIComponent(id)}`, withBody("PATCH", payload));

export const decideReportsPayment = (id: string, payload: { action: "confirm" | "reject"; note?: string; amount?: number | null }) =>
  request<ReportsRequest>(`/reports/backoffice/requests/${encodeURIComponent(id)}/payment`, withBody("POST", payload));

export async function uploadReportFile(id: string, file: File, markGenerated = true): Promise<ReportsRequest> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${API_BASE}/reports/backoffice/requests/${encodeURIComponent(id)}/files?mark_generated=${markGenerated ? "true" : "false"}`,
    { method: "POST", body: form, cache: "no-store" },
  );
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload?.detail) detail = payload.detail;
    } catch {
      /* sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as ReportsRequest;
}

export const deleteReportFile = (id: string, fileId: string) =>
  request<{ removed: boolean; request: ReportsRequest }>(
    `/reports/backoffice/requests/${encodeURIComponent(id)}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );

export const addReportNote = (id: string, payload: { message: string; internal: boolean }) =>
  request<ReportsRequest>(`/reports/backoffice/requests/${encodeURIComponent(id)}/note`, withBody("POST", payload));

export function reportsExportUrl(status = ""): string {
  return `${API_BASE}/reports/backoffice/export.csv${status ? `?status=${encodeURIComponent(status)}` : ""}`;
}

export async function downloadReportsExport(status = ""): Promise<void> {
  const response = await fetch(reportsExportUrl(status), { cache: "no-store" });
  if (!response.ok) throw new Error(`Exportação indisponível (${response.status}).`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "relatorios.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// -------------------------------------------------------------------- admin
export const getReportsAdmin = () => request<ReportsAdminPayload>("/reports/admin/settings");

export const saveReportsAdminSettings = (patch: Partial<ReportsAdminSettings>) =>
  request<ReportsAdminSettings>("/reports/admin/settings", withBody("PUT", patch));

export const saveReportsPackage = (payload: Partial<ReportsPackage>) =>
  request<ReportsPackage>("/reports/admin/catalogue", withBody("POST", payload));

export const deleteReportsPackage = (id: string) =>
  request<{ removed: boolean; catalogue: ReportsPackage[] }>(`/reports/admin/catalogue/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
