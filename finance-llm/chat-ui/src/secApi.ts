/**
 * Cliente da API do módulo **SEC** — `/sec/*`.
 *
 * Filings EDGAR: pesquisa de empresas, listagem de filings, ingestão,
 * pesquisa de documentos/factos e análise agregada.
 */
import { API_BASE } from "./api";

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(data?.detail || `Erro ${res.status} em ${path}`);
  }
  return data as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(data?.detail || `Erro ${res.status} em ${path}`);
  }
  return data as T;
}

export type SecCompany = {
  cik: string;
  cik_int: number;
  ticker: string;
  name: string;
};

export type SecFilingItem = {
  cik: string;
  ticker: string;
  company_name: string;
  accession_number: string;
  form: string;
  date: string;
  description: string;
  primary_document: string;
  url: string;
  text?: string;
  facts_count?: number;
  indexed_at?: string;
};

export type SecFact = {
  cik: string;
  ticker: string;
  company_name: string;
  accession_number: string;
  form: string;
  date?: string;
  filing_id: string;
  text: string;
  category: string;
  // XBRL structured fields.
  concept?: string;
  label?: string;
  description?: string;
  unit?: string;
  value?: number;
  end?: string;
  start?: string;
  fy?: number;
  fp?: string;
};

export type SecSearchResult<T> = {
  total: number;
  items: T[];
};

export type SecMeta = {
  modulo: string;
  versao: string;
  fonte: string;
  url: string;
  user_agent: string;
  status: { indices: Record<string, { count?: number }> };
};

export type SecBucket = { value: string; count: number };

export type SecSchedule = {
  started: boolean;
  error?: string;
  job_count: number;
  jobs: { id: string; name: string; next_run?: string }[];
};

export type SecAnalytics = {
  by_form: SecBucket[];
  by_year: SecBucket[];
  by_ticker: SecBucket[];
  error?: string;
};

export async function getSecMeta(): Promise<SecMeta> {
  return getJson<SecMeta>("/sec/meta");
}

export async function searchSecCompanies(q: string, size = 20): Promise<{ items: SecCompany[]; total: number; query: string }> {
  return getJson(`/sec/companies${query({ q, size })}`);
}

export async function getSecFilings(cik: string, limit = 40, form?: string): Promise<SecSearchResult<SecFilingItem> & { cik: string; ticker: string; company_name: string }> {
  return getJson(`/sec/filings/${encodeURIComponent(cik)}${query({ limit, form })}`);
}

export async function ingestSecFilings(cik: string, limit = 20): Promise<{ cik: string; total: number; indexed: number; analyzed: number; recolha_id: string; error?: string }> {
  return postJson(`/sec/filings/${encodeURIComponent(cik)}/ingestao${query({ limit })}`);
}

export async function searchSecFilings(params: {
  q?: string;
  ticker?: string;
  form?: string;
  cik?: string;
  year?: number;
  size?: number;
  from?: number;
}): Promise<SecSearchResult<SecFilingItem>> {
  return getJson(`/sec/search${query(params)}`);
}

export async function searchSecFacts(params: {
  q?: string;
  ticker?: string;
  form?: string;
  category?: string;
  size?: number;
  from?: number;
}): Promise<SecSearchResult<SecFact>> {
  return getJson(`/sec/facts${query(params)}`);
}

export async function getSecFiling(docId: string): Promise<SecFilingItem> {
  return getJson(`/sec/filings/${encodeURIComponent(docId)}/ficha`);
}

export async function fetchSecDocument(url: string): Promise<{ text: string; error?: string }> {
  return getJson(`/sec/document${query({ url })}`);
}

export async function getSecAnalytics(): Promise<SecAnalytics> {
  return getJson("/sec/analytics");
}

export async function getSecFactsXbrl(cik: string): Promise<{
  cik: string;
  company_name: string;
  taxonomy: string;
  total_concepts: number;
  facts: SecFact[];
  error?: string;
}> {
  return getJson(`/sec/facts/${encodeURIComponent(cik)}/xbrl`);
}

export async function indexSecFactsXbrl(cik: string): Promise<{ cik: string; indexed_facts: number; errors?: number; error?: string }> {
  return postJson(`/sec/facts/${encodeURIComponent(cik)}/indexar`);
}

export async function getSecSchedule(): Promise<{
  started: boolean;
  error?: string;
  job_count: number;
  jobs: { id: string; name: string; next_run?: string }[];
}> {
  return getJson("/sec/schedule");
}

export async function reloadSecSchedule(): Promise<{ started: boolean; error?: string; job_count: number; jobs: { id: string; name: string; next_run?: string }[] }> {
  return postJson("/sec/schedule/recarregar");
}

export async function runSecSchedule(ticker: string): Promise<{ ticker: string; triggered: boolean }> {
  return postJson(`/sec/schedule/${encodeURIComponent(ticker)}/executar`);
}
