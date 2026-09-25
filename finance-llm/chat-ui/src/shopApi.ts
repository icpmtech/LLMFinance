/**
 * Cliente da loja online IQ OS (`/shop/*`) e da vitrine pública (`/loja/*`).
 *
 * A loja trata de **produtos** (físicos, digitais ou serviços), **categorias**,
 * **encomendas** com pagamento registado à mão, **clientes**, **cupões**,
 * **métodos de envio** e **avaliações**. O resultado público vive em `/loja/…`.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------ tipos */

export type ShopStatus = "rascunho" | "agendado" | "publicado" | "arquivado";
export type OrderStatus = "pendente" | "pago" | "em_preparacao" | "enviado" | "entregue" | "cancelado" | "reembolsado";
export type PaymentStatus = "pendente" | "parcial" | "pago" | "reembolsado";
export type ReviewStatus = "pendente" | "aprovada" | "rejeitada";
export type ShopEntity = "products" | "categories" | "customers" | "orders" | "coupons" | "shipping" | "reviews";

export type ShopSeo = { title?: string; description?: string; keywords?: string[]; noindex?: boolean };

export type ShopProduct = {
  id: string;
  name: string;
  slug: string;
  sku: string;
  type: "fisico" | "digital" | "servico";
  status: ShopStatus;
  scheduled_at?: string | null;
  featured?: boolean;
  order?: number;
  short_description?: string;
  description?: string;
  price: number;
  compare_at_price: number;
  cost: number;
  tax_rate: number;
  stock: number;
  stock_min: number;
  track_stock: boolean;
  allow_backorder: boolean;
  unit: string;
  category_ids: string[];
  tags: string[];
  image_ids: string[];
  image_urls: string[];
  attributes: { label: string; value: string }[];
  weight_kg: number;
  length_cm: number;
  width_cm: number;
  height_cm: number;
  internal_notes?: string;
  seo?: ShopSeo;
  rating_avg?: number;
  rating_count?: number;
  image_url?: string;
  available?: boolean;
  published_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ShopCategory = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  parent_id?: string | null;
  status: ShopStatus;
  featured?: boolean;
  order?: number;
  image_id?: string | null;
  image_url?: string;
  products?: number;
  seo?: ShopSeo;
  created_at?: string;
  updated_at?: string;
};

export type ShopCustomer = {
  id: string;
  name: string;
  email: string;
  phone?: string;
  tax_id?: string;
  company?: string;
  status: "ativo" | "bloqueado";
  tags: string[];
  notes?: string;
  billing?: ShopAddress;
  shipping_address?: ShopAddress;
  marketing?: boolean;
  source?: string;
  crm_account_id?: string | null;
  orders_count?: number;
  total_spent?: number;
  last_order_at?: string;
  created_at?: string;
  updated_at?: string;
};

export type ShopAddress = {
  name?: string;
  line1?: string;
  line2?: string;
  postal_code?: string;
  city?: string;
  country?: string;
  phone?: string;
};

export type ShopOrderItem = {
  id: string;
  product_id?: string | null;
  name: string;
  sku: string;
  unit: string;
  quantity: number;
  unit_price: number;
  tax_rate: number;
  discount: number;
  image_url?: string;
};

export type ShopPayment = {
  method: string;
  status: PaymentStatus;
  reference?: string;
  amount: number;
  paid_at?: string | null;
  note?: string;
  history?: { at: string; status: string; amount: number; method?: string; note?: string; actor?: string }[];
};

export type ShopOrderTotals = {
  subtotal: number;
  discount_total: number;
  shipping_total: number;
  tax_total: number;
  total: number;
  items_count?: number;
};

export type ShopOrder = {
  id: string;
  number: string;
  status: OrderStatus;
  payment: ShopPayment;
  customer_id?: string | null;
  customer: { name?: string; email?: string; phone?: string; tax_id?: string; company?: string };
  billing?: ShopAddress;
  shipping_address?: ShopAddress;
  shipping_method_id?: string | null;
  shipping_method?: { id?: string | null; name?: string; price: number; days_min?: number; days_max?: number };
  coupon_id?: string | null;
  coupon_code?: string;
  coupon?: { id: string; code: string; type: string; value: number } | null;
  items: ShopOrderItem[];
  subtotal?: number;
  discount_total?: number;
  shipping_total?: number;
  tax_total?: number;
  total?: number;
  totals?: ShopOrderTotals;
  items_count?: number;
  notes?: string;
  internal_notes?: string;
  tracking?: string;
  source?: string;
  stock_reserved?: boolean;
  timeline?: { at: string; status: string; note?: string; actor?: string }[];
  placed_at?: string;
  created_at?: string;
  updated_at?: string;
};

export type ShopCoupon = {
  id: string;
  code: string;
  type: "percentagem" | "valor" | "portes_gratis";
  value: number;
  description?: string;
  active: boolean;
  min_subtotal: number;
  starts_at?: string | null;
  ends_at?: string | null;
  max_uses: number;
  uses: number;
  product_ids: string[];
  category_ids: string[];
  created_at?: string;
  updated_at?: string;
};

