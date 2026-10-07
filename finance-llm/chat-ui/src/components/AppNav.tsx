import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  History,
  Menu,
  PanelLeft,
  PanelLeftOpen,
  Settings,
  LogOut,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
  Plus,
} from "lucide-react";
import { DOCK_CATALOG, IFRAME_PAGES_APP, type DockApp } from "../dock";
import { CRM_SUITE_GROUPS } from "../crmSuite";
import { dropHidden, hiddenModules, useSidebarAccess } from "../sidebarAccess";
import { APP_MODULES, CRM_VIEW_IDS, TOOL_APP_IDS, dockAppById } from "../sidebarCatalog";
import { useWindows } from "../windows";
import {
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_RAIL_WIDTH,
  recordRecentView,
  useNavGroups,
  useRecentViews,
  useSidebar,
  useSidebarWidth,
  useWindowMode,
} from "../layout";
import { useAuth } from "../auth";
import { Avatar } from "../pages/SettingsPage";
import { getIframeRevision, iframeDockApps, subscribeIframePages } from "../iframePages";

export type AppView =
  | "dashboard"
  | "chat"
  | "browser"
  | "finder"
  | "compare"
  | "forecast"
  | "trading"
  | "tickers"
  | "ticker-detail"
  | "ticker-chart"
  | "rag"
  | "elastic"
  | "search"
  | "pesquisa"
  | "sentimento"
  | "cire"
  | "citacoes"
  | "contribuintes"
  | "world"
  | "world-rede"
  | "padroes"
  | "osint"
  | "mirofish"
  | "simulador"
  | "risco"
  | "societario"
  | "empresas-recolha"
  | "gleif"
  | "gleif-mapa"
  | "gleif-ingestao"
  | "contracts"
  | "contracts-search"
  | "contracts-dashboard"
  | "companies"
  | "companies-search"
  | "companies-dashboard"
  | "company-detail"
  | "entities-search"
  | "entities-dashboard"
  | "entities-adjudicantes"
  | "entities-adjudicatarios"
  | "entities-compare"
  | "empresas-iq"
  | "pessoas-iq"
  | "companies-global"
  | "crm"
  | "crm-accounts"
  | "crm-contacts"
  | "crm-agenda"
  | "crm-dashboard"
  | `crm-mod:${string}`
  | "scraper"
  | "scraper-templates"
  | "scraper-execucoes"
  | "scraper-pesquisa"
  | "scraper-agenda"
  | "social"
  | "social-canais"
  | "social-execucoes"
  | "social-modelos"
  | "social-agenda"
  | "social-estado"
  | "search360"
  | "search360-dossie"
  | "search360-projetos"
  | "search360-grafo"
  | "search360-biblioteca"
  | "hermes"
  | "jarvis"
  | "office"
  | "office-dossies"
  | "docs"
  | "cms"
  | "rss"
  | "noticias"
  | "email"
  | "visualizador"
  | "visualizador-dashboards"
  | "import"
  | "settings"
  | "admin"
  | "cli"
  | "contracts-list"
  | "contratos-es"
  | "deep-search"
  | "researcher";

type NavItem = { id: AppView; label: string; icon: React.ReactNode; match?: AppView[]; keywords?: string; adminOnly?: boolean };

interface NavGroup {
  id: string;
  label: string;
  icon: React.ReactNode;
  items: NavItem[];
  /** Secções do menu de aplicações ficam abertas por omissão. */
  defaultOpen?: boolean;
}
interface AppNavProps {
  active: AppView;
  onNavigate: (view: AppView) => void;
  onBackToChat?: () => void;
}

/**
 * Menu de aplicações (como o dock): a barra lateral lista as aplicações da
 * plataforma, não a árvore de páginas de cada uma. As páginas internas de cada
 * aplicação vivem dentro da própria aplicação.
 *
 * `TOOL_APP_IDS` e `CRM_VIEW_IDS` vêm de `sidebarCatalog` — a classificação dos
 * módulos é única no projeto (a página de administração usa a mesma).
 */

