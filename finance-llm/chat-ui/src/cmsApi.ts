/**
 * Cliente do CMS IQ OS (`/cms/*`) e do site público (`/site/*`).
 *
 * O CMS trata de **páginas** (por blocos), **conteúdos** reutilizáveis,
 * **artigos de blog** com taxonomia, **media**, **modelos**, **menus** e
 * **aparência** — com publicação imediata ou agendada, revisões e auditoria.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------ tipos */

export type CmsStatus = "rascunho" | "agendado" | "publicado" | "arquivado";

export type CmsBlock = {
  id: string;
  type: string;
  hidden?: boolean;
  data: Record<string, unknown>;
};

export type CmsSeo = {
  title?: string;
  description?: string;
  keywords?: string[];
  image_id?: string | null;
  noindex?: boolean;
};

export type CmsPage = {
  id: string;
  title: string;
  slug: string;
  path: string;
  parent_id?: string | null;
  template?: string;
  status: CmsStatus;
  published_at?: string | null;
  scheduled_at?: string | null;
  show_in_menu?: boolean;
  menu_order?: number;
  menu_label?: string;
  excerpt?: string;
  blocks: CmsBlock[];
  seo?: CmsSeo;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
  blocks_count?: number;
};

export type CmsPost = {
  id: string;
  title: string;
  slug: string;
  excerpt?: string;
  markdown?: string;
  blocks: CmsBlock[];
  cover_id?: string | null;
  category_ids: string[];
  tags: string[];
  author?: string;
  status: CmsStatus;
  published_at?: string | null;
  scheduled_at?: string | null;
  featured?: boolean;
  /** O artigo tem relatório em PDF descarregável (`/site/blog/{slug}/pdf`). */
  report_pdf?: boolean;
  reading_minutes?: number;
  markdown_words?: number;
  has_markdown?: boolean;
  seo?: CmsSeo;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
};

export type CmsContent = {
  id: string;
  title: string;
  kind: string;
  body: string;
  data: Record<string, string>;
  tags: string[];
  notes?: string;
  uses?: number;
  preview?: string;
  created_at?: string;
  updated_at?: string;
};

export type CmsMedia = {
  id: string;
  title: string;
  filename: string;
  mime: string;
  extension?: string;
  size: number;
  storage: "ficheiro" | "externo";
  url: string;
  kind: "imagem" | "documento";
  alt?: string;
  caption?: string;
  credit?: string;
  tags: string[];
  created_at?: string;
  updated_at?: string;
};

export type CmsCategory = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  parent_id?: string | null;
  color?: string;
  posts?: number;
  created_at?: string;
  updated_at?: string;
};

export type CmsTemplate = {
  id: string;
  name: string;
  kind: "page" | "post";
  description?: string;
  blocks: CmsBlock[];
  builtin?: boolean;
  created_at?: string;
  updated_at?: string;
};

/** Dados oficiais de um município, guardados na ficha (INE + Portal BASE). */
export type CmsMunicipioDados = {
  municipio?: string;
  geocod?: string | null;
  geocod_curto?: string | null;
  distrito?: string | null;
  nuts?: string | null;
  nuts_nome?: string | null;
  ano_despesas?: number | null;
  anos_despesas?: string[];
  /** Série anual da despesa total (o INE publica um ano de cada vez). */
  serie_despesas?: { ano: string; total: number }[];
  por_classificador?: { codigo: string; etiqueta: string; valor: number }[];
  despesas_total?: number;
  despesas_correntes?: number;
  despesas_capital?: number;
  despesas_pessoal?: number;
  despesas_bens_servicos?: number;
  contratos?: {
    total?: number;
    valor?: number;
    primeiro_ano?: number | null;
    ultimo_ano?: number | null;
    /** Ano → contratos e valor (a série do Portal BASE). */
    por_ano?: Record<string, { contratos: number; valor: number }>;
    fornecedores?: { nome: string; contratos: number; valor: number }[];
    adjudicantes?: string[];
  };
  recolhido_em?: string | null;
  fontes?: { documento?: string | null; url?: string | null }[];
  error?: string;
};

