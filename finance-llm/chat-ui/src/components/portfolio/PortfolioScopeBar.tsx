import { Link } from "lucide-react";
import type { PortfolioScope } from "../../portfolioScope";

/**
 * Barra fina que mostra — e permite trocar — a carteira que alimenta o módulo.
 * Todos os cálculos usam a carteira escolhida aqui.
 */
export function PortfolioScopeBar({ scope, className = "" }: { scope: PortfolioScope; className?: string }) {
  const { portfolios, portfolioId, active, loading, select } = scope;

  if (loading) {
    return <div className={`text-xs text-slate-500 ${className}`}>A carregar carteiras…</div>;
  }

  if (portfolios.length === 0) {
    return (
      <div className={`flex items-center gap-2 text-xs text-slate-500 ${className}`}>
        <Link className="h-3.5 w-3.5" />
        Sem carteiras —{" "}
        <a href="/portfolio/manage" className="text-emerald-400 hover:underline">
          criar carteira
        </a>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className="text-xs uppercase tracking-wider text-slate-500">Carteira</span>
      <select
        value={portfolioId ?? ""}
        onChange={(event) => select(event.target.value || null)}
        className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        aria-label="Carteira em uso"
      >
        {portfolios.map((portfolio) => (
          <option key={portfolio.id} value={portfolio.id}>
            {portfolio.name} · {portfolio.currency}
          </option>
        ))}
      </select>
      {active && active.ticker_count === 0 && (
        <a href="/portfolio/manage" className="text-xs text-amber-400 hover:underline">
          adicionar tickers
        </a>
      )}
    </div>
  );
}
