import { useState, useCallback, useEffect, useRef } from "react";
import { ChatLayout } from "./components/ChatLayout";
import { AppNav, type AppView as AppNavView } from "./components/AppNav";
import { Dock } from "./components/Dock";
import { WindowManager } from "./components/WindowManager";
import { useDockSpacer, updateDockPrefs, dockApp } from "./dock";
import { getSidebarMode, setSidebarHidden, setSidebarMode, setWindowMode, useSidebarShortcut, useWindowMode } from "./layout";
import { openWindow, closeWindow, restoreWindow, windowFor } from "./windows";
import { useAuth } from "./auth";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";
import CliPage from "./pages/CliPage";
import { FileText, Loader2, Sparkles } from "lucide-react";
import { DashboardPage } from "./pages/DashboardPage";
import { TickerDetailPage } from "./pages/TickerDetailPage";
import RealtimeChartPage from "./pages/RealtimeChartPage";
import BrowserPage from "./pages/BrowserPage";
import { InstallBanner } from "./components/InstallBanner";
import AdminPage from "./pages/AdminPage";
import { ForecastPage } from "./pages/ForecastPage";
import { TradingPage } from "./pages/TradingPage";
import { TickerPage } from "./pages/TickerPage";
import { RagPage } from "./pages/RagPage";
import { ElasticPage } from "./pages/ElasticPage";
import { GlobalSearchPage } from "./pages/GlobalSearchPage";
// import { ContractsPage } from "./pages/ContractsPage"; // página legada, mantida no código mas não usada
import { ContractsDashboardPage } from "./pages/ContractsDashboardPage";
import { ContractsSearchPage } from "./pages/ContractsSearchPage";
import { CompanyDirectoryPage } from "./pages/CompanyDirectoryPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import CompanyDashboardPage from "./pages/CompanyDashboardPage";
import EmpresasIQPage from "./pages/EmpresasIQPage";
import CrmPage, {
  CRM_SECTION_VIEWS,
  CrmAccountWindow,
  CrmRecordWindow,
  crmEditorTitle,
  crmRecordLabel,
  crmSectionForView,
  type CrmSection,
} from "./pages/CrmPage";
import type { CrmKind, CrmRecord } from "./crmApi";
import FinderPage from "./pages/FinderPage";
import CompareWindow from "./pages/CompareWindow";
import { ContractDetailWindow, EntityDetailWindow, QuickLookWindow } from "./components/DetailWindow";
import EntityContractsWindow from "./pages/EntityContractsWindow";
import type { FinderKind } from "./finder";
import { EntitiesSearchPage } from "./pages/EntitiesSearchPage";
import { ImportPage } from "./pages/ImportPage";
import { ContractsListPage } from "./pages/ContractsListPage";
import { sendChat } from "./sendChat";
import type { Message, ModelBackend } from "./types";

type AppView =
  | AppNavView
  | "chat"
  | "ticker-detail"
  | "ticker-chart"
  | "empresas-iq"
  | "crm"
  | "crm-accounts"
  | "crm-contacts"
  | "crm-agenda"
  | "crm-dashboard"
  | "contracts-list"
  | "settings"
  | "cli"
  | "browser"
  | "finder"
  | "compare"
  | "admin";
const COMPANY_DETAIL_KEY = "finance-llm-company-detail";
const TICKER_DETAIL_KEY = "finance-llm-ticker-detail";
/** Último modelo/fornecedor escolhido no chat. */
const BACKEND_KEY = "finance-llm-backend";

const STORAGE_KEY = "finance-llm-conversations";

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function makeMessage(role: Message["role"], content: string): Message {
  return {
    id: generateId(),
    role,
    content,
    timestamp: new Date().toISOString(),
  };
}

function titleFromText(text: string) {
  return text.length > 40 ? text.slice(0, 37) + "..." : text;
}

