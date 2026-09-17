/**
 * Finder da plataforma (estilo macOS).
 *
 * - Locais (Recentes, Favoritos, Entidades, Contratos, Documentos, Mercados,
 *   Índices) na primeira coluna.
 * - Quatro vistas: ícones, lista (com ordenação por colunas), colunas (Miller)
 *   e galeria.
 * - Quick Look (barra de espaço), inspetor «Obter informação», etiquetas,
 *   barra de caminho e barra de estado.
 * - Menu de contexto (abrir, quick look, informação, favoritos, exportar).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Building2,
  ChevronRight,
  Columns3,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  FileText,
  FolderSearch,
  GalleryVerticalEnd,
  GitCompare,
  Info,
  Landmark,
  LayoutGrid,
  List,
  Loader2,
  RefreshCw,
  Search,
  Star,
  StarOff,
  TrendingUp,
  X,
} from "lucide-react";
import {
  getCompanyContracts,
  getContractStatus,
  getEntityDetail,
  getEntityStats,
  listElasticTickers,
  listRagDocuments,
  searchContracts,
  searchEntities,
} from "../api";
import type { ContractItem, EntityDetail, EntityItem, RagDocument } from "../types";
import { useDock } from "../dock";
import { useWindowMode } from "../layout";
import { useFavorites, type Favorite } from "../favorites";
import { openWindow } from "../windows";
import { openCompareWindow, useCompare, MAX_COMPARE } from "../compare";
import {
  FINDER_LOCATIONS,
  KIND_LABEL,
  appHref,
  formatFinderDate,
  formatFinderSize,
  formatFinderValue,
  itemKey,
  pushFinderRecent,
  sortFinderItems,
  tagColor,
  useFinder,
  type FinderItem,
  type FinderKind,
  type FinderLocation,
  type FinderLocationId,
  type FinderSort,
  type FinderView,
} from "../finder";

/* ------------------------------------------------------------------ tipos */

type Trail = { location: FinderLocationId; key: string | null };

const VIEWS: { id: FinderView; label: string; icon: React.ElementType }[] = [
  { id: "icons", label: "Ícones", icon: LayoutGrid },
  { id: "columns", label: "Colunas", icon: Columns3 },
  { id: "list", label: "Lista", icon: List },
  { id: "gallery", label: "Galeria", icon: GalleryVerticalEnd },
];

const SORTS: { id: FinderSort; label: string }[] = [
  { id: "name", label: "Nome" },
  { id: "kind", label: "Tipo" },
  { id: "date", label: "Data" },
  { id: "size", label: "Tamanho" },
];

/** Índices do Elasticsearch criados pela plataforma. */
const KNOWN_INDICES: { id: string; label: string; hint: string }[] = [
  { id: "finance_contracts", label: "finance_contracts", hint: "Contratos públicos" },
  { id: "finance_entities", label: "finance_entities", hint: "Diretório de entidades" },
  { id: "finance_documents", label: "finance_documents", hint: "Documentos RAG" },
  { id: "finance_users", label: "finance_users", hint: "Contas de utilizador" },
  { id: "finance_sessions", label: "finance_sessions", hint: "Sessões ativas" },
  { id: "finance_user_state", label: "finance_user_state", hint: "Favoritos e estado do utilizador" },
];

/* --------------------------------------------------------------- helpers */

function nameOf(value: unknown): string {
  if (!value) return "";
  if (Array.isArray(value)) return value.map(nameOf).filter(Boolean).join(", ");
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.nome ?? record.name ?? record.designacao ?? record.nif ?? "");
  }
  return String(value);
}

function contractToItem(contract: ContractItem): FinderItem {
  const adjudicatarios = nameOf(contract.adjudicatarios);
  return {
    id: String(contract.idcontrato ?? contract.doc_id ?? contract.objectoContrato ?? ""),
    kind: "contract",
    name: contract.objectoContrato?.trim() || contract.descContrato?.trim() || `Contrato ${contract.idcontrato ?? ""}`,
    subtitle: [adjudicatarios, contract.Ano ? String(contract.Ano) : ""].filter(Boolean).join(" · "),
    date: contract.dataCelebracaoContrato ?? contract.dataPublicacao,
    value: contract.precoContratual ?? contract.PrecoTotalEfetivo,
    raw: contract,
  };
}

function entityToItem(entity: EntityItem, favoriteIds: Set<string>): FinderItem {
  const tags: string[] = [];
  if (entity.nif && favoriteIds.has(entity.nif)) tags.push("Favorito");
  return {
    id: entity.nif ?? entity.name,
    kind: "entity",
    name: entity.name,
    subtitle: [entity.nif ? `NIF ${entity.nif}` : "sem NIF", entity.country].filter(Boolean).join(" · "),
    date: entity.ingested_at,
    size: entity.contracts_count,
    value: entity.total_value,
    tags,
    raw: entity,
  };
}

function documentToItem(document: RagDocument): FinderItem {
  return {
    id: document.doc_id,
    kind: "document",
    name: document.title || document.filename,
    subtitle: document.filename,
    date: document.updated_at ? new Date(document.updated_at * 1000).toISOString() : undefined,
    size: document.pages,
    value: document.size_bytes,
    tags: document.indexed ? ["Indexado"] : [],
    raw: document,
  };
}

function favoriteToItem(favorite: Favorite): FinderItem {
  return {
    id: favorite.id,
    kind: favorite.kind === "entity" ? "entity" : "contract",
    name: favorite.label,
    subtitle: favorite.sublabel,
    date: favorite.addedAt,
    value: favorite.value ?? undefined,
    tags: ["Favorito"],
    raw: favorite,
  };
}

const KIND_ICON: Record<FinderKind, React.ElementType> = {
  entity: Building2,
  contract: FileText,
  document: Landmark,
  ticker: TrendingUp,
  index: Database,
};

const KIND_GRADIENT: Record<FinderKind, string> = {
  entity: "from-emerald-300 via-emerald-500 to-teal-600",
  contract: "from-amber-200 via-amber-400 to-orange-500",
  document: "from-sky-200 via-cyan-400 to-teal-500",
  ticker: "from-rose-200 via-rose-400 to-pink-600",
  index: "from-slate-300 via-slate-500 to-slate-700",
};

