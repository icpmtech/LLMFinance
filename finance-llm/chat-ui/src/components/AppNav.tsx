import { useState } from "react";
import {
  MessageSquare,
  LayoutDashboard,
  Search,
  FileText,
  Building2,
  TrendingUp,
  CandlestickChart,
  FolderOpen,
  Database,
  ChevronDown,
  Menu,
  X,
  Sparkles,
  BarChart3,
  Network,
  Upload,
} from "lucide-react";

export type AppView =
  | "dashboard"
  | "chat"
  | "forecast"
  | "trading"
  | "tickers"
  | "ticker-detail"
  | "rag"
  | "elastic"
  | "search"
  | "contracts"
  | "contracts-search"
  | "contracts-dashboard"
  | "companies"
  | "companies-search"
  | "companies-dashboard"
  | "company-detail"
  | "entities-search"
  | "empresas-iq"
  | "import"
  | "contracts-list";

interface NavGroup {
  id: string;
  label: string;
  icon: React.ReactNode;
  items: { id: AppView; label: string; icon: React.ReactNode; match?: AppView[] }[];
}

interface AppNavProps {
  active: AppView;
  onNavigate: (view: AppView) => void;
  onBackToChat?: () => void;
}

const groups: NavGroup[] = [
  {
    id: "home",
    label: "Central",
    icon: <LayoutDashboard size={18} />,
    items: [
      { id: "chat", label: "Chat IA", icon: <MessageSquare size={18} /> },
      { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={18} /> },
      { id: "search", label: "Pesquisa Global", icon: <Search size={18} /> },
    ],
  },
  {
    id: "contracts",
    label: "Contratos Públicos",
    icon: <FileText size={18} />,
    items: [
      { id: "contracts-search", label: "Pesquisar Contratos", icon: <Search size={18} />, match: ["contracts", "contracts-search"] },
      { id: "contracts-dashboard", label: "Dashboard Contratos", icon: <BarChart3 size={18} />, match: ["contracts-dashboard"] },
    ],
  },
  {
    id: "companies",
    label: "Diretório de Empresas",
    icon: <Building2 size={18} />,
    items: [
      { id: "entities-search", label: "Pesquisar Empresas", icon: <Search size={18} />, match: ["entities-search"] },
      { id: "companies-search", label: "Pesquisar Entidades (Contratos)", icon: <Search size={18} />, match: ["companies", "companies-search"] },
      { id: "companies-dashboard", label: "Dashboard Empresas", icon: <BarChart3 size={18} />, match: ["companies-dashboard"] },
    ],
  },
  {
    id: "empresas-iq",
    label: "EmpresasIQ",
    icon: <Network size={18} />,
    items: [
      { id: "empresas-iq", label: "Inteligência Contratual", icon: <Network size={18} /> },
    ],
  },
  {
    id: "markets",
    label: "Mercados",
    icon: <TrendingUp size={18} />,
    items: [
      { id: "tickers", label: "Tickers & Ações", icon: <TrendingUp size={18} />, match: ["tickers", "ticker-detail"] },
      { id: "forecast", label: "Previsões", icon: <Sparkles size={18} /> },
      { id: "trading", label: "Trading Simulado", icon: <CandlestickChart size={18} /> },
    ],
  },
  {
    id: "tools",
    label: "Ferramentas",
    icon: <Database size={18} />,
    items: [
      { id: "rag", label: "RAG Documentos", icon: <FolderOpen size={18} /> },
      { id: "elastic", label: "Elasticsearch", icon: <Database size={18} /> },
      { id: "contracts-list", label: "Contratos", icon: <FileText size={18} />, match: ["contracts-list"] },
      { id: "import", label: "Importar Dados", icon: <Upload size={18} /> },
    ],
  },
];

function isActive(view: AppView, item: NavGroup["items"][number]): boolean {
  if (view === item.id) return true;
  if (item.match?.includes(view)) return true;
  return false;
}

function isGroupActive(view: AppView, group: NavGroup): boolean {
  return group.items.some((item) => isActive(view, item));
}

export function AppNav({ active, onNavigate, onBackToChat }: AppNavProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    groups.forEach((g) => (initial[g.id] = isGroupActive("dashboard", g)));
    return initial;
  });

  const toggleGroup = (id: string) => {
    setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleClick = (id: AppView) => {
    onNavigate(id);
    setMobileOpen(false);
  };

  const navContent = (
    <nav className="flex flex-col h-full">
      <div className="p-4 border-b border-border/60">
        <button
          onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl glass-card hover:bg-white/5 transition text-left"
        >
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Sparkles size={16} />
          </div>
          <div className="leading-tight">
            <p className="font-semibold text-sm">FinanceLLM</p>
            <p className="text-[11px] text-muted-foreground">Plataforma inteligente</p>
          </div>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-3 px-3 space-y-1">
        {groups.map((group) => {
          const groupActive = isGroupActive(active, group);
          const expanded = openGroups[group.id] ?? groupActive;
          return (
            <div key={group.id} className="mb-1">
              <button
                onClick={() => toggleGroup(group.id)}
                className={[
                  "w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition",
                  groupActive
                    ? "bg-primary/15 text-primary border border-primary/20"
                    : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
                ].join(" ")}
              >
                <span className="flex items-center gap-2.5">
                  <span className={groupActive ? "text-primary" : "text-muted-foreground"}>{group.icon}</span>
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
                    const itemActive = isActive(active, item);
                    return (
                      <button
                        key={item.id}
                        onClick={() => handleClick(item.id)}
                        className={[
                          "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition",
                          itemActive
                            ? "bg-primary/20 text-primary font-medium border border-primary/20"
                            : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
                        ].join(" ")}
                      >
                        <span className={itemActive ? "text-primary" : "text-muted-foreground/80"}>{item.icon}</span>
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
            Use o menu acima para navegar entre dados públicos, mercados e ferramentas.
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
          <span className="font-semibold text-sm">FinanceLLM</span>
        </div>
        <button
          onClick={() => setMobileOpen((v) => !v)}
          className="p-2 rounded-lg hover:bg-white/5 transition"
          aria-label="Menu"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-40 pt-14 bg-background/95 backdrop-blur-xl">
          {navContent}
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-[260px] shrink-0 h-screen glass-panel border-r border-border/60 flex-col">
        {navContent}
      </aside>
    </>
  );
}
