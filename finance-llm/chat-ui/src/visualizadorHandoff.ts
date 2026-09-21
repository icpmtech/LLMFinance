/**
 * Passagem de dashboards entre a galeria e o editor do Visualizador.
 *
 * Há dois caminhos, e é preciso os dois:
 *
 * 1. **`localStorage`** — quem monta o editor a seguir (o caso normal: a galeria
 *    navega para `/visualizador` e o editor é montado do zero) lê daqui o
 *    trabalho a retomar.
 * 2. **evento** — em modo janelas o editor pode **já estar montado** noutra
 *    janela; nesse caso a mudança de `localStorage` não chega, porque o estado
 *    React só é inicializado uma vez. O evento entrega o dashboard à instância
 *    que já está a correr.
 */
import { useEffect } from "react";
import type { Dashboard, VisualConfig } from "./visualizadorApi";

export const HANDOFF_EVENT = "visualizador:open-dashboard";
const WORKSPACE_KEY = "visualizador:workspace";
const DATASET_KEY = "visualizador:dataset";

/** O mesmo formato que o editor guarda para retomar o trabalho. */
export type VisualizadorWorkspace = {
  name: string;
  dashboardId: string | null;
  dataset: string | null;
  filters: Record<string, unknown>;
  search: string;
  visuals: VisualConfig[];
};

export function workspaceFromDashboard(dashboard: Dashboard): VisualizadorWorkspace {
  return {
    name: dashboard.name,
    dashboardId: dashboard.id ?? null,
    dataset: dashboard.dataset,
    filters: dashboard.filters ?? {},
    search: "",
    visuals: dashboard.visuals ?? [],
  };
}

/**
 * Abre um dashboard no editor: grava o trabalho a retomar e avisa quem já esteja
 * montado. O chamador deve navegar para a vista do editor depois desta chamada.
 */
export function openDashboardInEditor(dashboard: Dashboard): VisualizadorWorkspace {
  const workspace = workspaceFromDashboard(dashboard);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
      if (workspace.dataset) window.localStorage.setItem(DATASET_KEY, workspace.dataset);
    } catch {
      /* localStorage cheio ou indisponível: o evento ainda entrega o dashboard */
    }
    window.dispatchEvent(new CustomEvent<VisualizadorWorkspace>(HANDOFF_EVENT, { detail: workspace }));
  }
  return workspace;
}

/** Lê o trabalho pendente deixado pela galeria (usado ao montar o editor). */
export function readPendingWorkspace(): VisualizadorWorkspace | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<VisualizadorWorkspace>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      name: parsed.name || "Análise sem título",
      dashboardId: parsed.dashboardId ?? null,
      dataset: parsed.dataset ?? null,
      filters: parsed.filters ?? {},
      search: parsed.search ?? "",
      visuals: Array.isArray(parsed.visuals) ? parsed.visuals : [],
    };
  } catch {
    return null;
  }
}

/** Escuta dashboards abertos a partir da galeria (editor já montado). */
export function useDashboardHandoff(handler: (workspace: VisualizadorWorkspace) => void): void {
  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<VisualizadorWorkspace>).detail;
      if (detail && Array.isArray(detail.visuals)) handler(detail);
    };
    window.addEventListener(HANDOFF_EVENT, listener);
    return () => window.removeEventListener(HANDOFF_EVENT, listener);
  }, [handler]);
}

export function persistWorkspace(workspace: VisualizadorWorkspace): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
    if (workspace.dataset) window.localStorage.setItem(DATASET_KEY, workspace.dataset);
  } catch {
    /* sem persistência local: o trabalho continua apenas em memória */
  }
}

export function storedDatasetId(fallback = "contrato"): string {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(DATASET_KEY) || fallback;
}

/** Guarda só o dataset escolhido (sem tocar nos visuais guardados). */
export function persistDatasetId(datasetId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DATASET_KEY, datasetId);
  } catch {
    /* sem persistência local */
  }
}
