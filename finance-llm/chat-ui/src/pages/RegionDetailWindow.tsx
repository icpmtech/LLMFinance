/**
 * Ficha de uma região de contratos — janela `region-detail:<pais>:<code>`.
 *
 * Abre a partir do menu de contexto do mapa (`/contracts/map`, botão direito
 * sobre um distrito/província) e responde a «quem contrata, quem executa e por
 * quanto»: volume e valor, distribuição por ano, CPV, procedimento, tipo e
 * escalão de valor, as entidades que adjudicam, as empresas adjudicatárias e os
 * maiores contratos da região.
 *
 * O conteúdo é o mesmo em modo janelas e em modo página (quando o modo janelas
 * está desligado a vista `region-detail` ocupa a moldura da plataforma e recebe
 * `onClose` para voltar).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Building2, Euro, FileText, Landmark, Loader2, RefreshCw, TrendingUp } from "lucide-react";
import { getContractRegionDetail, type RegionDetailEntity, type RegionDetailResponse, type RegionDetailRow } from "../contractsMapApi";
import { getContractYears } from "../api";
import { getContratosEsStatus } from "../contratosEsApi";
import { LEVEL_LABELS, resolveIberiaRegion } from "../components/geo/iberia";

interface RegionDetailWindowProps {
  pais: "PT" | "ES";
  code: string;
  /** Ano do mapa (vazio = todos os anos). */
  ano?: number | null;
  /** Presente no modo página (botão «Voltar»). */
  onClose?: () => void;
}

const COUNTRY_LABELS: Record<"PT" | "ES", string> = { PT: "Portugal", ES: "Espanha" };
const COUNTRY_COLORS: Record<"PT" | "ES", string> = { PT: "#10a37f", ES: "#f59e0b" };

function formatNumber(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT");
}

