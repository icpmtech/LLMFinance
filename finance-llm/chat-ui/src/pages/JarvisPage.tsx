/**
 * Jarvis — a página completa do assistente operacional do IQ OS.
 *
 * A conversa (streaming, passos, fontes, compositor) vive no núcleo partilhado
 * `components/jarvis/JarvisChat.tsx`; esta página é a moldura: a órbita grande,
 * o painel de gateways/ferramentas e os controlos de voz e profundidade.
 *
 * A mesma conversa está acessível em qualquer página da plataforma pelo widget
 * flutuante (`components/jarvis/JarvisWidget.tsx`) — o histórico é partilhado.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Aperture,
  Brain,
  ChevronDown,
  Globe2,
  Orbit,
  RotateCcw,
  Server,
  Volume2,
  VolumeX,
  Zap,
} from "lucide-react";

import JarvisOrb, { type JarvisOrbState } from "../components/jarvis/JarvisOrb";
import { useJarvisVoice } from "../components/jarvis/useJarvisVoice";
import {
  JarvisComposer,
  JarvisThread,
  readJarvisBackend,
  useJarvisActionRunner,
  useJarvisChat,
} from "../components/jarvis/JarvisChat";
import { clearJarvisHistory, getJarvisMeta, jarvisPreferences, type JarvisAction, type JarvisMeta } from "../jarvisApi";

const GATEWAY_ICONS: Record<string, typeof Orbit> = {
  hermes: Brain,
  mcp: Server,
  web: Globe2,
};

const IDEAS = [
  "Quais são os maiores contratos públicos de energia em 2025?",
  "Ficha da EDP: contratos com o Estado e sinais de risco",
  "Compara as notícias de hoje sobre o BCE com os dados da plataforma",
  "Resume os documentos indexados sobre insolvências",
];

export default function JarvisPage({ onNavigate }: { onNavigate?: (action: JarvisAction) => void } = {}) {
  const [meta, setMeta] = useState<JarvisMeta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [prefs, setPrefs] = useState(() => jarvisPreferences.load());
  const [showTools, setShowTools] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJarvisMeta(readJarvisBackend())
      .then((value) => {
        if (!cancelled) setMeta(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) setMetaError(err instanceof Error ? err.message : "Não foi possível carregar o Jarvis.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    jarvisPreferences.save(prefs);
  }, [prefs]);

  // A voz precisa de falar com a conversa e a conversa com a voz: passa-se por
  // refs para não haver referências para a frente entre os dois hooks.
  const sendRef = useRef<(text: string) => void>(() => undefined);
  const reportErrorRef = useRef<(message: string) => void>(() => undefined);

  const voice = useJarvisVoice({
    language: "pt-PT",
    stt: meta?.voice.stt,
    tts: meta?.voice.tts,
    onTranscript: (text) => sendRef.current(text),
    onError: (message) => reportErrorRef.current(message),
  });

  const executeAction = useJarvisActionRunner({ onNavigate });

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

  const { turns, pending, error, busy } = chat;
  const hasConversation = turns.length > 0 || pending !== null;

  const orbState: JarvisOrbState = voice.listening
    ? "listening"
    : voice.speaking
      ? "speaking"
      : busy
        ? "thinking"
        : "idle";

  const orbSize = hasConversation ? 84 : 176;

  const scrollToEnd = useCallback(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, []);

  useEffect(() => {
    scrollToEnd();
  }, [turns.length, pending?.steps.length, pending?.answer, scrollToEnd]);

  const send = useCallback(
    (text: string) => {
      setQuestion("");
      // Um «sim» confirma a ação proposta em vez de virar pergunta nova.
      chat.askAgain(text);
    },
    [chat],
  );

  const reset = useCallback(() => {
    chat.stop();
    clearJarvisHistory();
    chat.setError(null);
  }, [chat]);

  const stateLabel = useMemo(() => {
    if (voice.listening) return voice.draft ? `A ouvir… «${voice.draft.slice(-60)}»` : "A ouvir…";
    if (voice.speaking) return "A responder em voz alta";
    if (busy) {
      const last = pending?.steps[pending.steps.length - 1];
      return last ? last.label : "A pensar…";
    }
    return meta?.about.greeting ? "Pronto." : "A ligar os gateways…";
  }, [busy, meta, pending, voice.draft, voice.listening, voice.speaking]);

  const modelLabel = meta?.model?.model
    ? `${meta.model.model}${meta.model.provider ? ` · ${meta.model.provider}` : ""}`
    : meta?.model?.kind === "cloud"
      ? "modelo da conta"
      : "modo factual (sem modelo)";

  const toolsByGateway = useMemo(() => {
    const map = new Map<string, number>();
    for (const tool of meta?.tools || []) {
      map.set(tool.gateway, (map.get(tool.gateway) || 0) + 1);
    }
    return map;
  }, [meta]);

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-sky-400/85 via-cyan-500/85 to-indigo-600/85 text-white shadow-lg shadow-cyan-500/20">
          <Orbit size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="text-[13.5px] font-semibold leading-tight text-foreground">Jarvis</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Hermes · MCP do sistema · browser · voz — {modelLabel}
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() =>
              setPrefs((current) => ({ ...current, depth: current.depth === "rapida" ? "profunda" : "rapida" }))
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.07]"
            title="Profundidade do gateway do Hermes"
          >
            <Aperture size={13} />
            {prefs.depth === "rapida" ? "Investigação rápida" : "Investigação profunda"}
          </button>

          <button
            type="button"
            onClick={() => setPrefs((current) => ({ ...current, autoSpeak: !current.autoSpeak }))}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] transition ${
              prefs.autoSpeak
                ? "border-teal-400/30 bg-teal-400/10 text-teal-200 hover:bg-teal-400/15"
                : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
            }`}
            title="Ler as respostas em voz alta"
          >
            {prefs.autoSpeak ? <Volume2 size={13} /> : <VolumeX size={13} />}
            Falar
          </button>

          <button
            type="button"
            onClick={() => setPrefs((current) => ({ ...current, serverVoice: !current.serverVoice }))}
            disabled={!meta?.voice.tts.available}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] transition disabled:opacity-40 ${
              prefs.serverVoice
                ? "border-violet-400/30 bg-violet-400/10 text-violet-200 hover:bg-violet-400/15"
                : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
            }`}
            title={
              meta?.voice.tts.available
                ? "Vozes neurais sintetizadas no servidor (edge-tts)"
                : "Sem edge-tts no servidor: usa-se a voz do sistema"
            }
          >
            <Server size={13} />
            Voz do servidor
          </button>

          {meta?.voice.tts.available && prefs.serverVoice ? (
            <select
              value={prefs.voice}
              onChange={(event) => setPrefs((current) => ({ ...current, voice: event.target.value }))}
              className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[11.5px] text-muted-foreground"
            >
              <option value="">Voz predefinida</option>
              {(meta.voice.tts.voices || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          ) : null}

          <button
            type="button"
            onClick={() => setShowTools((current) => !current)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.07]"
            title="O que o Jarvis pode fazer"
          >
            <Zap size={13} />
            {meta?.tools.length ?? 0} ferramentas
            <ChevronDown size={12} className={showTools ? "rotate-180 transition" : "transition"} />
          </button>

          <button
            type="button"
            onClick={reset}
            disabled={!hasConversation}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.07] disabled:opacity-40"
            title="Começar de novo"
          >
            <RotateCcw size={13} />
          </button>
        </div>
      </header>

      {showTools ? (
        <div className="shrink-0 border-b border-white/8 bg-white/[0.015] px-4 py-3">
          <div className="grid gap-3 @3xl:grid-cols-3">
            {(meta?.gateways || []).map((gateway) => {
              const Icon = GATEWAY_ICONS[gateway.id] || Server;
              return (
                <div key={gateway.id} className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                  <div className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
                    <Icon size={14} className="text-cyan-300" />
                    {gateway.label}
                    <span className="ml-auto text-[11px] text-muted-foreground">
                      {toolsByGateway.get(gateway.id) || gateway.tools} ferramentas
                    </span>
                  </div>
                  <p className="mt-1 text-[11.5px] leading-snug text-muted-foreground">{gateway.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {gateway.examples.slice(0, 4).map((example) => (
                      <code
                        key={example}
                        className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[10.5px] text-cyan-200/90"
                      >
                        {example}
                      </code>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col">
        {/* Órbita + estado */}
        <div className="flex shrink-0 flex-wrap items-center gap-4 border-b border-white/8 bg-white/[0.012] px-4 py-3">
          <JarvisOrb state={orbState} level={voice.level} size={orbSize} title={stateLabel} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[13px] font-medium text-foreground">
              <span
                className={`inline-flex h-2 w-2 rounded-full ${
                  orbState === "listening"
                    ? "bg-amber-400"
                    : orbState === "thinking"
                      ? "bg-violet-400"
                      : orbState === "speaking"
                        ? "bg-teal-400"
                        : "bg-sky-400"
                } ${busy || voice.listening || voice.speaking ? "animate-pulse" : ""}`}
              />
              {stateLabel}
            </div>
            {!hasConversation ? (
              <>
                <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">
                  {meta?.about.description || "A ligar os gateways…"}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(meta?.about.capabilities || []).map((item) => (
                    <span
                      key={item}
                      className="rounded-full border border-white/8 bg-white/[0.03] px-2 py-0.5 text-[11px] text-muted-foreground"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="mt-0.5 text-[11.5px] text-muted-foreground">
                {turns.length} {turns.length === 1 ? "resposta" : "respostas"} nesta conversa ·{" "}
                {voice.recognitionSupported
                  ? "microfone (reconhecimento do browser)"
                  : voice.serverStt
                    ? "microfone (transcrição no servidor)"
                    : "microfone indisponível"}
              </p>
            )}
            {metaError ? (
              <p className="mt-1.5 text-[11.5px] text-rose-300">
                Não foi possível ler o metamodelo do Jarvis: {metaError}
              </p>
            ) : null}
          </div>
        </div>

        {/* Conversa */}
        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
          {!hasConversation ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 py-6 text-center">
              <p className="max-w-md text-[12.5px] leading-relaxed text-muted-foreground">
                Faça uma pergunta sobre contratos, empresas, mercados, documentos ou peça uma investigação na web.
                Pode falar em vez de escrever.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {IDEAS.map((idea) => (
                  <button
                    key={idea}
                    type="button"
                    onClick={() => send(idea)}
                    className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-muted-foreground transition hover:border-cyan-400/30 hover:bg-cyan-400/10 hover:text-cyan-100"
                  >
                    {idea}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <JarvisThread
            turns={turns}
            pending={pending}
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
          error={error}
          onDismissError={() => chat.setError(null)}
        />
      </div>
    </div>
  );
}
