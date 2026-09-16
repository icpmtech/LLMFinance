/**
 * Diagrama de Sankey (dois níveis) para fluxos de valor entre dimensões.
 * Construído em SVG com medição do contentor, sem dependências externas.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphMetric, StudioEdge, StudioNode } from "./graphStudio";
import { formatCompact, formatMoney } from "./graphStudio";

type Flow = {
  edge: StudioEdge;
  source: StudioNode;
  target: StudioNode;
  value: number;
};

type Block = { node: StudioNode; height: number; y: number };

const NODE_WIDTH = 14;
const NODE_GAP = 8;

function ribbonPath(x0: number, y0: number, x1: number, y1: number, width: number) {
  const half = Math.max(width / 2, 0.5);
  const midX = (x0 + x1) / 2;
  return [
    `M ${x0} ${y0 - half}`,
    `C ${midX} ${y0 - half}, ${midX} ${y1 - half}, ${x1} ${y1 - half}`,
    `L ${x1} ${y1 + half}`,
    `C ${midX} ${y1 + half}, ${midX} ${y0 + half}, ${x0} ${y0 + half}`,
    "Z",
  ].join(" ");
}

export function SankeyDiagram({
  nodes,
  edges,
  metric,
  height = 460,
  onNodeClick,
}: {
  nodes: StudioNode[];
  edges: StudioEdge[];
  metric: GraphMetric;
  height?: number;
  onNodeClick?: (node: StudioNode) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(900);
  const [hovered, setHovered] = useState<{ kind: "flow"; flow: Flow } | { kind: "node"; node: StudioNode } | null>(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const measure = () => setWidth(wrapper.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  const model = useMemo(() => {
    if (nodes.length === 0 || edges.length === 0) return null;
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const flows: Flow[] = edges
      .map((edge) => ({
        edge,
        source: byId.get(edge.source),
        target: byId.get(edge.target),
        value: metric === "valor" ? edge.value : edge.count,
      }))
      .filter((flow): flow is Flow => Boolean(flow.source && flow.target) && flow.value > 0)
      .sort((a, b) => b.value - a.value);

    if (flows.length === 0) return null;

    const total = flows.reduce((acc, flow) => acc + flow.value, 0) || 1;
    const usable = Math.max(160, height - 60);
    const scale = usable / total;

    const buildBlocks = (side: "source" | "target") => {
      const totals = new Map<string, number>();
      flows.forEach((flow) => {
        const key = side === "source" ? flow.source.id : flow.target.id;
        totals.set(key, (totals.get(key) ?? 0) + flow.value);
      });
      const entries = [...totals.entries()].sort((a, b) => b[1] - a[1]);
      const gapTotal = Math.max(0, entries.length - 1) * NODE_GAP;
      const slack = Math.max(0, usable - gapTotal - total * scale);
      const blocks = new Map<string, Block>();
      let cursor = 30 + slack / 2;
      entries.forEach(([id, nodeTotal]) => {
        const node = byId.get(id);
        if (!node) return;
        const blockHeight = Math.max(6, nodeTotal * scale);
        blocks.set(id, { node, height: blockHeight, y: cursor });
        cursor += blockHeight + NODE_GAP;
      });
      return blocks;
    };

    const sourceBlocks = buildBlocks("source");
    const targetBlocks = buildBlocks("target");
    const sourceCursor = new Map<string, number>();
    const targetCursor = new Map<string, number>();
    const ribbons: { flow: Flow; y0: number; y1: number; thickness: number }[] = [];
    flows.forEach((flow) => {
      const source = sourceBlocks.get(flow.source.id);
      const target = targetBlocks.get(flow.target.id);
      if (!source || !target) return;
      const thickness = Math.max(1.5, flow.value * scale);
      const sourceOffset = sourceCursor.get(flow.source.id) ?? 0;
      const targetOffset = targetCursor.get(flow.target.id) ?? 0;
      ribbons.push({
        flow,
        y0: source.y + sourceOffset + thickness / 2,
        y1: target.y + targetOffset + thickness / 2,
        thickness,
      });
      sourceCursor.set(flow.source.id, sourceOffset + thickness);
      targetCursor.set(flow.target.id, targetOffset + thickness);
    });

    return {
      sourceBlocks: [...sourceBlocks.values()],
      targetBlocks: [...targetBlocks.values()],
      ribbons,
      metricTotal: metric === "valor"
        ? flows.reduce((acc, flow) => acc + flow.edge.value, 0)
        : flows.reduce((acc, flow) => acc + flow.edge.count, 0),
    };
  }, [edges, height, metric, nodes]);

  const left = 190;
  const right = Math.max(left + 120, width - 210);

  return (
    <div ref={wrapperRef} className="relative w-full" style={{ height }}>
      <svg
        width={width}
        height={height}
        className="rounded-xl bg-[#07151b]"
        role="img"
        aria-label={`Diagrama de fluxo com ${nodes.length} nós`}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setMouse({ x: event.clientX - rect.left, y: event.clientY - rect.top });
        }}
      >
        {!model && (
          <text x={width / 2} y={height / 2} textAnchor="middle" className="fill-slate-400" fontSize={13}>
            Sem fluxos para as dimensões escolhidas
          </text>
        )}

        {model?.ribbons.map((ribbon) => {
          const key = `${ribbon.flow.edge.source}->${ribbon.flow.edge.target}`;
          const active = hovered?.kind === "flow" && `${hovered.flow.edge.source}->${hovered.flow.edge.target}` === key;
          return (
            <path
              key={key}
              d={ribbonPath(left + NODE_WIDTH, ribbon.y0, right, ribbon.y1, ribbon.thickness)}
              fill={ribbon.flow.source.color}
              fillOpacity={active ? 0.75 : 0.28}
              stroke={active ? "rgba(251,191,36,0.9)" : "transparent"}
              strokeWidth={1}
              onMouseEnter={() => setHovered({ kind: "flow", flow: ribbon.flow })}
              onMouseLeave={() => setHovered(null)}
            />
          );
        })}

        {model?.sourceBlocks.map((block) => (
          <g key={block.node.id}>
            <rect
              x={left}
              y={block.y}
              width={NODE_WIDTH}
              height={block.height}
              rx={3}
              fill={block.node.color}
              className="cursor-pointer"
              onMouseEnter={() => setHovered({ kind: "node", node: block.node })}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onNodeClick?.(block.node)}
            />
            <text x={left - 8} y={block.y + block.height / 2 + 4} textAnchor="end" fontSize={11} className="fill-slate-300">
              {block.node.label.length > 26 ? `${block.node.label.slice(0, 24)}…` : block.node.label}
            </text>
          </g>
        ))}

        {model?.targetBlocks.map((block) => (
          <g key={block.node.id}>
            <rect
              x={right}
              y={block.y}
              width={NODE_WIDTH}
              height={block.height}
              rx={3}
              fill={block.node.color}
              className="cursor-pointer"
              onMouseEnter={() => setHovered({ kind: "node", node: block.node })}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onNodeClick?.(block.node)}
            />
            <text x={right + NODE_WIDTH + 8} y={block.y + block.height / 2 + 4} fontSize={11} className="fill-slate-300">
              {block.node.label.length > 26 ? `${block.node.label.slice(0, 24)}…` : block.node.label}
            </text>
          </g>
        ))}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute z-20 w-[230px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl"
          style={{ left: Math.min(mouse.x + 14, Math.max(width - 240, 8)), top: Math.max(mouse.y + 14, 8) }}
        >
          {hovered.kind === "node" ? (
            <>
              <p className="text-sm text-foreground break-words">{hovered.node.label}</p>
              <p className="mt-1 text-xs text-teal-300">
                {formatCompact(hovered.node.count)} contratos · {formatMoney(hovered.node.total_value)}
              </p>
            </>
          ) : (
            <>
              <p className="text-xs text-teal-300 break-words">{hovered.flow.source.label}</p>
              <p className="text-xs text-blue-300 break-words">→ {hovered.flow.target.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatCompact(hovered.flow.edge.count)} contratos · {formatMoney(hovered.flow.edge.value)}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
