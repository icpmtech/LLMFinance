/**
 * Dock estilo macOS da plataforma IQ OS.
 *
 * O dock é uma barra de ícones fixa (em baixo, à esquerda ou à direita) com
 * ampliação ao passar o rato, etiquetas, indicadores de aplicações abertas e
 * arrumação/reordenação dos ícones.
 *
 * Toda a configuração (posição, tamanho, ampliação, auto-ocultar, ordem dos
 * ícones e ícones escondidos) vive no `localStorage`, partilhada entre
 * separadores, tal como o resto do estado do EmpresasIQ.
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  Briefcase,
  Building2,
  CalendarClock,
  CandlestickChart,
  Compass,
  Database,
  FileText,
  FolderOpen,
  FolderSearch,
  Gauge,
  GitCompare,
  Globe2,
  Gavel,
  Landmark,
  LayoutDashboard,
  Layers,
  Mail,
  Map as MapIcon,
  MessageCircle,
  MessageSquare,
  Network,
  PersonStanding,
  Play,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  Telescope,
  TerminalSquare,
  TrendingUp,
  Upload,
  Users,
  Microscope,
} from "lucide-react";
import { getIframePages, iframeDockApps, iframeToDockApp, subscribeIframePages } from "./iframePages";

export type DockPosition = "bottom" | "left" | "right";

export type DockApp = {
  /** Identificador da vista da aplicação (`AppView`). */
  id: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Gradiente do tile (classes Tailwind). */
  gradient: string;
  /** Cor do brilho/realce do tile, em `r,g,b`. */
  accent: string;
};

