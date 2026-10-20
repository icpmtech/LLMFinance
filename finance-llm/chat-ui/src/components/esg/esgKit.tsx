/**
 * Peças visuais partilhadas do módulo **ESG**: medidor, selo de nível, barras
 * dos pilares e dos componentes, formatação e avisos.
 *
 * As caixas base (`SectionCard`, `Kpi`, `Chip`, `EmptyState`, `Loading`) vêm do
 * kit do módulo de padrões — a leitura tem de ser a mesma em toda a plataforma.
 */
import type { ReactNode } from "react";
import { Info, Leaf, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";

import type { EsgComponente, EsgNivel, EsgPilarDetalhe } from "../../esgApi";
import { Chip, EmptyState, formatNumber, formatPct } from "../padroes/padroesKit";

export const ESG_CORES: Record<string, string> = {
  lider: "#10b981",
  avancado: "#2dd4bf",
  intermedio: "#fbbf24",
  inicial: "#fb923c",
  fraco: "#ef4444",
  sem_dados: "#94a3b8",
};

export const ESG_TONS: Record<string, string> = {
  lider: "teal",
  avancado: "teal",
  intermedio: "amber",
  inicial: "amber",
  fraco: "rose",
  sem_dados: "neutral",
};

export const ESG_PILAR_CORES: Record<string, string> = {
  e: "#34d399",
  s: "#38bdf8",
  g: "#a78bfa",
};

export function esgCor(nivel?: string | null): string {
  return ESG_CORES[String(nivel || "sem_dados")] ?? ESG_CORES.sem_dados;
}

export function esgTone(nivel?: string | null): string {
  return ESG_TONS[String(nivel || "sem_dados")] ?? "neutral";
}

export function euros(value?: number | null, digits = 0): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: digits });
}

