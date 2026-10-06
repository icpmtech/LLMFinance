/**
 * Cliente do módulo **MiroFish** (`/mirofish/*`).
 *
 * O MiroFish é o motor de previsão por enxame de agentes que corre em Docker
 * (`docker compose --profile mirofish up -d`) e que se abre como página iframe
 * «MiroFish». Aqui ficam as chamadas que **alimentam** essa máquina com dados do
 * sistema e que **conduzem** a simulação.
 */
import { API_BASE } from "./api";

export type MiroFishParam = {
  name: string;
  label: string;
  type: "text" | "number" | "select" | "document";
  required?: boolean;
  placeholder?: string;
  default?: string | number;
  options?: string[];
  min?: number;
  max?: number;
};

export type MiroFishSource = {
  id: string;
  label: string;
  hint: string;
  params: MiroFishParam[];
  requirement: string;
};

export type MiroFishService = {
  available: boolean;
  base_url: string;
  status?: number;
  service?: string | null;
  detail?: string | null;
};

export type MiroFishMeta = {
  service: MiroFishService;
  public_url: string;
  sources: MiroFishSource[];
  defaults: { source: string; platform: string; steps: Record<string, boolean> };
  notes: string[];
};

export type MiroFishSeed = {
  source: string;
  label?: string;
  title: string;
  filename: string;
  markdown: string;
  chars: number;
  words: number;
  suggested_requirement: string;
  stats: Record<string, unknown>;
};

export type MiroFishJobLog = { at: string; message: string; level: string };

export type MiroFishJob = {
  id: string;
  kind: string;
  title: string;
  status: "running" | "done" | "failed";
  step: string;
  progress: number;
  created_at: string;
  updated_at: string;
  log: MiroFishJobLog[];
  result: Record<string, unknown>;
  error?: string | null;
  /** O que fazer para resolver (ex.: que chave definir), quando o erro é conhecido. */
  hint?: string | null;
};

export type MiroFishKeyRequirement = {
  name: string;
  aliases: string[];
  role: string;
  where: string;
  detail: string;
};

export type MiroFishDiagnose = {
  service: MiroFishService;
  keys: MiroFishKeyRequirement[];
  host_env: Record<string, boolean | string>;
  note: string;
  commands: Record<string, string>;
  last_error: { job: string; title?: string; at?: string; error?: string; hint?: string } | null;
};

export type MiroFishStatus = {
  service: MiroFishService;
  projects: Record<string, unknown>[];
  simulations: Record<string, unknown>[];
};

export type MiroFishSeedRequest = {
  source: string;
  params: Record<string, string | number | undefined>;
  requirement?: string;
};

export type MiroFishSearchSourceResult = {
  source_id: string;
  source_label: string;
  source_family?: string;
  title: string;
  subtitle?: string | null;
  snippet?: string | null;
  url?: string | null;
  date?: string | null;
  icon?: string;
  badges?: string[];
  score?: number;
  selected?: boolean;
  data?: Record<string, unknown>;
};

export type MiroFishSimulationRequest = MiroFishSeedRequest & {
  title?: string;
  project_name?: string;
  max_rounds?: number;
  platform?: string;
  steps?: Record<string, boolean>;
};

export type MiroFishProviderOption = {
  id: string;
  label: string;
  base_url: string;
  default_model: string;
  models: string[];
  docs_url?: string;
  key_optional: boolean;
  configured: boolean;
  key_source: string;
  key_hint: string;
  usable: boolean;
};

export type MiroFishSettingsView = {
  settings: {
    llm_provider: string | null;
    llm_model: string;
    llm_base_url: string;
    llm_key_hint: string;
    llm_key_source: string;
    llm_custom: boolean;
    zep_key_set: boolean;
    zep_key_hint: string;
    updated_at: string | null;
    updated_by: string | null;
    applied_at: string | null;
  };
  providers: MiroFishProviderOption[];
  env: {
    path: string;
    exists: boolean;
    llm_key_hint: string;
    zep_key_hint: string;
    llm_base_url: string;
    llm_model: string;
    in_sync: boolean;
  };
  docker: { available: boolean; project_dir: string };
  commands: Record<string, string>;
};

