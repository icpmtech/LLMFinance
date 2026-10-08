/**
 * Voz do Jarvis — ouvir (STT) e falar (TTS), tudo no browser com recurso ao
 * servidor quando vale a pena.
 *
 * **Ouvir.** Preferimos a *Web Speech API* (`SpeechRecognition`): transcreve
 * enquanto se fala, sem enviar áudio para lado nenhum e sem carregar modelos.
 * Quando o browser não a tem (Firefox, por exemplo), gravamos com
 * `MediaRecorder` e transcrevemos no servidor (`/jarvis/transcribe`), que usa
 * `faster-whisper`. Sem nenhum dos dois, o microfone fica indisponível e a
 * página continua a funcionar por texto.
 *
 * **Falar.** Por omissão usamos as vozes do sistema (`speechSynthesis`) — é
 * instantâneo. Se o servidor tiver `edge-tts` e o utilizador o preferir, o
 * áudio vem de `/jarvis/speak` (vozes neurais, mais naturais).
 *
 * Em ambos os casos o hook expõe `level` (0–1), que a órbita do Jarvis usa para
 * pulsar: no microfone vem do `AnalyserNode`; na fala, de um envelope suave,
 * porque o `speechSynthesis` não dá acesso ao sinal.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  speakJarvis,
  transcribeJarvisAudio,
  wakeJarvisAudio,
  type JarvisVoiceEngine,
  type JarvisWakeStatus,
} from "../../jarvisApi";

/* ----------------------------------------------------------- Web Speech API */

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function speechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const scope = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return scope.SpeechRecognition || scope.webkitSpeechRecognition || null;
}

/* -------------------------------------------------------------------- hook */

/**
 * Modo de escuta contínua (palavra de ativação).
 *
 * - `off` — desligado;
 * - `dormant` — a ouvir, à espera da palavra de ativação (transcrição local, por
 *   trechos curtos, com o modelo pequeno);
 * - `capturing` — a palavra foi ouvida e está a gravar o pedido até haver
 *   silêncio, para depois transcrever com o modelo completo.
 */
export type JarvisWakeState = "off" | "dormant" | "capturing";

//: Duração de cada trecho enviado a transcrever. Curto = latência baixa; longo =
//: menos pedidos. 1,5 s dá ~0,8 s de atraso entre falar e a órbita acordar.
const WAKE_CHUNK_MS = 1500;
//: Trechos seguidos sem voz que fecham o pedido.
const WAKE_SILENCE_CHUNKS = 2;
//: Teto para um pedido ditado (evita gravar para sempre se houver ruído).
const WAKE_MAX_COMMAND_MS = 15000;
//: Abaixo disto considera-se silêncio (o nível vem do analisador, 0–1).
const WAKE_MIN_LEVEL = 0.05;

export type UseJarvisVoiceOptions = {
  language?: string;
  stt?: JarvisVoiceEngine | null;
  tts?: JarvisVoiceEngine | null;
  /** Palavra de ativação publicada pelo servidor (`/jarvis/voice`). */
  wake?: JarvisWakeStatus | null;
  onTranscript: (text: string) => void;
  onError?: (message: string) => void;
  /** Chamado quando a fala começa e termina (para a órbita e a UI). */
  onSpeakingChange?: (speaking: boolean) => void;
};

