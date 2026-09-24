import { useState, useCallback, useEffect, useRef, useSyncExternalStore } from "react";
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
import { FileText, Loader2, Network, Sparkles, Users } from "lucide-react";
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
import { ContractsMapPage } from "./pages/ContractsMapPage";
import { ContractsSearchPage } from "./pages/ContractsSearchPage";
import { ContractsEsSearchPage } from "./pages/ContractsEsSearchPage";
import { ContractsEsDashboardPage } from "./pages/ContractsEsDashboardPage";
import { CompanyDirectoryPage } from "./pages/CompanyDirectoryPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import CompanyDashboardPage from "./pages/CompanyDashboardPage";
import EntityDashboardPage from "./pages/EntityDashboardPage";
import EntityComparePage from "./pages/EntityComparePage";
import EmpresasIQPage from "./pages/EmpresasIQPage";
import PessoasIQPage from "./pages/PessoasIQPage";
import { PessoasGraphWindow } from "./pages/PessoasGraphWindow";
import { parseGraphWindowView } from "./components/people/peopleKit";
import CompaniesGlobalPage from "./pages/CompaniesGlobalPage";
import OntologyPage from "./pages/OntologyPage";
import VisualizadorPage from "./pages/VisualizadorPage";
import VisualizadorDashboardsPage from "./pages/VisualizadorDashboardsPage";
import HermesPage from "./pages/HermesPage";
import ResearcherPage from "./pages/ResearcherPage";
import DynamicAgentsPage from "./pages/DynamicAgentsPage";
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
import ScraperPage, {
  SCRAPER_SECTION_VIEWS,
  scraperSectionForView,
  type ScraperSection,
} from "./pages/ScraperPage";
import SocialPage, {
  SOCIAL_SECTION_VIEWS,
  socialSectionForView,
  type SocialSection,
} from "./pages/SocialPage";
import UnifiedSearchPage from "./pages/UnifiedSearchPage";
import SentimentPage from "./pages/SentimentPage";
import CirePage from "./pages/CirePage";
import ContribuintesPage from "./pages/ContribuintesPage";
import Search360Page, {
  SEARCH360_SECTION_VIEWS,
  search360SectionForView,
  type Search360Section,
} from "./pages/Search360Page";
import OfficePage, {
  OFFICE_SECTION_VIEWS,
  officeSectionForView,
  type OfficeSection,
} from "./pages/OfficePage";
import FinderPage from "./pages/FinderPage";
import EmailPage from "./pages/EmailPage";
import CompareWindow from "./pages/CompareWindow";
import { ContractDetailWindow, EntityDetailWindow, QuickLookWindow } from "./components/DetailWindow";
import EntityContractsWindow from "./pages/EntityContractsWindow";
import type { FinderKind } from "./finder";
import { EntitiesSearchPage } from "./pages/EntitiesSearchPage";
import { ImportPage } from "./pages/ImportPage";
import { ContractsListPage } from "./pages/ContractsListPage";
import { RegionDetailWindow } from "./pages/RegionDetailWindow";
import IframePage from "./pages/IframePage";
import IframePagesPage from "./pages/IframePagesPage";
import {
  getIframeRevision,
  iframeDockApps,
  iframeIdFromView,
  iframePathFor,
  iframeViewFor,
  iframeViewFromPath,
  isIframeView,
  subscribeIframePages,
} from "./iframePages";
import { sendChat } from "./sendChat";
import type { EntityRole, Message, ModelBackend } from "./types";

type AppView =
  | AppNavView
  | "chat"
  | "ticker-detail"
  | "ticker-chart"
  | "empresas-iq"
  | "pessoas-iq"
  | "pessoas-graph"
  | "ontology"
  | "crm"
  | "crm-accounts"
  | "crm-contacts"
  | "crm-agenda"
  | "crm-dashboard"
  | "contracts-list"
  | "contracts-map"
  | "region-detail"
  | "contratos-es"
  | "contratos-es-dashboard"
  | "companies-global"
  | "settings"
  | "cli"
  | "browser"
  | "finder"
  | "compare"
  | "admin"
  | "agents"
  | "iframe-pages";
