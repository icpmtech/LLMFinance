/**
 * CIRE — Publicidade do PER, PEAP, PEVE e da insolvência (CITIUS / Ministério da Justiça).
 *
 * Recolhe a lista de resultados da pesquisa do portal (`consultascire.aspx`),
 * grava-a em **JSON** (`data/cire/runs/<run_id>.json`) e importa-a para o
 * Elasticsearch (`finance_cire`), onde fica pesquisável.
 *
 * Secções
 * - **Pesquisa** — procurar no índice por texto, NIF/NIPC, tribunal, tipo de
 *   processo, ato e datas; as facetas filtram com um clique.
 * - **Grafo** — rede de insolvências: entidades (insolventes, administradores,
 *   credores), tribunais, comarcas, tipos e tempo, com receitas prontas e
 *   navegação para as publicações de cada nó.
 * - **Recolha** — definir os critérios (iguais aos do portal: datas, atalho de
 *   dias, interveniente, processo, tribunal, grupo de atos, ato) e recolher; o
 *   progresso é acompanhado página a página.
 * - **Execuções** — ficheiros JSON gravados em `data/cire/runs`, com a
 *   importação para o Elasticsearch e a remoção.
 * - **Estado** — volumetria do índice e distribuições (tribunais, tipos, meses).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Database,
  Download,
  FileJson,
  Gavel,
  Landmark,
  Loader2,
  Play,
  RefreshCw,
  Scale,
  Search,
  Share2,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import {
  deleteCireRun,
  getCireCoverage,
  getCireJob,
  getCireMeta,
  getCireOptions,
  getCireStatus,
  ingestCire,
  listCireJobs,
  listCireRuns,
  searchCire,
  startCireCollect,
  stopCireJob,
  type CireCollectCriteria,
  type CireCoverageWindow,
  type CireFacet,
  type CireJob,
  type CireMeta,
  type CireOptions,
  type CirePublicacao,
  type CireRun,
  type CireSearchParams,
  type CireSearchResult,
  type CireStatus,
} from "../cireApi";
import CireGraphPanel from "../components/cire/CireGraphPanel";

const numberFormat = new Intl.NumberFormat("pt-PT");
const dateFormat = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });

type Section = "pesquisa" | "grafo" | "recolha" | "execucoes" | "estado";

const SECTIONS: { id: Section; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "pesquisa", label: "Pesquisa", hint: "Procurar nas publicações indexadas", icon: <Search size={14} /> },
  { id: "grafo", label: "Grafo", hint: "Rede de insolvências: entidades, tribunais, tipos e tempo", icon: <Share2 size={14} /> },
  { id: "recolha", label: "Recolha", hint: "Recolher a lista do portal para JSON", icon: <Play size={14} /> },
  { id: "execucoes", label: "Execuções", hint: "Ficheiros gravados e importação", icon: <FileJson size={14} /> },
  { id: "estado", label: "Estado", hint: "Volumetria e distribuições do índice", icon: <Database size={14} /> },
];

/** Data ISO de hoje (e um intervalo por omissão de 7 dias). */
function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  try {
    return dateFormat.format(new Date(value));
  } catch {
    return value;
  }
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("pt-PT");
  } catch {
    return value;
  }
}

/**
 * Divide o intervalo em janelas (mais recente primeiro), como o backend faz.
 * Serve para avisar, antes de recolher, que dias já foram processados.
 */
