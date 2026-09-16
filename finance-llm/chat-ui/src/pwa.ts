/**
 * Suporte de PWA: registo do service worker e instalação da aplicação.
 *
 * - O service worker (`public/sw.js`) só é registado em produção; em
 *   desenvolvimento (Vite) atrapalharia o recarregamento a quente.
 * - `beforeinstallprompt` é capturado uma única vez e guardado, para que o
 *   botão "Instalar aplicação" (no painel do dock) possa ser mostrado quando o
 *   browser o permite.
 */
import { useEffect, useSyncExternalStore } from "react";

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice?: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let deferredPrompt: InstallPromptEvent | null = null;
let installed = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function isStandalone() {
  if (typeof window === "undefined") return false;
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  return window.matchMedia("(display-mode: standalone)").matches || window.matchMedia("(display-mode: fullscreen)").matches || iosStandalone;
}

/** Deve ser chamado uma vez, no arranque da aplicação. */
export function initPwa() {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event as InstallPromptEvent;
    emit();
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installed = true;
    emit();
  });

  window
    .matchMedia("(display-mode: standalone)")
    .addEventListener?.("change", () => emit());

  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Sem service worker a aplicação continua a funcionar normalmente.
      });
    });
  }
}

/** Estado da instalação + ação de instalar (quando o browser o permite). */
export function usePwaInstall() {
  const canInstall = useSyncExternalStore(
    subscribe,
    () => deferredPrompt !== null,
    () => false,
  );
  const standalone = useSyncExternalStore(subscribe, isStandalone, () => false);
  const installedApp = useSyncExternalStore(
    subscribe,
    () => installed,
    () => false,
  );

  useEffect(() => {
    // O browser pode disparar o evento antes de a aplicação montar.
    emit();
  }, []);

  const install = async () => {
    const prompt = deferredPrompt;
    if (!prompt) return;
    deferredPrompt = null;
    emit();
    await prompt.prompt();
    await prompt.userChoice;
    emit();
  };

  return { canInstall, standalone, installed: installedApp, install };
}
