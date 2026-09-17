import { useEffect, useState, useMemo } from "react";
import {
  ArrowLeft,
  Building2,
  Loader2,
  Frown,
  FileText,
  TrendingUp,
  Euro,
  Calendar,
  User,
  ExternalLink,
  Network,
  Briefcase,
  HandCoins,
  Activity,
  Tag,
} from "lucide-react";
import { getCompanyDetail, getCompanyContracts, getCompanyAnalytics } from "../api";
import { SeeAllContractsButton } from "./EntityContractsWindow";
import type { CompanyDetail, CompanyContractsResponse, CompanyAnalyticsResponse, ContractItem, ContractParty, ContractAnalyticsRow } from "../types";

interface CompanyDetailPageProps {
  nif: string;
  onBack: () => void;
  onSwitchDashboard?: () => void;
  onViewContract?: (contractId: string) => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

function formatDate(d?: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("pt-PT");
}

function partyText(party?: ContractParty | ContractParty[]) {
  if (!party) return "—";
  const list = Array.isArray(party) ? party : [party];
  const names = list
    .flatMap((p) => p.parsed || [])
    .map((p) => p.nome)
    .filter(Boolean);
  return names.length ? names.join(", ") : "—";
}

function contractValue(c: ContractItem) {
  return c.precoContratual ?? c.PrecoTotalEfetivo ?? undefined;
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

export default function CompanyDetailPage({
  nif,
  onBack,
  onSwitchDashboard,
  onViewContract,
}: CompanyDetailPageProps) {
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [contracts, setContracts] = useState<CompanyContractsResponse | null>(null);
  const [analytics, setAnalytics] = useState<CompanyAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!nif) {
      setError("NIF em falta");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getCompanyDetail(nif), getCompanyContracts(nif), getCompanyAnalytics(nif)])
      .then(([d, c, a]) => {
        if (cancelled) return;
        setCompany(d);
        setContracts(c);
        setAnalytics(a);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Erro ao carregar entidade");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nif]);

  const allContracts = contracts?.items ?? [];
  const relatedEntities = analytics?.top_partners ?? [];
  const cpvBreakdown = analytics?.by_cpv ?? [];
  const yearly = analytics?.by_year ?? [];

  const firstYear = useMemo(() => {
    const years = [
      company?.adjudicante?.first_year,
      company?.adjudicatario?.first_year,
    ].filter((y): y is number => typeof y === "number");
    return years.length ? Math.min(...years) : undefined;
  }, [company]);

  const lastYear = useMemo(() => {
    const years = [
      company?.adjudicante?.last_year,
      company?.adjudicatario?.last_year,
    ].filter((y): y is number => typeof y === "number");
    return years.length ? Math.max(...years) : undefined;
  }, [company]);

  if (loading) {
    return (
      <div className="min-h-screen w-full bg-background text-foreground flex items-center justify-center orbit-bg">
        <Loader2 size={44} className="animate-spin text-teal-400" />
      </div>
    );
  }

  if (error || !company) {
    return (
      <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <button
            onClick={onBack}
            className="mb-4 flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
          <div className="p-6 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-3">
            <Frown size={24} />
            {error || "Entidade não encontrada"}
          </div>
        </div>
      </div>
    );
  }

  const yearlyMax = maxValue(yearly);
  const cpvMax = maxValue(cpvBreakdown);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <button
            onClick={onBack}
            className="self-start flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar ao diretório
          </button>
          {onSwitchDashboard && (
            <button
              onClick={onSwitchDashboard}
              className="flex items-center gap-2 px-4 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm"
            >
              <TrendingUp size={18} className="text-amber-400" />
              Dashboard
            </button>
          )}
        </div>

        {/* Entity hero */}
        <div className="glass-card gradient-border rounded-3xl p-6 md:p-8 mb-8 fade-in">
          <div className="flex flex-col md:flex-row md:items-center gap-5">
            <div className="shrink-0 p-4 rounded-3xl bg-gradient-to-br from-teal-500/20 via-blue-500/15 to-rose-500/10 border border-white/10 glow-teal">
              <Building2 size={44} className="text-teal-300" />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl md:text-4xl font-bold leading-tight mb-1">{company.name}</h1>
              <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                {company.nif && <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10">NIF {company.nif}</span>}
                {company.normalized_name && company.normalized_name !== company.name && (
                  <span>{company.normalized_name}</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5 glow-teal">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <FileText size={16} className="text-teal-400" />
              Total de contratos
            </div>
            <p className="text-3xl font-bold stat-value text-glow-teal">{company.contracts_total ?? 0}</p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-amber">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Euro size={16} className="text-amber-400" />
              Valor total
            </div>
            <p className="text-2xl md:text-3xl font-bold stat-value text-glow-amber">{formatPrice(company.total_value)}</p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-blue">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Calendar size={16} className="text-blue-400" />
              Período
            </div>
            <p className="text-3xl font-bold stat-value text-glow-blue">
              {firstYear ?? "—"} — {lastYear ?? "—"}
            </p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-rose">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Activity size={16} className="text-rose-400" />
              Média / contrato
            </div>
            <p className="text-2xl md:text-3xl font-bold stat-value text-glow-rose">
              {formatPrice(analytics?.avg_value)}
            </p>
          </div>
        </div>

        {/* Role cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
          {company.adjudicante && company.adjudicante.contracts_count > 0 && (
            <div className="glass-card gradient-border rounded-2xl p-6 glow-blue">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-xl bg-blue-500/15 border border-blue-400/20">
                  <Briefcase size={22} className="text-blue-400" />
                </div>
                <h2 className="text-xl font-semibold">Como Adjudicante</h2>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="glass-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Contratos</p>
                  <p className="text-2xl font-bold stat-value mt-1">{company.adjudicante.contracts_count}</p>
                </div>
                <div className="glass-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor total</p>
                  <p className="text-xl font-bold stat-value text-glow-amber mt-1">{formatPrice(company.adjudicante.total_value)}</p>
                </div>
              </div>
            </div>
          )}
          {company.adjudicatario && company.adjudicatario.contracts_count > 0 && (
            <div className="glass-card gradient-border rounded-2xl p-6 glow-teal">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-xl bg-emerald-500/15 border border-emerald-400/20">
                  <HandCoins size={22} className="text-emerald-400" />
                </div>
                <h2 className="text-xl font-semibold">Como Adjudicatário</h2>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="glass-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Contratos</p>
                  <p className="text-2xl font-bold stat-value mt-1">{company.adjudicatario.contracts_count}</p>
                </div>
                <div className="glass-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor total</p>
                  <p className="text-xl font-bold stat-value text-glow-amber mt-1">{formatPrice(company.adjudicatario.total_value)}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Top partners */}
        {(company.top_adjudicantes?.length > 0 || company.top_adjudicatarios?.length > 0) && (
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-4">
              <Network size={20} className="text-teal-400" />
              <h2 className="text-xl font-semibold">Rede de entidades</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {company.top_adjudicantes?.length > 0 && (
                <div className="glass-card gradient-border rounded-2xl p-5">
                  <h3 className="text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-500" />
                    Principais Adjudicantes
                  </h3>
                  <div className="space-y-3">
                    {company.top_adjudicantes.slice(0, 8).map((e, i) => (
                      <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/5">
                        <div className="w-8 h-8 rounded-full bg-blue-500/15 flex items-center justify-center shrink-0 text-xs font-bold text-blue-300">
                          {i + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate" title={e.nome || e.nif}>{e.nome || e.nif || "—"}</p>
                          {e.nif && <p className="text-xs text-muted-foreground">NIF {e.nif}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {company.top_adjudicatarios?.length > 0 && (
                <div className="glass-card gradient-border rounded-2xl p-5">
                  <h3 className="text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    Principais Adjudicatários
                  </h3>
                  <div className="space-y-3">
                    {company.top_adjudicatarios.slice(0, 8).map((e, i) => (
                      <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/5">
                        <div className="w-8 h-8 rounded-full bg-emerald-500/15 flex items-center justify-center shrink-0 text-xs font-bold text-emerald-300">
                          {i + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate" title={e.nome || e.nif}>{e.nome || e.nif || "—"}</p>
                          {e.nif && <p className="text-xs text-muted-foreground">NIF {e.nif}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Breakdown columns */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {yearly.length > 0 && (
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h3 className="text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
                <TrendingUp size={16} className="text-teal-400" />
                Por ano
              </h3>
              <div className="space-y-3">
                {yearly.map((row, i) => (
                  <div key={i}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="font-medium">{row.key}</span>
                      <div className="text-right">
                        <span className="font-medium">{formatPrice(row.total_value)}</span>
                        <span className="text-xs text-muted-foreground ml-2">{row.count} contratos</span>
                      </div>
                    </div>
                    <MiniBar value={row.total_value || 0} max={yearlyMax} color="bg-teal-400" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {cpvBreakdown.length > 0 && (
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h3 className="text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
                <Tag size={16} className="text-amber-400" />
                Por categoria (CPV)
              </h3>
              <div className="space-y-3">
                {cpvBreakdown.slice(0, 8).map((row, i) => (
                  <div key={i}>
                    <div className="flex items-center justify-between text-sm mb-1 gap-3">
                      <span className="truncate" title={row.description || row.key}>{row.description || row.key}</span>
                      <div className="text-right shrink-0">
                        <span className="font-medium">{formatPrice(row.total_value)}</span>
                        <span className="text-xs text-muted-foreground ml-2">{row.count}</span>
                      </div>
                    </div>
                    <MiniBar value={row.total_value || 0} max={cpvMax} color="bg-amber-400" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {relatedEntities.length > 0 && (
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h3 className="text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center gap-2">
                <User size={16} className="text-rose-400" />
                Entidades relacionadas
              </h3>
              <div className="space-y-3 max-h-[28rem] overflow-auto pr-1">
                {relatedEntities.slice(0, 20).map((entity, i) => (
                  <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-white/[0.03] border border-white/5 text-sm">
                    <span className="truncate max-w-[70%]" title={entity.description || entity.key}>{entity.description || entity.key}</span>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{entity.count} contratos</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Contracts table */}
        <div className="glass-card gradient-border rounded-2xl p-5 md:p-6">
          <div className="flex items-center gap-3 mb-5">
            <div className="p-2 rounded-xl bg-primary/15 border border-primary/20">
              <FileText size={20} className="text-primary" />
            </div>
            <h2 className="text-xl font-semibold">Contratos recentes</h2>
            <span className="ml-auto text-sm text-muted-foreground">{allContracts.length} visíveis</span>
            <SeeAllContractsButton nif={nif} name={company.name} total={company.contracts_total} compact />
          </div>
          {allContracts.length === 0 ? (
            <p className="text-muted-foreground">Sem contratos registados para esta entidade.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left text-muted-foreground">
                    <th className="py-3 pr-4 font-medium">Objeto</th>
                    <th className="py-3 pr-4 font-medium">Adjudicante(s)</th>
                    <th className="py-3 pr-4 font-medium">Adjudicatário(s)</th>
                    <th className="py-3 pr-4 font-medium">Data</th>
                    <th className="py-3 pr-4 font-medium">Valor</th>
                    <th className="py-3">/</th>
                  </tr>
                </thead>
                <tbody>
                  {allContracts.map((c, idx) => (
                    <tr
                      key={c.idcontrato || c.doc_id || idx}
                      className="border-b border-white/5 hover:bg-white/[0.04] transition"
                    >
                      <td className="py-3 pr-4 max-w-xs truncate" title={c.objectoContrato || c.descContrato || ""}>
                        {c.objectoContrato || c.descContrato || "—"}
                      </td>
                      <td className="py-3 pr-4 max-w-xs truncate text-muted-foreground" title={partyText(c.adjudicantes)}>
                        {partyText(c.adjudicantes)}
                      </td>
                      <td className="py-3 pr-4 max-w-xs truncate text-muted-foreground" title={partyText(c.adjudicatarios)}>
                        {partyText(c.adjudicatarios)}
                      </td>
                      <td className="py-3 pr-4 whitespace-nowrap text-muted-foreground">
                        {formatDate(c.dataPublicacao || c.dataCelebracaoContrato)}
                      </td>
                      <td className="py-3 pr-4 font-medium text-glow-amber">{formatPrice(contractValue(c))}</td>
                      <td className="py-3">
                        {onViewContract && c.idcontrato && (
                          <button
                            onClick={() => onViewContract(c.idcontrato!)}
                            className="p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-foreground transition"
                            title="Ver contrato"
                          >
                            <ExternalLink size={16} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
