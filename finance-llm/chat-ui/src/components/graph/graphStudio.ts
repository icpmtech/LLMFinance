/**
 * Modelo do estúdio de grafos: catálogo de dimensões, receitas prontas,
 * métricas e transformações para as várias visualizações (rede, Sankey, treemap).
 */
import type {
  ContractGraphBuildEdge,
  ContractGraphBuildNode,
  ContractGraphBuildResponse,
} from "../../types";

export type GraphMetric = "valor" | "contratos";

export type StudioView = "network" | "hierarchical" | "circular" | "sankey" | "treemap" | "list";

export type StudioNode = ContractGraphBuildNode & {
  value: number;
  radius: number;
  color: string;
  /** Chave/label usados na legenda (lado A/B quando as dimensões diferem, tipo caso contrário). */
  legendKey: string;
  legendLabel: string;
};

export type StudioEdge = ContractGraphBuildEdge & {
  weight: number;
};

export type StudioGraph = {
  nodes: StudioNode[];
  edges: StudioEdge[];
  meta: ContractGraphBuildResponse["meta"];
};

/** Cores por tipo de dimensão (mantém a leitura consistente entre grafos). */
export const TYPE_COLORS: Record<string, string> = {
  entidade: "#2dd4bf",
  concorrente: "#fb7185",
  regiao: "#fbbf24",
  cpv: "#a78bfa",
  processo: "#60a5fa",
  tempo: "#f59e0b",
  outra: "#94a3b8",
};

export const TYPE_LABELS: Record<string, string> = {
  entidade: "Entidades",
  concorrente: "Concorrentes",
  regiao: "Território",
  cpv: "Classificação CPV",
  processo: "Procedimento",
  tempo: "Tempo",
  outra: "Outros",
};

export type Recipe = {
  id: string;
  label: string;
  description: string;
  dimensionA: string;
  dimensionB: string | null;
  metric: GraphMetric;
  view: StudioView;
  limit: number;
};

/** Receitas prontas: cada uma responde a uma pergunta distinta sobre os contratos. */
export const RECIPES: Recipe[] = [
  {
    id: "entity-network",
    label: "Rede de entidades",
    description: "Quem contrata quem: adjudicantes ligados aos adjudicatários por contratos.",
    dimensionA: "adjudicante",
    dimensionB: "adjudicatario",
    metric: "valor",
    view: "network",
    limit: 60,
  },
  {
    id: "cpv-hierarchy",
    label: "Hierarquia CPV",
    description: "Como o valor se distribui da divisão CPV até à classe contratada.",
    dimensionA: "cpv_divisao",
    dimensionB: "cpv_classe",
    metric: "valor",
    view: "hierarchical",
    limit: 60,
  },
  {
    id: "competition",
    label: "Rede de concorrência",
    description: "Concorrentes que se encontram nos mesmos contratos (quem compete com quem).",
    dimensionA: "concorrente",
    dimensionB: "concorrente",
    metric: "contratos",
    view: "network",
    limit: 50,
  },
  {
    id: "value-flow",
    label: "Fluxo de valor",
    description: "Fluxo do tipo de procedimento para o território, espessura pelo valor.",
    dimensionA: "procedimento",
    dimensionB: "regiao",
    metric: "valor",
    view: "sankey",
    limit: 40,
  },
  {
    id: "territory",
    label: "Território",
    description: "Valor contratado por região (treemap: a área é o valor).",
    dimensionA: "regiao",
    dimensionB: null,
    metric: "valor",
    view: "treemap",
    limit: 30,
  },
  {
    id: "cpv-value",
    label: "Valor por CPV",
    description: "Treemap das classes CPV com maior valor contratado.",
    dimensionA: "cpv_classe",
    dimensionB: null,
    metric: "valor",
    view: "treemap",
    limit: 40,
  },
  {
    id: "timeline",
    label: "Evolução anual",
    description: "Como cada entidade adjudicatária cresce ao longo dos anos.",
    dimensionA: "ano",
    dimensionB: "adjudicatario",
    metric: "valor",
    view: "hierarchical",
    limit: 50,
  },
  {
    id: "sme",
    label: "PME por região",
    description: "Peso relativo dos adjudicatários PME em cada região.",
    dimensionA: "regiao",
    dimensionB: "pme",
    metric: "contratos",
    view: "network",
    limit: 40,
  },
  {
    id: "custom",
    label: "Personalizado",
    description: "Escolha as dimensões, a métrica e a visualização.",
    dimensionA: "adjudicante",
    dimensionB: "cpv_divisao",
    metric: "valor",
    view: "network",
    limit: 60,
  },
];

export const METRIC_LABELS: Record<GraphMetric, string> = {
  valor: "Valor contratado",
  contratos: "Nº de contratos",
};

