/**
 * Secção «Mapa» do módulo das citações editais (CITIUS) — OpenStreetMap.
 *
 * Os éditos não têm coordenadas: trazem o **tribunal/serviço**. A API geocodifica
 * offline (tabelas do GeoNames já usadas pelo GLEIF) e devolve pontos por
 * **sede do tribunal** (a terra onde o processo corre), por **comarca judicial**
 * (agrupa concelhos) ou por **serviço completo**. As chaves sem coordenadas
 * conhecidas aparecem na lista «sem localização» — o mapa não inventa posições.
 *
 * O mapa é desenhado com tiles do OpenStreetMap (atribuição obrigatória no canto)
 * e um círculo por local, com área proporcional ao número de éditos. Clicar num
 * círculo abre o detalhe e permite saltar para os éditos desse local na Pesquisa.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2, MapPin, RefreshCw, Search, X } from "lucide-react";
import {
  getCitacoesMap,
  type CitacoesMapParams,
  type CitacoesMapPoint,
  type CitacoesMapResponse,
  type CitacoesSearchParams,
} from "../../citacoesApi";
import { latToWorld, lonToWorld, TILE_SIZE, worldToLat, worldToLon } from "../graph/geo";
import { formatMoney } from "../graph/graphStudio";

const numberFormat = new Intl.NumberFormat("pt-PT");

const PAPEIS = [
  "Exequente",
  "Executado",
  "Réu",
  "Requerente",
  "Requerido",
  "Credor",
  "Agente de Execução (Sol.)",
  "Autor",
];

const inputClass =
  "mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40";

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-white/10 bg-white/5 p-4 ${className}`}>{children}</div>;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold text-foreground">{value}</div>
      {hint ? <div className="text-[10px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

export default function CitacoesMapPanel({
  onOpenSearch,
}: {
  /** Navegação: abre a pesquisa com os filtros do local escolhido. */
  onOpenSearch: (params: CitacoesSearchParams) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ px: number; py: number; lat: number; lon: number } | null>(null);
  const dragMovedRef = useRef(false);

  const [data, setData] = useState<CitacoesMapResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CitacoesMapPoint | null>(null);
  const [size, setSize] = useState({ width: 900, height: 480 });
  const [center, setCenter] = useState({ lat: 39.6, lon: -8.1, zoom: 6 });
  const [dragging, setDragging] = useState(false);

  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState("");
  const [comarca, setComarca] = useState("");
  const [papel, setPapel] = useState("");
  const [nivel, setNivel] = useState<"sede" | "comarca" | "tribunal">("sede");
  const [soComTexto, setSoComTexto] = useState(false);

  const params: CitacoesMapParams = useMemo(
    () => ({
      nivel,
      q: q || undefined,
      tipo: tipo || undefined,
      comarca_judicial: comarca || undefined,
      papel: papel || undefined,
      has_texto: soComTexto ? true : undefined,
    }),
    [comarca, nivel, papel, q, soComTexto, tipo],
  );

  const load = useCallback(async (next: CitacoesMapParams) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await getCitacoesMap(next);
      setData(payload);
      setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const measure = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const points = data?.points ?? [];
  const maxCount = useMemo(() => Math.max(1, ...points.map((point) => point.count)), [points]);
  const radiusOf = useCallback(
    (count: number) => 6 + Math.sqrt(Math.max(0, count) / maxCount) * 20,
    [maxCount],
  );

  const projection = useMemo(() => {
    const width = size.width || 900;
    const height = size.height || 480;
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

  const zoomAt = useCallback(
    (delta: number, anchor?: { x: number; y: number }) => {
      const next = Math.max(4, Math.min(13, Math.round(center.zoom) + delta));
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

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("[data-map-chrome]")) return;
    const onNode = !!(event.target as HTMLElement).closest("[data-map-node='true']");
    dragRef.current = { px: event.clientX, py: event.clientY, lat: center.lat, lon: center.lon };
    dragMovedRef.current = false;
    setDragging(true);
    if (!onNode) {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        /* sem captura: o arrasto continua pelo movimento */
      }
    }
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
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      /* a captura pode já ter sido libertada */
    }
  };

  const focusPoint = (point: CitacoesMapPoint) => {
    setSelected(point);
    setCenter({ lat: point.lat, lon: point.lon, zoom: Math.max(center.zoom, 9) });
  };

  const searchParamsFor = (point: CitacoesMapPoint): CitacoesSearchParams => {
    if (data?.nivel === "comarca") return { comarca_judicial: point.key };
    if (data?.nivel === "tribunal") return { tribunal: point.key };
    return { tribunal_comarca: point.key };
  };

  const topPoints = [...points].slice(0, 60);
  const maior = topPoints[0];
  const totals = data?.totals;

  return (
    <div className="space-y-4">
      {error ? (
        <Card className="flex items-start gap-2 border-amber-400/25 bg-amber-400/5 text-[11.5px] text-amber-200">
          <AlertTriangle size={14} />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} className="opacity-70 hover:opacity-100">
            ×
          </button>
        </Card>
      ) : null}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Pesquisar nos éditos</label>
            <div className="relative">
              <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="interveniente, processo, texto do PDF…"
                autoComplete="off"
                className={`${inputClass} pl-7`}
              />
            </div>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo</label>
            <select value={tipo} onChange={(event) => setTipo(event.target.value)} className={inputClass}>
              <option value="">Todos</option>
              <option value="Citação">Citação</option>
              <option value="Notificação">Notificação</option>
              <option value="Anúncio">Anúncio</option>
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Papel</label>
            <select value={papel} onChange={(event) => setPapel(event.target.value)} className={inputClass}>
              <option value="">Todos</option>
              {PAPEIS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="w-[160px]">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Comarca judicial</label>
            <input
              value={comarca}
              onChange={(event) => setComarca(event.target.value)}
              placeholder="ex.: Santarém"
              autoComplete="off"
              className={inputClass}
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Agrupar por</label>
            <select
              value={nivel}
              onChange={(event) => setNivel(event.target.value as typeof nivel)}
              className={inputClass}
            >
              {(data?.niveis ?? [
                { key: "sede", label: "Sede do tribunal (terra)", hint: "" },
                { key: "comarca", label: "Comarca judicial", hint: "" },
                { key: "tribunal", label: "Tribunal/serviço", hint: "" },
              ]).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-1.5 pb-2 text-[11px] text-muted-foreground">
            <input type="checkbox" checked={soComTexto} onChange={(event) => setSoComTexto(event.target.checked)} />
            só com PDF analisado
          </label>
          <button
            type="button"
            onClick={() => void load(params)}
            disabled={loading}
            className="mb-0.5 inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-[11.5px] text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Aplicar
          </button>
        </div>
        {data?.nivel_label ? (
          <p className="text-[10.5px] text-muted-foreground">
            A mostrar por <span className="text-foreground">{data.nivel_label}</span> —{" "}
            {(data.niveis ?? []).find((item) => item.key === data.nivel)?.hint ?? ""}
          </p>
        ) : null}
      </Card>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Locais no mapa" value={numberFormat.format(totals?.locais_no_mapa ?? 0)} hint={`de ${numberFormat.format(totals?.locais ?? 0)}`} />
        <Stat label="Éditos" value={numberFormat.format(totals?.editais ?? 0)} />
        <Stat label="Valor em jogo" value={formatMoney(totals?.valor ?? 0)} hint="valor das execuções" />
        <Stat label="Com PDF analisado" value={numberFormat.format(totals?.com_texto ?? 0)} />
        <Stat
          label="Sem coordenadas"
          value={numberFormat.format(totals?.locais_sem_coordenadas ?? 0)}
          hint={(data?.sem_localizacao ?? [])[0]?.label}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="relative !p-0">
          <div
            ref={containerRef}
            role="application"
            aria-label="Mapa das citações editais: arraste para navegar, roda do rato para zoom"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onDoubleClick={(event) => zoomAt(1, { x: event.clientX, y: event.clientY })}
            className="relative h-[520px] touch-none overflow-hidden rounded-2xl bg-[#0a1a26] outline-none select-none"
            style={{ cursor: dragging ? "grabbing" : "grab" }}
          >
            {projection.tiles.map((tile) => (
              <img
                key={tile.key}
                src={tile.url}
                alt=""
                draggable={false}
                decoding="async"
                className="pointer-events-none absolute opacity-80"
                style={{ left: tile.left, top: tile.top, width: TILE_SIZE, height: TILE_SIZE }}
              />
            ))}

            {points.map((point) => {
              const screen = projection.project(point.lat, point.lon);
              const radius = radiusOf(point.count);
              const isSelected = selected?.key === point.key;
              return (
                <button
                  key={point.key}
                  type="button"
                  data-map-node="true"
                  onClick={(event) => {
                    if (dragMovedRef.current) return;
                    event.stopPropagation();
                    focusPoint(point);
                  }}
                  title={`${point.label} — ${numberFormat.format(point.count)} éditos${
                    point.valor ? ` · ${formatMoney(point.valor)}` : ""
                  }`}
                  className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
                  style={{ left: screen.left, top: screen.top, zIndex: isSelected ? 20 : 10 }}
                >
                  <span
                    className="rounded-full border-2 transition"
                    style={{
                      width: radius * 2,
                      height: radius * 2,
                      background: isSelected ? "rgba(245,158,11,0.85)" : "rgba(245,158,11,0.45)",
                      borderColor: isSelected ? "#ffffff" : "#f59e0b",
                      boxShadow: isSelected ? "0 0 0 3px rgba(245,158,11,0.35)" : "0 2px 6px rgba(0,0,0,0.45)",
                    }}
                  />
                  <span className="mt-0.5 max-w-[130px] truncate rounded bg-[#04121a]/85 px-1.5 py-0.5 text-[10px] text-white/90">
                    {radius >= 12 ? point.label : ""}
                  </span>
                </button>
              );
            })}

            <div data-map-chrome className="absolute right-3 top-3 z-30 flex flex-col gap-1">
              {[
                { label: "+", delta: 1 },
                { label: "−", delta: -1 },
              ].map((control) => (
                <button
                  key={control.label}
                  type="button"
                  onClick={() => zoomAt(control.delta)}
                  className="h-7 w-7 rounded-md border border-white/15 bg-[#04121a]/85 text-[13px] text-white/85 hover:bg-white/10"
                >
                  {control.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setCenter({ lat: 39.6, lon: -8.1, zoom: 6 })}
                title="Ver Portugal"
                className="h-7 w-7 rounded-md border border-white/15 bg-[#04121a]/85 text-[10px] text-white/85 hover:bg-white/10"
              >
                PT
              </button>
            </div>

            {loading ? (
              <div className="absolute inset-0 z-20 flex items-center justify-center gap-2 bg-[#04121a]/60 text-[12px] text-white/80">
                <Loader2 size={14} className="animate-spin" /> a carregar…
              </div>
            ) : null}

            {!loading && points.length === 0 ? (
              <p className="absolute inset-0 z-20 flex items-center justify-center p-6 text-center text-[12px] text-white/70">
                Sem locais para estes filtros. Recolha éditos na secção «Recolha».
              </p>
            ) : null}

            <span className="absolute bottom-2 left-3 z-30 rounded bg-[#04121a]/80 px-1.5 py-0.5 text-[10px] text-white/70">
              Arraste para navegar · roda para zoom ·{" "}
              <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">
                © OpenStreetMap
              </a>
            </span>

            {maior ? (
              <span className="absolute left-3 top-3 z-30 rounded-xl border border-white/10 bg-[#04121a]/85 px-2 py-1 text-[10.5px] text-white/80">
                {numberFormat.format(points.length)} locais · maior: {maior.label} ({numberFormat.format(maior.count)} éditos)
              </span>
            ) : null}
          </div>
        </Card>

        <div className="space-y-3">
          <Card className="space-y-2">
            <div className="text-[11.5px] font-semibold text-foreground">Locais com mais éditos</div>
            <div className="max-h-[300px] space-y-1 overflow-y-auto">
              {topPoints.map((point) => (
                <button
                  key={point.key}
                  type="button"
                  onClick={() => focusPoint(point)}
                  className={`flex w-full items-center justify-between gap-2 rounded-lg border px-2 py-1 text-left text-[11px] ${
                    selected?.key === point.key
                      ? "border-amber-400/40 bg-amber-400/15"
                      : "border-white/10 bg-white/[0.03] hover:bg-white/10"
                  }`}
                >
                  <span className="truncate text-foreground">{point.label}</span>
                  <span className="shrink-0 text-muted-foreground">{numberFormat.format(point.count)}</span>
                </button>
              ))}
              {topPoints.length === 0 ? <p className="text-[11px] text-muted-foreground">Sem locais.</p> : null}
            </div>
          </Card>

          {(data?.sem_localizacao ?? []).length ? (
            <Card className="space-y-2">
              <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-foreground">
                <MapPin size={13} /> Sem localização conhecida
              </div>
              <p className="text-[10.5px] text-muted-foreground">
                Chaves que a tabela de geocodificação offline não reconhece (não são colocadas no mapa).
              </p>
              <div className="max-h-[160px] space-y-1 overflow-y-auto">
                {(data?.sem_localizacao ?? []).map((point) => (
                  <button
                    key={point.key}
                    type="button"
                    onClick={() => onOpenSearch(searchParamsFor(point))}
                    className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-left text-[11px] hover:bg-white/10"
                  >
                    <span className="truncate text-foreground">{point.label}</span>
                    <span className="shrink-0 text-muted-foreground">{numberFormat.format(point.count)}</span>
                  </button>
                ))}
              </div>
            </Card>
          ) : null}

          {selected ? (
            <Card className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">{selected.label}</div>
                  <div className="text-[10.5px] text-muted-foreground">
                    {data?.nivel_label} · {selected.lat.toFixed(4)}, {selected.lon.toFixed(4)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded-lg border border-white/10 bg-white/5 p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                  aria-label="Fechar detalhe"
                >
                  <X size={12} />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Éditos" value={numberFormat.format(selected.count)} />
                <Stat label="Valor" value={formatMoney(selected.valor)} />
                <Stat label="Com PDF" value={numberFormat.format(selected.com_texto)} />
                <Stat
                  label="Período"
                  value={selected.min_date ? `${selected.min_date.slice(0, 10)} → ${(selected.max_date ?? "").slice(0, 10)}` : "—"}
                />
              </div>
              {(selected.por_tipo ?? []).length ? (
                <div className="flex flex-wrap gap-1">
                  {(selected.por_tipo ?? []).map((item) => (
                    <span
                      key={item.key}
                      className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground"
                    >
                      {item.key} <span className="text-foreground">{numberFormat.format(item.count)}</span>
                    </span>
                  ))}
                </div>
              ) : null}
              {(selected.top_tribunais ?? []).length ? (
                <div className="space-y-0.5">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Serviços</div>
                  {(selected.top_tribunais ?? []).map((item) => (
                    <div key={item.key} className="flex justify-between gap-2 text-[10.5px] text-muted-foreground">
                      <span className="truncate">{item.key}</span>
                      <span>{numberFormat.format(item.count)}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              <button
                type="button"
                onClick={() => onOpenSearch(searchParamsFor(selected))}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-400/15 px-2.5 py-1.5 text-[11px] text-amber-100 hover:bg-amber-400/25"
              >
                <Search size={12} /> Ver éditos deste local
              </button>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
