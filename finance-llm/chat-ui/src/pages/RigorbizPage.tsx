/**
 * Diretório de empresas da RigorBiz — página de pesquisa.
 *
 * Lê o índice `finance_rigorbiz` (ou o JSONL local se o índice ainda não
 * existir). A pesquisa é por texto livre, CAE ou localização.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, ChevronLeft, ChevronRight, ExternalLink, Loader2, MapPin, RefreshCw, Search, Briefcase } from "lucide-react";

import {
  getRigorbizMeta,
  searchRigorbizCompanies,
  type RigorbizCompany,
  type RigorbizMeta,
  type RigorbizQuery,
} from "../rigorbizApi";

const PAGE_SIZE = 20;

const SORTS: { id: string; label: string }[] = [
  { id: "relevance", label: "Relevância" },
  { id: "name", label: "Nome (A–Z)" },
];

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
      {children}
    </span>
  );
}

function CompanyCard({ company }: { company: RigorbizCompany }) {
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold" title={company.name}>
            {company.name ?? "(sem nome)"}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            NIF {company.nif ?? "—"}
          </p>
        </div>
        {company.source_url ? (
          <a
            href={company.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
            title="Abrir a empresa na RigorBiz"
          >
            RigorBiz <ExternalLink size={11} />
          </a>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap gap-1">
        {company.cae_code ? <Badge>CAE {company.cae_code}</Badge> : null}
        {company.location ? (
          <Badge>
            <MapPin size={10} /> {company.location}
          </Badge>
        ) : null}
      </div>

      {company.cae_description ? (
        <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground" title={company.cae_description}>
          {company.cae_description}
        </p>
      ) : null}
    </article>
  );
}

export default function RigorbizPage() {
  const [meta, setMeta] = useState<RigorbizMeta | null>(null);
  const [items, setItems] = useState<RigorbizCompany[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [cae, setCae] = useState("");
  const [location, setLocation] = useState("");
  const [sort, setSort] = useState("relevance");
  const [page, setPage] = useState(0);
  const [submitted, setSubmitted] = useState<RigorbizQuery>({});

  const query = useMemo<RigorbizQuery>(
    () => ({ ...submitted, sort, size: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [submitted, sort, page],
  );

  const loadMeta = useCallback(async () => {
    try {
      setMeta(await getRigorbizMeta());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar o diretório.");
    }
  }, []);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchRigorbizCompanies(query);
        if (cancelled) return;
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
        if (data.error) setError(data.error);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Erro na pesquisa.");
        setItems([]);
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [query]);

  const submit = useCallback(() => {
    setPage(0);
    setSubmitted({ q: q.trim() || undefined, cae: cae.trim() || undefined, location: location.trim() || undefined });
  }, [q, cae, location]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-8">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full glass-card px-3 py-1 text-xs text-teal-300">
            <Briefcase size={14} />
            Diretório empresarial
          </div>
          <h1 className="mb-2 flex items-center gap-3 text-3xl font-bold">
            <span className="rounded-2xl border border-white/10 bg-gradient-to-br from-teal-500/20 to-blue-500/20 p-2">
              <Building2 size={32} className="text-teal-400" />
            </span>
            RigorBiz
          </h1>
          <p className="max-w-2xl text-muted-foreground">
            Pesquisa no diretório de empresas portuguesas da RigorBiz.
          </p>
        </div>

        <div className="mb-6 grid grid-cols-1 gap-4 rounded-2xl glass-card p-4 md:grid-cols-4">
          <div className="relative md:col-span-2">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
              placeholder="Nome, NIF, localidade, atividade…"
              className="w-full rounded-xl border border-white/10 bg-background py-2 pl-9 pr-3 text-sm outline-none focus:border-teal-400/50"
            />
          </div>
          <input
            type="text"
            value={cae}
            onChange={(e) => setCae(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="CAE"
            className="rounded-xl border border-white/10 bg-background px-3 py-2 text-sm outline-none focus:border-teal-400/50"
          />
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Localização"
            className="rounded-xl border border-white/10 bg-background px-3 py-2 text-sm outline-none focus:border-teal-400/50"
          />
        </div>

        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <button
              onClick={submit}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lg shadow-primary/20 transition hover:opacity-90 disabled:opacity-50"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
              Pesquisar
            </button>
            <button
              onClick={() => {
                setQ("");
                setCae("");
                setLocation("");
                setPage(0);
                setSubmitted({});
              }}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl glass-card px-3 py-2 text-sm transition hover:bg-white/5 disabled:opacity-50"
            >
              <RefreshCw size={14} />
              Limpar
            </button>
          </div>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="rounded-xl border border-white/10 bg-background px-3 py-2 text-sm outline-none"
            >
              {SORTS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            <span>
              {total.toLocaleString("pt-PT")} resultado{total !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        {meta ? (
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="glass-card rounded-2xl px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Indexadas</p>
              <p className="mt-1 text-xl font-semibold">{meta.elasticsearch_count.toLocaleString("pt-PT")}</p>
              <p className="text-[10px] text-muted-foreground">{meta.index}</p>
            </div>
            <div className="glass-card rounded-2xl px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Recolhidas localmente</p>
              <p className="mt-1 text-xl font-semibold">{meta.local_count.toLocaleString("pt-PT")}</p>
            </div>
            <div className="glass-card rounded-2xl px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Fonte</p>
              <p className="mt-1 text-sm font-medium">RigorBiz</p>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="mb-4 rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-3">
          {items.map((item, idx) => (
            <CompanyCard key={item.nif ?? idx} company={item} />
          ))}
        </div>

        {totalPages > 1 ? (
          <div className="mt-6 flex items-center justify-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
              className="rounded-xl glass-card px-3 py-2 transition hover:bg-white/5 disabled:opacity-50"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-sm text-muted-foreground">
              Página {page + 1} de {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1 || loading}
              className="rounded-xl glass-card px-3 py-2 transition hover:bg-white/5 disabled:opacity-50"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
