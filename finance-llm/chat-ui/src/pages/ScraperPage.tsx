/**
 * Recolha de dados de sites («Scraping») — o módulo de recolha do IQ OS.
 *
 * Cinco áreas, no mesmo desenho dos outros módulos:
 *
 * - **Templates**: definições prontas para sites concretos (Jornal Económico,
 *   ECO, Público, Observador, Expansión, …). Escolhe-se o site, testa-se contra
 *   a página real e a fonte fica criada — sem escrever seletores à mão.
 * - **Fontes**: as definições declarativas (URL, *fetcher*, seletores, campos,
 *   paginação, cron e, se for caso disso, o texto integral do artigo).
 * - **Execuções**: histórico (estado, itens, indexados, páginas, erros) e os
 *   itens gravados em JSONL por execução.
 * - **Pesquisa**: pesquisa livre sobre os itens recolhidos no Elasticsearch,
 *   com facetas por fonte, etiqueta e dia.
 * - **Agenda**: jobs de cron e próximas execuções.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Database,
  Eye,
  FileJson,
  Globe2,
  Layers,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rss,
  Search,
  Settings2,
  Sparkles,
  Tag,
  Trash2,
  Wand2,
  X,
  XCircle,
} from "lucide-react";
import {
  applyScraperTemplate,
  createScraperSource,
  createScraperSourceFromTemplate,
  deleteScraperSource,
  getScraperJobs,
  getScraperMeta,
  getScraperRunItems,
  getScraperStats,
  getScraperStatus,
  getScraperTemplate,
  listScraperRuns,
  listScraperSources,
  listScraperTemplates,
  previewScraperSource,
  previewScraperTemplate,
  reloadScraperJobs,
  runScraperSource,
  searchScraperItems,
  suggestScraperSource,
  updateScraperSource,
  type ScraperField,
  type ScraperDetail,
  type ScraperItem,
  type ScraperMeta,
  type ScraperPreview,
  type ScraperRun,
  type ScraperSelectorKind,
  type ScraperSource,
  type ScraperStats,
  type ScraperStatus,
  type ScraperSuggestion,
  type ScraperTemplate,
} from "../scraperApi";
import {
  ItemsCollection,
  ItemsViewToggle,
  type DisplayItem,
  type ItemsView,
} from "../components/ItemsView";
import { useAuth } from "../auth";

/* ------------------------------------------------------------- navegação */

export type ScraperSection = "templates" | "sources" | "runs" | "search" | "schedule";

export const SCRAPER_SECTIONS: { id: ScraperSection; label: string; icon: React.ReactNode }[] = [
  { id: "templates", label: "Templates", icon: <Layers size={14} /> },
  { id: "sources", label: "Fontes", icon: <Globe2 size={14} /> },
  { id: "runs", label: "Execuções", icon: <Play size={14} /> },
  { id: "search", label: "Pesquisa", icon: <Search size={14} /> },
  { id: "schedule", label: "Agenda", icon: <CalendarClock size={14} /> },
];

/** Vista da plataforma correspondente a cada secção (usada pelo App/dock). */
export const SCRAPER_SECTION_VIEWS: Record<ScraperSection, string> = {
  templates: "scraper-templates",
  sources: "scraper",
  runs: "scraper-execucoes",
  search: "scraper-pesquisa",
  schedule: "scraper-agenda",
};

export function scraperSectionForView(view: string): ScraperSection | null {
  const entry = (Object.entries(SCRAPER_SECTION_VIEWS) as [ScraperSection, string][]).find(([, v]) => v === view);
  return entry ? entry[0] : null;
}

export function scraperSectionTitle(section: ScraperSection): string {
  return `Recolha · ${SCRAPER_SECTIONS.find((s) => s.id === section)?.label ?? "Fontes"}`;
}

/* ------------------------------------------------------------- utilitários */

const dateFormat = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });
const numberFormat = new Intl.NumberFormat("pt-PT");

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return dateFormat.format(date);
}

function formatDuration(ms?: number | null): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60_000)} min`;
}

const FETCHER_LABEL: Record<string, string> = {
  http: "HTTP",
  dynamic: "Browser",
  stealth: "Stealth",
};

const FETCHER_TONE: Record<string, string> = {
  http: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  dynamic: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  stealth: "border-amber-400/30 bg-amber-400/10 text-amber-200",
};

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${className}`}>{children}</span>;
}

