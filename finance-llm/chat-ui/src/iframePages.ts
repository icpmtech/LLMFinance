/**
 * Páginas iframe configuráveis pelo utilizador.
 *
 * Permite adicionar, editar e remover aplicações externas que são incorporadas
 * na plataforma através de um `iframe`. O estado de verdade vive nas
 * preferências do utilizador (`user.preferences.iframe_pages`) no
 * Elasticsearch; o `localStorage` serve apenas de cache local/offline.
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
import { authApi, type IframePagePreference } from "./authApi";
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
const SAVE_DEBOUNCE_MS = 600;

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

/**
 * Contador de alterações. Serve de *snapshot* estável para
 * `useSyncExternalStore` (uma identidade nova a cada alteração).
 */
let revision = 0;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSave: IframePageConfig[] | null = null;
let saving = false;

function persistLocal(next: IframePageConfig[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Sem persistência: mantém-se em memória.
  }
}

function toPreference(page: IframePageConfig): IframePagePreference {
  return { ...page };
}

async function flushServerSave() {
  if (saving || !pendingSave) return;
  const payload = pendingSave;
  pendingSave = null;
  saving = true;
  try {
    await authApi.updateProfile({ preferences: { iframe_pages: payload.map(toPreference) } });
  } catch (error) {
    // Falha silenciosa: o localStorage já tem a versão mais recente; na próxima
    // abertura o servidor é sincronizado novamente.
    if (typeof console !== "undefined") {
      console.warn("Falha ao guardar páginas iframe no servidor:", error);
    }
  } finally {
    saving = false;
    if (pendingSave) {
      // Houve alterações enquanto salvava: agenda novo flush.
      scheduleServerSave();
    }
  }
}

function scheduleServerSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void flushServerSave();
  }, SAVE_DEBOUNCE_MS);
}

function commit(next: IframePageConfig[], { skipServer = false } = {}) {
  cache = next;
  revision += 1;
  persistLocal(next);
  window.dispatchEvent(new Event(CHANGE_EVENT));
  if (!skipServer) {
    pendingSave = next;
    scheduleServerSave();
  }
}

export function getIframePages(): IframePageConfig[] {
  return cache;
}

/** Versão atual da lista de páginas iframe (para subscrições React). */
export function getIframeRevision(): number {
  return revision;
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
    revision += 1;
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(CHANGE_EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

/** Converte uma vista `iframe:<id>` no id correspondente. */
export function iframeIdFromView(view: string): string | null {
  return view.startsWith(IFRAME_VIEW_PREFIX) ? view.slice(IFRAME_VIEW_PREFIX.length) : null;
}

/** Constrói a vista `iframe:<id>`. */
export function iframeViewFor(id: string): string {
  return `${IFRAME_VIEW_PREFIX}${id}`;
}

/** Procura uma página iframe pelo id. */
export function iframePageById(id: string): IframePageConfig | undefined {
  return cache.find((p) => p.id === id);
}

/** Constrói o caminho da SPA para uma página iframe. */
export function iframePathFor(view: string): string | null {
  const id = iframeIdFromView(view);
  if (!id) return null;
  if (!iframePageById(id)) return null;
  return `/iframe/${id}`;
}

/** Extrai o id de um caminho `/iframe/<id>`. */
export function iframeViewFromPath(path: string): string | null {
  const match = path.match(/^\/iframe\/([^/?#]+)$/);
  if (!match) return null;
  return iframeViewFor(match[1]);
}

export function isIframeView(view: string): boolean {
  return view.startsWith(IFRAME_VIEW_PREFIX);
}

/** Transforma uma página iframe numa aplicação do dock. */
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

/**
 * Sincroniza as páginas iframe vindas do servidor (preferências do utilizador)
 * com o cache local. Chamado pelo `AuthProvider` quando o perfil é carregado.
 */
export function syncIframePagesFromUser(pages: unknown[]): void {
  const sanitized = (Array.isArray(pages) ? pages : [])
    .map(sanitizePage)
    .filter((p): p is IframePageConfig => p !== null);
  const local = readRaw();
  if (JSON.stringify(local) === JSON.stringify(sanitized)) return;
  cache = sanitized;
  revision += 1;
  persistLocal(sanitized);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
