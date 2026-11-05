import { Loader2 } from "lucide-react";

export function PortfolioLoading() {
  return (
    <div className="flex h-96 items-center justify-center rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex flex-col items-center gap-3 text-slate-400">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-400" />
        <span className="text-sm">A carregar dados reais do Yahoo Finance…</span>
      </div>
    </div>
  );
}
