/**
 * Peças visuais do sentimento (corpus e mercado).
 *
 * Mobile-first e alinhadas com o resto da plataforma: cartões `glass-card`,
 * alvos de toque ≥ 44 px no telemóvel (`sm:` encolhe), anéis de foco visíveis e
 * tabelas largas com deslocamento horizontal em vez de aperto de colunas.
 */

export const tap = "min-h-[44px] sm:min-h-[34px]";
export const focusRing = "focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400";

export function tone(polarity: number): string {
  if (polarity >= 0.15) return "text-emerald-300";
  if (polarity <= -0.15) return "text-rose-300";
  return "text-muted-foreground";
}

export function labelChip(label: string): string {
  if (label === "positivo") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  if (label === "negativo") return "border-rose-400/30 bg-rose-400/10 text-rose-200";
  return "border-white/10 bg-white/5 text-muted-foreground";
}

/** Fundo de uma célula do heatmap (tom × evidência). */
export function heatClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "bg-white/[0.03] text-muted-foreground/60";
  const strength = Math.min(1, Math.abs(value));
  if (value >= 0.15) {
    if (strength > 0.66) return "bg-emerald-400/45 text-emerald-50";
    if (strength > 0.33) return "bg-emerald-400/30 text-emerald-50";
    return "bg-emerald-400/15 text-emerald-100";
  }
  if (value <= -0.15) {
    if (strength > 0.66) return "bg-rose-400/45 text-rose-50";
    if (strength > 0.33) return "bg-rose-400/30 text-rose-50";
    return "bg-rose-400/15 text-rose-100";
  }
  return "bg-white/10 text-muted-foreground";
}

export function signed(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function shortDay(day: string): string {
  const [, month, date] = (day || "").split("-");
  return month && date ? `${date}/${month}` : day;
}

/** Data/hora legível (agenda e última corrida). */
export function clock(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function number(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { maximumFractionDigits: digits });
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)} %`;
}

export function Kpi({
  label,
  value,
  hint,
  tone: toneClass,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${toneClass ?? ""}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** Barra de polaridade (-1 a 1) com marca central. */
export function PolarityBar({ value, width = 120 }: { value: number; width?: number }) {
  const clamped = Math.max(-1, Math.min(1, value || 0));
  const size = Math.abs(clamped) * (width / 2);
  const positive = clamped >= 0;
  return (
    <span className="inline-flex items-center" style={{ width }} title={clamped.toFixed(3)}>
      <span className="relative block h-2 w-full rounded-full bg-white/10">
        <span className="absolute left-1/2 top-[-2px] h-3 w-px bg-white/20" />
        <span
          className={`absolute top-0 h-2 rounded-full ${positive ? "bg-emerald-400/70" : "bg-rose-400/70"}`}
          style={positive ? { left: "50%", width: size } : { right: "50%", width: size }}
        />
      </span>
    </span>
  );
}

/** Colunas da série diária (altura pelo |tom|, cor pelo sinal, notícias no título). */
export function MiniBars({
  points,
  height = 64,
  onSelect,
}: {
  points: { day: string; sentiment: number; news: number; label?: string }[];
  height?: number;
  onSelect?: (day: string) => void;
}) {
  if (!points.length) {
    return <p className="text-[11px] text-muted-foreground">Sem série nesta janela.</p>;
  }
  return (
    <div className="flex items-end gap-1 overflow-x-auto [scrollbar-width:none]">
      {points.map((point) => {
        const size = Math.max(3, Math.round(Math.abs(point.sentiment) * height));
        const positive = point.sentiment >= 0;
        return (
          <button
            key={point.day}
            type="button"
            onClick={onSelect ? () => onSelect(point.day) : undefined}
            disabled={!onSelect}
            title={`${point.day} · tom ${signed(point.sentiment)} · ${point.news} notícia(s)`}
            className={`flex flex-col items-center gap-1 ${onSelect ? "cursor-pointer" : "cursor-default"}`}
          >
            <span className="flex w-full items-end justify-center" style={{ height }}>
              <span
                className={`block w-2.5 rounded-t ${positive ? "bg-emerald-400/70" : "bg-rose-400/70"}`}
                style={{ height: size }}
              />
            </span>
            <span className="whitespace-nowrap text-[9px] text-muted-foreground">{shortDay(point.day)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Seletor segmentado (janela de análise, base do ranking). */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {label ? <span className="text-[11px] text-muted-foreground">{label}</span> : null}
      <div className="flex overflow-hidden rounded-xl border border-white/10">
        {options.map((option) => (
          <button
            key={String(option.id)}
            type="button"
            onClick={() => onChange(option.id)}
            aria-pressed={option.id === value}
            className={`${tap} ${focusRing} px-3 text-[11px] transition ${
              option.id === value ? "bg-violet-500/25 text-violet-100" : "bg-white/5 text-muted-foreground hover:bg-white/10"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Chip({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${className || "border-white/10 bg-white/5 text-muted-foreground"}`}>
      {children}
    </span>
  );
}

export function Btn({
  children,
  onClick,
  disabled,
  variant = "ghost",
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
  title?: string;
}) {
  const style =
    variant === "primary"
      ? "bg-gradient-to-r from-fuchsia-400 to-indigo-600 text-white disabled:opacity-50"
      : "border border-white/10 bg-white/5 hover:bg-white/10 disabled:opacity-50";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex ${tap} ${focusRing} items-center justify-center gap-2 rounded-xl px-3 text-[11px] font-medium transition ${style}`}
    >
      {children}
    </button>
  );
}
