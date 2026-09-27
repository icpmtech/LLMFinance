/**
 * Cliente do módulo «Citação e Notificação Edital» (`/citacoes/*`).
 *
 * Fonte: portal do CITIUS (Ministério da Justiça) → *Citação e Notificação
 * Edital*: as citações/notificações publicadas por édito quando o citando não é
 * encontrado, com tribunal, ato, referência, processo, espécie, data,
 * intervenientes (exequente, executado, réu, requerido, …) e o documento em PDF.
 *
 * O módulo recolhe a lista de resultados da pesquisa (**pelo nome do
 * interveniente**), grava-a em **JSON** (`data/citacoes/runs`) e só depois a
 * importa para o Elasticsearch (`finance_citacoes_edital`), onde é pesquisável.
 *
 * As chamadas usam o `fetch` instrumentado em `authApi.ts`, que injeta o token
 * da sessão (necessário para recolher, importar e apagar recolhas).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Interveniente de um édito (exequente, executado, réu, credor, …). */
export type CitacoesInterveniente = {
  papel: string;
  nome: string;
  nif?: string | null;
};

/** Édito de citação/notificação (um documento do índice). */
export type CitacoesEdito = {
  pub_id: string;
  doc_id?: string;
  referencia: string;
  data_publicacao?: string | null;
  tribunal?: string | null;
  tribunal_comarca?: string | null;
  tribunal_sede?: string | null;
  /** Comarca judicial («… da Comarca de Santarém» → «Santarém»). */
  comarca_judicial?: string | null;
  ato?: string | null;
  tipo?: string | null;
  processo?: string | null;
  processo_numero?: string | null;
  juizo?: string | null;
  especie?: string | null;
  citado?: string | null;
  papeis?: string[];
  intervenientes?: CitacoesInterveniente[];
  has_documento?: boolean;
  documento_url?: string | null;
  /** Texto integral extraído do PDF (só quando pedido, ou na extração). */
  texto?: string | null;
  has_texto?: boolean;
  /** Análise do PDF: título, modelo, valor da execução, prazo e NIF. */
  documento_titulo?: string | null;
  documento_assunto?: string | null;
  documento_modelo?: string | null;
  documento_codigo?: string | null;
  documento_referencia_interna?: string | null;
  documento_valor?: number | null;
  documento_prazo?: string | null;
  documento_nifs?: string[];
  documento_partes?: { nome: string; nif?: string | null }[];
  documento_paginas?: number | null;
  documento_caracteres?: number | null;
  documento_bytes?: number | null;
  documento_erro?: string | null;
  documento_extraido_em?: string | null;
  run_id?: string;
  ingested_at?: string;
  extra?: Record<string, unknown>;
};

export type CitacoesFacet = { key: string; count: number };

export type CitacoesSearchResult = {
  query?: string | null;
  total: number;
  items: CitacoesEdito[];
  from?: number;
  size?: number;
  /** Éditos do resultado com o texto do PDF já extraído. */
  with_texto?: number;
  /** Soma e média do valor das execuções (do que foi analisado dos PDF). */
  valor_total?: number;
  valor_medio?: number | null;
  error?: string;
  facets?: {
    tipo?: CitacoesFacet[];
    tribunal_comarca?: CitacoesFacet[];
    comarca_judicial?: CitacoesFacet[];
    tribunal?: CitacoesFacet[];
    ato?: CitacoesFacet[];
    especie?: CitacoesFacet[];
    papel?: CitacoesFacet[];
    modelo?: CitacoesFacet[];
    assunto?: CitacoesFacet[];
    ano?: CitacoesFacet[];
    mes?: CitacoesFacet[];
  };
};

export type CitacoesStatus = {
  index?: string;
  documents?: number;
  referencias?: number;
  processos?: number;
  tribunais?: number;
  citados?: number;
  /** NIF/NIPC distintos vistos no documento analisado. */
  nifs?: number;
  min_date?: string | null;
  max_date?: string | null;
  with_documento?: number;
  with_texto?: number;
  with_valor?: number;
  valor_total?: number;
  valor_medio?: number | null;
  valor_maximo?: number | null;
  by_tipo?: CitacoesFacet[];
  by_ano?: CitacoesFacet[];
  by_mes?: CitacoesFacet[];
  by_papel?: CitacoesFacet[];
  top_comarcas?: CitacoesFacet[];
  top_comarcas_judiciais?: CitacoesFacet[];
  top_tribunais?: CitacoesFacet[];
  top_actos?: CitacoesFacet[];
  top_modelos?: CitacoesFacet[];
  top_assuntos?: CitacoesFacet[];
  error?: string;
};

