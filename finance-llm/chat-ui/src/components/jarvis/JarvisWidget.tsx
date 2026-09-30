/**
 * **Jarvis Widget** — o centro de inteligência do IQ OS, sempre à mão.
 *
 * Fica em qualquer página da plataforma como um botão flutuante (só o ícone) e
 * abre num painel de **Control Center**: o estado do sistema num relance
 * (modelo, gateways, ferramentas, voz), atalhos para os pedidos mais comuns e a
 * conversa completa — com passos, fontes e citações.
 *
 * É a mesma conversa da página `/jarvis` (o histórico é partilhado), mas sem
 * sair do sítio onde o utilizador está. Na página `/jarvis` o widget esconde-se,
 * porque aí já está a conversa toda.
 *
 * A voz está sempre disponível: o microfone no compositor e a leitura das
 * respostas em voz alta, com as mesmas preferências da página.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Aperture,
  Brain,
  ChevronDown,
  Globe2,
  Maximize2,
  Mic,
  Minus,
  Server,
  Volume2,
  VolumeX,
  X,
  Zap,
} from "lucide-react";

import JarvisOrb, { type JarvisOrbState } from "./JarvisOrb";
import { useJarvisVoice } from "./useJarvisVoice";
import {
  JarvisComposer,
  JarvisThread,
  generateJarvisId,
  readJarvisBackend,
  useJarvisActionRunner,
  useJarvisChat,
} from "./JarvisChat";
import {
  getJarvisMeta,
  jarvisPreferences,
  jarvisWidgetPrefs,
  type JarvisAction,
  type JarvisMeta,
} from "../../jarvisApi";

/** Atalhos do Control Center: o que se pede ao Jarvis com um clique. */
const QUICK_ACTIONS: { icon: typeof Zap; label: string; question: string }[] = [
  {
    icon: Aperture,
    label: "Maiores contratos",
    question: "Quais são os maiores contratos públicos assinados no último ano?",
  },
  {
    icon: Brain,
    label: "Ficha de empresa",
    question: "Dá-me a ficha de uma empresa com mais contratos com o Estado, com sinais de risco.",
  },
  {
    icon: Globe2,
    label: "Notícias de mercado",
    question: "Que notícias recentes explicam a evolução dos mercados esta semana?",
  },
  {
    icon: Server,
    label: "Estado do sistema",
    question: "Quantos contratos, empresas e documentos estão indexados na plataforma?",
  },
];