/** Ficha pública de um município (entidade `municipios` do CMS). */
export type CmsMunicipio = {
  id: string;
  title: string;
  slug: string;
  municipio: string;
  geocod?: string | null;
  status: CmsStatus;
  published_at?: string | null;
  scheduled_at?: string | null;
  excerpt?: string;
  blocks: CmsBlock[];
  dados?: CmsMunicipioDados | null;
  seo?: CmsSeo;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
  blocks_count?: number;
};

/** Um município que se pode publicar, com a ficha que já existe (se existir). */
export type CmsMunicipioOpcao = {
  municipio: string;
  geocod?: string | null;
  distrito?: string | null;
  nuts_nome?: string | null;
  ano_despesas?: number | null;
  despesas_total?: number;
  ficha_id?: string | null;
  ficha_status?: CmsStatus | null;
};

/** Rascunho escrito pela IA a partir dos números da ficha. */
export type CmsMunicipioTexto = {
  ok: boolean;
  titulo: string;
  resumo: string;
  corpo: string;
  municipio?: string;
  resumo_dos_dados?: string;
  ai?: { provider?: string; provider_label?: string; model?: string };
  error?: string;
};

/** Filtros de uma pesquisa sobre as despesas municipais (ficam guardados na página). */
export type CmsPesquisaFiltros = {
  q?: string;
  distrito?: string;
  nuts?: string;
  ano_contratos?: number | null;
  ordenar?: string;
  ordem?: "asc" | "desc";
  min_despesas?: number | null;
  limite?: number;
};

/** Uma linha da tabela de uma pesquisa. */
export type CmsPesquisaLinha = {
  nome?: string;
  geocod?: string | null;
  distrito?: string | null;
  ano_despesas?: number | null;
  despesas_total?: number | null;
  despesas_pessoal?: number | null;
  contratos_total?: number | null;
  contratos_valor?: number | null;
  contratos_ano_total?: number | null;
  contratos_ano_valor?: number | null;
  anos_recentes?: { ano: string; contratos: number; valor: number }[];
};

/** Uma barra de um gráfico da página (`graficos`). */
export type CmsPesquisaBarra = {
  rotulo: string;
  valor: number;
  /** O número que acompanha a barra (contratos, quando a barra é um valor). */
  nota?: string | null;
  contratos?: number | null;
};

/** Uma série desenhada na página (municípios do topo, contratado/despesa por ano). */
export type CmsPesquisaGrafico = {
  id: string;
  titulo: string;
  subtitulo?: string;
  unidade?: "euros" | "contratos";
  itens: CmsPesquisaBarra[];
};

/** Os maiores adjudicatários do filtro (lidos do índice dos contratos). */
export type CmsPesquisaAdjudicatarios = {
  ano?: number | null;
  total?: number;
  valor?: number;
  municipios?: number;
  itens?: { nome: string; contratos: number; valor: number }[];
  error?: string;
};

/** A fotografia que a página mostra (lida quando o editor a mandou ler). */
export type CmsPesquisaDados = {
  filtros?: CmsPesquisaFiltros;
  descricao?: string;
  total?: number;
  linhas?: number;
  itens?: CmsPesquisaLinha[];
  ano_contratos?: number | null;
  ano_despesas?: number | null;
  despesas_somadas?: number;
  contratos_somados?: number;
  contratos_ano_somados?: number;
  contratos_ano_total_somados?: number;
  distritos?: { key: string; count: number }[];
  graficos?: CmsPesquisaGrafico[];
  adjudicatarios?: CmsPesquisaAdjudicatarios | null;
  origem?: string;
  gerado_em?: string | null;
  fontes?: { documento?: string | null; url?: string | null }[];
  error?: string;
};

/** Página pública de uma pesquisa (entidade `pesquisas` do CMS). */
export type CmsPesquisa = {
  id: string;
  title: string;
  slug: string;
  status: CmsStatus;
  published_at?: string | null;
  scheduled_at?: string | null;
  excerpt?: string;
  /** Frase legível dos filtros («distrito do Porto, contratação de 2024…»). */
  descricao_filtros?: string;
  filtros?: CmsPesquisaFiltros;
  /** Texto de entrada (Markdown), por cima dos números. */
  intro?: string;
  blocks: CmsBlock[];
  dados?: CmsPesquisaDados | null;
  /** Marca da página: imagem de capa, logótipo e cor de destaque. */
  capa_id?: string | null;
  logo_id?: string | null;
  cor?: string;
  seo?: CmsSeo;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
};

