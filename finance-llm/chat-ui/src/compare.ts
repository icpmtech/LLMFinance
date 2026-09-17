/**
 * Comparação de entidades (adjudicantes/adjudicatários) e contratos.
 *
 * A seleção vive num store próprio (`finance-llm-compare:v1`), partilhado entre
 * separadores, e abre numa janela do gestor (`compare`). O Finder, as fichas e a
 * própria janela de comparação podem acrescentar/remover itens.
 */
import { useCallback, useSyncExternalStore } from "react";
import { openWindow, windowFor } from "./windows";

export type CompareKind = "entity" | "contract";

export type CompareItem = {
  kind: CompareKind;
  id: string;
  name: string;
  subtitle?: string;
};

/** Limite de itens comparados ao mesmo tempo (a tabela tem de caber). */
export const MAX_COMPARE = 4;

const STORAGE_KEY = "finance-llm-compare:v1";
const CHANGE_EVENT = "finance-llm-compare-changed";

export function compareKey(item: { kind: CompareKind; id: string }): string {
  return `${item.kind}:${item.id}`;
}

/** Itens da mesma espécie (não se comparam contratos com entidades). */
function kindOf(list: CompareItem[]): CompareKind | null {
  return list.length > 0 ? list[0].kind : null;
}

function read(): CompareItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((entry): entry is CompareItem => {
        const candidate = entry as Partial<CompareItem> | null;
        return Boolean(
          candidate &&
            (candidate.kind === "entity" || candidate.kind === "contract") &&
            typeof candidate.id === "string" &&
            typeof candidate.name === "string",
        );
      })
      .slice(0, MAX_COMPARE);
  } catch {
    return [];
  }
}

let cache: CompareItem[] = read();

function commit(next: CompareItem[]) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // sem persistência
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => { };
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

export function getCompareItems(): CompareItem[] {
  return cache;
}

/** Acrescenta itens (substitui a seleção se mudar de espécie). */
export function addToCompare(incoming: CompareItem[]) {
  if (incoming.length === 0) return;
  const wanted = incoming[0].kind;
  const base = kindOf(cache) === wanted ? cache : [];
  const seen = new Set(base.map(compareKey));
  const next = [...base];
  for (const item of incoming) {
    const key = compareKey(item);
    if (key === undefined || seen.has(key)) continue;
    seen.add(key);
    next.push(item);
  }
  commit(next.slice(0, MAX_COMPARE));
}

export function removeFromCompare(kind: CompareKind, id: string) {
  commit(cache.filter((item) => !(item.kind === kind && item.id === id)));
}

export function toggleCompare(item: CompareItem) {
  const exists = cache.some((entry) => compareKey(entry) === compareKey(item));
  if (exists) removeFromCompare(item.kind, item.id);
  else addToCompare([item]);
}

export function clearCompare() {
  if (cache.length === 0) return;
  commit([]);
}

/** Abre (ou foca) a janela de comparação. */
export function openCompareWindow() {
  openWindow("compare", undefined, {
    title: "Comparar",
    rect: { width: 1120, height: 720 },
  });
  return windowFor("compare");
}

export function useCompare() {
  const items = useSyncExternalStore(subscribe, getCompareItems, getCompareItems);
  const add = useCallback((incoming: CompareItem[]) => addToCompare(incoming), []);
  const toggle = useCallback((item: CompareItem) => toggleCompare(item), []);
  const remove = useCallback((kind: CompareKind, id: string) => removeFromCompare(kind, id), []);
  const clear = useCallback(() => clearCompare(), []);
  return {
    items,
    kind: kindOf(items),
    add,
    toggle,
    remove,
    clear,
    has: (item: { kind: CompareKind; id: string }) => items.some((entry) => compareKey(entry) === compareKey(item)),
    full: items.length >= MAX_COMPARE,
  };
}
