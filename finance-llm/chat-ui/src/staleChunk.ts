/**
 * Recuperação de chunks obsoletos («bundle antigo»).
 *
 * Depois de uma nova compilação, os ficheiros em `/assets/` mudam de hash. Se a
 * aplicação estiver aberta com o *bundle* antigo (separador de ontem, `index.html`
 * em cache, service worker com o shell antigo), qualquer `import()` dinâmico
 * falha com «Failed to fetch dynamically imported module: …/assets/algo-HASH.js»
 * — o ficheiro já não existe no servidor.
 *
 * O Vite avisa disso com o evento `vite:preloadError` no `window`. Aqui
 * recarregamos a página uma vez (com guarda de tempo, para não entrar em ciclo),
 * o que faz o browser pedir o `index.html` e o bundle atuais. Quem usa a app não
 * vê um erro que não sabe resolver; vê a app atualizada.
 */
const RELOAD_KEY = "iq-os:preload-reload";
const RELOAD_WINDOW_MS = 20_000;

/** Mensagens que significam «o ficheiro do build antigo já não existe». */
export function isStaleBundleError(message: string): boolean {
  return (
    /dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /Failed to fetch/i.test(message)
  );
}

/** Recarrega uma vez por janela de tempo (para não criar um ciclo de recargas). */
export function reloadOnce(reason: string): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY) || 0);
    if (Date.now() - last < RELOAD_WINDOW_MS) return false;
    window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    /* sem sessionStorage: recarrega na mesma */
  }
  if (reason && typeof console !== "undefined") console.info(`A recarregar a aplicação: ${reason}`);
  window.location.reload();
  return true;
}

/** Instala a recuperação automática do bundle obsoleto. */
export function installPreloadRecovery(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("vite:preloadError", () => {
    reloadOnce("bundle antigo (vite:preloadError)");
  });
  // Alguns bundles antigos não disparam o evento do Vite: apanhar o erro global.
  window.addEventListener("unhandledrejection", (event) => {
    const message = event.reason instanceof Error ? event.reason.message : String(event.reason ?? "");
    if (isStaleBundleError(message)) reloadOnce("bundle antigo (promessa rejeitada)");
  });
}