/** Filtros disponíveis para montar uma pesquisa. */
export type CmsPesquisaOpcoes = {
  distritos: string[];
  anos_contratos: string[];
  ordenacoes: { id: string; label: string }[];
  limite_maximo: number;
  ultimo_periodo?: string | null;
  ano_despesas?: string | null;
  fonte_despesas?: string | null;
  fonte_contratos?: string | null;
};

/* ------------------------------------------------------------------ remunerações da AP */

/** Uma linha da Tabela Remuneratória Única, como o CMS a guarda. */
export type CmsRemuneracaoNivel = { nivel: number; valor: number | null; nota?: string | null };

/** Uma posição remuneratória dentro de uma carreira. */
export type CmsRemuneracaoPosicao = {
  posicao: string;
  nivel?: number | null;
  niveis_texto?: string | null;
  remuneracao?: number | null;
};

/** Uma carreira/categoria com as suas posições. */
export type CmsRemuneracaoCarreira = {
  seccao?: string | null;
  carreira?: string;
  categoria?: string | null;
  variante?: string | null;
  minimo?: number | null;
  maximo?: number | null;
  posicoes?: CmsRemuneracaoPosicao[];
};

/** Um cargo dirigente. */
export type CmsRemuneracaoDirigente = {
  ambito?: string | null;
  grupo?: string | null;
  cargo?: string;
  indice?: number | null;
  niveis_texto?: string | null;
  remuneracao?: number | null;
};

/** A fotografia do quadro de um ano (lida quando o editor a mandou ler). */
export type CmsRemuneracaoDados = {
  ano?: number | null;
  versao?: string | null;
  contagens?: Record<string, number>;
  parametros?: { ano?: number; brap?: number | null; brap_nota?: string | null; nivel_maximo?: number | null } | null;
  niveis?: CmsRemuneracaoNivel[];
  tru_notas?: string[];
  serie?: { nivel: number; valores: Record<string, number | null> }[];
  carreiras?: CmsRemuneracaoCarreira[];
  dirigentes?: CmsRemuneracaoDirigente[];
  notas?: { seccao?: string | null; texto?: string[] }[];
  base_legal?: { seccao?: string | null; linhas?: Record<string, string>[] }[];
  fonte?: { documento?: string; url?: string; catalogo?: string; ficheiro?: string };
  gerado_em?: string | null;
  error?: string;
};

/** Título e subtítulo de uma secção da página (editáveis no CMS). */
export type CmsRemuneracaoSeccao = { titulo: string; sub: string };

/** Página pública do modelo de remunerações da Administração Pública. */
export type CmsRemuneracao = {
  id: string;
  title: string;
  slug: string;
  status: CmsStatus;
  published_at?: string | null;
  scheduled_at?: string | null;
  excerpt?: string;
  /** Ano do quadro da DGAEP que a página mostra. */
  ano?: number | null;
  intro?: string;
  blocks: CmsBlock[];
  dados?: CmsRemuneracaoDados | null;
  /** O que a página mostra, além do texto e dos blocos. */
  mostrar?: Record<string, boolean>;
  /** Título e subtítulo de cada secção, pela chave de `mostrar`. */
  seccoes?: Record<string, CmsRemuneracaoSeccao>;
  /** Ordem das secções na página. */
  ordem?: string[];
  /** Como as secções se apresentam (`cartoes`, `plano` ou `destaque`). */
  estilo?: string;
  /** Carreiras que ganham gráfico de posições. */
  destacar?: string[];
  capa_id?: string | null;
  logo_id?: string | null;
  cor?: string;
  /** Artigo de blog criado a partir desta página (`POST …/artigo`). */
  artigo_id?: string | null;
  seo?: CmsSeo;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
};

/** Uma secção da página, com o rótulo do interruptor e os títulos por omissão. */
export type CmsRemuneracaoSeccaoOpcao = { id: string; label: string; titulo: string; sub: string };

/** Escolhas para montar a página do modelo (anos e partes disponíveis). */
export type CmsRemuneracaoOpcoes = {
  anos: number[];
  ano?: number | null;
  mostrar: CmsRemuneracaoSeccaoOpcao[];
  estilos: { id: string; label: string }[];
  seccoes: string[];
  parametros?: { ano?: number; brap?: number | null; brap_nota?: string | null } | null;
  fonte?: string | null;
  fonte_url?: string | null;
  pagamentos_por_ano?: number;
  limites?: Record<string, number>;
};

