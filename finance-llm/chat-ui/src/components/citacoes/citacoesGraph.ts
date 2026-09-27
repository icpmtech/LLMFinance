/**
 * Modelo do grafo das citações e notificações editais (CITIUS).
 *
 * Converte a resposta de `/citacoes/graph` no formato que o canvas do estúdio de
 * grafos já sabe desenhar (`StudioGraph`) — os nós medem **éditos** e **menções**,
 * e cada nó traz também o **valor das execuções** analisado do PDF — e traduz
 * cada nó num conjunto de filtros da pesquisa, para o drill-down fazer sentido.
 */
import type {
  CitacoesGraphEdge,
  CitacoesGraphNode,
  CitacoesGraphResponse,
  CitacoesSearchParams,
} from "../../citacoesApi";
import type { StudioEdge, StudioGraph, StudioNode } from "../graph/graphStudio";
import { formatCompact, formatMoney } from "../graph/graphStudio";

/** Métrica do grafo das citações. */
export type CitacoesGraphMetric = "editais" | "mencoes";

export const CITACOES_METRIC_LABELS: Record<CitacoesGraphMetric, string> = {
  editais: "Nº de éditos",
  mencoes: "Menções a intervenientes",
};

/** Cores por tipo de dimensão (mantém a leitura consistente entre grafos). */
export const CITACOES_TYPE_COLORS: Record<string, string> = {
  entidade: "#2dd4bf",
  jurisdicao: "#fbbf24",
  processo: "#60a5fa",
  documento: "#a78bfa",
  tempo: "#f59e0b",
  outra: "#94a3b8",
};

export const CITACOES_TYPE_LABELS: Record<string, string> = {
  entidade: "Partes e intervenientes",
  jurisdicao: "Tribunais e comarcas",
  processo: "Tipo, ato e espécie",
  documento: "Documento (PDF analisado)",
  tempo: "Tempo",
  outra: "Outros",
};

export const CITACOES_SIDE_COLORS = { a: "#eab308", b: "#2dd4bf" };

export function citacoesTypeLabel(type: string): string {
  return CITACOES_TYPE_LABELS[type] ?? type;
}

/** Nó já pronto a desenhar, com os contadores e o valor preservados. */
export type CitacoesStudioNode = StudioNode & {
  editais: number;
  mencoes: number;
  valor: number;
  nif?: string | null;
  /** Papéis/facetas agregados no nó (ex.: «Executado», «Exequente»). */
  keys?: string[] | null;
};

export type CitacoesStudioEdge = StudioEdge & { mentions?: number; valor?: number };

function metricValue(node: CitacoesGraphNode, metric: CitacoesGraphMetric): number {
  return metric === "mencoes" ? node.mentions ?? 0 : node.count ?? 0;
}

function metricEdge(edge: CitacoesGraphEdge, metric: CitacoesGraphMetric): number {
  return metric === "mencoes" ? edge.mentions ?? 0 : edge.count ?? 0;
}

