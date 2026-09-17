/**
 * Convite para instalar a aplicação IQ OS.
 *
 * Aparece uma vez (por dispositivo) quando o browser permite instalar e a
 * aplicação ainda não está instalada. Fica discreto no canto inferior esquerdo,
 * acima do dock, e pode ser dispensado — a opção volta a estar sempre em
 * Definições → Aplicação IQ OS.
 */
import { Download, Package, X } from "lucide-react";
import { usePwaInstall } from "../pwa";

export function InstallBanner() {
  const { canInstall, standalone, installed, install, dismissed, dismiss } = usePwaInstall();

  if (!canInstall || standalone || installed || dismissed) return null;

  return (
    <div className="pointer-events-auto fixed bottom-28 left-4 z-40 w-[300px] rounded-2xl border border-teal-300/25 bg-[#101519]/95 p-3.5 shadow-2xl shadow-black/40 backdrop-blur-xl">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-teal-300 via-teal-500 to-emerald-600 text-[#04120e]">
          <Package size={18} />
        </span>
        <div className="min-w-0">
          <p className="text-[12.5px] font-semibold text-zinc-100">Instalar o IQ OS</p>
          <p className="mt-0.5 text-[11.5px] leading-snug text-zinc-400">
            Fica com ícone próprio, janela sem barra do browser e arranque offline.
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          title="Agora não"
          className="grid h-6 w-6 shrink-0 place-items-center rounded-lg text-zinc-500 transition hover:bg-white/8 hover:text-zinc-200"
        >
          <X size={12} />
        </button>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void install()}
          className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg bg-teal-400/20 text-[12px] font-medium text-teal-100 transition hover:bg-teal-400/30"
        >
          <Download size={13} /> Instalar
        </button>
        <button
          type="button"
          onClick={dismiss}
          className="h-8 shrink-0 rounded-lg border border-white/12 px-3 text-[12px] text-zinc-300 transition hover:bg-white/8"
        >
          Agora não
        </button>
      </div>
    </div>
  );
}

export default InstallBanner;
