import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getPortfolioIntraday, type IntradayFeed, type IntradayMode } from "../../portfolioApi";

type Props = { ticker: string; portfolioId?: string; prepost: boolean };
const time = (value: string) => new Date(value).toLocaleTimeString("pt-PT", { timeZone: "UTC", hour12: false });

export function IntradayPoints({ ticker, portfolioId, prepost }: Props) {
  const [mode, setMode] = useState<IntradayMode>("bars");
  const [enabled, setEnabled] = useState(true);
  const [feed, setFeed] = useState<IntradayFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let success = false;
      try {
        const result = await getPortfolioIntraday({ ticker, portfolio_id: portfolioId, prepost, mode }, controller.signal);
        if (!controller.signal.aborted) { setFeed(result); setError(null); success = true; }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (!controller.signal.aborted && enabled && (mode !== "provider" || success)) timer = setTimeout(poll, 15000);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [ticker, portfolioId, prepost, mode, enabled, revision]);
  return (
    <section className="space-y-3 rounded-lg border border-cyan-900 bg-slate-900/40 p-4" aria-label="Pontos intradiários acompanhados">
      <h2 className="font-semibold text-cyan-200">Pontos intradiários · {ticker}</h2>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Fonte dos pontos
          <select aria-label="Modo dos pontos intradiários" value={mode} onChange={(event) => {
            const value = event.target.value;
            if (value === "bars" || value === "samples" || value === "provider") { setMode(value); setFeed(null); setError(null); }
          }} className="ml-2 rounded bg-slate-800 p-2">
            <option value="bars">Barras reais de 1 minuto · Yahoo</option>
            <option value="samples">Uma amostra por consulta · Yahoo</option>
            <option value="provider">Feed externo · requer configuração</option>
          </select>
        </label>
        <label><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Consultar a cada 15 s</label>
        <button className="rounded bg-cyan-900 px-3 py-2" onClick={() => setRevision((value) => value + 1)}>Consultar pontos agora</button>
      </div>
      <p className="text-xs text-slate-400">Pontos efetivamente recebidos, não simulados. A fonte pode ter atraso; polling não é streaming tick-a-tick. Barras usam a hora original do mercado; amostras usam a hora da consulta e podem repetir o mesmo preço. Estes pontos não pontuam previsões de outras escalas. O acompanhamento pára ao sair da página.</p>
      {error && <p role="alert" className="text-rose-300">{error}{feed ? " Últimos dados recebidos mantidos; atualização falhou." : ""}</p>}
      {!feed && !error && <p role="status">A obter pontos intradiários…</p>}
      {feed && <>
        <p className="text-sm text-cyan-300">{feed.points.length} pontos · {feed.source} · Consulta {time(feed.fetched_at)} UTC · Observação {time(feed.source_date)} UTC · Idade {feed.age_seconds} s</p>
        <div className="h-72" aria-label="Gráfico de pontos intradiários">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={feed.points} margin={{ left: 10, right: 15, top: 10 }}>
              <CartesianGrid stroke="#1e293b" />
              <XAxis dataKey="date" tickFormatter={time} minTickGap={45} tick={{ fontSize: 10 }} />
              <YAxis domain={["auto", "auto"]} width={65} tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(value) => `${new Date(String(value)).toLocaleString("pt-PT", { timeZone: "UTC" })} UTC`} formatter={(value) => typeof value === "number" ? value.toFixed(4) : String(value)} contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }} />
              <Line dataKey="value" name={`Preço real ${feed.currency ?? ""}`} stroke="#22d3ee" strokeWidth={2} dot={{ r: 3, fill: "#22d3ee" }} activeDot={{ r: 6 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <details><summary className="cursor-pointer text-sm text-cyan-300">Ver pontos recebidos ({feed.points.length})</summary>
          <div className="max-h-64 overflow-auto"><table className="w-full text-left text-xs" aria-label="Pontos intradiários recebidos">
            <thead><tr>{["Ponto (UTC)", "Preço", "Barra/fonte (UTC)", "Estado"].map((heading) => <th className="p-2" key={heading}>{heading}</th>)}</tr></thead>
            <tbody>{[...feed.points].reverse().map((point) => <tr key={point.date} className="border-t border-slate-800"><td className="p-2">{new Date(point.date).toLocaleString("pt-PT", { timeZone: "UTC" })}</td><td className="p-2">{point.value.toFixed(4)}</td><td className="p-2">{new Date(point.source_date).toLocaleString("pt-PT", { timeZone: "UTC" })}</td><td className="p-2">{mode === "bars" ? point.completed ? "Concluída" : "Em formação" : mode === "samples" ? "Amostra de consulta" : "Observação do fornecedor"}</td></tr>)}</tbody>
          </table></div>
        </details>
        <p className="text-xs text-slate-500">{feed.notice} Até 390 pontos recentes recuperados do índice {feed.index}; os restantes continuam guardados.</p>
      </>}
    </section>
  );
}
