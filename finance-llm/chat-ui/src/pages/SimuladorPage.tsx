/**
 * Página **Simulador IQ OS** — simulações de previsão por enxame de agentes com
 * os dados do sistema, apresentadas dentro da plataforma.
 *
 * O motor é o **MiroFish** (Docker, perfil `mirofish`): esta página escolhe a
 * fonte de dados, lança a simulação e depois **apresenta os resultados** —
 * estado da execução, ações por ronda, elenco de agentes, ontologia do grafo,
 * relatório escrito pelo enxame e entrevistas aos agentes. O estúdio original
 * do MiroFish fica disponível no separador «Estúdio MiroFish» (ou em nova aba),
 * pelo proxy de incorporação em `:8893`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Clock,
  Download,
  ExternalLink,
  FileText,
  Fish,
  Gauge,
  Hand,
  KeyRound,
  Layers,
  Languages,
  Loader2,
  MessageSquare,
  Mic,
  Network,
  Play,
  RotateCcw,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Square,
  Terminal,
  Users,
  Wand2,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  mirofishApi,
  mirofishPublicUrl,
  type MiroFishAction,
  type MiroFishAgent,
  type MiroFishContentPage,
  type MiroFishEnvironment,
  type MiroFishGraph,
  type MiroFishGraphEdge,
  type MiroFishGraphNode,
  type MiroFishGraphSearch,
  type MiroFishGraphStats,
  type MiroFishInterviewBatch,
  type MiroFishJob,
  type MiroFishMeta,
  type MiroFishReportLog,
  type MiroFishReportView,
  type MiroFishRunOverview,
  type MiroFishRunState,
  type MiroFishRunSummary,
  type MiroFishSeed,
  type MiroFishSource,
} from "../mirofishApi";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import type { StudioGraph, StudioNode } from "../components/graph/graphStudio";
import type { ContractGraphBuildMeta } from "../types";

/** Nós sem etiqueta de tipo vinda do Zep (igual ao backend). */
const GRAPH_TYPE_WITHOUT_LABEL = "Sem tipo";

type Tab = "resultados" | "grafo" | "interacao" | "elenco" | "relatorio" | "nova" | "estudio";
const TABS: { id: Tab; label: string; icon: typeof Activity }[] = [
  { id: "resultados", label: "Resultados", icon: Gauge },
  { id: "grafo", label: "Grafo", icon: Network },
  { id: "interacao", label: "Interação", icon: Hand },
  { id: "elenco", label: "Elenco", icon: Users },
  { id: "relatorio", label: "Relatório", icon: FileText },
  { id: "nova", label: "Nova simulação", icon: Wand2 },
  { id: "estudio", label: "Estúdio MiroFish", icon: Fish },
];

/** Cores por tipo de entidade do grafo (a legenda lê-se de um lado). */
const ENTITY_TYPE_COLORS: Record<string, string> = {
  PublicContractingEntity: "#2dd4bf",
  PrivateCompany: "#fbbf24",
  InsolventEntity: "#fb7185",
  Court: "#60a5fa",
  Person: "#f472b6",
  Organization: "#a78bfa",
  Contractor: "#38bdf8",
  BusinessAssociation: "#34d399",
  Regulator: "#c084fc",
  MediaOutlet: "#f97316",
  GovernmentAgency: "#22d3ee",
  [GRAPH_TYPE_WITHOUT_LABEL]: "#94a3b8",
};

