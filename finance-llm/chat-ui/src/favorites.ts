/**
 * Favoritos do EmpresasIQ.
 *
 * Fonte de verdade: Elasticsearch (índice `finance_user_state`, via `/favorites`).
 * O `localStorage` fica como cache local — serve de primeira pintura instantânea e
 * permite migrar favoritos antigos que só existiam no browser.
 *
 * Motivo: o `localStorage` está preso à origem (localhost vs 127.0.0.1, portas, modo
 * privado), pelo que os favoritos "desapareciam" ao recarregar noutro contexto.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  clearFavoritesRequest,
  deleteFavoriteRequest,
  fetchFavorites,
  saveFavoriteRequest,
  type FavoriteEntry,
  type FavoriteKind,
  type FavoriteParty,
} from "./userStateApi";

export type { FavoriteKind, FavoriteParty };

export type Favorite = FavoriteEntry & { addedAt: string };

const STORAGE_KEY = "empresasiq:favorites:v1";
const CHANGE_EVENT = "empresasiq:favorites-changed";

function sortFavorites(items: Favorite[]) {
  return [...items].sort((a, b) => (a.addedAt < b.addedAt ? 1 : a.addedAt > b.addedAt ? -1 : 0));
}

function toRequest(entry: Favorite) {
  return {
    kind: entry.kind,
    id: entry.id,
    label: entry.label,
    sublabel: entry.sublabel,
    value: entry.value ?? null,
    parties: entry.parties ?? [],
  } satisfies FavoriteEntry;
}

/** Normaliza o que vem da API (`added_at`) para o formato usado na UI. */
function fromApi(item: FavoriteEntry & { added_at?: string }): Favorite {
  return {
    kind: item.kind,
    id: item.id,
    label: item.label,
    sublabel: item.sublabel ?? undefined,
    value: item.value ?? null,
    parties: item.parties ?? [],
    addedAt: item.addedAt ?? item.added_at ?? new Date().toISOString(),
  };
}

function read(): Favorite[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return sortFavorites(
      parsed
        .filter((item): item is Favorite => {
          const candidate = item as Partial<Favorite> | null;
          return Boolean(
            candidate &&
              (candidate.kind === "entity" || candidate.kind === "contract") &&
              typeof candidate.id === "string" &&
              typeof candidate.label === "string"
          );
        })
        .map((item) => ({ ...item, addedAt: typeof item.addedAt === "string" ? item.addedAt : new Date().toISOString() }))
    );
  } catch {
    return [];
  }
}

let cache: Favorite[] = read();
let hydrated = false;
let hydration: Promise<void> | null = null;
let lastError: string | null = null;

function emit() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}

function persistLocal() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Sem espaço ou modo privado: mantém-se em memória para a sessão.
  }
}

function commit(next: Favorite[]) {
  cache = sortFavorites(next);
  persistLocal();
  emit();
}

function fail(action: string, error: unknown) {
  lastError = error instanceof Error ? error.message : String(error);
  console.warn(`[favoritos] ${action}: ${lastError}`);
}

/**
 * Carrega os favoritos do Elasticsearch. Se o índice ainda estiver vazio mas houver
 * favoritos no browser, envia-os (migração automática) em vez de os perder.
 */
export function hydrateFavorites(force = false): Promise<void> {
  if (hydration && !force) return hydration;
  hydration = (async () => {
    try {
      const remote = (await fetchFavorites()).map((item) => fromApi(item as FavoriteEntry & { added_at?: string }));
      if (remote.length === 0 && cache.length > 0) {
        await Promise.all(cache.map((entry) => saveFavoriteRequest(toRequest(entry)).catch(() => undefined)));
      } else {
        commit(remote);
      }
      lastError = null;
      hydrated = true;
    } catch (error) {
      fail("não foi possível carregar do Elasticsearch", error);
    }
  })();
  return hydration;
}

export function isFavoritesHydrated() {
  return hydrated;
}

export function getFavoritesError() {
  return lastError;
}

/** Instantâneo estável para o `useSyncExternalStore` (só muda quando há alterações). */
export function listFavorites(): Favorite[] {
  return cache;
}

export function findFavorite(kind: FavoriteKind, id: string): Favorite | undefined {
  return cache.find((item) => item.kind === kind && item.id === id);
}

export function isFavorite(kind: FavoriteKind, id: string): boolean {
  return Boolean(findFavorite(kind, id));
}

/** Alterna o favorito e devolve `true` se o item ficou marcado. */
export function toggleFavorite(entry: Omit<Favorite, "addedAt">): boolean {
  const exists = isFavorite(entry.kind, entry.id);
  if (exists) {
    commit(cache.filter((item) => !(item.kind === entry.kind && item.id === entry.id)));
    void deleteFavoriteRequest(entry.kind, entry.id).catch((error) => fail("remover no Elasticsearch", error));
    return false;
  }
  const record: Favorite = { ...entry, addedAt: new Date().toISOString() };
  commit([...cache, record]);
  void saveFavoriteRequest(toRequest(record)).catch((error) => fail("guardar no Elasticsearch", error));
  return true;
}

export function removeFavorite(kind: FavoriteKind, id: string) {
  if (!isFavorite(kind, id)) return;
  commit(cache.filter((item) => !(item.kind === kind && item.id === id)));
  void deleteFavoriteRequest(kind, id).catch((error) => fail("remover no Elasticsearch", error));
}

export function clearFavorites() {
  if (cache.length === 0) return;
  commit([]);
  void clearFavoritesRequest().catch((error) => fail("limpar no Elasticsearch", error));
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

export function useFavorites() {
  const favorites = useSyncExternalStore(subscribe, listFavorites, listFavorites);

  // Carrega do Elasticsearch uma vez por sessão (o cache local serve de primeira pintura).
  useEffect(() => {
    void hydrateFavorites();
  }, []);

  const toggle = useCallback((entry: Omit<Favorite, "addedAt">) => toggleFavorite(entry), []);
  const remove = useCallback((kind: FavoriteKind, id: string) => removeFavorite(kind, id), []);
  return {
    favorites,
    entities: favorites.filter((item) => item.kind === "entity"),
    contracts: favorites.filter((item) => item.kind === "contract"),
    isFavorite,
    toggle,
    remove,
    clear: clearFavorites,
  };
}
