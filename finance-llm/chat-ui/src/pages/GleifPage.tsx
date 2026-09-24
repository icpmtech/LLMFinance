/**
 * Módulo **GLEIF / LEI** — registos *Legal Entity Identifier* (Golden Copy).
 *
 * Três ecrãs no mesmo módulo (o `section` vem do encaminhamento da app):
 *
 * - **pesquisa** — caixa única no estilo da *Pesquisa total*: nome legal, LEI,
 *   NIF de registo, BIC ou cidade, com sugestões enquanto se escreve, facetas
 *   (país, região, estado, categoria, forma jurídica) e ficha completa do LEI;
 * - **mapa** — agregado por país/região desenhado sobre tiles do
 *   OpenStreetMap (`components/gleif/GleifMap.tsx`), com lista ordenada;
 * - **ingestão** — recolha/indexação (API oficial do GLEIF, ficheiro Golden Copy
 *   ou a golden copy local), acompanhamento das tarefas e exportação CSV.
 *
 * A golden copy vive em `data/gleif/lei.jsonl` e no índice
 * `finance_gleif_lei` — o módulo mostra sempre as duas volumetrias.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  CalendarClock,
  Database,
  Download,
  FileSpreadsheet,
  Fingerprint,
  Globe2,
  Layers,
  Link2,
  Loader2,
  Map as MapIcon,
  MapPin,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  ACTIVE_STATUSES,
  FACET_LABELS,
  categoryLabel,
  deleteGleifIndex,
  getGleifJob,
  getGleifJobs,
  getGleifMap,
  getGleifMeta,
  getGleifStatus,
  gleifExportUrl,
  searchGleif,
  shortDate,
  sourceLabel,
  startGleifIngest,
  statusLabel,
  suggestGleif,
  type GleifFacet,
  type GleifIngestRequest,
  type GleifJob,
  type GleifLei,
  type GleifMapLevel,
  type GleifMapResult,
  type GleifMeta,
  type GleifSearchParams,
  type GleifStatus,
  type GleifSuggestion,
} from "../gleifApi";
import LeiDetail from "../components/gleif/LeiDetail";
import GleifMap, { type GleifMapPoint, type GleifMapView } from "../components/gleif/GleifMap";
import {
  ATLANTIC_ISLANDS_VIEW,
  IBERIA_VIEW,
  WORLD_VIEW,
  countryFlag,
  countryName,
  resolveLeiPlace,
} from "../components/geo/world";

export type GleifSection = "pesquisa" | "mapa" | "ingestao";

/** Vista (`AppView`) de cada secção do módulo. */
export const GLEIF_SECTION_VIEWS: Record<GleifSection, string> = {
  pesquisa: "gleif",
  mapa: "gleif-mapa",
  ingestao: "gleif-ingestao",
};

/** Secção do GLEIF a partir da vista (`AppView`) — `null` se não for deste módulo. */
export function gleifSectionForView(view: string): GleifSection | null {
  const entry = (Object.entries(GLEIF_SECTION_VIEWS) as [GleifSection, string][]).find(([, id]) => id === view);
  return entry ? entry[0] : null;
}

/** Secção do GLEIF a partir do caminho do URL (`/gleif`, `/gleif/mapa`, …). */
export function gleifSectionFromPath(path: string): GleifSection | null {
  if (path === "/gleif") return "pesquisa";
  if (path === "/gleif/mapa") return "mapa";
  if (path === "/gleif/ingestao") return "ingestao";
  return null;
}

/** Caminho do URL de cada secção (inverso de `gleifSectionFromPath`). */
export function gleifPathForSection(section: GleifSection): string {
  if (section === "mapa") return "/gleif/mapa";
  if (section === "ingestao") return "/gleif/ingestao";
  return "/gleif";
}

interface GleifPageProps {
  section?: GleifSection;
  onSectionChange?: (section: GleifSection) => void;
  onOpenRegion?: (level: "country" | "region", code: string, label: string) => void;
  initialQuery?: string;
}

const numberFormat = new Intl.NumberFormat("pt-PT");

function formatNumber(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return numberFormat.format(value);
}

