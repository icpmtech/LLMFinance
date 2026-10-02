/**
 * Documentos de referência da plataforma (`/docs/*`).
 *
 * A pasta `data/docs` (no backend) guarda os documentos oficiais que a
 * plataforma usa — manuais, tabelas e classificações. Cada documento pode ter
 * uma **versão markdown** (um `.md` irmão, como `CAE-Rev.4.md` gerado a partir
 * de `CAE-Rev.4.pdf`), que é o que a página Documentos mostra.
 */
import { API_BASE } from "./api";

export type DocsItem = {
  name: string;
  title: string;
  kind: string;
  extension: string;
  size: number;
  modified: string;
  has_markdown: boolean;
  markdown_name: string;
  /** `.md` que é a versão markdown de outro documento da pasta. */
  generated: boolean;
  url: string;
};

export type DocsList = {
  folder: string;
  total: number;
  items: DocsItem[];
};

export type DocsMarkdown = {
  name: string;
  title: string;
  kind: string;
  source: string;
  chars: number;
  lines: number;
  markdown: string;
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

/** Lista os documentos de `data/docs`. */
export function listDocs(): Promise<DocsList> {
  return request<DocsList>("/docs/documents");
}

/** Markdown de um documento (`.md` irmão ou conversão de texto). */
export function getDocMarkdown(name: string): Promise<DocsMarkdown> {
  return request<DocsMarkdown>(`/docs/markdown/${encodeURIComponent(name)}`);
}

/** URL absoluto do ficheiro original (pré-visualizar ou descarregar). */
export function docFileUrl(name: string, download = false): string {
  return `${API_BASE}/docs/document/${encodeURIComponent(name)}${download ? "?download=true" : ""}`;
}
