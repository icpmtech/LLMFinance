/**
 * Browser do IQ OS.
 *
 * Estado (separadores, histórico, favoritos, motor de pesquisa) guardado no
 * `localStorage`, seguindo o mesmo padrão dos outros módulos de estado da
 * plataforma: cache em memória + `useSyncExternalStore` + evento próprio e
 * sincronização entre separadores pela `storage` event.
 *
 * Este módulo não depende de React para a lógica de URLs (`toUrl`, `isInternalUrl`,
 * `blocksFraming`) — a página só consome o que precisa.
 */
import { useCallback, useSyncExternalStore } from "react";

export type SearchEngine = "duckduckgo" | "google" | "bing" | "brave";

export type BrowserTab = {
  id: string;
  /** URL atual (vazio = página inicial). */
  url: string;
  title: string;
  /** Pilha de navegação do separador. */
  history: string[];
  /** Posição dentro da pilha. */
  index: number;
  /** Carregar URLs internos do IQ OS dentro do separador (opt-in). */
  embedInternal?: boolean;
};

export type Bookmark = { id: string; url: string; title: string; addedAt: string };
export type HistoryEntry = { url: string; title: string; visitedAt: string };

export type BrowserState = {
  tabs: BrowserTab[];
  activeId: string;
  bookmarks: Bookmark[];
  history: HistoryEntry[];
  engine: SearchEngine;
  /** Carregar a última sessão ao abrir (em vez da página inicial). */
  restoreSession: boolean;
  /** Sites para os quais o aviso "pode estar bloqueado" foi dispensado. */
  mutedHints: string[];
  /** Ler pelo proxy do servidor as páginas que recusam incorporação (predefinição: ligado). */
  proxyEnabled: boolean;
  /** Ler **todas** as páginas pelo proxy do servidor. */
  forceProxy: boolean;
};

const STORAGE_KEY = "finance-llm-browser:v1";
const CHANGE_EVENT = "finance-llm-browser-changed";
const MAX_HISTORY = 300;
const MAX_TABS = 12;

export const SEARCH_ENGINES: { id: SearchEngine; label: string; url: (query: string) => string }[] = [
  // O DuckDuckGo «lite» é HTML simples (sem JavaScript): é o único motor que
  // funciona de forma fiável quando a página é lida pelo proxy do servidor.
  { id: "duckduckgo", label: "DuckDuckGo", url: (query) => `https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}` },
  { id: "google", label: "Google", url: (query) => `https://www.google.com/search?q=${encodeURIComponent(query)}` },
  { id: "bing", label: "Bing", url: (query) => `https://www.bing.com/search?q=${encodeURIComponent(query)}` },
  { id: "brave", label: "Brave", url: (query) => `https://search.brave.com/search?q=${encodeURIComponent(query)}` },
];

/**
 * Endereço a pedir ao proxy do servidor (que lê a página sem os cabeçalhos que
 * impedem a incorporação). O `apiBase` é a origem da API do IQ OS.
 */
export function proxyUrl(apiBase: string, url: string): string {
  return `${alignApiHost(apiBase).replace(/\/$/, "")}/proxy?url=${encodeURIComponent(url)}`;
}

/** Alias de loopback (`localhost`, `127.0.0.1`, `::1`). */
function isLoopbackAlias(host: string): boolean {
  const value = host.replace(/^\[|\]$/g, "");
  return value === "localhost" || value === "127.0.0.1" || value === "::1";
}

/**
 * Alinha o host da API com o host da aplicação.
 *
 * Motivo: `localhost` e `127.0.0.1` são a mesma máquina mas origens distintas, e
 * alguns browsers (incluindo o browser embutido do VS Code) abortam navegações
 * de `iframe` entre esses dois nomes. Como o conteúdo do proxy é mostrado num
 * `iframe`, o pedido tem de usar o mesmo nome de host que a aplicação.
 */
export function alignApiHost(apiBase: string): string {
  if (typeof window === "undefined") return apiBase;
  try {
    const api = new URL(apiBase, window.location.origin);
    const app = window.location;
    if (isLoopbackAlias(api.hostname) && isLoopbackAlias(app.hostname) && api.hostname !== app.hostname) {
      api.hostname = app.hostname;
      return api.origin;
    }
    return apiBase;
  } catch {
    return apiBase;
  }
}