export type ShopShipping = {
  id: string;
  name: string;
  description?: string;
  price: number;
  free_above: number;
  days_min: number;
  days_max: number;
  zone: string;
  active: boolean;
  digital: boolean;
  order?: number;
  created_at?: string;
  updated_at?: string;
};

export type ShopReview = {
  id: string;
  product_id?: string | null;
  product_name?: string;
  customer_id?: string | null;
  customer_name: string;
  email?: string;
  rating: number;
  title?: string;
  body?: string;
  status: ReviewStatus;
  reply?: string;
  order_id?: string | null;
  verified?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type ShopSettings = {
  store_name: string;
  tagline: string;
  description: string;
  base_url: string;
  language: string;
  currency: string;
  prices_include_tax: boolean;
  default_tax_rate: number;
  email: string;
  phone: string;
  address: string;
  tax_id: string;
  min_order: number;
  low_stock_threshold: number;
  order_prefix: string;
  payments: Record<string, boolean>;
  payment_instructions: Record<string, string>;
  terms_url: string;
  footer_text: string;
  theme: string;
  accent: string;
  radius: number;
  show_stock: boolean;
  allow_reviews: boolean;
  seo: ShopSeo;
  robots: string;
  analytics_id: string;
  social: Record<string, string>;
  updated_at?: string;
  updated_by?: string;
};

export type ShopActivity = {
  id: string;
  at: string;
  action: string;
  entity: string;
  entity_id: string;
  label: string;
  actor: string;
  detail?: string;
};

export type ShopRevision = {
  id: string;
  entity: string;
  entity_id: string;
  title: string;
  author?: string;
  note?: string;
  at: string;
  fields: string[];
};

export type ShopCatalogue = {
  product_types: { id: string; label: string; hint: string }[];
  product_statuses: { id: ShopStatus; label: string; style: string }[];
  order_statuses: { id: OrderStatus; label: string; style: string; next: OrderStatus[] }[];
  payment_statuses: { id: PaymentStatus; label: string; style: string }[];
  payment_methods: { id: string; label: string; hint: string }[];
  coupon_types: { id: string; label: string; hint: string }[];
  review_statuses: { id: ReviewStatus; label: string; style: string }[];
  customer_statuses: { id: string; label: string }[];
  units: string[];
  sort_options: { id: string; label: string }[];
  entities: ShopEntity[];
  products_index: { id: string; name: string; slug: string; sku: string; price: number; stock: number; status: ShopStatus; type: string; image_url?: string }[];
  categories_index: { id: string; name: string; slug: string; parent_id?: string | null; status: ShopStatus }[];
  customers_index: { id: string; name: string; email: string; orders_count: number }[];
  shipping_index: { id: string; name: string; price: number; active: boolean }[];
  coupons_index: { id: string; code: string; type: string; value: number; active: boolean }[];
  media_index: { id: string; title: string; url: string; kind: string; mime: string; size: number; storage: string }[];
  settings: ShopSettings;
  store_url: string;
  cart_url: string;
  products_url: string;
};

export type ShopOverview = {
  revenue: { total: number; month: number; pending: number; average_ticket: number; paid_orders: number };
  orders: { total: number; by_status: Record<OrderStatus, number>; pending: number; open: number };
  products: {
    total: number;
    published: number;
    drafts: number;
    featured: number;
    low_stock: { id: string; name: string; sku: string; stock: number; status: ShopStatus }[];
    out_of_stock: { id: string; name: string; sku: string; stock: number; status: ShopStatus }[];
  };
  customers: { total: number; new_month: number; top: { id: string; name: string; email: string; spent: number; orders: number }[] };
  coupons: { total: number; active: number; uses: number };
  reviews: { total: number; pending: number; approved: number; average: number };
  shipping: number;
  top_products: { id: string; name: string; sku: string; units: number; revenue: number; image_url?: string }[];
  recent_orders: { id: string; number: string; customer?: string; total: number; status: OrderStatus; payment_status: PaymentStatus; at: string }[];
  series: { day: string; revenue: number }[];
  activity: ShopActivity[];
  store: { url: string; cart_url: string; settings: ShopSettings };
};

export type ShopSearchHit = {
  entity: string;
  id: string;
  title: string;
  subtitle: string;
  status: string;
  updated_at: string;
};

export type ShopListPayload<T> = { total: number; count: number; items: T[] };

export type ShopPublicOrder = ShopOrder & {
  totals: ShopOrderTotals;
  payment_label?: string;
  status_label?: string;
  payment_instructions?: string;
  currency?: string;
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

export function getShopCatalogue(): Promise<ShopCatalogue> {
  return request<ShopCatalogue>("/shop/catalogue");
}

export function getShopOverview(): Promise<ShopOverview> {
  return request<ShopOverview>("/shop/overview");
}

export function getShopSettings(): Promise<{ settings: ShopSettings; payment_methods: ShopCatalogue["payment_methods"] }> {
  return request("/shop/settings");
}

export function getShopActivity(limit = 40): Promise<{ total: number; items: ShopActivity[] }> {
  return request(`/shop/activity?limit=${limit}`);
}

export function getShopTaxonomy(): Promise<{ categories: ShopCategory[]; tags: { tag: string; products: number }[] }> {
  return request("/shop/taxonomy");
}

export function searchShop(q: string, limit = 30): Promise<{ query: string; total: number; items: ShopSearchHit[] }> {
  return request(`/shop/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

type ListOptions = {
  status?: string;
  paymentStatus?: string;
  q?: string;
  categoryId?: string;
  tag?: string;
  productId?: string;
  customerId?: string;
  stock?: string;
  limit?: number;
  light?: boolean;
};

function listQuery(options: ListOptions = {}): string {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.paymentStatus) params.set("payment_status", options.paymentStatus);
  if (options.q) params.set("q", options.q);
  if (options.categoryId) params.set("category_id", options.categoryId);
  if (options.tag) params.set("tag", options.tag);
  if (options.productId) params.set("product_id", options.productId);
  if (options.customerId) params.set("customer_id", options.customerId);
  if (options.stock) params.set("stock", options.stock);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.light) params.set("light", "true");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listShop<T>(entity: ShopEntity, options: ListOptions = {}): Promise<ShopListPayload<T>> {
  return request<ShopListPayload<T>>(`/shop/${entity}${listQuery({ limit: 400, ...options })}`);
}

export function getShopItem<T>(entity: ShopEntity, id: string): Promise<{ item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}`);
}

export function getShopRevisions(entity: ShopEntity, id: string, limit = 20): Promise<{ total: number; items: ShopRevision[] }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}/revisions?limit=${limit}`);
}

/* --------------------------------------------------------------- escrita */

export function createShopItem<T>(entity: ShopEntity, payload: Partial<T>): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}`, withBody("POST", payload));
}

