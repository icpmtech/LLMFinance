/**
 * Cliente da API do módulo Arquivo.pt (`/arquivo/*`).
 *
 * O backend expõe pesquisa no índice local e recolha a partir da API pública
 * do Arquivo.pt (FCT). A recolha exige sessão; a leitura é pública.
 */
export const API_BASE = import.meta.env.VITE_API_URL || "/api";

export type ArquivoItem = {
  title?: string;
  url?: string;
  domain?: string;
  tstamp?: string;
  capture_date?: string;
  digest?: string;
  mime_type?: string;
  status?: string;
  length?: number;
  collection?: string;
  query?: string;
  site?: string;
  type?: string;
  snippet?: string;
  text?: string;
  link_to_archive?: string;
  link_to_no_frame?: string;
  link_to_screenshot?: string;
  link_to_extracted_text?: string;
  link_to_metadata?: string;
  link_to_original_file?: string;
  filename?: string;
  host_key?: string;
  kind?: "search" | "cdx";
  collected_at?: string;
};

export type ArquivoSearchResult = {
  total: number;
  items: ArquivoItem[];
  offset: number;
  size: number;
  query?: string;
  error?: string;
};

export type ArquivoMeta = {
  module: string;
  source: string;
  source_label: string;
  index: string;
  search_page: string;
  api_docs: string;
  max_items_per_request: number;
  default_max_items: number;
  default_max_pages: number;
  notes: string;
};

export type ArquivoStatus = {
  available: boolean;
  total: number;
  index: string;
  error?: string;
};

export type ArquivoCollectRequest = {
  q: string;
  max_pages?: number;
  max_items?: number;
  site?: string;
  type?: string;
  from_ts?: string;
  to_ts?: string;
  ingest?: boolean;
  min_interval?: number;
};

export type ArquivoCollectResult = {
  query: string;
  site?: string;
  type?: string;
  from_ts?: string;
  to_ts?: string;
  pages: number;
  offset: number;
  collected: number;
  estimated_total: number;
  next_offset?: number | null;
  items: ArquivoItem[];
  ingest?: {
    indexed_count: number;
    errors?: number;
    total: number;
    error?: string;
  };
  error?: string;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
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

export function getArquivoMeta(): Promise<ArquivoMeta> {
  return request<ArquivoMeta>("/arquivo/meta");
}

export function getArquivoStatus(): Promise<ArquivoStatus> {
  return request<ArquivoStatus>("/arquivo/status");
}

export function searchArquivo(params: {
  q?: string;
  domain?: string;
  url?: string;
  mime_type?: string;
  type?: string;
  from_date?: string;
  to_date?: string;
  kind?: string;
  sort?: string;
  size?: number;
  offset?: number;
} = {}): Promise<ArquivoSearchResult> {
  const p = new URLSearchParams();
  const put = (name: string, value: string | number | undefined) => {
    if (value === undefined || value === null || value === "") return;
    p.set(name, String(value));
  };
  put("q", params.q?.trim());
  put("domain", params.domain);
  put("url", params.url);
  put("mime_type", params.mime_type);
  put("type", params.type);
  put("from_date", params.from_date);
  put("to_date", params.to_date);
  put("kind", params.kind);
  put("sort", params.sort);
  put("size", params.size);
  put("offset", params.offset);
  const suffix = p.toString();
  return request<ArquivoSearchResult>(`/arquivo/search${suffix ? `?${suffix}` : ""}`);
}

export function collectArquivo(req: ArquivoCollectRequest): Promise<ArquivoCollectResult> {
  return request<ArquivoCollectResult>("/arquivo/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}
