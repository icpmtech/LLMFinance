/**
 * Consola de operador do apoio ao cliente.
 *
 * Três colunas: a fila de conversas, a transcrição em tempo real e o dossiê do
 * visitante (conta, páginas por onde passou, tickets e registos). As mensagens
 * entram por WebSocket (`/support/ws`); os comandos (assumir, libertar, fechar,
 * tickets) vão por REST e o servidor reenvia o estado a todos os operadores.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  ClipboardList,
  Clock,
  FileText,
  Globe2,
  Inbox,
  Link2,
  Loader2,
  MessageSquare,
  Monitor,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Star,
  Ticket,
  Trash2,
  UserRound,
  Users,
  X,
  XCircle,
} from "lucide-react";

import { getToken } from "../authApi";
import {
  SESSION_STATUS_LABELS,
  TICKET_PRIORITY_LABELS,
  TICKET_STATUS_LABELS,
  claimSupportSession,
  closeSupportSession,
  createSupportTicket,
  getSupportOverview,
  getSupportSession,
  listSupportFormTemplates,
  listSupportReports,
  listSupportSessions,
  readSupportSession,
  releaseSupportSession,
  sendSupportMessage,
  setSupportOperatorStatus,
  supportOperatorSocketUrl,
  updateSupportTicket,
  type SupportEvent,
  type SupportFormField,
  type SupportFormPayload,
  type SupportFormTemplate,
  type SupportMessage,
  type SupportOperator,
  type SupportOverview,
  type SupportReportOption,
  type SupportSession,
  type SupportSessionDetail,
  type SupportTicket,
} from "../supportApi";

const TICKET_CATEGORIES = ["Conta", "Faturação", "Dados", "Sugestão", "Outro"];
const PRIORITIES = ["low", "normal", "high", "urgent"];

type Props = { onError?: (message: string | null) => void };
type SideTab = "contexto" | "tickets" | "registos";
type WsState = "connecting" | "online" | "offline";

function fmtDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fmtTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
}

function relative(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "agora";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" });
}

function initials(name?: string) {
  const parts = (name || "?").split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return (parts[0] || "?").slice(0, 2).toUpperCase();
}

function host(url?: string) {
  if (!url) return "";
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function pathOf(url?: string) {
  if (!url) return "—";
  try {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}` || "/";
  } catch {
    return url;
  }
}

function text(value: unknown, fallback = ""): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "waiting"
      ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
      : status === "active"
        ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
        : "border-white/10 bg-white/[0.04] text-muted-foreground";
  return (
    <span className={`rounded-full border px-1.5 py-px text-[10px] font-medium ${tone}`}>
      {SESSION_STATUS_LABELS[status] || status}
    </span>
  );
}

function TicketBadge({ status }: { status: string }) {
  const tone =
    status === "open"
      ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
      : status === "pending"
        ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
        : status === "resolved"
          ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
          : "border-white/10 bg-white/[0.04] text-muted-foreground";
  return (
    <span className={`rounded-full border px-1.5 py-px text-[10px] font-medium ${tone}`}>
      {TICKET_STATUS_LABELS[status] || status}
    </span>
  );
}

function StatCard({ label, value, icon, tone }: { label: string; value: number | string; icon: ReactNode; tone: string }) {
  return (
    <div className="flex min-w-[120px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <span className={`grid h-7 w-7 place-items-center rounded-lg ${tone}`}>{icon}</span>
      <div className="min-w-0">
        <p className="text-[15px] font-semibold leading-tight">{value}</p>
        <p className="truncate text-[10.5px] text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="break-words text-[11.5px] text-foreground/90">{children}</div>
    </div>
  );
}

function safeHref(value: unknown): string {
  const raw = text(value);
  if (/^https?:\/\//i.test(raw)) return raw;
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "";
}

function RichMessageCard({ message }: { message: SupportMessage }) {
  const payload = (message.payload || {}) as Record<string, unknown>;
  const kind = message.kind || "text";
  const href = safeHref(payload.url);
  const response = message.form_response;
  const fields = Array.isArray(payload.fields) ? (payload.fields as SupportFormField[]) : [];

  const kindLabel = kind === "link" ? "Link" : kind === "report" ? "Relatório" : "Formulário";

  return (
    <div className="max-w-[88%] rounded-xl border border-teal-400/25 bg-gradient-to-br from-teal-400/[0.1] to-sky-400/[0.05] px-2.5 py-2">
      <p className="mb-1 w-fit rounded-full border border-teal-400/30 bg-teal-400/10 px-1.5 py-px text-[9px] uppercase tracking-wide text-teal-200">
        {kindLabel}
        {kind === "report" && payload.free ? " · gratuito" : ""}
      </p>
      <p className="text-[12px] font-semibold">{text(payload.title, "—")}</p>
      {text(payload.description || payload.summary) ? (
        <p className="mt-0.5 whitespace-pre-wrap text-[10.5px] text-muted-foreground">
          {text(payload.description || payload.summary)}
        </p>
      ) : null}
      {kind !== "form" && href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-gradient-to-r from-teal-300 to-sky-400 px-2 py-1 text-[10.5px] font-semibold text-slate-900"
        >
          {kind === "report" ? "Abrir relatório" : "Abrir link"} <ArrowUpRight size={10} />
        </a>
      ) : null}
      {kind === "form" ? (
        <div className="mt-1.5 flex flex-col gap-1">
          {fields.map((field) => (
            <p key={field.key} className="text-[10.5px] text-muted-foreground">
              <span className="text-foreground/80">{field.label}</span>
              {field.required ? " *" : ""}
              {response?.values?.[field.key] ? (
                <span className="block whitespace-pre-wrap text-[11px] text-foreground">→ {response.values[field.key]}</span>
              ) : null}
            </p>
          ))}
          {response ? (
            <p className="mt-1 text-[10px] font-medium text-teal-200">
              Respondido {response.submitted_at ? `· ${fmtDate(response.submitted_at)}` : ""}
            </p>
          ) : (
            <p className="mt-1 text-[10px] text-amber-200/80">A aguardar resposta do visitante.</p>
          )}
        </div>
      ) : null}
      <p className="mt-1 text-[9.5px] text-muted-foreground">
        {message.author_name || "Operador"} · {fmtTime(message.created_at)}
      </p>
    </div>
  );
}

const DEFAULT_FORM_FIELDS: SupportFormField[] = [
  { key: "nome", label: "Nome", type: "text", required: true },
  { key: "email", label: "Email", type: "email", required: true },
  { key: "mensagem", label: "Como podemos ajudar?", type: "textarea", required: true },
];

export default function AdminSupportPanel({ onError }: Props) {
  const [overview, setOverview] = useState<SupportOverview | null>(null);
  const [operators, setOperators] = useState<SupportOperator[]>([]);
  const [sessions, setSessions] = useState<SupportSession[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("open");
  const [assignedFilter, setAssignedFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SupportSessionDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [internal, setInternal] = useState(false);
  const [wsState, setWsState] = useState<WsState>("connecting");
  const [typing, setTyping] = useState<string | null>(null);
  const [sideTab, setSideTab] = useState<SideTab>("contexto");
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sending, setSending] = useState(false);
  const [away, setAway] = useState(false);
  const [ticketForm, setTicketForm] = useState({ subject: "", description: "", category: TICKET_CATEGORIES[0], priority: "normal" });
  const [ticketNotes, setTicketNotes] = useState<Record<string, string>>({});
  const [composerMode, setComposerMode] = useState<"text" | "link" | "report" | "form">("text");
  const [linkDraft, setLinkDraft] = useState({ title: "", url: "", description: "" });
  const [reports, setReports] = useState<SupportReportOption[]>([]);
  const [reportQuery, setReportQuery] = useState("");
  const [reportsLoading, setReportsLoading] = useState(false);
  const [formTemplates, setFormTemplates] = useState<SupportFormTemplate[]>([]);
  const [formDraft, setFormDraft] = useState<{
    template: string;
    title: string;
    description: string;
    fields: SupportFormField[];
  }>({ template: "contacto", title: "Dados de contacto", description: "Para falarmos consigo, indique os seus dados.", fields: DEFAULT_FORM_FIELDS });

  const selectedRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const typingTimer = useRef<number | null>(null);
  const lastTypingSent = useRef(0);
  const messageEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  const report = useCallback(
    (message: string | null) => {
      onError?.(message);
    },
    [onError],
  );

  const loadOverview = useCallback(async () => {
    try {
      const data = await getSupportOverview();
      setOverview(data);
      setOperators(data.operators || []);
    } catch (error) {
      report(error instanceof Error ? error.message : "Não foi possível carregar o resumo do apoio.");
    }
  }, [report]);

  const loadSessions = useCallback(async () => {
    try {
      const data = await listSupportSessions({
        status: statusFilter,
        assigned: assignedFilter,
        q: search.trim(),
        size: 60,
      });
      setSessions(data.items);
      setTotal(data.total);
    } catch (error) {
      report(error instanceof Error ? error.message : "Não foi possível listar as conversas.");
    }
  }, [assignedFilter, report, search, statusFilter]);

  const upsertSession = useCallback((session: SupportSession) => {
    setSessions((current) => {
      const index = current.findIndex((item) => item.id === session.id);
      if (index === -1) return [session, ...current].slice(0, 100);
      const next = [...current];
      next[index] = { ...next[index], ...session };
      return next;
    });
  }, []);

  const openSession = useCallback(
    async (sessionId: string) => {
      setSelectedId(sessionId);
      setLoadingDetail(true);
      setSideTab("contexto");
      try {
        const data = await getSupportSession(sessionId);
        setDetail(data);
        upsertSession(data.session);
        if (data.session.unread_operator > 0) {
          await readSupportSession(sessionId).catch(() => null);
          setSessions((current) =>
            current.map((item) => (item.id === sessionId ? { ...item, unread_operator: 0 } : item)),
          );
        }
      } catch (error) {
        report(error instanceof Error ? error.message : "Não foi possível abrir a conversa.");
      } finally {
        setLoadingDetail(false);
      }
    },
    [report, upsertSession],
  );

  /* ------------------------------------------------------------- carregamento */
  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    setLoading(true);
    const timer = window.setTimeout(() => {
      void loadSessions().finally(() => setLoading(false));
    }, 280);
    return () => window.clearTimeout(timer);
  }, [search, statusFilter, assignedFilter, loadSessions]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadOverview();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [loadOverview]);

  useEffect(() => {
    if (messageEnd.current) {
      messageEnd.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [detail?.messages.length, selectedId]);

  /* --------------------------------------------------------------- websocket */
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setWsState("offline");
      return;
    }
    let stopped = false;
    let retry = 0;
    let timer: number | null = null;

    const connect = () => {
      if (stopped) return;
      setWsState("connecting");
      let socket: WebSocket;
      try {
        socket = new WebSocket(supportOperatorSocketUrl(token));
      } catch {
        setWsState("offline");
        return;
      }
      socketRef.current = socket;
      socket.onopen = () => {
        retry = 0;
        setWsState("online");
      };
      socket.onmessage = (event) => {
        let payload: {
          type?: string;
          message?: SupportMessage;
          session?: SupportSession;
          ticket?: SupportTicket;
          operators_online?: number;
          actor?: string;
          name?: string;
          session_id?: string;
        } | null = null;
        // `form.submitted` traz a mesma mensagem atualizada em `message`.
        try {
          payload = JSON.parse(event.data as string);
        } catch {
          return;
        }
        if (!payload || !payload.type) return;
        if (payload.type === "ready") {
          setWsState("online");
          return;
        }
        if (payload.type === "presence") {
          void loadOverview();
          return;
        }
        if (payload.type === "message.created" && payload.message) {
          const message = payload.message;
          if (payload.session) upsertSession(payload.session);
          if (selectedRef.current === message.session_id) {
            setDetail((current) => {
              if (!current) return current;
              const index = current.messages.findIndex(
                (item) => item.id === message.id || (!!message.client_id && item.client_id === message.client_id),
              );
              const messages =
                index >= 0
                  ? current.messages.map((item, position) => (position === index ? message : item))
                  : [...current.messages, message];
              return {
                ...current,
                messages,
                session: payload.session ? { ...current.session, ...payload.session } : current.session,
              };
            });
            if (message.author_type === "visitor") {
              void readSupportSession(message.session_id).catch(() => null);
            }
          }
          setTyping(null);
          return;
        }
        if (payload.type === "form.submitted" && payload.message) {
          const message = payload.message;
          if (payload.session) upsertSession(payload.session);
          if (selectedRef.current === message.session_id) {
            setDetail((current) =>
              current
                ? {
                    ...current,
                    messages: current.messages.map((item) => (item.id === message.id ? message : item)),
                    session: payload.session ? { ...current.session, ...payload.session } : current.session,
                  }
                : current,
            );
          }
          return;
        }
        if ((payload.type === "session.updated" || payload.type === "session.closed") && payload.session) {
          const session = payload.session;
          upsertSession(session);
          if (selectedRef.current === session.id) {
            setDetail((current) => (current ? { ...current, session: { ...current.session, ...session } } : current));
          }
          return;
        }
        if (payload.type === "ticket.created" && payload.ticket) {
          if (selectedRef.current === payload.ticket.session_id) {
            const ticket = payload.ticket;
            setDetail((current) => {
              if (!current) return current;
              const exists = current.tickets.some((item) => item.id === ticket.id);
              return {
                ...current,
                tickets: exists ? current.tickets.map((item) => (item.id === ticket.id ? ticket : item)) : [ticket, ...current.tickets],
              };
            });
          }
          return;
        }
        if (payload.type === "typing" && payload.actor === "visitor" && payload.session_id === selectedRef.current) {
          setTyping(payload.name || "Visitante");
          if (typingTimer.current) window.clearTimeout(typingTimer.current);
          typingTimer.current = window.setTimeout(() => setTyping(null), 4000);
        }
      };
      socket.onclose = () => {
        setWsState("offline");
        socketRef.current = null;
        if (stopped) return;
        retry += 1;
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry, 15000));
      };
      socket.onerror = () => {
        socket.close();
      };
    };

    connect();
    const ping = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
    }, 25000);

    return () => {
      stopped = true;
      window.clearInterval(ping);
      if (timer) window.clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [loadOverview, upsertSession]);

  /* ---------------------------------------------------------------- comandos */
  const wsSend = useCallback((payload: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }, []);

  const act = useCallback(
    async (action: () => Promise<{ session: SupportSession }>) => {
      try {
        const result = await action();
        upsertSession(result.session);
        setDetail((current) => (current ? { ...current, session: { ...current.session, ...result.session } } : current));
        void loadOverview();
      } catch (error) {
        report(error instanceof Error ? error.message : "A ação falhou.");
      }
    },
    [loadOverview, report, upsertSession],
  );

  const sendMessage = useCallback(async () => {
    const body = draft.trim();
    if (!body || !detail) return;
    const sessionId = detail.session.id;
    const clientId = `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const optimistic: SupportMessage = {
      id: clientId,
      client_id: clientId,
      session_id: sessionId,
      author_type: internal ? "note" : "operator",
      author_id: "me",
      author_name: "Eu",
      body,
      kind: "text",
      payload: {},
      form_response: null,
      internal,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setDetail((current) => (current ? { ...current, messages: [...current.messages, optimistic] } : current));
    setDraft("");
    setSending(true);
    const sent = wsSend({
      type: "message",
      session_id: sessionId,
      body,
      client_id: clientId,
      internal,
    });
    if (!sent) {
      try {
        const result = await sendSupportMessage(sessionId, body, { internal, clientId });
        setDetail((current) => {
          if (!current) return current;
          return {
            ...current,
            messages: current.messages.map((item) => (item.client_id === clientId ? result.message : item)),
            session: { ...current.session, ...result.session },
          };
        });
      } catch (error) {
        setDetail((current) =>
          current
            ? {
                ...current,
                messages: current.messages.map((item) =>
                  item.client_id === clientId ? { ...item, pending: false, body: `${item.body} (não enviada)` } : item,
                ),
              }
            : current,
        );
        report(error instanceof Error ? error.message : "Não foi possível enviar a mensagem.");
      }
    }
    setSending(false);
  }, [detail, draft, internal, report, wsSend]);

  const sendRich = useCallback(
    async (kind: "link" | "report" | "form", payload: Record<string, unknown>) => {
      if (!detail) return;
      const sessionId = detail.session.id;
      const clientId = `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const optimistic: SupportMessage = {
        id: clientId,
        client_id: clientId,
        session_id: sessionId,
        author_type: "operator",
        author_id: "me",
        author_name: "Eu",
        body: text(payload.title),
        kind,
        payload,
        form_response: null,
        internal: false,
        created_at: new Date().toISOString(),
        pending: true,
      };
      setDetail((current) => (current ? { ...current, messages: [...current.messages, optimistic] } : current));
      const sent = wsSend({ type: "message", session_id: sessionId, kind, payload, client_id: clientId });
      if (!sent) {
        try {
          const result = await sendSupportMessage(sessionId, "", { kind, payload, clientId });
          setDetail((current) => {
            if (!current) return current;
            const index = current.messages.findIndex((item) => item.client_id === clientId);
            const messages =
              index >= 0
                ? current.messages.map((item, position) => (position === index ? result.message : item))
                : [...current.messages, result.message];
            return { ...current, messages, session: { ...current.session, ...result.session } };
          });
        } catch (error) {
          setDetail((current) =>
            current
              ? {
                  ...current,
                  messages: current.messages.map((item) =>
                    item.client_id === clientId ? { ...item, pending: false, body: `${item.body} (não enviado)` } : item,
                  ),
                }
              : current,
          );
          report(error instanceof Error ? error.message : "Não foi possível enviar o cartão.");
          return;
        }
      }
      setComposerMode("text");
    },
    [detail, report, wsSend],
  );

  const loadReports = useCallback(
    async (q: string) => {
      setReportsLoading(true);
      try {
        const data = await listSupportReports(q.trim());
        setReports(data.items);
      } catch (error) {
        report(error instanceof Error ? error.message : "Não foi possível carregar os relatórios.");
      } finally {
        setReportsLoading(false);
      }
    },
    [report],
  );

  useEffect(() => {
    if (composerMode !== "report") return;
    const timer = window.setTimeout(() => {
      void loadReports(reportQuery);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [composerMode, loadReports, reportQuery]);

  useEffect(() => {
    if (composerMode !== "form" || formTemplates.length) return;
    void listSupportFormTemplates()
      .then((data) => setFormTemplates(data.templates || []))
      .catch((error) => report(error instanceof Error ? error.message : "Não foi possível carregar os modelos de formulário."));
  }, [composerMode, formTemplates.length, report]);

  const chooseTemplate = useCallback(
    (templateId: string) => {
      if (templateId === "custom") {
        setFormDraft({ template: "custom", title: "Formulário", description: "", fields: [...DEFAULT_FORM_FIELDS] });
        return;
      }
      const template = formTemplates.find((item) => item.id === templateId);
      if (!template) return;
      setFormDraft({
        template: template.id,
        title: template.title,
        description: template.description,
        fields: template.fields.map((field) => ({ ...field, options: [...(field.options || [])] })),
      });
    },
    [formTemplates],
  );

  const submitLink = useCallback(async () => {
    const url = safeHref(linkDraft.url);
    if (!url) {
      report("Indique um endereço http(s) válido.");
      return;
    }
    await sendRich("link", {
      url,
      title: linkDraft.title.trim() || url,
      description: linkDraft.description.trim(),
    });
    setLinkDraft({ title: "", url: "", description: "" });
  }, [linkDraft, report, sendRich]);

  const submitReport = useCallback(
    async (item: SupportReportOption) => {
      const url = safeHref(item.url);
      if (!url) {
        report("Este relatório não tem um endereço público.");
        return;
      }
      await sendRich("report", {
        report_id: item.report_id,
        title: item.title,
        summary: item.summary || item.subtitle,
        url,
        free: item.free,
        area: item.area,
      });
    },
    [report, sendRich],
  );

  const submitFormMessage = useCallback(async () => {
    const fields = formDraft.fields.filter((field) => field.label.trim());
    if (!fields.length) {
      report("Adicione pelo menos um campo ao formulário.");
      return;
    }
    const payload: Omit<SupportFormPayload, "form_id"> & { form_id?: string } = {
      title: formDraft.title.trim() || "Formulário de apoio",
      description: formDraft.description.trim(),
      submit_label: "Enviar",
      template: formDraft.template,
      fields: fields.map((field) => ({
        ...field,
        key: field.key || "",
        label: field.label.trim(),
        options: field.options || [],
      })),
    };
    await sendRich("form", payload as unknown as Record<string, unknown>);
  }, [formDraft, report, sendRich]);

  const addTicket = useCallback(async () => {
    if (!detail) return;
    if (ticketForm.subject.trim().length < 3) {
      report("Indique um assunto com pelo menos 3 caracteres.");
      return;
    }
    try {
      const result = await createSupportTicket(detail.session.id, ticketForm);
      setDetail((current) =>
        current ? { ...current, tickets: [result.ticket, ...current.tickets] } : current,
      );
      setTicketForm({ subject: "", description: "", category: TICKET_CATEGORIES[0], priority: "normal" });
      setSideTab("tickets");
      report(null);
    } catch (error) {
      report(error instanceof Error ? error.message : "Não foi possível abrir o ticket.");
    }
  }, [detail, report, ticketForm]);

  const patchTicket = useCallback(
    async (ticket: SupportTicket, patch: { status?: string; priority?: string; note?: string }) => {
      try {
        const result = await updateSupportTicket(ticket.id, patch);
        setDetail((current) =>
          current
            ? { ...current, tickets: current.tickets.map((item) => (item.id === ticket.id ? result.ticket : item)) }
            : current,
        );
        if (!patch.note) report(null);
      } catch (error) {
        report(error instanceof Error ? error.message : "Não foi possível atualizar o ticket.");
      }
    },
    [report],
  );

  const toggleAway = useCallback(async () => {
    const next = !away;
    setAway(next);
    try {
      await setSupportOperatorStatus(next ? "away" : "online");
      wsSend({ type: "status", status: next ? "away" : "online" });
      void loadOverview();
    } catch (error) {
      setAway(!next);
      report(error instanceof Error ? error.message : "Não foi possível alterar o estado.");
    }
  }, [away, loadOverview, report, wsSend]);

  const account = detail?.account || null;
  const subscription = (account?.subscription || {}) as Record<string, unknown>;
  const context = (detail?.session.context || {}) as Record<string, unknown>;
  const visitor = (detail?.session.visitor || {}) as Record<string, unknown>;
  const pages = detail?.session.pages || [];
  const events = detail?.events || [];
  const tickets = detail?.tickets || [];

  const counts = useMemo(
    () => ({
      waiting: overview?.waiting ?? 0,
      active: overview?.active ?? 0,
      open: overview?.open ?? 0,
      unread: overview?.unread ?? 0,
      tickets: overview?.tickets_open ?? 0,
      today: overview?.today ?? 0,
    }),
    [overview],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <StatCard label="À espera" value={counts.waiting} icon={<Clock size={14} />} tone="bg-amber-400/10 text-amber-200" />
        <StatCard label="Em curso" value={counts.active} icon={<MessageSquare size={14} />} tone="bg-teal-400/10 text-teal-200" />
        <StatCard label="Não lidas" value={counts.unread} icon={<Inbox size={14} />} tone="bg-sky-400/10 text-sky-200" />
        <StatCard label="Tickets abertos" value={counts.tickets} icon={<Ticket size={14} />} tone="bg-fuchsia-400/10 text-fuchsia-200" />
        <StatCard label="Hoje" value={counts.today} icon={<Activity size={14} />} tone="bg-white/[0.04] text-slate-300" />
        <StatCard
          label={away ? "Operador ausente" : "Operador disponível"}
          value={overview?.operators_online ?? 0}
          icon={<Users size={14} />}
          tone={away ? "bg-amber-400/10 text-amber-200" : "bg-emerald-400/10 text-emerald-200"}
        />
        <div className="ml-auto flex items-center gap-1.5">
          <span
            className={`flex items-center gap-1 rounded-full border px-2 py-1 text-[10.5px] ${
              wsState === "online"
                ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                : wsState === "connecting"
                  ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
                  : "border-rose-400/30 bg-rose-400/10 text-rose-200"
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {wsState === "online" ? "Tempo real" : wsState === "connecting" ? "A ligar…" : "Sem tempo real"}
          </span>
          <button
            type="button"
            onClick={() => {
              void loadOverview();
              void loadSessions();
            }}
            className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.09]"
            title="Atualizar"
          >
            <RefreshCw size={12} />
          </button>
          <button
            type="button"
            onClick={toggleAway}
            className={`rounded-lg border px-2 py-1 text-[10.5px] transition ${
              away
                ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
                : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]"
            }`}
          >
            {away ? "Voltar online" : "Ficar ausente"}
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden xl:grid-cols-[290px_minmax(0,1fr)_320px]">
        {/* ------------------------------------------------------------- fila */}
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          <div className="flex shrink-0 flex-col gap-1.5 border-b border-white/8 p-2">
            <div className="flex items-center gap-1">
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Nome, email, página…"
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] outline-none focus:border-teal-400/40"
              />
              <span className="rounded-md bg-white/[0.04] px-1.5 py-1 text-[10px] text-muted-foreground">{total}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {[
                ["open", "Abertas"],
                ["waiting", "À espera"],
                ["active", "Em curso"],
                ["closed", "Fechadas"],
                ["", "Todas"],
              ].map(([value, label]) => (
                <button
                  key={value || "all"}
                  type="button"
                  onClick={() => setStatusFilter(value)}
                  className={`rounded-md border px-1.5 py-0.5 text-[10px] transition ${
                    statusFilter === value
                      ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {[
                ["", "Todas"],
                ["me", "Minhas"],
                ["unassigned", "Sem operador"],
              ].map(([value, label]) => (
                <button
                  key={value || "all-assigned"}
                  type="button"
                  onClick={() => setAssignedFilter(value)}
                  className={`rounded-md border px-1.5 py-0.5 text-[10px] transition ${
                    assignedFilter === value
                      ? "border-sky-400/40 bg-sky-400/10 text-sky-200"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {loading && !sessions.length ? (
              <p className="flex items-center gap-2 p-3 text-[11.5px] text-muted-foreground">
                <Loader2 size={12} className="animate-spin" /> A carregar conversas…
              </p>
            ) : sessions.length === 0 ? (
              <p className="p-3 text-[11.5px] text-muted-foreground">Sem conversas neste filtro.</p>
            ) : (
              sessions.map((session) => {
                const active = session.id === selectedId;
                const lastPage = pathOf(text(session.context.url));
                return (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => void openSession(session.id)}
                    className={`mb-1 flex w-full items-start gap-2 rounded-lg border px-2 py-1.5 text-left transition ${
                      active
                        ? "border-teal-400/40 bg-teal-400/10"
                        : "border-transparent hover:border-white/10 hover:bg-white/[0.04]"
                    }`}
                  >
                    <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-600 to-slate-800 text-[10px] font-semibold text-slate-100">
                      {initials(session.visitor_name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1">
                        <span className="truncate text-[12px] font-medium">{session.visitor_name || "Visitante"}</span>
                        {session.online ? <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" title="Online" /> : null}
                        {session.unread_operator > 0 ? (
                          <span className="ml-auto grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[9.5px] font-bold text-white">
                            {session.unread_operator}
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                        <Globe2 size={9} />
                        <span className="truncate">{lastPage}</span>
                      </span>
                      <span className="mt-0.5 flex items-center gap-1">
                        <StatusBadge status={session.status} />
                        {session.assigned_operator_name ? (
                          <span className="truncate text-[9.5px] text-muted-foreground">{session.assigned_operator_name}</span>
                        ) : null}
                        <span className="ml-auto shrink-0 text-[9.5px] text-muted-foreground">
                          {relative(session.last_message_at || session.created_at)}
                        </span>
                      </span>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* --------------------------------------------------------- conversa */}
        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          {!detail ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
              <MessageSquare size={26} />
              <p className="text-[12.5px]">Escolha uma conversa à esquerda para ver a transcrição.</p>
              {loadingDetail ? <Loader2 size={14} className="animate-spin" /> : null}
            </div>
          ) : (
            <>
              <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 px-3 py-2">
                <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-teal-400/80 to-sky-500/80 text-[11px] font-bold text-slate-900">
                  {initials(detail.session.visitor_name)}
                </span>
                <div className="min-w-0">
                  <p className="flex items-center gap-1 text-[13px] font-semibold">
                    {detail.session.visitor_name || "Visitante"}
                    {detail.session.online ? (
                      <span className="rounded-full bg-emerald-400/15 px-1.5 py-px text-[9.5px] text-emerald-200">online</span>
                    ) : (
                      <span className="rounded-full bg-white/[0.05] px-1.5 py-px text-[9.5px] text-muted-foreground">offline</span>
                    )}
                  </p>
                  <p className="truncate text-[10.5px] text-muted-foreground">
                    {detail.session.visitor_email || "sem email"} · iniciada {fmtDate(detail.session.created_at)}
                  </p>
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-1">
                  <StatusBadge status={detail.session.status} />
                  {detail.session.rating ? (
                    <span className="flex items-center gap-0.5 rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-px text-[10px] text-amber-200">
                      <Star size={9} /> {detail.session.rating}/5
                    </span>
                  ) : null}
                  {detail.session.status !== "closed" ? (
                    <>
                      {!detail.session.assigned_to_me ? (
                        <button
                          type="button"
                          onClick={() => void act(() => claimSupportSession(detail.session.id))}
                          className="rounded-md border border-teal-400/30 bg-teal-400/10 px-2 py-1 text-[10.5px] text-teal-200 hover:bg-teal-400/20"
                        >
                          Assumir
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void act(() => releaseSupportSession(detail.session.id))}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/[0.08]"
                        >
                          Libertar
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void act(() => closeSupportSession(detail.session.id))}
                        className="rounded-md border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-[10.5px] text-rose-200 hover:bg-rose-400/20"
                      >
                        Fechar
                      </button>
                    </>
                  ) : null}
                </div>
              </header>

              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <div className="flex flex-col gap-2">
                  {detail.messages.length === 0 ? (
                    <p className="text-center text-[11.5px] text-muted-foreground">Ainda não há mensagens.</p>
                  ) : (
                    detail.messages.map((message) => {
                      if (message.author_type === "system") {
                        return (
                          <p key={message.id} className="mx-auto max-w-[85%] rounded-full bg-white/[0.05] px-2.5 py-1 text-center text-[10.5px] text-muted-foreground">
                            {message.body}
                          </p>
                        );
                      }
                      if (message.kind && message.kind !== "text") {
                        return <RichMessageCard key={message.id} message={message} />;
                      }
                      const mine = message.author_type === "operator" || message.author_type === "note";
                      const note = message.author_type === "note" || message.internal;
                      return (
                        <div key={message.id} className={`flex max-w-[85%] flex-col gap-0.5 ${mine ? "self-end items-end" : "self-start items-start"}`}>
                          <span className="px-1 text-[10px] text-muted-foreground">
                            {message.author_name || (mine ? "Operador" : "Visitante")} · {fmtTime(message.created_at)}
                            {message.pending ? " · a enviar…" : ""}
                          </span>
                          <div
                            className={`whitespace-pre-wrap break-words rounded-xl border px-2.5 py-1.5 text-[12px] ${
                              note
                                ? "border-amber-400/30 bg-amber-400/10 text-amber-100"
                                : mine
                                  ? "border-teal-400/20 bg-teal-400/15 text-teal-50"
                                  : "border-white/10 bg-white/[0.05] text-foreground"
                            }`}
                          >
                            {note ? <span className="mb-0.5 block text-[9.5px] uppercase tracking-wide text-amber-300">nota interna</span> : null}
                            {message.body}
                          </div>
                        </div>
                      );
                    })
                  )}
                  <div ref={messageEnd} />
                </div>
              </div>

              {typing ? <p className="px-3 pb-1 text-[10.5px] text-teal-200">{typing} está a escrever…</p> : null}

              {detail.session.status !== "closed" ? (
                <div className="shrink-0 border-t border-white/8 p-2">
                  <div className="mb-1.5 flex flex-wrap items-center gap-1">
                    {(
                      [
                        ["text", "Mensagem", <MessageSquare key="m" size={11} />],
                        ["link", "Link", <Link2 key="l" size={11} />],
                        ["report", "Relatório", <FileText key="r" size={11} />],
                        ["form", "Formulário", <ClipboardList key="f" size={11} />],
                      ] as [typeof composerMode, string, ReactNode][]
                    ).map(([value, label, icon]) => (
                      <button
                        key={String(value)}
                        type="button"
                        onClick={() => setComposerMode(value as typeof composerMode)}
                        className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] transition ${
                          composerMode === value
                            ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                            : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
                        }`}
                      >
                        {icon} {label}
                      </button>
                    ))}
                  </div>

                  {composerMode === "text" ? (
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        void sendMessage();
                      }}
                    >
                      <div className="flex items-end gap-1.5">
                        <textarea
                          value={draft}
                          onChange={(event) => {
                            setDraft(event.target.value);
                            const now = Date.now();
                            if (event.target.value.trim() && now - lastTypingSent.current > 2000) {
                              lastTypingSent.current = now;
                              wsSend({ type: "typing", session_id: detail.session.id });
                            }
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !event.shiftKey) {
                              event.preventDefault();
                              void sendMessage();
                            }
                          }}
                          rows={2}
                          placeholder={internal ? "Nota interna (o visitante não vê)…" : "Escreva a resposta…"}
                          className={`max-h-32 min-h-[44px] flex-1 resize-y rounded-lg border px-2.5 py-1.5 text-[12px] outline-none ${
                            internal
                              ? "border-amber-400/30 bg-amber-400/[0.06] focus:border-amber-400/60"
                              : "border-white/10 bg-black/30 focus:border-teal-400/40"
                          }`}
                        />
                        <button
                          type="submit"
                          disabled={sending || !draft.trim()}
                          className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-teal-300 to-sky-400 text-slate-900 disabled:opacity-40"
                          title="Enviar"
                        >
                          <Send size={15} />
                        </button>
                      </div>
                      <label className="mt-1 flex w-fit cursor-pointer items-center gap-1 text-[10.5px] text-muted-foreground">
                        <input type="checkbox" checked={internal} onChange={(event) => setInternal(event.target.checked)} />
                        Nota interna
                      </label>
                    </form>
                  ) : null}

                  {composerMode === "link" ? (
                    <div className="flex flex-col gap-1">
                      <input
                        value={linkDraft.url}
                        onChange={(event) => setLinkDraft((current) => ({ ...current, url: event.target.value }))}
                        placeholder="https://exemplo.pt/pagina"
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                      />
                      <input
                        value={linkDraft.title}
                        onChange={(event) => setLinkDraft((current) => ({ ...current, title: event.target.value }))}
                        placeholder="Título do link (opcional)"
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                      />
                      <input
                        value={linkDraft.description}
                        onChange={(event) => setLinkDraft((current) => ({ ...current, description: event.target.value }))}
                        placeholder="Descrição curta (opcional)"
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                      />
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => void submitLink()}
                          className="rounded-md bg-gradient-to-r from-teal-300 to-sky-400 px-2 py-1 text-[10.5px] font-semibold text-slate-900"
                        >
                          Enviar link
                        </button>
                        <button
                          type="button"
                          onClick={() => setComposerMode("text")}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10.5px] text-muted-foreground"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {composerMode === "report" ? (
                    <div className="flex max-h-60 flex-col gap-1">
                      <div className="flex gap-1">
                        <div className="relative min-w-0 flex-1">
                          <Search size={11} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                          <input
                            value={reportQuery}
                            onChange={(event) => setReportQuery(event.target.value)}
                            placeholder="Pesquisar relatórios…"
                            className="w-full rounded-md border border-white/10 bg-black/30 py-1 pl-6 pr-2 text-[11px] outline-none focus:border-teal-400/40"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => setComposerMode("text")}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 text-[10.5px] text-muted-foreground"
                          title="Fechar"
                        >
                          <X size={11} />
                        </button>
                      </div>
                      <div className="min-h-0 flex-1 overflow-y-auto">
                        {reportsLoading ? (
                          <p className="flex items-center gap-1 p-1 text-[10.5px] text-muted-foreground">
                            <Loader2 size={10} className="animate-spin" /> A carregar relatórios…
                          </p>
                        ) : reports.length === 0 ? (
                          <p className="p-1 text-[10.5px] text-muted-foreground">Sem relatórios publicados.</p>
                        ) : (
                          reports.map((item) => (
                            <div
                              key={`${item.report_id}-${item.title}`}
                              className="mb-1 flex items-start gap-1 rounded-md border border-white/8 bg-white/[0.03] px-1.5 py-1"
                            >
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-[11px] font-medium">{item.title}</p>
                                <p className="truncate text-[9.5px] text-muted-foreground">
                                  {item.area || item.kind_label} · {item.free ? "gratuito" : `${item.price} €`}
                                </p>
                              </div>
                              <button
                                type="button"
                                onClick={() => void submitReport(item)}
                                className="shrink-0 rounded-md border border-teal-400/30 bg-teal-400/10 px-1.5 py-0.5 text-[10px] text-teal-200"
                              >
                                Enviar
                              </button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  ) : null}

                  {composerMode === "form" ? (
                    <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                      <div className="flex gap-1">
                        <select
                          value={formDraft.template}
                          onChange={(event) => chooseTemplate(event.target.value)}
                          className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1.5 py-1 text-[10.5px] outline-none"
                        >
                          {formTemplates.map((template) => (
                            <option key={template.id} value={template.id}>
                              {template.title}
                            </option>
                          ))}
                          <option value="custom">Personalizado</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => setComposerMode("text")}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 text-[10.5px] text-muted-foreground"
                          title="Fechar"
                        >
                          <X size={11} />
                        </button>
                      </div>
                      <input
                        value={formDraft.title}
                        onChange={(event) => setFormDraft((current) => ({ ...current, title: event.target.value }))}
                        placeholder="Título do formulário"
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                      />
                      <input
                        value={formDraft.description}
                        onChange={(event) => setFormDraft((current) => ({ ...current, description: event.target.value }))}
                        placeholder="Descrição (opcional)"
                        className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                      />
                      <div className="flex flex-col gap-1">
                        {formDraft.fields.map((field, index) => (
                          <div key={`${field.key}-${index}`} className="rounded-md border border-white/8 bg-white/[0.03] p-1">
                            <div className="flex items-center gap-1">
                              <input
                                value={field.label}
                                onChange={(event) =>
                                  setFormDraft((current) => ({
                                    ...current,
                                    fields: current.fields.map((item, position) =>
                                      position === index ? { ...item, label: event.target.value } : item,
                                    ),
                                  }))
                                }
                                placeholder="Etiqueta do campo"
                                className="min-w-0 flex-1 rounded border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10.5px] outline-none"
                              />
                              <select
                                value={field.type}
                                onChange={(event) =>
                                  setFormDraft((current) => ({
                                    ...current,
                                    fields: current.fields.map((item, position) =>
                                      position === index ? { ...item, type: event.target.value } : item,
                                    ),
                                  }))
                                }
                                className="w-20 rounded border border-white/10 bg-black/30 px-1 py-0.5 text-[10px] outline-none"
                              >
                                {["text", "email", "tel", "textarea", "select", "number", "date"].map((type) => (
                                  <option key={type} value={type}>
                                    {type}
                                  </option>
                                ))}
                              </select>
                              <label className="flex items-center gap-0.5 text-[9.5px] text-muted-foreground">
                                <input
                                  type="checkbox"
                                  checked={field.required}
                                  onChange={(event) =>
                                    setFormDraft((current) => ({
                                      ...current,
                                      fields: current.fields.map((item, position) =>
                                        position === index ? { ...item, required: event.target.checked } : item,
                                      ),
                                    }))
                                  }
                                />
                                obrig.
                              </label>
                              <button
                                type="button"
                                onClick={() =>
                                  setFormDraft((current) => ({
                                    ...current,
                                    fields: current.fields.filter((_, position) => position !== index),
                                  }))
                                }
                                className="rounded p-0.5 text-rose-300/80 hover:bg-rose-400/10"
                                title="Remover campo"
                              >
                                <Trash2 size={10} />
                              </button>
                            </div>
                            {field.type === "select" ? (
                              <input
                                value={(field.options || []).join(", ")}
                                onChange={(event) =>
                                  setFormDraft((current) => ({
                                    ...current,
                                    fields: current.fields.map((item, position) =>
                                      position === index
                                        ? {
                                            ...item,
                                            options: event.target.value
                                              .split(",")
                                              .map((option) => option.trim())
                                              .filter(Boolean),
                                          }
                                        : item,
                                    ),
                                  }))
                                }
                                placeholder="Opções separadas por vírgulas"
                                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10px] outline-none"
                              />
                            ) : null}
                          </div>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          setFormDraft((current) => ({
                            ...current,
                            fields: [...current.fields, { key: "", label: "", type: "text", required: false, options: [] }],
                          }))
                        }
                        className="flex w-fit items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >
                        <Plus size={10} /> Campo
                      </button>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => void submitFormMessage()}
                          className="rounded-md bg-gradient-to-r from-teal-300 to-sky-400 px-2 py-1 text-[10.5px] font-semibold text-slate-900"
                        >
                          Enviar formulário
                        </button>
                        <button
                          type="button"
                          onClick={() => setComposerMode("text")}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[10.5px] text-muted-foreground"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="shrink-0 border-t border-white/8 px-3 py-2 text-[11px] text-muted-foreground">
                  Conversa fechada{detail.session.closed_at ? ` em ${fmtDate(detail.session.closed_at)}` : ""}.
                </p>
              )}
            </>
          )}
        </section>

        {/* -------------------------------------------------------- dossiê */}
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          <nav className="flex shrink-0 gap-1 border-b border-white/8 p-1.5">
            {[
              ["contexto", "Contexto"],
              ["tickets", `Tickets${tickets.length ? ` (${tickets.length})` : ""}`],
              ["registos", "Registos"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setSideTab(value as SideTab)}
                className={`flex-1 rounded-md border px-1.5 py-1 text-[10.5px] transition ${
                  sideTab === value
                    ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                    : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.07]"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {!detail ? (
              <p className="p-2 text-[11.5px] text-muted-foreground">Sem conversa selecionada.</p>
            ) : sideTab === "contexto" ? (
              <div className="flex flex-col gap-2">
                <section className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
                  <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold">
                    <UserRound size={12} /> Visitante
                  </p>
                  <div className="grid grid-cols-1 gap-1.5">
                    <Field label="Nome">{detail.session.visitor_name || "—"}</Field>
                    <Field label="Email">{detail.session.visitor_email || "—"}</Field>
                    <Field label="Organização">{text(visitor.organization, "—")}</Field>
                    <Field label="Telefone">{text(visitor.phone, "—")}</Field>
                    <Field label="ID">{detail.session.visitor_id}</Field>
                  </div>
                </section>

                {account ? (
                  <section className="rounded-lg border border-teal-400/20 bg-teal-400/[0.05] p-2">
                    <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold text-teal-200">
                      <ShieldCheck size={12} /> Conta na plataforma
                    </p>
                    <div className="grid grid-cols-1 gap-1.5">
                      <Field label="Conta">{text(account.name)} · {text(account.email)}</Field>
                      <Field label="Papel / estado">
                        {text(account.role, "member")} · {text(account.status, "—")}
                      </Field>
                      <Field label="Organização / cargo">
                        {text(account.organization, "—")} · {text(account.title, "—")}
                      </Field>
                      <Field label="Plano">
                        {text(subscription.plan_id, "—")} · {text(subscription.status, "sem subscrição")}
                      </Field>
                      <Field label="Último início de sessão">{fmtDate(text(account.last_login_at))}</Field>
                    </div>
                  </section>
                ) : null}

                <section className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
                  <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold">
                    <Monitor size={12} /> Onde está
                  </p>
                  <div className="grid grid-cols-1 gap-1.5">
                    <Field label="Página atual">
                      {text(context.url) ? (
                        <a
                          href={text(context.url)}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-0.5 break-all text-sky-300 hover:underline"
                        >
                          {host(text(context.url))}
                          {pathOf(text(context.url))}
                          <ArrowUpRight size={9} />
                        </a>
                      ) : (
                        "—"
                      )}
                    </Field>
                    <Field label="Título">{text(context.title, "—")}</Field>
                    <Field label="Referrer">{text(context.referrer) ? host(text(context.referrer)) : "direto"}</Field>
                    <Field label="IP">{text(context.ip, "—")}</Field>
                    <Field label="Dispositivo">
                      {text(context.device, "—")} · {text((context.screen as Record<string, unknown>)?.width, "?")}×
                      {text((context.screen as Record<string, unknown>)?.height, "?")}
                    </Field>
                    <Field label="Idioma / fuso">{text(context.locale, "—")} · {text(context.timezone, "—")}</Field>
                    <Field label="Entrada">
                      {text((context.utm as Record<string, unknown>)?.utm_source) ||
                        text((context.utm as Record<string, unknown>)?.utm_campaign) ||
                        "orgânica"}
                    </Field>
                    <Field label="Browser">
                      <span className="line-clamp-3">{text(context.user_agent, "—")}</span>
                    </Field>
                  </div>
                </section>

                <section className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
                  <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold">
                    <Globe2 size={12} /> Páginas por onde passou
                  </p>
                  {pages.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground">Sem navegação registada.</p>
                  ) : (
                    <ul className="flex flex-col gap-1">
                      {pages.slice(0, 14).map((page, index) => (
                        <li key={`${page.url}-${index}`} className="flex items-start gap-1 text-[10.5px]">
                          <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-teal-300/70" />
                          <span className="min-w-0 flex-1">
                            <a href={page.url} target="_blank" rel="noreferrer" className="break-all text-sky-300 hover:underline">
                              {pathOf(page.url)}
                            </a>
                            <span className="block text-[9.5px] text-muted-foreground">{fmtTime(page.at)}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            ) : sideTab === "tickets" ? (
              <div className="flex flex-col gap-2">
                <section className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
                  <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold">
                    <Ticket size={12} /> Abrir ticket
                  </p>
                  <div className="flex flex-col gap-1.5">
                    <input
                      value={ticketForm.subject}
                      onChange={(event) => setTicketForm((current) => ({ ...current, subject: event.target.value }))}
                      placeholder="Assunto"
                      className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                    />
                    <div className="flex gap-1">
                      <select
                        value={ticketForm.category}
                        onChange={(event) => setTicketForm((current) => ({ ...current, category: event.target.value }))}
                        className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1.5 py-1 text-[11px] outline-none"
                      >
                        {TICKET_CATEGORIES.map((category) => (
                          <option key={category} value={category}>
                            {category}
                          </option>
                        ))}
                      </select>
                      <select
                        value={ticketForm.priority}
                        onChange={(event) => setTicketForm((current) => ({ ...current, priority: event.target.value }))}
                        className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1.5 py-1 text-[11px] outline-none"
                      >
                        {PRIORITIES.map((priority) => (
                          <option key={priority} value={priority}>
                            {TICKET_PRIORITY_LABELS[priority]}
                          </option>
                        ))}
                      </select>
                    </div>
                    <textarea
                      value={ticketForm.description}
                      onChange={(event) => setTicketForm((current) => ({ ...current, description: event.target.value }))}
                      rows={3}
                      placeholder="Descrição"
                      className="rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] outline-none focus:border-teal-400/40"
                    />
                    <button
                      type="button"
                      onClick={() => void addTicket()}
                      className="rounded-md bg-gradient-to-r from-teal-300 to-sky-400 px-2 py-1 text-[11px] font-semibold text-slate-900"
                    >
                      Criar ticket
                    </button>
                  </div>
                </section>

                {tickets.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">Esta conversa ainda não tem tickets.</p>
                ) : (
                  tickets.map((ticket) => (
                    <section key={ticket.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
                      <div className="flex items-start gap-1">
                        <p className="min-w-0 flex-1 text-[11.5px] font-semibold">{ticket.subject}</p>
                        <TicketBadge status={ticket.status} />
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {ticket.category || "sem categoria"} · {TICKET_PRIORITY_LABELS[ticket.priority] || ticket.priority} ·{" "}
                        {fmtDate(ticket.created_at)}
                      </p>
                      {ticket.description ? (
                        <p className="mt-1 whitespace-pre-wrap text-[10.5px] text-foreground/80">{ticket.description}</p>
                      ) : null}
                      {ticket.notes.length ? (
                        <ul className="mt-1 flex flex-col gap-1">
                          {ticket.notes.slice(-3).map((note, index) => (
                            <li key={index} className="rounded-md bg-black/25 px-1.5 py-1 text-[10px] text-muted-foreground">
                              <span className="text-foreground/70">{note.by || "Operador"}</span> · {note.text}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <div className="mt-1.5 flex gap-1">
                        <select
                          value={ticket.status}
                          onChange={(event) => void patchTicket(ticket, { status: event.target.value })}
                          className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1 py-0.5 text-[10px] outline-none"
                        >
                          {Object.entries(TICKET_STATUS_LABELS).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <select
                          value={ticket.priority}
                          onChange={(event) => void patchTicket(ticket, { priority: event.target.value })}
                          className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1 py-0.5 text-[10px] outline-none"
                        >
                          {PRIORITIES.map((priority) => (
                            <option key={priority} value={priority}>
                              {TICKET_PRIORITY_LABELS[priority]}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="mt-1 flex gap-1">
                        <input
                          value={ticketNotes[ticket.id] || ""}
                          onChange={(event) => setTicketNotes((current) => ({ ...current, [ticket.id]: event.target.value }))}
                          placeholder="Nota…"
                          className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10px] outline-none focus:border-teal-400/40"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const note = (ticketNotes[ticket.id] || "").trim();
                            if (!note) return;
                            void patchTicket(ticket, { note }).then(() => {
                              setTicketNotes((current) => ({ ...current, [ticket.id]: "" }));
                            });
                          }}
                          className="rounded-md border border-white/10 bg-white/[0.05] px-1.5 text-[10px] hover:bg-white/[0.1]"
                        >
                          Adicionar
                        </button>
                      </div>
                    </section>
                  ))
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {events.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">Sem registos nesta conversa.</p>
                ) : (
                  events.map((event: SupportEvent) => (
                    <article key={event.id} className="rounded-lg border border-white/8 bg-white/[0.03] px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-teal-300/80" />
                        <p className="text-[10.5px] font-medium">{event.kind}</p>
                        <span className="ml-auto text-[9.5px] text-muted-foreground">{fmtTime(event.created_at)}</span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{event.detail}</p>
                      {event.actor_name ? (
                        <p className="text-[9.5px] text-muted-foreground">
                          {event.actor_type} · {event.actor_name}
                        </p>
                      ) : null}
                    </article>
                  ))
                )}
              </div>
            )}
          </div>
          {detail ? (
            <footer className="shrink-0 border-t border-white/8 px-2 py-1.5 text-[9.5px] text-muted-foreground">
              <span className="flex items-center gap-1">
                {detail.session.status === "closed" ? <CheckCircle2 size={10} /> : <Clock size={10} />}
                {detail.session.message_count} mensagens · {detail.session.status}
                {detail.session.assigned_operator_name ? ` · ${detail.session.assigned_operator_name}` : ""}
              </span>
            </footer>
          ) : null}
        </aside>
      </div>

      {overview?.oldest_waiting ? (
        <p className="shrink-0 text-[10.5px] text-amber-200/80">
          <Clock size={10} className="mr-1 inline" />
          Mais antiga à espera: {overview.oldest_waiting.visitor_name || "Visitante"} ({relative(overview.oldest_waiting.created_at)})
        </p>
      ) : null}
      {operators.length ? (
        <p className="shrink-0 truncate text-[10px] text-muted-foreground">
          <Users size={10} className="mr-1 inline" />
          Operadores:{" "}
          {operators.map((operator) => `${operator.name || operator.email} (${operator.live_status || operator.status || "offline"})`).join(" · ")}
        </p>
      ) : null}
      {wsState === "offline" ? (
        <p className="shrink-0 text-[10px] text-rose-300/80">
          <XCircle size={10} className="mr-1 inline" /> Sem WebSocket: as mensagens continuam a funcionar por REST e atualizam ao recarregar.
        </p>
      ) : null}
    </div>
  );
}
