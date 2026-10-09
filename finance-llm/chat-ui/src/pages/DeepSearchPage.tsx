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
    ArrowLeft,
    Binoculars,
    Boxes,
    CircleStop,
    CornerDownRight,
    Download,
    ExternalLink,
    Focus,
    Layers,
    Loader2,
    Network,
    RefreshCw,
    Search,
    Share2,
    Sparkles,
    X,
} from "lucide-react";

import { API_BASE } from "../api";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import {
    toStudioGraph,
    type GraphMetric,
    type StudioEdge,
    type StudioNode,
} from "../components/graph/graphStudio";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui";
import { MermaidDiagram } from "../components/world/MermaidDiagram";
import type { ContractGraphBuildResponse } from "../types";
import {
    fetchDeepAnalogies,
    fetchDeepAnalysis,
    fetchDeepOntology,
    type DeepAnalogies,
    type DeepAnalysis,
    type DeepAnalysisEngine,
    type DeepGraphNode,
    type DeepOntology,
} from "../deepSearchAnalysisApi";
import {
    DEEP_EXAMPLES,
    askDeepSearch,
    fetchDeepExamples,
    fetchDeepMeta,
    fetchDeepSuggestions,
    type DeepExample,
    type DeepMarketRef,
    type DeepMeta,
    type DeepSource,
    type DeepSuggestion,
    type DeepSourcesEvent,
} from "../deepSearchApi";

// Cartões de fonte desenhados de início e em cada «mostrar mais». Com «sem
// limite» a API devolve centenas de fontes: desenhá-las todas bloqueia a página.
const CARTOES_INICIAIS = 24;
const CARTOES_PASSO = 48;

// Tetos do desenho interativo do grafo da ontologia (ver `grafoVista`).
const GRAFO_MAX_NOS = 40;
const GRAFO_MAX_ARESTAS = 80;

/** Disposições oferecidas pelo canvas (as mesmas do Estúdio de Grafos). */
const GRAFO_LAYOUTS = [
    { valor: "network", rotulo: "Rede" },
    { valor: "hierarchical", rotulo: "Hierárquico" },
    { valor: "circular", rotulo: "Circular" },
] as const;

