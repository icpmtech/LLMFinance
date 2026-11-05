import { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  LineSeries,
  ColorType,
  type IChartApi,
} from "lightweight-charts";
import type { TickerHistoryResponse } from "../../portfolioApi";

interface PortfolioChartProps {
  history: Record<string, TickerHistoryResponse>;
  selected: string | null;
}

const COLORS = [
  "#34d399", // emerald
  "#60a5fa", // blue
  "#f87171", // red
  "#fbbf24", // amber
  "#a78bfa", // violet
  "#22d3ee", // cyan
  "#f472b6", // pink
];

export function PortfolioChart({ history, selected }: PortfolioChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const seriesData = useMemo(() => {
    const map: Record<string, { ticker: string; data: { time: string; value: number }[]; color: string } > = {};
    let colorIndex = 0;
    for (const [ticker, resp] of Object.entries(history)) {
      if (!resp?.points?.length) continue;
      const first = resp.points[0].close ?? resp.points[0].open ?? 0;
      if (!first) continue;
      const data = resp.points
        .filter((p) => typeof p.close === "number")
        .map((p) => ({
          time: typeof p.date === "string" ? p.date.split("T")[0] : String(p.date).split("T")[0],
          value: Number(((p.close! / first) * 100).toFixed(4)),
        }));
      if (data.length > 1) {
        map[ticker] = { ticker, data, color: COLORS[colorIndex % COLORS.length] };
        colorIndex++;
      }
    }
    return map;
  }, [history]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(node, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148, 163, 184, 0.15)",
      },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.15)",
        timeVisible: false,
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "rgba(148, 163, 184, 0.2)" },
        horzLine: { color: "rgba(148, 163, 184, 0.2)" },
      },
      autoSize: true,
    });
    chartRef.current = chart;

    const ordered = selected && seriesData[selected] ? [selected] : Object.keys(seriesData);
    ordered.forEach((ticker) => {
      const s = seriesData[ticker];
      const line = chart.addSeries(LineSeries, {
        color: s.color,
        lineWidth: selected ? 3 : 2,
        lastValueVisible: true,
        title: ticker,
      });
      line.setData(s.data);
    });

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (node.clientWidth && node.clientHeight) {
        chart.resize(node.clientWidth, node.clientHeight, true);
      }
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [seriesData, selected]);

  return (
    <div
      ref={containerRef}
      className="w-full"
      style={{ minHeight: selected ? 360 : 280, height: "100%" }}
    />
  );
}
