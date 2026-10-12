/**
 * Apoio ao grafo da Descoberta: rótulos das dimensões, cor do nó e as operações
 * de vista (isolar vizinhança, ver só um tipo, esconder um tipo).
 *
 * Vive fora do componente para a página só chamar funções puras sobre o grafo —
 * o mesmo grafo do servidor entra, um sub-grafo sai, sem tocar no original.
 */
import { TYPE_COLORS, typeLabel, type StudioGraph, type StudioNode } from "../graph/graphStudio";

/** Cor do nó: a do tipo (paleta partilhada) quando não vier já no nó. */
export function corDoNo(node: { type?: string; dimension?: string; color?: string }): string {
  if (node.color) return node.color;
  const chave = String(node.type || node.dimension || "").toLowerCase();
  return TYPE_COLORS[chave] ?? TYPE_COLORS.outra;
}

/** Nome curto legível de cada dimensão da descoberta (e a sigla usada na ficha). */
export const DIMENSAO_LABEL: Record<string, { label: string; sigla: string }> = {
  empresa: { label: "empresa analisada", sigla: "EM" },
  adjudicante: { label: "compradores públicos", sigla: "CP" },
  entidade: { label: "entidades", sigla: "EN" },
  cpv: { label: "classificações CPV", sigla: "CP" },
  pessoa: { label: "pessoas", sigla: "PE" },
  processo: { label: "processos", sigla: "PR" },
  firma: { label: "firmas", sigla: "FI" },
  marca: { label: "marcas", sigla: "MA" },
  subvencao: { label: "subvenções", sigla: "SU" },
  noticia: { label: "menções na imprensa", sigla: "IM" },
  contrato: { label: "contratos", sigla: "CO" },
  regiao: { label: "regiões", sigla: "RE" },
  outra: { label: "outros nós", sigla: "OU" },
};

export function rotuloDimensao(dimensao: string | undefined, tipo?: string): string {
  const chave = String(dimensao || tipo || "").toLowerCase();
  return DIMENSAO_LABEL[chave]?.label ?? typeLabel(String(tipo || dimensao || "outra"));
}

/** Nós e ligações que tocam o nó indicado (ele próprio incluído) — a vizinhança. */
export function vizinhanca(grafo: StudioGraph, nodeId: string): StudioGraph {
  const ids = new Set<string>([nodeId]);
  grafo.edges.forEach((edge) => {
    if (edge.source === nodeId) ids.add(edge.target);
    if (edge.target === nodeId) ids.add(edge.source);
  });
  return {
    nodes: grafo.nodes.filter((node) => ids.has(node.id)),
    edges: grafo.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    meta: grafo.meta,
  };
}

/**
 * Só os nós de uma dimensão — com a empresa analisada, quando existe.
 *
 * Sem a empresa o sub-grafo fica uma constelação solta: a âncora é o que dá
 * sentido a «ver só os compradores» ou «só as classificações».
 */
export function apenasDimensao(grafo: StudioGraph, dimensao: string): StudioGraph {
  const ancora = grafo.nodes.filter((node) => String(node.dimension) === "empresa");
  const escolhidos = grafo.nodes.filter((node) => String(node.dimension) === dimensao || String(node.type) === dimensao);
  const ids = new Set([...ancora, ...escolhidos].map((node) => node.id));
  return {
    nodes: grafo.nodes.filter((node) => ids.has(node.id)),
    edges: grafo.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    meta: grafo.meta,
  };
}

/** Sem os nós de uma dimensão (e sem as ligações que dependiam deles). */
export function semDimensao(grafo: StudioGraph, dimensao: string): StudioGraph {
  const fora = new Set(
    grafo.nodes
      .filter((node) => String(node.dimension) === dimensao || String(node.type) === dimensao)
      .map((node) => node.id),
  );
  return {
    nodes: grafo.nodes.filter((node) => !fora.has(node.id)),
    edges: grafo.edges.filter((edge) => !fora.has(edge.source) && !fora.has(edge.target)),
    meta: grafo.meta,
  };
}

/** Dimensões presentes no grafo, por ordem decrescente de número de nós. */
export function dimensoesDoGrafo(grafo: StudioGraph | null): { id: string; label: string; total: number }[] {
  if (!grafo) return [];
  const contagem = new Map<string, number>();
  grafo.nodes.forEach((node) => {
    const chave = String(node.dimension || node.type || "outra");
    contagem.set(chave, (contagem.get(chave) ?? 0) + 1);
  });
  return [...contagem.entries()]
    .map(([id, total]) => ({ id, label: rotuloDimensao(id), total }))
    .sort((a, b) => b.total - a.total);
}

/** Nó cujo identificador corresponde à chave de um contrato/pessoa, para foco por URL. */
export function noPorChave(grafo: StudioGraph, chave: string): StudioNode | undefined {
  return grafo.nodes.find((node) => String(node.key) === chave || node.id.endsWith(`:${chave}`));
}
