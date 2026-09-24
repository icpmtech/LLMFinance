/**
 * Contribuintes — índice único com todos os NIF/NIPC do sistema.
 *
 * `finance_contribuintes` é um índice **derivado**: cada documento é um
 * contribuinte (empresa, pessoa, empresário, entidade pública ou estrangeiro)
 * agregado a partir de todos os índices da plataforma — contratos públicos de
 * Portugal e de Espanha, cadastro de entidades, publicações societárias,
 * insolvências (CIRE), PessoasIQ, firmas (RNPC), marcas (INPI) e CRM.
 *
 * Secções
 * - **Pesquisa** — procurar por nome/NIF, filtrar por tipo, fonte, papel e
 *   país; abrir a ficha do contribuinte com os totais e a evidência de cada
 *   fonte (contratos, publicações, processos, marcas, cargos, contas). A lista
 *   e a ficha exportam-se em **PDF, Excel e CSV** (relatórios do backend, com o
 *   logótipo do IQ OS no PDF e no Excel).
 * - **Sincronização** — reconstruir o índice a partir de todas as fontes (ou
 *   só de algumas), acompanhar o progresso e, se for caso disso, esvaziar o
 *   índice para forçar uma reconstrução limpa.
 * - **Agenda** — ligar a sincronização automática (expressão cron de 5 campos),
 *   ver a próxima execução e o histórico das últimas passagens.
 * - **Cobertura** — gráficos da volumetria: tipos de contribuinte, localização
 *   (distrito/concelho) e a matriz tipo × distrito, além das facetas de país,
 *   fontes e papéis.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  FileSpreadsheet,
  FileText,
  Gavel,
  Landmark,
  Loader2,
  MapPin,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Formatter as RechartsFormatter } from "recharts/types/component/DefaultTooltipContent";
import {
  deleteContribuintesIndex,
  exportContribuinteReport,
  exportContribuintesReport,
  getContribuinte,
  getContribuintesJob,
  getContribuintesMeta,
  getContribuintesSchedule,
  getContribuintesStatus,
  autocompleteContribuintes,
  listContribuintesJobs,
  saveContribuintesReport,
  saveContribuintesSchedule,
  searchContribuintes,
  startContribuintesSync,
  type Contribuinte,
  type ContribuinteFacet,
  type ContribuinteSourceBlock,
  type ContribuintesJob,
  type ContribuintesMeta,
  type ContribuintesReportFormat,
  type ContribuintesReportsMeta,
  type ContribuintesSchedule,
  type ContribuintesStatus,
} from "../contribuintesApi";
import { useAuth } from "../auth";

type Section = "pesquisa" | "sincronizacao" | "agenda" | "cobertura";

const SECTIONS: { id: Section; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "pesquisa", label: "Pesquisa", icon: <Search size={13} />, hint: "Procurar contribuintes e abrir a ficha" },
  { id: "sincronizacao", label: "Sincronização", icon: <RefreshCw size={13} />, hint: "Reconstruir o índice a partir de todas as fontes" },
  { id: "agenda", label: "Agenda", icon: <CalendarClock size={13} />, hint: "Sincronização automática (cron)" },
  { id: "cobertura", label: "Cobertura", icon: <Database size={13} />, hint: "Volumetria e distribuições do índice" },
];

const numberFormat = new Intl.NumberFormat("pt-PT");
const currencyFormat = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const compactFormat = new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 });

/** Tooltip do recharts: contagem de contribuintes (o valor chega como tipo genérico). */
const countTooltip: RechartsFormatter = (value) => [numberFormat.format(Number(value)), "Contribuintes"];

const TYPE_STYLES: Record<string, string> = {
  empresa: "border-sky-400/25 bg-sky-400/10 text-sky-200",
  pessoa: "border-fuchsia-400/25 bg-fuchsia-400/10 text-fuchsia-200",
  empresario: "border-amber-400/25 bg-amber-400/10 text-amber-200",
  entidade_publica: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
  estrangeiro: "border-violet-400/25 bg-violet-400/10 text-violet-200",
  outro: "border-white/15 bg-white/5 text-muted-foreground",
  desconhecido: "border-white/15 bg-white/5 text-muted-foreground",
};

const SORT_OPTIONS = [
  { id: "relevance", label: "Relevância" },
  { id: "activity", label: "Atividade recente" },
  { id: "contracts", label: "Nº de contratos" },
  { id: "value", label: "Valor contratual" },
  { id: "name", label: "Nome" },
  { id: "nif", label: "NIF" },
];

const ROLE_LABELS: Record<string, string> = {
  adjudicante: "Adjudicante",
  adjudicatario: "Adjudicatário",
  cadastro: "Cadastro",
  firma: "Firma",
  titular_marca: "Titular de marca",
  societario: "Publicações societárias",
  matriculado: "Matrícula",
  insolvente: "Insolvente",
  administrador: "Administrador de insolvência",
  credor: "Credor",
  interveniente: "Interveniente",
  pessoa: "Pessoa/cargos",
  crm: "Conta de CRM",
};

function roleLabel(role: string) {
  return ROLE_LABELS[role] ?? role;
}

/** Etiquetas dos subcampos de `location` (os nomes vêm do índice). */
const LOCATION_LABELS: Record<string, string> = {
  pais: "País",
  distrito: "Distrito",
  concelho: "Concelho",
  freguesia: "Freguesia",
  codigo_postal: "Código postal",
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString("pt-PT");
}

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

function valueOrDash(value?: number | null) {
  return value === undefined || value === null ? "—" : numberFormat.format(value);
}

function sourceBlock(doc: Contribuinte, sourceId: string): ContribuinteSourceBlock | undefined {
  const block = doc[`src_${sourceId}`];
  return block && typeof block === "object" ? (block as ContribuinteSourceBlock) : undefined;
}

