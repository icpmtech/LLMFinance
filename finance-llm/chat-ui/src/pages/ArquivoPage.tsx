/**
 * Módulo Arquivo.pt — pesquisar e recolher páginas do passado.
 *
 * Oferece:
 * - pesquisa no índice local (`finance_arquivo_pt`) já recolhido;
 * - recolha nova a partir da API pública do Arquivo.pt (sessão necessária);
 * - pré-visualização dos resultados com links para o Arquivo.pt.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  Calendar,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Globe2,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";

import {
  collectArquivo,
  getArquivoMeta,
  getArquivoStatus,
  searchArquivo,
  type ArquivoCollectResult,
  type ArquivoItem,
  type ArquivoMeta,
  type ArquivoSearchResult,
  type ArquivoStatus,
} from "../arquivoApi";

const PAGE_SIZE = 20;

const SORTS: { id: string; label: string }[] = [
  { id: "relevance", label: "Relevância" },
  { id: "date_desc", label: "Data (mais recente)" },
  { id: "date_asc", label: "Data (mais antiga)" },
  { id: "domain", label: "Domínio" },
];

function formatCaptureDate(value?: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("pt-PT");
  } catch {
    return value;
  }
}

function formatNumber(value?: number): string {
  if (value === undefined || value === null) return "—";
  return new Intl.NumberFormat("pt-PT").format(value);
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "sky" | "emerald" | "amber" }) {
  const tones: Record<string, string> = {
    neutral: "border-white/10 bg-white/5 text-muted-foreground",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function ResultCard({ item }: { item: ArquivoItem }) {
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold" title={item.title || "(sem título)"}>
            {item.title || "(sem título)"}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {item.domain || "—"}
            {item.mime_type ? ` · ${item.mime_type}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {item.link_to_archive ? (
            <a
              href={item.link_to_archive}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
              title="Abrir a captura no Arquivo.pt"
            >
              Arquivo <ExternalLink size={11} />
            </a>
          ) : null}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1">
        {item.capture_date ? (
          <Badge tone="sky">
            <Calendar size={10} /> {formatCaptureDate(item.capture_date)}
          </Badge>
        ) : null}
        {item.tstamp ? <Badge>{item.tstamp}</Badge> : null}
        {item.collection ? (
          <Badge tone="amber">
            <Archive size={10} /> {item.collection}
          </Badge>
        ) : null}
      </div>

      {item.url ? (
        <p className="mt-2 line-clamp-1 text-[11px] text-muted-foreground" title={item.url}>
          {item.url}
        </p>
      ) : null}
      {item.snippet ? (
        <p
          className="mt-2 line-clamp-3 text-[11px] text-muted-foreground"
          dangerouslySetInnerHTML={{ __html: item.snippet }}
        />
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        {item.link_to_no_frame ? (
          <a
            href={item.link_to_no_frame}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-emerald-200 hover:text-emerald-100"
          >
            <Globe2 size={11} /> Sem moldura
          </a>
        ) : null}
        {item.link_to_screenshot ? (
          <a
            href={item.link_to_screenshot}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-emerald-200 hover:text-emerald-100"
          >
            Screenshot
          </a>
        ) : null}
        {item.link_to_extracted_text ? (
          <a
            href={item.link_to_extracted_text}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-emerald-200 hover:text-emerald-100"
          >
            Texto
          </a>
        ) : null}
      </div>
    </article>
  );
}

export default function ArquivoPage() {
  const [meta, setMeta] = useState<ArquivoMeta | null>(null);
  const [status, setStatus] = useState<ArquivoStatus | null>(null);
  const [results, setResults] = useState<ArquivoSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collectResult, setCollectResult] = useState<ArquivoCollectResult | null>(null);

  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [kind, setKind] = useState("");
  const [sort, setSort] = useState("relevance");
  const [page, setPage] = useState(0);
  const [submitted, setSubmitted] = useState<{
    q?: string;
    domain?: string;
    from_date?: string;
    to_date?: string;
    kind?: string;
  }>({});

  const query = useMemo(
    () => ({ ...submitted, sort, size: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [submitted, sort, page],
  );

  const loadMeta = useCallback(async () => {
    try {
      setMeta(await getArquivoMeta());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar metadados.");
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getArquivoStatus());
    } catch {
      /* mostra sem estado */
    }
  }, []);

  const runSearch = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setResults(await searchArquivo(query));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa.");
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void loadMeta();
    void loadStatus();
  }, [loadMeta, loadStatus]);

  useEffect(() => {
    void runSearch();
  }, [runSearch]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(0);
    setCollectResult(null);
    setSubmitted({
      q: q.trim() || undefined,
      domain: domain.trim() || undefined,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
      kind: kind || undefined,
    });
  };

  const handleCollect = async () => {
    if (!q.trim()) return;
    try {
      setCollecting(true);
      setError(null);
      setCollectResult(null);
      const res = await collectArquivo({ q: q.trim() });
      setCollectResult(res);
      if (res.ingest && !res.ingest.error) {
        void loadStatus();
        setPage(0);
        setSubmitted({ q: q.trim() });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na recolha.");
    } finally {
      setCollecting(false);
    }
  };

  const total = results?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-screen p-4 md:p-6">
      <div className="mx-auto max-w-6xl space-y-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold">Arquivo.pt</h1>
          <p className="text-sm text-muted-foreground">
            Pesquise e recolha páginas da web preservadas pelo Arquivo.pt (FCT).
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-4">
          <div className="glass-card rounded-2xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Índice local</p>
            <p className="mt-1 text-xl font-semibold">{status?.index ?? "—"}</p>
          </div>
          <div className="glass-card rounded-2xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Documentos</p>
            <p className="mt-1 text-xl font-semibold">{formatNumber(status?.total ?? 0)}</p>
          </div>
          <div className="glass-card rounded-2xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">API pública</p>
            <p className="mt-1 text-xl font-semibold">arquivo.pt</p>
          </div>
          <div className="glass-card rounded-2xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Por página</p>
            <p className="mt-1 text-xl font-semibold">{meta?.default_max_items ?? PAGE_SIZE}</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="glass-card rounded-2xl p-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto_auto_auto] md:items-end">
            <div className="space-y-1">
              <label htmlFor="arquivo-q" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Pesquisa
              </label>
              <input
                id="arquivo-q"
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Termos de pesquisa no Arquivo.pt..."
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-sky-400"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="arquivo-domain" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Domínio
              </label>
              <input
                id="arquivo-domain"
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="ex.: gov.pt"
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-sky-400"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="arquivo-from" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                De
              </label>
              <input
                id="arquivo-from"
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-sky-400"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="arquivo-to" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Até
              </label>
              <input
                id="arquivo-to"
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-sky-400"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="arquivo-kind" className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Tipo
              </label>
              <select
                id="arquivo-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-sky-400"
              >
                <option value="">Todos</option>
                <option value="search">Pesquisa</option>
                <option value="cdx">CDX</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2 text-sm font-medium text-white hover:bg-sky-400 disabled:opacity-60"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                Procurar
              </button>
              <button
                type="button"
                onClick={handleCollect}
                disabled={collecting || !q.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-500 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-400 disabled:opacity-60"
                title="Recolher novos resultados do Arquivo.pt e indexá-los (requer sessão)"
              >
                {collecting ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Recolher
              </button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>Ordenar:</span>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value)}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs outline-none focus:border-sky-400"
              >
                {SORTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </form>

        {error ? (
          <div className="rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        ) : null}

        {collectResult ? (
          <div className="rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200">
            Recolha concluída: {collectResult.collected} itens de ~{formatNumber(collectResult.estimated_total)} estimados.
            {collectResult.ingest ? (
              <>
                {" "}
                Indexados {collectResult.ingest.indexed_count}/{collectResult.ingest.total}.
              </>
            ) : null}
          </div>
        ) : null}

        {results ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>
                {formatNumber(total)} resultado{total === 1 ? "" : "s"}
                {results.query ? ` para «${results.query}»` : ""}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded-lg p-1 hover:bg-white/10 disabled:opacity-40"
                >
                  <ChevronLeft size={16} />
                </button>
                <span className="px-1">
                  {page + 1} / {pages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                  disabled={page >= pages - 1}
                  className="rounded-lg p-1 hover:bg-white/10 disabled:opacity-40"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
            <div className="grid gap-3">
              {results.items.map((item, idx) => (
                <ResultCard key={`${item.tstamp}-${item.digest ?? idx}`} item={item} />
              ))}
            </div>
            {!results.items.length && !loading ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Nenhum resultado. Experimente recolher dados do Arquivo.pt.
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
