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

/** Orçamento de desenho: acima disto o grafo fica ilegível e a simulação arrasta-se. */
const MAX_DRAW_NODES = 110;
const MAX_DRAW_EDGES = 350;
/** A partir deste número de nós tira-se peso ao desenho (sombras/gradientes) e às etiquetas. */
const DENSE_NODE_COUNT = 70;

type NodeShape = "circle" | "square" | "diamond" | "hexagon";

/** Forma por tipo de nó: pessoa ●, empresa ■, entidade ◆, site/perfil ⬢. */
function shapeForType(type: string | undefined): NodeShape {
  switch (String(type || "").toLowerCase()) {
    case "company":
      return "square";
    case "entity":
      return "diamond";
    case "source":
      return "hexagon";
    case "person":
    default:
      return "circle";
  }
}

function traceRoundRect(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, radius: number) {
  const left = x - size / 2;
  const top = y - size / 2;
  const r = Math.max(0, Math.min(radius, size / 2));
  ctx.beginPath();
  ctx.moveTo(left + r, top);
  ctx.lineTo(left + size - r, top);
  ctx.quadraticCurveTo(left + size, top, left + size, top + r);
  ctx.lineTo(left + size, top + size - r);
  ctx.quadraticCurveTo(left + size, top + size, left + size - r, top + size);
  ctx.lineTo(left + r, top + size);
  ctx.quadraticCurveTo(left, top + size, left, top + size - r);
  ctx.lineTo(left, top + r);
  ctx.quadraticCurveTo(left, top, left + r, top);
  ctx.closePath();
}

