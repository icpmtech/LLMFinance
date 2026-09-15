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
  PieChart,
  Search,
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

function simpleBar(value: number, max: number) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
      <div
        className="h-full bg-primary rounded-full"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function CompanyDashboardPage({
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

  const maxByYear = useMemo(
    () => Math.max(...yearRows().map((r) => r.total_value || 0), 1),
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
  const byCpv: ContractAnalyticsRow[] = [];
  const procedures: ContractAnalyticsRow[] = [];
  const contractTypes: ContractAnalyticsRow[] = [];

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-6xl mx-auto px-4 py-6">
        <button
          onClick={onSwitchView}
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <BarChart3 size={28} />
              Dashboard de Empresas
            </h1>
            <p className="text-sm text-muted-foreground mt-1">Visão agregada das entidades nos contratos públicos.</p>
          </div>
          <div className="flex items-center gap-2">
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border hover:bg-accent transition text-sm"
              >
                <Search size={18} />
                Pesquisar
              </button>
            )}
          </div>
        </div>

        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 size={36} className="animate-spin text-primary" />
          </div>
        )}

        {!loading && error && (
          <div className="mb-4 p-4 rounded-lg bg-destructive/10 text-destructive flex items-center gap-2">
            <Frown size={18} />
            {error}
          </div>
        )}

        {!loading && !error && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <div className="bg-card border border-border rounded-xl p-4">
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <Building2 size={16} />
                  Entidades ativas
                </p>
                <p className="text-2xl font-bold mt-1">{topCompanies.length.toLocaleString("pt-PT")}</p>
              </div>
              <div className="bg-card border border-border rounded-xl p-4">
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <FileText size={16} />
                  Total de contratos
                </p>
                <p className="text-2xl font-bold mt-1">{totalContracts.toLocaleString("pt-PT")}</p>
              </div>
              <div className="bg-card border border-border rounded-xl p-4">
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <Euro size={16} />
                  Valor total indexado
                </p>
                <p className="text-2xl font-bold mt-1">{formatPrice(totalValue)}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <TrendingUp size={20} />
                  Top entidades por valor
                </h2>
                <div className="space-y-3">
                  {topCompanies.length === 0 && (
                    <p className="text-muted-foreground">Sem dados suficientes.</p>
                  )}
                  {topCompanies.map((c) => {
                    const id = c.nif || c.normalized_name || c.name;
                    return (
                      <button
                        key={id}
                        onClick={() => id && onSelectCompany(c.nif || id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium truncate max-w-[60%]">{c.name}</span>
                          <span className="text-sm font-semibold">{formatPrice(c.total_value)}</span>
                        </div>
                        {simpleBar(c.total_value || 0, maxCompanyValue)}
                        <p className="text-xs text-muted-foreground mt-1">{c.contracts_total} contratos</p>
                      </button>
                    );
                  })}
                </div>
              </div>

              {byYear.length > 0 && (
                <div className="bg-card border border-border rounded-xl p-5">
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Calendar size={20} />
                    Evolução por ano
                  </h2>
                  <div className="space-y-3">
                    {byYear.map((row, i) => (
                      <div key={i}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm">{row.key}</span>
                          <span className="text-sm font-medium">{formatPrice(row.total_value)} ({row.count})</span>
                        </div>
                        {simpleBar(row.total_value || 0, maxByYear)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {byCpv.length === 0 && (
                <div className="bg-card border border-border rounded-xl p-5">
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <PieChart size={20} />
                    Por CPV
                  </h2>
                  <p className="text-sm text-muted-foreground">CPV ainda não extraído agregadamente.</p>
                </div>
              )}

              {procedures.length === 0 && (
                <div className="bg-card border border-border rounded-xl p-5">
                  <h2 className="text-lg font-semibold mb-4">Por procedimento</h2>
                  <p className="text-sm text-muted-foreground">Dados por procedimento não disponíveis nesta visão agregada.</p>
                </div>
              )}

              {contractTypes.length === 0 && (
                <div className="bg-card border border-border rounded-xl p-5">
                  <h2 className="text-lg font-semibold mb-4">Por tipo de contrato</h2>
                  <p className="text-sm text-muted-foreground">Dados por tipo de contrato não disponíveis nesta visão agregada.</p>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <Building2 size={20} />
                  Top adjudicantes
                </h2>
                <div className="space-y-3">
                  {topAdjudicantes.length === 0 && (
                    <p className="text-muted-foreground">Sem dados suficientes.</p>
                  )}
                  {topAdjudicantes.map((c) => {
                    const id = c.nif || c.normalized_name || c.name;
                    return (
                      <button
                        key={id}
                        onClick={() => id && onSelectCompany(c.nif || id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium truncate max-w-[60%]">{c.name}</span>
                          <span className="text-sm font-semibold">{formatPrice(c.total_value)}</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">{c.contracts_total} contratos</p>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <TrendingUp size={20} />
                  Top adjudicatários
                </h2>
                <div className="space-y-3">
                  {topAdjudicatarios.length === 0 && (
                    <p className="text-muted-foreground">Sem dados suficientes.</p>
                  )}
                  {topAdjudicatarios.map((c) => {
                    const id = c.nif || c.normalized_name || c.name;
                    return (
                      <button
                        key={id}
                        onClick={() => id && onSelectCompany(c.nif || id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium truncate max-w-[60%]">{c.name}</span>
                          <span className="text-sm font-semibold">{formatPrice(c.total_value)}</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">{c.contracts_total} contratos</p>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default CompanyDashboardPage;
