/**
 * Cliente do módulo **Benchmarks de produtos** (`/benchmarks/*`).
 *
 * Um benchmark compara o mesmo produto em várias lojas: define-se o estudo
 * (lojas + seletores de recolha + chave de comparação), recolhem-se os preços e
 * comparam-se. Cada benchmark tem o **seu índice** no Elasticsearch e pode ser
 * publicado como página pública no site.
 */
import { API_BASE } from "./api";

export type BenchmarkMatchKey = "ean" | "sku" | "nome" | "url";
export type BenchmarkOrdem = "dispersao" | "poupanca" | "lojas" | "preco" | "nome";
export type BenchmarkOrdemOferta = "preco" | "preco_desc" | "recentes" | "nome" | "desconto";

/** Campos do benchmark que podem ser ligados a um campo extraído pela recolha. */
export interface BenchmarkFieldMap {
  price?: string;
  price_original?: string;
  product_name?: string;
  brand?: string;
  category?: string;
  ean?: string;
  sku?: string;
  url?: string;
  image?: string;
  availability?: string;
}

export interface BenchmarkScraper {
  fetcher?: string;
  list?: { selector?: string; type?: string };
  fields?: {
    name: string;
    label?: string;
    selector?: string;
    selectors?: string[];
    type?: string;
    attr?: string | null;
    all?: boolean;
    cast?: string;
    max_length?: number;
  }[];
  pagination?: { selector?: string; type?: string; attr?: string; max_pages?: number };
  options?: Record<string, unknown>;
  respect_robots?: boolean;
  id_fields?: string[];
}

export interface BenchmarkStore {
  id?: string;
  name: string;
  url: string;
  enabled?: boolean;
  source_id?: string | null;
  template_id?: string | null;
  scraper?: BenchmarkScraper | null;
  tags?: string[];
}

export interface BenchmarkStats {
  offers?: number;
  products?: number;
  stores?: number;
}

export interface BenchmarkLastRun {
  at?: string;
  offers?: number;
  indexed?: number;
  errors?: string[];
  stores?: {
    store_id?: string;
    store_name?: string;
    status?: string;
    items?: number;
    ofertas?: number;
    indexadas?: number;
    error?: string;
  }[];
}

export interface Benchmark {
  slug: string;
  name: string;
  description?: string;
  category?: string;
  unit?: string;
  currency?: string;
  tags?: string[];
  public?: boolean;
  active?: boolean;
  match_on?: BenchmarkMatchKey;
  field_map?: BenchmarkFieldMap;
  stores?: BenchmarkStore[];
  stats?: BenchmarkStats;
  last_run?: BenchmarkLastRun | null;
  cms_page_id?: string;
  public_path?: string;
  public_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface BenchmarkPayload {
  name: string;
  slug?: string;
  description?: string;
  category?: string;
  unit?: string;
  currency?: string;
  tags?: string[];
  match_on?: BenchmarkMatchKey;
  field_map?: BenchmarkFieldMap;
  stores: BenchmarkStore[];
}

export interface BenchmarkTemplateInfo {
  id: string;
  name: string;
  site?: string;
  category?: string;
  requires?: string;
}

/** Modelo de recolha já construído (seletores prontos a usar numa loja). */
export interface BenchmarkTemplateScraper {
  id?: string;
  name?: string;
  site?: string;
  description?: string;
  notes?: string;
  requires?: string;
  scraper?: BenchmarkScraper;
}

export interface BenchmarkMeta {
  match_keys: { id: BenchmarkMatchKey; label: string; hint: string }[];
  field_map_keys: string[];
  currencies: string[];
  templates: BenchmarkTemplateInfo[];
  total: number;
}

export interface BenchmarkOffer {
  _id?: string;
  product_key?: string;
  product_name?: string;
  brand?: string | null;
  category?: string | null;
  sku?: string | null;
  ean?: string | null;
  store_id?: string;
  store_name?: string;
  url?: string;
  image?: string | null;
  availability?: string | null;
  in_stock?: boolean;
  currency?: string;
  price?: number;
  price_original?: number | null;
  discount_pct?: number | null;
  collected_at?: string;
}

export interface BenchmarkOffersResponse {
  items: BenchmarkOffer[];
  total: number;
  index?: string;
  facets?: {
    lojas: { id: string; count: number }[];
    categorias: { id: string; count: number }[];
    disponibilidade: { id: string; count: number }[];
  };
  stats?: { preco_min?: number | null; preco_max?: number | null; preco_medio?: number | null };
  error?: string;
}

export interface BenchmarkComparison {
  product_key: string;
  product_name: string;
  brand?: string | null;
  offers: number;
  stores: number;
  price_min?: number | null;
  price_max?: number | null;
  price_avg?: number | null;
  spread_pct?: number | null;
  saving_abs?: number | null;
  best: BenchmarkOffer;
  all_offers: BenchmarkOffer[];
}

export interface BenchmarkComparisonResponse {
  items: BenchmarkComparison[];
  total: number;
  index?: string;
  order?: string;
  error?: string;
}

export interface BenchmarkStoreStat {
  store_id: string;
  store_name?: string;
  ofertas: number;
  produtos: number;
  em_stock?: number;
  preco_min?: number | null;
  preco_max?: number | null;
  preco_medio?: number | null;
  indice_preco?: number | null;
}

export interface BenchmarkAnalysis {
  benchmark: {
    slug?: string;
    name?: string;
    category?: string;
    currency?: string;
    match_on?: string;
    public?: boolean;
    public_path?: string;
    last_run?: BenchmarkLastRun | null;
    stores_defined?: number;
  };
  kpis: {
    stores: number;
    offers: number;
    products: number;
    comparable_products: number;
    single_store_products: number;
    avg_spread_pct?: number | null;
    max_spread_pct?: number | null;
    potential_saving_eur?: number | null;
    avg_price?: number | null;
  };
  stores: BenchmarkStoreStat[];
  opportunities: BenchmarkComparison[];
  exclusives: BenchmarkComparison[];
  error?: string;
}

export interface BenchmarkRecolhaResumo extends BenchmarkLastRun {
  slug: string;
  stores: NonNullable<BenchmarkLastRun["stores"]>;
  errors?: string[];
  error?: string;
}

export interface BenchmarkPublicacao {
  slug: string;
  public: boolean;
  page_id?: string;
  path?: string;
  url?: string;
  search_url?: string;
  error?: string;
}

export interface BenchmarkIndexInfo {
  items: Benchmark[];
  total: number;
  publicos: number;
  indexes: string[];
}

async function ler<T>(res: Response, contexto: string): Promise<T> {
  if (!res.ok) {
    let detalhe = `${res.status}`;
    try {
      const corpo = await res.json();
      detalhe = String((corpo as { detail?: string }).detail ?? detalhe);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(`${contexto}: ${detalhe}`);
  }
  return (await res.json()) as T;
}

export async function getBenchmarksMeta(): Promise<BenchmarkMeta> {
  return ler<BenchmarkMeta>(await fetch(`${API_BASE}/benchmarks/meta`), "Erro ao obter os metadados");
}

/** Seletores prontos de um modelo de recolha (para preencher uma loja). */
export async function getBenchmarkModelo(templateId: string): Promise<BenchmarkTemplateScraper> {
  return ler<BenchmarkTemplateScraper>(
    await fetch(`${API_BASE}/benchmarks/modelo/${encodeURIComponent(templateId)}`),
    "Erro ao obter o modelo de recolha",
  );
}

export async function listarBenchmarks(): Promise<BenchmarkIndexInfo> {
  return ler<BenchmarkIndexInfo>(await fetch(`${API_BASE}/benchmarks/lista`), "Erro ao listar benchmarks");
}

export async function obterBenchmark(slug: string): Promise<Benchmark> {
  return ler<Benchmark>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}`),
    "Erro ao obter o benchmark",
  );
}

export async function criarBenchmark(payload: BenchmarkPayload): Promise<Benchmark> {
  return ler<Benchmark>(
    await fetch(`${API_BASE}/benchmarks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "Erro ao criar o benchmark",
  );
}

