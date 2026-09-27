/**
 * Cliente do módulo World Model (`/world/*`).
 *
 * Servir este módulo é percorrer o pipeline completo do IQ OS:
 * **Public Data → World Model → Dynamic Neural Network → Graph/Temporal →
 * Future Simulator → Investigation Agent**. Cada camada tem os seus endpoints e
 * a página `WorldPage` compõe-nas; a rede dinâmica é mostrada **como grafo**
 * (`getWorldNetworkGraph`, consumido pelo `GraphCanvas`).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type WorldSource = {
  id: string;
  label: string;
  index: string;
  country: string;
  kind: string;
  description: string;
  exists?: boolean;
  documents?: number;
  /** Como a fonte entra no mundo: `contratos`, `registo`, `publicacoes`, ... */
  adapter?: string;
  /** Chave de junção: `nif` (exata), `nome` (designação legal) ou `texto`. */
  join?: string;
  contributes?: string[];
  default?: boolean;
  associable?: boolean;
  required?: boolean;
  associated?: boolean;
  error?: string;
};

/** Catálogo de fontes do sistema + o que está associado ao Public Data. */
export type WorldSourcesOverview = {
  sources: WorldSource[];
  associated: string[];
  adapters?: string[];
  counts?: Record<string, number>;
  unknown?: string[];
  note?: string;
};

export type WorldArchitectureLayer = {
  id: string;
  label: string;
  hint: string;
  items: string[];
  backend: string;
};

export type WorldEntity = {
  entity_ref: string;
  entity_id: string;
  entity_type: string;
  name: string;
  names?: string[];
  country?: string;
  roles?: string[];
  sources?: string[];
  state?: {
    status?: string;
    insolvent?: boolean;
    insolvency_roles?: string[];
    avg_ticket?: number;
    concentration?: number;
    concentration_reliable?: boolean;
    dependency?: number;
    last_seen?: string | null;
    activity_trend?: string;
  };
  metrics?: Record<string, number>;
  contracts_count?: number;
  contracts_value?: number;
  relations_count?: number;
  events_count?: number;
  counterparties_count?: number;
  top_cpv?: string | null;
  cpv_codes?: string[];
  risk?: number;
  risk_label?: string;
  activity?: number;
  activity_trend?: string;
  first_seen?: string | null;
  last_event_at?: string | null;
  insolvent?: boolean;
  world_version?: number;
  updated_at?: string;
  _score?: number | null;
};

export type WorldEvent = {
  event_id?: string;
  kind: string;
  kind_label?: string;
  entity_ref?: string;
  entity_name?: string;
  entity_type?: string;
  counterparty_ref?: string | null;
  counterparty_name?: string | null;
  ts?: string | null;
  year?: number | null;
  value?: number | null;
  severity?: number | null;
  severity_label?: string;
  country?: string;
  source_index?: string;
  source_id?: string;
};

export type WorldRelation = {
  relation_id: string;
  kind: string;
  kind_label?: string;
  source_ref: string;
  source_name?: string | null;
  source_type?: string;
  target_ref: string;
  target_name?: string | null;
  target_type?: string;
  weight?: number;
  contracts_count?: number;
  value_sum?: number;
  first_ts?: string | null;
  last_ts?: string | null;
  status?: string;
};

export type WorldGraphNode = {
  id: string;
  name: string;
  entity_type?: string;
  risk?: number | null;
  risk_label?: string | null;
  contracts_value?: number | null;
  degree?: number;
  origin?: boolean;
};

export type WorldGraphEdge = {
  id: string;
  source: string;
  target: string;
  kind?: string;
  kind_label?: string;
  weight?: number;
  value_sum?: number;
  contracts_count?: number;
  first_ts?: string | null;
  last_ts?: string | null;
};

export type WorldGraph = {
  origin?: string | null;
  nodes: WorldGraphNode[];
  edges: WorldGraphEdge[];
  truncated?: boolean;
  metrics?: { nodes: number; edges: number; avg_degree: number };
  meta?: Record<string, unknown>;
  error?: string;
};

