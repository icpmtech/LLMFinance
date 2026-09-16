import { useEffect, useState } from "react";
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
  ChevronRight,
  Menu,
  X,
  Sparkles,
  BarChart3,
  Network,
  PanelLeftClose,
  Settings,
  LogOut,
  ChevronUp,
  Upload,
} from "lucide-react";
import { useSidebarHidden } from "../layout";
import { useAuth } from "../auth";
import { Avatar } from "../pages/SettingsPage";

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
  | "settings"
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
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const { hidden: sidebarHidden, toggle: toggleSidebar } = useSidebarHidden();
  const { user, logout } = useAuth();
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

  useEffect(() => {
    if (!userMenuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUserMenuOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [userMenuOpen]);

  const accountMenu = (positionClass: string) => (
    <>
      {userMenuOpen && user && (
        <>
          <div className="fixed inset-0 z-[55]" onMouseDown={() => setUserMenuOpen(false)} aria-hidden="true" />
          <div
            role="menu"
            aria-label="Conta"
            className={`z-[60] overflow-hidden rounded-2xl border border-white/10 bg-[#14161b]/97 p-1.5 shadow-2xl backdrop-blur-xl ${positionClass}`}
          >
            <div className="flex items-center gap-3 rounded-xl px-3 py-2.5">
              <Avatar user={user} size={36} />
              <div className="min-w-0 leading-tight">
                <p className="truncate text-sm font-medium">{user.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">{user.email}</p>
              </div>
            </div>
            <div className="my-1 h-px bg-white/8" />
            <button
              role="menuitem"
              onClick={() => {
                setUserMenuOpen(false);
                handleClick("settings");
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
            >
              <Settings size={14} /> Definições da conta
            </button>
            <button
              role="menuitem"
              onClick={() => {
                setUserMenuOpen(false);
                void logout();
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-rose-300 transition hover:bg-rose-400/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50"
            >
              <LogOut size={14} /> Terminar sessão
            </button>
          </div>
        </>
      )}
    </>
  );

  const navContent = (
    <nav className="flex flex-col h-full">
      <div className="p-4 border-b border-border/60 flex items-center gap-2">
        <button
          onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
          className="flex-1 min-w-0 flex items-center gap-3 px-3 py-2.5 rounded-xl glass-card hover:bg-white/5 transition text-left"
        >
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Sparkles size={16} />
          </div>
          <div className="leading-tight">
            <p className="font-semibold text-sm">FinanceLLM</p>
            <p className="text-[11px] text-muted-foreground">Plataforma inteligente</p>
          </div>
        </button>
        <button
          onClick={toggleSidebar}
          aria-label="Ocultar barra lateral"
          title="Ocultar barra lateral (Ctrl+B)"
          className="hidden md:grid shrink-0 place-items-center h-9 w-9 rounded-xl text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <PanelLeftClose size={17} />
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

      <div className="p-4 border-t border-border/60 relative">
        <button
          type="button"
          onClick={() => setUserMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={userMenuOpen}
          className="w-full flex items-center gap-3 rounded-xl glass-card px-3 py-2.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          {user ? <Avatar user={user} size={34} /> : null}
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm font-medium">{user?.name ?? "Conta"}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{user?.title || user?.email || ""}</span>
          </span>
          <ChevronUp size={15} className={userMenuOpen ? "text-foreground" : "text-muted-foreground"} />
        </button>
        {accountMenu("absolute bottom-full left-4 right-4 mb-2")}
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
        <div className="flex items-center gap-2">
          {user && (
            <button
              type="button"
              onClick={() => setUserMenuOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={userMenuOpen}
              aria-label="Conta"
              className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
            >
              <Avatar user={user} size={30} />
            </button>
          )}
          <button
            onClick={() => setMobileOpen((v) => !v)}
            className="p-2 rounded-lg hover:bg-white/5 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
            aria-label="Menu"
            aria-controls="finance-llm-mobile-nav"
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        {accountMenu("fixed right-3 top-16 w-64")}
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div id="finance-llm-mobile-nav" className="md:hidden fixed inset-0 z-40 pt-14 bg-background/95 backdrop-blur-xl">
          {navContent}
        </div>
      )}

      {/* Pega para voltar a mostrar a barra lateral (desktop). */}
      {sidebarHidden && (
        <button
          onClick={toggleSidebar}
          aria-label="Mostrar barra lateral"
          title="Mostrar barra lateral (Ctrl+B)"
          className="hidden md:flex fixed left-0 top-1/2 -translate-y-1/2 z-40 items-center rounded-r-2xl border border-l-0 border-white/10 bg-[#111318]/92 py-4 pl-1 pr-1.5 text-muted-foreground shadow-lg backdrop-blur-xl transition hover:pr-4 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
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
          sidebarHidden ? "w-0 opacity-0 border-0" : "w-[260px] opacity-100 border-r border-border/60",
        ].join(" ")}
      >
        <div className="w-[260px] shrink-0 h-full">{navContent}</div>
      </aside>
    </>
  );
}
