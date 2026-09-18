/**
 * Cliente da análise de sentimento (`/sentiment/*`).
 *
 * Analisa texto (colado), dados recolhidos de sites, notícias, um dossiê de
 * análise ou um documento do Office — e permite guardar o resultado no dossiê e
 * criar/atualizar um documento no editor Office.
 */
import { API_BASE } from "./api";

export type SentimentEngineId = "lexicon" | "neural" | "auto";

export type SentimentOrigin = "scraped" | "news" | "dossier" | "office" | "text";

export type SentimentRow = {
  id: string;
  title: string;
  source: string;
  date: string | null;
  url: string;
  polarity: number;
  label: string;
  score: number;
  hits: number;
  words: number;
  engine: string;
  excerpt: string;
  matched: { term: string; weight: number; value: number }[];
  sentences: { text: string; polarity: number; hits: number }[];
};

export type SentimentSummary = {
  documents: number;
  engine: string;
  model: string | null;
  generated_at: string;
  mean_polarity: number;
  median_polarity?: number;
  std_polarity?: number;
  ci95?: [number, number];
  label: string;
  positive: number;
  negative: number;
  neutral: number;
  positive_share?: number;
  negative_share?: number;
  extreme_positive?: SentimentRow | null;
  extreme_negative?: SentimentRow | null;
};

export type SentimentAnalysis = {
  summary: SentimentSummary;
  rows: SentimentRow[];
  by_source: { source: string; documents: number; polarity: number; label: string; std: number }[];
  by_day: { day: string; documents: number; polarity: number }[];
  terms: { term: string; count: number; weight: number; polarity: string }[];
  keywords: { term: string; score: number }[];
  distribution: { label: string; count: number }[];
  markdown?: string;
  csv?: string;
  origin?: string;
  documents_used?: number;
};

export type SentimentMeta = {
  engines: { id: SentimentEngineId; label: string; detail: string; offline: boolean; available?: boolean }[];
  lexicon_size: number;
  thresholds: { positive: number; negative: number };
  keywords: string;
  aggregation: string;
  dossiers: boolean;
  office: boolean;
};

export type CorpusRequest = {
  origin: SentimentOrigin;
  q?: string;
  sourceId?: string;
  dossierId?: string;
  documentId?: string;
  limit?: number;
  engine?: SentimentEngineId;
  title?: string;
  term?: string;
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

function withBody(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function corpusBody(request_: CorpusRequest) {
  return {
    origin: request_.origin,
    q: request_.q || undefined,
    source_id: request_.sourceId || undefined,
    dossier_id: request_.dossierId || undefined,
    document_id: request_.documentId || undefined,
    limit: request_.limit ?? 60,
    engine: request_.engine ?? "lexicon",
    title: request_.title || undefined,
    term: request_.term || undefined,
  };
}

export function getSentimentMeta() {
  return request<SentimentMeta>("/sentiment/meta");
}

export function analyzeSentimentText(payload: { text: string; title?: string; engine?: SentimentEngineId }) {
  return request<SentimentAnalysis>("/sentiment/analyze", withBody(payload));
}

export function analyzeSentimentCorpus(corpus: CorpusRequest) {
  return request<SentimentAnalysis>("/sentiment/corpus", withBody(corpusBody(corpus)));
}

export function saveSentimentToDossier(corpus: CorpusRequest & { dossierId: string }) {
  return request<{ saved: boolean; summary: Record<string, unknown>; analysis: SentimentAnalysis; sentiment: Record<string, unknown> }>(
    "/sentiment/save/dossier",
    withBody({ ...corpusBody(corpus), dossier_id: corpus.dossierId }),
  );
}

export function saveSentimentToOffice(payload: {
  title: string;
  analysis: SentimentAnalysis;
  dossierId?: string;
  folderId?: string;
  tags?: string[];
}) {
  return request<{ saved: boolean; document: { id: string; title: string; kind: string; words: number } }>(
    "/sentiment/save/office",
    withBody({
      title: payload.title,
      analysis: payload.analysis,
      dossier_id: payload.dossierId || undefined,
      folder_id: payload.folderId || undefined,
      tags: payload.tags ?? ["sentimento"],
    }),
  );
}

/** Descarrega um texto como ficheiro (CSV/Markdown). */
export function downloadText(filename: string, content: string, type = "text/csv;charset=utf-8") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