/** Sub-ecrãs que pertencem a uma aplicação do menu (mantêm-na realçada). */
const APP_MATCH: Record<string, AppView[]> = {
  "contracts-search": ["contracts", "contracts-list"],
  "contracts-dashboard": ["companies-dashboard"],
  "entities-search": ["companies-search", "company-detail"],
  compare: ["entities-compare"],
  tickers: ["ticker-detail", "ticker-chart"],
  crm: [
    "crm-accounts",
    "crm-contacts",
    "crm-agenda",
    "crm-dashboard",
    // As vistas dos módulos da arquitetura (`crm-mod:<slug>`) mantêm o CRM realçado.
    ...CRM_SUITE_GROUPS.flatMap((group) => group.sections.map((section) => section.view as AppView)).filter(
      (view) => view !== "crm",
    ),
  ],
  scraper: ["scraper-templates", "scraper-execucoes", "scraper-pesquisa", "scraper-agenda"],
  social: ["social-canais", "social-execucoes", "social-modelos", "social-agenda", "social-estado"],
  search360: ["search360-dossie", "search360-projetos", "search360-grafo", "search360-biblioteca"],
  world: ["world-rede"],
  gleif: ["gleif-mapa", "gleif-ingestao"],
  office: ["office-dossies"],
  visualizador: ["visualizador-dashboards"],
  "iframe-pages": [],
};

function appItem(app: DockApp): NavItem {
  const Icon = app.icon;
  return {
    id: app.id as AppView,
    label: app.label,
    icon: <Icon size={16} />,
    match: APP_MATCH[app.id],
    keywords: app.hint,
    // A administração da solução só aparece a contas com papel `admin`.
    adminOnly: app.id === "admin",
  };
}

/**
 * Menu de CRM: uma secção por área funcional (ver `CRM_NAV_GROUPS`).
 * Identificadores das secções em `CRM_VIEW_IDS` (sidebarCatalog).
 */
/** Item de menu de uma secção do CRM (sem o prefixo «CRM · » do dock). */
function crmItem(view: string): NavItem | null {
  const app = DOCK_CATALOG.find((candidate) => candidate.id === view);
  if (!app) return null;
  const item = appItem(app);
  return {
    id: item.id,
    // O CRM **não** herda a lista de vistas de `APP_MATCH.crm`: o item «Pipeline»
    // casaria com todas as páginas do CRM e o grupo «Visão» abriria sempre.
    label: view === "crm" ? "Pipeline" : item.label.replace(/^CRM\s*\u00b7\s*/, ""),
    icon: item.icon,
    keywords: item.keywords,
    adminOnly: item.adminOnly,
  };
}

/**
 * O CRM na barra lateral: **uma secção por área funcional** (Visão, Analytics,
 * Relação com o cliente, Comercial e catálogo, Compras e fornecedores, Marketing,
 * Administração, Operação e auditoria, Conhecimento, Inteligência artificial),
 * com os módulos pela ordem da arquitetura.
 *
 * Sem `defaultOpen`: só a área onde o utilizador está abre automaticamente (e a
 * escolha de abrir/fechar fica memorizada), para o menu não mostrar 29 linhas de
 * CRM à vista.
 */
const CRM_NAV_GROUPS: NavGroup[] = CRM_SUITE_GROUPS.map((area) => {
  const AreaIcon = area.icon;
  return {
    id: `crm-${area.id}`,
    // A área «Visão» é a entrada do CRM: chama-se só «CRM».
    label: area.id === "visao" ? "CRM" : `CRM · ${area.label}`,
    icon: <AreaIcon size={14} />,
    items: area.sections
      .map((section) => crmItem(section.view))
      .filter((item): item is NavItem => Boolean(item)),
  };
});

/**
 * As aplicações no menu, **agrupadas por módulo** (`APP_MODULES`): Visão geral,
 * Contratos públicos, Contratos de Espanha, Empresas, Pessoas, Dados públicos,
 * Mercados e previsão, Investigação e IA, Conhecimento e conteúdos, Recolha de
 * dados e Redes sociais.
 *
 * O ícone de cada módulo é o da sua primeira aplicação (não obriga a mais um
 * mapa de ícones) e «Visão geral» é o único aberto por omissão — os restantes
 * abrem a pedido, ou sozinhos quando lá está a aplicação ativa.
 */
const APP_MODULE_GROUPS: NavGroup[] = APP_MODULES.map((module) => {
  const items = module.ids
    .map((id) => dockAppById(id))
    .filter((app): app is DockApp => Boolean(app))
    .map(appItem);
  const Icon = dockAppById(module.ids[0])?.icon ?? Sparkles;
  return {
    id: `app-${module.id}`,
    label: module.label,
    icon: <Icon size={14} />,
    defaultOpen: module.id === "visao-geral" ? true : undefined,
    items,
  };
}).filter((group) => group.items.length > 0);

