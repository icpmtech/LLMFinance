/**
 * Cliente do módulo de **pesquisa social** (`/social/*`).
 *
 * Traz publicações de LinkedIn, TikTok, Reddit e Facebook através de **canais**
 * (definições: plataforma + variante + alvo), guarda-as em JSONL, indexa-as no
 * índice `finance_social` e permite pesquisá-las, agendá-las por cron e
 * exportá-las.
 *
 * Cada plataforma tem as suas variantes (`kind`) e algumas exigem credenciais
 * (a pesquisa do Reddit e o Facebook) — o estado do canal diz o que falta, com
 * a indicação de onde obter a chave.
 */
import { API_BASE } from "./api";
import type { DisplayItem } from "./components/ItemsView";

/* ------------------------------------------------------------------- tipos */

export type SocialPlatformId = "linkedin" | "tiktok" | "reddit" | "facebook";

export type SocialKind = {
  id: string;
  label: string;
  /** O que se escreve no `target` (nome, hashtag, ligação…). */
  target: string;
  credentials: boolean;
  notes: string;
};

export type SocialPlatform = {
  id: SocialPlatformId;
  label: string;
  color: string;
  credential_hint: string;
  kinds: SocialKind[];
};

/** Estados possíveis de uma recolha (o que a UI mostra). */
export type SocialRunStatus = "running" | "ok" | "empty" | "credentials" | "blocked" | "error";

export type SocialChannelCredentials = {
  required: boolean;
  ok: boolean;
  provided: string[];
  missing: string[];
  hint?: string;
};

/** Canal (definição) de recolha social. */
export type SocialChannel = {
  id: string;
  name: string;
  description?: string;
  platform: SocialPlatformId | string;
  kind: string;
  target: string;
  enabled: boolean;
  limit: number;
  /** Opções do coletor (proxy, token, client_id…); os segredos vêm mascarados. */
  options: Record<string, unknown>;
  schedule: { cron: string; timezone: string };
  tags: string[];
  sentiment?: Record<string, unknown>;
  notes?: string;
  created_at?: string;
  updated_at?: string;
  /** Estado das credenciais (só leitura, calculado pelo backend). */
  credentials?: SocialChannelCredentials;
  requires_credentials?: boolean;
  kind_label?: string;
  platform_label?: string;
  kind_notes?: string;
  template_id?: string;
};

/** Métricas de interação de uma publicação. */
export type SocialMetrics = {
  likes?: number;
  comments?: number;
  shares?: number;
  views?: number;
  videos?: number;
};

/** Publicação recolhida (documento do índice `finance_social`). */
export type SocialPost = {
  platform: string;
  channel_id?: string;
  channel_name?: string;
  kind?: string;
  run_id?: string;
  item_id?: string;
  post_id?: string;
  url?: string;
  title?: string;
  text?: string;
  author?: string;
  community?: string;
  lang?: string;
  image?: string;
  tags?: string[];
  likes?: number;
  comments?: number;
  shares?: number;
  views?: number;
  published_at?: string | null;
  collected_at?: string;
  sentiment?: string;
  sentiment_score?: number;
  sentiment_engine?: string;
  trigger?: string;
  data?: Record<string, unknown>;
};

export type SocialFacets = {
  platforms?: { key: string; count: number }[];
  channels?: { key: string; count: number }[];
  tags?: { key: string; count: number }[];
  days?: { key: string; count: number }[];
  sentiment?: { key: string; count: number }[];
};

export type SocialSentimentSummary = {
  positivo: number;
  neutro: number;
  negativo: number;
  analyzed: number;
  total: number;
  polarity: number;
  label: string;
  coverage: number;
};

export type SocialSearchResult = {
  total: number;
  items: SocialPost[];
  facets?: SocialFacets;
  sentiment?: SocialSentimentSummary;
  error?: string;
};

export type SocialRun = {
  run_id: string;
  channel_id: string;
  channel_name: string;
  platform?: string;
  kind?: string;
  target?: string;
  trigger?: string;
  status: SocialRunStatus;
  started_at?: string;
  finished_at?: string | null;
  items_count?: number;
  indexed_count?: number;
  index_error?: string | null;
  notes?: string[];
  error?: string | null;
  hint?: string | null;
  seconds?: number | null;
  sentiment_count?: number;
  likes?: number;
  comments?: number;
  views?: number;
  shares?: number;
  /** Resumo já preparado pelo backend (com `source_id`/`source_name`). */
  items?: number;
  counters?: { key: string; count: number }[];
  organization?: Record<string, unknown>;
};

export type SocialMeta = {
  platforms: SocialPlatform[];
  cron_presets: { cron: string; label: string }[];
  default_timezone: string;
  index: string;
  run_statuses: SocialRunStatus[];
  max_limit: number;
  default_limit: number;
  sentiment_engines: { id: string; label: string }[];
  sentiment_fields: { id: string; label: string }[];
};

