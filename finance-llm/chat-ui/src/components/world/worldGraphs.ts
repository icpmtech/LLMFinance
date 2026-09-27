/**
 * Adaptadores dos grafos do World Model para o canvas partilhado.
 *
 * Traduzem as duas projeções em grafo do módulo — as **relações** do mundo
 * (`/world/graph`) e a **rede neuronal dinâmica** (`/world/network/graph`) — para
 * o formato `StudioGraph` que o `GraphCanvas` já desenha (rede orgânica,
 * hierárquica ou circular), com raio/cores/legenda derivados de cada projeção.
 *
 * A forma do nó (`type`) segue o desenho do canvas: empresa ■, entidade pública
 * ◆, pessoa ● e padrão de memória ⬢.
 */
import type { StudioEdge, StudioGraph, StudioNode } from "../graph/graphStudio";
import type {
  EvidenceGraph,
  ExecutionGraph,
  NetworkEdge,
  NetworkGraph,
  PipelineGraph,
  WorldGraph,
  WorldGraphEdge,
  WorldGraphNode,
} from "../../worldApi";

/** Cores por tipo de entidade (iguais às do resto da plataforma). */
export const WORLD_TYPE_COLORS: Record<string, string> = {
  empresa: "#2dd4bf",
  entidade_publica: "#60a5fa",
  pessoa: "#f472b6",
  memoria: "#fbbf24",
  outro: "#94a3b8",
};

export const WORLD_TYPE_LABELS: Record<string, string> = {
  empresa: "Empresas",
  entidade_publica: "Entidades públicas",
  pessoa: "Pessoas",
  memoria: "Memória (padrões)",
  outro: "Outros",
};

/** Cores por nível de risco (usadas no grafo do mundo). */
export const RISK_COLORS: Record<string, string> = {
  baixo: "#2dd4bf",
  médio: "#fbbf24",
  elevado: "#fb7185",
  "—": "#94a3b8",
};

/** Forma do nó no canvas, a partir do tipo semântico. */
export function shapeForWorldType(entityType?: string | null): string {
  switch (String(entityType || "").toLowerCase()) {
    case "empresa":
      return "company";
    case "entidade_publica":
      return "entity";
    case "pessoa":
      return "person";
    case "memoria":
      return "source";
    default:
      return "company";
  }
}

function normalize(value: number | undefined | null, max: number): number {
  if (!value || !max) return 0.15;
  return Math.max(0.05, Math.min(1, value / max));
}

/**
 * Grafo das **relações do mundo** (`/world/graph`): nós coloridos pelo risco,
 * dimensionados pelo valor movimentado, ligados pelas adjudicações e cargos.
 */
export function toWorldStudioGraph(graph: WorldGraph | null): StudioGraph | null {
  if (!graph || graph.error || !graph.nodes?.length) return null;
  const values = graph.nodes.map((node) => Math.abs(node.contracts_value ?? node.degree ?? 1));
  const max = Math.max(...values, 1);

  const nodes: StudioNode[] = graph.nodes.map((node: WorldGraphNode) => {
    const value = Math.abs(node.contracts_value ?? node.degree ?? 1);
    const riskKey = (node.risk_label as string) || "—";
    return {
      id: node.id,
      key: node.id,
      label: node.name || node.id,
      dimension: "entidade",
      type: shapeForWorldType(node.entity_type),
      role: node.entity_type,
      count: node.degree ?? 0,
      total_value: node.contracts_value ?? 0,
      value,
      radius: 10 + Math.min(16, Math.sqrt(value / max) * 16),
      color: RISK_COLORS[riskKey] ?? RISK_COLORS["—"],
      legendKey: riskKey,
      legendLabel: `Risco ${riskKey}`,
      // Campos próprios do mundo, lidos pelas dicas (`worldNodeSummary`).
      risk: node.risk ?? null,
      risk_label: node.risk_label ?? null,
      degree: node.degree ?? 0,
      entity_type: node.entity_type ?? null,
    } as unknown as StudioNode;
  });

  const weights = graph.edges.map((edge) => Math.abs(edge.value_sum ?? edge.contracts_count ?? 1));
  const maxWeight = Math.max(...weights, 1);
  const edges: StudioEdge[] = graph.edges.map((edge: WorldGraphEdge) => ({
    source: edge.source,
    target: edge.target,
    count: edge.contracts_count ?? 0,
    value: edge.value_sum ?? 0,
    weight: normalize(Math.abs(edge.value_sum ?? edge.contracts_count ?? 1), maxWeight),
  }));

  return { nodes, edges, meta: (graph.meta ?? {}) as unknown as StudioGraph["meta"] };
}

