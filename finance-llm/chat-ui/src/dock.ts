/**
 * Dock estilo macOS da plataforma FinanceLLM.
 *
 * O dock é uma barra de ícones fixa (em baixo, à esquerda ou à direita) com
 * ampliação ao passar o rato, etiquetas, indicadores de aplicações abertas e
 * arrumação/reordenação dos ícones.
 *
 * Toda a configuração (posição, tamanho, ampliação, auto-ocultar, ordem dos
 * ícones e ícones escondidos) vive no `localStorage`, partilhada entre
 * separadores, tal como o resto do estado do EmpresasIQ.
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Building2,
  CandlestickChart,
  Database,
  FileText,
  FolderOpen,
  LayoutDashboard,
  MessageSquare,
  Network,
  Search,
  Settings,
  Sparkles,
  TrendingUp,
  Upload,
} from "lucide-react";

export type DockPosition = "bottom" | "left" | "right";

export type DockApp = {
  /** Identificador da vista da aplicação (`AppView`). */
  id: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Gradiente do tile (classes Tailwind). */
  gradient: string;
  /** Cor do brilho/realce do tile, em `r,g,b`. */
  accent: string;
};

/** Catálogo de aplicações que podem entrar no dock. */
export const DOCK_CATALOG: DockApp[] = [
  {
    id: "chat",
    label: "Chat IA",
    hint: "Conversar com os modelos",
    icon: MessageSquare,
    gradient: "from-teal-300 via-teal-500 to-emerald-600",
    accent: "16,163,127",
  },
  {
    id: "empresas-iq",
    label: "EmpresasIQ",
    hint: "Inteligência contratual",
    icon: Network,
    gradient: "from-cyan-300 via-sky-500 to-blue-600",
    accent: "14,165,233",
  },
  {
    id: "dashboard",
    label: "Dashboard",
    hint: "Visão geral da plataforma",
    icon: LayoutDashboard,
    gradient: "from-indigo-300 via-indigo-500 to-violet-600",
    accent: "99,102,241",
  },
  {
    id: "search",
    label: "Pesquisa Global",
    hint: "Procurar em todas as fontes",
    icon: Search,
    gradient: "from-slate-200 via-slate-400 to-slate-600",
    accent: "148,163,184",
  },
  {
    id: "contracts-search",
    label: "Contratos",
    hint: "Pesquisar contratos públicos",
    icon: FileText,
    gradient: "from-amber-200 via-amber-400 to-orange-500",
    accent: "245,158,11",
  },
  {
    id: "contracts-dashboard",
    label: "Análise de Contratos",
    hint: "Indicadores de contratação pública",
    icon: BarChart3,
    gradient: "from-orange-200 via-orange-400 to-rose-500",
    accent: "249,115,22",
  },
  {
    id: "entities-search",
    label: "Empresas",
    hint: "Diretório e fichas de empresas",
    icon: Building2,
    gradient: "from-emerald-200 via-emerald-400 to-teal-600",
    accent: "16,185,129",
  },
  {
    id: "tickers",
    label: "Mercados",
    hint: "Tickers e ações",
    icon: TrendingUp,
    gradient: "from-rose-200 via-rose-400 to-pink-600",
    accent: "244,63,94",
  },
  {
    id: "forecast",
    label: "Previsões",
    hint: "Modelos de previsão",
    icon: Sparkles,
    gradient: "from-fuchsia-300 via-purple-500 to-indigo-600",
    accent: "192,132,252",
  },
  {
    id: "trading",
    label: "Trading",
    hint: "Simulador de trading",
    icon: CandlestickChart,
    gradient: "from-lime-200 via-green-500 to-emerald-700",
    accent: "34,197,94",
  },
  {
    id: "rag",
    label: "RAG",
    hint: "Documentos e recuperação aumentada",
    icon: FolderOpen,
    gradient: "from-sky-200 via-cyan-400 to-teal-500",
    accent: "34,211,238",
  },
  {
    id: "elastic",
    label: "Elasticsearch",
    hint: "Explorar índices e documentos",
    icon: Database,
    gradient: "from-yellow-200 via-yellow-400 to-amber-600",
    accent: "250,204,21",
  },
  {
    id: "import",
    label: "Importar",
    hint: "Carregar dados para a plataforma",
    icon: Upload,
    gradient: "from-zinc-200 via-zinc-400 to-zinc-600",
    accent: "161,161,170",
  },
  {
    id: "settings",
    label: "Definições",
    hint: "Conta, perfil e preferências",
    icon: Settings,
    gradient: "from-slate-300 via-slate-500 to-slate-700",
    accent: "148,163,184",
  },
];

