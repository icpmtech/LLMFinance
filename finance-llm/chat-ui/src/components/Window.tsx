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
 * - Minimizar encolhe a janela para o lado do dock ("genie" simplificado) e
 *   restaurar fá-la voltar a crescer do mesmo ponto.
 * - **Efeito 3D** (opcional, Preferências do dock → Janelas 3D): as janelas sem
 *   foco recuam (`scale`) e, ao arrastar, a janela inclina-se na direção do
 *   movimento. A perspetiva vai dentro do próprio `transform`, pelo que o efeito
 *   não depende da árvore 3D (nem é afetado pelo `backdrop-filter` do vidro).
 * - **Aspeto macOS ou Windows 11** (Preferências do dock → Janelas): no macOS os
 *   semáforos ficam à esquerda com o título ao centro; no Windows 11 o ícone e o
 *   título ficam à esquerda e minimizar/maximizar/fechar à direita (com o hover
 *   vermelho do fechar). O comportamento é exatamente o mesmo.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, type WindowRect, type WindowState, type WorkspaceSize } from "../windows";
import { WINDOW3D_DEPTH_SCALE, useWindow3d, useWindowStyle, window3dPerspective } from "../layout";

export type SnapZone = "maximize" | "left" | "right" | null;

export type DockSide = "bottom" | "left" | "right";

/** Ponto de onde a janela encolhe/cresce: o lado onde está o dock. */
const ORIGIN_FOR: Record<DockSide, string> = {
  bottom: "50% 100%",
  left: "0% 100%",
  right: "100% 100%",
};

interface WindowProps {
  state: WindowState;
  workspace: WorkspaceSize;
  title: string;
  icon: React.ReactNode;
  active: boolean;
  children: React.ReactNode;
  /** Em animação de minimizar (encolhe para o dock antes de desaparecer). */
  minimizing?: boolean;
  /** Em animação de fechar (encolhe e desvanece antes de desaparecer). */
  closing?: boolean;
  /** Lado onde está o dock (dá a direção da animação). */
  dockSide?: DockSide;
  onFocus: () => void;
  onClose: () => void;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  onSnap: (zone: Exclude<SnapZone, null>) => void;
  onSnapPreview: (zone: SnapZone) => void;
  onRectChange: (rect: Partial<WindowRect>) => void;
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
  minimizing = false,
  closing = false,
  dockSide = "bottom",
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
  /** A janela acabou de aparecer (abertura ou restauro a partir do dock). */
  const [entering, setEntering] = useState(true);
  /** Efeito 3D: preferências e inclinação corrente (graus em X e Y). */
  const { window3d } = useWindow3d();
  /** Aspeto do chrome: semáforos (macOS) ou botões à direita (Windows 11). */
  const { windowStyle } = useWindowStyle();
  const tilt = useRef({ x: 0, y: 0 });
  const lastPoint = useRef<{ x: number; y: number } | null>(null);

