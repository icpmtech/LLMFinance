/**
 * Métricas da barra (dock / barra de tarefas) publicadas pelo componente `Dock`.
 *
 * O gestor de janelas precisa da **espessura real** da barra para maximizar as
 * janelas sem deixar um vão por baixo: no aspeto Windows a barra cresce com o
 * espaço disponível (e desaparece quando está escondida), pelo que um valor fixo
 * deixaria a janela a flutuar sobre um vazio.
 */
import { useSyncExternalStore } from "react";

const EVENT = "finance-llm-dock-metrics";

/** Espessura da barra + folga (px); `0` quando não reserva espaço. */
let thickness = 0;

export function setDockThickness(value: number) {
  const next = Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
  if (next === thickness) return;
  thickness = next;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
}

export function getDockThickness() {
  return thickness;
}

function subscribe(onChange: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}

/** Espaço a reservar à barra (espessura + 16 px de folga). */
export function useDockThickness() {
  return useSyncExternalStore(subscribe, getDockThickness, getDockThickness);
}