export type NetworkNode = {
  id: string;
  label: string;
  type: string;
  dimension?: string;
  count: number;
  total_value: number;
  activation?: number;
  degree?: number;
  risk?: number | null;
  risk_label?: string | null;
  score?: number | null;
  expected_contracts?: number | null;
  risk_after?: number | null;
  insolvent?: boolean;
  trend?: string | null;
  memory_hits?: number;
  age?: number;
  features?: number[] | null;
};

export type NetworkEdge = {
  source: string;
  target: string;
  count: number;
  value: number;
  weight: number;
  kind?: string;
};

export type NetworkGraph = {
  trained?: boolean;
  error?: string;
  version?: number;
  created_at?: string;
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  memory?: { id: string; label: string; hits: number; age?: number; entity_ref?: string }[];
  metrics?: Record<string, number | null>;
  pruned?: Record<string, number>;
  growth?: Record<string, number>;
  readout?: Record<string, unknown>;
  params?: Record<string, unknown>;
  meta?: Record<string, unknown>;
};

export type SimulationStep = {
  step: number;
  label: string;
  new_contracts: Percentiles;
  delays: Percentiles;
  cancellations: Percentiles;
  new_relations: Percentiles;
  financial_change: Percentiles;
  risk: Percentiles;
};

export type Percentiles = { mean: number; p10: number; p50: number; p90: number };

export type SimulationScenario = {
  id: string;
  label: string;
  note: string;
  weight: number;
  rates: Record<string, number>;
  steps: SimulationStep[];
  totals: Record<string, Percentiles>;
};

export type SimulationRun = {
  run_id: string;
  created_at: string;
  kind: string;
  subject_ref?: string | null;
  subject_name?: string | null;
  horizon: number;
  step_months: number;
  samples: number;
  steps: SimulationStep[];
  scenarios: SimulationScenario[];
  summary: {
    subject?: string;
    scenario_labels: string[];
    scenario_matrix: number[][];
    totals: Record<string, number>;
    rates: Record<string, number>;
    assumptions: string[];
  };
  status: string;
  elapsed_s?: number;
};

export type Investigation = {
  run_id: string;
  question: string;
  created_at: string;
  status: string;
  elapsed_s?: number;
  subject_ref?: string | null;
  subject_name?: string | null;
  steps: { step: string; elapsed_s: number; [key: string]: unknown }[];
  hypotheses: { id: string; kind: string; statement: string; test: string; basis: string[] }[];
  evidence: {
    id: string;
    type: string;
    source_index?: string;
    source_id?: string;
    description?: string;
    ts?: string | null;
    value?: number | null;
    severity?: number | null;
  }[];
  claims: { kind: string; claim: string; confidence: number; sources?: string[] }[];
  validation?: { checks: { check: string; expected: string; observed: string; ok: boolean }[] };
  counters?: Record<string, number>;
  report: string;
};

export type HistoryRow = {
  entity_ref: string;
  entity_type?: string;
  name?: string;
  grain?: string;
  period: string;
  period_start?: string;
  period_end?: string;
  contracts?: number;
  value?: number;
  events?: number;
  kinds?: Record<string, number>;
  new_counterparties?: number;
  cum_contracts?: number;
  cum_value?: number;
  cum_counterparties?: number;
  cum_directors?: number;
  insolvent?: boolean;
  risk?: number;
  risk_label?: string;
  delta_contracts?: number;
  delta_value?: number;
  status?: string;
};

/** Nó do grafo de execução do pipeline (camada do diagrama). */
export type PipelineNode = {
  id: string;
  label: string;
  hint: string;
  backend: string;
  dimension: string;
  type: string;
  position: number;
  documents: number;
  artifacts: { label: string; documents: number | null }[];
  count?: number;
  total_value?: number;
  radius?: number;
  color?: string;
  legendKey?: string;
  legendLabel?: string;
  value?: number;
};

export type PipelineGraph = {
  nodes: PipelineNode[];
  edges: { id: string; source: string; target: string; label: string; kind: string }[];
  mermaid: string;
  metrics: { layers: number; edges: number; documents: number; last_rebuild?: string | null; version?: number };
};