/** Métricas a mostrar na ficha, por fonte. */
function metricsFor(doc: Contribuinte, sourceId: string): { label: string; value: string }[] {
  const block = sourceBlock(doc, sourceId);
  const rows: { label: string; value: string }[] = [];
  if (!block) return rows;
  switch (sourceId) {
    case "contratos":
      rows.push({ label: "Contratos", value: valueOrDash(block.count) });
      if (doc.contracts_as_adjudicante) rows.push({ label: "Como adjudicante", value: numberFormat.format(doc.contracts_as_adjudicante) });
      if (doc.contracts_as_adjudicatario) rows.push({ label: "Como adjudicatário", value: numberFormat.format(doc.contracts_as_adjudicatario) });
      if (block.value) rows.push({ label: "Valor envolvido", value: currencyFormat.format(block.value) });
      rows.push({ label: "Contratos entre", value: `${formatDate(block.first)} → ${formatDate(block.last)}` });
      break;
    case "contratos_es":
      rows.push({ label: "Contratos", value: valueOrDash(block.count) });
      if (block.value) rows.push({ label: "Valor adjudicado", value: currencyFormat.format(block.value) });
      rows.push({ label: "Última adjudicação", value: formatDate(block.last) });
      break;
    case "entidades":
      rows.push({ label: "Contratos no cadastro", value: valueOrDash(doc.entities_contracts_count) });
      if (doc.entities_value) rows.push({ label: "Valor no cadastro", value: currencyFormat.format(doc.entities_value) });
      break;
    case "societario":
      rows.push({ label: "Publicações", value: valueOrDash(block.count) });
      rows.push({ label: "Publicações entre", value: `${formatDate(block.first)} → ${formatDate(block.last)}` });
      break;
    case "cire":
      rows.push({ label: "Processos", value: valueOrDash(block.count) });
      if (doc.cire_roles?.length) rows.push({ label: "Papéis", value: doc.cire_roles.join(", ") });
      rows.push({ label: "Última publicação", value: formatDate(block.last) });
      break;
    case "pessoas":
      if (doc.people_roles_count) rows.push({ label: "Cargos", value: numberFormat.format(doc.people_roles_count) });
      if (doc.people_companies_count) rows.push({ label: "Empresas", value: numberFormat.format(doc.people_companies_count) });
      break;
    case "firmas":
      rows.push({ label: "Firmas", value: valueOrDash(block.count) });
      break;
    case "marcas":
      rows.push({ label: "Marcas", value: valueOrDash(block.count) });
      break;
    case "crm":
      rows.push({ label: "Conta de CRM", value: "sim" });
      break;
    default:
      rows.push({ label: "Registos", value: valueOrDash(block.count) });
  }
  const detail = block.detail ?? {};
  Object.entries(detail)
    .filter(([key]) => !["contracts_count", "total_value", "as_adjudicante_count", "as_adjudicatario_count", "roles_count", "companies_count", "is_company"].includes(key))
    .slice(0, 6)
    .forEach(([key, value]) => {
      if (value === null || value === undefined || value === "" || typeof value === "object") return;
      rows.push({ label: key.replace(/_/g, " "), value: String(value) });
    });
  return rows;
}

/* --------------------------------------------------------------- relatórios */

/** Paleta dos tipos de contribuinte (coerente com as etiquetas de `TYPE_STYLES`). */
const TYPE_COLORS: Record<string, string> = {
  empresa: "#38bdf8",
  pessoa: "#e879f9",
  empresario: "#fbbf24",
  entidade_publica: "#34d399",
  estrangeiro: "#a78bfa",
  outro: "#94a3b8",
  desconhecido: "#64748b",
};

/** Formato de relatório por omissão, quando os metadados ainda não chegaram. */
const DEFAULT_REPORT_FORMATS = [
  { id: "pdf" as ContribuintesReportFormat, label: "PDF", available: true, embeds_logo: true },
  { id: "xlsx" as ContribuintesReportFormat, label: "Excel", available: true, embeds_logo: true },
  { id: "csv" as ContribuintesReportFormat, label: "CSV", available: true, embeds_logo: false },
];

const REPORT_ICONS: Record<ContribuintesReportFormat, React.ReactNode> = {
  pdf: <FileText size={12} />,
  xlsx: <FileSpreadsheet size={12} />,
  csv: <Download size={12} />,
};

/**
 * Botões de relatório (PDF, Excel e CSV) com a marca do IQ OS.
 *
 * O ficheiro é gerado no backend (com o logótipo embutido no PDF e no Excel) e
 * descarregado aqui; o estado do botão diz qual está a ser preparado.
 */
function ReportButtons({
  formats,
  onExport,
  hint,
}: {
  formats: ContribuintesReportsMeta["formats"];
  onExport: (format: ContribuintesReportFormat) => Promise<void>;
  hint?: string;
}) {
  const [busy, setBusy] = useState<ContribuintesReportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const list = formats?.length ? formats : DEFAULT_REPORT_FORMATS;

  const run = async (format: ContribuintesReportFormat) => {
    setBusy(format);
    setError(null);
    try {
      await onExport(format);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível gerar o relatório");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {list
        .filter((format) => format.available)
        .map((format) => (
          <button
            key={format.id}
            type="button"
            disabled={busy !== null}
            onClick={() => void run(format.id)}
            title={
              format.embeds_logo
                ? `Relatório ${format.label} com o logótipo do IQ OS`
                : `Relatório ${format.label} com o cabeçalho do IQ OS`
            }
            className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground disabled:opacity-50"
          >
            {busy === format.id ? <Loader2 size={12} className="animate-spin" /> : REPORT_ICONS[format.id]}
            {format.label}
          </button>
        ))}
      {hint && !error ? <span className="text-[10.5px] text-muted-foreground">{hint}</span> : null}
      {error ? <span className="text-[10.5px] text-rose-300">{error}</span> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ página */

export default function ContribuintesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [meta, setMeta] = useState<ContribuintesMeta | null>(null);
  const [status, setStatus] = useState<ContribuintesStatus | null>(null);
  const [schedule, setSchedule] = useState<ContribuintesSchedule | null>(null);
  const [active, setActive] = useState<Section>("pesquisa");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const canWrite = Boolean(user);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextSchedule] = await Promise.all([getContribuintesStatus(), getContribuintesSchedule()]);
      setStatus(nextStatus);
      setSchedule(nextSchedule);
      if (nextStatus.error) setError(nextStatus.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível ler o estado do índice de contribuintes");
    }
  }, []);

  useEffect(() => {
    getContribuintesMeta()
      .then(setMeta)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Metadados indisponíveis"));
    void refresh();
  }, [refresh]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-teal-300/30 via-emerald-500/25 to-slate-900 p-2 text-emerald-100">
          <Users size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Contribuintes</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            Todos os NIF/NIPC do sistema, agregados de todos os índices da plataforma
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> · {numberFormat.format(status?.documents ?? 0)} contribuintes
            </span>
          ) : null}
          {schedule?.scheduler?.next_run_time ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              próxima sincronização {formatDateTime(schedule.scheduler.next_run_time)}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => void refresh()}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            <RefreshCw size={12} /> Atualizar
          </button>
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
              active === item.id ? "bg-emerald-400/15 text-emerald-200" : "text-muted-foreground hover:bg-white/5 hover:text-foreground"
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

        {active === "pesquisa" && <SearchSection meta={meta} />}
        {active === "sincronizacao" && (
          <SyncSection
            meta={meta}
            status={status}
            canWrite={canWrite}
            isAdmin={isAdmin}
            onDone={(message) => {
              setNotice(message);
              void refresh();
            }}
            onError={setError}
          />
        )}
        {active === "agenda" && (
          <ScheduleSection
            meta={meta}
            schedule={schedule}
            canWrite={canWrite}
            onSaved={(next, message) => {
              setSchedule(next);
              setNotice(message);
            }}
            onError={setError}
          />
        )}
        {active === "cobertura" && <CoverageSection meta={meta} status={status} />}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------- pesquisa */

