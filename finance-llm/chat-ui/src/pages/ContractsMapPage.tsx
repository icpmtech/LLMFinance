/**
 * Mapa ibérico dos contratos públicos — `/contracts/map`.
 *
 * Os contratos não têm coordenadas: o que existe é a divisão administrativa onde
 * foram executados — distrito em Portugal (`localExecucao`) e província/NUTS em
 * Espanha (`nuts`). Cada região aparece como um círculo posicionado na capital
 * (distrito) ou capital de província, dimensionado pelo valor ou pelo número de
 * contratos. As posições que só se conhecem ao nível de NUTS 2/1 saem com círculo
 * tracejado e as regiões insulares (Açores, Madeira, Canarias, Ceuta, Melilla)
 * ficam listadas à parte, porque não cabem no enquadramento da Península.
 *
 * A página ocupa a altura do ecrã (mapa à esquerda, leitura à direita), como o
 * Chat e o Hermes: o mapa não deve empurrar a página para baixo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Crosshair,
  Euro,
  ExternalLink,
  FileText,
  Globe2,
  Info,
  Loader2,
  MapPin,
  RefreshCw,
  RotateCcw,
  Search,
  Sigma,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  getContractsIberiaMap,
  type IberiaMapRegion,
  type IberiaMapResponse,
} from "../contractsMapApi";
import { autocompleteContracts, getContractYears, searchContracts } from "../api";
import { autocompleteContratosEs, getContratosEsStatus, searchContratosEs } from "../contratosEsApi";
import type { ContractItem } from "../types";
import {
  IBERIA_ISLANDS_VIEW,
  IBERIA_VIEW,
  LEVEL_LABELS,
  allIberiaRegions,
  foldIberiaText,
  isOffshoreRegion,
  resolveIberiaRegion,
  type IberiaRegion,
} from "../components/geo/iberia";
import { TILE_SIZE, latToWorld, lonToWorld, worldToLat, worldToLon } from "../components/graph/geo";

interface ContractsMapPageProps {
  onSwitchView: () => void;
  /**
   * Abre a ficha de uma região (contratos, entidades e métricas). O App decide
   * se abre numa janela própria ou numa vista de página inteira.
   */
  onOpenRegionDetail?: (pais: "PT" | "ES", code: string, label: string, ano: number | null) => void;
}

type Metric = "value" | "count";
/** Filtros de pesquisa aplicados ao agregado do mapa. */
type MapFilters = { q?: string; entidade?: string; cpv?: string };
/** Sugestão escolhida na caixa de pesquisa. */
type Suggestion = { text: string; kind: "entidade" | "cpv"; pais: "PT" | "ES"; count: number };

type CountryFilter = "all" | "PT" | "ES";

const COUNTRY_COLORS: Record<"PT" | "ES", string> = { PT: "#10a37f", ES: "#f59e0b" };
const COUNTRY_LABELS: Record<"PT" | "ES", string> = { PT: "Portugal", ES: "Espanha" };

/** Placed region: linha da API + posição resolvida no mapa. */
type PlacedRegion = { row: IberiaMapRegion; region: IberiaRegion };

function formatNumber(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT");
}

