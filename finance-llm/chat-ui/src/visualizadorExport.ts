/**
 * Exportações do Visualizador: transferir ficheiros do backend, guardar a imagem
 * de um gráfico (PNG) e imprimir/gerar PDF do dashboard.
 *
 * O PNG é feito no cliente a partir do SVG do Recharts: serializa-se o SVG,
 * desenha-se num canvas com fundo opaco (o tema é escuro) e exporta-se — sem
 * dependências novas e sem servidor de renderização.
 */
import {
  buildQuery,
  exportVisualQuery,
  runVisualQuery,
  type QueryResult,
  type VisualConfig,
  type VisualQueryRequest,
} from "./visualizadorApi";

/** Descarrega um ficheiro gerado no browser. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Exporta o resultado de uma consulta pelo backend (CSV ou Excel). */
export async function exportVisual(format: "csv" | "xlsx", payload: VisualQueryRequest): Promise<void> {
  const { blob, filename } = await exportVisualQuery(format, payload);
  downloadBlob(blob, filename);
}

/** Exporta as linhas de um resultado já obtido (sem novo pedido ao backend). */
export function exportRowsAsCsv(result: QueryResult, name: string): void {
  const columns = result.columns ?? [];
  const separator = ";";
  const escape = (value: unknown) => {
    if (value === null || value === undefined) return "";
    const text = typeof value === "number" ? String(value).replace(".", ",") : String(value);
    return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [
    `# Visualizador — IQ OS${separator}${result.dataset?.label ?? ""}`,
    `# Registos analisados${separator}${result.meta?.documents ?? ""}`,
    columns.map((column) => escape(column.label)).join(separator),
    ...(result.rows ?? []).map((row) => columns.map((column) => escape(row[column.key])).join(separator)),
  ];
  const blob = new Blob([`\ufeff${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  downloadBlob(blob, `${slugify(name)}_${stamp()}.csv`);
}

/** Guarda o gráfico (SVG) de um cartão como PNG. */
export async function downloadChartPng(container: HTMLElement | null, name: string): Promise<void> {
  const svg = container?.querySelector("svg");
  if (!svg) throw new Error("Este visual não tem gráfico para exportar (use CSV/Excel).");
  const bounds = svg.getBoundingClientRect();
  const width = Math.max(320, Math.round(bounds.width));
  const height = Math.max(200, Math.round(bounds.height));
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  background.setAttribute("width", "100%");
  background.setAttribute("height", "100%");
  background.setAttribute("fill", "#16181d");
  clone.insertBefore(background, clone.firstChild);

  const data = new XMLSerializer().serializeToString(clone);
  const image = new Image();
  const scale = 2; // exporta a 2x para não sair desfocado em relatórios
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("Não foi possível preparar a imagem do gráfico."));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(data)}`;
  });
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("O browser não disponibilizou o canvas.");
  context.fillStyle = "#16181d";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob((value) => resolve(value), "image/png"));
  if (!blob) throw new Error("Não foi possível gerar o PNG.");
  downloadBlob(blob, `${slugify(name)}_${stamp()}.png`);
}

/**
 * Exporta **todos** os visuais de um dashboard para CSV (um ficheiro por visual).
 *
 * Devolve quantos ficheiros foram gerados, para a UI poder confirmar.
 */
export async function exportDashboardCsv(
  dashboardName: string,
  visuals: VisualConfig[],
  datasetId: string,
  filters: Record<string, unknown> = {},
  search = "",
): Promise<number> {
  let exported = 0;
  for (const visual of visuals.slice(0, 12)) {
    const result = await runVisualQuery(buildQuery(visual, datasetId, filters, search));
    if (result.error && (result.rows ?? []).length === 0) continue;
    exportRowsAsCsv(result, `${dashboardName}_${visual.title || visual.id}`);
    exported += 1;
  }
  return exported;
}

/**
 * Imprime um dashboard (o browser oferece «Guardar como PDF»).
 *
 * Antes de imprimir, adiciona ao `body` a classe `visualizador-printing`, o que
 * ativa as regras de impressão definidas na página do Visualizador (fundo claro,
 * só o dashboard visível, cartões sem sombra nem animação).
 */
export function printVisualizador(): void {
  document.body.classList.add("visualizador-printing");
  const cleanup = () => {
    document.body.classList.remove("visualizador-printing");
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
  window.setTimeout(cleanup, 4000);
}

function slugify(value: string): string {
  return (value || "visualizador")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase()
    .slice(0, 48) || "visualizador";
}

function stamp(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}
