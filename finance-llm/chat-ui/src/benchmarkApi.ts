/**
 * Cliente do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).
 *
 * O backend responde com preço de referência do segmento (CPV + anos), a lista
 * de concorrentes, o historial de contrapartes da empresa e as oportunidades
 * (contrapartes com que a empresa nunca contratou). Tudo em euros.
 */
import { API_BASE } from "./api";

export type BenchmarkRole = "adjudicatario" | "adjudicante";

/** País dos dados: `all` é o quadro conjunto (por CPV). */
export type BenchmarkCountry = "pt" | "es" | "fr";
export type BenchmarkScope = BenchmarkCountry | "all";

export interface BenchmarkCountryInfo {
  country: BenchmarkCountry;
  label: string;
  short: string;
  index: string;
  total: number;
  years: number[];
  roles: string[];
  role_labels?: Record<string, string>;
}

export interface BenchmarkMetaAll {
  country: BenchmarkScope;
  label: string;
  total: number;
  years: number[];
  roles: string[];
  countries: BenchmarkCountryInfo[];
  error?: string;
}

export interface BenchmarkMeta {
  total: number;
  years: number[];
  roles?: string[];
  error?: string;
}

export interface BenchmarkCpv {
  code: string;
  description: string;
  count: number;
  value?: number | null;
}

export interface BenchmarkCpvResponse {
  query?: string | null;
  items: BenchmarkCpv[];
  error?: string;
}

export interface BenchmarkRow {
  nif: string;
  name: string;
  count: number;
  value?: number | null;
  last_date?: string | null;
  rank?: number;
  share_pct?: number | null;
  why?: string;
}

export interface BenchmarkByYear {
  year: string;
  count: number;
  value: number;
}

export interface BenchmarkRecentContract {
  idcontrato?: string | null;
  objecto?: string | null;
  value?: number | null;
  date?: string | null;
  counterpart?: string | null;
}

export interface BenchmarkEntityStats {
  nif?: string | null;
  name: string;
  contracts: number;
  total_value: number;
  avg_value?: number | null;
  median_value?: number | null;
  last_date?: string | null;
  rank?: number | null;
  share_pct?: number | null;
  count_share_pct?: number | null;
  price_index?: number | null;
  /** `false` quando a entidade não tem contratos nesse papel no segmento. */
  present?: boolean;
  by_year: BenchmarkByYear[];
  top_cpv: BenchmarkCpv[];
  recent: BenchmarkRecentContract[];
}

export interface BenchmarkReference {
  scope: string;
  contracts: number;
  total_value: number;
  avg?: number | null;
  median?: number | null;
  p10?: number | null;
  p25?: number | null;
  p75?: number | null;
  p90?: number | null;
  min?: number | null;
  max?: number | null;
}

export interface BenchmarkResponse {
  role: BenchmarkRole;
  entity: BenchmarkEntityStats;
  reference: BenchmarkReference;
  market: { contracts: number; peers: number; counterparts: number };
  competitors: BenchmarkRow[];
  counterparties: BenchmarkRow[];
  history: BenchmarkRow[];
  opportunities: BenchmarkRow[];
  notes: string[];
  error?: string;
}

export interface BenchmarkQuery {
  nif?: string;
  name?: string;
  role?: BenchmarkRole;
  country?: BenchmarkCountry;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  top?: number;
}

/** Volumetria do índice de contratos e anos disponíveis. */
export async function getBenchmarkMeta(country: BenchmarkScope = "pt"): Promise<BenchmarkMetaAll> {
  const res = await fetch(`${API_BASE}/benchmark/meta?country=${country}`);
  if (!res.ok) throw new Error(`Erro ao obter o estado do benchmark: ${res.status}`);
  return res.json();
}

/** CPV mais usados no país (para escolher o segmento). */
export async function getBenchmarkCpv(
  q?: string,
  size = 20,
  country: BenchmarkCountry = "pt",
): Promise<BenchmarkCpvResponse> {
  const params = new URLSearchParams({ size: String(size), country });
  if (q) params.set("q", q);
  const res = await fetch(`${API_BASE}/benchmark/cpv?${params}`);
  if (!res.ok) throw new Error(`Erro ao obter CPV: ${res.status}`);
  return res.json();
}