const GRAPH_TYPE_FALLBACK = ["#22d3ee", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#60a5fa", "#fb7185", "#c084fc"];

function entityColor(type: string): string {
  const known = ENTITY_TYPE_COLORS[type];
  if (known) return known;
  let hash = 0;
  for (let index = 0; index < type.length; index += 1) hash = (hash * 31 + type.charCodeAt(index)) % 9973;
  return GRAPH_TYPE_FALLBACK[hash % GRAPH_TYPE_FALLBACK.length];
}

const STEP_LABELS: Record<string, string> = {
  graph: "Construir o grafo (Zep)",
  prepare: "Gerar personas e ambiente",
  run: "Correr a simulação",
  report: "Escrever o relatório",
};

const PLATFORM_LABELS: Record<string, string> = {
  twitter: "Twitter",
  reddit: "Reddit",
};

const TYPE_COLORS = ["#22d3ee", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#60a5fa", "#fb7185", "#c084fc"];

const POLL_MS = 5000;

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-PT").format(value);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value)}%`;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * Texto com caracteres CJK: as simulações anteriores à tradução do motor têm as
 * personas, as publicações e as justificações gravadas em chinês (o que está no
 * Zep e nos ficheiros da simulação não é reescrito).
 */
const CJK = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;

function hasChinese(text?: string | null): boolean {
  return Boolean(text) && CJK.test(String(text));
}

function StatePill({ state, size = "sm" }: { state?: MiroFishRunState | null; size?: "sm" | "md" }) {
  const tone = state?.tone ?? "idle";
  const styles: Record<string, string> = {
    busy: "bg-sky-950/60 text-sky-300 border-sky-900/60",
    ok: "bg-emerald-950/60 text-emerald-300 border-emerald-900/60",
    warn: "bg-amber-950/60 text-amber-300 border-amber-900/60",
    error: "bg-red-950/60 text-red-300 border-red-900/60",
    idle: "bg-zinc-900/80 text-zinc-400 border-zinc-800",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${
        size === "md" ? "text-xs" : "text-[11px]"
      } ${styles[tone] ?? styles.idle}`}
    >
      {tone === "busy" ? <Loader2 size={11} className="animate-spin" /> : <Activity size={11} />}
      {state?.label ?? "—"}
    </span>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-zinc-100">{value}</div>
      {hint ? <div className="text-[11px] text-zinc-500">{hint}</div> : null}
    </div>
  );
}

function ActionCard({ action, onAgent }: { action: MiroFishAction; onAgent: (agentId: number | null | undefined) => void }) {
  const platformColor = action.platform === "twitter" ? "text-sky-300" : action.platform === "reddit" ? "text-orange-300" : "text-zinc-400";
  return (
    <article className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      <header className="flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          onClick={() => onAgent(action.agent_id)}
          className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800/80 px-2 py-0.5 font-medium text-zinc-200 transition hover:bg-zinc-700"
        >
          <Users size={11} /> {action.agent_name}
        </button>
        <span className="text-zinc-500">
          {action.action}
          {action.platform ? <span className={platformColor}> · {PLATFORM_LABELS[action.platform] ?? action.platform}</span> : null}
          {action.round !== null && action.round !== undefined ? <span> · ronda {action.round}</span> : null}
        </span>
        <span className="ml-auto text-zinc-500">{formatTime(action.timestamp)}</span>
      </header>
      {action.content ? <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{action.content}</p> : null}
      {!action.success ? <p className="mt-1 text-[11px] text-red-300">ação falhou no MiroFish</p> : null}
    </article>
  );
}

export default function SimuladorPage({ onNavigate }: { onNavigate?: (view: string) => void }) {
  const [tab, setTab] = useState<Tab>("resultados");
  const [meta, setMeta] = useState<MiroFishMeta | null>(null);
  const [runs, setRuns] = useState<MiroFishRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [overview, setOverview] = useState<MiroFishRunOverview | null>(null);
  const [reportView, setReportView] = useState<MiroFishReportView | null>(null);
  const [jobs, setJobs] = useState<MiroFishJob[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Feed de ações
  const [extraActions, setExtraActions] = useState<MiroFishAction[]>([]);
  const [feedPlatform, setFeedPlatform] = useState("");
  const [feedRound, setFeedRound] = useState("");
  const [feedAgent, setFeedAgent] = useState<number | null>(null);

  // Elenco
  const [castQuery, setCastQuery] = useState("");
  const [castType, setCastType] = useState("");
  const [openAgent, setOpenAgent] = useState<MiroFishAgent | null>(null);
  const [interviewPrompt, setInterviewPrompt] = useState("Nos próximos 6 meses, o que esperas que aconteça?");
  const [interviewResult, setInterviewResult] = useState<string | null>(null);
  const [interviewTarget, setInterviewTarget] = useState<number | null>(null);

  // Relatório
  const [chatMessages, setChatMessages] = useState<{ role: "user" | "agent"; content: string; sources?: string[] }[]>([]);
  const [chatQuestion, setChatQuestion] = useState("");

  // Grafo do conhecimento (Zep)
  const [graph, setGraph] = useState<MiroFishGraph | null>(null);  const [graphLoading, setGraphLoading] = useState(false);
  const [graphLayout, setGraphLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [graphHidden, setGraphHidden] = useState<string[]>([]);
  const [graphQuery, setGraphQuery] = useState("");
  const [graphNode, setGraphNode] = useState<MiroFishGraphNode | null>(null);
  const [graphVersion, setGraphVersion] = useState(0);

  // Interação: ambiente, entrevistas em lote, conteúdo, registos e grafo
  const [env, setEnv] = useState<MiroFishEnvironment | null>(null);
  const [batchPrompt, setBatchPrompt] = useState("Nos próximos 6 meses, o que esperas que aconteça?");
  const [batchAgents, setBatchAgents] = useState("");
  const [batchPlatform, setBatchPlatform] = useState("");
  const [batchResult, setBatchResult] = useState<MiroFishInterviewBatch | null>(null);
  const [contentMode, setContentMode] = useState<"posts" | "comments">("posts");
  const [contentPlatform, setContentPlatform] = useState("");
  const [contentPage, setContentPage] = useState<MiroFishContentPage | null>(null);
  const [logKind, setLogKind] = useState<"console" | "agent">("console");
  const [logLines, setLogLines] = useState<MiroFishReportLog | null>(null);
  const [graphSearchQuery, setGraphSearchQuery] = useState("");
  const [graphSearchResult, setGraphSearchResult] = useState<MiroFishGraphSearch | null>(null);
  const [graphStatsResult, setGraphStatsResult] = useState<MiroFishGraphStats | null>(null);

  // Nova simulação
  const [sourceId, setSourceId] = useState("sistema");
  const [params, setParams] = useState<Record<string, string>>({});
  const [requirement, setRequirement] = useState("");
  const [steps, setSteps] = useState<Record<string, boolean>>({ graph: true, prepare: true, run: true, report: false });
  const [maxRounds, setMaxRounds] = useState("30");
  const [platform, setPlatform] = useState("parallel");
  const [seed, setSeed] = useState<MiroFishSeed | null>(null);

  const pollRef = useRef<number | null>(null);

  const sources = useMemo(() => meta?.sources ?? [], [meta]);
  const source: MiroFishSource | undefined = useMemo(
    () => sources.find((item) => item.id === sourceId) ?? sources[0],
    [sourceId, sources],
  );
  const publicUrl = mirofishPublicUrl(meta?.public_url);
  const serviceAvailable = Boolean(meta?.service?.available);

  const runningJob = jobs.find((job) => job.status === "running");

  /** Lista de simulações + trabalhos recentes. */
  const refreshRuns = useCallback(async () => {
    const [catalog, jobList] = await Promise.all([
      mirofishApi.runs(20, 6),
      mirofishApi.jobs(8).catch(() => ({ jobs: [] as MiroFishJob[] })),
    ]);
    setRuns(catalog.runs);
    setJobs(jobList.jobs);
    setSelectedId((current) => {
      if (current && catalog.runs.some((run) => run.simulation_id === current)) return current;
      const active = catalog.runs.find((run) => run.state.tone === "busy") ?? catalog.runs[0];
      return active?.simulation_id ?? "";
    });
  }, []);

  const loadRun = useCallback(async (simulationId: string, withReport = true) => {
    if (!simulationId) {
      setOverview(null);
      return;
    }
    const payload = await mirofishApi.run(simulationId, 30);
    setOverview(payload);
    if (withReport) {
      const report = await mirofishApi.runReport(simulationId).catch(() => null);
      setReportView(report);
    }
  }, []);

  /** Grafo de conhecimento do Zep (só quando o separador é aberto). */
  const loadGraph = useCallback(async (simulationId: string) => {
    if (!simulationId) {
      setGraph(null);
      return;
    }
    setGraphLoading(true);
    try {
      const payload = await mirofishApi.runGraph(simulationId);
      setGraph(payload);
      setGraphHidden([]);
      setGraphVersion((version) => version + 1);
    } catch (exc) {
      setGraph(null);
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setGraphLoading(false);
    }
  }, []);

  /** Estado do ambiente de simulação: só um ambiente vivo aceita entrevistas. */
  const loadEnv = useCallback(async (simulationId: string) => {
    if (!simulationId) {
      setEnv(null);
      return;
    }
    try {
      const result = await mirofishApi.runEnvironment(simulationId);
      setEnv(result);
    } catch {
      setEnv(null);
    }
  }, []);

  const loadAll = useCallback(
    async (label = "load") => {
      setBusy(label);
      setError(null);
      try {
        const metaPayload = await mirofishApi.meta();
        setMeta(metaPayload);
        await refreshRuns();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        setBusy(null);
      }
    },
    [refreshRuns],
  );

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // Carrega (e vai refrescando) o resultado da simulação escolhida.
  useEffect(() => {
    if (!selectedId) return;
    setExtraActions([]);
    setOpenAgent(null);
    setInterviewResult(null);
    setChatMessages([]);
    setGraph(null);
    setGraphNode(null);
    setEnv(null);
    setBatchResult(null);
    setContentPage(null);
    setLogLines(null);
    setGraphSearchResult(null);
    setGraphStatsResult(null);
    void loadRun(selectedId).catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [selectedId, loadRun]);

  // O grafo do Zep só se pede quando o separador é aberto (é a leitura mais pesada).
  useEffect(() => {
    if (tab !== "grafo" || !selectedId || graph) return;
    void loadGraph(selectedId);
  }, [graph, loadGraph, selectedId, tab]);

  // O estado do ambiente também só se pergunta quando o separador é aberto.
  useEffect(() => {
    if (tab !== "interacao" || !selectedId || env) return;
    void loadEnv(selectedId);
  }, [env, loadEnv, selectedId, tab]);

  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const shouldPoll = Boolean(selectedId) && (overview?.active || Boolean(runningJob));
    if (!shouldPoll) return;
    pollRef.current = window.setInterval(() => {
      void loadRun(selectedId, false).catch(() => undefined);
      void refreshRuns().catch(() => undefined);
    }, POLL_MS);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [overview?.active, runningJob, refreshRuns, selectedId, loadRun]);

  // Valores por omissão da fonte escolhida (nova simulação).
  useEffect(() => {
    if (!source) return;
    const next: Record<string, string> = {};
    for (const param of source.params) {
      next[param.name] = params[param.name] ?? (param.default !== undefined ? String(param.default) : "");
    }
    setParams(next);
    setRequirement((current) => current || source.requirement);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.id]);

  const runAction = useCallback(async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  }, []);

  const actionFilters = useCallback(
    () => ({
      platform: feedPlatform || undefined,
      agentId: feedAgent ?? undefined,
      round: feedRound ? Number(feedRound) : undefined,
    }),
    [feedAgent, feedPlatform, feedRound],
  );

  const handleLoadMore = useCallback(
    () =>
      runAction("more", async () => {
        if (!selectedId) return;
        const all = [...(overview?.actions ?? []), ...extraActions];
        const page = await mirofishApi.runActions(selectedId, { limit: 40, offset: all.length, ...actionFilters() });
        setExtraActions((current) => [...current, ...page.actions]);
      }),
    [actionFilters, extraActions, overview?.actions, runAction, selectedId],
  );

  const actions = useMemo(() => {
    const base = feedPlatform || feedAgent !== null || feedRound ? extraActions : [...(overview?.actions ?? []), ...extraActions];
    return base;
  }, [extraActions, feedAgent, feedPlatform, feedRound, overview?.actions]);

  const handleFilter = useCallback(
    (next: { platform?: string; round?: string; agentId?: number | null }) =>
      runAction("filter", async () => {
        const appliedPlatform = next.platform !== undefined ? next.platform : feedPlatform;
        const appliedRound = next.round !== undefined ? next.round : feedRound;
        const appliedAgent = next.agentId !== undefined ? next.agentId : feedAgent;
        if (next.platform !== undefined) setFeedPlatform(next.platform);
        if (next.round !== undefined) setFeedRound(next.round);
        if (next.agentId !== undefined) setFeedAgent(next.agentId);
        if (!selectedId) return;
        const page = await mirofishApi.runActions(selectedId, {
          limit: 60,
          offset: 0,
          platform: appliedPlatform || undefined,
          agentId: appliedAgent ?? undefined,
          round: appliedRound ? Number(appliedRound) : undefined,
        });
        setExtraActions(page.actions);
      }),
    [feedAgent, feedPlatform, feedRound, runAction, selectedId],
  );

  const handleStop = useCallback(
    () =>
      runAction("stop", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.stopRun(selectedId);
        setNotice(`Execução interrompida (${result.state.label}). O relatório já pode ser pedido.`);
        await loadRun(selectedId, false);
        await refreshRuns();
      }),
    [loadRun, refreshRuns, runAction, selectedId],
  );

  const handleInterview = useCallback(
    () =>
      runAction("interview", async () => {
        if (!selectedId) return;
        setInterviewResult(null);
        const result = await mirofishApi.interview(selectedId, {
          prompt: interviewPrompt,
          agent_id: interviewTarget ?? undefined,
          timeout: 180,
        });
        setInterviewResult(JSON.stringify(result.data, null, 2));
      }),
    [interviewPrompt, interviewTarget, runAction, selectedId],
  );

  // --- Interação: ambiente, reinício, entrevistas em lote, conteúdo e grafo ---
  const handleCheckEnv = useCallback(
    () =>
      runAction("env", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.runEnvironment(selectedId);
        setEnv(result);
      }),
    [runAction, selectedId],
  );

  const handleCloseEnv = useCallback(
    () =>
      runAction("close-env", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.closeEnvironment(selectedId, 30);
        if (result.closed) {
          setEnv({ simulation_id: selectedId, alive: false, platforms: { twitter: false, reddit: false }, message: "Ambiente fechado." });
          setNotice("Ambiente de simulação fechado.");
        } else {
          setNotice("Não foi possível fechar o ambiente.");
        }
      }),
    [runAction, selectedId],
  );

  const handleStartRun = useCallback(
    () =>
      runAction("start-run", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.startRun(selectedId, { force: true });
        setNotice(`Simulação reiniciada (${result.state.label}).`);
        await loadRun(selectedId, false);
        await refreshRuns();
      }),
    [loadRun, refreshRuns, runAction, selectedId],
  );

  const handleBatchInterview = useCallback(
    () =>
      runAction("batch-interview", async () => {
        if (!selectedId) return;
        setBatchResult(null);
        const typed = batchAgents
          .split(/[\n,;]+/)
          .map((item) => item.trim())
          .filter((item) => item !== "")
          .map((item) => (/^-?\d+$/.test(item) ? Number(item) : item));
        // Sem IDs indicados a pergunta vai a todo o elenco (o MiroFish exige alvos explícitos).
        const agents: (number | string)[] = typed.length
          ? typed
          : (overview?.cast ?? [])
              .map((agent) => (agent.agent_id === null || agent.agent_id === undefined ? agent.name : agent.agent_id))
              .filter((item): item is number | string => item !== "" && item !== null && item !== undefined);
        if (!agents.length) {
          setNotice("Esta simulação ainda não tem elenco para entrevistar.");
          return;
        }
        const result = await mirofishApi.interviewBatch(selectedId, {
          prompt: batchPrompt,
          agents,
          platform: batchPlatform || undefined,
          timeout: 180,
        });
        setBatchResult(result);
      }),
    [batchAgents, batchPlatform, batchPrompt, overview?.cast, runAction, selectedId],
  );

  const handleLoadContent = useCallback(
    () =>
      runAction("content", async () => {
        if (!selectedId) return;
        const page =
          contentMode === "posts"
            ? await mirofishApi.runPosts(selectedId, { platform: contentPlatform || undefined, limit: 30, offset: 0 })
            : await mirofishApi.runComments(selectedId, { platform: contentPlatform || undefined, limit: 30, offset: 0 });
        setContentPage(page);
      }),
    [contentMode, contentPlatform, runAction, selectedId],
  );

  const handleLoadLogs = useCallback(
    () =>
      runAction("logs", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.reportLog(selectedId, logKind, 0);
        setLogLines(result);
      }),
    [logKind, runAction, selectedId],
  );

  const handleGraphSearch = useCallback(
    () =>
      runAction("graph-search", async () => {
        if (!selectedId || !graphSearchQuery.trim()) return;
        const result = await mirofishApi.graphSearch(selectedId, graphSearchQuery.trim(), 10);
        setGraphSearchResult(result);
      }),
    [graphSearchQuery, runAction, selectedId],
  );

  const handleGraphStats = useCallback(
    () =>
      runAction("graph-stats", async () => {
        if (!selectedId) return;
        const result = await mirofishApi.graphStatistics(selectedId);
        setGraphStatsResult(result);
      }),
    [runAction, selectedId],
  );

  const handleGenerateReport = useCallback(
    (force = false) =>
      runAction("report", async () => {
        if (!selectedId) return;
        const view = await mirofishApi.generateReport(selectedId, force);
        setReportView(view);
        setNotice(
          view.has_report
            ? "Relatório disponível."
            : "Relatório em preparação no MiroFish — a página vai atualizando (pode demorar alguns minutos).",
        );
      }),
    [runAction, selectedId],
  );

  // Enquanto o relatório estiver a ser escrito, vai consultando o estado.
  useEffect(() => {
    const state = reportView?.status?.key ?? "";
    if (!selectedId || !["planning", "generating", "pending"].includes(state)) return;
    const timer = window.setInterval(() => {
      void mirofishApi
        .runReport(selectedId)
        .then((view) => {
          setReportView(view);
          if (view.has_report) setNotice("Relatório pronto.");
        })
        .catch(() => undefined);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [reportView?.status?.key, selectedId]);

  const handleAskReport = useCallback(
    () =>
      runAction("ask", async () => {
        const question = chatQuestion.trim();
        if (!selectedId || !question) return;
        setChatMessages((current) => [...current, { role: "user", content: question }]);
        setChatQuestion("");
        const history = chatMessages.map((message) => ({
          role: message.role === "user" ? "user" : "assistant",
          content: message.content,
        }));
        const answer = await mirofishApi.askReport(selectedId, question, history);
        setChatMessages((current) => [...current, { role: "agent", content: answer.answer || "(sem resposta)", sources: answer.sources }]);
      }),
    [chatMessages, chatQuestion, runAction, selectedId],
  );

  const seedPayload = useCallback(
    () => ({
      source: source?.id ?? sourceId,
      params: Object.fromEntries(Object.entries(params).filter(([, value]) => String(value).trim() !== "")),
      requirement: requirement.trim() || undefined,
    }),
    [params, requirement, source?.id, sourceId],
  );

  const handlePreviewSeed = useCallback(
    () =>
      runAction("preview", async () => {
        const result = await mirofishApi.seed(seedPayload());
        setSeed(result);
        setNotice(`Semente composta: ${result.title} — ${formatNumber(result.chars)} caracteres, ${formatNumber(result.words)} palavras.`);
      }),
    [runAction, seedPayload],
  );

  const handleSimulate = useCallback(
    () =>
      runAction("simulate", async () => {
        const job = await mirofishApi.simulate({
          ...seedPayload(),
          title: source?.label ?? sourceId,
          project_name: seed?.title,
          max_rounds: maxRounds ? Number(maxRounds) : undefined,
          platform,
          steps,
        });
        setNotice(`Simulação lançada (trabalho ${job.id}). Vai aparecer na lista à esquerda à medida que avança.`);
        await refreshRuns();
        setTab("resultados");
      }),
    [maxRounds, platform, refreshRuns, runAction, seed?.title, seedPayload, source, sourceId, steps],
  );

  const handleSaveSeed = useCallback(
    () =>
      runAction("save", async () => {
        const result = await mirofishApi.saveSeed(seedPayload());
        setNotice(`Semente guardada no Office: «${result.document.title}».`);
      }),
    [runAction, seedPayload],
  );

  const cast = useMemo(() => overview?.cast ?? [], [overview]);
  const filteredCast = useMemo(() => {
    const term = castQuery.trim().toLowerCase();
    return cast.filter((agent) => {
      if (castType && agent.entity_type !== castType) return false;
      if (!term) return true;
      return (
        agent.name.toLowerCase().includes(term) ||
        (agent.entity_type ?? "").toLowerCase().includes(term) ||
        (agent.bio ?? "").toLowerCase().includes(term)
      );
    });
  }, [cast, castQuery, castType]);

  const rounds = overview?.rounds ?? [];
  const roundsCount = rounds.length;
  const metrics = overview?.metrics;
  const typeData = (overview?.state_counts ?? []).map((row) => ({ name: row.type, value: row.count }));
  const topAgents = cast.slice(0, 10).map((agent) => ({ name: agent.name.slice(0, 22), twitter: agent.actions_twitter, reddit: agent.actions_reddit }));
  const selected = runs.find((run) => run.simulation_id === selectedId) ?? null;

  // Simulações anteriores à tradução do motor: personas e publicações em chinês.
  const chineseRun = useMemo(() => {
    if (!overview) return false;
    const amostras = [
      ...overview.cast.slice(0, 4).flatMap((agent) => [agent.bio, agent.persona, agent.name]),
      ...overview.actions.slice(0, 4).map((action) => action.content),
    ];
    return amostras.some((texto) => hasChinese(texto));
  }, [overview]);

  // --- Grafo do conhecimento (Zep) -------------------------------------------
  // Filtros: tipo de entidade (legenda) e pesquisa por nome/resumo.
  const graphNodes = useMemo(() => {
    const hidden = new Set(graphHidden);
    const term = graphQuery.trim().toLowerCase();
    return (graph?.nodes ?? []).filter((node) => {
      if (hidden.has(node.type)) return false;
      if (!term) return true;
      return (
        node.name.toLowerCase().includes(term) ||
        node.type.toLowerCase().includes(term) ||
        node.summary.toLowerCase().includes(term)
      );
    });
  }, [graph, graphHidden, graphQuery]);

  /** Facto por par de nós — o canvas desenha arestas simples, a dica mostra a frase. */
  const graphFacts = useMemo(() => {
    const map = new Map<string, MiroFishGraphEdge>();
    (graph?.edges ?? []).forEach((edge) => map.set(`${edge.source}|${edge.target}`, edge));
    return map;
  }, [graph]);

  /** Grafo do Zep no modelo do canvas do IQ OS (cores por tipo de entidade). */
  const studioGraph = useMemo<StudioGraph | null>(() => {
    if (!graph) return null;
    const ids = new Set(graphNodes.map((node) => node.id));
    const shape = (type: string) => {
      const key = type.toLowerCase();
      if (key === "person") return "person";
      if (key.includes("court") || key.includes("government") || key.includes("regulator")) return "entity";
      if (key.includes("media") || key === "organization" || key === GRAPH_TYPE_WITHOUT_LABEL.toLowerCase()) return "source";
      return "company";
    };
    const nodes: StudioNode[] = graphNodes.map((node) => {
      const degree = node.degree ?? 0;
      return {
        id: node.id,
        key: node.id,
        label: node.name,
        dimension: "entidade",
        type: shape(node.type),
        role: node.type,
        count: degree,
        total_value: degree,
        value: degree,
        radius: 7 + Math.min(10, Math.sqrt(Math.max(0, degree)) * 2.6),
        color: entityColor(node.type),
        legendKey: node.type,
        legendLabel: node.type,
      };
    });
    const edges = (graph.edges ?? [])
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge) => ({ source: edge.source, target: edge.target, count: 1, value: 1, weight: 1 }));
    const meta: ContractGraphBuildMeta = {
      dimension_a: "entidade",
      dimension_b: "entidade",
      metric: "contratos",
      mode: "knowledge_graph",
      complete: true,
      scan_capped: false,
      sample_order: "grau",
      sample_limit: null,
      documents_scanned: graph.node_count,
      documents_matching: graph.node_count,
      scanned_value: graph.edge_count,
      nodes_total: graph.node_count,
      edges_total: graph.edge_count,
      kept_nodes: nodes.length,
      kept_edges: edges.length,
      omitted_edges: Math.max(0, graph.edge_count - edges.length),
      directed: false,
      notes: [],
      filters: {},
    };
    return { nodes, edges, meta };
  }, [graph, graphNodes]);

  /** Relações do nó escolhido (factos que entram e saem). */
  const nodeRelations = useMemo(() => {
    if (!graph || !graphNode) return [];
    return graph.edges
      .filter((edge) => edge.source === graphNode.id || edge.target === graphNode.id)
      .map((edge) => ({
        edge,
        outgoing: edge.source === graphNode.id,
        other: edge.source === graphNode.id ? edge.target_name : edge.source_name,
      }));
  }, [graph, graphNode]);

  return (
    <div className="h-full w-full overflow-auto bg-zinc-950 p-4 text-zinc-100 md:p-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <Sparkles className="text-cyan-400" size={22} />
              Simulador IQ OS
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-400">
              Previsão por <strong className="text-zinc-300">enxame de agentes</strong> a partir dos dados do sistema: a
              plataforma compõe a semente, o MiroFish constrói o grafo de conhecimento, gera as personas, corre a simulação e
              escreve o relatório — aqui vê-se tudo sem sair do IQ OS.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-xs text-zinc-400">
              <Activity size={14} className={serviceAvailable ? "text-emerald-400" : "text-red-400"} />
              {serviceAvailable ? "Motor MiroFish a responder" : "Motor MiroFish indisponível"}
            </span>
            <button
              onClick={() => void loadAll("load")}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white"
            >
              <RefreshCw size={16} className={busy === "load" ? "animate-spin" : ""} /> Atualizar
            </button>
            {onNavigate ? (
              <button
                onClick={() => onNavigate("mirofish")}
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white"
              >
                <KeyRound size={16} /> Chaves e motor
              </button>
            ) : null}
            <a
              href={`${publicUrl}/`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-500/90 px-3 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-400"
            >
              <ExternalLink size={16} /> Abrir estúdio
            </a>
          </div>
        </header>

        <nav className="flex flex-wrap gap-2 border-b border-zinc-800 pb-2">
          {TABS.map((item) => {
            const Icon = item.icon;
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition ${
                  active ? "bg-zinc-800 text-white" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                }`}
              >
                <Icon size={15} /> {item.label}
              </button>
            );
          })}
        </nav>

        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-200">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-xl border border-sky-900/60 bg-sky-950/30 p-3 text-sm text-sky-200">{notice}</div>
        ) : null}

        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          {/* Lista de simulações */}
          <aside className="space-y-2 lg:sticky lg:top-0 lg:max-h-[calc(100vh-220px)] lg:overflow-auto">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Simulações</h2>
              <span className="text-xs text-zinc-500">{runs.length}</span>
            </div>
            {runs.length === 0 ? (
              <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-400">
                Ainda não há simulações. Use «Nova simulação» para lançar a primeira com dados do sistema.
              </p>
            ) : null}
            {runs.map((run) => {
              const active = run.simulation_id === selectedId;
              return (
                <button
                  key={run.simulation_id}
                  onClick={() => setSelectedId(run.simulation_id)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    active ? "border-cyan-700/70 bg-cyan-950/20" : "border-zinc-800 bg-zinc-900/40 hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-zinc-100">{run.title}</span>
                    <StatePill state={run.state} />
                  </div>
                  <div className="mt-1 truncate text-[11px] text-zinc-500">
                    {run.simulation_id} · {formatDate(run.created_at)}
                  </div>
                  {run.live ? (
                    <div className="mt-2 space-y-1">
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className="h-full rounded-full bg-cyan-500"
                          style={{ width: `${Math.min(100, Math.max(2, run.live.progress ?? 0))}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-[11px] text-zinc-500">
                        <span>
                          ronda {formatNumber(run.live.round_current)}/{formatNumber(run.live.rounds_total)}
                        </span>
                        <span>
                          {formatNumber(run.live.actions_total)} ações · {formatPercent(run.live.progress)}
                        </span>
                      </div>
                    </div>
                  ) : null}
                  {run.report?.has_report ? (
                    <div className="mt-1 inline-flex items-center gap-1 text-[11px] text-emerald-300">
                      <FileText size={11} /> relatório pronto
                    </div>
                  ) : null}
                </button>
              );
            })}

            {jobs.length ? (
              <div className="space-y-2 pt-2">
                <h2 className="px-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Trabalhos recentes</h2>
                {jobs.slice(0, 5).map((job) => (
                  <div key={job.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-2.5 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-zinc-200">{job.title}</span>
                      <span className="text-zinc-500">{job.step}</span>
                    </div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-zinc-800">
                      <div className="h-full rounded-full bg-violet-500" style={{ width: `${job.progress}%` }} />
                    </div>
                    {job.error ? <p className="mt-1 text-red-300">{job.error}</p> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </aside>

          <section className="min-w-0 space-y-5">
            {tab === "resultados" ? (
              !overview ? (
                <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
                  Escolha (ou lance) uma simulação para ver os resultados.
                </p>
              ) : (
                <>
                  {chineseRun ? (
                    <div className="flex items-start gap-2 rounded-xl border border-amber-800/60 bg-amber-950/30 p-3 text-xs text-amber-200">
                      <Languages size={15} className="mt-0.5 shrink-0" />
                      <span>
                        Esta simulação foi criada <strong>antes de o MiroFish passar a escrever em português</strong>: os
                        textos dos agentes (personas, publicações e justificações) ficaram gravados em chinês e não são
                        reescritos. Lance uma nova simulação no separador «Nova simulação» para os ter em português.
                      </span>
                    </div>
                  ) : null}
                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h2 className="truncate text-lg font-semibold text-zinc-100">{overview.simulation.title}</h2>
                        <p className="mt-0.5 text-xs text-zinc-500">
                          {overview.simulation.simulation_id} · projeto {overview.simulation.project_id || "—"} · grafo{" "}
                          {overview.simulation.graph_id || "—"}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatePill state={overview.state} size="md" />
                        {overview.active ? (
                          <button
                            onClick={() => void handleStop()}
                            className="inline-flex items-center gap-2 rounded-lg border border-amber-800/70 px-3 py-1.5 text-xs text-amber-200 transition hover:border-amber-600"
                          >
                            {busy === "stop" ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} />} Interromper
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {overview.simulation.requirement ? (
                      <p className="mt-3 whitespace-pre-wrap rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-sm text-zinc-300">
                        {overview.simulation.requirement}
                      </p>
                    ) : null}

                    <div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
                      <Metric
                        label="Progresso"
                        value={formatPercent(metrics?.progress)}
                        hint={`ronda ${formatNumber(metrics?.round_current)} de ${formatNumber(metrics?.rounds_total)}`}
                      />
                      <Metric label="Ações dos agentes" value={formatNumber(metrics?.actions_total)} hint={`${formatNumber(metrics?.actions_twitter)} twitter · ${formatNumber(metrics?.actions_reddit)} reddit`} />
                      <Metric label="Agentes" value={formatNumber(metrics?.agents_total)} hint={`${formatNumber(metrics?.entities_total)} entidades no grafo`} />
                      <Metric label="Rondas com atividade" value={formatNumber(roundsCount)} hint={`horas simuladas ${formatNumber(metrics?.hours_total)}`} />
                      <Metric label="Início" value={formatDate(metrics?.started_at)} hint={overview.job?.title ? `trabalho ${overview.job.id}` : undefined} />
                      <Metric label="Fim" value={formatDate(metrics?.completed_at)} hint={overview.simulation.created_at ? `criada ${formatDate(overview.simulation.created_at)}` : undefined} />
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                      {(["twitter", "reddit"] as const).map((key) => {
                        const info = overview.platforms[key];
                        return (
                          <span key={key} className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-950/60 px-2 py-0.5 text-zinc-400">
                            <span className={info.completed ? "text-emerald-400" : info.running ? "text-sky-400" : "text-zinc-500"}>
                              {info.completed ? "concluído" : info.running ? "a correr" : "parado"}
                            </span>
                            {PLATFORM_LABELS[key]} · ronda {formatNumber(info.round)} · {formatNumber(info.actions)} ações
                          </span>
                        );
                      })}
                      {overview.simulation.entity_types?.length ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-950/60 px-2 py-0.5 text-zinc-400">
                          <Layers size={11} /> {overview.simulation.entity_types.length} tipos de entidade
                        </span>
                      ) : null}
                      {overview.job?.seed ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-950/60 px-2 py-0.5 text-zinc-400">
                          semente: {String(overview.job.seed.title ?? overview.job.seed.source ?? "—")} (
                          {formatNumber(Number(overview.job.seed.chars ?? 0))} caracteres)
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <div className="grid gap-4 xl:grid-cols-2">
                    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <BarChart3 size={16} className="text-cyan-400" /> Ações por ronda
                      </h3>
                      <div className="mt-3 h-56">
                        {rounds.length ? (
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={rounds.map((row) => ({ name: `R${row.round ?? 0}`, twitter: row.twitter, reddit: row.reddit }))}>
                              <CartesianGrid stroke="#27272a" vertical={false} />
                              <XAxis dataKey="name" stroke="#71717a" fontSize={11} />
                              <YAxis stroke="#71717a" fontSize={11} allowDecimals={false} />
                              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} />
                              <Legend wrapperStyle={{ fontSize: 11 }} />
                              <Bar dataKey="twitter" name="Twitter" stackId="a" fill="#38bdf8" radius={[0, 0, 0, 0]} />
                              <Bar dataKey="reddit" name="Reddit" stackId="a" fill="#fb923c" radius={[3, 3, 0, 0]} />
                            </BarChart>
                          </ResponsiveContainer>
                        ) : (
                          <p className="pt-10 text-center text-sm text-zinc-500">Ainda sem ações: a simulação está na fase de preparação.</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Users size={16} className="text-violet-400" /> Quem mais falou
                      </h3>
                      <div className="mt-3 h-56">
                        {topAgents.some((row) => row.twitter + row.reddit > 0) ? (
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={topAgents} layout="vertical" margin={{ left: 8, right: 12 }}>
                              <CartesianGrid stroke="#27272a" horizontal={false} />
                              <XAxis type="number" stroke="#71717a" fontSize={11} allowDecimals={false} />
                              <YAxis type="category" dataKey="name" stroke="#71717a" fontSize={10} width={130} />
                              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} />
                              <Legend wrapperStyle={{ fontSize: 11 }} />
                              <Bar dataKey="twitter" name="Twitter" stackId="a" fill="#38bdf8" />
                              <Bar dataKey="reddit" name="Reddit" stackId="a" fill="#fb923c" radius={[0, 3, 3, 0]} />
                            </BarChart>
                          </ResponsiveContainer>
                        ) : (
                          <p className="pt-10 text-center text-sm text-zinc-500">Sem ações registadas por agente.</p>
                        )}
                      </div>
                    </div>
                  </div>

                  {typeData.length ? (
                    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Layers size={16} className="text-emerald-400" /> Composição do enxame
                      </h3>
                      <div className="mt-2 grid gap-4 md:grid-cols-[260px_1fr]">
                        <div className="h-52">
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie data={typeData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={2}>
                                {typeData.map((entry, index) => (
                                  <Cell key={entry.name} fill={TYPE_COLORS[index % TYPE_COLORS.length]} />
                                ))}
                              </Pie>
                              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }} />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>
                        <div className="flex flex-wrap content-start gap-2">
                          {typeData.map((row, index) => (
                            <span
                              key={row.name}
                              className="inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 px-2 py-1 text-xs text-zinc-300"
                            >
                              <span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLORS[index % TYPE_COLORS.length] }} />
                              {row.name} · {row.value}
                            </span>
                          ))}
                        </div>
                      </div>
                      {overview.simulation.ontology?.edge_types?.length ? (
                        <p className="mt-3 text-xs text-zinc-500">
                          Relações modeladas: {overview.simulation.ontology.edge_types.join(" · ")}
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <MessageSquare size={16} className="text-cyan-400" /> O que se disse
                      </h3>
                      <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
                        <select
                          value={feedPlatform}
                          onChange={(event) => void handleFilter({ platform: event.target.value })}
                          className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200"
                        >
                          <option value="">todas as plataformas</option>
                          <option value="twitter">Twitter</option>
                          <option value="reddit">Reddit</option>
                        </select>
                        <input
                          value={feedRound}
                          onChange={(event) => setFeedRound(event.target.value)}
                          onBlur={() => void handleFilter({ round: feedRound })}
                          placeholder="ronda"
                          className="w-16 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-zinc-200"
                        />
                        {feedAgent !== null ? (
                          <button
                            onClick={() => void handleFilter({ agentId: null })}
                            className="rounded-lg border border-zinc-800 px-2 py-1 text-zinc-300 hover:border-zinc-600"
                          >
                            limpar agente
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-3 space-y-2">
                      {actions.length === 0 ? (
                        <p className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-sm text-zinc-400">
                          Sem ações para os filtros escolhidos.
                        </p>
                      ) : null}
                      {actions.slice(0, 60).map((action) => (
                        <ActionCard key={action.id} action={action} onAgent={(agentId) => void handleFilter({ agentId: agentId ?? null })} />
                      ))}
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <button
                        onClick={() => void handleLoadMore()}
                        className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                      >
                        {busy === "more" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Carregar mais
                      </button>
                      <span className="text-[11px] text-zinc-500">
                        {actions.length} de {formatNumber(metrics?.actions_total)} ações
                      </span>
                    </div>
                  </div>
                </>
              )
            ) : null}

            {tab === "elenco" ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <Users size={16} className="text-violet-400" /> Elenco da simulação ({filteredCast.length}/{cast.length})
                    </h3>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <div className="relative">
                        <Search size={13} className="absolute left-2 top-2 text-zinc-500" />
                        <input
                          value={castQuery}
                          onChange={(event) => setCastQuery(event.target.value)}
                          placeholder="procurar agente…"
                          className="rounded-lg border border-zinc-800 bg-zinc-950 py-1 pl-7 pr-2 text-xs text-zinc-200"
                        />
                      </div>
                      <select
                        value={castType}
                        onChange={(event) => setCastType(event.target.value)}
                        className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                      >
                        <option value="">todos os tipos</option>
                        {(overview?.state_counts ?? []).map((row) => (
                          <option key={row.type} value={row.type}>
                            {row.type} ({row.count})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-zinc-500">
                    Cada agente representa uma entidade real extraída do grafo (adjudicantes, tribunais, insolventes, pessoas,
                    media) com personalidade, influência e horários próprios.
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {filteredCast.map((agent) => (
                    <button
                      key={`${agent.agent_id}-${agent.name}`}
                      onClick={() => {
                        setOpenAgent(agent);
                        setInterviewTarget(agent.agent_id ?? null);
                      }}
                      className={`rounded-xl border p-3 text-left transition ${
                        openAgent?.agent_id === agent.agent_id ? "border-cyan-700/70 bg-cyan-950/20" : "border-zinc-800 bg-zinc-900/40 hover:border-zinc-700"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-sm font-medium text-zinc-100">{agent.name}</span>
                        <span className="rounded-full bg-zinc-800/80 px-2 py-0.5 text-[10px] text-zinc-300">
                          {agent.entity_type || "sem tipo"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-zinc-400">
                        <span className="rounded border border-zinc-800 px-1.5 py-0.5">influência {agent.influence ?? "—"}</span>
                        <span className="rounded border border-zinc-800 px-1.5 py-0.5">atividade {agent.activity ?? "—"}</span>
                        {agent.mbti ? <span className="rounded border border-zinc-800 px-1.5 py-0.5">{agent.mbti}</span> : null}
                        <span className="rounded border border-zinc-800 px-1.5 py-0.5">
                          {formatNumber(agent.actions_total)} ações
                        </span>
                      </div>
                      {agent.bio ? <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-zinc-400">{agent.bio}</p> : null}
                    </button>
                  ))}
                </div>

                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Mic size={16} className="text-cyan-400" /> Entrevistar os agentes
                  </h3>
                  <p className="mt-1 text-xs text-zinc-500">
                    Pergunte ao enxame o que espera que aconteça. Sem agente escolhido, a pergunta vai a todos (pode demorar).
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <input
                      value={interviewPrompt}
                      onChange={(event) => setInterviewPrompt(event.target.value)}
                      className="min-w-[260px] flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    />
                    <select
                      value={interviewTarget ?? ""}
                      onChange={(event) => setInterviewTarget(event.target.value === "" ? null : Number(event.target.value))}
                      className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-2 text-sm text-zinc-200"
                    >
                      <option value="">todos os agentes</option>
                      {cast.map((agent) => (
                        <option key={`pick-${agent.agent_id}`} value={agent.agent_id ?? ""}>
                          {agent.name}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => void handleInterview()}
                      disabled={!selectedId}
                      className="inline-flex items-center gap-2 rounded-lg bg-cyan-500/90 px-3 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-400 disabled:opacity-50"
                    >
                      {busy === "interview" ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Perguntar
                    </button>
                  </div>
                  {interviewResult ? (
                    <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs text-zinc-300">
                      {interviewResult}
                    </pre>
                  ) : null}
                </div>

                {openAgent ? (
                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-zinc-100">{openAgent.name}</h3>
                      <button onClick={() => setOpenAgent(null)} className="text-xs text-zinc-400 hover:text-zinc-200">
                        fechar
                      </button>
                    </div>
                    <div className="mt-2 grid gap-2 text-xs text-zinc-400 sm:grid-cols-4">
                      <span>tipo: {openAgent.entity_type || "—"}</span>
                      <span>idade: {openAgent.age ?? "—"}</span>
                      <span>género: {openAgent.gender ?? "—"}</span>
                      <span>país: {openAgent.country ?? "—"}</span>
                      <span>influência: {openAgent.influence ?? "—"}</span>
                      <span>atividade: {openAgent.activity ?? "—"}</span>
                      <span>tom: {openAgent.stance || "—"}</span>
                      <span>sentimento: {openAgent.sentiment ?? "—"}</span>
                      <span className="sm:col-span-4">
                        ações: {formatNumber(openAgent.actions_twitter)} twitter · {formatNumber(openAgent.actions_reddit)} reddit
                        {openAgent.last_action_at ? ` · última ${formatDate(openAgent.last_action_at)}` : ""}
                      </span>
                      {openAgent.topics?.length ? <span className="sm:col-span-4">temas: {openAgent.topics.join(" · ")}</span> : null}
                      {openAgent.active_hours?.length ? (
                        <span className="sm:col-span-4">horas ativas: {openAgent.active_hours.join(", ")}h</span>
                      ) : null}
                    </div>
                    {openAgent.bio ? (
                      <div className="prose prose-invert mt-3 max-w-none text-sm">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{openAgent.bio}</ReactMarkdown>
                      </div>
                    ) : null}
                    {openAgent.persona ? (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-zinc-400">persona completa</summary>
                        <div className="prose prose-invert mt-2 max-w-none text-xs">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{openAgent.persona}</ReactMarkdown>
                        </div>
                      </details>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            {tab === "grafo" ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <Network size={16} className="text-cyan-400" /> Grafo de conhecimento (Zep)
                    </h3>
                    {graph ? (
                      <span className="text-xs text-zinc-500">
                        {formatNumber(graph.node_count)} entidades · {formatNumber(graph.edge_count)} factos · grafo{" "}
                        {graph.graph_id}
                      </span>
                    ) : null}
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-950/60 p-1">
                        {(["network", "hierarchical", "circular"] as const).map((option) => (
                          <button
                            key={option}
                            onClick={() => {
                              setGraphLayout(option);
                              setGraphVersion((version) => version + 1);
                            }}
                            className={`rounded-md px-2 py-1 text-[11px] transition ${
                              graphLayout === option ? "bg-cyan-500/20 text-cyan-200" : "text-zinc-400 hover:text-zinc-200"
                            }`}
                          >
                            {option === "network" ? "Rede" : option === "hierarchical" ? "Hierarquia" : "Circular"}
                          </button>
                        ))}
                      </div>
                      <div className="relative">
                        <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-zinc-500" />
                        <input
                          value={graphQuery}
                          onChange={(event) => setGraphQuery(event.target.value)}
                          placeholder="Procurar entidade…"
                          autoComplete="off"
                          className="w-44 rounded-lg border border-zinc-800 bg-zinc-950/60 py-1.5 pl-7 pr-2 text-xs text-zinc-200 placeholder:text-zinc-600"
                        />
                      </div>
                      <button
                        onClick={() => void loadGraph(selectedId)}
                        className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                      >
                        <RefreshCw size={13} className={graphLoading ? "animate-spin" : ""} /> Recarregar grafo
                      </button>
                    </div>
                  </div>

                  {graph?.types?.length ? (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <span className="text-[11px] uppercase tracking-wide text-zinc-500">Tipos de entidade</span>
                      {graph.types.map((row) => {
                        const hiddenType = graphHidden.includes(row.type);
                        return (
                          <button
                            key={row.type}
                            onClick={() =>
                              setGraphHidden((current) =>
                                current.includes(row.type) ? current.filter((item) => item !== row.type) : [...current, row.type],
                              )
                            }
                            title={hiddenType ? "Mostrar este tipo" : "Esconder este tipo"}
                            className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition ${
                              hiddenType ? "border-zinc-800 text-zinc-600" : "border-zinc-700 text-zinc-300"
                            }`}
                          >
                            <span
                              className="h-2 w-2 rounded-full"
                              style={{ background: hiddenType ? "#52525b" : entityColor(row.type) }}
                            />
                            {row.type} · {row.count}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {graph?.relations?.length ? (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="text-[11px] uppercase tracking-wide text-zinc-500">Factos</span>
                      {graph.relations.slice(0, 12).map((row) => (
                        <span key={row.type} className="rounded-full bg-zinc-800/60 px-2 py-0.5 text-[10px] text-zinc-400">
                          {row.type.toLowerCase().replace(/_/g, " ")} · {row.count}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>

                {!selectedId ? (
                  <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
                    Escolha uma simulação para ver o grafo de conhecimento.
                  </p>
                ) : !graph && graphLoading ? (
                  <p className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
                    <Loader2 size={15} className="animate-spin" /> A ler o grafo do Zep…
                  </p>
                ) : !graph ? (
                  <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
                    Esta simulação ainda não tem grafo (o passo «Construir o grafo» não correu, ou falhou).
                  </p>
                ) : (
                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
                    <div className="min-w-0">
                      <GraphCanvas
                        graph={studioGraph}
                        layout={graphLayout}
                        metric="contratos"
                        unitLabel="ligações"
                        heightClass="h-[620px]"
                        selectedNodeId={graphNode?.id ?? null}
                        layoutVersion={graphVersion}
                        loading={graphLoading}
                        nodeSummary={(node) =>
                          `${node.role ?? "entidade"} · ${formatNumber(node.count)} ${node.count === 1 ? "ligação" : "ligações"}`
                        }
                        edgeSummary={(edge) => {
                          const raw = graphFacts.get(`${edge.source}|${edge.target}`);
                          return raw ? `${raw.type.toLowerCase().replace(/_/g, " ")}: ${raw.fact}` : "facto do grafo";
                        }}
                        onNodeClick={(node) => {
                          const raw = graph.nodes.find((item) => item.id === node.id) ?? null;
                          setGraphNode((current) => (current?.id === node.id ? null : raw));
                        }}
                      />
                      {graph.omitted.nodes || graph.omitted.edges ? (
                        <p className="mt-2 text-xs text-zinc-500">
                          Para o desenho manter-se legível mostram-se os nós mais ligados: ficaram de fora{" "}
                          {formatNumber(graph.omitted.nodes)} entidades e {formatNumber(graph.omitted.edges)} factos.
                        </p>
                      ) : null}
                    </div>

                    <aside className="space-y-3">
                      {graphNode ? (
                        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                          <div className="flex items-start justify-between gap-2">
                            <h4 className="text-sm font-semibold text-zinc-100">{graphNode.name}</h4>
                            <button
                              onClick={() => setGraphNode(null)}
                              className="rounded-md px-1.5 text-xs text-zinc-500 transition hover:text-zinc-300"
                            >
                              fechar
                            </button>
                          </div>
                          <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-400">
                            <span className="h-2 w-2 rounded-full" style={{ background: entityColor(graphNode.type) }} />
                            {graphNode.type} · {formatNumber(graphNode.degree)}{" "}
                            {graphNode.degree === 1 ? "ligação" : "ligações"}
                          </p>
                          {graphNode.summary ? (
                            <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">{graphNode.summary}</p>
                          ) : null}
                          <dl className="mt-3 space-y-1 text-[11px] text-zinc-500">
                            <div className="flex gap-2">
                              <dt className="w-16 shrink-0">uuid</dt>
                              <dd className="truncate font-mono text-zinc-400">{graphNode.id}</dd>
                            </div>
                            <div className="flex gap-2">
                              <dt className="w-16 shrink-0">criado</dt>
                              <dd className="text-zinc-400">{formatDate(graphNode.created_at)}</dd>
                            </div>
                            {graphNode.labels.length ? (
                              <div className="flex gap-2">
                                <dt className="w-16 shrink-0">etiquetas</dt>
                                <dd className="text-zinc-400">{graphNode.labels.join(", ")}</dd>
                              </div>
                            ) : null}
                          </dl>
                          {Object.entries(graphNode.attributes).filter(([, value]) => value !== null && value !== "").length ? (
                            <div className="mt-3 space-y-1 border-t border-zinc-800 pt-2 text-[11px]">
                              {Object.entries(graphNode.attributes)
                                .filter(([, value]) => value !== null && value !== "")
                                .map(([key, value]) => (
                                  <div key={key} className="flex gap-2">
                                    <span className="w-28 shrink-0 text-zinc-500">{key}</span>
                                    <span className="text-zinc-300">{String(value)}</span>
                                  </div>
                                ))}
                            </div>
                          ) : null}
                        </div>
                      ) : (
                        <p className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 text-xs text-zinc-500">
                          Clique num nó para ver o resumo, os atributos e os factos que o ligam ao resto do grafo. Passe o rato
                          por cima para ler a frase de cada facto.
                        </p>
                      )}

                      {nodeRelations.length ? (
                        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                          <h5 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                            Factos ({nodeRelations.length})
                          </h5>
                          <ul className="mt-2 space-y-2">
                            {nodeRelations.map(({ edge, outgoing, other }) => (
                              <li key={edge.id} className="text-[11px] leading-relaxed text-zinc-400">
                                <span className="text-zinc-300">
                                  {outgoing ? "→" : "←"} {other}
                                </span>
                                <span className="ml-1.5 rounded bg-zinc-800/70 px-1.5 py-0.5 text-[10px] text-zinc-400">
                                  {edge.type.toLowerCase().replace(/_/g, " ")}
                                </span>
                                <p className="mt-0.5 text-zinc-400">{edge.fact}</p>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </aside>
                  </div>
                )}
              </div>
            ) : null}

            {tab === "relatorio" ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <FileText size={16} className="text-emerald-400" /> Relatório do enxame
                    </h3>
                    <StatePill state={reportView?.status} />
                    <div className="ml-auto flex items-center gap-2">
                      {reportView?.report_id ? (
                        <a
                          href={`${publicUrl}/report/${reportView.report_id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                        >
                          <Download size={13} /> Ver no MiroFish
                        </a>
                      ) : null}
                      <button
                        onClick={() => void handleGenerateReport(Boolean(reportView?.has_report))}
                        disabled={!selectedId || overview?.active}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-500/90 px-3 py-1.5 text-xs font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:opacity-50"
                      >
                        {busy === "report" ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                        {reportView?.has_report ? "Regenerar relatório" : "Escrever relatório"}
                      </button>
                    </div>
                  </div>
                  {overview?.report_hint ? (
                    <p className="mt-2 rounded-lg border border-amber-900/60 bg-amber-950/30 p-2 text-xs text-amber-200">
                      {overview.report_hint}
                    </p>
                  ) : null}
                  {reportView?.report?.words ? (
                    <p className="mt-2 text-xs text-zinc-500">
                      {formatNumber(reportView.report.words)} palavras · {reportView.report.sections.length} secções ·{" "}
                      {reportView.report.completed_at ? `concluído ${formatDate(reportView.report.completed_at)}` : "em curso"}
                    </p>
                  ) : null}
                </div>

                {reportView?.report?.markdown ? (
                  <>
                    <div className="flex flex-wrap gap-2">
                      {reportView.report.sections.map((section) => (
                        <span
                          key={section.title}
                          className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-2 py-1 text-[11px] text-zinc-300"
                        >
                          {section.title} · {formatNumber(section.chars)}
                        </span>
                      ))}
                    </div>
                    <article className="prose prose-invert max-w-none rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5 text-sm">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportView.report.markdown}</ReactMarkdown>
                    </article>
                  </>
                ) : (
                  <p className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
                    Ainda não há relatório para esta simulação. O MiroFish só o escreve depois de a execução terminar — use
                    «Escrever relatório».
                  </p>
                )}

                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <MessageSquare size={16} className="text-cyan-400" /> Perguntar ao relatório
                  </h3>
                  <p className="mt-1 text-xs text-zinc-500">
                    As respostas são construídas a partir do grafo de conhecimento da simulação, com as fontes citadas.
                  </p>
                  <div className="mt-3 space-y-2">
                    {chatMessages.map((message, index) => (
                      <div
                        key={`${index}-${message.role}`}
                        className={`rounded-xl border p-3 text-sm ${
                          message.role === "user" ? "border-cyan-900/60 bg-cyan-950/20 text-cyan-100" : "border-zinc-800 bg-zinc-950/60 text-zinc-200"
                        }`}
                      >
                        <div className="prose prose-invert max-w-none text-sm">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                        </div>
                        {message.sources?.length ? (
                          <p className="mt-2 text-[11px] text-zinc-500">fontes: {message.sources.join(" · ")}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <input
                      value={chatQuestion}
                      onChange={(event) => setChatQuestion(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void handleAskReport();
                      }}
                      placeholder="Ex.: que setores correm mais risco nos próximos 6 meses?"
                      className="flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    />
                    <button
                      onClick={() => void handleAskReport()}
                      disabled={!selectedId}
                      className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50"
                    >
                      {busy === "ask" ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Enviar
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "nova" ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Wand2 size={16} className="text-cyan-400" /> 1. Fonte de dados
                  </h3>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {sources.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => setSourceId(item.id)}
                        className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                          source?.id === item.id ? "border-cyan-700/70 bg-cyan-950/20 text-cyan-100" : "border-zinc-800 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700"
                        }`}
                      >
                        <div className="font-medium">{item.label}</div>
                        <div className="mt-0.5 max-w-[280px] text-[11px] text-zinc-500">{item.hint}</div>
                      </button>
                    ))}
                  </div>
                  {source?.params?.length ? (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {source.params.map((param) => (
                        <label key={param.name} className="text-xs text-zinc-400">
                          {param.label}
                          <input
                            value={params[param.name] ?? ""}
                            onChange={(event) => setParams((current) => ({ ...current, [param.name]: event.target.value }))}
                            placeholder={param.placeholder}
                            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                          />
                        </label>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Activity size={16} className="text-violet-400" /> 2. Pedido de previsão
                  </h3>
                  <textarea
                    value={requirement}
                    onChange={(event) => setRequirement(event.target.value)}
                    rows={4}
                    className="mt-3 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                  />
                  <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <label className="text-xs text-zinc-400">
                      Rondas
                      <input
                        value={maxRounds}
                        onChange={(event) => setMaxRounds(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                      />
                    </label>
                    <label className="text-xs text-zinc-400">
                      Plataformas
                      <select
                        value={platform}
                        onChange={(event) => setPlatform(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                      >
                        <option value="parallel">Twitter + Reddit</option>
                        <option value="twitter">Só Twitter</option>
                        <option value="reddit">Só Reddit</option>
                      </select>
                    </label>
                    <div className="sm:col-span-2">
                      <span className="text-xs text-zinc-400">Passos</span>
                      <div className="mt-1 flex flex-wrap gap-2">
                        {Object.keys(STEP_LABELS).map((step) => (
                          <label
                            key={step}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-950/60 px-2 py-1 text-[11px] text-zinc-300"
                          >
                            <input
                              type="checkbox"
                              checked={Boolean(steps[step])}
                              onChange={(event) => setSteps((current) => ({ ...current, [step]: event.target.checked }))}
                            />
                            {STEP_LABELS[step]}
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => void handlePreviewSeed()}
                      className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500"
                    >
                      {busy === "preview" ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />} Pré-visualizar semente
                    </button>
                    <button
                      onClick={() => void handleSaveSeed()}
                      className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500"
                    >
                      {busy === "save" ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />} Guardar no Office
                    </button>
                    <button
                      onClick={() => void handleSimulate()}
                      disabled={!serviceAvailable || Boolean(busy)}
                      className="inline-flex items-center gap-2 rounded-lg bg-cyan-500/90 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-400 disabled:opacity-50"
                    >
                      {busy === "simulate" ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />} Simular com estes dados
                    </button>
                    <span className="text-[11px] text-zinc-500">
                      <Clock size={11} className="mr-1 inline" /> cada ronda chama o LLM por agente e pode demorar minutos.
                    </span>
                  </div>
                </div>

                {seed ? (
                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <h3 className="text-sm font-semibold text-zinc-200">
                      Semente: {seed.title} — {formatNumber(seed.chars)} caracteres
                    </h3>
                    <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border border-zinc-800 bg-zinc-950/70 p-3 text-xs text-zinc-300">
                      {seed.markdown}
                    </pre>
                  </div>
                ) : null}

                {jobs.length ? (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Trabalhos</h3>
                    {jobs.map((job) => (
                      <details key={job.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3" open={job.status === "running"}>
                        <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm text-zinc-200">
                          <span className="font-medium">{job.title}</span>
                          <span className="text-xs text-zinc-500">{job.id}</span>
                          <span className="ml-auto text-xs text-zinc-400">
                            {job.step} · {job.progress}%
                          </span>
                          <StatePill
                            state={{
                              key: job.status,
                              label: job.status === "running" ? "a correr" : job.status === "done" ? "concluído" : "falhou",
                              tone: job.status === "running" ? "busy" : job.status === "done" ? "ok" : "error",
                            }}
                          />
                        </summary>
                        {job.error ? (
                          <p className="mt-2 rounded-lg border border-red-900/60 bg-red-950/40 p-2 text-xs text-red-200">
                            {job.error}
                            {job.hint ? <span className="mt-1 block text-red-300">{job.hint}</span> : null}
                          </p>
                        ) : null}
                        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-400">
                          {job.log.map((entry) => `${entry.at} ${entry.message}`).join("\n")}
                        </pre>
                      </details>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {tab === "estudio" ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-400">
                  <Fish size={15} className="text-cyan-400" />
                  Estúdio original do MiroFish (a mesma app que a página iframe abre), servido pelo proxy de incorporação em{" "}
                  <code className="rounded bg-zinc-950 px-1 py-0.5 text-zinc-300">{publicUrl}</code>.
                  <a
                    href={`${publicUrl}/`}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1 text-zinc-200 transition hover:border-zinc-500"
                  >
                    <ExternalLink size={12} /> nova aba
                  </a>
                </div>
                <div className="overflow-hidden rounded-2xl border border-zinc-800 bg-black">
                  <iframe
                    key={publicUrl}
                    title="Estúdio MiroFish"
                    src={`${publicUrl}/`}
                    className="h-[72vh] w-full border-0"
                    allow="clipboard-read; clipboard-write"
                  />
                </div>
              </div>
            ) : null}

            {tab === "interacao" ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <Hand size={16} className="text-cyan-400" /> Ambiente de simulação
                    </h3>
                    {env ? (
                      <span className={`text-xs ${env.alive ? "text-emerald-400" : "text-zinc-500"}`}>
                        {env.alive ? "ativo" : "inativo"} · twitter {env.platforms.twitter ? "ligado" : "desligado"} · reddit{" "}
                        {env.platforms.reddit ? "ligado" : "desligado"}
                      </span>
                    ) : null}
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => void handleCheckEnv()}
                        className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                      >
                        <RefreshCw size={13} className={busy === "env" ? "animate-spin" : ""} /> Atualizar
                      </button>
                      <button
                        onClick={() => void handleCloseEnv()}
                        disabled={!env?.alive}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-900/60 px-3 py-1.5 text-xs text-red-200 transition hover:border-red-700 disabled:opacity-50"
                      >
                        {busy === "close-env" ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />} Fechar
                      </button>
                      <button
                        onClick={() => void handleStartRun()}
                        disabled={!selectedId}
                        className="inline-flex items-center gap-2 rounded-lg bg-cyan-500/90 px-3 py-1.5 text-xs font-medium text-zinc-950 transition hover:bg-cyan-400 disabled:opacity-50"
                      >
                        {busy === "start-run" ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />} Correr / reiniciar
                      </button>
                    </div>
                  </div>
                  {env?.interview_hint ? <p className="mt-2 text-xs text-zinc-500">{env.interview_hint}</p> : null}
                  {env?.message ? <p className="mt-2 text-xs text-zinc-400">{env.message}</p> : null}
                </div>

                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Mic size={16} className="text-violet-400" /> Entrevista em lote
                  </h3>
                  <p className="mt-1 text-xs text-zinc-500">
                    Pergunte a vários agentes ao mesmo tempo. Indique os IDs separados por vírgula ou deixe em branco para
                    perguntar a todos.
                  </p>
                  <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                    <input
                      value={batchPrompt}
                      onChange={(event) => setBatchPrompt(event.target.value)}
                      className="min-w-[260px] flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    />
                    <input
                      value={batchAgents}
                      onChange={(event) => setBatchAgents(event.target.value)}
                      placeholder="IDs dos agentes"
                      className="w-40 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    />
                    <select
                      value={batchPlatform}
                      onChange={(event) => setBatchPlatform(event.target.value)}
                      className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-2 text-sm text-zinc-200"
                    >
                      <option value="">todas</option>
                      <option value="twitter">Twitter</option>
                      <option value="reddit">Reddit</option>
                    </select>
                    <button
                      onClick={() => void handleBatchInterview()}
                      disabled={!selectedId}
                      className="inline-flex items-center gap-2 rounded-lg bg-cyan-500/90 px-3 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-400 disabled:opacity-50"
                    >
                      {busy === "batch-interview" ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Perguntar
                    </button>
                  </div>
                  {batchResult ? (
                    <div className="mt-3 space-y-2">
                      <p className="text-xs text-zinc-500">
                        Respostas: {batchResult.answered}/{batchResult.asked}
                      </p>
                      {batchResult.answers.map((answer, index) => (
                        <div key={`${index}-${answer.agent_id ?? "x"}`} className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-xs">
                          <div className="text-zinc-400">
                            {answer.agent_id ?? "todos"}
                            {answer.platform ? ` · ${PLATFORM_LABELS[answer.platform] ?? answer.platform}` : null}
                          </div>
                          <p className="mt-1 whitespace-pre-wrap text-zinc-300">{answer.response}</p>
                          {answer.error ? <p className="mt-1 text-red-300">{answer.error}</p> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <MessageSquare size={16} className="text-emerald-400" /> Publicações e comentários
                    </h3>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-950/60 p-1">
                        {(["posts", "comments"] as const).map((mode) => (
                          <button
                            key={mode}
                            onClick={() => setContentMode(mode)}
                            className={`rounded-md px-2 py-1 text-[11px] transition ${
                              contentMode === mode ? "bg-cyan-500/20 text-cyan-200" : "text-zinc-400 hover:text-zinc-200"
                            }`}
                          >
                            {mode === "posts" ? "Publicações" : "Comentários"}
                          </button>
                        ))}
                      </div>
                      <select
                        value={contentPlatform}
                        onChange={(event) => setContentPlatform(event.target.value)}
                        className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                      >
                        <option value="">todas as plataformas</option>
                        <option value="twitter">Twitter</option>
                        <option value="reddit">Reddit</option>
                      </select>
                      <button
                        onClick={() => void handleLoadContent()}
                        className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                      >
                        <RefreshCw size={13} className={busy === "content" ? "animate-spin" : ""} /> Carregar
                      </button>
                    </div>
                  </div>
                  {contentPage ? (
                    <div className="mt-3 space-y-2">
                      <p className="text-xs text-zinc-500">
                        {formatNumber(contentPage.total)} {contentMode === "posts" ? "publicações" : "comentários"} · plataforma{" "}
                        {contentPage.platform}
                      </p>
                      {(contentMode === "posts" ? contentPage.posts : contentPage.comments)?.map((item, index) => (
                        <pre
                          key={index}
                          className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-xs text-zinc-300"
                        >
                          {JSON.stringify(item, null, 2)}
                        </pre>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-zinc-500">Carregue para ver o conteúdo do mundo simulado.</p>
                  )}
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Terminal size={16} className="text-zinc-400" /> Registos do relatório
                      </h3>
                      <div className="ml-auto flex flex-wrap items-center gap-2">
                        <select
                          value={logKind}
                          onChange={(event) => setLogKind(event.target.value as "console" | "agent")}
                          className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                        >
                          <option value="console">consola</option>
                          <option value="agent">agente</option>
                        </select>
                        <button
                          onClick={() => void handleLoadLogs()}
                          className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                        >
                          <RefreshCw size={13} className={busy === "logs" ? "animate-spin" : ""} /> Carregar
                        </button>
                      </div>
                    </div>
                    {logLines ? (
                      <div className="mt-3 max-h-72 space-y-1 overflow-auto">
                        <p className="text-xs text-zinc-500">
                          {formatNumber(logLines.lines.length)} de {formatNumber(logLines.total_lines)} linhas
                          {logLines.has_more ? " (há mais)" : ""}
                        </p>
                        {logLines.lines.map((line, index) => (
                          <pre
                            key={index}
                            className="whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950/60 p-2 text-[11px] text-zinc-300"
                          >
                            {typeof line === "string" ? line : JSON.stringify(line)}
                          </pre>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Search size={16} className="text-cyan-400" /> Procurar no grafo
                      </h3>
                      <div className="ml-auto flex items-center gap-2">
                        <input
                          value={graphSearchQuery}
                          onChange={(event) => setGraphSearchQuery(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") void handleGraphSearch();
                          }}
                          placeholder="Facto ou entidade…"
                          autoComplete="off"
                          className="w-44 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-100"
                        />
                        <button
                          onClick={() => void handleGraphSearch()}
                          className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                        >
                          {busy === "graph-search" ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
                        </button>
                        <button
                          onClick={() => void handleGraphStats()}
                          className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 transition hover:border-zinc-500"
                        >
                          {busy === "graph-stats" ? <Loader2 size={13} className="animate-spin" /> : <BarChart3 size={13} />} Estatísticas
                        </button>
                      </div>
                    </div>
                    {graphSearchResult?.facts?.length ? (
                      <div className="mt-3 space-y-1">
                        <p className="text-xs text-zinc-500">Factos ({graphSearchResult.facts.length})</p>
                        {graphSearchResult.facts.map((fact, index) => (
                          <p key={index} className="text-xs leading-relaxed text-zinc-300">
                            {fact.fact}
                          </p>
                        ))}
                      </div>
                    ) : null}
                    {graphSearchResult?.nodes?.length ? (
                      <div className="mt-3 space-y-1">
                        <p className="text-xs text-zinc-500">Entidades ({graphSearchResult.nodes.length})</p>
                        {graphSearchResult.nodes.map((node, index) => (
                          <div key={index} className="text-xs text-zinc-300">
                            <span className="text-zinc-500">{node.type}</span> · {node.name}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {graphStatsResult ? (
                      <div className="mt-3 space-y-1 text-xs text-zinc-300">
                        <p>
                          {formatNumber(graphStatsResult.node_count)} nós · {formatNumber(graphStatsResult.edge_count)} arestas
                        </p>
                        <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-zinc-800 bg-zinc-950/60 p-3 text-[11px] text-zinc-400">
                          {JSON.stringify(graphStatsResult.detail, null, 2)}
                        </pre>
                      </div>
                    ) : null}
                    {!graphSearchResult && !graphStatsResult ? (
                      <p className="mt-3 text-sm text-zinc-500">
                        Pesquise um facto no grafo do Zep ou peça as estatísticas (nós, arestas e tipos de entidade).
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}

            {selected ? (
              <p className="pt-2 text-center text-[11px] text-zinc-600">
                Simulação {selected.simulation_id} · estado {selected.state.label} · atualizado {formatDate(overview?.simulation.updated_at)}
              </p>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}
