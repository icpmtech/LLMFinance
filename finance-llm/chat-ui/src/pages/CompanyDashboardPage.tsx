import { useEffect, useState, useMemo } from "react";
import {
  ArrowLeft,
  Building2,
  Loader2,
  Frown,
  BarChart3,
  Euro,
  FileText,
  Calendar,
  TrendingUp,
  Search,
  Briefcase,
  HandCoins,
  Sparkles,
} from "lucide-react";
import { searchCompanies } from "../api";
import type { CompanySummary, ContractAnalyticsRow } from "../types";

interface CompanyDashboardPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
  onSelectCompany: (nif: string) => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

function maxValue(rows: ContractAnalyticsRow[]) {
  return Math.max(...rows.map((r) => r.total_value || 0), 1);
}

function MiniBar({ value, max, color = "bg-teal-400" }: { value: number; max: number; color?: string }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
  glow,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  color: string;
  glow: string;
}) {
  return (
    <div className={`glass-card gradient-border rounded-2xl p-5 ${glow}`}>
      <div className={`flex items-center gap-2 text-sm text-muted-foreground mb-2`}>
        <Icon size={18} className={color} />
        {label}
      </div>
      <p className="text-2xl md:text-3xl font-bold stat-value">{value}</p>
    </div>
  );
}

