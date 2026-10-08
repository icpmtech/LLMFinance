/**
 * Contratação pública ecológica.
 *
 * Área dedicada à transparência da aplicação de **critérios ecológicos** nas
 * compras públicas: parte do campo `ContratEcologico` do portal BASE (valor
 * "Sim") e mostra o volume e o valor face ao universo total, a evolução anual, a
 * distribuição regional/CPV e a lista dos procedimentos identificados — cada um
 * com acesso às **peças do procedimento** (ligações oficiais e texto extraído do
 * pacote publicado).
 *
 * Os indicadores vêm de `/contracts/analytics` com `ecological=true`, a lista de
 * `/contracts/search` e as peças de `/contracts/{id}/document` — todos já
 * existentes; esta página é sobretudo leitura e contexto.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Filter,
  Leaf,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  getContractAnalytics,
  getContractDocument,
  getContractRegionalAnalytics,
  getContractYears,
  searchContracts,
} from "../api";
import type {
  ContractAnalyticsResponse,
  ContractDocumentResponse,
  ContractItem,
  ContractParty,
  ContractRegionalResponse,
} from "../types";

interface ContratosEcologicosPageProps {
  onSwitchView: () => void;
  onSwitchSearch?: () => void;
  onSwitchDashboard?: () => void;
}

/** Filtros do formulário (strings para os campos numéricos/opcionais). */
type EcoFilters = {
  q: string;
  year: number | "";
  region: string;
  cpv: string;
  minValue: string;
  maxValue: string;
};

const EMPTY_FILTERS: EcoFilters = { q: "", year: "", region: "", cpv: "", minValue: "", maxValue: "" };
const PAGE_SIZE = 20;
const INPUT_CLASS =
  "w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-emerald-400/50";

