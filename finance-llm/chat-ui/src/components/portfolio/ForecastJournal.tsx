import { useEffect, useState } from "react";
import { getPortfolioForecastHistory, type ForecastInterval, type ForecastJournal as Journal } from "../../portfolioApi";

type Props = {
  ticker: string; interval: ForecastInterval; prepost: boolean; portfolioId?: string;
  persistence?: Journal | { error: string }; currency?: string;
};
const date = (value: string) => new Date(value).toLocaleString("pt-PT", { timeZone: "UTC" });
const number = (value?: number) => value === undefined ? "—" : value.toFixed(3);
const outcome = (value?: boolean) => value === undefined ? "Pendente" : value ? "Acertou" : "Falhou";

export function ForecastJournal({ ticker, interval, prepost, portfolioId, persistence, currency }: Props) {
  const [kind, setKind] = useState<"forecast" | "backtest" | "signal">("forecast");
  const [offset, setOffset] = useState(0);
  const [cursors, setCursors] = useState<Record<number, string>>({});
  const [result, setResult] = useState<Journal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initial = persistence && !("error" in persistence) ? persistence : null;
  const useInitial = kind === "forecast" && offset === 0;
  useEffect(() => {
    if (useInitial) return;
    const controller = new AbortController();
    void getPortfolioForecastHistory({
      ticker, interval, prepost, portfolio_id: portfolioId, kind, offset, cursor: cursors[offset],
    }, controller.signal).then((journal) => {
      if (!controller.signal.aborted) { setResult(journal); setError(null); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => controller.abort();
  }, [ticker, interval, prepost, portfolioId, kind, offset, persistence, useInitial, cursors]);
  const journal = useInitial ? initial : result;
  const loading = !useInitial && result === null && error === null;
  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4" aria-label="Simulações guardadas no Elasticsearch">
      <h2 className="font-semibold text-white">Simulações guardadas · {ticker} · comparação com a série real</h2>
      {persistence && "error" in persistence && <p role="alert" className="text-rose-300">{persistence.error}</p>}
      <p className="text-xs leading-5 text-slate-400">Cada ponto conserva a previsão, parâmetros e hora do registo originais. A avaliação usa apenas barras concluídas com a mesma marca temporal. Direção: subida/descida/estável (±0,20% em relação ao preço de referência). Preço: acertou se o erro absoluto for ≤1% do real. São critérios independentes, não rentabilidade de uma ordem. Backtests retrospetivos não contam como acertos ao vivo.</p>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Registos
          <select aria-label="Tipo de simulações guardadas" value={kind} onChange={(event) => {
            setKind(event.target.value === "backtest" ? "backtest" : event.target.value === "signal" ? "signal" : "forecast"); setOffset(0); setCursors({}); setResult(null); setError(null);
          }} className="ml-2 rounded bg-slate-800 p-2">
            <option value="forecast">Previsões registadas</option>
            <option value="backtest">Backtest histórico · separado</option>
            <option value="signal">Sinais técnicos e estado simulado</option>
          </select>
        </label>
        {journal && <span className="text-slate-400">{journal.total} pontos · {journal.pending} pendentes · {journal.evaluated} avaliados · {journal.not_eligible} sem elegibilidade temporal</span>}
      </div>
      {error && <p role="alert" className="text-rose-300">{error}</p>}
      {loading && !useInitial ? <p role="status">A ler Elasticsearch…</p> : journal && !error && <>
        <p className="text-sm text-cyan-300">Direção: {journal.direction_hits}/{journal.evaluated} acertos · Preço (≤1%): {journal.price_hits}/{journal.evaluated} acertos{journal.evaluated > 0 ? ` · ${((journal.direction_hits / journal.evaluated) * 100).toFixed(1)}% / ${((journal.price_hits / journal.evaluated) * 100).toFixed(1)}%` : ""}.</p>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-left text-xs" aria-label="Avaliação persistente por ponto">
            <thead><tr>{["Registado (UTC)", "Barra alvo (UTC)", "Referência", "Previsão original", "Real concluído", "Erro %", "Direção", "Preço ≤1%", "Estado", "Sinal", "Parâmetros e ponto original"].map((heading) => <th key={heading} className="whitespace-nowrap p-2">{heading}</th>)}</tr></thead>
            <tbody>{journal.items.map((point) => <tr key={point.id} className="border-t border-slate-800">
              <td className="whitespace-nowrap p-2">{date(point.recorded_at)}</td><td className="whitespace-nowrap p-2">{date(point.target_date)}</td>
              <td className="p-2">{number(point.reference_price)}</td><td className="p-2">{number(point.predicted)} {currency}</td><td className="p-2">{number(point.actual)}</td><td className="p-2">{number(point.error_pct)}</td>
              <td className={`p-2 ${point.direction_hit === undefined ? "" : point.direction_hit ? "text-emerald-300" : "text-rose-300"}`}>{outcome(point.direction_hit)}</td>
              <td className={`p-2 ${point.price_hit === undefined ? "" : point.price_hit ? "text-emerald-300" : "text-rose-300"}`}>{outcome(point.price_hit)}</td>
              <td className="p-2">{point.status === "evaluated" ? "Avaliado" : point.status === "not_eligible" ? "Alvo já iniciado ao registar" : "Aguarda barra concluída"}</td>
              <td className="p-2">{point.signal ? ({ buy: "Comprar", sell: "Vender", hold: "Manter" }[point.signal.action]) : "—"}</td>
              <td className="p-2"><details><summary className="cursor-pointer text-violet-300">Ver snapshot</summary><pre className="max-w-80 overflow-auto p-2 text-xs">{JSON.stringify(point.config, null, 2)}</pre></details></td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 100)); setResult(null); setError(null); }} className="rounded bg-slate-800 px-3 py-2 disabled:opacity-40">Página anterior</button>
          <span>{offset + (journal.total ? 1 : 0)}–{Math.min(offset + journal.items.length, journal.total)} / {journal.total}</span>
          <button disabled={journal.next_offset === null} onClick={() => {
            const next = journal.next_offset;
            const cursor = journal.next_cursor;
            if (next !== null && cursor) { setCursors((current) => ({ ...current, [next]: cursor })); setOffset(next); setResult(null); setError(null); }
          }} className="rounded bg-slate-800 px-3 py-2 disabled:opacity-40">Página seguinte</button>
        </div>
      </>}
      <p className="text-xs text-slate-500">Índice: {journal?.index ?? "finance_portfolio_forecast_points"}. Dados isolados por conta, carteira, ativo, escala e pré/pós-mercado. Atualiza ao calcular/acompanhar a página, não com o browser fechado. Previsões com alvo já iniciado ficam guardadas mas não são pontuadas ao vivo. Datas aproximadas sem barra real correspondente permanecem pendentes. Cada revisão é um snapshot separado; pontos idênticos não são duplicados.</p>
    </section>
  );
}