export type CitacoesMeta = {
  module: string;
  source: string;
  source_label: string;
  source_url: string;
  index: string;
  storage: string;
  page_size: number;
  captcha_required: boolean;
  nome_required: boolean;
  /** Meses recolhidos por omissão («últimos 6 meses»). */
  default_months: number;
  max_months: number;
  min_request_interval: number;
  /** Extração do texto dos PDF durante a recolha. */
  extrair_documentos?: boolean;
  /** Documentos analisados por omissão numa recolha (0 = todos). */
  max_documentos?: number;
  max_text_chars?: number;
  dias: { value: string; label: string }[];
  notes?: string;
  notas?: string;
};

export type CitacoesOptions = {
  tribunais: { value: string; label: string }[];
  dias: { value: string; label: string }[];
  error?: string;
};

/** Critérios da recolha (os campos do formulário do portal). */
export type CitacoesCollectCriteria = {
  nome: string;
  tribunal?: string | null;
  dias?: string | null;
  /** Últimos N meses (0 = tudo). Por omissão, 6. */
  meses?: number | null;
  max_pages?: number;
  max_items?: number | null;
  /** Descarregar e analisar o PDF de cada édito (texto, valor, NIF). */
  extrair_documentos?: boolean;
  /** Documentos a extrair por recolha (0 = todos). */
  max_documentos?: number;
  min_interval?: number;
  proxy?: string | null;
  index?: boolean;
};

/** Recolha gravada em disco (`data/citacoes/runs`). */
export type CitacoesRun = {
  run_id: string;
  source?: string;
  criteria?: Record<string, unknown>;
  collected?: number;
  declared_total?: number;
  declared_pages?: number;
  pages?: number;
  page_size?: number;
  /** Éditos anteriores ao corte de meses que foram descartados. */
  older_than_cutoff?: number;
  /** Documentos (PDF) extraídos e falhados nesta operação. */
  documentos_extraidos?: number;
  documentos_falhados?: number;
  documentos_caracteres?: number;
  duration_s?: number;
  created_at?: string;
  finished_at?: string;
  indexed?: number;
  indexed_at?: string | null;
  index_count?: number;
  /** Documentos ignorados na importação por já existirem no índice. */
  skipped_existing?: number;
  file?: string;
  meta_file?: string;
  errors?: string[];
  stopped?: boolean;
};