function money(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function num(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT");
}

function percent(part?: number | null, whole?: number | null): string {
  if (!part || !whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

/** Normaliza as partes (o índice guarda `{raw, parsed}` ou listas dos dois). */
function partyList(parties?: ContractParty | ContractParty[]): { nome?: string; nif?: string }[] {
  if (!parties) return [];
  const list = Array.isArray(parties) ? parties : [parties];
  return list.flatMap((entry) => {
    const parsed = (entry as { parsed?: { nome?: string; nif?: string }[] })?.parsed;
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    const raw = (entry as { raw?: unknown })?.raw;
    if (Array.isArray(raw)) {
      return raw.map((value) => (typeof value === "string" ? { nome: value } : (value as { nome?: string; nif?: string })));
    }
    if (typeof raw === "string") {
      return raw
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
        .map((value) => {
          const match = value.match(/\b\d{9}\b/);
          return { nome: value.replace(/\b\d{9}\b/g, "").replace(/[()]/g, "").trim(), nif: match?.[0] };
        });
    }
    return [];
  });
}

function partyNames(parties?: ContractParty | ContractParty[]): string {
  const names = partyList(parties)
    .map((entry) => entry.nome)
    .filter((name): name is string => Boolean(name));
  return names.length > 0 ? names.join(", ") : "—";
}

function place(contract: ContractItem): string {
  const nuts = Array.isArray(contract.NUTs) ? contract.NUTs[0] : contract.NUTs;
  const local = Array.isArray(contract.localExecucao) ? contract.localExecucao[0] : contract.localExecucao;
  return String(nuts || local || "—");
}

/** Converte o formulário nos parâmetros comuns às três chamadas. */
function toQuery(filters: EcoFilters) {
  const query: {
    q?: string;
    year?: number;
    region?: string;
    cpv_code?: string;
    min_price?: number;
    max_price?: number;
  } = {};
  if (filters.q.trim()) query.q = filters.q.trim();
  if (filters.year !== "") query.year = filters.year;
  if (filters.region.trim()) query.region = filters.region.trim();
  if (filters.cpv.trim()) query.cpv_code = filters.cpv.trim();
  if (filters.minValue.trim() && !Number.isNaN(Number(filters.minValue))) query.min_price = Number(filters.minValue);
  if (filters.maxValue.trim() && !Number.isNaN(Number(filters.maxValue))) query.max_price = Number(filters.maxValue);
  return query;
}

function Badge({ children, tone = "emerald" }: { children: React.ReactNode; tone?: "emerald" | "sky" | "amber" }) {
  const tones = {
    emerald: "bg-emerald-400/10 text-emerald-300 border-emerald-400/20",
    sky: "bg-sky-400/10 text-sky-300 border-sky-400/20",
    amber: "bg-amber-400/10 text-amber-300 border-amber-400/20",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Stat({ label, value, hint, tone = "text-emerald-300" }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="glass-card rounded-2xl p-5">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-2 text-2xl font-bold stat-value ${tone}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function ContratosEcologicosPage({ onSwitchView, onSwitchSearch, onSwitchDashboard }: ContratosEcologicosPageProps) {
  const [filters, setFilters] = useState<EcoFilters>(EMPTY_FILTERS);
  const [draft, setDraft] = useState<EcoFilters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);

  const [eco, setEco] = useState<ContractAnalyticsResponse | null>(null);
  const [universe, setUniverse] = useState<ContractAnalyticsResponse | null>(null);
  const [regional, setRegional] = useState<ContractRegionalResponse | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [regionOptions, setRegionOptions] = useState<string[]>([]);

  const [items, setItems] = useState<ContractItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);

  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [openId, setOpenId] = useState<string | null>(null);
  const [docs, setDocs] = useState<Record<string, ContractDocumentResponse>>({});
  const [docLoading, setDocLoading] = useState<string | null>(null);
  const [docErrors, setDocErrors] = useState<Record<string, string>>({});
  const [showPieceText, setShowPieceText] = useState<Record<string, boolean>>({});

  // Anos indexados e o universo total (denominador das percentagens).
  useEffect(() => {
    getContractYears()
      .then((res) => setYears(res.available ?? []))
      .catch(() => setYears([]));
    getContractAnalytics({ top_entities: 1, top_cpv: 1 })
      .then(setUniverse)
      .catch(() => setUniverse(null));
    getContractRegionalAnalytics(undefined, {}, 60)
      .then((res) => {
        setRegionOptions(
          Array.from(new Set((res.regions ?? []).map((row) => row.key)))
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b, "pt")),
        );
      })
      .catch(() => setRegionOptions([]));
  }, []);

  // Indicadores do recorte ecológico (reagem aos filtros).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const query = toQuery(filters);
    Promise.all([
      getContractAnalytics({ ...query, ecological: true, top_entities: 10, top_cpv: 10 }),
      getContractRegionalAnalytics(query.year, { ...query, ecological: true }, 60),
    ])
      .then(([analytics, regions]) => {
        if (cancelled) return;
        setEco(analytics);
        setRegional(regions);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro ao carregar os indicadores");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  // Lista de procedimentos (paginada, do maior valor para o menor).
  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    searchContracts({
      ...toQuery(filters),
      ecological: true,
      size: PAGE_SIZE,
      from: page * PAGE_SIZE,
      sort_by: "precoContratual",
      sort_order: "desc",
    })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items ?? []);
        setTotal(res.total ?? 0);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro ao carregar os procedimentos");
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters, page]);

  const applyFilters = () => {
    setFilters(draft);
    setPage(0);
    setOpenId(null);
  };

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPage(0);
    setOpenId(null);
  };

  const toggleDoc = async (idcontrato?: string) => {
    if (!idcontrato) return;
    if (openId === idcontrato) {
      setOpenId(null);
      return;
    }
    setOpenId(idcontrato);
    if (docs[idcontrato] || docLoading === idcontrato) return;
    setDocLoading(idcontrato);
    try {
      const doc = await getContractDocument(idcontrato);
      setDocs((prev) => ({ ...prev, [idcontrato]: doc }));
    } catch (err) {
      setDocErrors((prev) => ({
        ...prev,
        [idcontrato]: err instanceof Error ? err.message : "Erro ao obter as peças",
      }));
    } finally {
      setDocLoading(null);
    }
  };

  const activeFilters = useMemo(
    () =>
      [
        filters.q && `texto: ${filters.q}`,
        filters.year !== "" && `ano: ${filters.year}`,
        filters.region && `região: ${filters.region}`,
        filters.cpv && `CPV: ${filters.cpv}`,
        filters.minValue && `mín.: ${money(Number(filters.minValue))}`,
        filters.maxValue && `máx.: ${money(Number(filters.maxValue))}`,
      ].filter((value): value is string => Boolean(value)),
    [filters],
  );

  const byYear = useMemo(() => {
    const universeByYear = new Map((universe?.by_year ?? []).map((row) => [row.key, row.count]));
    return [...(eco?.by_year ?? [])]
      .sort((a, b) => (a.key < b.key ? -1 : 1))
      .map((row) => ({
        key: row.key,
        count: row.count,
        total: universeByYear.get(row.key) ?? 0,
        value: row.total_value ?? 0,
      }));
  }, [eco, universe]);

  const topCpv = eco?.top_cpv ?? [];
  const topEntities = eco?.top_entities ?? [];
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-7xl px-4 py-8 @2xl:px-6">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
          <button
            onClick={onSwitchView}
            className="glass-card flex items-center gap-2 rounded-full px-3 py-1.5 text-sm text-muted-foreground transition hover:text-foreground"
          >
            <ArrowLeft size={16} /> Voltar
          </button>
          <div className="flex flex-wrap items-center gap-2">
            {loading && <Loader2 size={16} className="animate-spin text-emerald-300" />}
            <button
              onClick={() => setShowFilters((value) => !value)}
              className={`glass-card flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                showFilters ? "bg-emerald-400/10 text-emerald-200 ring-1 ring-emerald-400/30" : "hover:bg-white/5"
              }`}
            >
              <Filter size={16} /> Filtros
            </button>
            {onSwitchDashboard && (
              <button
                onClick={onSwitchDashboard}
                className="glass-card flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition hover:bg-white/5"
              >
                <BarChart3 size={16} /> Análise
              </button>
            )}
            {onSwitchSearch && (
              <button
                onClick={onSwitchSearch}
                className="glass-card flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition hover:bg-white/5"
              >
                <FileText size={16} /> Pesquisar contratos
              </button>
            )}
          </div>
        </div>

        <div className="mb-8 fade-in">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs text-emerald-200">
            <ShieldCheck size={14} /> Transparência das compras públicas verdes
          </div>
          <h1 className="mb-2 flex items-center gap-3 text-3xl font-bold md:text-4xl">
            <span className="rounded-2xl border border-white/10 bg-gradient-to-br from-emerald-500/20 to-teal-500/15 p-2">
              <Leaf size={32} className="text-emerald-400" />
            </span>
            Contratação Pública Ecológica
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Todos os procedimentos identificados com critérios ecológicos (<code>ContratEcologico = Sim</code> no portal
            BASE), com as respetivas peças do procedimento. As percentagens comparam este universo com o total de
            contratos indexados.
          </p>
        </div>

        {error && (
          <div className="mb-6 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">{error}</div>
        )}

        {showFilters && (
          <div className="glass-card fade-in mb-8 rounded-2xl p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 font-semibold">
                <Filter size={18} /> Filtros
              </h2>
              <span className="text-xs text-muted-foreground">Só contratos com critérios ecológicos</span>
            </div>
            <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2 @5xl:grid-cols-4">
              <label className="@lg:col-span-2">
                <span className="mb-1 block text-xs text-muted-foreground">Texto livre</span>
                <input
                  type="text"
                  value={draft.q}
                  onChange={(event) => setDraft((prev) => ({ ...prev, q: event.target.value }))}
                  placeholder="Objeto, entidades, descrição…"
                  className={INPUT_CLASS}
                />
              </label>
              <label>
                <span className="mb-1 block text-xs text-muted-foreground">Ano</span>
                <select
                  value={draft.year === "" ? "" : String(draft.year)}
                  onChange={(event) =>
                    setDraft((prev) => ({ ...prev, year: event.target.value === "" ? "" : Number(event.target.value) }))
                  }
                  className={INPUT_CLASS}
                >
                  <option value="">Todos os anos</option>
                  {years.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-xs text-muted-foreground">Região</span>
                <select
                  value={draft.region}
                  onChange={(event) => setDraft((prev) => ({ ...prev, region: event.target.value }))}
                  className={INPUT_CLASS}
                >
                  <option value="">Todas as regiões</option>
                  {regionOptions.map((region) => (
                    <option key={region} value={region}>
                      {region}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-xs text-muted-foreground">Código CPV</span>
                <input
                  type="text"
                  value={draft.cpv}
                  onChange={(event) => setDraft((prev) => ({ ...prev, cpv: event.target.value }))}
                  placeholder="ex.: 33600"
                  className={INPUT_CLASS}
                />
              </label>
              <label>
                <span className="mb-1 block text-xs text-muted-foreground">Valor mínimo €</span>
                <input
                  type="number"
                  min={0}
                  value={draft.minValue}
                  onChange={(event) => setDraft((prev) => ({ ...prev, minValue: event.target.value }))}
                  className={INPUT_CLASS}
                />
              </label>
              <label>
                <span className="mb-1 block text-xs text-muted-foreground">Valor máximo €</span>
                <input
                  type="number"
                  min={0}
                  value={draft.maxValue}
                  onChange={(event) => setDraft((prev) => ({ ...prev, maxValue: event.target.value }))}
                  className={INPUT_CLASS}
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                onClick={applyFilters}
                className="glass-card rounded-xl bg-emerald-400/10 px-4 py-2 text-sm text-emerald-200 ring-1 ring-emerald-400/20 transition hover:bg-emerald-400/15"
              >
                Aplicar filtros
              </button>
              <button onClick={resetFilters} className="glass-card rounded-xl px-4 py-2 text-sm transition hover:bg-white/5">
                Limpar
              </button>
            </div>
          </div>
        )}

        {activeFilters.length > 0 && (
          <div className="glass-card mb-8 flex flex-wrap items-center gap-2 rounded-2xl px-4 py-3 text-sm">
            <span className="text-muted-foreground">Filtros ativos:</span>
            {activeFilters.map((label) => (
              <span key={label} className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs">
                {label}
              </span>
            ))}
            <button onClick={resetFilters} className="ml-auto text-xs text-emerald-300 hover:underline">
              Limpar tudo
            </button>
          </div>
        )}

        <div className="mb-8 grid grid-cols-1 gap-4 @lg:grid-cols-2 @5xl:grid-cols-5">
          <Stat
            label="Contratos ecológicos"
            value={num(eco?.total_contracts)}
            hint={`${percent(eco?.total_contracts, universe?.total_contracts)} do universo (${num(universe?.total_contracts)})`}
          />
          <Stat
            label="Valor adjudicado"
            value={money(eco?.total_value)}
            hint={`${percent(eco?.total_value, universe?.total_value)} do valor total`}
            tone="text-teal-300"
          />
          <Stat label="Valor médio" value={money(eco?.avg_value)} hint={`Maior: ${money(eco?.max_value)}`} tone="text-sky-300" />
          <Stat
            label="Entidades"
            value={num(eco?.distinct_adjudicatarios)}
            hint={`adjudicatárias · ${num(eco?.distinct_adjudicantes)} adjudicantes`}
            tone="text-indigo-300"
          />
          <Stat
            label="Regiões e CPV"
            value={`${num(regional?.region_count)} / ${num(eco?.distinct_cpv)}`}
            hint="regiões NUTS · categorias CPV"
            tone="text-amber-300"
          />
        </div>

        <div className="mb-8 grid grid-cols-1 gap-6 @4xl:grid-cols-2">
          <div className="glass-card rounded-2xl p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">Evolução da contratação ecológica</h2>
                <p className="text-xs text-muted-foreground">Contratos por ano (percentagem do total do ano no cursor)</p>
              </div>
              <Badge tone="emerald">
                <Leaf size={11} /> {num(eco?.total_contracts)}
              </Badge>
            </div>
            <div className="h-64 overflow-hidden @3xl:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byYear}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="key" stroke="rgba(255,255,255,0.3)" fontSize={12} />
                  <YAxis stroke="rgba(255,255,255,0.3)" fontSize={12} tickFormatter={(value) => num(Number(value))} />
                  <Tooltip
                    contentStyle={{ background: "rgba(7,21,27,0.95)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12 }}
                    formatter={(value, _name, entry) => {
                      const row = entry?.payload as { count: number; total: number } | undefined;
                      return [`${num(Number(value))} contratos`, `ecológicos (${percent(row?.count, row?.total)} do ano)`];
                    }}
                  />
                  <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">Onde se concentra</h2>
                <p className="text-xs text-muted-foreground">Categorias CPV com mais contratos ecológicos</p>
              </div>
              <Badge tone="sky">CPV</Badge>
            </div>
            <div className="h-64 space-y-3 overflow-auto pr-1 @3xl:h-72">
              {topCpv.length === 0 && <p className="text-sm text-muted-foreground">Sem dados para os filtros aplicados.</p>}
              {topCpv.map((row) => {
                const peak = topCpv[0]?.count || 1;
                return (
                  <div key={row.key}>
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate" title={row.description || row.key}>
                        <span className="mr-2 font-mono text-[11px] text-muted-foreground">{row.key}</span>
                        {row.description || "Sem descrição"}
                      </span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{num(row.count)}</span>
                    </div>
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                      <div
                        className="h-full rounded-full bg-emerald-400"
                        style={{ width: `${Math.max(2, ((row.count || 0) / peak) * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {topEntities.length > 0 && (
          <div className="glass-card mb-8 rounded-2xl p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">Quem contrata com critérios ecológicos</h2>
                <p className="text-xs text-muted-foreground">Entidades com maior valor adjudicado neste recorte</p>
              </div>
              <Badge tone="amber">Top {topEntities.length}</Badge>
            </div>
            <div className="grid gap-3 @xl:grid-cols-2 @5xl:grid-cols-3">
              {topEntities.slice(0, 9).map((row) => (
                <div key={row.key} className="rounded-xl border border-white/5 bg-white/[0.03] p-3">
                  <p className="truncate text-sm" title={row.description || row.key}>
                    {row.description || row.key}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {num(row.count)} contratos · <span className="text-emerald-300">{money(row.total_value)}</span>
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="glass-card rounded-2xl p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 font-semibold">
                <FileText size={18} className="text-emerald-300" /> Procedimentos com critérios ecológicos
              </h2>
              <p className="text-xs text-muted-foreground">
                {num(total)} procedimentos identificados · página {page + 1} de {totalPages}
              </p>
            </div>
            <div className="flex items-center gap-1">
              {listLoading && <Loader2 size={16} className="animate-spin text-emerald-300" />}
              <button
                onClick={() => setPage((value) => Math.max(0, value - 1))}
                disabled={page === 0 || listLoading}
                aria-label="Página anterior"
                className="glass-card rounded-lg p-1.5 transition hover:bg-white/5 disabled:opacity-40"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setPage((value) => value + 1)}
                disabled={page + 1 >= totalPages || listLoading}
                aria-label="Página seguinte"
                className="glass-card rounded-lg p-1.5 transition hover:bg-white/5 disabled:opacity-40"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          {items.length === 0 && !listLoading && (
            <p className="py-10 text-center text-sm text-muted-foreground">Sem procedimentos para os filtros aplicados.</p>
          )}

          <div className="space-y-4">
            {items.map((contract) => {
              const id = contract.idcontrato ?? "";
              const open = openId === id;
              const doc = docs[id];
              const loadingDoc = docLoading === id;
              const showText = Boolean(showPieceText[id]);
              return (
                <article key={id || contract.doc_id} className="rounded-2xl border border-white/5 bg-white/[0.02] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-snug">
                        {contract.objectoContrato || contract.descContrato || "Sem objeto publicado"}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {id} · {contract.Ano ?? "—"} · {contract.tipoprocedimento || "procedimento n/d"} ·{" "}
                        {contract.tipoContrato || "tipo n/d"} · {place(contract)}
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground" title={`${partyNames(contract.adjudicantes)} → ${partyNames(contract.adjudicatarios)}`}>
                        <span className="text-foreground/70">{partyNames(contract.adjudicantes)}</span>
                        {" → "}
                        {partyNames(contract.adjudicatarios)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-lg font-semibold text-emerald-300">{money(contract.precoContratual ?? contract.PrecoTotalEfetivo)}</p>
                      <div className="mt-1 flex flex-wrap justify-end gap-1">
                        <Badge tone="emerald">
                          <Leaf size={11} /> Ecológico
                        </Badge>
                        {contract.linkPecasProc && <Badge tone="sky">Peças publicadas</Badge>}
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => void toggleDoc(id)}
                      className="glass-card flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-emerald-200 transition hover:bg-emerald-400/10"
                    >
                      <FileText size={13} /> {open ? "Ocultar peças" : "Peças do procedimento"}
                    </button>
                    {contract.linkPecasProc && (
                      <a
                        href={contract.linkPecasProc}
                        target="_blank"
                        rel="noreferrer"
                        className="glass-card flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition hover:bg-white/5"
                      >
                        <ExternalLink size={13} /> Abrir pacote no BASE
                      </a>
                    )}
                  </div>

                  {open && (
                    <div className="mt-3 rounded-xl border border-white/10 bg-black/20 p-3">
                      {loadingDoc && (
                        <p className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 size={14} className="animate-spin" /> A ler as peças do procedimento…
                        </p>
                      )}
                      {docErrors[id] && <p className="text-xs text-amber-300">{docErrors[id]}</p>}
                      {doc && (
                        <>
                          {(doc.links ?? []).length > 0 ? (
                            <div className="flex flex-wrap gap-2">
                              {doc.links.map((link) => (
                                <a
                                  key={link.url}
                                  href={link.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-emerald-200 transition hover:border-emerald-400/40"
                                >
                                  <ExternalLink size={12} /> {link.label}
                                </a>
                              ))}
                            </div>
                          ) : (
                            <p className="text-xs text-muted-foreground">Sem ligações oficiais publicadas.</p>
                          )}

                          {(doc.highlights ?? []).length > 0 && (
                            <div className="mt-3 grid gap-2 @xl:grid-cols-2 @5xl:grid-cols-3">
                              {doc.highlights.slice(0, 9).map((fact) => (
                                <div key={`${fact.label}-${fact.value}`} className="rounded-lg bg-white/[0.03] p-2">
                                  <p className="text-[11px] text-muted-foreground">{fact.label}</p>
                                  <p className="text-xs font-medium break-words text-foreground/90">{String(fact.value ?? "—")}</p>
                                </div>
                              ))}
                            </div>
                          )}

                          {(doc.pieces ?? []).some((piece) => piece.text) && (
                            <div className="mt-3">
                              <button
                                onClick={() => setShowPieceText((prev) => ({ ...prev, [id]: !prev[id] }))}
                                className="flex items-center gap-1 text-xs text-emerald-300 hover:underline"
                              >
                                <FileText size={12} /> {showText ? "Ocultar texto das peças" : "Ver texto das peças"}
                              </button>
                              {showText && (
                                <div className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/10 bg-black/20 p-3 text-xs text-foreground/80">
                                  {(doc.pieces ?? [])
                                    .filter((piece) => piece.text)
                                    .map((piece) => (
                                      <div key={piece.name} className="mb-3">
                                        <p className="mb-1 font-medium text-emerald-200">{piece.name}</p>
                                        {piece.text}
                                      </div>
                                    ))}
                                </div>
                              )}
                            </div>
                          )}

                          {doc.note && <p className="mt-2 text-xs text-muted-foreground">{doc.note}</p>}
                          {doc.error && <p className="mt-2 text-xs text-amber-300">{doc.error}</p>}
                        </>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </div>

        <p className="mt-6 text-[11px] text-muted-foreground">
          Fonte: contratos públicos publicados no portal BASE, indexados na plataforma. Os critérios ecológicos seguem o
          campo <code>ContratEcologico</code> da publicação; as peças do procedimento são lidas do pacote oficial indicado
          em <code>linkPecasProc</code>. Indicadores atualizados a cada consulta.
        </p>
      </div>
    </div>
  );
}