/** Converte a resposta da API num grafo pronto a desenhar. */
export function toCitacoesStudioGraph(
  response: CitacoesGraphResponse | null,
  metric: CitacoesGraphMetric,
): StudioGraph | null {
  if (!response || response.error) return null;
  const meta = response.meta;
  const twoSided = Boolean(meta.dimension_b) && meta.dimension_b !== meta.dimension_a;
  const values = response.nodes.map((node) => metricValue(node, metric));
  const max = Math.max(...values, 1);

  const nodes: CitacoesStudioNode[] = response.nodes.map((node) => {
    const value = metricValue(node, metric);
    const side = node.dimension === meta.dimension_a ? "a" : "b";
    return {
      ...node,
      // `count` alimenta as legendas dos componentes partilhados (treemap/sankey):
      // passa a ser o valor da métrica escolhida.
      count: value,
      editais: node.count ?? 0,
      mencoes: node.mentions ?? value,
      valor: node.valor ?? 0,
      value,
      radius: 10 + Math.min(16, Math.sqrt(value / max) * 16),
      color: twoSided
        ? CITACOES_SIDE_COLORS[side]
        : CITACOES_TYPE_COLORS[node.type] ?? CITACOES_TYPE_COLORS.outra,
      legendKey: twoSided ? side : node.type,
      legendLabel: twoSided ? node.role ?? node.dimension : citacoesTypeLabel(node.type),
      // O treemap/lista dos componentes partilhados mostram `total_value`: usa-se
      // o valor das execuções, que é o que interessa em euros.
      total_value: node.valor ?? 0,
    };
  });

  const weights = response.edges.map((edge) => metricEdge(edge, metric));
  const maxWeight = Math.max(...weights, 1);
  const edges: CitacoesStudioEdge[] = response.edges.map((edge) => ({
    ...edge,
    count: metricEdge(edge, metric),
    value: edge.valor ?? 0,
    weight: metricEdge(edge, metric) / maxWeight,
  }));

  return { nodes, edges, meta: response.meta as unknown as StudioGraph["meta"] };
}

export function citacoesGraphNodes(graph: StudioGraph | null): CitacoesStudioNode[] {
  return (graph?.nodes ?? []) as CitacoesStudioNode[];
}

export function citacoesGraphEdges(graph: StudioGraph | null): CitacoesStudioEdge[] {
  return (graph?.edges ?? []) as CitacoesStudioEdge[];
}

/** Unidade mostrada nas dicas. */
export function citacoesUnitLabel(metric: CitacoesGraphMetric): string {
  return metric === "mencoes" ? "menções" : "éditos";
}

export function citacoesNodeSummary(node: StudioNode): string {
  const rich = node as CitacoesStudioNode;
  const editais = rich.editais ?? node.count;
  const mencoes = rich.mencoes ?? node.count;
  const partes = [editais === mencoes ? `${formatCompact(editais)} éditos` : `${formatCompact(editais)} éditos · ${formatCompact(mencoes)} menções`];
  if (rich.valor) partes.push(formatMoney(rich.valor));
  return partes.join(" · ");
}

export function citacoesEdgeSummary(edge: StudioEdge): string {
  const rich = edge as CitacoesStudioEdge;
  const mencoes = rich.mentions ?? edge.count;
  const partes =
    mencoes === edge.count
      ? [`${formatCompact(edge.count)} éditos em comum`]
      : [`${formatCompact(edge.count)} éditos em comum · ${formatCompact(mencoes)} menções`];
  if (rich.valor) partes.push(formatMoney(rich.valor));
  return partes.join(" · ");
}

export function citacoesLegendEntries(nodes: StudioNode[]): { key: string; label: string; color: string }[] {
  const map = new Map<string, { key: string; label: string; color: string }>();
  nodes.forEach((node) => {
    if (!map.has(node.legendKey)) {
      map.set(node.legendKey, { key: node.legendKey, label: node.legendLabel, color: node.color });
    }
  });
  return [...map.values()];
}

export function citacoesGraphSummary(graph: StudioGraph | null) {
  if (!graph) return { nodes: 0, edges: 0, total: 0, valor: 0, topNodes: [] as CitacoesStudioNode[] };
  const twoSided = Boolean(graph.meta.dimension_b) && graph.meta.dimension_b !== graph.meta.dimension_a;
  const primary = twoSided ? graph.nodes.filter((node) => node.dimension === graph.meta.dimension_a) : graph.nodes;
  return {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    total: primary.reduce((acc, node) => acc + node.value, 0),
    valor: (graph.meta as { documents_value?: number }).documents_value ?? 0,
    topNodes: [...citacoesGraphNodes(graph)].sort((a, b) => b.value - a.value),
  };
}