function CompanyRow({
  company,
  rank,
  max,
  color,
  onSelectCompany,
}: {
  company: CompanySummary;
  rank: number;
  max: number;
  color: string;
  onSelectCompany: (nif: string) => void;
}) {
  const id = company.nif || company.normalized_name || company.name;
  return (
    <button
      key={id}
      onClick={() => id && onSelectCompany(company.nif || id)}
      className="w-full text-left p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition group"
    >
      <div className="flex items-center gap-3">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${color}`}>
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium truncate max-w-[60%] group-hover:text-teal-300 transition">{company.name}</span>
            <span className="text-sm font-bold stat-value">{formatPrice(company.total_value)}</span>
          </div>
          <MiniBar value={company.total_value || 0} max={max} color={color.replace("bg-", "bg-").replace("/15", "").replace("text-", "") || "bg-teal-400"} />
          <p className="text-xs text-muted-foreground mt-1">{company.contracts_total} contratos</p>
        </div>
      </div>
    </button>
  );
}

export default function CompanyDashboardPage({
  onSwitchView,
  onSwitchSearch,
  onSelectCompany,
}: CompanyDashboardPageProps) {
  const [topCompanies, setTopCompanies] = useState<CompanySummary[]>([]);
  const [topAdjudicantes, setTopAdjudicantes] = useState<CompanySummary[]>([]);
  const [topAdjudicatarios, setTopAdjudicatarios] = useState<CompanySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      searchCompanies({ role: "all", min_contracts: 1, size: 10, from: 0 }),
      searchCompanies({ role: "adjudicante", min_contracts: 1, size: 5, from: 0 }),
      searchCompanies({ role: "adjudicatario", min_contracts: 1, size: 5, from: 0 }),
    ])
      .then(([allData, adjData, contData]) => {
        if (cancelled) return;
        setTopCompanies(allData.items ?? []);
        setTopAdjudicantes(adjData.items ?? []);
        setTopAdjudicatarios(contData.items ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Erro ao carregar dashboard");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalValue = useMemo(
    () => topCompanies.reduce((acc, c) => acc + (c.total_value || 0), 0),
    [topCompanies],
  );
  const totalContracts = useMemo(
    () => topCompanies.reduce((acc, c) => acc + (c.contracts_total || 0), 0),
    [topCompanies],
  );
  const maxCompanyValue = useMemo(
    () => Math.max(...topCompanies.map((c) => c.total_value || 0), 1),
    [topCompanies],
  );

  function yearRows(): ContractAnalyticsRow[] {
    const map: Record<string, ContractAnalyticsRow> = {};
    topCompanies.forEach((c) => {
      const y = c.adjudicante?.last_year ?? c.adjudicatario?.last_year;
      if (!y) return;
      const k = String(y);
      if (!map[k]) map[k] = { key: k, count: 0, total_value: 0, description: undefined };
      map[k].count += c.contracts_total || 0;
      map[k].total_value = (map[k].total_value || 0) + (c.total_value || 0);
    });
    return Object.values(map).sort((a, b) => a.key.localeCompare(b.key));
  }

  const byYear = yearRows();
  const maxByYear = maxValue(byYear);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-8">
          <button
            onClick={onSwitchView}
            className="self-start flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
          <div className="flex items-center gap-3">
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="flex items-center gap-2 px-4 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm"
              >
                <Search size={18} className="text-teal-400" />
                Pesquisar
              </button>
            )}
          </div>
        </div>

        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-amber-300 mb-3">
            <Sparkles size={14} />
            Visão agregada do universo contratual
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-amber-500/20 to-rose-500/15 border border-white/10">
              <BarChart3 size={32} className="text-amber-400" />
            </span>
            Dashboard de Empresas
          </h1>
        </div>

        {loading && (
          <div className="flex justify-center py-16">
            <Loader2 size={44} className="animate-spin text-teal-400" />
          </div>
        )}

        {!loading && error && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2">
            <Frown size={20} />
            {error}
          </div>
        )}

        {!loading && !error && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8 fade-in">
              <StatCard
                icon={Building2}
                label="Entidades ativas"
                value={topCompanies.length.toLocaleString("pt-PT")}
                color="text-blue-400"
                glow="glow-blue"
              />
              <StatCard
                icon={FileText}
                label="Total de contratos"
                value={totalContracts.toLocaleString("pt-PT")}
                color="text-teal-400"
                glow="glow-teal"
              />
              <StatCard
                icon={Euro}
                label="Valor total indexado"
                value={formatPrice(totalValue)}
                color="text-amber-400"
                glow="glow-amber"
              />
              <StatCard
                icon={Calendar}
                label="Anos cobertos"
                value={byYear.length > 0 ? `${byYear[0].key} — ${byYear[byYear.length - 1].key}` : "—"}
                color="text-rose-400"
                glow="glow-rose"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
              <div className="glass-card gradient-border rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-5">
                  <div className="p-2 rounded-xl bg-amber-500/15 border border-amber-400/20">
                    <TrendingUp size={20} className="text-amber-400" />
                  </div>
                  <h2 className="text-xl font-semibold">Top entidades por valor</h2>
                </div>
                <div className="space-y-3">
                  {topCompanies.length === 0 && <p className="text-muted-foreground">Sem dados suficientes.</p>}
                  {topCompanies.map((c, i) => (
                    <CompanyRow
                      key={c.nif || c.name}
                      company={c}
                      rank={i + 1}
                      max={maxCompanyValue}
                      color="bg-amber-500/15 text-amber-300"
                      onSelectCompany={onSelectCompany}
                    />
                  ))}
                </div>
              </div>

              <div className="glass-card gradient-border rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-5">
                  <div className="p-2 rounded-xl bg-teal-500/15 border border-teal-400/20">
                    <Calendar size={20} className="text-teal-400" />
                  </div>
                  <h2 className="text-xl font-semibold">Evolução por ano</h2>
                </div>
                {byYear.length > 0 ? (
                  <div className="space-y-4">
                    {byYear.map((row, i) => (
                      <div key={i}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium">{row.key}</span>
                          <span className="text-sm">{formatPrice(row.total_value)} <span className="text-muted-foreground">({row.count})</span></span>
                        </div>
                        <MiniBar value={row.total_value || 0} max={maxByYear} color="bg-teal-400" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-muted-foreground">Sem dados suficientes.</p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="glass-card gradient-border rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-5">
                  <div className="p-2 rounded-xl bg-blue-500/15 border border-blue-400/20">
                    <Briefcase size={20} className="text-blue-400" />
                  </div>
                  <h2 className="text-xl font-semibold">Top adjudicantes</h2>
                </div>
                <div className="space-y-3">
                  {topAdjudicantes.length === 0 && <p className="text-muted-foreground">Sem dados suficientes.</p>}
                  {topAdjudicantes.map((c, i) => (
                    <CompanyRow
                      key={c.nif || c.name}
                      company={c}
                      rank={i + 1}
                      max={maxCompanyValue}
                      color="bg-blue-500/15 text-blue-300"
                      onSelectCompany={onSelectCompany}
                    />
                  ))}
                </div>
              </div>

              <div className="glass-card gradient-border rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-5">
                  <div className="p-2 rounded-xl bg-emerald-500/15 border border-emerald-400/20">
                    <HandCoins size={20} className="text-emerald-400" />
                  </div>
                  <h2 className="text-xl font-semibold">Top adjudicatários</h2>
                </div>
                <div className="space-y-3">
                  {topAdjudicatarios.length === 0 && <p className="text-muted-foreground">Sem dados suficientes.</p>}
                  {topAdjudicatarios.map((c, i) => (
                    <CompanyRow
                      key={c.nif || c.name}
                      company={c}
                      rank={i + 1}
                      max={maxCompanyValue}
                      color="bg-emerald-500/15 text-emerald-300"
                      onSelectCompany={onSelectCompany}
                    />
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