/** Resumos da dica do canvas — fora do componente para não serem recriados a cada render. */
function resumoNoGrafo(no: StudioNode) {
    return `${no.count} contratos · ${(no.total_value || 0).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

function resumoArestaGrafo(aresta: StudioEdge) {
    return `${aresta.count}× ${(aresta as { label?: string }).label ?? ""}`.trim();
}

/** Valor em euros à portuguesa («15 446,04 €»); vazio quando não há valor. */
const euros = (value?: number | null) =>
    typeof value === "number" && value > 0
        ? new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 2 }).format(value)
        : "";

/** Valor a mostrar no cartão: o preço do contrato ou o total agregado da entidade. */
const valorDaFonte = (source: DeepSource) => euros(source.meta?.preco) || euros(source.meta?.valor);

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
    if (scope === "processo") return "border-teal-400/30 bg-teal-400/10 text-teal-200";
    if (scope === "cpv") return "border-violet-400/30 bg-violet-400/10 text-violet-200";
    if (scope === "tempo") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
    if (scope === "pessoa") return "border-pink-400/30 bg-pink-400/10 text-pink-200";
    return "border-white/15 bg-white/5 text-muted-foreground";
}

/** Rótulo de um nó da ontologia a partir do seu identificador (`tipo|chave`). */
function rotuloDoNo(ontologia: DeepOntology | null, id: string): string {
    return ontologia?.nodes.find((no) => no.id === id)?.label ?? id;
}

/** Nome legível do tipo de nó (`entidade` → «Entidade»). */
const ROTULOS_TIPO: Record<string, string> = {
    entidade: "Entidade",
    processo: "Contrato",
    cpv: "CPV",
    tempo: "Ano",
    pessoa: "Pessoa",
};

function scopeRotulo(tipo: string): string {
    return ROTULOS_TIPO[tipo] ?? tipo;
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
    const [mercado, setMercado] = useState<DeepMarketRef[]>([]);
    const [exemplosDinamicos, setExemplosDinamicos] = useState<DeepExample[] | null>(null);
    // Ontologia, analogias e análise do resultado (separador na página).
    const [aba, setAba] = useState("ontologia");
    const [ontologia, setOntologia] = useState<DeepOntology | null>(null);
    const [analogias, setAnalogias] = useState<DeepAnalogies | null>(null);
    const [analisandoOntologia, setAnalisandoOntologia] = useState(false);
    const [analisandoAnalogias, setAnalisandoAnalogias] = useState(false);
    const [analise, setAnalise] = useState<DeepAnalysis | null>(null);
    const [analisando, setAnalisando] = useState<DeepAnalysisEngine | null>(null);
    const [erroAnalise, setErroAnalise] = useState("");
    const [verMermaid, setVerMermaid] = useState(false);
    // Controlos do separador Grafo: quem filtra e o que se destaca no canvas.
    const [grafoLayout, setGrafoLayout] = useState<(typeof GRAFO_LAYOUTS)[number]["valor"]>("network");
    const [grafoMetrica, setGrafoMetrica] = useState<GraphMetric>("contratos");
    const [grafoVersao, setGrafoVersao] = useState(0);
    const [grafoTipos, setGrafoTipos] = useState<string[] | null>(null);
    const [grafoProcura, setGrafoProcura] = useState("");
    const [noSelecionado, setNoSelecionado] = useState<string | null>(null);
    /** Relações ligadas no filtro (null = todas). */
    const [grafoRelacoes, setGrafoRelacoes] = useState<string[] | null>(null);
    /** Modo foco: mostra apenas o nó selecionado e os seus vizinhos. */
    const [focoAtivo, setFocoAtivo] = useState(false);
    /** Nós visitados, para o botão «voltar» do grafo. */
    const [historicoNos, setHistoricoNos] = useState<string[]>([]);
    const [ordemNos, setOrdemNos] = useState<"contratos" | "valor" | "ligacoes">("contratos");
    const [arestaSelecionada, setArestaSelecionada] = useState<string | null>(null);
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
    /** Contentor do canvas do grafo (exportação PNG). */
    const grafoRef = useRef<HTMLDivElement | null>(null);
    /** Nó selecionado fora do estado, para o histórico não depender do render. */
    const noSelecionadoRef = useRef<string | null>(null);

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

        // Exemplos com dados reais: chegam depois do `/meta` (são agregações) e
        // substituem os de recurso que já estão no ecrã.
        fetchDeepExamples()
            .then((items) => {
                if (alive && items.length) setExemplosDinamicos(items);
            })
            .catch(() => undefined);

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

    // Exemplos: primeiro os que vierem no `/meta` (instantâneo), depois os
    // construídos com os dados indexados; a lista fixa é a última rede.
    const exemplos = useMemo(
        () => exemplosDinamicos ?? meta?.examples ?? DEEP_EXAMPLES,
        [exemplosDinamicos, meta],
    );

    // --- ontologia, analogias e análise do resultado ------------------------

    /** Objectos e relações das fontes (barato: não repete a recuperação). */
    const analisarOntologia = useCallback(async (fontes: DeepSource[]) => {
        if (!fontes.length) return;
        setAnalisandoOntologia(true);
        try {
            setOntologia(await fetchDeepOntology(fontes));
        } catch (erro: unknown) {
            setErroAnalise(erro instanceof Error ? erro.message : String(erro));
        } finally {
            setAnalisandoOntologia(false);
        }
    }, []);

    /** Contratos semelhantes no mercado (kNN do próprio contrato + CPV/valor). */
    const procurarAnalogias = useCallback(async (fontes: DeepSource[]) => {
        if (!fontes.some((fonte) => fonte.scope === "contracts")) return;
        setAnalisandoAnalogias(true);
        try {
            setAnalogias(await fetchDeepAnalogies(fontes));
        } catch (erro: unknown) {
            setErroAnalise(erro instanceof Error ? erro.message : String(erro));
        } finally {
            setAnalisandoAnalogias(false);
        }
    }, []);

    /** Interpretação: pelo modelo escolhido ou pelo agente Hermes. */
    const pedirAnalise = useCallback(
        async (motor: DeepAnalysisEngine, reiniciar = false) => {
            if (!sources.length) return;
            setAnalisando(motor);
            setErroAnalise("");
            if (reiniciar) setAnalise(null);
            try {
                setAnalise(
                    await fetchDeepAnalysis({
                        question,
                        sources,
                        ontology: reiniciar ? null : ontologia,
                        analogies: reiniciar ? null : analogias,
                        engine: motor,
                        backend,
                    }),
                );
            } catch (erro: unknown) {
                setErroAnalise(erro instanceof Error ? erro.message : String(erro));
            } finally {
                setAnalisando(null);
            }
        },
        [analogias, backend, ontologia, question, sources],
    );

    /** Abrir a ficha do objecto de um nó do grafo (empresa, contrato ou pessoa). */
    const abrirNo = useCallback(
        (no: DeepGraphNode) => {
            if (!onNavigate) return;
            if (no.type === "entidade" && /^\d{6,}$/.test(no.key)) {
                onNavigate(`company-detail:${no.key}`);
                return;
            }
            if (no.type === "processo" && no.key) {
                onNavigate(`contract-detail:${no.key}`);
            }
        },
        [onNavigate],
    );

    /** Tipos de objecto presentes na ontologia (para os filtros do grafo). */
    const tiposDoGrafo = useMemo(
        () =>
            (ontologia?.legend ?? []).map((entrada) => ({
                tipo: entrada.type,
                rotulo: entrada.label,
                total: entrada.count,
            })),
        [ontologia],
    );

    const tiposAtivos = useMemo(
        () => grafoTipos ?? tiposDoGrafo.map((entrada) => entrada.tipo),
        [grafoTipos, tiposDoGrafo],
    );

    /** Tipos de ligação presentes na ontologia (para filtrar as relações). */
    const relacoesDoGrafo = useMemo(() => {
        const contagem = new Map<string, number>();
        (ontologia?.edges ?? []).forEach((aresta) => {
            contagem.set(aresta.label, (contagem.get(aresta.label) ?? 0) + 1);
        });
        return [...contagem.entries()]
            .map(([rotulo, total]) => ({ rotulo, total }))
            .sort((a, b) => b.total - a.total);
    }, [ontologia]);

    const relacoesAtivas = useMemo(
        () => grafoRelacoes ?? relacoesDoGrafo.map((entrada) => entrada.rotulo),
        [grafoRelacoes, relacoesDoGrafo],
    );

    /**
     * Grafo para o canvas: filtrado, procurado e limitado.
     *
     * O `GraphCanvas` desenha e anima num `<canvas>`; com o grafo inteiro (até 90
     * nós) entra no caminho «denso» e, nesta página — que já tem a resposta, as
     * fontes e a referência de mercado acesas —, chegava a prender o browser. O
     * desenho fica com os 40 nós com mais contratos, e a procura, os filtros e a
     * lista de objectos servem para chegar aos outros (o Mermaid mostra tudo).
     */
    const grafoVista = useMemo(() => {
        if (!ontologia) return null;
        const tipos = new Set(tiposAtivos);
        const relacoes = new Set(relacoesAtivas);
        const filtrouRelacoes = relacoes.size !== relacoesDoGrafo.length;

        let nos = ontologia.nodes.filter((no) => tipos.has(no.type));
        let arestas = ontologia.edges.filter((aresta) => relacoes.has(aresta.label));

        /** Fica só com os nós indicados e as ligações que os unem. */
        const restringir = (ids: Set<string>) => {
            nos = nos.filter((no) => ids.has(no.id));
            arestas = arestas.filter((aresta) => ids.has(aresta.source) && ids.has(aresta.target));
        };

        const termo = grafoProcura.trim().toLowerCase();
        if (termo) {
            const diretos = new Set(
                nos.filter((no) => no.label.toLowerCase().includes(termo)).map((no) => no.id),
            );
            // Com a vizinhança de um salto: procurar «MEDTRONIC» mostra também quem
            // contrata com ela, senão o grafo perdia o contexto. Sem correspondências
            // o grafo fica vazio e a página di-lo.
            const alcance = new Set(diretos);
            arestas.forEach((aresta) => {
                if (diretos.has(aresta.source)) alcance.add(aresta.target);
                if (diretos.has(aresta.target)) alcance.add(aresta.source);
            });
            restringir(alcance);
        }

        if (focoAtivo && noSelecionado) {
            const alcance = new Set<string>([noSelecionado]);
            arestas.forEach((aresta) => {
                if (aresta.source === noSelecionado) alcance.add(aresta.target);
                if (aresta.target === noSelecionado) alcance.add(aresta.source);
            });
            restringir(alcance);
        }

        if (filtrouRelacoes) {
            // Com relações filtradas, um objecto sem nenhuma das ligações escolhidas
            // só continua no desenho se for a própria seleção (não perder o foco).
            const ligados = new Set<string>();
            arestas.forEach((aresta) => {
                ligados.add(aresta.source);
                ligados.add(aresta.target);
            });
            nos = nos.filter((no) => ligados.has(no.id) || no.id === noSelecionado);
        }

        const disponiveis = nos.length;
        const escolhidos = [...nos]
            .sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || (b.total_value ?? 0) - (a.total_value ?? 0))
            .slice(0, GRAFO_MAX_NOS);
        const mantidos = new Set(escolhidos.map((no) => no.id));
        const visiveis = arestas
            .filter((aresta) => mantidos.has(aresta.source) && mantidos.has(aresta.target))
            .sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
            .slice(0, GRAFO_MAX_ARESTAS);

        /** Grau de cada nó **no desenho atual** (para ordenar a lista). */
        const grau = new Map<string, number>();
        visiveis.forEach((aresta) => {
            grau.set(aresta.source, (grau.get(aresta.source) ?? 0) + 1);
            grau.set(aresta.target, (grau.get(aresta.target) ?? 0) + 1);
        });

        return {
            grafo: toStudioGraph(
                { ...ontologia, nodes: escolhidos, edges: visiveis } as unknown as ContractGraphBuildResponse,
                grafoMetrica,
            ),
            nos: escolhidos,
            arestas: visiveis,
            grau,
            disponiveis,
            desenhados: escolhidos.length,
            ligacoes: visiveis.length,
        };
    }, [ontologia, tiposAtivos, relacoesAtivas, relacoesDoGrafo.length, grafoProcura, focoAtivo, noSelecionado, grafoMetrica]);

    const grafoStudio = grafoVista?.grafo ?? null;

    const noAtual = useMemo(
        () => (ontologia && noSelecionado ? ontologia.nodes.find((no) => no.id === noSelecionado) ?? null : null),
        [ontologia, noSelecionado],
    );

    /** Ligações do nó selecionado, com o objecto do outro lado de cada uma. */
    const ligacoesDoNo = useMemo(() => {
        if (!ontologia || !noSelecionado) return [];
        return ontologia.edges
            .filter((aresta) => aresta.source === noSelecionado || aresta.target === noSelecionado)
            .sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
            .slice(0, 8)
            .map((aresta) => ({
                id: aresta.id,
                rotulo: aresta.label,
                vizinho: aresta.source === noSelecionado ? aresta.target : aresta.source,
                contratos: aresta.count ?? 0,
            }));
    }, [ontologia, noSelecionado]);

    /** Ligar/desligar um tipo no filtro (nunca deixa o grafo sem tipos). */
    const alternarTipo = useCallback(
        (tipo: string) => {
            setGrafoTipos((atual) => {
                const base = atual ?? tiposDoGrafo.map((entrada) => entrada.tipo);
                const seguinte = base.includes(tipo)
                    ? base.filter((item) => item !== tipo)
                    : [...base, tipo];
                if (seguinte.length === 0) return atual;
                return seguinte.length === tiposDoGrafo.length ? null : seguinte;
            });
        },
        [tiposDoGrafo],
    );

    /**
     * Exporta o desenho como PNG.
     *
     * O fundo do canvas vem do CSS e não do bitmap: copia-se o desenho para um
     * canvas com fundo sólido, senão a imagem saía transparente (ilegível em
     * documentos com fundo branco).
     */
    const transferirGrafo = useCallback(() => {
        const origem = grafoRef.current?.querySelector("canvas");
        if (!origem) return;
        const destino = document.createElement("canvas");
        destino.width = origem.width;
        destino.height = origem.height;
        const alvo = destino.getContext("2d");
        if (!alvo) return;
        alvo.fillStyle = "#07151b";
        alvo.fillRect(0, 0, destino.width, destino.height);
        alvo.drawImage(origem, 0, 0);
        const ligacao = document.createElement("a");
        ligacao.href = destino.toDataURL("image/png");
        ligacao.download = `grafo-ontologia-${Date.now()}.png`;
        ligacao.click();
    }, []);

    /** Ligar/desligar um tipo de ligação (nunca deixa o grafo sem relações). */
    const alternarRelacao = useCallback(
        (rotulo: string) => {
            setGrafoRelacoes((atual) => {
                const base = atual ?? relacoesDoGrafo.map((entrada) => entrada.rotulo);
                const seguinte = base.includes(rotulo)
                    ? base.filter((item) => item !== rotulo)
                    : [...base, rotulo];
                if (seguinte.length === 0) return atual;
                return seguinte.length === relacoesDoGrafo.length ? null : seguinte;
            });
        },
        [relacoesDoGrafo],
    );

    /**
     * Selecionar um nó, guardando o anterior para o botão «voltar».
     *
     * O nó atual fica também num `ref`: assim o histórico não depende do estado
     * (e não é preciso chamar `setState` dentro de outro `setState`).
     */
    const selecionarNo = useCallback((id: string | null) => {
        const anterior = noSelecionadoRef.current;
        if (id && anterior && anterior !== id) {
            setHistoricoNos((pilha) => [...pilha, anterior].slice(-12));
        }
        noSelecionadoRef.current = id;
        setNoSelecionado(id);
        setArestaSelecionada(null);
    }, []);

    const voltarNo = useCallback(() => {
        if (historicoNos.length === 0) return;
        const anterior = historicoNos[historicoNos.length - 1];
        setHistoricoNos((pilha) => pilha.slice(0, -1));
        noSelecionadoRef.current = anterior;
        setNoSelecionado(anterior);
    }, [historicoNos]);

    /** Objectos visíveis ordenados pelo critério escolhido (clique seleciona). */
    const listaNos = useMemo(() => {
        if (!grafoVista) return [];
        const chave = (no: DeepGraphNode) =>
            ordemNos === "valor"
                ? no.total_value ?? 0
                : ordemNos === "ligacoes"
                  ? grafoVista.grau.get(no.id) ?? 0
                  : no.count ?? 0;
        return [...grafoVista.nos].sort((a, b) => chave(b) - chave(a)).slice(0, 12);
    }, [grafoVista, ordemNos]);

    /** Ligação selecionada no canvas (origem, destino, tipo e volume). */
    const arestaAtual = useMemo(
        () =>
            grafoVista && arestaSelecionada
                ? grafoVista.arestas.find((aresta) => aresta.id === arestaSelecionada) ?? null
                : null,
        [grafoVista, arestaSelecionada],
    );

    /**
     * Exporta as ligações visíveis (CSV).
     *
     * Separador `;` e BOM UTF-8: é assim que o Excel em português abre as colunas
     * no sítio certo e com os acentos, sem pedir importação manual.
     */
    const transferirCsv = useCallback(() => {
        if (!grafoVista) return;
        const rotulo = (id: string) => ontologia?.nodes.find((no) => no.id === id)?.label ?? id;
        const linhas = [
            "origem;tipo_ligacao;destino;contratos;valor",
            ...grafoVista.arestas.map((aresta) =>
                [
                    rotulo(aresta.source),
                    aresta.label,
                    rotulo(aresta.target),
                    aresta.count ?? 0,
                    Math.round(aresta.value ?? 0),
                ]
                    .map((campo) => `"${String(campo).replace(/"/g, '""')}"`)
                    .join(";"),
            ),
        ];
        const blob = new Blob(["\ufeff" + linhas.join("\r\n")], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const ligacao = document.createElement("a");
        ligacao.href = url;
        ligacao.download = `grafo-ligacoes-${Date.now()}.csv`;
        ligacao.click();
        URL.revokeObjectURL(url);
    }, [grafoVista, ontologia]);

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
            setMercado([]);
            setOntologia(null);
            setAnalogias(null);
            setAnalise(null);
            setErroAnalise("");
            setAba("ontologia");
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
                        const finais = payload.sources?.length ? payload.sources : sources;
                        if (payload.sources?.length) setSources(payload.sources);
                        if (payload.citations) setCited(payload.citations);
                        setFollowups(payload.suggestions ?? []);
                        setMercado(payload.mercado ?? []);
                        // Objectos e analogias do resultado: pedem-se depois de a
                        // resposta estar fechada, para não competir com ela.
                        void analisarOntologia(finais);
                        void procurarAnalogias(finais);
                    },
                    onError: (message) => {
                        setAnswering(false);
                        setError(message);
                    },
                },
            );
        },
        [analisarOntologia, answering, backend, chosenSources, maxSources, mode, procurarAnalogias, question],
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
                            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                                Exemplos de perguntas
                            </p>
                            <p className="mb-3 text-[10.5px] text-muted-foreground">
                                Construídos a partir dos dados indexados (contratos, empresas, imprensa e notícias) —
                                mudam à medida que os dados mudam.
                            </p>
                            <div className="grid gap-2 sm:grid-cols-2">
                                {exemplos.map((example) => (
                                    <button
                                        key={example.text}
                                        type="button"
                                        onClick={() => ask(example.text)}
                                        className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-xs text-foreground/80 transition hover:border-teal-400/30 hover:text-foreground"
                                    >
                                        <Search size={14} className="mt-0.5 shrink-0 text-teal-300" />
                                        <span className="flex min-w-0 flex-col gap-0.5">
                                            <span>{example.text}</span>
                                            {example.hint && (
                                                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                                    {example.hint}
                                                </span>
                                            )}
                                        </span>
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
                            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                                {sources.slice(0, cartoes).map((source) => {
                                    const clickable = Boolean(source.url) || Boolean(source.open?.arg);
                                    const valor = valorDaFonte(source);
                                    const ligacoes = source.links ?? [];
                                    return (
                                        // Não é um <button>: dentro do cartão há ligações
                                        // («Contrato», «Adjudicatário») que são botões.
                                        <div
                                            key={`${source.scope}-${source.id}-${source.n}`}
                                            id={`fonte-${source.n}`}
                                            className={`flex min-w-0 flex-col gap-1 overflow-hidden rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left transition ${
                                                clickable ? "hover:border-teal-400/40" : ""
                                            }`}
                                        >
                                            <div className="flex min-w-0 items-center gap-2">
                                                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-teal-400/30 bg-teal-400/10 text-[10px] font-semibold text-teal-100">
                                                    {source.n}
                                                </span>
                                                <span
                                                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${scopeBadgeClass(source.scope)}`}
                                                >
                                                    {source.scope_label}
                                                </span>
                                                {source.date && (
                                                    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">{source.date}</span>
                                                )}
                                                {clickable && <ExternalLink size={12} className="shrink-0 text-muted-foreground" />}
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => clickable && openSource(source)}
                                                className={`min-w-0 text-left ${clickable ? "cursor-pointer" : "cursor-default"}`}
                                            >
                                                <span className="line-clamp-2 break-words text-xs font-medium text-foreground">
                                                    {source.title}
                                                </span>
                                            </button>
                                            {valor && (
                                                <p className="text-[11.5px] font-semibold text-teal-200">
                                                    {valor}
                                                    {source.meta?.cpv && (
                                                        <span className="ml-1 font-normal text-muted-foreground">
                                                            · CPV {source.meta.cpv}
                                                        </span>
                                                    )}
                                                </p>
                                            )}
                                            {source.subtitle && (
                                                <p className="line-clamp-1 break-words text-[11px] text-muted-foreground">{source.subtitle}</p>
                                            )}
                                            {source.snippet && (
                                                <p className="line-clamp-3 break-words text-[11px] leading-relaxed text-foreground/70">
                                                    {source.snippet}
                                                </p>
                                            )}
                                            {ligacoes.length > 0 && (
                                                <div className="mt-0.5 flex min-w-0 flex-col gap-0.5 border-t border-white/10 pt-1.5">
                                                    {ligacoes.map((ligacao) => (
                                                        <div
                                                            key={`${ligacao.label}-${ligacao.arg || ligacao.text}`}
                                                            className="flex min-w-0 items-baseline gap-1.5 text-[11px]"
                                                        >
                                                            <span className="w-[7.5rem] shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                                                                {ligacao.label}
                                                            </span>
                                                            {ligacao.view && ligacao.arg && onNavigate ? (
                                                                <button
                                                                    type="button"
                                                                    onClick={() =>
                                                                        onNavigate(`${ligacao.view}:${ligacao.arg}`)
                                                                    }
                                                                    className="min-w-0 flex-1 truncate text-left text-teal-200 underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                >
                                                                    {ligacao.text || ligacao.arg}
                                                                </button>
                                                            ) : (
                                                                <span className="min-w-0 flex-1 truncate text-foreground/80">
                                                                    {ligacao.text || ligacao.arg}
                                                                </span>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
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

                    {mercado.length > 0 && (
                        <section className="flex flex-col gap-2 rounded-2xl border border-teal-400/15 bg-teal-400/[0.04] p-4">
                            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                Referência de mercado · mesmo CPV, todos os anos
                            </p>
                            <div className="flex flex-col gap-1.5">
                                {mercado.map((ref) => (
                                    <div key={ref.cpv} className="flex flex-wrap items-baseline gap-x-3 text-[11.5px]">
                                        <span className="font-medium text-foreground/90">CPV {ref.cpv}</span>
                                        <span className="text-muted-foreground">
                                            {ref.contratos.toLocaleString("pt-PT")} contratos adjudicados
                                        </span>
                                        <span className="font-medium text-teal-200">mediana {ref.mediana}</span>
                                        <span className="text-muted-foreground">
                                            p25 {ref.p25} · p75 {ref.p75} · máximo {ref.maximo}
                                        </span>
                                    </div>
                                ))}
                            </div>
                            <p className="text-[10.5px] leading-relaxed text-muted-foreground">
                                Preços adjudicados no Portal Base para o mesmo CPV. É a referência que a resposta usa
                                para dizer se um destes contratos está acima ou abaixo do habitual.
                            </p>
                        </section>
                    )}

                    {(answer || answering) && (
                        <section
                            ref={answerRef}
                            className="min-w-0 overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm leading-relaxed"
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

                    {/* Ontologia, analogias e análise do resultado: objectos e
                        relações reais dos contratos, os contratos semelhantes no
                        mercado e a interpretação (modelo ou agente Hermes). */}
                    {(sources.length > 0 || analisandoOntologia || analisandoAnalogias) && (
                        <section className="flex min-w-0 flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                    Ontologia, analogias e análise
                                </p>
                                {ontologia && (
                                    <p className="text-[11px] text-muted-foreground">
                                        {ontologia.totals.nodes} objectos · {ontologia.totals.edges} relações ·{" "}
                                        {ontologia.totals.contracts} contratos
                                    </p>
                                )}
                                {analogias && analogias.totals.analogues > 0 && (
                                    <p className="text-[11px] text-muted-foreground">
                                        {analogias.totals.analogues} semelhantes
                                        {analogias.totals.semantic > 0
                                            ? ` (${analogias.totals.semantic} por semelhança semântica)`
                                            : ""}
                                    </p>
                                )}
                            </div>

                            {erroAnalise && (
                                <p className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[11.5px] text-rose-100">
                                    {erroAnalise}
                                </p>
                            )}

                            <Tabs value={aba}>
                                <TabsList className="flex w-full flex-wrap">
                                    <TabsTrigger value="ontologia" active={aba === "ontologia"} onClick={() => setAba("ontologia")}>
                                        <span className="flex items-center gap-1.5">
                                            <Boxes size={13} /> Ontologia
                                        </span>
                                    </TabsTrigger>
                                    <TabsTrigger value="grafo" active={aba === "grafo"} onClick={() => setAba("grafo")}>
                                        <span className="flex items-center gap-1.5">
                                            <Network size={13} /> Grafo
                                        </span>
                                    </TabsTrigger>
                                    <TabsTrigger value="analogias" active={aba === "analogias"} onClick={() => setAba("analogias")}>
                                        <span className="flex items-center gap-1.5">
                                            <Share2 size={13} /> Analogias
                                            {analogias ? ` (${analogias.totals.analogues})` : ""}
                                        </span>
                                    </TabsTrigger>
                                    <TabsTrigger value="analise" active={aba === "analise"} onClick={() => setAba("analise")}>
                                        <span className="flex items-center gap-1.5">
                                            <Sparkles size={13} /> Análise
                                        </span>
                                    </TabsTrigger>
                                </TabsList>

                                <TabsContent value="ontologia" active={aba === "ontologia"} className="min-w-0 pt-3">
                                    {analisandoOntologia && (
                                        <p className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
                                            <Loader2 size={13} className="animate-spin" /> A construir a ontologia…
                                        </p>
                                    )}
                                    {ontologia && (
                                        <div className="flex flex-col gap-3">
                                            <div className="flex flex-wrap gap-1.5">
                                                {ontologia.legend.map((entrada) => (
                                                    <span
                                                        key={entrada.type}
                                                        className={`rounded-full border px-2 py-0.5 text-[10.5px] ${scopeBadgeClass(entrada.type)}`}
                                                    >
                                                        {entrada.label} · {entrada.count}
                                                    </span>
                                                ))}
                                            </div>

                                            <div className="flex flex-col gap-1">
                                                <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                                                    Objectos com mais contratos
                                                </p>
                                                {ontologia.nodes.slice(0, 10).map((no) => {
                                                    const abre = no.type === "entidade" && /^\d{6,}$/.test(no.key);
                                                    const abreContrato = no.type === "processo" && Boolean(no.key);
                                                    return (
                                                        <div key={no.id} className="grid min-w-0 grid-cols-[3.5rem_minmax(0,1fr)_auto] items-baseline gap-2 text-[11.5px]">
                                                            <span className="text-[10px] uppercase text-muted-foreground">
                                                                {no.type}
                                                            </span>
                                                            {abre || abreContrato ? (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => abrirNo(no)}
                                                                    className="min-w-0 break-words text-left text-teal-200 underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                >
                                                                    {no.label}
                                                                </button>
                                                            ) : (
                                                                <span className="min-w-0 break-words text-foreground/80">{no.label}</span>
                                                            )}
                                                            <span className="shrink-0 text-right text-muted-foreground">
                                                                {no.count} · {(no.total_value || 0).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €
                                                            </span>
                                                        </div>
                                                    );
                                                })}
                                            </div>

                                            <div className="flex flex-col gap-1">
                                                <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                                                    Relações mais fortes
                                                </p>
                                                {ontologia.edges.slice(0, 10).map((aresta) => (
                                                    <p key={aresta.id} className="break-words text-[11.5px] text-foreground/80">
                                                        <span className="text-muted-foreground">
                                                            {rotuloDoNo(ontologia, aresta.source)}
                                                        </span>{" "}
                                                        <span className="text-teal-200">—{aresta.label}→</span>{" "}
                                                        <span className="text-muted-foreground">
                                                            {rotuloDoNo(ontologia, aresta.target)}
                                                        </span>{" "}
                                                        <span className="text-[10.5px] text-muted-foreground">({aresta.count})</span>
                                                    </p>
                                                ))}
                                            </div>

                                            {ontologia.meta.notes?.length > 0 && (
                                                <ul className="flex flex-col gap-0.5 text-[10.5px] text-muted-foreground">
                                                    {ontologia.meta.notes.map((nota) => (
                                                        <li key={nota}>· {nota}</li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    )}
                                </TabsContent>

                                <TabsContent value="grafo" active={aba === "grafo"} className="min-w-0 pt-3">
                                    {grafoStudio && grafoVista ? (
                                        <div className="flex min-w-0 flex-col gap-2.5">
                                            <div className="flex flex-wrap items-center gap-1.5">
                                                <div
                                                    role="group"
                                                    aria-label="Disposição do grafo"
                                                    className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1"
                                                >
                                                    {GRAFO_LAYOUTS.map((opcao) => (
                                                        <button
                                                            key={opcao.valor}
                                                            type="button"
                                                            aria-pressed={grafoLayout === opcao.valor}
                                                            onClick={() => setGrafoLayout(opcao.valor)}
                                                            className={`min-h-[32px] rounded-lg px-2.5 text-[11.5px] transition ${
                                                                grafoLayout === opcao.valor
                                                                    ? "bg-teal-500/20 text-teal-100"
                                                                    : "text-muted-foreground hover:text-foreground"
                                                            }`}
                                                        >
                                                            {opcao.rotulo}
                                                        </button>
                                                    ))}
                                                </div>
                                                <div
                                                    role="group"
                                                    aria-label="Métrica do grafo"
                                                    className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1"
                                                >
                                                    {(
                                                        [
                                                            { valor: "contratos", rotulo: "Contratos" },
                                                            { valor: "valor", rotulo: "Valor" },
                                                        ] as const
                                                    ).map((opcao) => (
                                                        <button
                                                            key={opcao.valor}
                                                            type="button"
                                                            aria-pressed={grafoMetrica === opcao.valor}
                                                            onClick={() => setGrafoMetrica(opcao.valor)}
                                                            className={`min-h-[32px] rounded-lg px-2.5 text-[11.5px] transition ${
                                                                grafoMetrica === opcao.valor
                                                                    ? "bg-teal-500/20 text-teal-100"
                                                                    : "text-muted-foreground hover:text-foreground"
                                                            }`}
                                                        >
                                                            {opcao.rotulo}
                                                        </button>
                                                    ))}
                                                </div>
                                                {!verMermaid && (
                                                    <>
                                                        <button
                                                            type="button"
                                                            onClick={() => setGrafoVersao((versao) => versao + 1)}
                                                            title="Voltar a dispor os nós a partir do zero"
                                                            className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                                        >
                                                            <RefreshCw size={13} /> Recalcular
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={transferirGrafo}
                                                            title="Transferir o desenho como imagem PNG"
                                                            className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                                        >
                                                            <Download size={13} /> PNG
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={transferirCsv}
                                                            title="Transferir as ligações visíveis (CSV para folha de cálculo)"
                                                            className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                                        >
                                                            <Download size={13} /> CSV
                                                        </button>
                                                        {noSelecionado && (
                                                            <button
                                                                type="button"
                                                                aria-pressed={focoAtivo}
                                                                onClick={() => setFocoAtivo((atual) => !atual)}
                                                                title={
                                                                    focoAtivo
                                                                        ? "Voltar a mostrar todos os objectos"
                                                                        : "Ver apenas este objecto e os seus vizinhos"
                                                                }
                                                                className={`flex min-h-[36px] items-center gap-1.5 rounded-xl border px-2.5 text-[11.5px] transition ${
                                                                    focoAtivo
                                                                        ? "border-teal-400/40 bg-teal-500/20 text-teal-100"
                                                                        : "border-white/10 bg-white/[0.03] text-foreground/80 hover:border-teal-400/40 hover:text-foreground"
                                                                }`}
                                                            >
                                                                <Focus size={13} /> {focoAtivo ? "Vizinh\u00e7a" : "Isolar"}
                                                            </button>
                                                        )}
                                                        {historicoNos.length > 0 && (
                                                            <button
                                                                type="button"
                                                                onClick={voltarNo}
                                                                title="Voltar ao objecto anterior"
                                                                className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                                            >
                                                                <ArrowLeft size={13} /> Voltar
                                                            </button>
                                                        )}
                                                    </>
                                                )}
                                                <button
                                                    type="button"
                                                    onClick={() => setVerMermaid((atual) => !atual)}
                                                    className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 hover:text-foreground"
                                                >
                                                    {verMermaid ? "Ver grafo interativo" : "Ver diagrama Mermaid"}
                                                </button>
                                            </div>

                                            {!verMermaid && (
                                                <>
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5">
                                                            <Search size={13} className="shrink-0 text-muted-foreground" />
                                                            <input
                                                                value={grafoProcura}
                                                                onChange={(evento) => setGrafoProcura(evento.target.value)}
                                                                autoComplete="off"
                                                                placeholder="Procurar objecto no grafo (empresa, contrato, CPV…)"
                                                                className="min-w-0 flex-1 bg-transparent text-[12px] text-foreground outline-none placeholder:text-muted-foreground"
                                                            />
                                                            {grafoProcura && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => setGrafoProcura("")}
                                                                    aria-label="Limpar procura"
                                                                    className="shrink-0 text-muted-foreground hover:text-foreground"
                                                                >
                                                                    <X size={13} />
                                                                </button>
                                                            )}
                                                        </label>
                                                        <span className="shrink-0 text-[10.5px] text-muted-foreground">
                                                            {grafoVista.desenhados} de {grafoVista.disponiveis} nós ·{" "}
                                                            {grafoVista.ligacoes} ligações
                                                        </span>
                                                    </div>

                                                    {tiposDoGrafo.length > 1 && (
                                                        <div className="flex flex-wrap items-center gap-1.5">
                                                            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                                                Objectos
                                                            </span>
                                                            {tiposDoGrafo.map((entrada) => {
                                                                const ligado = tiposAtivos.includes(entrada.tipo);
                                                                const cor =
                                                                    grafoStudio?.nodes.find((no) => no.type === entrada.tipo)?.color ??
                                                                    "#94a3b8";
                                                                return (
                                                                    <button
                                                                        key={entrada.tipo}
                                                                        type="button"
                                                                        aria-pressed={ligado}
                                                                        title={
                                                                            ligado
                                                                                ? `Ocultar ${entrada.rotulo} no desenho`
                                                                                : `Mostrar ${entrada.rotulo} no desenho`
                                                                        }
                                                                        onClick={() => alternarTipo(entrada.tipo)}
                                                                        className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10.5px] transition ${
                                                                            ligado
                                                                                ? scopeBadgeClass(entrada.tipo)
                                                                                : "border-white/10 bg-white/[0.02] text-muted-foreground opacity-60"
                                                                        }`}
                                                                    >
                                                                        <span
                                                                            aria-hidden="true"
                                                                            className="h-2 w-2 shrink-0 rounded-full"
                                                                            style={{ backgroundColor: cor }}
                                                                        />
                                                                        {entrada.rotulo} · {entrada.total}
                                                                    </button>
                                                                );
                                                            })}
                                                        </div>
                                                    )}

                                                    {relacoesDoGrafo.length > 1 && (
                                                        <div className="flex flex-wrap items-center gap-1.5">
                                                            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                                                Ligações
                                                            </span>
                                                            {relacoesDoGrafo.map((entrada) => {
                                                                const ligada = relacoesAtivas.includes(entrada.rotulo);
                                                                return (
                                                                    <button
                                                                        key={entrada.rotulo}
                                                                        type="button"
                                                                        aria-pressed={ligada}
                                                                        title={
                                                                            ligada
                                                                                ? `Ocultar as ligações «${entrada.rotulo}»`
                                                                                : `Mostrar as ligações «${entrada.rotulo}»`
                                                                        }
                                                                        onClick={() => alternarRelacao(entrada.rotulo)}
                                                                        className={`rounded-full border px-2 py-0.5 text-[10.5px] transition ${
                                                                            ligada
                                                                                ? "border-blue-400/30 bg-blue-400/10 text-blue-100"
                                                                                : "border-white/10 bg-white/[0.02] text-muted-foreground opacity-60"
                                                                        }`}
                                                                    >
                                                                        {entrada.rotulo} · {entrada.total}
                                                                    </button>
                                                                );
                                                            })}
                                                        </div>
                                                    )}

                                                    {grafoVista.nos.length > 0 && (
                                                        <details className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                                                            <summary className="cursor-pointer text-[11px] text-muted-foreground">
                                                                Objectos no desenho ({grafoVista.nos.length}) — clique para selecionar no
                                                                grafo
                                                            </summary>
                                                            <div className="mt-2 flex flex-col gap-1.5">
                                                                <div className="flex flex-wrap items-center gap-1">
                                                                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                                                        Ordenar por
                                                                    </span>
                                                                    {(
                                                                        [
                                                                            { valor: "contratos", rotulo: "Contratos" },
                                                                            { valor: "valor", rotulo: "Valor" },
                                                                            { valor: "ligacoes", rotulo: "Ligações" },
                                                                        ] as const
                                                                    ).map((opcao) => (
                                                                        <button
                                                                            key={opcao.valor}
                                                                            type="button"
                                                                            aria-pressed={ordemNos === opcao.valor}
                                                                            onClick={() => setOrdemNos(opcao.valor)}
                                                                            className={`min-h-[30px] rounded-lg px-2 text-[11px] transition ${
                                                                                ordemNos === opcao.valor
                                                                                    ? "bg-teal-500/20 text-teal-100"
                                                                                    : "text-muted-foreground hover:text-foreground"
                                                                            }`}
                                                                        >
                                                                            {opcao.rotulo}
                                                                        </button>
                                                                    ))}
                                                                </div>
                                                                {listaNos.map((no) => {
                                                                    const ligacoesNo = grafoVista.grau.get(no.id) ?? 0;
                                                                    return (
                                                                        <div
                                                                            key={no.id}
                                                                            className={`grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-2 text-[11.5px] ${
                                                                                no.id === noSelecionado ? "text-teal-100" : ""
                                                                            }`}
                                                                        >
                                                                            <button
                                                                                type="button"
                                                                                onClick={() => selecionarNo(no.id)}
                                                                                className="min-w-0 break-words text-left underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                            >
                                                                                {no.label}
                                                                            </button>
                                                                            <span className="shrink-0 text-right text-[10.5px] text-muted-foreground">
                                                                                {no.count ?? 0} contratos ·{" "}
                                                                                {(no.total_value ?? 0).toLocaleString("pt-PT", {
                                                                                    maximumFractionDigits: 0,
                                                                                })}{" "}
                                                                                € · {ligacoesNo} lig.
                                                                            </span>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                        </details>
                                                    )}
                                                </>
                                            )}

                                            {verMermaid ? (
                                                <div className="min-w-0 overflow-x-auto">
                                                    <MermaidDiagram
                                                        code={ontologia?.mermaid || ""}
                                                        title="Ontologia da resposta"
                                                        height={460}
                                                        compact
                                                    />
                                                </div>
                                            ) : grafoVista.disponiveis === 0 ? (
                                                <p className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-6 text-center text-[11.5px] text-muted-foreground">
                                                    {grafoProcura.trim()
                                                        ? `Nenhum objecto do grafo corresponde a «${grafoProcura.trim()}».`
                                                        : "Sem objectos para os filtros escolhidos."}
                                                </p>
                                            ) : (
                                                <>
                                                    <div
                                                        ref={grafoRef}
                                                        className="h-[320px] w-full min-w-0 overflow-hidden sm:h-[460px]"
                                                    >
                                                        <GraphCanvas
                                                            graph={grafoStudio}
                                                            layout={grafoLayout}
                                                            metric={grafoMetrica}
                                                            layoutVersion={grafoVersao}
                                                            selectedNodeId={noSelecionado}
                                                            heightClass="h-full"
                                                            unitLabel={grafoMetrica === "valor" ? "€" : "contratos"}
                                                            onNodeClick={(no) => selecionarNo(no.id)}
                                                            onEdgeClick={(aresta) =>
                                                                setArestaSelecionada(
                                                                    (aresta as { id?: string }).id ??
                                                                        `${aresta.source}->${aresta.target}`,
                                                                )
                                                            }
                                                            nodeSummary={resumoNoGrafo}
                                                            edgeSummary={resumoArestaGrafo}
                                                        />
                                                    </div>

                                                    {noAtual ? (
                                                        <div className="flex min-w-0 flex-col gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3">
                                                            <div className="flex flex-wrap items-start justify-between gap-2">
                                                                <div className="min-w-0 flex-1">
                                                                    <p className="break-words text-[12.5px] font-medium text-foreground">
                                                                        {noAtual.label}
                                                                    </p>
                                                                    <p className="break-words text-[10.5px] text-muted-foreground">
                                                                        {scopeRotulo(noAtual.type)} · {noAtual.count ?? 0} contratos ·{" "}
                                                                        {(noAtual.total_value ?? 0).toLocaleString("pt-PT", {
                                                                            maximumFractionDigits: 0,
                                                                        })}{" "}
                                                                        €
                                                                        {noAtual.cae ? ` · CAE ${noAtual.cae}` : ""}
                                                                        {noAtual.global_contracts
                                                                            ? ` · ${noAtual.global_contracts} contratos no índice`
                                                                            : ""}
                                                                    </p>
                                                                </div>
                                                                <div className="flex shrink-0 items-center gap-1.5">
                                                                    {(noAtual.type === "entidade" || noAtual.type === "processo") && (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => abrirNo(noAtual)}
                                                                            className="flex min-h-[36px] items-center gap-1.5 rounded-lg border border-teal-400/40 bg-teal-500/15 px-2.5 text-[11.5px] text-teal-100 transition hover:bg-teal-500/25"
                                                                        >
                                                                            <ExternalLink size={12} />
                                                                            {noAtual.type === "processo" ? "Abrir contrato" : "Abrir ficha"}
                                                                        </button>
                                                                    )}
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => selecionarNo(null)}
                                                                        aria-label="Limpar seleção"
                                                                        className="flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-muted-foreground transition hover:text-foreground"
                                                                    >
                                                                        <X size={13} />
                                                                    </button>
                                                                </div>
                                                            </div>

                                                            {ligacoesDoNo.length > 0 ? (
                                                                <div className="flex flex-col gap-0.5">
                                                                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                                                        Ligações ({ligacoesDoNo.length})
                                                                    </p>
                                                                    {ligacoesDoNo.map((ligacao) => (
                                                                        <p key={ligacao.id} className="min-w-0 break-words text-[11.5px]">
                                                                            <span className="text-teal-200">{ligacao.rotulo}</span>{" "}
                                                                            <span className="text-muted-foreground">→</span>{" "}
                                                                            <button
                                                                                type="button"
                                                                                onClick={() => setNoSelecionado(ligacao.vizinho)}
                                                                                className="text-left text-foreground/85 underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                            >
                                                                                {rotuloDoNo(ontologia, ligacao.vizinho)}
                                                                            </button>{" "}
                                                                            <span className="text-[10.5px] text-muted-foreground">
                                                                                ({ligacao.contratos})
                                                                            </span>
                                                                        </p>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <p className="text-[10.5px] text-muted-foreground">
                                                                    Sem ligações na ontologia para este objecto (aparece pelo
                                                                    valor próprio, por exemplo um ano).
                                                                </p>
                                                            )}
                                                        </div>
                                                    ) : (
                                                        <span className="text-[10.5px] text-muted-foreground">
                                                            clique num nó (ou numa ligação) para ver detalhes e vizinhos · roda
                                                            para ampliar · arraste para mover
                                                        </span>
                                                    )}

                                                    {arestaAtual && (
                                                        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-blue-400/20 bg-blue-400/[0.06] px-3 py-2">
                                                            <p className="min-w-0 break-words text-[11.5px] text-foreground/85">
                                                                <button
                                                                    type="button"
                                                                    onClick={() => selecionarNo(arestaAtual.source)}
                                                                    className="underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                >
                                                                    {rotuloDoNo(ontologia, arestaAtual.source)}
                                                                </button>{" "}
                                                                <span className="text-blue-200">
                                                                    —{arestaAtual.label}→
                                                                </span>{" "}
                                                                <button
                                                                    type="button"
                                                                    onClick={() => selecionarNo(arestaAtual.target)}
                                                                    className="underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                                >
                                                                    {rotuloDoNo(ontologia, arestaAtual.target)}
                                                                </button>{" "}
                                                                <span className="text-[10.5px] text-muted-foreground">
                                                                    {arestaAtual.count} contratos ·{" "}
                                                                    {Math.round(arestaAtual.value ?? 0).toLocaleString("pt-PT")} €
                                                                </span>
                                                            </p>
                                                            <button
                                                                type="button"
                                                                onClick={() => setArestaSelecionada(null)}
                                                                aria-label="Limpar ligação selecionada"
                                                                className="flex min-h-[32px] min-w-[32px] shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-muted-foreground transition hover:text-foreground"
                                                            >
                                                                <X size={13} />
                                                            </button>
                                                        </div>
                                                    )}

                                                    {grafoVista.desenhados < grafoVista.disponiveis && (
                                                        <span className="text-[10.5px] text-muted-foreground">
                                                            O desenho mostra os {grafoVista.desenhados} nós com mais contratos; use a
                                                            procura ou os filtros para chegar aos restantes.
                                                        </span>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    ) : (
                                        <p className="text-[11.5px] text-muted-foreground">
                                            {analisandoOntologia
                                                ? "A desenhar o grafo…"
                                                : "Sem objectos suficientes nas fontes para desenhar um grafo."}
                                        </p>
                                    )}
                                </TabsContent>

                                <TabsContent value="analogias" active={aba === "analogias"} className="min-w-0 pt-3">
                                    {analisandoAnalogias && (
                                        <p className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
                                            <Loader2 size={13} className="animate-spin" /> A procurar contratos semelhantes…
                                        </p>
                                    )}
                                    {analogias && analogias.items.length === 0 && !analisandoAnalogias && (
                                        <p className="text-[11.5px] text-muted-foreground">
                                            Não há contratos com identificador nesta resposta para comparar.
                                        </p>
                                    )}
                                    {analogias && analogias.items.length > 0 && (
                                        <div className="flex flex-col gap-4">
                                            {analogias.items.map((item) => (
                                                <div key={item.contrato.id} className="flex min-w-0 flex-col gap-1.5">
                                                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                                                        <button
                                                            type="button"
                                                            onClick={() =>
                                                                onNavigate?.(`contract-detail:${item.contrato.id}`)
                                                            }
                                                            className="min-w-0 break-words text-left text-[11.5px] font-medium text-foreground underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                        >
                                                            {item.contrato.title}
                                                        </button>
                                                        <span className="text-[11.5px] font-semibold text-teal-200">
                                                            {item.contrato.preco}
                                                        </span>
                                                        {item.contrato.cpv && (
                                                            <span className="text-[10.5px] text-muted-foreground">
                                                                CPV {item.contrato.cpv}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="text-[10.5px] text-muted-foreground">{item.posicao?.frase}</p>
                                                    {item.semelhantes.map((semelhante, indice) => (
                                                        <div
                                                            key={`${semelhante.id}-${indice}`}
                                                            className="flex min-w-0 flex-wrap items-baseline gap-x-2 border-l border-white/10 pl-3 text-[11.5px]"
                                                        >
                                                            <button
                                                                type="button"
                                                                onClick={() =>
                                                                    onNavigate?.(`contract-detail:${semelhante.id}`)
                                                                }
                                                                className="min-w-0 break-words text-left text-foreground/85 underline decoration-dotted underline-offset-2 hover:text-teal-100"
                                                            >
                                                                {semelhante.title}
                                                            </button>
                                                            <span className="text-muted-foreground">
                                                                {semelhante.preco}
                                                                {typeof semelhante.desvio_pct === "number" && (
                                                                    <span
                                                                        className={
                                                                            semelhante.desvio_pct > 0 ? "text-amber-200" : "text-teal-200"
                                                                        }
                                                                    >
                                                                        {" "}
                                                                        {semelhante.desvio_pct > 0 ? "+" : ""}
                                                                        {semelhante.desvio_pct.toLocaleString("pt-PT", {
                                                                            maximumFractionDigits: 1,
                                                                        })}
                                                                        %
                                                                    </span>
                                                                )}
                                                            </span>
                                                            <span className="text-[10px] text-muted-foreground">
                                                                {semelhante.porque}
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            ))}
                                            {analogias.notes.length > 0 && (
                                                <ul className="flex flex-col gap-0.5 text-[10.5px] text-muted-foreground">
                                                    {analogias.notes.map((nota) => (
                                                        <li key={nota}>· {nota}</li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    )}
                                </TabsContent>

                                <TabsContent value="analise" active={aba === "analise"} className="min-w-0 pt-3">
                                    <div className="flex flex-col gap-2">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <button
                                                type="button"
                                                disabled={Boolean(analisando)}
                                                onClick={() => void pedirAnalise("modelo")}
                                                className="flex items-center gap-1.5 rounded-full border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-[11.5px] text-teal-100 transition hover:border-teal-400/60 disabled:opacity-50"
                                            >
                                                {analisando === "modelo" ? (
                                                    <Loader2 size={13} className="animate-spin" />
                                                ) : (
                                                    <Sparkles size={13} />
                                                )}
                                                Analisar com a IA
                                            </button>
                                            <button
                                                type="button"
                                                disabled={Boolean(analisando)}
                                                onClick={() => void pedirAnalise("hermes")}
                                                className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-foreground/80 transition hover:border-teal-400/40 disabled:opacity-50"
                                            >
                                                {analisando === "hermes" ? (
                                                    <Loader2 size={13} className="animate-spin" />
                                                ) : (
                                                    <Network size={13} />
                                                )}
                                                Analisar com o Hermes
                                            </button>
                                            {analise && !analisando && (
                                                <button
                                                    type="button"
                                                    onClick={() => void pedirAnalise(analise.motor === "hermes" ? "hermes" : "modelo", true)}
                                                    className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-foreground/70 transition hover:border-teal-400/40"
                                                >
                                                    <RefreshCw size={12} /> Repetir
                                                </button>
                                            )}
                                            <span className="text-[10.5px] text-muted-foreground">
                                                a IA interpreta o grafo e as analogias; o Hermes faz a sua própria recolha
                                            </span>
                                        </div>

                                        {analise && (
                                            <div className="flex flex-col gap-2">
                                                <p className="text-[10.5px] text-muted-foreground">
                                                    {analise.motor === "hermes" ? "Hermes" : "IA"}
                                                    {analise.modelo ? ` · ${analise.modelo}` : ""}
                                                    {analise.modo ? ` · ${analise.modo}` : ""}
                                                    {analise.elapsed_ms ? ` · ${(analise.elapsed_ms / 1000).toFixed(1)} s` : ""}
                                                </p>
                                                <div className="prose prose-invert max-w-none text-[12.5px] leading-relaxed text-foreground/90">
                                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                        {analise.texto || analise.error || ""}
                                                    </ReactMarkdown>
                                                </div>
                                                {analise.passos && analise.passos.length > 0 && (
                                                    <div className="flex flex-col gap-0.5">
                                                        <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                                                            Passos do Hermes
                                                        </p>
                                                        {analise.passos.map((passo, indice) => (
                                                            <p key={`${passo.focus}-${indice}`} className="text-[11px] text-muted-foreground">
                                                                · {passo.question || passo.focus}
                                                                {typeof passo.items === "number" ? ` — ${passo.items} resultados` : ""}
                                                            </p>
                                                        ))}
                                                    </div>
                                                )}
                                                {analise.evidencias && analise.evidencias.length > 0 && (
                                                    <div className="flex flex-col gap-0.5">
                                                        <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                                                            Evidências recolhidas
                                                        </p>
                                                        {analise.evidencias.slice(0, 8).map((evidencia) => (
                                                            <p key={`${evidencia.n}-${evidencia.title}`} className="text-[11px] text-muted-foreground">
                                                                <span className="text-teal-200">[{evidencia.n}]</span>{" "}
                                                                {evidencia.url ? (
                                                                    <a
                                                                        href={evidencia.url}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                        className="underline decoration-dotted hover:text-foreground"
                                                                    >
                                                                        {evidencia.title}
                                                                    </a>
                                                                ) : (
                                                                    evidencia.title
                                                                )}
                                                                {evidencia.source ? ` · ${evidencia.source}` : ""}
                                                            </p>
                                                        ))}
                                                    </div>
                                                )}
                                                {analise.notes && analise.notes.length > 0 && (
                                                    <ul className="flex flex-col gap-0.5 text-[10.5px] text-muted-foreground">
                                                        {analise.notes.map((nota) => (
                                                            <li key={nota}>· {nota}</li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </TabsContent>
                            </Tabs>
                        </section>
                    )}
                </div>
            </div>
        </div>
    );
}
