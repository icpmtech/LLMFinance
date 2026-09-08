import { API_BASE, askRag } from "./api";
import type { Message, ModelBackend, ChatResponse, ChatRequest } from "./types";


export async function sendChat(
    messages: Message[],
    backend: ModelBackend = "gpt2"
): Promise<ChatResponse> {
    if (backend === "bloomberg") {
        const lastUser = [...messages].reverse().find((m) => m.role === "user");
        const question = lastUser?.content || "";
        const res = await askRag({ question });
        return {
            message: { role: "assistant", content: res.answer },
            sources: res.sources.map((s) => ({
                name: s.doc_title,
                value: s.text,
            })),
            tools: [],
        };
    }

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