function formatEuro(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function formatCompactEuro(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil M €`;
  if (abs >= 1e6) return `${(value / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M €`;
  if (abs >= 1e3) return `${(value / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} mil €`;
  return formatEuro(value);
}

/** Cartão de indicador. */
function Kpi({ label, value, hint, icon }: { label: string; value: string; hint?: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded-2xl glass-card px-3 py-2">
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <p className="mt-1 text-base font-semibold leading-none">{value}</p>
      {hint && <p className="mt-1 text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Lista de entidades com barra proporcional ao valor. */
function EntityList({
  title,
  hint,
  rows,
  color,
  emptyLabel,
}: {
  title: string;
  hint: string;
  rows: RegionDetailEntity[];
  color: string;
  emptyLabel: string;
}) {
  const max = rows.reduce((acc, row) => Math.max(acc, row.total_value || 0), 0);
  return (
    <div className="rounded-2xl glass-card p-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p>
      <div className="mt-2 space-y-1.5">
        {rows.slice(0, 12).map((row) => (
          <div key={`${row.nif ?? row.name}-${row.count}`} className="rounded-xl px-1 py-1">
            <div className="flex items-baseline gap-2">
              <span className="truncate text-xs" title={row.name}>
                {row.name}
              </span>
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                {formatNumber(row.count)} · {formatCompactEuro(row.total_value)}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full" style={{ width: `${max > 0 ? ((row.total_value || 0) / max) * 100 : 0}%`, background: color }} />
            </div>
          </div>
        ))}
        {rows.length === 0 && <p className="py-2 text-center text-[11px] text-muted-foreground">{emptyLabel}</p>}
      </div>
    </div>
  );
}

/** Lista analítica genérica (ano, CPV, procedimento, escalões…). */
function MetricList({
  title,
  rows,
  labelOf,
  max,
}: {
  title: string;
  rows: RegionDetailRow[];
  labelOf?: (row: RegionDetailRow) => string;
  max?: number;
}) {
  const top = max ?? rows.reduce((acc, row) => Math.max(acc, row.count || 0), 0);
  return (
    <div className="rounded-2xl glass-card p-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="mt-2 space-y-1.5">
        {rows.slice(0, 10).map((row) => (
          <div key={`${row.key}-${row.description ?? ""}`}>
            <div className="flex items-baseline gap-2">
              <span className="truncate text-[11px]" title={labelOf ? labelOf(row) : row.key}>
                {labelOf ? labelOf(row) : row.key}
              </span>
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                {formatNumber(row.count)} · {formatCompactEuro(row.total_value)}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-primary/70" style={{ width: `${top > 0 ? (row.count / top) * 100 : 0}%` }} />
            </div>
          </div>
        ))}
        {rows.length === 0 && <p className="py-2 text-center text-[11px] text-muted-foreground">Sem dados.</p>}
      </div>
    </div>
  );
}

export function RegionDetailWindow({ pais, code, ano, onClose }: RegionDetailWindowProps) {
  const [data, setData] = useState<RegionDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Ano escolhido dentro da janela (começa no ano do mapa). */
  const [anoLocal, setAnoLocal] = useState<number | "">(ano ?? "");
  const [years, setYears] = useState<number[]>([]);

  const region = useMemo(() => resolveIberiaRegion(pais, code), [pais, code]);
  const title = region?.name ?? data?.code ?? code;

  useEffect(() => {
    setAnoLocal(ano ?? "");
  }, [ano]);

  /** Anos indexados nos dois países (o ano do mapa é só a sugestão inicial). */
  useEffect(() => {
    Promise.all([
      pais === "PT" ? getContractYears() : Promise.resolve(null),
      pais === "ES" ? getContratosEsStatus() : Promise.resolve(null),
    ])
      .then(([pt, es]) => {
        const all = new Set<number>();
        for (const row of pt?.indexed ?? []) all.add(row.year);
        for (const year of es?.years ?? []) all.add(year);
        setYears([...all].sort((a, b) => b - a));
      })
      .catch(() => setYears([]));
  }, [pais]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getContractRegionDetail({
        pais,
        code,
        ano: anoLocal === "" ? null : Number(anoLocal),
      });
      if (response.error) throw new Error(response.error);
      setData(response);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Erro ao carregar a região");
    } finally {
      setLoading(false);
    }
  }, [anoLocal, code, pais]);

  useEffect(() => {
    void load();
  }, [load]);

  const totals = data?.totals;
  const byYear = useMemo(() => [...(data?.by_year ?? [])].sort((a, b) => Number(b.key) - Number(a.key)), [data?.by_year]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background text-foreground">
      <header className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="flex items-center gap-2 rounded-full glass-card px-3 py-1.5 text-sm text-muted-foreground transition hover:text-foreground"
          >
            <ArrowLeft size={16} />
            Voltar
          </button>
        )}
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: COUNTRY_COLORS[pais] }} />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold leading-tight">{title} · contratos e entidades</h1>
          <p className="text-[11px] text-muted-foreground">
            {COUNTRY_LABELS[pais]}
            {region ? ` · ${LEVEL_LABELS[region.level]}` : ""}
            {region?.approx ? " · posição aproximada no mapa" : ""}
          </p>
        </div>
        <label className="ml-auto flex items-center gap-2 rounded-2xl glass-card px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">Ano</span>
          <select
            value={anoLocal}
            onChange={(event) => setAnoLocal(event.target.value ? Number(event.target.value) : "")}
            className="bg-transparent text-xs outline-none"
          >
            <option value="">Todos</option>
            {years.map((year) => (
              <option key={year} value={year} className="text-foreground">
                {year}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          Atualizar
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {error && (
          <div className="mb-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</div>
        )}

        {loading && !data && (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-xs text-muted-foreground">
            <Loader2 size={20} className="animate-spin" />
            A agregar contratos, entidades e métricas de {title}…
          </div>
        )}

        {totals && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
              <Kpi label="Contratos" value={formatNumber(totals.contracts)} icon={<FileText size={11} />} />
              <Kpi label="Valor contratual" value={formatCompactEuro(totals.value)} icon={<Euro size={11} />} />
              <Kpi
                label="Ticket médio"
                value={formatEuro(totals.avg)}
                hint={totals.max ? `maior: ${formatCompactEuro(totals.max)}` : undefined}
                icon={<TrendingUp size={11} />}
              />
              <Kpi
                label="Quem adjudica"
                value={formatNumber(totals.awarders)}
                hint={pais === "PT" ? "entidades adjudicantes distintas" : "órgãos distintos"}
                icon={<Landmark size={11} />}
              />
              <Kpi
                label="Empresas"
                value={formatNumber(totals.suppliers)}
                hint="adjudicatárias distintas"
                icon={<Building2 size={11} />}
              />
              <Kpi
                label="Valor por empresa"
                value={
                  totals.suppliers && totals.value
                    ? formatCompactEuro(totals.value / totals.suppliers)
                    : "—"
                }
                hint="média por adjudicatária"
              />
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-3">
              <EntityList
                title={pais === "PT" ? "Quem adjudica (entidades)" : "Quem adjudica (órgãos)"}
                hint="maiores por valor contratado na região"
                rows={data?.awarders ?? []}
                color={COUNTRY_COLORS[pais]}
                emptyLabel="Sem entidades identificadas."
              />
              <EntityList
                title="Empresas adjudicatárias"
                hint="maiores por valor executado na região"
                rows={data?.suppliers ?? []}
                color="#3b82f6"
                emptyLabel="Sem empresas identificadas."
              />
              <MetricList
                title="Por ano"
                rows={byYear.map((row) => ({ ...row, key: row.key }))}
                labelOf={(row) => `${row.key} · ${formatCompactEuro(row.total_value)}`}
                max={byYear.reduce((acc, row) => Math.max(acc, row.count), 0)}
              />
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-3">
              <MetricList
                title="Top CPV"
                rows={data?.by_cpv ?? []}
                labelOf={(row) => `${row.key}${row.description ? ` · ${row.description}` : ""}`}
              />
              <MetricList
                title={pais === "PT" ? "Procedimento" : "Procedimiento"}
                rows={data?.by_procedure ?? []}
                labelOf={(row) => row.description || row.key}
              />
              <MetricList
                title={pais === "PT" ? "Tipo de contrato" : "Tipo de contrato (ES)"}
                rows={data?.by_contract_type ?? []}
                labelOf={(row) => row.description || row.key}
              />
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-3">
              <MetricList
                title="Escalões de valor"
                rows={data?.by_value_range ?? []}
                labelOf={(row) => row.description || row.key}
              />
              <div className="rounded-2xl glass-card p-3 xl:col-span-2">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Maiores contratos {anoLocal ? `de ${anoLocal}` : "de todo o período"}
                </h2>
                <div className="mt-2 space-y-1.5">
                  {(data?.contracts ?? []).slice(0, 20).map((contract, index) => (
                    <div key={contract.doc_id ?? index} className="rounded-xl bg-white/5 px-2 py-1.5">
                      <p className="line-clamp-2 text-[11px]">{contract.title || "Contrato sem objeto descrito"}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
                        <span className="truncate">{contract.awarder || "—"}</span>
                        <span>→</span>
                        <span className="truncate">{contract.supplier || "—"}</span>
                        <span className="ml-auto shrink-0 text-foreground">{formatCompactEuro(contract.value)}</span>
                        {contract.ano ? <span className="shrink-0">· {contract.ano}</span> : null}
                      </p>
                    </div>
                  ))}
                  {(data?.contracts ?? []).length === 0 && (
                    <p className="py-3 text-center text-[11px] text-muted-foreground">
                      Sem contratos indexados para esta região.
                    </p>
                  )}
                </div>
              </div>
            </div>

            <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
              Região definida pela geografia dos contratos publicados: distrito de execução em Portugal
              (<code>localExecucao</code>) e província/NUTS em Espanha (<code>nuts</code>). Um contrato com execução em
              vários distritos conta em cada um deles.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
