/**
 * Cliente do módulo **Administração Central** (`/administracao-central/*`).
 *
 * O INE publica anualmente, em PDF, a lista das entidades que integram o Setor
 * Institucional das Administrações Públicas (SEC 2010). O backend lê esse PDF,
 * constrói o **índice** das entidades da Administração Central e liga cada uma
 * ao NIF com que contrata no portal BASE, para que a plataforma possa mostrar:
 *
 * - a **lista pesquisável** das entidades (S.13111 Estado, S.13112 Serviços e
 *   Fundos Autónomos e S.13113 Instituições Sem Fim Lucrativo);
 * - a **ficha** de cada entidade: contratos adjudicados, adjudicatárias, CPV;
 * - o **painel** do setor: volume, valor, anos, rankings de entidades e de
 *   adjudicatárias;
 * - a **pesquisa de contratos** adjudicados pelo setor.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Subsetor SEC 2010 indexado, com a cobertura das ligações a NIF. */
export type AdministracaoCentralSubsetor = {
  id: string;
  nome: string;
  total: number;
  ligadas: number;
};

export type AdministracaoCentralFonte = {
  designacao: string;
  edicao: number;
  emissor: string;
  publicacao: string;
  metodologia: string;
  contacto: string;
  ficheiro: string;
};

export type AdministracaoCentralMeta = {
  fonte: AdministracaoCentralFonte;
  ficheiro_pdf: string;
  ficheiro_indice: string;
  ligacoes_manuais: string;
  gerado_em?: string | null;
  subsetor_omissao: string;
  subsetores: AdministracaoCentralSubsetor[];
  total: number;
  ligadas: number;
  com_contratos?: number;
  candidatos_contratos?: number | null;
  indice_em_falta?: boolean;
  erro?: string | null;
};

/** Tipo de ligação entre o nome do INE e o NIF usado nos contratos. */
export type AdministracaoCentralLigacao = "exato" | "nome" | "prefixo" | "sigla" | "forte" | "manual" | "nenhuma";

export type AdministracaoCentralEntidade = {
  id: string;
  nome: string;
  slug: string;
  subsetor: string;
  subsetor_nome: string;
  nif?: string | null;
  nome_contratos?: string | null;
  ligacao: AdministracaoCentralLigacao;
  ligacao_confianca: number;
  contratos: number;
  valor: number;
  ano_min?: number | null;
  ano_max?: number | null;
};

export type AdministracaoCentralEntidadesResultado = {
  query?: string | null;
  subsetor: string;
  ordenar: string;
  total: number;
  from: number;
  size: number;
  items: AdministracaoCentralEntidade[];
  error?: string | null;
};

/** Linha genérica das agregações (`by year`, CPV, adjudicatárias…). */
export type AdministracaoCentralLinha = {
  key: string | number;
  nome?: string | null;
  count: number;
  valor: number;
};

export type AdministracaoCentralRanking = {
  nif: string;
  id?: string | null;
  nome: string;
  nome_contratos?: string | null;
  subsetor?: string | null;
  contratos: number;
  valor: number;
};

export type AdministracaoCentralAnaliticas = {
  subsetor?: string;
  ano?: number | null;
  total_contratos: number;
  total_valor: number;
  valor_medio: number;
  valor_maximo: number;
  entidades_com_contratos?: number;
  adjudicatarias_distintas?: number;
  por_ano: AdministracaoCentralLinha[];
  top_entidades: AdministracaoCentralRanking[];
  top_adjudicatarios: AdministracaoCentralLinha[];
  top_cpv: AdministracaoCentralLinha[];
  tipos_procedimento: AdministracaoCentralLinha[];
  tipos_contrato: AdministracaoCentralLinha[];
  atualizado_em?: string | null;
  aviso?: string;
  error?: string | null;
};

/** Contrato do portal BASE, tal como o índice o devolve. */
export type AdministracaoCentralContrato = {
  idcontrato?: string | null;
  objectoContrato?: string | null;
  descContrato?: string | null;
  precoContratual?: number | null;
  PrecoTotalEfetivo?: number | null;
  dataPublicacao?: string | null;
  dataCelebracaoContrato?: string | null;
  Ano?: number | null;
  tipoprocedimento?: string | null;
  tipoContrato?: string[] | null;
  localExecucao?: string[] | null;
  cpv?: { code?: string | null; description?: string | null }[];
  adjudicantes?: { parsed?: { nome?: string; nif?: string }[] } | null;
  adjudicatarios?: { parsed?: { nome?: string; nif?: string }[] } | null;
  doc_id?: string | null;
};

export type AdministracaoCentralContratosResultado = {
  total: number;
  items: AdministracaoCentralContrato[];
  from: number;
  size: number;
  aviso?: string;
  error?: string | null;
};

