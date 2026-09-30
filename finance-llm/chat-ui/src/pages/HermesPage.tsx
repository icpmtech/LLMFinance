/**
 * Hermes — o assistente de investigação do IQ OS.
 *
 * Escreve-se uma pergunta em linguagem natural; o Hermes planeia-a, recolhe
 * evidências na plataforma (contratos, empresas, documentos, notícias) e nas
 * fontes abertas (enciclopédia, dados abertos, investigação) e responde com
 * citações `[n]`, através do modelo de IA configurado na conta. Sem modelo
 * disponível responde em modo factual (contagens, títulos e indicadores).
 *
 * Modos: **resposta rápida** (uma recolha) e **investigação profunda**
 * (sub-perguntas, mais fontes e indicadores). O histórico das investigações
 * fica neste browser e a resposta pode ser levada para o Office como documento.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  Compass,
  Copy,
  FileText,
  History,
  Info,
  Loader2,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "../auth";
import { getWindowMode } from "../layout";
import { OFFICE_OPEN_KEY, saveOfficeDocument } from "../officeApi";
import { estimateWorkspace, openWindow } from "../windows";
import {
  askHermes,
  clearHermesHistory,
  getHermesMeta,
  hermesMarkdown,
  loadHermesHistory,
  removeHermesInvestigation,
  saveHermesInvestigation,
  type HermesAnswer,
  type HermesMeta,
  type HermesSavedInvestigation,
} from "../hermesApi";
import {
  deleteSkill,
  listSkills,
  patchSkill,
  type HermesSkill,
  type SkillsStatus,
} from "../skillsApi";
import type { SkillRef } from "../types";
import HermesAgentPanel from "../components/hermes/HermesAgentPanel";

/** O que uma resposta precisa de ter para ser desenhada (viva ou guardada). */
type DisplayAnswer = Pick<
  HermesAnswer,
  | "id"
  | "question"
  | "topic"
  | "depth"
  | "mode"
  | "text"
  | "evidence"
  | "metrics"
  | "steps"
  | "per_source"
  | "notes"
  | "warnings"
  | "followups"
  | "stats"
  | "backend"
  | "generated_at"
> & { depth_label?: string; skill?: SkillRef | null };

type Turn = { id: string; question: string; answer?: DisplayAnswer; error?: string };

const EXAMPLES = [
  "Quais são os maiores contratos públicos de energia em Portugal?",
  "Que empresas portuguesas têm mais contratos com o Estado?",
  "Como evoluiu o desemprego em Portugal na última década?",
  "O que é a ontologia do IQ OS e que objetos tem?",
];

const MODE_TONE: Record<string, string> = {
  ai: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  factual: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  empty: "border-rose-400/30 bg-rose-400/10 text-rose-200",
};

const MODE_LABEL: Record<string, string> = {
  ai: "resposta com IA",
  factual: "resposta factual",
  empty: "sem evidências",
};

const FAMILY_LABEL: Record<string, string> = {
  internal: "Plataforma",
  documents: "Documentos",
  encyclopedia: "Enciclopédia",
  opendata: "Dados abertos",
  research: "Investigação",
  web: "Web",
  ai: "IA",
};

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-teal-400/50 focus:outline-none focus:ring-2 focus:ring-teal-400/20";

