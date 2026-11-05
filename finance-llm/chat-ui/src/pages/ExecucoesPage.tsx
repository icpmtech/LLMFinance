/**
 * Lista Pública de Execuções do CITIUS / Ministério da Justiça.
 *
 * Fonte: https://www.citius.mj.pt/portal/execucoes/ListaPublicaExecucoes.aspx
 *
 * Secções
 * - **Pesquisa** — procurar no índice por texto, nome do executado, processo,
 *   tribunal, comarca, agente de execução, estado, datas e valor da execução.
 * - **Recolha** — recolha completa por letra do alfabeto ou pesquisa nomeada;
 *   o progresso é acompanhado em tempo real.
 * - **Execuções** — ficheiros JSON gravados em `data/execucoes/runs`, com
 *   importação para o Elasticsearch e remoção.
 * - **Estado** — volumetria do índice e distribuições (estado, comarca,
 *   tribunal, agente, datas, valores).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  FileJson,
  Gavel,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import {
  deleteExecucoesRun,
  getExecucoesJob,
  getExecucoesMeta,
  getExecucoesOptions,
  getExecucoesStatus,
  ingestExecucoes,
  listExecucoesJobs,
  listExecucoesRuns,
  searchExecucoes,
  startExecucoesCollect,
  stopExecucoesJob,
  type Execucao,
  type ExecucaoCollectCriteria,
  type ExecucaoFacet,
  type ExecucaoJob,
  type ExecucaoMeta,
  type ExecucaoOptions,
  type ExecucaoRun,
  type ExecucaoSearchParams,
  type ExecucaoSearchResult,
  type ExecucaoStatus,
} from "../execucoesApi";
import { formatMoney } from "../components/graph/graphStudio";

const numberFormat = new Intl.NumberFormat("pt-PT");
const dateFormat = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });

type Section = "pesquisa" | "recolha" | "execucoes" | "estado" | "logs";

const SECTIONS: { id: Section; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "pesquisa", label: "Pesquisa", hint: "Procurar execuções indexadas", icon: <Search size={14} /> },
  { id: "recolha", label: "Recolha", hint: "Recolher a lista do portal para JSON", icon: <Play size={14} /> },
  { id: "execucoes", label: "Execuções", hint: "Ficheiros gravados e importação", icon: <FileJson size={14} /> },
  { id: "estado", label: "Estado", hint: "Volumetria e distribuições do índice", icon: <Database size={14} /> },
  { id: "logs", label: "Logs", hint: "Registo de atividade das recolhas", icon: <RefreshCw size={14} /> },
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
  facet?: ExecucaoFacet[];
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
                ? "border-rose-400/40 bg-rose-400/15 text-rose-200"
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

/** Cartão de uma execução. */
function ExecucaoCard({ item }: { item: Execucao }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-0.5 text-[10.5px] text-rose-200">
              {item.extra?.estado || "Execução"}
            </span>
            <span className="text-sm font-semibold text-foreground">{item.nome_executado}</span>
            {item.extra?.valor_execucao ? (
              <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10.5px] text-emerald-200">
                {formatMoney(item.extra.valor_execucao)}
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {item.extra?.tribunal || item.extra?.comarca || "—"} · {item.numero_processo || "—"}
          </div>
        </div>
        <div className="text-right text-[11px] text-muted-foreground">
          <div className="font-medium text-foreground">{formatDate(item.data_entrada)}</div>
          <div>{item.extra?.agente_execucao || "—"}</div>
        </div>
      </div>

      <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
        {item.extra?.comarca ? (
          <div>
            <span className="text-muted-foreground/70">Comarca:</span> {item.extra.comarca}
          </div>
        ) : null}
        {item.extra?.unidade_organica ? (
          <div>
            <span className="text-muted-foreground/70">Unidade orgânica:</span> {item.extra.unidade_organica}
          </div>
        ) : null}
        {item.extra?.agente_execucao ? (
          <div>
            <span className="text-muted-foreground/70">Agente execução:</span> {item.extra.agente_execucao}
          </div>
        ) : null}
      </div>

      <div className="mt-2 flex items-center gap-2 text-[10.5px] text-muted-foreground">
        <span className="font-mono text-foreground">{item.pub_id.slice(0, 8)}</span>
        {item.run_id ? <span className="truncate">· {item.run_id}</span> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ página */

export default function ExecucoesPage() {
  const [active, setActive] = useState<Section>("pesquisa");
  const [meta, setMeta] = useState<ExecucaoMeta | null>(null);
  const [options, setOptions] = useState<ExecucaoOptions | null>(null);
  const [status, setStatus] = useState<ExecucaoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getExecucoesStatus());
    } catch {
      /* Elasticsearch pode não estar disponível */
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [m, o] = await Promise.all([getExecucoesMeta(), getExecucoesOptions()]);
        setMeta(m);
        setOptions(o);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    void refreshStatus();
  }, [refreshStatus]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-red-200 via-rose-500 to-slate-700 p-2 text-rose-950">
          <Gavel size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Lista Pública de Execuções</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {meta?.source_label ?? "Lista Pública de Execuções — CITIUS"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> ·{" "}
              {numberFormat.format(status?.documents ?? 0)} registos
            </span>
          ) : null}
          {meta?.source_url ? (
            <a
              href={meta.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <ExternalLink size={10} /> portal
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
                ? "bg-rose-400/15 text-rose-200"
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

        {active === "pesquisa" && <SearchSection onError={setError} />}
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
        {active === "logs" && <LogsSection />}
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- pesquisa */

function SearchSection({ onError }: { onError: (message: string) => void }) {
  const [params, setParams] = useState<ExecucaoSearchParams>({ size: 20, from: 0 });
  const [result, setResult] = useState<ExecucaoSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState({
    q: "",
    nome_executado: "",
    numero_processo: "",
    tribunal: "",
    comarca: "",
    unidade_organica: "",
    agente_execucao: "",
    estado: "",
    data_from: "",
    data_to: "",
    valor_min: "",
    valor_max: "",
  });

  const run = useCallback(
    async (next: ExecucaoSearchParams) => {
      setLoading(true);
      try {
        setResult(await searchExecucoes(next));
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

  const apply = (patch: Partial<ExecucaoSearchParams>) => {
    const next: ExecucaoSearchParams = { ...params, ...patch, from: patch.from ?? 0 };
    Object.keys(next).forEach((key) => {
      const value = (next as Record<string, unknown>)[key];
      if (value === "" || value === undefined || value === null) delete (next as Record<string, unknown>)[key];
    });
    next.size = params.size ?? 20;
    setParams(next);
    void run(next);
  };

  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    const patch: Partial<ExecucaoSearchParams> = {
      q: draft.q || undefined,
      nome_executado: draft.nome_executado || undefined,
      numero_processo: draft.numero_processo || undefined,
      tribunal: draft.tribunal || undefined,
      comarca: draft.comarca || undefined,
      unidade_organica: draft.unidade_organica || undefined,
      agente_execucao: draft.agente_execucao || undefined,
      estado: draft.estado || undefined,
      data_from: draft.data_from || undefined,
      data_to: draft.data_to || undefined,
      valor_min: draft.valor_min ? Number(draft.valor_min) : undefined,
      valor_max: draft.valor_max ? Number(draft.valor_max) : undefined,
    };
    apply(patch);
  };

  const clear = () => {
    setDraft({
      q: "",
      nome_executado: "",
      numero_processo: "",
      tribunal: "",
      comarca: "",
      unidade_organica: "",
      agente_execucao: "",
      estado: "",
      data_from: "",
      data_to: "",
      valor_min: "",
      valor_max: "",
    });
    apply({ size: 20, from: 0 });
  };

  const pageCount = useMemo(() => Math.ceil((result?.total ?? 0) / (params.size ?? 20)), [result, params.size]);
  const currentPage = useMemo(() => Math.floor((params.from ?? 0) / (params.size ?? 20)) + 1, [params]);

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card className="space-y-3 self-start">
        <form className="space-y-3" onSubmit={submit}>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Texto livre</label>
            <input
              value={draft.q}
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
              placeholder="nome, processo, tribunal, agente…"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Nome do executado</label>
            <input
              value={draft.nome_executado}
              onChange={(event) => setDraft({ ...draft, nome_executado: event.target.value })}
              placeholder="ex.: Silva"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Processo</label>
              <input
                value={draft.numero_processo}
                onChange={(event) => setDraft({ ...draft, numero_processo: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Estado</label>
              <input
                value={draft.estado}
                onChange={(event) => setDraft({ ...draft, estado: event.target.value })}
                placeholder="ex.: Inexistência de bens"
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tribunal</label>
              <input
                value={draft.tribunal}
                onChange={(event) => setDraft({ ...draft, tribunal: event.target.value })}
                placeholder="texto parcial"
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Comarca</label>
              <input
                value={draft.comarca}
                onChange={(event) => setDraft({ ...draft, comarca: event.target.value })}
                placeholder="exata"
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Unidade orgânica</label>
              <input
                value={draft.unidade_organica}
                onChange={(event) => setDraft({ ...draft, unidade_organica: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Agente execução</label>
              <input
                value={draft.agente_execucao}
                onChange={(event) => setDraft({ ...draft, agente_execucao: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Valor mínimo (€)</label>
              <input
                type="number"
                min={0}
                step="1000"
                value={draft.valor_min}
                onChange={(event) => setDraft({ ...draft, valor_min: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Valor máximo (€)</label>
              <input
                type="number"
                min={0}
                step="1000"
                value={draft.valor_max}
                onChange={(event) => setDraft({ ...draft, valor_max: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data entrada de</label>
              <input
                type="date"
                value={draft.data_from}
                onChange={(event) => setDraft({ ...draft, data_from: event.target.value })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data entrada até</label>
              <input
                type="date"
                value={draft.data_to}
                onChange={(event) => setDraft({ ...draft, data_to: event.target.value })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/20 px-3 py-1.5 text-[11.5px] text-rose-100 hover:bg-rose-500/30"
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

        <div className="space-y-2 pt-2">
          <Facets
            title="Estado"
            facet={result?.facets?.estado}
            active={params.estado}
            onPick={(key) => apply({ estado: key })}
          />
          <Facets
            title="Comarca"
            facet={result?.facets?.comarca}
            active={params.comarca}
            onPick={(key) => apply({ comarca: key })}
          />
          <Facets
            title="Tribunal"
            facet={result?.facets?.tribunal}
            active={params.tribunal}
            onPick={(key) => apply({ tribunal: key })}
          />
          <Facets
            title="Agente execução"
            facet={result?.facets?.agente_execucao}
            active={params.agente_execucao}
            onPick={(key) => apply({ agente_execucao: key })}
          />
        </div>
      </Card>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11.5px] text-muted-foreground">
            {result ? (
              <>
                <span className="font-semibold text-foreground">{numberFormat.format(result.total ?? 0)}</span> registos
                {result.valor_total !== undefined ? ` · valor total ${formatMoney(result.valor_total)}` : ""}
              </>
            ) : null}
          </div>
          {result && pageCount > 1 ? (
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={currentPage <= 1}
                onClick={() => apply({ from: (params.from ?? 0) - (params.size ?? 20) })}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
              >
                ‹
              </button>
              <span className="text-[11px] text-muted-foreground">
                {currentPage} / {pageCount}
              </span>
              <button
                type="button"
                disabled={currentPage >= pageCount}
                onClick={() => apply({ from: (params.from ?? 0) + (params.size ?? 20) })}
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
              >
                ›
              </button>
            </div>
          ) : null}
        </div>

        {result?.error ? <Card className="text-[11px] text-amber-200">{result.error}</Card> : null}

        <div className="space-y-2">
          {result?.items.map((item) => (
            <ExecucaoCard key={item.pub_id} item={item} />
          ))}
          {result && result.items.length === 0 ? (
            <Card className="text-[11px] text-muted-foreground">Nenhum registo encontrado para os filtros atuais.</Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- recolha */

function RecolhaSection({
  meta,
  options,
  onDone,
  onError,
}: {
  meta: ExecucaoMeta | null;
  options: ExecucaoOptions | null;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [documento, setDocumento] = useState("");
  const [tipoDocumento, setTipoDocumento] = useState("");
  const [processo, setProcesso] = useState("");
  const [dias, setDias] = useState("todos");
  const [letras, setLetras] = useState("");
  const [maxPages, setMaxPages] = useState(2000);
  const [maxItems, setMaxItems] = useState("");
  const [minInterval, setMinInterval] = useState(1.5);
  const [proxy, setProxy] = useState("");
  const [indexar, setIndexar] = useState(true);
  const [aRecolher, setARecolher] = useState(false);
  const [job, setJob] = useState<ExecucaoJob | null>(null);
  const [jobs, setJobs] = useState<ExecucaoJob[]>([]);
  const timer = useRef<number | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs((await listExecucoesJobs()).jobs);
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
          const current = await getExecucoesJob(id);
          setJob(current);
          if (current.finished) {
            if (timer.current) window.clearInterval(timer.current);
            timer.current = null;
            setARecolher(false);
            void refreshJobs();
            if (current.state === "error") {
              onError(current.error || "A recolha falhou.");
            } else if (current.state === "empty") {
              onDone("Não foram encontrados registos para os critérios indicados.");
            } else {
              onDone(
                `${numberFormat.format(current.collected ?? 0)} registos recolhidos` +
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
    const alvos = letras
      .split(",")
      .map((l) => l.trim().toUpperCase())
      .filter(Boolean);
    const criteria: ExecucaoCollectCriteria = {
      nome: nome || undefined,
      documento: documento || undefined,
      tipo_documento: tipoDocumento || undefined,
      numero_processo: processo || undefined,
      dias,
      letras: alvos.length ? alvos : undefined,
      max_pages_per_letra: maxPages,
      max_items: maxItems ? Number(maxItems) : undefined,
      min_interval: minInterval,
      proxy: proxy || undefined,
      index: indexar,
    };
    try {
      const created = await startExecucoesCollect(criteria);
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
      await stopExecucoesJob(job.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      <Card className="space-y-3 self-start">
        <div className="text-[11.5px] font-semibold text-foreground">Recolher execuções</div>

        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Nome do executado</label>
          <input
            value={nome}
            onChange={(event) => setNome(event.target.value)}
            placeholder="parcial (ex.: Silva) — omisso recolhe por alfabeto"
            autoComplete="off"
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Documento</label>
            <input
              value={documento}
              onChange={(event) => setDocumento(event.target.value)}
              placeholder="número"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo</label>
            <select
              value={tipoDocumento}
              onChange={(event) => setTipoDocumento(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            >
              <option value="">- Todos -</option>
              <option value="nif">NIF</option>
              <option value="bi">Bilhete de Identidade</option>
              <option value="passaporte">Passaporte</option>
              <option value="cartaconducao">Carta de Condução</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Processo</label>
            <input
              value={processo}
              onChange={(event) => setProcesso(event.target.value)}
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Atalho datas</label>
            <select
              value={dias}
              onChange={(event) => setDias(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            >
              <option value="todos">Todos</option>
              <option value="15">Últimos 15 dias</option>
              <option value="30">Últimos 30 dias</option>
            </select>
          </div>
        </div>

        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Letras do alfabeto (A-Z, separadas por vírgula)</label>
          <input
            value={letras}
            onChange={(event) => setLetras(event.target.value)}
            placeholder="ex.: A,B,C — omisso percorre A-Z + '0'"
            autoComplete="off"
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
          />
          {options?.alfabeto.length ? (
            <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
              Disponíveis:{" "}
              {options.alfabeto.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => setLetras(o.value)}
                  className="rounded border border-white/10 bg-white/5 px-1 py-0.5 hover:bg-white/10"
                >
                  {o.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Páginas por letra</label>
            <input
              type="number"
              min={1}
              max={5000}
              value={maxPages}
              onChange={(event) => setMaxPages(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Máximo de registos</label>
            <input
              type="number"
              min={1}
              value={maxItems}
              onChange={(event) => setMaxItems(event.target.value)}
              placeholder="ilimitado"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Intervalo (s)</label>
            <input
              type="number"
              min={0}
              max={30}
              step={0.1}
              value={minInterval}
              onChange={(event) => setMinInterval(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Proxy</label>
            <input
              value={proxy}
              onChange={(event) => setProxy(event.target.value)}
              placeholder="http://host:porta"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-rose-400/40"
            />
          </div>
        </div>

        <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <input
            type="checkbox"
            checked={indexar}
            onChange={(event) => setIndexar(event.target.checked)}
            autoComplete="off"
          />
          Importar para o Elasticsearch depois da recolha
        </label>

        <div className="flex items-center gap-2">
          {aRecolher ? (
            <button
              type="button"
              onClick={stop}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-400/30 bg-rose-400/15 px-3 py-1.5 text-[11.5px] text-rose-100 hover:bg-rose-400/25"
            >
              <Square size={13} /> Parar
            </button>
          ) : (
            <button
              type="button"
              onClick={start}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/20 px-3 py-1.5 text-[11.5px] text-rose-100 hover:bg-rose-500/30"
            >
              <Play size={13} /> Recolher
            </button>
          )}
        </div>
      </Card>

      <div className="space-y-3">
        {job ? (
          <Card className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-[11.5px] font-semibold text-foreground">{job.id}</div>
              <span
                className={`rounded-full border px-2 py-0.5 text-[10.5px] ${
                  job.state === "running"
                    ? "border-rose-400/30 bg-rose-400/15 text-rose-200"
                    : job.state === "error"
                      ? "border-amber-400/30 bg-amber-400/15 text-amber-200"
                      : "border-emerald-400/30 bg-emerald-400/15 text-emerald-200"
                }`}
              >
                {job.state} · {job.stage}
              </span>
            </div>
            <div className="text-[11px] text-muted-foreground">
              {job.letra ? `letra ${job.letra} · ` : ""}
              {job.declared_total !== undefined && job.declared_total !== null
                ? `${numberFormat.format(job.declared_total)} anunciados · `
                : ""}
              página {job.page ?? 0} / {job.pages ?? "?"}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {numberFormat.format(job.collected ?? 0)} recolhidos
              {job.indexed !== undefined ? ` · ${numberFormat.format(job.indexed)} indexados` : ""}
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
                    <span className="text-foreground">{item.criteria?.dias ?? "todos"}</span>
                    <span className="text-muted-foreground"> · {item.state}</span>
                  </span>
                  <span className="text-muted-foreground">
                    {numberFormat.format(item.collected ?? 0)} registos
                    {item.indexed ? ` · ${numberFormat.format(item.indexed)} indexados` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        {job?.logs && job.logs.length > 0 ? (
          <Card className="space-y-2">
            <div className="text-[11.5px] font-semibold text-foreground">Log da recolha</div>
            <div className="max-h-56 overflow-y-auto rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground">
              {job.logs.map((entry, idx) => (
                <div key={idx} className="flex gap-2 py-0.5">
                  <span className="shrink-0 text-white/30">{formatDateTime(entry.at)}</span>
                  <span className="text-foreground/80">{entry.message}</span>
                </div>
              ))}
            </div>
          </Card>
        ) : null}

        <Card className="space-y-1 text-[11px] text-muted-foreground">
          <div className="text-[11.5px] font-semibold text-foreground">Como funciona</div>
          <p>
            1. A recolha consulta o portal «Lista Pública de Execuções» do CITIUS, gravando o resultado em{" "}
            <span className="font-mono text-foreground">data/execucoes/runs</span>.
          </p>
          <p>
            2. Durante e no final da recolha (se «Importar» estiver ligado) os registos novos são indexados em{" "}
            <span className="font-mono text-foreground">{meta?.index ?? "finance_execucoes"}</span>;. Já existentes
            são ignorados.
          </p>
          <p>
            3. Sem critérios específicos, a recolha percorre A-Z (e a opção «0») para obter a lista completa. Cada letra
            corresponde ao dropdown do portal.
          </p>
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
  const [runs, setRuns] = useState<ExecucaoRun[]>([]);
  const [directory, setDirectory] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listExecucoesRuns(100);
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
      const res = await ingestExecucoes({ run_id: runId, update_existing: updateExisting });
      onDone(
        `${runId}: ${numberFormat.format(res.indexed_count ?? 0)} registos indexados` +
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

  const remove = async (runId: string, dropIndex = false) => {
    setBusy(runId);
    try {
      const res = await deleteExecucoesRun(runId, dropIndex);
      onDone(
        `Recolha «${runId}» apagada do disco` +
          (dropIndex && res.index ? ` e ${numberFormat.format(res.index.deleted ?? 0)} registos removidos do índice.` : "."),
      );
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
        <div className="text-[11.5px] font-semibold text-foreground">Recolhas gravadas</div>
        <div className="text-[10.5px] text-muted-foreground">{directory}</div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
        >
          <RefreshCw size={11} /> atualizar
        </button>
      </Card>

      {loading ? (
        <Card className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> a carregar recolhas…
        </Card>
      ) : runs.length === 0 ? (
        <Card className="text-[11px] text-muted-foreground">Ainda não há recolhas gravadas em disco.</Card>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <Card key={run.run_id} className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[11.5px] font-semibold text-foreground">{run.run_id}</div>
                  <div className="text-[10.5px] text-muted-foreground">
                    {`${formatDateTime(run.created_at)} · ${run.criteria?.nome || "recolha por alfabeto"}`}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void importRun(run.run_id)}
                    title="Importar para o Elasticsearch"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
                  >
                    <Upload size={11} /> importar
                  </button>
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void importRun(run.run_id, true)}
                    title="Reimportar (forçar atualização dos existentes)"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
                  >
                    <RefreshCw size={11} /> reindexar
                  </button>
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void remove(run.run_id)}
                    title="Apagar os ficheiros desta recolha"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-50"
                  >
                    <Trash2 size={11} /> ficheiros
                  </button>
                  <button
                    type="button"
                    disabled={busy === run.run_id}
                    onClick={() => void remove(run.run_id, true)}
                    title="Apaga os ficheiros e remove do Elasticsearch os registos desta recolha"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-50"
                  >
                    <Trash2 size={11} /> +índice
                  </button>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-4">
                <Stat label="Recolhidos" value={numberFormat.format(run.collected ?? 0)} />
                <Stat label="No índice" value={numberFormat.format(run.index_count ?? 0)} />
                <Stat label="Páginas" value={numberFormat.format(run.pages ?? 0)} />
                <Stat label="Duração" value={run.duration_s ? `${run.duration_s}s` : "—"} />
              </div>
              <div className="text-[10.5px] text-muted-foreground">
                {run.indexed ? ` · última importação: ${numberFormat.format(run.indexed)} documentos` : ""}
                {run.letras ? ` · ${run.letras} letras percorridas` : ""}
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

function EstadoSection({ status, onRefresh }: { status: ExecucaoStatus | null; onRefresh: () => void }) {
  if (!status) {
    return (
      <Card className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> a carregar o estado…
      </Card>
    );
  }

  if (status.error) {
    return <Card className="text-[11px] text-amber-200">Elasticsearch indisponível: {status.error}</Card>;
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

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Documentos" value={numberFormat.format(status.documents ?? 0)} />
        <Stat label="Valor total" value={formatMoney(status.valor_total ?? 0)} hint="soma dos valores da execução" />
        <Stat label="Valor médio" value={formatMoney(status.valor_medio ?? 0)} />
        <Stat label="Valor máximo" value={formatMoney(status.valor_maximo ?? 0)} />
      </div>

      <Card className="space-y-1 text-[11px] text-muted-foreground">
        <div>
          <span className="text-muted-foreground/70">Entradas de</span>{" "}
          <span className="text-foreground">{formatDate(status.min_date)}</span>{" "}
          <span className="text-muted-foreground/70">a</span>{" "}
          <span className="text-foreground">{formatDate(status.max_date)}</span>
        </div>
      </Card>

      <div className="grid gap-3 lg:grid-cols-4">
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Estado</div>
          {(status.by_estado ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_estado ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Comarca</div>
          {(status.by_comarca ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_comarca ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Tribunal</div>
          {(status.by_tribunal ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_tribunal ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Agente execução</div>
          {(status.by_agente ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_agente ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ logs */

function LogsSection() {
  const [jobs, setJobs] = useState<ExecucaoJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<ExecucaoJob | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listExecucoesJobs();
      setJobs(data.jobs);
    } catch (err) {
      /* ignora silenciosamente */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedJob(null);
      return;
    }
    let timer: number | null = null;
    const fetchJob = async () => {
      try {
        const job = await getExecucoesJob(selectedId);
        setSelectedJob(job);
      } catch {
        setSelectedJob(null);
      }
    };
    void fetchJob();
    timer = window.setInterval(fetchJob, 1500);
    return () => {
      if (timer) window.clearInterval(timer);
    };
  }, [selectedId]);

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card className="space-y-2 self-start">
        <div className="flex items-center justify-between">
          <div className="text-[11.5px] font-semibold text-foreground">Recolhas</div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> atualizar
          </button>
        </div>
        {jobs.length === 0 ? (
          <div className="text-[11px] text-muted-foreground">Ainda não há recolhas nesta sessão da API.</div>
        ) : (
          <div className="space-y-1">
            {jobs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelectedId(item.id)}
                className={`w-full rounded-lg border px-2 py-1.5 text-left text-[11px] transition ${
                  selectedId === item.id
                    ? "border-rose-400/30 bg-rose-400/10 text-rose-100"
                    : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-foreground">{item.id}</span>
                  <span className="text-[10px]">{item.state}</span>
                </div>
                <div className="text-[10px]">
                  {item.stage}
                  {item.letra ? ` · letra ${item.letra}` : ""}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-2">
        <div className="text-[11.5px] font-semibold text-foreground">Log do processo</div>
        {!selectedJob ? (
          <div className="text-[11px] text-muted-foreground">
            Seleciona uma recolha para ver o registo de atividade.
          </div>
        ) : !selectedJob.logs || selectedJob.logs.length === 0 ? (
          <div className="text-[11px] text-muted-foreground">Sem mensagens de log para esta recolha.</div>
        ) : (
          <div className="max-h-[calc(100vh-220px)] overflow-y-auto rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground">
            {selectedJob.logs.map((entry, idx) => (
              <div key={idx} className="flex gap-2 py-0.5">
                <span className="shrink-0 text-white/30">{formatDateTime(entry.at)}</span>
                <span className="text-foreground/80">{entry.message}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