function splitWindows(desde: string, ate: string, windowDays: number): { desde: string; ate: string }[] {
  if (!desde || !ate || windowDays <= 0) return desde && ate ? [{ desde, ate }] : [];
  const start = new Date(`${desde}T00:00:00Z`);
  const end = new Date(`${ate}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) return [];
  const janelas: { desde: string; ate: string }[] = [];
  let cursor = end;
  while (cursor >= start) {
    const ini = new Date(Math.max(start.getTime(), cursor.getTime() - (windowDays - 1) * 86400000));
    janelas.push({ desde: ini.toISOString().slice(0, 10), ate: cursor.toISOString().slice(0, 10) });
    cursor = new Date(ini.getTime() - 86400000);
  }
  return janelas;
}

/* ------------------------------------------------------------------ peças */

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

function Facets({
  title,
  facet,
  active,
  onPick,
}: {
  title: string;
  facet?: CireFacet[];
  active?: string;
  onPick: (key: string) => void;
}) {
  if (!facet || facet.length === 0) return null;
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="flex flex-wrap gap-1">
        {facet.slice(0, 12).map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onPick(item.key)}
            title={`Filtrar por ${item.key}`}
            className={`rounded-full border px-2 py-0.5 text-[10.5px] transition ${
              active === item.key
                ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-200"
                : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            }`}
          >
            {item.key} <span className="opacity-60">{numberFormat.format(item.count)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Cartão de uma publicação do CIRE. */
function PublicacaoCard({ item, onNif }: { item: CirePublicacao; onNif: (nif: string) => void }) {
  const intervenientes = item.intervenientes ?? [];
  const [open, setOpen] = useState(false);
  const visiveis = open ? intervenientes : intervenientes.slice(0, 4);
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10.5px] text-emerald-200">
              {item.tipo || "Processo"}
            </span>
            <span className="text-sm font-semibold text-foreground">{item.insolvente || item.referencia}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {item.tribunal || "—"} · {item.processo || "—"}
          </div>
        </div>
        <div className="text-right text-[11px] text-muted-foreground">
          <div className="font-medium text-foreground">{formatDate(item.data_publicacao)}</div>
          <div>ref. {item.referencia}</div>
        </div>
      </div>

      <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
        <div>
          <span className="text-muted-foreground/70">Ato:</span> {item.ato || "—"}
        </div>
        <div>
          <span className="text-muted-foreground/70">Espécie:</span> {item.especie || "—"}
        </div>
        {item.data_propositura ? (
          <div>
            <span className="text-muted-foreground/70">Propositura:</span> {formatDate(item.data_propositura)}
          </div>
        ) : null}
        {item.juizo ? (
          <div className="truncate" title={item.juizo}>
            <span className="text-muted-foreground/70">Juízo:</span> {item.juizo}
          </div>
        ) : null}
      </div>

      {visiveis.length > 0 ? (
        <div className="mt-2 space-y-1">
          {visiveis.map((pessoa, index) => (
            <div key={`${pessoa.papel}-${pessoa.nif}-${index}`} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate">
                <span className="text-muted-foreground/70">{pessoa.papel}:</span> {pessoa.nome}
              </span>
              {pessoa.nif ? (
                <button
                  type="button"
                  onClick={() => onNif(pessoa.nif as string)}
                  className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
                  title={`Ver todas as publicações com o NIF ${pessoa.nif}`}
                >
                  {pessoa.nif}
                </button>
              ) : null}
            </div>
          ))}
          {intervenientes.length > 4 ? (
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              className="text-[10.5px] text-sky-300 hover:underline"
            >
              {open ? "Mostrar menos" : `Ver os ${intervenientes.length} intervenientes`}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------- página */

export default function CirePage({ section = "pesquisa" }: { section?: Section }) {
  const [active, setActive] = useState<Section>(section);
  const [meta, setMeta] = useState<CireMeta | null>(null);
  const [options, setOptions] = useState<CireOptions | null>(null);
  const [status, setStatus] = useState<CireStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** Filtros vindos do grafo (navegação de um nó para a pesquisa). */
  const [searchSeed, setSearchSeed] = useState<{ id: number; params: CireSearchParams } | null>(null);

  const openSearch = useCallback((params: CireSearchParams) => {
    setSearchSeed({ id: Date.now(), params });
    setActive("pesquisa");
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getCireStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    getCireMeta().then(setMeta).catch(() => undefined);
    getCireOptions().then(setOptions).catch(() => undefined);
    void refreshStatus();
  }, [refreshStatus]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-emerald-500/30 via-teal-600/25 to-slate-900 p-2 text-emerald-100">
          <Gavel size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Insolvências e revitalizações (CIRE)</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {meta?.source_label ?? "Publicidade do PER, PEAP, PEVE e da insolvência — CITIUS / Ministério da Justiça"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> · {numberFormat.format(status?.documents ?? 0)} docs
            </span>
          ) : null}
          {meta?.source_url ? (
            <a
              href={meta.source_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              portal
            </a>
          ) : null}
        </div>
      </header>

      <nav className="flex flex-wrap items-center gap-1 border-b border-white/10 px-6 py-2">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setActive(item.id)}
            title={item.hint}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11.5px] transition ${
              active === item.id
                ? "bg-emerald-400/15 text-emerald-200"
                : "text-muted-foreground hover:bg-white/5 hover:text-foreground"
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {(error || notice) && (
          <div className="mb-3 flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
            {error ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
            <span className="flex-1">{error ?? notice}</span>
            <button type="button" className="opacity-70 hover:opacity-100" onClick={() => { setError(null); setNotice(null); }}>
              ×
            </button>
          </div>
        )}

        {active === "pesquisa" && <SearchSection meta={meta} onStatus={refreshStatus} seed={searchSeed} />}
        {active === "grafo" && <CireGraphPanel onOpenSearch={openSearch} />}
        {active === "recolha" && (
          <RecolhaSection meta={meta} options={options} onDone={(message) => { setNotice(message); void refreshStatus(); }} />
        )}
        {active === "execucoes" && <ExecucoesSection onDone={(message) => { setNotice(message); void refreshStatus(); }} />}
        {active === "estado" && <EstadoSection status={status} onRefresh={refreshStatus} />}
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- pesquisa */

function SearchSection({
  meta,
  onStatus,
  seed,
}: {
  meta: CireMeta | null;
  onStatus: () => void;
  seed?: { id: number; params: CireSearchParams } | null;
}) {
  const [query, setQuery] = useState("");
  const [nif, setNif] = useState("");
  const [tipo, setTipo] = useState("");
  const [papel, setPapel] = useState("");
  const [comarca, setComarca] = useState("");
  const [dataFrom, setDataFrom] = useState("");
  const [dataTo, setDataTo] = useState("");
  const [size] = useState(20);
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<CireSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (offset: number, override?: CireSearchParams) => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchCire({
          q: query || undefined,
          nif: nif || undefined,
          tipo: tipo || undefined,
          papel: papel || undefined,
          tribunal_comarca: comarca || undefined,
          data_from: dataFrom || undefined,
          data_to: dataTo || undefined,
          ...(override ?? {}),
          size,
          from: offset,
        });
        if (data.error) throw new Error(data.error);
        setResult(data);
        setPage(offset);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [query, nif, tipo, papel, comarca, dataFrom, dataTo, size],
  );

  useEffect(() => {
    void run(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Filtros vindos do grafo: preenche os campos e procura logo.
  useEffect(() => {
    if (!seed) return;
    setQuery(seed.params.q ?? "");
    setNif(seed.params.nif ?? "");
    setTipo(seed.params.tipo ?? "");
    setPapel(seed.params.papel ?? "");
    setComarca(seed.params.tribunal_comarca ?? "");
    setDataFrom(seed.params.data_from ?? "");
    setDataTo(seed.params.data_to ?? "");
    void run(0, seed.params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.id]);

  const total = result?.total ?? 0;
  const items = result?.items ?? [];
  const facetas = result?.facets ?? {};
  const papeis = useMemo(
    () => ["Insolvente", "Administrador Insolvência", "Credor", "Fiduciário", "Devedor"],
    [],
  );

  const limpar = () => {
    setQuery("");
    setNif("");
    setTipo("");
    setPapel("");
    setComarca("");
    setDataFrom("");
    setDataTo("");
    void run(0);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-3">
        <Card className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Filtros</div>
          <label className="block text-[11px] text-muted-foreground">
            Texto livre (pessoa, tribunal, processo, ato)
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void run(0)}
              placeholder="ex.: construção civil"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            NIF/NIPC do interveniente
            <input
              value={nif}
              onChange={(event) => setNif(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void run(0)}
              placeholder="ex.: 500189412"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 font-mono text-[12px] text-foreground outline-none"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[11px] text-muted-foreground">
              De
              <input
                type="date"
                value={dataFrom}
                onChange={(event) => setDataFrom(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
              />
            </label>
            <label className="block text-[11px] text-muted-foreground">
              Até
              <input
                type="date"
                value={dataTo}
                onChange={(event) => setDataTo(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
              />
            </label>
          </div>
          <label className="block text-[11px] text-muted-foreground">
            Tipo de processo
            <select
              value={tipo}
              onChange={(event) => setTipo(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            >
              <option value="">Todos</option>
              {(facetas.tipo ?? []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.key} ({item.count})
                </option>
              ))}
              {["Insolvência", "PER", "PEAP", "PEVE"].filter((t) => !(facetas.tipo ?? []).some((f) => f.key === t)).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Papel do interveniente
            <select
              value={papel}
              onChange={(event) => setPapel(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            >
              <option value="">Todos</option>
              {papeis.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={() => void run(0)}
              disabled={loading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/20 px-3 py-1.5 text-[12px] font-medium text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
              Pesquisar
            </button>
            <button
              type="button"
              onClick={limpar}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[12px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              Limpar
            </button>
          </div>
        </Card>

        <Card className="space-y-3">
          <Facets title="Comarca" facet={facetas.tribunal_comarca} active={comarca} onPick={(key) => { setComarca(key); void run(0); }} />
          <Facets title="Tipo" facet={facetas.tipo} active={tipo} onPick={(key) => { setTipo(key); void run(0); }} />
          <Facets title="Papel" facet={facetas.papel} active={papel} onPick={(key) => { setPapel(key); void run(0); }} />
          <Facets title="Ato" facet={facetas.ato} onPick={(key) => { setQuery(key); void run(0); }} />
          <Facets title="Ano" facet={facetas.ano} onPick={(key) => { setDataFrom(`${key}-01-01`); setDataTo(`${key}-12-31`); void run(0); }} />
        </Card>

        {meta?.notes ? <p className="px-1 text-[10.5px] leading-relaxed text-muted-foreground">{meta.notes}</p> : null}
      </aside>

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11.5px] text-muted-foreground">
            {loading ? "a pesquisar…" : `${numberFormat.format(total)} publicações`}
            {total > size ? ` · página ${Math.floor(page / size) + 1} de ${Math.ceil(total / size)}` : ""}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={page === 0 || loading}
              onClick={() => void run(Math.max(0, page - size))}
              className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10 disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={page + size >= total || loading}
              onClick={() => void run(page + size)}
              className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10 disabled:opacity-40"
            >
              Seguinte
            </button>
            <button
              type="button"
              onClick={() => { void run(page); onStatus(); }}
              className="rounded-lg border border-white/10 bg-white/5 p-1.5 text-muted-foreground hover:bg-white/10"
              title="Atualizar"
            >
              <RefreshCw size={12} />
            </button>
          </div>
        </div>

        {error ? (
          <Card className="border-rose-400/25 bg-rose-400/5 text-[11.5px] text-rose-200">{error}</Card>
        ) : null}

        {!loading && items.length === 0 ? (
          <Card className="text-[11.5px] text-muted-foreground">
            Sem publicações para estes filtros. Se o índice ainda estiver vazio, faça uma recolha na secção
            <span className="text-foreground"> Recolha</span>.
          </Card>
        ) : null}

        <div className="space-y-2">
          {items.map((item) => (
            <PublicacaoCard
              key={item.pub_id}
              item={item}
              onNif={(value) => { setNif(value); void run(0); }}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- recolha */

function RecolhaSection({
  meta,
  options,
  onDone,
}: {
  meta: CireMeta | null;
  options: CireOptions | null;
  onDone: (message: string) => void;
}) {
  const [desde, setDesde] = useState(isoDaysAgo(7));
  const [ate, setAte] = useState(isoDaysAgo(0));
  const [dias, setDias] = useState("");
  const [nif, setNif] = useState("");
  const [nome, setNome] = useState("");
  const [numeroProcesso, setNumeroProcesso] = useState("");
  const [tribunal, setTribunal] = useState("");
  const [grupo, setGrupo] = useState("");
  const [acto, setActo] = useState("");
  const [maxPages, setMaxPages] = useState(20);
  const [windowDays, setWindowDays] = useState(meta?.default_window_days ?? 31);
  const [minInterval, setMinInterval] = useState(meta?.min_request_interval ?? 1.2);
  const [indexar, setIndexar] = useState(true);
  const [porJanela, setPorJanela] = useState(false);
  const [forcar, setForcar] = useState(false);
  const [cobertura, setCobertura] = useState<CireCoverageWindow[]>([]);
  const [job, setJob] = useState<CireJob | null>(null);
  const [jobs, setJobs] = useState<CireJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const carregarCobertura = useCallback(async () => {
    try {
      const data = await getCireCoverage();
      setCobertura(data.windows);
    } catch {
      /* sem cobertura */
    }
  }, []);

  const carregarJobs = useCallback(async () => {
    try {
      const data = await listCireJobs();
      setJobs(data.jobs);
      const maisRecente = data.jobs[0];
      if (maisRecente) setJob(maisRecente);
    } catch {
      /* sem jobs */
    }
  }, []);

  useEffect(() => {
    void carregarJobs();
    void carregarCobertura();
  }, [carregarJobs, carregarCobertura]);

  // Janelas do intervalo escolhido que já foram processadas (aviso antes de recolher).
  const jaProcessadas = useMemo(() => {
    if (dias) return [];
    const existentes = new Map(cobertura.map((janela) => [`${janela.desde}|${janela.ate}`, janela]));
    return splitWindows(desde, ate, windowDays)
      .map((janela) => existentes.get(`${janela.desde}|${janela.ate}`))
      .filter((janela): janela is CireCoverageWindow => Boolean(janela));
  }, [cobertura, desde, ate, dias, windowDays]);

  // Acompanha o job em curso (progresso página a página).
  useEffect(() => {
    if (!job || job.finished) return undefined;
    timer.current = window.setInterval(async () => {
      try {
        const atualizado = await getCireJob(job.id);
        setJob(atualizado);
        if (atualizado.finished) {
          void carregarJobs();
          void carregarCobertura();
        }
      } catch {
        /* ignora falhas de polling */
      }
    }, 2500);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [job, carregarJobs, carregarCobertura]);

  const recolher = async () => {
    setBusy(true);
    setError(null);
    try {
      const criteria: CireCollectCriteria = {
        desde: dias ? null : desde || null,
        ate: dias ? null : ate || null,
        dias: dias || null,
        nif: nif || null,
        nome: nome || null,
        numero_processo: numeroProcesso || null,
        tribunal: tribunal || null,
        grupo_actos: grupo || null,
        acto: acto || null,
        max_pages: maxPages,
        window_days: windowDays,
        min_interval: minInterval,
        force: forcar,
        split_runs: porJanela,
        index: indexar,
      };
      const started = await startCireCollect(criteria);
      setJob(started);
      await carregarJobs();
      await carregarCobertura();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const parar = async () => {
    if (!job) return;
    try {
      setJob(await stopCireJob(job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const emCurso = Boolean(job && !job.finished);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="space-y-3">
        <div className="flex items-center gap-2">
          <Landmark size={16} className="text-emerald-200" />
          <h2 className="text-[13px] font-semibold text-foreground">Critérios da recolha</h2>
          <span className="text-[10.5px] text-muted-foreground">
            {meta?.page_size ?? 10} documentos por página do portal
          </span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-[11px] text-muted-foreground">
            Data início
            <input
              type="date"
              value={desde}
              disabled={Boolean(dias)}
              onChange={(event) => setDesde(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none disabled:opacity-40"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Data fim
            <input
              type="date"
              value={ate}
              disabled={Boolean(dias)}
              onChange={(event) => setAte(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none disabled:opacity-40"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">Ou atalho do portal:</span>
          {[{ value: "", label: "Intervalo de datas" }, ...(options?.dias ?? meta?.dias ?? [])].map((item) => (
            <button
              key={item.value || "custom"}
              type="button"
              onClick={() => setDias(item.value)}
              className={`rounded-full border px-2 py-0.5 text-[10.5px] transition ${
                dias === item.value
                  ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-200"
                  : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-[11px] text-muted-foreground">
            NIF/NIPC do interveniente
            <input
              value={nif}
              onChange={(event) => setNif(event.target.value)}
              placeholder="ex.: 500189412"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 font-mono text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Designação (mín. 3 caracteres, sem tribunal selecionado)
            <input
              value={nome}
              onChange={(event) => setNome(event.target.value)}
              placeholder="ex.: Construções"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Número do processo
            <input
              value={numeroProcesso}
              onChange={(event) => setNumeroProcesso(event.target.value)}
              placeholder="ex.: 1401/26.0T8ACB"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Tribunal
            <select
              value={tribunal}
              onChange={(event) => setTribunal(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            >
              <option value="">Todos os tribunais</option>
              {(options?.tribunais ?? []).slice(1).map((item) => (
                <option key={item.value} value={item.label}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Grupo de atos
            <select
              value={grupo}
              onChange={(event) => setGrupo(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            >
              <option value="">Todos os grupos</option>
              {(options?.grupos_actos ?? meta?.grupos_actos ?? []).map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Ato
            <select
              value={acto}
              onChange={(event) => setActo(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            >
              <option value="">Todos os atos</option>
              {(options?.actos ?? []).slice(1).map((item) => (
                <option key={item.value} value={item.label}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-[11px] text-muted-foreground">
            Máx. páginas por janela
            <input
              type="number"
              min={1}
              value={maxPages}
              onChange={(event) => setMaxPages(Number(event.target.value) || 1)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Janela (dias)
            <input
              type="number"
              min={1}
              max={meta?.max_window_days ?? 366}
              value={windowDays}
              onChange={(event) => setWindowDays(Number(event.target.value) || 1)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Pausa entre pedidos (s)
            <input
              type="number"
              min={0}
              step={0.1}
              value={minInterval}
              onChange={(event) => setMinInterval(Number(event.target.value) || 0)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none"
            />
          </label>
        </div>

        <label className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <input type="checkbox" checked={indexar} onChange={(event) => setIndexar(event.target.checked)} />
          Importar para o Elasticsearch depois de gravar o JSON (só o que ainda não existe)
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            <input type="checkbox" checked={porJanela} onChange={(event) => setPorJanela(event.target.checked)} />
            Uma recolha (JSON) por janela — períodos longos
          </label>
          <label className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            <input type="checkbox" checked={forcar} onChange={(event) => setForcar(event.target.checked)} />
            Forçar reprocessamento de dias já recolhidos
          </label>
        </div>

        {!dias && jaProcessadas.length > 0 && !forcar ? (
          <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
            <div className="flex items-center gap-1.5 font-medium">
              <AlertTriangle size={12} />
              {jaProcessadas.length} janela(s) deste intervalo já foram processadas e vão ser ignoradas:
            </div>
            <ul className="mt-1 space-y-0.5">
              {jaProcessadas.slice(0, 6).map((janela) => (
                <li key={`${janela.desde}|${janela.ate}`} className="font-mono text-[10.5px]">
                  {janela.desde} → {janela.ate} · {numberFormat.format(janela.collected ?? 0)} docs
                  {janela.run_id ? ` · ${janela.run_id}` : ""}
                </li>
              ))}
              {jaProcessadas.length > 6 ? <li className="text-[10.5px]">… e mais {jaProcessadas.length - 6}.</li> : null}
            </ul>
            <div className="mt-1 text-[10.5px] text-amber-200/80">
              Marque «Forçar reprocessamento» para recolher outra vez.
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-rose-400/25 bg-rose-400/5 px-3 py-2 text-[11px] text-rose-200">{error}</div>
        ) : null}

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void recolher()}
            disabled={busy || emCurso}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-500/20 px-3 py-1.5 text-[12px] font-medium text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
          >
            {busy || emCurso ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
            Recolher
          </button>
          {emCurso ? (
            <button
              type="button"
              onClick={() => void parar()}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[12px] text-muted-foreground hover:bg-white/10"
            >
              <Square size={12} />
              Parar
            </button>
          ) : null}
          <span className="text-[10.5px] text-muted-foreground">
            Os JSON ficam em <span className="font-mono">{meta?.storage ?? "data/cire/runs"}</span>
          </span>
        </div>
      </Card>

      <aside className="space-y-3">
        {job ? (
          <Card className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Recolha atual</span>
              <span
                className={`rounded-full px-2 py-0.5 text-[10.5px] ${
                  job.state === "done"
                    ? "bg-emerald-400/15 text-emerald-200"
                    : job.state === "error"
                      ? "bg-rose-400/15 text-rose-200"
                      : "bg-sky-400/15 text-sky-200"
                }`}
              >
                {job.state}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Recolhidos" value={numberFormat.format(job.collected ?? 0)} hint={job.run_id ? job.run_id.slice(-24) : undefined} />
              <Stat label="Páginas" value={numberFormat.format(job.pages ?? 0)} hint={job.page ? `página ${job.page}` : undefined} />
              <Stat label="Declarado" value={numberFormat.format(job.declared_total ?? 0)} hint="total do portal" />
              <Stat label="No índice" value={numberFormat.format(job.indexed ?? 0)} hint={job.index_total ? `total ${job.index_total}` : undefined} />
            </div>
            {job.stage ? <div className="text-[11px] text-muted-foreground">etapa: {job.stage}</div> : null}
            {job.window ? (
              <div className="text-[10.5px] text-muted-foreground">
                janela {job.window.desde ?? "—"} → {job.window.ate ?? "—"}
                {job.window_index && job.window_total ? ` (${job.window_index}/${job.window_total})` : ""}
                {job.runs_done ? ` · ${job.runs_done} recolhas gravadas` : ""}
              </div>
            ) : null}
            {job.skipped_existing ? (
              <div className="text-[10.5px] text-muted-foreground">
                {numberFormat.format(job.skipped_existing)} documentos já existiam no índice (não reescritos)
              </div>
            ) : null}
            {job.warnings && job.warnings.length > 0 ? (
              <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 px-2 py-1.5 text-[10.5px] text-amber-200">
                <div className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle size={11} />
                  avisos da recolha
                </div>
                <ul className="mt-1 space-y-0.5">
                  {job.warnings.slice(0, 5).map((aviso, index) => (
                    <li key={index}>{aviso}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {job.error ? <div className="text-[11px] text-rose-200">{job.error}</div> : null}
            {job.errors && job.errors.length > 0 ? (
              <div className="max-h-24 overflow-y-auto text-[10.5px] text-amber-200">{job.errors.join("\n")}</div>
            ) : null}
            {job.file ? <div className="truncate text-[10px] text-muted-foreground" title={job.file}>{job.file}</div> : null}
          </Card>
        ) : null}

        <Card className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Recolhas recentes</div>
          {jobs.length === 0 ? (
            <div className="text-[11px] text-muted-foreground">Ainda não há recolhas nesta sessão.</div>
          ) : (
            jobs.slice(0, 6).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setJob(item)}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-left text-[11px] hover:bg-white/10"
              >
                <span className="truncate text-muted-foreground">{item.criteria?.nif || item.criteria?.nome || "recolha geral"}</span>
                <span className="shrink-0 text-foreground">{numberFormat.format(item.collected ?? 0)}</span>
                <span
                  className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${
                    item.state === "done" ? "bg-emerald-400/15 text-emerald-200" : item.state === "error" ? "bg-rose-400/15 text-rose-200" : "bg-sky-400/15 text-sky-200"
                  }`}
                >
                  {item.state}
                </span>
              </button>
            ))
          )}
          {job?.finished ? (
            <button
              type="button"
              onClick={() => onDone(`Recolha ${job.run_id ?? ""} concluída com ${job.collected ?? 0} documentos.`)}
              className="text-[10.5px] text-sky-300 hover:underline"
            >
              confirmar conclusão
            </button>
          ) : null}
        </Card>
      </aside>
    </div>
  );
}

/* -------------------------------------------------------------- execuções */

function ExecucoesSection({ onDone }: { onDone: (message: string) => void }) {
  const [runs, setRuns] = useState<CireRun[]>([]);
  const [directory, setDirectory] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listCireRuns(100);
      setRuns(data.items);
      setDirectory(data.directory);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const importar = async (runId: string) => {
    setBusy(runId);
    try {
      const result = await ingestCire({ run_id: runId });
      const novos = result.indexed_count ?? 0;
      const existentes = result.skipped_existing ?? 0;
      onDone(
        existentes > 0
          ? `Recolha ${runId}: ${numberFormat.format(novos)} novos documentos indexados; ` +
            `${numberFormat.format(existentes)} já existiam no índice (não reescritos).`
          : `Recolha ${runId}: ${numberFormat.format(novos)} documentos indexados em finance_cire.`,
      );
      await carregar();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const apagar = async (runId: string) => {
    setBusy(runId);
    try {
      await deleteCireRun(runId);
      onDone(`Ficheiros da recolha ${runId} apagados.`);
      await carregar();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11.5px] text-muted-foreground">
          {loading ? "a carregar…" : `${runs.length} recolhas gravadas`} · pasta{" "}
          <span className="font-mono">{directory || "data/cire/runs"}</span>
        </div>
        <button
          type="button"
          onClick={() => void carregar()}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10"
        >
          <RefreshCw size={12} />
          Atualizar
        </button>
      </div>

      {error ? (
        <Card className="border-rose-400/25 bg-rose-400/5 text-[11.5px] text-rose-200">{error}</Card>
      ) : null}

      {runs.length === 0 ? (
        <Card className="text-[11.5px] text-muted-foreground">
          Ainda não há ficheiros em <span className="font-mono">data/cire/runs</span>. Faça uma recolha na secção Recolha.
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="w-full text-[11.5px]">
            <thead className="bg-white/5 text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Recolha</th>
                <th className="px-3 py-2">Critérios</th>
                <th className="px-3 py-2 text-right">Recolhidos</th>
                <th className="px-3 py-2 text-right">Páginas</th>
                <th className="px-3 py-2 text-right">No índice</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const criteria = (run.criteria ?? {}) as Record<string, unknown>;
                const alvo = (criteria.nif as string) || (criteria.nome as string) || "";
                const intervalo = [criteria.desde, criteria.ate].filter(Boolean).join(" → ") || (criteria.dias as string) || "todos";
                return (
                  <tr key={run.run_id} className="border-t border-white/5">
                    <td className="px-3 py-2">
                      <div className="font-mono text-[10.5px] text-foreground">{run.run_id}</div>
                      <div className="text-[10px] text-muted-foreground">{formatDateTime(run.created_at)}</div>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      <div>{intervalo}</div>
                      <div className="text-[10px]">
                        {alvo ? `alvo: ${alvo}` : "sem alvo"}
                        {criteria.tribunal ? ` · ${criteria.tribunal}` : ""}
                        {criteria.acto ? ` · ${criteria.acto}` : ""}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">{numberFormat.format(run.collected ?? 0)}</td>
                    <td className="px-3 py-2 text-right">{numberFormat.format(run.pages ?? 0)}</td>
                    <td className="px-3 py-2 text-right">
                      {numberFormat.format(run.index_count ?? run.indexed ?? 0)}
                    </td>
                    <td className="px-3 py-2">
                      {run.errors && run.errors.length > 0 ? (
                        <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-[10px] text-amber-200">
                          {run.errors.length} avisos
                        </span>
                      ) : run.index_count ? (
                        <span className="rounded-full bg-emerald-400/15 px-2 py-0.5 text-[10px] text-emerald-200">importada</span>
                      ) : run.indexed ? (
                        <span className="rounded-full bg-emerald-400/15 px-2 py-0.5 text-[10px] text-emerald-200">
                          {numberFormat.format(run.indexed)} novos
                        </span>
                      ) : (
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-muted-foreground">por importar</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          disabled={busy === run.run_id}
                          onClick={() => void importar(run.run_id)}
                          className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-40"
                          title="Importar esta recolha para o Elasticsearch"
                        >
                          {busy === run.run_id ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
                          Importar
                        </button>
                        <button
                          type="button"
                          disabled={busy === run.run_id}
                          onClick={() => void apagar(run.run_id)}
                          className="rounded-lg border border-white/10 bg-white/5 p-1 text-muted-foreground hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-40"
                          title="Apagar os ficheiros desta recolha"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ estado */

function Distribuicao({ title, facet }: { title: string; facet?: CireFacet[] }) {
  if (!facet || facet.length === 0) return null;
  const max = Math.max(...facet.map((item) => item.count), 1);
  return (
    <Card className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="space-y-1">
        {facet.slice(0, 10).map((item) => (
          <div key={item.key} className="space-y-0.5">
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate text-foreground" title={item.key}>
                {item.key}
              </span>
              <span className="shrink-0 text-muted-foreground">{numberFormat.format(item.count)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-400/70 to-teal-500/70"
                style={{ width: `${Math.max(2, (item.count / max) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function EstadoSection({ status, onRefresh }: { status: CireStatus | null; onRefresh: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
          <Scale size={15} className="text-emerald-200" />
          Índice {status?.index ?? "finance_cire"}
        </h2>
        <button
          type="button"
          onClick={onRefresh}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10"
        >
          <RefreshCw size={12} />
          Atualizar
        </button>
      </div>

      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Documentos" value={numberFormat.format(status?.documents ?? 0)} />
        <Stat label="NIF/NIPC" value={numberFormat.format(status?.nifs ?? 0)} hint="intervenientes distintos" />
        <Stat label="Insolventes" value={numberFormat.format(status?.insolventes ?? 0)} />
        <Stat label="Referências" value={numberFormat.format(status?.referencias ?? 0)} />
        <Stat label="Com documento" value={numberFormat.format(status?.with_documento ?? 0)} />
        <Stat
          label="Intervalo"
          value={status?.min_date ? formatDate(status.min_date) : "—"}
          hint={status?.max_date ? `até ${formatDate(status.max_date)}` : undefined}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Distribuicao title="Tipo de processo" facet={status?.by_tipo} />
        <Distribuicao title="Comarcas" facet={status?.top_comarcas} />
        <Distribuicao title="Tribunais" facet={status?.top_tribunais} />
        <Distribuicao title="Atos" facet={status?.top_actos} />
        <Distribuicao title="Espécies" facet={status?.by_especie} />
        <Distribuicao title="Por mês" facet={status?.by_mes} />
      </div>

      {status?.error ? (
        <Card className="border-rose-400/25 bg-rose-400/5 text-[11.5px] text-rose-200">{status.error}</Card>
      ) : null}

      {(status?.documents ?? 0) === 0 ? (
        <Card className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <Building2 size={14} />
          O índice está vazio: recolha na secção <span className="text-foreground">Recolha</span> e importe em
          <span className="text-foreground"> Execuções</span>.
        </Card>
      ) : null}
    </div>
  );
}
