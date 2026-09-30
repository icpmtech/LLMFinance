/**
 * Núcleo da conversa do Jarvis — partilhado pela página `/jarvis` e pelo
 * widget flutuante.
 *
 * Aqui vive tudo o que é preciso para uma conversa com o Jarvis funcionar:
 *
 * - `useJarvisChat` — conduz o streaming (`/jarvis/ask/stream`), junta os passos
 *   à medida que chegam, guarda o turno no histórico e manda falar a resposta;
 * - `JarvisThread` — desenha os turnos (pergunta, rasto dos passos, resposta,
 *   fontes, sugestões) e o turno a decorrer;
 * - `JarvisComposer` — o microfone e a caixa de texto.
 *
 * A página e o widget são só molduras diferentes à volta disto: a página tem a
 * órbita grande e o painel de ferramentas; o widget é o botão que acompanha a
 * plataforma. Assim os dois comportam-se exatamente igual.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Aperture,
  ArrowUpRight,
  AudioLines,
  Check,
  ChevronDown,
  ExternalLink,
  Lightbulb,
  Loader2,
  Mic,
  MicOff,
  RotateCcw,
  Send,
  Server,
  Sparkle,
  Square,
  Volume2,
  Zap,
} from "lucide-react";

import {
  loadJarvisHistory,
  runJarvisAction,
  saveJarvisTurn,
  streamJarvis,
  subscribeJarvisHistory,
  type JarvisAction,
  type JarvisSkill,
  type JarvisSource,
  type JarvisStep,
  type JarvisTurn,
} from "../../jarvisApi";

/* ------------------------------------------------------------------- tipos */

export type PendingTurn = {
  id: string;
  question: string;
  steps: JarvisStep[];
  tools: { tool: string; label: string; state: "a_correr" | "ok" | "falhou"; error?: string }[];
  skill?: JarvisSkill | null;
  plan?: string[];
  planReason?: string | null;
  answer?: string;
  speech?: string;
  sources: JarvisSource[];
  suggestions: string[];
  actions: JarvisAction[];
};

export type JarvisVoiceHandle = {
  speak: (text: string, options?: { voice?: string; useServer?: boolean }) => Promise<void> | void;
  stopSpeaking: () => void;
  stop: () => void;
};

export type UseJarvisChatOptions = {
  depth: "rapida" | "profunda";
  autoSpeak: boolean;
  voiceId: string;
  serverVoice: boolean;
  voice: JarvisVoiceHandle;
  models?: { provider?: string | null; model?: string | null; kind?: string };
  /**
   * Executa uma ação proposta (confirmada pelo utilizador, por clique ou por
   * voz). Recebe o turno de onde veio, para reconstruir o corpo da criação.
   * Devolve uma mensagem curta para o Jarvis dizer o que fez.
   */
  executeAction?: (
    action: JarvisAction,
    context: { question: string; answer: string },
  ) => Promise<string | void>;
  onTurnDone?: (turn: JarvisTurn) => void;
};

/**
 * Expressões que valem como «sim» numa conversa por voz.
 *
 * Sem isto, quem fala não teria forma de confirmar uma proposta: o Jarvis lê
 * «diga confirmar» e tem de perceber a resposta.
 */
const CONFIRMATIONS = (
  "confirmar, confirma, confirmo, sim, avanca, avança, pode, pode ser, guarda, guardar, grava, "
  + "salva, cria, faz isso, esta bem, está bem, ok, certo, exatamente"
).split(", ");

/** `true` quando a pergunta é uma confirmação curta («sim», «confirma»). */
export function isConfirmation(text: string): boolean {
  const folded = text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[!.?,;:\s]+/g, " ")
    .trim();
  if (!folded || folded.split(" ").length > 4) return false;
  return CONFIRMATIONS.some((word) => folded === word || folded.startsWith(`${word} `));
}

/**
 * Chave única de uma ação **dentro da conversa**.
 *
 * O id do catálogo repete-se em vários turnos («guarda isto no office» duas
 * vezes é a mesma ação `guardar_office`). Sem o turno na chave, confirmar uma
 * marcaria as outras como feitas — e a segunda gravação seria bloqueada.
 */
