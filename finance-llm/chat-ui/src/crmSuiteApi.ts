/**
 * Cliente da arquitetura de CRM (`/crm/suite`, `/crm/mod/*`, `/crm/rbac/*`, `/crm/ai/*`).
 *
 * Um só cliente serve os 24 módulos do CRM: os campos, os filtros e as ações são
 * descritos pelo servidor (`GET /crm/suite`) e o perfil do utilizador decide o que
 * está visível. Assim o frontend não tem listas duplicadas de módulos nem de campos.
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts` (injeta o token).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type CrmFieldType =
  | "text"
  | "textarea"
  | "email"
  | "phone"
  | "url"
  | "select"
  | "multiselect"
  | "reference"
  | "number"
  | "int"
  | "percent"
  | "bool"
  | "date"
  | "datetime"
  | "json";

export type CrmFieldOption = { value: string; label: string };

export type CrmFieldMeta = {
  key: string;
  label: string;
  type: CrmFieldType;
  options: CrmFieldOption[];
  required: boolean;
  reference: string | null;
  column: boolean;
  width: number;
  help: string;
  filter: boolean;
  system: boolean;
  computed: boolean;
};

export type CrmModulePermissions = {
  read: boolean;
  create: boolean;
  update: boolean;
  delete: boolean;
  export: boolean;
  manage: boolean;
};

export type CrmModuleMeta = {
  slug: string;
  kind: string;
  label: string;
  singular: string;
  group: string;
  icon: string;
  description: string;
  fields: CrmFieldMeta[];
  label_fields: string[];
  aliases: string[];
  read_only: boolean;
  admin_only: boolean;
  ai: boolean;
  allowed: boolean;
  permissions: CrmModulePermissions;
};

export type CrmArea = { id: string; label: string; description?: string };
export type CrmDepartment = { id: string; label: string; area?: string };
export type CrmAction = { id: string; label: string };
export type CrmScope = { id: string; label: string };
export type CrmRole = {
  key: string;
  label: string;
  area: string;
  department: string;
  scope: string;
  rank: number;
  modules: string[];
  actions: string[];
  builtin?: boolean;
  description?: string;
};

export type CrmPermissions = {
  user_id: string;
  email: string;
  name: string;
  role: string;
  role_label: string;
  area: string;
  department: string;
  team_id: string;
  team: string;
  job_title: string;
  quota: number | null;
  status: string;
  scope: string;
  modules: string[];
  actions: string[];
  is_admin: boolean;
  see_all: boolean;
  admin_only_modules: string[];
};

export type CrmSuiteGroup = { id: string; label: string; icon: string; description: string };

export type CrmSuiteMeta = {
  groups: CrmSuiteGroup[];
  modules: CrmModuleMeta[];
  areas: CrmArea[];
  departments: CrmDepartment[];
  roles: CrmRole[];
  actions: CrmAction[];
  scopes: CrmScope[];
  me: CrmPermissions;
  visible_modules: string[];
  visible_groups: string[];
  generated_at: string;
};

export type CrmSuiteRecord = Record<string, unknown> & {
  id: string;
  module: string;
  label: string;
  doc_id?: string;
  owner_email?: string;
  updated_at?: string;
};

export type CrmModuleList = {
  module: string;
  kind: string;
  total: number;
  from: number;
  size: number;
  items: CrmSuiteRecord[];
  error?: string;
};

export type CrmStatBucket = { key: string; label: string; count: number };
export type CrmStatMetric = {
  field: string;
  label: string;
  count: number;
  sum: number;
  avg: number;
  min: number;
  max: number;
};
export type CrmModuleStats = {
  module: string;
  label: string;
  total: number;
  groups: { field: string; label: string; buckets: CrmStatBucket[] }[];
  metrics: CrmStatMetric[];
  timeline: { month: string; count: number }[];
  error?: string;
};

export type CrmRbacMatrixEntry = {
  module: string;
  label: string;
  group: string;
  admin_only: boolean;
  read_only: boolean;
  roles: Record<string, { scope: string | null; actions: string[]; allowed: boolean }>;
};

export type CrmRbacMeta = {
  areas: CrmArea[];
  departments: CrmDepartment[];
  roles: CrmRole[];
  role_index: Record<string, CrmRole>;
  actions: CrmAction[];
  scopes: CrmScope[];
  modules: CrmModuleMeta[];
  matrix: CrmRbacMatrixEntry[];
  members: CrmSuiteRecord[];
  members_total: number;
  teams: CrmSuiteRecord[];
};

export type CrmSuiteOverview = {
  generated_at: string;
  scope: string;
  counts: Record<string, number>;
  pipeline: { open_count: number; open_value: number; stats: CrmModuleStats | Record<string, never> };
  cases: CrmModuleStats | Record<string, never>;
  campaigns: CrmModuleStats | Record<string, never>;
  insights: CrmSuiteRecord[];
  audit: CrmSuiteRecord[];
  error?: string;
};

export type CrmAiAnswer = {
  ok: boolean;
  answer: string;
  intent: string;
  provider: string;
  model: string;
  status: string;
  latency_ms: number;
  facts: Record<string, unknown>;
  interaction?: CrmSuiteRecord;
};

/* ---------------------------------------------------------------- analytics */