/** Catálogo de aplicações que podem entrar no dock. */
export const DOCK_CATALOG: DockApp[] = [
  {
    id: "chat",
    label: "Chat IA",
    hint: "Conversar com os modelos",
    icon: MessageSquare,
    gradient: "from-teal-300 via-teal-500 to-emerald-600",
    accent: "16,163,127",
  },
  {
    id: "empresas-iq",
    label: "EmpresasIQ",
    hint: "Inteligência contratual",
    icon: Network,
    gradient: "from-cyan-300 via-sky-500 to-blue-600",
    accent: "14,165,233",
  },
  {
    id: "pessoas-iq",
    label: "PessoasIQ",
    hint: "Pessoas, cargos e relações societárias",
    icon: PersonStanding,
    gradient: "from-pink-300 via-rose-500 to-red-600",
    accent: "244,63,94",
  },
  {
    id: "companies-global",
    label: "Empresas Global",
    hint: "Entidades e empresas de todo o sistema (PT + Espanha + CRM)",
    icon: Briefcase,
    gradient: "from-emerald-200 via-emerald-400 to-teal-600",
    accent: "16,185,129",
  },
  {
    id: "ontology",
    label: "Ontologia",
    hint: "Camada semântica: objetos, ligações e IA",
    icon: Boxes,
    gradient: "from-teal-200 via-cyan-500 to-indigo-700",
    accent: "20,184,166",
  },
  {
    id: "visualizador",
    label: "Visualizador",
    hint: "BI: analisar dados, criar métricas e dashboards",
    icon: BarChart3,
    gradient: "from-teal-200 via-cyan-500 to-indigo-600",
    accent: "20,184,166",
  },
  {
    id: "sentimento",
    label: "Sentimento",
    hint: "Análise de sentimento da recolha, notícias, dossiês e documentos",
    icon: BarChart3,
    gradient: "from-fuchsia-300 via-violet-500 to-indigo-600",
    accent: "139,92,246",
  },
  {
    id: "search360",
    label: "Pesquisa 360",
    hint: "Meta-modelo de pesquisa: plataforma, enciclopédia, dados abertos e IA",
    icon: Telescope,
    gradient: "from-sky-200 via-indigo-500 to-violet-700",
    accent: "99,102,241",
  },
  {
    id: "hermes",
    label: "Hermes",
    hint: "Assistente de investigação: perguntas com evidências citadas",
    icon: Compass,
    gradient: "from-violet-300 via-purple-500 to-fuchsia-600",
    accent: "168,85,247",
  },
  {
    id: "office",
    label: "Office",
    hint: "Ler e escrever conteúdos em Markdown: notas, relatórios e dossiês",
    icon: BookOpen,
    gradient: "from-teal-200 via-sky-500 to-indigo-700",
    accent: "14,165,233",
  },
  {
    id: "email",
    label: "Email",
    hint: "Caixa de correio: Gmail, Outlook, iCloud ou qualquer IMAP/SMTP",
    icon: Mail,
    gradient: "from-sky-200 via-teal-400 to-emerald-600",
    accent: "20,184,166",
  },
  {
    id: "crm",
    label: "CRM",
    hint: "Contas, contactos e pipeline comercial",
    icon: Target,
    gradient: "from-rose-300 via-rose-500 to-pink-600",
    accent: "244,63,94",
  },
  {
    id: "crm-accounts",
    label: "CRM · Contas",
    hint: "Contas e empresas do CRM",
    icon: Briefcase,
    gradient: "from-amber-200 via-amber-400 to-orange-600",
    accent: "245,158,11",
  },
  {
    id: "crm-contacts",
    label: "CRM · Contactos",
    hint: "Pessoas de contacto do CRM",
    icon: Users,
    gradient: "from-sky-200 via-sky-400 to-indigo-600",
    accent: "56,189,248",
  },
  {
    id: "crm-agenda",
    label: "CRM · Agenda",
    hint: "Compromissos e tarefas comerciais",
    icon: CalendarClock,
    gradient: "from-teal-200 via-teal-400 to-emerald-600",
    accent: "16,185,129",
  },
  {
    id: "crm-dashboard",
    label: "CRM · Relatórios",
    hint: "Indicadores do trabalho comercial",
    icon: Gauge,
    gradient: "from-violet-300 via-purple-500 to-indigo-700",
    accent: "167,139,250",
  },
  {
    id: "scraper",
    label: "Recolha",
    hint: "Recolher dados de sites (scraping) e agendar com cron",
    icon: Globe2,
    gradient: "from-amber-200 via-orange-500 to-rose-600",
    accent: "249,115,22",
  },
  {
    id: "scraper-templates",
    label: "Recolha · Templates",
    hint: "Definições prontas para jornais e sites de dados",
    icon: Layers,
    gradient: "from-orange-200 via-amber-500 to-yellow-600",
    accent: "245,158,11",
  },
  {
    id: "scraper-execucoes",
    label: "Recolha · Execuções",
    hint: "Histórico de recolhas e itens gravados",
    icon: Play,
    gradient: "from-emerald-200 via-emerald-500 to-teal-600",
    accent: "16,185,129",
  },
  {
    id: "scraper-pesquisa",
    label: "Recolha · Pesquisa",
    hint: "Pesquisar nos itens recolhidos",
    icon: Search,
    gradient: "from-sky-200 via-sky-500 to-blue-700",
    accent: "14,165,233",
  },
  {
    id: "scraper-agenda",
    label: "Recolha · Agenda",
    hint: "Jobs de cron e próximas recolhas",
    icon: CalendarClock,
    gradient: "from-violet-200 via-violet-500 to-indigo-700",
    accent: "139,92,246",
  },  {
    id: "social",
    label: "Pesquisa social",
    hint: "LinkedIn, TikTok, Reddit e Facebook: recolher, agendar e pesquisar",
    icon: MessageCircle,
    gradient: "from-sky-200 via-fuchsia-500 to-indigo-700",
    accent: "217,70,239",
  },
  {
    id: "social-canais",
    label: "Social · Canais",
    hint: "Definições de recolha por plataforma",
    icon: Globe2,
    gradient: "from-sky-200 via-cyan-500 to-blue-700",
    accent: "14,165,233",
  },
  {
    id: "social-execucoes",
    label: "Social · Execuções",
    hint: "Histórico das recolhas e publicações gravadas",
    icon: Play,
    gradient: "from-emerald-200 via-emerald-500 to-teal-600",
    accent: "16,185,129",
  },
  {
    id: "social-modelos",
    label: "Social · Modelos",
    hint: "Canais prontos a criar por plataforma",
    icon: Layers,
    gradient: "from-orange-200 via-amber-500 to-yellow-600",
    accent: "245,158,11",
  },
  {
    id: "social-agenda",
    label: "Social · Agenda",
    hint: "Cron das recolhas sociais e próximas execuções",
    icon: CalendarClock,
    gradient: "from-violet-200 via-violet-500 to-indigo-700",
    accent: "139,92,246",
  },
  {
    id: "social-estado",
    label: "Social · Estado",
    hint: "Ambiente, indexação e volumetria por plataforma",
    icon: Database,
    gradient: "from-slate-200 via-slate-400 to-slate-600",
    accent: "148,163,184",
  },  {
    id: "cire",
    label: "Insolvências",
    hint: "CIRE: publicidade do PER, PEAP, PEVE e da insolvência (CITIUS)",
    icon: Gavel,
    gradient: "from-emerald-200 via-teal-500 to-slate-700",
    accent: "16,185,129",
  },
  {
    id: "contribuintes",
    label: "Contribuintes",
    hint: "Todos os NIF/NIPC do sistema (contratos, empresas, CIRE, marcas, CRM) com cron",
    icon: Users,
    gradient: "from-lime-200 via-emerald-500 to-teal-700",
    accent: "132,204,22",
  },
  {
    id: "finder",
    label: "Finder",
    hint: "Explorar dados como ficheiros",
    icon: FolderSearch,
    gradient: "from-cyan-200 via-sky-400 to-blue-600",
    accent: "56,189,248",
  },
  {
    id: "dashboard",
    label: "Dashboard",
    hint: "Visão geral da plataforma",
    icon: LayoutDashboard,
    gradient: "from-indigo-300 via-indigo-500 to-violet-600",
    accent: "99,102,241",
  },
  {
    id: "pesquisa",
    label: "Pesquisa total",
    hint: "Estilo Google: recolha, contratos, empresas, marcas, notícias e mercado",
    icon: Search,
    gradient: "from-sky-200 via-indigo-500 to-fuchsia-600",
    accent: "99,102,241",
  },
  {
    id: "search",
    label: "Pesquisa Global",
    hint: "Procurar em todas as fontes",
    icon: Search,
    gradient: "from-slate-200 via-slate-400 to-slate-600",
    accent: "148,163,184",
  },
  {
    id: "browser",
    label: "Browser",
    hint: "Navegar na web dentro do IQ OS",
    icon: Globe2,
    gradient: "from-sky-200 via-cyan-500 to-blue-700",
    accent: "56,189,248",
  },
  {
    id: "contracts-search",
    label: "Contratos",
    hint: "Pesquisar contratos públicos",
    icon: FileText,
    gradient: "from-amber-200 via-amber-400 to-orange-500",
    accent: "245,158,11",
  },
  {
    id: "contracts-dashboard",
    label: "Análise de Contratos",
    hint: "Indicadores de contratação pública",
    icon: BarChart3,
    gradient: "from-orange-200 via-orange-400 to-rose-500",
    accent: "249,115,22",
  },
  {
    id: "contracts-map",
    label: "Mapa de Contratos",
    hint: "Contratos públicos de Portugal e Espanha no mapa",
    icon: MapIcon,
    gradient: "from-emerald-200 via-teal-400 to-sky-600",
    accent: "16,163,127",
  },
  {
    id: "contratos-es",
    label: "Contratos Espanha",
    hint: "Pesquisar contratos públicos de Espanha (PLACSP)",
    icon: Landmark,
    gradient: "from-yellow-200 via-amber-400 to-red-500",
    accent: "251,191,36",
  },
  {
    id: "contratos-es-dashboard",
    label: "Análise Espanha",
    hint: "Dashboard analítica dos contratos públicos de Espanha",
    icon: BarChart3,
    gradient: "from-orange-200 via-amber-400 to-rose-500",
    accent: "251,191,36",
  },
  {
    id: "entities-search",
    label: "Empresas",
    hint: "Diretório e fichas de empresas",
    icon: Building2,
    gradient: "from-emerald-200 via-emerald-400 to-teal-600",
    accent: "16,185,129",
  },
  {
    id: "entities-dashboard",
    label: "Empresas · Dashboard",
    hint: "Indicadores de empresas que contratam e são contratadas",
    icon: Building2,
    gradient: "from-emerald-200 via-teal-400 to-cyan-600",
    accent: "16,185,129",
  },
  {
    id: "entities-adjudicantes",
    label: "Adjudicantes",
    hint: "Dashboard das entidades que adjudicam contratos",
    icon: Landmark,
    gradient: "from-sky-200 via-blue-500 to-indigo-600",
    accent: "59,130,246",
  },
  {
    id: "entities-adjudicatarios",
    label: "Adjudicatários",
    hint: "Dashboard das entidades fornecedoras e adjudicatárias",
    icon: Briefcase,
    gradient: "from-amber-200 via-orange-400 to-rose-500",
    accent: "245,158,11",
  },
  {
    id: "entities-compare",
    label: "Comparar entidades",
    hint: "Comparar empresas, adjudicantes e adjudicatários lado a lado",
    icon: GitCompare,
    gradient: "from-violet-300 via-indigo-500 to-blue-600",
    accent: "129,140,248",
  },
  {
    id: "tickers",
    label: "Mercados",
    hint: "Tickers e ações",
    icon: TrendingUp,
    gradient: "from-rose-200 via-rose-400 to-pink-600",
    accent: "244,63,94",
  },
  {
    id: "ticker-chart",
    label: "Gráfico Tempo Real",
    hint: "Cotações ao segundo com TradingView",
    icon: CandlestickChart,
    gradient: "from-emerald-200 via-teal-500 to-cyan-700",
    accent: "16,185,129",
  },
  {
    id: "forecast",
    label: "Previsões",
    hint: "Modelos de previsão",
    icon: Sparkles,
    gradient: "from-fuchsia-300 via-purple-500 to-indigo-600",
    accent: "192,132,252",
  },
  {
    id: "trading",
    label: "Trading",
    hint: "Simulador de trading",
    icon: CandlestickChart,
    gradient: "from-lime-200 via-green-500 to-emerald-700",
    accent: "34,197,94",
  },
  {
    id: "researcher",
    label: "Investigador",
    hint: "Investigador de contratos públicos",
    icon: Microscope,
    gradient: "from-rose-200 via-pink-500 to-purple-700",
    accent: "236,72,153",
  },
  {
    id: "agents",
    label: "Agentes",
    hint: "Criar e executar agentes dinâmicos com LangGraph",
    icon: Bot,
    gradient: "from-violet-200 via-fuchsia-500 to-pink-600",
    accent: "217,70,239",
  },
  {
    id: "rag",
    label: "RAG",
    hint: "Documentos e recuperação aumentada",
    icon: FolderOpen,
    gradient: "from-sky-200 via-cyan-400 to-teal-500",
    accent: "34,211,238",
  },
  {
    id: "elastic",
    label: "Elasticsearch",
    hint: "Explorar índices e documentos",
    icon: Database,
    gradient: "from-yellow-200 via-yellow-400 to-amber-600",
    accent: "250,204,21",
  },
  {
    id: "import",
    label: "Importar",
    hint: "Carregar dados para a plataforma",
    icon: Upload,
    gradient: "from-zinc-200 via-zinc-400 to-zinc-600",
    accent: "161,161,170",
  },
  {
    id: "compare",
    label: "Comparar",
    hint: "Comparar entidades e contratos",
    icon: GitCompare,
    gradient: "from-violet-300 via-indigo-500 to-blue-600",
    accent: "129,140,248",
  },
  {
    id: "settings",
    label: "Definições",
    hint: "Conta, perfil e preferências",
    icon: Settings,
    gradient: "from-slate-300 via-slate-500 to-slate-700",
    accent: "148,163,184",
  },
  {
    id: "admin",
    label: "Administração",
    hint: "Sistema, utilizadores e eventos",
    icon: ShieldCheck,
    gradient: "from-slate-200 via-slate-400 to-slate-600",
    accent: "203,213,225",
  },
  {
    id: "cli",
    label: "Terminal",
    hint: "CLI da plataforma dentro da app",
    icon: TerminalSquare,
    gradient: "from-zinc-800 via-zinc-700 to-slate-900",
    accent: "113,113,122",
  },
];

