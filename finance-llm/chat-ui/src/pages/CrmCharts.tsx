/**
 * Gráficos do CRM (analytics e quadros de análise).
 *
 * Componentes "burros": recebem uma série já resolvida (`label` + `value`) e um
 * formatador. São desenhados com SVG e `div`s (sem bibliotecas de gráficos), para
 * ficarem leves e consistentes com o resto da plataforma.
 */
import type { ReactNode } from "react";

import type { CrmChartKind, CrmMetricKind } from "../crmSuiteApi";

export type CrmChartPoint = { label: string; value: number; extra?: string };

export const CHART_LABELS: Record<CrmChartKind, string> = {
  barras: "Barras horizontais",
  colunas: "Colunas",
  linhas: "Linhas",
  circular: "Circular",
  tabela: "Tabela",
  kpi: "Indicador",
};

export const CHART_OPTIONS: CrmChartKind[] = ["colunas", "barras", "linhas", "circular", "kpi", "tabela"];

const PALETTE = ["#5eead4", "#818cf8", "#fbbf24", "#fb7185", "#34d399", "#60a5fa", "#c084fc", "#f97316"];

/** Formata um valor conforme o tipo da métrica (euros, %, contagem…). */
export function formatMetric(kind: CrmMetricKind, value: number | null | undefined): string {
  const number = Number(value ?? 0);
  if (kind === "money") {
    return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(number);
  }
  if (kind === "percent") {
    const text = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(number);
    return `${text}\u00a0%`;
  }
  if (kind === "text") return String(value ?? "—");
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: kind === "int" ? 0 : 1 }).format(number);
}

