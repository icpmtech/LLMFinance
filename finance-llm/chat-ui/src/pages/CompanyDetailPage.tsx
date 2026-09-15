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
} from "lucide-react";
import { getCompanyDetail, getCompanyContracts, getCompanyAnalytics } from "../api";
import type { CompanyDetail, CompanyContractsResponse, CompanyAnalyticsResponse, ContractItem, ContractParty } from "../types";

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

export function CompanyDetailPage({
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
      <div className="min-h-screen w-full bg-background text-foreground flex items-center justify-center">
        <Loader2 size={40} className="animate-spin text-primary" />
      </div>
    );
  }

  if (error || !company) {
    return (
      <div className="min-h-screen w-full bg-background text-foreground">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <button
            onClick={onBack}
            className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
          <div className="p-6 rounded-lg bg-destructive/10 text-destructive flex items-center gap-3">
            <Frown size={24} />
            {error || "Entidade não encontrada"}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-6xl mx-auto px-4 py-6">
        <button
          onClick={onBack}
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar ao diretório
        </button>

        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 mb-6">
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-xl bg-primary/10 text-primary">
              <Building2 size={32} />
            </div>
            <div>
              <h1 className="text-2xl font-bold">{company.name}</h1>
              {company.nif && <p className="text-sm text-muted-foreground mt-1">NIF: {company.nif}</p>}
              {company.normalized_name && company.normalized_name !== company.name && (
                <p className="text-xs text-muted-foreground mt-0.5">{company.normalized_name}</p>
              )}
            </div>
          </div>
          {onSwitchDashboard && (
            <button
              onClick={onSwitchDashboard}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border hover:bg-accent transition text-sm"
            >
              <TrendingUp size={18} />
              Dashboard
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              <FileText size={16} />
              Total de contratos
            </p>
            <p className="text-2xl font-bold mt-1">{company.contracts_total ?? 0}</p>
          </div>
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              <Euro size={16} />
              Valor total
            </p>
            <p className="text-2xl font-bold mt-1">{formatPrice(company.total_value)}</p>
          </div>
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              <Calendar size={16} />
              Período
            </p>
            <p className="text-2xl font-bold mt-1">
              {firstYear ?? "—"} — {lastYear ?? "—"}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
          {company.adjudicante && company.adjudicante.contracts_count > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                Como Adjudicante
              </h2>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-sm text-muted-foreground">Contratos</p>
                  <p className="text-xl font-semibold">{company.adjudicante.contracts_count}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Valor total</p>
                  <p className="text-xl font-semibold">{formatPrice(company.adjudicante.total_value)}</p>
                </div>
              </div>
            </div>
          )}
          {company.adjudicatario && company.adjudicatario.contracts_count > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                Como Adjudicatário
              </h2>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-sm text-muted-foreground">Contratos</p>
                  <p className="text-xl font-semibold">{company.adjudicatario.contracts_count}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Valor total</p>
                  <p className="text-xl font-semibold">{formatPrice(company.adjudicatario.total_value)}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {(company.top_adjudicantes?.length > 0 || company.top_adjudicatarios?.length > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            {company.top_adjudicantes?.length > 0 && (
              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-blue-500" />
                  Principais Adjudicantes
                </h2>
                <div className="space-y-2">
                  {company.top_adjudicantes.slice(0, 10).map((e, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="truncate max-w-[75%]" title={e.nome || e.nif}>{e.nome || e.nif || "—"}</span>
                      {e.nif && <span className="text-xs text-muted-foreground whitespace-nowrap">NIF: {e.nif}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {company.top_adjudicatarios?.length > 0 && (
              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Principais Adjudicatários
                </h2>
                <div className="space-y-2">
                  {company.top_adjudicatarios.slice(0, 10).map((e, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="truncate max-w-[75%]" title={e.nome || e.nif}>{e.nome || e.nif || "—"}</span>
                      {e.nif && <span className="text-xs text-muted-foreground whitespace-nowrap">NIF: {e.nif}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {yearly.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-lg font-semibold mb-3">Por ano</h2>
              <div className="space-y-2">
                {yearly.map((row, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="text-sm">{row.key}</span>
                    <div className="text-right">
                      <p className="text-sm font-medium">{formatPrice(row.total_value)}</p>
                      <p className="text-xs text-muted-foreground">{row.count} contratos</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {cpvBreakdown.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-lg font-semibold mb-3">Por categoria (CPV)</h2>
              <div className="space-y-2">
                {cpvBreakdown.slice(0, 8).map((row, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="text-sm truncate max-w-[60%]" title={row.description || row.key}>{row.description || row.key}</span>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-medium">{formatPrice(row.total_value)}</p>
                      <p className="text-xs text-muted-foreground">{row.count} contratos</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {relatedEntities.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <User size={18} />
                Entidades relacionadas
              </h2>
              <div className="space-y-2 max-h-80 overflow-auto">
                {relatedEntities.slice(0, 20).map((entity, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span className="truncate max-w-[70%]" title={entity.description || entity.key}>{entity.description || entity.key}</span>
                    <span className="text-muted-foreground whitespace-nowrap">
                      {entity.count} contratos
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="bg-card border border-border rounded-xl p-5">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <FileText size={20} />
            Contratos recentes
          </h2>
          {allContracts.length === 0 ? (
            <p className="text-muted-foreground">Sem contratos registados para esta entidade.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-2 pr-4">Objeto</th>
                    <th className="py-2 pr-4">Adjudicante(s)</th>
                    <th className="py-2 pr-4">Adjudicatário(s)</th>
                    <th className="py-2 pr-4">Data</th>
                    <th className="py-2 pr-4">Valor</th>
                    <th className="py-2">/</th>
                  </tr>
                </thead>
                <tbody>
                  {allContracts.map((c, idx) => (
                    <tr key={c.idcontrato || c.doc_id || idx} className="border-b border-border/50 hover:bg-accent/30">
                      <td className="py-3 pr-4 max-w-xs truncate" title={c.objectoContrato || c.descContrato || ""}>
                        {c.objectoContrato || c.descContrato || "—"}
                      </td>
                      <td className="py-3 pr-4 max-w-xs truncate" title={partyText(c.adjudicantes)}>
                        {partyText(c.adjudicantes)}
                      </td>
                      <td className="py-3 pr-4 max-w-xs truncate" title={partyText(c.adjudicatarios)}>
                        {partyText(c.adjudicatarios)}
                      </td>
                      <td className="py-3 pr-4 whitespace-nowrap">{formatDate(c.dataPublicacao || c.dataCelebracaoContrato)}</td>
                      <td className="py-3 pr-4 font-medium">{formatPrice(contractValue(c))}</td>
                      <td className="py-3">
                        {onViewContract && c.idcontrato && (
                          <button
                            onClick={() => onViewContract(c.idcontrato!)}
                            className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground"
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

export default CompanyDetailPage;