export type AdministracaoCentralFicha = {
  entidade: AdministracaoCentralEntidade;
  contratos?: {
    total: number;
    valor: number;
    valor_medio: number;
    valor_maximo: number;
    por_ano: AdministracaoCentralLinha[];
  };
  top_adjudicatarios?: AdministracaoCentralLinha[];
  top_cpv?: AdministracaoCentralLinha[];
  tipos_procedimento?: AdministracaoCentralLinha[];
  ultimos?: AdministracaoCentralContrato[];
  aviso?: string;
  error?: string | null;
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

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Euros em pt-PT (sem casas decimais acima de mil). */
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

/**
 * Período de atividade da entidade: primeiro e último ano com contratos
 * (`2012–2026`), um único ano quando só há um. `null` sem contratos.
 */
export function periodoAtividade(anoMin?: number | null, anoMax?: number | null): string | null {
  const inicio = anoMin ?? anoMax;
  const fim = anoMax ?? anoMin;
  if (!inicio || !fim) return null;
  return inicio === fim ? String(inicio) : `${inicio}–${fim}`;
}

/** Etiqueta legível do tipo de ligação nome→NIF. */
export const LIGACAO_LABEL: Record<AdministracaoCentralLigacao, string> = {
  exato: "Nome exato",
  nome: "Nome (sem sigla)",
  prefixo: "Nome truncado",
  sigla: "Sigla",
  forte: "Nome semelhante",
  manual: "Correção manual",
  nenhuma: "Sem NIF",
};

/* ------------------------------------------------------------------ pedidos */

export function getAdministracaoCentralMeta(): Promise<AdministracaoCentralMeta> {
  return request<AdministracaoCentralMeta>("/administracao-central/meta");
}

export function getAdministracaoCentralSubsetores(): Promise<{
  fonte: AdministracaoCentralFonte;
  subsetor_omissao: string;
  items: AdministracaoCentralSubsetor[];
  total: number;
  ligadas: number;
  indice_em_falta: boolean;
}> {
  return request("/administracao-central/subsetores");
}

export function searchAdministracaoCentralEntidades(params: {
  q?: string;
  subsetor?: string;
  ligacao?: "com_nif" | "sem_nif" | "com_contratos";
  ordenar?: "nome" | "nome_desc" | "contratos" | "valor" | "subsetor";
  size?: number;
  offset?: number;
}): Promise<AdministracaoCentralEntidadesResultado> {
  return request(
    `/administracao-central/entidades${queryString({
      q: params.q,
      subsetor: params.subsetor,
      ligacao: params.ligacao,
      ordenar: params.ordenar ?? "valor",
      size: params.size ?? 25,
      from: params.offset ?? 0,
    })}`,
  );
}

export function getAdministracaoCentralEntidade(id: string, top = 15): Promise<AdministracaoCentralFicha> {
  return request(`/administracao-central/entidades/${encodeURIComponent(id)}${queryString({ top })}`);
}

export function getAdministracaoCentralContratosDaEntidade(
  id: string,
  params: { q?: string; ano?: number; adjudicatario?: string; cpv?: string; size?: number; offset?: number } = {},
): Promise<AdministracaoCentralContratosResultado> {
  return request(
    `/administracao-central/entidades/${encodeURIComponent(id)}/contratos${queryString({
      q: params.q,
      ano: params.ano,
      adjudicatario: params.adjudicatario,
      cpv: params.cpv,
      size: params.size ?? 20,
      from: params.offset ?? 0,
    })}`,
  );
}

export function searchAdministracaoCentralContratos(
  params: {
    q?: string;
    subsetor?: string;
    ano?: number;
    entidade?: string;
    adjudicatario?: string;
    cpv?: string;
    preco_min?: number;
    preco_max?: number;
    size?: number;
    offset?: number;
  } = {},
): Promise<AdministracaoCentralContratosResultado> {
  return request(
    `/administracao-central/contratos${queryString({
      q: params.q,
      subsetor: params.subsetor,
      ano: params.ano,
      entidade: params.entidade,
      adjudicatario: params.adjudicatario,
      cpv: params.cpv,
      preco_min: params.preco_min,
      preco_max: params.preco_max,
      size: params.size ?? 20,
      from: params.offset ?? 0,
    })}`,
  );
}

export function getAdministracaoCentralAnaliticas(params: {
  subsetor?: string;
  ano?: number;
  nif?: string;
  q?: string;
  top?: number;
  forcar?: boolean;
} = {}): Promise<AdministracaoCentralAnaliticas> {
  return request(`/administracao-central/analiticas${queryString({ ...params })}`);
}

export function reindexarAdministracaoCentral(usarContratos = true): Promise<{
  total: number;
  ligadas: number;
  subsetores: AdministracaoCentralSubsetor[];
  gerado_em?: string | null;
  ficheiro: string;
}> {
  return request("/administracao-central/reindexar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usar_contratos: usarContratos }),
  });
}

/** Descarrega o CSV do índice de entidades (com o filtro de pesquisa aplicado). */
export async function downloadAdministracaoCentralCsv(params: { q?: string; subsetor?: string } = {}): Promise<void> {
  const res = await fetch(
    `${API_BASE}/administracao-central/export.csv${queryString({ q: params.q, subsetor: params.subsetor })}`,
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "administracao-central.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
