/**
 * Gestor de janelas (estilo macOS).
 *
 * Cada aplicação da plataforma abre numa janela flutuante sobre a área de
 * trabalho, com barra de título arrastável, botões (fechar / minimizar /
 * maximizar), redimensionamento pelas margens e empilhamento por foco.
 *
 * Uma aplicação tem no máximo **uma** janela (como no macOS): voltar a abrir
 * foca/restaura a existente. O estado (posição, tamanho, minimizada, maximizada)
 * vive no `localStorage`, pelo que a sessão é retomada ao recarregar.
 */
import { useCallback, useSyncExternalStore } from "react";

export type WindowRect = { x: number; y: number; width: number; height: number };

export type WindowState = WindowRect & {
  /** Vista da aplicação (`AppView`) mostrada na janela. */
  view: string;
  z: number;
  minimized: boolean;
  maximized: boolean;
  /** Geometria antes de maximizar (para restaurar). */
  prev?: WindowRect;
  /** Título próprio (fichas, quick look) quando não vem do catálogo de apps. */
  title?: string;
};

export type WindowOptions = { focus?: boolean; title?: string; rect?: Partial<WindowRect> };

export type WorkspaceSize = { width: number; height: number };

const STORAGE_KEY = "finance-llm-windows:v1";
const CHANGE_EVENT = "finance-llm-windows-changed";

export const MIN_WINDOW_WIDTH = 360;
export const MIN_WINDOW_HEIGHT = 240;
/** Margem mínima visível da barra de título ao arrastar. */
const EDGE_KEEP = 96;

type Store = { windows: WindowState[]; topZ: number };

function defaultRect(index: number, workspace: WorkspaceSize): WindowRect {
  const width = Math.round(Math.min(1180, Math.max(420, workspace.width * 0.8)));
  const height = Math.round(Math.min(820, Math.max(320, workspace.height * 0.82)));
  const offset = index % 6;
  return {
    x: Math.max(8, Math.round((workspace.width - width) / 2) + offset * 26),
    y: Math.max(8, Math.round((workspace.height - height) / 2) - 20 + offset * 22),
    width,
    height,
  };
}

function read(): Store {
  if (typeof window === "undefined") return { windows: [], topZ: 10 };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { windows: [], topZ: 10 };
    const parsed = JSON.parse(raw) as Partial<Store> | null;
    const windows = Array.isArray(parsed?.windows)
      ? parsed!.windows
          .map((item): WindowState | null => {
            const candidate = item as Partial<WindowState> | null;
            if (!candidate || typeof candidate.view !== "string") return null;
            const number = (value: unknown, fallback: number) =>
              typeof value === "number" && Number.isFinite(value) ? value : fallback;
            return {
              view: candidate.view,
              x: number(candidate.x, 40),
              y: number(candidate.y, 40),
              width: Math.max(MIN_WINDOW_WIDTH, number(candidate.width, 900)),
              height: Math.max(MIN_WINDOW_HEIGHT, number(candidate.height, 600)),
              z: number(candidate.z, 10),
              minimized: candidate.minimized === true,
              maximized: candidate.maximized === true,
              prev: candidate.prev as WindowRect | undefined,
              ...(typeof candidate.title === "string" ? { title: candidate.title } : {}),
            };
          })
          .filter((item): item is WindowState => item !== null)
      : [];
    const topZ = windows.reduce((max, item) => Math.max(max, item.z), 10);
    return { windows, topZ };
  } catch {
    return { windows: [], topZ: 10 };
  }
}

let cache: Store = read();

function commit(next: Store) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Sem persistência: a sessão de janelas vive apenas em memória.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getWindows(): WindowState[] {
  return cache.windows;
}

export function getTopZ(): number {
  return cache.topZ;
}

/** Janela de uma aplicação (uma por vista). */
export function windowFor(view: string): WindowState | undefined {
  return cache.windows.find((item) => item.view === view);
}

function focusIn(list: WindowState[], view: string): WindowState[] {
  const top = cache.topZ + 1;
  cache.topZ = top;
  return list.map((item) =>
    item.view === view ? { ...item, z: top, minimized: false } : item,
  );
}

/**
 * Estimativa da área de trabalho a partir da janela do browser e da barra
 * lateral. Usada por quem abre janelas fora do gestor (fichas, quick look).
 */
export function estimateWorkspace(): WorkspaceSize {
  if (typeof window === "undefined") return { width: 1200, height: 800 };
  const mode = typeof window.localStorage?.getItem === "function" ? window.localStorage.getItem("finance-llm-sidebar-mode") : null;
  const sidebar = mode === "hidden" ? 0 : mode === "rail" ? 72 : 268;
  return {
    width: Math.max(360, window.innerWidth - sidebar),
    height: Math.max(240, window.innerHeight - 140),
  };
}

