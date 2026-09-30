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

import { speakJarvis, transcribeJarvisAudio, type JarvisVoiceEngine } from "../../jarvisApi";

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

export type UseJarvisVoiceOptions = {
  language?: string;
  stt?: JarvisVoiceEngine | null;
  tts?: JarvisVoiceEngine | null;
  onTranscript: (text: string) => void;
  onError?: (message: string) => void;
  /** Chamado quando a fala começa e termina (para a órbita e a UI). */
  onSpeakingChange?: (speaking: boolean) => void;
};

export function useJarvisVoice({
  language = "pt-PT",
  stt,
  tts,
  onTranscript,
  onError,
  onSpeakingChange,
}: UseJarvisVoiceOptions) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [level, setLevel] = useState(0);
  const [draft, setDraft] = useState("");

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
        setLevel(Math.min(1, average * 2.6));
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

  /* --------------------------------------------------------------- limpeza */

  useEffect(() => () => {
    stopLevelLoop();
    if (speakingRafRef.current !== null) window.cancelAnimationFrame(speakingRafRef.current);
    recognitionRef.current?.abort();
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
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
  } as const;
}

export default useJarvisVoice;
