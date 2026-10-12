/**
 * Cliente da importação dos **Contratos Públicos do Portal Base** (dados.gov.pt).
 *
 * A página de administração usa estes endpoints para (1) ler o catálogo de
 * ficheiros publicados por ano, (2) ver o **formato real** do ZIP do ano atual,
 * (3) lançar a importação para o Elasticsearch e seguir o progresso, e (4)
 * cancelar a meio.
 *
 * O `fetch` de `authApi.ts` injecta o token; a importação exige sessão de
 * administrador (`403` nas contas sem papel `admin`).
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Ficheiro publicado no conjunto (um ZIP e um XLSX por ano). */
export type BaseImpicRecurso = {
  titulo: string;
  ano: string;
  formato: string;
  bytes: number;
  atualizado_em: string;
  url: string;
  url_estavel: string;
  sha1: string;
  id: string;
};

/** Ficheiro já descarregado nesta instalação. */
export type BaseImpicCache = {
  ano: string;
  ficheiro: string;
  bytes: number;
  modificado_em: string;
};

/** Volumetria do índice `contratos`, por ano. */
export type BaseImpicIndice = {
  disponivel: boolean;
  indice?: string;
  total?: number;
  por_ano?: { ano: number; contratos: number }[];
  erro?: string;
};

export type BaseImpicRecursos = {
  dataset: string;
  url_dataset: string;
  ano_atual: number;
  anos: number[];
  recursos: BaseImpicRecurso[];
  em_cache: BaseImpicCache[];
  indice: BaseImpicIndice;
};

/** Campo de um contrato no JSON publicado. */
export type BaseImpicCampo = { nome: string; tipo: string; exemplo: string };

/** Formato do ZIP de um ano (o que a página mostra antes de importar). */
export type BaseImpicFormato = {
  ano: string;
  recurso?: BaseImpicRecurso;
  descarregado: boolean;
  ficheiro_local?: string;
  nota?: string;
  membros?: { nome: string; bytes: number; comprimido: number }[];
  membro_json?: string;
  membro_bytes?: number;
  forma?: string;
  total_campos?: number;
  campos?: BaseImpicCampo[];
  exemplo_inicio?: string;
  indice_destino?: string;
  normalizacao?: string;
  erro?: string;
};

/** Contrato já normalizado (o que é indexado). */
export type BaseImpicAmostraItem = {
  idcontrato?: string;
  Ano?: number;
  objectoContrato?: string;
  precoContratual?: number | null;
  adjudicantes?: string[];
  adjudicatarios?: string[];
  cpv?: string[];
};

export type BaseImpicAmostra = { ano: string; itens: BaseImpicAmostraItem[]; erro?: string };

/** Estado de uma importação (uma por ano). */
export type BaseImpicTrabalho = {
  ano: number;
  estado: "parado" | "a_correr" | "concluido" | "erro" | "cancelado" | string;
  fase: string;
  mensagem: string;
  bytes_lidos: number;
  bytes_total: number;
  registos: number;
  indexados: number;
  erros: number;
  lotes: number;
  cancelar: boolean;
  iniciado_em?: string | null;
  terminado_em?: string | null;
  utilizador?: string;
};

export type BaseImpicEstado = {
  trabalhos: Record<string, BaseImpicTrabalho>;
  indice: BaseImpicIndice;
  em_cache: BaseImpicCache[];
  ano_atual: number;
};

/* ---------------------------------------------------------------- helpers */

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

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/* ----------------------------------------------------------------- rotas */

/** Catálogo de ficheiros do conjunto + o que já está no índice. */
export function getBaseImpicRecursos(forcar = false): Promise<BaseImpicRecursos> {
  return request<BaseImpicRecursos>(`/base-impic/recursos${forcar ? "?forcar=true" : ""}`);
}

/** Formato do ZIP de um ano. `descarregar` força a leitura do ficheiro publicado. */
export function getBaseImpicFormato(ano: number | string, descarregar = false): Promise<BaseImpicFormato> {
  return request<BaseImpicFormato>(`/base-impic/formato/${ano}${descarregar ? "?descarregar=true" : ""}`);
}

/** Primeiros contratos do ano, já normalizados. */
export function getBaseImpicAmostra(ano: number | string, registos = 3): Promise<BaseImpicAmostra> {
  return request<BaseImpicAmostra>(`/base-impic/amostra/${ano}?registos=${registos}`);
}

/** Progresso das importações e volumetria do índice. */
export function getBaseImpicEstado(): Promise<BaseImpicEstado> {
  return request<BaseImpicEstado>("/base-impic/estado");
}

/** Lança a importação de um ano em segundo plano (idempotente por `idcontrato`). */
export function importarBaseImpic(payload: {
  ano?: number;
  limite?: number | null;
  descarregar?: boolean;
}): Promise<{ iniciado: boolean; ano: number; mensagem: string; estado?: BaseImpicTrabalho }> {
  return post("/base-impic/importar", payload);
}

/** Pede a paragem da importação de um ano. */
export function cancelarBaseImpic(ano: number | string): Promise<{ ano: number; cancelado: boolean; mensagem: string }> {
  return post(`/base-impic/cancelar/${ano}`);
}

/** Anos com ZIP publicado. */
export function getBaseImpicAnos(): Promise<{ anos: number[]; ano_atual: number }> {
  return request("/base-impic/anos");
}

/* --------------------------------------------------------------- formatação */

export function baseImpicBytes(bytes?: number | null): string {
  if (!bytes || !Number.isFinite(bytes) || bytes <= 0) return "—";
  const unidades = ["B", "KB", "MB", "GB"];
  const indice = Math.min(unidades.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** indice).toFixed(indice === 0 ? 0 : 1)} ${unidades[indice]}`;
}

export function baseImpicQuando(valor?: string | null): string {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

export function baseImpicEstadoCor(estado?: string): string {
  switch (estado) {
    case "a_correr":
      return "border-sky-400/30 bg-sky-400/10 text-sky-200";
    case "concluido":
      return "border-teal-400/30 bg-teal-400/10 text-teal-200";
    case "cancelado":
      return "border-amber-400/30 bg-amber-400/10 text-amber-200";
    case "erro":
      return "border-rose-400/30 bg-rose-400/10 text-rose-200";
    default:
      return "border-white/10 bg-white/[0.05] text-muted-foreground";
  }
}