export function compactEuro(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} k€`;
  return euros(value);
}

export function pct(value?: number | null, digits = 1): string {
  return formatPct(value ?? null, digits);
}

export function num(value?: number | null, digits = 0): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-PT", { maximumFractionDigits: digits });
}

export function data(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("pt-PT");
}

/** Selo compacto: `63 · Avançado`. */
export function EsgBadge({
  score,
  nivel,
  nivelLabel,
  cor,
  compact = false,
}: {
  score?: number | null;
  nivel?: EsgNivel | string | null;
  nivelLabel?: string | null;
  cor?: string | null;
  compact?: boolean;
}) {
  if (score === null || score === undefined) {
    return <Chip tone="neutral">sem score</Chip>;
  }
  const tone = cor || esgCor(nivel);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: `${tone}55`, backgroundColor: `${tone}1a`, color: tone }}
      title={`Nível ${nivelLabel || nivel || "—"}`}
    >
      <Leaf size={12} />
      <span className="font-mono font-semibold">{score.toFixed(0)}</span>
      {!compact && <span>{nivelLabel || nivel || ""}</span>}
    </span>
  );
}

/** Medidor circular do score (0–100) com o nível por baixo. */
export function EsgGauge({
  score,
  nivelLabel,
  cor,
  cobertura,
  size = 176,
}: {
  score?: number | null;
  nivelLabel?: string | null;
  cor?: string | null;
  cobertura?: number | null;
  size?: number;
}) {
  const valor = typeof score === "number" ? Math.max(0, Math.min(100, score)) : null;
  const tone = valor === null ? ESG_CORES.sem_dados : cor || ESG_CORES.avancado;
  const raio = size / 2 - 12;
  const perimetro = 2 * Math.PI * raio;
  const preenchido = ((valor ?? 0) / 100) * perimetro;
  return (
    <div className="flex flex-col items-center gap-1" style={{ width: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Score ESG ${valor ?? "sem dados"}`}>
        <circle cx={size / 2} cy={size / 2} r={raio} fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth={12} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={raio}
          fill="none"
          stroke={tone}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={`${preenchido} ${perimetro}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray 500ms ease" }}
        />
        <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" fill="currentColor" className="fill-current" fontSize={size / 4} fontWeight={700}>
          {valor === null ? "—" : valor.toFixed(0)}
        </text>
        <text x="50%" y="66%" textAnchor="middle" fill="currentColor" opacity={0.6} fontSize={size / 11}>
          /100
        </text>
      </svg>
      <p className="text-sm font-semibold" style={{ color: tone }}>
        {nivelLabel || "Sem dados"}
      </p>
      {cobertura !== undefined && cobertura !== null && (
        <p className="text-[11px] text-muted-foreground">cobertura {pct(cobertura, 0)}</p>
      )}
    </div>
  );
}

function corPontos(pontos?: number | null): string {
  if (pontos === null || pontos === undefined) return ESG_CORES.sem_dados;
  if (pontos >= 70) return ESG_CORES.lider;
  if (pontos >= 55) return ESG_CORES.avancado;
  if (pontos >= 40) return ESG_CORES.intermedio;
  if (pontos >= 25) return ESG_CORES.inicial;
  return ESG_CORES.fraco;
}

/** Três barras (E, S, G) com o score e a cobertura de cada pilar. */
export function PilarBars({ pilares }: { pilares: EsgPilarDetalhe[] }) {
  if (!pilares?.length) return <EmptyState>Sem pilares para mostrar.</EmptyState>;
  return (
    <div className="space-y-3">
      {pilares.map((pilar) => {
        const cor = ESG_PILAR_CORES[pilar.id] || pilar.cor;
        return (
          <div key={pilar.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3" title={pilar.descricao}>
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: cor }} />
                {pilar.label}
                <span className="text-[11px] text-muted-foreground">peso {pct(pilar.peso, 0)}</span>
              </span>
              <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-mono" style={{ color: cor }}>
                  {pilar.score === null || pilar.score === undefined ? "sem dados" : `${pilar.score.toFixed(0)}/100`}
                </span>
                <span>cobertura {pct(pilar.cobertura, 0)}</span>
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full"
                style={{ width: `${pilar.score ?? 0}%`, backgroundColor: cor, opacity: pilar.score === null ? 0.25 : 1 }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Barras dos componentes, com o peso efetivo e a evidência. */
export function ComponentesEsg({ componentes, mostrarEvidencia = true }: { componentes: EsgComponente[]; mostrarEvidencia?: boolean }) {
  if (!componentes?.length) return <EmptyState>Sem componentes para mostrar.</EmptyState>;
  return (
    <ul className="space-y-3">
      {componentes.map((item) => {
        const pontos = item.pontos ?? null;
        const cor = corPontos(pontos);
        return (
          <li
            key={item.id}
            className="rounded-xl border border-white/10 bg-white/[0.03] p-3"
            title={[item.descricao, item.metodo && `Método: ${item.metodo}`].filter(Boolean).join("\n")}
          >
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ESG_PILAR_CORES[item.pilar] }} />
                {item.label}
              </span>
              <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-mono" style={{ color: cor }}>
                  {pontos === null ? "sem dados" : `${pontos.toFixed(0)}/100`}
                </span>
                <span>peso {pct(item.peso_efetivo || item.peso, 0)}</span>
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full"
                style={{ width: `${pontos ?? 0}%`, backgroundColor: cor, opacity: item.disponivel ? 1 : 0.25 }}
              />
            </div>
            {mostrarEvidencia && item.evidencia?.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                {item.evidencia.map((linha, index) => (
                  <li key={index}>· {linha}</li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Fatores que mais puxam o score para cima/baixo. */
export function FatoresEsg({ fatores }: { fatores: EsgComponente[] }) {
  if (!fatores?.length) return <EmptyState>Sem fatores com contributo calculado.</EmptyState>;
  const positivos = fatores.filter((item) => (item.contributo ?? 0) > 0).slice(0, 4);
  const negativos = fatores.filter((item) => (item.contributo ?? 0) < 0).slice(0, 4);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-emerald-200">
          <TrendingUp size={14} /> Puxam para cima
        </p>
        {positivos.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Nenhum fator positivo disponível.</p>
        ) : (
          <ul className="space-y-1 text-[11px] text-muted-foreground">
            {positivos.map((item) => (
              <li key={item.id} className="flex justify-between gap-2">
                <span>{item.label}</span>
                <span className="font-mono text-emerald-300">+{(item.contributo ?? 0).toFixed(1)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-xl border border-rose-400/20 bg-rose-400/5 p-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-rose-200">
          <TrendingDown size={14} /> Puxam para baixo
        </p>
        {negativos.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Nenhum fator negativo disponível.</p>
        ) : (
          <ul className="space-y-1 text-[11px] text-muted-foreground">
            {negativos.map((item) => (
              <li key={item.id} className="flex justify-between gap-2">
                <span>{item.label}</span>
                <span className="font-mono text-rose-300">{(item.contributo ?? 0).toFixed(1)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Benchmark: percentil, mediana e posição face aos pares. */
export function BenchmarkEsg({ benchmark }: { benchmark?: import("../../esgApi").EsgBenchmark | null }) {
  if (!benchmark) return <EmptyState>Sem benchmark disponível.</EmptyState>;
  if (!benchmark.disponivel) {
    return (
      <EmptyState>
        {benchmark.motivo || "Amostra de pares insuficiente."}
        {benchmark.n_pares !== undefined && ` (${formatNumber(benchmark.n_pares)} pares)`}
      </EmptyState>
    );
  }
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-3">
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <p className="text-[11px] text-muted-foreground">Percentil no grupo</p>
        <p className="font-mono text-xl font-semibold text-teal-200">{benchmark.percentil?.toFixed(0) ?? "—"}</p>
        <p className="text-[11px] text-muted-foreground">{benchmark.posicao || "—"} · {formatNumber(benchmark.n_pares)} pares</p>
      </div>
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <p className="text-[11px] text-muted-foreground">Mediana do grupo</p>
        <p className="font-mono text-xl font-semibold">{benchmark.mediana?.toFixed(1) ?? "—"}</p>
        <p className="text-[11px] text-muted-foreground">P25 {benchmark.p25?.toFixed(1) ?? "—"} · P75 {benchmark.p75?.toFixed(1) ?? "—"}</p>
      </div>
      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <p className="text-[11px] text-muted-foreground">Pares por pilar (mediana)</p>
        <p className="text-[11px] text-muted-foreground">
          E {benchmark.mediana_pilares?.e?.toFixed(1) ?? "—"} · S {benchmark.mediana_pilares?.s?.toFixed(1) ?? "—"} · G{" "}
          {benchmark.mediana_pilares?.g?.toFixed(1) ?? "—"}
        </p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{benchmark.nota}</p>
      </div>
    </div>
  );
}

/** Nota de rodapé com o aviso do modelo. */
export function AvisoEsg({ aviso, className = "" }: { aviso?: string | null; className?: string }) {
  if (!aviso) return null;
  return (
    <p className={`flex items-start gap-2 text-[11px] text-muted-foreground ${className}`}>
      <Info size={13} className="mt-0.5 shrink-0 text-sky-300" />
      <span>{aviso}</span>
    </p>
  );
}

/** Caixa de destaques (alertas do dossiê/carteira). */
export function AlertasEsg({ alertas }: { alertas?: string[] | null }) {
  if (!alertas?.length) return null;
  return (
    <div className="space-y-1.5">
      {alertas.map((alerta, index) => (
        <p key={index} className="flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-100">
          <ShieldCheck size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>{alerta}</span>
        </p>
      ))}
    </div>
  );
}

/** Cartão de indicador declarado. */
export function IndicadorCard({ label, valor, unidade, pontos, fonte }: { label: string; valor: number; unidade?: string | null; pontos?: number | null; fonte?: string | null }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-2.5" title={fonte || undefined}>
      <p className="truncate text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold">
        {num(valor, 1)} <span className="text-[11px] font-normal text-muted-foreground">{unidade || ""}</span>
      </p>
      {pontos !== null && pontos !== undefined && (
        <p className="text-[10px] text-muted-foreground">pontuação {pontos.toFixed(0)}/100</p>
      )}
    </div>
  );
}

/** Bloco com título e conteúdo (para os painéis do dossiê). */
export function Bloco({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
      <header className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {actions}
      </header>
      {children}
    </section>
  );
}