/** Recolha em curso (job em segundo plano). */
export type CitacoesJob = {
  id: string;
  state: "queued" | "running" | "done" | "error" | "stopped" | "empty";
  /** `recolha` (pesquisa no portal) ou `documentos` (extração dos PDF de uma recolha). */
  kind?: string;
  stage?: string;
  criteria?: CitacoesCollectCriteria;
  page?: number | null;
  pages?: number;
  collected?: number;
  declared_total?: number;
  declared_pages?: number;
  older_than_cutoff?: number;
  /** Progresso da extração dos PDF. */
  documento?: number | null;
  documentos?: number | null;
  documento_titulo?: string | null;
  documento_referencia?: string | null;
  documentos_extraidos?: number;
  documentos_falhados?: number;
  documentos_caracteres?: number;
  documentos_pendentes?: number | null;
  duration_s?: number;
  indexed?: number;
  index_total?: number;
  run_id?: string;
  error?: string | null;
  estado_final?: string | null;
  errors?: string[];
  skipped_existing?: number;
  stop_requested?: boolean;
  finished?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type CitacoesIngestResult = {
  run_id?: string;
  received?: number;
  indexed_count?: number;
  total?: number;
  index_total?: number;
  /** Documentos já existentes no índice (não foram reescritos). */
  skipped_existing?: number;
  /** Documentos candidatos a indexação (recebidos - ignorados). */
  candidates?: number;
  error_details?: unknown[];
  error?: string;
};

export type CitacoesSearchParams = {
  q?: string;
  referencia?: string;
  processo?: string;
  tribunal?: string;
  tribunal_comarca?: string;
  comarca_judicial?: string;
  tipo?: string;
  ato?: string;
  especie?: string;
  citado?: string;
  nome?: string;
  papel?: string;
  nif?: string;
  modelo?: string;
  titulo?: string;
  data_from?: string;
  data_to?: string;
  has_documento?: boolean;
  has_texto?: boolean;
  with_texto?: boolean;
  size?: number;
  from?: number;
};

/* ------------------------------------------------------- grafo e mapa --- */

/** Nó do grafo das citações (uma entidade, tribunal, comarca, tipo, modelo, mês…). */
export type CitacoesGraphNode = {
  id: string;
  key: string;
  label: string;
  dimension: string;
  type: string;
  role?: string;
  /** Éditos distintos em que o valor aparece. */
  count: number;
  /** Menções (intervenções) do valor em todos os éditos. */
  mentions: number;
  /** Soma do valor das execuções dos éditos em que aparece. */
  valor: number;
  /** Papéis vistos (quando a dimensão é derivada de intervenientes). */
  keys?: string[];
  nif?: string | null;
};

export type CitacoesGraphEdge = {
  source: string;
  target: string;
  count: number;
  mentions: number;
  valor: number;
};

export type CitacoesGraphMeta = {
  dimension_a: string;
  dimension_b?: string | null;
  metric: string;
  mode?: string;
  complete?: boolean;
  documents_scanned: number;
  documents_matching: number;
  documents_value?: number;
  documents_with_text?: number;
  nodes_total: number;
  edges_total: number;
  kept_nodes: number;
  kept_edges: number;
  omitted_edges: number;
  directed?: boolean;
  generated_at?: string;
  limits?: Record<string, number>;
  notes: string[];
  filters: Record<string, unknown>;
};

export type CitacoesGraphResponse = {
  nodes: CitacoesGraphNode[];
  edges: CitacoesGraphEdge[];
  meta: CitacoesGraphMeta;
  error?: string;
};

export type CitacoesGraphDimensions = {
  dimensions: { key: string; label: string; short: string; type: string }[];
  metrics: { key: string; label: string }[];
  recipes: {
    id: string;
    label: string;
    description: string;
    dimension_a: string;
    dimension_b: string | null;
    metric: "editais" | "mencoes";
    view: string;
    limit: number;
  }[];
  limits: Record<string, number>;
};

export type CitacoesGraphParams = {
  dimension_a: string;
  dimension_b?: string | null;
  metric?: "editais" | "mencoes";
  q?: string;
  tipo?: string;
  comarca_judicial?: string;
  tribunal?: string;
  papel?: string;
  nif?: string;
  modelo?: string;
  data_from?: string;
  data_to?: string;
  has_texto?: boolean;
  min_count?: number;
  limit?: number;
  edge_limit?: number;
  max_docs?: number;
};

/** Ponto do mapa: uma terra/comarca/serviço com éditos. */
export type CitacoesMapPoint = {
  key: string;
  label: string;
  lat: number;
  lon: number;
  precisao?: string;
  nivel?: string;
  count: number;
  valor: number;
  com_texto: number;
  com_documento: number;
  por_tipo?: CitacoesFacet[];
  top_tribunais?: CitacoesFacet[];
  min_date?: string | null;
  max_date?: string | null;
};

export type CitacoesMapResponse = {
  nivel: string;
  nivel_label?: string;
  niveis?: { key: string; label: string; campo: string; hint: string }[];
  points: CitacoesMapPoint[];
  sem_localizacao: CitacoesMapPoint[];
  totals: {
    editais: number;
    locais: number;
    locais_no_mapa: number;
    locais_sem_coordenadas: number;
    valor: number;
    com_texto: number;
    com_documento: number;
    por_tipo: CitacoesFacet[];
    documents_matching: number;
    documents_scanned: number;
  };
  truncated?: boolean;
  generated_at?: string;
  filters?: Record<string, unknown>;
  error?: string;
};

export type CitacoesMapParams = {
  nivel?: "sede" | "comarca" | "tribunal";
  q?: string;
  tipo?: string;
  comarca_judicial?: string;
  tribunal?: string;
  papel?: string;
  nif?: string;
  modelo?: string;
  data_from?: string;
  data_to?: string;
  has_texto?: boolean;
};

/** Texto extraído do PDF de um édito (e o que a análise retirou dele). */
export type CitacoesDocumento = {
  pub_id: string;
  referencia?: string | null;
  titulo?: string | null;
  assunto?: string | null;
  modelo?: string | null;
  valor?: number | null;
  prazo?: string | null;
  nifs?: string[];
  partes?: { nome: string; nif?: string | null }[];
  paginas?: number | null;
  caracteres?: number | null;
  extraido_em?: string | null;
  erro?: string | null;
  texto?: string | null;
  error?: string;
};

export type CitacoesDocumentosResult = {
  run_id?: string;
  alvos?: number;
  pedidos?: number;
  extraidos?: number;
  falhados?: number;
  caracteres?: number;
  por_extrair?: number;
  parado?: boolean;
  indexado?: number;
  index_total?: number;
  mensagem?: string;
  error?: string;
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

/* -------------------------------------------------------------------- API */

export function getCitacoesMeta() {
  return request<CitacoesMeta>("/citacoes/meta");
}

export function getCitacoesOptions(refresh = false) {
  return request<CitacoesOptions>(`/citacoes/options${refresh ? "?refresh=true" : ""}`);
}

export function getCitacoesStatus() {
  return request<CitacoesStatus>("/citacoes/status");
}

/** Pesquisa os éditos já indexados (só devolve o que está no Elasticsearch). */
export function searchCitacoes(params: CitacoesSearchParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<CitacoesSearchResult>(`/citacoes/search${suffix}`);
}

export function listCitacoesRuns(limit = 50) {
  return request<{ items: CitacoesRun[]; total: number; directory: string }>(`/citacoes/runs?limit=${limit}`);
}

export function getCitacoesRun(runId: string, withItems = false) {
  return request<CitacoesRun & { items?: CitacoesEdito[] }>(
    `/citacoes/runs/${encodeURIComponent(runId)}${withItems ? "?with_items=true" : ""}`,
  );
}

export function deleteCitacoesRun(runId: string, dropIndex = false) {
  return request<{ run_id: string; removed: string[]; index?: { deleted?: number; error?: string } }>(
    `/citacoes/runs/${encodeURIComponent(runId)}${dropIndex ? "?drop_index=true" : ""}`,
    { method: "DELETE" },
  );
}

/** Arranca uma recolha em segundo plano (grava JSON e, se `index`, importa). */
export function startCitacoesCollect(criteria: CitacoesCollectCriteria) {
  return request<CitacoesJob>("/citacoes/collect", withBody("POST", criteria));
}

export function listCitacoesJobs() {
  return request<{ jobs: CitacoesJob[] }>("/citacoes/jobs");
}

export function getCitacoesJob(jobId: string) {
  return request<CitacoesJob>(`/citacoes/jobs/${encodeURIComponent(jobId)}`);
}

export function stopCitacoesJob(jobId: string) {
  return request<CitacoesJob>(`/citacoes/jobs/${encodeURIComponent(jobId)}/stop`, withBody("POST", {}));
}

/** Importa para o Elasticsearch uma recolha gravada (por omissão, a mais recente).
 *
 * Os documentos que já existem no índice são ignorados; `update_existing` força
 * a reescrita.
 */
export function ingestCitacoes(
  payload: { run_id?: string; items?: CitacoesEdito[]; save_json?: boolean; update_existing?: boolean } = {},
) {
  return request<CitacoesIngestResult>("/citacoes/ingest", withBody("POST", payload));
}

/** Rótulo legível do tipo de édito. */
export function citacoesTipoLabel(tipo?: string | null): string {
  return tipo || "Édito";
}

/** Dimensões, métricas e receitas disponíveis para o grafo. */
export function getCitacoesGraphDimensions() {
  return request<CitacoesGraphDimensions>("/citacoes/graph/dimensions");
}

/** Constrói o grafo das citações (rede de entidades, tribunais, tipos e tempo). */
export function getCitacoesGraph(params: CitacoesGraphParams) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  return request<CitacoesGraphResponse>(`/citacoes/graph?${query.toString()}`);
}

/** Pontos do mapa OpenStreetMap (por sede do tribunal, comarca ou serviço). */
export function getCitacoesMap(params: CitacoesMapParams = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<CitacoesMapResponse>(`/citacoes/map${suffix}`);
}

/** Texto extraído do PDF de um édito (por `pub_id`). */
export function getCitacoesDocumento(pubId: string) {
  return request<CitacoesDocumento>(`/citacoes/documentos/${encodeURIComponent(pubId)}`);
}

/** Extrai (em segundo plano) o texto dos PDF de uma recolha gravada. */
export function startCitacoesDocumentos(
  runId: string,
  payload: { max_documentos?: number; max_text_chars?: number; force?: boolean; min_interval?: number; index?: boolean } = {},
) {
  return request<CitacoesJob>(
    `/citacoes/runs/${encodeURIComponent(runId)}/documentos`,
    withBody("POST", payload),
  );
}
