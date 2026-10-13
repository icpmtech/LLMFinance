/**
 * Cliente do módulo **Despesas das câmaras municipais** (`/municipios/*`).
 *
 * Uma área por município, com duas fontes que se cruzam:
 *
 * - a **despesa** do indicador 0013909 do INE (origem DGAL), por classificador
 *   económico (`D`, `D1`, `D11`, …), em euros. O INE publica em milhares de
 *   euros (potência de 10 = 3) e o backend converte para euros;
 * - a **contratação pública** em que o município é adjudicante, agregada do
 *   Portal BASE: total de contratos, valor, série anual e fornecedores.
 *
 * A contratação em nome de associações intermunicipais (LIPOR, SIMRIA, …) fica
 * deliberadamente de fora: pertence a vários municípios, não a um.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

/** Uma linha da lista de municípios. */
export type MunicipioDespesas = {
  doc_id?: string;
  nome: string;
  nome_keyword?: string;
  /** Código geográfico do INE (7 caracteres) — a chave estável do município. */
  geocod?: string;
  distrito?: string | null;
  nuts?: string | null;
  nuts_nome?: string | null;
  populacao_2021?: number | null;
  ano_despesas?: number | null;
  anos?: string[];
  despesas_total?: number | null;
  despesas_correntes?: number | null;
  despesas_capital?: number | null;
  despesas_pessoal?: number | null;
  despesas_bens_servicos?: number | null;
  despesas_bens_capital?: number | null;
  despesas_juros?: number | null;
  despesas_transferencias_freguesias?: number | null;
  despesas_transferencias_capital?: number | null;
  despesas_transferencias_capital_freguesias?: number | null;
  despesas_outras_transferencias_capital?: number | null;
  despesas_outras_correntes?: number | null;
  despesas_outras_capital?: number | null;
  despesas_ativos_financeiros?: number | null;
  despesas_passivos_financeiros?: number | null;
  contratos_total?: number | null;
  contratos_valor?: number | null;
  contratos_primeiro_ano?: number | null;
  contratos_ultimo_ano?: number | null;
  /** Ano do Portal BASE escolhido no filtro (só vem preenchido quando há um). */
  contratos_ano?: number | null;
  /** Contratos e valor **do ano escolhido** (Portal BASE). */
  contratos_ano_total?: number | null;
  contratos_ano_valor?: number | null;
  /**
   * Anos mais recentes de contratação **deste município** (Portal BASE), do
   * mais recente para o mais antigo — são os anos dele, não zeros dos anos em
   * que não contratou.
   */
  contratos_recentes?: { ano: string; contratos: number; valor: number }[];
  /** Nomes com que a câmara aparece no Portal BASE. */
  adjudicantes?: string[];
  fonte_despesas?: string | null;
  fonte_contratos?: string | null;
};

/** A ficha completa de um município. */
export type MunicipioFicha = MunicipioDespesas & {
  /** Série completa: ano → código do classificador → euros. */
  despesas_por_ano?: Record<string, Record<string, number>> | null;
  /** Código do classificador → etiqueta legível. */
  classificadores?: Record<string, string> | null;
  /** Ano → { contratos, valor }. */
  contratos_por_ano?: Record<string, { contratos: number; valor: number }> | null;
  /**
   * Agregação a pedido (não guardada no índice): fornecedores e tipos de
   * contrato do município, calculados quando a área é aberta.
   */
  contratos_detalhe?: {
    total?: number;
    valor?: number;
    por_ano?: Record<string, { contratos: number; valor: number }>;
    fornecedores?: { nome: string; contratos: number; valor: number }[];
    tipos?: { key: string; count: number }[];
    error?: string;
  } | null;
  recolhido_em?: string | null;
  error?: string;
};

export type MunicipiosDespesasResponse = {
  total: number;
  page: number;
  size: number;
  items: MunicipioDespesas[];
  /** Soma da despesa dos municípios que passam o filtro (não só a página). */
  despesas_somadas?: number;
  contratos_somados?: number;
  /** Ano do Portal BASE que a lista está a mostrar (quando há um escolhido). */
  ano_contratos?: number | null;
  /** Contratos e valor **desse ano**, somados por todos os municípios do filtro. */
  contratos_ano_total_somados?: number;
  contratos_ano_somados?: number;
  distritos?: { key: string; count: number }[];
  origem?: string;
  error?: string | null;
};