export type AnomalySignal = { id: string; label: string; detail?: string };

export type Anomaly = {
  entity_ref: string;
  entity_name: string;
  entity_type?: string;
  period?: string;
  score: number;
  label: string;
  signals: AnomalySignal[];
  signal_ids: string[];
  risk?: number;
  cum_contracts?: number;
  cum_value?: number;
  periods?: number;
  interpretation: string;
};

export type TransitionModel = {
  available: boolean;
  reason?: string;
  pairs?: number;
  entities?: number;
  r2?: number;
  rmse?: number;
  features?: string[];
  rmse_by_feature?: Record<string, number>;
  holdout?: number;
  note?: string;
};

export type TransitionForecast = {
  entity_ref: string;
  base_period?: string;
  transition_r2?: number;
  steps: { step: number; cum_contracts: number; cum_value: number; cum_counterparties: number; risk: number; contracts: number; value: number }[];
};

export type ExecutionNode = {
  id: string;
  agent: string;
  label: string;
  action: string;
  status: string;
  elapsed_s: number;
  outputs: Record<string, unknown>;
  evidence: string[];
  note?: string | null;
};

export type ExecutionGraph = {
  nodes: ExecutionNode[];
  edges: { id: string; source: string; target: string; label: string; kind: string }[];
  mermaid: string;
  metrics: { steps: number; flows: number };
};

export type EvidenceGraph = {
  nodes: {
    id: string;
    label: string;
    type: string;
    dimension?: string;
    count?: number;
    total_value?: number;
    source_index?: string;
    source_id?: string;
    claim_kind?: string;
    confidence?: number;
  }[];
  edges: { id: string; source: string; target: string; label: string; kind: string }[];
  mermaid: string;
  counts: Record<string, number>;
  metrics: { nodes: number; edges: number };
};

export type AgentRun = {
  run_id: string;
  question: string;
  created_at: string;
  status: string;
  engine?: string;
  elapsed_s?: number;
  subject_ref?: string | null;
  subject_name?: string | null;
  subject_type?: string | null;
  subject_resolution?: string;
  chosen_by_network?: boolean;
  network_version?: number | null;
  anomaly?: Anomaly | null;
  plan?: { agent: string; action: string; why: string }[];
  execution_graph: ExecutionGraph;
  evidence_graph: EvidenceGraph;
  relations_graph: WorldGraph & { mermaid?: string };
  hypotheses: { id: string; kind: string; statement: string; test: string; basis: string[] }[];
  evidence: {
    id: string;
    type: string;
    source_index?: string;
    source_id?: string;
    description?: string;
    ts?: string | null;
    value?: number | null;
  }[];
  claims: { kind: string; claim: string; confidence: number; sources?: string[] }[];
  validation?: { checks: { check: string; expected: string; observed: string; ok: boolean }[] };
  simulation?: SimulationRun | null;
  counters?: Record<string, number>;
  report: string;
};

export type WorldJob = {
  job_id: string;
  kind: string;
  status: string;
  created_at: string;
  finished_at?: string | null;
  elapsed_s?: number;
  progress: { label: string; at: string }[];
  error?: string | null;
  result?: Record<string, unknown> | null;
};

/* ----------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/* -------------------------------------------------------------------- API */

export function getWorldMeta() {
  return request<Record<string, unknown>>("/world/meta");
}

export function getWorldArchitecture() {
  return request<{ architecture: WorldArchitectureLayer[] }>("/world/architecture");
}

export function getWorldSources() {
  return request<WorldSourcesOverview>("/world/sources");
}

/** Associa/desassocia fontes do sistema no Public Data (aplica-se na reconstrução). */
export function saveWorldSources(ids: string[]) {
  return request<WorldSourcesOverview>("/world/sources", withBody("PUT", { ids }));
}

export function getWorldStatus() {
  return request<Record<string, unknown>>("/world/status");
}

export function getWorldSchedule() {
  return request<Record<string, unknown>>("/world/schedule");
}

export function updateWorldSchedule(payload: {
  enabled?: boolean;
  cron?: string;
  timezone?: string;
  train_network?: boolean;
}) {
  return request<Record<string, unknown>>("/world/schedule", withBody("PUT", payload));
}

