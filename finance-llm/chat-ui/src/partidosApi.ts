/**
 * Cliente do módulo **Partidos políticos e as suas contas** (`/partidos/*`).
 *
 * Duas fontes oficiais, complementares:
 *
 * 1. **Tribunal Constitucional — Financiamento Partidário**: por ano, as contas
 *    anuais de cada partido, as listas de ações e meios de propaganda política,
 *    os relatórios da ECFP, os acórdãos e as decisões (`contas_eleicoes-partidos`);
 * 2. **CNE — Partidos Políticos**: o registo oficial (denominação, sigla, data
 *    de inscrição, inscritos/extintos, sítio, símbolo e descrição).
 *
 * O backend **recolhe** as páginas e os PDF (`POST /partidos/recolher`),
 * **indexa** os JSONL em `finance_partidos` (`POST /partidos/indexar`) e serve o
 * painel, a pesquisa (com o texto dos PDF digitais), as fichas por partido e a
 * ligação às pessoas do PessoasIQ.
 *
 * As contas anuais e as listas de ações são **digitalizações** sem camada de
 * texto: dessas fica o número de páginas e o documento, não o texto.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Uma entrada da página anual (partido × ano × secção), já indexada. */
export type PartidosDocumento = {
  doc_id: string;
  ano: number;
  secao: string;
  secao_titulo?: string | null;
  ancora?: string | null;
  ordem?: number | null;
  partido_nome?: string | null;
  partido_sigla?: string | null;
  partido_chave?: string | null;
  entregou?: boolean | null;
  motivo?: string | null;
  observacao?: string | null;
  nota?: boolean;
  agregado?: boolean;
  documento?: boolean;
  ficheiro?: string | null;
  ficheiro_kb?: number | null;
  pdf_url?: string | null;
  pdf_titulo?: string | null;
  paginas?: number | null;
  pdf_digitalizado?: boolean | null;
  texto?: string | null;
  texto_chars?: number | null;
  texto_extraido?: boolean;
  pagina_url?: string | null;
  score?: number | null;
};

export type PartidosFacet = { key: string | number | null; label?: string | null; nome?: string | null; count?: number };

export type PartidosSearchResult = {
  total: number;
  page: number;
  size: number;
  items: PartidosDocumento[];
  facets: {
    ano?: PartidosFacet[];
    secao?: PartidosFacet[];
    partido?: PartidosFacet[];
  };
  kpis: {
    entregues?: number;
    em_falta?: number;
    com_documento?: number;
    com_texto?: number;
    digitalizados?: number;
  };
};

export type PartidosAnoResumo = {
  ano: number;
  url?: string | null;
  sha256?: string | null;
  bytes?: number | null;
  secoes?: string[];
  itens?: number | null;
  notas?: number | null;
  documentos?: number | null;
  partidos?: number | null;
  pdfs?: number | null;
  com_texto?: number | null;
  digitalizados?: number | null;
  sem_documento?: number | null;
  indexados?: number | null;
  recolhido_em?: string | null;
  indexado_em?: string | null;
  em_disco?: boolean;
};

export type PartidosRecolha = {
  url?: string | null;
  fonte?: string | null;
  bytes?: number | null;
  sha256?: string | null;
  jsonl?: string | null;
  inscritos?: number | null;
  extintos?: number | null;
  registos?: number | null;
  com_descricao?: number | null;
  com_site?: number | null;
  com_erro?: number | null;
  recolhido_em?: string | null;
  indexados?: number | null;
};

export type PartidosFonte = {
  id: string;
  nome: string;
  url: string;
  url_ano?: string;
  descricao: string;
  secoes?: { id: string; ancora: string; label: string }[];
};

export type PartidosMeta = {
  dir: string;
  anos: PartidosAnoResumo[];
  anos_recolhidos: number;
  anos_em_disco: number[];
  itens: number;
  documentos: number;
  pdfs: number;
  pdf_bytes: number;
  cne: PartidosRecolha;
  fontes: PartidosFonte[];
  indices: string[];
};

export type PartidosAnoDisponivel = {
  ano: number;
  url: string;
  recolhido: boolean;
  itens?: number | null;
  documentos?: number | null;
  partidos?: number | null;
  com_texto?: number | null;
  digitalizados?: number | null;
  indexados?: number | null;
  recolhido_em?: string | null;
};

export type PartidosAnos = {
  total: number;
  minimo: number;
  anos: PartidosAnoDisponivel[];
};

export type PartidosFicheiros = {
  dir: string;
  paginas: string[];
  pdf: { ano: number; ficheiro: string; bytes: number; modificado_em: string }[];
  pdf_total: number;
  pdf_bytes: number;
  jsonl: { ficheiro: string; bytes: number }[];
  cne: string[];
};

