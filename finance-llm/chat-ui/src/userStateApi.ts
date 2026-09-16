/**
 * Cliente das preferências do utilizador guardadas no Elasticsearch
 * (`finance_user_state`): favoritos, pastas do dossier e histórico.
 */
import { API_BASE } from "./api";

export type FavoriteKind = "entity" | "contract";

export type FavoriteParty = { nif: string; label: string; role?: string };

export type FavoriteEntry = {
  kind: FavoriteKind;
  id: string;
  label: string;
  sublabel?: string;
  value?: number | null;
  parties?: FavoriteParty[];
  addedAt?: string;
};

export type WorkspaceFolderEntry = {
  id: string;
  name: string;
  createdAt?: string;
  items: FavoriteEntry[];
};

export type WorkspaceState = {
  folders: WorkspaceFolderEntry[];
  history: FavoriteEntry[];
};

async function readError(res: Response, fallback: string) {
  try {
    const payload = await res.json();
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // resposta sem JSON: fica a mensagem genérica
  }
  return `${fallback} (${res.status})`;
}

export async function fetchFavorites(): Promise<FavoriteEntry[]> {
  const res = await fetch(`${API_BASE}/favorites`);
  if (!res.ok) throw new Error(await readError(res, "Erro ao carregar favoritos"));
  const payload = (await res.json()) as { items?: FavoriteEntry[] };
  return payload.items ?? [];
}

export async function saveFavoriteRequest(entry: FavoriteEntry): Promise<void> {
  const res = await fetch(`${API_BASE}/favorites`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind: entry.kind,
      id: entry.id,
      label: entry.label,
      sublabel: entry.sublabel ?? null,
      value: entry.value ?? null,
      parties: entry.parties ?? [],
    }),
  });
  if (!res.ok) throw new Error(await readError(res, "Erro ao guardar favorito"));
}

export async function deleteFavoriteRequest(kind: FavoriteKind, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/favorites/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res, "Erro ao remover favorito"));
}

export async function clearFavoritesRequest(): Promise<void> {
  const res = await fetch(`${API_BASE}/favorites`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res, "Erro ao limpar favoritos"));
}

export async function fetchWorkspace(): Promise<WorkspaceState> {
  const res = await fetch(`${API_BASE}/workspace`);
  if (!res.ok) throw new Error(await readError(res, "Erro ao carregar o dossier"));
  const payload = (await res.json()) as { folders?: WorkspaceFolderEntry[]; history?: FavoriteEntry[] };
  return { folders: payload.folders ?? [], history: payload.history ?? [] };
}

export async function saveFolderRequest(folder: WorkspaceFolderEntry): Promise<void> {
  const res = await fetch(`${API_BASE}/workspace/folders/${encodeURIComponent(folder.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: folder.id,
      name: folder.name,
      createdAt: folder.createdAt ?? null,
      items: folder.items,
    }),
  });
  if (!res.ok) throw new Error(await readError(res, "Erro ao guardar a pasta"));
}

export async function deleteFolderRequest(folderId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/workspace/folders/${encodeURIComponent(folderId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res, "Erro ao apagar a pasta"));
}

export async function saveHistoryRequest(items: FavoriteEntry[]): Promise<void> {
  const res = await fetch(`${API_BASE}/workspace/history`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await readError(res, "Erro ao guardar o histórico"));
}
