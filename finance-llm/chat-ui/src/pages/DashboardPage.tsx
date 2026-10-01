/**
 * Painel do mercado **em direto** (rota `/dashboard`).
 *
 * Não há aqui números escritos à mão: tudo vem de uma única leitura ao Yahoo
 * Finance (`GET /sentiment/market/live`), feita a cada pedido —
 *
 * * **cotações** com a variação **do dia** (`lastPrice / previousClose − 1`);
 * * **manchetes** com o tom lido pelo léxico (PT e bilingue PT/EN);
 * * **movimentos** e **oportunidades** (tom acima/abaixo do preço);
 * * a **contraprova** de cada cotação, lida por um segundo caminho do Yahoo.
 *
 * O que não vier da fonte aparece como erro, nunca como valor suposto. O painel
 * refresca sozinho a cada minuto (e a pedido) e mostra sempre a hora da última
 * leitura, para não haver dúvida sobre a idade do que está à vista.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Loader2,
  MessageSquare,
  Newspaper,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  Target,
  TrendingUp,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { getTickerHistory, searchYahooTickers } from "../api";
import { useAuth } from "../auth";
import {
  addSentimentMarketFavourite,
  getSentimentMarketLive,
  getSentimentMarketWatchlist,
  removeSentimentMarketFavourite,
  type MarketLive,
  type MarketLiveOpportunity,
  type MarketLiveQuote,
} from "../sentimentApi";
import type { TickerHistory } from "../types";

/** Índices do topo (a variação é sempre a do dia). */
const INDICES = [
  { ticker: "^GSPC", label: "S&P 500" },
  { ticker: "^IXIC", label: "NASDAQ" },
  { ticker: "BTC-USD", label: "Bitcoin" },
];

/** Carteira lida em direto (movimentos, tom e oportunidades). */
const DEFAULT_FAVOURITES = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "EDP.LS"];

const INDEX_TICKERS = INDICES.map((item) => item.ticker);

/** Intervalo da leitura automática (o Yahoo não serve dados em menos de um minuto). */
const REFRESH_MS = 60_000;

const REFRESH_OPTIONS = [
  { id: 0, label: "Manual" },
  { id: 60_000, label: "1 min" },
  { id: 300_000, label: "5 min" },
];

const READING_LABELS: Record<string, string> = {
  tom_acima_do_preco: "Tom acima do preço",
  preco_acima_do_tom: "Preço acima do tom",
};

const MATERIAL_LABELS: Record<string, string> = {
  "lexico-pt": "léxico PT",
  bilingue: "léxico bilingue",
  traduzido: "traduzido",
  "sem-texto": "sem texto",
};

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)} %`;
}

function share(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)} %`;
}

