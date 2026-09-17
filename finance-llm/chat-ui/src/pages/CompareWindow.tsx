/**
 * Janela de comparação: entidades (adjudicantes/adjudicatários) ou contratos
 * lado a lado, com valores, analítica por ano, CPV em comum e diferenças.
 *
 * Pode receber itens do Finder e das fichas, e acrescentar mais aqui mesmo
 * (pesquisa de entidades e de contratos).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Building2,
  FileText,
  GitCompare,
  Loader2,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { getCompanyAnalytics, getContract, getEntityDetail, searchContracts, searchEntities } from "../api";
import type { ContractItem, EntityDetail } from "../types";
import { formatFinderValue } from "../finder";
import {
  MAX_COMPARE,
  compareKey,
  useCompare,
  type CompareItem,
  type CompareKind,
} from "../compare";
import { nifsFromParty, partyNames } from "../pages/EmpresasIQPage";
import { openWindow } from "../windows";

type EntityData = {
  detail: EntityDetail;
  total: number;
  totalValue: number;
  avg: number;
  max: number;
  asAdjudicante: number;
  asAdjudicatario: number;
  adjudicanteContracts: number;
  adjudicatarioContracts: number;
  byYear: { key: string; count: number; value: number }[];
  cpv: { key: string; count: number; value: number }[];
  procedures: { key: string; value: number }[];
};

type ContractData = {
  contract: ContractItem;
  value: number;
  adjudicantes: string;
  adjudicatarios: string;
  cpv: string;
  date?: string;
};

type Loaded = { item: CompareItem; entity?: EntityData; contract?: ContractData };

/* ------------------------------------------------------------- carregamento */

async function loadEntity(item: CompareItem): Promise<Loaded> {
  const [detail, all, adjudicante, adjudicatario] = await Promise.all([
    getEntityDetail(item.id),
    getCompanyAnalytics(item.id, "all").catch(() => null),
    getCompanyAnalytics(item.id, "adjudicante").catch(() => null),
    getCompanyAnalytics(item.id, "adjudicatario").catch(() => null),
  ]);
  const slice = (rows?: { key: string; count: number; total_value?: number }[]) =>
    (rows ?? []).map((row) => ({ key: row.key, count: row.count, value: row.total_value ?? 0 }));
  return {
    item,
    entity: {
      detail,
      // A agregação da plataforma é limitada a 10 000 documentos; a contagem da
      // ficha (índice de entidades) é exata, por isso fica com o maior valor.
      total: Math.max(all?.total_contracts ?? 0, detail.contracts_count ?? 0),
      totalValue: all?.total_value ?? detail.total_value ?? 0,
      avg: all?.avg_value ?? 0,
      max: all?.max_value ?? 0,
      asAdjudicante: adjudicante?.total_value ?? detail.as_adjudicante_value ?? 0,
      asAdjudicatario: adjudicatario?.total_value ?? 0,
      adjudicanteContracts: Math.max(adjudicante?.total_contracts ?? 0, detail.as_adjudicante_count ?? 0),
      adjudicatarioContracts: Math.max(adjudicatario?.total_contracts ?? 0, detail.as_adjudicatario_count ?? 0),
      byYear: slice(all?.by_year).sort((a, b) => b.key.localeCompare(a.key)).slice(0, 6),
      cpv: slice(all?.by_cpv).sort((a, b) => b.value - a.value).slice(0, 8),
      procedures: slice(all?.by_procedure_type).sort((a, b) => b.value - a.value).slice(0, 4),
    },
  };
}

async function loadContract(item: CompareItem): Promise<Loaded> {
  const contract = await getContract(item.id);
  return {
    item,
    contract: {
      contract,
      value: contract.precoContratual ?? contract.PrecoTotalEfetivo ?? 0,
      adjudicantes: partyNames(contract.adjudicantes),
      adjudicatarios: partyNames(contract.adjudicatarios),
      cpv: (contract.cpv ?? []).map((entry) => `${entry.code ?? ""} ${entry.description ?? ""}`.trim()).join(" · "),
      date: contract.dataCelebracaoContrato ?? contract.dataPublicacao,
    },
  };
}

