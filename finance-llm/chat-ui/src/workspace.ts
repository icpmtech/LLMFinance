/**
 * Espaço de trabalho do EmpresasIQ: histórico de consultas e pastas (dossier).
 *
 * - Histórico: entidades e contratos abertos recentemente (mais recentes primeiro).
 * - Pastas: agrupam fichas de entidades/contratos num dossier para análise, revisão
 *   e construção de grafos de visualização.
 *
 * Fonte de verdade: Elasticsearch (`finance_user_state` via `/workspace`). O
 * `localStorage` fica como cache local (primeira pintura + migração do que existia
 * apenas no browser).
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { FavoriteEntry, FavoriteKind } from "./userStateApi";
import {
  deleteFolderRequest,
  fetchWorkspace,
  saveFolderRequest,
  saveHistoryRequest,
} from "./userStateApi";

export type WorkspaceEntryKind = FavoriteKind;

export type WorkspaceEntry = FavoriteEntry & { seenAt: string };

export type WorkspaceFolder = {
  id: string;
  name: string;
  createdAt: string;
  items: WorkspaceEntry[];
};

type WorkspaceState = {
  history: WorkspaceEntry[];
  folders: WorkspaceFolder[];
};

const STORAGE_KEY = "empresasiq:workspace:v1";
const CHANGE_EVENT = "empresasiq:workspace-changed";
const HISTORY_LIMIT = 40;

const EMPTY: WorkspaceState = { history: [], folders: [] };

function uid(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function isKind(value: unknown): value is WorkspaceEntryKind {
  return value === "entity" || value === "contract";
}

function sanitizeEntry(value: unknown): WorkspaceEntry | null {
  const candidate = value as Partial<WorkspaceEntry> | null;
  if (!candidate || !isKind(candidate.kind) || typeof candidate.id !== "string" || typeof candidate.label !== "string") {
    return null;
  }
  return {
    kind: candidate.kind,
    id: candidate.id,
    label: candidate.label,
    sublabel: typeof candidate.sublabel === "string" ? candidate.sublabel : undefined,
    value: typeof candidate.value === "number" ? candidate.value : null,
    parties: Array.isArray(candidate.parties)
      ? candidate.parties
          .map((party): { nif: string; label: string; role?: string } | null => {
            const item = party as { nif?: unknown; label?: unknown; role?: unknown } | null;
            if (!item || typeof item.nif !== "string" || typeof item.label !== "string") return null;
            return { nif: item.nif, label: item.label, role: typeof item.role === "string" ? item.role : undefined };
          })
          .filter((party): party is { nif: string; label: string; role?: string } => party !== null)
      : undefined,
    seenAt: typeof candidate.seenAt === "string" ? candidate.seenAt : new Date().toISOString(),
  };
}

/** Normaliza entradas vindas da API (`seen_at`/`added_at` → `seenAt`). */
function fromApiEntry(value: unknown): WorkspaceEntry | null {
  const candidate = value as (Partial<WorkspaceEntry> & { seen_at?: string; added_at?: string }) | null;
  if (!candidate) return null;
  const seenAt = candidate.seenAt ?? candidate.seen_at ?? candidate.added_at ?? new Date().toISOString();
  return sanitizeEntry({ ...candidate, seenAt });
}

function read(): WorkspaceState {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<WorkspaceState> | null;
    const history = Array.isArray(parsed?.history)
      ? parsed!.history.map(sanitizeEntry).filter((item): item is WorkspaceEntry => Boolean(item))
      : [];
    const folders = Array.isArray(parsed?.folders)
      ? parsed!.folders
          .map((folder) => {
            const candidate = folder as Partial<WorkspaceFolder> | null;
            if (!candidate || typeof candidate.id !== "string" || typeof candidate.name !== "string") return null;
            return {
              id: candidate.id,
              name: candidate.name,
              createdAt: typeof candidate.createdAt === "string" ? candidate.createdAt : new Date().toISOString(),
              items: Array.isArray(candidate.items)
                ? candidate.items.map(sanitizeEntry).filter((item): item is WorkspaceEntry => Boolean(item))
                : [],
            } satisfies WorkspaceFolder;
          })
          .filter((folder): folder is WorkspaceFolder => Boolean(folder))
      : [];
    return { history, folders };
  } catch {
    return EMPTY;
  }
}