export type MiroFishSettingsPayload = {
  llm_provider?: string;
  llm_model?: string;
  llm_base_url?: string;
  llm_api_key?: string;
  zep_api_key?: string;
  apply?: boolean;
  recreate?: boolean;
};

export type MiroFishApplyResult = {
  applied: {
    written: string[];
    env_path: string;
    llm: { provider: string; model: string; base_url: string; key_hint: string; source: string };
    zep: { key_hint: string };
    recreate: { ok: boolean; command: string; exit_code?: number; output?: string[]; detail?: string } | null;
  } | null;
} & Partial<MiroFishSettingsView>;

export type OfficeDocumentSummary = {
  id: string;
  title?: string;
  kind?: string;
  words?: number;
  updated_at?: string;
};

/** Estado da execução/relatório já traduzido pelo backend. */
export type MiroFishRunState = {
  key: string;
  label: string;
  tone: "idle" | "busy" | "ok" | "warn" | "error" | string;
};

/** Simulação vista a partir da lista (com estado ao vivo nas mais recentes). */
export type MiroFishRunSummary = {
  simulation_id: string;
  project_id?: string | null;
  graph_id?: string | null;
  title: string;
  state: MiroFishRunState;
  created_at?: string | null;
  updated_at?: string | null;
  profiles_count?: number | null;
  entities_count?: number | null;
  entity_types?: string[];
  platforms?: { twitter: boolean; reddit: boolean };
  job?: { id?: string | null; status?: string | null; step?: string | null } | null;
  live?: {
    round_current?: number | null;
    rounds_total?: number | null;
    progress?: number | null;
    actions_total?: number | null;
    actions_twitter?: number | null;
    actions_reddit?: number | null;
    simulated_hours?: number | null;
    hours_total?: number | null;
    started_at?: string | null;
    completed_at?: string | null;
    twitter_round?: number | null;
    reddit_round?: number | null;
  } | null;
  report?: { has_report: boolean; report_id?: string | null; status: MiroFishRunState; interview_unlocked: boolean } | null;
};

/** Uma ação de um agente no feed da simulação. */
export type MiroFishAction = {
  id: string;
  agent_id?: number | null;
  agent_name: string;
  action_type?: string | null;
  action: string;
  platform?: string;
  round?: number | null;
  timestamp?: string | null;
  success: boolean;
  content: string;
  target?: string;
};

export type MiroFishActionPage = {
  count: number;
  offset: number;
  limit: number;
  actions: MiroFishAction[];
};

/** Um agente do elenco: quem representa, como se comporta e o que fez. */
export type MiroFishAgent = {
  agent_id?: number | null;
  name: string;
  entity_type?: string;
  influence?: number | null;
  activity?: number | null;
  stance?: string;
  sentiment?: number | null;
  active_hours?: number[];
  age?: number | null;
  gender?: string;
  mbti?: string;
  country?: string;
  karma?: number | null;
  topics?: string[];
  bio?: string;
  persona?: string;
  actions_total: number;
  actions_twitter: number;
  actions_reddit: number;
  actions_detail: Record<string, number>;
  first_action_at?: string | null;
  last_action_at?: string | null;
};

export type MiroFishCast = {
  count: number;
  agents: MiroFishAgent[];
  by_type: { type: string; count: number }[];
};

/** Trabalho da plataforma que lançou a simulação (semente, projeto e registo). */
export type MiroFishRunJob = {
  id?: string | null;
  title?: string | null;
  status?: string | null;
  step?: string | null;
  progress?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  hint?: string | null;
  seed?: { source?: string; title?: string; chars?: number; words?: number } | null;
  project_id?: string | null;
  report_id?: string | null;
  log?: MiroFishJobLog[];
};