/**
 * Decide como carregar um endereço: pelo proxy do servidor (sites que recusam
 * incorporação, motores de pesquisa, ou quando o utilizador força) ou direto.
 */
export function useProxyFor(url: string, proxyEnabled: boolean, forceProxy: boolean): boolean {
  if (!url) return false;
  if (internalPath(url)) return false;
  if (forceProxy) return true;
  return proxyEnabled && blocksFraming(url);
}

/** Endereços que recusam ser mostrados em `iframe` (`X-Frame-Options` / CSP). */
const NO_FRAMES = [
  "google.com",
  "google.pt",
  "youtube.com",
  "github.com",
  "linkedin.com",
  "x.com",
  "twitter.com",
  "facebook.com",
  "instagram.com",
  "whatsapp.com",
  "amazon.com",
  "amazon.es",
  "netflix.com",
  "reddit.com",
  "wikipedia.org",
  "notion.so",
  "figma.com",
  "openai.com",
  "chatgpt.com",
  "bloomberg.com",
  "reuters.com",
  "ft.com",
  "wsj.com",
  "nytimes.com",
  "publico.pt",
  "observador.pt",
  "cmvm.pt",
  "ine.pt",
  "tradingeconomics.com",
  "investing.com",
  "zerohedge.com",
  "seekingalpha.com",
  // Confirmados por teste direto (X-Frame-Options/CSP em 2026-09): portais
  // oficiais e agregadores financeiros recusam quase todos a incorporação.
  "base.gov.pt",
  "euronext.com",
  "yahoo.com",
  "finance.yahoo.com",
  "marketwatch.com",
  "morningstar.com",
  "cnbc.com",
  "forbes.com",
  "economist.com",
  "bportugal.pt",
  "europa.eu",
  "ec.europa.eu",
  "eurostat.ec.europa.eu",
  "tradingview.com",
];

/**
 * Motores de pesquisa: todos recusam incorporação (`frame-ancestors`), pelo que
 * os resultados abrem sempre numa aba do sistema. Detetados à parte para a
 * interface explicar o motivo em vez de mostrar um quadro vazio.
 */
const SEARCH_HOSTS = [
  "duckduckgo.com",
  "html.duckduckgo.com",
  "google.com",
  "google.pt",
  "bing.com",
  "search.brave.com",
  "brave.com",
  "ecosia.org",
  "startpage.com",
  "qwant.com",
  "yandex.com",
  "mojeek.com",
];

/** Verdadeiro quando o endereço é a página de resultados de um motor de pesquisa. */
export function isSearchUrl(url: string): boolean {
  if (!url) return false;
  let host = "";
  try {
    host = new URL(url, "http://localhost").hostname.replace(/^www\./, "");
  } catch {
    return false;
  }
  return SEARCH_HOSTS.some((engine) => host === engine || host.endsWith(`.${engine}`));
}

/** Termo de pesquisa dentro de um URL de resultados (vazio se não houver). */
export function queryFromSearchUrl(url: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url, "http://localhost");
    return (parsed.searchParams.get("q") || parsed.searchParams.get("query") || "").trim();
  } catch {
    return "";
  }
}

/** Atalhos da página inicial (ordem = ordem no ecrã). */
export type QuickLink = { label: string; url: string; hint: string; internal?: string };

/** Rotas internas do IQ OS conhecidas: caminho → vista da aplicação. */
export const INTERNAL_ROUTES: Record<string, string> = {
  "/": "dashboard",
  "/dashboard": "dashboard",
  "/chat": "chat",
  "/empresas-iq": "empresas-iq",
  "/finder": "finder",
  "/compare": "compare",
  "/contratos/search": "contracts-search",
  "/contracts/search": "contracts-search",
  "/contracts/dashboard": "contracts-dashboard",
  "/contracts-list": "contracts-list",
  "/companies/search": "companies-search",
  "/entities/search": "entities-search",
  "/tickers": "tickers",
  "/grafico": "ticker-chart",
  "/forecast": "forecast",
  "/trading": "trading",
  "/rag": "rag",
  "/search": "search",
  "/elastic": "elastic",
  "/import": "import",
  "/settings": "settings",
  "/admin": "admin",
  "/cli": "cli",
};

