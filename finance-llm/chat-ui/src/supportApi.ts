/**
 * Cliente da consola de apoio ao cliente (`/admin/support/*`).
 *
 * O widget das páginas públicas é autónomo (`api/support_widget.js`) e não passa
 * por aqui. Esta camada serve a Administração: fila de conversas, transcrição,
 * mensagens em tempo real, tickets e presença dos operadores.
 */
import { API_BASE } from "./api";
import { getToken } from "./authApi";

export type SupportSessionStatus = "waiting" | "active" | "closed";

export type SupportSession = {
  id: string;
  visitor_id: string;
  user_id: string;
  status: SupportSessionStatus | string;
  subject: string;
  visitor_name: string;
  visitor_email: string;
  visitor: Record<string, unknown>;
  context: Record<string, unknown>;
  pages: { url: string; title?: string; at?: string }[];
  assigned_operator_id: string;
  assigned_operator_name: string;
  assigned_to_me: boolean;
  tags: string[];
  unread_operator: number;
  unread_visitor: number;
  message_count: number;
  rating: number | null;
  rating_comment: string;
  online: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_message_at: string | null;
  last_visitor_message_at: string | null;
  last_seen_at: string | null;
  closed_at: string | null;
};

export type SupportMessageKind = "text" | "link" | "report" | "form" | "form_response" | string;

export type SupportFormField = {
  key: string;
  label: string;
  type: "text" | "email" | "tel" | "textarea" | "select" | "number" | "date" | string;
  required: boolean;
  placeholder?: string;
  options?: string[];
};

export type SupportFormPayload = {
  form_id: string;
  title: string;
  description: string;
  submit_label: string;
  template?: string;
  fields: SupportFormField[];
};

export type SupportLinkPayload = {
  url: string;
  title: string;
  description: string;
};

export type SupportReportPayload = {
  report_id: string;
  title: string;
  summary: string;
  url: string;
  free: boolean;
  area: string;
};

export type SupportFormResponse = {
  response_id: string;
  submitted_at: string | null;
  values: Record<string, string>;
  by: string;
};

export type SupportMessage = {
  id: string;
  session_id: string;
  author_type: "visitor" | "operator" | "system" | "note" | string;
  author_id: string;
  author_name: string;
  body: string;
  kind: SupportMessageKind;
  payload: Record<string, unknown>;
  form_response: SupportFormResponse | null;
  client_id: string;
  internal: boolean;
  created_at: string | null;
  pending?: boolean;
};

export type SupportTicket = {
  id: string;
  session_id: string;
  visitor_id: string;
  subject: string;
  description: string;
  status: string;
  priority: string;
  category: string;
  requester: Record<string, unknown>;
  assigned_operator_id: string;
  assigned_operator_name: string;
  notes: { at?: string; by?: string; text?: string }[];
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
};

export type SupportEvent = {
  id: string;
  kind: string;
  session_id: string;
  ticket_id: string;
  actor_type: string;
  actor_id: string;
  actor_name: string;
  detail: string;
  data: Record<string, unknown>;
  created_at: string | null;
};

export type SupportOperator = {
  id: string;
  name: string;
  email: string;
  status: string;
  last_seen_at: string | null;
  live_status?: string;
};

export type SupportOverview = {
  waiting: number;
  active: number;
  closed: number;
  open: number;
  unread: number;
  tickets_open: number;
  today: number;
  oldest_waiting: { id?: string; visitor_name?: string; created_at?: string } | null;
  operators: SupportOperator[];
  events: SupportEvent[];
  operators_online: number;
};

export type SupportSessionDetail = {
  session: SupportSession;
  messages: SupportMessage[];
  tickets: SupportTicket[];
  form_responses: SupportFormResponse[];
  events: SupportEvent[];
  account: Record<string, unknown> | null;
  visitor: Record<string, unknown> | null;
};

export type SupportReportOption = {
  report_id: string;
  title: string;
  subtitle: string;
  summary: string;
  url: string;
  free: boolean;
  kind: string;
  kind_label: string;
  area: string;
  price: number;
};

export type SupportFormTemplate = {
  id: string;
  title: string;
  description: string;
  fields: SupportFormField[];
};

export const TICKET_STATUS_LABELS: Record<string, string> = {
  open: "Aberto",
  pending: "Pendente",
  resolved: "Resolvido",
  closed: "Fechado",
};

export const TICKET_PRIORITY_LABELS: Record<string, string> = {
  low: "Baixa",
  normal: "Normal",
  high: "Alta",
  urgent: "Urgente",
};

