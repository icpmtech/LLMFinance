/**
 * Cliente do Correio da plataforma (`/admin/mail/*`).
 *
 * O gestor das caixas de correio da própria solução — só contas com o papel
 * `admin` entram (o servidor responde 403 a quem não é). A lista e a pesquisa vêm
 * do índice (`finance_mail_messages`); abrir uma mensagem e enviar passa pelo
 * IMAP/SMTP da caixa. O token da sessão é injectado por `installAuthFetch`, por
 * isso bastam os `fetch` normais.
 */
import { API_BASE } from "./api";

export type PlatformMailAddress = { name: string; email: string };

export type PlatformMailAccount = {
  id: string;
  label: string;
  email_address: string;
  display_name?: string;
  username?: string;
  imap_host: string;
  imap_port: number;
  imap_security: string;
  smtp_host: string;
  smtp_port: number;
  smtp_security: string;
  folders: string[];
  enabled: boolean;
  source?: string;
  readonly?: boolean;
  has_password: boolean;
  signature?: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_sync_at?: string | null;
  last_error?: string | null;
};

export type PlatformMailAccountDraft = {
  id?: string;
  label?: string;
  email_address?: string;
  display_name?: string;
  username?: string;
  password?: string;
  imap_host?: string;
  imap_port?: number;
  imap_security?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_security?: string;
  folders?: string[];
  signature?: string;
  enabled?: boolean;
};

export type PlatformMailFolder = {
  id: string;
  name: string;
  label: string;
  delimiter: string;
  selectable: boolean;
  sent?: boolean;
  drafts?: boolean;
  trash?: boolean;
  junk?: boolean;
  archive?: boolean;
  inbox?: boolean;
  messages?: number | null;
  unseen?: number | null;
  indexed?: number;
  synced_at?: string | null;
};

export type PlatformMailSummary = {
  id: string;
  account: string;
  account_label?: string;
  mailbox?: string;
  folder: string;
  uid: string;
  subject: string;
  from: PlatformMailAddress;
  to: PlatformMailAddress[];
  cc: PlatformMailAddress[];
  date?: string | null;
  snippet: string;
  unseen: boolean;
  flagged: boolean;
  answered: boolean;
  draft: boolean;
  has_attachments: boolean | null;
  attachments_count: number;
  size?: number | null;
  thread_key?: string | null;
  message_id?: string | null;
  direction?: string;
};

export type PlatformMailAttachment = {
  filename: string;
  content_type: string;
  size: number;
  inline?: boolean;
};

export type PlatformMailMessage = {
  uid: string;
  folder: string;
  subject: string;
  from: PlatformMailAddress[];
  to: PlatformMailAddress[];
  cc: PlatformMailAddress[];
  reply_to?: PlatformMailAddress[];
  date?: string | null;
  message_id?: string;
  in_reply_to?: string;
  references?: string;
  body_text: string;
  body_html: string;
  attachments: PlatformMailAttachment[];
  unread: boolean;
  flagged: boolean;
  answered: boolean;
  draft: boolean;
  size?: number | null;
};

export type PlatformMailFacets = {
  accounts: { key: string; count: number }[];
  folders: { key: string; count: number }[];
  unseen: number | null;
  flagged: number | null;
  with_attachments: number | null;
  senders: { key: string; count: number }[];
};

export type PlatformMailList = {
  source: "elasticsearch" | "imap";
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  items: PlatformMailSummary[];
  facets: PlatformMailFacets;
  account?: PlatformMailAccount;
};

export type PlatformMailMessageDetail = {
  message: PlatformMailMessage;
  account: PlatformMailAccount;
  source: "elasticsearch" | "imap";
  stale: boolean;
  warning?: string;
};

