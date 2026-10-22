/**
 * Venda de Bens Penhorados em Processos Executivos.
 *
 * Duas fontes:
 * - CITIUS (Ministério da Justiça): bens penhorados em processos executivos
 *   com venda determinada, por tribunal e datas.
 * - e-leiloes.pt: vendas promovidas pelos agentes de execução, com processo,
 *     executados, gestor, fotos e geolocalização.
 *
 * Secções
 * - **Pesquisa** — procurar no índice por texto, processo, tribunal, tipo de
 *   bem, modalidade, estado, localização, executado e valor base.
 * - **Recolha** — escolher fontes, tribunais CITIUS e datas, e recolher; o
 *   progresso é acompanhado em tempo real.
 * - **Execuções** — ficheiros JSON gravados em `data/vendas_penhorados/runs`,
 *   com importação para o Elasticsearch e remoção.
 * - **Estado** — volumetria do índice e distribuições (fontes, tipos,
 *   modalidades, estados, distritos, valores).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building,
  CheckCircle2,
  Database,
  ExternalLink,
  FileJson,
  Hammer,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import {
  deleteVendasRun,
  getVendasJob,
  getVendasMeta,
  getVendasOptions,
  getVendasStatus,
  ingestVendas,
  listVendasJobs,
  listVendasRuns,
  searchVendas,
  startVendasCollect,
  stopVendasJob,
  vendaFonteLabel,
  type VendaCollectCriteria,
  type VendaFacet,
  type VendaJob,
  type VendaMeta,
  type VendaOptions,
  type VendaPenhorada,
  type VendaRun,
  type VendaSearchParams,
  type VendaSearchResult,
  type VendaStatus,
} from "../vendasApi";
import { formatMoney } from "../components/graph/graphStudio";

const numberFormat = new Intl.NumberFormat("pt-PT");
const dateFormat = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit", year: "numeric" });

type Section = "pesquisa" | "recolha" | "execucoes" | "estado";

const SECTIONS: { id: Section; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "pesquisa", label: "Pesquisa", hint: "Procurar bens penhorados indexados", icon: <Search size={14} /> },
  { id: "recolha", label: "Recolha", hint: "Recolher do CITIUS e/ou do e-leiloes.pt", icon: <Play size={14} /> },
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

/** Fontes de uma recolha gravada (o JSON guarda-as em `criteria.fontes`). */
function fontesLabel(criteria?: Record<string, unknown> | null): string {
  const fontes = criteria?.fontes;
  if (Array.isArray(fontes) && fontes.length > 0) return fontes.map(String).join(" + ");
  return "—";
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
  facet?: VendaFacet[];
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

/** Cartão de um bem penhorado. */
function VendaCard({ item }: { item: VendaPenhorada }) {
  const [open, setOpen] = useState(false);
  const cor =
    item.fonte === "eleiloes"
      ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
      : "border-amber-400/30 bg-amber-400/10 text-amber-200";

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${cor}`}>
              {vendaFonteLabel(item.fonte)}
            </span>
            <span className="text-sm font-semibold text-foreground">{item.titulo || item.referencia || item.processo}</span>
            {item.valor_base ? (
              <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10.5px] text-emerald-200">
                {formatMoney(item.valor_base)}
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {item.tribunal || item.comarca_judicial || "—"} · {item.processo || "—"}
          </div>
        </div>
        <div className="text-right text-[11px] text-muted-foreground">
          <div className="font-medium text-foreground">{formatDate(item.data_venda)}</div>
          <div>ref. {item.referencia || "—"}</div>
        </div>
      </div>

      <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
        {item.tipo_bem ? (
          <div>
            <span className="text-muted-foreground/70">Tipo:</span> {item.tipo_bem}
            {item.subtipo_bem ? ` / ${item.subtipo_bem}` : ""}
          </div>
        ) : null}
        {item.modalidade ? (
          <div>
            <span className="text-muted-foreground/70">Modalidade:</span> {item.modalidade}
          </div>
        ) : null}
        {item.estado ? (
          <div>
            <span className="text-muted-foreground/70">Estado:</span> {item.estado}
          </div>
        ) : null}
        {item.morada ? (
          <div className="truncate" title={item.morada}>
            <span className="text-muted-foreground/70">Morada:</span> {item.morada}
            {item.codigo_postal ? ` (${item.codigo_postal})` : ""}
          </div>
        ) : null}
        {item.distrito ? (
          <div>
            <span className="text-muted-foreground/70">Localização:</span> {item.distrito}
            {item.concelho ? ` › ${item.concelho}` : ""}
            {item.freguesia ? ` › ${item.freguesia}` : ""}
          </div>
        ) : null}
        {item.processo_numero ? (
          <div>
            <span className="text-muted-foreground/70">Processo:</span> {item.processo_numero}
          </div>
        ) : null}
      </div>

      {item.descricao ? (
        <div className="mt-2 text-[11px] text-muted-foreground">
          <span className="text-muted-foreground/70">Descrição:</span> {item.descricao.slice(0, 200)}
          {item.descricao.length > 200 ? "…" : ""}
        </div>
      ) : null}

      {item.intervenientes && item.intervenientes.length > 0 ? (
        <div className="mt-2 space-y-1">
          {(open ? item.intervenientes : item.intervenientes.slice(0, 4)).map((pessoa, index) => (
            <div key={`${pessoa.nome}-${index}`} className="flex items-center justify-between gap-2 text-[11px]">
              <span className="truncate">
                <span className="text-muted-foreground/70">{pessoa.papel || "Interveniente"}:</span> {pessoa.nome}
              </span>
              {pessoa.nif ? (
                <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {pessoa.nif}
                </span>
              ) : null}
            </div>
          ))}
          {item.intervenientes.length > 4 ? (
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              className="text-[10.5px] text-sky-300 hover:underline"
            >
              {open ? "Mostrar menos" : `Ver os ${item.intervenientes.length} intervenientes`}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {item.fotos && item.fotos.length > 0 ? (
          <div className="flex gap-1">
            {item.fotos.slice(0, 3).map((url, index) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noreferrer"
                className="h-12 w-12 overflow-hidden rounded border border-white/10"
              >
                <img src={url} alt={`Foto ${index + 1}`} className="h-full w-full object-cover" />
              </a>
            ))}
            {item.fotos.length > 3 ? (
              <span className="flex h-12 w-12 items-center justify-center rounded border border-white/10 text-[10px] text-muted-foreground">
                +{item.fotos.length - 3}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          {item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <ExternalLink size={11} /> portal
            </a>
          ) : null}
          {item.detalhe_url ? (
            <a
              href={item.detalhe_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <ExternalLink size={11} /> detalhe
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- app */

export default function VendasPage() {
  const [active, setActive] = useState<Section>("pesquisa");
  const [meta, setMeta] = useState<VendaMeta | null>(null);
  const [options, setOptions] = useState<VendaOptions | null>(null);
  const [status, setStatus] = useState<VendaStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getVendasStatus());
    } catch {
      /* Elasticsearch pode não estar disponível */
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [m, o] = await Promise.all([getVendasMeta(), getVendasOptions()]);
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
        <div className="rounded-xl bg-gradient-to-br from-amber-200 via-rose-500 to-violet-700 p-2 text-amber-950">
          <Hammer size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Vendas de bens penhorados</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {meta?.source_label ?? "Venda de Bens Penhorados em Processos Executivos — CITIUS + e-leiloes.pt"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> ·{" "}
              {numberFormat.format(status?.documents ?? 0)} bens
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
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- pesquisa */

function SearchSection({ onError }: { onError: (message: string) => void }) {
  const [params, setParams] = useState<VendaSearchParams>({ size: 20, from: 0 });
  const [result, setResult] = useState<VendaSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState({
    q: "",
    nome: "",
    processo: "",
    tribunal: "",
    tipo_bem: "",
    modalidade: "",
    estado: "",
    distrito: "",
    concelho: "",
    morada: "",
    data_from: "",
    data_to: "",
    valor_min: "",
    valor_max: "",
  });

  const run = useCallback(
    async (next: VendaSearchParams) => {
      setLoading(true);
      try {
        setResult(await searchVendas(next));
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

  const apply = (patch: Partial<VendaSearchParams>) => {
    const next: VendaSearchParams = { ...params, ...patch, from: patch.from ?? 0 };
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
    const patch: Partial<VendaSearchParams> = {
      q: draft.q || undefined,
      nome: draft.nome || undefined,
      processo: draft.processo || undefined,
      tribunal: draft.tribunal || undefined,
      tipo_bem: draft.tipo_bem || undefined,
      modalidade: draft.modalidade || undefined,
      estado: draft.estado || undefined,
      distrito: draft.distrito || undefined,
      concelho: draft.concelho || undefined,
      morada: draft.morada || undefined,
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
      nome: "",
      processo: "",
      tribunal: "",
      tipo_bem: "",
      modalidade: "",
      estado: "",
      distrito: "",
      concelho: "",
      morada: "",
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
              placeholder="título, descrição, processo, morada, nome…"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Executado / interveniente</label>
            <input
              value={draft.nome}
              onChange={(event) => setDraft({ ...draft, nome: event.target.value })}
              placeholder="ex.: Silva"
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
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo de bem</label>
              <input
                value={draft.tipo_bem}
                onChange={(event) => setDraft({ ...draft, tipo_bem: event.target.value })}
                placeholder="ex.: imóvel"
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Modalidade</label>
              <input
                value={draft.modalidade}
                onChange={(event) => setDraft({ ...draft, modalidade: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Estado</label>
              <input
                value={draft.estado}
                onChange={(event) => setDraft({ ...draft, estado: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
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
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Distrito</label>
              <input
                value={draft.distrito}
                onChange={(event) => setDraft({ ...draft, distrito: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Concelho</label>
              <input
                value={draft.concelho}
                onChange={(event) => setDraft({ ...draft, concelho: event.target.value })}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Morada</label>
            <input
              value={draft.morada}
              onChange={(event) => setDraft({ ...draft, morada: event.target.value })}
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
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
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
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
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data venda de</label>
              <input
                type="date"
                value={draft.data_from}
                onChange={(event) => setDraft({ ...draft, data_from: event.target.value })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              />
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data venda até</label>
              <input
                type="date"
                value={draft.data_to}
                onChange={(event) => setDraft({ ...draft, data_to: event.target.value })}
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

        <div className="space-y-2 pt-2">
          <Facets title="Fonte" facet={result?.facets?.fonte} active={params.fonte} onPick={(key) => apply({ fonte: key })} />
          <Facets title="Tipo de bem" facet={result?.facets?.tipo_bem} active={params.tipo_bem} onPick={(key) => apply({ tipo_bem: key })} />
          <Facets title="Modalidade" facet={result?.facets?.modalidade} active={params.modalidade} onPick={(key) => apply({ modalidade: key })} />
          <Facets title="Estado" facet={result?.facets?.estado} active={params.estado} onPick={(key) => apply({ estado: key })} />
          <Facets title="Distrito" facet={result?.facets?.distrito} active={params.distrito} onPick={(key) => apply({ distrito: key })} />
          <Facets title="Concelho" facet={result?.facets?.concelho} active={params.concelho} onPick={(key) => apply({ concelho: key })} />
        </div>
      </Card>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11.5px] text-muted-foreground">
            {result ? (
              <>
                <span className="font-semibold text-foreground">{numberFormat.format(result.total ?? 0)}</span> bens
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
            <VendaCard key={item.venda_id} item={item} />
          ))}
          {result && result.items.length === 0 ? (
            <Card className="text-[11px] text-muted-foreground">Nenhum bem encontrado para os filtros atuais.</Card>
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
  meta: VendaMeta | null;
  options: VendaOptions | null;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [fontes, setFontes] = useState<string[]>(["citius", "eleiloes"]);
  const [tribunal, setTribunal] = useState("");
  const [desde, setDesde] = useState("");
  const [ate, setAte] = useState("");
  const [tipoBem, setTipoBem] = useState("");
  const [modalidade, setModalidade] = useState("");
  const [estado, setEstado] = useState("");
  const [maxPagesTribunal, setMaxPagesTribunal] = useState(50);
  const [maxPagesEleiloes, setMaxPagesEleiloes] = useState(100);
  const [maxDetails, setMaxDetails] = useState(meta?.max_details ?? 400);
  const [maxItems, setMaxItems] = useState("");
  const [indexar, setIndexar] = useState(true);
  const [aRecolher, setARecolher] = useState(false);
  const [job, setJob] = useState<VendaJob | null>(null);
  const [jobs, setJobs] = useState<VendaJob[]>([]);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (meta?.default_window && !desde && !ate) {
      setDesde(meta.default_window.desde);
      setAte(meta.default_window.ate);
    }
  }, [meta, desde, ate]);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs((await listVendasJobs()).jobs);
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
          const current = await getVendasJob(id);
          setJob(current);
          if (current.finished) {
            if (timer.current) window.clearInterval(timer.current);
            timer.current = null;
            setARecolher(false);
            void refreshJobs();
            if (current.state === "error") {
              onError(current.error || "A recolha falhou.");
            } else if (current.state === "empty") {
              onDone("Não foram encontrados bens para os critérios indicados.");
            } else {
              onDone(
                `${numberFormat.format(current.collected ?? 0)} bens recolhidos` +
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
    const criteria: VendaCollectCriteria = {
      fontes,
      tribunais: tribunal ? [tribunal] : undefined,
      desde: desde || undefined,
      ate: ate || undefined,
      tipo_bem: tipoBem || undefined,
      modalidade: modalidade || undefined,
      estado: estado || undefined,
      max_pages_per_tribunal: maxPagesTribunal,
      max_pages_eleiloes: maxPagesEleiloes,
      max_details: maxDetails,
      max_items: maxItems ? Number(maxItems) : undefined,
      index: indexar,
    };
    try {
      const created = await startVendasCollect(criteria);
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
      await stopVendasJob(job.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      <Card className="space-y-3 self-start">
        <div className="text-[11.5px] font-semibold text-foreground">Recolher bens penhorados</div>

        <div>
          <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Fontes</label>
          <div className="mt-1 flex flex-wrap gap-3">
            {[
              { key: "citius", label: "CITIUS" },
              { key: "eleiloes", label: "e-leiloes.pt" },
            ].map((f) => (
              <label key={f.key} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={fontes.includes(f.key)}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...fontes, f.key]
                      : fontes.filter((item) => item !== f.key);
                    setFontes(next.length ? next : ["citius"]);
                  }}
                  autoComplete="off"
                />
                <span>{f.label}</span>
              </label>
            ))}
          </div>
        </div>

        {fontes.includes("citius") ? (
          <>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tribunal/serviço</label>
              <select
                value={tribunal}
                onChange={(event) => setTribunal(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              >
                <option value="">- Todos os Serviços -</option>
                {(options?.tribunais ?? []).map((option) => (
                  <option key={option.value} value={option.label}>
                    {option.label}
                  </option>
                ))}
              </select>
              {options?.error ? <p className="mt-1 text-[10px] text-amber-300">{options.error}</p> : null}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data venda de</label>
                <input
                  type="date"
                  value={desde}
                  onChange={(event) => setDesde(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
                />
              </div>
              <div>
                <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Data venda até</label>
                <input
                  type="date"
                  value={ate}
                  onChange={(event) => setAte(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo de bem</label>
                <select
                  value={tipoBem}
                  onChange={(event) => setTipoBem(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
                >
                  <option value="">- Todos -</option>
                  {(options?.tipos_bem ?? []).map((option) => (
                    <option key={option.value} value={option.label}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Modalidade</label>
                <select
                  value={modalidade}
                  onChange={(event) => setModalidade(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
                >
                  <option value="">- Todas -</option>
                  {(options?.modalidades ?? []).map((option) => (
                    <option key={option.value} value={option.label}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Estado</label>
              <select
                value={estado}
                onChange={(event) => setEstado(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
              >
                <option value="">- Todos -</option>
                {(options?.estados ?? []).map((option) => (
                  <option key={option.value} value={option.label}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </>
        ) : null}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Páginas CITIUS/tribunal</label>
            <input
              type="number"
              min={1}
              max={5000}
              value={maxPagesTribunal}
              onChange={(event) => setMaxPagesTribunal(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Páginas e-leiloes</label>
            <input
              type="number"
              min={1}
              max={5000}
              value={maxPagesEleiloes}
              onChange={(event) => setMaxPagesEleiloes(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Detalhes CITIUS</label>
            <input
              type="number"
              min={0}
              max={5000}
              value={maxDetails}
              onChange={(event) => setMaxDetails(Number(event.target.value))}
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Máximo de bens</label>
            <input
              type="number"
              min={1}
              value={maxItems}
              onChange={(event) => setMaxItems(event.target.value)}
              placeholder="ilimitado"
              className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40"
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
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-[11.5px] text-amber-100 hover:bg-amber-500/30"
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
              <div className="text-[11.5px] font-semibold text-foreground">Recolha em curso</div>
              <span
                className={`rounded-full px-2 py-0.5 text-[10.5px] ${
                  job.state === "error"
                    ? "bg-rose-400/15 text-rose-200"
                    : job.state === "done"
                      ? "bg-emerald-400/15 text-emerald-200"
                      : "bg-amber-400/15 text-amber-200"
                }`}
              >
                {job.state} · {job.stage}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              <Stat label="Bens" value={numberFormat.format(job.collected ?? 0)} hint={job.tribunal ? job.tribunal : undefined} />
              <Stat label="Páginas" value={numberFormat.format(job.pages ?? 0)} />
              <Stat label="Detalhes" value={numberFormat.format(job.details ?? 0)} />
              <Stat label="Importados" value={numberFormat.format(job.indexed ?? 0)} />
            </div>
            <div className="text-[10.5px] text-muted-foreground">
              {job.run_id ? (
                <>
                  ficheiro <span className="font-mono text-foreground">{job.run_id}</span>
                </>
              ) : null}
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
                    <span className="text-foreground">{item.criteria?.fontes?.join(" + ") ?? "—"}</span>
                    <span className="text-muted-foreground"> · {item.state}</span>
                  </span>
                  <span className="text-muted-foreground">
                    {numberFormat.format(item.collected ?? 0)} bens
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
            1. A recolha consulta o portal CITIUS ("Venda de Bens Penhorados em Processos Executivos") e/ou a API pública
            do e-leiloes.pt, gravando o resultado em{" "}
            <span className="font-mono text-foreground">data/vendas_penhorados/runs</span>.
          </p>
          <p>
            2. No fim (se «Importar» estiver ligado) o JSON é indexado em{" "}
            <span className="font-mono text-foreground">{meta?.index ?? "finance_vendas_penhorados"}</span>. Reimportar a
            mesma recolha não duplica: os bens já existentes são ignorados.
          </p>
          <p>
            3. O CITIUS exige tribunal e um intervalo de datas de venda (cerca de um mês atrás e dois à frente). O
            e-leiloes.pt devolve os eventos mais recentes primeiro.
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
  const [runs, setRuns] = useState<VendaRun[]>([]);
  const [directory, setDirectory] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listVendasRuns(100);
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
      const res = await ingestVendas({ run_id: runId, update_existing: updateExisting });
      onDone(
        `${runId}: ${numberFormat.format(res.indexed_count ?? 0)} bens indexados` +
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
      const res = await deleteVendasRun(runId, dropIndex);
      onDone(
        `Recolha «${runId}» apagada do disco` +
          (dropIndex && res.index ? ` e ${numberFormat.format(res.index.deleted ?? 0)} bens removidos do índice.` : "."),
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
          <Loader2 size={13} className="animate-spin" /> a carregar execuções…
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
                    {formatDateTime(run.created_at)} · {fontesLabel(run.criteria)}
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
                    title="Apaga os ficheiros e remove do Elasticsearch os bens desta recolha"
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-50"
                  >
                    <Trash2 size={11} /> +índice
                  </button>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-4">
                <Stat label="Recolhidos" value={numberFormat.format(run.collected ?? 0)} />
                <Stat label="Detalhes" value={numberFormat.format(run.details ?? 0)} />
                <Stat label="No índice" value={numberFormat.format(run.index_count ?? 0)} />
                <Stat label="Duração" value={run.duration_s ? `${run.duration_s}s` : "—"} />
              </div>
              <div className="text-[10.5px] text-muted-foreground">
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

function EstadoSection({ status, onRefresh }: { status: VendaStatus | null; onRefresh: () => void }) {
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
        <Stat label="Valor total" value={formatMoney(status.valor_total ?? 0)} hint="soma dos valores base" />
        <Stat label="Valor médio" value={formatMoney(status.valor_medio ?? 0)} />
        <Stat label="Valor máximo" value={formatMoney(status.valor_maximo ?? 0)} />
      </div>

      <Card className="space-y-1 text-[11px] text-muted-foreground">
        <div>
          <span className="text-muted-foreground/70">Vendas de</span>{" "}
          <span className="text-foreground">{formatDate(status.min_date)}</span>{" "}
          <span className="text-muted-foreground/70">a</span>{" "}
          <span className="text-foreground">{formatDate(status.max_date)}</span>
        </div>
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Fonte</div>
          {(status.by_fonte ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{vendaFonteLabel(item.key)}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_fonte ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Tipo de bem</div>
          {(status.by_tipo_bem ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_tipo_bem ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Modalidade</div>
          {(status.by_modalidade ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_modalidade ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
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
          <div className="text-[11.5px] font-semibold text-foreground">Distritos</div>
          {(status.by_distrito ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_distrito ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
        <Card className="space-y-1">
          <div className="text-[11.5px] font-semibold text-foreground">Concelhos</div>
          {(status.by_concelho ?? []).map((item) => (
            <div key={item.key} className="flex justify-between text-[11px] text-muted-foreground">
              <span className="truncate text-foreground">{item.key}</span>
              <span>{numberFormat.format(item.count)}</span>
            </div>
          ))}
          {(status.by_concelho ?? []).length === 0 ? <div className="text-[11px] text-muted-foreground">—</div> : null}
        </Card>
      </div>

      <Card className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Building size={13} /> Os dados unificam as duas fontes: CITIUS traz o bem em si, o processo e o tribunal;
        o e-leiloes.pt acrescenta executados com NIF, geolocalização, fotografias e ónus.
      </Card>
    </div>
  );
}