/** URL correspondente a uma vista (usado na navegação e nas janelas). */
function pathForView(view: string, company: string | null, ticker: string | null): string {
  if (view === "chat") return "/chat";
  if (view === "browser") return "/browser";
  if (view === "dashboard") return "/dashboard";
  if (view === "finder") return "/finder";
  if (view === "compare") return "/compare";
  if (view === "forecast") return "/forecast";
  if (view === "trading") return "/trading";
  if (view === "tickers" || view === "ticker-detail") return ticker ? `/tickers/${ticker}` : "/tickers";
  if (view === "ticker-chart") return ticker ? `/tickers/${ticker}/grafico` : "/grafico";
  if (view === "rag") return "/rag";
  if (view === "elastic") return "/elastic";
  if (view === "search") return "/search";
  if (view === "contracts-search" || view === "contracts") return "/contracts/search";
  if (view === "contracts-dashboard") return "/contracts/dashboard";
  if (view === "companies-search" || view === "companies") return "/companies/search";
  if (view === "entities-search") return "/entities/search";
  if (view === "companies-dashboard") return "/companies/dashboard";
  if (view === "import") return "/import";
  if (view === "settings") return "/settings";
  if (view === "admin") return "/admin";
  if (view === "cli") return "/cli";
  if (view === "empresas-iq") return "/empresas-iq";
  if (view === "crm") return "/crm";
  if (view === "crm-accounts") return "/crm/contas";
  if (view === "crm-contacts") return "/crm/contactos";
  if (view === "crm-agenda") return "/crm/agenda";
  if (view === "crm-dashboard") return "/crm/relatorios";
  if (view === "contracts-list") return "/contracts-list";
  if (view === "company-detail" && company) return `/companies/${company}`;
  return "/";
}

/** Janelas auxiliares (fichas, quick look, contratos da entidade): identificadas por prefixo. */
function isDetailView(view: string): boolean {
  return (
    view.startsWith("company-detail:") ||
    view.startsWith("contract-detail:") ||
    view.startsWith("quicklook:") ||
    view.startsWith("entity-contracts:") ||
    view.startsWith("crm-account:") ||
    view.startsWith("crm-edit:")
  );
}

/** Secção do CRM a partir do caminho do URL (ou `null`). */
function crmSectionFromPath(path: string): CrmSection | null {
  if (path === "/crm") return "pipeline";
  if (path === "/crm/contas") return "accounts";
  if (path === "/crm/contactos") return "contacts";
  if (path === "/crm/agenda") return "agenda";
  if (path === "/crm/relatorios") return "dashboard";
  return null;
}

/** Estimativa da área de trabalho (o gestor de janelas ajusta logo a seguir). */
function workspaceEstimate(): { width: number; height: number } {
  if (typeof window === "undefined") return { width: 1200, height: 800 };
  const mode = getSidebarMode();
  const sidebar = mode === "hidden" ? 0 : mode === "rail" ? 72 : 268;
  return {
    width: Math.max(360, window.innerWidth - sidebar),
    height: Math.max(240, window.innerHeight - 140),
  };
}

