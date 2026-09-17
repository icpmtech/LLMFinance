/**
 * Aplicação «CRM» do IQ OS.
 *
 * Um CRM comercial assente nos dados da plataforma: contas (empresas, ligáveis
 * ao cadastro do EmpresasIQ pelo NIF), contactos, oportunidades (pipeline em
 * Kanban) e atividades/compromissos, mais um painel de indicadores.
 *
 * Estado: tudo vem da API (`/crm/*`, índice `finance_crm`). O âmbito é o do
 * utilizador (ou de toda a equipa, para administradores), conforme o `meta`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  Check,
  CheckCircle2,
  Columns3,
  ExternalLink,
  FileText,
  Filter,
  LayoutDashboard,
  Link2,
  Loader2,
  Mail,
  NotebookPen,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Target,
  Trash2,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import {
  createCrmAccountFromEntity,
  createCrmRecord,
  deleteCrmRecord,
  getCrmAccountTimeline,
  getCrmMeta,
  getCrmOverview,
  listCrmAccounts,
  listCrmActivities,
  listCrmContacts,
  listCrmDeals,
  searchCrmEntities,
  syncCrmAccountEntity,
  updateCrmRecord,
  type CrmAccount,
  type CrmAccountTimeline,
  type CrmActivity,
  type CrmActivityType,
  type CrmContact,
  type CrmDeal,
  type CrmDealStage,
  type CrmEntityCandidate,
  type CrmKind,
  type CrmMeta,
  type CrmOverview,
  type CrmPriority,
  type CrmRecord,
} from "../crmApi";

/* ------------------------------------------------------------------ aspeto */

const STAGE_META: Record<CrmDealStage, { label: string; bar: string; text: string }> = {
  prospeccao: { label: "Prospeção", bar: "bg-slate-400", text: "text-slate-300" },
  qualificacao: { label: "Qualificação", bar: "bg-sky-400", text: "text-sky-300" },
  proposta: { label: "Proposta", bar: "bg-indigo-400", text: "text-indigo-300" },
  negociacao: { label: "Negociação", bar: "bg-amber-400", text: "text-amber-300" },
  ganho: { label: "Ganho", bar: "bg-teal-400", text: "text-teal-300" },
  perdido: { label: "Perdido", bar: "bg-rose-400", text: "text-rose-300" },
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  prospect: { label: "Prospecto", className: "bg-sky-400/15 text-sky-200" },
  cliente: { label: "Cliente", className: "bg-teal-400/15 text-teal-200" },
  inativo: { label: "Inativo", className: "bg-white/10 text-muted-foreground" },
};

const ACTIVITY_META: Record<CrmActivityType, { label: string; icon: LucideIcon }> = {
  chamada: { label: "Chamada", icon: Phone },
  reuniao: { label: "Reunião", icon: Users },
  email: { label: "Email", icon: Mail },
  tarefa: { label: "Tarefa", icon: CheckCircle2 },
  nota: { label: "Nota", icon: NotebookPen },
};

const PRIORITY_META: Record<CrmPriority, { label: string; className: string }> = {
  baixa: { label: "Baixa", className: "bg-white/10 text-muted-foreground" },
  media: { label: "Média", className: "bg-amber-400/15 text-amber-200" },
  alta: { label: "Alta", className: "bg-rose-400/15 text-rose-200" },
};

/* -------------------------------------------------------------- formatação */

function formatCurrency(value?: number | null, currency = "EUR") {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatCompact(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString("pt-PT");
}

function formatMonth(value: string) {
  if (!value) return "—";
  const parsed = new Date(`${value}-01T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("pt-PT", { month: "short", year: "2-digit" });
}

/** Valor para `<input type="date">`. */
function dateInputValue(value?: string | null) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function startOfToday() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

type Bucket = "overdue" | "today" | "week" | "later" | "none";

function bucketOf(value?: string | null): Bucket {
  if (!value) return "none";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "none";
  const today = startOfToday();
  const day = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const diff = Math.round((day.getTime() - today.getTime()) / 86400000);
  if (diff < 0) return "overdue";
  if (diff === 0) return "today";
  if (diff <= 7) return "week";
  return "later";
}

function relativeDay(value?: string | null) {
  const bucket = bucketOf(value);
  if (bucket === "none") return "Sem data";
  const parsed = new Date(String(value));
  const today = startOfToday();
  const day = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const diff = Math.round((day.getTime() - today.getTime()) / 86400000);
  if (diff === 0) return "Hoje";
  if (diff === 1) return "Amanhã";
  if (diff === -1) return "Ontem";
  if (diff < 0) return `${Math.abs(diff)} dias em atraso`;
  if (diff <= 7) return `Em ${diff} dias`;
  return formatDate(value);
}

/* --------------------------------------------------------- peças de interface */

function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "teal",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: "teal" | "sky" | "amber" | "rose" | "indigo";
}) {
  const tones: Record<string, string> = {
    teal: "from-teal-400/20 to-emerald-500/5 text-teal-300",
    sky: "from-sky-400/20 to-blue-500/5 text-sky-300",
    amber: "from-amber-400/20 to-orange-500/5 text-amber-300",
    rose: "from-rose-400/20 to-pink-500/5 text-rose-300",
    indigo: "from-indigo-400/20 to-violet-500/5 text-indigo-300",
  };
  return (
    <div className="glass-card min-w-0 rounded-xl p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="stat-value mt-1 truncate text-xl font-semibold text-foreground">{value}</p>
          {hint && <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</p>}
        </div>
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br ${tones[tone]}`}>
          <Icon size={15} />
        </span>
      </div>
    </div>
  );
}

const INPUT_CLASS =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[13px] text-foreground outline-none transition placeholder:text-muted-foreground/70 focus:border-teal-400/50 focus:bg-white/[0.07]";

