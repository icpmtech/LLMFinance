/**
 * Página **Pesquisa profunda** — pergunta em linguagem natural respondida com os
 * dados do IQ OS (contratos, empresas, imprensa, …) e **fontes citadas**.
 *
 * É o «Perplexity» da plataforma: a recuperação vem do Elasticsearch (o mesmo
 * `unified_search` da Pesquisa total) e a redação do modelo configurado pelo
 * utilizador. A resposta chega em fluxo (SSE) e as fontes aparecem primeiro, para
 * se poder verificar a origem de cada afirmação enquanto o texto é escrito.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
    Binoculars,
    CircleStop,
    CornerDownRight,
    ExternalLink,
    Layers,
    Loader2,
    Search,
    Sparkles,
} from "lucide-react";

import { API_BASE } from "../api";
import {
    DEEP_EXAMPLES,
    askDeepSearch,
    fetchDeepMeta,
    fetchDeepSuggestions,
    type DeepMeta,
    type DeepSource,
    type DeepSuggestion,
    type DeepSourcesEvent,
} from "../deepSearchApi";

// Cartões de fonte desenhados de início e em cada «mostrar mais». Com «sem
// limite» a API devolve centenas de fontes: desenhá-las todas bloqueia a página.
const CARTOES_INICIAIS = 24;
const CARTOES_PASSO = 48;

type ChatModelOption = {
    id: string;
    label: string;
    group: string;
    usable: boolean;    note?: string | null;
    default?: boolean;
};

type Props = {
    onNavigate?: (view: string) => void;
};

/** Marcas de citação `[n]` transformadas em ligações para o cartão da fonte. */
function withCitationLinks(answer: string, total: number): string {
    if (!answer) return answer;
    return answer.replace(/\[(\d+)\]/g, (match, digits: string) => {
        const n = Number(digits);
        return n >= 1 && n <= total ? `[[${n}]](#fonte-${n})` : match;
    });
}

function scopeBadgeClass(scope: string): string {
    if (scope.startsWith("contracts")) return "border-teal-400/30 bg-teal-400/10 text-teal-200";
    if (scope.startsWith("entit") || scope === "pessoas") return "border-sky-400/30 bg-sky-400/10 text-sky-200";
    if (scope === "imprensa" || scope === "news") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
    if (scope === "social") return "border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200";
    return "border-white/15 bg-white/5 text-muted-foreground";
}