/** Dados mínimos de um nó necessários para o drill-down para a pesquisa. */
export type CitacoesNodeRef = Pick<CitacoesGraphNode, "dimension" | "key" | "label"> & {
  nif?: string | null;
};

/**
 * Traduz um nó em filtros da pesquisa.
 *
 * As partes são procuradas por **nome** (o portal não publica NIF/NIPC das partes
 * na lista) e, quando o NIF veio do documento analisado, por NIF.
 */
export function citacoesNodeSearchParams(node: CitacoesNodeRef): CitacoesSearchParams {
  const nif = node.nif && /^\d{9}$/.test(String(node.nif)) ? String(node.nif) : null;
  switch (node.dimension) {
    case "parte_ativa":
    case "parte_passiva":
      return nif ? { nif } : { nome: node.label };
    case "agente":
    case "interveniente":
    case "credor":
      return nif ? { nif } : { nome: node.label };
    case "nif":
      return { nif: node.key };
    case "tribunal":
      return { tribunal: node.key };
    case "sede":
      return { tribunal_comarca: node.key };
    case "comarca":
      return { comarca_judicial: node.key };
    case "tipo":
      return { tipo: node.key };
    case "ato":
      return { ato: node.key };
    case "especie":
      return { especie: node.key };
    case "processo":
      return { processo: node.key };
    case "modelo":
      return { modelo: node.key };
    case "titulo":
      return { titulo: node.key };
    case "ano": {
      const ano = String(node.key).slice(0, 4);
      return { data_from: `${ano}-01-01`, data_to: `${ano}-12-31` };
    }
    case "mes":
      return {
        data_from: `${node.key}-01`,
        data_to: `${node.key}-31`,
      };
    default:
      return { q: node.label };
  }
}

/** Vizinhos de um nó (arestas onde participa), para o painel de detalhe. */
export function citacoesNeighbours(
  graph: StudioGraph | null,
  nodeId: string,
  metric: CitacoesGraphMetric,
  limit = 12,
): { node: CitacoesStudioNode | undefined; edge: CitacoesStudioEdge }[] {
  if (!graph) return [];
  const byId = new Map(citacoesGraphNodes(graph).map((node) => [node.id, node]));
  return citacoesGraphEdges(graph)
    .filter((edge) => edge.source === nodeId || edge.target === nodeId)
    .map((edge) => ({ node: byId.get(edge.source === nodeId ? edge.target : edge.source), edge }))
    .filter((item) => item.node)
    .sort((a, b) => metricEdge(b.edge as unknown as CitacoesGraphEdge, metric) - metricEdge(a.edge as unknown as CitacoesGraphEdge, metric))
    .slice(0, limit);
}

export function citacoesGraphToCsv(graph: StudioGraph): string {
  const labelOf = (id: string) => graph.nodes.find((node) => node.id === id)?.label ?? id;
  const lines = ["tipo,origem,destino,editais,mencoes,valor"];
  graph.edges.forEach((edge) => {
    const rich = edge as CitacoesStudioEdge;
    lines.push(
      [
        "aresta",
        JSON.stringify(labelOf(edge.source)),
        JSON.stringify(labelOf(edge.target)),
        rich.count,
        rich.mentions ?? rich.count,
        rich.valor ?? 0,
      ].join(","),
    );
  });
  graph.nodes.forEach((node) => {
    const rich = node as CitacoesStudioNode;
    lines.push(
      ["no", JSON.stringify(node.label), "", rich.editais ?? node.count, rich.mencoes ?? node.count, rich.valor ?? 0].join(","),
    );
  });
  return lines.join("\n");
}

export function downloadCitacoesFile(filename: string, content: string, mime: string) {
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
 * Só conhecem «valor» e «contratos»; aqui usam-se contagens («contratos») e os
 * resumos são substituídos por `citacoesNodeSummary`/`citacoesEdgeSummary`.
 */
export const CITACOES_COMPONENT_METRIC = "contratos" as const;
