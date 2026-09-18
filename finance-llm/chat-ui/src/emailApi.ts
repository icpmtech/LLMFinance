/**
 * Cliente do Email IQ OS (`/email/*`).
 *
 * A caixa de correio da plataforma: contas Gmail, Outlook/Microsoft 365, iCloud,
 * Yahoo, Zoho, SAPO ou qualquer servidor IMAP/SMTP; pastas, mensagens, leitura,
 * sinalizadores, envio e resposta. O token da sessão é injetado
 * automaticamente por `installAuthFetch`, por isso bastam os `fetch` normais.
 */
import { API_BASE } from "./api";

export type EmailProvider = {
  id: string;
  label: string;
  family: string;
  imap_host: string;
  imap_port: number;
  imap_security: string;
  smtp_host: string;
  smtp_port: number;
  smtp_security: string;
  help: string;
  docs_url: string;
};

export type EmailAccount = {
  id: string;
  label: string;
  email_address: string;
  display_name?: string;
  provider: string;
  provider_label?: string | null;
  username: string;
  imap_host: string;
  imap_port: number;
  imap_security: string;
  smtp_host: string;
  smtp_port: number;
  smtp_security: string;
  signature?: string;
  color?: string;
  is_default?: boolean;
  has_password: boolean;
  created_at?: string;
  updated_at?: string;
  last_sync_at?: string | null;
  last_error?: string | null;
};

export type EmailAccountDraft = {
  id?: string;
  label?: string;
  email_address: string;
  display_name?: string;
  provider: string;
  username?: string;
  password?: string;
  imap_host?: string;
  imap_port?: number;
  imap_security?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_security?: string;
  signature?: string;
  color?: string;
  is_default?: boolean;
};

export type EmailFolder = {
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
  messages?: number | null;
  unseen?: number | null;
};

export type EmailAddress = { name: string; email: string };

export type EmailMessageSummary = {
  uid: string;
  folder: string;
  subject: string;
  from: EmailAddress[];
  to: EmailAddress[];
  cc: EmailAddress[];
  date: string | null;
  message_id: string;
  size?: number | null;
  unread: boolean;
  flagged: boolean;
  answered: boolean;
  preview?: string;
};

export type EmailAttachment = {
  filename: string;
  content_type: string;
  size: number;
  inline?: boolean;
};

export type EmailMessage = EmailMessageSummary & {
  reply_to: EmailAddress[];
  in_reply_to: string;
  references: string;
  body_text: string;
  body_html: string;
  attachments: EmailAttachment[];
  draft?: boolean;
};

export type EmailFolderList = { total: number; items: EmailFolder[]; account?: EmailAccount };
export type EmailAccountList = { total: number; items: EmailAccount[]; default_id: string | null };
export type EmailMessageList = {
  folder: string;
  total: number;
  folder_total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  items: EmailMessageSummary[];
};

export type EmailTestResult = {
  imap: boolean;
  smtp: boolean;
  folders: number;
  capabilities: string[];
  inbox_ok?: boolean;
  smtp_error?: string;
};

export type EmailStats = {
  accounts: number;
  default_id: string | null;
  by_provider: { value: string; label: string; count: number }[];
  last_sync_at: string | null;
  errors: { id: string; email_address: string; error: string }[];
};

