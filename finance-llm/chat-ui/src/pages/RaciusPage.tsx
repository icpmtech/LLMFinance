/**
 * Diretório de empresas (Racius) — página de pesquisa.
 *
 * Lê o índice `finance_racius`, que a recolha do IQ OS alimenta (fonte
 * `racius-diretorio`): cada empresa traz os campos da ficha normalizados
 * (concelho, distrito, forma jurídica, capital social, morada, CAE…) e a ficha
 * completa. A pesquisa é por texto + filtros, com facetas para os dropdowns.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  ChevronLeft,
  ChevronRight,
  Euro,
  ExternalLink,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
} from "lucide-react";

import {
  formatEuros,
  getRaciusMeta,
  searchRaciusCompanies,
  type RaciusCompany,
  type RaciusMeta,
  type RaciusQuery,
} from "../raciusApi";

const PAGE_SIZE = 20;

const SORTS: { id: string; label: string }[] = [
  { id: "relevance", label: "Relevância" },
  { id: "nome", label: "Nome (A–Z)" },
  { id: "capital", label: "Capital social (maior)" },
  { id: "recent", label: "Recolha mais recente" },
  { id: "oldest", label: "Recolha mais antiga" },
];

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3" title={hint}>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "sky" | "emerald" }) {
  const tones: Record<string, string> = {
    neutral: "border-white/10 bg-white/5 text-muted-foreground",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** Ficha completa da empresa (rótulo → valor), como está na página de origem. */
