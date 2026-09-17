/**
 * Cliente da Ontologia do IQ OS (`/ontology/*`).
 *
 * A ontologia é a camada semântica da plataforma: descreve os tipos de objeto
 * (Empresa, Contrato, CPV, Região, Marca, Firma, Ticker, Cotação, Notícia,
 * Sentimento, Tópico, Conta, Contacto, Oportunidade, Atividade, Pessoa), as
 * ligações entre eles e as ações disponíveis — ligados aos dados reais do
 * Elasticsearch. Serve também para fundamentar e validar as respostas da IA.
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts` (injeta o token).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type OntologyDomain = {
  id: string;
  label: string;
  description: string;
  accent?: string;
  object_types?: number;
};

export type OntologySummary = {
  version: number;
  updated_at: string;
  domains: OntologyDomain[];
  totals: {
    object_types: number;
    link_types: number;
    actions: number;
    custom: number;
    session_required: number;
  };
  graph: OntologyGraph;
  limits: { max_query_size: number; max_links_per_object: number; max_resolve_candidates: number; notes: string[] };
};

export type OntologyProperty = {
  id: string;
  label: string;
  type: "string" | "text" | "keyword" | "number" | "date" | "boolean" | "enum" | "reference";
  field?: string;
  nested?: string;
  unit?: string;
  enum?: string[];
  /** Id de um tipo de objeto cujos objetos fornecem os valores válidos (ex.: `regiao`, `cpv`, `topico`). */
  values_from?: string;
  pk?: boolean;
  searchable?: boolean;
  filterable?: boolean;
  sortable?: boolean;
  description?: string;
};

export type OntologyBinding = {
  kind: "es" | "aggregation" | "derived";
  index?: string;
  id_field?: string;
  nested?: string;
  field?: string;
  search_fields?: string[];
  filter?: Record<string, unknown>;
  default_sort?: { field: string; order: string };
  sources?: string[];
  resolver?: string;
  scoped?: boolean;
  optional_scope?: boolean;
  missing_label?: string;
};

export type OntologyObjectType = {
  id: string;
  label: string;
  plural?: string;
  description?: string;
  domain: string;
  icon?: string;
  primary_key?: string;
  title_field?: string;
  subtitle_fields?: string[];
  resolvable?: boolean;
  requires_session?: boolean;
  builtin?: boolean;
  query_hint?: string;
  binding: OntologyBinding;
  properties: OntologyProperty[];
  link_counts?: { out: number; in: number };
  action_count?: number;
};

export type OntologyObjectTypeSummary = {
  id: string;
  label: string;
  plural?: string;
  description?: string;
  domain: string;
  icon?: string;
  primary_key: string;
  title_field: string;
  source_kind: string;
  sources: string[];
  resolvable: boolean;
  builtin: boolean;
  session_required: boolean;
  properties: number;
  links: { out: number; in: number };
  actions: number;
};

export type OntologyLinkType = {
  id: string;
  label: string;
  description?: string;
  from: string;
  to: string;
  from_label?: string;
  to_label?: string;
  cardinality?: string;
  binding?: Record<string, unknown>;
  reverse?: Record<string, unknown>;
  has_reverse?: boolean;
  builtin?: boolean;
};

export type OntologyTypeLink = {
  id: string;
  direction: "forward" | "reverse";
  label: string;
  description?: string;
  other_type: string;
  other_label: string;
  cardinality?: string;
  available: boolean;
  note?: string | null;
};

export type OntologyAction = {
  id: string;
  label: string;
  description?: string;
  object_type?: string | null;
  kind: "navigate" | "http" | "ontology_links" | "ai" | string;
  method?: string;
  url?: string;
  target?: string;
  link?: string;
  requires_session?: boolean;
  params?: { id: string; from: string; property?: string }[];
};

