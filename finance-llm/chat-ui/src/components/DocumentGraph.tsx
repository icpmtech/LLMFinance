import { useEffect, useRef, useState } from "react";
import { Network, X, ZoomIn, ZoomOut, Move, Loader2, AlertCircle } from "lucide-react";
import type { RagDocument, RagDocumentGraphResponse } from "../types";
import { getRagDocumentGraph } from "../api";
import { Button, Card, CardHeader, CardTitle } from "./ui";

interface DocumentGraphProps {
  doc: RagDocument;
  onClose: () => void;
}

export function DocumentGraph({ doc, onClose }: DocumentGraphProps) {
  const [data, setData] = useState<RagDocumentGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStart = useRef({ x: 0, y: 0 });

  useEffect(() => {
    getRagDocumentGraph(doc.doc_id, 8)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar grafo"))
      .finally(() => setLoading(false));
  }, [doc.doc_id]);

  const positions = computePositions(data?.nodes ?? []);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const next = Math.max(0.3, Math.min(3, scale - e.deltaY * 0.001));
    setScale(next);
  };

  const startDrag = (e: React.MouseEvent) => {
    setDragging(true);
    dragStart.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
  };

  const onDrag = (e: React.MouseEvent) => {
    if (!dragging) return;
    setOffset({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y });
  };

  const endDrag = () => setDragging(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <Card className="w-full max-w-5xl h-[85vh] flex flex-col" padding="none">
        <CardHeader className="p-5 border-b border-border bg-muted/30">
          <CardTitle icon={<Network size={20} className="text-primary" />}>
            Grafo de chunks: {doc.title}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" icon={<ZoomIn size={16} />} onClick={() => setScale((s) => Math.min(3, s + 0.2))}>
              Zoom +
            </Button>
            <Button variant="ghost" size="sm" icon={<ZoomOut size={16} />} onClick={() => setScale((s) => Math.max(0.3, s - 0.2))}>
              Zoom -
            </Button>
            <Button variant="ghost" size="sm" icon={<Move size={16} />} onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }}>
              Centrar
            </Button>
            <Button variant="ghost" size="sm" icon={<X size={16} />} onClick={onClose}>
              Fechar
            </Button>
          </div>
        </CardHeader>

        <div
          ref={containerRef}
          className="relative flex-1 overflow-hidden cursor-grab active:cursor-grabbing bg-background"
          onWheel={handleWheel}
          onMouseDown={startDrag}
          onMouseMove={onDrag}
          onMouseUp={endDrag}
          onMouseLeave={endDrag}
        >
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-muted-foreground">
              <Loader2 size={20} className="animate-spin" /> A carregar grafo...
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-destructive">
              <AlertCircle size={20} /> {error}
            </div>
          )}
          {data && (
            <svg
              className="absolute inset-0 w-full h-full pointer-events-none"
              viewBox="0 0 800 600"
              preserveAspectRatio="xMidYMid meet"
              style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`, transformOrigin: "center" }}
            >
              {data.edges.map((edge, i) => {
                const a = positions[edge.source];
                const b = positions[edge.target];
                if (!a || !b) return null;
                return (
                  <line
                    key={i}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="#64748b"
                    strokeOpacity={0.25}
                    strokeWidth={Math.max(0.5, edge.weight * 1.2)}
                  />
                );
              })}
              {data.nodes.map((node) => {
                const p = positions[node.id];
                if (!p) return null;
                const isHover = hover === node.id;
                return (
                  <g
                    key={node.id}
                    transform={`translate(${p.x}, ${p.y})`}
                    className="pointer-events-auto cursor-pointer"
                    onMouseEnter={() => setHover(node.id)}
                    onMouseLeave={() => setHover(null)}
                  >
                    <circle
                      r={isHover ? 10 : 6}
                      fill="#10a37f"
                      stroke="#ffffff"
                      strokeWidth={1.5}
                      className="transition-all"
                    />
                    {isHover && (
                      <circle r={14} fill="none" stroke="#10a37f" strokeOpacity={0.5} strokeWidth={1} />
                    )}
                    {isHover && (
                      <foreignObject x={20} y={-50} width={320} height={120}>
                        <div className="bg-card border border-border rounded-xl p-3 text-xs shadow-lg">
                          <p className="font-medium mb-1">Chunk {node.chunk_index + 1}{node.page ? ` • p. ${node.page}` : ""}</p>
                          <p className="text-muted-foreground line-clamp-4">{node.text_preview}</p>
                        </div>
                      </foreignObject>
                    )}
                  </g>
                );
              })}
            </svg>
          )}
          <div className="absolute bottom-4 left-4 text-xs text-muted-foreground bg-card/80 border border-border rounded-lg px-3 py-2">
            Rodinha: zoom • Arrastar: mover • Passar: ver chunk
          </div>
        </div>
      </Card>
    </div>
  );
}

function computePositions(nodes: { id: string }[]) {
  const count = nodes.length;
  // Para documentos grandes, aumenta o raio para evitar sobreposição excessiva.
  const radius = Math.max(160, Math.min(360, count * 22));
  const cx = 400;
  const cy = 300;
  const map: Record<string, { x: number; y: number }> = {};
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, count) - Math.PI / 2;
    map[node.id] = {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });
  return map;
}
