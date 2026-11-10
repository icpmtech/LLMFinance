import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Sparkles, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
  ReferenceLine,
  Legend,
} from "recharts";
import { getPortfolioForecast, type PortfolioForecastResponse, type ForecastPoint, type ForecastSeries, type ForecastInterval, type TradingSignal } from "../portfolioApi";
import { usePortfolioScope } from "../portfolioScope";
import { PortfolioScopeBar } from "../components/portfolio/PortfolioScopeBar";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";
import { PortfolioNewsStrip } from "../components/portfolio/PortfolioNewsStrip";
import { ForecastJournal } from "../components/portfolio/ForecastJournal";
import { IntradayPoints } from "../components/portfolio/IntradayPoints";

type TickerSettings = {
  mode: "auto" | "manual"; order: number[]; backtestDays: number;
  interval: ForecastInterval; trainWindow: number; steps: number; prepost: boolean;
};
type RealPrice = { date: string; value: number };
type ChartPoint = {
  date: string; history?: number; actual?: number; prediction?: number; lower?: number; upper?: number;
  trend?: number; recommended?: number; sma20?: number; sma50?: number;
  buy?: number; sell?: number; hold?: number; realPrice?: number;
  storedForecast?: number;
};
const DEFAULT_SETTINGS: TickerSettings = {
  mode: "auto", order: [1, 0, 1], backtestDays: 20, interval: "1d", trainWindow: 252, steps: 30, prepost: true,
};
const INTERVAL_LABELS: Record<ForecastInterval, string> = { "1m": "minutos", "1h": "horas", "1d": "dias", "1wk": "semanas", "1mo": "meses" };
const MODEL_LABELS: Record<string, string> = { arima: "ARIMA", last_close: "Último preço", trend: "Tendência recente" };
const ACTION_LABELS = { buy: "Comprar", sell: "Vender", hold: "Manter", none: "Sem operação" };

function forecastRequest(settings: TickerSettings) {
  return {
    future_days: settings.steps, arima_mode: settings.mode,
    arima_p: settings.order[0], arima_d: settings.order[1], arima_q: settings.order[2],
    backtest_days: settings.backtestDays, interval: settings.interval, train_window: settings.trainWindow,
    prepost: settings.prepost, include_news: false,
  };
}