export type CmsMenuItem = {
  id: string;
  label: string;
  href: string;
  page_id?: string | null;
  new_tab?: boolean;
  children?: CmsMenuItem[];
};

export type CmsMenuThemeTemplate = { id: string; label: string };

export type CmsMenuTheme = {
  id: string;
  label: string;
  templates: CmsMenuThemeTemplate[];
};

export type CmsMenu = {
  id: string;
  name: string;
  location: "header" | "footer";
  menu_theme?: string;
  menu_template?: string;
  items: CmsMenuItem[];
};

export type CmsSettings = {
  site_name: string;
  tagline: string;
  description: string;
  base_url: string;
  language: string;
  home_page_id: string;
  blog_page_id: string;
  posts_per_page: number;
  theme: string;
  accent: string;
  radius: number;
  header_menu_theme?: string;
  header_menu_template?: string;
  footer_menu_theme?: string;
  footer_menu_template?: string;
  footer_text: string;
  logo_id?: string | null;
  favicon_id?: string | null;
  social: Record<string, string>;
  seo: CmsSeo;
  robots: string;
  analytics_id: string;
  updated_at?: string;
  updated_by?: string;
};

export type CmsCatalogue = {
  block_types: { id: string; label: string; hint: string; icon: string }[];
  content_kinds: { id: string; label: string }[];
  template_kinds: { id: string; label: string }[];
  menu_locations: { id: string; label: string }[];
  menu_themes: CmsMenuTheme[];
  statuses: { id: CmsStatus; label: string; style: string }[];
  entities: string[];
  pages_index: { id: string; title: string; path: string; status: CmsStatus; parent_id?: string | null }[];
  categories_index: { id: string; name: string; slug: string }[];
  media_index: { id: string; title: string; url: string; kind: string; mime: string; size: number; storage: string }[];
  contents_index: { id: string; title: string; kind: string }[];
  templates_index: { id: string; name: string; kind: string; builtin?: boolean }[];
  blog_url: string;
  site_url: string;
  home_page_id: string;
  blog_page_id: string;
};

export type CmsOverview = {
  pages: { total: number; by_status: Record<CmsStatus, number>; published: number };
  posts: { total: number; by_status: Record<CmsStatus, number>; published: number };
  municipios?: { total: number; by_status: Record<CmsStatus, number>; published: number };
  contents: number;
  media: { total: number; bytes: number };
  categories: number;
  templates: number;
  words: number;
  /** Contactos recebidos pelo formulário do site, por estado de seguimento. */
  contactos?: Record<string, number>;
  scheduled: { id: string; entity: string; title: string; slug: string; at: string }[];
  recent: { id: string; entity: string; title: string; slug: string; at: string; status: CmsStatus; by?: string }[];
  activity: CmsActivity[];
  site: { home: string; pages: number; posts: number; settings: CmsSettings };
};

export type CmsActivity = {
  id: string;
  at: string;
  action: string;
  entity: string;
  entity_id: string;
  label: string;
  actor: string;
  detail?: string;
};

export type CmsRevision = {
  id: string;
  entity: string;
  entity_id: string;
  title: string;
  author?: string;
  note?: string;
  at: string;
  fields: string[];
};

export type CmsMenuListing = {
  total: number;
  items: CmsMenu[];
  resolved: Record<string, CmsMenu>;
  locations: { id: string; label: string }[];
  themes: CmsMenuTheme[];
};

export type CmsListPayload<T> = { total: number; count: number; items: T[] };

export type CmsSearchHit = {
  entity: string;
  id: string;
  title: string;
  subtitle: string;
  status: string;
  updated_at: string;
};

/* --------------------------------------------------------------- pedidos */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
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

/* --------------------------------------------------------------- leitura */

export function getCmsCatalogue(): Promise<CmsCatalogue> {
  return request<CmsCatalogue>("/cms/catalogue");
}

export function getCmsOverview(): Promise<CmsOverview> {
  return request<CmsOverview>("/cms/overview");
}

