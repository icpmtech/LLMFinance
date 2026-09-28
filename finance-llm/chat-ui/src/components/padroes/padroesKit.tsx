/**
 * Peças visuais do módulo **Deteção de padrões**.
 *
 * Segue o desenho «premium» do IQ OS (`glass-card`, `gradient-border`, `glow-*`)
 * e concentra aqui os formatadores e os estados vazios, para a página ficar
 * legível e as tabelas consistentes entre painéis.
 */
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Info, Search, X } from "lucide-react";

/** Campo de formulário com rótulo curto (usado nas barras de filtros). */
export function FilterField({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground ${className}`}>
      <span className="truncate">{label}</span>
      {children}
    </label>
  );
}

/** Campo de pesquisa com ícone e botão de limpar (usado em todos os painéis com tabelas). */
export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2">
      <Search size={14} className="shrink-0 text-muted-foreground" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full bg-transparent text-sm normal-case tracking-normal text-foreground outline-none placeholder:text-muted-foreground/60"
      />
      {value && (
        <button onClick={() => onChange("")} className="shrink-0 text-muted-foreground hover:text-foreground">
          <X size={13} />
        </button>
      )}
    </div>
  );
}

export function formatEuro(value?: number | null, digits = 0): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: digits });
}

export function formatCompactEuro(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} k€`;
  return formatEuro(value);
}

export function formatNumber(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT");
}

export function formatPct(value?: number | null, digits = 1): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatRatio(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}×`;
}

/** Dias com sinal explícito («+12 d» / «−30 d»). */
export function formatDays(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${rounded.toLocaleString("pt-PT")} d`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("pt-PT");
}

