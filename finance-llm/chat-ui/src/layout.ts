/**
 * Preferências de interface da plataforma (independentes do dock).
 *
 * - Modo da barra lateral: `expanded` (com rótulos), `rail` (só ícones) ou
 *   `hidden` (escondida, com pega para reabrir).
 * - Grupos abertos: memorizados entre sessões.
 * - Vistas recentes: alimentam a secção «Recentes» da barra lateral.
 *
 * Tudo fica no `localStorage` e é partilhado entre separadores, tal como o
 * resto do estado do browser (workspace, dock, favoritos).
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";

export type SidebarMode = "expanded" | "rail" | "hidden";

const STORAGE_KEY = "finance-llm-sidebar-hidden"; // compatibilidade (API/Definições)
const MODE_KEY = "finance-llm-sidebar-mode";
const GROUPS_KEY = "finance-llm-sidebar-groups";
const RECENT_KEY = "finance-llm-sidebar-recent";
const CHANGE_EVENT = "finance-llm-sidebar-changed";
const RECENT_EVENT = "finance-llm-sidebar-recent-changed";
const RECENT_LIMIT = 5;

function readMode(): SidebarMode {
  if (typeof window === "undefined") return "expanded";
  try {
    const stored = window.localStorage.getItem(MODE_KEY);
    if (stored === "expanded" || stored === "rail" || stored === "hidden") return stored;
    // Migração: instalações antigas só tinham «escondida» sim/não.
    return window.localStorage.getItem(STORAGE_KEY) === "1" ? "hidden" : "expanded";
  } catch {
    return "expanded";
  }
}

let cache: SidebarMode = readMode();

function persistMode(mode: SidebarMode) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MODE_KEY, mode);
    // Mantém a chave antiga coerente com o que as Definições e o dock leem.
    window.localStorage.setItem(STORAGE_KEY, mode === "hidden" ? "1" : "0");
  } catch {
    // Modo privado: fica apenas em memória nesta sessão.
  }
}

export function getSidebarMode(): SidebarMode {
  return cache;
}

export function setSidebarMode(mode: SidebarMode) {
  cache = mode;
  persistMode(mode);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Compatibilidade: `true` quando a barra está totalmente escondida. */
export function getSidebarHidden() {
  return cache === "hidden";
}

export function setSidebarHidden(hidden: boolean) {
  setSidebarMode(hidden ? "hidden" : "expanded");
}

export function toggleSidebar() {
  setSidebarMode(cache === "hidden" ? "expanded" : "hidden");
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== STORAGE_KEY && event.key !== MODE_KEY) return;
    cache = readMode();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Modo da barra lateral, com persistência e atalho `Ctrl/Cmd + B`. */
export function useSidebar() {
  const mode = useSyncExternalStore(subscribe, getSidebarMode, getSidebarMode);
  const setMode = useCallback((next: SidebarMode) => setSidebarMode(next), []);
  const toggleHidden = useCallback(() => toggleSidebar(), []);
  const toggleRail = useCallback(() => setSidebarMode(cache === "rail" ? "expanded" : "rail"), []);
  return { mode, hidden: mode === "hidden", rail: mode === "rail", setMode, toggleHidden, toggleRail };
}

/** Compatibilidade com quem só precisa de saber se está escondida. */
export function useSidebarHidden() {
  const { hidden, setMode, toggleHidden } = useSidebar();
  const setHidden = useCallback((value: boolean) => setMode(value ? "hidden" : "expanded"), [setMode]);
  return { hidden, toggle: toggleHidden, setHidden };
}

/**
 * Regista o atalho `Ctrl/Cmd + B` para esconder/mostrar a barra lateral.
 * Deve ser usado **uma única vez** na aplicação (em `App`), para que o atalho
 * não alterne duas vezes com dois listeners ativos.
 */
export function useSidebarShortcut() {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      if (event.key.toLowerCase() !== "b") return;
      event.preventDefault();
      toggleSidebar();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

/* --------------------------------------------------------- grupos abertos */
function readGroups(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(GROUPS_KEY);
    const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    const clean: Record<string, boolean> = {};
    Object.entries(parsed).forEach(([key, value]) => {
      if (typeof value === "boolean") clean[key] = value;
    });
    return clean;
  } catch {
    return {};
  }
}

let groupsCache = readGroups();

function subscribeGroups(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== GROUPS_KEY) return;
    groupsCache = readGroups();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Grupos abertos/fechados na barra lateral (memorizados entre sessões). */
export function useNavGroups() {
  const groups = useSyncExternalStore(subscribeGroups, () => groupsCache, () => groupsCache);

  const toggleGroup = useCallback((id: string, fallback: boolean) => {
    const next = { ...groupsCache, [id]: !(groupsCache[id] ?? fallback) };
    groupsCache = next;
    try {
      window.localStorage.setItem(GROUPS_KEY, JSON.stringify(next));
    } catch {
      // Sem persistência: aplica-se apenas nesta sessão.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  const setGroupOpen = useCallback((id: string, open: boolean) => {
    const next = { ...groupsCache, [id]: open };
    groupsCache = next;
    try {
      window.localStorage.setItem(GROUPS_KEY, JSON.stringify(next));
    } catch {
      // Sem persistência.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  return { openGroups: groups, toggleGroup, setGroupOpen };
}

/* -------------------------------------------------------- vistas recentes */
function readRecent(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

let recentCache = readRecent();

/** Memoriza uma vista visitada (mais recente primeiro, sem duplicados). */
export function recordRecentView(id: string) {
  if (!id) return;
  const next = [id, ...recentCache.filter((item) => item !== id)].slice(0, RECENT_LIMIT);
  if (next.length === recentCache.length && next.every((item, index) => item === recentCache[index])) return;
  recentCache = next;
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Sem persistência.
  }
  window.dispatchEvent(new Event(RECENT_EVENT));
}

function subscribeRecent(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== RECENT_KEY) return;
    recentCache = readRecent();
    onChange();
  };
  window.addEventListener(RECENT_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(RECENT_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Últimas vistas visitadas (mais recentes primeiro). */
export function useRecentViews() {
  return useSyncExternalStore(subscribeRecent, () => recentCache, () => recentCache);
}
