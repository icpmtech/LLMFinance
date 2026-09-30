/**
 * Cliente do **Jarvis** (`/jarvis/*`) — o assistente operacional com voz do IQ OS.
 *
 * O Jarvis não vai buscar os dados diretamente: fala com o sistema por
 * **gateways** (Hermes, MCP do sistema e browser) e devolve, além da resposta,
 * o plano e os passos que seguiu — é isso que a interface desenha enquanto
 * ele pensa. A resposta vem também em versão falada (`speech`) e pode ser
 * sintetizada no servidor (`/jarvis/speak`) ou lida pelas vozes do sistema.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type JarvisTool = {
  id: string;
  gateway: "hermes" | "mcp" | "web" | string;
  label: string;
  description: string;
  parameters: Record<string, unknown>;
  keywords: string[];
  read_only: boolean;
  destructive: boolean;
};

export type JarvisGateway = {
  id: string;
  label: string;
  description: string;
  tools: number;
  examples: string[];
};

export type JarvisVoiceEngine = {
  available: boolean;
  engine?: string | null;
  model?: string | null;
  voices?: { id: string; label: string; locale: string }[];
  default_voice?: string;
  browser_fallback: boolean;
  note: string;
};

export type JarvisModelInfo = {
  kind: "cloud" | "local" | "unavailable" | string;
  provider?: string | null;
  model?: string | null;
  note?: string | null;
};

export type JarvisMeta = {
  about: { name: string; label: string; description: string; greeting: string; capabilities: string[] };
  gateways: JarvisGateway[];
  actions?: { destinations: JarvisAction[]; creations: JarvisAction[] };
  tools: JarvisTool[];
  voice: { stt: JarvisVoiceEngine; tts: JarvisVoiceEngine };
  model: JarvisModelInfo;
  limits: { max_question_chars: number; max_tools_per_plan: number; max_actions_per_plan?: number; max_history: number };
};

export type JarvisSkill = {
  id?: string | null;
  title?: string | null;
  summary?: string | null;
  steps?: string[];
  created?: boolean;
  merged?: boolean;
  mode?: string | null;
};

export type JarvisStep = {
  kind: "ouvir" | "modelo" | "skill" | "plano" | "ferramenta" | "resultado" | "responder" | string;
  label: string;
  at?: number;
  tool?: string;
  ok?: boolean;
  reason?: string;
  source?: string;
  skill_id?: string;
};

export type JarvisToolUse = {
  tool: string;
  gateway: string;
  label: string;
  ok: boolean;
  error?: string | null;
};

export type JarvisSource = {
  index?: number;
  label: string;
  url?: string | null;
  origin: string;
};

export type JarvisAudio = { mime: string; engine: string; base64: string };

/**
 * Uma ação que o Jarvis propõe — nunca a executa sozinho.
 *
 * `navigate` leva o utilizador a um sítio da plataforma (executa-se no cliente);
 * `create` cria um artefacto em nome dele (documento, dossiê, skill) e por isso
 * exige confirmação e passa por `/jarvis/actions/run`.
 */
export type JarvisAction = {
  id: string;
  kind: "navigate" | "create";
  label: string;
  description: string;
  /** `navigate`: vista e caminho da aplicação. */
  view?: string;
  path?: string;
  query?: string | null;
  accepts_query?: boolean;
  /** `create`: operação MCP e corpo já resolvido. */
  operation?: string;
  params?: Record<string, unknown>;
  requires_confirmation: boolean;
};

export type JarvisActionCatalog = {
  destinations: (JarvisAction & { keywords?: string[] })[];
  creations: (JarvisAction & { keywords?: string[] })[];
  total?: number;
};

export type JarvisAnswer = {
  answered: boolean;
  answer: string;
  speech: string;
  steps: JarvisStep[];
  plan: { tools: string[]; reason?: string | null; source?: string | null };
  tools_used: JarvisToolUse[];
  evidence: Record<string, unknown>[];
  sources: JarvisSource[];
  suggestions: string[];
  actions?: JarvisAction[];
  skill?: JarvisSkill | null;
  model: JarvisModelInfo;
  elapsed_seconds: number;
  audio?: JarvisAudio | null;
  audio_error?: string | null;
};

export type JarvisAskPayload = {
  question: string;
  depth?: "rapida" | "profunda";
  backend?: string;
  history?: { role: "user" | "assistant"; content: string }[];
  voice?: string;
  speak?: boolean;
};

/* ----------------------------------------------------------------- helpers */

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

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

export function getJarvisMeta(backend?: string): Promise<JarvisMeta> {
  const suffix = backend ? `?backend=${encodeURIComponent(backend)}` : "";
  return request<JarvisMeta>(`/jarvis/meta${suffix}`);
}

export function getJarvisVoice(): Promise<{ stt: JarvisVoiceEngine; tts: JarvisVoiceEngine }> {
  return request<{ stt: JarvisVoiceEngine; tts: JarvisVoiceEngine }>("/jarvis/voice");
}