export type PartidosPorAno = {
  ano: number;
  entradas: number;
  partidos: number;
  documentos: number;
  com_texto: number;
  digitalizados: number;
  em_falta: number;
  paginas: number;
  megabytes: number;
  secoes: PartidosFacet[];
};

export type PartidosTopPartido = {
  chave: string;
  nome?: string | null;
  count: number;
  documentos: number;
  em_falta: number;
  anos: number;
};

export type PartidosRegistoResumo = {
  total: number;
  inscritos?: number;
  extintos?: number;
  com_site?: number;
  com_descricao?: number;
};

export type PartidosResumo = {
  total: number;
  partidos_distintos: number;
  entregues: number;
  em_falta: number;
  com_texto: number;
  digitalizados: number;
  paginas: number;
  por_ano: PartidosPorAno[];
  por_secao: PartidosFacet[];
  top_partidos: PartidosTopPartido[];
  registo: PartidosRegistoResumo;
};

/** Ficha oficial do partido no registo da CNE. */
export type PartidosRegistoPartido = {
  chave: string;
  denominacao: string;
  sigla?: string | null;
  siglas?: string[];
  situacao?: string | null;
  data_inscricao?: string | null;
  site?: string | null;
  logotipo_url?: string | null;
  descricao?: string | null;
  url?: string | null;
  recolhido_em?: string | null;
};

export type PartidosFichaPartido = {
  termo: string;
  chave: string;
  encontrado: boolean;
  partido_nome?: string | null;
  partido_sigla?: string | null;
  chaves?: string[];
  registo?: PartidosRegistoPartido | null;
  total: number;
  em_falta: number;
  com_texto: number;
  por_ano: { ano: number; entradas: number; em_falta: number; secoes: PartidosFacet[] }[];
  por_secao: PartidosFacet[];
  documentos: PartidosDocumento[];
};

export type PartidosPessoa = {
  nif: string;
  pessoa: {
    nif?: string | null;
    nome?: string | null;
    cargos?: unknown[];
    fonte?: string | null;
    partido?: string | null;
    metadata?: Record<string, unknown>;
  };
  partido?: string | null;
  ficha_partido?: PartidosFichaPartido | null;
};

export type PartidosPessoas = {
  termo: string;
  partido: string;
  total: number;
  items: { nif?: string | null; nome?: string | null; partido?: string | null; source?: string | null; roles_count?: number | null }[];
};