/** Benchmark de preços, concorrência, historial e oportunidades. */
export async function getBenchmarkEntity(params: BenchmarkQuery): Promise<BenchmarkResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/entity?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no benchmark: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------------------------ comparação */

/** Máximo de empresas comparáveis de uma vez (igual ao limite do servidor). */
export const MAX_COMPARE = 10;

export interface BenchmarkCompareEntity {
  nif?: string;
  name?: string;
}

export interface BenchmarkCompareRequest {
  entities: BenchmarkCompareEntity[];
  role?: BenchmarkRole;
  country?: BenchmarkCountry;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  top?: number;
}

export interface BenchmarkCompareRow {
  nif?: string | null;
  name: string;
  contracts: number;
  total_value: number;
  avg_value?: number | null;
  median_value?: number | null;
  p25?: number | null;
  p75?: number | null;
  share_pct?: number | null;
  count_share_pct?: number | null;
  rank?: number | null;
  price_index?: number | null;
  /** `abaixo` | `na linha` | `acima` do preço de referência do mercado. */
  price_position?: string | null;
  last_date?: string | null;
  present?: boolean;
  /** Posição na tabela (1 = maior valor no segmento). */
  order?: number;
  /** CPV em que a empresa atua dentro do segmento (maiores primeiro). */
  top_cpv: BenchmarkCpv[];
  /** Contrapartes da empresa no segmento (quem lhe compra, se vende). */
  buyers: BenchmarkRow[];
  /** Contrapartes distintas da empresa no segmento. */
  buyers_total?: number;
}

/** Contraparte que compra a duas ou mais das empresas comparadas. */
export interface BenchmarkSharedBuyer {
  nif: string;
  name: string;
  companies: string[];
  companies_total: number;
  value: number;
}

/** CPV em que atuam duas ou mais das empresas comparadas. */
export interface BenchmarkSharedCpv {
  code: string;
  description: string;
  companies: string[];
  companies_total: number;
  value: number;
  count: number;
}

export interface BenchmarkCompareResponse {
  role: BenchmarkRole;
  country?: BenchmarkCountry;
  country_label?: string;
  reference: {
    scope: string;
    contracts: number;
    total_value: number;
    avg?: number | null;
    median?: number | null;
    p25?: number | null;
    p75?: number | null;
  };
  market: { contracts: number; peers: number };
  /** Papel das contrapartes: `adjudicante` (quem compra) ou `adjudicatario`. */
  counterpart_role?: BenchmarkRole;
  entities: BenchmarkCompareRow[];
  ranking: (BenchmarkRow & { selected?: boolean; label?: string | null })[];
  /** Contrapartes comuns a duas ou mais empresas comparadas. */
  shared_buyers: BenchmarkSharedBuyer[];
  /** CPV em que atuam duas ou mais empresas comparadas. */
  shared_cpvs: BenchmarkSharedCpv[];
  notes: string[];
  error?: string;
}

