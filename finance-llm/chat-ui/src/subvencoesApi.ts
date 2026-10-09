/**
 * Cliente do módulo **Subvenções públicas** (`/subvencoes/*`).
 *
 * A IGF publica, em `.ods`, a listagem anual das subvenções e outros
 * benefícios públicos (Lei n.º 64/2013, de 27/08). Os ficheiros vivem em
 * `data/subvencoes` — um por ano, ou uma subpasta por ano — e o backend:
 *
 * 1. **lê a pasta por ano** (`POST /subvencoes/ler`) para JSONL, em segundo
 *    plano (são ~200 mil linhas por ficheiro);
 * 2. **indexa** os JSONL em `finance_subvencoes` (`POST /subvencoes/indexar`);
 * 3. serve a **pesquisa**, o **painel**, as **fichas** de beneficiário e de
 *    entidade e a **exportação** CSV.
 *
 * O ano de cada registo é o da **listagem** (o ficheiro), não o da decisão: o
 * mesmo apoio aparece em listagens de anos diferentes.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type SubvencoesAno = {
  ano: number | null;
  ficheiros: number;
  bytes: number;
  lidos: number;
  registos: number;
  montante: number;
  pendentes: number;
  ficheiros_disco: {
    rel_path: string;
    bytes: number;
    ano_origem: string;
    modificado_em?: string | null;
  }[];
};

export type SubvencoesMeta = {
  module: string;
  dir: string;
  dir_env: string;
  normalized_dir: string;
  index: string;
  indice: { index?: string; registos?: number; lotes_index?: string; error?: string };
  ficheiros_disco: number;
  anos: SubvencoesAno[];
  lidos: number;
  registos_lidos: number;
  atualizado_em?: string | null;
  colunas: { campo: string; rotulo: string }[];
  tipos_beneficiario: Record<string, string>;
  notes: string;
};

export type SubvencoesFicheiro = {
  rel_path: string;
  path?: string;
  ficheiro: string;
  ano: number | null;
  ano_origem: string;
  bytes: number;
  modificado_em?: string | null;
  sufixo: string;
};

export type SubvencoesLote = {
  lote_id?: string;
  ano: number | null;
  ficheiro?: string;
  rel_path: string;
  folha?: string | null;
  bytes?: number;
  sha256?: string;
  modificado_em?: string | null;
  registos: number;
  ignoradas?: number;
  montante_total: number;
  primeira_decisao?: string | null;
  ultima_decisao?: string | null;
  lido_em?: string | null;
  indexados?: number;
  indexado_em?: string | null;
  jsonl_path?: string;
};

export type SubvencoesLotes = {
  dir: string;
  total: number;
  registos: number;
  montante: number;
  items: SubvencoesLote[];
  por_ano: { ano: number; ficheiros: number; registos: number; montante: number }[];
  atualizado_em?: string | null;
};

/** Uma linha da listagem: quem deu, quem recebeu, quanto e porquê. */
export type Subvencao = {
  doc_id: string;
  ano: number | null;
  linha: number;
  ficheiro: string;
  folha?: string | null;
  nif_entidade?: string | null;
  entidade?: string | null;
  nif_beneficiario?: string | null;
  beneficiario?: string | null;
  beneficiario_tipo?: string | null;
  beneficiario_estrangeiro?: boolean;
  montante?: number | null;
  data_decisao?: string | null;
  ano_decisao?: number | null;
  finalidade?: string | null;
  tipo_ato?: string | null;
  numero_ato?: string | null;
  data_ato?: string | null;
  fundamento_legal?: string | null;
  lido_em?: string | null;
  score?: number | null;
};

export type SubvencoesFacet = { key: string | number | null; count: number; montante?: number; nome?: string | null };

export type SubvencoesSearchParams = {
  q?: string;
  ano?: number;
  ano_decisao?: number;
  nif_entidade?: string;
  nif_beneficiario?: string;
  entidade?: string;
  beneficiario?: string;
  tipo_ato?: string;
  beneficiario_tipo?: string;
  fundamento_legal?: string;
  data_from?: string;
  data_to?: string;
  montante_min?: number;
  montante_max?: number;
  sort?: "relevancia" | "montante" | "data" | "beneficiario" | "entidade" | "ano";
  order?: "asc" | "desc";
  page?: number;
  size?: number;
};

