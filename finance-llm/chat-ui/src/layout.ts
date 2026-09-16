/**
 * Preferências de interface da plataforma (independentes do dock).
 *
 * Neste momento, apenas a visibilidade da barra lateral de navegação. Fica no
 * `localStorage` e é partilhada entre separadores, tal como o resto do estado
 * do browser (workspace, dock, favoritos).
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";

const STORAGE_KEY = "finance-llm-sidebar-hidden";
const CHANGE_EVENT = "finance-llm-sidebar-changed";

function read(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

let cache = read();

export function getSidebarHidden(): boolean {
  return cache;
}

export function setSidebarHidden(hidden: boolean) {
  cache = hidden;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, hidden ? "1" : "0");
  } catch {
    // Modo privado: fica apenas em memória nesta sessão.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function toggleSidebar() {
  setSidebarHidden(!cache);
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== STORAGE_KEY) return;
    cache = read();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Visibilidade da barra lateral, com persistência e atalho `Ctrl/Cmd + B`. */
export function useSidebarHidden() {
  const hidden = useSyncExternalStore(subscribe, getSidebarHidden, getSidebarHidden);
  const toggle = useCallback(() => toggleSidebar(), []);
  const set = useCallback((value: boolean) => setSidebarHidden(value), []);
  return { hidden, toggle, setHidden: set };
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