/** Ícones visíveis por defeito (a ordem é a ordem no dock). */
const DEFAULT_ITEMS = [
  "finder",
  "chat",
  "browser",
  "search360",
  "office",
  "empresas-iq",
  "pessoas-iq",
  "crm",
  "dashboard",
  "search",
  "contracts-search",
  "contracts-dashboard",
  "entities-search",
  "tickers",
  "forecast",
  "trading",
  "rag",
  "cli",
  "settings",
];

/**
 * Ordem antiga (sem o Finder à frente). Serve apenas para saber se o dock de um
 * utilizador ainda está na ordem de fábrica e, nesse caso, promover o Finder a
 * primeiro ícone — como no macOS, onde o Finder é o primeiro da doca.
 */
const LEGACY_DEFAULT_ITEMS = [
  "chat",
  "empresas-iq",
  "dashboard",
  "search",
  "contracts-search",
  "contracts-dashboard",
  "entities-search",
  "tickers",
  "forecast",
  "trading",
  "rag",
  "cli",
  "settings",
];

/** Versão da ordem do dock (2 = Finder à frente). */
const ORDER_VERSION = 2;

/** Ícones fora do dock por defeito (disponíveis para adicionar). */
const DEFAULT_PARKED = ["iframe-pages", "elastic", "import", "compare", "contratos-es", "crm-accounts", "crm-contacts", "crm-agenda", "crm-dashboard", "scraper-templates", "scraper-execucoes", "scraper-pesquisa", "scraper-agenda", "social-canais", "social-execucoes", "social-modelos", "social-agenda", "social-estado"];

