/**
 * Finder da plataforma (estilo macOS).
 *
 * O Finder é um explorador dos dados da plataforma tratados como «ficheiros»:
 * entidades, contratos, documentos, mercados e índices. Tem locais (Recentes,
 * Favoritos, …), quatro vistas (ícones, lista, colunas e galeria), Quick Look,
 * inspetor, etiquetas e barra de caminho.
 *
 * Preferências e itens recentes vivem no `localStorage`
 * (`finance-llm-finder:v1`), partilhados entre separadores.
 */
import { useCallback, useSyncExternalStore } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Building2,
  Clock,
  Database,
  FileText,
  FolderHeart,
  Landmark,
  TrendingUp,
} from "lucide-react";

export type FinderView = "icons" | "list" | "columns" | "gallery";
export type FinderSort = "name" | "kind" | "date" | "size";

export type FinderLocationId =
  | "recents"
  | "favorites"
  | "entities"
  | "contracts"
  | "documents"
  | "tickers"
  | "indices";

export type FinderLocation = {
  id: FinderLocationId;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Cor do ícone (classes de gradiente do Tailwind). */
  gradient: string;
};

export const FINDER_LOCATIONS: FinderLocation[] = [
  { id: "recents", label: "Recentes", hint: "Abertos recentemente", icon: Clock, gradient: "from-sky-300 via-sky-500 to-blue-600" },
  { id: "favorites", label: "Favoritos", hint: "Entidades e contratos guardados", icon: FolderHeart, gradient: "from-rose-300 via-pink-500 to-rose-600" },
  { id: "entities", label: "Entidades", hint: "Diretório de empresas", icon: Building2, gradient: "from-emerald-300 via-emerald-500 to-teal-600" },
  { id: "contracts", label: "Contratos", hint: "Contratação pública", icon: FileText, gradient: "from-amber-200 via-amber-400 to-orange-500" },
  { id: "documents", label: "Documentos", hint: "PDF indexados no RAG", icon: Landmark, gradient: "from-sky-200 via-cyan-400 to-teal-500" },
  { id: "tickers", label: "Mercados", hint: "Tickers indexados", icon: TrendingUp, gradient: "from-rose-200 via-rose-400 to-pink-600" },
  { id: "indices", label: "Índices", hint: "Índices do Elasticsearch", icon: Database, gradient: "from-slate-300 via-slate-500 to-slate-700" },
];

export function finderLocation(id: FinderLocationId): FinderLocation {
  return FINDER_LOCATIONS.find((item) => item.id === id) ?? FINDER_LOCATIONS[0];
}

/** Tipo de «ficheiro» do Finder. */
export type FinderKind = "entity" | "contract" | "document" | "ticker" | "index";

export const KIND_LABEL: Record<FinderKind, string> = {
  entity: "Entidade",
  contract: "Contrato",
  document: "Documento",
  ticker: "Ticker",
  index: "Índice",
};

export type FinderItem = {
  /** Identificador dentro do tipo (NIF, idcontrato, doc_id, símbolo, índice). */
  id: string;
  kind: FinderKind;
  name: string;
  subtitle?: string;
  /** Data em ISO (publicação, criação, ingestão). */
  date?: string;
  /** Número (contratos, páginas, documentos) — coluna «Tamanho». */
  size?: number;
  /** Valor em euros. */
  value?: number;
  /** Etiquetas coloridas (Favorito, Recente, Indexado…). */
  tags?: string[];
  /** Dados originais (alimentam o inspetor e o Quick Look). */
  raw?: unknown;
};

export function itemKey(item: FinderItem): string {
  return `${item.kind}:${item.id}`;
}

export type FinderPrefs = {
  view: FinderView;
  sort: FinderSort;
  ascending: boolean;
  info: boolean;
};

export const DEFAULT_FINDER_PREFS: FinderPrefs = {
  view: "icons",
  sort: "name",
  ascending: true,
  info: false,
};

export type FinderSnapshot = {
  prefs: FinderPrefs;
  /** Itens abertos recentemente (mais recente primeiro). */
  recents: FinderItem[];
};

const STORAGE_KEY = "finance-llm-finder:v1";
const CHANGE_EVENT = "finance-llm-finder-changed";
const RECENTS_LIMIT = 30;

