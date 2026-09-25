/**
 * Acesso aos módulos da solução na barra lateral (por perfil).
 *
 * O servidor calcula, para o utilizador autenticado, a lista de módulos que
 * **não** deve ver — juntando o papel da plataforma (`admin`/`member`) com o
 * perfil de CRM atribuído (`comercial`, `marketing`, `convidado`…). A matriz é
 * gerida na página de administração (`PUT /admin/sidebar-access`).
 *
 * Este módulo guarda essa lista em cache (subscrevível) para o `AppNav`, o dock
 * e o menu Iniciar esconderem os mesmos módulos, sem cada um fazer o seu pedido.
 */
import { useSyncExternalStore } from "react";

import { API_BASE } from "./api";

export type SidebarProfileOption = {
  key: string;
  label: string;
  kind: "plataforma" | "crm";
  area?: string;
  department?: string;
  scope?: string;
};

export type SidebarAccessAdmin = {
  profiles: SidebarProfileOption[];
  profile_kinds: { id: string; label: string }[];
  protected: string[];
  rules: Record<string, string[]>;
  escondidos: Record<string, number>;
  updated_at?: string | null;
  updated_by?: string;
  backend?: string;
  gravado?: boolean;
  reposto?: boolean;
};

export type SidebarAccessMe = {
  hidden: string[];
  platform_role: string;
  profile: string;
  profile_label: string;
  rules_aplicadas?: string[];
  protected?: string[];
};

const EMPTY: SidebarAccessMe = { hidden: [], platform_role: "", profile: "", profile_label: "" };

let cache: SidebarAccessMe = EMPTY;
let loaded = false;
let pending: Promise<SidebarAccessMe> | null = null;

const CHANGE_EVENT = "finance-llm-sidebar-access";

function emit() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}

function commit(next: SidebarAccessMe) {
  cache = { ...next, hidden: [...(next.hidden || [])] };
  loaded = true;
  emit();
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
  return (await response.json()) as T;
}

/* ------------------------------------------------------------------ estado */

export function peekSidebarAccess(): SidebarAccessMe {
  return cache;
}

/** Módulos escondidos (conjunto, para consultas rápidas). */
export function hiddenModules(): Set<string> {
  return new Set(cache.hidden);
}

export function isModuleHidden(id: string): boolean {
  return cache.hidden.includes(id);
}

/** Esconde itens com um `id` (aplicações, secções, entradas de menu). */
export function dropHidden<T extends { id: string }>(items: T[]): T[] {
  if (cache.hidden.length === 0) return items;
  const hidden = hiddenModules();
  return items.filter((item) => !hidden.has(item.id));
}

export function sidebarAccessLoaded(): boolean {
  return loaded;
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => window.removeEventListener(CHANGE_EVENT, onChange);
}

/** Estado atual, com subscrição (re-render quando a lista muda). */
export function useSidebarAccess(): SidebarAccessMe {
  return useSyncExternalStore(subscribe, peekSidebarAccess, peekSidebarAccess);
}

/* ------------------------------------------------------------------- rotas */

/** Lista efetiva do utilizador autenticado (uma vez por sessão). */
export function loadSidebarAccess(force = false): Promise<SidebarAccessMe> {
  if (loaded && !force) return Promise.resolve(cache);
  if (pending && !force) return pending;
  pending = request<SidebarAccessMe>("/auth/sidebar-access")
    .then((result) => {
      commit(result);
      return cache;
    })
    .catch(() => {
      // Falha de rede: assume-se que tudo é visível (a plataforma continua a funcionar).
      commit(EMPTY);
      return cache;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

/** Esquece o que está em cache (ao terminar sessão). */
export function clearSidebarAccess() {
  cache = EMPTY;
  loaded = false;
  emit();
}

/** Matriz completa (só administradores). */
export function getSidebarAccessAdmin(): Promise<SidebarAccessAdmin> {
  return request<SidebarAccessAdmin>("/admin/sidebar-access");
}

/** Grava a matriz e atualiza já a lista efetiva do utilizador. */
export async function saveSidebarAccess(rules: Record<string, string[]>): Promise<SidebarAccessAdmin> {
  const result = await request<SidebarAccessAdmin>("/admin/sidebar-access", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rules }),
  });
  await loadSidebarAccess(true);
  return result;
}

/** Repõe tudo visível a todos os perfis. */
export async function resetSidebarAccess(): Promise<SidebarAccessAdmin> {
  const result = await request<SidebarAccessAdmin>("/admin/sidebar-access/reset", { method: "POST" });
  await loadSidebarAccess(true);
  return result;
}