/**
 * Grafo da **rede neuronal dinâmica** (`/world/network/graph`).
 *
 * Nós = entidades (neurónios), dimensionados pela **ativação** (eventos
 * recentes) e coloridos pelo tipo; os padrões de memória entram como nós ⬢
 * ligados à entidade que os recordou. Arestas = sinapses, com espessura pelo
 * peso do ciclo atual.
 */
export function toNetworkStudioGraph(graph: NetworkGraph | null): StudioGraph | null {
  if (!graph || !graph.nodes?.length) return null;
  const activations = graph.nodes.map((node) => Math.max(1, node.activation ?? node.count ?? 1));
  const maxActivation = Math.max(...activations, 1);

  const nodes: StudioNode[] = graph.nodes.map((node) => {
    const activation = Math.max(1, node.activation ?? node.count ?? 1);
    const semantic = node.type || "empresa";
    return {
      id: node.id,
      key: node.id,
      label: node.label || node.id,
      dimension: node.dimension ?? (semantic === "memoria" ? "memoria" : "entidade"),
      type: shapeForWorldType(semantic),
      role: semantic,
      count: node.activation ?? node.count ?? 0,
      total_value: node.expected_contracts ?? 0,
      value: activation,
      radius: 8 + Math.min(18, Math.sqrt(activation / maxActivation) * 18),
      color: WORLD_TYPE_COLORS[semantic] ?? WORLD_TYPE_COLORS.outro,
      legendKey: semantic,
      legendLabel: WORLD_TYPE_LABELS[semantic] ?? semantic,
      // Sinais da rede, lidos pelas dicas (`networkNodeSummary`).
      risk: node.risk ?? null,
      risk_label: node.risk_label ?? null,
      score: node.score ?? null,
      expected_contracts: node.expected_contracts ?? null,
      risk_after: node.risk_after ?? null,
      memory_hits: node.memory_hits ?? 0,
      trend: node.trend ?? null,
    } as unknown as StudioNode;
  });

  const weights = graph.edges.map((edge) => Math.abs(edge.weight ?? 0.1));
  const maxWeight = Math.max(...weights, 0.1);
  const edges: StudioEdge[] = graph.edges.map((edge: NetworkEdge) => ({
    source: edge.source,
    target: edge.target,
    count: edge.count ?? 0,
    value: edge.value ?? 0,
    weight: normalize(Math.abs(edge.weight ?? 0.1), maxWeight),
  }));

  return { nodes, edges, meta: { ...(graph.meta ?? {}), dimension_a: "entidade" } as unknown as StudioGraph["meta"] };
}

/** Resumo do nó da rede (a dica do canvas não conhece estes campos). */
export function networkNodeSummary(node: StudioNode): string {
  const activation = node.count ?? 0;
  const parts = [`ativos: ${activation}`];
  const extra = node as StudioNode & {
    risk_label?: string | null;
    score?: number | null;
    expected_contracts?: number | null;
    risk_after?: number | null;
    memory_hits?: number;
    trend?: string | null;
  };
  if (typeof extra.score === "number") parts.push(`previsão: ${extra.score.toFixed(3)}`);
  if (typeof extra.expected_contracts === "number") parts.push(`contratos esperados: ${extra.expected_contracts}`);
  if (extra.risk_label) parts.push(`risco: ${extra.risk_label}`);
  if (typeof extra.risk_after === "number") parts.push(`risco projetado: ${extra.risk_after.toFixed(2)}`);
  if (extra.memory_hits) parts.push(`memória: ${extra.memory_hits}×`);
  return parts.join(" · ");
}

