/**
 * Peças do CMS: campos de formulário, gaveta de edição e **editor de blocos**.
 *
 * O editor de blocos é o coração das páginas: cada bloco tem um tipo
 * (`hero`, `texto`, `imagem`, `faq`, …) e o formulário certo para esse tipo.
 * A lista de tipos e os ícones vêm do servidor (`GET /cms/catalogue`), pelo que
 * acrescentar um bloco novo no backend faz aparecer o editor automaticamente.
 */
import { useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "../ui/Button";
import { cmsMediaUrl } from "../../cmsApi";

export const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/60 focus:border-teal-300/40 focus:bg-white/[0.07]";
export const areaClass = `${inputClass} resize-y font-normal leading-relaxed`;
export const cardClass = "rounded-xl border border-white/8 bg-white/[0.03] p-3";
export const labelClass = "text-[11.5px] font-medium text-muted-foreground";

export type MediaOption = { id: string; title: string; url: string; kind: string; mime: string; size: number; storage: string };
export type BlockTypeInfo = { id: string; label: string; hint: string };

export type CmsBlockLike = {
  id: string;
  type: string;
  hidden?: boolean;
  data: Record<string, unknown>;
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
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  wide?: boolean;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint} wide={wide}>
      <input className={inputClass} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
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

export function MediaPicker({
  label,
  value,
  onChange,
  media,
  wide,
  placeholder = "— sem imagem —",
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  media: MediaOption[];
  wide?: boolean;
  placeholder?: string;
}) {
  const selected = media.find((item) => item.id === value);
  return (
    <Field label={label} wide={wide}>
      <div className="flex items-center gap-2">
        <select className={inputClass} value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">{placeholder}</option>
          {media.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title || item.id}
            </option>
          ))}
        </select>
        {selected && selected.kind === "imagem" && (
          <img src={cmsMediaUrl(selected)} alt="" className="h-8 w-8 rounded-md border border-white/10 object-cover" />
        )}
      </div>
    </Field>
  );
}

/* ------------------------------------------------------------------ vários */

