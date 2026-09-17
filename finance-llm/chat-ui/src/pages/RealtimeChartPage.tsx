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
} from "lucide-react";
import { getTickerInfo, searchLocalTickers, searchYahooTickers } from "../api";
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
  toolbar: true,
};

/**
 * Gráfico interativo da TradingView (Advanced Real-Time Chart).
 * O script externo é injetado por efeito — recriado quando muda qualquer opção.
 */
export function TradingViewChart({
  symbol,
  height = "100%",
  settings = DEFAULT_SETTINGS,
  rounded = true,
}: {
  symbol: string;
  height?: number | string;
  settings?: ChartSettings;
  rounded?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);
  const studiesKey = settings.studies.join(",");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !symbol) return;
    setFailed(false);
    container.innerHTML = "";

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "100%";
    widget.style.width = "100%";
    container.appendChild(widget);

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
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
      allow_symbol_change: true,
      save_image: true,
      details: false,
      calendar: false,
      hide_top_toolbar: false,
      studies: settings.studies,
      support_host: "https://www.tradingview.com",
    });
    script.onerror = () => setFailed(true);
    container.appendChild(script);

    return () => {
      container.innerHTML = "";
    };
  }, [settings.interval, settings.style, settings.theme, settings.toolbar, studiesKey, symbol]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={containerRef}
        className={[
          "tradingview-widget-container relative min-h-[320px] w-full flex-1 overflow-hidden border border-white/10 bg-[#0f1115]",
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
          <TradingViewChart symbol={symbol} settings={settings} />
        )}
      </div>

      <footer className="shrink-0 border-t border-white/8 px-3 py-1.5 text-[10.5px] text-muted-foreground">
        Cotações e gráfico fornecidos pela TradingView — em tempo real ou com atraso conforme a bolsa
        e as permissões da sua conta. Símbolo: <span className="font-mono">{symbol || "—"}</span>
      </footer>
    </div>
  );
}
