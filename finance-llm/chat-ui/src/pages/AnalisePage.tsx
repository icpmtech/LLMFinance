/**
 * Área de análise — o painel de trabalho dos membros com perfil «Analista de dados».
 *
 * Reproduz a leitura que o analista faz todos os dias: os números de topo da
 * contratação pública portuguesa, a série anual (contratos ou valor), quem mais
 * contrata e os atalhos para as ferramentas de investigação.
 *
 * Os valores vêm de `/contracts/analytics` e `/contracts/years` — a mesma fonte
 * do dashboard de contratos. Não há indicadores inventados: quando a API não
 * responde, a página di-lo e mostra os campos vazios.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  Building2,
  Compass,
  Euro,
  FileText,
  Gauge,
  Landmark,
  Loader2,
  RefreshCw,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import { getContractAnalytics, getContractYears } from "../api";
import { useAuth } from "../auth";
import type { ContractAnalyticsFilters, ContractAnalyticsResponse } from "../types";

interface AnalisePageProps {
  /** Abre outra aplicação da plataforma (contratos, empresas, Hermes…). */
  onNavigate: (view: string) => void;
}

type Metrica = "contratos" | "valor";

const FILTROS_BASE: ContractAnalyticsFilters = { top_entities: 10, top_cpv: 8 };

function formatNumber(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT");
}