export default function App() {
  const { status: authStatus, user } = useAuth();
  const { windowMode } = useWindowMode();
  const [focusedWindowView, setFocusedWindowView] = useState<string | null>(null);
  const prefAppliedRef = useRef(false);
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [backend, setBackend] = useState<ModelBackend>(() => {
    if (typeof window === "undefined") return "gpt2";
    return window.localStorage.getItem(BACKEND_KEY) || "gpt2";
  });
  const changeBackend = useCallback((next: ModelBackend) => {
    setBackend(next);
    if (typeof window !== "undefined") window.localStorage.setItem(BACKEND_KEY, next);
  }, []);
  const [loading, setLoading] = useState(false);
  /** Última pesquisa pedida fora da app de pesquisa (ex.: pelo browser). */
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCompany, setSelectedCompany] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(COMPANY_DETAIL_KEY);
  });
  const [selectedTicker, setSelectedTicker] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(TICKER_DETAIL_KEY);
  });

  const [view, setView] = useState<AppView>(() => {
    if (typeof window === "undefined") return "dashboard";
    const path = window.location.pathname.replace(/\/$/, "");
    if (path === "/rag") return "rag";
    if (path === "/browser") return "browser";
    if (path === "/finder") return "finder";
    if (path === "/compare") return "compare";
    if (path === "/forecast") return "forecast";
    if (path === "/trading") return "trading";
    if (path === "/tickers") return "tickers";
    if (path === "/grafico" || path === "/chart") return "ticker-chart";
    if (path.startsWith("/tickers/")) {
      const [symbol, section] = path.replace("/tickers/", "").split("/");
      if (symbol) setSelectedTicker(symbol);
      return section === "grafico" ? "ticker-chart" : "ticker-detail";
    }
    if (path === "/elastic") return "elastic";
    if (path === "/search") return "search";
    if (path === "/contracts") return "contracts-search";
    if (path === "/contracts/search") return "contracts-search";
    if (path === "/contracts/dashboard") return "contracts-dashboard";
    if (path === "/companies") return "companies-search";
    if (path === "/companies/search") return "companies-search";
    if (path === "/entities" || path === "/entities/search" || path === "/empresas") return "entities-search";
    if (path === "/companies/dashboard") return "companies-dashboard";
    if (path === "/import") return "import";
    if (path === "/settings") return "settings";
    if (path === "/admin") return "admin";
    if (path === "/cli") return "cli";
    if (path === "/contracts-list" || path.startsWith("/contracts-list/")) return "contracts-list";
    if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) return "empresas-iq";
    {
      const crmSection = crmSectionFromPath(path);
      if (crmSection) return CRM_SECTION_VIEWS[crmSection] as AppView;
    }
    if (path.startsWith("/companies/") && !path.startsWith("/companies/search") && !path.startsWith("/companies/dashboard")) {
      const nif = path.replace("/companies/", "").split("/")[0];
      if (nif) setSelectedCompany(nif);
      return "company-detail";
    }
    if (path === "/" || path === "") {
      const saved = localStorage.getItem("finance-llm-view");
      return (saved as AppView) || "dashboard";
    }
    return "dashboard";
  });

  useEffect(() => {
    const onPop = () => {
      if (typeof window === "undefined") return;
      const path = window.location.pathname.replace(/\/$/, "");
      let next: AppView = "dashboard";
      if (path === "/chat") next = "chat";
      else if (path === "/finder") next = "finder";
      else if (path === "/compare") next = "compare";
      else if (path === "/dashboard") next = "dashboard";
      else if (path === "/forecast") next = "forecast";
      else if (path === "/trading") next = "trading";
      else if (path === "/tickers") next = "tickers";
      else if (path === "/grafico" || path === "/chart") next = "ticker-chart";
      else if (path.startsWith("/tickers/")) {
        const [symbol, section] = path.replace("/tickers/", "").split("/");
        if (symbol) setSelectedTicker(symbol);
        next = section === "grafico" ? "ticker-chart" : "ticker-detail";
      } else if (path === "/rag") next = "rag";      else if (path === "/browser") next = "browser";      else if (path === "/elastic") next = "elastic";
      else if (path === "/search") next = "search";
      else if (path === "/contracts" || path === "/contracts/search") next = "contracts-search";
      else if (path === "/contracts/dashboard") next = "contracts-dashboard";
      else if (path === "/companies" || path === "/companies/search") next = "companies-search";
      else if (path === "/entities" || path === "/entities/search" || path === "/empresas") next = "entities-search";
      else if (path === "/companies/dashboard") next = "companies-dashboard";
      else if (path === "/import") next = "import";
      else if (path === "/settings") next = "settings";
      else if (path === "/admin") next = "admin";
      else if (path === "/cli") next = "cli";
      else if (path === "/contracts-list" || path.startsWith("/contracts-list/")) next = "contracts-list";
      else if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) next = "empresas-iq";
      else if (crmSectionFromPath(path)) next = CRM_SECTION_VIEWS[crmSectionFromPath(path) as CrmSection] as AppView;
      else if (path.startsWith("/companies/")) {
        const nif = path.replace("/companies/", "").split("/")[0];
        if (nif) setSelectedCompany(nif);
        next = "company-detail";
      }
      setView(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (selectedCompany) {
      localStorage.setItem(COMPANY_DETAIL_KEY, selectedCompany);
    } else {
      localStorage.removeItem(COMPANY_DETAIL_KEY);
    }
    if (selectedTicker) {
      localStorage.setItem(TICKER_DETAIL_KEY, selectedTicker);
    } else {
      localStorage.removeItem(TICKER_DETAIL_KEY);
    }
  }, [selectedCompany, selectedTicker]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  }, [conversations]);

  useEffect(() => {
    localStorage.setItem("finance-llm-view", view);
  }, [view]);

  const ensureActiveConversation = useCallback(
    (text: string) => {
      if (activeId) return activeId;
      const newId = generateId();
      const newConv: Conversation = {
        id: newId,
        title: titleFromText(text),
        messages: [],
      };
      setConversations((prev) => [newConv, ...prev]);
      setActiveId(newId);
      return newId;
    },
    [activeId],
  );

  const updateConversation = useCallback((id: string, msgs: Message[]) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, messages: msgs } : c)),
    );
    setMessages(msgs);
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      const id = ensureActiveConversation(text);
      const userMsg = makeMessage("user", text);
      const currentMessages = [...messages, userMsg];
      updateConversation(id, currentMessages);
      setLoading(true);

      let assistantMsg = makeMessage("assistant", "");

      try {
        const result = await sendChat(currentMessages, backend);
        assistantMsg = {
          ...assistantMsg,
          content: result.message.content,
          sources: result.sources,
          tools: result.tools,
        };
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.id === assistantMsg.id) {
            return [...prev.slice(0, -1), assistantMsg];
          }
          return [...prev, assistantMsg];
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Erro desconhecido";
        assistantMsg = { ...assistantMsg, content: `❌ ${message}` };
        setMessages((prev) => [...prev, assistantMsg]);
      } finally {
        setLoading(false);
        updateConversation(id, [...currentMessages, assistantMsg]);
      }
    },
    [messages, backend, ensureActiveConversation, updateConversation],
  );

  const handleSelect = useCallback(
    (id: string) => {
      setActiveId(id);
      setMessages(conversations.find((c) => c.id === id)?.messages || []);
    },
    [conversations],
  );

  const handleNew = useCallback(() => {
    setActiveId(null);
    setMessages([]);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    },
    [activeId],
  );

  const setViewAndHistory = useCallback(
    (next: AppView) => {
      setView(next);
      // No modo janelas, navegar abre (ou foca) a janela da aplicação.
      if (windowMode && typeof window !== "undefined") {
        if (windowFor(next)) restoreWindow(next);
        else openWindow(next, workspaceEstimate());
      }
      const path = pathForView(next, selectedCompany, selectedTicker);
      if (typeof window !== "undefined" && window.location.pathname !== path) {
        window.history.pushState({}, "", path);
      }
    },
    [selectedCompany, selectedTicker, windowMode],
  );

  const handleSwitchView = (v: string) => {
    if (v === "tickers" || v === "tickers-old") {
      setViewAndHistory("tickers");
      return;
    }
    if (v === "ticker-detail") {
      if (!selectedTicker && typeof window !== "undefined") {
        const saved = localStorage.getItem(TICKER_DETAIL_KEY);
        setSelectedTicker(saved || "AAPL");
        setViewAndHistory("ticker-detail");
      } else {
        setViewAndHistory("ticker-detail");
      }
      return;
    }
    if (v === "search") {
      setViewAndHistory("search");
      return;
    }
    if (v === "trading") {
      setViewAndHistory("trading");
      return;
    }
    if (v === "contracts" || v === "contracts-search") {
      setViewAndHistory("contracts-search");
      return;
    }
    if (v === "contracts-dashboard") {
      setViewAndHistory("contracts-dashboard");
      return;
    }
    if (v === "companies" || v === "companies-search") {
      setViewAndHistory("companies-search");
      return;
    }
    if (v === "entities-search") {
      setViewAndHistory("entities-search");
      return;
    }
    if (v === "companies-dashboard") {
      setViewAndHistory("companies-dashboard");
      return;
    }
    if (v === "empresas-iq") {
      setViewAndHistory("empresas-iq");
      return;
    }
    if (v === "import") {
      setViewAndHistory("import");
      return;
    }
    setViewAndHistory(v as AppView);
  };

  const handleSelectTicker = (ticker: string) => {
    setSelectedTicker(ticker);
    setViewAndHistory("ticker-detail");
  };

  /** Pesquisa nos dados do IQ OS (usada pelo browser). */
  const handleGlobalSearch = (query: string) => {
    const value = (query || "").trim();
    if (!value) return;
    setSearchQuery(value);
    setViewAndHistory("search");
  };

  /** Abre a ficha de uma entidade do cadastro (EmpresasIQ). */
  const handleOpenCompany = (nif: string) => {
    if (!nif) return;
    setSelectedCompany(nif);
    setViewAndHistory("company-detail");
  };

  /* ------------------------------------------------- janelas do CRM (macOS) */

  /** Cada separador do CRM abre (ou foca) a janela da sua secção. */
  const openCrmSection = (section: CrmSection) => {
    setViewAndHistory(CRM_SECTION_VIEWS[section] as AppView);
  };

  /** Ficha da conta numa janela própria (`crm-account:<id>`). */
  const openCrmAccount = (account: { id: string; name?: string }) => {
    openWindow(`crm-account:${account.id}`, undefined, {
      title: account.name ? `Conta · ${account.name}` : "Conta",
      rect: { width: 880, height: 720 },
    });
  };

  /** Editor de um registo numa janela própria (`crm-edit:<kind>:<id|new>`). */
  const openCrmEditor = (kind: CrmKind, record: CrmRecord | null, defaults?: Record<string, unknown>) => {
    const id = (record as { id?: string } | null)?.id ?? "new";
    const stage = typeof defaults?.stage === "string" ? defaults.stage : "";
    const view = `crm-edit:${kind}:${id}${stage ? `:${stage}` : ""}`;
    const label = crmRecordLabel(record);
    openWindow(view, undefined, {
      title: [crmEditorTitle(kind, record), label].filter(Boolean).join(" · "),
      rect: { width: 780, height: 700 },
    });
  };

  const dockSpacer = useDockSpacer();
  useSidebarShortcut();

  // Ao ligar o modo janelas, a página atual passa a estar aberta numa janela
  // (para não ficar com a área de trabalho vazia).
  useEffect(() => {
    if (!windowMode) return;
    if (!windowFor(view)) openWindow(view, workspaceEstimate());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowMode]);

  // Aplica as preferências da conta quando a sessão abre (uma vez por login).
  useEffect(() => {
    if (authStatus !== "authenticated") {
      prefAppliedRef.current = false;
      return;
    }
    if (!user || prefAppliedRef.current) return;
    prefAppliedRef.current = true;
    const preferences = (user.preferences || {}) as Record<string, unknown>;
    if (typeof preferences.sidebar_hidden === "boolean") setSidebarHidden(preferences.sidebar_hidden);
    if (typeof preferences.window_mode === "boolean") {
      // Num ecrã pequeno (telemóvel) as janelas flutuantes são apertadas:
      // abre em modo página, mesmo que a conta prefira janelas.
      const compact = typeof window !== "undefined" && window.matchMedia("(max-width: 1023px)").matches;
      setWindowMode(compact ? false : preferences.window_mode);
    }
    const sidebarMode = preferences.sidebar_mode;
    if (sidebarMode === "expanded" || sidebarMode === "rail" || sidebarMode === "hidden") {
      setSidebarMode(sidebarMode);
    }
    const dockPosition = preferences.dock_position;
    if (dockPosition === "bottom" || dockPosition === "left" || dockPosition === "right") {
      updateDockPrefs({ position: dockPosition });
    }
    const defaultView = preferences.default_view;
    if (typeof defaultView === "string" && typeof window !== "undefined" && window.location.pathname === "/") {
      handleSwitchView(defaultView);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, user]);

  if (authStatus === "loading") {
    return (
      <div className="grid min-h-screen w-full place-items-center bg-background text-foreground">
        <div className="flex flex-col items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 to-blue-500 text-white shadow-lg shadow-teal-500/25">
            <Sparkles size={22} />
          </span>
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> A validar a sessão…
          </p>
        </div>
      </div>
    );
  }

  if (authStatus === "anonymous") {
    return <LoginPage />;
  }

  const renderView = (target: AppView) => {
    if (target === "finder") return <FinderPage />;
    if (target === "compare") return <CompareWindow />;
    if (target.startsWith("company-detail:")) {
      return <EntityDetailWindow nif={target.slice("company-detail:".length)} />;
    }
    if (target.startsWith("contract-detail:")) {
      return <ContractDetailWindow id={target.slice("contract-detail:".length)} />;
    }
    if (target.startsWith("quicklook:")) {
      const [, kind, ...rest] = target.split(":");
      return <QuickLookWindow kind={kind as FinderKind} id={rest.join(":")} />;
    }
    if (target.startsWith("entity-contracts:")) {
      return <EntityContractsWindow nif={target.slice("entity-contracts:".length)} />;
    }
    if (target === "dashboard") return <DashboardPage onSwitchView={handleSwitchView} onSelectTicker={handleSelectTicker} />;
    if (target === "empresas-iq") return <EmpresasIQPage />;
    if (crmSectionForView(target)) {
      const section = crmSectionForView(target) as CrmSection;
      return (
        <CrmPage
          section={section}
          onSectionChange={windowMode ? openCrmSection : undefined}
          onOpenAccount={windowMode ? openCrmAccount : undefined}
          onEditRecord={windowMode ? openCrmEditor : undefined}
          onOpenCompany={handleOpenCompany}
        />
      );
    }
    if (target.startsWith("crm-account:")) {
      return (
        <CrmAccountWindow
          id={target.slice("crm-account:".length)}
          onOpenCompany={handleOpenCompany}
          onEdit={windowMode ? (account) => openCrmEditor("accounts", account) : undefined}
        />
      );
    }
    if (target.startsWith("crm-edit:")) {
      const [, kind, idPart, stage] = target.split(":");
      return (
        <CrmRecordWindow
          kind={kind as CrmKind}
          id={idPart || "new"}
          defaults={stage ? { stage } : undefined}
          onClose={() => closeWindow(target)}
          onSaved={() => closeWindow(target)}
        />
      );
    }
    if (target === "ticker-detail" && selectedTicker) {
      return (
        <TickerDetailPage
          ticker={selectedTicker}
          onBack={() => setViewAndHistory("tickers")}
          onSwitchView={handleSwitchView}
        />
      );
    }
    if (target === "forecast") return <ForecastPage />;
    if (target === "ticker-chart") return <RealtimeChartPage initialTicker={selectedTicker ?? undefined} />;
    if (target === "browser") return <BrowserPage onOpenInternal={handleSwitchView} onGlobalSearch={handleGlobalSearch} />;
    if (target === "trading") return <TradingPage />;
    if (target === "tickers") return <TickerPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "rag") return <RagPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "elastic") return <ElasticPage />;
    if (target === "import") return <ImportPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "settings") return <SettingsPage />;
    if (target === "admin") return <AdminPage />;
    if (target === "cli") return <CliPage />;
    if (target === "contracts-list") return <ContractsListPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "search") {
      return (
        <GlobalSearchPage
          initialQuery={searchQuery}
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSelectTicker={handleSelectTicker}
        />
      );
    }
    if (target === "contracts-dashboard") {
      return (
        <ContractsDashboardPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchSearch={() => setViewAndHistory("contracts-search")}
        />
      );
    }
    if (target === "contracts-search" || view === "contracts") {
      return (
        <ContractsSearchPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchDashboard={() => setViewAndHistory("contracts-dashboard")}
        />
      );
    }
    if (target === "entities-search") {
      const handleSelectEntity = (nif: string | null) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      return (
        <EntitiesSearchPage
          onSelectCompany={handleSelectEntity}
          onSwitchDashboard={() => setViewAndHistory("companies-dashboard")}
        />
      );
    }
    if (target === "companies-search" || view === "companies") {
      const handleSelectCompany = (nif: string | null) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      return (
        <CompanyDirectoryPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchDashboard={() => setViewAndHistory("companies-dashboard")}
          onSelectCompany={handleSelectCompany}
        />
      );
    }
    if (target === "companies-dashboard") {
      const handleSelectCompany = (nif: string | null) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      return (
        <CompanyDashboardPage
          onSwitchView={() => setViewAndHistory("companies-search")}
          onSwitchSearch={() => setViewAndHistory("companies-search")}
          onSelectCompany={handleSelectCompany}
        />
      );
    }
    if (target === "company-detail" && selectedCompany) {
      return (
        <CompanyDetailPage
          nif={selectedCompany}
          onBack={() => setViewAndHistory("companies-search")}
          onSwitchDashboard={() => setViewAndHistory("companies-dashboard")}
        />
      );
    }
    return (
      <ChatLayout
        conversations={conversations}
        activeId={activeId}
        messages={messages}
        loading={loading}
        streaming={false}
        backend={backend}
        onSelectConversation={handleSelect}
        onNewConversation={handleNew}
        onDeleteConversation={handleDelete}
        onSend={handleSend}
        onBackendChange={changeBackend}
      />
    );
  };

  const renderContent = () => renderView(view);

  /**
   * Título e ícone de cada janela. Usa o catálogo do dock (mesma identidade
   * visual) e cai num genérico para vistas que não têm ícone próprio.
   */
  const labelFor = (target: string): { title: string; icon: React.ReactNode } => {
    // Janelas com título próprio (fichas, quick look).
    const custom = windowFor(target)?.title;
    if (custom) {
      return { title: custom, icon: <FileText size={13} /> };
    }
    const app = dockApp(target);
    if (app) {
      const Icon = app.icon;
      return { title: app.label, icon: <Icon size={13} /> };
    }
    const fallback: Record<string, string> = {
      "company-detail": "Ficha da Empresa",
      "ticker-detail": "Detalhe do Ticker",
      "ticker-chart": "Gráfico Tempo Real",
      "admin": "Administração",
      "companies-search": "Entidades (Contratos)",
      "companies-dashboard": "Dashboard de Empresas",
      "contracts-list": "Contratos",
    };
    return { title: fallback[target] ?? "IQ OS", icon: <Sparkles size={13} /> };
  };

  /** Abrir pelo dock: no modo janelas foca/restaura a existente, senão abre. */
  const handleDockOpen = (id: string) => {
    if (windowMode) {
      if (windowFor(id)) restoreWindow(id);
      else openWindow(id, workspaceEstimate());
      return;
    }
    handleSwitchView(id);
  };

  const renderDock = () =>
    view === "chat" && !windowMode ? null : (
      <Dock active={windowMode && focusedWindowView ? focusedWindowView : view} onOpen={(id) => handleDockOpen(id)} />
    );

  /* ------------------------------------------------- modo janelas (macOS) */
  if (windowMode) {
    return (
      <div className={["flex h-screen w-full overflow-hidden bg-background text-foreground", dockSpacer.sides].join(" ")}>
        <AppNav
          active={(focusedWindowView ?? view) as AppNavView}
          onNavigate={(next) => setViewAndHistory(next as AppView)}
          onBackToChat={() => setViewAndHistory("chat")}
        />
        {/* As janelas ficam em `fixed`/`absolute` dentro deste contentor: aplica-se
            um transform (no gestor) para que `position: fixed` das páginas fique
            confinado à própria janela. */}
        <main className="relative min-h-0 min-w-0 flex-1 pt-14 md:pt-0">
          <WindowManager
            renderView={(target) => renderView(target as AppView)}
            labelFor={labelFor}
            onActiveChange={(next) => {
              setFocusedWindowView(next);
              // Fichas e quick look são janelas auxiliares: não mexem no URL.
              if (!next || isDetailView(next)) return;
              // Mantém o URL sincronizado com a janela em foco, sem empilhar histórico.
              const path = pathForView(next as AppView, selectedCompany, selectedTicker);
              if (typeof window !== "undefined" && window.location.pathname !== path) {
                window.history.replaceState({}, "", path);
              }
            }}
          />
        </main>
        {renderDock()}
        <InstallBanner />
      </div>
    );
  }

  if (view === "chat") {
    return renderContent();
  }

  if (view === "empresas-iq") {
    return (
      <div className={["relative w-full bg-background text-foreground", dockSpacer.sides, dockSpacer.bottom].join(" ")}>
        {renderContent()}
        {renderDock()}
        <InstallBanner />
      </div>
    );
  }

  return (
    <div className={["min-h-screen w-full bg-background text-foreground flex", dockSpacer.sides].join(" ")}>
      <AppNav
        active={view as AppNavView}
        onNavigate={(next) => setViewAndHistory(next as AppView)}
        onBackToChat={() => setViewAndHistory("chat")}
      />
      <main className={["flex-1 min-w-0 min-h-screen overflow-y-auto pt-14 md:pt-0", dockSpacer.bottom].join(" ")}>
        {renderContent()}
      </main>
      {renderDock()}
      <InstallBanner />
    </div>
  );
}