export function SectionCard({
  title,
  subtitle,
  icon: Icon,
  actions,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`glass-card gradient-border rounded-2xl p-5 ${className}`}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            {Icon && <Icon size={18} className="text-teal-300" />}
            {title}
          </h2>
          {subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Kpi({
  icon: Icon,
  label,
  value,
  sub,
  color = "text-teal-300",
  glow = "glow-teal",
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  color?: string;
  glow?: string;
}) {
  return (
    <div className={`glass-card gradient-border rounded-2xl p-4 ${glow}`}>
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        <Icon size={16} className={color} />
        {label}
      </div>
      <p className="stat-value text-xl font-bold md:text-2xl">{value}</p>
      {sub && <p className="mt-1 text-[11px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

const TONE: Record<string, string> = {
  neutral: "bg-white/5 text-muted-foreground border-white/10",
  teal: "bg-teal-400/10 text-teal-200 border-teal-400/25",
  amber: "bg-amber-400/10 text-amber-200 border-amber-400/25",
  rose: "bg-rose-400/10 text-rose-200 border-rose-400/25",
  blue: "bg-sky-400/10 text-sky-200 border-sky-400/25",
  violet: "bg-violet-400/10 text-violet-200 border-violet-400/25",
};

export function Chip({ children, tone = "neutral", title }: { children: ReactNode; tone?: keyof typeof TONE | string; title?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${TONE[tone] ?? TONE.neutral}`} title={title}>
      {children}
    </span>
  );
}

/** Barra de score 0–1 (percentil de anomalia). */
export function ScoreBar({ score, label }: { score?: number | null; label?: string }) {
  const value = Math.max(0, Math.min(1, score ?? 0));
  const tone = value >= 0.9 ? "from-rose-400 to-rose-600" : value >= 0.75 ? "from-amber-300 to-amber-500" : "from-teal-300 to-teal-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full bg-gradient-to-r ${tone}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="font-mono text-[11px] text-muted-foreground">{value.toFixed(2)}</span>
      {label && <span className="text-[11px] text-muted-foreground">{label}</span>}
    </div>
  );
}

export function EmptyState({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const Icon = tone === "warn" ? AlertTriangle : Info;
  return (
    <div className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-xs text-muted-foreground">
      <Icon size={15} className={tone === "warn" ? "mt-0.5 shrink-0 text-amber-300" : "mt-0.5 shrink-0 text-sky-300"} />
      <span>{children}</span>
    </div>
  );
}

export function Loading({ label = "A analisar…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-muted-foreground">
      <span className="animated-shimmer h-4 w-4 rounded-full" />
      {label}
    </div>
  );
}

/** Rótulo legível dos detectores usados pelo motor. */
export const DETECTOR_LABELS: Record<string, string> = {
  isolation_forest: "Isolation Forest",
  lof: "Local Outlier Factor",
  kmeans: "K-Means",
  one_class_svm: "One-Class SVM",
  dbscan: "DBSCAN",
  z_cpv: "z-score por CPV",
  // Nome antigo da chave do K-Means (compatibilidade com respostas em cache).
  cluster_distance: "K-Means",
};

/** Rótulo **curto** para os chips (o nome completo fica no tooltip). */
export const DETECTOR_SHORT: Record<string, string> = {
  isolation_forest: "IForest",
  lof: "LOF",
  kmeans: "KMeans",
  one_class_svm: "OCSVM",
  dbscan: "DBSCAN",
  z_cpv: "z-CPV",
  cluster_distance: "KMeans",
};

/**
 * Motivos das entidades vêm do backend como frases; nos chips usa-se a versão
 * curta (o `title` guarda o texto integral, para não se perder informação).
 */
export function motivoCurto(texto: string): string {
  if (texto.includes("LOF")) return "fora do padrão (LOF)";
  if (texto.includes("poucos adjudicantes")) return "valor concentrado";
  if (texto.includes("um quarto")) return ">25% contratos sinalizados";
  if (texto.includes("insolvência")) return "insolvência (CIRE)";
  return texto.length > 34 ? `${texto.slice(0, 32)}…` : texto;
}

export function detectorTone(name: string): string {
  switch (name) {
    case "isolation_forest":
      return "rose";
    case "lof":
      return "amber";
    case "one_class_svm":
      return "violet";
    case "kmeans":
    case "cluster_distance":
      return "blue";
    case "dbscan":
      return "teal";
    default:
      return "neutral";
  }
}

/** Rótulo legível dos padrões (o id vem do backend). */
export const PADRAO_LABELS: Record<string, string> = {
  desvio_preco_alto: "Preço acima do base",
  desvio_preco_baixo: "Preço muito abaixo do base",
  aditivo_valor: "Aditivo financeiro",
  publicacao_tardia: "Transparência tardia",
  publicacao_incoerente: "Publicado antes de assinado",
  assinatura_tardia: "Assinatura tardia",
  decisao_muito_anterior: "Decisão com atraso",
  ajuste_direto_atipico: "Ajuste direto atípico",
  baixa_concorrencia: "Baixa concorrência",
  sem_concorrentes: "Sem concorrentes",
  valor_atipico: "Valor atípico no CPV",
  prazo_execucao_longo: "Prazo muito longo",
  contrato_atipico: "Contrato atípico",
  concentracao_fornecedor: "Concentração",
  rede_pessoas: "Laço societário",
  insolvencia: "Insolvência / PER",
  noticias_negativas: "Menções em notícias",
  risco_aditivo: "Risco de aditivo",
};

export function padraoLabel(id: string): string {
  return PADRAO_LABELS[id] ?? id;
}

export function padraoTone(id: string): string {
  if (id.startsWith("desvio") || id === "aditivo_valor") return "rose";
  if (id === "insolvencia") return "rose";
  if (id === "rede_pessoas" || id.startsWith("concentracao")) return "violet";
  if (id.startsWith("publicacao") || id.startsWith("assinatura") || id === "ajuste_direto_atipico") return "amber";
  if (id === "baixa_concorrencia" || id === "valor_atipico" || id === "sem_concorrentes") return "blue";
  return "neutral";
}