export type PlatformMailMeta = {
  defaults: {
    imap_host: string;
    imap_port: number;
    imap_security: string;
    smtp_host?: string;
    smtp_port?: number;
    smtp_security?: string;
    sync_folders: string[];
  };
  platform_account_configured: boolean;
  accounts: number;
  signature: { text: string; html: string };
  es: { available: boolean; index: string; documents: number };
  limits: { initial_batch: number; sync_batch: number; full_sync_cap: number; max_limit: number; max_message_bytes: number };
  settings: PlatformMailSettings;
  help: string[];
};

export type PlatformMailSettings = {
  auto_sync: boolean;
  sync_seconds: number;
  initial_batch?: number;
  sync_batch?: number;
  full_sync_cap?: number;
  updated_at?: string | null;
  updated_by?: string | null;
};

export type PlatformMailStats = {
  es_available: boolean;
  accounts: number;
  enabled_accounts: number;
  settings: PlatformMailSettings;
  mailboxes: {
    id: string;
    label: string;
    email_address: string;
    source?: string;
    enabled: boolean;
    folders: string[];
    last_sync_at?: string | null;
    last_error?: string | null;
  }[];
  index: { name: string; documents: number; size: string };
  totals: { messages: number; unseen: number; flagged: number; with_attachments: number; threads: number };
  folders: { key: string; count: number }[];
  senders: { key: string; count: number }[];
  daily: { date: string; count: number }[];
  latest?: PlatformMailSummary | null;
  error?: string;
};

export type PlatformMailSyncResult = {
  indexed: number;
  started_at?: string;
  finished_at?: string;
  errors: string[];
  accounts: {
    id: string;
    label: string;
    email_address?: string;
    indexed: number;
    error?: string | null;
    folders: { folder: string; indexed: number; total?: number | null; last_uid?: string | null; error?: string | null }[];
  }[];
};

export type PlatformMailTestResult = {
  imap: boolean;
  smtp: boolean;
  folders: number;
  capabilities: string[];
  account?: PlatformMailAccount;
  unread_inbox?: number | null;
  error?: string;
  details?: Record<string, unknown>;
};

export type PlatformMailSendPayload = {
  account?: string;
  to: string[];
  cc?: string[];
  bcc?: string[];
  subject: string;
  body_text?: string;
  body_html?: string;
  in_reply_to?: string;
  references?: string;
  include_signature?: boolean;
  attachments?: { filename: string; content_type?: string; data: string }[];
};

export type PlatformMailSendResult = {
  sent: boolean;
  account: PlatformMailAccount;
  message_id: string;
  subject: string;
  to: string[];
  cc: string[];
  bcc: string[];
  appended_to_sent: boolean;
  sent_folder?: string | null;
  indexed: boolean;
  warning?: string | null;
};

export type PlatformMailListParams = {
  account?: string;
  folder?: string;
  q?: string;
  sender?: string;
  thread?: string;
  direction?: string;
  unseen?: boolean;
  flagged?: boolean;
  attachments?: boolean;
  exclude_drafts?: boolean;
  date_from?: string;
  date_to?: string;
  sort?: string;
  limit?: number;
  offset?: number;
};

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
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

/** Caminho de uma mensagem: o identificador leva `::` e pode levar `/` (pastas). */
function messagePath(id: string): string {
  return `/admin/mail/messages/${encodeURIComponent(id)}`;
}

// ------------------------------------------------------------------ descoberta
export function getPlatformMailMeta(): Promise<PlatformMailMeta> {
  return request(`/admin/mail/meta`);
}

export function getPlatformMailStats(): Promise<PlatformMailStats> {
  return request(`/admin/mail/stats`);
}

export function getPlatformMailSettings(): Promise<PlatformMailSettings> {
  return request(`/admin/mail/settings`);
}

export function savePlatformMailSettings(patch: { auto_sync?: boolean; sync_seconds?: number }): Promise<{
  saved: boolean;
  settings: PlatformMailSettings;
}> {
  return request(`/admin/mail/settings`, withBody("PUT", patch));
}

// ----------------------------------------------------------------------- caixas
export function listPlatformMailAccounts(): Promise<{ total: number; items: PlatformMailAccount[] }> {
  return request(`/admin/mail/accounts`);
}

