/**
 * «Ver todos os contratos» de uma entidade.
 *
 * Janela própria (`entity-contracts:<NIF>`) com a lista completa — pesquisa,
 * ano, ordenação e paginação no servidor (`/contracts/search` com `nif`) — para
 * não ficar limitada aos 10 contratos recentes da ficha.
 *
 * O painel é reutilizado dentro da modal do EmpresasIQ quando o modo janelas
 * está desligado (telemóvel/modo página).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, FileText, GitCompare, Loader2, Search } from "lucide-react";
import { getCompanyDetail, getContractStatus, searchContracts } from "../api";
import type { ContractItem, ContractParty, ContractSearchRequest } from "../types";
import { formatFinderValue } from "../finder";
import { useCompare } from "../compare";
import { openWindow } from "../windows";

const PAGE_SIZE = 50;

type SortOption = {
  value: NonNullable<ContractSearchRequest["sort_by"]>;
  label: string;
};

const SORTS: SortOption[] = [
  { value: "dataPublicacao", label: "Data de publicação" },
  { value: "dataCelebracaoContrato", label: "Data de celebração" },
  { value: "precoContratual", label: "Valor" },
  { value: "objectoContrato", label: "Objeto" },
  { value: "adjudicatarios", label: "Adjudicatário" },
];

/* ----------------------------------------------------------- utilidades */

function partyList(party?: ContractParty | ContractParty[]): ContractParty[] {
  if (!party) return [];
  return Array.isArray(party) ? party : [party];
}

/** NIF de cada parte (vivem em `party.parsed[]`, não em `party.nif`). */
function partyNifs(party?: ContractParty | ContractParty[]): string[] {
  return partyList(party).flatMap((entry) => (entry.parsed ?? []).map((parsed) => parsed.nif).filter(Boolean) as string[]);
}

function partyLabel(party?: ContractParty | ContractParty[]): string {
  const names = partyList(party).flatMap((entry) => (entry.parsed ?? []).map((parsed) => parsed.nome).filter(Boolean));
  if (names.length > 0) return names.join(", ");
  const raw = partyList(party)
    .map((entry) => entry.raw)
    .filter(Boolean);
  return raw.length > 0 ? raw.join(", ") : "—";
}

function contractValue(contract: ContractItem): number {
  return contract.precoContratual ?? contract.PrecoTotalEfetivo ?? 0;
}

function contractDate(contract: ContractItem): string {
  const raw = contract.dataCelebracaoContrato ?? contract.dataPublicacao;
  if (!raw) return "—";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString("pt-PT");
}

/* --------------------------------------------------------------- painel */