export const SESSION_STATUS_LABELS: Record<string, string> = {
  waiting: "À espera",
  active: "Em curso",
  closed: "Fechada",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
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
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/* --------------------------------------------------------------- operador */
export function getSupportOverview(): Promise<SupportOverview> {
  return request<SupportOverview>("/admin/support/overview");
}

export function listSupportSessions(
  params: {
    status?: string;
    q?: string;
    assigned?: string;
    unread?: boolean;
    from?: number;
    size?: number;
  } = {},
): Promise<{ items: SupportSession[]; total: number; from: number; size: number }> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.q) query.set("q", params.q);
  if (params.assigned) query.set("assigned", params.assigned);
  if (params.unread) query.set("unread", "true");
  query.set("from", String(params.from ?? 0));
  query.set("size", String(params.size ?? 60));
  return request(`/admin/support/sessions?${query}`);
}

export function getSupportSession(sessionId: string): Promise<SupportSessionDetail> {
  return request(`/admin/support/sessions/${encodeURIComponent(sessionId)}`);
}

export function claimSupportSession(sessionId: string): Promise<{ session: SupportSession }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/claim`);
}

export function releaseSupportSession(sessionId: string): Promise<{ session: SupportSession }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/release`);
}

export function closeSupportSession(sessionId: string): Promise<{ session: SupportSession }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/close`);
}

export function readSupportSession(sessionId: string): Promise<{ session: SupportSession }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/read`);
}

export function sendSupportMessage(
  sessionId: string,
  body: string,
  options: {
    internal?: boolean;
    clientId?: string;
    kind?: SupportMessageKind;
    payload?: Record<string, unknown>;
  } = {},
): Promise<{ message: SupportMessage; session: SupportSession }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/messages`, {
    body,
    client_id: options.clientId ?? "",
    internal: options.internal ?? false,
    kind: options.kind ?? "text",
    payload: options.payload,
  });
}

export function listSupportReports(q = ""): Promise<{ items: SupportReportOption[]; total: number }> {
  const query = new URLSearchParams();
  if (q) query.set("q", q);
  query.set("limit", "60");
  return request(`/admin/support/reports?${query}`);
}

export function listSupportFormTemplates(): Promise<{
  templates: SupportFormTemplate[];
  field_types: string[];
  max_fields: number;
}> {
  return request("/admin/support/forms");
}

export function listSupportTickets(
  params: { status?: string; q?: string; sessionId?: string } = {},
): Promise<{ items: SupportTicket[]; total: number }> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.q) query.set("q", params.q);
  if (params.sessionId) query.set("session_id", params.sessionId);
  query.set("size", "100");
  return request(`/admin/support/tickets?${query}`);
}

export function updateSupportTicket(
  ticketId: string,
  patch: { status?: string; priority?: string; category?: string; note?: string },
): Promise<{ ticket: SupportTicket }> {
  return request(`/admin/support/tickets/${encodeURIComponent(ticketId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function createSupportTicket(
  sessionId: string,
  payload: { subject: string; description?: string; category?: string; priority?: string },
): Promise<{ ticket: SupportTicket }> {
  return post(`/admin/support/sessions/${encodeURIComponent(sessionId)}/ticket`, payload);
}

export function listSupportEvents(params: { sessionId?: string; from?: number; size?: number } = {}): Promise<{
  items: SupportEvent[];
  total: number;
}> {
  const query = new URLSearchParams();
  if (params.sessionId) query.set("session_id", params.sessionId);
  query.set("from", String(params.from ?? 0));
  query.set("size", String(params.size ?? 80));
  return request(`/admin/support/events?${query}`);
}

export function listSupportOperators(): Promise<{
  items: SupportOperator[];
  operators_online: number;
  connected: string[];
}> {
  return request("/admin/support/operators");
}

export function setSupportOperatorStatus(status: "online" | "away"): Promise<{ operator: SupportOperator }> {
  return post("/admin/support/operators/me", { status });
}

/** URL do WebSocket de operador, derivado da base da API (relativa ou absoluta). */
export function supportOperatorSocketUrl(token: string): string {
  const base = /^https?:\/\//i.test(API_BASE)
    ? new URL(`${API_BASE}/support/ws`)
    : new URL(`${API_BASE || ""}/support/ws`, window.location.href);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.searchParams.set("role", "operator");
  base.searchParams.set("token", token);
  return base.toString();
}
