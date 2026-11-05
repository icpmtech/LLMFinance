import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  TrendingUp,
  ShieldAlert,
  PieChart,
  Sparkles,
  FileText,
  Newspaper,
  RefreshCw,
  ChevronRight,
} from "lucide-react";
import {
  getPortfolioSummary,
  getPortfolioTickerHistory,
  type PortfolioSummaryResponse,
  type TickerHistoryResponse,
} from "../portfolioApi";
import { PortfolioChart } from "../components/portfolio/PortfolioChart";
import { PortfolioTickerCard } from "../components/portfolio/PortfolioTickerCard";
import { PortfolioNewsStrip } from "../components/portfolio/PortfolioNewsStrip";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

const SECTIONS = [
  { id: "reporting", label: "Automatizar relatórios", icon: FileText, route: "/portfolio/reporting", color: "text-emerald-400" },
  { id: "forecast", label: "Antecipar o futuro", icon: Sparkles, route: "/portfolio/forecast", color: "text-violet-400" },
  { id: "resilience", label: "Construir portfólio resiliente", icon: ShieldAlert, route: "/portfolio/resilience", color: "text-amber-400" },
  { id: "attribution", label: "Ver o que impulsiona retornos", icon: PieChart, route: "/portfolio/attribution", color: "text-cyan-400" },
  { id: "risk", label: "Controlar risco", icon: BarChart3, route: "/portfolio/risk", color: "text-rose-400" },
];

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [history, setHistory] = useState<Record<string, TickerHistoryResponse>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const tickersParam = params.get("tickers");
  const weightsParam = params.get("weights");

  const tickers = useMemo(() => (tickersParam ? tickersParam.split(",") : undefined), [tickersParam]);
  const weights = useMemo(
    () => (weightsParam ? weightsParam.split(",").map(Number) : undefined),
    [weightsParam],
  );

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await getPortfolioSummary({ tickers, weights });
      setData(summary);
      const histories: Record<string, TickerHistoryResponse> = {};
      for (const t of summary.tickers.slice(0, 5)) {
        if (t.error) continue;
        try {
          histories[t.ticker] = await getPortfolioTickerHistory(t.ticker, "1y", "1d");
        } catch {
          // ignorar falhas individuais de histórico
        }
      }
      setHistory(histories);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar portfólio");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [tickersParam, weightsParam]);

  const totalValue = data?.portfolio_value ?? 0;
  const totalChange = data?.portfolio_change_pct ?? 0;
  const selectedTicker = useMemo(
    () => data?.tickers.find((t) => t.ticker === selected) || data?.tickers[0],
    [data, selected],
  );

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        {/* Header */}
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white flex items-center gap-2">
              <TrendingUp className="h-6 w-6 text-emerald-400" />
              Portfólio
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Dados reais do Yahoo Finance · notícias do sistema
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Atualizar
            </button>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wider text-slate-500">Valor da carteira</div>
            <div className="mt-2 text-2xl font-semibold text-white">
              {totalValue.toLocaleString(undefined, { style: "currency", currency: data?.currency || "USD" })}
            </div>
            <div className={`mt-1 flex items-center gap-1 text-sm font-medium ${totalChange >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {totalChange >= 0 ? "+" : ""}
              {totalChange.toFixed(2)}% hoje
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wider text-slate-500">Ativos</div>
            <div className="mt-2 text-2xl font-semibold text-white">{data?.tickers.length ?? "-"}</div>
            <div className="mt-1 text-sm text-slate-400">{data?.tickers.filter((t) => t.sector).length ?? 0} setores</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wider text-slate-500">Benchmark</div>
            <div className="mt-2 text-2xl font-semibold text-white">{data?.benchmark.name ?? "S&P 500"}</div>
            <div className="mt-1 text-sm text-slate-400">{data?.benchmark.ticker ?? "^GSPC"}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wider text-slate-500">Notícias</div>
            <div className="mt-2 text-2xl font-semibold text-white">{data?.news.length ?? "-"}</div>
            <div className="mt-1 text-sm text-slate-400">últimas 72h</div>
          </div>
        </div>

        {/* Main content */}
        {loading && !data ? (
          <PortfolioLoading />
        ) : error ? (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">
            {error}
          </div>
        ) : data ? (
          <>
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-6">
                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                      Performance normalizada (base 100)
                    </h2>
                    {selectedTicker && (
                      <span className="text-xs text-slate-500">
                        Destaque: {selectedTicker.ticker} · {selectedTicker.name}
                      </span>
                    )}
                  </div>
                  <PortfolioChart history={history} selected={selected} />
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {data.tickers.map((t) => (
                    <PortfolioTickerCard
                      key={t.ticker}
                      ticker={t}
                      weight={data.weights[data.tickers.indexOf(t)] ?? 0}
                      selected={selected === t.ticker}
                      onClick={() => setSelected(selected === t.ticker ? null : t.ticker)}
                    />
                  ))}
                </div>
              </div>

              <div className="space-y-6">
                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                    <Newspaper className="h-4 w-4" />
                    Notícias recentes
                  </h2>
                  <PortfolioNewsStrip news={data.news} />
                </div>

                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Módulos de portfólio
                  </h2>
                  <div className="space-y-2">
                    {SECTIONS.map((section) => (
                      <a
                        key={section.id}
                        href={section.route}
                        className="group flex items-center justify-between rounded-md bg-slate-800/50 p-3 hover:bg-slate-800 transition"
                      >
                        <div className="flex items-center gap-3">
                          <section.icon className={`h-5 w-5 ${section.color}`} />
                          <span className="text-sm font-medium text-slate-200">{section.label}</span>
                        </div>
                        <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-slate-300" />
                      </a>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
