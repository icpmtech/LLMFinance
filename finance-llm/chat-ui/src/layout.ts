/**
 * Preferências de interface da plataforma (independentes do dock).
 *
 * - Modo da barra lateral: `expanded` (com rótulos), `rail` (só ícones) ou
 *   `hidden` (escondida, com pega para reabrir).
 * - Largura redimensionável (arrastar a divisória, duplo clique repõe).
 * - Grupos abertos: memorizados entre sessões.
 * - Recentes: alimentam a secção «Recentes» da barra lateral.
 *
 * Tudo fica no `localStorage` e é partilhado entre separadores, tal como o
 * resto do estado do browser (workspace, dock, favoritos).
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";

export type SidebarMode = "expanded" | "rail" | "hidden";

const STORAGE_KEY = "finance-llm-sidebar-hidden"; // compatibilidade (API/Definições)
const MODE_KEY = "finance-llm-sidebar-mode";
const WIDTH_KEY = "finance-llm-sidebar-width";
const GROUPS_KEY = "finance-llm-sidebar-groups";
const RECENT_KEY = "finance-llm-sidebar-recent";
const CHANGE_EVENT = "finance-llm-sidebar-changed";
const WIDTH_EVENT = "finance-llm-sidebar-width-changed";
const RECENT_EVENT = "finance-llm-sidebar-recent-changed";
const RECENT_LIMIT = 5;

/** Limites da largura da barra lateral (como o arrasto da divisória no macOS). */
export const SIDEBAR_MIN_WIDTH = 196;
export const SIDEBAR_MAX_WIDTH = 384;
export const SIDEBAR_DEFAULT_WIDTH = 268;
export const SIDEBAR_RAIL_WIDTH = 68;

function clampWidth(value: number) {
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(value)));
}

function readWidth(): number {
  if (typeof window === "undefined") return SIDEBAR_DEFAULT_WIDTH;
  try {
    const stored = Number(window.localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(stored) && stored > 0 ? clampWidth(stored) : SIDEBAR_DEFAULT_WIDTH;
  } catch {
    return SIDEBAR_DEFAULT_WIDTH;
  }
}

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

let widthCache: number = readWidth();

export function getSidebarWidth(): number {
  return widthCache;
}

/** Define a largura da barra lateral (valores fora dos limites são ajustados). */
export function setSidebarWidth(value: number) {
  const next = clampWidth(value);
  if (next === widthCache) return;
  widthCache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WIDTH_KEY, String(next));
  } catch {
    // sem persistência
  }
  window.dispatchEvent(new Event(WIDTH_EVENT));
}