export type MiroFishRunOverview = {
  simulation: {
    simulation_id: string;
    project_id?: string;
    graph_id?: string;
    title: string;
    project_name?: string;
    requirement?: string;
    reasoning?: string;
    analysis?: string;
    created_at?: string | null;
    updated_at?: string | null;
    entity_types?: string[];
    profiles_count?: number | null;
    entities_count?: number | null;
    ontology?: { entity_types: string[]; edge_types: string[] };
  };
  state: MiroFishRunState;
  active: boolean;
  metrics: {
    round_current?: number | null;
    rounds_total?: number | null;
    progress?: number | null;
    actions_total?: number | null;
    actions_twitter?: number | null;
    actions_reddit?: number | null;
    simulated_hours?: number | null;
    hours_total?: number | null;
    agents_total?: number | null;
    entities_total?: number | null;
    started_at?: string | null;
    completed_at?: string | null;
  };
  platforms: Record<"twitter" | "reddit", { running: boolean; completed: boolean; round?: number | null; actions?: number | null }>;
  rounds: { round?: number | null; total: number; twitter: number; reddit: number; agents: number; types: Record<string, number> }[];
  actions: MiroFishAction[];
  cast: MiroFishAgent[];
  state_counts: { type: string; count: number }[];
  report: { has_report: boolean; report_id?: string | null; status: MiroFishRunState; interview_unlocked: boolean };
  job?: MiroFishRunJob | null;
  report_hint?: string | null;
};

export type MiroFishReportSection = { title: string; chars: number; content: string };

/** Relatório escrito pelo MiroFish (markdown + secções). */
export type MiroFishReport = {
  report_id?: string | null;
  simulation_id?: string | null;
  status: MiroFishRunState;
  title: string;
  summary: string;
  requirement: string;
  created_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  chars: number;
  words: number;
  markdown: string;
  sections: MiroFishReportSection[];
};

export type MiroFishReportView = {
  simulation_id: string;
  has_report: boolean;
  report_id?: string | null;
  status: MiroFishRunState;
  interview_unlocked: boolean;
  started?: boolean;
  report?: MiroFishReport | null;
};

/** Estado do ambiente de simulação (aceita entrevistas enquanto estiver vivo). */
export type MiroFishEnvironment = {
  simulation_id: string;
  alive: boolean;
  platforms: { twitter: boolean; reddit: boolean };
  message: string;
  interview_hint?: string | null;
};

/** Resposta de uma entrevista em lote (uma linha por agente/plataforma). */
export type MiroFishInterviewAnswer = {
  agent_id?: number | null;
  platform?: string;
  response: string;
  error?: string | null;
};

export type MiroFishInterviewBatch = {
  simulation_id: string;
  prompt: string;
  asked: number;
  answered: number;
  answers: MiroFishInterviewAnswer[];
};

/** Publicações/comentários do mundo simulado (campos variam com a plataforma). */
export type MiroFishContentPage = {
  simulation_id: string;
  platform: string;
  total: number;
  offset: number;
  posts?: Record<string, unknown>[];
  comments?: Record<string, unknown>[];
};

/** Registo do relatório (consola do motor ou ações do agente). */
export type MiroFishReportLog = {
  simulation_id: string;
  report_id?: string | null;
  kind: "console" | "agent";
  from_line: number;
  total_lines: number;
  has_more: boolean;
  lines: (string | Record<string, unknown>)[];
};

export type MiroFishGraphFact = {
  fact: string;
  name?: string;
  source_name?: string;
  target_name?: string;
  type?: string;
  score?: number | null;
};

export type MiroFishGraphSearch = {
  simulation_id: string;
  graph_id: string;
  query: string;
  facts: MiroFishGraphFact[];
  nodes: { name: string; type?: string; summary?: string; score?: number | null }[];
};

export type MiroFishGraphStats = {
  simulation_id: string;
  graph_id: string;
  node_count: number;
  edge_count: number;
  entity_types: unknown[];
  detail: Record<string, unknown>;
};

/** Nó do grafo de conhecimento (Zep): tipo de entidade, resumo e grau. */
export type MiroFishGraphNode = {
  id: string;
  name: string;
  type: string;
  labels: string[];
  summary: string;
  created_at?: string | null;
  attributes: Record<string, unknown>;
  degree: number;
};

