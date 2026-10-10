import { useCallback, useEffect, useState, useMemo } from "react";
import {
  ArrowLeft,
  Loader2,
  Frown,
  ChevronDown,
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
  Landmark,
  Tag,
  Globe,
  Sparkles,
  Download,
  AlertCircle,
  Info,
} from "lucide-react";
import {
  getCompanyDetail,
  getCompanyContracts,
  getCompanyAnalytics,
  getCompanySocietarioPublicacoes,
  enrichEntity,
  downloadEntityReport,
  downloadEntityProcessosReport,
  downloadEntityDossie,
} from "../api";
import { SeeAllContractsButton } from "./EntityContractsWindow";
import EmpresaLogo from "../components/benchmark/EmpresaLogo";
import { siteDe, usePerfisEmpresas } from "../components/benchmark/usePerfisEmpresas";
import { EntityEnrichmentCard } from "./EmpresasIQPage";
import { obterDadosEmpresa } from "../societarioRecolhaApi";
import { useWindowMode } from "../layout";
import type { CompanyDetail, CompanyAnalyticsResponse, CompanySocietarioResponse, ContractItem, ContractParty, ContractAnalyticsRow } from "../types";

/** Contratos por página na ficha (o «carregar mais» pede a página seguinte). */
const PAGINA_CONTRATOS = 20;

/** Papel da entidade no contrato: filtro da lista da ficha. */
type PapelContrato = "all" | "adjudicante" | "adjudicatario";

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

/** Contagens com separador de milhares («7 238»). */
function formatCount(n?: number | null) {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("pt-PT");
}

/**
 * Valores grandes em forma curta («1,8 mil M €»): há totais de milhares de
 * milhões de euros e o número por extenso estoura os cartões e as células.
 * O valor exato fica no `title` (e por baixo, quando abreviado).
 */
