/**
 * Cliente do módulo de CRM (`/crm/*`).
 *
 * Um CRM comercial assente nos dados do IQ OS: contas (empresas, ligáveis ao
 * cadastro do EmpresasIQ pelo NIF), contactos, oportunidades (pipeline) e
 * atividades/compromissos. Os dados vivem no Elasticsearch (`finance_crm`) e
 * cada utilizador vê os seus registos; os administradores veem os da equipa.
 *
 * Todas as chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o
 * token da sessão.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type CrmKind = "accounts" | "contacts" | "deals" | "activities";

export type CrmAccountStatus = "prospect" | "cliente" | "inativo";
export type CrmDealStage =
  | "prospeccao"
  | "qualificacao"
  | "proposta"
  | "negociacao"
  | "ganho"
  | "perdido";
export type CrmActivityType = "chamada" | "reuniao" | "email" | "tarefa" | "nota";
export type CrmPriority = "baixa" | "media" | "alta";

export type CrmEntitySnapshot = {
  nif?: string;
  name?: string;
  country?: string;
  contracts_count?: number;
  as_adjudicante_count?: number;
  as_adjudicatario_count?: number;
  total_value?: number;
  as_adjudicante_value?: number;
  synced_at?: string;
};

export type CrmBaseRecord = {
  id: string;
  doc_id?: string;
  owner_id?: string;
  owner_email?: string;
  created_at?: string;
  updated_at?: string;
  tags?: string[];
};

export type CrmAccount = CrmBaseRecord & {
  name: string;
  nif?: string;
  sector?: string;
  status?: CrmAccountStatus;
  website?: string;
  email?: string;
  phone?: string;
  mobile?: string;
  address?: string;
  city?: string;
  country?: string;
  postal_code?: string;
  employees?: number | null;
  annual_revenue?: number | null;
  notes?: string;
  entity?: CrmEntitySnapshot | null;
};

export type CrmContact = CrmBaseRecord & {
  account_id?: string;
  name: string;
  title?: string;
  role?: string;
  email?: string;
  phone?: string;
  mobile?: string;
  linkedin?: string;
  is_primary?: boolean;
  notes?: string;
};

export type CrmDeal = CrmBaseRecord & {
  account_id?: string;
  contact_id?: string;
  title: string;
  amount?: number | null;
  weighted_amount?: number;
  currency?: string;
  stage: CrmDealStage;
  probability?: number;
  expected_close_date?: string;
  closed_at?: string | null;
  loss_reason?: string;
  source?: string;
  notes?: string;
};

export type CrmActivity = CrmBaseRecord & {
  account_id?: string;
  contact_id?: string;
  deal_id?: string;
  type: CrmActivityType;
  subject: string;
  notes?: string;
  due_at?: string;
  done?: boolean;
  done_at?: string | null;
  priority?: CrmPriority;
};

export type CrmRecord = CrmAccount | CrmContact | CrmDeal | CrmActivity;

export type CrmListResponse<T> = {
  kind?: string;
  total: number;
  from: number;
  size: number;
  items: T[];
  error?: string;
};

export type CrmMeta = {
  kinds: string[];
  account_statuses: CrmAccountStatus[];
  deal_stages: CrmDealStage[];
  open_stages: CrmDealStage[];
  closed_stages: CrmDealStage[];
  activity_types: CrmActivityType[];
  priorities: CrmPriority[];
  default_currency: string;
  scope: "own" | "all";
};

export type CrmOverview = {
  generated_at: string;
  totals: {
    accounts: number;
    contacts: number;
    deals_open: number;
    deals_won: number;
    deals_lost: number;
    activities_open: number;
  };
  pipeline: {
    open_value: number;
    weighted_value: number;
    average_deal: number;
    win_rate: number;
    won_value_12m: number;
  };
  by_stage: { stage: CrmDealStage; count: number; value: number; weighted: number }[];
  forecast: { month: string; count: number; value: number; weighted: number }[];
  top_accounts: { account_id: string; name: string; count: number; value: number }[];
  agenda: {
    overdue: CrmActivity[];
    overdue_count: number;
    next_7_days: CrmActivity[];
    next_7_days_count: number;
    upcoming: CrmActivity[];
  };
  recent_activity: CrmRecord[];
};

export type CrmAccountTimeline = {
  account: CrmAccount;
  contacts: CrmContact[];
  deals: CrmDeal[];
  activities: CrmActivity[];
};

export type CrmEntityCandidate = {
  nif?: string;
  name: string;
  country?: string;
  contracts_count?: number;
  total_value?: number;
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

function queryString(params: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === null) continue;
    query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

/* ------------------------------------------------------------------- rotas */

export function getCrmMeta(): Promise<CrmMeta> {
  return request<CrmMeta>("/crm/meta");
}

export function getCrmOverview(months = 6): Promise<CrmOverview> {
  return request<CrmOverview>(`/crm/overview?months=${months}`);
}

export function listCrmAccounts(
  params: { q?: string; status?: string; sector?: string; country?: string; tag?: string; size?: number } = {},
): Promise<CrmListResponse<CrmAccount>> {
  return request(`/crm/accounts${queryString({ ...params, size: params.size ?? 300 })}`);
}

export function listCrmContacts(
  params: { q?: string; account_id?: string; tag?: string; size?: number } = {},
): Promise<CrmListResponse<CrmContact>> {
  return request(`/crm/contacts${queryString({ ...params, size: params.size ?? 300 })}`);
}

export function listCrmDeals(
  params: { q?: string; stage?: string; account_id?: string; contact_id?: string; size?: number } = {},
): Promise<CrmListResponse<CrmDeal>> {
  return request(`/crm/deals${queryString({ ...params, size: params.size ?? 500 })}`);
}

export function listCrmActivities(
  params: {
    q?: string;
    account_id?: string;
    deal_id?: string;
    contact_id?: string;
    type?: string;
    done?: boolean;
    priority?: string;
    size?: number;
  } = {},
): Promise<CrmListResponse<CrmActivity>> {
  return request(`/crm/activities${queryString({ ...params, size: params.size ?? 500 })}`);
}

export function createCrmRecord<T extends CrmRecord>(kind: CrmKind, body: Record<string, unknown>) {
  return request<{ ok: boolean; item: T }>(`/crm/${kind}`, withBody("POST", body));
}

export function updateCrmRecord<T extends CrmRecord>(kind: CrmKind, id: string, body: Record<string, unknown>) {
  return request<{ ok: boolean; item: T }>(`/crm/${kind}/${encodeURIComponent(id)}`, withBody("PATCH", body));
}

export function deleteCrmRecord(kind: CrmKind, id: string) {
  return request<{ ok: boolean; deleted: number; cascaded?: number }>(
    `/crm/${kind}/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export function getCrmAccountTimeline(accountId: string): Promise<CrmAccountTimeline> {
  return request<CrmAccountTimeline>(`/crm/accounts/${encodeURIComponent(accountId)}/timeline`);
}

export function createCrmAccountFromEntity(
  nif: string,
  extra: Record<string, unknown> = {},
): Promise<{ ok: boolean; created: boolean; item: CrmAccount }> {
  return request(`/crm/accounts/from-entity`, withBody("POST", { nif, ...extra }));
}

export function syncCrmAccountEntity(accountId: string): Promise<{ ok: boolean; item: CrmAccount }> {
  return request(`/crm/accounts/${encodeURIComponent(accountId)}/sync-entity`, { method: "POST" });
}

export function searchCrmEntities(q: string, size = 10): Promise<{ items: CrmEntityCandidate[] }> {
  return request(`/crm/entities/search${queryString({ q, size })}`);
}
