import { useCallback, useEffect, useMemo, useState } from "react";
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
  Briefcase,
  Eye,
  Wallet,
  AlertTriangle,
} from "lucide-react";
import {
  getPortfolioSummary,
  getPortfolioTickerHistory,
  type PortfolioSummaryResponse,
  type TickerHistoryResponse,
} from "../portfolioApi";
import { usePortfolioScope, withPortfolioScope } from "../portfolioScope";
import { PortfolioChart } from "../components/portfolio/PortfolioChart";
import { PortfolioTickerCard } from "../components/portfolio/PortfolioTickerCard";
import { PortfolioNewsStrip } from "../components/portfolio/PortfolioNewsStrip";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";

const SECTIONS = [
  { id: "manage", label: "Gerir carteiras e ordens", icon: Briefcase, route: "/portfolio/manage", color: "text-emerald-400" },
  { id: "reporting", label: "Automatizar relatórios", icon: FileText, route: "/portfolio/reporting", color: "text-emerald-400" },
  { id: "forecast", label: "Antecipar o futuro", icon: Sparkles, route: "/portfolio/forecast", color: "text-violet-400" },
  { id: "resilience", label: "Construir portfólio resiliente", icon: ShieldAlert, route: "/portfolio/resilience", color: "text-amber-400" },
  { id: "attribution", label: "Ver o que impulsiona retornos", icon: PieChart, route: "/portfolio/attribution", color: "text-cyan-400" },
  { id: "risk", label: "Controlar risco", icon: BarChart3, route: "/portfolio/risk", color: "text-rose-400" },
];