function formatBytes(value?: number | null): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toLocaleString("pt-PT", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

function ApiBadge({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "ok" | "warn" | "info" }) {
  const tones = {
    muted: "border-white/10 bg-white/5 text-muted-foreground",
    ok: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
    warn: "border-amber-400/25 bg-amber-400/10 text-amber-200",
    info: "border-sky-400/25 bg-sky-400/10 text-sky-200",
  } as const;
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] ${tones[tone]}`}>{children}</span>;
}

/* ============================================================ página base */

export default function GleifPage({ section = "pesquisa", onSectionChange, onOpenRegion, initialQuery = "" }: GleifPageProps) {
  const [meta, setMeta] = useState<GleifMeta | null>(null);
  const [status, setStatus] = useState<GleifStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Filtro ativo que o separador «mapa» recebe ao clicar «ver no mapa». */
  const [mapFilter, setMapFilter] = useState<{ country?: string; region?: string }>({});

  /**
   * Secção efetiva do módulo.
   *
   * A app só entrega `onSectionChange` **em modo janelas**; em modo página (a
   * vista normal) seria `undefined` e carregar num separador não fazia nada. Por
   * isso a secção vive também em estado interno (como no Office e no Social) e,
   * quando o App não assume a navegação, o URL é atualizado aqui — o `popstate`
   * do App resolve a vista e o separador fica recarregável/partilhável.
   */
  const [current, setCurrent] = useState<GleifSection>(section);

  useEffect(() => {
    setCurrent(section);
  }, [section]);

  const goToSection = useCallback(
    (next: GleifSection) => {
      setCurrent(next);
      onSectionChange?.(next);
      if (onSectionChange || typeof window === "undefined") return;
      const path = gleifPathForSection(next);
      if (window.location.pathname.replace(/\/$/, "") === path) return;
      window.history.pushState({}, "", path);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    [onSectionChange],
  );

  const refreshStatus = useCallback((force = false) => {
    getGleifStatus(force)
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Estado indisponível"));
  }, []);

  useEffect(() => {
    getGleifMeta()
      .then(setMeta)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Metadados indisponíveis"));
    refreshStatus();
  }, [refreshStatus]);

  const tabs: { id: GleifSection; label: string; icon: React.ReactNode }[] = [
    { id: "pesquisa", label: "Pesquisa", icon: <Search size={13} /> },
    { id: "mapa", label: "Mapa", icon: <MapIcon size={13} /> },
    { id: "ingestao", label: "Ingestão", icon: <Database size={13} /> },
  ];

  const openMap = useCallback(
    (filter: { country?: string; region?: string }) => {
      setMapFilter(filter);
      goToSection("mapa");
    },
    [goToSection],
  );

  const indexed = status?.elasticsearch?.count ?? 0;
  const fileRecords = status?.file?.records ?? 0;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-sky-300/30 via-cyan-500/25 to-slate-900 p-2 text-sky-100">
          <Fingerprint size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">GLEIF · LEI</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            Registos <span className="font-mono">Legal Entity Identifier</span> do Golden Copy — quem é quem no sistema financeiro global
          </p>
        </div>

        <nav className="flex items-center gap-1 rounded-2xl glass-card p-1 text-xs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => goToSection(tab.id)}
              aria-pressed={current === tab.id}
              className={`flex items-center gap-1.5 rounded-xl px-3 py-1 transition ${
                current === tab.id ? "bg-primary/15 text-primary" : "hover:bg-white/5"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {meta ? (
            <ApiBadge>
              índice <span className="font-mono text-foreground">{meta.index}</span>
            </ApiBadge>
          ) : null}
          <ApiBadge tone={indexed > 0 ? "ok" : "warn"}>
            <BadgeCheck size={11} />
            {formatNumber(indexed)} LEI indexados
          </ApiBadge>
          <ApiBadge>
            <FileSpreadsheet size={11} />
            {formatNumber(fileRecords)} na golden copy
          </ApiBadge>
          <button
            type="button"
            onClick={() => refreshStatus(true)}
            className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
          >
            <RefreshCw size={13} />
            Atualizar
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/5 px-6 py-1.5 text-[11px] text-amber-200">
          <AlertTriangle size={13} />
          {error}
        </div>
      )}

      {current === "pesquisa" && (
        <SearchSection initialQuery={initialQuery} meta={meta} status={status} onOpenMap={openMap} />
      )}
      {current === "mapa" && (
        <MapSection
          status={status}
          presets={mapFilter}
          onClearPresets={() => setMapFilter({})}
          onOpenRegion={onOpenRegion ? (level, code, label) => onOpenRegion(level, code, label) : undefined}
        />
      )}
      {current === "ingestao" && <IngestSection meta={meta} status={status} onChanged={refreshStatus} />}
    </div>
  );
}

/* ======================================================== 1. Pesquisa */

