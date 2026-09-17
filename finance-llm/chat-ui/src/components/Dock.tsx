/**
 * Dock estilo macOS.
 *
 * - Barra de ícones fixa (em baixo, à esquerda ou à direita) com efeito de vidro.
 * - Ampliação no eixo do dock com "empurrão" dos ícones vizinhos (como no macOS),
 *   calculada por frame e escrita diretamente no DOM para não provocar re-render.
 * - Etiquetas flutuantes, indicador de aplicação aberta, salto ao abrir, arrumação
 *   por arrastar e um painel de preferências (posição, tamanho, ampliação, etc.).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  EyeOff,
  GripVertical,
  Maximize2,
  Minimize2,
  Minus,
  MonitorSmartphone,
  PanelLeftOpen,
  Pin,
  Plus,
  RotateCcw,
  Settings,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  ICON_SIZE_RANGE,
  MAGNIFY_RANGE,
  SPREAD_RANGE,
  useDock,
  type DockApp,
  type DockPosition,
} from "../dock";
import { useAuth } from "../auth";
import { useSidebar, useWindowMode } from "../layout";
import { closeWindow, focusWindow, minimizeWindow, useWindows, windowFor } from "../windows";
import { useFullscreen } from "../fullscreen";
import { usePwaInstall } from "../pwa";

interface DockProps {
  /** Vista ativa da aplicação (id do `AppView`). */
  active: string;
  onOpen: (id: string) => void;
}

/** Tamanho mínimo dos ícones (alvo tátil confortável em ecrãs pequenos). */
const MIN_ICON_SIZE = 42;

