/**
 * Instalação da aplicação IQ OS.
 *
 * Mostra o estado real da instalação (PWA instalada / a correr no browser /
 * instalável agora), o botão de instalação (usa o `beforeinstallprompt` do
 * Chromium), as instruções para os browsers que não têm esse evento, o estado do
 * `service worker` (modo offline + atualizações) e o instalador para Windows
 * (`public/instalar-iq-os.ps1`), que cria atalhos no Ambiente de Trabalho e no
 * Menu Iniciar a abrir a plataforma numa janela própria do Edge/Chrome.
 */
import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Download,
  HardDriveDownload,
  Loader2,
  MonitorDown,
  Package,
  RefreshCw,
  Smartphone,
  Trash2,
  WifiOff,
} from "lucide-react";
import {
  applyServiceWorkerUpdate,
  clearOfflineCache,
  installHint,
  serviceWorkerState,
  usePwaInstall,
  windowsInstallerCommand,
  type ServiceWorkerState,
  type UpdateOutcome,
} from "../pwa";

type ManifestInfo = { name: string; short_name: string; description: string; version: string };

const SW_LABELS: Record<ServiceWorkerState, string> = {
  unsupported: "Sem suporte neste browser",
  none: "Ainda não registado",
  installing: "A instalar…",
  waiting: "Atualização pronta",
  active: "Pronto para funcionar offline",
  broken: "Registo inválido — ative o modo offline",
};

/** Trava de segurança: nenhuma ação deste cartão pode deixar o botão preso. */
async function withLimit<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return Promise.race([
    promise.catch(() => fallback),
    new Promise<T>((resolve) => window.setTimeout(() => resolve(fallback), ms)),
  ]);
}

const UPDATE_NOTES: Record<string, string> = {
  updated: "Atualização aplicada — a recarregar a aplicação.",
  current: "A aplicação já está na versão mais recente em cache.",
  repaired: "Modo offline restabelecido — a recarregar a aplicação.",
  unsupported: "Este browser/contexto não suporta service workers (acontece em desenvolvimento ou em modo privado).",
  error: "Não foi possível atualizar agora. Tente novamente mais tarde.",
};