function Frame({ title, subtitle, children, actions }: { title: string; subtitle?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex h-full flex-col rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[11px] uppercase tracking-wide text-muted-foreground" title={title}>
            {title}
          </p>
          {subtitle && <p className="truncate text-[10.5px] text-muted-foreground/80">{subtitle}</p>}
        </div>
        {actions}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

function Empty({ text = "Sem dados no período." }: { text?: string }) {
  return <p className="py-6 text-center text-[11.5px] text-muted-foreground/80">{text}</p>;
}

const maxOf = (points: CrmChartPoint[]) => Math.max(1, ...points.map((point) => Math.abs(point.value)));

/** Barras horizontais (boa para rankings com etiquetas longas). */
export function CrmBarsChart({ points, format }: { points: CrmChartPoint[]; format: (value: number) => string }) {
  if (points.length === 0) return <Empty />;
  const top = maxOf(points);
  return (
    <ul className="space-y-1.5">
      {points.map((point, index) => (
        <li key={`${point.label}-${index}`} className="flex items-center gap-2 text-[11.5px]" title={point.extra || `${point.label}: ${format(point.value)}`}>
          <span className="w-[38%] min-w-0 truncate text-muted-foreground">{point.label}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
            <span
              className="block h-full rounded-full bg-gradient-to-r from-teal-300 to-indigo-500"
              style={{ width: `${Math.max(2, (Math.abs(point.value) / top) * 100)}%` }}
            />
          </span>
          <span className="w-[24%] shrink-0 text-right font-medium text-foreground">{format(point.value)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Colunas verticais, com grelha e etiquetas rodadas quando são muitas. */
export function CrmColumnsChart({ points, format, height = 190 }: { points: CrmChartPoint[]; format: (value: number) => string; height?: number }) {
  if (points.length === 0) return <Empty />;
  const top = maxOf(points);
  const many = points.length > 8;
  return (
    <div className="flex flex-col gap-1" style={{ height }}>
      <div className="relative flex-1">
        {[0.25, 0.5, 0.75, 1].map((line) => (
          <span key={line} className="absolute inset-x-0 border-t border-dashed border-white/8" style={{ bottom: `${line * 100}%` }} />
        ))}
        <div className="absolute inset-0 flex items-end gap-1">
          {points.map((point, index) => (
            <div key={`${point.label}-${index}`} className="group flex h-full flex-1 flex-col justify-end" title={`${point.label}: ${format(point.value)}`}>
              <span className="mb-0.5 hidden text-center text-[9.5px] text-muted-foreground group-hover:block">{format(point.value)}</span>
              <span
                className="w-full rounded-t bg-gradient-to-t from-indigo-600 to-teal-300 transition group-hover:opacity-80"
                style={{ height: `${Math.max(2, (Math.abs(point.value) / top) * 100)}%` }}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-1">
        {points.map((point, index) => (
          <span
            key={`label-${point.label}-${index}`}
            className={many ? "flex-1 truncate text-center text-[9px]" : "flex-1 text-center text-[9.5px] leading-tight text-muted-foreground"}
            style={many ? { writingMode: "vertical-rl", maxHeight: 62, overflow: "hidden" } : { maxHeight: 26, overflow: "hidden" }}
            title={point.label}
          >
            {point.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Linha com área (evolução mensal). */
export function CrmLineChart({ points, format, height = 190 }: { points: CrmChartPoint[]; format: (value: number) => string; height?: number }) {
  if (points.length === 0) return <Empty />;
  const width = 640;
  const inner = height - 26;
  const top = maxOf(points);
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const coords = points.map((point, index) => ({
    x: points.length > 1 ? index * step : width / 2,
    y: inner - (Math.abs(point.value) / top) * (inner - 12),
  }));
  const line = coords.map((coord) => `${coord.x.toFixed(1)},${coord.y.toFixed(1)}`).join(" ");
  const area = `0,${inner} ${line} ${width},${inner}`;

  return (
    <div className="flex flex-col" style={{ height }}>
      <svg viewBox={`0 0 ${width} ${inner}`} preserveAspectRatio="none" className="h-full w-full">
        {[0, 0.5, 1].map((line2) => (
          <line key={line2} x1={0} x2={width} y1={inner - line2 * (inner - 12)} y2={inner - line2 * (inner - 12)} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
        ))}
        <polygon points={area} fill="url(#crmArea)" opacity="0.5" />
        <defs>
          <linearGradient id="crmArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5eead4" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <polyline points={line} fill="none" stroke="#7dd3fc" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {coords.map((coord, index) => (
          <circle key={index} cx={coord.x} cy={coord.y} r="3" fill="#0f172a" stroke="#7dd3fc" strokeWidth="1.5">
            <title>{`${points[index].label}: ${format(points[index].value)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="flex justify-between text-[9.5px] text-muted-foreground">
        <span>{points[0]?.label}</span>
        <span>{points[points.length - 1]?.label}</span>
      </div>
    </div>
  );
}

/** Anel (distribuições). */
export function CrmDonutChart({ points, format }: { points: CrmChartPoint[]; format: (value: number) => string }) {
  const data = points.filter((point) => point.value > 0).slice(0, 8);
  if (data.length === 0) return <Empty />;
  const total = data.reduce((sum, point) => sum + point.value, 0);
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 120 120" className="h-[132px] w-[132px] shrink-0">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="16" />
        {data.map((point, index) => {
          const share = point.value / total;
          const dash = share * circumference;
          const circle = (
            <circle
              key={point.label}
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={PALETTE[index % PALETTE.length]}
              strokeWidth="16"
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 60 60)"
            >
              <title>{`${point.label}: ${format(point.value)}`}</title>
            </circle>
          );
          offset += dash;
          return circle;
        })}
        <text x="60" y="58" textAnchor="middle" className="fill-foreground text-[13px] font-semibold">
          {format(total)}
        </text>
        <text x="60" y="72" textAnchor="middle" className="fill-muted-foreground text-[8px]">
          total
        </text>
      </svg>
      <ul className="min-w-0 flex-1 space-y-1 text-[11.5px]">
        {data.map((point, index) => (
          <li key={point.label} className="flex items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: PALETTE[index % PALETTE.length] }} />
            <span className="min-w-0 flex-1 truncate text-muted-foreground" title={point.label}>
              {point.label}
            </span>
            <span className="shrink-0 font-medium text-foreground">{format(point.value)}</span>
            <span className="w-10 shrink-0 text-right text-muted-foreground">{Math.round((point.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Indicador único (total da série). */
export function CrmKpiValue({ points, format, title }: { points: CrmChartPoint[]; format: (value: number) => string; title: string }) {
  const total = points.reduce((sum, point) => sum + point.value, 0);
  const best = points.reduce<CrmChartPoint | null>((top, point) => (!top || point.value > top.value ? point : top), null);
  return (
    <div className="flex flex-col justify-center gap-1 py-2">
      <p className="text-[26px] font-semibold text-teal-200">{format(total)}</p>
      <p className="text-[11px] text-muted-foreground">{title}</p>
      {best && (
        <p className="text-[11.5px] text-muted-foreground/90">
          Melhor: <span className="text-foreground">{best.label}</span> · {format(best.value)}
        </p>
      )}
      <p className="text-[10.5px] text-muted-foreground/80">{points.length} linha(s)</p>
    </div>
  );
}

/** Tabela simples (dimensão + métrica). */
export function CrmTableChart({ points, format, dimensionLabel, metricLabel }: { points: CrmChartPoint[]; format: (value: number) => string; dimensionLabel: string; metricLabel: string }) {
  if (points.length === 0) return <Empty />;
  return (
    <div className="max-h-[260px] overflow-auto">
      <table className="w-full border-collapse text-left">
        <thead className="sticky top-0 bg-[#0a1c24]/95">
          <tr>
            <th className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{dimensionLabel}</th>
            <th className="px-2 py-1 text-right text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{metricLabel}</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point, index) => (
            <tr key={`${point.label}-${index}`} className="border-t border-white/6">
              <td className="max-w-[240px] truncate px-2 py-1 text-[11.5px] text-foreground" title={point.label}>
                {point.label}
              </td>
              <td className="px-2 py-1 text-right text-[11.5px] text-muted-foreground">{format(point.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Desenha a série conforme o tipo de gráfico escolhido. */
export function CrmChart({
  kind,
  points,
  format,
  title,
  subtitle,
  dimensionLabel = "Dimensão",
  metricLabel = "Valor",
  actions,
}: {
  kind: CrmChartKind;
  points: CrmChartPoint[];
  format: (value: number) => string;
  title: string;
  subtitle?: string;
  dimensionLabel?: string;
  metricLabel?: string;
  actions?: ReactNode;
}) {
  return (
    <Frame title={title} subtitle={subtitle} actions={actions}>
      {kind === "barras" && <CrmBarsChart points={points} format={format} />}
      {kind === "colunas" && <CrmColumnsChart points={points} format={format} />}
      {kind === "linhas" && <CrmLineChart points={points} format={format} />}
      {kind === "circular" && <CrmDonutChart points={points} format={format} />}
      {kind === "kpi" && <CrmKpiValue points={points} format={format} title={metricLabel} />}
      {kind === "tabela" && <CrmTableChart points={points} format={format} dimensionLabel={dimensionLabel} metricLabel={metricLabel} />}
    </Frame>
  );
}
