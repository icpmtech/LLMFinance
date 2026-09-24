/**
 * Pesquisa total — a pesquisa «estilo Google» do IQ OS.
 *
 * Uma caixa, tudo o que a plataforma sabe: **Recolha** (dados recolhidos de
 * sites), **Contratos** públicos, **Contratos ES** (contratação pública de
 * Espanha, PLACSP), **Entidades ES** (órgãos adjudicantes e empresas
 * adjudicatárias de Espanha), **Empresas**, **Marcas**, **Firmas**,
 * **Notícias**, **Mercado** e **CRM** (privado, só com sessão). Os resultados
 * chegam agrupados por área, com contagem por âmbito, sugestões enquanto se
 * escreve e abertura direta das fichas internas (empresa, contrato, contrato
 * espanhol, ticker).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CornerDownLeft,
  ExternalLink,
  FileSignature,
  Globe2,
  Handshake,
  Landmark,
  LineChart,
  Loader2,
  Newspaper,
  ScrollText,
  Search,
  Tag,
  Users,
  X,
} from "lucide-react";
import { CONTRATOS_ES_VIEW, openResult } from "../openResult";
import { ItemsCollection, ItemsViewToggle, type DisplayItem, type ItemsView } from "../components/ItemsView";
import {
  externalSearchUrl,
  searchScopes,
  searchSuggest,
  unifiedSearch,
  type SearchGroup,
  type SearchItem,
  type SearchScope,
  type SearchScopeId,
  type SearchSuggestion,
  type UnifiedSearchResult,
} from "../searchApi";

/* ------------------------------------------------------------------ apoio */

/** Âmbitos que uma sugestão pode abrir diretamente (o resto cai na recolha). */
const SUGGESTION_SCOPES: SearchScopeId[] = ["entities", "entities_es", "contracts_es", "market"];

function scopeForSuggestion(scope: SearchScopeId): SearchScopeId {
  return SUGGESTION_SCOPES.includes(scope) ? scope : "scraped";
}

const numberFormat = new Intl.NumberFormat("pt-PT");
const moneyFormat = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

const SCOPE_ICON: Record<string, React.ReactNode> = {
  scraped: <Globe2 size={14} />,
  social: <Users size={14} />,
  contracts: <FileSignature size={14} />,
  contracts_es: <ScrollText size={14} />,
  entities_es: <Handshake size={14} />,
  entities: <Building2 size={14} />,
  trademarks: <Tag size={14} />,
  firmas: <Landmark size={14} />,
  news: <Newspaper size={14} />,
  market: <LineChart size={14} />,
  crm: <Users size={14} />,
};

const EXAMPLES = ["EDP", "combustíveis", "Sonae", "AAPL", "Renfe"];

function openLabel(item: SearchItem): string | null {
  if (!item.open) return null;
  if (item.open.view === "company-detail") return "Abrir ficha da empresa";
  if (item.open.view === "contract-detail") return "Abrir ficha do contrato";
  if (item.open.view === CONTRATOS_ES_VIEW) {
    return item.open.mode ? "Ver contratos desta entidade" : "Abrir em Contratos Espanha";
  }
  if (item.open.view.startsWith("crm-")) return "Abrir no CRM";
  return "Abrir no IQ OS";
}

function Badge({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "accent" | "money" }) {
  const tones = {
    muted: "border-white/10 bg-white/5 text-muted-foreground",
    accent: "border-sky-400/25 bg-sky-400/10 text-sky-200",
    money: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
  } as const;
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>{children}</span>;
}

/* ----------------------------------------------------------------- página */

interface UnifiedSearchPageProps {
  initialQuery?: string;
  onOpenTicker?: (ticker: string) => void;
  /** Abre uma vista/ficha interna (janela própria ou navegação, conforme o modo). */
  onOpenView?: (view: string, title?: string) => void;
}