/** Repõe a largura predefinida (duplo clique na divisória). */
export function resetSidebarWidth() {
  setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
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

function subscribeWidth(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== WIDTH_KEY) return;
    widthCache = readWidth();
    onChange();
  };
  window.addEventListener(WIDTH_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(WIDTH_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Largura da barra lateral (redimensionável com arrasto da divisória). */
export function useSidebarWidth() {
  const width = useSyncExternalStore(subscribeWidth, getSidebarWidth, getSidebarWidth);
  const setWidth = useCallback((value: number) => setSidebarWidth(value), []);
  const reset = useCallback(() => resetSidebarWidth(), []);
  return { width, setWidth, reset };
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

/* ------------------------------------------------- material de vidro (glass) */
/**
 * O «vidro» é um material partilhado pelo dock e pelas janelas: em vez de
 * repetir `backdrop-filter` por todo o lado, os componentes leem variáveis CSS
 * (abaixo) e o utilizador ajusta o material num único sítio.
 *
 * `strength` vai de 0 (quase transparente, muito desfocado) a 1 (mais opaco).
 * Com o vidro desligado as variáveis passam a "sem desfoco" e as superfícies
 * ficam praticamente opacas, para ecrãs ou GPUs mais fracos.
 */
export type GlassPrefs = {
  /** Vidro ativo no dock, nas janelas e nos painéis flutuantes. */
  enabled: boolean;
  /** Intensidade do material (0 = mais transparente, 1 = mais opaco). */
  strength: number;
  /** Papel de parede do «desktop» (dá cor ao vidro por trás). */
  wallpaper: boolean;
};

const GLASS_KEY = "finance-llm-glass:v1";
const GLASS_EVENT = "finance-llm-glass-changed";

const DEFAULT_GLASS: GlassPrefs = { enabled: true, strength: 0.6, wallpaper: true };

function readGlass(): GlassPrefs {
  if (typeof window === "undefined") return DEFAULT_GLASS;
  try {
    const raw = window.localStorage.getItem(GLASS_KEY);
    if (!raw) return DEFAULT_GLASS;
    const parsed = JSON.parse(raw) as Partial<GlassPrefs> | null;
    return {
      enabled: typeof parsed?.enabled === "boolean" ? parsed.enabled : DEFAULT_GLASS.enabled,
      strength:
        typeof parsed?.strength === "number" && Number.isFinite(parsed.strength)
          ? Math.min(1, Math.max(0, parsed.strength))
          : DEFAULT_GLASS.strength,
      wallpaper: typeof parsed?.wallpaper === "boolean" ? parsed.wallpaper : DEFAULT_GLASS.wallpaper,
    };
  } catch {
    return DEFAULT_GLASS;
  }
}

let glassCache: GlassPrefs = readGlass();

/** Escreve os tokens do material no `<html>` (o resto do estilo só lê variáveis). */
export function applyGlass(prefs: GlassPrefs = glassCache) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const strength = Math.min(1, Math.max(0, prefs.strength));
  root.dataset.glass = prefs.enabled ? "on" : "off";
  root.dataset.wallpaper = prefs.wallpaper ? "on" : "off";
  root.style.setProperty("--glass-blur", prefs.enabled ? `${Math.round(8 + strength * 30)}px` : "0px");
  root.style.setProperty("--glass-saturate", prefs.enabled ? `${Math.round(130 + strength * 70)}%` : "100%");
  root.style.setProperty("--glass-window-alpha", (0.56 + strength * 0.3).toFixed(3));
  root.style.setProperty("--glass-window-alpha-edge", (0.44 + strength * 0.3).toFixed(3));
  root.style.setProperty("--glass-bar-alpha", (0.1 + strength * 0.16).toFixed(3));
  root.style.setProperty("--glass-body-alpha", (0.46 + strength * 0.34).toFixed(3));
  root.style.setProperty("--glass-dock-alpha", (0.38 + strength * 0.36).toFixed(3));
  root.style.setProperty("--glass-dock-alpha-edge", (0.5 + strength * 0.36).toFixed(3));
  root.style.setProperty("--glass-border", `rgba(255, 255, 255, ${(0.1 + strength * 0.1).toFixed(3)})`);
  root.style.setProperty("--glass-highlight", `rgba(255, 255, 255, ${(0.11 + strength * 0.08).toFixed(3)})`);
}

export function getGlass(): GlassPrefs {
  return glassCache;
}

export function setGlass(patch: Partial<GlassPrefs>) {
  glassCache = { ...glassCache, ...patch };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(GLASS_KEY, JSON.stringify(glassCache));
    } catch {
      // Sem persistência: o material aplica-se apenas nesta sessão.
    }
  }
  applyGlass();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(GLASS_EVENT));
}

