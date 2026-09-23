import {
  ArrowRight,
  Building2,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Network,
  PersonStanding,
  Search,
  Settings,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, getCompanyCombinedGraph, getCompanyPeopleGraph, getPerson, getPersonGraph, ingestPeopleForCompany, searchPeople } from "../api";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import type { GraphMetric, StudioEdge, StudioGraph, StudioNode } from "../components/graph/graphStudio";
import type {
  PeopleGraphEdge,
  PeopleGraphNode,
  PeopleGraphResponse,
  PeopleIngestResponse,
  PeopleSearchResponse,
  PeopleStatusResponse,
  Person,
  PersonRole,
} from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(date?: string | null): string {
  if (!date) return "—";
  try {
    return new Date(date).toLocaleDateString("pt-PT");
  } catch {
    return date;
  }
}

function roleLabel(role?: string | null, event?: string | null): string {
  if (!role && !event) return "Ligação societária";
  return [event, role].filter(Boolean).join(" · ");
}

function combinedToStudioGraph(response: PeopleGraphResponse | null): StudioGraph | null {
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

  const edges: StudioEdge[] = response.edges.map((edge: PeopleGraphEdge) => {
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

// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

function Card({
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

function Loading({ message = "A carregar…" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
      <Loader2 size={32} className="animate-spin mb-3" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

function EmptyState({ message, icon: Icon }: { message: string; icon?: React.ElementType }) {
  const I = Icon || Search;
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <I size={36} className="mb-3 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

type PessoasIQSection = "dashboard" | "search" | "graph" | "settings";

const SECTIONS: { id: PessoasIQSection; label: string; icon: React.ElementType }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "search", label: "Pesquisa", icon: Search },
  { id: "graph", label: "Grafo", icon: Network },
  { id: "settings", label: "Configurações", icon: Settings },
];

function SectionTabs({
  active,
  onChange,
}: {
  active: PessoasIQSection;
  onChange: (section: PessoasIQSection) => void;
}) {
  return (
    <div className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 px-3 py-2 lg:px-4 backdrop-blur-xl">
      <div
        role="tablist"
        aria-label="Secções do PessoasIQ"
        className="dock-scroll flex items-center gap-0.5 overflow-x-auto rounded-[10px] border border-white/8 bg-white/[0.05] p-0.5"
      >
        {SECTIONS.map((item) => {
          const Icon = item.icon;
          const isActive = item.id === active;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(item.id)}
              title={item.label}
              className={[
                "flex shrink-0 items-center gap-1.5 rounded-[8px] px-3 py-2 text-[13px] transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 min-h-[40px]",
                isActive
                  ? "bg-white/[0.16] font-medium text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
              ].join(" ")}
            >
              <Icon size={15} className={isActive ? "text-teal-300" : undefined} />
              <span className="whitespace-nowrap">{item.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Topbar({
  q,
  setQ,
  onSearch,
}: {
  q: string;
  setQ: (v: string) => void;
  onSearch: () => void;
}) {
  return (
    <header className="min-h-16 border-b border-white/10 bg-[#07151b]/80 backdrop-blur flex flex-wrap items-center gap-2 px-3 py-2 lg:px-4 lg:py-0 sticky top-0 z-30">
      <label className="flex flex-1 items-center gap-2 min-w-0 max-w-2xl min-h-[44px] rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
        <PersonStanding size={18} className="text-rose-300 shrink-0" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Nome, NIF, cargo, empresa…"
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground focus:ring-0"
        />
      </label>
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        <button
          onClick={onSearch}
          className="min-h-[40px] px-4 py-2 rounded-xl bg-rose-400/10 text-rose-300 border border-rose-400/20 text-sm hover:bg-rose-400/20 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
        >
          Pesquisar
        </button>
        <button
          className="min-h-[40px] min-w-[40px] p-2 rounded-xl hover:bg-white/5 text-muted-foreground transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
          aria-label="Configurações"
          title="Configurações"
        >
          <Settings size={18} />
        </button>
        <div
          className="w-8 h-8 rounded-full bg-gradient-to-br from-rose-400 to-orange-500 flex items-center justify-center text-xs font-bold text-white"
          aria-label="Utilizador PM"
          title="Utilizador PM"
        >
          PM
        </div>
      </div>
    </header>
  );
}

function DashboardSection({ status, onSection }: { status: PeopleStatusResponse | null; onSection: (s: PessoasIQSection) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card glow="rose">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pessoas/cargos indexados</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">{status?.documents ?? 0}</p>
        </Card>
        <Card glow="blue">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Empresas com pessoas</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">{status?.total_company_links ?? 0}</p>
        </Card>
        <Card glow="teal">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Cargos mais comuns</p>
          <div className="mt-2 space-y-1">
            {(status?.top_roles ?? []).slice(0, 3).map((role) => (
              <div key={role.key} className="flex items-center justify-between text-xs">
                <span className="truncate">{role.key}</span>
                <span className="text-muted-foreground">{role.count}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card
          glow="rose"
          className="cursor-pointer hover:bg-white/[0.03] transition"
          onClick={() => onSection("search")}
        >
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pesquisar</p>
          <p className="mt-2 flex items-center gap-2 text-sm font-medium text-rose-300">
            Abrir pesquisa <ArrowRight size={14} />
          </p>
        </Card>
      </div>
    </div>
  );
}

function RoleRow({ role }: { role: PersonRole }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-foreground">{roleLabel(role.role, role.event)}</p>
          {role.role_org && <p className="text-xs text-muted-foreground">{role.role_org}</p>}
        </div>
        {role.quota !== null && role.quota !== undefined && (
          <span className="shrink-0 rounded-full bg-amber-400/10 px-2 py-0.5 text-xs text-amber-300">
            {role.quota.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {role.company_nif && (
          <span className="flex items-center gap-1">
            <Building2 size={12} />
            {role.company_name || role.company_nif}
          </span>
        )}
        {role.date && <span>Data: {formatDate(role.date)}</span>}
        {role.publication_date && <span>Publicação: {formatDate(role.publication_date)}</span>}
        {role.acto && <span className="truncate max-w-xs">Acto: {role.acto}</span>}
        {role.causa && <span className="truncate max-w-xs">Causa: {role.causa}</span>}
      </div>
    </div>
  );
}

function PersonDetailPanel({
  person,
  onClose,
  onGraph,
}: {
  person: Person;
  onClose: () => void;
  onGraph: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <PersonStanding size={22} className="text-rose-300" />
            {person.name}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            NIF {person.nif} · {person.is_company ? "Entidade coletiva" : "Pessoa singular"} ·{" "}
            {person.roles_count} cargos · {person.companies_count} empresas
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-white/10 p-1.5 text-muted-foreground hover:text-foreground transition"
          aria-label="Fechar"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onGraph}
          className="flex items-center gap-2 rounded-xl bg-rose-400/10 px-3 py-1.5 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition"
        >
          <GitBranch size={16} /> Ver grafo
        </button>
      </div>

      {person.roles.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Cargos e empresas</h3>
          <div className="max-h-[420px] overflow-y-auto space-y-2 pr-1">
            {person.roles.map((role, idx) => (
              <RoleRow key={`${role.publication_id || idx}-${idx}`} role={role} />
            ))}
          </div>
        </div>
      )}

      {person.first_seen && person.last_seen && (
        <p className="text-xs text-muted-foreground">
          Primeira deteção: {formatDate(person.first_seen)} · Última deteção: {formatDate(person.last_seen)}
        </p>
      )}
    </div>
  );
}

function SearchSection({
  initialQ,
  onSelectPerson,
}: {
  initialQ: string;
  onSelectPerson: (person: Person) => void;
}) {
  const [q, setQ] = useState(initialQ);
  const [personType, setPersonType] = useState<PersonTypeFilter>("all");
  const [results, setResults] = useState<PeopleSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = useCallback(async (value: string, type: PersonTypeFilter) => {
    if (!value.trim()) {
      setResults(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const isCompany = type === "company" ? true : type === "person" ? false : undefined;
      const resp = await searchPeople(value, { isCompany });
      setResults(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao pesquisar");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialQ) runSearch(initialQ, personType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-col gap-3">
          <label className="flex min-h-[44px] flex-1 items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
            <Search size={18} className="text-muted-foreground shrink-0" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch(q, personType)}
              placeholder="Nome, NIF, cargo ou empresa…"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </label>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="flex w-full items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] p-0.5 sm:w-auto">
              {([
                { key: "all", label: "Todos" },
                { key: "person", label: "Pessoas" },
                { key: "company", label: "Entidades" },
              ] as const).map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => {
                    setPersonType(opt.key);
                    if (q.trim()) runSearch(q, opt.key);
                  }}
                  className={[
                    "min-h-[44px] flex-1 rounded-md px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:flex-initial",
                    personType === opt.key
                      ? "bg-white/[0.16] font-medium text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => runSearch(q, personType)}
              disabled={loading}
              className="min-h-[40px] w-full rounded-xl bg-rose-400/10 px-4 py-2 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition disabled:opacity-50 sm:w-auto"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Pesquisar"}
            </button>
          </div>
        </div>
      </Card>

      {error && (
        <Card className="p-6 text-center">
          <p className="text-rose-300">{error}</p>
        </Card>
      )}

      {!results && !loading && !error && (
        <EmptyState message="Introduza um termo para pesquisar pessoas e cargos." />
      )}

      {loading && <Loading message="A pesquisar pessoas e cargos…" />}

      {results && results.total === 0 && !loading && (
        <EmptyState message="Nenhuma pessoa ou cargo encontrado." />
      )}

      {results && results.total > 0 && !loading && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {results.items.map((person) => (
            <Card
              key={person.nif}
              className="cursor-pointer hover:bg-white/[0.03] transition"
              onClick={() => onSelectPerson(person)}
            >
              <div className="flex items-start justify-between gap-2 min-h-[44px]">
                <div className="min-w-0">
                  <p className="font-medium text-foreground truncate">{person.name}</p>
                  <p className="text-xs text-muted-foreground">NIF {person.nif}</p>
                </div>
                {person.is_company ? (
                  <Building2 size={18} className="text-blue-300 shrink-0" />
                ) : (
                  <PersonStanding size={18} className="text-rose-300 shrink-0" />
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-white/[0.06] px-2 py-1 text-muted-foreground">
                  {person.roles_count} cargos
                </span>
                <span className="rounded-full bg-white/[0.06] px-2 py-1 text-muted-foreground">
                  {person.companies_count} empresas
                </span>
              </div>
              {person.roles.slice(0, 2).map((role, idx) => (
                <p key={idx} className="mt-1 text-xs text-muted-foreground truncate">
                  {roleLabel(role.role, role.event)} · {role.company_name || role.company_nif || "—"}
                </p>
              ))}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

type GraphMode = "person" | "company" | "combined";
type NodeKindFilter = "all" | "person" | "company" | "entity";
type EdgeKindFilter = "all" | "role" | "contract";
type PersonTypeFilter = "all" | "person" | "company";

function GraphSection({ person }: { person: Person | null }) {
  const [nif, setNif] = useState(person?.nif || "");
  const [companyNif, setCompanyNif] = useState("");
  const [mode, setMode] = useState<GraphMode>("person");
  const [graphData, setGraphData] = useState<PeopleGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [layoutVersion, setLayoutVersion] = useState(0);

  // Filtros dinâmicos no grafo renderizado
  const [nodeKind, setNodeKind] = useState<NodeKindFilter>("all");
  const [edgeKind, setEdgeKind] = useState<EdgeKindFilter>("all");
  const [minValue, setMinValue] = useState<number | "">("");
  const [searchText, setSearchText] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const effectiveMode: GraphMode = useMemo(() => {
    if (mode === "combined" && companyNif.trim()) return "combined";
    if (mode === "person" && nif.trim()) return "person";
    if (mode === "company" && companyNif.trim()) return "company";
    if (companyNif.trim()) return "company";
    return "person";
  }, [mode, nif, companyNif]);

  const loadGraph = useCallback(async () => {
    if (!nif.trim() && !companyNif.trim()) return;
    setLoading(true);
    setError(null);
    try {
      let resp: PeopleGraphResponse;
      if (effectiveMode === "combined" && companyNif.trim()) {
        resp = await getCompanyCombinedGraph(companyNif.trim(), { contractLimit: 100 });
      } else if (effectiveMode === "company" && companyNif.trim()) {
        resp = await getCompanyPeopleGraph(companyNif.trim());
      } else {
        resp = await getPersonGraph(nif.trim());
      }
      setGraphData(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar grafo");
    } finally {
      setLoading(false);
    }
  }, [companyNif, effectiveMode, nif]);

  useEffect(() => {
    if (person?.nif) {
      setNif(person.nif);
      setCompanyNif("");
      setMode("person");
      loadGraph();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [person?.nif]);

  const filteredGraphData = useMemo(() => {
    if (!graphData) return null;
    const term = searchText.trim().toLowerCase();
    const min = typeof minValue === "number" ? minValue : 0;

    let nodes = graphData.nodes;
    let edges = graphData.edges;

    // 1) Edge type/value filters first so we know which edges are available.
    if (edgeKind !== "all") {
      edges = edges.filter((e) => e.type === edgeKind);
    }
    if (min > 0) {
      edges = edges.filter((e) => (typeof e.value === "number" ? e.value : e.count || 0) >= min);
    }

    // 2) Node type filter keeps matching nodes plus the central company anchor
    //    and any node that is still linked by the surviving edges.
    if (nodeKind !== "all") {
      const central = nodes.find((n) => n.is_company) || nodes.find((n) => n.type === "company");
      const matched = nodes.filter((n) => n.type === nodeKind);
      const keepIds = new Set<string>([
        ...(central ? [central.id] : []),
        ...matched.map((n) => n.id),
      ]);
      nodes = nodes.filter((n) => keepIds.has(n.id));
      const connectedIds = new Set(edges.flatMap((e) => [e.source, e.target]));
      nodes = nodes.filter((n) => connectedIds.has(n.id));
    }

    // 3) Always keep only edges whose endpoints are still present.
    const keepNodeIds = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => keepNodeIds.has(e.source) && keepNodeIds.has(e.target));

    // 4) Text search filters by node label/nif/type and keeps connected neighbours.
    if (term) {
      const matchedNodeIds = new Set(
        nodes
          .filter((n) =>
            (n.label || "").toLowerCase().includes(term) ||
            (n.nif || "").toLowerCase().includes(term) ||
            (n.type || "").toLowerCase().includes(term),
          )
          .map((n) => n.id),
      );
      edges = edges.filter((e) => matchedNodeIds.has(e.source) || matchedNodeIds.has(e.target));
      const connectedIds = new Set(edges.flatMap((e) => [e.source, e.target]));
      nodes = nodes.filter((n) => matchedNodeIds.has(n.id) || connectedIds.has(n.id));
      const finalNodeIds = new Set(nodes.map((n) => n.id));
      edges = edges.filter((e) => finalNodeIds.has(e.source) && finalNodeIds.has(e.target));
    }

    return {
      ...graphData,
      nodes,
      edges,
      node_count: nodes.length,
      edge_count: edges.length,
    };
  }, [graphData, nodeKind, edgeKind, minValue, searchText]);

  const studioGraph = useMemo(() => combinedToStudioGraph(filteredGraphData), [filteredGraphData]);

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="min-w-0">
              <label className="block text-[11px] text-muted-foreground">Pessoa (NIF)</label>
              <input
                value={nif}
                onChange={(e) => setNif(e.target.value)}
                placeholder="NIF da pessoa"
                className="mt-1 min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50 sm:w-[220px]"
              />
            </div>
            <div className="min-w-0">
              <label className="block text-[11px] text-muted-foreground">ou Empresa (NIF)</label>
              <input
                value={companyNif}
                onChange={(e) => setCompanyNif(e.target.value)}
                placeholder="NIF da empresa"
                className="mt-1 min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50 sm:w-[220px]"
              />
            </div>
            <button
              onClick={loadGraph}
              disabled={loading || (!nif.trim() && !companyNif.trim())}
              className="min-h-[44px] rounded-xl bg-rose-400/10 px-4 py-2 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition disabled:opacity-40 sm:self-end"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Carregar grafo"}
            </button>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="flex flex-wrap items-center gap-2">
              {(["person", "company", "combined"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={mode === option}
                  onClick={() => setMode(option)}
                  className={[
                    "min-h-[44px] rounded-xl px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px]",
                    mode === option
                      ? "glass-card text-rose-200 ring-1 ring-rose-400/30"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {option === "person" ? "Pessoa" : option === "company" ? "Empresa" : "Combinado"}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {(["network", "hierarchical", "circular"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={layout === option}
                  onClick={() => {
                    setLayout(option);
                    setLayoutVersion((v) => v + 1);
                  }}
                  className={[
                    "min-h-[44px] rounded-xl px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px]",
                    layout === option
                      ? "glass-card text-rose-200 ring-1 ring-rose-400/30"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {option === "network" ? "Rede" : option === "hierarchical" ? "Hierárquico" : "Circular"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Card>

      <Card className="py-3 px-4">
        <div className="flex flex-col gap-3 text-xs sm:flex-row sm:flex-wrap sm:items-center">
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Pesquisar nó…"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-[200px]"
            />
            <select
              value={nodeKind}
              onChange={(e) => setNodeKind(e.target.value as NodeKindFilter)}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-auto"
            >
              <option value="all">Todos os nós</option>
              <option value="person">Pessoas</option>
              <option value="company">Empresas</option>
              <option value="entity">Entidades</option>
            </select>
            <select
              value={edgeKind}
              onChange={(e) => setEdgeKind(e.target.value as EdgeKindFilter)}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-auto"
            >
              <option value="all">Todas as ligações</option>
              <option value="role">Cargos/sócios</option>
              <option value="contract">Contratos</option>
            </select>
            <input
              type="number"
              min={0}
              value={minValue}
              onChange={(e) => setMinValue(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="Valor mínimo €"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-[140px]"
            />
          </div>
          {effectiveMode === "combined" && graphData?.meta && (
            <span className="text-muted-foreground sm:ml-auto">
              {graphData.meta.people_edge_count ?? 0} cargos · {graphData.meta.contract_nodes ?? 0} entidades ·{" "}
              {graphData.meta.contract_count_total ?? 0} contratos ·{" "}
              {(graphData.meta.contract_value_total ?? 0).toLocaleString("pt-PT", {
                style: "currency",
                currency: "EUR",
                maximumFractionDigits: 0,
              })}
            </span>
          )}
        </div>
      </Card>

      {effectiveMode === "combined" && (
        <Card className="py-2 px-3">
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-[#38bdf8]" />
              Empresa central
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-[#fb7185]" />
              Pessoas/cargos
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-3 rounded-full bg-[#a78bfa]" />
              Entidades contratuais
            </span>
            {filteredGraphData && (
              <span className="ml-auto text-muted-foreground">
                Visíveis: {filteredGraphData.node_count} nós · {filteredGraphData.edge_count} arestas
              </span>
            )}
          </div>
        </Card>
      )}

      {error && (
        <Card className="p-6 text-center">
          <p className="text-rose-300">{error}</p>
        </Card>
      )}

      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[1fr_minmax(0,420px)]">
        <Card className="flex flex-col p-3 lg:min-h-0 w-full">
          {studioGraph && studioGraph.nodes.length > 0 ? (
            <GraphCanvas
              graph={studioGraph}
              layout={layout}
              metric={"contratos" as GraphMetric}
              layoutVersion={layoutVersion}
              loading={loading}
              heightClass="h-[50vh] min-h-[300px] sm:h-[58vh] lg:h-[68vh] max-h-[640px]"
              selectedNodeId={selectedNodeId}
              onNodeClick={(node) => setSelectedNodeId(node.id)}
            />
          ) : (
            <div className="flex h-[50vh] min-h-[300px] flex-col items-center justify-center text-sm text-muted-foreground sm:h-[58vh] lg:h-[68vh] max-h-[640px]">
              <Network size={32} className="mb-3 opacity-40" />
              {loading ? "A construir grafo…" : "Escolha uma pessoa ou empresa para visualizar as ligações."}
            </div>
          )}
        </Card>

        <Card className="flex flex-col p-4 lg:col-span-1 lg:min-h-0 w-full">
          <h4 className="text-sm font-semibold shrink-0">Detalhe do nó</h4>
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto max-h-[40vh] sm:max-h-[55vh] lg:max-h-[520px]">
            {selectedNodeId && graphData ? (
              (() => {
                const node = graphData.nodes.find((n) => n.id === selectedNodeId);
                const connected = graphData.edges.filter(
                  (e) => e.source === selectedNodeId || e.target === selectedNodeId,
                );
                if (!node) return <p className="text-xs text-muted-foreground">Nó não encontrado.</p>;
                return (
                  <div className="space-y-3 text-xs">
                    <p className="font-medium text-sm">{node.label}</p>
                    <p className="text-muted-foreground">
                      Tipo: {node.type === "company" ? "Empresa central" : node.type === "entity" ? "Entidade" : "Pessoa"}
                      <br />
                      {node.nif && <span>NIF: {node.nif}</span>}
                      <br />
                      Ligações: {connected.length}
                    </p>
                    <div className="space-y-2">
                      {connected.map((edge, idx) => {
                        const otherId = edge.source === selectedNodeId ? edge.target : edge.source;
                        const other = graphData.nodes.find((n) => n.id === otherId);
                        return (
                          <div key={idx} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                            <p className="font-medium">{edge.label || edge.role || "Ligação"}</p>
                            <p className="text-muted-foreground">{other?.label || otherId}</p>
                            {typeof edge.value === "number" && edge.value > 0 && (
                              <p className="text-rose-200">
                                {edge.value.toLocaleString("pt-PT", { style: "currency", currency: "EUR" })}
                              </p>
                            )}
                            {edge.count && edge.count > 1 && <p className="text-muted-foreground">{edge.count} ocorrências</p>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()
            ) : (
              <p className="text-xs text-muted-foreground">Clique num nó do grafo para ver detalhes e ligações.</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function IngestPanel() {
  const [nif, setNif] = useState("");
  const [result, setResult] = useState<PeopleIngestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!nif.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await ingestPeopleForCompany(nif.trim());
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card glow="rose">
        <h3 className="text-sm font-semibold">Indexar pessoas/cargos por empresa</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Extrai pessoas e cargos das publicações societárias indexadas para o NIF indicado.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={nif}
            onChange={(e) => setNif(e.target.value)}
            placeholder="NIF da empresa"
            className="w-[200px] rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
          />
          <button
            onClick={run}
            disabled={loading || !nif.trim()}
            className="rounded-xl bg-rose-400/10 px-3 py-2 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition disabled:opacity-40"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : "Indexar"}
          </button>
        </div>
        {result && (
          <p className="mt-3 text-xs text-teal-300">
            Indexados {result.indexed_count} registos a partir de {result.total} publicações.
          </p>
        )}
        {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PessoasIQPage({ nif: nifProp }: { nif?: string } = {}) {
  const [section, setSection] = useState<PessoasIQSection>("dashboard");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<PeopleStatusResponse | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/people/status`);
      if (res.ok) setStatus(await res.json());
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  /**
   * Abre a ficha de uma pessoa: pelo NIF recebido em prop (janela `person-detail:`
   * aberta a partir do societário) ou pelo NIF no URL (`/pessoas-iq/<NIF>`).
   */
  useEffect(() => {
    const fromUrl = window.location.pathname.match(/^\/pessoas-iq\/([^/]+)$/);
    const nif = (nifProp || (fromUrl ? decodeURIComponent(fromUrl[1]) : "")).trim();
    if (!/^\d{9}$/.test(nif)) return;
    setDetailLoading(true);
    setDetailError(null);
    getPerson(nif)
      .then((person) => {
        setSelectedPerson(person);
        setSection("search");
      })
      .catch((err) => setDetailError(err instanceof Error ? err.message : "Erro"))
      .finally(() => setDetailLoading(false));
  }, [nifProp]);

  const handleSearchTopbar = () => {
    setSection("search");
  };

  const handleSelectPerson = (person: Person) => {
    setSelectedPerson(person);
  };

  const handleGraphForSelected = () => {
    setSection("graph");
  };

  const content = useMemo(() => {
    if (detailLoading) return <Loading message="A carregar ficha…" />;
    if (detailError) {
      return (
        <Card className="p-8 text-center">
          <p className="text-rose-300">{detailError}</p>
        </Card>
      );
    }

    switch (section) {
      case "dashboard":
        return <DashboardSection status={status} onSection={setSection} />;
      case "search":
        return (
          <SearchSection initialQ={q} onSelectPerson={handleSelectPerson} />
        );
      case "graph":
        return <GraphSection person={selectedPerson} />;
      case "settings":
        return <IngestPanel />;
      default:
        return null;
    }
  }, [detailError, detailLoading, q, section, selectedPerson, status]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background text-foreground orbit-bg">
      <Topbar q={q} setQ={setQ} onSearch={handleSearchTopbar} />
      <SectionTabs active={section} onChange={setSection} />
      <main className="@container min-w-0 flex-1 overflow-y-auto p-3 lg:p-6">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_minmax(0,420px)]">
          <div className={`min-w-0 ${section === "graph" ? "lg:col-span-2" : "space-y-4"}`}>{content}</div>

          {selectedPerson && section !== "graph" && (
            <aside className="min-w-0 space-y-4">
              <Card glow="rose">
                <PersonDetailPanel
                  person={selectedPerson}
                  onClose={() => setSelectedPerson(null)}
                  onGraph={handleGraphForSelected}
                />
              </Card>
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}
