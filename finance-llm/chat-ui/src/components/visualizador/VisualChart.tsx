/**
 * Desenho dos visuais do Visualizador (Recharts).
 *
 * Cada visual recebe o resultado de **uma** consulta (dimensões × medidas) e
 * desenha-o no tipo escolhido. O pivot de duas dimensões (barras empilhadas) e o
 * par de medidas (dispersão) são resolvidos aqui, no cliente — o backend devolve
 * sempre linhas planas.
 */
import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { QueryColumn, QueryResult, QueryRow, VisualConfig } from "../../visualizadorApi";

const CHART_COLORS = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1", "#84cc16", "#f97316"];

const tooltipStyle = {
  backgroundColor: "#16181d",
  borderColor: "#2e323b",
  color: "#e8e9ec",
  borderRadius: 12,
} as const;

// ---------------------------------------------------------------------------
// Formatação
// ---------------------------------------------------------------------------
export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mM`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M`;
  if (abs >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil`;
  return value.toLocaleString("pt-PT", { maximumFractionDigits: 2 });
}

export function formatCurrencyCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} mM€`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil€`;
  return `${value.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

/** Formata um valor segundo a coluna (unidade, formato, tipo). */
export function formatCell(value: string | number | null | undefined, column?: QueryColumn): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  const format = column?.format || (column?.data_type === "date" ? "date" : undefined);
  if (column?.unit === "€" || format === "currency") return formatCurrencyCompact(value);
  if (format === "integer" || column?.measure_kind === "contagem" || column?.measure_kind === "distintos") return formatNumber(value, 0);
  if (Math.abs(value) >= 1000) return formatNumber(value, 0);
  return value.toLocaleString("pt-PT", { maximumFractionDigits: 2 });
}

/** Rótulo de eixo para dimensões de data (o backend devolve ISO, ano ou mês). */
export function formatDimensionValue(value: string | number | null | undefined, column?: QueryColumn): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  if (column?.data_type === "date" || column?.type === "dimension" && column?.data_type === "date") {
    if (/^\d{4}$/.test(text)) return text;
    if (/^\d{4}-\d{2}$/.test(text)) {
      const [year, month] = text.split("-");
      const date = new Date(Number(year), Number(month) - 1, 1);
      return date.toLocaleDateString("pt-PT", { month: "short", year: "2-digit" });
    }
    const parsed = new Date(text);
    if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });
  }
  return text;
}

function isNumeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// ---------------------------------------------------------------------------
// Preparação dos dados
// ---------------------------------------------------------------------------
type ChartData = {
  dimensionKeys: string[];
  valueKeys: string[];
  rows: QueryRow[];
  labels: Record<string, QueryColumn>;
  isEmpty: boolean;
};

function prepare(result: QueryResult): ChartData {
  const labels: Record<string, QueryColumn> = {};
  for (const column of result.columns ?? []) labels[column.key] = column;
  const dimensionKeys = (result.columns ?? []).filter((column) => column.type === "dimension").map((column) => column.key);
  const valueKeys = (result.columns ?? []).filter((column) => column.type !== "dimension").map((column) => column.key);
  const rows = result.rows ?? [];
  return { dimensionKeys, valueKeys, rows, labels, isEmpty: rows.length === 0 };
}

/** Pivot para barras empilhadas: uma linha por 1.ª dimensão, uma série por 2.ª. */
function pivot(rows: QueryRow[], first: string, second: string, value: string): { data: Record<string, string | number>[]; series: string[] } {
  const series: string[] = [];
  const map = new Map<string, Record<string, string | number>>();
  for (const row of rows) {
    const key = String(row[first] ?? "—");
    const group = String(row[second] ?? "—");
    if (!series.includes(group)) series.push(group);
    const entry = map.get(key) ?? { __key: key };
    const current = Number(entry[group] ?? 0);
    entry[group] = current + (isNumeric(row[value]) ? (row[value] as number) : 0);
    map.set(key, entry);
  }
  return { data: Array.from(map.values()), series: series.slice(0, 12) };
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center gap-2 text-sm text-muted-foreground px-6">
      <p>{message}</p>
    </div>
  );
}

function tips(columns: QueryColumn[], labels: Record<string, QueryColumn>) {
  return (value: unknown, name: unknown): [string, string] => {
    const column = labels[String(name)] ?? columns.find((item) => item.label === name);
    return [formatCell(typeof value === "number" ? value : (value as string), column), String(column?.label ?? name)];
  };
}

