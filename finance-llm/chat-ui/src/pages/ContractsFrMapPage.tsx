/**
 * Mapa dos contratos públicos de França (DECP) — `/contratos-fr/mapa`.
 *
 * Os contratos do DECP não têm coordenadas: trazem o **local de execução** em
 * `lieu_execution_code` + `lieu_execution_type`, com níveis diferentes (código de
 * departamento, código postal, código INSEE de comuna, código de região, país).
 * A API (`GET /contracts-fr/map`) agrega por departamento/região e devolve a
 * posição de cada um; aqui desenha-se sobre **tiles do OpenStreetMap**, com o
 * mesmo motor do mapa ibérico e do mapa LEI (`components/graph/geo.ts`).
 *
 * Regras de honestidade seguidas neste mapa (como no mapa ibérico):
 *
 * - a posição de um departamento é o centro de massa do polígono oficial, de uma
 *   região o centro de massa dos seus departamentos, e de um departamento de
 *   ultramar a sua prefeitura — nunca uma posição inventada;
 * - o que não tem posição conhecida (códigos de cantão/arrondissement inválidos,
 *   códigos de região não reconhecidos, outros países) aparece em «sem posição no
 *   mapa», com contagem e valor;
 * - os departamentos de **ultramar** não cabem no enquadramento metropolitano e
 *   ficam listados à parte (clicar neles voa até lá);
 * - o valor é apresentado com reserva: o DECP tem valores indicativos
 *   (`99999999999999`) que dominam qualquer soma — a página diz quantos são.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  AlertTriangle,
  Crosshair,
  Euro,
  Info,
  Layers,
  Loader2,
  MapPin,
  RefreshCw,
  Sigma,
} from "lucide-react";
import {
  getContratosFrMap,
  writeContratosFrEntry,
  type ContratoFrMapFilters,
  type ContratoFrMapRegion,
  type ContratoFrMapResponse,
} from "../contratosFrApi";
import { TILE_SIZE, latToWorld, lonToWorld, worldToLat, worldToLon } from "../components/graph/geo";

/** Enquadramento da França metropolitana. */
const FRANCE_VIEW = { lat: 46.6, lon: 2.35, zoom: 6 };
const ZOOM_MIN = 3;
const ZOOM_MAX = 13;

type Metrica = "contracts" | "value";

interface ContractsFrMapPageProps {
  /** Abre a pesquisa de contratos de França (lista) com os filtros do mapa. */
  onOpenSearch?: () => void;
  onSwitchView?: () => void;
}

const numberFormat = new Intl.NumberFormat("pt-PT");

