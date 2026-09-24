/**
 * Modelo do grafo do CIRE (insolvências e revitalizações).
 *
 * Converte a resposta de `/cire/graph` no formato que o canvas do estúdio de
 * grafos já sabe desenhar (`StudioGraph`) — os nós e arestas do CIRE medem
 * **publicações** e **menções**, não euros — e traduz cada nó num conjunto de
 * filtros da pesquisa, para a navegação (drill-down) fazer sentido.
 */
import type {
  CireGraphEdge,
  CireGraphNode,
  CireGraphResponse,
  CireSearchParams,
} from "../../cireApi";
import type { StudioEdge, StudioGraph, StudioNode } from "../graph/graphStudio";
import { formatCompact } from "../graph/graphStudio";

/** Métrica do grafo do CIRE. */
export type CireGraphMetric = "publicacoes" | "mencoes";

/** Nó do CIRE já pronto a desenhar, com os dois contadores preservados. */
export type CireStudioNode = StudioNode & {
  publicacoes: number;
  mencoes: number;
  nif?: string | null;
};

/** Aresta do CIRE já pronta a desenhar. */
export type CireStudioEdge = StudioEdge & { mentions?: number };

/** Nós de um grafo do CIRE (os objetos devolvidos pela API trazem os contadores). */
export function cireGraphNodes(graph: StudioGraph | null): CireStudioNode[] {
  return (graph?.nodes ?? []) as CireStudioNode[];
}

/** Arestas de um grafo do CIRE. */
export function cireGraphEdges(graph: StudioGraph | null): CireStudioEdge[] {
  return (graph?.edges ?? []) as CireStudioEdge[];
}

export const CIRE_METRIC_LABELS: Record<CireGraphMetric, string> = {
  publicacoes: "Nº de publicações",
  mencoes: "Menções a intervenientes",
};

/** Cores por tipo de dimensão (mantém a leitura consistente entre grafos). */
export const CIRE_TYPE_COLORS: Record<string, string> = {
  entidade: "#2dd4bf",
  jurisdicao: "#fbbf24",
  processo: "#60a5fa",
  tempo: "#f59e0b",
  outra: "#94a3b8",
};

export const CIRE_TYPE_LABELS: Record<string, string> = {
  entidade: "Entidades",
  jurisdicao: "Tribunais e comarcas",
  processo: "Tipo e ato do processo",
  tempo: "Tempo",
  outra: "Outros",
};

export const CIRE_SIDE_COLORS = { a: "#2dd4bf", b: "#60a5fa" };

export function cireTypeLabel(type: string): string {
  return CIRE_TYPE_LABELS[type] ?? type;
}

function metricValue(node: CireGraphNode, metric: CireGraphMetric): number {
  return metric === "mencoes" ? node.mentions ?? 0 : node.count ?? 0;
}

function edgeValue(edge: CireGraphEdge, metric: CireGraphMetric): number {
  return metric === "mencoes" ? edge.mentions ?? 0 : edge.count ?? 0;
}

/** Converte a resposta da API num grafo pronto a desenhar. */
export function toCireStudioGraph(
  response: CireGraphResponse | null,
  metric: CireGraphMetric,
): StudioGraph | null {
  if (!response || response.error) return null;
  const meta = response.meta;
  const twoSided = Boolean(meta.dimension_b) && meta.dimension_b !== meta.dimension_a;
  const values = response.nodes.map((node) => metricValue(node, metric));
  const max = Math.max(...values, 1);

  const nodes: CireStudioNode[] = response.nodes.map((node) => {
    const value = metricValue(node, metric);
    const side = node.dimension === meta.dimension_a ? "a" : "b";
    return {
      ...node,
      // `count` alimenta as legendas dos componentes partilhados (treemap/sankey):
      // passa a ser o valor da métrica escolhida.
      count: value,
      publicacoes: node.count ?? 0,
      mencoes: node.mentions ?? value,
      value,
      radius: 10 + Math.min(16, Math.sqrt(value / max) * 16),
      color: twoSided ? CIRE_SIDE_COLORS[side] : CIRE_TYPE_COLORS[node.type] ?? CIRE_TYPE_COLORS.outra,
      legendKey: twoSided ? side : node.type,
      legendLabel: twoSided ? node.role ?? node.dimension : cireTypeLabel(node.type),
      total_value: 0,
    };
  });

  const weights = response.edges.map((edge) => edgeValue(edge, metric));
  const maxWeight = Math.max(...weights, 1);
  const edges: CireStudioEdge[] = response.edges.map((edge) => ({
    ...edge,
    count: edgeValue(edge, metric),
    value: 0,
    weight: edgeValue(edge, metric) / maxWeight,
  }));

  return { nodes, edges, meta: response.meta as StudioGraph["meta"] };
}

/** Unidade mostrada nas dicas (o CIRE não mede euros). */
export function cireUnitLabel(metric: CireGraphMetric): string {
  return metric === "mencoes" ? "menções" : "publicações";
}

