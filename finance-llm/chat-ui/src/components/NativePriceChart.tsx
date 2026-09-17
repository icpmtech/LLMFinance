/**
 * Gráfico de cotações do IQ OS — sem serviços externos.
 *
 * Serve de reserva ao widget da TradingView (`TradingViewChart`) quando o
 * `iframe` desse widget não consegue carregar: acontece em browsers/rede que
 * bloqueiam a incorporação de `www.tradingview-widget.com` (por exemplo o
 * browser embutido do VS Code, que aborta essas navegações com `ERR_ABORTED`).
 * Sem isto, a aplicação «Gráfico Tempo Real» ficava com uma área em branco.
 *
 * Os dados vêm da própria API do IQ OS (`/tickers/{ticker}/history`), pelo que o
 * gráfico funciona sempre — offline e sem chaves. As velas são diárias (o
 * intervalo intradiário exige a TradingView e é assinalado na interface).
 */
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { Loader2 } from "lucide-react";
import { getTickerHistory } from "../api";
import type { TickerHistory } from "../types";

/** Intervalo da TradingView → período suportado pela API do IQ OS. */
const TV_TO_API_PERIOD: Record<string, string> = {
  "1": "1mo",
  "5": "1mo",
  "15": "3mo",
  "30": "3mo",
  "60": "6mo",
  "240": "1y",
  D: "1y",
  W: "2y",
  M: "5y",
};

/** Intervalos intradiários: na API do IQ OS só existem velas diárias. */
const INTRADAY = new Set(["1", "5", "15", "30", "60", "240"]);

export function apiPeriodForInterval(interval: string): string {
  return TV_TO_API_PERIOD[interval] ?? "1y";
}

export function isIntradayInterval(interval: string): boolean {
  return INTRADAY.has(interval);
}

interface NativePriceChartProps {
  /** Ticker da plataforma (ex.: `EDP`, `AAPL`). */
  ticker: string;
  /** Intervalo escolhido na interface (formato TradingView). */
  interval?: string;
  theme?: "dark" | "light";
  height?: number | string;
  rounded?: boolean;
  /** Mostrar barra de volume. */
  showVolume?: boolean;
}