export function StatusBadge({ status, labels }: { status: string; labels: Record<string, string> }) {
  const tone: Record<string, string> = {
    publicado: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    agendado: "border-amber-400/30 bg-amber-400/10 text-amber-100",
    rascunho: "border-white/12 bg-white/[0.06] text-slate-300",
    arquivado: "border-white/10 bg-white/[0.03] text-muted-foreground",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${tone[status] ?? tone.rascunho}`}>
      {labels[status] ?? status}
    </span>
  );
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

/** Cabeçalho de uma secção do CMS: título, explicação e ações à direita. */
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

/** Filtro por estado de publicação, com contagens. */
export function StatusTabs({
  value,
  onChange,
  statuses,
  counts,
}: {
  value: string;
  onChange: (next: string) => void;
  statuses: { id: string; label: string }[];
  counts?: Record<string, number>;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-lg border border-white/8 bg-white/[0.05] p-0.5">
      {[{ id: "all", label: "Todos" }, ...statuses].map((status) => {
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

/** Índice de um documento na lista (título, caminho, meta e ações). */
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

/** Botão de ação compacto (ícone) usado nas listas. */
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

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "ok"; children: ReactNode }) {  const styles: Record<string, string> = {
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

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/* ------------------------------------------------------------- blocos */

const itemDefaults: Record<string, Record<string, string>> = {
  destaques: { title: "Novo cartão", text: "" },
  faq: { question: "Pergunta?", answer: "" },
  passos: { title: "Passo", text: "" },
};

/** Itens de uma lista dentro de um bloco (`destaques`, `faq`, `passos`). */
function ItemsEditor({
  block,
  items,
  onChange,
}: {
  block: CmsBlockLike;
  items: Record<string, unknown>[];
  onChange: (next: Record<string, unknown>[]) => void;
}) {
  const template = itemDefaults[block.type] ?? { title: "", text: "" };
  const keys = Object.keys(template);
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={index} className="rounded-lg border border-white/8 bg-white/[0.02] p-2">
          <div className="flex items-center gap-2">
            <span className="text-[10.5px] font-medium uppercase tracking-wide text-muted-foreground">Item {index + 1}</span>
            <div className="flex-1" />
            <button
              type="button"
              title="Remover item"
              onClick={() => onChange(items.filter((_, position) => position !== index))}
              className="rounded p-1 text-muted-foreground transition hover:bg-white/10 hover:text-rose-200"
            >
              <Trash2 size={12} />
            </button>
          </div>
          <div className="mt-1 grid gap-2 sm:grid-cols-2">
            {keys.map((key) => (
              <Field key={key} label={key === "question" ? "Pergunta" : key === "answer" ? "Resposta" : key === "title" ? "Título" : "Texto"} wide={key === "title" || key === "question"}>
                <input
                  className={inputClass}
                  value={String(item[key] ?? "")}
                  onChange={(event) => onChange(items.map((entry, position) => (position === index ? { ...entry, [key]: event.target.value } : entry)))}
                />
              </Field>
            ))}
          </div>
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={() => onChange([...items, { ...template }])} icon={<Plus size={12} />}>
        Acrescentar item
      </Button>
    </div>
  );
}

/** Formulário de um bloco, por tipo. */
function BlockForm({
  block,
  onChange,
  media,
  contents,
  categories,
}: {
  block: CmsBlockLike;
  onChange: (data: Record<string, unknown>) => void;
  media: MediaOption[];
  contents: { id: string; title: string; kind: string }[];
  categories: { id: string; name: string }[];
}) {
  const data = block.data ?? {};
  const set = (key: string, value: unknown) => onChange({ ...data, [key]: value });
  const text = (key: string) => String(data[key] ?? "");
  const list = (key: string) => (Array.isArray(data[key]) ? (data[key] as Record<string, unknown>[]) : []);

  switch (block.type) {
    case "hero":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Título" value={text("title")} onChange={(next) => set("title", next)} wide />
          <TextInput label="Subtítulo" value={text("subtitle")} onChange={(next) => set("subtitle", next)} wide />
          <MediaPicker label="Imagem de fundo" value={text("image_id")} onChange={(next) => set("image_id", next)} media={media} wide />
          <TextInput label="Botão — texto" value={text("cta_label")} onChange={(next) => set("cta_label", next)} />
          <TextInput label="Botão — ligação" value={text("cta_href")} onChange={(next) => set("cta_href", next)} placeholder="/site/blog" />
          <SelectInput
            label="Alinhamento"
            value={text("align") || "esquerda"}
            onChange={(next) => set("align", next)}
            options={[
              { value: "esquerda", label: "Esquerda" },
              { value: "centro", label: "Centro" },
            ]}
            wide
          />
        </div>
      );
    case "texto":
      return (
        <div className="grid gap-2">
          <TextInput label="Título da secção" value={text("title")} onChange={(next) => set("title", next)} wide />
          <TextArea label="Corpo (Markdown)" value={text("markdown")} onChange={(next) => set("markdown", next)} rows={8} mono />
        </div>
      );
    case "imagem":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <MediaPicker label="Imagem" value={text("media_id")} onChange={(next) => set("media_id", next)} media={media} wide />
          <TextInput label="…ou URL externo" value={text("url")} onChange={(next) => set("url", next)} wide hint="Use quando a imagem não está na biblioteca do CMS." />
          <TextInput label="Texto alternativo" value={text("alt")} onChange={(next) => set("alt", next)} />
          <TextInput label="Legenda" value={text("caption")} onChange={(next) => set("caption", next)} />
        </div>
      );
    case "galeria":
      return (
        <div className="space-y-2">
          <p className={labelClass}>Imagens da galeria</p>
          <div className="flex flex-wrap gap-1">
            {media.map((item) => {
              const chosen = (data.media_ids as string[] | undefined) ?? [];
              const active = chosen.includes(item.id);
              return (
                <Chip
                  key={item.id}
                  active={active}
                  onClick={() => set("media_ids", active ? chosen.filter((id) => id !== item.id) : [...chosen, item.id])}
                >
                  {item.title || item.id}
                </Chip>
              );
            })}
          </div>
        </div>
      );
    case "destaques":
    case "faq":
    case "passos":
      return (
        <div className="space-y-2">
          <TextInput label="Título da secção" value={text("title")} onChange={(next) => set("title", next)} wide />
          <ItemsEditor block={block} items={list("items")} onChange={(next) => set("items", next)} />
        </div>
      );
    case "cta":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Título" value={text("title")} onChange={(next) => set("title", next)} wide />
          <TextInput label="Texto" value={text("text")} onChange={(next) => set("text", next)} wide />
          <TextInput label="Botão — texto" value={text("button_label")} onChange={(next) => set("button_label", next)} />
          <TextInput label="Botão — ligação" value={text("button_href")} onChange={(next) => set("button_href", next)} placeholder="/site/contactos" />
        </div>
      );
    case "tabela":
      return (
        <div className="grid gap-2">
          <TextInput label="Título" value={text("title")} onChange={(next) => set("title", next)} wide />
          <TextArea
            label="Cabeçalho (uma célula por linha)"
            value={((data.head as string[] | undefined) ?? []).join("\n")}
            onChange={(next) => set("head", next.split("\n").filter((line) => line.trim()))}
            rows={3}
          />
          <TextArea
            label="Linhas (células separadas por |)"
            value={((data.rows as string[][] | undefined) ?? []).map((row) => row.join(" | ")).join("\n")}
            onChange={(next) =>
              set(
                "rows",
                next
                  .split("\n")
                  .filter((line) => line.trim())
                  .map((line) => line.split("|").map((cell) => cell.trim())),
              )
            }
            rows={5}
            mono
          />
        </div>
      );
    case "citacao":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextArea label="Citação" value={text("quote")} onChange={(next) => set("quote", next)} rows={3} wide />
          <TextInput label="Autor" value={text("author")} onChange={(next) => set("author", next)} wide />
        </div>
      );
    case "aviso":
      return (
        <div className="grid gap-2">
          <TextArea label="Texto" value={text("text")} onChange={(next) => set("text", next)} rows={3} />
          <SelectInput
            label="Tom"
            value={text("tone") || "info"}
            onChange={(next) => set("tone", next)}
            options={[
              { value: "info", label: "Informação" },
              { value: "green", label: "Sucesso" },
              { value: "amber", label: "Atenção" },
              { value: "red", label: "Erro" },
            ]}
            wide
          />
        </div>
      );
    case "codigo":
      return (
        <div className="grid gap-2">
          <TextInput label="Linguagem" value={text("language")} onChange={(next) => set("language", next)} wide placeholder="python, bash, json…" />
          <TextArea label="Código" value={text("code")} onChange={(next) => set("code", next)} rows={8} mono />
        </div>
      );
    case "contactos":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Título" value={text("title")} onChange={(next) => set("title", next)} wide />
          <TextInput label="Email" value={text("email")} onChange={(next) => set("email", next)} />
          <TextInput label="Telefone" value={text("phone")} onChange={(next) => set("phone", next)} />
          <TextInput label="Morada" value={text("address")} onChange={(next) => set("address", next)} wide />
        </div>
      );
    case "blog":
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Título da secção" value={text("title")} onChange={(next) => set("title", next)} />
          <NumberInput label="Nº de artigos" value={Number(data.limit ?? 3)} onChange={(next) => set("limit", next)} min={1} max={24} />
          <SelectInput
            label="Só desta categoria"
            value={text("category_id")}
            onChange={(next) => set("category_id", next)}
            options={categories.map((item) => ({ value: item.id, label: item.name }))}
            placeholder="— todas —"
            wide
          />
        </div>
      );
    case "conteudo":
      return (
        <SelectInput
          label="Conteúdo reutilizado"
          value={text("content_id")}
          onChange={(next) => set("content_id", next)}
          options={contents.map((item) => ({ value: item.id, label: item.title }))}
          placeholder="— escolher —"
          wide
          hint="Alterar o conteúdo na secção «Conteúdos» atualiza todas as páginas que o usam."
        />
      );
    case "divisor":
      return <p className="text-[12px] text-muted-foreground">Uma linha de separação entre secções. Não tem campos.</p>;
    default:
      return <p className="text-[12px] text-muted-foreground">Este bloco não tem campos configuráveis.</p>;
  }
}

/** Lista de blocos de uma página, com mover/ocultar/duplicar/apagar. */
export function BlockEditor({
  blocks,
  onChange,
  blockTypes,
  media = [],
  contents = [],
  categories = [],
}: {
  blocks: CmsBlockLike[];
  onChange: (next: CmsBlockLike[]) => void;
  blockTypes: BlockTypeInfo[];
  media?: MediaOption[];
  contents?: { id: string; title: string; kind: string }[];
  categories?: { id: string; name: string }[];
}) {
  const [adding, setAdding] = useState(false);
  const labels = useMemo(() => Object.fromEntries(blockTypes.map((item) => [item.id, item.label])), [blockTypes]);

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= blocks.length) return;
    const next = [...blocks];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const patch = (index: number, data: Record<string, unknown>) =>
    onChange(blocks.map((block, position) => (position === index ? { ...block, data } : block)));

  return (
    <div className="space-y-2">
      {blocks.length === 0 && (
        <p className="rounded-lg border border-dashed border-white/12 px-3 py-4 text-center text-[12px] text-muted-foreground">
          Página sem blocos. Acrescente o primeiro para começar.
        </p>
      )}

      {blocks.map((block, index) => (
        <section key={block.id} className={`rounded-xl border border-white/8 bg-white/[0.02] ${block.hidden ? "opacity-60" : ""}`}>
          <header className="flex flex-wrap items-center gap-2 border-b border-white/8 px-3 py-2">
            <span className="rounded-md bg-teal-400/12 px-2 py-0.5 text-[11px] font-medium text-teal-100">
              {labels[block.type] ?? block.type}
            </span>
            <span className="text-[10.5px] text-muted-foreground">#{index + 1}</span>
            <div className="flex-1" />
            <button type="button" title="Subir" onClick={() => move(index, -1)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground">
              <ArrowUp size={12} />
            </button>
            <button type="button" title="Descer" onClick={() => move(index, 1)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground">
              <ArrowDown size={12} />
            </button>
            <button
              type="button"
              title={block.hidden ? "Mostrar" : "Ocultar"}
              onClick={() => onChange(blocks.map((entry, position) => (position === index ? { ...entry, hidden: !entry.hidden } : entry)))}
              className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              {block.hidden ? <EyeOff size={12} /> : <Eye size={12} />}
            </button>
            <button
              type="button"
              title="Duplicar bloco"
              onClick={() => {
                const clone = { ...block, id: `${block.id}-c${Math.random().toString(36).slice(2, 7)}`, data: { ...block.data } };
                onChange([...blocks.slice(0, index + 1), clone, ...blocks.slice(index + 1)]);
              }}
              className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <Copy size={12} />
            </button>
            <button
              type="button"
              title="Apagar bloco"
              onClick={() => onChange(blocks.filter((_, position) => position !== index))}
              className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-rose-200"
            >
              <Trash2 size={12} />
            </button>
          </header>
          <div className="px-3 py-3">
            <BlockForm block={block} onChange={(data) => patch(index, data)} media={media} contents={contents} categories={categories} />
          </div>
        </section>
      ))}

      {adding ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className={`${labelClass} mb-2`}>Escolher o tipo de bloco</p>
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {blockTypes.map((item) => (
              <button
                key={item.id}
                type="button"
                title={item.hint}
                onClick={() => {
                  onChange([
                    ...blocks,
                    {
                      id: `blk_${Math.random().toString(36).slice(2, 10)}`,
                      type: item.id,
                      data: item.id === "blog" ? { limit: 3 } : {},
                    },
                  ]);
                  setAdding(false);
                }}
                className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-left text-[12px] transition hover:border-teal-300/30 hover:bg-teal-400/10"
              >
                <span className="font-medium text-foreground">{item.label}</span>
                <span className="mt-0.5 block text-[10.5px] text-muted-foreground">{item.hint}</span>
              </button>
            ))}
          </div>
          <div className="mt-2 flex justify-end">
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="secondary" icon={<Plus size={12} />} onClick={() => setAdding(true)}>
          Acrescentar bloco
        </Button>
      )}
    </div>
  );
}