export function savePlatformMailAccount(draft: PlatformMailAccountDraft): Promise<{
  saved: boolean;
  account: PlatformMailAccount;
}> {
  return request(`/admin/mail/accounts`, withBody("POST", draft));
}

export function deletePlatformMailAccount(id: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/admin/mail/accounts/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function testPlatformMailAccount(payload: PlatformMailAccountDraft): Promise<PlatformMailTestResult> {
  return request(`/admin/mail/accounts/test`, withBody("POST", payload));
}

export function listPlatformMailFolders(accountId: string): Promise<{
  account: PlatformMailAccount;
  items: PlatformMailFolder[];
  total: number;
  sync_folders: string[];
  state: Record<string, { last_uid?: string; total?: number; synced_at?: string; error?: string }>;
}> {
  return request(`/admin/mail/accounts/${encodeURIComponent(accountId)}/folders`);
}

export function syncPlatformMail(options: { account?: string; full?: boolean } = {}): Promise<PlatformMailSyncResult> {
  return request(`/admin/mail/sync`, withBody("POST", options));
}

// -------------------------------------------------------------------- mensagens
export function listPlatformMailMessages(params: PlatformMailListParams = {}): Promise<PlatformMailList> {
  const query = new URLSearchParams();
  const definir = (chave: string, valor: unknown) => {
    if (valor === undefined || valor === null || valor === "") return;
    query.set(chave, typeof valor === "boolean" ? String(valor) : String(valor));
  };
  definir("account", params.account);
  definir("folder", params.folder);
  definir("q", params.q);
  definir("sender", params.sender);
  definir("thread", params.thread);
  definir("direction", params.direction);
  definir("unseen", params.unseen);
  definir("flagged", params.flagged);
  definir("attachments", params.attachments);
  if (params.exclude_drafts !== undefined) definir("exclude_drafts", params.exclude_drafts);
  definir("date_from", params.date_from);
  definir("date_to", params.date_to);
  definir("sort", params.sort);
  definir("limit", params.limit);
  definir("offset", params.offset);
  const sufixo = query.toString();
  return request(`/admin/mail/messages${sufixo ? `?${sufixo}` : ""}`);
}

export function getPlatformMailMessage(id: string, markRead = true): Promise<PlatformMailMessageDetail> {
  return request(`${messagePath(id)}?mark_read=${markRead ? "true" : "false"}`);
}

export function setPlatformMailFlags(
  id: string,
  action: "read" | "unread" | "flag" | "unflag",
): Promise<{ updated: boolean; uid: string; action: string; indexed: boolean }> {
  return request(`${messagePath(id)}/flags`, withBody("POST", { action }));
}

export function movePlatformMailMessage(
  id: string,
  target: string,
): Promise<{ moved: boolean; uid: string; from: string; to: string; reindexed_as?: string | null }> {
  return request(`${messagePath(id)}/move`, withBody("POST", { target }));
}

export function deletePlatformMailMessage(id: string): Promise<{ deleted: boolean; uid: string; removed_from_index: boolean }> {
  return request(messagePath(id), { method: "DELETE" });
}

/**
 * Descarrega um anexo (o conteúdo vem do IMAP, não do índice).
 *
 * Vai por `fetch` e não por um link direto: o pedido tem de levar o token da
 * sessão, que só o `installAuthFetch` acrescenta.
 */
export async function downloadPlatformMailAttachment(id: string, index: number): Promise<void> {
  const response = await fetch(`${API_BASE}${messagePath(id)}/attachments/${index}`);
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
  const disposicao = response.headers.get("content-disposition") || "";
  const achado = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposicao);
  const nome = achado ? decodeURIComponent(achado[1]) : `anexo-${index}`;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ------------------------------------------------------------------------- envio
export function sendPlatformMail(payload: PlatformMailSendPayload): Promise<PlatformMailSendResult> {
  return request(`/admin/mail/send`, withBody("POST", payload));
}
