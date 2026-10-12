import { Ear, Mic, MicOff, Send, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ModelBackend } from "../types";
import { buildChatOptions, useProviders } from "../providers";
import { getJarvisVoice, type JarvisVoiceEngine, type JarvisWakeStatus } from "../jarvisApi";
import { primaryWakeWord, useJarvisVoice, wakeWordsHint } from "./jarvis/useJarvisVoice";

interface ChatInputProps {
  onSend: (text: string) => void;
  loading?: boolean;
  backend?: ModelBackend;
  onBackendChange?: (backend: ModelBackend) => void;
}

type VoiceMeta = {
  stt: JarvisVoiceEngine;
  tts: JarvisVoiceEngine;
  wake?: JarvisWakeStatus;
};

export function ChatInput({ onSend, loading, backend = "gpt2", onBackendChange }: ChatInputProps) {
  const [text, setText] = useState("");
  const [voiceMeta, setVoiceMeta] = useState<VoiceMeta | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const { catalog } = useProviders();

  /* O que o browser/server conseguem fazer em voz (STT, TTS e a palavra de
     ativação). Falha em silêncio: sem isto o chat funciona só com o teclado. */
  useEffect(() => {
    getJarvisVoice()
      .then(setVoiceMeta)
      .catch(() => undefined);
  }, []);

  const sendRef = useRef(onSend);
  sendRef.current = onSend;

  /* Voz no chat: o microfone escreve e envia; a escuta contínua espera pela
     palavra de ativação («sabemos») e envia o que vier a seguir. Reutiliza o
     mesmo mecanismo local do Jarvis (transcrição no backend, sem áudio para fora). */
  const voice = useJarvisVoice({
    language: "pt-PT",
    stt: voiceMeta?.stt,
    tts: voiceMeta?.tts,
    wake: voiceMeta?.wake,
    onTranscript: (transcrito) => {
      const limpo = transcrito.trim();
      if (limpo) sendRef.current(limpo);
    },
    onError: (mensagem) => setVoiceError(mensagem),
  });

  const wakeWord = primaryWakeWord(voice.wakeWords);
  const wakeOn = voice.wakeState !== "off";

  /* Modelos locais + fornecedores externos, agrupados no selector. */
  const options = useMemo(() => buildChatOptions(catalog), [catalog]);
  const groups = useMemo(() => {
    const map = new Map<string, typeof options>();
    for (const option of options) {
      const list = map.get(option.group) ?? [];
      list.push(option);
      map.set(option.group, list);
    }
    return [...map.entries()];
  }, [options]);

  const current = options.find((option) => option.id === backend);
  const currentUsable = current ? current.usable : true;

  useEffect(() => {
    // Se o backend escolhido deixou de estar utilizável (sem chave), volta ao primeiro que funciona.
    if (options.length === 0 || currentUsable) return;
    const fallback = options.find((option) => option.usable);
    if (fallback) onBackendChange?.(fallback.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUsable, options.length]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    onSend(trimmed);
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(e);
    }
  };

  return (
    <form onSubmit={submit} className="p-4 border-t border-border bg-card">
      <div className="max-w-4xl mx-auto flex items-center gap-2 mb-2">
        <label className="text-xs text-muted-foreground">Modelo:</label>
        <select
          value={backend}
          onChange={(e) => onBackendChange?.(e.target.value as ModelBackend)}
          disabled={loading}
          className="text-xs bg-muted rounded-md px-2 py-1 outline-none focus:ring-1 focus:ring-primary/50 max-w-[360px]"
          title="Modelos locais da plataforma ou fornecedores externos (chaves em Definições → Fornecedores de IA)"
        >
          {groups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.usable}>
                  {option.label}
                  {option.usable ? "" : " — sem chave"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {current?.note && <span className="text-[11px] text-muted-foreground truncate">{current.note}</span>}
      </div>
      <div className="max-w-4xl mx-auto relative">
        <div className="absolute left-2 bottom-2 flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => {
              setVoiceError(null);
              if (voice.listening) voice.stop();
              else voice.start();
            }}
            disabled={!voice.canListen || loading}
            title={
              voice.canListen
                ? voice.listening
                  ? "Parar de ouvir"
                  : "Falar (transcreve para o chat)"
                : "Microfone indisponível neste browser"
            }
            className={[
              "p-2 rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed",
              voice.listening ? "text-primary animate-pulse" : "text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {voice.listening ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
          <button
            type="button"
            onClick={() => {
              setVoiceError(null);
              voice.toggleWake();
            }}
            disabled={!voice.wakeAvailable || loading}
            title={
              voice.wakeAvailable
                ? `Escuta contínua local (faster-whisper ${voiceMeta?.wake?.model ?? ""}). ${wakeWordsHint(
                    voice.wakeWords,
                  )}`
                : voiceMeta?.wake?.note || "Palavra de ativação indisponível"
            }
            className={[
              "p-2 rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed",
              wakeOn ? "text-amber-400" : "text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            <Ear size={18} />
          </button>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
          placeholder="Pergunta sobre finanças, ações, indicadores macro..."
          className="w-full resize-none max-h-40 bg-muted rounded-2xl pl-20 pr-12 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 border border-transparent focus:border-primary transition"
        />
        <button
          type="submit"
          disabled={!text.trim() || loading}
          className="absolute right-2 bottom-2 p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </div>
      {(wakeOn || voice.listening || voiceError) && (
        <p className="max-w-4xl mx-auto text-center text-[11px] text-muted-foreground mt-2">
          {voiceError
            ? `Voz: ${voiceError}`
            : voice.wakeState === "capturing"
              ? "A ouvir o pedido…"
              : voice.wakeState === "dormant"
                ? `A ouvir: diga «${wakeWord ?? "sabemos"}» e faça o pedido.`
                : voice.listening
                  ? "A ouvir… fale o seu pedido."
                  : ""}
        </p>
      )}
      <p className="text-center text-xs text-muted-foreground mt-2">
        O IQ OS pode cometer erros. Verifica dados críticos antes de investir.
      </p>
    </form>
  );
}
