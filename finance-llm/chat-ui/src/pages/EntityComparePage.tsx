/**
 * Página de comparação de entidades (adjudicantes, adjudicatários e empresas).
 *
 * Parte da mesma seleção do comparador (store `finance-llm-compare:v1`), mas
 * oferece uma leitura de página inteira com uma lente por papel: os indicadores,
 * as distribuições e as contrapartes passam a refletir o papel escolhido
 * (`all`, `adjudicante`, `adjudicatario`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Building2,
  Briefcase,
  GitCompare,
  Landmark,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trophy,
  X,
} from "lucide-react";
import { getCompanyAnalytics, getCompanyDetail, searchCompanies } from "../api";
import type {
  CompanyAnalyticsResponse,
  CompanyDetail,
  CompanySummary,
  ContractAnalyticsRow,
  EntityRole,
} from "../types";
import { formatFinderValue } from "../finder";
import { MAX_COMPARE, compareKey, openCompareWindow, useCompare, type CompareItem } from "../compare";
import { nifsFromParty, partyNames } from "../pages/EmpresasIQPage";

interface EntityComparePageProps {
  onOpenEntity: (nif: string) => void;
  onOpenDashboard?: (role: EntityRole) => void;
  onBack?: () => void;
}

type EntityLoad = {
  item: CompareItem;
  detail: CompanyDetail;
  analytics: CompanyAnalyticsResponse | null;
  /** Distribuições derivadas das agregações (chave/contagem/valor). */
  byYear: { key: string; count: number; value: number }[];
  cpv: { key: string; count: number; value: number; label: string }[];
  partners: { key: string; count: number; value: number; label: string }[];
  procedures: { key: string; count: number; value: number; label: string }[];
};

const LENS_COPY: Record<EntityRole, { label: string; icon: React.ElementType }> = {
  all: { label: "Empresas", icon: Building2 },
  adjudicante: { label: "Adjudicantes", icon: Landmark },
  adjudicatario: { label: "Adjudicatários", icon: Briefcase },
};

function rows(list?: ContractAnalyticsRow[]) {
  return (list ?? []).map((row) => ({
    key: row.key,
    count: row.count,
    value: row.total_value ?? 0,
    label: row.description || row.key,
  }));
}

async function loadEntity(item: CompareItem, role: EntityRole): Promise<EntityLoad> {
  const [detail, analytics] = await Promise.all([
    getCompanyDetail(item.id),
    getCompanyAnalytics(item.id, role).catch(() => null),
  ]);
  return {
    item,
    detail,
    analytics,
    byYear: rows(analytics?.by_year).sort((a, b) => b.key.localeCompare(a.key)).slice(0, 6),
    cpv: rows(analytics?.by_cpv).sort((a, b) => b.value - a.value).slice(0, 8),
    partners: rows(analytics?.top_partners).sort((a, b) => b.value - a.value).slice(0, 5),
    procedures: rows(analytics?.by_procedure_type).sort((a, b) => b.value - a.value).slice(0, 4),
  };
}

const inputClass =
  "w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60";

function best(values: number[], higher = true): number | null {
  if (values.length < 2 || values.some((value) => !Number.isFinite(value))) return null;
  return higher ? Math.max(...values) : Math.min(...values);
}