export function useJarvisVoice({
  language = "pt-PT",
  stt,
  tts,
  wake,
  onTranscript,
  onError,
  onSpeakingChange,
}: UseJarvisVoiceOptions) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [level, setLevel] = useState(0);
  const [draft, setDraft] = useState("");
  const [wakeState, setWakeState] = useState<JarvisWakeState>("off");
  const [wakeWord, setWakeWord] = useState<string | null>(null);

  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef = useRef(onError);
  const onSpeakingChangeRef = useRef(onSpeakingChange);
  onTranscriptRef.current = onTranscript;
  onErrorRef.current = onError;
  onSpeakingChangeRef.current = onSpeakingChange;

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const levelRafRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speakingRafRef = useRef<number | null>(null);
  const modeRef = useRef<"recognition" | "recorder" | null>(null);
  // Escuta contínua (palavra de ativação)
  const levelRef = useRef(0);
  const wakeStateRef = useRef<JarvisWakeState>("off");
  const wakeRecorderRef = useRef<MediaRecorder | null>(null);
  const wakeChunksRef = useRef<Blob[]>([]);
  const wakeSilenceRef = useRef(0);
  const wakeBusyRef = useRef(false);
  const wakeTimerRef = useRef<number | null>(null);

  const recognitionSupported = useMemo(() => speechRecognitionCtor() !== null, []);
  const recorderSupported = useMemo(
    () => typeof window !== "undefined" && typeof window.MediaRecorder !== "undefined",
    [],
  );
  const serverStt = Boolean(stt?.available);
  const canListen = recognitionSupported || (recorderSupported && serverStt);

  /* ------------------------------------------------------- nível de áudio */

  const stopLevelLoop = useCallback(() => {
    if (levelRafRef.current !== null) {
      window.cancelAnimationFrame(levelRafRef.current);
      levelRafRef.current = null;
    }
  }, []);

  const startLevelLoop = useCallback(
    (analyser: AnalyserNode) => {
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i];
        const average = sum / data.length / 255;
        const value = Math.min(1, average * 2.6);
        levelRef.current = value;
        setLevel(value);
        levelRafRef.current = window.requestAnimationFrame(tick);
      };
      stopLevelLoop();
      levelRafRef.current = window.requestAnimationFrame(tick);
    },
    [stopLevelLoop],
  );

  const releaseStream = useCallback(() => {
    stopLevelLoop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
  }, [stopLevelLoop]);

  const openMicStream = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    try {
      const AudioContextCtor =
        (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext })
          .AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioContextCtor) {
        const context = new AudioContextCtor();
        audioContextRef.current = context;
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        startLevelLoop(analyser);
      }
    } catch {
      /* sem analisador: a órbita fica sem nível, mas ouvir continua a funcionar */
    }
    return stream;
  }, [startLevelLoop]);

  /* ---------------------------------------------------------------- falar */

  const stopSpeaking = useCallback(() => {
    if (speakingRafRef.current !== null) {
      window.cancelAnimationFrame(speakingRafRef.current);
      speakingRafRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
    setLevel(0);
  }, []);

  const speak = useCallback(
    async (text: string, options?: { voice?: string; useServer?: boolean }) => {
      const content = String(text || "").trim();
      if (!content) return;
      stopSpeaking();

      // Envelope suave para a órbita: o `speechSynthesis` não expõe o sinal.
      const startEnvelope = () => {
        const startedAt = performance.now();
        const tick = () => {
          const t = (performance.now() - startedAt) / 1000;
          const envelope = 0.42 + 0.34 * Math.abs(Math.sin(t * 7.5)) + 0.12 * Math.random();
          setLevel(Math.min(1, envelope));
          speakingRafRef.current = window.requestAnimationFrame(tick);
        };
        speakingRafRef.current = window.requestAnimationFrame(tick);
      };

      setSpeaking(true);
      onSpeakingChangeRef.current?.(true);

      const finish = () => {
        stopSpeaking();
        onSpeakingChangeRef.current?.(false);
      };

      if (options?.useServer && tts?.available) {
        try {
          const url = await speakJarvis(content, options.voice, "+0%");
          const audio = new Audio(url);
          audioRef.current = audio;
          audio.onended = () => {
            URL.revokeObjectURL(url);
            finish();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            finish();
          };
          startEnvelope();
          await audio.play();
          return;
        } catch {
          /* cai para a voz do sistema */
        }
      }

      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utterance = new SpeechSynthesisUtterance(content);
        utterance.lang = language;
        utterance.rate = 1.02;
        utterance.pitch = 1.0;
        const voices = window.speechSynthesis.getVoices();
        const preferred = options?.voice
          ? voices.find((item) => item.name === options.voice || item.voiceURI === options.voice)
          : undefined;
        const portuguese = preferred || voices.find((item) => item.lang?.toLowerCase().startsWith("pt"));
        if (portuguese) utterance.voice = portuguese;
        utterance.onend = finish;
        utterance.onerror = finish;
        startEnvelope();
        window.speechSynthesis.speak(utterance);
        return;
      }

      finish();
      onErrorRef.current?.("Este browser não tem síntese de voz.");
    },
    [language, stopSpeaking, tts?.available],
  );

  /* ---------------------------------------------------------------- ouvir */

  const stop = useCallback(() => {
    const mode = modeRef.current;
    modeRef.current = null;
    setListening(false);
    stopLevelLoop();
    setLevel(0);

    if (mode === "recognition") {
      recognitionRef.current?.stop();
      recognitionRef.current = null;
      releaseStream();
      return;
    }
    if (mode === "recorder") {
      const recorder = recorderRef.current;
      recorderRef.current = null;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      return;
    }
    releaseStream();
  }, [releaseStream, stopLevelLoop]);

  const start = useCallback(async () => {
    if (listening) return;
    stopSpeaking();

    const Ctor = speechRecognitionCtor();
    if (Ctor) {
      modeRef.current = "recognition";
      const recognition = new Ctor();
      recognition.lang = language;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event: any) => {
        let finalText = "";
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          const text = String(result[0]?.transcript || "");
          if (result.isFinal) finalText += text;
          else interim += text;
        }
        setDraft((finalText || interim).trim());
        if (finalText.trim()) {
          setDraft(finalText.trim());
          onTranscriptRef.current(finalText.trim());
        }
      };
      recognition.onerror = (event: any) => {
        const code = String(event?.error || "");
        if (code && code !== "aborted" && code !== "no-speech") {
          onErrorRef.current?.(`Microfone: ${code}.`);
        }
      };
      recognition.onend = () => {
        if (modeRef.current === "recognition") {
          // O reconhecedor para sozinho ao fim de uns segundos: reabre-se
          // enquanto o utilizador não mandar parar.
          try {
            recognition.start();
            return;
          } catch {
            /* já não é possível reabrir */
          }
        }
        setListening(false);
      };
      recognitionRef.current = recognition;
      try {
        await openMicStream();
        recognition.start();
        setDraft("");
        setListening(true);
        return;
      } catch (error) {
        modeRef.current = null;
        recognitionRef.current = null;
        onErrorRef.current?.(error instanceof Error ? error.message : "Não foi possível abrir o microfone.");
        return;
      }
    }

    if (!recorderSupported || !serverStt) {
      onErrorRef.current?.(
        "Este browser não tem reconhecimento de voz e o servidor não tem transcrição configurada. Escreva a pergunta.",
      );
      return;
    }

    modeRef.current = "recorder";
    try {
      const stream = await openMicStream();
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        releaseStream();
        setLevel(0);
        if (!blob.size) return;
        try {
          const result = await transcribeJarvisAudio(blob, language.slice(0, 2));
          if (result.text.trim()) {
            setDraft(result.text.trim());
            onTranscriptRef.current(result.text.trim());
          } else {
            onErrorRef.current?.("Não percebi nada no áudio gravado.");
          }
        } catch (error) {
          onErrorRef.current?.(error instanceof Error ? error.message : "Falha na transcrição.");
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setDraft("");
      setListening(true);
    } catch (error) {
      modeRef.current = null;
      onErrorRef.current?.(error instanceof Error ? error.message : "Não foi possível abrir o microfone.");
    }
  }, [language, listening, openMicStream, recorderSupported, releaseStream, serverStt, stopLevelLoop, stopSpeaking]);

  /* ------------------------------------------------- palavra de ativação */

  const wakeWords = wake?.words ?? [];
  const wakeAvailable = Boolean(wake?.available) && recorderSupported;

  /** Bipe curto de confirmação: diz «acordei» sem gastar uma síntese de voz. */
  const wakeBeep = useCallback(() => {
    const context = audioContextRef.current;
    if (!context) return;
    try {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = 880;
      gain.gain.value = 0.06;
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.12);
    } catch {
      /* sem bipe: a órbita e o texto continuam a indicar o estado */
    }
  }, []);

  const clearWakeTimer = useCallback(() => {
    if (wakeTimerRef.current !== null) {
      window.clearTimeout(wakeTimerRef.current);
      wakeTimerRef.current = null;
    }
  }, []);

  const backToDormant = useCallback(() => {
    clearWakeTimer();
    wakeChunksRef.current = [];
    wakeSilenceRef.current = 0;
    wakeStateRef.current = "dormant";
    setWakeState("dormant");
    setWakeWord(null);
    setDraft("");
  }, [clearWakeTimer]);

  const stopWake = useCallback(() => {
    clearWakeTimer();
    wakeStateRef.current = "off";
    setWakeState("off");
    setWakeWord(null);
    const recorder = wakeRecorderRef.current;
    wakeRecorderRef.current = null;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    wakeChunksRef.current = [];
    releaseStream();
    setLevel(0);
  }, [clearWakeTimer, releaseStream]);

  /** Fecha o pedido ditado: transcreve tudo com o modelo completo e pergunta. */
  const finishWakeCommand = useCallback(
    async (blob: Blob) => {
      const state = wakeStateRef.current;
      if (state === "off") return;
      backToDormant();
      releaseStream();
      if (!blob.size) {
        // Disse só a palavra de ativação: fica à espera do pedido seguinte.
        return;
      }
      try {
        const result = await transcribeJarvisAudio(blob, language.slice(0, 2));
        const text = result.text.trim();
        if (text) {
          setDraft(text);
          onTranscriptRef.current(text);
        } else {
          onErrorRef.current?.("Não percebi o pedido depois da palavra de ativação.");
        }
      } catch (error) {
        onErrorRef.current?.(error instanceof Error ? error.message : "Falha na transcrição.");
      }
    },
    [backToDormant, language, releaseStream],
  );

  const startWake = useCallback(async () => {
    if (!wakeAvailable) {
      onErrorRef.current?.(
        wake?.available
          ? "Este browser não consegue gravar áudio para a palavra de ativação."
          : "A palavra de ativação precisa de transcrição no servidor (`faster-whisper`).",
      );
      return;
    }
    stop();
    stopSpeaking();
    try {
      const stream = await openMicStream();
      const recorder = new MediaRecorder(stream);
      wakeRecorderRef.current = recorder;
      backToDormant();

      recorder.ondataavailable = async (event: BlobEvent) => {
        if (!event.data?.size) return;
        const state = wakeStateRef.current;
        if (state === "off" || wakeBusyRef.current) return;

        if (state === "dormant") {
          wakeBusyRef.current = true;
          try {
            const result = await wakeJarvisAudio(event.data, language.slice(0, 2));
            if (!result.active) return;
            setWakeWord(result.word ?? wakeWords[0] ?? null);
            const command = (result.command || "").trim();
            if (command.length >= 3) {
              // Disse a palavra e o pedido de uma vez: não se perde o resto.
              await finishWakeCommand(event.data);
              return;
            }
            // Só a palavra: grava o pedido até haver silêncio.
            wakeChunksRef.current = [];
            wakeSilenceRef.current = 0;
            wakeStateRef.current = "capturing";
            setWakeState("capturing");
            wakeBeep();
            clearWakeTimer();
            wakeTimerRef.current = window.setTimeout(() => {
              const chunks = wakeChunksRef.current;
              void finishWakeCommand(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
            }, WAKE_MAX_COMMAND_MS);
          } catch {
            /* é um ciclo: um trecho falhado não pode parar a escuta */
          } finally {
            wakeBusyRef.current = false;
          }
          return;
        }

        // A capturar o pedido: acumula e conta o silêncio.
        wakeChunksRef.current.push(event.data);
        if (levelRef.current < WAKE_MIN_LEVEL) wakeSilenceRef.current += 1;
        else wakeSilenceRef.current = 0;
        if (wakeSilenceRef.current >= WAKE_SILENCE_CHUNKS) {
          const chunks = wakeChunksRef.current;
          void finishWakeCommand(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
        }
      };

      recorder.start(WAKE_CHUNK_MS);
      wakeStateRef.current = "dormant";
      setWakeState("dormant");
    } catch (error) {
      wakeStateRef.current = "off";
      setWakeState("off");
      onErrorRef.current?.(error instanceof Error ? error.message : "Não foi possível abrir o microfone.");
    }
  }, [
    backToDormant,
    clearWakeTimer,
    finishWakeCommand,
    language,
    openMicStream,
    stop,
    stopSpeaking,
    wake?.available,
    wakeAvailable,
    wakeBeep,
    wakeWords,
  ]);

  const toggleWake = useCallback(() => {
    if (wakeStateRef.current === "off") void startWake();
    else stopWake();
  }, [startWake, stopWake]);

  /* --------------------------------------------------------------- limpeza */

  useEffect(() => () => {
    stopLevelLoop();
    if (speakingRafRef.current !== null) window.cancelAnimationFrame(speakingRafRef.current);
    if (wakeTimerRef.current !== null) window.clearTimeout(wakeTimerRef.current);
    recognitionRef.current?.abort();
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    if (wakeRecorderRef.current && wakeRecorderRef.current.state !== "inactive") {
      wakeRecorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, [stopLevelLoop]);

  // As vozes do sistema só ficam disponíveis depois de um evento `voiceschanged`.
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.getVoices();
    const onVoices = () => window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener("voiceschanged", onVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", onVoices);
  }, []);

  return {
    listening,
    speaking,
    level,
    draft,
    setDraft,
    start,
    stop,
    speak,
    stopSpeaking,
    canListen,
    recognitionSupported,
    recorderSupported,
    serverStt,
    // Palavra de ativação (escuta contínua local)
    wakeState,
    wakeWord,
    wakeWords,
    wakeAvailable,
    toggleWake,
    stopWake,
  } as const;
}

export default useJarvisVoice;