export function PortfolioPage() {
  const scope = usePortfolioScope();
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [history, setHistory] = useState<Record<string, TickerHistoryResponse>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const portfolioId = scope.portfolioId;

  // A carteira escolhida é a fonte de todos os números desta página.
  const load = useCallback(async () => {
    if (scope.loading) return;
    if (!portfolioId) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const summary = await getPortfolioSummary({ portfolio_id: portfolioId });
      setData(summary);
      const histories: Record<string, TickerHistoryResponse> = {};
      for (const ticker of summary.tickers.slice(0, 5)) {
        if (ticker.error) continue;
        try {
          histories[ticker.ticker] = await getPortfolioTickerHistory(ticker.ticker, "1y", "1d");
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
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalValue = data?.portfolio_value ?? 0;
  const totalChange = data?.portfolio_change_pct ?? 0;
  const cashValue = data?.cash ?? 0;
  const investedValue = data?.invested_value ?? 0;
  const sectors = useMemo(
    () => new Set((data?.tickers ?? []).map((t) => t.sector).filter(Boolean)).size,
    [data],
  );
  const selectedTicker = useMemo(
    () => data?.tickers.find((t) => t.ticker === selected) || data?.tickers[0],
    [data, selected],
  );
  const watchlists = useMemo(
    () => scope.watchlists.filter((list) => list.items.length > 0),
    [scope.watchlists],
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
              {scope.active
                ? `${scope.active.name} · ${scope.active.ticker_count} tickers · dados reais do Yahoo Finance`
                : "Notícias do sistema · dados reais do Yahoo Finance"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PortfolioScopeBar scope={scope} />
            <a
              href="/portfolio/manage"
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600/20 px-3 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-600/30"
            >
              <Briefcase className="h-4 w-4" />
              Gerir carteiras
            </a>
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

        {/* Sem carteiras: convite a criar */}
        {!scope.loading && scope.portfolios.length === 0 ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center">
            <Wallet className="mx-auto h-10 w-10 text-slate-600" />
            <h2 className="mt-3 text-lg font-semibold text-white">Ainda não tem carteiras</h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-400">
              Os módulos de portfólio calculam sobre uma carteira sua. Crie a primeira e adicione tickers para
              começar.
            </p>
            <a
              href="/portfolio/manage"
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
            >
              <Briefcase className="h-4 w-4" />
              Criar carteira
            </a>
          </div>
        ) : null}

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
            <div className="text-xs uppercase tracking-wider text-slate-500">Investido / caixa</div>
            <div className="mt-2 text-2xl font-semibold text-white">
              {investedValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
            <div className="mt-1 text-sm text-slate-400">
              caixa {cashValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wider text-slate-500">Posições</div>
            <div className="mt-2 text-2xl font-semibold text-white">{data?.tickers.length ?? "-"}</div>
            <div className="mt-1 text-sm text-slate-400">{sectors} setores</div>
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
            {data.tickers.length === 0 ? (
              <div className="flex items-start gap-3 rounded-lg border border-amber-900/50 bg-amber-950/20 p-4 text-amber-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="text-sm">
                  Esta carteira ainda não tem tickers.{" "}
                  <a href="/portfolio/manage" className="underline">
                    Adicione posições
                  </a>{" "}
                  para ver cotações, gráficos e análises.
                </div>
              </div>
            ) : null}

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
                  {data.tickers.map((ticker, index) => (
                    <PortfolioTickerCard
                      key={ticker.ticker}
                      ticker={ticker}
                      weight={ticker.weight ?? data.weights[index] ?? 0}
                      selected={selected === ticker.ticker}
                      onClick={() => setSelected(selected === ticker.ticker ? null : ticker.ticker)}
                    />
                  ))}
                </div>

                {data.positioned ? (
                  <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
                    <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                      Posições e resultado
                    </h2>
                    <table className="w-full text-sm">
                      <thead className="bg-slate-900 text-left text-xs uppercase text-slate-500">
                        <tr>
                          <th className="px-4 py-2">Ticker</th>
                          <th className="px-4 py-2 text-right">Qtd.</th>
                          <th className="px-4 py-2 text-right">Preço médio</th>
                          <th className="px-4 py-2 text-right">Valor</th>
                          <th className="px-4 py-2 text-right">P&amp;L</th>
                          <th className="px-4 py-2 text-right">Peso</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {data.tickers.map((ticker) => (
                          <tr key={ticker.ticker}>
                            <td className="px-4 py-2 font-medium text-slate-100">{ticker.ticker}</td>
                            <td className="px-4 py-2 text-right text-slate-300">{ticker.quantity ?? 0}</td>
                            <td className="px-4 py-2 text-right text-slate-300">
                              {ticker.avg_price ? ticker.avg_price.toFixed(2) : "—"}
                            </td>
                            <td className="px-4 py-2 text-right text-slate-300">
                              {(ticker.market_value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                            <td
                              className={`px-4 py-2 text-right ${
                                (ticker.unrealized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                              }`}
                            >
                              {ticker.cost_basis
                                ? `${(ticker.unrealized_pnl ?? 0) >= 0 ? "+" : ""}${(
                                    ticker.unrealized_pnl ?? 0
                                  ).toLocaleString(undefined, { maximumFractionDigits: 2 })} (${(
                                    ticker.unrealized_pnl_pct ?? 0
                                  ).toFixed(2)}%)`
                                : "—"}
                            </td>
                            <td className="px-4 py-2 text-right text-slate-400">
                              {((ticker.weight ?? 0) * 100).toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                {watchlists.length > 0 ? (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                    <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                      <Eye className="h-4 w-4" /> Watchlists
                    </h2>
                    <div className="space-y-3">
                      {watchlists.map((list) => (
                        <div key={list.id}>
                          <div className="mb-1 flex items-center justify-between">
                            <span className="text-sm font-medium text-slate-200">{list.name}</span>
                            <span className="text-xs text-slate-500">{list.item_count} tickers</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {list.items.map((item) => (
                              <a
                                key={item.ticker}
                                href={`/tickers/${encodeURIComponent(item.ticker)}`}
                                title={item.name}
                                className="rounded-full bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-700"
                              >
                                {item.ticker}
                              </a>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
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
                  <p className="mb-3 text-xs text-slate-500">
                    Todos os módulos calculam sobre «{scope.active?.name ?? "a carteira escolhida"}».
                  </p>
                  <div className="space-y-2">
                    {SECTIONS.map((section) => (
                      <a
                        key={section.id}
                        href={withPortfolioScope(section.route, portfolioId)}
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