export function NativePriceChart({
  ticker,
  interval = "D",
  theme = "dark",
  height = "100%",
  rounded = true,
  showVolume = true,
}: NativePriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  /** Dados carregados antes de o gráfico existir (é aplicado quando existir). */
  const pendingRef = useRef<{ candles: unknown[]; volumes: unknown[] } | null>(null);
  const [status, setStatus] = useState<{ loading: boolean; error: string | null; bars: number }>({
    loading: true,
    error: null,
    bars: 0,
  });

  const period = apiPeriodForInterval(interval);
  const light = theme === "light";

  /** Aplica ao gráfico os dados já carregados (se o gráfico já existir). */
  const flushPending = () => {
    const pending = pendingRef.current;
    if (!pending || !candlesRef.current || !chartRef.current) return;
    candlesRef.current.setData(pending.candles as never);
    volumeRef.current?.setData(pending.volumes as never);
    chartRef.current.timeScale().fitContent();
  };

  /*
   * Gráfico criado uma vez por tema, mas **só quando o contentor está na página e
   * com tamanho**: o `lightweight-charts` mede o contentor ao criar e, se estiver
   * fora do documento (ou a 0×0), fica com o canvas por defeito (300×150) e nunca
   * se vê o gráfico. Daí o `ResizeObserver` + repetição limitada.
   */
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    let chart: IChartApi | null = null;
    let observer: ResizeObserver | null = null;
    let timer = 0;
    let attempts = 0;

    /** Mantém o canvas (backing store) igual ao tamanho do contentor. */
    const fit = () => {
      const width = node.clientWidth;
      const height = node.clientHeight;
      if (!chart || width === 0 || height === 0) return;
      chart.resize(width, height, true);
    };

    const start = (): boolean => {
      if (chart) return true;
      if (!node.isConnected || node.clientWidth === 0 || node.clientHeight === 0) return false;
      chart = createChart(node, {
        // Tamanho explícito + `ResizeObserver` próprio: o `autoSize` do
        // lightweight-charts não atualiza o *bitmap* do canvas em alguns
        // contextos (página oculta, contentor medido antes de ter tamanho),
        // deixando o canvas no tamanho por defeito (300×150) esticado por CSS.
        width: node.clientWidth,
        height: node.clientHeight,
        layout: {
          background: { type: ColorType.Solid, color: light ? "#ffffff" : "#0f1115" },
          textColor: light ? "#111827" : "#e5e7eb",
        },
        grid: {
          vertLines: { color: light ? "#eef1f5" : "#16181d" },
          horzLines: { color: light ? "#eef1f5" : "#16181d" },
        },
        crosshair: { mode: 1 },
        rightPriceScale: { borderColor: light ? "#d6dae1" : "#2e323b" },
        timeScale: { borderColor: light ? "#d6dae1" : "#2e323b" },
      });
      chartRef.current = chart;
      observer = new ResizeObserver(() => fit());
      observer.observe(node);
      window.requestAnimationFrame(fit);
      candlesRef.current = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });
      if (showVolume) {
        volumeRef.current = chart.addSeries(HistogramSeries, {
          color: light ? "rgba(100,116,139,0.45)" : "rgba(148,163,184,0.45)",
          priceFormat: { type: "volume" },
          priceScaleId: "left",
        });
        volumeRef.current.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      }
      flushPending();
      fit();
      return true;
    };

    if (!start()) {
      const wait = new ResizeObserver(() => {
        if (start()) wait.disconnect();
      });
      wait.observe(node);
      const retry = () => {
        if (start()) {
          wait.disconnect();
          return;
        }
        attempts += 1;
        if (attempts < 40) timer = window.setTimeout(retry, 250);
      };
      timer = window.setTimeout(retry, 50);
    }

    return () => {
      observer?.disconnect();
      if (timer) window.clearTimeout(timer);
      if (chart) chart.remove();
      chartRef.current = null;
      candlesRef.current = null;
      volumeRef.current = null;
    };
  }, [light, showVolume]);

  /* Dados da API do IQ OS. */
  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setStatus({ loading: true, error: null, bars: 0 });
    getTickerHistory(ticker, period)
      .then((history: TickerHistory) => {
        if (cancelled) return;
        const points = (history.points || []).filter((point) => typeof point.close === "number");
        const candles = points.map((point) => ({
          time: point.date.slice(0, 10),
          open: point.open ?? point.close ?? 0,
          high: point.high ?? point.close ?? 0,
          low: point.low ?? point.close ?? 0,
          close: point.close ?? 0,
        }));
        const volumes = points
          .filter((point) => typeof point.volume === "number")
          .map((point) => ({
            time: point.date.slice(0, 10),
            value: point.volume ?? 0,
            color: (point.close ?? 0) >= (point.open ?? 0) ? "rgba(16,185,129,0.35)" : "rgba(239,68,68,0.35)",
          }));
        pendingRef.current = { candles, volumes };
        flushPending();
        setStatus({ loading: false, error: candles.length ? null : "Sem cotações para este ticker.", bars: candles.length });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setStatus({
          loading: false,
          error: error instanceof Error ? error.message : "Não foi possível obter as cotações.",
          bars: 0,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, period]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={containerRef}
        className={[
          "relative min-h-[320px] w-full flex-1 overflow-hidden border border-white/10",
          light ? "bg-white" : "bg-[#0f1115]",
          rounded ? "rounded-xl" : "",
        ].join(" ")}
        style={{ height }}
      />
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-400">
        {status.loading ? (
          <span className="flex items-center gap-1.5">
            <Loader2 size={11} className="animate-spin" /> A carregar cotações do IQ OS…
          </span>
        ) : status.error ? (
          <span className="text-rose-300">{status.error}</span>
        ) : (
          <span>
            {status.bars} sessões · {period} (diário)
            {isIntradayInterval(interval) ? " — o intervalo intradiário só está disponível na TradingView" : ""}
          </span>
        )}
        <span className="text-zinc-500">fonte: API do IQ OS</span>
      </p>
    </div>
  );
}

export default NativePriceChart;