/**
 * Grupo das ferramentas. O CRM e o grupo das páginas iframe são acrescentados em
 * `buildGroups()`.
 */
const TOOLS_GROUP: NavGroup = {
  id: "tools",
  label: "Ferramentas",
  icon: <SlidersHorizontal size={14} />,
  defaultOpen: true,
  items: [
    ...DOCK_CATALOG.filter((app) => TOOL_APP_IDS.includes(app.id) && app.id !== "iframe-pages").map(appItem),
    appItem(IFRAME_PAGES_APP),
  ],
};

/** Módulos do menu, na ordem em que aparecem na barra lateral. */
function baseGroups(): NavGroup[] {
  const known = new Set<string>(APP_MODULE_GROUPS.flatMap((group) => group.items.map((item) => String(item.id))));
  const rest = DOCK_CATALOG.filter(
    (app) => !known.has(app.id) && !TOOL_APP_IDS.includes(app.id) && !CRM_VIEW_IDS.includes(app.id),
  ).map(appItem);
  const groups = [...APP_MODULE_GROUPS];
  if (rest.length > 0) {
    // Aplicações novas, ainda sem módulo: mostram-se à parte em vez de desaparecer.
    groups.push({ id: "app-outras", label: "Outras aplicações", icon: <Sparkles size={14} />, items: rest });
  }
  return [...groups, ...CRM_NAV_GROUPS, TOOLS_GROUP];
}

/** Grupos do menu já com o CRM e as páginas iframe configuradas pelo utilizador. */
export function buildGroups(): NavGroup[] {
  const iframes = iframeDockApps();
  // Módulos de aplicações · CRM (por área) · Ferramentas · Páginas iframe.
  const groups = baseGroups();
  if (iframes.length === 0) return groups;
  return [
    ...groups,
    {
      id: "iframes",
      label: "Páginas iframe",
      icon: <Plus size={14} />,
      defaultOpen: true,
      items: iframes.map(appItem),
    },
  ];
}

/** Todos os itens de navegação, associados ao respetivo grupo. */
function allItems(role?: string | null) {
  const items = buildGroups().flatMap((group) => group.items.map((item) => ({ item, group })));
  const allowed = isAdminRole(role) ? items : items.filter(({ item }) => !item.adminOnly);
  // Módulos escondidos por perfil (definidos na página de administração).
  const hidden = hiddenModules();
  return allowed.filter(({ item }) => !hidden.has(item.id));
}

/** Papel `admin` (a área de administração é a única restrita). */
function isAdminRole(role?: string | null) {
  return (role ?? "member") === "admin";
}

/** Item de navegação (peça partilhada com o menu Iniciar). */
export type { NavItem, NavGroup };

/** Itens de navegação permitidos ao papel indicado. */
export function itemsFor(role?: string | null) {
  return allItems(role);
}

/** Grupos de navegação permitidos ao papel indicado (sem grupos vazios). */
export function groupsFor(role?: string | null): NavGroup[] {
  const groups = buildGroups();
  const allowed = isAdminRole(role)
    ? groups
    : groups
        .map((group) => ({ ...group, items: group.items.filter((item) => !item.adminOnly) }))
        .filter((group) => group.items.length > 0);
  // Módulos escondidos por perfil: o grupo desaparece quando fica sem itens.
  return allowed
    .map((group) => ({ ...group, items: dropHidden(group.items) }))
    .filter((group) => group.items.length > 0);
}

/** Remove acentos e baixa para minúsculas, para pesquisa tolerante. */
export function normalize(text: string) {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}
export function isActive(view: AppView, item: NavItem): boolean {
  if (view === item.id) return true;
  if (item.match?.includes(view)) return true;
  return false;
}

function isGroupActive(view: AppView, group: NavGroup): boolean {
  return group.items.some((item) => isActive(view, item));
}

/** Item de navegação correspondente à vista ativa (resolve sub-vistas). */
function resolveItem(view: AppView, items: { item: NavItem; group: NavGroup }[]): NavItem | undefined {
  return items.find(({ item }) => isActive(view, item))?.item;
}

