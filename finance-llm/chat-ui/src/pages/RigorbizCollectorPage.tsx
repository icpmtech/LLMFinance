/**
 * Monitor da recolha RigorBiz (`/rigorbiz/collect/*`).
 *
 * Mostra em tempo real o progresso do runner (página, recolhidas, indexadas,
 * total anunciado pelo site), permite arrancar/parar a recolha e acompanhar o
 * log. O estado é lido de `data/rigorbiz/rigorbiz_runner_state.json`, escrito
 * pelo runner a cada página, e atualiza-se por polling.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Building2,
  Database,
  Gauge,
  Loader2,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";

import {
  getRigorbizCollectStatus,
  startRigorbizCollect,
  stopRigorbizCollect,
  type RigorbizCollectStatus,
} from "../rigorbizApi";

const POLL_MS = 3000;

function Kpi({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3">
      <p className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function num(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT");
}

function since(iso?: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `há ${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `há ${minutes}min`;
  return `há ${Math.round(minutes / 60)}h`;
}

export default function RigorbizCollectorPage() {
  const [status, setStatus] = useState<RigorbizCollectStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [delay, setDelay] = useState(4);
  const logRef = useRef<HTMLPreElement>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getRigorbizCollectStatus();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao ler o estado da recolha.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const runner = status?.runner ?? {};
  const running = Boolean(runner.running);
  const total = runner.total_announced ?? status?.checkpoint.total ?? null;
  const unique = runner.unique_total ?? status?.meta.local_count ?? 0;
  const indexed = runner.indexed ?? 0;
  const page = runner.page ?? status?.checkpoint.last_page ?? 0;
  const progress = useMemo(() => {
    if (!total || total <= 0) return 0;
    return Math.min(100, (unique / total) * 100);
  }, [total, unique]);

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Operação falhou.");
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const logLines = status?.log_tail ?? [];

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logLines.length]);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full glass-card px-3 py-1 text-xs text-teal-300">
              <Activity size={14} />
              Recolha em direto
            </div>
            <h1 className="mb-1 flex items-center gap-3 text-3xl font-bold">
              <span className="rounded-2xl border border-white/10 bg-gradient-to-br from-teal-500/20 to-blue-500/20 p-2">
                <Building2 size={28} className="text-teal-400" />
              </span>
              Collector RigorBiz
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Recolha paginada do diretório com indexação contínua em{" "}
              <code className="rounded bg-white/5 px-1">{status?.meta.index ?? "finance_rigorbiz"}</code>.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => act(() => startRigorbizCollect({ mode: "all", delay }))}
              disabled={busy || running}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lg shadow-primary/20 transition hover:opacity-90 disabled:opacity-40"
            >
              {busy && !running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              Arrancar
            </button>
            <button
              type="button"
              onClick={() => act(stopRigorbizCollect)}
              disabled={busy || !running}
              className="inline-flex items-center gap-2 rounded-xl glass-card px-4 py-2 text-sm transition hover:bg-white/5 disabled:opacity-40"
            >
              <Square size={14} />
              Parar
            </button>
            <button
              type="button"
              onClick={() => void refresh()}
              className="inline-flex items-center gap-2 rounded-xl glass-card px-3 py-2 text-sm transition hover:bg-white/5"
              title="Atualizar"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${
              running
                ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"
                : runner.error
                  ? "border-red-400/40 bg-red-400/10 text-red-200"
                  : "border-white/10 bg-white/5"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${running ? "animate-pulse bg-emerald-400" : "bg-white/40"}`}
            />
            {running ? "em curso" : runner.error ? "erro" : runner.stopped ? "parado" : "inativo"}
          </span>
          {running ? <span>atualizado {since(runner.updated_at)}</span> : null}
          {runner.started_at ? <span>início {since(runner.started_at)}</span> : null}
          {typeof runner.delay === "number" ? <span>delay {runner.delay}s/página</span> : null}
          <label className="ml-auto flex items-center gap-2">
            delay
            <input
              type="number"
              min={0.5}
              max={30}
              step={0.5}
              value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
              className="w-16 rounded-lg border border-white/10 bg-background px-2 py-1 text-xs outline-none"
            />
            s
          </label>
        </div>

        {error ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
        {runner.error ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>Runner: {runner.error}</span>
          </div>
        ) : null}

        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Página" value={num(page)} icon={<Gauge size={11} />} hint={`total ${num(total)}`} />
          <Kpi label="Recolhidas" value={num(unique)} icon={<Building2 size={11} />} hint={`+${num(runner.collected)} nesta execução`} />
          <Kpi label="Indexadas (ES)" value={num(status?.meta.elasticsearch_count ?? indexed)} icon={<Database size={11} />} hint={`${num(indexed)} neste run`} />
          <Kpi
            label="Progresso"
            value={`${progress.toFixed(progress < 1 ? 3 : 1)}%`}
            hint={total ? `${num(total)} anunciadas pelo site` : "total desconhecido"}
          />
        </div>

        <div className="mb-6 h-2 w-full overflow-hidden rounded-full bg-white/5">
          <div
            className="h-full rounded-full bg-gradient-to-r from-teal-400 to-sky-500 transition-all duration-500"
            style={{ width: `${Math.max(progress, progress > 0 ? 0.5 : 0)}%` }}
          />
        </div>

        <div className="glass-card overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between border-b border-white/5 px-4 py-2">
            <p className="text-xs font-medium text-muted-foreground">Log da recolha</p>
            <span className="text-[10px] text-muted-foreground">{logLines.length} linhas</span>
          </div>
          <pre
            ref={logRef}
            className="max-h-[420px] overflow-auto px-4 py-3 text-[11px] leading-relaxed text-muted-foreground"
          >
            {logLines.length ? logLines.join("") : loading ? "A carregar…" : "Sem log registado."}
          </pre>
        </div>
      </div>
    </div>
  );
}
