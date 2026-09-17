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
let dismissedState = false;
const DISMISS_KEY = "finance-llm-install-dismissed";
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** O utilizador já dispensou o convite de instalação. */
function isDismissed() {
  if (dismissedState) return true;
  if (typeof window === "undefined") return true;
  try {
    const saved = window.localStorage.getItem(DISMISS_KEY);
    dismissedState = Boolean(saved);
  } catch {
    dismissedState = true;
  }
  return dismissedState;
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
  const dismissed = useSyncExternalStore(subscribe, isDismissed, () => true);

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

  const dismiss = () => {
    dismissedState = true;
    try {
      window.localStorage.setItem(DISMISS_KEY, new Date().toISOString());
    } catch {
      // Sem localStorage: a dispensa vale só para esta sessão.
    }
    emit();
  };

  const resetDismiss = () => {
    dismissedState = false;
    try {
      window.localStorage.removeItem(DISMISS_KEY);
    } catch {
      // Sem localStorage: nada a limpar.
    }
    emit();
  };

  return { canInstall, standalone, installed: installedApp, install, dismissed, dismiss, resetDismiss };
}

/* ------------------------------------------------------------------ extras */

/**
 * O `beforeinstallprompt` só existe no Chromium. Nos restantes browsers (Safari,
 * Firefox) explicamos onde está a opção, porque a aplicação é instalável na
 * mesma (Safari: Partilha → Adicionar ao Dock; iOS: Adicionar ao ecrã principal;
 * Firefox: não suporta instalação de PWA).
 */
export type InstallHint = { browser: string; steps: string[] };

export function installHint(): InstallHint {
  if (typeof window === "undefined") return { browser: "Browser", steps: [] };
  const ua = window.navigator.userAgent;
  const iOS = /iPad|iPhone|iPod/.test(ua) || (ua.includes("Macintosh") && "ontouchend" in document);
  const edge = /Edg\//.test(ua);
  const chrome = /Chrome\//.test(ua) && !edge;
  const safari = /Safari\//.test(ua) && !chrome && !edge;

  if (iOS) {
    return {
      browser: "Safari (iPhone/iPad)",
      steps: ["Tocar em Partilhar", "Escolher «Adicionar ao ecrã principal»", "Confirmar com «Adicionar»"],
    };
  }
  if (safari) {
    return {
      browser: "Safari (macOS)",
      steps: ["Menu Ficheiro", "Escolher «Adicionar ao Dock»", "Confirmar o nome e adicionar"],
    };
  }
  if (edge) {
    return {
      browser: "Microsoft Edge",
      steps: ["Menu «…» no canto superior direito", "Aplicações → «Instalar este site como aplicação»", "Confirmar «Instalar»"],
    };
  }
  if (chrome) {
    return {
      browser: "Google Chrome",
      steps: ["Ícone de instalação na barra de endereço", "Ou menu «⋮» → «Transmitir, guardar e partilhar» → «Instalar página como aplicação»", "Confirmar «Instalar»"],
    };
  }
  return {
    browser: "Firefox ou outro",
    steps: [
      "O Firefox não instala PWA: use o Edge/Chrome para instalar o IQ OS",
      "Alternativa: descarregue o instalador para Windows (cria o atalho na mesma)",
    ],
  };
}

export type ServiceWorkerState =
  | "unsupported"
  | "none"
  | "installing"
  | "waiting"
  | "active"
  /** Registo existente mas sem worker ativo: instalação falhou (ex.: cache limpa a meio). */
  | "broken";