export function AppNav({ active, onNavigate, onBackToChat }: AppNavProps) {
  /* As páginas iframe são configuráveis: a barra lateral volta a construir os
     grupos sempre que a lista muda. */
  const iframeRevision = useSyncExternalStore(subscribeIframePages, getIframeRevision, getIframeRevision);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { rail, hidden, setMode, toggleHidden, toggleRail } = useSidebar();
  const { width, setWidth, reset: resetWidth } = useSidebarWidth();
  const { openGroups, toggleGroup } = useNavGroups();
  const { windows: openWindows } = useWindows();
  const { windowMode } = useWindowMode();
  /** Aplicações com janela aberta (ponto nas linhas do menu). */
  const runningApps = useMemo(
    () => new Set(windowMode ? openWindows.map((item) => item.view) : [active]),
    [windowMode, openWindows, active],
  );
  const recent = useRecentViews();
  const { user, logout } = useAuth();
  /* Módulos escondidos por perfil: a barra volta a desenhar-se quando a matriz muda. */
  const sidebarAccess = useSidebarAccess();
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const [resizing, setResizing] = useState(false);

  /* Divisória arrastável: define a largura da barra (duplo clique repõe). */
  const startResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    setResizing(true);
  };
  const onResizeMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!resizing) return;
    const left = asideRef.current?.getBoundingClientRect().left ?? 0;
    setWidth(event.clientX - left);
  };
  const endResize = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!resizing) return;
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
    setResizing(false);
  };

  const context = useMemo(() => {
    // `iframeRevision` é lido no corpo para que o menu seja recalculado quando
    // as páginas iframe configuradas mudam (o oxlint não o vê como dependência).
    void iframeRevision;
    const allowed = itemsFor(user?.role);
    return { items: allowed, groups: groupsFor(user?.role) };
  }, [user?.role, iframeRevision, sidebarAccess]);

  /* Histórico de vistas (alimenta a secção «Recentes»). */
  useEffect(() => {
    const item = resolveItem(active, context.items);
    if (item) recordRecentView(item.id);
  }, [active, context.items]);

  const recentItems = useMemo(
    () =>
      recent
        .map((id) => context.items.find(({ item }) => item.id === id)?.item)
        .filter((item): item is NavItem => Boolean(item))
        .slice(0, 4),
    [recent, context.items],
  );

  const results = useMemo(() => {
    const term = normalize(query.trim());
    if (!term) return [];
    return context.items.filter(({ item, group }) =>
      `${normalize(item.label)} ${normalize(group.label)} ${normalize(item.keywords ?? "")}`.includes(term),
    );
  }, [context.items, query]);

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
    <nav className="flex h-full flex-col items-center gap-1 px-2 py-2.5" aria-label="Navegação principal (compacta)">
      <button
        onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
        title="IQ OS"
        aria-label="IQ OS"
        className="grid h-7 w-7 place-items-center rounded-[7px] bg-gradient-to-br from-teal-500 to-blue-500 text-white shadow-md shadow-primary/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <Sparkles size={14} />
      </button>

      <button
        onClick={() => setMode("expanded")}
        title="Expandir barra lateral"
        aria-label="Expandir barra lateral"
        className="mac-sidebar-rail-btn grid h-7 w-7 place-items-center rounded-[7px] text-muted-foreground/80 transition hover:bg-white/8 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <PanelLeftOpen size={15} />
      </button>

      <div className="my-1 h-px w-6 bg-white/10" />

      <div className="flex w-full flex-1 flex-col items-center gap-0.5 overflow-y-auto">
        {context.items.map(({ item }) => (
          <button
            key={item.id}
            onClick={() => handleClick(item.id)}
            title={item.label}
            aria-label={item.label}
            data-active={isActive(active, item)}
            className="mac-nav-row mac-nav-row-rail relative w-9 justify-center px-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
          >
            <span className="mac-nav-icon">{item.icon}</span>
            {runningApps.has(item.id) && (
              <span
                aria-hidden="true"
                className="absolute bottom-0.5 right-1 h-1 w-1 rounded-full bg-slate-300/80"
              />
            )}
          </button>
        ))}

        {recentItems.length > 0 && (
          <>
            <div className="my-1 h-px w-6 bg-white/10" />
            <span className="grid place-items-center py-1 text-muted-foreground/50" title="Recentes" aria-hidden="true">
              <History size={13} />
            </span>
            {recentItems.map((item) => (
              <button
                key={item.id}
                onClick={() => handleClick(item.id)}
                title={item.label}
                aria-label={item.label}
                data-active={isActive(active, item)}
                className="mac-nav-row mac-nav-row-rail w-9 justify-center px-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
              >
                <span className="mac-nav-icon">{item.icon}</span>
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
        {user ? <Avatar user={user} size={26} /> : null}
      </button>
      {accountMenu("fixed bottom-4 left-[76px] w-64")}
    </nav>
  );

  /* ------------------------------------------------- modo expandido/gaveta */
  const sidebarTop = (
    <div className="mac-sidebar-top flex h-11 shrink-0 items-center gap-1 px-2.5">
      <button
        onClick={() => (onBackToChat ? onBackToChat() : handleClick("chat"))}
        className="mac-sidebar-brand flex min-w-0 flex-1 items-center gap-2 rounded-[6px] px-1.5 py-1 text-left transition hover:bg-white/6 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-[6px] bg-gradient-to-br from-teal-500 to-blue-500 text-white shadow-sm shadow-primary/20">
          <Sparkles size={13} />
        </span>
        <span className="truncate text-[13px] font-semibold">IQ OS</span>
      </button>
      <button
        onClick={toggleRail}
        aria-label="Modo compacto (só ícones)"
        title="Modo compacto (só ícones)"
        className="mac-sidebar-btn hidden md:grid shrink-0 place-items-center h-6 w-6 rounded-[6px] text-muted-foreground/80 transition hover:bg-white/8 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <PanelLeft size={15} />
      </button>
      <button
        onClick={toggleHidden}
        aria-label="Ocultar barra lateral"
        title="Ocultar barra lateral (Ctrl+B)"
        className="mac-sidebar-btn hidden md:grid shrink-0 place-items-center h-6 w-6 rounded-[6px] text-muted-foreground/80 transition hover:bg-white/8 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
      >
        <ChevronLeft size={16} />
      </button>
    </div>
  );

  const navContent = (
    <nav className="flex h-full flex-col" aria-label="Navegação principal">
      {/* Topo da barra lateral (como a barra de ferramentas de uma janela macOS) */}
      {sidebarTop}

      <div className="shrink-0 px-2.5 pb-2" role="search">
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/80" />
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
            placeholder="Pesquisar ( / )"
            aria-label="Procurar na navegação"
            className="mac-sidebar-search h-7 w-full rounded-[6px] border border-white/8 bg-white/[0.055] pl-7 pr-6 text-[12.5px] outline-none transition placeholder:text-muted-foreground/80 focus:border-teal-300/40 focus:bg-white/[0.08]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Limpar pesquisa"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition hover:text-foreground"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div ref={listRef} className="flex-1 space-y-1 overflow-y-auto px-2 pb-2">
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
              <NavSection label="Recentes" icon={<History size={11} />}>
                {recentItems.map((item) => (
                  <NavButton
                    key={`recent-${item.id}`}
                    item={item}
                    active={isActive(active, item)}
                    onClick={() => handleClick(item.id)}
                  />
                ))}
              </NavSection>
            )}

            {context.groups.map((group) => {
              const groupActive = isGroupActive(active, group);
              const expanded = openGroups[group.id] ?? group.defaultOpen ?? groupActive;
              return (
                <NavSection
                  key={group.id}
                  label={group.label}
                  icon={group.icon}
                  expanded={expanded}
                  onToggle={() => toggleGroup(group.id, groupActive)}
                >
                  {group.items.map((item) => (
                    <NavButton
                      key={item.id}
                      item={item}
                      active={isActive(active, item)}
                      onClick={() => handleClick(item.id)}
                    />
                  ))}
                </NavSection>
              );
            })}
          </>
        )}
      </div>

      <div className="relative shrink-0 px-2 pb-2 pt-1.5">
        <div className="mac-sidebar-sep mb-1.5 h-px bg-white/8" />
        <button
          type="button"
          onClick={() => setUserMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={userMenuOpen}
          className="mac-sidebar-account flex w-full items-center gap-2 rounded-[6px] px-1.5 py-1.5 text-left transition hover:bg-white/6 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          {user ? <Avatar user={user} size={26} /> : null}
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-[12.5px] font-medium">{user?.name ?? "Conta"}</span>
            <span className="block truncate text-[10.5px] text-muted-foreground">{user?.email ?? ""}</span>
          </span>
          <ChevronUp size={13} className={userMenuOpen ? "text-foreground" : "text-muted-foreground/70"} />
        </button>
        <p className="mt-1.5 px-1.5 text-[10px] leading-relaxed text-muted-foreground/60">
          Divisória arrastável · <kbd className="rounded border border-white/10 bg-white/5 px-1">Ctrl</kbd>+
          <kbd className="rounded border border-white/10 bg-white/5 px-1">B</kbd> oculta
        </p>
        {accountMenu("absolute bottom-full left-2 right-2 mb-2")}
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
          <span className="font-semibold text-sm">IQ OS</span>
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
          className="mac-sidebar-handle hidden md:flex fixed left-0 top-1/2 z-40 -translate-y-1/2 items-center rounded-r-2xl border border-l-0 border-white/10 bg-[#111318]/92 py-4 pl-1 pr-1.5 text-muted-foreground shadow-lg backdrop-blur-xl transition hover:pr-4 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <ChevronRight size={16} />
        </button>
      )}

      {/* Barra lateral (desktop) — material macOS, arrastável na divisória */}
      <aside
        ref={asideRef}
        aria-hidden={hidden || undefined}
        inert={hidden || undefined}
        style={hidden ? { borderWidth: 0 } : { width: rail ? SIDEBAR_RAIL_WIDTH : width }}
        className={[
          "relative hidden md:flex shrink-0 h-screen mac-sidebar flex-col overflow-hidden",
          resizing ? "select-none" : "transition-[width,opacity] duration-200 ease-out",
          hidden ? "w-0 opacity-0" : "opacity-100",
        ].join(" ")}
      >
        {!hidden && (
          <div
            className="mac-sidebar-resizer hidden md:block"
            data-dragging={resizing || undefined}
            role="separator"
            aria-orientation="vertical"
            aria-label="Redimensionar barra lateral"
            aria-valuemin={SIDEBAR_MIN_WIDTH}
            aria-valuemax={SIDEBAR_MAX_WIDTH}
            aria-valuenow={width}
            title="Arrastar para redimensionar · duplo clique repõe"
            onPointerDown={startResize}
            onPointerMove={onResizeMove}
            onPointerUp={endResize}
            onPointerCancel={endResize}
            onDoubleClick={resetWidth}
          />
        )}
        <div className="h-full w-full shrink-0">{rail ? railContent : navContent}</div>
      </aside>
    </>
  );
}