export default function UnifiedSearchPage({ initialQuery = "", onOpenTicker, onOpenView }: UnifiedSearchPageProps) {
  const [query, setQuery] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.trim());
  const [scope, setScope] = useState<SearchScopeId>("all");
  const [result, setResult] = useState<UnifiedSearchResult | null>(null);
  const [scopes, setScopes] = useState<SearchScope[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  /** Como se apresentam os itens: cartões, lista ou imagens. */
  const [view, setView] = useState<ItemsView>("cards");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    searchScopes()
      .then((payload) => setScopes(payload.items))
      .catch(() => setScopes([]));
  }, []);

  const run = useCallback(async (term: string, nextScope: SearchScopeId) => {
    const value = term.trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    setShowSuggestions(false);
    try {
      const payload = await unifiedSearch({ q: value, scope: nextScope, size: 8 });
      if (payload.error) {
        setError(payload.error);
        setResult(null);
      } else {
        setResult(payload);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!submitted) return;
    void run(submitted, scope);
  }, [submitted, scope, run]);

  // Sugestões (com atraso curto para não bater na API a cada tecla).
  useEffect(() => {
    const term = query.trim();
    if (term.length < 2 || !showSuggestions) {
      setSuggestions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      searchSuggest(term, 8)
        .then((payload) => setSuggestions(payload.items))
        .catch(() => setSuggestions([]));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, showSuggestions]);

  const submit = (term?: string, nextScope?: SearchScopeId) => {
    const value = (term ?? query).trim();
    if (!value) return;
    setQuery(value);
    if (nextScope) setScope(nextScope);
    setHighlight(-1);
    setShowSuggestions(false);
    if (value === submitted && (nextScope ?? scope) === scope) {
      void run(value, nextScope ?? scope);
      return;
    }
    setSubmitted(value);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((prev) => Math.min(prev + 1, suggestions.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((prev) => Math.max(prev - 1, -1));
      return;
    }
    if (event.key === "Escape") {
      setShowSuggestions(false);
      setHighlight(-1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const picked = highlight >= 0 ? suggestions[highlight] : null;
      if (picked) {
        setShowSuggestions(false);
        submit(picked.text, scopeForSuggestion(picked.scope));
        return;
      }
      submit();
    }
  };

  const openItem = (item: SearchItem) => {
    const target = item.open;
    if (!target) {
      if (item.url) window.open(item.url, "_blank", "noreferrer");
      return;
    }
    const title = item.title.slice(0, 60);
    // O ticker é uma vista da plataforma sem identificador no nome.
    if (target.view === "ticker-detail") {
      if (onOpenTicker) {
        onOpenTicker(target.arg);
        return;
      }
      openResult({ view: "ticker-detail", arg: "" }, `Ticker · ${target.arg}`, onOpenView);
      return;
    }
    openResult(target, title, onOpenView);
  };

  const visibleGroups = useMemo(() => {
    const groups = result?.groups ?? [];
    if (scope === "all") return groups.filter((group) => group.items.length || group.error);
    return groups;
  }, [result, scope]);

  const countFor = (scopeId: SearchScopeId): number => {
    if (!result) return 0;
    if (scopeId === "all") return result.total;
    return result.groups.find((group) => group.scope === scopeId)?.total ?? 0;
  };

  const scopeList: SearchScope[] = scopes.length
    ? scopes
    : [{ id: "all", label: "Tudo" }, ...(result?.scopes ?? [])];

  /* ------------------------------------------------------------- caixa */

  const searchBox = (compact: boolean) => (
    <div className="relative w-full">
      <div
        className={`flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 shadow-lg shadow-black/20 backdrop-blur focus-within:border-sky-400/40 focus-within:ring-2 focus-within:ring-sky-400/30 ${
          compact ? "h-11" : "h-14"
        }`}
      >
        <Search size={compact ? 16 : 20} className="shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setShowSuggestions(true);
            setHighlight(-1);
          }}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => window.setTimeout(() => setShowSuggestions(false), 150)}
          onKeyDown={onKeyDown}
          placeholder="Pesquisar em tudo: recolha, contratos (PT/ES), empresas, marcas, firmas, notícias e mercado…"
          aria-label="Pesquisar em todos os dados do IQ OS"
          className={`w-full bg-transparent outline-none placeholder:text-muted-foreground ${compact ? "text-sm" : "text-base"}`}
        />
        {query ? (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setSuggestions([]);
              inputRef.current?.focus();
            }}
            aria-label="Limpar pesquisa"
            className="rounded-full p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            <X size={compact ? 13 : 16} />
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => submit()}
          className="hidden shrink-0 rounded-full bg-gradient-to-r from-sky-400 to-indigo-600 px-4 py-1.5 text-xs font-medium text-white sm:inline-flex"
        >
          Pesquisar
        </button>
      </div>

      {showSuggestions && suggestions.length ? (
        <ul className="absolute left-0 right-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-2xl border border-white/10 bg-[#0b1220]/95 py-1 shadow-2xl backdrop-blur">
          {suggestions.map((entry, index) => (
            <li key={`${entry.scope}:${entry.text}`}>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => submit(entry.text, scopeForSuggestion(entry.scope))}
                className={`flex w-full items-center gap-3 px-4 py-2 text-left text-xs ${
                  highlight === index ? "bg-white/10" : "hover:bg-white/5"
                }`}
              >
                <span className="text-muted-foreground">{SCOPE_ICON[entry.scope] ?? <Search size={13} />}</span>
                <span className="min-w-0 flex-1 truncate">{entry.text}</span>
                {entry.hint ? <span className="shrink-0 text-[10px] text-muted-foreground">{entry.hint}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );

  /* -------------------------------------------------------------- hero */

  if (!submitted) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pb-32 pt-16 sm:pt-24">
        <span className="grid h-14 w-14 place-items-center rounded-3xl bg-gradient-to-br from-sky-300 via-indigo-500 to-fuchsia-600 text-white shadow-xl shadow-indigo-500/25">
          <Search size={26} />
        </span>
        <h1 className="mt-4 bg-gradient-to-r from-sky-200 via-indigo-200 to-fuchsia-200 bg-clip-text text-4xl font-semibold tracking-tight text-transparent sm:text-5xl">
          Pesquisa total
        </h1>
        <p className="mt-2 max-w-xl text-center text-sm text-muted-foreground">
          Uma caixa para tudo o que o IQ OS sabe: <strong className="font-medium text-foreground">recolha</strong> de sites,{" "}
          contratos públicos (Portugal e Espanha), entidades contratantes e empresas adjudicatárias de Espanha, empresas,
          marcas, firmas, notícias, mercado e CRM.
        </p>

        <div className="mt-7 w-full">{searchBox(false)}</div>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
          {scopeList.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setScope(entry.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] transition ${
                scope === entry.id
                  ? "border-sky-400/40 bg-sky-400/10 text-sky-100"
                  : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
              }`}
              title={entry.hint}
            >
              {SCOPE_ICON[entry.id] ?? <Search size={12} />}
              {entry.label}
            </button>
          ))}
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-[11px] text-muted-foreground">
          <span>Exemplos:</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 hover:bg-white/10 hover:text-foreground"
            >
              {example}
            </button>
          ))}
        </div>

        <p className="mt-8 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <CornerDownLeft size={12} /> Enter para pesquisar · ↓ para ver sugestões · o CRM só aparece com sessão iniciada
        </p>
      </div>
    );
  }

  /* ------------------------------------------------------------ resultados */

  const allEmpty = !loading && result && result.total === 0;

  return (
    <div className="mx-auto w-full max-w-[1300px] overflow-x-hidden px-4 pb-32 pt-4 sm:px-6">
      <div className="sticky top-0 z-40 -mx-4 flex flex-col gap-3 border-b border-white/5 bg-background/80 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex items-center gap-3">
          <span className="hidden h-9 w-9 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-sky-300 via-indigo-500 to-fuchsia-600 text-white sm:grid">
            <Search size={16} />
          </span>
          <div className="min-w-0 flex-1">{searchBox(true)}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {scopeList.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setScope(entry.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] transition ${
                scope === entry.id
                  ? "border-sky-400/40 bg-sky-400/10 text-sky-100"
                  : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
              }`}
              title={entry.hint}
            >
              {SCOPE_ICON[entry.id] ?? <Search size={12} />}
              {entry.label}
              <span className="tabular-nums opacity-70">{numberFormat.format(countFor(entry.id))}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        {loading ? (
          <>
            <Loader2 size={12} className="animate-spin" /> A pesquisar «{submitted}»…
          </>
        ) : result ? (
          <>
            {numberFormat.format(result.total)} resultados em {result.took_ms} ms para «{result.query}»
          </>
        ) : null}
        {result?.groups?.length ? (
          <div className="ml-auto">
            <ItemsViewToggle value={view} onChange={setView} />
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} className="mt-0.5" /> {error}
        </div>
      ) : null}

      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_290px]">
        <div className="min-w-0 space-y-5">
          {allEmpty ? (
            <div className="glass-card rounded-2xl px-6 py-12 text-center">
              <Search size={26} className="mx-auto text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">Sem resultados para «{result?.query}»</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Experimente outro termo, um NIF, um ticker — ou pesquise fora do IQ OS.
              </p>
              <a
                href={externalSearchUrl(result?.query ?? submitted)}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
              >
                <ExternalLink size={13} /> Pesquisar na web
              </a>
            </div>
          ) : null}

          {visibleGroups.map((group) => (
            <ScopeResults
              key={group.scope}
              group={group}
              view={view}
              showHeader={scope === "all"}
              onSeeAll={() => setScope(group.scope)}
              onOpenItem={openItem}
            />
          ))}
        </div>

        <aside className="space-y-3">
          <div className="glass-card rounded-2xl p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Âmbitos</h2>
            <ul className="mt-2 space-y-1">
              {scopeList.map((entry) => {
                const count = countFor(entry.id);
                return (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={() => setScope(entry.id)}
                      title={entry.hint}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-[11px] hover:bg-white/5 ${
                        scope === entry.id ? "bg-white/10 text-foreground" : "text-muted-foreground"
                      }`}
                    >
                      <span className="flex min-w-0 items-center gap-1.5">
                        {SCOPE_ICON[entry.id] ?? <Search size={12} />}
                        <span className="truncate">{entry.label}</span>
                      </span>
                      <span className="tabular-nums">{numberFormat.format(count)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {result?.facets?.sources?.length ? (
            <div className="glass-card rounded-2xl p-4">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes da recolha</h2>
              <div className="mt-2 flex flex-wrap gap-1">
                {result.facets.sources.slice(0, 12).map((facet) => (
                  <button
                    key={facet.key}
                    type="button"
                    onClick={() => submit(facet.key, "scraped")}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
                    title={`Pesquisar «${facet.key}» na recolha`}
                  >
                    {facet.key} · {facet.count}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {result?.facets?.tags?.length ? (
            <div className="glass-card rounded-2xl p-4">
              <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Tag size={12} /> Etiquetas
              </h2>
              <div className="mt-2 flex flex-wrap gap-1">
                {result.facets.tags.slice(0, 18).map((facet) => (
                  <button
                    key={facet.key}
                    type="button"
                    onClick={() => submit(facet.key, "scraped")}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
                  >
                    #{facet.key} · {facet.count}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <p className="px-1 text-[10px] leading-relaxed text-muted-foreground">
            A pesquisa cobre a recolha, os contratos públicos (Portugal e Espanha/PLACSP), as entidades de Espanha (quem
            contrata e quem ganha), o cadastro de entidades, INPI, RNPC, notícias e mercado. O CRM só é incluído quando há
            sessão, porque é privado por utilizador.
          </p>
        </aside>
      </div>
    </div>
  );
}

/* -------------------------------------------------------- grupo de resultados */

/**
 * Converte um resultado da pesquisa no item das vistas partilhadas: o que já
 * existia (título, subtítulo, ligação, etiquetas, valores de `extra`) passa a
 * poder ver-se em cartões, lista ou imagens — com a imagem e os valores à vista.
 */
function toDisplayItem(item: SearchItem, onOpenItem: (item: SearchItem) => void): DisplayItem {
  const label = openLabel(item);
  const rawMoney = item.extra?.preco ?? item.extra?.valor;
  const money = typeof rawMoney === "number" ? moneyFormat.format(rawMoney) : null;
  return {
    id: `${item.scope}:${item.id}`,
    title: item.title,
    subtitle: item.subtitle,
    summary: item.snippet,
    url: item.url,
    image: item.image ?? null,
    date: item.date,
    badges: item.badges,
    values: (item.extra ?? {}) as Record<string, unknown>,
    actions: (
      <>
        {money ? <Badge tone="money">{money}</Badge> : null}
        {label ? (
          <button
            type="button"
            onClick={() => onOpenItem(item)}
            className="inline-flex items-center gap-1 rounded-full border border-sky-400/25 bg-sky-400/10 px-2 py-0.5 text-[10px] text-sky-200 hover:bg-sky-400/20"
          >
            {label} <ArrowRight size={10} />
          </button>
        ) : item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
          >
            Abrir site <ExternalLink size={10} />
          </a>
        ) : null}
      </>
    ),
  };
}

function ScopeResults({
  group,
  view,
  showHeader,
  onSeeAll,
  onOpenItem,
}: {
  group: SearchGroup;
  view: ItemsView;
  showHeader: boolean;
  onSeeAll: () => void;
  onOpenItem: (item: SearchItem) => void;
}) {
  if (!group.items.length && !group.error) return null;

  return (
    <section>
      {showHeader ? (
        <div className="mb-2 flex items-center gap-2 px-1">
          <span className="text-muted-foreground">{SCOPE_ICON[group.scope] ?? <Search size={13} />}</span>
          <h2 className="text-sm font-semibold">{group.label}</h2>
          <span className="text-[11px] text-muted-foreground">{numberFormat.format(group.total)}</span>
          {group.total > group.items.length ? (
            <button
              type="button"
              onClick={onSeeAll}
              className="ml-auto inline-flex items-center gap-1 text-[11px] text-sky-300 hover:underline"
            >
              Ver todos <ArrowRight size={11} />
            </button>
          ) : null}
        </div>
      ) : null}

      {group.error ? (
        <p className="mb-2 flex items-center gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
          <AlertTriangle size={12} /> {group.label}: {group.error}
        </p>
      ) : null}

      <ItemsCollection
        items={group.items.map((item) => toDisplayItem(item, onOpenItem))}
        view={view}
      />
    </section>
  );
}