export type CrmMoneyBlock = {
  realizada: number;
  faturada: number;
  em_aberto: number;
  encomendas: number;
  encomendas_em_aberto: number;
  ticket_medio: number;
  margem: number;
  margem_pct: number;
  variacao_periodo_pct: number | null;
};

export type CrmRevenueRow = {
  account_id?: string;
  product_id?: string;
  owner?: string;
  month?: string;
  name?: string;
  category?: string;
  revenue: number;
  orders?: number;
  units?: number;
  margin?: number;
  margin_pct?: number;
  ticket_medio?: number;
};

export type CrmCustomerRow = {
  account_id: string;
  name: string;
  status?: string;
  clv: number;
  orders: number;
  ticket_medio: number;
  frequencia_anual: number;
  ultima_encomenda: string;
  dias_sem_compra: number | null;
  produtos: { product_id: string; name: string; units: number; revenue: number }[];
  produtos_total: number;
  receita_periodo: number;
  variacao_pct: number | null;
  estado: string;
};

export type CrmAnalytics = {
  gerado_em: string;
  filtros: { meses: number; top: number; dias_sem_compra: number };
  fontes: Record<string, number>;
  acesso: Record<string, boolean>;
  vendas?: {
    filtros: Record<string, unknown>;
    receita: CrmMoneyBlock;
    por_cliente: CrmRevenueRow[];
    por_produto: CrmRevenueRow[];
    por_vendedor: CrmRevenueRow[];
    por_periodo: CrmRevenueRow[];
    mais_vendidos: CrmRevenueRow[];
  };
  clientes?: {
    resumo: Record<string, number>;
    top_clv: CrmCustomerRow[];
    sem_compra: CrmCustomerRow[];
    a_crescer: CrmCustomerRow[];
    a_encolher: CrmCustomerRow[];
    nunca_compraram: CrmCustomerRow[];
    dias_sem_compra: number;
  };
  operacoes?: {
    encomendas: {
      total: number;
      pendentes: number;
      valor_pendente: number;
      atrasadas: number;
      por_estado: { key: string; count: number; value: number }[];
      exemplos_atrasadas: Record<string, unknown>[];
    };
    ordens: {
      total: number;
      abertas: number;
      concluidas: number;
      atrasadas: number;
      taxa_conclusao_pct: number;
      tempo_medio_horas: number;
      horas_totais: number;
      sla: { cumprido: number; em_risco: number; incumprido: number; cumprimento_pct: number };
      custo: number;
      valor_faturavel: number;
      margem_servico: number;
      exemplos_atrasadas: Record<string, unknown>[];
    };
    capacidade: { team_id: string; label: string; abertas: number; concluidas: number; horas: number; tecnicos: number }[];
    por_tipo: { key: string; count: number; abertas: number; horas: number; custo: number }[];
  };
  fornecedores?: {
    total: number;
    por_estado: { key: string; count: number }[];
    por_tipo: { key: string; count: number }[];
    custo_aquisicao: number;
    receita_atribuida: number;
    margem_bruta: number;
    prazos: {
      lead_time_medio_dias: number | null;
      pontualidade_media_pct: number | null;
      qualidade_media: number | null;
      cumprimento_prazos_medio: number | null;
    };
    compras: {
      supplier_id: string;
      name: string;
      lines: number;
      units: number;
      cost: number;
      revenue: number;
      margin: number;
      margin_pct: number;
    }[];
    sem_linhas_atribuidas: number;
    risco: {
      supplier_id: string;
      name: string;
      criticality: string;
      status: string;
      on_time_pct: number | null;
      lead_time_days: number | null;
      motivo: string;
    }[];
    criticos: number;
  };
  error?: string;
};