/** Traça o contorno do nó na forma do seu tipo (todas as formas cabem no mesmo raio). */
function traceShape(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, shape: NodeShape) {
  if (shape === "square") {
    traceRoundRect(ctx, x, y, radius * 1.66, Math.max(3, radius * 0.32));
    return;
  }
  if (shape === "diamond") {
    const r = radius * 1.14;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
    return;
  }
  if (shape === "hexagon") {
    ctx.beginPath();
    for (let index = 0; index < 6; index += 1) {
      const angle = (Math.PI / 3) * index - Math.PI / 2;
      const px = x + Math.cos(angle) * radius * 1.08;
      const py = y + Math.sin(angle) * radius * 1.08;
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    return;
  }
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
}

/** Glifo dentro do nó: pessoa, edifício, documento e globo (desenhados, sem imagens). */
function drawGlyph(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, shape: NodeShape, alpha: number) {
  if (radius < 7) return;
  const s = Math.max(3, radius * 0.46);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineWidth = Math.max(1.1, radius * 0.11);
  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.fillStyle = "rgba(255,255,255,0.95)";
  if (shape === "circle") {
    // Pessoa: cabeça + ombros.
    ctx.beginPath();
    ctx.arc(x, y - s * 0.5, s * 0.42, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x, y + s * 0.95, s * 0.78, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();
  } else if (shape === "square") {
    // Empresa: edifício com janelas.
    const w = s * 1.1;
    const h = s * 1.35;
    ctx.strokeRect(x - w / 2, y - h / 2, w, h);
    ctx.beginPath();
    const step = w / 3;
    for (let row = 0; row < 2; row += 1) {
      for (let col = 0; col < 2; col += 1) {
        ctx.rect(x - w / 2 + step * (col + 0.6), y - h / 2 + h * (0.22 + row * 0.42), step * 0.42, h * 0.2);
      }
    }
    ctx.fill();
  } else if (shape === "diamond") {
    // Entidade: documento com linhas.
    const w = s * 1.0;
    const h = s * 1.3;
    ctx.beginPath();
    ctx.moveTo(x - w / 2, y - h / 2);
    ctx.lineTo(x + w / 2, y - h / 2);
    ctx.lineTo(x + w / 2, y + h / 2 - s * 0.3);
    ctx.lineTo(x + w / 2 - s * 0.3, y + h / 2);
    ctx.lineTo(x - w / 2, y + h / 2);
    ctx.closePath();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - w * 0.28, y - h * 0.18);
    ctx.lineTo(x + w * 0.28, y - h * 0.18);
    ctx.moveTo(x - w * 0.28, y + h * 0.12);
    ctx.lineTo(x + w * 0.12, y + h * 0.12);
    ctx.stroke();
  } else {
    // Site/perfil: globo com um meridiano.
    ctx.beginPath();
    ctx.arc(x, y, s * 0.75, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(x, y, s * 0.34, s * 0.75, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - s * 0.73, y);
    ctx.lineTo(x + s * 0.73, y);
    ctx.stroke();
  }
  ctx.restore();
}

export function GraphCanvas({
  graph,
  layout,
  metric,
  selectedNodeId,
  layoutVersion = 0,
  loading = false,
  heightClass = "h-[560px]",
  unitLabel = "contratos",
  nodeSummary,
  edgeSummary,
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
  /** Unidade mostrada nas dicas (ex.: «contratos» ou «publicações»). */
  unitLabel?: string;
  /** Resumo personalizado do nó na dica (por omissão: contratos · valor). */
  nodeSummary?: (node: StudioNode) => string;
  /** Resumo personalizado da aresta na dica (por omissão: métrica · contratos). */
  edgeSummary?: (edge: StudioEdge) => string;
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
  /**
   * Chave do último layout já simulado.
   *
   * O efeito de layout volta a correr sempre que o pai re-renderiza com um
   * `graph` de identidade nova (o `layoutKey` resulta de `nodes`/`edges`). Sem
   * esta guarda, cada re-render reiniciava a simulação e o `fitToView()` que se
   * segue publicava `scale`/`offset` — que por serem objectos novos forçam novo
   * render — e o ciclo só terminava quando o browser ficava sem resposta.
   */
  const laidOutKeyRef = useRef<string | null>(null);
  const lastPointerRef = useRef({ x: 0, y: 0 });

  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hovered, setHovered] = useState<StudioNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<StudioEdge | null>(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });
  const [settled, setSettled] = useState(false);

  const degree = useMemo(() => {
    const counts = new Map<string, number>();
    (graph?.edges ?? []).forEach((edge) => {
      counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1);
      counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
    });
    return counts;
  }, [graph]);

  /**
   * Orçamento de desenho.
   *
   * Um grafo com centenas de nós deixa de se ler e a simulação de forças arrasta
   * o browser. Aqui escolhem-se os nós mais relevantes (valor + ligações),
   * guardando sempre o nó selecionado, e cortam-se as ligações mais fracas; o
   * que ficar de fora é anunciado no próprio canvas (e não desaparece do painel
   * de detalhe, que trabalha sobre o grafo completo, em `graph`).
   */
  const drawn = useMemo(() => {
    const allNodes = graph?.nodes ?? [];
    const allEdges = graph?.edges ?? [];
    const relevance = (node: StudioNode) =>
      (node.value || 0) * 2 + (degree.get(node.id) ?? 0) * 3 + (node.type === "company" ? 1 : 0);
    const ranked = [...allNodes].sort((a, b) => relevance(b) - relevance(a));
    const keep = new Set(ranked.slice(0, MAX_DRAW_NODES).map((node) => node.id));
    if (selectedNodeId) keep.add(selectedNodeId);
    const nodes = allNodes.filter((node) => keep.has(node.id));
    const ids = new Set(nodes.map((node) => node.id));
    const edges = allEdges
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .sort((a, b) => (b.value || b.count || 0) - (a.value || a.count || 0))
      .slice(0, MAX_DRAW_EDGES);
    return {
      nodes,
      edges,
      omittedNodes: allNodes.length - nodes.length,
      omittedEdges: allEdges.length - edges.length,
    };
  }, [degree, graph, selectedNodeId]);

  const nodes = drawn.nodes;
  const edges = drawn.edges;
  const dense = nodes.length > DENSE_NODE_COUNT;

  const labelledIds = useMemo(
    () =>
      new Set(
        [...nodes]
          .sort((a, b) => b.value - a.value)
          .slice(0, dense ? 6 : layout === "circular" ? 16 : 12)
          .map((node) => node.id),
      ),
    [nodes, layout, dense],
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
    dense,
    omittedNodes: drawn.omittedNodes,
    omittedEdges: drawn.omittedEdges,
  });

  useEffect(() => {
    frame.current = {
      nodes,
      edges,
      scale,
      offset,
      hovered,
      hoveredEdge,
      selectedNodeId,
      labelledIds,
      dense,
      omittedNodes: drawn.omittedNodes,
      omittedEdges: drawn.omittedEdges,
    };
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

    if (current.dense) {
      // Grafos densos: as arestas são traçadas em três grupos (por intensidade) e
      // as formas por cor — são 6 chamadas de desenho em vez de uma por elemento.
      const bands = [new Path2D(), new Path2D(), new Path2D()];
      const hoverPath = new Path2D();
      let hovered = false;
      current.edges.forEach((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return;
        const key = [edge.source, edge.target].sort().join("|");
        if (hoveredEdgeKey && key === hoveredEdgeKey) {
          hoverPath.moveTo(a.x, a.y);
          hoverPath.lineTo(b.x, b.y);
          hovered = true;
          return;
        }
        const band = edge.weight > 0.66 ? 2 : edge.weight > 0.33 ? 1 : 0;
        bands[band].moveTo(a.x, a.y);
        bands[band].lineTo(b.x, b.y);
      });
      bands.forEach((path, index) => {
        ctx.strokeStyle = `rgba(125,211,252,${0.2 + index * 0.22})`;
        ctx.lineWidth = 0.7 + index * 0.7;
        ctx.stroke(path);
      });
      if (hovered) {
        ctx.strokeStyle = "rgba(251,191,36,0.95)";
        ctx.lineWidth = 2.6;
        ctx.stroke(hoverPath);
      }
    } else {
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
    }

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

    const drawNodeAt = (
      node: StudioNode,
      p: { x: number; y: number },
      isSelected: boolean,
      isHovered: boolean,
    ) => {
      const radius = isSelected ? node.radius + 5 : isHovered ? node.radius + 3 : node.radius;
      // A forma identifica o tipo: ● pessoa · ■ empresa · ◆ entidade · ⬢ site/perfil.
      const shape = shapeForType(node.type ?? node.dimension);
      traceShape(ctx, p.x, p.y, radius, shape);

      if (current.dense && !isSelected && !isHovered) {
        // Em grafos densos: sem sombras nem gradientes por nó (é o que mais custa).
        ctx.fillStyle = `${node.color}b8`;
        ctx.fill();
      } else {
        ctx.shadowBlur = isSelected || isHovered ? 20 : 9;
        ctx.shadowColor = node.color;
        const fill = ctx.createRadialGradient(p.x - radius * 0.35, p.y - radius * 0.35, 1, p.x, p.y, radius);
        fill.addColorStop(0, node.color);
        fill.addColorStop(0.4, `${node.color}cc`);
        fill.addColorStop(1, "rgba(7,21,27,0.98)");
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      ctx.lineWidth = isSelected ? 4 : isHovered ? 3.5 : Math.max(1.6, radius * 0.16);
      ctx.strokeStyle = isSelected || isHovered ? "#ffffff" : node.color;
      ctx.stroke();

      // Os glifos dão a ler o tipo; em grafos enormes são o primeiro luxo a cair.
      if (!current.dense || isSelected || isHovered || current.nodes.length <= 350) {
        drawGlyph(ctx, p.x, p.y, radius, shape, isSelected || isHovered ? 1 : current.dense ? 0.7 : 0.85);
      }

      if (isSelected || isHovered || (!current.dense && current.labelledIds.has(node.id))) {
        drawLabel(node.label, p.x + radius + 6, p.y + 3, isSelected || isHovered);
      }
    };

    if (current.dense) {
      // Em bloco: formas sem sombras nem gradientes (o que mais custa por nó); só o
      // nó escolhido/a pairar ganha o desenho completo.
      const emphasised: { node: StudioNode; p: { x: number; y: number }; selected: boolean }[] = [];
      current.nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        const isSelected = current.selectedNodeId === node.id;
        const isHovered = current.hovered?.id === node.id;
        if (isSelected || isHovered) {
          emphasised.push({ node, p, selected: isSelected });
          return;
        }
        const radius = node.radius;
        const shape = shapeForType(node.type ?? node.dimension);
        traceShape(ctx, p.x, p.y, radius, shape);
        ctx.fillStyle = `${node.color}b8`;
        ctx.fill();
        ctx.lineWidth = Math.max(1.4, radius * 0.14);
        ctx.strokeStyle = node.color;
        ctx.stroke();
        if (current.nodes.length <= 350) {
          drawGlyph(ctx, p.x, p.y, radius, shape, 0.7);
        }
      });
      emphasised.forEach((entry) => drawNodeAt(entry.node, entry.p, entry.selected, true));
    } else {
      current.nodes.forEach((node) => {
        const p = positions.get(node.id);
        if (!p) return;
        drawNodeAt(
          node,
          p,
          current.selectedNodeId === node.id,
          current.hovered?.id === node.id,
        );
      });
    }

    // Anúncio do que ficou de fora do desenho (o painel de detalhe tem tudo).
    if (current.omittedNodes > 0 || current.omittedEdges > 0) {
      const message =
        `${current.omittedNodes} nó(s) e ${current.omittedEdges} ligação(ões) não desenhados ` +
        "(limite de desempenho: use os filtros para reduzir o grafo)";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = "600 10px ui-sans-serif, system-ui";
      const textWidth = ctx.measureText(message).width;
      ctx.fillStyle = "rgba(3,12,17,0.85)";
      ctx.fillRect(10, 10, textWidth + 16, 20);
      ctx.fillStyle = "#fcd34d";
      ctx.fillText(message, 18, 24);
    }
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
    const nextOffsetX = -((minX + maxX) / 2) * nextScale;
    const nextOffsetY = -((minY + maxY) / 2) * nextScale;
    // Estado só se mudar: `fitToView` é chamado pelo `ResizeObserver` e por cada
    // layout; publicar sempre destes objectos punha o componente a re-renderizar
    // sem fim.
    setScale((current) => (current === nextScale ? current : nextScale));
    setOffset((current) =>
      current.x === nextOffsetX && current.y === nextOffsetY
        ? current
        : { x: nextOffsetX, y: nextOffsetY },
    );
  }, []);

  fitToViewRef.current = fitToView;

  // Layout: determinístico (circular/hierárquico) ou simulação de forças.
  useEffect(() => {
    if (nodes.length === 0) return;
    // Mesmo layout (mesmos nós e ligações): só falta desenhar. Sem esta guarda o
    // efeito volta a correr a cada re-render do pai e a física nunca assenta.
    if (laidOutKeyRef.current === layoutKey) {
      draw();
      return;
    }
    laidOutKeyRef.current = layoutKey;
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

    // Semeadura por tipo em anéis concêntricos: empresas por fora, pessoas no meio,
    // sites/perfis por dentro. Com centenas de nós isto poupa centenas de iterações
    // (a física parte de um arranjo legível em vez de um círculo aleatório).
    const ringByType: Record<string, number> = { company: 1, entity: 0.88, person: 0.58, source: 0.4 };
    const radiusBase = Math.max(170, Math.min(460, 70 + nodes.length * 1.7));
    const groups = new Map<string, StudioNode[]>();
    nodes.forEach((node) => {
      const type = String(node.type ?? node.dimension ?? "person");
      const bucket = groups.get(type) ?? [];
      bucket.push(node);
      groups.set(type, bucket);
    });
    groups.forEach((group, type) => {
      const ring = (ringByType[type] ?? 0.7) * radiusBase;
      [...group]
        .sort((a, b) => b.value - a.value)
        .forEach((node, index) => {
          if (positions.has(node.id)) return;
          const angle = (index / Math.max(group.length, 1)) * Math.PI * 2;
          positions.set(node.id, { x: Math.cos(angle) * ring, y: Math.sin(angle) * ring, vx: 0, vy: 0 });
        });
    });

    /**
     * Recoloca no anel uma posição não finita (NaN/±∞).
     *
     * É a rede de segurança do ciclo de forças: `Infinity` numa coordenada faz
     * `Math.floor(x / CELL)` dar `Infinity` e o ciclo
     * `for (let gx = cx - 1; gx <= cx + 1; gx++)` **nunca termina** —
     * `Infinity + 1` continua a ser `Infinity` — bloqueando a thread principal
     * sem forma de recuperar (a página fica sem resposta para sempre).
     */
    const sanear = (node: StudioNode, index: number): NodePosition => {
      const current = positions.get(node.id);
      if (
        current &&
        Number.isFinite(current.x) &&
        Number.isFinite(current.y) &&
        Number.isFinite(current.vx) &&
        Number.isFinite(current.vy)
      ) {
        return current;
      }
      const ring = Math.max(140, Math.min(radiusBase, 140 + index * 6));
      const angle = index * 2.399963229728653; // ângulo áureo: espalha sem repetir
      const fixed: NodePosition = {
        x: Math.cos(angle) * ring,
        y: Math.sin(angle) * ring,
        vx: 0,
        vy: 0,
      };
      positions.set(node.id, fixed);
      return fixed;
    };

    const runStep = () => {
      const grid = new Map<string, StudioNode[]>();
      nodes.forEach((node, index) => {
        const p = sanear(node, index);
        const key = `${Math.floor(p.x / CELL)}:${Math.floor(p.y / CELL)}`;
        const bucket = grid.get(key) ?? [];
        bucket.push(node);
        grid.set(key, bucket);
      });
      nodes.forEach((node, index) => {
        const p = sanear(node, index);
        const cx = Math.floor(p.x / CELL);
        const cy = Math.floor(p.y / CELL);
        // Sem coordenadas finitas não há vizinhança a calcular (e o ciclo abaixo
        // seria infinito).
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) return;
        // Ciclo com contador fixo (`dx`/`dy`) e não `gx <= cx + 1`: com uma
        // coordenada infinita, `gx++` nunca faria a condição falhar — o ciclo
        // correria para sempre e a página ficava presa sem recuperação.
        for (let dx = -1; dx <= 1; dx += 1) {
          for (let dy = -1; dy <= 1; dy += 1) {
            const bucket = grid.get(`${cx + dx}:${cy + dy}`);
            if (!bucket) continue;
            bucket.forEach((other) => {
              if (other.id <= node.id) return;
              const q = positions.get(other.id);
              if (!q) return;
              const vx = p.x - q.x;
              const vy = p.y - q.y;
              const dist = Math.sqrt(vx * vx + vy * vy) || 1;
              if (dist > CELL * 3) return;
              const force = REPULSION / (dist * dist);
              p.vx += (vx / dist) * force;
              p.vy += (vy / dist) * force;
              q.vx -= (vx / dist) * force;
              q.vy -= (vy / dist) * force;
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
      nodes.forEach((node, index) => {
        const p = sanear(node, index);
        p.vx = (p.vx - p.x * 0.003) * 0.88;
        p.vy = (p.vy - p.y * 0.003) * 0.88;
        p.x += p.vx;
        p.y += p.vy;
        energy += Math.abs(p.vx) + Math.abs(p.vy);
      });
      return energy / Math.max(nodes.length, 1);
    };

    const reduceMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
    const maxTicks = nodes.length > 1200 ? 100 : nodes.length > 600 ? 120 : nodes.length > 250 ? 180 : 420;

    /**
     * Grafos grandes: **desenha-se já** com o arranjo por anéis (determinístico e
     * legível) e o refinamento da física corre em blocos de ~10 ms por frame — o
     * browser nunca fica preso e a vista não espera por «a estabilizar layout…».
     */
    if (nodes.length > 45) {
      draw();
      if (!userMovedRef.current) fitToView();
      setSettled(true);

      let raf = 0;
      let ticks = 0;
      const refine = () => {
        const deadline = performance.now() + 10;
        let energy = 0;
        while (ticks < maxTicks && performance.now() < deadline) {
          energy = runStep();
          ticks += 1;
          if (!Number.isFinite(energy) || energy <= 0.4) break;
        }
        draw();
        if (ticks < maxTicks && Number.isFinite(energy) && energy > 0.4) {
          raf = requestAnimationFrame(refine);
        } else if (!userMovedRef.current) {
          fitToView();
          draw();
        }
      };
      raf = requestAnimationFrame(refine);
      return () => cancelAnimationFrame(raf);
    }

    if (reduceMotion) {
      for (let tick = 0; tick < maxTicks; tick += 1) {
        const energy = runStep();
        if (!Number.isFinite(energy) || energy <= 0.4) break;
      }
      draw();
      if (!userMovedRef.current) fitToView();
      setSettled(true);
      return;
    }

    let raf = 0;
    let ticks = 0;
    let frames = 0;
    const stepsPerFrame = 2;
    const maxFrames = 120;
    const loop = () => {
      let energy = 0;
      for (let step = 0; step < stepsPerFrame && ticks < maxTicks; step += 1) {
        energy = runStep();
        ticks += 1;
        if (!Number.isFinite(energy) || energy <= 0.4) break;
      }
      draw();
      frames += 1;
      if (ticks < maxTicks && frames < maxFrames && Number.isFinite(energy) && energy > 0.4) {
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
    // Folga em **píxeis de ecrã** (e não em unidades do grafo): com o grafo
    // afastado (zoom a 30%), `node.radius + 5` em unidades dava menos de 2 px e
    // acertar num nó era uma lotaria.
    const folga = 12 / Math.max(scale, 0.3);
    return (
      frame.current.nodes.find((node) => {
        const p = positions.get(node.id);
        return p ? Math.hypot(p.x - x, p.y - y) <= node.radius + folga : false;
      }) ?? null
    );
  };

  const hitEdge = (x: number, y: number) => {
    const positions = positionsRef.current;
    // Mesma folga dos nós (12 px de ecrã): a 8 px, clicar numa ligação fina era
    // quase impossível, ainda mais com o grafo afastado.
    const folga = 12 / Math.max(scale, 0.3);
    return (
      frame.current.edges.find((edge) => {
        const a = positions.get(edge.source);
        const b = positions.get(edge.target);
        if (!a || !b) return false;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const lengthSquared = dx * dx + dy * dy || 1;
        const projection = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / lengthSquared));
        return Math.hypot(x - (a.x + projection * dx), y - (a.y + projection * dy)) <= folga;
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
        aria-label={`Grafo com ${nodes.length} nós e ${edges.length} ligações${
          drawn.omittedNodes > 0 ? ` (mais ${drawn.omittedNodes} nós não desenhados por limite de desempenho)` : ""
        }. Setas para mover, mais e menos para zoom, zero para ajustar à vista.`}
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
                {nodeSummary
                  ? nodeSummary(hovered)
                  : `${formatCompact(hovered.count)} ${unitLabel} · ${formatMoney(hovered.total_value)}`}
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
                {edgeSummary
                  ? edgeSummary(hoveredEdge as StudioEdge)
                  : `${metricLabel(metric, metric === "valor" ? hoveredEdge?.value ?? 0 : hoveredEdge?.count ?? 0)} · ${formatCompact(hoveredEdge?.count ?? 0)} ${unitLabel}`}
              </p>
            </>
          )}
        </div>
      )}

      <div className="absolute bottom-3 right-3 z-20 flex items-center gap-1.5">
        <span className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1.5 text-[11px] text-muted-foreground">
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
          className="glass-card flex min-h-[40px] min-w-[40px] items-center justify-center rounded-lg p-2 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <Scan size={18} />
        </button>
        <button
          type="button"
          onClick={() => setScale((current) => Math.min(3, current + 0.2))}
          aria-label="Aproximar"
          title="Aproximar (+)"
          className="glass-card flex min-h-[40px] min-w-[40px] items-center justify-center rounded-lg p-2 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <ZoomIn size={18} />
        </button>
        <button
          type="button"
          onClick={() => setScale((current) => Math.max(0.3, current - 0.2))}
          aria-label="Afastar"
          title="Afastar (-)"
          className="glass-card flex min-h-[40px] min-w-[40px] items-center justify-center rounded-lg p-2 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
        >
          <ZoomOut size={18} />
        </button>
      </div>
    </div>
  );
}