const COMPANY_DETAIL_KEY = "finance-llm-company-detail";
const TICKER_DETAIL_KEY = "finance-llm-ticker-detail";
/** Região de contratos aberta a partir do mapa (janela `region-detail`). */
const REGION_DETAIL_KEY = "finance-llm-region-detail";

type RegionDetailTarget = { pais: "PT" | "ES"; code: string; label?: string; ano?: number | null };

/** Lê a região guardada (deep link `/contracts/region/...` ou última aberta). */
function readRegionDetailTarget(): RegionDetailTarget | null {
  if (typeof window === "undefined") return null;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(REGION_DETAIL_KEY) || "null") as RegionDetailTarget | null;
    if (parsed && (parsed.pais === "PT" || parsed.pais === "ES") && typeof parsed.code === "string") {
      return parsed;
    }
  } catch {
    /* sem região guardada */
  }
  return null;
}
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
function pathForView(
  view: string,
  company: string | null,
  ticker: string | null,
  region: RegionDetailTarget | null = null,
): string {
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
  if (view === "contratos-es") return "/contratos-es";
  if (view === "contratos-es-dashboard") return "/contratos-es/dashboard";
  if (view === "companies-global") return "/empresas-global";
  if (view === "contracts-dashboard") return "/contracts/dashboard";
  if (view === "contracts-map") return "/contracts/map";
  if (view === "region-detail") {
    return region ? `/contracts/region/${region.pais}/${encodeURIComponent(region.code)}` : "/contracts/map";
  }
  if (view === "companies-search" || view === "companies") return "/companies/search";
  if (view === "entities-search") return "/entities/search";
  if (view === "entities-dashboard") return "/entities/dashboard";
  if (view === "entities-adjudicantes") return "/adjudicantes";
  if (view === "entities-adjudicatarios") return "/adjudicatarios";
  if (view === "entities-compare") return "/entities/compare";
  if (view === "companies-dashboard") return "/companies/dashboard";
  if (view === "import") return "/import";
  if (view === "settings") return "/settings";
  if (view === "admin") return "/admin";
  if (view === "cli") return "/cli";
  if (view === "empresas-iq") return "/empresas-iq";
  if (view === "pessoas-iq") return "/pessoas-iq";
  if (view === "ontology") return "/ontology";
  if (view === "hermes") return "/hermes";
  if (view === "researcher") return "/researcher";
  if (view === "visualizador") return "/visualizador";
  if (view === "visualizador-dashboards") return "/visualizador/dashboards";
  if (view === "iframe-pages") return "/iframe-pages";
  const iframePath = iframePathFor(view);
  if (iframePath) return iframePath;
  if (view === "crm") return "/crm";
  if (view === "crm-accounts") return "/crm/contas";
  if (view === "crm-contacts") return "/crm/contactos";
  if (view === "crm-agenda") return "/crm/agenda";
  if (view === "crm-dashboard") return "/crm/relatorios";
  if (view === "scraper") return "/scraper";
  if (view === "scraper-templates") return "/scraper/modelos";
  if (view === "scraper-execucoes") return "/scraper/execucoes";
  if (view === "scraper-pesquisa") return "/scraper/pesquisa";
  if (view === "scraper-agenda") return "/scraper/agenda";
  if (view === "social") return "/social";
  if (view === "social-canais") return "/social/canais";
  if (view === "social-execucoes") return "/social/execucoes";
  if (view === "social-modelos") return "/social/modelos";
  if (view === "social-agenda") return "/social/agenda";
  if (view === "social-estado") return "/social/estado";
  if (view === "pesquisa") return "/pesquisa";
  if (view === "sentimento") return "/sentimento";
  if (view === "cire") return "/cire";
  if (view === "contribuintes") return "/contribuintes";
  if (view === "search360") return "/search360";
  if (view === "search360-dossie") return "/search360/dossie";
  if (view === "search360-projetos") return "/search360/projetos";
  if (view === "search360-grafo") return "/search360/grafo";
  if (view === "search360-biblioteca") return "/search360/biblioteca";
  if (view === "office") return "/office";
  if (view === "office-dossies") return "/office/dossies";
  if (view === "email") return "/email";
  if (view === "contracts-list") return "/contracts-list";
  if (view === "company-detail" && company) return `/companies/${company}`;
  return "/";
}