function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function Button({
  children,
  onClick,
  variant = "ghost",
  type = "button",
  disabled,
  title,
  formId,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "ghost" | "primary" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  title?: string;
  /** Liga um botão de submissão a um formulário fora deste nó (atributo `form`). */
  formId?: string;
}) {
  const variants: Record<string, string> = {
    ghost: "border-white/10 bg-white/[0.05] text-foreground hover:bg-white/[0.1]",
    primary: "border-teal-400/30 bg-teal-500/20 text-teal-100 hover:bg-teal-500/30",
    danger: "border-rose-400/30 bg-rose-500/15 text-rose-200 hover:bg-rose-500/25",
  };
  return (
    <button
      type={type}
      form={formId}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]}`}
    >
      {children}
    </button>
  );
}

function Badge({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function EmptyState({ icon: Icon, title, hint }: { icon: LucideIcon; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 px-6 py-10 text-center">
      <Icon size={22} className="text-muted-foreground" />
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      {hint && <p className="max-w-md text-[12px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-black/55 p-4 pb-32 backdrop-blur-sm">
      <div
        className={`glass-modal my-4 w-full ${wide ? "max-w-3xl" : "max-w-xl"} rounded-2xl p-4 shadow-2xl`}
        role="dialog"
        aria-label={title}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold text-foreground">{title}</h2>
            {subtitle && <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
            aria-label="Fechar"
          >
            <X size={15} />
          </button>
        </div>
        <div className="mt-3">{children}</div>
        {footer && <div className="mt-4 flex items-center justify-between gap-2 border-t border-white/8 pt-3">{footer}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ editor */

const NUMERIC_FIELDS = new Set(["employees", "annual_revenue", "amount", "probability"]);

type Draft = Record<string, unknown>;

/** Nome do registo em edição (subtítulo de janelas e fichas). */
export function crmRecordLabel(record?: CrmAccount | CrmContact | CrmDeal | CrmActivity | null) {
  if (!record) return "";
  const item = record as { name?: string; title?: string; subject?: string };
  return String(item.name ?? item.title ?? item.subject ?? "");
}

const EDITOR_TITLES: Record<CrmKind, string> = {
  accounts: "conta",
  contacts: "contacto",
  deals: "oportunidade",
  activities: "atividade",
};

/** Título de uma janela/modal de edição («Nova conta», «Editar oportunidade»…). */
export function crmEditorTitle(kind: CrmKind, record?: { id?: string } | null) {
  return `${record?.id ? "Editar" : "Nova"} ${EDITOR_TITLES[kind] ?? "registo"}`;
}

/** Constrói o corpo do pedido: campos vazios viram `null`, números viram números. */
function buildPayload(kind: CrmKind, draft: Draft) {
  const payload: Record<string, unknown> = {};
  const skip = new Set([
    "id", "kind", "doc_id", "owner_id", "owner_email", "created_at", "updated_at",
    "entity", "weighted_amount", "closed_at", "done_at", "account_name", "contact_name",
  ]);
  for (const [key, value] of Object.entries(draft)) {
    if (skip.has(key)) continue;
    if (kind === "accounts" && key === "nif") {
      const text = typeof value === "string" ? value.trim() : "";
      payload[key] = text || null;
      continue;
    }
    if (key === "tags") {
      const list = Array.isArray(value)
        ? value
        : String(value ?? "")
            .split(",")
            .map((chunk) => chunk.trim())
            .filter(Boolean);
      payload[key] = list;
      continue;
    }
    if (NUMERIC_FIELDS.has(key)) {
      const text = String(value ?? "").trim();
      payload[key] = text === "" ? null : Number(text.replace(",", "."));
      continue;
    }
    if (typeof value === "string") {
      const text = value.trim();
      payload[key] = text === "" ? null : text;
      continue;
    }
    payload[key] = value ?? null;
  }
  return payload;
}

function RecordEditor({
  kind,
  record,
  defaults,
  meta,
  accounts,
  contacts,
  deals,
  onClose,
  onSaved,
}: {
  kind: CrmKind;
  record?: CrmAccount | CrmContact | CrmDeal | CrmActivity | null;
  defaults?: Draft;
  meta: CrmMeta;
  accounts: CrmAccount[];
  contacts: CrmContact[];
  deals: CrmDeal[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => ({
    ...(record ?? {}),
    ...(defaults ?? {}),
    tags: ((record as { tags?: string[] } | null)?.tags ?? []).join(", "),
    expected_close_date: dateInputValue((record as CrmDeal | null)?.expected_close_date),
    due_at: dateInputValue((record as CrmActivity | null)?.due_at),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = useCallback((key: string, value: unknown) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = buildPayload(kind, draft);
      const id = (record as { id?: string } | null)?.id;
      if (id) await updateCrmRecord(kind, id, payload);
      else await createCrmRecord(kind, payload);
      notifyCrmChanged();
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    const id = (record as { id?: string } | null)?.id;
    if (!id) return;
    const label =
      kind === "accounts"
        ? "Apagar a conta arrasta também os contactos, oportunidades e atividades ligados. Continuar?"
        : "Apagar este registo?";
    if (typeof window !== "undefined" && !window.confirm(label)) return;
    setSaving(true);
    try {
      await deleteCrmRecord(kind, id);
      notifyCrmChanged();
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível apagar");
      setSaving(false);
    }
  };

  const id = (record as { id?: string } | null)?.id;
  /* O rodapé vive fora do formulário: o botão de submissão liga-se-lhe pelo
     atributo `form` (o formulário é envolvido por uma janela ou por um modal). */
  const formId = `crm-editor-${kind}`;

  return (
    <div className="flex flex-col gap-3">
      <form id={formId} onSubmit={submit} className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        {kind === "accounts" && (
          <>
            <Field label="Nome" className="@md:col-span-2">
              <input className={INPUT_CLASS} value={String(draft.name ?? "")} onChange={(e) => set("name", e.target.value)} required />
            </Field>
            <Field label="NIF">
              <input className={INPUT_CLASS} value={String(draft.nif ?? "")} onChange={(e) => set("nif", e.target.value)} placeholder="500000000" />
            </Field>
            <Field label="Estado">
              <select className={INPUT_CLASS} value={String(draft.status ?? "prospect")} onChange={(e) => set("status", e.target.value)}>
                {meta.account_statuses.map((status) => (
                  <option key={status} value={status}>{STATUS_META[status]?.label ?? status}</option>
                ))}
              </select>
            </Field>
            <Field label="Setor">
              <input className={INPUT_CLASS} value={String(draft.sector ?? "")} onChange={(e) => set("sector", e.target.value)} />
            </Field>
            <Field label="Website">
              <input className={INPUT_CLASS} value={String(draft.website ?? "")} onChange={(e) => set("website", e.target.value)} />
            </Field>
            <Field label="Email">
              <input className={INPUT_CLASS} type="email" value={String(draft.email ?? "")} onChange={(e) => set("email", e.target.value)} />
            </Field>
            <Field label="Telefone">
              <input className={INPUT_CLASS} value={String(draft.phone ?? "")} onChange={(e) => set("phone", e.target.value)} />
            </Field>
            <Field label="Cidade">
              <input className={INPUT_CLASS} value={String(draft.city ?? "")} onChange={(e) => set("city", e.target.value)} />
            </Field>
            <Field label="País">
              <input className={INPUT_CLASS} value={String(draft.country ?? "")} onChange={(e) => set("country", e.target.value)} />
            </Field>
            <Field label="Colaboradores">
              <input className={INPUT_CLASS} type="number" value={String(draft.employees ?? "")} onChange={(e) => set("employees", e.target.value)} />
            </Field>
            <Field label="Volume de negócios (€)">
              <input className={INPUT_CLASS} type="number" value={String(draft.annual_revenue ?? "")} onChange={(e) => set("annual_revenue", e.target.value)} />
            </Field>
            <Field label="Etiquetas (separadas por vírgulas)" className="@md:col-span-2">
              <input className={INPUT_CLASS} value={String(draft.tags ?? "")} onChange={(e) => set("tags", e.target.value)} />
            </Field>
            <Field label="Notas" className="@md:col-span-2">
              <textarea className={`${INPUT_CLASS} min-h-[84px]`} value={String(draft.notes ?? "")} onChange={(e) => set("notes", e.target.value)} />
            </Field>
          </>
        )}

        {kind === "contacts" && (
          <>
            <Field label="Nome" className="@md:col-span-2">
              <input className={INPUT_CLASS} value={String(draft.name ?? "")} onChange={(e) => set("name", e.target.value)} required />
            </Field>
            <Field label="Conta">
              <select className={INPUT_CLASS} value={String(draft.account_id ?? "")} onChange={(e) => set("account_id", e.target.value)}>
                <option value="">— sem conta —</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>{account.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Cargo">
              <input className={INPUT_CLASS} value={String(draft.title ?? "")} onChange={(e) => set("title", e.target.value)} />
            </Field>
            <Field label="Email">
              <input className={INPUT_CLASS} type="email" value={String(draft.email ?? "")} onChange={(e) => set("email", e.target.value)} />
            </Field>
            <Field label="Telefone">
              <input className={INPUT_CLASS} value={String(draft.phone ?? "")} onChange={(e) => set("phone", e.target.value)} />
            </Field>
            <Field label="Telemóvel">
              <input className={INPUT_CLASS} value={String(draft.mobile ?? "")} onChange={(e) => set("mobile", e.target.value)} />
            </Field>
            <Field label="LinkedIn">
              <input className={INPUT_CLASS} value={String(draft.linkedin ?? "")} onChange={(e) => set("linkedin", e.target.value)} />
            </Field>
            <Field label="Contacto principal">
              <select className={INPUT_CLASS} value={String(draft.is_primary ?? "")} onChange={(e) => set("is_primary", e.target.value)}>
                <option value="">—</option>
                <option value="true">Sim</option>
                <option value="false">Não</option>
              </select>
            </Field>
            <Field label="Notas" className="@md:col-span-2">
              <textarea className={`${INPUT_CLASS} min-h-[84px]`} value={String(draft.notes ?? "")} onChange={(e) => set("notes", e.target.value)} />
            </Field>
          </>
        )}

        {kind === "deals" && (
          <>
            <Field label="Título" className="@md:col-span-2">
              <input className={INPUT_CLASS} value={String(draft.title ?? "")} onChange={(e) => set("title", e.target.value)} required />
            </Field>
            <Field label="Conta">
              <select className={INPUT_CLASS} value={String(draft.account_id ?? "")} onChange={(e) => set("account_id", e.target.value)}>
                <option value="">— sem conta —</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>{account.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Contacto">
              <select className={INPUT_CLASS} value={String(draft.contact_id ?? "")} onChange={(e) => set("contact_id", e.target.value)}>
                <option value="">—</option>
                {contacts
                  .filter((contact) => !draft.account_id || contact.account_id === draft.account_id)
                  .map((contact) => (
                    <option key={contact.id} value={contact.id}>{contact.name}</option>
                  ))}
              </select>
            </Field>
            <Field label="Fase">
              <select className={INPUT_CLASS} value={String(draft.stage ?? meta.deal_stages[0])} onChange={(e) => set("stage", e.target.value)}>
                {meta.deal_stages.map((stage) => (
                  <option key={stage} value={stage}>{STAGE_META[stage]?.label ?? stage}</option>
                ))}
              </select>
            </Field>
            <Field label="Valor (€)">
              <input className={INPUT_CLASS} type="number" value={String(draft.amount ?? "")} onChange={(e) => set("amount", e.target.value)} />
            </Field>
            <Field label="Probabilidade (%)">
              <input className={INPUT_CLASS} type="number" min={0} max={100} value={String(draft.probability ?? "")} onChange={(e) => set("probability", e.target.value)} />
            </Field>
            <Field label="Fecho previsto">
              <input className={INPUT_CLASS} type="date" value={String(draft.expected_close_date ?? "")} onChange={(e) => set("expected_close_date", e.target.value)} />
            </Field>
            <Field label="Origem">
              <input className={INPUT_CLASS} value={String(draft.source ?? "")} onChange={(e) => set("source", e.target.value)} placeholder="Contratos públicos, INPI…" />
            </Field>
            {String(draft.stage) === "perdido" && (
              <Field label="Motivo da perda">
                <input className={INPUT_CLASS} value={String(draft.loss_reason ?? "")} onChange={(e) => set("loss_reason", e.target.value)} />
              </Field>
            )}
            <Field label="Notas" className="@md:col-span-2">
              <textarea className={`${INPUT_CLASS} min-h-[84px]`} value={String(draft.notes ?? "")} onChange={(e) => set("notes", e.target.value)} />
            </Field>
          </>
        )}

        {kind === "activities" && (
          <>
            <Field label="Assunto" className="@md:col-span-2">
              <input className={INPUT_CLASS} value={String(draft.subject ?? "")} onChange={(e) => set("subject", e.target.value)} required />
            </Field>
            <Field label="Tipo">
              <select className={INPUT_CLASS} value={String(draft.type ?? "tarefa")} onChange={(e) => set("type", e.target.value)}>
                {meta.activity_types.map((type) => (
                  <option key={type} value={type}>{ACTIVITY_META[type]?.label ?? type}</option>
                ))}
              </select>
            </Field>
            <Field label="Prioridade">
              <select className={INPUT_CLASS} value={String(draft.priority ?? "media")} onChange={(e) => set("priority", e.target.value)}>
                {meta.priorities.map((priority) => (
                  <option key={priority} value={priority}>{PRIORITY_META[priority]?.label ?? priority}</option>
                ))}
              </select>
            </Field>
            <Field label="Conta">
              <select className={INPUT_CLASS} value={String(draft.account_id ?? "")} onChange={(e) => set("account_id", e.target.value)}>
                <option value="">— sem conta —</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>{account.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Oportunidade">
              <select className={INPUT_CLASS} value={String(draft.deal_id ?? "")} onChange={(e) => set("deal_id", e.target.value)}>
                <option value="">—</option>
                {(draft.account_id ? deals.filter((deal) => deal.account_id === draft.account_id) : deals).map((deal) => (
                  <option key={deal.id} value={deal.id}>{deal.title}</option>
                ))}
              </select>
            </Field>
            <Field label="Data">
              <input className={INPUT_CLASS} type="date" value={String(draft.due_at ?? "")} onChange={(e) => set("due_at", e.target.value)} />
            </Field>
            <Field label="Concluída">
              <select className={INPUT_CLASS} value={String(draft.done ?? "false")} onChange={(e) => set("done", e.target.value)}>
                <option value="false">Não</option>
                <option value="true">Sim</option>
              </select>
            </Field>
            <Field label="Notas" className="@md:col-span-2">
              <textarea className={`${INPUT_CLASS} min-h-[84px]`} value={String(draft.notes ?? "")} onChange={(e) => set("notes", e.target.value)} />
            </Field>
          </>
        )}
        {error && (
          <p className="flex items-center gap-1.5 text-[12px] text-rose-300 @md:col-span-2">
            <AlertTriangle size={13} /> {error}
          </p>
        )}
      </form>
      <div className="flex items-center justify-between gap-2 border-t border-white/8 pt-3">
        <div>
          {id && (
            <Button variant="danger" onClick={remove} disabled={saving}>
              <Trash2 size={13} /> Apagar
            </Button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={onClose} disabled={saving}>Cancelar</Button>
          <Button variant="primary" type="submit" formId={formId} disabled={saving}>
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Guardar
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Editor em modal (modo página: janelas desligadas). */
function EditorModal(props: React.ComponentProps<typeof RecordEditor>) {
  const { record, kind, onClose } = props;
  return (
    <Modal title={crmEditorTitle(kind, record)} subtitle={crmRecordLabel(record) || undefined} onClose={onClose} wide>
      <RecordEditor {...props} />
    </Modal>
  );
}

/**
 * Oportunidades e atividades de uma conta (usado no formulário de atividades).
 */

/* ----------------------------------------------------------------- pipeline */

function PipelineBoard({
  deals,
  accounts,
  meta,
  onEdit,
  onCreate,
  onMove,
}: {
  deals: CrmDeal[];
  accounts: CrmAccount[];
  meta: CrmMeta;
  onEdit: (deal: CrmDeal) => void;
  onCreate: (stage: CrmDealStage) => void;
  onMove: (deal: CrmDeal, stage: CrmDealStage) => void;
}) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [overStage, setOverStage] = useState<CrmDealStage | null>(null);
  const accountName = useMemo(() => new Map(accounts.map((account) => [account.id, account.name])), [accounts]);

  return (
    <div className="flex min-h-0 gap-3 overflow-x-auto pb-2">
      {meta.deal_stages.map((stage) => {
        const items = deals.filter((deal) => deal.stage === stage);
        const total = items.reduce((sum, deal) => sum + (deal.amount ?? 0), 0);
        const info = STAGE_META[stage] ?? { label: stage, bar: "bg-white/30", text: "text-foreground" };
        const isTarget = overStage === stage && Boolean(dragId);
        return (
          <section
            key={stage}
            onDragOver={(event) => {
              event.preventDefault();
              setOverStage(stage);
            }}
            onDragLeave={() => setOverStage((current) => (current === stage ? null : current))}
            onDrop={(event) => {
              event.preventDefault();
              const id = event.dataTransfer.getData("text/crm-deal") || dragId;
              const deal = deals.find((item) => item.id === id);
              setDragId(null);
              setOverStage(null);
              if (deal && deal.stage !== stage) onMove(deal, stage);
            }}
            className={[
              "flex w-[260px] shrink-0 flex-col rounded-xl border p-2 transition",
              isTarget ? "border-teal-400/50 bg-teal-500/5" : "border-white/8 bg-white/[0.02]",
            ].join(" ")}
          >
            <header className="flex items-center justify-between gap-2 px-1 pb-2">
              <div className="flex min-w-0 items-center gap-1.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${info.bar}`} />
                <h3 className={`truncate text-[12px] font-semibold ${info.text}`}>{info.label}</h3>
                <span className="shrink-0 rounded-full bg-white/8 px-1.5 text-[10px] text-muted-foreground">{items.length}</span>
              </div>
              <button
                type="button"
                onClick={() => onCreate(stage)}
                title={`Nova oportunidade em ${info.label}`}
                className="rounded-md p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
              >
                <Plus size={13} />
              </button>
            </header>
            <p className="stat-value px-1 pb-2 text-[11px] text-muted-foreground">{formatCurrency(total)}</p>
            <div className="flex min-h-[80px] flex-col gap-2">
              {items.map((deal) => (
                <article
                  key={deal.id}
                  draggable
                  onDragStart={(event) => {
                    setDragId(deal.id);
                    event.dataTransfer.setData("text/crm-deal", deal.id);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverStage(null);
                  }}
                  onClick={() => onEdit(deal)}
                  className="glass-card cursor-grab rounded-lg p-2.5 transition hover:border-teal-400/40 active:cursor-grabbing"
                >
                  <p className="truncate text-[12.5px] font-medium text-foreground">{deal.title}</p>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                    {accountName.get(deal.account_id ?? "") ?? "Sem conta"}
                  </p>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="stat-value text-[12px] font-semibold text-teal-300">
                      {formatCurrency(deal.amount, deal.currency)}
                    </span>
                    <span className="text-[10.5px] text-muted-foreground">{deal.probability ?? 0}%</span>
                  </div>
                  {deal.expected_close_date && (
                    <p className="mt-1 flex items-center gap-1 text-[10.5px] text-muted-foreground">
                      <CalendarClock size={10} /> {formatDate(deal.expected_close_date)}
                    </p>
                  )}
                </article>
              ))}
              {items.length === 0 && (
                <p className="rounded-lg border border-dashed border-white/10 px-2 py-4 text-center text-[11px] text-muted-foreground">
                  Sem oportunidades
                </p>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------- contas */

function AccountsPanel({
  accounts,
  deals,
  contacts,
  meta,
  onEdit,
  onOpen,
  onCreate,
  onLinked,
}: {
  accounts: CrmAccount[];
  deals: CrmDeal[];
  contacts: CrmContact[];
  meta: CrmMeta;
  onEdit: (account: CrmAccount) => void;
  onOpen: (account: CrmAccount) => void;
  onCreate: () => void;
  onLinked: () => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [showLink, setShowLink] = useState(false);
  const [linkQuery, setLinkQuery] = useState("");
  const [candidates, setCandidates] = useState<CrmEntityCandidate[]>([]);
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const contactCount = useMemo(() => {
    const map = new Map<string, number>();
    for (const contact of contacts) {
      if (!contact.account_id) continue;
      map.set(contact.account_id, (map.get(contact.account_id) ?? 0) + 1);
    }
    return map;
  }, [contacts]);

  const pipeline = useMemo(() => {
    const map = new Map<string, number>();
    for (const deal of deals) {
      if (!deal.account_id || !meta.open_stages.includes(deal.stage)) continue;
      map.set(deal.account_id, (map.get(deal.account_id) ?? 0) + (deal.amount ?? 0));
    }
    return map;
  }, [deals, meta.open_stages]);

  useEffect(() => {
    const term = linkQuery.trim();
    if (term.length < 2) {
      setCandidates([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      searchCrmEntities(term, 8)
        .then((result) => {
          if (!cancelled) setCandidates(result.items ?? []);
        })
        .catch(() => {
          if (!cancelled) setCandidates([]);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [linkQuery]);

  const normalized = query.trim().toLowerCase();
  const rows = accounts.filter((account) => {
    if (status && (account.status ?? "prospect") !== status) return false;
    if (!normalized) return true;
    return [account.name, account.nif, account.email, account.city, account.sector]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalized));
  });

  const link = async (nif?: string) => {
    if (!nif) return;
    setLinking(true);
    setLinkError(null);
    try {
      await createCrmAccountFromEntity(nif);
      setShowLink(false);
      setLinkQuery("");
      setCandidates([]);
      onLinked();
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : "Não foi possível criar a conta");
    } finally {
      setLinking(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            className={`${INPUT_CLASS} pl-8`}
            placeholder="Pesquisar contas (nome, NIF, cidade…)"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="relative">
          <Filter size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <select className={`${INPUT_CLASS} w-[150px] pl-7`} value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Todos os estados</option>
            {meta.account_statuses.map((value) => (
              <option key={value} value={value}>{STATUS_META[value]?.label ?? value}</option>
            ))}
          </select>
        </div>
        <Button onClick={() => setShowLink((value) => !value)} title="Criar conta a partir do cadastro de entidades">
          <Link2 size={13} /> Ligar ao EmpresasIQ
        </Button>
        <Button variant="primary" onClick={onCreate}>
          <Plus size={13} /> Nova conta
        </Button>
      </div>

      {showLink && (
        <div className="glass-card rounded-xl p-3">
          <p className="text-[12px] text-muted-foreground">
            Procure a empresa no cadastro do EmpresasIQ (dados de contratos públicos) para criar a conta já com o NIF e o
            resumo de contratação.
          </p>
          <div className="relative mt-2">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              className={`${INPUT_CLASS} pl-8`}
              placeholder="Nome da empresa ou NIF (mín. 2 caracteres)"
              value={linkQuery}
              onChange={(event) => setLinkQuery(event.target.value)}
            />
          </div>
          {linkError && <p className="mt-2 text-[12px] text-rose-300">{linkError}</p>}
          {candidates.length > 0 && (
            <ul className="mt-2 divide-y divide-white/5">
              {candidates.map((candidate) => (
                <li key={`${candidate.nif}-${candidate.name}`} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="min-w-0">
                    <p className="truncate text-[12.5px] text-foreground">{candidate.name}</p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {candidate.nif ? `NIF ${candidate.nif} · ` : ""}
                      {candidate.contracts_count ?? 0} contratos · {formatCompact(candidate.total_value)} €
                    </p>
                  </div>
                  <Button variant="primary" onClick={() => link(candidate.nif)} disabled={linking || !candidate.nif}>
                    {linking ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Criar conta
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {linkQuery.trim().length >= 2 && candidates.length === 0 && (
            <p className="mt-2 text-[11.5px] text-muted-foreground">Sem resultados no cadastro de entidades.</p>
          )}
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="Sem contas"
          hint="Crie uma conta à mão ou ligue-a a uma empresa do EmpresasIQ para trazer o resumo de contratos públicos."
        />
      ) : (
        <div className="glass-card overflow-x-auto rounded-xl">
          <table className="w-full min-w-[720px] text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-white/8">
                <th className="px-3 py-2 font-medium">Conta</th>
                <th className="px-3 py-2 font-medium">Estado</th>
                <th className="px-3 py-2 font-medium">Setor</th>
                <th className="px-3 py-2 text-right font-medium">Contratos</th>
                <th className="px-3 py-2 text-right font-medium">Pipeline aberto</th>
                <th className="px-3 py-2 text-right font-medium">Contactos</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((account) => {
                const statusInfo = STATUS_META[account.status ?? "prospect"] ?? STATUS_META.prospect;
                return (
                  <tr key={account.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.03]">
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => onOpen(account)} className="text-left">
                        <span className="block truncate font-medium text-foreground">{account.name}</span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {account.nif ? `NIF ${account.nif}` : account.city || account.email || "—"}
                        </span>
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <Badge className={statusInfo.className}>{statusInfo.label}</Badge>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{account.sector || "—"}</td>
                    <td className="stat-value px-3 py-2 text-right text-muted-foreground">
                      {account.entity?.contracts_count ?? "—"}
                    </td>
                    <td className="stat-value px-3 py-2 text-right text-teal-300">
                      {formatCurrency(pipeline.get(account.id) ?? 0)}
                    </td>
                    <td className="stat-value px-3 py-2 text-right text-muted-foreground">
                      {contactCount.get(account.id) ?? 0}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => onEdit(account)}
                        className="rounded-md p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                        title="Editar conta"
                      >
                        <Pencil size={13} />
                      </button>
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

/* -------------------------------------------------------- ficha da conta */

/**
 * Dossier de uma conta: indicadores, resumo do EmpresasIQ, notas, contactos,
 * oportunidades e atividades. É o mesmo conteúdo no modal (modo página) e na
 * janela própria `crm-account:<id>`.
 */
function AccountDossier({
  accountId,
  openStages,
  onEdit,
  onOpenCompany,
  onChanged,
}: {
  accountId: string;
  openStages?: CrmDealStage[];
  onEdit?: (account: CrmAccount) => void;
  onOpenCompany?: (nif: string) => void;
  onChanged?: () => void;
}) {
  const [timeline, setTimeline] = useState<CrmAccountTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const stages = openStages ?? FALLBACK_OPEN_STAGES;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTimeline(await getCrmAccountTimeline(accountId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar a conta");
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  const account = timeline?.account;

  const sync = async () => {
    try {
      await syncCrmAccountEntity(accountId);
      await load();
      notifyCrmChanged();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível sincronizar");
    }
  };

  const snapshot = account?.entity;
  const deals = timeline?.deals ?? [];
  const openValue = deals
    .filter((deal) => stages.includes(deal.stage))
    .reduce((sum, deal) => sum + (deal.amount ?? 0), 0);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {account?.nif && onOpenCompany && (
          <Button onClick={() => onOpenCompany(account.nif as string)}>
            <ExternalLink size={13} /> Abrir no EmpresasIQ
          </Button>
        )}
        {account?.nif && (
          <Button onClick={sync} title="Atualizar o resumo de contratos do EmpresasIQ">
            <RefreshCw size={13} /> Sincronizar
          </Button>
        )}
        {account && onEdit && (
          <Button onClick={() => onEdit(account)}>
            <Pencil size={13} /> Editar
          </Button>
        )}
      </div>
      {loading && (
        <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> A carregar a ficha…
        </p>
      )}
      {error && <p className="text-[12.5px] text-rose-300">{error}</p>}
      {!loading && timeline && account && (
        <>
          <div className="grid grid-cols-2 gap-2 @lg:grid-cols-4">
            <KpiCard label="Pipeline aberto" value={formatCurrency(openValue)} icon={TrendingUp} />
            <KpiCard label="Oportunidades" value={String(deals.length)} icon={Target} tone="indigo" />
            <KpiCard label="Contactos" value={String(timeline.contacts.length)} icon={Users} tone="sky" />
            <KpiCard
              label="Atividades abertas"
              value={String(timeline.activities.filter((activity) => !activity.done).length)}
              icon={CalendarClock}
              tone="amber"
            />
          </div>

          {snapshot && (
            <section className="glass-card rounded-xl p-3">
              <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                EmpresasIQ · contratação pública
              </h3>
              <div className="mt-2 grid grid-cols-2 gap-2 @lg:grid-cols-4">
                <div>
                  <p className="text-[11px] text-muted-foreground">Contratos</p>
                  <p className="stat-value text-[15px] text-foreground">{snapshot.contracts_count ?? "—"}</p>
                </div>
                <div>
                  <p className="text-[11px] text-muted-foreground">Valor adjudicatário</p>
                  <p className="stat-value text-[15px] text-foreground">{formatCompact(snapshot.total_value)} €</p>
                </div>
                <div>
                  <p className="text-[11px] text-muted-foreground">Valor adjudicante</p>
                  <p className="stat-value text-[15px] text-foreground">{formatCompact(snapshot.as_adjudicante_value)} €</p>
                </div>
                <div>
                  <p className="text-[11px] text-muted-foreground">Sincronizado</p>
                  <p className="text-[12px] text-muted-foreground">{formatDate(snapshot.synced_at)}</p>
                </div>
              </div>
            </section>
          )}

          {account.notes && (
            <section className="glass-card rounded-xl p-3">
              <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Notas</h3>
              <p className="mt-1 whitespace-pre-wrap text-[12.5px] text-foreground">{account.notes}</p>
            </section>
          )}

          <section className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
            <div className="glass-card rounded-xl p-3">
              <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Contactos</h3>
              <ul className="mt-2 flex flex-col gap-2">
                {timeline.contacts.map((contact) => (
                  <li key={contact.id} className="rounded-lg border border-white/5 px-2.5 py-2">
                    <p className="flex items-center gap-1.5 text-[12.5px] text-foreground">
                      {contact.name}
                      {contact.is_primary && <Badge className="bg-teal-400/15 text-teal-200">principal</Badge>}
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {[contact.title, contact.email, contact.phone || contact.mobile].filter(Boolean).join(" · ") || "—"}
                    </p>
                  </li>
                ))}
                {timeline.contacts.length === 0 && <li className="text-[11.5px] text-muted-foreground">Sem contactos.</li>}
              </ul>
            </div>

            <div className="glass-card rounded-xl p-3">
              <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Oportunidades</h3>
              <ul className="mt-2 flex flex-col gap-2">
                {deals.map((deal) => (
                  <li key={deal.id} className="rounded-lg border border-white/5 px-2.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-[12.5px] text-foreground">{deal.title}</p>
                      <span className={`shrink-0 text-[11px] ${STAGE_META[deal.stage]?.text ?? ""}`}>
                        {STAGE_META[deal.stage]?.label ?? deal.stage}
                      </span>
                    </div>
                    <p className="stat-value text-[11px] text-muted-foreground">
                      {formatCurrency(deal.amount, deal.currency)} · {deal.probability ?? 0}% ·{" "}
                      {formatDate(deal.expected_close_date)}
                    </p>
                  </li>
                ))}
                {deals.length === 0 && <li className="text-[11.5px] text-muted-foreground">Sem oportunidades.</li>}
              </ul>
            </div>
          </section>

          <section className="glass-card rounded-xl p-3">
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Atividades</h3>
            <ul className="mt-2 flex flex-col divide-y divide-white/5">
              {timeline.activities.map((activity) => {
                const Icon = ACTIVITY_META[activity.type]?.icon ?? NotebookPen;
                return (
                  <li key={activity.id} className="flex items-center gap-2 py-1.5">
                    <Icon size={13} className="shrink-0 text-muted-foreground" />
                    <span className={`min-w-0 flex-1 truncate text-[12.5px] ${activity.done ? "text-muted-foreground line-through" : "text-foreground"}`}>
                      {activity.subject}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">{relativeDay(activity.due_at)}</span>
                  </li>
                );
              })}
              {timeline.activities.length === 0 && <li className="text-[11.5px] text-muted-foreground">Sem atividades.</li>}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

/** Dossier em modal (modo página: gestor de janelas desligado). */
function AccountModal({
  account,
  openStages,
  onClose,
  onEdit,
  onOpenCompany,
  onChanged,
}: {
  account: CrmAccount;
  openStages: CrmDealStage[];
  onClose: () => void;
  onEdit: (account: CrmAccount) => void;
  onOpenCompany?: (nif: string) => void;
  onChanged: () => void;
}) {
  return (
    <Modal
      title={account.name}
      subtitle={[account.nif ? `NIF ${account.nif}` : null, account.sector, account.city].filter(Boolean).join(" · ") || undefined}
      onClose={onClose}
      wide
      footer={<Button onClick={onClose}>Fechar</Button>}
    >
      <AccountDossier
        accountId={account.id}
        openStages={openStages}
        onEdit={onEdit}
        onOpenCompany={onOpenCompany}
        onChanged={onChanged}
      />
    </Modal>
  );
}

/** Janela «Conta» do gestor de janelas (`crm-account:<id>`). */
export function CrmAccountWindow({
  id,
  onOpenCompany,
  onEdit,
}: {
  id: string;
  onOpenCompany?: (nif: string) => void;
  onEdit?: (account: CrmAccount) => void;
}) {
  const [meta, setMeta] = useState<CrmMeta | null>(null);
  useEffect(() => {
    getCrmMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);
  return (
    <div className="@container h-full overflow-y-auto bg-background p-4 text-foreground">
      <AccountDossier accountId={id} openStages={meta?.open_stages} onOpenCompany={onOpenCompany} onEdit={onEdit} />
    </div>
  );
}

/* ---------------------------------------------------------------- contactos */

function ContactsPanel({
  contacts,
  accounts,
  onEdit,
  onCreate,
}: {
  contacts: CrmContact[];
  accounts: CrmAccount[];
  onEdit: (contact: CrmContact) => void;
  onCreate: () => void;
}) {
  const [query, setQuery] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const accountName = useMemo(() => new Map(accounts.map((account) => [account.id, account.name])), [accounts]);

  const normalized = query.trim().toLowerCase();
  const rows = contacts.filter((contact) => {
    if (accountFilter && contact.account_id !== accountFilter) return false;
    if (!normalized) return true;
    return [contact.name, contact.title, contact.email, contact.phone, contact.mobile]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalized));
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            className={`${INPUT_CLASS} pl-8`}
            placeholder="Pesquisar contactos (nome, cargo, email…)"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <select className={`${INPUT_CLASS} w-[210px]`} value={accountFilter} onChange={(event) => setAccountFilter(event.target.value)}>
          <option value="">Todas as contas</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>{account.name}</option>
          ))}
        </select>
        <Button variant="primary" onClick={onCreate}>
          <Plus size={13} /> Novo contacto
        </Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon={Users} title="Sem contactos" hint="Registe as pessoas de contacto das suas contas." />
      ) : (
        <div className="glass-card overflow-x-auto rounded-xl">
          <table className="w-full min-w-[680px] text-left text-[12.5px]">
            <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-white/8">
                <th className="px-3 py-2 font-medium">Contacto</th>
                <th className="px-3 py-2 font-medium">Conta</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Telefone</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((contact) => (
                <tr key={contact.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.03]">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5 font-medium text-foreground">
                      {contact.name}
                      {contact.is_primary && <Badge className="bg-teal-400/15 text-teal-200">principal</Badge>}
                    </span>
                    <span className="block text-[11px] text-muted-foreground">{contact.title || contact.role || "—"}</span>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {accountName.get(contact.account_id ?? "") ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {contact.email ? (
                      <a href={`mailto:${contact.email}`} className="text-sky-300 hover:underline">{contact.email}</a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="stat-value px-3 py-2 text-muted-foreground">{contact.phone || contact.mobile || "—"}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => onEdit(contact)}
                      className="rounded-md p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
                      title="Editar contacto"
                    >
                      <Pencil size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ agenda */

const BUCKETS: { id: Bucket; label: string; tone: string }[] = [
  { id: "overdue", label: "Em atraso", tone: "text-rose-300" },
  { id: "today", label: "Hoje", tone: "text-teal-300" },
  { id: "week", label: "Próximos 7 dias", tone: "text-sky-300" },
  { id: "later", label: "Mais tarde", tone: "text-muted-foreground" },
  { id: "none", label: "Sem data", tone: "text-muted-foreground" },
];

function ActivityRow({
  activity,
  accounts,
  onToggle,
  onEdit,
}: {
  activity: CrmActivity;
  accounts: CrmAccount[];
  onToggle: (activity: CrmActivity) => void;
  onEdit: (activity: CrmActivity) => void;
}) {
  const Icon = ACTIVITY_META[activity.type]?.icon ?? NotebookPen;
  const priority = PRIORITY_META[activity.priority ?? "media"] ?? PRIORITY_META.media;
  const account = accounts.find((item) => item.id === activity.account_id);
  const bucket = bucketOf(activity.due_at);

  return (
    <li className="flex items-center gap-2.5 rounded-lg border border-white/5 px-2.5 py-2 transition hover:border-white/10">
      <button
        type="button"
        onClick={() => onToggle(activity)}
        title={activity.done ? "Marcar como não concluída" : "Marcar como concluída"}
        className={[
          "grid h-5 w-5 shrink-0 place-items-center rounded-full border transition",
          activity.done
            ? "border-teal-400/60 bg-teal-500/25 text-teal-100"
            : "border-white/20 text-transparent hover:border-teal-400/50",
        ].join(" ")}
      >
        <Check size={11} />
      </button>
      <Icon size={14} className="shrink-0 text-muted-foreground" />
      <button type="button" onClick={() => onEdit(activity)} className="min-w-0 flex-1 text-left">
        <span className={`block truncate text-[12.5px] ${activity.done ? "text-muted-foreground line-through" : "text-foreground"}`}>
          {activity.subject}
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">
          {[account?.name, ACTIVITY_META[activity.type]?.label].filter(Boolean).join(" · ") || "—"}
        </span>
      </button>
      {!activity.done && (activity.priority === "alta" || bucket === "overdue") && (
        <Badge className={bucket === "overdue" ? "bg-rose-400/15 text-rose-200" : priority.className}>
          {bucket === "overdue" ? relativeDay(activity.due_at) : priority.label}
        </Badge>
      )}
      <span className="stat-value hidden shrink-0 text-[11px] text-muted-foreground @lg:block">
        {activity.done ? `Concluída · ${formatDate(activity.done_at)}` : relativeDay(activity.due_at)}
      </span>
    </li>
  );
}

function AgendaPanel({
  activities,
  accounts,
  onEdit,
  onCreate,
  onToggle,
}: {
  activities: CrmActivity[];
  accounts: CrmAccount[];
  onEdit: (activity: CrmActivity) => void;
  onCreate: () => void;
  onToggle: (activity: CrmActivity) => void;
}) {
  const [showDone, setShowDone] = useState(false);
  const [query, setQuery] = useState("");

  const normalized = query.trim().toLowerCase();
  const filtered = activities.filter((activity) => {
    if (!showDone && activity.done) return false;
    if (!normalized) return true;
    const account = accounts.find((item) => item.id === activity.account_id);
    return [activity.subject, activity.notes, account?.name]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalized));
  });

  const open = filtered.filter((activity) => !activity.done);
  const done = filtered.filter((activity) => activity.done);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            className={`${INPUT_CLASS} pl-8`}
            placeholder="Pesquisar atividades…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Button onClick={() => setShowDone((value) => !value)}>
          <CheckCircle2 size={13} /> {showDone ? "Ocultar concluídas" : `Concluídas (${activities.filter((item) => item.done).length})`}
        </Button>
        <Button variant="primary" onClick={onCreate}>
          <Plus size={13} /> Nova atividade
        </Button>
      </div>

      {open.length === 0 && done.length === 0 ? (
        <EmptyState icon={CalendarClock} title="Agenda vazia" hint="Crie chamadas, reuniões e tarefas para não perder prazos." />
      ) : (
        <div className="flex flex-col gap-3">
          {BUCKETS.map((bucket) => {
            const items = open.filter((activity) => bucketOf(activity.due_at) === bucket.id);
            if (items.length === 0) return null;
            return (
              <section key={bucket.id} className="glass-card rounded-xl p-3">
                <header className="flex items-center justify-between gap-2">
                  <h3 className={`text-[12px] font-semibold uppercase tracking-wide ${bucket.tone}`}>{bucket.label}</h3>
                  <span className="text-[11px] text-muted-foreground">{items.length}</span>
                </header>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {items.map((activity) => (
                    <ActivityRow
                      key={activity.id}
                      activity={activity}
                      accounts={accounts}
                      onToggle={onToggle}
                      onEdit={onEdit}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
          {showDone && done.length > 0 && (
            <section className="glass-card rounded-xl p-3">
              <header className="flex items-center justify-between gap-2">
                <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Concluídas</h3>
                <span className="text-[11px] text-muted-foreground">{done.length}</span>
              </header>
              <ul className="mt-2 flex flex-col gap-1.5">
                {done.map((activity) => (
                  <ActivityRow
                    key={activity.id}
                    activity={activity}
                    accounts={accounts}
                    onToggle={onToggle}
                    onEdit={onEdit}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- dashboard */

function DashboardPanel({
  overview,
  accounts,
  onEditActivity,
}: {
  overview: CrmOverview | null;
  accounts: CrmAccount[];
  onEditActivity: (activity: CrmActivity) => void;
}) {
  if (!overview) {
    return (
      <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> A calcular indicadores…
      </p>
    );
  }

  const maxStage = Math.max(1, ...overview.by_stage.map((stage) => stage.value));
  const maxForecast = Math.max(1, ...overview.forecast.map((month) => month.value));
  const accountName = new Map(accounts.map((account) => [account.id, account.name]));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 @lg:grid-cols-3 @3xl:grid-cols-5">
        <KpiCard label="Pipeline aberto" value={formatCurrency(overview.pipeline.open_value)} hint={`${overview.totals.deals_open} oportunidades`} icon={TrendingUp} />
        <KpiCard label="Previsão ponderada" value={formatCurrency(overview.pipeline.weighted_value)} hint="valor × probabilidade" icon={Target} tone="indigo" />
        <KpiCard label="Ticket médio" value={formatCurrency(overview.pipeline.average_deal)} icon={FileText} tone="sky" />
        <KpiCard label="Taxa de conversão" value={`${overview.pipeline.win_rate.toFixed(1)}%`} hint={`${overview.totals.deals_won} ganhas · ${overview.totals.deals_lost} perdidas`} icon={CheckCircle2} tone="amber" />
        <KpiCard label="Ganho (12 meses)" value={formatCurrency(overview.pipeline.won_value_12m)} icon={Building2} />
      </div>

      <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
        <section className="glass-card rounded-xl p-3">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Pipeline por fase</h3>
          <ul className="mt-3 flex flex-col gap-2.5">
            {overview.by_stage.map((stage) => {
              const info = STAGE_META[stage.stage] ?? { label: stage.stage, bar: "bg-white/30", text: "text-foreground" };
              return (
                <li key={stage.stage}>
                  <div className="flex items-center justify-between gap-2 text-[12px]">
                    <span className={info.text}>{info.label}</span>
                    <span className="stat-value text-muted-foreground">
                      {stage.count} · {formatCurrency(stage.value)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                    <div className={`h-full rounded-full ${info.bar}`} style={{ width: `${Math.round((stage.value / maxStage) * 100)}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="glass-card rounded-xl p-3">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Previsão de fecho</h3>
          {overview.forecast.length === 0 ? (
            <p className="mt-2 text-[11.5px] text-muted-foreground">
              Sem datas de fecho previstas nas oportunidades abertas.
            </p>
          ) : (
            <ul className="mt-3 flex items-end gap-2 overflow-x-auto">
              {overview.forecast.map((month) => (
                <li key={month.month} className="flex min-w-[46px] flex-1 flex-col items-center gap-1">
                  <span className="stat-value text-[10.5px] text-muted-foreground">{formatCompact(month.value)}</span>
                  <div
                    className="w-full rounded-t bg-gradient-to-t from-teal-500/40 to-teal-300/80"
                    style={{ height: `${Math.max(6, Math.round((month.value / maxForecast) * 110))}px` }}
                    title={`${month.count} oportunidades · ${formatCurrency(month.value)} · ponderado ${formatCurrency(month.weighted)}`}
                  />
                  <span className="text-[10.5px] text-muted-foreground">{formatMonth(month.month)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="glass-card rounded-xl p-3">
          <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Maiores contas em pipeline</h3>
          {overview.top_accounts.length === 0 ? (
            <p className="mt-2 text-[11.5px] text-muted-foreground">Sem oportunidades abertas.</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {overview.top_accounts.map((account) => (
                <li key={account.account_id} className="flex items-center justify-between gap-2 text-[12.5px]">
                  <span className="min-w-0 truncate text-foreground">{accountName.get(account.account_id) ?? account.name}</span>
                  <span className="stat-value shrink-0 text-teal-300">{formatCurrency(account.value)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="glass-card rounded-xl p-3">
          <h3 className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
            Agenda
            {overview.agenda.overdue_count > 0 && (
              <Badge className="bg-rose-400/15 text-rose-200">{overview.agenda.overdue_count} em atraso</Badge>
            )}
          </h3>
          <ul className="mt-3 flex flex-col gap-1.5">
            {overview.agenda.next_7_days.map((activity) => (
              <li key={activity.id} className="flex items-center gap-2 text-[12.5px]">
                <CalendarClock size={13} className="shrink-0 text-muted-foreground" />
                <button type="button" onClick={() => onEditActivity(activity)} className="min-w-0 flex-1 truncate text-left text-foreground hover:underline">
                  {activity.subject}
                </button>
                <span className="shrink-0 text-[11px] text-muted-foreground">{relativeDay(activity.due_at)}</span>
              </li>
            ))}
            {overview.agenda.next_7_days.length === 0 && (
              <li className="text-[11.5px] text-muted-foreground">Sem compromissos nos próximos 7 dias.</li>
            )}
          </ul>
          {overview.agenda.overdue.length > 0 && (
            <>
              <h4 className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-rose-300">Em atraso</h4>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {overview.agenda.overdue.map((activity) => (
                  <li key={activity.id} className="flex items-center gap-2 text-[12.5px]">
                    <AlertTriangle size={13} className="shrink-0 text-rose-300" />
                    <button type="button" onClick={() => onEditActivity(activity)} className="min-w-0 flex-1 truncate text-left text-foreground hover:underline">
                      {activity.subject}
                    </button>
                    <span className="shrink-0 text-[11px] text-rose-200">{relativeDay(activity.due_at)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      <section className="glass-card rounded-xl p-3">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Movimentos recentes</h3>
        {overview.recent_activity.length === 0 ? (
          <p className="mt-2 text-[11.5px] text-muted-foreground">Ainda sem registos.</p>
        ) : (
          <ul className="mt-2 flex flex-col divide-y divide-white/5">
            {overview.recent_activity.map((record) => {
              const item = record as Record<string, unknown>;
              const kind = String(item.kind ?? "");
              const label = String(item.name ?? item.title ?? item.subject ?? "Registo");
              const kindLabel = kind === "account" ? "Conta" : kind === "contact" ? "Contacto" : kind === "deal" ? "Oportunidade" : "Atividade";
              return (
                <li key={`${kind}-${String(item.id)}`} className="flex items-center justify-between gap-3 py-1.5 text-[12.5px]">
                  <span className="min-w-0 truncate text-foreground">{label}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge className="bg-white/8 text-muted-foreground">{kindLabel}</Badge>
                    <span className="text-[11px] text-muted-foreground">{formatDate(String(item.updated_at ?? ""))}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------------- página */

export type CrmSection = "pipeline" | "accounts" | "contacts" | "agenda" | "dashboard";

/** Secções do CRM (separadores na barra de topo de cada janela). */
export const CRM_SECTIONS: { id: CrmSection; label: string; icon: LucideIcon }[] = [
  { id: "pipeline", label: "Pipeline", icon: Columns3 },
  { id: "accounts", label: "Contas", icon: Building2 },
  { id: "contacts", label: "Contactos", icon: Users },
  { id: "agenda", label: "Agenda", icon: CalendarClock },
  { id: "dashboard", label: "Relatórios", icon: LayoutDashboard },
];

/** Aplicação/janela correspondente a cada secção do CRM. */
export const CRM_SECTION_VIEWS: Record<CrmSection, string> = {
  pipeline: "crm",
  accounts: "crm-accounts",
  contacts: "crm-contacts",
  agenda: "crm-agenda",
  dashboard: "crm-dashboard",
};

const VIEW_SECTIONS: Record<string, CrmSection> = {
  crm: "pipeline",
  "crm-accounts": "accounts",
  "crm-contacts": "contacts",
  "crm-agenda": "agenda",
  "crm-dashboard": "dashboard",
};

/** Secção do CRM correspondente a uma vista (ou `null` se a vista não for do CRM). */
export function crmSectionForView(view: string): CrmSection | null {
  return VIEW_SECTIONS[view] ?? null;
}

/** Título da janela de uma secção do CRM. */
export function crmSectionTitle(section: CrmSection) {
  if (section === "pipeline") return "CRM";
  const label = CRM_SECTIONS.find((item) => item.id === section)?.label ?? "CRM";
  return `CRM · ${label}`;
}

/** Fases abertas, usadas quando o `meta` ainda não chegou. */
const FALLBACK_OPEN_STAGES: CrmDealStage[] = ["prospeccao", "qualificacao", "proposta", "negociacao"];

/** Evento interno: uma janela alterou dados do CRM e as outras devem recarregar. */
const CRM_CHANGED = "finance-llm-crm-changed";

function notifyCrmChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CRM_CHANGED));
}

/**
 * Dados do CRM. Cada janela do módulo tem a sua cópia e sincroniza-se com as
 * restantes através de `finance-llm-crm-changed`.
 */
function useCrmData() {
  const [meta, setMeta] = useState<CrmMeta | null>(null);
  const [overview, setOverview] = useState<CrmOverview | null>(null);
  const [accounts, setAccounts] = useState<CrmAccount[]>([]);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [deals, setDeals] = useState<CrmDeal[]>([]);
  const [activities, setActivities] = useState<CrmActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [metaResult, overviewResult, accountsResult, contactsResult, dealsResult, activitiesResult] = await Promise.all([
        getCrmMeta(),
        getCrmOverview(6),
        listCrmAccounts({ size: 400 }),
        listCrmContacts({ size: 400 }),
        listCrmDeals({ size: 500 }),
        listCrmActivities({ size: 500 }),
      ]);
      setMeta(metaResult);
      setOverview(overviewResult);
      setAccounts(accountsResult.items ?? []);
      setContacts(contactsResult.items ?? []);
      setDeals(dealsResult.items ?? []);
      setActivities(activitiesResult.items ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar o CRM");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* Outra janela do CRM alterou dados: recarrega para manter as vistas iguais. */
  useEffect(() => {
    const onChange = () => void reload();
    window.addEventListener(CRM_CHANGED, onChange);
    return () => window.removeEventListener(CRM_CHANGED, onChange);
  }, [reload]);

  return {
    meta,
    overview,
    accounts,
    contacts,
    deals,
    activities,
    loading,
    error,
    setError,
    setDeals,
    setActivities,
    reload,
  };
}

export default function CrmPage({
  section: sectionProp,
  onSectionChange,
  onOpenAccount,
  onEditRecord,
  onOpenCompany,
}: {
  /** Secção apresentada (no modo janelas vem da vista aberta). */
  section?: CrmSection;
  /** Definido no modo janelas: mudar de separador abre a janela dessa secção. */
  onSectionChange?: (section: CrmSection) => void;
  /** Definido no modo janelas: abrir uma conta abre uma janela própria. */
  onOpenAccount?: (account: CrmAccount) => void;
  /** Definido no modo janelas: editar/criar abre uma janela própria. */
  onEditRecord?: (kind: CrmKind, record: CrmRecord | null, defaults?: Draft) => void;
  onOpenCompany?: (nif: string) => void;
}) {
  const {
    meta,
    overview,
    accounts,
    contacts,
    deals,
    activities,
    loading,
    error,
    setError,
    setDeals,
    setActivities,
    reload,
  } = useCrmData();
  const [localSection, setLocalSection] = useState<CrmSection>("pipeline");
  const section = sectionProp ?? localSection;
  const [editor, setEditor] = useState<{
    kind: CrmKind;
    record?: CrmAccount | CrmContact | CrmDeal | CrmActivity | null;
    defaults?: Draft;
  } | null>(null);
  const [detail, setDetail] = useState<CrmAccount | null>(null);

  /** Abre a secção: em janelas abre/foca a janela respetiva, senão troca no local. */
  const changeSection = (next: CrmSection) => {
    if (onSectionChange) onSectionChange(next);
    else setLocalSection(next);
  };

  /** Editor: janela própria no modo janelas, modal no modo página. */
  const openEditor = (kind: CrmKind, record: CrmRecord | null, defaults?: Draft) => {
    if (onEditRecord) onEditRecord(kind, record, defaults);
    else setEditor({ kind, record, defaults });
  };

  /** Ficha da conta: janela própria no modo janelas, modal no modo página. */
  const openAccount = (account: CrmAccount) => {
    if (onOpenAccount) onOpenAccount(account);
    else setDetail(account);
  };

  const closeEditor = () => setEditor(null);
  const saved = useCallback(() => {
    setEditor(null);
    setDetail(null);
    void reload();
  }, [reload]);

  const moveDeal = useCallback(
    async (deal: CrmDeal, stage: CrmDealStage) => {
      // Atualização otimista: o cartão muda de coluna de imediato.
      setDeals((prev) => prev.map((item) => (item.id === deal.id ? { ...item, stage } : item)));
      try {
        await updateCrmRecord("deals", deal.id, { stage });
        notifyCrmChanged();
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Não foi possível mover a oportunidade");
        await reload();
      }
    },
    [reload, setDeals, setError],
  );

  const toggleActivity = useCallback(
    async (activity: CrmActivity) => {
      const done = !activity.done;
      setActivities((prev) => prev.map((item) => (item.id === activity.id ? { ...item, done } : item)));
      try {
        await updateCrmRecord("activities", activity.id, { done });
        notifyCrmChanged();
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Não foi possível atualizar a atividade");
        await reload();
      }
    },
    [reload, setActivities, setError],
  );

  const openDealCount = deals.filter((deal) => (meta?.open_stages ?? FALLBACK_OPEN_STAGES).includes(deal.stage)).length;

  if (loading) {
    return (
      <div className="grid min-h-[320px] place-items-center">
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar o CRM…
        </p>
      </div>
    );
  }

  return (
    <div className="@container flex h-full min-h-[520px] flex-col bg-background text-foreground">
      <header className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 py-2 backdrop-blur-xl md:top-0">
        <div className="flex flex-wrap items-center gap-2 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-teal-400 to-blue-500 text-white">
            <Target size={15} />
          </span>
          <h1 className="text-[14px] font-semibold">CRM</h1>
          {meta?.scope === "all" && (
            <Badge className="bg-indigo-400/15 text-indigo-200" >vista de equipa</Badge>
          )}
          <div className="min-w-0 flex-1" />
          <div className="dock-scroll flex items-center gap-1 overflow-x-auto rounded-[8px] border border-white/8 bg-white/[0.05] p-0.5">
            {CRM_SECTIONS.map((item) => {
              const Icon = item.icon;
              const active = section === item.id;
              const badge =
                item.id === "pipeline" ? openDealCount : item.id === "agenda" ? activities.filter((a) => !a.done).length : 0;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => changeSection(item.id)}
                  className={[
                    "flex shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 py-1 text-[12px] transition",
                    active
                      ? "bg-white/[0.16] font-medium text-foreground shadow-sm"
                      : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
                  ].join(" ")}
                >
                  <Icon size={13} className={active ? "text-teal-300" : undefined} />
                  <span className="whitespace-nowrap">{item.label}</span>
                  {badge > 0 && (
                    <span className="rounded-full bg-white/10 px-1.5 text-[10px] font-medium text-muted-foreground">{badge}</span>
                  )}
                </button>
              );
            })}
          </div>
          <Button onClick={() => void reload()} title="Recarregar">
            <RefreshCw size={13} /> Actualizar
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {meta && section === "pipeline" && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-3 @lg:grid-cols-4">
              <KpiCard label="Pipeline aberto" value={formatCurrency(overview?.pipeline.open_value ?? 0)} icon={TrendingUp} />
              <KpiCard label="Ponderado" value={formatCurrency(overview?.pipeline.weighted_value ?? 0)} icon={Target} tone="indigo" />
              <KpiCard label="Oportunidades abertas" value={String(openDealCount)} icon={Columns3} tone="sky" />
              <KpiCard label="Ganhas" value={String(overview?.totals.deals_won ?? 0)} icon={CheckCircle2} tone="amber" />
            </div>
            <PipelineBoard
              deals={deals}
              accounts={accounts}
              meta={meta}
              onEdit={(deal) => openEditor("deals", deal)}
              onCreate={(stage) => openEditor("deals", null, { stage })}
              onMove={(deal, stage) => void moveDeal(deal, stage)}
            />
          </>
        )}

        {meta && section === "accounts" && (
          <AccountsPanel
            accounts={accounts}
            deals={deals}
            contacts={contacts}
            meta={meta}
            onEdit={(account) => openEditor("accounts", account)}
            onOpen={(account) => openAccount(account)}
            onCreate={() => openEditor("accounts", null)}
            onLinked={() => void reload()}
          />
        )}

        {meta && section === "contacts" && (
          <ContactsPanel
            contacts={contacts}
            accounts={accounts}
            onEdit={(contact) => openEditor("contacts", contact)}
            onCreate={() => openEditor("contacts", null)}
          />
        )}

        {meta && section === "agenda" && (
          <AgendaPanel
            activities={activities}
            accounts={accounts}
            onEdit={(activity) => openEditor("activities", activity)}
            onCreate={() => openEditor("activities", null)}
            onToggle={(activity) => void toggleActivity(activity)}
          />
        )}

        {meta && section === "dashboard" && (
          <DashboardPanel
            overview={overview}
            accounts={accounts}
            onEditActivity={(activity) => openEditor("activities", activity)}
          />
        )}

        {!meta && !error && (
          <EmptyState icon={Target} title="CRM indisponível" hint="Não foi possível obter a configuração do módulo." />
        )}
      </div>

      {meta && editor && (
        <EditorModal
          kind={editor.kind}
          record={editor.record ?? null}
          defaults={editor.defaults}
          meta={meta}
          accounts={accounts}
          contacts={contacts}
          deals={deals}
          onClose={closeEditor}
          onSaved={saved}
        />
      )}

      {meta && detail && (
        <AccountModal
          account={detail}
          openStages={meta.open_stages}
          onClose={() => setDetail(null)}
          onEdit={(account) => {
            setDetail(null);
            openEditor("accounts", account);
          }}
          onOpenCompany={(nif) => {
            setDetail(null);
            onOpenCompany?.(nif);
          }}
          onChanged={() => void reload()}
        />
      )}
    </div>
  );
}

/**
 * Janela de um registo do CRM (`crm-edit:<kind>:<id|new>`).
 *
 * Usada no modo janelas: o formulário abre numa janela própria em vez de um
 * modal, para se poder trabalhar em vários registos ao mesmo tempo.
 */
export function CrmRecordWindow({
  kind,
  id,
  defaults,
  onClose,
  onSaved,
}: {
  kind: CrmKind;
  id: string;
  /** Valores iniciais (ex.: a fase da coluna onde se clicou «+»). */
  defaults?: Draft;
  onClose?: () => void;
  onSaved?: () => void;
}) {
  const { meta, accounts, contacts, deals, activities, loading } = useCrmData();

  const record = useMemo<CrmRecord | null>(() => {
    if (id === "new") return null;
    const list: CrmRecord[] =
      kind === "accounts" ? accounts : kind === "contacts" ? contacts : kind === "deals" ? deals : activities;
    return list.find((item) => item.id === id) ?? null;
  }, [kind, id, accounts, contacts, deals, activities]);

  const handleSaved = useCallback(() => {
    notifyCrmChanged();
    onSaved?.();
  }, [onSaved]);

  return (
    <div className="@container h-full overflow-y-auto bg-background p-4 text-foreground">
      {loading && !meta && (
        <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> A carregar…
        </p>
      )}
      {!loading && meta && id !== "new" && !record && (
        <EmptyState
          icon={FileText}
          title="Registo não encontrado"
          hint="Foi apagado noutra janela ou pertence a outro utilizador."
        />
      )}
      {meta && (id === "new" || record) && (
        <div className="glass-card rounded-xl p-4">
          <RecordEditor
            kind={kind}
            record={record}
            defaults={defaults}
            meta={meta}
            accounts={accounts}
            contacts={contacts}
            deals={deals}
            onClose={() => onClose?.()}
            onSaved={handleSaved}
          />
        </div>
      )}
    </div>
  );
}