/* ------------------------------------------------------------------- página */

export default function CompareWindow() {
  const { items, kind, add, remove, clear, full } = useCompare();
  const [loaded, setLoaded] = useState<Loaded[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState<CompareKind | null>(null);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<CompareItem[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (items.length === 0) {
      setLoaded([]);
      return;
    }
    setLoading(true);
    setError(null);
    void Promise.all(items.map((item) => (item.kind === "entity" ? loadEntity(item) : loadContract(item))))
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
  }, [items]);

  /* Pesquisa no seletor de itens. */
  useEffect(() => {
    if (!picker) return;
    const term = query.trim();
    if (term.length < 3) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      const run = async () => {
        try {
          if (picker === "entity") {
            const response = await searchEntities({ q: term, size: 8, sort_by: "total_value", sort_order: "desc" });
            if (!cancelled) {
              setOptions(
                response.items.map((entity) => ({
                  kind: "entity" as const,
                  id: entity.nif ?? entity.name,
                  name: entity.name,
                  subtitle: entity.nif ? `NIF ${entity.nif} · ${entity.contracts_count} contratos` : undefined,
                })),
              );
            }
          } else {
            const response = await searchContracts({ q: term, size: 8 });
            if (!cancelled) {
              setOptions(
                response.items.map((contract) => ({
                  kind: "contract" as const,
                  id: String(contract.idcontrato ?? ""),
                  name: contract.objectoContrato?.trim() || `Contrato ${contract.idcontrato ?? ""}`,
                  subtitle: `${formatFinderValue(contract.precoContratual ?? contract.PrecoTotalEfetivo)} · ${contract.Ano ?? ""}`,
                })),
              );
            }
          }
        } catch {
          if (!cancelled) setOptions([]);
        } finally {
          if (!cancelled) setSearching(false);
        }
      };
      void run();
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [picker, query]);

  const addAndClose = useCallback(
    (item: CompareItem) => {
      add([item]);
      setPicker(null);
      setQuery("");
      setOptions([]);
    },
    [add],
  );

  const years = useMemo(() => {
    const set = new Set<string>();
    for (const entry of loaded) for (const year of entry.entity?.byYear ?? []) set.add(year.key);
    return [...set].sort((a, b) => b.localeCompare(a)).slice(0, 6);
  }, [loaded]);

  const sharedCpv = useMemo(() => {
    const counts = new Map<string, { label: string; who: Set<string> }>();
    for (const entry of loaded) {
      for (const cpv of entry.entity?.cpv ?? []) {
        const current = counts.get(cpv.key) ?? { label: cpv.key, who: new Set<string>() };
        current.who.add(entry.item.name);
        counts.set(cpv.key, current);
      }
    }
    return [...counts.entries()]
      .filter(([, value]) => value.who.size > 1)
      .map(([key, value]) => ({ key, names: [...value.who] }))
      .slice(0, 8);
  }, [loaded]);

  const entities = loaded.filter((entry) => entry.entity);
  const contracts = loaded.filter((entry) => entry.contract);
  const isEntityComparison = kind !== "contract";

  return (
    <div className="finder-shell bg-background text-foreground" data-in-window="true">
      <header className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.02] px-3 py-2 backdrop-blur-xl">
        <span className="grid h-6 w-6 place-items-center rounded-[6px] bg-gradient-to-br from-violet-300 via-indigo-500 to-blue-600 text-white shadow-sm">
          <GitCompare size={13} />
        </span>
        <span className="text-[13px] font-semibold">
          {items.length === 0
            ? "Comparar"
            : `Comparar ${items.length} ${isEntityComparison ? (items.length === 1 ? "entidade" : "entidades") : items.length === 1 ? "contrato" : "contratos"}`}
        </span>
        {items.length > 0 && (
          <button
            type="button"
            onClick={clear}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            Limpar
          </button>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            disabled={full}
            onClick={() => setPicker(isEntityComparison ? "entity" : "contract")}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1] disabled:opacity-40"
          >
            <Plus size={13} /> Adicionar {isEntityComparison ? "entidade" : "contrato"}
          </button>
          {full && <span className="text-[10.5px] text-muted-foreground">máx. {MAX_COMPARE}</span>}
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-rose-400/20 bg-rose-400/10 px-4 py-1.5 text-[12px] text-rose-200">
          <AlertCircle size={13} /> {error}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <GitCompare size={26} className="text-muted-foreground/60" />
            <p className="text-sm text-muted-foreground">Ainda não há nada para comparar.</p>
            <p className="max-w-md text-[11.5px] text-muted-foreground/80">
              Selecione entidades ou contratos no <strong>Finder</strong> (Ctrl/⌘+clique e depois «Comparar»), use o
              botão «Comparar» numa ficha, ou acrescente aqui com «Adicionar».
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => setPicker("entity")}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
              >
                <Building2 size={13} /> Comparar entidades
              </button>
              <button
                type="button"
                onClick={() => setPicker("contract")}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
              >
                <FileText size={13} /> Comparar contratos
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Itens comparados */}
            <div className="flex flex-wrap gap-2">
              {items.map((item) => (
                <span
                  key={compareKey(item)}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px]"
                >
                  <span className="max-w-[260px] truncate font-medium">{item.name}</span>
                  {item.subtitle && (
                    <span className="hidden max-w-[180px] truncate text-[10.5px] text-muted-foreground sm:inline">
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
            </div>

            {loading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <Loader2 size={15} className="animate-spin" /> A carregar dados…
              </div>
            ) : isEntityComparison ? (
              <EntityComparison loaded={entities} years={years} sharedCpv={sharedCpv} />
            ) : (
              <ContractComparison loaded={contracts} />
            )}
          </>
        )}
      </div>

      {/* Seletor */}
      {picker && (
        <div className="absolute inset-0 z-40 flex items-start justify-center bg-[#03080b]/55 p-4 pt-10 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-white/12 bg-[#14161b]/97 p-4 shadow-2xl">
            <div className="flex items-center gap-2">
              <p className="text-[13px] font-semibold">
                Adicionar {picker === "entity" ? "entidade" : "contrato"}
              </p>
              <button
                type="button"
                onClick={() => setPicker(null)}
                aria-label="Fechar"
                className="ml-auto rounded p-1 text-muted-foreground transition hover:text-foreground"
              >
                <X size={14} />
              </button>
            </div>
            <div className="relative mt-3">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={picker === "entity" ? "Nome ou NIF da entidade…" : "Objeto, NIF ou nº do contrato…"}
                className="h-8 w-full rounded-[7px] border border-white/8 bg-white/[0.05] pl-8 pr-3 text-[12.5px] outline-none focus:border-teal-300/40"
              />
              {searching && <Loader2 size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />}
            </div>
            {query.trim().length < 3 ? (
              <p className="mt-2 text-[11.5px] text-muted-foreground">Escreva pelo menos 3 caracteres.</p>
            ) : (
              <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto">
                {options.length === 0 && !searching && (
                  <li className="px-1 py-2 text-[11.5px] text-muted-foreground">Sem resultados.</li>
                )}
                {options.map((option) => (
                  <li key={compareKey(option)}>
                    <button
                      type="button"
                      onClick={() => addAndClose(option)}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition hover:bg-white/8"
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
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- comparações */

function best(list: number[], higher = true): number | null {
  if (list.length < 2 || list.some((value) => !Number.isFinite(value))) return null;
  return higher ? Math.max(...list) : Math.min(...list);
}

/** Tabela de métricas com destaque do melhor valor e barra proporcional. */
function MetricTable({
  rows,
  columns,
}: {
  rows: { label: string; values: number[]; format: (value: number) => string; higher?: boolean }[];
  columns: string[];
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/8">
      <table className="w-full text-[12px]">
        <thead className="bg-white/[0.04] text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 text-left font-medium">Métrica</th>
            {columns.map((column) => (
              <th key={column} className="px-3 py-1.5 text-right font-medium">
                <span className="line-clamp-1">{column}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const winner = best(row.values, row.higher !== false);
            const max = Math.max(1, ...row.values.map((value) => Math.abs(value)));
            return (
              <tr key={row.label} className="border-t border-white/6">
                <td className="px-3 py-1.5 text-muted-foreground">{row.label}</td>
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

function EntityComparison({
  loaded,
  years,
  sharedCpv,
}: {
  loaded: Loaded[];
  years: string[];
  sharedCpv: { key: string; names: string[] }[];
}) {
  const columns = loaded.map((entry) => entry.item.name);
  const withData = loaded.filter((entry): entry is Loaded & { entity: EntityData } => Boolean(entry.entity));

  return (
    <div className="mt-4 space-y-5">
      <MetricTable
        columns={columns}
        rows={[
          { label: "Contratos", values: withData.map((e) => e.entity.total), format: (v) => v.toLocaleString("pt-PT") },
          { label: "Valor contratado", values: withData.map((e) => e.entity.totalValue), format: formatFinderValue },
          { label: "Valor médio / contrato", values: withData.map((e) => e.entity.avg), format: formatFinderValue },
          { label: "Maior contrato", values: withData.map((e) => e.entity.max), format: formatFinderValue },
          {
            label: "Como adjudicante",
            values: withData.map((e) => e.entity.asAdjudicante),
            format: formatFinderValue,
          },
          {
            label: "Como adjudicatário",
            values: withData.map((e) => e.entity.asAdjudicatario),
            format: formatFinderValue,
          },
          {
            label: "Contratos como adjudicante",
            values: withData.map((e) => e.entity.adjudicanteContracts),
            format: (v) => v.toLocaleString("pt-PT"),
          },
          {
            label: "Contratos como adjudicatário",
            values: withData.map((e) => e.entity.adjudicatarioContracts),
            format: (v) => v.toLocaleString("pt-PT"),
          },
          { label: "Marcas INPI", values: withData.map((e) => e.entity.detail.trademarks_total ?? 0), format: (v) => String(v) },
          { label: "Firmas RNPC", values: withData.map((e) => e.entity.detail.firmas_total ?? 0), format: (v) => String(v) },
        ]}
      />

      {/* Valores por ano (matriz com barras) */}
      {years.length > 0 && withData.length > 0 && (
        <div>
          <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Valor contratado por ano</p>
          <div className="mt-1 overflow-hidden rounded-xl border border-white/8">
            <table className="w-full text-[11.5px]">
              <thead className="bg-white/[0.04] text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium">Ano</th>
                  {withData.map((entry) => (
                    <th key={entry.item.id} className="px-3 py-1.5 text-right font-medium">
                      <span className="line-clamp-1">{entry.item.name}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {years.map((year) => {
                  const rowValues = withData.map(
                    (entry) => entry.entity.byYear.find((item) => item.key === year)?.value ?? 0,
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
      <div>
        <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">CPV em comum</p>
        {sharedCpv.length === 0 ? (
          <p className="mt-1 text-[11.5px] text-muted-foreground/80">
            Sem códigos CPV partilhados entre as entidades selecionadas (nos principais de cada uma).
          </p>
        ) : (
          <ul className="mt-1 space-y-1">
            {sharedCpv.map((entry) => (
              <li key={entry.key} className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px]">
                <span className="font-medium">{entry.key}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{entry.names.join(" · ")}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Maiores CPV de cada entidade */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {withData.map((entry) => (
          <div key={entry.item.id}>
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
              top CPV · {entry.item.name}
            </p>
            <ul className="mt-1 space-y-1">
              {entry.entity.cpv.slice(0, 5).map((cpv) => (
                <li key={cpv.key} className="text-[11.5px]">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate">{cpv.key}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {cpv.count.toLocaleString("pt-PT")} · {formatFinderValue(cpv.value)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContractComparison({ loaded }: { loaded: Loaded[] }) {
  const withData = loaded.filter((entry): entry is Loaded & { contract: ContractData } => Boolean(entry.contract));
  const columns = withData.map((entry) => entry.item.name);
  const rows: { label: string; values: number[]; format: (value: number) => string }[] = [
    { label: "Valor contratual", values: withData.map((e) => e.contract.value), format: formatFinderValue },
  ];

  const text = (label: string, pick: (data: ContractData) => string) => {
    const values = withData.map((entry) => pick(entry.contract));
    // Linhas sem informação em nenhuma das colunas não ocupam espaço.
    if (values.every((value) => !value || value === "—")) return null;
    return (
      <div key={label} className="grid grid-cols-[160px_1fr] gap-2 border-t border-white/6 py-1.5 text-[11.5px]">
        <span className="text-muted-foreground">{label}</span>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {values.map((value, index) => (
            <span key={withData[index].item.id} className="min-w-0 truncate" title={value}>
              {value || "—"}
            </span>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="mt-4 space-y-5">
      <MetricTable columns={columns} rows={rows} />

      <div className="overflow-hidden rounded-xl border border-white/8 px-3 py-1">
        {text("Objeto", (data) => data.contract.objectoContrato?.trim() || "—")}
        {text("Nº", (data) => String(data.contract.idcontrato ?? ""))}
        {text("Data", (data) => (data.date ? new Date(data.date).toLocaleDateString("pt-PT") : "—"))}
        {text("Tipo de contrato", (data) => data.contract.tipoContrato ?? "—")}
        {text("Procedimento", (data) => data.contract.tipoprocedimento ?? "—")}
        {text("Adjudicantes", (data) => data.adjudicantes)}
        {text("Adjudicatários", (data) => data.adjudicatarios)}
        {text("CPV", (data) => data.cpv)}
        {text("Local de execução", (data) => data.contract.localExecucao ?? "—")}
        {text("Preço base", (data) => formatFinderValue(data.contract.precoBaseProcedimento))}
        {text("Concorrentes", (data) => (Array.isArray(data.contract.concorrentes) ? data.contract.concorrentes.join(", ") : data.contract.concorrentes ?? "—"))}
        {text("Partes (NIF)", (data) =>
          [...nifsFromParty(data.contract.adjudicantes), ...nifsFromParty(data.contract.adjudicatarios)].join(", ") || "—")}
      </div>

      {/* Abrir cada contrato numa janela */}
      <div className="flex flex-wrap gap-2">
        {withData.map((entry) => (
          <button
            key={entry.item.id}
            type="button"
            onClick={() =>
              openWindow(`contract-detail:${entry.item.id}`, undefined, { title: "Ficha do contrato" })
            }
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[11.5px] transition hover:bg-white/[0.1]"
          >
            <FileText size={13} /> Abrir ficha · {String(entry.contract.contract.idcontrato ?? "")}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Botão «Comparar» reutilizável (Finder e fichas). */
export function CompareButton({ item, label = "Comparar" }: { item: CompareItem; label?: string }) {
  const { has, toggle } = useCompare();
  const active = has(item);
  return (
    <button
      type="button"
      onClick={() => toggle(item)}
      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
    >
      {active ? <Trash2 size={13} /> : <GitCompare size={13} />}
      {active ? "Na comparação" : label}
    </button>
  );
}
