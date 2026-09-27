/**
 * Peças do leitor de RSS: campos, gavetas, cartões e tons de estado.
 *
 * Segue o mesmo desenho dos kits do CMS e da Loja (campos pequenos, cartões
 * translúcidos, gaveta lateral) para o leitor não parecer um corpo estranho
 * dentro da plataforma.
 */
import { useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, X } from "lucide-react";

export const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/60 focus:border-teal-300/40 focus:bg-white/[0.07]";
export const areaClass = `${inputClass} resize-y font-normal leading-relaxed`;
export const cardClass = "rounded-xl border border-white/8 bg-white/[0.03] p-3";
export const labelClass = "text-[11.5px] font-medium text-muted-foreground";

/** Alvo tátil mínimo em telemóvel (44 px) sem inflacionar o desktop. */
export const tap = "min-h-[44px] sm:min-h-[34px]";
/** Anel de foco visível, como no resto da plataforma. */
export const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50";

/** Botão da plataforma: variantes de cor, alvo tátil e foco visível. */
export function Btn({
  children,
  onClick,
  variant = "soft",
  disabled = false,
  title,
  ariaLabel,
  className = "",
  type = "button",
  wide = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "soft" | "ghost" | "danger" | "ai";
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  className?: string;
  type?: "button" | "submit";
  wide?: boolean;
}) {
  const variants: Record<string, string> = {
    primary: "border-teal-300/40 bg-teal-500/15 text-teal-100 hover:bg-teal-500/25 font-medium",
    soft: "border-white/10 bg-white/[0.05] text-muted-foreground hover:bg-white/[0.1] hover:text-foreground",
    ghost: "border-transparent bg-transparent text-muted-foreground hover:bg-white/[0.08] hover:text-foreground",
    danger: "border-rose-400/25 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20",
    ai: "border-violet-400/30 bg-violet-500/10 text-violet-100 hover:bg-violet-500/20",
  };
  return (
    <button
      type={type}
      title={title}
      aria-label={ariaLabel ?? title}
      disabled={disabled}
      onClick={onClick}
      className={[
        "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border px-2.5 text-[12px] transition disabled:opacity-50",
        tap,
        focusRing,
        wide ? "w-full" : "",
        variants[variant] ?? variants.soft,
        className,
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/** Tons de estado (os mesmos nomes que o backend devolve em `status_tone`/`color`). */
export const TONE_CLASS: Record<string, string> = {
  teal: "border-teal-400/30 bg-teal-400/10 text-teal-100",
  emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  sky: "border-sky-400/30 bg-sky-400/10 text-sky-100",
  violet: "border-violet-400/30 bg-violet-400/10 text-violet-100",
  indigo: "border-indigo-400/30 bg-indigo-400/10 text-indigo-100",
  amber: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  rose: "border-rose-400/30 bg-rose-400/10 text-rose-100",
  slate: "border-white/12 bg-white/[0.06] text-slate-300",
};

/* ------------------------------------------------------------------ campos */

export function Field({ label, hint, children, wide = false }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={["flex flex-col gap-1", wide ? "sm:col-span-2" : ""].join(" ")}>
      <span className={labelClass}>{label}</span>
      {children}
      {hint && <span className="text-[10.5px] text-muted-foreground/70">{hint}</span>}
    </label>
  );
}

export function TextInput({
  label,
  value,
  onChange,
  placeholder,
  wide,
  hint,
  onEnter,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  wide?: boolean;
  hint?: string;
  onEnter?: () => void;
  autoFocus?: boolean;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      <input
        className={inputClass}
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && onEnter) {
            event.preventDefault();
            onEnter();
          }
        }}
      />
    </Field>
  );
}

