/**
 * Cliente da API de autenticação.
 *
 * O token fica em `localStorage` e é injetado automaticamente em todos os
 * pedidos feitos à API (`fetch` é envolvido uma única vez), pelo que os
 * endpoints protegidos passam a receber `Authorization: Bearer <token>` sem
 * ser preciso alterar cada chamada existente.
 */
import { API_BASE } from "./api";

const TOKEN_KEY = "finance-llm-token";

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  initials: string;
  role: "admin" | "member" | string;
  status: string;
  title: string;
  organization: string;
  phone: string;
  locale: string;
  timezone: string;
  created_at: string | null;
  updated_at: string | null;
  last_login_at: string | null;
  login_count: number;
  preferences: Record<string, unknown>;
  password_updated_at: string | null;
};

export type AuthSession = {
  id: string;
  created_at: string | null;
  last_seen_at: string | null;
  expires_at: string | null;
  user_agent: string;
  ip: string;
  current: boolean;
};

export type ProfilePreferences = {
  default_view?: string;
  dock_position?: string;
  sidebar_hidden?: boolean;
  sidebar_mode?: string;
  window_mode?: boolean;
  reduced_motion?: boolean;
};

export type ProfilePatch = {
  name?: string;
  title?: string;
  organization?: string;
  phone?: string;
  locale?: string;
  timezone?: string;
  preferences?: ProfilePreferences;
};

/* ------------------------------------------------------------------ token */
let token: string | null = null;

try {
  token = typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
} catch {
  token = null;
}

export function getToken() {
  return token;
}

export function setToken(next: string | null) {
  token = next;
  try {
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(TOKEN_KEY, next);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Modo privado: fica apenas em memória.
  }
}

/** Injeta o token em todos os pedidos dirigidos à API. */
let fetchPatched = false;
export function installAuthFetch() {
  if (fetchPatched || typeof window === "undefined" || !window.fetch) return;
  fetchPatched = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!token || !url.startsWith(API_BASE)) return original(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
    return original(input, { ...init, headers });
  };
}

/* ------------------------------------------------------------- pedidos */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new Error("Não foi possível contactar o servidor. Verifique se a API está a correr.");
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail.length
          ? String((detail[0] as { msg?: string })?.msg ?? "Dados inválidos.")
          : `Erro ${response.status}`;
    throw new Error(message);
  }

  return payload as T;
}

export type AuthResult = { token: string; expires_at: string; user: AuthUser };

export const authApi = {
  register: (data: { name: string; email: string; password: string; title?: string; organization?: string }) =>
    request<AuthResult>("/auth/register", { method: "POST", body: JSON.stringify(data) }),

  login: (data: { email: string; password: string; remember?: boolean }) =>
    request<AuthResult>("/auth/login", { method: "POST", body: JSON.stringify(data) }),

  logout: () => request<{ ok: boolean; message: string }>("/auth/logout", { method: "POST" }),

  me: () => request<AuthUser>("/auth/me"),

  updateProfile: (patch: ProfilePatch) =>
    request<AuthUser>("/auth/me", { method: "PATCH", body: JSON.stringify(patch) }),

  changePassword: (data: { current_password: string; new_password: string }) =>
    request<{ ok: boolean; message: string }>("/auth/password", { method: "POST", body: JSON.stringify(data) }),

  sessions: () => request<AuthSession[]>("/auth/sessions"),

  revokeSession: (id: string) => request<{ ok: boolean; message: string }>(`/auth/sessions/${id}`, { method: "DELETE" }),

  revokeOtherSessions: () => request<{ ok: boolean; message: string }>("/auth/sessions", { method: "DELETE" }),

  deleteAccount: (password: string) =>
    request<{ ok: boolean; message: string }>("/auth/me", { method: "DELETE", body: JSON.stringify({ password }) }),
};