export type DockPrefs = {
  position: DockPosition;
  /** Lado do ícone em repouso, em px. */
  iconSize: number;
  magnification: boolean;
  /** Ampliação máxima do ícone sob o cursor (1 = sem ampliação). */
  magnify: number;
  /** Distância de influência da ampliação, em múltiplos do tamanho do ícone. */
  magnifySpread: number;
  autoHide: boolean;
  tooltips: boolean;
  indicators: boolean;
  /** Reflexo/brilho sob os ícones. */
  reflection: boolean;
  /** Miniaturas das janelas minimizadas no dock (como no macOS). */
  minimizedShelf: boolean;
  /**
   * Agrupar as aplicações que já não cabem no dock numa pasta «Mais».
   *
   * Quando o dock está cheio, em vez de deslizar, mostra os ícones que cabem
   * ao tamanho pedido e guarda o resto numa pasta que abre num painel.
   */
  overflow: boolean;
  /** Ícones visíveis, pela ordem apresentada. */
  items: string[];
  /** Ícones removidos do dock. */
  parked: string[];
  /** Versão da ordem do dock (migrações de arrumação). */
  version?: number;
};

const STORAGE_KEY = "finance-llm-dock:v1";
const CHANGE_EVENT = "finance-llm-dock-changed";

export const ICON_SIZE_RANGE = { min: 38, max: 84 } as const;
export const MAGNIFY_RANGE = { min: 1.15, max: 2.2 } as const;
export const SPREAD_RANGE = { min: 1, max: 4 } as const;