function subscribeGlass(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== GLASS_KEY) return;
    glassCache = readGlass();
    applyGlass();
    onChange();
  };
  window.addEventListener(GLASS_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(GLASS_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Preferências do material de vidro (dock, janelas e painéis). */
export function useGlass() {
  const glass = useSyncExternalStore(subscribeGlass, getGlass, getGlass);
  const set = useCallback((patch: Partial<GlassPrefs>) => setGlass(patch), []);
  const toggle = useCallback(() => setGlass({ enabled: !glassCache.enabled }), []);
  return { glass, setGlass: set, toggleGlass: toggle };
}

/* Aplica o material assim que o módulo carrega (antes do primeiro paint útil). */
applyGlass();

/* --------------------------------------------------------------- janelas 3D */
/**
 * Efeito 3D opcional para as janelas do IQ OS (estilo "profundidade" do
 * visionOS/Windows): as janelas sem foco recuam ligeiramente e, ao arrastar, a
 * janela inclina-se um pouco na direção do movimento (como um cartão a ser
 * empurrado). A inclinação é composta no `transform` da própria janela (a
 * perspetiva vive no mesmo elemento, por isso não depende da árvore 3D).
 *
 * `tilt` é a inclinação máxima em graus (0–8).
 */
export type Window3dPrefs = {
  /** Efeito 3D ligado (inclinação + profundidade). */
  enabled: boolean;
  /** Inclinação máxima ao arrastar, em graus (0–8). */
  tilt: number;
  /** Janelas sem foco recuam (dão profundidade à área de trabalho). */
  depth: boolean;
};

const WINDOW3D_KEY = "finance-llm-window3d:v1";
const WINDOW3D_EVENT = "finance-llm-window3d-changed";

const DEFAULT_WINDOW3D: Window3dPrefs = { enabled: true, tilt: 5, depth: true };

function readWindow3d(): Window3dPrefs {
  if (typeof window === "undefined") return DEFAULT_WINDOW3D;
  try {
    const raw = window.localStorage.getItem(WINDOW3D_KEY);
    if (!raw) return DEFAULT_WINDOW3D;
    const parsed = JSON.parse(raw) as Partial<Window3dPrefs> | null;
    return {
      enabled: typeof parsed?.enabled === "boolean" ? parsed.enabled : DEFAULT_WINDOW3D.enabled,
      tilt:
        typeof parsed?.tilt === "number" && Number.isFinite(parsed.tilt)
          ? Math.min(8, Math.max(0, parsed.tilt))
          : DEFAULT_WINDOW3D.tilt,
      depth: typeof parsed?.depth === "boolean" ? parsed.depth : DEFAULT_WINDOW3D.depth,
    };
  } catch {
    return DEFAULT_WINDOW3D;
  }
}

let window3dCache: Window3dPrefs = readWindow3d();

/** Distância do observador à janela, em px (quanto mais inclinada, mais próxima). */
export function window3dPerspective(tilt: number) {
  return Math.round(1000 + Math.min(8, Math.max(0, tilt)) * 80);
}

/** Escala de uma janela sem foco, com a profundidade ligada. */
export const WINDOW3D_DEPTH_SCALE = 0.982;

/** Escreve os tokens do efeito 3D no `<html>` e liga/desliga a perspetiva. */
export function applyWindow3d(prefs: Window3dPrefs = window3dCache) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const tilt = Math.min(8, Math.max(0, prefs.tilt));
  root.dataset.window3d = prefs.enabled ? "on" : "off";
  root.dataset.window3dDepth = prefs.depth ? "on" : "off";
  root.style.setProperty("--win3d-tilt", `${tilt.toFixed(2)}deg`);
  root.style.setProperty("--win3d-perspective", `${window3dPerspective(tilt)}px`);
  root.style.setProperty("--win3d-depth-scale", prefs.depth ? String(WINDOW3D_DEPTH_SCALE) : "1");
  // Sombra/decalque que a janela sem foco ganha ao recuar.
  root.style.setProperty("--win3d-depth-shadow", prefs.depth ? "0 14px 38px rgba(0, 0, 0, 0.42)" : "none");
}

export function getWindow3d(): Window3dPrefs {
  return window3dCache;
}

export function setWindow3d(patch: Partial<Window3dPrefs>) {
  window3dCache = { ...window3dCache, ...patch };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(WINDOW3D_KEY, JSON.stringify(window3dCache));
    } catch {
      // Sem persistência: aplica-se apenas nesta sessão.
    }
  }
  applyWindow3d();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(WINDOW3D_EVENT));
}