/** Vista do IQ OS correspondente a um caminho interno (ou `null`). */
export function viewForPath(path: string): string | null {
  if (!path) return null;
  const clean = path.split("?")[0].split("#")[0].replace(/\/+$/, "") || "/";
  return INTERNAL_ROUTES[clean] ?? null;
}

export const QUICK_GROUPS: { id: string; label: string; links: QuickLink[] }[] = [
  {
    id: "plataforma",
    label: "Plataforma",
    links: [
      { label: "Dashboard", url: "/dashboard", hint: "Visão geral", internal: "dashboard" },
      { label: "EmpresasIQ", url: "/empresas-iq", hint: "Inteligência contratual", internal: "empresas-iq" },
      { label: "Contratos", url: "/contracts/search", hint: "Contratação pública", internal: "contracts-search" },
      { label: "Mercados", url: "/tickers", hint: "Tickers e ações", internal: "tickers" },
      { label: "Gráfico tempo real", url: "/grafico", hint: "TradingView", internal: "ticker-chart" },
      { label: "Administração", url: "/admin", hint: "Sistema e eventos", internal: "admin" },
    ],
  },
  {
    id: "mercados",
    label: "Mercados",
    links: [
      { label: "TradingView", url: "https://www.tradingview.com/markets/", hint: "Gráficos e cotações" },
      { label: "Yahoo Finance", url: "https://finance.yahoo.com/", hint: "Cotações e fundamentais" },
      { label: "Google Finance", url: "https://www.google.com/finance/", hint: "Índices e ações" },
      { label: "Euronext", url: "https://www.euronext.com/en/markets/lisbon", hint: "Bolsa de Lisboa" },
      { label: "Investing.com", url: "https://www.investing.com/", hint: "Mercados globais" },
      { label: "CoinMarketCap", url: "https://coinmarketcap.com/", hint: "Criptomoedas" },
    ],
  },
  {
    id: "fontes",
    label: "Fontes oficiais",
    links: [
      { label: "BASE.gov", url: "https://www.base.gov.pt/Base4/pt/", hint: "Contratos públicos" },
      { label: "CMVM", url: "https://www.cmvm.pt/pt/Paginas/homepage.aspx", hint: "Regulador do mercado" },
      { label: "INE", url: "https://www.ine.pt/", hint: "Estatísticas" },
      { label: "Banco de Portugal", url: "https://www.bportugal.pt/", hint: "Estatísticas e séries" },
      { label: "Eurostat", url: "https://ec.europa.eu/eurostat", hint: "Estatísticas europeias" },
      { label: "INPI", url: "https://www.inpi.pt/", hint: "Marcas e patentes" },
    ],
  },
];

/* ------------------------------------------------------------------ estado */

function newId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function blankTab(url = ""): BrowserTab {
  return { id: newId(), url, title: "", history: url ? [url] : [], index: url ? 0 : -1 };
}

function emptyState(): BrowserState {
  const tab = blankTab();
  return {
    tabs: [tab],
    activeId: tab.id,
    bookmarks: [],
    history: [],
    engine: "duckduckgo",
    restoreSession: true,
    mutedHints: [],
    proxyEnabled: true,
    forceProxy: false,
  };
}

function asTab(value: unknown): BrowserTab | null {
  const candidate = value as Partial<BrowserTab> | null;
  if (!candidate || typeof candidate.id !== "string") return null;
  const history = Array.isArray(candidate.history)
    ? candidate.history.filter((item): item is string => typeof item === "string").slice(-60)
    : [];
  const index = typeof candidate.index === "number" && Number.isFinite(candidate.index) ? candidate.index : history.length - 1;
  return {
    id: candidate.id,
    url: typeof candidate.url === "string" ? candidate.url : "",
    title: typeof candidate.title === "string" ? candidate.title : "",
    history,
    index: Math.min(Math.max(-1, index), history.length - 1),
    ...(candidate.embedInternal ? { embedInternal: true } : {}),
  };
}