function formatMs(ms: number): string {
  if (!ms) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("pt-PT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Lista numerada de evidências com ligação, fonte e trecho. */
function EvidenceList({ evidence }: { evidence: DisplayAnswer["evidence"] }) {
  if (!evidence.length) {
    return <p className="text-sm text-muted-foreground">Nenhuma evidência encontrada.</p>;
  }
  return (
    <ol className="space-y-2">
      {evidence.map((entry) => (
        <li key={`${entry.n}-${entry.id ?? entry.title}`} className="rounded-xl border border-white/8 bg-white/[0.025] p-3">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md bg-white/[0.06] text-[11px] font-semibold text-teal-200">
              {entry.n}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                {entry.url ? (
                  <a
                    href={entry.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[13px] font-medium text-foreground hover:text-teal-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                  >
                    {entry.title}
                    <ArrowUpRight size={12} className="shrink-0 opacity-70" />
                  </a>
                ) : (
                  <span className="text-[13px] font-medium text-foreground">{entry.title}</span>
                )}
                <span className="text-[11px] text-muted-foreground">
                  {entry.source}
                  {entry.date ? ` · ${entry.date}` : ""}
                </span>
              </div>
              {entry.snippet ? (
                <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-muted-foreground">{entry.snippet}</p>
              ) : null}
              {entry.also_in?.length ? (
                <p className="mt-1 text-[10.5px] text-muted-foreground/80">também em: {entry.also_in.join(", ")}</p>
              ) : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Tabela de indicadores (séries do Banco Mundial). */
function MetricsTable({ metrics }: { metrics: DisplayAnswer["metrics"] }) {
  if (!metrics.length) return null;
  return (
    <div className="overflow-x-auto rounded-xl border border-white/8">
      <table className="w-full min-w-[420px] text-left text-[12px]">
        <thead className="bg-white/[0.04] text-[11px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Indicador</th>
            <th className="px-3 py-2 font-medium">País</th>
            <th className="px-3 py-2 font-medium">Primeiro</th>
            <th className="px-3 py-2 font-medium">Último</th>
            <th className="px-3 py-2 font-medium">Variação</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={`${metric.indicator}-${metric.country}`} className="border-t border-white/6">
              <td className="px-3 py-2">
                {metric.url ? (
                  <a href={metric.url} target="_blank" rel="noreferrer" className="hover:text-teal-200">
                    {metric.label}
                  </a>
                ) : (
                  metric.label
                )}
              </td>
              <td className="px-3 py-2 text-muted-foreground">{metric.country}</td>
              <td className="px-3 py-2 text-muted-foreground">
                {metric.first.value.toFixed(2)} <span className="opacity-70">({metric.first.year})</span>
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {metric.last.value.toFixed(2)} <span className="opacity-70">({metric.last.year})</span>
              </td>
              <td className={`px-3 py-2 ${metric.change >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                {metric.change >= 0 ? "+" : ""}
                {metric.change.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function HermesPage() {
  const { user } = useAuth();
  const [meta, setMeta] = useState<HermesMeta | null>(null);
  const [depth, setDepth] = useState("rapida");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [history, setHistory] = useState<HermesSavedInvestigation[]>([]);
  const [skills, setSkills] = useState<HermesSkill[]>([]);
  const [skillsStatus, setSkillsStatus] = useState<SkillsStatus | null>(null);
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const loadSkills = useCallback(async () => {
    try {
      const payload = await listSkills();
      setSkills(payload.skills);
      setSkillsStatus(payload.status);
    } catch {
      /* a biblioteca é um extra: não pode estragar a investigação */
    }
  }, []);

  useEffect(() => {
    setHistory(loadHermesHistory());
    void loadSkills();
    getHermesMeta()
      .then((payload) => {
        setMeta(payload);
        setDepth((current) => (payload.depths.some((item) => item.id === current) ? current : payload.default_depth));
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /* Rolar só a lista de respostas — nunca `scrollIntoView` (arrastaria o ecrã). */
  useEffect(() => {
    const list = bottomRef.current?.parentElement;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [turns.length, loading]);

  const sourceGroups = useMemo(() => {
    const groups = new Map<string, HermesMeta["sources"]>();
    for (const source of meta?.sources ?? []) {
      const bucket = groups.get(source.family);
      if (bucket) bucket.push(source);
      else groups.set(source.family, [source]);
    }
    return [...groups.entries()];
  }, [meta]);

  const defaultSources = useMemo(
    () => (meta?.depths.find((item) => item.id === depth)?.sources ?? []).filter(Boolean),
    [meta, depth],
  );

  const activeSources = selectedSources.length ? selectedSources : defaultSources;

  const submit = useCallback(
    async (raw: string) => {
      const clean = raw.trim();
      if (!clean || loading) return;
      const id = `t-${Date.now()}`;
      const previous = turns.slice(-3);
      setQuestion("");
      setError(null);
      setTurns((rows) => [...rows, { id, question: clean }]);
      setLoading(true);
      try {
        const answer = await askHermes({
          question: clean,
          depth,
          sources: selectedSources.length ? selectedSources : undefined,
          history: previous.flatMap((turn) => [
            { role: "user" as const, content: turn.question },
            ...(turn.answer ? [{ role: "assistant" as const, content: turn.answer.text }] : []),
          ]),
        });
        setTurns((rows) => rows.map((turn) => (turn.id === id ? { ...turn, answer } : turn)));
        setHistory(saveHermesInvestigation(answer));
        void loadSkills();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "A investigação falhou.";
        setTurns((rows) => rows.map((turn) => (turn.id === id ? { ...turn, error: message } : turn)));
        setError(message);
      } finally {
        setLoading(false);
        inputRef.current?.focus();
      }
    },
    [depth, loading, selectedSources, turns, loadSkills],
  );

  const copyAnswer = useCallback(async (answer: DisplayAnswer) => {
    try {
      await navigator.clipboard.writeText(answer.text);
      setCopied(answer.id);
      setNotice("Resposta copiada.");
      window.setTimeout(() => setCopied((current) => (current === answer.id ? null : current)), 2500);
    } catch {
      setError("O browser não deixou copiar para a área de transferência.");
    }
  }, []);

  /** Guarda a investigação como documento do Office e abre a aplicação. */
  const openInOffice = useCallback(
    async (answer: DisplayAnswer) => {
      if (!user) {
        setError("Entrar na plataforma para guardar no Office.");
        return;
      }
      setBusy(answer.id);
      try {
        const payload = await saveOfficeDocument({
          title: `Hermes · ${answer.question.slice(0, 90)}`,
          markdown: hermesMarkdown(answer),
          kind: "relatorio",
          tags: ["hermes", answer.depth],
        });
        if (typeof window !== "undefined") window.localStorage.setItem(OFFICE_OPEN_KEY, payload.document.id);
        if (getWindowMode()) {
          openWindow("office", estimateWorkspace());
        } else if (typeof window !== "undefined") {
          window.history.pushState({}, "", "/office");
          window.dispatchEvent(new PopStateEvent("popstate"));
        }
        setNotice(`«${payload.document.title}» guardado no Office IQ OS.`);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível guardar no Office.");
      } finally {
        setBusy(null);
      }
    },
    [user],
  );

  const reuseInvestigation = useCallback((entry: HermesSavedInvestigation) => {
    setTurns([{ id: `h-${entry.id}`, question: entry.question, answer: entry }]);
  }, []);

  /** Ativa/desativa uma skill (deixa de ser escolhida para novas perguntas). */
  const toggleSkill = useCallback(async (id: string, enabled: boolean) => {
    try {
      await patchSkill(id, { enabled });
      setSkills((current) => current.map((skill) => (skill.id === id ? { ...skill, enabled } : skill)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível alterar a skill.");
    }
  }, []);

  const removeSkill = useCallback(
    async (id: string) => {
      try {
        const payload = await deleteSkill(id);
        setSkills((current) => current.filter((skill) => skill.id !== id));
        setSkillsStatus(payload.status);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível apagar a skill.");
      }
    },
    [],
  );

  const toggleSource = useCallback((sourceId: string) => {
    setSelectedSources((current) =>
      current.includes(sourceId) ? current.filter((item) => item !== sourceId) : [...current, sourceId],
    );
  }, []);

  const backendChip = meta?.backend;
  const backendText =
    backendChip?.kind === "cloud"
      ? `${backendChip.provider}${backendChip.model ? ` · ${backendChip.model}` : ""}`
      : backendChip?.kind === "unavailable"
        ? "sem chave de API"
        : "sem modelo";

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-300 via-purple-500 to-fuchsia-600 text-white shadow-lg shadow-violet-500/25">
          <Compass size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold leading-tight">Hermes</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Assistente de investigação · evidências citadas na plataforma e em fontes abertas
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span
            className={`hidden items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium @2xl:inline-flex ${
              backendChip?.kind === "cloud"
                ? "border-teal-500/25 bg-teal-500/10 text-teal-200"
                : "border-amber-500/25 bg-amber-500/10 text-amber-200"
            }`}
            title={meta?.backend.note ?? "Modelo usado para redigir a resposta"}
          >
            <Sparkles size={11} />
            {backendText}
          </span>
          <button
            type="button"
            onClick={() => setSourcesOpen((current) => !current)}
            aria-expanded={sourcesOpen}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 @4xl:hidden"
          >
            <Info size={13} />
            Opções
          </button>
          <button
            type="button"
            onClick={() => {
              setTurns([]);
              setError(null);
              inputRef.current?.focus();
            }}
            disabled={!turns.length}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
          >
            <RefreshCw size={13} />
            Nova conversa
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 @4xl:flex-row @4xl:gap-4 @4xl:overflow-hidden @4xl:p-4">
        {/* Painel: modo, fontes e histórico — colapsável em janelas estreitas. */}
        <aside
          className={`${sourcesOpen ? "flex" : "hidden"} max-h-[42%] w-full shrink-0 flex-col gap-3 overflow-y-auto @4xl:flex @4xl:h-full @4xl:max-h-none @4xl:min-h-0 @4xl:w-[318px]`}
        >
          <section className="glass-card rounded-2xl p-3">
            <h2 className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
              <Sparkles size={12} /> Modo de investigação
            </h2>
            <div className="space-y-1.5">
              {(meta?.depths ?? []).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setDepth(item.id)}
                  aria-pressed={depth === item.id}
                  className={`w-full rounded-xl border px-3 py-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 ${
                    depth === item.id
                      ? "border-violet-400/40 bg-violet-400/10 text-foreground"
                      : "border-white/8 bg-white/[0.02] text-muted-foreground hover:bg-white/[0.05]"
                  }`}
                >
                  <span className="flex items-center gap-1.5 text-[12.5px] font-medium">
                    {depth === item.id ? <Check size={12} /> : null}
                    {item.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">{item.description}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="glass-card rounded-2xl p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Compass size={12} /> Fontes
              </h2>              {selectedSources.length ? (
                <button
                  type="button"
                  onClick={() => setSelectedSources([])}
                  className="text-[11px] text-teal-300 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                >
                  usar predefinidas
                </button>
              ) : null}
            </div>
            <p className="mb-2 text-[11px] text-muted-foreground">
              {selectedSources.length
                ? `${selectedSources.length} fonte${selectedSources.length === 1 ? "" : "s"} escolhida${selectedSources.length === 1 ? "" : "s"}.`
                : `Predefinidas do modo ${meta?.depths.find((item) => item.id === depth)?.label.toLowerCase() ?? depth}: ${defaultSources.length}.`}
            </p>
            <div className="space-y-2">
              {sourceGroups.map(([family, items]) => (
                <div key={family}>
                  <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground/80">
                    {FAMILY_LABEL[family] ?? family}
                  </p>
                  <ul className="space-y-0.5">
                    {items.map((source) => (
                      <li key={source.id}>
                        <label className="flex cursor-pointer items-start gap-2 rounded-lg px-1.5 py-1 text-[12px] transition hover:bg-white/[0.04]">
                          <input
                            type="checkbox"
                            checked={selectedSources.includes(source.id)}
                            onChange={() => toggleSource(source.id)}
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-foreground/90">{source.label}</span>
                            <span className="block truncate text-[10.5px] text-muted-foreground/80">
                              {source.description}
                              {source.requires_key && !source.available ? " · requer chave" : ""}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              {!meta ? <p className="text-[12px] text-muted-foreground">A carregar fontes…</p> : null}
            </div>
          </section>

          {/* O Hermes Agent (container) é outra coisa que o Hermes nativo desta
              página: aqui liga-se o agente aos fornecedores de IA da plataforma. */}
          <HermesAgentPanel />

          <section className="glass-card rounded-2xl p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                <History size={12} /> Histórico
              </h2>
              {history.length ? (
                <button
                  type="button"
                  onClick={() => setHistory(clearHermesHistory())}
                  className="text-[11px] text-muted-foreground hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                >
                  limpar
                </button>
              ) : null}
            </div>
            {history.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                As investigações ficam guardadas neste browser (últimas 30).
              </p>
            ) : (
              <ul className="space-y-1">
                {history.map((entry) => (
                  <li key={entry.id} className="group flex items-start gap-1">
                    <button
                      type="button"
                      onClick={() => reuseInvestigation(entry)}
                      className="min-w-0 flex-1 rounded-lg px-1.5 py-1 text-left transition hover:bg-white/[0.05] focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                    >
                      <span className="block truncate text-[12px] text-foreground/90">{entry.question}</span>
                      <span className="block truncate text-[10.5px] text-muted-foreground">
                        {MODE_LABEL[entry.mode] ?? entry.mode} · {entry.evidence.length} evidências · {formatWhen(entry.generated_at)}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setHistory(removeHermesInvestigation(entry.id))}
                      aria-label={`Remover «${entry.question}» do histórico`}
                      className="mt-1 rounded-md p-1 text-muted-foreground opacity-0 transition hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      <Trash2 size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Skills: o método que o Hermes segue antes de responder. Nascem das
              perguntas e são partilhadas com o Chat IA e o RAG. */}
          <section className="glass-card rounded-2xl p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Compass size={12} /> Skills
                {skillsStatus ? (
                  <span className="font-normal normal-case text-muted-foreground/80">
                    {skillsStatus.enabled}/{skillsStatus.total} · {skillsStatus.uses} usos
                  </span>
                ) : null}
              </h2>
              <button
                type="button"
                onClick={() => void loadSkills()}
                className="text-[11px] text-muted-foreground hover:text-teal-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
              >
                atualizar
              </button>
            </div>
            <p className="mb-2 text-[11px] text-muted-foreground">
              Antes de responder, o Hermes escolhe uma skill da biblioteca ou cria uma nova a partir da
              pergunta — e segue os seus passos. As mesmas skills servem o Chat IA e o RAG.
            </p>
            {skills.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">Ainda sem skills: a primeira pergunta cria uma.</p>
            ) : (
              <ul className="space-y-1.5">
                {skills.map((skill) => (
                  <li key={skill.id} className="rounded-lg border border-white/8 bg-white/[0.02] px-2 py-1.5">
                    <div className="flex items-start gap-1.5">
                      <input
                        type="checkbox"
                        checked={skill.enabled !== false}
                        onChange={(event) => void toggleSkill(skill.id ?? "", event.target.checked)}
                        title={skill.enabled === false ? "Skill desativada" : "Skill ativa"}
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-teal-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      />
                      <button
                        type="button"
                        onClick={() => setExpandedSkill((current) => (current === skill.id ? null : skill.id ?? null))}
                        aria-expanded={expandedSkill === skill.id}
                        className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        <span className={`block truncate text-[12px] ${skill.enabled === false ? "text-muted-foreground line-through" : "text-foreground/90"}`}>
                          {skill.name}
                        </span>
                        <span className="block truncate text-[10.5px] text-muted-foreground">
                          {skill.quality === "modelo" ? "escrita pelo modelo" : "heurística"} · {skill.uses} usos
                          {skill.tools?.length ? ` · ${skill.tools.slice(0, 3).join(", ")}` : ""}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeSkill(skill.id ?? "")}
                        aria-label={`Apagar a skill «${skill.name}»`}
                        className="rounded-md p-1 text-muted-foreground transition hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    {expandedSkill === skill.id ? (
                      <div className="mt-1.5">
                        {skill.when ? <p className="mb-1 text-[11px] text-muted-foreground">{skill.when}</p> : null}
                        <ol className="list-decimal space-y-0.5 pl-4 text-[11px] text-muted-foreground">
                          {(skill.steps ?? []).map((step) => (
                            <li key={step}>{step}</li>
                          ))}
                        </ol>
                        {skill.checks?.length ? (
                          <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                            Verificações: {skill.checks.join(" · ")}
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>

        {/* Conversa: respostas e caixa de pergunta (sempre visível — a lista rola por dentro). */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="glass-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
            <div className="flex min-h-0 flex-1 flex-col space-y-4 overflow-y-auto p-3">
              {turns.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-violet-300 via-purple-500 to-fuchsia-600 text-white shadow-lg shadow-violet-500/25">
                    <Compass size={22} />
                  </span>
                  <div className="max-w-md">
                    <h2 className="text-[15px] font-semibold">Pergunte o que quer investigar</h2>
                    <p className="mt-1 text-[12.5px] text-muted-foreground">
                      O Hermes junta o que a plataforma já sabe sobre o tema — contratos, empresas, documentos e
                      notícias — com as fontes abertas, e responde com citações que pode confirmar.
                    </p>
                  </div>
                  <div className="flex flex-wrap justify-center gap-2">
                    {EXAMPLES.map((example) => (
                      <button
                        key={example}
                        type="button"
                        onClick={() => void submit(example)}
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:border-violet-400/40 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {turns.map((turn) => (
                <article key={turn.id} className="space-y-2">
                  <div className="flex justify-end">
                    <p className="max-w-[80%] rounded-2xl bg-white/[0.07] px-3.5 py-2 text-[13px] text-foreground">
                      {turn.question}
                    </p>
                  </div>

                  {turn.error ? (
                    <div className="flex items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 p-3 text-[12.5px] text-rose-200">
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                      <span>{turn.error}</span>
                    </div>
                  ) : null}

                  {turn.answer ? (
                    <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-3.5">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${
                            MODE_TONE[turn.answer.mode] ?? "border-white/10 bg-white/5 text-muted-foreground"
                          }`}
                        >
                          {MODE_LABEL[turn.answer.mode] ?? turn.answer.mode}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                          {turn.answer.depth_label ?? turn.answer.depth}
                        </span>
                        <span className="text-[10.5px] text-muted-foreground">
                          {turn.answer.evidence.length} evidências · {turn.answer.stats.sources_with_results}/
                          {turn.answer.stats.sources_queried} fontes · {formatMs(turn.answer.stats.ms)}
                        </span>
                        <div className="ml-auto flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => void copyAnswer(turn.answer as DisplayAnswer)}
                            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                          >
                            {copied === turn.answer.id ? <Check size={11} /> : <Copy size={11} />}
                            Copiar
                          </button>
                          <button
                            type="button"
                            onClick={() => void openInOffice(turn.answer as DisplayAnswer)}
                            disabled={!user || busy === turn.answer.id}
                            title={user ? "Guardar no Office" : "Entrar na plataforma para guardar no Office"}
                            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                          >
                            {busy === turn.answer.id ? <Loader2 size={11} className="animate-spin" /> : <FileText size={11} />}
                            Office
                          </button>
                        </div>
                      </div>

                      {/* Skill aplicada: o método que guiou a resposta. */}
                      {turn.answer.skill?.name ? (
                        <details className="mb-2 rounded-xl border border-teal-400/20 bg-teal-400/[0.06] px-2.5 py-1.5">
                          <summary className="cursor-pointer text-[11.5px] text-teal-200">
                            🧭 Skill: {turn.answer.skill.name}
                            {turn.answer.skill.created
                              ? " · criada agora"
                              : turn.answer.skill.merged
                                ? " · fundida na biblioteca"
                                : ` · ${turn.answer.skill.uses} usos`}
                          </summary>
                          {turn.answer.skill.when ? (
                            <p className="mt-1 text-[11px] text-muted-foreground">{turn.answer.skill.when}</p>
                          ) : null}
                          <ol className="mt-1.5 list-decimal space-y-0.5 pl-4 text-[11px] text-muted-foreground">
                            {(turn.answer.skill.steps ?? []).map((step) => (
                              <li key={step}>{step}</li>
                            ))}
                          </ol>
                          {turn.answer.skill.checks?.length ? (
                            <p className="mt-1 text-[10.5px] text-muted-foreground/80">
                              Verificações: {turn.answer.skill.checks.join(" · ")}
                            </p>
                          ) : null}
                        </details>
                      ) : null}

                      <div className="prose-invert max-w-none text-[13px] leading-relaxed text-foreground/95 [&_a]:text-teal-300 [&_li]:my-1 [&_ol]:my-2 [&_p]:my-2 [&_ul]:my-2">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.answer.text}</ReactMarkdown>
                      </div>

                      {turn.answer.steps.length > 1 ? (
                        <div className="mt-3">
                          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            Sub-perguntas
                          </p>
                          <div className="flex flex-wrap gap-1.5">
                            {turn.answer.steps.map((step) => (
                              <span
                                key={step.id}
                                className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground"
                                title={`${step.question} · ${formatMs(step.ms)}`}
                              >
                                {step.focus} · {step.items}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {turn.answer.metrics.length ? (
                        <div className="mt-3 space-y-1.5">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            Indicadores
                          </p>
                          <MetricsTable metrics={turn.answer.metrics} />
                        </div>
                      ) : null}

                      {turn.answer.evidence.length ? (
                        <div className="mt-3 space-y-1.5">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            Evidências
                          </p>
                          <EvidenceList evidence={turn.answer.evidence} />
                        </div>
                      ) : null}

                      {turn.answer.followups.length ? (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {turn.answer.followups.map((item) => (
                            <button
                              key={item}
                              type="button"
                              onClick={() => void submit(item)}
                              className="rounded-full border border-violet-400/25 bg-violet-400/8 px-2.5 py-1 text-[11.5px] text-violet-100 transition hover:border-violet-400/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                            >
                              {item}
                            </button>
                          ))}
                        </div>
                      ) : null}

                      {turn.answer.notes.length || turn.answer.warnings.length ? (
                        <ul className="mt-3 space-y-1 border-t border-white/8 pt-2 text-[11px] text-muted-foreground">
                          {turn.answer.notes.map((item) => (
                            <li key={item} className="flex items-start gap-1.5">
                              <Info size={11} className="mt-0.5 shrink-0" />
                              <span>{item}</span>
                            </li>
                          ))}
                          {turn.answer.warnings.map((item) => (
                            <li key={item} className="flex items-start gap-1.5 text-amber-200/90">
                              <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  {!turn.answer && !turn.error ? (
                    <div className="flex items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.02] px-3.5 py-3 text-[12.5px] text-muted-foreground">
                      <Loader2 size={14} className="animate-spin text-violet-300" />
                      A planear a investigação, recolher evidências e redigir a resposta…
                    </div>
                  ) : null}
                </article>
              ))}
              <div ref={bottomRef} />
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit(question);
              }}
              className="shrink-0 border-t border-white/8 bg-white/[0.02] p-2.5"
            >
              {error ? (
                <div className="mb-2 flex items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                  <span className="flex-1">{error}</span>
                  <button
                    type="button"
                    onClick={() => setError(null)}
                    aria-label="Fechar aviso"
                    className="rounded-md p-0.5 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                  >
                    <X size={12} />
                  </button>
                </div>
              ) : null}
              {notice ? (
                <div className="mb-2 flex items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 py-1.5 text-[12px] text-teal-200">
                  <Check size={12} />
                  {notice}
                </div>
              ) : null}
              <div className="flex items-end gap-2">
                <label className="sr-only" htmlFor="hermes-question">
                  Pergunta para o Hermes
                </label>
                <textarea
                  id="hermes-question"
                  ref={inputRef}
                  rows={1}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                      event.preventDefault();
                      void submit(question);
                    }
                  }}
                  placeholder="Pergunte sobre contratos, empresas, setores, indicadores… (Ctrl+Enter envia)"
                  className={`${inputClass} max-h-40 min-h-[42px] resize-y`}
                />
                <button
                  type="submit"
                  disabled={loading || !question.trim()}
                  className="inline-flex h-[42px] shrink-0 items-center gap-1.5 rounded-xl bg-gradient-to-r from-violet-400 to-fuchsia-600 px-3.5 text-[12.5px] font-medium text-white transition disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
                >
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {loading ? "A investigar…" : "Investigar"}
                </button>
              </div>
              <p className="mt-1.5 text-[10.5px] text-muted-foreground">
                {activeSources.length} fontes · modo {meta?.depths.find((item) => item.id === depth)?.label.toLowerCase() ?? depth} ·
                resposta {backendChip?.kind === "cloud" ? "redigida por IA" : "factual"} com citações [n]
              </p>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
