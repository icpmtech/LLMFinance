/**
 * Sentimento de mercado — série diária por ticker.
 *
 * Mostra o panorama agregado das notícias indexadas: tom ponderado do mercado,
 * heatmap ticker × dia, rankings de variação contra a janela anterior e uma
 * tabela por ticker com detalhe (melhor/pior dia e destaques).
 *
 * A série é construída por um job diário (`/sentiment/market/build`) e é
 * idempotente por `ticker|dia`; os botões aqui só disparam a construção à mão.
 * Mobile-first: tudo em coluna no telemóvel, com as tabelas largas em
 * deslocamento horizontal e o detalhe em folha inferior (`Sheet`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Coins,
  Copy,
  Download,
  FileText,
  Flame,
  LineChart,
  Loader2,
  Plus,
  RefreshCw,
  ScrollText,
  Search,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "../auth";
import {
  buildSentimentMarket,
  followSentimentMarketTicker,
  getSentimentMarketAlerts,
  getSentimentMarketBrief,
  getSentimentMarketDivergence,
  getSentimentMarketOverview,
  getSentimentMarketPrice,
  getSentimentMarketSeries,
  getSentimentMarketState,
  getSentimentMarketTicker,
  listSentimentMarketTickers,
  reloadSentimentMarketSchedule,
  saveSentimentMarketBriefToOffice,
  saveSentimentMarketSchedule,
  saveSentimentMarketToOffice,
  sentimentMarketExportUrl,
  unfollowSentimentMarketTicker,
  type MarketAlert,
  type MarketAlerts,
  type MarketBrief,
  type MarketCorrelation,
  type MarketCoverage,
  type MarketDivergence,
  type MarketFollowResult,
  type MarketOverview,
  type MarketSchedule,
  type MarketTickerDetail,
  type MarketTickerList,
  type MarketTickerStats,
} from "../sentimentApi";
import { Btn, Chip, Kpi, MiniBars, PolarityBar, Segmented, clock, focusRing, heatClass, labelChip, number, percent, shortDay, signed, tap, tone } from "../components/sentiment/SentimentKit";

const WINDOWS = [
  { id: 7, label: "7 dias" },
  { id: 30, label: "30 dias" },
  { id: 90, label: "90 dias" },
];

/** Cor da etiqueta de severidade do alerta. */
function severityChip(severity: string): string {
  if (severity === "alta") return "border-rose-400/30 bg-rose-400/10 text-rose-200";
  if (severity === "media") return "border-amber-400/30 bg-amber-400/10 text-amber-100";
  return "border-white/10 bg-white/5 text-muted-foreground";
}

const SEVERITY_LABELS: Record<string, string> = { alta: "Alta", media: "Média", baixa: "Baixa" };

/** Leitura do desalinhamento entre tom e preço. */
const READING_LABELS: Record<string, string> = {
  alinhado: "Alinhado",
  tom_acima_do_preco: "Tom acima do preço",
  preco_acima_do_tom: "Preço acima do tom",
  amostra_insuficiente: "Amostra insuficiente",
  indeterminada: "Indeterminada",
};

function readingChip(reading: string): string {
  if (reading === "alinhado") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  if (reading === "amostra_insuficiente" || reading === "indeterminada") return "border-white/10 bg-white/5 text-muted-foreground";
  return "border-amber-400/30 bg-amber-400/10 text-amber-100";
}

