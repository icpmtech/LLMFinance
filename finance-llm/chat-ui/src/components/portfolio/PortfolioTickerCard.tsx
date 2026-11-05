import type { PortfolioTicker } from "../../portfolioApi";

interface PortfolioTickerCardProps {
  ticker: PortfolioTicker;
  weight: number;
  selected: boolean;
  onClick: () => void;
}

export function PortfolioTickerCard({ ticker, weight, selected, onClick }: PortfolioTickerCardProps) {
  const isUp = (ticker.change_pct ?? 0) >= 0;
  return (
    <button
      onClick={onClick}
      className={[
        "w-full rounded-lg border p-3 text-left transition",
        selected
          ? "border-emerald-500/40 bg-emerald-900/10"
          : "border-slate-800 bg-slate-900/40 hover:border-slate-700",
      ].join(" ")}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white">{ticker.ticker}</span>
            <span className="text-xs text-slate-500">{weight > 0 ? `${(weight * 100).toFixed(1)}%` : ""}</span>
          </div>
          <div className="text-xs text-slate-400 truncate max-w-[160px]">{ticker.name}</div>
        </div>
        <div className="text-right">
          <div className="font-medium text-white">
            {ticker.price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? "-"}
          </div>
          <div className={`text-xs font-medium ${isUp ? "text-emerald-400" : "text-rose-400"}`}>
            {ticker.change_pct !== undefined
              ? `${isUp ? "+" : ""}${ticker.change_pct.toFixed(2)}%`
              : ticker.error
                ? "Erro"
                : "-"}
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
        {ticker.sector && <span className="rounded bg-slate-800 px-1.5 py-0.5">{ticker.sector}</span>}
        {ticker.exchange && <span className="rounded bg-slate-800 px-1.5 py-0.5">{ticker.exchange}</span>}
      </div>
    </button>
  );
}