export function actionKey(turnId: string, actionId: string): string {
  return `${turnId}::${actionId}`;
}

const BACKEND_KEY = "finance-llm-backend";

/** Modelo/fornecedor escolhido no chat (o Jarvis usa o mesmo). */
export function readJarvisBackend(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const stored = window.localStorage.getItem(BACKEND_KEY) || "";
  // `gpt2` é o modelo local: é melhor deixar o servidor escolher o predefinido
  // da conta (que pode ser um fornecedor cloud).
  return stored && stored !== "gpt2" ? stored : undefined;
}

export function generateJarvisId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/* -------------------------------------------------------------------- hook */

export function useJarvisChat(options: UseJarvisChatOptions) {
  const { depth, voice } = options;

  const [turns, setTurns] = useState<JarvisTurn[]>(() => loadJarvisHistory());
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ id: string; state: "a_correr" | "ok" | "falhou"; message?: string } | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const busy = pending !== null;

  // O histórico é partilhado entre a página e o widget.
  useEffect(() => subscribeJarvisHistory((next) => setTurns(next)), []);

  const optionsRef = useRef(options);
  optionsRef.current = options;
  const onTurnDoneRef = useRef(options.onTurnDone);
  onTurnDoneRef.current = options.onTurnDone;
  // O histórico também é lido dentro de callbacks estáveis (a confirmação por
  // voz): uma ref evita recriar o callback a cada turno.
  const turnsRef = useRef<JarvisTurn[]>([]);
  turnsRef.current = turns;
  /** Ids de ações já executadas nesta sessão (evita duplicados por voz). */
  const doneActionsRef = useRef<Set<string>>(new Set());

  const send = useCallback(
    (text: string) => {
      const clean = text.trim();
      if (!clean) return;
      if (cancelRef.current) return; // já há um pedido em curso

      const current = optionsRef.current;
      current.voice.stopSpeaking();
      setError(null);
      const history = loadJarvisHistory()
        .slice(0, 8)
        .flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          { role: "assistant" as const, content: turn.answer },
        ])
        .reverse();

      const draft: PendingTurn = {
        id: generateJarvisId(),
        question: clean,
        steps: [],
        tools: [],
        sources: [],
        suggestions: [],
        actions: [],
      };
      setPending(draft);
      current.voice.stop();

      let answer = "";
      let speech = "";
      let sources: JarvisSource[] = [];
      let suggestions: string[] = [];
      let skill: JarvisSkill | null = null;
      let steps: JarvisStep[] = [];
      let actions: JarvisAction[] = [];

      cancelRef.current = streamJarvis(
        { question: clean, depth: current.depth, backend: readJarvisBackend(), history },
        (event) => {
          switch (event.type) {
            case "passo":
              steps = [...steps, event.step];
              setPending((state) => (state ? { ...state, steps: [...state.steps, event.step] } : state));
              break;
            case "plano":
              setPending((state) =>
                state ? { ...state, plan: event.tools, planReason: event.reason ?? null } : state,
              );
              break;
            case "ferramenta":
              setPending((state) => {
                if (!state) return state;
                const others = state.tools.filter((item) => item.tool !== event.tool);
                return {
                  ...state,
                  tools: [
                    ...others,
                    { tool: event.tool, label: event.label, state: event.state, error: event.error },
                  ],
                };
              });
              break;
            case "skill":
              skill = event.skill;
              setPending((state) => (state ? { ...state, skill: event.skill } : state));
              break;
            case "resposta":
              answer = event.answer;
              speech = event.speech;
              sources = event.sources;
              suggestions = event.suggestions;
              actions = event.actions || [];
              skill = event.skill ?? skill;
              if (event.steps?.length) steps = event.steps;
              setPending((state) =>
                state
                  ? {
                      ...state,
                      answer: event.answer,
                      speech: event.speech,
                      sources: event.sources,
                      suggestions: event.suggestions,
                      actions: event.actions || [],
                      skill: event.skill ?? state.skill,
                      steps: event.steps?.length ? event.steps : state.steps,
                    }
                  : state,
              );
              break;
            case "acao":
              actions = [...actions, event.action];
              setPending((state) => (state ? { ...state, actions: [...state.actions, event.action] } : state));
              break;
            case "fim": {
              const finished: JarvisTurn = {
                id: draft.id,
                question: clean,
                answer,
                speech,
                steps,
                sources,
                suggestions,
                actions,
                skill,
                elapsed_seconds: event.elapsed_seconds,
                at: new Date().toISOString(),
              };
              saveJarvisTurn(finished);
              setPending(null);
              cancelRef.current = null;
              onTurnDoneRef.current?.(finished);
              if (optionsRef.current.autoSpeak && speech) {
                void optionsRef.current.voice.speak(speech, {
                  voice: optionsRef.current.voiceId,
                  useServer: optionsRef.current.serverVoice,
                });
              }
              break;
            }
            case "erro":
              setError(event.detail);
              setPending(null);
              cancelRef.current = null;
              break;
            default:
              break;
          }
        },
        (err) => {
          setError(err.message);
          setPending(null);
          cancelRef.current = null;
        },
      );
    },
    [depth],
  );

  const stop = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    setPending(null);
    setError("Geração interrompida.");
  }, []);

  /**
   * Executa uma ação proposta.
   *
   * A navegação é do cliente (`executeAction` trata dela); as criações vão pelo
   * servidor. Nos dois casos só corre depois de o utilizador confirmar — por
   * clique no botão, ou por voz («sim», «confirma», «guarda»).
   */
  const runAction = useCallback(async (action: JarvisAction, turn?: JarvisTurn) => {
    const execute = optionsRef.current.executeAction;
    if (!execute) return;
    const source = turn ?? turnsRef.current[0];
    const key = actionKey(source?.id ?? "", action.id);
    setActionState({ id: key, state: "a_correr" });
    try {
      const message = await execute(action, {
        question: source?.question ?? "",
        answer: source?.answer ?? "",
      });
      setActionState({ id: key, state: "ok", message: typeof message === "string" ? message : undefined });
      doneActionsRef.current.add(key);
      if (typeof message === "string" && message) {
        if (optionsRef.current.autoSpeak) void optionsRef.current.voice.speak(message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível executar a ação.";
      setActionState({ id: key, state: "falhou", message });
      setError(message);
    }
  }, []);

  /**
   * «sim» / «confirma» dito em voz alta executa a última proposta.
   *
   * Só quando existe exatamente **uma** proposta de criação por confirmar: com
   * duas ou mais, adivinhar seria pior do que perguntar.
   */
  const confirmLastAction = useCallback((): boolean => {
    // Procura a proposta mais recente ainda por confirmar, do turno mais novo
    // para o mais antigo. Um «sim» deve valer para a última proposta da
    // conversa, mesmo que o utilizador tenha escrito outra coisa entretanto —
    // mas nunca adivinha quando há duas propostas no mesmo turno.
    let target: { action: JarvisAction; turn: JarvisTurn } | null = null;
    for (const turn of turnsRef.current) {
      const candidates = (turn.actions || []).filter(
        (action) =>
          action.requires_confirmation && !doneActionsRef.current.has(actionKey(turn.id, action.id)),
      );
      if (candidates.length > 1) return false;
      if (candidates.length === 1) {
        target = { action: candidates[0], turn };
        break;
      }
    }
    if (!target) return false;
    void runAction(target.action, target.turn);
    return true;
  }, [runAction]);

  const askAgain = useCallback(
    (text: string) => {
      voice.stopSpeaking();
      if (isConfirmation(text) && confirmLastAction()) return;
      send(text);
    },
    [confirmLastAction, send, voice],
  );

  const lastAnswer = turns[0]?.answer ?? pending?.answer ?? "";

  return {
    turns,
    pending,
    error,
    setError,
    busy,
    send,
    stop,
    askAgain,
    runAction,
    actionState,
    lastAnswer,
  } as const;
}

/**
 * Constrói o executor de ações do Jarvis.
 *
 * A divisão é esta: **navegar** é do cliente (a vista muda aqui), **criar** é do
 * servidor (`/jarvis/actions/run`, com o token do utilizador). O executor
 * devolve a frase que o Jarvis diz depois de cumprir — para um utilizador de
 * voz saber que aconteceu.
 */
export function useJarvisActionRunner(options: {
  onNavigate?: (action: JarvisAction) => void;
  onCreated?: (action: JarvisAction, message: string) => void;
}): (action: JarvisAction, context: { question: string; answer: string }) => Promise<string> {
  const navigateRef = useRef(options.onNavigate);
  navigateRef.current = options.onNavigate;
  const onCreatedRef = useRef(options.onCreated);
  onCreatedRef.current = options.onCreated;

  return useCallback(async (action, context) => {
    if (action.kind === "navigate") {
      const go = navigateRef.current;
      if (!go) throw new Error("Não consigo mudar de página a partir daqui.");
      go(action);
      return `${action.label.replace(/^Abrir\s+/i, "")} — a abrir.`;
    }

    const result = await runJarvisAction({
      action: action.id,
      question: context.question,
      answer: context.answer,
      params: action.params,
    });
    if (!result.ok) throw new Error(result.error || `A operação ${result.operation} falhou.`);
    const message = `${action.label}: feito.`;
    onCreatedRef.current?.(action, message);
    return message;
  }, []);
}

/* ---------------------------------------------------------------- desenho */

const STEP_ICONS: Record<string, typeof Sparkle> = {
  ouvir: AudioLines,
  modelo: Zap,
  skill: Lightbulb,
  plano: Aperture,
  ferramenta: Server,
  resultado: Check,
  responder: Sparkle,
};

export function SkillChip({ skill }: { skill: JarvisSkill }) {
  const [open, setOpen] = useState(false);
  const steps = skill.steps || [];
  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/25 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200 transition hover:bg-amber-400/15"
        title={skill.summary || "Método seguido pelo Jarvis"}
      >
        <Lightbulb size={12} />
        <span className="max-w-[22rem] truncate">Skill: {skill.title || skill.id}</span>
        {skill.created ? <span className="text-amber-200/70">· criada agora</span> : null}
        {steps.length ? <ChevronDown size={11} className={open ? "rotate-180 transition" : "transition"} /> : null}
      </button>
      {open && steps.length ? (
        <ol className="mt-1.5 space-y-0.5 rounded-lg border border-white/8 bg-white/[0.02] p-2 text-[11.5px] text-muted-foreground">
          {steps.map((step, index) => (
            <li key={step} className="flex items-start gap-1.5">
              <span className="mt-0.5 text-amber-200/70">{index + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export function StepRow({ step }: { step: JarvisStep }) {
  const Icon = STEP_ICONS[step.kind] || Sparkle;
  const tone =
    step.kind === "resultado" && step.ok === false
      ? "text-rose-300"
      : step.kind === "skill"
        ? "text-amber-200"
        : step.kind === "ferramenta"
          ? "text-cyan-200"
          : "text-muted-foreground";
  return (
    <li className="flex items-start gap-2 text-[11.5px]">
      <Icon size={12} className={`mt-0.5 shrink-0 ${tone}`} />
      <span className={tone}>{step.label}</span>
      {step.tool ? (
        <code className="ml-auto shrink-0 rounded bg-white/[0.05] px-1 text-[10px] text-muted-foreground">
          {step.tool}
        </code>
      ) : null}
    </li>
  );
}

/** O rasto de uma resposta já concluída: que gateways foram usados e porquê. */
export function TraceBlock({ steps, compact = false }: { steps: JarvisStep[]; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2.5">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground transition hover:text-foreground"
      >
        <Aperture size={11} />
        Como cheguei aqui ({steps.length} passos)
        <ChevronDown size={11} className={open ? "rotate-180 transition" : "transition"} />
      </button>
      {open ? (
        <ol className={`mt-1.5 space-y-0.5 rounded-lg border border-white/8 bg-white/[0.02] p-2 ${compact ? "max-h-56 overflow-y-auto" : ""}`}>
          {steps.map((step, index) => (
            <StepRow key={`${step.label}-${index}`} step={step} />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export function PendingCard({ turn, compact = false }: { turn: PendingTurn; compact?: boolean }) {
  const window = compact ? 6 : 9;
  return (
    <article className="space-y-2">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md border border-cyan-400/25 bg-cyan-400/10 px-3.5 py-2.5 text-[12.5px] text-cyan-50">
          {turn.question}
        </div>
      </div>
      <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-3.5">
        {turn.steps.length ? (
          <ol className="space-y-0.5">
            {turn.steps.slice(-window).map((step, index) => (
              <StepRow key={`${step.label}-${index}`} step={step} />
            ))}
          </ol>
        ) : (
          <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Loader2 size={13} className="animate-spin" />
            A preparar o plano…
          </div>
        )}
        {turn.answer ? (
          <div className="mt-3 border-t border-white/8 pt-2.5">
            <Markdownish text={turn.answer} />
          </div>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Renderizador leve: o Jarvis responde em texto simples com listas `-`, por
 * isso não vale a pena arrastar o ReactMarkdown (e as citações `[n]` ficam
 * realçadas). Linhas começadas por `-` viram itens de lista.
 */
export function Markdownish({ text }: { text: string }) {
  const blocks = useMemo(() => text.split(/\n{2,}/).filter((block) => block.trim()), [text]);
  return (
    <div className="space-y-2 text-[12.5px] leading-relaxed text-foreground/90">
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        const isList = lines.every((line) => /^\s*[-*•]\s+/.test(line));
        if (isList) {
          return (
            <ul key={index} className="space-y-1 pl-1">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex} className="flex items-start gap-1.5">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400/70" />
                  <span>{highlightCitations(line.replace(/^\s*[-*•]\s+/, ""))}</span>
                </li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{highlightCitations(block)}</p>;
      })}
    </div>
  );
}

function highlightCitations(text: string) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, index) =>
    /^\[\d+\]$/.test(part) ? (
      <sup key={index} className="mx-0.5 rounded bg-cyan-400/15 px-1 text-[10px] font-medium text-cyan-200">
        {part}
      </sup>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

/**
 * Ações propostas pelo Jarvis.
 *
 * Nada acontece sozinho: cada ação é um botão. As de **navegação** levam o
 * utilizador ao sítio pedido; as de **criação** escrevem na plataforma e por
 * isso aparecem marcadas como tal — e podem ser confirmadas por voz («sim»).
 */
export function ActionBar({
  actions,
  state,
  onRun,
  scope,
  compact = false,
}: {
  actions: JarvisAction[];
  state?: { id: string; state: "a_correr" | "ok" | "falhou"; message?: string } | null;
  onRun: (action: JarvisAction) => void;
  /** Id do turno dono destas ações (ver `actionKey`). */
  scope: string;
  compact?: boolean;
}) {
  if (!actions.length) return null;
  return (
    <div className="mt-3 border-t border-white/8 pt-2.5">
      <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Zap size={11} />
        O Jarvis pode fazer isto por si
      </h3>
      <div className={`mt-1.5 grid gap-1.5 ${compact ? "" : "@2xl:grid-cols-2"}`}>
        {actions.map((action) => {
          const current = state?.id === actionKey(scope, action.id) ? state : null;
          const busy = current?.state === "a_correr";
          const done = current?.state === "ok";
          return (
            <button
              key={action.id}
              type="button"
              onClick={() => onRun(action)}
              disabled={busy || done}
              title={action.description}
              className={`flex items-start gap-2 rounded-xl border px-2.5 py-2 text-left transition disabled:opacity-70 ${
                done
                  ? "border-emerald-400/30 bg-emerald-400/10"
                  : action.kind === "create"
                    ? "border-violet-400/25 bg-violet-400/[0.07] hover:border-violet-300/50 hover:bg-violet-400/15"
                    : "border-cyan-400/25 bg-cyan-400/[0.07] hover:border-cyan-300/50 hover:bg-cyan-400/15"
              }`}
            >
              {busy ? (
                <Loader2 size={13} className="mt-0.5 shrink-0 animate-spin text-cyan-300" />
              ) : done ? (
                <Check size={13} className="mt-0.5 shrink-0 text-emerald-300" />
              ) : action.kind === "create" ? (
                <Sparkle size={13} className="mt-0.5 shrink-0 text-violet-300" />
              ) : (
                <ArrowUpRight size={13} className="mt-0.5 shrink-0 text-cyan-300" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[11.5px] font-medium text-foreground/90">
                  {done ? "Feito: " : ""}
                  {action.label}
                </span>
                <span className="block truncate text-[10.5px] text-muted-foreground/80">
                  {current?.message || action.description}
                </span>
              </span>
              {action.kind === "create" && !done ? (
                <span className="mt-0.5 shrink-0 rounded bg-violet-400/15 px-1 text-[9.5px] uppercase tracking-wide text-violet-200">
                  escreve
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      {actions.some((action) => action.requires_confirmation) ? (
        <p className="mt-1.5 flex items-center gap-1.5 text-[10.5px] text-muted-foreground/70">
          <Mic size={10} />
          Pode confirmar por voz: diga «sim» ou «confirmar».
        </p>
      ) : null}
    </div>
  );
}

/** Uma resposta já concluída, com rasto, fontes e ações. */
export function TurnCard({
  turn,
  compact = false,
  actionState,
  onSpeak,
  onRepeat,
  onAsk,
  onAction,
}: {
  turn: JarvisTurn;
  compact?: boolean;
  actionState?: { id: string; state: "a_correr" | "ok" | "falhou"; message?: string } | null;
  onSpeak: () => void;
  onRepeat: () => void;
  onAsk: (text: string) => void;
  onAction?: (action: JarvisAction, turn: JarvisTurn) => void;
}) {
  return (
    <article className="space-y-2">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md border border-cyan-400/25 bg-cyan-400/10 px-3.5 py-2.5 text-[12.5px] text-cyan-50">
          {turn.question}
        </div>
      </div>
      <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-3.5">
        <Markdownish text={turn.answer} />

        {turn.steps?.length ? <TraceBlock steps={turn.steps} compact={compact} /> : null}

        {turn.actions?.length && onAction ? (
          <ActionBar
            actions={turn.actions}
            state={actionState}
            scope={turn.id}
            onRun={(action) => onAction(action, turn)}
            compact={compact}
          />
        ) : null}

        {turn.sources?.length ? (
          <div className="mt-3 border-t border-white/8 pt-2.5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Fontes ({turn.sources.length})
            </h3>
            <ul className="mt-1.5 space-y-1">
              {turn.sources.slice(0, compact ? 4 : 8).map((source, index) => (
                <li key={`${source.url || source.label}-${index}`} className="flex items-start gap-1.5 text-[11.5px]">
                  <span className="mt-0.5 shrink-0 rounded bg-white/[0.06] px-1 text-[10px] text-muted-foreground">
                    {source.origin}
                  </span>
                  {source.url ? (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-start gap-1 text-cyan-200 hover:text-cyan-100 hover:underline"
                    >
                      <span className="line-clamp-2">{source.label}</span>
                      <ExternalLink size={11} className="mt-0.5 shrink-0" />
                    </a>
                  ) : (
                    <span className="text-muted-foreground">{source.label}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {turn.skill ? <SkillChip skill={turn.skill} /> : null}
          {typeof turn.elapsed_seconds === "number" ? (
            <span className="text-[11px] text-muted-foreground">{turn.elapsed_seconds}s</span>
          ) : null}
          <button
            type="button"
            onClick={onSpeak}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/[0.07]"
          >
            <Volume2 size={12} />
            Ouvir
          </button>
          <button
            type="button"
            onClick={onRepeat}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] text-muted-foreground transition hover:bg-white/[0.07]"
          >
            <RotateCcw size={12} />
            Repetir
          </button>
        </div>

        {turn.suggestions?.length ? (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {turn.suggestions.slice(0, compact ? 2 : 4).map((idea) => (
              <button
                key={idea}
                type="button"
                onClick={() => onAsk(idea)}
                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-cyan-400/30 hover:bg-cyan-400/10 hover:text-cyan-100"
              >
                <ArrowUpRight size={11} />
                {idea}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

/* --------------------------------------------------------------- compositor */

export function JarvisComposer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  listening,
  canListen,
  onToggleMic,
  placeholder,
  error,
  onDismissError,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  listening: boolean;
  canListen: boolean;
  onToggleMic: () => void;
  placeholder?: string;
  error?: string | null;
  onDismissError?: () => void;
}) {
  return (
    <div className="shrink-0 border-t border-white/8 bg-white/[0.02] px-3 py-2.5">
      {error ? (
        <div className="mb-2 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
          <span className="flex-1">{error}</span>
          {onDismissError ? (
            <button type="button" onClick={onDismissError} className="text-rose-200/80 hover:text-rose-100">
              ✕
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={onToggleMic}
          disabled={!canListen}
          title={
            canListen
              ? listening
                ? "Parar de ouvir"
                : "Falar com o Jarvis"
              : "Este browser não tem reconhecimento de voz e o servidor não tem transcrição"
          }
          className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border transition disabled:opacity-40 ${
            listening
              ? "border-amber-400/40 bg-amber-400/15 text-amber-200"
              : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
          }`}
        >
          {canListen ? <Mic size={17} /> : <MicOff size={17} />}
        </button>

        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
          rows={1}
          placeholder={listening ? "A ouvir… fale agora" : placeholder || "Pergunte ao Jarvis (Enter envia)"}
          className="max-h-32 min-h-10 flex-1 resize-none rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-[12.5px] text-foreground outline-none transition placeholder:text-muted-foreground/70 focus:border-cyan-400/40"
        />

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 text-[12.5px] text-rose-200 transition hover:bg-rose-400/15"
          >
            <Square size={14} />
            Parar
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!value.trim()}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 px-3.5 text-[12.5px] font-medium text-white shadow-lg shadow-sky-500/20 transition hover:from-sky-400 hover:to-indigo-500 disabled:opacity-40"
          >
            <Send size={14} />
            Perguntar
          </button>
        )}
      </div>
    </div>
  );
}

/** Lista de turnos (a decorrer + histórico). */
export function JarvisThread({
  turns,
  pending,
  compact = false,
  actionState,
  onSpeak,
  onRepeat,
  onAsk,
  onAction,
}: {
  turns: JarvisTurn[];
  pending: PendingTurn | null;
  compact?: boolean;
  actionState?: { id: string; state: "a_correr" | "ok" | "falhou"; message?: string } | null;
  onSpeak: (turn: JarvisTurn) => void;
  onRepeat: (question: string) => void;
  onAsk: (text: string) => void;
  onAction?: (action: JarvisAction, turn: JarvisTurn) => void;
}) {
  // O histórico é **guardado** do mais recente para o mais antigo (é essa a
  // ordem que a confirmação por voz percorre), mas no ecrã tem de ser o
  // contrário: a conversa lê-se de cima para baixo, do mais antigo para o mais
  // recente. O turno a decorrer fica no fim, onde a resposta vai aparecer.
  const ordered = useMemo(() => [...turns].reverse(), [turns]);
  return (
    <>
      {ordered.map((turn) => (
        <TurnCard
          key={turn.id}
          turn={turn}
          compact={compact}
          actionState={actionState}
          onSpeak={() => onSpeak(turn)}
          onRepeat={() => onRepeat(turn.question)}
          onAsk={onAsk}
          onAction={onAction}
        />
      ))}
      {pending ? <PendingCard turn={pending} compact={compact} /> : null}
    </>
  );
}
