/**
 * Peças partilhadas da página **Empresas & Risco**: medidor do score, selo de
 * nível, barras dos componentes e formatação.
 *
 * Tudo o que é formatação (`formatEuro`, `formatNumber`, …) e as caixas
 * (`SectionCard`, `Kpi`, `Chip`, `EmptyState`, `Loading`) vem do kit do módulo de
 * padrões — a leitura tem de ser igual nos dois módulos, porque medem o mesmo.
 */
import type { ReactNode } from "react";
import { Gauge, Info, ShieldAlert, TrendingUp } from "lucide-react";

import type { RiscoAvaliacao, RiscoComponente, RiscoNivel } from "../../riscoApi";
import { Chip, EmptyState, formatNumber } from "../padroes/padroesKit";

/** Cor de cada nível (a mesma do backend, para o cartão e a UI não divergirem). */
export const RISCO_CORES: Record<string, string> = {
  baixo: "#2dd4bf",
  moderado: "#a3e635",
  elevado: "#fbbf24",
  muito_elevado: "#fb7185",
  critico: "#ef4444",
  sem_dados: "#94a3b8",
};

/** Tom do `Chip` correspondente a cada nível. */
export const RISCO_TONES: Record<string, string> = {
  baixo: "teal",
  moderado: "blue",
  elevado: "amber",
  muito_elevado: "rose",
  critico: "rose",
  sem_dados: "neutral",
};

export function riscoCor(nivel?: string | null): string {
  return RISCO_CORES[String(nivel || "sem_dados")] ?? RISCO_CORES.sem_dados;
}

export function riscoTone(nivel?: string | null): string {
  return RISCO_TONES[String(nivel || "sem_dados")] ?? "neutral";
}

/** Selo compacto: `63 · Muito elevado`. */
export function RiscoBadge({ risco, compact = false }: { risco?: RiscoAvaliacao | null; compact?: boolean }) {
  if (!risco || risco.score === null || risco.score === undefined) {
    return <Chip tone="neutral">sem dados</Chip>;
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: `${risco.cor}55`, backgroundColor: `${risco.cor}1a`, color: risco.cor }}
      title={`${risco.metodo_label || risco.metodo || ""} · confiança ${risco.confianca} · cobertura ${Math.round((risco.cobertura || 0) * 100)}%`}
    >
      <ShieldAlert size={12} />
      <span className="font-mono font-semibold">{risco.score.toFixed(0)}</span>
      {!compact && <span>{risco.nivel_label}</span>}
    </span>
  );
}

