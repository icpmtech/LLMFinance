/**
 * Mapa OpenStreetMap dos registos **LEI** (GLEIF).
 *
 * Os registos LEI não têm coordenadas: cada círculo é a posição da **capital**
 * do país/região da sede legal (ver `components/geo/world.ts`). Regiões que não
 * estejam na tabela de centroides caem no centroide do país e saem com círculo
 * **tracejado** — nunca se inventa uma posição.
 *
 * O mapa ocupa a altura disponível e suporta arrastar, roda do rato, duplo
 * clique, teclado (setas, `+`/`-`, `0` para reenquadrar) e uma caixa de destaque
 * com a leitura da região em foco.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  Crosshair,
  Filter,
  Fingerprint,
  Globe2,
  Layers,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { TILE_SIZE, latToWorld, lonToWorld, worldToLat, worldToLon } from "../graph/geo";

/** Ponto já resolvido (posição + volumetria) que o mapa desenha. */
export type GleifMapPoint = {
  key: string;
  label: string;
  count: number;
  active?: number;
  cities?: number;
  lat: number;
  lon: number;
  exact: boolean;
  /** País do ponto (para a cor do círculo). */
  country?: string;
  /** Percentagem do total (0-1). */
  share?: number;
};

export type GleifMapView = { lat: number; lon: number; zoom: number };

interface GleifMapProps {
  points: GleifMapPoint[];
  /** Região em foco (a lista lateral e o clique no círculo levam aqui). */
  focusKey?: string | null;
  loading?: boolean;
  /** Vista inicial; o componente só a aplica na montagem e quando muda de identidade. */
  initialView?: GleifMapView;
  /** Nível do agregado (muda a paleta de cores e o texto das ações). */
  level?: "country" | "region" | "grid";
  /** Texto mostrado enquanto não há dados. */
  emptyHint?: string;
  /** Botões de reenquadramento extra (ex.: «Mundo», «Ibéria», «Ilhas»). */
  resetViews?: { label: string; view: GleifMapView }[];
  onSelect?: (point: GleifMapPoint) => void;
  /** Abre as empresas da divisão (a interface mostra um botão no cartão de foco). */
  onOpen?: (point: GleifMapPoint) => void;
  /** Focar/desfocar uma divisão (o mapa recentra-se sozinho). */
  onFocus?: (point: GleifMapPoint | null) => void;
  /** Filtrar o agregado por país ou por região a partir do menu de contexto. */
  onFilter?: (kind: "country" | "region", code: string) => void;
  /** Mudar o nível do agregado. */
  onLevelChange?: (level: "country" | "region" | "grid") => void;
  /** Voltar a pedir o agregado. */
  onRefresh?: () => void;
  onHover?: (point: GleifMapPoint | null) => void;
}

/** Cores por país (as duas economias do módulo têm cor própria). */
const COUNTRY_COLORS: Record<string, string> = {
  PT: "#10a37f",
  ES: "#f59e0b",
};

const DEFAULT_COLOR = "#38bdf8";

/** Texto das ações de reenquadramento (as vistas são passadas pelo mapa da página). */
const VIEW_LABELS: Record<string, string> = {
  Mundo: "Reenquadrar no mundo",
  Ibéria: "Reenquadrar na Península Ibérica",
  Ilhas: "Ver as ilhas (Açores, Madeira, Canárias)",
};

function colorFor(point: GleifMapPoint): string {
  const country = (point.country || point.key.split("-")[0] || "").toUpperCase();
  return COUNTRY_COLORS[country] || DEFAULT_COLOR;
}

function formatNumber(value: number): string {
  return value.toLocaleString("pt-PT");
}