let cache: WorkspaceState = read();
let hydrated = false;
let hydration: Promise<void> | null = null;

function emit() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}

function persistLocal() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Sem espaço ou modo privado: fica apenas em memória nesta sessão.
  }
}

function commit(next: WorkspaceState) {
  cache = next;
  persistLocal();
  emit();
}

function fail(action: string, error: unknown) {
  console.warn(`[dossier] ${action}: ${error instanceof Error ? error.message : String(error)}`);
}

function toApiEntry(entry: WorkspaceEntry) {
  return { ...entry, seenAt: entry.seenAt } satisfies FavoriteEntry & { seenAt: string };
}

/** Carrega o dossier do Elasticsearch (migrando o que existir apenas no browser). */
export function hydrateWorkspace(force = false): Promise<void> {
  if (hydration && !force) return hydration;
  hydration = (async () => {
    try {
      const remote = await fetchWorkspace();
      const folders: WorkspaceFolder[] = (remote.folders ?? []).map((folder) => ({
        id: folder.id,
        name: folder.name,
        createdAt: folder.createdAt ?? new Date().toISOString(),
        items: (folder.items ?? []).map(fromApiEntry).filter((item): item is WorkspaceEntry => Boolean(item)),
      }));
      const history = (remote.history ?? []).map(fromApiEntry).filter((item): item is WorkspaceEntry => Boolean(item));

      const emptyRemote = folders.length === 0 && history.length === 0;
      const hasLocal = cache.folders.length > 0 || cache.history.length > 0;

      if (emptyRemote && hasLocal) {
        // Migração: envia o estado local para o Elasticsearch em vez de o perder.
        await Promise.all(cache.folders.map((folder) => saveFolderRequest(folder).catch(() => undefined)));
        if (cache.history.length > 0) {
          await saveHistoryRequest(cache.history.map(toApiEntry)).catch(() => undefined);
        }
      } else {
        commit({ folders, history });
      }
      hydrated = true;
    } catch (error) {
      fail("não foi possível carregar do Elasticsearch", error);
    }
  })();
  return hydration;
}

export function isWorkspaceHydrated() {
  return hydrated;
}

export function getWorkspace(): WorkspaceState {
  return cache;
}

function sameKey(a: { kind: WorkspaceEntryKind; id: string }, b: { kind: WorkspaceEntryKind; id: string }) {
  return a.kind === b.kind && a.id === b.id;
}

function syncHistory() {
  void saveHistoryRequest(cache.history.map(toApiEntry)).catch((error) => fail("guardar histórico", error));
}

function syncFolder(folderId: string) {
  const folder = cache.folders.find((item) => item.id === folderId);
  if (!folder) return;
  void saveFolderRequest(folder).catch((error) => fail("guardar pasta", error));
}

/** Regista a abertura de uma ficha (mais recente primeiro, sem duplicados). */
export function recordVisit(entry: Omit<WorkspaceEntry, "seenAt">) {
  const seenAt = new Date().toISOString();
  const record: WorkspaceEntry = { ...entry, seenAt };
  const history = [record, ...cache.history.filter((item) => !sameKey(item, record))].slice(0, HISTORY_LIMIT);
  // Mantém o dossier coerente: o que já está numa pasta é atualizado com a etiqueta mais recente.
  const folders = cache.folders.map((folder) =>
    folder.items.some((item) => sameKey(item, record))
      ? {
          ...folder,
          items: folder.items.map((item) =>
            sameKey(item, record)
              ? {
                  ...item,
                  label: record.label,
                  sublabel: record.sublabel ?? item.sublabel,
                  value: record.value ?? item.value,
                  seenAt,
                }
              : item
          ),
        }
      : folder
  );
  commit({ history, folders });
  syncHistory();
  folders
    .filter((folder) => folder.items.some((item) => sameKey(item, record)))
    .forEach((folder) => syncFolder(folder.id));
}

export function clearHistory() {
  if (cache.history.length === 0) return;
  commit({ ...cache, history: [] });
  syncHistory();
}

export function createFolder(name: string) {
  const trimmed = name.trim();
  if (!trimmed) return null;
  const folder: WorkspaceFolder = { id: uid("pasta"), name: trimmed, createdAt: new Date().toISOString(), items: [] };
  commit({ ...cache, folders: [...cache.folders, folder] });
  syncFolder(folder.id);
  return folder.id;
}

