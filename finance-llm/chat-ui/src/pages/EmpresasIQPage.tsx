import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import GraphStudioPage from "./GraphStudioPage";
import {
  AlertCircle,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  CandlestickChart,
  Circle,
  ChevronDown,
  ChevronRight,
  Crosshair,
  Database,
  Download,
  FileSearch,
  FileText,
  Filter,
  FolderHeart,
  FolderOpen,
  FolderPlus,
  GitBranch,
  HandCoins,
  Heart,
  History,
  Info,
  LayoutDashboard,
  List,
  Loader2,
  MapPin,
  Maximize2,
  Menu,
  MessageSquare,
  Minimize2,
  Network,
  PanelLeftClose,
  RefreshCw,
  Scan,
  Search,
  Settings,
  Shuffle,
  Sparkles,
  TrendingUp,
  Users,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart as RePieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  Area,
  AreaChart,
  Legend,
  type PieLabel,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import {
  getContract,
  getContractAnalytics,
  getContractNetwork,
  getContractRegionalAnalytics,
  getContractRelations,
  getContractStatus,
  getContractYears,
  searchCompanies,
  searchContracts,
  getCompanyDetail,
  getCompanyContracts,
  getCompanyAnalytics,
  analyzeContract,
} from "../api";
import {
  MAP_CENTER,
  TILE_SIZE,
  jitterAround,
  latToWorld,
  lonToWorld,
  lookupPlace,
  worldToLat,
  worldToLon,
} from "../components/graph/geo";
import { useFavorites, type FavoriteKind } from "../favorites";
import { useSidebarHidden } from "../layout";
import { useAuth } from "../auth";
import { Avatar } from "./SettingsPage";
import { companiesIn, useWorkspace, type WorkspaceEntry } from "../workspace";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { toStudioGraph, type GraphMetric, type StudioNode } from "../components/graph/graphStudio";
import type {
  CompanyAnalyticsResponse,
  CompanyContractsResponse,
  CompanyDetail,
  CompanySearchResponse,
  ContractAnalyticsResponse,
  ContractAnalyzeRequest,
  ContractAnalyzeResponse,
  ContractGraphBuildNode,
  ContractGraphBuildResponse,
  ContractGraphResponse,
  ContractItem,
  ContractRegionalResponse,
  ContractRegionalRow,
  ContractRelation,
  ContractRelationsResponse,
  ContractSearchResponse,
  ContractSearchRequest,
  ContractParty,
  ContractPartyParsed,
} from "../types";

type EmpresasIQSection =
  | "dashboard"
  | "contracts"
  | "entities"
  | "graph"
  | "studio"
  | "analysis"
  | "favorites"
  | "settings";

const COLORS = [
  "#10a37f",
  "#3b82f6",
  "#f59e0b",
  "#8b5cf6",
  "#ef4444",
  "#06b6d4",
  "#ec4899",
  "#6366f1",
];

function money(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function compact(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function full(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT").format(value);
}

function fmtDate(d?: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("pt-PT");
}

function partyNames(party?: ContractParty | ContractParty[]) {
  if (!party) return "—";
  const list = Array.isArray(party) ? party : [party];
  const names = list
    .flatMap((p) => p.parsed || [])
    .map((p: ContractPartyParsed) => p.nome)
    .filter(Boolean);
  return names.length ? names.join(", ") : "—";
}

function nifFromParty(party?: ContractParty | ContractParty[]) {
  if (!party) return undefined;
  const list = Array.isArray(party) ? party : [party];
  const first = list.flatMap((p) => p.parsed || [])[0];
  return first?.nif;
}

function nifsFromParty(party?: ContractParty | ContractParty[]) {
  const list = Array.isArray(party) ? party : party ? [party] : [];
  return list.flatMap((item) => (item.parsed ?? []).map((entry) => entry.nif).filter(Boolean) as string[]);
}

/** Entidades associadas a um contrato (adjudicantes e adjudicatários) para guardar no dossier. */
function contractPartiesOf(contract: ContractItem) {
  const collect = (party: ContractParty | ContractParty[] | undefined, role: string) =>
    (Array.isArray(party) ? party : party ? [party] : [])
      .flatMap((item) => item.parsed ?? [])
      .filter((entry) => Boolean(entry.nif))
      .map((entry) => ({ nif: entry.nif as string, label: entry.nome || `NIF ${entry.nif}`, role }));
  return [...collect(contract.adjudicantes, "Adjudicante"), ...collect(contract.adjudicatarios, "Adjudicatário")];
}

type ContractCompetitor = { name: string; nif?: string };

function parseCompetitors(value?: string | string[]): ContractCompetitor[] {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  return values
    .flatMap((entry) => {
      const text = String(entry).trim();
      if (!text) return [];
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
          return parsed.map((item) =>
            typeof item === "string"
              ? item
              : `${item?.nome ?? item?.name ?? ""} ${item?.nif ?? ""}`.trim()
          );
        }
      } catch {
      }
      return text.split(/\s*[;|\n]+\s*/);
    })
    .map((entry) => {
      const nif = entry.match(/\b\d{9}\b/)?.[0];
      return { name: entry.replace(/\b\d{9}\b/g, "").replace(/[()]/g, "").trim(), nif };
    })
    .filter((entry) => entry.name.length > 1);
}

const countFormatter: RechartsFormatter = (value) => [
  full(Number(value)),
  "Contratos",
];
const euroFormatter: RechartsFormatter = (value) => [
  money(Number(value)),
  "Valor",
];
const percentPieLabel: PieLabel = (props) => {
  const p = props?.percent ?? 0;
  return `${(p * 100).toFixed(0)}%`;
};

function useDebounce<T>(value: T, delay = 350) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

// --- Small presentational components ---

function Badge({
  children,
  color = "teal",
  variant,
}: {
  children: React.ReactNode;
  color?: "teal" | "blue" | "amber" | "rose" | "violet";
  variant?: "default" | "success" | "warning" | "info" | "danger" | "outline" | "secondary";
}) {
  const colorMap = {
    teal: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
    blue: "bg-blue-400/10 text-blue-400 border-blue-400/20",
    amber: "bg-amber-400/10 text-amber-400 border-amber-400/20",
    rose: "bg-rose-400/10 text-rose-400 border-rose-400/20",
    violet: "bg-violet-400/10 text-violet-400 border-violet-400/20",
  };
  const variantMap: Record<NonNullable<typeof variant>, string> = {
    default: "bg-muted text-muted-foreground",
    success: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
    warning: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
    info: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
    danger: "bg-red-500/15 text-red-400 border border-red-500/30",
    outline: "bg-transparent border border-border text-muted-foreground",
    secondary: "bg-secondary text-secondary-foreground border border-border",
  };
  const cls = color ? colorMap[color] : variantMap[variant ?? "default"];
  return (
    <span className={`px-2 py-0.5 rounded-full border text-xs ${cls}`}>
      {children}
    </span>
  );
}

function Card({
  children,
  className = "",
  glow,
}: {
  children: React.ReactNode;
  className?: string;
  glow?: "teal" | "blue" | "amber" | "rose" | "violet";
}) {
  const glowClass = glow ? `glow-${glow}` : "";
  return (
    <div
      className={`glass-card gradient-border rounded-2xl p-5 min-w-0 ${glowClass} ${className}`}
    >
      {children}
    </div>
  );
}

/** Botão de favorito (entidade ou contrato). Estado vem do módulo `favorites` (localStorage). */
function FavoriteButton({
  kind,
  id,
  label,
  sublabel,
  value,
  variant = "chip",
}: {
  kind: FavoriteKind;
  id: string;
  label: string;
  sublabel?: string;
  value?: number | null;
  variant?: "chip" | "solid";
}) {
  const { isFavorite, toggle } = useFavorites();
  const active = isFavorite(kind, id);
  const base =
    variant === "solid"
      ? "rounded-full px-3.5 py-1.5 text-sm"
      : "rounded-xl px-3 py-1.5 text-sm";
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => toggle({ kind, id, label, sublabel, value })}
      title={active ? "Remover dos favoritos" : "Adicionar aos favoritos"}
      className={[
        base,
        "glass-card flex items-center gap-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50",
        active ? "text-rose-300 ring-1 ring-rose-400/40" : "text-muted-foreground hover:text-rose-200",
      ].join(" ")}
    >
      <Heart size={16} className={active ? "scale-110 transition-transform" : "transition-transform"} fill={active ? "currentColor" : "none"} />
      {active ? "Nos favoritos" : "Favorito"}
    </button>
  );
}

/**
 * Guarda a ficha aberta numa pasta do dossier (pastas em Configurações).
 * Mostra em que pastas já está e permite criar uma pasta nova sem sair da ficha.
 */
