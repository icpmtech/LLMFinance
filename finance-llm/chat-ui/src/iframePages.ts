/**
 * Páginas iframe configuráveis pelo utilizador.
 *
 * Permite adicionar, editar e remover aplicações externas que são incorporadas
 * na plataforma através de um `iframe`. Cada entrada vive no `localStorage`
 * e é registada dinamicamente no catálogo do dock e na navegação lateral.
 */
import type { LucideIcon } from "lucide-react";
import {
  AppWindow,
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  Briefcase,
  Building2,
  CalendarClock,
  CandlestickChart,
  Compass,
  Database,
  FileText,
  FolderOpen,
  FolderSearch,
  Gauge,
  GitCompare,
  Globe2,
  Landmark,
  LayoutDashboard,
  Mail,
  MessageSquare,
  Microscope,
  Network,
  Play,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  Telescope,
  TerminalSquare,
  TrendingUp,
  Upload,
  Users,
} from "lucide-react";
import type { DockApp } from "./dock";

export type IframePageConfig = {
  id: string;
  title: string;
  url: string;
  icon: string;
  accent: string;
  gradient: IframeGradientValue;
  enabled: boolean;
  createdAt: string;
};

const STORAGE_KEY = "finance-llm-iframe-pages:v1";
const CHANGE_EVENT = "finance-llm-iframe-pages-changed";

export const IFRAME_VIEW_PREFIX = "iframe:";

/** Catálogo de ícones disponíveis para as páginas iframe. */
export const IFRAME_ICONS: Record<string, LucideIcon> = {
  AppWindow,
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  Briefcase,
  Building2,
  CalendarClock,
  CandlestickChart,
  Compass,
  Database,
  FileText,
  FolderOpen,
  FolderSearch,
  Gauge,
  GitCompare,
  Globe2,
  Landmark,
  LayoutDashboard,
  Mail,
  MessageSquare,
  Microscope,
  Network,
  Play,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  Telescope,
  TerminalSquare,
  TrendingUp,
  Upload,
  Users,
};

export const IFRAME_ICON_NAMES = Object.keys(IFRAME_ICONS);

/** Gradientes pré-definidos para escolha rápida. */
export const IFRAME_GRADIENTS = [
  { value: "from-slate-300 via-slate-500 to-slate-700", label: "Cinzento" },
  { value: "from-zinc-300 via-zinc-500 to-zinc-700", label: "Zinco" },
  { value: "from-neutral-300 via-neutral-500 to-neutral-700", label: "Neutro" },
  { value: "from-stone-300 via-stone-500 to-stone-700", label: "Pedra" },
  { value: "from-red-300 via-red-500 to-red-700", label: "Vermelho" },
  { value: "from-orange-300 via-orange-500 to-orange-700", label: "Laranja" },
  { value: "from-amber-300 via-amber-500 to-amber-700", label: "Âmbar" },
  { value: "from-yellow-300 via-yellow-500 to-yellow-700", label: "Amarelo" },
  { value: "from-lime-300 via-lime-500 to-lime-700", label: "Limão" },
  { value: "from-green-300 via-green-500 to-green-700", label: "Verde" },
  { value: "from-emerald-300 via-emerald-500 to-emerald-700", label: "Esmeralda" },
  { value: "from-teal-300 via-teal-500 to-teal-700", label: "Teal" },
  { value: "from-cyan-300 via-cyan-500 to-cyan-700", label: "Ciano" },
  { value: "from-sky-300 via-sky-500 to-sky-700", label: "Céu" },
  { value: "from-blue-300 via-blue-500 to-blue-700", label: "Azul" },
  { value: "from-indigo-300 via-indigo-500 to-indigo-700", label: "Índigo" },
  { value: "from-violet-300 via-violet-500 to-violet-700", label: "Violeta" },
  { value: "from-purple-300 via-purple-500 to-purple-700", label: "Roxo" },
  { value: "from-fuchsia-300 via-fuchsia-500 to-fuchsia-700", label: "Fúchsia" },
  { value: "from-pink-300 via-pink-500 to-pink-700", label: "Rosa" },
  { value: "from-rose-300 via-rose-500 to-rose-700", label: "Rosa escuro" },
] as const;

