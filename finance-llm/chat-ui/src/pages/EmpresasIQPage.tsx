import { useCallback, useEffect, useMemo, useState, useRef } from "react";
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
  Database,
  Download,
  FileSearch,
  FileText,
  Filter,
  FolderHeart,
  FolderOpen,
  GitBranch,
  HandCoins,
  Heart,
  LayoutDashboard,
  List,
  Loader2,
  MapPin,
  Maximize2,
  Menu,
  MessageSquare,
  Minimize2,
  Network,
  RefreshCw,
  Search,
  Settings,
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
} from "../api";
import type {
  CompanyAnalyticsResponse,
  CompanyContractsResponse,
  CompanyDetail,
  CompanySearchResponse,
  ContractAnalyticsResponse,
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
}: {
  children: React.ReactNode;
  color?: "teal" | "blue" | "amber" | "rose" | "violet";
}) {
  const map = {
    teal: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
    blue: "bg-blue-400/10 text-blue-400 border-blue-400/20",
    amber: "bg-amber-400/10 text-amber-400 border-amber-400/20",
    rose: "bg-rose-400/10 text-rose-400 border-rose-400/20",
    violet: "bg-violet-400/10 text-violet-400 border-violet-400/20",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full border text-xs ${map[color]}`}>
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

type SimNode = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
  mass: number;
  degree: number;
  contracts?: number;
  region?: string;
  lat?: number;
  lon?: number;
  contractId?: string;
};

type SimEdge = {
  source: string;
  target: string;
  count: number;
  value: number;
};

const NODE_COLORS: Record<string, string> = {
  regiao: "#fbbf24",
  adjudicante: "#2dd4bf",
  adjudicatario: "#60a5fa",
  contrato: "#a78bfa",
  outra: "#fb7185",
};

function seedLatLon(label: string): { lat: number; lon: number } {
  // Deterministic pseudo-geographic seed for demo purposes (Portugal + islands)
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  const lat = 36.8 + (hash % 600) / 100;
  const lon = -9.8 + ((hash >> 10) % 500) / 100;
  return { lat, lon };
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
    const rawNodes = (graph?.nodes ?? []).map((n) => {
      const { lat, lon } = seedLatLon(n.label);
      return {
        ...n,
        lat,
        lon,
      };
    });

    // 1. Back-end filtering: value threshold + type filters
    const filteredEdges = (graph?.edges ?? [])
      .filter((e) => e.value >= options.minValue)
      .sort((a, b) => b.value - a.value);

    // 2. Back-end aggregation: collapse duplicate edges by (source,target)
    const edgeMap = new Map<string, SimEdge>();
    filteredEdges.forEach((e) => {
      const key = [e.source, e.target].sort().join("-");
      const existing = edgeMap.get(key);
      if (existing) {
        existing.count += e.count;
        existing.value += e.value;
      } else {
        edgeMap.set(key, { source: e.source, target: e.target, count: e.count, value: e.value });
      }
    });
    let edges = Array.from(edgeMap.values()).slice(0, options.edgeLimit);

    // Degree counting after aggregation
    const degree = new Map<string, number>();
    edges.forEach((e) => {
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
    });

    let nodes = rawNodes
      .filter((n) => {
        if (!options.showAdjudicantes && n.type === "adjudicante") return false;
        if (!options.showAdjudicatarios && n.type === "adjudicatario") return false;
        if (!options.showContracts && n.type === "contrato") return false;
        return true;
      })
      .map((n) => ({
        id: n.id,
        label: n.label,
        type: n.type,
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        radius: n.type === "regiao" ? 18 : n.type === "adjudicante" ? 22 : n.type === "contrato" ? 19 : 16,
        color: NODE_COLORS[n.type] || NODE_COLORS.outra,
        mass: n.type === "regiao" ? 3 : n.type === "adjudicante" ? 2 : n.type === "contrato" ? 1.5 : 1,
        degree: degree.get(n.id) || 0,
        contracts: n.count,
        contractId: n.contract_id,
        region: n.label.split(/[\s,]+/).pop(),
        lat: n.lat,
        lon: n.lon,
      }))
      .sort((a, b) => b.degree - a.degree)
      .slice(0, options.nodeLimit);

    // 4. Pruning leaf/orphan nodes + supernodes
    if (options.pruneLeaves) {
      nodes = nodes.filter((n) => n.degree >= 2);
    }
    if (options.hideSupernodes) {
      nodes = nodes.filter((n) => n.degree <= options.supernodeThreshold);
    }

    // Keep only edges whose endpoints survived
    const nodeSet = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => nodeSet.has(e.source) && nodeSet.has(e.target));

    // 3. Clever visual model: region combos
    if (options.groupByRegion) {
      const regions = new Map<string, SimNode[]>();
      nodes.forEach((n) => {
        const key = n.region || "Outro";
        if (!regions.has(key)) regions.set(key, []);
        regions.get(key)!.push(n);
      });
      nodes = nodes.map((n) => {
        const group = regions.get(n.region || "Outro") || [];
        const idx = group.indexOf(n);
        const angle = (idx / Math.max(group.length, 1)) * Math.PI * 2;
        return { ...n, x: Math.cos(angle) * 180, y: Math.sin(angle) * 180 };
      });
    } else {
      nodes.forEach((n, i) => {
        const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
        n.x = Math.cos(angle) * 140;
        n.y = Math.sin(angle) * 140;
      });
    }

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
}: {
  graph: ContractGraphResponse | null;
  view: GraphView;
  onViewChange: (v: GraphView) => void;
  selectedNodeId?: string | null;
  selectedEdgeKey?: string | null;
  onNodeClick?: (node: SimNode) => void;
  onEdgeClick?: (edge: SimEdge) => void;
}) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [hovered, setHovered] = useState<SimNode | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isExpanded, setIsExpanded] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [nodeSearch, setNodeSearch] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const draggingRef = useRef(false);
  const dragMovedRef = useRef(false);
  const lastPosRef = useRef({ x: 0, y: 0 });

  const [options, setOptions] = useState({
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
  });

  const { nodes, edges } = useGraphModel(graph, options);
  const searchMatches = useMemo(() => {
    const query = nodeSearch.trim().toLocaleLowerCase();
    if (!query) return [];
    return nodes
      .filter((node) => `${node.label} ${node.id} ${node.contractId ?? ""}`.toLocaleLowerCase().includes(query))
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
  const renderNodes = visibleNodeIds ? nodes.filter((node) => visibleNodeIds.has(node.id)) : nodes;
  const renderEdges = visibleNodeIds
    ? edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    : edges;

  // Map state
  // Reset viewport when navigation changes the graph dataset.
  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setNodeSearch("");
    setSearchFocused(false);
  }, [graph]);

  const [mapZoom, setMapZoom] = useState(6);
  const [mapCenter] = useState({ lat: 39.5, lon: -8.2 });
  const [mapOffset] = useState({ x: 0, y: 0 });
  const [tilesReady, setTilesReady] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  // Resize canvas to wrapper size with device pixel ratio
  useEffect(() => {
    const resize = () => {
      const canvas = canvasRef.current;
      const wrapper = wrapperRef.current;
      if (!canvas || !wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [isExpanded, isFullscreen]);

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

  useEffect(() => {
    if (view !== "network" && view !== "hierarchical" && view !== "circular") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let ticks = 0;

    function step() {
      if (!ctx || !canvas) return;
      ticks++;
      const width = canvas.width;
      const height = canvas.height;

      if (view === "hierarchical") {
        const levels = new Map<string, SimNode[]>();
        renderNodes.forEach((node) => {
          const level = node.type === "adjudicante" ? "adjudicante" : node.type === "adjudicatario" ? "adjudicatario" : "outra";
          if (!levels.has(level)) levels.set(level, []);
          levels.get(level)!.push(node);
        });
        const orderedLevels = ["adjudicante", "outra", "adjudicatario"];
        orderedLevels.forEach((level, levelIndex) => {
          const levelNodes = levels.get(level) ?? [];
          const spacing = Math.max(110, Math.min(220, 760 / Math.max(levelNodes.length, 1)));
          levelNodes.forEach((node, index) => {
            node.x = (index - (levelNodes.length - 1) / 2) * spacing;
            node.y = (levelIndex - 1) * 190;
            node.vx = 0;
            node.vy = 0;
          });
        });
      } else if (view === "circular") {
        const isRegionRoot = renderNodes.length > 0 && renderNodes.every((node) => node.type === "regiao");
        const radius = isRegionRoot
          ? Math.max(100, Math.min(220, Math.min(width, height) * 0.23))
          : Math.max(130, Math.min(330, Math.min(width, height) * 0.36));
        renderNodes.slice().sort((a, b) => b.degree - a.degree).forEach((node, index, ordered) => {
          const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2 - Math.PI / 2;
          node.x = Math.cos(angle) * radius;
          node.y = Math.sin(angle) * radius;
          node.vx = 0;
          node.vy = 0;
        });
      }

      // Organic layout: force-directed motion reveals natural clusters.
      if (view === "network") {
      for (let i = 0; i < renderNodes.length; i++) {
        for (let j = i + 1; j < renderNodes.length; j++) {
          const a = renderNodes[i];
          const b = renderNodes[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (2200 * a.mass * b.mass) / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx += fx / a.mass;
          a.vy += fy / a.mass;
          b.vx -= fx / b.mass;
          b.vy -= fy / b.mass;
        }
      }
      renderEdges.forEach((edge) => {
        const a = renderNodes.find((n) => n.id === edge.source)!;
        const b = renderNodes.find((n) => n.id === edge.target)!;
        if (!a || !b) return;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = 90;
        const force = ((dist - target) * 0.025) / 2;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });
      renderNodes.forEach((n) => {
        n.vx -= n.x * 0.003;
        n.vy -= n.y * 0.003;
        n.vx *= 0.88;
        n.vy *= 0.88;
        n.x += n.vx;
        n.y += n.vy;
      });
      }

      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(width / 2 + offset.x, height / 2 + offset.y);
      ctx.scale(scale, scale);

      // edges
      renderEdges.forEach((edge) => {
        const a = renderNodes.find((n) => n.id === edge.source)!;
        const b = renderNodes.find((n) => n.id === edge.target)!;
        if (!a || !b) return;
        const key = [edge.source, edge.target].sort().join("-");
        const isSelected = selectedEdgeKey === key;
        const isSearchRelated = !nodeSearch || searchMatchIds.has(edge.source) || searchMatchIds.has(edge.target);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        const baseAlpha = Math.min(0.62, 0.18 + edge.count * 0.045);
        const alpha = isSelected ? Math.min(0.95, baseAlpha + 0.28) : baseAlpha;
        ctx.strokeStyle = isSelected
          ? `rgba(251,191,36,${alpha})`
          : `rgba(125,211,252,${alpha})`;
        ctx.globalAlpha = isSearchRelated ? 1 : 0.14;
        ctx.lineWidth = isSelected
          ? Math.max(3, Math.log(edge.count + 1) + 1.5)
          : Math.max(1.5, Math.log(edge.count + 1) + 0.5);
        ctx.stroke();
        ctx.globalAlpha = 1;
      });

      // nodes
      renderNodes.forEach((n) => {
        const isSelected = selectedNodeId === n.id;
        const isHovered = n.id === hovered?.id;
        const isSearchMatch = !nodeSearch || searchMatchIds.has(n.id);
        const nodeRadius = isSelected ? n.radius + 5 : isHovered ? n.radius + 3 : n.radius;
        ctx.beginPath();
        ctx.arc(n.x, n.y, nodeRadius, 0, Math.PI * 2);
        ctx.globalAlpha = isSearchMatch ? 1 : 0.2;
        ctx.shadowBlur = isSelected || (nodeSearch && isSearchMatch) ? 24 : isHovered ? 18 : 10;
        ctx.shadowColor = n.color;
        const fill = ctx.createRadialGradient(
          n.x - nodeRadius * 0.35,
          n.y - nodeRadius * 0.35,
          1,
          n.x,
          n.y,
          nodeRadius
        );
        fill.addColorStop(0, n.color);
        fill.addColorStop(0.38, `${n.color}cc`);
        fill.addColorStop(1, "rgba(7,21,27,0.98)");
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.lineWidth = isSelected ? 4 : isHovered ? 3.5 : 2.5;
        ctx.strokeStyle = isSelected || isHovered ? "#ffffff" : n.color;
        ctx.stroke();
        ctx.fillStyle = "#f8fafc";
        const showLabel = n.type === "regiao" || isSelected || n.id === hovered?.id || n.degree >= (view === "circular" ? 3 : 1);
        if (showLabel) {
          ctx.font = isSelected ? "bold 12px ui-sans-serif, system-ui" : isHovered ? "bold 11px ui-sans-serif, system-ui" : "10px ui-sans-serif, system-ui";
          const text = n.label.length > 18 ? n.label.slice(0, 16) + "…" : n.label;
          const labelX = n.x + nodeRadius + 6 + (isSelected ? 2 : 0);
          const labelY = n.y + 3;
          const labelWidth = ctx.measureText(text).width + 8;
          ctx.fillStyle = "rgba(3,12,17,0.88)";
          ctx.fillRect(labelX - 4, labelY - 10, labelWidth, 16);
          ctx.fillStyle = isSelected || isHovered ? "#ffffff" : "#dbeafe";
          ctx.fillText(text, labelX, labelY);
        }
        ctx.globalAlpha = 1;
      });

      ctx.restore();
      if (ticks < 250) {
        raf = requestAnimationFrame(step);
      }
    }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [renderNodes, renderEdges, scale, offset, view, hovered, selectedNodeId, selectedEdgeKey, nodeSearch, searchMatchIds]);

  const handleWheel = (e: React.WheelEvent) => {
    e.stopPropagation();
    setScale((s) => Math.min(3, Math.max(0.5, s - e.deltaY * 0.001)));
  };

  const hoveredInfo = hovered ? (
    <div
      className="absolute z-20 max-w-[220px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl pointer-events-none"
      style={{ left: mousePos.x + 14, top: mousePos.y + 14 }}
    >
      <p className="text-sm font-medium text-foreground">{hovered.label}</p>
      <p className="text-xs text-muted-foreground capitalize mt-0.5">{hovered.type}</p>
        <p className="text-xs text-teal-300 mt-1">
          {hovered.type === "regiao" ? `${compact(hovered.contracts ?? 0)} contratos` : `${hovered.degree} ligações`}
        </p>
    </div>
  ) : null;

  // OSM helpers
  function deg2num(lat: number, lon: number, zoom: number) {
    const n = 2 ** zoom;
    const xtile = Math.floor(((lon + 180) / 360) * n);
    const latRad = (lat * Math.PI) / 180;
    const ytile = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
    return { x: xtile, y: ytile, n };
  }

  function osmUrl(z: number, x: number, y: number) {
    return `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
  }

  const mapTiles = useMemo(() => {
    const { x, y, n } = deg2num(mapCenter.lat, mapCenter.lon, mapZoom);
    const cols = 4;
    const rows = 3;
    const tiles: { url: string; left: number; top: number; x: number; y: number }[] = [];
    for (let dy = -Math.floor(rows / 2); dy <= Math.floor(rows / 2); dy++) {
      for (let dx = -Math.floor(cols / 2); dx <= Math.floor(cols / 2); dx++) {
        const tx = (x + dx + n) % n;
        const ty = y + dy;
        if (ty < 0 || ty >= n) continue;
        tiles.push({
          url: osmUrl(mapZoom, tx, ty),
          left: (dx + 1.5) * 256 + mapOffset.x,
          top: (dy + 1) * 256 + mapOffset.y,
          x: tx,
          y: ty,
        });
      }
    }
    return tiles;
  }, [mapCenter, mapZoom, mapOffset]);

  const projectMap = (lat: number, lon: number) => {
    const { x: cx, y: cy, n } = deg2num(mapCenter.lat, mapCenter.lon, mapZoom);
    const p = deg2num(lat, lon, mapZoom);
    const dx = p.x - cx + (p.x < cx - n / 2 ? n : p.x > cx + n / 2 ? -n : 0);
    const dy = p.y - cy;
    return {
      left: (dx + 1.5) * 256 + mapOffset.x + 128,
      top: (dy + 1) * 256 + mapOffset.y + 64,
    };
  };

  const hasData = renderNodes.length > 0;
  const handleMapSurfaceClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (view !== "map" || (event.target as HTMLElement).closest("button")) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const clickX = event.clientX - rect.left;
    const clickY = event.clientY - rect.top;
    const nearest = renderNodes
      .map((node) => {
        const position = projectMap(node.lat ?? mapCenter.lat, node.lon ?? mapCenter.lon);
        return { node, distance: Math.hypot(position.left - clickX, position.top - clickY) };
      })
      .sort((a, b) => a.distance - b.distance)[0];
    if (nearest && nearest.distance <= 55) onNodeClick?.(nearest.node);
  };

  return (
    <div
      ref={wrapperRef}
      onClick={handleMapSurfaceClick}
      onPointerDown={handleMapSurfaceClick}
      className={[
        isExpanded ? "fixed inset-3 z-[70] shadow-2xl" : "relative w-full h-full",
        "rounded-2xl border border-white/10 bg-[#07151b] overflow-hidden",
      ].join(" ")}
    >
      {/* Toolbar */}
      <div className="pointer-events-auto absolute top-3 right-3 z-40 flex flex-col gap-2">
        <div className="relative self-end">
          <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-[#07151b]/95 px-2 py-1.5 shadow-xl">
            <Search size={14} className="text-muted-foreground" />
            <input
              value={nodeSearch}
              onChange={(event) => setNodeSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && searchMatches[0]) onNodeClick?.(searchMatches[0]);
              }}
              placeholder="Pesquisar no grafo..."
              aria-label="Pesquisar no grafo"
              className="w-48 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
            {nodeSearch && <span className="text-[10px] text-teal-300">{searchMatches.length}</span>}
            {nodeSearch && searchMatches.length > 0 && (
              <button
                type="button"
                onClick={() => setSearchFocused(true)}
                aria-label="Criar grafo da pesquisa"
                title="Criar grafo da pesquisa"
                className={searchFocused ? "rounded bg-teal-400/20 p-1 text-teal-200" : "rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-teal-200"}
              >
                <Network size={13} />
              </button>
            )}
            {searchFocused && (
              <button
                type="button"
                onClick={() => setSearchFocused(false)}
                aria-label="Mostrar grafo completo"
                title="Mostrar grafo completo"
                className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
              >
                <X size={13} />
              </button>
            )}
          </div>
          {nodeSearch && searchMatches.length > 0 && (
            <div className="absolute right-0 top-full mt-1 w-64 overflow-hidden rounded-lg border border-white/10 bg-[#07151b]/98 shadow-xl">
              {searchMatches.map((match) => (
                <button
                  key={match.id}
                  type="button"
                  onClick={() => onNodeClick?.(match)}
                  className="block w-full border-b border-white/5 px-3 py-2 text-left last:border-0 hover:bg-white/10"
                >
                  <span className="block truncate text-xs text-foreground">{match.label}</span>
                  <span className="block truncate text-[10px] capitalize text-muted-foreground">{match.type} · {match.id}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {(["network", "hierarchical", "circular", "map", "list"] as GraphView[]).map((v) => (
            <button
              key={v}
              onClick={() => onViewChange(v)}
              className={[
                "px-2.5 py-1.5 rounded-lg text-xs flex items-center gap-1.5 transition border",
                view === v
                  ? "bg-teal-400/15 text-teal-300 border-teal-400/30"
                  : "glass-card border-white/10 hover:bg-white/5",
              ].join(" ")}
            >
              {v === "network" && <Network size={14} />}
              {v === "hierarchical" && <GitBranch size={14} />}
              {v === "circular" && <Circle size={14} />}
              {v === "map" && <MapPin size={14} />}
              {v === "list" && <List size={14} />}
              {v === "network" ? "Organic" : v === "hierarchical" ? "Hierarchical" : v === "circular" ? "Circular" : v === "map" ? "Mapa" : "Lista"}
            </button>
          ))}
          <button
            onClick={() => void toggleFullscreen()}
            aria-label={isFullscreen || isExpanded ? "Sair do ecrã inteiro" : "Abrir ecrã inteiro"}
            title={isFullscreen || isExpanded ? "Sair do ecrã inteiro (Esc)" : "Abrir ecrã inteiro"}
            className="px-2.5 py-1.5 rounded-lg text-xs flex items-center gap-1.5 transition border glass-card border-white/10 hover:bg-white/5"
          >
            {isFullscreen || isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            {isFullscreen || isExpanded ? "Sair" : "Ecrã inteiro"}
          </button>
        </div>
        <div className="self-end rounded-lg border border-white/10 bg-[#07151b]/90 px-2.5 py-1 text-[11px] text-muted-foreground">
          Clique num node para expandir · linha para ver contratos
        </div>
      </div>

      {hoveredInfo}

      {!hasData && view !== "list" ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground z-10">
          <Search size={32} className="mb-3 opacity-40" />
          <p className="text-sm">Sem dados para visualizar</p>
          <p className="text-xs mt-1">Escolha uma região ou aguarde carregamento.</p>
        </div>
      ) : view === "list" ? (
        <div className="absolute inset-0 z-10 overflow-auto bg-[#07151b] p-4 pt-20">
          <div className="mb-3 flex items-center justify-between border-b border-white/10 pb-2 text-xs text-muted-foreground">
            <span>{renderNodes.length} nós no grafo</span>
            <span>Selecione um nó para navegar</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {renderNodes.map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => onNodeClick?.(node)}
                className="rounded-xl border border-white/10 bg-white/[0.04] p-3 text-left transition hover:border-teal-300/50 hover:bg-white/[0.08]"
              >
                <span className="block truncate text-sm text-foreground">{node.label}</span>
                <span className="mt-1 block text-xs capitalize text-muted-foreground">
                  {node.type === "regiao" ? `${compact(node.contracts ?? 0)} contratos` : node.type === "contrato" ? "Contrato" : `${node.degree} ligações`}
                </span>
              </button>
            ))}
          </div>
          {renderNodes.length === 0 && <p className="py-12 text-center text-sm text-muted-foreground">Sem nós para apresentar.</p>}
        </div>
      ) : view === "map" ? (
        <div
          className="relative w-full h-full overflow-hidden bg-[#0a1f29]"
        >
          {/* OSM tiles */}
          {mapTiles.map((t) => (
            <img
              key={`${t.x}-${t.y}`}
              src={t.url}
              alt=""
              crossOrigin="anonymous"
              className="absolute opacity-70 transition-opacity duration-300"
              style={{ left: t.left, top: t.top, width: 256, height: 256 }}
              onLoad={() => setTilesReady((n) => n + 1)}
              onError={() => setTilesReady((n) => n + 1)}
            />
          ))}
          {tilesReady < mapTiles.length && mapTiles.length > 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xs z-10">
              <RefreshCw size={16} className="animate-spin mr-2" /> A carregar mapa…
            </div>
          )}
          {/* Overlay nodes */}
          <div className="absolute inset-0 z-10 pointer-events-auto">
            {renderNodes.map((n) => {
              const pos = projectMap(n.lat, n.lon);
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onNodeClick?.(n);
                  }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    onNodeClick?.(n);
                  }}
                  className="absolute z-10 flex cursor-pointer flex-col items-center"
                  style={{ left: pos.left, top: pos.top, transform: "translate(-50%, -50%)" }}
                  title={`Abrir ${n.label}`}
                >
                  <div
                    className="rounded-full border-2 shadow-[0_2px_8px_rgba(0,0,0,0.6]"
                    style={{
                      width: n.radius * 2,
                      height: n.radius * 2,
                      background: "rgba(8,28,36,0.95)",
                      borderColor: n.color,
                    }}
                  />
                  <span className="text-[9px] whitespace-nowrap mt-0.5 px-1.5 py-0.5 rounded bg-[#07151b]/90 text-white shadow-sm">
                    {n.label.length > 14 ? n.label.slice(0, 12) + "…" : n.label}
                  </span>
                </button>
              );
            })}
          </div>
          {/* Map controls */}
          <div className="absolute bottom-3 right-3 flex gap-2">
            <span className="flex items-center rounded-lg border border-white/10 bg-[#07151b]/90 px-2 text-[11px] text-muted-foreground">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={() => setMapZoom((z) => Math.min(18, z + 1))}
              aria-label="Aproximar mapa"
              title="Aproximar mapa"
              className="p-1.5 rounded-lg glass-card hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomIn size={16} />
            </button>
            <button
              onClick={() => setMapZoom((z) => Math.max(3, z - 1))}
              aria-label="Afastar mapa"
              title="Afastar mapa"
              className="p-1.5 rounded-lg glass-card hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomOut size={16} />
            </button>
          </div>
        </div>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            className={`w-full h-full ${hovered ? "cursor-pointer" : "cursor-move"}`}
            onWheel={handleWheel}
            onMouseMove={(e) => {
              const canvas = canvasRef.current;
              if (!canvas) return;
              const rect = canvas.getBoundingClientRect();
              const x = (e.clientX - rect.left - rect.width / 2 - offset.x) / scale;
              const y = (e.clientY - rect.top - rect.height / 2 - offset.y) / scale;
              const found = renderNodes.find((n) => {
                const dx = n.x - x;
                const dy = n.y - y;
                return Math.sqrt(dx * dx + dy * dy) <= n.radius + 4;
              });
              setHovered(found || null);
              setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
              if (draggingRef.current) {
                const dx = e.clientX - lastPosRef.current.x;
                const dy = e.clientY - lastPosRef.current.y;
                lastPosRef.current = { x: e.clientX, y: e.clientY };
                dragMovedRef.current = dragMovedRef.current || Math.abs(dx) > 2 || Math.abs(dy) > 2;
                setOffset((o) => ({ x: o.x + dx, y: o.y + dy }));
              }
            }}
            onMouseDown={(e) => {
              draggingRef.current = true;
              dragMovedRef.current = false;
              lastPosRef.current = { x: e.clientX, y: e.clientY };
            }}
            onMouseUp={() => {
              draggingRef.current = false;
            }}
            onClick={(e) => {
              if (dragMovedRef.current) return;
              const canvas = canvasRef.current;
              if (!canvas) return;
              const rect = canvas.getBoundingClientRect();
              const x = (e.clientX - rect.left - rect.width / 2 - offset.x) / scale;
              const y = (e.clientY - rect.top - rect.height / 2 - offset.y) / scale;
              const found = renderNodes.find((n) => {
                const dx = n.x - x;
                const dy = n.y - y;
                return Math.sqrt(dx * dx + dy * dy) <= n.radius + 4;
              });
              if (found) {
                onNodeClick?.(found);
                return;
              }
              const edgeHit = renderEdges.find((edge) => {
                const source = renderNodes.find((n) => n.id === edge.source);
                const target = renderNodes.find((n) => n.id === edge.target);
                if (!source || !target) return false;
                const dx = target.x - source.x;
                const dy = target.y - source.y;
                const lengthSquared = dx * dx + dy * dy || 1;
                const projection = Math.max(
                  0,
                  Math.min(1, ((x - source.x) * dx + (y - source.y) * dy) / lengthSquared)
                );
                const nearX = source.x + projection * dx;
                const nearY = source.y + projection * dy;
                return Math.hypot(x - nearX, y - nearY) <= 8 / scale;
              });
              if (edgeHit) {
                onEdgeClick?.(edgeHit);
              }
            }}
            onMouseLeave={() => {
              draggingRef.current = false;
              setHovered(null);
            }}
          />
          <div className="absolute bottom-3 right-3 flex gap-2">
            <span className="flex items-center rounded-lg border border-white/10 bg-[#07151b]/90 px-2 text-[11px] text-muted-foreground">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={() => {
                setScale(1);
                setOffset({ x: 0, y: 0 });
              }}
              aria-label="Recentrar grafo"
              title="Recentrar grafo"
              className="p-1.5 rounded-lg glass-card hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={() => setScale((s) => Math.min(3, s + 0.2))}
              aria-label="Aproximar"
              title="Aproximar"
              className="p-1.5 rounded-lg glass-card hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomIn size={16} />
            </button>
            <button
              onClick={() => setScale((s) => Math.max(0.5, s - 0.2))}
              aria-label="Afastar"
              title="Afastar"
              className="p-1.5 rounded-lg glass-card hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <ZoomOut size={16} />
            </button>
          </div>
        </>
      )}

      {/* Filter panel */}
      <div className="absolute bottom-3 left-3 z-20 max-w-[260px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl">
        <p className="text-xs font-semibold mb-2 flex items-center gap-1.5">
          <Filter size={12} /> Filtros do grafo
        </p>
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <label className="text-[11px] text-muted-foreground">Máx nós</label>
            <input
              type="range"
              min={10}
              max={100}
              value={options.nodeLimit}
              onChange={(e) => setOptions((o) => ({ ...o, nodeLimit: Number(e.target.value) }))}
              className="w-24 accent-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 rounded"
            />
            <span className="text-[11px] w-6 text-right">{options.nodeLimit}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <label className="text-[11px] text-muted-foreground">Valor mín. (€)</label>
            <input
              type="number"
              min={0}
              step={1000}
              value={options.minValue}
              onChange={(e) => setOptions((o) => ({ ...o, minValue: Number(e.target.value) }))}
              className="w-20 bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-[11px] focus:outline-none focus-visible:border-teal-400/50 focus-visible:ring-1 focus-visible:ring-teal-400/30"
            />
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            {[
              { key: "showAdjudicantes", label: "Adjudicantes" },
              { key: "showAdjudicatarios", label: "Adjudicatários" },
              { key: "showContracts", label: "Contratos" },
              { key: "pruneLeaves", label: "Sem folhas" },
              { key: "hideSupernodes", label: "Ocultar supernós" },
              { key: "groupByRegion", label: "Agrupar por região" },
            ].map((opt) => {
              const key = opt.key as keyof typeof options;
              const checked = Boolean(options[key]);
              return (
                <label
                  key={opt.key}
                  className="flex items-center gap-1.5 text-[11px] cursor-pointer select-none"
                >
                  <span className="relative inline-flex items-center justify-center w-4 h-4 rounded border border-white/20 bg-white/5 transition focus-within:ring-2 focus-within:ring-teal-400/50">
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      checked={checked}
                      onChange={(e) => setOptions((o) => ({ ...o, [key]: e.target.checked }))}
                    />
                    <svg
                      className={`w-3 h-3 text-teal-400 transition ${checked ? "opacity-100" : "opacity-0"}`}
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
  | "elastic";

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
      <div className="p-4 border-b border-border/60">
        <button
          onClick={() => onNavigate("chat")}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl glass-card hover:bg-white/5 transition text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Sparkles size={16} />
          </div>
          <div className="leading-tight">
            <p className="font-semibold text-sm">FinanceLLM</p>
            <p className="text-[11px] text-muted-foreground">Voltar à plataforma</p>
          </div>
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
        <div className="glass-card rounded-xl p-3">
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            EmpresasIQ — navegue entre o universo de contratos públicos e as restantes ferramentas da plataforma.
          </p>
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

      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-[220px] shrink-0 h-screen glass-panel border-r border-border/60 flex-col">
        {navContent}
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
}: {
  onEntity: (nif: string) => void;
  onContract: (id: string) => void;
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
  const regionOverviewGraph = useMemo<ContractGraphResponse>(
    () => ({
      nodes: regions
        .filter((region) => !/não especificado/i.test(region.key))
        .map((region) => ({
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
      setView("circular");
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
  const graphView = !activeRegion && view !== "map" && view !== "list" ? "circular" : view;
  const activeNodeId = selectedEntity?.id ?? null;

  const breadcrumb = useMemo(() => {
    const steps: { label: string; onClick?: () => void }[] = [{ label: "Regiões" }];
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

      <div className="flex flex-col xl:flex-row gap-4 w-full flex-1 min-h-0">
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
                    className="w-full text-left rounded-xl border border-white/8 bg-white/[0.03] hover:bg-white/[0.06] px-3 py-2.5 transition"
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
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#2dd4bf]" />
                    <span>Adjudicante</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#60a5fa]" />
                    <span>Adjudicatário</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#f59e0b]" />
                    <span>Ambos os papéis</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-[#a78bfa]" />
                    <span>Contrato</span>
                  </div>
                </div>
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
                <YAxis stroke="rgba(255,255,255,0.3)" fontSize={12} tickFormatter={(v) => compact(v)} />
                <Tooltip
                  contentStyle={{
                    background: "rgba(7,21,27,0.95)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 12,
                  }}
                  formatter={euroFormatter}
                />
                <Line
                  type="monotone"
                  dataKey="total_value"
                  stroke="#10a37f"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#10a37f" }}
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#3b82f6" }}
                  yAxisId={1}
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
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="px-3 py-1.5 rounded-full glass-card text-sm text-muted-foreground hover:text-foreground transition flex items-center gap-2"
        >
          <ArrowUpRight size={16} className="rotate-[-135deg]" /> Voltar
        </button>
        <button className="px-3 py-1.5 rounded-xl glass-card text-sm flex items-center gap-2 text-rose-300 hover:bg-white/5">
          <Heart size={16} /> Adicionar aos Favoritos
        </button>
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
          <button className="px-3 py-1.5 rounded-xl glass-card text-sm flex items-center gap-2 text-rose-300 hover:bg-white/5">
            <Heart size={16} /> Favorito
          </button>
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

// --- FAVORITES / SETTINGS placeholders ---

function FavoritesSection() {
  return (
    <Card className="p-12 text-center">
      <Heart size={40} className="mx-auto text-rose-400 mb-4" />
      <h2 className="text-xl font-semibold">Favoritos</h2>
      <p className="text-sm text-muted-foreground mt-2">
        As entidades e contratos marcados aparecerão aqui.
      </p>
    </Card>
  );
}

function SettingsSection() {
  return (
    <Card className="p-12 text-center">
      <Settings size={40} className="mx-auto text-muted-foreground mb-4" />
      <h2 className="text-xl font-semibold">Configurações</h2>
      <p className="text-sm text-muted-foreground mt-2">
        Preferências do módulo EmpresasIQ em desenvolvimento.
      </p>
    </Card>
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
      if (event.key === "Escape") setDetail(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
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

  const closeDetail = () => setDetail(null);

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
        return <GraphSection onEntity={openEntity} onContract={openContract} />;
      case "analysis":
        return <AnalysisSection analytics={analytics} regional={regional} onEntity={openEntity} />;
      case "favorites":
        return <FavoritesSection />;
      case "settings":
        return <SettingsSection />;
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
          className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/70 p-3 backdrop-blur-md sm:p-6 lg:p-10"
          role="dialog"
          aria-modal="true"
          aria-label={detail.type === "entity" ? "Ficha da entidade" : "Detalhe do contrato"}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDetail();
          }}
        >
          <div className="relative w-full max-w-6xl rounded-2xl border border-white/15 bg-[#07151b]/95 shadow-2xl shadow-black/50 backdrop-blur-xl">
            <button
              type="button"
              onClick={closeDetail}
              aria-label="Fechar ficha"
              title="Fechar ficha (Esc)"
              className="absolute right-3 top-3 z-10 rounded-lg border border-white/10 bg-white/[0.06] p-2 text-muted-foreground transition hover:bg-white/10 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            >
              <X size={18} />
            </button>
            <div className="max-h-[calc(100vh-1.5rem)] overflow-y-auto p-3 sm:max-h-[calc(100vh-3rem)] sm:p-6 lg:p-8">
              {detail.type === "entity" ? (
                <EntityDetailPanel nif={detail.id} onBack={closeDetail} onContract={openContract} />
              ) : (
                <ContractDetailPanel id={detail.id} onBack={closeDetail} onEntity={openEntity} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