/** Resumo da aresta da rede (sinapse). */
export function networkEdgeSummary(edge: StudioEdge): string {
  const kind = (edge as StudioEdge & { kind?: string }).kind;
  return `${kind === "memoria" ? "memória" : "sinapse"} · peso ${edge.weight.toFixed(2)} · ${edge.count} contratos`;
}

/** Resumo do nó do grafo do mundo. */
export function worldNodeSummary(node: StudioNode): string {
  const extra = node as StudioNode & { risk?: number; risk_label?: string; degree?: number };
  const value = new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(
    node.total_value ?? 0,
  );
  const parts = [`grau ${extra.degree ?? node.count ?? 0}`, `${value} €`];
  if (extra.risk_label) parts.push(`risco ${extra.risk_label}`);
  return parts.join(" · ");
}

/** Resumo da aresta do mundo (adjudicação/cargo). */
export function worldEdgeSummary(edge: StudioEdge): string {
  const value = new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(edge.value ?? 0);
  return `${edge.count} contrato(s) · ${value} €`;
}

/* ------------------------------------------------------------------ */
/* Grafos do agente: execução, evidências e pipeline                   */
/* ------------------------------------------------------------------ */

/** Cores por tipo de nó nos grafos do agente. */
export const AGENT_NODE_COLORS: Record<string, string> = {
  passo: "#38bdf8",
  sujeito: "#2dd4bf",
  afirmacao: "#fbbf24",
  evidencia: "#a78bfa",
  fonte: "#94a3b8",
  camada: "#60a5fa",
};

/** Forma do nó no canvas para os grafos do agente. */
export function shapeForAgentKind(kind?: string | null): string {
  switch (String(kind || "").toLowerCase()) {
    case "passo":
      return "hexagon";
    case "afirmacao":
      return "circle";
    case "evidencia":
      return "square";
    case "fonte":
      return "diamond";
    case "sujeito":
      return "diamond";
    default:
      return "square";
  }
}

/**
 * Grafo de **execução do pipeline** (`/world/pipeline/graph`): as camadas com a
 * volumetria real, na ordem do diagrama (disposição hierárquica).
 */
export function toPipelineStudioGraph(graph: PipelineGraph | null | undefined): StudioGraph | null {
  if (!graph?.nodes?.length) return null;
  const values = graph.nodes.map((node) => Math.max(1, node.documents ?? 1));
  const max = Math.max(...values, 1);
  const nodes: StudioNode[] = graph.nodes.map((node) => ({
    id: node.id,
    key: node.id,
    label: node.label,
    dimension: "camada",
    type: shapeForAgentKind("passo"),
    role: node.backend,
    count: node.documents ?? 0,
    total_value: 0,
    value: Math.max(1, node.documents ?? 1),
    radius: 12 + Math.min(16, Math.sqrt(Math.max(1, node.documents ?? 1) / max) * 16),
    color: AGENT_NODE_COLORS.camada,
    legendKey: "camada",
    legendLabel: "Camadas do pipeline",
    ...({ backend: node.backend, hint: node.hint, artifacts: node.artifacts } as Record<string, unknown>),
  })) as unknown as StudioNode[];

  const edges: StudioEdge[] = graph.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    count: 1,
    value: 0,
    weight: 0.6,
  }));
  return { nodes, edges, meta: { dimension_a: "camada" } as unknown as StudioGraph["meta"] };
}

/**
 * Grafo de **execução do agente**: passos (planeador → observação → rede →
 * recolha → simulação → verificação → narrativa), ligados pelo dado que passa.
 */
