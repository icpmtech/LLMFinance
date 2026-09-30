/**
 * Empresas Global — todas as entidades e empresas do IQ OS numa só lista.
 *
 * Agrega as fontes que a plataforma já tem: **cadastro** português (portal base),
 * **firmas** (RNPC), **marcas** (INPI), **entidades** (órgãos adjudicantes) e
 * **empresas** (adjudicatárias) de Espanha/PLACSP e as **contas do CRM** (estas
 * só com sessão). Cada cartão mostra a origem, o NIF/NIPC ou DIR3, o número de
 * contratos e o valor associado, e abre a ficha da aplicação correspondente.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Briefcase,
  Building2,
  ExternalLink,
  Handshake,
  Landmark,
  Loader2,
  RefreshCw,
  Search,
  Tag,
  Users,
  X,
} from "lucide-react";
import {
  getCompaniesGlobalSources,
  searchCompaniesGlobal,
  type CompaniesGlobalResult,
  type CompaniesGlobalRow,
  type CompaniesGlobalSource,
  type CompaniesGlobalSourceId,
} from "../companiesGlobalApi";
import { openResult } from "../openResult";

/* ------------------------------------------------------------------ apoio */

const numberFormat = new Intl.NumberFormat("pt-PT");
const moneyFormat = new Intl.NumberFormat("pt-PT", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const SOURCE_ICON: Record<string, React.ReactNode> = {
  entity: <Building2 size={14} />,
  firma: <Tag size={14} />,
  trademark: <BadgeCheck size={14} />,
  organo_es: <Landmark size={14} />,
  adjudicataria_es: <Handshake size={14} />,
  crm: <Briefcase size={14} />,
  iberinform: <Search size={14} />,
};

const SOURCE_TONE: Record<string, string> = {
  entity: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
  firma: "border-cyan-400/25 bg-cyan-400/10 text-cyan-200",
  trademark: "border-pink-400/25 bg-pink-400/10 text-pink-200",
  organo_es: "border-amber-400/25 bg-amber-400/10 text-amber-200",
  adjudicataria_es: "border-orange-400/25 bg-orange-400/10 text-orange-200",
  crm: "border-indigo-400/25 bg-indigo-400/10 text-indigo-200",
  iberinform: "border-rose-400/25 bg-rose-400/10 text-rose-200",
};

const SORTS = [
  { id: "name", label: "Nome" },
  { id: "contracts", label: "Contratos" },
  { id: "value", label: "Valor" },
] as const;

type SortId = (typeof SORTS)[number]["id"];

function money(value?: number | null): string | null {
  return typeof value === "number" && value > 0 ? moneyFormat.format(value) : null;
}

function compact(value?: number | null): string {
  if (typeof value !== "number") return "—";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} G€`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (value >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return moneyFormat.format(value);
}

function sourceLabel(card: { label: string } | undefined, fallback: string): string {
  return card?.label ?? fallback;
}

/* ----------------------------------------------------------------- página */

interface CompaniesGlobalPageProps {
  initialQuery?: string;
  /** Abre uma ficha/vista interna (janela própria ou navegação, conforme o modo). */
  onOpenView?: (view: string, title?: string) => void;
}

export default function CompaniesGlobalPage({ initialQuery = "", onOpenView }: CompaniesGlobalPageProps) {
  const [query, setQuery] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.trim());
  const [source, setSource] = useState<CompaniesGlobalSourceId>("all");
  const [sort, setSort] = useState<SortId>("contracts");
  const [catalog, setCatalog] = useState<CompaniesGlobalSource[]>([]);
  const [result, setResult] = useState<CompaniesGlobalResult | null>(null);
  const [rows, setRows] = useState<CompaniesGlobalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Segundos desde o início da pesquisa (a vista «Todas» chega a demorar). */
  const [segundosDecorridos, setSegundosDecorridos] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!loading) {
      setSegundosDecorridos(0);
      return;
    }
    const inicio = Date.now();
    const id = setInterval(() => setSegundosDecorridos(Math.round((Date.now() - inicio) / 1000)), 1000);
    return () => clearInterval(id);
  }, [loading]);

  useEffect(() => {
    getCompaniesGlobalSources()
      .then((payload) => setCatalog(payload.items ?? []))
      .catch(() => setCatalog([]));
  }, []);

  const run = useCallback(async (term: string, nextSource: CompaniesGlobalSourceId) => {
    setLoading(true);
    setError(null);
    // Duas fases: as fontes de diretório (PT) respondem num instante e as
    // empresas aparecem logo; as agregações do PLACSP chegam depois e
    // substituem a lista pela versão completa.
    try {
      const rapida = await searchCompaniesGlobal({ q: term, source: nextSource, size: 24, fast: true });
      if (rapida.error) {
        setError(rapida.error);
      } else {
        setResult(rapida);
        setRows(rapida.items ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa.");
    }
    try {
      const payload = await searchCompaniesGlobal({ q: term, source: nextSource, size: 24 });
      if (payload.error) {
        setError(payload.error);
        setResult(null);
        setRows([]);
        return;
      }
      setResult(payload);
      setRows(payload.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa.");
      setResult(null);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run(submitted, source);
  }, [submitted, source, run]);

  const loadMore = async () => {
    if (!result || source === "all") return;
    setLoadingMore(true);
    try {
      const payload = await searchCompaniesGlobal({ q: submitted, source, size: 24, offset: rows.length });
      setRows((current) => [...current, ...(payload.items ?? [])]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha a carregar mais.");
    } finally {
      setLoadingMore(false);
    }
  };

  const submit = (term?: string) => {
    const value = (term ?? query).trim();
    setQuery(value);
    if (value === submitted) void run(value, source);
    else setSubmitted(value);
  };

  const sorted = useMemo(() => {
    const copy = [...rows];
    if (sort === "name") copy.sort((a, b) => a.name.localeCompare(b.name, "pt"));
    if (sort === "contracts") copy.sort((a, b) => (b.contracts_count ?? 0) - (a.contracts_count ?? 0));
    if (sort === "value") copy.sort((a, b) => (b.total_value ?? 0) - (a.total_value ?? 0));
    return copy;
  }, [rows, sort]);

  const cards = result?.sources ?? [];
  const cardFor = (id: string) => cards.find((card) => card.id === id);

  const sourcesWithAll = useMemo(
    () => [
      { id: "all" as CompaniesGlobalSourceId, label: "Todas", hint: "Todas as fontes com resultados", country: "", available: null },
      ...catalog,
    ],
    [catalog],
  );

  const hasMore = Boolean(result) && source !== "all" && rows.length < (result?.total ?? 0);

  const sourceChip = (entry: { id: CompaniesGlobalSourceId; label: string; hint?: string; available?: number | null; available_label?: string | null; blocked?: boolean }) => {
    const active = source === entry.id;
    return (
      <button
        key={entry.id}
        type="button"
        onClick={() => setSource(entry.id)}
        title={entry.hint}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] transition ${
          active
            ? "border-sky-400/40 bg-sky-400/10 text-sky-100"
            : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
        }`}
      >
        {SOURCE_ICON[entry.id] ?? <Users size={12} />}
        {entry.label}
        {entry.id !== "all" ? (
          <span className="tabular-nums opacity-70">
            {entry.available === null || entry.available === undefined ? "—" : numberFormat.format(entry.available)}
          </span>
        ) : (
          <span className="tabular-nums opacity-70">{numberFormat.format(result?.total ?? 0)}</span>
        )}
      </button>
    );
  };

  return (
    <div className="mx-auto w-full max-w-[1300px] overflow-x-hidden px-4 pb-32 pt-4 sm:px-6 fade-in">
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[10.5px] text-muted-foreground">
            <Users size={11} /> Entidades e empresas de todo o sistema
          </span>
          <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Briefcase size={22} className="text-emerald-300" />
            Empresas Global
          </h1>
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
            Cadastro português, firmas (RNPC), marcas (INPI), empresas recolhidas
            do Iberinform, entidades contratantes e empresas adjudicatárias de
            Espanha (PLACSP) e contas do CRM — com contratos e valores somados
            por entidade.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-muted-foreground" htmlFor="empresas-global-sort">
            Ordenar
          </label>
          <select
            id="empresas-global-sort"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortId)}
            className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] outline-none"
          >
            {SORTS.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void run(submitted, source)}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] hover:bg-white/10"
          >
            <RefreshCw size={12} /> Atualizar
          </button>
        </div>
      </header>

      <form
        className="relative"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="flex h-12 items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 shadow-lg shadow-black/20 backdrop-blur focus-within:border-emerald-400/40 focus-within:ring-2 focus-within:ring-emerald-400/25">
          <Search size={17} className="shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Nome, NIF/NIPC, marca, órgão ou conta…"
            aria-label="Pesquisar empresas e entidades em todo o sistema"
            className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                inputRef.current?.focus();
              }}
              aria-label="Limpar pesquisa"
              className="rounded-full p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <X size={14} />
            </button>
          ) : null}
          <button
            type="submit"
            className="shrink-0 rounded-full bg-gradient-to-r from-emerald-400 to-teal-600 px-4 py-1.5 text-xs font-medium text-white"
          >
            Pesquisar
          </button>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-1">
        {sourcesWithAll.map((entry) => sourceChip(entry))}
      </div>

      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        {loading ? (
          <>
            <Loader2 size={12} className="animate-spin" /> A pesquisar
            {submitted ? ` «${submitted}»` : " no diretório"}… {segundosDecorridos}s
          </>
        ) : result ? (
          <>
            {numberFormat.format(result.total)} registos em {result.took_ms} ms
            {submitted ? ` para «${result.query}»` : ""} · a mostrar {sorted.length}
          </>
        ) : null}
        {!loading && !result ? (
          <button
            type="button"
            onClick={() => void run(submitted, source)}
            className="rounded-full border border-white/15 bg-white/5 px-3 py-1 hover:bg-white/10"
          >
            Carregar empresas
          </button>
        ) : null}
      </div>

      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} className="mt-0.5" /> {error}
        </div>
      ) : null}

      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_290px]">
        <div className="min-w-0 space-y-4">
          {cards.length && source === "all" ? (
            <div className="flex flex-wrap gap-2">
              {cards.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  onClick={() => setSource(card.id)}
                  className="glass-card flex items-center gap-2 rounded-xl px-3 py-2 text-left text-[11px] hover:bg-white/[0.06]"
                >
                  <span className={SOURCE_TONE[card.id] ?? "text-muted-foreground"}>
                    {SOURCE_ICON[card.id] ?? <Users size={13} />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{card.label}</span>
                    <span className="text-muted-foreground">
                      {card.total ? `${numberFormat.format(card.total)} resultados` : "sem resultados"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : null}

          {!loading && result && sorted.length === 0 ? (
            <div className="glass-card rounded-2xl px-6 py-12 text-center">
              <Users size={26} className="mx-auto text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">Sem empresas ou entidades para esta pesquisa</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Experimente outro nome, um NIF/NIPC, uma marca ou mude de fonte.
              </p>
            </div>
          ) : null}

          {sorted.map((row) => {
            const card = cardFor(row.source);
            const value = row.total_value;
            return (
              <article key={`${row.source}:${row.id}:${row.name}`} className="glass-card overflow-hidden rounded-2xl p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${
                          SOURCE_TONE[row.source] ?? "border-white/10 bg-white/5 text-muted-foreground"
                        }`}
                      >
                        {SOURCE_ICON[row.source] ?? <Users size={11} />}
                        {sourceLabel(card, row.source_label)}
                      </span>
                      {row.country ? (
                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
                          {row.country}
                        </span>
                      ) : null}
                      {row.nif ? (
                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
                          NIF {row.nif}
                        </span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => row.open && openResult(row.open, row.name.slice(0, 60), onOpenView)}
                      className="mt-1.5 block w-full truncate text-left text-sm font-medium hover:underline"
                      title={row.name}
                    >
                      {row.name}
                    </button>
                    {row.detail ? (
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{row.detail}</p>
                    ) : null}
                  </div>
                  <div className="shrink-0 text-right">
                    {typeof value === "number" && value > 0 ? (
                      <p className="text-sm font-semibold text-emerald-200" title={money(value) ?? ""}>
                        {compact(value)}
                      </p>
                    ) : null}
                    {row.contracts_count ? (
                      <p className="text-[11px] text-muted-foreground">
                        {numberFormat.format(row.contracts_count)} contratos
                      </p>
                    ) : null}
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {row.open ? (
                    <button
                      type="button"
                      onClick={() => openResult(row.open, row.name.slice(0, 60), onOpenView)}
                      className="inline-flex items-center gap-1 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-0.5 text-[10px] text-emerald-200 hover:bg-emerald-400/20"
                    >
                      Abrir ficha <ArrowRight size={10} />
                    </button>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">sem ficha interna</span>
                  )}
                  {row.extra?.dir3 ? (
                    <span className="text-[10px] text-muted-foreground">DIR3 {String(row.extra.dir3)}</span>
                  ) : null}
                  {row.extra?.last_year ? (
                    <span className="text-[10px] text-muted-foreground">último contrato {String(row.extra.last_year)}</span>
                  ) : null}
                  {row.region ? <span className="text-[10px] text-muted-foreground">{row.region}</span> : null}
                </div>
              </article>
            );
          })}

          {hasMore ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs hover:bg-white/10"
            >
              {loadingMore ? <Loader2 size={12} className="mx-auto animate-spin" /> : "Carregar mais"}
            </button>
          ) : null}
        </div>

        <aside className="space-y-3">
          <div className="glass-card rounded-2xl p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes</h2>
            <ul className="mt-2 space-y-1">
              {catalog.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => setSource(entry.id)}
                    title={entry.hint}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1 text-[11px] hover:bg-white/5 ${
                      source === entry.id ? "bg-white/10 text-foreground" : "text-muted-foreground"
                    }`}
                  >
                    <span className="flex min-w-0 items-center gap-1.5">
                      {SOURCE_ICON[entry.id] ?? <Users size={12} />}
                      <span className="truncate">{entry.label}</span>
                    </span>
                    <span className="tabular-nums">
                      {entry.blocked
                        ? "sessão"
                        : entry.available === null || entry.available === undefined
                          ? "—"
                          : numberFormat.format(entry.available)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-2 px-1 text-[10px] leading-relaxed text-muted-foreground">
              As fontes de Espanha são agregadas a partir dos 4 milhões de contratos do PLACSP: cada nome é um órgão
              adjudicante ou uma empresa adjudicatária, com o total de contratos e o valor somado.
            </p>
          </div>

          {cards.length ? (
            <div className="glass-card rounded-2xl p-4">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Resultados por fonte
              </h2>
              <ul className="mt-2 space-y-1 text-[11px]">
                {cards.map((card) => (
                  <li key={card.id} className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-muted-foreground">{card.label}</span>
                    <span className="tabular-nums">{card.error ? "erro" : numberFormat.format(card.total)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {cards.some((card) => card.error) ? (
            <div className="rounded-2xl border border-amber-400/25 bg-amber-400/5 p-3 text-[10.5px] text-amber-200">
              {cards
                .filter((card) => card.error)
                .map((card) => (
                  <p key={card.id} className="flex items-start gap-1.5">
                    <AlertTriangle size={11} className="mt-0.5" /> {card.label}: {card.error}
                  </p>
                ))}
            </div>
          ) : null}

          <a
            href="/pesquisa"
            className="glass-card flex items-center justify-between gap-2 rounded-2xl px-4 py-3 text-[11px] hover:bg-white/[0.06]"
          >
            <span className="text-muted-foreground">
              Procurar em tudo (contratos, notícias, recolha…)
            </span>
            <ExternalLink size={12} />
          </a>
        </aside>
      </div>
    </div>
  );
}
