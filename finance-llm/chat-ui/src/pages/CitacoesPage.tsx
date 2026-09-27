/**
 * Citações e notificações editais — CITIUS / Ministério da Justiça.
 *
 * Recolhe a lista de resultados da pesquisa do portal
 * (`consultascitedital.aspx`), grava-a em **JSON** (`data/citacoes/runs`) e
 * importa-a para o Elasticsearch (`finance_citacoes_edital`), onde fica
 * pesquisável.
 *
 * São as citações e notificações **editais** (aquelas em que o citando não foi
 * encontrado e é chamado por édito): tribunal, ato, referência, processo,
 * espécie, data, intervenientes (exequente, executado, réu, requerido, agente de
 * execução, …) e o documento em PDF.
 *
 * Secções
 * - **Pesquisa** — procurar no índice por texto, nome do interveniente, papel,
 *   tribunal, tipo e datas; as facetas filtram com um clique.
 * - **Recolha** — definir os critérios (nome do interveniente, tribunal e
 *   «últimos N meses» — 6 por omissão) e recolher; o progresso é acompanhado
 *   página a página.
 * - **Execuções** — ficheiros JSON gravados em `data/citacoes/runs`, com a
 *   importação para o Elasticsearch e a remoção.
 * - **Estado** — volumetria do índice e distribuições (tribunais, tipos, meses).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  FileJson,
  Gavel,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import {
  deleteCitacoesRun,
  getCitacoesJob,
  getCitacoesMeta,
  getCitacoesOptions,
  getCitacoesStatus,
  ingestCitacoes,
  listCitacoesJobs,
  listCitacoesRuns,
  searchCitacoes,
  startCitacoesCollect,
  stopCitacoesJob,
  type CitacoesCollectCriteria,
  type CitacoesEdito,
  type CitacoesFacet,
  type CitacoesJob,
  type CitacoesMeta,
  type CitacoesOptions,
  type CitacoesRun,
  type CitacoesSearchParams,
  type CitacoesSearchResult,
  type CitacoesStatus,
} from "../citacoesApi";

const numberFormat = new Intl.NumberFormat("pt-PT");
const dateFormat = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });

type Section = "pesquisa" | "recolha" | "execucoes" | "estado";

const SECTIONS: { id: Section; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "pesquisa", label: "Pesquisa", hint: "Procurar nos éditos indexados", icon: <Search size={14} /> },
  { id: "recolha", label: "Recolha", hint: "Recolher a lista do portal para JSON e importar", icon: <Play size={14} /> },
  { id: "execucoes", label: "Execuções", hint: "Ficheiros gravados e importação", icon: <FileJson size={14} /> },
  { id: "estado", label: "Estado", hint: "Volumetria e distribuições do índice", icon: <Database size={14} /> },
];

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
  facet?: CitacoesFacet[];
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

/** Cartão de um édito de citação/notificação. */
function EditoCard({ item }: { item: CitacoesEdito }) {
  const intervenientes = item.intervenientes ?? [];
  const [open, setOpen] = useState(false);
  const visiveis = open ? intervenientes : intervenientes.slice(0, 4);
  const cor =
    item.tipo === "Notificação"
      ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
      : "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${cor}`}>{item.tipo || "Édito"}</span>
            <span className="text-sm font-semibold text-foreground">{item.citado || item.referencia}</span>
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
        {item.juizo ? (
          <div className="truncate" title={item.juizo}>
            <span className="text-muted-foreground/70">Juízo:</span> {item.juizo}
          </div>
        ) : null}
        {item.tribunal_comarca ? (
          <div>
            <span className="text-muted-foreground/70">Comarca:</span> {item.tribunal_comarca}
          </div>
        ) : null}
      </div>

      {visiveis.length > 0 ? (
        <div className="mt-2 space-y-1">
          {visiveis.map((pessoa, index) => (
            <div key={`${pessoa.papel}-${index}`} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate">
                <span className="text-muted-foreground/70">{pessoa.papel}:</span> {pessoa.nome}
              </span>
              {pessoa.nif ? (
                <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {pessoa.nif}
                </span>
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

      {item.documento_url ? (
        <div className="mt-2">
          <a
            href={item.documento_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            title="Abre o PDF no portal do CITIUS (a ligação está ligada à sessão da recolha)"
          >
            <Download size={11} /> documento
          </a>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------- página */

export default function CitacoesPage({ section = "pesquisa" }: { section?: Section }) {
  const [active, setActive] = useState<Section>(section);
  const [meta, setMeta] = useState<CitacoesMeta | null>(null);
  const [options, setOptions] = useState<CitacoesOptions | null>(null);
  const [status, setStatus] = useState<CitacoesStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getCitacoesStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    getCitacoesMeta().then(setMeta).catch(() => undefined);
    getCitacoesOptions().then(setOptions).catch(() => undefined);
    void refreshStatus();
  }, [refreshStatus]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-amber-200 via-amber-500 to-rose-600 p-2 text-amber-950">
          <Gavel size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Citações e notificações editais</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {meta?.source_label ?? "Citação e Notificação Edital — CITIUS / Ministério da Justiça"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> ·{" "}
              {numberFormat.format(status?.documents ?? 0)} éditos
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
                ? "bg-amber-400/15 text-amber-200"
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
            <button
              type="button"
              className="opacity-70 hover:opacity-100"
              onClick={() => {
                setError(null);
                setNotice(null);
              }}
            >
              ×
            </button>
          </div>
        )}

        {active === "pesquisa" && <SearchSection meta={meta} onError={setError} />}
        {active === "recolha" && (
          <RecolhaSection
            meta={meta}
            options={options}
            onDone={(message) => {
              setNotice(message);
              void refreshStatus();
            }}
            onError={setError}
          />
        )}
        {active === "execucoes" && (
          <ExecucoesSection
            onDone={(message) => {
              setNotice(message);
              void refreshStatus();
            }}
            onError={setError}
          />
        )}
        {active === "estado" && <EstadoSection status={status} onRefresh={refreshStatus} />}
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- pesquisa */

function SearchSection({ meta, onError }: { meta: CitacoesMeta | null; onError: (message: string) => void }) {
  const [params, setParams] = useState<CitacoesSearchParams>({ size: 20, from: 0 });
  const [result, setResult] = useState<CitacoesSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState({ q: "", nome: "", citado: "", processo: "", tribunal: "", ato: "", tipo: "" });

  const run = useCallback(
    async (next: CitacoesSearchParams) => {
      setLoading(true);
      try {
        setResult(await searchCitacoes(next));
      } catch (err) {
        onError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [onError],
  );

  useEffect(() => {
    void run(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const apply = (patch: Partial<CitacoesSearchParams>) => {
    const next: CitacoesSearchParams = { ...params, ...patch, from: patch.from ?? 0 };
    Object.keys(next).forEach((key) => {
      const value = (next as Record<string, unknown>)[key];
      if (value === "" || value === undefined || value === null) delete (next as Record<string, unknown>)[key];
    });
    next.size = params.size ?? 20;
    setParams(next);
    void run(next);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    apply({
      q: draft.q || undefined,
      nome: draft.nome || undefined,
      citado: draft.citado || undefined,
      processo: draft.processo || undefined,
      tribunal: draft.tribunal || undefined,
      ato: draft.ato || undefined,
      tipo: draft.tipo || undefined,
    });
  };

  const clear = () => {
    setDraft({ q: "", nome: "", citado: "", processo: "", tribunal: "", ato: "", tipo: "" });
    setParams({ size: 20, from: 0 });
    void run({ size: 20, from: 0 });
  };

  const total = result?.total ?? 0;
  const size = params.size ?? 20;
  const page = Math.floor((params.from ?? 0) / size) + 1;
  const pages = Math.max(1, Math.ceil(total / size));
  const facets = result?.facets;

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <Card className="space-y-3 self-start">
        <form className="space-y-3" onSubmit={submit}>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Texto livre</label>
            <input
              value={draft.q}
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
              placeholder="interveniente, tribunal, processo, ato…"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Interveniente (qualquer papel)</label>
            <input
              value={draft.nome}
              onChange={(event) => setDraft({ ...draft, nome: event.target.value })}
              placeholder="ex.: Montepio"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Citado / executado</label>
            <input
              value={draft.citado}
              onChange={(event) => setDraft({ ...draft, citado: event.target.value })}
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Processo</label>
              <input
                value={draft.processo}
                onChange={(event) => setDraft({ ...draft, processo: event.target.value })}
                placeholder="6438/19.2T8LSB"
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo</label>
              <select
                value={draft.tipo}
                onChange={(event) => setDraft({ ...draft, tipo: event.target.value })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              >
                <option value="">Todos</option>
                <option value="Citação">Citação</option>
                <option value="Notificação">Notificação</option>
                <option value="Anúncio">Anúncio</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tribunal</label>
            <input
              value={draft.tribunal}
              onChange={(event) => setDraft({ ...draft, tribunal: event.target.value })}
              placeholder="texto parcial (ex.: Lisboa)"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Ato</label>
            <input
              value={draft.ato}
              onChange={(event) => setDraft({ ...draft, ato: event.target.value })}
              placeholder="ex.: Citação Edital"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">De</label>
              <input
                type="date"
                value={params.data_from ?? ""}
                onChange={(event) => apply({ data_from: event.target.value || undefined })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Até</label>
              <input
                type="date"
                value={params.data_to ?? ""}
                onChange={(event) => apply({ data_to: event.target.value || undefined })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-[11.5px] text-amber-100 hover:bg-amber-500/30"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />} Pesquisar
            </button>
            <button
              type="button"
              onClick={clear}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              Limpar
            </button>
          </div>
        </form>
      </Card>

      <div className="space-y-3">
        <Card className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11.5px] text-muted-foreground">
              <span className="font-semibold text-foreground">{numberFormat.format(total)}</span> éditos
              {result?.error ? <span className="ml-2 text-amber-300">{result.error}</span> : null}
            </div>
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => apply({ from: Math.max(0, (page - 2) * size) })}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 disabled:opacity-40"
              >
                anterior
              </button>
              <span>
                página {page} de {pages}
              </span>
              <button
                type="button"
                disabled={page >= pages}
                onClick={() => apply({ from: page * size })}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 disabled:opacity-40"
              >
                seguinte
              </button>
              <select
                value={size}
                onChange={(event) => apply({ size: Number(event.target.value), from: 0 })}
                className="rounded-lg border border-white/10 bg-black/20 px-2 py-1"
              >
                {[10, 20, 50, 100].map((option) => (
                  <option key={option} value={option}>
                    {option}/página
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Facets title="Tipo" facet={facets?.tipo} active={params.tipo} onPick={(key) => apply({ tipo: key })} />
            <Facets
              title="Papel do interveniente"
              facet={facets?.papel}
              active={params.papel}
              onPick={(key) => apply({ papel: key })}
            />
            <Facets
              title="Comarca"
              facet={facets?.tribunal_comarca}
              active={params.tribunal_comarca}
              onPick={(key) => apply({ tribunal_comarca: key })}
            />
            <Facets title="Ato" facet={facets?.ato} active={params.ato} onPick={(key) => apply({ ato: key })} />
            <Facets
              title="Espécie"
              facet={facets?.especie}
              active={params.especie}
              onPick={(key) => apply({ especie: key })}
            />
            <Facets title="Ano" facet={facets?.ano} active={undefined} onPick={(key) => apply({ data_from: `${key}-01-01`, data_to: `${key}-12-31` })} />
          </div>
        </Card>

        {loading && !result ? (
          <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> a pesquisar…
          </div>
        ) : null}

        <div className="grid gap-2 xl:grid-cols-2">
          {(result?.items ?? []).map((item) => (
            <EditoCard key={item.pub_id} item={item} />
          ))}
        </div>

        {!loading && total === 0 ? (
          <Card className="text-[11.5px] text-muted-foreground">
            Sem resultados no índice. {meta ? "Recolha primeiro na secção «Recolha»." : null}
          </Card>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- recolha */

function RecolhaSection({
  meta,
  options,
  onDone,
  onError,
}: {
  meta: CitacoesMeta | null;
  options: CitacoesOptions | null;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [tribunal, setTribunal] = useState("");
  const [dias, setDias] = useState("todos");
  const [meses, setMeses] = useState<number>(meta?.default_months ?? 6);
  const [maxPages, setMaxPages] = useState(200);
  const [indexar, setIndexar] = useState(true);
  const [job, setJob] = useState<CitacoesJob | null>(null);
  const [jobs, setJobs] = useState<CitacoesJob[]>([]);
  const [aRecolher, setARecolher] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (meta?.default_months) setMeses(meta.default_months);
  }, [meta?.default_months]);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs((await listCitacoesJobs()).jobs);
    } catch {
      /* sem sessão ou API indisponível */
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  const watch = useCallback(
    (id: string) => {
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        try {
          const current = await getCitacoesJob(id);
          setJob(current);
          if (current.finished) {
            if (timer.current) window.clearInterval(timer.current);
            timer.current = null;
            setARecolher(false);
            void refreshJobs();
            if (current.state === "error") {
              onError(current.error || "A recolha falhou.");
            } else if (current.state === "empty") {
              onDone(`«${current.criteria?.nome}»: o portal não devolveu éditos nos últimos ${current.criteria?.meses ?? 6} meses.`);
            } else {
              onDone(
                `${numberFormat.format(current.collected ?? 0)} éditos recolhidos` +
                  (current.indexed !== undefined ? ` e ${numberFormat.format(current.indexed)} importados` : "") +
                  (current.run_id ? ` (${current.run_id}).` : "."),
              );
            }
          }
        } catch (err) {
          if (timer.current) window.clearInterval(timer.current);
          timer.current = null;
          setARecolher(false);
          onError(err instanceof Error ? err.message : String(err));
        }
      }, 1200);
    },
    [onDone, onError, refreshJobs],
  );

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  const start = async () => {
    if (nome.trim().length < 2) {
      onError("Indique o nome do interveniente a pesquisar (mínimo 2 caracteres).");
      return;
    }
    const criteria: CitacoesCollectCriteria = {
      nome: nome.trim(),
      tribunal: tribunal || undefined,
      dias,
      meses,
      max_pages: maxPages,
      index: indexar,
    };
    try {
      const created = await startCitacoesCollect(criteria);
      setJob(created);
      setARecolher(true);
      watch(created.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  const stop = async () => {
    if (!job) return;
    try {
      await stopCitacoesJob(job.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  const corte = useMemo(() => {
    if (!meses) return "sem corte (todos os éditos)";
    const hoje = new Date();
    const alvo = new Date(hoje.getFullYear(), hoje.getMonth() - meses, Math.min(hoje.getDate(), 28));
    return alvo.toLocaleDateString("pt-PT");
  }, [meses]);

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      <Card className="space-y-3 self-start">
        <div className="text-[11.5px] font-semibold text-foreground">Recolher éditos do portal</div>
        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
            Nome do interveniente <span className="text-amber-300">*</span>
          </label>
          <input
            value={nome}
            onChange={(event) => setNome(event.target.value)}
            placeholder="ex.: Montepio, Silva, 123456789"
            autoComplete="off"
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            A consulta do CITIUS só pesquisa pelo nome do interveniente (não aceita NIF/NIPC).
          </p>
        </div>

        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tribunal/serviço</label>
          <select
            value={tribunal}
            onChange={(event) => setTribunal(event.target.value)}
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
          >
            <option value="">- Todos os Serviços -</option>
            {(options?.tribunais ?? []).slice(1).map((option) => (
              <option key={option.value} value={option.label}>
                {option.label}
              </option>
            ))}
          </select>
          {options?.error ? <p className="mt-1 text-[10px] text-amber-300">{options.error}</p> : null}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Janela do portal</label>
            <select
              value={dias}
              onChange={(event) => setDias(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            >
              {(options?.dias ?? [
                { value: "15", label: "Últimos 15 dias" },
                { value: "30", label: "Últimos 30 dias" },
                { value: "todos", label: "Todos" },
              ]).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Últimos (meses)</label>
            <input
              type="number"
              min={0}
              max={meta?.max_months ?? 120}
              value={meses}
              onChange={(event) => setMeses(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
        </div>
        <p className="text-[10px] text-muted-foreground">
          Corte: <span className="text-foreground">{corte}</span> · os resultados vêm por data descendente, pelo que a
          recolha para sozinha ao passar este limite (0 = tudo).
        </p>

        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Máximo de páginas</label>
          <input
            type="number"
            min={1}
            max={2000}
            value={maxPages}
            onChange={(event) => setMaxPages(Number(event.target.value))}
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">10 éditos por página (rede: ~1,2 s por pedido).</p>
        </div>

        <label className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <input type="checkbox" checked={indexar} onChange={(event) => setIndexar(event.target.checked)} />
          Importar para o Elasticsearch no fim
        </label>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={start}
            disabled={aRecolher}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-[11.5px] text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
          >
            {aRecolher ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} Recolher
          </button>
          {aRecolher ? (
            <button
              type="button"
              onClick={stop}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <Square size={12} /> Parar
            </button>
          ) : null}
        </div>
      </Card>

      <div className="space-y-3">
        {job ? (
          <Card className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[11.5px] font-semibold text-foreground">
                {job.criteria?.nome ? `«${job.criteria.nome}»` : "Recolha"} · {job.stage ?? job.state}
              </div>
              <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                {job.state}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              <Stat label="Recolhidos" value={numberFormat.format(job.collected ?? 0)} />
              <Stat label="Declarados" value={numberFormat.format(job.declared_total ?? 0)} hint="total no portal" />
              <Stat label="Páginas" value={numberFormat.format(job.pages ?? 0)} hint={job.declared_pages ? `de ~${job.declared_pages}` : undefined} />
              <Stat label="Importados" value={numberFormat.format(job.indexed ?? 0)} />
            </div>
            <div className="text-[10.5px] text-muted-foreground">
              {job.run_id ? (
                <>
                  ficheiro <span className="font-mono text-foreground">{job.run_id}</span>
                </>
              ) : null}
              {job.older_than_cutoff ? ` · ${job.older_than_cutoff} éditos anteriores ao corte ignorados` : ""}
              {job.skipped_existing ? ` · ${job.skipped_existing} já estavam no índice` : ""}
              {job.error ? <span className="text-amber-300"> · {job.error}</span> : null}
            </div>
            {job.errors && job.errors.length > 0 ? (
              <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-2 py-1 text-[10.5px] text-amber-200">
                {job.errors.join(" · ")}
              </div>
            ) : null}
          </Card>
        ) : null}

        <Card className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[11.5px] font-semibold text-foreground">Recolhas recentes</div>
            <button
              type="button"
              onClick={() => void refreshJobs()}
              className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <RefreshCw size={11} /> atualizar
            </button>
          </div>
          {jobs.length === 0 ? (
            <div className="text-[11px] text-muted-foreground">Ainda não há recolhas nesta sessão da API.</div>
          ) : (
            <div className="space-y-1">
              {jobs.slice(0, 8).map((item) => (
                <div
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[11px]"
                >
                  <span className="truncate">
                    <span className="text-foreground">{item.criteria?.nome ?? "—"}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {item.criteria?.meses ?? 6} meses · {item.state}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    {numberFormat.format(item.collected ?? 0)} éditos
                    {item.indexed ? ` · ${numberFormat.format(item.indexed)} indexados` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="space-y-1 text-[11px] text-muted-foreground">
          <div className="text-[11.5px] font-semibold text-foreground">Como funciona</div>
          <p>
            1. A recolha pesquisa o portal (<span className="font-mono">{meta?.source_url ?? "consultascitedital.aspx"}</span>)
            pelo nome e percorre a lista página a página, gravando o JSON em{" "}
            <span className="font-mono text-foreground">data/citacoes/runs</span>.
          </p>
          <p>
            2. No fim (se «Importar» estiver ligado) o JSON é indexado em{" "}
            <span className="font-mono text-foreground">{meta?.index ?? "finance_citacoes_edital"}</span>. Reimportar a
            mesma recolha não duplica: os éditos já existentes são ignorados.
          </p>
          <p>3. Cada édito traz o documento em PDF (ligação na secção Pesquisa).</p>
        </Card>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- execuções */

function ExecucoesSection({
  onDone,
  onError,
}: {
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [runs, setRuns] = useState<CitacoesRun[]>([]);
  const [directory, setDirectory] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listCitacoesRuns(100);
      setRuns(payload.items ?? []);
      setDirectory(payload.directory ?? "");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const importRun = async (runId: string, updateExisting = false) => {
    setBusy(runId);
    try {
      const res = await ingestCitacoes({ run_id: runId, update_existing: updateExisting });
      onDone(
        `${runId}: ${numberFormat.format(res.indexed_count ?? 0)} éditos indexados` +
          (res.skipped_existing ? ` (${res.skipped_existing} já existiam)` : "") +
          (res.index_total ? ` · índice com ${numberFormat.format(res.index_total)} documentos` : "") +
          ".",
      );
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (runId: string) => {
    setBusy(runId);
    try {
      await deleteCitacoesRun(runId);
      onDone(`Recolha «${runId}» apagada do disco.`);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <Card className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11.5px] text-muted-foreground">
          {numberFormat.format(runs.length)} recolhas em <span className="font-mono text-foreground">{directory || "data/citacoes/runs"}</span>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} atualizar
        </button>
      </Card>

      {runs.length === 0 ? (
        <Card className="text-[11.5px] text-muted-foreground">Sem ficheiros de recolha no disco.</Card>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <Card key={run.run_id} className="space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-[12px] font-semibold text-foreground">
                    {String(run.criteria?.nome ?? run.run_id)}
                    <span className="ml-2 font-normal text-muted-foreground">
                      {run.criteria?.meses ? `últimos ${run.criteria.meses} meses` : "tudo"}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[10.5px] text-muted-foreground">{run.run_id}</div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void importRun(run.run_id)}
                    className="inline-flex items-center gap-1 rounded-lg bg-amber-500/20 px-2 py-1 text-[10.5px] text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
                  >
                    <Upload size={11} /> importar
                  </button>
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void importRun(run.run_id, true)}
                    title="Reescreve no índice os éditos que já existem"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
                  >
                    reimportar
                  </button>
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void remove(run.run_id)}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-50"
                  >
                    <Trash2 size={11} /> apagar
                  </button>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-5">
                <Stat label="Recolhidos" value={numberFormat.format(run.collected ?? 0)} />
                <Stat label="Declarados" value={numberFormat.format(run.declared_total ?? 0)} />
                <Stat label="Páginas" value={numberFormat.format(run.pages ?? 0)} />
                <Stat label="No índice" value={numberFormat.format(run.index_count ?? 0)} />
                <Stat label="Duração" value={run.duration_s ? `${run.duration_s}s` : "—"} />
              </div>
              <div className="text-[10.5px] text-muted-foreground">
                {formatDateTime(run.created_at)}
                {run.older_than_cutoff ? ` · ${run.older_than_cutoff} anteriores ao corte` : ""}
                {run.indexed ? ` · última importação: ${numberFormat.format(run.indexed)} documentos` : ""}
                {run.stopped ? " · parada pelo utilizador" : ""}
              </div>
              {run.errors && run.errors.length > 0 ? (
                <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-2 py-1 text-[10.5px] text-amber-200">
                  {run.errors.join(" · ")}
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ estado */

function EstadoSection({ status, onRefresh }: { status: CitacoesStatus | null; onRefresh: () => void }) {
  const mesMax = useMemo(() => {
    const buckets = status?.by_mes ?? [];
    const max = buckets.reduce((acc, item) => Math.max(acc, item.count), 0);
    return { max, recentes: buckets.slice(-18) };
  }, [status?.by_mes]);

  if (!status) {
    return (
      <Card className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> a carregar o estado…
      </Card>
    );
  }

  if (status.error) {
    return <Card className="text-[11.5px] text-amber-200">Elasticsearch indisponível: {status.error}</Card>;
  }

  return (
    <div className="space-y-3">
      <Card className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11.5px] text-muted-foreground">
          índice <span className="font-mono text-foreground">{status.index}</span>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
        >
          <RefreshCw size={11} /> atualizar
        </button>
      </Card>

      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Documentos" value={numberFormat.format(status.documents ?? 0)} />
        <Stat label="Referências" value={numberFormat.format(status.referencias ?? 0)} />
        <Stat label="Processos" value={numberFormat.format(status.processos ?? 0)} />
        <Stat label="Tribunais" value={numberFormat.format(status.tribunais ?? 0)} />
        <Stat label="Citados" value={numberFormat.format(status.citados ?? 0)} />
        <Stat label="Com documento" value={numberFormat.format(status.with_documento ?? 0)} />
      </div>

      <Card className="space-y-1 text-[11px] text-muted-foreground">
        <div>
          <span className="text-muted-foreground/70">Publicações de</span>{" "}
          <span className="text-foreground">{formatDate(status.min_date)}</span>{" "}
          <span className="text-muted-foreground/70">a</span>{" "}
          <span className="text-foreground">{formatDate(status.max_date)}</span>
        </div>
      </Card>

      <Card className="space-y-2">
        <div className="text-[11.5px] font-semibold text-foreground">Por mês</div>
        {mesMax.max === 0 ? (
          <div className="text-[11px] text-muted-foreground">Sem dados.</div>
        ) : (
          <div className="flex items-end gap-1">
            {mesMax.recentes.map((item) => (
              <div key={item.key} className="flex-1" title={`${item.key}: ${item.count}`}>
                <div
                  className="rounded-t bg-amber-400/50"
                  style={{ height: `${Math.max(3, Math.round((item.count / mesMax.max) * 90))}px` }}
                />
                <div className="mt-1 rotate-45 text-[8.5px] text-muted-foreground">{item.key?.slice(2)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Tipo de édito</div>
          {(status.by_tipo ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_tipo ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Papéis</div>
          {(status.by_papel ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_papel ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Comarcas</div>
          {(status.top_comarcas ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.top_comarcas ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Atos</div>
          {(status.top_actos ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.top_actos ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Tribunais</div>
          {(status.top_tribunais ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.top_tribunais ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
      </div>

      <Card className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Users size={13} /> Os papéis vêm dos intervenientes de cada édito; a pesquisa permite filtrar por papel e por nome
        do interveniente.
      </Card>
    </div>
  );
}