export function cireNodeSummary(node: StudioNode): string {
  const rich = node as CireStudioNode;
  const publicacoes = rich.publicacoes ?? node.count;
  const mencoes = rich.mencoes ?? node.count;
  if (publicacoes === mencoes) return `${formatCompact(publicacoes)} publicações`;
  return `${formatCompact(publicacoes)} publicações · ${formatCompact(mencoes)} menções`;
}

export function cireEdgeSummary(edge: StudioEdge): string {
  const mencoes = (edge as CireStudioEdge).mentions ?? edge.count;
  if (mencoes === edge.count) return `${formatCompact(edge.count)} publicações em comum`;
  return `${formatCompact(edge.count)} publicações em comum · ${formatCompact(mencoes)} menções`;
}

function edgeMetric(edge: StudioEdge, metric: CireGraphMetric): number {
  return metric === "mencoes" ? (edge as CireStudioEdge).mentions ?? edge.count : edge.count;
}

export function cireGraphSummary(graph: StudioGraph | null) {
  if (!graph) return { nodes: 0, edges: 0, total: 0, topNodes: [] as CireStudioNode[] };
  const twoSided = Boolean(graph.meta.dimension_b) && graph.meta.dimension_b !== graph.meta.dimension_a;
  const primary = twoSided ? graph.nodes.filter((node) => node.dimension === graph.meta.dimension_a) : graph.nodes;
  return {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    total: primary.reduce((acc, node) => acc + node.value, 0),
    topNodes: [...cireGraphNodes(graph)].sort((a, b) => b.value - a.value),
  };
}

export function cireLegendEntries(nodes: StudioNode[]): { key: string; label: string; color: string }[] {
  const map = new Map<string, { key: string; label: string; color: string }>();
  nodes.forEach((node) => {
    if (!map.has(node.legendKey)) {
      map.set(node.legendKey, { key: node.legendKey, label: node.legendLabel, color: node.color });
    }
  });
  return [...map.values()];
}

/**
 * Traduz um nó em filtros da pesquisa do CIRE, para o drill-down.
 *
 * As entidades sem NIF são procuradas por texto livre (o índice guarda o nome do
 * interveniente no campo pesquisável `intervenientes.nome`).
 */
export function cireNodeSearchParams(node: CireNodeRef): CireSearchParams {
  const nif = node.nif && /^\d{9}$/.test(String(node.nif)) ? String(node.nif) : null;
  switch (node.dimension) {
    case "insolvente":
    case "administrador":
    case "credor":
    case "requerente":
    case "interveniente":
      return nif ? { nif } : { q: node.label };
    case "tribunal":
      return { tribunal: node.key };
    case "comarca":
      return { tribunal_comarca: node.key };
    case "especie":
      return { especie: node.key };
    case "tipo":
      return { tipo: node.key };
    case "ato":
      return { ato: node.key };
    case "juizo":
    case "sede":
    case "papel":
    default:
      return { q: node.label };
  }
}

/** Vizinhos de um nó (arestas onde participa), para o painel de detalhe. */
export function cireNeighbours(
  graph: StudioGraph | null,
  nodeId: string,
  metric: CireGraphMetric,
  limit = 12,
): { node: CireStudioNode | undefined; edge: CireStudioEdge }[] {
  if (!graph) return [];
  const byId = new Map(cireGraphNodes(graph).map((node) => [node.id, node]));
  return cireGraphEdges(graph)
    .filter((edge) => edge.source === nodeId || edge.target === nodeId)
    .map((edge) => ({
      node: byId.get(edge.source === nodeId ? edge.target : edge.source),
      edge,
    }))
    .filter((item) => item.node)
    .sort((a, b) => edgeMetric(b.edge, metric) - edgeMetric(a.edge, metric))
    .slice(0, limit);
}

export function cireGraphToCsv(graph: StudioGraph): string {
  const labelOf = (id: string) => graph.nodes.find((node) => node.id === id)?.label ?? id;
  const lines = ["tipo,origem,destino,publicacoes"];
  graph.edges.forEach((edge) => {
    lines.push(["aresta", JSON.stringify(labelOf(edge.source)), JSON.stringify(labelOf(edge.target)), edge.count].join(","));
  });
  graph.nodes.forEach((node) => {
    const rich = node as CireStudioNode;
    lines.push(["no", JSON.stringify(node.label), "", rich.publicacoes ?? node.count].join(","));
  });
  return lines.join("\n");
}

export function downloadCireFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Métrica a passar aos componentes partilhados (treemap/sankey/canvas).
 *
 * Só conhecem «valor» e «contratos»; o CIRE usa «contratos» (contagens) e os
 * resumos são substituídos por `cireNodeSummary`/`cireEdgeSummary`.
 */
export const CIRE_COMPONENT_METRIC = "contratos" as const;

/** Dados mínimos de um nó necessários para o drill-down para a pesquisa. */
export type CireNodeRef = Pick<CireGraphNode, "dimension" | "key" | "label"> & { nif?: string | null };

/** Exporta os tipos do grafo usados pela UI. */
export type { CireGraphEdge };