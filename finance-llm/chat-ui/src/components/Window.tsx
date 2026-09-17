/**
 * Janela estilo macOS.
 *
 * - Barra de título arrastável (duplo clique maximiza/restaura).
 * - Semáforos: fechar (vermelho), minimizar (amarelo), maximizar (verde).
 * - Redimensionamento pelas 8 margens/cantos, com tamanhos mínimos.
 * - Ao arrastar para o topo/limites laterais aparece a pré-visualização do
 *   encaixe ("snap"), que é aplicado ao largar o botão.
 * - A geometria é escrita diretamente no DOM durante o arrasto (sem re-render
 *   do conteúdo da página) e consolidada no estado no fim.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, type WindowRect, type WindowState, type WorkspaceSize } from "../windows";

export type SnapZone = "maximize" | "left" | "right" | null;

interface WindowProps {
  state: WindowState;
  workspace: WorkspaceSize;
  title: string;
  icon: React.ReactNode;
  active: boolean;
  children: React.ReactNode;
  onFocus: () => void;
  onClose: () => void;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  onSnap: (zone: Exclude<SnapZone, null>) => void;
  onSnapPreview: (zone: SnapZone) => void;
  onRectChange: (rect: WindowRect) => void;
}

const RESIZE_EDGES = ["n", "s", "e", "w", "ne", "nw", "se", "sw"] as const;
type ResizeEdge = (typeof RESIZE_EDGES)[number];

const EDGE_CLASS: Record<ResizeEdge, string> = {
  n: "top-0 left-3 right-3 h-1.5 cursor-ns-resize",
  s: "bottom-0 left-3 right-3 h-1.5 cursor-ns-resize",
  e: "right-0 top-3 bottom-3 w-1.5 cursor-ew-resize",
  w: "left-0 top-3 bottom-3 w-1.5 cursor-ew-resize",
  ne: "top-0 right-0 h-3 w-3 cursor-nesw-resize",
  nw: "top-0 left-0 h-3 w-3 cursor-nwse-resize",
  se: "bottom-0 right-0 h-3 w-3 cursor-nwse-resize",
  sw: "bottom-0 left-0 h-3 w-3 cursor-nesw-resize",
};

export function Window({
  state,
  workspace,
  title,
  icon,
  active,
  children,
  onFocus,
  onClose,
  onMinimize,
  onToggleMaximize,
  onSnap,
  onSnapPreview,
  onRectChange,
}: WindowProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const live = useRef<WindowRect>({ x: state.x, y: state.y, width: state.width, height: state.height });
  const gesture = useRef<{ kind: "move" | "resize"; edge?: ResizeEdge; startX: number; startY: number; origin: WindowRect } | null>(null);
  const frame = useRef<number | null>(null);
  const pending = useRef<WindowRect | null>(null);
  const [interacting, setInteracting] = useState(false);

  // O estado externo (cascata, snap, reposição) manda no `live` quando não há gesto.
  if (!gesture.current) {
    live.current = { x: state.x, y: state.y, width: state.width, height: state.height };
  }

  const write = useCallback((rect: WindowRect) => {
    const node = rootRef.current;
    if (!node) return;
    node.style.width = `${rect.width}px`;
    node.style.height = `${rect.height}px`;
    node.style.transform = `translate3d(${rect.x}px, ${rect.y}px, 0)`;
  }, []);

  const scheduleWrite = useCallback(
    (rect: WindowRect) => {
      pending.current = rect;
      if (frame.current !== null) return;
      frame.current = window.requestAnimationFrame(() => {
        frame.current = null;
        if (pending.current) write(pending.current);
      });
    },
    [write],
  );

  useEffect(
    () => () => {
      if (frame.current !== null) window.cancelAnimationFrame(frame.current);
    },
    [],
  );

  /** Zona de encaixe a partir da posição do ponteiro (bordas da área de trabalho). */
  const snapZoneFor = useCallback(
    (clientX: number, clientY: number): SnapZone => {
      const root = rootRef.current?.parentElement;
      if (!root) return null;
      const box = root.getBoundingClientRect();
      if (clientY - box.top <= 4) return "maximize";
      if (clientX - box.left <= 4) return "left";
      if (box.right - clientX <= 4) return "right";
      return null;
    },
    [],
  );

  const beginGesture = (event: React.PointerEvent, kind: "move" | "resize", edge?: ResizeEdge) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    // Não iniciar arrasto a partir dos botões da barra de título.
    if (kind === "move" && target.closest("[data-window-control]")) return;
    event.preventDefault();
    onFocus();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    gesture.current = {
      kind,
      edge,
      startX: event.clientX,
      startY: event.clientY,
      origin: { ...live.current },
    };
    setInteracting(true);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const active = gesture.current;
    if (!active) return;
    const dx = event.clientX - active.startX;
    const dy = event.clientY - active.startY;
    const origin = active.origin;

    let next: WindowRect;
    if (active.kind === "move") {
      next = {
        ...origin,
        x: Math.min(Math.max(origin.x + dx, -origin.width + 96), Math.max(0, workspace.width - 96)),
        y: Math.min(Math.max(origin.y + dy, 0), Math.max(0, workspace.height - 36)),
      };
      onSnapPreview(snapZoneFor(event.clientX, event.clientY));
    } else {
      const edge = active.edge ?? "se";
      let { x, y, width, height } = origin;
      if (edge.includes("e")) width = Math.max(MIN_WINDOW_WIDTH, origin.width + dx);
      if (edge.includes("s")) height = Math.max(MIN_WINDOW_HEIGHT, origin.height + dy);
      if (edge.includes("w")) {
        width = Math.max(MIN_WINDOW_WIDTH, origin.width - dx);
        x = origin.x + (origin.width - width);
      }
      if (edge.includes("n")) {
        height = Math.max(MIN_WINDOW_HEIGHT, origin.height - dy);
        y = origin.y + (origin.height - height);
      }
      next = { x, y, width, height };
    }

    live.current = next;
    scheduleWrite(next);
  };

  const endGesture = (event: React.PointerEvent) => {
    const active = gesture.current;
    if (!active) return;
    gesture.current = null;
    setInteracting(false);
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);

    if (active.kind === "move") {
      const zone = snapZoneFor(event.clientX, event.clientY);
      onSnapPreview(null);
      if (zone) {
        onSnap(zone);
        return;
      }
    }
    // Consolida a geometria final no estado.
    const rect = live.current;
    if (
      rect.x !== state.x ||
      rect.y !== state.y ||
      rect.width !== state.width ||
      rect.height !== state.height
    ) {
      onRectChange(rect);
    }
  };

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-label={title}
      onPointerDown={onFocus}
      className={[
        "absolute left-0 top-0 flex flex-col overflow-hidden rounded-xl border backdrop-blur-xl",
        active
          ? "border-white/16 bg-[#12141a]/95 shadow-[0_28px_80px_rgba(0,0,0,0.62)]"
          : "border-white/10 bg-[#101218]/92 shadow-[0_18px_50px_rgba(0,0,0,0.5)]",
        interacting ? "select-none" : "",
      ].join(" ")}
      style={{
        width: live.current.width,
        height: live.current.height,
        transform: `translate3d(${live.current.x}px, ${live.current.y}px, 0)`,
        zIndex: state.z,
        // Suaviza as mudanças vindas do estado (cascata, snap, maximizar),
        // mas não durante um arrasto.
        transition: interacting ? "none" : "width 180ms ease, height 180ms ease, transform 180ms ease",
      }}
    >
      {/* Barra de título */}
      <header
        onPointerDown={(event) => beginGesture(event, "move")}
        onPointerMove={onPointerMove}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onDoubleClick={onToggleMaximize}
        className={[
          "group flex h-9 shrink-0 cursor-default items-center gap-2 border-b px-3",
          active ? "border-white/8 bg-white/[0.06]" : "border-white/5 bg-white/[0.02]",
        ].join(" ")}
      >
        <div className="flex items-center gap-2" data-window-control>
          <TrafficLight
            color="close"
            label={`Fechar ${title}`}
            onClick={onClose}
          />
          <TrafficLight color="minimize" label={`Minimizar ${title}`} onClick={onMinimize} />
          <TrafficLight color="maximize" label={`Maximizar ${title}`} onClick={onToggleMaximize} />
        </div>
        <div className="pointer-events-none flex min-w-0 flex-1 items-center justify-center gap-2">
          <span className="opacity-80">{icon}</span>
          <p className={["truncate text-xs font-medium", active ? "text-foreground" : "text-muted-foreground"].join(" ")}>
            {title}
          </p>
        </div>
        <span className="w-[52px]" aria-hidden="true" />
      </header>

      {/* Conteúdo */}
      <div className="relative min-h-0 flex-1 overflow-hidden bg-[#0f1115]">{children}</div>

      {/* Margens de redimensionamento */}
      {!state.maximized &&
        RESIZE_EDGES.map((edge) => (
          <div
            key={edge}
            onPointerDown={(event) => beginGesture(event, "resize", edge)}
            onPointerMove={onPointerMove}
            onPointerUp={endGesture}
            onPointerCancel={endGesture}
            className={`absolute z-10 ${EDGE_CLASS[edge]}`}
            aria-hidden="true"
          />
        ))}
    </div>
  );
}

function TrafficLight({
  color,
  label,
  onClick,
}: {
  color: "close" | "minimize" | "maximize";
  label: string;
  onClick: () => void;
}) {
  const palette = {
    close: { base: "bg-[#ff5f57] border-[#e0443e]", glyph: "text-[#7a1010]" },
    minimize: { base: "bg-[#febc2e] border-[#d89e24]", glyph: "text-[#7a4d04]" },
    maximize: { base: "bg-[#28c840] border-[#1faf34]", glyph: "text-[#0a5116]" },
  }[color];

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={[
        "grid h-3 w-3 place-items-center rounded-full border text-[7px] leading-none opacity-90 transition hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70",
        palette.base,
      ].join(" ")}
    >
      <span className={["opacity-0 transition group-hover:opacity-100", palette.glyph].join(" ")}>
        {color === "close" ? "✕" : color === "minimize" ? "–" : "＋"}
      </span>
    </button>
  );
}
