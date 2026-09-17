/**
 * Aplicação «Administração» (`/admin`).
 *
 * Reúne a administração da solução numa janela própria, com quatro separadores:
 *
 * - **Visão geral** — saúde da API e do Elasticsearch, índices (documentos e
 *   tamanho), contas por papel/estado, eventos das últimas 24 h e ficheiros de log.
 * - **Utilizadores** — pesquisa, papel (`admin`/`member`), estado
 *   (`active`/`suspended`), sessões ativas e ações (suspender, promover, terminar
 *   sessões, apagar).
 * - **Eventos** — o *event logger viewer*: filtros por nível/origem/utilizador/
 *   texto, fonte (tempo real em memória ou arquivo no Elasticsearch), atualização
 *   automática, gráfico por hora, detalhe JSON de cada evento e criação de eventos
 *   manuais para teste.
 * - **Ficheiros de log** — lista e últimas linhas dos ficheiros em `logs/`.
 *
 * O acesso é restrito a contas com papel `admin` (o servidor devolve 403).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Info,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserCog,
  Users,
  XCircle,
} from "lucide-react";
import {
  deleteAdminUser,
  getAdminEventStats,
  getAdminOverview,
  listAdminEvents,
  listAdminLogs,
  listAdminUsers,
  logAdminEvent,
  revokeAdminUserSessions,
  tailAdminLog,
  updateAdminUser,
  type AdminOverview,
  type AdminUser,
  type EventLevel,
  type EventQuery,
  type EventStats,
  type LogTail,
  type SystemEvent,
} from "../adminApi";
import { useAuth } from "../auth";
import { useWindowMode } from "../layout";

type Tab = "overview" | "users" | "events" | "logs";

const LEVEL_STYLES: Record<string, { color: string; label: string; icon: typeof Info }> = {
  debug: { color: "bg-slate-500/15 text-slate-300 border-slate-400/20", label: "debug", icon: Bug },
  info: { color: "bg-sky-500/15 text-sky-300 border-sky-400/20", label: "info", icon: Info },
  warning: { color: "bg-amber-500/15 text-amber-300 border-amber-400/30", label: "aviso", icon: AlertTriangle },
  error: { color: "bg-rose-500/15 text-rose-300 border-rose-400/30", label: "erro", icon: XCircle },
  critical: { color: "bg-rose-600/25 text-rose-200 border-rose-400/40", label: "crítico", icon: XCircle },
};

const ALL_LEVELS: EventLevel[] = ["debug", "info", "warning", "error", "critical"];

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(seconds?: number) {
  if (!seconds || seconds <= 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${Math.floor(seconds % 60)}s`;
}

function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-PT", { hour12: false });
}

function formatClock(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("pt-PT", { hour12: false });
}

/** Cartão simples de métrica (usado na visão geral e nos utilizadores). */
function Metric({
  label,
  value,
  hint,
  icon,
  tone = "teal",
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: React.ReactNode;
  tone?: "teal" | "amber" | "rose" | "violet" | "sky";
}) {
  const tones: Record<string, string> = {
    teal: "text-teal-300",
    amber: "text-amber-300",
    rose: "text-rose-300",
    violet: "text-violet-300",
    sky: "text-sky-300",
  };
  return (
    <div className="min-w-0 rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <p className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
        {icon}
        <span className="truncate">{label}</span>
      </p>
      <p className={`mt-1 truncate text-[19px] font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-[10.5px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Barras horizontais simples para contagens (níveis, origens, caminhos). */
function CountBars({
  rows,
  color = "bg-teal-400",
  onSelect,
  emptyLabel = "Sem dados.",
  labelWidth = "w-40",
}: {
  rows: { key: string; count: number }[];
  color?: string;
  onSelect?: (key: string) => void;
  emptyLabel?: string;
  labelWidth?: string;
}) {
  if (rows.length === 0) return <p className="text-[11.5px] text-muted-foreground">{emptyLabel}</p>;
  const peak = Math.max(...rows.map((row) => row.count), 1);
  return (
    <ul className="space-y-2">
      {rows.map((row) => {
        const content = (
          <>
            <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
              <span className={`min-w-0 truncate font-mono ${labelWidth}`} title={row.key}>
                {row.key}
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{row.count.toLocaleString("pt-PT")}</span>
            </div>
            <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-white/10">
              <span
                className={`block h-full rounded-full ${color}`}
                style={{ width: `${Math.max(2, Math.round((row.count / peak) * 100))}%` }}
              />
            </span>
          </>
        );
        return (
          <li key={row.key}>
            {onSelect ? (
              <button type="button" onClick={() => onSelect(row.key)} className="group w-full text-left">
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* -------------------------------------------------------------- eventos */

function EventRow({ event }: { event: SystemEvent }) {
  const [open, setOpen] = useState(false);
  const style = LEVEL_STYLES[event.level] ?? LEVEL_STYLES.info;
  const Icon = style.icon;
  return (
    <li className="border-b border-white/6 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-2 px-3 py-1.5 text-left transition hover:bg-white/[0.04]"
      >
        <span className="shrink-0 pt-0.5 font-mono text-[11px] text-muted-foreground" title={formatTime(event.timestamp)}>
          {formatClock(event.timestamp)}
        </span>
        <span className={`flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] uppercase ${style.color}`}>
          <Icon size={10} /> {style.label}
        </span>
        <span className="w-14 shrink-0 truncate text-[11px] text-muted-foreground" title={event.source}>
          {event.source}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px]" title={event.message}>
          {event.message}
        </span>
        {event.status !== undefined && (
          <span
            className={`shrink-0 rounded-md border px-1.5 text-[10.5px] tabular-nums ${
              event.status >= 500
                ? "border-rose-400/30 text-rose-300"
                : event.status >= 400
                  ? "border-amber-400/30 text-amber-300"
                  : "border-white/10 text-muted-foreground"
            }`}
          >
            {event.status}
          </span>
        )}
        {event.duration_ms !== undefined && (
          <span className="w-14 shrink-0 truncate text-right text-[10.5px] tabular-nums text-muted-foreground">
            {event.duration_ms.toFixed(0)} ms
          </span>
        )}
        <span className="w-40 shrink-0 truncate text-[11px] text-muted-foreground" title={event.user_email || event.ip || ""}>
          {event.user_email || event.ip || "—"}
        </span>
      </button>
      {open && (
        <pre className="mx-3 mb-2 max-h-64 overflow-auto rounded-lg border border-white/10 bg-black/40 p-2 text-[11px] text-slate-300">
          {JSON.stringify(event, null, 2)}
        </pre>
      )}
    </li>
  );
}

function EventsTab({ onError }: { onError: (message: string | null) => void }) {
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [backend, setBackend] = useState("");
  const [levels, setLevels] = useState<EventLevel[]>([]);
  const [source, setSource] = useState("");
  const [user, setUser] = useState("");
  const [text, setText] = useState("");
  const [hours, setHours] = useState<number | "">(24);
  const [source_, setSource_] = useState<"memory" | "elasticsearch" | "auto">("memory");
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<EventStats | null>(null);
  const [statsHours, setStatsHours] = useState(24);
  const [draft, setDraft] = useState({ level: "info", message: "" });
  const timerRef = useRef<number | null>(null);

  const query = useMemo<EventQuery>(() => {
    const since = hours === "" ? undefined : new Date(Date.now() - hours * 3600_000).toISOString();
    return {
      level: levels.length > 0 ? levels.join(",") : undefined,
      source: source || undefined,
      user: user.trim() || undefined,
      q: text.trim() || undefined,
      since,
      backend: source_,
      size: 200,
    };
  }, [hours, levels, source, source_, text, user]);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const response = await listAdminEvents(query);
        setEvents(response.items);
        setTotal(response.total);
        setBackend(response.capacity ? `${response.backend} (${response.capacity})` : response.backend);
        onError(null);
      } catch (error) {
        onError(error instanceof Error ? error.message : "Erro ao carregar eventos.");
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [onError, query],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const loadStats = useCallback(async () => {
    try {
      setStats(await getAdminEventStats(statsHours));
    } catch {
      /* o painel de estatísticas é acessório */
    }
  }, [statsHours]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  /* Atualização automática (5 s) — desligada por omissão. */
  useEffect(() => {
    if (!live) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      return;
    }
    timerRef.current = window.setInterval(() => {
      void load(true);
      void loadStats();
    }, 5000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [live, load, loadStats]);

  const toggleLevel = (level: EventLevel) =>
    setLevels((current) => (current.includes(level) ? current.filter((value) => value !== level) : [...current, level]));

  const sendDraft = async () => {
    if (!draft.message.trim()) return;
    try {
      await logAdminEvent({ level: draft.level, source: "admin", message: draft.message.trim() });
      setDraft({ level: draft.level, message: "" });
      await load(true);
      await loadStats();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Erro ao registar o evento.");
    }
  };

  return (
    <div className="@container flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
      {/* Estatísticas */}
      <section className="grid shrink-0 gap-3 @2xl:grid-cols-3">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Eventos por nível</p>
            <select
              value={statsHours}
              onChange={(event) => setStatsHours(Number(event.target.value))}
              className="rounded-md border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[11px]"
            >
              {[1, 6, 24, 72, 168].map((value) => (
                <option key={value} value={value}>
                  {value} h
                </option>
              ))}
            </select>
          </div>
          <p className="mt-1 text-[11.5px] text-muted-foreground">
            {stats ? `${stats.total.toLocaleString("pt-PT")} eventos · ${stats.backend}` : "—"}
          </p>
          <div className="mt-2">
            <CountBars
              rows={(stats?.by_level ?? []).map((row) => ({ key: row.key, count: row.count }))}
              color="bg-sky-400"
              onSelect={(key) => setLevels([key as EventLevel])}
            />
          </div>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Origens</p>
          <div className="mt-2">
            <CountBars
              rows={stats?.by_source ?? []}
              color="bg-violet-400"
              onSelect={(key) => setSource(key)}
              labelWidth="w-24"
            />
          </div>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Caminhos mais chamados</p>
          <div className="mt-2">
            <CountBars rows={stats?.top_paths ?? []} color="bg-amber-400" labelWidth="w-full" />
          </div>
        </div>
      </section>

      {/* Linha temporal por hora */}
      {stats && stats.by_hour.length > 0 && (
        <section className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Por hora</p>
          <div className="mt-2 flex h-16 items-end gap-1">
            {stats.by_hour.slice(-48).map((row) => {
              const peak = Math.max(...stats.by_hour.map((item) => item.count), 1);
              return (
                <span
                  key={row.key}
                  title={`${row.key} · ${row.count}`}
                  className="flex-1 rounded-t bg-teal-400/70"
                  style={{ height: `${Math.max(4, Math.round((row.count / peak) * 100))}%` }}
                />
              );
            })}
          </div>
        </section>
      )}

      {/* Filtros */}
      <section className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] p-2">
        {ALL_LEVELS.map((level) => {
          const active = levels.includes(level);
          const style = LEVEL_STYLES[level];
          return (
            <button
              key={level}
              type="button"
              aria-pressed={active}
              onClick={() => toggleLevel(level)}
              className={[
                "rounded-lg border px-2 py-1 text-[11px] uppercase transition",
                active ? style.color : "border-white/10 text-muted-foreground hover:bg-white/[0.06]",
              ].join(" ")}
            >
              {style.label}
            </button>
          );
        })}
        <input
          value={source}
          onChange={(event) => setSource(event.target.value)}
          placeholder="origem (api, auth…)"
          className="w-32 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none focus:border-teal-400/40"
        />
        <input
          value={user}
          onChange={(event) => setUser(event.target.value)}
          placeholder="utilizador (email)"
          className="w-40 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none focus:border-teal-400/40"
        />
        <label className="relative flex items-center">
          <Search size={12} className="pointer-events-none absolute left-2 text-muted-foreground" />
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="procurar na mensagem/caminho"
            className="w-56 rounded-lg border border-white/10 bg-white/[0.04] py-1 pl-7 pr-2 text-[11.5px] outline-none focus:border-teal-400/40"
          />
        </label>
        <select
          value={hours}
          onChange={(event) => setHours(event.target.value === "" ? "" : Number(event.target.value))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
          title="Janela temporal"
        >
          <option value="">Sem limite</option>
          {[1, 6, 24, 72, 168, 720].map((value) => (
            <option key={value} value={value}>
              últimas {value} h
            </option>
          ))}
        </select>
        <select
          value={source_}
          onChange={(event) => setSource_(event.target.value as "memory" | "elasticsearch" | "auto")}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
          title="Fonte dos eventos"
        >
          <option value="memory">Tempo real (memória)</option>
          <option value="elasticsearch">Arquivo (Elasticsearch)</option>
          <option value="auto">Automática</option>
        </select>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Atualizar
        </button>
        <button
          type="button"
          onClick={() => setLive((value) => !value)}
          aria-pressed={live}
          className={[
            "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11.5px] transition",
            live ? "border-teal-400/40 bg-teal-400/10 text-teal-200" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
          ].join(" ")}
        >
          {live ? <Pause size={12} /> : <Play size={12} />} {live ? "Em direto" : "Direto"}
        </button>
        <span className="ml-auto text-[11px] text-muted-foreground">
          {total.toLocaleString("pt-PT")} eventos · fonte {backend || "—"}
        </span>
      </section>

      {/* Lista */}
      <section className="max-h-[55vh] shrink-0 overflow-hidden rounded-xl border border-white/10 bg-white/[0.01]">
        <div className="flex items-center gap-2 border-b border-white/8 bg-white/[0.03] px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          <span className="w-16">hora</span>
          <span className="w-16">nível</span>
          <span className="w-14">origem</span>
          <span className="flex-1">mensagem</span>
          <span className="w-10 text-right">http</span>
          <span className="w-14 text-right">tempo</span>
          <span className="w-40">utilizador / ip</span>
        </div>
        <ul className="max-h-[50vh] overflow-auto">
          {events.length === 0 && !loading && (
            <li className="px-3 py-8 text-center text-[12px] text-muted-foreground">
              Sem eventos para os filtros escolhidos.
            </li>
          )}
          {events.map((event, index) => (
            <EventRow key={event.id ?? `${event.timestamp}-${index}`} event={event} />
          ))}
        </ul>
      </section>

      {/* Evento manual */}
      <section className="flex shrink-0 flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] p-2">
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Registar evento de teste</span>
        <select
          value={draft.level}
          onChange={(event) => setDraft((current) => ({ ...current, level: event.target.value }))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
        >
          {ALL_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        <input
          value={draft.message}
          onChange={(event) => setDraft((current) => ({ ...current, message: event.target.value }))}
          onKeyDown={(event) => {
            if (event.key === "Enter") void sendDraft();
          }}
          placeholder="mensagem do evento…"
          className="min-w-[240px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] outline-none focus:border-teal-400/40"
        />
        <button
          type="button"
          onClick={() => void sendDraft()}
          className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] transition hover:bg-white/[0.1]"
        >
          Registar
        </button>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------- utilizadores */

function UsersTab({ onError, currentUserId }: { onError: (message: string | null) => void; currentUserId?: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listAdminUsers({ q: q.trim() || undefined, role: role || undefined, status: status || undefined });
      setUsers(response.items);
      setTotal(response.total);
      onError(null);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Erro ao carregar utilizadores.");
    } finally {
      setLoading(false);
    }
  }, [onError, q, role, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (label: string, action: () => Promise<unknown>, userId: string) => {
    setBusy(userId);
    setNotice(null);
    try {
      await action();
      setNotice(label);
      await load();
    } catch (error) {
      onError(error instanceof Error ? error.message : `Erro: ${label}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <section className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] p-2">
        <label className="relative flex items-center">
          <Search size={12} className="pointer-events-none absolute left-2 text-muted-foreground" />
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="nome ou email"
            className="w-56 rounded-lg border border-white/10 bg-white/[0.04] py-1 pl-7 pr-2 text-[11.5px] outline-none focus:border-teal-400/40"
          />
        </label>
        <select
          value={role}
          onChange={(event) => setRole(event.target.value)}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
        >
          <option value="">Todos os papéis</option>
          <option value="admin">Administradores</option>
          <option value="member">Membros</option>
        </select>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
        >
          <option value="">Todos os estados</option>
          <option value="active">Ativos</option>
          <option value="suspended">Suspensos</option>
        </select>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Atualizar
        </button>
        <span className="ml-auto text-[11px] text-muted-foreground">{total} conta(s)</span>
      </section>

      {notice && (
        <p className="rounded-xl border border-teal-400/20 bg-teal-400/10 px-3 py-1.5 text-[11.5px] text-teal-200">{notice}</p>
      )}

      <section className="min-h-0 flex-1 overflow-auto rounded-xl border border-white/10">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-10 bg-[#12141a]/95 text-[10px] uppercase tracking-wide text-muted-foreground backdrop-blur">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium">Conta</th>
              <th className="px-3 py-1.5 text-left font-medium">Papel</th>
              <th className="px-3 py-1.5 text-left font-medium">Estado</th>
              <th className="px-3 py-1.5 text-right font-medium">Sessões</th>
              <th className="px-3 py-1.5 text-right font-medium">Logins</th>
              <th className="px-3 py-1.5 text-left font-medium">Último login</th>
              <th className="px-3 py-1.5 text-left font-medium">Criada</th>
              <th className="px-3 py-1.5 text-right font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && !loading && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">
                  Sem contas para os filtros escolhidos.
                </td>
              </tr>
            )}
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              const disabled = busy === user.id;
              return (
                <tr key={user.id} className="border-t border-white/6">
                  <td className="max-w-[260px] px-3 py-1.5">
                    <span className="block truncate font-medium" title={user.email}>
                      {user.name || "—"} {isSelf && <span className="text-[10.5px] text-muted-foreground">(você)</span>}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground" title={user.email}>
                      {user.email}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    <select
                      value={user.role}
                      disabled={disabled || isSelf}
                      onChange={(event) => void act(`Papel de ${user.email} → ${event.target.value}`, () => updateAdminUser(user.id, { role: event.target.value }), user.id)}
                      className="rounded-md border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[11.5px] disabled:opacity-50"
                    >
                      <option value="admin">admin</option>
                      <option value="member">member</option>
                    </select>
                  </td>
                  <td className="px-3 py-1.5">
                    <select
                      value={user.status}
                      disabled={disabled || isSelf}
                      onChange={(event) => void act(`Estado de ${user.email} → ${event.target.value}`, () => updateAdminUser(user.id, { status: event.target.value }), user.id)}
                      className="rounded-md border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[11.5px] disabled:opacity-50"
                    >
                      <option value="active">active</option>
                      <option value="suspended">suspended</option>
                    </select>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{user.active_sessions ?? 0}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{user.login_count ?? 0}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-[11px] text-muted-foreground">
                    {formatTime(user.last_login_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-[11px] text-muted-foreground">
                    {formatTime(user.created_at)}
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        disabled={disabled}
                        title="Terminar todas as sessões"
                        onClick={() => void act(`Sessões de ${user.email} terminadas`, () => revokeAdminUserSessions(user.id), user.id)}
                        className="rounded-md border border-white/10 bg-white/[0.04] p-1 text-muted-foreground transition hover:text-amber-200 disabled:opacity-40"
                      >
                        <ShieldOff size={12} />
                      </button>
                      <button
                        type="button"
                        disabled={disabled || isSelf}
                        title="Apagar conta"
                        onClick={() => {
                          if (!window.confirm(`Apagar a conta ${user.email}? Esta ação é irreversível.`)) return;
                          void act(`Conta ${user.email} apagada`, () => deleteAdminUser(user.id), user.id);
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] p-1 text-muted-foreground transition hover:text-rose-300 disabled:opacity-40"
                      >
                        {disabled ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/* -------------------------------------------------------------- logs */

function LogsTab({ onError }: { onError: (message: string | null) => void }) {
  const [files, setFiles] = useState<{ name: string; size: number; modified_at: string }[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [tail, setTail] = useState<LogTail | null>(null);
  const [lines, setLines] = useState(300);
  const [live, setLive] = useState(false);
  const [wrap, setWrap] = useState(true);

  const loadFiles = useCallback(async () => {
    try {
      const response = await listAdminLogs();
      setFiles([...response.files].sort((a, b) => (a.modified_at < b.modified_at ? 1 : -1)));
      onError(null);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Erro ao listar ficheiros de log.");
    }
  }, [onError]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const loadTail = useCallback(
    async (name: string, quiet = false) => {
      if (!name) return;
      try {
        setTail(await tailAdminLog(name, lines));
        onError(null);
      } catch (error) {
        if (!quiet) onError(error instanceof Error ? error.message : "Erro ao ler o ficheiro.");
      }
    },
    [lines, onError],
  );

  useEffect(() => {
    if (selected) void loadTail(selected);
  }, [loadTail, selected]);

  useEffect(() => {
    if (!live || !selected) return;
    const timer = window.setInterval(() => {
      void loadTail(selected, true);
      void loadFiles();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [live, loadFiles, loadTail, selected]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 @container">
      <section className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] p-2">
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="max-w-[280px] rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
        >
          <option value="">Escolher ficheiro…</option>
          {files.map((file) => (
            <option key={file.name} value={file.name}>
              {file.name} · {formatBytes(file.size)}
            </option>
          ))}
        </select>
        <select
          value={lines}
          onChange={(event) => setLines(Number(event.target.value))}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px]"
        >
          {[100, 300, 1000, 3000].map((value) => (
            <option key={value} value={value}>
              {value} linhas
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void loadTail(selected)}
          disabled={!selected}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09] disabled:opacity-40"
        >
          <RefreshCw size={12} /> Atualizar
        </button>
        <button
          type="button"
          onClick={() => setLive((value) => !value)}
          aria-pressed={live}
          disabled={!selected}
          className={[
            "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11.5px] transition disabled:opacity-40",
            live ? "border-teal-400/40 bg-teal-400/10 text-teal-200" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
          ].join(" ")}
        >
          {live ? <Pause size={12} /> : <Play size={12} />} {live ? "Em direto" : "Direto"}
        </button>
        <button
          type="button"
          onClick={() => setWrap((value) => !value)}
          aria-pressed={wrap}
          className={[
            "rounded-lg border px-2 py-1 text-[11.5px] transition",
            wrap ? "border-teal-400/40 bg-teal-400/10 text-teal-200" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
          ].join(" ")}
        >
          Quebrar linhas
        </button>
        {tail && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {tail.name} · {tail.total_lines.toLocaleString("pt-PT")} linhas · {formatBytes(tail.size)}
            {tail.truncated ? " (últimas apenas)" : ""}
          </span>
        )}
      </section>

      <section className="min-h-0 flex-1 overflow-auto rounded-xl border border-white/10 bg-black/40 p-2">
        {!selected ? (
          <p className="py-10 text-center text-[12px] text-muted-foreground">
            Escolha um ficheiro de log para ver as últimas linhas.
          </p>
        ) : !tail ? (
          <p className="flex items-center justify-center gap-2 py-10 text-[12px] text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> A ler…
          </p>
        ) : (
          <pre
            className={`text-[11px] leading-relaxed text-slate-300 ${wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre"}`}
          >
            {tail.lines.join("\n")}
          </pre>
        )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------- página */

function OverviewTab({ overview, onError }: { overview: AdminOverview | null; onError: (message: string | null) => void }) {
  if (!overview) {
    return (
      <p className="flex items-center justify-center gap-2 py-12 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar o estado do sistema…
      </p>
    );
  }
  const es = overview.elasticsearch;
  const errorCount = overview.events.by_level.find((row) => row.key === "error")?.count ?? 0;
  const warningCount = overview.events.by_level.find((row) => row.key === "warning")?.count ?? 0;

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-auto @container">
      <section className="grid gap-3 @xl:grid-cols-2 @5xl:grid-cols-4">
        <Metric
          icon={<Server size={11} />}
          label="API"
          value={`v${overview.api.service ? "0.4.0" : "—"}`}
          hint={`${overview.api.host} · pid ${overview.api.pid} · up ${formatDuration(overview.api.uptime_seconds)}`}
        />
        <Metric
          icon={<Database size={11} />}
          label="Elasticsearch"
          value={es.available ? `${es.version}` : "offline"}
          hint={es.available ? `${es.cluster} · ${es.status} · ${es.nodes} nó(s)` : es.error}
          tone={es.available ? "teal" : "rose"}
        />
        <Metric
          icon={<Users size={11} />}
          label="Contas"
          value={String(overview.accounts.users)}
          hint={`${overview.accounts.active_sessions} sessão(ões) ativa(s)`}
          tone="sky"
        />
        <Metric
          icon={<Activity size={11} />}
          label="Eventos (24 h)"
          value={overview.events.total.toLocaleString("pt-PT")}
          hint={`${warningCount} avisos · ${errorCount} erros`}
          tone={errorCount > 0 ? "rose" : warningCount > 0 ? "amber" : "teal"}
        />
      </section>

      <section className="grid gap-3 @3xl:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
            <Database size={11} /> Índices
          </p>
          <div className="mt-2 space-y-1.5">
            {(es.index_list ?? []).map((entry) => (
              <div key={entry.index} className="flex items-center gap-2 text-[11.5px]">
                <span className="min-w-0 flex-1 truncate font-mono" title={entry.index}>
                  {entry.index}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {entry.exists ? entry.documents.toLocaleString("pt-PT") : "—"}
                </span>
                <span className="w-16 shrink-0 text-right text-[10.5px] text-muted-foreground">{entry.exists ? entry.size : "n/d"}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Contas por papel</p>
            <div className="mt-2">
              <CountBars
                rows={overview.accounts.by_role}
                color="bg-violet-400"
                labelWidth="w-24"
                emptyLabel="Sem contas."
              />
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
              <FileText size={11} /> Ficheiros de log
            </p>
            <p className="mt-1 text-[11.5px] text-muted-foreground">
              {overview.logs.length} ficheiros em {overview.api.root}
            </p>
            <p className="mt-1 font-mono text-[10.5px] text-muted-foreground">
              {overview.logs.slice(0, 4).map((file) => file.name).join(" · ") || "—"}
            </p>
            <p className="mt-2 flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
              <Clock size={10} /> buffer de eventos em memória: {overview.api.buffer_size}/{overview.api.buffer_capacity}
            </p>
            <button
              type="button"
              onClick={() => onError(null)}
              className="mt-2 hidden"
            >
              limpar
            </button>
          </div>
        </div>
      </section>

      <section className="grid gap-3 @3xl:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Eventos por origem (24 h)</p>
          <div className="mt-2">
            <CountBars rows={overview.events.by_source} color="bg-sky-400" labelWidth="w-24" />
          </div>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Caminhos mais chamados (24 h)</p>
          <div className="mt-2">
            <CountBars rows={overview.events.top_paths} color="bg-amber-400" labelWidth="w-full" />
          </div>
        </div>
      </section>
    </div>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();
  const { windowMode } = useWindowMode();
  const isAdmin = (user?.role ?? "member") === "admin";

  const loadOverview = useCallback(async () => {
    try {
      setOverview(await getAdminOverview());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Erro ao carregar o estado do sistema.");
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void loadOverview();
  }, [isAdmin, loadOverview]);

  if (!isAdmin) {
    return (
      <div className="finder-shell flex flex-col items-center justify-center gap-2 bg-background p-8 text-center text-foreground" data-in-window={windowMode || undefined}>
        <ShieldOff size={28} className="text-amber-300" />
        <h1 className="text-lg font-semibold">Área reservada a administradores</h1>
        <p className="max-w-md text-[12.5px] text-muted-foreground">
          A sua conta ({user?.email}) tem o papel <span className="font-mono">{user?.role ?? "member"}</span>. Peça a um
          administrador para o promover — ou, com acesso ao servidor, corra:
        </p>
        <code className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-[11.5px]">
          python scripts/promote_admin.py --email {user?.email ?? "o.seu@email"}
        </code>
      </div>
    );
  }

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "Visão geral", icon: <Server size={13} /> },
    { id: "users", label: "Utilizadores", icon: <UserCog size={13} /> },
    { id: "events", label: "Eventos", icon: <Activity size={13} /> },
    { id: "logs", label: "Ficheiros de log", icon: <FileText size={13} /> },
  ];

  return (
    <div className="finder-shell flex flex-col bg-background text-foreground" data-in-window={windowMode || undefined}>
      <header className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 bg-white/[0.02] px-3 py-2 backdrop-blur-xl">
        <span className="grid h-6 w-6 place-items-center rounded-[6px] bg-gradient-to-br from-slate-200 via-slate-400 to-slate-600 text-slate-900 shadow-sm">
          <ShieldCheck size={13} />
        </span>
        <div className="min-w-0">
          <p className="text-[13px] font-semibold">Administração</p>
          <p className="truncate text-[10.5px] text-muted-foreground">
            {overview ? `${overview.api.host} · ${overview.api.platform} · Python ${overview.api.python}` : "estado do sistema e registo de eventos"}
          </p>
        </div>
        <nav className="ml-auto flex flex-wrap items-center gap-1">
          {tabs.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              aria-pressed={tab === entry.id}
              className={[
                "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11.5px] transition",
                tab === entry.id
                  ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                  : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
              ].join(" ")}
            >
              {entry.icon} {entry.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              void loadOverview();
            }}
            title="Atualizar estado"
            className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.09]"
          >
            <RefreshCw size={12} />
          </button>
        </nav>
      </header>

      {error && (
        <p className="flex shrink-0 items-center gap-2 border-b border-rose-400/20 bg-rose-400/10 px-3 py-1.5 text-[11.5px] text-rose-200">
          <XCircle size={12} /> {error}
        </p>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-3">
        {tab === "overview" && <OverviewTab overview={overview} onError={setError} />}
        {tab === "users" && <UsersTab onError={setError} currentUserId={user?.id} />}
        {tab === "events" && <EventsTab onError={setError} />}
        {tab === "logs" && <LogsTab onError={setError} />}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-white/8 px-3 py-1 text-[10.5px] text-muted-foreground">
        <CheckCircle2 size={11} className="text-teal-300" />
        <span>
          Sessão de administração · {user?.email} · eventos arquivados em <span className="font-mono">finance_events</span>
        </span>
      </footer>
    </div>
  );
}