export type IframeGradientValue = (typeof IFRAME_GRADIENTS)[number]["value"];

function isValidUrl(value: string): boolean {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function sanitizePage(raw: unknown): IframePageConfig | null {
  if (!raw || typeof raw !== "object") return null;
  const candidate = raw as Partial<IframePageConfig>;
  if (!candidate.id || !candidate.url || !candidate.title) return null;
  const id = String(candidate.id).trim();
  const title = String(candidate.title).trim();
  const url = String(candidate.url).trim();
  if (!id || !title || !isValidUrl(url)) return null;
  return {
    id,
    title,
    url,
    icon: IFRAME_ICON_NAMES.includes(String(candidate.icon)) ? String(candidate.icon) : "Globe2",
    accent: String(candidate.accent || "56,189,248"),
    gradient: String(candidate.gradient || "from-sky-300 via-sky-500 to-sky-700") as IframeGradientValue,
    enabled: candidate.enabled !== false,
    createdAt: String(candidate.createdAt || new Date().toISOString()),
  };
}

function readRaw(): IframePageConfig[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown[];
    if (!Array.isArray(parsed)) return [];
    return parsed.map(sanitizePage).filter((p): p is IframePageConfig => p !== null);
  } catch {
    return [];
  }
}

let cache: IframePageConfig[] = readRaw();

function commit(next: IframePageConfig[]) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Sem persistência: mantém-se em memória.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getIframePages(): IframePageConfig[] {
  return cache;
}

export function saveIframePage(page: Omit<IframePageConfig, "createdAt"> & { createdAt?: string }): IframePageConfig | null {
  const sanitized = sanitizePage({ ...page, createdAt: page.createdAt || new Date().toISOString() });
  if (!sanitized) return null;
  const next = cache.filter((p) => p.id !== sanitized.id);
  next.push(sanitized);
  commit(next);
  return sanitized;
}

export function deleteIframePage(id: string): boolean {
  const next = cache.filter((p) => p.id !== id);
  if (next.length === cache.length) return false;
  commit(next);
  return true;
}

export function reorderIframePages(orderedIds: string[]): void {
  const map = new Map(cache.map((p) => [p.id, p]));
  const next: IframePageConfig[] = [];
  for (const id of orderedIds) {
    const page = map.get(id);
    if (page) next.push(page);
  }
  for (const page of cache) {
    if (!orderedIds.includes(page.id)) next.push(page);
  }
  commit(next);
}

export function subscribeIframePages(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = () => {
    cache = readRaw();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(CHANGE_EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

export function iframePageById(id: string): IframePageConfig | undefined {
  return cache.find((p) => p.id === id);
}

/** Vista (`AppView`) de uma página iframe a partir do id. */
export function iframeViewFor(id: string): string {
  return `${IFRAME_VIEW_PREFIX}${id}`;
}

/** Id da página iframe a partir da vista. */
export function iframeIdFromView(view: string): string | null {
  if (!view.startsWith(IFRAME_VIEW_PREFIX)) return null;
  return view.slice(IFRAME_VIEW_PREFIX.length);
}

export function isIframeView(view: string): boolean {
  return view.startsWith(IFRAME_VIEW_PREFIX);
}

/** Converte uma configuração numa entrada do catálogo do dock. */
export function iframeToDockApp(page: IframePageConfig): DockApp {
  const Icon = IFRAME_ICONS[page.icon] ?? Globe2;
  return {
    id: iframeViewFor(page.id),
    label: page.title,
    hint: page.url,
    icon: Icon,
    gradient: page.gradient,
    accent: page.accent,
  };
}

/** Lista de entradas do dock para as páginas iframe ativas. */
export function iframeDockApps(): DockApp[] {
  return cache.filter((p) => p.enabled).map(iframeToDockApp);
}

/** Caminho URL de uma vista iframe. */
export function iframePathFor(view: string): string | null {
  const id = iframeIdFromView(view);
  if (!id) return null;
  const page = iframePageById(id);
  if (!page) return null;
  return `/iframe/${id}`;
}

/** Vista iframe a partir de um caminho URL. */
export function iframeViewFromPath(path: string): string | null {
  const match = path.match(/^\/iframe\/([^/]+)$/);
  if (!match) return null;
  return iframeViewFor(match[1]);
}
