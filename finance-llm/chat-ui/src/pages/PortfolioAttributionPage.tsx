import { useCallback, useEffect, useMemo, useState } from "react";
import { PieChart, RefreshCw, ArrowUpRight, ArrowDownRight, Download, Search } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Pie,
  PieChart as RechartsPieChart,
  Cell,
} from "recharts";
import { getPortfolioAttribution, type PortfolioAttributionResponse } from "../portfolioApi";
import { usePortfolioScope } from "../portfolioScope";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";

const COLORS = ["#34d399", "#60a5fa", "#f87171", "#fbbf24", "#a78bfa", "#22d3ee", "#f472b6", "#94a3b8"];

type Contributor = PortfolioAttributionResponse["top_contributors"][number];
type SectorSort = "total_effect" | "portfolio_weight" | "portfolio_return";

export function PortfolioAttributionPage() {
  const scope = usePortfolioScope();
  const portfolioId = scope.portfolioId;

  const [data, setData] = useState<PortfolioAttributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [contributorQuery, setContributorQuery] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [sectorSort, setSectorSort] = useState<SectorSort>("total_effect");

  const load = useCallback(async () => {
    if (scope.loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioAttribution({ portfolio_id: portfolioId ?? undefined });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar attribution");
    } finally {
      setLoading(false);
    }
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    void load();
  }, [load]);

  const sectorData =
    data?.sectors.map((s, i) => ({
      name: s.sector,
      allocation: Number((s.allocation_effect * 100).toFixed(2)),
      selection: Number((s.selection_effect * 100).toFixed(2)),
      total: Number((s.total_effect * 100).toFixed(2)),
      color: COLORS[i % COLORS.length],
    })) ?? [];

  const pieData =
    data?.sectors.map((s, i) => ({
      name: s.sector,
      value: Number((s.portfolio_weight * 100).toFixed(2)),
      color: COLORS[i % COLORS.length],
    })) ?? [];

  const sortedSectors = useMemo(
    () => [...(data?.sectors ?? [])].sort((a, b) => b[sectorSort] - a[sectorSort]),
    [data?.sectors, sectorSort],
  );
  const sectors = useMemo(
    () => [...new Set((data?.sectors ?? []).map((sector) => sector.sector))].sort(),
    [data?.sectors],
  );
  const filterContributors = (contributors: Contributor[]) =>
    contributors.filter((contributor) => {
      const matchesSector = !sectorFilter || contributor.sector === sectorFilter;
      const query = contributorQuery.trim().toLocaleLowerCase();
      const matchesQuery =
        !query ||
        contributor.ticker.toLocaleLowerCase().includes(query) ||
        contributor.name.toLocaleLowerCase().includes(query);
      return matchesSector && matchesQuery;
    });
  const topContributors = filterContributors(data?.top_contributors ?? []);
  const bottomContributors = filterContributors(data?.bottom_contributors ?? []);
  const strongestSector = data?.sectors.reduce<PortfolioAttributionResponse["sectors"][number] | null>(
    (best, sector) => (!best || sector.total_effect > best.total_effect ? sector : best),
    null,
  );
  const strongestContributor = data?.top_contributors[0];
  const weakestContributor = data?.bottom_contributors[0];

  const exportCsv = () => {
    if (!data) return;
    const contributors = new Map(
      [...data.top_contributors, ...data.bottom_contributors].map((contributor) => [contributor.ticker, contributor]),
    );
    const rows: (string | number)[][] = [
      ["Tipo", "Setor", "Ticker", "Nome", "Peso carteira (%)", "Retorno carteira (%)", "Retorno benchmark (%)", "Alocação (%)", "Seleção (%)", "Efeito total (%)"],
      ...data.sectors.map((sector) => [
        "Setor",
        sector.sector,
        sector.tickers.join(", "),
        "",
        sector.portfolio_weight * 100,
        sector.portfolio_return * 100,
        sector.benchmark_return * 100,
        sector.allocation_effect * 100,
        sector.selection_effect * 100,
        sector.total_effect * 100,
      ]),
      ...[...contributors.values()]
        .sort((a, b) => a.ticker.localeCompare(b.ticker))
        .map((contributor) => [
          "Ativo",
          contributor.sector,
          contributor.ticker,
          contributor.name,
          contributor.weight * 100,
          contributor.return_pct,
          "",
          "",
          "",
          contributor.contribution_pct,
        ]),
    ];
    const csv = `\uFEFF${rows
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `attribution-${data.period}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-cyan-500/10 p-2">
              <PieChart className="h-6 w-6 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Ver o que impulsiona retornos</h1>
              <p className="text-sm text-slate-400">
                Attribution Brinson: alocação por setor, selecção de títulos e contributors.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <PortfolioScopeBar scope={scope} />
            <button
              onClick={exportCsv}
              disabled={!data}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              Exportar CSV
            </button>
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

        {loading && !data ? (
          <PortfolioLoading />
        ) : error ? (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">{error}</div>
        ) : data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card label="Retorno carteira" value={`${data.portfolio_return.toFixed(2)}%`} />
              <Card label="Active return" value={`${data.active_return >= 0 ? "+" : ""}${data.active_return.toFixed(2)}%`} />
              <Card
                label="Setor com maior efeito"
                value={strongestSector?.sector ?? "—"}
                detail={strongestSector ? `${(strongestSector.total_effect * 100).toFixed(2)}% de efeito` : "Sem dados por setor"}
              />
              <Card
                label="Maior contribuidor"
                value={strongestContributor?.ticker ?? "—"}
                detail={
                  strongestContributor
                    ? `${strongestContributor.name} · ${strongestContributor.contribution_pct >= 0 ? "+" : ""}${strongestContributor.contribution_pct.toFixed(2)}%`
                    : `${data.sectors.length} setores · ${data.period}`
                }
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
              <span>{data.sectors.length} setores · período de {data.period}</span>
              {weakestContributor ? (
                <span>
                  Maior detrator: {weakestContributor.ticker} ({weakestContributor.contribution_pct.toFixed(2)}%)
                </span>
              ) : null}
            </div>
            {data.excluded_tickers?.length ? (
              <div className="rounded-md border border-amber-900/50 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
                Sem histórico suficiente no período para: {data.excluded_tickers.join(", ")}. Os restantes pesos foram
                normalizados para esta análise.
              </div>
            ) : null}

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Efeito de alocação vs selecção por setor
                </h2>
                <div className="mb-3 rounded-md border border-slate-800 bg-slate-950/60 p-3 text-xs leading-relaxed text-slate-400">
                  <div className="mb-1.5 flex flex-wrap gap-x-4 gap-y-1">
                    <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-cyan-400" />Alocação: efeito de sobre/subponderar o setor</span>
                    <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-pink-400" />Seleção: efeito da escolha dos ativos no setor</span>
                  </div>
                  <p>
                    Valores positivos favoreceram o retorno; negativos retiraram retorno. A decomposição é uma
                    aproximação: compara os pesos com setores igualmente ponderados e usa a média simples dos ativos
                    com histórico disponível como referência. O período é {data.period}.
                  </p>
                </div>
                {sectorData.length ? (
                  <div className="h-[360px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={sectorData}>
                        <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                        <XAxis dataKey="name" stroke="#64748b" tick={{ fontSize: 10 }} />
                        <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                          itemStyle={{ color: "#e2e8f0" }}
                          formatter={(value) => `${Number(value).toFixed(2)}%`}
                        />
                        <Bar dataKey="allocation" stackId="a" fill="#22d3ee" name="Alocação" />
                        <Bar dataKey="selection" stackId="a" fill="#f472b6" name="Selecção" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <EmptyState>Sem efeitos por setor para apresentar.</EmptyState>
                )}
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                  Peso da carteira por setor
                </h2>
                <p className="mb-3 rounded-md border border-slate-800 bg-slate-950/60 p-3 text-xs leading-relaxed text-slate-400">
                  Cada fatia mostra o peso dos ativos agrupados nesse setor. São usados apenas os ativos com histórico
                  de preços suficiente para a análise; por isso, os pesos podem não somar 100%.
                </p>
                {pieData.length ? (
                  <div className="h-[360px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsPieChart>
                        <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={120}>
                          {pieData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                          itemStyle={{ color: "#e2e8f0" }}
                          formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
                        />
                      </RechartsPieChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <EmptyState>Sem dados de peso por setor para este período.</EmptyState>
                )}
              </div>
            </div>

            <section className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
                <div>
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Detalhe por setor</h2>
                  <p className="mt-1 text-xs text-slate-500">Compare pesos, retornos e efeitos de alocação e seleção.</p>
                </div>
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  Ordenar por
                  <select
                    value={sectorSort}
                    onChange={(event) => {
                      const value = event.target.value;
                      if (value === "total_effect" || value === "portfolio_weight" || value === "portfolio_return") {
                        setSectorSort(value);
                      }
                    }}
                    className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-slate-200"
                    aria-label="Ordenar setores por"
                  >
                    <option value="total_effect">Efeito total</option>
                    <option value="portfolio_weight">Peso da carteira</option>
                    <option value="portfolio_return">Retorno da carteira</option>
                  </select>
                </label>
              </div>
              {sortedSectors.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[760px] text-sm">
                    <thead className="bg-slate-900/70 text-left text-xs uppercase text-slate-500">
                      <tr>
                        <th className="px-4 py-2">Setor</th>
                        <th className="px-4 py-2 text-right">Peso</th>
                        <th className="px-4 py-2 text-right">Retorno carteira</th>
                        <th className="px-4 py-2 text-right">Retorno referência</th>
                        <th className="px-4 py-2 text-right">Alocação</th>
                        <th className="px-4 py-2 text-right">Seleção</th>
                        <th className="px-4 py-2 text-right">Efeito total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {sortedSectors.map((sector) => (
                        <tr key={sector.sector}>
                          <td className="px-4 py-2 font-medium text-slate-200">
                            <div>{sector.sector}</div>
                            <div className="text-xs font-normal text-slate-500">{sector.tickers.join(", ")}</div>
                          </td>
                          <td className="px-4 py-2 text-right text-slate-300">{(sector.portfolio_weight * 100).toFixed(1)}%</td>
                          <td className="px-4 py-2 text-right text-slate-300">{(sector.portfolio_return * 100).toFixed(2)}%</td>
                          <td className="px-4 py-2 text-right text-slate-300">{(sector.benchmark_return * 100).toFixed(2)}%</td>
                          <EffectCell value={sector.allocation_effect} />
                          <EffectCell value={sector.selection_effect} />
                          <EffectCell value={sector.total_effect} />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState>A API não devolveu setores para esta carteira.</EmptyState>
              )}
            </section>

            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Contribuidores por ativo</h2>
                  <p className="mt-1 text-xs text-slate-500">Filtre os principais contribuidores e detratores por nome, ticker ou setor.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <label className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-500" />
                    <input
                      value={contributorQuery}
                      onChange={(event) => setContributorQuery(event.target.value)}
                      placeholder="Pesquisar ativo"
                      aria-label="Pesquisar contribuidores por ticker ou nome"
                      className="w-48 rounded-md border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-3 text-sm text-slate-200 placeholder:text-slate-600"
                    />
                  </label>
                  <select
                    value={sectorFilter}
                    onChange={(event) => setSectorFilter(event.target.value)}
                    aria-label="Filtrar contribuidores por setor"
                    className="max-w-48 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
                  >
                    <option value="">Todos os setores</option>
                    {sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-emerald-400">
                  Top contributors
                </h2>
                <div className="space-y-2">
                  {topContributors.length ? topContributors.map((c) => (
                    <div key={c.ticker} className="flex items-center justify-between rounded-md bg-slate-800/40 p-2">
                      <div>
                        <div className="text-sm font-medium text-slate-200">{c.ticker}</div>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span>{c.name}</span>
                          <span className="rounded bg-slate-700/70 px-1.5 py-0.5">{c.sector}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <span className="text-slate-400">{(c.weight * 100).toFixed(1)}%</span>
                        <span className="flex items-center gap-1 font-medium text-emerald-400">
                          <ArrowUpRight className="h-3.5 w-3.5" />
                          +{c.contribution_pct.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  )) : <EmptyState>Não há contribuidores que correspondam aos filtros.</EmptyState>}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-rose-400">
                  Bottom contributors
                </h2>
                <div className="space-y-2">
                  {bottomContributors.length ? bottomContributors.map((c) => (
                    <div key={c.ticker} className="flex items-center justify-between rounded-md bg-slate-800/40 p-2">
                      <div>
                        <div className="text-sm font-medium text-slate-200">{c.ticker}</div>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span>{c.name}</span>
                          <span className="rounded bg-slate-700/70 px-1.5 py-0.5">{c.sector}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <span className="text-slate-400">{(c.weight * 100).toFixed(1)}%</span>
                        <span className="flex items-center gap-1 font-medium text-rose-400">
                          <ArrowDownRight className="h-3.5 w-3.5" />
                          {c.contribution_pct.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  )) : <EmptyState>Não há detratores que correspondam aos filtros.</EmptyState>}
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Card({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-white" title={value}>{value}</div>
      {detail ? <div className="mt-1 truncate text-xs text-slate-500" title={detail}>{detail}</div> : null}
    </div>
  );
}

function EffectCell({ value }: { value: number }) {
  return (
    <td className={`px-4 py-2 text-right font-medium ${value >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
      {value >= 0 ? "+" : ""}{(value * 100).toFixed(2)}%
    </td>
  );
}

function EmptyState({ children }: { children: string }) {
  return <p className="p-6 text-center text-sm text-slate-500">{children}</p>;
}