function formatEuro(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

/** Valores grandes em forma curta (2,4 mil M €) para caber nos rótulos do mapa. */
function formatCompactEuro(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil M €`;
  if (abs >= 1e6) return `${(value / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M €`;
  if (abs >= 1e3) return `${(value / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} mil €`;
  return formatEuro(value);
}

function formatCompactNumber(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} M`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil`;
  return formatNumber(value);
}

/** Nome das entidades adjudicantes de um contrato português. */
function ptPartyNames(item: ContractItem): string {
  const parties = item.adjudicantes;
  if (!parties) return "";
  const list = Array.isArray(parties) ? parties : [parties];
  return list
    .flatMap((party) => (Array.isArray(party?.parsed) ? party.parsed : []))
    .map((parsed) => parsed?.nome)
    .filter(Boolean)
    .slice(0, 2)
    .join(", ");
}

type RegionContract = { id: string; title: string; subtitle: string; value?: number | null; ano?: number | null };

function ptRegionContract(item: ContractItem, index: number): RegionContract {
  return {
    id: item.doc_id ?? item.idcontrato ?? String(index),
    title: item.objectoContrato?.trim() || "Contrato sem objeto descrito",
    subtitle: ptPartyNames(item) || "Adjudicante não identificado",
    value: item.precoContratual ?? null,
    ano: typeof item.Ano === "number" ? item.Ano : null,
  };
}

export function ContractsMapPage({ onSwitchView, onOpenRegionDetail }: ContractsMapPageProps) {
  const [metric, setMetric] = useState<Metric>("value");
  const [country, setCountry] = useState<CountryFilter>("all");
  const [ano, setAno] = useState<number | "">("");
  const [years, setYears] = useState<number[]>([]);

  const [filters, setFilters] = useState<MapFilters>({});
  const [searchText, setSearchText] = useState("");
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestLoading, setSuggestLoading] = useState(false);

  const [data, setData] = useState<IberiaMapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<{ pais: "PT" | "ES"; code: string } | null>(null);
  const [hovered, setHovered] = useState<PlacedRegion | null>(null);
  /** Menu de contexto do mapa (botão direito): sobre uma região ou no fundo. */
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; entry: PlacedRegion | null } | null>(null);
  const [regionContracts, setRegionContracts] = useState<RegionContract[] | null>(null);
  const [regionLoading, setRegionLoading] = useState(false);

  /* --------------------------------------------------------------- mapa */

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 900, height: 560 });
  const [center, setCenter] = useState(IBERIA_VIEW.center);
  const [zoom, setZoom] = useState(IBERIA_VIEW.zoom);
  const [tilesLoaded, setTilesLoaded] = useState(0);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ px: number; py: number; lat: number; lon: number } | null>(null);
  const dragMovedRef = useRef(false);

  /** Tamanho real do contentor (a grelha de tiles parte daqui, sem offsets fixos). */
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
  }, [zoom, size.width, size.height]);

  const projection = useMemo(() => {
    const width = size.width || 900;
    const height = size.height || 560;
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
  }, [center.lat, center.lon, size.height, size.width, zoom]);

  /** Zoom mantendo fixo o ponto sob o cursor (ou o centro). */
  const zoomAt = useCallback(
    (delta: number, anchor?: { x: number; y: number }) => {
      const next = Math.max(3, Math.min(13, zoom + delta));
      if (next === zoom) return;
      const rect = containerRef.current?.getBoundingClientRect();
      const offsetX = anchor && rect ? anchor.x - rect.left - size.width / 2 : 0;
      const offsetY = anchor && rect ? anchor.y - rect.top - size.height / 2 : 0;
      const anchorLon = worldToLon(lonToWorld(center.lon, zoom) + offsetX, zoom);
      const anchorLat = worldToLat(latToWorld(center.lat, zoom) + offsetY, zoom);
      setCenter({
        lat: worldToLat(latToWorld(anchorLat, next) - offsetY, next),
        lon: worldToLon(lonToWorld(anchorLon, next) - offsetX, next),
      });
      setZoom(next);
    },
    [center.lat, center.lon, size.height, size.width, zoom],
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

  const focusRegion = useCallback((region: IberiaRegion) => {
    setCenter({ lat: region.lat, lon: region.lon });
    setZoom(region.level === "distrito" || region.level === "nuts3" ? 8 : 6);
  }, []);

  const resetView = useCallback(() => {
    setCenter(IBERIA_VIEW.center);
    setZoom(IBERIA_VIEW.zoom);
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    // O menu fecha ao clicar fora dele: se fechasse também ao carregar num item,
    // o item desaparecia antes de receber o `click` (o clique nunca acontecia).
    if (!(event.target as HTMLElement).closest("[role='menu']")) setContextMenu(null);
    if ((event.target as HTMLElement).closest("[data-map-chrome]")) return;
    dragRef.current = { px: event.clientX, py: event.clientY, lat: center.lat, lon: center.lon };
    dragMovedRef.current = false;
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  /** Abre o menu de contexto na posição do clique (dentro do mapa). */
  const openContextMenu = (event: React.MouseEvent, entry: PlacedRegion | null) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = containerRef.current?.getBoundingClientRect();
    setContextMenu({
      x: event.clientX - (rect?.left ?? 0),
      y: event.clientY - (rect?.top ?? 0),
      entry,
    });
    if (entry) setSelected({ pais: entry.row.pais, code: entry.row.code });
  };

  /** Abre a janela da região (contratos, entidades e métricas). */
  const openRegionWindow = (entry: PlacedRegion) => {
    setContextMenu(null);
    onOpenRegionDetail?.(entry.row.pais, entry.row.code, entry.region.name, ano === "" ? null : Number(ano));
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start) return;
    const dx = event.clientX - start.px;
    const dy = event.clientY - start.py;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMovedRef.current = true;
    setCenter({
      lat: worldToLat(latToWorld(start.lat, zoom) - dy, zoom),
      lon: worldToLon(lonToWorld(start.lon, zoom) - dx, zoom),
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
    const centerX = lonToWorld(center.lon, zoom);
    const centerY = latToWorld(center.lat, zoom);
    const pan = (dx: number, dy: number) => {
      setCenter({ lat: worldToLat(centerY + dy, zoom), lon: worldToLon(centerX + dx, zoom) });
    };
    if (event.key === "ArrowLeft") pan(-step, 0);
    else if (event.key === "ArrowRight") pan(step, 0);
    else if (event.key === "ArrowUp") pan(0, -step);
    else if (event.key === "ArrowDown") pan(0, step);
    else if (event.key === "+" || event.key === "=") zoomAt(1);
    else if (event.key === "-" || event.key === "_") zoomAt(-1);
    else if (event.key === "0") resetView();
    else if (event.key === "Escape") setContextMenu(null);
    else return;
    event.preventDefault();
  };

  /* ------------------------------------------------------------- dados */

  useEffect(() => {
    Promise.all([getContractYears(), getContratosEsStatus()])
      .then(([pt, es]) => {
        const all = new Set<number>();
        for (const row of pt?.indexed ?? []) all.add(row.year);
        for (const year of es?.years ?? []) all.add(year);
        setYears([...all].sort((a, b) => b - a));
      })
      .catch(() => setYears([]));
  }, []);

  const loadMap = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getContractsIberiaMap({
        ano: ano === "" ? null : ano,
        pais: country,
        q: filters.q,
        entidade: filters.entidade,
        cpv: filters.cpv,
      });
      if (response.error) throw new Error(response.error);
      setData(response);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Erro ao carregar o mapa");
    } finally {
      setLoading(false);
    }
  }, [ano, country, filters.q, filters.entidade, filters.cpv]);

  useEffect(() => {
    void loadMap();
  }, [loadMap]);

  /** Regiões com posição no mapa (as restantes ficam em "sem localização"). */
  const placed = useMemo<PlacedRegion[]>(() => {
    if (!data) return [];
    const rows: PlacedRegion[] = [];
    for (const row of data.regions) {
      const region = resolveIberiaRegion(row.pais, row.code);
      if (region) rows.push({ row, region });
    }
    return rows;
  }, [data]);

  const unplacedRows = useMemo(
    () => (data ? data.regions.filter((row) => !resolveIberiaRegion(row.pais, row.code)) : []),
    [data],
  );

  const offshore = useMemo(() => placed.filter((entry) => isOffshoreRegion(entry.region)), [placed]);
  const onMap = useMemo(() => placed.filter((entry) => !isOffshoreRegion(entry.region)), [placed]);

  const metricOf = useCallback(
    (row: IberiaMapRegion) => (metric === "value" ? row.total_value : row.count),
    [metric],
  );

  const maxMetric = useMemo(() => onMap.reduce((max, entry) => Math.max(max, metricOf(entry.row)), 0), [metricOf, onMap]);

  const ranked = useMemo(
    () => [...placed].sort((a, b) => metricOf(b.row) - metricOf(a.row)).slice(0, 12),
    [metricOf, placed],
  );

  const totals = useMemo(() => {
    const empty = { count: 0, total_value: 0 };
    const countries = data?.countries ?? [];
    const byCountry = Object.fromEntries(countries.map((row) => [row.code, row])) as Record<
      string,
      { total_contracts: number; total_value: number }
    >;
    return {
      countries,
      PT: byCountry.PT ?? { total_contracts: 0, total_value: 0 },
      ES: byCountry.ES ?? { total_contracts: 0, total_value: 0 },
      unspecifiedPT: data?.unspecified?.PT ?? empty,
      unspecifiedES: data?.unspecified?.ES ?? empty,
      other: data?.other_locations ?? empty,
    };
  }, [data]);

  const selectedEntry = useMemo(
    () => placed.find((entry) => entry.row.pais === selected?.pais && entry.row.code === selected?.code) ?? null,
    [placed, selected],
  );

  /** Se a pesquisa deixar a região escolhida sem resultados, largamos a seleção. */
  useEffect(() => {
    if (!selected || !data) return;
    const stillHasMatches = data.regions.some((row) => row.pais === selected.pais && row.code === selected.code);
    if (!stillHasMatches) setSelected(null);
  }, [data, selected]);

  /** Contratos da região escolhida (drill-down): maiores valores do período. */
  useEffect(() => {
    if (!selected) {
      setRegionContracts(null);
      return;
    }
    let active = true;
    setRegionLoading(true);
    setRegionContracts(null);
    const year = ano === "" ? undefined : Number(ano);
    const run = async () => {
      try {
        if (selected.pais === "PT") {
          const response = await searchContracts({
            region: selected.code,
            year,
            q: filters.q,
            entity: filters.entidade,
            cpv_code: filters.cpv,
            size: 6,
            sort_by: "precoContratual",
            sort_order: "desc",
          });
          if (!active) return;
          setRegionContracts((response.items ?? []).map(ptRegionContract));
        } else {
          const response = await searchContratosEs({
            nuts: selected.code,
            ano: year,
            q: [filters.q, filters.entidade].filter(Boolean).join(" ") || undefined,
            cpv_code: filters.cpv,
            size: 6,
            sort_by: "valor_adjudicado",
            sort_order: "desc",
          });
          if (!active) return;
          setRegionContracts(
            (response.items ?? []).map((item, index) => ({
              id: item.doc_id ?? item.id_expediente ?? String(index),
              title: item.objeto?.trim() || item.descripcion?.trim() || "Contrato sem objeto descrito",
              subtitle: [item.organo_nombre, item.adjudicatario_nombre].filter(Boolean).join(" → ") || "Sem entidades",
              value: item.valor_adjudicado ?? item.valor_base ?? null,
              ano: item.ano ?? null,
            })),
          );
        }
      } catch {
        if (active) setRegionContracts([]);
      } finally {
        if (active) setRegionLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [ano, filters.q, filters.entidade, filters.cpv, selected]);

  /* ------------------------------------------------------------ pesquisa */

  /** Regiões que correspondem ao texto (sugestões «ir para», independentes dos filtros). */
  const regionSuggestions = useMemo(() => {
    const text = foldIberiaText(searchText);
    if (text.length < 2) return [];
    return allIberiaRegions()
      .filter((region) => foldIberiaText(region.name).includes(text) || foldIberiaText(region.code).includes(text))
      .slice(0, 5);
  }, [searchText]);

  /** Sugestões de entidades e CPV dos dois países (com atraso, para não martelar a API). */
  useEffect(() => {
    const text = searchText.trim();
    if (!suggestOpen || text.length < 2) {
      setSuggestions([]);
      setSuggestLoading(false);
      return;
    }
    let active = true;
    setSuggestLoading(true);
    const timer = setTimeout(async () => {
      try {
        const [pt, es] = await Promise.all([
          autocompleteContracts(text, 6).catch(() => null),
          autocompleteContratosEs(text, 6).catch(() => null),
        ]);
        if (!active) return;
        const rows: Suggestion[] = [];
        for (const item of pt?.suggestions ?? []) {
          rows.push({ text: item.text, kind: item.type === "cpv" ? "cpv" : "entidade", pais: "PT", count: item.count ?? 0 });
        }
        for (const item of es?.suggestions ?? []) {
          rows.push({ text: item.text, kind: item.type === "cpv" ? "cpv" : "entidade", pais: "ES", count: item.count ?? 0 });
        }
        setSuggestions(rows.slice(0, 12));
      } catch {
        if (active) setSuggestions([]);
      } finally {
        if (active) setSuggestLoading(false);
      }
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [searchText, suggestOpen]);

  /** Texto livre → filtro `q` (mantém CPV/entidade já escolhidos). */
  const applyTextSearch = (text: string) => {
    const value = text.trim();
    setFilters((prev) => ({ q: value || undefined, entidade: prev.entidade, cpv: prev.cpv }));
    setSuggestOpen(false);
  };

  /** Sugestão escolhida → filtro de entidade ou CPV (substitui a pesquisa livre). */
  const applySuggestion = (suggestion: Suggestion) => {
    setFilters(
      suggestion.kind === "cpv"
        ? { cpv: suggestion.text }
        : { entidade: suggestion.text },
    );
    setSearchText("");
    setSuggestOpen(false);
  };

  const goToRegion = (region: IberiaRegion) => {
    setSelected({ pais: region.pais, code: region.code });
    focusRegion(region);
    setSearchText("");
    setSuggestOpen(false);
  };

  const activeFilters = useMemo(
    () =>
      [
        filters.q ? { key: "q" as const, label: `pesquisa: «${filters.q}»` } : null,
        filters.entidade ? { key: "entidade" as const, label: `entidade: «${filters.entidade}»` } : null,
        filters.cpv ? { key: "cpv" as const, label: `CPV: ${filters.cpv}` } : null,
      ].filter((entry): entry is { key: keyof MapFilters; label: string } => entry !== null),
    [filters],
  );
  const hasFilters = activeFilters.length > 0;
  const matchedTotal = totals.PT.total_contracts + totals.ES.total_contracts;

  const bubbleRadius = (value: number) => {
    const ratio = maxMetric > 0 ? Math.max(0, value) / maxMetric : 0;
    return 7 + 34 * Math.sqrt(ratio);
  };

  /** Etiqueta do detalhe rápido: região em foco (hover) ou última escolhida. */
  const spotlight = hovered ?? selectedEntry;
  const unplacedCount = unplacedRows.reduce((sum, row) => sum + row.count, 0);
  const unplacedValue = unplacedRows.reduce((sum, row) => sum + row.total_value, 0);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background text-foreground">
      {/* Cabeçalho: filtros do agregado */}
      <header className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <button
          type="button"
          onClick={onSwitchView}
          className="flex items-center gap-2 rounded-full glass-card px-3 py-1.5 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="flex items-center gap-2">
          <MapPin size={18} className="text-primary" />
          <div>
            <h1 className="text-sm font-semibold leading-tight">Mapa de contratos · Portugal e Espanha</h1>
            <p className="text-[11px] text-muted-foreground">
              Por distrito de execução (PT) e província/NUTS (ES)
            </p>
          </div>
        </div>

        {/* Pesquisa: texto livre, entidade, CPV ou salto para uma região */}
        <div className="relative order-last w-full max-w-[460px] flex-1 md:order-none md:w-auto">
          <div className="flex items-center gap-2 rounded-2xl glass-card px-3 py-1.5">
            <Search size={14} className="shrink-0 text-muted-foreground" />
            <input
              value={searchText}
              onChange={(event) => {
                setSearchText(event.target.value);
                setSuggestOpen(true);
              }}
              onFocus={() => setSuggestOpen(true)}
              onBlur={() => setSuggestOpen(false)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  applyTextSearch(searchText);
                  (event.target as HTMLInputElement).blur();
                } else if (event.key === "Escape") {
                  setSuggestOpen(false);
                  (event.target as HTMLInputElement).blur();
                }
              }}
              placeholder="Pesquisar contratos no mapa: objeto, entidade ou CPV…"
              aria-label="Pesquisar contratos no mapa"
              className="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground"
            />
            {suggestLoading && <Loader2 size={12} className="shrink-0 animate-spin text-muted-foreground" />}
            {searchText && (
              <button
                type="button"
                onClick={() => setSearchText("")}
                aria-label="Limpar texto de pesquisa"
                className="shrink-0 rounded-full p-0.5 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
              >
                <X size={12} />
              </button>
            )}
          </div>

          {suggestOpen && (regionSuggestions.length > 0 || suggestions.length > 0 || searchText.trim().length >= 2) && (
            <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-[330px] overflow-y-auto rounded-2xl border border-white/10 bg-[#07151b]/95 p-1 shadow-2xl backdrop-blur-xl">
              {regionSuggestions.length > 0 && (
                <>
                  <p className="px-2 pt-1.5 pb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    Ir para a região
                  </p>
                  {regionSuggestions.map((region) => (
                    <button
                      key={`go-${region.pais}-${region.code}`}
                      type="button"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        goToRegion(region);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: COUNTRY_COLORS[region.pais] }} />
                      <MapPin size={12} className="shrink-0 text-muted-foreground" />
                      <span className="truncate">{region.name}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                        {COUNTRY_LABELS[region.pais]} · {LEVEL_LABELS[region.level]}
                      </span>
                    </button>
                  ))}
                </>
              )}

              {suggestions.length > 0 && (
                <>
                  <p className="px-2 pt-2 pb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    Pesquisar contratos de…
                  </p>
                  {suggestions.map((suggestion, index) => (
                    <button
                      key={`sug-${suggestion.pais}-${index}-${suggestion.text}`}
                      type="button"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        applySuggestion(suggestion);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: COUNTRY_COLORS[suggestion.pais] }} />
                      <span className="truncate" title={suggestion.text}>
                        {suggestion.text}
                      </span>
                      <span className="ml-auto shrink-0 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {suggestion.kind === "cpv" ? `CPV · ${suggestion.count}` : `Entidade · ${formatCompactNumber(suggestion.count)}`}
                      </span>
                    </button>
                  ))}
                </>
              )}

              {searchText.trim().length >= 2 && (
                <button
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    applyTextSearch(searchText);
                  }}
                  className="mt-1 flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs text-primary transition hover:bg-primary/10"
                >
                  <Search size={12} className="shrink-0" />
                  Ver no mapa os contratos com «{searchText.trim()}»
                </button>
              )}
            </div>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-2xl glass-card p-1 text-xs">
            {(["all", "PT", "ES"] as CountryFilter[]).map((candidate) => (
              <button
                key={candidate}
                type="button"
                onClick={() => setCountry(candidate)}
                aria-pressed={country === candidate}
                className={`rounded-xl px-2.5 py-1 transition ${
                  country === candidate ? "bg-primary/15 text-primary" : "hover:bg-white/5"
                }`}
              >
                {candidate === "all" ? "Ambos" : COUNTRY_LABELS[candidate]}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 rounded-2xl glass-card p-1 text-xs">
            {([["value", "Valor"], ["count", "Contratos"]] as [Metric, string][]).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setMetric(key)}
                aria-pressed={metric === key}
                className={`flex items-center gap-1 rounded-xl px-2.5 py-1 transition ${
                  metric === key ? "bg-primary/15 text-primary" : "hover:bg-white/5"
                }`}
              >
                {key === "value" ? <Euro size={13} /> : <Sigma size={13} />}
                {label}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2 rounded-2xl glass-card px-3 py-1.5 text-xs">
            <span className="text-muted-foreground">Ano</span>
            <select
              value={ano}
              onChange={(event) => setAno(event.target.value ? Number(event.target.value) : "")}
              className="bg-transparent text-xs outline-none"
            >
              <option value="">Todos</option>
              {years.map((year) => (
                <option key={year} value={year} className="text-foreground">
                  {year}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => void loadMap()}
            className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            Atualizar
          </button>
        </div>
      </header>

      {/* Filtros de pesquisa ativos */}
      {hasFilters && (
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-1.5 text-[11px]">
          <span className="text-muted-foreground">
            {formatNumber(matchedTotal)} contratos correspondem aos filtros
          </span>
          {activeFilters.map((filter) => (
            <span key={filter.key} className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-1 text-primary">
              {filter.label}
              <button
                type="button"
                onClick={() => setFilters((prev) => ({ ...prev, [filter.key]: undefined }))}
                aria-label={`Remover filtro ${filter.key}`}
                className="rounded-full p-0.5 transition hover:bg-primary/20"
              >
                <X size={11} />
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={() => setFilters({})}
            className="rounded-full px-2 py-1 text-muted-foreground transition hover:bg-white/5 hover:text-foreground"
          >
            limpar tudo
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* Mapa */}
        <div
          ref={containerRef}
          tabIndex={0}
          role="application"
          aria-label="Mapa de contratos de Portugal e Espanha: arraste para navegar, roda do rato para zoom, 0 para reenquadrar"
          onKeyDown={handleKeyDown}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onContextMenu={(event) => openContextMenu(event, null)}
          onDoubleClick={(event) => zoomAt(1, { x: event.clientX, y: event.clientY })}
          className="relative min-h-[320px] flex-1 touch-none overflow-hidden bg-[#0a1f29] outline-none select-none"
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

          {/* Regiões: círculo = volume/valor, posição = capital da região */}
          <div className="absolute inset-0">
            {[...onMap]
              .sort((a, b) => metricOf(b.row) - metricOf(a.row))
              .map(({ row, region }) => {
                const point = projection.project(region.lat, region.lon);
                const radius = bubbleRadius(metricOf(row));
                const isSelected = selected?.pais === row.pais && selected?.code === row.code;
                const color = COUNTRY_COLORS[row.pais];
                return (
                  <button
                    key={`${row.pais}-${row.code}`}
                    type="button"
                    data-map-node="true"
                    onMouseEnter={() => setHovered({ row, region })}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered({ row, region })}
                    onContextMenu={(event) => openContextMenu(event, { row, region })}
                    onClick={(event) => {
                      if (dragMovedRef.current) return;
                      event.stopPropagation();
                      setSelected({ pais: row.pais, code: row.code });
                    }}
                    className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
                    style={{ left: point.left, top: point.top, zIndex: isSelected ? 20 : 10 }}
                    title={`${region.name} (${COUNTRY_LABELS[row.pais]}) — ${formatNumber(row.count)} contratos · ${formatEuro(row.total_value)}`}
                  >
                    <span
                      className="rounded-full border-2 transition"
                      style={{
                        width: radius * 2,
                        height: radius * 2,
                        background: `${color}${isSelected ? "cc" : "80"}`,
                        borderColor: isSelected ? "#ffffff" : color,
                        borderStyle: region.approx ? "dashed" : "solid",
                        boxShadow: isSelected ? `0 0 0 3px ${color}55` : "0 2px 6px rgba(0,0,0,0.45)",
                      }}
                    />
                    <span className="mt-0.5 whitespace-nowrap rounded bg-[#07151b]/85 px-1.5 py-0.5 text-[10px] text-white/90">
                      {region.name.length > 18 ? `${region.name.slice(0, 16)}…` : region.name}
                    </span>
                  </button>
                );
              })}
          </div>

          {loading && (
            <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 bg-[#04121a]/70 text-xs text-muted-foreground">
              <Loader2 size={20} className="animate-spin" />
              A agregar contratos de Portugal e Espanha…
              <span className="text-[10px]">A primeira consulta pode demorar alguns segundos.</span>
            </div>
          )}

          {!loading && tilesLoaded < projection.tiles.length && projection.tiles.length > 0 && (
            <div className="absolute inset-x-0 top-2 z-30 flex justify-center">
              <span className="flex items-center gap-2 rounded-full bg-[#07151b]/85 px-3 py-1 text-[11px] text-muted-foreground">
                <RefreshCw size={12} className="animate-spin" /> A carregar mapa…
              </span>
            </div>
          )}

          {/* Detalhe rápido da região em foco */}
          {spotlight && (
            <div
              data-map-chrome
              className="absolute bottom-3 left-3 z-30 max-w-[280px] rounded-2xl glass-card px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: COUNTRY_COLORS[spotlight.row.pais] }} />
                <span className="text-sm font-medium">{spotlight.region.name}</span>
                <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {LEVEL_LABELS[spotlight.region.level]}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatNumber(spotlight.row.count)} contratos ·{" "}
                <span className="text-foreground">{formatEuro(spotlight.row.total_value)}</span>
              </p>
              {spotlight.region.approx && (
                <p className="mt-1 flex items-start gap-1 text-[10px] text-amber-200">
                  <Info size={12} className="mt-0.5 shrink-0" />
                  Posição aproximada: o dado só identifica {LEVEL_LABELS[spotlight.region.level].toLowerCase()}.
                </p>
              )}
            </div>
          )}

          {/* Controlos + legenda */}
          <div className="absolute bottom-3 right-3 z-30 flex flex-col items-end gap-2" data-map-chrome>
            <div className="flex items-center gap-1 rounded-2xl bg-[#07151b]/90 p-1">
              <button
                type="button"
                onClick={(event) => zoomAt(1, { x: event.clientX, y: event.clientY })}
                className="rounded-xl p-1.5 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                aria-label="Aproximar"
              >
                <ZoomIn size={15} />
              </button>
              <button
                type="button"
                onClick={(event) => zoomAt(-1, { x: event.clientX, y: event.clientY })}
                className="rounded-xl p-1.5 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                aria-label="Afastar"
              >
                <ZoomOut size={15} />
              </button>
              <button
                type="button"
                onClick={resetView}
                className="rounded-xl p-1.5 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                aria-label="Reenquadrar Portugal e Espanha"
                title="Reenquadrar Portugal e Espanha"
              >
                <Crosshair size={15} />
              </button>
            </div>
            <span className="rounded-full bg-[#07151b]/90 px-2 py-1 text-[10px] text-muted-foreground">Nível {zoom}</span>
          </div>

          {/* Menu de contexto (botão direito): região ou fundo do mapa */}
          {contextMenu && (
            <div
              role="menu"
              data-map-chrome
              className="absolute z-40 min-w-[268px] max-w-[320px] rounded-2xl border border-white/10 bg-[#07151b]/95 p-1 shadow-2xl backdrop-blur-xl"
              style={{
                left: Math.min(contextMenu.x, Math.max(8, size.width - 320)),
                top: Math.min(contextMenu.y, Math.max(8, size.height - 300)),
              }}
            >
              {contextMenu.entry ? (
                <>
                  <div className="px-2 py-1.5">
                    <p className="flex items-center gap-2 text-xs font-medium">
                      <span className="h-2 w-2 rounded-full" style={{ background: COUNTRY_COLORS[contextMenu.entry.row.pais] }} />
                      {contextMenu.entry.region.name}
                    </p>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      {COUNTRY_LABELS[contextMenu.entry.row.pais]} · {LEVEL_LABELS[contextMenu.entry.region.level]} ·{" "}
                      {formatNumber(contextMenu.entry.row.count)} contratos ·{" "}
                      {formatCompactEuro(contextMenu.entry.row.total_value)}
                    </p>
                  </div>
                  <div className="my-1 h-px bg-white/10" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => openRegionWindow(contextMenu.entry as PlacedRegion)}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs text-primary transition hover:bg-primary/10"
                  >
                    <ExternalLink size={13} className="shrink-0" />
                    Abrir janela · contratos, entidades e métricas
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      focusRegion(contextMenu.entry!.region);
                      setContextMenu(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                  >
                    <Crosshair size={13} className="shrink-0" />
                    Focar no mapa
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setSelected({ pais: contextMenu.entry!.row.pais, code: contextMenu.entry!.row.code });
                      setContextMenu(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                  >
                    <FileText size={13} className="shrink-0" />
                    Ver contratos da região no painel
                  </button>
                  <div className="my-1 h-px bg-white/10" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setSelected(null);
                      setContextMenu(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                  >
                    <X size={13} className="shrink-0" />
                    Limpar seleção
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      resetView();
                      setContextMenu(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                  >
                    <RotateCcw size={13} className="shrink-0" />
                    Reenquadrar Portugal e Espanha
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setCenter(IBERIA_ISLANDS_VIEW.center);
                      setZoom(IBERIA_ISLANDS_VIEW.zoom);
                      setContextMenu(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                  >
                    <Globe2 size={13} className="shrink-0" />
                    Ver ilhas (Açores, Madeira, Canárias)
                  </button>
                  {hasFilters && (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setFilters({});
                        setContextMenu(null);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                    >
                      <X size={13} className="shrink-0" />
                      Limpar filtros de pesquisa
                    </button>
                  )}
                  {selected && (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setSelected(null);
                        setContextMenu(null);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition hover:bg-white/10"
                    >
                      <X size={13} className="shrink-0" />
                      Limpar seleção
                    </button>
                  )}
                  <p className="px-2 py-1.5 text-[10px] leading-relaxed text-muted-foreground">
                    Botão direito sobre um círculo abre a ficha da região (contratos, entidades e métricas).
                  </p>
                </>
              )}
            </div>
          )}

          <div
            className="absolute left-3 top-3 z-20 max-w-[60%] rounded-full bg-[#07151b]/85 px-3 py-1 text-[10px] text-muted-foreground"
            data-map-chrome
          >
            Arraste para navegar · roda para zoom · botão direito abre opções · © OpenStreetMap
          </div>

          {offshore.length > 0 && size.width > 820 && (
            <div className="absolute right-3 top-3 z-30 rounded-2xl bg-[#07151b]/90 px-3 py-2 text-[11px] text-muted-foreground" data-map-chrome>
              <span className="text-foreground">{offshore.length}</span> regiões fora do enquadramento (ilhas e
              cidades autónomas) — abra-as na lista lateral.
            </div>
          )}
        </div>

        {/* Painel de leitura */}
        <aside className="min-h-0 w-full shrink-0 overflow-y-auto border-t border-white/10 p-3 lg:h-full lg:w-[380px] lg:border-l lg:border-t-0">
          {error && (
            <div className="mb-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}
          {data?.warnings?.map((warning) => (
            <div key={warning} className="mb-2 rounded-2xl border border-amber-300/25 bg-amber-400/10 px-3 py-2 text-[11px] text-amber-100">
              {warning}
            </div>
          ))}

          {/* Totais por país */}
          <div className="grid grid-cols-2 gap-2">
            {(["PT", "ES"] as const).map((code) => {
              const row = totals[code];
              const share = totals.PT.total_value + totals.ES.total_value > 0
                ? (row.total_value / (totals.PT.total_value + totals.ES.total_value)) * 100
                : 0;
              return (
                <div key={code} className="rounded-2xl glass-card p-3">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: COUNTRY_COLORS[code] }} />
                    <span className="text-xs font-medium">{COUNTRY_LABELS[code]}</span>
                  </div>
                  <p className="mt-2 text-lg font-semibold leading-none">{formatCompactEuro(row.total_value)}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{formatCompactNumber(row.total_contracts)} contratos</p>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full" style={{ width: `${share}%`, background: COUNTRY_COLORS[code] }} />
                  </div>
                  <p className="mt-1 text-[10px] text-muted-foreground">{share.toFixed(1)}% do valor da Península</p>
                </div>
              );
            })}
          </div>

          {/* Ranking de regiões */}
          <div className="mt-3 rounded-2xl glass-card p-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Regiões por {metric === "value" ? "valor" : "nº de contratos"}
              </h2>
              <span className="text-[10px] text-muted-foreground">{placed.length} com localização</span>
            </div>
            <div className="mt-2 space-y-1.5">
              {ranked.map(({ row, region }) => {
                const value = metricOf(row);
                const width = maxMetric > 0 ? (value / maxMetric) * 100 : 0;
                const isSelected = selected?.pais === row.pais && selected?.code === row.code;
                return (
                  <button
                    key={`rank-${row.pais}-${row.code}`}
                    type="button"
                    onClick={() => {
                      setSelected({ pais: row.pais, code: row.code });
                      focusRegion(region);
                    }}
                    className={`w-full rounded-xl px-2 py-1.5 text-left transition ${
                      isSelected ? "bg-primary/10" : "hover:bg-white/5"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: COUNTRY_COLORS[row.pais] }} />
                      <span className="truncate text-xs">{region.name}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                        {metric === "value" ? formatCompactEuro(row.total_value) : formatNumber(row.count)}
                      </span>
                    </div>
                    <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full rounded-full" style={{ width: `${width}%`, background: COUNTRY_COLORS[row.pais] }} />
                    </div>
                  </button>
                );
              })}
              {!loading && ranked.length === 0 && (
                <p className="py-3 text-center text-xs text-muted-foreground">Sem regiões para estes filtros.</p>
              )}
            </div>
          </div>

          {/* Região escolhida + maiores contratos */}
          {selectedEntry && (
            <div className="mt-3 rounded-2xl glass-card p-3">
              <div className="flex items-start gap-2">
                <span className="mt-1 h-2.5 w-2.5 rounded-full" style={{ background: COUNTRY_COLORS[selectedEntry.row.pais] }} />
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-sm font-semibold">{selectedEntry.region.name}</h2>
                  <p className="text-[11px] text-muted-foreground">
                    {COUNTRY_LABELS[selectedEntry.row.pais]} · {LEVEL_LABELS[selectedEntry.region.level]}
                    {selectedEntry.region.approx ? " · posição aproximada" : ""}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded-xl px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/5 hover:text-foreground"
                >
                  limpar
                </button>
              </div>

              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded-xl bg-white/5 px-2 py-1.5">
                  <p className="text-muted-foreground">Contratos</p>
                  <p className="text-sm font-medium">{formatNumber(selectedEntry.row.count)}</p>
                </div>
                <div className="rounded-xl bg-white/5 px-2 py-1.5">
                  <p className="text-muted-foreground">Valor</p>
                  <p className="text-sm font-medium">{formatCompactEuro(selectedEntry.row.total_value)}</p>
                </div>
                <div className="rounded-xl bg-white/5 px-2 py-1.5">
                  <p className="text-muted-foreground">Ticket médio</p>
                  <p className="text-sm font-medium">
                    {formatEuro(selectedEntry.row.count ? selectedEntry.row.total_value / selectedEntry.row.count : null)}
                  </p>
                </div>
                <div className="rounded-xl bg-white/5 px-2 py-1.5">
                  <p className="text-muted-foreground">% do país</p>
                  <p className="text-sm font-medium">
                    {(() => {
                      const countryTotal = totals[selectedEntry.row.pais];
                      if (!countryTotal.total_value) return "—";
                      return `${((selectedEntry.row.total_value / countryTotal.total_value) * 100).toFixed(1)}%`;
                    })()}
                  </p>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Maiores contratos {ano !== "" ? `de ${ano}` : "de todo o período"}
                  {filters.q || filters.entidade || filters.cpv ? " (com os filtros de pesquisa)" : ""}
                </h3>
                {regionLoading && <Loader2 size={12} className="animate-spin text-muted-foreground" />}
              </div>
              <div className="mt-1.5 space-y-1.5">
                {regionContracts?.slice(0, 6).map((contract) => (
                  <div key={contract.id} className="rounded-xl bg-white/5 px-2 py-1.5">
                    <p className="line-clamp-2 text-[11px]">{contract.title}</p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="truncate">{contract.subtitle}</span>
                      <span className="ml-auto shrink-0 text-foreground">{formatCompactEuro(contract.value)}</span>
                      {contract.ano ? <span className="shrink-0">· {contract.ano}</span> : null}
                    </p>
                  </div>
                ))}
                {!regionLoading && regionContracts?.length === 0 && (
                  <p className="py-2 text-center text-[11px] text-muted-foreground">
                    Sem contratos indexados para esta região nestes filtros.
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Regiões sem lugar no mapa */}
          {(offshore.length > 0 || unplacedRows.length > 0) && (
            <div className="mt-3 rounded-2xl glass-card p-3">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sem posição no mapa</h2>
              {offshore.length > 0 && (
                <div className="mt-2">
                  <p className="text-[11px] text-muted-foreground">Regiões insulares e cidades autónomas (fora do enquadramento)</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {offshore
                      .sort((a, b) => metricOf(b.row) - metricOf(a.row))
                      .map(({ row, region }) => (
                        <button
                          key={`off-${row.pais}-${row.code}`}
                          type="button"
                          onClick={() => {
                            setSelected({ pais: row.pais, code: row.code });
                            focusRegion(region);
                          }}
                          className="rounded-full bg-white/5 px-2 py-1 text-[10px] transition hover:bg-white/10"
                          title={`${formatNumber(row.count)} contratos · ${formatEuro(row.total_value)}`}
                        >
                          <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: COUNTRY_COLORS[row.pais] }} />
                          {region.name}
                        </button>
                      ))}
                  </div>
                </div>
              )}
              {unplacedRows.length > 0 && (
                <div className="mt-2">
                  <p className="text-[11px] text-muted-foreground">
                    Códigos/agrupamentos sem posição no mapa ({formatNumber(unplacedCount)} · {formatEuro(unplacedValue)}):
                    províncias não identificadas em Espanha e valores que não são distritos em Portugal.
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {unplacedRows.slice(0, 10).map((row) => (
                      <span
                        key={`unplaced-${row.pais}-${row.code}`}
                        className="rounded-full bg-white/5 px-2 py-1 text-[10px]"
                        title={`${COUNTRY_LABELS[row.pais]} · ${formatNumber(row.count)} contratos · ${formatEuro(row.total_value)}`}
                      >
                        <span
                          className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle"
                          style={{ background: COUNTRY_COLORS[row.pais] }}
                        />
                        {row.label || row.code} · {formatNumber(row.count)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Sem localização + nota metodológica */}
          <div className="mt-3 rounded-2xl glass-card p-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sem localização</h2>
            <ul className="mt-1.5 space-y-1 text-[11px] text-muted-foreground">
              {totals.PT.total_contracts > 0 && (
                <li>
                  Portugal · {formatNumber(totals.unspecifiedPT.count)} contratos ({formatCompactEuro(totals.unspecifiedPT.total_value)}) sem
                  distrito de execução nos dados.
                </li>
              )}
              {totals.ES.total_contracts > 0 && (
                <li>
                  Espanha · {formatNumber(totals.unspecifiedES.count)} contratos ({formatCompactEuro(totals.unspecifiedES.total_value)}) sem
                  código de localização.
                </li>
              )}
              {totals.other.count > 0 && (
                <li>
                  {formatNumber(totals.other.count)} contratos de Espanha executados fora do país (
                  {formatCompactEuro(totals.other.total_value)}).
                </li>
              )}
            </ul>
            <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
              Cada círculo é uma região administrativa (distrito em Portugal, província em Espanha) posicionada na sua
              capital — os contratos publicados não trazem coordenadas. Círculos tracejados são regiões que o dado só
              identifica ao nível de comunidade autónoma ou agrupamento NUTS. Portugal agrega por <code>localExecucao</code>{" "}
              (o campo <code>NUTs</code> só existe em ~14% dos contratos); Espanha por <code>nuts</code>. A pesquisa do mapa
              exige todos os termos (a pesquisa livre das outras páginas é mais permissiva) e aceita também o nome de uma
              região, que aqui serve para saltar até ela. Em Portugal, um contrato com execução em vários distritos conta
              em cada um deles — a ficha da região (botão direito sobre o círculo) dá o número exato de contratos.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