function StatusPill({ status }: { status: string }) {
  if (status === "completed") {
    return (
      <Pill className="border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
        <CheckCircle2 size={10} /> Concluída
      </Pill>
    );
  }
  if (status === "failed") {
    return (
      <Pill className="border-rose-400/30 bg-rose-400/10 text-rose-200">
        <XCircle size={10} /> Falhada
      </Pill>
    );
  }
  return (
    <Pill className="border-amber-400/30 bg-amber-400/10 text-amber-200">
      <Loader2 size={10} className="animate-spin" /> Em curso
    </Pill>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3" title={hint}>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function emptySource(): Partial<ScraperSource> {
  return {
    name: "",
    description: "",
    url: "",
    enabled: false,
    fetcher: "http",
    list: { selector: "", type: "css" },
    fields: [{ name: "titulo", label: "Título", selector: "h1::text", type: "css", cast: "text" }],
    pagination: { selector: "", type: "css", attr: "href", max_pages: 1 },
    options: {},
    schedule: { cron: "", timezone: "Europe/Lisbon" },
    respect_robots: true,
    tags: [],
    id_fields: [],
    detail: { enabled: false, selector: "", max_items: 0, delay: 0.5, max_chars: 20000 },
  };
}

/* ------------------------------------------------------------- página */

interface ScraperPageProps {
  section: ScraperSection;
  onSectionChange?: (section: ScraperSection) => void;
}

export default function ScraperPage({ section, onSectionChange }: ScraperPageProps) {
  const { user } = useAuth();
  const [meta, setMeta] = useState<ScraperMeta | null>(null);
  const [status, setStatus] = useState<ScraperStatus | null>(null);
  const [stats, setStats] = useState<ScraperStats | null>(null);
  const [sources, setSources] = useState<ScraperSource[]>([]);
  const [templates, setTemplates] = useState<ScraperTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<ScraperSource> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextMeta, nextStatus, nextStats, nextSources, nextTemplates] = await Promise.all([
        getScraperMeta(),
        getScraperStatus(),
        getScraperStats(),
        listScraperSources(),
        // A galeria é estática no servidor; se falhar, a página continua a servir.
        listScraperTemplates().catch(() => ({ total: 0, categories: [], items: [] })),
      ]);
      setMeta(nextMeta);
      setStatus(nextStatus);
      setStats(nextStats);
      setSources(nextSources.items);
      setTemplates(nextTemplates.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar o módulo de recolha.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Enquanto houver execuções em curso, o painel atualiza-se sozinho.
  const hasRunning = sources.some((source) => source.running);
  useEffect(() => {
    if (!hasRunning) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [hasRunning, refresh]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const runSource = async (source: ScraperSource) => {
    setBusy(source.id);
    try {
      const result = await runScraperSource(source.id);
      setNotice(result.already_running ? `«${source.name}» já estava a recolher.` : `Recolha de «${source.name}» iniciada.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível iniciar a recolha.");
    } finally {
      setBusy(null);
    }
  };

  const toggleSource = async (source: ScraperSource) => {
    setBusy(source.id);
    try {
      await updateScraperSource(source.id, { enabled: !source.enabled });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível alterar a fonte.");
    } finally {
      setBusy(null);
    }
  };

  const removeSource = async (source: ScraperSource) => {
    if (!window.confirm(`Apagar a fonte «${source.name}»? Os itens já recolhidos ficam no índice.`)) return;
    setBusy(source.id);
    try {
      await deleteScraperSource(source.id);
      setNotice(`Fonte «${source.name}» apagada.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível apagar a fonte.");
    } finally {
      setBusy(null);
    }
  };

  const openNewSource = () => {
    const draft = emptySource();
    if (meta?.fetchers?.length) draft.fetcher = meta.fetchers[0].id;
    draft.schedule = { cron: "", timezone: meta?.default_timezone ?? "Europe/Lisbon" };
    setEditing(draft);
  };

  /** Volta a aplicar o template à fonte (o site mudou de marcação). */
  const applyTemplate = async (source: ScraperSource) => {
    const templateName = templates.find((entry) => entry.id === source.template_id)?.name ?? source.template_id;
    if (
      !window.confirm(
        `Reaplicar a definição do template «${templateName}» à fonte «${source.name}»?\n\n` +
          "Os seletores, os campos e o texto integral voltam aos do template. Nome, agenda, interruptor e etiquetas mantêm-se.",
      )
    )
      return;
    setBusy(source.id);
    try {
      await applyScraperTemplate(source.id);
      setNotice(`Fonte «${source.name}» sincronizada com o template ${templateName}.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível aplicar o template.");
    } finally {
      setBusy(null);
    }
  };

  /** Abre o editor com a definição do template, para revisão antes de guardar. */
  const useTemplate = async (template: ScraperTemplate) => {
    setBusy(`template:${template.id}`);
    try {
      const { item } = await getScraperTemplate(template.id);
      const draft = item.source ?? { name: template.name, url: template.url };
      setEditing({ ...draft, name: draft.name || template.name });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível abrir o template.");
    } finally {
      setBusy(null);
    }
  };

  /** Cria a fonte a partir do template, tal como está (agendamento desligado). */
  const createFromTemplate = async (template: ScraperTemplate) => {
    setBusy(`template:${template.id}`);
    try {
      const { item } = await createScraperSourceFromTemplate(template.id, { name: template.name });
      setNotice(`Fonte «${item.name}» criada a partir do template ${template.name}.`);
      await refresh();
      onSectionChange?.("sources");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível criar a fonte a partir do template.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 pb-32 pt-6 sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-amber-300 via-orange-500 to-rose-600 text-white shadow-lg shadow-orange-500/25">
            <Globe2 size={20} />
          </span>
          <div>
            <h1 className="text-xl font-semibold">Recolha de dados</h1>
            <p className="text-sm text-muted-foreground">
              Definir fontes, recolher de sites (HTTP ou browser) e agendar com cron — com pesquisa sobre tudo o que foi recolhido.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            <RefreshCw size={14} /> Atualizar
          </button>
          <button
            type="button"
            onClick={openNewSource}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-amber-400 to-orange-600 px-3 py-2 text-xs font-medium text-white shadow-lg shadow-orange-500/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300"
          >
            <Plus size={14} /> Nova fonte
          </button>
        </div>
      </header>

      {/* Estado do ambiente */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {status ? (
          <>
            <Pill
              className={
                status.scrapling
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                  : "border-rose-400/30 bg-rose-400/10 text-rose-200"
              }
            >
              {status.scrapling ? <CheckCircle2 size={10} /> : <AlertTriangle size={10} />}
              Scrapling {status.scrapling ? status.scrapling_version || "instalado" : "em falta"}
            </Pill>
            <Pill
              className={
                status.elasticsearch
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                  : "border-amber-400/30 bg-amber-400/10 text-amber-200"
              }
            >
              <Database size={10} /> Elasticsearch {status.elasticsearch ? "ligado" : "indisponível"}
            </Pill>
            <Pill
              className={
                status.scheduler?.available
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                  : "border-amber-400/30 bg-amber-400/10 text-amber-200"
              }
            >
              <CalendarClock size={10} /> Cron {status.scheduler?.available ? `${status.scheduler.jobs_total} jobs` : "inativo"}
            </Pill>
            {status.browsers ? (
              <Pill className="border-violet-400/30 bg-violet-400/10 text-violet-200">
                <Sparkles size={10} /> Browsers disponíveis
              </Pill>
            ) : (
              <Pill className="border-white/10 bg-white/5 text-muted-foreground" >
                <AlertTriangle size={10} /> Browsers não instalados (só HTTP)
              </Pill>
            )}
          </>
        ) : null}
      </div>

      {status && status.browsers === false && status.browsers_hint ? (
        <p className="mt-2 text-[11px] text-muted-foreground">{status.browsers_hint}</p>
      ) : null}

      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} className="mt-0.5" />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Fechar aviso">
            <X size={14} />
          </button>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-100">
          <CheckCircle2 size={14} /> {notice}
        </div>
      ) : null}
      {status?.scrapling_error ? (
        <div className="mt-4 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-xs text-amber-100">
          <p>
            <strong className="font-medium">Scrapling:</strong> {status.scrapling_error}
          </p>
          {status.python ? (
            <p className="mt-2 text-[11px] text-amber-200/90">
              A API está a correr com <code className="rounded bg-black/30 px-1">{status.python}</code>
              {status.python_version ? ` (Python ${status.python_version})` : ""}. Se o projeto usa
              <code className="mx-1 rounded bg-black/30 px-1">c:\LLMFinance\.venv\Scripts\python.exe</code>, reinicie a API com esse
              interpretador (é o que os scripts <code>start_solution.ps1</code> e <code>start.py</code> usam).
            </p>
          ) : null}
        </div>
      ) : null}

      {/* KPIs */}
      {stats ? (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Kpi label="Fontes" value={stats.sources_total} hint={`${stats.sources_enabled} com agendamento`} />
          <Kpi label="Execuções" value={stats.runs_total} hint={`${stats.runs_completed} concluídas`} />
          <Kpi label="Itens recolhidos" value={numberFormat.format(stats.items_scraped)} hint="gravados em JSONL" />
          <Kpi
            label="Itens indexados"
            value={numberFormat.format(stats.items_indexed)}
            hint={stats.items_with_text ? `${numberFormat.format(stats.items_with_text)} com texto integral` : "pesquisáveis no Elasticsearch"}
          />
          <Kpi label="Última recolha" value={formatDate(stats.last_run?.finished_at ?? stats.last_run?.started_at)} hint={stats.last_run?.source_name ?? "—"} />
        </div>
      ) : null}

      {/* Separadores */}
      <nav className="mt-5 flex flex-wrap gap-1 rounded-2xl border border-white/10 bg-white/5 p-1" aria-label="Secções da recolha">
        {SCRAPER_SECTIONS.map((entry) => {
          const active = entry.id === section;
          return (
            <button
              key={entry.id}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => (onSectionChange ? onSectionChange(entry.id) : undefined)}
              className={`inline-flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 ${
                active ? "bg-white/10 font-medium text-foreground" : "text-muted-foreground hover:bg-white/5"
              }`}
            >
              {entry.icon}
              {entry.label}
            </button>
          );
        })}
      </nav>

      <div className="mt-5">
        {loading ? (
          <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" /> A carregar o módulo de recolha…
          </div>
        ) : section === "templates" ? (
          <TemplatesSection
            templates={templates}
            categories={meta?.template_categories ?? []}
            sources={sources}
            busy={busy}
            canWrite={Boolean(user)}
            onUse={(template) => void useTemplate(template)}
            onCreate={(template) => void createFromTemplate(template)}
            onOpenSource={(source) => setEditing(source)}
            onError={setError}
          />
        ) : section === "sources" ? (
          <SourcesSection
            sources={sources}
            templates={templates}
            busy={busy}
            onRun={runSource}
            onToggle={toggleSource}
            onEdit={(source) => setEditing(source)}
            onDelete={removeSource}
            onApplyTemplate={(source) => void applyTemplate(source)}
            onNew={openNewSource}
          />
        ) : section === "runs" ? (
          <RunsSection sources={sources} />
        ) : section === "search" ? (
          <SearchSection sources={sources} />
        ) : (
          <ScheduleSection status={status} sources={sources} onRefresh={refresh} onError={setError} onNotice={setNotice} />
        )}
      </div>

      {editing ? (
        <SourceEditor
          value={editing}
          meta={meta}
          canWrite={Boolean(user)}
          onClose={() => setEditing(null)}
          onSaved={async (message) => {
            setEditing(null);
            setNotice(message);
            await refresh();
          }}
          onError={(message) => setError(message)}
        />
      ) : null}
    </div>
  );
}

/* ----------------------------------------------------------- templates */

/**
 * Galeria de definições prontas: escolhe-se o site, testa-se contra a página
 * real e cria-se a fonte. Resolve o problema de ter de escrever seletores à mão
 * para cada jornal.
 */
function TemplatesSection({
  templates,
  categories,
  sources,
  busy,
  canWrite,
  onUse,
  onCreate,
  onOpenSource,
  onError,
}: {
  templates: ScraperTemplate[];
  categories: string[];
  sources: ScraperSource[];
  busy: string | null;
  canWrite: boolean;
  onUse: (template: ScraperTemplate) => void;
  onCreate: (template: ScraperTemplate) => void;
  onOpenSource: (source: ScraperSource) => void;
  onError: (message: string) => void;
}) {
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [tests, setTests] = useState<Record<string, ScraperPreview>>({});
  const [testing, setTesting] = useState<string | null>(null);

  const sourceFor = (template: ScraperTemplate) =>
    sources.find(
      (source) =>
        source.template_id === template.id || source.url.replace(/\/+$/, "") === template.url.replace(/\/+$/, ""),
    );

  const test = async (template: ScraperTemplate) => {
    setTesting(template.id);
    try {
      const result = await previewScraperTemplate(template.id, 3, 1);
      setTests((previous) => ({ ...previous, [template.id]: result }));
      if (!result.ok && result.error) onError(`Template ${template.name}: ${result.error}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao testar o template.");
    } finally {
      setTesting(null);
    }
  };

  const needle = query.trim().toLowerCase();
  const visible = templates.filter((template) => {
    if (category && template.category !== category) return false;
    if (!needle) return true;
    return (
      template.name.toLowerCase().includes(needle) ||
      template.site.toLowerCase().includes(needle) ||
      template.description.toLowerCase().includes(needle) ||
      template.tags.some((tag) => tag.toLowerCase().includes(needle))
    );
  });

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-600 text-white">
              <Layers size={18} />
            </span>
            <div>
              <h2 className="text-base font-semibold">Templates de sites</h2>
              <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
                Definições prontas para sites concretos: URL da lista, seletores dos campos, agendamento sugerido e —
                nos jornais — o seletor do corpo do artigo, para que a recolha traga também o texto integral. Teste um
                template, ajuste-o se quiser e crie a fonte.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Procurar site…"
              className="w-44 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
              aria-label="Procurar template"
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => setCategory("")}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              category === "" ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
            }`}
          >
            Todas ({templates.length})
          </button>
          {categories.map((entry) => {
            const count = templates.filter((template) => template.category === entry).length;
            if (!count) return null;
            return (
              <button
                key={entry}
                type="button"
                onClick={() => setCategory(entry)}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  category === entry ? "border-orange-400/40 bg-orange-400/15 text-orange-100" : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
                }`}
              >
                {entry} ({count})
              </button>
            );
          })}
        </div>
      </div>

      {!visible.length ? (
        <div className="glass-card rounded-2xl px-6 py-10 text-center text-sm text-muted-foreground">
          Sem templates para este filtro.
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {visible.map((template) => {
          const existing = sourceFor(template);
          const result = tests[template.id];
          const isBusy = busy === `template:${template.id}`;
          return (
            <article key={template.id} className="glass-card flex flex-col rounded-2xl p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">{template.name}</h3>
                  <a
                    href={template.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] text-muted-foreground hover:text-foreground"
                  >
                    {template.site}
                  </a>
                </div>
                <Pill className={FETCHER_TONE[template.fetcher] ?? "border-white/10 bg-white/5 text-muted-foreground"}>
                  {FETCHER_LABEL[template.fetcher] ?? template.fetcher}
                </Pill>
              </div>

              <p className="mt-2 flex-1 text-xs text-muted-foreground">{template.description}</p>

              <div className="mt-2 flex flex-wrap gap-1">
                {template.detail ? (
                  <Pill className="border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                    <FileJson size={10} /> texto integral
                  </Pill>
                ) : null}
                {template.requires_browser ? (
                  <Pill className="border-violet-400/30 bg-violet-400/10 text-violet-200">
                    <Sparkles size={10} /> precisa de browser
                  </Pill>
                ) : null}
                <Pill className="border-white/10 bg-white/5 text-muted-foreground">
                  <Clock size={10} /> {template.cron || "manual"}
                </Pill>
                <Pill className="border-white/10 bg-white/5 text-muted-foreground">
                  {template.fields.length} campos
                </Pill>
                {existing ? (
                  <Pill className="border-sky-400/30 bg-sky-400/10 text-sky-200">
                    <CheckCircle2 size={10} /> já configurada
                  </Pill>
                ) : null}
              </div>

              {template.notes ? (
                <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/80">{template.notes}</p>
              ) : null}

              {result ? (
                <div
                  className={`mt-3 rounded-xl border px-3 py-2 text-[11px] ${
                    result.ok && result.total
                      ? "border-emerald-400/25 bg-emerald-400/5 text-emerald-100"
                      : "border-rose-400/25 bg-rose-400/5 text-rose-100"
                  }`}
                >
                  {result.ok && result.total ? (
                    <>
                      <p>
                        {result.total} itens na lista
                        {result.detail_count ? ` · ${result.detail_count} com texto integral` : ""}
                        {result.duplicates ? ` · ${result.duplicates} repetidos ignorados` : ""}
                      </p>
                      {result.items?.[0]?.title ? (
                        <p className="mt-1 truncate text-muted-foreground">Exemplo: {result.items[0].title}</p>
                      ) : null}
                    </>
                  ) : (
                    <p>{result.error ?? "O site não devolveu itens. Os seletores podem ter mudado."}</p>
                  )}
                </div>
              ) : null}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void test(template)}
                  disabled={testing === template.id || isBusy || !canWrite}
                  title={canWrite ? "Recolher 3 itens da página (não guarda nem indexa)" : "É precisa uma sessão para testar"}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] hover:bg-white/10 disabled:opacity-50"
                >
                  {testing === template.id ? <Loader2 size={12} className="animate-spin" /> : <Eye size={12} />} Testar
                </button>
                {existing ? (
                  <button
                    type="button"
                    onClick={() => onOpenSource(existing)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-sky-400/30 bg-sky-400/10 px-2.5 py-1.5 text-[11px] text-sky-100 hover:bg-sky-400/20"
                  >
                    <Pencil size={12} /> Abrir fonte
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onUse(template)}
                      disabled={isBusy || !canWrite}
                      title={canWrite ? "Abrir o editor com esta definição" : "É precisa uma sessão"}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] hover:bg-white/10 disabled:opacity-50"
                    >
                      {isBusy ? <Loader2 size={12} className="animate-spin" /> : <Settings2 size={12} />} Ajustar
                    </button>
                    <button
                      type="button"
                      onClick={() => onCreate(template)}
                      disabled={isBusy || !canWrite}
                      title={canWrite ? "Criar a fonte já (agendamento desligado)" : "É precisa uma sessão"}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-amber-400 to-orange-600 px-2.5 py-1.5 text-[11px] font-medium text-white disabled:opacity-50"
                    >
                      {isBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Criar fonte
                    </button>
                  </>
                )}
                {template.tags.length ? (
                  <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Tag size={10} /> {template.tags.slice(0, 2).join(", ")}
                  </span>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- fontes */

function SourcesSection({
  sources,
  templates,
  busy,
  onRun,
  onToggle,
  onEdit,
  onDelete,
  onApplyTemplate,
  onNew,
}: {
  sources: ScraperSource[];
  templates: ScraperTemplate[];
  busy: string | null;
  onRun: (source: ScraperSource) => void;
  onToggle: (source: ScraperSource) => void;
  onEdit: (source: ScraperSource) => void;
  onDelete: (source: ScraperSource) => void;
  onApplyTemplate: (source: ScraperSource) => void;
  onNew: () => void;
}) {
  if (!sources.length) {
    return (
      <div className="glass-card rounded-2xl px-6 py-12 text-center">
        <Globe2 size={28} className="mx-auto text-muted-foreground" />
        <p className="mt-3 text-sm font-medium">Ainda não há fontes definidas</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Uma fonte é uma definição: URL, tipo de pedido, seletores dos campos e a periodicidade (cron).
        </p>
        <button
          type="button"
          onClick={onNew}
          className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-amber-400 to-orange-600 px-3 py-2 text-xs font-medium text-white"
        >
          <Plus size={14} /> Criar a primeira fonte
        </button>
      </div>
    );
  }

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {sources.map((source) => {
        const lastRun = source.last_run;
        const running = source.running || lastRun?.status === "running";
        return (
          <article key={source.id} className="glass-card flex flex-col gap-3 rounded-2xl p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-sm font-semibold">{source.name}</h2>
                  <Pill className={FETCHER_TONE[source.fetcher] ?? "border-white/10 bg-white/5"}>
                    <Globe2 size={10} /> {FETCHER_LABEL[source.fetcher] ?? source.fetcher}
                  </Pill>
                  {source.enabled ? (
                    <Pill className="border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                      <Clock size={10} /> {source.schedule.cron || "sem cron"}
                    </Pill>
                  ) : (
                    <Pill className="border-white/10 bg-white/5 text-muted-foreground">desligada</Pill>
                  )}
                  {source.template_id ? (
                    <Pill className="border-amber-400/30 bg-amber-400/10 text-amber-200">
                      <Layers size={10} /> {templates.find((entry) => entry.id === source.template_id)?.name ?? source.template_id}
                    </Pill>
                  ) : null}
                  {running ? <StatusPill status="running" /> : null}
                </div>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 block truncate text-[11px] text-sky-300 hover:underline"
                >
                  {source.url}
                </a>
                {source.description ? <p className="mt-1 text-xs text-muted-foreground">{source.description}</p> : null}
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={source.enabled}
                aria-label={`${source.enabled ? "Desligar" : "Ligar"} agendamento de ${source.name}`}
                onClick={() => onToggle(source)}
                disabled={busy === source.id}
                className={`relative h-6 w-11 shrink-0 rounded-full border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 ${
                  source.enabled ? "border-emerald-400/40 bg-emerald-400/30" : "border-white/15 bg-white/5"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-4.5 w-4.5 rounded-full bg-white transition-all ${
                    source.enabled ? "left-[22px]" : "left-0.5"
                  }`}
                  style={{ height: 18, width: 18 }}
                />
              </button>
            </div>

            <div className="flex flex-wrap gap-2 text-[10px] text-muted-foreground">
              <span>{source.fields.length} campos</span>
              <span>·</span>
              <span>lista {source.list.selector ? `«${source.list.selector}»` : "página única"}</span>
              <span>·</span>
              <span>{source.pagination.max_pages} página(s)</span>
              {source.respect_robots ? (
                <>
                  <span>·</span>
                  <span>robots.txt respeitado</span>
                </>
              ) : null}
              {source.tags.length ? (
                <>
                  <span>·</span>
                  <span className="inline-flex items-center gap-1">
                    <Tag size={10} /> {source.tags.join(", ")}
                  </span>
                </>
              ) : null}
            </div>

            {lastRun ? (
              <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={lastRun.status} />
                  <span className="text-muted-foreground">{formatDate(lastRun.finished_at ?? lastRun.started_at)}</span>
                  <span className="text-muted-foreground">·</span>
                  <span>{numberFormat.format(lastRun.items_count)} itens</span>
                  <span className="text-muted-foreground">·</span>
                  <span>{numberFormat.format(lastRun.indexed_count)} indexados</span>
                  <span className="text-muted-foreground">·</span>
                  <span>{lastRun.pages} pág.</span>
                  {lastRun.detail_count ? (
                    <>
                      <span className="text-muted-foreground">·</span>
                      <span>{numberFormat.format(lastRun.detail_count)} com texto integral</span>
                    </>
                  ) : null}
                  {lastRun.duplicates ? (
                    <>
                      <span className="text-muted-foreground">·</span>
                      <span title="Cartões repetidos na página (mesmo URL ou mesmo título)">
                        {numberFormat.format(lastRun.duplicates)} repetidos ignorados
                      </span>
                    </>
                  ) : null}
                  <span className="text-muted-foreground">·</span>
                  <span>{formatDuration(lastRun.duration_ms)}</span>
                </div>
                {lastRun.errors?.length ? (
                  <p className="mt-1 text-rose-200">{lastRun.errors[0]}</p>
                ) : null}
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground">Ainda sem execuções registadas.</p>
            )}

            <div className="mt-auto flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onRun(source)}
                disabled={busy === source.id || running}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-400 to-teal-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
              >
                {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                {running ? "A recolher…" : "Recolher agora"}
              </button>
              <button
                type="button"
                onClick={() => onEdit(source)}
                className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
              >
                <Pencil size={13} /> Editar
              </button>
              {source.template_id ? (
                <button
                  type="button"
                  onClick={() => onApplyTemplate(source)}
                  disabled={busy === source.id}
                  title="Reaplicar os seletores do template (mantém nome, agenda e interruptor)"
                  className="inline-flex items-center gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-xs text-amber-100 hover:bg-amber-400/20 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
                >
                  {busy === source.id ? <Loader2 size={13} className="animate-spin" /> : <Layers size={13} />} Template
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onDelete(source)}
                disabled={busy === source.id}
                className="inline-flex items-center gap-2 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-200 hover:bg-rose-400/20 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
              >
                <Trash2 size={13} /> Apagar
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

/* ----------------------------------------------------------- execuções */

function RunsSection({ sources }: { sources: ScraperSource[] }) {
  const [runs, setRuns] = useState<ScraperRun[]>([]);
  const [sourceFilter, setSourceFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<ScraperRun | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await listScraperRuns(sourceFilter || undefined, 80);
      setRuns(result.items.filter(Boolean) as ScraperRun[]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar as execuções.");
    } finally {
      setLoading(false);
    }
  }, [sourceFilter]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  useEffect(() => {
    const active = runs.some((run) => run.status === "running");
    if (!active) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [runs, load]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,440px)]">
      <div className="glass-card rounded-2xl p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Play size={15} /> Execuções
          </h2>
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="runs-source">
              Filtrar por fonte
            </label>
            <select
              id="runs-source"
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
            >
              <option value="">Todas as fontes</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-xl border border-white/10 bg-white/5 p-2 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
              aria-label="Atualizar execuções"
            >
              <RefreshCw size={13} />
            </button>
          </div>
        </div>

        {loading ? (
          <p className="flex items-center gap-2 py-10 text-xs text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> A carregar…
          </p>
        ) : error ? (
          <p className="py-6 text-xs text-rose-200">{error}</p>
        ) : !runs.length ? (
          <p className="py-10 text-center text-xs text-muted-foreground">Sem execuções registadas.</p>
        ) : (
          <ul className="mt-3 divide-y divide-white/5">
            {runs.map((run) => (
              <li key={`${run.source_id}:${run.run_id}`}>
                <button
                  type="button"
                  onClick={() => setOpenRun(run)}
                  className={`flex w-full flex-wrap items-center gap-2 px-1 py-3 text-left text-xs transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 ${
                    openRun?.run_id === run.run_id ? "bg-white/5" : ""
                  }`}
                >
                  <StatusPill status={run.status} />
                  <span className="font-medium">{run.source_name ?? run.source_id}</span>
                  <span className="text-muted-foreground">{formatDate(run.started_at)}</span>
                  <span className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <Rss size={11} /> {numberFormat.format(run.items_count)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Database size={11} /> {numberFormat.format(run.indexed_count)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Layers size={11} /> {run.pages}
                    </span>
                    <span>{formatDuration(run.duration_ms)}</span>
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">{run.trigger}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <RunItemsPanel run={openRun} onClose={() => setOpenRun(null)} />
    </div>
  );
}

function RunItemsPanel({ run, onClose }: { run: ScraperRun | null; onClose: () => void }) {
  const [items, setItems] = useState<ScraperItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [view, setView] = useState<ItemsView>("cards");
  const PAGE = 50;

  useEffect(() => {
    if (!run) return;
    let cancelled = false;
    setLoading(true);
    getScraperRunItems(run.run_id, run.source_id, PAGE, 0)
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [run]);

  const loadMore = async () => {
    if (!run) return;
    setLoadingMore(true);
    try {
      const result = await getScraperRunItems(run.run_id, run.source_id, PAGE, items.length);
      setItems((previous) => [...previous, ...result.items]);
      setTotal(result.total);
    } finally {
      setLoadingMore(false);
    }
  };

  if (!run) {
    return (
      <aside className="glass-card rounded-2xl p-4">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <FileJson size={15} /> Itens da execução
        </h3>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Escolha uma execução para ver os itens gravados (JSONL).
        </p>
      </aside>
    );
  }

  return (
    <aside className="glass-card rounded-2xl p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <FileJson size={15} /> {run.source_name ?? run.source_id}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {run.run_id} · {numberFormat.format(items.length)} de {numberFormat.format(total)} itens
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar painel de itens"
          className="rounded-lg border border-white/10 bg-white/5 p-1.5 hover:bg-white/10"
        >
          <X size={13} />
        </button>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <ItemsViewToggle value={view} onChange={setView} />
        {loading ? (
          <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
            <Loader2 size={11} className="animate-spin" /> a ler…
          </span>
        ) : null}
      </div>

      {run.errors?.length ? (
        <div className="mt-3 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[11px] text-rose-100">
          {run.errors.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      {loading ? (
        <p className="flex items-center gap-2 py-8 text-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> A ler os itens…
        </p>
      ) : !items.length ? (
        <p className="py-8 text-center text-xs text-muted-foreground">Sem itens nesta execução.</p>
      ) : (
        <div className="mt-3 max-h-[62vh] overflow-auto pr-1">
          <ItemsCollection items={items.map((item) => toDisplayItem(item))} view={view} />
          {items.length < total ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={loadingMore}
              className="mt-2 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] hover:bg-white/10 disabled:opacity-50"
            >
              {loadingMore ? "A carregar…" : `Carregar mais (${numberFormat.format(total - items.length)})`}
            </button>
          ) : null}
        </div>
      )}
    </aside>
  );
}

/* ------------------------------------------------ itens recolhidos (vistas)
   Os itens vêm do JSONL/índice com o título, a ligação, os campos extraídos
   (`data`) e a imagem; a apresentação (cartões, lista ou imagens) é a partilhada
   de `components/ItemsView`. */

/** Converte um item recolhido no formato comum das vistas. */
function toDisplayItem(item: ScraperItem, options: { source?: boolean } = {}): DisplayItem {
  const data = item.data ?? {};
  const imageEntry = Object.entries(data).find(
    ([key, value]) => /^(imagem|image|img|thumbnail|foto|cover)$/i.test(key) && typeof value === "string",
  );
  return {
    id: item.item_id ?? item.url ?? item.title ?? Math.random().toString(36),
    title: item.title || item.item_id || "(sem título)",
    subtitle: options.source ? item.source_name ?? item.source_id : undefined,
    summary: item.summary || item.text,
    url: item.url,
    image: imageEntry ? String(imageEntry[1]) : null,
    date: item.scraped_at,
    tags: item.tags,
    values: data,
  };
}

/* ------------------------------------------------------------ pesquisa */

function SearchSection({ sources }: { sources: ScraperSource[] }) {
  const [query, setQuery] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sort, setSort] = useState<"recent" | "oldest" | "relevance">("recent");
  const [view, setView] = useState<ItemsView>("cards");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [result, setResult] = useState<{ total: number; items: ScraperItem[]; facets: { sources: { key: string; count: number }[]; tags: { key: string; count: number }[] } } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await searchScraperItems({ q: query || undefined, sourceId: sourceId || undefined, tags: activeTags, sort, size: 30 });
      if (payload.error) {
        setError(payload.error);
        setResult(null);
      } else {
        setError(null);
        setResult({ total: payload.total, items: payload.items, facets: payload.facets });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha na pesquisa.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [query, sourceId, activeTags, sort]);

  useEffect(() => {
    void search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId, sort, activeTags]);

  const toggleTag = (tag: string) => {
    setActiveTags((previous) => (previous.includes(tag) ? previous.filter((t) => t !== tag) : [...previous, tag]));
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="space-y-3">
        <form
          className="glass-card flex flex-wrap items-center gap-2 rounded-2xl p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void search();
          }}
        >
          <label className="sr-only" htmlFor="scraper-search">
            Pesquisar itens recolhidos
          </label>
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              id="scraper-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Pesquisar em títulos, textos e todos os campos recolhidos…"
              className="w-full rounded-xl border border-white/10 bg-white/5 py-2 pl-9 pr-3 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
            />
          </div>
          <label className="sr-only" htmlFor="scraper-search-source">
            Fonte
          </label>
          <select
            id="scraper-search-source"
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            <option value="">Todas as fontes</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="scraper-search-sort">
            Ordenação
          </label>
          <select
            id="scraper-search-sort"
            value={sort}
            onChange={(event) => setSort(event.target.value as "recent" | "oldest" | "relevance")}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            <option value="recent">Mais recentes</option>
            <option value="oldest">Mais antigos</option>
            <option value="relevance">Relevância</option>
          </select>
          <button
            type="submit"
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-amber-400 to-orange-600 px-3 py-2 text-xs font-medium text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300"
          >
            <Search size={13} /> Pesquisar
          </button>
        </form>

        {error ? <p className="rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">{error}</p> : null}

        <div className="glass-card rounded-2xl p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Database size={15} /> Itens recolhidos
            </h2>
            <div className="flex items-center gap-2">
              <ItemsViewToggle value={view} onChange={setView} />
              <span className="text-[11px] text-muted-foreground">
                {loading ? "a pesquisar…" : `${numberFormat.format(result?.total ?? 0)} resultados`}
              </span>
            </div>
          </div>
          {!loading && result && !result.items.length ? (
            <p className="py-10 text-center text-xs text-muted-foreground">
              Sem resultados. {sources.length ? "Execute uma fonte para recolher dados." : "Crie uma fonte primeiro."}
            </p>
          ) : (
            <ItemsCollection
              items={(result?.items ?? []).map((item) => toDisplayItem(item, { source: true }))}
              view={view}
              onTagClick={toggleTag}
              className="mt-3"
            />
          )}
        </div>
      </div>

      <aside className="space-y-3">
        {activeTags.length ? (
          <div className="glass-card rounded-2xl p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Filtros ativos</h3>
              <button type="button" onClick={() => setActiveTags([])} className="text-[10px] text-muted-foreground hover:text-foreground">
                limpar
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {activeTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => toggleTag(tag)}
                  className="inline-flex items-center gap-1 rounded-full border border-orange-400/30 bg-orange-400/10 px-2 py-0.5 text-[10px] text-orange-100"
                >
                  #{tag} <X size={9} />
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="glass-card rounded-2xl p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes</h3>
          <ul className="mt-2 space-y-1">
            {(result?.facets.sources ?? []).map((facet) => (
              <li key={facet.key}>
                <button
                  type="button"
                  onClick={() => setSourceId(sourceId === facet.key ? "" : facet.key)}
                  className={`flex w-full items-center justify-between rounded-lg px-2 py-1 text-[11px] hover:bg-white/5 ${
                    sourceId === facet.key ? "bg-white/10" : ""
                  }`}
                >
                  <span className="truncate">{sources.find((s) => s.id === facet.key)?.name ?? facet.key}</span>
                  <span className="text-muted-foreground">{numberFormat.format(facet.count)}</span>
                </button>
              </li>
            ))}
            {!result?.facets.sources?.length ? <li className="px-2 py-1 text-[11px] text-muted-foreground">—</li> : null}
          </ul>
        </div>

        <div className="glass-card rounded-2xl p-4">
          <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <Tag size={12} /> Etiquetas
          </h3>
          <div className="mt-2 flex flex-wrap gap-1">
            {(result?.facets.tags ?? []).slice(0, 30).map((facet) => (
              <button
                key={facet.key}
                type="button"
                onClick={() => toggleTag(facet.key)}
                className={`rounded-full border px-2 py-0.5 text-[10px] hover:bg-white/10 ${
                  activeTags.includes(facet.key)
                    ? "border-orange-400/40 bg-orange-400/10 text-orange-100"
                    : "border-white/10 bg-white/5 text-muted-foreground"
                }`}
              >
                #{facet.key} · {facet.count}
              </button>
            ))}
            {!result?.facets.tags?.length ? <span className="text-[11px] text-muted-foreground">—</span> : null}
          </div>
        </div>
      </aside>
    </div>
  );
}

/* --------------------------------------------------------------- agenda */

function ScheduleSection({
  status,
  sources,
  onRefresh,
  onError,
  onNotice,
}: {
  status: ScraperStatus | null;
  sources: ScraperSource[];
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const [jobs, setJobs] = useState<{ id: string; source_id: string; name: string; next_run_time: string | null }[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await getScraperJobs();
      setJobs(payload.jobs ?? []);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao carregar os jobs.");
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = async () => {
    setLoading(true);
    try {
      const payload = await reloadScraperJobs();
      setJobs(payload.jobs ?? []);
      onNotice("Definições reaplicadas ao agendador.");
      await onRefresh();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao reaplicar as definições.");
    } finally {
      setLoading(false);
    }
  };

  const scheduled = sources.filter((source) => source.enabled && source.schedule.cron);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="glass-card rounded-2xl p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <CalendarClock size={15} /> Agendamento (cron)
          </h2>
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Reaplicar definições
          </button>
        </div>

        {status && !status.scheduler.available ? (
          <p className="mt-3 rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[11px] text-amber-100">
            O agendador está inativo{status.scheduler.error ? `: ${status.scheduler.error}` : " (APScheduler não instalado ou a API não reiniciou)."}
          </p>
        ) : null}

        {!jobs.length ? (
          <p className="py-10 text-center text-xs text-muted-foreground">
            Nenhum job agendado. Ligue a fonte e defina uma expressão cron para a recolha automática.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-white/5">
            {jobs.map((job) => (
              <li key={job.id} className="flex flex-wrap items-center gap-2 px-1 py-3 text-xs">
                <Clock size={13} className="text-emerald-300" />
                <span className="font-medium">{sources.find((s) => s.id === job.source_id)?.name ?? job.name}</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
                  {sources.find((s) => s.id === job.source_id)?.schedule.cron ?? "—"}
                </span>
                <span className="ml-auto text-[11px] text-muted-foreground">próxima: {formatDate(job.next_run_time)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <aside className="space-y-3">
        <div className="glass-card rounded-2xl p-4">
          <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <Settings2 size={12} /> Fontes com agendamento
          </h3>
          <ul className="mt-2 space-y-2">
            {scheduled.map((source) => (
              <li key={source.id} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                <p className="truncate text-[11px] font-medium">{source.name}</p>
                <p className="text-[10px] text-muted-foreground">
                  {source.schedule.cron} · {source.schedule.timezone}
                </p>
              </li>
            ))}
            {!scheduled.length ? <li className="text-[11px] text-muted-foreground">Nenhuma fonte ligada com cron.</li> : null}
          </ul>
        </div>
        <div className="glass-card rounded-2xl p-4 text-[11px] text-muted-foreground">
          <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
            <Wand2 size={12} /> Expressões cron
          </h3>
          <p className="mt-2">
            Formato de 5 campos: <code>minuto hora dia mês dia-semana</code>.
          </p>
          <ul className="mt-2 space-y-1">
            <li>
              <code>0 7 * * *</code> — todos os dias às 07:00
            </li>
            <li>
              <code>*/15 * * * *</code> — a cada 15 minutos
            </li>
            <li>
              <code>0 7 * * 1-5</code> — dias úteis às 07:00
            </li>
          </ul>
        </div>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------- editor de fonte */

function SourceEditor({
  value,
  meta,
  canWrite,
  onClose,
  onSaved,
  onError,
}: {
  value: Partial<ScraperSource>;
  meta: ScraperMeta | null;
  canWrite: boolean;
  onClose: () => void;
  onSaved: (message: string) => void | Promise<void>;
  onError: (message: string) => void;
}) {
  const [draft, setDraft] = useState<Partial<ScraperSource>>(() => ({
    ...value,
    list: { selector: "", type: "css", ...(value.list ?? {}) },
    pagination: { selector: "", type: "css", attr: "href", max_pages: 1, ...(value.pagination ?? {}) },
    schedule: { cron: "", timezone: "Europe/Lisbon", ...(value.schedule ?? {}) },
    fields: value.fields?.length ? value.fields : [{ name: "", selector: "", type: "css", cast: "text" } as ScraperField],
    tags: value.tags ?? [],
    id_fields: value.id_fields ?? [],
    options: value.options ?? {},
  }));
  const [preview, setPreview] = useState<ScraperPreview | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tagsText, setTagsText] = useState((value.tags ?? []).join(", "));
  const [suggestion, setSuggestion] = useState<ScraperSuggestion | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const patch = (changes: Partial<ScraperSource>) => setDraft((previous) => ({ ...previous, ...changes }));

  const updateField = (index: number, changes: Partial<ScraperField>) => {
    setDraft((previous) => {
      const fields = [...(previous.fields ?? [])];
      fields[index] = { ...fields[index], ...changes };
      return { ...previous, fields };
    });
  };

  const addField = () => {
    setDraft((previous) => ({
      ...previous,
      fields: [...(previous.fields ?? []), { name: "", label: "", selector: "", type: "css", cast: "text" } as ScraperField],
    }));
  };

  const removeField = (index: number) => {
    setDraft((previous) => ({ ...previous, fields: (previous.fields ?? []).filter((_, i) => i !== index) }));
  };

  const payload = (): Partial<ScraperSource> => ({
    ...draft,
    name: (draft.name ?? "").trim(),
    url: (draft.url ?? "").trim(),
    tags: tagsText
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean),
    fields: (draft.fields ?? [])
      .filter((field) => field.name && field.selector)
      .map((field) => {
        // Se o seletor foi reescrito à mão, os alternativos do template deixam de
        // fazer sentido (o primeiro já não é o que veio de origem).
        const alternativos = field.selectors ?? [];
        const mantemAlternativos = alternativos.length > 1 && alternativos[0] === field.selector;
        return {
          ...field,
          label: field.label || field.name,
          type: field.type || "css",
          cast: field.cast || "text",
          selectors: mantemAlternativos ? alternativos : undefined,
        };
      }),
    id_fields: draft.id_fields ?? [],
  });

  /** Pede à IA (com a análise determinística por trás) os seletores desta página. */
  const suggest = async () => {
    const url = (draft.url ?? "").trim();
    if (!url) {
      onError("Indique o URL antes de pedir a sugestão.");
      return;
    }
    setSuggesting(true);
    setSuggestion(null);
    try {
      const result = await suggestScraperSource({
        url,
        hint: draft.description || draft.name || "",
        fetcher: draft.fetcher ?? "http",
        options: draft.options ?? {},
      });
      setSuggestion(result);
      if (result.definition) {
        const proposed = result.definition;
        setDraft((previous) => ({
          ...previous,
          name: previous.name || result.title || previous.url || "",
          list: proposed.list ?? previous.list,
          fields: (proposed.fields ?? []).map((field) => ({
            name: field.name,
            label: field.label ?? field.name,
            selector: field.selector,
            type: field.type ?? "css",
            attr: field.attr ?? null,
            all: Boolean(field.all),
            cast: field.cast ?? "text",
            max_length: field.max_length ?? 1000,
          })),
          pagination: proposed.pagination ?? previous.pagination,
          id_fields: proposed.id_fields ?? previous.id_fields,
          title_field: proposed.title_field ?? previous.title_field,
        }));
      }
      if (result.ai_error) onError(`IA indisponível: ${result.ai_error}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao obter a sugestão.");
    } finally {
      setSuggesting(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setPreview(null);
    try {
      const result = await previewScraperSource(payload(), 5, 1);
      setPreview(result);
      if (!result.ok && result.error) onError(`Teste da fonte: ${result.error}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao testar a fonte.");
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    const body = payload();
    if (!body.url) {
      onError("Indique o URL do site a recolher.");
      return;
    }
    if (!body.fields?.length) {
      onError("Defina pelo menos um campo a extrair (nome + seletor).");
      return;
    }
    setSaving(true);
    try {
      if (draft.id) {
        await updateScraperSource(draft.id, body);
        await onSaved(`Fonte «${body.name || body.url}» atualizada.`);
      } else {
        await createScraperSource(body);
        await onSaved(`Fonte «${body.name || body.url}» criada.`);
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Falha ao guardar a fonte.");
    } finally {
      setSaving(false);
    }
  };

  const fieldNames = (draft.fields ?? []).map((field) => field.name).filter(Boolean);
  const fetcher = draft.fetcher ?? "http";

  return (
    <div className="fixed inset-0 z-[120] flex items-start justify-center overflow-auto bg-black/60 p-4 pb-32 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Definição da fonte de recolha">
      <div ref={dialogRef} className="glass-card mt-6 w-full max-w-4xl rounded-2xl p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-amber-300 to-orange-600 text-white">
              <Globe2 size={18} />
            </span>
            <div>
              <h2 className="text-base font-semibold">{draft.id ? "Editar fonte de recolha" : "Nova fonte de recolha"}</h2>
              <p className="text-xs text-muted-foreground">
                Definição declarativa: URL, tipo de pedido, seletores dos campos e periodicidade.
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar" className="rounded-lg border border-white/10 bg-white/5 p-1.5 hover:bg-white/10">
            <X size={14} />
          </button>
        </div>

        {!canWrite ? (
          <p className="mt-3 rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[11px] text-amber-100">
            É precisa uma sessão para guardar definições. Pode testar a fonte, mas não guardar.
          </p>
        ) : null}

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="Nome da fonte">
            <input value={draft.name ?? ""} onChange={(event) => patch({ name: event.target.value })} className={inputClass} placeholder="Ex.: Contratos do portal base" />
          </Field>
          <Field label="URL a recolher">
            <div className="flex items-center gap-2">
              <input value={draft.url ?? ""} onChange={(event) => patch({ url: event.target.value })} className={inputClass} placeholder="https://exemplo.pt/listagem" />
              <button
                type="button"
                onClick={() => void suggest()}
                disabled={suggesting || !(draft.url ?? "").trim()}
                title="Analisa a página e propõe os seletores (IA + heurística)"
                className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-gradient-to-r from-violet-400 to-indigo-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
              >
                {suggesting ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
                {suggesting ? "A analisar…" : "Obter com IA"}
              </button>
            </div>
          </Field>
          <Field label="Descrição">
            <input value={draft.description ?? ""} onChange={(event) => patch({ description: event.target.value })} className={inputClass} placeholder="Para que serve esta recolha" />
          </Field>
          <Field label="Tipo de pedido">
            <select
              value={fetcher}
              onChange={(event) => patch({ fetcher: event.target.value as ScraperSource["fetcher"] })}
              className={inputClass}
            >
              {(meta?.fetchers ?? [{ id: "http", label: "HTTP", options: {} }]).map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {/* resultado da sugestão (IA + análise da página) */}
        {suggestion ? (
          <div className="mt-4 rounded-2xl border border-violet-400/25 bg-violet-400/5 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {suggestion.definition ? (
                <CheckCircle2 size={14} className="text-emerald-300" />
              ) : (
                <AlertTriangle size={14} className="text-amber-300" />
              )}
              <span className="font-medium">Sugestão de recolha</span>
              <Pill
                className={
                  suggestion.origin === "ai"
                    ? "border-violet-400/30 bg-violet-400/10 text-violet-200"
                    : "border-amber-400/30 bg-amber-400/10 text-amber-200"
                }
              >
                <Sparkles size={10} />
                {suggestion.origin === "ai" ? "obtida por IA" : "obtida por análise da página"}
              </Pill>
              {suggestion.ai ? (
                <span className="text-[11px] text-muted-foreground">
                  {suggestion.ai.provider_label ?? suggestion.ai.provider} · {suggestion.ai.model}
                </span>
              ) : null}
              {suggestion.preview ? (
                <span className="text-[11px] text-muted-foreground">
                  {suggestion.preview.total} itens em {suggestion.preview.pages} página(s)
                </span>
              ) : null}
              <button type="button" onClick={() => setSuggestion(null)} className="ml-auto text-[10px] text-muted-foreground hover:text-foreground">
                limpar
              </button>
            </div>

            {suggestion.error ? <p className="mt-2 text-[11px] text-rose-200">{suggestion.error}</p> : null}
            {suggestion.ai_error ? (
              <p className="mt-2 text-[11px] text-amber-200">
                Sem IA: {suggestion.ai_error} (foi usada a análise determinística da página)
              </p>
            ) : null}
            {suggestion.ai?.notes ? (
              <p className="mt-2 text-[11px] text-muted-foreground">
                <strong className="font-medium text-foreground">Notas do modelo:</strong> {suggestion.ai.notes}
              </p>
            ) : null}

            {suggestion.analysis.length ? (
              <details className="mt-2">
                <summary className="cursor-pointer text-[11px] text-muted-foreground">
                  Candidatos analisados ({suggestion.analysis.length})
                </summary>
                <ul className="mt-2 space-y-1">
                  {suggestion.analysis.slice(0, 6).map((candidate) => (
                    <li key={candidate.selector} className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                      <code className="rounded bg-black/30 px-1.5 py-0.5 text-foreground">{candidate.selector}</code>
                      <span>{candidate.count} itens</span>
                      <span>texto {candidate.text_ratio}</span>
                      <span>título {candidate.title_ratio}</span>
                      <span className="truncate">{(candidate.samples?.[0] ?? "").slice(0, 60)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}

        {/* seletores da lista + paginação */}
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Lista e paginação</h3>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <Field label="Seletor de cada item da lista" hint="Vazio = a página inteira é um único item.">
              <input
                value={draft.list?.selector ?? ""}
                onChange={(event) => patch({ list: { ...(draft.list ?? { type: "css" }), selector: event.target.value } })}
                className={inputClass}
                placeholder=".quote"
              />
            </Field>
            <Field label="Tipo de seletor">
              <SelectorKindSelect value={draft.list?.type ?? "css"} onChange={(kind) => patch({ list: { ...(draft.list ?? {}), selector: draft.list?.selector ?? "", type: kind } })} kinds={meta?.selector_kinds} />
            </Field>
            <Field label="Seletor do link da página seguinte">
              <input
                value={draft.pagination?.selector ?? ""}
                onChange={(event) => patch({ pagination: { ...(draft.pagination ?? { attr: "href", max_pages: 1, type: "css" }), selector: event.target.value } })}
                className={inputClass}
                placeholder=".next a"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Atributo">
                <input
                  value={draft.pagination?.attr ?? "href"}
                  onChange={(event) => patch({ pagination: { ...(draft.pagination ?? { selector: "", type: "css", max_pages: 1 }), attr: event.target.value } })}
                  className={inputClass}
                />
              </Field>
              <Field label="Máx. páginas">
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={draft.pagination?.max_pages ?? 1}
                  onChange={(event) => patch({ pagination: { ...(draft.pagination ?? { selector: "", type: "css", attr: "href" }), max_pages: Number(event.target.value) || 1 } })}
                  className={inputClass}
                />
              </Field>
            </div>
          </div>
        </div>

        {/* texto integral (página de detalhe de cada item) */}
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Texto integral</h3>
            <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(draft.detail?.enabled)}
                onChange={(event) =>
                  patch({
                    detail: {
                      ...(draft.detail ?? { selector: "", max_items: 0, delay: 0.5, max_chars: 20000 }),
                      enabled: event.target.checked,
                      max_items: event.target.checked ? draft.detail?.max_items || 15 : 0,
                    },
                  })
                }
                className="h-3.5 w-3.5 rounded border-white/20 bg-white/5"
              />
              Abrir a página de cada item e guardar o corpo do artigo
            </label>
          </div>
          {draft.detail?.enabled ? (
            <div className="mt-2 grid gap-3 sm:grid-cols-[2fr_1fr_1fr]">
              <Field label="Seletor do corpo do artigo" hint="É escolhido o maior dos nós que casam com o seletor.">
                <input
                  value={draft.detail?.selector ?? ""}
                  onChange={(event) => patch({ detail: { ...(draft.detail as ScraperDetail), selector: event.target.value } })}
                  className={inputClass}
                  placeholder="div.article-body"
                />
              </Field>
              <Field label="Itens por execução" hint="Cada item é um pedido extra ao site.">
                <input
                  type="number"
                  min={0}
                  max={200}
                  value={draft.detail?.max_items ?? 0}
                  onChange={(event) => patch({ detail: { ...(draft.detail as ScraperDetail), max_items: Number(event.target.value) || 0 } })}
                  className={inputClass}
                />
              </Field>
              <Field label="Pausa (segundos)" hint="Intervalo entre páginas, para não sobrecarregar o site.">
                <input
                  type="number"
                  min={0}
                  max={10}
                  step={0.1}
                  value={draft.detail?.delay ?? 0.5}
                  onChange={(event) => patch({ detail: { ...(draft.detail as ScraperDetail), delay: Number(event.target.value) || 0 } })}
                  className={inputClass}
                />
              </Field>
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Desligado: os itens ficam com o título, o resumo e os restantes campos da lista (mais rápido e mais leve).
            </p>
          )}
        </div>

        {/* campos */}
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Campos a extrair</h3>
            <button type="button" onClick={addField} className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] hover:bg-white/10">
              <Plus size={12} /> Campo
            </button>
          </div>
          <div className="mt-2 space-y-2">
            {(draft.fields ?? []).map((field, index) => (
              <div key={index} className="rounded-xl border border-white/10 bg-black/20 p-2">
                <div className="grid gap-2 sm:grid-cols-[1fr_1fr_1.4fr_auto_auto_auto]">
                  <input value={field.name} onChange={(event) => updateField(index, { name: event.target.value })} className={inputClass} placeholder="nome" aria-label={`Nome do campo ${index + 1}`} />
                  <input value={field.label ?? ""} onChange={(event) => updateField(index, { label: event.target.value })} className={inputClass} placeholder="etiqueta" aria-label={`Etiqueta do campo ${index + 1}`} />
                  <input value={field.selector} onChange={(event) => updateField(index, { selector: event.target.value })} className={inputClass} placeholder=".preco::text" aria-label={`Seletor do campo ${index + 1}`} />
                  <SelectorKindSelect value={field.type} onChange={(kind) => updateField(index, { type: kind })} kinds={meta?.selector_kinds} compact />
                  <select
                    value={field.cast ?? "text"}
                    onChange={(event) => updateField(index, { cast: event.target.value as ScraperField["cast"] })}
                    className={inputClass}
                    aria-label={`Conversão do campo ${index + 1}`}
                  >
                    {(meta?.casts ?? ["text"]).map((cast) => (
                      <option key={cast} value={cast}>
                        {cast}
                      </option>
                    ))}
                  </select>
                  <div className="flex items-center gap-1">
                    <label className="inline-flex items-center gap-1 text-[10px] text-muted-foreground" title="Recolher todas as ocorrências (lista)">
                      <input type="checkbox" checked={Boolean(field.all)} onChange={(event) => updateField(index, { all: event.target.checked })} className="h-3.5 w-3.5 rounded border-white/20 bg-white/5" />
                      todos
                    </label>
                    <button type="button" onClick={() => removeField(index)} aria-label={`Remover campo ${index + 1}`} className="rounded-lg border border-rose-400/20 bg-rose-400/10 p-1.5 text-rose-200 hover:bg-rose-400/20">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                {field.selectors && field.selectors.length > 1 ? (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Alternativos (usados se o primeiro não devolver nada): {field.selectors.slice(1).join(" · ")}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        {/* identidade + agendamento */}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Identidade e metadados</h3>
            <div className="mt-2 space-y-3">
              <Field label="Campos que identificam um item" hint="Evita duplicados entre recolhas (por omissão: o URL).">
                <div className="flex flex-wrap gap-1">
                  {fieldNames.length ? (
                    fieldNames.map((name) => {
                      const selected = (draft.id_fields ?? []).includes(name);
                      return (
                        <button
                          key={name}
                          type="button"
                          onClick={() =>
                            patch({
                              id_fields: selected ? (draft.id_fields ?? []).filter((item) => item !== name) : [...(draft.id_fields ?? []), name],
                            })
                          }
                          className={`rounded-full border px-2 py-0.5 text-[10px] ${
                            selected ? "border-orange-400/40 bg-orange-400/10 text-orange-100" : "border-white/10 bg-white/5 text-muted-foreground"
                          }`}
                        >
                          {name}
                        </button>
                      );
                    })
                  ) : (
                    <span className="text-[11px] text-muted-foreground">Defina campos primeiro.</span>
                  )}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Campo do título">
                  <FieldSelect value={draft.title_field ?? ""} onChange={(next) => patch({ title_field: next })} options={fieldNames} />
                </Field>
                <Field label="Campo do resumo">
                  <FieldSelect value={draft.summary_field ?? ""} onChange={(next) => patch({ summary_field: next })} options={fieldNames} />
                </Field>
                <Field label="Campo do texto">
                  <FieldSelect value={draft.text_field ?? ""} onChange={(next) => patch({ text_field: next })} options={fieldNames} />
                </Field>
                <Field label="Campo das etiquetas">
                  <FieldSelect value={draft.tags_field ?? ""} onChange={(next) => patch({ tags_field: next })} options={fieldNames} />
                </Field>
              </div>
              <Field label="Etiquetas da fonte">
                <input value={tagsText} onChange={(event) => setTagsText(event.target.value)} className={inputClass} placeholder="contratos, portal-base" />
              </Field>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Agendamento (cron)</h3>
            <div className="mt-2 space-y-3">
              <Field label="Expressão cron" hint="minuto hora dia mês dia-semana">
                <input
                  value={draft.schedule?.cron ?? ""}
                  onChange={(event) => patch({ schedule: { ...(draft.schedule ?? { timezone: "Europe/Lisbon" }), cron: event.target.value } })}
                  className={inputClass}
                  placeholder="0 7 * * 1-5"
                />
              </Field>
              <div className="flex flex-wrap gap-1">
                {(meta?.cron_presets ?? []).map((preset) => (
                  <button
                    key={preset.cron}
                    type="button"
                    onClick={() => patch({ schedule: { ...(draft.schedule ?? { timezone: "Europe/Lisbon" }), cron: preset.cron } })}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
                    title={preset.cron}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Fuso horário">
                  <input
                    value={draft.schedule?.timezone ?? "Europe/Lisbon"}
                    onChange={(event) => patch({ schedule: { ...(draft.schedule ?? { cron: "" }), timezone: event.target.value } })}
                    className={inputClass}
                  />
                </Field>
                <Field label="Estado">
                  <label className="mt-1 inline-flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={Boolean(draft.enabled)} onChange={(event) => patch({ enabled: event.target.checked })} className="h-4 w-4 rounded border-white/20 bg-white/5" />
                    Agendar e permitir execução
                  </label>
                </Field>
              </div>
              <label className="inline-flex items-center gap-2 text-xs">
                <input type="checkbox" checked={draft.respect_robots ?? true} onChange={(event) => patch({ respect_robots: event.target.checked })} className="h-4 w-4 rounded border-white/20 bg-white/5" />
                Respeitar o robots.txt do site
              </label>
            </div>
          </div>
        </div>

        {/* opções do fetcher */}
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Opções do pedido ({FETCHER_LABEL[fetcher] ?? fetcher})</h3>
          <div className="mt-2 grid gap-2 sm:grid-cols-4">
            {fetcher === "http" ? (
              <Field label="Impersonar">
                <input
                  value={String(draft.options?.impersonate ?? "")}
                  onChange={(event) => patch({ options: { ...(draft.options ?? {}), impersonate: event.target.value } })}
                  className={inputClass}
                  placeholder="chrome"
                />
              </Field>
            ) : (
              <>
                <Field label="Sem janela (headless)">
                  <label className="mt-1 inline-flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={draft.options?.headless !== false}
                      onChange={(event) => patch({ options: { ...(draft.options ?? {}), headless: event.target.checked } })}
                      className="h-4 w-4 rounded border-white/20 bg-white/5"
                    />
                    headless
                  </label>
                </Field>
                <Field label="Esperar rede">
                  <label className="mt-1 inline-flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={draft.options?.network_idle !== false}
                      onChange={(event) => patch({ options: { ...(draft.options ?? {}), network_idle: event.target.checked } })}
                      className="h-4 w-4 rounded border-white/20 bg-white/5"
                    />
                    network_idle
                  </label>
                </Field>
                {fetcher === "stealth" ? (
                  <Field label="Resolver Cloudflare">
                    <label className="mt-1 inline-flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={Boolean(draft.options?.solve_cloudflare)}
                        onChange={(event) => patch({ options: { ...(draft.options ?? {}), solve_cloudflare: event.target.checked } })}
                        className="h-4 w-4 rounded border-white/20 bg-white/5"
                      />
                      solve_cloudflare
                    </label>
                  </Field>
                ) : null}
              </>
            )}
            <Field label="Timeout (s)">
              <input
                type="number"
                min={5}
                max={300}
                value={Number(draft.options?.timeout ?? 30)}
                onChange={(event) => patch({ options: { ...(draft.options ?? {}), timeout: Number(event.target.value) || 30 } })}
                className={inputClass}
              />
            </Field>
          </div>
        </div>

        {preview ? (
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {preview.ok ? <CheckCircle2 size={14} className="text-emerald-300" /> : <AlertTriangle size={14} className="text-amber-300" />}
              <span className="font-medium">Teste da fonte</span>
              <span className="text-muted-foreground">
                {preview.total} itens em {preview.pages} página(s)
              </span>
              <button type="button" onClick={() => setPreview(null)} className="ml-auto text-[10px] text-muted-foreground hover:text-foreground">
                limpar
              </button>
            </div>
            {preview.error ? <p className="mt-2 text-[11px] text-rose-200">{preview.error}</p> : null}
            {preview.items.length ? (
              <div className="mt-2 max-h-80 overflow-auto pr-1">
                <ItemsCollection items={preview.items.map((item) => toDisplayItem(item))} view="cards" />
              </div>
            ) : preview.ok ? (
              <p className="mt-2 text-[11px] text-amber-200">Nenhum item encontrado — confirme o seletor da lista e dos campos.</p>
            ) : null}
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-white/10 pt-4">
          <button
            type="button"
            onClick={() => void test()}
            disabled={testing}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            {testing ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />} Testar extração
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || !canWrite}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-amber-400 to-orange-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300"
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Guardar fonte
          </button>
        </div>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted-foreground" title={hint}>
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function SelectorKindSelect({
  value,
  onChange,
  kinds,
  compact,
}: {
  value: ScraperSelectorKind;
  onChange: (kind: ScraperSelectorKind) => void;
  kinds?: ScraperSelectorKind[];
  compact?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as ScraperSelectorKind)}
      className={inputClass}
      aria-label="Tipo de seletor"
      title={compact ? "Tipo de seletor" : undefined}
    >
      {(kinds ?? ["css", "xpath", "text", "regex"]).map((kind) => (
        <option key={kind} value={kind}>
          {kind}
        </option>
      ))}
    </select>
  );
}

function FieldSelect({ value, onChange, options }: { value: string; onChange: (next: string) => void; options: string[] }) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} className={inputClass}>
      <option value="">(automático)</option>
      {options.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}
