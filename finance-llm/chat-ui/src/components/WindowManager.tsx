/**
 * Área de trabalho com janelas (estilo macOS).
 *
 * - Renderiza as janelas abertas sobre o fundo do "desktop", com foco,
 *   empilhamento, minimizar/maximizar/fechar e encaixes.
 * - Barra de menus mínima: nome da aplicação, janela ativa, ações de disposição
 *   e relógio.
 * - Atalhos: Ctrl/Cmd+W (fechar), Ctrl/Cmd+M (minimizar), Ctrl/Cmd+` (ciclar),
 *   Ctrl/Cmd+Shift+M (maximizar/restaurar).
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronsDownUp, LayoutGrid, Rows3, X } from "lucide-react";
import { Window, type SnapZone } from "./Window";
import {
  cascadeWindows,
  clampWindows,
  closeAllWindows,
  closeWindow,
  focusWindow,
  minimizeWindow,
  openWindow,
  setWindowRect,
  tileWindows,
  toggleMaximizeWindow,
  useWindows,
  type WindowRect,
  type WorkspaceSize,
} from "../windows";
import { dockApp } from "../dock";

interface WindowManagerProps {
  /** Renderiza o conteúdo de uma vista (a mesma função usada no modo página). */
  renderView: (view: string) => React.ReactNode;
  /** Título e ícone por vista (por omissão usa o catálogo do dock). */
  labelFor: (view: string) => { title: string; icon: React.ReactNode };
  /** Chamado quando a vista focada muda (para sincronizar o URL). */
  onActiveChange?: (view: string | null) => void;
}

export function WindowManager({ renderView, labelFor, onActiveChange }: WindowManagerProps) {
  const { windows, topZ, focus, close, minimize, restore, closeAll } = useWindows();
  const desktopRef = useRef<HTMLDivElement | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceSize>({ width: 0, height: 0 });
  const [snapPreview, setSnapPreview] = useState<SnapZone>(null);
  const [now, setNow] = useState(() => new Date());

  /* Tamanho da área de trabalho (é o "ecrã" das janelas). */
  useLayoutEffect(() => {
    const node = desktopRef.current;
    if (!node) return;
    const measure = () => {
      const box = node.getBoundingClientRect();
      setWorkspace({ width: Math.round(box.width), height: Math.round(box.height) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  /* Reposiciona janelas que ficaram fora da área de trabalho. */
  useEffect(() => {
    if (workspace.width > 0) clampWindows(workspace);
  }, [workspace.width, workspace.height]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const visible = windows.filter((item) => !item.minimized);
  const topWindow = [...visible].sort((a, b) => b.z - a.z)[0] ?? null;
  const activeView = topWindow?.view ?? null;

  useEffect(() => {
    onActiveChange?.(activeView);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView]);

  const snapTo = useCallback(
    (view: string, zone: Exclude<SnapZone, null>) => {
      const rect: WindowRect =
        zone === "maximize"
          ? { x: 0, y: 0, width: workspace.width, height: workspace.height }
          : zone === "left"
            ? { x: 0, y: 0, width: Math.round(workspace.width / 2), height: workspace.height }
            : { x: Math.round(workspace.width / 2), y: 0, width: Math.round(workspace.width / 2), height: workspace.height };
      setWindowRect(view, rect);
      focusWindow(view);
    },
    [workspace.width, workspace.height],
  );

  /* Atalhos de teclado das janelas. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      const key = event.key.toLowerCase();

      if (key === "`") {
        event.preventDefault();
        const ordered = [...visible].sort((a, b) => a.z - b.z);
        if (ordered.length < 2) return;
        focusWindow(ordered[0].view);
        return;
      }
      if (key === "w" && !event.shiftKey) {
        if (!activeView || typing) return;
        event.preventDefault();
        closeWindow(activeView);
        return;
      }
      if (key === "m") {
        if (!activeView) return;
        event.preventDefault();
        if (event.shiftKey) toggleMaximizeWindow(activeView, workspace);
        else minimizeWindow(activeView);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeView, workspace, visible]);

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col">
      {/* Barra de menus */}
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-white/8 bg-[#0d0f13]/85 px-3 text-[11px] backdrop-blur">
        <span className="font-semibold text-foreground">FinanceLLM</span>
        <span className="hidden text-muted-foreground sm:inline">
          {visible.length === 0 ? "sem janelas abertas" : `${visible.length} janela${visible.length === 1 ? "" : "s"}`}
        </span>
        {activeView && (
          <span className="hidden truncate text-muted-foreground md:inline">· {labelFor(activeView).title}</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <MenuButton
            icon={<Rows3 size={12} />}
            label="Cascata"
            onClick={() => cascadeWindows(workspace)}
            disabled={visible.length === 0}
          />
          <MenuButton
            icon={<LayoutGrid size={12} />}
            label="Lado a lado"
            onClick={() => tileWindows(workspace)}
            disabled={visible.length < 2}
          />
          <MenuButton
            icon={<ChevronsDownUp size={12} />}
            label="Minimizar todas"
            onClick={() => visible.forEach((item) => minimizeWindow(item.view))}
            disabled={visible.length === 0}
          />
          <MenuButton
            icon={<X size={12} />}
            label="Fechar todas"
            onClick={() => closeAll()}
            disabled={visible.length === 0}
          />
          <span className="ml-2 tabular-nums text-muted-foreground">
            {now.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      </div>

      {/* Área de trabalho */}
      <div
        ref={desktopRef}
        className="desktop-bg relative min-h-0 flex-1 overflow-hidden"
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) setSnapPreview(null);
        }}
      >
        {snapPreview && (
          <div
            className="pointer-events-none absolute z-[9999] rounded-xl border border-teal-300/40 bg-teal-400/10 transition-all duration-100"
            style={
              snapPreview === "maximize"
                ? { inset: 0 }
                : snapPreview === "left"
                  ? { left: 0, top: 0, width: "50%", height: "100%" }
                  : { left: "50%", top: 0, width: "50%", height: "100%" }
            }
            aria-hidden="true"
          />
        )}

        {visible.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <p className="text-sm text-muted-foreground">Nenhuma janela aberta.</p>
            <p className="max-w-sm text-xs text-muted-foreground/70">
              Abra uma aplicação na barra lateral ou no dock — cada uma abre numa janela que pode arrastar,
              redimensionar, minimizar e maximizar.
            </p>
            <div className="mt-2 flex flex-wrap justify-center gap-2">
              {["empresas-iq", "contracts-search", "dashboard", "cli"].map((view) => {
                const info = labelFor(view);
                return (
                  <button
                    key={view}
                    type="button"
                    onClick={() => openWindow(view, workspace)}
                    className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs transition hover:bg-white/[0.08] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                  >
                    {info.icon}
                    {info.title}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {windows.map((item) =>
          item.minimized ? null : (
            <Window
              key={item.view}
              state={item}
              workspace={workspace}
              title={labelFor(item.view).title}
              icon={labelFor(item.view).icon}
              active={item.z === topZ}
              onFocus={() => focus(item.view)}
              onClose={() => close(item.view)}
              onMinimize={() => minimize(item.view)}
              onToggleMaximize={() => toggleMaximizeWindow(item.view, workspace)}
              onSnap={(zone) => snapTo(item.view, zone)}
              onSnapPreview={setSnapPreview}
              onRectChange={(rect) => setWindowRect(item.view, rect)}
            >
              <div className="h-full overflow-auto">{renderView(item.view)}</div>
            </Window>
          ),
        )}
      </div>
    </div>
  );
}

function MenuButton({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60 disabled:opacity-35"
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
