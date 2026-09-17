/**
 * Gráfico de cotações em tempo real (TradingView).
 *
 * Nova aplicação «Gráfico Tempo Real» (`/chart`), que embebe o *Advanced Real-Time
 * Chart* da TradingView — velas, intervalos, indicadores, ferramentas de desenho e
 * alteração de símbolo. O símbolo da plataforma (ex.: `EDP`) é traduzido para o
 * formato da TradingView (`EURONEXT:EDP`) a partir da bolsa devolvida pela API,
 * e pode ser substituído manualmente (a escolha fica guardada em `localStorage`).
 *
 * O mesmo componente `TradingViewChart` é reutilizado no separador «Gráfico» da
 * ficha do ticker.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickChart,
  ExternalLink,
  Fullscreen,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { getTickerInfo, searchLocalTickers, searchYahooTickers } from "../api";
import { NativePriceChart } from "../components/NativePriceChart";
import type { TickerInfo } from "../types";

/* --------------------------------------------------- símbolo TradingView */

/** Bolsa da API (código yfinance) → prefixo de bolsa da TradingView. */
const EXCHANGE_PREFIX: Record<string, string> = {
  NMS: "NASDAQ",
  NGM: "NASDAQ",
  NCM: "NASDAQ",
  NAS: "NASDAQ",
  NASDAQ: "NASDAQ",
  NYQ: "NYSE",
  NYE: "NYSE",
  NYS: "NYSE",
  ASE: "AMEX",
  PCX: "NYSEARCA",
  BTT: "CBOE",
  LIS: "EURONEXT",
  PAR: "EURONEXT",
  AMS: "EURONEXT",
  BRU: "EURONEXT",
  LON: "LSE",
  LSE: "LSE",
  IOB: "LSE",
  GER: "XETR",
  XETRA: "XETR",
  FRA: "FWB",
  STU: "STU",
  BER: "BER",
  MUN: "MUN",
  HAM: "HAM",
  DUS: "DUS",
  MIL: "MIL",
  MCE: "BME",
  SWX: "SIX",
  VIE: "VIE",
  OSL: "OSL",
  STO: "OMXSTO",
  CPH: "OMXCOP",
  HEL: "OMXHEX",
  TOR: "TSX",
  VAN: "TSXV",
  SAO: "BMFBOVESPA",
  MEX: "BMV",
  SGO: "BCS",
  BUE: "BCBA",
  HKG: "HKEX",
  SHH: "SSE",
  SHZ: "SZSE",
  TYO: "TSE",
  JPX: "TSE",
  KSC: "KRX",
  TAI: "TPE",
  ASX: "ASX",
  NZE: "NZX",
  IST: "BIST",
  TLV: "TASE",
  JNB: "JSE",
};

/** Sufixo do ticker (ex.: `EDP.LS`) → prefixo de bolsa da TradingView. */
const SUFFIX_PREFIX: Record<string, string> = {
  LS: "EURONEXT",
  PA: "EURONEXT",
  AS: "EURONEXT",
  BR: "EURONEXT",
  DE: "XETR",
  F: "FWB",
  L: "LSE",
  IL: "LSE",
  MI: "MIL",
  MC: "BME",
  SW: "SIX",
  VX: "SIX",
  ST: "OMXSTO",
  CO: "OMXCOP",
  HE: "OMXHEX",
  OL: "OSL",
  VI: "VIE",
  TO: "TSX",
  V: "TSXV",
  HK: "HKEX",
  T: "TSE",
  AX: "ASX",
  NZ: "NZX",
  IS: "BIST",
  SA: "BMFBOVESPA",
  MX: "BMV",
  KS: "KRX",
  TW: "TPE",
  SS: "SSE",
  SZ: "SZSE",
  SI: "SGX",
  JO: "JSE",
};

/**
 * Traduz o ticker da plataforma no símbolo da TradingView.
 * Aceita já um símbolo completo (`NASDAQ:AAPL`), um ticker com sufixo
 * (`EDP.LS`) ou um ticker simples + a bolsa devolvida pela API (`LIS`).
 */