  /**
   * `transform` completo da janela: posição (escrita a cada frame durante o
   * arrasto) + perspetiva/inclinação/profundidade do efeito 3D.
   */
  const transformFor = useCallback(
    (rect: WindowRect) => {
      const { enabled, tilt: maxTilt, depth } = window3d;
      const pieces: string[] = [];
      if (enabled) pieces.push(`perspective(${window3dPerspective(maxTilt)}px)`);
      pieces.push(`translate3d(${rect.x}px, ${rect.y}px, 0)`);
      if (enabled) {
        const { x: rx, y: ry } = tilt.current;
        if (rx) pieces.push(`rotateX(${rx.toFixed(2)}deg)`);
        if (ry) pieces.push(`rotateY(${ry.toFixed(2)}deg)`);
        if (depth && !active) pieces.push(`scale(${WINDOW3D_DEPTH_SCALE})`);
      }
      return pieces.join(" ");
    },
    [active, window3d],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setEntering(false), 320);
    return () => window.clearTimeout(timer);
  }, []);

  // O estado externo (cascata, snap, reposição) manda no `live` quando não há gesto.
  if (!gesture.current) {
    live.current = { x: state.x, y: state.y, width: state.width, height: state.height };
  }

  const write = useCallback(
    (rect: WindowRect) => {
      const node = rootRef.current;
      if (!node) return;
      node.style.width = `${rect.width}px`;
      node.style.height = `${rect.height}px`;
      node.style.transform = transformFor(rect);
    },
    [transformFor],
  );

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
    // O gesto começa **antes** da captura: se `setPointerCapture` falhar (pode
    // lançar, ex.: ponteiro já libertado) o arrasto não pode ficar por fazer.
    gesture.current = {
      kind,
      edge,
      startX: event.clientX,
      startY: event.clientY,
      origin: { ...live.current },
    };
    lastPoint.current = { x: event.clientX, y: event.clientY };
    setInteracting(true);
    try {
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    } catch {
      // Sem captura: o arrasto continua a funcionar por eventos de ponteiro normais.
    }
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
      // Efeito 3D: a janela inclina-se na direção do movimento (como um cartão
      // a ser empurrado). A velocidade é suavizada para o movimento ser calmo.
      if (window3d.enabled && window3d.tilt > 0) {
        const previous = lastPoint.current ?? { x: event.clientX, y: event.clientY };
        const vx = event.clientX - previous.x;
        const vy = event.clientY - previous.y;
        lastPoint.current = { x: event.clientX, y: event.clientY };
        const max = Math.min(8, window3d.tilt);
        const perPixel = max / 26;
        const damp = 0.72;
        const nextX = Math.max(-max, Math.min(max, tilt.current.x * damp + vy * perPixel * (1 - damp)));
        const nextY = Math.max(-max, Math.min(max, tilt.current.y * damp - vx * perPixel * (1 - damp)));
        tilt.current = { x: nextX, y: nextY };
      }
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
    try {
      (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
    } catch {
      // A captura pode já ter sido perdida (janela fechada, ponteiro solto).
    }

    // Endireita a janela (efeito 3D): sem gesto, a inclinação volta a zero.
    if (tilt.current.x !== 0 || tilt.current.y !== 0) {
      tilt.current = { x: 0, y: 0 };
      scheduleWrite(live.current);
    }
    lastPoint.current = null;

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
    // Num arrasto passamos só a posição: se a janela estava maximizada, o
    // store repõe o tamanho anterior (como no macOS).
    const next = active.kind === "move" ? { x: rect.x, y: rect.y } : rect;
    if (
      rect.x !== state.x ||
      rect.y !== state.y ||
      rect.width !== state.width ||
      rect.height !== state.height
    ) {
      onRectChange(next);
    }
  };

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-label={title}
      onPointerDown={onFocus}
      className={[
        "window-shell absolute left-0 top-0 overflow-hidden rounded-2xl border",
        interacting ? "select-none" : "",
      ].join(" ")}
      data-active={active ? "true" : "false"}
      data-interacting={interacting ? "true" : "false"}
      data-maximized={state.maximized ? "true" : "false"}
      style={{
        width: live.current.width,
        height: live.current.height,
        transform: transformFor(live.current),
        zIndex: state.z,
        // Suaviza as mudanças vindas do estado (cascata, snap, maximizar) e a
        // inclinação do efeito 3D, mas não durante um arrasto (1:1 com o rato).
        transition: interacting
          ? `width 180ms ease, height 180ms ease${window3d.enabled ? ", transform 90ms ease-out" : ""}`
          : "width 260ms cubic-bezier(0.22, 1, 0.36, 1), height 260ms cubic-bezier(0.22, 1, 0.36, 1), transform 260ms cubic-bezier(0.22, 1, 0.36, 1)",
      }}
    >
      {/* O invólucro é que anima (o `transform` da raiz é escrito no arrasto). */}
      <div
        className={[
          "window-scale flex h-full w-full flex-col overflow-hidden rounded-[inherit]",
          minimizing ? "is-minimizing" : closing ? "is-closing" : entering ? "is-entering" : "",
        ].join(" ")}
        style={{ transformOrigin: ORIGIN_FOR[dockSide] }}
      >
        {/* Barra de título */}
        <header
          onPointerDown={(event) => beginGesture(event, "move")}
          onPointerMove={onPointerMove}
          onPointerUp={endGesture}
          onPointerCancel={endGesture}
          onDoubleClick={onToggleMaximize}
          className="window-bar group flex h-9 shrink-0 cursor-default items-center gap-2 px-3"
        >
          {windowStyle === "windows" ? (
            /* Windows 11: ícone + título à esquerda, controlos à direita. */
            <>
              <div className="pointer-events-none flex min-w-0 flex-1 items-center gap-2">
                <span className="window-bar-icon">{icon}</span>
                <p className={["truncate text-[12px]", active ? "text-foreground" : "text-muted-foreground"].join(" ")}>
                  {title}
                </p>
              </div>
              <div className="win-controls flex h-full shrink-0 items-center" data-window-control>
                <WinButton kind="minimize" label={`Minimizar ${title}`} onClick={onMinimize} />
                <WinButton
                  kind={state.maximized ? "restore" : "maximize"}
                  label={state.maximized ? `Restaurar ${title}` : `Maximizar ${title}`}
                  onClick={onToggleMaximize}
                />
                <WinButton kind="close" label={`Fechar ${title}`} onClick={onClose} />
              </div>
            </>
          ) : (
            /* macOS: semáforos à esquerda, título centrado. */
            <>
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
            </>
          )}
        </header>

        {/* Conteúdo */}
        <div className="window-body relative min-h-0 flex-1 overflow-hidden">{children}</div>

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
    </div>
  );
}

/**
 * Controlos de janela do Windows 11 (minimizar / maximizar-restaurar / fechar).
 *
 * São alvos largos (46×32 px) colados ao canto superior direito, como no
 * Windows: o `hover` é um retângulo claro e o fechar fica vermelho (o vermelho
 * do próprio Windows, `#c42b1c`). Os glifos são desenhados em SVG, com o traço
 * de 1 px do sistema.
 */
function WinButton({
  kind,
  label,
  onClick,
}: {
  kind: "minimize" | "maximize" | "restore" | "close";
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      data-kind={kind}
      className="win-btn grid place-items-center focus:outline-none focus-visible:ring-1 focus-visible:ring-teal-300/70"
    >
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1">
        {kind === "minimize" && <path d="M0 5.5h10" />}
        {kind === "maximize" && <rect x="0.5" y="0.5" width="9" height="9" rx="0.5" />}
        {kind === "restore" && (
          <>
            <path d="M0.5 3.5h6v6h-6z" />
            <path d="M3.5 3.5v-3h6v6h-3" />
          </>
        )}
        {kind === "close" && (
          <>
            <path d="M0.5 0.5l9 9" />
            <path d="M9.5 0.5l-9 9" />
          </>
        )}
      </svg>
    </button>
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
}) {  const palette = {
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