export function PortfolioForecastPage() {
  const scope = usePortfolioScope();
  const portfolioId = scope.portfolioId;

  const [data, setData] = useState<PortfolioForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartView, setChartView] = useState("both");
  const [historyWindow, setHistoryWindow] = useState(90);
  const [showBands, setShowBands] = useState(true);
  const [showSignals, setShowSignals] = useState(true);
  const [showAverages, setShowAverages] = useState(false);
  const [showRealPrice, setShowRealPrice] = useState(true);
  const [showStoredForecast, setShowStoredForecast] = useState(true);
  const [realPrices, setRealPrices] = useState<RealPrice[]>([]);
  const [drafts, setDrafts] = useState<Record<string, TickerSettings>>({});
  const [applied, setApplied] = useState<Record<string, TickerSettings>>({});
  const settingsKey = `${portfolioId ?? "default"}:${selectedTicker ?? ""}`;
  const settings = drafts[settingsKey] ?? applied[settingsKey] ?? DEFAULT_SETTINGS;
  const updateSettings = (change: Partial<TickerSettings>) =>
    setDrafts((previous) => ({ ...previous, [settingsKey]: { ...settings, ...change } }));
  const [refreshing, setRefreshing] = useState(false);
  const [live, setLive] = useState(false);
  const [liveMessage, setLiveMessage] = useState<string | null>(null);
  const [showTrend, setShowTrend] = useState(true);
  const [showRecommended, setShowRecommended] = useState(true);
  const requestRef = useRef<AbortController | null>(null);
  const [simulationDay, setSimulationDay] = useState(0);
  const [playing, setPlaying] = useState(false);

  const load = useCallback(async (signal: AbortSignal) => {
    if (scope.loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getPortfolioForecast({
        ...forecastRequest(DEFAULT_SETTINGS), include_news: true,
        use_sentiment: false, portfolio_id: portfolioId ?? undefined,
      }, signal);
      if (signal.aborted) return;
      setData(result);
      setRealPrices([]);
      setSimulationDay(0);
      setPlaying(false);
      setSelectedTicker((prev) =>
        result.forecasts.some((forecast) => forecast.ticker === prev)
          ? prev
          : (result.forecasts[0]?.ticker ?? null),
      );
    } catch (e) {
      if (!signal.aborted) setError(e instanceof Error ? e.message : "Erro ao carregar previsões");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [portfolioId, scope.loading]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const selected = data?.forecasts.find((f) => f.ticker === selectedTicker);
  const selectedRef = useRef(selected);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  const refreshTicker = useCallback(async (config: TickerSettings, save: boolean) => {
    if (!selectedTicker) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setRefreshing(true);
    setLiveMessage(null);
    try {
      const previous = selectedRef.current;
      const result = await getPortfolioForecast({
        ...forecastRequest(config), tickers: [selectedTicker], portfolio_id: portfolioId ?? undefined,
      }, controller.signal);
      if (controller.signal.aborted) return;
      const forecast = result.forecasts.find((entry) => entry.ticker === selectedTicker);
      if (!forecast) throw new Error("A API não devolveu o ativo selecionado.");
      if (forecast.error) throw new Error(forecast.error);
      setData((current) => current ? { ...current, as_of: result.as_of, forecasts: current.forecasts.map((entry) => entry.ticker === forecast.ticker ? forecast : entry) } : current);
      if (save) {
        setApplied((current) => ({ ...current, [settingsKey]: config }));
      }
      const observed = forecast.series.findLast((point) => isHistoricalSeries(point) && typeof point.value === "number");
      const previousObserved = previous?.series.findLast((point) => isHistoricalSeries(point) && typeof point.value === "number");
      setRealPrices((current) => {
        const points = new Map((save ? [] : current).map((point) => [point.date, point]));
        for (const point of [save ? undefined : previousObserved, observed]) {
          if (point && typeof point.value === "number") points.set(point.date, { date: point.date, value: point.value });
        }
        return [...points.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-100);
      });
      const changed = previous?.series.at(-1)?.value !== forecast.series.at(-1)?.value
        || previous?.series.at(-1)?.date !== forecast.series.at(-1)?.date;
      setLiveMessage(changed ? "Novo preço/barra recebido; projeção recalculada." : "Fonte consultada: sem novos preços. Projeção atualizada com os dados disponíveis.");
    } catch (reason) {
      if (!controller.signal.aborted) setLiveMessage(`Erro ao atualizar: ${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      if (requestRef.current === controller) setRefreshing(false);
    }
  }, [selectedTicker, settingsKey, portfolioId]);
  useEffect(() => {
    if (!live || !selectedTicker || loading) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await refreshTicker(applied[settingsKey] ?? DEFAULT_SETTINGS, false);
      if (!cancelled) timer = setTimeout(poll, 60000);
    };
    timer = setTimeout(poll, 60000);
    return () => { cancelled = true; clearTimeout(timer); requestRef.current?.abort(); };
  }, [live, selectedTicker, loading, applied, settingsKey, refreshTicker]);
  useEffect(() => () => requestRef.current?.abort(), [settingsKey]);
  const simulationRows = chartView === "backtest" ? selected?.backtest ?? [] : selected?.forecast ?? [];
  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => {
      if (simulationDay >= simulationRows.length) setPlaying(false);
      else setSimulationDay((day) => day + 1);
    }, 750);
    return () => clearTimeout(timer);
  }, [playing, simulationRows.length, simulationDay]);
  const resetSimulation = () => {
    setPlaying(false);
    setSimulationDay(0);
  };
  const selectTicker = (ticker: string) => {
    requestRef.current?.abort();
    resetSimulation();
    setRefreshing(false);
    setLiveMessage(null);
    setLive(false);
    setRealPrices([]);
    setSelectedTicker(ticker);
  };

  const completeChartData = buildChartData(selected, chartView, historyWindow, showRealPrice, realPrices);
  const chartData = simulationDay === 0 || chartView === "history"
    ? completeChartData
    : completeChartData.filter((point) => point.date <= (simulationRows[simulationDay - 1]?.date ?? ""));
  const lastHistoricalPrice = selected?.series.findLast(
    (point) => isHistoricalSeries(point) && typeof point.value === "number",
  )?.value;
  const finalForecast = selected?.forecast.at(-1);
  const forecastChange = calculateChange(lastHistoricalPrice, finalForecast?.price);

  return (
    <div className="min-h-screen bg-[#0b0d10] text-slate-200 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-violet-500/10 p-2">
              <Sparkles className="h-6 w-6 text-violet-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Antecipar o futuro</h1>
              <p className="text-sm text-slate-400">Previsões ARIMA de preço com bandas de confiança e notícias de contexto.</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              aria-label="Horizonte da projeção"
              value={settings.steps}
              onChange={(e) => updateSettings({ steps: Number(e.target.value) })}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
            >
              {[7, 14, 30, 60, 90].map((d) => (
                <option key={d} value={d}>{d} observações · {INTERVAL_LABELS[settings.interval]}</option>
              ))}
            </select>
            <PortfolioScopeBar scope={scope} />
            <button
              onClick={() => void refreshTicker(applied[settingsKey] ?? DEFAULT_SETTINGS, false)}
              disabled={loading || refreshing || !selectedTicker}
              className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading || refreshing ? "animate-spin" : ""}`} />
              Atualizar
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <p className="w-full font-semibold text-violet-300">Configuração individual · {selectedTicker ?? "A carregar"} · guardada nesta página por ativo</p>
          <label className="text-sm text-slate-300">Escala
            <select aria-label="Escala da série" value={settings.interval} onChange={(event) => {
              const interval = event.target.value;
              if (interval === "1m" || interval === "1h" || interval === "1d" || interval === "1wk" || interval === "1mo") updateSettings({ interval });
            }} disabled={loading || refreshing} className="ml-2 rounded-md bg-slate-800 p-2">
              <option value="1m">Minuto · intradiário real</option><option value="1h">Horária · intradiário real</option><option value="1d">Diária</option><option value="1wk">Semanal</option><option value="1mo">Mensal</option>
            </select>
          </label>
          <label className="text-sm text-slate-300">Janela de treino
            <select aria-label="Janela de treino" value={settings.trainWindow} onChange={(event) => updateSettings({trainWindow:Number(event.target.value)})} disabled={loading || refreshing} className="ml-2 rounded-md bg-slate-800 p-2">
              {[60,120,252,500,1000].map((value) => <option key={value} value={value}>{value} observações</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-300">Ajuste ARIMA
            <select aria-label="Ajuste ARIMA" value={settings.mode} onChange={(event) => updateSettings({mode:event.target.value === "manual" ? "manual" : "auto"})} className="ml-2 rounded-md bg-slate-800 p-2" disabled={loading || refreshing}>
              <option value="auto">Automático · validação temporal</option>
              <option value="manual">Manual · parâmetros p,d,q</option>
            </select>
          </label>
          {settings.mode === "manual" && ["p", "d", "q"].map((label, index) => (
            <label key={label} className="text-sm text-slate-300">{label}
              <select aria-label={`ARIMA ${label}`} value={settings.order[index]} onChange={(event) => updateSettings({order:settings.order.map((value,i) => i === index ? Number(event.target.value) : value)})} disabled={loading || refreshing} className="ml-2 rounded-md bg-slate-800 p-2">
                {(index === 1 ? [0, 1] : [0, 1, 2, 3]).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          ))}
          <label className="text-sm text-slate-300">Backtest por observação
            <select aria-label="Observações de backtest" value={settings.backtestDays} onChange={(event) => updateSettings({backtestDays:Number(event.target.value)})} disabled={loading || refreshing} className="ml-2 rounded-md bg-slate-800 p-2">
              {[10, 20, 40, 60].map((value) => <option key={value} value={value}>{value} observações</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-300"><input type="checkbox" checked={settings.prepost} onChange={(event) => updateSettings({prepost:event.target.checked})} disabled={loading || refreshing || !["1m", "1h"].includes(settings.interval)} /> Incluir pré/pós-mercado</label>
          <button onClick={() => { resetSimulation(); void refreshTicker(settings, true); }} disabled={loading || refreshing || !selectedTicker} className="rounded-md bg-violet-600 px-3 py-2 text-sm text-white disabled:opacity-50">{refreshing ? "A calcular…" : "Aplicar configuração"}</button>
          <label className="text-sm text-slate-300"><input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} /> Acompanhar preços · consultar a cada 60 s</label>
          <p className="w-full text-xs text-slate-400">Cada ativo mantém a sua escala e parâmetros durante esta sessão da página. Aplicar recalcula só o ativo selecionado. O acompanhamento consulta barras reais, não um feed tick-a-tick; pode haver atraso da fonte. A barra em formação entra apenas na projeção, nunca no backtest.</p>
          <p className="w-full text-xs text-slate-400">p: termos autorregressivos · d: diferenciação dos log-retornos (d=0 corresponde a ARMA nos retornos) · q: termos de média móvel. As alterações só entram em vigor ao aplicar.</p>
          {liveMessage && <p role="status" className={`w-full text-sm ${liveMessage.startsWith("Erro") ? "text-rose-300" : "text-slate-300"}`}>{liveMessage}</p>}
        </div>

        {loading && !data ? (
          <PortfolioLoading />
        ) : error ? (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">{error}</div>
        ) : data ? (
          <>
            <div className="flex flex-wrap gap-2">
              {data.forecasts.map((f) => (
                <button
                  key={f.ticker}
                  onClick={() => selectTicker(f.ticker)}
                  className={[
                    "rounded-full px-3 py-1 text-sm font-medium transition",
                    selectedTicker === f.ticker
                      ? "bg-violet-600 text-white"
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700",
                  ].join(" ")}
                >
                  {f.ticker}
                  {f.error && <span className="ml-1 text-rose-400">!</span>}
                </button>
              ))}
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-6">
                {selected && (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <h2 className="text-lg font-semibold text-white">{selected.company_name || selected.ticker}</h2>
                        <p className="text-sm text-slate-400">
                          Previsão ARIMA{selected.order ? `(${selected.order.join(",")})` : ""} · {selected.mode === "manual" ? "Manual" : "Automático"} · {selected.forecast.length} {INTERVAL_LABELS[selected.interval ?? "1d"]} · RMSE {selected.rmse?.toFixed(3) ?? "-"} · MAPE{" "}
                          {selected.mape?.toFixed(2) ?? "-"}%
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => downloadForecastCsv(selected)}
                          className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
                        >
                          <Download className="h-4 w-4" />
                          Exportar CSV
                        </button>
                        <ForecastSignal change={forecastChange} />
                      </div>
                    </div>

                    {selected.market && (
                      <div className="mb-4 space-y-1 text-xs text-slate-400" aria-label="Estado da fonte de mercado">
                        <p>Mercado: {({ pre: "Pré-mercado", regular: "Aberto", post: "Pós-mercado", closed: "Fechado", unknown: "Estado não confirmado" })[selected.market.market_state]} · {selected.market.timezone} · {selected.market.prepost ? "Inclui pré/pós" : "Sessão regular"}</p>
                        <p>Última barra: {formatDate(selected.market.observed_at)} · {selected.market.partial_bar ? "Em formação" : "Concluída"} · Consulta: {formatDate(selected.market.fetched_at)} · Fonte pode ter atraso. A marca temporal identifica a barra, não a hora do último negócio.</p>
                      </div>
                    )}
                    <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <ForecastMetric
                        label="Último preço observado"
                        value={formatPrice(lastHistoricalPrice, selected.currency)}
                      />
                      <ForecastMetric
                        label="Previsão final"
                        value={formatPrice(finalForecast?.price, selected.currency)}
                        detail={finalForecast?.date ? formatDate(finalForecast.date) : undefined}
                      />
                      <ForecastMetric
                        label="Variação estimada"
                        value={forecastChange === null ? "—" : `${forecastChange >= 0 ? "+" : ""}${forecastChange.toFixed(2)}%`}
                        positive={forecastChange === null ? undefined : forecastChange >= 0}
                        detail="Face ao último preço disponível"
                      />
                      <ForecastMetric
                        label="Intervalo final"
                        value={
                          finalForecast?.lower !== undefined && finalForecast.upper !== undefined
                            ? `${formatPrice(finalForecast.lower, selected.currency)} – ${formatPrice(finalForecast.upper, selected.currency)}`
                            : "—"
                        }
                        detail="Banda de confiança do modelo"
                      />
                    </div>

                    <div className="mb-4 flex flex-wrap items-end gap-3">
                      <label className="text-sm text-slate-300">
                        Séries
                        <select
                          aria-label="Séries do gráfico"
                          value={chartView}
                          onChange={(event) => { resetSimulation(); setChartView(event.target.value); }}
                          className="ml-2 rounded-md border border-slate-700 bg-slate-900 p-2"
                        >
                          <option value="both">Histórico e previsão</option>
                          <option value="history">Só histórico</option>
                          <option value="forecast">Só previsão</option>
                          <option value="backtest">Backtest · real vs previsto</option>
                        </select>
                      </label>
                      <label className="text-sm text-slate-300">
                        Histórico
                        <select
                          aria-label="Janela do histórico"
                          value={historyWindow}
                          disabled={chartView === "forecast" || chartView === "backtest"}
                          onChange={(event) => setHistoryWindow(Number(event.target.value))}
                          className="ml-2 rounded-md border border-slate-700 bg-slate-900 p-2 disabled:opacity-50"
                        >
                          <option value={30}>Últimas 30 observações</option>
                          <option value={90}>Últimas 90 observações</option>
                          <option value={252}>Últimas 252 observações</option>
                          <option value={0}>Todo o histórico</option>
                        </select>
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input
                          type="checkbox"
                          checked={showBands}
                          onChange={(event) => setShowBands(event.target.checked)}
                        />
                        Bandas de confiança
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showTrend} onChange={(event) => setShowTrend(event.target.checked)} />
                        Cenário de tendência
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showRecommended} onChange={(event) => setShowRecommended(event.target.checked)} />
                        Modelo escolhido na validação
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showSignals} onChange={(event) => setShowSignals(event.target.checked)} />
                        Pontos comprar / vender / manter
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showAverages} onChange={(event) => setShowAverages(event.target.checked)} />
                        Médias SMA20 / SMA50
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showRealPrice} onChange={(event) => setShowRealPrice(event.target.checked)} />
                        Série real · preços observados
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-300">
                        <input type="checkbox" checked={showStoredForecast} onChange={(event) => setShowStoredForecast(event.target.checked)} />
                        Previsão original guardada
                      </label>
                    </div>
                    {chartView !== "history" && simulationRows.length > 0 && (
                      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-slate-300">
                        <button className="rounded bg-violet-600 px-3 py-2 text-white" onClick={() => { if (simulationDay === 0 || simulationDay >= simulationRows.length) setSimulationDay(1); setPlaying(!playing); }}>
                          {playing ? "Pausar simulação" : "Simular ponto a ponto"}
                        </button>
                        <button className="rounded bg-slate-800 px-3 py-2" onClick={() => { setPlaying(false); setSimulationDay(0); }}>Mostrar todos os pontos</button>
                        <label className="flex items-center gap-2">Observação
                          <input aria-label="Ponto da simulação" type="range" min={1} max={simulationRows.length} value={simulationDay || simulationRows.length} onChange={(event) => { setPlaying(false); setSimulationDay(Number(event.target.value)); }} />
                        </label>
                        <span>{simulationDay ? `${simulationDay}/${simulationRows.length} · ${formatDate(simulationRows[simulationDay - 1]?.date ?? "")}` : `${simulationRows.length} pontos · ${INTERVAL_LABELS[selected.interval ?? "1d"]}`}</span>
                      </div>
                    )}
                    <div className="h-[420px]" aria-label="Gráfico de histórico e previsão">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData} margin={{ top: 24, right: 20, bottom: 8, left: 8 }}>
                          <CartesianGrid stroke="rgba(148,163,184,0.08)" />
                          <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={32} stroke="#94a3b8" tick={{ fontSize: 10 }} />
                          <YAxis stroke="#94a3b8" tick={{ fontSize: 10 }} domain={["auto", "auto"]} width={65} />
                          <Tooltip
                            labelFormatter={(value) => formatDate(String(value))}
                            formatter={(value) => typeof value === "number" ? formatPrice(value, selected.currency) : String(value ?? "")}
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1e293b" }}
                            itemStyle={{ color: "#e2e8f0" }}
                            labelStyle={{ color: "#94a3b8" }}
                          />
                          <Legend />
                          {chartView !== "history" && chartView !== "backtest" && selected.forecast.length > 0 && <ReferenceArea
                            x1={selected.forecast[0]?.date}
                            x2={chartData[chartData.length - 1]?.date}
                            fill="rgba(139,92,246,0.08)"
                          />}
                          {chartView === "both" && selected.forecast.length > 0 && <ReferenceLine
                            x={selected.forecast[0]?.date}
                            stroke="#cbd5e1"
                            strokeDasharray="4 4"
                            label={{ value: "Previsão", position: "insideTopRight", fill: "#cbd5e1" }}
                          />}
                          {chartView !== "forecast" && chartView !== "backtest" && <Line
                            type="linear"
                            dataKey="history"
                            stroke="#38bdf8"
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={false}
                            name="Histórico"
                          />}
                          {chartView === "backtest" && <Line type="linear" dataKey="actual" stroke="#38bdf8" strokeWidth={2} dot={simulationDay === 1 ? { r: 3 } : false} isAnimationActive={false} name="Fecho real" />}
                          {showRealPrice && <Line type="linear" dataKey="realPrice" stroke="#06b6d4" strokeWidth={3} dot={{ r: 2, fill: "#06b6d4" }} isAnimationActive={false} name="Série real · fonte" />}
                          {showStoredForecast && <Line type="linear" dataKey="storedForecast" stroke="#e879f9" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} isAnimationActive={false} name="Previsão original guardada · última simulação" />}
                          {chartView !== "forecast" && showSignals && <>
                            <Line dataKey="buy" stroke="#22c55e" strokeWidth={0} legendType="circle" dot={{ r: 6, fill: "#22c55e", stroke: "#052e16" }} activeDot={{ r: 8, fill: "#22c55e" }} isAnimationActive={false} name="Sinal: Comprar" />
                            <Line dataKey="sell" stroke="#f43f5e" strokeWidth={0} legendType="circle" dot={{ r: 6, fill: "#f43f5e", stroke: "#4c0519" }} activeDot={{ r: 8, fill: "#f43f5e" }} isAnimationActive={false} name="Sinal: Vender" />
                            <Line dataKey="hold" stroke="#cbd5e1" strokeWidth={0} legendType="circle" dot={{ r: 4, fill: "#cbd5e1", stroke: "#334155" }} activeDot={{ r: 6, fill: "#cbd5e1" }} isAnimationActive={false} name="Sinal: Manter" />
                          </>}
                          {chartView !== "forecast" && showAverages && <>
                            <Line dataKey="sma20" stroke="#2dd4bf" dot={false} isAnimationActive={false} name="SMA20" />
                            <Line dataKey="sma50" stroke="#fbbf24" dot={false} isAnimationActive={false} name="SMA50" />
                          </>}
                          {chartView !== "history" && showTrend && <Line type="linear" dataKey="trend" stroke="#fb923c" strokeWidth={2} strokeDasharray="3 3" dot={simulationDay === 1 ? {r:3} : false} isAnimationActive={false} name="Cenário de tendência" />}
                          {chartView !== "history" && showRecommended && <Line type="linear" dataKey="recommended" stroke="#f472b6" strokeWidth={2} strokeDasharray="10 5" dot={simulationDay === 1 ? {r:3} : false} isAnimationActive={false} name="Escolha da validação" />}
                          {chartView !== "history" && <Line
                            type="linear"
                            dataKey="prediction"
                            stroke="#c4b5fd"
                            strokeWidth={3}
                            dot={simulationDay === 1 ? { r: 3 } : false}
                            isAnimationActive={false}
                            name="Previsão ARIMA"
                          />}
                          {chartView !== "history" && showBands && <Line
                            type="linear"
                            dataKey="upper"
                            stroke="#fbbf24"
                            strokeWidth={2.5}
                            strokeDasharray="8 5"
                            dot={simulationDay === 1 ? { r: 3 } : false}
                            isAnimationActive={false}
                            name="Limite superior"
                          />}
                          {chartView !== "history" && showBands && <Line
                            type="linear"
                            dataKey="lower"
                            stroke="#34d399"
                            strokeWidth={2.5}
                            strokeDasharray="8 5"
                            dot={simulationDay === 1 ? { r: 3 } : false}
                            isAnimationActive={false}
                            name="Limite inferior"
                          />}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <p className="mt-2 text-xs text-cyan-300">Preço real atual: {formatPrice(lastHistoricalPrice, selected.currency)} · barra {formatDate(selected.market?.observed_at ?? selected.series.at(-1)?.date ?? "")}. A série ciano contém apenas preços observados, incluindo o histórico guardado no Elasticsearch. Em “Só previsão” mostra as últimas 30 barras reais para comparação. Revisões da barra em formação atualizam o preço, sem pontuar a previsão. Ative “Acompanhar preços” para consultar a cada 60 s; pode haver atraso da fonte. A linha rosa tracejada conserva a última simulação registada; os snapshots anteriores estão na tabela persistente.</p>
                  </div>
                )}

                {selected && !selected.error && <IntradayPoints key={`${settingsKey}:${selected.market?.prepost}`}
                  ticker={selected.ticker} portfolioId={portfolioId ?? undefined} prepost={selected.market?.prepost ?? settings.prepost}
                />}
                {selected?.trading && !selected.error && (
                  <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/40 p-4" aria-label="Simulação de compra e venda">
                    <h2 className="font-semibold text-white">Simulação {selected.interval === "1h" ? "intradiária" : INTERVAL_LABELS[selected.interval ?? "1d"]} · comprar, vender ou manter</h2>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ForecastMetric label="Último sinal · barra concluída" value={ACTION_LABELS[selected.trading.latest.action]} detail={formatDate(selected.trading.latest.date)} />
                      <ForecastMetric label="RSI14 · médias simples" value={selected.trading.latest.rsi14.toFixed(2)} detail="≤30 sobrevendido · ≥70 sobrecomprado" />
                      <ForecastMetric label="MACD / sinal / histograma" value={`${selected.trading.latest.macd.toFixed(3)} / ${selected.trading.latest.macd_signal.toFixed(3)} / ${selected.trading.latest.macd_histogram.toFixed(3)}`} detail="EMA12 − EMA26; sinal EMA9" />
                      <ForecastMetric label="Previsão da próxima barra concluída" value={`${selected.trading.latest.expected_return_pct.toFixed(3)}%`} detail={`Pontuação combinada: ${selected.trading.latest.score}`} />
                      <ForecastMetric label="Retorno simulado líquido" value={`${selected.trading.return_pct.toFixed(2)}%`} detail={`Índice base 100 → ${selected.trading.final_equity.toFixed(2)} · ${selected.trading.trades} operações`} positive={selected.trading.return_pct >= 0} />
                      <ForecastMetric label="Comprar e manter · líquido" value={`${selected.trading.buy_hold_return_pct.toFixed(2)}%`} detail="Mesma primeira execução e custo de saída" />
                      <ForecastMetric label="Drawdown máximo" value={`${selected.trading.max_drawdown_pct.toFixed(2)}%`} />
                      <ForecastMetric label="Posição simulada" value={selected.trading.position === "long" ? "Comprado" : "Fora do mercado"} detail={`Comissões pagas: ${selected.trading.fees_paid.toFixed(3)} pontos do índice`} />
                    </div>
                    <ul className="list-inside list-disc text-sm text-slate-300">{selected.trading.latest.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                    <p className="text-xs leading-5 text-slate-400">Regras fixas, não otimizadas pelo backtest: RSI≤30 soma +1, RSI≥70 soma −1; MACD acima/abaixo do sinal e SMA20 acima/abaixo da SMA50 somam +1/−1. Previsão ARIMA acima de +0,20% ou abaixo de −0,20% soma +1/−1. Vender se RSI≥70, pontuação≤−2 ou previsão&lt;−0,20%; comprar se pontuação≥2 e previsão&gt;+0,20%; senão manter. Vender fora do mercado não abre uma posição curta; comprar já comprado não duplica a posição.</p>
                    <p className="text-xs leading-5 text-slate-400">Os pontos no gráfico são sinais no fecho da barra, não execuções. São mostrados nas vistas com histórico e backtest; não se inventam sinais para barras futuras. A tabela cobre o período reservado de backtest e o último sinal. Execução hipotética no fecho seguinte, 100% comprado ou em caixa, comissão de {selected.trading.fee_pct.toFixed(2)}% por compra/venda, sem ordens reais. O último sinal aguarda a próxima barra concluída; barras em formação não alteram estes sinais. A previsão dos sinais continua o ARIMA do backtest apenas com barras concluídas, distinta da projeção reajustada. A janela é recalculada a cada consulta, não é um livro persistente de operações. Valor líquido inclui custo estimado de saída da posição aberta. Sem spread, slippage, impostos ou fecho obrigatório ao fim da sessão; posições podem passar para o dia seguinte. Não é aconselhamento financeiro.</p>
                    <div className="h-44" aria-label="Gráfico RSI14 dos sinais">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={selected.trading.signals}>
                          <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={55} tick={{ fontSize: 10 }} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} width={35} />
                          <Tooltip labelFormatter={(value) => formatDate(String(value))} contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155" }} />
                          <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="4 4" />
                          <ReferenceLine y={70} stroke="#f43f5e" strokeDasharray="4 4" />
                          <Line dataKey="rsi14" name="RSI14" stroke="#a78bfa" dot={false} isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <details>
                      <summary className="cursor-pointer text-sm text-violet-300">Ver todos os sinais, indicadores e operações ({selected.trading.signals.length})</summary>
                      <div className="overflow-auto">
                        <table className="w-full text-left text-xs" aria-label="Sinais e operações simuladas">
                          <thead><tr>{["Barra do sinal", "Sinal", "RSI14", "MACD hist.", "SMA20 / SMA50", "Previsão 1 barra", "Motivos", "Execução seguinte", "Operação", "Preço execução", "Índice líquido"].map((heading) => <th key={heading} className="whitespace-nowrap p-2">{heading}</th>)}</tr></thead>
                          <tbody>{selected.trading.signals.map((row) => <tr key={row.date} className="border-t border-slate-800">
                            <td className="whitespace-nowrap p-2">{formatDate(row.date)}</td><td className="p-2">{ACTION_LABELS[row.action]}</td><td className="p-2">{row.rsi14.toFixed(2)}</td><td className="p-2">{row.macd_histogram.toFixed(3)}</td><td className="p-2">{row.sma20.toFixed(2)} / {row.sma50.toFixed(2)}</td><td className="p-2">{row.expected_return_pct.toFixed(3)}%</td><td className="min-w-60 p-2">{row.reasons.join("; ")}</td><td className="whitespace-nowrap p-2">{row.execution_date ? formatDate(row.execution_date) : "Aguarda barra concluída"}</td><td className="p-2">{row.execution ? ACTION_LABELS[row.execution] : "Pendente"}</td><td className="p-2">{formatPrice(row.execution_price, selected.currency)}</td><td className="p-2">{row.equity?.toFixed(2) ?? "—"}</td>
                          </tr>)}</tbody>
                        </table>
                      </div>
                    </details>
                  </section>
                )}
                {selected && !selected.error && (
                  <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4" aria-label="Diagnóstico ARIMA e padrões">
                    <h2 className="font-semibold text-white">Diagnóstico ARIMA e padrões</h2>
                    <p className="text-sm text-slate-300">Backtest de uma observação à frente ({INTERVAL_LABELS[selected.interval ?? "1d"]}): RMSE {selected.rmse?.toFixed(3) ?? "—"} · MAPE {selected.mape?.toFixed(2) ?? "—"}%. Referência ingénua (último preço): RMSE {selected.baseline_rmse?.toFixed(3) ?? "—"} · MAPE {selected.baseline_mape?.toFixed(2) ?? "—"}%.</p>
                    <p className="text-sm text-violet-300">Modelo escolhido por validação temporal anterior ao backtest: {MODEL_LABELS[selected.recommended_model ?? ""] ?? "—"}. Seleção estatística automática, sem LLM e sem garantia de superioridade futura.</p>
                    <div className="overflow-auto">
                      <table className="w-full text-left text-xs" aria-label="Comparação de modelos">
                        <thead><tr>{["Modelo", "RMSE validação", "MAPE validação", "RMSE backtest reservado", "MAPE backtest reservado"].map((heading) => <th key={heading} className="p-2">{heading}</th>)}</tr></thead>
                        <tbody>{selected.comparison?.map((row) => {
                          const holdout = selected.holdout_comparison?.find((candidate) => candidate.model === row.model);
                          return <tr key={row.model} className="border-t border-slate-800"><td className="p-2">{MODEL_LABELS[row.model] ?? row.model}</td><td className="p-2">{row.rmse.toFixed(3)}</td><td className="p-2">{row.mape.toFixed(2)}%</td><td className="p-2">{holdout?.rmse.toFixed(3) ?? "—"}</td><td className="p-2">{holdout?.mape.toFixed(2) ?? "—"}%</td></tr>;
                        })}</tbody>
                      </table>
                    </div>
                    {selected.warnings?.map((warning) => <p key={warning} className="text-sm text-amber-300">{warning}</p>)}
                    {selected.patterns && <div className="grid gap-3 sm:grid-cols-2">
                      <ForecastMetric label="Tendência (SMA20/SMA50)" value={{up:"Alta",down:"Baixa",mixed:"Mista"}[selected.patterns.trend]} detail={`${formatPrice(selected.patterns.sma20)} / ${formatPrice(selected.patterns.sma50)}`} />
                      <ForecastMetric label="Volatilidade anualizada" value={`${selected.patterns.volatility_annual_pct.toFixed(2)}%`} detail={`Últimas ${selected.patterns.window} observações`} />
                      <ForecastMetric label="Autocorrelação dos retornos (lag 1)" value={selected.patterns.autocorrelation_lag1?.toFixed(3) ?? "—"} />
                      <ForecastMetric label="Suporte / resistência indicativos" value={`${formatPrice(selected.patterns.support ?? undefined)} / ${formatPrice(selected.patterns.resistance ?? undefined)}`} />
                    </div>}
                    <p className="text-xs leading-5 text-slate-400">Padrões descritivos calculados até ao último preço, não sinais históricos do backtest. Suportes/resistências são extremos locais das últimas 60 observações, não níveis garantidos. A anualização horária assume 6,5 horas por sessão, aproximada com pré/pós. A tendência é um cenário separado de regressão log-linear das últimas 20 observações, não altera o ARIMA. Não é aconselhamento financeiro.</p>
                  </section>
                )}
                {selected && !selected.error && (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                    <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                      Como interpretar a previsão
                    </h2>
                    <p className="text-sm leading-6 text-slate-300">
                      A linha azul mostra os preços observados e a linha violeta a estimativa ARIMA para as próximas {selected.forecast.length} observações ({INTERVAL_LABELS[selected.interval ?? "1d"]}).
                      Os limites tracejados amarelo e verde delimitam a banda de confiança: uma faixa mais larga indica maior incerteza,
                      não um intervalo garantido para o preço.
                    </p>
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      Use “Só previsão” para ampliar o horizonte futuro e ver melhor as bandas, ou “Todo o histórico”
                      para consultar todas as observações. Histórico e previsão são séries separadas: não existe
                      uma linha artificial a ligar o último fecho à primeira estimativa.
                    </p>
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      A variação estimada compara o último fecho disponível com a previsão final. RMSE é a raiz do erro
                      quadrático médio na unidade do preço e MAPE é o erro percentual absoluto médio; são métricas históricas,
                      não uma garantia de desempenho futuro.
                    </p>
                  </div>
                )}

                {selected?.error && (
                  <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-4 text-rose-200">
                    {selected.error}
                  </div>
                )}
              </div>

              <div className="space-y-6">
                <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Notícias de contexto
                  </h2>
                  <PortfolioNewsStrip news={data.news} />
                </div>

              </div>
            </div>
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4" aria-label="Previsões resumidas">
              <h2 className="mb-2 text-lg font-semibold text-white">Previsões resumidas</h2>
              <p className="mb-4 text-sm text-slate-400">
                Todos os {data.forecasts.length} ativos devolvidos para esta carteira. Selecione um ticker para ver o gráfico
                e exportar o histórico completo e as previsões. Os ativos sem previsão mostram o erro recebido.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-700 text-slate-400">
                    <tr>
                      {["Ativo", "Escala", "Último preço", "Previsão final", "Variação", "Limite inferior", "Limite superior", "RMSE", "MAPE", "Estado"].map((heading) => (
                        <th key={heading} className="whitespace-nowrap p-3">{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.forecasts.map((forecast) => {
                      const historicalPrice = forecast.series.findLast(isHistoricalSeries)?.value;
                      const last = forecast.forecast.at(-1);
                      const change = calculateChange(historicalPrice, last?.price);
                      return (
                        <tr key={forecast.ticker} className={`border-b border-slate-800 ${selectedTicker === forecast.ticker ? "bg-violet-500/10" : ""}`}>
                          <td className="p-3">
                            <button onClick={() => selectTicker(forecast.ticker)} className="font-semibold text-violet-300 underline underline-offset-4">
                              {forecast.ticker}
                            </button>
                          </td>
                          <td className="whitespace-nowrap p-3">{INTERVAL_LABELS[forecast.interval ?? "1d"]}</td>
                          <td className="whitespace-nowrap p-3">{formatPrice(historicalPrice, forecast.currency)}</td>
                          <td className="whitespace-nowrap p-3">{formatPrice(last?.price, forecast.currency)}</td>
                          <td className={`p-3 ${change === null ? "text-slate-400" : change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {change === null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
                          </td>
                          <td className="whitespace-nowrap p-3">{formatPrice(last?.lower, forecast.currency)}</td>
                          <td className="whitespace-nowrap p-3">{formatPrice(last?.upper, forecast.currency)}</td>
                          <td className="p-3">{forecast.rmse?.toFixed(3) ?? "—"}</td>
                          <td className="p-3">{forecast.mape === undefined ? "—" : `${forecast.mape.toFixed(2)}%`}</td>
                          <td className={`min-w-40 p-3 ${forecast.error ? "text-rose-300" : "text-slate-400"}`}>
                            {forecast.error || (last ? `${forecast.forecast.length} pontos · ${formatDate(last.date)}` : "Sem previsões disponíveis")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
            {selected && !selected.error && <ForecastJournal key={`${settingsKey}:${selected.interval}:${selected.market?.prepost}`}
              ticker={selected.ticker} interval={selected.interval ?? "1d"} prepost={selected.market?.prepost ?? false}
              portfolioId={portfolioId ?? undefined} persistence={selected.persistence} currency={selected.currency}
            />}
            {selected && selected.forecast.length > 0 && (
              <details className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <summary className="cursor-pointer font-semibold text-violet-300">Ver todas as previsões · {selected.ticker} · {INTERVAL_LABELS[selected.interval ?? "1d"]}</summary>
                <div className="mt-4 max-h-96 overflow-auto">
                  <table className="w-full text-left text-sm" aria-label="Previsões por observação">
                    <thead><tr>{["Data", "Preço previsto", "Limite inferior", "Limite superior"].map((heading) => <th key={heading} className="p-2">{heading}</th>)}</tr></thead>
                    <tbody>{selected.forecast.map((point) => (
                      <tr key={point.date} className="border-t border-slate-800">
                        <td className="p-2">{formatDate(point.date)}</td>
                        <td className="p-2">{formatPrice(point.price, selected.currency)}</td>
                        <td className="p-2">{formatPrice(point.lower, selected.currency)}</td>
                        <td className="p-2">{formatPrice(point.upper, selected.currency)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </details>
            )}
            {selected?.backtest && selected.backtest.length > 0 && (
              <details className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
                <summary className="cursor-pointer font-semibold text-violet-300">Backtest por observação · {selected.ticker}</summary>
                <div className="mt-4 max-h-96 overflow-auto">
                  <table className="w-full text-left text-sm" aria-label="Resultados do backtest por observação">
                    <thead><tr>{["Data", "Real", "Previsto antes do fecho", "Erro absoluto", "Referência"].map((heading) => <th className="p-2" key={heading}>{heading}</th>)}</tr></thead>
                    <tbody>{selected.backtest.map((point) => <tr key={point.date} className="border-t border-slate-800">
                      <td className="p-2">{formatDate(point.date)}</td><td className="p-2">{formatPrice(point.actual)}</td><td className="p-2">{formatPrice(point.price)}</td><td className="p-2">{formatPrice(Math.abs(point.price - point.actual))}</td><td className="p-2">{formatPrice(point.baseline)}</td>
                    </tr>)}</tbody>
                  </table>
                </div>
              </details>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

function buildChartData(
  selected: PortfolioForecastResponse["forecasts"][number] | undefined,
  view: string,
  historyWindow: number,
  showRealPrice: boolean,
  realPrices: RealPrice[],
): ChartPoint[] {
  if (!selected) return [];
  const signals = new Map(selected.trading?.signals.map((signal) => [signal.date, signal]));
  const signalData = (date: string) => {
    const signal = signals.get(date);
    return signal ? {
      buy: signal.action === "buy" ? signal.price : undefined,
      sell: signal.action === "sell" ? signal.price : undefined,
      hold: signal.action === "hold" ? signal.price : undefined,
      sma20: signal.sma20, sma50: signal.sma50,
    } : {};
  };
  const mergeRealPrices = (points: ChartPoint[]): ChartPoint[] => {
    const merged = new Map(points.map((point) => [point.date, point]));
    const journal = selected.persistence && !("error" in selected.persistence) ? selected.persistence : null;
    const observed = new Map((journal?.real_series ?? []).map((point) => [point.date, point.value]));
    realPrices.forEach((point) => observed.set(point.date, point.value));
    selected.series.filter(isHistoricalSeries).forEach((point) => { if (typeof point.value === "number") observed.set(point.date, point.value); });
    const visibleReal = [...observed].sort(([a], [b]) => a.localeCompare(b));
    for (const [date, value] of view === "forecast" ? visibleReal.slice(-30) : visibleReal) {
      if (view !== "forecast" && points[0] && date < points[0].date) continue;
      if (showRealPrice) merged.set(date, { ...merged.get(date), date, realPrice: value });
    }
    const lastRun = journal?.items[0]?.run_id;
    journal?.items.filter((point) => point.run_id === lastRun).forEach((point) => {
      const date = point.target_key;
      if (view === "history" && !merged.has(date)) return;
      if (points[0] && date < points[0].date) return;
      merged.set(date, { ...merged.get(date), date, storedForecast: point.predicted });
    });
    return [...merged.values()].sort((a, b) => a.date.localeCompare(b.date));
  };
  if (view === "backtest") return mergeRealPrices((selected.backtest ?? []).map((point) => ({
    date: point.date, actual: point.actual, prediction: point.price, lower: point.lower, upper: point.upper,
    ...signalData(point.date),
    trend: point.trend,
    recommended: selected.recommended_model === "trend" ? point.trend : selected.recommended_model === "last_close" ? point.baseline : point.price,
  })));
  const allHistory = selected.series
    .filter((s) => isHistoricalSeries(s) && typeof s.value === "number" && Number.isFinite(s.value))
    .sort((a, b) => a.date.localeCompare(b.date));
  const history = (historyWindow > 0 ? allHistory.slice(-historyWindow) : allHistory)
    .map((point) => ({ date: point.date, history: point.value, ...signalData(point.date) }));
  const forecast = selected.forecast.map((p) => ({
    date: p.date,
    prediction: p.price,
    lower: p.lower,
    upper: p.upper,
    trend: p.trend,
    recommended: p.recommended,
  }));
  return mergeRealPrices([...(view === "forecast" ? [] : history), ...(view === "history" ? [] : forecast)]
    .sort((a, b) => a.date.localeCompare(b.date)));
}

function isHistoricalSeries(point: ForecastSeries) {
  return point.type === "train" || point.type === "test" || point.type === "history";
}

function formatDate(value: string) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value.slice(0, 10);
  if (value.includes("T")) return `${d.toLocaleString("pt-PT", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;
  return d.toLocaleDateString("pt-PT", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

function formatPrice(value?: number, currency?: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const formatted = value.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${formatted} ${currency}` : formatted;
}

function calculateChange(referencePrice?: number, forecastPrice?: number) {
  if (
    typeof referencePrice !== "number" ||
    !Number.isFinite(referencePrice) ||
    referencePrice === 0 ||
    typeof forecastPrice !== "number" ||
    !Number.isFinite(forecastPrice)
  ) {
    return null;
  }
  return (forecastPrice / referencePrice - 1) * 100;
}

function downloadForecastCsv(forecast: {
  ticker: string;
  currency?: string;
  series: ForecastSeries[];
  forecast: ForecastPoint[];
  backtest?: { date: string; actual: number; price: number; lower: number; upper: number; baseline: number }[];
  trading?: { signals: TradingSignal[] };
}) {
  const escapeCsv = (value: string | number | undefined) =>
    `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [
    ["ticker", "date", "type", "price", "lower", "upper", "currency", "actual", "baseline", "trend", "recommended"],
    ...forecast.series
      .filter(isHistoricalSeries)
      .map((point) => [forecast.ticker, point.date, point.type, point.value, "", "", forecast.currency ?? "", "", "", "", ""]),
    ...forecast.forecast.map((point) => [
      forecast.ticker,
      point.date,
      "forecast",
      point.price,
      point.lower,
      point.upper,
      forecast.currency ?? "",
      "",
      "",
      point.trend,
      point.recommended,
    ]),
    ...(forecast.backtest ?? []).map((point) => [
      forecast.ticker, point.date, "backtest", point.price, point.lower, point.upper,
      forecast.currency ?? "", point.actual, point.baseline, "", "",
    ]),
  ];
  const signalHeaders = ["action", "rsi14", "macd", "macd_signal", "macd_histogram", "sma20", "sma50", "signal_prediction", "expected_return_pct", "score", "reasons", "execution_date", "execution", "execution_price", "fee", "equity"];
  const exportRows = [
    [...rows[0], ...signalHeaders],
    ...rows.slice(1).map((row) => [...row, ...signalHeaders.map(() => "")]),
    ...(forecast.trading?.signals ?? []).map((row) => [
      forecast.ticker, row.date, "signal", row.price, "", "", forecast.currency ?? "", "", "", "", "",
      row.action, row.rsi14, row.macd, row.macd_signal, row.macd_histogram, row.sma20, row.sma50, row.prediction,
      row.expected_return_pct, row.score, row.reasons.join("; "), row.execution_date, row.execution, row.execution_price, row.fee, row.equity,
    ]),
  ];
  const csv = `\uFEFF${exportRows.map((row) => row.map(escapeCsv).join(";")).join("\r\n")}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `previsao-${forecast.ticker.replace(/[^a-zA-Z0-9._-]/g, "_")}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ForecastMetric({
  label,
  value,
  detail,
  positive,
}: {
  label: string;
  value: string;
  detail?: string;
  positive?: boolean;
}) {
  return (
    <div className="rounded-md bg-slate-800/60 p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-base font-semibold ${positive === undefined ? "text-white" : positive ? "text-emerald-400" : "text-rose-400"}`}>
        {value}
      </p>
      {detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}
    </div>
  );
}

function ForecastSignal({ change }: { change: number | null }) {
  if (change === null) return null;
  const Icon = change > 0 ? TrendingUp : change < 0 ? TrendingDown : Minus;
  const color = change > 0 ? "text-emerald-400" : change < 0 ? "text-rose-400" : "text-slate-400";
  return (
    <div className={`flex items-center gap-2 rounded-lg bg-slate-800 px-3 py-1.5 ${color}`}>
      <Icon className="h-4 w-4" />
      <span className="text-sm font-semibold">{change >= 0 ? "+" : ""}
        {change.toFixed(2)}%
      </span>
    </div>
  );
}