/** Abre a janela da aplicação (ou foca/restaura a existente). */
export function openWindow(view: string, workspace?: WorkspaceSize, options?: WindowOptions): void {
  const existing = windowFor(view);
  if (existing) {
    if (options?.focus === false) return;
    commit({
      windows: focusIn(
        cache.windows.map((item) =>
          item.view === view && options?.title ? { ...item, title: options.title } : item,
        ),
        view,
      ),
      topZ: cache.topZ,
    });
    return;
  }
  const top = cache.topZ + 1;
  cache.topZ = top;
  const base = defaultRect(cache.windows.length, workspace ?? estimateWorkspace());
  const rect = { ...base, ...(options?.rect ?? {}) };
  commit({
    windows: [
      ...cache.windows,
      { view, ...rect, z: top, minimized: false, maximized: false, ...(options?.title ? { title: options.title } : {}) },
    ],
    topZ: top,
  });
}

export function closeWindow(view: string) {
  if (!windowFor(view)) return;
  commit({ windows: cache.windows.filter((item) => item.view !== view), topZ: cache.topZ });
}

export function closeAllWindows() {
  if (cache.windows.length === 0) return;
  commit({ windows: [], topZ: cache.topZ });
}

export function focusWindow(view: string) {
  const existing = windowFor(view);
  if (!existing) return;
  if (existing.z === cache.topZ && !existing.minimized) return;
  commit({ windows: focusIn(cache.windows, view), topZ: cache.topZ });
}

export function minimizeWindow(view: string) {
  // Guarda o estado (incluindo "maximizada") para a janela voltar como estava.
  commit({
    windows: cache.windows.map((item) => (item.view === view ? { ...item, minimized: true } : item)),
    topZ: cache.topZ,
  });
}

export function restoreWindow(view: string) {
  commit({ windows: focusIn(cache.windows, view), topZ: cache.topZ });
}

export function toggleMaximizeWindow(view: string, workspace: WorkspaceSize) {
  commit({
    windows: cache.windows.map((item) => {
      if (item.view !== view) return item;
      if (item.maximized) {
        const prev = item.prev ?? defaultRect(0, workspace);
        return { ...item, ...prev, maximized: false, prev: undefined, z: cache.topZ };
      }
      return {
        ...item,
        prev: { x: item.x, y: item.y, width: item.width, height: item.height },
        x: 0,
        y: 0,
        width: workspace.width,
        height: workspace.height,
        maximized: true,
        minimized: false,
      };
    }),
    topZ: cache.topZ,
  });
}

/** Maximiza sem alternar (usado no encaixe no topo do ecrã). */
export function maximizeWindow(view: string, workspace: WorkspaceSize) {
  commit({
    windows: cache.windows.map((item) =>
      item.view === view
        ? {
            ...item,
            prev: item.maximized
              ? item.prev
              : { x: item.x, y: item.y, width: item.width, height: item.height },
            x: 0,
            y: 0,
            width: workspace.width,
            height: workspace.height,
            maximized: true,
            minimized: false,
          }
        : item,
    ),
    topZ: cache.topZ,
  });
}

/** Atualiza a geometria de uma janela (arrastar/redimensionar/snap). */
export function setWindowRect(view: string, rect: Partial<WindowRect> & { maximized?: boolean }) {
  const existing = windowFor(view);
  if (!existing) return;
  commit({
    windows: cache.windows.map((item) => {
      if (item.view !== view) return item;
      // Arrastar uma janela maximizada repõe o tamanho anterior (como no macOS).
      const isMove = rect.width === undefined && rect.height === undefined;
      const restore = isMove && item.maximized && item.prev ? item.prev : null;
      return {
        ...item,
        x: rect.x ?? item.x,
        y: rect.y ?? item.y,
        width: Math.max(MIN_WINDOW_WIDTH, rect.width ?? restore?.width ?? item.width),
        height: Math.max(MIN_WINDOW_HEIGHT, rect.height ?? restore?.height ?? item.height),
        // Uma geometria definida à mão deixa de ser "maximizada",
        // a menos que o pedido diga o contrário.
        maximized: rect.maximized ?? false,
        prev: undefined,
      };
    }),
    topZ: cache.topZ,
  });
}