export function getCmsTaxonomy(): Promise<{
  categories: CmsCategory[];
  tags: { tag: string; posts: number }[];
}> {
  return request("/cms/taxonomy");
}

export function getCmsActivity(limit = 40): Promise<{ total: number; items: CmsActivity[] }> {
  return request(`/cms/activity?limit=${limit}`);
}

export function searchCms(q: string, limit = 30): Promise<{ query: string; total: number; items: CmsSearchHit[] }> {
  return request(`/cms/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export function getCmsSettings(): Promise<{ settings: CmsSettings; menus: CmsMenu[] }> {
  return request("/cms/settings");
}

export function saveCmsSettings(payload: Partial<CmsSettings>): Promise<{ saved: boolean; settings: CmsSettings }> {
  return request("/cms/settings", withBody("PUT", payload));
}

export function listCmsMenus(): Promise<CmsMenuListing> {
  return request<CmsMenuListing>("/cms/menus");
}

export function saveCmsMenu(payload: Partial<CmsMenu> & { id?: string }): Promise<{ saved: boolean; menu: CmsMenu }> {
  return payload.id
    ? request(`/cms/menus/${encodeURIComponent(payload.id)}`, withBody("PATCH", payload))
    : request("/cms/menus", withBody("POST", payload));
}

export function deleteCmsMenu(menuId: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/cms/menus/${encodeURIComponent(menuId)}`, withBody("DELETE"));
}

type ListOptions = {
  status?: string;
  q?: string;
  categoryId?: string;
  tag?: string;
  limit?: number;
  full?: boolean;
};

function listQuery(options: ListOptions = {}): string {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.q) params.set("q", options.q);
  if (options.categoryId) params.set("category_id", options.categoryId);
  if (options.tag) params.set("tag", options.tag);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.full === false) params.set("full", "false");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listCmsPages(options: ListOptions = {}): Promise<CmsListPayload<CmsPage>> {
  return request(`/cms/pages${listQuery({ limit: 300, ...options })}`);
}

/** Mensagem recebida pelo formulário do site (`POST /site/contacto`). */
export type CmsContacto = {
  id: string;
  nome: string;
  email: string;
  organizacao?: string;
  assunto?: string;
  mensagem: string;
  estado: "novo" | "em_curso" | "tratado";
  notas?: string;
  origem?: string;
  consentimento?: boolean;
  created_at?: string;
  updated_at?: string;
  updated_by?: string;
};

export function listCmsContactos(options: ListOptions = {}): Promise<CmsListPayload<CmsContacto>> {
  return request(`/cms/contactos${listQuery({ limit: 200, ...options })}`);
}