export type SubvencoesSearchResult = {
  total: number;
  page: number;
  size: number;
  pages: number;
  items: Subvencao[];
  facets: {
    ano?: SubvencoesFacet[];
    tipo_ato?: SubvencoesFacet[];
    beneficiario_tipo?: SubvencoesFacet[];
    fundamento_legal?: SubvencoesFacet[];
    top_entidades?: SubvencoesFacet[];
    top_beneficiarios?: SubvencoesFacet[];
  };
  kpis: {
    registos: number;
    montante: number;
    beneficiarios_distintos: number;
    entidades_distintas: number;
    com_montante: number;
    por_mes: { key: string | null; count: number; montante: number }[];
  };
};

export type SubvencoesResumo = {
  por_ano: {
    ano: number | null;
    registos: number;
    montante: number;
    beneficiarios: number;
    entidades: number;
    tipo_ato: { key: string | null; count: number }[];
  }[];
  top_entidades: SubvencoesFacet[];
  top_beneficiarios: SubvencoesFacet[];
  por_tipo_beneficiario: { key: string | null; count: number; label?: string }[];
  por_mes: { key: string | null; count: number; montante: number }[];
  kpis: { registos: number; montante: number; beneficiarios: number; entidades: number };
};

export type SubvencoesFichaBeneficiario = {
  nif: string;
  nome?: string | null;
  tipo?: string | null;
  total: number;
  montante: number;
  montante_indexado?: number;
  por_ano: { ano: number; registos: number; montante: number }[];
  entidades: { nif?: string | null; nome?: string | null; registos: number; montante: number }[];
  items: Subvencao[];
};

export type SubvencoesFichaEntidade = {
  nif: string;
  nome?: string | null;
  total: number;
  montante: number;
  por_ano: { ano: number; registos: number; montante: number }[];
  beneficiarios: { nif?: string | null; nome?: string | null; registos: number; montante: number }[];
  items: Subvencao[];
};

export type SubvencoesJob = {
  job_id: string;
  tipo: "ler" | "indexar";
  status: "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  already_running?: boolean;
  message?: string;
  error?: string | null;
  progress?: {
    phase?: string;
    ficheiros_total?: number;
    ficheiros_done?: number;
    registos?: number;
    current?: string | null;
  };
  result?: {
    lidos_total?: number;
    reutilizados_total?: number;
    registos?: number;
    montante?: number;
    ficheiros?: number;
    indexados?: number;
    lidos?: SubvencoesLote[];
    erros?: { rel_path: string; error: string }[];
    errors?: { rel_path: string; error: string }[];
  } | null;
};

/* -------------------------------------------------------------- utilidades */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = (body && (body.detail || body.error)) || detail;
    } catch {
      /* corpo não-JSON: fica o código */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Euros em pt-PT, sem casas decimais acima de mil. */
export function money(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const casas = Math.abs(valor) >= 1000 ? 0 : 2;
  return new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  }).format(valor);
}

/** Números grandes de forma curta («18,9 mil M€»). */
export function moneyShort(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1e9) return `${(valor / 1e9).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} mil M€`;
  if (abs >= 1e6) return `${(valor / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} M€`;
  if (abs >= 1e3) return `${(valor / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil €`;
  return money(valor);
}

/** Contagem com separador de milhares. */
export function count(valor?: number | null): string {
  return valor === undefined || valor === null ? "—" : valor.toLocaleString("pt-PT");
}