export type SocialStatus = {
  python?: string;
  python_version?: string;
  http_client?: string | null;
  scrapling?: boolean;
  scrapling_version?: string | null;
  browsers?: boolean;
  elasticsearch?: boolean;
  indexed_items?: number;
  indexed_platforms?: { key: string; count: number }[];
  indexed_channels?: { key: string; count: number }[];
  platforms?: SocialPlatform[];
  proxy_configured?: boolean;
  scheduler?: { available?: boolean; jobs?: SocialJob[]; jobs_total?: number; error?: string | null };
  scrapling_error?: string;
};

export type SocialJob = { id: string; channel_id: string; name: string; next_run_time?: string | null };

export type SocialStats = {
  channels: number;
  channels_enabled: number;
  channels_by_platform: { key: string; count: number }[];
  runs: number;
  runs_by_status: { key: string; count: number }[];
  last_run?: SocialRun | null;
  indexed?: { total?: number; platforms?: { key: string; count: number }[] };
  cron_presets?: { cron: string; label: string }[];
};

export type SocialTemplate = {
  id: string;
  name: string;
  platform: SocialPlatformId | string;
  kind: string;
  target: string;
  description: string;
  requires_credentials: boolean;
  cron: string;
  tags: string[];
};

export type SocialPreview = {
  ok: boolean;
  status: string;
  error?: string;
  hint?: string;
  items?: SocialPost[];
  notes?: string[];
  count?: number;
  seconds?: number;
  channel?: SocialChannel;
  organization?: Record<string, unknown>;
};

export type SocialSearchParams = {
  q?: string;
  platform?: string;
  channel_id?: string;
  tag?: string[];
  sentiment?: string[];
  date_from?: string;
  date_to?: string;
  size?: number;
  offset?: number;
  sort?: "recent" | "oldest" | "relevance" | "engagement" | "views";
};

export type SocialChannelParams = {
  id?: string;
  name?: string;
  description?: string;
  platform?: string;
  kind?: string;
  target?: string;
  enabled?: boolean;
  limit?: number;
  options?: Record<string, unknown>;
  schedule?: { cron?: string; timezone?: string };
  tags?: string[];
  notes?: string;
};

/* ----------------------------------------------------------------- helpers */

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

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

function queryOf(params: Record<string, unknown>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value.forEach((entry) => query.append(key, String(entry)));
      return;
    }
    query.set(key, String(value));
  });
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

/* -------------------------------------------------------------------- API */

export function getSocialMeta() {
  return request<SocialMeta>("/social/meta");
}

export function getSocialStatus() {
  return request<SocialStatus>("/social/status");
}

export function getSocialStats() {
  return request<SocialStats>("/social/stats");
}

export function listSocialPlatforms() {
  return request<{ total: number; items: SocialPlatform[] }>("/social/platforms");
}

/** Canais de recolha (definições). */
export function listSocialChannels(enabledOnly = false) {
  return request<{ total: number; items: SocialChannel[] }>(`/social/channels${queryOf({ enabled_only: enabledOnly || undefined })}`);
}

export function getSocialChannel(channelId: string) {
  return request<{ item: SocialChannel }>(`/social/channels/${encodeURIComponent(channelId)}`);
}

export function createSocialChannel(body: SocialChannelParams) {
  return request<{ item: SocialChannel }>("/social/channels", withBody("POST", body));
}

export function updateSocialChannel(channelId: string, body: SocialChannelParams) {
  return request<{ item: SocialChannel }>(`/social/channels/${encodeURIComponent(channelId)}`, withBody("PATCH", body));
}

export function deleteSocialChannel(channelId: string, purgeItems = false) {
  return request<{ id: string; deleted: boolean; purged?: { deleted?: number } }>(
    `/social/channels/${encodeURIComponent(channelId)}${queryOf({ purge_items: purgeItems || undefined })}`,
    { method: "DELETE" },
  );
}

/** Arranca a recolha de um canal (em segundo plano) e devolve o `run_id`. */
export function runSocialChannel(channelId: string) {
  return request<{ run_id?: string; status?: string; already_running?: boolean; started?: boolean }>(
    `/social/channels/${encodeURIComponent(channelId)}/run`,
    { method: "POST" },
  );
}

/** Testa uma definição sem a guardar (a chave fica para validar o formulário). */
export function previewSocialChannel(channel: SocialChannelParams, limit = 5) {
  return request<SocialPreview>("/social/preview", withBody("POST", { channel, limit }));
}

export function previewSavedSocialChannel(channelId: string, limit = 5) {
  return request<SocialPreview>(
    `/social/channels/${encodeURIComponent(channelId)}/preview${queryOf({ limit })}`,
    { method: "POST" },
  );
}

export function listSocialRuns(params: { channel_id?: string; limit?: number } = {}) {
  return request<{ total: number; items: SocialRun[] }>(`/social/runs${queryOf(params)}`);
}

export function getSocialRun(runId: string, channelId?: string) {
  return request<{ item: SocialRun }>(`/social/runs/${encodeURIComponent(runId)}${queryOf({ channel_id: channelId })}`);
}

