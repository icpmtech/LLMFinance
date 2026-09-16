import { useEffect, useMemo, useRef, useState } from "react";
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
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  History,
  Menu,
  X,
  Sparkles,
  BarChart3,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  LogOut,
  Upload,
} from "lucide-react";
import { recordRecentView, useNavGroups, useRecentViews, useSidebar } from "../layout";
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

type NavItem = { id: AppView; label: string; icon: React.ReactNode; match?: AppView[]; keywords?: string };

interface NavGroup {
  id: string;
  label: string;
  icon: React.ReactNode;
  items: NavItem[];
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
      { id: "chat", label: "Chat IA", icon: <MessageSquare size={18} />, keywords: "conversa modelos gpt mistral" },
      { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={18} />, keywords: "mercado sentimento" },
      { id: "search", label: "Pesquisa Global", icon: <Search size={18} />, keywords: "procurar tudo" },
    ],
  },
  {
    id: "contracts",
    label: "Contratos Públicos",
    icon: <FileText size={18} />,
    items: [
      {
        id: "contracts-search",
        label: "Pesquisar Contratos",
        icon: <Search size={18} />,
        match: ["contracts", "contracts-search"],
        keywords: "base portal cpv adjudicante",
      },
      {
        id: "contracts-dashboard",
        label: "Dashboard Contratos",
        icon: <BarChart3 size={18} />,
        match: ["contracts-dashboard"],
        keywords: "indicadores valores",
      },
      { id: "contracts-list", label: "Contratos", icon: <FileText size={18} />, match: ["contracts-list"], keywords: "lista fichas" },
    ],
  },
  {
    id: "companies",
    label: "Diretório de Empresas",
    icon: <Building2 size={18} />,
    items: [
      { id: "entities-search", label: "Pesquisar Empresas", icon: <Search size={18} />, keywords: "nif cadastro" },
      {
        id: "companies-search",
        label: "Pesquisar Entidades (Contratos)",
        icon: <Search size={18} />,
        match: ["companies", "companies-search"],
        keywords: "adjudicante adjudicatário",
      },
      {
        id: "companies-dashboard",
        label: "Dashboard Empresas",
        icon: <BarChart3 size={18} />,
        match: ["companies-dashboard"],
        keywords: "ranking top",
      },
    ],
  },
  {
    id: "empresas-iq",
    label: "EmpresasIQ",
    icon: <Network size={18} />,
    items: [
      {
        id: "empresas-iq",
        label: "Inteligência Contratual",
        icon: <Network size={18} />,
        keywords: "grafos análise dossier",
      },
    ],
  },
  {
    id: "markets",
    label: "Mercados",
    icon: <TrendingUp size={18} />,
    items: [
      {
        id: "tickers",
        label: "Tickers & Ações",
        icon: <TrendingUp size={18} />,
        match: ["tickers", "ticker-detail"],
        keywords: "cotações ações",
      },
      { id: "forecast", label: "Previsões", icon: <Sparkles size={18} />, keywords: "arima kronos modelo" },
      { id: "trading", label: "Trading Simulado", icon: <CandlestickChart size={18} />, keywords: "carteira ordens" },
    ],
  },
  {
    id: "tools",
    label: "Ferramentas",
    icon: <Database size={18} />,
    items: [
      { id: "rag", label: "RAG Documentos", icon: <FolderOpen size={18} />, keywords: "pdf indexação" },
      { id: "elastic", label: "Elasticsearch", icon: <Database size={18} />, keywords: "índices pesquisa" },
      { id: "import", label: "Importar Dados", icon: <Upload size={18} />, keywords: "excel csv ingestão" },
      { id: "settings", label: "Definições", icon: <Settings size={18} />, keywords: "conta perfil preferências sessões" },
    ],
  },
];

const ALL_ITEMS: { item: NavItem; group: NavGroup }[] = groups.flatMap((group) =>
  group.items.map((item) => ({ item, group })),
);