function CompanyFicha({ ficha }: { ficha?: Record<string, string> }) {
  const entries = Object.entries(ficha ?? {});
  if (!entries.length) return null;
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
        Ficha da empresa ({entries.length} campos)
      </summary>
      <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px]">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="break-words">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function CompanyCard({ company }: { company: RaciusCompany }) {
  const local = [company.concelho, company.distrito].filter(Boolean).join(", ");
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold" title={company.nome}>
            {company.nome ?? "(sem nome)"}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            NIF {company.nif ?? "—"}
            {company.forma_juridica ? ` · ${company.forma_juridica}` : ""}
          </p>
        </div>
        {company.url ? (
          <a
            href={company.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
            title="Abrir a empresa no Racius"
          >
            Racius <ExternalLink size={11} />
          </a>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap gap-1">
        {local ? (
          <Badge tone="sky">
            <MapPin size={10} /> {local}
          </Badge>
        ) : null}
        {company.capital_social_eur !== undefined ? (
          <Badge tone="emerald">
            <Euro size={10} /> {formatEuros(company.capital_social_eur)}
          </Badge>
        ) : null}
        {company.cae ? <Badge>CAE {company.cae}</Badge> : null}
      </div>

      {company.morada ? (
        <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground" title={company.morada}>
          {company.morada}
        </p>
      ) : null}
      {company.atividade ? (
        <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground" title={company.atividade}>
          {company.atividade}
        </p>
      ) : null}

      <CompanyFicha ficha={company.ficha} />
    </article>
  );
}

export default function RaciusPage() {
  const [meta, setMeta] = useState<RaciusMeta | null>(null);
  const [items, setItems] = useState<RaciusCompany[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Record<string, { value: string; count: number }[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [distrito, setDistrito] = useState("");
  const [concelho, setConcelho] = useState("");
  const [forma, setForma] = useState("");
  const [minCapital, setMinCapital] = useState("");
  const [maxCapital, setMaxCapital] = useState("");
  const [sort, setSort] = useState("relevance");
  const [page, setPage] = useState(0);
  const [submitted, setSubmitted] = useState<RaciusQuery>({});

  const query = useMemo<RaciusQuery>(
    () => ({ ...submitted, sort, size: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [submitted, sort, page],
  );

  const loadMeta = useCallback(async () => {
    try {
      setMeta(await getRaciusMeta());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar o diretório.");
    }
  }, []);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    searchRaciusCompanies(query)
      .then((result) => {
        if (cancelled) return;
        setError(result.error ?? null);
        setItems(result.items ?? []);
        setTotal(result.total ?? 0);
        setFacets(result.facets ?? {});
        if (result.error) setLoading(false);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Falha na pesquisa.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  const distritos = useMemo(
    () => (facets.distrito ?? meta?.facets?.distrito ?? []).map((entry) => entry.value),
    [facets, meta],
  );
  const formas = useMemo(
    () => (facets.forma_juridica ?? meta?.facets?.forma_juridica ?? []).map((entry) => entry.value),
    [facets, meta],
  );
  // Os concelhos só fazem sentido dentro do distrito escolhido.
  const concelhos = useMemo(
    () => (facets.concelho ?? []).map((entry) => entry.value),
    [facets],
  );

  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    setPage(0);
    setSubmitted({
      q: q.trim() || undefined,
      distrito: distrito || undefined,
      concelho: concelho || undefined,
      forma_juridica: forma || undefined,
      minCapital: minCapital ? Number(minCapital) : undefined,
      maxCapital: maxCapital ? Number(maxCapital) : undefined,
    });
  };

  const clear = () => {
    setQ("");
    setDistrito("");
    setConcelho("");
    setForma("");
    setMinCapital("");
    setMaxCapital("");
    setSort("relevance");
    setPage(0);
    setSubmitted({});
  };

  const from = total ? page * PAGE_SIZE + 1 : 0;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
  const semDados = meta && !meta.available;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Building2 size={18} /> Diretório de empresas · Racius
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Empresas portuguesas recolhidas do Racius (nome, NIF, concelho/distrito, forma jurídica, capital social e
            ficha completa).
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void loadMeta();
            setSubmitted((previous) => ({ ...previous }));
          }}
          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Atualizar
        </button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Empresas" value={meta?.total ?? 0} hint="no índice do diretório" />
        <Kpi label="Distritos" value={distritos.length} hint="com empresas recolhidas" />
        <Kpi label="Formas jurídicas" value={formas.length} />
        <Kpi label="Resultados" value={total} hint={total ? `${from}–${to}` : "sem resultados"} />
      </div>

      {semDados ? (
        <div className="glass-card rounded-2xl p-4 text-xs text-muted-foreground">
          Ainda não há empresas no diretório. Corra a recolha <strong>Racius · Diretório de empresas (PT)</strong> em{" "}
          <em>Recolha → Fontes → Recolher agora</em> (ou{" "}
          <code>python -m collectors.racius</code>) para encher o índice.
        </div>
      ) : null}

      <form onSubmit={submit} className="glass-card flex flex-wrap items-end gap-2 rounded-2xl p-3">
        <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-[11px] text-muted-foreground">
          Pesquisar
          <span className="relative">
            <Search size={13} className="absolute left-2 top-2.5 text-muted-foreground" />
            <input
              id="racius-search"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="Nome, NIF, morada ou atividade…"
              className="w-full rounded-xl border border-white/10 bg-black/20 py-2 pl-7 pr-2 text-xs text-foreground"
            />
          </span>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Distrito
          <select
            value={distrito}
            onChange={(event) => {
              setDistrito(event.target.value);
              setConcelho("");
            }}
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
          >
            <option value="">Todos</option>
            {distritos.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Concelho
          <select
            value={concelho}
            onChange={(event) => setConcelho(event.target.value)}
            disabled={!distrito}
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground disabled:opacity-50"
            title={distrito ? undefined : "Escolha primeiro o distrito"}
          >
            <option value="">Todos</option>
            {concelhos.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Forma jurídica
          <select
            value={forma}
            onChange={(event) => setForma(event.target.value)}
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
          >
            <option value="">Todas</option>
            {formas.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="flex w-28 flex-col gap-1 text-[11px] text-muted-foreground">
          Capital ≥ (€)
          <input
            value={minCapital}
            onChange={(event) => setMinCapital(event.target.value.replace(/[^\d]/g, ""))}
            inputMode="numeric"
            placeholder="0"
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
          />
        </label>
        <label className="flex w-28 flex-col gap-1 text-[11px] text-muted-foreground">
          Capital ≤ (€)
          <input
            value={maxCapital}
            onChange={(event) => setMaxCapital(event.target.value.replace(/[^\d]/g, ""))}
            inputMode="numeric"
            placeholder="—"
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Ordenar
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
          >
            {SORTS.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="inline-flex items-center gap-2 rounded-xl border border-orange-400/40 bg-orange-400/15 px-3 py-2 text-xs text-orange-100 hover:bg-orange-400/25"
        >
          <Search size={13} /> Pesquisar
        </button>
        <button
          type="button"
          onClick={clear}
          className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
        >
          Limpar
        </button>
      </form>

      {error ? (
        <div className="glass-card rounded-2xl border border-rose-400/25 bg-rose-400/5 p-3 text-xs text-rose-100">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-xs text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A pesquisar…
        </div>
      ) : items.length ? (
        <>
          <div className="grid gap-3 lg:grid-cols-2">
            {items.map((company) => (
              <CompanyCard key={company.nif ?? company.nome} company={company} />
            ))}
          </div>
          <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>
              {from}–{to} de {total} empresas
            </span>
            <span className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((value) => Math.max(0, value - 1))}
                disabled={page === 0}
                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 hover:bg-white/10 disabled:opacity-40"
              >
                <ChevronLeft size={12} /> Anterior
              </button>
              <button
                type="button"
                onClick={() => setPage((value) => Math.min(lastPage, value + 1))}
                disabled={page >= lastPage}
                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 hover:bg-white/10 disabled:opacity-40"
              >
                Seguinte <ChevronRight size={12} />
              </button>
            </span>
          </div>
        </>
      ) : (
        <div className="glass-card rounded-2xl p-4 text-xs text-muted-foreground">
          Sem empresas para estes filtros.
        </div>
      )}
    </div>
  );
}
