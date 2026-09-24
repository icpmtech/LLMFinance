/**
 * Peças partilhadas do PessoasIQ.
 *
 * Vive num módulo próprio (e não dentro da página) porque o grafo passou a
 * poder abrir-se numa **janela independente** — a página e a janela usam
 * exatamente os mesmos cartões, legenda, resumo de nó e conversão do grafo,
 * sem duplicar código nem criar importações circulares.
 */
import { Building2, Check, Copy, Loader2, PersonStanding, Search, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { autocompletePeople, generateNodeSummary, getNodeSummary, getPeopleFilters, searchPeople } from "../../api";
import { openWindow, estimateWorkspace, MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH } from "../../windows";
import type { GraphMetric, StudioEdge, StudioGraph, StudioNode } from "../graph/graphStudio";
import type {
  NodeSummaryResponse,
  PeopleAutocompleteItem,
  PeopleFiltersResponse,
  PeopleGraphNode,
  PeopleGraphResponse,
  Person,
} from "../../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatDate(date?: string | null): string {
  if (!date) return "—";
  try {
    return new Date(date).toLocaleDateString("pt-PT");
  } catch {
    return date;
  }
}

export function roleLabel(role?: string | null, event?: string | null): string {
  if (!role && !event) return "Ligação societária";
  return [event, role].filter(Boolean).join(" · ");
}

// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

export function Card({
  children,
  className = "",
  glow,
  onClick,
}: {
  children: React.ReactNode;
  className?: string;
  glow?: "teal" | "rose" | "blue";
  onClick?: () => void;
}) {
  const glowClass = glow ? `glow-${glow}` : "";
  const clickable = onClick ? "cursor-pointer hover:bg-white/[0.03] transition" : "";
  const baseClass = `glass-card gradient-border rounded-2xl p-5 min-w-0 text-left ${glowClass} ${clickable} ${className}`;
  if (onClick) {
    return (
      <div role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick()} className={baseClass}>
        {children}
      </div>
    );
  }
  return <div className={baseClass}>{children}</div>;
}