/* --------------------------------------------------------------- subpeças */

/** Item do menu de aplicações (estilo macOS: linha compacta com seleção em pílula). */
function NavButton({ item, active, onClick }: { item: NavItem; active: boolean; onClick: () => void }) {
  const { windowMode } = useWindowMode();
  const { windows } = useWindows();
  // Com janelas abertas, o ponto indica as aplicações em execução (como o dock).
  const running = windowMode
    ? windows.some((item2) => item2.view === item.id)
    : active;
  return (
    <button
      data-nav
      data-active={active}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={item.label}
      className="mac-nav-row focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
    >
      <span className="mac-nav-icon">{item.icon}</span>
      <span className="truncate">{item.label}</span>
      {running && (
        <span
          aria-hidden="true"
          className={[
            "ml-auto h-1 w-1 shrink-0 rounded-full",
            active ? "bg-white/90" : "bg-slate-400/70",
          ].join(" ")}
        />
      )}
    </button>
  );
}

/** Secção da barra lateral com título discreto e triângulo de divulgação. */
function NavSection({
  label,
  icon,
  expanded = true,
  onToggle,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  expanded?: boolean;
  onToggle?: () => void;
  children: React.ReactNode;
}) {
  const content = (
    <>
      <span className="mac-section-chevron grid place-items-center">
        {onToggle ? <ChevronDown size={11} /> : null}
      </span>
      {icon ? <span className="opacity-70">{icon}</span> : null}
      <span className="truncate">{label}</span>
    </>
  );

  return (
    <section className="mb-1.5">
      {onToggle ? (
        <button type="button" onClick={onToggle} aria-expanded={expanded} className="mac-section-title focus:outline-none">
          {content}
        </button>
      ) : (
        <p className="mac-section-title">{content}</p>
      )}
      {expanded && <div className="mt-0.5 space-y-0.5 pl-[19px]">{children}</div>}
    </section>
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