export function tradingViewSymbol(ticker: string, exchange?: string | null): string {
  const clean = (ticker || "").trim().toUpperCase();
  if (!clean) return "";
  if (clean.includes(":")) return clean;
  if (clean.includes(".")) {
    const [base, suffix] = clean.split(".");
    const prefix = SUFFIX_PREFIX[suffix];
    return prefix ? `${prefix}:${base}` : clean;
  }
  const prefix = exchange ? EXCHANGE_PREFIX[exchange.toUpperCase()] : undefined;
  return prefix ? `${prefix}:${clean}` : clean;
}

/* ------------------------------------------------------ override manual */

const SYMBOL_KEY = "finance-llm-tv-symbols:v1";

function readOverrides(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(SYMBOL_KEY) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

/** Símbolo guardado pelo utilizador para um ticker (se existir). */
export function savedTradingViewSymbol(ticker: string): string | undefined {
  return readOverrides()[(ticker || "").toUpperCase()];
}

/** Guarda (ou limpa, com `null`) o símbolo escolhido para um ticker. */
export function saveTradingViewSymbol(ticker: string, symbol: string | null) {
  if (typeof window === "undefined") return;
  const overrides = readOverrides();
  const key = (ticker || "").toUpperCase();
  if (symbol) overrides[key] = symbol.toUpperCase();
  else delete overrides[key];
  try {
    window.localStorage.setItem(SYMBOL_KEY, JSON.stringify(overrides));
  } catch {
    /* sem persistência */
  }
}

/* ------------------------------------------------------------- widget */

const INTERVALS: { value: string; label: string }[] = [
  { value: "1", label: "1 min" },
  { value: "5", label: "5 min" },
  { value: "15", label: "15 min" },
  { value: "30", label: "30 min" },
  { value: "60", label: "1 hora" },
  { value: "240", label: "4 horas" },
  { value: "D", label: "Diário" },
  { value: "W", label: "Semanal" },
  { value: "M", label: "Mensal" },
];

const STYLES: { value: string; label: string }[] = [
  { value: "1", label: "Velas" },
  { value: "9", label: "Velas ocas" },
  { value: "8", label: "Heikin Ashi" },
  { value: "3", label: "Área" },
  { value: "2", label: "Linha" },
  { value: "0", label: "Barras" },
];

const STUDIES: { value: string; label: string }[] = [
  { value: "STD;Volume", label: "Volume" },
  { value: "STD;RSI", label: "RSI" },
  { value: "STD;MACD", label: "MACD" },
  { value: "STD;BB", label: "Bollinger" },
  { value: "STD;EMA", label: "EMA" },
];

type ChartSettings = {
  interval: string;
  style: string;
  studies: string[];
  theme: "dark" | "light";
  toolbar: boolean;
};

const DEFAULT_SETTINGS: ChartSettings = {
  interval: "D",
  style: "1",
  studies: ["STD;Volume"],
  theme: "dark",
  // Como no snippet oficial da TradingView: a barra lateral de desenho vem
  // escondida (`hide_side_toolbar: true`).
  toolbar: false,
};

/**
 * Contentor oculto — sempre ligado ao documento — onde ficam as gerações antigas
 * do widget da TradingView até o respetivo script ter executado.
 *
 * Motivo: o script `embed-widget-advanced-chart.js` encontra o contentor através
 * do elemento `<script>`:
 *
 *   const d = document.currentScript.parentNode;              // tem de ser
 *   const m = d.classList.contains("tradingview-widget-container");  // a classe!
 *
 * Daí as duas regras deste componente:
 *
 * 1. o `<script>` é sempre filho direto de um elemento com a classe
 *    `tradingview-widget-container` (a «geração»), senão o widget não encontra
 *    o contentor e falha com `Cannot listen to the event from the provided
 *    iframe, contentWindow is not available`;
 * 2. enquanto o script está a carregar, essa geração **nunca é removida do
 *    documento** — é movida para aqui — senão o script executa com `parentNode`
 *    nulo e rebenta com `Cannot read properties of null (reading 'querySelector')`.
 */
function retiredWidgetHost(): HTMLElement {
  const existing = document.getElementById("iqos-tv-retired");
  if (existing) return existing;
  const host = document.createElement("div");
  host.id = "iqos-tv-retired";
  host.setAttribute("aria-hidden", "true");
  host.style.cssText =
    "position:absolute;left:-99999px;top:0;width:0;height:0;overflow:hidden;pointer-events:none";
  document.body.appendChild(host);
  return host;
}

/** Tempo que uma geração antiga fica viva (e invisível) à espera de executar. */
const RETIRED_TTL_MS = 30_000;

/**
 * Afasta uma geração do widget sem a remover do documento.
 *
 * Se a geração já estiver fora do documento (o React desmonta a página antes de
 * o script acabar de carregar), é **religada** ao contentor oculto: é isso que
 * garante que o script em voo executa com um pai ligado ao documento. Sem isto,
 * o widget cria o `iframe` fora do documento, onde `contentWindow` é `null`, e a
 * TradingView avisa «Cannot listen to the event from the provided iframe».
 */
function retireWidgetGeneration(generation: HTMLElement) {
  const host = retiredWidgetHost();
  host.appendChild(generation);
  window.setTimeout(() => generation.remove(), RETIRED_TTL_MS);
}

/**
 * Gráfico interativo da TradingView (Advanced Real-Time Chart).
 * O script externo é injetado por efeito — recriado quando muda qualquer opção.
 */
export function TradingViewChart({
  symbol,
  ticker,
  height = "100%",
  settings = DEFAULT_SETTINGS,
  rounded = true,
}: {
  symbol: string;
  /** Ticker da plataforma: usado pelo gráfico de reserva do IQ OS. */
  ticker?: string;
  height?: number | string;
  settings?: ChartSettings;
  rounded?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const studiesKey = settings.studies.join(",");

  /*
   * Vigia do widget: o script pode carregar (200) mas a TradingView recusa/
   * aborta a incorporação do `iframe` — o quadro fica em branco, sem erro de
   * JavaScript. Aí entra o gráfico nativo do IQ OS (dados da própria API).
   */
  useEffect(() => {
    if (!symbol || !ticker) return;
    setBlocked(false);
    let attempts = 0;
    let timer = 0;

    const frameLoaded = (): boolean | null => {
      const frame = containerRef.current?.querySelector("iframe");
      if (!frame) return null;
      try {
        // Acesso permitido: o quadro continua no documento vazio (`about:blank`)
        // ou numa página de erro do browser => não carregou.
        const doc = frame.contentDocument;
        if (!doc) return true;
        const href = doc.location.href;
        if (href.startsWith("chrome-error://")) return false;
        if (href === "about:blank" && (!doc.body || doc.body.childElementCount === 0)) return false;
        return true;
      } catch {
        // Sem acesso => conteúdo de outra origem => carregou.
        return true;
      }
    };

    const check = () => {
      if (frameLoaded() === true) return;
      attempts += 1;
      if (attempts >= 12) {
        setBlocked(true);
        return;
      }
      timer = window.setTimeout(check, 400);
    };
    timer = window.setTimeout(check, 600);
    return () => window.clearTimeout(timer);
  }, [symbol, ticker, settings.interval, settings.style, settings.theme, studiesKey, retryToken]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !symbol) return;
    setFailed(false);

    let cancelled = false;
    let generation: HTMLDivElement | null = null;
    let observer: MutationObserver | null = null;
    let frame = 0;
    let timer = 0;

    /*
     * Constrói uma «geração» nova: um contentor com a classe que o widget da
     * TradingView procura (pai direto do `<script>`) e, lá dentro, o alvo e o
     * próprio script.
     *
     * O contentor tem de estar **ligado ao documento** antes de o script
     * executar: se não estiver, a TradingView cria o `iframe` fora do documento,
     * onde `iframe.contentWindow` é `null`, e avisa «Cannot listen to the event
     * from the provided iframe». Como o script vem de cache e executa em poucos
     * milissegundos, não basta a ordem dos `appendChild` — é preciso esperar que
     * o React ligue o contentor à página.
     */
    const build = (): boolean => {
      if (cancelled || !container.isConnected) return false;

      generation = document.createElement("div");
      generation.className = "tradingview-widget-container";
      generation.dataset.tvGeneration = "1";
      generation.style.height = "100%";
      generation.style.width = "100%";

      const widget = document.createElement("div");
      widget.className = "tradingview-widget-container__widget";
      // Como no snippet oficial: o gráfico ocupa a altura do contentor menos a
      // faixa de 32 px do aviso de copyright da TradingView.
      widget.style.height = "calc(100% - 32px)";
      widget.style.width = "100%";
      generation.appendChild(widget);

      /*
       * Aviso de copyright: vem no snippet oficial e é também ele que dá altura
       * útil ao gráfico (`calc(100% - 32px)` acima).
       */
      const copyright = document.createElement("div");
      copyright.className = "tradingview-widget-copyright";
      copyright.style.cssText =
        "height:32px;display:flex;align-items:center;justify-content:center;gap:4px;" +
        "font-size:11.5px;color:#9aa0a6;background:transparent";
      const link = document.createElement("a");
      link.href = `https://www.tradingview.com/symbols/${symbol.replace(":", "-")}/`;
      link.target = "_blank";
      link.rel = "noopener nofollow";
      link.style.color = "#7cc4ff";
      link.textContent = `${symbol} — gráfico de cotações`;
      const trademark = document.createElement("span");
      trademark.textContent = "por TradingView";
      copyright.append(link, trademark);
      generation.appendChild(copyright);

      const script = document.createElement("script");
      script.type = "text/javascript";
      script.async = true;
      script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
      // Configuração do widget (as mesmas chaves do snippet oficial).
      script.innerHTML = JSON.stringify({
        autosize: true,
        symbol,
        interval: settings.interval,
        timezone: "Europe/Lisbon",
        theme: settings.theme,
        style: settings.style,
        locale: "pt_PT",
        withdateranges: true,
        hide_side_toolbar: !settings.toolbar,
        hide_top_toolbar: false,
        hide_legend: false,
        hide_volume: false,
        allow_symbol_change: true,
        save_image: true,
        details: false,
        calendar: false,
        hotlist: false,
        watchlist: [],
        compareSymbols: [],
        studies: settings.studies,
        backgroundColor: settings.theme === "dark" ? "#0f1115" : "#ffffff",
        gridColor: settings.theme === "dark" ? "rgba(255, 255, 255, 0.06)" : "rgba(46, 46, 46, 0.2)",
        support_host: "https://www.tradingview.com",
      });
      script.onerror = () => setFailed(true);
      // Depois de executar, a geração já pode ser removida sem risco. Se já
      // estava estacionada (página desmontada), o widget não serve para nada:
      // sai logo, em vez de ficar 30 s a consumir recursos.
      script.onload = () => {
        if (!generation) return;
        generation.dataset.tvExecuted = "1";
        if (generation.parentElement && generation.parentElement.id === "iqos-tv-retired") {
          generation.remove();
        }
      };
      generation.appendChild(script);

      container.appendChild(generation);
      return true;
    };

    if (!build()) {
      /*
       * O contentor ainda não está na página (o React pode montar a árvore antes
       * de a ligar, e a aplicação é montada em vários passos). Espera-se pela
       * ligação com um observador de mutações e, em paralelo, com uma repetição
       * limitada — se o contentor for de uma árvore descartada, desiste sem
       * gastar recursos.
       */
      let attempts = 0;
      const retry = () => {
        if (build()) return;
        attempts += 1;
        if (attempts < 40) timer = window.setTimeout(retry, 250);
      };
      observer = new MutationObserver(() => {
        if (build()) observer?.disconnect();
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
      frame = window.requestAnimationFrame(() => {
        if (build()) observer?.disconnect();
      });
      timer = window.setTimeout(retry, 50);
    }

    return () => {
      cancelled = true;
      observer?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      if (timer) window.clearTimeout(timer);
      if (!generation) return;
      if (generation.dataset.tvExecuted === "1") generation.remove();
      else retireWidgetGeneration(generation);
    };
  }, [settings.interval, settings.style, settings.theme, settings.toolbar, studiesKey, symbol, retryToken]);

  const tradingViewHref = symbol
    ? `https://www.tradingview.com/symbols/${symbol.replace(":", "-")}/`
    : "https://www.tradingview.com/markets/";

  const usarNativo = Boolean(ticker) && (blocked || failed);

  /* A incorporação foi bloqueada neste browser: gráfico nativo do IQ OS. */
  if (usarNativo && ticker) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-[11.5px] text-amber-100">
          <ShieldAlert size={13} className="shrink-0" />
          <span className="min-w-0 flex-1">
            O gráfico da TradingView não carregou neste browser (a incorporação de <code>tradingview-widget.com</code> foi
            bloqueada, o que acontece em ambientes restritos). A mostrar o gráfico nativo do IQ OS, com cotações da própria API.
          </span>
          <button
            type="button"
            onClick={() => {
              setBlocked(false);
              setRetryToken((value) => value + 1);
            }}
            className="h-7 shrink-0 rounded-lg bg-amber-300/20 px-2.5 font-medium text-amber-50 transition hover:bg-amber-300/30"
          >
            Tentar a TradingView
          </button>
          <a
            href={tradingViewHref}
            target="_blank"
            rel="noreferrer"
            className="flex h-7 shrink-0 items-center gap-1 rounded-lg border border-white/15 px-2.5 text-amber-50/90 transition hover:bg-white/10"
          >
            <ExternalLink size={11} /> Abrir na TradingView
          </a>
        </div>
        <NativePriceChart ticker={ticker} interval={settings.interval} theme={settings.theme} rounded={rounded} height={height} />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* A classe `tradingview-widget-container` fica na geração criada no
          efeito: é o pai do `<script>` e é o que o widget procura. */}
      <div
        ref={containerRef}
        className={[
          "relative min-h-[320px] w-full flex-1 overflow-hidden border border-white/10 bg-[#0f1115]",
          rounded ? "rounded-xl" : "",
        ].join(" ")}
        style={{ height }}
      />
      {failed && (
        <p className="mt-2 text-[11.5px] text-rose-300">
          Não foi possível carregar o gráfico (sem ligação à TradingView?). Verifique a rede e tente
          novamente.
        </p>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- página */

export default function RealtimeChartPage({ initialTicker }: { initialTicker?: string }) {
  const [tickerInput, setTickerInput] = useState(initialTicker?.toUpperCase() ?? "");
  const [ticker, setTicker] = useState(initialTicker?.toUpperCase() ?? "");
  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [manual, setManual] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [settings, setSettings] = useState<ChartSettings>(DEFAULT_SETTINGS);
  const [reloadToken, setReloadToken] = useState(0);
  const shellRef = useRef<HTMLDivElement | null>(null);

  /* Ticker a mostrar: o inicial, o guardado ou o último usado no Mercados. */
  useEffect(() => {
    if (ticker) return;
    const stored =
      initialTicker ||
      (typeof window !== "undefined"
        ? window.localStorage.getItem("finance-llm-ticker-detail") || window.localStorage.getItem("finance-llm-ticker")
        : null);
    if (stored) {
      setTicker(stored.toUpperCase());
      setTickerInput(stored.toUpperCase());
    }
  }, [initialTicker, ticker]);

  /* Metadados do ticker (nome, bolsa) para resolver o símbolo da TradingView. */
  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTickerInfo(ticker)
      .then((response) => {
        if (!cancelled) setInfo(response);
      })
      .catch((caught) => {
        if (cancelled) return;
        setInfo(null);
        setError(caught instanceof Error ? caught.message : "Não foi possível obter os dados do ticker.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, reloadToken]);

  /* Sugestões de tickers enquanto se escreve. */
  useEffect(() => {
    if (tickerInput.trim().length < 2 || tickerInput.toUpperCase() === ticker) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      searchLocalTickers(tickerInput.trim())
        .then((list) => {
          if (!cancelled) setSuggestions(list.slice(0, 8));
        })
        .catch(() => {
          searchYahooTickers(tickerInput.trim())
            .then((response) => {
              if (!cancelled) setSuggestions((response.tickers ?? []).slice(0, 8));
            })
            .catch(() => {
              if (!cancelled) setSuggestions([]);
            });
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ticker, tickerInput]);

  const resolved = useMemo(() => {
    const override = savedTradingViewSymbol(ticker);
    if (override) return override;
    return tradingViewSymbol(ticker, info?.exchange);
  }, [info?.exchange, ticker]);

  const symbol = manual.trim() ? manual.trim().toUpperCase() : resolved;

  const applyTicker = useCallback((value: string) => {
    const clean = value.trim().toUpperCase();
    if (!clean) return;
    setTicker(clean);
    setTickerInput(clean);
    setSuggestions([]);
    setManual("");
    setManualOpen(false);
    if (typeof window !== "undefined") window.localStorage.setItem("finance-llm-ticker-detail", clean);
  }, []);

  const price = info?.price;

  return (
    <div
      ref={shellRef}
      className="finder-shell flex flex-col bg-background text-foreground"
      data-in-window="true"
    >
      {/* Barra de ferramentas */}
      <header className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.02] px-3 py-2 backdrop-blur-xl">
        <span className="grid h-6 w-6 place-items-center rounded-[6px] bg-gradient-to-br from-lime-200 via-green-500 to-emerald-700 text-white shadow-sm">
          <CandlestickChart size={13} />
        </span>
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[13px] font-semibold">
            <span>{ticker || "—"}</span>
            {price !== undefined && price !== null && (
              <span className="tabular-nums text-muted-foreground">
                {price.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}{" "}
                {info?.currency ?? ""}
              </span>
            )}
          </p>
          <p className="truncate text-[10.5px] text-muted-foreground">
            {info?.name ?? "Sem metadados"} · símbolo TradingView: <span className="font-mono">{symbol}</span>
            {info?.exchange ? ` (${info.exchange})` : ""}
          </p>
        </div>

        {/* Pesquisa de ticker */}
        <div className="relative ml-auto flex items-center gap-1.5">
          <label className="relative flex items-center">
            <Search size={12} className="pointer-events-none absolute left-2 text-muted-foreground" />
            <input
              value={tickerInput}
              onChange={(event) => setTickerInput(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") applyTicker(suggestions[0] ?? tickerInput);
              }}
              placeholder="Ticker (ex.: AAPL, EDP, MC.PA)"
              className="w-40 rounded-lg border border-white/10 bg-white/[0.04] py-1 pl-7 pr-2 text-[11.5px] outline-none transition focus:border-teal-400/40 @2xl:w-56"
            />
          </label>
          <button
            type="button"
            onClick={() => applyTicker(suggestions[0] ?? tickerInput)}
            className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1]"
          >
            Abrir
          </button>
          {suggestions.length > 0 && (
            <ul className="absolute left-0 top-8 z-40 max-h-56 w-56 overflow-auto rounded-xl border border-white/10 bg-[#12141a]/97 p-1.5 shadow-2xl backdrop-blur-xl">
              {suggestions.map((suggestion) => (
                <li key={suggestion}>
                  <button
                    type="button"
                    onClick={() => applyTicker(suggestion)}
                    className="w-full rounded-lg px-2 py-1 text-left font-mono text-[11.5px] transition hover:bg-white/8"
                  >
                    {suggestion}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </header>

      {/* Controlos do gráfico */}
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-white/8 bg-white/[0.01] px-3 py-1.5">
        <select
          value={settings.interval}
          onChange={(event) => setSettings((current) => ({ ...current, interval: event.target.value }))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none"
          title="Intervalo"
        >
          {INTERVALS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          value={settings.style}
          onChange={(event) => setSettings((current) => ({ ...current, style: event.target.value }))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none"
          title="Estilo do gráfico"
        >
          {STYLES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {STUDIES.map((study) => {
          const active = settings.studies.includes(study.value);
          return (
            <button
              key={study.value}
              type="button"
              aria-pressed={active}
              onClick={() =>
                setSettings((current) => ({
                  ...current,
                  studies: active
                    ? current.studies.filter((value) => value !== study.value)
                    : [...current.studies, study.value],
                }))
              }
              className={[
                "rounded-lg border px-2 py-1 text-[11.5px] transition",
                active
                  ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                  : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
              ].join(" ")}
            >
              {study.label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setSettings((current) => ({ ...current, toolbar: !current.toolbar }))}
          aria-pressed={settings.toolbar}
          title="Barra lateral de ferramentas de desenho"
          className={[
            "rounded-lg border px-2 py-1 text-[11.5px] transition",
            settings.toolbar
              ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
              : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
          ].join(" ")}
        >
          Ferramentas
        </button>
        <button
          type="button"
          onClick={() => setSettings((current) => ({ ...current, theme: current.theme === "dark" ? "light" : "dark" }))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
        >
          {settings.theme === "dark" ? "Tema escuro" : "Tema claro"}
        </button>
        <button
          type="button"
          onClick={() => {
            const node = shellRef.current;
            if (!node) return;
            if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => undefined);
            else void node.requestFullscreen?.().catch(() => undefined);
          }}
          title="Ecrã inteiro"
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
        >
          <Fullscreen size={12} /> Ecrã inteiro
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setManualOpen((value) => !value)}
            title="Escrever o símbolo da TradingView à mão (ex.: EURONEXT:EDP)"
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
          >
            <Maximize2 size={12} /> Símbolo manual
          </button>
          <button
            type="button"
            onClick={() => setReloadToken((value) => value + 1)}
            title="Atualizar metadados"
            className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.09]"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          </button>
          <a
            href={symbol ? `https://www.tradingview.com/symbols/${symbol.replace(":", "-")}/` : "https://www.tradingview.com/markets/"}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
          >
            <ExternalLink size={12} /> TradingView
          </a>
        </div>
      </div>

      {manualOpen && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.01] px-3 py-1.5">
          <input
            value={manual}
            onChange={(event) => setManual(event.target.value.toUpperCase())}
            placeholder={`Símbolo da TradingView (sugerido: ${resolved || "—"})`}
            className="w-64 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11.5px] outline-none focus:border-teal-400/40"
          />
          <button
            type="button"
            onClick={() => {
              if (!manual.trim()) return;
              saveTradingViewSymbol(ticker, manual.trim().toUpperCase());
              setManual("");
              setManualOpen(false);
            }}
            className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1]"
          >
            Guardar para {ticker || "este ticker"}
          </button>
          <button
            type="button"
            onClick={() => {
              saveTradingViewSymbol(ticker, null);
              setManual("");
            }}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.09]"
          >
            Repor automático
          </button>
          <span className="text-[11px] text-muted-foreground">
            Exemplos: <span className="font-mono">EURONEXT:EDP</span>,{" "}
            <span className="font-mono">NASDAQ:AAPL</span>, <span className="font-mono">BME:SAN</span>
          </span>
        </div>
      )}

      {error && (
        <p className="shrink-0 border-b border-amber-400/20 bg-amber-400/10 px-3 py-1.5 text-[11.5px] text-amber-200">
          {error} — o gráfico continua disponível com o símbolo <span className="font-mono">{symbol || "—"}</span>.
        </p>
      )}

      {/* Gráfico */}
      <div className="flex min-h-0 flex-1 flex-col p-2">
        {!symbol ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-muted-foreground">
            <CandlestickChart size={28} />
            <p className="text-[12.5px]">Escolha um ticker para ver o gráfico em tempo real.</p>
          </div>
        ) : loading && !info ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-[12.5px] text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> A resolver o símbolo…
          </div>
        ) : (
          <TradingViewChart symbol={symbol} ticker={ticker} settings={settings} />
        )}
      </div>

      <footer className="shrink-0 border-t border-white/8 px-3 py-1.5 text-[10.5px] text-muted-foreground">
        Cotações e gráfico fornecidos pela TradingView — em tempo real ou com atraso conforme a bolsa
        e as permissões da sua conta. Símbolo: <span className="font-mono">{symbol || "—"}</span>
      </footer>
    </div>
  );
}