/** Janelas auxiliares (fichas, quick look, contratos da entidade, regiões): identificadas por prefixo. */
function isDetailView(view: string): boolean {
  return (
    view.startsWith("company-detail:") ||
    view.startsWith("contract-detail:") ||
    view.startsWith("person-detail:") ||
    view.startsWith("quicklook:") ||
    view.startsWith("entity-contracts:") ||
    view.startsWith("region-detail:") ||
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

/** Secção da recolha (scraping) a partir do caminho do URL (ou `null`). */
function scraperSectionFromPath(path: string): ScraperSection | null {
  if (path === "/scraper" || path === "/scraper/fontes") return "sources";
  // `/scraper/templates` é a rota de dados (JSON); a página é `/scraper/modelos`.
  if (path === "/scraper/modelos") return "templates";
  if (path === "/scraper/execucoes") return "runs";
  if (path === "/scraper/pesquisa") return "search";
  if (path === "/scraper/agenda") return "schedule";
  return null;
}

/** Secção da pesquisa social a partir do caminho do URL (ou `null`). */
function socialSectionFromPath(path: string): SocialSection | null {
  if (path === "/social" || path === "/social/pesquisa") return "pesquisa";
  if (path === "/social/canais") return "canais";
  if (path === "/social/execucoes") return "execucoes";
  if (path === "/social/modelos") return "modelos";
  if (path === "/social/agenda") return "agenda";
  if (path === "/social/estado") return "estado";
  return null;
}

/** Secção da Pesquisa 360 a partir do caminho do URL (ou `null`). */
function search360SectionFromPath(path: string): Search360Section | null {
  if (path === "/search360") return "busca";
  if (path === "/search360/dossie") return "dossie";
  if (path === "/search360/projetos") return "projetos";
  if (path === "/search360/grafo") return "grafo";
  if (path === "/search360/biblioteca") return "biblioteca";
  return null;
}

/** Secção do Office a partir do caminho do URL (ou `null`). */
function officeSectionFromPath(path: string): OfficeSection | null {
  if (path === "/office" || path === "/office/documentos") return "documentos";
  if (path === "/office/dossies") return "dossies";
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
  /* Re-renderiza quando as páginas iframe configuradas mudam (etiquetas,
     ícones e janelas dependem do catálogo dinâmico). */
  useSyncExternalStore(subscribeIframePages, getIframeRevision, getIframeRevision);
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
  /** Região cuja ficha está aberta (`/contracts/region/<pais>/<código>`). */
  const [regionDetail, setRegionDetail] = useState<RegionDetailTarget | null>(() => readRegionDetailTarget());

  const rememberRegionDetail = useCallback((target: RegionDetailTarget | null) => {
    setRegionDetail(target);
    if (typeof window === "undefined") return;
    if (target) window.localStorage.setItem(REGION_DETAIL_KEY, JSON.stringify(target));
    else window.localStorage.removeItem(REGION_DETAIL_KEY);
  }, []);

  const [view, setView] = useState<AppView>(() => {
    if (typeof window === "undefined") return "dashboard";
    const path = window.location.pathname.replace(/\/$/, "");
    if (path === "/chat") return "chat";
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
    if (path === "/pesquisa") return "pesquisa";
    if (path === "/sentimento") return "sentimento";
    if (path === "/cire" || path.startsWith("/cire/")) return "cire";
    if (path === "/contribuintes" || path.startsWith("/contribuintes/")) return "contribuintes";
    if (path === "/contracts") return "contracts-search";
    if (path === "/contracts/search") return "contracts-search";
    if (path === "/contratos-es") return "contratos-es";
    if (path === "/contratos-es/dashboard") return "contratos-es-dashboard";
    if (path === "/contracts/dashboard") return "contracts-dashboard";
    if (path === "/contracts/map") return "contracts-map";
    if (path.startsWith("/contracts/region/")) {
      const [, , , pais, ...rest] = path.split("/");
      const code = decodeURIComponent(rest.join("/"));
      if ((pais === "PT" || pais === "ES") && code) {
        setRegionDetail((prev) => ({ pais, code, label: prev?.label }));
        return "region-detail";
      }
    }
    if (path === "/companies") return "companies-search";
    if (path === "/companies/search") return "companies-search";
    if (path === "/entities" || path === "/entities/search" || path === "/empresas") return "entities-search";
    if (path === "/entities/dashboard" || path === "/empresas/dashboard") return "entities-dashboard";
    if (path === "/adjudicantes" || path === "/entidades/adjudicantes") return "entities-adjudicantes";
    if (path === "/adjudicatarios" || path === "/entidades/adjudicatarios") return "entities-adjudicatarios";
    if (path === "/entities/compare" || path === "/empresas/comparar") return "entities-compare";
    if (path === "/companies/dashboard") return "companies-dashboard";
    if (path === "/import") return "import";
    if (path === "/settings") return "settings";
    if (path === "/admin") return "admin";
    if (path === "/cli") return "cli";
    if (path === "/contracts-list" || path.startsWith("/contracts-list/")) return "contracts-list";
    if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) return "empresas-iq";
    if (path === "/pessoas-iq" || path.startsWith("/pessoas-iq/")) return "pessoas-iq";
    if (path === "/empresas-global") return "companies-global";
    if (path === "/ontology" || path.startsWith("/ontology/")) return "ontology";
    if (path === "/hermes" || path.startsWith("/hermes/")) return "hermes";
    if (path === "/researcher" || path.startsWith("/researcher/")) return "researcher";
    if (path === "/visualizador") return "visualizador";
    if (path.startsWith("/visualizador/")) return "visualizador-dashboards";
    if (path === "/email" || path.startsWith("/email/")) return "email";
    if (path === "/iframe-pages") return "iframe-pages";
    const iframeView = iframeViewFromPath(path);
    if (iframeView) return iframeView as AppView;
    {
      const crmSection = crmSectionFromPath(path);
      if (crmSection) return CRM_SECTION_VIEWS[crmSection] as AppView;
    }
    {
      const scraperSection = scraperSectionFromPath(path);
      if (scraperSection) return SCRAPER_SECTION_VIEWS[scraperSection] as AppView;
      const socialSection = socialSectionFromPath(path);
      if (socialSection) return SOCIAL_SECTION_VIEWS[socialSection] as AppView;
      const search360Section = search360SectionFromPath(path);
      if (search360Section) return SEARCH360_SECTION_VIEWS[search360Section] as AppView;
      const officeSection = officeSectionFromPath(path);
      if (officeSection) return OFFICE_SECTION_VIEWS[officeSection] as AppView;
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
      else if (path === "/pesquisa") next = "pesquisa";
      else if (path === "/sentimento") next = "sentimento";
      else if (path === "/cire" || path.startsWith("/cire/")) next = "cire";
      else if (path === "/contribuintes" || path.startsWith("/contribuintes/")) next = "contribuintes";
      else if (path === "/contracts" || path === "/contracts/search") next = "contracts-search";
      else if (path === "/contratos-es") next = "contratos-es";
      else if (path === "/contratos-es/dashboard") next = "contratos-es-dashboard";
      else if (path === "/contracts/dashboard") next = "contracts-dashboard";
      else if (path === "/contracts/map") next = "contracts-map";
      else if (path === "/companies" || path === "/companies/search") next = "companies-search";
      else if (path === "/entities" || path === "/entities/search" || path === "/empresas") next = "entities-search";
      else if (path === "/entities/dashboard" || path === "/empresas/dashboard") next = "entities-dashboard";
      else if (path === "/adjudicantes" || path === "/entidades/adjudicantes") next = "entities-adjudicantes";
      else if (path === "/adjudicatarios" || path === "/entidades/adjudicatarios") next = "entities-adjudicatarios";
      else if (path === "/entities/compare" || path === "/empresas/comparar") next = "entities-compare";
      else if (path === "/companies/dashboard") next = "companies-dashboard";
      else if (path === "/import") next = "import";
      else if (path === "/settings") next = "settings";
      else if (path === "/admin") next = "admin";
      else if (path === "/cli") next = "cli";
      else if (path === "/contracts-list" || path.startsWith("/contracts-list/")) next = "contracts-list";
      else if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) next = "empresas-iq";
      else if (path === "/pessoas-iq" || path.startsWith("/pessoas-iq/")) next = "pessoas-iq";
      else if (path === "/empresas-global") next = "companies-global";
      else if (path === "/ontology" || path.startsWith("/ontology/")) next = "ontology";
      else if (path === "/hermes" || path.startsWith("/hermes/")) next = "hermes";
      else if (path === "/researcher" || path.startsWith("/researcher/")) next = "researcher";
      else if (path === "/visualizador") next = "visualizador";
      else if (path.startsWith("/visualizador/")) next = "visualizador-dashboards";
      else if (path === "/email" || path.startsWith("/email/")) next = "email";
      else if (path === "/iframe-pages") next = "iframe-pages";
      else if (iframeViewFromPath(path)) next = iframeViewFromPath(path) as AppView;
      else if (crmSectionFromPath(path)) next = CRM_SECTION_VIEWS[crmSectionFromPath(path) as CrmSection] as AppView;
      else if (scraperSectionFromPath(path)) next = SCRAPER_SECTION_VIEWS[scraperSectionFromPath(path) as ScraperSection] as AppView;
      else if (socialSectionFromPath(path)) next = SOCIAL_SECTION_VIEWS[socialSectionFromPath(path) as SocialSection] as AppView;
      else if (search360SectionFromPath(path)) next = SEARCH360_SECTION_VIEWS[search360SectionFromPath(path) as Search360Section] as AppView;
      else if (officeSectionFromPath(path)) next = OFFICE_SECTION_VIEWS[officeSectionFromPath(path) as OfficeSection] as AppView;
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
          skill: result.skill ?? null,
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
      const path = pathForView(next, selectedCompany, selectedTicker, regionDetail);
      if (typeof window !== "undefined" && window.location.pathname !== path) {
        window.history.pushState({}, "", path);
      }
    },
    [regionDetail, selectedCompany, selectedTicker, windowMode],
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
    if (v === "contracts-map") {
      setViewAndHistory("contracts-map");
      return;
    }
    if (v === "contratos-es") {
      setViewAndHistory("contratos-es");
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
    if (v === "ontology") {
      setViewAndHistory("ontology");
      return;
    }
    if (v === "import") {
      setViewAndHistory("import");
      return;
    }
    if (v === "iframe-pages") {
      setViewAndHistory("iframe-pages");
      return;
    }
    if (isIframeView(v)) {
      const id = iframeIdFromView(v);
      if (id && iframeDockApps().some((app) => app.id === v)) {
        setViewAndHistory(v as AppView);
      }
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

  /** Abre a ficha de uma região (menu de contexto do mapa): janela ou página. */
  const openRegionDetail = useCallback(
    (pais: "PT" | "ES", code: string, label: string, ano: number | null) => {
      const view = `region-detail:${pais}:${code}`;
      rememberRegionDetail({ pais, code, label, ano });
      if (windowMode && typeof window !== "undefined") {
        openWindow(view, workspaceEstimate(), {
          title: `${label} · contratos`,
          rect: { width: 1180, height: 840 },
        });
        return;
      }
      setViewAndHistory("region-detail" as AppView);
      // O caminho é escrito aqui: `setViewAndHistory` usa o estado anterior desta
      // região (ainda vazio na primeira abertura) e apontaria para o mapa.
      if (typeof window !== "undefined") {
        window.history.pushState({}, "", `/contracts/region/${pais}/${encodeURIComponent(code)}`);
      }
    },
    [rememberRegionDetail, setViewAndHistory, windowMode],
  );

  /**
   * Abre uma vista ou ficha a partir de um resultado da Pesquisa total.
   * Em modo janelas abre (ou foca) a janela da aplicação; em modo página navega
   * para ela. As fichas levam o identificador no próprio nome da vista
   * (`company-detail:<nif>`, `contract-detail:<id>`), tal como as janelas do CRM.
   */
  const handleOpenSearchView = useCallback(
    (target: string, title?: string) => {
      if (target.startsWith("company-detail:")) {
        const nif = target.slice("company-detail:".length);
        if (nif) setSelectedCompany(nif);
      }
      if (windowMode) {
        if (windowFor(target)) restoreWindow(target);
        else openWindow(target, workspaceEstimate(), title ? { title } : undefined);
        return;
      }
      setViewAndHistory(target as AppView);
    },
    [windowMode, setViewAndHistory],
  );

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
    if (target.startsWith("person-detail:")) {
      return <PessoasIQPage nif={target.slice("person-detail:".length)} />;
    }
    // Grafo de pessoas numa janela própria (`pessoas-graph[:<lado>:<NIF>]`):
    // permite ter vários grafos abertos em paralelo, com pesquisa e filtros.
    if (target === "pessoas-graph" || target.startsWith("pessoas-graph:")) {
      return (
        <PessoasGraphWindow
          target={target.includes(":") ? target.slice("pessoas-graph:".length) : null}
        />
      );
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
    if (target.startsWith("region-detail:")) {
      const [, pais, ...rest] = target.split(":");
      const code = rest.join(":");
      return (
        <RegionDetailWindow
          pais={pais === "ES" ? "ES" : "PT"}
          code={code}
          ano={regionDetail?.ano ?? null}
          onOpenView={handleOpenSearchView}
        />
      );
    }
    if (target === "region-detail") {
      return regionDetail ? (
        <RegionDetailWindow
          pais={regionDetail.pais}
          code={regionDetail.code}
          ano={regionDetail.ano ?? null}
          onOpenView={handleOpenSearchView}
          onClose={() => {
            rememberRegionDetail(null);
            setViewAndHistory("contracts-map");
          }}
        />
      ) : (
        <ContractsMapPage onSwitchView={() => setViewAndHistory("contracts-search")} />
      );
    }
    if (target === "dashboard") return <DashboardPage onSwitchView={handleSwitchView} onSelectTicker={handleSelectTicker} />;
    if (target === "empresas-iq") return <EmpresasIQPage />;
    if (target === "pessoas-iq") return <PessoasIQPage />;
    if (target === "companies-global") return <CompaniesGlobalPage onOpenView={handleOpenSearchView} />;
    if (target === "ontology") return <OntologyPage />;
    if (target === "hermes") return <HermesPage />;
    if (target === "researcher") return <ResearcherPage />;
    if (target === "visualizador") return <VisualizadorPage onOpenDashboards={() => setViewAndHistory("visualizador-dashboards")} />;
    if (target === "visualizador-dashboards") return <VisualizadorDashboardsPage onOpenEditor={() => setViewAndHistory("visualizador")} />;
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
    if (scraperSectionForView(target)) {
      const section = scraperSectionForView(target) as ScraperSection;
      return (
        <ScraperPage
          section={section}
          onSectionChange={windowMode ? (next) => setViewAndHistory(SCRAPER_SECTION_VIEWS[next] as AppView) : undefined}
        />
      );
    }
    if (socialSectionForView(target)) {
      const section = socialSectionForView(target) as SocialSection;
      return (
        <SocialPage
          section={section}
          onSectionChange={windowMode ? (next) => setViewAndHistory(SOCIAL_SECTION_VIEWS[next] as AppView) : undefined}
        />
      );
    }
    const search360WindowSection = search360SectionForView(target);
    if (search360WindowSection) {
      return (
        <Search360Page
          section={search360WindowSection}
          onSectionChange={windowMode ? (next) => setViewAndHistory(SEARCH360_SECTION_VIEWS[next] as AppView) : undefined}
        />
      );
    }
    const officeWindowSection = officeSectionForView(target);
    if (officeWindowSection) {
      return (
        <OfficePage
          section={officeWindowSection}
          onSectionChange={windowMode ? (next) => setViewAndHistory(OFFICE_SECTION_VIEWS[next] as AppView) : undefined}
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
    if (target === "email") return <EmailPage />;
    if (target === "trading") return <TradingPage />;
    if (target === "tickers") return <TickerPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "rag") return <RagPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "agents") return <DynamicAgentsPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "elastic") return <ElasticPage />;
    if (target === "import") return <ImportPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "settings") return <SettingsPage />;
    if (target === "admin") return <AdminPage />;
    if (target === "cli") return <CliPage />;
    if (target === "contracts-list") return <ContractsListPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (target === "iframe-pages") {
      return <IframePagesPage onOpenIframe={(id) => setViewAndHistory(iframeViewFor(id) as AppView)} />;
    }
    if (isIframeView(target)) {
      return <IframePage view={target} onConfigure={() => setViewAndHistory("iframe-pages")} />;
    }
    if (target === "search") {
      return (
        <GlobalSearchPage
          initialQuery={searchQuery}
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSelectTicker={handleSelectTicker}
        />
      );
    }
    if (target === "pesquisa") {
      return <UnifiedSearchPage initialQuery={searchQuery} onOpenTicker={handleSelectTicker} onOpenView={handleOpenSearchView} />;
    }
    if (target === "sentimento") {
      return <SentimentPage onNavigate={(next) => setViewAndHistory(next as AppView)} />;
    }
    if (target === "cire") return <CirePage />;
    if (target === "contribuintes") return <ContribuintesPage />;
    if (target === "contracts-dashboard") {
      return (
        <ContractsDashboardPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchSearch={() => setViewAndHistory("contracts-search")}
        />
      );
    }
    if (target === "contracts-map") {
      return (
        <ContractsMapPage
          onSwitchView={() => setViewAndHistory("contracts-search")}
          onOpenRegionDetail={openRegionDetail}
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
    if (target === "contratos-es") {
      return (
        <ContractsEsSearchPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchDashboard={() => setViewAndHistory("contratos-es-dashboard")}
        />
      );
    }
    if (target === "contratos-es-dashboard") {
      return (
        <ContractsEsDashboardPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchSearch={() => setViewAndHistory("contratos-es")}
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
    if (
      target === "entities-dashboard" ||
      target === "entities-adjudicantes" ||
      target === "entities-adjudicatarios"
    ) {
      const role =
        target === "entities-adjudicantes" ? "adjudicante" : target === "entities-adjudicatarios" ? "adjudicatario" : "all";
      const openEntity = (nif: string) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      const switchRole = (next: EntityRole) => {
        const viewForRole: Record<EntityRole, AppView> = {
          all: "entities-dashboard",
          adjudicante: "entities-adjudicantes",
          adjudicatario: "entities-adjudicatarios",
        };
        setViewAndHistory(viewForRole[next]);
      };
      return (
        <EntityDashboardPage
          key={target}
          role={role}
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchRole={switchRole}
          onSelectEntity={openEntity}
          onOpenCompare={() => setViewAndHistory("entities-compare")}
        />
      );
    }
    if (target === "entities-compare") {
      return (
        <EntityComparePage
          onOpenEntity={(nif) => {
            if (!nif) return;
            setSelectedCompany(nif);
            setViewAndHistory("company-detail");
          }}
          onOpenDashboard={(role) =>
            setViewAndHistory(
              role === "adjudicante"
                ? "entities-adjudicantes"
                : role === "adjudicatario"
                  ? "entities-adjudicatarios"
                  : "entities-dashboard",
            )
          }
          onBack={() => setViewAndHistory("entities-dashboard")}
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
    // Ficha de pessoa (PessoasIQ) aberta como janela a partir do societário.
    if (target.startsWith("person-detail:")) {
      return { title: "Pessoas IQ", icon: <Users size={13} /> };
    }
    // Grafo de pessoas/cargos numa janela própria.
    if (target === "pessoas-graph" || target.startsWith("pessoas-graph:")) {
      const parsed = parseGraphWindowView(target.includes(":") ? target.slice("pessoas-graph:".length) : null);
      const suffix = parsed ? ` · ${parsed.nif}` : "";
      return { title: `Grafo${suffix}`, icon: <Network size={13} /> };
    }
    // Janelas com título próprio (fichas, quick look).
    const custom = windowFor(target)?.title;
    if (custom) {
      return { title: custom, icon: <FileText size={13} /> };
    }
    if (isIframeView(target)) {
      const id = iframeIdFromView(target);
      const page = iframeDockApps().find((app) => app.id === target);
      if (page) {
        const Icon = page.icon;
        return { title: page.label, icon: <Icon size={13} /> };
      }
      return { title: id ? `iframe · ${id}` : "Página iframe", icon: <FileText size={13} /> };
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

  const renderDock = () => (
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
    /* O Chat vive dentro da mesma moldura da plataforma: a barra lateral e a
       barra de tarefas ficam **sempre** visíveis, como em todas as páginas. */
    return (
      <div className={["flex h-screen w-full overflow-hidden bg-background text-foreground", dockSpacer.sides].join(" ")}>
        <AppNav
          active={view as AppNavView}
          onNavigate={(next) => setViewAndHistory(next as AppView)}
          onBackToChat={() => setViewAndHistory("chat")}
        />
        <main
          className={[
            "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-14 md:pt-0",
            dockSpacer.bottom,
          ].join(" ")}
        >
          {renderContent()}
        </main>
        {renderDock()}
        <InstallBanner />
      </div>
    );
  }

  if (view === "hermes" || view === "contracts-map") {
    /* Hermes é uma conversa e o mapa de contratos é um mapa: ambos ocupam a altura
       do ecrã (a lista/o painel rolam por dentro) em vez de fazer crescer a página
       — no mapa, o enquadramento da Península não deve empurrar o painel para baixo. */
    return (
      <div className={["flex h-screen w-full overflow-hidden bg-background text-foreground", dockSpacer.sides].join(" ")}>
        <AppNav
          active={view as AppNavView}
          onNavigate={(next) => setViewAndHistory(next as AppView)}
          onBackToChat={() => setViewAndHistory("chat")}
        />
        <main
          className={[
            "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden pt-14 md:pt-0",
            dockSpacer.bottom,
          ].join(" ")}
        >
          {renderContent()}
        </main>
        {renderDock()}
        <InstallBanner />
      </div>
    );
  }

  if (view === "empresas-iq" || view === "pessoas-iq") {
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

