/**
 * Cliente das empresas/entidades **globais** (`/companies-global/*`).
 *
 * Uma vista única sobre todas as fontes de entidades e empresas do IQ OS:
 * cadastro português (portal base), firmas (RNPC), marcas (INPI), órgãos
 * adjudicantes e empresas adjudicatárias de Espanha (PLACSP) e contas do CRM
 * (estas só com sessão, porque são privadas por utilizador).
 */
import { API_BASE } from "./api";

export type CompaniesGlobalSourceId =
  | "all"
  | "entity"
  | "firma"
  | "trademark"
  | "organo_es"
  | "adjudicataria_es"
  | "crm"
  | "iberinform";

/** Fonte concreta (sem o agregado «all»). */
export type CompaniesGlobalSourceKey = Exclude<CompaniesGlobalSourceId, "all">;

/** Fonte do catálogo, com a volumetria indexada. */
export type CompaniesGlobalSource = {
  id: CompaniesGlobalSourceKey;
  label: string;
  hint?: string;
  country?: string;
  /** Registos/entidades disponíveis (aproximado nas fontes de Espanha). */
  available?: number | null;
  available_label?: string | null;
  /** Documentos do índice (só nas fontes agregadas de Espanha). */
  documents?: number | null;
  /** verdadeiro quando a fonte exige sessão e não há nenhuma. */
  blocked?: boolean;
  session?: boolean;
};

/** Contagem por fonte numa pesquisa (o cartão de cada origem). */
export type CompaniesGlobalCard = {
  id: CompaniesGlobalSourceKey;
  label: string;
  country: string;
  total: number;
  returned: number;
  error: string | null;
};

/** Linha normalizada: o mesmo formato para todas as fontes. */
export type CompaniesGlobalRow = {
  source: CompaniesGlobalSourceKey;
  source_label: string;
  country: string;
  id: string;
  name: string;
  detail: string;
  nif: string;
  region: string;
  date: string | null;
  contracts_count: number | null;
  total_value: number | null;
  extra: Record<string, unknown>;
  open: { view: string; arg: string; mode?: string } | null;
};

export type CompaniesGlobalResult = {
  query: string;
  source: CompaniesGlobalSourceId;
  size: number;
  offset: number;
  took_ms: number;
  total: number;
  items: CompaniesGlobalRow[];
  sources: CompaniesGlobalCard[];
  /** Resposta só com as fontes de diretório (sem as agregações do PLACSP). */
  fast?: boolean;
  /** Resposta servida da cache do servidor. */
  cached?: boolean;
  error?: string;
};

/** Linha da agregação de entidades do PLACSP (`/contracts-es/entities`). */
export type ContratoEsEntity = {
  kind: "organo" | "adjudicatario";
  kind_label: string;
  name: string;
  count: number;
  total_value: number | null;
  city: string;
  nuts: string;
  nif: string;
  organo_id: string;
  organo_tipo: string;
  last_year: number | null;
};

export type ContratoEsEntityResult = {
  query?: string | null;
  total: number;
  by_kind?: Record<string, number>;
  items: ContratoEsEntity[];
  from?: number;
  size?: number;
  error?: string;
};

/**
 * Tempo máximo de uma leitura (ms).
 *
 * A pesquisa «Todas» agrega os ~4 M de contratos do PLACSP e, com a cache do
 * Elasticsearch fria, pode demorar muito. Sem limite, a página ficava presa em
 * «A pesquisar…» para sempre — melhor falhar e poder repetir.
 */
const TIMEOUT_MS = 45000;

async function fetchOnce(path: string, signal: AbortSignal): Promise<Response> {
  return fetch(`${API_BASE}${path}`, { signal });
}

async function request<T>(path: string, tentativas = 2): Promise<T> {
  let ultimoErro: unknown = null;
  for (let tentativa = 1; tentativa <= tentativas; tentativa += 1) {
    const controlador = new AbortController();
    const relogio = setTimeout(() => controlador.abort(), TIMEOUT_MS);
    try {
      const response = await fetchOnce(path, controlador.signal);
      if (!response.ok) {
        let detail = `${response.status}`;
        try {
          const payload = (await response.json()) as { detail?: unknown };
          if (payload?.detail) detail = String(payload.detail);
        } catch {
          /* resposta sem JSON */
        }
        // 5xx e 429 valem uma segunda tentativa; 4xx não.
        if (response.status >= 500 || response.status === 429) {
          ultimoErro = new Error(detail);
          continue;
        }
        throw new Error(detail);
      }
      return (await response.json()) as T;
    } catch (err) {
      ultimoErro = err;
      const abortado = err instanceof DOMException && err.name === "AbortError";
      if (abortado) {
        ultimoErro = new Error(`O pedido demorou mais de ${Math.round(TIMEOUT_MS / 1000)} s.`);
      }
    } finally {
      clearTimeout(relogio);
    }
  }
  throw ultimoErro instanceof Error ? ultimoErro : new Error("Falha na ligação ao servidor.");
}

export function searchCompaniesGlobal(params: {
  q: string;
  source?: CompaniesGlobalSourceId;
  size?: number;
  offset?: number;
  fast?: boolean;
}) {
  const query = new URLSearchParams();
  query.set("q", params.q ?? "");
  query.set("source", params.source ?? "all");
  query.set("size", String(params.size ?? 24));
  query.set("offset", String(params.offset ?? 0));
  if (params.fast) query.set("fast", "true");
  return request<CompaniesGlobalResult>(`/companies-global/search?${query.toString()}`);
}

export function getCompaniesGlobalSources() {
  return request<{ items: CompaniesGlobalSource[]; error?: string }>("/companies-global/sources");
}

/** Entidades de Espanha (órgãos adjudicantes e empresas adjudicatárias). */
export function searchEsEntities(params: {
  q?: string;
  kind?: "organo" | "adjudicatario" | "all";
  size?: number;
  offset?: number;
}) {
  const query = new URLSearchParams();
  query.set("q", params.q ?? "");
  query.set("kind", params.kind ?? "all");
  query.set("size", String(params.size ?? 20));
  query.set("from", String(params.offset ?? 0));
  return request<ContratoEsEntityResult>(`/contracts-es/entities?${query.toString()}`);
}
