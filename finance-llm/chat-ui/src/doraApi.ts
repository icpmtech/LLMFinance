/**
 * Cliente da API do módulo **DORA** — `/dora/*`.
 *
 * Digital Operational Resilience Act: Register of Information, incidentes ICT,
 * riscos ICT, workflows de conformidade, relatórios ITS/RTS e conteúdo
 * original/traduzido da EIOPA.
 */
import { API_BASE } from "./api";

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(data?.detail || `Erro ${res.status} em ${path}`);
  }
  return data as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(data?.detail || `Erro ${res.status} em ${path}`);
  }
  return data as T;
}

export type DoraPilar = {
  id: string;
  titulo: string;
  descricao: string;
};

export type DoraProvisao = {
  titulo: string;
  url: string;
  descricao?: string;
};

export type DoraProvisoesLegais = {
  nivel_1: DoraProvisao[];
  nivel_2: DoraProvisao[];
  nivel_3: DoraProvisao[];
};

export type DoraConteudoIdioma = {
  introducao: string;
  porque: string;
  oversight: string;
  pilares: DoraPilar[];
  provisoes_legais: DoraProvisoesLegais;
};

export type DoraConteudo = {
  titulo: string;
  fonte: string;
  url: string;
  data_extracao: string;
  original: DoraConteudoIdioma;
  pt: DoraConteudoIdioma;
};

export type DoraStatus = {
  indices: Record<string, { count?: number }>;
};

export type DoraMeta = {
  conteudo: DoraConteudo;
  status: DoraStatus;
  modulo: string;
  versao: string;
};

export type DoraSearchResult<T> = {
  total: number;
  items: T[];
};

export type DoraRegistoItem = {
  id?: string;
  tipo: "entidade" | "funcao" | "sistema" | "fornecedor" | "contrato" | "outro";
  nome: string;
  descricao?: string;
  entidade_id?: string;
  entidade_nome?: string;
  fornecedor_ids?: string[];
  sistema_ids?: string[];
  funcao_ids?: string[];
  contrato_ids?: string[];
  tags?: string[];
  dados?: Record<string, unknown>;
};

export type DoraIncidente = {
  id?: string;
  titulo: string;
  descricao?: string;
  referencia?: string;
  severidade: "critico" | "alto" | "medio" | "baixo" | "informacao";
  estado: "aberto" | "em_analise" | "contido" | "resolvido" | "fechado";
  entidade_id?: string;
  entidade_nome?: string;
  sistema?: string;
  data_inicio?: string;
  data_fim?: string;
  impacto_financeiro?: number;
  dados?: Record<string, unknown>;
};

export type DoraRisco = {
  id?: string;
  nome: string;
  descricao?: string;
  categoria?: string;
  impacto: "critico" | "alto" | "medio" | "baixo";
  probabilidade: "quase_certo" | "provavel" | "possivel" | "improvavel" | "raro";
  ativo?: string;
  entidade_id?: string;
  entidade_nome?: string;
  mitigacao?: string;
  dados?: Record<string, unknown>;
};

export type DoraWorkflow = {
  id?: string;
  nome: string;
  descricao?: string;
  ativo?: boolean;
  trigger?: string;
  acao?: string;
  passos?: Record<string, unknown>[];
  entidade_id?: string;
};

export type DoraRelatorio = {
  id: string;
  tipo: string;
  nome: string;
  entidade_id: string;
  resumo: Record<string, unknown>;
  dados: Record<string, unknown>;
  formato: string;
  created_at: string;
  updated_at: string;
};

export type DoraRelatorioPayload = {
  tipo: "register-of-information" | "incidents" | "risk" | "third-party" | "tls" | "oversight" | "combined";
  entidade_id: string;
  nome?: string;
  formato?: "json" | "csv" | "pdf" | "xlsx";
  dados?: Record<string, unknown>;
};

export async function getDoraMeta(): Promise<DoraMeta> {
  return getJson<DoraMeta>("/dora/meta");
}

export async function searchDoraConteudo(params: { q: string; idioma?: "pt" | "en"; size?: number; from?: number }) {
  return getJson<DoraSearchResult<Record<string, unknown>>>(`/dora/conteudo${query(params)}`);
}

export async function ingestDoraConteudo() {
  return postJson<{ indexados: number; ok: boolean }>("/dora/conteudo/ingestao", {});
}

export async function searchDoraRegisto(params: {
  q?: string;
  tipo?: DoraRegistoItem["tipo"];
  entidade_id?: string;
  size?: number;
  from?: number;
}) {
  return getJson<DoraSearchResult<DoraRegistoItem>>(`/dora/registo${query(params)}`);
}

export async function getDoraRegistoItem(tipo: string, itemId: string) {
  return getJson<DoraRegistoItem>(`/dora/registo/${tipo}/${itemId}`);
}

export async function getDoraRegistoRelacoes(tipo: string, itemId: string) {
  return getJson<DoraSearchResult<DoraRegistoItem>>(`/dora/registo/${tipo}/${itemId}/relacoes`);
}

export async function saveDoraRegisto(item: DoraRegistoItem) {
  return postJson<{ id: string; tipo: string; ok: boolean }>("/dora/registo", item);
}

export async function searchDoraIncidentes(params: {
  q?: string;
  severidade?: DoraIncidente["severidade"];
  estado?: DoraIncidente["estado"];
  size?: number;
  from?: number;
}) {
  return getJson<DoraSearchResult<DoraIncidente>>(`/dora/incidentes${query(params)}`);
}

export async function getDoraIncidente(id: string) {
  return getJson<DoraIncidente>(`/dora/incidentes/${id}`);
}

export async function saveDoraIncidente(item: DoraIncidente) {
  return postJson<{ id: string; ok: boolean }>("/dora/incidentes", item);
}

export async function searchDoraRiscos(params: {
  q?: string;
  impacto?: DoraRisco["impacto"];
  probabilidade?: DoraRisco["probabilidade"];
  size?: number;
  from?: number;
}) {
  return getJson<DoraSearchResult<DoraRisco>>(`/dora/riscos${query(params)}`);
}

export async function getDoraRisco(id: string) {
  return getJson<DoraRisco>(`/dora/riscos/${id}`);
}

export async function saveDoraRisco(item: DoraRisco) {
  return postJson<{ id: string; ok: boolean }>("/dora/riscos", item);
}

export async function searchDoraWorkflows(params: { q?: string; ativo?: boolean; size?: number; from?: number }) {
  return getJson<DoraSearchResult<DoraWorkflow>>(`/dora/workflows${query(params)}`);
}

export async function getDoraWorkflow(id: string) {
  return getJson<DoraWorkflow>(`/dora/workflows/${id}`);
}

export async function saveDoraWorkflow(item: DoraWorkflow) {
  return postJson<{ id: string; ok: boolean }>("/dora/workflows", item);
}

export async function searchDoraRelatorios(params: { q?: string; tipo?: DoraRelatorioPayload["tipo"]; size?: number; from?: number }) {
  return getJson<DoraSearchResult<DoraRelatorio>>(`/dora/relatorios${query(params)}`);
}

export async function getDoraRelatorio(id: string) {
  return getJson<DoraRelatorio>(`/dora/relatorios/${id}`);
}

export async function generateDoraRelatorio(payload: DoraRelatorioPayload) {
  return postJson<{ id: string; ok: boolean; relatorio: DoraRelatorio }>("/dora/relatorios", payload);
}