export function askJarvis(payload: JarvisAskPayload): Promise<JarvisAnswer> {
  return request<JarvisAnswer>("/jarvis/ask", withBody(payload));
}

/** Sintetiza texto no servidor e devolve um URL de objeto pronto a tocar. */
export async function speakJarvis(text: string, voice?: string, rate = "+0%"): Promise<string> {
  const response = await fetch(`${API_BASE}/jarvis/speak`, withBody({ text, voice, rate }));
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
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

/** Transcreve áudio gravado no microfone (fallback do browser quando falha). */
export async function transcribeJarvisAudio(blob: Blob, language = "pt"): Promise<{ text: string; engine: string }> {
  const form = new FormData();
  form.append("audio", blob, blob.type.includes("wav") ? "jarvis.wav" : "jarvis.webm");
  const response = await fetch(`${API_BASE}/jarvis/transcribe?language=${encodeURIComponent(language)}`, {
    method: "POST",
    body: form,
  });
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
  return (await response.json()) as { text: string; engine: string };
}

/** Executa uma criação em nome do utilizador (documento, dossiê, skill). */
export function runJarvisAction(payload: {
  action: string;
  question?: string;
  answer?: string;
  params?: Record<string, unknown>;
}): Promise<{ ok: boolean; action: string; label: string; operation: string; result?: unknown; error?: string | null }> {
  return request("/jarvis/actions/run", withBody(payload));
}

export function getJarvisActions(): Promise<JarvisActionCatalog> {
  return request<JarvisActionCatalog>("/jarvis/actions");
}

/* ------------------------------------------------------------- streaming SSE */

export type JarvisStreamEvent =
  | { type: "passo"; step: JarvisStep }
  | { type: "plano"; tools: string[]; reason?: string | null; source?: string | null }
  | { type: "ferramenta"; tool: string; label: string; state: "a_correr" | "ok" | "falhou"; error?: string }
  | { type: "skill"; skill: JarvisSkill }
  | {
      type: "resposta";
      answer: string;
      speech: string;
      sources: JarvisSource[];
      suggestions: string[];
      actions?: JarvisAction[];
      skill?: JarvisSkill | null;
      /** Rasto completo dos passos (o servidor manda-o no fim, sem faltas). */
      steps?: JarvisStep[];
      tools_used?: JarvisToolUse[];
    }
  | { type: "acao"; action: JarvisAction }
  | { type: "fim"; elapsed_seconds: number }
  | { type: "erro"; detail: string };

/**
 * Pergunta ao Jarvis em streaming (SSE sobre POST).
 *
 * Devolve uma função para cancelar. O `onEvent` recebe cada evento à medida que
 * chega — é assim que a interface mostra o Jarvis a «pensar por passos».
 */
export function streamJarvis(
  payload: JarvisAskPayload,
  onEvent: (event: JarvisStreamEvent) => void,
  onError?: (error: Error) => void,
): () => void {
  const controller = new AbortController();

  const run = async () => {
    const response = await fetch(`${API_BASE}/jarvis/ask/stream`, {
      ...withBody(payload),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      let detail = `${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* resposta sem JSON */
      }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const flush = (chunk: string) => {
      for (const frame of chunk.split("\n\n")) {
        const block = frame.trim();
        if (!block) continue;
        let event = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        let parsed: Record<string, unknown> = {};
        try {
          parsed = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
        } catch {
          continue;
        }
        emit(event, parsed, onEvent);
      }
    };

    // A app envolve `window.fetch` com cabeçalhos de auth; o corpo chega em
    // pedaços que podem cortar um quadro SSE a meio, daí o buffer.
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const cut = buffer.lastIndexOf("\n\n");
      if (cut === -1) continue;
      flush(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
    }
    if (buffer.trim()) flush(buffer);
  };

  run()
    .catch((error: unknown) => {
      if (controller.signal.aborted) return;
      onError?.(error instanceof Error ? error : new Error(String(error)));
    })
    .finally(() => {
      /* nada a limpar: o reader fecha sozinho */
    });

  return () => controller.abort();
}

function emit(event: string, data: Record<string, unknown>, onEvent: (event: JarvisStreamEvent) => void) {
  switch (event) {
    case "passo":
      onEvent({ type: "passo", step: data as unknown as JarvisStep });
      break;
    case "plano":
      onEvent({
        type: "plano",
        tools: (data.tools as string[]) || [],
        reason: (data.reason as string) ?? null,
        source: (data.source as string) ?? null,
      });
      break;
    case "ferramenta":
      onEvent({
        type: "ferramenta",
        tool: String(data.tool || ""),
        label: String(data.label || data.tool || ""),
        state: (data.state as "a_correr" | "ok" | "falhou") || "a_correr",
        error: data.error ? String(data.error) : undefined,
      });
      break;
    case "skill":
      onEvent({ type: "skill", skill: (data.skill || {}) as JarvisSkill });
      break;
    case "resposta":
      onEvent({
        type: "resposta",
        answer: String(data.answer || ""),
        speech: String(data.speech || data.answer || ""),
        sources: (data.sources as JarvisSource[]) || [],
        suggestions: (data.suggestions as string[]) || [],
        actions: (data.actions as JarvisAction[]) || [],
        skill: (data.skill as JarvisSkill) ?? null,
        steps: (data.steps as JarvisStep[]) || [],
        tools_used: (data.tools_used as JarvisToolUse[]) || [],
      });
      break;
    case "acao":
      onEvent({ type: "acao", action: data.action as JarvisAction });
      break;
    case "fim":
      onEvent({ type: "fim", elapsed_seconds: Number(data.elapsed_seconds || 0) });
      break;
    case "erro":
      onEvent({ type: "erro", detail: String(data.detail || "Falha no Jarvis.") });
      break;
    default:
      break;
  }
}

/* ----------------------------------------------------------------- histórico */

const HISTORY_KEY = "finance-llm-jarvis:v1";
const HISTORY_MAX = 40;

export type JarvisTurn = {
  id: string;
  question: string;
  answer: string;
  speech?: string;
  steps?: JarvisStep[];
  sources?: JarvisSource[];
  suggestions?: string[];
  actions?: JarvisAction[];
  skill?: JarvisSkill | null;
  tools_used?: JarvisToolUse[];
  elapsed_seconds?: number;
  at: string;
};

export function loadJarvisHistory(): JarvisTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]") as JarvisTurn[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Publicação do histórico para quem estiver a ver a mesma conversa.
 *
 * O Jarvis aparece em dois sítios — a página `/jarvis` e o widget flutuante que
 * acompanha o resto da plataforma — e os dois têm de mostrar a mesma conversa.
 * Como são componentes independentes, sincronizam-se por aqui (e por um
 * `storage` event, para o caso de serem separadores diferentes).
 */
type JarvisHistoryListener = (turns: JarvisTurn[]) => void;

const historyListeners = new Set<JarvisHistoryListener>();

export function subscribeJarvisHistory(listener: JarvisHistoryListener): () => void {
  historyListeners.add(listener);
  return () => {
    historyListeners.delete(listener);
  };
}

function publishHistory(turns: JarvisTurn[]): void {
  for (const listener of historyListeners) {
    try {
      listener(turns);
    } catch {
      /* um ouvinte com problemas não pode travar os outros */
    }
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === HISTORY_KEY) publishHistory(loadJarvisHistory());
  });
}

export function saveJarvisTurn(turn: JarvisTurn): JarvisTurn[] {
  const next = [turn, ...loadJarvisHistory()].slice(0, HISTORY_MAX);
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* quota cheia: o histórico é um extra, não pode quebrar a conversa */
  }
  publishHistory(next);
  return next;
}

export function clearJarvisHistory(): void {
  try {
    window.localStorage.removeItem(HISTORY_KEY);
  } catch {
    /* ignorado */
  }
  publishHistory([]);
}

/** Preferências do Jarvis (página e widget partilham-nas). */
export type JarvisPrefs = {
  voice: string;
  serverVoice: boolean;
  autoSpeak: boolean;
  depth: "rapida" | "profunda";
  widgetOpen: boolean;
};

export const jarvisPreferences = {
  KEY: "finance-llm-jarvis:prefs",
  load(): JarvisPrefs {
    const fallback: JarvisPrefs = {
      voice: "",
      serverVoice: false,
      autoSpeak: true,
      depth: "rapida",
      widgetOpen: false,
    };
    if (typeof window === "undefined") return fallback;
    try {
      const parsed = JSON.parse(window.localStorage.getItem(this.KEY) || "null");
      return { ...fallback, ...(parsed || {}) };
    } catch {
      return fallback;
    }
  },
  save(value: JarvisPrefs): void {
    try {
      window.localStorage.setItem(this.KEY, JSON.stringify(value));
    } catch {
      /* ignorado */
    }
  },
};

/* Preferências do widget (posição arrastada, minimizado). */
export const jarvisWidgetPrefs = {
  KEY: "finance-llm-jarvis:widget",
  load(): { x: number | null; y: number | null; open: boolean } {
    const fallback = { x: null as number | null, y: null as number | null, open: false };
    if (typeof window === "undefined") return fallback;
    try {
      const parsed = JSON.parse(window.localStorage.getItem(this.KEY) || "null");
      return { ...fallback, ...(parsed || {}) };
    } catch {
      return fallback;
    }
  },
  save(value: { x: number | null; y: number | null; open: boolean }): void {
    try {
      window.localStorage.setItem(this.KEY, JSON.stringify(value));
    } catch {
      /* ignorado */
    }
  },
};

export { delay, request };
