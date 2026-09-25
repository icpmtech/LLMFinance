/**
 * Peças da loja online: campos, gaveta de edição, imagens e indicadores.
 *
 * Segue o mesmo vocabulário visual do CMS (`components/cms/CmsKit.tsx`) para que
 * a plataforma pareça uma só aplicação: os mesmos `inputClass`, `Sheet`, listas e
 * distintivos — mas com o que é próprio do comércio (preços em euros, imagens de
 * produto, estrelas de avaliação e mini-gráficos de vendas).
 */
import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Loader2, Plus, Trash2, X } from "lucide-react";

import { shopMediaUrl } from "../../shopApi";

export const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/60 focus:border-teal-300/40 focus:bg-white/[0.07]";
export const areaClass = `${inputClass} resize-y font-normal leading-relaxed`;
export const cardClass = "rounded-xl border border-white/8 bg-white/[0.03] p-3";
export const labelClass = "text-[11.5px] font-medium text-muted-foreground";

export type MediaOption = { id: string; title: string; url: string; kind: string; mime: string; size: number; storage: string };
export type Option = { value: string; label: string };

/** Preço em euros, com o formato português (1 234,56 €). */
export function money(value?: number | null): string {
  const amount = Number.isFinite(Number(value)) ? Number(value) : 0;
  return `${amount.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

export function percent(value?: number | null): string {
  const amount = Number.isFinite(Number(value)) ? Number(value) : 0;
  return `${amount.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}%`;
}

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
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  wide?: boolean;
  hint?: string;
  type?: string;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      <input type={type} className={inputClass} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  hint,
  wide,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  wide?: boolean;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      <input
        type="number"
        className={inputClass}
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
  );
}

/** Campo de dinheiro: mostra o valor em euros e guarda só o número. */
export function MoneyInput({
  label,
  value,
  onChange,
  hint,
  wide,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  hint?: string;
  wide?: boolean;
}) {
  return (
    <Field label={label} hint={hint ?? "Em euros, com IVA incluído quando a loja assim está definida."} wide={wide}>
      <div className="flex items-center gap-2">
        <input
          type="number"
          step="0.01"
          min={0}
          className={inputClass}
          value={Number.isFinite(value) ? value : 0}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <span className="text-[12px] text-muted-foreground">€</span>
      </div>
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
  hint,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  rows?: number;
  placeholder?: string;
  wide?: boolean;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
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
  placeholder,
  hint,
  wide,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: Option[];
  placeholder?: string;
  hint?: string;
  wide?: boolean;
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
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-start gap-2.5 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-2 text-left transition hover:border-white/14"
    >
      <span
        className={[
          "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border transition",
          checked ? "border-teal-300/60 bg-teal-400/25 text-teal-100" : "border-white/20 bg-white/[0.04] text-transparent",
        ].join(" ")}
      >
        <Check size={11} />
      </span>
      <span className="min-w-0">
        <span className="block text-[12.5px] text-foreground">{label}</span>
        {hint && <span className="block text-[10.5px] text-muted-foreground/80">{hint}</span>}
      </span>
    </button>
  );
}

export function TagsInput({ label, value, onChange, placeholder = "etiqueta, outra" }: { label: string; value: string[]; onChange: (next: string[]) => void; placeholder?: string }) {
  return (
    <Field label={label} hint="Separe por vírgulas.">
      <input
        className={inputClass}
        value={value.join(", ")}
        placeholder={placeholder}
        onChange={(event) =>
          onChange(
            event.target.value
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean),
          )
        }
      />
    </Field>
  );
}

/** Lista de caixas de seleção (categorias, produtos ou categorias de cupão). */
export function CheckList({
  label,
  values,
  options,
  onChange,
  hint,
  emptyHint = "Ainda não há nada para escolher aqui.",
  wide = true,
}: {
  label: string;
  values: string[];
  options: Option[];
  onChange: (next: string[]) => void;
  hint?: string;
  emptyHint?: string;
  wide?: boolean;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      {options.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 px-2.5 py-2 text-[11.5px] text-muted-foreground">{emptyHint}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {options.map((option) => {
            const active = values.includes(option.value);
            return (
              <Chip
                key={option.value}
                active={active}
                onClick={() => onChange(active ? values.filter((value) => value !== option.value) : [...values, option.value])}
              >
                {option.label}
              </Chip>
            );
          })}
        </div>
      )}
    </Field>
  );
}

/** Atributos técnicos do produto (formato, prazo, cor…). */
export function AttributesEditor({
  value,
  onChange,
  label = "Atributos",
}: {
  value: { label: string; value: string }[];
  onChange: (next: { label: string; value: string }[]) => void;
  label?: string;
}) {
  return (
    <div className="sm:col-span-2">
      <div className="mb-1 flex items-center gap-2">
        <span className={labelClass}>{label}</span>
        <button
          type="button"
          onClick={() => onChange([...value, { label: "", value: "" }])}
          className="rounded-md border border-white/8 bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
        >
          acrescentar
        </button>
      </div>
      <div className="space-y-1.5">
        {value.length === 0 && <p className="text-[11.5px] text-muted-foreground">Sem atributos. Servem para mostrar detalhes na ficha do produto.</p>}
        {value.map((attribute, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              className={inputClass}
              placeholder="Nome (ex.: Formato)"
              value={attribute.label}
              onChange={(event) => onChange(value.map((entry, position) => (position === index ? { ...entry, label: event.target.value } : entry)))}
            />
            <input
              className={inputClass}
              placeholder="Valor (ex.: PDF + XLSX)"
              value={attribute.value}
              onChange={(event) => onChange(value.map((entry, position) => (position === index ? { ...entry, value: event.target.value } : entry)))}
            />
            <button
              type="button"
              title="Remover"
              onClick={() => onChange(value.filter((_, position) => position !== index))}
              className="rounded-md border border-white/8 bg-white/[0.04] p-1.5 text-muted-foreground hover:text-rose-200"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- imagens */

/** Imagens do produto: escolhe da biblioteca do CMS ou aceita URLs externos. */
export function ImagePicker({
  ids,
  urls,
  media,
  onChange,
  label = "Imagens",
}: {
  ids: string[];
  urls: string[];
  media: MediaOption[];
  onChange: (next: { ids: string[]; urls: string[] }) => void;
  label?: string;
}) {
  const [pending, setPending] = useState("");
  const byId = useMemo(() => new Map(media.map((item) => [item.id, item])), [media]);
  return (
    <div className="sm:col-span-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className={labelClass}>{label}</span>
        <div className="min-w-0 flex-1" />
        <select className={`${inputClass} max-w-[280px]`} value={pending} onChange={(event) => setPending(event.target.value)}>
          <option value="">— imagem da biblioteca —</option>
          {media
            .filter((item) => item.kind === "imagem")
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.title || item.id}
              </option>
            ))}
        </select>
        <button
          type="button"
          disabled={!pending}
          onClick={() => {
            onChange({ ids: [...ids, pending], urls });
            setPending("");
          }}
          className="rounded-md border border-white/8 bg-white/[0.04] px-2 py-1.5 text-[11.5px] text-muted-foreground transition hover:text-foreground disabled:opacity-40"
        >
          <Plus size={12} className="inline" /> juntar
        </button>
      </div>
      {(ids.length > 0 || urls.length > 0) && (
        <div className="mb-2 flex flex-wrap gap-2">
          {ids.map((id) => {
            const item = byId.get(id);
            return (
              <span key={id} className="relative overflow-hidden rounded-lg border border-white/10">
                {item ? (
                  <img src={shopMediaUrl(item.url)} alt={item.title} className="h-16 w-20 object-cover" />
                ) : (
                  <span className="grid h-16 w-20 place-items-center text-[10px] text-muted-foreground">em falta</span>
                )}
                <button
                  type="button"
                  title="Remover"
                  onClick={() => onChange({ ids: ids.filter((value) => value !== id), urls })}
                  className="absolute right-1 top-1 rounded bg-black/60 p-0.5 text-white"
                >
                  <X size={11} />
                </button>
              </span>
            );
          })}
          {urls.map((url) => (
            <span key={url} className="relative overflow-hidden rounded-lg border border-white/10">
              <img src={url} alt="" className="h-16 w-20 object-cover" />
              <button
                type="button"
                title="Remover"
                onClick={() => onChange({ ids, urls: urls.filter((value) => value !== url) })}
                className="absolute right-1 top-1 rounded bg-black/60 p-0.5 text-white"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        className={areaClass}
        rows={2}
        placeholder="…ou um URL por linha (https://…)"
        value={urls.join("\n")}
        onChange={(event) =>
          onChange({
            ids,
            urls: event.target.value
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
          })
        }
      />
      <span className="mt-1 block text-[10.5px] text-muted-foreground/70">
        A primeira imagem é a que aparece no catálogo. As imagens da biblioteca são as do módulo CMS.
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ vários */

const TONES: Record<string, string> = {
  slate: "border-white/12 bg-white/[0.06] text-slate-300",
  zinc: "border-white/10 bg-white/[0.03] text-muted-foreground",
  amber: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  indigo: "border-indigo-400/30 bg-indigo-400/10 text-indigo-200",
  violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  rose: "border-rose-400/30 bg-rose-400/10 text-rose-200",
};

export function StatusPill({ label, tone = "slate" }: { label: string; tone?: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${TONES[tone] ?? TONES.slate}`}>{label}</span>;
}