function SearchSection({
  initialQuery,
  meta,
  status,
  onOpenMap,
}: {
  initialQuery: string;
  meta: GleifMeta | null;
  status: GleifStatus | null;
  onOpenMap: (filter: { country?: string; region?: string }) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.trim());
  const [filters, setFilters] = useState<Omit<GleifSearchParams, "q" | "size" | "from">>({ sort: "relevance" });
  const [items, setItems] = useState<GleifLei[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Record<string, GleifFacet[]>>({});
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<GleifSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const [selected, setSelected] = useState<GleifLei | null>(null);
  const [showFilters, setShowFilters] = useState(true);
  const pageSize = 25;
  const inputRef = useRef<HTMLInputElement | null>(null);

  const runSearch = useCallback(
    async (text: string, nextPage = 0) => {
      setLoading(true);
      setError(null);
      try {
        const result = await searchGleif({ q: text, ...filters, size: pageSize, from: nextPage * pageSize });
        setItems(result.items || []);
        setTotal(result.total || 0);
        setFacets(result.facets || {});
        setPage(nextPage);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Pesquisa falhou");
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    void runSearch(submitted, 0);
  }, [runSearch, submitted]);

  // Sugestões enquanto se escreve (debounce curto).
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2 || text === submitted) {
      setSuggestions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      suggestGleif(text, 8)
        .then((result) => setSuggestions(result.suggestions || []))
        .catch(() => setSuggestions([]));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, submitted]);

  const submit = (text: string) => {
    setShowSuggestions(false);
    setHighlight(-1);
    setSubmitted(text.trim());
    setQuery(text);
  };

  const activeFilters = Object.entries(filters).filter(
    ([key, value]) => value && key !== "sort",
  ) as [string, string][];

  const facetLabel = (key: string) => FACET_LABELS[key] || key;
  const facetValueLabel = (key: string, value: string) => {
    if (key === "country") return `${countryFlag(value)} ${countryName(value)}`;
    if (key === "region") return meta?.pt_regions?.[value] || value;
    if (key === "status" || key === "verification") return statusLabel(value);
    if (key === "category") return categoryLabel(value);
    return value;
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Caixa de pesquisa estilo «Pesquisa total» */}
      <div className="border-b border-white/10 px-6 py-3">
        <div className="relative mx-auto max-w-3xl">
          <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 focus-within:border-primary/40">
            <Search size={16} className="text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setShowSuggestions(true);
                setHighlight(-1);
              }}
              onFocus={() => setShowSuggestions(true)}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  setHighlight((prev) => Math.min(prev + 1, suggestions.length - 1));
                  event.preventDefault();
                } else if (event.key === "ArrowUp") {
                  setHighlight((prev) => Math.max(prev - 1, -1));
                  event.preventDefault();
                } else if (event.key === "Enter") {
                  if (highlight >= 0 && suggestions[highlight]) submit(suggestions[highlight].lei);
                  else submit(query);
                } else if (event.key === "Escape") {
                  setShowSuggestions(false);
                }
              }}
              placeholder="Nome legal, LEI, NIF de registo, BIC ou cidade…"
              className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
            />
            {query ? (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  submit("");
                  inputRef.current?.focus();
                }}
                className="rounded-full p-1 text-muted-foreground transition hover:bg-white/10"
              >
                <X size={13} />
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => submit(query)}
              className="rounded-xl bg-primary/20 px-3 py-1 text-xs text-primary transition hover:bg-primary/30"
            >
              Pesquisar
            </button>
          </div>

          {showSuggestions && suggestions.length > 0 && (
            <ul className="absolute z-30 mt-1 w-full overflow-hidden rounded-2xl border border-white/10 bg-[#0b1620]/95 shadow-xl backdrop-blur">
              {suggestions.map((suggestion, index) => (
                <li key={suggestion.lei}>
                  <button
                    type="button"
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => submit(suggestion.lei)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition ${
                      highlight === index ? "bg-white/10" : "hover:bg-white/5"
                    }`}
                  >
                    <span>{countryFlag(suggestion.country)}</span>
                    <span className="min-w-0 flex-1 truncate">{suggestion.name}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">{suggestion.lei}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mx-auto mt-2 flex max-w-3xl flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span>exemplos:</span>
          {["EDP", "SONAE", "GALP", "PT-13", "ACTIVE"].map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 transition hover:bg-white/10 hover:text-foreground"
            >
              {example}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setShowFilters((prev) => !prev)}
            className="ml-auto flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 transition hover:bg-white/10 hover:text-foreground"
          >
            <SlidersHorizontal size={11} />
            {showFilters ? "esconder filtros" : "mostrar filtros"}
          </button>
        </div>

        {showFilters && (
          <div className="mx-auto mt-2 flex max-w-3xl flex-wrap items-center gap-2">
            {(Object.keys(FACET_LABELS) as string[]).map((key) => {
              const values = facets[key] || [];
              if (values.length === 0) return null;
              return (
                <label key={key} className="flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1 text-[11px]">
                  <span className="text-muted-foreground">{facetLabel(key)}</span>
                  <select
                    value={(filters as Record<string, string>)[key] || ""}
                    onChange={(event) =>
                      setFilters((prev) => ({ ...prev, [key]: event.target.value || undefined }))
                    }
                    className="max-w-[190px] bg-transparent text-[11px] outline-none"
                  >
                    <option value="">todos</option>
                    {values
                      .filter((facet) => facet.key)
                      .map((facet) => (
                        <option key={facet.key} value={facet.key} className="text-foreground">
                          {facetValueLabel(key, facet.key)} ({formatNumber(facet.count)})
                        </option>
                      ))}
                  </select>
                </label>
              );
            })}
            <label className="ml-auto flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1 text-[11px]">
              <span className="text-muted-foreground">ordenar</span>
              <select
                value={filters.sort || "relevance"}
                onChange={(event) => setFilters((prev) => ({ ...prev, sort: event.target.value as GleifSearchParams["sort"] }))}
                className="bg-transparent text-[11px] outline-none"
              >
                <option value="relevance">relevância</option>
                <option value="name">nome (A→Z)</option>
                <option value="updated">atualização recente</option>
                <option value="registered">registo recente</option>
              </select>
            </label>
          </div>
        )}

        {activeFilters.length > 0 && (
          <div className="mx-auto mt-2 flex max-w-3xl flex-wrap items-center gap-2 text-[11px]">
            {activeFilters.map(([key, value]) => (
              <span key={key} className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-1 text-primary">
                {facetLabel(key)}: {facetValueLabel(key, value)}
                <button
                  type="button"
                  onClick={() => setFilters((prev) => ({ ...prev, [key]: undefined }))}
                  className="rounded-full p-0.5 transition hover:bg-primary/20"
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            <button
              type="button"
              onClick={() => setFilters({ sort: filters.sort })}
              className="rounded-full px-2 py-1 text-muted-foreground transition hover:bg-white/5 hover:text-foreground"
            >
              limpar tudo
            </button>
          </div>
        )}
      </div>

      {/* Resultados */}
      <div className="relative flex min-h-0 flex-1">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-6 py-1.5 text-[11px] text-muted-foreground">
            {loading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> a pesquisar…
              </span>
            ) : (
              <span>
                <span className="text-foreground">{formatNumber(total)}</span> registos
                {submitted ? (
                  <>
                    {" "}
                    para <span className="text-foreground">«{submitted}»</span>
                  </>
                ) : null}
              </span>
            )}
            {total > pageSize && (
              <span className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => void runSearch(submitted, page - 1)}
                  className="rounded-lg border border-white/10 px-2 py-0.5 disabled:opacity-40"
                >
                  anterior
                </button>
                <span>
                  {page + 1}/{totalPages}
                </span>
                <button
                  type="button"
                  disabled={page + 1 >= totalPages}
                  onClick={() => void runSearch(submitted, page + 1)}
                  className="rounded-lg border border-white/10 px-2 py-0.5 disabled:opacity-40"
                >
                  seguinte
                </button>
              </span>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
            {error && (
              <div className="mb-2 flex items-center gap-2 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
                <AlertTriangle size={13} />
                {error}
              </div>
            )}
            {!loading && items.length === 0 && !error && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-xs text-muted-foreground">
                <Fingerprint size={22} />
                {status?.elasticsearch?.count
                  ? "Sem resultados. Tente outro nome, um LEI completo ou remova filtros."
                  : "Ainda não há registos LEI. Faça uma ingestão no separador «Ingestão»."}
              </div>
            )}

            <div className="grid gap-2">
              {items.map((item) => (
                <button
                  key={item.lei}
                  type="button"
                  onClick={() => setSelected(item)}
                  className={`flex items-start gap-3 rounded-2xl border px-3 py-2 text-left transition ${
                    selected?.lei === item.lei
                      ? "border-primary/40 bg-primary/10"
                      : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/5"
                  }`}
                >
                  <span className="mt-0.5 text-lg leading-none">{countryFlag(item.country)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">{item.legal_name}</span>
                      {item.status && (
                        <ApiBadge tone={ACTIVE_STATUSES.has(item.status) ? "ok" : "warn"}>{statusLabel(item.status)}</ApiBadge>
                      )}
                      {item.category && <ApiBadge tone="info">{categoryLabel(item.category)}</ApiBadge>}
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      <span className="font-mono text-foreground/80">{item.lei}</span>
                      <span className="flex items-center gap-1">
                        <MapPin size={11} />
                        {[item.city, item.region_name || item.region, countryName(item.country)].filter(Boolean).join(" · ")}
                      </span>
                      {item.registered_as ? <span>NIF registo {item.registered_as}</span> : null}
                      {item.legal_form ? <span>forma {item.legal_form}</span> : null}
                      {item.initial_registration_date ? <span>desde {shortDate(item.initial_registration_date)}</span> : null}
                    </span>
                  </span>
                  <ArrowRight size={14} className="mt-1 shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          </div>
        </div>

        {/*
          Ficha do LEI.

          Em ecrãs largos é a coluna da direita (sempre visível, com a dica
          «selecione um registo» quando está vazia); em ecrãs estreitos — como a
          janela do IQ OS, que pode ficar abaixo dos 1024 px — aparece **sobreposta**
          aos resultados quando se escolhe um registo. Antes tinha `hidden lg:block`
          e nesse intervalo o clique num resultado não mostrava nada.
        */}
        <aside
          className={`absolute inset-y-0 right-0 z-20 flex w-full max-w-[min(100%,440px)] shrink-0 flex-col overflow-y-auto border-l border-white/10 bg-background/95 px-4 py-3 backdrop-blur lg:static lg:z-auto lg:max-w-none lg:w-[440px] lg:bg-transparent lg:backdrop-blur-none ${
            selected ? "flex" : "hidden lg:flex"
          }`}
        >
          {selected ? (
            <LeiDetail record={selected} onClose={() => setSelected(null)} onOpenMap={onOpenMap} />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-[11px] text-muted-foreground">
              <ShieldCheck size={20} />
              Selecione um registo para ver a ficha completa
              <span className="text-[10px]">Nível 1 (quem é quem) e identificadores associados</span>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/* ============================================================== 2. Mapa */

function MapSection({
  status,
  presets,
  onClearPresets,
  onOpenRegion,
}: {
  status: GleifStatus | null;
  presets: { country?: string; region?: string };
  onClearPresets: () => void;
  /** Abre a janela com as empresas de uma divisão (país, região ou cidade). */
  onOpenRegion?: (level: "country" | "region" | "city", code: string, label: string) => void;
}) {
  const [level, setLevel] = useState<GleifMapLevel>("grid");
  /** Nível `grid`: precisão da célula geohash (5 ≈ 4,9 km · 6 ≈ 1,2 km · 7 ≈ 150 m). */
  const [precision, setPrecision] = useState(6);
  const [country, setCountry] = useState<string>(presets.country || "");
  const [region, setRegion] = useState<string>(presets.region || "");
  const [result, setResult] = useState<GleifMapResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(presets.region || presets.country || null);
  const [view, setView] = useState<GleifMapView>(level === "country" ? WORLD_VIEW : IBERIA_VIEW);

  // O filtro vindo da pesquisa («ver no mapa») sobrepõe-se ao escolhido aqui.
  useEffect(() => {
    if (presets.country) setCountry(presets.country);
    if (presets.region) setRegion(presets.region);
    if (presets.region) {
      setLevel("region");
      setFocusKey(presets.region);
      setView(IBERIA_VIEW);
    } else if (presets.country) {
      setFocusKey(presets.country);
    }
  }, [presets.country, presets.region]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getGleifMap({
        level,
        country: country || undefined,
        region: region || undefined,
        precision: level === "grid" ? precision : undefined,
        size: level === "grid" ? 1200 : 400,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agregado indisponível");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [country, level, precision, region]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Círculos do mapa: no nível `grid` o backend já dá as coordenadas. */
  const points = useMemo<GleifMapPoint[]>(() => {
    const rows = result?.regions || [];
    const max = Math.max(1, ...rows.map((row) => row.count));
    const out: GleifMapPoint[] = [];
    rows.forEach((row) => {
      if (typeof row.lat === "number" && typeof row.lon === "number") {
        out.push({
          key: row.key,
          label: row.label || row.city || row.key,
          count: row.count,
          active: row.active,
          lat: row.lat,
          lon: row.lon,
          exact: true,
          country: country || undefined,
          share: row.count / max,
        });
        return;
      }
      const place = resolveLeiPlace(row.key, level === "country" ? "country" : "region", level === "region" ? country || null : null);
      if (!place) return;
      out.push({
        key: row.key,
        label: row.label || place.label || row.key,
        count: row.count,
        active: row.active,
        cities: row.cities,
        lat: place.lat,
        lon: place.lon,
        exact: place.exact,
        country: level === "region" ? row.key.split("-")[0] : row.key,
        share: row.count / max,
      });
    });
    return out;
  }, [country, level, result]);

  /** Quando o filtro é insular, o enquadramento passa para o Atlântico. */
  const islandFocus = useMemo(
    () => points.some((point) => point.exact && /^(PT-20|PT-30|ES-CN|ES-GC|ES-TF|ES-PM|ES-CE|ES-ML)$/.test(point.key)) && points.length <= 3,
    [points],
  );

  const totalShown = points.reduce((sum, point) => sum + point.count, 0);
  const indexTotal = result?.index_total ?? status?.elasticsearch?.count ?? 0;
  /** Regiões agregadas que não têm centroide conhecido (caem no centroide do país). */
  const semCentroide = (result?.regions?.length || 0) - points.length;
  /** Registos sem região no endereço (vista por região) ou sem ponto geocodificado (vista por empresa). */
  const semRegiao = level === "country" ? 0 : result?.missing || 0;
  const matched = result?.matched ?? totalShown;

  /**
   * Abre a janela com as empresas de uma divisão.
   * No nível «empresas» o ponto é uma célula geográfica: abre pela cidade dominante.
   */
  const openWindowFor = (point: GleifMapPoint) => {
    if (!onOpenRegion) return;
    if (level === "grid") {
      const row = (result?.regions || []).find((item) => item.key === point.key);
      if (row?.city) onOpenRegion("city", row.city, row.label || row.city);
      return;
    }
    onOpenRegion(level, point.key, point.label);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-6 py-2 text-[11px]">
        <div className="flex items-center gap-1 rounded-2xl glass-card p-1">
          {(
            [
              ["grid", "Empresas", <Fingerprint key="f" size={12} />],
              ["region", "Regiões", <Layers key="l" size={12} />],
              ["country", "Países", <Globe2 key="g" size={12} />],
            ] as [GleifMapLevel, string, React.ReactNode][]
          ).map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setLevel(id);
                setFocusKey(null);
                if (id === "country") setView(WORLD_VIEW);
                else if (id === "region") setView(IBERIA_VIEW);
              }}
              aria-pressed={level === id}
              title={
                id === "grid"
                  ? "Empresas colocadas pela sede legal (endereço do registo)"
                  : id === "region"
                    ? "Agregado por região/distrito (só onde o GLEIF a indica)"
                    : "Agregado por país"
              }
              className={`flex items-center gap-1.5 rounded-xl px-2.5 py-1 transition ${
                level === id ? "bg-primary/15 text-primary" : "hover:bg-white/5"
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>

        {level === "grid" && (
          <label className="flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1">
            <span className="text-muted-foreground">detalhe</span>
            <select
              value={precision}
              onChange={(event) => setPrecision(Number(event.target.value))}
              className="bg-transparent outline-none"
              title="Tamanho da célula: 5 ≈ 4,9 km · 6 ≈ 1,2 km · 7 ≈ 150 m"
            >
              <option value={5} className="text-foreground">
                amplo (≈5 km)
              </option>
              <option value={6} className="text-foreground">
                médio (≈1 km)
              </option>
              <option value={7} className="text-foreground">
                fino (≈150 m)
              </option>
            </select>
          </label>
        )}

        <label className="flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1">
          <span className="text-muted-foreground">país</span>
          <select value={country} onChange={(event) => setCountry(event.target.value)} className="bg-transparent outline-none">
            <option value="">todos</option>
            {(status?.facets?.country || []).map((facet) => (
              <option key={facet.key} value={facet.key} className="text-foreground">
                {countryFlag(facet.key)} {countryName(facet.key)} ({formatNumber(facet.count)})
              </option>
            ))}
          </select>
        </label>

        {level === "region" && (status?.facets?.region || []).length > 0 && (
          <label className="flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1">
            <span className="text-muted-foreground">região</span>
            <select value={region} onChange={(event) => setRegion(event.target.value)} className="max-w-[200px] bg-transparent outline-none">
              <option value="">todas</option>
              {(status?.facets?.region || [])
                .filter((facet) => !country || facet.key.startsWith(country))
                .map((facet) => (
                  <option key={facet.key} value={facet.key} className="text-foreground">
                    {countryName(facet.key.split("-")[0])} · {facet.key} ({formatNumber(facet.count)})
                  </option>
                ))}
            </select>
          </label>
        )}

        {(presets.country || presets.region) && (
          <button
            type="button"
            onClick={onClearPresets}
            className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-primary transition hover:bg-primary/20"
          >
            filtro da pesquisa: {presets.region || presets.country} ✕
          </button>
        )}

        <span className="ml-auto flex flex-wrap items-center gap-2 text-muted-foreground">
          <span>
            <span className="text-foreground">{formatNumber(totalShown)}</span> LEI em{" "}
            <span className="text-foreground">{formatNumber(result?.regions?.length || 0)}</span>{" "}
            {level === "country" ? "países" : level === "region" ? "regiões" : "pontos (sede legal)"} · índice{" "}
            {formatNumber(indexTotal)}
          </span>
          {semRegiao > 0 && (
            <button
              type="button"
              onClick={() => {
                setLevel("country");
                setView(WORLD_VIEW);
              }}
              title={`${formatNumber(semRegiao)} registos ${result?.missing_label || "sem região"}. A vista por país cobre-os a todos.`}
              className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-amber-200 transition hover:bg-amber-400/20"
            >
              {formatNumber(semRegiao)} {result?.missing_label || "sem região"} · ver por país
            </button>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-2xl glass-card px-2.5 py-1 transition hover:bg-white/5"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            atualizar
          </button>
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/5 px-6 py-1.5 text-[11px] text-amber-200">
          <AlertTriangle size={13} />
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <GleifMap
          points={points}
          focusKey={focusKey}
          loading={loading}
          level={level}
          initialView={islandFocus ? ATLANTIC_ISLANDS_VIEW : view}
          resetViews={[
            { label: "Mundo", view: WORLD_VIEW },
            { label: "Ibéria", view: IBERIA_VIEW },
            { label: "Ilhas", view: ATLANTIC_ISLANDS_VIEW },
          ]}
          onSelect={(point) => {
            setFocusKey(point.key);
            // Clicar num nó mostra as empresas da divisão numa janela própria.
            openWindowFor(point);
          }}
          onOpen={onOpenRegion ? openWindowFor : undefined}
          onFocus={(point) => setFocusKey(point ? point.key : null)}
          onFilter={
            level === "grid"
              ? undefined
              : (kind, code) => {
                  // O menu de contexto filtra pelo próprio agregado (recarrega o mapa).
                  if (kind === "country") setCountry(code);
                  else {
                    setRegion(code);
                    setFocusKey(code);
                  }
                }
          }
          onLevelChange={(next) => {
            setLevel(next);
            setFocusKey(null);
            if (next === "country") setView(WORLD_VIEW);
            else if (next === "region") setView(IBERIA_VIEW);
          }}
          onRefresh={() => void load()}
          emptyHint="Sem registos LEI para os filtros escolhidos. Faça uma ingestão no separador «Ingestão»."
        />

        <aside className="flex w-full shrink-0 flex-col overflow-hidden border-white/10 lg:w-[360px] lg:border-l">
          <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2 text-[11px] text-muted-foreground">
            <Sparkles size={12} />
            {level === "country" ? "Países por LEI" : "Regiões por LEI"}
            {semCentroide > 0 && <span className="ml-auto text-amber-300/90">{semCentroide} sem centroide</span>}
          </div>
          {semRegiao > 0 && (
            <p className="border-b border-white/10 bg-amber-400/5 px-4 py-1.5 text-[10.5px] text-amber-200/90">
              {formatNumber(semRegiao)} registos ({Math.round((semRegiao / Math.max(1, matched)) * 100)}%) não trazem
              região no endereço — só aparecem na vista por país.
            </p>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            {points.length === 0 && !loading && (
              <p className="px-1 py-4 text-center text-[11px] text-muted-foreground">Sem dados para mostrar.</p>
            )}
            <ul className="flex flex-col gap-1">
              {[...points]
                .sort((a, b) => b.count - a.count)
                .map((point) => (
                  <li
                    key={point.key}
                    className={`flex items-center gap-1 rounded-xl border px-2.5 py-1.5 transition ${
                      focusKey === point.key
                        ? "border-primary/40 bg-primary/10"
                        : "border-white/10 bg-white/[0.02] hover:bg-white/5"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setFocusKey(point.key)}
                      title="Centrar o mapa nesta divisão"
                      className="min-w-0 flex-1 text-left"
                    >
                      <span className="flex items-center gap-2 text-[11.5px]">
                        <span>{level === "country" ? countryFlag(point.key) : "◍"}</span>
                        <span className="min-w-0 flex-1 truncate">
                          {level === "country" ? countryName(point.key) : point.label}
                        </span>
                        <span className="font-mono text-[10px] text-muted-foreground">{point.key}</span>
                        <span className="text-foreground">{formatNumber(point.count)}</span>
                      </span>
                      <span className="mt-1 flex items-center gap-2">
                        <span
                          className="h-1.5 rounded-full bg-primary/70"
                          style={{ width: `${Math.max(2, (point.share || 0) * 100).toFixed(1)}%` }}
                        />
                        {point.active !== undefined && point.active > 0 && (
                          <span className="text-[10px] text-emerald-300/90">{formatNumber(point.active)} ativos</span>
                        )}
                        {point.cities !== undefined && point.cities > 0 && (
                          <span className="text-[10px] text-muted-foreground">{formatNumber(point.cities)} cidades</span>
                        )}
                        {!point.exact && <span className="text-[10px] text-amber-300/90">aprox.</span>}
                      </span>
                    </button>
                    {onOpenRegion && (
                      <button
                        type="button"
                        onClick={() => openWindowFor(point)}
                        title={`Ver as empresas de ${point.label} numa janela`}
                        className="shrink-0 rounded-lg border border-white/10 bg-white/5 p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                      >
                        <ArrowRight size={12} />
                      </button>
                    )}
                  </li>
                ))}
            </ul>
          </div>
          {status?.timeline && status.timeline.length > 0 && (
            <div className="border-t border-white/10 px-4 py-2">
              <p className="mb-1 flex items-center gap-1 text-[10.5px] text-muted-foreground">
                <CalendarClock size={11} /> registos por ano de registo inicial
              </p>
              <div className="flex h-12 items-end gap-0.5">
                {status.timeline.slice(-24).map((row) => {
                  const max = Math.max(1, ...status.timeline!.map((entry) => entry.count));
                  return (
                    <span
                      key={row.year}
                      title={`${row.year}: ${formatNumber(row.count)}`}
                      className="flex-1 rounded-t bg-primary/50"
                      style={{ height: `${Math.max(4, (row.count / max) * 100)}%` }}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/* ========================================================== 3. Ingestão */

function IngestSection({
  meta,
  status,
  onChanged,
}: {
  meta: GleifMeta | null;
  status: GleifStatus | null;
  onChanged: () => void;
}) {
  const [source, setSource] = useState<GleifIngestRequest["source"]>("api");
  const [countries, setCountries] = useState((meta?.default_countries || ["PT"]).join(" "));
  const [path, setPath] = useState("");
  const [limit, setLimit] = useState("");
  const [replace, setReplace] = useState(true);
  const [download, setDownload] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<GleifJob[]>([]);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (meta?.default_countries?.length) setCountries(meta.default_countries.join(" "));
  }, [meta?.default_countries]);

  const refreshJobs = useCallback(() => {
    getGleifJobs()
      .then((result) => setJobs(result.jobs || []))
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  // Enquanto houver tarefas a correr, vai atualizando.
  useEffect(() => {
    const running = jobs.some((job) => job.status === "running");
    if (!running) {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    if (pollRef.current) return;
    pollRef.current = window.setInterval(() => {
      refreshJobs();
      onChanged();
    }, 2500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [jobs, onChanged, refreshJobs]);

  const run = async (override?: Partial<GleifIngestRequest>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const payload: GleifIngestRequest = {
        source: override?.source || source,
        countries: override?.countries ?? (countries.trim() ? countries.trim().toUpperCase().split(/[\s,;]+/) : undefined),
        path: override?.path ?? (path.trim() || undefined),
        limit: override?.limit ?? (limit.trim() ? Number(limit.trim()) : undefined),
        replace: override?.replace ?? replace,
        download: override?.download ?? download,
        wait: false,
      };
      const result = await startGleifIngest(payload);
      setMessage(
        result.job_id
          ? `Tarefa ${result.job_id} iniciada (${payload.source}). O progresso aparece abaixo.`
          : "Pedido aceite.",
      );
      refreshJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao iniciar a ingestão");
    } finally {
      setBusy(false);
    }
  };

  const removeIndex = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteGleifIndex();
      setMessage("Índice esvaziado. A golden copy local em ficheiro não foi alterada.");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao esvaziar o índice");
    } finally {
      setBusy(false);
    }
  };

  /** Acompanha uma tarefa até terminar (usado no botão «seguir»). */
  const follow = async (jobId: string) => {
    for (let attempt = 0; attempt < 400; attempt += 1) {
      const found = await getGleifJob(jobId);
      setJobs((previous) => [found, ...previous.filter((job) => job.id !== found.id)]);
      if (found.status !== "running") {
        onChanged();
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
  };

  const lastRun = status?.meta?.last_run as Record<string, unknown> | null | undefined;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="flex flex-col gap-3">
          <div className="rounded-2xl glass-card p-4">
            <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
              <Download size={15} /> Recolher e indexar registos LEI
            </h2>
            <p className="mb-3 text-[11px] text-muted-foreground">
              Os registos ficam na <span className="font-mono">golden copy local</span> (
              <span className="font-mono">{status?.file?.path || meta?.file}</span>) e no índice{" "}
              <span className="font-mono">{meta?.index}</span>.
            </p>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex flex-col gap-1 text-[11px]">
                <span className="text-muted-foreground">Origem dos dados</span>
                <select
                  value={source}
                  onChange={(event) => setSource(event.target.value as GleifIngestRequest["source"])}
                  className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs outline-none"
                >
                  {(meta?.sources || [
                    { id: "api", label: "API oficial do GLEIF" },
                    { id: "file", label: "Golden copy local" },
                    { id: "golden-copy", label: "Ficheiro Golden Copy" },
                    { id: "golden-copy-download", label: "Descarregar Golden Copy" },
                  ]).map((option) => (
                    <option key={option.id} value={option.id} className="text-foreground">
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-[11px]">
                <span className="text-muted-foreground">Países (ISO, separados por espaço)</span>
                <input
                  value={countries}
                  onChange={(event) => setCountries(event.target.value)}
                  placeholder="PT ES"
                  className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 font-mono text-xs outline-none"
                />
              </label>

              {(source === "golden-copy") && (
                <label className="flex flex-col gap-1 text-[11px] md:col-span-2">
                  <span className="text-muted-foreground">Ficheiro Golden Copy (ZIP/CSV/XML/JSON)</span>
                  <input
                    value={path}
                    onChange={(event) => setPath(event.target.value)}
                    placeholder="lei2-latest.zip (em data/gleif/golden-copy) ou caminho absoluto"
                    className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 font-mono text-xs outline-none"
                  />
                </label>
              )}

              <label className="flex flex-col gap-1 text-[11px]">
                <span className="text-muted-foreground">Limite de registos (opcional)</span>
                <input
                  value={limit}
                  onChange={(event) => setLimit(event.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="ex.: 500"
                  className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs outline-none"
                />
              </label>

              <div className="flex flex-col gap-1.5 text-[11px]">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={replace} onChange={(event) => setReplace(event.target.checked)} />
                  substituir os registos destes países
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={download} onChange={(event) => setDownload(event.target.checked)} />
                  forçar novo descarregamento do Golden Copy (~540 MB)
                </label>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void run()}
                className="flex items-center gap-1.5 rounded-2xl bg-primary/20 px-3 py-1.5 text-xs text-primary transition hover:bg-primary/30 disabled:opacity-50"
              >
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                Recolher e indexar
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void run({ source: "file" })}
                className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
              >
                <RefreshCw size={13} />
                Reindexar golden copy local
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void run({ source: "golden-copy-download", download: true })}
                className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
              >
                <Layers size={13} />
                Descarregar Golden Copy completo
              </button>
              <a
                href={gleifExportUrl(5000)}
                className="flex items-center gap-1.5 rounded-2xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
              >
                <FileSpreadsheet size={13} />
                Exportar CSV
              </a>
              <button
                type="button"
                disabled={busy}
                onClick={() => void removeIndex()}
                className="ml-auto flex items-center gap-1.5 rounded-2xl border border-rose-400/25 bg-rose-400/10 px-3 py-1.5 text-xs text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-50"
              >
                <Trash2 size={13} />
                Esvaziar índice
              </button>
            </div>

            {message && <p className="mt-2 text-[11px] text-emerald-300">{message}</p>}
            {error && <p className="mt-2 text-[11px] text-amber-200">{error}</p>}
            <p className="mt-2 text-[10.5px] text-muted-foreground">
              Nota: a API oficial do GLEIF não permite paginação além de 10 000 resultados por consulta. Para o universo
              completo de um país grande (ex.: Espanha, 193 mil LEI) use a origem «Descarregar Golden Copy», que lê o
              ficheiro LEI-CDF publicado pelo GLEIF.
            </p>
          </div>

          <div className="rounded-2xl glass-card p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Link2 size={15} /> Tarefas de ingestão
            </h2>
            {jobs.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">Ainda não há tarefas nesta sessão.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {jobs.map((job) => (
                  <li key={job.id} className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[10px] text-muted-foreground">{job.id}</span>
                      <ApiBadge tone={job.status === "done" ? "ok" : job.status === "error" ? "warn" : "info"}>
                        {job.status === "running" ? `${job.phase || "a correr"}…` : job.status === "done" ? "concluída" : "erro"}
                      </ApiBadge>
                      <span className="text-muted-foreground">
                        {sourceLabel(job.source)} · {job.countries?.length ? job.countries.join(", ") : "todos"}
                      </span>
                      {job.status === "running" && (
                        <button
                          type="button"
                          onClick={() => void follow(job.id)}
                          className="ml-auto rounded-full border border-white/10 px-2 py-0.5 transition hover:bg-white/10"
                        >
                          seguir
                        </button>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
                      {job.note && <span>{job.note}</span>}
                      {job.indexed !== undefined && (
                        <span>
                          indexados <span className="text-foreground">{formatNumber(job.indexed)}</span>
                        </span>
                      )}
                      {job.errors ? <span className="text-amber-300">erros {formatNumber(job.errors)}</span> : null}
                      {job.duration_s !== undefined && <span>{job.duration_s}s</span>}
                      {job.truncated && <span className="text-amber-300">truncada em 10 000 (use o Golden Copy)</span>}
                      {job.error && <span className="text-rose-300">{job.error}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <aside className="flex flex-col gap-3">
          <div className="rounded-2xl glass-card p-4 text-[11px]">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Database size={15} /> Volumetria
            </h2>
            <dl className="grid grid-cols-2 gap-y-1.5">
              <dt className="text-muted-foreground">Índice</dt>
              <dd className="text-right font-mono text-[10.5px]">{meta?.index}</dd>
              <dt className="text-muted-foreground">Registos no índice</dt>
              <dd className="text-right text-foreground">{formatNumber(status?.elasticsearch?.count)}</dd>
              <dt className="text-muted-foreground">Golden copy (linhas)</dt>
              <dd className="text-right text-foreground">{formatNumber(status?.file?.records)}</dd>
              <dt className="text-muted-foreground">Tamanho do ficheiro</dt>
              <dd className="text-right text-foreground">{formatBytes(status?.file?.bytes)}</dd>
              <dt className="text-muted-foreground">Ficheiro atualizado</dt>
              <dd className="text-right text-foreground">{shortDate(status?.file?.modified)}</dd>
            </dl>
            {status?.elasticsearch?.error && (
              <p className="mt-2 text-amber-200">{status.elasticsearch.error}</p>
            )}
            {lastRun && (
              <p className="mt-2 border-t border-white/10 pt-2 text-muted-foreground">
                Última recolha: <span className="text-foreground">{String(lastRun.source ?? "—")}</span> ·{" "}
                {formatNumber(Number(lastRun.indexed ?? 0))} indexados em {String(lastRun.duration_s ?? "—")}s
              </p>
            )}
          </div>

          {status?.facets && (
            <div className="rounded-2xl glass-card p-4 text-[11px]">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <Globe2 size={15} /> Distribuições
              </h2>
              {(["country", "region", "status", "category"] as const).map((key) => {
                const values = (status.facets?.[key] || []).slice(0, 8);
                if (values.length === 0) return null;
                const max = Math.max(1, ...values.map((facet) => facet.count));
                return (
                  <div key={key} className="mb-2">
                    <p className="mb-1 text-muted-foreground">{FACET_LABELS[key]}</p>
                    <ul className="flex flex-col gap-0.5">
                      {values.map((facet) => (
                        <li key={facet.key} className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate">
                            {key === "country" ? `${countryFlag(facet.key)} ${countryName(facet.key)}` : facet.key}
                          </span>
                          <span className="h-1 w-16 overflow-hidden rounded-full bg-white/10">
                            <span className="block h-full bg-primary/70" style={{ width: `${(facet.count / max) * 100}%` }} />
                          </span>
                          <span className="w-14 text-right text-muted-foreground">{formatNumber(facet.count)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}

          {status?.golden_copy_files && status.golden_copy_files.length > 0 && (
            <div className="rounded-2xl glass-card p-4 text-[11px]">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <FileSpreadsheet size={15} /> Ficheiros Golden Copy
              </h2>
              <ul className="flex flex-col gap-1">
                {status.golden_copy_files.map((file) => (
                  <li key={file.name} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-[10.5px]">{file.name}</span>
                    <span className="text-muted-foreground">{formatBytes(file.bytes)}</span>
                    <span className="text-muted-foreground">{shortDate(file.modified)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