export type OntologyGraph = {
  nodes: {
    id: string;
    label: string;
    domain: string;
    icon?: string;
    properties: number;
    source_kind: string;
    session_required: boolean;
  }[];
  edges: { id: string; source: string; target: string; label: string; cardinality?: string; reverse: boolean }[];
};

export type OntologyObject = Record<string, unknown> & {
  _id: string;
  _label: string;
  _score?: number | null;
  _count?: number;
  _unresolved?: boolean;
  _note?: string;
};

export type ObjectQueryResult = {
  type: string;
  label: string;
  source_kind: string;
  query: Record<string, unknown>;
  total: number;
  items: OntologyObject[];
  exact: boolean;
  notes: string[];
  error?: string;
};

export type ObjectLinkGroup = {
  id: string;
  direction: "forward" | "reverse";
  label: string;
  other_type: string;
  other_label: string;
  cardinality?: string;
  available: boolean;
  count?: number;
  items: OntologyObject[];
  notes?: string[];
};

export type ObjectLinksResult = {
  type: string;
  id: string;
  found: boolean;
  label?: string;
  links: ObjectLinkGroup[];
};

export type OntologyObjectDetail = {
  type: string;
  label: string;
  id: string;
  found: boolean;
  object: OntologyObject;
  source_document?: Record<string, unknown>;
  links?: ObjectLinksResult;
  available_links?: OntologyTypeLink[];
  actions?: OntologyAction[];
  notes?: string[];
};

export type ResolvedEntity = {
  mention: string;
  type: string;
  type_label: string;
  domain: string;
  object: OntologyObject;
  confidence: number;
  matched_on: string;
};

export type ResolveResult = {
  text: string;
  mentions: string[];
  entities: ResolvedEntity[];
  count: number;
  queries?: number;
  notes: string[];
};

export type OntologyRelation = {
  from: { type: string; id: string; label: string };
  link: string;
  label: string;
  direction: "forward" | "reverse";
  to_type: string;
  to_type_label: string;
  count?: number;
  items: { id: string; label: string }[];
};

export type AiContext = {
  question: string;
  objects: {
    type: string;
    type_label: string;
    domain: string;
    id: string;
    label: string;
    confidence: number;
    matched_on: string;
    mention: string;
    properties: Record<string, unknown>;
  }[];
  relations: OntologyRelation[];
  grounding: string;
  mentions: string[];
  notes: string[];
  suggested_tools: string[];
  elapsed_ms: number;
};

export type ValidationCheck = {
  kind: string;
  value: unknown;
  status: "ok" | "aviso" | "erro";
  message: string;
};

export type ValidationResult = {
  supported: boolean;
  score: number;
  checks: ValidationCheck[];
  objects: { type: string; id: string; label: string; confidence: number }[];
  notes: string[];
  grounding?: string;
};

export type AiAnswer = {
  answer: string;
  context: AiContext;
  validation: ValidationResult;
  generated: boolean;
  notes: string[];
};

export type GeneratedTool = {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
  catalog?: unknown;
};

export type OntologyStatus = {
  elasticsearch: boolean;
  evaluated_at: string;
  sources: { index: string; object_types: string[]; documents: number | null }[];
  notes: string[];
};