/** Tabela de métricas com destaque do melhor valor e barra proporcional. */
function MetricTable({
  rows: metricRows,
  columns,
}: {
  rows: { label: string; values: number[]; format: (value: number) => string; higher?: boolean; hint?: string }[];
  columns: string[];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/8">
      <table className="w-full text-[12px] min-w-[520px]">
        <thead className="bg-white/[0.04] text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 text-left font-medium">Métrica</th>
            {columns.map((column, index) => (
              <th key={`${column}-${index}`} className="px-3 py-1.5 text-right font-medium">
                <span className="line-clamp-1">{column}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricRows.map((row) => {
            const winner = best(row.values, row.higher !== false);
            const max = Math.max(1, ...row.values.map((value) => Math.abs(value)));
            return (
              <tr key={row.label} className="border-t border-white/6">
                <td className="px-3 py-1.5 text-muted-foreground">
                  {row.label}
                  {row.hint && <span className="ml-1 text-[10px] text-muted-foreground/70">({row.hint})</span>}
                </td>
                {row.values.map((value, index) => (
                  <td key={`${row.label}-${index}`} className="px-3 py-1.5 text-right">
                    <span className={winner !== null && value === winner ? "font-semibold text-teal-300" : ""}>
                      {row.format(value)}
                    </span>
                    <span className="mt-1 block h-1 rounded-full bg-white/8">
                      <span
                        className="block h-1 rounded-full bg-indigo-400/70"
                        style={{ width: `${Math.max(2, Math.round((Math.abs(value) / max) * 100))}%` }}
                      />
                    </span>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function EntityComparePage({ onOpenEntity, onOpenDashboard }: EntityComparePageProps) {
  const { items, kind, add, remove, clear, full } = useCompare();
  const [lens, setLens] = useState<EntityRole>("all");
  const [loaded, setLoaded] = useState<EntityLoad[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<CompareItem[]>([]);
  const [searching, setSearching] = useState(false);

  const entityItems = useMemo(() => items.filter((item) => item.kind === "entity"), [items]);
  const entityIds = useMemo(() => entityItems.map((item) => item.id).join("|"), [entityItems]);

  useEffect(() => {
    let cancelled = false;
    if (entityItems.length === 0) {
      setLoaded([]);
      return;
    }
    setLoading(true);
    setError(null);
    void Promise.all(entityItems.map((item) => loadEntity(item, lens)))
      .then((result) => {
        if (!cancelled) setLoaded(result);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Erro ao carregar a comparação.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityIds, lens]);

  /* Pesquisa de entidades para acrescentar à comparação. */
  useEffect(() => {
    const term = query.trim();
    if (term.length < 3) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      void searchCompanies({ q: term, role: lens, size: 8 })
        .then((response) => {
          if (cancelled) return;
          setOptions(
            response.items
              .filter((entity): entity is CompanySummary & { nif: string } => Boolean(entity.nif))
              .map((entity) => ({
                kind: "entity" as const,
                id: entity.nif,
                name: entity.name,
                subtitle: `NIF ${entity.nif} · ${entity.contracts_total} contratos · ${formatFinderValue(entity.total_value)}`,
              })),
          );
        })
        .catch(() => {
          if (!cancelled) setOptions([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, lens]);

  const addItem = useCallback(
    (item: CompareItem) => {
      add([item]);
      setQuery("");
      setOptions([]);
    },
    [add],
  );

  const years = useMemo(() => {
    const set = new Set<string>();
    for (const entry of loaded) for (const year of entry.byYear) set.add(year.key);
    return [...set].sort((a, b) => b.localeCompare(a)).slice(0, 6);
  }, [loaded]);

  const sharedCpv = useMemo(() => {
    const counts = new Map<string, { label: string; who: Set<string> }>();
    for (const entry of loaded) {
      for (const cpv of entry.cpv) {
        const current = counts.get(cpv.key) ?? { label: cpv.label, who: new Set<string>() };
        current.who.add(entry.item.name);
        counts.set(cpv.key, current);
      }
    }
    return [...counts.entries()]
      .filter(([, value]) => value.who.size > 1)
      .map(([key, value]) => ({ key, label: value.label, names: [...value.who] }))
      .slice(0, 10);
  }, [loaded]);

  const columns = loaded.map((entry) => entry.item.name);

  /** Métricas da lente escolhida. */
  const metrics = useMemo(() => {
    if (loaded.length === 0) return [];
    const detail = (entry: EntityLoad) => entry.detail;
    const scoped = (entry: EntityLoad) => {
      if (lens === "adjudicante") return entry.detail.adjudicante;
      if (lens === "adjudicatario") return entry.detail.adjudicatario;
      return null;
    };

    const scopedContracts = loaded.map((entry) =>
      lens === "all"
        ? Math.max(entry.analytics?.total_contracts ?? 0, detail(entry).contracts_total ?? 0)
        : Math.max(scoped(entry)?.contracts_count ?? 0, entry.analytics?.total_contracts ?? 0),
    );
    const scopedValue = loaded.map((entry) =>
      lens === "all"
        ? entry.analytics?.total_value ?? detail(entry).total_value ?? 0
        : scoped(entry)?.total_value ?? entry.analytics?.total_value ?? 0,
    );

    const base: { label: string; values: number[]; format: (value: number) => string; higher?: boolean; hint?: string }[] = [
      {
        label: lens === "all" ? "Contratos (total)" : "Contratos no papel",
        values: scopedContracts,
        format: (v) => v.toLocaleString("pt-PT"),
        hint: lens === "all" ? undefined : LENS_COPY[lens].label.toLowerCase(),
      },
      {
        label: lens === "all" ? "Valor contratado" : "Valor no papel",
        values: scopedValue,
        format: formatFinderValue,
      },
      {
        label: "Valor médio por contrato",
        values: loaded.map((entry) =>
          entry.analytics?.avg_value ?? (scopedContracts[loaded.indexOf(entry)] ? scopedValue[loaded.indexOf(entry)] / scopedContracts[loaded.indexOf(entry)] : 0),
        ),
        format: formatFinderValue,
      },
      {
        label: "Maior contrato",
        values: loaded.map((entry) => entry.analytics?.max_value ?? 0),
        format: formatFinderValue,
      },
      {
        label: "Como adjudicante (€)",
        values: loaded.map((entry) => detail(entry).adjudicante?.total_value ?? 0),
        format: formatFinderValue,
      },
      {
        label: "Como adjudicatário (€)",
        values: loaded.map((entry) => detail(entry).adjudicatario?.total_value ?? 0),
        format: formatFinderValue,
      },
      {
        label: "Contratos como adjudicante",
        values: loaded.map((entry) => detail(entry).adjudicante?.contracts_count ?? 0),
        format: (v) => v.toLocaleString("pt-PT"),
      },
      {
        label: "Contratos como adjudicatário",
        values: loaded.map((entry) => detail(entry).adjudicatario?.contracts_count ?? 0),
        format: (v) => v.toLocaleString("pt-PT"),
      },
      {
        label: "Códigos CPV distintos",
        values: loaded.map((entry) => entry.cpv.length ? new Set(entry.cpv.map((c) => c.key)).size : entry.analytics?.by_cpv?.length ?? 0),
        format: (v) => v.toLocaleString("pt-PT"),
      },
      {
        label: "Anos com atividade",
        values: loaded.map((entry) => entry.byYear.length),
        format: (v) => v.toLocaleString("pt-PT"),
      },
      {
        label: "Marcas INPI",
        values: loaded.map((entry) => detail(entry).trademarks_total ?? 0),
        format: (v) => v.toLocaleString("pt-PT"),
      },
      {
        label: "Firmas RNPC",
        values: loaded.map((entry) => detail(entry).firmas_total ?? 0),
        format: (v) => v.toLocaleString("pt-PT"),
      },
    ];
    return base;
  }, [loaded, lens]);

  /** Quantas métricas cada entidade lidera. */
  const scoreboard = useMemo(() => {
    const scores = loaded.map(() => 0);
    for (const row of metrics) {
      const winner = best(row.values, row.higher !== false);
      if (winner === null) continue;
      row.values.forEach((value, index) => {
        if (value === winner) scores[index] += 1;
      });
    }
    return loaded
      .map((entry, index) => ({ name: entry.item.name, score: scores[index] }))
      .sort((a, b) => b.score - a.score);
  }, [loaded, metrics]);

  const hasContracts = kind === "contract" && items.some((item) => item.kind === "contract");

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1500px] mx-auto px-4 md:px-6 py-6">
        {/* Cabeçalho */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <div className="flex items-center gap-1 rounded-2xl glass-card p-1">
            {(Object.keys(LENS_COPY) as EntityRole[]).map((candidate) => {
              const Icon = LENS_COPY[candidate].icon;
              const active = candidate === lens;
              return (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => setLens(candidate)}
                  aria-pressed={active}
                  className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm transition ${
                    active ? "bg-primary/15 text-primary" : "hover:bg-white/5"
                  }`}
                >
                  <Icon size={15} />
                  {LENS_COPY[candidate].label}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={clear}
            disabled={items.length === 0}
            className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm disabled:opacity-50 flex items-center gap-2"
          >
            <RefreshCw size={15} /> Limpar
          </button>

          {onOpenDashboard && (
            <button
              type="button"
              onClick={() => onOpenDashboard(lens)}
              className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm flex items-center gap-2"
            >
              <Layers size={15} className="text-teal-300" /> Ver dashboard
            </button>
          )}

          {hasContracts && (
            <button
              type="button"
              onClick={() => openCompareWindow()}
              className="px-3 py-2 rounded-xl glass-card hover:bg-white/5 transition text-sm flex items-center gap-2"
            >
              <GitCompare size={15} className="text-violet-300" /> Comparar contratos
            </button>
          )}
        </div>

        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card text-xs text-violet-300 mb-3">
            <GitCompare size={14} />
            Comparação lado a lado · até {MAX_COMPARE} entidades
          </div>
          <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
            <span className="p-2 rounded-2xl bg-gradient-to-br from-violet-500/20 to-indigo-500/15 border border-white/10">
              <GitCompare size={32} className="text-violet-300" />
            </span>
            Comparar {LENS_COPY[lens].label.toLowerCase()}
          </h1>
          <p className="text-muted-foreground mt-2">
            Escolha a lente por papel: os indicadores, as distribuições e as contrapartes passam a refletir apenas os
            contratos em que a entidade atua nesse papel.
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-center gap-2">
            <AlertCircle size={18} /> {error}
          </div>
        )}

        {/* Seletor de entidades */}
        <div className="glass-card gradient-border rounded-2xl p-5 mb-6">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <h2 className="font-semibold flex items-center gap-2">
              <Search size={18} /> Acrescentar entidade
            </h2>
            <span className="text-xs text-muted-foreground">
              {entityItems.length}/{MAX_COMPARE} selecionadas
            </span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,420px)_1fr] gap-3">
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Nome ou NIF da entidade…"
                className={`${inputClass} pl-9`}
                disabled={full}
              />
              {searching && (
                <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {items.map((item) => (
                <span
                  key={compareKey(item)}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px]"
                >
                  <span className="max-w-[220px] truncate font-medium">{item.name}</span>
                  {item.subtitle && (
                    <span className="hidden max-w-[150px] truncate text-[10.5px] text-muted-foreground sm:inline">
                      {item.subtitle}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => remove(item.kind, item.id)}
                    aria-label={`Remover ${item.name}`}
                    className="rounded p-0.5 text-muted-foreground transition hover:text-rose-300"
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
              {items.length === 0 && (
                <p className="text-[11.5px] text-muted-foreground">
                  Ainda não há entidades. Pesquise acima ou use o botão de comparação nos dashboards.
                </p>
              )}
            </div>
          </div>
          {full && (
            <p className="mt-2 text-[11px] text-amber-300">
              Limite de {MAX_COMPARE} entidades atingido — remova uma para acrescentar outra.
            </p>
          )}
          {query.trim().length >= 3 && (
            <ul className="mt-3 space-y-1 max-h-64 overflow-y-auto">
              {options.length === 0 && !searching && (
                <li className="px-1 py-2 text-[11.5px] text-muted-foreground">Sem resultados.</li>
              )}
              {options.map((option) => (
                <li key={compareKey(option)}>
                  <button
                    type="button"
                    disabled={full}
                    onClick={() => addItem(option)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition hover:bg-white/8 disabled:opacity-40"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{option.name}</span>
                      {option.subtitle && (
                        <span className="block truncate text-[10.5px] text-muted-foreground">{option.subtitle}</span>
                      )}
                    </span>
                    <Plus size={13} className="shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {entityItems.length === 0 ? (
          <div className="glass-card rounded-2xl p-10 flex flex-col items-center gap-2 text-center">
            <GitCompare size={28} className="text-muted-foreground/60" />
            <p className="text-sm text-muted-foreground">Escolha entidades para comparar.</p>
            <p className="max-w-md text-[11.5px] text-muted-foreground/80">
              Use a pesquisa acima, o botão de comparação nos dashboards de <strong>empresas</strong>,{" "}
              <strong>adjudicantes</strong> e <strong>adjudicatários</strong>, ou a ficha da entidade.
            </p>
            {onOpenDashboard && (
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                {(Object.keys(LENS_COPY) as EntityRole[]).map((candidate) => (
                  <button
                    key={candidate}
                    type="button"
                    onClick={() => onOpenDashboard(candidate)}
                    className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
                  >
                    <Layers size={13} /> Dashboard · {LENS_COPY[candidate].label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : loading && loaded.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
            <Loader2 size={18} className="animate-spin" /> A carregar dados…
          </div>
        ) : (
          <div className="space-y-6">
            {/* Scorecard */}
            <div className="glass-card gradient-border rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Trophy size={18} className="text-amber-300" />
                <h2 className="font-semibold">Quem lidera</h2>
                <span className="text-xs text-muted-foreground">
                  nº de métricas em que cada entidade tem o melhor valor (lente {LENS_COPY[lens].label.toLowerCase()})
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {scoreboard.map((entry, index) => (
                  <span
                    key={entry.name}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 text-[12px] ${
                      index === 0 && entry.score > 0
                        ? "border-amber-400/40 bg-amber-400/10 text-amber-200"
                        : "border-white/10 bg-white/[0.04]"
                    }`}
                  >
                    <span className="max-w-[240px] truncate font-medium">{entry.name}</span>
                    <span className="rounded-full bg-white/10 px-1.5 text-[10.5px]">{entry.score}</span>
                  </span>
                ))}
              </div>
            </div>

            <MetricTable rows={metrics} columns={columns} />

            {/* Valores por ano */}
            {years.length > 0 && (
              <div className="glass-card gradient-border rounded-2xl p-5">
                <h2 className="font-semibold mb-1">Valor contratado por ano</h2>
                <p className="text-xs text-muted-foreground mb-3">lente {LENS_COPY[lens].label.toLowerCase()}</p>
                <div className="overflow-x-auto rounded-xl border border-white/8">
                  <table className="w-full text-[11.5px] min-w-[520px]">
                    <thead className="bg-white/[0.04] text-[10.5px] uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-3 py-1.5 text-left font-medium">Ano</th>
                        {loaded.map((entry) => (
                          <th key={entry.item.id} className="px-3 py-1.5 text-right font-medium">
                            <span className="line-clamp-1">{entry.item.name}</span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {years.map((year) => {
                        const rowValues = loaded.map(
                          (entry) => entry.byYear.find((item) => item.key === year)?.value ?? 0,
                        );
                        const max = Math.max(1, ...rowValues);
                        return (
                          <tr key={year} className="border-t border-white/6">
                            <td className="px-3 py-1.5 text-muted-foreground">{year}</td>
                            {rowValues.map((value, index) => (
                              <td key={`${year}-${index}`} className="px-3 py-1.5 text-right">
                                <span className="tabular-nums">{value > 0 ? formatFinderValue(value) : "—"}</span>
                                <span className="mt-1 block h-1 rounded-full bg-white/8">
                                  <span
                                    className="block h-1 rounded-full bg-teal-400/70"
                                    style={{ width: `${Math.round((value / max) * 100)}%` }}
                                  />
                                </span>
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* CPV em comum */}
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h2 className="font-semibold mb-1">CPV em comum</h2>
              <p className="text-xs text-muted-foreground mb-3">
                Categorias onde mais do que uma das entidades selecionadas atua
              </p>
              {sharedCpv.length === 0 ? (
                <p className="text-[11.5px] text-muted-foreground/80">
                  Sem códigos CPV partilhados nos principais de cada entidade.
                </p>
              ) : (
                <ul className="space-y-1">
                  {sharedCpv.map((entry) => (
                    <li
                      key={entry.key}
                      className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px]"
                    >
                      <span className="font-medium">{entry.key}</span>
                      <span className="hidden min-w-0 flex-1 truncate text-muted-foreground sm:block">
                        {entry.label}
                      </span>
                      <span className="min-w-0 max-w-[40%] truncate text-muted-foreground/80" title={entry.names.join(" · ")}>
                        {entry.names.join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Contrapartes e CPV por entidade */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="glass-card gradient-border rounded-2xl p-5">
                <h2 className="font-semibold mb-1">Contrapartes principais</h2>
                <p className="text-xs text-muted-foreground mb-3">por entidade, no papel oposto</p>
                <div className="space-y-4">
                  {loaded.map((entry) => (
                    <div key={entry.item.id}>
                      <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground truncate">
                        {entry.item.name}
                      </p>
                      {entry.partners.length === 0 ? (
                        <p className="text-[11.5px] text-muted-foreground/80">Sem contrapartes nos filtros.</p>
                      ) : (
                        <ul className="mt-1 space-y-1">
                          {entry.partners.map((partner) => (
                            <li key={partner.key} className="text-[11.5px]">
                              <div className="flex items-baseline justify-between gap-2">
                                <span className="min-w-0 truncate">{partner.label}</span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                  {partner.count.toLocaleString("pt-PT")} · {formatFinderValue(partner.value)}
                                </span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="glass-card gradient-border rounded-2xl p-5">
                <h2 className="font-semibold mb-1">Top categorias CPV</h2>
                <p className="text-xs text-muted-foreground mb-3">
                  lente {LENS_COPY[lens].label.toLowerCase()}
                </p>
                <div className="space-y-4">
                  {loaded.map((entry) => (
                    <div key={entry.item.id}>
                      <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground truncate">
                        {entry.item.name}
                      </p>
                      {entry.cpv.length === 0 ? (
                        <p className="text-[11.5px] text-muted-foreground/80">Sem CPV nos filtros.</p>
                      ) : (
                        <ul className="mt-1 space-y-1">
                          {entry.cpv.slice(0, 5).map((cpv) => (
                            <li key={cpv.key} className="text-[11.5px]">
                              <div className="flex items-baseline justify-between gap-2">
                                <span className="min-w-0 truncate" title={cpv.label}>
                                  {cpv.key} · {cpv.label}
                                </span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                  {cpv.count.toLocaleString("pt-PT")} · {formatFinderValue(cpv.value)}
                                </span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Ações por entidade */}
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h2 className="font-semibold mb-3">Ações</h2>
              <div className="flex flex-wrap gap-2">
                {loaded.map((entry) => (
                  <button
                    key={entry.item.id}
                    type="button"
                    onClick={() => onOpenEntity(entry.item.id)}
                    className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[11.5px] transition hover:bg-white/[0.1]"
                  >
                    <Building2 size={13} /> Ficha · {entry.item.name}
                  </button>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                {loaded.map((entry) => (
                  <span key={`meta-${entry.item.id}`} className="rounded-lg border border-white/8 bg-white/[0.03] px-2 py-1">
                    <span className="font-medium text-foreground/90">{entry.item.name}</span>
                    {entry.detail.nif ? ` · NIF ${entry.detail.nif}` : ""}
                    {entry.detail.top_adjudicantes?.length
                      ? ` · ${entry.detail.top_adjudicantes.length} adjudicantes`
                      : ""}
                    {entry.detail.top_adjudicatarios?.length
                      ? ` · ${entry.detail.top_adjudicatarios.length} adjudicatários`
                      : ""}
                  </span>
                ))}
              </div>
            </div>

            {/* Contratos recentes de cada entidade (objeto) */}
            <div className="glass-card gradient-border rounded-2xl p-5">
              <h2 className="font-semibold mb-3">Contratos recentes</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {loaded.map((entry) => (
                  <div key={`recent-${entry.item.id}`} className="min-w-0">
                    <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground truncate">
                      {entry.item.name}
                    </p>
                    {(entry.detail.recent_contracts ?? []).length === 0 ? (
                      <p className="text-[11.5px] text-muted-foreground/80">Sem contratos recentes.</p>
                    ) : (
                      <ul className="mt-1 space-y-1">
                        {(entry.detail.recent_contracts ?? []).slice(0, 5).map((contract) => (
                          <li key={String(contract.idcontrato)} className="text-[11.5px]">
                            <span className="min-w-0 block truncate" title={contract.objectoContrato ?? ""}>
                              {(contract.objectoContrato ?? "—").trim() || "—"}
                            </span>
                            <span className="block text-[10.5px] text-muted-foreground">
                              {formatFinderValue(contract.precoContratual ?? contract.PrecoTotalEfetivo)} ·{" "}
                              {contract.Ano ?? ""} · {partyNames(contract.adjudicantes) || "—"}
                              {nifsFromParty(contract.adjudicatarios).length
                                ? ` → ${partyNames(contract.adjudicatarios)}`
                                : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {onOpenDashboard && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onOpenDashboard(lens)}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
                >
                  <ArrowLeft size={13} /> Dashboard de {LENS_COPY[lens].label.toLowerCase()}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