function SaveToFolderButton({
  kind,
  id,
  label,
  sublabel,
  value,
  parties,
  variant = "chip",
}: {
  kind: FavoriteKind;
  id: string;
  label: string;
  sublabel?: string;
  value?: number | null;
  parties?: { nif: string; label: string; role?: string }[];
  variant?: "chip" | "solid";
}) {
  const { folders, addToFolder, createFolder } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  const savedIn = folders.filter((folder) => folder.items.some((item) => item.kind === kind && item.id === id));
  const entry = { kind, id, label, sublabel, value: value ?? null, parties };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const base = variant === "solid" ? "rounded-full px-3.5 py-1.5 text-sm" : "rounded-xl px-3 py-1.5 text-sm";

  const save = (folderId: string) => {
    addToFolder(folderId, entry);
    setOpen(false);
  };

  const saveToNewFolder = () => {
    const folderId = createFolder(newName);
    if (folderId) addToFolder(folderId, entry);
    setNewName("");
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        title="Guardar numa pasta do dossier"
        className={[
          base,
          "glass-card flex items-center gap-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
          savedIn.length > 0 ? "text-teal-300 ring-1 ring-teal-400/30" : "text-muted-foreground hover:text-teal-200",
        ].join(" ")}
      >
        <FolderPlus size={16} />
        {savedIn.length > 0 ? `${savedIn.length} pasta${savedIn.length === 1 ? "" : "s"}` : "Guardar em pasta"}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-64 rounded-xl border border-white/10 bg-[#07151b]/95 p-2 shadow-2xl backdrop-blur-xl"
        >
          <p className="px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">Dossier</p>
          {folders.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">Ainda não há pastas. Crie a primeira abaixo.</p>
          )}
          <div className="max-h-52 space-y-1 overflow-y-auto">
            {folders.map((folder) => {
              const already = folder.items.some((item) => item.kind === kind && item.id === id);
              return (
                <button
                  key={folder.id}
                  type="button"
                  role="menuitem"
                  onClick={() => save(folder.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                >
                  <FolderHeart size={14} className={already ? "text-teal-300" : ""} />
                  <span className="min-w-0 flex-1 truncate">{folder.name}</span>
                  {already && <span className="text-[10px] text-teal-300">guardado</span>}
                </button>
              );
            })}
          </div>
          <div className="mt-2 flex items-center gap-1.5 border-t border-white/10 pt-2">
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") saveToNewFolder();
              }}
              placeholder="Nova pasta…"
              aria-label="Nome da nova pasta"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            />
            <button
              type="button"
              onClick={saveToNewFolder}
              disabled={!newName.trim()}
              className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-2 py-1.5 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Criar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({
  icon: Icon,
  value,
  label,
  change,
  color = "text-teal-400",
}: {
  icon: React.ElementType;
  value: string;
  label: string;
  change?: string;
  color?: string;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-2xl md:text-3xl font-bold stat-value">{value}</p>
          <p className="mt-1 text-sm text-muted-foreground">{label}</p>
        </div>
        <div className={`p-2 rounded-xl bg-white/5 border border-white/10 ${color}`}>
          <Icon size={22} />
        </div>
      </div>
      {change && (
        <p className="mt-3 text-xs flex items-center gap-1 text-emerald-400">
          <TrendingUp size={12} />
          {change}
        </p>
      )}
    </Card>
  );
}

function MiniBar({
  value,
  max,
  color = "bg-teal-400",
}: {
  value: number;
  max: number;
  color?: string;
}) {
  const pct = Math.min(100, Math.round((value / Math.max(max, 1)) * 100));
  return (
    <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// --- Network canvas ---

type GraphView = "network" | "hierarchical" | "circular" | "map" | "list";

/** Nó normalizado para simulação/desenho. As coordenadas ficam em `positionsRef` (mutáveis). */
type SimNode = {
  id: string;
  label: string;
  type: string;
  radius: number;
  color: string;
  mass: number;
  degree: number;
  contracts?: number;
  group: string;
  region?: string;
  lat?: number;
  lon?: number;
  approx?: boolean;
  contractId?: string;
};

type SimEdge = {
  source: string;
  target: string;
  count: number;
  value: number;
};

type NodePosition = { x: number; y: number; vx: number; vy: number };

const NODE_COLORS: Record<string, string> = {
  regiao: "#fbbf24",
  adjudicante: "#2dd4bf",
  adjudicatario: "#60a5fa",
  ambos: "#f59e0b",
  contrato: "#a78bfa",
  outra: "#fb7185",
};

const NODE_LEGEND: { type: string; label: string }[] = [
  { type: "regiao", label: "Região" },
  { type: "adjudicante", label: "Adjudicante" },
  { type: "adjudicatario", label: "Adjudicatário" },
  { type: "ambos", label: "Adjudicante e adjudicatário" },
  { type: "contrato", label: "Contrato" },
];

/** Opções por omissão do painel de filtros do grafo (usadas no "Repor filtros"). */
const DEFAULT_GRAPH_OPTIONS = {
  nodeLimit: 250,
  edgeLimit: 400,
  minValue: 0,
  showAdjudicantes: true,
  showAdjudicatarios: true,
  showContracts: true,
  groupByRegion: false,
  pruneLeaves: false,
  hideSupernodes: false,
  supernodeThreshold: 12,
};

function nodeTypeLabel(type: string) {
  switch (type) {
    case "regiao":
      return "Região";
    case "adjudicante":
      return "Adjudicante";
    case "adjudicatario":
      return "Adjudicatário";
    case "ambos":
      return "Adjudicante e adjudicatário";
    case "contrato":
      return "Contrato";
    default:
      return "Outro";
  }
}

/** Raio codifica centralidade (grau) ou volume contratual (regiões). */
function nodeRadius(type: string, degree: number, contracts?: number) {
  const base = type === "regiao" ? 17 : type === "adjudicante" ? 13 : type === "contrato" ? 11 : 11;
  const weight = type === "regiao" ? Math.sqrt(contracts ?? 0) / 3 : Math.sqrt(degree);
  return Math.min(30, base + Math.min(9, weight * 2));
}

function normalizeLabel(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

/** Posição inicial determinística (anel simples ou anéis por grupo). */
function seedPosition(index: number, count: number, groupIndex = 0, groupCount = 1): NodePosition {
  if (groupCount > 1) {
    const groupAngle = (groupIndex / groupCount) * Math.PI * 2;
    const localAngle = (index / Math.max(count, 1)) * Math.PI * 2;
    return {
      x: Math.cos(groupAngle) * 220 + Math.cos(localAngle) * 54,
      y: Math.sin(groupAngle) * 220 + Math.sin(localAngle) * 54,
      vx: 0,
      vy: 0,
    };
  }
  const angle = (index / Math.max(count, 1)) * Math.PI * 2;
  return { x: Math.cos(angle) * 150, y: Math.sin(angle) * 150, vx: 0, vy: 0 };
}

function useGraphModel(graph: ContractGraphResponse | null, options: {
  nodeLimit: number;
  edgeLimit: number;
  minValue: number;
  showAdjudicantes: boolean;
  showAdjudicatarios: boolean;
  showContracts: boolean;
  groupByRegion: boolean;
  pruneLeaves: boolean;
  hideSupernodes: boolean;
  supernodeThreshold: number;
}) {
  return useMemo(() => {
    // 1. Filtragem por valor + agregação de arestas duplicadas por (source,target).
    const edgeMap = new Map<string, SimEdge>();
    (graph?.edges ?? [])
      .filter((edge) => (edge.value ?? 0) >= options.minValue)
      .forEach((edge) => {
        const key = [edge.source, edge.target].sort().join("|");
        const existing = edgeMap.get(key);
        if (existing) {
          existing.count += edge.count;
          existing.value += edge.value;
        } else {
          edgeMap.set(key, { source: edge.source, target: edge.target, count: edge.count, value: edge.value });
        }
      });

    // 2. Grau calculado sobre a rede agregada (dimensiona e ordena os nós).
    const degree = new Map<string, number>();
    edgeMap.forEach((edge) => {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    });

    // 3. Nós: filtros de tipo -> centralidade -> limite.
    let nodes: SimNode[] = (graph?.nodes ?? [])
      .filter((node) => {
        if (!options.showAdjudicantes && node.type === "adjudicante") return false;
        if (!options.showAdjudicatarios && node.type === "adjudicatario") return false;
        if (!options.showAdjudicantes && !options.showAdjudicatarios && node.type === "ambos") return false;
        if (!options.showContracts && node.type === "contrato") return false;
        return true;
      })
      .map((node) => {
        const nodeDegree = degree.get(node.id) || 0;
        // Só nós de região têm geografia nos dados. Entidades/contratos nunca são colocados
        // por semelhança de nome (isso punha, por exemplo, "Startup Madeira" na Madeira e
        // "Euromar" em qualquer sítio): ficam sem lat/lon e o mapa posiciona-os dentro da
        // região ativa (marcados como aproximados) ou omite-os.
        const place = node.type === "regiao" ? lookupPlace(node.id, node.label) : null;
        return {
          id: node.id,
          label: node.label,
          type: node.type,
          radius: nodeRadius(node.type, nodeDegree, node.count),
          color: NODE_COLORS[node.type] || NODE_COLORS.outra,
          mass: node.type === "regiao" ? 3 : node.type === "adjudicante" ? 2 : node.type === "contrato" ? 1.5 : 1,
          degree: nodeDegree,
          contracts: node.count,
          group: node.type === "regiao" ? node.label : node.type,
          region: node.type === "regiao" ? node.label : undefined,
          lat: place?.lat,
          lon: place?.lon,
          approx: Boolean(place && !place.exact),
          contractId: node.contract_id,
        };
      })
      .sort((a, b) => b.degree - a.degree || (b.contracts ?? 0) - (a.contracts ?? 0));
    if (options.nodeLimit > 0) nodes = nodes.slice(0, options.nodeLimit);

    // 4. Podas: folhas (grau < 2) e supernós (grau acima do limiar).
    if (options.pruneLeaves) nodes = nodes.filter((node) => node.degree >= 2);
    if (options.hideSupernodes) nodes = nodes.filter((node) => node.degree <= options.supernodeThreshold);

    // 5. Arestas: apenas entre nós visíveis, ordenadas por valor e limitadas.
    const nodeIds = new Set(nodes.map((node) => node.id));
    let edges = Array.from(edgeMap.values()).filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)
    );
    edges.sort((a, b) => b.value - a.value);
    if (options.edgeLimit > 0) edges = edges.slice(0, options.edgeLimit);

    return { nodes, edges };
  }, [graph, options]);
}

function NetworkCanvas({
  graph,
  view,
  onViewChange,
  selectedNodeId,
  selectedEdgeKey,
  onNodeClick,
  onEdgeClick,
  disabledViews = [],
  disabledHint = "Disponível depois de escolher uma região.",
  emptyHint,
  regionHint,
}: {
  graph: ContractGraphResponse | null;
  view: GraphView;
  onViewChange: (v: GraphView) => void;
  selectedNodeId?: string | null;
  selectedEdgeKey?: string | null;
  onNodeClick?: (node: SimNode) => void;
  onEdgeClick?: (edge: SimEdge) => void;
  disabledViews?: GraphView[];
  disabledHint?: string;
  emptyHint?: string;
  /** Região ativa (NUTS): usada para posicionar entidades que não têm coordenadas próprias. */
  regionHint?: string | null;
}) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [hovered, setHovered] = useState<SimNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<SimEdge | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [isExpanded, setIsExpanded] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [nodeSearch, setNodeSearch] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(
    // No layout de duas colunas (xl) há espaço para o painel aberto; abaixo disso, recolhido.
    () => typeof window === "undefined" || window.innerWidth >= 1280
  );
  const [layoutRun, setLayoutRun] = useState(0);
  const [tilesLoaded, setTilesLoaded] = useState(0);
  const [mapZoom, setMapZoom] = useState(6);
  const [mapCenter, setMapCenter] = useState(MAP_CENTER);
  const [mapDragging, setMapDragging] = useState(false);
  const [mapFitNonce, setMapFitNonce] = useState(0);
  const mapManualRef = useRef(false);
  const mapFitKeyRef = useRef("");
  const mapDragRef = useRef<{ x: number; y: number; lat: number; lon: number } | null>(null);
  const mapDragMovedRef = useRef(false);
  const mapWheelAccumRef = useRef(0);

  const draggingRef = useRef(false);
  const dragMovedRef = useRef(false);
  const lastPosRef = useRef({ x: 0, y: 0 });
  const userMovedRef = useRef(false);
  const positionsRef = useRef(new Map<string, NodePosition>());
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const [options, setOptions] = useState({ ...DEFAULT_GRAPH_OPTIONS });
  const maxNodes = useMemo(() => (graph?.nodes?.length || 100), [graph]);
  const maxEdges = useMemo(() => (graph?.edges?.length || 400), [graph]);

  const { nodes, edges } = useGraphModel(graph, options);
  const isRegionLevel = nodes.length > 0 && nodes.every((node) => node.type === "regiao");
  const searchMatches = useMemo(() => {
    // Pesquisa sem sensibilidade a maiúsculas nem acentos ("saude" encontra "Saúde").
    const query = normalizeLabel(nodeSearch);
    if (!query) return [];
    return nodes
      .filter((node) => normalizeLabel(`${node.label} ${node.id} ${node.contractId ?? ""}`).includes(query))
      .slice(0, 8);
  }, [nodeSearch, nodes]);
  const searchMatchIds = useMemo(() => new Set(searchMatches.map((node) => node.id)), [searchMatches]);
  const visibleNodeIds = useMemo(() => {
    if (!searchFocused || searchMatches.length === 0) return null;
    const ids = new Set(searchMatches.map((node) => node.id));
    edges.forEach((edge) => {
      if (ids.has(edge.source) || ids.has(edge.target)) {
        ids.add(edge.source);
        ids.add(edge.target);
      }
    });
    return ids;
  }, [edges, searchFocused, searchMatches]);
  const renderNodes = useMemo(
    () => (visibleNodeIds ? nodes.filter((node) => visibleNodeIds.has(node.id)) : nodes),
    [nodes, visibleNodeIds]
  );
  const renderEdges = useMemo(
    () =>
      visibleNodeIds
        ? edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
        : edges,
    [edges, visibleNodeIds]
  );
  const hasData = renderNodes.length > 0;

  // Orçamento de etiquetas por centralidade: evita o "muro de texto" em grafos densos.
  const labelledIds = useMemo(() => {
    const limit = view === "circular" ? 16 : view === "hierarchical" ? 22 : 12;
    return new Set(
      [...renderNodes]
        .sort((a, b) => b.degree - a.degree || (b.contracts ?? 0) - (a.contracts ?? 0))
        .slice(0, limit)
        .map((node) => node.id)
    );
  }, [renderNodes, view]);

  const legendTypes = useMemo(() => [...new Set(renderNodes.map((node) => node.type))], [renderNodes]);

  // Qualquer alteração à composição do grafo reinicia a simulação (e o enquadramento).
  const layoutKey = useMemo(() => {
    const nodeIds = renderNodes.map((node) => node.id).sort().join("|");
    const edgeIds = renderEdges.map((edge) => `${edge.source}>${edge.target}`).sort().join("|");
    return `${view}#${options.groupByRegion ? "grouped" : "free"}#${layoutRun}#${nodeIds}#${edgeIds}`;
  }, [layoutRun, options.groupByRegion, renderEdges, renderNodes, view]);

  const activeFilterCount =
    (options.minValue > 0 ? 1 : 0) +
    (options.groupByRegion ? 1 : 0) +
    (options.pruneLeaves ? 1 : 0) +
    (options.hideSupernodes ? 1 : 0) +
    (!options.showAdjudicantes ? 1 : 0) +
    (!options.showAdjudicatarios ? 1 : 0) +
    (!options.showContracts ? 1 : 0);

  // Um novo conjunto de nós/arestas invalida o hover (evita tooltips "fantasma").
  useEffect(() => {
    setHovered(null);
    setHoveredEdge(null);
  }, [layoutKey]);

  // Ao mudar de conjunto de dados, volta ao enquadramento inicial.
  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setNodeSearch("");
    setSearchFocused(false);
    setHovered(null);
    setHoveredEdge(null);
    positionsRef.current.clear();
    userMovedRef.current = false;
  }, [graph]);

  useEffect(() => {
    setTilesLoaded(0);
  }, [mapZoom, size.height, size.width]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === wrapperRef.current);
      setIsExpanded(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!isExpanded) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.fullscreenElement) {
        void document.exitFullscreen();
      } else {
        setIsExpanded(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isExpanded]);

  const toggleFullscreen = async () => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (wrapper.requestFullscreen) {
        await wrapper.requestFullscreen();
      } else {
        setIsExpanded((expanded) => !expanded);
      }
    } catch {
      setIsExpanded((expanded) => !expanded);
    }
  };

  // Espelho do estado atual: mantém o desenho estável sem reiniciar a simulação em cada hover/pan.
  const frame = useRef({
    nodes: renderNodes,
    edges: renderEdges,
    view,
    scale,
    offset,
    hovered,
    hoveredEdge,
    selectedNodeId,
    selectedEdgeKey,
    hasSearch: false,
    searchMatchIds,
    labelledIds,
  });

  useEffect(() => {
    frame.current = {
      nodes: renderNodes,
      edges: renderEdges,
      view,
      scale,
      offset,
      hovered,
      hoveredEdge,
      selectedNodeId,
      selectedEdgeKey,
      hasSearch: Boolean(nodeSearch.trim()),
      searchMatchIds,
      labelledIds,
    };
  });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const current = frame.current;
    const positions = positionsRef.current;
    // O contexto é escalado por DPR: as coordenadas usadas (layout, hit-test, tooltip) ficam em CSS px.
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.width / dpr;
    const height = rect.height || canvas.height / dpr;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (current.nodes.length === 0) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.translate(width / 2 + current.offset.x, height / 2 + current.offset.y);
    ctx.scale(current.scale, current.scale);

    const edgeKeyOf = (edge: SimEdge) => [edge.source, edge.target].sort().join("|");
    const activeEdgeKey = current.hoveredEdge ? edgeKeyOf(current.hoveredEdge) : null;

    // Arestas
    current.edges.forEach((edge) => {
      const a = positions.get(edge.source);
      const b = positions.get(edge.target);
      if (!a || !b) return;
      const key = edgeKeyOf(edge);
      const active = key === current.selectedEdgeKey || key === activeEdgeKey;
      const inSearch =
        !current.hasSearch ||
        current.searchMatchIds.has(edge.source) ||
        current.searchMatchIds.has(edge.target);
      const baseAlpha = Math.min(0.62, 0.18 + edge.count * 0.045);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = active
        ? `rgba(251,191,36,${Math.min(0.95, baseAlpha + 0.3)})`
        : `rgba(125,211,252,${baseAlpha})`;
      ctx.globalAlpha = inSearch ? 1 : 0.12;
      ctx.lineWidth = active
        ? Math.max(3, Math.log(edge.count + 1) + 1.5)
        : Math.max(1.5, Math.log(edge.count + 1) + 0.5);
      ctx.stroke();
      ctx.globalAlpha = 1;
    });

    // Etiquetas com deteção simples de colisões (a última palavra é sempre visível).
    const labelBoxes: { x: number; y: number; width: number; height: number }[] = [];
    const drawLabel = (text: string, x: number, y: number, emphasised: boolean) => {
      ctx.font = emphasised ? "bold 12px ui-sans-serif, system-ui" : "600 10px ui-sans-serif, system-ui";
      const label = text.length > 22 ? `${text.slice(0, 20)}…` : text;
      const box = { x: x - 4, y: y - 10, width: ctx.measureText(label).width + 8, height: 16 };
      const collides = labelBoxes.some(
        (other) =>
          !(
            box.x + box.width < other.x ||
            other.x + other.width < box.x ||
            box.y + box.height < other.y ||
            other.y + other.height < box.y
          )
      );
      if (collides && !emphasised) return;
      labelBoxes.push(box);
      ctx.fillStyle = "rgba(3,12,17,0.88)";
      ctx.fillRect(box.x, box.y, box.width, box.height);
      ctx.fillStyle = emphasised ? "#ffffff" : "#dbeafe";
      ctx.fillText(label, x, y);
    };

    // Nós
    current.nodes.forEach((node) => {
      const p = positions.get(node.id);
      if (!p) return;
      const isSelected = current.selectedNodeId === node.id;
      const isHovered = current.hovered?.id === node.id;
      const isMatch = !current.hasSearch || current.searchMatchIds.has(node.id);
      const showLabel =
        isSelected || isHovered || node.type === "regiao" || (current.labelledIds.has(node.id) && isMatch);
      const radius = isSelected ? node.radius + 5 : isHovered ? node.radius + 3 : node.radius;
      ctx.globalAlpha = isMatch ? 1 : 0.18;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.shadowBlur = isSelected || isHovered ? 20 : 10;
      ctx.shadowColor = node.color;
      const fill = ctx.createRadialGradient(p.x - radius * 0.35, p.y - radius * 0.35, 1, p.x, p.y, radius);
      fill.addColorStop(0, node.color);
      fill.addColorStop(0.38, `${node.color}cc`);
      fill.addColorStop(1, "rgba(7,21,27,0.98)");
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = isSelected ? 4 : isHovered ? 3.5 : 2.5;
      ctx.strokeStyle = isSelected || isHovered ? "#ffffff" : node.color;
      ctx.stroke();
      if (showLabel) drawLabel(node.label, p.x + radius + 6, p.y + 3, isSelected || isHovered);
      ctx.globalAlpha = 1;
    });
  }, []);

  useEffect(() => {
    draw();
  }, [
    draw,
    hovered,
    hoveredEdge,
    labelledIds,
    nodeSearch,
    offset,
    renderEdges,
    renderNodes,
    scale,
    searchMatchIds,
    selectedEdgeKey,
    selectedNodeId,
    size,
    view,
  ]);

  /** Enquadra todos os nós visíveis (usado no arranque, no botão "Ajustar" e na tecla 0). */
  const fitToView = useCallback(() => {
    const canvas = canvasRef.current;
    const positions = positionsRef.current;
    const visibleNodes = frame.current.nodes;
    if (!canvas || visibleNodes.length === 0) return;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    visibleNodes.forEach((node) => {
      const p = positions.get(node.id);
      if (!p) return;
      minX = Math.min(minX, p.x - node.radius);
      maxX = Math.max(maxX, p.x + node.radius);
      minY = Math.min(minY, p.y - node.radius);
      maxY = Math.max(maxY, p.y + node.radius);
    });
    if (!Number.isFinite(minX) || !Number.isFinite(minY)) return;
    const rect = canvas.getBoundingClientRect();
    // Reserva espaço para os painéis sobrepostos (barra superior e filtros).
    const availableWidth = Math.max(120, rect.width - 128);
    const availableHeight = Math.max(120, rect.height - 96);
    const nextScale = Math.min(
      2.4,
      Math.max(
        0.35,
        Math.min(availableWidth / Math.max(maxX - minX, 1), availableHeight / Math.max(maxY - minY, 1))
      )
    );
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    setScale(nextScale);
    setOffset({ x: -centerX * nextScale, y: -centerY * nextScale });
  }, []);

  // Dimensiona o canvas pelo wrapper. O ResizeObserver + deps em `hasData`/`view` garantem o
  // dimensionamento mesmo quando o canvas só é montado depois de os dados chegarem, e o
  // reenquadramento automático evita que o grafo fique cortado se o cartão mudar de tamanho.
  // A medição do wrapper é feita sempre (mesmo sem canvas, como na vista de mapa) porque a
  // projeção do mapa depende das dimensões reais do contentor.
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const applySize = () => {
      const rect = wrapper.getBoundingClientRect();
      setSize((current) =>
        current.width === rect.width && current.height === rect.height
          ? current
          : { width: rect.width, height: rect.height }
      );
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextWidth = Math.max(1, Math.floor(rect.width * dpr));
      const nextHeight = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }
      if (!userMovedRef.current && positionsRef.current.size > 0) fitToView();
      draw();
    };
    applySize();
    const observer = new ResizeObserver(applySize);
    observer.observe(wrapper);
    window.addEventListener("resize", applySize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", applySize);
    };
  }, [draw, fitToView, hasData, isExpanded, isFullscreen, view]);

  const toGraphCoords = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: (clientX - rect.left - rect.width / 2 - offset.x) / scale,
      y: (clientY - rect.top - rect.height / 2 - offset.y) / scale,
    };
  };

  const hitTestNode = (x: number, y: number) => {
    const positions = positionsRef.current;
    return (
      frame.current.nodes.find((node) => {
        const p = positions.get(node.id);
        if (!p) return false;
        return Math.hypot(p.x - x, p.y - y) <= node.radius + 5;
      }) ?? null
    );
  };

  const hitTestEdge = (x: number, y: number, currentScale: number) => {
    const positions = positionsRef.current;
    return (
      frame.current.edges.find((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return false;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const lengthSquared = dx * dx + dy * dy || 1;
        const projection = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / lengthSquared));
        const nearX = a.x + projection * dx;
        const nearY = a.y + projection * dy;
        return Math.hypot(x - nearX, y - nearY) <= 9 / Math.max(currentScale, 0.3);
      }) ?? null
    );
  };

  // Pan com pointer events (rato, caneta e toque) e captura do ponteiro.
  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    draggingRef.current = true;
    dragMovedRef.current = false;
    lastPosRef.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (draggingRef.current) {
      const dx = event.clientX - lastPosRef.current.x;
      const dy = event.clientY - lastPosRef.current.y;
      lastPosRef.current = { x: event.clientX, y: event.clientY };
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        dragMovedRef.current = true;
        userMovedRef.current = true;
        setOffset((currentOffset) => ({ x: currentOffset.x + dx, y: currentOffset.y + dy }));
      }
      return;
    }
    const point = toGraphCoords(event.clientX, event.clientY);
    const node = hitTestNode(point.x, point.y);
    const edge = node ? null : hitTestEdge(point.x, point.y, scale);
    if ((node?.id ?? null) !== (hovered?.id ?? null)) setHovered(node);
    if (edge !== hoveredEdge) setHoveredEdge(edge);
    if (node || edge) {
      const rect = canvas.getBoundingClientRect();
      setMousePos({ x: event.clientX - rect.left, y: event.clientY - rect.top });
    }
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    draggingRef.current = false;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const handleCanvasClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragMovedRef.current) return;
    const point = toGraphCoords(event.clientX, event.clientY);
    const node = hitTestNode(point.x, point.y);
    if (node) {
      onNodeClick?.(node);
      return;
    }
    const edge = hitTestEdge(point.x, point.y, scale);
    if (edge) onEdgeClick?.(edge);
  };

  const handleCanvasKeyDown = (event: React.KeyboardEvent<HTMLCanvasElement>) => {
    const step = 48;
    const pan = (dx: number, dy: number) => {
      event.preventDefault();
      userMovedRef.current = true;
      setOffset((currentOffset) => ({ x: currentOffset.x + dx, y: currentOffset.y + dy }));
    };
    if (event.key === "ArrowLeft") pan(step, 0);
    else if (event.key === "ArrowRight") pan(-step, 0);
    else if (event.key === "ArrowUp") pan(0, step);
    else if (event.key === "ArrowDown") pan(0, -step);
    else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      setScale((current) => Math.min(3, current + 0.15));
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      setScale((current) => Math.max(0.35, current - 0.15));
    } else if (event.key === "0") {
      event.preventDefault();
      fitToView();
    }
  };

  // Zoom com scroll sem arrastar a página (listener não-passivo).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || view === "map" || view === "list") return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      userMovedRef.current = true;
      setScale((current) => Math.min(3, Math.max(0.35, current - event.deltaY * 0.0015)));
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [view]);

  useEffect(() => {
    if (view === "map" || view === "list") return;
    const data = frame.current;
    const positions = positionsRef.current;
    const canvas = canvasRef.current;
    const rect = canvas?.getBoundingClientRect();

    // Descarta posições de nós que já não pertencem à vista atual.
    const activeIds = new Set(data.nodes.map((node) => node.id));
    positions.forEach((_position, id) => {
      if (!activeIds.has(id)) positions.delete(id);
    });

    // Semeia posições determinísticas (em anéis por grupo, quando pedido).
    const groups = new Map<string, SimNode[]>();
    if (options.groupByRegion) {
      data.nodes.forEach((node) => {
        const bucket = groups.get(node.group) ?? [];
        bucket.push(node);
        groups.set(node.group, bucket);
      });
    }
    const groupKeys = [...groups.keys()];
    data.nodes.forEach((node, index) => {
      if (positions.has(node.id)) return;
      const bucket = groups.get(node.group) ?? [];
      positions.set(
        node.id,
        seedPosition(
          options.groupByRegion ? Math.max(bucket.indexOf(node), 0) : index,
          options.groupByRegion ? Math.max(bucket.length, 1) : data.nodes.length,
          options.groupByRegion ? Math.max(groupKeys.indexOf(node.group), 0) : 0,
          options.groupByRegion ? Math.max(groupKeys.length, 1) : 1
        )
      );
    });

    // Layouts determinísticos: anel (circular) e camadas (hierárquico).
    const applyDeterministicLayout = () => {
      const width = rect?.width ?? 900;
      const height = rect?.height ?? 600;
      if (view === "circular") {
        const ordered = [...data.nodes].sort(
          (a, b) => b.degree - a.degree || (b.contracts ?? 0) - (a.contracts ?? 0)
        );
        const isRegionRing = ordered.length > 0 && ordered.every((node) => node.type === "regiao");
        const radius = isRegionRing
          ? Math.max(120, Math.min(260, Math.min(width, height) * 0.3))
          : Math.max(140, Math.min(360, Math.min(width, height) * 0.38));
        ordered.forEach((node, index) => {
          const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2 - Math.PI / 2;
          positions.set(node.id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, vx: 0, vy: 0 });
        });
        return;
      }
      const laneOf = (node: SimNode) =>
        node.type === "adjudicante" || node.type === "regiao" ? 0 : node.type === "adjudicatario" ? 2 : 1;
      [0, 1, 2].forEach((lane) => {
        const laneNodes = data.nodes.filter((node) => laneOf(node) === lane);
        const spacing = Math.max(64, Math.min(210, width / Math.max(laneNodes.length, 1)));
        laneNodes.forEach((node, index) => {
          positions.set(node.id, {
            x: (index - (laneNodes.length - 1) / 2) * spacing,
            y: (lane - 1) * 170,
            vx: 0,
            vy: 0,
          });
        });
      });
    };

    // Repulsão em grelha espacial (O(n)) em vez de O(n²): escala para redes densas.
    const cell = 170;
    const runNetworkStep = () => {
      const grid = new Map<string, SimNode[]>();
      data.nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        const key = `${Math.floor(p.x / cell)}:${Math.floor(p.y / cell)}`;
        const bucket = grid.get(key) ?? [];
        bucket.push(node);
        grid.set(key, bucket);
      });
      data.nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        const cx = Math.floor(p.x / cell);
        const cy = Math.floor(p.y / cell);
        for (let gx = cx - 1; gx <= cx + 1; gx++) {
          for (let gy = cy - 1; gy <= cy + 1; gy++) {
            const bucket = grid.get(`${gx}:${gy}`);
            if (!bucket) continue;
            bucket.forEach((other) => {
              if (other.id <= node.id) return;
              const q = positions.get(other.id);
              if (!q) return;
              const dx = p.x - q.x;
              const dy = p.y - q.y;
              const dist = Math.sqrt(dx * dx + dy * dy) || 1;
              if (dist > cell * 3) return;
              const force = (2600 * node.mass * other.mass) / (dist * dist);
              const fx = (dx / dist) * force;
              const fy = (dy / dist) * force;
              p.vx += fx / node.mass;
              p.vy += fy / node.mass;
              q.vx -= fx / other.mass;
              q.vy -= fy / other.mass;
            });
          }
        }
      });
      data.edges.forEach((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = ((dist - 96) * 0.025) / 2;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });
      let energy = 0;
      data.nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        p.vx = (p.vx - p.x * 0.003) * 0.88;
        p.vy = (p.vy - p.y * 0.003) * 0.88;
        p.x += p.vx;
        p.y += p.vy;
        energy += Math.abs(p.vx) + Math.abs(p.vy);
      });
      return energy / Math.max(data.nodes.length, 1);
    };

    // Só enquadra automaticamente se o utilizador ainda não mexeu na vista.
    const finish = () => {
      if (userMovedRef.current) return;
      fitToView();
    };

    if (view === "circular" || view === "hierarchical") {
      applyDeterministicLayout();
      draw();
      finish();
      return;
    }

    // Sem movimento animado quando o sistema pede menos animações: assenta o layout de imediato.
    const reduceMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
    if (reduceMotion) {
      for (let tick = 0; tick < 320; tick++) runNetworkStep();
      draw();
      finish();
      return;
    }

    let raf = 0;
    let ticks = 0;
    const loop = () => {
      const energy = runNetworkStep();
      draw();
      ticks += 1;
      // Para quando o layout estabilizou (ou após o limite de iterações).
      if (ticks < 480 && Number.isFinite(energy) && energy > 0.4) {
        raf = requestAnimationFrame(loop);
      } else {
        finish();
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [draw, fitToView, layoutKey, options.groupByRegion, view]);

  const labelForId = (id: string) => nodes.find((node) => node.id === id)?.label ?? id;

  const tooltipVisible = Boolean(hovered || hoveredEdge);
  const tooltipStyle = {
    left: Math.max(8, Math.min(mousePos.x + 16, Math.max(size.width - 248, 8))),
    top: Math.max(8, Math.min(mousePos.y + 16, Math.max(size.height - 112, 8))),
  };

  const hoveredInfo = hovered ? (
    <div
      className="pointer-events-none absolute z-30 w-[236px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl"
      style={tooltipStyle}
    >
      <p className="text-sm font-medium text-foreground break-words">{hovered.label}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{nodeTypeLabel(hovered.type)}</p>
      <p className="mt-1 text-xs text-teal-300">
        {hovered.type === "regiao" ? `${compact(hovered.contracts ?? 0)} contratos` : `${hovered.degree} ligações`}
        {hovered.approx ? " · localização aproximada" : ""}
      </p>
      <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">
        {hovered.type === "contrato" ? "Clique para abrir o contrato" : "Clique para expandir"}
      </p>
    </div>
  ) : hoveredEdge ? (
    <div
      className="pointer-events-none absolute z-30 w-[236px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl"
      style={tooltipStyle}
    >
      <p className="text-xs text-teal-300 break-words">{labelForId(hoveredEdge.source)}</p>
      <p className="text-xs text-blue-300 break-words">
        <ArrowRight size={11} className="mr-1 inline" />
        {labelForId(hoveredEdge.target)}
      </p>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {hoveredEdge.count} contratos · <span className="text-foreground">{money(hoveredEdge.value)}</span>
      </p>
      <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">Clique na linha para ver contratos</p>
    </div>
  ) : null;

  /**
   * Projeção Mercator: converte lat/lon em pixels do mundo e centra o mapa no canvas.
   * A grelha de tiles é calculada a partir do tamanho real do canvas (sem offsets fixos),
   * garantindo que os nós caem exatamente sobre os tiles.
   */
  const mapProjection = useMemo(() => {
    const zoom = mapZoom;
    const width = size.width || 800;
    const height = size.height || 520;
    const centerX = lonToWorld(mapCenter.lon, zoom);
    const centerY = latToWorld(mapCenter.lat, zoom);
    const worldTiles = 2 ** zoom;

    const firstTileX = Math.floor((centerX - width / 2) / TILE_SIZE);
    const lastTileX = Math.floor((centerX + width / 2) / TILE_SIZE);
    const firstTileY = Math.max(0, Math.floor((centerY - height / 2) / TILE_SIZE));
    const lastTileY = Math.min(worldTiles - 1, Math.floor((centerY + height / 2) / TILE_SIZE));

    const tiles: { key: string; url: string; left: number; top: number }[] = [];
    for (let tileY = firstTileY; tileY <= lastTileY; tileY++) {
      for (let tileX = firstTileX; tileX <= lastTileX; tileX++) {
        const wrappedX = ((tileX % worldTiles) + worldTiles) % worldTiles;
        tiles.push({
          key: `${zoom}/${wrappedX}/${tileY}`,
          url: `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${tileY}.png`,
          left: width / 2 + (tileX * TILE_SIZE - centerX),
          top: height / 2 + (tileY * TILE_SIZE - centerY),
        });
      }
    }

    return {
      tiles,
      project: (lat: number, lon: number) => ({
        left: width / 2 + (lonToWorld(lon, zoom) - centerX),
        top: height / 2 + (latToWorld(lat, zoom) - centerY),
      }),
    };
  }, [mapCenter.lat, mapCenter.lon, mapZoom, size.height, size.width]);

  /**
   * Nós posicionáveis no mapa. Entidades não têm coordenadas nos dados: quando o grafo
   * está limitado a uma região, são espalhadas em torno do centroide dessa região
   * (marcadas como aproximadas); caso contrário não são desenhadas (não se inventam posições).
   */
  const regionCenter = useMemo(() => (regionHint ? lookupPlace(regionHint, regionHint) : null), [regionHint]);

  const mapNodes = useMemo(
    () =>
      renderNodes.flatMap((node) => {
        if (node.lat != null && node.lon != null) {
          return [{ node, lat: node.lat, lon: node.lon, approximated: Boolean(node.approx) }];
        }
        if (regionCenter) {
          const point = jitterAround(regionCenter, node.id);
          return [{ node, lat: point.lat, lon: point.lon, approximated: true }];
        }
        return [];
      }),
    [regionCenter, renderNodes]
  );
  const approximateNodes = mapNodes.filter((entry) => entry.approximated).length;
  const unplacedNodes = renderNodes.length - mapNodes.length;

  /**
   * Enquadra o mapa nos nós visíveis (inclui ilhas e nós estrangeiros) na primeira vez que
   * a vista é aberta, ou quando o conjunto de nós/modo muda. Não reenquadra depois de o
   * utilizador ter feito zoom manualmente.
   */
  useEffect(() => {
    if (view !== "map" || mapNodes.length === 0) return;
    const key = `${regionHint ?? "todos"}|${mapNodes.length}|${Math.round(size.width)}x${Math.round(size.height)}`;
    if (mapFitKeyRef.current === key || mapManualRef.current) return;
    mapFitKeyRef.current = key;

    const lats = mapNodes.map((entry) => entry.lat);
    const lons = mapNodes.map((entry) => entry.lon);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const width = Math.max(320, size.width || 800);
    const height = Math.max(240, size.height || 520);

    let zoom = 4;
    for (let candidate = 11; candidate >= 3; candidate--) {
      const spanX = lonToWorld(maxLon, candidate) - lonToWorld(minLon, candidate);
      const spanY = latToWorld(minLat, candidate) - latToWorld(maxLat, candidate);
      if (spanX <= width - 120 && spanY <= height - 120) {
        zoom = candidate;
        break;
      }
    }

    setMapCenter({ lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 });
    setMapZoom(zoom);
  }, [mapFitNonce, mapNodes, regionHint, size.height, size.width, view]);

  const mapRadius = (radius: number) => Math.max(5, Math.min(13, radius * 0.45));

  const mapBounds = () => {
    const width = Math.max(320, size.width || 800);
    const height = Math.max(240, size.height || 520);
    return { width, height };
  };

  /** Mantém um ponto geográfico debaixo do cursor/ponto de referência após mudar de zoom. */
  const zoomMapAt = (deltaZoom: number, anchor?: { x: number; y: number }) => {
    const nextZoom = Math.max(3, Math.min(18, mapZoom + deltaZoom));
    if (nextZoom === mapZoom) return;
    const { width, height } = mapBounds();
    const offsetX = (anchor?.x ?? width / 2) - width / 2;
    const offsetY = (anchor?.y ?? height / 2) - height / 2;
    const anchorLon = worldToLon(lonToWorld(mapCenter.lon, mapZoom) + offsetX, mapZoom);
    const anchorLat = worldToLat(latToWorld(mapCenter.lat, mapZoom) + offsetY, mapZoom);
    const centerX = lonToWorld(anchorLon, nextZoom) - offsetX;
    const centerY = latToWorld(anchorLat, nextZoom) - offsetY;
    mapManualRef.current = true;
    setMapZoom(nextZoom);
    setMapCenter({ lat: worldToLat(centerY, nextZoom), lon: worldToLon(centerX, nextZoom) });
  };

  const panMapBy = (dx: number, dy: number) => {
    const centerX = lonToWorld(mapCenter.lon, mapZoom) - dx;
    const centerY = latToWorld(mapCenter.lat, mapZoom) - dy;
    mapManualRef.current = true;
    setMapCenter({ lat: worldToLat(centerY, mapZoom), lon: worldToLon(centerX, mapZoom) });
  };

  /** Um evento que caia sobre a barra de ferramentas/caixa de pesquisa não navega o mapa. */
  const isMapChrome = (target: EventTarget | null) => {
    const element = target as HTMLElement | null;
    if (!element?.closest) return false;
    if (element.closest("input")) return true;
    const button = element.closest("button");
    return Boolean(button && !button.hasAttribute("data-map-node"));
  };

  const handleMapPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (view !== "map" || event.button !== 0 || isMapChrome(event.target)) return;
    mapDragRef.current = { x: event.clientX, y: event.clientY, lat: mapCenter.lat, lon: mapCenter.lon };
    mapDragMovedRef.current = false;
    mapWheelAccumRef.current = 0;
    setMapDragging(true);
    // Captura o ponteiro para continuar a navegar mesmo que o cursor saia do mapa.
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Alguns apontadores não suportam captura; o arrastar continua a funcionar dentro do mapa.
    }
  };

  const handleMapPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = mapDragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!mapDragMovedRef.current && Math.hypot(dx, dy) < 4) return;
    mapDragMovedRef.current = true;
    // Arrasta o conteúdo com o cursor: o centro desloca-se no sentido inverso ao movimento.
    const centerX = lonToWorld(drag.lon, mapZoom) - dx;
    const centerY = latToWorld(drag.lat, mapZoom) - dy;
    mapManualRef.current = true;
    setMapCenter({ lat: worldToLat(centerY, mapZoom), lon: worldToLon(centerX, mapZoom) });
  };

  const handleMapPointerUp = () => {
    mapDragRef.current = null;
    setMapDragging(false);
  };

  const handleMapDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (view !== "map" || isMapChrome(event.target)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    zoomMapAt(1, { x: event.clientX - rect.left, y: event.clientY - rect.top });
  };

  const fitMapToNodes = () => {
    mapManualRef.current = false;
    mapFitKeyRef.current = "";
    setMapFitNonce((nonce) => nonce + 1);
  };

  // Zoom com a roda do rato/apontador, ancorado no cursor (listener não-passivo).
  // A referência à função mais recente evita re-subscrir o listener a cada movimento do mapa.
  const zoomMapAtRef = useRef(zoomMapAt);
  zoomMapAtRef.current = zoomMapAt;
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || view !== "map") return;
    const onWheel = (event: WheelEvent) => {
      if (isMapChrome(event.target)) return;
      event.preventDefault();
      mapWheelAccumRef.current += event.deltaY;
      if (Math.abs(mapWheelAccumRef.current) < 100) return;
      const direction = mapWheelAccumRef.current < 0 ? 1 : -1;
      mapWheelAccumRef.current = 0;
      const rect = wrapper.getBoundingClientRect();
      zoomMapAtRef.current(direction, { x: event.clientX - rect.left, y: event.clientY - rect.top });
    };
    wrapper.addEventListener("wheel", onWheel, { passive: false });
    return () => wrapper.removeEventListener("wheel", onWheel);
  }, [view]);

  const handleMapKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = 96;
    if (event.key === "ArrowLeft") panMapBy(step, 0);
    else if (event.key === "ArrowRight") panMapBy(-step, 0);
    else if (event.key === "ArrowUp") panMapBy(0, step);
    else if (event.key === "ArrowDown") panMapBy(0, -step);
    else if (event.key === "+" || event.key === "=") zoomMapAt(1);
    else if (event.key === "-" || event.key === "_") zoomMapAt(-1);
    else if (event.key === "0") fitMapToNodes();
    else return;
    event.preventDefault();
  };

  const handleMapSurfaceClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (view !== "map" || mapDragMovedRef.current || (event.target as HTMLElement).closest("button")) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const clickY = event.clientY - rect.top;
    const nearest = mapNodes
      .map((entry) => {
        const position = mapProjection.project(entry.lat, entry.lon);
        return { node: entry.node, distance: Math.hypot(position.left - clickX, position.top - clickY) };
      })
      .sort((a, b) => a.distance - b.distance)[0];
    if (nearest && nearest.distance <= 55) onNodeClick?.(nearest.node);
  };

  return (
    <div
      ref={wrapperRef}
      onClick={handleMapSurfaceClick}
      onPointerDown={handleMapPointerDown}
      onPointerMove={handleMapPointerMove}
      onPointerUp={handleMapPointerUp}
      onPointerLeave={handleMapPointerUp}
      onPointerCancel={handleMapPointerUp}
      onDoubleClick={handleMapDoubleClick}
      className={[
        // `absolute inset-0` (e não `h-full`) porque a altura do cartão vem de `min-height`:
        // percentagens não resolvem nesse caso e o canvas colapsaria para 0.
        isExpanded ? "fixed inset-3 z-[70] shadow-2xl" : "absolute inset-0",
        "rounded-2xl border border-white/10 bg-[#07151b] overflow-hidden",
        view === "map" && (mapDragging ? "cursor-grabbing" : "cursor-grab"),
      ].join(" ")}
    >
      {/* Barra de ferramentas */}
      <div className="pointer-events-auto absolute top-3 right-3 z-40 flex flex-col items-end gap-2 rounded-2xl bg-[#07151b]/80 p-1.5 backdrop-blur-sm">
        <div className="relative">
          <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-[#07151b]/95 px-2 py-1.5 shadow-xl">
            <Search size={14} className="text-muted-foreground" />
            <input
              value={nodeSearch}
              type="text"
              onChange={(event) => {
                setNodeSearch(event.target.value);
                setSearchFocused(false);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && searchMatches[0]) onNodeClick?.(searchMatches[0]);
                if (event.key === "Escape") {
                  setNodeSearch("");
                  setSearchFocused(false);
                }
              }}
              placeholder="Pesquisar no grafo…"
              aria-label="Pesquisar nós no grafo"
              aria-expanded={Boolean(nodeSearch) && searchMatches.length > 0}
              aria-controls="graph-search-results"
              className="w-40 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground sm:w-48"
            />
            {nodeSearch && <span className="text-[10px] text-teal-300">{searchMatches.length}</span>}
            {nodeSearch && searchMatches.length > 0 && (
              <button
                type="button"
                onClick={() => setSearchFocused((focused) => !focused)}
                aria-pressed={searchFocused}
                aria-label={searchFocused ? "Mostrar grafo completo" : "Destacar apenas os resultados da pesquisa"}
                title={searchFocused ? "Mostrar grafo completo" : "Destacar apenas os resultados da pesquisa"}
                className={searchFocused ? "rounded bg-teal-400/20 p-1 text-teal-200" : "rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-teal-200"}
              >
                <Network size={13} />
              </button>
            )}
            {nodeSearch && (
              <button
                type="button"
                onClick={() => {
                  setNodeSearch("");
                  setSearchFocused(false);
                }}
                aria-label="Limpar pesquisa"
                title="Limpar pesquisa (Esc)"
                className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
              >
                <X size={13} />
              </button>
            )}
          </div>
          {nodeSearch && searchMatches.length > 0 && (
            <div
              id="graph-search-results"
              className="absolute right-0 top-full mt-1 w-64 overflow-hidden rounded-lg border border-white/10 bg-[#07151b]/98 shadow-xl"
            >
              {searchMatches.map((match) => (
                <button
                  key={match.id}
                  type="button"
                  onClick={() => onNodeClick?.(match)}
                  className="block w-full border-b border-white/5 px-3 py-2 text-left last:border-0 hover:bg-white/10"
                >
                  <span className="block truncate text-xs text-foreground">{match.label}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">
                    {nodeTypeLabel(match.type)} · {match.id}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {(["network", "hierarchical", "circular", "map", "list"] as GraphView[]).map((v) => {
            const disabled = disabledViews.includes(v);
            const label =
              v === "network"
                ? "Orgânica"
                : v === "hierarchical"
                ? "Hierárquica"
                : v === "circular"
                ? "Circular"
                : v === "map"
                ? "Mapa"
                : "Lista";
            return (
              <button
                key={v}
                type="button"
                onClick={() => onViewChange(v)}
                disabled={disabled}
                aria-pressed={view === v}
                title={disabled ? disabledHint : `Vista ${label}`}
                className={[
                  "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
                  view === v
                    ? "border-teal-400/30 bg-teal-400/15 text-teal-300"
                    : "glass-card border-white/10 hover:bg-white/5",
                  disabled ? "cursor-not-allowed opacity-40 hover:bg-transparent" : "",
                ].join(" ")}
              >
                {v === "network" && <Network size={14} />}
                {v === "hierarchical" && <GitBranch size={14} />}
                {v === "circular" && <Circle size={14} />}
                {v === "map" && <MapPin size={14} />}
                {v === "list" && <List size={14} />}
                {label}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => void toggleFullscreen()}
            aria-label={isFullscreen || isExpanded ? "Sair do ecrã inteiro" : "Abrir ecrã inteiro"}
            title={isFullscreen || isExpanded ? "Sair do ecrã inteiro (Esc)" : "Abrir ecrã inteiro"}
            className="glass-card flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          >
            {isFullscreen || isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            {isFullscreen || isExpanded ? "Sair" : "Ecrã inteiro"}
          </button>
        </div>
        <div className="self-end rounded-lg border border-white/10 bg-[#07151b]/90 px-2.5 py-1 text-right text-[11px] leading-4 text-muted-foreground">
          {view === "map" ? (
            <span className="block">Arraste para navegar · roda para zoom · duplo clique aproxima</span>
          ) : (
            <span className="block">Clique num nó para expandir · linha para ver contratos</span>
          )}
        </div>
      </div>

      {/* Legenda dinâmica: só as categorias presentes na vista atual */}
      <div className="pointer-events-none absolute left-3 top-3 z-20 hidden max-w-[55%] flex-wrap gap-x-3 gap-y-1 rounded-lg border border-white/10 bg-[#07151b]/85 px-2.5 py-1.5 text-[11px] sm:flex">
        {legendTypes.map((type) => (
          <span key={type} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: NODE_COLORS[type] || NODE_COLORS.outra }} />
            {nodeTypeLabel(type)}
          </span>
        ))}
      </div>

      {hoveredInfo}

      <p className="sr-only" aria-live="polite">
        {`Vista ${view}. ${renderNodes.length} nós e ${renderEdges.length} ligações visíveis.`}
      </p>

      {!hasData && view !== "list" ? (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-muted-foreground">
          <Search size={32} className="mb-3 opacity-40" />
          <p className="text-sm">Sem dados para visualizar</p>
          <p className="mt-1 max-w-xs text-center text-xs">
            {emptyHint ?? "Escolha uma região na lista lateral ou alivie os filtros do grafo."}
          </p>
        </div>
      ) : view === "list" ? (
        <div className="absolute inset-0 z-10 overflow-auto bg-[#07151b] p-4 pt-20">
          <div className="mb-3 flex items-center justify-between gap-3 border-b border-white/10 pb-2 text-xs text-muted-foreground">
            <span className="truncate">
              {renderNodes.length} nós por centralidade
              {nodeSearch.trim() ? ` · pesquisa "${nodeSearch.trim()}"` : ""}
            </span>
            <span className="shrink-0">Selecione um nó para navegar</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {[...renderNodes]
              .sort((a, b) => b.degree - a.degree || (b.contracts ?? 0) - (a.contracts ?? 0))
              .map((node) => (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => onNodeClick?.(node)}
                  className="rounded-xl border border-white/10 bg-white/[0.04] p-3 text-left transition hover:border-teal-300/50 hover:bg-white/[0.08] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                >
                  <span className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: node.color }} />
                    <span className="truncate text-sm text-foreground">{node.label}</span>
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {nodeTypeLabel(node.type)} ·{" "}
                    {node.type === "regiao" ? `${compact(node.contracts ?? 0)} contratos` : `${node.degree} ligações`}
                  </span>
                </button>
              ))}
          </div>
          {renderNodes.length === 0 && <p className="py-12 text-center text-sm text-muted-foreground">Sem nós para apresentar.</p>}
        </div>
      ) : view === "map" ? (
        <div
          tabIndex={0}
          role="application"
          aria-label="Mapa interativo: arraste para deslocar, roda do rato para zoom, setas para navegar, 0 para reenquadrar"
          onKeyDown={handleMapKeyDown}
          className="relative h-full w-full touch-none overflow-hidden bg-[#0a1f29] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          {/* Tiles OpenStreetMap (grelha calculada pelo canvas) */}
          {mapProjection.tiles.map((t) => (
            <img
              key={t.key}
              src={t.url}
              alt=""
              draggable={false}
              decoding="async"
              className="absolute opacity-70 transition-opacity duration-300"
              style={{ left: t.left, top: t.top, width: TILE_SIZE, height: TILE_SIZE }}
              onLoad={() => setTilesLoaded((count) => count + 1)}
              onError={() => setTilesLoaded((count) => count + 1)}
            />
          ))}
          {tilesLoaded < mapProjection.tiles.length && mapProjection.tiles.length > 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-muted-foreground">
              <RefreshCw size={16} className="mr-2 animate-spin" /> A carregar mapa…
            </div>
          )}

          {/* Nós sobrepostos ao mapa */}
          <div className="absolute inset-0 z-10">
            {mapNodes.map(({ node, lat, lon, approximated }) => {
              const pos = mapProjection.project(lat, lon);
              return (
                <button
                  key={node.id}
                  type="button"
                  data-map-node="true"
                  onClick={(event) => {
                    // Um arrastar do mapa não deve abrir o nó onde o gesto terminou.
                    if (mapDragMovedRef.current) return;
                    event.stopPropagation();
                    onNodeClick?.(node);
                  }}
                  className="absolute z-10 flex -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/60"
                  style={{ left: pos.left, top: pos.top }}
                  aria-label={`${node.label} — ${nodeTypeLabel(node.type)}`}
                  title={`${node.label}${approximated ? " (posição aproximada)" : ""}`}
                >
                  <span
                    className="rounded-full border-2 shadow-[0_2px_8px_rgba(0,0,0,0.6)]"
                    style={{
                      width: mapRadius(node.radius) * 2,
                      height: mapRadius(node.radius) * 2,
                      background: "rgba(8,28,36,0.95)",
                      borderColor: node.color,
                      borderStyle: approximated ? "dashed" : "solid",
                      opacity: approximated ? 0.75 : 1,
                    }}
                  />
                  <span className="mt-0.5 whitespace-nowrap rounded bg-[#07151b]/90 px-1.5 py-0.5 text-[9px] text-white shadow-sm">
                    {node.label.length > 14 ? `${node.label.slice(0, 12)}…` : node.label}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Controlos do mapa (com atribuição obrigatória do OpenStreetMap) */}
          <div className="absolute bottom-3 right-3 z-20 flex flex-wrap items-center justify-end gap-2">
            {mapNodes.length > 0 && (
              <span className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[10px] text-muted-foreground">
                {mapNodes.length} nós no mapa
              </span>
            )}
            {approximateNodes > 0 && (
              <span
                className="flex items-center gap-1.5 rounded-lg border border-amber-300/25 bg-[#07151b]/90 px-2 py-1 text-[10px] text-amber-200"
                title={
                  regionCenter
                    ? `${approximateNodes} de ${mapNodes.length} nós não têm coordenadas próprias: foram espalhados dentro de ${regionHint}.`
                    : `${approximateNodes} de ${mapNodes.length} nós sem coordenadas próprias.`
                }
              >
                <Info size={12} />
                {approximateNodes}/{mapNodes.length} aproximadas
              </span>
            )}
            {unplacedNodes > 0 && (
              <span
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[10px] text-muted-foreground"
                title="Entidades não têm coordenadas nos dados. Selecione uma região para as posicionar dentro dessa área."
              >
                <Info size={12} />
                {unplacedNodes} sem localização
              </span>
            )}
            <a
              href="https://www.openstreetmap.org/copyright"
              target="_blank"
              rel="noreferrer noopener"
              className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[10px] text-muted-foreground hover:text-teal-300"
            >
              © OpenStreetMap
            </a>
            <span className="flex items-center rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[11px] text-muted-foreground">
              Nível {mapZoom}
            </span>
            <button
              type="button"
              onClick={fitMapToNodes}
              aria-label="Reenquadrar mapa nos nós"
              title="Reenquadrar mapa nos nós"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <Crosshair size={16} />
            </button>
            <button
              type="button"
              onClick={() => zoomMapAt(1)}
              disabled={mapZoom >= 18}
              aria-label="Aproximar mapa"
              title="Aproximar mapa"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ZoomIn size={16} />
            </button>
            <button
              type="button"
              onClick={() => zoomMapAt(-1)}
              disabled={mapZoom <= 3}
              aria-label="Afastar mapa"
              title="Afastar mapa"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ZoomOut size={16} />
            </button>
          </div>
        </div>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            role="img"
            tabIndex={0}
            aria-label={`Grafo interativo com ${renderNodes.length} nós e ${renderEdges.length} ligações. Use as setas para mover, mais e menos para zoom, zero para ajustar à vista.`}
            className={`absolute inset-0 h-full w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-400/50 ${
              tooltipVisible ? "cursor-pointer" : "cursor-move"
            }`}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={() => {
              draggingRef.current = false;
              setHovered(null);
              setHoveredEdge(null);
            }}
            onClick={handleCanvasClick}
            onKeyDown={handleCanvasKeyDown}
          />
          <div className="absolute bottom-3 right-3 z-20 flex items-center gap-2">
            <span className="flex items-center rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[11px] text-muted-foreground">
              {Math.round(scale * 100)}%
            </span>
            <button
              type="button"
              onClick={() => {
                userMovedRef.current = false;
                positionsRef.current.clear();
                setLayoutRun((run) => run + 1);
              }}
              aria-label="Voltar a calcular o layout"
              title="Voltar a calcular o layout"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <Shuffle size={16} />
            </button>
            <button
              type="button"
              onClick={() => {
                userMovedRef.current = true;
                fitToView();
              }}
              aria-label="Ajustar à vista"
              title="Ajustar à vista (0)"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <Scan size={16} />
            </button>
            <button
              type="button"
              onClick={() => setScale((current) => Math.min(3, current + 0.2))}
              aria-label="Aproximar"
              title="Aproximar (+)"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomIn size={16} />
            </button>
            <button
              type="button"
              onClick={() => setScale((current) => Math.max(0.35, current - 0.2))}
              aria-label="Afastar"
              title="Afastar (-)"
              className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomOut size={16} />
            </button>
          </div>
        </>
      )}

      {/* Painel de filtros: colapsável, com contadores em direto */}
      <div className="absolute bottom-3 left-3 z-20 w-[250px] overflow-hidden rounded-xl border border-white/10 bg-[#07151b]/95 shadow-xl">
        <button
          type="button"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
          aria-controls="graph-filter-panel"
          className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-400/50"
        >
          <Filter size={12} />
          Filtros
          {activeFilterCount > 0 && (
            <span className="rounded-full bg-teal-400/20 px-1.5 text-[10px] font-medium text-teal-200">
              {activeFilterCount}
            </span>
          )}
          <span className="ml-auto flex items-center gap-1 text-[10px] font-normal text-muted-foreground">
            {renderNodes.length} nós · {renderEdges.length} arestas
          </span>
          <ChevronDown size={13} className={`transition-transform ${filtersOpen ? "" : "-rotate-90"}`} />
        </button>

        <div id="graph-filter-panel" className={filtersOpen ? "space-y-2 px-3 pb-3" : "hidden"}>
          <div className="flex items-center justify-between gap-2">
            <label className="text-[11px] text-muted-foreground" htmlFor="graph-max-nodes">
              Máx. nós
            </label>
            <input
              id="graph-max-nodes"
              type="range"
              min={10}
              max={Math.max(maxNodes, 100)}
              value={Math.min(options.nodeLimit || maxNodes, maxNodes)}
              aria-valuetext={`${Math.min(options.nodeLimit || maxNodes, maxNodes)} nós`}
              onChange={(event) => {
                const value = Number(event.target.value);
                setOptions((current) => ({
                  ...current,
                  nodeLimit: value >= maxNodes ? Number.MAX_SAFE_INTEGER : value,
                }));
              }}
              className="w-24 rounded accent-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            />
            <span className="w-8 text-right text-[11px]">
              {(options.nodeLimit || 0) >= maxNodes ? "Todos" : options.nodeLimit}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <label className="text-[11px] text-muted-foreground" htmlFor="graph-max-edges">
              Máx. arestas
            </label>
            <input
              id="graph-max-edges"
              type="range"
              min={10}
              max={Math.max(maxEdges, 400)}
              value={Math.min(options.edgeLimit || maxEdges, maxEdges)}
              aria-valuetext={`${Math.min(options.edgeLimit || maxEdges, maxEdges)} arestas`}
              onChange={(event) => {
                const value = Number(event.target.value);
                setOptions((current) => ({
                  ...current,
                  edgeLimit: value >= maxEdges ? Number.MAX_SAFE_INTEGER : value,
                }));
              }}
              className="w-24 rounded accent-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            />
            <span className="w-8 text-right text-[11px]">
              {(options.edgeLimit || 0) >= maxEdges ? "Todas" : options.edgeLimit}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <label className="text-[11px] text-muted-foreground" htmlFor="graph-min-value">
              Valor mín.
            </label>
            <input
              id="graph-min-value"
              type="number"
              min={0}
              step={1000}
              value={options.minValue}
              aria-label="Valor mínimo do contrato em euros"
              onChange={(event) => setOptions((current) => ({ ...current, minValue: Number(event.target.value) }))}
              className="w-20 rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[11px] focus:outline-none focus-visible:border-teal-400/50 focus-visible:ring-1 focus-visible:ring-teal-400/30"
            />
          </div>
          <p className="text-right text-[10px] text-muted-foreground">
            {options.minValue > 0 ? `≥ ${money(options.minValue)}` : "sem limite de valor"}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            {[
              { key: "showAdjudicantes", label: "Adjudicantes" },
              { key: "showAdjudicatarios", label: "Adjudicatários" },
              { key: "showContracts", label: "Contratos" },
              { key: "pruneLeaves", label: "Sem folhas" },
              { key: "hideSupernodes", label: "Ocultar supernós" },
              {
                key: "groupByRegion",
                label: isRegionLevel ? "Agrupar por região" : "Agrupar por tipo",
              },
            ].map((opt) => {
              const key = opt.key as keyof typeof options;
              const checked = Boolean(options[key]);
              const hint =
                key === "pruneLeaves"
                  ? "Esconde nós com uma única ligação"
                  : key === "hideSupernodes"
                  ? "Esconde nós com muitas ligações (supernós)"
                  : key === "groupByRegion"
                  ? "Dispõe os nós em anéis agrupados"
                  : `Mostrar ${opt.label.toLowerCase()}`;
              return (
                <label key={opt.key} title={hint} className="flex cursor-pointer select-none items-center gap-1.5 text-[11px]">
                  <span className="relative inline-flex h-4 w-4 items-center justify-center rounded border border-white/20 bg-white/5 transition focus-within:ring-2 focus-within:ring-teal-400/50">
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      checked={checked}
                      onChange={(event) => setOptions((current) => ({ ...current, [key]: event.target.checked }))}
                    />
                    <svg
                      className={`h-3 w-3 text-teal-400 transition ${checked ? "opacity-100" : "opacity-0"}`}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  {opt.label}
                </label>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => setOptions({ ...DEFAULT_GRAPH_OPTIONS })}
            disabled={activeFilterCount === 0}
            className="mt-1 w-full rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Repor filtros
          </button>
          <p className="text-[10px] leading-4 text-muted-foreground">
            Arrastar para mover · scroll para zoom · 0 ajusta à vista
          </p>
        </div>
      </div>
    </div>
  );
}

// --- Unified module sidebar (legacy AppNav style, scoped to EmpresasIQ) ---

type PlatformView =
  | "chat"
  | "dashboard"
  | "search"
  | "contracts-search"
  | "contracts-dashboard"
  | "companies-search"
  | "companies-dashboard"
  | "tickers"
  | "forecast"
  | "trading"
  | "rag"
  | "elastic"
  | "settings"
  | "cli";

interface NavGroup {
  id: string;
  label: string;
  icon: React.ElementType;
  items: { id: EmpresasIQSection | PlatformView; label: string; icon: React.ElementType; isPlatform?: boolean }[];
}

function ModuleSidebar({
  activeSection,
  onSectionChange,
  onNavigate,
}: {
  activeSection: EmpresasIQSection;
  onSectionChange: (s: EmpresasIQSection) => void;
  onNavigate: (view: PlatformView) => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    module: true,
    platform: false,
  });
  const { favorites: sidebarFavorites } = useFavorites();
  const { hidden: sidebarHidden, toggle: toggleSidebar } = useSidebarHidden();
  const { user: sidebarUser, logout } = useAuth();

  const navRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (mobileOpen) {
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") setMobileOpen(false);
      };
      document.addEventListener("keydown", onKey);
      return () => {
        document.body.style.overflow = originalOverflow;
        document.removeEventListener("keydown", onKey);
      };
    }
  }, [mobileOpen]);

  const groups: NavGroup[] = [
    {
      id: "module",
      label: "EmpresasIQ",
      icon: Network,
      items: [
        { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
        { id: "contracts", label: "Contratos Públicos", icon: FileSearch },
        { id: "entities", label: "Entidades", icon: Building2 },
        { id: "graph", label: "Grafo de Relações", icon: Network },
        { id: "studio", label: "Grafos & Visualizações", icon: GitBranch },
        { id: "analysis", label: "Análise e Relatórios", icon: BarChart3 },
        { id: "favorites", label: "Favoritos", icon: FolderHeart },
        { id: "settings", label: "Configurações", icon: Settings },
      ],
    },
    {
      id: "platform",
      label: "Plataforma",
      icon: LayoutDashboard,
      items: [
        { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, isPlatform: true },
        { id: "chat", label: "Chat IA", icon: MessageSquare, isPlatform: true },
        { id: "search", label: "Pesquisa Global", icon: Search, isPlatform: true },
        { id: "contracts-search", label: "Pesquisar Contratos", icon: FileText, isPlatform: true },
        { id: "contracts-dashboard", label: "Dashboard Contratos", icon: BarChart3, isPlatform: true },
        { id: "companies-search", label: "Pesquisar Empresas", icon: Building2, isPlatform: true },
        { id: "companies-dashboard", label: "Dashboard Empresas", icon: BarChart3, isPlatform: true },
        { id: "tickers", label: "Tickers & Ações", icon: TrendingUp, isPlatform: true },
        { id: "forecast", label: "Previsões", icon: Sparkles, isPlatform: true },
        { id: "trading", label: "Trading Simulado", icon: CandlestickChart, isPlatform: true },
        { id: "rag", label: "RAG Documentos", icon: FolderOpen, isPlatform: true },
        { id: "elastic", label: "Elasticsearch", icon: Database, isPlatform: true },
      ],
    },
  ];

  const toggleGroup = (id: string) => {
    setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleItem = (item: NavGroup["items"][number]) => {
    if (item.isPlatform) {
      onNavigate(item.id as PlatformView);
    } else {
      onSectionChange(item.id as EmpresasIQSection);
    }
    setMobileOpen(false);
  };

  const navContent = (
    <nav className="flex flex-col h-full">
      <div className="p-4 border-b border-border/60 flex items-center gap-2">
        <button
          onClick={() => onNavigate("chat")}
          className="flex-1 min-w-0 flex items-center gap-3 px-3 py-2.5 rounded-xl glass-card hover:bg-white/5 transition text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Sparkles size={16} />
          </div>
          <div className="leading-tight">
            <p className="font-semibold text-sm">FinanceLLM</p>
            <p className="text-[11px] text-muted-foreground">Voltar à plataforma</p>
          </div>
        </button>
        <button
          onClick={toggleSidebar}
          aria-label="Ocultar barra lateral"
          title="Ocultar barra lateral (Ctrl+B)"
          className="hidden md:grid shrink-0 place-items-center h-9 w-9 rounded-xl text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          <PanelLeftClose size={17} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-3 px-3 space-y-1">
        {groups.map((group) => {
          const expanded = openGroups[group.id] ?? false;
          return (
            <div key={group.id} className="mb-1">
              <button
                onClick={() => toggleGroup(group.id)}
                aria-expanded={expanded}
                className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition text-muted-foreground hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
              >
                <span className="flex items-center gap-2.5">
                  <span className="text-muted-foreground"><group.icon size={18} /></span>
                  {group.label}
                </span>
                <ChevronDown
                  size={16}
                  className={`transition-transform ${expanded ? "rotate-180" : ""}`}
                />
              </button>
              {expanded && (
                <div className="mt-1 ml-2 pl-3 border-l border-border/60 space-y-0.5">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const isActive = !item.isPlatform && activeSection === item.id;
                    return (
                      <button
                        key={`${group.id}-${item.id}`}
                        onClick={() => handleItem(item)}
                        aria-current={isActive ? "page" : undefined}
                        className={[
                          "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40",
                          isActive
                            ? "bg-teal-400/15 text-teal-300 font-medium border border-teal-400/20"
                            : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
                        ].join(" ")}
                      >
                        <span className={isActive ? "text-teal-300" : "text-muted-foreground/80"}>
                          <Icon size={18} />
                        </span>
                        {item.label}
                        {item.id === "favorites" && sidebarFavorites.length > 0 && (
                          <span className="ml-auto rounded-full bg-rose-400/20 px-1.5 py-0.5 text-[10px] font-medium text-rose-200">
                            {sidebarFavorites.length}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="p-4 border-t border-border/60">
        <button
          type="button"
          onClick={() => onNavigate("settings")}
          className="w-full flex items-center gap-3 rounded-xl glass-card px-3 py-2.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          {sidebarUser ? <Avatar user={sidebarUser} size={32} /> : null}
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm font-medium">{sidebarUser?.name ?? "Conta"}</span>
            <span className="block truncate text-[11px] text-muted-foreground">
              {sidebarUser?.title || sidebarUser?.email || "Definições da conta"}
            </span>
          </span>
          <Settings size={15} className="text-muted-foreground" />
        </button>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => onNavigate("settings")}
            className="flex-1 rounded-xl border border-white/10 px-2 py-1.5 text-[11px] text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
          >
            Definições
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex-1 rounded-xl border border-rose-400/20 px-2 py-1.5 text-[11px] text-rose-200 transition hover:bg-rose-400/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50"
          >
            Terminar sessão
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <>
      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 h-14 glass-panel border-b border-border/60 flex items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center text-white">
            <Sparkles size={14} />
          </div>
          <span className="font-semibold text-sm">EmpresasIQ</span>
        </div>
        <button
          onClick={() => setMobileOpen((v) => !v)}
          className="p-2 rounded-lg hover:bg-white/5 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          aria-label="Menu"
          aria-expanded={mobileOpen}
          aria-controls="empresasiq-mobile-nav"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-40 pt-14">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onPointerDown={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setMobileOpen(false);
            }}
            aria-hidden="true"
          />
          <div
            id="empresasiq-mobile-nav"
            ref={navRef}
            className="absolute top-14 left-0 bottom-0 w-[280px] bg-background/95 backdrop-blur-xl shadow-2xl"
          >
            {navContent}
          </div>
        </div>
      )}

      {/* Pega para voltar a mostrar a barra lateral (desktop). */}
      {sidebarHidden && (
        <button
          onClick={toggleSidebar}
          aria-label="Mostrar barra lateral"
          title="Mostrar barra lateral (Ctrl+B)"
          className="hidden md:flex fixed left-0 top-1/2 -translate-y-1/2 z-40 items-center rounded-r-2xl border border-l-0 border-white/10 bg-[#111318]/92 py-4 pl-1 pr-1.5 text-muted-foreground shadow-lg backdrop-blur-xl transition hover:pr-4 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <ChevronRight size={16} />
        </button>
      )}

      {/* Desktop sidebar */}
      <aside
        aria-hidden={sidebarHidden || undefined}
        inert={sidebarHidden || undefined}
        style={sidebarHidden ? { borderWidth: 0 } : undefined}
        className={[
          "hidden md:flex shrink-0 h-screen glass-panel flex-col overflow-hidden transition-[width,opacity] duration-300 ease-out",
          sidebarHidden ? "w-0 opacity-0 border-0" : "w-[220px] opacity-100 border-r border-border/60",
        ].join(" ")}
      >
        <div className="w-[220px] shrink-0 h-full">{navContent}</div>
      </aside>
    </>
  );
}

// --- Topbar ---

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
    <header className="h-16 border-b border-white/10 bg-[#07151b]/80 backdrop-blur flex items-center justify-between px-4 sticky top-0 z-30">
      <label className="flex items-center gap-3 flex-1 max-w-2xl">
        <Search size={18} className="text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Pesquisar entidades, contratos, NIF, CPV, palavras-chave..."
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground focus:ring-0"
        />
      </label>
      <div className="flex items-center gap-2">
        <button
          onClick={onSearch}
          className="px-4 py-2 rounded-xl bg-teal-400/10 text-teal-300 border border-teal-400/20 text-sm hover:bg-teal-400/20 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          Pesquisar
        </button>
        <button
          className="p-2 rounded-xl hover:bg-white/5 text-muted-foreground transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          aria-label="Configurações"
          title="Configurações"
        >
          <Settings size={18} />
        </button>
        <div
          className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-400 to-blue-500 flex items-center justify-center text-xs font-bold text-white"
          aria-label="Utilizador PM"
          title="Utilizador PM"
        >
          PM
        </div>
      </div>
    </header>
  );
}

// --- Empty state ---

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <Search size={36} className="mb-3 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// --- Loading ---

function Loading() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
      <RefreshCw size={32} className="animate-spin mb-3" />
      <p className="text-sm">A carregar inteligência contratual...</p>
    </div>
  );
}

// --- DASHBOARD ---

function DashboardSection({
  analytics,
  regional,
  status,
  onContracts,
  onEntities,
  onGraph,
  onEntity,
}: {
  analytics: ContractAnalyticsResponse | null;
  regional: ContractRegionalResponse | null;
  status: { total: number; years: number[] } | null;
  onContracts: () => void;
  onEntities: () => void;
  onGraph: () => void;
  onEntity: (nif: string) => void;
}) {
  const total = analytics?.total_contracts ?? status?.total ?? 0;
  const topEntities = analytics?.top_entities ?? [];
  const topCpv = analytics?.top_cpv ?? [];
  const byYear = useMemo(
    () => [...(analytics?.by_year ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)),
    [analytics],
  );
  const maxEntity = Math.max(...topEntities.map((r) => r.total_value || 0), 1);
  const maxCpv = Math.max(...topCpv.map((r) => r.total_value || 0), 1);
  const byProcedure = analytics?.procedure_types ?? [];

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="relative overflow-hidden min-h-[260px] flex flex-col justify-between">
          <div className="relative z-10">
            <p className="text-xs uppercase tracking-wider text-teal-400 mb-2">
              EmpresasIQ / Contratos Públicos
            </p>
            <h1 className="text-3xl md:text-4xl font-bold leading-tight">
              Explore o universo dos contratos públicos
            </h1>
            <p className="mt-3 max-w-xl text-sm text-muted-foreground">
              Descubra entidades, contratos e relações através de gráficos interativos,
              análises e mapas territoriais.
            </p>
          </div>
          <div className="relative z-10 mt-6 flex flex-wrap gap-3">
            <button
              onClick={onContracts}
              className="px-4 py-2.5 rounded-xl bg-teal-400/10 text-teal-300 border border-teal-400/20 text-sm hover:bg-teal-400/20 transition flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <Search size={16} /> Pesquisar Contratos
            </button>
            <button
              onClick={onGraph}
              className="px-4 py-2.5 rounded-xl glass-card hover:bg-white/5 text-sm transition flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <Network size={16} /> Explorar Grafo de Relações
            </button>
            <button
              onClick={onEntities}
              className="px-4 py-2.5 rounded-xl glass-card hover:bg-white/5 text-sm transition flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <BarChart3 size={16} /> Ver Análises e Relatórios
            </button>
          </div>
          <div
            className="absolute right-0 top-0 bottom-0 w-1/2 opacity-30 pointer-events-none"
            style={{
              background:
                "radial-gradient(circle at 80% 50%, rgba(45,212,191,0.35), transparent 70%)",
            }}
          />
        </Card>
        <Card className="relative overflow-hidden flex items-center justify-center">
          <div className="absolute inset-0 opacity-20 network-bg" />
          <div className="relative z-10 text-center">
            <Network size={48} className="mx-auto text-teal-400 mb-3" />
            <p className="text-sm font-medium">Rede ativa</p>
            <p className="text-xs text-muted-foreground mt-1">
              {full(analytics?.total_contracts)} contratos · {regional?.regions.length ?? 0}{" "}
              regiões
            </p>
          </div>
        </Card>
      </div>

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          icon={FileSearch}
          value={compact(total)}
          label="Total de Contratos"
          change="+12% vs ano anterior"
        />
        <Kpi
          icon={Building2}
          value={compact(topEntities.length)}
          label="Entidades no Grafo"
          change="Dados indexados"
          color="text-blue-400"
        />
        <Kpi
          icon={Users}
          value={compact(topEntities.length)}
          label="Top Entidades Distintas"
          change="Por valor adjudicado"
          color="text-violet-400"
        />
        <Kpi
          icon={HandCoins}
          value={money(analytics?.total_value)}
          label="Valor Total Adjudicado"
          change="+7% vs ano anterior"
          color="text-amber-400"
        />
      </div>

      {/* Charts + tables */}
      <div className="grid gap-6 xl:grid-cols-[1fr_0.4fr]">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold">Evolução do valor adjudicado</h3>
              <p className="text-xs text-muted-foreground">Valor total por ano</p>
            </div>
            <Badge color="teal">EUR</Badge>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={byYear}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10a37f" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#10a37f" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="key" stroke="rgba(255,255,255,0.3)" fontSize={12} />
                <YAxis
                  stroke="rgba(255,255,255,0.3)"
                  fontSize={12}
                  tickFormatter={(v) => compact(v)}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(7,21,27,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                  }}
                  formatter={euroFormatter}
                />
                <Area
                  type="monotone"
                  dataKey="total_value"
                  stroke="#10a37f"
                  fillOpacity={1}
                  fill="url(#colorValue)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold">Por tipo de contrato</h3>
              <p className="text-xs text-muted-foreground">Distribuição percentual</p>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <RePieChart>
                <Pie
                  data={byProcedure.slice(0, 6)}
                  dataKey="count"
                  nameKey="key"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={3}
                  label={percentPieLabel}
                >
                  {byProcedure.slice(0, 6).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "rgba(7,21,27,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                  }}
                  formatter={countFormatter}
                />
              </RePieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr_0.6fr]">
        <Card>
          <h3 className="font-semibold mb-4">Entidades com maior volume</h3>
          <div className="space-y-4">
            {topEntities.slice(0, 7).map((row) => (
              <button
                key={row.key}
                onClick={() => onEntity(row.key)}
                className="w-full text-left group focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded-lg"
              >
                <div className="flex justify-between gap-4 text-sm mb-1">
                  <span className="truncate text-foreground group-hover:text-teal-300 transition">
                    {row.description || row.key}
                  </span>
                  <span className="text-muted-foreground shrink-0">{money(row.total_value)}</span>
                </div>
                <MiniBar value={row.total_value || 0} max={maxEntity} />
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">Top Categorias (CPV)</h3>
          <div className="space-y-4">
            {topCpv.slice(0, 7).map((row) => (
              <div key={row.key}>
                <div className="flex justify-between gap-4 text-sm mb-1">
                  <span className="truncate">{row.description || row.key}</span>
                  <span className="text-muted-foreground shrink-0">{money(row.total_value)}</span>
                </div>
                <MiniBar value={row.total_value || 0} max={maxCpv} color="bg-amber-400" />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">Pulso regional</h3>
          <div className="space-y-3">
            {(regional?.regions ?? [])
              .sort((a, b) => (b.total_value || 0) - (a.total_value || 0))
              .slice(0, 6)
              .map((region) => (
                <div
                  key={region.key}
                  className="flex items-center justify-between rounded-xl bg-white/[0.03] px-3 py-2.5 border border-white/5"
                >
                  <span className="text-sm flex items-center gap-2">
                    <MapPin size={14} className="text-teal-400" />
                    {region.key}
                  </span>
                  <span className="text-sm font-medium text-primary">{money(region.total_value)}</span>
                </div>
              ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// --- CONTRACTS ---

function ContractsSection({
  onContract,
  onEntity,
}: {
  onContract: (_id: string) => void;
  onEntity: (_nif: string) => void;
}) {
  const [filters, setFilters] = useState<ContractSearchRequest>({ size: 15, from: 0 });
  const debouncedFilters = useDebounce(filters, 400);
  const [data, setData] = useState<ContractSearchResponse | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    getContractYears()
      .then((y) => setYears(y.available ?? []))
      .catch(() => setYears([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    searchContracts(debouncedFilters)
      .then(setData)
      .finally(() => setLoading(false));
  }, [debouncedFilters]);

  const apply = () => {
    const f: ContractSearchRequest = { size: 15, from: 0 };
    if (q.trim()) f.q = q.trim();
    if (year !== "") f.year = year;
    setFilters(f);
  };

  const reset = () => {
    setQ("");
    setYear("");
    setFilters({ size: 15, from: 0 });
  };

  const contracts = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold">Contratos Públicos</h2>
          <p className="text-sm text-muted-foreground">
            {full(total)} resultados disponíveis
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters((s) => !s)}
            className={`px-3 py-2 rounded-xl text-sm flex items-center gap-2 transition ${
              showFilters
                ? "bg-teal-400/10 text-teal-300 border border-teal-400/20"
                : "glass-card hover:bg-white/5"
            }`}
          >
            <Filter size={16} /> Filtros
          </button>
          <button
            disabled
            title="Exportação brevemente disponível"
            className="px-3 py-2 rounded-xl glass-card text-sm flex items-center gap-2 opacity-60 cursor-not-allowed"
          >
            <Download size={16} /> Exportar
          </button>
        </div>
      </div>

      {showFilters && (
        <Card>
          <div className="grid gap-4 md:grid-cols-4 items-end">
            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">Palavra-chave</label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-2.5 text-muted-foreground" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && apply()}
                  placeholder="Objeto, entidade, CPV..."
                  className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 pl-9 pr-3 text-sm outline-none focus:border-teal-400/50 focus:ring-1 focus:ring-teal-400/30"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1.5" htmlFor="contracts-year">Ano</label>
              <select
                id="contracts-year"
                value={year}
                onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 px-3 text-sm outline-none focus:border-teal-400/50 focus:ring-1 focus:ring-teal-400/30"
              >
                <option value="">Todos</option>
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={apply}
              className="px-4 py-2 rounded-xl bg-teal-400/10 text-teal-300 border border-teal-400/20 text-sm hover:bg-teal-400/20 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              Aplicar
            </button>
            <button
              onClick={reset}
              className="px-4 py-2 rounded-xl glass-card hover:bg-white/5 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              Limpar
            </button>
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        {loading ? (
          <Loading />
        ) : contracts.length === 0 ? (
          <EmptyState message="Nenhum contrato encontrado." />
        ) : (
          <div
            className="overflow-x-auto pr-1"
            role="region"
            aria-label="Lista de contratos públicos"
            style={{ scrollbarWidth: "thin" }}
          >
            <table className="w-full text-sm border-collapse table-fixed" style={{ minWidth: "100%" }}>
              <thead className="sticky top-0 bg-[#0b0f19]/95 backdrop-blur-sm z-10">
                <tr className="border-b border-white/10 text-left text-muted-foreground text-xs uppercase tracking-wider">
                  <th className="py-3 px-3 font-medium w-[90px] min-w-[90px]">Nº Contrato</th>
                  <th className="py-3 px-3 font-medium w-[22%] min-w-[220px]">Objeto</th>
                  <th className="py-3 px-3 font-medium w-[16%] min-w-[160px]">Entidade Adjudicante</th>
                  <th className="py-3 px-3 font-medium w-[16%] min-w-[160px]">Entidade Adjudicatária</th>
                  <th className="py-3 px-3 font-medium w-[90px] min-w-[90px]">Data</th>
                  <th className="py-3 px-3 font-medium text-right w-[110px] min-w-[110px]">Valor (€)</th>
                  <th className="py-3 px-3 font-medium w-[100px] min-w-[100px]">Tipo</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map((c, idx) => {
                  const adjSource = nifFromParty(c.adjudicantes);
                  const adjTarget = nifFromParty(c.adjudicatarios);
                  return (
                    <tr
                      key={c.idcontrato || c.doc_id || idx}
                      className="border-b border-white/5 hover:bg-white/[0.04] transition"
                    >
                      <td className="py-3 px-3 font-medium text-teal-300 align-top truncate" title={`Abrir contrato ${c.idcontrato || ""}`}>
                        <button
                          onClick={() => c.idcontrato && onContract(c.idcontrato)}
                          className="hover:underline text-left truncate w-full"
                        >
                          {c.idcontrato || "—"}
                        </button>
                      </td>
                      <td className="py-3 px-3 align-top truncate" title={c.objectoContrato || ""}>
                        <span className="line-clamp-2">
                          {c.objectoContrato || "—"}
                        </span>
                      </td>
                      <td className="py-3 px-3 align-top truncate">
                        <button
                          onClick={() => adjSource && onEntity(adjSource)}
                          className="text-left hover:text-teal-300 transition line-clamp-2 w-full"
                          title={partyNames(c.adjudicantes)}
                        >
                          {partyNames(c.adjudicantes)}
                        </button>
                      </td>
                      <td className="py-3 px-3 align-top truncate">
                        <button
                          onClick={() => adjTarget && onEntity(adjTarget)}
                          className="text-left hover:text-teal-300 transition line-clamp-2 w-full"
                          title={partyNames(c.adjudicatarios)}
                        >
                          {partyNames(c.adjudicatarios)}
                        </button>
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap text-muted-foreground align-top">
                        {fmtDate(c.dataPublicacao || c.dataCelebracaoContrato)}
                      </td>
                      <td className="py-3 px-3 text-right font-medium tabular-nums align-top">
                        {money(c.precoContratual ?? c.PrecoTotalEfetivo)}
                      </td>
                      <td className="py-3 px-3 align-top">
                        <Badge color="blue">{c.tipoContrato || "—"}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {contracts.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mt-4 text-sm text-muted-foreground px-5 pb-5">
            <p>
              Mostrando {contracts.length} de {full(total)}
            </p>
            <div className="flex items-center gap-2">
              <button
                disabled={filters.from === 0}
                onClick={() => setFilters((f) => ({ ...f, from: Math.max(0, (f.from ?? 0) - 15) }))}
                className="px-3 py-1.5 rounded-lg glass-card disabled:opacity-40 hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                aria-label="Página anterior"
              >
                Anterior
              </button>
              <span className="text-xs px-2 py-1 rounded-md bg-white/5 border border-white/10" aria-live="polite">
                Página {Math.floor((filters.from ?? 0) / 15) + 1}
              </span>
              <button
                disabled={(filters.from ?? 0) + contracts.length >= total}
                onClick={() =>
                  setFilters((f) => ({ ...f, from: (f.from ?? 0) + 15 }))
                }
                className="px-3 py-1.5 rounded-lg glass-card disabled:opacity-40 hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                aria-label="Próxima página"
              >
                Próximo
              </button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

// --- ENTITIES ---

function EntitiesSection({
  onEntity,
}: {
  onEntity: (_nif: string) => void;
}) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState<"all" | "adjudicante" | "adjudicatario">("all");
  const [data, setData] = useState<CompanySearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [from, setFrom] = useState(0);

  const load = async (offset = 0) => {
    setLoading(true);
    try {
      const res = await searchCompanies({
        q: q.trim() || undefined,
        role,
        size: 15,
        from: offset,
      });
      setData(res);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(0);
    setFrom(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, role]);

  const companies = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold">Entidades</h2>
          <p className="text-sm text-muted-foreground">
            {full(total)} entidades no universo
          </p>
        </div>
      </div>

      <Card>
        <div className="grid gap-4 md:grid-cols-3 items-end">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-2.5 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load(0)}
              placeholder="Nome, NIF..."
              className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 pl-9 pr-3 text-sm outline-none focus:border-teal-400/50 focus:ring-1 focus:ring-teal-400/30"
            />
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 px-3 text-sm outline-none focus:border-teal-400/50 focus:ring-1 focus:ring-teal-400/30"
          >
            <option value="all">Todas as funções</option>
            <option value="adjudicante">Adjudicante</option>
            <option value="adjudicatario">Adjudicatário</option>
          </select>
          <button
            onClick={() => load(0)}
            className="px-4 py-2 rounded-xl bg-teal-400/10 text-teal-300 border border-teal-400/20 text-sm hover:bg-teal-400/20 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          >
            Pesquisar
          </button>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {loading && companies.length === 0 && <Loading />}
        {companies.map((company) => (
          <button
            key={company.nif || company.normalized_name}
            onClick={() => company.nif && onEntity(company.nif)}
            className="text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 rounded-xl"
          >
            <Card className="hover:border-teal-400/30 transition group">
              <div className="flex items-start justify-between">
                <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-400/20 group-hover:bg-teal-400/10 group-hover:border-teal-400/30 transition">
                  <Building2 size={20} className="text-blue-400 group-hover:text-teal-300" />
                </div>
                <Badge color={company.adjudicante ? "blue" : "teal"}>
                  {company.adjudicante ? "Adjudicante" : "Adjudicatário"}
                </Badge>
              </div>
              <p className="mt-4 font-semibold line-clamp-2">{company.name}</p>
              <p className="text-xs text-muted-foreground mt-1">NIF {company.nif || "—"}</p>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Contratos</p>
                  <p className="font-semibold">{full(company.contracts_total)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Valor total</p>
                  <p className="font-semibold text-amber-400">{money(company.total_value)}</p>
                </div>
              </div>
            </Card>
          </button>
        ))}
      </div>

      {!loading && companies.length > 0 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <p>
            Mostrando {from + 1}–{from + companies.length} de {full(total)}
          </p>
          <div className="flex items-center gap-2">
            <button
              disabled={from === 0}
              onClick={() => {
                const next = Math.max(0, from - 15);
                setFrom(next);
                load(next);
              }}
              className="px-3 py-1.5 rounded-lg glass-card disabled:opacity-40 hover:bg-white/5"
            >
              Anterior
            </button>
            <button
              disabled={from + companies.length >= total}
              onClick={() => {
                const next = from + 15;
                setFrom(next);
                load(next);
              }}
              className="px-3 py-1.5 rounded-lg glass-card disabled:opacity-40 hover:bg-white/5"
            >
              Próximo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function errMsg(e: unknown, fallback = "Erro") {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return fallback;
}

// --- GRAPH ---

function GraphSection({
  onEntity,
  onContract,
  onStudio,
}: {
  onEntity: (nif: string) => void;
  onContract: (id: string) => void;
  onStudio?: () => void;
}) {
  const [regions, setRegions] = useState<ContractRegionalRow[]>([]);
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [regionNetwork, setRegionNetwork] = useState<ContractGraphResponse | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<SimNode | null>(null);
  const [entityNetwork, setEntityNetwork] = useState<ContractGraphResponse | null>(null);
  const [entityContracts, setEntityContracts] = useState<ContractItem[]>([]);
  const [relations, setRelations] = useState<ContractRelationsResponse | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [pairSelection, setPairSelection] = useState<{ nif: string; counterpartyNif: string } | null>(null);
  const [pairContracts, setPairContracts] = useState<ContractItem[] | null>(null);
  const [view, setView] = useState<GraphView>("network");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [pairSize] = useState(50);
  const requestVersionRef = useRef(0);

  const activeRegion = selectedRegion;
  // Todos os grupos regionais entram no grafo, incluindo "Não especificado" (contratos sem NUTs).
  const regionOverviewGraph = useMemo<ContractGraphResponse>(
    () => ({
      nodes: regions.map((region) => ({
        id: region.key,
        label: region.key,
        type: "regiao",
        count: region.count ?? 0,
        total_value: region.total_value ?? 0,
      })),
      edges: [],
    }),
    [regions]
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getContractRegionalAnalytics()
      .then((res) => {
        if (cancelled) return;
        const sorted = [...(res.regions ?? [])].sort(
          (a, b) => (b.count ?? 0) - (a.count ?? 0)
        );
        setRegions(sorted);
      })
      .catch((e) => setError(errMsg(e, "Erro ao carregar regiões")))
      .finally(() => setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeRegion) {
      // Ao voltar às regiões só "Orgânica"/"Hierárquica" deixam de fazer sentido.
      setView((current) => (current === "network" || current === "hierarchical" ? "circular" : current));
      setRegionNetwork(null);
      setSelectedEntity(null);
      setEntityNetwork(null);
      setEntityContracts([]);
      setRelations(null);
      setSelectedEdgeKey(null);
      setPairSelection(null);
      setPairContracts(null);
      return;
    }
    let cancelled = false;
    const requestVersion = ++requestVersionRef.current;
    setView("network");
    setLoading(true);
    setError(null);
    setSelectedEntity(null);
    setEntityNetwork(null);
    setEntityContracts([]);
    setSelectedEdgeKey(null);
    setPairSelection(null);
    setPairContracts(null);
    Promise.all([
      getContractNetwork(300, activeRegion),
      getContractRelations(500, activeRegion),
    ])
      .then(([net, rel]) => {
        if (cancelled || requestVersion !== requestVersionRef.current) return;
        setRegionNetwork(net);
        setRelations(rel);
      })
      .catch((e) => {
        if (!cancelled && requestVersion === requestVersionRef.current) {
          setError(errMsg(e, "Erro ao carregar rede regional"));
        }
      })
      .finally(() => {
        if (!cancelled && requestVersion === requestVersionRef.current) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRegion]);

  const handleSelectEntity = useCallback(
    (node: SimNode) => {
      if (!activeRegion) return;
      const nif = node.id;
      setSelectedEntity(node);
      setEntityNetwork(null);
      setEntityContracts([]);
      setSelectedEdgeKey(null);
      setPairSelection(null);
      setPairContracts(null);
      const requestVersion = ++requestVersionRef.current;
      setLoading(true);
      Promise.all([
        getContractNetwork(200, activeRegion, nif, "all"),
        getContractRelations(300, activeRegion, nif),
        searchContracts({ nif, region: activeRegion, from: 0, size: 100 }),
      ])
        .then(([net, rel, contracts]) => {
          if (requestVersion !== requestVersionRef.current) return;
          setEntityNetwork(net);
          setRelations(rel);
          setEntityContracts(contracts.items ?? []);
        })
        .catch((e) => {
          if (requestVersion === requestVersionRef.current) setError(errMsg(e, "Erro ao carregar entidade"));
        })
        .finally(() => {
          if (requestVersion === requestVersionRef.current) setLoading(false);
        });
    },
    [activeRegion]
  );

  const handleSelectGraphNode = useCallback(
    (node: SimNode) => {
      if (node.type === "contrato" && node.contractId) {
        onContract(node.contractId);
        return;
      }
      if (!activeRegion) {
        setSelectedRegion(node.id);
        return;
      }
      handleSelectEntity(node);
    },
    [activeRegion, handleSelectEntity, onContract]
  );

  const handleSelectRelation = useCallback(
    (rel: ContractRelation) => {
      if (!activeRegion) return;
      setSelectedEdgeKey([rel.source, rel.target].sort().join("-"));
      setPairSelection({ nif: rel.source, counterpartyNif: rel.target });
      setPairContracts(null);
      const requestVersion = ++requestVersionRef.current;
      setLoading(true);
      searchContracts({
        nif: rel.source,
        counterparty_nif: rel.target,
        region: activeRegion,
        from: 0,
        size: pairSize,
      })
        .then((res) => {
          if (requestVersion === requestVersionRef.current) setPairContracts(res.items ?? []);
        })
        .catch((e) => {
          if (requestVersion === requestVersionRef.current) setError(errMsg(e, "Erro ao carregar contratos do par"));
        })
        .finally(() => {
          if (requestVersion === requestVersionRef.current) setLoading(false);
        });
    },
    [activeRegion, pairSize]
  );

  const handleSelectEdge = useCallback(
    (edge: SimEdge) => {
      setSelectedEdgeKey([edge.source, edge.target].sort().join("-"));
      const relation = (relations?.relations ?? []).find(
        (candidate) =>
          (candidate.source === edge.source && candidate.target === edge.target) ||
          (candidate.source === edge.target && candidate.target === edge.source)
      );
      if (relation) handleSelectRelation(relation);
    },
    [handleSelectRelation, relations]
  );

  const entityGraphWithContracts = useMemo(() => {
    if (!entityNetwork || !selectedEntity || entityContracts.length === 0) return entityNetwork;
    const entityIds = new Set(entityNetwork.nodes.map((node) => node.id));
    const contractNodes = entityContracts
      .filter((contract) => Boolean(contract.idcontrato))
      .map((contract) => ({
        id: `contract:${contract.idcontrato}`,
        contract_id: contract.idcontrato,
        label: contract.objectoContrato ?? contract.descContrato ?? contract.idcontrato ?? "Contrato",
        type: "contrato",
      }));
    const contractEdges = entityContracts.flatMap((contract) => {
      if (!contract.idcontrato) return [];
      const contractId = `contract:${contract.idcontrato}`;
      const participantIds = [...nifsFromParty(contract.adjudicantes), ...nifsFromParty(contract.adjudicatarios)]
        .filter((nif) => entityIds.has(nif));
      return participantIds.map((nif) => ({
        source: contractId,
        target: nif,
        count: 1,
        value: contract.precoContratual ?? contract.PrecoTotalEfetivo ?? 0,
      }));
    });
    return {
      ...entityNetwork,
      nodes: [...entityNetwork.nodes, ...contractNodes],
      edges: [...entityNetwork.edges, ...contractEdges],
    };
  }, [entityContracts, entityNetwork, selectedEntity]);

  const activeNetwork = selectedEntity ? entityGraphWithContracts : activeRegion ? regionNetwork : regionOverviewGraph;
  // Sem override silencioso: no nível de regiões os layouts de força ficam desativados na barra.
  const graphView = view;
  const disabledGraphViews: GraphView[] = activeRegion ? [] : ["network", "hierarchical"];
  const activeNodeId = selectedEntity?.id ?? null;

  const legendEntries = useMemo(() => {
    const types = new Set((activeNetwork?.nodes ?? []).map((node) => node.type));
    const entries = NODE_LEGEND.filter((entry) => types.has(entry.type));
    return entries.length > 0 ? entries : NODE_LEGEND;
  }, [activeNetwork]);

  const breadcrumb = useMemo(() => {
    const steps: { label: string; onClick?: () => void }[] = [
      {
        label: "Regiões",
        // Permite voltar ao nível das regiões diretamente pelo breadcrumb.
        onClick: activeRegion
          ? () => {
              setSelectedRegion(null);
              setSelectedEntity(null);
              setEntityNetwork(null);
              setEntityContracts([]);
              setRelations(null);
              setSelectedEdgeKey(null);
              setPairSelection(null);
              setPairContracts(null);
            }
          : undefined,
      },
    ];
    if (activeRegion) {
      const r = regions.find((x) => x.key === activeRegion);
      steps.push({
        label: r?.key ?? activeRegion,
        onClick: () => {
          setSelectedEntity(null);
          setEntityNetwork(null);
          setPairSelection(null);
          setPairContracts(null);
        },
      });
    }
    if (selectedEntity) {
      steps.push({
        label: selectedEntity.label,
        onClick: () => {
          setPairSelection(null);
          setPairContracts(null);
        },
      });
    }
    if (pairSelection) {
      steps.push({ label: "Contratos do par" });
    }
    return steps;
  }, [activeRegion, regions, selectedEntity, pairSelection]);

  const topRelations = useMemo(
    () => (relations?.relations ?? []).slice(0, 50),
    [relations]
  );

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold">Grafo de Entidades e Contratos</h2>
          <p className="text-sm text-muted-foreground">
            {selectedEntity
              ? `Entidade: ${selectedEntity.label}`
              : activeRegion
              ? `${activeNetwork?.nodes.length ?? 0} entidades · ${activeNetwork?.edges.length ?? 0} ligações`
              : `${regions.length} regiões · selecione um nó para explorar`}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            {[
              ["Regiões", !activeRegion],
              ["Entidades", Boolean(activeRegion) && !selectedEntity],
              ["Relações", Boolean(selectedEntity) && !pairSelection],
              ["Contratos", Boolean(pairSelection)],
            ].map(([label, active]) => (
              <span
                key={label as string}
                className={active ? "rounded-full border border-teal-300/40 bg-teal-300/10 px-2.5 py-1 text-teal-200" : "text-muted-foreground"}
              >
                {label as string}
              </span>
            ))}
          </div>
        </div>
        {onStudio && (
          <button
            type="button"
            onClick={onStudio}
            className="glass-card flex shrink-0 items-center gap-2 self-start rounded-xl border border-white/10 px-3 py-2 text-xs hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 md:self-end"
            title="Construir grafos por dimensões (CPV, território, concorrência, fluxos de valor)"
          >
            <GitBranch size={14} className="text-teal-300" />
            Grafos &amp; Visualizações
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100 flex items-center gap-2">
          <AlertCircle size={16} />
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-xs underline">
            Dispensar
          </button>
        </div>
      )}

      <div className="flex flex-col xl:flex-row gap-4 w-full flex-1 min-h-0 xl:max-h-[calc(100vh-15rem)]">
        <Card className="p-0 overflow-hidden min-w-0 flex-1 w-full flex flex-col min-h-[520px]">
          {/* Breadcrumb toolbar */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-[#07151b]/80">
            <div className="flex items-center gap-1.5 text-sm min-w-0">
              {breadcrumb.map((step, idx) => (
                <div key={idx} className="flex items-center gap-1.5 min-w-0">
                  {idx > 0 && (
                    <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                  )}
                  {step.onClick ? (
                    <button
                      onClick={step.onClick}
                      className="text-teal-300 hover:underline truncate min-w-0"
                    >
                      {step.label}
                    </button>
                  ) : (
                    <span className="text-muted-foreground truncate min-w-0">{step.label}</span>
                  )}
                </div>
              ))}
            </div>
            {activeRegion && (
              <button
                onClick={() => {
                  setSelectedRegion(null);
                  setSelectedEntity(null);
                  setEntityNetwork(null);
                  setRelations(null);
                  setSelectedEdgeKey(null);
                  setPairSelection(null);
                  setPairContracts(null);
                }}
                className="text-xs flex items-center gap-1 text-muted-foreground hover:text-teal-300"
              >
                <X size={13} /> Limpar
              </button>
            )}
          </div>

          <div className="relative flex-1 min-h-0">
            {pairSelection && pairContracts ? (
              <div className="absolute inset-0 overflow-auto p-4">
                <PairContractsPanel
                  contracts={pairContracts}
                  nifA={pairSelection.nif}
                  nifB={pairSelection.counterpartyNif}
                  onContract={onContract}
                />
              </div>
            ) : (
              <NetworkCanvas
                graph={activeNetwork}
                view={graphView}
                onViewChange={setView}
                selectedNodeId={activeNodeId}
                selectedEdgeKey={selectedEdgeKey}
                onNodeClick={handleSelectGraphNode}
                onEdgeClick={handleSelectEdge}
                disabledViews={disabledGraphViews}
                regionHint={activeRegion}
              />
            )}

            {loading && (
              <div className="absolute inset-0 flex items-center justify-center bg-[#07151b]/60 z-30 pointer-events-none">
                <div className="flex flex-col items-center gap-2">
                  <Loader2 size={28} className="animate-spin text-teal-300" />
                  <span className="text-xs text-muted-foreground">A carregar...</span>
                </div>
              </div>
            )}
          </div>
        </Card>

        <div className="w-full xl:w-[340px] shrink-0 space-y-4 flex flex-col min-h-0">
          {!activeRegion ? (
            <Card className="flex-1 flex flex-col min-h-0">
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                <MapPin size={16} className="text-teal-300" /> Regiões
              </h3>
              <div className="overflow-auto pr-1 space-y-2 flex-1">
                {regions.map((r) => (
                  <button
                    key={r.key}
                    onClick={() => setSelectedRegion(r.key)}
                    title={`Explorar ${r.key}`}
                    className="w-full text-left rounded-xl border border-white/8 bg-white/[0.03] hover:bg-white/[0.06] px-3 py-2.5 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm truncate">{r.key}</span>
                      <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{compact(r.count ?? 0)} contratos</span>
                      <span>{money(r.total_value ?? 0)}</span>
                    </div>
                  </button>
                ))}
                {regions.length === 0 && !loading && (
                  <p className="text-sm text-muted-foreground text-center py-8">Sem regiões disponíveis.</p>
                )}
              </div>
            </Card>
          ) : (
            <>
              <Card>
                <h3 className="font-semibold mb-3">Legenda</h3>
                <div className="space-y-2 text-sm">
                  {legendEntries.map((entry) => (
                    <div key={entry.type} className="flex items-center gap-2">
                      <span
                        className="w-3 h-3 shrink-0 rounded-full"
                        style={{ background: NODE_COLORS[entry.type] || NODE_COLORS.outra }}
                      />
                      <span>{entry.label}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-4 text-muted-foreground">
                  O tamanho do nó reflete a centralidade; a espessura da linha, o número de contratos do par.
                </p>
              </Card>

              <Card className="flex-1 flex flex-col min-h-0">
                <h3 className="font-semibold mb-3 flex items-center gap-2">
                  <ArrowUpRight size={16} className="text-teal-300" />
                  Relações {selectedEntity ? "da entidade" : "da região"}
                </h3>
                <div className="overflow-auto pr-1 space-y-2 flex-1">
                  {topRelations.map((rel) => (
                    <button
                      key={`rel-${rel.source}-${rel.target}`}
                      onClick={() => handleSelectRelation(rel)}
                      className="w-full text-left rounded-xl border border-white/8 bg-white/[0.03] hover:bg-white/[0.06] px-3 py-2.5 transition"
                    >
                      <div className="flex items-center gap-1.5 text-xs">
                        <span className="truncate text-teal-300">{rel.source_name}</span>
                        <ArrowRight size={12} className="shrink-0 text-muted-foreground" />
                        <span className="truncate text-blue-300">{rel.target_name}</span>
                      </div>
                      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                        <span>{rel.count} contratos</span>
                        <span>{money(rel.total_value)}</span>
                      </div>
                    </button>
                  ))}
                  {topRelations.length === 0 && !loading && (
                    <p className="text-sm text-muted-foreground text-center py-8">Nenhuma relação disponível.</p>
                  )}
                </div>
              </Card>

              {selectedEntity && (
                <>
                  <Card>
                    <h3 className="font-semibold mb-2">Entidade selecionada</h3>
                    <p className="text-sm text-teal-300 truncate">{selectedEntity.label}</p>
                    <p className="text-xs text-muted-foreground mt-1">ID: {selectedEntity.id}</p>
                    <button
                      onClick={() => onEntity(selectedEntity.id)}
                      className="mt-3 w-full px-3 py-1.5 rounded-lg bg-teal-400/15 text-teal-300 text-sm hover:bg-teal-400/20"
                    >
                      Ver perfil
                    </button>
                  </Card>
                  <Card className="flex-1 min-h-0">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h3 className="font-semibold">Contratos da entidade</h3>
                      <span className="text-xs text-violet-300">{entityContracts.length}</span>
                    </div>
                    <div className="max-h-64 overflow-auto space-y-2 pr-1">
                      {entityContracts.slice(0, 12).map((contract, index) => (
                        <button
                          key={contract.idcontrato ?? `${contract.objectoContrato}-${index}`}
                          type="button"
                          onClick={() => contract.idcontrato && onContract(contract.idcontrato)}
                          disabled={!contract.idcontrato}
                          className="w-full rounded-lg border border-white/8 bg-white/[0.03] p-2 text-left transition hover:border-violet-300/40 hover:bg-white/[0.07] disabled:opacity-50"
                        >
                          <span className="block line-clamp-2 text-xs text-foreground">
                            {contract.objectoContrato ?? contract.descContrato ?? "Contrato sem objeto"}
                          </span>
                          <span className="mt-1 flex justify-between gap-2 text-[11px] text-muted-foreground">
                            <span>{contract.idcontrato ?? "Sem ID"}</span>
                            <span className="text-violet-300">{money(contract.precoContratual ?? contract.PrecoTotalEfetivo)}</span>
                          </span>
                        </button>
                      ))}
                      {entityContracts.length === 0 && !loading && (
                        <p className="py-4 text-center text-xs text-muted-foreground">Sem contratos carregados.</p>
                      )}
                    </div>
                  </Card>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function PairContractsPanel({
  contracts,
  nifA,
  nifB,
  onContract,
}: {
  contracts: ContractItem[];
  nifA: string;
  nifB: string;
  onContract: (id: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Contratos entre {nifA} e {nifB}</h3>
        <span className="text-xs text-muted-foreground">{contracts.length} contratos</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {contracts.map((c, idx) => (
          <div
            key={c.idcontrato ?? `${c.objectoContrato}-${idx}`}
            className="rounded-xl border border-white/10 bg-white/[0.03] p-3 flex flex-col gap-2"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-teal-300 line-clamp-2">{c.objectoContrato ?? c.descContrato ?? "Sem objecto"}</p>
              <span className="text-xs text-muted-foreground whitespace-nowrap">{money(c.precoContratual ?? c.precoBaseProcedimento)}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {c.dataPublicacao && <span>{new Date(c.dataPublicacao).toLocaleDateString("pt-PT")}</span>}
              {c.tipoContrato && <span className="ml-2">· {c.tipoContrato}</span>}
            </div>
            <div className="flex gap-2 mt-auto">
              <button
                onClick={() => onContract(c.idcontrato ?? "")}
                className="flex-1 px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-xs"
              >
                Ver contrato
              </button>
            </div>
          </div>
        ))}
      </div>
      {contracts.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">Nenhum contrato encontrado para este par.</p>
      )}
    </div>
  );
}

function ContractParticipantNode({
  label,
  role,
  nif,
  color,
  onOpen,
}: {
  label: string;
  role: string;
  nif?: string;
  color: string;
  onOpen?: () => void;
}) {
  const content = (
    <>
      <span className="block text-xs uppercase tracking-wide" style={{ color }}>
        {role}
      </span>
      <span className="mt-1 block text-sm font-medium text-foreground line-clamp-2">{label}</span>
      {nif && <span className="mt-1 block text-[11px] text-muted-foreground">NIF {nif}</span>}
    </>
  );

  if (!onOpen) return <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">{content}</div>;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-xl border border-white/10 bg-white/[0.04] p-3 text-left transition hover:border-teal-300/50 hover:bg-white/[0.08]"
      title="Abrir ficha da entidade"
    >
      {content}
    </button>
  );
}

function ContractParticipantsGraph({
  contract,
  onEntity,
}: {
  contract: ContractItem;
  onEntity: (nif: string) => void;
}) {
  const competitors = useMemo(() => parseCompetitors(contract.concorrentes), [contract.concorrentes]);
  const [searching, setSearching] = useState<string | null>(null);

  const openCompetitor = async (competitor: ContractCompetitor) => {
    if (competitor.nif) {
      onEntity(competitor.nif);
      return;
    }
    setSearching(competitor.name);
    try {
      const result = await searchCompanies({ q: competitor.name, size: 1 });
      const nif = result.items[0]?.nif;
      if (nif) onEntity(nif);
    } finally {
      setSearching(null);
    }
  };

  const adjudicantes = (Array.isArray(contract.adjudicantes) ? contract.adjudicantes : contract.adjudicantes ? [contract.adjudicantes] : [])
    .flatMap((party) => party.parsed ?? [])
    .filter((party) => party.nome || party.nif);
  const adjudicatarios = (Array.isArray(contract.adjudicatarios) ? contract.adjudicatarios : contract.adjudicatarios ? [contract.adjudicatarios] : [])
    .flatMap((party) => party.parsed ?? [])
    .filter((party) => party.nome || party.nif);

  return (
    <div className="mt-6 rounded-2xl border border-white/10 bg-[#07151b]/70 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-teal-300">Rede do contrato</p>
          <p className="mt-1 text-sm text-muted-foreground">Participantes e concorrentes navegáveis</p>
        </div>
        <Network size={18} className="text-teal-300" />
      </div>

      <div className="mt-4 flex justify-center">
        <div className="rounded-xl border border-amber-300/50 bg-amber-300/10 px-4 py-3 text-center shadow-[0_0_20px_rgba(251,191,36,0.18)]">
          <FileText size={18} className="mx-auto text-amber-300" />
          <p className="mt-1 text-xs font-semibold text-amber-100">Contrato</p>
          <p className="mt-1 max-w-[220px] truncate text-[11px] text-muted-foreground">{contract.idcontrato || "sem ID"}</p>
        </div>
      </div>

      <div className="my-2 flex justify-center text-muted-foreground"><ChevronDown size={18} /></div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {adjudicantes.map((party, index) => (
          <ContractParticipantNode
            key={`buyer-${party.nif ?? party.nome}-${index}`}
            label={party.nome ?? party.nif ?? "Adjudicante"}
            role="Adjudicante"
            nif={party.nif}
            color="#2dd4bf"
            onOpen={party.nif ? () => onEntity(party.nif!) : undefined}
          />
        ))}
        {adjudicatarios.map((party, index) => (
          <ContractParticipantNode
            key={`supplier-${party.nif ?? party.nome}-${index}`}
            label={party.nome ?? party.nif ?? "Adjudicatário"}
            role="Adjudicatário"
            nif={party.nif}
            color="#60a5fa"
            onOpen={party.nif ? () => onEntity(party.nif!) : undefined}
          />
        ))}
      </div>

      <div className="my-4 flex items-center gap-3 text-xs text-muted-foreground">
        <span className="h-px flex-1 bg-white/10" />
        <span>Concorrentes ({competitors.length})</span>
        <span className="h-px flex-1 bg-white/10" />
      </div>
      {competitors.length > 0 ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {competitors.map((competitor, index) => (
            <ContractParticipantNode
              key={`competitor-${competitor.nif ?? competitor.name}-${index}`}
              label={competitor.name}
              role="Concorrente"
              nif={competitor.nif}
              color="#fb7185"
              onOpen={() => void openCompetitor(competitor)}
            />
          ))}
        </div>
      ) : (
        <p className="text-center text-xs text-muted-foreground">Sem concorrentes publicados para este contrato.</p>
      )}
      {searching && <p className="mt-3 text-center text-xs text-teal-300">A procurar ficha de {searching}...</p>}
    </div>
  );
}

function ContractAIAnalysis({
  idcontrato,
}: {
  idcontrato: string;
}) {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("");
  const [maxTokens, setMaxTokens] = useState(2048);
  const [temperature, setTemperature] = useState(0.3);
  const [useWeb, setUseWeb] = useState(true);
  const [useRelated, setUseRelated] = useState(true);
  const [result, setResult] = useState<ContractAnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    try {
      const body: ContractAnalyzeRequest = {
        question: question.trim() || undefined,
        model: model.trim() || undefined,
        max_tokens: maxTokens,
        temperature,
        use_web_search: useWeb,
        use_related_contracts: useRelated,
      };
      const res = await analyzeContract(idcontrato, body);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao analisar contrato");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="mt-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-teal-300">Análise IA</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Analisa este contrato com Ollama/cloud + web search e contratos relacionados
          </p>
        </div>
        <Sparkles size={18} className="text-teal-300" />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="sm:col-span-2 lg:col-span-2">
          <label className="block text-xs text-muted-foreground mb-1">Modelo (vazio = auto)</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="ex: llama3.2, mistral, gpt-4o-mini"
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm outline-none focus:border-teal-400/50"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Max tokens</label>
          <input
            type="number"
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm outline-none focus:border-teal-400/50"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Temperatura</label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm outline-none focus:border-teal-400/50"
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useWeb}
            onChange={(e) => setUseWeb(e.target.checked)}
            className="accent-teal-400"
          />
          Web search
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useRelated}
            onChange={(e) => setUseRelated(e.target.checked)}
            className="accent-teal-400"
          />
          Contratos relacionados
        </label>
      </div>

      <div className="mt-4">
        <label className="block text-xs text-muted-foreground mb-1">Pergunta / instrução</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ex: Identifica riscos de corrupção, compara preço com o mercado, resume as partes..."
          rows={3}
          className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm outline-none focus:border-teal-400/50 resize-none"
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleAnalyze}
          disabled={loading}
          className="px-4 py-2 rounded-xl bg-teal-500/20 border border-teal-400/40 text-teal-100 text-sm font-medium hover:bg-teal-500/30 transition disabled:opacity-60 flex items-center gap-2"
        >
          {loading && <Loader2 size={16} className="animate-spin" />}
          <Sparkles size={16} /> Analisar contrato
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-xl border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {result && !error && (
        <div className="mt-5 space-y-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <p className="text-xs text-muted-foreground mb-2">Análise</p>
            <div className="text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
              {result.analysis}
            </div>
          </div>

          {result.sources && result.sources.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-2">Fontes web</p>
              <div className="space-y-2">
                {result.sources.map((s, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm"
                  >
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-teal-300 hover:underline"
                    >
                      {s.title || s.url}
                    </a>
                    {s.snippet && (
                      <p className="mt-1 text-xs text-muted-foreground">{s.snippet}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.model_used && (
            <p className="text-xs text-muted-foreground">Modelo: {result.model_used}</p>
          )}
        </div>
      )}
    </Card>
  );
}

// --- ANALYSIS ---

function AnalysisSection({
  analytics,
  regional,
  onEntity,
}: {
  analytics: ContractAnalyticsResponse | null;
  regional: ContractRegionalResponse | null;
  onEntity: (_nif: string) => void;
}) {
  const byYear = useMemo(
    () => [...(analytics?.by_year ?? [])].sort((a, b) => (a.key < b.key ? -1 : 1)),
    [analytics],
  );
  const topEntities = analytics?.top_entities ?? [];
  const topCpv = analytics?.top_cpv ?? [];
  const contractTypes = analytics?.contract_types ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold">Análise de Contratos</h2>
        <p className="text-sm text-muted-foreground">
          Métricas agregadas e distribuições do universo indexado
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card glow="teal">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor Total Adjudicado</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-teal">{money(analytics?.total_value)}</p>
        </Card>
        <Card glow="blue">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Nº de Contratos</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-blue">{full(analytics?.total_contracts)}</p>
        </Card>
        <Card glow="amber">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Entidades no Grafo</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-amber">{full(topEntities.length)}</p>
        </Card>
        <Card glow="violet">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Top Entidades Distintas</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-violet">{full(topEntities.length)}</p>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <h3 className="font-semibold mb-4">Evolução do Valor Adjudicado</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={byYear}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="key" stroke="rgba(255,255,255,0.3)" fontSize={12} />
                <YAxis
                  yAxisId="left"
                  orientation="left"
                  stroke="rgba(255,255,255,0.3)"
                  fontSize={12}
                  tickFormatter={(v) => compact(v)}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="rgba(255,255,255,0.3)"
                  fontSize={12}
                  tickFormatter={(v) => full(v)}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(7,21,27,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                  }}
                  formatter={(value, name) => {
                    const val = typeof value === "number" ? value : Number(value);
                    return [name === "Nº contratos" ? full(val) : money(val), name];
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="total_value"
                  yAxisId="left"
                  stroke="#10a37f"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#10a37f" }}
                  name="Valor adjudicado"
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  yAxisId="right"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#3b82f6" }}
                  name="Nº contratos"
                />
                <Legend />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">Por Tipo de Contrato</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <RePieChart>
                <Pie
                  data={contractTypes.slice(0, 6)}
                  dataKey="count"
                  nameKey="key"
                  innerRadius={50}
                  outerRadius={85}
                  paddingAngle={3}
                  label={percentPieLabel}
                >
                  {contractTypes.slice(0, 6).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "rgba(7,21,27,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                  }}
                  formatter={countFormatter}
                />
              </RePieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr_0.6fr]">
        <Card>
          <h3 className="font-semibold mb-4">Top 5 Entidades por Valor</h3>
          <div className="space-y-4">
            {topEntities.slice(0, 5).map((row) => (
              <button
                key={row.key}
                onClick={() => onEntity(row.key)}
                className="w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 rounded-lg"
              >
                <div className="flex items-center justify-between gap-3 mb-1 text-sm">
                  <span className="truncate hover:text-teal-300 transition">{row.description || row.key}</span>
                  <span className="text-muted-foreground shrink-0">{money(row.total_value)}</span>
                </div>
                <MiniBar
                  value={row.total_value || 0}
                  max={Math.max(...topEntities.map((r) => r.total_value || 0), 1)}
                />
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">CPV Mais Frequentes</h3>
          <div className="space-y-4">
            {topCpv.slice(0, 5).map((row) => (
              <div key={row.key}>
                <div className="flex items-center justify-between gap-3 mb-1 text-sm">
                  <span className="truncate">{row.description || row.key}</span>
                  <span className="text-muted-foreground shrink-0">{full(row.count)}</span>
                </div>
                <MiniBar
                  value={row.count || 0}
                  max={Math.max(...topCpv.map((r) => r.count || 0), 1)}
                  color="bg-amber-400"
                />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">Regiões ativas</h3>
          <div className="space-y-3 max-h-[320px] overflow-auto pr-1">
            {(regional?.regions ?? [])
              .sort((a, b) => (b.total_value || 0) - (a.total_value || 0))
              .slice(0, 8)
              .map((region) => (
                <div
                  key={region.key}
                  className="flex items-center justify-between rounded-xl bg-white/[0.03] px-3 py-2.5 border border-white/5"
                >
                  <span className="text-sm">{region.key}</span>
                  <span className="text-xs text-muted-foreground">{region.count} contratos</span>
                </div>
              ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// --- ENTITY DETAIL ---

function EntityDetailPanel({
  nif,
  onBack,
  onContract,
}: {
  nif: string;
  onBack: () => void;
  onContract: (id: string) => void;
}) {
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [contracts, setContracts] = useState<CompanyContractsResponse | null>(null);
  const [analytics, setAnalytics] = useState<CompanyAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { recordVisit } = useWorkspace();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getCompanyDetail(nif),
      getCompanyContracts(nif, "all", 0, 10),
      getCompanyAnalytics(nif),
    ])
      .then(([d, c, a]) => {
        if (cancelled) return;
        setCompany(d);
        setContracts(c);
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

  // Histórico do dossier: registar a consulta assim que a ficha carrega.
  useEffect(() => {
    if (!company) return;
    recordVisit({
      kind: "entity",
      id: nif,
      label: company.name,
      sublabel: `NIF ${nif}`,
      value: company.total_value ?? null,
    });
  }, [company, nif, recordVisit]);

  if (loading) return <Loading />;
  if (error || !company) {
    return (
      <Card className="p-8 text-center">
        <p className="text-rose-300">{error || "Entidade não encontrada"}</p>
        <button onClick={onBack} className="mt-4 px-4 py-2 rounded-xl glass-card hover:bg-white/5 text-sm">
          Voltar
        </button>
      </Card>
    );
  }

  const allContracts = contracts?.items ?? [];
  const yearly = analytics?.by_year ?? [];
  const yearlyMax = Math.max(...yearly.map((r) => r.total_value || 0), 1);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <button
          onClick={onBack}
          className="px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition flex items-center gap-2"
        >
          <ArrowUpRight size={16} className="rotate-[-135deg]" /> Voltar
        </button>
        <FavoriteButton
          kind="entity"
          id={nif}
          label={company.name}
          sublabel={`NIF ${nif}`}
          variant="solid"
        />
        <SaveToFolderButton
          kind="entity"
          id={nif}
          label={company.name}
          sublabel={`NIF ${nif}`}
          variant="solid"
        />
      </div>

      <Card>
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-2xl bg-gradient-to-br from-teal-500/20 via-blue-500/15 to-rose-500/10 border border-white/10">
            <Building2 size={36} className="text-teal-300" />
          </div>
          <div>
            <h2 className="text-2xl font-bold">{company.name}</h2>
            <div className="flex flex-wrap items-center gap-2 mt-2 text-sm text-muted-foreground">
              {company.nif && <Badge>NIF {company.nif}</Badge>}
              {company.normalized_name && company.normalized_name !== company.name && (
                <span>{company.normalized_name}</span>
              )}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card glow="blue">
          <p className="text-xs text-muted-foreground">Total de contratos</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-blue">{full(company.contracts_total)}</p>
        </Card>
        <Card glow="amber">
          <p className="text-xs text-muted-foreground">Valor total</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-amber">{money(company.total_value)}</p>
        </Card>
        <Card glow="teal">
          <p className="text-xs text-muted-foreground">Valor médio / contrato</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-teal">{money(analytics?.avg_value)}</p>
        </Card>
        <Card glow="rose">
          <p className="text-xs text-muted-foreground">Maior contrato</p>
          <p className="mt-2 text-2xl font-bold stat-value text-glow-rose">{money(analytics?.max_value)}</p>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <h3 className="font-semibold mb-4">Contratos Recentes</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground text-xs uppercase tracking-wider">
                  <th className="py-2 pr-3">Nº</th>
                  <th className="py-2 pr-3">Objeto</th>
                  <th className="py-2 pr-3 text-right">Valor</th>
                </tr>
              </thead>
              <tbody>
                {allContracts.slice(0, 6).map((c, idx) => (
                  <tr key={c.idcontrato || idx} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-teal-300">
                      <button onClick={() => c.idcontrato && onContract(c.idcontrato)} className="hover:underline">
                        {c.idcontrato || "—"}
                      </button>
                    </td>
                    <td className="py-2 pr-3 max-w-xs truncate">{c.objectoContrato || "—"}</td>
                    <td className="py-2 pr-3 text-right">{money(c.precoContratual ?? c.PrecoTotalEfetivo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <h3 className="font-semibold mb-4">Por ano</h3>
          <div className="space-y-3">
            {yearly.slice(0, 7).map((row) => (
              <div key={row.key}>
                <div className="flex justify-between text-sm mb-1">
                  <span>{row.key}</span>
                  <span className="text-muted-foreground">{money(row.total_value)}</span>
                </div>
                <MiniBar value={row.total_value || 0} max={yearlyMax} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// --- CONTRACT DETAIL ---

function ContractDetailPanel({
  id,
  onBack,
  onEntity,
}: {
  id: string;
  onBack: () => void;
  onEntity: (nif: string) => void;
}) {
  const [contract, setContract] = useState<ContractItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { recordVisit } = useWorkspace();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getContract(id)
      .then((c) => {
        if (!cancelled) setContract(c);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro ao carregar contrato");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Histórico do dossier: registar a consulta assim que a ficha carrega.
  useEffect(() => {
    if (!contract) return;
    recordVisit({
      kind: "contract",
      id,
      label: contract.objectoContrato || `Contrato ${id}`,
      sublabel: contract.idcontrato || id,
      value: contract.precoContratual ?? contract.PrecoTotalEfetivo ?? null,
      parties: contractPartiesOf(contract),
    });
  }, [contract, id, recordVisit]);

  if (loading) return <Loading />;
  if (error || !contract) {
    return (
      <Card className="p-8 text-center">
        <p className="text-rose-300">{error || "Contrato não encontrado"}</p>
        <button onClick={onBack} className="mt-4 px-4 py-2 rounded-xl glass-card hover:bg-white/5 text-sm">
          Voltar
        </button>
      </Card>
    );
  }

  const sourceNif = nifFromParty(contract.adjudicantes);
  const targetNif = nifFromParty(contract.adjudicatarios);

  return (
    <div className="space-y-5">
      <button
        onClick={onBack}
        className="px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition flex items-center gap-2"
      >
        <ArrowUpRight size={16} className="rotate-[-135deg]" /> Voltar
      </button>

      <Card>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs text-teal-400 uppercase tracking-wider">Detalhe do Contrato</p>
            <h2 className="text-2xl font-bold mt-2">{contract.objectoContrato || "Contrato sem descrição"}</h2>
            <p className="text-sm text-muted-foreground mt-1">{contract.idcontrato || "—"}</p>
          </div>
          <FavoriteButton
            kind="contract"
            id={id}
            label={contract.objectoContrato || `Contrato ${id}`}
            sublabel={contract.idcontrato || id}
            value={contract.precoContratual ?? contract.PrecoTotalEfetivo ?? null}
          />
          <SaveToFolderButton
            kind="contract"
            id={id}
            label={contract.objectoContrato || `Contrato ${id}`}
            sublabel={contract.idcontrato || id}
            value={contract.precoContratual ?? contract.PrecoTotalEfetivo ?? null}
            parties={contractPartiesOf(contract)}
          />
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">Valor contratual</p>
            <p className="text-xl font-semibold text-amber-400 mt-1">
              {money(contract.precoContratual ?? contract.PrecoTotalEfetivo)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Tipo de contrato</p>
            <p className="text-xl font-semibold mt-1">{contract.tipoContrato || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Procedimento</p>
            <p className="text-xl font-semibold mt-1">{contract.tipoprocedimento || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Data de publicação</p>
            <p className="text-xl font-semibold mt-1">{fmtDate(contract.dataPublicacao)}</p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted-foreground mb-2">Entidade Adjudicante</p>
            <button
              onClick={() => sourceNif && onEntity(sourceNif)}
              disabled={!sourceNif}
              className="text-left w-full p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:border-teal-400/30 transition disabled:opacity-60"
            >
              <p className="font-medium">{partyNames(contract.adjudicantes)}</p>
              {sourceNif && <p className="text-xs text-muted-foreground mt-1">NIF {sourceNif}</p>}
            </button>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-2">Entidade Adjudicatária</p>
            <button
              onClick={() => targetNif && onEntity(targetNif)}
              disabled={!targetNif}
              className="text-left w-full p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:border-teal-400/30 transition disabled:opacity-60"
            >
              <p className="font-medium">{partyNames(contract.adjudicatarios)}</p>
              {targetNif && <p className="text-xs text-muted-foreground mt-1">NIF {targetNif}</p>}
            </button>
          </div>
        </div>

        <ContractParticipantsGraph contract={contract} onEntity={onEntity} />

        <ContractAIAnalysis idcontrato={id} />

        <div className="mt-6">
          <p className="text-xs text-muted-foreground mb-2">Descrição</p>
          <p className="text-sm leading-relaxed text-foreground/80">
            {contract.descContrato || "Sem descrição adicional publicada."}
          </p>
        </div>

        {contract.cpv && contract.cpv.length > 0 && (
          <div className="mt-6">
            <p className="text-xs text-muted-foreground mb-2">CPV</p>
            <div className="flex flex-wrap gap-2">
              {contract.cpv.map((c, i) => (
                <Badge key={i} color="amber">
                  {c.code} {c.description}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

// --- Favoritos ---

function FavoritesSection({
  onEntity,
  onContract,
}: {
  onEntity: (nif: string) => void;
  onContract: (id: string) => void;
}) {
  const { entities, contracts, remove, clear } = useFavorites();
  const total = entities.length + contracts.length;

  if (total === 0) {
    return (
      <Card className="p-12 text-center">
        <Heart size={40} className="mx-auto text-rose-400/70 mb-4" />
        <h2 className="text-xl font-semibold">Favoritos</h2>
        <p className="text-sm text-muted-foreground mt-2">
          As entidades e contratos marcados aparecem aqui.
        </p>
        <p className="text-xs text-muted-foreground/80 mt-1">
          Abra uma ficha e use o botão «Favorito» para a marcar.
        </p>
      </Card>
    );
  }

  const groups = [
    {
      key: "entity" as const,
      title: "Entidades",
      icon: Building2,
      items: entities,
      open: onEntity,
      openLabel: "Abrir ficha da entidade",
    },
    {
      key: "contract" as const,
      title: "Contratos",
      icon: FileText,
      items: contracts,
      open: onContract,
      openLabel: "Abrir ficha do contrato",
    },
  ].filter((group) => group.items.length > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Favoritos</h2>
          <p className="text-sm text-muted-foreground">
            {total} {total === 1 ? "marcado" : "marcados"} · {entities.length} entidades · {contracts.length} contratos
          </p>
        </div>
        <button
          type="button"
          onClick={clear}
          className="rounded-xl glass-card px-3 py-1.5 text-sm text-muted-foreground transition hover:text-rose-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
        >
          Limpar favoritos
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map((group) => {
          const Icon = group.icon;
          return (
            <Card key={group.key}>
              <div className="flex items-center gap-2">
                <Icon size={18} className="text-teal-300" />
                <h3 className="font-semibold">
                  {group.title} <span className="text-muted-foreground">({group.items.length})</span>
                </h3>
              </div>
              <ul className="mt-3 space-y-2">
                {group.items.map((item) => (
                  <li
                    key={`${item.kind}-${item.id}`}
                    className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3"
                  >
                    <button
                      type="button"
                      onClick={() => group.open(item.id)}
                      title={group.openLabel}
                      className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                    >
                      <span className="block truncate text-sm text-foreground">{item.label}</span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {item.sublabel ?? item.id}
                        {typeof item.value === "number" && item.value > 0 ? ` · ${money(item.value)}` : ""}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(item.kind, item.id)}
                      aria-label={`Remover ${item.label} dos favoritos`}
                      title="Remover dos favoritos"
                      className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:border-rose-400/30 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// --- Configurações & Dossier ---

type WorkspaceTab = "companies" | "folders" | "history" | "graph";

const WORKSPACE_TABS: { id: WorkspaceTab; label: string; icon: React.ElementType; hint: string }[] = [
  { id: "companies", label: "Empresas & contratos", icon: Building2, hint: "Empresas do dossier e os seus contratos" },
  { id: "folders", label: "Pastas & dossier", icon: FolderHeart, hint: "Organize fichas em pastas" },
  { id: "history", label: "Histórico", icon: History, hint: "Fichas consultadas recentemente" },
  { id: "graph", label: "Grafo do dossier", icon: GitBranch, hint: "Grafos de visualização do dossier" },
];

const contractValue = (contract: ContractItem) => contract.precoContratual ?? contract.PrecoTotalEfetivo ?? 0;

const contractLabel = (contract: ContractItem, fallbackId: string) =>
  contract.objectoContrato || `Contrato ${contract.idcontrato || fallbackId}`;

/**
 * Constrói um grafo (empresas → contratos) a partir do dossier, no mesmo formato dos grafos
 * por dimensões, para reutilizar o canvas (rede, hierárquico e circular).
 */
function buildDossierGraph(
  companies: { nif: string; label: string; value: number }[],
  previews: Record<string, ContractItem[]>,
  entries: WorkspaceEntry[]
): ContractGraphBuildResponse {
  const nodes: ContractGraphBuildNode[] = [];
  const edges: { source: string; target: string; count: number; value: number }[] = [];
  const seenContracts = new Set<string>();

  companies.forEach((company) => {
    const contracts = (previews[company.nif] ?? []).slice(0, 8);
    const total = contracts.reduce((acc, contract) => acc + contractValue(contract), 0) || company.value || 0;
    nodes.push({
      id: `ent:${company.nif}`,
      key: company.nif,
      label: company.label,
      dimension: "entidade",
      type: "entidade",
      role: "Entidade",
      count: contracts.length || 1,
      total_value: total,
    });
    contracts.forEach((contract) => {
      const contractId = contract.idcontrato;
      if (!contractId || seenContracts.has(contractId)) return;
      seenContracts.add(contractId);
      nodes.push({
        id: `ctr:${contractId}`,
        key: contractId,
        label: contractLabel(contract, contractId),
        dimension: "contrato",
        type: "outra",
        role: "Contrato",
        count: 1,
        total_value: contractValue(contract),
      });
      edges.push({ source: `ent:${company.nif}`, target: `ctr:${contractId}`, count: 1, value: contractValue(contract) });
    });
  });

  // Contratos guardados no dossier mas sem pré-visualização carregada entram como nó isolado.
  entries
    .filter((entry) => entry.kind === "contract")
    .forEach((entry) => {
      if (seenContracts.has(entry.id)) return;
      seenContracts.add(entry.id);
      nodes.push({
        id: `ctr:${entry.id}`,
        key: entry.id,
        label: entry.label,
        dimension: "contrato",
        type: "outra",
        role: "Contrato",
        count: 1,
        total_value: entry.value ?? 0,
      });
    });

  const keptNodes = nodes.length;
  return {
    nodes,
    edges,
    meta: {
      dimension_a: "entidade",
      dimension_b: "contrato",
      metric: "valor",
      mode: "dossier",
      complete: true,
      scan_capped: false,
      sample_order: "dossier",
      sample_limit: null,
      documents_scanned: edges.length,
      documents_matching: edges.length,
      scanned_value: edges.reduce((acc, edge) => acc + edge.value, 0),
      nodes_total: keptNodes,
      edges_total: edges.length,
      kept_nodes: keptNodes,
      kept_edges: edges.length,
      omitted_edges: 0,
      directed: true,
      notes: ["Grafo construído a partir das fichas guardadas no dossier."],
      filters: {},
    },
  };
}

/** Pré-visualização dos contratos das empresas do dossier (limitada para não pesar). */
function useDossierContracts(companies: { nif: string }[], perCompany = 6) {
  const [previews, setPreviews] = useState<Record<string, ContractItem[]>>({});
  const [loading, setLoading] = useState(false);
  const companiesRef = useRef(companies);
  companiesRef.current = companies;
  const key = companies.map((company) => company.nif).join(",");

  useEffect(() => {
    const list = companiesRef.current.slice(0, 8);
    if (list.length === 0) {
      setPreviews({});
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(
      list.map(async (company) => {
        try {
          const response = await getCompanyContracts(company.nif, "all", 0, perCompany);
          return [company.nif, response.items ?? []] as const;
        } catch {
          return [company.nif, [] as ContractItem[]] as const;
        }
      })
    )
      .then((pairs) => {
        if (!cancelled) setPreviews(Object.fromEntries(pairs));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [key, perCompany]);

  return { previews, loading };
}

function DossierEntryRow({
  entry,
  onOpen,
  onRemove,
}: {
  entry: WorkspaceEntry;
  onOpen: () => void;
  onRemove?: () => void;
}) {
  const Icon = entry.kind === "entity" ? Building2 : FileText;
  return (
    <li className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-2.5">
      <span className="mt-0.5 text-muted-foreground/80">
        <Icon size={15} />
      </span>
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
      >
        <span className="block truncate text-sm text-foreground">{entry.label}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
          {entry.kind === "entity" ? "Entidade" : "Contrato"}
          {entry.sublabel ? ` · ${entry.sublabel}` : ""}
          {entry.value ? ` · ${money(entry.value)}` : ""}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remover ${entry.label}`}
          title="Remover"
          className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:border-rose-400/30 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
        >
          <X size={13} />
        </button>
      )}
    </li>
  );
}

function SettingsSection({
  onEntity,
  onContract,
}: {
  onEntity: (nif: string) => void;
  onContract: (id: string) => void;
}) {
  const { history, folders, createFolder, renameFolder, deleteFolder, addToFolder, removeFromFolder, clearHistory } =
    useWorkspace();
  const { favorites } = useFavorites();
  const [tab, setTab] = useState<WorkspaceTab>("companies");
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState("");

  const activeFolder = useMemo(
    () => folders.find((folder) => folder.id === activeFolderId) ?? folders[0] ?? null,
    [activeFolderId, folders]
  );

  const favouriteEntries: WorkspaceEntry[] = useMemo(
    () =>
      favorites.map((favorite) => ({
        kind: favorite.kind,
        id: favorite.id,
        label: favorite.label,
        sublabel: favorite.sublabel,
        value: favorite.value ?? null,
        seenAt: favorite.addedAt,
      })),
    [favorites]
  );

  // Sem pasta escolhida, o dossier é o conjunto de favoritos + histórico recente.
  // As identidades são estáveis (só mudam quando o armazém muda) para não reiniciar
  // o layout do grafo nem refazer pedidos em cada render.
  const dossierEntries: WorkspaceEntry[] = useMemo(
    () =>
      activeFolder
        ? activeFolder.items
        : [
            ...favouriteEntries,
            ...history.filter(
              (item) => !favouriteEntries.some((favorite) => favorite.kind === item.kind && favorite.id === item.id)
            ),
          ].slice(0, 24),
    [activeFolder, favouriteEntries, history]
  );

  const companies = useMemo(() => companiesIn(dossierEntries), [dossierEntries]);
  const { previews, loading: loadingContracts } = useDossierContracts(companies);

  const openEntry = (entry: WorkspaceEntry) => {
    if (entry.kind === "entity") onEntity(entry.id);
    else onContract(entry.id);
  };

  const addFavouritesToActiveFolder = () => {
    if (!activeFolder) return;
    favouriteEntries.forEach((entry) => addToFolder(activeFolder.id, entry));
  };

  const handleCreateFolder = () => {
    const id = createFolder(newFolderName);
    if (id) {
      setNewFolderName("");
      setActiveFolderId(id);
      setTab("folders");
    }
  };

  const handleGraphNode = (node: StudioNode) => {
    if (node.dimension === "entidade") onEntity(node.key);
    else onContract(node.key);
  };

  const [metric, setMetric] = useState<GraphMetric>("valor");
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [layoutVersion, setLayoutVersion] = useState(0);

  const dossierGraphResponse = useMemo(
    () => buildDossierGraph(companies, previews, dossierEntries),
    // `previews`/`companies` derivam do dossier; recalcular quando muda o conjunto.
    [companies, dossierEntries, previews]
  );
  const dossierGraph = useMemo(() => toStudioGraph(dossierGraphResponse, metric), [dossierGraphResponse, metric]);
  const dossierValue = dossierEntries.reduce((acc, entry) => acc + (entry.value ?? 0), 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Settings size={20} className="text-teal-300" /> Configurações & dossier
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Área de trabalho: empresas e os seus contratos, pastas de fichas guardadas, histórico de consultas e
            grafos de visualização do dossier.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-muted-foreground">
            {folders.length} pastas
          </span>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-muted-foreground">
            {favouriteEntries.length} favoritos
          </span>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-muted-foreground">
            {history.length} no histórico
          </span>
          <span className="rounded-full border border-teal-400/20 bg-teal-400/10 px-3 py-1.5 text-teal-200">
            {money(dossierValue)} no dossier
          </span>
        </div>
      </div>

      <div role="tablist" aria-label="Secções das configurações" className="flex flex-wrap gap-2">
        {WORKSPACE_TABS.map((item) => {
          const Icon = item.icon;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={active}
              title={item.hint}
              onClick={() => setTab(item.id)}
              className={[
                "flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
                active
                  ? "glass-card text-teal-200 ring-1 ring-teal-400/30"
                  : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
              ].join(" ")}
            >
              <Icon size={16} />
              {item.label}
            </button>
          );
        })}
      </div>

      {tab === "companies" && (
        <div className="space-y-4">
          {dossierEntries.length === 0 ? (
            <Card className="p-10 text-center">
              <Building2 size={36} className="mx-auto mb-3 text-muted-foreground/70" />
              <h2 className="text-lg font-semibold">Sem empresas no dossier</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Marque fichas como favoritas ou guarde-as numa pasta para as ver aqui com os respetivos contratos.
              </p>
            </Card>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {activeFolder ? `Pasta «${activeFolder.name}»` : "Favoritos + histórico recente"} · {companies.length}{" "}
                empresas · contratos dos últimos {Object.values(previews).reduce((acc, list) => acc + list.length, 0)} carregados
                {loadingContracts ? " (a carregar…)" : ""}
              </p>
              <div className="grid gap-4 xl:grid-cols-2">
                {companies.map((company) => {
                  const contracts = previews[company.nif] ?? [];
                  const total = contracts.reduce((acc, contract) => acc + contractValue(contract), 0) || company.value;
                  return (
                    <Card key={company.nif}>
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => onEntity(company.nif)}
                          className="min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                        >
                          <span className="flex items-center gap-2">
                            <Building2 size={16} className="shrink-0 text-teal-300" />
                            <span className="truncate font-semibold">{company.label}</span>
                          </span>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            NIF {company.nif}
                            {company.role ? ` · ${company.role}` : ""}
                          </span>
                        </button>
                        <div className="shrink-0 text-right">
                          <p className="text-sm font-semibold text-amber-300">{money(total)}</p>
                          <p className="text-[11px] text-muted-foreground">{contracts.length} contratos recentes</p>
                        </div>
                      </div>
                      {contracts.length > 0 ? (
                        <ul className="mt-3 space-y-1.5">
                          {contracts.slice(0, 5).map((contract) => (
                            <li key={contract.idcontrato ?? contract.doc_id}>
                              <button
                                type="button"
                                onClick={() => contract.idcontrato && onContract(contract.idcontrato)}
                                className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-left transition hover:border-teal-400/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                              >
                                <span className="block truncate text-xs text-foreground">
                                  {contractLabel(contract, company.nif)}
                                </span>
                                <span className="mt-0.5 block text-[11px] text-muted-foreground">
                                  {contract.idcontrato} · {fmtDate(contract.dataCelebracaoContrato ?? contract.dataPublicacao)} ·{" "}
                                  {money(contractValue(contract))}
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-3 text-xs text-muted-foreground">
                          {loadingContracts ? "A carregar contratos…" : "Sem contratos recentes indexados."}
                        </p>
                      )}
                      {activeFolder && (
                        <button
                          type="button"
                          onClick={() =>
                            addToFolder(activeFolder.id, {
                              kind: "entity",
                              id: company.nif,
                              label: company.label,
                              sublabel: `NIF ${company.nif}`,
                              value: company.value,
                            })
                          }
                          className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-teal-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                        >
                          Guardar empresa na pasta
                        </button>
                      )}
                    </Card>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}

      {tab === "folders" && (
        <div className="space-y-4">
          <Card>
            <div className="flex flex-wrap items-center gap-2">
              <FolderPlus size={18} className="text-teal-300" />
              <h2 className="text-sm font-semibold">Nova pasta</h2>
              <input
                value={newFolderName}
                onChange={(event) => setNewFolderName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") handleCreateFolder();
                }}
                placeholder="Ex.: Concorrência 2026, Auditoria Coimbra…"
                aria-label="Nome da nova pasta"
                className="min-w-[220px] flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
              />
              <button
                type="button"
                onClick={handleCreateFolder}
                disabled={!newFolderName.trim()}
                className="rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-sm text-teal-200 transition hover:bg-teal-400/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Criar pasta
              </button>
            </div>
          </Card>

          {folders.length === 0 ? (
            <Card className="p-10 text-center">
              <FolderHeart size={36} className="mx-auto mb-3 text-muted-foreground/70" />
              <h2 className="text-lg font-semibold">Ainda não há pastas</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Crie uma pasta e guarde fichas de entidades e contratos — ou use «Guardar em pasta» dentro de cada ficha.
              </p>
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,300px)_1fr]">
              <div className="space-y-2">
                {folders.map((folder) => {
                  const isActive = activeFolder?.id === folder.id;
                  return (
                    <div
                      key={folder.id}
                      className={[
                        "rounded-2xl border border-white/10 bg-white/[0.03] p-3 transition",
                        isActive ? "ring-1 ring-teal-400/40" : "",
                      ].join(" ")}
                    >
                      <button
                        type="button"
                        onClick={() => setActiveFolderId(folder.id)}
                        className="flex w-full items-center gap-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        <FolderHeart size={16} className={isActive ? "text-teal-300" : "text-muted-foreground"} />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{folder.name}</span>
                        <span className="text-[11px] text-muted-foreground">{folder.items.length}</span>
                      </button>
                      <div className="mt-2 flex items-center gap-1.5">
                        <input
                          defaultValue={folder.name}
                          onBlur={(event) => renameFolder(folder.id, event.target.value)}
                          aria-label={`Renomear pasta ${folder.name}`}
                          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                        />
                        <button
                          type="button"
                          onClick={() => deleteFolder(folder.id)}
                          aria-label={`Apagar pasta ${folder.name}`}
                          title="Apagar pasta"
                          className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:border-rose-400/30 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
                        >
                          <X size={13} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {activeFolder && (
                <Card>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <FolderOpen size={18} className="text-teal-300" />
                      <h3 className="font-semibold">{activeFolder.name}</h3>
                      <span className="text-xs text-muted-foreground">
                        {activeFolder.items.length} fichas ·{" "}
                        {money(activeFolder.items.reduce((acc, entry) => acc + (entry.value ?? 0), 0))}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={addFavouritesToActiveFolder}
                        disabled={favouriteEntries.length === 0}
                        className="rounded-xl glass-card px-3 py-1.5 text-xs text-muted-foreground transition hover:text-teal-200 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        Juntar favoritos ({favouriteEntries.length})
                      </button>
                      <button
                        type="button"
                        onClick={() => setTab("graph")}
                        className="rounded-xl glass-card px-3 py-1.5 text-xs text-teal-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        Ver grafo do dossier
                      </button>
                    </div>
                  </div>
                  {activeFolder.items.length === 0 ? (
                    <p className="mt-4 text-sm text-muted-foreground">
                      Pasta vazia. Abra fichas e use «Guardar em pasta», ou junte os favoritos.
                    </p>
                  ) : (
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {activeFolder.items.map((entry) => (
                        <DossierEntryRow
                          key={`${entry.kind}-${entry.id}`}
                          entry={entry}
                          onOpen={() => openEntry(entry)}
                          onRemove={() => removeFromFolder(activeFolder.id, entry)}
                        />
                      ))}
                    </ul>
                  )}
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "history" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Registo local (neste browser) das fichas abertas, mais recentes primeiro.
            </p>
            <button
              type="button"
              onClick={clearHistory}
              disabled={history.length === 0}
              className="rounded-xl glass-card px-3 py-1.5 text-xs text-muted-foreground transition hover:text-rose-200 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
            >
              Limpar histórico
            </button>
          </div>
          {history.length === 0 ? (
            <Card className="p-10 text-center">
              <History size={36} className="mx-auto mb-3 text-muted-foreground/70" />
              <h2 className="text-lg font-semibold">Sem consultas registadas</h2>
              <p className="mt-1 text-sm text-muted-foreground">Abra uma ficha de entidade ou de contrato.</p>
            </Card>
          ) : (
            <Card>
              <ul className="grid gap-2 sm:grid-cols-2">
                {history.map((entry) => (
                  <DossierEntryRow
                    key={`${entry.kind}-${entry.id}`}
                    entry={entry}
                    onOpen={() => openEntry(entry)}
                    onRemove={activeFolder ? () => addToFolder(activeFolder.id, entry) : undefined}
                  />
                ))}
              </ul>
              <p className="mt-3 text-[11px] text-muted-foreground">
                {activeFolder
                  ? `O botão «×» move a ficha para a pasta «${activeFolder.name}» (em vez de remover).`
                  : "Crie uma pasta para poder guardar entradas a partir daqui."}
              </p>
            </Card>
          )}
        </div>
      )}

      {tab === "graph" && (
        <div className="space-y-4">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 font-semibold">
                  <GitBranch size={18} className="text-teal-300" /> Grafo do dossier
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {activeFolder ? `Pasta «${activeFolder.name}»` : "Favoritos + histórico recente"} ·{" "}
                  {dossierGraphResponse.nodes.length} nós · {dossierGraphResponse.edges.length} ligações
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {(["network", "hierarchical", "circular"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={layout === option}
                    onClick={() => {
                      setLayout(option);
                      setLayoutVersion((version) => version + 1);
                    }}
                    className={[
                      "rounded-xl px-3 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40",
                      layout === option ? "glass-card text-teal-200 ring-1 ring-teal-400/30" : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    {option === "network" ? "Rede" : option === "hierarchical" ? "Hierárquico" : "Circular"}
                  </button>
                ))}
                <span className="mx-1 h-5 w-px bg-white/10" />
                {(["valor", "contratos"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={metric === option}
                    onClick={() => setMetric(option)}
                    className={[
                      "rounded-xl px-3 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40",
                      metric === option ? "glass-card text-teal-200 ring-1 ring-teal-400/30" : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    {option === "valor" ? "Valor" : "Contratos"}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-3">
              {dossierGraph && dossierGraph.nodes.length > 0 ? (
                <GraphCanvas
                  graph={dossierGraph}
                  layout={layout}
                  metric={metric}
                  layoutVersion={layoutVersion}
                  loading={loadingContracts}
                  heightClass="h-[440px]"
                  onNodeClick={handleGraphNode}
                />
              ) : (
                <p className="rounded-xl border border-white/10 bg-white/[0.03] p-8 text-center text-sm text-muted-foreground">
                  Sem fichas suficientes no dossier para desenhar um grafo. Guarde empresas e contratos numa pasta.
                </p>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// --- Main page ---

export default function EmpresasIQPage({
  onNavigate,
}: {
  onNavigate?: (view: PlatformView) => void;
}) {
  const [section, setSection] = useState<EmpresasIQSection>("dashboard");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState<{ type: "entity" | "contract"; id: string } | null>(null);
  const [detailClosing, setDetailClosing] = useState(false);
  const [analytics, setAnalytics] = useState<ContractAnalyticsResponse | null>(null);
  const [regional, setRegional] = useState<ContractRegionalResponse | null>(null);
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, r, s] = await Promise.all([
        getContractAnalytics({ top_entities: 10, top_cpv: 8 }),
        getContractRegionalAnalytics(),
        getContractStatus(),
      ]);
      setAnalytics(a);
      setRegional(r);
      setStatus(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar dados");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!detail) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDetail();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  const handleSearch = () => {
    setSection("contracts");
    // global search could set a shared filter here
  };

  const openEntity = (nif: string) => {
    setDetail({ type: "entity", id: nif });
  };

  const openContract = (id: string) => {
    setDetail({ type: "contract", id });
  };

  // Fecha a ficha com o gesto inverso ao de abertura (o ficheiro volta a fechar-se).
  const closeDetail = () => {
    if (detailClosing) return;
    setDetailClosing(true);
    window.setTimeout(() => {
      setDetailClosing(false);
      setDetail(null);
    }, 175);
  };

  const content = useMemo(() => {
    if (loading) return <Loading />;
    if (error) {
      return (
        <Card className="p-8 text-center">
          <p className="text-rose-300">{error}</p>
          <button
            onClick={() => void load()}
            className="mt-4 px-4 py-2 rounded-xl bg-teal-400/10 text-teal-300 border border-teal-400/20 text-sm hover:bg-teal-400/20 transition"
          >
            Tentar novamente
          </button>
        </Card>
      );
    }

    switch (section) {
      case "dashboard":
        return (
          <DashboardSection
            analytics={analytics}
            regional={regional}
            status={status}
            onContracts={() => setSection("contracts")}
            onEntities={() => setSection("entities")}
            onGraph={() => setSection("graph")}
            onEntity={openEntity}
          />
        );
      case "contracts":
        return <ContractsSection onContract={openContract} onEntity={openEntity} />;
      case "entities":
        return <EntitiesSection onEntity={openEntity} />;
      case "graph":
        return <GraphSection onEntity={openEntity} onContract={openContract} onStudio={() => setSection("studio")} />;
      case "studio":
        return <GraphStudioPage />;
      case "analysis":
        return <AnalysisSection analytics={analytics} regional={regional} onEntity={openEntity} />;
      case "favorites":
        return <FavoritesSection onEntity={openEntity} onContract={openContract} />;
      case "settings":
        return <SettingsSection onEntity={openEntity} onContract={openContract} />;
      default:
        return null;
    }
  }, [analytics, error, loading, regional, section, status]);

  const handleNavigate = (view: PlatformView) => {
    if (typeof window !== "undefined") {
      const map: Record<PlatformView, string> = {
        chat: "/chat",
        dashboard: "/dashboard",
        search: "/search",
        "contracts-search": "/contracts/search",
        "contracts-dashboard": "/contracts/dashboard",
        "companies-search": "/companies/search",
        "companies-dashboard": "/companies/dashboard",
        tickers: "/tickers",
        forecast: "/forecast",
        trading: "/trading",
        rag: "/rag",
        elastic: "/elastic",
        settings: "/settings",
        cli: "/cli",
      };
      window.history.pushState({}, "", map[view]);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
    onNavigate?.(view);
  };

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg flex">
      <ModuleSidebar
        activeSection={section}
        onSectionChange={(s) => {
          setSection(s);
          closeDetail();
        }}
        onNavigate={handleNavigate}
      />
      <div className="flex-1 min-w-0 overflow-x-hidden">
        <Topbar q={q} setQ={setQ} onSearch={handleSearch} />
        <main className="p-4 pt-20 md:pt-4 min-w-0">{content}</main>
      </div>
      {detail && (
        <div
          className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-[#03080b]/55 p-3 pt-5 backdrop-blur-sm sm:p-6 sm:pt-8 lg:p-10 lg:pt-12"
          role="dialog"
          aria-modal="true"
          aria-label={detail.type === "entity" ? "Ficha da entidade" : "Detalhe do contrato"}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDetail();
          }}
        >
          {/* Ficheiro: aba por cima, folha de vidro por baixo (abre com um desdobrar). */}
          <div
            className={`flex w-full max-w-6xl flex-col ${detailClosing ? "file-closing" : "file-opening"}`}
          >
            <div className="file-tab pl-3 text-[11px] uppercase tracking-wide text-muted-foreground">
              <FileText size={13} className="text-teal-300" />
              <span className="text-foreground">
                {detail.type === "entity" ? "Ficha da entidade" : "Ficha do contrato"}
              </span>
              <span className="hidden truncate opacity-70 sm:inline">#{detail.id}</span>
            </div>
            <div className="file-sheet glass-modal gradient-border relative rounded-tl-none rounded-tr-2xl rounded-b-2xl">
              <button
                type="button"
                onClick={closeDetail}
                aria-label="Fechar ficha"
                title="Fechar ficha (Esc)"
                className="absolute right-3 top-3 z-10 rounded-lg border border-white/10 bg-white/[0.06] p-2 text-muted-foreground backdrop-blur-sm transition hover:bg-white/10 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              >
                <X size={18} />
              </button>
              <div className="file-body max-h-[calc(100vh-3.5rem)] overflow-y-auto p-3 pt-10 sm:max-h-[calc(100vh-5rem)] sm:p-6 sm:pt-12 lg:p-8 lg:pt-12">
                {detail.type === "entity" ? (
                  <EntityDetailPanel nif={detail.id} onBack={closeDetail} onContract={openContract} />
                ) : (
                  <ContractDetailPanel id={detail.id} onBack={closeDetail} onEntity={openEntity} />
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
