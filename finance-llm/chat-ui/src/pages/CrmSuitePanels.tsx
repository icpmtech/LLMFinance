/**
 * Vistas genéricas da arquitetura de CRM.
 *
 * Um só componente (`CrmModulePanel`) serve os 24 módulos: a lista, os filtros, a
 * ficha e o formulário são gerados a partir da descrição do módulo que o servidor
 * devolve em `GET /crm/suite`. Não há código por módulo — acrescentar um campo no
 * registo do servidor faz aparecer o campo na lista e no formulário.
 *
 * Acrescenta, sobre o genérico:
 * - `CrmRbacPanel` — a matriz de acesso (perfis × módulos), na secção «Perfis»;
 * - `CrmAiComposer` — o assistente de CRM, na secção «Interações de IA»;
 * - o botão «Gerar perceções», na secção «Perceções de IA».
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDownWideNarrow,
  ArrowUpWideNarrow,
  BarChart3,
  Check,
  Download,
  Filter,
  LayoutGrid,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Table2,
  Trash2,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import {
  askCrmAi,
  createCrmModuleRecord,
  deleteCrmModuleRecord,
  formatFieldValue,
  generateCrmInsights,
  getCrmModuleReferences,
  getCrmModuleStats,
  getCrmRbac,
  listCrmModule,
  loadCrmSuite,
  updateCrmModuleRecord,
  type CrmFieldMeta,
  type CrmModuleMeta,
  type CrmModuleStats,
  type CrmRbacMeta,
  type CrmSuiteRecord,
} from "../crmSuiteApi";

/* ------------------------------------------------------------------ primitivas */