export function formatMoney(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatCompact(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function metricLabel(metric: GraphMetric, value: number): string {
  return metric === "valor" ? formatMoney(value) : `${formatCompact(value)} contratos`;
}

export function nodeValue(node: ContractGraphBuildNode, metric: GraphMetric): number {
  return metric === "valor" ? node.total_value ?? 0 : node.count ?? 0;
}

export function edgeWeight(edge: ContractGraphBuildEdge, metric: GraphMetric): number {
  return metric === "valor" ? edge.value ?? 0 : edge.count ?? 0;
}

/** Cores por lado quando o grafo liga duas dimensões distintas (ex.: adjudicante → adjudicatário). */
export const SIDE_COLORS = { a: "#2dd4bf", b: "#60a5fa" };

/** Converte a resposta da API num grafo pronto a desenhar (raio e cor derivados da métrica). */
export function toStudioGraph(
  response: ContractGraphBuildResponse | null,
  metric: GraphMetric,
): StudioGraph | null {
  if (!response || response.error) return null;
  const meta = response.meta;
  const twoSided = Boolean(meta.dimension_b) && meta.dimension_b !== meta.dimension_a;
  const values = response.nodes.map((node) => nodeValue(node, metric));
  const max = Math.max(...values, 1);
  const nodes: StudioNode[] = response.nodes.map((node) => {
    const value = nodeValue(node, metric);
    const side = node.dimension === meta.dimension_a ? "a" : "b";
    return {
      ...node,
      value,
      radius: 10 + Math.min(16, Math.sqrt(value / max) * 16),
      color: twoSided
        ? SIDE_COLORS[side]
        : TYPE_COLORS[node.type] ?? TYPE_COLORS.outra,
      legendKey: twoSided ? side : node.type,
      legendLabel: twoSided ? node.role ?? node.dimension : typeLabel(node.type),
    };
  });
  const weights = response.edges.map((edge) => edgeWeight(edge, metric));
  const maxWeight = Math.max(...weights, 1);
  const edges: StudioEdge[] = response.edges.map((edge) => ({
    ...edge,
    weight: edgeWeight(edge, metric) / maxWeight,
  }));
  return { nodes, edges, meta: response.meta };
}

export function graphSummary(graph: StudioGraph | null, metric: GraphMetric) {
  if (!graph) return { nodes: 0, edges: 0, total: 0, topNodes: [] as StudioNode[], topEdges: [] as StudioEdge[] };
  // Em grafos de duas dimensões somar ambos os lados duplicaria o valor: usa-se o lado A.
  const twoSided = Boolean(graph.meta.dimension_b) && graph.meta.dimension_b !== graph.meta.dimension_a;
  const primary = twoSided
    ? graph.nodes.filter((node) => node.dimension === graph.meta.dimension_a)
    : graph.nodes;
  const total = primary.reduce((acc, node) => acc + nodeValue(node, metric), 0);
  return {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    total,
    topNodes: [...graph.nodes].sort((a, b) => nodeValue(b, metric) - nodeValue(a, metric)),
    topEdges: [...graph.edges].sort((a, b) => edgeWeight(b, metric) - edgeWeight(a, metric)),
  };
}

export function groupTypes(nodes: StudioNode[]): string[] {
  return [...new Set(nodes.map((node) => node.type))];
}

/** Entradas de legenda efetivamente presentes no grafo (máx. 5). */
export function legendEntries(nodes: StudioNode[]): { key: string; label: string; color: string }[] {
  const map = new Map<string, { key: string; label: string; color: string }>();
  nodes.forEach((node) => {
    if (!map.has(node.legendKey)) {
      map.set(node.legendKey, { key: node.legendKey, label: node.legendLabel, color: node.color });
    }
  });
  return [...map.values()];
}

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

/**
 * Traduz um nó ngen filtro de pesquisa de contratos (para o painel de detalhe).
 */
export function nodeContractQuery(
  node: ContractGraphBuildNode,
): { nif?: string; region?: string; cpv_code?: string; year?: number; q?: string } | null {
  switch (node.dimension) {
    case "adjudicante":
    case "adjudicatario":
    case "entidade":
    case "concorrente":
      return /^\d{9}$/.test(node.key) ? { nif: node.key } : { q: node.label };
    case "regiao":
      return { region: node.key };
    case "local_execucao":
      return { q: node.key };
    case "cpv_divisao":
    case "cpv_classe":
      return { cpv_code: node.key };
    case "ano": {
      const year = Number(node.key);
      return Number.isFinite(year) ? { year } : null;
    }
    case "procedimento":
    case "tipo_contrato":
    case "pme":
      return { q: node.key };
    default:
      return null;
  }
}

export function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function graphToCsv(graph: StudioGraph, metric: GraphMetric): string {
  const labelOf = (id: string) => graph.nodes.find((node) => node.id === id)?.label ?? id;
  const lines = ["tipo,origem,destino,contratos,valor"];
  graph.edges.forEach((edge) => {
    lines.push(
      [
        "aresta",
        JSON.stringify(labelOf(edge.source)),
        JSON.stringify(labelOf(edge.target)),
        edge.count,
        Math.round(edge.value),
      ].join(","),
    );
  });
  graph.nodes.forEach((node) => {
    lines.push(["no", JSON.stringify(node.label), "", node.count, Math.round(node.total_value)].join(","));
  });
  void metric;
  return lines.join("\n");
}