export function renameFolder(folderId: string, name: string) {
  const trimmed = name.trim();
  if (!trimmed) return;
  const current = cache.folders.find((folder) => folder.id === folderId);
  if (!current || current.name === trimmed) return;
  commit({
    ...cache,
    folders: cache.folders.map((folder) => (folder.id === folderId ? { ...folder, name: trimmed } : folder)),
  });
  syncFolder(folderId);
}

export function deleteFolder(folderId: string) {
  commit({ ...cache, folders: cache.folders.filter((folder) => folder.id !== folderId) });
  void deleteFolderRequest(folderId).catch((error) => fail("apagar pasta", error));
}

/** Guarda uma ficha numa pasta (idempotente). */
export function addToFolder(folderId: string, entry: Omit<WorkspaceEntry, "seenAt">) {
  const seenAt = new Date().toISOString();
  commit({
    ...cache,
    folders: cache.folders.map((folder) =>
      folder.id === folderId
        ? folder.items.some((item) => sameKey(item, entry))
          ? folder
          : { ...folder, items: [{ ...entry, seenAt }, ...folder.items] }
        : folder
    ),
  });
  syncFolder(folderId);
}

export function removeFromFolder(folderId: string, entry: { kind: WorkspaceEntryKind; id: string }) {
  commit({
    ...cache,
    folders: cache.folders.map((folder) =>
      folder.id === folderId ? { ...folder, items: folder.items.filter((item) => !sameKey(item, entry)) } : folder
    ),
  });
  syncFolder(folderId);
}

/** Pasta que contém a ficha, se existir (para mostrar o estado no menu de guardar). */
export function folderIdsContaining(entry: { kind: WorkspaceEntryKind; id: string }) {
  return cache.folders.filter((folder) => folder.items.some((item) => sameKey(item, entry))).map((folder) => folder.id);
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

export function useWorkspace() {
  const state = useSyncExternalStore(subscribe, getWorkspace, getWorkspace);

  useEffect(() => {
    void hydrateWorkspace();
  }, []);

  const create = useCallback((name: string) => createFolder(name), []);
  const rename = useCallback((folderId: string, name: string) => renameFolder(folderId, name), []);
  const remove = useCallback((folderId: string) => deleteFolder(folderId), []);
  const add = useCallback((folderId: string, entry: Omit<WorkspaceEntry, "seenAt">) => addToFolder(folderId, entry), []);
  const drop = useCallback(
    (folderId: string, entry: { kind: WorkspaceEntryKind; id: string }) => removeFromFolder(folderId, entry),
    []
  );
  const record = useCallback((entry: Omit<WorkspaceEntry, "seenAt">) => recordVisit(entry), []);
  return {
    history: state.history,
    folders: state.folders,
    createFolder: create,
    renameFolder: rename,
    deleteFolder: remove,
    addToFolder: add,
    removeFromFolder: drop,
    recordVisit: record,
    clearHistory,
  };
}

/** Empresas distintas presentes num conjunto de fichas (entidades e partes de contratos). */
export function companiesIn(entries: WorkspaceEntry[]) {
  const map = new Map<string, { nif: string; label: string; role?: string; value: number; seenAt: string }>();
  const register = (nif: string, label: string, role: string | undefined, value: number, seenAt: string) => {
    const current = map.get(nif);
    if (!current) {
      map.set(nif, { nif, label, role, value, seenAt });
      return;
    }
    // Guarda o valor mais alto visto (dá contexto no cartão) e a etiqueta mais recente.
    if (value > current.value) current.value = value;
    if (seenAt > current.seenAt) {
      current.label = label;
      current.role = role ?? current.role;
      current.seenAt = seenAt;
    }
  };

  entries.forEach((entry) => {
    if (entry.kind === "entity") {
      register(entry.id, entry.label, entry.sublabel, entry.value ?? 0, entry.seenAt);
    }
    (entry.parties ?? []).forEach((party) => register(party.nif, party.label, party.role, entry.value ?? 0, entry.seenAt));
  });

  return [...map.values()].sort((a, b) => b.value - a.value || (a.seenAt < b.seenAt ? 1 : -1));
}