/** Mede a janela, para o dock se adaptar a ecrãs pequenos. */
function useViewport() {
  const [size, setSize] = useState(() => ({
    width: typeof window === "undefined" ? 0 : window.innerWidth,
    height: typeof window === "undefined" ? 0 : window.innerHeight,
  }));
  useEffect(() => {
    const update = () => setSize({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
    };
  }, []);
  return size;
}

/**
 * Ajusta o tamanho dos ícones ao espaço disponível.
 *
 * `scrolling` fica a `true` quando nem no tamanho mínimo o dock cabe: nesse caso
 * o dock passa a poder ser arrastado lateralmente (e a ampliação é desligada,
 * porque nenhum ícone pode crescer sem ficar cortado).
 */
function fitDock(desired: number, items: number, available: number) {
  if (!available) return { iconSize: desired, scrolling: false };
  // size × fator ≈ largura total (ícones + folgas proporcionais + separador + padding)
  const factor = items + 1.64 + (items + 2) * 0.154 + 0.38 + 0.2;
  const fits = Math.floor(available / factor);
  const iconSize = Math.max(MIN_ICON_SIZE, Math.min(desired, fits));
  return { iconSize, scrolling: iconSize < desired };
}

/** Vistas que não têm ícone próprio e herdam o realce de outra aplicação. */
const ALIAS: Record<string, string> = {
  "ticker-detail": "tickers",
  "company-detail": "entities-search",
  "companies-dashboard": "entities-search",
  contracts: "contracts-search",
  "contracts-list": "contracts-search",
  "companies-search": "entities-search",
};

const POSITION_LABELS: Record<DockPosition, string> = {
  bottom: "Baixo",
  left: "Esquerda",
  right: "Direita",
};

export function Dock({ active, onOpen }: DockProps) {
  const { prefs, visible, parked, set, move, park, unpark, reset } = useDock();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [revealed, setRevealed] = useState(!prefs.autoHide);
  const [visited, setVisited] = useState<string[]>([]);
  const [hovered, setHovered] = useState<DockApp | null>(null);
  const [menu, setMenu] = useState<{ app: DockApp | null; x: number; y: number } | null>(null);
  const [bouncing, setBouncing] = useState<string | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [finePointer, setFinePointer] = useState(false);
  const { mode: sidebarMode } = useSidebar();
  const { windowMode, setWindowMode } = useWindowMode();
  const { user, updateProfile } = useAuth();
  /** O modo janelas é uma preferência de conta: guardar aqui evita que um
   *  recarregamento reponha o valor antigo. */
  const changeWindowMode = (value: boolean) => {
    setWindowMode(value);
    if (user) {
      void updateProfile({ preferences: { window_mode: value } }).catch(() => {});
    }
  };
  const { windows: openWindows, restore: restoreWindowFocus } = useWindows();
  const { isFullscreen, supported: fullscreenSupported, toggle: toggleFullscreen } = useFullscreen();
  const { canInstall, standalone, installed: appInstalled, install } = usePwaInstall();

  const vertical = prefs.position !== "bottom";
  const editing = settingsOpen;
  const viewport = useViewport();

  /** Tamanho efetivo dos ícones (o utilizador define o máximo; o ecrã manda). */
  const fitted = useMemo(() => {
    const available = vertical
      ? Math.max(220, viewport.height - 150)
      : Math.max(220, viewport.width - 24);
    return fitDock(prefs.iconSize, visible.length, available);
  }, [prefs.iconSize, visible.length, vertical, viewport.width, viewport.height]);
  const iconSize = fitted.iconSize;

  /** Em ecrãs táteis não há rato: sem ampliação e sem esconder ao sair. */
  const autoHideActive = prefs.autoHide && finePointer;
  const tooltipsActive = prefs.tooltips && finePointer;

  /** Largura reservada à barra lateral (o dock não a deve tapar). */
  const sidebarGutter = sidebarMode === "hidden" ? "" : sidebarMode === "rail" ? "md:pl-[72px]" : "md:pl-[268px]";

  /* ------------------------------------------------------------------ refs */
  const shelfRef = useRef<HTMLDivElement | null>(null);
  const trayRef = useRef<HTMLSpanElement | null>(null);
  const tileRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const centersRef = useRef<number[]>([]);
  const baseRef = useRef<number>(prefs.iconSize + 8);
  const sizeRef = useRef<number>(prefs.iconSize);
  /** Geometria do tabuleiro e do conjunto de ícones, nas coordenadas do dock. */
  const trayRestRef = useRef({ pad: 10, box: 0, stripStart: 0, stripEnd: 0 });
  const pointerRef = useRef<number | null>(null);
  const hoverIndexRef = useRef<number | null>(null);

  /* ------------------------------------------------------------- ambiente */
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(hover: hover) and (pointer: fine)");
    const sync = () => setFinePointer(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (autoHideActive) setRevealed(false);
    else setRevealed(true);
  }, [autoHideActive]);

  useEffect(() => {
    if (!active) return;
    setVisited((prev) => (prev.includes(active) ? prev : [...prev, active]));
  }, [active]);

  /* ------------------------------------------------- ampliação (por frame) */
  const magnifying = prefs.magnification && finePointer && !editing && !fitted.scrolling;

  /** Coloca o tabuleiro no eixo do dock (`start`/`size` em px). */
  const setTray = useCallback(
    (start: number, size: number) => {
      const tray = trayRef.current;
      if (!tray) return;
      if (vertical) {
        tray.style.top = `${start.toFixed(2)}px`;
        tray.style.height = `${size.toFixed(2)}px`;
      } else {
        tray.style.left = `${start.toFixed(2)}px`;
        tray.style.width = `${size.toFixed(2)}px`;
      }
    },
    [vertical]
  );

  const measure = useCallback(() => {
    const els = tileRefs.current;
    for (const el of els) {
      if (el) el.style.transform = "";
    }
    const rects = els.map((el) => (el ? el.getBoundingClientRect() : null));
    const centers: number[] = [];
    rects.forEach((rect) => {
      if (!rect) return;
      centers.push(vertical ? rect.top + rect.height / 2 : rect.left + rect.width / 2);
    });
    const first = rects.find((rect) => rect !== null) ?? null;
    if (first) sizeRef.current = vertical ? first.height : first.width;
    centersRef.current = centers;
    baseRef.current =
      centers.length > 1 ? (centers[centers.length - 1] - centers[0]) / (centers.length - 1) : sizeRef.current;

    // Tabuleiro: em repouso cobre a caixa do dock; ao ampliar segue os ícones.
    const shelf = shelfRef.current;
    const tray = trayRef.current;
    if (shelf && tray && centers.length > 0 && first) {
      const styles = window.getComputedStyle(shelf);
      const pad = vertical ? parseFloat(styles.paddingTop) || 10 : parseFloat(styles.paddingLeft) || 10;
      const box = vertical ? shelf.clientHeight : shelf.clientWidth;
      const shelfStart = vertical ? shelf.getBoundingClientRect().top : shelf.getBoundingClientRect().left;
      trayRestRef.current = {
        pad,
        box,
        stripStart: centers[0] - sizeRef.current / 2 - shelfStart,
        stripEnd: centers[centers.length - 1] + sizeRef.current / 2 - shelfStart,
      };
      if (vertical) {
        tray.style.left = "";
        tray.style.width = "";
        tray.style.bottom = "auto";
        tray.style.top = "0px";
        tray.style.height = `${box}px`;
      } else {
        tray.style.top = "";
        tray.style.height = "";
        tray.style.left = "0px";
        tray.style.width = `${box}px`;
      }
    }

    if (shelfRef.current) shelfRef.current.dataset.magnifying = "false";
    pointerRef.current = null;
    hoverIndexRef.current = null;
  }, [vertical]);

  const placeTip = useCallback(() => {
    const tip = tipRef.current;
    const shelf = shelfRef.current;
    const index = hoverIndexRef.current;
    if (!tip || !shelf || index === null) return;
    const tile = tileRefs.current[index];
    if (!tile) return;
    const r = tile.getBoundingClientRect();
    const s = shelf.getBoundingClientRect();
    if (prefs.position === "bottom") {
      tip.style.left = `${r.left + r.width / 2 - s.left}px`;
      tip.style.top = `${r.top - s.top - 8}px`;
      tip.style.transform = "translate(-50%, -100%)";
    } else if (prefs.position === "left") {
      tip.style.left = `${r.right - s.left + 10}px`;
      tip.style.top = `${r.top + r.height / 2 - s.top}px`;
      tip.style.transform = "translate(0, -50%)";
    } else {
      tip.style.left = `${r.left - s.left - 10}px`;
      tip.style.top = `${r.top + r.height / 2 - s.top}px`;
      tip.style.transform = "translate(-100%, -50%)";
    }
  }, [prefs.position]);

  /** Escreve as transformações de todos os ícones para o frame atual. */
  const applyMagnification = useCallback(() => {
    const pointer = pointerRef.current;
    const centers = centersRef.current;
    if (pointer === null || centers.length === 0) return;

    const size = sizeRef.current || prefs.iconSize;
    const sigma = Math.max(14, (prefs.magnifySpread * size) / 2.5);
    const peak = prefs.magnify;

    const scales = centers.map((center) => {
      const distance = Math.abs(pointer - center);
      return 1 + (peak - 1) * Math.exp(-(distance * distance) / (2 * sigma * sigma));
    });

    // Geometria do "empurrão": cada ícone alarga-se e empurra os seguintes.
    const translates = new Array<number>(scales.length);
    let accumulated = 0;
    let anchor = 0;
    for (let i = 0; i < scales.length; i += 1) {
      translates[i] = accumulated + (size * (scales[i] - 1)) / 2;
      accumulated += size * (scales[i] - 1);
    }
    // Mantém o ponto sob o cursor parado (evita o "deslizar" da barra).
    let index = scales.findIndex((_, i) => pointer <= centers[i] + size / 2);
    if (index < 0) index = scales.length - 1;
    anchor = translates[index] + (pointer - centers[index]) * (scales[index] - 1);

    if (shelfRef.current) shelfRef.current.dataset.magnifying = "true";
    for (let i = 0; i < scales.length; i += 1) {
      const el = tileRefs.current[i];
      if (!el) continue;
      const offset = translates[i] - anchor;
      el.style.transform = vertical
        ? `translateY(${offset.toFixed(2)}px) scale(${scales[i].toFixed(3)})`
        : `translateX(${offset.toFixed(2)}px) scale(${scales[i].toFixed(3)})`;
    }

    // O tabuleiro acompanha o conjunto: desloca-se com o cursor e cresce.
    // Os extremos do conjunto incluem a meia-expansão de cada ícone (`h`), porque
    // a transformação escala a partir do centro de cada tile.
    const rest = trayRestRef.current;
    if (rest.box > 0) {
      const last = scales.length - 1;
      const headH = (size * (scales[0] - 1)) / 2;
      const tailH = (size * (scales[last] - 1)) / 2;
      const start = Math.min(rest.stripStart + translates[0] - anchor - headH, rest.pad);
      const end = Math.max(rest.stripEnd + translates[last] - anchor + tailH, rest.box - rest.pad);
      setTray(start - rest.pad, end - start + 2 * rest.pad);
    }
  }, [prefs.iconSize, prefs.magnify, prefs.magnifySpread, setTray, vertical]);

  const magnifyingRef = useRef(magnifying);
  magnifyingRef.current = magnifying;

  const frameRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);

  const runFrame = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (magnifyingRef.current) applyMagnification();
    placeTip();
  }, [applyMagnification, placeTip]);

  const scheduleFrame = useCallback(() => {
    if (frameRef.current !== null || timerRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(runFrame);
    // Rede de segurança: num separador oculto o rAF não corre e o dock ficaria
    // preso a meio da ampliação.
    timerRef.current = window.setTimeout(runFrame, 34);
  }, [runFrame]);

  const resetMagnification = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (shelfRef.current) shelfRef.current.dataset.magnifying = "false";
    for (const el of tileRefs.current) {
      if (el) el.style.transform = "";
    }
    const rest = trayRestRef.current;
    setTray(0, rest.box);
    pointerRef.current = null;
    hoverIndexRef.current = null;
  }, [setTray]);

  useLayoutEffect(() => {
    measure();
  }, [measure, visible.length, iconSize, prefs.position, editing]);

  useEffect(() => {
    const onResize = () => measure();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [measure]);

  useEffect(() => {
    if (!magnifying) resetMagnification();
  }, [magnifying, resetMagnification]);

  // Recoloca a etiqueta sempre que ela muda de ícone (ou de tamanho).
  useLayoutEffect(() => {
    if (!hovered) return;
    const id = window.requestAnimationFrame(() => placeTip());
    return () => window.cancelAnimationFrame(id);
  }, [hovered, iconSize, prefs.position, placeTip]);

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const shelf = shelfRef.current;
    if (!shelf || centersRef.current.length === 0) return;
    if (magnifying) {
      pointerRef.current = vertical ? event.clientY : event.clientX;
      let nearest = 0;
      let best = Number.POSITIVE_INFINITY;
      centersRef.current.forEach((center, i) => {
        const distance = Math.abs(pointerRef.current! - center);
        if (distance < best) {
          best = distance;
          nearest = i;
        }
      });
      hoverIndexRef.current = nearest;
    }
    scheduleFrame();
  };

  const handlePointerLeave = () => {
    setHovered(null);
    resetMagnification();
  };

  /* -------------------------------------------------------------- ações */
  const activeId = useMemo(() => {
    if (visible.some((app) => app.id === active)) return active;
    return ALIAS[active] ?? active;
  }, [active, visible]);

  /** Aplicações com janela aberta (indicador do dock). */
  const openViews = useMemo(() => new Set(openWindows.map((item) => item.view)), [openWindows]);
  /** Vista com a janela em foco (para realce quando o modo janelas está ativo). */
  const focusedView = useMemo(
    () => [...openWindows].filter((item) => !item.minimized).sort((a, b) => b.z - a.z)[0]?.view ?? null,
    [openWindows],
  );
  const highlightedView = windowMode ? focusedView ?? active : activeId;

  const openApp = (app: DockApp) => {
    setMenu(null);
    setBouncing(app.id);
    window.setTimeout(() => setBouncing((current) => (current === app.id ? null : current)), 700);
    // Com a janela já aberta, clicar no ícone foca-a (ou restaura, se minimizada).
    const existing = windowMode ? windowFor(app.id) : undefined;
    if (existing) {
      restoreWindowFocus(app.id);
      return;
    }
    onOpen(app.id);
  };

  useEffect(() => {
    if (!menu && !settingsOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenu(null);
      setSettingsOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menu, settingsOpen]);

  /* ------------------------------------------------------------- arrumação */
  const commitDrop = (target: number) => {
    if (dragFrom !== null && dragFrom !== target) move(dragFrom, target);
    setDragFrom(null);
    setDragOver(null);
  };

  /* ------------------------------------------------------------- geometria */
  const wrapperClass = [
    "fixed z-[60] flex pointer-events-none",
    // O dock centra-se sobre a área de trabalho: não tapa a barra lateral.
    sidebarGutter,
    prefs.position === "bottom"
      ? "dock-safe-bottom inset-x-0 bottom-0 justify-center"
      : prefs.position === "left"
        ? "inset-y-0 left-0 flex-col justify-center pl-2"
        : "inset-y-0 right-0 flex-col justify-center pr-2",
  ].join(" ");

  const popoverClass = [
    "dock-popover absolute z-[70] pointer-events-auto rounded-2xl border border-white/12",
    prefs.position === "bottom"
      ? "bottom-full right-0 mb-3"
      : prefs.position === "left"
        ? "left-full bottom-0 ml-3"
        : "right-full bottom-0 mr-3",
  ].join(" ");

  return (
    <>
      {autoHideActive && (
        <div
          className={[
            "fixed z-[58]",
            prefs.position === "bottom"
              ? "inset-x-0 bottom-0 h-3"
              : prefs.position === "left"
                ? "inset-y-0 left-0 w-3"
                : "inset-y-0 right-0 w-3",
          ].join(" ")}
          onMouseEnter={() => setRevealed(true)}
          aria-hidden="true"
        />
      )}

      {settingsOpen && (
        <div className="fixed inset-0 z-[55]" onMouseDown={() => setSettingsOpen(false)} aria-hidden="true" />
      )}

      <div className={wrapperClass}>
        <div
          className="dock-anchor pointer-events-auto relative min-w-0 max-w-full max-h-full"
          data-position={prefs.position}
          data-hidden={autoHideActive && !revealed && !settingsOpen ? "true" : "false"}
          onMouseEnter={() => setRevealed(true)}
          onMouseLeave={() => {
            if (autoHideActive && !settingsOpen) setRevealed(false);
          }}
        >
          <div
            ref={shelfRef}
            role="toolbar"
            aria-label="Dock de aplicações"
            data-position={prefs.position}
            data-magnifying="false"
            data-scroll={fitted.scrolling ? "true" : "false"}
            className={[
              "dock-shelf relative flex items-end",
              fitted.scrolling ? "dock-scroll" : "",
              vertical ? "flex-col" : "flex-row",
              iconSize >= 66 ? "gap-3 p-3.5" : "gap-2 p-2.5",
              "rounded-[26px]",
            ].join(" ")}
            onPointerMove={handlePointerMove}
            onPointerLeave={handlePointerLeave}
            onContextMenu={(event) => {
              event.preventDefault();
              setMenu({ app: null, x: event.clientX, y: event.clientY });
            }}
          >            <span ref={trayRef} className="dock-tray" aria-hidden="true" />            {visible.map((app, index) => {
              const isActive = app.id === highlightedView;
              const isRunning = windowMode ? openViews.has(app.id) : visited.includes(app.id);
              const Icon = app.icon;
              return (
                <div
                  key={app.id}
                  className="relative flex flex-col items-center"
                  draggable={editing}
                  onDragStart={() => setDragFrom(index)}
                  onDragEnd={() => {
                    setDragFrom(null);
                    setDragOver(null);
                  }}
                  onDragOver={(event) => {
                    if (dragFrom === null) return;
                    event.preventDefault();
                    setDragOver(index);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    commitDrop(index);
                  }}
                  style={{ opacity: dragFrom === index ? 0.35 : 1 }}
                >
                  {editing && index === dragOver && dragFrom !== null && (
                    <span
                      className={[
                        "absolute rounded-full bg-teal-400/80",
                        vertical ? "left-1/2 h-full w-0.5 -translate-x-1/2" : "top-1/2 h-full w-0.5 -translate-y-1/2",
                      ].join(" ")}
                      style={vertical ? undefined : { left: index > dragFrom ? `${iconSize / 2 + 5}px` : `${-iconSize / 2 - 5}px` }}
                      aria-hidden="true"
                    />
                  )}
                  <button
                    ref={(el) => {
                      tileRefs.current[index] = el;
                    }}
                    type="button"
                    draggable={false}
                    onClick={() => openApp(app)}
                    onMouseEnter={() => {
                      setHovered(tooltipsActive ? app : null);
                      if (tooltipsActive) hoverIndexRef.current = index;
                    }}
                    onMouseLeave={() => setHovered(null)}
                    onContextMenu={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setMenu({ app, x: event.clientX, y: event.clientY });
                    }}
                    aria-label={`${app.label} — ${app.hint}`}
                    aria-current={isActive ? "page" : undefined}
                    title={tooltipsActive ? undefined : `${app.label} — ${app.hint}`}
                    className={[
                      "dock-tile dock-app group relative grid place-items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70",
                      bouncing === app.id ? "is-bouncing" : "",
                    ].join(" ")}
                    style={{ width: iconSize, height: iconSize, borderRadius: iconSize * 0.28 }}
                  >
                    <span
                      className={[
                        "absolute inset-0 overflow-hidden bg-gradient-to-br",
                        app.gradient,
                        prefs.reflection ? "dock-tile-inset" : "",
                      ].join(" ")}
                      style={{ borderRadius: "inherit" }}
                      aria-hidden="true"
                    />
                    <span className="dock-icon relative z-[1] grid place-items-center text-white drop-shadow">
                      <Icon size={Math.round(iconSize * 0.5)} strokeWidth={1.9} />
                    </span>
                    {isActive && (
                      <span
                        className="pointer-events-none absolute inset-0 ring-2 ring-white/70"
                        style={{ borderRadius: "inherit", boxShadow: `0 0 22px rgba(${app.accent},0.55)` }}
                        aria-hidden="true"
                      />
                    )}
                  </button>

                  {prefs.indicators && (
                    <span
                      aria-hidden="true"
                      className={[
                        "dock-dot absolute rounded-full transition-all",
                        isActive
                          ? "h-1.5 w-1.5 opacity-100"
                          : isRunning
                            ? "h-1 w-1 opacity-70"
                            : "h-1 w-1 opacity-0",
                      ].join(" ")}
                      style={{
                        background: isActive ? "rgb(52 211 153)" : "rgb(148 163 184)",
                        ...(vertical
                          ? prefs.position === "left"
                            ? { left: -6, top: "50%", transform: "translateY(-50%)" }
                            : { right: -6, top: "50%", transform: "translateY(-50%)" }
                          : { bottom: -5, left: "50%", transform: "translateX(-50%)" }),
                      }}
                    />
                  )}
                </div>
              );
            })}

            <span
              aria-hidden="true"
              className={[
                "relative shrink-0 rounded-full bg-white/12",
                vertical ? "h-px w-8 self-center" : "h-8 w-px self-center",
              ].join(" ")}
            />

            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              aria-label="Preferências do dock"
              aria-expanded={settingsOpen}
              title="Preferências do dock"
              className="dock-tile relative grid shrink-0 place-items-center bg-white/8 text-muted-foreground transition hover:bg-white/14 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70"
              style={{
                width: iconSize * 0.82,
                height: iconSize * 0.82,
                borderRadius: iconSize * 0.24,
              }}
            >
              <Settings size={Math.round(iconSize * 0.4)} />
            </button>

            {fullscreenSupported && (
              <button
                type="button"
                onClick={() => void toggleFullscreen()}
                aria-label={isFullscreen ? "Sair do ecrã inteiro" : "Ecrã inteiro"}
                aria-pressed={isFullscreen}
                title={isFullscreen ? "Sair do ecrã inteiro" : "Ecrã inteiro"}
                className={[
                  "dock-tile relative grid shrink-0 place-items-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70",
                  isFullscreen
                    ? "bg-teal-400/25 text-teal-100 hover:bg-teal-400/35"
                    : "bg-white/8 text-muted-foreground hover:bg-white/14 hover:text-foreground",
                ].join(" ")}
                style={{
                  width: iconSize * 0.82,
                  height: iconSize * 0.82,
                  borderRadius: iconSize * 0.24,
                }}
              >
                {isFullscreen ? (
                  <Minimize2 size={Math.round(iconSize * 0.4)} />
                ) : (
                  <Maximize2 size={Math.round(iconSize * 0.4)} />
                )}
              </button>
            )}

            {fitted.scrolling && <span className="dock-fade" aria-hidden="true" />}

            {hovered && tooltipsActive && (
              <div ref={tipRef} className="dock-tip pointer-events-none" role="presentation">
                <span className="font-medium">{hovered.label}</span>
                <span className="dock-tip-hint">{hovered.hint}</span>
              </div>
            )}
          </div>

          {settingsOpen && (
            <DockPreferences
              className={popoverClass}
              prefs={prefs}
              visible={visible}
              parked={parked}
              onChange={set}
              onMove={move}
              onPark={park}
              onUnpark={unpark}
              onReset={reset}
              onClose={() => setSettingsOpen(false)}
              fullscreen={{ isFullscreen, supported: fullscreenSupported, toggle: () => void toggleFullscreen() }}
              pwa={{
                canInstall,
                standalone,
                installed: appInstalled,
                install: () => void install(),
              }}
              finePointer={finePointer}
              windowMode={windowMode}
              onWindowModeChange={changeWindowMode}
            />
          )}
        </div>
      </div>

      {menu && (
        <>
          <div className="fixed inset-0 z-[80]" onMouseDown={() => setMenu(null)} aria-hidden="true" />
          <div
            role="menu"
            className="fixed z-[81] min-w-[220px] overflow-hidden rounded-xl border border-white/10 bg-[#14161b]/95 p-1 shadow-2xl backdrop-blur-xl"
            style={{
              left: Math.min(menu.x, window.innerWidth - 240),
              top: Math.min(menu.y, window.innerHeight - 140),
            }}
          >
            {menu.app ? (
              <>
                <p className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                  {menu.app.label}
                </p>
                <button
                  role="menuitem"
                  onClick={() => {
                    const app = menu.app;
                    setMenu(null);
                    if (app) openApp(app);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <Plus size={14} /> Abrir
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    const app = menu.app;
                    setMenu(null);
                    if (app) park(app.id);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-rose-300 transition hover:bg-rose-400/10"
                >
                  <X size={14} /> Retirar do dock
                </button>
                {windowMode && menu.app && windowFor(menu.app.id) && (
                  <>
                    <div className="my-1 h-px bg-white/8" />
                    <button
                      role="menuitem"
                      onClick={() => {
                        const app = menu.app;
                        setMenu(null);
                        if (app) minimizeWindow(app.id);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                    >
                      <Minus size={14} /> Minimizar janela
                    </button>
                    <button
                      role="menuitem"
                      onClick={() => {
                        const app = menu.app;
                        setMenu(null);
                        if (app) focusWindow(app.id);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                    >
                      <PanelLeftOpen size={14} /> Trazer para a frente
                    </button>
                    <button
                      role="menuitem"
                      onClick={() => {
                        const app = menu.app;
                        setMenu(null);
                        if (app) closeWindow(app.id);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-rose-300 transition hover:bg-rose-400/10"
                    >
                      <X size={14} /> Fechar janela
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenu(null);
                    setSettingsOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <SlidersHorizontal size={14} /> Preferências do dock…
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenu(null);
                    set(prefs.position === "bottom" ? { position: "left" } : prefs.position === "left" ? { position: "right" } : { position: "bottom" });
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <GripVertical size={14} /> Mudar posição ({POSITION_LABELS[prefs.position]})
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenu(null);
                    set({ autoHide: !prefs.autoHide });
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <Pin size={14} /> {prefs.autoHide ? "Mostrar sempre" : "Ocultar automaticamente"}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ painel */

interface DockPreferencesProps {
  className: string;
  prefs: ReturnType<typeof useDock>["prefs"];
  visible: DockApp[];
  parked: DockApp[];
  onChange: (patch: Partial<ReturnType<typeof useDock>["prefs"]>) => void;
  onMove: (from: number, to: number) => void;
  onPark: (id: string) => void;
  onUnpark: (id: string) => void;
  onReset: () => void;
  onClose: () => void;
  fullscreen: { isFullscreen: boolean; supported: boolean; toggle: () => void };
  pwa: { canInstall: boolean; standalone: boolean; installed: boolean; install: () => void };
  finePointer: boolean;
  windowMode: boolean;
  onWindowModeChange: (value: boolean) => void;
}

function DockPreferences({
  className,
  prefs,
  visible,
  parked,
  onChange,
  onMove,
  onPark,
  onUnpark,
  onReset,
  onClose,
  fullscreen,
  pwa,
  finePointer,
  windowMode,
  onWindowModeChange,
}: DockPreferencesProps) {
  const { mode: sidebarMode, setMode: setSidebarMode } = useSidebar();
  const viewport = useViewport();

  /* O dock adapta o tamanho ao ecrã: o painel explica o que está a acontecer. */
  const fitted = useMemo(() => {
    const vertical = prefs.position !== "bottom";
    const available = vertical
      ? Math.max(220, viewport.height - 150)
      : Math.max(220, viewport.width - 24);
    return fitDock(prefs.iconSize, visible.length, available);
  }, [prefs.iconSize, prefs.position, visible.length, viewport.width, viewport.height]);

  return (
    <div className={className} style={{ width: 336 }}>
      <header className="flex items-center justify-between border-b border-white/8 px-4 py-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-teal-300" />
          <p className="text-sm font-semibold">Dock</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar preferências"
          className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-white/8 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <X size={15} />
        </button>
      </header>

      <div className="max-h-[62vh] space-y-5 overflow-y-auto px-4 py-4">
        <section className="space-y-2.5">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Posição</p>
          <div className="flex gap-1 rounded-xl bg-white/5 p-1">
            {(["bottom", "left", "right"] as DockPosition[]).map((position) => (
              <button
                key={position}
                type="button"
                onClick={() => onChange({ position })}
                aria-pressed={prefs.position === position}
                className={[
                  "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                  prefs.position === position ? "bg-teal-400/20 text-teal-200" : "text-muted-foreground hover:bg-white/5",
                ].join(" ")}
              >
                {POSITION_LABELS[position]}
              </button>
            ))}
          </div>
          {fitted.scrolling ? (
            <div className="space-y-1.5 rounded-xl border border-amber-400/25 bg-amber-400/10 p-2.5">
              <p className="text-[11px] leading-snug text-amber-200">
                Neste ecrã o dock não cabe todo: os ícones ficam no tamanho mínimo ({fitted.iconSize}px) e a barra pode
                ser deslizada lateralmente. Retire aplicações do dock para que caiba tudo.
              </p>
            </div>
          ) : fitted.iconSize < prefs.iconSize ? (
            <p className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.04] p-2.5 text-[11px] leading-snug text-muted-foreground">
              <MonitorSmartphone size={13} className="mt-0.5 shrink-0 text-teal-300" />
              Neste ecrã os ícones são mostrados a {fitted.iconSize}px (definiu {prefs.iconSize}px) para o dock caber.
            </p>
          ) : null}
        </section>

        <section className="space-y-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Aparência</p>
          <SliderRow
            label="Tamanho dos ícones"
            value={prefs.iconSize}
            min={ICON_SIZE_RANGE.min}
            max={ICON_SIZE_RANGE.max}
            step={1}
            suffix="px"
            onChange={(iconSize) => onChange({ iconSize })}
          />
          {fitted.iconSize < prefs.iconSize && (
            <p className="text-[11px] text-muted-foreground">
              Neste ecrã o valor efetivo é <span className="text-foreground">{fitted.iconSize}px</span>.
            </p>
          )}
          <SliderRow
            label="Ampliação máxima"
            value={Number(prefs.magnify.toFixed(2))}
            min={MAGNIFY_RANGE.min}
            max={MAGNIFY_RANGE.max}
            step={0.05}
            suffix="×"
            disabled={!prefs.magnification}
            onChange={(magnify) => onChange({ magnify })}
          />
          <SliderRow
            label="Alcance da ampliação"
            value={Number(prefs.magnifySpread.toFixed(2))}
            min={SPREAD_RANGE.min}
            max={SPREAD_RANGE.max}
            step={0.1}
            suffix=""
            disabled={!prefs.magnification}
            onChange={(magnifySpread) => onChange({ magnifySpread })}
          />
          <ToggleRow label="Ampliação ao passar o rato" checked={prefs.magnification} onChange={(magnification) => onChange({ magnification })} />
          <ToggleRow label="Reflexo nos ícones" checked={prefs.reflection} onChange={(reflection) => onChange({ reflection })} />
        </section>

        <section className="space-y-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Comportamento</p>
          <ToggleRow
            label="Ocultar automaticamente"
            hint={finePointer ? undefined : "Não se aplica a ecrãs táteis (não há rato para revelar o dock)."}
            checked={prefs.autoHide}
            onChange={(autoHide) => onChange({ autoHide })}
          />
          <ToggleRow
            label="Etiquetas ao passar o rato"
            hint={finePointer ? undefined : "Em ecrãs táteis aparece o nome ao manter premido."}
            checked={prefs.tooltips}
            onChange={(tooltips) => onChange({ tooltips })}
          />
          <ToggleRow label="Indicadores de apps abertas" checked={prefs.indicators} onChange={(indicators) => onChange({ indicators })} />
        </section>

        <section className="space-y-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Interface</p>
          <ToggleRow
            label="Abrir páginas em janelas"
            hint="Cada aplicação abre numa janela arrastável, redimensionável e minimizável."
            checked={windowMode}
            onChange={onWindowModeChange}
          />
          <div className="space-y-1.5">
            <span className="text-xs text-muted-foreground">Barra lateral</span>
            <div className="flex gap-1 rounded-xl bg-white/5 p-1">
              {([
                { value: "expanded", label: "Expandida" },
                { value: "rail", label: "Só ícones" },
                { value: "hidden", label: "Escondida" },
              ] as const).map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setSidebarMode(option.value)}
                  aria-pressed={sidebarMode === option.value}
                  title={option.value === "hidden" ? "Ctrl+B alterna este modo" : undefined}
                  className={[
                    "flex-1 rounded-lg px-2 py-1.5 text-[11px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                    sidebarMode === option.value
                      ? "bg-teal-400/20 text-teal-200"
                      : "text-muted-foreground hover:bg-white/5",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          {fullscreen.supported && (
            <ToggleRow label="Ecrã inteiro" checked={fullscreen.isFullscreen} onChange={() => fullscreen.toggle()} />
          )}
          {pwa.standalone || pwa.installed ? (
            <p className="flex items-center gap-2 text-[11px] text-teal-200">
              <Check size={13} /> Aplicação instalada
            </p>
          ) : pwa.canInstall ? (
            <button
              type="button"
              onClick={() => pwa.install()}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-teal-300/30 bg-teal-400/10 px-3 py-2 text-xs text-teal-100 transition hover:bg-teal-400/20"
            >
              <MonitorSmartphone size={14} /> Instalar aplicação
            </button>
          ) : (
            <p className="text-[11px] leading-snug text-muted-foreground">
              Para instalar: menu do browser → «Instalar aplicação». No iPhone: Partilhar → «Adicionar ao ecrã principal».
            </p>
          )}
        </section>

        <section className="space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            No dock — arraste os ícones para reordenar
          </p>
          <ul className="space-y-1">
            {visible.map((app, index) => (
              <li
                key={app.id}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", app.id);
                  event.currentTarget.dataset.dragging = "true";
                }}
                onDragEnd={(event) => {
                  delete event.currentTarget.dataset.dragging;
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  const from = visible.findIndex((item) => item.id === event.dataTransfer.getData("text/plain"));
                  if (from >= 0 && from !== index) onMove(from, index);
                }}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition hover:bg-white/5 data-[dragging=true]:opacity-40"
              >
                <GripVertical size={13} className="cursor-grab text-muted-foreground" />
                <MiniTile app={app} />
                <span className="flex-1 truncate text-xs">{app.label}</span>
                <button
                  type="button"
                  onClick={() => onMove(index, index - 1)}
                  disabled={index === 0}
                  aria-label={`Mover ${app.label} para cima`}
                  className="rounded p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground disabled:opacity-30"
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => onMove(index, index + 1)}
                  disabled={index === visible.length - 1}
                  aria-label={`Mover ${app.label} para baixo`}
                  className="rounded p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground disabled:opacity-30"
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => onPark(app.id)}
                  aria-label={`Retirar ${app.label} do dock`}
                  title="Retirar do dock"
                  className="rounded p-1 text-muted-foreground transition hover:bg-rose-400/10 hover:text-rose-300"
                >
                  <EyeOff size={13} />
                </button>
              </li>
            ))}
          </ul>
        </section>

        {parked.length > 0 && (
          <section className="space-y-2">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Fora do dock</p>
            <ul className="space-y-1">
              {parked.map((app) => (
                <li key={app.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition hover:bg-white/5">
                  <span className="w-[13px]" />
                  <MiniTile app={app} muted />
                  <span className="flex-1 truncate text-xs text-muted-foreground">{app.label}</span>
                  <button
                    type="button"
                    onClick={() => onUnpark(app.id)}
                    aria-label={`Adicionar ${app.label} ao dock`}
                    title="Adicionar ao dock"
                    className="rounded p-1 text-muted-foreground transition hover:bg-teal-400/10 hover:text-teal-300"
                  >
                    <Plus size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <button
          type="button"
          onClick={onReset}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs text-muted-foreground transition hover:bg-white/5 hover:text-foreground"
        >
          <RotateCcw size={13} /> Restaurar predefinições
        </button>
      </div>
    </div>
  );
}

function MiniTile({ app, muted }: { app: DockApp; muted?: boolean }) {
  const Icon = app.icon;
  return (
    <span
      className={[
        "grid h-6 w-6 shrink-0 place-items-center rounded-[7px] bg-gradient-to-br text-white",
        app.gradient,
        muted ? "opacity-45" : "",
      ].join(" ")}
      aria-hidden="true"
    >
      <Icon size={13} strokeWidth={2} />
    </span>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  suffix,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className={["block space-y-1", disabled ? "opacity-45" : ""].join(" ")}>
      <span className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums text-foreground">
          {value}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="dock-range w-full"
      />
    </label>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="min-w-0">
        <span className="block text-xs text-muted-foreground">{label}</span>
        {hint && <span className="mt-0.5 block text-[10px] leading-snug text-muted-foreground/70">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={[
          "relative h-5 w-9 shrink-0 rounded-full border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
          checked ? "border-teal-300/40 bg-teal-400/70" : "border-white/12 bg-white/10",
        ].join(" ")}
      >
        <span
          className={[
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all",
            checked ? "left-[18px]" : "left-0.5",
          ].join(" ")}
        />
      </button>
    </div>
  );
}