/** Estado do service worker (modo offline + versão em cache). */
export async function serviceWorkerState(): Promise<{
  state: ServiceWorkerState;
  version: string | null;
  scope: string | null;
  controlled: boolean;
}> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return { state: "unsupported", version: null, scope: null, controlled: false };
  }
  try {
    const registration = await withTimeout(
      navigator.serviceWorker.getRegistration(),
      5_000,
      undefined as ServiceWorkerRegistration | undefined,
    );
    const version = await readCacheVersion();
    const controlled = Boolean(navigator.serviceWorker.controller);
    if (!registration) return { state: "none", version, scope: null, controlled };
    if (registration.waiting) return { state: "waiting", version, scope: registration.scope, controlled };
    if (registration.installing) return { state: "installing", version, scope: registration.scope, controlled };
    if (registration.active) return { state: "active", version, scope: registration.scope, controlled };
    return { state: "broken", version, scope: registration.scope, controlled };
  } catch {
    return { state: "broken", version: null, scope: null, controlled: false };
  }
}

/** Versão da cache offline (`iq-os-shell-<versão>`), usada como versão da app. */
async function readCacheVersion(): Promise<string | null> {
  if (typeof caches === "undefined") return null;
  try {
    const keys = await caches.keys();
    const shell = keys.find((key) => key.startsWith("iq-os-shell-"));
    return shell ? shell.replace("iq-os-shell-", "") : null;
  } catch {
    return null;
  }
}

/** Limite de tempo para operações do service worker (alguns browsers ficam pendurados). */
function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return Promise.race([
    promise.catch(() => fallback),
    new Promise<T>((resolve) => window.setTimeout(() => resolve(fallback), ms)),
  ]);
}

/**
 * Repara o modo offline: remove um registo inválido e volta a registar o
 * service worker (acontece quando a instalação falha, por exemplo após limpar a
 * cache do browser a meio).
 */
export async function repairOfflineMode(): Promise<boolean> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return false;
  try {
    const registration = await navigator.serviceWorker.getRegistration().catch(() => undefined);
    if (registration) await registration.unregister().catch(() => undefined);
    const fresh = await withTimeout(
      navigator.serviceWorker.register("/sw.js", { scope: "/" }),
      10_000,
      null as ServiceWorkerRegistration | null,
    );
    return fresh !== null;
  } catch {
    return false;
  }
}

/** Resultado de procurar/ativar uma atualização da aplicação. */
export type UpdateOutcome = "updated" | "current" | "repaired" | "unsupported" | "error";

/** Procura uma atualização e ativa-a (recarrega a aplicação quando aplicável). */
export async function applyServiceWorkerUpdate(): Promise<UpdateOutcome> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return "unsupported";
  const registration = await withTimeout(
    navigator.serviceWorker.getRegistration(),
    5_000,
    undefined as ServiceWorkerRegistration | undefined,
  ).catch(() => undefined);
  if (!registration) {
    // Sem registo: tenta criar um (e o modo offline passa a estar disponível).
    const repaired = await repairOfflineMode();
    if (repaired) {
      window.setTimeout(() => window.location.reload(), 900);
      return "repaired";
    }
    return "unsupported";
  }
  const outcome = await withTimeout(
    registration.update().then(() => "ok" as const),
    8_000,
    "timeout" as const,
  );
  if (outcome === "timeout") {
    // Registo inválido ou browser sem resposta: reinstala do zero.
    const repaired = await repairOfflineMode();
    if (repaired) {
      window.setTimeout(() => window.location.reload(), 900);
      return "repaired";
    }
    return "error";
  }
  const waiting = registration.waiting;
  if (!waiting) return "current";
  waiting.postMessage("skip-waiting");
  window.setTimeout(() => window.location.reload(), 400);
  return "updated";
}

/** Limpa as caches offline (mantém as definições do utilizador). */
export async function clearOfflineCache(): Promise<number> {
  if (typeof caches === "undefined") return 0;
  try {
    const keys = await caches.keys();
    const targets = keys.filter((key) => key.startsWith("iq-os-") || key.startsWith("finance-llm-"));
    await Promise.all(targets.map((key) => caches.delete(key)));
    return targets.length;
  } catch {
    return 0;
  }
}

/** Comando para instalar a aplicação no Windows sem passar pela loja. */
export function windowsInstallerCommand(origin: string): string {
  return `powershell -ExecutionPolicy Bypass -File .\\instalar-iq-os.ps1 -Url ${origin}`;
}
