/**
 * Desenho dos blocos do **Estúdio de relatórios**.
 *
 * Cada bloco recebe o resultado de uma consulta (dimensões × medidas), tal como
 * vem de `/reports/studio/query`: indicadores (KPI), gráficos (Recharts),
 * tabelas, grafos de relações (SVG) e texto. É a mesma matéria-prima que o PDF
 * desenha no servidor — o cliente não recalcula nada.
 */
import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui";
import { studioCompact, studioNumber, type StudioRunBlock } from "../../reportsStudioApi";

const CHART_COLORS = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1"];

const tooltipStyle = {
  backgroundColor: "#16181d",
  borderColor: "#2e323b",
  color: "#e8e9ec",
  borderRadius: 12,
} as const;

function dimensionKey(block: StudioRunBlock): string {
  return String(block.dimensions?.[0]?.id || "");
}

function measureEntry(block: StudioRunBlock) {
  return block.measures?.[0];
}

function axisTick(value: unknown): string {
  const text = String(value ?? "");
  return text.length > 16 ? `${text.slice(0, 15)}…` : text;
}

function valueOf(row: Record<string, unknown> | undefined, key: string): number {
  const value = row?.[key];
  return typeof value === "number" ? value : Number(value) || 0;
}

// ---------------------------------------------------------------------------
// Gráfico
// ---------------------------------------------------------------------------
export function StudioChart({ block, height = 240 }: { block: StudioRunBlock; height?: number }) {
  const rows = block.rows ?? [];
  const dimension = dimensionKey(block);
  const measure = measureEntry(block);
  const key = String(measure?.id || "contagem");
  const format = String(measure?.format || "");
  const data = rows.slice(0, 24).map((row) => ({
    label: String(row?.[dimension] ?? "—"),
    value: valueOf(row, key),
  }));

  if (!data.length) {
    return <p className="py-8 text-center text-xs text-muted-foreground">Sem dados para este gráfico.</p>;
  }

  const tooltipFormatter = (value: unknown) => [studioNumber(value, format), measure?.label || key];
  const chart = String(block.chart || "bar");

  if (chart === "donut" || chart === "pie") {
    const total = data.reduce((sum, item) => sum + item.value, 0) || 1;
    return (
      <div className="flex flex-col items-center gap-2 sm:flex-row">
        <ResponsiveContainer width="100%" height={height}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="label" innerRadius={chart === "donut" ? "55%" : 0} outerRadius="80%" stroke="none">
              {data.map((entry, index) => (
                <Cell key={entry.label} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
          </PieChart>
        </ResponsiveContainer>
        <ul className="w-full space-y-1 text-[11px] sm:w-56">
          {data.map((entry, index) => (
            <li key={entry.label} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CHART_COLORS[index % CHART_COLORS.length] }} />
                <span className="truncate">{entry.label}</span>
              </span>
              <span className="shrink-0 text-muted-foreground">{((entry.value / total) * 100).toFixed(0)} %</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" />
      <XAxis dataKey="label" tick={{ fontSize: 10 }} tickFormatter={axisTick} />
      <YAxis tick={{ fontSize: 10 }} tickFormatter={(value) => studioCompact(Number(value))} width={54} />
      <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
    </>
  );

  if (chart === "line") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          {common}
          <Line type="monotone" dataKey="value" stroke={CHART_COLORS[0]} strokeWidth={2} dot={{ r: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (chart === "area") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          {common}
          <Area type="monotone" dataKey="value" stroke={CHART_COLORS[0]} fill={CHART_COLORS[0]} fillOpacity={0.25} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={chart === "bar-h" ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        {chart === "bar-h" ? (
          <>
            <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(value) => studioCompact(Number(value))} />
            <YAxis type="category" dataKey="label" tick={{ fontSize: 10 }} tickFormatter={axisTick} width={116} />
          </>
        ) : (
          common
        )}
        <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
        <Bar dataKey="value" fill={CHART_COLORS[0]} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---------------------------------------------------------------------------
// Grafo de relações
// ---------------------------------------------------------------------------
export function StudioGraph({ block }: { block: StudioRunBlock }) {
  const graph = block.graph;
  const edges = (graph?.edges ?? []).slice(0, 12);
  if (!edges.length) {
    return <p className="py-8 text-center text-xs text-muted-foreground">Sem relações para representar.</p>;
  }
  const origins = Array.from(new Set(edges.map((edge) => edge.source))).slice(0, 8);
  const targets = Array.from(new Set(edges.map((edge) => edge.target))).slice(0, 8);
  const maximum = Math.max(...edges.map((edge) => Number(edge.value) || 0)) || 1;
  const height = Math.max(220, Math.max(origins.length, targets.length) * 30);
  const step = (index: number, count: number) => 26 + (height - 52) * (count <= 1 ? 0.5 : index / (count - 1));
  const format = String(measureEntry(block)?.format || "");
  const label = (value: string) => (value.length > 22 ? `${value.slice(0, 21)}…` : value);

  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 640 ${height}`} className="w-full" role="img" aria-label={block.title || "Grafo de relações"}>
        {edges.map((edge) => {
          const from = origins.indexOf(edge.source);
          const to = targets.indexOf(edge.target);
          if (from < 0 || to < 0) return null;
          const width = 0.5 + (Number(edge.value) / maximum) * 2.4;
          return (
            <line
              key={`${edge.source}-${edge.target}`}
              x1={168}
              y1={step(from, origins.length)}
              x2={472}
              y2={step(to, targets.length)}
              stroke="#94a3b8"
              strokeWidth={width}
              strokeOpacity={0.55}
            />
          );
        })}
        {origins.map((name, index) => (
          <g key={`o-${name}`}>
            <circle cx={164} cy={step(index, origins.length)} r={4} fill={CHART_COLORS[0]} />
            <text x={156} y={step(index, origins.length) + 3} textAnchor="end" fontSize={10} fill="#94a3b8">
              {label(name)}
            </text>
          </g>
        ))}
        {targets.map((name, index) => (
          <g key={`t-${name}`}>
            <circle cx={476} cy={step(index, targets.length)} r={4} fill={CHART_COLORS[1]} />
            <text x={484} y={step(index, targets.length) + 3} fontSize={10} fill="#94a3b8">
              {label(name)}
            </text>
          </g>
        ))}
      </svg>
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ background: CHART_COLORS[0] }} />
          {graph?.labels?.origin || "Origem"}
        </span>
        <ArrowRight size={12} />
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full" style={{ background: CHART_COLORS[1] }} />
          {graph?.labels?.target || "Destino"}
        </span>
      </div>
      <ul className="grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
        {edges.slice(0, 8).map((edge) => (
          <li key={`l-${edge.source}-${edge.target}`} className="flex items-center justify-between gap-2">
            <span className="truncate">
              {edge.source} <ArrowRight size={10} className="inline" /> {edge.target}
            </span>
            <span className="shrink-0">{studioNumber(edge.value, format)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pré-visualização de um bloco
// ---------------------------------------------------------------------------
export function BlockPreview({
  block,
  result,
  running,
}: {
  block: { title: string; type: string; text?: string };
  result?: StudioRunBlock;
  running?: boolean;
}) {
  if (running && !result) {
    return (
      <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A calcular…
      </div>
    );
  }
  if (result?.error) {
    return (
      <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
        <AlertCircle size={14} className="mt-0.5 shrink-0" /> {result.error}
      </p>
    );
  }
  if (block.type === "chart" && result) return <StudioChart block={result} />;
  if (block.type === "graph" && result) return <StudioGraph block={result} />;
  if (block.type === "table" && result) {
    const columns = result.columns ?? [];
    const rows = (result.rows ?? []).slice(0, 40);
    if (!columns.length || !rows.length) {
      return <p className="py-6 text-center text-xs text-muted-foreground">Sem dados para esta tabela.</p>;
    }
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              {columns.map((column) => (
                <th key={column.key} className="px-2 py-1.5 font-medium">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-b border-border/40">
                {columns.map((column) => (
                  <td key={column.key} className="px-2 py-1.5">
                    {column.type === "dimension" ? String(row?.[column.key] ?? "—") : studioNumber(row?.[column.key], String(column.format || ""))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (block.type === "kpi" && result) {
    const measures = result.measures ?? [];
    if (!measures.length) return null;
    return (
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {measures.map((measure) => (
          <div key={measure.id} className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-3 py-2">
            <p className="text-[11px] text-muted-foreground">{measure.label}</p>
            <p className="text-lg font-semibold text-emerald-400">
              {studioNumber(result.totals?.[measure.id], String(measure.format || ""))}
            </p>
          </div>
        ))}
      </div>
    );
  }
  const text = String(result?.text ?? block.text ?? "");
  if (!text) {
    return <p className="py-4 text-xs text-muted-foreground">Sem texto. Escreva ou peça à IA para redigir.</p>;
  }
  return <p className="whitespace-pre-wrap text-sm text-muted-foreground">{text}</p>;
}

/** Cartão de um bloco com o resultado já desenhado. */
export function BlockCard({
  title,
  type,
  result,
  running,
  actions,
  children,
}: {
  title: string;
  type: string;
  result?: StudioRunBlock;
  running?: boolean;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const labels: Record<string, string> = {
    heading: "Secção",
    text: "Texto",
    note: "Nota",
    ai: "IA",
    kpi: "Indicadores",
    chart: "Gráfico",
    table: "Tabela",
    graph: "Grafo",
  };
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex min-w-0 items-center gap-2 text-sm">
          <span className="truncate">{title || labels[type] || type}</span>
          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {labels[type] || type}
          </span>
        </CardTitle>
        {actions}
      </CardHeader>
      <CardContent className="space-y-2">
        <BlockPreview block={{ title, type, text: result?.text }} result={result} running={running} />
        {children}
      </CardContent>
    </Card>
  );
}
