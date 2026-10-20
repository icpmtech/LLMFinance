/**
 * Conversão da resposta do Grafo da Transparência no modelo dos grafos
 * partilhados (`StudioGraph`), para reutilizar o `GraphCanvas` sem duplicar o
 * desenho, o layout de forças e as interações.
 */
import type { StudioEdge, StudioGraph, StudioNode } from "../graph/graphStudio";
import type { TgAresta, TgGrafoResposta, TgNo, TgTipoInfo } from "../../transparenciaGrafoApi";

export const TG_CORES: Record<string, string> = {
  pessoa: "#f472b6",
  cargo: "#fbbf24",
  entidade: "#2dd4bf",
  empresa: "#60a5fa",
};

export const TG_CORES_FALLBACK = "#94a3b8";

export const TG_TIPO_LABELS: Record<string, string> = {
  pessoa: "Pessoas",
  cargo: "Cargos",
  entidade: "Entidades públicas",
  empresa: "Empresas",
};

export type TgStudioNode = StudioNode & {
  nif?: string | null;
  concelho?: string | null;
  lat?: number | null;
  lon?: number | null;
  grau: number;
  peso: number;
  anos: number[];
};

export type TgStudioEdge = StudioEdge & {
  relacao: string;
  anos: number[];
};

/** Nó da API → nó desenhável (raio pela raiz do grau, cor pelo tipo). */
export function noParaStudio(no: TgNo, maxGrau: number, tipos?: Record<string, TgTipoInfo>): TgStudioNode {
  const tipo = String(no.type || "empresa");
  const grau = Number(no.grau ?? no.count ?? 0);
  return {
    id: no.id,
    key: no.key ?? no.id,
    label: no.label || no.id,
    dimension: tipo,
    type: tipo,
    count: grau,
    total_value: 0,
    value: grau,
    radius: 9 + Math.min(17, Math.sqrt(Math.max(0, grau) / Math.max(1, maxGrau)) * 17),
    color: TG_CORES[tipo] ?? TG_CORES_FALLBACK,
    legendKey: tipo,
    legendLabel: tipos?.[tipo]?.label ?? TG_TIPO_LABELS[tipo] ?? tipo,
    nif: no.nif ?? null,
    concelho: no.concelho ?? null,
    lat: no.lat ?? null,
    lon: no.lon ?? null,
    grau,
    peso: Number(no.peso ?? 0),
    anos: no.anos ?? [],
  };
}

export function arestaParaStudio(aresta: TgAresta, maxPeso: number): TgStudioEdge {
  const peso = Number(aresta.count ?? 1);
  return {
    source: aresta.source,
    target: aresta.target,
    count: peso,
    value: 0,
    weight: Math.max(0.08, peso / Math.max(1, maxPeso)),
    relation: aresta.relation,
    relacao: aresta.relacao,
    anos: aresta.anos ?? [],
  };
}

export function toStudioGraph(resposta: TgGrafoResposta | null): StudioGraph | null {
  if (!resposta || resposta.error) return null;
  const nodes = resposta.nodes ?? [];
  if (!nodes.length) return null;
  const maxGrau = Math.max(...nodes.map((no) => Number(no.grau ?? no.count ?? 0)), 1);
  const arestas = resposta.edges ?? [];
  const maxPeso = Math.max(...arestas.map((aresta) => Number(aresta.count ?? 1)), 1);
  const tipos = resposta.meta?.tipos;
  return {
    nodes: nodes.map((no) => noParaStudio(no, maxGrau, tipos)),
    edges: arestas.map((aresta) => arestaParaStudio(aresta, maxPeso)),
    meta: {
      dimension_a: "no",
      dimension_b: null,
      metric: "ligacoes",
      complete: true,
      sample_order: "grau",
      sample_limit: resposta.meta?.sample_limit ?? nodes.length,
      documents_scanned: resposta.meta?.documents_scanned ?? 0,
      documents_matching: resposta.meta?.documents_matching ?? nodes.length,
    } as unknown as StudioGraph["meta"],
  };
}

export function noResumo(no: StudioNode): string {
  const rico = no as TgStudioNode;
  const partes = [`${rico.grau ?? 0} ligações`];
  if (rico.concelho) partes.push(rico.concelho);
  if (rico.nif) partes.push(`NIF ${rico.nif}`);
  return partes.join(" · ");
}

export function arestaResumo(aresta: StudioEdge): string {
  const rica = aresta as TgStudioEdge;
  const anos = rica.anos?.length ? ` · ${rica.anos[0]}–${rica.anos[rica.anos.length - 1]}` : "";
  return `${rica.relation ?? "ligação"} · ${aresta.count} registo(s)${anos}`;
}

/** Vizinhos de um nó tal como o grafo os desenha (para a ficha lateral). */
export function vizinhosDe(
  graph: StudioGraph | null,
  noId: string | null,
): { no: TgStudioNode | undefined; aresta: TgStudioEdge; sentido: "entrada" | "saida" }[] {
  if (!graph || !noId) return [];
  const porId = new Map(graph.nodes.map((no) => [no.id, no as TgStudioNode]));
  const saida: { no: TgStudioNode | undefined; aresta: TgStudioEdge; sentido: "entrada" | "saida" }[] = [];
  for (const aresta of graph.edges as TgStudioEdge[]) {
    if (aresta.source === noId) saida.push({ no: porId.get(aresta.target), aresta, sentido: "saida" });
    else if (aresta.target === noId) saida.push({ no: porId.get(aresta.source), aresta, sentido: "entrada" });
  }
  return saida.sort((a, b) => b.aresta.count - a.aresta.count);
}

export function legendaDe(graph: StudioGraph | null): { key: string; label: string; color: string; total: number }[] {
  const mapa = new Map<string, { key: string; label: string; color: string; total: number }>();
  for (const no of graph?.nodes ?? []) {
    const atual = mapa.get(no.legendKey) ?? {
      key: no.legendKey,
      label: no.legendLabel,
      color: no.color,
      total: 0,
    };
    atual.total += 1;
    mapa.set(no.legendKey, atual);
  }
  return [...mapa.values()].sort((a, b) => b.total - a.total);
}
