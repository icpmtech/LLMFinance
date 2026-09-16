import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Search,
} from "lucide-react";
import { searchContracts, getContractYears } from "../api";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import type {
  ContractItem,
  ContractSearchRequest,
  ContractSearchResponse,
} from "../types";

const PAGE_SIZES = [10, 20, 50, 100];

interface ContractsListPageProps {
  onSwitchView?: () => void;
}

function formatCurrency(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 2,
  });
}

function formatDate(value?: string): string {
  if (!value) return "—";
  const [y, m, d] = value.split("T")[0].split("-");
  if (!y || !m || !d) return value;
  return `${d}/${m}/${y}`;
}

function partyNames(item: ContractItem | undefined, key: "adjudicantes" | "adjudicatarios"): string {
  if (!item) return "—";
  const party = item[key];
  if (!party) return "—";
  const parsed = Array.isArray(party) ? party.flatMap((p) => p.parsed) : party.parsed;
  if (!parsed?.length) return "—";
  return parsed.map((p) => p.nome).filter(Boolean).join(", ");
}

function contractType(item?: ContractItem): string {
  if (!item?.tipoContrato) return "—";
  return Array.isArray(item.tipoContrato)
    ? item.tipoContrato.join(", ")
    : String(item.tipoContrato);
}

type SortableColumn =
  | Exclude<ContractSearchRequest["sort_by"], undefined>
  | "idcontrato";

const COLUMNS: {
  key: SortableColumn;
  label: string;
  width?: string;
}[] = [
  { key: "dataPublicacao", label: "Data", width: "w-28" },
  { key: "adjudicantes", label: "Entidade Adjudicante" },
  { key: "adjudicatarios", label: "Entidade Adjudicatária" },
  { key: "objectoContrato", label: "Objeto" },
  { key: "tipoContrato", label: "Tipo", width: "w-36" },
  { key: "precoContratual", label: "Valor (€)", width: "w-32" },
  { key: "idcontrato", label: "Nº Contrato", width: "w-36" },
];

export function ContractsListPage({ onSwitchView }: ContractsListPageProps) {
  const [items, setItems] = useState<ContractItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [years, setYears] = useState<number[]>([]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<ContractSearchRequest["sort_by"]>("dataPublicacao");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [q, setQ] = useState("");
  const [year, setYear] = useState<string>("");
  const [entity, setEntity] = useState("");
  const [minPrice, setMinPrice] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState<string>("");

  const request = useMemo<ContractSearchRequest>(() => {
    const payload: ContractSearchRequest = {
      q: q.trim() || undefined,
      year: year ? Number(year) : undefined,
      entity: entity.trim() || undefined,
      min_price: minPrice ? Number(minPrice) : undefined,
      max_price: maxPrice ? Number(maxPrice) : undefined,
      size: pageSize,
      from: (page - 1) * pageSize,
      sort_by: (sortBy as SortableColumn) === "idcontrato" ? undefined : sortBy,
      sort_order: sortOrder,
    };
    return payload;
  }, [q, year, entity, minPrice, maxPrice, pageSize, page, sortBy, sortOrder]);

  useEffect(() => {
    getContractYears()
      .then((res) => setYears(res.indexed.map((y) => y.year).sort((a, b) => b - a)))
      .catch(() => setYears([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    searchContracts(request)
      .then((res: ContractSearchResponse) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [request]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function handleSort(key: SortableColumn) {
    if (!key) return;
    if (key === "idcontrato") {
      // Elasticsearch does not sort by idcontrato directly; sort by doc_id instead.
      const actual: ContractSearchRequest["sort_by"] = "relevance";
      setSortBy(actual);
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else if (sortBy === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder(key === "dataPublicacao" ? "desc" : "asc");
    }
    setPage(1);
  }

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
  }

  return (
    <div className="min-h-screen bg-background text-foreground p-4 md:p-6 lg:p-8">
      <div className="max-w-[1600px] mx-auto space-y-6">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
              <FileText size={20} />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-semibold">Contratos Públicos</h1>
              <p className="text-sm text-muted-foreground">
                Pesquisa, ordenação e paginação de contratos via servidor
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onSwitchView}>
              Voltar
            </Button>
          </div>
        </header>

        <Card>
          <form onSubmit={applyFilters} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Texto livre</label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 text-muted-foreground" size={16} />
                <input
                  type="text"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Objeto, entidade, CPV..."
                  className="w-full rounded-md border border-input bg-background pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Entidade</label>
              <input
                type="text"
                value={entity}
                onChange={(e) => setEntity(e.target.value)}
                placeholder="Adjudicante ou adjudicatária"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Ano</label>
              <select
                value={year}
                onChange={(e) => { setYear(e.target.value); setPage(1); }}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">Todos</option>
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Valor mín (€)</label>
              <input
                type="number"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                placeholder="0"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Valor máx (€)</label>
              <input
                type="number"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder="∞"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="lg:col-span-5 flex items-center justify-end gap-2">
              <Button type="submit" disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Aplicar filtros
              </Button>
            </div>
          </form>
        </Card>

        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-muted-foreground">
                <tr>
                  {COLUMNS.map((col) => {
                    const active = sortBy === col.key;
                    return (
                      <th
                        key={col.key}
                        className={`px-4 py-3 text-left font-medium cursor-pointer select-none hover:text-foreground ${col.width || ""}`}
                        onClick={() => handleSort(col.key)}
                      >
                        <div className="flex items-center gap-1">
                          {col.label}
                          <span className="inline-flex flex-col leading-none">
                            {active ? (
                              sortOrder === "asc" ? (
                                <ArrowUp size={14} className="text-primary" />
                              ) : (
                                <ArrowDown size={14} className="text-primary" />
                              )
                            ) : (
                              <>
                                <ArrowUp size={10} className="opacity-30" />
                                <ArrowDown size={10} className="opacity-30" />
                              </>
                            )}
                          </span>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {loading && items.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-muted-foreground">
                      <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin" />
                      A carregar contratos...
                    </td>
                  </tr>
                ) : error ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-destructive">
                      Erro: {error}
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-muted-foreground">
                      Nenhum contrato encontrado.
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={item.doc_id || item.idcontrato || `${item.nAnuncio}-${item.dataPublicacao}`} className="border-b border-border/60 hover:bg-muted/30">
                      <td className="px-4 py-3 whitespace-nowrap">{formatDate(item.dataPublicacao)}</td>
                      <td className="px-4 py-3 max-w-xs truncate" title={partyNames(item, "adjudicantes")}>
                        {partyNames(item, "adjudicantes")}
                      </td>
                      <td className="px-4 py-3 max-w-xs truncate" title={partyNames(item, "adjudicatarios")}>
                        {partyNames(item, "adjudicatarios")}
                      </td>
                      <td className="px-4 py-3 max-w-md truncate" title={item.objectoContrato}>
                        {item.objectoContrato || "—"}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">{contractType(item)}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-right tabular-nums">
                        {formatCurrency(item.precoContratual)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                        {item.idcontrato || "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>
              {total.toLocaleString("pt-PT")} resultado{total !== 1 ? "s" : ""}
            </span>
            <span>|</span>
            <label className="flex items-center gap-2">
              Mostrar
              <select
                value={pageSize}
                onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
                className="rounded-md border border-input bg-background px-2 py-1 text-sm"
              >
                {PAGE_SIZES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              por página
            </label>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
            >
              <ChevronLeft size={16} />
            </Button>
            <span className="text-sm">
              Página <span className="font-medium">{page}</span> de{" "}
              <span className="font-medium">{totalPages}</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
            >
              <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