function SearchSection({ meta }: { meta: ContribuintesMeta | null }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [source, setSource] = useState("");
  const [role, setRole] = useState("");
  const [country, setCountry] = useState("");
  const [hasContracts, setHasContracts] = useState(false);
  const [sort, setSort] = useState("relevance");
  const [page, setPage] = useState(1);
  const [size] = useState(20);
  const [result, setResult] = useState<{ total: number; items: Contribuinte[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Contribuinte[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const suggestTimer = useRef<number | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await searchContribuintes({
        q: q.trim() || undefined,
        type: type || undefined,
        source: source || undefined,
        role: role || undefined,
        country: country || undefined,
        has_contracts: hasContracts ? true : undefined,
        sort,
        page,
        size,
      });
      if (data.error) throw new Error(data.error);
      setResult({ total: data.total, items: data.items });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pesquisa falhou");
    } finally {
      setLoading(false);
    }
  }, [q, type, source, role, country, hasContracts, sort, page, size]);

  useEffect(() => {
    void run();
  }, [run]);

  useEffect(() => {
    setPage(1);
  }, [q, type, source, role, country, hasContracts, sort]);

  useEffect(() => {
    const term = q.trim();
    if (suggestTimer.current) window.clearTimeout(suggestTimer.current);
    if (term.length < 2) {
      setSuggestions([]);
      return;
    }
    suggestTimer.current = window.setTimeout(() => {
      autocompleteContribuintes(term, 6)
        .then((data) => setSuggestions(data.items))
        .catch(() => setSuggestions([]));
    }, 250);
    return () => {
      if (suggestTimer.current) window.clearTimeout(suggestTimer.current);
    };
  }, [q]);

  const pages = result ? Math.max(1, Math.ceil(result.total / size)) : 1;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,480px)]">
      <div className="min-w-0 space-y-3">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => window.setTimeout(() => setShowSuggestions(false), 150)}
              placeholder="Nome, designação ou NIF/NIPC (ex.: «EDP», «500189412»)"
              className="w-full rounded-xl border border-white/10 bg-black/20 py-2 pl-9 pr-24 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-emerald-400/40"
            />
            {q ? (
              <button
                type="button"
                onClick={() => setQ("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                title="Limpar"
              >
                <X size={13} />
              </button>
            ) : null}
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-white/10 bg-slate-950/95 shadow-xl">
                {suggestions.map((item) => (
                  <button
                    key={item.nif}
                    type="button"
                    onMouseDown={() => {
                      setQ(item.name ?? item.nif);
                      setSelected(item.nif);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11.5px] text-muted-foreground hover:bg-white/5 hover:text-foreground"
                  >
                    <span className="min-w-0 flex-1 truncate">{item.name}</span>
                    <span className="font-mono text-[10.5px] opacity-70">{item.nif}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
            <Select value={type} onChange={setType} placeholder="Tipo">
              {(meta?.types ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <Select value={source} onChange={setSource} placeholder="Fonte">
              {(meta?.sources ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <Select value={role} onChange={setRole} placeholder="Papel">
              {Array.from(new Set((meta?.sources ?? []).flatMap((item) => item.roles))).map((item) => (
                <option key={item} value={item}>
                  {roleLabel(item)}
                </option>
              ))}
            </Select>
            <Select value={country} onChange={setCountry} placeholder="País">
              {["Portugal", "Espanha", "Internacional"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Select value={sort} onChange={setSort} placeholder="Ordenar">
              {SORT_OPTIONS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-muted-foreground">
              <input type="checkbox" checked={hasContracts} onChange={(event) => setHasContracts(event.target.checked)} className="accent-emerald-400" />
              só com contratos
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span>
            {loading ? "a pesquisar…" : result ? `${numberFormat.format(result.total)} contribuintes` : "—"}
            {pages > 1 ? ` · página ${page} de ${numberFormat.format(pages)}` : ""}
          </span>
          <span className="flex flex-wrap items-center gap-2">
            {result && result.total > 0 ? (
              <ReportButtons
                formats={meta?.reports?.formats ?? []}
                onExport={async (format) => {
                  const { blob, filename } = await exportContribuintesReport(
                    {
                      q: q.trim() || undefined,
                      type: type || undefined,
                      source: source || undefined,
                      role: role || undefined,
                      country: country || undefined,
                      has_contracts: hasContracts ? true : undefined,
                      sort,
                    },
                    format,
                    1000,
                  );
                  saveContribuintesReport(blob, filename);
                }}
                hint="resultados filtrados"
              />
            ) : null}
            {pages > 1 && (
              <span className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 disabled:opacity-40"
                >
                  <ChevronLeft size={12} /> anterior
                </button>
                <button
                  type="button"
                  disabled={page >= pages}
                  onClick={() => setPage((current) => current + 1)}
                  className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 disabled:opacity-40"
                >
                  seguinte <ChevronRight size={12} />
                </button>
              </span>
            )}
          </span>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-400/25 bg-rose-400/5 px-3 py-2 text-[11.5px] text-rose-200">{error}</div>
        )}

        <div className="space-y-1.5">
          {(result?.items ?? []).map((item) => (
            <button
              key={item.nif}
              type="button"
              onClick={() => setSelected(item.nif)}
              className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition ${
                selected === item.nif ? "border-emerald-400/40 bg-emerald-400/10" : "border-white/10 bg-white/[0.02] hover:bg-white/[0.06]"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[12.5px] font-medium text-foreground">{item.name || item.nif}</span>
                  <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] ${TYPE_STYLES[item.type ?? "desconhecido"] ?? TYPE_STYLES.desconhecido}`}>
                    {item.type_label ?? item.type}
                  </span>
                  {item.nif_valid === false && (
                    <span className="shrink-0 rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">NIF a confirmar</span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
                  <span className="font-mono">{item.nif}</span>
                  {item.location?.concelho ? <span>· {String(item.location.concelho)}</span> : null}
                  <span>· {(item.sources ?? []).length} fonte(s)</span>
                  {item.contracts_count ? <span>· {numberFormat.format(item.contracts_count)} contratos</span> : null}
                  {item.contracts_value ? <span>· {compactFormat.format(item.contracts_value)} €</span> : null}
                  {item.cire_count ? <span>· {numberFormat.format(item.cire_count)} processos CIRE</span> : null}
                  <span>· visto em {formatDate(item.last_seen)}</span>
                </div>
                {(() => {
                  const alternatives = (item.names ?? []).filter((name) => name && name !== item.name).slice(0, 2);
                  if (!alternatives.length) return null;
                  return (
                    <div className="mt-0.5 truncate text-[10.5px] text-muted-foreground">
                      também: <span className="text-foreground/80">{alternatives.join(" · ")}</span>
                    </div>
                  );
                })()}
                <div className="mt-1 flex flex-wrap gap-1">
                  {(item.roles ?? []).slice(0, 6).map((role) => (
                    <span key={role} className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {roleLabel(role)}
                    </span>
                  ))}
                </div>
              </div>
            </button>
          ))}
          {!loading && result && result.items.length === 0 && (
            <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-6 text-center text-[11.5px] text-muted-foreground">
              Sem resultados. Se o índice ainda estiver vazio, sincronize-o na secção «Sincronização».
            </div>
          )}
        </div>
      </div>

      <DetailPanel nif={selected} meta={meta} onClose={() => setSelected(null)} />
    </div>
  );
}

function Select({
  value,
  onChange,
  placeholder,
  children,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={`rounded-full border px-2.5 py-1 outline-none ${
        value ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-100" : "border-white/10 bg-white/5 text-muted-foreground"
      }`}
    >
      <option value="">{placeholder}</option>
      {children}
    </select>
  );
}

function DetailPanel({ nif, meta, onClose }: { nif: string | null; meta: ContribuintesMeta | null; onClose: () => void }) {
  const [doc, setDoc] = useState<Contribuinte | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!nif) {
      setDoc(null);
      return;
    }
    setLoading(true);
    setError(null);
    getContribuinte(nif)
      .then(setDoc)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Ficha indisponível"))
      .finally(() => setLoading(false));
  }, [nif]);

  if (!nif) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-[11.5px] text-muted-foreground">
        Escolha um contribuinte para ver a ficha completa: identificação, totais por fonte e evidência.
      </div>
    );
  }

  const sources = meta?.sources ?? [];
  const known = sources.filter((source) => Boolean(doc && sourceBlock(doc, source.id)));
  const extra = (doc?.sources ?? []).filter((id) => !sources.some((source) => source.id === id));

  return (
    <div className="min-w-0 space-y-3">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-semibold text-foreground">{doc?.name ?? nif}</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-mono">{nif}</span>
              {doc?.type ? (
                <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${TYPE_STYLES[doc.type] ?? TYPE_STYLES.desconhecido}`}>
                  {doc.type_label ?? doc.type}
                </span>
              ) : null}
              {doc?.country ? <span>{doc.country}</span> : null}
              {doc?.is_company !== undefined ? <span>{doc.is_company ? "pessoa coletiva" : "pessoa singular"}</span> : null}
              {doc?.nif_valid === false ? <span className="text-amber-300">NIF a confirmar</span> : null}
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground" title="Fechar">
            <X size={13} />
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Relatório</span>
          <ReportButtons
            formats={meta?.reports?.formats ?? []}
            onExport={async (format) => {
              const { blob, filename } = await exportContribuinteReport(nif, format);
              saveContribuintesReport(blob, filename);
            }}
          />
        </div>

        {loading && <div className="mt-3 text-[11.5px] text-muted-foreground">a carregar…</div>}
        {error && <div className="mt-3 text-[11.5px] text-rose-300">{error}</div>}

        {doc && (
          <>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
              {[
                { label: "Registos agregados", value: numberFormat.format(doc.records_total ?? 0) },
                { label: "Contratos (PT)", value: valueOrDash(doc.contracts_count) },
                { label: "Contratos (ES)", value: valueOrDash(doc.contratos_es_count) },
                {
                  label: "Valor contratual (PT)",
                  value: doc.contracts_value ? compactFormat.format(doc.contracts_value) + " €" : "—",
                },
                {
                  label: "Valor contratual (ES)",
                  value: doc.contratos_es_value ? compactFormat.format(doc.contratos_es_value) + " €" : "—",
                },
                { label: "Publicações (MJ)", value: valueOrDash(doc.societario_count) },
                { label: "Processos CIRE", value: valueOrDash(doc.cire_count) },
                {
                  label: "Marcas / firmas",
                  value: numberFormat.format((doc.trademarks_count ?? 0) + (doc.firmas_count ?? 0)),
                },
                { label: "Cargos (PessoasIQ)", value: valueOrDash(doc.people_roles_count) },
                { label: "Conta de CRM", value: doc.crm_account ? "sim" : "—" },
              ].map((kpi) => (
                <div key={kpi.label} className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{kpi.label}</div>
                  <div className="text-[13px] font-semibold text-foreground">{kpi.value}</div>
                </div>
              ))}
            </div>

            <div className="mt-2 rounded-xl border border-white/10 bg-black/20 px-2.5 py-2 text-[11px]">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Atividade registada</div>
              <div className="text-[12px] text-foreground">
                {formatDate(doc.first_seen)} → {formatDate(doc.last_seen)}
              </div>
            </div>

            {(doc.location && Object.values(doc.location).some(Boolean)) || doc.names?.length ? (
              <div className="mt-3 space-y-2">
                {doc.location && Object.values(doc.location).some(Boolean) ? (
                  <div>
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <MapPin size={11} /> Localização
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[10.5px] text-muted-foreground">
                      {Object.entries(doc.location)
                        .filter(([, value]) => value)
                        .map(([key, value]) => (
                          <span key={key} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
                            {LOCATION_LABELS[key] ?? key}: <span className="text-foreground">{String(value)}</span>
                          </span>
                        ))}
                    </div>
                  </div>
                ) : null}
                {(doc.names ?? []).length > 0 ? (
                  <div>
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <FileText size={11} /> Designações ({(doc.names ?? []).length})
                    </div>
                    <div className="mt-1 space-y-0.5 text-[11px]">
                      {(doc.names ?? []).map((name, index) => (
                        <div key={`${name}-${index}`} className="flex items-baseline gap-1.5">
                          <span className={index === 0 ? "text-foreground" : "text-muted-foreground"}>{name}</span>
                          {index === 0 ? (
                            <span className="shrink-0 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[9.5px] text-emerald-100">
                              principal
                            </span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="mt-3 flex flex-wrap items-center gap-1">
              {(doc.source_labels ?? doc.sources ?? []).map((label) => (
                <span key={String(label)} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                  {String(label)}
                </span>
              ))}
            </div>

            <div className="mt-2 flex flex-wrap gap-1">
              {(doc.roles ?? []).map((role) => (
                <span key={role} className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-[10.5px] text-emerald-100">
                  {roleLabel(role)}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      {doc && (known.length > 0 || extra.length > 0) && (
        <div className="space-y-2">
          {known.map((source) => {
            const rows = metricsFor(doc, source.id);
            return (
              <div key={source.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={13} className="text-emerald-300" />
                  <span className="text-[11.5px] font-medium text-foreground">{source.label}</span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">{source.index}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  {rows.map((row) => (
                    <div key={`${source.id}-${row.label}`} className="flex items-baseline gap-1.5">
                      <span className="text-muted-foreground">{row.label}</span>
                      <span className="ml-auto text-foreground">{row.value}</span>
                    </div>
                  ))}
                </div>
                {(() => {
                  const block = sourceBlock(doc, source.id);
                  const names = (block?.names ?? []).filter(Boolean);
                  const parts = block?.parts ?? {};
                  const keys = Object.keys(parts);
                  return (
                    <>
                      {names.length > 0 ? (
                        <div className="mt-2 text-[10.5px] text-muted-foreground">
                          <div className="text-[10px] uppercase tracking-wide">Designações nesta fonte</div>
                          <div className="mt-0.5 space-y-0.5">
                            {names.map((name, index) => (
                              <div key={`${name}-${index}`} className="text-foreground/90">
                                {name}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {keys.length >= 2 ? (
                        <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] text-muted-foreground">
                          {keys.map((key) => (
                            <span key={key} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
                              {key}: {numberFormat.format(parts[key]?.count ?? 0)}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </>
                  );
                })()}
              </div>
            );
          })}
          {extra.length > 0 && (
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3 text-[11px] text-muted-foreground">
              <div className="flex items-center gap-2">
                <Database size={13} />
                <span>Outras fontes com registos deste NIF</span>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {extra.map((id) => (
                  <span key={id} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-3 text-[10.5px] text-muted-foreground">
            <div className="flex flex-wrap items-center gap-3">
              <span>
                Última sincronização: <strong className="text-foreground">{formatDate(doc.synced_at)}</strong>
              </span>
              {doc.run_id ? (
                <span>
                  Passagem: <span className="font-mono text-foreground">{String(doc.run_id).slice(0, 8)}</span>
                </span>
              ) : null}
              <span>
                Documento: <span className="font-mono">{String(doc.doc_id ?? nif)}</span>
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------- sincronização */

function SyncSection({
  meta,
  status,
  canWrite,
  isAdmin,
  onDone,
  onError,
}: {
  meta: ContribuintesMeta | null;
  status: ContribuintesStatus | null;
  canWrite: boolean;
  isAdmin: boolean;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [job, setJob] = useState<ContribuintesJob | null>(null);
  const [busy, setBusy] = useState(false);

  const running = job?.status === "running" || Boolean(status?.running);

  // Se a sincronização já estiver a correr (cron, script ou outra janela), liga-se-lhe.
  useEffect(() => {
    let cancelled = false;
    listContribuintesJobs()
      .then((data) => {
        if (cancelled) return;
        const current = data.jobs.find((entry) => entry.status === "running");
        if (current) setJob((previous) => (previous && previous.id === current.id ? previous : current));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [status?.running]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setInterval(() => {
      getContribuintesJob(job.id)
        .then((next) => {
          setJob(next);
          if (next.status !== "running") {
            setBusy(false);
            const summary = next.summary;
            if (next.status === "ok" && summary) {
              onDone(
                `Sincronização concluída: ${numberFormat.format(summary.unique ?? 0)} contribuintes únicos ` +
                  `em ${summary.duration_s ?? "?"} s${summary.deleted ? ` (${numberFormat.format(summary.deleted)} removidos)` : ""}.`,
              );
            } else if (next.status === "error") {
              onError(next.error ?? "Sincronização falhou");
            }
          }
        })
        .catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job, onDone, onError]);

  const start = async (sources?: string[]) => {
    if (!canWrite) {
      onError("Inicie sessão para sincronizar o índice de contribuintes.");
      return;
    }
    setBusy(true);
    try {
      const result = await startContribuintesSync({ sources, page_size: meta?.page_size });
      if (result.error) throw new Error(result.error);
      if (result.job_id) {
        setJob({ id: result.job_id, status: "running", started_at: result.started_at, progress: { phase: "start" } });
        onDone("Sincronização iniciada em segundo plano.");
      }
    } catch (err) {
      setBusy(false);
      onError(err instanceof Error ? err.message : "Não foi possível iniciar a sincronização");
    }
  };

  const wipe = async () => {
    if (!isAdmin) {
      onError("Só administradores podem esvaziar o índice.");
      return;
    }
    if (!window.confirm("Esvaziar o índice de contribuintes? Fica vazio até à próxima sincronização.")) return;
    try {
      const result = await deleteContribuintesIndex();
      if (result.error) throw new Error(result.error);
      onDone(`Índice esvaziado (${numberFormat.format(result.deleted ?? 0)} documentos).`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível esvaziar o índice");
    }
  };

  const sources = meta?.sources ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[12.5px] font-medium text-foreground">Sincronizar a partir de todas as fontes</div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Percorre {sources.length} índices da plataforma por agregação e reconstrói o índice de contribuintes.
              Os contribuintes que já não apareçam em nenhuma fonte são removidos.
            </p>
          </div>
          <button
            type="button"
            disabled={busy || running}
            onClick={() => void start()}
            className="flex items-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-400/15 px-3 py-2 text-[12px] font-medium text-emerald-100 hover:bg-emerald-400/25 disabled:opacity-50"
          >
            {busy || running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? "a sincronizar…" : "Sincronizar agora"}
          </button>
        </div>

        {job && (
          <div className="mt-3 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-[11px] text-muted-foreground">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{job.id}</span>
              <span className={job.status === "ok" ? "text-emerald-300" : job.status === "error" ? "text-rose-300" : "text-amber-300"}>
                {job.status}
              </span>
              <span>início {formatDateTime(job.started_at)}</span>
              {job.finished_at ? <span>fim {formatDateTime(job.finished_at)}</span> : null}
            </div>
            <div className="mt-1">
              {job.progress
                ? Object.entries(job.progress)
                    .filter(([key]) => key !== "at")
                    .map(([key, value]) => `${key}: ${String(value)}`)
                    .join(" · ")
                : "a preparar…"}
            </div>
            {job.summary?.sources && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(job.summary.sources).map(([id, info]) => (
                  <span key={id} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
                    {info.label ?? id}: {numberFormat.format(info.nifs ?? 0)} registos
                  </span>
                ))}
              </div>
            )}
            {job.summary?.errors?.length ? (
              <div className="mt-1.5 text-amber-300">
                {job.summary.errors.map((item) => `${item.source}.${item.spec}: ${item.error}`).join(" · ")}
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2">
          <Database size={14} className="text-muted-foreground" />
          <span className="text-[12.5px] font-medium text-foreground">Sincronizar só algumas fontes</span>
        </div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Uma sincronização parcial <strong>funde-se</strong> com o que já está indexado (não remove nada).
        </p>
        <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {sources.map((source) => (
            <label key={source.id} className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                className="accent-emerald-400"
                checked={selected.includes(source.id)}
                onChange={(event) =>
                  setSelected((current) => (event.target.checked ? [...current, source.id] : current.filter((id) => id !== source.id)))
                }
              />
              <span className="min-w-0 flex-1 truncate">{source.label}</span>
              <span className="font-mono text-[10px] opacity-70">{source.index}</span>
            </label>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={selected.length === 0 || busy || running}
            onClick={() => void start(selected)}
            className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-3 py-1.5 text-[11.5px] text-foreground hover:bg-white/15 disabled:opacity-50"
          >
            <Play size={13} /> Sincronizar selecionadas
          </button>
          <button
            type="button"
            onClick={() => setSelected(sources.map((source) => source.id))}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            Selecionar todas
          </button>
          <button
            type="button"
            disabled={!isAdmin}
            onClick={() => void wipe()}
            title={isAdmin ? "Esvaziar o índice" : "Só administradores"}
            className="ml-auto flex items-center gap-1.5 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-1.5 text-[11.5px] text-rose-200 hover:bg-rose-400/20 disabled:opacity-40"
          >
            <Trash2 size={13} /> Esvaziar índice
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2">
          <ShieldCheck size={14} className="text-muted-foreground" />
          <span className="text-[12.5px] font-medium text-foreground">Últimas sincronizações</span>
        </div>
        <div className="mt-2 space-y-1">
          {(status?.history ?? []).slice(0, 6).map((run) => (
            <div key={run.run_id ?? run.started_at} className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-muted-foreground">
              <span className="font-mono text-[10.5px]">{run.run_id}</span>
              <span className={run.status === "ok" ? "text-emerald-300" : "text-amber-300"}>{run.status}</span>
              <span>{run.full ? "completa" : "parcial"}</span>
              <span>{run.trigger === "cron" ? "cron" : "manual"}</span>
              <span>{numberFormat.format(run.unique ?? 0)} contribuintes</span>
              <span>{run.duration_s ?? "?"} s</span>
              <span className="ml-auto">{formatDateTime(run.finished_at)}</span>
            </div>
          ))}
          {!status?.history?.length && <div className="text-[11px] text-muted-foreground">Ainda não há sincronizações registadas.</div>}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- agenda */

function ScheduleSection({
  meta,
  schedule,
  canWrite,
  onSaved,
  onError,
}: {
  meta: ContribuintesMeta | null;
  schedule: ContribuintesSchedule | null;
  canWrite: boolean;
  onSaved: (next: ContribuintesSchedule, message: string) => void;
  onError: (message: string) => void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [cron, setCron] = useState("0 3 * * *");
  const [timezone, setTimezone] = useState("Europe/Lisbon");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!schedule) return;
    setEnabled(Boolean(schedule.enabled));
    setCron(schedule.cron || "0 3 * * *");
    setTimezone(schedule.timezone || "Europe/Lisbon");
  }, [schedule]);

  const save = async () => {
    if (!canWrite) {
      onError("Inicie sessão para alterar o agendamento.");
      return;
    }
    setSaving(true);
    try {
      const next = await saveContribuintesSchedule({ enabled, cron, timezone });
      onSaved(next, enabled ? `Sincronização automática ativa (${cron}).` : "Sincronização automática desligada.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível guardar o agendamento");
    } finally {
      setSaving(false);
    }
  };

  const scheduler = schedule?.scheduler;

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2">
          <CalendarClock size={15} className="text-emerald-300" />
          <span className="text-[12.5px] font-medium text-foreground">Sincronização automática (cron)</span>
          <span
            className={`ml-auto rounded-full border px-2 py-0.5 text-[10.5px] ${
              scheduler?.active
                ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                : schedule?.enabled
                  ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
                  : "border-white/10 bg-white/5 text-muted-foreground"
            }`}
          >
            {scheduler?.active ? "ativa" : schedule?.enabled ? "configurada mas inativa" : "desligada"}
          </span>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Percorre {meta?.sources.length ?? 0} índices e reconstrói o índice de contribuintes. Expressão em 5 campos
          (minuto hora dia mês dia-semana); ex.: <span className="font-mono">0 3 * * *</span> (todos os dias às 03:00) ou{" "}
          <span className="font-mono">30 6 * * 1</span> (segundas-feiras às 06:30).
        </p>

        <div className="mt-3 flex flex-wrap items-end gap-3 text-[11px]">
          <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-muted-foreground">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="accent-emerald-400" />
            ligar sincronização automática
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Expressão cron</span>
            <input
              value={cron}
              onChange={(event) => setCron(event.target.value)}
              className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 font-mono text-[12px] text-foreground outline-none focus:border-emerald-400/40"
              placeholder="0 3 * * *"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Fuso horário</span>
            <input
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-[12px] text-foreground outline-none focus:border-emerald-400/40"
              placeholder="Europe/Lisbon"
            />
          </label>
          <button
            type="button"
            disabled={saving}
            onClick={() => void save()}
            className="flex items-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-400/15 px-3 py-2 text-[12px] font-medium text-emerald-100 hover:bg-emerald-400/25 disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Guardar agendamento
          </button>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide">Próxima execução</div>
            <div className="text-[12px] text-foreground">{scheduler?.next_run_time ? formatDateTime(scheduler.next_run_time) : "—"}</div>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide">Agendador</div>
            <div className="text-[12px] text-foreground">
              {scheduler?.available ? "ativo" : "indisponível"}
              {scheduler?.error ? ` — ${scheduler.error}` : ""}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide">Última passagem</div>
            <div className="text-[12px] text-foreground">
              {schedule?.last_run?.finished_at ? formatDateTime(schedule.last_run.finished_at) : "—"}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2">
          <Play size={14} className="text-muted-foreground" />
          <span className="text-[12.5px] font-medium text-foreground">Histórico recente</span>
        </div>
        <div className="mt-2 space-y-1">
          {(schedule?.history ?? []).map((run) => (
            <div key={run.run_id ?? run.started_at} className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-muted-foreground">
              <span className="font-mono text-[10.5px]">{run.run_id}</span>
              <span>{run.trigger === "cron" ? "cron" : "manual"}</span>
              <span>{numberFormat.format(run.unique ?? 0)} contribuintes</span>
              <span>{run.duration_s ?? "?"} s</span>
              <span className="ml-auto">{formatDateTime(run.finished_at)}</span>
            </div>
          ))}
          {!schedule?.history?.length && <div className="text-[11px] text-muted-foreground">Ainda não há execuções registadas.</div>}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ cobertura */

function CoverageSection({ meta, status }: { meta: ContribuintesMeta | null; status: ContribuintesStatus | null }) {
  const formats = meta?.reports?.formats ?? [];
  const cards = [
    { label: "Contribuintes", value: status?.documents, icon: <Users size={14} /> },
    { label: "Pessoas coletivas", value: status?.companies, icon: <Landmark size={14} /> },
    { label: "Com contratos públicos", value: status?.with_contracts, icon: <ShieldCheck size={14} /> },
    { label: "Com processos CIRE", value: status?.with_cire, icon: <Gavel size={14} /> },
    { label: "Com localização conhecida", value: status?.with_location, icon: <MapPin size={14} /> },
    { label: "Distritos representados", value: (status?.districts ?? []).length, icon: <BarChart3 size={14} /> },
  ];

  // Tipos de contribuinte (gráfico de barras horizontais, para caberem os nomes).
  const typeData = useMemo(
    () =>
      (status?.types ?? []).map((facet) => ({
        label: facet.label ?? facet.key,
        key: facet.key,
        count: facet.count,
      })),
    [status?.types],
  );

  // Localização: distritos ordenados por nº de contribuintes (top 12).
  const districtData = useMemo(
    () => (status?.districts ?? []).slice(0, 12).map((facet) => ({ label: facet.key, count: facet.count })),
    [status?.districts],
  );

  // Grafo composto: cada barra é um distrito, repartida pelos tipos de contribuinte.
  const typeKeys = useMemo(() => (status?.types ?? []).map((facet) => facet.key), [status?.types]);
  const typeLabels = useMemo(
    () => Object.fromEntries((status?.types ?? []).map((facet) => [facet.key, facet.label ?? facet.key])),
    [status?.types],
  );
  /** Tooltip do gráfico composto: traduz a chave do tipo na etiqueta legível. */
  const stackedTooltip: RechartsFormatter = (value, name) => [
    numberFormat.format(Number(value)),
    typeLabels[String(name)] ?? String(name),
  ];
  const matrixData = useMemo(
    () =>
      (status?.types_by_district ?? []).slice(0, 12).map((row) => {
        const entry: Record<string, string | number> = { label: row.key, total: row.count };
        (row.types ?? []).forEach((facet) => {
          entry[facet.key] = facet.count;
        });
        return entry;
      }),
    [status?.types_by_district],
  );

  const topMunicipalities = (status?.municipalities ?? []).slice(0, 14);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11.5px] text-muted-foreground">
          Distribuição do índice por <strong className="text-foreground">tipo de contribuinte</strong> e por{" "}
          <strong className="text-foreground">localização</strong> (distrito e concelho).
        </div>
        <ReportButtons
          formats={formats}
          onExport={async (format) => {
            const { blob, filename } = await exportContribuintesReport({ sort: "contracts" }, format, 1000);
            saveContribuintesReport(blob, filename);
          }}
          hint="exporta os 1000 maiores por contratos"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((card) => (
          <div key={card.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              {card.icon}
              <span className="text-[11px]">{card.label}</span>
            </div>
            <div className="mt-1 text-[20px] font-semibold text-foreground">{numberFormat.format(card.value ?? 0)}</div>
          </div>
        ))}
      </div>

      {!status?.with_location ? (
        <div className="rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
          A localização só existe para os contribuintes cujos contratos ou publicações societárias a trazem.
          Sincronize o índice (secção «Sincronização») para a preencher com os locais de execução dos contratos.
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="text-[11.5px] font-medium text-foreground">Tipo de contribuinte</div>
          <div className="mt-2 h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={typeData} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" horizontal={false} />
                <XAxis type="number" stroke="#9aa0aa" fontSize={11} tickFormatter={(value) => compactFormat.format(Number(value))} />
                <YAxis type="category" dataKey="label" stroke="#9aa0aa" fontSize={11} width={140} />
                <Tooltip
                  contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 11 }}
                  formatter={countTooltip}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {typeData.map((entry) => (
                    <Cell key={entry.key} fill={TYPE_COLORS[entry.key] ?? TYPE_COLORS.desconhecido} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="text-[11.5px] font-medium text-foreground">Localização · distrito</div>
          <div className="mt-2 h-[260px]">
            {districtData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={districtData} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" horizontal={false} />
                  <XAxis type="number" stroke="#9aa0aa" fontSize={11} tickFormatter={(value) => compactFormat.format(Number(value))} />
                  <YAxis type="category" dataKey="label" stroke="#9aa0aa" fontSize={11} width={140} />
                  <Tooltip
                    contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 11 }}
                    formatter={countTooltip}
                  />
                  <Bar dataKey="count" fill="#2dd4bf" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="grid h-full place-items-center px-4 text-center text-[11px] text-muted-foreground">
                Ainda sem localização no índice. A sincronização preenche-a a partir dos contratos
                («país, distrito, concelho») e das publicações societárias.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <div className="flex flex-wrap items-baseline gap-2">
          <div className="text-[11.5px] font-medium text-foreground">Tipos de contribuinte por distrito</div>
          <span className="text-[10.5px] text-muted-foreground">
            cada barra é um distrito, repartida pelos tipos de contribuinte
          </span>
        </div>
        <div className="mt-2 h-[320px]">
          {matrixData.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={matrixData} margin={{ left: 8, right: 16, bottom: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" vertical={false} />
                <XAxis dataKey="label" stroke="#9aa0aa" fontSize={10.5} angle={-35} textAnchor="end" height={60} interval={0} />
                <YAxis stroke="#9aa0aa" fontSize={11} tickFormatter={(value) => compactFormat.format(Number(value))} />
                <Tooltip
                  contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 11 }}
                  formatter={stackedTooltip}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} formatter={(name) => typeLabels[name] ?? name} />
                {typeKeys.map((key) => (
                  <Bar key={key} dataKey={key} stackId="tipos" fill={TYPE_COLORS[key] ?? TYPE_COLORS.desconhecido} radius={[0, 0, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="grid h-full place-items-center text-[11px] text-muted-foreground">
              Sem dados de localização — sincronize o índice.
            </div>
          )}
        </div>
      </div>

      {topMunicipalities.length ? (
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center gap-2 text-[11.5px] font-medium text-foreground">
            <MapPin size={13} className="text-teal-300" />
            Concelhos com mais contribuintes
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {topMunicipalities.map((facet) => (
              <span
                key={facet.key}
                className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground"
              >
                {facet.key} <span className="text-foreground">{numberFormat.format(facet.count)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <FacetCard title="País" facets={status?.countries} />
        <FacetCard title="Fontes" facets={status?.sources} />
        <FacetCard title="Papéis" facets={(status?.roles ?? []).map((facet) => ({ ...facet, label: roleLabel(facet.key) }))} />
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-[11px] text-muted-foreground">
          <div className="flex flex-wrap items-center gap-3">
            <span>
              Valor contratual agregado: <strong className="text-foreground">{currencyFormat.format(status?.contracts_value ?? 0)}</strong>
            </span>
            <span>
              Última atividade registada: <strong className="text-foreground">{formatDate(status?.last_seen)}</strong>
            </span>
            <span>
              NIF a confirmar (dígito de controlo): <strong className="text-foreground">{numberFormat.format(status?.invalid_nif ?? 0)}</strong>
            </span>
            <span>
              Fontes percorridas: <strong className="text-foreground">{meta?.sources.length ?? 0}</strong>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function FacetCard({ title, facets }: { title: string; facets?: ContribuinteFacet[] }) {
  const total = (facets ?? []).reduce((sum, facet) => sum + facet.count, 0);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
      <div className="text-[11.5px] font-medium text-foreground">{title}</div>
      <div className="mt-2 space-y-1">
        {(facets ?? []).map((facet) => (
          <div key={facet.key} className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className="w-40 truncate">{facet.label ?? facet.key}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
              <span
                className="block h-full rounded-full bg-emerald-400/60"
                style={{ width: `${total ? Math.max(2, Math.round((facet.count / total) * 100)) : 0}%` }}
              />
            </span>
            <span className="w-16 text-right text-foreground">{numberFormat.format(facet.count)}</span>
          </div>
        ))}
        {!facets?.length && <div className="text-[11px] text-muted-foreground">Sem dados — sincronize o índice.</div>}
      </div>
    </div>
  );
}
