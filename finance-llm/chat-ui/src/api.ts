import type { ChatRequest, ChatResponse, Message, ModelBackend } from "./types";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

export async function sendChat(
  messages: Message[],
  backend: ModelBackend = "gpt2"
): Promise<ChatResponse> {
  const body: ChatRequest = {
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
    })),
    model: "finance-llm",
    backend,
    stream: false,
  };

  const res = await fetch(`${API_BASE}/chat?backend=${backend}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw new Error(`Erro do servidor: ${res.status}`);
  }

  return res.json();
}

export function streamChat(
  messages: Message[],
  backend: ModelBackend,
  onToken: (token: string) => void,
  onDone: (sources: Message["sources"], tools: Message["tools"]) => void,
  onError: (err: Error) => void,
) {
  const body: ChatRequest = {
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
    })),
    model: "finance-llm",
    backend,
    stream: true,
  };

  const controller = new AbortController();
  let closed = false;
  let buffer = "";

  fetch(`${API_BASE}/chat/stream?backend=${backend}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        throw new Error(`Erro do servidor: ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          parseSSELine(line, onToken, onDone, onError, () => {
            if (!closed) {
              closed = true;
              reader.cancel().catch(() => {});
              controller.abort();
            }
          });
        }
      }
      // process remaining buffer
      for (const line of buffer.split("\n")) {
        parseSSELine(line, onToken, onDone, onError, () => {
          if (!closed) {
            closed = true;
            controller.abort();
          }
        });
      }
    })
    .catch((err) => {
      if ((err as Error).name !== "AbortError") {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    });

  return () => {
    if (!closed) {
      closed = true;
      controller.abort();
    }
  };
}

function parseSSELine(
  line: string,
  onToken: (token: string) => void,
  onDone: (sources: Message["sources"], tools: Message["tools"]) => void,
  _onError: (err: Error) => void,
  close: () => void,
) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith(":")) return;

  const eventMatch = trimmed.match(/^event:\s*(.+)$/);
  if (eventMatch) {
    // next line will contain the data; store is not needed for simple parser
    return;
  }

  const dataMatch = trimmed.match(/^data:\s*(.+)$/);
  if (!dataMatch) return;

  try {
    const data = JSON.parse(dataMatch[1]);
    if (data.token) {
      onToken(data.token);
    }
    if (data.sources || data.tools) {
      onDone(data.sources || [], data.tools || []);
      close();
    }
  } catch {
    onToken(dataMatch[1]);
  }
}