export async function editarBenchmark(slug: string, payload: BenchmarkPayload): Promise<Benchmark> {
  return ler<Benchmark>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "Erro ao guardar o benchmark",
  );
}

export async function apagarBenchmark(slug: string, comDados = true): Promise<{ slug: string; removed: boolean }> {
  return ler(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}?com_dados=${comDados ? "true" : "false"}`, {
      method: "DELETE",
    }),
    "Erro ao apagar o benchmark",
  );
}

export async function recolherBenchmark(
  slug: string,
  opcoes: { stores?: string[]; limite_por_loja?: number } = {},
): Promise<BenchmarkRecolhaResumo> {
  return ler<BenchmarkRecolhaResumo>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/recolher`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stores: opcoes.stores ?? [], limite_por_loja: opcoes.limite_por_loja ?? 500 }),
    }),
    "Erro na recolha",
  );
}

export async function obterOfertas(
  slug: string,
  params: { q?: string; loja?: string; ordem?: BenchmarkOrdemOferta; size?: number; from?: number } = {},
): Promise<BenchmarkOffersResponse> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.loja) search.set("loja", params.loja);
  if (params.ordem) search.set("ordem", params.ordem);
  search.set("size", String(params.size ?? 50));
  if (params.from) search.set("from", String(params.from));
  return ler<BenchmarkOffersResponse>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/ofertas?${search}`),
    "Erro ao obter as ofertas",
  );
}

export async function obterComparacao(
  slug: string,
  params: { q?: string; loja?: string; ordem?: BenchmarkOrdem; min_lojas?: number; size?: number; from?: number } = {},
): Promise<BenchmarkComparisonResponse> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.loja) search.set("loja", params.loja);
  if (params.ordem) search.set("ordem", params.ordem);
  search.set("min_lojas", String(params.min_lojas ?? 2));
  search.set("size", String(params.size ?? 50));
  if (params.from) search.set("from", String(params.from));
  return ler<BenchmarkComparisonResponse>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/comparacao?${search}`),
    "Erro ao comparar",
  );
}

export async function obterAnalise(slug: string): Promise<BenchmarkAnalysis> {
  return ler<BenchmarkAnalysis>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/analise`),
    "Erro na análise",
  );
}

export async function publicarBenchmark(slug: string): Promise<BenchmarkPublicacao> {
  return ler<BenchmarkPublicacao>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/publicar`, { method: "POST" }),
    "Erro ao publicar",
  );
}

export async function despublicarBenchmark(slug: string): Promise<BenchmarkPublicacao> {
  return ler<BenchmarkPublicacao>(
    await fetch(`${API_BASE}/benchmarks/${encodeURIComponent(slug)}/publicar`, { method: "DELETE" }),
    "Erro ao retirar do site",
  );
}

/** Benchmarks publicados (sem sessão) — usado pelo site e pelo menu. */
export async function listarBenchmarksPublicos(): Promise<{
  items: { slug: string; name: string; description?: string; path?: string; url?: string; search_url?: string; stats?: BenchmarkStats }[];
  total: number;
}> {
  return ler(await fetch(`${API_BASE}/benchmarks/publico/lista`), "Erro ao listar os benchmarks públicos");
}
