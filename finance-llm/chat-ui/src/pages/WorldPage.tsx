/**
 * World Model — do dado público ao relatório de investigação.
 *
 * A página segue o pipeline do módulo, camada a camada:
 *
 * 1. **Pipeline** — as fontes públicas (contratos PT/ES, entidades, CIRE,
 *    pessoas, contribuintes), o estado do mundo e os botões de reconstrução e
 *    de treino da rede, com o progresso das execuções.
 * 2. **Mundo** — pesquisa de entidades do estado materializado (tipo, risco,
 *    insolvência) e ficha com estado, métricas, previsão da rede, relações e
 *    linha temporal.
 * 3. **Eventos** — linha temporal, série mensal e influências temporais
 *    candidatas (causalidade).
 * 4. **Grafo** — o grafo de relações do mundo no canvas do estúdio (ego-rede,
 *    profundidade, tipo de relação), centralidade e caminhos entre entidades.
 * 5. **Rede** — a **rede neuronal dinâmica desenhada como grafo**: neurónios
 *    (entidades) e sinapses (relações), padrões de memória como nós, métricas de
 *    crescimento/poda/previsão e histórico de ciclos.
 * 6. **Simulador** — t0 → t3 com três cenários, distribuições por passo e totais.
 * 7. **Investigação** — o agente (Observe → Hypothesize → Search → Validate →
 *    Simulate → Report) com hipóteses, evidência, validação e relatório.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Brain,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  Gavel,
  Layers,
  Loader2,
  Microscope,
  Network,
  Play,
  RefreshCw,
  Search,
  Share2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
  X,
  Zap,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import type { GraphMetric, StudioView } from "../components/graph/graphStudio";
import {
  executionNodeSummary,
  evidenceNodeSummary,
  networkEdgeSummary,
  networkNodeSummary,
  pipelineNodeSummary,
  toEvidenceStudioGraph,
  toExecutionStudioGraph,
  toNetworkStudioGraph,
  toPipelineStudioGraph,
  toWorldStudioGraph,
  worldEdgeSummary,
  worldNodeSummary,
} from "../components/world/worldGraphs";
import { MermaidDiagram } from "../components/world/MermaidDiagram";
import { useAuth } from "../auth";
import {
  getAgentCatalog,
  getAgentTargets,
  getEntityHistory,
  getEntityTransition,
  getWorldAgentRun,
  getWorldAgentRuns,
  getWorldAnomalies,
  getWorldArchitecture,
  getWorldCentrality,
  getWorldCausality,
  getWorldEntity,
  getWorldEvents,
  getWorldGraph,
  getWorldHistorySeries,
  getWorldInvestigation,
  getWorldInvestigations,
  getWorldJobs,
  getWorldMeta,
  getWorldNetwork,
  getWorldNetworkGraph,
  getWorldNetworkHistory,
  getWorldNetworkRecall,
  getWorldPaths,
  getWorldPipelineGraph,
  getWorldSimulations,
  getWorldSources,
  getWorldStatus,
  getWorldTemporal,
  getWorldTransition,
  investigateWorld,
  rebuildWorld,
  runWorldAgent,
  runWorldSimulation,
  saveWorldSources,
  searchWorldEntities,
  trainWorldNetwork,
  type AgentRun,
  type Anomaly,
  type HistoryRow,
  type Investigation,
  type NetworkGraph,
  type PipelineGraph,
  type SimulationRun,
  type TransitionModel,
  type WorldArchitectureLayer,
  type WorldEntity,
  type WorldEvent,
  type WorldGraph,
  type WorldJob,
  type WorldSource,
} from "../worldApi";

type Section = "pipeline" | "mundo" | "eventos" | "grafo" | "rede" | "simulador" | "agente" | "investigacao";

const SECTIONS: { id: Section; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "pipeline", label: "Pipeline", icon: <Layers size={13} />, hint: "Grafo de execução: Public Data → … → Evidence Graph" },
  { id: "mundo", label: "Mundo", icon: <Database size={13} />, hint: "Estado materializado: entidades, risco e atividade" },
  { id: "eventos", label: "Eventos", icon: <Clock size={13} />, hint: "Linha temporal, evolução por período e causalidade" },
  { id: "grafo", label: "Grafo", icon: <Share2 size={13} />, hint: "Relações entre entidades, centralidade e caminhos" },
  { id: "rede", label: "Rede (grafo)", icon: <Brain size={13} />, hint: "Rede neuronal dinâmica, anomalias e transição latente" },
  { id: "simulador", label: "Simulador", icon: <FlaskConical size={13} />, hint: "t0 → t3: contratos, atrasos, cancelamentos e risco" },
  { id: "agente", label: "Agente", icon: <Microscope size={13} />, hint: "Agente sobre a rede: plano, evidência, cenários e grafos" },
  { id: "investigacao", label: "Investigação", icon: <Gavel size={13} />, hint: "Observe → Hypothesize → Search → Validate → Simulate → Report" },
];

const ANOMALY_STYLES: Record<string, string> = {
  "anómalo": "border-rose-400/30 bg-rose-400/10 text-rose-200",
  "atenção": "border-amber-400/30 bg-amber-400/10 text-amber-200",
};

const numberFormat = new Intl.NumberFormat("pt-PT");
const currencyFormat = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const compactCurrency = new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 });

const RISK_STYLES: Record<string, string> = {
  baixo: "border-teal-400/30 bg-teal-400/10 text-teal-200",
  médio: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  elevado: "border-rose-400/30 bg-rose-400/10 text-rose-200",
};

const CLAIM_STYLES: Record<string, string> = {
  FACT: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  CALCULATION: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  INFERENCE: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  HYPOTHESIS: "border-white/15 bg-white/5 text-muted-foreground",
};

function Pill({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function Stat({ label, value, hint, icon }: { label: string; value: React.ReactNode; hint?: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-foreground">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function Section({ children }: { children: React.ReactNode }) {
  return <div className="rounded-2xl border border-border bg-card p-4">{children}</div>;
}

function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 size={15} className="animate-spin" /> {label}
    </div>
  );
}

function ErrorBox({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      <span className="flex items-start gap-2">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        {message}
      </span>
      {onClose && (
        <button type="button" onClick={onClose} className="text-destructive/70 hover:text-destructive">
          <X size={14} />
        </button>
      )}
    </div>
  );
}

export default function WorldPage() {
  const { user } = useAuth();
  const hasSession = Boolean(user);
  const [section, setSection] = useState<Section>(() => {
    const path = typeof window === "undefined" ? "" : window.location.pathname;
    return path.startsWith("/world/rede") ? "rede" : "pipeline";
  });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Dados do módulo (carregam uma vez).
  const [architecture, setArchitecture] = useState<WorldArchitectureLayer[]>([]);
  const [sources, setSources] = useState<WorldSource[]>([]);
  /** Fontes mexidas mas ainda não gravadas (a associação só se aplica na reconstrução). */
  const [sourcesDirty, setSourcesDirty] = useState(false);
  const [savingSources, setSavingSources] = useState(false);
  const [sourcesNotice, setSourcesNotice] = useState("");
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);
  const [jobs, setJobs] = useState<WorldJob[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  // Mundo
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [sort, setSort] = useState("risk");
  const [entities, setEntities] = useState<WorldEntity[]>([]);
  const [entitiesTotal, setEntitiesTotal] = useState(0);
  const [selected, setSelected] = useState<WorldEntity | null>(null);
  const [detail, setDetail] = useState<{
    entity: WorldEntity;
    prediction: Record<string, unknown> | null;
    relations: {
      relation_id: string;
      source_ref: string;
      target_ref: string;
      source_name?: string | null;
      target_name?: string | null;
      contracts_count?: number;
      value_sum?: number;
    }[];
    timeline: WorldEvent[];
  } | null>(null);

  // Eventos
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [temporal, setTemporal] = useState<{ period: string; events: number; value: number }[]>([]);
  const [causality, setCausality] = useState<
    { cause: { entity_name?: string; event?: string; ts?: string }; effect: { entity_name?: string; event?: string; ts?: string }; score: number; days: number; interpretation: string }[]
  >([]);

  // Grafo
  const [graphOrigin, setGraphOrigin] = useState("");
  const [graphDepth, setGraphDepth] = useState(1);
  const [graphKind, setGraphKind] = useState("");
  const [graph, setGraph] = useState<WorldGraph | null>(null);
  const [graphView, setGraphView] = useState<StudioView>("network");
  const [centrality, setCentrality] = useState<{ entity_ref: string; name: string; degree: number; risk_label?: string }[]>([]);
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [paths, setPaths] = useState<{ id: string; name: string }[][] | null>(null);

  // Rede
  const [network, setNetwork] = useState<NetworkGraph | null>(null);
  const [networkSummary, setNetworkSummary] = useState<Record<string, unknown> | null>(null);
  const [networkHistory, setNetworkHistory] = useState<Record<string, unknown>[]>([]);
  const [memoryOnly, setMemoryOnly] = useState(true);
  const [recall, setRecall] = useState<{ pattern_id: string; label: string; similarity: number; hits?: number }[]>([]);

  // Simulador
  const [simSubject, setSimSubject] = useState("");
  const [simHorizon, setSimHorizon] = useState(4);
  const [simSamples, setSimSamples] = useState(300);
  const [simulation, setSimulation] = useState<SimulationRun | null>(null);
  const [history, setHistory] = useState<SimulationRun[]>([]);

  // Investigação
  const [question, setQuestion] = useState("Qual é o risco desta entidade e o que pode acontecer nos próximos 12 meses?");
  const [investigationSubject, setInvestigationSubject] = useState("");
  const [investigation, setInvestigation] = useState<Investigation | null>(null);

  // Pipeline / estado temporal / rede (anomalias e transição)
  const [pipelineGraph, setPipelineGraph] = useState<PipelineGraph | null>(null);
  const [worldHistory, setWorldHistory] = useState<{ period: string; contracts: number; value: number; new_counterparties: number }[]>([]);
  const [entityHistory, setEntityHistory] = useState<HistoryRow[]>([]);
  const [entityTransition, setEntityTransition] = useState<{ step: number; cum_contracts: number; risk: number }[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [transitionModel, setTransitionModel] = useState<TransitionModel | null>(null);

  // Agente sobre a rede
  const [agentCatalog, setAgentCatalog] = useState<{
    agents: { id: string; label: string; role: string; consumes: string[]; produces: string[] }[];
    mermaid: string;
  } | null>(null);
  const [agentTargets, setAgentTargets] = useState<
    { entity_ref: string; entity_name: string; score: number; label: string; signals: string[]; interpretation?: string }[]
  >([]);
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [agentQuestion, setAgentQuestion] = useState("O que se passa com esta entidade e o que pode acontecer nos próximos 12 meses?");
  const [pastInvestigations, setPastInvestigations] = useState<Investigation[]>([]);
  const reportRef = useRef<HTMLDivElement | null>(null);

  const metric: GraphMetric = "valor";

  /* -------------------------------------------------------------- carregar */

  const loadOverview = useCallback(async () => {
    const [arch, src, st, mt, jb, net] = await Promise.all([
      getWorldArchitecture().catch(() => ({ architecture: [] })),
      getWorldSources().catch(() => ({ sources: [] })),
      getWorldStatus().catch(() => null),
      getWorldMeta().catch(() => null),
      getWorldJobs().catch(() => ({ jobs: [] })),
      getWorldNetwork().catch(() => null),
    ]);
    setArchitecture(arch.architecture ?? []);
    setSources(src.sources ?? []);
    setSourcesDirty(false);
    setStatus(st);
    setMeta(mt);
    setJobs(jb.jobs ?? []);
    setNetworkSummary(net);
  }, []);

  useEffect(() => {
    void loadOverview().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [loadOverview]);

  /* ------------------------------------------------ fontes do Public Data */

  const toggleSource = (id: string) => {
    setSources((current) => current.map((item) => (item.id === id ? { ...item, associated: !item.associated } : item)));
    setSourcesDirty(true);
    setSourcesNotice("");
  };

  const handleSaveSources = async () => {
    setSavingSources(true);
    try {
      const ids = sources.filter((item) => item.associated || item.required).map((item) => item.id);
      const result = await saveWorldSources(ids);
      setSources(result.sources ?? []);
      setSourcesDirty(false);
      const ignored = (result.unknown ?? []).length;
      setSourcesNotice(
        ignored > 0
          ? `Associações gravadas (${result.associated?.length ?? ids.length} fontes). Ignoradas ${ignored} desconhecidas — reconstrua o mundo para aplicar.`
          : `Associações gravadas — reconstrua o mundo para as fontes novas entrarem no estado, eventos e relações.`,
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSavingSources(false);
    }
  };

  const loadEntities = useCallback(async () => {
    const result = await searchWorldEntities({
      q: query || undefined,
      type: typeFilter || undefined,
      risk: riskFilter || undefined,
      sort,
      size: 25,
    });
    setEntities(result.results ?? []);
    setEntitiesTotal(result.total ?? 0);
    if (result.error) setError(result.error);
  }, [query, riskFilter, sort, typeFilter]);

  useEffect(() => {
    if (section !== "mundo") return;
    void loadEntities().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [loadEntities, section]);

  const loadEvents = useCallback(async () => {
    const [ev, tp, cs] = await Promise.all([
      getWorldEvents({ size: 60 }),
      getWorldTemporal({ years: 6 }),
      getWorldCausality({ window_days: 60, limit: 12 }),
    ]);
    setEvents(ev.events ?? []);
    setTemporal((tp.series ?? []).slice(-48));
    setCausality((cs.links ?? []) as never);
  }, []);

  useEffect(() => {
    if (section !== "eventos") return;
    void loadEvents().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [loadEvents, section]);

  const loadGraph = useCallback(async () => {
    const [g, cent] = await Promise.all([
      getWorldGraph({ entity_ref: graphOrigin || undefined, depth: graphDepth, kind: graphKind || undefined, nodes: 120, edges: 400 }),
      getWorldCentrality({ top: 12 }),
    ]);
    setGraph(g);
    setCentrality(cent.results ?? []);
  }, [graphDepth, graphKind, graphOrigin]);

  useEffect(() => {
    if (section !== "grafo") return;
    void loadGraph().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [loadGraph, section]);

  const loadNetworkSignals = useCallback(async () => {
    const [anomalyPayload, transitionPayload] = await Promise.all([
      getWorldAnomalies({ limit: 60 }).catch(() => ({ available: false, anomalies: [] })),
      getWorldTransition().catch(() => null),
    ]);
    setAnomalies(anomalyPayload.anomalies ?? []);
    setTransitionModel(transitionPayload);
  }, []);

  const loadAgent = useCallback(async () => {
    const [catalog, targets, runs] = await Promise.all([
      getAgentCatalog().catch(() => null),
      getAgentTargets(12).catch(() => ({ targets: [] })),
      getWorldAgentRuns(10).catch(() => ({ runs: [] })),
    ]);
    setAgentCatalog(catalog);
    setAgentTargets(targets.targets ?? []);
    setAgentRuns(runs.runs ?? []);
  }, []);

  const loadPipelineGraph = useCallback(async () => {
    const [graphPayload, history] = await Promise.all([
      getWorldPipelineGraph().catch(() => null),
      getWorldHistorySeries({ grain: "quarter", limit: 16 }).catch(() => ({ series: [] })),
    ]);
    setPipelineGraph(graphPayload);
    setWorldHistory(history.series ?? []);
  }, []);

  const loadNetwork = useCallback(async () => {
    const [g, summary, hist] = await Promise.all([
      getWorldNetworkGraph({ limit: 90, memory: memoryOnly }).catch(() => null),
      getWorldNetwork().catch(() => null),
      getWorldNetworkHistory(12).catch(() => ({ history: [] })),
    ]);
    setNetwork(g);
    setNetworkSummary(summary);
    setNetworkHistory(hist.history ?? []);
    if (g?.error) setError(g.error);
  }, [memoryOnly]);

  const loadSimulations = useCallback(async () => {
    const result = await getWorldSimulations(10).catch(() => ({ simulations: [] }));
    setHistory(result.simulations ?? []);
  }, []);

  const loadInvestigations = useCallback(async () => {
    const result = await getWorldInvestigations(10).catch(() => ({ investigations: [] }));
    setPastInvestigations(result.investigations ?? []);
  }, []);

  // Estes efeitos usam as funções de carregamento acima, por isso ficam depois
  // delas (antes davam «usado antes de ser declarado»).
  useEffect(() => {
    if (section !== "rede") return;
    void loadNetwork().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
    void loadNetworkSignals().catch(() => undefined);
  }, [loadNetwork, loadNetworkSignals, section]);

  useEffect(() => {
    if (section !== "agente") return;
    void loadAgent().catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  }, [loadAgent, section]);

  useEffect(() => {
    if (section !== "pipeline") return;
    void loadPipelineGraph().catch(() => undefined);
  }, [loadPipelineGraph, section]);

  /* --------------------------------------------------------------- ações */

  const handleRebuild = async () => {
    if (!hasSession) {
      setError("Iniciar sessão é necessário para reconstruir o mundo.");
      return;
    }
    setBusy("rebuild");
    setError(null);
    try {
      const job = await rebuildWorld({});
      setNotice(`Reconstrução lançada (${job.job_id ?? "job"}). O progresso aparece em Execuções.`);
      await loadOverview();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handleTrain = async () => {
    if (!hasSession) {
      setError("Iniciar sessão é necessário para treinar a rede.");
      return;
    }
    setBusy("train");
    setError(null);
    try {
      const job = await trainWorldNetwork({});
      setNotice(`Ciclo da rede lançado (${job.job_id ?? "job"}).`);
      await loadNetwork();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const openEntity = async (entityRef: string) => {
    setError(null);
    try {
      const payload = await getWorldEntity(entityRef);
      setDetail(payload as never);
      setSelected(payload.entity);
      const [history, forecast] = await Promise.all([
        getEntityHistory(payload.entity.entity_ref, { limit: 40 }).catch(() => ({ series: [] })),
        getEntityTransition(payload.entity.entity_ref, 6).catch(() => null),
      ]);
      setEntityHistory(history.series ?? []);
      setEntityTransition(forecast?.steps ?? []);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const handleAgentRun = async (subjectOverride?: string) => {
    if (!agentQuestion.trim()) return;
    setBusy("agente");
    setError(null);
    try {
      const run = await runWorldAgent({
        question: agentQuestion.trim(),
        subject: subjectOverride,
        horizon: 4,
        samples: 300,
        simulate: true,
      });
      setAgentRun(run);
      await loadAgent();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handleRecall = async (entityRef: string) => {
    try {
      const payload = await getWorldNetworkRecall(entityRef);
      setRecall(payload.patterns ?? []);
      if (payload.error) setError(payload.error);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const handleSimulate = async () => {
    setBusy("simulate");
    setError(null);
    try {
      const run = await runWorldSimulation({
        subject: simSubject || undefined,
        horizon: simHorizon,
        samples: simSamples,
      });
      setSimulation(run);
      await loadSimulations();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handleInvestigate = async () => {
    if (!question.trim()) return;
    setBusy("investigate");
    setError(null);
    try {
      const run = await investigateWorld({
        question: question.trim(),
        subject: investigationSubject || undefined,
        horizon: 4,
        samples: 200,
      });
      setInvestigation(run);
      await loadInvestigations();
      window.setTimeout(() => reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const handlePaths = async () => {
    if (!pathFrom.trim() || !pathTo.trim()) return;
    try {
      const result = await getWorldPaths({ source: pathFrom.trim(), target: pathTo.trim() });
      setPaths(result.paths ?? []);
      if (!result.paths?.length) setNotice("Sem caminho encontrado entre as duas entidades no grafo atual.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  /* ---------------------------------------------------------- derivados */

  const studioGraph = useMemo(() => toWorldStudioGraph(graph), [graph]);
  const networkGraph = useMemo(() => toNetworkStudioGraph(network), [network]);
  const pipelineStudio = useMemo(() => toPipelineStudioGraph(pipelineGraph), [pipelineGraph]);
  const executionStudio = useMemo(() => toExecutionStudioGraph(agentRun?.execution_graph ?? null), [agentRun]);
  const evidenceStudio = useMemo(() => toEvidenceStudioGraph(agentRun?.evidence_graph ?? null), [agentRun]);
  const agentRelationsStudio = useMemo(() => toWorldStudioGraph((agentRun?.relations_graph as WorldGraph) ?? null), [agentRun]);

  const networkMetrics = useMemo(() => {
    const metrics = (network?.metrics ?? (networkSummary?.metrics as Record<string, number>) ?? {}) as Record<string, number>;
    return {
      nodes: metrics.nodes ?? network?.nodes?.length ?? 0,
      edges: metrics.edges ?? network?.edges?.length ?? 0,
      growth: metrics.edges_added ?? 0,
      pruned: metrics.edges_pruned ?? 0,
      memory: metrics.memory_patterns ?? network?.memory?.length ?? 0,
      r2: metrics.r2,
      rmse: metrics.rmse,
      sparsity: metrics.sparsity,
      growthFactor: metrics.growth_factor,
    };
  }, [network, networkSummary]);

  const scenarioChart = useMemo(() => {
    if (!simulation) return [];
    const labels = simulation.summary?.scenario_labels ?? [];
    const matrix = simulation.summary?.scenario_matrix ?? [];
    const steps = simulation.steps?.length ?? 0;
    return Array.from({ length: steps }, (_, index) => {
      const row: Record<string, number | string> = { step: `t${index + 1}` };
      labels.forEach((label, scenarioIndex) => {
        row[label] = matrix[scenarioIndex]?.[index] ?? 0;
      });
      return row;
    });
  }, [simulation]);

  const temporalChart = useMemo(
    () => temporal.map((item) => ({ period: (item.period ?? "").slice(0, 7), eventos: item.events, valor: Math.round(item.value ?? 0) })),
    [temporal],
  );

  /* ---------------------------------------------------------- render */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-gradient-to-br from-cyan-400 via-sky-500 to-indigo-600 p-2 text-white shadow">
            <Brain size={22} />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-foreground">World Model</h1>
            <p className="text-xs text-muted-foreground">
              Public Data → World Model → Rede dinâmica (grafo) → Grafo/Tempo → Simulador → Agente de investigação
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRebuild}
            disabled={busy === "rebuild"}
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-muted px-3 py-2 text-xs font-semibold text-foreground hover:bg-muted/70 disabled:opacity-60"
          >
            {busy === "rebuild" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Reconstruir mundo
          </button>
          <button
            type="button"
            onClick={handleTrain}
            disabled={busy === "train"}
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {busy === "train" ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
            Ciclo da rede
          </button>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-border px-4 py-2">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            title={item.hint}
            onClick={() => setSection(item.id)}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              section === item.id
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>

      <main className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {error && <ErrorBox message={error} onClose={() => setError(null)} />}
        {notice && (
          <div className="flex items-start justify-between gap-3 rounded-xl border border-teal-400/30 bg-teal-400/10 p-3 text-sm text-teal-200">
            <span className="flex items-start gap-2">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              {notice}
            </span>
            <button type="button" onClick={() => setNotice(null)} className="text-teal-200/70 hover:text-teal-100">
              <X size={14} />
            </button>
          </div>
        )}

        {/* ------------------------------------------------------- PIPELINE */}
        {section === "pipeline" && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Entidades no mundo"
                value={numberFormat.format(Number(((status?.indexes as Record<string, { documents: number }>)?.state?.documents) ?? 0))}
                hint={`versão ${String(status?.version ?? "—")}`}
                icon={<Database size={13} />}
              />
              <Stat
                label="Eventos"
                value={numberFormat.format(Number(((status?.indexes as Record<string, { documents: number }>)?.events?.documents) ?? 0))}
                hint="linha temporal"
                icon={<Clock size={13} />}
              />
              <Stat
                label="Relações"
                value={numberFormat.format(Number(((status?.indexes as Record<string, { documents: number }>)?.relations?.documents) ?? 0))}
                hint="arestas do grafo"
                icon={<Share2 size={13} />}
              />
              <Stat
                label="Padrões de memória"
                value={numberFormat.format(networkMetrics.memory)}
                hint={networkMetrics.r2 != null ? `readout R² ${networkMetrics.r2}` : "rede ainda sem ciclo"}
                icon={<Brain size={13} />}
              />
            </div>

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Share2 size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Grafo de execução do pipeline</h2>
                {pipelineGraph?.metrics && (
                  <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">
                    {numberFormat.format(pipelineGraph.metrics.documents)} documentos
                  </Pill>
                )}
              </div>
              <p className="mb-2 text-[11px] text-muted-foreground">
                Cada camada com os artefactos que produz (e a volumetria real). O diagrama abaixo é o mesmo grafo em
                Mermaid — copiável para relatórios.
              </p>
              <GraphCanvas
                graph={pipelineStudio}
                layout="hierarchical"
                metric="contratos"
                heightClass="h-[420px]"
                unitLabel="documentos"
                nodeSummary={pipelineNodeSummary}
              />
              {pipelineGraph?.mermaid && (
                <div className="mt-3">
                  <MermaidDiagram code={pipelineGraph.mermaid} title="Pipeline (Mermaid)" height={360} />
                </div>
              )}
            </Section>

            <Section>
              <div className="mb-3 flex items-center gap-2">
                <Layers size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Arquitetura em execução</h2>
              </div>
              <div className="space-y-2">
                {architecture.map((layer, index) => (
                  <div key={layer.id}>
                    <div className="rounded-xl border border-border bg-muted/40 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-sm font-semibold text-foreground">{layer.label}</div>
                        <code className="rounded bg-black/30 px-2 py-0.5 text-[11px] text-muted-foreground">{layer.backend}</code>
                      </div>
                      <p className="mt-0.5 text-xs text-muted-foreground">{layer.hint}</p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {layer.items.map((item) => (
                          <Pill key={item} className="border-white/10 bg-white/5 text-muted-foreground">
                            {item}
                          </Pill>
                        ))}
                      </div>
                    </div>
                    {index < architecture.length - 1 && (
                      <div className="flex justify-center py-1 text-muted-foreground">
                        <ChevronDown size={16} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2">
              <Section>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Database size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Public Data (fontes do sistema)</h2>
                  <Pill className="border-white/15 bg-white/5 text-muted-foreground">
                    {sources.filter((item) => item.associated).length} associadas
                  </Pill>
                  <button
                    type="button"
                    onClick={() => void handleSaveSources()}
                    disabled={savingSources || !sourcesDirty}
                    className="ml-auto inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
                  >
                    {savingSources ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                    guardar associações
                  </button>
                </div>
                <p className="mb-2 text-[11px] text-muted-foreground">
                  Associe as fontes do sistema que alimentam o mundo. Cada fonte declara <strong>como entra</strong>
                  (adaptador) e <strong>como se liga</strong> às entidades já conhecidas — por NIF (exato), por designação
                  legal ou pelo nome no texto. As associações aplicam-se na próxima reconstrução.
                </p>
                <div className="space-y-2">
                  {sources.map((source) => (
                    <label
                      key={source.id}
                      className={`flex cursor-pointer items-start justify-between gap-3 rounded-xl border p-3 ${
                        source.associated ? "border-primary/40 bg-primary/5" : "border-border bg-muted/30"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={Boolean(source.associated)}
                          disabled={Boolean(source.required) || !source.exists || savingSources}
                          onChange={() => toggleSource(source.id)}
                          className="mt-0.5"
                        />
                        <div>
                          <div className="text-sm font-medium text-foreground">
                            {source.label}
                            {source.default && (
                              <span className="ml-2 text-[10px] uppercase tracking-wide text-muted-foreground">omissão</span>
                            )}
                            {source.required && (
                              <span className="ml-2 text-[10px] uppercase tracking-wide text-amber-300">obrigatória</span>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground">{source.description}</div>
                          <div className="mt-1 flex flex-wrap items-center gap-2">
                            <code className="text-[11px] text-muted-foreground/80">{source.index}</code>
                            <Pill className="border-white/15 bg-white/5 text-muted-foreground">{source.adapter}</Pill>
                            <span className="text-[11px] text-muted-foreground/80">junção: {source.join}</span>
                            {(source.contributes ?? []).map((item) => (
                              <span key={item} className="text-[11px] text-muted-foreground/70">
                                {item}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                      <Pill
                        className={
                          source.exists
                            ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
                            : "border-white/15 bg-white/5 text-muted-foreground"
                        }
                      >
                        {source.exists ? numberFormat.format(source.documents ?? 0) : "sem índice"}
                      </Pill>
                    </label>
                  ))}
                  {sources.length === 0 && <Spinner label="A ler as fontes…" />}
                </div>
                {sourcesNotice && <p className="mt-2 text-[11px] text-teal-200">{sourcesNotice}</p>}
                {sourcesDirty && <p className="mt-2 text-[11px] text-amber-200">Alterações por gravar.</p>}
              </Section>

              <Section>
                <div className="mb-3 flex items-center gap-2">
                  <Activity size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Execuções</h2>
                  <button
                    type="button"
                    onClick={() => void getWorldJobs().then((payload) => setJobs(payload.jobs ?? []))}
                    className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                  >
                    atualizar
                  </button>
                </div>
                <div className="space-y-2">
                  {jobs.map((job) => (
                    <div key={job.job_id} className="rounded-xl border border-border bg-muted/30 p-3">
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium text-foreground">
                          {job.kind === "rebuild" ? "Reconstrução do mundo" : "Ciclo da rede"}
                        </span>
                        <Pill
                          className={
                            job.status === "concluído"
                              ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
                              : job.status === "falhou"
                                ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                                : "border-white/15 bg-white/5 text-muted-foreground"
                          }
                        >
                          {job.status}
                        </Pill>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {job.created_at?.slice(0, 19).replace("T", " ")}
                        {job.elapsed_s ? ` · ${job.elapsed_s}s` : ""}
                      </div>
                      {job.progress?.length > 0 && (
                        <ul className="mt-1 space-y-0.5 text-[11px] text-muted-foreground">
                          {job.progress.slice(-4).map((step, index) => (
                            <li key={`${job.job_id}-${index}`}>• {step.label}</li>
                          ))}
                        </ul>
                      )}
                      {job.error && <div className="mt-1 text-[11px] text-rose-300">{job.error}</div>}
                      {job.status === "concluído" && job.result && (
                        <div className="mt-1 text-[11px] text-teal-200">
                          {job.kind === "rebuild"
                            ? `${numberFormat.format(Number((job.result as Record<string, number>).entities ?? 0))} entidades · ${numberFormat.format(
                                Number((job.result as Record<string, number>).events ?? 0),
                              )} eventos · ${numberFormat.format(Number((job.result as Record<string, number>).relations ?? 0))} relações`
                            : `v${String((job.result as Record<string, unknown>).version ?? "—")}`}
                        </div>
                      )}
                    </div>
                  ))}
                  {jobs.length === 0 && <p className="text-xs text-muted-foreground">Sem execuções nesta sessão.</p>}
                </div>
                {Boolean(status?.last_rebuild) && (
                  <div className="mt-3 rounded-xl border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
                    <div className="mb-1 flex items-center gap-1 font-medium text-foreground">
                      <CalendarClock size={13} /> Última reconstrução
                    </div>
                    {(() => {
                      const last = status?.last_rebuild as Record<string, unknown>;
                      return (
                        <div className="space-y-0.5">
                          <div>versão {String(last.version)} · {String(last.duration_s)}s</div>
                          <div>
                            {numberFormat.format(Number(last.entities))} entidades · {numberFormat.format(Number(last.events))} eventos ·{" "}
                            {numberFormat.format(Number(last.relations))} relações
                          </div>
                          <div className="text-muted-foreground/80">amostra: {JSON.stringify(last.sources)}</div>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </Section>
            </div>

            {meta && (
              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Modelação e limitações</h2>
                </div>
                <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                  <li>O risco é um índice heurístico (insolvência, concentração, dimensão, inatividade) — não é um modelo de crédito validado.</li>
                  <li>As contagens por entidade vêm de agregações; os eventos e as relações vêm de uma amostra de contratos.</li>
                  <li>A causalidade é influência temporal candidata, nunca causalidade provada.</li>
                  <li>A rede dinâmica prevê com um readout linear (in-sample) e a simulação usa cenários com pesos subjetivos.</li>
                </ul>
              </Section>
            )}
          </div>
        )}

        {/* ---------------------------------------------------------- MUNDO */}
        {section === "mundo" && (
          <div className="space-y-4">
            <Section>
              <div className="flex flex-wrap items-end gap-2">
                <label className="flex-1 min-w-[220px]">
                  <span className="mb-1 block text-xs text-muted-foreground">Designação ou NIF/NIPC</span>
                  <div className="flex items-center gap-2 rounded-xl border border-border bg-muted px-3 py-2">
                    <Search size={14} className="text-muted-foreground" />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => event.key === "Enter" && void loadEntities()}
                      placeholder="Ex.: EDP, 501234567"
                      className="w-full bg-transparent text-sm text-foreground outline-none"
                    />
                  </div>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Tipo</span>
                  <select
                    value={typeFilter}
                    onChange={(event) => setTypeFilter(event.target.value)}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    <option value="">Todos</option>
                    <option value="empresa">Empresas</option>
                    <option value="entidade_publica">Entidades públicas</option>
                    <option value="pessoa">Pessoas</option>
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Risco</span>
                  <select
                    value={riskFilter}
                    onChange={(event) => setRiskFilter(event.target.value)}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    <option value="">Todos</option>
                    <option value="elevado">Elevado</option>
                    <option value="médio">Médio</option>
                    <option value="baixo">Baixo</option>
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Ordenar por</span>
                  <select
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    <option value="risk">Risco</option>
                    <option value="value">Valor contratado</option>
                    <option value="contracts">Contratos</option>
                    <option value="activity">Atividade</option>
                    <option value="relations">Relações</option>
                    <option value="recent">Mais recente</option>
                    <option value="name">Designação</option>
                    <option value="relevance">Relevância</option>
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void loadEntities()}
                  className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90"
                >
                  <Search size={14} /> Pesquisar
                </button>
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
              <Section>
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-foreground">
                    Entidades <span className="text-muted-foreground">({numberFormat.format(entitiesTotal)})</span>
                  </h2>
                  <Pill className="border-white/15 bg-white/5 text-muted-foreground">risco por heurística</Pill>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-1 pr-2">Entidade</th>
                        <th className="py-1 pr-2">Tipo</th>
                        <th className="py-1 pr-2 text-right">Contratos</th>
                        <th className="py-1 pr-2 text-right">Valor</th>
                        <th className="py-1 pr-2">Risco</th>
                        <th className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {entities.map((entity) => (
                        <tr key={entity.entity_ref} className="border-t border-border/60 hover:bg-muted/40">
                          <td className="py-1.5 pr-2">
                            <div className="max-w-[280px] truncate font-medium text-foreground">{entity.name}</div>
                            <div className="text-[11px] text-muted-foreground">{entity.entity_id}</div>
                          </td>
                          <td className="py-1.5 pr-2 text-muted-foreground">{entity.entity_type}</td>
                          <td className="py-1.5 pr-2 text-right text-foreground">{numberFormat.format(entity.contracts_count ?? 0)}</td>
                          <td className="py-1.5 pr-2 text-right text-foreground">{compactCurrency.format(entity.contracts_value ?? 0)} €</td>
                          <td className="py-1.5 pr-2">
                            <Pill className={RISK_STYLES[entity.risk_label ?? "baixo"] ?? RISK_STYLES.baixo}>
                              {entity.risk_label ?? "—"} {entity.risk != null ? `· ${entity.risk}` : ""}
                            </Pill>
                          </td>
                          <td className="py-1.5 text-right">
                            <button
                              type="button"
                              onClick={() => void openEntity(entity.entity_ref)}
                              className="rounded-lg border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                            >
                              abrir
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {entities.length === 0 && (
                    <p className="py-3 text-xs text-muted-foreground">
                      Sem resultados. Se o mundo ainda não foi construído, use «Reconstruir mundo».
                    </p>
                  )}
                </div>
              </Section>

              <Section>
                {!detail && !selected && <p className="text-xs text-muted-foreground">Escolha uma entidade para ver a ficha.</p>}
                {detail && (
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h2 className="text-sm font-semibold text-foreground">{detail.entity.name}</h2>
                        <p className="text-xs text-muted-foreground">
                          {detail.entity.entity_ref} · {detail.entity.entity_type} · {(detail.entity.state?.status ?? "—")}
                        </p>
                      </div>
                      <button type="button" onClick={() => { setDetail(null); setSelected(null); setRecall([]); }} className="text-muted-foreground hover:text-foreground">
                        <X size={14} />
                      </button>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="text-muted-foreground">Contratos</div>
                        <div className="text-base font-semibold text-foreground">{numberFormat.format(detail.entity.contracts_count ?? 0)}</div>
                      </div>
                      <div className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="text-muted-foreground">Valor</div>
                        <div className="text-base font-semibold text-foreground">{currencyFormat.format(detail.entity.contracts_value ?? 0)}</div>
                      </div>
                      <div className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="text-muted-foreground">Relações / contrapartes</div>
                        <div className="text-base font-semibold text-foreground">
                          {detail.entity.relations_count ?? 0} / {detail.entity.counterparties_count ?? 0}
                        </div>
                      </div>
                      <div className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="text-muted-foreground">Risco</div>
                        <div className="text-base font-semibold text-foreground">
                          {detail.entity.risk} · {detail.entity.risk_label}
                        </div>
                      </div>
                    </div>

                    {detail.prediction && (
                      <div className="rounded-xl border border-border bg-muted/20 p-3 text-xs">
                        <div className="mb-1 flex items-center gap-1 font-medium text-foreground">
                          <Brain size={13} /> Rede dinâmica
                        </div>
                        <div className="text-muted-foreground">
                          score {(detail.prediction as { prediction?: { score?: number } }).prediction?.score ?? "—"} · contratos esperados{" "}
                          {(detail.prediction as { prediction?: { expected_contracts?: number } }).prediction?.expected_contracts ?? "—"} · risco projetado{" "}
                          {(detail.prediction as { prediction?: { risk_after?: number } }).prediction?.risk_after ?? "—"}
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleRecall(detail.entity.entity_ref)}
                          className="mt-2 rounded-lg border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                        >
                          ver padrões de memória próximos
                        </button>
                        {recall.length > 0 && (
                          <ul className="mt-1 space-y-0.5">
                            {recall.map((pattern) => (
                              <li key={pattern.pattern_id} className="text-muted-foreground">
                                • {pattern.label} — semelhança {pattern.similarity}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    <div>
                      <div className="mb-1 text-xs font-medium text-foreground">Relações</div>
                      <ul className="max-h-40 space-y-1 overflow-y-auto text-[11px] text-muted-foreground">
                        {detail.relations.map((relation) => (
                          <li key={relation.relation_id} className="flex items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                            <span className="truncate">
                              {relation.source_name ?? relation.source_ref} <ArrowRight size={10} className="inline" />{" "}
                              {relation.target_name ?? relation.target_ref}
                            </span>
                            <span className="shrink-0">{compactCurrency.format(relation.value_sum ?? 0)} €</span>
                          </li>
                        ))}
                        {detail.relations.length === 0 && <li>Sem relações na amostra atual.</li>}
                      </ul>
                    </div>

                    <div>
                      <div className="mb-1 text-xs font-medium text-foreground">Linha temporal</div>
                      <ul className="max-h-40 space-y-1 overflow-y-auto text-[11px] text-muted-foreground">
                        {detail.timeline.map((event, index) => (
                          <li key={`${event.event_id}-${index}`} className="flex items-center justify-between gap-2">
                            <span className="truncate">
                              {event.ts?.slice(0, 10)} · {event.kind_label ?? event.kind}
                            </span>
                            <span className="shrink-0">{event.value ? compactCurrency.format(event.value) + " €" : "—"}</span>
                          </li>
                        ))}
                        {detail.timeline.length === 0 && <li>Sem eventos registados.</li>}
                      </ul>
                    </div>

                    {entityHistory.length > 0 && (
                      <div>
                        <div className="mb-1 text-xs font-medium text-foreground">Estado por período (histórico)</div>
                        <div className="max-h-40 overflow-y-auto">
                          <table className="w-full text-left text-[11px]">
                            <thead className="text-muted-foreground">
                              <tr>
                                <th className="py-0.5 pr-2">Período</th>
                                <th className="py-0.5 pr-2 text-right">Ctr.</th>
                                <th className="py-0.5 pr-2 text-right">Valor</th>
                                <th className="py-0.5 pr-2 text-right">Novas cpt.</th>
                                <th className="py-0.5 text-right">Risco</th>
                              </tr>
                            </thead>
                            <tbody>
                              {entityHistory.map((row) => (
                                <tr key={row.period} className="border-t border-border/50">
                                  <td className="py-0.5 pr-2 text-muted-foreground">{row.period}</td>
                                  <td className="py-0.5 pr-2 text-right text-foreground">{row.contracts ?? 0}</td>
                                  <td className="py-0.5 pr-2 text-right text-foreground">{compactCurrency.format(row.value ?? 0)} €</td>
                                  <td className="py-0.5 pr-2 text-right text-muted-foreground">{row.new_counterparties ?? 0}</td>
                                  <td className="py-0.5 text-right text-foreground">{row.risk}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {entityTransition.length > 0 && (
                      <div className="rounded-xl border border-border bg-muted/20 p-2 text-[11px]">
                        <div className="mb-1 flex items-center gap-1 font-medium text-foreground">
                          <Zap size={12} /> Trajetória pela transição latente
                        </div>
                        <div className="flex flex-wrap gap-2 text-muted-foreground">
                          {entityTransition.map((step) => (
                            <span key={step.step} className="rounded-lg border border-border/60 px-2 py-0.5">
                              t{step.step}: {step.cum_contracts} ctr · risco {step.risk}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <button
                      type="button"
                      onClick={() => {
                        setSection("agente");
                        setAgentQuestion(`O que se passa com ${detail.entity.name} e o que pode acontecer nos próximos 12 meses?`);
                        void handleAgentRun(detail.entity.entity_ref);
                      }}
                      className="w-full rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90"
                    >
                      Investigar com o agente
                    </button>
                  </div>
                )}
              </Section>
            </div>
          </div>
        )}

        {/* --------------------------------------------------------- EVENTOS */}
        {section === "eventos" && (
          <div className="space-y-4">
            <Section>
              <div className="mb-3 flex items-center gap-2">
                <TrendingUp size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Evolução por período (estado temporal)</h2>
                <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">amostra estratificada por ano</Pill>
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={worldHistory}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="period" tick={{ fontSize: 10 }} stroke="rgba(255,255,255,0.4)" />
                    <YAxis tick={{ fontSize: 10 }} stroke="rgba(255,255,255,0.4)" />
                    <Tooltip contentStyle={{ background: "#0b1a21", border: "1px solid rgba(255,255,255,0.1)", fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="contracts" name="contratos" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="new_counterparties" name="contrapartes novas" fill="#fbbf24" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                É este histórico que permite responder «como chegou a este estado?» e alimenta a transição latente e a
                deteção de anomalias.
              </p>
            </Section>

            <Section>
              <div className="mb-3 flex items-center gap-2">
                <TrendingUp size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Série mensal de eventos e valor</h2>
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={temporalChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="period" tick={{ fontSize: 10 }} stroke="rgba(255,255,255,0.4)" />
                    <YAxis tick={{ fontSize: 10 }} stroke="rgba(255,255,255,0.4)" />
                    <Tooltip
                      contentStyle={{ background: "#0b1a21", border: "1px solid rgba(255,255,255,0.1)", fontSize: 12 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="eventos" fill="#22d3ee" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="valor" fill="#818cf8" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2">
              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Clock size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Eventos recentes</h2>
                </div>
                <div className="max-h-[420px] overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-1 pr-2">Data</th>
                        <th className="py-1 pr-2">Tipo</th>
                        <th className="py-1 pr-2">Entidade</th>
                        <th className="py-1 pr-2 text-right">Valor</th>
                        <th className="py-1">Sev.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((event, index) => (
                        <tr key={event.event_id ?? index} className="border-t border-border/60">
                          <td className="py-1 pr-2 text-muted-foreground">{event.ts?.slice(0, 10) ?? "—"}</td>
                          <td className="py-1 pr-2 text-foreground">{event.kind_label ?? event.kind}</td>
                          <td className="py-1 pr-2 text-muted-foreground">
                            <span className="block max-w-[200px] truncate">{event.entity_name ?? event.entity_ref}</span>
                          </td>
                          <td className="py-1 pr-2 text-right text-foreground">
                            {event.value ? compactCurrency.format(event.value) + " €" : "—"}
                          </td>
                          <td className="py-1 text-muted-foreground">{event.severity_label ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {events.length === 0 && <p className="py-3 text-xs text-muted-foreground">Sem eventos — reconstrua o mundo.</p>}
                </div>
              </Section>

              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <GitBranch size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Causalidade candidata</h2>
                  <Pill className="ml-auto border-amber-400/30 bg-amber-400/10 text-amber-200">hipótese</Pill>
                </div>
                <p className="mb-2 text-[11px] text-muted-foreground">
                  Eventos de entidades ligadas, próximos no tempo. Pontuação = peso da relação × proximidade × severidade — não é prova de causa.
                </p>
                <ul className="max-h-[400px] space-y-2 overflow-y-auto text-xs">
                  {causality.map((link, index) => (
                    <li key={index} className="rounded-xl border border-border bg-muted/30 p-2">
                      <div className="flex items-center gap-2 text-foreground">
                        <span className="truncate">{link.cause?.entity_name ?? "—"}</span>
                        <ArrowRight size={12} className="shrink-0 text-muted-foreground" />
                        <span className="truncate">{link.effect?.entity_name ?? "—"}</span>
                        <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">{link.days}d</Pill>
                      </div>
                      <div className="mt-1 text-[11px] text-muted-foreground">{link.interpretation}</div>
                      <div className="text-[11px] text-muted-foreground/80">
                        {link.cause?.event} → {link.effect?.event} · score {link.score}
                      </div>
                    </li>
                  ))}
                  {causality.length === 0 && <li className="text-muted-foreground">Sem ligações candidatas na janela analisada.</li>}
                </ul>
              </Section>
            </div>
          </div>
        )}

        {/* ----------------------------------------------------------- GRAFO */}
        {section === "grafo" && (
          <div className="space-y-4">
            <Section>
              <div className="flex flex-wrap items-end gap-2">
                <label className="min-w-[240px] flex-1">
                  <span className="mb-1 block text-xs text-muted-foreground">Centro do grafo (ego-rede) — vazio = grafo global</span>
                  <input
                    value={graphOrigin}
                    onChange={(event) => setGraphOrigin(event.target.value)}
                    placeholder="Ex.: entidade:501234567 ou 501234567"
                    className="w-full rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground outline-none"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Profundidade</span>
                  <select
                    value={graphDepth}
                    onChange={(event) => setGraphDepth(Number(event.target.value))}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    {[1, 2, 3].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Relação</span>
                  <select
                    value={graphKind}
                    onChange={(event) => setGraphKind(event.target.value)}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    <option value="">Todas</option>
                    <option value="adjudicou">Adjudicações</option>
                    <option value="cargo_em">Cargos</option>
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Vista</span>
                  <select
                    value={graphView}
                    onChange={(event) => setGraphView(event.target.value as StudioView)}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    <option value="network">Rede</option>
                    <option value="hierarchical">Hierárquica</option>
                    <option value="circular">Circular</option>
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void loadGraph()}
                  className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90"
                >
                  <Network size={14} /> Construir
                </button>
              </div>
            </Section>

            <Section>
              <GraphCanvas
                graph={studioGraph}
                layout={graphView as "network" | "hierarchical" | "circular"}
                metric={metric}
                heightClass="h-[520px]"
                unitLabel="contratos"
                nodeSummary={worldNodeSummary}
                edgeSummary={worldEdgeSummary}
                loading={!graph}
                onNodeClick={(node) => {
                  setGraphOrigin(node.id);
                  setSection("mundo");
                  void openEntity(node.id);
                }}
              />
              {graph?.metrics && (
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  <span>{numberFormat.format(graph.metrics.nodes)} nós</span>
                  <span>{numberFormat.format(graph.metrics.edges)} arestas</span>
                  <span>grau médio {graph.metrics.avg_degree}</span>
                  {graph.truncated && <span className="text-amber-300">grafo truncado pelos limites</span>}
                </div>
              )}
            </Section>

            <div className="grid gap-4 lg:grid-cols-2">
              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Entidades mais centrais</h2>
                </div>
                <ul className="space-y-1 text-xs">
                  {centrality.map((item) => (
                    <li key={item.entity_ref} className="flex items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                      <button type="button" className="truncate text-left text-foreground hover:text-primary" onClick={() => void openEntity(item.entity_ref)}>
                        {item.name}
                      </button>
                      <span className="shrink-0 text-muted-foreground">grau {item.degree}</span>
                    </li>
                  ))}
                  {centrality.length === 0 && <li className="text-muted-foreground">Sem relações — reconstrua o mundo com mais contratos.</li>}
                </ul>
              </Section>

              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Share2 size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Caminhos entre entidades</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  <input
                    value={pathFrom}
                    onChange={(event) => setPathFrom(event.target.value)}
                    placeholder="origem (ref ou NIF)"
                    className="flex-1 rounded-xl border border-border bg-muted px-3 py-2 text-xs text-foreground outline-none"
                  />
                  <input
                    value={pathTo}
                    onChange={(event) => setPathTo(event.target.value)}
                    placeholder="destino (ref ou NIF)"
                    className="flex-1 rounded-xl border border-border bg-muted px-3 py-2 text-xs text-foreground outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => void handlePaths()}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-xs font-semibold text-foreground hover:bg-muted/70"
                  >
                    procurar
                  </button>
                </div>
                {paths && (
                  <ul className="mt-2 space-y-1 text-xs">
                    {paths.map((path, index) => (
                      <li key={index} className="rounded-lg border border-border/60 px-2 py-1 text-muted-foreground">
                        {path.map((step) => step.name).join(" → ")}
                      </li>
                    ))}
                    {paths.length === 0 && <li className="text-muted-foreground">Sem caminho no grafo atual.</li>}
                  </ul>
                )}
              </Section>
            </div>
          </div>
        )}

        {/* ------------------------------------------------------------ REDE */}
        {section === "rede" && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Stat label="Neurónios (nós)" value={numberFormat.format(networkMetrics.nodes)} hint="entidades ativas" icon={<Brain size={13} />} />
              <Stat label="Sinapses (arestas)" value={numberFormat.format(networkMetrics.edges)} hint={`+${networkMetrics.growth} / −${networkMetrics.pruned}`} icon={<Share2 size={13} />} />
              <Stat label="Padrões de memória" value={numberFormat.format(networkMetrics.memory)} hint="reutilizados na previsão" icon={<Sparkles size={13} />} />
              <Stat
                label="Readout (R²)"
                value={networkMetrics.r2 != null ? networkMetrics.r2.toFixed(3) : "—"}
                hint={networkMetrics.rmse != null ? `RMSE ${networkMetrics.rmse}` : "sem ciclo"}
                icon={<TrendingUp size={13} />}
              />
              <Stat
                label="Crescimento"
                value={networkMetrics.growthFactor != null ? `${networkMetrics.growthFactor}×` : "—"}
                hint="atividade recente vs. anterior"
                icon={<Activity size={13} />}
              />
            </div>

            <Section>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Brain size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Rede dinâmica como grafo</h2>
                <Pill className="border-white/15 bg-white/5 text-muted-foreground">
                  versão {String(network?.version ?? "—")}
                </Pill>
                <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                  <input type="checkbox" checked={memoryOnly} onChange={(event) => setMemoryOnly(event.target.checked)} />
                  incluir padrões de memória
                </label>
                <button
                  type="button"
                  onClick={() => void loadNetwork()}
                  className="rounded-xl border border-border bg-muted px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted/70"
                >
                  atualizar
                </button>
                <button
                  type="button"
                  onClick={handleTrain}
                  disabled={busy === "train"}
                  className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
                >
                  {busy === "train" ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
                  novo ciclo
                </button>
              </div>

              {!network?.trained && !network?.nodes?.length ? (
                <p className="text-xs text-muted-foreground">
                  A rede ainda não tem ciclos. Use «novo ciclo» (crescimento → poda → memória → previsão) para a construir.
                </p>
              ) : (
                <GraphCanvas
                  graph={networkGraph}
                  layout="network"
                  metric="contratos"
                  heightClass="h-[560px]"
                  unitLabel="ativações"
                  nodeSummary={networkNodeSummary}
                  edgeSummary={networkEdgeSummary}
                  onNodeClick={(node) => {
                    if (String(node.id).startsWith("memoria:")) return;
                    setSection("mundo");
                    void openEntity(node.id);
                  }}
                />
              )}

              <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                <span>■ empresa ◆ entidade pública ● pessoa ⬢ padrão de memória</span>
                <span>raio = ativação · espessura = peso da sinapse</span>
                {network?.pruned && (
                  <span>
                    poda neste ciclo: {network.pruned.edges ?? 0} aresta(s), {network.pruned.patterns ?? 0} padrão(ões)
                  </span>
                )}
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2">
              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <RefreshCw size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Histórico de ciclos</h2>
                </div>
                <div className="max-h-64 overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-1 pr-2">Versão</th>
                        <th className="py-1 pr-2 text-right">Nós</th>
                        <th className="py-1 pr-2 text-right">Arestas</th>
                        <th className="py-1 pr-2 text-right">+ / −</th>
                        <th className="py-1 pr-2 text-right">Memória</th>
                        <th className="py-1 text-right">R²</th>
                      </tr>
                    </thead>
                    <tbody>
                      {networkHistory.map((entry) => {
                        const metrics = (entry.metrics ?? {}) as Record<string, number>;
                        const pruned = (entry.pruned ?? {}) as Record<string, number>;
                        return (
                          <tr key={String(entry.version)} className="border-t border-border/60">
                            <td className="py-1 pr-2 text-muted-foreground">{String(entry.version)}</td>
                            <td className="py-1 pr-2 text-right text-foreground">{metrics.nodes ?? 0}</td>
                            <td className="py-1 pr-2 text-right text-foreground">{metrics.edges ?? 0}</td>
                            <td className="py-1 pr-2 text-right text-muted-foreground">
                              +{metrics.edges_added ?? 0} / −{pruned.edges ?? metrics.edges_pruned ?? 0}
                            </td>
                            <td className="py-1 pr-2 text-right text-muted-foreground">{metrics.memory_patterns ?? 0}</td>
                            <td className="py-1 text-right text-muted-foreground">
                              {typeof metrics.r2 === "number" ? metrics.r2.toFixed(3) : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {networkHistory.length === 0 && <p className="py-2 text-xs text-muted-foreground">Sem ciclos registados.</p>}
                </div>
              </Section>

              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Memória (padrões reutilizados)</h2>
                </div>
                <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
                  {(network?.memory ?? []).map((pattern) => (
                    <li key={pattern.id} className="flex items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                      <span className="truncate text-foreground">{pattern.label}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {pattern.hits}× · idade {pattern.age ?? 0}
                      </span>
                    </li>
                  ))}
                  {(network?.memory ?? []).length === 0 && <li className="text-muted-foreground">Sem padrões na memória.</li>}
                </ul>
                <div className="mt-3 rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
                  <div className="mb-1 font-medium text-foreground">Como ler a rede</div>
                  Crescimento: entidades e relações entram a cada ciclo. Poda: arestas com peso abaixo do limiar e padrões antigos saem.
                  Memória: padrões de atividade que se repetem são consolidados e reutilizados. Previsão: readout linear (ridge) sobre as features
                  de cada entidade — estimativa transversal, com erro in-sample.
                </div>
              </Section>
            </div>

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <AlertTriangle size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Anomalias detetadas pela rede</h2>
                <Pill className="ml-auto border-amber-400/30 bg-amber-400/10 text-amber-200">
                  padrões a investigar, não acusações
                </Pill>
              </div>
              <p className="mb-2 text-[11px] text-muted-foreground">
                Cada entidade é comparada **consigo própria**: desvios da sua média de valor/contratos, picos, paragens,
                contrapartes novas, alteração de administradores e erro da previsão. É a rede que aponta os alvos ao agente.
              </p>
              <div className="max-h-[420px] overflow-y-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="py-1 pr-2">Entidade</th>
                      <th className="py-1 pr-2">Período</th>
                      <th className="py-1 pr-2">Sinais</th>
                      <th className="py-1 pr-2 text-right">Score</th>
                      <th className="py-1" />
                    </tr>
                  </thead>
                  <tbody>
                    {anomalies.map((item) => (
                      <tr key={`${item.entity_ref}-${item.period}`} className="border-t border-border/60">
                        <td className="py-1.5 pr-2">
                          <div className="max-w-[260px] truncate font-medium text-foreground">{item.entity_name}</div>
                          <div className="text-[11px] text-muted-foreground">{item.interpretation}</div>
                        </td>
                        <td className="py-1.5 pr-2 text-muted-foreground">{item.period ?? "—"}</td>
                        <td className="py-1.5 pr-2">
                          <div className="flex flex-wrap gap-1">
                            {item.signal_ids.map((signal) => (
                              <Pill key={signal} className="border-white/15 bg-white/5 text-muted-foreground">
                                {signal}
                              </Pill>
                            ))}
                          </div>
                        </td>
                        <td className="py-1.5 pr-2 text-right">
                          <Pill className={ANOMALY_STYLES[item.label] ?? RISK_STYLES.baixo}>{item.label} · {item.score}</Pill>
                        </td>
                        <td className="py-1.5 text-right">
                          <button
                            type="button"
                            onClick={() => void openEntity(item.entity_ref)}
                            className="rounded-lg border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                          >
                            abrir
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {anomalies.length === 0 && (
                  <p className="py-3 text-xs text-muted-foreground">
                    Sem anomalias acima do limiar — treine um ciclo da rede com histórico reconstruído.
                  </p>
                )}
              </div>
            </Section>

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Zap size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Transição latente z_t → z_t+1</h2>
              </div>
              {transitionModel?.available ? (
                <div className="space-y-2 text-xs text-muted-foreground">
                  <div className="grid gap-2 sm:grid-cols-4">
                    <div className="rounded-xl border border-border bg-muted/30 p-2">
                      <div className="text-muted-foreground">Pares usados</div>
                      <div className="text-base font-semibold text-foreground">{transitionModel.pairs}</div>
                    </div>
                    <div className="rounded-xl border border-border bg-muted/30 p-2">
                      <div className="text-muted-foreground">Entidades com série</div>
                      <div className="text-base font-semibold text-foreground">{transitionModel.entities}</div>
                    </div>
                    <div className="rounded-xl border border-border bg-muted/30 p-2">
                      <div className="text-muted-foreground">R² (validação 30 %)</div>
                      <div className="text-base font-semibold text-foreground">{transitionModel.r2}</div>
                    </div>
                    <div className="rounded-xl border border-border bg-muted/30 p-2">
                      <div className="text-muted-foreground">RMSE</div>
                      <div className="text-base font-semibold text-foreground">{transitionModel.rmse}</div>
                    </div>
                  </div>
                  <div>
                    RMSE por feature:{" "}
                    {Object.entries(transitionModel.rmse_by_feature ?? {})
                      .map(([key, value]) => `${key} ${value}`)
                      .join(" · ")}
                  </div>
                  <div>{transitionModel.note}</div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {transitionModel?.reason ?? "Sem transição ajustada — é preciso histórico de pelo menos dois períodos por entidade."}
                </p>
              )}
            </Section>
          </div>
        )}
        {section === "simulador" && (
          <div className="space-y-4">
            <Section>
              <div className="flex flex-wrap items-end gap-2">
                <label className="min-w-[240px] flex-1">
                  <span className="mb-1 block text-xs text-muted-foreground">Sujeito (vazio = mundo inteiro)</span>
                  <input
                    value={simSubject}
                    onChange={(event) => setSimSubject(event.target.value)}
                    placeholder="entidade:501234567"
                    className="w-full rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground outline-none"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Passos</span>
                  <select
                    value={simHorizon}
                    onChange={(event) => setSimHorizon(Number(event.target.value))}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    {[2, 3, 4, 6, 8].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs text-muted-foreground">Amostras</span>
                  <select
                    value={simSamples}
                    onChange={(event) => setSimSamples(Number(event.target.value))}
                    className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground"
                  >
                    {[100, 300, 600, 1200].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void handleSimulate()}
                  disabled={busy === "simulate"}
                  className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
                >
                  {busy === "simulate" ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                  Simular
                </button>
              </div>
            </Section>

            {simulation && (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat label="Novos contratos" value={numberFormat.format(simulation.summary.totals.new_contracts)} hint={`${simulation.horizon} passos · ${simulation.samples} amostras`} />
                  <Stat label="Atrasos" value={numberFormat.format(simulation.summary.totals.delays)} hint="proxy por eventos de cessação" />
                  <Stat label="Cancelamentos" value={numberFormat.format(simulation.summary.totals.cancellations)} />
                  <Stat
                    label="Δ financeiro"
                    value={currencyFormat.format(simulation.summary.totals.financial_change)}
                    hint={`risco final ${simulation.summary.totals.risk_final}`}
                  />
                </div>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <FlaskConical size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Cenários — novos contratos por passo</h2>
                  </div>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={scenarioChart}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                        <XAxis dataKey="step" tick={{ fontSize: 11 }} stroke="rgba(255,255,255,0.4)" />
                        <YAxis tick={{ fontSize: 11 }} stroke="rgba(255,255,255,0.4)" />
                        <Tooltip contentStyle={{ background: "#0b1a21", border: "1px solid rgba(255,255,255,0.1)", fontSize: 12 }} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        {(simulation.summary.scenario_labels ?? []).map((label, index) => (
                          <Line
                            key={label}
                            type="monotone"
                            dataKey={label}
                            stroke={["#2dd4bf", "#60a5fa", "#fb7185"][index % 3]}
                            strokeWidth={2}
                            dot={false}
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="mt-2 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-3">
                    {simulation.scenarios.map((scenario) => (
                      <div key={scenario.id} className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="font-medium text-foreground">{scenario.label} · peso {scenario.weight}</div>
                        <div>{scenario.note}</div>
                        <div>contratos/passo {scenario.rates.contracts_per_step} · atrasos {scenario.rates.delay_probability} · cancelamentos {scenario.rates.cancel_probability}</div>
                      </div>
                    ))}
                  </div>
                </Section>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <TrendingUp size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Passos (média e intervalo p10–p90)</h2>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-muted-foreground">
                        <tr>
                          <th className="py-1 pr-2">Passo</th>
                          <th className="py-1 pr-2 text-right">Contratos</th>
                          <th className="py-1 pr-2 text-right">Atrasos</th>
                          <th className="py-1 pr-2 text-right">Cancel.</th>
                          <th className="py-1 pr-2 text-right">Relações</th>
                          <th className="py-1 pr-2 text-right">Δ Financeiro</th>
                          <th className="py-1 text-right">Risco</th>
                        </tr>
                      </thead>
                      <tbody>
                        {simulation.steps.map((step) => (
                          <tr key={step.step} className="border-t border-border/60">
                            <td className="py-1 pr-2 text-muted-foreground">{step.label}</td>
                            <td className="py-1 pr-2 text-right text-foreground">
                              {step.new_contracts.mean}{" "}
                              <span className="text-muted-foreground">
                                ({step.new_contracts.p10}–{step.new_contracts.p90})
                              </span>
                            </td>
                            <td className="py-1 pr-2 text-right text-foreground">{step.delays.mean}</td>
                            <td className="py-1 pr-2 text-right text-foreground">{step.cancellations.mean}</td>
                            <td className="py-1 pr-2 text-right text-foreground">{step.new_relations.mean}</td>
                            <td className="py-1 pr-2 text-right text-foreground">{currencyFormat.format(step.financial_change.mean)}</td>
                            <td className="py-1 text-right text-foreground">{step.risk.mean}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <ul className="mt-3 list-disc space-y-0.5 pl-5 text-[11px] text-muted-foreground">
                    {simulation.summary.assumptions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </Section>
              </>
            )}

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Clock size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Simulações recentes</h2>
              </div>
              <ul className="space-y-1 text-xs">
                {history.map((run) => (
                  <li key={run.run_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                    <button type="button" className="text-left text-foreground hover:text-primary" onClick={() => setSimulation(run)}>
                      {run.subject_name ?? run.summary?.subject ?? "mundo"} · {run.horizon} passos
                    </button>
                    <span className="text-muted-foreground">
                      {run.summary?.totals?.new_contracts} contratos · {run.created_at?.slice(0, 16).replace("T", " ")}
                    </span>
                  </li>
                ))}
                {history.length === 0 && <li className="text-muted-foreground">Sem simulações gravadas.</li>}
              </ul>
            </Section>
          </div>
        )}

        {/* ---------------------------------------------------------- AGENTE */}
        {section === "agente" && (
          <div className="space-y-4">
            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Brain size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Agente sobre a rede neuronal</h2>
                <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">
                  o LLM escreve; os números e as decisões vêm do código
                </Pill>
              </div>
              <p className="mb-2 text-[11px] text-muted-foreground">
                O planeador escolhe o alvo a partir das <strong>anomalias da rede</strong> (não de uma lista fixa) e decide
                os passos: observação → história → rede → recolha de evidência → simulação → verificação → narrativa. Cada
                execução produz o grafo de execução, o grafo de evidências e o grafo de relações, todos em Mermaid.
              </p>
              <div className="flex flex-wrap gap-1">
                {(agentCatalog?.agents ?? []).map((item) => (
                  <Pill key={item.id} className="border-white/10 bg-white/5 text-muted-foreground" >
                    {item.label}
                  </Pill>
                ))}
              </div>
              {agentCatalog?.mermaid && (
                <div className="mt-3">
                  <MermaidDiagram code={agentCatalog.mermaid} title="Roster de agentes e fluxo de dados" height={280} />
                </div>
              )}
            </Section>

            <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Sparkles size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Alvos sugeridos pela rede</h2>
                  <button
                    type="button"
                    onClick={() => void loadAgent()}
                    className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                  >
                    atualizar
                  </button>
                </div>
                <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
                  {agentTargets.map((target) => (
                    <li key={target.entity_ref} className="flex items-start justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-foreground">{target.entity_name}</div>
                        <div className="truncate text-[11px] text-muted-foreground">
                          {target.signals.join(", ")} — {target.interpretation}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <Pill className={ANOMALY_STYLES[target.label] ?? RISK_STYLES.baixo}>{target.score}</Pill>
                        <button
                          type="button"
                          onClick={() => void handleAgentRun(target.entity_ref)}
                          className="rounded-lg border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                        >
                          investigar
                        </button>
                      </div>
                    </li>
                  ))}
                  {agentTargets.length === 0 && (
                    <li className="text-muted-foreground">Sem alvos — treine um ciclo da rede com histórico reconstruído.</li>
                  )}
                </ul>
              </Section>

              <Section>
                <div className="mb-2 flex items-center gap-2">
                  <Play size={16} className="text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Executar</h2>
                </div>
                <textarea
                  value={agentQuestion}
                  onChange={(event) => setAgentQuestion(event.target.value)}
                  rows={3}
                  className="w-full rounded-xl border border-border bg-muted p-3 text-sm text-foreground outline-none"
                  placeholder="Ex.: O que se passa com esta entidade e o que pode acontecer nos próximos 12 meses?"
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleAgentRun()}
                    disabled={busy === "agente"}
                    className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
                  >
                    {busy === "agente" ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                    Correr agente (alvo = rede)
                  </button>
                  {investigationSubject && (
                    <button
                      type="button"
                      onClick={() => void handleAgentRun(investigationSubject)}
                      className="rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground hover:bg-muted/70"
                    >
                      Sujeito indicado
                    </button>
                  )}
                </div>
                <ul className="mt-3 space-y-1 text-[11px] text-muted-foreground">
                  {(agentRun?.plan ?? []).map((step, index) => (
                    <li key={`${step.agent}-${index}`}>
                      <span className="font-medium text-foreground">{step.agent}</span> — {step.action}{" "}
                      <span className="text-muted-foreground/80">({step.why})</span>
                    </li>
                  ))}
                </ul>
              </Section>
            </div>

            {agentRun && (
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat
                    label="Passos do agente"
                    value={agentRun.execution_graph?.metrics?.steps ?? 0}
                    hint={`${agentRun.elapsed_s ?? "—"}s`}
                    icon={<Layers size={13} />}
                  />
                  <Stat
                    label="Alvo"
                    value={<span className="text-sm">{agentRun.subject_name ?? "mundo"}</span>}
                    hint={agentRun.chosen_by_network ? "escolhido pela rede" : agentRun.subject_resolution}
                    icon={<Users size={13} />}
                  />
                  <Stat
                    label="Anomalia"
                    value={agentRun.anomaly ? `${agentRun.anomaly.label} · ${agentRun.anomaly.score}` : "—"}
                    hint={(agentRun.anomaly?.signal_ids ?? []).join(", ") || "sem sinais"}
                    icon={<AlertTriangle size={13} />}
                  />
                  <Stat
                    label="Verificações OK"
                    value={`${agentRun.counters?.checks_ok ?? 0}/${agentRun.counters?.checks_total ?? 0}`}
                    hint={`${agentRun.evidence.length} evidências · ${agentRun.counters?.periods ?? 0} períodos`}
                    icon={<ShieldCheck size={13} />}
                  />
                </div>

                {agentRun.anomaly && (
                  <Section>
                    <div className="mb-1 flex items-center gap-2">
                      <AlertTriangle size={15} className="text-amber-300" />
                      <h2 className="text-sm font-semibold text-foreground">
                        Porque foi escolhido: {agentRun.anomaly.label} (score {agentRun.anomaly.score}) em {agentRun.anomaly.period}
                      </h2>
                    </div>
                    <p className="text-xs text-muted-foreground">{agentRun.anomaly.interpretation}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {agentRun.anomaly.signals.map((signal) => (
                        <Pill key={signal.id} className="border-amber-400/25 bg-amber-400/10 text-amber-200">
                          {signal.id}: {signal.detail}
                        </Pill>
                      ))}
                    </div>
                  </Section>
                )}

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <GitBranch size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Grafo de execução</h2>
                    <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">
                      {agentRun.execution_graph?.metrics?.steps ?? 0} passos · {agentRun.execution_graph?.metrics?.flows ?? 0} fluxos
                    </Pill>
                  </div>
                  <GraphCanvas
                    graph={executionStudio}
                    layout="hierarchical"
                    metric="contratos"
                    heightClass="h-[420px]"
                    unitLabel="passos"
                    nodeSummary={executionNodeSummary}
                  />
                  <div className="mt-3">
                    <MermaidDiagram code={agentRun.execution_graph?.mermaid ?? ""} title="Grafo de execução (Mermaid)" height={420} />
                  </div>
                </Section>

                <div className="grid gap-4 lg:grid-cols-2">
                  <Section>
                    <div className="mb-2 flex items-center gap-2">
                      <Share2 size={16} className="text-primary" />
                      <h2 className="text-sm font-semibold text-foreground">Grafo de relações (ego-rede)</h2>
                      <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">
                        {agentRun.relations_graph?.metrics?.nodes ?? 0} nós
                      </Pill>
                    </div>
                    <GraphCanvas
                      graph={agentRelationsStudio}
                      layout="network"
                      metric="valor"
                      heightClass="h-[380px]"
                      unitLabel="contratos"
                      nodeSummary={worldNodeSummary}
                      edgeSummary={worldEdgeSummary}
                    />
                    <div className="mt-3">
                      <MermaidDiagram code={agentRun.relations_graph?.mermaid ?? ""} title="Grafo de relações (Mermaid)" height={340} />
                    </div>
                  </Section>

                  <Section>
                    <div className="mb-2 flex items-center gap-2">
                      <Gavel size={16} className="text-primary" />
                      <h2 className="text-sm font-semibold text-foreground">Grafo de evidências</h2>
                      <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">
                        {Object.entries(agentRun.evidence_graph?.counts ?? {})
                          .map(([key, value]) => `${value} ${key}`)
                          .join(" · ")}
                      </Pill>
                    </div>
                    <GraphCanvas
                      graph={evidenceStudio}
                      layout="network"
                      metric="contratos"
                      heightClass="h-[380px]"
                      unitLabel="ligações"
                      nodeSummary={evidenceNodeSummary}
                    />
                    <div className="mt-3">
                      <MermaidDiagram code={agentRun.evidence_graph?.mermaid ?? ""} title="Grafo de evidências (Mermaid)" height={340} />
                    </div>
                  </Section>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <Section>
                    <div className="mb-2 flex items-center gap-2">
                      <Microscope size={16} className="text-primary" />
                      <h2 className="text-sm font-semibold text-foreground">Hipóteses</h2>
                    </div>
                    <ul className="space-y-2 text-xs">
                      {agentRun.hypotheses.map((hypothesis) => (
                        <li key={hypothesis.id} className="rounded-xl border border-border bg-muted/30 p-2">
                          <div className="flex items-center gap-2">
                            <Pill className={CLAIM_STYLES[hypothesis.kind] ?? CLAIM_STYLES.HYPOTHESIS}>{hypothesis.kind}</Pill>
                            <span className="font-semibold text-foreground">{hypothesis.id}</span>
                            <span className="text-foreground">{hypothesis.statement}</span>
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">Como testar: {hypothesis.test}</div>
                        </li>
                      ))}
                    </ul>
                  </Section>

                  <Section>
                    <div className="mb-2 flex items-center gap-2">
                      <ShieldCheck size={16} className="text-primary" />
                      <h2 className="text-sm font-semibold text-foreground">Verificação e afirmações</h2>
                    </div>
                    <ul className="space-y-1 text-xs">
                      {(agentRun.validation?.checks ?? []).map((check, index) => (
                        <li key={index} className="flex items-start gap-2">
                          {check.ok ? (
                            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-teal-300" />
                          ) : (
                            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" />
                          )}
                          <span className="text-muted-foreground">
                            {check.check} — esperado {check.expected}, observado {check.observed}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {agentRun.claims.map((claim, index) => (
                        <Pill key={index} className={CLAIM_STYLES[claim.kind] ?? CLAIM_STYLES.HYPOTHESIS}>
                          {claim.kind}: {claim.claim.slice(0, 110)}
                          {claim.claim.length > 110 ? "…" : ""}
                        </Pill>
                      ))}
                    </div>
                  </Section>
                </div>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <FileText size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Relatório do agente</h2>
                    <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">{agentRun.run_id}</Pill>
                  </div>
                  <article className="prose prose-invert max-w-none text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{agentRun.report}</ReactMarkdown>
                  </article>
                </Section>
              </div>
            )}

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Clock size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Execuções recentes</h2>
              </div>
              <ul className="space-y-1 text-xs">
                {agentRuns.map((run) => (
                  <li key={run.run_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                    <button
                      type="button"
                      className="truncate text-left text-foreground hover:text-primary"
                      onClick={async () => {
                        try {
                          setAgentRun(await getWorldAgentRun(run.run_id));
                        } catch (exc) {
                          setError(exc instanceof Error ? exc.message : String(exc));
                        }
                      }}
                    >
                      {run.subject_name ?? "mundo"} · {String(run.question).slice(0, 60)}
                    </button>
                    <span className="shrink-0 text-muted-foreground">
                      {run.elapsed_s ?? "—"}s · {String(run.created_at).slice(0, 16).replace("T", " ")}
                    </span>
                  </li>
                ))}
                {agentRuns.length === 0 && <li className="text-muted-foreground">Sem execuções gravadas.</li>}
              </ul>
            </Section>
          </div>
        )}

        {/* --------------------------------------------------- INVESTIGAÇÃO */}
        {section === "investigacao" && (
          <div className="space-y-4">
            <Section>
              <div className="flex flex-col gap-2">
                <label className="text-xs text-muted-foreground">Pergunta de investigação</label>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  rows={3}
                  className="w-full rounded-xl border border-border bg-muted p-3 text-sm text-foreground outline-none"
                  placeholder="Ex.: Qual é o risco da EDP e o que pode acontecer nos próximos 12 meses?"
                />
                <div className="flex flex-wrap items-end gap-2">
                  <label className="min-w-[220px] flex-1">
                    <span className="mb-1 block text-xs text-muted-foreground">Sujeito (opcional — NIF ou ref)</span>
                    <input
                      value={investigationSubject}
                      onChange={(event) => setInvestigationSubject(event.target.value)}
                      placeholder="Ex.: 503504564"
                      className="w-full rounded-xl border border-border bg-muted px-3 py-2 text-sm text-foreground outline-none"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void handleInvestigate()}
                    disabled={busy === "investigate" || !question.trim()}
                    className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
                  >
                    {busy === "investigate" ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    Investigar
                  </button>
                </div>
              </div>
            </Section>

            {investigation && (
              <div ref={reportRef} className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat label="Passos" value={investigation.steps.length} hint={(investigation.steps.map((step) => step.step).join(" → ") || "").slice(0, 68)} />
                  <Stat label="Hipóteses" value={investigation.hypotheses.length} icon={<Microscope size={13} />} />
                  <Stat label="Evidência" value={investigation.counters?.evidence_total ?? investigation.evidence.length} icon={<FileText size={13} />} />
                  <Stat
                    label="Verificações OK"
                    value={`${investigation.counters?.checks_ok ?? 0}/${investigation.counters?.checks_total ?? 0}`}
                    hint={`${investigation.elapsed_s ?? "—"}s`}
                    icon={<ShieldCheck size={13} />}
                  />
                </div>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <Microscope size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Hipóteses</h2>
                  </div>
                  <ul className="space-y-2 text-xs">
                    {investigation.hypotheses.map((hypothesis) => (
                      <li key={hypothesis.id} className="rounded-xl border border-border bg-muted/30 p-2">
                        <div className="flex items-center gap-2">
                          <Pill className={CLAIM_STYLES[hypothesis.kind] ?? CLAIM_STYLES.HYPOTHESIS}>{hypothesis.kind}</Pill>
                          <span className="font-semibold text-foreground">{hypothesis.id}</span>
                          <span className="text-foreground">{hypothesis.statement}</span>
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground">Como testar: {hypothesis.test}</div>
                      </li>
                    ))}
                  </ul>
                </Section>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <ShieldCheck size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Validação programática</h2>
                  </div>
                  <ul className="space-y-1 text-xs">
                    {(investigation.validation?.checks ?? []).map((check, index) => (
                      <li key={index} className="flex items-start gap-2">
                        {check.ok ? (
                          <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-teal-300" />
                        ) : (
                          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" />
                        )}
                        <span className="text-muted-foreground">
                          {check.check} — esperado {check.expected}, observado {check.observed}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {investigation.claims.map((claim, index) => (
                      <Pill key={index} className={CLAIM_STYLES[claim.kind] ?? CLAIM_STYLES.HYPOTHESIS}>
                        {claim.kind}: {claim.claim.slice(0, 110)}
                        {claim.claim.length > 110 ? "…" : ""}
                      </Pill>
                    ))}
                  </div>
                </Section>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <Gavel size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Evidência</h2>
                  </div>
                  <div className="max-h-80 overflow-y-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-muted-foreground">
                        <tr>
                          <th className="py-1 pr-2">Tipo</th>
                          <th className="py-1 pr-2">Data</th>
                          <th className="py-1 pr-2">Descrição</th>
                          <th className="py-1 pr-2 text-right">Valor</th>
                          <th className="py-1">Origem</th>
                        </tr>
                      </thead>
                      <tbody>
                        {investigation.evidence.map((item) => (
                          <tr key={item.id} className="border-t border-border/60">
                            <td className="py-1 pr-2 text-foreground">{item.type}</td>
                            <td className="py-1 pr-2 text-muted-foreground">{item.ts?.slice(0, 10) ?? "—"}</td>
                            <td className="py-1 pr-2 text-muted-foreground">
                              <span className="block max-w-[380px] truncate">{item.description}</span>
                            </td>
                            <td className="py-1 pr-2 text-right text-foreground">
                              {item.value ? compactCurrency.format(item.value) + " €" : "—"}
                            </td>
                            <td className="py-1 text-muted-foreground">
                              <code className="text-[10px]">
                                {item.source_index}#{item.source_id}
                              </code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Section>

                <Section>
                  <div className="mb-2 flex items-center gap-2">
                    <FileText size={16} className="text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">Relatório</h2>
                    <Pill className="ml-auto border-white/15 bg-white/5 text-muted-foreground">{investigation.run_id}</Pill>
                  </div>
                  <article className="prose prose-invert max-w-none text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{investigation.report}</ReactMarkdown>
                  </article>
                </Section>
              </div>
            )}

            <Section>
              <div className="mb-2 flex items-center gap-2">
                <Clock size={16} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Investigações recentes</h2>
              </div>
              <ul className="space-y-1 text-xs">
                {pastInvestigations.map((run) => (
                  <li key={run.run_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 px-2 py-1">
                    <button
                      type="button"
                      className="truncate text-left text-foreground hover:text-primary"
                      onClick={async () => {
                        try {
                          setInvestigation(await getWorldInvestigation(run.run_id));
                        } catch (exc) {
                          setError(exc instanceof Error ? exc.message : String(exc));
                        }
                      }}
                    >
                      {run.subject_name ?? run.question}
                    </button>
                    <span className="shrink-0 text-muted-foreground">{run.created_at?.slice(0, 16).replace("T", " ")}</span>
                  </li>
                ))}
                {pastInvestigations.length === 0 && <li className="text-muted-foreground">Sem investigações gravadas.</li>}
              </ul>
            </Section>
          </div>
        )}
      </main>
    </div>
  );
}