export type ActionRequest = {
  action: OntologyAction;
  method: string;
  url: string;
  body: Record<string, unknown> | null;
  values: Record<string, unknown>;
  notes: string[];
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

/* ------------------------------------------------------------------- rotas */

export function getOntologySummary(): Promise<OntologySummary> {
  return request<OntologySummary>("/ontology/summary");
}

export function getOntology(): Promise<{
  version: number;
  updated_at: string;
  domains: OntologyDomain[];
  object_types: OntologyObjectType[];
  link_types: OntologyLinkType[];
  actions: OntologyAction[];
  limits: OntologySummary["limits"];
}> {
  return request("/ontology");
}

export function listObjectTypes(): Promise<{ total: number; items: OntologyObjectTypeSummary[]; domains: OntologyDomain[] }> {
  return request("/ontology/object-types");
}

export function getObjectType(typeId: string): Promise<{
  object_type: OntologyObjectType;
  links: OntologyTypeLink[];
  actions: OntologyAction[];
  source_kind: string;
  session_required: boolean;
}> {
  return request(`/ontology/object-types/${encodeURIComponent(typeId)}`);
}

export function listLinkTypes(): Promise<{ total: number; items: OntologyLinkType[] }> {
  return request("/ontology/link-types");
}

export function listActions(objectType?: string): Promise<{ total: number; items: OntologyAction[] }> {
  const query = objectType ? `?object_type=${encodeURIComponent(objectType)}` : "";
  return request(`/ontology/actions${query}`);
}

export function getOntologyGraph(): Promise<OntologyGraph> {
  return request("/ontology/graph");
}

export function getOntologyStatus(): Promise<OntologyStatus> {
  return request("/ontology/status");
}

export function queryOntologyObjects(
  typeId: string,
  options: { search?: string; filters?: Record<string, unknown>; size?: number; from?: number; sort?: unknown } = {},
): Promise<ObjectQueryResult> {
  return request(
    `/ontology/objects/${encodeURIComponent(typeId)}/query`,
    withBody("POST", {
      search: options.search || null,
      filters: options.filters ?? {},
      size: options.size ?? 20,
      from: options.from ?? 0,
      sort: options.sort ?? null,
    }),
  );
}

export function getOntologyObject(
  typeId: string,
  objectId: string,
  options: { includeSource?: boolean; withLinks?: boolean } = {},
): Promise<OntologyObjectDetail> {
  const params = new URLSearchParams();
  if (options.includeSource) params.set("include_source", "true");
  if (options.withLinks) params.set("with_links", "true");
  const query = params.toString();
  return request(`/ontology/objects/${encodeURIComponent(typeId)}/${encodeURIComponent(objectId)}${query ? `?${query}` : ""}`);
}

export function getOntologyObjectLinks(
  typeId: string,
  objectId: string,
  options: { link?: string; size?: number } = {},
): Promise<ObjectLinksResult> {
  const params = new URLSearchParams();
  if (options.link) params.set("link", options.link);
  if (options.size) params.set("size", String(options.size));
  const query = params.toString();
  return request(
    `/ontology/objects/${encodeURIComponent(typeId)}/${encodeURIComponent(objectId)}/links${query ? `?${query}` : ""}`,
    withBody("POST"),
  );
}

export function resolveOntologyEntities(text: string, limit = 5, types?: string[]): Promise<ResolveResult> {
  return request("/ontology/resolve", withBody("POST", { text, limit, types: types ?? null }));
}

export function buildOntologyContext(question: string, limit = 5, linksPerObject = 3): Promise<AiContext> {
  return request("/ontology/ai/context", withBody("POST", { question, limit, links_per_object: linksPerObject }));
}

export function askOntologyGrounded(question: string): Promise<AiAnswer> {
  return request("/ontology/ai/answer", withBody("POST", { question }));
}

export function validateWithOntology(answer: string, question?: string, context?: AiContext | null): Promise<ValidationResult> {
  return request(
    "/ontology/ai/validate",
    withBody("POST", { answer, question: question ?? null, context: context ?? null }),
  );
}

export function getOntologyTools(includeCrm = false): Promise<{ total: number; items: GeneratedTool[] }> {
  return request(`/ontology/ai/tools${includeCrm ? "?include_crm=true" : ""}`);
}

export function resolveOntologyAction(
  actionId: string,
  options: { type?: string; id?: string; params?: Record<string, unknown> } = {},
): Promise<ActionRequest> {
  return request(
    `/ontology/actions/${encodeURIComponent(actionId)}/resolve`,
    withBody("POST", { type: options.type ?? null, id: options.id ?? null, params: options.params ?? {} }),
  );
}