export const DEFAULT_DOCK_PREFS: DockPrefs = {
  position: "bottom",
  iconSize: 52,
  magnification: true,
  magnify: 1.75,
  magnifySpread: 2.2,
  autoHide: false,
  tooltips: true,
  indicators: true,
  reflection: true,
  minimizedShelf: true,
  overflow: true,
  items: DEFAULT_ITEMS,
  parked: DEFAULT_PARKED,
  version: ORDER_VERSION,
};

/** Aplicação para abrir a página de configuração de iframes. */
export const IFRAME_PAGES_APP: DockApp = {
  id: "iframe-pages",
  label: "Páginas iframe",
  hint: "Adicionar e configurar páginas externas",
  icon: Plus,
  gradient: "from-violet-300 via-purple-500 to-indigo-600",
  accent: "139,92,246",
};

/**
 * Configuração virtual do catálogo do dock: aplicações do sistema + páginas
 * iframe configuradas pelo utilizador. Não é uma constante exportada para evitar
 * que entradas dinâmicas fiquem desligadas após a validação do sanitize().
 */
function allDockApps(): DockApp[] {
  return [...DOCK_CATALOG, IFRAME_PAGES_APP, ...iframeDockApps()];
}

function allCatalogIds(): string[] {
  return allDockApps().map((app) => app.id);
}

/** Limita um número ao intervalo indicado. */
function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** Lê um número das preferências do dock, com valor por omissão e limites. */
function asNumber(value: unknown, fallback: number, min: number, max: number) {
  return typeof value === "number" && Number.isFinite(value) ? clamp(value, min, max) : fallback;
}

const CATALOG_IDS = allCatalogIds();

function asIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const entry of value) {
    if (typeof entry !== "string") continue;
    if (!allCatalogIds().includes(entry) || seen.has(entry)) continue;
    seen.add(entry);
    ids.push(entry);
  }
  return ids;
}

function sanitize(raw: Partial<DockPrefs> | null): DockPrefs {
  let items = asIds(raw?.items);
  const parked = asIds(raw?.parked).filter((id) => !items.includes(id));

  // Aplicações novas no catálogo entram automaticamente no dock, no fim,
  // exceto se o utilizador já as tiver removido; as que nascem «fora do dock»
  // ficam listadas nas preferências, prontas a adicionar.
  const known = new Set([...items, ...parked]);
  const newcomers = CATALOG_IDS.filter((id) => !known.has(id));
  const newVisible = newcomers.filter((id) => !DEFAULT_PARKED.includes(id));
  const newParked = newcomers.filter((id) => DEFAULT_PARKED.includes(id));

  /* Migração de ordem: o Finder é o primeiro ícone da doca (como no macOS).
     Só mexe em docks que ainda estejam na ordem de fábrica, para não desfazer
     arrumações feitas à mão. */
  const version = typeof raw?.version === "number" ? raw.version : 1;
  if (version < ORDER_VERSION && items.length > 0) {
    const rest = items.filter((id) => id !== "finder");
    const wasFactoryOrder =
      rest.length <= LEGACY_DEFAULT_ITEMS.length &&
      rest.every((id, index) => id === LEGACY_DEFAULT_ITEMS[index]);
    if (!items.includes("finder")) {
      items = ["finder", ...items];
    } else if (wasFactoryOrder && items[0] !== "finder") {
      items = ["finder", ...rest];
    }
  }

  return {
    position:
      raw?.position === "left" || raw?.position === "right" || raw?.position === "bottom"
        ? raw.position
        : DEFAULT_DOCK_PREFS.position,
    iconSize: Math.round(
      asNumber(raw?.iconSize, DEFAULT_DOCK_PREFS.iconSize, ICON_SIZE_RANGE.min, ICON_SIZE_RANGE.max)
    ),
    magnification: typeof raw?.magnification === "boolean" ? raw.magnification : DEFAULT_DOCK_PREFS.magnification,
    magnify: asNumber(raw?.magnify, DEFAULT_DOCK_PREFS.magnify, MAGNIFY_RANGE.min, MAGNIFY_RANGE.max),
    magnifySpread: asNumber(
      raw?.magnifySpread,
      DEFAULT_DOCK_PREFS.magnifySpread,
      SPREAD_RANGE.min,
      SPREAD_RANGE.max
    ),
    autoHide: typeof raw?.autoHide === "boolean" ? raw.autoHide : DEFAULT_DOCK_PREFS.autoHide,
    tooltips: typeof raw?.tooltips === "boolean" ? raw.tooltips : DEFAULT_DOCK_PREFS.tooltips,
    indicators: typeof raw?.indicators === "boolean" ? raw.indicators : DEFAULT_DOCK_PREFS.indicators,
    reflection: typeof raw?.reflection === "boolean" ? raw.reflection : DEFAULT_DOCK_PREFS.reflection,
    minimizedShelf: typeof raw?.minimizedShelf === "boolean" ? raw.minimizedShelf : DEFAULT_DOCK_PREFS.minimizedShelf,
    overflow: typeof raw?.overflow === "boolean" ? raw.overflow : DEFAULT_DOCK_PREFS.overflow,
    items: items.length ? [...items, ...newVisible] : DEFAULT_DOCK_PREFS.items,
    parked: [...parked, ...newParked],
    version: ORDER_VERSION,
  };
}

function read(): DockPrefs {
  if (typeof window === "undefined") return DEFAULT_DOCK_PREFS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_DOCK_PREFS;
    return sanitize(JSON.parse(raw) as Partial<DockPrefs> | null);
  } catch {
    return DEFAULT_DOCK_PREFS;
  }
}

let cache: DockPrefs = read();