export default function GleifMap({
  points,
  focusKey,
  loading = false,
  initialView,
  level = "region",
  emptyHint = "Sem dados para mostrar. Faça uma ingestão no separador «Ingestão».",
  resetViews,
  onSelect,
  onOpen,
  onFocus,
  onFilter,
  onLevelChange,
  onRefresh,
  onHover,
}: GleifMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 900, height: 520 });
  const [center, setCenter] = useState(() => ({
    lat: initialView?.lat ?? 39.6,
    lon: initialView?.lon ?? -4.2,
    zoom: initialView?.zoom ?? 5.2,
  }));
  const [tilesLoaded, setTilesLoaded] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [hovered, setHovered] = useState<GleifMapPoint | null>(null);
  /** Menu de contexto do botão direito (sobre um círculo ou sobre o fundo). */
  const [menu, setMenu] = useState<{ x: number; y: number; point: GleifMapPoint | null } | null>(null);
  const dragRef = useRef<{ px: number; py: number; lat: number; lon: number } | null>(null);
  const dragMovedRef = useRef(false);

  /** Tamanho real do contentor (a grelha de tiles parte daqui). */
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const measure = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setTilesLoaded(0);
  }, [center.zoom, size.width, size.height]);

  // A vista inicial muda quando o utilizador escolhe «Mundo»/«Ibéria»/«Ilhas».
  useEffect(() => {
    if (!initialView) return;
    setCenter({ lat: initialView.lat, lon: initialView.lon, zoom: initialView.zoom });
  }, [initialView?.lat, initialView?.lon, initialView?.zoom]);

  const projection = useMemo(() => {
    const width = size.width || 900;
    const height = size.height || 520;
    const zoom = Math.round(center.zoom);
    const centerX = lonToWorld(center.lon, zoom);
    const centerY = latToWorld(center.lat, zoom);
    const worldTiles = 2 ** zoom;

    const firstTileX = Math.floor((centerX - width / 2) / TILE_SIZE);
    const lastTileX = Math.floor((centerX + width / 2) / TILE_SIZE);
    const firstTileY = Math.max(0, Math.floor((centerY - height / 2) / TILE_SIZE));
    const lastTileY = Math.min(worldTiles - 1, Math.floor((centerY + height / 2) / TILE_SIZE));

    const tiles: { key: string; url: string; left: number; top: number }[] = [];
    for (let tileY = firstTileY; tileY <= lastTileY; tileY++) {
      for (let tileX = firstTileX; tileX <= lastTileX; tileX++) {
        const wrappedX = ((tileX % worldTiles) + worldTiles) % worldTiles;
        tiles.push({
          key: `${zoom}/${wrappedX}/${tileY}`,
          url: `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${tileY}.png`,
          left: width / 2 + (tileX * TILE_SIZE - centerX),
          top: height / 2 + (tileY * TILE_SIZE - centerY),
        });
      }
    }

    return {
      tiles,
      project: (lat: number, lon: number) => ({
        left: width / 2 + (lonToWorld(lon, zoom) - centerX),
        top: height / 2 + (latToWorld(lat, zoom) - centerY),
      }),
    };
  }, [center.lat, center.lon, center.zoom, size.height, size.width]);

  /** Zoom com o ponto sob o cursor fixo (ou o centro do mapa). */
  const zoomAt = useCallback(
    (delta: number, anchor?: { x: number; y: number }) => {
      const next = Math.max(1, Math.min(11, Math.round(center.zoom) + delta));
      if (next === Math.round(center.zoom)) return;
      const rect = containerRef.current?.getBoundingClientRect();
      const offsetX = anchor && rect ? anchor.x - rect.left - size.width / 2 : 0;
      const offsetY = anchor && rect ? anchor.y - rect.top - size.height / 2 : 0;
      const anchorLon = worldToLon(lonToWorld(center.lon, center.zoom) + offsetX, center.zoom);
      const anchorLat = worldToLat(latToWorld(center.lat, center.zoom) + offsetY, center.zoom);
      setCenter({
        lat: worldToLat(latToWorld(anchorLat, next) - offsetY, next),
        lon: worldToLon(lonToWorld(anchorLon, next) - offsetX, next),
        zoom: next,
      });
    },
    [center.lat, center.lon, center.zoom, size.height, size.width],
  );

  /** Roda do rato com zoom ancorado no cursor (listener não-passivo). */
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      zoomAt(event.deltaY > 0 ? -1 : 1, { x: event.clientX, y: event.clientY });
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // Foco pedido pela lista lateral ou pela pesquisa.
  const focusPoint = useMemo(() => points.find((point) => point.key === focusKey) || null, [points, focusKey]);
  useEffect(() => {
    if (!focusPoint) return;
    setCenter((prev) => ({
      lat: focusPoint.lat,
      lon: focusPoint.lon,
      zoom: Math.max(prev.zoom, level === "region" ? 7 : 5),
    }));
  }, [focusPoint?.key, focusPoint?.lat, focusPoint?.lon, level]);

  const maxCount = useMemo(() => Math.max(1, ...points.map((point) => point.count)), [points]);

  /**
   * Só os maiores pontos levam etiqueta com o nome.
   *
   * No nível «empresas» há centenas de células e as etiquetas de todas tapavam o
   * mapa; as restantes ficam identificadas no `title` e no cartão de foco.
   */
  const withLabel = useMemo(() => {
    const limit = level === "grid" ? 24 : Number.POSITIVE_INFINITY;
    const ordered = [...points].sort((a, b) => b.count - a.count).slice(0, limit);
    return new Set(ordered.map((point) => point.key));
  }, [level, points]);

  /** Raio do círculo: raiz quadrada da área (a área representa a contagem). */
  const radiusOf = useCallback(
    (count: number) => {
      const ratio = Math.max(0, count) / maxCount;
      return 6 + Math.sqrt(ratio) * 22;
    },
    [maxCount],
  );

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    // O menu fecha ao clicar fora dele: se fechasse também ao carregar num item,
    // o item desaparecia antes de receber o `click` (o clique nunca acontecia).
    if (!(event.target as HTMLElement).closest("[role='menu']")) setMenu(null);
    if ((event.target as HTMLElement).closest("[data-map-chrome]")) return;
    dragRef.current = { px: event.clientX, py: event.clientY, lat: center.lat, lon: center.lon };
    dragMovedRef.current = false;
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  /** Abre o menu de contexto na posição do clique (ou sobre um círculo). */
  const openMenu = (event: React.MouseEvent, point: GleifMapPoint | null) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = containerRef.current?.getBoundingClientRect();
    setMenu({ x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0), point });
    if (point) {
      setHovered(point);
      onHover?.(point);
    }
  };

  /** Corre uma ação do menu e fecha-o. */
  const runMenuAction = (action: () => void) => {
    setMenu(null);
    action();
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start) return;
    const dx = event.clientX - start.px;
    const dy = event.clientY - start.py;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMovedRef.current = true;
    setCenter({
      lat: worldToLat(latToWorld(start.lat, center.zoom) - dy, center.zoom),
      lon: worldToLon(lonToWorld(start.lon, center.zoom) - dx, center.zoom),
      zoom: center.zoom,
    });
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = 80;
    const centerX = lonToWorld(center.lon, center.zoom);
    const centerY = latToWorld(center.lat, center.zoom);
    const pan = (dx: number, dy: number) =>
      setCenter((prev) => ({
        lat: worldToLat(centerY + dy, prev.zoom),
        lon: worldToLon(centerX + dx, prev.zoom),
        zoom: prev.zoom,
      }));
    if (event.key === "ArrowLeft") pan(-step, 0);
    else if (event.key === "ArrowRight") pan(step, 0);
    else if (event.key === "ArrowUp") pan(0, -step);
    else if (event.key === "ArrowDown") pan(0, step);
    else if (event.key === "+" || event.key === "=") zoomAt(1);
    else if (event.key === "-" || event.key === "_") zoomAt(-1);
    else if (event.key === "Escape") setMenu(null);
    else return;
    event.preventDefault();
  };

  const spotlight = hovered || focusPoint;
  const drawOrder = useMemo(() => [...points].sort((a, b) => a.count - b.count), [points]);

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="application"
      aria-label="Mapa de registos LEI: arraste para navegar, roda do rato para zoom"
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onContextMenu={(event) => openMenu(event, null)}
      onDoubleClick={(event) => zoomAt(1, { x: event.clientX, y: event.clientY })}
      className="relative min-h-[320px] flex-1 touch-none overflow-hidden bg-[#071c26] outline-none select-none"
      style={{ cursor: dragging ? "grabbing" : "grab" }}
    >
      {projection.tiles.map((tile) => (
        <img
          key={tile.key}
          src={tile.url}
          alt=""
          draggable={false}
          decoding="async"
          className="pointer-events-none absolute opacity-75"
          style={{ left: tile.left, top: tile.top, width: TILE_SIZE, height: TILE_SIZE }}
          onLoad={() => setTilesLoaded((count) => count + 1)}
          onError={() => setTilesLoaded((count) => count + 1)}
        />
      ))}

      <div className="absolute inset-0">
        {drawOrder.map((point) => {
          const screen = projection.project(point.lat, point.lon);
          const radius = radiusOf(point.count);
          const selected = point.key === focusKey;
          const color = colorFor(point);
          return (
            <button
              key={point.key}
              type="button"
              data-map-node="true"
              onMouseEnter={() => {
                setHovered(point);
                onHover?.(point);
              }}
              onMouseLeave={() => {
                setHovered(null);
                onHover?.(null);
              }}
              onFocus={() => setHovered(point)}
              onContextMenu={(event) => openMenu(event, point)}
              onClick={(event) => {
                if (dragMovedRef.current) return;
                event.stopPropagation();
                onSelect?.(point);
              }}
              className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
              style={{ left: screen.left, top: screen.top, zIndex: selected ? 20 : 10 }}
              title={`${point.label} — ${formatNumber(point.count)} registos${
                point.cities ? ` · ${formatNumber(point.cities)} cidades` : ""
              }${point.exact ? "" : " (posição aproximada)"}`}
            >
              <span
                className="rounded-full border-2 transition"
                style={{
                  width: radius * 2,
                  height: radius * 2,
                  background: `${color}${selected ? "cc" : "80"}`,
                  borderColor: selected ? "#ffffff" : color,
                  borderStyle: point.exact ? "solid" : "dashed",
                  boxShadow: selected ? `0 0 0 3px ${color}55` : "0 2px 6px rgba(0,0,0,0.45)",
                }}
              />
              <span className="mt-0.5 whitespace-nowrap rounded bg-[#04121a]/85 px-1.5 py-0.5 text-[10px] text-white/90">
                {withLabel.has(point.key)
                  ? point.label.length > 20
                    ? `${point.label.slice(0, 18)}…`
                    : point.label
                  : ""}
              </span>
            </button>
          );
        })}
      </div>

      {/* Controlos */}
      <div data-map-chrome className="absolute top-3 right-3 z-30 flex flex-col gap-1">
        <button
          type="button"
          onClick={() => zoomAt(1)}
          title="Aproximar"
          className="rounded-xl glass-card p-2 transition hover:bg-white/10"
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          onClick={() => zoomAt(-1)}
          title="Afastar"
          className="rounded-xl glass-card p-2 transition hover:bg-white/10"
        >
          <Minus size={14} />
        </button>
        {resetViews?.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => setCenter(item.view)}
            title={`Reenquadrar: ${item.label}`}
            className="rounded-xl glass-card px-2 py-1 text-[10px] transition hover:bg-white/10"
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 bg-[#04121a]/70 text-xs text-muted-foreground">
          <Loader2 size={20} className="animate-spin" />
          A agregar registos LEI…
        </div>
      )}

      {!loading && projection.tiles.length > 0 && tilesLoaded < projection.tiles.length && (
        <div className="absolute inset-x-0 top-2 z-30 flex justify-center">
          <span className="flex items-center gap-2 rounded-full bg-[#04121a]/85 px-3 py-1 text-[11px] text-muted-foreground">
            <RefreshCw size={12} className="animate-spin" /> A carregar mapa…
          </span>
        </div>
      )}

      {!loading && points.length === 0 && (
        <div className="absolute inset-0 z-20 flex items-center justify-center px-6 text-center text-xs text-muted-foreground">
          {emptyHint}
        </div>
      )}

      {/* Leitura rápida do ponto em foco */}
      {spotlight && (
        <div data-map-chrome className="absolute bottom-3 left-3 z-30 max-w-[300px] rounded-2xl glass-card px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: colorFor(spotlight) }} />
            <span className="text-sm font-medium">{spotlight.label}</span>
            <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {level === "country" ? "país" : "região"}
            </span>
          </div>
          <div className="mt-1 grid grid-cols-3 gap-2 text-[11px]">
            <span className="text-muted-foreground">
              LEI<span className="ml-1 text-foreground">{formatNumber(spotlight.count)}</span>
            </span>
            {spotlight.active !== undefined && (
              <span className="text-muted-foreground">
                ativos<span className="ml-1 text-emerald-300">{formatNumber(spotlight.active)}</span>
              </span>
            )}
            {spotlight.cities !== undefined && (
              <span className="text-muted-foreground">
                cidades<span className="ml-1 text-foreground">{formatNumber(spotlight.cities)}</span>
              </span>
            )}
          </div>
          {!spotlight.exact && (
            <p className="mt-1 text-[10px] text-amber-300/90">
              Posição aproximada (centroide do país): a região não tem centroide conhecido.
            </p>
          )}
          {onOpen && (
            <button
              type="button"
              onClick={() => onOpen(spotlight)}
              className="mt-1.5 flex w-full items-center justify-center gap-1 rounded-xl border border-primary/30 bg-primary/10 px-2 py-1 text-[10.5px] text-primary transition hover:bg-primary/20"
            >
              <Building2 size={11} />
              Ver as empresas numa janela
            </button>
          )}
        </div>
      )}

      {/* Menu de contexto (botão direito): divisão do mapa ou fundo */}
      {menu && (
        <div
          role="menu"
          data-map-chrome
          className="absolute z-40 min-w-[266px] max-w-[330px] rounded-2xl border border-white/10 bg-[#04121a]/95 p-1 shadow-2xl backdrop-blur-xl"
          style={{
            left: Math.min(menu.x, Math.max(8, size.width - 340)),
            top: Math.min(menu.y, Math.max(8, size.height - 300)),
          }}
        >
          {menu.point ? (
            <>
              <div className="px-2 py-1.5">
                <p className="flex items-center gap-2 text-xs font-medium">
                  <span className="h-2 w-2 rounded-full" style={{ background: colorFor(menu.point) }} />
                  {menu.point.label}
                </p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  <span className="font-mono">{menu.point.key}</span> · {formatNumber(menu.point.count)} LEI ·{" "}
                  {level === "country" ? "país" : "região"}
                  {menu.point.active !== undefined ? ` · ${formatNumber(menu.point.active)} ativos` : ""}
                </p>
              </div>
              <div className="my-1 h-px bg-white/10" />
              {onOpen && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => onOpen(menu.point as GleifMapPoint))}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs text-primary transition hover:bg-primary/10"
                >
                  <Fingerprint size={13} className="shrink-0" />
                  Abrir janela · empresas {level === "country" ? "deste país" : "desta região"}
                </button>
              )}
              {onFocus && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => onFocus(menu.point))}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                >
                  <Crosshair size={13} className="shrink-0" />
                  Focar no mapa
                </button>
              )}
              {onFilter && level !== "grid" && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => onFilter(level, (menu.point as GleifMapPoint).key))}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                >
                  <Filter size={13} className="shrink-0" />
                  Filtrar o mapa por {level === "country" ? "este país" : "esta região"}
                </button>
              )}
              <div className="my-1 h-px bg-white/10" />
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => onFocus?.(null))}
                className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
              >
                <X size={13} className="shrink-0" />
                Desfocar
              </button>
            </>
          ) : (
            <>
              {onLevelChange && (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={level === "grid"}
                    onClick={() => runMenuAction(() => onLevelChange("grid"))}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10 disabled:opacity-40"
                  >
                    <Fingerprint size={13} className="shrink-0" />
                    Empresas pela sede legal
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={level === "region"}
                    onClick={() => runMenuAction(() => onLevelChange("region"))}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10 disabled:opacity-40"
                  >
                    <Layers size={13} className="shrink-0" />
                    Agrupar por regiões
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={level === "country"}
                    onClick={() => runMenuAction(() => onLevelChange("country"))}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10 disabled:opacity-40"
                  >
                    <Globe2 size={13} className="shrink-0" />
                    Agrupar por países
                  </button>
                  <div className="my-1 h-px bg-white/10" />
                </>
              )}
              {resetViews?.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  onClick={() => runMenuAction(() => setCenter(item.view))}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                >
                  <RotateCcw size={13} className="shrink-0" />
                  {VIEW_LABELS[item.label] || item.label}
                </button>
              ))}
              {onRefresh && (
                <>
                  <div className="my-1 h-px bg-white/10" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => runMenuAction(() => onRefresh())}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                  >
                    <RefreshCw size={13} className="shrink-0" />
                    Atualizar o agregado
                  </button>
                </>
              )}
              <p className="px-2 py-1.5 text-[10px] leading-relaxed text-muted-foreground">
                Botão direito sobre um círculo abre as opções da divisão; o botão esquerdo abre logo a janela das
                empresas.
              </p>
            </>
          )}
        </div>
      )}

      <div data-map-chrome className="absolute right-3 bottom-3 z-30 flex items-center gap-2 text-[10px] text-muted-foreground">
        <Crosshair size={11} />
        tiles © OpenStreetMap
      </div>

      <div className="pointer-events-none absolute top-3 left-3 z-20 flex gap-1 text-[10px] text-muted-foreground">
        <ZoomIn size={12} />
        <ZoomOut size={12} />
        <span className="ml-1">arraste · roda · duplo clique</span>
      </div>
    </div>
  );
}
