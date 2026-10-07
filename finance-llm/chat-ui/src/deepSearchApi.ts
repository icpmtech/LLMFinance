/**
 * Cliente da **Pesquisa profunda** (`/deep-search/*`) — resposta citada sobre os
 * dados indexados (contratos, empresas, imprensa, …), no estilo do Perplexity.
 *
 * O pedido é respondido em SSE (`POST /deep-search/ask`): primeiro chegam as
 * fontes numeradas e só depois os tokens da resposta, para a interface poder
 * mostrar as fontes enquanto o modelo escreve.
 */
import { API_BASE } from "./api";

export type DeepSource = {
    n: number;
    id: string;
    scope: string;
    scope_label: string;
    title: string;
    subtitle: string;
    snippet: string;
    url: string;
    date?: string | null;
    badges: string[];
    image: string;
    open?: { view?: string; arg?: string; mode?: string } | null;
    score?: number;
};

export type DeepSourceOption = {
    id: string;
    label: string;
    hint: string;
    default: boolean;
    kind: string;
    vector: boolean;
};

export type DeepMode = {
    id: string;
    label: string;
    hint: string;
};

export type DeepVectorScope = {
    index: string;
    total: number;
    with_embedding: number;
    ready: boolean;
    usable?: boolean;
    percent: number;
};

export type DeepVectorInfo = {
    scopes: Record<string, DeepVectorScope>;
    model: string;
    dims: number;
    error?: string | null;
};

export type DeepLimits = {
    per_source: { default: number; min: number; max: number };
    max_sources: { default: number; min: number; max: number };
    unlimited: number;
    citable_max: number;
};

export type DeepMeta = {
    sources: DeepSourceOption[];
    modes: DeepMode[];
    default_mode: string;
    examples: string[];
    vector: DeepVectorInfo;
    defaults: { sources: string[]; provider: string; model: string; backend: string };
    limits: DeepLimits;
    has_session: boolean;
};

export type DeepSuggestion = {
    text: string;
    scope: string;
    kind: string;
    hint: string;
    arg: string;
};

export type DeepSearchResult = {
    question: string;
    text_query?: string;
    sources: DeepSource[];
    searched: string[];
    took_ms: number;
    mode?: string;
    citable_max?: number;
    unlimited?: boolean;
    suggestions?: string[];
    vector_skipped?: Record<string, string>;
    vector_error?: string | null;
    error?: string | null;
};

export type DeepAskRequest = {
    question: string;
    backend?: string;
    sources?: string[];
    mode?: string;
    per_source?: number;
    max_sources?: number;
    temperature?: number;
    max_tokens?: number;
    history?: { role: string; content: string }[];
};

export type DeepSourcesEvent = {
    question: string;
    sources: DeepSource[];
    searched: string[];
    took_ms: number;
    model: string;
    mode?: string;
    text_lists?: number;
    vector_lists?: number;
    citable_max?: number;
    unlimited?: boolean;
    suggestions?: string[];
    vector_skipped?: Record<string, string>;
    vector_error?: string | null;
};

export type DeepAskHandlers = {
    onSources?: (payload: DeepSourcesEvent) => void;
    onMeta?: (payload: { model: string; backend: string; kind?: string }) => void;
    onToken?: (token: string) => void;
    onDone?: (payload: { sources: DeepSource[]; answer: string; citations: number[]; suggestions?: string[] }) => void;
    onError?: (message: string) => void;
};

export const DEEP_EXAMPLES = [
    "Quais os maiores contratos de 2025 na área da saúde?",
    "Que empresas ganharam mais contratos com a Comunidade Intermunicipal da Região de Leiria?",
    "Resume os contratos de videovigilância adjudicados no último ano e diz quem concorreu.",
    "Que notícias recentes ligam a EDP a contratação pública?",
];

async function readError(res: Response, fallback: string): Promise<string> {
    try {
        const data = await res.json();
        return String(data?.detail || data?.error || fallback);
    } catch {
        return fallback;
    }
}

/** Catálogo de âmbitos, limites e predefinições do utilizador. */
export async function fetchDeepMeta(): Promise<DeepMeta> {
    const res = await fetch(`${API_BASE}/deep-search/meta`);
    if (!res.ok) throw new Error(await readError(res, `Erro ao carregar as fontes (${res.status}).`));
    return res.json();
}