export function updateShopItem<T>(entity: ShopEntity, id: string, payload: Partial<T>): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function deleteShopItem(entity: ShopEntity, id: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}`, withBody("DELETE"));
}

export function duplicateShopItem<T>(entity: ShopEntity, id: string): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}/duplicate`, withBody("POST"));
}

export function publishShopItem<T>(entity: ShopEntity, id: string, at?: string): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}/publish`, withBody("POST", at ? { at } : {}));
}

export function unpublishShopItem<T>(entity: ShopEntity, id: string): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}/unpublish`, withBody("POST"));
}

export function setShopItemStatus<T>(entity: ShopEntity, id: string, status: ShopStatus): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/${entity}/${encodeURIComponent(id)}/status`, withBody("POST", { status }));
}

export function restoreShopRevision<T>(revisionId: string): Promise<{ saved: boolean; item: T }> {
  return request(`/shop/revisions/${encodeURIComponent(revisionId)}/restore`, withBody("POST"));
}

export function saveShopSettings(payload: Partial<ShopSettings>): Promise<{ saved: boolean; settings: ShopSettings }> {
  return request("/shop/settings", withBody("PUT", payload));
}

/* ------------------------------------------------------- encomendas (gestão) */

export function setShopOrderStatus(id: string, status: OrderStatus, note = "", actor = ""): Promise<{ saved: boolean; item: ShopOrder }> {
  return request(`/shop/orders/${encodeURIComponent(id)}/status`, withBody("POST", { status, note, actor }));
}

export function registerShopPayment(
  id: string,
  payload: { method: string; amount?: number; reference?: string; note?: string; status?: string },
): Promise<{ saved: boolean; item: ShopOrder }> {
  return request(`/shop/orders/${encodeURIComponent(id)}/payment`, withBody("POST", payload));
}

export function addShopOrderNote(id: string, note: string, internal = true): Promise<{ saved: boolean; item: ShopOrder }> {
  return request(`/shop/orders/${encodeURIComponent(id)}/note`, withBody("POST", { note, internal }));
}

/* ------------------------------------------------------------- media e CRM */

export function uploadShopMedia(payload: {
  filename: string;
  mime: string;
  data: string;
  title?: string;
  alt?: string;
  tags?: string[];
}): Promise<{ saved: boolean; item: { id: string; title: string; url: string; kind: string }; url: string }> {
  return request("/shop/media", withBody("POST", payload));
}

export function registerShopMediaUrl(payload: { url: string; title?: string; tags?: string[] }): Promise<{ saved: boolean; item: { id: string; title: string; url: string }; url: string }> {
  return request("/shop/media", withBody("POST", payload));
}

export function linkShopCustomerToCrm(id: string, accountId = ""): Promise<{ saved: boolean; item: ShopCustomer }> {
  return request(`/shop/customers/${encodeURIComponent(id)}/crm`, withBody("POST", { account_id: accountId }));
}

/* ------------------------------------------------------------------ URLs */

/** URL da vitrine pública. */
export const SHOP_STORE_URL = "/loja";

/** Encomenda pronta a imprimir (HTML na API). */
export function shopOrderPrintUrl(id: string): string {
  return `${API_BASE}/shop/orders/${encodeURIComponent(id)}/print`;
}

/** Imagem da biblioteca do CMS, usada nos produtos da loja. */
export function shopMediaUrl(url?: string | null): string {
  if (!url) return "";
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}
