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

export type CmsMenuItem = {
  id: string;
  label: string;
  href: string;
  page_id?: string | null;
  new_tab?: boolean;
  children?: CmsMenuItem[];
};

export type CmsMenu = {
  id: string;
  name: string;
  location: "header" | "footer";
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
  contents: number;
  media: { total: number; bytes: number };
  categories: number;
  templates: number;
  words: number;
  scheduled: { id: string; entity: "pages" | "posts"; title: string; slug: string; at: string }[];
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

export function listCmsPosts(options: ListOptions = {}): Promise<CmsListPayload<CmsPost>> {
  return request(`/cms/posts${listQuery({ limit: 300, ...options })}`);
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
export function cmsPreviewUrl(entity: "pages" | "posts", id: string, stamp = Date.now()): string {
  return `${API_BASE}/cms/preview/${entity}/${encodeURIComponent(id)}?t=${stamp}`;
}

/** URL do site público correspondente (abre numa janela do browser). */
export function cmsPublicUrl(path: string): string {
  return `${API_BASE}/site${path ? (path.startsWith("/") ? path : `/${path}`) : ""}`;
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