export default function DeepSearchPage({ onNavigate }: Props) {
    const [meta, setMeta] = useState<DeepMeta | null>(null);
    const [models, setModels] = useState<ChatModelOption[]>([]);
    const [question, setQuestion] = useState("");
    const [backend, setBackend] = useState("");
    const [mode, setMode] = useState("");
    const [active, setActive] = useState<string[] | null>(null);
    const [maxSources, setMaxSources] = useState(12);
    const [answering, setAnswering] = useState(false);
    const [answer, setAnswer] = useState("");
    const [sources, setSources] = useState<DeepSource[]>([]);
    const [usedModel, setUsedModel] = useState("");
    const [error, setError] = useState("");
    const [tookMs, setTookMs] = useState<number | null>(null);
    const [cited, setCited] = useState<number[]>([]);
    const [retrieval, setRetrieval] = useState<DeepSourcesEvent | null>(null);
    const [followups, setFollowups] = useState<string[]>([]);
    // Com «sem limite» a API chega a devolver 291 fontes. Desenhar todas de uma
    // vez custa caro (centenas de cartões com texto) e ninguém lê as últimas:
    // mostram-se as primeiras e um botão abre o resto.
    const [cartoes, setCartoes] = useState(CARTOES_INICIAIS);
    const [acItems, setAcItems] = useState<DeepSuggestion[]>([]);
    const [acOpen, setAcOpen] = useState(false);
    const [acIndex, setAcIndex] = useState(-1);

    const stopRef = useRef<null | (() => void)>(null);
    const answerRef = useRef<HTMLDivElement | null>(null);
    const acAbortRef = useRef<AbortController | null>(null);

    useEffect(() => {
        let alive = true;
        fetchDeepMeta()
            .then((data) => {
                if (!alive) return;
                setMeta(data);
                setActive((current) => current ?? data.defaults.sources);
                setMaxSources(data.limits.max_sources.default);
                setMode((current) => current || data.default_mode || "hybrid");
                if (!backend && data.defaults.backend) setBackend(data.defaults.backend);
            })
            .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));

        fetch(`${API_BASE}/providers/chat-models`)
            .then((res) => (res.ok ? res.json() : { options: [] }))
            .then((data: { options?: ChatModelOption[] }) => setModels(data.options ?? []))
            .catch(() => setModels([]));

        return () => {
            alive = false;
            stopRef.current?.();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => () => stopRef.current?.(), []);

    // Sugestões de autocompletar: a cada pausa da escrita, com cancelamento do
    // pedido anterior (evita respostas fora de ordem a escrever depressa).
    useEffect(() => {
        const term = question.trim();
        if (term.length < 2 || answering) {
            setAcItems([]);
            setAcOpen(false);
            return;
        }
        const timer = window.setTimeout(() => {
            acAbortRef.current?.abort();
            const controller = new AbortController();
            acAbortRef.current = controller;
            fetchDeepSuggestions(term, controller.signal)
                .then((items) => {
                    setAcItems(items);
                    setAcIndex(-1);
                    setAcOpen(items.length > 0);
                })
                .catch(() => undefined);
        }, 250);
        return () => window.clearTimeout(timer);
    }, [question, answering]);

    const chosenSources = useMemo(() => active ?? meta?.defaults.sources ?? [], [active, meta]);

    const ask = useCallback(
        (text?: string) => {
            const prompt = (text ?? question).trim();
            if (!prompt || answering) return;
            stopRef.current?.();

            setQuestion(prompt);
            setAnswering(true);
            setAnswer("");
            setSources([]);
            setCartoes(CARTOES_INICIAIS);
            setError("");
            setTookMs(null);
            setCited([]);
            setRetrieval(null);
            setFollowups([]);
            setAcOpen(false);

            stopRef.current = askDeepSearch(
                {
                    question: prompt,
                    backend,
                    sources: chosenSources,
                    mode: mode || undefined,
                    // «Sem limite»: pede o máximo por âmbito (o `unified_search`
                    // aceita 50) e deixa o número de fontes em aberto.
                    per_source: maxSources === 0 ? 50 : undefined,
                    max_sources: maxSources,
                    temperature: 0.2,
                },
                {
                    onSources: (payload) => {
                        setSources(payload.sources ?? []);
                        setTookMs(payload.took_ms ?? null);
                        setUsedModel(payload.model || backend);
                        setRetrieval(payload);
                    },
                    onMeta: (payload) => setUsedModel(payload.model || backend),
                    onToken: (token) => {
                        setAnswer((current) => current + token);
                        answerRef.current?.scrollIntoView({ block: "nearest" });
                    },
                    onDone: (payload) => {
                        setAnswering(false);
                        if (payload.sources?.length) setSources(payload.sources);
                        if (payload.citations) setCited(payload.citations);
                        setFollowups(payload.suggestions ?? []);
                    },
                    onError: (message) => {
                        setAnswering(false);
                        setError(message);
                    },
                },
            );
        },
        [answering, backend, chosenSources, maxSources, mode, question],
    );

    const stop = useCallback(() => {
        stopRef.current?.();
        stopRef.current = null;
        setAnswering(false);
    }, []);

    const toggleSource = (id: string) => {
        setActive((current) => {
            const list = current ?? meta?.defaults.sources ?? [];
            return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
        });
    };

    const openSource = (source: DeepSource) => {
        const view = source.open?.view;
        const arg = source.open?.arg;
        if (onNavigate && view && arg && (view === "company-detail" || view === "contract-detail")) {
            onNavigate(`${view}:${arg}`);
            return;
        }
        if (source.url) window.open(source.url, "_blank", "noopener,noreferrer");
    };

    const markdown = useMemo(() => withCitationLinks(answer, sources.length), [answer, sources.length]);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
            <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
                <div className="rounded-xl bg-gradient-to-br from-cyan-300/30 via-teal-500/25 to-slate-900 p-2 text-cyan-100">
                    <Binoculars size={20} />
                </div>
                <div className="min-w-0">
                    <h1 className="text-sm font-semibold text-foreground">Pesquisa profunda</h1>
                    <p className="truncate text-[11px] text-muted-foreground">
                        Pergunta em linguagem natural: resposta do modelo com fontes citadas dos dados indexados
                    </p>
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                        modelo <span className="font-mono text-foreground">{usedModel || backend || "predefinido"}</span>
                    </span>
                    {sources.length > 0 && (
                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                            {sources.length} fonte(s)
                            {tookMs !== null ? ` · ${tookMs} ms a procurar` : ""}
                        </span>
                    )}
                </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
                    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                            Pergunta
                        </label>
                        <div className="relative">
                            <textarea
                                value={question}
                                onChange={(event) => setQuestion(event.target.value)}
                                onKeyDown={(event) => {
                                    if (acOpen && event.key === "ArrowDown") {
                                        event.preventDefault();
                                        setAcIndex((current) => Math.min(current + 1, acItems.length - 1));
                                        return;
                                    }
                                    if (acOpen && event.key === "ArrowUp") {
                                        event.preventDefault();
                                        setAcIndex((current) => Math.max(current - 1, -1));
                                        return;
                                    }
                                    if (event.key === "Escape" && acOpen) {
                                        setAcOpen(false);
                                        return;
                                    }
                                    if (event.key === "Enter" && !event.shiftKey) {
                                        event.preventDefault();
                                        // Com uma sugestão escolhida (↓/↑), o Enter completa
                                        // o texto; sem escolha, pergunta logo.
                                        if (acOpen && acIndex >= 0 && acItems[acIndex]) {
                                            setQuestion(acItems[acIndex].text);
                                            setAcOpen(false);
                                            return;
                                        }
                                        ask();
                                    }
                                }}
                                rows={3}
                                autoComplete="off"
                                placeholder="Ex.: Que contratos de videovigilância foram adjudicados na região de Leiria e por que valores?"
                                className="w-full resize-none rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm outline-none focus:border-teal-400/50"
                            />

                            {acOpen && acItems.length > 0 && (
                                <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-xl border border-white/10 bg-[#16181d] shadow-xl">
                                    {acItems.map((item, index) => (
                                        <li key={`${item.scope}-${item.text}-${index}`}>
                                            <button
                                                type="button"
                                                onMouseDown={(event) => event.preventDefault()}
                                                onClick={() => {
                                                    setQuestion(item.text);
                                                    setAcOpen(false);
                                                }}
                                                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition ${
                                                    index === acIndex ? "bg-teal-400/10 text-foreground" : "text-foreground/80 hover:bg-white/5"
                                                }`}
                                            >
                                                <Search size={13} className="shrink-0 text-teal-300" />
                                                <span className="min-w-0 flex-1 truncate">{item.text}</span>
                                                {item.hint && (
                                                    <span className="shrink-0 truncate text-[10px] text-muted-foreground">{item.hint}</span>
                                                )}
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={() => ask()}
                                disabled={answering || !question.trim()}
                                className="flex items-center gap-2 rounded-xl border border-teal-400/40 bg-teal-500/20 px-4 py-2 text-sm font-medium text-teal-100 transition hover:bg-teal-500/30 disabled:opacity-60"
                            >
                                {answering ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                                {answering ? "A responder…" : "Responder"}
                            </button>
                            {answering && (
                                <button
                                    type="button"
                                    onClick={stop}
                                    className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
                                >
                                    <CircleStop size={16} />
                                    Parar
                                </button>
                            )}

                            <div className="ml-auto flex flex-wrap items-center gap-2">
                                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                    Modelo
                                    <select
                                        value={backend}
                                        onChange={(event) => setBackend(event.target.value)}
                                        className="max-w-[260px] rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-foreground outline-none focus:border-teal-400/50"
                                    >
                                        <option value="">Predefinido da conta</option>
                                        {models.map((option) => (
                                            <option key={option.id} value={option.id} disabled={!option.usable}>
                                                {option.label}
                                                {option.usable ? "" : " (sem chave)"}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                    Modo
                                    <select
                                        value={mode}
                                        onChange={(event) => setMode(event.target.value)}
                                        title={meta?.modes.find((item) => item.id === mode)?.hint}
                                        className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-foreground outline-none focus:border-teal-400/50"
                                    >
                                        {meta?.modes.map((item) => (
                                            <option key={item.id} value={item.id}>
                                                {item.label}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                    Fontes
                                    <select
                                        value={maxSources}
                                        onChange={(event) => setMaxSources(Number(event.target.value))}
                                        title="Número máximo de fontes (0 = todas as que existirem)"
                                        className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-foreground outline-none focus:border-teal-400/50"
                                    >
                                        {[
                                            { value: 6, label: "até 6" },
                                            { value: 12, label: "até 12" },
                                            { value: 24, label: "até 24" },
                                            { value: 48, label: "até 48" },
                                            { value: 120, label: "até 120" },
                                            { value: 0, label: "sem limite" },
                                        ].map((option) => (
                                            <option key={option.value} value={option.value}>
                                                {option.label}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            </div>
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/5 pt-3">
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <Layers size={13} />
                                Dados a procurar
                            </span>
                            {(meta?.sources ?? []).map((source) => {
                                const on = chosenSources.includes(source.id);
                                return (
                                    <button
                                        key={source.id}
                                        type="button"
                                        title={source.hint}
                                        onClick={() => toggleSource(source.id)}
                                        className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                                            on
                                                ? "border-teal-400/40 bg-teal-400/15 text-teal-100"
                                                : "border-white/10 bg-white/5 text-muted-foreground hover:text-foreground"
                                        }`}
                                    >
                                        {source.label}
                                    </button>
                                );
                            })}
                        </div>
                    </section>

                    {error && (
                        <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                            {error}
                        </div>
                    )}

                    {!answer && !answering && sources.length === 0 && !error && (
                        <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                            <p className="mb-3 text-[11px] uppercase tracking-wide text-muted-foreground">
                                Exemplos de perguntas
                            </p>
                            <div className="grid gap-2 sm:grid-cols-2">
                                {DEEP_EXAMPLES.map((example) => (
                                    <button
                                        key={example}
                                        type="button"
                                        onClick={() => ask(example)}
                                        className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-xs text-foreground/80 transition hover:border-teal-400/30 hover:text-foreground"
                                    >
                                        <Search size={14} className="mt-0.5 shrink-0 text-teal-300" />
                                        {example}
                                    </button>
                                ))}
                            </div>
                        </section>
                    )}

                    {sources.length > 0 && (
                        <section className="flex flex-col gap-2">
                            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                Fontes consideradas ({sources.length})
                                {cited.length > 0 ? ` · citadas: ${cited.map((n) => `[${n}]`).join(" ")}` : ""}
                            </p>
                            {retrieval && (
                                <p className="text-[11px] text-muted-foreground">
                                    Recuperação:{" "}
                                    <span className="text-foreground/80">
                                        {meta?.modes.find((item) => item.id === retrieval.mode)?.label ?? retrieval.mode}
                                    </span>
                                    {typeof retrieval.text_lists === "number" && ` · ${retrieval.text_lists} lista(s) por palavras`}
                                    {typeof retrieval.vector_lists === "number" &&
                                        retrieval.vector_lists > 0 &&
                                        ` · ${retrieval.vector_lists} lista(s) semântica(s)`}
                                    {retrieval.vector_error && ` · semântica indisponível (${retrieval.vector_error})`}
                                    {retrieval.vector_skipped && Object.keys(retrieval.vector_skipped).length > 0 &&
                                        ` · sem vectores suficientes em: ${Object.keys(retrieval.vector_skipped).join(", ")}`}
                                    {typeof retrieval.citable_max === "number" &&
                                        retrieval.citable_max > 0 &&
                                        sources.length > retrieval.citable_max &&
                                        ` · ${sources.length} encontradas, ${retrieval.citable_max} citáveis`}
                                </p>
                            )}
                            <div className="grid gap-2 sm:grid-cols-2">
                                {sources.slice(0, cartoes).map((source) => {
                                    const clickable = Boolean(source.url) || Boolean(source.open?.arg);
                                    return (
                                        <button
                                            key={`${source.scope}-${source.id}-${source.n}`}
                                            id={`fonte-${source.n}`}
                                            type="button"
                                            onClick={() => clickable && openSource(source)}
                                            className={`flex flex-col gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left transition ${
                                                clickable ? "hover:border-teal-400/40" : "cursor-default"
                                            }`}
                                        >
                                            <div className="flex items-center gap-2">
                                                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-teal-400/30 bg-teal-400/10 text-[10px] font-semibold text-teal-100">
                                                    {source.n}
                                                </span>
                                                <span
                                                    className={`rounded-full border px-2 py-0.5 text-[10px] ${scopeBadgeClass(source.scope)}`}
                                                >
                                                    {source.scope_label}
                                                </span>
                                                {source.date && (
                                                    <span className="ml-auto text-[10px] text-muted-foreground">{source.date}</span>
                                                )}
                                                {clickable && <ExternalLink size={12} className="text-muted-foreground" />}
                                            </div>
                                            <p className="line-clamp-2 text-xs font-medium text-foreground">{source.title}</p>
                                            {source.subtitle && (
                                                <p className="line-clamp-1 text-[11px] text-muted-foreground">{source.subtitle}</p>
                                            )}
                                            {source.snippet && (
                                                <p className="line-clamp-3 text-[11px] leading-relaxed text-foreground/70">
                                                    {source.snippet}
                                                </p>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                            {sources.length > cartoes && (
                                <button
                                    type="button"
                                    onClick={() => setCartoes((atual) => atual + CARTOES_PASSO)}
                                    className="self-start rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                >
                                    Mostrar mais fontes ({sources.length - cartoes} por mostrar)
                                </button>
                            )}
                        </section>
                    )}

                    {(answer || answering) && (
                        <section
                            ref={answerRef}
                            className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm leading-relaxed"
                        >
                            <div className="prose prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 text-foreground/90">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                                {answering && <span className="inline-block h-4 w-2 animate-pulse bg-teal-300/70" />}
                            </div>
                        </section>
                    )}

                    {!answering && followups.length > 0 && (
                        <section className="flex flex-col gap-2">
                            <p className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                                <CornerDownRight size={12} />
                                Perguntas de seguimento
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {followups.map((item) => (
                                    <button
                                        key={item}
                                        type="button"
                                        onClick={() => ask(item)}
                                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                    >
                                        {item}
                                    </button>
                                ))}
                            </div>
                        </section>
                    )}
                </div>
            </div>
        </div>
    );
}