/** Só a recuperação (sem IA): útil para ver/refrescar as fontes. */
export async function searchDeepSources(
    question: string,
    options: { sources?: string[]; mode?: string; per_source?: number; max_sources?: number } = {},
): Promise<DeepSearchResult> {
    const params = new URLSearchParams({ q: question });
    if (options.sources?.length) params.set("sources", options.sources.join(","));
    if (options.mode) params.set("mode", options.mode);
    if (options.per_source) params.set("per_source", String(options.per_source));
    if (options.max_sources) params.set("max_sources", String(options.max_sources));
    const res = await fetch(`${API_BASE}/deep-search/search?${params.toString()}`);
    if (!res.ok) throw new Error(await readError(res, `Erro ao pesquisar (${res.status}).`));
    return res.json();
}

/** Sugestões de autocompletar (empresas, contratos ES, recolha, mercado). */
export async function fetchDeepSuggestions(q: string, signal?: AbortSignal): Promise<DeepSuggestion[]> {
    const query = q.trim();
    if (query.length < 2) return [];
    const res = await fetch(`${API_BASE}/deep-search/suggest?q=${encodeURIComponent(query)}&limit=8`, { signal });
    if (!res.ok) return [];
    const data = (await res.json()) as { items?: DeepSuggestion[] };
    return data.items ?? [];
}

function parseEventBlock(block: string): { event: string; data: Record<string, unknown> } | null {
    let event = "message";
    const dataLines: string[] = [];
    for (const raw of block.split("\n")) {
        const line = raw.replace(/\r$/, "");
        if (!line.trim() || line.startsWith(":")) continue;
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^\s/, ""));
    }
    if (!dataLines.length) return null;
    const text = dataLines.join("\n");
    try {
        return { event, data: JSON.parse(text) as Record<string, unknown> };
    } catch {
        return { event, data: { token: text } };
    }
}

/**
 * Pergunta com resposta citada. Devolve a função de cancelamento (como o
 * `streamChat`), para o botão «Parar» abortar o pedido a meio.
 */
export function askDeepSearch(payload: DeepAskRequest, handlers: DeepAskHandlers): () => void {
    const controller = new AbortController();
    let closed = false;

    const close = () => {
        if (closed) return;
        closed = true;
        try {
            controller.abort();
        } catch {
            /* ignorado */
        }
    };

    fetch(`${API_BASE}/deep-search/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
    })
        .then(async (res) => {
            if (!res.ok) {
                handlers.onError?.(await readError(res, `Erro do servidor (${res.status}).`));
                close();
                return;
            }
            if (!res.body) {
                handlers.onError?.("O servidor não devolveu resposta em fluxo.");
                close();
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            const consume = (text: string, flush = false) => {
                buffer += text;
                const parts = buffer.split("\n\n");
                const rest = parts.pop() ?? "";
                buffer = flush ? "" : rest;
                // No fim do fluxo, o que sobrar sem `\n\n` final ainda é um evento.
                const blocks = flush && rest.trim() ? [...parts, rest] : parts;
                for (const block of blocks) {
                    const parsed = parseEventBlock(block);
                    if (!parsed) continue;
                    const { event, data } = parsed;
                    if (event === "sources") handlers.onSources?.(data as never);
                    else if (event === "meta") handlers.onMeta?.(data as never);
                    else if (event === "error") {
                        handlers.onError?.(String((data as { message?: string }).message || "Erro desconhecido."));
                        close();
                    } else if (event === "done") {
                        handlers.onDone?.(data as never);
                        close();
                    } else if (typeof (data as { token?: string }).token === "string") {
                        handlers.onToken?.((data as { token: string }).token);
                    }
                }
            };

            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                consume(decoder.decode(value, { stream: true }));
            }
            consume(decoder.decode(), true);
            if (!closed) {
                handlers.onDone?.({ sources: [], answer: "", citations: [] });
                close();
            }
        })
        .catch((error: unknown) => {
            if (closed || (error as Error)?.name === "AbortError") return;
            handlers.onError?.(error instanceof Error ? error.message : String(error));
            close();
        });

    return close;
}