export function getSocialRunItems(runId: string, channelId: string, limit = 100, offset = 0) {
  return request<{ run_id: string; items: SocialPost[]; count: number; total: number }>(
    `/social/runs/${encodeURIComponent(runId)}/items${queryOf({ channel_id: channelId, limit, offset })}`,
  );
}

/** Pesquisa publicações sociais indexadas. */
export function searchSocial(params: SocialSearchParams = {}) {
  return request<SocialSearchResult>(`/social/search${queryOf({ ...params })}`);
}

/** Canais prontos a criar (galeria). */
export function listSocialTemplates() {
  return request<{ total: number; items: SocialTemplate[] }>("/social/templates");
}

export function createChannelFromTemplate(
  templateId: string,
  body: { name?: string; target?: string; enabled?: boolean; cron?: string; limit?: number; tags?: string[]; options?: Record<string, unknown> } = {},
) {
  return request<{ item: SocialChannel }>(`/social/templates/${encodeURIComponent(templateId)}/channel`, withBody("POST", body));
}

export function previewSocialTemplate(templateId: string, limit = 3, overrides: Record<string, unknown> = {}) {
  return request<SocialPreview>(
    `/social/templates/${encodeURIComponent(templateId)}/preview${queryOf({ limit })}`,
    withBody("POST", overrides),
  );
}

export function listSocialJobs() {
  return request<{ available: boolean; jobs: SocialJob[]; jobs_total: number; error?: string | null }>("/social/jobs");
}

export function reloadSocialJobs() {
  return request<{ available: boolean; jobs: SocialJob[]; jobs_total: number }>("/social/jobs/reload", { method: "POST" });
}

/* ------------------------------------------------------------ apresentação */

/** Cor de cada plataforma (coerente com o catálogo do backend). */
export const PLATFORM_COLORS: Record<string, string> = {
  linkedin: "#0a66c2",
  reddit: "#ff4500",
  tiktok: "#22d3ee",
  facebook: "#1877f2",
};

const PLATFORM_LABELS: Record<string, string> = {
  linkedin: "LinkedIn",
  reddit: "Reddit",
  tiktok: "TikTok",
  facebook: "Facebook",
};

export function platformLabel(platform?: string): string {
  return PLATFORM_LABELS[String(platform ?? "")] ?? String(platform ?? "");
}

/** Etiquetas de uma publicação (plataforma, comunidade e interação). */
export function postBadges(post: SocialPost): string[] {
  const badges: string[] = [];
  if (post.platform) badges.push(platformLabel(post.platform));
  if (post.community) badges.push(post.community);
  const metrics: [number | undefined, string][] = [
    [post.likes, "reações"],
    [post.comments, "comentários"],
    [post.shares, "partilhas"],
    [post.views, "vistas"],
  ];
  metrics.forEach(([value, label]) => {
    if (value) badges.push(`${new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(value)} ${label}`);
  });
  return badges;
}

/**
 * Converte uma publicação no item que as vistas de itens (cartões, lista,
 * imagens) sabem mostrar — o mesmo componente da Recolha e da Pesquisa total.
 */
export function toDisplayItem(post: SocialPost): DisplayItem {
  const valores: Record<string, unknown> = {};
  if (post.author) valores["Autor"] = post.author;
  if (post.kind) valores["Tipo"] = post.kind;
  if (post.likes) valores["Reações"] = post.likes;
  if (post.comments) valores["Comentários"] = post.comments;
  if (post.shares) valores["Partilhas"] = post.shares;
  if (post.views) valores["Vistas"] = post.views;
  if (post.post_id) valores["Publicação"] = post.post_id;
  Object.entries(post.data ?? {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "" || typeof value === "object") return;
    if (Object.keys(valores).length >= 12) return;
    valores[key] = value;
  });
  return {
    id: String(post.item_id ?? post.post_id ?? post.url ?? Math.random()),
    title: post.title || post.text || post.item_id || "Publicação",
    subtitle: [post.channel_name, post.author].filter(Boolean).join(" · "),
    summary: post.text || post.title || "",
    url: post.url ?? "",
    image: post.image ?? "",
    date: post.published_at || post.collected_at || null,
    badges: postBadges(post),
    tags: post.tags ?? [],
    values: valores,
  };
}

/** Etiqueta legível e tom de cada estado de execução. */
export const RUN_STATUS_STYLE: Record<string, { label: string; className: string }> = {
  running: { label: "a recolher", className: "border-sky-400/30 bg-sky-400/10 text-sky-200" },
  ok: { label: "concluída", className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200" },
  empty: { label: "sem resultados", className: "border-white/15 bg-white/5 text-muted-foreground" },
  credentials: { label: "precisa de credenciais", className: "border-amber-400/30 bg-amber-400/10 text-amber-200" },
  blocked: { label: "bloqueada", className: "border-rose-400/30 bg-rose-400/10 text-rose-200" },
  error: { label: "erro", className: "border-rose-400/30 bg-rose-400/10 text-rose-200" },
};