/** Ícones visíveis por defeito (a ordem é a ordem no dock). */
const DEFAULT_ITEMS = [
  "chat",
  "empresas-iq",
  "dashboard",
  "search",
  "contracts-search",
  "contracts-dashboard",
  "entities-search",
  "tickers",
  "forecast",
  "trading",
  "rag",
  "settings",
];

/** Ícones fora do dock por defeito (disponíveis para adicionar). */
const DEFAULT_PARKED = ["elastic", "import"];

export type DockPrefs = {
  position: DockPosition;
  /** Lado do ícone em repouso, em px. */
  iconSize: number;
  magnification: boolean;
  /** Ampliação máxima do ícone sob o cursor (1 = sem ampliação). */
  magnify: number;
  /** Distância de influência da ampliação, em múltiplos do tamanho do ícone. */
  magnifySpread: number;
  autoHide: boolean;
  tooltips: boolean;
  indicators: boolean;
  /** Reflexo/brilho sob os ícones. */
  reflection: boolean;
  /** Ícones visíveis, pela ordem apresentada. */
  items: string[];
  /** Ícones removidos do dock. */
  parked: string[];
};

const STORAGE_KEY = "finance-llm-dock:v1";
const CHANGE_EVENT = "finance-llm-dock-changed";

export const ICON_SIZE_RANGE = { min: 38, max: 84 } as const;
export const MAGNIFY_RANGE = { min: 1.15, max: 2.2 } as const;
export const SPREAD_RANGE = { min: 1, max: 4 } as const;

export const DEFAULT_DOCK_PREFS: DockPrefs = {
  position: "bottom",
  iconSize: 52,
  magnification: true,
  magnify: 1.75,
  magnifySpread: 2.2,
  autoHide: false,
  tooltips: true,
  indicators: true,
  reflection: true,
  items: DEFAULT_ITEMS,
  parked: DEFAULT_PARKED,
};

const CATALOG_IDS = DOCK_CATALOG.map((app) => app.id);

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function asNumber(value: unknown, fallback: number, min: number, max: number) {
  return typeof value === "number" && Number.isFinite(value) ? clamp(value, min, max) : fallback;
}

function asIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const entry of value) {
    if (typeof entry !== "string") continue;
    if (!CATALOG_IDS.includes(entry) || seen.has(entry)) continue;
    seen.add(entry);
    ids.push(entry);
  }
  return ids;
}

function sanitize(raw: Partial<DockPrefs> | null): DockPrefs {
  const items = asIds(raw?.items);
  const parked = asIds(raw?.parked).filter((id) => !items.includes(id));

  // Aplicações novas no catálogo entram automaticamente no dock, no fim,
  // exceto se o utilizador já as tiver removido.
  const known = new Set([...items, ...parked]);
  const newcomers = CATALOG_IDS.filter((id) => !known.has(id) && !DEFAULT_PARKED.includes(id));

  return {
    position:
      raw?.position === "left" || raw?.position === "right" || raw?.position === "bottom"
        ? raw.position
        : DEFAULT_DOCK_PREFS.position,
    iconSize: Math.round(
      asNumber(raw?.iconSize, DEFAULT_DOCK_PREFS.iconSize, ICON_SIZE_RANGE.min, ICON_SIZE_RANGE.max)
    ),
    magnification: typeof raw?.magnification === "boolean" ? raw.magnification : DEFAULT_DOCK_PREFS.magnification,
    magnify: asNumber(raw?.magnify, DEFAULT_DOCK_PREFS.magnify, MAGNIFY_RANGE.min, MAGNIFY_RANGE.max),
    magnifySpread: asNumber(
      raw?.magnifySpread,
      DEFAULT_DOCK_PREFS.magnifySpread,
      SPREAD_RANGE.min,
      SPREAD_RANGE.max
    ),
    autoHide: typeof raw?.autoHide === "boolean" ? raw.autoHide : DEFAULT_DOCK_PREFS.autoHide,
    tooltips: typeof raw?.tooltips === "boolean" ? raw.tooltips : DEFAULT_DOCK_PREFS.tooltips,
    indicators: typeof raw?.indicators === "boolean" ? raw.indicators : DEFAULT_DOCK_PREFS.indicators,
    reflection: typeof raw?.reflection === "boolean" ? raw.reflection : DEFAULT_DOCK_PREFS.reflection,
    items: items.length ? [...items, ...newcomers] : DEFAULT_DOCK_PREFS.items,
    parked,
  };
}

