/**
 * Cliente da análise da Pesquisa profunda (`/deep-search/ontology|analogies|analysis`).
 *
 * A ontologia e as analogias são pedidas a partir das **fontes já recuperadas**
 * (as mesmas que a resposta mostrou no evento `sources`): a recuperação é a parte
 * lenta da pesquisa profunda e não se repete. Só se enviam os campos que o
 * backend usa — sem imagens nem excertos, que só engordariam o pedido.
 */
import { API_BASE } from "./api";
import type { ContractGraphBuildEdge, ContractGraphBuildMeta, ContractGraphBuildNode } from "./types";
import type { DeepSource } from "./deepSearchApi";

/** Nó do grafo: o mesmo do grafo de contratos, com o que a ontologia acrescenta. */
export type DeepGraphNode = ContractGraphBuildNode & {
    subtitulo?: string;
    cae?: string | null;
    global_contracts?: number;
    global_value?: number;
    country?: string | null;
    scope?: string;
};

export type DeepGraphEdge = ContractGraphBuildEdge & { id: string; label: string; kind: string };

export type DeepOntology = {
    nodes: DeepGraphNode[];
    edges: DeepGraphEdge[];
    meta: ContractGraphBuildMeta;
    legend: { type: string; label: string; count: number }[];
    totals: {
        nodes: number;
        edges: number;
        by_type: Record<string, number>;
        scopes: number;
        contracts: number;
    };
    mermaid: string;
    elapsed_ms: number;
    error?: string | null;
};

export type DeepAnalogousContract = {
    id: string;
    title: string;
    preco: string;
    preco_valor: number;
    cpv: string | null;
    ano?: number | null;
    adjudicante: string;
    adjudicatario: string;
    score?: number | null;
    porque?: string;
    desvio_pct?: number;
};

export type DeepAnalogyItem = {
    contrato: DeepAnalogousContract;
    semelhantes: DeepAnalogousContract[];
    posicao: {
        estado?: string;
        mediana?: string;
        p25?: string;
        p75?: string;
        vezes_a_mediana?: number;
        frase: string;
    };
};

export type DeepAnalogies = {
    items: DeepAnalogyItem[];
    totals: { contracts: number; analogues: number; semantic: number; by_value: number };
    notes: string[];
    elapsed_ms: number;
    error?: string | null;
};

export type DeepAnalysisEvidence = {
    n: number;
    title: string;
    subtitle?: string;
    source?: string;
    source_label?: string;
    url?: string;
    date?: string;
    snippet?: string;
};

export type DeepAnalysis = {
    motor: string;
    modelo?: string | null;
    modo?: string;
    texto: string;
    evidencias?: DeepAnalysisEvidence[];
    passos?: { focus?: string; question?: string; items?: number; sources_with_results?: number; ms?: number }[];
    facts?: string[];
    notes?: string[];
    followups?: string[];
    stats?: Record<string, unknown>;
    elapsed_ms: number;
    error?: string | null;
};

/** Motor da análise: o modelo escolhido na página ou o agente Hermes. */
export type DeepAnalysisEngine = "modelo" | "hermes";

/**
 * Campos das fontes que o backend realmente lê.
 *
 * `image` (pode ser uma imagem em base64) e `url`/`badges`/`score` ficam de fora:
 * não entram na ontologia nem no resumo que vai para o modelo.
 */
function paraEnvio(sources: DeepSource[]) {
    return sources.map((source) => ({
        n: source.n,
        id: source.id,
        scope: source.scope,
        title: source.title,
        subtitle: source.subtitle,
        date: source.date ?? null,
        open: source.open ?? null,
        meta: source.meta ?? {},
        links: source.links ?? [],
    }));
}

async function readError(res: Response, fallback: string): Promise<string> {
    try {
        const data = await res.json();
        return String(data?.detail || data?.error || fallback);
    } catch {
        return fallback;
    }
}

async function pedir<T>(caminho: string, corpo: unknown, fallback: string): Promise<T> {
    const res = await fetch(`${API_BASE}/deep-search/${caminho}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
    });
    if (!res.ok) throw new Error(await readError(res, fallback));
    return res.json();
}

/** Ontologia das fontes: objectos (contratos, empresas, CPV, anos) e relações. */
export async function fetchDeepOntology(sources: DeepSource[], enrich = true): Promise<DeepOntology> {
    return pedir<DeepOntology>(
        "ontology",
        { sources: paraEnvio(sources), enrich },
        "Erro ao construir a ontologia das fontes.",
    );
}

/** Contratos semelhantes no mercado para os contratos da resposta. */
export async function fetchDeepAnalogies(
    sources: DeepSource[],
    contracts = 3,
    similar = 3,
): Promise<DeepAnalogies> {
    return pedir<DeepAnalogies>(
        "analogies",
        { sources: paraEnvio(sources), contracts, similar },
        "Erro ao procurar contratos semelhantes.",
    );
}

/**
 * Interpretação da ontologia e das analogias.
 *
 * `engine` escolhe quem escreve: o modelo da plataforma (`modelo`, com o
 * `backend` resolvido como na resposta) ou o agente Hermes, que junta a sua
 * própria recolha federada e devolve evidências.
 */
export async function fetchDeepAnalysis(payload: {
    question: string;
    sources: DeepSource[];
    ontology?: DeepOntology | null;
    analogies?: DeepAnalogies | null;
    engine?: DeepAnalysisEngine;
    backend?: string;
    depth?: string;
}): Promise<DeepAnalysis> {
    return pedir<DeepAnalysis>(
        "analysis",
        {
            question: payload.question,
            sources: paraEnvio(payload.sources),
            ontology: payload.ontology ?? null,
            analogies: payload.analogies ?? null,
            engine: payload.engine ?? "modelo",
            backend: payload.backend ?? "",
            depth: payload.depth ?? "profunda",
        },
        payload.engine === "hermes"
            ? "O agente Hermes não conseguiu analisar."
            : "O modelo não conseguiu analisar.",
    );
}