/** Medidor circular do score (0–100) com o nível por baixo. */
export function RiscoGauge({ risco, size = 168 }: { risco?: RiscoAvaliacao | null; size?: number }) {
  const score = typeof risco?.score === "number" ? Math.max(0, Math.min(100, risco.score)) : null;
  const cor = score === null ? RISCO_CORES.sem_dados : risco?.cor || riscoCor(risco?.nivel);
  const raio = size / 2 - 12;
  const perímetro = 2 * Math.PI * raio;
  const preenchido = ((score ?? 0) / 100) * perímetro;
  return (
    <div className="flex flex-col items-center gap-1" style={{ width: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Risco ${score ?? "sem dados"}`}>
        <circle cx={size / 2} cy={size / 2} r={raio} fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth={12} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={raio}
          fill="none"
          stroke={cor}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={`${preenchido} ${perímetro}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray 500ms ease" }}
        />
        <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" fill="currentColor" className="fill-current" fontSize={size / 4} fontWeight={700}>
          {score === null ? "—" : score.toFixed(0)}
        </text>
        <text x="50%" y="66%" textAnchor="middle" fill="currentColor" opacity={0.6} fontSize={size / 11}>
          /100
        </text>
      </svg>
      <p className="text-sm font-semibold" style={{ color: cor }}>
        {risco?.nivel_label || "Sem dados"}
      </p>
      {risco?.faixa && <p className="text-[11px] text-muted-foreground">faixa {risco.faixa}</p>}
    </div>
  );
}

function corComponente(pontos?: number | null): string {
  if (pontos === null || pontos === undefined) return RISCO_CORES.sem_dados;
  if (pontos >= 75) return RISCO_CORES.critico;
  if (pontos >= 50) return RISCO_CORES.elevado;
  if (pontos >= 25) return RISCO_CORES.moderado;
  return RISCO_CORES.baixo;
}

/** Barras dos componentes: pontos, peso efetivo e a evidência que os sustenta. */
export function ComponentesRisco({ componentes, mostrarEvidencia = true }: { componentes: RiscoComponente[]; mostrarEvidencia?: boolean }) {
  if (!componentes?.length) return <EmptyState>Sem componentes para mostrar.</EmptyState>;
  return (
    <ul className="space-y-3">
      {componentes.map((item) => {
        const pontos = item.pontos ?? null;
        const cor = corComponente(pontos);
        return (
          <li key={item.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3" title={[item.descricao, item.metodo && `Método: ${item.metodo}`].filter(Boolean).join("\n")}>
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm">
                <TrendingUp size={13} className="text-muted-foreground" />
                {item.label}
              </span>
              <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-mono" style={{ color: cor }}>
                  {pontos === null ? "sem dados" : `${pontos.toFixed(0)}/100`}
                </span>
                <span>peso {Math.round((item.peso_efetivo ?? item.peso) * 100)}%</span>
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full" style={{ width: `${pontos ?? 0}%`, backgroundColor: cor, opacity: item.disponivel ? 1 : 0.25 }} />
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

/** Nota de rodapé com o aviso do modelo (repetida onde o score aparece sozinho). */
export function AvisoModelo({ risco, className = "" }: { risco?: RiscoAvaliacao | null; className?: string }) {
  const aviso = risco?.cartao_modelo?.aviso;
  if (!aviso) return null;
  return (
    <p className={`flex items-start gap-2 text-[11px] text-muted-foreground ${className}`}>
      <Info size={13} className="mt-0.5 shrink-0 text-sky-300" />
      <span>
        {aviso} <span className="opacity-70">Modelo {risco?.cartao_modelo?.versao}.</span>
      </span>
    </p>
  );
}

/** Bloco do modelo de anomalia (ML): percentil, algoritmo e população. */
export function AnomaliaMl({ risco }: { risco?: RiscoAvaliacao | null }) {
  const ml = risco?.ml;
  if (!ml) return null;
  if (!ml.disponivel) {
    return (
      <EmptyState>
        Modelo de anomalia indisponível: {ml.motivo || "sem população de referência suficiente"}.
      </EmptyState>
    );
  }
  const percentil = ml.percentil ?? 0;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Gauge size={13} className="text-teal-300" />
          {ml.algoritmo}
        </span>
        <span className="font-mono text-foreground">percentil {(percentil * 100).toFixed(0)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.round(percentil * 100)}%`,
            background: `linear-gradient(90deg, ${RISCO_CORES.baixo}, ${RISCO_CORES.elevado}, ${RISCO_CORES.critico})`,
          }}
        />
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Posição entre {formatNumber(ml.n_referencia ?? 0)} empresas comparáveis · features: {(ml.features || []).join(", ")}
      </p>
      {ml.nota && <p className="mt-1 text-[11px] text-muted-foreground">{ml.nota}</p>}
    </div>
  );
}

/** Lista de avisos do motor (cobertura, amostra, indisponibilidades). */
export function AvisosRisco({ risco }: { risco?: RiscoAvaliacao | null }) {
  if (!risco?.avisos?.length) return null;
  return (
    <ul className="space-y-1">
      {risco.avisos.map((aviso, index) => (
        <li key={index} className="text-[11px] text-muted-foreground">
          · {aviso}
        </li>
      ))}
    </ul>
  );
}

/** Linhas de contexto (país, contratos, valor) usadas nas listas. */
export function LinhaContexto({ children }: { children: ReactNode }) {
  return <p className="text-[11px] text-muted-foreground">{children}</p>;
}

export type { RiscoNivel };