function stamp(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function when(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function labelChip(label: string | null | undefined): string {
  if (label === "positivo") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (label === "negativo") return "border-rose-400/30 bg-rose-400/10 text-rose-300";
  return "border-white/10 bg-white/5 text-muted-foreground";
}

function changeTone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-emerald-400" : "text-red-400";
}

/** Série de fechos para a sparkline do índice (mesma fonte das cotações). */
function sparkData(history?: TickerHistory | null) {
  if (!history?.points?.length) return [];
  return history.points.map((point) => ({ date: point.date, value: point.close ?? point.open ?? undefined }));
}

export function DashboardPage({
  onSwitchView,
  onSelectTicker,
}: {
  onSwitchView?: (view: string) => void;
  onSelectTicker?: (ticker: string) => void;
}) {
  const { user } = useAuth();
  const [live, setLive] = useState<MarketLive | null>(null);
  const [sparks, setSparks] = useState<Record<string, TickerHistory>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshMs, setRefreshMs] = useState(REFRESH_MS);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<{ symbol: string; name?: string; exchange?: string }[]>(
    [],
  );
  /* ------------------------------------------------------- favoritos */
  const [favourites, setFavourites] = useState<string[]>([]);
  const [favouritesReady, setFavouritesReady] = useState(false);
  const [suggested, setSuggested] = useState<string[]>([]);
  const [favMax, setFavMax] = useState(60);
  const [favInput, setFavInput] = useState("");
  const [favResults, setFavResults] = useState<{ symbol: string; name?: string; exchange?: string }[]>([]);
  const [favBusy, setFavBusy] = useState<string | null>(null);
  const [favError, setFavError] = useState<string | null>(null);
  const [favNotice, setFavNotice] = useState<string | null>(null);

  /** Tickers à vista: os índices do topo + os favoritos guardados. */
  const liveTickers = useMemo(
    () => [...INDEX_TICKERS, ...(favourites.length ? favourites : DEFAULT_FAVOURITES)],
    [favourites],
  );
  const showingDefaults = favouritesReady && !favourites.length;

  /** Leitura completa ao Yahoo (o painel nunca mostra dados guardados). */
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const payload = await getSentimentMarketLive(liveTickers, 5);
      setLive(payload);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao ler o mercado no Yahoo Finance.");
    } finally {
      setLoading(false);
    }
  }, [liveTickers]);

  /** Favoritos guardados (leitura leve, independente dos índices). */
  const loadFavourites = useCallback(async () => {
    try {
      const payload = await getSentimentMarketWatchlist();
      setFavourites(payload.tickers);
      setSuggested(payload.suggested);
      setFavMax(payload.max);
    } catch {
      setFavourites([]);
    } finally {
      setFavouritesReady(true);
    }
  }, []);

  const syncFavourites = useCallback(
    (payload: { watchlist: string[] }) => {
      setFavourites(payload.watchlist.filter((code) => !INDEX_TICKERS.includes(code)));
      void loadFavourites();
    },
    [loadFavourites],
  );

  const addFavourite = useCallback(
    async (raw: string) => {
      const ticker = raw.trim().toUpperCase();
      if (!ticker) return;
      setFavBusy(ticker);
      setFavError(null);
      try {
        const payload = await addSentimentMarketFavourite(ticker);
        syncFavourites(payload);
        setFavInput("");
        setFavResults([]);
        const price = payload.quote?.price;
        setFavNotice(
          INDEX_TICKERS.includes(payload.ticker)
            ? `${payload.ticker} guardado — é um índice e está sempre no topo do painel.`
            : `${payload.ticker} guardado nos favoritos${price ? ` · ${num(price)} ${payload.quote?.currency ?? ""}` : ""}.`,
        );
      } catch (err) {
        setFavError(err instanceof Error ? err.message : "Não foi possível guardar o ticker.");
      } finally {
        setFavBusy(null);
      }
    },
    [syncFavourites],
  );

  const removeFavourite = useCallback(
    async (code: string) => {
      setFavBusy(code);
      setFavError(null);
      try {
        const payload = await removeSentimentMarketFavourite(code);
        syncFavourites(payload);
        setFavNotice(`${code} saiu dos favoritos.`);
      } catch (err) {
        setFavError(err instanceof Error ? err.message : "Não foi possível retirar o ticker.");
      } finally {
        setFavBusy(null);
      }
    },
    [syncFavourites],
  );

  useEffect(() => {
    void loadFavourites();
  }, [loadFavourites]);

  useEffect(() => {
    if (!favNotice) return;
    const timer = window.setTimeout(() => setFavNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [favNotice]);

  /** Sugestões do Yahoo para a caixa de favoritos (com atraso, como a pesquisa). */
  useEffect(() => {
    const timer = setTimeout(async () => {
      const query = favInput.trim();
      if (query.length < 2) {
        setFavResults([]);
        return;
      }
      try {
        const res = await searchYahooTickers(query);
        setFavResults((res.yahoo_results || []).slice(0, 6));
      } catch {
        setFavResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [favInput]);

  /** Séries de apoio do topo (1 mês, a mesma fonte das cotações). */
  const loadSparks = useCallback(async () => {
    const next: Record<string, TickerHistory> = {};
    await Promise.all(
      INDICES.map(async (item) => {
        try {
          next[item.ticker] = await getTickerHistory(item.ticker, "1mo");
        } catch {
          /* sem série para este índice */
        }
      }),
    );
    setSparks(next);
  }, []);

  useEffect(() => {
    void load();
    void loadSparks();
  }, [load, loadSparks]);

  useEffect(() => {
    if (!refreshMs) return;
    const timer = window.setInterval(() => {
      void load(true);
      void loadSparks();
    }, refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs, load, loadSparks]);

  useEffect(() => {
    const timer = setTimeout(async () => {
      if (search.trim().length < 2) {
        setSearchResults([]);
        return;
      }
      try {
        const res = await searchYahooTickers(search.trim());
        setSearchResults((res.yahoo_results || []).slice(0, 6));
      } catch {
        setSearchResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  function handleSelect(symbol: string) {
    if (onSelectTicker) onSelectTicker(symbol);
    else if (onSwitchView) onSwitchView("ticker-detail");
  }

  const byTicker = useMemo(
    () => new Map((live?.quotes ?? []).map((quote) => [quote.ticker, quote])),
    [live],
  );

  const movers = useMemo(() => {
    const rows = [...(live?.movers.up ?? []), ...(live?.movers.down ?? [])];
    return rows.sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0)).slice(0, 6);
  }, [live]);

  const summary = live?.summary;
  const validation = live?.validation;
  const failed = validation?.failed ?? [];
  const erreurs = summary?.errors ?? [];

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Hero */}
        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-teal-300 mb-3">
            <Sparkles size={14} />
            Mercado em tempo real · {live?.source ?? "Yahoo Finance"}
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3 mb-2">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-teal-500/20 to-blue-500/20 border border-white/10">
              <BarChart3 size={32} className="text-teal-400" />
            </span>
            Sentiment Market Dashboard
          </h1>
          <p className="text-muted-foreground max-w-2xl">
            Resumo do mercado, notícias e oportunidades em tempo real — cotações, manchetes e tom lidos
            agora no Yahoo Finance.
          </p>
        </div>

        {/* Barra de estado: fonte, hora da leitura, validação e refresco */}
        <div className="glass-card rounded-2xl p-4 mb-6 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className={`inline-flex h-2 w-2 rounded-full ${error ? "bg-rose-400" : "bg-emerald-400"}`} />
            <span className="text-muted-foreground">
              Leitura de <strong className="text-foreground">{stamp(live?.generated_at)}</strong>
              {live ? ` · ${summary?.quoted ?? 0}/${summary?.tickers ?? 0} cotações` : ""}
            </span>
          </div>

          {validation?.enabled ? (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
                validation.ok
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
                  : "border-amber-400/30 bg-amber-400/10 text-amber-200"
              }`}
              title={`${validation.method} (tolerância ${validation.tolerance_pct} %)`}
            >
              <ShieldCheck size={13} />
              {validation.verified}/{validation.checked} confirmadas no Yahoo
            </span>
          ) : null}

          {error ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-400/30 bg-rose-400/10 px-2.5 py-1 text-[11px] text-rose-300">
              <AlertTriangle size={13} /> {error}
            </span>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center rounded-xl border border-white/10 bg-white/5 p-0.5">
              {REFRESH_OPTIONS.map((option) => (
                <button
                  key={option.id}
                  onClick={() => setRefreshMs(option.id)}
                  className={`rounded-lg px-2.5 py-1 text-[11px] transition ${
                    refreshMs === option.id ? "bg-white/10 text-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => {
                void load();
                void loadSparks();
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 transition"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Atualizar
            </button>
          </div>
        </div>

        {/* Search panel */}
        <div className="glass-card rounded-2xl p-5 mb-8 relative">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-background/60 px-3 py-2">
            <Search size={16} className="text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Pesquisar empresa, ticker ou tema..."
              className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground text-foreground"
            />
          </div>
          {searchResults.length > 0 && (
            <div className="absolute mt-2 left-5 right-5 rounded-xl border border-border bg-card/95 backdrop-blur-md shadow-xl overflow-hidden z-20">
              {searchResults.map((r) => (
                <button
                  key={r.symbol}
                  onClick={() => {
                    setSearch("");
                    setSearchResults([]);
                    handleSelect(r.symbol);
                  }}
                  className="w-full text-left px-4 py-2 hover:bg-white/5 transition text-sm"
                >
                  <span className="font-semibold">{r.symbol}</span>
                  <span className="text-muted-foreground ml-2">{r.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Os meus tickers: escolher o que ver e guardar como favoritos */}
        <section className="glass-card rounded-2xl p-5 mb-8">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-xl bg-violet-500/15 border border-violet-400/20">
                <Star size={16} className="text-violet-300" />
              </div>
              <div>
                <h2 className="text-sm font-semibold">Os meus tickers</h2>
                <p className="text-[11px] text-muted-foreground">
                  {favourites.length
                    ? `${favourites.length}/${favMax} guardados — é isto que o painel mostra.`
                    : "Ainda sem favoritos: o painel está a mostrar a carteira sugerida."}
                </p>
              </div>
            </div>
            <span className="ml-auto text-[11px] text-muted-foreground">
              {user ? "Guardado na plataforma" : "Entra na plataforma para guardar"}
            </span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {favourites.map((code) => (
              <span
                key={code}
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 pl-3 pr-1 py-1 text-xs"
              >
                <button onClick={() => handleSelect(code)} className="hover:text-teal-300" title="Ver o detalhe">
                  {code}
                </button>
                <button
                  onClick={() => void removeFavourite(code)}
                  disabled={!user || favBusy === code}
                  className="rounded-full p-1 text-muted-foreground hover:text-rose-300 disabled:opacity-40"
                  title={user ? "Retirar dos favoritos" : "Entra para guardar"}
                >
                  {favBusy === code ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
                </button>
              </span>
            ))}
            {!favourites.length
              ? DEFAULT_FAVOURITES.map((code) => (
                  <span
                    key={code}
                    className="inline-flex items-center rounded-full border border-dashed border-white/15 bg-white/[0.02] px-3 py-1 text-xs text-muted-foreground"
                  >
                    {code}
                  </span>
                ))
              : null}
          </div>

          <div className="mt-3 relative">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void addFavourite(favInput);
              }}
              className="flex items-center gap-2 rounded-xl border border-border bg-background/60 px-3 py-2"
            >
              <Plus size={15} className="text-muted-foreground" />
              <input
                value={favInput}
                onChange={(event) => setFavInput(event.target.value)}
                placeholder="Acrescentar ticker (ex.: EDP.LS, NVDA, BTC-USD)"
                autoComplete="off"
                className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground text-foreground"
              />
              <button
                type="submit"
                disabled={!user || !favInput.trim() || Boolean(favBusy)}
                className="rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs hover:bg-white/10 disabled:opacity-40"
              >
                {favBusy && favBusy === favInput.trim().toUpperCase() ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  "Guardar"
                )}
              </button>
            </form>
            {favResults.length > 0 ? (
              <div className="absolute mt-1 left-0 right-0 rounded-xl border border-border bg-card/95 backdrop-blur-md shadow-xl overflow-hidden z-30">
                {favResults.map((result) => (
                  <div key={result.symbol} className="flex items-center gap-2 px-3 py-2 hover:bg-white/5">
                    <button onClick={() => handleSelect(result.symbol)} className="flex-1 text-left text-sm">
                      <span className="font-semibold">{result.symbol}</span>
                      <span className="text-muted-foreground ml-2 text-xs">
                        {result.name}
                        {result.exchange ? ` · ${result.exchange}` : ""}
                      </span>
                    </button>
                    <button
                      onClick={() => void addFavourite(result.symbol)}
                      disabled={!user || favourites.includes(result.symbol)}
                      title={favourites.includes(result.symbol) ? "Já está nos favoritos" : "Guardar nos favoritos"}
                      className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] hover:bg-white/10 disabled:opacity-40"
                    >
                      {favourites.includes(result.symbol) ? "guardado" : "+ favorito"}
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          {suggested.length ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span>Sugeridos:</span>
              {suggested.map((code) => (
                <button
                  key={code}
                  onClick={() => void addFavourite(code)}
                  disabled={!user || Boolean(favBusy)}
                  className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 hover:bg-white/10 disabled:opacity-40"
                >
                  + {code}
                </button>
              ))}
            </div>
          ) : null}

          {favError ? (
            <p className="mt-3 flex items-start gap-2 text-[11px] text-rose-300">
              <XCircle size={13} className="mt-0.5 shrink-0" />
              {favError}
            </p>
          ) : null}
          {favNotice ? (
            <p className="mt-3 flex items-start gap-2 text-[11px] text-emerald-300">
              <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
              {favNotice}
            </p>
          ) : null}
          {showingDefaults ? (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Guarda os que te interessam e o painel passa a mostrar só esses (os índices do topo mantêm-se).
            </p>
          ) : null}
        </section>

        {/* Índices */}
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8 fade-in">
          {INDICES.map((item, i) => {
            const quote = byTicker.get(item.ticker);
            const change = quote?.change_pct ?? null;
            const positive = (change ?? 0) >= 0;
            const glows = ["glow-teal", "glow-amber", "glow-blue"];
            return (
              <div
                key={item.ticker}
                className={`glass-card gradient-border rounded-2xl p-5 ${glows[i % glows.length]} cursor-pointer hover:bg-white/[0.04] transition`}
                onClick={() => handleSelect(item.ticker)}
              >
                <div className="flex items-center justify-between">
                  <div className="text-xs text-muted-foreground uppercase tracking-wider">{quote?.ticker ?? item.label}</div>
                  {quote?.verified ? (
                    <span title="Confirmado no Yahoo Finance" className="text-emerald-400">
                      <CheckCircle2 size={14} />
                    </span>
                  ) : null}
                </div>
                <div className="flex items-end justify-between mt-2">
                  <div className="text-2xl md:text-3xl font-bold stat-value">{num(quote?.price)}</div>
                  <div className={`flex items-center gap-1 text-sm font-medium whitespace-nowrap ${changeTone(change)}`}>
                    {positive ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                    {pct(change)}
                  </div>
                </div>
                <div className="mt-2 text-[11px] text-muted-foreground">
                  {item.label} · {quote?.currency ?? "—"} · fecho anterior {num(quote?.previous_close)}
                </div>
                <div className="mt-3 h-12">
                  <Sparkline data={sparkData(sparks[item.ticker])} positive={positive} />
                </div>
              </div>
            );
          })}
          {loading && !live
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="glass-card gradient-border rounded-2xl p-5 animate-pulse h-40" />
              ))
            : null}
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Sentimento do mercado (real: manchetes lidas agora) */}
          <div className="glass-card gradient-border rounded-2xl p-5 glow-teal">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-xl bg-teal-500/15 border border-teal-400/20">
                  <Activity size={18} className="text-teal-400" />
                </div>
                <h3 className="font-semibold">Sentimento do Mercado</h3>
              </div>
              <span
                className={`text-[11px] px-2 py-0.5 rounded-full border ${labelChip(summary?.label)}`}
                title="Média da polaridade das manchetes distintas da carteira"
              >
                {summary?.label ?? "sem leitura"}
              </span>
            </div>

            <div className="flex items-center gap-6">
              <div className="relative w-28 h-28 shrink-0">
                <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
                  <path
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                    fill="none"
                    stroke="#1e2128"
                    strokeWidth="4"
                  />
                  <path
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                    fill="none"
                    stroke="#10b981"
                    strokeDasharray={`${(summary?.positive_share ?? 0) * 100}, 100`}
                    strokeWidth="4"
                    strokeLinecap="round"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-bold stat-value">{share(summary?.positive_share)}</span>
                  <span className="text-xs font-medium text-emerald-400">Positivo</span>
                </div>
              </div>
              <div className="flex-1 space-y-3">
                <SentimentRow
                  color="#10b981"
                  label="Positivo"
                  value={summary?.positive ?? 0}
                  shareValue={summary?.positive_share}
                />
                <SentimentRow
                  color="#9ca3af"
                  label="Neutro"
                  value={summary?.neutral ?? 0}
                  shareValue={summary?.neutral_share}
                />
                <SentimentRow
                  color="#ef4444"
                  label="Negativo"
                  value={summary?.negative ?? 0}
                  shareValue={summary?.negative_share}
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
              <span>
                Manchetes distintas: <strong className="text-foreground">{summary?.news ?? 0}</strong>
              </span>
              <span>
                Com vocabulário: <strong className="text-foreground">{share(summary?.coverage)}</strong>
              </span>
              <span>
                Tom médio: <strong className="text-foreground">{(summary?.sentiment ?? 0).toFixed(3)}</strong>
              </span>
              <span>
                Em alta / em baixa:{" "}
                <strong className="text-foreground">
                  {summary?.advancers ?? 0}/{summary?.decliners ?? 0}
                </strong>
              </span>
            </div>
            {live?.translated ? null : (
              <p className="mt-3 text-[10px] text-muted-foreground">
                Tom lido pelo léxico PT e, nas manchetes em inglês, pelo léxico bilingue — sem tradução
                (a tradução fina é opcional e muito mais lenta).
              </p>
            )}
          </div>

          {/* Top movimentações (reais, ordenadas pela variação do dia) */}
          <div className="lg:col-span-2 glass-card gradient-border rounded-2xl p-6">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-xl bg-amber-500/15 border border-amber-400/20">
                  <TrendingUp size={18} className="text-amber-400" />
                </div>
                <h3 className="font-semibold">Top Movimentações do Dia</h3>
              </div>
              <span className="text-[11px] text-muted-foreground">variação vs fecho anterior</span>
            </div>
            <div className="space-y-2">
              {movers.map((item) => (
                <button
                  key={item.ticker}
                  onClick={() => handleSelect(item.ticker)}
                  className="w-full flex items-center gap-4 p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition group"
                >
                  <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center text-sm font-bold shrink-0">
                    {item.ticker.slice(0, 2)}
                  </div>
                  <div className="flex-1 text-left min-w-0">
                    <div className="font-semibold group-hover:text-teal-300 transition truncate">{item.ticker}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.news_count} manchete(s) · tom{" "}
                      <span className={labelChip(item.label).includes("emerald") ? "text-emerald-300" : "text-muted-foreground"}>
                        {item.label ?? "—"}
                      </span>
                      {item.verified ? " · confirmado" : ""}
                    </div>
                  </div>
                  <RangeBar quote={item} />
                  <div className="text-right">
                    <div className="font-semibold stat-value">{num(item.price)}</div>
                    <div className={`text-xs font-medium ${changeTone(item.change_pct)}`}>{pct(item.change_pct)}</div>
                  </div>
                </button>
              ))}
              {!movers.length && !loading ? (
                <p className="text-xs text-muted-foreground">
                  Sem movimentos para mostrar: o Yahoo não devolveu cotações para esta carteira.
                </p>
              ) : null}
              {loading && !live
                ? Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-14 rounded-xl bg-muted animate-pulse" />
                  ))
                : null}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Oportunidades: tom vs preço (medido, não previsto) */}
          <div className="glass-card gradient-border rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="p-2 rounded-xl bg-violet-500/15 border border-violet-400/20">
                <Target size={18} className="text-violet-300" />
              </div>
              <h3 className="font-semibold">Oportunidades</h3>
            </div>
            <div className="space-y-3">
              {(live?.opportunities ?? []).map((item) => (
                <OpportunityRow key={item.ticker} item={item} onSelect={handleSelect} />
              ))}
              {live && !live.opportunities.length ? (
                <p className="text-xs text-muted-foreground">
                  Sem desalinhamento relevante entre o tom e a variação do dia nesta leitura.
                </p>
              ) : null}
            </div>
            <p className="mt-4 text-[10px] text-muted-foreground">{live?.caveat}</p>
          </div>

          {/* Últimas notícias (com o tom lido em cada uma) */}
          <div className="glass-card gradient-border rounded-2xl p-6 lg:col-span-2">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-xl bg-blue-500/15 border border-blue-400/20">
                  <Newspaper size={18} className="text-blue-400" />
                </div>
                <h3 className="font-semibold">Últimas Notícias</h3>
              </div>
              <span className="text-[11px] text-muted-foreground">
                {live?.news.length ?? 0} manchete(s) distintas
              </span>
            </div>
            <div className="space-y-3">
              {(live?.news ?? []).slice(0, 8).map((item, i) => (
                <article
                  key={`${item.ticker}-${i}`}
                  className="flex items-start gap-4 p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition group"
                >
                  <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center shrink-0 text-xs font-bold">
                    {item.ticker.replace(/[\^.]/g, "").slice(0, 2) || "N"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        onClick={() => handleSelect(item.ticker)}
                        className="text-xs font-semibold text-teal-400 hover:underline"
                      >
                        {item.ticker}
                      </button>
                      <span className="text-xs text-muted-foreground">{when(item.published) || item.source}</span>
                    </div>
                    <div className="text-sm font-medium mt-0.5 line-clamp-2">{item.title}</div>
                    {item.title_pt ? (
                      <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{item.title_pt}</div>
                    ) : null}
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
                      <span>{item.source}</span>
                      <span>·</span>
                      <span title="De onde veio o tom">
                        {MATERIAL_LABELS[item.material] ?? item.material}
                        {item.hits ? ` (${item.hits} termo(s))` : ""}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <span className={`text-[11px] px-2 py-1 rounded-full border ${labelChip(item.label)}`}>
                      {item.label}
                    </span>
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-muted-foreground hover:text-teal-300 transition"
                        title="Abrir no Yahoo Finance"
                      >
                        <ExternalLink size={14} />
                      </a>
                    ) : null}
                  </div>
                </article>
              ))}
              {live && !live.news.length ? (
                <p className="text-xs text-muted-foreground">O Yahoo não devolveu manchetes para esta carteira.</p>
              ) : null}
              {loading && !live
                ? Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-16 rounded-xl bg-muted animate-pulse" />
                  ))
                : null}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Validação: o que foi confirmado e o que não bateu */}
          <div className="glass-card gradient-border rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="p-2 rounded-xl bg-emerald-500/15 border border-emerald-400/20">
                <ShieldCheck size={18} className="text-emerald-400" />
              </div>
              <h3 className="font-semibold">Validação no Yahoo</h3>
            </div>
            {validation?.enabled ? (
              <>
                <div
                  className={`text-2xl font-bold stat-value ${
                    validation.ok ? "text-emerald-400" : "text-amber-300"
                  }`}
                >
                  {validation.verified}/{validation.checked}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Cada cotação é relida por um segundo caminho do Yahoo ({validation.method}) e só conta
                  como confirmada dentro de {validation.tolerance_pct} %.
                </p>
                <div className="mt-4 space-y-2">
                  {failed.map((item) => (
                    <div key={item.ticker} className="flex items-start gap-2 text-[11px] text-amber-200">
                      <XCircle size={13} className="mt-0.5 shrink-0" />
                      <span>
                        <strong>{item.ticker}</strong> — {item.reason} (mostrado {num(item.shown)}, leitura
                        cruzada {num(item.cross_check)}).
                      </span>
                    </div>
                  ))}
                  {!failed.length ? (
                    <div className="flex items-start gap-2 text-[11px] text-emerald-300">
                      <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
                      <span>Todas as cotações à vista batem com a segunda leitura do Yahoo.</span>
                    </div>
                  ) : null}
                </div>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">Contraprova desligada nesta leitura.</p>
            )}

            {erreurs.length ? (
              <div className="mt-5 border-t border-white/10 pt-4">
                <p className="text-[11px] font-semibold text-rose-300 mb-2">Sem cotação</p>
                {erreurs.map((item) => (
                  <p key={item.ticker} className="text-[11px] text-muted-foreground">
                    <strong className="text-foreground">{item.ticker}</strong> — {item.error ?? "sem resposta"}
                  </p>
                ))}
              </div>
            ) : null}
          </div>

          {/* IA */}
          <div className="lg:col-span-2 glass-card gradient-border rounded-2xl p-6 glow-amber flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="p-2 rounded-xl bg-amber-500/15 border border-amber-400/20">
                  <Zap size={20} className="text-amber-400" />
                </div>
                <h3 className="font-semibold">IA a trabalhar para ti</h3>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                A leitura acima é factual: preços, manchetes e tom, com a hora e a contraprova à vista. Para
                cruzar isto com o resto da plataforma — empresas, contratos, dossiês e previsões —, pergunta
                ao chat. Podes também guardar o panorama como relatório em Sentimento → Mercado.
              </p>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              <button
                onClick={() => onSwitchView?.("chat")}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-3 text-primary-foreground font-medium hover:opacity-90 transition shadow-lg shadow-primary/20"
              >
                <MessageSquare size={18} />
                Começar conversa
              </button>
              <button
                onClick={() => onSwitchView?.("sentimento")}
                className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm hover:bg-white/10 transition"
              >
                Sentimento de mercado <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Oportunidade: desalinhamento entre o tom das manchetes e a variação do dia. */
function OpportunityRow({
  item,
  onSelect,
}: {
  item: MarketLiveOpportunity;
  onSelect: (ticker: string) => void;
}) {
  const above = item.reading === "tom_acima_do_preco";
  return (
    <button
      onClick={() => onSelect(item.ticker)}
      className="w-full text-left rounded-xl border border-white/5 bg-white/[0.03] p-3 hover:bg-white/[0.06] transition"
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-sm">{item.ticker}</span>
        <span
          className={`text-[11px] px-2 py-0.5 rounded-full border ${
            above
              ? "border-violet-400/30 bg-violet-400/10 text-violet-200"
              : "border-amber-400/30 bg-amber-400/10 text-amber-200"
          }`}
        >
          {READING_LABELS[item.reading] ?? item.reading}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
        <span>tom {item.sentiment.toFixed(3)}</span>
        <span>·</span>
        <span>{pct(item.change_pct)} hoje</span>
        <span>·</span>
        <span>{item.news} manchete(s)</span>
        <span>·</span>
        <span>desvio {item.gap > 0 ? "+" : ""}{item.gap.toFixed(2)}</span>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{item.rationale}</p>
    </button>
  );
}

function SentimentRow({
  color,
  label,
  value,
  shareValue,
}: {
  color: string;
  label: string;
  value: number;
  shareValue?: number | null;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-3 h-3 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-sm text-muted-foreground flex-1">{label}</span>
      <span className="text-xs text-muted-foreground">{value}</span>
      <span className="text-sm font-semibold stat-value w-14 text-right">{share(shareValue)}</span>
    </div>
  );
}

/** Posição do preço dentro do intervalo de 52 semanas (dados do Yahoo). */
function RangeBar({ quote }: { quote: MarketLiveQuote }) {
  const low = quote.year_low;
  const high = quote.year_high;
  const price = quote.price;
  if (low === null || high === null || price === null || high <= low) return null;
  const position = Math.max(0, Math.min(1, (price - low) / (high - low)));
  return (
    <div className="hidden sm:block w-24 shrink-0" title={`52 semanas: ${num(low)} – ${num(high)}`}>
      <div className="relative h-1.5 rounded-full bg-gradient-to-r from-rose-400/30 via-amber-300/30 to-emerald-400/30">
        <div className="absolute -top-1 h-3.5 w-0.5 bg-white" style={{ left: `${position * 100}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{num(low, 0)}</span>
        <span>{num(high, 0)}</span>
      </div>
    </div>
  );
}

function Sparkline({ data, positive }: { data: { date: string; value?: number }[]; positive: boolean }) {
  const valid = data.filter((d) => typeof d.value === "number");
  if (valid.length < 2) {
    return <div className="w-full h-full bg-muted/30 rounded" />;
  }
  const color = positive ? "#10b981" : "#ef4444";
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={valid} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <defs>
          <linearGradient id={`spark-${positive ? "up" : "down"}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="date" hide />
        <YAxis domain={["auto", "auto"]} hide />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#spark-${positive ? "up" : "down"})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