function read(): BrowserState {
  if (typeof window === "undefined") return emptyState();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return emptyState();
    const parsed = JSON.parse(raw) as Partial<BrowserState> | null;
    const tabs = Array.isArray(parsed?.tabs)
      ? parsed!.tabs.map(asTab).filter((tab): tab is BrowserTab => tab !== null).slice(0, MAX_TABS)
      : [];
    if (tabs.length === 0) return emptyState();
    const activeId = tabs.some((tab) => tab.id === parsed?.activeId) ? parsed!.activeId! : tabs[0].id;
    const bookmarks = Array.isArray(parsed?.bookmarks)
      ? parsed!.bookmarks
          .map((item): Bookmark | null => {
            const candidate = item as Partial<Bookmark> | null;
            if (!candidate || typeof candidate.url !== "string") return null;
            return {
              id: typeof candidate.id === "string" ? candidate.id : newId(),
              url: candidate.url,
              title: typeof candidate.title === "string" && candidate.title ? candidate.title : siteLabel(candidate.url),
              addedAt: typeof candidate.addedAt === "string" ? candidate.addedAt : new Date().toISOString(),
            };
          })
          .filter((item): item is Bookmark => item !== null)
      : [];
    const history = Array.isArray(parsed?.history)
      ? parsed!.history
          .map((item): HistoryEntry | null => {
            const candidate = item as Partial<HistoryEntry> | null;
            if (!candidate || typeof candidate.url !== "string") return null;
            return {
              url: candidate.url,
              title: typeof candidate.title === "string" ? candidate.title : "",
              visitedAt: typeof candidate.visitedAt === "string" ? candidate.visitedAt : new Date().toISOString(),
            };
          })
          .filter((item): item is HistoryEntry => item !== null)
          .slice(0, MAX_HISTORY)
      : [];
    const engine = SEARCH_ENGINES.some((item) => item.id === parsed?.engine) ? (parsed!.engine as SearchEngine) : "duckduckgo";
    const mutedHints = Array.isArray(parsed?.mutedHints)
      ? parsed!.mutedHints.filter((item): item is string => typeof item === "string").slice(0, 100)
      : [];
    return {
      tabs,
      activeId,
      bookmarks,
      history,
      engine,
      restoreSession: parsed?.restoreSession !== false,
      mutedHints,
      proxyEnabled: parsed?.proxyEnabled !== false,
      forceProxy: parsed?.forceProxy === true,
    };
  } catch {
    return emptyState();
  }
}

let cache: BrowserState | null = null;
let sessionInitialised = false;
const listeners = new Set<() => void>();

function state(): BrowserState {
  if (!cache) cache = read();
  return cache;
}