export function InstallAppSettings() {
  const { canInstall, standalone, installed, install, dismissed, dismiss, resetDismiss } = usePwaInstall();
  const [manifest, setManifest] = useState<ManifestInfo | null>(null);
  const [sw, setSw] = useState<{ state: ServiceWorkerState; version: string | null; controlled: boolean }>({
    state: "none",
    version: null,
    controlled: false,
  });
  const [busy, setBusy] = useState<"none" | "update" | "clear">("none");
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const hint = installHint();
  const origin = typeof window === "undefined" ? "http://localhost:5174/" : `${window.location.origin}/`;
  const command = windowsInstallerCommand(origin);

  const refresh = useCallback(async () => {
    const state = await withLimit(serviceWorkerState(), 6_000, { state: "broken" as ServiceWorkerState, version: null, scope: null, controlled: false });
    setSw({ state: state.state, version: state.version, controlled: state.controlled });
  }, []);

  useEffect(() => {
    void refresh();
    void (async () => {
      try {
        const response = await fetch("/manifest.webmanifest", { cache: "no-store" });
        if (!response.ok) return;
        const raw = (await response.json()) as Partial<ManifestInfo>;
        setManifest({
          name: raw.name ?? "IQ OS",
          short_name: raw.short_name ?? "IQ OS",
          description: raw.description ?? "",
          version: raw.version ?? "1.0.0",
        });
      } catch {
        // Sem manifest acessível: a secção continua a funcionar sem identidade.
      }
    })();
  }, [refresh]);

  const onUpdate = async () => {
    setBusy("update");
    const result = await withLimit<UpdateOutcome>(applyServiceWorkerUpdate(), 12_000, "error");
    setBusy("none");
    setNote(UPDATE_NOTES[result] ?? null);
    void refresh();
  };

  const onClear = async () => {
    setBusy("clear");
    const removed = await withLimit(clearOfflineCache(), 8_000, 0);
    setBusy("none");
    setNote(removed > 0 ? `${removed} cache(s) offline limpa(s).` : "Não havia caches offline para limpar.");
    void refresh();
  };

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setNote("Não foi possível copiar automaticamente — selecione o comando à mão.");
    }
  };

  const installedNow = standalone || installed;

  return (
    <section className="glass-card @container rounded-2xl p-5">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Package size={15} className="text-teal-300" />
          Aplicação IQ OS
        </h2>
        <span
          className={[
            "rounded-full border px-2.5 py-1 text-[10.5px] font-medium",
            installedNow
              ? "border-teal-300/30 bg-teal-400/12 text-teal-200"
              : canInstall
                ? "border-sky-300/30 bg-sky-400/12 text-sky-200"
                : "border-white/12 bg-white/6 text-zinc-300",
          ].join(" ")}
        >
          {installedNow ? "Instalada neste dispositivo" : canInstall ? "Pronta a instalar" : "A correr no browser"}
        </span>
      </header>

      <div className="flex flex-col gap-4 @3xl:flex-row">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-teal-300 via-teal-500 to-emerald-600">
            <img src="/icon-192.png" alt="Ícone do IQ OS" width={56} height={56} className="h-full w-full object-cover" />
          </span>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-zinc-100">{manifest?.name ?? "IQ OS"}</p>
            <p className="mt-0.5 line-clamp-2 text-[11.5px] text-zinc-400">
              {manifest?.description ?? "Plataforma de inteligência financeira com contratos públicos, empresas e mercados."}
            </p>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
              <span>versão {manifest?.version ?? "1.0.0"}</span>
              <span>origem {origin}</span>
              {sw.version ? <span>cache offline {sw.version}</span> : null}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-col gap-2">
          <button
            type="button"
            onClick={() => void install()}
            disabled={!canInstall || installedNow}
            className="flex h-10 items-center justify-center gap-2 rounded-xl bg-teal-400/20 px-4 text-[12.5px] font-medium text-teal-100 transition hover:bg-teal-400/30 disabled:opacity-40"
          >
            <Download size={14} />
            {installedNow ? "Já instalada" : "Instalar aplicação"}
          </button>
          <a
            href="/instalar-iq-os.ps1"
            download="instalar-iq-os.ps1"
            className="flex h-10 items-center justify-center gap-2 rounded-xl border border-white/12 px-4 text-[12.5px] text-zinc-200 transition hover:bg-white/8"
          >
            <MonitorDown size={14} />
            Instalador Windows
          </a>
        </div>
      </div>

      {!installedNow ? (
        <div className="mt-4 rounded-xl border border-white/10 bg-white/3 p-3">
          <p className="mb-1.5 flex items-center gap-2 text-[11.5px] font-medium text-zinc-200">
            {hint.browser.includes("iPhone") ? <Smartphone size={13} className="text-sky-300" /> : <Download size={13} className="text-sky-300" />}
            Como instalar em {hint.browser}
          </p>
          <ol className="ml-4 list-decimal space-y-0.5 text-[11.5px] text-zinc-400">
            {hint.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {canInstall ? (
            <p className="mt-2 text-[11px] text-teal-200">Este browser permite instalar agora — use o botão «Instalar aplicação».</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 flex items-center gap-2 rounded-xl border border-teal-300/25 bg-teal-400/8 px-3 py-2 text-[11.5px] text-teal-100">
          <CheckCircle2 size={13} /> A correr como aplicação instalada ({standalone ? "modo autónomo" : "sessão instalada"}).
        </p>
      )}

      <div className="mt-4 grid gap-3 @3xl:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-white/3 p-3">
          <p className="mb-1.5 flex items-center gap-2 text-[11.5px] font-medium text-zinc-200">
            <WifiOff size={13} className="text-emerald-300" /> Modo offline
          </p>
          <p className="text-[11.5px] text-zinc-400">
            {SW_LABELS[sw.state]}
            {sw.version ? ` · cache ${sw.version}` : ""}
            {sw.state === "active" && !sw.controlled ? " (assume controlo no próximo carregamento)" : ""}
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void onUpdate()}
              disabled={busy !== "none"}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-white/12 px-2.5 text-[11.5px] text-zinc-200 transition hover:bg-white/8 disabled:opacity-40"
            >
              {busy === "update" ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              {sw.state === "none" || sw.state === "broken" ? "Ativar modo offline" : "Procurar atualizações"}
            </button>
            <button
              type="button"
              onClick={() => void onClear()}
              disabled={busy !== "none"}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-white/12 px-2.5 text-[11.5px] text-zinc-300 transition hover:bg-white/8 disabled:opacity-40"
            >
              {busy === "clear" ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
              Limpar cache offline
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/3 p-3">
          <p className="mb-1.5 flex items-center gap-2 text-[11.5px] font-medium text-zinc-200">
            <HardDriveDownload size={13} className="text-amber-300" /> Atalho com janela própria (Windows)
          </p>
          <p className="text-[11.5px] text-zinc-400">
            Descarregue o instalador e execute-o para criar atalhos no Ambiente de Trabalho e no Menu Iniciar:
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-black/40 px-2 py-1.5 font-mono text-[10.5px] text-zinc-300">
              {command}
            </code>
            <button
              type="button"
              onClick={() => void onCopy()}
              title="Copiar comando"
              className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/12 text-zinc-300 transition hover:bg-white/8"
            >
              {copied ? <CheckCircle2 size={12} className="text-teal-300" /> : <Copy size={12} />}
            </button>
          </div>
          <p className="mt-2 text-[10.5px] text-zinc-500">
            Para remover: acrescente <code className="font-mono">-Uninstall</code>. A forma preferida é sempre a instalação pelo
            próprio browser (cria aplicação com ícone e arranque offline).
          </p>
        </div>
      </div>

      {note ? <p className="mt-3 text-[11.5px] text-zinc-300">{note}</p> : null}

      {dismissed ? (
        <button type="button" onClick={resetDismiss} className="mt-3 text-[11px] text-teal-300 hover:underline">
          Voltar a mostrar o convite de instalação ao abrir a plataforma
        </button>
      ) : (
        <button type="button" onClick={dismiss} className="mt-3 text-[11px] text-zinc-500 hover:text-zinc-300">
          Não mostrar o convite de instalação
        </button>
      )}
    </section>
  );
}

export default InstallAppSettings;