export function Loading({ message = "A carregar…" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
      <Loader2 size={32} className="animate-spin mb-3" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function EmptyState({ message, icon: Icon }: { message: string; icon?: React.ElementType }) {
  const I = Icon || Search;
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <I size={36} className="mb-3 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

/** Legenda das formas do grafo: cada tipo de nó tem forma (e cor) própria. */
export function NodeShapeLegend({ compact = false }: { compact?: boolean }) {
  const items = [
    { glyph: "●", label: "Pessoa", color: "#fb7185" },
    { glyph: "■", label: "Empresa", color: "#38bdf8" },
    { glyph: "◆", label: "Entidade", color: "#a78bfa" },
    { glyph: "⬢", label: "Site/perfil", color: "#34d399" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      {!compact && <span className="text-muted-foreground">Formas:</span>}
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span className="text-base leading-none" style={{ color: item.color }}>
            {item.glyph}
          </span>
          {item.label}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tipos e constantes da pesquisa/grafo
// ---------------------------------------------------------------------------

export type GraphMode = "person" | "company" | "combined";
export type NodeKindFilter = "all" | "person" | "company" | "entity";
export type EdgeKindFilter = "all" | "role" | "contract";
export type PersonTypeFilter = "all" | "person" | "company";
export type PeopleSort = "relevance" | "roles" | "recent" | "name";

export const SORT_LABELS: Record<PeopleSort, string> = {
  relevance: "Mais relevantes",
  roles: "Mais cargos",
  recent: "Mais recentes",
  name: "Nome (A-Z)",
};

export const SEARCH_PAGE_SIZE = 24;

export const GRAPH_MODE_LABELS: Record<GraphMode, string> = {
  person: "Pessoa",
  company: "Empresa",
  combined: "Combinado",
};

// ---------------------------------------------------------------------------
// Janela própria do grafo (`pessoas-graph:*`)
// ---------------------------------------------------------------------------

export type GraphTarget = { mode: GraphMode; nif: string };

/** Codifica o alvo no id da janela: `pessoas-graph:p:226815340`. */
export function graphWindowView(mode: GraphMode, nif: string): string {
  const code = mode === "person" ? "p" : mode === "company" ? "e" : "c";
  return `pessoas-graph:${code}:${nif}`;
}

export function parseGraphWindowView(target?: string | null): GraphTarget | null {
  if (!target) return null;
  const [code, ...rest] = target.split(":");
  const nif = rest.join(":").trim();
  if (!nif) return null;
  return { mode: code === "e" ? "company" : code === "c" ? "combined" : "person", nif };
}

/** Abre (ou foca) o grafo numa janela própria, já apontado ao alvo indicado. */
export function openGraphWindow(mode: GraphMode, nif: string, label?: string | null): void {
  // Dimensiona pela área de trabalho disponível: uma janela maior do que o
  // ecrã deixa a pesquisa e os filtros fora de alcance.
  const workspace = estimateWorkspace();
  const width = Math.max(MIN_WINDOW_WIDTH, Math.min(1180, Math.round(workspace.width * 0.92)));
  const height = Math.max(MIN_WINDOW_HEIGHT, Math.min(840, Math.round(workspace.height * 0.94)));
  openWindow(graphWindowView(mode, nif), workspace, {
    title: `${GRAPH_MODE_LABELS[mode]} · ${label || nif}`,
    rect: {
      width,
      height,
      x: Math.max(8, Math.round((workspace.width - width) / 2)),
      y: Math.max(8, Math.round((workspace.height - height) / 2)),
    },
  });
}

// ---------------------------------------------------------------------------
// Seletor de pessoas (autocomplete + filtros) para o grafo
// ---------------------------------------------------------------------------

/**
 * Pesquisa de pessoas/entidades com autocomplete e filtros, para escolher o
 * alvo do grafo sem sair da página/janela onde ele está a ser explorado.
 */
export function PeoplePicker({
  onPick,
  onOpenDetail,
}: {
  onPick: (target: GraphTarget, item: PeopleAutocompleteItem) => void;
  onOpenDetail?: (target: GraphTarget) => void;
}) {
  const [q, setQ] = useState("");
  const [personType, setPersonType] = useState<PersonTypeFilter>("all");
  const [role, setRole] = useState("");
  const [origin, setOrigin] = useState<"" | "cire" | "societario">("");
  const [minRoles, setMinRoles] = useState<number | "">("");
  const [sort, setSort] = useState<PeopleSort>("roles");
  const [suggestions, setSuggestions] = useState<PeopleAutocompleteItem[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [rows, setRows] = useState<Person[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facets, setFacets] = useState<PeopleFiltersResponse | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const hasSearchedRef = useRef(false);

  useEffect(() => {
    getPeopleFilters()
      .then(setFacets)
      .catch(() => setFacets(null));
  }, []);

  const runSearch = useCallback(
    async (term: string) => {
      setLoading(true);
      setError(null);
      hasSearchedRef.current = true;
      try {
        const resp = await searchPeople(term.trim() || undefined, {
          isCompany: personType === "company" ? true : personType === "person" ? false : undefined,
          role: role || undefined,
          origin: origin || undefined,
          minRoles: typeof minRoles === "number" ? minRoles : undefined,
          sort,
          size: 12,
        });
        setRows(resp.items);
        setTotal(resp.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao pesquisar");
        setRows([]);
        setTotal(null);
      } finally {
        setLoading(false);
      }
    },
    [minRoles, origin, personType, role, sort],
  );

  // Sugestões enquanto se escreve (nome/NIF/cargo).
  useEffect(() => {
    const term = q.trim();
    if (!showSuggestions || term.length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const items = await autocompletePeople(term, { limit: 6, signal: controller.signal });
        setSuggestions(items);
        setActiveIndex(items.length ? 0 : -1);
      } catch {
        // pedido cancelado
      }
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [q, showSuggestions]);

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setShowSuggestions(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Mudar um filtro refaz a pesquisa (sem refazer a cada tecla).
  useEffect(() => {
    if (!hasSearchedRef.current) return;
    void runSearch(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personType, role, origin, minRoles, sort]);

  const pickItem = (item: PeopleAutocompleteItem) => {
    setShowSuggestions(false);
    setSuggestions([]);
    if (!item.nif) return;
    onPick({ mode: item.is_company ? "company" : "person", nif: item.nif }, item);
  };

  const targetOf = (person: Person): GraphTarget =>
    person.is_company ? { mode: "company", nif: person.nif } : { mode: "person", nif: person.nif };

  const itemOf = (person: Person): PeopleAutocompleteItem => ({
    nif: person.nif,
    name: person.name,
    is_company: person.is_company,
    roles_count: person.roles_count,
    companies_count: person.companies_count,
    role: person.roles?.[0]?.role ?? null,
    company_name: person.roles?.[0]?.company_name ?? null,
    origin: person.source ?? null,
    last_seen: person.last_seen ?? null,
  });

  return (
    <Card className="p-4">
      <div ref={boxRef} className="flex flex-col gap-3">
        <div className="relative">
          <div className="flex min-h-[44px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
            <Search size={18} className="shrink-0 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setShowSuggestions(true);
              }}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && suggestions.length) {
                  e.preventDefault();
                  setActiveIndex((prev) => (prev + 1) % suggestions.length);
                  return;
                }
                if (e.key === "ArrowUp" && suggestions.length) {
                  e.preventDefault();
                  setActiveIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
                  return;
                }
                if (e.key === "Escape") {
                  setShowSuggestions(false);
                  return;
                }
                if (e.key === "Enter") {
                  e.preventDefault();
                  const active = showSuggestions && activeIndex >= 0 ? suggestions[activeIndex] : undefined;
                  if (active) pickItem(active);
                  else void runSearch(q);
                }
              }}
              placeholder="Pesquisar pessoa ou entidade (nome, NIF, cargo)…"
              autoComplete="off"
              aria-label="Pesquisar pessoa ou entidade para o grafo"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {q && (
              <button
                type="button"
                onClick={() => {
                  setQ("");
                  setSuggestions([]);
                }}
                aria-label="Limpar pesquisa do grafo"
                className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-40 mt-1 max-h-[260px] w-full overflow-y-auto rounded-xl border border-white/10 bg-[#140f13] p-1 shadow-xl">
              {suggestions.map((item, idx) => (
                <button
                  key={`${item.nif || item.name}-${idx}`}
                  type="button"
                  onMouseEnter={() => setActiveIndex(idx)}
                  onClick={() => pickItem(item)}
                  className={[
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition",
                    idx === activeIndex ? "bg-white/[0.10]" : "hover:bg-white/[0.06]",
                  ].join(" ")}
                >
                  {item.is_company ? (
                    <Building2 size={14} className="shrink-0 text-blue-300" />
                  ) : (
                    <PersonStanding size={14} className="shrink-0 text-rose-300" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-foreground">{item.name}</span>
                    <span className="block truncate text-muted-foreground">
                      NIF {item.nif || "—"}
                      {item.role ? ` · ${item.role}` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">{item.roles_count} cargos</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
          <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] p-0.5">
            {([
              { key: "all", label: "Todos" },
              { key: "person", label: "Pessoas" },
              { key: "company", label: "Entidades" },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setPersonType(opt.key)}
                className={[
                  "min-h-[40px] rounded-md px-3 py-2 text-xs transition",
                  personType === opt.key
                    ? "bg-white/[0.16] font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                ].join(" ")}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            aria-label="Filtrar por cargo ou papel"
            className="min-h-[40px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground lg:w-[210px]"
          >
            <option value="">Todos os cargos</option>
            {(facets?.roles || []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.key} ({item.count.toLocaleString("pt-PT")})
              </option>
            ))}
          </select>
          <select
            value={origin}
            onChange={(e) => setOrigin(e.target.value as "" | "cire" | "societario")}
            aria-label="Filtrar por origem dos dados"
            className="min-h-[40px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground lg:w-[210px]"
          >
            <option value="">Qualquer origem</option>
            <option value="cire">CIRE / insolvências</option>
            <option value="societario">Societário (publicações MJ)</option>
          </select>
          <input
            type="number"
            min={0}
            value={minRoles}
            onChange={(e) => setMinRoles(e.target.value === "" ? "" : Math.max(0, Number(e.target.value)))}
            placeholder="Mín. cargos"
            aria-label="Número mínimo de cargos"
            className="min-h-[40px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground lg:w-[120px]"
          />
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as PeopleSort)}
            aria-label="Ordenar resultados"
            className="min-h-[40px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground lg:w-[160px]"
          >
            {(Object.keys(SORT_LABELS) as PeopleSort[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABELS[key]}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void runSearch(q)}
            disabled={loading}
            className="min-h-[40px] w-full rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-2 text-sm text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50 lg:w-auto"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : "Pesquisar"}
          </button>
        </div>

        {error && <p className="text-xs text-rose-300">{error}</p>}

        {total !== null && (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2">
            <p className="px-1 pb-1 text-[11px] text-muted-foreground">
              {total.toLocaleString("pt-PT")} resultado{total === 1 ? "" : "s"} — clique para carregar o grafo.
              {total > rows.length ? ` (a mostrar ${rows.length})` : ""}
            </p>
            <ul className="divide-y divide-white/5">
              {rows.map((person) => (
                <li key={person.nif} className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onPick(targetOf(person), itemOf(person))}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs transition hover:bg-white/[0.05]"
                  >
                    {person.is_company ? (
                      <Building2 size={15} className="shrink-0 text-blue-300" />
                    ) : (
                      <PersonStanding size={15} className="shrink-0 text-rose-300" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-foreground">{person.name}</span>
                      <span className="block truncate text-muted-foreground">
                        NIF {person.nif}
                        {person.roles?.[0] ? ` · ${roleLabel(person.roles[0].role, person.roles[0].event)}` : ""}
                        {person.roles?.[0]?.company_name ? ` · ${person.roles[0].company_name}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {person.roles_count} cargos · {person.companies_count} empresas
                    </span>
                  </button>
                  {onOpenDetail && (
                    <button
                      type="button"
                      onClick={() => onOpenDetail(targetOf(person))}
                      title="Abrir a ficha numa janela própria"
                      className="shrink-0 rounded-lg border border-white/10 px-2 py-1 text-[10px] text-muted-foreground transition hover:text-foreground"
                    >
                      ficha
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {rows.length === 0 && !loading && (
              <p className="px-1 py-2 text-[11px] text-muted-foreground">Nada encontrado com estes filtros.</p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Grafo: resposta da API → grafo do GraphCanvas
// ---------------------------------------------------------------------------

export function combinedToStudioGraph(response: PeopleGraphResponse | null): StudioGraph | null {
  if (!response || !response.nodes.length) return null;

  const edgeValues = response.edges.map((edge) =>
    typeof edge.value === "number" && edge.value > 0 ? edge.value : edge.count || 1,
  );
  const maxValue = Math.max(...edgeValues, 1);

  const colorForType = (type: string) => {
    switch (type) {
      case "company":
        return "#38bdf8"; // sky
      case "entity":
        return "#a78bfa"; // violet
      case "source":
        return "#34d399"; // emerald (sites/perfis da análise 360)
      case "person":
      default:
        return "#fb7185"; // rose
    }
  };

  const legendForType = (type: string) => {
    switch (type) {
      case "company":
        return { key: "company", label: "Empresa central" };
      case "entity":
        return { key: "entity", label: "Entidades contratuais" };
      case "source":
        return { key: "source", label: "Sites e perfis" };
      case "person":
      default:
        return { key: "person", label: "Pessoas/cargos" };
    }
  };

  const nodes: StudioNode[] = response.nodes.map((node: PeopleGraphNode) => {
    const connected = response.edges.filter(
      (edge) => edge.source === node.id || edge.target === node.id,
    ).length;
    const value = Math.max(1, connected);
    const legend = legendForType(node.type);
    return {
      id: node.id,
      key: node.nif || node.id,
      label: node.label,
      dimension: node.type,
      type: node.type,
      role: node.type === "company" ? "Empresa" : node.type === "entity" ? "Entidade" : "Pessoa",
      count: connected,
      total_value: value,
      value,
      radius: node.type === "company" ? 28 : 10 + Math.min(20, Math.sqrt(value / maxValue) * 20),
      color: colorForType(node.type),
      legendKey: legend.key,
      legendLabel: legend.label,
    };
  });

  const edges: StudioEdge[] = response.edges.map((edge) => {
    const rawValue = typeof edge.value === "number" && edge.value > 0 ? edge.value : edge.count || 1;
    const weight = rawValue / maxValue;
    return {
      source: edge.source,
      target: edge.target,
      count: edge.count || 1,
      value: rawValue,
      weight: Math.max(0.2, Math.min(1, weight)),
      label: edge.label || edge.role || undefined,
    };
  });

  const notes = Array.isArray(response.meta?.notes)
    ? (response.meta.notes as string[])
    : (["Grafo combinado: pessoas, cargos, contratos e entidades"] as string[]);

  return {
    nodes,
    edges,
    meta: {
      dimension_a: "person",
      dimension_b: "company",
      metric: "contratos",
      mode: "auto",
      sample_order: "relevance",
      sample_limit: null,
      documents_scanned: response.meta?.contract_count_total ?? 0,
      documents_matching: response.meta?.contract_count_total ?? 0,
      scanned_value: response.meta?.contract_value_total ?? 0,
      nodes_total: response.nodes.length,
      edges_total: response.edges.length,
      kept_nodes: response.nodes.length,
      kept_edges: response.edges.length,
      omitted_edges: 0,
      directed: false,
      notes,
      filters: { company_nif: response.company_nif, company_name: response.company_name },
    },
  };
}

export function graphMetric(): GraphMetric {
  return "contratos" as GraphMetric;
}

// ---------------------------------------------------------------------------
// Resumo de um nó (IA + web search, sempre gravado no Elasticsearch)
// ---------------------------------------------------------------------------

export const MARKDOWN_COMPONENTS = {
  h1: (props: React.ComponentProps<"h2">) => <h2 className="mt-5 text-base font-semibold text-foreground" {...props} />,
  h2: (props: React.ComponentProps<"h3">) => <h3 className="mt-5 text-sm font-semibold text-teal-200" {...props} />,
  h3: (props: React.ComponentProps<"h4">) => <h4 className="mt-4 text-[13px] font-medium text-foreground" {...props} />,
  p: (props: React.ComponentProps<"p">) => <p className="mt-2 text-xs leading-relaxed text-muted-foreground" {...props} />,
  ul: (props: React.ComponentProps<"ul">) => <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground" {...props} />,
  ol: (props: React.ComponentProps<"ol">) => <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground" {...props} />,
  li: (props: React.ComponentProps<"li">) => <li className="leading-relaxed" {...props} />,
  strong: (props: React.ComponentProps<"strong">) => <strong className="font-semibold text-foreground" {...props} />,
  em: (props: React.ComponentProps<"em">) => <em className="italic" {...props} />,
  a: (props: React.ComponentProps<"a">) => (
    <a className="text-teal-300 underline decoration-dotted" target="_blank" rel="noreferrer" {...props} />
  ),
  hr: () => <hr className="my-4 border-white/10" />,
  code: (props: React.ComponentProps<"code">) => (
    <code className="rounded bg-white/[0.06] px-1 py-0.5 text-[11px] text-teal-200" {...props} />
  ),
  blockquote: (props: React.ComponentProps<"blockquote">) => (
    <blockquote className="mt-2 border-l-2 border-teal-400/30 pl-3 text-xs italic text-muted-foreground" {...props} />
  ),
};

/**
 * Resumo de um nó do grafo com IA e pesquisa na web.
 *
 * Ao abrir, mostra o último resumo **já gravado** no Elasticsearch (não gasta
 * nada); o botão volta a gerar (factos do IQ OS + web + modelo) e grava de novo.
 */
export function NodeSummaryCard({
  nodeId,
  nif,
  name,
  kind,
}: {
  nodeId: string;
  nif?: string | null;
  name?: string | null;
  kind?: string | null;
}) {
  const [stored, setStored] = useState<NodeSummaryResponse | null>(null);
  const [fresh, setFresh] = useState<NodeSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);

  const load = useCallback(async () => {
    setStored(null);
    setFresh(null);
    setError(null);
    setShowEvidence(false);
    try {
      const data = await getNodeSummary({ nodeId, nif: nif || undefined, name: name || undefined });
      if (data.found) setStored(data);
    } catch {
      // sem resumo gravado: é normal
    }
  }, [nif, nodeId, name]);

  useEffect(() => {
    void load();
  }, [load]);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await generateNodeSummary({
        nodeId,
        nif: nif || undefined,
        name: name || undefined,
        kind: kind || undefined,
        pages: 2,
      });
      setFresh(data);
      setStored(data);
      setShowEvidence(data.evidence.length > 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao gerar o resumo");
    } finally {
      setLoading(false);
    }
  };

  const current = fresh || stored;
  const summary = current?.summary || "";
  const evidence = current?.evidence || [];

  const copy = async () => {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summary);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="rounded-xl border border-teal-400/20 bg-teal-400/[0.04] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles size={14} className="text-teal-300" />
        <p className="text-xs font-medium text-foreground">Resumo do nó (IA + web search)</p>
        {current?.mode && (
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-muted-foreground">
            {current.mode === "ai" ? "redigido por IA" : "só factos"}
          </span>
        )}
        {typeof current?.generations === "number" && (
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-muted-foreground">
            geração {current.generations}
          </span>
        )}
        {(current?.saved || current?.cached || typeof current?.generations === "number") && (
          <span className="rounded-full border border-teal-400/25 bg-teal-400/10 px-2 py-0.5 text-[10px] text-teal-200">
            guardado no Elasticsearch
          </span>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void generate()}
          disabled={loading}
          className="flex min-h-[36px] items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {loading ? "A gerar…" : summary ? "Gerar novo resumo" : "Gerar resumo"}
        </button>
        {summary && (
          <button
            type="button"
            onClick={() => void copy()}
            className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-foreground transition hover:bg-white/[0.07]"
          >
            {copied ? <Check size={12} className="text-teal-300" /> : <Copy size={12} />}
            {copied ? "Copiado" : "Copiar"}
          </button>
        )}
        {current?.generated_at && (
          <span className="text-[10px] text-muted-foreground">gerado em {formatDate(current.generated_at)}</span>
        )}
      </div>

      {loading && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          A juntar os factos dos índices, a pesquisar na web e a pedir o resumo ao modelo…
        </p>
      )}
      {error && <p className="mt-2 text-[11px] text-rose-300">{error}</p>}

      {summary ? (
        <div className="mt-2">
          <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
            {summary}
          </Markdown>
        </div>
      ) : (
        !loading && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Sem resumo guardado para este nó. Gere um: junta a ficha, as insolvências e os conteúdos
            recolhidos aos resultados da pesquisa na web, e fica gravado para consulta futura.
          </p>
        )
      )}

      {(current?.notes?.length || current?.warnings?.length) && (
        <ul className="mt-2 space-y-1 text-[10px] text-muted-foreground">
          {(current?.notes || []).map((note, index) => (
            <li key={`note-${index}`}>· {note}</li>
          ))}
          {(current?.warnings || []).map((warning, index) => (
            <li key={`warn-${index}`} className="text-amber-200/90">
              ! {warning}
            </li>
          ))}
        </ul>
      )}

      {evidence.length > 0 && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowEvidence((value) => !value)}
            className="text-[11px] text-teal-300 hover:underline"
          >
            {showEvidence ? "Ocultar" : "Ver"} evidência ({evidence.length})
          </button>
          {showEvidence && (
            <ul className="mt-1.5 space-y-1.5">
              {evidence.slice(0, 10).map((entry, index) => (
                <li key={`${entry.url}-${index}`} className="text-[10px]">
                  <a className="text-teal-200 hover:underline" href={entry.url || "#"} target="_blank" rel="noreferrer">
                    {entry.title || entry.url || "ligação"}
                  </a>
                  {entry.engine && <span className="ml-1 text-muted-foreground">({entry.engine})</span>}
                  {entry.snippet && (
                    <p className="mt-0.5 line-clamp-2 text-muted-foreground">{entry.snippet}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
