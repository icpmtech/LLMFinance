/**
 * Cliente do Office IQ OS (`/office/*`).
 *
 * Documentos em Markdown (notas, dossiês, relatórios, atas, páginas) com pastas,
 * etiquetas, pesquisa, exportação (.md/.html) e importação dos dossiês 360
 * guardados na Pesquisa 360.
 */
import { API_BASE } from "./api";

export type OfficeDocumentSummary = {
  id: string;
  title: string;
  kind: string;
  kind_label: string;
  folder_id?: string | null;
  folder?: string | null;
  tags: string[];
  author?: string | null;
  pinned: boolean;
  words: number;
  excerpt: string;
  source?: { type?: string; id?: string; term?: string; generated_at?: string } | null;
  created_at?: string;
  updated_at?: string;
};

export type OfficeDocument = OfficeDocumentSummary & { markdown: string };

export type OfficeFolder = {
  id: string;
  name: string;
  color?: string;
  description?: string | null;
  documents?: number;
  created_at?: string;
  updated_at?: string;
};

export type OfficeStats = {
  documents: number;
  folders: number;
  words: number;
  by_kind: { value: string; label: string; count: number }[];
  recent: OfficeDocumentSummary[];
  updated_at?: string;
};

export type OfficeListPayload = {
  total: number;
  items: OfficeDocumentSummary[];
  folders: OfficeFolder[];
  kinds: { id: string; label: string }[];
  stats: OfficeStats;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) };
}

export function listOfficeDocuments(options: { folderId?: string; q?: string; kind?: string; tag?: string } = {}): Promise<OfficeListPayload> {
  const params = new URLSearchParams();
  if (options.folderId) params.set("folder_id", options.folderId);
  if (options.q) params.set("q", options.q);
  if (options.kind) params.set("kind", options.kind);
  if (options.tag) params.set("tag", options.tag);
  const query = params.toString();
  return request(`/office/documents${query ? `?${query}` : ""}`);
}

export function getOfficeDocument(id: string): Promise<{ document: OfficeDocument }> {
  return request(`/office/documents/${encodeURIComponent(id)}`);
}

export function saveOfficeDocument(payload: {
  id?: string;
  title?: string;
  markdown?: string;
  kind?: string;
  folder_id?: string | null;
  tags?: string[];
  pinned?: boolean;
  template?: string;
}): Promise<{ saved: boolean; document: OfficeDocument }> {
  return request("/office/documents", withBody("POST", payload));
}

export function patchOfficeDocument(
  id: string,
  payload: { title?: string; folder_id?: string | null; tags?: string[]; pinned?: boolean },
): Promise<{ saved: boolean; document: OfficeDocument }> {
  return request(`/office/documents/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function deleteOfficeDocument(id: string): Promise<{ removed: boolean; id: string }> {
  return request(`/office/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function duplicateOfficeDocument(id: string, title?: string): Promise<{ duplicated: boolean; document: OfficeDocument }> {
  return request(`/office/documents/${encodeURIComponent(id)}/duplicate`, withBody("POST", { title }));
}

export function saveOfficeFolder(payload: { id?: string; name: string; color?: string; description?: string }): Promise<{ saved: boolean; folder: OfficeFolder }> {
  return request("/office/folders", withBody("POST", payload));
}

export function deleteOfficeFolder(id: string): Promise<{ removed: boolean; id: string; documents_kept: number }> {
  return request(`/office/folders/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function officeStats(): Promise<OfficeStats> {
  return request("/office/stats");
}

/** Traz um dossiê 360 guardado para o Office (atualiza o documento ligado, se existir). */
export function officeDocumentFromDossier(
  dossierId: string,
  options: { folderId?: string; createNew?: boolean } = {},
): Promise<{ saved: boolean; document: OfficeDocument; dossier: { id: string; title: string; term?: string } }> {
  return request(
    `/office/documents/from-dossier/${encodeURIComponent(dossierId)}`,
    withBody("POST", { folder_id: options.folderId, create_new: options.createNew ?? false }),
  );
}

export function listOfficeAvailableDossiers(limit = 40): Promise<{
  total: number;
  items: (OfficeDocumentSummary & { term?: string; document_id?: string | null })[];
}> {
  return request(`/office/dossiers/available?limit=${limit}`);
}

export function officeExportUrl(id: string, format: "md" | "html" = "md"): string {
  return `${API_BASE}/office/documents/${encodeURIComponent(id)}/export?format=${format}`;
}

/** Chave onde a aplicação que envia para o Office deixa o documento a abrir. */
export const OFFICE_OPEN_KEY = "finance-llm-office-doc";

export const OFFICE_TEMPLATES = [
  { id: "nota", label: "Nota", hint: "Uma página simples para escrever." },
  { id: "relatorio", label: "Relatório", hint: "Sumário, contexto, análise, riscos e próximos passos." },
  { id: "ata", label: "Ata de reunião", hint: "Ordem de trabalhos, decisões e ações." },
  { id: "pagina", label: "Página", hint: "Documento em branco." },
];