export function toExecutionStudioGraph(graph: ExecutionGraph | null | undefined): StudioGraph | null {
  if (!graph?.nodes?.length) return null;
  const max = Math.max(...graph.nodes.map((node) => Math.max(0.05, node.elapsed_s)), 0.05);
  const nodes: StudioNode[] = graph.nodes.map((node) => ({
    id: node.id,
    key: node.id,
    label: `${node.label} · ${node.action}`,
    dimension: "passo",
    type: shapeForAgentKind("passo"),
    role: node.agent,
    count: Object.keys(node.outputs ?? {}).length,
    total_value: 0,
    value: Math.max(0.05, node.elapsed_s),
    radius: 12 + Math.min(14, (Math.max(0.05, node.elapsed_s) / max) * 14),
    color: node.status === "concluído" ? AGENT_NODE_COLORS.passo : "#fb7185",
    legendKey: node.agent,
    legendLabel: node.agent,
    ...({ outputs: node.outputs, note: node.note, elapsed_s: node.elapsed_s, status: node.status } as Record<string, unknown>),
  })) as unknown as StudioNode[];

  const edges: StudioEdge[] = graph.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    count: 1,
    value: 0,
    weight: 0.7,
  }));
  return { nodes, edges, meta: { dimension_a: "passo" } as unknown as StudioGraph["meta"] };
}

/**
 * Grafo de **evidências**: conclusões → factos → fontes (é o que permite auditar
 * cada frase do relatório até ao documento de origem).
 */
export function toEvidenceStudioGraph(graph: EvidenceGraph | null | undefined): StudioGraph | null {
  if (!graph?.nodes?.length) return null;
  const nodes: StudioNode[] = graph.nodes.map((node) => {
    const kind = node.type || "evidencia";
    const base = kind === "afirmacao" ? 1 + (node.confidence ?? 0) * 3 : kind === "fonte" ? 2 : 3;
    return {
      id: node.id,
      key: node.id,
      label: node.label,
      dimension: kind,
      type: shapeForAgentKind(kind),
      role: node.claim_kind ?? node.source_index ?? kind,
      count: node.count ?? 1,
      total_value: node.total_value ?? 0,
      value: base,
      radius: 8 + Math.min(12, base * 2.4),
      color: AGENT_NODE_COLORS[kind] ?? AGENT_NODE_COLORS.evidencia,
      legendKey: kind,
      legendLabel: kind,
      ...({ source_index: node.source_index, source_id: node.source_id, confidence: node.confidence } as Record<string, unknown>),
    } as unknown as StudioNode;
  });

  const edges: StudioEdge[] = graph.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    count: 1,
    value: 0,
    weight: edge.kind === "suporte" ? 0.9 : 0.5,
  }));
  return { nodes, edges, meta: { dimension_a: "afirmacao", dimension_b: "fonte" } as unknown as StudioGraph["meta"] };
}

/** Resumo do nó de um passo do agente (dica do canvas). */
export function executionNodeSummary(node: StudioNode): string {
  const extra = node as StudioNode & { outputs?: Record<string, unknown>; elapsed_s?: number; status?: string };
  const outputs = Object.entries(extra.outputs ?? {})
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
  return [`${extra.elapsed_s ?? 0}s`, extra.status ?? "", outputs].filter(Boolean).join(" · ");
}

/** Resumo do nó do pipeline. */
export function pipelineNodeSummary(node: StudioNode): string {
  const extra = node as StudioNode & { backend?: string; artifacts?: { label: string; documents: number | null }[] };
  const artifacts = (extra.artifacts ?? [])
    .filter((item) => item.documents)
    .map((item) => `${item.label}: ${item.documents}`)
    .join(" · ");
  return [`${extra.backend ?? ""}`, artifacts].filter(Boolean).join(" · ");
}

/** Resumo do nó de evidência (fonte ou afirmação). */
export function evidenceNodeSummary(node: StudioNode): string {
  const extra = node as StudioNode & { source_index?: string; source_id?: string; confidence?: number };
  if (extra.source_index) return `${extra.source_index}#${extra.source_id ?? ""}`;
  if (extra.confidence != null) return `confiança ${extra.confidence}`;
  return node.role ?? "";
}