export type EmailSendPayload = {
  to: string;
  cc?: string;
  bcc?: string;
  subject: string;
  body_text: string;
  body_html?: string;
  in_reply_to?: string;
  references?: string;
  include_signature?: boolean;
  attachments?: { filename: string; content_type?: string; data: string }[];
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

export function getEmailMeta(): Promise<{ total: number; items: EmailProvider[] }> {
  return request(`/email/meta`);
}

export function getEmailStats(): Promise<EmailStats> {
  return request(`/email/stats`);
}

export function listEmailAccounts(): Promise<EmailAccountList> {
  return request(`/email/accounts`);
}

export function saveEmailAccount(draft: EmailAccountDraft): Promise<{ saved: boolean; account: EmailAccount }> {
  return request(`/email/accounts`, withBody("POST", draft));
}

export function deleteEmailAccount(id: string): Promise<{ deleted: boolean; id: string }> {
  return request(`/email/accounts/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function testEmailAccountDraft(draft: EmailAccountDraft): Promise<EmailTestResult> {
  return request(`/email/accounts/test`, withBody("POST", draft));
}

export function testEmailAccount(id: string): Promise<EmailTestResult> {
  return request(`/email/accounts/${encodeURIComponent(id)}/test`, withBody("POST"));
}

export function listEmailFolders(accountId: string): Promise<EmailFolderList> {
  return request(`/email/accounts/${encodeURIComponent(accountId)}/folders`);
}

export function listEmailMessages(
  accountId: string,
  options: { folder?: string; limit?: number; offset?: number; q?: string; unread?: boolean; flagged?: boolean } = {},
): Promise<EmailMessageList> {
  const params = new URLSearchParams();
  params.set("folder", options.folder || "INBOX");
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  if (options.q) params.set("q", options.q);
  if (options.unread) params.set("unread", "true");
  if (options.flagged) params.set("flagged", "true");
  return request(`/email/accounts/${encodeURIComponent(accountId)}/messages?${params.toString()}`);
}

export function getEmailMessage(
  accountId: string,
  uid: string,
  options: { folder?: string; markRead?: boolean } = {},
): Promise<{ message: EmailMessage; account: EmailAccount }> {
  const params = new URLSearchParams();
  params.set("folder", options.folder || "INBOX");
  if (options.markRead === false) params.set("mark_read", "false");
  return request(`/email/accounts/${encodeURIComponent(accountId)}/messages/${encodeURIComponent(uid)}?${params.toString()}`);
}

export function setEmailFlags(
  accountId: string,
  uid: string,
  action: "read" | "unread" | "flag" | "unflag",
  folder = "INBOX",
): Promise<{ updated: boolean; uid: string; action: string }> {
  return request(
    `/email/accounts/${encodeURIComponent(accountId)}/messages/${encodeURIComponent(uid)}/flags`,
    withBody("POST", { action, folder }),
  );
}

export function moveEmailMessage(
  accountId: string,
  uid: string,
  target: string,
  folder = "INBOX",
): Promise<{ moved: boolean; uid: string; from: string; to: string }> {
  return request(
    `/email/accounts/${encodeURIComponent(accountId)}/messages/${encodeURIComponent(uid)}/move`,
    withBody("POST", { target, folder }),
  );
}

export function deleteEmailMessage(
  accountId: string,
  uid: string,
  folder = "INBOX",
): Promise<{ deleted: boolean; uid: string; folder: string }> {
  const params = new URLSearchParams({ folder });
  return request(`/email/accounts/${encodeURIComponent(accountId)}/messages/${encodeURIComponent(uid)}?${params}`, {
    method: "DELETE",
  });
}

export function sendEmail(accountId: string, payload: EmailSendPayload): Promise<{ sent: boolean; message_id: string; to: string[] }> {
  return request(`/email/accounts/${encodeURIComponent(accountId)}/send`, withBody("POST", payload));
}

/* ------------------------------------------------------------------ auxiliares */

/** Nome apresentável de um remetente («Ana Silva <ana@x.pt>» → «Ana Silva»). */
export function displayAddress(address?: EmailAddress | null): string {
  if (!address) return "";
  return address.name || address.email || "";
}

/** Lista de destinatários em texto simples. */
export function addressListText(addresses?: EmailAddress[] | null): string {
  if (!addresses?.length) return "";
  return addresses.map((item) => (item.name ? `${item.name} <${item.email}>` : item.email)).join(", ");
}

/** Data curta relativa ao dia de hoje (hora se for de hoje, senão dia/mês). */
export function formatMessageDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  const sameYear = date.getFullYear() === now.getFullYear();
  if (sameYear) return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "short" });
  return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

/** Data e hora completas, para a leitura da mensagem. */
export function formatFullDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("pt-PT", { dateStyle: "long", timeStyle: "short" });
}

/** Tamanho legível de um anexo. */
export function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value < 10 && index > 0 ? 1 : 0)} ${units[index]}`;
}

/** Iniciais para o avatar redondo de um remetente. */
export function initialsOf(address?: EmailAddress | null): string {
  const source = displayAddress(address);
  if (!source) return "?";
  const parts = source.replace(/["']/g, "").trim().split(/[\s@.]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

/** Cor estável (de uma paleta) a partir do endereço, para o avatar. */
const AVATAR_COLORS = [
  "bg-teal-500/20 text-teal-200",
  "bg-sky-500/20 text-sky-200",
  "bg-indigo-500/20 text-indigo-200",
  "bg-violet-500/20 text-violet-200",
  "bg-rose-500/20 text-rose-200",
  "bg-amber-500/20 text-amber-100",
  "bg-emerald-500/20 text-emerald-200",
];

export function avatarColor(address?: EmailAddress | null): string {
  const source = (address?.email || displayAddress(address) || "?").toLowerCase();
  let hash = 0;
  for (let index = 0; index < source.length; index += 1) hash = (hash * 31 + source.charCodeAt(index)) % 997;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}
