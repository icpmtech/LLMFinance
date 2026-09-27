/**
 * Cliente da análise de sentimento (`/sentiment/*`).
 *
 * Analisa texto (colado), dados recolhidos de sites, notícias, um dossiê de
 * análise ou um documento do Office — e permite guardar o resultado no dossiê e
 * criar/atualizar um documento no editor Office.
 */
import { API_BASE } from "./api";

export type SentimentEngineId = "lexicon" | "neural" | "auto";

export type SentimentOrigin = string;

/** Fonte do sistema analisável (com quantos documentos tem disponíveis). */
export type SentimentSource = {
  id: string;
  label: string;
  group: string;
  hint?: string;
  session?: boolean;
  needs?: string;
  available: number;
  blocked: boolean;
  blocked_reason?: string | null;
};

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
  /** Média ponderada apenas dos documentos com termos de sentimento. */
  mean_polarity_signal?: number;
  reported_mean?: number;
  documents_with_signal?: number;
  documents_without_signal?: number;
  coverage?: number;
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
  by_tag: { tag: string; documents: number; polarity: number; label: string }[];
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
  accountId?: string;
  folder?: string;
  limit?: number;
  engine?: SentimentEngineId;
  title?: string;
  term?: string;
  /** Notícias: limita o corpus a um ticker (ex.: EDP.LS). */
  ticker?: string;
  startDate?: string;
  endDate?: string;
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
    account_id: request_.accountId || undefined,
    folder: request_.folder || undefined,
    limit: request_.limit ?? 60,
    engine: request_.engine ?? "lexicon",
    title: request_.title || undefined,
    term: request_.term || undefined,
    ticker: request_.ticker || undefined,
    start_date: request_.startDate || undefined,
    end_date: request_.endDate || undefined,
  };
}

export function getSentimentMeta() {
  return request<SentimentMeta>("/sentiment/meta");
}