function correlationText(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

/** Símbolo do alerta por tipo. */
function kindIcon(kind: string) {
  if (kind === "subida") return <TrendingUp size={12} className="text-emerald-300" />;
  if (kind === "descida") return <TrendingDown size={12} className="text-rose-300" />;
  if (kind === "viragem") return <RefreshCw size={12} className="text-violet-300" />;
  if (kind === "cobertura") return <AlertTriangle size={12} className="text-amber-300" />;
  return <Flame size={12} className="text-orange-300" />;
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400";

export default function SentimentMarketPanel({ onAnalyseTicker }: { onAnalyseTicker?: (ticker: string) => void }) {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [alerts, setAlerts] = useState<MarketAlerts | null>(null);
  const [divergence, setDivergence] = useState<MarketDivergence | null>(null);
  const [tickers, setTickers] = useState<MarketTickerList | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [ingestNews, setIngestNews] = useState(true);
  const [ingestPrices, setIngestPrices] = useState(true);
  const [adding, setAdding] = useState(false);
  const [followResult, setFollowResult] = useState<MarketFollowResult | null>(null);
  const [loadingPrices, setLoadingPrices] = useState(false);
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [loadingBrief, setLoadingBrief] = useState(false);
  const [savingBrief, setSavingBrief] = useState(false);
  const [coverage, setCoverage] = useState<MarketCoverage | null>(null);
  const [schedule, setSchedule] = useState<MarketSchedule | null>(null);
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [savingOffice, setSavingOffice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ ticker: string; days: number } | null>(null);
  const [cron, setCron] = useState("30 6 * * *");
  const [scheduleDays, setScheduleDays] = useState(3);
  const [enabled, setEnabled] = useState(true);
  /* ------------------------------------------------- pesquisas e filtros */
  const [query, setQuery] = useState("");
  const [labelFilter, setLabelFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"noticias" | "tom" | "delta" | "cobertura" | "ticker">("noticias");
  const [minNews, setMinNews] = useState(0);
  const [onlyFollowed, setOnlyFollowed] = useState(false);
  const [withPrices, setWithPrices] = useState(false);
  const [alertKind, setAlertKind] = useState<string | null>(null);
  const [divergenceReading, setDivergenceReading] = useState<string | null>(null);
  const [onlyDaysWithNews, setOnlyDaysWithNews] = useState(false);
  const [chartTicker, setChartTicker] = useState("");
  const [chartSeries, setChartSeries] = useState<{ day: string; sentiment: number; news: number; label: string }[] | null>(null);
  const [chartLoading, setChartLoading] = useState(false);

  const load = useCallback(
    async (windowDays: number, silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [panorama, state, alertPayload, divergencePayload, tickerList] = await Promise.all([
          getSentimentMarketOverview(windowDays),
          getSentimentMarketState(),
          getSentimentMarketAlerts(windowDays),
          getSentimentMarketDivergence(windowDays),
          listSentimentMarketTickers(windowDays),
        ]);
        if (panorama.error) throw new Error(panorama.error);
        setOverview(panorama);
        setAlerts(alertPayload.error ? null : alertPayload);
        setDivergence(divergencePayload.error ? null : divergencePayload);
        setTickers(tickerList);
        setCoverage(state.coverage);
        setSchedule(state.schedule ?? panorama.schedule ?? null);
        setError(null);
      } catch (err) {
        setOverview(null);
        setAlerts(null);
        setDivergence(null);
        setTickers(null);
        setError(err instanceof Error ? err.message : "Falha ao carregar o sentimento de mercado.");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(days);
  }, [days, load]);

  useEffect(() => {
    if (!schedule) return;
    setCron(schedule.cron || "30 6 * * *");
    setScheduleDays(schedule.days || 3);
    setEnabled(schedule.enabled !== false);
  }, [schedule]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // Gráfico da série: mercado inteiro ou um ticker escolhido (busca à parte).
  useEffect(() => {
    if (!chartTicker) {
      setChartSeries(null);
      return;
    }
    let active = true;
    setChartLoading(true);
    getSentimentMarketSeries(Math.max(days, 30), chartTicker)
      .then((payload) => {
        if (active) setChartSeries(payload.items ?? []);
      })
      .catch(() => {
        if (active) setChartSeries([]);
      })
      .finally(() => {
        if (active) setChartLoading(false);
      });
    return () => {
      active = false;
    };
  }, [chartTicker, days]);

  const runBuild = async (onlyMissing: boolean) => {
    setBuilding(true);
    setError(null);
    try {
      const result = await buildSentimentMarket({ days, only_missing: onlyMissing });
      const parts = [
        `${number(result.documents)} dia(s) de série gravados`,
        `${number(result.news)} notícia(s) analisadas`,
        `${number(result.tickers_with_news ?? result.tickers)} ticker(s) com notícias`,
      ];
      if (result.skipped) parts.push(`${number(result.skipped)} já existiam`);
      if (result.pruned) parts.push(`${number(result.pruned)} dia(s) obsoleto(s) removidos`);
      setNotice(parts.join(" · "));
      if (result.errors?.length) setError(`Algumas fontes falharam: ${result.errors.slice(0, 3).join("; ")}`);
      await load(days, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na construção da série.");
    } finally {
      setBuilding(false);
    }
  };

  const saveSchedule = async () => {
    setSavingSchedule(true);
    setError(null);
    try {
      const payload = await saveSentimentMarketSchedule({
        cron,
        timezone: schedule?.timezone || "Europe/Lisbon",
        enabled,
        days: scheduleDays,
      });
      setSchedule(payload.schedule);
      setNotice(
        enabled
          ? `Agenda guardada: ${payload.schedule.cron} (${payload.schedule.timezone}).`
          : "Agenda desligada — a série só é construída à mão.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao guardar a agenda.");
    } finally {
      setSavingSchedule(false);
    }
  };

  const reloadSchedule = async () => {
    setSavingSchedule(true);
    try {
      setSchedule(await reloadSentimentMarketSchedule());
      setNotice("Agendador recarregado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao recarregar o agendador.");
    } finally {
      setSavingSchedule(false);
    }
  };

  const saveOffice = async () => {
    setSavingOffice(true);
    setError(null);
    try {
      const payload = await saveSentimentMarketToOffice({ days, title: `Sentimento de mercado — ${days} dias` });
      setNotice(`Relatório guardado no Office: «${payload.document.title}».`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao guardar o relatório no Office.");
    } finally {
      setSavingOffice(false);
    }
  };

  const openBrief = async () => {
    setLoadingBrief(true);
    setError(null);
    try {
      setBrief(await getSentimentMarketBrief(Math.min(days, 30)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao preparar o boletim.");
    } finally {
      setLoadingBrief(false);
    }
  };

  const saveBrief = async () => {
    setSavingBrief(true);
    setError(null);
    try {
      const payload = await saveSentimentMarketBriefToOffice({ days: Math.min(days, 30) });
      setNotice(`Boletim guardado no Office: «${payload.document.title}».`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao guardar o boletim no Office.");
    } finally {
      setSavingBrief(false);
    }
  };

  const copyBrief = async () => {
    if (!brief?.markdown) return;
    try {
      await navigator.clipboard.writeText(brief.markdown);
      setNotice("Boletim copiado para a área de transferência.");
    } catch {
      setError("O navegador não autorizou a cópia para a área de transferência.");
    }
  };

  /** Seguir um ticker: traz notícias e cotações e constrói a série já. */
  const addTicker = async () => {
    const code = newTicker.trim().toUpperCase();
    if (!code) return;
    setAdding(true);
    setError(null);
    setFollowResult(null);
    try {
      const result = await followSentimentMarketTicker({
        ticker: code,
        ingest_news: ingestNews,
        ingest_prices: ingestPrices,
        days,
      });
      setFollowResult(result);
      const bits = [
        result.news ? `${number(result.news.indexed)} notícia(s) indexadas` : null,
        `${number(result.series?.days ?? 0)} dia(s) de série`,
        result.prices?.points ? `${number(result.prices.points)} cotações (${result.prices.source})` : null,
      ].filter(Boolean);
      setNotice(`${result.ticker}: ${bits.join(" · ")}.`);
      if (!result.ok) setError(result.errors.join(" · "));
      setNewTicker("");
      await load(days, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao seguir o ticker.");
    } finally {
      setAdding(false);
    }
  };

  const removeTicker = async (code: string) => {
    setError(null);
    try {
      const result = await unfollowSentimentMarketTicker(code);
      setTickers((current) =>
        current ? { ...current, watchlist: result.watchlist, items: current.items.map((item) => ({ ...item, followed: item.ticker !== code && item.followed })) } : current,
      );
      setNotice(`${code} deixou de ser seguido (a série já construída mantém-se).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao deixar de seguir.");
    }
  };

  /** Cotações em falta na plataforma: ir buscá-las ao Yahoo (a pedido, é lento). */
  const fetchPrices = async () => {
    setLoadingPrices(true);
    setError(null);
    try {
      const payload = await getSentimentMarketDivergence(days, 12, true);
      setDivergence(payload);
      const saved = payload.stored ? ` e guardadas ${number(payload.stored)} na plataforma` : "";
      setNotice(
        payload.with_prices
          ? `Cotações obtidas para ${payload.with_prices} ticker(s)${saved}.`
          : "O Yahoo Finance não devolveu cotações para estes tickers.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao obter as cotações.");
    } finally {
      setLoadingPrices(false);
    }
  };

  const kpis = overview?.kpis;
  const hasSeries = Boolean(kpis && kpis.tickers);
  const missing = coverage?.missing ?? [];
  const basis = overview?.ranking.basis === "delta" ? "variação vs janela anterior" : "nível de tom";

  /* --------------------------------------------- filtros aplicados às vistas */
  const followedSet = useMemo(() => new Set(tickers?.watchlist ?? []), [tickers]);
  const pricePoints = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of tickers?.items ?? []) map.set(item.ticker, item.price_points);
    return map;
  }, [tickers]);

  const filtersActive = Boolean(
    query.trim() || labelFilter !== "all" || onlyFollowed || withPrices || minNews > 0 || sortBy !== "noticias" || alertKind || divergenceReading,
  );

  const visibleTickers = useMemo(() => {
    const text = query.trim().toLowerCase();
    const rows = (overview?.tickers ?? []).filter((item) => {
      if (text && !`${item.ticker} ${item.label}`.toLowerCase().includes(text)) return false;
      if (labelFilter !== "all" && item.label !== labelFilter) return false;
      if (onlyFollowed && !followedSet.has(item.ticker)) return false;
      if (withPrices && !(pricePoints.get(item.ticker) ?? 0)) return false;
      if (minNews > 0 && item.news < minNews) return false;
      return true;
    });
    const sorters: Record<string, (a: MarketTickerStats, b: MarketTickerStats) => number> = {
      noticias: (a, b) => b.news - a.news,
      tom: (a, b) => b.sentiment - a.sentiment,
      delta: (a, b) => (b.delta ?? -9) - (a.delta ?? -9),
      cobertura: (a, b) => b.coverage - a.coverage,
      ticker: (a, b) => a.ticker.localeCompare(b.ticker),
    };
    return [...rows].sort(sorters[sortBy] ?? sorters.noticias);
  }, [overview, query, labelFilter, onlyFollowed, withPrices, minNews, sortBy, followedSet, pricePoints]);

  const visibleCodes = useMemo(() => new Set(visibleTickers.map((item) => item.ticker)), [visibleTickers]);

  const visibleHeatRows = useMemo(
    () => (overview?.heatmap.rows ?? []).filter((row) => visibleCodes.has(row.ticker)),
    [overview, visibleCodes],
  );

  const heatDays = useMemo(() => {
    const days = overview?.heatmap.days ?? [];
    if (!onlyDaysWithNews) return days;
    const withNews = new Set<string>();
    for (const row of visibleHeatRows) {
      for (const cell of row.cells) {
        if (cell.news > 0) withNews.add(cell.day);
      }
    }
    return days.filter((day) => withNews.has(day));
  }, [overview, visibleHeatRows, onlyDaysWithNews]);

  const visibleAlerts = useMemo(
    () =>
      (alerts?.items ?? []).filter(
        (item) => visibleCodes.has(item.ticker) && (!alertKind || item.kind === alertKind),
      ),
    [alerts, visibleCodes, alertKind],
  );

  const visibleDivergence = useMemo(
    () =>
      (divergence?.items ?? []).filter(
        (item) => visibleCodes.has(item.ticker) && (!divergenceReading || item.reading === divergenceReading),
      ),
    [divergence, visibleCodes, divergenceReading],
  );

  const loadingChart = chartLoading && Boolean(chartTicker);
  const chartPoints = chartTicker ? chartSeries ?? [] : overview?.series ?? [];

  const clearFilters = () => {
    setQuery("");
    setLabelFilter("all");
    setSortBy("noticias");
    setMinNews(0);
    setOnlyFollowed(false);
    setWithPrices(false);
    setAlertKind(null);
    setDivergenceReading(null);
  };

  const stateLine = useMemo(() => {
    if (!overview?.state) return "sem série guardada";
    const state = overview.state;
    if (!state.documents) return "sem série guardada";
    const bits = [`${number(state.documents)} documento(s)`, `${number(state.tickers)} ticker(s)`];
    if (state.first_date && state.last_date) bits.push(`${state.first_date} → ${state.last_date}`);
    if (state.covered_news) bits.push(`${number(state.covered_news)} notícia(s) cobertas`);
    return bits.join(" · ");
  }, [overview]);

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------- controlos */}
      <section className="glass-card rounded-2xl p-4">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Activity size={15} /> Sentimento de mercado
          </h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Série diária por ticker construída a partir das notícias indexadas. {stateLine}.
          </p>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Segmented options={WINDOWS} value={days} onChange={setDays} label="Janela" />
          <span className="mx-1 hidden h-5 w-px bg-white/10 sm:block" />
          <Btn variant="primary" onClick={() => void runBuild(false)} disabled={building || !user} title={user ? "Recolher e agregar as notícias da janela" : "Exige sessão"}>
            {building ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {building ? "A recolher…" : "Recolher agora"}
          </Btn>
          <Btn onClick={() => void runBuild(true)} disabled={building || !user} title="Só constrói os dias que ainda não têm série">
            <CalendarClock size={13} /> Completar falhas
          </Btn>
          <Btn onClick={() => void load(days)} disabled={loading} title="Voltar a ler o panorama">
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Atualizar
          </Btn>
          <span className="ml-auto flex flex-wrap items-center gap-2">
            <a
              href={sentimentMarketExportUrl(days, "csv")}
              className={`inline-flex ${tap} ${focusRing} items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 text-[11px] hover:bg-white/10`}
            >
              <Download size={13} /> CSV
            </a>
            <a
              href={sentimentMarketExportUrl(days, "md")}
              className={`inline-flex ${tap} ${focusRing} items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 text-[11px] hover:bg-white/10`}
            >
              <Download size={13} /> Markdown
            </a>
            <Btn onClick={() => void saveOffice()} disabled={savingOffice || !user || !hasSeries} title="Guardar o relatório no editor Office">
              {savingOffice ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />} Relatório
            </Btn>
            <Btn onClick={() => void openBrief()} disabled={loadingBrief || !hasSeries} title="Boletim: resumo, movimentos, alertas e temas">
              {loadingBrief ? <Loader2 size={13} className="animate-spin" /> : <ScrollText size={13} />} Boletim
            </Btn>
            <Btn onClick={() => { setAddOpen(true); setFollowResult(null); }} title="Seguir outro ticker: traz notícias e cotações e analisa já">
              <Plus size={13} /> Ticker
            </Btn>
          </span>
        </div>

        {/* tickers seguidos */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Seguidos {tickers ? `(${tickers.watchlist.length})` : ""}
          </span>
          {tickers?.watchlist.length ? (
            tickers.watchlist.map((code) => {
              const entry = tickers.items.find((item) => item.ticker === code);
              return (
                <span
                  key={code}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 pr-1 pl-2 text-[10px]"
                  title={`${entry?.documents ?? 0} dia(s) de série · ${entry?.news ?? 0} notícia(s) · ${entry?.price_points ?? 0} cotações guardadas`}
                >
                  <span className="font-mono">{code}</span>
                  {entry?.documents ? <span className={tone(0.5)}>•</span> : null}
                  <button
                    type="button"
                    onClick={() => void removeTicker(code)}
                    aria-label={`Deixar de seguir ${code}`}
                    className={`${focusRing} grid h-6 w-6 place-items-center rounded-full hover:bg-white/10`}
                  >
                    <X size={11} />
                  </button>
                </span>
              );
            })
          ) : (
            <span className="text-[10px] text-muted-foreground">
              nenhum — os tickers aparecem aqui quando os acrescenta (ou quando têm notícias/cotações)
            </span>
          )}
        </div>

        {!user ? (
          <p className="mt-3 text-[10px] text-amber-200">
            A construção da série e o relatório no Office exigem sessão iniciada. A leitura do panorama é livre.
          </p>
        ) : null}

        {/* agenda da construção */}
        <details className="mt-3 rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
          <summary className="flex cursor-pointer items-center gap-2 text-[11px] text-muted-foreground">
            <CalendarClock size={12} /> Agenda da série
            <span className="ml-auto">
              {schedule
                ? schedule.enabled
                  ? `cron ${schedule.cron} · ${schedule.scheduled ? "agendado" : "sem agendador"} · próxima ${clock(schedule.next_run_at)}`
                  : "desligada"
                : "—"}
            </span>
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-[150px_130px_1fr]">
            <label className="block">
              <span className="text-[10px] text-muted-foreground">Cron (minuto hora dia mês semana)</span>
              <input value={cron} onChange={(event) => setCron(event.target.value)} className={`${inputClass} mt-1 font-mono`} placeholder="30 6 * * *" />
            </label>
            <label className="block">
              <span className="text-[10px] text-muted-foreground">Dias por corrida</span>
              <input
                type="number"
                min={1}
                max={90}
                value={scheduleDays}
                onChange={(event) => setScheduleDays(Number(event.target.value))}
                className={`${inputClass} mt-1`}
              />
            </label>
            <div className="flex flex-wrap items-end gap-2">
              <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
                <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="h-4 w-4 accent-violet-500" />
                Construir todos os dias
              </label>
              <Btn variant="primary" onClick={() => void saveSchedule()} disabled={savingSchedule}>
                {savingSchedule ? <Loader2 size={13} className="animate-spin" /> : null} Guardar
              </Btn>
              <Btn onClick={() => void reloadSchedule()} disabled={savingSchedule}>
                <RefreshCw size={13} /> Recarregar
              </Btn>
            </div>
          </div>
          {schedule ? (
            <p className="mt-2 text-[10px] text-muted-foreground">
              Última corrida: {clock(schedule.last_run_at)}
              {schedule.last_result?.documents !== undefined ? ` · ${number(Number(schedule.last_result.documents))} documento(s)` : ""}
              {schedule.last_result?.news !== undefined ? ` · ${number(Number(schedule.last_result.news))} notícia(s)` : ""}
              {schedule.error ? ` · ${schedule.error}` : ""}
            </p>
          ) : null}
        </details>
      </section>

      {/* ----------------------------------------------- pesquisa e filtros */}
      <section className="glass-card rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-[170px] flex-1">
            <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className={`${inputClass} pl-8`}
              placeholder="Procurar ticker ou tom (ex.: EDP, positivo)"
              aria-label="Procurar ticker"
            />
          </label>
          <select
            value={labelFilter}
            onChange={(event) => setLabelFilter(event.target.value)}
            className={inputClass}
            title="Filtrar pela leitura do tom"
            aria-label="Filtrar pela leitura"
          >
            <option value="all">Todas as leituras</option>
            <option value="positivo">Positivo</option>
            <option value="neutro">Neutro</option>
            <option value="negativo">Negativo</option>
          </select>
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as typeof sortBy)}
            className={inputClass}
            title="Ordenar a tabela"
            aria-label="Ordenar"
          >
            <option value="noticias">Ordenar: notícias</option>
            <option value="tom">Ordenar: tom</option>
            <option value="delta">Ordenar: Δ</option>
            <option value="cobertura">Ordenar: cobertura</option>
            <option value="ticker">Ordenar: ticker</option>
          </select>
          <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
            <input
              type="number"
              min={0}
              max={400}
              value={minNews}
              onChange={(event) => setMinNews(Math.max(0, Number(event.target.value) || 0))}
              className={`${inputClass} w-20`}
              aria-label="Notícias mínimas"
            />
            notícias ≥
          </label>
          <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
            <input type="checkbox" checked={onlyFollowed} onChange={(event) => setOnlyFollowed(event.target.checked)} className="h-4 w-4 accent-violet-500" />
            Só seguidos
          </label>
          <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
            <input type="checkbox" checked={withPrices} onChange={(event) => setWithPrices(event.target.checked)} className="h-4 w-4 accent-violet-500" />
            Com cotações
          </label>
          {filtersActive ? (
            <Btn onClick={clearFilters} title="Voltar a mostrar tudo">
              <X size={13} /> Limpar
            </Btn>
          ) : null}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          A mostrar {number(visibleTickers.length)} de {number(overview?.tickers.length ?? 0)} ticker(s) · {number(visibleAlerts.length)} alerta(s) ·{" "}
          {number(visibleDivergence.length)} linha(s) de tom × preço
          {query.trim() && !visibleTickers.length
            ? ` — «${query.trim()}» não corresponde a nenhum ticker desta janela (pode segui-lo abaixo).`
            : ""}
        </p>
        {query.trim() && !visibleTickers.length && !followedSet.has(query.trim().toUpperCase()) ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[10px] text-muted-foreground">Ainda não segue este símbolo?</span>
            <Btn
              onClick={() => {
                setNewTicker(query.trim().toUpperCase());
                setFollowResult(null);
                setAddOpen(true);
              }}
              title="Trazer notícias e cotações e construir a série já"
            >
              <Plus size={13} /> Seguir «{query.trim().toUpperCase()}»
            </Btn>
          </div>
        ) : null}
      </section>

      {error ? (
        <div className="flex items-start gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} className="mt-0.5" />
          <span className="flex-1">{error}</span>
        </div>
      ) : null}
      {notice ? (
        <div className="flex items-center gap-2 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-100">
          <CheckCircle2 size={14} /> {notice}
        </div>
      ) : null}

      {missing.length ? (
        <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-amber-400/25 bg-amber-400/10 px-4 py-3 text-[11px] text-amber-100">
          <AlertTriangle size={13} />
          <span>
            {coverage?.missing_total} ticker(s) têm notícias mas ainda não têm série — use «Recolher agora» ou «Completar falhas».
          </span>
          <span className="flex flex-wrap gap-1">
            {missing.slice(0, 8).map((ticker) => (
              <Chip key={ticker} className="border-amber-400/30 bg-amber-400/10 text-amber-100">
                {ticker}
              </Chip>
            ))}
            {coverage && coverage.missing_total > 8 ? <Chip>+{coverage.missing_total - 8}</Chip> : null}
          </span>
        </div>
      ) : null}

      {!hasSeries ? (
        <section className="glass-card rounded-2xl p-6 text-center">
          <Flame size={22} className="mx-auto text-muted-foreground" />
          <h3 className="mt-2 text-sm font-semibold">Ainda não há série de sentimento de mercado</h3>
          <p className="mx-auto mt-1 max-w-xl text-[11px] text-muted-foreground">
            A série é construída a partir das notícias indexadas de cada ticker (título + resumo), com o léxico português. Escolha uma janela e
            recolha: os dias ficam guardados como `ticker|dia` e a partir daí passam a ser atualizados sozinhos todos os dias.
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <Btn variant="primary" onClick={() => void runBuild(false)} disabled={building || !user}>
              {building ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Construir série ({days} dias)
            </Btn>
            <Btn onClick={() => void load(days)} disabled={loading}>
              <RefreshCw size={13} /> Verificar outra vez
            </Btn>
          </div>
        </section>
      ) : (
        <>
          {/* --------------------------------------------------------- KPIs */}
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Tom do mercado" value={signed(kpis?.sentiment)} hint={kpis?.label} tone={tone(kpis?.sentiment ?? 0)} />
            <Kpi
              label="Tendência"
              value={signed(kpis?.trend)}
              hint={kpis?.tickers_with_delta ? `${kpis.tickers_with_delta} ticker(s) com janela anterior` : "sem janela anterior"}
              tone={tone(kpis?.trend ?? 0)}
            />
            <Kpi label="Notícias" value={number(kpis?.news)} hint={`janela de ${overview?.window.days} dias`} />
            <Kpi label="Tickers" value={number(kpis?.tickers)} hint={overview ? `${overview.window.start} → ${overview.window.end}` : undefined} />
            <Kpi label="Cobertura" value={percent(kpis?.coverage)} hint="com vocabulário de sentimento" />
            <Kpi label="Positivas" value={percent(kpis?.positive_ratio)} hint={`negativas ${percent(kpis?.negative_ratio)}`} />
          </section>

          {/* ----------------------------------------------------- alertas */}
          <section className="glass-card rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Bell size={12} /> Alertas do mercado
                {alerts ? <Chip>{number(alerts.total)}</Chip> : null}
              </h3>
              <span className="text-[10px] text-muted-foreground">
                {alerts
                  ? `Δ ≥ ${alerts.thresholds.min_delta} · mínimo ${alerts.thresholds.min_news} notícia(s) · leitura extrema ≥ ${alerts.thresholds.extreme}`
                  : "—"}
              </span>
            </div>

            {!alerts ? (
              <p className="mt-3 text-[11px] text-muted-foreground">Não foi possível ler os alertas nesta janela.</p>
            ) : alerts.items.length === 0 ? (
              <p className="mt-3 text-[11px] text-muted-foreground">
                Sem movimentos acima dos limiares nesta janela — nenhuma leitura merece destaque (o que também é informação).
              </p>
            ) : (
              <>
                {alerts.counts.length ? (
                  <div className="mt-3 flex flex-wrap items-center gap-1">
                    {alerts.counts.map((entry) => (
                      <button
                        key={entry.kind}
                        type="button"
                        onClick={() => setAlertKind(alertKind === entry.kind ? null : entry.kind)}
                        aria-pressed={alertKind === entry.kind}
                        title={`Filtrar por «${entry.label}»`}
                        className={`${focusRing} rounded-full border px-2 py-0.5 text-[10px] transition ${
                          alertKind === entry.kind
                            ? "border-violet-400/40 bg-violet-500/20 text-violet-100"
                            : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
                        }`}
                      >
                        {entry.label} · {entry.count}
                      </button>
                    ))}
                    {alertKind ? (
                      <button
                        type="button"
                        onClick={() => setAlertKind(null)}
                        className={`${focusRing} rounded-full border border-violet-400/40 bg-violet-500/20 px-2 py-0.5 text-[10px] text-violet-100`}
                      >
                        todos
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {visibleAlerts.length === 0 ? (
                  <p className="mt-3 text-[11px] text-muted-foreground">Nenhum alerta deste tipo com os filtros e a pesquisa atuais.</p>
                ) : (
                <ul className="mt-3 space-y-2">
                  {visibleAlerts.map((item: MarketAlert, index) => (
                    <li key={`${item.ticker}-${item.kind}-${index}`}>
                      <button
                        type="button"
                        onClick={() => setDetail({ ticker: item.ticker, days })}
                        title={`Ver o detalhe de ${item.ticker}`}
                        className={`${focusRing} w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-left transition hover:bg-white/10`}
                      >
                        <span className="flex flex-wrap items-center gap-2">
                          <Chip className={severityChip(item.severity)}>{SEVERITY_LABELS[item.severity] ?? item.severity}</Chip>
                          <span className="flex items-center gap-1 text-[11px]">
                            {kindIcon(item.kind)} {item.kind_label}
                          </span>
                          <span className="font-mono text-[11px]">{item.ticker}</span>
                          <span className="text-[10px] text-muted-foreground">{number(item.news)} notícia(s)</span>
                          <span className="ml-auto font-mono text-[11px]">
                            {item.kind === "extremo"
                              ? `dia ${signed(item.value ?? 0, 2)}${item.day ? ` em ${shortDay(item.day)}` : ""}`
                              : `Δ ${item.delta === null ? "—" : signed(item.delta, 2)}`}
                          </span>
                          <ChevronRight size={13} className="text-muted-foreground" />
                        </span>
                        <span className="mt-1 block text-[11px] text-muted-foreground">{item.detail}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                )}
              </>
            )}
            <p className="mt-2 text-[10px] text-muted-foreground">
              São leituras de tom das notícias, não sinais de investimento: cada alerta mostra o critério, o número de notícias que o sustenta e a
              cobertura do vocabulário.
            </p>
          </section>

          {/* -------------------------------------------------------- série */}
          <section className="glass-card rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Série diária</h3>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={chartTicker}
                  onChange={(event) => setChartTicker(event.target.value)}
                  className={inputClass}
                  title="Ver a série do mercado ou de um ticker"
                  aria-label="Série a desenhar"
                >
                  <option value="">Mercado (todos os tickers)</option>
                  {visibleTickers.map((item) => (
                    <option key={item.ticker} value={item.ticker}>
                      {item.ticker}
                    </option>
                  ))}
                </select>
                <span className="text-[10px] text-muted-foreground">
                  média ponderada pelas notícias · última data {kpis?.last_date ?? "—"}
                </span>
              </div>
            </div>
            <div className="mt-3">
              {loadingChart ? (
                <p className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <Loader2 size={13} className="animate-spin" /> A ler a série de {chartTicker}…
                </p>
              ) : chartPoints.length ? (
                <MiniBars points={chartPoints} />
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  {chartTicker ? `Sem série guardada para ${chartTicker} nesta janela.` : "Sem série nesta janela."}
                </p>
              )}
            </div>
          </section>

          {/* ------------------------------------------------------ heatmap */}
          <section className="glass-card rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Heatmap ticker × dia</h3>
              <span className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
                <label className="inline-flex min-h-[44px] items-center gap-2 sm:min-h-[24px]">
                  <input
                    type="checkbox"
                    checked={onlyDaysWithNews}
                    onChange={(event) => setOnlyDaysWithNews(event.target.checked)}
                    className="h-3.5 w-3.5 accent-violet-500"
                  />
                  só dias com notícias
                </label>
                <span>célula = tom do dia · «—» = sem notícias</span>
              </span>
            </div>
            {visibleHeatRows.length === 0 || heatDays.length === 0 ? (
              <p className="mt-3 text-[11px] text-muted-foreground">
                {overview?.heatmap.rows.length && !visibleHeatRows.length
                  ? "Nenhum ticker corresponde aos filtros — limpe os filtros para voltar a ver o heatmap."
                  : "Sem dias com série nesta janela."}
              </p>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[520px] border-separate border-spacing-1 text-[10px]">
                  <thead>
                    <tr>
                      <th className="text-left font-medium text-muted-foreground">Ticker</th>
                      {heatDays.map((day) => (
                        <th key={day} className="text-center font-medium text-muted-foreground">
                          {shortDay(day)}
                        </th>
                      ))}
                      <th className="text-right font-medium text-muted-foreground">Tom</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleHeatRows.map((row) => (
                      <tr key={row.ticker}>
                        <td>
                          <button
                            type="button"
                            onClick={() => setDetail({ ticker: row.ticker, days })}
                            className={`${focusRing} rounded px-1 py-0.5 font-mono text-[10px] hover:bg-white/10`}
                          >
                            {row.ticker}
                          </button>
                        </td>
                        {row.cells
                          .filter((cell) => heatDays.includes(cell.day))
                          .map((cell) => (
                            <td key={`${row.ticker}-${cell.day}`} className="text-center">
                              <span
                                className={`inline-flex h-6 w-full min-w-[38px] items-center justify-center rounded ${heatClass(cell.value)}`}
                                title={`${row.ticker} · ${cell.day} · tom ${signed(cell.value)} · ${cell.news} notícia(s) · cobertura ${percent(cell.coverage)}`}
                              >
                                {cell.value === null ? "—" : cell.value.toFixed(2)}
                              </span>
                            </td>
                          ))}
                        <td className={`text-right font-mono ${tone(row.sentiment)}`}>{signed(row.sentiment, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-2 text-[10px] text-muted-foreground">
              {number(visibleHeatRows.length)} ticker(s) e {number(heatDays.length)} dia(s) à vista (máximo de {number(overview?.heatmap.rows.length ?? 0)} tickers mais
              ativos). Toque num ticker para ver o detalhe.
            </p>
          </section>

          {/* ---------------------------------------------------- rankings */}
          <section className="grid gap-3 lg:grid-cols-2">
            {[
              { title: "Maiores subidas", items: (overview?.ranking.up ?? []).filter((item) => visibleCodes.has(item.ticker)), icon: <TrendingUp size={13} />, good: true },
              { title: "Maiores descidas", items: (overview?.ranking.down ?? []).filter((item) => visibleCodes.has(item.ticker)), icon: <TrendingDown size={13} />, good: false },
            ].map((block) => (
              <div key={block.title} className="glass-card rounded-2xl p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {block.icon} {block.title}
                  </h3>
                  <span className="text-[10px] text-muted-foreground">base: {basis}</span>
                </div>
                {block.items.length === 0 ? (
                  <p className="mt-3 text-[11px] text-muted-foreground">Sem tickers nesta condição.</p>
                ) : (
                  <ul className="mt-3 space-y-1">
                    {block.items.map((item) => (
                      <li key={item.ticker}>
                        <button
                          type="button"
                          onClick={() => setDetail({ ticker: item.ticker, days })}
                          className={`${focusRing} flex w-full items-center gap-2 rounded-xl px-2 py-2 ${tap} text-left hover:bg-white/5`}
                        >
                          <span className="w-20 shrink-0 font-mono text-[11px]">{item.ticker}</span>
                          <PolarityBar value={item.sentiment} width={80} />
                          <span className={`w-14 shrink-0 text-right font-mono text-[11px] ${tone(item.sentiment)}`}>
                            {signed(item.sentiment, 2)}
                          </span>
                          <span className={`ml-auto shrink-0 font-mono text-[11px] ${tone(item.delta ?? item.sentiment)}`}>
                            Δ {item.delta === null ? "—" : signed(item.delta, 2)}
                          </span>
                          <ChevronRight size={13} className="text-muted-foreground" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </section>

          {/* ----------------------------------------------- tom × preço */}
          <section className="glass-card rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Coins size={12} /> Tom × preço
                {divergence ? <Chip>{number(divergence.with_prices)} de {number(divergence.tickers_with_series)} com cotações</Chip> : null}
              </h3>
              <span className="text-[10px] text-muted-foreground">
                variação normalizada: ±{divergence?.reference_move ?? 5} % ≈ ±1 em tom
              </span>
            </div>

            {divergence && divergence.items.length ? (
              <div className="mt-3 flex flex-wrap items-center gap-1">
                {Array.from(new Set(divergence.items.map((item) => item.reading))).map((reading) => {
                  const total = divergence.items.filter((item) => item.reading === reading).length;
                  return (
                    <button
                      key={reading}
                      type="button"
                      onClick={() => setDivergenceReading(divergenceReading === reading ? null : reading)}
                      aria-pressed={divergenceReading === reading}
                      title={`Filtrar por «${READING_LABELS[reading] ?? reading}»`}
                      className={`${focusRing} rounded-full border px-2 py-0.5 text-[10px] transition ${
                        divergenceReading === reading ? readingChip(reading) : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
                      }`}
                    >
                      {READING_LABELS[reading] ?? reading} · {total}
                    </button>
                  );
                })}
                {divergenceReading ? (
                  <button
                    type="button"
                    onClick={() => setDivergenceReading(null)}
                    className={`${focusRing} rounded-full border border-violet-400/40 bg-violet-500/20 px-2 py-0.5 text-[10px] text-violet-100`}
                  >
                    todas
                  </button>
                ) : null}
              </div>
            ) : null}

            {!divergence ? (
              <p className="mt-3 text-[11px] text-muted-foreground">Não foi possível ler as cotações nesta janela.</p>
            ) : visibleDivergence.length === 0 ? (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <p className="text-[11px] text-muted-foreground">
                  {divergence.items.length
                    ? "Nenhuma linha corresponde aos filtros — limpe os filtros para voltar a ver o tom × preço."
                    : divergence.message ??
                      "Sem cotações na plataforma para estes tickers nesta janela. As cotações podem ser obtidas no Yahoo Finance (mesma fonte da app de mercados)."}
                </p>
                {divergence.items.length ? null : (
                  <Btn onClick={() => void fetchPrices()} disabled={loadingPrices}>
                    {loadingPrices ? <Loader2 size={13} className="animate-spin" /> : <LineChart size={13} />} Obter cotações
                  </Btn>
                )}
              </div>
            ) : (
              <>
                <ul className="mt-3 space-y-2">
                  {visibleDivergence.map((item) => (
                    <li key={item.ticker}>
                      <button
                        type="button"
                        onClick={() => setDetail({ ticker: item.ticker, days })}
                        title={`Ver o detalhe de ${item.ticker}`}
                        className={`${focusRing} flex w-full flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-left transition hover:bg-white/10`}
                      >
                        <Chip className={readingChip(item.reading)}>{READING_LABELS[item.reading] ?? item.reading}</Chip>
                        <span className="font-mono text-[11px]">{item.ticker}</span>
                        <span className="text-[10px] text-muted-foreground">
                          tom <span className={tone(item.sentiment)}>{signed(item.sentiment, 2)}</span> · preço{" "}
                          <span className={tone(item.change_pct)}>{item.change_pct >= 0 ? "+" : ""}{item.change_pct.toFixed(2)} %</span>
                        </span>
                        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                          desvio {item.gap >= 0 ? "+" : ""}{item.gap.toFixed(2)}
                        </span>
                        <ChevronRight size={13} className="text-muted-foreground" />
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Btn onClick={() => void fetchPrices()} disabled={loadingPrices} title="Atualizar as cotações em falta no Yahoo Finance">
                    {loadingPrices ? <Loader2 size={13} className="animate-spin" /> : <LineChart size={13} />} Atualizar cotações
                  </Btn>
                  <span className="text-[10px] text-muted-foreground">{divergence.caveat}</span>
                </div>
              </>
            )}
          </section>

          {/* ----------------------------------------------- tabela tickers */}
          <section className="glass-card rounded-2xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tickers na janela</h3>
              <span className="text-[10px] text-muted-foreground">
                {number(visibleTickers.length)} de {number(overview?.tickers.length ?? 0)} · {overview?.window.start} → {overview?.window.end}
              </span>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[620px] text-[11px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-2 font-medium">Ticker</th>
                    <th className="py-2 pr-2 font-medium">Tom</th>
                    <th className="py-2 pr-2 font-medium">Δ janela anterior</th>
                    <th className="py-2 pr-2 font-medium">Notícias</th>
                    <th className="py-2 pr-2 font-medium">Dias</th>
                    <th className="py-2 pr-2 font-medium">Cobertura</th>
                    <th className="py-2 pr-2 font-medium">Positivas</th>
                    <th className="py-2 font-medium">Última data</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleTickers.map((item: MarketTickerStats) => (
                    <tr
                      key={item.ticker}
                      onClick={() => setDetail({ ticker: item.ticker, days })}
                      className="cursor-pointer border-t border-white/5 hover:bg-white/5"
                    >
                      <td className="py-2 pr-2 font-mono">
                        <span className="inline-flex items-center gap-1">
                          {item.ticker}
                          <ChevronRight size={12} className="text-muted-foreground" />
                        </span>
                      </td>
                      <td className="py-2 pr-2">
                        <span className="inline-flex items-center gap-2">
                          <span className={`font-mono ${tone(item.sentiment)}`}>{signed(item.sentiment, 2)}</span>
                          <Chip className={labelChip(item.label)}>{item.label}</Chip>
                        </span>
                      </td>
                      <td className={`py-2 pr-2 font-mono ${tone(item.delta ?? item.sentiment)}`}>
                        {item.delta === null ? "—" : signed(item.delta, 2)}
                      </td>
                      <td className="py-2 pr-2">{number(item.news)}</td>
                      <td className="py-2 pr-2">{number(item.days)}</td>
                      <td className="py-2 pr-2">{percent(item.coverage)}</td>
                      <td className="py-2 pr-2">{percent(item.positive_ratio)}</td>
                      <td className="py-2 text-muted-foreground">{item.last_date ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* ------------------------------------------------ temas e fontes */}
          <section className="grid gap-3 lg:grid-cols-2">
            <div className="glass-card rounded-2xl p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Temas mais frequentes</h3>
              <div className="mt-3 flex flex-wrap gap-1">
                {(overview?.topics ?? []).map((topic) => (
                  <Chip key={topic.term}>
                    {topic.term} · {number(topic.news)}
                  </Chip>
                ))}
                {(overview?.topics ?? []).length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">Sem temas registados nas notícias desta janela.</p>
                ) : null}
              </div>
            </div>
            <div className="glass-card rounded-2xl p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes</h3>
              <div className="mt-3 flex flex-wrap gap-1">
                {(overview?.sources ?? []).map((source) => (
                  <Chip key={source.source}>
                    {source.source} · {number(source.news)}
                  </Chip>
                ))}
                {(overview?.sources ?? []).length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">Sem fontes nesta janela.</p>
                ) : null}
              </div>
            </div>
          </section>
        </>
      )}

      {addOpen ? (
        <AddTickerSheet
          ticker={newTicker}
          onTicker={setNewTicker}
          ingestNews={ingestNews}
          ingestPrices={ingestPrices}
          onIngestNews={setIngestNews}
          onIngestPrices={setIngestPrices}
          days={days}
          busy={adding}
          result={followResult}
          onSubmit={() => void addTicker()}
          onClose={() => setAddOpen(false)}
        />
      ) : null}

      {brief ? <BriefSheet brief={brief} saving={savingBrief} onCopy={() => void copyBrief()} onSave={() => void saveBrief()} onClose={() => setBrief(null)} /> : null}

      {detail ? (
        <TickerSheet
          ticker={detail.ticker}
          days={detail.days}
          onClose={() => setDetail(null)}
          onAnalyse={onAnalyseTicker}
        />
      ) : null}
    </div>
  );
}

/** Folha com o detalhe de um ticker (melhor/pior dia e destaques). */
function TickerSheet({
  ticker,
  days,
  onClose,
  onAnalyse,
}: {
  ticker: string;
  days: number;
  onClose: () => void;
  onAnalyse?: (ticker: string) => void;
}) {
  const [detail, setDetail] = useState<MarketTickerDetail | null>(null);
  const [correlation, setCorrelation] = useState<MarketCorrelation | null>(null);
  const [loadingPrice, setLoadingPrice] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getSentimentMarketTicker(ticker, Math.max(days, 30))
      .then((payload) => {
        if (!active) return;
        if (payload.error) throw new Error(payload.error);
        setDetail(payload);
        setError(null);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Falha ao carregar o ticker.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [ticker, days]);

  // Tom × preço: primeiro as cotações da plataforma e, se não houver, as do Yahoo.
  useEffect(() => {
    let active = true;
    const windowDays = Math.max(days, 30);
    setLoadingPrice(true);
    setPriceError(null);
    getSentimentMarketPrice(ticker, windowDays, false)
      .then((payload) => {
        if (!active) return null;
        if (payload.error) throw new Error(payload.error);
        if (payload.price_days) {
          setCorrelation(payload);
          return null;
        }
        return getSentimentMarketPrice(ticker, windowDays, true).then((live) => {
          if (active) setCorrelation(live);
        });
      })
      .catch((err) => {
        if (active) setPriceError(err instanceof Error ? err.message : "Falha ao ler as cotações.");
      })
      .finally(() => {
        if (active) setLoadingPrice(false);
      });
    return () => {
      active = false;
    };
  }, [ticker, days]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="glass-card max-h-[88vh] w-full overflow-y-auto rounded-t-3xl p-4 sm:max-w-3xl sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">{ticker}</h3>
            {detail?.stats ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                tom {signed(detail.stats.sentiment ?? 0, 3)} · {detail.stats.days ?? 0} dia(s) · {number(detail.stats.news ?? 0)} notícia(s) ·
                cobertura {percent(detail.stats.coverage ?? 0)}
              </p>
            ) : (
              <p className="mt-1 text-[11px] text-muted-foreground">Série diária, melhor/pior dia e destaques.</p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar" className={`${focusRing} ${tap} rounded-xl px-2 hover:bg-white/10`}>
            <X size={16} />
          </button>
        </div>

        {loading ? (
          <p className="mt-4 flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> A carregar…
          </p>
        ) : error ? (
          <p className="mt-4 text-[11px] text-rose-200">{error}</p>
        ) : !detail?.items.length ? (
          <p className="mt-4 text-[11px] text-muted-foreground">
            {detail?.message ?? "Sem série para este ticker nesta janela."}
          </p>
        ) : (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Kpi label="Tom" value={signed(detail.stats.sentiment ?? 0)} hint={detail.stats.label} tone={tone(detail.stats.sentiment ?? 0)} />
              <Kpi label="Melhor dia" value={detail.best ? signed(detail.best.value) : "—"} hint={detail.best?.day} />
              <Kpi label="Pior dia" value={detail.worst ? signed(detail.worst.value) : "—"} hint={detail.worst?.day} />
              <Kpi label="Notícias" value={number(detail.stats.news ?? 0)} hint={`cobertura ${percent(detail.stats.coverage ?? 0)}`} />
            </div>

            <div className="mt-4">
              <MiniBars points={detail.items} />
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[420px] text-[11px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-2 font-medium">Dia</th>
                    <th className="py-2 pr-2 font-medium">Tom</th>
                    <th className="py-2 pr-2 font-medium">Média simples</th>
                    <th className="py-2 pr-2 font-medium">Notícias</th>
                    <th className="py-2 pr-2 font-medium">Cobertura</th>
                    <th className="py-2 font-medium">Temas</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.items.map((item) => (
                    <tr key={item.day} className="border-t border-white/5">
                      <td className="py-1.5 pr-2 font-mono">{item.day}</td>
                      <td className={`py-1.5 pr-2 font-mono ${tone(item.sentiment)}`}>{signed(item.sentiment, 2)}</td>
                      <td className="py-1.5 pr-2 font-mono text-muted-foreground">{signed(item.mean, 2)}</td>
                      <td className="py-1.5 pr-2">
                        {item.news}
                        {item.unique < item.news ? (
                          <span className="ml-1 text-[10px] text-muted-foreground" title={`${item.duplicates} notícia(s) repetida(s) — a mesma história em vários sítios`}>
                            ({item.unique} histórias)
                          </span>
                        ) : null}
                      </td>
                      <td className="py-1.5 pr-2">{percent(item.coverage)}</td>
                      <td className="py-1.5 text-muted-foreground">{item.topics.slice(0, 3).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {detail.highlights.length ? (
              <div className="mt-4">
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Destaques do melhor e do pior dia
                </h4>
                <ul className="mt-2 space-y-2">
                  {detail.highlights.map((item, index) => (
                    <li key={`${item.day}-${index}`} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                      <div className="flex items-start gap-2">
                        <span className={`mt-0.5 font-mono text-[10px] ${tone(item.polarity)}`}>{signed(item.polarity, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[11px] leading-snug">
                            {item.url ? (
                              <a href={item.url} target="_blank" rel="noreferrer" className="hover:underline">
                                {item.title}
                              </a>
                            ) : (
                              item.title
                            )}
                          </p>
                          <p className="mt-0.5 text-[10px] text-muted-foreground">
                            {item.source} · {item.day} · {item.reason}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}

        {correlation ? (
          <div className="mt-5 rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Coins size={12} /> Tom × preço
              </h4>
              <span className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                <Chip className={readingChip(correlation.window_move.reading)}>
                  {READING_LABELS[correlation.window_move.reading] ?? correlation.window_move.reading}
                </Chip>
                {correlation.price_source === "yahoo" ? <span>cotações: Yahoo Finance</span> : null}
                {correlation.price_source === "plataforma" ? <span>cotações: plataforma</span> : null}
              </span>
            </div>

            {loadingPrice ? (
              <p className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
                <Loader2 size={13} className="animate-spin" /> A obter cotações…
              </p>
            ) : priceError ? (
              <p className="mt-3 text-[11px] text-rose-200">{priceError}</p>
            ) : !correlation.price_days ? (
              <p className="mt-3 text-[11px] text-muted-foreground">
                {correlation.price_message ?? "Sem cotações para este ticker."}
              </p>
            ) : (
              <>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Kpi label="Correlação (mesmo dia)" value={correlationText(correlation.same_day.r)} hint={correlation.same_day.strength} />
                  <Kpi label="Spearman (posições)" value={correlationText(correlation.same_day.spearman)} hint="robustez a valores extremos" />
                  <Kpi
                    label="Dias alinhados"
                    value={`${number(correlation.pairs)} / ${number(correlation.price_days)}`}
                    hint={`mínimo ${correlation.min_pairs}`}
                  />
                  <Kpi
                    label="Tom do dia anterior"
                    value={correlationText(correlation.lag1.r)}
                    hint={`n = ${correlation.lag1.n} · ${correlation.lag1.strength}`}
                  />
                </div>

                <p className="mt-3 text-[11px] text-muted-foreground">
                  Na janela: tom <span className={tone(correlation.window_move.sentiment ?? 0)}>{signed(correlation.window_move.sentiment, 2)}</span> ·
                  preço{" "}
                  <span className={tone(correlation.window_move.change_pct ?? 0)}>
                    {correlation.window_move.change_pct === null
                      ? "—"
                      : `${correlation.window_move.change_pct >= 0 ? "+" : ""}${correlation.window_move.change_pct.toFixed(2)} %`}
                  </span>{" "}
                  · desvio {correlation.window_move.gap === null ? "—" : signed(correlation.window_move.gap, 2)}
                  {correlation.same_day.significant === true ? " · correlação com t ≥ 2 (p ≈ 0,05)" : ""}
                  {correlation.enough_data ? "" : " · amostra curta: leia como indício, não como relação estabelecida"}
                </p>

                {correlation.series.length ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[360px] text-[11px]">
                      <thead>
                        <tr className="text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                          <th className="py-1 pr-2 font-medium">Dia</th>
                          <th className="py-1 pr-2 font-medium">Tom</th>
                          <th className="py-1 pr-2 font-medium">Variação</th>
                          <th className="py-1 font-medium">Fecho</th>
                        </tr>
                      </thead>
                      <tbody>
                        {correlation.series.map((row) => (
                          <tr key={row.day} className="border-t border-white/5">
                            <td className="py-1 pr-2 font-mono">{row.day}</td>
                            <td className={`py-1 pr-2 font-mono ${tone(row.sentiment)}`}>{signed(row.sentiment, 2)}</td>
                            <td className={`py-1 pr-2 font-mono ${tone(row.change_pct)}`}>
                              {row.change_pct >= 0 ? "+" : ""}
                              {row.change_pct.toFixed(2)} %
                            </td>
                            <td className="py-1 font-mono text-muted-foreground">{row.close.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                <p className="mt-2 text-[10px] text-muted-foreground">{correlation.caveat}</p>
              </>
            )}
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Btn
            onClick={() => {
              onAnalyse?.(ticker);
              onClose();
            }}
            disabled={!onAnalyse}
            title="Analisar o corpus de notícias deste ticker"
          >
            <FileText size={13} /> Analisar notícias
          </Btn>
          <Btn onClick={onClose}>Fechar</Btn>
        </div>
      </div>
    </div>
  );
}

/** Folha para seguir outro ticker: o símbolo, o que trazer e o que aconteceu. */
function AddTickerSheet({
  ticker,
  onTicker,
  ingestNews,
  ingestPrices,
  onIngestNews,
  onIngestPrices,
  days,
  busy,
  result,
  onSubmit,
  onClose,
}: {
  ticker: string;
  onTicker: (value: string) => void;
  ingestNews: boolean;
  ingestPrices: boolean;
  onIngestNews: (value: boolean) => void;
  onIngestPrices: (value: boolean) => void;
  days: number;
  busy: boolean;
  result: MarketFollowResult | null;
  onSubmit: () => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="glass-card max-h-[88vh] w-full overflow-y-auto rounded-t-3xl p-4 sm:max-w-xl sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Plus size={15} /> Seguir outro ticker
            </h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              O símbolo fica na lista, as notícias e cotações são trazidas já (Yahoo Finance) e a série de {days} dias é construída a seguir.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar" className={`${focusRing} ${tap} rounded-xl px-2 hover:bg-white/10`}>
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="block flex-1">
            <span className="text-[11px] text-muted-foreground">Símbolo</span>
            <input
              value={ticker}
              onChange={(event) => onTicker(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSubmit();
              }}
              className={`${inputClass} mt-1 font-mono`}
              placeholder="ex.: NVDA, EDP.LS, ^GSPC"
              autoFocus
            />
          </label>
          <div className="flex flex-col justify-end gap-2 sm:w-52">
            <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
              <input type="checkbox" checked={ingestNews} onChange={(event) => onIngestNews(event.target.checked)} className="h-4 w-4 accent-violet-500" />
              Trazer notícias
            </label>
            <label className="inline-flex min-h-[44px] items-center gap-2 text-[11px] sm:min-h-[34px]">
              <input type="checkbox" checked={ingestPrices} onChange={(event) => onIngestPrices(event.target.checked)} className="h-4 w-4 accent-violet-500" />
              Trazer cotações
            </label>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Btn variant="primary" onClick={onSubmit} disabled={busy || !ticker.trim()}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {busy ? "A trazer e a analisar…" : "Adicionar e analisar"}
          </Btn>
          <span className="text-[10px] text-muted-foreground">Símbolos válidos: letras, números, «.» e «-» (ex.: EDP.LS, BRK-B, ^GSPC).</span>
        </div>

        {result ? (
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
            <p className="text-[11px] font-semibold">Resultado para {result.ticker}</p>
            <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
              <li>
                Notícias: {result.news ? `${number(result.news.indexed)} indexadas de ${number(result.news.total)}` : "não pedidas"}
                {result.news?.analyzed ? ` · ${number(result.news.analyzed)} analisadas (PT + entidades)` : ""}
              </li>
              <li>
                Série: {number(result.series?.days ?? 0)} dia(s) com notícias · {number(result.series?.news ?? 0)} notícia(s) na janela
                {result.series?.pruned ? ` · ${number(result.series.pruned)} dia(s) obsoletos removidos` : ""}
              </li>
              <li>
                Cotações: {result.prices?.points ? `${number(result.prices.points)} pontos (${result.prices.source})` : "sem cotações para este símbolo"}
                {result.prices?.stored?.indexed ? ` · ${number(result.prices.stored.indexed)} guardados na plataforma` : ""}
              </li>
            </ul>
            {result.errors.length ? <p className="mt-2 text-[11px] text-amber-200">{result.errors.join(" · ")}</p> : null}
            {result.suggestions.length ? (
              <div className="mt-3">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Quis dizer…</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {result.suggestions.map((item) => (
                    <button
                      key={item.ticker}
                      type="button"
                      onClick={() => onTicker(item.ticker)}
                      className={`${focusRing} rounded-full border border-white/10 bg-white/5 px-2 py-1 font-mono text-[10px] hover:bg-white/10`}
                      title={item.name || item.ticker}
                    >
                      {item.ticker}
                      {item.name ? <span className="ml-1 font-sans text-muted-foreground">{item.name.slice(0, 28)}</span> : null}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <Btn onClick={onClose}>Fechar</Btn>
        </div>
      </div>
    </div>
  );
}

/** Folha do boletim: o Markdown do relatório, com cópia e gravação no Office. */
function BriefSheet({
  brief,
  saving,
  onCopy,
  onSave,
  onClose,
}: {
  brief: MarketBrief;
  saving: boolean;
  onCopy: () => void;
  onSave: () => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true">
      <div className="glass-card max-h-[88vh] w-full overflow-y-auto rounded-t-3xl p-4 sm:max-w-3xl sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <ScrollText size={15} /> Boletim de mercado
            </h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {brief.window?.start} a {brief.window?.end} · {number(brief.kpis?.news)} notícia(s) · tom {signed(brief.kpis?.sentiment)} (
              {brief.kpis?.label})
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar" className={`${focusRing} ${tap} rounded-xl px-2 hover:bg-white/10`}>
            <X size={16} />
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Btn onClick={onCopy} title="Copiar o boletim em Markdown">
            <Copy size={13} /> Copiar
          </Btn>
          <Btn variant="primary" onClick={onSave} disabled={saving} title="Guardar o boletim no editor Office">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />} Guardar no Office
          </Btn>
        </div>

        <div className="prose prose-invert mt-4 max-w-none text-[12px] leading-relaxed [&_h1]:text-base [&_h2]:mt-4 [&_h2]:text-sm [&_table]:w-full [&_table]:text-[11px] [&_td]:py-1 [&_th]:py-1 [&_th]:text-left">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{brief.markdown}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