export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  hint,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="number"
        className={inputClass}
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  rows = 6,
  placeholder,
  wide = true,
  mono = false,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  rows?: number;
  placeholder?: string;
  wide?: boolean;
  mono?: boolean;
}) {
  return (
    <Field label={label} wide={wide}>
      <textarea
        className={[areaClass, mono ? "font-mono text-[12px]" : ""].join(" ")}
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

export function SelectInput({
  label,
  value,
  onChange,
  options,
  wide,
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: { value: string; label: string }[];
  wide?: boolean;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      <select className={inputClass} value={value} onChange={(event) => onChange(event.target.value)}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (next: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2">
      <input type="checkbox" className="mt-0.5 h-3.5 w-3.5 accent-teal-400" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        <span className="text-[12px] text-foreground">{label}</span>
        {hint && <span className="block text-[10.5px] text-muted-foreground/70">{hint}</span>}
      </span>
    </label>
  );
}

export function TagsInput({ label, value, onChange, placeholder = "etiqueta, outra" }: { label: string; value: string[]; onChange: (next: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    if (!parts.length) return;
    onChange([...new Set([...value, ...parts])]);
    setDraft("");
  };
  return (
    <Field label={label}>
      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] p-1.5">
        {value.map((tag) => (
          <span key={tag} className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-foreground">
            {tag}
            <button type="button" onClick={() => onChange(value.filter((item) => item !== tag))} title="Remover">
              <X size={10} />
            </button>
          </span>
        ))}
        <input
          className="min-w-[120px] flex-1 bg-transparent px-1 py-0.5 text-[12px] outline-none placeholder:text-muted-foreground/60"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              add();
            }
          }}
          onBlur={add}
        />
      </div>
    </Field>
  );
}

/** Editor de etiquetas de um artigo (chips + sugestões do catálogo). */
export function TagEditor({
  value,
  onChange,
  suggestions = [],
  hint,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  suggestions?: string[];
  hint?: string;
}) {
  const [draft, setDraft] = useState("");
  const free = suggestions.filter((suggestion) => !value.includes(suggestion)).slice(0, 8);
  const add = (raw: string) => {
    const parts = raw
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    if (!parts.length) return;
    onChange([...new Set([...value, ...parts])].slice(0, 12));
    setDraft("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((tag) => (
        <span key={tag} className="flex items-center gap-1 rounded-full border border-teal-300/30 bg-teal-400/10 px-2 py-1 text-[11.5px] text-teal-100">
          {tag}
          <button type="button" aria-label={`Remover a etiqueta ${tag}`} onClick={() => onChange(value.filter((item) => item !== tag))} className={focusRing}>
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        className="min-w-[120px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[12px] outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
        placeholder={hint ?? "etiquetar…"}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            add(draft);
          }
        }}
        onBlur={() => add(draft)}
      />
      {free.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          onClick={() => add(suggestion)}
          className={`rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground ${focusRing}`}
        >
          + {suggestion}
        </button>
      ))}
    </div>
  );
}