// ---------------------------------------------------------------------------
// Componente
// ---------------------------------------------------------------------------
export function VisualChart({
  result,
  config,
  onSelectRow,
}: {
  result: QueryResult;
  config: VisualConfig;
  onSelectRow?: (row: QueryRow) => void;
}) {
  const { dimensionKeys, valueKeys, rows, labels, isEmpty } = prepare(result);
  const primaryMeasure = valueKeys[0];
  const secondMeasure = valueKeys[1];
  const firstDimension = dimensionKeys[0];
  const secondDimension = dimensionKeys[1];

  if (result.error) {
    return <EmptyState message={result.error} />;
  }
  if (isEmpty) {
    return <EmptyState message="Sem dados para os filtros aplicados." />;
  }
  if (!primaryMeasure && config.chart !== "kpi") {
    return <EmptyState message="Escolha pelo menos uma medida." />;
  }

  const axisTickFormatter = (value: unknown) => {
    const column = labels[firstDimension];
    // Dimensões mostram-se como são (um ano é "2025", não "2 mil"); só as
    // medidas é que são abreviadas.
    if (column?.type === "dimension") return formatDimensionValue(String(value), column);
    return typeof value === "number" ? formatCompact(value) : String(value);
  };
  const primaryColumn = labels[primaryMeasure];
  const valueFormatter = (value: number) =>
    primaryColumn?.unit === "€" || primaryColumn?.format === "currency" ? formatCurrencyCompact(value) : formatCompact(value);

  switch (config.chart) {
    case "kpi": {
      const totalsSource = dimensionKeys.length > 0 ? (result.totals ?? {}) : (rows[0] ?? {});
      const entries = valueKeys.length > 0 ? valueKeys : Object.keys(result.totals ?? {});
      return (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 h-full content-center">
          {entries.slice(0, 6).map((key) => {
            const column = labels[key];
            const raw = totalsSource[key];
            const value = typeof raw === "number" ? raw : null;
            return (
              <div key={key} className="glass-card rounded-xl px-3 py-3 fade-in">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground truncate">{column?.label ?? key}</p>
                <p className="text-xl md:text-2xl font-bold stat-value mt-1 truncate">{formatCell(value, column)}</p>
                {dimensionKeys.length > 0 && <p className="text-[10px] text-muted-foreground mt-1">total com filtros</p>}
              </div>
            );
          })}
        </div>
      );
    }

    case "donut": {
      const data = rows
        .map((row) => ({
          name: formatDimensionValue(row[firstDimension], labels[firstDimension]),
          value: isNumeric(row[primaryMeasure]) ? (row[primaryMeasure] as number) : 0,
          row,
        }))
        .filter((entry) => entry.value > 0);
      return (
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="45%" outerRadius="78%" paddingAngle={2}
                 onClick={(entry: unknown) => {
                   const point = entry as { payload?: { row?: QueryRow } };
                   if (point?.payload?.row && onSelectRow) onSelectRow(point.payload.row);
                 }}>
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} stroke="#16181d" />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} formatter={tips(result.columns, labels)} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#9aa0aa" }} />
          </PieChart>
        </ResponsiveContainer>
      );
    }

    case "treemap": {
      const data = rows
        .map((row) => ({
          name: secondDimension && row[secondDimension] ? `${row[firstDimension]} · ${row[secondDimension]}` : String(row[firstDimension] ?? "—"),
          size: isNumeric(row[primaryMeasure]) ? Math.abs(row[primaryMeasure] as number) : 0,
          value: isNumeric(row[primaryMeasure]) ? (row[primaryMeasure] as number) : 0,
        }))
        .filter((entry) => entry.size > 0);
      return (
        <ResponsiveContainer width="100%" height="100%">
          <Treemap data={data} dataKey="size" nameKey="name" stroke="#0f1115" aspectRatio={4 / 3} isAnimationActive={false}>
            <Tooltip contentStyle={tooltipStyle} formatter={tips(result.columns, labels)} />
          </Treemap>
        </ResponsiveContainer>
      );
    }

    case "scatter": {
      if (!secondMeasure) return <EmptyState message="A dispersão precisa de duas medidas." />;
      const data = rows.map((row) => ({
        x: isNumeric(row[primaryMeasure]) ? (row[primaryMeasure] as number) : 0,
        y: isNumeric(row[secondMeasure]) ? (row[secondMeasure] as number) : 0,
        z: dimensionKeys.length > 0 && isNumeric(row["contagem"]) ? (row["contagem"] as number) : 1,
        name: formatDimensionValue(row[firstDimension], labels[firstDimension]),
        row,
      }));
      return (
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
            <XAxis type="number" dataKey="x" name={labels[primaryMeasure]?.label ?? primaryMeasure} stroke="#9aa0aa"
                   tickFormatter={valueFormatter} tick={{ fontSize: 11 }} />
            <YAxis type="number" dataKey="y" name={labels[secondMeasure]?.label ?? secondMeasure} stroke="#9aa0aa"
                   tickFormatter={valueFormatter} tick={{ fontSize: 11 }} />
            <ZAxis type="number" dataKey="z" range={[40, 420]} />
            <Tooltip contentStyle={tooltipStyle} formatter={tips(result.columns, labels)} />
            <Scatter data={data} fill="#10a37f" onClick={(point: unknown) => {
              const payload = point as { payload?: { row?: QueryRow } };
              if (payload?.payload?.row && onSelectRow) onSelectRow(payload.payload.row);
            }} />
          </ScatterChart>
        </ResponsiveContainer>
      );
    }

    case "stacked": {
      if (!secondDimension) return <EmptyState message="Escolha duas dimensões para barras empilhadas." />;
      const { data, series } = pivot(rows, firstDimension, secondDimension, primaryMeasure);
      return (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" vertical={false} />
            <XAxis dataKey="__key" stroke="#9aa0aa" tick={{ fontSize: 11 }} tickFormatter={axisTickFormatter} />
            <YAxis stroke="#9aa0aa" tick={{ fontSize: 11 }} tickFormatter={valueFormatter} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#9aa0aa" }} />
            {series.map((key, index) => (
              <Bar key={key} dataKey={key} stackId="total" fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      );
    }

    case "matrix": {
      const columns = result.columns ?? [];
      return (
        <div className="h-full overflow-auto rounded-xl border border-border/60">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card/95 backdrop-blur">
              <tr>
                {columns.map((column) => (
                  <th key={column.key}
                      className={["px-3 py-2 font-semibold text-muted-foreground whitespace-nowrap", column.type === "dimension" ? "text-left" : "text-right"].join(" ")}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row._key)}
                    onClick={() => onSelectRow?.(row)}
                    className="border-t border-border/40 hover:bg-white/5 cursor-pointer">
                  {columns.map((column) => (
                    <td key={column.key}
                        className={["px-3 py-1.5 whitespace-nowrap", column.type === "dimension" ? "text-left" : "text-right stat-value"].join(" ")}>
                      {column.type === "dimension"
                        ? formatDimensionValue(row[column.key], column)
                        : formatCell(row[column.key], column)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            {Object.keys(result.totals ?? {}).length > 0 && (
              <tfoot className="bg-white/5">
                <tr>
                  {columns.map((column) => (
                    <td key={column.key} className={["px-3 py-2 font-semibold whitespace-nowrap", column.type === "dimension" ? "text-left" : "text-right stat-value"].join(" ")}>
                      {column.type === "dimension" ? (column.key === columns[0]?.key ? "Total" : "") : formatCell(result.totals[column.key] ?? null, column)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      );
    }

    case "line":
    case "area":
    case "bar-h":
    case "bar":
    default: {
      const shared = {
        data: rows,
        margin: { top: 8, right: 16, bottom: 4, left: 4 },
      } as const;
      const axes = (
        <>
          <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" vertical={config.chart === "bar-h"} />
          {config.chart === "bar-h" ? (
            <>
              <XAxis type="number" stroke="#9aa0aa" tick={{ fontSize: 11 }} tickFormatter={valueFormatter} />
              <YAxis type="category" dataKey={firstDimension} stroke="#9aa0aa" width={150} tick={{ fontSize: 11 }}
                     tickFormatter={(value: unknown) => formatDimensionValue(String(value), labels[firstDimension])} />
            </>
          ) : (
            <>
              <XAxis dataKey={firstDimension} stroke="#9aa0aa" tick={{ fontSize: 11 }} tickFormatter={axisTickFormatter} />
              <YAxis stroke="#9aa0aa" tick={{ fontSize: 11 }} tickFormatter={valueFormatter} />
            </>
          )}
          <Tooltip contentStyle={tooltipStyle} formatter={tips(result.columns, labels)} labelFormatter={(value) => formatDimensionValue(String(value), labels[firstDimension])} />
          {valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#9aa0aa" }} />}
        </>
      );

      const bars: ReactNode[] = valueKeys.map((key, index) => (
        <Bar key={key} dataKey={key} fill={CHART_COLORS[index % CHART_COLORS.length]} radius={config.chart === "bar-h" ? [0, 4, 4, 0] : [4, 4, 0, 0]}
             onClick={(entry: unknown) => {
               const point = entry as { payload?: QueryRow };
               if (point?.payload && onSelectRow) onSelectRow(point.payload);
             }} />
      ));

      if (config.chart === "line" || config.chart === "area") {
        const ChartComponent = config.chart === "line" ? LineChart : AreaChart;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <ChartComponent {...shared}>
              {axes}
              {valueKeys.map((key, index) =>
                config.chart === "line" ? (
                  <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[index % CHART_COLORS.length]} strokeWidth={2} dot={false} />
                ) : (
                  <Area key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[index % CHART_COLORS.length]}
                        fill={CHART_COLORS[index % CHART_COLORS.length]} fillOpacity={0.25} />
                ),
              )}
            </ChartComponent>
          </ResponsiveContainer>
        );
      }

      return (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart {...shared} layout={config.chart === "bar-h" ? "vertical" : "horizontal"}>
            {axes}
            {bars}
          </BarChart>
        </ResponsiveContainer>
      );
    }
  }
}
