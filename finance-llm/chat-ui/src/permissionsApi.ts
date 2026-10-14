/**
 * Cliente do módulo de permissões (`/permissions/*`).
 *
 * O token é injetado pelo `fetch` já envolvido em `authApi.ts`, como no
 * `adminApi`. `GET /permissions` e a gravação exigem papel `admin`; o resumo do
 * próprio utilizador (`/permissions/me`) é de qualquer conta autenticada.
 */
import { API_BASE } from "./api";

export type PermissionAction = "read" | "write";

export type PermissionRole = {
  id: string;
  label: string;
  is_admin: boolean;
};

export type PermissionModule = {
  id: string;
  label: string;
  group: string;
  content: boolean;
  self_service: boolean;
  admin_only: boolean;
};

export type PermissionMatrix = Record<string, Record<string, Record<PermissionAction, boolean>>>;

export type PermissionsState = {
  index: string;
  doc_id: string;
  roles: PermissionRole[];
  modules: PermissionModule[];
  matrix: PermissionMatrix;
  protected: string[];
  admin_only: string[];
  read_like_note: string;
  atualizado_em?: string | null;
  atualizado_por?: string | null;
};

export type MyPermissions = {
  role: string;
  role_label: string;
  can_write_all: boolean;
  read_only: boolean;
  writable_modules: string[];
  self_service: string[];
};

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

export function getPermissions(): Promise<PermissionsState> {
  return request<PermissionsState>("/permissions");
}

export function savePermissions(matrix: PermissionMatrix): Promise<{ ok: boolean; matrix: PermissionMatrix }> {
  return request("/permissions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ matrix }),
  });
}

export function resetPermissions(): Promise<{ ok: boolean; matrix: PermissionMatrix }> {
  return request("/permissions/reset", { method: "POST" });
}

export function getMyPermissions(): Promise<MyPermissions> {
  return request<MyPermissions>("/permissions/me");
}