/** Barras compactas para uma série (artigos por dia). */
export function MiniBars({ data, label = "Artigos" }: { data: { day: string; articles: number }[]; label?: string }) {
  const max = Math.max(1, ...data.map((item) => item.articles));
  return (
    <div>
      <div className="flex h-[64px] items-end gap-[3px]">
        {data.map((item) => (
          <span
            key={item.day}
            title={`${item.day}: ${item.articles} ${label.toLowerCase()}`}
            className="flex-1 rounded-t bg-gradient-to-t from-teal-500/40 to-teal-300/80"
            style={{ height: `${Math.max(4, (item.articles / max) * 100)}%` }}
          />
        ))}
      </div>
      <p className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{data[0]?.day?.slice(5)}</span>
        <span>{max} no pico</span>
        <span>{data[data.length - 1]?.day?.slice(5)}</span>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ vários */

export function Chip({ active, onClick, children, title }: { active?: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={[
        "inline-flex items-center rounded-full border px-2.5 text-[11.5px] transition",
        tap,
        focusRing,
        active
          ? "border-teal-300/40 bg-teal-400/15 font-medium text-teal-100"
          : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.08] hover:text-foreground",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

export function StatusPill({ label, tone = "slate" }: { label: string; tone?: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${TONE_CLASS[tone] ?? TONE_CLASS.slate}`}>{label}</span>;
}

export function CountDot({ value, title }: { value: number; title?: string }) {
  if (!value) return null;
  return (
    <span title={title} className="rounded-full bg-teal-400/20 px-1.5 py-0.5 text-[10px] font-medium text-teal-100">
      {value}
    </span>
  );
}

export function StatCard({ label, value, hint, tone = "teal" }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={`rounded-xl border p-3 ${TONE_CLASS[tone] ?? TONE_CLASS.teal}`}>
      <p className="text-[10.5px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-0.5 text-[18px] font-semibold text-foreground">{value}</p>
      {hint && <p className="mt-0.5 text-[10.5px] opacity-80">{hint}</p>}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-white/12 bg-white/[0.02] px-6 py-10 text-center">
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      {hint && <p className="max-w-md text-[12px] text-muted-foreground">{hint}</p>}
      {action}
    </div>
  );
}

export function PanelHeader({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <h2 className="text-[13.5px] font-semibold text-foreground">{title}</h2>
        {hint && <p className="mt-0.5 max-w-3xl text-[11.5px] text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export function ListRow({
  icon,
  title,
  subtitle,
  meta,
  badges,
  actions,
  onClick,
}: {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2 transition hover:border-white/14">
      {icon && <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white/[0.06] text-teal-200">{icon}</span>}
      <button type="button" onClick={onClick} className="min-w-0 flex-1 text-left" disabled={!onClick}>
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[12.5px] font-medium text-foreground">{title}</span>
          {badges}
        </span>
        {subtitle && <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{subtitle}</span>}
      </button>
      {meta && <span className="flex items-center gap-2 text-[11px] text-muted-foreground">{meta}</span>}
      {actions && <span className="flex items-center gap-1">{actions}</span>}
    </div>
  );
}

export function IconAction({ title, onClick, children, danger = false }: { title: string; onClick: () => void; children: ReactNode; danger?: boolean }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={[
        "grid min-h-[44px] min-w-[44px] place-items-center rounded-md border border-white/8 bg-white/[0.04] text-muted-foreground transition hover:bg-white/[0.1] sm:min-h-0 sm:min-w-0 sm:p-1.5",
        focusRing,
        danger ? "hover:text-rose-200" : "hover:text-foreground",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "ok"; children: ReactNode }) {
  const styles: Record<string, string> = {
    info: "border-sky-400/25 bg-sky-500/10 text-sky-200",
    error: "border-rose-400/25 bg-rose-500/10 text-rose-200",
    ok: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200",
  };
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] ${styles[tone]}`}>
      {tone === "error" && <AlertTriangle size={13} className="mt-0.5 shrink-0" />}
      <span className="min-w-0">{children}</span>
    </div>
  );
}

export function Sheet({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
  busy = false,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  busy?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-[130] flex justify-end bg-black/55 backdrop-blur-sm" onClick={onClose}>
      <aside
        className={["flex h-full flex-col border-l border-white/10 bg-[#08181f] shadow-2xl", wide ? "w-full max-w-[min(1080px,96vw)]" : "w-full max-w-[min(560px,96vw)]"].join(" ")}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-white/8 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[14px] font-semibold text-foreground">{title}</h2>
            {subtitle && <p className="truncate text-[11.5px] text-muted-foreground">{subtitle}</p>}
          </div>
          {busy && <Loader2 size={15} className="mt-1 animate-spin text-teal-300" />}
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground" title="Fechar">
            <X size={16} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">{children}</div>
        {footer && (
          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-white/8 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">{footer}</footer>
        )}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------- formatação */

export function timeAgo(value?: string | null): string {
  if (!value) return "—";
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value).slice(0, 16).replace("T", " ");
  const minutes = Math.round((Date.now() - stamp) / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d`;
  return new Date(stamp).toLocaleDateString("pt-PT");
}

/** Tempo que falta até um momento futuro (para a próxima recolha). */
export function timeUntil(value?: string | null): string {
  if (!value) return "—";
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value).slice(0, 16).replace("T", " ");
  const minutes = Math.round((stamp - Date.now()) / 60_000);
  if (minutes <= 0) return "a próxima recolha é já";
  if (minutes < 60) return `próxima em ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `próxima em ${hours} h`;
  return `próxima em ${new Date(stamp).toLocaleDateString("pt-PT")}`;
}

export function fullDate(value?: string | null): string {
  if (!value) return "—";
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value).slice(0, 16).replace("T", " ");
  return new Date(stamp).toLocaleString("pt-PT", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
