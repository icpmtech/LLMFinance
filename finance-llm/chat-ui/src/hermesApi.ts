/**
 * Cliente do **Hermes** (`/hermes/*`) — o assistente de investigação do IQ OS.
 *
 * Recebe uma pergunta em linguagem natural, recolhe evidências nas fontes da
 * plataforma (contratos, empresas, documentos, notícias) e nas fontes abertas
 * (enciclopédia, dados abertos, investigação), e devolve uma resposta **citada**
 * com o modelo de IA configurado na conta. Sem modelo disponível responde em
 * modo factual (contagens, títulos e indicadores).
 *
 * Modos de investigação: `rapida` (uma recolha) e `profunda` (sub-perguntas,
 * mais fontes e indicadores).
 */
import { API_BASE } from "./api";
import type { SkillRef } from "./types";

/* ------------------------------------------------------------------- tipos */

export type HermesSource = {
  id: string;
  label: string;
  family: string;
  description: string;
  icon: string;
  accent: string;
  kinds: string[];
  capabilities: string[];
  requires_key: boolean;
  default?: boolean;
  available?: boolean;
};

export type HermesDepth = {
  id: string;
  label: string;
  description: string;
  sources: string[];
  limit: number;
  subquestions: boolean;
};

export type HermesBackend = {
  kind: "cloud" | "local" | "unavailable" | string;
  provider?: string | null;
  model?: string | null;
  label?: string | null;
  note?: string | null;
};

export type HermesMeta = {
  about: { name: string; description: string; capabilities: string[] };
  depths: HermesDepth[];
  default_depth: string;
  sources: HermesSource[];
  families: string[];
  indexes: { index: string; label: string; kind: string; documents: number }[];
  cache: { entries: number; ttl_seconds: number };
  limits: {
    max_question_chars: number;
    max_evidence: number;
    max_substeps: number;
    max_history: number;
  };
  backend: HermesBackend;
};

export type HermesEvidence = {
  n: number;
  id?: string | null;
  title: string;
  subtitle?: string | null;
  source: string;
  source_id: string;
  source_family?: string | null;
  kind: string;
  date?: string | null;
  url?: string | null;
  snippet?: string | null;
  score: number;
  also_in: string[];
};

export type HermesMetric = {
  indicator: string;
  label: string;
  country: string;
  points: { year: number; value: number }[];
  first: { year: number; value: number };
  last: { year: number; value: number };
  change: number;
  change_pct: number | null;
  url?: string | null;
};

export type HermesStep = {
  id: string;
  focus: string;
  question: string;
  items: number;
  sources_with_results: number;
  ms: number;
};

export type HermesAnswer = {
  id: string;
  question: string;
  topic: string;
  depth: string;
  depth_label: string;
  sources: string[];
  plan: {
    term: string;
    strategy: string;
    keywords: string[];
    tickers: string[];
    nifs: string[];
    sources: string[];
    auto: boolean;
    macro_hint: boolean;
  };
  backend: HermesBackend;
  mode: "ai" | "factual" | "empty";
  text: string;
  /** Skill (método) que o Hermes seguiu — escolhida na biblioteca ou criada agora. */
  skill?: SkillRef | null;
  evidence: HermesEvidence[];
  metrics: HermesMetric[];
  steps: HermesStep[];
  per_source: { source_id: string; label: string; family?: string | null; items: number; ms: number; ok: boolean }[];
  notes: string[];
  warnings: string[];
  followups: string[];
  generated_at: string;
  stats: {
    ms: number;
    items: number;
    evidence: number;
    sources_queried: number;
    sources_with_results: number;
    subquestions: number;
  };
};

export type HermesAskPayload = {
  question: string;
  depth?: string;
  sources?: string[];
  backend?: string;
  history?: { role: "user" | "assistant"; content: string }[];
  country?: string;
};

/* ----------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/* ------------------------------------------------------------------- rotas */

export function getHermesMeta(): Promise<HermesMeta> {
  return request<HermesMeta>("/hermes/meta");
}

export function askHermes(payload: HermesAskPayload): Promise<HermesAnswer> {
  return request<HermesAnswer>("/hermes/ask", withBody(payload));
}

/* ---------------------------------------------------------------- histórico */

const HISTORY_KEY = "finance-llm-hermes:v1";
const HISTORY_MAX = 30;

export type HermesSavedInvestigation = {
  id: string;
  question: string;
  topic: string;
  depth: string;
  mode: HermesAnswer["mode"];
  text: string;
  evidence: HermesEvidence[];
  metrics: HermesMetric[];
  steps: HermesStep[];
  notes: string[];
  warnings: string[];
  followups: string[];
  per_source: HermesAnswer["per_source"];
  stats: HermesAnswer["stats"];
  backend: HermesBackend;
  skill?: SkillRef | null;
  generated_at: string;
};

