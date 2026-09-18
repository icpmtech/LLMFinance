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
import { useGlass, useSidebar, useWindow3d, useWindowMode, useWindowStyle } from "../layout";
import { StartMenu } from "./StartMenu";
import { closeWindow, estimateWorkspace, focusWindow, minimizeWindow, toggleMaximizeWindow, useWindows, windowFor } from "../windows";
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

/** Largura de uma miniatura de janela minimizada, em "ícones". */
const MINI_WIDTH_UNITS = 1.34;

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
  /** Relógio da bandeja (só usado na barra de tarefas do Windows). */
  const [now, setNow] = useState(() => new Date());
  const [hovered, setHovered] = useState<DockApp | null>(null);
  const [menu, setMenu] = useState<{ app: DockApp | null; view?: string | null; x: number; y: number } | null>(null);
  const [bouncing, setBouncing] = useState<string | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [finePointer, setFinePointer] = useState(false);
  /** Menu Iniciar (Windows 11): painel flutuante sobre o ambiente de trabalho. */
  const [startOpen, setStartOpen] = useState(false);
  const { mode: sidebarMode } = useSidebar();
  const { windowMode, setWindowMode } = useWindowMode();
  const { windowStyle } = useWindowStyle();
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
  /**
   * Barra de tarefas do Windows 11 (o aspeto escolhido nas preferências).
   *
   * É o mesmo dock — mesmas aplicações, mesma ordem, mesmas janelas minimizadas
   * — mas com o material e as métricas do Windows: barra plana tipo Mica, botões
   * quadrados de 40 px, indicador por baixo do ícone em vez do ponto do macOS e
   * sem ampliação nem etiquetas flutuantes.
   */
  const windowsTaskbar = windowStyle === "windows";

  /* O menu Iniciar só existe com a barra de tarefas do Windows. */
  useEffect(() => {
    if (!windowsTaskbar) setStartOpen(false);
  }, [windowsTaskbar]);

  /** Tamanho efetivo dos ícones (o utilizador define o máximo; o ecrã manda). */
  const fitted = useMemo(() => {
    const available = vertical
      ? Math.max(220, viewport.height - 150)
      : Math.max(220, viewport.width - 24);
    // As janelas minimizadas também ocupam dock: contam para o espaço necessário.
    const minis = windowMode && prefs.minimizedShelf ? openWindows.filter((item) => item.minimized).length : 0;
    const units = visible.length + minis * MINI_WIDTH_UNITS + (minis > 0 ? 0.4 : 0);
    return fitDock(prefs.iconSize, units, available);
  }, [openWindows, prefs.iconSize, prefs.minimizedShelf, visible.length, vertical, viewport.width, viewport.height, windowMode]);
  const iconSize = fitted.iconSize;

  /**
   * Tamanho dos botões da **barra de tarefas** (Windows).
   *
   * A barra ganha com o espaço livre: com poucas aplicações os botões crescem
   * (até 72 px, com o ícone maior), com muitas mantêm os 40 px mínimos — e a
   * barra passa a deslizar. A base é «Tamanho dos ícones» das preferências do
   * dock (que passa a valer nos dois aspetos) e a reserva fixa (Iniciar,
   * bandeja, relógio e folgas) é descontada antes de repartir o espaço.
   */
  const windowsTile = useMemo(() => {
    if (!windowsTaskbar) return iconSize;
    const available = Math.max(220, (vertical ? viewport.height : viewport.width) - 24);
    const base = Math.min(72, Math.max(40, Math.round(prefs.iconSize * 0.77)));
    // O tecto segue a preferência (não cresce mais do que ~25% acima dela).
    const cap = Math.max(base, Math.min(72, Math.round(prefs.iconSize * 1.25)));
    const tray = 2 * Math.max(28, Math.round(base * 0.8)) + 96 + base + 24;
    const apps = Math.max(1, visible.length);
    const perApp = (available - tray - 4 * (apps - 1)) / apps;
    return Math.max(base, Math.min(cap, Math.round(perApp)));
  }, [iconSize, prefs.iconSize, vertical, viewport.height, viewport.width, visible.length, windowsTaskbar]);

  /** Métricas da barra de tarefas (Windows) vs ícones do dock (macOS). */
  const tileSize = windowsTaskbar ? windowsTile : iconSize;
  const tileRadius = windowsTaskbar ? 4 : Math.round(iconSize * 0.28);
  const iconPx = windowsTaskbar ? Math.round(windowsTile * 0.55) : Math.round(iconSize * 0.5);
  /** Espessura da barra (altura em baixo, largura nas laterais): os botões mandam. */
  const barThickness = tileSize + 8;
  /** Botões de sistema da bandeja (preferências / ecrã inteiro). */
  const trayBtn = windowsTaskbar ? Math.max(28, Math.round(tileSize * 0.8)) : Math.round(iconSize * 0.82);
  const trayIcon = windowsTaskbar ? Math.max(14, Math.round(tileSize * 0.4)) : Math.round(iconSize * 0.4);

  /** Em ecrãs táteis não há rato: sem ampliação e sem esconder ao sair. */
  const autoHideActive = prefs.autoHide && finePointer;
  const tooltipsActive = prefs.tooltips && finePointer && !windowsTaskbar;

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

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  /* ------------------------------------------------- ampliação (por frame) */
  const magnifying = prefs.magnification && finePointer && !editing && !fitted.scrolling && !windowsTaskbar;

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

  /**
   * Janelas minimizadas, como miniaturas no dock (como no macOS).
   *
   * Ficam depois do separador das aplicações; um clique restaura a janela.
   * Fichas e quick look (vistas sem ícone próprio no dock) usam a informação
   * da aplicação correspondente quando existe.
   */
  const minimizedWindows = useMemo(() => {
    if (!windowMode || !prefs.minimizedShelf) return [];
    const catalog = new Map<string, DockApp>();
    [...visible, ...parked].forEach((app) => catalog.set(app.id, app));
    return openWindows
      .filter((item) => item.minimized)
      .map((item) => {
        const app = catalog.get(item.view) ?? catalog.get(ALIAS[item.view] ?? "");
        return {
          view: item.view,
          app,
          title: item.title ?? app?.label ?? item.view,
          gradient: app?.gradient ?? "from-slate-500/80 to-slate-700/85",
          accent: app?.accent ?? "148,163,184",
        };
      });
  }, [openWindows, parked, prefs.minimizedShelf, visible, windowMode]);

  /** Restaura (e foca) uma janela a partir da miniatura do dock. */
  const restoreFromDock = (view: string) => {
    setMenu(null);
    setBouncing(null);
    restoreWindowFocus(view);
  };

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

  /** Abre (ou foca/restaura) uma vista pelo id — usado pelo menu Iniciar. */
  const openViewById = (id: string) => {
    setMenu(null);
    const existing = windowMode ? windowFor(id) : undefined;
    if (existing) {
      restoreWindowFocus(id);
      return;
    }
    onOpen(id);
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
          data-hidden={autoHideActive && !revealed && !settingsOpen && !startOpen ? "true" : "false"}
          onMouseEnter={() => setRevealed(true)}
          onMouseLeave={() => {
            if (autoHideActive && !settingsOpen && !startOpen) setRevealed(false);
          }}
        >
          <div
            ref={shelfRef}
            role="toolbar"
            aria-label={windowsTaskbar ? "Barra de tarefas do IQ OS" : "Dock de aplicações"}
            data-position={prefs.position}
            data-style={windowsTaskbar ? "windows" : "macos"}
            data-magnifying="false"
            data-scroll={fitted.scrolling ? "true" : "false"}
            className={[
              "dock-shelf relative flex",
              windowsTaskbar ? "items-center" : "items-end",
              fitted.scrolling ? "dock-scroll" : "",
              vertical ? "flex-col" : "flex-row",
              windowsTaskbar
                ? vertical
                  ? "gap-1 py-1"
                  : "w-full gap-1 px-1.5"
                : iconSize >= 66
                  ? "gap-3 p-3.5"
                  : "gap-2 p-2.5",
              windowsTaskbar ? "rounded-none" : "rounded-[26px]",
            ].join(" ")}
            /* A barra ganha espessura com os botões (no Windows). */
            style={
              windowsTaskbar
                ? {
                    ...(vertical ? { width: barThickness } : { height: barThickness }),
                    ["--dock-ind" as string]: `${Math.round(tileSize * 0.4)}px`,
                    ["--dock-ind-min" as string]: `${Math.round(tileSize * 0.175)}px`,
                  }
                : undefined
            }
            onPointerMove={handlePointerMove}
            onPointerLeave={handlePointerLeave}
            onContextMenu={(event) => {
              event.preventDefault();
              setMenu({ app: null, x: event.clientX, y: event.clientY });
            }}
          >
            <span ref={trayRef} className="dock-tray" aria-hidden="true" />

            {/* Windows 11: botão Iniciar (abre o menu Iniciar flutuante) */}
            {windowsTaskbar && (
              <button
                type="button"
                onClick={() => setStartOpen((open) => !open)}
                aria-label="Menu Iniciar"
                aria-haspopup="dialog"
                aria-expanded={startOpen}
                data-open={startOpen || undefined}
                title="Menu Iniciar"
                className="dock-start grid shrink-0 place-items-center"
                style={{ width: tileSize, height: tileSize }}
              >
                {/* Marca do IQ OS: quatro quadrantes (o "Iniciar" da barra). */}
                <svg
                  width={Math.round(tileSize * 0.45)}
                  height={Math.round(tileSize * 0.45)}
                  viewBox="0 0 20 20"
                  aria-hidden="true"
                  fill="currentColor"
                >
                  <rect x="1" y="1" width="8" height="8" rx="1.6" />
                  <rect x="11" y="1" width="8" height="8" rx="1.6" />
                  <rect x="1" y="11" width="8" height="8" rx="1.6" />
                  <rect x="11" y="11" width="8" height="8" rx="1.6" />
                </svg>
              </button>
            )}

            {visible.map((app, index) => {
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
                    style={{ width: tileSize, height: tileSize, borderRadius: tileRadius }}
                  >
                    <span
                      className={[
                        "dock-tile-bg absolute inset-0 overflow-hidden bg-gradient-to-br",
                        app.gradient,
                        prefs.reflection ? "dock-tile-inset" : "",
                      ].join(" ")}
                      style={{ borderRadius: "inherit" }}
                      aria-hidden="true"
                    />
                    <span
                      className={[
                        "dock-icon relative z-[1] grid place-items-center",
                        windowsTaskbar ? "text-white" : "text-white drop-shadow",
                      ].join(" ")}
                    >
                      <Icon size={iconPx} strokeWidth={1.9} />
                    </span>
                    {isActive && !windowsTaskbar && (
                      <span
                        className="pointer-events-none absolute inset-0 ring-2 ring-white/70"
                        style={{ borderRadius: "inherit", boxShadow: `0 0 22px rgba(${app.accent},0.55)` }}
                        aria-hidden="true"
                      />
                    )}
                    {windowsTaskbar && prefs.indicators && (
                      /* Windows 11: barra por baixo do ícone (larga com foco, curta se
                         só estiver aberta, invisível se fechada). */
                      <span
                        aria-hidden="true"
                        className="dock-win-indicator"
                        data-state={isActive ? "active" : isRunning ? "running" : "idle"}
                      />
                    )}
                  </button>

                  {!windowsTaskbar && prefs.indicators && (
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

            {/* Janelas minimizadas: miniaturas no macOS, botões da barra no Windows */}
            {minimizedWindows.length > 0 && (
              <>
                <div
                  role="group"
                  aria-label="Janelas minimizadas"
                  className={[
                    "flex shrink-0 items-center",
                    windowsTaskbar ? "gap-0.5" : "gap-1.5",
                    vertical ? "flex-col" : "flex-row",
                  ].join(" ")}
                >
                  {minimizedWindows.map((item) => {
                    const Icon = item.app?.icon ?? PanelLeftOpen;
                    const barHeight = Math.max(5, Math.round(iconSize * 0.16));
                    return (
                      <button
                        key={item.view}
                        type="button"
                        onClick={() => restoreFromDock(item.view)}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setMenu({ app: null, view: item.view, x: event.clientX, y: event.clientY });
                        }}
                        aria-label={`Restaurar janela ${item.title}`}
                        title={`Restaurar ${item.title}`}
                        className="dock-mini group relative shrink-0 overflow-hidden focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70"
                        style={
                          windowsTaskbar
                            ? { width: tileSize, height: tileSize, borderRadius: tileRadius }
                            : {
                                width: Math.round(iconSize * 1.34),
                                height: Math.round(iconSize * 0.92),
                                borderRadius: Math.max(6, Math.round(iconSize * 0.14)),
                              }
                        }
                      >
                        <span
                          className="dock-mini-dots absolute inset-x-0 top-0 flex items-center gap-1 bg-white/10 px-1.5"
                          style={{ height: barHeight }}
                          aria-hidden="true"
                        >
                          <span className="h-1 w-1 rounded-full bg-[#ff5f57]" />
                          <span className="h-1 w-1 rounded-full bg-[#febc2e]" />
                          <span className="h-1 w-1 rounded-full bg-[#28c840]" />
                        </span>
                        <span
                          className={`absolute inset-x-0 bottom-0 grid place-items-center bg-gradient-to-br ${item.gradient}`}
                          style={{ top: windowsTaskbar ? 0 : barHeight }}
                          aria-hidden="true"
                        >
                          <Icon
                            size={windowsTaskbar ? iconPx : Math.round(iconSize * 0.34)}
                            strokeWidth={1.9}
                            className="text-white drop-shadow"
                          />
                        </span>
                        <span className="dock-mini-label" role="presentation">
                          <span className="font-medium">{item.title}</span>
                          <span className="dock-mini-hint">no dock · clique para restaurar</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                <span
                  aria-hidden="true"
                  className={[
                    "relative shrink-0 rounded-full bg-white/12",
                    vertical ? "h-px w-8 self-center" : "h-8 w-px self-center",
                  ].join(" ")}
                />
              </>
            )}

            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              aria-label="Preferências do dock"
              aria-expanded={settingsOpen}
              title="Preferências do dock"
              className={[
                "dock-tile relative grid shrink-0 place-items-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70",
                windowsTaskbar
                  ? "dock-tray-btn text-muted-foreground hover:text-foreground bg-transparent hover:bg-white/10"
                  : "bg-white/8 text-muted-foreground hover:bg-white/14 hover:text-foreground",
              ].join(" ")}
              style={
                windowsTaskbar
                  ? { width: trayBtn, height: trayBtn, borderRadius: 4, marginLeft: vertical ? undefined : "auto" }
                  : {
                      width: iconSize * 0.82,
                      height: iconSize * 0.82,
                      borderRadius: iconSize * 0.24,
                    }
              }
            >
              <Settings size={trayIcon} />
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
                  windowsTaskbar
                    ? isFullscreen
                      ? "text-teal-200 bg-white/12"
                      : "dock-tray-btn text-muted-foreground hover:text-foreground bg-transparent hover:bg-white/10"
                    : isFullscreen
                      ? "bg-teal-400/25 text-teal-100 hover:bg-teal-400/35"
                      : "bg-white/8 text-muted-foreground hover:bg-white/14 hover:text-foreground",
                ].join(" ")}
                style={
                  windowsTaskbar
                    ? { width: trayBtn, height: trayBtn, borderRadius: 4 }
                    : {
                        width: iconSize * 0.82,
                        height: iconSize * 0.82,
                        borderRadius: iconSize * 0.24,
                      }
                }
              >
                {isFullscreen ? (
                  <Minimize2 size={trayIcon} />
                ) : (
                  <Maximize2 size={trayIcon} />
                )}
              </button>
            )}

            {fitted.scrolling && <span className="dock-fade" aria-hidden="true" />}

            {/* Windows 11: bandeja do sistema com a hora e a data */}
            {windowsTaskbar && (
              <div
                className="dock-clock"
                title={now.toLocaleString("pt-PT", { dateStyle: "full", timeStyle: "short" })}
              >
                <span className="dock-clock-time">
                  {now.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="dock-clock-date">
                  {now.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" })}
                </span>
              </div>
            )}

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
              minimizedCount={minimizedWindows.length}
              onWindowModeChange={changeWindowMode}
            />
          )}
        </div>
      </div>

      {/* Menu Iniciar (Windows 11): painel flutuante encostado ao botão Iniciar */}
      {startOpen && windowsTaskbar && (
        <div
          className="start-layer"
          data-position={prefs.position}
          style={{
            ["--start-gutter" as string]: sidebarGutter.includes("268") ? "268px" : sidebarGutter ? "72px" : "0px",
            ["--dock-thickness" as string]: `${barThickness}px`,
          }}
        >
          <button
            type="button"
            className="start-scrim"
            aria-label="Fechar o menu Iniciar"
            onMouseDown={() => setStartOpen(false)}
          />
          <div className="start-anchor" data-position={prefs.position}>
            <StartMenu active={active} onClose={() => setStartOpen(false)} onOpenView={openViewById} />
          </div>
        </div>
      )}

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
            {menu.view ? (
              <>
                <p className="truncate px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                  {minimizedWindows.find((item) => item.view === menu.view)?.title ?? menu.view}
                </p>
                <button
                  role="menuitem"
                  onClick={() => {
                    const view = menu.view;
                    setMenu(null);
                    if (view) restoreFromDock(view);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <PanelLeftOpen size={14} /> Restaurar janela
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    const view = menu.view;
                    setMenu(null);
                    if (view) toggleMaximizeWindow(view, estimateWorkspace());
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-white/8"
                >
                  <Maximize2 size={14} /> Maximizar
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    const view = menu.view;
                    setMenu(null);
                    if (view) closeWindow(view);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-rose-300 transition hover:bg-rose-400/10"
                >
                  <X size={14} /> Fechar janela
                </button>
              </>
            ) : menu.app ? (
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
  /** Janelas minimizadas mostradas como miniaturas no dock. */
  minimizedCount: number;
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
  minimizedCount,
  onWindowModeChange,
}: DockPreferencesProps) {
  const { mode: sidebarMode, setMode: setSidebarMode } = useSidebar();
  const viewport = useViewport();
  const { glass, setGlass } = useGlass();
  const { window3d, setWindow3d } = useWindow3d();
  const { windowStyle, setWindowStyle } = useWindowStyle();

  /* O dock adapta o tamanho ao ecrã: o painel explica o que está a acontecer. */
  const fitted = useMemo(() => {
    const vertical = prefs.position !== "bottom";
    const available = vertical
      ? Math.max(220, viewport.height - 150)
      : Math.max(220, viewport.width - 24);
    const units = visible.length + minimizedCount * MINI_WIDTH_UNITS + (minimizedCount > 0 ? 0.4 : 0);
    return fitDock(prefs.iconSize, units, available);
  }, [minimizedCount, prefs.iconSize, prefs.position, visible.length, viewport.width, viewport.height]);

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
          <p className="dock-hint-windows text-[11px] leading-snug text-muted-foreground">
            Na <span className="text-foreground">barra de tarefas</span> este valor é a base dos botões: com poucas
            aplicações os botões <span className="text-foreground">crescem</span> (até 72 px, com o ícone maior) e a barra
            ganha altura; com muitas ficam nos 40 px e a barra passa a deslizar.
          </p>
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
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Vidro</p>
          <ToggleRow
            label="Efeito de vidro"
            hint="Translucidez e desfoco no dock, nas janelas e nos painéis. Desligado, as superfícies ficam opacas (mais leve para GPUs fracas)."
            checked={glass.enabled}
            onChange={(enabled) => setGlass({ enabled })}
          />
          <SliderRow
            label="Intensidade do vidro"
            value={Math.round(glass.strength * 100)}
            min={0}
            max={100}
            step={5}
            suffix="%"
            disabled={!glass.enabled}
            onChange={(value) => setGlass({ strength: value / 100 })}
          />
          <ToggleRow
            label="Papel de parede do desktop"
            hint="Manchas de cor por trás das janelas — é o que o vidro desfoca."
            checked={glass.wallpaper}
            onChange={(wallpaper) => setGlass({ wallpaper })}
          />
        </section>

        <section className="space-y-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Janelas</p>
          <div className="space-y-1.5">
            <span className="text-xs text-muted-foreground">Aspeto do IQ OS (janelas, dock e barra lateral)</span>
            <div className="flex gap-1 rounded-xl bg-white/5 p-1">
              {([
                { value: "macos", label: "macOS" },
                { value: "windows", label: "Windows 11" },
              ] as const).map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setWindowStyle(option.value)}
                  aria-pressed={windowStyle === option.value}
                  className={[
                    "flex-1 rounded-lg px-2 py-1.5 text-[11px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                    windowStyle === option.value
                      ? "bg-teal-400/20 text-teal-200"
                      : "text-muted-foreground hover:bg-white/5",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="text-[10px] leading-snug text-muted-foreground/70">
              {windowStyle === "windows"
                ? "Janelas com barra de 32 px (ícone e título à esquerda, controlos à direita, cantos de 8 px e material Mica), o dock como barra de tarefas (plana, 48 px, botões de 40 px, indicador por baixo do ícone, Iniciar e relógio) — com o botão Iniciar a abrir o menu Iniciar flutuante — e a barra lateral em Mica, com linhas de 32 px, cantos de 4 px e a barra de acento na aplicação ativa."
                : "Janelas com semáforos à esquerda, título centrado, vidro e cantos grandes; dock flutuante com ampliação e miniaturas das janelas minimizadas; barra lateral translúcida com seleção em pílula."}
            </p>
          </div>
        </section>

        <section className="space-y-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Janelas 3D</p>
          <ToggleRow
            label="Efeito 3D"
            hint="As janelas inclinam-se na direção do movimento ao arrastar e as janelas sem foco recuam, dando profundidade à área de trabalho."
            checked={window3d.enabled}
            onChange={(enabled) => setWindow3d({ enabled })}
          />
          <SliderRow
            label="Inclinação ao arrastar"
            value={window3d.tilt}
            min={0}
            max={8}
            step={0.5}
            suffix="°"
            disabled={!window3d.enabled}
            onChange={(tilt) => setWindow3d({ tilt })}
          />
          <ToggleRow
            label="Profundidade (janelas sem foco)"
            hint="A janela em foco fica à frente e as outras recuam ligeiramente."
            checked={window3d.depth}
            onChange={(depth) => setWindow3d({ depth })}
          />
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
          <ToggleRow
            label="Janelas minimizadas no dock"
            hint="Miniaturas das janelas minimizadas (só no modo janelas); clique restaura a janela."
            checked={prefs.minimizedShelf}
            onChange={(minimizedShelf) => onChange({ minimizedShelf })}
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
