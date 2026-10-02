/**
 * Abrir um resultado de pesquisa na aplicação certa do IQ OS.
 *
 * Os resultados trazem um alvo normalizado (`{view, arg, mode}`): a maioria abre
 * uma ficha interna (`company-detail:<nif>`, `contract-detail:<id>`,
 * `crm-account:<id>`) e os dados de Espanha abrem a app **Contratos Espanha**,
 * que lê o pedido do `localStorage` (contrato concreto ou entidade já filtrada).
 *
 * Em modo janelas abre (ou foca) a janela da aplicação; em modo página navega
 * para a vista. A decisão é do `App` (callback `onOpenView`), pelo que este
 * módulo não conhece o modo de layout.
 */
import { type ContratosEsEntry, writeContratosEsEntry } from "./contratosEsApi";
import { type ContratosFrEntry, writeContratosFrEntry } from "./contratosFrApi";
import { openWindow } from "./windows";

export type OpenTarget = { view: string; arg: string; mode?: string };

/** Vista interna da app de contratos públicos de Espanha. */
export const CONTRATOS_ES_VIEW = "contratos-es";

/** Vista interna da app de contratos públicos de França. */
export const CONTRATOS_FR_VIEW = "contratos-fr";

/** Deixa o pedido à app de contratos de Espanha (documento ou entidade). */
export function writeContratosEsRequest(target: OpenTarget): void {
  const entry: ContratosEsEntry =
    target.mode === "organo"
      ? { organo: target.arg }
      : target.mode === "adjudicatario"
        ? { adjudicatario: target.arg }
        : { doc: target.arg };
  writeContratosEsEntry(entry);
}

/** Deixa o pedido à app de contratos de França (documento ou entidade). */
export function writeContratosFrRequest(target: OpenTarget): void {
  const entry: ContratosFrEntry =
    target.mode === "acheteur"
      ? { acheteur: target.arg }
      : target.mode === "adjudicatario"
        ? { adjudicatario: target.arg }
        : { doc: target.arg };
  writeContratosFrEntry(entry);
}

export function openResult(
  target: OpenTarget | null | undefined,
  title: string,
  onOpenView?: (view: string, title?: string) => void,
): void {
  if (!target?.view) return;
  if (target.view === CONTRATOS_ES_VIEW) {
    if (target.arg) writeContratosEsRequest(target);
    if (onOpenView) onOpenView(CONTRATOS_ES_VIEW, title);
    else openWindow(CONTRATOS_ES_VIEW, undefined, { title });
    return;
  }
  if (target.view === CONTRATOS_FR_VIEW) {
    if (target.arg) writeContratosFrRequest(target);
    if (onOpenView) onOpenView(CONTRATOS_FR_VIEW, title);
    else openWindow(CONTRATOS_FR_VIEW, undefined, { title });
    return;
  }
  // As fichas levam o identificador no próprio nome da vista; no CRM já vem lá.
  const view = !target.arg || target.view.includes(":") ? target.view : `${target.view}:${target.arg}`;
  if (onOpenView) onOpenView(view, title);
  else openWindow(view, undefined, { title });
}