export function EntityContractsPanel({ nif, onBack }: { nif: string; onBack?: () => void }) {
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [sortBy, setSortBy] = useState<SortOption["value"]>("dataPublicacao");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [rows, setRows] = useState<ContractItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const { add: addToCompare } = useCompare();
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  /* Nome da entidade e anos disponíveis (o filtro usa todos os anos indexados). */
  useEffect(() => {
    let cancelled = false;
    getCompanyDetail(nif)
      .then((detail) => {
        if (!cancelled) setName(detail.name ?? "");
      })
      .catch(() => {
        /* o nome é acessório: a lista continua utilizável */
      });
    getContractStatus()
      .then((status) => {
        if (!cancelled) setYears([...(status.years ?? [])].sort((a, b) => b - a));
      })
      .catch(() => {
        /* sem anos o filtro fica só com «Todos os anos» */
      });
    return () => {
      cancelled = true;
    };
  }, [nif]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [query]);

  const buildRequest = useCallback(
    (from: number): ContractSearchRequest => ({
      nif,
      q: debounced || undefined,
      year: year === "" ? undefined : year,
      sort_by: debounced ? "relevance" : sortBy,
      sort_order: order,
      from,
      size: PAGE_SIZE,
    }),
    [debounced, nif, order, sortBy, year],
  );

  /* Primeira página: recarrega sempre que muda um filtro. */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    searchContracts(buildRequest(0))
      .then((response) => {
        if (cancelled) return;
        setRows(response.items ?? []);
        setTotal(response.total ?? 0);
        if (response.error) setError(response.error);
      })
      .catch((caught) => {
        if (cancelled) return;
        setRows([]);
        setTotal(0);
        setError(caught instanceof Error ? caught.message : "Erro ao carregar contratos.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [buildRequest]);

  const hasMore = rows.length < total;

  const loadMore = useCallback(() => {
    if (loading || loadingMore || !hasMore) return;
    setLoadingMore(true);
    searchContracts(buildRequest(rows.length))
      .then((response) => setRows((previous) => [...previous, ...(response.items ?? [])]))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Erro ao carregar mais contratos."))
      .finally(() => setLoadingMore(false));
  }, [buildRequest, hasMore, loading, loadingMore, rows.length]);

  /* Scroll infinito (o botão «Carregar mais» fica como alternativa). */
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore();
      },
      { rootMargin: "240px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [loadMore]);

  const loadedValue = useMemo(() => rows.reduce((acc, row) => acc + contractValue(row), 0), [rows]);

  const roleOf = useCallback(
    (contract: ContractItem) => {
      const roles: string[] = [];
      if (partyNifs(contract.adjudicantes).includes(nif)) roles.push("Adjudicante");
      if (partyNifs(contract.adjudicatarios).includes(nif)) roles.push("Adjudicatário");
      return roles.length > 0 ? roles.join(" · ") : "—";
    },
    [nif],
  );

  const exportCsv = useCallback(() => {
    const header = ["Nº", "Objeto", "Papel", "Adjudicantes", "Adjudicatários", "Data", "Valor", "CPV"];
    const csvRows = rows.map((contract) => [
      String(contract.idcontrato ?? ""),
      contract.objectoContrato ?? "",
      roleOf(contract),
      partyLabel(contract.adjudicantes),
      partyLabel(contract.adjudicatarios),
      contractDate(contract),
      String(contractValue(contract)),
      (contract.cpv ?? []).map((entry) => entry.code).filter(Boolean).join(" "),
    ]);
    const csv = [header, ...csvRows]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(";"))
      .join("\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `contratos-${nif}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [nif, roleOf, rows]);

  const openContract = (contract: ContractItem) => {
    const id = String(contract.idcontrato ?? "");
    if (id) openWindow(`contract-detail:${id}`, undefined, { title: "Ficha do contrato" });
  };

  return (
    <div className="flex h-full min-h-0 flex-col text-foreground">
      {/* Barra de ferramentas */}
      <header className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.02] px-3 py-2 backdrop-blur-xl">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1]"
          >
            Voltar
          </button>
        )}
        <div className="min-w-0">
          <p className="truncate text-[12.5px] font-medium" title={name || nif}>
            {name || `Entidade ${nif}`}
          </p>
          <p className="text-[10.5px] text-muted-foreground">
            NIF {nif} · {loading ? "a carregar…" : `${total.toLocaleString("pt-PT")} contratos`}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <label className="relative flex items-center">
            <Search size={12} className="pointer-events-none absolute left-2 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Pesquisar no objeto…"
              className="w-44 rounded-lg border border-white/10 bg-white/[0.04] py-1 pl-7 pr-2 text-[11.5px] outline-none transition focus:border-teal-400/40 @2xl:w-56"
            />
          </label>
          <select
            value={year}
            onChange={(event) => setYear(event.target.value === "" ? "" : Number(event.target.value))}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none"
          >
            <option value="">Todos os anos</option>
            {years.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as SortOption["value"])}
            disabled={Boolean(debounced)}
            title={debounced ? "Com pesquisa de texto a ordem é por relevância" : "Ordenar por"}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none disabled:opacity-50"
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setOrder((value) => (value === "desc" ? "asc" : "desc"))}
            title={order === "desc" ? "Descendente" : "Ascendente"}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
          >
            {order === "desc" ? "↓" : "↑"}
          </button>
          <button
            type="button"
            onClick={exportCsv}
            disabled={rows.length === 0}
            title="Exportar CSV"
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09] disabled:opacity-40"
          >
            <Download size={12} /> CSV
          </button>
        </div>
      </header>

      {error && (
        <p className="shrink-0 border-b border-rose-400/20 bg-rose-400/10 px-3 py-1.5 text-[11.5px] text-rose-200">
          {error}
        </p>
      )}

      {/* Tabela */}
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && rows.length === 0 ? (
          <p className="flex items-center justify-center gap-2 py-16 text-[12px] text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> A carregar contratos…
          </p>
        ) : rows.length === 0 ? (
          <p className="py-16 text-center text-[12px] text-muted-foreground">
            Sem contratos para os filtros escolhidos.
          </p>
        ) : (
          <table className="w-full border-collapse text-[12px]">
            <thead className="sticky top-0 z-10 bg-[#12141a]/95 text-[10.5px] uppercase tracking-wide text-muted-foreground backdrop-blur">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium">Nº</th>
                <th className="px-3 py-1.5 text-left font-medium">Objeto</th>
                <th className="hidden px-3 py-1.5 text-left font-medium @3xl:table-cell">Papel</th>
                <th className="hidden px-3 py-1.5 text-left font-medium @4xl:table-cell">Adjudicatários</th>
                <th className="px-3 py-1.5 text-right font-medium">Data</th>
                <th className="px-3 py-1.5 text-right font-medium">Valor</th>
                <th className="w-24 px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((contract) => {
                const rowKey = String(contract.idcontrato ?? contract.doc_id ?? Math.random());
                const objecto = contract.objectoContrato?.trim() || "Sem descrição";
                return (
                  <tr
                    key={rowKey}
                    className="cursor-pointer border-t border-white/6 transition hover:bg-white/[0.04]"
                    onClick={() => openContract(contract)}
                  >
                    <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                      {String(contract.idcontrato ?? "—")}
                    </td>
                    <td className="max-w-0 px-3 py-1.5">
                      <span className="block truncate" title={objecto}>
                        {objecto}
                      </span>
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-1.5 text-muted-foreground @3xl:table-cell">
                      {roleOf(contract)}
                    </td>
                    <td className="hidden max-w-0 px-3 py-1.5 text-muted-foreground @4xl:table-cell">
                      <span className="block truncate" title={partyLabel(contract.adjudicatarios)}>
                        {partyLabel(contract.adjudicatarios)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right text-muted-foreground">
                      {contractDate(contract)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
                      {formatFinderValue(contractValue(contract))}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <button
                        type="button"
                        title="Adicionar à comparação"
                        onClick={(event) => {
                          event.stopPropagation();
                          addToCompare([
                            { kind: "contract", id: String(contract.idcontrato ?? ""), name: objecto, subtitle: contract.Ano ? String(contract.Ano) : undefined },
                          ]);
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] p-1 text-muted-foreground transition hover:text-teal-200"
                      >
                        <GitCompare size={12} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div ref={sentinelRef} className="h-10" />
        {loadingMore && (
          <p className="flex items-center justify-center gap-2 py-3 text-[11.5px] text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> A carregar mais…
          </p>
        )}
      </div>

      {/* Rodapé */}
      <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-white/8 px-3 py-1.5 text-[11px] text-muted-foreground">
        <FileText size={12} />
        <span>
          {rows.length.toLocaleString("pt-PT")} de {total.toLocaleString("pt-PT")} contratos
        </span>
        <span className="opacity-60">· valor dos carregados: {formatFinderValue(loadedValue)}</span>
        {hasMore && (
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="ml-auto rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 transition hover:bg-white/[0.1] disabled:opacity-40"
          >
            Carregar mais
          </button>
        )}
      </footer>
    </div>
  );
}

/* ----------------------------------------------------------- janela */

/** Janela «Contratos da entidade» (vista `entity-contracts:<NIF>`). */
export default function EntityContractsWindow({ nif }: { nif: string }) {
  return (
    <div className="finder-shell bg-background text-foreground" data-in-window="true">
      <EntityContractsPanel nif={nif} />
    </div>
  );
}

/** Botão «Ver todos» reutilizável (fichas e Quick Look). */
export function SeeAllContractsButton({
  nif,
  name,
  total,
  compact,
}: {
  nif: string;
  name?: string;
  total?: number;
  compact?: boolean;
}) {
  const label = total && total > 0 ? `Ver todos (${total.toLocaleString("pt-PT")})` : "Ver todos";
  return (
    <button
      type="button"
      onClick={() =>
        openWindow(`entity-contracts:${nif}`, undefined, {
          title: name ? `Contratos · ${name}` : "Contratos da entidade",
          rect: { width: 1100, height: 720 },
        })
      }
      title="Abrir a lista completa de contratos desta entidade"
      className={[
        "inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] transition hover:bg-white/[0.1]",
        compact ? "px-2 py-1 text-[11.5px]" : "px-3 py-1.5 text-[12px]",
      ].join(" ")}
    >
      <FileText size={compact ? 12 : 13} /> {label}
    </button>
  );
}

/** Botão «Ver todos» reutilizável (fichas e Quick Look). */