/** Remove acentos e baixa para minúsculas, para pesquisa tolerante. */
function normalize(text: string) {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function isActive(view: AppView, item: NavItem): boolean {
  if (view === item.id) return true;
  if (item.match?.includes(view)) return true;
  return false;
}

function isGroupActive(view: AppView, group: NavGroup): boolean {
  return group.items.some((item) => isActive(view, item));
}

/** Item de navegação correspondente à vista ativa (resolve sub-vistas). */
function resolveItem(view: AppView): NavItem | undefined {
  return ALL_ITEMS.find(({ item }) => isActive(view, item))?.item;
}

export function AppNav({ active, onNavigate, onBackToChat }: AppNavProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { rail, hidden, setMode, toggleHidden, toggleRail } = useSidebar();
  const { openGroups, toggleGroup, setGroupOpen } = useNavGroups();
  const recent = useRecentViews();
  const { user, logout } = useAuth();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  /* Histórico de vistas (alimenta a secção «Recentes»). */
  useEffect(() => {
    const item = resolveItem(active);
    if (item) recordRecentView(item.id);
  }, [active]);

  const recentItems = useMemo(
    () =>
      recent
        .map((id) => ALL_ITEMS.find(({ item }) => item.id === id)?.item)
        .filter((item): item is NavItem => Boolean(item))
        .slice(0, 4),
    [recent],
  );

  const results = useMemo(() => {
    const term = normalize(query.trim());
    if (!term) return [];
    return ALL_ITEMS.filter(({ item, group }) =>
      `${normalize(item.label)} ${normalize(group.label)} ${normalize(item.keywords ?? "")}`.includes(term),
    );
  }, [query]);

  /* Atalhos: «/» ou Ctrl+K focam a pesquisa. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      const isSlash = event.key === "/" && !typing && !event.ctrlKey && !event.metaKey;
      const isCtrlK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
      if (!isSlash && !isCtrlK) return;
      event.preventDefault();
      if (rail) setMode("expanded");
      window.setTimeout(() => searchRef.current?.focus(), 40);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [rail, setMode]);

  useEffect(() => {
    if (!userMenuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUserMenuOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [userMenuOpen]);

  useKeyboardNavigation(listRef);

  const handleClick = (id: AppView) => {
    onNavigate(id);
    setMobileOpen(false);
  };

  const openGroupInExpanded = (group: NavGroup) => {
    setMode("expanded");
    setGroupOpen(group.id, true);
    window.setTimeout(() => searchRef.current?.focus(), 60);
  };

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

  /* --------------------------------------------------------------- rail */
  const railContent = (
    <nav className="flex h-full flex-col items-center gap-1 py-3" aria-label="Navegação principal (compacta)">
      <button
        onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
        title="FinanceLLM"
        aria-label="FinanceLLM"
        className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-500 to-blue-500 text-white shadow-lg shadow-primary/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <Sparkles size={16} />
      </button>

      <button
        onClick={() => setMode("expanded")}
        title="Expandir barra lateral"
        aria-label="Expandir barra lateral"
        className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <PanelLeftOpen size={16} />
      </button>

      <div className="my-1 h-px w-7 bg-white/10" />

      <div className="flex w-full flex-1 flex-col items-center gap-1 overflow-y-auto px-2">
        {groups.map((group) => {
          const groupActive = isGroupActive(active, group);
          return (
            <button
              key={group.id}
              onClick={() => openGroupInExpanded(group)}
              title={group.label}
              aria-label={group.label}
              className={[
                "relative grid h-10 w-10 place-items-center rounded-xl transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                groupActive
                  ? "bg-teal-400/15 text-teal-300"
                  : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
              ].join(" ")}
            >
              {group.icon}
              {groupActive && (
                <span
                  className="absolute -left-2 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-teal-300"
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}

        {recentItems.length > 0 && (
          <>
            <div className="my-1 h-px w-7 bg-white/10" />
            <span className="grid place-items-center py-1 text-muted-foreground/60" title="Recentes" aria-hidden="true">
              <History size={14} />
            </span>
            {recentItems.map((item) => (
              <button
                key={item.id}
                onClick={() => handleClick(item.id)}
                title={item.label}
                aria-label={item.label}
                className={[
                  "grid h-9 w-9 place-items-center rounded-xl transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                  isActive(active, item)
                    ? "bg-teal-400/15 text-teal-200"
                    : "text-muted-foreground/80 hover:bg-white/5 hover:text-foreground",
                ].join(" ")}
              >
                {item.icon}
              </button>
            ))}
          </>
        )}
      </div>

      <button
        onClick={() => setUserMenuOpen((open) => !open)}
        title={user ? `${user.name} · ${user.email}` : "Conta"}
        aria-label="Conta"
        aria-haspopup="menu"
        aria-expanded={userMenuOpen}
        className="relative rounded-full transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        {user ? <Avatar user={user} size={30} /> : null}
      </button>
      {accountMenu("fixed bottom-4 left-[84px] w-64")}
    </nav>
  );

  /* ------------------------------------------------- modo expandido/gaveta */
  const navContent = (
    <nav className="flex h-full flex-col" aria-label="Navegação principal">
      <div className="flex items-center gap-2 border-b border-border/60 p-3.5">
        <button
          onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
          className="flex min-w-0 flex-1 items-center gap-3 rounded-xl glass-card px-3 py-2.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
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
          onClick={toggleRail}
          aria-label="Modo compacto (só ícones)"
          title="Modo compacto (só ícones)"
          className="hidden md:grid shrink-0 place-items-center h-9 w-9 rounded-xl text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <PanelLeftClose size={17} />
        </button>
        <button
          onClick={toggleHidden}
          aria-label="Ocultar barra lateral"
          title="Ocultar barra lateral (Ctrl+B)"
          className="hidden md:grid shrink-0 place-items-center h-9 w-9 rounded-xl text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <ChevronLeft size={18} />
        </button>
      </div>

      <div className="px-3 pt-3" role="search">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setQuery("");
                event.currentTarget.blur();
              }
              if (event.key === "Enter" && results.length > 0) {
                handleClick(results[0].item.id);
                setQuery("");
              }
            }}
            placeholder="Ir para… ( / )"
            aria-label="Procurar na navegação"
            className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2 pl-8 pr-7 text-xs outline-none transition placeholder:text-muted-foreground focus:border-teal-300/40 focus:bg-white/[0.06]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Limpar pesquisa"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition hover:text-foreground"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      <div ref={listRef} className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
        {query.trim() ? (
          <SearchResults
            results={results}
            active={active}
            query={query.trim()}
            onSelect={(id) => {
              handleClick(id);
              setQuery("");
            }}
          />
        ) : (
          <>
            {recentItems.length > 0 && (
              <section className="mb-2">
                <p className="flex items-center gap-1.5 px-2 pb-1 text-[10px] uppercase tracking-wide text-muted-foreground/80">
                  <History size={12} /> Recentes
                </p>
                <div className="space-y-0.5">
                  {recentItems.map((item) => (
                    <NavButton
                      key={`recent-${item.id}`}
                      item={item}
                      active={isActive(active, item)}
                      onClick={() => handleClick(item.id)}
                    />
                  ))}
                </div>
              </section>
            )}

            {groups.map((group) => {
              const groupActive = isGroupActive(active, group);
              const expanded = openGroups[group.id] ?? groupActive;
              return (
                <div key={group.id}>
                  <button
                    onClick={() => toggleGroup(group.id, groupActive)}
                    aria-expanded={expanded}
                    className={[
                      "flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                      groupActive
                        ? "bg-teal-400/10 text-teal-200"
                        : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
                    ].join(" ")}
                  >
                    <span className="flex items-center gap-2.5">
                      <span className={groupActive ? "text-teal-300" : "text-muted-foreground"}>{group.icon}</span>
                      {group.label}
                    </span>
                    <ChevronDown size={15} className={expanded ? "rotate-180 transition-transform" : "transition-transform"} />
                  </button>
                  {expanded && (
                    <div className="ml-2 mt-0.5 space-y-0.5 border-l border-border/60 pl-2.5">
                      {group.items.map((item) => (
                        <NavButton
                          key={item.id}
                          item={item}
                          active={isActive(active, item)}
                          onClick={() => handleClick(item.id)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>

      <div className="relative border-t border-border/60 p-3.5">
        <button
          type="button"
          onClick={() => setUserMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={userMenuOpen}
          className="flex w-full items-center gap-3 rounded-xl glass-card px-3 py-2.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          {user ? <Avatar user={user} size={32} /> : null}
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm font-medium">{user?.name ?? "Conta"}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{user?.title || user?.email || ""}</span>
          </span>
          <ChevronUp size={15} className={userMenuOpen ? "text-foreground" : "text-muted-foreground"} />
        </button>
        <p className="mt-2 px-1 text-[10px] leading-relaxed text-muted-foreground/70">
          <kbd className="rounded border border-white/10 bg-white/5 px-1">Ctrl</kbd> +{" "}
          <kbd className="rounded border border-white/10 bg-white/5 px-1">B</kbd> oculta ·{" "}
          <kbd className="rounded border border-white/10 bg-white/5 px-1">/</kbd> pesquisa
        </p>
        {accountMenu("absolute bottom-full left-3.5 right-3.5 mb-2")}
      </div>
    </nav>
  );

  return (
    <>
      {/* Barra de topo (mobile) */}
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

      {/* Gaveta (mobile) */}
      {mobileOpen && (
        <div
          id="finance-llm-mobile-nav"
          className="md:hidden fixed inset-0 z-40 pt-14 bg-background/95 backdrop-blur-xl"
        >
          {navContent}
        </div>
      )}

      {/* Pega para reabrir quando escondida */}
      {hidden && (
        <button
          onClick={toggleHidden}
          aria-label="Mostrar barra lateral"
          title="Mostrar barra lateral (Ctrl+B)"
          className="hidden md:flex fixed left-0 top-1/2 z-40 -translate-y-1/2 items-center rounded-r-2xl border border-l-0 border-white/10 bg-[#111318]/92 py-4 pl-1 pr-1.5 text-muted-foreground shadow-lg backdrop-blur-xl transition hover:pr-4 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <ChevronRight size={16} />
        </button>
      )}

      {/* Barra lateral (desktop) */}
      <aside
        aria-hidden={hidden || undefined}
        inert={hidden || undefined}
        style={hidden ? { borderWidth: 0 } : undefined}
        className={[
          "hidden md:flex shrink-0 h-screen glass-panel flex-col overflow-hidden transition-[width,opacity] duration-300 ease-out",
          hidden
            ? "w-0 opacity-0 border-0"
            : rail
              ? "w-[72px] opacity-100 border-r border-border/60"
              : "w-[268px] opacity-100 border-r border-border/60",
        ].join(" ")}
      >
        <div className={rail ? "h-full w-[72px] shrink-0" : "h-full w-[268px] shrink-0"}>
          {rail ? railContent : navContent}
        </div>
      </aside>
    </>
  );
}

/* --------------------------------------------------------------- subpeças */

/** Item de navegação com realce da vista ativa (com barra de destaque à esquerda). */
function NavButton({ item, active, onClick }: { item: NavItem; active: boolean; onClick: () => void }) {
  return (
    <button
      data-nav
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={item.label}
      className={[
        "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
        active ? "bg-teal-400/15 font-medium text-teal-200" : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
      ].join(" ")}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-teal-300" aria-hidden="true" />
      )}
      <span className={active ? "text-teal-300" : "text-muted-foreground/80"}>{item.icon}</span>
      <span className="truncate">{item.label}</span>
    </button>
  );
}

/** Resultados da pesquisa rápida (lista plana, com o grupo de cada item). */
function SearchResults({
  results,
  active,
  query,
  onSelect,
}: {
  results: { item: NavItem; group: NavGroup }[];
  active: AppView;
  query: string;
  onSelect: (id: AppView) => void;
}) {
  if (results.length === 0) {
    return <p className="px-2 py-6 text-center text-xs text-muted-foreground">Sem resultados para «{query}».</p>;
  }
  return (
    <div aria-live="polite">
      <p className="px-2 pb-1 text-[10px] uppercase tracking-wide text-muted-foreground/80">
        {results.length} resultado{results.length === 1 ? "" : "s"} · Enter abre o primeiro
      </p>
      <div className="space-y-0.5">
        {results.map(({ item, group }) => (
          <div key={item.id}>
            <NavButton item={item} active={isActive(active, item)} onClick={() => onSelect(item.id)} />
            <p className="pb-1 pl-9 text-[10px] text-muted-foreground/70">{group.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Navegação por teclado (setas/Home/End) entre os itens visíveis. */
function useKeyboardNavigation(containerRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>("button[data-nav]"));
      if (buttons.length === 0) return;
      const currentIndex = buttons.indexOf(document.activeElement as HTMLButtonElement);
      let nextIndex = currentIndex;
      if (event.key === "ArrowDown") nextIndex = currentIndex < 0 ? 0 : Math.min(buttons.length - 1, currentIndex + 1);
      if (event.key === "ArrowUp") nextIndex = currentIndex < 0 ? buttons.length - 1 : Math.max(0, currentIndex - 1);
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = buttons.length - 1;
      event.preventDefault();
      buttons[nextIndex]?.focus();
    };
    container.addEventListener("keydown", onKeyDown);
    return () => container.removeEventListener("keydown", onKeyDown);
  }, [containerRef]);
}
