/**
 * Módulo de **Notícias** (rota `/noticias`).
 *
 * Duas metades que se alimentam uma à outra:
 *
 * 1. **Recolher** — vai ao Yahoo buscar notícias para o Elasticsearch, por ticker
 *    (com sentimento, tradução PT, tópicos e entidades) ou por tema (léxico
 *    bilingue, mais rápido). Sem indicar nada, recolhe para os favoritos do painel
 *    de mercado.
 * 2. **Pesquisar** — texto livre + filtros (ticker, fonte, tema, sentimento,
 *    período, com/sem análise) sobre tudo o que está indexado, com facetas
 *    calculadas sobre o mesmo filtro e paginação.
 *
 * O que aqui se recolhe fica no índice `finance_news`, o mesmo que o sentimento
 * de mercado, a Pesquisa total e o RAG usam.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Filter,
  Loader2,
  Newspaper,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Tag,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import {
  collectNews,
  getNewsStats,
  searchNews,
  type NewsCollectResult,
  type NewsCollectTarget,
  type NewsDoc,
  type NewsFacetBucket,
  type NewsSearchResult,
  type NewsStats,
} from "../newsApi";
import { getSentimentMarketWatchlist } from "../sentimentApi";

const SORTS = [
  { id: "recent", label: "Mais recentes" },
  { id: "oldest", label: "Mais antigas" },
  { id: "relevance", label: "Relevância" },
] as const;

const SENTIMENTS = [
  { id: "positivo", label: "Positivo" },
  { id: "negativo", label: "Negativo" },
  { id: "neutro", label: "Neutro" },
];

const SIZES = [10, 20, 50];

type Filters = {
  q: string;
  tickers: string[];
  topic: string;
  publisher: string;
  sentiment: string;
  start: string;
  end: string;
  analyzed: "" | "true" | "false";
  sort: "recent" | "oldest" | "relevance";
  page: number;
  size: number;
};

const EMPTY_FILTERS: Filters = {
  q: "",
  tickers: [],
  topic: "",
  publisher: "",
  sentiment: "",
  start: "",
  end: "",
  analyzed: "",
  sort: "recent",
  page: 1,
  size: 20,
};

function day(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return parsed.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function moment(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function sentimentChip(sentiment?: string | null): string {
  if (sentiment === "positivo") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (sentiment === "negativo") return "border-rose-400/30 bg-rose-400/10 text-rose-300";
  if (sentiment === "neutro") return "border-white/10 bg-white/5 text-muted-foreground";
  return "border-white/10 bg-white/5 text-muted-foreground/70";
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400";

export default function NewsPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<NewsStats | null>(null);
  const [result, setResult] = useState<NewsSearchResult | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [queryDraft, setQueryDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facetsOpen, setFacetsOpen] = useState(false);

  /* ------------------------------------------------------------- recolha */
  const [collectTickers, setCollectTickers] = useState("");
  const [collectTopics, setCollectTopics] = useState("");
  const [maxItems, setMaxItems] = useState(20);
  const [collecting, setCollecting] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [collectResult, setCollectResult] = useState<NewsCollectResult | null>(null);
  const [collectError, setCollectError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    try {
      setStats(await getNewsStats());
    } catch {
      /* o cabeçalho mostra o que houver */
    }
  }, []);

  const runSearch = useCallback(async (active: Filters, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const payload = await searchNews({
        q: active.q || undefined,
        tickers: active.tickers.length ? active.tickers : undefined,
        topic: active.topic || undefined,
        publisher: active.publisher || undefined,
        sentiment: active.sentiment || undefined,
        start: active.start || undefined,
        end: active.end || undefined,
        analyzed: active.analyzed === "" ? undefined : active.analyzed === "true",
        sort: active.sort,
        page: active.page,
        size: active.size,
      });
      setResult(payload);
      setError(payload.error ? payload.error : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa de notícias.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    void runSearch(filters);
  }, [filters, runSearch]);

  const patch = useCallback((changes: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...changes, page: changes.page ?? 1 }));
  }, []);

  const toggleTicker = useCallback(
    (code: string) => {
      setFilters((current) => {
        const has = current.tickers.includes(code);
        return {
          ...current,
          tickers: has ? current.tickers.filter((item) => item !== code) : [...current.tickers, code],
          page: 1,
        };
      });
    },
    [],
  );

  const activeCount = useMemo(() => {
    let total = 0;
    if (filters.q) total += 1;
    total += filters.tickers.length;
    if (filters.topic) total += 1;
    if (filters.publisher) total += 1;
    if (filters.sentiment) total += 1;
    if (filters.start) total += 1;
    if (filters.end) total += 1;
    if (filters.analyzed) total += 1;
    return total;
  }, [filters]);

  /* ------------------------------------------------------------ recolher */
  const useFavourites = useCallback(async () => {
    try {
      const payload = await getSentimentMarketWatchlist();
      setCollectTickers(payload.tickers.join(", "));
    } catch {
      setCollectError("Não foi possível ler os favoritos guardados.");
    }
  }, []);

  /**
   * Recolher: corre **alvo a alvo** para o progresso ser visível.
   *
   * Por ticker a recolha leva o NLP completo (tradução incluída), pelo que um
   * pedido único de vários tickers deixaria o botão parado minutos sem dizer nada.
   * Os temas vão num pedido só (são rápidos).
   */
  const runCollect = useCallback(async () => {
    setCollecting(true);
    setCollectError(null);
    setCollectResult(null);
    const tickers = collectTickers
      .split(/[\s,;]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    const topics = collectTopics
      .split(/[;\n]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const targets: NewsCollectTarget[] = [];
    let indexed = 0;
    let analyzed = 0;
    let latest: NewsStats | null = stats;
    const absorb = (payload: NewsCollectResult) => {
      targets.push(...payload.results);
      indexed += payload.indexed;
      analyzed += payload.analyzed;
      latest = payload.stats;
    };
    try {
      if (!tickers.length && !topics.length) {
        // Sem nada indicado o servidor usa os favoritos guardados.
        setProgress("favoritos");
        absorb(await collectNews({ max_items: maxItems }));
      }
      for (const [index, code] of tickers.entries()) {
        setProgress(`${index + 1}/${tickers.length} · ${code}`);
        try {
          absorb(await collectNews({ tickers: [code], max_items: maxItems }));
        } catch (err) {
          targets.push({
            target: code,
            kind: "ticker",
            indexed: 0,
            total: 0,
            analyzed: 0,
            error: err instanceof Error ? err.message : "falhou",
          });
        }
      }
      if (topics.length) {
        setProgress(`temas · ${topics.length}`);
        try {
          absorb(await collectNews({ topics, max_items: maxItems }));
        } catch (err) {
          setCollectError(err instanceof Error ? err.message : "Falha na recolha por tema.");
        }
      }
      setCollectResult({
        ok: !targets.some((item) => item.error),
        tickers,
        topics,
        max_items: maxItems,
        indexed,
        analyzed,
        results: targets,
        stats: latest ?? ({} as NewsStats),
      });
      if (latest) setStats(latest);
      await runSearch(filters, true);
    } catch (err) {
      setCollectError(err instanceof Error ? err.message : "Falha na recolha de notícias.");
    } finally {
      setCollecting(false);
      setProgress(null);
    }
  }, [collectTickers, collectTopics, maxItems, runSearch, filters, stats]);

  const items = result?.items ?? [];
  const facets = result?.facets;

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">
        {/* Cabeçalho */}
        <header>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
            <Sparkles size={14} /> Índice {stats?.index ?? "finance_news"}
          </div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/20 to-blue-500/20 border border-white/10">
              <Newspaper size={28} className="text-teal-400" />
            </span>
            Notícias
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Recolhe notícias para o Elasticsearch e procura-as com filtros e facetas — é o mesmo
            índice que alimenta o sentimento de mercado, a Pesquisa total e o RAG.
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span>
              Documentos: <strong className="text-foreground">{stats?.documents ?? 0}</strong>
            </span>
            <span>
              Tickers: <strong className="text-foreground">{stats?.tickers ?? 0}</strong>
            </span>
            <span>
              Fontes: <strong className="text-foreground">{stats?.publishers ?? 0}</strong>
            </span>
            <span>
              Com análise:{" "}
              <strong className="text-foreground">
                {stats?.analyzed ?? 0}
                {stats?.analyzed_share != null ? ` (${Math.round(stats.analyzed_share * 100)} %)` : ""}
              </strong>
            </span>
            <span>
              Janela: <strong className="text-foreground">{day(stats?.first_published)}</strong> a{" "}
              <strong className="text-foreground">{day(stats?.last_published)}</strong>
            </span>
            <span>
              Última recolha: <strong className="text-foreground">{moment(stats?.last_ingest)}</strong>
            </span>
          </div>
        </header>

        {/* Recolha */}
        <section className="glass-card rounded-2xl p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Sparkles size={15} className="text-teal-400" /> Recolher para o Elasticsearch
          </h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Por ticker a notícia leva sentimento, tradução, tópicos e entidades; por tema é mais
            rápido (léxico bilingue). Sem nada indicado, recolhe para os favoritos do painel de mercado.
          </p>

          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <div>
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-muted-foreground">Tickers</label>
                <button
                  onClick={() => void useFavourites()}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] hover:bg-white/10"
                  title="Preencher com os favoritos guardados"
                >
                  <Star size={10} /> favoritos
                </button>
              </div>
              <input
                value={collectTickers}
                onChange={(event) => setCollectTickers(event.target.value)}
                placeholder="AAPL, MSFT, EDP.LS"
                autoComplete="off"
                className={`${inputClass} mt-1`}
              />
            </div>
            <div>
              <label className="text-[11px] font-medium text-muted-foreground">Temas (texto livre)</label>
              <input
                value={collectTopics}
                onChange={(event) => setCollectTopics(event.target.value)}
                placeholder="energia; Galp; renewable energy"
                autoComplete="off"
                className={`${inputClass} mt-1`}
              />
            </div>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <label className="text-[11px] font-medium text-muted-foreground">Notícias por tema</label>
                <select
                  value={maxItems}
                  onChange={(event) => setMaxItems(Number(event.target.value))}
                  className={`${inputClass} mt-1`}
                >
                  {[10, 20, 30, 50].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={() => void runCollect()}
                disabled={collecting || !user}
                title={user ? "Recolher agora" : "Entra na plataforma para recolher"}
                className="inline-flex min-h-[38px] items-center gap-2 rounded-xl bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {collecting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                {collecting ? progress ?? "A recolher…" : "Recolher"}
              </button>
            </div>
          </div>

          {collectError ? (
            <p className="mt-3 flex items-start gap-2 text-[11px] text-rose-300">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {collectError}
            </p>
          ) : null}

          {collectResult ? (
            <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="text-[11px] text-muted-foreground">
                {collectResult.results.length} alvo(s) ·{" "}
                <strong className="text-foreground">{collectResult.indexed}</strong> notícia(s)
                indexadas · <strong className="text-foreground">{collectResult.analyzed}</strong> analisadas
              </p>
              <div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {collectResult.results.map((item) => (
                  <div
                    key={`${item.kind}-${item.target}`}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-[11px] ${
                      item.error ? "border-amber-400/30 bg-amber-400/10 text-amber-200" : "border-white/10 bg-white/5"
                    }`}
                    title={item.error ?? undefined}
                  >
                    <span className="truncate">
                      {item.kind === "topic" ? "tema " : ""}
                      <strong>{item.target}</strong>
                    </span>
                    <span className="shrink-0 text-muted-foreground">
                      {item.error ? "falhou" : `${item.indexed}/${item.total} · ${item.analyzed} analisadas`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>

        {/* Pesquisa */}
        <section className="glass-card rounded-2xl p-5">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              patch({ q: queryDraft.trim() });
            }}
            className="flex flex-wrap items-center gap-2"
          >
            <div className="flex min-w-[240px] flex-1 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2">
              <Search size={15} className="text-muted-foreground" />
              <input
                value={queryDraft}
                onChange={(event) => setQueryDraft(event.target.value)}
                placeholder="Procurar nas notícias (título, resumo, fonte, temas)…"
                autoComplete="off"
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {queryDraft ? (
                <button
                  type="button"
                  onClick={() => {
                    setQueryDraft("");
                    patch({ q: "" });
                  }}
                  className="rounded-full p-1 text-muted-foreground hover:text-foreground"
                >
                  <X size={13} />
                </button>
              ) : null}
            </div>
            <select
              value={filters.sort}
              onChange={(event) => patch({ sort: event.target.value as Filters["sort"] })}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
            >
              {SORTS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
            >
              <Search size={13} /> Pesquisar
            </button>
            <button
              type="button"
              onClick={() => setFacetsOpen((current) => !current)}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 lg:hidden"
            >
              <Filter size={13} /> Filtros
              {activeCount ? (
                <span className="rounded-full bg-teal-500/20 px-1.5 text-[10px] text-teal-200">{activeCount}</span>
              ) : null}
            </button>
            <button
              type="button"
              onClick={() => {
                setFilters(EMPTY_FILTERS);
                setQueryDraft("");
              }}
              disabled={!activeCount}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40"
            >
              <X size={13} /> Limpar
            </button>
          </form>

          {/* Filtros ativos */}
          {activeCount ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="text-muted-foreground">Filtros:</span>
              {filters.tickers.map((code) => (
                <button
                  key={code}
                  onClick={() => toggleTicker(code)}
                  className="inline-flex items-center gap-1 rounded-full border border-teal-400/30 bg-teal-400/10 px-2 py-0.5 text-teal-200"
                >
                  {code} <X size={10} />
                </button>
              ))}
              {filters.topic ? (
                <button
                  onClick={() => patch({ topic: "" })}
                  className="inline-flex items-center gap-1 rounded-full border border-violet-400/30 bg-violet-400/10 px-2 py-0.5 text-violet-200"
                >
                  tema: {filters.topic} <X size={10} />
                </button>
              ) : null}
              {filters.publisher ? (
                <button
                  onClick={() => patch({ publisher: "" })}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5"
                >
                  fonte: {filters.publisher} <X size={10} />
                </button>
              ) : null}
              {filters.sentiment ? (
                <button
                  onClick={() => patch({ sentiment: "" })}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5"
                >
                  tom: {filters.sentiment} <X size={10} />
                </button>
              ) : null}
              {filters.start || filters.end ? (
                <button
                  onClick={() => patch({ start: "", end: "" })}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5"
                >
                  {filters.start || "…"} → {filters.end || "…"} <X size={10} />
                </button>
              ) : null}
              {filters.analyzed ? (
                <button
                  onClick={() => patch({ analyzed: "" })}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5"
                >
                  {filters.analyzed === "true" ? "só analisadas" : "só sem análise"} <X size={10} />
                </button>
              ) : null}
            </div>
          ) : null}
        </section>

        <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
          {/* Facetas / filtros */}
          <aside className={`${facetsOpen ? "block" : "hidden"} lg:block space-y-4`}>
            <FacetCard title="Tickers" buckets={facets?.tickers} onPick={toggleTicker} active={filters.tickers} />
            <FacetCard
              title="Temas recolhidos"
              buckets={facets?.topics}
              onPick={(value) => patch({ topic: filters.topic === value ? "" : value })}
              active={filters.topic ? [filters.topic] : []}
            />
            <FacetCard
              title="Fontes"
              buckets={facets?.publishers}
              onPick={(value) => patch({ publisher: filters.publisher === value ? "" : value })}
              active={filters.publisher ? [filters.publisher] : []}
            />
            <FacetCard
              title="Sentimento"
              buckets={facets?.sentiments}
              onPick={(value) => patch({ sentiment: filters.sentiment === value ? "" : value })}
              active={filters.sentiment ? [filters.sentiment] : []}
            />

            <div className="glass-card rounded-2xl p-4 space-y-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Período</p>
              <input
                type="date"
                value={filters.start}
                onChange={(event) => patch({ start: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[11px]"
              />
              <input
                type="date"
                value={filters.end}
                onChange={(event) => patch({ end: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[11px]"
              />
              <div className="flex flex-wrap gap-1">
                {SENTIMENTS.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => patch({ sentiment: filters.sentiment === option.id ? "" : option.id })}
                    className={`rounded-full border px-2 py-0.5 text-[10px] ${sentimentChip(option.id)}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => patch({ analyzed: filters.analyzed === "true" ? "" : "true" })}
                  className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] hover:bg-white/10"
                >
                  só analisadas
                </button>
                <button
                  onClick={() => patch({ analyzed: filters.analyzed === "false" ? "" : "false" })}
                  className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] hover:bg-white/10"
                >
                  sem análise
                </button>
                <select
                  value={filters.size}
                  onChange={(event) => patch({ size: Number(event.target.value) })}
                  className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px]"
                >
                  {SIZES.map((value) => (
                    <option key={value} value={value}>
                      {value} por página
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </aside>

          {/* Resultados */}
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span>
                {loading ? (
                  <span className="inline-flex items-center gap-1">
                    <Loader2 size={12} className="animate-spin" /> a procurar…
                  </span>
                ) : (
                  <>
                    <strong className="text-foreground">{result?.total ?? 0}</strong> notícia(s)
                    {result && result.pages > 1 ? ` · página ${result.page} de ${result.pages}` : ""}
                  </>
                )}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setFilters((current) => ({ ...current, page: Math.max(1, current.page - 1) }))}
                  disabled={(result?.page ?? 1) <= 1}
                  className="rounded-lg border border-white/10 bg-white/5 p-1.5 hover:bg-white/10 disabled:opacity-40"
                >
                  <ChevronLeft size={13} />
                </button>
                <button
                  onClick={() => setFilters((current) => ({ ...current, page: current.page + 1 }))}
                  disabled={!result || result.page >= result.pages}
                  className="rounded-lg border border-white/10 bg-white/5 p-1.5 hover:bg-white/10 disabled:opacity-40"
                >
                  <ChevronRight size={13} />
                </button>
                <button
                  onClick={() => {
                    void loadStats();
                    void runSearch(filters);
                  }}
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 hover:bg-white/10"
                >
                  <RefreshCw size={12} /> Atualizar
                </button>
              </div>
            </div>

            {error ? (
              <p className="flex items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[11px] text-rose-300">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
              </p>
            ) : null}

            {items.map((item) => (
              <NewsCard key={item.id} item={item} onPickTicker={toggleTicker} onPickPublisher={(value) => patch({ publisher: value })} />
            ))}

            {!loading && !items.length && !error ? (
              <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-6 text-center text-xs text-muted-foreground">
                Sem notícias para estes filtros. Recolhe primeiro (por ticker ou tema) ou alarga a pesquisa.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Lista de facetas clicáveis (tickers, temas, fontes, sentimentos). */
function FacetCard({
  title,
  buckets,
  onPick,
  active,
}: {
  title: string;
  buckets?: NewsFacetBucket[];
  onPick: (value: string) => void;
  active: string[];
}) {
  if (!buckets?.length) return null;
  return (
    <div className="glass-card rounded-2xl p-4">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Tag size={12} /> {title}
      </p>
      <div className="flex flex-wrap gap-1">
        {buckets.slice(0, 18).map((bucket) => {
          const value = String(bucket.value ?? "");
          const on = active.includes(value);
          return (
            <button
              key={value}
              onClick={() => onPick(value)}
              title={`${bucket.count} notícia(s)`}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition ${
                on
                  ? "border-teal-400/40 bg-teal-400/15 text-teal-100"
                  : "border-white/10 bg-white/5 hover:bg-white/10"
              }`}
            >
              <span className="max-w-[140px] truncate">{value}</span>
              <span className="text-muted-foreground">{bucket.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Cartão de uma notícia: título (traduzido quando existe), fonte, tom e ligações. */
function NewsCard({
  item,
  onPickTicker,
  onPickPublisher,
}: {
  item: NewsDoc;
  onPickTicker: (code: string) => void;
  onPickPublisher: (value: string) => void;
}) {
  const title = item.title || "(sem título)";
  const translated = item.translated_title && item.translated_title !== item.title ? item.translated_title : null;
  const summary = item.summary_pt || item.translated_summary || item.summary || null;

  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        {item.ticker ? (
          <button
            onClick={() => onPickTicker(item.ticker)}
            className="rounded-full border border-teal-400/30 bg-teal-400/10 px-2 py-0.5 font-semibold text-teal-200 hover:bg-teal-400/20"
          >
            {item.ticker}
          </button>
        ) : null}
        {item.topic ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-violet-400/30 bg-violet-400/10 px-2 py-0.5 text-violet-200">
            <Tag size={10} /> {item.topic}
          </span>
        ) : null}
        {item.publisher ? (
          <button
            onClick={() => onPickPublisher(item.publisher as string)}
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
          >
            <Building2 size={11} /> {item.publisher}
          </button>
        ) : null}
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <CalendarDays size={11} /> {day(item.published)}
        </span>
        <span className={`ml-auto rounded-full border px-2 py-0.5 ${sentimentChip(item.sentiment)}`}>
          {item.sentiment ?? "sem análise"}
        </span>
      </div>

      <h3 className="mt-2 text-sm font-semibold leading-snug">{title}</h3>
      {translated ? <p className="mt-0.5 text-xs text-muted-foreground">{translated}</p> : null}
      {summary ? <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{summary}</p> : null}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
        {(item.topics ?? []).slice(0, 5).map((topic) => (
          <span key={topic} className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5">
            {topic}
          </span>
        ))}
        {(item.entities ?? []).slice(0, 4).map((entity) => (
          <span key={entity.name} className="text-muted-foreground/80">
            {entity.name}
          </span>
        ))}
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-teal-300 hover:underline"
          >
            <ExternalLink size={11} /> abrir
          </a>
        ) : null}
      </div>
    </article>
  );
}