function read(): DockPrefs {
  if (typeof window === "undefined") return DEFAULT_DOCK_PREFS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_DOCK_PREFS;
    return sanitize(JSON.parse(raw) as Partial<DockPrefs> | null);
  } catch {
    return DEFAULT_DOCK_PREFS;
  }
}

let cache: DockPrefs = read();

function commit(next: DockPrefs) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Modo privado ou sem espaço: mantém-se apenas em memória.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getDockPrefs(): DockPrefs {
  return cache;
}

export function updateDockPrefs(patch: Partial<DockPrefs>) {
  commit(sanitize({ ...cache, ...patch }));
}

export function resetDockPrefs() {
  commit({ ...DEFAULT_DOCK_PREFS });
}

/** Move um ícone do dock para outra posição. */
export function moveDockItem(from: number, to: number) {
  const items = [...cache.items];
  if (from < 0 || from >= items.length) return;
  const target = clamp(to, 0, items.length - 1);
  if (from === target) return;
  const [moved] = items.splice(from, 1);
  items.splice(target, 0, moved);
  commit({ ...cache, items });
}

/** Retira um ícone do dock (fica disponível para voltar a adicionar). */
export function parkDockItem(id: string) {
  if (!cache.items.includes(id)) return;
  commit({
    ...cache,
    items: cache.items.filter((item) => item !== id),
    parked: [...cache.parked, id],
  });
}

/** Devolve um ícone ao dock (no fim, ou numa posição concreta). */
export function unparkDockItem(id: string, index?: number) {
  if (cache.items.includes(id)) return;
  const items = [...cache.items];
  const position = typeof index === "number" ? clamp(index, 0, items.length) : items.length;
  items.splice(position, 0, id);
  commit({ ...cache, items, parked: cache.parked.filter((item) => item !== id) });
}

export function isDockItemVisible(id: string) {
  return cache.items.includes(id);
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

/** Configuração do dock e operações, com persistência automática. */
export function useDock() {
  const prefs = useSyncExternalStore(subscribe, getDockPrefs, getDockPrefs);

  const visible = useMemo(
    () => prefs.items.map((id) => DOCK_CATALOG.find((app) => app.id === id)).filter((app): app is DockApp => Boolean(app)),
    [prefs.items]
  );

  const parked = useMemo(
    () => prefs.parked.map((id) => DOCK_CATALOG.find((app) => app.id === id)).filter((app): app is DockApp => Boolean(app)),
    [prefs.parked]
  );

  const set = useCallback((patch: Partial<DockPrefs>) => updateDockPrefs(patch), []);

  const move = useCallback((from: number, to: number) => moveDockItem(from, to), []);
  const park = useCallback((id: string) => parkDockItem(id), []);
  const unpark = useCallback((id: string, index?: number) => unparkDockItem(id, index), []);
  const reset = useCallback(() => resetDockPrefs(), []);

  return { prefs, visible, parked, set, move, park, unpark, reset };
}

export function dockApp(id: string): DockApp | undefined {
  return DOCK_CATALOG.find((app) => app.id === id);
}

/**
 * Espaço a reservar no conteúdo para o dock não tapar o fim das páginas.
 * `bottom` aplica-se à área de conteúdo; `sides` à moldura exterior (para o
 * dock lateral não tapar a barra de navegação).
 */
export function useDockSpacer() {
  const prefs = useSyncExternalStore(subscribe, getDockPrefs, getDockPrefs);
  if (prefs.autoHide) return { bottom: "", sides: "" };
  if (prefs.position === "bottom") return { bottom: "pb-[112px]", sides: "" };
  if (prefs.position === "left") return { bottom: "", sides: "pl-[104px]" };
  return { bottom: "", sides: "pr-[104px]" };
}