/** Investigações guardadas neste browser (as mais recentes primeiro). */
export function loadHermesHistory(): HermesSavedInvestigation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const parsed = raw ? (JSON.parse(raw) as HermesSavedInvestigation[]) : [];
    return Array.isArray(parsed) ? parsed.filter((entry) => entry && entry.id && entry.question) : [];
  } catch {
    return [];
  }
}

export function saveHermesInvestigation(answer: HermesAnswer): HermesSavedInvestigation[] {
  const entry: HermesSavedInvestigation = {
    id: answer.id,
    question: answer.question,
    topic: answer.topic,
    depth: answer.depth,
    mode: answer.mode,
    text: answer.text,
    evidence: answer.evidence,
    metrics: answer.metrics,
    steps: answer.steps,
    notes: answer.notes,
    warnings: answer.warnings,
    followups: answer.followups,
    per_source: answer.per_source,
    stats: answer.stats,
    backend: answer.backend,
    skill: answer.skill ?? null,
    generated_at: answer.generated_at,
  };
  const next = [entry, ...loadHermesHistory().filter((item) => item.id !== entry.id)].slice(0, HISTORY_MAX);
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* quota cheia: o histórico é só um extra */
  }
  return next;
}

export function removeHermesInvestigation(id: string): HermesSavedInvestigation[] {
  const next = loadHermesHistory().filter((entry) => entry.id !== id);
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* ignorar */
  }
  return next;
}

export function clearHermesHistory(): HermesSavedInvestigation[] {
  try {
    window.localStorage.removeItem(HISTORY_KEY);
  } catch {
    /* ignorar */
  }
  return [];
}

/* -------------------------------------------------------------- Office / doc */

/** Converte uma investigação em documento Markdown pronto para o Office. */
export function hermesMarkdown(answer: {
  question: string;
  depth_label?: string;
  mode: string;
  text: string;
  evidence: HermesEvidence[];
  metrics: HermesMetric[];
  per_source: { label: string; items: number }[];
  notes: string[];
  warnings: string[];
  followups: string[];
  backend: HermesBackend;
  skill?: SkillRef | null;
  stats: { ms: number; items: number; sources_with_results: number };
}): string {
  const lines: string[] = [`# ${answer.question}`, ""];
  lines.push(
    `> Investigação Hermes · ${answer.depth_label ?? ""} · resposta ${answer.mode === "ai" ? "redigida por IA" : "factual"} · ` +
      `${answer.evidence.length} evidências em ${answer.stats.sources_with_results} fontes · ${(answer.stats.ms / 1000).toFixed(1)}s`,
  );
  if (answer.backend?.provider) {
    lines.push(`> Modelo: ${answer.backend.provider}${answer.backend.model ? ` · ${answer.backend.model}` : ""}`);
  }
  if (answer.skill?.name) {
    lines.push(`> Skill: ${answer.skill.name}${answer.skill.created ? " (criada nesta investigação)" : ""}`);
    if (answer.skill.steps?.length) {
      lines.push("", "**Método seguido**", "");
      answer.skill.steps.forEach((step, index) => lines.push(`${index + 1}. ${step}`));
    }
  }
  lines.push("", answer.text, "");
  if (answer.metrics.length) {
    lines.push("## Indicadores", "");
    lines.push("| Indicador | País | Primeiro | Último | Variação |", "| --- | --- | --- | --- | --- |");
    for (const metric of answer.metrics) {
      lines.push(
        `| ${metric.label} | ${metric.country} | ${metric.first.value.toFixed(2)} (${metric.first.year}) | ` +
          `${metric.last.value.toFixed(2)} (${metric.last.year}) | ${metric.change >= 0 ? "+" : ""}${metric.change.toFixed(2)} |`,
      );
    }
    lines.push("");
  }
  if (answer.evidence.length) {
    lines.push("## Evidências", "");
    for (const entry of answer.evidence) {
      const link = entry.url ? ` [ligação](${entry.url})` : "";
      lines.push(`- **[${entry.n}] ${entry.title}** — ${entry.source}${entry.date ? ` · ${entry.date}` : ""}${link}`);
    }
    lines.push("");
  }
  lines.push("## Fontes consultadas", "");
  for (const row of answer.per_source) {
    lines.push(`- ${row.label}: ${row.items} resultado${row.items === 1 ? "" : "s"}`);
  }
  if (answer.followups.length) {
    lines.push("", "## Próximos passos", "");
    for (const item of answer.followups) lines.push(`- ${item}`);
  }
  if (answer.warnings.length || answer.notes.length) {
    lines.push("", "## Notas", "");
    for (const item of [...answer.notes, ...answer.warnings]) lines.push(`- ${item}`);
  }
  return lines.join("\n");
}