export type CrmCrossSellFilters = {
  compraram: string;
  nao_tem: string;
  min_spend: number | null;
  meses: number;
};

export type CrmCrossSellRow = {
  account_id: string;
  name: string;
  revenue: number;
  orders: number;
  ultima_encomenda: string;
  produtos: number;
  comprados: { product_id: string; name: string; revenue: number }[];
  falta: string;
};

export type CrmCrossSellResult = {
  filtros: CrmCrossSellFilters;
  catalogo: number;
  total: number;
  valor_potencial: number;
  accounts: CrmCrossSellRow[];
};

export type CrmOpportunityAction = {
  ok: boolean;
  dry_run: boolean;
  criadas: { account_id: string; name?: string; title: string; amount: number; opportunity_id?: string }[];
  ignoradas: { account_id: string; name?: string; motivo: string }[];
  total_criadas: number;
  valor_total: number;
  title?: string;
  publico?: CrmCrossSellResult;
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

function withBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function queryString(params: Record<string, string | number | boolean | undefined | null>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === null) continue;
    query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

/* ------------------------------------------------------------------- rotas */

export function getCrmSuite(): Promise<CrmSuiteMeta> {
  return request<CrmSuiteMeta>("/crm/suite");
}

/* ------------------------------------------------------------------- cache */

let suiteCache: CrmSuiteMeta | null = null;
let suiteInFlight: Promise<CrmSuiteMeta> | null = null;

/** Estrutura já carregada (ou `null`). */
export function peekCrmSuite(): CrmSuiteMeta | null {
  return suiteCache;
}

/**
 * Estrutura do CRM com cache: a mesma promessa serve todas as janelas do módulo,
 * para não repetir o pedido a cada painel aberto.
 */
export function loadCrmSuite(force = false): Promise<CrmSuiteMeta> {
  if (!force && suiteCache) return Promise.resolve(suiteCache);
  if (!force && suiteInFlight) return suiteInFlight;
  suiteInFlight = getCrmSuite()
    .then((meta) => {
      suiteCache = meta;
      suiteInFlight = null;
      return meta;
    })
    .catch((error: unknown) => {
      suiteInFlight = null;
      throw error;
    });
  return suiteInFlight;
}

export function getCrmSuiteOverview(): Promise<CrmSuiteOverview> {
  return request<CrmSuiteOverview>("/crm/suite/overview");
}

export function getCrmMe(): Promise<{ assignment: Record<string, unknown>; permissions: CrmPermissions; modules: string[] }> {
  return request("/crm/me");
}

export function getCrmRbac(): Promise<CrmRbacMeta> {
  return request<CrmRbacMeta>("/crm/rbac");
}

export function syncCrmMembers(): Promise<{ ok: boolean; created: number }> {
  return request("/crm/rbac/sync", { method: "POST" });
}

export function listCrmModule(
  slug: string,
  params: {
    q?: string;
    size?: number;
    from?: number;
    sort_by?: string;
    sort_order?: "asc" | "desc";
    [filter: string]: string | number | undefined;
  } = {},
): Promise<CrmModuleList> {
  return request<CrmModuleList>(`/crm/mod/${encodeURIComponent(slug)}${queryString(params)}`);
}

export function getCrmModuleRecord(slug: string, id: string): Promise<{ item: CrmSuiteRecord }> {
  return request(`/crm/mod/${encodeURIComponent(slug)}/${encodeURIComponent(id)}`);
}

export function createCrmModuleRecord<T = CrmSuiteRecord>(slug: string, body: Record<string, unknown>) {
  return request<{ ok: boolean; item: T }>(`/crm/mod/${encodeURIComponent(slug)}`, withBody("POST", body));
}

export function updateCrmModuleRecord<T = CrmSuiteRecord>(slug: string, id: string, body: Record<string, unknown>) {
  return request<{ ok: boolean; item: T }>(
    `/crm/mod/${encodeURIComponent(slug)}/${encodeURIComponent(id)}`,
    withBody("PATCH", body),
  );
}

export function deleteCrmModuleRecord(slug: string, id: string) {
  return request<{ ok: boolean; deleted: number; cascaded?: number; reset?: boolean }>(
    `/crm/mod/${encodeURIComponent(slug)}/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export function getCrmModuleStats(slug: string): Promise<CrmModuleStats> {
  return request<CrmModuleStats>(`/crm/mod/${encodeURIComponent(slug)}/stats`);
}

export function getCrmModuleReferences(
  slug: string,
  size = 300,
): Promise<{ module: string; references: Record<string, Record<string, string>> }> {
  return request(`/crm/mod/${encodeURIComponent(slug)}/references${queryString({ size })}`);
}

export function updateCrmAssignment(userId: string, body: Record<string, unknown>) {
  return request<{ ok: boolean; item: CrmSuiteRecord }>(
    `/crm/mod/users/${encodeURIComponent(userId)}`,
    withBody("PATCH", body),
  );
}

export function generateCrmInsights(): Promise<{
  ok: boolean;
  created: number;
  updated: number;
  preserved: number;
  total: number;
}> {
  return request("/crm/ai/insights/generate", { method: "POST" });
}

export function getCrmAnalytics(params: { months?: number; top?: number; days_without_purchase?: number } = {}) {
  return request<CrmAnalytics>(`/crm/analytics${queryString(params)}`);
}

export function runCrmCrossSell(body: {
  have_product?: string;
  missing_product?: string;
  min_spend?: number;
  months?: number;
  limit?: number;
  exclude_with_open_opportunity?: boolean;
}) {
  return request<CrmCrossSellResult>("/crm/analytics/cross-sell", withBody("POST", body));
}

export function createCrmCrossSellOpportunities(body: {
  have_product?: string;
  missing_product?: string;
  min_spend?: number;
  months?: number;
  limit?: number;
  title?: string;
  amount?: number;
  amount_from?: "revenue_pct" | "revenue" | "fixed";
  stage?: string;
  expected_days?: number;
  dry_run?: boolean;
}) {
  return request<CrmOpportunityAction>("/crm/analytics/opportunities", withBody("POST", body));
}

export function askCrmAi(
  question: string,
  options: { module?: string; record_id?: string; backend?: string } = {},
): Promise<CrmAiAnswer> {
  return request<CrmAiAnswer>("/crm/ai/ask", withBody("POST", { question, ...options }));
}

/* --------------------------------------------------------------- formatação */

export function formatFieldValue(field: CrmFieldMeta, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  switch (field.type) {
    case "bool":
      return value ? "Sim" : "Não";
    case "select": {
      const option = field.options.find((item) => item.value === String(value));
      return option?.label ?? String(value);
    }
    case "multiselect":
      return Array.isArray(value) ? value.join(", ") : String(value);
    case "number":
      return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 }).format(Number(value));
    case "percent":
      return `${new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 1 }).format(Number(value))} %`;
    case "int":
      return new Intl.NumberFormat("pt-PT").format(Number(value));
    case "date":
      return String(value).slice(0, 10);
    case "datetime": {
      const text = String(value);
      return text.length > 10 ? `${text.slice(0, 10)} ${text.slice(11, 16)}` : text;
    }
    case "json":
      return Array.isArray(value) ? `${value.length} linha(s)` : "JSON";
    default:
      return String(value);
  }
}