export type PartidosJob = {
  job_id: string;
  tipo: "recolher" | "indexar";
  status: "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  already_running?: boolean;
  message?: string;
  payload?: Record<string, unknown>;
  progress?: {
    phase?: string;
    anos_total?: number;
    anos_done?: number;
    ficheiros_total?: number;
    ficheiros_done?: number;
    registos?: number;
    current?: string | null;
  };
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export type PartidosAmostra = {
  ano: number;
  total: number;
  items: PartidosDocumento[];
  error?: string;
};

export type PartidosRegisto = {
  total: number;
  page: number;
  size: number;
  items: PartidosRegistoPartido[];
};

export type PartidosSearchParams = {
  q?: string;
  ano?: number;
  secao?: string;
  partido?: string;
  sigla?: string;
  entregou?: boolean;
  com_documento?: boolean;
  digitalizado?: boolean;
  sort?: "relevancia" | "ano" | "partido" | "secao" | "paginas";
  order?: "asc" | "desc";
  page?: number;
  size?: number;
};

/* ------------------------------------------------------------------ pedidos */

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

/* ------------------------------------------------------------- formatação */

/** Contagem com separador de milhares. */
export function count(valor?: number | null): string {
  return valor === undefined || valor === null ? "—" : valor.toLocaleString("pt-PT");
}

/** Números grandes de forma curta («18,9 mil»). */
export function compact(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1e6) return `${(valor / 1e6).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M`;
  if (abs >= 1e3) return `${(valor / 1e3).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} mil`;
  return count(valor);
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

/** Data ISO abreviada (`2024-06-01` → `01/06/2024`). */
export function shortDate(iso?: string | null): string {
  if (!iso) return "—";
  const partes = String(iso).slice(0, 10).split("-");
  if (partes.length !== 3) return String(iso);
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

/** Rótulo legível de cada secção da página anual do TC. */
export const SECOES_LABEL: Record<string, string> = {
  contas_anuais: "Contas anuais",
  lista_acoes: "Lista de ações e meios",
  relatorios_ecfp: "Relatórios da ECFP",
  acordaos: "Acórdãos",
  decisoes_ecfp: "Decisões da ECFP",
};

/** Rótulo de uma secção (com o `label` do backend como primeira escolha). */
export function secaoLabel(secao?: string | null, label?: string | null): string {
  if (label) return label;
  if (!secao) return "—";
  return SECOES_LABEL[secao] || secao;
}

/** Rótulo do estado de entrega das contas. */
export function entregaLabel(item: Pick<PartidosDocumento, "entregou" | "motivo" | "nota" | "agregado">): string {
  if (item.nota) return "Nota";
  if (item.agregado) return "Documento agregado";
  if (item.entregou) return "Entregue";
  return item.motivo ? `Em falta — ${item.motivo}` : "Em falta";
}

/* -------------------------------------------------------------------- API */

/** Pasta dos dados, anos recolhidos, volumetria e índices usados. */
export function getPartidosMeta(): Promise<PartidosMeta> {
  return request<PartidosMeta>("/partidos/meta");
}

/** Anos publicados pelo TC e o que já está recolhido. */
export function getPartidosAnos(refrescar = false): Promise<PartidosAnos> {
  return request<PartidosAnos>(`/partidos/anos${refrescar ? "?refrescar=true" : ""}`);
}

/** As duas fontes do módulo e as secções da página anual. */
export function getPartidosFontes(): Promise<{ fontes: PartidosFonte[]; indices: string[] }> {
  return request("/partidos/fontes");
}

/** Páginas, PDF e JSONL guardados na pasta do módulo. */
export function getPartidosFicheiros(): Promise<PartidosFicheiros> {
  return request<PartidosFicheiros>("/partidos/ficheiros");
}

/** Recolhe páginas + PDF + registo da CNE para JSONL (segundo plano). */
export function recolherPartidos(
  params: { anos?: number[]; secoes?: string[]; com_pdf?: boolean; com_cne?: boolean; forcar?: boolean; indexar?: boolean } = {}
): Promise<PartidosJob> {
  return post<PartidosJob>("/partidos/recolher", params);
}

/** Indexa os JSONL lidos no Elasticsearch (segundo plano). */
export function indexarPartidos(params: { anos?: number[]; forcar?: boolean } = {}): Promise<PartidosJob> {
  return post<PartidosJob>("/partidos/indexar", params);
}

export function getPartidosJobs(): Promise<{ total: number; items: PartidosJob[] }> {
  return request("/partidos/jobs");
}

export function getPartidosJob(jobId: string): Promise<PartidosJob> {
  return request<PartidosJob>(`/partidos/jobs/${jobId}`);
}

/** Painel: por ano, por secção, top partidos e cumprimento. */
export function getPartidosResumo(anos?: number[]): Promise<PartidosResumo> {
  const query = anos && anos.length ? queryString({ ano: anos.join(",") }) : "";
  return request<PartidosResumo>(`/partidos/resumo${query}`);
}

/** Pesquisa os documentos das contas (com o texto dos PDF digitais). */
export function searchPartidos(params: PartidosSearchParams): Promise<PartidosSearchResult> {
  return request<PartidosSearchResult>(`/partidos/search${queryString({ ...params })}`);
}

/** Registo oficial dos partidos na CNE. */
export function getPartidosRegisto(params: { q?: string; situacao?: "inscrito" | "extinto"; page?: number; size?: number } = {}): Promise<PartidosRegisto> {
  return request<PartidosRegisto>(`/partidos/registo${queryString({ ...params })}`);
}

/** Ficha do partido: registo da CNE + contas por ano. */
export function getPartidosPartido(termo: string, size = 400): Promise<PartidosFichaPartido> {
  return request<PartidosFichaPartido>(`/partidos/partido/${encodeURIComponent(termo)}${queryString({ size })}`);
}

/** Pessoas do PessoasIQ ligadas ao partido. */
export function getPartidosPartidoPessoas(termo: string, size = 60): Promise<PartidosPessoas> {
  return request<PartidosPessoas>(`/partidos/partido/${encodeURIComponent(termo)}/pessoas${queryString({ size })}`);
}

/** A pessoa e o partido dela, com as contas do partido. */
export function getPartidosPessoa(nif: string): Promise<PartidosPessoa> {
  return request<PartidosPessoa>(`/partidos/pessoa/${encodeURIComponent(nif)}`);
}

/** Amostra das entradas lidas de um ano (não precisa do Elasticsearch). */
export function getPartidosAmostra(ano: number, limite = 50): Promise<PartidosAmostra> {
  return request<PartidosAmostra>(`/partidos/amostra/${ano}${queryString({ limit_items: limite })}`);
}

/** URL do PDF guardado no módulo (`inline` abre no browser; `download` descarrega). */
export function partidoPdfUrl(ano: number, ficheiro: string, download = false): string {
  return `${API_BASE}/partidos/documento/pdf${queryString({ ano, ficheiro, download: download || undefined })}`;
}

/** Exporta em CSV o resultado da pesquisa. */
export async function downloadPartidosCsv(params: PartidosSearchParams & { maximo?: number }): Promise<void> {
  const query = queryString({ ...params });
  const res = await fetch(`${API_BASE}/partidos/export.csv${query}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `partidos${params.ano ? `-${params.ano}` : ""}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