function commit(next: DockPrefs) {
  cache = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Modo privado ou sem espaço: mantém-se apenas em memória.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function getDockPrefs(): DockPrefs {
  return cache;
}

export function updateDockPrefs(patch: Partial<DockPrefs>) {
  commit(sanitize({ ...cache, ...patch }));
}

export function resetDockPrefs() {
  commit({ ...DEFAULT_DOCK_PREFS });
}

/** Move um ícone do dock para outra posição. */
export function moveDockItem(from: number, to: number) {
  const items = [...cache.items];
  if (from < 0 || from >= items.length) return;
  const target = clamp(to, 0, items.length - 1);
  if (from === target) return;
  const [moved] = items.splice(from, 1);
  items.splice(target, 0, moved);
  commit({ ...cache, items });
}

/** Retira um ícone do dock (fica disponível para voltar a adicionar). */
export function parkDockItem(id: string) {
  if (!cache.items.includes(id)) return;
  commit({
    ...cache,
    items: cache.items.filter((item) => item !== id),
    parked: [...cache.parked, id],
  });
}

/** Devolve um ícone ao dock (no fim, ou numa posição concreta). */
export function unparkDockItem(id: string, index?: number) {
  if (cache.items.includes(id)) return;
  const items = [...cache.items];
  const position = typeof index === "number" ? clamp(index, 0, items.length) : items.length;
  items.splice(position, 0, id);
  commit({ ...cache, items, parked: cache.parked.filter((item) => item !== id) });
}

export function isDockItemVisible(id: string) {
  return cache.items.includes(id);
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== STORAGE_KEY) return;
    cache = read();
    onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Configuração do dock e operações, com persistência automática. */
export function useDock() {
  const prefs = useSyncExternalStore(subscribe, getDockPrefs, getDockPrefs);
  /* As páginas iframe entram no catálogo: o dock volta a resolver os ícones
     sempre que a lista de páginas configuradas muda. */
  const iframePages = useSyncExternalStore(subscribeIframePages, getIframePages, getIframePages);

  const apps = useMemo(
    () => [...DOCK_CATALOG, IFRAME_PAGES_APP, ...iframePages.filter((page) => page.enabled).map(iframeToDockApp)],
    [iframePages]
  );

  const visible = useMemo(
    () => prefs.items.map((id) => apps.find((app) => app.id === id)).filter((app): app is DockApp => Boolean(app)),
    [prefs.items, apps]
  );

  /* «Fora do dock»: ícones que o utilizador retirou + aplicações que ainda não
     conhece (inclui páginas iframe criadas depois da última arrumação). */
  const parked = useMemo(() => {
    const known = new Set([...prefs.items, ...prefs.parked]);
    const ids = [...prefs.parked, ...apps.filter((app) => !known.has(app.id)).map((app) => app.id)];
    return ids
      .map((id) => apps.find((app) => app.id === id))
      .filter((app): app is DockApp => Boolean(app));
  }, [prefs.items, prefs.parked, apps]);

  const iframe = useMemo(() => iframePages.filter((page) => page.enabled).map(iframeToDockApp), [iframePages]);

  const set = useCallback((patch: Partial<DockPrefs>) => updateDockPrefs(patch), []);

  const move = useCallback((from: number, to: number) => moveDockItem(from, to), []);
  const park = useCallback((id: string) => parkDockItem(id), []);
  const unpark = useCallback((id: string, index?: number) => unparkDockItem(id, index), []);
  const reset = useCallback(() => resetDockPrefs(), []);

  return { prefs, visible, parked, iframe, set, move, park, unpark, reset };
}

export function dockApp(id: string): DockApp | undefined {
  if (id === "iframe-pages") return IFRAME_PAGES_APP;
  return allDockApps().find((app) => app.id === id);
}

/** Subscreve tanto às preferências do dock como às páginas iframe dinâmicas. */
export function useDockWithIframes() {
  return useDock();
}

/**
 * Espaço a reservar no conteúdo para o dock não tapar o fim das páginas.
 * `bottom` aplica-se à área de conteúdo; `sides` à moldura exterior (para o
 * dock lateral não tapar a barra de navegação).
 */
export function useDockSpacer() {
  const prefs = useSyncExternalStore(subscribe, getDockPrefs, getDockPrefs);
  if (prefs.autoHide) return { bottom: "", sides: "" };
  if (prefs.position === "bottom") return { bottom: "pb-[112px]", sides: "" };
  if (prefs.position === "left") return { bottom: "", sides: "pl-[104px]" };
  return { bottom: "", sides: "pr-[104px]" };
}