function formatCompactPrice(n?: number | null) {
  if (n === undefined || n === null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil M €`;
  if (abs >= 1e6) return `${(n / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M €`;
  if (abs >= 1e3) return `${(n / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil €`;
  return formatPrice(n);
}

/** True quando vale a pena mostrar o valor exato por baixo do abreviado. */
function abreviado(n?: number | null) {
  return typeof n === "number" && Number.isFinite(n) && Math.abs(n) >= 1_000_000;
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
  /**
   * Contratos da entidade: a ficha abre com os 20 mais recentes e cresce a pedido
   * (`PAGINA_CONTRATOS` de cada vez) até ao total — ver todos não obriga a abrir
   * outra janela, que no modo página (telemóvel) nem sequer existe.
   */
  const [contratos, setContratos] = useState<ContractItem[]>([]);
  const [contratosTotal, setContratosTotal] = useState(0);
  const [contratosRole, setContratosRole] = useState<PapelContrato>("all");
  const [aCarregarContratos, setACarregarContratos] = useState(false);
  const [erroContratos, setErroContratos] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<CompanyAnalyticsResponse | null>(null);
  /** Publicações do Ministério da Justiça já indexadas (só se existirem no Elastic). */
  const [societario, setSocietario] = useState<CompanySocietarioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Ações da ficha: enriquecer (web + IA), gerar relatórios, obter societário. */
  const [aEnriquecer, setAEnriquecer] = useState(false);
  const [aGerar, setAGerar] = useState<null | "relatorio" | "processos" | "dossie">(null);
  const [aObterSocietario, setAObterSocietario] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [erroAcao, setErroAcao] = useState<string | null>(null);

  /**
   * Marca da empresa (site e logótipo), do módulo `/empresas/perfil`: a cache do
   * servidor responde logo; se ainda não houver perfil, procura em segundo plano.
   */
  const {
    perfis,
    aResolver: marcaAResolver,
    repetir: repetirMarca,
  } = usePerfisEmpresas(useMemo(() => [{ nif, nome: company?.name }], [nif, company?.name]), {
    ativo: Boolean(nif),
  });
  const siteEmpresa = siteDe(perfis, { nif, nome: company?.name }) ?? company?.perfil?.site ?? null;
  const perfilEmpresa = perfis[nif] ?? company?.perfil ?? undefined;
  /** O gestor de janelas só existe no modo janelas: no modo página a lista é inline. */
  const { windowMode } = useWindowMode();

  /**
   * Lê uma página de contratos do servidor. `de > 0` acrescenta à lista em vez de
   * substituir; os repetidos (a paginação do Elasticsearch pode repetir empates
   * de ordenação) são descartados.
   */
  const carregarContratos = useCallback(
    async (role: PapelContrato, de: number, tamanho = PAGINA_CONTRATOS) => {
      setACarregarContratos(true);
      setErroContratos(null);
      try {
        const resposta = await getCompanyContracts(nif, role, de, Math.min(100, tamanho));
        setContratosTotal(resposta.total ?? 0);
        setContratos((anterior) => {
          const base = de > 0 ? anterior : [];
          const vistos = new Set(base.map((item) => item.idcontrato || item.doc_id).filter(Boolean));
          const novos = (resposta.items ?? []).filter((item) => {
            const chave = item.idcontrato || item.doc_id;
            if (!chave) return true;
            if (vistos.has(chave)) return false;
            vistos.add(chave);
            return true;
          });
          return [...base, ...novos];
        });
      } catch (err) {
        setErroContratos(err instanceof Error ? err.message : "Erro ao carregar os contratos");
      } finally {
        setACarregarContratos(false);
      }
    },
    [nif],
  );

  /** Recarrega a ficha (e o societário) depois de uma ação. */
  const recarregar = async () => {
    const [d, a] = await Promise.all([getCompanyDetail(nif), getCompanyAnalytics(nif)]);
    setCompany(d);
    setAnalytics(a);
    setContratosRole("all");
    await carregarContratos("all", 0);
    try {
      setSocietario(await getCompanySocietarioPublicacoes(nif, 0, 20));
    } catch {
      setSocietario(null);
    }
    repetirMarca();
  };

  /** Pesquisa web + IA: descrição, contactos, morada, dimensão, CAE, site e logótipo. */
  const handleEnriquecer = async () => {
    setAEnriquecer(true);
    setErroAcao(null);
    setAviso("A enriquecer com pesquisa web e IA — site, contactos, morada e atividade…");
    try {
      const resultado = await enrichEntity(nif, { use_web: true, use_scraper: true, save_relations: true });
      const campos = Object.keys(resultado.fields_added ?? {}).length;
      setAviso(
        resultado.message ||
          `Enriquecimento concluído — ${campos} campos, ${resultado.source_count ?? 0} fontes, ${resultado.relation_count ?? 0} relações.`,
      );
      await recarregar();
    } catch (err) {
      setErroAcao(err instanceof Error ? err.message : "Erro ao enriquecer a ficha");
      setAviso(null);
    } finally {
      setAEnriquecer(false);
    }
  };

  /** Descarrega um dos relatórios da entidade (dossiê, ficha ou processos). */
  const descarregar = async (tipo: "relatorio" | "processos" | "dossie") => {
    setAGerar(tipo);
    setErroAcao(null);
    try {
      const blob =
        tipo === "dossie"
          ? await downloadEntityDossie(nif)
          : tipo === "processos"
            ? await downloadEntityProcessosReport(nif)
            : await downloadEntityReport(nif);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${tipo}_${nif}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setAviso(`PDF gerado e descarregado (${tipo === "dossie" ? "dossiê da empresa" : tipo === "processos" ? "processos e risco" : "ficha"}).`);
    } catch (err) {
      setErroAcao(err instanceof Error ? err.message : "Erro ao gerar o PDF");
    } finally {
      setAGerar(null);
    }
  };

  /**
   * Recolhe os dados societários (publicações do Ministério da Justiça) quando a
   * ficha ainda não os tem. A recolha corre no servidor; a lista aparece quando
   * estiver indexada, por isso recarrega-se algumas vezes em vez de esperar.
   */
  const obterSocietario = async () => {
    setAObterSocietario(true);
    setErroAcao(null);
    setAviso("A recolher publicações societárias no portal do Ministério da Justiça…");
    try {
      await obterDadosEmpresa(nif);
      for (let tentativa = 0; tentativa < 6; tentativa += 1) {
        await new Promise((resolve) => setTimeout(resolve, 4000));
        const resposta = await getCompanySocietarioPublicacoes(nif, 0, 20).catch(() => null);
        if (resposta && resposta.total > 0) {
          setSocietario(resposta);
          setAviso(`${resposta.total} publicações societárias recolhidas.`);
          return;
        }
      }
      setAviso("Recolha iniciada. As publicações aparecem aqui assim que ficarem indexadas (pode levar alguns minutos).");
    } catch (err) {
      setErroAcao(err instanceof Error ? err.message : "Erro ao obter os dados societários");
      setAviso(null);
    } finally {
      setAObterSocietario(false);
    }
  };

  useEffect(() => {
    if (!nif) {
      setError("NIF em falta");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getCompanyDetail(nif), getCompanyAnalytics(nif)])
      .then(([d, a]) => {
        if (cancelled) return;
        setCompany(d);
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

  /* Lista de contratos: primeira página e recarga sempre que muda o papel filtrado. */
  useEffect(() => {
    if (!nif) return;
    setContratos([]);
    setContratosTotal(0);
    void carregarContratos(contratosRole, 0);
  }, [nif, contratosRole, carregarContratos]);

  const relatedEntities = analytics?.top_partners ?? [];
  const cpvBreakdown = analytics?.by_cpv ?? [];
  const yearly = analytics?.by_year ?? [];

  /** Contratos por papel (para o filtro) e quantos ainda faltam carregar. */
  const contratosAdjudicante = company?.adjudicante?.contracts_count ?? 0;
  const contratosAdjudicatario = company?.adjudicatario?.contracts_count ?? 0;
  const temAmbosPapeis = contratosAdjudicante > 0 && contratosAdjudicatario > 0;
  const faltamContratos = Math.max(0, contratosTotal - contratos.length);

  // O societário vive noutro índice e é opcional: falha ou ausência não travam a ficha.
  useEffect(() => {
    if (!nif) return;
    let cancelled = false;
    setSocietario(null);
    getCompanySocietarioPublicacoes(nif, 0, 20)
      .then((res) => {
        if (!cancelled) setSocietario(res);
      })
      .catch(() => {
        if (!cancelled) setSocietario(null);
      });
    return () => {
      cancelled = true;
    };
  }, [nif]);

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

  /** Publicações do MJ, da mais recente para a mais antiga. */
  const publicacoes = useMemo(
    () =>
      [...(societario?.items ?? [])].sort((a, b) =>
        String(b.data_publicacao ?? "").localeCompare(String(a.data_publicacao ?? "")),
      ),
    [societario],
  );

  /**
   * Identificação societária da publicação mais recente que a traz preenchida.
   * Guarda-se também a data: um endereço de 2017 não é a sede de hoje, e o
   * cartão diz de quando é.
   */
  const societarioDestaque = publicacoes.find((p) => p.natureza_juridica || p.sede || p.matricula_nipc);

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

        {/* Ações: enriquecer (web + IA) e relatórios da empresa */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <button
            onClick={handleEnriquecer}
            disabled={aEnriquecer}
            title="Pesquisa web + IA: descrição, contactos, morada, dimensão, CAE, site e logótipo"
            className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-teal-300 hover:text-teal-200 transition disabled:opacity-60"
          >
            {aEnriquecer ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            Enriquecer ficha
          </button>
          <button
            onClick={() => descarregar("dossie")}
            disabled={aGerar !== null}
            title="Dossiê completo: identidade digital, ficha (web + IA), risco com CIRE, processos, atos societários e contratos"
            className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-amber-300 hover:text-amber-200 transition disabled:opacity-60"
          >
            {aGerar === "dossie" ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
            Dossiê da empresa
          </button>
          <button
            onClick={() => descarregar("processos")}
            disabled={aGerar !== null}
            title="Relatório de processos e risco: insolvências/PER (CIRE), processos judiciais, situação fiscal e atos societários"
            className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-sky-300 hover:text-sky-200 transition disabled:opacity-60"
          >
            {aGerar === "processos" ? <Loader2 size={16} className="animate-spin" /> : <AlertCircle size={16} />}
            Processos e risco
          </button>
          <button
            onClick={() => descarregar("relatorio")}
            disabled={aGerar !== null}
            title="Relatório PDF da ficha (enriquecimento, CPV e relações)"
            className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition disabled:opacity-60"
          >
            {aGerar === "relatorio" ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
            Relatório PDF
          </button>
        </div>

        {aviso && (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-teal-500/30 bg-teal-500/10 px-4 py-3 text-sm text-teal-200">
            <Info size={16} />
            {aviso}
          </div>
        )}
        {erroAcao && (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            <AlertCircle size={16} />
            {erroAcao}
          </div>
        )}

        {/* Entity hero */}
        <div className="glass-card gradient-border rounded-3xl p-6 md:p-8 mb-8 fade-in">
          <div className="flex flex-col md:flex-row md:items-center gap-5">
            <EmpresaLogo
              nome={company.name}
              nif={nif}
              logoUrl={perfilEmpresa?.logo_url}
              size={88}
              titulo={siteEmpresa ? `${company.name} · ${siteEmpresa}` : company.name}
            />
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl md:text-4xl font-bold leading-tight mb-1">{company.name}</h1>
              <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                {company.nif && <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10">NIF {company.nif}</span>}
                {company.normalized_name && company.normalized_name !== company.name && (
                  <span>{company.normalized_name}</span>
                )}
                {siteEmpresa ? (
                  <a
                    href={siteEmpresa}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200 transition"
                    title={`Site oficial: ${siteEmpresa}`}
                  >
                    <Globe size={13} />
                    {siteEmpresa.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                  </a>
                ) : (
                  <span className="inline-flex items-center gap-1">
                    <Globe size={13} />
                    {marcaAResolver > 0 ? "à procura do site…" : "sem site identificado — use «Enriquecer ficha»"}
                  </span>
                )}
                {perfilEmpresa?.site && perfilEmpresa?.confianca !== undefined ? (
                  <span className="text-[11px] opacity-70" title={perfilEmpresa.motivo ?? undefined}>
                    confiança {Math.round((perfilEmpresa.confianca || 0) * 100)}%
                    {perfilEmpresa.origem ? ` · ${perfilEmpresa.origem}` : ""}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="glass-card gradient-border rounded-2xl p-5 glow-teal min-w-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <FileText size={16} className="text-teal-400" />
              Total de contratos
            </div>
            <p className="text-3xl font-bold stat-value text-glow-teal tabular-nums" title={String(company.contracts_total ?? 0)}>
              {formatCount(company.contracts_total)}
            </p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-amber min-w-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Euro size={16} className="text-amber-400" />
              Valor total
            </div>
            <p
              className="text-2xl md:text-3xl font-bold stat-value text-glow-amber tabular-nums leading-tight break-words"
              title={formatPrice(company.total_value)}
            >
              {formatCompactPrice(company.total_value)}
            </p>
            {abreviado(company.total_value) && (
              <p className="mt-1 text-[11px] text-muted-foreground tabular-nums break-all">
                {formatPrice(company.total_value)}
              </p>
            )}
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-blue min-w-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Calendar size={16} className="text-blue-400" />
              Período
            </div>
            <p className="text-3xl font-bold stat-value text-glow-blue tabular-nums">
              {firstYear ?? "—"} — {lastYear ?? "—"}
            </p>
          </div>
          <div className="glass-card gradient-border rounded-2xl p-5 glow-rose min-w-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Activity size={16} className="text-rose-400" />
              Média / contrato
            </div>
            <p
              className="text-2xl md:text-3xl font-bold stat-value text-glow-rose tabular-nums leading-tight break-words"
              title={formatPrice(analytics?.avg_value)}
            >
              {formatCompactPrice(analytics?.avg_value)}
            </p>
            {abreviado(analytics?.avg_value) && (
              <p className="mt-1 text-[11px] text-muted-foreground tabular-nums break-all">
                {formatPrice(analytics?.avg_value)}
              </p>
            )}
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
                <div className="glass-card rounded-xl p-4 min-w-0">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Contratos</p>
                  <p className="text-2xl font-bold stat-value mt-1 tabular-nums">{formatCount(company.adjudicante.contracts_count)}</p>
                </div>
                <div className="glass-card rounded-xl p-4 min-w-0">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor total</p>
                  <p
                    className="text-xl font-bold stat-value text-glow-amber mt-1 tabular-nums leading-tight break-words"
                    title={formatPrice(company.adjudicante.total_value)}
                  >
                    {formatCompactPrice(company.adjudicante.total_value)}
                  </p>
                  {abreviado(company.adjudicante.total_value) && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground tabular-nums break-all">
                      {formatPrice(company.adjudicante.total_value)}
                    </p>
                  )}
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
                <div className="glass-card rounded-xl p-4 min-w-0">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Contratos</p>
                  <p className="text-2xl font-bold stat-value mt-1 tabular-nums">{formatCount(company.adjudicatario.contracts_count)}</p>
                </div>
                <div className="glass-card rounded-xl p-4 min-w-0">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor total</p>
                  <p
                    className="text-xl font-bold stat-value text-glow-amber mt-1 tabular-nums leading-tight break-words"
                    title={formatPrice(company.adjudicatario.total_value)}
                  >
                    {formatCompactPrice(company.adjudicatario.total_value)}
                  </p>
                  {abreviado(company.adjudicatario.total_value) && (
                    <p className="mt-1 text-[10.5px] text-muted-foreground tabular-nums break-all">
                      {formatPrice(company.adjudicatario.total_value)}
                    </p>
                  )}
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
                        <span className="font-medium tabular-nums" title={formatPrice(row.total_value)}>
                          {formatCompactPrice(row.total_value)}
                        </span>
                        <span className="text-xs text-muted-foreground ml-2">{formatCount(row.count)}</span>
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
                        <span className="font-medium tabular-nums" title={formatPrice(row.total_value)}>
                          {formatCompactPrice(row.total_value)}
                        </span>
                        <span className="text-xs text-muted-foreground ml-2">{formatCount(row.count)}</span>
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
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{formatCount(entity.count)} contratos</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Contracts table */}
        {/* Ficha recolhida por web + IA: descrição, contactos, morada, dimensão, atividade */}
        <div className="mb-8">
          <EntityEnrichmentCard data={company.enrichment_web} lastUpdated={company.enrichment_last_updated} />
          {!company.enrichment_web ? (
            <div className="glass-card gradient-border rounded-2xl p-5 text-sm text-muted-foreground">
              Ainda não há ficha recolhida por IA para esta empresa. Use <strong className="font-medium text-teal-300">Enriquecer ficha</strong> para
              procurar descrição, contactos, morada, dimensão, CAE, site e logótipo.
            </div>
          ) : null}
        </div>

        {/* Dados societários (publicações do Ministério da Justiça) */}
        {!societario || societario.total === 0 ? (
          <div className="glass-card gradient-border rounded-2xl p-5 md:p-6 mb-8 flex flex-wrap items-center gap-3">
            <div className="p-2 rounded-xl bg-violet-500/15 border border-violet-400/20">
              <Landmark size={20} className="text-violet-300" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">Dados societários</h2>
              <p className="text-xs text-muted-foreground">
                Sem publicações de atos societários (Ministério da Justiça) para esta empresa. A recolha é feita no
                portal público e fica guardada na ficha.
              </p>
            </div>
            <button
              onClick={obterSocietario}
              disabled={aObterSocietario}
              className="flex items-center gap-2 px-3 py-1.5 rounded-full glass-card text-sm text-violet-300 hover:text-violet-200 transition disabled:opacity-60"
            >
              {aObterSocietario ? <Loader2 size={16} className="animate-spin" /> : <Landmark size={16} />}
              {aObterSocietario ? "A recolher…" : "Obter dados societários"}
            </button>
          </div>
        ) : null}
        {societario && societario.total > 0 && (
          <div className="glass-card gradient-border rounded-2xl p-5 md:p-6 mb-8">
            <div className="flex flex-wrap items-center gap-3 mb-5">
              <div className="p-2 rounded-xl bg-violet-500/15 border border-violet-400/20">
                <Landmark size={20} className="text-violet-300" />
              </div>
              <h2 className="text-xl font-semibold">Dados societários</h2>
              <span className="text-sm text-muted-foreground">
                {societario.total} publicações de atos societários (Ministério da Justiça)
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
              {[
                { label: "Natureza jurídica", value: societarioDestaque?.natureza_juridica },
                { label: "Sede", value: societarioDestaque?.sede },
                { label: "Matrícula / NIPC", value: societarioDestaque?.matricula_nipc },
              ]
                .filter((f) => f.value)
                .map((f) => (
                  <div key={f.label} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">{f.label}</p>
                    <p className="mt-1 text-sm">{f.value}</p>
                  </div>
                ))}
            </div>
            {societarioDestaque?.data_publicacao && (
              <p className="-mt-3 mb-4 text-xs text-muted-foreground">
                Identificação da publicação de {formatDate(societarioDestaque.data_publicacao)}
              </p>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left text-muted-foreground">
                    <th className="py-3 pr-4 font-medium">Data</th>
                    <th className="py-3 pr-4 font-medium">Ato</th>
                    <th className="py-3 pr-4 font-medium">Conservatória</th>
                    <th className="py-3 pr-4 font-medium">Tipo</th>
                    <th className="py-3 font-medium">Documento</th>
                  </tr>
                </thead>
                <tbody>
                  {publicacoes.slice(0, 10).map((pub) => (
                    <tr key={pub.pub_id} className="border-b border-white/5 hover:bg-white/[0.04] transition">
                      <td className="py-2.5 pr-4 whitespace-nowrap text-muted-foreground">{formatDate(pub.data_publicacao)}</td>
                      <td className="py-2.5 pr-4 max-w-md" title={pub.acto || ""}>
                        {pub.acto || "—"}
                      </td>
                      <td className="py-2.5 pr-4 text-muted-foreground">{pub.conservatoria || "—"}</td>
                      <td className="py-2.5 pr-4 text-muted-foreground">{pub.tipo_label || pub.tipo || "—"}</td>
                      <td className="py-2.5">
                        {pub.documento_url ? (
                          <a
                            href={pub.documento_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-teal-300 hover:underline"
                          >
                            <ExternalLink size={13} /> PDF
                          </a>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {societario.total > 10 && (
              <p className="mt-4 text-xs text-muted-foreground">
                A mostrar os 10 registos mais recentes de {societario.total}. A lista completa, a timeline por IA e as
                pessoas extraídas estão na ficha do EmpresasIQ (e no dossiê da empresa).
              </p>
            )}
          </div>
        )}

        <div className="glass-card gradient-border rounded-2xl p-5 md:p-6">
          <div className="flex flex-wrap items-center gap-3 mb-5">
            <div className="p-2 rounded-xl bg-primary/15 border border-primary/20">
              <FileText size={20} className="text-primary" />
            </div>
            <h2 className="text-xl font-semibold">Contratos recentes</h2>
            <span className="text-sm text-muted-foreground">
              {contratos.length.toLocaleString("pt-PT")} de {contratosTotal.toLocaleString("pt-PT")}
              {contratosTotal > 0 ? " visíveis" : ""}
            </span>
            {temAmbosPapeis && (
              <div className="flex items-center gap-0.5 rounded-xl border border-white/10 bg-white/[0.04] p-0.5 text-[11.5px]">
                {(
                  [
                    { valor: "all" as PapelContrato, texto: `Todos (${formatCount(company?.contracts_total)})` },
                    { valor: "adjudicatario" as PapelContrato, texto: `Adjudicatário (${formatCount(contratosAdjudicatario)})` },
                    { valor: "adjudicante" as PapelContrato, texto: `Adjudicante (${formatCount(contratosAdjudicante)})` },
                  ]
                ).map((papel) => (
                  <button
                    key={papel.valor}
                    type="button"
                    onClick={() => setContratosRole(papel.valor)}
                    className={`rounded-lg px-2 py-1 transition ${
                      contratosRole === papel.valor
                        ? "bg-white/[0.12] text-foreground"
                        : "text-muted-foreground hover:bg-white/[0.07]"
                    }`}
                  >
                    {papel.texto}
                  </button>
                ))}
              </div>
            )}
            <div className="ml-auto flex items-center gap-2">
              {faltamContratos > 0 && (
                <button
                  type="button"
                  onClick={() => carregarContratos(contratosRole, contratos.length)}
                  disabled={aCarregarContratos}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.1] disabled:opacity-40"
                  title="Carregar os 20 contratos seguintes"
                >
                  {aCarregarContratos ? <Loader2 size={12} className="animate-spin" /> : <ChevronDown size={12} />}
                  Mais {Math.min(PAGINA_CONTRATOS, faltamContratos)}
                </button>
              )}
              {windowMode && (
                <SeeAllContractsButton
                  nif={nif}
                  name={company.name}
                  total={contratosTotal || company.contracts_total}
                  compact
                />
              )}
            </div>
          </div>
          {erroContratos && (
            <p className="mb-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
              {erroContratos}
            </p>
          )}
          {contratos.length === 0 ? (
            <p className="text-muted-foreground">
              {aCarregarContratos
                ? "A carregar contratos…"
                : contratosRole === "all"
                  ? "Sem contratos registados para esta entidade."
                  : "Sem contratos para este papel."}
            </p>
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
                  {contratos.map((c, idx) => (
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
                      <td className="py-3 pr-4 font-medium text-glow-amber whitespace-nowrap tabular-nums" title={formatPrice(contractValue(c))}>
                        {formatCompactPrice(contractValue(c))}
                      </td>
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
          {contratos.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[12px] text-muted-foreground">
              <span>
                A mostrar {contratos.length.toLocaleString("pt-PT")} de {contratosTotal.toLocaleString("pt-PT")} contratos
                {contratosRole === "adjudicante"
                  ? " como adjudicante"
                  : contratosRole === "adjudicatario"
                    ? " como adjudicatário"
                    : ""}
                .
              </span>
              {faltamContratos > 0 && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => carregarContratos(contratosRole, contratos.length)}
                    disabled={aCarregarContratos}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 transition hover:bg-white/[0.1] disabled:opacity-40"
                  >
                    {aCarregarContratos ? <Loader2 size={12} className="animate-spin" /> : <ChevronDown size={12} />}
                    Carregar mais {Math.min(PAGINA_CONTRATOS, faltamContratos)}
                  </button>
                  {faltamContratos > PAGINA_CONTRATOS && (
                    <button
                      type="button"
                      onClick={() => carregarContratos(contratosRole, contratos.length, 100)}
                      disabled={aCarregarContratos}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 transition hover:bg-white/[0.1] disabled:opacity-40"
                      title="Carregar de 100 em 100"
                    >
                      Mais 100
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