export type MunicipiosDespesasMeta = {
  fonte_despesas?: string | null;
  fonte_despesas_url?: string | null;
  fonte_dados_gov?: string | null;
  fonte_contratos?: string | null;
  indicador?: string | null;
  designacao?: string | null;
  anos?: string[];
  /** Anos com contratação registada no Portal BASE (do mais recente para o mais antigo). */
  anos_contratos?: string[];
  /** Os anos recentes em destaque (os mesmos para toda a lista). */
  anos_recentes?: string[];
  /** Contratação dos anos recentes, somada por todos os municípios. */
  totais_recentes?: { ano: string; contratos: number; valor: number }[];
  atualizado_no_ine?: string | null;
  ultimo_periodo?: string | null;
  recolhido_em?: string | null;
  gerado_em?: string | null;
  classificadores?: { codigo: string; etiqueta: string }[];
  diagnostico?: {
    municipios?: number;
    com_despesas?: number;
    com_contratos?: number;
    adjudicantes_reconhecidos?: number;
    adjudicantes_nao_atribuidos?: number;
    valor_nao_atribuido?: number;
    sem_distrito?: number;
    exemplos_nao_atribuidos?: string[];
  } | null;
  indice?: {
    index?: string;
    documents?: number;
    total_despesas?: number;
    total_contratos?: number;
    sem_despesas?: number;
    por_distrito?: { key: string; count: number }[];
    error?: string;
  } | null;
};

export type MunicipiosMapaResposta = {
  total: number;
  items: MunicipioDespesas[];
};

/* ------------------------------------------------------------------ pedidos */

type Params = Record<string, string | number | boolean | undefined | null>;

function queryString(params: Params): string {
  const search = new URLSearchParams();
  for (const [chave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    search.set(chave, String(valor));
  }
  const texto = search.toString();
  return texto ? `?${texto}` : "";
}

async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detalhe = await res.text().catch(() => "");
    throw new Error(`${res.status} — ${detalhe || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function getMunicipiosDespesas(params?: {
  q?: string;
  distrito?: string;
  nuts?: string;
  ano?: number;
  /** Ano do Portal BASE: a lista mostra e ordena a contratação desse ano. */
  ano_contratos?: number;
  ordenar?: string;
  ordem?: "asc" | "desc";
  min_despesas?: number;
  page?: number;
  size?: number;
}): Promise<MunicipiosDespesasResponse> {
  return pedir<MunicipiosDespesasResponse>(
    `/municipios/despesas${queryString({ ...(params ?? {}) })}`,
  );
}

export function getMunicipiosDespesasMeta(): Promise<MunicipiosDespesasMeta> {
  return pedir<MunicipiosDespesasMeta>("/municipios/despesas/meta");
}

export function getMunicipiosDespesasMapa(): Promise<MunicipiosMapaResposta> {
  return pedir<MunicipiosMapaResposta>("/municipios/despesas/mapa");
}

export function getMunicipioFicha(municipio: string): Promise<MunicipioFicha> {
  return pedir<MunicipioFicha>(`/municipios/despesas/${encodeURIComponent(municipio)}`);
}

export function recolherMunicipiosDespesas(forcar = false): Promise<{
  recolhido_em: string;
  indexacao: { indexed: number; errors?: number; error?: string };
  diagnostico: Record<string, unknown>;
}> {
  return pedir(`/municipios/despesas/recolher${queryString({ forcar })}`, { method: "POST" });
}

/* ------------------------------------------------------------------ formato */

/** Euros compactos para as tabelas («1 016,3 M €»). */
export function euroCompacto(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} mil M €`;
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M €`;
  if (abs >= 1_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} mil €`;
  return `${valor.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

export function euroExato(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return `${valor.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

export function numero(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT");
}