export default function JarvisWidget({
  hidden = false,
  onNavigate,
}: {
  hidden?: boolean;
  onNavigate?: (action: JarvisAction) => void;
}) {
  const [meta, setMeta] = useState<JarvisMeta | null>(null);
  const [prefs, setPrefs] = useState(() => jarvisPreferences.load());
  const [widget, setWidget] = useState(() => jarvisWidgetPrefs.load());
  const [question, setQuestion] = useState("");
  const [showStatus, setShowStatus] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const open = widget.open;

  useEffect(() => {
    getJarvisMeta(readJarvisBackend())
      .then(setMeta)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    jarvisPreferences.save(prefs);
  }, [prefs]);

  useEffect(() => {
    jarvisWidgetPrefs.save(widget);
  }, [widget]);

  const sendRef = useRef<(text: string) => void>(() => undefined);
  const reportErrorRef = useRef<(message: string) => void>(() => undefined);

  const voice = useJarvisVoice({
    language: "pt-PT",
    stt: meta?.voice.stt,
    tts: meta?.voice.tts,
    onTranscript: (text) => sendRef.current(text),
    onError: (message) => reportErrorRef.current(message),
  });

  // Ao navegar, o widget fecha para o utilizador ver a página de destino.
  const executeAction = useJarvisActionRunner({
    onNavigate: (action) => {
      onNavigate?.(action);
      setWidget((current) => ({ ...current, open: false }));
    },
  });

  const chat = useJarvisChat({
    depth: prefs.depth,
    autoSpeak: prefs.autoSpeak,
    voiceId: prefs.voice,
    serverVoice: prefs.serverVoice,
    voice,
    executeAction,
  });

  sendRef.current = chat.askAgain;
  reportErrorRef.current = chat.setError;

  const { turns, pending, busy, error } = chat;
  const hasConversation = turns.length > 0 || pending !== null;

  const orbState: JarvisOrbState = voice.listening
    ? "listening"
    : voice.speaking
      ? "speaking"
      : busy
        ? "thinking"
        : "idle";

  const stateLabel = useMemo(() => {
    if (voice.listening) return "A ouvir…";
    if (voice.speaking) return "A responder em voz alta";
    if (busy) {
      const last = pending?.steps[pending.steps.length - 1];
      return last ? last.label : "A pensar…";
    }
    return "Control Center pronto";
  }, [busy, pending, voice.listening, voice.speaking]);

  const toggle = useCallback(() => {
    setWidget((current) => ({ ...current, open: !current.open }));
    if (!open) {
      // Ao abrir, o foco vai para a caixa de texto (se não estiver a ouvir).
      window.setTimeout(() => {
        const node = document.getElementById("jarvis-widget-input") as HTMLTextAreaElement | null;
        node?.focus();
      }, 120);
    }
  }, [open]);

  const send = useCallback(
    (text: string) => {
      setQuestion("");
      // Passa por `askAgain`: um «sim» dito ou escrito confirma a proposta
      // pendente em vez de ser enviado como pergunta nova ao modelo.
      chat.askAgain(text);
    },
    [chat],
  );

  useEffect(() => {
    const node = scrollRef.current;
    if (node && open) node.scrollTop = node.scrollHeight;
  }, [turns.length, pending?.steps.length, pending?.answer, open]);

  // Esc fecha o painel; não se fecha enquanto o Jarvis estiver a responder.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (busy) return;
      setWidget((current) => ({ ...current, open: false }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy]);

  // Arrastar o botão (a posição fica guardada).
  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const x = Math.max(8, Math.min(window.innerWidth - 70, event.clientX - drag.dx));
      const y = Math.max(8, Math.min(window.innerHeight - 70, event.clientY - drag.dy));
      setWidget((current) => ({ ...current, x, y }));
    };
    const onUp = () => {
      dragRef.current = null;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  const startDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
  };

  if (hidden) return null;

  const style: React.CSSProperties = widget.x === null || widget.y === null
    ? {}
    : { left: widget.x, top: widget.y, right: "auto", bottom: "auto" };

  return (
    <>
      {/* Botão flutuante — só o ícone. */}
      {!open ? (
        <button
          ref={buttonRef}
          type="button"
          onPointerDown={startDrag}
          onClick={toggle}
          title="Jarvis — Control Center do IQ OS (pergunte qualquer coisa)"
          aria-label="Abrir o Jarvis"
          style={style}
          className="fixed bottom-[124px] right-4 z-[60] grid h-14 w-14 place-items-center rounded-full border border-cyan-400/30 bg-slate-950/85 shadow-2xl shadow-cyan-500/25 backdrop-blur transition hover:border-cyan-300/60 hover:shadow-cyan-400/40"
        >
          <span className="pointer-events-none absolute inset-0 rounded-full ring-1 ring-inset ring-white/10" />
          {busy || voice.listening || voice.speaking ? (
            <span className="pointer-events-none absolute inset-0 animate-ping rounded-full border border-cyan-300/40" />
          ) : null}
          <JarvisOrb state={orbState} level={voice.level} size={52} />
          {turns.length ? (
            <span className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-cyan-500 px-1 text-[10px] font-semibold text-slate-950">
              {turns.length > 9 ? "9+" : turns.length}
            </span>
          ) : null}
        </button>
      ) : null}

      {/* Painel do Control Center. */}
      {open ? (
        <section
          className="fixed bottom-[124px] right-4 z-[60] flex h-[min(640px,calc(100vh-160px))] w-[min(420px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-950/95 shadow-2xl shadow-black/60 backdrop-blur-xl"
          aria-label="Jarvis Control Center"
        >
          {/* Cabeçalho */}
          <header className="flex shrink-0 items-center gap-3 border-b border-white/8 bg-gradient-to-r from-cyan-500/10 via-transparent to-violet-500/10 px-3 py-2.5">
            <JarvisOrb state={orbState} level={voice.level} size={38} title={stateLabel} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-foreground">
                Jarvis
                <span className="rounded bg-white/[0.06] px-1 text-[9.5px] font-medium uppercase tracking-wide text-cyan-200/90">
                  Control Center
                </span>
              </p>
              <p className="truncate text-[10.5px] text-muted-foreground">{stateLabel}</p>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              <button
                type="button"
                onClick={() => setPrefs((current) => ({ ...current, autoSpeak: !current.autoSpeak }))}
                title={prefs.autoSpeak ? "Não ler as respostas em voz alta" : "Ler as respostas em voz alta"}
                className={`grid h-7 w-7 place-items-center rounded-lg transition ${
                  prefs.autoSpeak ? "text-teal-300 hover:bg-white/[0.06]" : "text-muted-foreground hover:bg-white/[0.06]"
                }`}
              >
                {prefs.autoSpeak ? <Volume2 size={14} /> : <VolumeX size={14} />}
              </button>
              <a
                href="/jarvis"
                title="Abrir na página completa"
                className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/[0.06] hover:text-foreground"
              >
                <Maximize2 size={13} />
              </a>
              <button
                type="button"
                onClick={toggle}
                title="Minimizar"
                className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/[0.06] hover:text-foreground"
              >
                <Minus size={14} />
              </button>
              <button
                type="button"
                onClick={() => {
                  chat.stop();
                  setWidget((current) => ({ ...current, open: false }));
                }}
                title="Fechar"
                className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/[0.06] hover:text-foreground"
              >
                <X size={14} />
              </button>
            </div>
          </header>

          {/* Faixa de estado — o que o sistema está a dar ao Jarvis agora. */}
          <div className="shrink-0 border-b border-white/8 bg-white/[0.012] px-3 py-2">
            <button
              type="button"
              onClick={() => setShowStatus((current) => !current)}
              className="flex w-full items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/80 transition hover:text-foreground"
            >
              <Zap size={10} />
              Estado do sistema
              <ChevronDown size={10} className={showStatus ? "rotate-180 transition" : "transition"} />
            </button>
            {showStatus ? (
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                <StatusCell
                  icon={Brain}
                  label="Modelo"
                  value={
                    meta?.model?.model
                      ? `${meta.model.model}`
                      : meta?.model?.kind === "cloud"
                        ? "modelo da conta"
                        : "factual"
                  }
                />
                <StatusCell icon={Zap} label="Ferramentas" value={`${meta?.tools.length ?? 0}`} />
                {(meta?.gateways || []).map((gateway) => (
                  <StatusCell
                    key={gateway.id}
                    icon={gateway.id === "hermes" ? Brain : gateway.id === "web" ? Globe2 : Server}
                    label={gateway.label}
                    value={`${gateway.tools}`}
                  />
                ))}
                <StatusCell
                  icon={Mic}
                  label="Voz"
                  value={
                    voice.canListen
                      ? voice.recognitionSupported
                        ? "microfone + fala"
                        : "microfone (servidor)"
                      : "só texto"
                  }
                />
              </div>
            ) : null}
          </div>

          {/* Conversa */}
          <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
            {!hasConversation ? (
              <div className="space-y-2.5">
                <p className="text-[12px] leading-relaxed text-muted-foreground">
                  {meta?.about.description ||
                    "Pergunte o que quiser sobre os dados do IQ OS — contratos, empresas, mercados, documentos ou a web."}
                </p>
                <div className="grid grid-cols-2 gap-1.5">
                  {QUICK_ACTIONS.map((action) => (
                    <button
                      key={action.label}
                      type="button"
                      onClick={() => send(action.question)}
                      className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/[0.025] px-2.5 py-2 text-left text-[11.5px] text-muted-foreground transition hover:border-cyan-400/30 hover:bg-cyan-400/10 hover:text-cyan-100"
                    >
                      <action.icon size={13} className="shrink-0 text-cyan-300" />
                      <span className="truncate">{action.label}</span>
                    </button>
                  ))}
                </div>
                <p className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground/70">
                  <Mic size={10} />
                  Toque no microfone e fale, ou escreva em baixo.
                </p>
              </div>
            ) : null}

            <JarvisThread
              turns={turns}
              pending={pending}
              compact
              actionState={chat.actionState}
              onSpeak={(turn) =>
                void voice.speak(turn.speech || turn.answer, { voice: prefs.voice, useServer: prefs.serverVoice })
              }
              onRepeat={(text) => chat.askAgain(text)}
              onAsk={(text) => chat.askAgain(text)}
              onAction={(action, turn) => void chat.runAction(action, turn)}
            />
          </div>

          <JarvisComposer
            value={question}
            onChange={setQuestion}
            onSend={() => send(question)}
            onStop={chat.stop}
            busy={busy}
            listening={voice.listening}
            canListen={voice.canListen}
            onToggleMic={() => (voice.listening ? voice.stop() : void voice.start())}
            placeholder="Pergunte ao Jarvis (Enter envia)"
            error={error}
            onDismissError={() => chat.setError(null)}
          />
        </section>
      ) : null}
    </>
  );
}

function StatusCell({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.02] px-2 py-1">
      <Icon size={11} className="shrink-0 text-cyan-300/80" />
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground/80">{label}</span>
      <span className="shrink-0 text-[10px] font-medium text-foreground/90">{value}</span>
    </div>
  );
}

export { generateJarvisId };