function subscribeWindow3d(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== WINDOW3D_KEY) return;
    window3dCache = readWindow3d();
    applyWindow3d();
    onChange();
  };
  window.addEventListener(WINDOW3D_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(WINDOW3D_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Preferências do efeito 3D das janelas. */
export function useWindow3d() {
  const window3d = useSyncExternalStore(subscribeWindow3d, getWindow3d, getWindow3d);
  const set = useCallback((patch: Partial<Window3dPrefs>) => setWindow3d(patch), []);
  const toggle = useCallback(() => setWindow3d({ enabled: !window3dCache.enabled }), []);
  return { window3d, setWindow3d: set, toggleWindow3d: toggle };
}

applyWindow3d();

/* --------------------------------------------------------- estilo das janelas */
/**
 * Aspeto das janelas: `macos` (semáforos à esquerda, cantos grandes, vidro) ou
 * `windows` (Windows 11: ícone e título à esquerda, minimizar/maximizar/fechar
 * à direita, cantos de 8 px e material tipo Mica). Só muda o chrome — o
 * comportamento (arrastar, encaixe, minimizar para o dock, 3D) é o mesmo.
 */
export type WindowStyle = "macos" | "windows";

const WINDOW_STYLE_KEY = "finance-llm-window-style:v1";
const WINDOW_STYLE_EVENT = "finance-llm-window-style-changed";
const DEFAULT_WINDOW_STYLE: WindowStyle = "macos";

function readWindowStyle(): WindowStyle {
  if (typeof window === "undefined") return DEFAULT_WINDOW_STYLE;
  try {
    const raw = window.localStorage.getItem(WINDOW_STYLE_KEY);
    return raw === "windows" || raw === "macos" ? raw : DEFAULT_WINDOW_STYLE;
  } catch {
    return DEFAULT_WINDOW_STYLE;
  }
}

let windowStyleCache: WindowStyle = readWindowStyle();

/** Escreve o estilo no `<html>` (`data-window-style`): o CSS faz o resto. */
export function applyWindowStyle(style: WindowStyle = windowStyleCache) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.windowStyle = style;
}

export function getWindowStyle(): WindowStyle {
  return windowStyleCache;
}

export function setWindowStyle(style: WindowStyle) {
  windowStyleCache = style;
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(WINDOW_STYLE_KEY, style);
    } catch {
      // Sem persistência: aplica-se apenas nesta sessão.
    }
  }
  applyWindowStyle();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(WINDOW_STYLE_EVENT));
}

function subscribeWindowStyle(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== WINDOW_STYLE_KEY) return;
    windowStyleCache = readWindowStyle();
    applyWindowStyle();
    onChange();
  };
  window.addEventListener(WINDOW_STYLE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(WINDOW_STYLE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Estilo das janelas (macOS ou Windows 11). */
export function useWindowStyle() {
  const style = useSyncExternalStore(subscribeWindowStyle, getWindowStyle, getWindowStyle);
  const set = useCallback((next: WindowStyle) => setWindowStyle(next), []);
  return { windowStyle: style, setWindowStyle: set };
}

applyWindowStyle();

/* ------------------------------------------------------------- modo janelas */
const WINDOW_MODE_KEY = "finance-llm-window-mode";

function readWindowMode(): boolean {
  // Num ecrã pequeno (telemóvel) as janelas flutuantes seriam apertadas:
  // aí a omissão é o modo página.
  const fallback = () =>
    typeof window === "undefined" ? true : window.matchMedia("(min-width: 1024px)").matches;
  if (typeof window === "undefined") return true;
  try {
    const stored = window.localStorage.getItem(WINDOW_MODE_KEY);
    return stored === null ? fallback() : stored === "1";
  } catch {
    return fallback();
  }
}

let windowModeCache = readWindowMode();

/** `true` quando as páginas abrem em janelas flutuantes (estilo macOS). */
export function getWindowMode() {
  return windowModeCache;
}

export function setWindowMode(enabled: boolean) {
  windowModeCache = enabled;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WINDOW_MODE_KEY, enabled ? "1" : "0");
  } catch {
    // sem persistência
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribeWindowMode(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== WINDOW_MODE_KEY) return;
    windowModeCache = readWindowMode();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Modo janelas (com persistência). */
export function useWindowMode() {
  const enabled = useSyncExternalStore(subscribeWindowMode, getWindowMode, getWindowMode);
  const toggle = useCallback(() => setWindowMode(!windowModeCache), []);
  const set = useCallback((value: boolean) => setWindowMode(value), []);
  return { windowMode: enabled, setWindowMode: set, toggleWindowMode: toggle };
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
