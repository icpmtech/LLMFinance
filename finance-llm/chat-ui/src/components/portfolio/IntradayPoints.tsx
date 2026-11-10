import { useEffect, useState } from "react";
import { CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getPortfolioIntraday, type IntradayAction, type IntradayFeed, type IntradayMode } from "../../portfolioApi";

type Props = { ticker: string; portfolioId?: string; prepost: boolean };
const time = (value: string) => new Date(value).toLocaleTimeString("pt-PT", { timeZone: "UTC", hour12: false });
const SIGNALS: Record<IntradayAction, { label: string; color: string }> = {
  buy: { label: "BUY", color: "#22c55e" }, sell: { label: "SELL", color: "#f43f5e" },
  hold: { label: "HOLD", color: "#cbd5e1" }, strong_buy: { label: "STRONG BUY", color: "#10b981" },
  strong_sell: { label: "STRONG SELL", color: "#fb7185" }, wait: { label: "WAIT", color: "#fbbf24" },
};
const metric = (value?: number | null) => value == null ? "—" : value.toFixed(3);

export function IntradayPoints({ ticker, portfolioId, prepost }: Props) {
  const [mode, setMode] = useState<IntradayMode>("bars");
  const [enabled, setEnabled] = useState(true);
  const [feed, setFeed] = useState<IntradayFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [showLabels, setShowLabels] = useState(true);
  const [window, setWindow] = useState(30);
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
  const chartPoints = (window ? feed?.points.slice(-window) : feed?.points)?.map((point) => ({
    ...point, actionLabel: SIGNALS[point.signal?.action ?? "wait"].label,
  })) ?? [];
  const latest = feed?.points.at(-1)?.signal;
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
        <div className="flex flex-wrap gap-3 text-xs" aria-label="Legenda dos sinais intradiários">{Object.entries(SIGNALS).map(([key, signal]) => <span key={key} style={{ color: signal.color }}>● {signal.label}</span>)}</div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label><input type="checkbox" checked={showLabels} onChange={(event) => setShowLabels(event.target.checked)} /> Mostrar BUY/SELL/HOLD em cada ponto</label>
          <label>Pontos visíveis <select aria-label="Janela de pontos intradiários" value={window} onChange={(event) => setWindow(Number(event.target.value))} className="rounded bg-slate-800 p-2">
            {[15, 30, 60, 0].map((value) => <option value={value} key={value}>{value || "Todos"}</option>)}
          </select></label>
        </div>
        {latest && <p className="text-sm" style={{ color: SIGNALS[latest.action].color }}>
          Último sinal: <strong>{SIGNALS[latest.action].label}</strong> · {latest.provisional ? "Provisório" : "Barra concluída"} · RSI {metric(latest.rsi14)} · MACD hist. {metric(latest.macd_histogram)} · Pontuação {latest.score ?? "—"}
          {latest.alerts.map((alert) => ` · ${alert === "overbought" ? "Sobrecompra" : "Sobrevenda"}`)}
        </p>}
        {latest && <p className="text-xs text-slate-400">{latest.reasons.join("; ")}</p>}
        <div className="h-72" aria-label="Gráfico de pontos intradiários">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartPoints} margin={{ left: 10, right: 35, top: 55 }}>
              <CartesianGrid stroke="#1e293b" />
              <XAxis dataKey="date" tickFormatter={time} minTickGap={45} tick={{ fontSize: 10 }} />
              <YAxis domain={["auto", "auto"]} width={65} tick={{ fontSize: 10 }} />
              <Tooltip content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const point = chartPoints.find((entry) => entry.date === String(label));
                if (!point) return null;
                const signal = point.signal;
                return <div className="max-w-72 rounded border border-slate-700 bg-slate-900 p-3 text-xs">
                  <p>{time(point.date)} UTC · {point.value.toFixed(4)} {feed.currency}</p>
                  <p style={{ color: SIGNALS[signal?.action ?? "wait"].color }}>{point.actionLabel} · {signal?.provisional ? "Provisório" : signal ? "Concluído" : "Sem análise guardada"}</p>
                  <p>RSI {metric(signal?.rsi14)} · MACD {metric(signal?.macd)} / {metric(signal?.macd_signal)}</p>
                  <p>SMA20 {metric(signal?.sma20)} / SMA50 {metric(signal?.sma50)} · Pontuação {signal?.score ?? "—"}</p>
                  <p>{signal?.reasons.join("; ")}</p>
                </div>;
              }} />
              <Line dataKey="value" name={`Preço real ${feed.currency ?? ""}`} stroke="#22d3ee" strokeWidth={2}
                dot={(props) => {
                  const point = chartPoints[props.index];
                  const action = point?.signal?.action ?? "wait";
                  return <circle key={point?.date ?? props.index} cx={props.cx} cy={props.cy} r={action.startsWith("strong") ? 6 : 4} fill={SIGNALS[action].color} stroke="#0f172a" data-action={action} />;
                }} activeDot={{ r: 7 }} isAnimationActive={false}>
                {showLabels && <LabelList dataKey="actionLabel" position="top" angle={-45} offset={14} fill="#e2e8f0" fontSize={9} />}
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
        <details><summary className="cursor-pointer text-sm text-cyan-300">Ver pontos recebidos ({feed.points.length})</summary>
          <div className="max-h-64 overflow-auto"><table className="w-full text-left text-xs" aria-label="Pontos intradiários recebidos">
            <thead><tr>{["Ponto (UTC)", "Preço", "Barra/fonte (UTC)", "Estado", "Sinal", "RSI14", "MACD / sinal", "SMA20 / SMA50", "Pontuação", "Alertas e motivos"].map((heading) => <th className="p-2" key={heading}>{heading}</th>)}</tr></thead>
            <tbody>{[...feed.points].reverse().map((point) => <tr key={point.date} className="border-t border-slate-800">
              <td className="p-2">{new Date(point.date).toLocaleString("pt-PT", { timeZone: "UTC" })}</td><td className="p-2">{point.value.toFixed(4)}</td><td className="p-2">{new Date(point.source_date).toLocaleString("pt-PT", { timeZone: "UTC" })}</td>
              <td className="p-2">{point.signal?.provisional ? "Provisório" : point.completed ? "Concluído" : "Observação"}</td>
              <td className="whitespace-nowrap p-2" style={{ color: SIGNALS[point.signal?.action ?? "wait"].color }}>{SIGNALS[point.signal?.action ?? "wait"].label}</td>
              <td className="p-2">{metric(point.signal?.rsi14)}</td><td className="p-2">{metric(point.signal?.macd)} / {metric(point.signal?.macd_signal)}</td>
              <td className="p-2">{metric(point.signal?.sma20)} / {metric(point.signal?.sma50)}</td><td className="p-2">{point.signal?.score ?? "—"}</td>
              <td className="min-w-60 p-2">{point.signal?.alerts.map((alert) => alert === "overbought" ? "Sobrecompra" : "Sobrevenda").join(", ")} {point.signal?.reasons.join("; ") ?? "Sem análise guardada para este ponto antigo."}</td>
            </tr>)}</tbody>
          </table></div>
        </details>
        <p className="text-xs text-slate-500">{feed.notice} Até 390 pontos recentes recuperados do índice {feed.index}; os restantes continuam guardados.</p>
        <p className="text-xs text-slate-400">Sinais técnicos, sem ARIMA: RSI≤30 soma +1, RSI≥70 soma −1; MACD acima/abaixo do sinal e SMA20 acima/abaixo da SMA50 somam +1/−1. ±3: STRONG BUY/SELL; ±2: BUY/SELL; senão HOLD. WAIT: menos de 50 observações distintas ou fonte com mais de 180 s. “Strong” significa confluência, não probabilidade de lucro. Indicadores das amostras Yahoo usam barras de 1 minuto, não repetições da consulta; no feed externo usam observações distintas do fornecedor. Sinais provisórios podem mudar; sinais concluídos ficam guardados. Não envia ordens reais nem constitui aconselhamento financeiro.</p>
      </>}
    </section>
  );
}