function formatEuro(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

/** Valor em milhões/mil milhões, como no resto da plataforma («198,8 mil M€»). */
function formatCompactEuro(n?: number | null) {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1_000_000_000) {
    return `${(n / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil M€`;
  }
  if (Math.abs(n) >= 1_000_000) {
    return `${(n / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  }
  return formatEuro(n);
}

function Kpi({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  color: string;
}) {
  return (
    <div className="glass-card gradient-border rounded-2xl p-5">
      <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Icon size={18} className={color} />
        {label}
      </div>
      <p className="stat-value text-2xl font-bold md:text-3xl">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

export function AnalisePage({ onNavigate }: AnalisePageProps) {
  const { user } = useAuth();
  const [anos, setAnos] = useState<number[]>([]);
  const [ano, setAno] = useState<number | "">("");
  const [universo, setUniverso] = useState<ContractAnalyticsResponse | null>(null);
  const [recorte, setRecorte] = useState<ContractAnalyticsResponse | null>(null);
  const [metrica, setMetrica] = useState<Metrica>("contratos");
  const [loading, setLoading] = useState(true);
  const [recarregar, setRecarregar] = useState(0);
  const [erro, setErro] = useState<string | null>(null);

  const carregarUniverso = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const [lista, dados] = await Promise.all([
        getContractYears().catch(() => null),
        getContractAnalytics(FILTROS_BASE),
      ]);
      if (lista) setAnos(lista.available ?? []);
      setUniverso(dados);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não foi possível carregar os indicadores.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregarUniverso();
  }, [carregarUniverso, recarregar]);

  useEffect(() => {
    if (ano === "") {
      setRecorte(null);
      return;
    }
    let cancelado = false;
    getContractAnalytics({ ...FILTROS_BASE, year: ano })
      .then((dados) => {
        if (!cancelado) setRecorte(dados);
      })
      .catch(() => {
        if (!cancelado) setRecorte(null);
      });
    return () => {
      cancelado = true;
    };
  }, [ano, recarregar]);

  const atual = recorte ?? universo;

  /** Últimos anos com dados — a série completa (2012 a 2026) não cabe legível. */
  const serie = useMemo(() => {
    const linhas = [...(universo?.by_year ?? [])]
      .filter((linha) => Number.isFinite(Number(linha.key)))
      .sort((a, b) => Number(a.key) - Number(b.key));
    return linhas.slice(-8);
  }, [universo]);

  const periodo = useMemo(() => {
    const disponiveis = anos.length ? anos : serie.map((linha) => Number(linha.key));
    if (disponiveis.length === 0) return "";
    return `${Math.min(...disponiveis)} a ${Math.max(...disponiveis)}`;
  }, [anos, serie]);

  const ranking = (atual?.top_adjudicantes ?? atual?.top_entities ?? []).slice(0, 4);
  const destaque = ranking[0] ?? null;
  const maiorContagem = destaque?.count || 1;
  const perfil = user?.title?.trim() || "Analista";

  const tooltipFormatter: RechartsFormatter = (value) => [
    metrica === "valor" ? formatEuro(Number(value)) : formatNumber(Number(value)),
    metrica === "valor" ? "Valor contratado" : "Contratos",
  ];

  const atalhos = [
    {
      id: "contracts-dashboard",
      label: "Análise de contratos",
      hint: "Filtros, CPV, procedimentos e exportações",
      icon: BarChart3,
      color: "text-teal-300",
    },
    {
      id: "empresas-iq",
      label: "Empresas e pessoas",
      hint: "Ficha completa, sócios e relações",
      icon: Building2,
      color: "text-sky-300",
    },
    {
      id: "search360",
      label: "Pesquisa 360",
      hint: "Dossiês e investigação cruzada",
      icon: Compass,
      color: "text-violet-300",
    },
    {
      id: "hermes",
      label: "Hermes",
      hint: "Perguntar com evidências citadas",
      icon: Sparkles,
      color: "text-amber-300",
    },
  ];

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-7xl px-4 py-8 @2xl:px-6">
        <header className="mb-8 flex flex-col gap-4 @4xl:flex-row @4xl:items-end @4xl:justify-between">
          <div>
            <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-teal-300/80">
              <Gauge size={14} /> Área de análise
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Contratos públicos — Portugal</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {periodo ? `${periodo} · ` : ""}Portal BASE, PLACSP e DECP
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-teal-400/25 bg-teal-400/10 px-3 py-1.5 text-xs text-teal-200">
              <span className="h-1.5 w-1.5 rounded-full bg-teal-300" />
              Sessão ativa · perfil {perfil}
            </span>
            <select
              value={ano}
              onChange={(event) => setAno(event.target.value === "" ? "" : Number(event.target.value))}
              className="rounded-xl border border-border bg-background/60 px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              aria-label="Ano em análise"
            >
              <option value="">Todos os anos</option>
              {anos.map((valor) => (
                <option key={valor} value={valor}>
                  {valor}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setRecarregar((valor) => valor + 1)}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl glass-card px-3 py-2 text-sm transition hover:bg-white/5 disabled:opacity-50"
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              Atualizar
            </button>
            <button
              type="button"
              onClick={() => onNavigate("contracts-dashboard")}
              className="flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/10 px-3 py-2 text-sm text-primary transition hover:bg-primary/15"
            >
              <FileText size={16} /> Abrir dashboard
            </button>
          </div>
        </header>

        {erro ? (
          <div className="mb-6 rounded-2xl border border-rose-400/25 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {erro}
          </div>
        ) : null}

        <div className="mb-6 grid grid-cols-1 gap-4 @lg:grid-cols-2 @5xl:grid-cols-4 fade-in">
          <Kpi
            icon={FileText}
            label="Contratos públicos"
            value={formatNumber(atual?.total_contracts)}
            sub={ano === "" ? "Portal BASE e parceiros ibéricos" : `Contratos com data em ${ano}`}
            color="text-teal-400"
          />
          <Kpi
            icon={Euro}
            label="Valor contratado"
            value={formatCompactEuro(atual?.total_value)}
            sub={`Média de ${formatCompactEuro(atual?.avg_value)} por contrato`}
            color="text-amber-400"
          />
          <Kpi
            icon={Landmark}
            label="Adjudicantes"
            value={formatNumber(atual?.distinct_adjudicantes)}
            sub="Entidades que compram"
            color="text-sky-400"
          />
          <Kpi
            icon={Users}
            label="Adjudicatários"
            value={formatNumber(atual?.distinct_adjudicatarios)}
            sub="Empresas que fornecem"
            color="text-violet-400"
          />
        </div>

        <div className="mb-6 grid grid-cols-1 gap-6 @5xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
          <section className="glass-card gradient-border rounded-2xl p-5">
            <div className="mb-5 flex flex-wrap items-center gap-3">
              <div className="rounded-xl border border-teal-400/20 bg-teal-500/15 p-2">
                <BarChart3 size={20} className="text-teal-300" />
              </div>
              <div className="min-w-0">
                <h2 className="text-lg font-semibold">
                  {metrica === "valor" ? "Valor por ano" : "Contratos por ano"}
                </h2>
                <p className="text-[11px] text-muted-foreground">
                  {serie.length ? `${serie[0].key} a ${serie[serie.length - 1].key}` : "Sem série disponível"}
                </p>
              </div>
              <div className="ml-auto flex rounded-xl border border-border bg-background/50 p-0.5 text-xs">
                {(["contratos", "valor"] as Metrica[]).map((valor) => (
                  <button
                    key={valor}
                    type="button"
                    onClick={() => setMetrica(valor)}
                    className={[
                      "rounded-lg px-3 py-1.5 capitalize transition",
                      metrica === valor ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                    aria-pressed={metrica === valor}
                  >
                    {valor}
                  </button>
                ))}
              </div>
            </div>

            {loading && serie.length === 0 ? (
              <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                <Loader2 size={18} className="mr-2 animate-spin" /> A carregar a série…
              </div>
            ) : serie.length === 0 ? (
              <p className="py-16 text-center text-sm text-muted-foreground">Sem dados para desenhar a série.</p>
            ) : (
              <div className="h-64 overflow-hidden @3xl:h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={serie} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" vertical={false} />
                    <XAxis dataKey="key" stroke="#9aa0aa" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis
                      stroke="#9aa0aa"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(valor: number) =>
                        metrica === "valor" ? formatCompactEuro(valor) : Intl.NumberFormat("pt-PT", { notation: "compact" }).format(valor)
                      }
                      width={72}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(255,255,255,0.04)" }}
                      contentStyle={{ backgroundColor: "#16181d", borderColor: "#2e323b", color: "#e8e9ec" }}
                      formatter={tooltipFormatter}
                    />
                    <Bar
                      dataKey={metrica === "valor" ? "total_value" : "count"}
                      fill={metrica === "valor" ? "#f59e0b" : "#10a37f"}
                      radius={[6, 6, 0, 0]}
                      maxBarSize={48}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <aside className="glass-card gradient-border rounded-2xl p-5">
            <div className="mb-4 flex items-center gap-2">
              <div className="rounded-xl border border-amber-400/20 bg-amber-500/15 p-2">
                <Sparkles size={18} className="text-amber-300" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Assistente</h2>
                <p className="text-[11px] text-muted-foreground">Leitura rápida do ranking de compradores</p>
              </div>
            </div>

            <div className="rounded-xl bg-muted/30 px-3 py-2 text-sm text-foreground/90">
              {ano === "" ? "Quem mais contratou?" : `Quem mais contratou em ${ano}?`}
            </div>

            {destaque ? (
              <>
                <p className="mt-3 text-sm leading-relaxed">
                  A <strong className="font-semibold">{destaque.description || destaque.key}</strong> lidera, com{" "}
                  <strong className="font-semibold">{formatNumber(destaque.count)}</strong>{" "}
                  {destaque.count === 1 ? "contrato" : "contratos"}
                  {ano === "" ? " no período disponível" : ` em ${ano}`}.
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatCompactEuro(destaque.total_value)} contratados · {formatEuro(atual?.avg_value)} de valor médio global
                </p>
              </>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                {loading ? "A calcular o ranking…" : "Sem ranking de adjudicantes para este recorte."}
              </p>
            )}

            <ul className="mt-3 space-y-1.5">
              {ranking.slice(1).map((linha) => (
                <li key={linha.key} className="flex items-center gap-2 text-[11px]">
                  <span className="min-w-0 flex-1 truncate text-muted-foreground" title={linha.description || linha.key}>
                    {linha.description || linha.key}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{formatNumber(linha.count)}</span>
                  <span className="h-1 w-16 overflow-hidden rounded-full bg-white/10">
                    <span
                      className="block h-full rounded-full bg-teal-400/70"
                      style={{ width: `${Math.max(6, (linha.count / maiorContagem) * 100)}%` }}
                    />
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
              <span className="rounded-full border border-teal-400/20 bg-teal-400/10 px-2.5 py-1 text-teal-200">
                [1] Portal BASE
              </span>
              <span className="rounded-full border border-indigo-400/20 bg-indigo-400/10 px-2.5 py-1 text-indigo-200">
                [2] IQ OS · agregação
              </span>
            </div>

            <button
              type="button"
              onClick={() => onNavigate("hermes")}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs transition hover:bg-white/10"
            >
              Investigar com o Hermes <ArrowUpRight size={14} />
            </button>
          </aside>
        </div>

        <section className="glass-card rounded-2xl p-5">
          <h2 className="mb-4 text-lg font-semibold">Continuar a análise</h2>
          <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2 @5xl:grid-cols-4">
            {atalhos.map((atalho) => {
              const Icon = atalho.icon;
              return (
                <button
                  key={atalho.id}
                  type="button"
                  onClick={() => onNavigate(atalho.id)}
                  className="group flex items-start gap-3 rounded-xl border border-white/8 bg-white/4 p-3 text-left transition hover:border-teal-300/30 hover:bg-white/8"
                >
                  <span className="rounded-lg border border-white/10 bg-white/5 p-2">
                    <Icon size={16} className={atalho.color} />
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1 text-sm font-medium">
                      {atalho.label}
                      <ArrowUpRight size={13} className="opacity-0 transition group-hover:opacity-100" />
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">{atalho.hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

export default AnalisePage;