function readSnapshot(): FinderSnapshot {
  const fallback: FinderSnapshot = { prefs: { ...DEFAULT_FINDER_PREFS }, recents: [] };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<FinderSnapshot>;
    const prefs = { ...DEFAULT_FINDER_PREFS, ...(parsed.prefs ?? {}) };
    const recents = Array.isArray(parsed.recents)
      ? parsed.recents.filter((item): item is FinderItem => Boolean(item && typeof item.id === "string" && typeof item.name === "string"))
      : [];
    return { prefs, recents: recents.slice(0, RECENTS_LIMIT) };
  } catch {
    return fallback;
  }
}

let cache: FinderSnapshot = readSnapshot();

function commit(next: FinderSnapshot) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // sem persistência
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getFinderSnapshot(): FinderSnapshot {
  return cache;
}

export function setFinderPrefs(patch: Partial<FinderPrefs>) {
  commit({ ...cache, prefs: { ...cache.prefs, ...patch } });
}

/** Guarda um item em «Recentes» (chamado ao abrir/visualizar). */
export function pushFinderRecent(item: FinderItem) {
  const key = itemKey(item);
  const rest = cache.recents.filter((entry) => itemKey(entry) !== key);
  commit({ ...cache, recents: [item, ...rest].slice(0, RECENTS_LIMIT) });
}

export function clearFinderRecents() {
  commit({ ...cache, recents: [] });
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => { };
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== STORAGE_KEY) return;
    cache = readSnapshot();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Preferências e recentes do Finder. */
export function useFinder() {
  const snapshot = useSyncExternalStore(subscribe, getFinderSnapshot, getFinderSnapshot);
  const setPrefs = useCallback((patch: Partial<FinderPrefs>) => setFinderPrefs(patch), []);
  const clearRecents = useCallback(() => clearFinderRecents(), []);
  return { ...snapshot, setPrefs, clearRecents };
}

/** Ordenação das vistas de lista/ícones (como «Organizar por» do Finder). */
export function sortFinderItems(items: FinderItem[], sort: FinderSort, ascending: boolean): FinderItem[] {
  const direction = ascending ? 1 : -1;
  const collator = new Intl.Collator("pt-PT", { numeric: true, sensitivity: "base" });
  return [...items].sort((a, b) => {
    if (sort === "kind") {
      const kindDiff = collator.compare(KIND_LABEL[a.kind], KIND_LABEL[b.kind]) * direction;
      if (kindDiff !== 0) return kindDiff;
    } else if (sort === "date") {
      const left = a.date ? Date.parse(a.date) : 0;
      const right = b.date ? Date.parse(b.date) : 0;
      if (left !== right) return (left - right) * direction;
    } else if (sort === "size") {
      const left = (a.size ?? 0) || (a.value ?? 0);
      const right = (b.size ?? 0) || (b.value ?? 0);
      if (left !== right) return (left - right) * direction;
    }
    return collator.compare(a.name, b.name) * direction;
  });
}

/** Data legível (curta, como a coluna «Data de modificação»). */
export function formatFinderDate(value?: string): string {
  if (!value) return "—";
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return "—";
  return new Date(ms).toLocaleDateString("pt-PT", { day: "2-digit", month: "short", year: "numeric" });
}

/** Valor monetário compacto (€). */
export function formatFinderValue(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil €`;
  return `${value.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

/** «Tamanho» do item: nº de contratos/páginas/documentos ou o valor. */
export function formatFinderSize(item: FinderItem): string {
  if (typeof item.size === "number" && item.size > 0) return item.size.toLocaleString("pt-PT");
  if (typeof item.value === "number" && item.value > 0) return formatFinderValue(item.value);
  return "—";
}

/** Deep link da aplicação onde o item vive (`/companies/<NIF>`, `/tickers/<símbolo>`, …). */
export function appHref(item: FinderItem): string {
  if (item.kind === "entity") return `/companies/${encodeURIComponent(item.id)}`;
  if (item.kind === "contract") return "/empresas-iq";
  if (item.kind === "document") return "/rag";
  if (item.kind === "ticker") return `/tickers/${encodeURIComponent(item.id)}`;
  return "/elastic";
}

/** Cor da etiqueta (como as etiquetas coloridas do Finder). */
export function tagColor(tag: string): string {
  const key = tag.toLowerCase();
  if (key === "favorito") return "bg-rose-400";
  if (key === "recente") return "bg-sky-400";
  if (key === "indexado") return "bg-teal-400";
  if (key === "arquivado") return "bg-slate-400";
  return "bg-amber-400";
}
