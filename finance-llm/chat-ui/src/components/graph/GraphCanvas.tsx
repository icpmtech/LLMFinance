/**
 * Canvas de grafo reutilizável (rede orgânica, hierárquica e circular).
 *
 * Princípios aplicados:
 * - posições num ref mutável, separadas do desenho (hover/zoom não reiniciam o layout);
 * - simulação de forças com grelha espacial (escala para centenas de nós);
 * - contexto escalado por DPR (desenho e hit-test partilham as mesmas coordenadas);
 * - enquadramento automático até o utilizador interagir;
 * - etiquetas com orçamento por centralidade e deteção de colisões;
 * - teclado (setas, +/- e 0) e região de anúncio para leitores de ecrã.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Scan, ZoomIn, ZoomOut } from "lucide-react";
import type { GraphMetric, StudioEdge, StudioGraph, StudioNode } from "./graphStudio";
import { formatMoney, formatCompact, metricLabel } from "./graphStudio";

type Layout = "network" | "hierarchical" | "circular";

type NodePosition = { x: number; y: number; vx: number; vy: number };

const CELL = 170;
const REPULSION = 2400;
const LINK_DISTANCE = 110;

function seedPosition(index: number, count: number, groupIndex = 0, groupCount = 1): NodePosition {
  if (groupCount > 1) {
    const groupAngle = (groupIndex / groupCount) * Math.PI * 2;
    const localAngle = (index / Math.max(count, 1)) * Math.PI * 2;
    return {
      x: Math.cos(groupAngle) * 200 + Math.cos(localAngle) * 48,
      y: Math.sin(groupAngle) * 200 + Math.sin(localAngle) * 48,
      vx: 0,
      vy: 0,
    };
  }
  const angle = (index / Math.max(count, 1)) * Math.PI * 2;
  return { x: Math.cos(angle) * 140, y: Math.sin(angle) * 140, vx: 0, vy: 0 };
}

export function GraphCanvas({
  graph,
  layout,
  metric,
  selectedNodeId,
  layoutVersion = 0,
  loading = false,
  heightClass = "h-[560px]",
  onNodeClick,
  onEdgeClick,
}: {
  graph: StudioGraph | null;
  layout: Layout;
  metric: GraphMetric;
  selectedNodeId?: string | null;
  layoutVersion?: number;
  loading?: boolean;
  heightClass?: string;
  onNodeClick?: (node: StudioNode) => void;
  onEdgeClick?: (edge: StudioEdge) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const positionsRef = useRef(new Map<string, NodePosition>());
  const fitToViewRef = useRef<(() => void) | null>(null);
  const draggingRef = useRef(false);
  const dragMovedRef = useRef(false);
  const userMovedRef = useRef(false);
  const layoutVersionRef = useRef(layoutVersion);
  const lastPointerRef = useRef({ x: 0, y: 0 });

  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hovered, setHovered] = useState<StudioNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<StudioEdge | null>(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });
  const [settled, setSettled] = useState(false);

  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = useMemo(() => graph?.edges ?? [], [graph]);

  const labelledIds = useMemo(
    () =>
      new Set(
        [...nodes]
          .sort((a, b) => b.value - a.value)
          .slice(0, layout === "circular" ? 16 : 12)
          .map((node) => node.id),
      ),
    [nodes, layout],
  );

  const layoutKey = useMemo(() => {
    const ids = nodes.map((node) => node.id).sort().join("|");
    const links = edges.map((edge) => `${edge.source}>${edge.target}`).sort().join("|");
    return `${layout}#${layoutVersion}#${metric}#${ids}#${links}`;
  }, [edges, layout, layoutVersion, metric, nodes]);

  const frame = useRef({
    nodes,
    edges,
    scale,
    offset,
    hovered,
    hoveredEdge,
    selectedNodeId,
    labelledIds,
  });

  useEffect(() => {
    frame.current = { nodes, edges, scale, offset, hovered, hoveredEdge, selectedNodeId, labelledIds };
  });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const current = frame.current;
    const positions = positionsRef.current;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.width / dpr;
    const height = rect.height || canvas.height / dpr;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (current.nodes.length === 0) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.translate(width / 2 + current.offset.x, height / 2 + current.offset.y);
    ctx.scale(current.scale, current.scale);

    const hoveredEdgeKey = current.hoveredEdge
      ? [current.hoveredEdge.source, current.hoveredEdge.target].sort().join("|")
      : null;

    current.edges.forEach((edge) => {
      const a = positions.get(edge.source);
      const b = positions.get(edge.target);
      if (!a || !b) return;
      const key = [edge.source, edge.target].sort().join("|");
      const active = key === hoveredEdgeKey;
      const alpha = 0.12 + edge.weight * 0.6;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = active ? `rgba(251,191,36,${Math.min(0.95, alpha + 0.3)})` : `rgba(125,211,252,${alpha})`;
      ctx.lineWidth = 1 + edge.weight * 5;
      ctx.stroke();
    });

    const boxes: { x: number; y: number; w: number; h: number }[] = [];
    const drawLabel = (text: string, x: number, y: number, emphasised: boolean) => {
      ctx.font = emphasised ? "bold 12px ui-sans-serif, system-ui" : "600 10px ui-sans-serif, system-ui";
      const label = text.length > 26 ? `${text.slice(0, 24)}…` : text;
      const box = { x: x - 4, y: y - 10, w: ctx.measureText(label).width + 8, h: 16 };
      const collides = boxes.some(
        (other) =>
          !(
            box.x + box.w < other.x ||
            other.x + other.w < box.x ||
            box.y + box.h < other.y ||
            other.y + other.h < box.y
          ),
      );
      if (collides && !emphasised) return;
      boxes.push(box);
      ctx.fillStyle = "rgba(3,12,17,0.86)";
      ctx.fillRect(box.x, box.y, box.w, box.h);
      ctx.fillStyle = emphasised ? "#ffffff" : "#dbeafe";
      ctx.fillText(label, x, y);
    };

    current.nodes.forEach((node) => {
      const p = positions.get(node.id);
      if (!p) return;
      const isSelected = current.selectedNodeId === node.id;
      const isHovered = current.hovered?.id === node.id;
      const radius = isSelected ? node.radius + 5 : isHovered ? node.radius + 3 : node.radius;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.shadowBlur = isSelected || isHovered ? 20 : 9;
      ctx.shadowColor = node.color;
      const fill = ctx.createRadialGradient(p.x - radius * 0.35, p.y - radius * 0.35, 1, p.x, p.y, radius);
      fill.addColorStop(0, node.color);
      fill.addColorStop(0.4, `${node.color}cc`);
      fill.addColorStop(1, "rgba(7,21,27,0.98)");
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = isSelected ? 4 : isHovered ? 3.5 : 2.5;
      ctx.strokeStyle = isSelected || isHovered ? "#ffffff" : node.color;
      ctx.stroke();
      if (isSelected || isHovered || current.labelledIds.has(node.id)) {
        drawLabel(node.label, p.x + radius + 6, p.y + 3, isSelected || isHovered);
      }
    });
  }, []);

  // Dimensionamento (ResizeObserver) + reenquadramento automático.
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const applySize = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = wrapper.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextWidth = Math.max(1, Math.floor(rect.width * dpr));
      const nextHeight = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }
      setSize((current) =>
        current.width === rect.width && current.height === rect.height
          ? current
          : { width: rect.width, height: rect.height },
      );
      if (!userMovedRef.current && positionsRef.current.size > 0) {
        fitToViewRef.current?.();
      }
      draw();
    };
    applySize();
    const observer = new ResizeObserver(applySize);
    observer.observe(wrapper);
    window.addEventListener("resize", applySize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", applySize);
    };
  }, [draw, layoutKey]);

  const fitToView = useCallback(() => {
    const canvas = canvasRef.current;
    const positions = positionsRef.current;
    const visible = frame.current.nodes;
    if (!canvas || visible.length === 0) return;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    visible.forEach((node) => {
      const p = positions.get(node.id);
      if (!p) return;
      minX = Math.min(minX, p.x - node.radius);
      maxX = Math.max(maxX, p.x + node.radius);
      minY = Math.min(minY, p.y - node.radius);
      maxY = Math.max(maxY, p.y + node.radius);
    });
    if (!Number.isFinite(minX)) return;
    const rect = canvas.getBoundingClientRect();
    const availableWidth = Math.max(120, rect.width - 120);
    const availableHeight = Math.max(120, rect.height - 96);
    const nextScale = Math.min(
      2.2,
      Math.max(
        0.3,
        Math.min(availableWidth / Math.max(maxX - minX, 1), availableHeight / Math.max(maxY - minY, 1)),
      ),
    );
    setScale(nextScale);
    setOffset({ x: -((minX + maxX) / 2) * nextScale, y: -((minY + maxY) / 2) * nextScale });
  }, []);

  fitToViewRef.current = fitToView;

  // Layout: determinístico (circular/hierárquico) ou simulação de forças.
  useEffect(() => {
    if (nodes.length === 0) return;
    // "Recalcular layout" (layoutVersion) reinicia as posições: tem de ser feito AQUI,
    // antes de semear — um efeito separado correria depois do layout e deixaria o grafo vazio.
    if (layoutVersionRef.current !== layoutVersion) {
      layoutVersionRef.current = layoutVersion;
      userMovedRef.current = false;
      positionsRef.current.clear();
    }
    setSettled(false);
    const positions = positionsRef.current;
    const activeIds = new Set(nodes.map((node) => node.id));
    positions.forEach((_position, id) => {
      if (!activeIds.has(id)) positions.delete(id);
    });

    const canvas = canvasRef.current;
    const rect = canvas?.getBoundingClientRect();
    const width = rect?.width ?? 900;
    const height = rect?.height ?? 560;

    const applyDeterministic = () => {
      if (layout === "circular") {
        const ordered = [...nodes].sort((a, b) => b.value - a.value);
        const radius = Math.max(140, Math.min(340, Math.min(width, height) * 0.38));
        ordered.forEach((node, index) => {
          const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2 - Math.PI / 2;
          positions.set(node.id, {
            x: Math.cos(angle) * radius,
            y: Math.sin(angle) * radius,
            vx: 0,
            vy: 0,
          });
        });
        return;
      }
      const lanes = [...new Set(nodes.map((node) => node.type))];
      lanes.forEach((lane, laneIndex) => {
        const laneNodes = nodes.filter((node) => node.type === lane);
        const spacing = Math.max(58, Math.min(190, width / Math.max(laneNodes.length, 1)));
        laneNodes.forEach((node, index) => {
          positions.set(node.id, {
            x: (index - (laneNodes.length - 1) / 2) * spacing,
            y: (laneIndex - (lanes.length - 1) / 2) * Math.max(140, height / (lanes.length + 1)),
            vx: 0,
            vy: 0,
          });
        });
      });
    };

    if (layout !== "network") {
      applyDeterministic();
      draw();
      if (!userMovedRef.current) fitToView();
      setSettled(true);
      return;
    }

    nodes.forEach((node, index) => {
      if (!positions.has(node.id)) positions.set(node.id, seedPosition(index, nodes.length));
    });

    const runStep = () => {
      const grid = new Map<string, StudioNode[]>();
      nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        const key = `${Math.floor(p.x / CELL)}:${Math.floor(p.y / CELL)}`;
        const bucket = grid.get(key) ?? [];
        bucket.push(node);
        grid.set(key, bucket);
      });
      nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        const cx = Math.floor(p.x / CELL);
        const cy = Math.floor(p.y / CELL);
        for (let gx = cx - 1; gx <= cx + 1; gx++) {
          for (let gy = cy - 1; gy <= cy + 1; gy++) {
            const bucket = grid.get(`${gx}:${gy}`);
            if (!bucket) continue;
            bucket.forEach((other) => {
              if (other.id <= node.id) return;
              const q = positions.get(other.id);
              if (!q) return;
              const dx = p.x - q.x;
              const dy = p.y - q.y;
              const dist = Math.sqrt(dx * dx + dy * dy) || 1;
              if (dist > CELL * 3) return;
              const force = REPULSION / (dist * dist);
              p.vx += (dx / dist) * force;
              p.vy += (dy / dist) * force;
              q.vx -= (dx / dist) * force;
              q.vy -= (dy / dist) * force;
            });
          }
        }
      });
      edges.forEach((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = ((dist - LINK_DISTANCE) * 0.03) / 2;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });
      let energy = 0;
      nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        p.vx = (p.vx - p.x * 0.003) * 0.88;
        p.vy = (p.vy - p.y * 0.003) * 0.88;
        p.x += p.vx;
        p.y += p.vy;
        energy += Math.abs(p.vx) + Math.abs(p.vy);
      });
      return energy / Math.max(nodes.length, 1);
    };

    const reduceMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
    if (reduceMotion) {
      for (let tick = 0; tick < 320; tick++) runStep();
      draw();
      if (!userMovedRef.current) fitToView();
      setSettled(true);
      return;
    }

    let raf = 0;
    let ticks = 0;
    // Grafos grandes: menos iterações para a vista ficar utilizável depressa.
    const maxTicks = nodes.length > 1500 ? 140 : nodes.length > 700 ? 260 : 420;
    const loop = () => {
      const energy = runStep();
      draw();
      ticks += 1;
      if (ticks < maxTicks && Number.isFinite(energy) && energy > 0.4) {
        raf = requestAnimationFrame(loop);
      } else {
        if (!userMovedRef.current) fitToView();
        setSettled(true);
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw, fitToView, layoutKey, layoutVersion]);

  useEffect(() => {
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw, nodes, edges, hovered, hoveredEdge, scale, offset, size, selectedNodeId, labelledIds]);

  // Zoom com scroll sem arrastar a página.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      userMovedRef.current = true;
      setScale((current) => Math.min(3, Math.max(0.3, current - event.deltaY * 0.0015)));
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  const toGraphCoords = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: (clientX - rect.left - rect.width / 2 - offset.x) / scale,
      y: (clientY - rect.top - rect.height / 2 - offset.y) / scale,
    };
  };

  const hitNode = (x: number, y: number) => {
    const positions = positionsRef.current;
    return (
      frame.current.nodes.find((node) => {
        const p = positions.get(node.id);
        return p ? Math.hypot(p.x - x, p.y - y) <= node.radius + 5 : false;
      }) ?? null
    );
  };

  const hitEdge = (x: number, y: number) => {
    const positions = positionsRef.current;
    return (
      frame.current.edges.find((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return false;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const lengthSquared = dx * dx + dy * dy || 1;
        const projection = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / lengthSquared));
        return Math.hypot(x - (a.x + projection * dx), y - (a.y + projection * dy)) <= 8 / Math.max(scale, 0.3);
      }) ?? null
    );
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (draggingRef.current) {
      const dx = event.clientX - lastPointerRef.current.x;
      const dy = event.clientY - lastPointerRef.current.y;
      lastPointerRef.current = { x: event.clientX, y: event.clientY };
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        dragMovedRef.current = true;
        userMovedRef.current = true;
        setOffset((current) => ({ x: current.x + dx, y: current.y + dy }));
      }
      return;
    }
    const point = toGraphCoords(event.clientX, event.clientY);
    const node = hitNode(point.x, point.y);
    const edge = node ? null : hitEdge(point.x, point.y);
    if ((node?.id ?? null) !== (hovered?.id ?? null)) setHovered(node);
    if (edge !== hoveredEdge) setHoveredEdge(edge);
    if (node || edge) {
      const rect = canvas.getBoundingClientRect();
      setMouse({ x: event.clientX - rect.left, y: event.clientY - rect.top });
    }
  };

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragMovedRef.current) return;
    const point = toGraphCoords(event.clientX, event.clientY);
    const node = hitNode(point.x, point.y);
    if (node) {
      onNodeClick?.(node);
      return;
    }
    const edge = hitEdge(point.x, point.y);
    if (edge) onEdgeClick?.(edge);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLCanvasElement>) => {
    const step = 48;
    const pan = (dx: number, dy: number) => {
      event.preventDefault();
      userMovedRef.current = true;
      setOffset((current) => ({ x: current.x + dx, y: current.y + dy }));
    };
    if (event.key === "ArrowLeft") pan(step, 0);
    else if (event.key === "ArrowRight") pan(-step, 0);
    else if (event.key === "ArrowUp") pan(0, step);
    else if (event.key === "ArrowDown") pan(0, -step);
    else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      setScale((current) => Math.min(3, current + 0.15));
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      setScale((current) => Math.max(0.3, current - 0.15));
    } else if (event.key === "0") {
      event.preventDefault();
      userMovedRef.current = true;
      fitToView();
    }
  };

  const tooltipVisible = Boolean(hovered || hoveredEdge);
  const tooltipStyle = {
    left: Math.max(8, Math.min(mouse.x + 16, Math.max(size.width - 250, 8))),
    top: Math.max(8, Math.min(mouse.y + 16, Math.max(size.height - 120, 8))),
  };

  return (
    <div ref={wrapperRef} className={`relative w-full ${heightClass}`}>
      <canvas
        ref={canvasRef}
        role="img"
        tabIndex={0}
        aria-label={`Grafo com ${nodes.length} nós e ${edges.length} ligações. Setas para mover, mais e menos para zoom, zero para ajustar à vista.`}
        className={`h-full w-full rounded-xl bg-[#07151b] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-400/50 ${
          tooltipVisible ? "cursor-pointer" : "cursor-move"
        }`}
        onPointerDown={(event) => {
          draggingRef.current = true;
          dragMovedRef.current = false;
          lastPointerRef.current = { x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={handlePointerMove}
        onPointerUp={(event) => {
          draggingRef.current = false;
          event.currentTarget.releasePointerCapture?.(event.pointerId);
        }}
        onPointerLeave={() => {
          draggingRef.current = false;
          setHovered(null);
          setHoveredEdge(null);
        }}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
      />

      {!settled && nodes.length > 0 && (
        <span className="pointer-events-none absolute bottom-3 left-3 rounded-lg border border-white/10 bg-[#07151b]/85 px-2 py-1 text-[10px] text-muted-foreground">
          a estabilizar layout…
        </span>
      )}

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center rounded-xl bg-[#07151b]/70">
          <Loader2 size={26} className="animate-spin text-teal-300" />
        </div>
      )}

      {nodes.length === 0 && !loading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center rounded-xl text-muted-foreground">
          <p className="text-sm">Sem nós para a combinação escolhida</p>
          <p className="mt-1 max-w-xs text-center text-xs">
            Aumente a amostra, reduza o valor mínimo ou escolha outras dimensões.
          </p>
        </div>
      )}

      {tooltipVisible && (
        <div
          className="pointer-events-none absolute z-30 w-[240px] rounded-xl border border-white/10 bg-[#07151b]/95 p-3 shadow-xl"
          style={tooltipStyle}
        >
          {hovered ? (
            <>
              <p className="text-sm font-medium text-foreground break-words">{hovered.label}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{hovered.role ?? hovered.dimension}</p>
              <p className="mt-1 text-xs text-teal-300">
                {formatCompact(hovered.count)} contratos · {formatMoney(hovered.total_value)}
              </p>
              <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">Clique para detalhar</p>
            </>
          ) : (
            <>
              <p className="text-xs text-teal-300 break-words">
                {nodes.find((node) => node.id === hoveredEdge?.source)?.label ?? hoveredEdge?.source}
              </p>
              <p className="text-xs text-blue-300 break-words">
                → {nodes.find((node) => node.id === hoveredEdge?.target)?.label ?? hoveredEdge?.target}
              </p>
              <p className="mt-1.5 text-xs text-muted-foreground">
                {metricLabel(metric, metric === "valor" ? hoveredEdge?.value ?? 0 : hoveredEdge?.count ?? 0)}
                {" · "}
                {formatCompact(hoveredEdge?.count ?? 0)} contratos
              </p>
            </>
          )}
        </div>
      )}

      <div className="absolute bottom-3 right-3 z-20 flex items-center gap-1.5">
        <span className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-[11px] text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <button
          type="button"
          onClick={() => {
            userMovedRef.current = true;
            fitToView();
          }}
          aria-label="Ajustar à vista"
          title="Ajustar à vista (0)"
          className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <Scan size={15} />
        </button>
        <button
          type="button"
          onClick={() => setScale((current) => Math.min(3, current + 0.2))}
          aria-label="Aproximar"
          title="Aproximar (+)"
          className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <ZoomIn size={15} />
        </button>
        <button
          type="button"
          onClick={() => setScale((current) => Math.max(0.3, current - 0.2))}
          aria-label="Afastar"
          title="Afastar (-)"
          className="glass-card rounded-lg p-1.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <ZoomOut size={15} />
        </button>
      </div>
    </div>
  );
}
