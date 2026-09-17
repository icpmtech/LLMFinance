/**
 * Cliente da área de administração (`/admin/*`).
 *
 * Todas as chamadas passam pelo `fetch` já instrumentado em `authApi.ts`, que
 * injeta o token da sessão — os endpoints exigem papel `admin` (o servidor
 * devolve 403 caso contrário).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type EventLevel = "debug" | "info" | "warning" | "error" | "critical";

export type SystemEvent = {
  id?: string;
  timestamp: string;
  level: EventLevel | string;
  source: string;
  message: string;
  data?: Record<string, unknown>;
  user_id?: string;
  user_email?: string;
  method?: string;
  path?: string;
  status?: number;
  duration_ms?: number;
  ip?: string;
  host?: string;
  pid?: number;
};

export type EventCount = { key: string; count: number };

export type EventStats = {
  hours: number;
  total: number;
  by_level: EventCount[];
  by_source: EventCount[];
  by_hour: EventCount[];
  top_paths: EventCount[];
  backend: string;
};

export type EventSearchResponse = {
  items: SystemEvent[];
  total: number;
  from: number;
  size: number;
  backend: string;
  capacity?: number;
};

export type AdminUser = {
  id: string;
  email: string;
  name: string;
  initials?: string;
  role: string;
  status: string;
  title?: string;
  organization?: string;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string;
  login_count?: number;
  active_sessions?: number;
};

export type IndexSummary = {
  index: string;
  exists: boolean;
  documents: number;
  size: string;
  error?: string;
};

export type AdminOverview = {
  api: {
    service: string;
    python: string;
    platform: string;
    host: string;
    pid: number;
    started_at: string;
    uptime_seconds: number;
    buffer_size: number;
    buffer_capacity: number;
    events_file: string;
    root: string;
  };
  elasticsearch: {
    available: boolean;
    error?: string;
    url?: string;
    cluster?: string;
    node?: string;
    version?: string;
    status?: string;
    nodes?: number;
    shards?: number;
    index_list?: IndexSummary[];
  };
  accounts: {
    users: number;
    active_sessions: number;
    by_role: EventCount[];
    by_status: EventCount[];
  };
  events: EventStats;
  logs: LogFile[];
};

export type LogFile = { name: string; size: number; modified_at: string };

export type LogTail = {
  name: string;
  size: number;
  total_lines: number;
  lines: string[];
  truncated: boolean;
};

/* ---------------------------------------------------------------- helpers */

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
  return (await response.json()) as T;
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: body === undefined ? "POST" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/* ----------------------------------------------------------------- rotas */

export function getAdminOverview(): Promise<AdminOverview> {
  return request<AdminOverview>("/admin/overview");
}

export function listAdminUsers(params: { q?: string; role?: string; status?: string; limit?: number } = {}): Promise<{
  total: number;
  items: AdminUser[];
  returned: number;
}> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.role) query.set("role", params.role);
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 200));
  return request(`/admin/users?${query}`);
}

export function updateAdminUser(
  userId: string,
  patch: { role?: string; status?: string; name?: string; title?: string; organization?: string },
): Promise<{ user: AdminUser }> {
  return request(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function deleteAdminUser(userId: string): Promise<{ ok: boolean; message: string }> {
  return request(`/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

export function revokeAdminUserSessions(userId: string): Promise<{ ok: boolean; message: string }> {
  return post(`/admin/users/${encodeURIComponent(userId)}/revoke-sessions`);
}

export type EventQuery = {
  level?: string;
  source?: string;
  user?: string;
  q?: string;
  since?: string;
  until?: string;
  backend?: "memory" | "elasticsearch" | "auto";
  from?: number;
  size?: number;
};

export function listAdminEvents(params: EventQuery = {}): Promise<EventSearchResponse> {
  const query = new URLSearchParams();
  if (params.level) query.set("level", params.level);
  if (params.source) query.set("source", params.source);
  if (params.user) query.set("user", params.user);
  if (params.q) query.set("q", params.q);
  if (params.since) query.set("since", params.since);
  if (params.until) query.set("until", params.until);
  if (params.backend) query.set("backend", params.backend);
  query.set("from", String(params.from ?? 0));
  query.set("size", String(params.size ?? 100));
  return request(`/admin/events?${query}`);
}

export function getAdminEventStats(hours = 24): Promise<EventStats> {
  return request(`/admin/events/stats?hours=${hours}`);
}

export function logAdminEvent(payload: { level: string; source: string; message: string; data?: Record<string, unknown> }): Promise<{ event: SystemEvent }> {
  return post("/admin/events", payload);
}

export function listAdminLogs(): Promise<{ files: LogFile[] }> {
  return request("/admin/logs");
}

export function tailAdminLog(name: string, lines = 200): Promise<LogTail> {
  return request(`/admin/logs/${encodeURIComponent(name)}?lines=${lines}`);
}