/** Disposição em cascata (como o "Organizar por" do Finder). */
export function cascadeWindows(workspace: WorkspaceSize) {
  const visible = cache.windows.filter((item) => !item.minimized);
  if (visible.length === 0) return;
  // O tamanho nunca excede a área de trabalho (ecrãs pequenos incluídos).
  const size = {
    width: Math.round(Math.min(workspace.width, Math.min(1100, Math.max(420, workspace.width * 0.7)))),
    height: Math.round(Math.min(workspace.height, Math.min(760, Math.max(320, workspace.height * 0.74)))),
  };
  let index = 0;
  const windows = cache.windows.map((item) => {
    if (item.minimized) return item;
    const rect = defaultRect(index, workspace);
    index += 1;
    // A cascata nunca empurra uma janela para fora da área de trabalho.
    const x = Math.max(0, Math.min(rect.x, Math.max(0, workspace.width - size.width)));
    const y = Math.max(0, Math.min(rect.y, Math.max(0, workspace.height - size.height)));
    return { ...item, x, y, width: size.width, height: size.height, maximized: false, prev: undefined };
  });
  commit({ windows, topZ: cache.topZ });
}

/** Reparte `total` por `parts`, sem sobras (a última célula absorve o resto). */
function splitSpace(total: number, parts: number): number[] {
  const base = Math.floor(total / parts);
  const rest = total - base * parts;
  return Array.from({ length: parts }, (_, index) => base + (index < rest ? 1 : 0));
}

/**
 * Grelha para `count` janelas: colunas = ⌈√count⌉ (o formato que os gestores de
 * janelas usam, que mantém as células parecidas com a área de trabalho e evita
 * grelhas esburacadas do género 7×1).
 */
function gridFor(count: number): { columns: number; rows: number } {
  const columns = Math.min(count, Math.ceil(Math.sqrt(count)));
  return { columns, rows: Math.ceil(count / columns) };
}

/** Coloca todas as janelas visíveis lado a lado, sem sobreposições nem fendas. */
export function tileWindows(workspace: WorkspaceSize) {
  const visible = cache.windows.filter((item) => !item.minimized).sort((a, b) => a.z - b.z);
  if (visible.length === 0) return;
  const { columns, rows } = gridFor(visible.length);
  // As sobras de píxeis vão para as primeiras células, para a grelha preencher
  // a área de trabalho exatamente (sem fendas de 1–2 px nas margens).
  const widths = splitSpace(Math.max(1, Math.round(workspace.width)), columns);
  const heights = splitSpace(Math.max(1, Math.round(workspace.height)), rows);
  const xs: number[] = [];
  const ys: number[] = [];
  let accX = 0;
  for (const value of widths) {
    xs.push(accX);
    accX += value;
  }
  let accY = 0;
  for (const value of heights) {
    ys.push(accY);
    accY += value;
  }
  let index = 0;
  const windows = cache.windows.map((item) => {
    if (item.minimized) return item;
    const column = index % columns;
    const row = Math.floor(index / columns);
    index += 1;
    return {
      ...item,
      x: xs[column] ?? 0,
      y: ys[row] ?? 0,
      width: widths[column] ?? workspace.width,
      height: heights[row] ?? workspace.height,
      maximized: false,
      prev: undefined,
    };
  });
  commit({ windows, topZ: cache.topZ });
}

/** Mantém a janela dentro da área de trabalho (reage a redimensionar a janela do browser). */
export function clampWindows(workspace: WorkspaceSize) {
  let changed = false;
  const windows = cache.windows.map((item) => {
    const width = Math.min(item.width, Math.max(MIN_WINDOW_WIDTH, workspace.width));
    const height = Math.min(item.height, Math.max(MIN_WINDOW_HEIGHT, workspace.height));
    const maxX = Math.max(0, workspace.width - EDGE_KEEP);
    const maxY = Math.max(0, workspace.height - 40);
    const x = Math.min(Math.max(item.x, -width + EDGE_KEEP), maxX);
    const y = Math.min(Math.max(item.y, 0), maxY);
    if (x !== item.x || y !== item.y || width !== item.width || height !== item.height) {
      changed = true;
      return { ...item, x, y, width, height, maximized: false, prev: undefined };
    }
    return item;
  });
  if (changed) commit({ windows, topZ: cache.topZ });
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

/** Janelas abertas, pela ordem de criação (o `z` define o empilhamento). */
export function useWindows() {
  const windows = useSyncExternalStore(subscribe, getWindows, getWindows);
  const topZ = useSyncExternalStore(subscribe, getTopZ, getTopZ);

  const open = useCallback(
    (view: string, workspace: WorkspaceSize) => openWindow(view, workspace),
    [],
  );
  const close = useCallback((view: string) => closeWindow(view), []);
  const focus = useCallback((view: string) => focusWindow(view), []);
  const minimize = useCallback((view: string) => minimizeWindow(view), []);
  const restore = useCallback((view: string) => restoreWindow(view), []);
  const closeAll = useCallback(() => closeAllWindows(), []);

  return { windows, topZ, open, close, focus, minimize, restore, closeAll };
}

export function isWindowOpen(view: string) {
  return Boolean(windowFor(view));
}