function Field({ label, hint, children, wide = false }: { label: string; hint?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={["flex flex-col gap-1", wide ? "sm:col-span-2" : ""].join(" ")}>
      <span className="text-[11.5px] font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[10.5px] leading-snug text-muted-foreground/80">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/60 focus:border-teal-300/40 focus:bg-white/[0.07]";

function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-black/60 p-4 pb-32 backdrop-blur-sm">
      <div
        className={[
          "mt-6 flex max-h-[80vh] w-full flex-col overflow-hidden rounded-2xl border border-white/12 bg-[#08181f] shadow-2xl",
          wide ? "max-w-4xl" : "max-w-2xl",
        ].join(" ")}
      >
        <header className="flex items-start gap-3 border-b border-white/8 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[14px] font-semibold text-foreground">{title}</h2>
            {subtitle && <p className="truncate text-[11.5px] text-muted-foreground">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground">
            <X size={15} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-white/8 px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

function Notice({ text, tone = "info", onClose }: { text: string; tone?: "info" | "error"; onClose?: () => void }) {
  return (
    <div
      className={[
        "flex items-center gap-2 rounded-lg border px-3 py-2 text-[12px]",
        tone === "error"
          ? "border-rose-400/25 bg-rose-500/10 text-rose-200"
          : "border-teal-300/25 bg-teal-400/10 text-teal-100",
      ].join(" ")}
    >
      {tone === "error" ? <AlertTriangle size={13} /> : <Check size={13} />}
      <span className="min-w-0 flex-1">{text}</span>
      {onClose && (
        <button type="button" onClick={onClose} className="rounded p-0.5 text-muted-foreground hover:text-foreground">
          <X size={12} />
        </button>
      )}
    </div>
  );
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}

/* ------------------------------------------------------------------ utilitários */

/** Valor inicial de um campo no formulário (a partir do registo). */
function initialValue(field: CrmFieldMeta, record: Record<string, unknown> | null) {
  const raw = record?.[field.key];
  if (raw === undefined || raw === null) return field.type === "bool" ? false : "";
  if (field.type === "bool") return Boolean(raw);
  if (field.type === "multiselect") return Array.isArray(raw) ? raw.map(String) : String(raw).split(",").filter(Boolean);
  if (field.type === "json") return typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
  if (field.type === "datetime") return String(raw).slice(0, 16);
  if (field.type === "date") return String(raw).slice(0, 10);
  return raw as string | number;
}

/** Converte o valor do formulário para o que a API espera. */
function payloadValue(field: CrmFieldMeta, value: unknown) {
  if (field.type === "json") {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (field.type === "multiselect") {
    return Array.isArray(value) ? value : String(value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
  }
  return value === "" ? null : value;
}

/* -------------------------------------------------------------- campo (formulário) */

function FieldInput({
  field,
  value,
  onChange,
  references,
}: {
  field: CrmFieldMeta;
  value: unknown;
  onChange: (next: unknown) => void;
  references: Record<string, Record<string, string>>;
}) {
  if (field.type === "bool") {
    return (
      <label className="flex items-center gap-2 py-1 text-[12.5px] text-foreground">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-3.5 w-3.5 rounded border-white/20 bg-white/10 accent-teal-400"
        />
        {field.label}
      </label>
    );
  }

  if (field.type === "select" || field.type === "reference") {
    const options =
      field.type === "reference"
        ? Object.entries(references[field.key] ?? {}).map(([id, label]) => ({ value: id, label }))
        : field.options;
    return (
      <select className={inputClass} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        <option value="">—</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === "multiselect") {
    const selected = Array.isArray(value) ? value.map(String) : [];
    if (field.options.length) {
      return (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-white/10 bg-white/[0.03] p-2">
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {field.options.map((option) => {
              const on = selected.includes(option.value);
              return (
                <label key={option.value} className="flex items-center gap-1.5 text-[11.5px] text-foreground">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange(on ? selected.filter((item) => item !== option.value) : [...selected, option.value])
                    }
                    className="h-3 w-3 rounded border-white/20 bg-white/10 accent-teal-400"
                  />
                  <span className="truncate">{option.label}</span>
                </label>
              );
            })}
          </div>
        </div>
      );
    }
    return <input className={inputClass} value={selected.join(", ")} onChange={(event) => onChange(event.target.value)} placeholder="valores separados por vírgulas" />;
  }

  if (field.type === "textarea" || field.type === "json") {
    return (
      <textarea
        className={`${inputClass} min-h-[80px] font-mono text-[11.5px]`}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        placeholder={field.type === "json" ? '[{"descricao": "…", "quantidade": 1, "preco": 100}]' : undefined}
      />
    );
  }

  if (field.type === "number" || field.type === "int" || field.type === "percent") {
    return <input className={inputClass} type="number" step={field.type === "int" ? 1 : "any"} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />;
  }

  if (field.type === "date") {
    return <input className={inputClass} type="date" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === "datetime") {
    return <input className={inputClass} type="datetime-local" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />;
  }

  return (
    <input
      className={inputClass}
      type={field.type === "email" ? "email" : field.type === "url" ? "url" : "text"}
      value={String(value ?? "")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/* --------------------------------------------------------------------- painel */

/**
 * Módulo do CRM: a página só indica qual; o painel resolve a descrição do módulo
 * e as permissões do perfil, com uma segunda tentativa (a primeira pode cruzar-se
 * com o arranque da sessão).
 */
export function CrmModulePanel({ slug, label }: { slug: string; label?: string }) {
  const [state, setState] = useState<{ module: CrmModuleMeta | null; error: string | null; loading: boolean }>({
    module: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let alive = true;
    setState({ module: null, error: null, loading: true });
    loadCrmSuite()
      .catch(() => loadCrmSuite(true))
      .then((meta) => {
        if (!alive) return;
        setState({ module: meta.modules.find((item) => item.slug === slug) ?? null, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setState({
          module: null,
          error: err instanceof Error ? err.message : "Não foi possível obter a arquitetura de CRM",
          loading: false,
        });
      });
    return () => {
      alive = false;
    };
  }, [slug]);

  if (state.loading) {
    return (
      <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar {label ?? slug}…
      </p>
    );
  }
  if (state.error) return <Notice text={state.error} tone="error" />;
  if (!state.module) {
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <ShieldCheck size={20} className="text-muted-foreground/70" />
        <p className="text-[13px] text-foreground">Sem acesso a este módulo</p>
        <p className="max-w-md text-[11.5px] text-muted-foreground">
          O seu perfil não inclui {label ?? slug}. Peça ao administrador do CRM para o incluir.
        </p>
      </div>
    );
  }
  return <CrmModuleBody module={state.module} />;
}

function CrmModuleBody({ module }: { module: CrmModuleMeta }) {
  const [items, setItems] = useState<CrmSuiteRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<CrmModuleStats | null>(null);
  const [references, setReferences] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sortBy, setSortBy] = useState<string>("");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [showFilters, setShowFilters] = useState(false);
  const [showStats, setShowStats] = useState(false);

  const [detail, setDetail] = useState<CrmSuiteRecord | null>(null);
  const [editor, setEditor] = useState<{ record: CrmSuiteRecord | null; draft: Record<string, unknown> } | null>(null);
  const [saving, setSaving] = useState(false);

  const filterFields = useMemo(() => module.fields.filter((field) => field.filter && !field.system), [module]);
  const columnFields = useMemo(() => {
    const columns = module.fields.filter((field) => field.column && !field.system);
    return (columns.length ? columns : module.fields.filter((field) => !field.system)).slice(0, 8);
  }, [module]);
  const writableFields = useMemo(() => module.fields.filter((field) => !field.system && !field.computed), [module]);

  /* Procura livre com atraso (evita um pedido por tecla). */
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 320);
    return () => window.clearTimeout(timer);
  }, [query]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const listed = await listCrmModule(module.slug, {
        q: debounced || undefined,
        size: 200,
        sort_by: sortBy || undefined,
        sort_order: sortBy ? sortOrder : undefined,
        ...filters,
      });
      setItems(listed.items ?? []);
      setTotal(listed.total ?? 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar o módulo");
    } finally {
      setLoading(false);
    }
  }, [module.slug, debounced, filters, sortBy, sortOrder]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    setQuery("");
    setFilters({});
    setSortBy("");
    setSortOrder("desc");
    setTotal(0);
    setItems([]);
    setDetail(null);
    setEditor(null);
    setStats(null);
    setReferences({});
  }, [module.slug]);

  useEffect(() => {
    let alive = true;
    void getCrmModuleStats(module.slug)
      .then((result) => alive && setStats(result))
      .catch(() => undefined);
    void getCrmModuleReferences(module.slug)
      .then((result) => alive && setReferences(result.references ?? {}))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [module.slug]);

  const openDetail = useCallback(async (record: CrmSuiteRecord) => setDetail(record), []);

  const openEditor = (record: CrmSuiteRecord | null) => {
    const draft: Record<string, unknown> = {};
    for (const field of writableFields) draft[field.key] = initialValue(field, record ?? null);
    setEditor({ record, draft });
    setDetail(null);
  };

  const submit = async () => {
    if (!editor) return;
    const body: Record<string, unknown> = {};
    for (const field of writableFields) {
      body[field.key] = payloadValue(field, editor.draft[field.key]);
    }
    setSaving(true);
    try {
      if (editor.record) {
        await updateCrmModuleRecord(module.slug, String(editor.record.id), body);
      } else {
        await createCrmModuleRecord(module.slug, body);
      }
      setNotice(`${module.singular} ${editor.record ? "alterado" : "criado"} com sucesso.`);
      setEditor(null);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (record: CrmSuiteRecord) => {
    if (!window.confirm(`Eliminar ${module.singular.toLowerCase()} «${record.label}»?`)) return;
    try {
      const result = await deleteCrmModuleRecord(module.slug, String(record.id));
      setNotice(
        result.cascaded
          ? `${module.singular} eliminado (e ${result.cascaded} registo(s) ligados).`
          : `${module.singular} eliminado.`,
      );
      setDetail(null);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível eliminar");
    }
  };

  const exportCsv = () => {
    const columns = module.fields.filter((field) => !field.system);
    const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const lines = [columns.map((field) => escape(field.label)).join(";")];
    for (const item of items) {
      lines.push(columns.map((field) => escape(formatFieldValue(field, item[field.key]))).join(";"));
    }
    const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `crm-${module.slug}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const grouped = (stats?.groups ?? []).filter((group) => group.buckets.length);
  const metrics = (stats?.metrics ?? []).filter((metric) => metric.count > 0);

  return (
    <div className="flex flex-col gap-3">
      {/* ---------------------------------------------------------- barra */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[190px] flex-1">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            className={`${inputClass} pl-7`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`Pesquisar em ${module.label.toLowerCase()}…`}
          />
        </div>

        {filterFields.length > 0 && (
          <Button size="sm" variant={showFilters ? "secondary" : "outline"} icon={<Filter size={13} />} onClick={() => setShowFilters((value) => !value)}>
            Filtros
            {Object.values(filters).filter(Boolean).length > 0 && (
              <span className="rounded-full bg-teal-400/25 px-1.5 text-[10px] text-teal-100">
                {Object.values(filters).filter(Boolean).length}
              </span>
            )}
          </Button>
        )}

        <Button
          size="sm"
          variant={showStats ? "secondary" : "outline"}
          icon={<BarChart3 size={13} />}
          onClick={() => setShowStats((value) => !value)}
        >
          Indicadores
        </Button>

        <Button
          size="sm"
          variant="outline"
          icon={sortOrder === "asc" ? <ArrowUpWideNarrow size={13} /> : <ArrowDownWideNarrow size={13} />}
          onClick={() => setSortOrder((value) => (value === "asc" ? "desc" : "asc"))}
          disabled={!sortBy}
          title="Inverter a ordenação"
        >
          {sortOrder === "asc" ? "Crescente" : "Decrescente"}
        </Button>

        <Button size="sm" variant="outline" icon={<RefreshCw size={13} />} onClick={() => void reload()} title="Recarregar">
          {total > 0 ? `${total}` : ""}
        </Button>

        {module.permissions.export && (
          <Button size="sm" variant="outline" icon={<Download size={13} />} onClick={exportCsv} disabled={!items.length}>
            CSV
          </Button>
        )}

        {module.permissions.create && (
          <Button size="sm" icon={<Plus size={13} />} onClick={() => openEditor(null)}>
            Novo
          </Button>
        )}
      </div>

      {error && <Notice text={error} tone="error" onClose={() => setError(null)} />}
      {notice && <Notice text={notice} onClose={() => setNotice(null)} />}

      {/* --------------------------------------------------------- filtros */}
      {showFilters && filterFields.length > 0 && (
        <div className="grid grid-cols-1 gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-3 sm:grid-cols-3 lg:grid-cols-4">
          {filterFields.map((field) => (
            <Field key={field.key} label={field.label}>
              {field.type === "bool" ? (
                <select
                  className={inputClass}
                  value={filters[field.key] ?? ""}
                  onChange={(event) => setFilters((prev) => ({ ...prev, [field.key]: event.target.value }))}
                >
                  <option value="">Todos</option>
                  <option value="true">Sim</option>
                  <option value="false">Não</option>
                </select>
              ) : field.type === "reference" || field.type === "select" ? (
                <select
                  className={inputClass}
                  value={filters[field.key] ?? ""}
                  onChange={(event) => setFilters((prev) => ({ ...prev, [field.key]: event.target.value }))}
                >
                  <option value="">Todos</option>
                  {(field.type === "reference"
                    ? Object.entries(references[field.key] ?? {}).map(([id, label]) => ({ value: id, label }))
                    : field.options
                  ).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className={inputClass}
                  value={filters[field.key] ?? ""}
                  onChange={(event) => setFilters((prev) => ({ ...prev, [field.key]: event.target.value }))}
                />
              )}
            </Field>
          ))}
          <Field label="Ordenar por">
            <select className={inputClass} value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="">Predefinido</option>
              {module.fields
                .filter((field) => !field.system && field.type !== "json" && field.type !== "textarea")
                .map((field) => (
                  <option key={field.key} value={field.key}>
                    {field.label}
                  </option>
                ))}
            </select>
          </Field>
          <div className="flex items-end">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setFilters({});
                setSortBy("");
                setQuery("");
              }}
            >
              Limpar
            </Button>
          </div>
        </div>
      )}

      {/* ----------------------------------------------------- indicadores */}
      {showStats && stats && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Total</p>
            <p className="mt-0.5 text-[22px] font-semibold text-foreground">{new Intl.NumberFormat("pt-PT").format(stats.total)}</p>
            {metrics.length > 0 && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {metrics.slice(0, 2).map((metric) => `${metric.label}: ${formatMoney(metric.sum)}`).join(" · ")}
              </p>
            )}
          </div>
          {grouped.slice(0, 2).map((group) => (
            <div key={group.field} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{group.label}</p>
              <ul className="mt-1 space-y-1">
                {group.buckets.slice(0, 5).map((bucket) => (
                  <li key={bucket.key} className="flex items-center gap-2 text-[11.5px]">
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{bucket.label}</span>
                    <span className="h-1.5 flex-[2] overflow-hidden rounded-full bg-white/8">
                      <span
                        className="block h-full rounded-full bg-gradient-to-r from-teal-300 to-sky-500"
                        style={{ width: `${Math.max(4, (bucket.count / Math.max(1, group.buckets[0].count)) * 100)}%` }}
                      />
                    </span>
                    <span className="w-8 shrink-0 text-right font-medium text-foreground">{bucket.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {/* --------------------------------------------------------- listagem */}
      <div className="overflow-hidden rounded-xl border border-white/8 bg-white/[0.02]">
        {loading ? (
          <p className="flex items-center justify-center gap-2 py-10 text-[12.5px] text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> A carregar {module.label.toLowerCase()}…
          </p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <LayoutGrid size={20} className="text-muted-foreground/70" />
            <p className="text-[13px] text-foreground">Sem registos</p>
            <p className="max-w-md text-[11.5px] text-muted-foreground">
              {module.permissions.create
                ? `Ainda não há ${module.label.toLowerCase()}. Use «Novo» para criar o primeiro registo.`
                : `O seu perfil não permite criar ${module.label.toLowerCase()}.`}
            </p>
          </div>
        ) : (
          <div className="max-h-[62vh] overflow-auto">
            <table className="w-full min-w-[720px] border-collapse text-left">
              <thead className="sticky top-0 z-10 bg-[#0a1c24]/95 backdrop-blur">
                <tr>
                  {columnFields.map((field) => (
                    <th key={field.key} className="whitespace-nowrap px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {field.label}
                    </th>
                  ))}
                  <th className="w-20 px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="cursor-pointer border-t border-white/6 transition hover:bg-white/[0.05]"
                    onClick={() => void openDetail(item)}
                  >
                    {columnFields.map((field) => (
                      <td key={field.key} className="max-w-[280px] truncate px-3 py-2 text-[12.5px] text-foreground">
                        {renderCell(field, item, references)}
                      </td>
                    ))}
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {module.permissions.update && (
                        <button
                          type="button"
                          className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                          onClick={(event) => {
                            event.stopPropagation();
                            openEditor(item);
                          }}
                          title="Alterar"
                        >
                          <Pencil size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {items.length > 0 && (
        <p className="px-1 text-[11px] text-muted-foreground">
          A mostrar {items.length} de {total} registos{total > items.length ? " — refine a pesquisa para ver os restantes." : "."}
        </p>
      )}

      {/* ------------------------------------------------------------ IA */}
      {module.slug === "ai-insights" && module.permissions.create && <CrmInsightGenerator onDone={(text) => { setNotice(text); void reload(); }} onError={setError} />}
      {module.slug === "ai-interactions" && module.permissions.create && <CrmAiComposer onAnswered={() => void reload()} onError={setError} />}

      {/* ---------------------------------------------------------- ficha */}
      {detail && (
        <Modal
          title={detail.label || module.singular}
          subtitle={`${module.singular} · atualizado a ${String(detail.updated_at ?? "").slice(0, 16).replace("T", " ")}`}
          onClose={() => setDetail(null)}
          wide
          footer={
            <>
              {module.permissions.delete && (
                <Button size="sm" variant="danger" icon={<Trash2 size={13} />} onClick={() => void remove(detail)}>
                  Eliminar
                </Button>
              )}
              {module.permissions.update && (
                <Button size="sm" icon={<Pencil size={13} />} onClick={() => openEditor(detail)}>
                  Alterar
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>
                Fechar
              </Button>
            </>
          }
        >
          <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
            {module.fields
              .filter((field) => !field.system)
              .map((field) => (
                <div key={field.key} className={field.type === "textarea" || field.type === "json" ? "sm:col-span-2" : ""}>
                  <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{field.label}</dt>
                  <dd className="whitespace-pre-wrap break-words text-[12.5px] text-foreground">
                    {renderCell(field, detail, references)}
                  </dd>
                </div>
              ))}
          </dl>
        </Modal>
      )}

      {/* --------------------------------------------------------- editor */}
      {editor && (
        <Modal
          title={editor.record ? `Alterar ${module.singular.toLowerCase()}` : `Novo ${module.singular.toLowerCase()}`}
          subtitle={module.description}
          onClose={() => setEditor(null)}
          wide
          footer={
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditor(null)}>
                Cancelar
              </Button>
              <Button size="sm" loading={saving} icon={<Check size={13} />} onClick={() => void submit()}>
                Guardar
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {writableFields.map((field) => (
              <Field
                key={field.key}
                label={`${field.label}${field.required ? " *" : ""}`}
                hint={field.help}
                wide={field.type === "textarea" || field.type === "json" || field.type === "multiselect"}
              >
                <FieldInput
                  field={field}
                  value={editor.draft[field.key]}
                  references={references}
                  onChange={(next) => setEditor((prev) => (prev ? { ...prev, draft: { ...prev.draft, [field.key]: next } } : prev))}
                />
              </Field>
            ))}
          </div>
          {module.slug === "users" && (
            <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-400/10 px-3 py-2 text-[11.5px] text-amber-100">
              O perfil, a área, o departamento e a equipa definem o que este utilizador vê no CRM e aplicam-se no pedido seguinte.
            </p>
          )}
        </Modal>
      )}

      {/* ------------------------------------------------------- matriz RBAC */}
      {module.slug === "roles" && <CrmRbacPanel />}
    </div>
  );
}

/** Célula formatada (com etiquetas de referência quando existirem). */
function renderCell(field: CrmFieldMeta, record: Record<string, unknown>, references: Record<string, Record<string, string>>) {
  const value = record[field.key];
  if (field.type === "reference") {
    const label = value ? references[field.key]?.[String(value)] : "";
    return label || (value ? <span className="text-muted-foreground">{String(value)}</span> : "—");
  }
  if (field.type === "select") {
    return <Badge className="bg-white/8 text-muted-foreground">{formatFieldValue(field, value)}</Badge>;
  }
  if (field.type === "multiselect" && Array.isArray(value)) {
    if (!value.length) return "—";
    return (
      <span className="flex flex-wrap gap-1">
        {value.slice(0, 3).map((item) => (
          <Badge key={String(item)} className="bg-white/8 text-muted-foreground">
            {field.options.find((option) => option.value === String(item))?.label ?? String(item)}
          </Badge>
        ))}
        {value.length > 3 && <span className="text-[11px] text-muted-foreground">+{value.length - 3}</span>}
      </span>
    );
  }
  if (field.type === "bool") {
    return value ? <Check size={13} className="text-teal-300" /> : "—";
  }
  return formatFieldValue(field, value);
}

/* ------------------------------------------------------------- IA: perceções */

function CrmInsightGenerator({ onDone, onError }: { onDone: (text: string) => void; onError: (text: string) => void }) {
  const [running, setRunning] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-indigo-300/20 bg-indigo-400/[0.07] px-3 py-2.5">
      <Sparkles size={14} className="text-indigo-200" />
      <p className="min-w-0 flex-1 text-[11.5px] text-indigo-100">
        O motor analisa o pipeline, a agenda, os casos, os leads, as previsões e as campanhas e cria ou atualiza perceções.
      </p>
      <Button
        size="sm"
        variant="secondary"
        loading={running}
        onClick={async () => {
          setRunning(true);
          try {
            const result = await generateCrmInsights();
            onDone(`Perceções: ${result.created} novas, ${result.updated} atualizadas, ${result.preserved} preservadas.`);
          } catch (err) {
            onError(err instanceof Error ? err.message : "Não foi possível gerar perceções");
          } finally {
            setRunning(false);
          }
        }}
      >
        Gerar perceções
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------ IA: assistente */

function CrmAiComposer({ onAnswered, onError }: { onAnswered: () => void; onError: (text: string) => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ text: string; provider: string; model: string; status: string } | null>(null);
  const [running, setRunning] = useState(false);

  const send = async () => {
    const text = question.trim();
    if (text.length < 3) return;
    setRunning(true);
    try {
      const result = await askCrmAi(text);
      setAnswer({ text: result.answer, provider: result.provider, model: result.model, status: result.status });
      setQuestion("");
      onAnswered();
    } catch (err) {
      onError(err instanceof Error ? err.message : "O assistente não respondeu");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="rounded-xl border border-teal-300/20 bg-teal-400/[0.06] p-3">
      <p className="mb-2 flex items-center gap-2 text-[12px] font-medium text-teal-100">
        <Sparkles size={13} /> Assistente de CRM
      </p>
      <p className="mb-2 text-[11.5px] text-muted-foreground">
        Pergunte pelos seus dados («quais são as oportunidades paradas?», «como está a previsão do trimestre?»).
        A resposta usa apenas os registos a que tem acesso.
      </p>
      <div className="flex items-end gap-2">
        <textarea
          className={`${inputClass} min-h-[54px] flex-1`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Escreva a pergunta…"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <Button size="sm" loading={running} icon={<Send size={13} />} onClick={() => void send()}>
          Perguntar
        </Button>
      </div>
      {answer && (
        <div className="mt-3 rounded-lg border border-white/10 bg-[#08181f] p-3">
          <p className="whitespace-pre-wrap text-[12.5px] text-foreground">{answer.text}</p>
          <p className="mt-2 text-[10.5px] text-muted-foreground">
            {answer.provider ? `${answer.provider}${answer.model ? ` · ${answer.model}` : ""}` : "resposta determinística (sem modelo configurado)"}
          </p>
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- matriz RBAC */

export function CrmRbacPanel() {
  const [rbac, setRbac] = useState<CrmRbacMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [group, setGroup] = useState<string>("");
  const [view, setView] = useState<"matriz" | "pessoas" | "equipas">("matriz");
  const loaded = useRef(false);

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    void getCrmRbac()
      .then(setRbac)
      .catch((err) => setError(err instanceof Error ? err.message : "Não foi possível carregar a matriz de acesso"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <p className="flex items-center gap-2 py-6 text-[12.5px] text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> A carregar a matriz de acesso…
      </p>
    );
  }
  if (error) return <Notice text={error} tone="error" />;
  if (!rbac) return null;

  const groups = Array.from(new Set(rbac.modules.map((module) => module.group)));
  const rows = rbac.matrix.filter((entry) => !group || entry.group === group);

  return (
    <div className="mt-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <ShieldCheck size={15} className="text-teal-300" />
        <h3 className="text-[13px] font-semibold text-foreground">Matriz de acesso</h3>
        <span className="text-[11.5px] text-muted-foreground">
          {rbac.roles.length} perfis · {rbac.areas.length} áreas · {rbac.departments.length} departamentos · {rbac.modules.length} módulos
        </span>
        <div className="flex-1" />
        {(["matriz", "pessoas", "equipas"] as const).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setView(item)}
            className={[
              "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11.5px] transition",
              view === item ? "bg-white/[0.14] font-medium text-foreground" : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
            ].join(" ")}
          >
            {item === "matriz" ? <Table2 size={12} /> : item === "pessoas" ? <ShieldCheck size={12} /> : <LayoutGrid size={12} />}
            {item === "matriz" ? "Perfis × módulos" : item === "pessoas" ? "Atribuições" : "Equipas"}
          </button>
        ))}
      </div>

      {view === "matriz" && (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setGroup("")}
              className={[
                "rounded-full px-2.5 py-0.5 text-[11px] transition",
                group === "" ? "bg-teal-400/20 text-teal-100" : "bg-white/6 text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              Todos
            </button>
            {groups.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setGroup(item)}
                className={[
                  "rounded-full px-2.5 py-0.5 text-[11px] transition",
                  group === item ? "bg-teal-400/20 text-teal-100" : "bg-white/6 text-muted-foreground hover:text-foreground",
                ].join(" ")}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="max-h-[52vh] overflow-auto rounded-lg border border-white/8">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead className="sticky top-0 bg-[#0a1c24]/95 backdrop-blur">
                <tr>
                  <th className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">Módulo</th>
                  {rbac.roles.map((role) => (
                    <th key={role.key} className="px-2 py-2 text-[11px] uppercase tracking-wide text-muted-foreground" title={`${role.label} · ${role.scope}`}>
                      {role.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.module} className="border-t border-white/6">
                    <td className="px-3 py-1.5 text-[12px] text-foreground">
                      {entry.label}
                      {entry.read_only && <span className="ml-1.5 text-[10px] text-muted-foreground">(leitura)</span>}
                    </td>
                    {rbac.roles.map((role) => {
                      const grant = entry.roles[role.key];
                      return (
                        <td key={role.key} className="px-2 py-1.5">
                          {grant?.allowed ? (
                            <span
                              className="inline-flex items-center gap-1 rounded-full bg-teal-400/15 px-1.5 py-0.5 text-[10px] text-teal-100"
                              title={`${grant.actions.join(", ")} · âmbito ${grant.scope}`}
                            >
                              <Check size={9} />
                              {grant.actions.length}
                            </span>
                          ) : (
                            <span className="text-[11px] text-muted-foreground/50">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {view === "pessoas" && (
        <div className="overflow-hidden rounded-lg border border-white/8">
          <table className="w-full min-w-[560px] border-collapse text-left">
            <thead className="bg-[#0a1c24]/95">
              <tr>
                {["Utilizador", "Perfil", "Área", "Departamento", "Equipa", "Estado"].map((label) => (
                  <th key={label} className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rbac.members.map((member) => {
                const role = rbac.role_index[String(member.role ?? "")];
                return (
                  <tr key={member.id} className="border-t border-white/6 text-[12px]">
                    <td className="px-3 py-1.5 text-foreground">
                      {String(member.name ?? member.email ?? member.id)}
                      <span className="ml-2 text-[10.5px] text-muted-foreground">{String(member.email ?? "")}</span>
                    </td>
                    <td className="px-3 py-1.5">{role?.label ?? String(member.role ?? "—")}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{String(member.area ?? "—")}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{String(member.department ?? "—")}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{String(member.team ?? "—")}</td>
                    <td className="px-3 py-1.5">
                      <Badge className="bg-white/8 text-muted-foreground">{String(member.status ?? "ativo")}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {view === "equipas" && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {rbac.teams.length === 0 && <p className="text-[12px] text-muted-foreground">Ainda não há equipas definidas.</p>}
          {rbac.teams.map((team) => (
            <div key={team.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12.5px] font-medium text-foreground">{String(team.name ?? team.id)}</p>
              <p className="text-[11px] text-muted-foreground">
                {String(team.area ?? "—")} · {String(team.department ?? "—")}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Responsável: {String(team.manager_email ?? "—")} · {Array.isArray(team.members) ? team.members.length : 0} membro(s)
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