/** Fontes do sistema disponíveis para análise (com contagem de documentos). */
export function listSentimentSources() {
  return request<{ total: number; items: SentimentSource[]; accounts: { id: string; label?: string; address?: string }[] }>(
    "/sentiment/sources",
  );
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

/* ====================================================================== *
 * Sentimento de mercado — série diária por ticker (`/sentiment/market/*`) *
 * ====================================================================== */

/** Ponto da série diária do mercado (todos os tickers ou um só). */
export type MarketDailyPoint = {
  day: string;
  sentiment: number;
  news: number;
  tickers: number;
  coverage: number;
  label: string;
};

/** Estatísticas de um ticker na janela (com a janela anterior, se houver). */
export type MarketTickerStats = {
  ticker: string;
  days: number;
  news: number;
  sentiment: number;
  coverage: number;
  positive_ratio: number;
  negative_ratio: number;
  label: string;
  last_date: string | null;
  /** Tom da janela anterior (quando existe histórico). */
  previous: number | null;
  previous_news: number;
  delta: number | null;
  /** `delta` = variação contra a janela anterior; `nivel` = só nível de tom. */
  basis: "delta" | "nivel";
};

export type MarketHeatCell = {
  day: string;
  value: number | null;
  news: number;
  label: string | null;
  coverage: number | null;
};

export type MarketHeatRow = {
  ticker: string;
  cells: MarketHeatCell[];
  sentiment: number;
  news: number;
  label: string;
};

/** Estado da série guardada (documentos, datas, cobertura). */
export type MarketState = {
  documents: number;
  tickers: number;
  first_date: string | null;
  last_date: string | null;
  covered_news: number;
  top: { ticker: string; documents: number; first_date: string; last_date: string; news: number }[];
  settings: Record<string, unknown>;
  index: string;
};

/** Agenda da construção da série (cron diário). */
export type MarketSchedule = {
  running: boolean;
  error: string | null;
  job_id?: string;
  scheduled: boolean;
  cron: string;
  timezone: string;
  enabled: boolean;
  days: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_result: Record<string, unknown> | null;
};

export type MarketOverview = {
  window: { days: number; start: string; end: string; previous_start: string; previous_end: string };
  kpis: {
    tickers: number;
    news: number;
    sentiment: number;
    coverage: number;
    positive_ratio: number;
    negative_ratio: number;
    label: string;
    trend: number | null;
    tickers_with_delta: number;
    last_date: string | null;
  };
  series: MarketDailyPoint[];
  heatmap: { days: string[]; rows: MarketHeatRow[] };
  ranking: { up: MarketTickerStats[]; down: MarketTickerStats[]; basis: "delta" | "nivel" };
  tickers: MarketTickerStats[];
  topics: { term: string; news: number }[];
  sources: { source: string; news: number }[];
  state: MarketState;
  schedule?: MarketSchedule;
  error?: string;
};

/** Resultado de uma construção da série (manual ou agendada). */
export type MarketBuildResult = {
  ok: boolean;
  window: { days: number; start: string; end: string };
  tickers: number;
  tickers_with_news?: number;
  news: number;
  documents: number;
  skipped?: number;
  /** Dias obsoletos apagados da série nesta corrida. */
  pruned?: number;
  engine?: string;
  errors: string[];
  details?: { ticker: string; news: number; days: number; skipped: number }[];
};

export type MarketTickerDetail = {
  ticker: string;
  window: { days: number; start: string; end: string };
  stats: Partial<MarketTickerStats>;
  items: {
    day: string;
    sentiment: number;
    mean: number;
    news: number;
    /** Histórias distintas do dia (notícias repetidas contam uma vez). */
    unique: number;
    duplicates: number;
    coverage: number;
    label: string;
    topics: string[];
  }[];
  best?: { day: string; value: number };
  worst?: { day: string; value: number };
  highlights: { title: string; url: string; source: string; polarity: number; label: string; day: string; reason: string }[];
  message?: string;
  error?: string;
};

export type MarketCoverage = { with_news: number; built: number; missing: string[]; missing_total: number };

/** Panorama do mercado: KPIs, série, heatmap ticker × dia e rankings. */
export function getSentimentMarketOverview(days = 30, limit = 24) {
  return request<MarketOverview>(`/sentiment/market/overview?days=${days}&limit=${limit}`);
}

/** Série diária do mercado ou de um ticker. */
export function getSentimentMarketSeries(days = 90, ticker?: string) {
  const search = ticker ? `&ticker=${encodeURIComponent(ticker)}` : "";
  return request<{ ticker: string | null; start: string; end: string; days: number; items: MarketDailyPoint[]; error?: string }>(
    `/sentiment/market/series?days=${days}${search}`,
  );
}

/** Série e destaques de um ticker. */
export function getSentimentMarketTicker(ticker: string, days = 90) {
  return request<MarketTickerDetail>(`/sentiment/market/ticker/${encodeURIComponent(ticker)}?days=${days}`);
}

/** Volume guardado, cobertura e o que falta construir (com a agenda). */
export function getSentimentMarketState() {
  return request<{ state: MarketState; coverage: MarketCoverage; schedule: MarketSchedule }>("/sentiment/market/state");
}

export function getSentimentMarketSchedule() {
  return request<MarketSchedule>("/sentiment/market/schedule");
}

export function saveSentimentMarketSchedule(payload: { cron?: string; timezone?: string; enabled?: boolean; days?: number; engine?: SentimentEngineId; max_news_per_ticker?: number }) {
  return request<{ saved: boolean; settings: Record<string, unknown>; schedule: MarketSchedule }>(
    "/sentiment/market/schedule",
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
  );
}

export function reloadSentimentMarketSchedule() {
  return request<MarketSchedule>("/sentiment/market/schedule/reload", { method: "POST" });
}

/** (Re)constrói a série diária a partir das notícias indexadas. */
export function buildSentimentMarket(payload: { days?: number; tickers?: string[]; only_missing?: boolean; engine?: SentimentEngineId } = {}) {
  return request<MarketBuildResult>("/sentiment/market/build", withBody(payload));
}

/** Guarda o relatório do panorama no editor Office. */
export function saveSentimentMarketToOffice(payload: { days?: number; title?: string } = {}) {
  return request<{ ok: boolean; document: { id: string; title: string; kind: string }; document_id: string }>(
    "/sentiment/market/report/office",
    withBody(payload),
  );
}

/** Endereço de descarga do panorama (CSV para Excel ou Markdown). */
export function sentimentMarketExportUrl(days = 30, format: "csv" | "md" = "csv"): string {
  return `${API_BASE}/sentiment/market/export?format=${format}&days=${days}`;
}

/** Tipo de alerta: movimento, viragem de sinal, dia extremo ou tom pouco sustentado. */
export type MarketAlertKind = "subida" | "descida" | "viragem" | "extremo" | "cobertura";

export type MarketAlert = {
  ticker: string;
  sentiment: number;
  label: string;
  news: number;
  coverage: number;
  last_date: string | null;
  previous: number | null;
  delta: number | null;
  kind: MarketAlertKind;
  kind_label: string;
  severity: "alta" | "media" | "baixa";
  detail: string;
  /** Só nos alertas de dia extremo. */
  day?: string | null;
  value?: number;
};

export type MarketAlerts = {
  window: MarketOverview["window"];
  thresholds: { min_delta: number; min_news: number; extreme: number; low_coverage: number };
  kinds: { id: MarketAlertKind; label: string }[];
  items: MarketAlert[];
  total: number;
  counts: { kind: MarketAlertKind; label: string; count: number }[];
  generated_at: string;
  error?: string;
};

/** Boletim do mercado: resumo, movimentos, alertas e temas (com o Markdown). */
export type MarketBrief = {
  window: MarketOverview["window"];
  kpis: MarketOverview["kpis"];
  series: MarketDailyPoint[];
  ranking: MarketOverview["ranking"];
  best: MarketDailyPoint | null;
  worst: MarketDailyPoint | null;
  movers: { up: MarketTickerStats[]; down: MarketTickerStats[]; basis: "delta" | "nivel" };
  alerts: MarketAlerts;
  topics: { term: string; news: number }[];
  sources: { source: string; news: number }[];
  generated_at: string;
  markdown: string;
  error?: string;
};

/** Alertas de movimentos (critérios devolvidos na própria resposta). */
export function getSentimentMarketAlerts(days = 30, minDelta = 0.25, minNews = 2, limit = 12) {
  return request<MarketAlerts>(`/sentiment/market/alerts?days=${days}&min_delta=${minDelta}&min_news=${minNews}&limit=${limit}`);
}

/** Boletim do mercado num formato pronto a ler. */
export function getSentimentMarketBrief(days = 7) {
  return request<MarketBrief>(`/sentiment/market/brief?days=${days}`);
}

/** Guarda o boletim no editor Office. */
export function saveSentimentMarketBriefToOffice(payload: { days?: number; title?: string } = {}) {
  return request<{ ok: boolean; document: { id: string; title: string; kind: string }; document_id: string; markdown: string }>(
    "/sentiment/market/brief/office",
    withBody(payload),
  );
}

/** Cotações de um ticker na janela (plataforma ou Yahoo Finance). */
export type MarketPrice = {
  ticker: string;
  window: MarketOverview["window"];
  source: "plataforma" | "yahoo" | null;
  points: { date: string; close: number; volume: number | null }[];
  total: number;
  message?: string | null;
  error?: string | null;
};

/** Par alinhado (dia com tom **e** variação de fecho). */
export type MarketCorrelationPair = {
  day: string;
  sentiment: number;
  change_pct: number;
  close: number;
  news: number;
  coverage: number;
  label: string;
};

export type MarketCorrelationReading =
  | "amostra_insuficiente"
  | "alinhado"
  | "tom_acima_do_preco"
  | "preco_acima_do_tom"
  | "indeterminada";

/** Relação entre o tom das notícias e a variação do preço. */
export type MarketCorrelation = {
  ticker: string;
  window: MarketOverview["window"];
  price_source: "plataforma" | "yahoo" | null;
  price_days: number;
  sentiment_days: number;
  pairs: number;
  enough_data: boolean;
  min_pairs: number;
  same_day: {
    r: number | null;
    spearman: number | null;
    n: number;
    strength: string;
    direction: string | null;
    t: number | null;
    significant: boolean | null;
  };
  lag1: { r: number | null; n: number; strength: string; t: number | null; significant: boolean | null };
  window_move: {
    sentiment: number | null;
    change_pct: number | null;
    normalized_change: number | null;
    gap: number | null;
    reading: MarketCorrelationReading;
  };
  series: MarketCorrelationPair[];
  /** Quantas cotações ficaram guardadas na plataforma nesta leitura. */
  price_stored?: { indexed: number; errors: number; error?: string | null } | null;
  price_message?: string | null;
  caveat: string;
  error?: string | null;
};

/** Linha do ranking de divergência tom × preço. */
export type MarketDivergenceRow = {
  ticker: string;
  sentiment: number;
  label: string;
  news: number;
  days: number;
  coverage: number;
  change_pct: number;
  normalized_change: number;
  gap: number;
  reading: MarketCorrelationReading;
  price_source: "plataforma" | "yahoo" | null;
  price_days: number;
};

export type MarketDivergence = {
  window: MarketOverview["window"];
  items: MarketDivergenceRow[];
  total: number;
  tickers_with_series: number;
  with_prices: number;
  /** Cotações guardadas na plataforma durante esta leitura. */
  stored?: number;
  reference_move: number;
  caveat: string;
  message?: string | null;
  error?: string;
};

/** Tom × preço de um ticker (com `live` vai buscar cotações ao Yahoo quando faltam). */
export function getSentimentMarketPrice(ticker: string, days = 90, live = false) {
  return request<MarketCorrelation>(
    `/sentiment/market/price/${encodeURIComponent(ticker)}?days=${days}&live=${live ? 1 : 0}`,
  );
}

/** Ranking de divergência entre o tom e a variação do preço. */
export function getSentimentMarketDivergence(days = 30, limit = 12, live = false) {
  return request<MarketDivergence>(`/sentiment/market/divergence?days=${days}&limit=${limit}&live=${live ? 1 : 0}`);
}

/** Estado de um ticker: seguido ou não, série, notícias e cotações guardadas. */
export type MarketTickerStatus = {
  ticker: string;
  followed: boolean;
  documents: number;
  news: number;
  stories: number;
  last_date: string | null;
  label: string | null;
  price_points: number;
  price_error?: string | null;
};

export type MarketTickerList = {
  window: MarketOverview["window"];
  watchlist: string[];
  total: number;
  items: MarketTickerStatus[];
  max_watchlist: number;
};

/** Resultado de seguir um ticker (análise dinâmica: notícias + cotações + série). */
export type MarketFollowResult = {
  ok: boolean;
  ticker: string;
  window: { days: number };
  news: { indexed: number; total: number; analyzed: number; error?: string | null } | null;
  prices: { source: string | null; points: number; stored?: { indexed: number } | null; error?: string | null } | null;
  series: { days: number; news: number; documents: number; pruned?: number } | null;
  errors: string[];
  suggestions: { ticker: string; name?: string | null; exchange?: string | null }[];
  watchlist: string[];
  followed: boolean;
};

/** Tickers seguidos e o que cada um tem guardado. */
export function listSentimentMarketTickers(days = 30) {
  return request<MarketTickerList>(`/sentiment/market/tickers?days=${days}`);
}

/** Segue um ticker: traz notícias, cotações e constrói a série já. */
export function followSentimentMarketTicker(payload: {
  ticker: string;
  ingest_news?: boolean;
  ingest_prices?: boolean;
  days?: number;
}) {
  return request<MarketFollowResult>("/sentiment/market/tickers", withBody(payload));
}

/** Deixa de seguir um ticker (a série guardada mantém-se). */
export function unfollowSentimentMarketTicker(ticker: string) {
  return request<{ ticker: string; removed: boolean; watchlist: string[] }>(
    `/sentiment/market/tickers/${encodeURIComponent(ticker)}`,
    { method: "DELETE" },
  );
}