export function updateWorldConfig(payload: Record<string, unknown>) {
  return request<Record<string, unknown>>("/world/config", withBody("PUT", payload));
}

export function rebuildWorld(payload: Record<string, unknown> = {}) {
  return request<{ job_id?: string; status?: string; job?: WorldJob }>("/world/rebuild", withBody("POST", payload));
}

export function getWorldJobs() {
  return request<{ jobs: WorldJob[] }>("/world/jobs");
}

export function searchWorldEntities(params: {
  q?: string;
  type?: string;
  country?: string;
  risk?: string;
  role?: string;
  insolvent?: boolean;
  sort?: string;
  size?: number;
  page?: number;
}) {
  return request<{ total: number; results: WorldEntity[]; error?: string }>(`/world/entities${query(params)}`);
}

export function getWorldEntity(entityRef: string) {
  return request<{
    entity: WorldEntity;
    prediction: Record<string, unknown> | null;
    relations: WorldRelation[];
    timeline: WorldEvent[];
  }>(`/world/entities/${encodeURIComponent(entityRef)}`);
}

export function getWorldEvents(params: {
  entity_ref?: string;
  kind?: string;
  year_from?: number;
  year_to?: number;
  size?: number;
}) {
  return request<{ total: number; events: WorldEvent[] }>(`/world/events${query(params)}`);
}

export function getWorldEventStats() {
  return request<{ kinds: { key: string; count: number }[]; years: { key: number; count: number }[] }>(
    "/world/events/stats",
  );
}

export function getWorldRelations(params: { entity_ref?: string; kind?: string; size?: number }) {
  return request<{ total: number; relations: WorldRelation[] }>(`/world/relations${query(params)}`);
}

export function getWorldGraph(params: { entity_ref?: string; depth?: number; kind?: string; nodes?: number; edges?: number }) {
  return request<WorldGraph>(`/world/graph${query(params)}`);
}

export function getWorldGraphDimensions() {
  return request<{ dimensions: { id: string; label: string; kind: string }[] }>("/world/graph/dimensions");
}

export function getWorldCentrality(params: { kind?: string; top?: number }) {
  return request<{
    results: { entity_ref: string; name: string; entity_type?: string; degree: number; contracts_value?: number; risk?: number; risk_label?: string }[];
    note?: string;
  }>(`/world/centrality${query(params)}`);
}

export function getWorldPaths(params: { source: string; target: string; max_depth?: number; kind?: string }) {
  return request<{
    source: string;
    target: string;
    count: number;
    paths: { id: string; name: string; entity_type?: string }[][];
    note?: string;
  }>(`/world/paths${query(params)}`);
}

export function getWorldTemporal(params: { entity_ref?: string; kind?: string; years?: number; interval?: string }) {
  return request<{
    interval: string;
    series: { period: string; events: number; value: number; kinds: { key: string; count: number }[] }[];
  }>(`/world/temporal${query(params)}`);
}

export function getWorldCausality(params: { entity_ref?: string; window_days?: number; limit?: number }) {
  return request<{
    count: number;
    window_days: number;
    note: string;
    links: {
      cause: { event?: string; entity_name?: string; ts?: string; value?: number | null };
      effect: { event?: string; entity_name?: string; ts?: string; value?: number | null };
      mechanism_label?: string;
      days: number;
      score: number;
      interpretation: string;
    }[];
  }>(`/world/causality${query(params)}`);
}

export function trainWorldNetwork(payload: Record<string, unknown> = {}) {
  return request<{ job_id?: string; status?: string; job?: WorldJob }>("/world/network/train", withBody("POST", payload));
}

export function getWorldNetwork(params: { version?: number } = {}) {
  return request<Record<string, unknown>>(`/world/network${query(params)}`);
}

export function getWorldNetworkGraph(params: { limit?: number; memory?: boolean; entity_ref?: string; version?: number } = {}) {
  return request<NetworkGraph>(`/world/network/graph${query(params)}`);
}