/** Compara até 10 empresas no mesmo segmento (papel + CPV + anos). */
export async function compareBenchmarkEntities(
  payload: BenchmarkCompareRequest,
): Promise<BenchmarkCompareResponse> {
  const res = await fetch(`${API_BASE}/benchmark/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro na comparação: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------- quadro conjunto, por CPV */

/** Parcela de um CPV num país (contratos, valor e mediana). */
export interface BenchmarkByCpvCell {
  contracts: number;
  value?: number | null;
  median?: number | null;
}

export interface BenchmarkByCpvRow {
  rank: number;
  code: string;
  description: string;
  example: string;
  contracts: number;
  value: number;
  by_country: Record<string, BenchmarkByCpvCell>;
}

export interface BenchmarkByCpvResponse {
  countries: {
    country: BenchmarkCountry;
    label: string;
    short: string;
    index: string;
    contracts: number;
    priced_contracts: number;
    total_value: number;
    median?: number | null;
  }[];
  cpv_filter?: string | null;
  items: BenchmarkByCpvRow[];
  notes: string[];
  error?: string;
}

/** Quadro por CPV com o volume e o preço de cada país (página conjunta). */
export async function getBenchmarkByCpv(params: {
  countries?: BenchmarkCountry[];
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  top?: number;
} = {}): Promise<BenchmarkByCpvResponse> {
  const search = new URLSearchParams();
  if (params.countries?.length) search.set("countries", params.countries.join(","));
  if (params.cpv_code) search.set("cpv_code", params.cpv_code);
  if (params.year_from !== undefined) search.set("year_from", String(params.year_from));
  if (params.year_to !== undefined) search.set("year_to", String(params.year_to));
  if (params.top !== undefined) search.set("top", String(params.top));
  const res = await fetch(`${API_BASE}/benchmark/by-cpv?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no quadro por CPV: ${res.status}`);
  }
  return res.json();
}

/** Pesquisa de entidades por país (para o seletor, conforme o papel).
 *
 * Usa o próprio módulo do benchmark (`/benchmark/entities`): assim os três
 * países respondem na mesma forma — e em França, onde o DECP não traz nomes, a
 * pesquisa é por SIRET (o campo `name` devolve o identificador).
 */
export async function searchBenchmarkEntities(
  country: BenchmarkCountry,
  role: BenchmarkRole,
  q: string,
  size = 8,
): Promise<{ nif: string; name: string; contracts: number; total_value?: number | null }[]> {
  const params = new URLSearchParams({ q, role, country, size: String(size) });
  const res = await fetch(`${API_BASE}/benchmark/entities?${params}`);
  if (!res.ok) throw new Error(`Erro ao procurar entidades: ${res.status}`);
  const dados: { items?: { nif?: string; name?: string; contracts?: number; total_value?: number | null }[] } =
    await res.json();
  return (dados.items ?? []).map((item) => ({
    nif: item.nif ?? "",
    name: item.name ?? item.nif ?? "",
    contracts: item.contracts ?? 0,
    total_value: item.total_value ?? null,
  }));
}

/* ------------------------------------------------- empresas e os seus CPV */

/** CPV onde uma entidade atua (com volume e valor). */
export interface BenchmarkEntityCpv {
  code: string;
  description?: string | null;
  count: number;
  value?: number | null;
  median?: number | null;
}

export interface BenchmarkByEntityCountry {
  country: BenchmarkCountry;
  label: string;
  short: string;
  index?: string;
  contracts?: number;
  total_value?: number | null;
  entities?: number;
  error?: string;
}

export interface BenchmarkByEntityRow {
  country: BenchmarkCountry;
  country_label: string;
  short: string;
  rank?: number | null;
  nif: string;
  name: string;
  contracts: number;
  value?: number | null;
  share_pct?: number | null;
  last_date?: string | null;
  cpvs: BenchmarkEntityCpv[];
}

export interface BenchmarkByEntityResponse {
  country: BenchmarkScope;
  role: BenchmarkRole;
  countries: BenchmarkByEntityCountry[];
  items: BenchmarkByEntityRow[];
  notes: string[];
  error?: string;
}

/** Empresas (ou compradores) de cada país, com os CPV onde cada uma atua. */
export async function getBenchmarkByEntity(
  params: {
    countries?: BenchmarkCountry[];
    role?: BenchmarkRole;
    cpv_code?: string;
    year_from?: number;
    year_to?: number;
    size?: number;
    cpv_size?: number;
  } = {},
): Promise<BenchmarkByEntityResponse> {
  const search = new URLSearchParams();
  if (params.countries?.length) search.set("countries", params.countries.join(","));
  if (params.role) search.set("role", params.role);
  if (params.cpv_code) search.set("cpv_code", params.cpv_code);
  if (params.year_from !== undefined) search.set("year_from", String(params.year_from));
  if (params.year_to !== undefined) search.set("year_to", String(params.year_to));
  if (params.size !== undefined) search.set("size", String(params.size));
  if (params.cpv_size !== undefined) search.set("cpv_size", String(params.cpv_size));
  const res = await fetch(`${API_BASE}/benchmark/by-entity?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no quadro de empresas: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------- cruzar empresas de países diferentes */

/** Máximo de empresas cruzadas de uma vez (igual ao limite do servidor). */
export const MAX_CROSS = 6;

export interface BenchmarkCrossEntity {
  /** País dos dados da empresa (cada empresa pode vir de um país diferente). */
  country: BenchmarkCountry;
  nif?: string;
  name?: string;
}

export interface BenchmarkCrossRequest {
  entities: BenchmarkCrossEntity[];
  role?: BenchmarkRole;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  top?: number;
}

/** Uma empresa no cruzamento (com o preço comparado ao seu próprio mercado). */
export interface BenchmarkCrossCompany {
  country: BenchmarkCountry;
  country_label: string;
  short: string;
  nif?: string | null;
  name: string;
  present: boolean;
  contracts: number;
  total_value: number;
  median?: number | null;
  price_index?: number | null;
  rank?: number | null;
  share_pct?: number | null;
  market: { contracts: number; median?: number | null; label: string };
  cpvs: BenchmarkCpv[];
  counterparties: BenchmarkRow[];
  recent?: BenchmarkRecentContract[];
  error?: string;
}

/** CPV (ou contraparte) onde pelo menos duas das empresas cruzadas coincidem. */
export interface BenchmarkCrossShared {
  code?: string;
  description?: string | null;
  nif?: string;
  name?: string;
  companies: { nif?: string | null; name: string; short: string; count: number; value?: number | null }[];
  companies_count: number;
  contracts: number;
  value: number;
}

export interface BenchmarkCrossResponse {
  role: BenchmarkRole;
  counterparty_label: string;
  cpv_filter?: string | null;
  companies: BenchmarkCrossCompany[];
  shared_cpvs: BenchmarkCrossShared[];
  shared_counterparties: BenchmarkCrossShared[];
  notes: string[];
  error?: string;
}

/** Cruza empresas de países diferentes: preços, CPV e contrapartes em comum. */
export async function compareBenchmarkCross(payload: BenchmarkCrossRequest): Promise<BenchmarkCrossResponse> {
  const res = await fetch(`${API_BASE}/benchmark/cross`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no cruzamento: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------- anomalias de preço e concentração */

export interface BenchmarkAnomalyItem {
  kind: string;
  severity: "alta" | "media" | "info" | string;
  title: string;
  detail: string;
  value?: number | null;
}

export interface BenchmarkAnomalyContract {
  value: number;
  times_p90?: number | null;
  object?: string | null;
  date?: string | null;
  counterpart?: string | null;
  id?: string | null;
}

export interface BenchmarkAnomalyCpv {
  code: string;
  description?: string | null;
  contracts: number;
  market_contracts: number;
  market_median?: number | null;
  entity_median?: number | null;
  ratio?: number | null;
  suppliers: number;
  share_pct?: number | null;
  competition_verdict: string;
  price_verdict: string;
}

export interface BenchmarkAnomaliesResponse {
  role: BenchmarkRole;
  country: BenchmarkCountry;
  country_label: string;
  entity: {
    nif?: string | null;
    name: string;
    contracts: number;
    total_value: number;
    median?: number | null;
    p90?: number | null;
    share_of_segment_pct?: number | null;
  };
  reference: { contracts: number; median?: number | null; p90?: number | null };
  items: BenchmarkAnomalyItem[];
  outliers: BenchmarkAnomalyContract[];
  by_cpv: BenchmarkAnomalyCpv[];
  data_quality: { excluded_contracts: number; excluded_value?: number | null };
  notes: string[];
  error?: string;
}

/** Anomalias de preço e concentração de uma entidade no seu segmento. */
export async function getBenchmarkAnomalies(params: BenchmarkQuery & { top_cpvs?: number }): Promise<BenchmarkAnomaliesResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/anomalies?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro nas anomalias: ${res.status}`);
  }
  return res.json();
}

/* -------------------------------- oportunidades (CPV dos compradores) */

export interface BenchmarkGapRow {
  code: string;
  description?: string | null;
  contracts: number;
  value: number;
  median?: number | null;
  buyers: BenchmarkRow[];
  buyers_total: number;
  competition: BenchmarkRow[];
}

export interface BenchmarkGapsResponse {
  role: BenchmarkRole;
  country: BenchmarkCountry;
  country_label: string;
  entity: { nif?: string | null; name: string; cpvs_known: number };
  buyers: BenchmarkRow[];
  gaps: BenchmarkGapRow[];
  notes: string[];
  error?: string;
}

/** Onde a entidade pode vender mais: CPV dos seus compradores que ela não serve. */
export async function getBenchmarkGaps(
  params: BenchmarkQuery & { top_buyers?: number; size?: number },
): Promise<BenchmarkGapsResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/gaps?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro nas oportunidades: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------- grafo do comprador (fornecedores) */

export interface BenchmarkBuyerSupplier {
  nif: string;
  name: string;
  contracts: number;
  value: number;
  share_pct?: number | null;
  price_index?: number | null;
  median?: number | null;
  client_count: number;
  dependency_pct?: number | null;
  cpvs_here: number;
  cpvs_market: number;
  last_date?: string | null;
  status: string;
  strengths: string[];
  weaknesses: string[];
  score: number;
  rank?: number | null;
  market_value?: number | null;
}

export interface BenchmarkBuyerClient {
  nif: string;
  name: string;
  contracts: number;
  value?: number | null;
  share_pct?: number | null;
}

export interface BenchmarkBuyerRegion {
  code: string;
  contracts: number;
  value: number;
}

export interface BenchmarkOntology {
  perspectiva?: BenchmarkPerspectiva;
  object_types: { id: string; label: string; shape: string; fields: string[] }[];
  link_types: { id: string; label: string; from: string; to: string; weight: string; fields: string[] }[];
}

/** De que lado se lê o grafo: quem compra ou quem vende. */
export type BenchmarkPerspectiva = "comprador" | "vendedor";

/**
 * Rótulos dos elementos do grafo.
 *
 * O grafo é o mesmo desenho nas duas páginas (comprador e vendedor): aqui diz-se
 * o que é o nó central, o primeiro anel (`ring1`) e o segundo (`ring2`), e como
 * se chamam as métricas. No grafo do vendedor, `suppliers` são os **compradores**
 * e `clients` são os **concorrentes**.
 */
export interface BenchmarkGraphLabels {
  entity: string;
  ring1: string;
  ring2: string;
  ring1_one: string;
  ring2_one: string;
  share: string;
  dependency: string;
  count: string;
  counterpart: string;
  price: string;
  ring2_hint: string;
  regions_hint: string;
}

export interface BenchmarkBuyerGraphResponse {
  perspectiva?: BenchmarkPerspectiva;
  labels?: BenchmarkGraphLabels;
  role: BenchmarkRole;
  country: BenchmarkCountry;
  country_label: string;
  segment: { cpv_code?: string | null; year_from?: number | null; year_to?: number | null; region?: string | null };
  buyer: {
    nif?: string | null;
    name: string;
    contracts: number;
    total_value?: number | null;
    median?: number | null;
    share_pct?: number | null;
    market_median?: number | null;
    market_p90?: number | null;
    top_cpv: BenchmarkCpv[];
  };
  reference: BenchmarkReference;
  suppliers: BenchmarkBuyerSupplier[];
  alternatives: { nif?: string | null; name: string; contracts: number; value?: number | null; share_pct?: number | null }[];
  clients: BenchmarkBuyerClient[];
  regions: BenchmarkBuyerRegion[];
  ontology: BenchmarkOntology;
  notes: string[];
  error?: string;
}

/** Grafo do comprador: fornecedores (forças/fraquezas), clientes comuns e regiões. */
export async function getBenchmarkBuyerGraph(
  params: BenchmarkQuery & { top_suppliers?: number; top_clients?: number },
): Promise<BenchmarkBuyerGraphResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/buyer-graph?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no grafo do comprador: ${res.status}`);
  }
  return res.json();
}

/**
 * Grafo do **vendedor**: a quem vendo, com quem disputo e onde vendo.
 *
 * Mesma forma de resposta do grafo do comprador (e por isso as duas páginas
 * partilham o desenho): o nó central é o vendedor, `suppliers` são os seus
 * **compradores** e `clients` são os **concorrentes** que vendem aos mesmos
 * compradores.
 */
export async function getBenchmarkSellerGraph(
  params: BenchmarkQuery & { top_buyers?: number; top_competitors?: number },
): Promise<BenchmarkBuyerGraphResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/seller-graph?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no grafo do vendedor: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------ preço por CPV e ano (eu vs concorrência) */

export interface BenchmarkPriceRiskYear {
  year: string;
  entity_contracts: number;
  entity_avg?: number | null;
  market_contracts: number;
  market_avg?: number | null;
  ratio?: number | null;
  risk: string;
}

export interface BenchmarkPriceRiskCpv {
  code: string;
  description?: string | null;
  contracts: number;
  value: number;
  avg?: number | null;
  median?: number | null;
  market_contracts: number;
  market_value: number;
  market_avg?: number | null;
  market_median?: number | null;
  ratio?: number | null;
  ratio_median?: number | null;
  share_pct?: number | null;
  suppliers: number;
  competitors: BenchmarkRow[];
  years: BenchmarkPriceRiskYear[];
  risk: string;
  risk_reason: string;
}

export interface BenchmarkPriceRiskResponse {
  role: BenchmarkRole;
  country: BenchmarkCountry;
  country_label: string;
  segment: { cpv_code?: string | null; year_from?: number | null; year_to?: number | null; region?: string | null };
  entity: { nif?: string | null; name: string; contracts: number; total_value: number; avg?: number | null };
  reference: { scope: string; contracts: number; avg?: number | null; median?: number | null };
  items: BenchmarkPriceRiskCpv[];
  summary: { risk_level: string; items: BenchmarkAnomalyItem[] };
  notes: string[];
  error?: string;
}

/** Preço por CPV e ano face à média do mercado, com risco explicado. */
export async function getBenchmarkPriceRisk(
  params: BenchmarkQuery & { top_cpvs?: number; top_years?: number },
): Promise<BenchmarkPriceRiskResponse> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const res = await fetch(`${API_BASE}/benchmark/price-risk?${search}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Erro no risco de preço: ${res.status}`);
  }
  return res.json();
}