/** Facto do Zep: liga dois nós e traz a frase que o justifica. */
export type MiroFishGraphEdge = {
  id: string;
  source: string;
  target: string;
  source_name: string;
  target_name: string;
  type: string;
  fact: string;
  valid_at?: string | null;
  episodes: number;
};

export type MiroFishGraph = {
  simulation_id: string;
  project_id?: string;
  graph_id: string;
  node_count: number;
  edge_count: number;
  nodes: MiroFishGraphNode[];
  edges: MiroFishGraphEdge[];
  types: { type: string; count: number }[];
  relations: { type: string; count: number }[];
  omitted: { nodes: number; edges: number; reason: string };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      // resposta sem JSON: fica o código
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** Endereço público da UI do MiroFish (o mesmo que a página iframe usa). */
export function mirofishPublicUrl(configured?: string): string {
  const value = String(configured || "").trim();
  if (value) return value.replace(/\/+$/, "");
  const host = typeof window !== "undefined" && window.location.hostname ? window.location.hostname : "127.0.0.1";
  return `http://${host}:8893`;
}

export const mirofishApi = {
  meta: () => request<MiroFishMeta>("/mirofish/meta"),
  status: () => request<MiroFishStatus>("/mirofish/status"),
  diagnose: () => request<MiroFishDiagnose>("/mirofish/diagnose"),
  seed: (payload: MiroFishSeedRequest) => request<MiroFishSeed>("/mirofish/seed", withBody("POST", payload)),
  saveSeed: (payload: MiroFishSeedRequest & { title?: string; folder_id?: string; tags?: string[] }) =>
    request<{ document: OfficeDocumentSummary; seed: { title: string; chars: number; words: number } }>(
      "/mirofish/seed/office",
      withBody("POST", payload),
    ),
  simulate: (payload: MiroFishSimulationRequest) => request<MiroFishJob>("/mirofish/simulations", withBody("POST", payload)),
  /** Pesquisa direta para selecionar fontes de simulação (Search360 / web). */
  search: (payload: { term: string; sources?: string[]; limit?: number }) =>
    request<{ term: string; items: MiroFishSearchSourceResult[]; stats: Record<string, unknown> }>("/search360/search", withBody("POST", payload)),
  settings: () => request<MiroFishSettingsView>("/mirofish/settings"),
  saveSettings: (payload: MiroFishSettingsPayload) => request<MiroFishApplyResult>("/mirofish/settings", withBody("PUT", payload)),
  applySettings: (recreate = true) =>
    request<MiroFishApplyResult>(`/mirofish/settings/apply?recreate=${recreate ? "true" : "false"}`, { method: "POST" }),
  jobs: (limit = 10) => request<{ jobs: MiroFishJob[] }>(`/mirofish/jobs?limit=${limit}`),
  job: (id: string) => request<MiroFishJob>(`/mirofish/jobs/${id}`),
  documents: () =>
    request<{ items: OfficeDocumentSummary[]; total: number }>("/office/documents?limit=200").catch(() => ({
      items: [],
      total: 0,
    })),

  // --- Simulador IQ OS: resultados ----------------------------------------
  runs: (limit = 20, enrich = 6) => request<{ count: number; runs: MiroFishRunSummary[] }>(`/mirofish/runs?limit=${limit}&enrich=${enrich}`),
  run: (simulationId: string, actions = 30) =>
    request<MiroFishRunOverview>(`/mirofish/runs/${encodeURIComponent(simulationId)}?actions=${actions}`),
  runActions: (simulationId: string, options: { limit?: number; offset?: number; platform?: string; agentId?: number; round?: number } = {}) => {
    const query = new URLSearchParams();
    query.set("limit", String(options.limit ?? 60));
    query.set("offset", String(options.offset ?? 0));
    if (options.platform) query.set("platform", options.platform);
    if (options.agentId !== undefined) query.set("agent_id", String(options.agentId));
    if (options.round !== undefined) query.set("round_num", String(options.round));
    return request<MiroFishActionPage>(`/mirofish/runs/${encodeURIComponent(simulationId)}/actions?${query.toString()}`);
  },
  runAgents: (simulationId: string) => request<MiroFishCast>(`/mirofish/runs/${encodeURIComponent(simulationId)}/agents`),
  runGraph: (simulationId: string, nodes = 150, edges = 500) =>
    request<MiroFishGraph>(`/mirofish/runs/${encodeURIComponent(simulationId)}/graph?nodes=${nodes}&edges=${edges}`),
  stopRun: (simulationId: string) =>
    request<{ simulation_id: string; state: MiroFishRunState; detail: Record<string, unknown> }>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/stop`,
      { method: "POST" },
    ),
  interview: (simulationId: string, payload: { prompt: string; agent_id?: number; platform?: string; timeout?: number }) =>
    request<{ simulation_id: string; mode: string; data: Record<string, unknown> }>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/interview`,
      withBody("POST", payload),
    ),
  runReport: (simulationId: string) => request<MiroFishReportView>(`/mirofish/runs/${encodeURIComponent(simulationId)}/report`),
  generateReport: (simulationId: string, force = false) =>
    request<MiroFishReportView>(`/mirofish/runs/${encodeURIComponent(simulationId)}/report`, withBody("POST", { force })),
  askReport: (simulationId: string, message: string, history: { role: string; content: string }[] = []) =>
    request<{ simulation_id: string; answer: string; tools: unknown[]; sources: string[] }>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/report/chat`,
      withBody("POST", { message, history }),
    ),

  // --- ações na simulação (como na página de interação do MiroFish) --------
  runEnvironment: (simulationId: string) =>
    request<MiroFishEnvironment>(`/mirofish/runs/${encodeURIComponent(simulationId)}/environment`),
  closeEnvironment: (simulationId: string, timeout = 30) =>
    request<{ simulation_id: string; closed: boolean; detail: Record<string, unknown> | string }>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/environment/close?timeout=${timeout}`,
      { method: "POST" },
    ),
  startRun: (
    simulationId: string,
    payload: { max_rounds?: number; platform?: string; force?: boolean; memory_update?: boolean } = {},
  ) =>
    request<{ simulation_id: string; state: MiroFishRunState; max_rounds?: number | null; memory_update: boolean }>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/start`,
      withBody("POST", { platform: "parallel", force: true, ...payload }),
    ),
  interviewBatch: (
    simulationId: string,
    payload: { prompt: string; agents: (number | string)[]; platform?: string; timeout?: number },
  ) =>
    request<MiroFishInterviewBatch>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/interview/batch`,
      withBody("POST", payload),
    ),
  runPosts: (simulationId: string, options: { platform?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    query.set("limit", String(options.limit ?? 30));
    query.set("offset", String(options.offset ?? 0));
    if (options.platform) query.set("platform", options.platform);
    return request<MiroFishContentPage>(`/mirofish/runs/${encodeURIComponent(simulationId)}/posts?${query.toString()}`);
  },
  runComments: (simulationId: string, options: { platform?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    query.set("limit", String(options.limit ?? 30));
    query.set("offset", String(options.offset ?? 0));
    if (options.platform) query.set("platform", options.platform);
    return request<MiroFishContentPage>(`/mirofish/runs/${encodeURIComponent(simulationId)}/comments?${query.toString()}`);
  },
  reportLog: (simulationId: string, kind: "console" | "agent" = "console", fromLine = 0) =>
    request<MiroFishReportLog>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/report/logs?kind=${kind}&from_line=${fromLine}`,
    ),
  graphSearch: (simulationId: string, query: string, limit = 10) =>
    request<MiroFishGraphSearch>(
      `/mirofish/runs/${encodeURIComponent(simulationId)}/graph/search`,
      withBody("POST", { query, limit }),
    ),
  graphStatistics: (simulationId: string) =>
    request<MiroFishGraphStats>(`/mirofish/runs/${encodeURIComponent(simulationId)}/graph/statistics`),
};