export function Chip({ active, onClick, children, title }: { active?: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={[
        "rounded-full border px-2.5 py-1 text-[11.5px] transition",
        active
          ? "border-teal-300/40 bg-teal-400/15 font-medium text-teal-100"
          : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.08] hover:text-foreground",
      ].join(" ")}
    >
      {children}
    </button>
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
        className={[
          "flex h-full flex-col border-l border-white/10 bg-[#08181f] shadow-2xl",
          wide ? "w-full max-w-[min(1080px,96vw)]" : "w-full max-w-[min(560px,96vw)]",
        ].join(" ")}
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
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-white/8 px-4 py-3">{footer}</footer>}
      </aside>
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

export function StatusTabs({
  value,
  onChange,
  statuses,
  counts,
  allLabel = "Todos",
}: {
  value: string;
  onChange: (next: string) => void;
  statuses: { id: string; label: string }[];
  counts?: Record<string, number>;
  allLabel?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-lg border border-white/8 bg-white/[0.05] p-0.5">
      {[{ id: "all", label: allLabel }, ...statuses].map((status) => {
        const active = value === status.id;
        const count = status.id === "all" ? undefined : counts?.[status.id];
        return (
          <button
            key={status.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(status.id)}
            className={[
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition",
              active ? "bg-white/[0.16] font-medium text-foreground shadow-sm" : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
            ].join(" ")}
          >
            {status.label}
            {count !== undefined && <span className="rounded-full bg-white/10 px-1.5 text-[10px] text-muted-foreground">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function ListRow({
  image,
  title,
  subtitle,
  badges,
  meta,
  actions,
  onClick,
}: {
  image?: string;
  title: string;
  subtitle?: string;
  badges?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2 transition hover:border-white/14">
      {image !== undefined && (
        <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-lg bg-white/[0.06] text-[11px] text-teal-200">
          {image ? <img src={shopMediaUrl(image)} alt="" className="h-full w-full object-cover" /> : "—"}
        </span>
      )}
      <button type="button" onClick={onClick} className="min-w-0 flex-1 text-left" disabled={!onClick}>
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[12.5px] font-medium text-foreground">{title}</span>
          {badges}
        </span>
        {subtitle && <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{subtitle}</span>}
      </button>
      {meta && <span className="flex items-center gap-3 text-[11.5px] text-muted-foreground">{meta}</span>}
      {actions && <span className="flex items-center gap-1">{actions}</span>}
    </div>
  );
}

export function IconAction({ title, onClick, children, danger = false }: { title: string; onClick: () => void; children: ReactNode; danger?: boolean }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={[
        "rounded-md border border-white/8 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.1]",
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

export function timeAgo(value?: string | null): string {
  if (!value) return "—";
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value).slice(0, 16).replace("T", " ");
  const minutes = Math.round((Date.now() - stamp) / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  return new Date(stamp).toLocaleDateString("pt-PT");
}

export function Stars({ value, count = 0 }: { value?: number; count?: number }) {
  const average = Number(value) || 0;
  const full = Math.round(average);
  return (
    <span className="whitespace-nowrap text-[11.5px] text-amber-300" title={count ? `${average.toFixed(1)} em ${count} avaliação(ões)` : "sem avaliações"}>
      {"★".repeat(Math.max(0, full))}
      <span className="text-white/20">{"★".repeat(Math.max(0, 5 - full))}</span>
      <span className="ml-1.5 text-muted-foreground">{count ? `${average.toFixed(1)} (${count})` : "—"}</span>
    </span>
  );
}

/** Indicador do painel (receita, encomendas, clientes…). */
export function StatCard({ label, value, hint, tone = "teal" }: { label: string; value: string; hint?: string; tone?: string }) {
  const tones: Record<string, string> = {
    teal: "from-teal-300/18 to-teal-500/5 text-teal-100",
    sky: "from-sky-300/18 to-sky-500/5 text-sky-100",
    amber: "from-amber-300/18 to-amber-500/5 text-amber-100",
    violet: "from-violet-300/18 to-violet-500/5 text-violet-100",
    rose: "from-rose-300/18 to-rose-500/5 text-rose-100",
  };
  return (
    <div className={`rounded-xl border border-white/8 bg-gradient-to-br px-3 py-2.5 ${tones[tone] ?? tones.teal}`}>
      <p className="text-[10.5px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-0.5 text-[17px] font-semibold text-foreground">{value}</p>
      {hint && <p className="mt-0.5 text-[10.5px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Mini-gráfico de barras (vendas dos últimos dias). */
export function MiniBars({ data, label = "Vendas" }: { data: { day: string; revenue: number }[]; label?: string }) {
  const peak = Math.max(1, ...data.map((item) => item.revenue));
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className={labelClass}>{label}</span>
        <span className="text-[10.5px] text-muted-foreground">últimos {data.length} dias</span>
      </div>
      <div className="flex h-20 items-end gap-1">
        {data.map((item) => (
          <span
            key={item.day}
            title={`${new Date(item.day).toLocaleDateString("pt-PT")} · ${money(item.revenue)}`}
            className="flex-1 rounded-t bg-gradient-to-t from-teal-500/25 to-teal-300/70"
            style={{ height: `${Math.max(3, Math.round((item.revenue / peak) * 100))}%` }}
          />
        ))}
      </div>
    </div>
  );
}