function commit(next: BrowserState, persist = true) {
  cache = next;
  if (persist && typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Sem espaço/quota: o estado em memória continua válido.
    }
  }
  listeners.forEach((listener) => listener());
  if (persist && typeof window !== "undefined") {
    try {
      window.dispatchEvent(new Event(CHANGE_EVENT));
    } catch {
      // Evento indisponível: o estado local já foi atualizado.
    }
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key && event.key !== STORAGE_KEY) return;
    cache = null;
    listeners.forEach((listener) => listener());
  });
  window.addEventListener(CHANGE_EVENT, () => {
    cache = null;
    listeners.forEach((listener) => listener());
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/* -------------------------------------------------------------- utilitários */

/** Etiqueta de um endereço (domínio sem `www.`, ou caminho quando é interno). */
export function siteLabel(url: string): string {
  if (!url) return "Nova aba";
  try {
    const parsed = new URL(url, typeof window === "undefined" ? "http://localhost" : window.location.origin);
    const internal = typeof window !== "undefined" && parsed.origin === window.location.origin;
    if (internal) return parsed.pathname === "/" ? "IQ OS" : `IQ OS ${parsed.pathname}`;
    return parsed.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Caminho interno do IQ OS (mesma origem) ou `null`. */
export function internalPath(url: string): string | null {
  if (!url) return null;
  if (typeof window === "undefined") return null;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin !== window.location.origin) return null;
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return null;
  }
}

/** Host de um endereço (sem `www.`), ou string vazia. */
export function hostOf(url: string): string {
  if (!url) return "";
  try {
    return new URL(url, "http://localhost").hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Verdadeiro quando o site costuma recusar ser incorporado num `iframe`. */
export function blocksFraming(url: string): boolean {
  if (!url) return false;
  if (isSearchUrl(url)) return true;
  let host = "";
  try {
    host = new URL(url, "http://localhost").hostname.replace(/^www\./, "");
  } catch {
    return false;
  }
  return NO_FRAMES.some((blocked) => host === blocked || host.endsWith(`.${blocked}`));
}

/** Converte o que o utilizador escreveu na barra em URL (ou pesquisa). */
export function toUrl(input: string, engine: SearchEngine = "duckduckgo"): string {
  const value = input.trim();
  if (!value) return "";
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return value;
  if (value.startsWith("/")) return value; // rota interna do IQ OS
  if (/^(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(value)) return `http://${value}`;
  // Domínio (com ou sem caminho), sem espaços.
  if (!/\s/.test(value) && /^[^\s/]+\.[a-z]{2,}([/:?#].*)?$/i.test(value)) return `https://${value}`;
  const search = SEARCH_ENGINES.find((item) => item.id === engine) ?? SEARCH_ENGINES[0];
  return search.url(value);
}

/** Nome amigável do motor de pesquisa. */
export function engineLabel(engine: SearchEngine): string {
  return (SEARCH_ENGINES.find((item) => item.id === engine) ?? SEARCH_ENGINES[0]).label;
}

/* ----------------------------------------------------------------- ações */

function withTab(next: BrowserState, id: string, update: (tab: BrowserTab) => BrowserTab): BrowserState {
  return { ...next, tabs: next.tabs.map((tab) => (tab.id === id ? update(tab) : tab)) };
}

function pushHistory(state: BrowserState, url: string, title = ""): BrowserState {
  if (!url) return state;
  const entry: HistoryEntry = { url, title: title || siteLabel(url), visitedAt: new Date().toISOString() };
  const history = [entry, ...state.history.filter((item) => item.url !== url)].slice(0, MAX_HISTORY);
  return { ...state, history };
}

export const browserActions = {
  /** Abre um separador novo (e ativa-o). */
  addTab(url = "", activate = true): string {
    const current = state();
    if (current.tabs.length >= MAX_TABS) return current.activeId;
    const tab = blankTab(url);
    const next = { ...current, tabs: [...current.tabs, tab], activeId: activate ? tab.id : current.activeId };
    commit(url ? pushHistory(next, url) : next);
    return tab.id;
  },
  closeTab(id: string) {
    const current = state();
    if (current.tabs.length <= 1) {
      const tab = blankTab();
      commit({ ...current, tabs: [tab], activeId: tab.id });
      return;
    }
    const index = current.tabs.findIndex((tab) => tab.id === id);
    const tabs = current.tabs.filter((tab) => tab.id !== id);
    const activeId = current.activeId === id ? (tabs[Math.max(0, index - 1)] ?? tabs[0]).id : current.activeId;
    commit({ ...current, tabs, activeId });
  },
  activateTab(id: string) {
    const current = state();
    if (!current.tabs.some((tab) => tab.id === id)) return;
    commit({ ...current, activeId: id });
  },
  /** Navega no separador indicado (aceita URL, domínio, rota interna ou texto). */
  navigate(id: string, input: string, options: { embedInternal?: boolean } = {}) {
    const current = state();
    const tab = current.tabs.find((item) => item.id === id);
    if (!tab) return;
    const url = toUrl(input, current.engine);
    if (!url) return;
    const history = [...tab.history.slice(0, tab.index + 1), url].slice(-60);
    const next = withTab(current, id, (item) => ({
      ...item,
      url,
      title: siteLabel(url),
      history,
      index: history.length - 1,
      ...(options.embedInternal === undefined ? {} : { embedInternal: options.embedInternal }),
    }));
    commit(pushHistory(next, url));
  },
  back(id: string) {
    const current = state();
    const tab = current.tabs.find((item) => item.id === id);
    if (!tab || tab.index <= 0) return;
    const index = tab.index - 1;
    commit(withTab(current, id, (item) => ({ ...item, index, url: item.history[index], title: siteLabel(item.history[index]) })));
  },
  forward(id: string) {
    const current = state();
    const tab = current.tabs.find((item) => item.id === id);
    if (!tab || tab.index >= tab.history.length - 1) return;
    const index = tab.index + 1;
    commit(withTab(current, id, (item) => ({ ...item, index, url: item.history[index], title: siteLabel(item.history[index]) })));
  },
  home(id: string) {
    const current = state();
    commit(withTab(current, id, (item) => ({ ...item, url: "", index: -1 })));
  },
  setTitle(id: string, title: string) {
    const current = state();
    const tab = current.tabs.find((item) => item.id === id);
    if (!tab || !title || tab.title === title) return;
    commit(withTab(current, id, (item) => ({ ...item, title })), false);
  },
  setEmbedInternal(id: string, embed: boolean) {
    const current = state();
    commit(withTab(current, id, (item) => ({ ...item, embedInternal: embed })));
  },
  toggleBookmark(url: string, title?: string) {
    if (!url) return;
    const current = state();
    const existing = current.bookmarks.find((item) => item.url === url);
    if (existing) {
      commit({ ...current, bookmarks: current.bookmarks.filter((item) => item.id !== existing.id) });
      return;
    }
    const bookmark: Bookmark = { id: newId(), url, title: title || siteLabel(url), addedAt: new Date().toISOString() };
    commit({ ...current, bookmarks: [bookmark, ...current.bookmarks].slice(0, 200) });
  },
  removeBookmark(id: string) {
    const current = state();
    commit({ ...current, bookmarks: current.bookmarks.filter((item) => item.id !== id) });
  },
  clearHistory() {
    commit({ ...state(), history: [] });
  },
  removeHistory(url: string) {
    const current = state();
    commit({ ...current, history: current.history.filter((item) => item.url !== url) });
  },
  setEngine(engine: SearchEngine) {
    commit({ ...state(), engine });
  },
  setRestoreSession(restore: boolean) {
    commit({ ...state(), restoreSession: restore });
  },
  /** Não voltar a avisar que um site pode recusar incorporação. */
  muteHint(host: string) {
    if (!host) return;
    const current = state();
    if (current.mutedHints.includes(host)) return;
    commit({ ...current, mutedHints: [...current.mutedHints, host].slice(0, 100) });
  },
  /** Liga/desliga a leitura das páginas pelo proxy do servidor. */
  setProxyEnabled(enabled: boolean) {
    commit({ ...state(), proxyEnabled: enabled, ...(enabled ? {} : { forceProxy: false }) });
  },
  /** Lê todas as páginas pelo servidor (não só as que bloqueiam incorporação). */
  setForceProxy(enabled: boolean) {
    commit({ ...state(), forceProxy: enabled, ...(enabled ? { proxyEnabled: true } : {}) });
  },
  /** Repõe a sessão inicial (um separador vazio) mantendo favoritos e histórico. */
  resetSession() {
    const current = state();
    const tab = blankTab();
    commit({ ...current, tabs: [tab], activeId: tab.id });
  },
  /** Descarrega o estado (usado em testes e ao terminar sessão). */
  reload() {
    cache = null;
    listeners.forEach((listener) => listener());
  },
};

/**
 * Prepara a sessão do browser uma vez por carregamento da aplicação: quando o
 * utilizador pediu para não retomar separadores, começa numa aba limpa.
 */
export function initBrowserSession() {
  if (sessionInitialised) return;
  sessionInitialised = true;
  if (state().restoreSession) return;
  const current = state();
  const tab = blankTab();
  commit({ ...current, tabs: [tab], activeId: tab.id }, false);
}

export type BrowserController = ReturnType<typeof useBrowser>;

/** Estado + ações do browser (com subscrição React). */
export function useBrowser() {
  const current = useSyncExternalStore(subscribe, state, state);
  const active = current.tabs.find((tab) => tab.id === current.activeId) ?? current.tabs[0];
  const bookmarkUrls = new Set(current.bookmarks.map((item) => item.url));
  const isBookmarked = useCallback((url: string) => bookmarkUrls.has(url), [current.bookmarks]);
  return { ...current, active, actions: browserActions, isBookmarked, engine: current.engine };
}