/* ----------------------------------------------------------------- página */

export default function FinderPage() {
  const { prefs, recents, setPrefs, clearRecents } = useFinder();
  const { favorites, toggle: toggleFavorite } = useFavorites();
  const { windowMode } = useWindowMode();
  const { prefs: dockPrefs } = useDock();
  const { add: addToCompare, clear: clearCompare } = useCompare();
  /** Seleção múltipla (Ctrl/⌘+clique) para comparar. */
  const [multi, setMulti] = useState<FinderItem[]>([]);
  /** Espaço reservado ao dock em modo página (as vistas rolam por dentro). */
  const dockReserve = dockPrefs.position === "bottom" && !dockPrefs.autoHide ? 112 : 0;

  const [location, setLocation] = useState<FinderLocationId>("entities");
  const [items, setItems] = useState<FinderItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<FinderItem | null>(null);
  const [related, setRelated] = useState<FinderItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [quickLook, setQuickLook] = useState<FinderItem | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; item: FinderItem } | null>(null);
  const [sortOpen, setSortOpen] = useState(false);
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [trail, setTrail] = useState<Trail[]>([{ location: "entities", key: null }]);
  const [trailIndex, setTrailIndex] = useState(0);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const favoriteIds = useMemo(
    () => new Set(favorites.filter((item) => item.kind === "entity").map((item) => item.id)),
    [favorites],
  );

  /* ------------------------------------------------------------- carregar */
  const load = useCallback(
    async (target: FinderLocationId, term: string, favoritesSnapshot: Favorite[]) => {
      setLoading(true);
      setError(null);
      try {
        const q = term.trim();
        let next: FinderItem[] = [];
        if (target === "recents") {
          next = recents;
        } else if (target === "favorites") {
          const source = favoritesSnapshot;
          next = source
            .filter((item) => !q || `${item.label} ${item.sublabel ?? ""}`.toLowerCase().includes(q.toLowerCase()))
            .map(favoriteToItem);
        } else if (target === "entities") {
          const response = await searchEntities({
            q: q || undefined,
            size: 80,
            sort_by: "contracts_count",
            sort_order: "desc",
          });
          next = response.items.map((entity) => entityToItem(entity, favoriteIds));
        } else if (target === "contracts") {
          const response = await searchContracts({ q: q || undefined, size: 80 });
          next = response.items.map(contractToItem);
        } else if (target === "documents") {
          const documents = await listRagDocuments();
          next = documents
            .filter((document) => !q || `${document.title} ${document.filename}`.toLowerCase().includes(q.toLowerCase()))
            .map(documentToItem);
        } else if (target === "tickers") {
          const response = await listElasticTickers();
          next = response.tickers
            .filter((ticker) => !q || ticker.toLowerCase().includes(q.toLowerCase()))
            .map((ticker) => ({ id: ticker, kind: "ticker" as const, name: ticker, subtitle: "Série de preços indexada" }));
        } else {
          const [contracts, entities, documents] = await Promise.all([
            getContractStatus().catch(() => null),
            getEntityStats().catch(() => null),
            listRagDocuments().catch(() => []),
          ]);
          const counts: Record<string, number | undefined> = {
            finance_contracts: contracts?.total,
            finance_entities: entities?.total,
            finance_documents: documents.length,
          };
          next = KNOWN_INDICES.filter((index) => !q || index.label.includes(q)).map((index) => ({
            id: index.id,
            kind: "index" as const,
            name: index.label,
            subtitle: index.hint,
            size: counts[index.id],
          }));
        }
        setItems(next);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Erro ao carregar.");
        setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [favoriteIds, recents],
  );

  useEffect(() => {
    void load(location, query, favorites);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location, query, favoriteIds, favorites.length]);

  /* ------------------------------------------------- itens ordenados/visíveis */
  const sorted = useMemo(
    () => (location === "recents" ? items : sortFinderItems(items, prefs.sort, prefs.ascending)),
    [items, location, prefs.sort, prefs.ascending],
  );

  const totals = useMemo(() => {
    const value = sorted.reduce((sum, item) => sum + (item.value ?? 0), 0);
    const count = sorted.reduce((sum, item) => sum + (item.size ?? 0), 0);
    return { value, count };
  }, [sorted]);

  /* -------------------------------------------------------- coluna de relacionados */
  useEffect(() => {
    let cancelled = false;
    if (!selected) {
      setRelated([]);
      return;
    }
    const run = async () => {
      setRelatedLoading(true);
      try {
        if (selected.kind === "entity" && selected.id) {
          const response = await getCompanyContracts(selected.id, "all", 0, 25);
          if (!cancelled) setRelated(response.items.map(contractToItem));
        } else if (selected.kind === "contract" && selected.raw) {
          const contract = selected.raw as ContractItem;
          const parties = [contract.adjudicantes, contract.adjudicatarios]
            .flatMap((entry) => (Array.isArray(entry) ? entry : entry ? [entry] : []))
            .map((party) => ({
              id: String((party as { nif?: string }).nif ?? nameOf(party)),
              kind: "entity" as const,
              name: nameOf(party) || "Entidade",
              subtitle: (party as { nif?: string }).nif ? `NIF ${(party as { nif?: string }).nif}` : undefined,
              raw: party,
            }));
          if (!cancelled) setRelated(parties);
        } else {
          if (!cancelled) setRelated([]);
        }
      } catch {
        if (!cancelled) setRelated([]);
      } finally {
        if (!cancelled) setRelatedLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  /* Detalhe (para o inspetor e o Quick Look) quando é uma entidade. */
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    if (selected?.kind === "entity" && selected.id) {
      void getEntityDetail(selected.id)
        .then((response) => {
          if (!cancelled) setDetail(response);
        })
        .catch(() => {
          if (!cancelled) setDetail(null);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [selected]);

  /* -------------------------------------------------------------- navegação */
  const navigate = useCallback(
    (target: FinderLocationId, key: string | null) => {
      setTrail((previous) => {
        const next = [...previous.slice(0, trailIndex + 1), { location: target, key }];
        setTrailIndex(next.length - 1);
        return next;
      });
      setLocation(target);
      setQuery("");
    },
    [trailIndex],
  );

  const goBack = useCallback(() => {
    if (trailIndex === 0) return;
    const index = trailIndex - 1;
    setTrailIndex(index);
    setLocation(trail[index].location);
  }, [trail, trailIndex]);

  const goForward = useCallback(() => {
    if (trailIndex >= trail.length - 1) return;
    const index = trailIndex + 1;
    setTrailIndex(index);
    setLocation(trail[index].location);
  }, [trail, trailIndex]);

  /** Guarda o item em «Recentes» (o store notifica as vistas). */
  const pushRecent = useCallback((item: FinderItem) => {
    pushFinderRecent(item);
  }, []);

  const open = useCallback(
    (item: FinderItem) => {
      setSelected(item);
      pushRecent(item);
      // Em modo janelas, o Quick Look é uma janela própria (em vez de modal).
      if (windowMode) {
        // As entidades trazem valores, analítica, contratos e concorrentes: janela maior.
        const rect = item.kind === "entity" ? { width: 780, height: 660 } : { width: 560, height: 520 };
        openWindow(`quicklook:${item.kind}:${item.id}`, undefined, { title: item.name, rect });
        return;
      }
      setQuickLook(item);
    },
    [pushRecent, windowMode],
  );

  /**
   * Clique simples seleciona; **Ctrl/⌘+clique** junta à seleção múltipla
   * (para comparar entidades/contratos).
   */
  const select = useCallback(
    (item: FinderItem, additive = false) => {
      if (additive) {
        setMulti((current) => {
          const exists = current.some((entry) => itemKey(entry) === itemKey(item));
          if (exists) return current.filter((entry) => itemKey(entry) !== itemKey(item));
          // Não misturar espécies: uma seleção nova começa do zero.
          const sameKind = current.filter((entry) => entry.kind === item.kind);
          return [...sameKind, item];
        });
      } else {
        setMulti([]);
      }
      setSelected(item);
    },
    [],
  );

  /* Mudar de local (ou pesquisar de novo) limpa a seleção múltipla. */
  useEffect(() => {
    setMulti([]);
  }, [location]);

  /** Compara a seleção múltipla (ou o item indicado) numa janela própria. */
  const compare = useCallback(
    (itemsToCompare: FinderItem[]) => {
      const comparable = itemsToCompare.filter((item) => item.kind === "entity" || item.kind === "contract");
      if (comparable.length === 0) return;
      // Só se comparam itens da mesma espécie (entidades entre si, contratos entre si).
      const kind = comparable[0].kind;
      const sameKind = comparable.filter((item) => item.kind === kind).slice(0, MAX_COMPARE);
      // Vários itens: a seleção indicada passa a ser a comparação. Um só item
      // (menu de contexto «Comparar com…»): acrescenta ao que já está em cima da mesa.
      if (sameKind.length >= 2) clearCompare();
      addToCompare(
        sameKind.map((item) => ({
          kind: kind === "entity" ? ("entity" as const) : ("contract" as const),
          id: item.id,
          name: item.name,
          subtitle: item.subtitle,
        })),
      );
      setMulti([]);
      openCompareWindow();
    },
    [addToCompare, clearCompare],
  );

  /* ------------------------------------------------------------- atalhos */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (event.key === "Escape") {
        setMenu(null);
        setSortOpen(false);
        setLocationsOpen(false);
        if (quickLook) setQuickLook(null);
        return;
      }
      if (typing) return;
      if (event.key === " " && selected) {
        event.preventDefault();
        setQuickLook((current) => (current ? null : selected));
        return;
      }
      if ((event.key === "i" || event.key === "I") && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        setPrefs({ info: !prefs.info });
        return;
      }
      if (event.key === "Backspace") {
        event.preventDefault();
        goBack();
        return;
      }
      if (event.key === "/" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (sorted.length === 0) return;
        const index = selected ? sorted.findIndex((item) => itemKey(item) === itemKey(selected)) : -1;
        const nextIndex = event.key === "ArrowDown"
          ? Math.min(sorted.length - 1, index + 1)
          : Math.max(0, index <= 0 ? 0 : index - 1);
        setSelected(sorted[nextIndex]);
        return;
      }
      if (event.key === "Enter" && selected) {
        event.preventDefault();
        setQuickLook(selected);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goBack, prefs.info, quickLook, selected, setPrefs, sorted]);

  /* ------------------------------------------------------------------ CSV */
  const exportCsv = useCallback(() => {
    const header = ["Nome", "Tipo", "Detalhe", "Data", "Tamanho", "Valor"];
    const rows = sorted.map((item) => [
      item.name,
      KIND_LABEL[item.kind],
      item.subtitle ?? "",
      formatFinderDate(item.date),
      formatFinderSize(item),
      formatFinderValue(item.value),
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(";"))
      .join("\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `finder-${location}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [location, sorted]);

  /* ------------------------------------------------------------------ UI */
  const activeLocation = FINDER_LOCATIONS.find((entry) => entry.id === location) ?? FINDER_LOCATIONS[0];

  return (
    <div
      className="finder-shell bg-background text-foreground"
      data-in-window={windowMode || undefined}
      style={{ "--finder-reserve": `${dockReserve}px` } as React.CSSProperties}
      onClick={() => {
        setMenu(null);
        setSortOpen(false);
        setLocationsOpen(false);
      }}
    >
      {/* Barra de ferramentas */}
      <header className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.02] px-3 py-2 backdrop-blur-xl">
        <div className="flex items-center gap-0.5">
          <ToolbarButton label="Retroceder" icon={ArrowLeft} disabled={trailIndex === 0} onClick={goBack} />
          <ToolbarButton
            label="Avançar"
            icon={ArrowRight}
            disabled={trailIndex >= trail.length - 1}
            onClick={goForward}
          />
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-[6px] bg-gradient-to-br ${activeLocation.gradient} text-white shadow-sm`}>
            <activeLocation.icon size={13} />
          </span>
          <span className="truncate text-[13px] font-semibold">{activeLocation.label}</span>
          <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">
            {loading ? "a carregar…" : `${sorted.length} ite${sorted.length === 1 ? "m" : "ns"}`}
          </span>
        </div>

        {/* Locais (a vista de colunas já os mostra na 1.ª coluna) */}
        <div className="relative">
          <ToolbarButton
            label="Locais"
            icon={FolderSearch}
            active={locationsOpen}
            onClick={() => setLocationsOpen((open) => !open)}
          />
          {locationsOpen && (
            <div
              role="menu"
              aria-label="Locais"
              className="absolute left-0 top-8 z-50 w-56 overflow-hidden rounded-xl border border-white/10 bg-[#14161b]/97 p-1.5 shadow-2xl backdrop-blur-xl"
              onClick={(event) => event.stopPropagation()}
            >
              {FINDER_LOCATIONS.map((entry) => (
                <button
                  key={entry.id}
                  role="menuitem"
                  onClick={() => {
                    navigate(entry.id, null);
                    setLocationsOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition hover:bg-white/8"
                >
                  <span className={`grid h-4 w-4 place-items-center rounded-[4px] bg-gradient-to-br ${entry.gradient} text-white`}>
                    <entry.icon size={10} />
                  </span>
                  <span className="truncate">{entry.label}</span>
                  {entry.id === location && <span className="ml-auto text-teal-300">✓</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          {/* Vistas */}
          <div className="flex items-center gap-0.5 rounded-[7px] border border-white/8 bg-white/[0.05] p-0.5">
            {VIEWS.map((view) => (
              <button
                key={view.id}
                type="button"
                onClick={() => setPrefs({ view: view.id })}
                aria-pressed={prefs.view === view.id}
                aria-label={view.label}
                title={view.label}
                className={[
                  "grid h-6 w-7 place-items-center rounded-[5px] transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                  prefs.view === view.id ? "bg-white/[0.16] text-foreground" : "text-muted-foreground hover:text-foreground",
                ].join(" ")}
              >
                <view.icon size={13} />
              </button>
            ))}
          </div>

          {/* Ordenação */}
          <div className="relative">
            <ToolbarButton
              label="Organizar por"
              icon={ArrowDownUp}
              active={sortOpen}
              onClick={() => setSortOpen((open) => !open)}
            />
            {sortOpen && (
              <div
                role="menu"
                aria-label="Organizar por"
                className="absolute right-0 top-8 z-50 w-52 overflow-hidden rounded-xl border border-white/10 bg-[#14161b]/97 p-1.5 shadow-2xl backdrop-blur-xl"
                onClick={(event) => event.stopPropagation()}
              >
                {SORTS.map((sort) => (
                  <button
                    key={sort.id}
                    role="menuitem"
                    onClick={() => {
                      setPrefs({ sort: sort.id, ascending: prefs.sort === sort.id ? !prefs.ascending : true });
                      setSortOpen(false);
                    }}
                    className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition hover:bg-white/8"
                  >
                    {sort.label}
                    {prefs.sort === sort.id && (
                      <ArrowUp size={12} className={prefs.ascending ? "" : "rotate-180"} />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <ToolbarButton
            label="Obter informação"
            icon={Info}
            active={prefs.info}
            onClick={() => setPrefs({ info: !prefs.info })}
          />
          {(multi.length >= 2 || (selected && (selected.kind === "entity" || selected.kind === "contract"))) && (
            <button
              type="button"
              onClick={() => compare(multi.length >= 2 ? multi : [selected as FinderItem])}
              title="Comparar numa janela própria"
              className="flex items-center gap-1.5 rounded-[6px] border border-indigo-400/30 bg-indigo-400/15 px-2 py-1 text-[11.5px] text-indigo-100 transition hover:bg-indigo-400/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300/60"
            >
              <GitCompare size={13} />
              {multi.length >= 2 ? `Comparar (${multi.length})` : "Comparar"}
            </button>
          )}
          {multi.length > 0 && (
            <button
              type="button"
              onClick={() => setMulti([])}
              title="Limpar seleção múltipla"
              className="rounded-[6px] border border-white/8 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
            >
              {multi.length} sel.
            </button>
          )}
          <ToolbarButton label="Exportar lista (CSV)" icon={Download} onClick={exportCsv} disabled={sorted.length === 0} />
          <ToolbarButton
            label="Atualizar"
            icon={RefreshCw}
            onClick={() => void load(location, query, favorites)}
          />

          {/* Pesquisa */}
          <div className="relative">
            <Search size={12} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground/80" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Pesquisar ( / )"
              aria-label="Pesquisar no Finder"
              className="h-7 w-32 rounded-[6px] border border-white/8 bg-white/[0.055] pl-6 pr-6 text-[12px] outline-none transition placeholder:text-muted-foreground/80 focus:w-44 focus:border-teal-300/40 focus:bg-white/[0.08] sm:w-40 sm:focus:w-56"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Limpar pesquisa"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition hover:text-foreground"
              >
                <X size={11} />
              </button>
            )}
          </div>
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-rose-400/20 bg-rose-400/10 px-4 py-1.5 text-[12px] text-rose-200">
          <AlertCircle size={13} /> {error}
        </div>
      )}

      {/* Conteúdo */}
      <div className="flex min-h-0 flex-1">
        <div ref={listRef} className="relative min-w-0 flex-1">
          {loading ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 size={15} className="animate-spin" /> A carregar…
            </div>
          ) : sorted.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
              <FolderSearch size={26} className="text-muted-foreground/60" />
              <p className="text-sm text-muted-foreground">Sem itens nesta localização.</p>
              <p className="text-[11px] text-muted-foreground/70">
                {query ? `Nada corresponde a «${query}».` : "Escolha outro local ou ajuste a pesquisa."}
              </p>
            </div>
          ) : prefs.view === "icons" ? (
            <IconsView
              items={sorted}
              selected={selected}
              multi={multi}
              onSelect={select}
              onOpen={open}
              onMenu={setMenu}
              onCompare={compare}
            />
          ) : prefs.view === "list" ? (
            <ListView
              items={sorted}
              selected={selected}
              multi={multi}
              sort={prefs.sort}
              ascending={prefs.ascending}
              onSelect={select}
              onOpen={open}
              onMenu={setMenu}
              onCompare={compare}
              onSort={(sort) => setPrefs({ sort, ascending: prefs.sort === sort ? !prefs.ascending : true })}
            />
          ) : prefs.view === "columns" ? (
            <ColumnsView
              locations={FINDER_LOCATIONS}
              location={location}
              items={sorted}
              recents={recents}
              selected={selected}
              related={related}
              relatedLoading={relatedLoading}
              onLocation={(id) => navigate(id, null)}
              onSelect={select}
              onOpen={open}
              onMenu={setMenu}
              onClearRecents={clearRecents}
            />
          ) : (
            <GalleryView items={sorted} selected={selected} onSelect={(item) => select(item)} onOpen={open} detail={detail} />
          )}
        </div>

        {/* Inspetor «Obter informação» */}
        {prefs.info && (
          <InspectorPanel
            item={selected}
            detail={detail}
            related={related}
            onClose={() => setPrefs({ info: false })}
            onToggleFavorite={toggleFavorite}
          />
        )}
      </div>

      {/* Barra de caminho + estado */}
      <footer className="flex shrink-0 items-center gap-2 border-t border-white/8 bg-white/[0.02] px-3 py-1 text-[11px] text-muted-foreground">
        <PathBar location={activeLocation} item={selected} onLocation={(id) => navigate(id, null)} />
        <span className="ml-auto tabular-nums">
          {sorted.length} ite{sorted.length === 1 ? "m" : "ns"}
          {totals.count > 0 ? ` · ${totals.count.toLocaleString("pt-PT")} registos` : ""}
          {totals.value > 0 ? ` · ${formatFinderValue(totals.value)}` : ""}
        </span>
      </footer>

      {/* Quick Look */}
      {quickLook && (
        <QuickLook
          item={quickLook}
          detail={detail}
          related={related}
          onClose={() => setQuickLook(null)}
          onToggleFavorite={toggleFavorite}
        />
      )}

      {/* Menu de contexto */}
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          item={menu.item}
          onClose={() => setMenu(null)}
          onOpen={open}
          onInfo={() => {
            setPrefs({ info: true });
            setSelected(menu.item);
            setMenu(null);
          }}
          onToggleFavorite={toggleFavorite}
          onCompare={compare}
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- peças UI */

function ToolbarButton({
  label,
  icon: Icon,
  onClick,
  disabled,
  active,
}: {
  label: string;
  icon: React.ElementType;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={[
        "grid h-7 w-7 place-items-center rounded-[6px] border border-white/8 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60 disabled:opacity-35",
        active ? "bg-white/[0.16] text-foreground" : "bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09] hover:text-foreground",
      ].join(" ")}
    >
      <Icon size={13} />
    </button>
  );
}

function Tags({ tags }: { tags?: string[] }) {
  if (!tags || tags.length === 0) return null;
  return (
    <span className="flex items-center gap-1" aria-hidden="true">
      {tags.map((tag) => (
        <span key={tag} className={`h-1.5 w-1.5 rounded-full ${tagColor(tag)}`} title={tag} />
      ))}
    </span>
  );
}

function ItemGlyph({ item, size = 34 }: { item: FinderItem; size?: number }) {
  const Icon = KIND_ICON[item.kind];
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-[8px] bg-gradient-to-br ${KIND_GRADIENT[item.kind]} text-white shadow-sm`}
      style={{ width: size, height: size }}
    >
      <Icon size={Math.round(size * 0.5)} />
    </span>
  );
}

function IconsView({
  items,
  selected,
  multi,
  onSelect,
  onOpen,
  onMenu,
  onCompare,
}: {
  items: FinderItem[];
  selected: FinderItem | null;
  multi: FinderItem[];
  onSelect: (item: FinderItem, additive?: boolean) => void;
  onOpen: (item: FinderItem) => void;
  onMenu: (menu: { x: number; y: number; item: FinderItem }) => void;
  onCompare: (items: FinderItem[]) => void;
}) {
  return (
    <div className="h-full overflow-auto p-3">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2">
        {items.map((item) => {
          const active = selected ? itemKey(selected) === itemKey(item) : false;
          const marked = multi.some((entry) => itemKey(entry) === itemKey(item));
          return (
            <button
              key={itemKey(item)}
              type="button"
              onClick={(event) => onSelect(item, event.ctrlKey || event.metaKey)}
              onDoubleClick={() => (multi.length >= 2 ? onCompare(multi) : onOpen(item))}
              onContextMenu={(event) => {
                event.preventDefault();
                onSelect(item);
                onMenu({ x: event.clientX, y: event.clientY, item });
              }}
              className={[
                "flex flex-col items-center gap-1.5 rounded-[8px] px-2 py-3 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                marked
                  ? "bg-indigo-400/15 ring-1 ring-indigo-300/50"
                  : active
                    ? "bg-teal-400/15 ring-1 ring-teal-300/40"
                    : "hover:bg-white/[0.06]",
              ].join(" ")}
            >
              <ItemGlyph item={item} size={40} />
              <span className="line-clamp-2 text-[11.5px] leading-tight">{item.name}</span>
              <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <Tags tags={item.tags} />
                {KIND_LABEL[item.kind]}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ListView({
  items,
  selected,
  multi,
  sort,
  ascending,
  onSelect,
  onOpen,
  onMenu,
  onCompare,
  onSort,
}: {
  items: FinderItem[];
  selected: FinderItem | null;
  multi: FinderItem[];
  sort: FinderSort;
  ascending: boolean;
  onSelect: (item: FinderItem, additive?: boolean) => void;
  onOpen: (item: FinderItem) => void;
  onMenu: (menu: { x: number; y: number; item: FinderItem }) => void;
  onCompare: (items: FinderItem[]) => void;
  onSort: (sort: FinderSort) => void;
}) {
  const columns: { id: FinderSort; label: string; className: string }[] = [
    { id: "name", label: "Nome", className: "flex-1 min-w-0" },
    { id: "kind", label: "Tipo", className: "w-24 shrink-0" },
    { id: "date", label: "Data", className: "w-28 shrink-0" },
    { id: "size", label: "Tamanho", className: "w-24 shrink-0 text-right" },
  ];
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-white/8 bg-white/[0.03] px-3 py-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">
        {columns.map((column) => (
          <button
            key={column.id}
            type="button"
            onClick={() => onSort(column.id)}
            className={`${column.className} flex items-center gap-1 text-left transition hover:text-foreground`}
          >
            {column.label}
            {sort === column.id && <ArrowUp size={10} className={ascending ? "" : "rotate-180"} />}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {items.map((item) => {
          const active = selected ? itemKey(selected) === itemKey(item) : false;
          const marked = multi.some((entry) => itemKey(entry) === itemKey(item));
          return (
            <button
              key={itemKey(item)}
              type="button"
              onClick={(event) => onSelect(item, event.ctrlKey || event.metaKey)}
              onDoubleClick={() => (multi.length >= 2 ? onCompare(multi) : onOpen(item))}
              onContextMenu={(event) => {
                event.preventDefault();
                onSelect(item);
                onMenu({ x: event.clientX, y: event.clientY, item });
              }}
              data-active={active}
              className={[
                "flex w-full items-center gap-2 px-3 py-1 text-left text-[12.5px] transition",
                marked ? "bg-indigo-400/15" : active ? "bg-teal-400/15" : "hover:bg-white/[0.05]",
              ].join(" ")}
            >
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <ItemGlyph item={item} size={18} />
                <span className="truncate">{item.name}</span>
                <Tags tags={item.tags} />
              </span>
              <span className="w-24 shrink-0 truncate text-[11px] text-muted-foreground">{KIND_LABEL[item.kind]}</span>
              <span className="w-28 shrink-0 text-[11px] text-muted-foreground">{formatFinderDate(item.date)}</span>
              <span className="w-24 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                {formatFinderSize(item)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ColumnsView({
  locations,
  location,
  items,
  recents,
  selected,
  related,
  relatedLoading,
  onLocation,
  onSelect,
  onOpen,
  onMenu,
  onClearRecents,
}: {
  locations: FinderLocation[];
  location: FinderLocationId;
  items: FinderItem[];
  recents: FinderItem[];
  selected: FinderItem | null;
  related: FinderItem[];
  relatedLoading: boolean;
  onLocation: (id: FinderLocationId) => void;
  onSelect: (item: FinderItem, additive?: boolean) => void;
  onOpen: (item: FinderItem) => void;
  onMenu: (menu: { x: number; y: number; item: FinderItem }) => void;
  onClearRecents: () => void;
}) {
  const columnClass = "h-full w-64 shrink-0 overflow-auto border-r border-white/8 lg:w-72";
  const row = (item: FinderItem) => {
    const active = selected ? itemKey(selected) === itemKey(item) : false;
    return (
      <button
        key={itemKey(item)}
        type="button"
        onClick={(event) => onSelect(item, event.ctrlKey || event.metaKey)}
        onDoubleClick={() => onOpen(item)}
        onContextMenu={(event) => {
          event.preventDefault();
          onSelect(item);
          onMenu({ x: event.clientX, y: event.clientY, item });
        }}
        className={[
          "flex w-full items-center gap-2 rounded-[6px] px-2 py-1 text-left text-[12.5px] transition",
          active ? "bg-teal-400/90 font-medium text-white" : "hover:bg-white/[0.06]",
        ].join(" ")}
      >
        <ItemGlyph item={item} size={16} />
        <span className="truncate">{item.name}</span>
        {item.tags?.length ? <span className="ml-auto"><Tags tags={item.tags} /></span> : null}
      </button>
    );
  };

  return (
    <div className="flex h-full min-h-0 overflow-x-auto">
      {/* Coluna 1 — locais */}
      <div className={columnClass}>
        <p className="px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-wide text-muted-foreground">Locais</p>
        <div className="space-y-0.5 px-1.5 pb-2">
          {locations.map((entry) => {
            const active = entry.id === location;
            return (
              <button
                key={entry.id}
                type="button"
                onClick={() => onLocation(entry.id)}
                className={[
                  "flex w-full items-center gap-2 rounded-[6px] px-2 py-1 text-left text-[12.5px] transition",
                  active ? "bg-white/[0.12] font-medium text-foreground" : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground",
                ].join(" ")}
              >
                <span className={`grid h-4 w-4 place-items-center rounded-[4px] bg-gradient-to-br ${entry.gradient} text-white`}>
                  <entry.icon size={10} />
                </span>
                <span className="truncate">{entry.label}</span>
                {entry.id === "recents" && recents.length > 0 && (
                  <span className="ml-auto text-[10px] text-muted-foreground">{recents.length}</span>
                )}
              </button>
            );
          })}
          {location === "recents" && recents.length > 0 && (
            <button
              type="button"
              onClick={onClearRecents}
              className="mt-1 w-full rounded-[6px] px-2 py-1 text-left text-[11px] text-rose-300 transition hover:bg-rose-400/10"
            >
              Limpar recentes
            </button>
          )}
        </div>
      </div>

      {/* Coluna 2 — itens */}
      <div className={columnClass}>
        <p className="px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-wide text-muted-foreground">
          {locations.find((entry) => entry.id === location)?.label}
        </p>
        <div className="space-y-0.5 px-1.5 pb-2">{items.map(row)}</div>
      </div>

      {/* Coluna 3 — relacionados */}
      <div className="h-full w-64 shrink-0 overflow-auto lg:w-72">
        <p className="px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-wide text-muted-foreground">
          {selected ? "Relacionados" : "Seleção"}
        </p>
        {relatedLoading ? (
          <p className="flex items-center gap-2 px-3 py-1 text-[11.5px] text-muted-foreground">
            <Loader2 size={12} className="animate-spin" /> A carregar…
          </p>
        ) : related.length > 0 ? (
          <div className="space-y-0.5 px-1.5 pb-2">{related.map(row)}</div>
        ) : (
          <p className="px-3 py-1 text-[11.5px] text-muted-foreground/80">
            {selected ? "Sem itens relacionados." : "Escolha um item para ver o que está ligado a ele."}
          </p>
        )}
      </div>
    </div>
  );
}

function GalleryView({
  items,
  selected,
  onSelect,
  onOpen,
  detail,
}: {
  items: FinderItem[];
  selected: FinderItem | null;
  onSelect: (item: FinderItem) => void;
  onOpen: (item: FinderItem) => void;
  detail: EntityDetail | null;
}) {
  const current = selected ?? items[0];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto p-5">
        {current ? (
          <div className="mx-auto max-w-3xl">
            <div className="flex items-start gap-4">
              <ItemGlyph item={current} size={64} />
              <div className="min-w-0">
                <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{KIND_LABEL[current.kind]}</p>
                <h2 className="truncate text-lg font-semibold">{current.name}</h2>
                {current.subtitle && <p className="text-[12.5px] text-muted-foreground">{current.subtitle}</p>}
                <Tags tags={current.tags} />
              </div>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <GalleryStat label="Data" value={formatFinderDate(current.date)} />
              <GalleryStat label="Tamanho" value={formatFinderSize(current)} />
              <GalleryStat label="Valor" value={formatFinderValue(current.value)} />
              <GalleryStat
                label={current.kind === "entity" ? "Marcas" : "Tipo"}
                value={current.kind === "entity" ? String(detail?.trademarks_total ?? "—") : KIND_LABEL[current.kind]}
              />
            </dl>
            <button
              type="button"
              onClick={() => onOpen(current)}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
            >
              <Eye size={13} /> Quick Look
            </button>
          </div>
        ) : null}
      </div>
      <div className="dock-scroll flex shrink-0 items-center gap-1.5 overflow-x-auto border-t border-white/8 bg-white/[0.02] p-2">
        {items.map((item) => {
          const active = current ? itemKey(current) === itemKey(item) : false;
          return (
            <button
              key={itemKey(item)}
              type="button"
              onClick={() => onSelect(item)}
              onDoubleClick={() => onOpen(item)}
              title={item.name}
              className={[
                "shrink-0 rounded-[6px] p-1 transition",
                active ? "bg-teal-400/20 ring-1 ring-teal-300/40" : "hover:bg-white/[0.06]",
              ].join(" ")}
            >
              <ItemGlyph item={item} size={22} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function GalleryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="truncate text-[13px] font-medium">{value}</dd>
    </div>
  );
}

function PathBar({
  location,
  item,
  onLocation,
}: {
  location: FinderLocation;
  item: FinderItem | null;
  onLocation: (id: FinderLocationId) => void;
}) {
  return (
    <div className="flex min-w-0 items-center gap-1">
      <button
        type="button"
        onClick={() => onLocation(location.id)}
        className="flex items-center gap-1 rounded-[4px] px-1 transition hover:bg-white/[0.08] hover:text-foreground"
      >
        <span className={`grid h-3.5 w-3.5 place-items-center rounded-[3px] bg-gradient-to-br ${location.gradient} text-white`}>
          <location.icon size={9} />
        </span>
        {location.label}
      </button>
      {item && (
        <>
          <ChevronRight size={11} className="shrink-0 opacity-60" />
          <span className="truncate text-foreground/90">{item.name}</span>
        </>
      )}
    </div>
  );
}

function QuickLook({
  item,
  detail,
  related,
  onClose,
  onToggleFavorite,
}: {
  item: FinderItem;
  detail: EntityDetail | null;
  related: FinderItem[];
  onClose: () => void;
  onToggleFavorite: (entry: Omit<Favorite, "addedAt">) => void;
}) {
  const isFavorite = item.tags?.includes("Favorito") ?? false;
  const rows: [string, string][] = [
    ["Tipo", KIND_LABEL[item.kind]],
    ["Identificador", item.id],
    ["Detalhe", item.subtitle ?? "—"],
    ["Data", formatFinderDate(item.date)],
    ["Tamanho", formatFinderSize(item)],
    ["Valor", formatFinderValue(item.value)],
  ];
  if (item.kind === "entity" && detail) {
    rows.push(["Contratos (adjudicante)", String(detail.as_adjudicante_count ?? 0)]);
    rows.push(["Contratos (adjudicatário)", String(detail.as_adjudicatario_count ?? 0)]);
    rows.push(["Marcas INPI", String(detail.trademarks_total ?? 0)]);
    rows.push(["Firmas RNPC", String(detail.firmas_total ?? 0)]);
  }
  if (item.kind === "document" && item.raw) {
    const document = item.raw as RagDocument;
    rows.push(["Ficheiro", document.filename]);
    rows.push(["Indexado", document.indexed ? "Sim" : "Não"]);
  }

  return (
    <div
      className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-[#03080b]/55 p-4 pt-10 backdrop-blur-sm sm:p-8 sm:pt-16"
      role="dialog"
      aria-modal="true"
      aria-label={`Quick Look: ${item.name}`}
      onClick={onClose}
    >
      <div
        className="glass-modal w-full max-w-2xl rounded-2xl border border-white/12 p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-4">
          <ItemGlyph item={item} size={56} />
          <div className="min-w-0 flex-1">
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{KIND_LABEL[item.kind]}</p>
            <h2 className="text-lg font-semibold leading-tight">{item.name}</h2>
            {item.subtitle && <p className="text-[12.5px] text-muted-foreground">{item.subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar Quick Look"
            className="rounded-lg border border-white/10 bg-white/[0.06] p-1.5 text-muted-foreground transition hover:text-foreground"
          >
            <X size={15} />
          </button>
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3 border-b border-white/6 py-1">
              <dt className="text-[11px] text-muted-foreground">{label}</dt>
              <dd className="min-w-0 truncate text-[12.5px] font-medium">{value}</dd>
            </div>
          ))}
        </dl>

        {related.length > 0 && (
          <div className="mt-4">
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Relacionados</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {related.slice(0, 8).map((entry) => (
                <span
                  key={itemKey(entry)}
                  className="flex max-w-[240px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
                >
                  <ItemGlyph item={entry} size={14} />
                  <span className="truncate">{entry.name}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          {(item.kind === "entity" || item.kind === "contract") && (
            <button
              type="button"
              onClick={() =>
                onToggleFavorite({
                  kind: item.kind === "entity" ? "entity" : "contract",
                  id: item.id,
                  label: item.name,
                  sublabel: item.subtitle,
                  value: item.value ?? null,
                })
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
            >
              {isFavorite ? <StarOff size={13} /> : <Star size={13} />}
              {isFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
            </button>
          )}
          <a
            href={appHref(item)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
          >
            <ExternalLink size={13} /> Abrir na aplicação
          </a>
          <span className="ml-auto text-[10.5px] text-muted-foreground">Espaço fecha · Esc fecha</span>
        </div>
      </div>
    </div>
  );
}

function InspectorPanel({
  item,
  detail,
  related,
  onClose,
  onToggleFavorite,
}: {
  item: FinderItem | null;
  detail: EntityDetail | null;
  related: FinderItem[];
  onClose: () => void;
  onToggleFavorite: (entry: Omit<Favorite, "addedAt">) => void;
}) {
  const isFavorite = item?.tags?.includes("Favorito") ?? false;
  return (
    <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-l border-white/8 bg-white/[0.02] p-3 md:flex lg:w-80">
      <div className="mb-2 flex items-center gap-2">
        <Info size={13} className="text-teal-300" />
        <p className="text-[12.5px] font-semibold">Obter informação</p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar informação"
          className="ml-auto rounded p-1 text-muted-foreground transition hover:text-foreground"
        >
          <X size={13} />
        </button>
      </div>

      {!item ? (
        <p className="text-[11.5px] text-muted-foreground">Selecione um item para ver os metadados.</p>
      ) : (
        <>
          <div className="flex items-center gap-3">
            <ItemGlyph item={item} size={44} />
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium">{item.name}</p>
              <p className="truncate text-[11px] text-muted-foreground">{KIND_LABEL[item.kind]}</p>
            </div>
          </div>

          <dl className="mt-3 space-y-1">
            <InfoRow label="Identificador" value={item.id} />
            {item.subtitle && <InfoRow label="Detalhe" value={item.subtitle} />}
            <InfoRow label="Data" value={formatFinderDate(item.date)} />
            <InfoRow label="Tamanho" value={formatFinderSize(item)} />
            <InfoRow label="Valor" value={formatFinderValue(item.value)} />
            {item.kind === "entity" && detail && (
              <>
                <InfoRow label="Contratos" value={String(detail.contracts_count ?? 0)} />
                <InfoRow label="Como adjudicante" value={String(detail.as_adjudicante_count ?? 0)} />
                <InfoRow label="Como adjudicatário" value={String(detail.as_adjudicatario_count ?? 0)} />
                <InfoRow label="Marcas INPI" value={String(detail.trademarks_total ?? 0)} />
                <InfoRow label="Firmas RNPC" value={String(detail.firmas_total ?? 0)} />
                <InfoRow label="País" value={detail.country || "—"} />
              </>
            )}
          </dl>

          {(item.kind === "entity" || item.kind === "contract") && (
            <button
              type="button"
              onClick={() =>
                onToggleFavorite({
                  kind: item.kind === "entity" ? "entity" : "contract",
                  id: item.id,
                  label: item.name,
                  sublabel: item.subtitle,
                  value: item.value ?? null,
                })
              }
              className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
            >
              {isFavorite ? <StarOff size={13} /> : <Star size={13} />}
              {isFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
            </button>
          )}

          {related.length > 0 && (
            <div className="mt-4">
              <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                Relacionados ({related.length})
              </p>
              <ul className="mt-1 space-y-1">
                {related.slice(0, 12).map((entry) => (
                  <li key={itemKey(entry)} className="flex items-center gap-2 text-[11.5px]">
                    <ItemGlyph item={entry} size={14} />
                    <span className="truncate">{entry.name}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </aside>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-[11px] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right text-[11.5px] font-medium">{value}</dd>
    </div>
  );
}

function ContextMenu({
  x,
  y,
  item,
  onClose,
  onOpen,
  onInfo,
  onToggleFavorite,
  onCompare,
}: {
  x: number;
  y: number;
  item: FinderItem;
  onClose: () => void;
  onOpen: (item: FinderItem) => void;
  onInfo: () => void;
  onToggleFavorite: (entry: Omit<Favorite, "addedAt">) => void;
  onCompare: (items: FinderItem[]) => void;
}) {
  const isFavorite = item.tags?.includes("Favorito") ?? false;
  const style = {
    left: Math.min(x, (typeof window === "undefined" ? x : window.innerWidth) - 220),
    top: Math.min(y, (typeof window === "undefined" ? y : window.innerHeight) - 260),
  };
  const actions: { label: string; icon: React.ElementType; run: () => void; danger?: boolean }[] = [
    { label: "Quick Look", icon: Eye, run: () => onOpen(item) },
    { label: "Obter informação", icon: Info, run: onInfo },
  ];
  if (item.kind === "entity" || item.kind === "contract") {
    actions.push({
      label: isFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos",
      icon: isFavorite ? StarOff : Star,
      run: () =>
        onToggleFavorite({
          kind: item.kind === "entity" ? "entity" : "contract",
          id: item.id,
          label: item.name,
          sublabel: item.subtitle,
          value: item.value ?? null,
        }),
    });
    actions.push({
      label: "Comparar com…",
      icon: GitCompare,
      run: () => onCompare([item]),
    });
  }
  actions.push({
    label: "Copiar identificador",
    icon: Copy,
    run: () => void navigator.clipboard?.writeText(item.id),
  });

  return (
    <div
      role="menu"
      aria-label={`Ações para ${item.name}`}
      className="fixed z-[130] w-56 overflow-hidden rounded-xl border border-white/10 bg-[#14161b]/97 p-1.5 shadow-2xl backdrop-blur-xl"
      style={style}
      onClick={(event) => event.stopPropagation()}
    >
      <p className="truncate px-2.5 py-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">{item.name}</p>
      {actions.map((action) => (
        <button
          key={action.label}
          role="menuitem"
          onClick={() => {
            action.run();
            onClose();
          }}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition hover:bg-white/8"
        >
          <action.icon size={13} /> {action.label}
        </button>
      ))}
      <div className="my-1 h-px bg-white/8" />
      <a
        role="menuitem"
        href={appHref(item)}
        target="_blank"
        rel="noreferrer"
        onClick={onClose}
        className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition hover:bg-white/8"
      >
        <ExternalLink size={13} /> Abrir na aplicação
      </a>
    </div>
  );
}