export function updateCmsContacto(id: string, payload: Partial<CmsContacto>): Promise<{ saved: boolean; item: CmsContacto }> {
  return request(`/cms/contactos/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function listCmsPosts(options: ListOptions = {}): Promise<CmsListPayload<CmsPost>> {
  return request(`/cms/posts${listQuery({ limit: 300, ...options })}`);
}

export function listCmsMunicipios(options: ListOptions = {}): Promise<CmsListPayload<CmsMunicipio>> {
  return request(`/cms/municipios${listQuery({ limit: 300, ...options })}`);
}

export function getCmsMunicipio(id: string): Promise<{ item: CmsMunicipio }> {
  return request(`/cms/municipios/${encodeURIComponent(id)}`);
}

/** Os 308 municípios que se podem publicar, com a ficha que já existe de cada um. */
export function getCmsMunicipioOpcoes(): Promise<{ total: number; items: CmsMunicipioOpcao[]; ano_despesas?: string | null }> {
  return request("/cms/municipios/opcoes");
}

/** Cria a ficha de um município; os dados oficiais entram já lidos do INE/BASE. */
export function createCmsMunicipio(payload: { municipio: string; title?: string; slug?: string }): Promise<{ saved: boolean; item: CmsMunicipio }> {
  return request("/cms/municipios", withBody("POST", payload));
}

export function updateCmsMunicipio(id: string, payload: Partial<CmsMunicipio>): Promise<{ saved: boolean; item: CmsMunicipio }> {
  return request(`/cms/municipios/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

/** Volta a ler a despesa e a contratação oficiais e guarda-as na ficha. */
export function refreshCmsMunicipioDados(id: string): Promise<{ saved: boolean; item: CmsMunicipio; resumo_dos_dados: string }> {
  return request(`/cms/municipios/${encodeURIComponent(id)}/dados`, withBody("POST", {}));
}

/** Rascunho do texto escrito pela IA com os números da ficha (não grava nada). */
export function gerarCmsMunicipioTexto(
  id: string,
  payload: { instrucoes?: string; provider?: string; model?: string } = {},
): Promise<CmsMunicipioTexto> {
  return request(`/cms/municipios/${encodeURIComponent(id)}/texto`, withBody("POST", payload));
}

export function cmsMunicipioPreviewUrl(id: string, stamp = Date.now()): string {
  return `${API_BASE}/cms/preview/municipios/${encodeURIComponent(id)}?t=${stamp}`;
}

/** Endereço público de uma ficha de município (`/site/municipio/{slug}`). */
export function cmsMunicipioUrl(slug: string): string {
  return cmsPublicUrl(`/municipio/${slug}`);
}

export function listCmsPesquisas(options: ListOptions = {}): Promise<CmsListPayload<CmsPesquisa>> {
  return request(`/cms/pesquisas${listQuery({ limit: 300, ...options })}`);
}

export function getCmsPesquisa(id: string): Promise<{ item: CmsPesquisa }> {
  return request(`/cms/pesquisas/${encodeURIComponent(id)}`);
}

/** Distritos, anos de contratação e ordenações que se podem filtrar. */
export function getCmsPesquisaOpcoes(): Promise<CmsPesquisaOpcoes> {
  return request("/cms/pesquisas/opcoes");
}

/** Cria a página de pesquisa; a fotografia dos números entra já lida. */
export function createCmsPesquisa(payload: {
  title?: string;
  slug?: string;
  filtros?: CmsPesquisaFiltros;
}): Promise<{ saved: boolean; item: CmsPesquisa }> {
  return request("/cms/pesquisas", withBody("POST", payload));
}

export function updateCmsPesquisa(id: string, payload: Partial<CmsPesquisa>): Promise<{ saved: boolean; item: CmsPesquisa }> {
  return request(`/cms/pesquisas/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

/** Volta a correr a pesquisa e guarda a fotografia nova (a página muda com ela). */
export function refreshCmsPesquisaDados(
  id: string,
  payload: { filtros?: CmsPesquisaFiltros; guardar_filtros?: boolean } = {},
): Promise<{ saved: boolean; item: CmsPesquisa; resumo_dos_dados: string }> {
  return request(`/cms/pesquisas/${encodeURIComponent(id)}/dados`, withBody("POST", payload));
}

/** Endereço público de uma página de pesquisa (`/site/pesquisa/{slug}`). */
export function cmsPesquisaUrl(slug: string): string {
  return cmsPublicUrl(`/pesquisa/${slug}`);
}

/* ------------------------------------------- remunerações da Administração Pública */

export function listCmsRemuneracoes(options: ListOptions = {}): Promise<CmsListPayload<CmsRemuneracao>> {
  return request(`/cms/remuneracoes${listQuery({ limit: 300, ...options })}`);
}

export function getCmsRemuneracao(id: string): Promise<{ item: CmsRemuneracao }> {
  return request(`/cms/remuneracoes/${encodeURIComponent(id)}`);
}

/** Anos recolhidos da DGAEP e partes que a página pode mostrar. */
export function getCmsRemuneracaoOpcoes(): Promise<CmsRemuneracaoOpcoes> {
  return request("/cms/remuneracoes/opcoes");
}

/** Cria a página; o modelo do ano escolhido entra já lido. */
export function createCmsRemuneracao(payload: {
  title?: string;
  slug?: string;
  ano?: number;
}): Promise<{ saved: boolean; item: CmsRemuneracao }> {
  return request("/cms/remuneracoes", withBody("POST", payload));
}

export function updateCmsRemuneracao(id: string, payload: Partial<CmsRemuneracao>): Promise<{ saved: boolean; item: CmsRemuneracao }> {
  return request(`/cms/remuneracoes/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

/** Volta a ler o quadro da DGAEP (do ano pedido) e guarda a fotografia nova. */
export function refreshCmsRemuneracaoModelo(
  id: string,
  payload: { ano?: number; guardar_ano?: boolean } = {},
): Promise<{ saved: boolean; item: CmsRemuneracao; ano: number; resumo_dos_dados: string }> {
  return request(`/cms/remuneracoes/${encodeURIComponent(id)}/modelo`, withBody("POST", payload));
}

/** Cria no blog o rascunho que anuncia a página (capa, resumo e ligação). */
export function createCmsRemuneracaoArtigo(
  id: string,
  payload: { title?: string; slug?: string; excerpt?: string; markdown?: string; category_ids?: string[]; tags?: string[] } = {},
): Promise<{ saved: boolean; item: CmsRemuneracao; artigo: CmsPost; url: string; resumo: string }> {
  return request(`/cms/remuneracoes/${encodeURIComponent(id)}/artigo`, withBody("POST", payload));
}

/** Endereço público da página do modelo (`/site/remuneracoes/{slug}`). */
export function cmsRemuneracaoUrl(slug: string): string {
  return cmsPublicUrl(`/remuneracoes/${slug}`);
}

export function listCmsContents(options: ListOptions = {}): Promise<CmsListPayload<CmsContent>> {
  return request(`/cms/contents${listQuery({ limit: 300, ...options })}`);
}

export function listCmsMedia(options: ListOptions = {}): Promise<CmsListPayload<CmsMedia>> {
  return request(`/cms/media${listQuery({ limit: 300, ...options })}`);
}

export function listCmsCategories(options: ListOptions = {}): Promise<CmsListPayload<CmsCategory>> {
  return request(`/cms/categories${listQuery({ limit: 300, ...options })}`);
}

export function listCmsTemplates(options: ListOptions = {}): Promise<CmsListPayload<CmsTemplate>> {
  return request(`/cms/templates${listQuery({ limit: 300, ...options })}`);
}

export function getCmsPage(id: string): Promise<{ item: CmsPage }> {
  return request(`/cms/pages/${encodeURIComponent(id)}`);
}

export function getCmsPost(id: string): Promise<{ item: CmsPost }> {
  return request(`/cms/posts/${encodeURIComponent(id)}`);
}

export function getCmsContent(id: string): Promise<{ item: CmsContent }> {
  return request(`/cms/contents/${encodeURIComponent(id)}`);
}

export function getCmsTemplate(id: string): Promise<{ item: CmsTemplate }> {
  return request(`/cms/templates/${encodeURIComponent(id)}`);
}

export function getCmsMedia(id: string): Promise<{ item: CmsMedia }> {
  return request(`/cms/media/${encodeURIComponent(id)}`);
}

/* --------------------------------------------------------------- escrita */

export function createCmsPage(payload: Partial<CmsPage>): Promise<{ saved: boolean; item: CmsPage }> {
  return request("/cms/pages", withBody("POST", payload));
}

export function updateCmsPage(id: string, payload: Partial<CmsPage>): Promise<{ saved: boolean; item: CmsPage }> {
  return request(`/cms/pages/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function createCmsPost(payload: Partial<CmsPost>): Promise<{ saved: boolean; item: CmsPost }> {
  return request("/cms/posts", withBody("POST", payload));
}

export function updateCmsPost(id: string, payload: Partial<CmsPost>): Promise<{ saved: boolean; item: CmsPost }> {
  return request(`/cms/posts/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function createCmsContent(payload: Partial<CmsContent>): Promise<{ saved: boolean; item: CmsContent }> {
  return request("/cms/contents", withBody("POST", payload));
}

export function updateCmsContent(id: string, payload: Partial<CmsContent>): Promise<{ saved: boolean; item: CmsContent }> {
  return request(`/cms/contents/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function createCmsTemplate(payload: Partial<CmsTemplate>): Promise<{ saved: boolean; item: CmsTemplate }> {
  return request("/cms/templates", withBody("POST", payload));
}

export function updateCmsTemplate(id: string, payload: Partial<CmsTemplate>): Promise<{ saved: boolean; item: CmsTemplate }> {
  return request(`/cms/templates/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function createCmsCategory(payload: Partial<CmsCategory>): Promise<{ saved: boolean; item: CmsCategory }> {
  return request("/cms/categories", withBody("POST", payload));
}

export function updateCmsCategory(id: string, payload: Partial<CmsCategory>): Promise<{ saved: boolean; item: CmsCategory }> {
  return request(`/cms/categories/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function uploadCmsMedia(payload: {
  filename: string;
  mime: string;
  data: string;
  title?: string;
  alt?: string;
  caption?: string;
  tags?: string[];
}): Promise<{ saved: boolean; item: CmsMedia }> {
  return request("/cms/media", withBody("POST", payload));
}

export function registerCmsMediaUrl(payload: {
  url: string;
  title?: string;
  alt?: string;
  tags?: string[];
}): Promise<{ saved: boolean; item: CmsMedia }> {
  return request("/cms/media", withBody("POST", payload));
}

export function updateCmsMedia(id: string, payload: Partial<CmsMedia>): Promise<{ saved: boolean; item: CmsMedia }> {
  return request(`/cms/media/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function deleteCmsEntity(entity: string, id: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}`, withBody("DELETE"));
}

export function duplicateCmsEntity<T>(entity: string, id: string): Promise<{ saved: boolean; item: T }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}/duplicate`, withBody("POST"));
}

export function publishCmsItem(
  entity: string,
  id: string,
  at?: string | null,
): Promise<{ saved: boolean; item: CmsPage | CmsPost }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}/publish`, withBody("POST", at ? { at } : {}));
}

export function unpublishCmsItem(entity: string, id: string): Promise<{ saved: boolean; item: CmsPage | CmsPost }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}/unpublish`, withBody("POST"));
}

export function setCmsStatus(entity: string, id: string, status: CmsStatus): Promise<{ saved: boolean; item: CmsPage | CmsPost }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}/status`, withBody("POST", { status }));
}

export function getCmsRevisions(entity: string, id: string, limit = 20): Promise<{ total: number; items: CmsRevision[] }> {
  return request(`/cms/${entity}/${encodeURIComponent(id)}/revisions?limit=${limit}`);
}

export function restoreCmsRevision(revisionId: string): Promise<{ saved: boolean; item: CmsPage | CmsPost }> {
  return request(`/cms/revisions/${encodeURIComponent(revisionId)}/restore`, withBody("POST"));
}

export function getCmsMediaUsage(mediaId: string): Promise<{ total: number; items: { entity: string; id: string; title: string; where: string }[] }> {
  return request(`/cms/media/${encodeURIComponent(mediaId)}/usage`);
}

/* ------------------------------------------------------------- URLs úteis */

/** URL absoluta de um media (servido pelo backend). */
export function cmsMediaUrl(media: { id: string; url: string; storage?: string }): string {
  if (media.storage === "externo") return media.url;
  return `${API_BASE}${media.url || `/cms/media/${media.id}/raw`}`;
}

/** URL da pré-visualização HTML (iframe com `?t=` para não apanhar cache). */
export function cmsPreviewUrl(entity: "pages" | "posts" | "municipios" | "pesquisas" | "remuneracoes", id: string, stamp = Date.now()): string {
  return `${API_BASE}/cms/preview/${entity}/${encodeURIComponent(id)}?t=${stamp}`;
}

/** URL do site público correspondente (abre numa janela do browser). */
export function cmsPublicUrl(path: string): string {
  // Sem o prefixo `/api`: o site público vive em `/site/...` na mesma origem (o
  // nginx do frontend encaminha-o para o backend) e é esse o endereço que o
  // `robots.txt` autoriza — `/api/` está fora dos motores de busca e os links
  // partilhados têm de ser os endereços reais das páginas.
  return `/site${path ? (path.startsWith("/") ? path : `/${path}`) : ""}`;
}

/**
 * Ligação para um item **dentro da aplicação do CMS** (`/cms/municipios?id=…`).
 *
 * O caminho é da própria SPA (não passa pelo `/api`): serve para saltar de outra
 * página da aplicação para o editor certo, sem o utilizador ter de o procurar.
 */
export function cmsAppUrl(section: "municipios" | "pesquisas" | "paginas" | "blog" | "remuneracoes", id: string): string {
  return `/cms/${section}?id=${encodeURIComponent(id)}`;
}

/** Lê um ficheiro do disco do utilizador e devolve base64 (sem o prefixo `data:`). */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.slice(result.indexOf(",") + 1) : result);
    };
    reader.onerror = () => reject(new Error("Não foi possível ler o ficheiro."));
    reader.readAsDataURL(file);
  });
}
