/**
 * Treemap (squarified) para comparar magnitudes — a área representa a métrica
 * escolhida. Construído em SVG, com medição do contentor.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphMetric, StudioNode } from "./graphStudio";
import { formatCompact, formatMoney, typeLabel } from "./graphStudio";

type Rect = { node: StudioNode; x: number; y: number; w: number; h: number };

/** Layout squarified simplificado: divide faixas e mantém as proporções próximas de 1. */
function squarify(nodes: StudioNode[], x: number, y: number, w: number, h: number): Rect[] {
  const total = nodes.reduce((acc, node) => acc + node.value, 0) || 1;
  const rects: Rect[] = [];
  let remaining = [...nodes];
  let boxX = x;
  let boxY = y;
  let boxW = w;
  let boxH = h;
  let remainingTotal = total;

  while (remaining.length > 0) {
    const horizontal = boxW >= boxH;
    const side = horizontal ? boxH : boxW;
    const row: StudioNode[] = [];
    let rowTotal = 0;

    while (remaining.length > 0) {
      const candidate = remaining[0];
      const candidateTotal = rowTotal + candidate.value;
      const rowWidth = (candidateTotal / remainingTotal) * (horizontal ? boxW : boxH);
      const worst = (() => {
        const items = [...row, candidate];
        const rowThickness = rowWidth || 1;
        return Math.max(
          ...items.map((item) => {
            const length = ((item.value / candidateTotal) * side) || 1;
            return Math.max(rowThickness / length, length / rowThickness);
          }),
        );
      })();
      const currentWorst = row.length === 0
        ? Number.POSITIVE_INFINITY
        : (() => {
            const rowWidthBefore = (rowTotal / remainingTotal) * (horizontal ? boxW : boxH) || 1;
            return Math.max(
              ...row.map((item) => {
                const length = ((item.value / rowTotal) * side) || 1;
                return Math.max(rowWidthBefore / length, length / rowWidthBefore);
              }),
            );
          })();
      if (row.length > 0 && worst > currentWorst) break;
      row.push(candidate);
      rowTotal = candidateTotal;
      remaining = remaining.slice(1);
    }

    const rowThickness = (rowTotal / remainingTotal) * (horizontal ? boxW : boxH);
    let cursor = horizontal ? boxY : boxX;
    row.forEach((node) => {
      const length = (node.value / rowTotal) * side;
      rects.push(
        horizontal
          ? { node, x: boxX, y: cursor, w: rowThickness, h: length }
          : { node, x: cursor, y: boxY, w: length, h: rowThickness },
      );
      cursor += length;
    });

    if (horizontal) {
      boxX += rowThickness;
      boxW = Math.max(1, boxW - rowThickness);
    } else {
      boxY += rowThickness;
      boxH = Math.max(1, boxH - rowThickness);
    }
    remainingTotal = Math.max(0, remainingTotal - rowTotal);
    if (remainingTotal <= 0 || boxW < 2 || boxH < 2) break;
  }
  return rects;
}

export function TreemapChart({
  nodes,
  metric,
  height = 460,
  onNodeClick,
}: {
  nodes: StudioNode[];
  metric: GraphMetric;
  height?: number;
  onNodeClick?: (node: StudioNode) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(900);
  const [hovered, setHovered] = useState<StudioNode | null>(null);
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

  const rects = useMemo(() => {
    const sorted = [...nodes].sort((a, b) => b.value - a.value).slice(0, 40);
    if (sorted.length === 0) return [];
    return squarify(sorted, 0, 0, width, height);
  }, [height, nodes, width]);

  const total = nodes.reduce((acc, node) => acc + node.value, 0);
  const hint = metric === "valor" ? "área = valor contratado" : "área = nº de contratos";

  return (
    <div
      ref={wrapperRef}
      className="relative w-full"
      style={{ height }}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        setMouse({ x: event.clientX - rect.left, y: event.clientY - rect.top });
      }}
    >
      <svg width={width} height={height} className="rounded-xl bg-[#07151b]" role="img" aria-label={`Treemap de ${nodes.length} nós, ${hint}`}>
        {rects.length === 0 && (
          <text x={width / 2} y={height / 2} textAnchor="middle" className="fill-slate-400" fontSize={13}>
            Sem dados para representar
          </text>
        )}
        {rects.map((rect) => {
          const active = hovered?.id === rect.node.id;
          const share = total > 0 ? (rect.node.value / total) * 100 : 0;
          return (
            <g key={rect.node.id}>
              <rect
                x={rect.x + 1}
                y={rect.y + 1}
                width={Math.max(0, rect.w - 2)}
                height={Math.max(0, rect.h - 2)}
                rx={4}
                fill={rect.node.color}
                fillOpacity={active ? 0.85 : 0.45}
                stroke={active ? "#fbbf24" : "rgba(7,21,27,0.9)"}
                strokeWidth={active ? 2 : 1}
                className="cursor-pointer"
                onMouseEnter={() => setHovered(rect.node)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onNodeClick?.(rect.node)}
              />
              {rect.w > 86 && rect.h > 30 && (
                <>
                  <text x={rect.x + 8} y={rect.y + 18} fontSize={11} className="fill-white">
                    {rect.node.label.length > Math.floor(rect.w / 7) ? `${rect.node.label.slice(0, Math.floor(rect.w / 7))}…` : rect.node.label}
                  </text>
                  <text x={rect.x + 8} y={rect.y + 32} fontSize={10} className="fill-slate-300">
                    {metric === "valor" ? formatMoney(rect.node.total_value) : `${formatCompact(rect.node.count)} contratos`} ·{" "}
                    {share.toFixed(1)}%
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>

      <span className="pointer-events-none absolute bottom-2 right-3 rounded-lg border border-white/10 bg-[#07151b]/85 px-2 py-1 text-[10px] text-muted-foreground">
        {hint}
      </span>

      {hovered && (
        <div
          className="pointer-events-none absolute z-20 w-[230px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl"
          style={{ left: Math.min(mouse.x + 14, Math.max(width - 240, 8)), top: Math.max(mouse.y + 14, 8) }}
        >
          <p className="text-sm text-foreground break-words">{hovered.label}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{typeLabel(hovered.type)}</p>
          <p className="mt-1 text-xs text-teal-300">
            {formatCompact(hovered.count)} contratos · {formatMoney(hovered.total_value)}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {total > 0 ? `${((hovered.value / total) * 100).toFixed(1)}% do total representado` : ""}
          </p>
        </div>
      )}
    </div>
  );
}