/* ------------------------------------------------ relatório PDF (pago) */
/** Âmbito do relatório: uma empresa, o quadro por CPV ou o cruzamento. */
export type BenchmarkReportMode = "empresa" | "mercado" | "cruzar";

export interface BenchmarkReportParams {
  mode: BenchmarkReportMode;
  country?: BenchmarkCountry;
  nif?: string;
  name?: string;
  role?: BenchmarkRole;
  cpv_code?: string;
  year_from?: number;
  year_to?: number;
  region?: string;
  countries?: BenchmarkCountry[];
  top?: number;
  entities?: { country: BenchmarkCountry; nif?: string; name?: string }[];
  notes?: string;
}

export interface BenchmarkReportOrder {
  id: string;
  reference: string;
  status: string;
  package_title: string;
  amounts: { subtotal: number; vat: number; total: number; vat_rate?: number };
  payment: { method: string; status: string; mbway_phone?: string; provider_request_id?: string };
  files: { id: string; name: string; size: number; uploaded_at: string }[];
  history?: { id: string; message: string; at: string }[];
  targets_label?: string;
}

export interface BenchmarkReportResponse {
  request: BenchmarkReportOrder;
  package: { id: string; title: string; price: number; delivery_days?: number; features?: string[] };
  report: { mode: BenchmarkReportMode; title: string; subtitle: string };
  settings: { mbway_number: string; mbway_enabled: boolean; mbway_api: boolean; payment_instructions: string };
  automatic: { ok: boolean; configured: boolean; message?: string; request_id?: string };
}

/** Pede o relatório PDF do benchmark (preço definido no backoffice). */
export async function requestBenchmarkReport(
  payload: BenchmarkReportParams & { mbway_phone?: string },
): Promise<BenchmarkReportResponse> {
  const res = await fetch(`${API_BASE}/benchmark/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detalhe = `${res.status}`;
    try {
      const corpo = (await res.json()) as { detail?: string };
      if (corpo?.detail) detalhe = corpo.detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detalhe);
  }
  return res.json();
}