/** Data ISO abreviada (`2025-07-21` → `21/07/2025`). */
export function shortDate(iso?: string | null): string {
  if (!iso) return "—";
  const partes = String(iso).slice(0, 10).split("-");
  if (partes.length !== 3) return String(iso);
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

/** Tamanho de ficheiro legível. */
export function bytes(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const unidades = ["B", "KB", "MB", "GB"];
  let numero = valor;
  let indice = 0;
  while (numero >= 1024 && indice < unidades.length - 1) {
    numero /= 1024;
    indice += 1;
  }
  return `${numero.toLocaleString("pt-PT", { maximumFractionDigits: 1 })} ${unidades[indice]}`;
}

const TIPOS_FALLBACK: Record<string, string> = {
  pessoa_singular: "Pessoa singular",
  pessoa_coletiva: "Pessoa coletiva",
  empresario_individual: "Empresário em nome individual",
  entidade_publica: "Entidade pública",
  outro: "Outro",
};

/** Rótulo do tipo de beneficiário (deduzido do prefixo do NIF). */
export function tipoLabel(tipo?: string | null, mapa?: Record<string, string>): string {
  if (!tipo) return "—";
  return (mapa && mapa[tipo]) || TIPOS_FALLBACK[tipo] || tipo;
}

/** Minuto/ano legível a partir de `2025-07`. */
export function mesLabel(chave?: string | null): string {
  if (!chave) return "—";
  const [ano, mes] = String(chave).split("-");
  const nomes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const indice = Number(mes) - 1;
  return `${nomes[indice] ?? mes} ${String(ano).slice(2)}`;
}

/* ------------------------------------------------------------------- API */

/** Pasta dos dados, ficheiros por ano e volumetria lida/indexada. */
export function getSubvencoesMeta(): Promise<SubvencoesMeta> {
  return request<SubvencoesMeta>("/subvencoes/meta");
}

/** Ficheiros de subvenções encontrados na pasta (com o ano atribuído). */
export function getSubvencoesFicheiros(): Promise<{
  dir: string;
  total: number;
  anos: number[];
  items: SubvencoesFicheiro[];
}> {
  return request("/subvencoes/ficheiros");
}

/** Ficheiros já lidos para JSONL, com totais por lote e por ano. */
export function getSubvencoesLotes(): Promise<SubvencoesLotes> {
  return request<SubvencoesLotes>("/subvencoes/lotes");
}

/** Lê a pasta por ano (segundo plano). */
export function lerSubvencoes(params: { anos?: number[]; forcar?: boolean } = {}): Promise<SubvencoesJob> {
  return post<SubvencoesJob>("/subvencoes/ler", params);
}

/** Indexa os JSONL em `finance_subvencoes` (segundo plano). */
export function indexarSubvencoes(params: { anos?: number[]; forcar?: boolean } = {}): Promise<SubvencoesJob> {
  return post<SubvencoesJob>("/subvencoes/indexar", params);
}

/** Estado dos trabalhos de leitura/indexação. */
export function getSubvencoesJobs(): Promise<{ total: number; items: SubvencoesJob[] }> {
  return request("/subvencoes/jobs");
}

/** Estado de um trabalho. */
export function getSubvencoesJob(jobId: string): Promise<SubvencoesJob> {
  return request<SubvencoesJob>(`/subvencoes/jobs/${jobId}`);
}

/** Painel: totais por ano, top entidades e beneficiários e série mensal. */
export function getSubvencoesResumo(anos?: number[]): Promise<SubvencoesResumo> {
  const query = (anos || []).map((ano) => `ano=${encodeURIComponent(ano)}`).join("&");
  return request<SubvencoesResumo>(`/subvencoes/resumo${query ? `?${query}` : ""}`);
}

/** Pesquisa as subvenções concedidas. */
export function searchSubvencoes(params: SubvencoesSearchParams): Promise<SubvencoesSearchResult> {
  return request<SubvencoesSearchResult>(`/subvencoes/search${queryString({ ...params })}`);
}

/** Amostra dos registos lidos de um ano (funciona sem Elasticsearch). */
export function getSubvencoesAmostra(
  ano: number,
  limite = 25
): Promise<{ ano: number; total: number; lotes: number; items: Subvencao[] }> {
  return request(`/subvencoes/amostra/${ano}?limit_items=${limite}`);
}

/** O que um NIF recebeu, com totais por ano e por entidade. */
export function getSubvencoesBeneficiario(nif: string): Promise<SubvencoesFichaBeneficiario> {
  return request<SubvencoesFichaBeneficiario>(`/subvencoes/beneficiario/${encodeURIComponent(nif)}`);
}

/** O que uma entidade obrigada atribuiu. */
export function getSubvencoesEntidade(nif: string): Promise<SubvencoesFichaEntidade> {
  return request<SubvencoesFichaEntidade>(`/subvencoes/entidade/${encodeURIComponent(nif)}`);
}

/** Descarrega o CSV do resultado atual (o `fetch` leva o token da sessão). */
export async function downloadSubvencoesCsv(params: SubvencoesSearchParams & { maximo?: number }): Promise<void> {
  const res = await fetch(`${API_BASE}/subvencoes/export.csv${queryString({ ...params })}`);
  if (!res.ok) {
    throw new Error(`Exportação falhou (HTTP ${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `subvencoes${params.ano ? `-${params.ano}` : ""}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
