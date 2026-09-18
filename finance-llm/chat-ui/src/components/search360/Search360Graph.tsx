/**
 * Grafo de navegação da Pesquisa 360.
 *
 * O tema fica no centro e à volta dispõem-se, em anéis, tudo o que as fontes
 * devolveram: entidades, artigos, conjuntos de dados, indicadores, notícias e
 * ficheiros. Cada nó é um "ficheiro" com o ícone do seu tipo (como no Finder),
 * e clicar nele abre o painel de detalhe do lado direito da página.
 *
 * Implementado em canvas, sem dependências: uma disposição radial é mais
 * estável e legível do que uma simulação de forças para este formato de grafo
 * (um tema ao centro, muitos itens em volta), e permite arrastar, ampliar e
 * destacar sem re-layout.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Search360Graph, Search360GraphNode } from "../../search360Api";
import { kindLabel } from "../../search360Api";

const GLYPHS: Record<string, string> = {
  topic: "◎",
  entity: "◆",
  article: "▤",
  document: "▦",
  dataset: "▣",
  metric: "▮",
  news: "✦",
  file: "▧",
  summary: "✳",
};

type Placed = {
  node: Search360GraphNode;
  x: number;
  y: number;
  radius: number;
  glyph: string;
};

const MIN_RADIUS = 7;
const MAX_RADIUS = 15;

export function Search360Graph({
  graph,
  selectedId,
  onSelect,
  onOpen,
  heightClass = "h-[520px]",
  loading = false,
}: {
  graph: Search360Graph | null;
  selectedId?: string | null;
  onSelect?: (node: Search360GraphNode) => void;
  onOpen?: (node: Search360GraphNode) => void;
  heightClass?: string;
  loading?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 900, height: 520 });
  const [view, setView] = useState({ zoom: 1, offsetX: 0, offsetY: 0 });
  const dragState = useRef<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);

  /* ---------------------------------------------------------- dimensões */
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      setSize({ width: Math.max(320, Math.round(rect.width)), height: Math.max(280, Math.round(rect.height)) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    // Um separador oculto mede 0 de largura: ao voltar a ficar visível, medir outra vez.
    const onVisible = () => measure();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("resize", onVisible);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("resize", onVisible);
    };
  }, []);

  /* ------------------------------------------------------------- layout */
  const placed = useMemo<Placed[]>(() => {
    if (!graph?.nodes?.length) return [];
    const center = graph.nodes.find((node) => node.depth === 0) ?? graph.nodes[0];
    const rest = graph.nodes.filter((node) => node.id !== center.id);
    const maxValue = Math.max(...graph.nodes.map((node) => Number(node.value) || 0.5), 0.5);
    const ringRadius = Math.max(140, Math.min(size.width, size.height) / 2 - 70);
    const perRing = rest.length > 26 ? Math.ceil(rest.length / 2) : rest.length;
    const out: Placed[] = [
      {
        node: center,
        x: size.width / 2,
        y: size.height / 2,
        radius: 20,
        glyph: GLYPHS.topic ?? "◎",
      },
    ];
    rest.forEach((node, index) => {
      const ring = Math.floor(index / perRing);
      const inRing = ring === 0 ? Math.min(perRing, rest.length) : rest.length - perRing;
      const position = ring === 0 ? index : index - perRing;
      const angle = (position / Math.max(inRing, 1)) * Math.PI * 2 - Math.PI / 2 + (ring === 1 ? Math.PI / Math.max(inRing, 1) : 0);
      const scale = 1 - ring * 0.22;
      const radius = Math.max(MIN_RADIUS, Math.min(MAX_RADIUS, 6 + (Number(node.value) || 0.5) / maxValue * 9));
      out.push({
        node,
        x: size.width / 2 + Math.cos(angle) * ringRadius * scale,
        y: size.height / 2 + Math.sin(angle) * ringRadius * scale,
        radius,
        glyph: GLYPHS[node.kind] ?? "•",
      });
    });
    return out;
  }, [graph, size.width, size.height]);

  const byId = useMemo(() => new Map(placed.map((entry) => [entry.node.id, entry])), [placed]);

  /* -------------------------------------------------------------- desenho */
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size.width * dpr;
    canvas.height = size.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.width, size.height);
    ctx.save();
    ctx.translate(view.offsetX, view.offsetY);
    ctx.scale(view.zoom, view.zoom);

    // arestas
    for (const edge of graph?.edges ?? []) {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      if (!from || !to) continue;
      const focus = hovered === from.node.id || hovered === to.node.id || selectedId === from.node.id || selectedId === to.node.id;
      ctx.beginPath();
      ctx.strokeStyle = focus ? "rgba(56,189,248,0.85)" : "rgba(148,163,184,0.22)";
      ctx.lineWidth = focus ? 1.6 : 1;
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
    }

    // nós
    for (const entry of placed) {
      const { node, x, y, radius, glyph } = entry;
      const focus = hovered === node.id || selectedId === node.id;
      if (node.depth === 0) {
        ctx.beginPath();
        ctx.fillStyle = "rgba(56,189,248,0.16)";
        ctx.arc(x, y, radius + 10, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.beginPath();
      ctx.fillStyle = node.color || "#94a3b8";
      ctx.globalAlpha = node.depth === 0 || focus ? 1 : 0.86;
      ctx.arc(x, y, focus ? radius + 2 : radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = focus ? 2 : 1;
      ctx.strokeStyle = focus ? "#e2e8f0" : "rgba(15,23,42,0.65)";
      ctx.stroke();

      // ícone do tipo dentro do nó
      if (radius >= 9) {
        ctx.fillStyle = "rgba(8,15,26,0.9)";
        ctx.font = `${Math.round(radius * 1.05)}px ui-sans-serif, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(glyph, x, y + 0.5);
      }

      // etiqueta (tema e nós destacados, para não poluir)
      if (node.depth === 0 || focus) {
        const label = String(node.label ?? "").slice(0, 34);
        ctx.font = `${node.depth === 0 ? "600 12px" : "11px"} ui-sans-serif, system-ui, sans-serif`;
        const width = ctx.measureText(label).width + 12;
        ctx.fillStyle = "rgba(8,15,26,0.82)";
        ctx.beginPath();
        ctx.roundRect(x - width / 2, y + radius + 6, width, 18, 6);
        ctx.fill();
        ctx.fillStyle = "#e2e8f0";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, x, y + radius + 15);
      }
    }
    ctx.restore();
  }, [byId, graph, hovered, placed, selectedId, size.height, size.width, view]);

  useEffect(() => {
    draw();
  }, [draw]);

  /* ----------------------------------------------------------- interação */
  const pick = useCallback(
    (clientX: number, clientY: number): Placed | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const x = (clientX - rect.left - view.offsetX) / view.zoom;
      const y = (clientY - rect.top - view.offsetY) / view.zoom;
      let best: Placed | null = null;
      let bestDistance = Number.POSITIVE_INFINITY;
      for (const entry of placed) {
        const distance = Math.hypot(entry.x - x, entry.y - y);
        if (distance <= Math.max(entry.radius + 6, 12) && distance < bestDistance) {
          best = entry;
          bestDistance = distance;
        }
      }
      return best;
    },
    [placed, view],
  );

  const handleMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragState.current) {
      setView((current) => ({
        ...current,
        offsetX: dragState.current ? dragState.current.offsetX + (event.clientX - dragState.current.x) : current.offsetX,
        offsetY: dragState.current ? dragState.current.offsetY + (event.clientY - dragState.current.y) : current.offsetY,
      }));
      return;
    }
    const hit = pick(event.clientX, event.clientY);
    setHovered(hit?.node.id ?? null);
    if (hit) {
      const rect = event.currentTarget.getBoundingClientRect();
      setTip({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
        text: `${hit.node.label} — ${kindLabel(hit.node.kind)}${hit.node.source_label ? ` · ${hit.node.source_label}` : ""}`,
      });
    } else {
      setTip(null);
    }
  };

  const handleDown = (event: React.MouseEvent<HTMLCanvasElement>) => {
    dragState.current = { x: event.clientX, y: event.clientY, offsetX: view.offsetX, offsetY: view.offsetY };
  };

  const handleUp = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const wasDragging = dragState.current;
    dragState.current = null;
    if (!wasDragging) return;
    const moved = Math.hypot(event.clientX - wasDragging.x, event.clientY - wasDragging.y) > 4;
    if (moved) return;
    const hit = pick(event.clientX, event.clientY);
    if (hit) onSelect?.(hit.node);
  };

  const handleDouble = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const hit = pick(event.clientX, event.clientY);
    if (hit) onOpen?.(hit.node);
  };

  const handleWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    setView((current) => ({ ...current, zoom: Math.min(2.4, Math.max(0.4, current.zoom * (event.deltaY > 0 ? 0.92 : 1.08))) }));
  };

  const reset = () => setView({ zoom: 1, offsetX: 0, offsetY: 0 });

  return (
    <div ref={wrapRef} className={`relative w-full overflow-hidden rounded-2xl border border-white/10 bg-[#08131c] ${heightClass}`}>
      <canvas
        ref={canvasRef}
        className="h-full w-full cursor-grab active:cursor-grabbing"
        style={{ width: size.width, height: size.height }}
        onMouseMove={handleMove}
        onMouseDown={handleDown}
        onMouseUp={handleUp}
        onMouseLeave={() => {
          dragState.current = null;
          setHovered(null);
          setTip(null);
        }}
        onDoubleClick={handleDouble}
        onWheel={handleWheel}
      />
      {tip ? (
        <div
          className="pointer-events-none absolute max-w-[260px] rounded-lg border border-white/10 bg-[#0b1a24]/95 px-2 py-1 text-[11px] text-slate-200 shadow-lg"
          style={{ left: Math.min(tip.x + 12, size.width - 270), top: Math.max(tip.y - 34, 6) }}
        >
          {tip.text}
        </div>
      ) : null}
      <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-1.5">
        {(graph?.legend ?? []).map((entry) => (
          <span
            key={entry.kind}
            className="pointer-events-auto inline-flex items-center gap-1 rounded-full border border-white/10 bg-[#08131c]/85 px-2 py-0.5 text-[10px] text-slate-300"
          >
            <span className="h-2 w-2 rounded-full" style={{ background: entry.color }} />
            {entry.label} <span className="text-slate-500">{entry.count}</span>
          </span>
        ))}
      </div>
      <div className="absolute bottom-3 right-3 flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => setView((current) => ({ ...current, zoom: Math.min(2.4, current.zoom * 1.15) }))}
          className="h-7 w-7 rounded-lg border border-white/10 bg-white/5 text-xs text-slate-200 transition hover:bg-white/10"
          title="Ampliar"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => setView((current) => ({ ...current, zoom: Math.max(0.4, current.zoom * 0.87) }))}
          className="h-7 w-7 rounded-lg border border-white/10 bg-white/5 text-xs text-slate-200 transition hover:bg-white/10"
          title="Reduzir"
        >
          −
        </button>
        <button
          type="button"
          onClick={reset}
          className="h-7 rounded-lg border border-white/10 bg-white/5 px-2 text-[11px] text-slate-200 transition hover:bg-white/10"
          title="Repor a vista"
        >
          Repor
        </button>
      </div>
      {loading ? (
        <div className="absolute inset-0 grid place-items-center bg-[#08131c]/70 text-xs text-slate-300">A construir o grafo…</div>
      ) : null}
      {!loading && !placed.length ? (
        <div className="absolute inset-0 grid place-items-center text-xs text-slate-400">Sem nós para mostrar — faça uma pesquisa primeiro.</div>
      ) : null}
    </div>
  );
}