function formatMoneyCompact(n?: number | null): string {
  if (n === undefined || n === null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1e6) return `${(n / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 1e3) return `${(n / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} k€`;
  return `${n.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

function corDoNivel(item: ContratoFrMapRegion, selecionado: boolean): { fill: string; stroke: string } {
  if (item.level === "pais") return { fill: "rgba(16,185,129,0.35)", stroke: "#34d399" };
  if (selecionado) return { fill: "rgba(245,158,11,0.9)", stroke: "#ffffff" };
  if (item.level === "regiao") return { fill: "rgba(56,189,248,0.35)", stroke: "#38bdf8" };
  return { fill: "rgba(245,158,11,0.45)", stroke: "#f59e0b" };
}

export function ContractsFrMapPage({ onOpenSearch }: ContractsFrMapPageProps) {
  const [q, setQ] = useState("");
  const [ano, setAno] = useState("");
  const [nature, setNature] = useState("");
  const [procedure, setProcedure] = useState("");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [metrica, setMetrica] = useState<Metrica>("contracts");

  const [dados, setDados] = useState<ContratoFrMapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [selecionado, setSelecionado] = useState<ContratoFrMapRegion | null>(null);

  const [center, setCenter] = useState(FRANCE_VIEW);
  const [size, setSize] = useState({ width: 900, height: 560 });
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ px: number; py: number; lat: number; lon: number } | null>(null);
  const dragMovedRef = useRef(false);

  const filtros = useCallback((): ContratoFrMapFilters => {
    return {
      q: q.trim() || undefined,
      ano: ano ? Number(ano) : undefined,
      nature: nature.trim() || undefined,
      procedure: procedure.trim() || undefined,
      min_value: minValue ? Number(minValue) : undefined,
      max_value: maxValue ? Number(maxValue) : undefined,
      date_field: "date_publication",
    };
  }, [q, ano, nature, procedure, minValue, maxValue]);

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const resposta = await getContratosFrMap(filtros());
      if (resposta.error) throw new Error(resposta.error);
      setDados(resposta);
      setSelecionado(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
      setDados(null);
    } finally {
      setLoading(false);
    }
  }, [filtros]);

  useEffect(() => {
    void carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const medir = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    medir();
    const observer = new ResizeObserver(medir);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  /** Todos os locais com posição: metropolitanos + ultramar + país. */
  const locais = useMemo(() => {
    if (!dados) return [];
    return [...dados.regions, ...dados.offshore, ...dados.countries].filter(
      (item) => item.lat !== undefined && item.lon !== undefined,
    );
  }, [dados]);

  const maxMetrica = useMemo(
    () => Math.max(1, ...locais.map((item) => (metrica === "contracts" ? item.contracts : item.value))),
    [locais, metrica],
  );

  const radiusOf = useCallback(
    (item: ContratoFrMapRegion) => {
      const valor = metrica === "contracts" ? item.contracts : item.value;
      return 5 + Math.sqrt(Math.max(0, valor) / maxMetrica) * 22;
    },
    [maxMetrica, metrica],
  );

  const projection = useMemo(() => {
    const width = size.width || 900;
    const height = size.height || 560;
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
    (delta: number) => {
      const next = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(center.zoom) + delta));
      if (next === Math.round(center.zoom)) return;
      setCenter((atual) => ({ ...atual, zoom: next }));
    },
    [center.zoom],
  );

  const voarPara = useCallback((item: ContratoFrMapRegion, zoom = 7) => {
    if (item.lat === undefined || item.lon === undefined) return;
    setSelecionado(item);
    setCenter({ lat: item.lat, lon: item.lon, zoom: Math.max(zoom, 6) });
  }, []);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const next = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(center.zoom) + (event.deltaY > 0 ? -1 : 1)));
      if (next !== Math.round(center.zoom)) setCenter((atual) => ({ ...atual, zoom: next }));
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [center.zoom]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("[data-map-chrome]")) return;
    dragRef.current = { px: event.clientX, py: event.clientY, lat: center.lat, lon: center.lon };
    dragMovedRef.current = false;
    setDragging(true);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const inicio = dragRef.current;
    if (!inicio) return;
    const dx = event.clientX - inicio.px;
    const dy = event.clientY - inicio.py;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMovedRef.current = true;
    setCenter({
      lat: worldToLat(latToWorld(inicio.lat, center.zoom) - dy, center.zoom),
      lon: worldToLon(lonToWorld(inicio.lon, center.zoom) - dx, center.zoom),
      zoom: center.zoom,
    });
  };

  const endDrag = () => {
    dragRef.current = null;
    setDragging(false);
  };

  /** Abre a lista de contratos de França com o local selecionado como filtro. */
  const abrirNaPesquisa = (item: ContratoFrMapRegion) => {
    if (item.precision === "grupo-postal") return; // «20» não é um código filtrável
    writeContratosFrEntry({
      lieu_execution_code: item.code,
      // O tipo só é preciso para desambiguar códigos de **região** («76» é
      // Occitanie como região e Seine-Maritime como departamento). Num
      // departamento, o código sozinho filtra por prefixo e abrange os
      // códigos postais — é o que dá o mesmo total que o mapa mostra.
      lieu_execution_type: item.level === "regiao" ? "Code région" : item.level === "pais" ? "Code pays" : undefined,
    });
    onOpenSearch?.();
  };

  const metricLabel = metrica === "contracts" ? "contratos" : "valor";
  const topRegioes = dados?.regions.slice(0, 12) ?? [];
  const comPosicao = locais.length;
  const totalSemPosicao =
    (dados?.not_plotted ?? []).reduce((soma, item) => soma + item.contracts, 0) +
    (dados?.countries ?? []).filter((item) => item.lat === undefined).reduce((soma, item) => soma + item.contracts, 0);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-lg shadow-orange-500/25">
              <MapPin size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Contratos França · Mapa</h1>
              <p className="text-sm text-muted-foreground">
                DECP agregado por local de execução (departamento e região) sobre OpenStreetMap
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {onOpenSearch && (
              <button
                type="button"
                onClick={onOpenSearch}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs transition hover:bg-accent"
              >
                <Layers size={13} /> Ver lista
              </button>
            )}
            <button
              type="button"
              onClick={() => void carregar()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs transition hover:bg-accent disabled:opacity-50"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Atualizar
            </button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi icon={<Layers size={15} />} label="Contratos" value={numberFormat.format(dados?.total ?? 0)} hint={`às parcelas: ${numberFormat.format(comPosicao)} locais`} />
          <Kpi
            icon={<Euro size={15} />}
            label="Valor (DECP)"
            value={formatMoneyCompact(dados?.value ?? 0)}
            hint={
              dados?.value_outliers?.contracts
                ? `${numberFormat.format(dados.value_outliers.contracts)} com valor indicativo`
                : `em ${numberFormat.format(dados?.value_docs ?? 0)} contratos`
            }
          />
          <Kpi icon={<MapPin size={15} />} label="Departamentos no mapa" value={numberFormat.format(dados?.levels?.departamento ?? 0)} hint={`${numberFormat.format(dados?.levels?.regiao ?? 0)} regiões`} />
          <Kpi icon={<Sigma size={15} />} label="Sem posição no mapa" value={numberFormat.format(totalSemPosicao)} hint="listados ao lado, nunca colocados" />
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="glass-card relative !p-0">
            <div
              ref={containerRef}
              role="application"
              aria-label="Mapa dos contratos de França: arraste para navegar, roda do rato para zoom"
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onPointerLeave={endDrag}
              className="relative h-[62vh] min-h-[380px] touch-none overflow-hidden rounded-2xl bg-[#0a1a26] outline-none select-none"
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

              {locais.map((item, indice) => {
                const ponto = projection.project(item.lat as number, item.lon as number);
                const radius = radiusOf(item);
                const selecionadoAqui = selecionado?.code === item.code && selecionado?.level === item.level;
                const cores = corDoNivel(item, selecionadoAqui);
                const valorMetrica = metrica === "contracts" ? item.contracts : item.value;
                return (
                  <button
                    key={`${item.level ?? "x"}-${item.code}-${indice}`}
                    type="button"
                    data-map-node="true"
                    onClick={(event) => {
                      if (dragMovedRef.current) return;
                      event.stopPropagation();
                      setSelecionado(item);
                    }}
                    onDoubleClick={() => voarPara(item)}
                    title={`${item.label} — ${numberFormat.format(item.contracts)} contratos · ${formatMoneyCompact(item.value)}`}
                    className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
                    style={{ left: ponto.left, top: ponto.top, zIndex: selecionadoAqui ? 20 : 10 }}
                  >
                    <span
                      className="rounded-full border-2 transition"
                      style={{
                        width: radius * 2,
                        height: radius * 2,
                        background: cores.fill,
                        borderColor: cores.stroke,
                        borderStyle: item.precision === "centroide" || item.precision === "prefeitura" ? "solid" : "dashed",
                        boxShadow: selecionadoAqui ? "0 0 0 3px rgba(245,158,11,0.35)" : "0 2px 6px rgba(0,0,0,0.45)",
                      }}
                    />
                    <span className="mt-0.5 max-w-[150px] truncate rounded bg-[#04121a]/85 px-1.5 py-0.5 text-[10px] text-white/90">
                      {radius >= 13 || selecionadoAqui ? `${item.label} (${numberFormat.format(valorMetrica)})` : ""}
                    </span>
                  </button>
                );
              })}

              <div data-map-chrome className="absolute right-3 top-3 z-30 flex flex-col gap-1">
                <button
                  type="button"
                  onClick={() => zoomAt(1)}
                  className="h-7 w-7 rounded-md border border-white/15 bg-[#04121a]/85 text-[13px] text-white/85 hover:bg-white/10"
                >
                  +
                </button>
                <button
                  type="button"
                  onClick={() => zoomAt(-1)}
                  className="h-7 w-7 rounded-md border border-white/15 bg-[#04121a]/85 text-[13px] text-white/85 hover:bg-white/10"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => setCenter(FRANCE_VIEW)}
                  title="Ver França metropolitana"
                  className="h-7 w-7 rounded-md border border-white/15 bg-[#04121a]/85 text-[10px] text-white/85 hover:bg-white/10"
                >
                  FR
                </button>
              </div>

              {loading ? (
                <div className="absolute inset-0 z-20 flex items-center justify-center gap-2 bg-[#04121a]/60 text-[12px] text-white/80">
                  <Loader2 size={14} className="animate-spin" /> a agregar contratos…
                </div>
              ) : null}

              {!loading && locais.length === 0 ? (
                <p className="absolute inset-0 z-20 flex items-center justify-center p-6 text-center text-[12px] text-white/70">
                  Sem contratos com localização para estes filtros.
                </p>
              ) : null}

              {selecionado ? (
                <div
                  data-map-chrome
                  className="absolute left-3 top-3 z-30 max-w-[280px] rounded-xl border border-white/10 bg-[#04121a]/90 px-3 py-2 text-[11px] text-white/85"
                >
                  <div className="text-[12px] font-semibold text-white">{selecionado.label}</div>
                  <div className="mt-0.5 text-white/70">
                    {numberFormat.format(selecionado.contracts)} contratos · {formatMoneyCompact(selecionado.value)}
                  </div>
                  <div className="mt-0.5 text-white/50">
                    {selecionado.level ?? selecionado.kind ?? "—"}
                    {selecionado.precision ? ` · ${selecionado.precision}` : ""}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={() => voarPara(selecionado)}
                      className="inline-flex items-center gap-1 rounded-md border border-white/15 px-2 py-1 text-[10.5px] hover:bg-white/10"
                    >
                      <Crosshair size={11} /> Aproximar
                    </button>
                    {onOpenSearch && selecionado.precision !== "grupo-postal" && (
                      <button
                        type="button"
                        onClick={() => abrirNaPesquisa(selecionado)}
                        className="inline-flex items-center gap-1 rounded-md border border-white/15 px-2 py-1 text-[10.5px] hover:bg-white/10"
                      >
                        <Layers size={11} /> Ver contratos
                      </button>
                    )}
                  </div>
                </div>
              ) : null}

              <span className="absolute bottom-2 left-3 z-30 rounded bg-[#04121a]/80 px-1.5 py-0.5 text-[10px] text-white/70">
                Arraste para navegar · roda para zoom · duplo clique aproxima ·{" "}
                <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" className="underline">
                  © OpenStreetMap
                </a>
              </span>
            </div>
          </div>

          <div className="space-y-3">
            <Card titulo="Filtros">
              <div className="space-y-2">
                <Campo label="Pesquisar (objeto, CPV, procedimento)">
                  <input
                    value={q}
                    onChange={(event) => setQ(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void carregar();
                    }}
                    autoComplete="off"
                    placeholder="hôpital, école…"
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                  />
                </Campo>
                <div className="grid grid-cols-2 gap-2">
                  <Campo label="Ano">
                    <input
                      value={ano}
                      onChange={(event) => setAno(event.target.value.replace(/[^\d]/g, "").slice(0, 4))}
                      placeholder="2026"
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                    />
                  </Campo>
                  <Campo label="Natureza">
                    <input
                      value={nature}
                      onChange={(event) => setNature(event.target.value)}
                      placeholder="Marché"
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                    />
                  </Campo>
                </div>
                <Campo label="Procedimento">
                  <input
                    value={procedure}
                    onChange={(event) => setProcedure(event.target.value)}
                    placeholder="Appel d'offres ouvert"
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                  />
                </Campo>
                <div className="grid grid-cols-2 gap-2">
                  <Campo label="Valor ≥">
                    <input
                      value={minValue}
                      onChange={(event) => setMinValue(event.target.value.replace(/[^\d.]/g, ""))}
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                    />
                  </Campo>
                  <Campo label="Valor ≤">
                    <input
                      value={maxValue}
                      onChange={(event) => setMaxValue(event.target.value.replace(/[^\d.]/g, ""))}
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                    />
                  </Campo>
                </div>
                <div className="flex items-center justify-between gap-2 pt-1">
                  <div className="inline-flex rounded-lg border border-border p-0.5 text-[11px]">
                    <button
                      type="button"
                      onClick={() => setMetrica("contracts")}
                      className={`rounded-md px-2 py-1 transition ${metrica === "contracts" ? "bg-primary/20 text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      Nº contratos
                    </button>
                    <button
                      type="button"
                      onClick={() => setMetrica("value")}
                      className={`rounded-md px-2 py-1 transition ${metrica === "value" ? "bg-primary/20 text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      Valor
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => void carregar()}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Aplicar
                  </button>
                </div>
              </div>
            </Card>

            {erro && (
              <Card titulo="Erro">
                <p className="flex items-start gap-2 text-[11.5px] text-amber-300">
                  <AlertTriangle size={13} /> {erro}
                </p>
              </Card>
            )}

            {(dados?.warnings ?? []).map((aviso) => (
              <p key={aviso} className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
                <Info size={12} className="mt-0.5 shrink-0" /> {aviso}
              </p>
            ))}

            <Card titulo={`Locais por ${metricLabel}`}>
              <ul className="max-h-[300px] space-y-1 overflow-y-auto pr-1">
                {topRegioes.map((item) => (
                  <li key={`${item.level}-${item.code}`}>
                    <button
                      type="button"
                      onClick={() => voarPara(item)}
                      className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-left text-[11.5px] transition hover:bg-accent"
                    >
                      <span className="min-w-0">
                        <span className="font-mono text-[10.5px] text-amber-300">{item.code}</span>{" "}
                        <span className="truncate">{item.label}</span>
                        {item.level === "regiao" ? <span className="ml-1 text-[10px] text-sky-300">região</span> : null}
                      </span>
                      <span className="shrink-0 text-muted-foreground">
                        {numberFormat.format(item.contracts)} · {formatMoneyCompact(item.value)}
                      </span>
                    </button>
                  </li>
                ))}
                {!topRegioes.length && !loading ? (
                  <li className="px-2 py-1 text-[11.5px] text-muted-foreground">Sem locais para estes filtros.</li>
                ) : null}
              </ul>
            </Card>

            {dados?.offshore?.length ? (
              <Card titulo="Ultramar (fora do enquadramento)">
                <ul className="space-y-1">
                  {dados.offshore.map((item) => (
                    <li key={`${item.level}-${item.code}`}>
                      <button
                        type="button"
                        onClick={() => voarPara(item, 8)}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-left text-[11.5px] transition hover:bg-accent"
                      >
                        <span className="min-w-0 truncate">
                          <span className="font-mono text-[10.5px] text-emerald-300">{item.code}</span> {item.label}
                        </span>
                        <span className="shrink-0 text-muted-foreground">
                          {numberFormat.format(item.contracts)} · {formatMoneyCompact(item.value)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}

            {(dados?.not_plotted?.length || (dados?.countries ?? []).some((item) => item.lat === undefined)) ? (
              <Card titulo="Sem posição no mapa">
                <ul className="space-y-1">
                  {(dados?.not_plotted ?? []).map((item, indice) => (
                    <li key={`${item.code}-${indice}`} className="flex items-center justify-between gap-2 px-2 py-0.5 text-[11.5px]">
                      <span className="min-w-0 truncate">
                        <span className="font-mono text-[10.5px] text-muted-foreground">{item.code}</span> {item.label}
                      </span>
                      <span className="shrink-0 text-muted-foreground">{numberFormat.format(item.contracts)}</span>
                    </li>
                  ))}
                  {(dados?.countries ?? [])
                    .filter((item) => item.lat === undefined)
                    .map((item) => (
                      <li key={`pais-${item.code}`} className="flex items-center justify-between gap-2 px-2 py-0.5 text-[11.5px]">
                        <span className="min-w-0 truncate">{item.label}</span>
                        <span className="shrink-0 text-muted-foreground">{numberFormat.format(item.contracts)}</span>
                      </li>
                    ))}
                </ul>
              </Card>
            ) : null}

            <p className="px-1 text-[10.5px] leading-relaxed text-muted-foreground">
              Posições: centro de massa do polígono oficial do departamento, centro de massa dos departamentos
              para as regiões e prefeitura para o ultramar. Círculos <span className="text-amber-300">âmbar</span> são
              departamentos, <span className="text-sky-300">azuis</span> regiões e <span className="text-emerald-300">verdes</span> nível
              país; tracejado = posição aproximada para esse nível.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- auxiliares */

function Kpi({ icon, label, value, hint }: { icon: ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        {icon} {label}
      </div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function Card({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div className="glass-card space-y-2 rounded-2xl p-3">
      <div className="text-[11.5px] font-semibold text-foreground">{titulo}</div>
      {children}
    </div>
  );
}

function Campo({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="mt-0.5 block">{children}</span>
    </label>
  );
}

export default ContractsFrMapPage;