export function getWorldNetworkHistory(limit = 20) {
  return request<{ history: Record<string, unknown>[] }>(`/world/network/history${query({ limit })}`);
}

export function getWorldNetworkRecall(entityRef: string) {
  return request<{ entity_ref?: string; patterns: { pattern_id: string; label: string; similarity: number; hits?: number; age?: number }[]; error?: string }>(
    `/world/network/recall/${encodeURIComponent(entityRef)}`,
  );
}

export function runWorldSimulation(payload: {
  subject?: string;
  horizon?: number;
  step_months?: number;
  samples?: number;
  seed?: number;
}) {
  return request<SimulationRun>("/world/simulate", withBody("POST", payload));
}

export function getWorldSimulations(limit = 20) {
  return request<{ simulations: SimulationRun[] }>(`/world/simulations${query({ limit })}`);
}

export function getWorldSimulation(runId: string) {
  return request<SimulationRun>(`/world/simulations/${encodeURIComponent(runId)}`);
}

export function investigateWorld(payload: {
  question: string;
  subject?: string;
  horizon?: number;
  samples?: number;
  simulate?: boolean;
}) {
  return request<Investigation>("/world/investigate", withBody("POST", payload));
}

export function getWorldInvestigations(limit = 20) {
  return request<{ investigations: Investigation[] }>(`/world/investigations${query({ limit })}`);
}

export function getWorldInvestigation(runId: string) {
  return request<Investigation>(`/world/investigations/${encodeURIComponent(runId)}`);
}

/* -------------------------------------- estado temporal / pipeline / agente */

export function getWorldHistory(params: { grain?: string; limit?: number } = {}) {
  return request<{ total: number; series: HistoryRow[] }>(`/world/history${query(params)}`);
}

export function getWorldHistorySeries(params: { grain?: string; limit?: number } = {}) {
  return request<{
    grain: string;
    series: { period: string; entities: number; contracts: number; value: number; new_counterparties: number }[];
  }>(`/world/history/series${query(params)}`);
}

export function getEntityHistory(entityRef: string, params: { grain?: string; limit?: number } = {}) {
  return request<{ entity_ref: string; total: number; series: HistoryRow[] }>(
    `/world/history/${encodeURIComponent(entityRef)}${query(params)}`,
  );
}

export function getWorldPipelineGraph() {
  return request<PipelineGraph>("/world/pipeline/graph");
}

export function getWorldAnomalies(params: { limit?: number; entity_ref?: string } = {}) {
  return request<{
    available: boolean;
    reason?: string;
    version?: number;
    counts?: Record<string, number>;
    anomalies: Anomaly[];
    note?: string;
  }>(`/world/network/anomalies${query(params)}`);
}

export function getWorldTransition() {
  return request<TransitionModel>("/world/network/transition");
}

export function getEntityTransition(entityRef: string, steps = 6) {
  return request<TransitionForecast>(`/world/network/transition/${encodeURIComponent(entityRef)}${query({ steps })}`);
}

export function getAgentCatalog() {
  return request<{
    agents: { id: string; label: string; role: string; consumes: string[]; produces: string[] }[];
    flow: { source: string; target: string; label: string }[];
    mermaid: string;
  }>("/world/agent/catalog");
}

export function getAgentTargets(limit = 10) {
  return request<{
    version?: number;
    targets: {
      entity_ref: string;
      entity_name: string;
      entity_type?: string;
      score: number;
      label: string;
      signals: string[];
      interpretation?: string;
    }[];
    note?: string;
  }>(`/world/agent/targets${query({ limit })}`);
}

export function runWorldAgent(payload: {
  question: string;
  subject?: string;
  horizon?: number;
  samples?: number;
  simulate?: boolean;
}) {
  return request<AgentRun>("/world/agent/run", withBody("POST", payload));
}

export function getWorldAgentRuns(limit = 20) {
  return request<{ runs: AgentRun[] }>(`/world/agent/runs${query({ limit })}`);
}

export function getWorldAgentRun(runId: string) {
  return request<AgentRun>(`/world/agent/runs/${encodeURIComponent(runId)}`);
}
