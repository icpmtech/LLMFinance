import { API_BASE } from "./api";
import { parseSSELine } from "./parseSSELine";
import type { Message, ModelBackend, ChatRequest } from "./types";


export function streamChat(
    messages: Message[],
    backend: ModelBackend,
    onToken: (token: string) => void,
    onDone: (sources: Message["sources"], tools: Message["tools"]) => void,
    onError: (err: Error) => void
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
                            reader.cancel().catch(() => { });
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
