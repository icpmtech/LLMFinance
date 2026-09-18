/**
 * Aplicação «Email» do IQ OS.
 *
 * A caixa de correio dentro da plataforma, com três colunas: as **pastas** da
 * conta (com contagens de não lidas), a **lista de mensagens** (pesquisa,
 * filtro de não lidas e paginação) e a **leitura** da mensagem (texto ou HTML
 * isolado, anexos e ações). Uma barra de conta no topo permite alternar entre
 * várias caixas e ligar novas.
 *
 * Integra-se com Gmail, Outlook/Microsoft 365, iCloud, Yahoo, Zoho, SAPO e com
 * qualquer servidor IMAP/SMTP: as contas são configuradas no assistente
 * «Ligar conta», que traz os servidores já preenchidos por fornecedor e testa a
 * ligação antes de guardar.
 *
 * O envio aceita destinatários, CC/BCC, anexos e respostas encadeadas
 * (`In-Reply-To`/`References`), para a conversa continuar no fio certo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  Ban,
  Check,
  CheckCheck,
  ChevronDown,
  FileEdit,
  Inbox,
  Loader2,
  Mail,
  MailOpen,
  Paperclip,
  PenLine,
  Plug,
  Plus,
  RefreshCw,
  Reply,
  Search,
  Send,
  ShieldCheck,
  Star,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { Button } from "../components/ui";
import { useAuth } from "../auth";
import {
  addressListText,
  avatarColor,
  deleteEmailAccount,
  deleteEmailMessage,
  displayAddress,
  formatBytes,
  formatFullDate,
  formatMessageDate,
  getEmailMessage,
  initialsOf,
  listEmailAccounts,
  listEmailFolders,
  listEmailMessages,
  moveEmailMessage,
  saveEmailAccount,
  sendEmail,
  setEmailFlags,
  testEmailAccount,
  testEmailAccountDraft,
  type EmailAccount,
  type EmailAccountDraft,
  type EmailFolder,
  type EmailMessage,
  type EmailMessageSummary,
  type EmailProvider,
  type EmailSendPayload,
  getEmailMeta,
} from "../emailApi";

const ACCOUNT_KEY = "finance-llm-email-account";
const FOLDER_KEY = "finance-llm-email-folder";

/* ------------------------------------------------------------------ aspeto */

const FOLDER_ICONS: { test: (folder: EmailFolder) => boolean; icon: LucideIcon; className: string }[] = [
  { test: (folder) => (folder.name || "").toUpperCase() === "INBOX", icon: Inbox, className: "text-teal-300" },
  { test: (folder) => Boolean(folder.sent), icon: Send, className: "text-sky-300" },
  { test: (folder) => Boolean(folder.drafts), icon: FileEdit, className: "text-amber-300" },
  { test: (folder) => Boolean(folder.archive), icon: Archive, className: "text-violet-300" },
  { test: (folder) => Boolean(folder.junk), icon: Ban, className: "text-rose-300" },
  { test: (folder) => Boolean(folder.trash), icon: Trash2, className: "text-rose-300" },
];

function folderIcon(folder: EmailFolder): { Icon: LucideIcon; className: string } {
  const match = FOLDER_ICONS.find((entry) => entry.test(folder));
  return match ? { Icon: match.icon, className: match.className } : { Icon: Mail, className: "text-slate-300" };
}

/** Pastas usadas como destino de «mover para…» (sem a pasta atual). */
function moveTargets(folders: EmailFolder[], current: string): EmailFolder[] {
  return folders.filter((folder) => folder.selectable && folder.id !== current).slice(0, 12);
}

/* --------------------------------------------------------------- diálogos */

function Modal({
  title,
  hint,
  onClose,
  children,
  wide,
}: {
  title: string;
  hint?: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="absolute inset-0" onMouseDown={onClose} aria-hidden="true" />
      <div
        className={`relative z-10 flex max-h-[86vh] w-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0d1418] shadow-2xl ${
          wide ? "max-w-3xl" : "max-w-xl"
        }`}
      >
        <header className="flex items-start justify-between gap-3 border-b border-white/8 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-foreground">{title}</h2>
            {hint && <p className="mt-0.5 text-[12px] text-muted-foreground">{hint}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
          >
            <X size={15} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      </div>
    </div>
  );
}

const FIELD = "w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-[13px] text-foreground placeholder:text-muted-foreground/60 focus:border-teal-300/50 focus:outline-none";
const LABEL = "mb-1 block text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground";

type AccountForm = EmailAccountDraft & { id?: string };

function emptyForm(providers: EmailProvider[]): AccountForm {
  const preset = providers.find((entry) => entry.id === "gmail") ?? providers[0];
  return {
    provider: preset?.id ?? "custom",
    email_address: "",
    display_name: "",
    password: "",
    imap_host: preset?.imap_host ?? "",
    imap_port: preset?.imap_port ?? 993,
    imap_security: preset?.imap_security ?? "ssl",
    smtp_host: preset?.smtp_host ?? "",
    smtp_port: preset?.smtp_port ?? 587,
    smtp_security: preset?.smtp_security ?? "starttls",
    signature: "",
    is_default: true,
  };
}

function AccountDialog({
  providers,
  initial,
  onClose,
  onSaved,
}: {
  providers: EmailProvider[];
  initial?: EmailAccount | null;
  onClose: () => void;
  onSaved: (account: EmailAccount) => void;
}) {
  const [form, setForm] = useState<AccountForm>(() =>
    initial
      ? {
          id: initial.id,
          provider: initial.provider,
          email_address: initial.email_address,
          display_name: initial.display_name ?? "",
          username: initial.username,
          password: "",
          imap_host: initial.imap_host,
          imap_port: initial.imap_port,
          imap_security: initial.imap_security,
          smtp_host: initial.smtp_host,
          smtp_port: initial.smtp_port,
          smtp_security: initial.smtp_security,
          signature: initial.signature ?? "",
          is_default: Boolean(initial.is_default),
        }
      : emptyForm(providers),
  );
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(Boolean(initial));

  const preset = providers.find((entry) => entry.id === form.provider) ?? providers[0];

  const patch = (next: Partial<AccountForm>) => setForm((current) => ({ ...current, ...next }));

  const chooseProvider = (providerId: string) => {
    const entry = providers.find((item) => item.id === providerId);
    if (!entry) return;
    patch({
      provider: entry.id,
      imap_host: entry.imap_host,
      imap_port: entry.imap_port,
      imap_security: entry.imap_security,
      smtp_host: entry.smtp_host,
      smtp_port: entry.smtp_port,
      smtp_security: entry.smtp_security,
    });
  };

  const runTest = async () => {
    setBusy("test");
    setError(null);
    setNotice(null);
    try {
      const result = await testEmailAccountDraft(form);
      if (result.imap && result.smtp) {
        setNotice(`Ligação confirmada: IMAP OK, SMTP OK${result.folders ? `, ${result.folders} pastas` : ""}.`);
      } else {
        setNotice(
          `IMAP: ${result.imap ? "OK" : "falhou"} · SMTP: ${result.smtp ? "OK" : "falhou"}${
            result.smtp_error ? ` (${result.smtp_error})` : ""
          }`,
        );
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const runSave = async () => {
    setBusy("save");
    setError(null);
    try {
      const result = await saveEmailAccount(form);
      onSaved(result.account);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      title={initial ? "Editar conta de email" : "Ligar conta de email"}
      hint="Escolha o fornecedor — os servidores ficam preenchidos automaticamente — e confirme a ligação."
      onClose={onClose}
    >
      <div className="flex flex-col gap-3">
        <div>
          <label className={LABEL} htmlFor="email-provider">
            Fornecedor
          </label>
          <select
            id="email-provider"
            value={form.provider}
            onChange={(event) => chooseProvider(event.target.value)}
            className={FIELD}
          >
            {providers.map((entry) => (
              <option key={entry.id} value={entry.id} className="bg-[#0d1418]">
                {entry.label}
              </option>
            ))}
          </select>
        </div>

        {preset?.help && (
          <p className="flex items-start gap-2 rounded-lg border border-teal-300/20 bg-teal-400/5 px-3 py-2 text-[12px] text-teal-100">
            <ShieldCheck size={14} className="mt-0.5 shrink-0" />
            <span>
              {preset.help}
              {preset.docs_url && (
                <>
                  {" "}
                  <a className="underline decoration-dotted" href={preset.docs_url} target="_blank" rel="noreferrer">
                    Saber mais
                  </a>
                </>
              )}
            </span>
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-1">
            <label className={LABEL} htmlFor="email-address">
              Endereço de email
            </label>
            <input
              id="email-address"
              type="email"
              autoComplete="off"
              value={form.email_address}
              onChange={(event) => patch({ email_address: event.target.value })}
              placeholder="nome@empresa.pt"
              className={FIELD}
            />
          </div>
          <div className="sm:col-span-1">
            <label className={LABEL} htmlFor="email-name">
              Nome a mostrar
            </label>
            <input
              id="email-name"
              value={form.display_name ?? ""}
              onChange={(event) => patch({ display_name: event.target.value })}
              placeholder="Ana Silva"
              className={FIELD}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={LABEL} htmlFor="email-password">
              {initial ? "Palavra-passe (deixe vazio para manter)" : "Palavra-passe / palavra-passe de aplicação"}
            </label>
            <input
              id="email-password"
              type="password"
              autoComplete="new-password"
              value={form.password ?? ""}
              onChange={(event) => patch({ password: event.target.value })}
              placeholder="••••••••••••"
              className={FIELD}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setAdvanced((value) => !value)}
          className="flex w-full items-center gap-1.5 text-[12px] font-medium text-muted-foreground transition hover:text-foreground"
        >
          <ChevronDown size={13} className={advanced ? "rotate-180 transition" : "transition"} />
          Servidores IMAP/SMTP {advanced ? "(a editar)" : "(preenchidos pelo fornecedor)"}
        </button>

        {advanced && (
          <div className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.02] p-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="imap-host">
                Servidor IMAP
              </label>
              <input id="imap-host" value={form.imap_host ?? ""} onChange={(event) => patch({ imap_host: event.target.value })} className={FIELD} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={LABEL} htmlFor="imap-port">
                  Porta
                </label>
                <input
                  id="imap-port"
                  type="number"
                  value={form.imap_port ?? 993}
                  onChange={(event) => patch({ imap_port: Number(event.target.value) })}
                  className={FIELD}
                />
              </div>
              <div>
                <label className={LABEL} htmlFor="imap-security">
                  Segurança
                </label>
                <select
                  id="imap-security"
                  value={form.imap_security ?? "ssl"}
                  onChange={(event) => patch({ imap_security: event.target.value })}
                  className={FIELD}
                >
                  <option value="ssl" className="bg-[#0d1418]">
                    SSL/TLS
                  </option>
                  <option value="starttls" className="bg-[#0d1418]">
                    STARTTLS
                  </option>
                </select>
              </div>
            </div>
            <div>
              <label className={LABEL} htmlFor="smtp-host">
                Servidor SMTP
              </label>
              <input id="smtp-host" value={form.smtp_host ?? ""} onChange={(event) => patch({ smtp_host: event.target.value })} className={FIELD} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={LABEL} htmlFor="smtp-port">
                  Porta
                </label>
                <input
                  id="smtp-port"
                  type="number"
                  value={form.smtp_port ?? 587}
                  onChange={(event) => patch({ smtp_port: Number(event.target.value) })}
                  className={FIELD}
                />
              </div>
              <div>
                <label className={LABEL} htmlFor="smtp-security">
                  Segurança
                </label>
                <select
                  id="smtp-security"
                  value={form.smtp_security ?? "starttls"}
                  onChange={(event) => patch({ smtp_security: event.target.value })}
                  className={FIELD}
                >
                  <option value="ssl" className="bg-[#0d1418]">
                    SSL/TLS
                  </option>
                  <option value="starttls" className="bg-[#0d1418]">
                    STARTTLS
                  </option>
                </select>
              </div>
            </div>
            <div className="sm:col-span-2">
              <label className={LABEL} htmlFor="email-signature">
                Assinatura
              </label>
              <textarea
                id="email-signature"
                rows={2}
                value={form.signature ?? ""}
                onChange={(event) => patch({ signature: event.target.value })}
                placeholder={"Ana Silva\nDireção Financeira · +351 210 000 000"}
                className={FIELD}
              />
            </div>
          </div>
        )}

        <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <input
            type="checkbox"
            checked={Boolean(form.is_default)}
            onChange={(event) => patch({ is_default: event.target.checked })}
            className="h-3.5 w-3.5 rounded border-white/20 bg-white/5"
          />
          Usar como conta por omissão nesta app
        </label>

        {notice && (
          <p className="flex items-start gap-2 rounded-lg border border-sky-300/20 bg-sky-400/5 px-3 py-2 text-[12px] text-sky-100">
            <Check size={14} className="mt-0.5 shrink-0" /> {notice}
          </p>
        )}
        {error && (
          <p className="flex items-start gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}

        <footer className="flex items-center justify-between gap-2 border-t border-white/8 pt-3">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancelar
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void runTest()} loading={busy === "test"} icon={<Plug size={13} />}>
              Testar ligação
            </Button>
            <Button size="sm" onClick={() => void runSave()} loading={busy === "save"} icon={<Check size={13} />}>
              {initial ? "Guardar" : "Ligar conta"}
            </Button>
          </div>
        </footer>
      </div>
    </Modal>
  );
}

type ComposeState = EmailSendPayload & { attachments: { filename: string; content_type?: string; data: string }[] };

function ComposeDialog({
  account,
  replyTo,
  onClose,
  onSent,
}: {
  account: EmailAccount;
  replyTo?: EmailMessage | null;
  onClose: () => void;
  onSent: () => void;
}) {
  const [form, setForm] = useState<ComposeState>(() => ({
    to: replyTo ? addressListText(replyTo.from) : "",
    cc: replyTo ? addressListText(replyTo.cc) : "",
    bcc: "",
    subject: replyTo ? (replyTo.subject.startsWith("Re:") ? replyTo.subject : `Re: ${replyTo.subject}`) : "",
    body_text: replyTo
      ? `\n\n--- Em ${formatFullDate(replyTo.date)}, ${displayAddress(replyTo.from[0])} escreveu: ---\n${replyTo.body_text
          .split("\n")
          .map((line) => `> ${line}`)
          .join("\n")}`
      : "",
    in_reply_to: replyTo?.message_id || undefined,
    references: replyTo ? [replyTo.references, replyTo.message_id].filter(Boolean).join(" ") : undefined,
    include_signature: true,
    attachments: [],
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCc, setShowCc] = useState(Boolean(form.cc));
  const fileRef = useRef<HTMLInputElement | null>(null);

  const patch = (next: Partial<ComposeState>) => setForm((current) => ({ ...current, ...next }));

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const added: { filename: string; content_type?: string; data: string }[] = [];
    for (const file of Array.from(files)) {
      if (file.size > 12 * 1024 * 1024) {
        setError(`O ficheiro «${file.name}» excede 12 MB.`);
        continue;
      }
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
      added.push({ filename: file.name, content_type: file.type || undefined, data: dataUrl.split(",", 2)[1] ?? "" });
    }
    if (added.length) patch({ attachments: [...form.attachments, ...added] });
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await sendEmail(account.id, form);
      onSent();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={replyTo ? "Responder" : "Nova mensagem"}
      hint={`De ${account.display_name || account.email_address}`}
      onClose={onClose}
      wide
    >
      <div className="flex flex-col gap-3">
        <div>
          <label className={LABEL} htmlFor="compose-to">
            Para
          </label>
          <div className="flex items-center gap-2">
            <input
              id="compose-to"
              value={form.to}
              onChange={(event) => patch({ to: event.target.value })}
              placeholder="nome@empresa.pt, outro@empresa.pt"
              className={FIELD}
            />
            {!showCc && (
              <button
                type="button"
                onClick={() => setShowCc(true)}
                className="shrink-0 text-[12px] font-medium text-muted-foreground transition hover:text-foreground"
              >
                CC/BCC
              </button>
            )}
          </div>
        </div>

        {showCc && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="compose-cc">
                CC
              </label>
              <input id="compose-cc" value={form.cc ?? ""} onChange={(event) => patch({ cc: event.target.value })} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="compose-bcc">
                BCC
              </label>
              <input id="compose-bcc" value={form.bcc ?? ""} onChange={(event) => patch({ bcc: event.target.value })} className={FIELD} />
            </div>
          </div>
        )}

        <div>
          <label className={LABEL} htmlFor="compose-subject">
            Assunto
          </label>
          <input
            id="compose-subject"
            value={form.subject}
            onChange={(event) => patch({ subject: event.target.value })}
            className={FIELD}
          />
        </div>

        <div>
          <label className={LABEL} htmlFor="compose-body">
            Mensagem
          </label>
          <textarea
            id="compose-body"
            rows={12}
            value={form.body_text}
            onChange={(event) => patch({ body_text: event.target.value })}
            placeholder="Escreva a mensagem…"
            className={`${FIELD} font-mono leading-relaxed`}
          />
        </div>

        {form.attachments.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {form.attachments.map((item, index) => (
              <li
                key={`${item.filename}-${index}`}
                className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px]"
              >
                <Paperclip size={12} className="text-muted-foreground" />
                <span className="max-w-[220px] truncate">{item.filename}</span>
                <button
                  type="button"
                  aria-label={`Remover ${item.filename}`}
                  onClick={() => patch({ attachments: form.attachments.filter((_, position) => position !== index) })}
                  className="text-muted-foreground transition hover:text-rose-300"
                >
                  <X size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <input
            type="checkbox"
            checked={form.include_signature !== false}
            onChange={(event) => patch({ include_signature: event.target.checked })}
            className="h-3.5 w-3.5 rounded border-white/20 bg-white/5"
          />
          Incluir assinatura da conta
        </label>

        {error && (
          <p className="flex items-start gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}

        <footer className="flex items-center justify-between gap-2 border-t border-white/8 pt-3">
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" multiple hidden onChange={(event) => void addFiles(event.target.files)} />
            <Button variant="outline" size="sm" icon={<Paperclip size={13} />} onClick={() => fileRef.current?.click()}>
              Anexar
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Descartar
            </Button>
            <Button size="sm" loading={busy} icon={<Send size={13} />} onClick={() => void submit()}>
              Enviar
            </Button>
          </div>
        </footer>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ página */

export default function EmailPage({ initialAccountId }: { initialAccountId?: string | null } = {}) {
  const { user } = useAuth();
  const [providers, setProviders] = useState<EmailProvider[]>([]);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [accountId, setAccountId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return initialAccountId || window.localStorage.getItem(ACCOUNT_KEY);
  });
  const [folders, setFolders] = useState<EmailFolder[]>([]);
  const [folder, setFolder] = useState<string>(() => {
    if (typeof window === "undefined") return "INBOX";
    return window.localStorage.getItem(FOLDER_KEY) || "INBOX";
  });
  const [messages, setMessages] = useState<EmailMessageSummary[]>([]);
  const [list, setList] = useState<{ total: number; has_more: boolean }>({ total: 0, has_more: false });
  const [message, setMessage] = useState<EmailMessage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [showHtml, setShowHtml] = useState(false);
  const [accountDialog, setAccountDialog] = useState<{ open: boolean; editing: EmailAccount | null }>({ open: false, editing: null });
  const [compose, setCompose] = useState<{ open: boolean; replyTo: EmailMessage | null }>({ open: false, replyTo: null });
  const [moveOpen, setMoveOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const account = useMemo(() => accounts.find((item) => item.id === accountId) ?? null, [accounts, accountId]);

  /* Pesquisa com atraso (não dispara um pedido por tecla). */
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 420);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (accountId) window.localStorage.setItem(ACCOUNT_KEY, accountId);
  }, [accountId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(FOLDER_KEY, folder);
  }, [folder]);

  /* Arranque: catálogo de fornecedores e contas do utilizador. */
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [meta, accountList] = await Promise.all([getEmailMeta(), listEmailAccounts()]);
        if (!alive) return;
        setProviders(meta.items);
        setAccounts(accountList.items);
        setAccountId((current) => {
          if (current && accountList.items.some((item) => item.id === current)) return current;
          return accountList.default_id ?? accountList.items[0]?.id ?? null;
        });
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const loadFolders = useCallback(
    async (id: string) => {
      try {
        const payload = await listEmailFolders(id);
        setFolders(payload.items);
        setFolder((current) => (payload.items.some((item) => item.id === current) ? current : "INBOX"));
      } catch (exc) {
        setFolders([]);
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    },
    [],
  );

  useEffect(() => {
    if (!accountId) {
      setFolders([]);
      setMessages([]);
      setMessage(null);
      return;
    }
    void loadFolders(accountId);
  }, [accountId, loadFolders]);

  const loadMessages = useCallback(
    async (options: { append?: boolean; offset?: number } = {}) => {
      if (!accountId) return;
      setLoadingList(true);
      setError(null);
      try {
        const payload = await listEmailMessages(accountId, {
          folder,
          limit: 40,
          offset: options.offset ?? 0,
          q: search || undefined,
          unread: unreadOnly,
        });
        setMessages((current) => (options.append ? [...current, ...payload.items] : payload.items));
        setList({ total: payload.total, has_more: payload.has_more });
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
        if (!options.append) setMessages([]);
      } finally {
        setLoadingList(false);
      }
    },
    [accountId, folder, search, unreadOnly],
  );

  useEffect(() => {
    setMessage(null);
    void loadMessages();
  }, [loadMessages]);

  const openMessage = async (uid: string) => {
    if (!accountId) return;
    setLoadingMessage(true);
    setError(null);
    try {
      const payload = await getEmailMessage(accountId, uid, { folder });
      setMessage(payload.message);
      setShowHtml(Boolean(payload.message.body_html) && !payload.message.body_text.trim());
      if (payload.message.unread === false) {
        setMessages((current) => current.map((item) => (item.uid === uid ? { ...item, unread: false } : item)));
      }
      if (accountId) void loadFolders(accountId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoadingMessage(false);
    }
  };

  const runFlag = async (uid: string, action: "read" | "unread" | "flag" | "unflag") => {
    if (!accountId) return;
    setBusyAction(`${action}:${uid}`);
    try {
      await setEmailFlags(accountId, uid, action, folder);
      setMessages((current) =>
        current.map((item) =>
          item.uid === uid
            ? { ...item, unread: action === "read" ? false : action === "unread" ? true : item.unread, flagged: action === "flag" ? true : action === "unflag" ? false : item.flagged }
            : item,
        ),
      );
      setMessage((current) =>
        current && current.uid === uid
          ? {
              ...current,
              unread: action === "read" ? false : action === "unread" ? true : current.unread,
              flagged: action === "flag" ? true : action === "unflag" ? false : current.flagged,
            }
          : current,
      );
      if (accountId) void loadFolders(accountId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyAction(null);
    }
  };

  const runDelete = async (uid: string) => {
    if (!accountId) return;
    setBusyAction(`delete:${uid}`);
    try {
      await deleteEmailMessage(accountId, uid, folder);
      setMessages((current) => current.filter((item) => item.uid !== uid));
      setList((current) => ({ ...current, total: Math.max(0, current.total - 1) }));
      if (message?.uid === uid) setMessage(null);
      void loadFolders(accountId);
      setNotice("Mensagem apagada.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyAction(null);
    }
  };

  const runMove = async (target: string) => {
    if (!accountId || !message) return;
    setBusyAction("move");
    try {
      await moveEmailMessage(accountId, message.uid, target, folder);
      setMessages((current) => current.filter((item) => item.uid !== message.uid));
      setMessage(null);
      setMoveOpen(false);
      void loadFolders(accountId);
      setNotice(`Mensagem movida para «${target}».`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyAction(null);
    }
  };

  const removeAccount = async (target: EmailAccount) => {
    if (!window.confirm(`Remover a conta ${target.email_address} da plataforma? O correio no servidor não é alterado.`)) return;
    try {
      await deleteEmailAccount(target.id);
      const accountList = await listEmailAccounts();
      setAccounts(accountList.items);
      setAccountId(accountList.default_id ?? accountList.items[0]?.id ?? null);
      setNotice("Conta removida.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const testSaved = async (target: EmailAccount) => {
    setBusyAction(`test:${target.id}`);
    setError(null);
    try {
      const result = await testEmailAccount(target.id);
      setNotice(`IMAP: ${result.imap ? "OK" : "falhou"} · SMTP: ${result.smtp ? "OK" : "falhou"}${result.smtp_error ? ` (${result.smtp_error})` : ""}.`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyAction(null);
    }
  };

  /* Aviso do sistema: as contas ligadas ficam no servidor, a palavra-passe nunca é devolvida. */
  const unreadTotal = folders.reduce((total, item) => total + (item.unseen ?? 0), 0);

  if (loading) {
    return (
      <div className="grid min-h-[320px] place-items-center">
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar o Email…
        </p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="grid min-h-[320px] place-items-center px-6 text-center">
        <div className="max-w-md">
          <Mail size={22} className="mx-auto text-muted-foreground" />
          <p className="mt-2 text-[13px] text-muted-foreground">
            Entre na plataforma para ligar a sua caixa de correio. As contas são guardadas por utilizador.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="@container flex h-full min-h-[560px] flex-col bg-background text-foreground">
      {/* ---------------------------------------------------------- topo */}
      <header className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 py-2 backdrop-blur-xl md:top-0">
        <div className="flex flex-wrap items-center gap-2 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-teal-400 to-sky-500 text-white">
            <Mail size={15} />
          </span>
          <h1 className="text-[14px] font-semibold">Email</h1>

          {accounts.length > 0 && (
            <div className="relative">
              <select
                value={accountId ?? ""}
                onChange={(event) => setAccountId(event.target.value || null)}
                className="max-w-[280px] appearance-none rounded-lg border border-white/10 bg-white/[0.05] py-1 pl-2.5 pr-7 text-[12.5px] text-foreground focus:border-teal-300/50 focus:outline-none"
                aria-label="Conta de email"
              >
                {accounts.map((item) => (
                  <option key={item.id} value={item.id} className="bg-[#0d1418]">
                    {item.label || item.email_address}
                    {item.is_default ? " (omissão)" : ""}
                  </option>
                ))}
              </select>
              <ChevronDown size={13} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
            </div>
          )}

          {unreadTotal > 0 && (
            <span className="rounded-full bg-teal-400/15 px-2 py-0.5 text-[11px] font-medium text-teal-200">
              {unreadTotal} não lidas
            </span>
          )}

          <div className="min-w-0 flex-1" />

          {account && (
            <>
              <Button variant="outline" size="sm" onClick={() => void testSaved(account)} loading={busyAction === `test:${account.id}`} icon={<Plug size={13} />}>
                Testar
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setAccountDialog({ open: true, editing: account })}
                icon={<FileEdit size={13} />}
              >
                Editar conta
              </Button>
              <Button variant="ghost" size="sm" onClick={() => void removeAccount(account)} icon={<Trash2 size={13} />}>
                Remover
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={() => setAccountDialog({ open: true, editing: null })} icon={<Plus size={13} />}>
            Ligar conta
          </Button>
          <Button
            size="sm"
            disabled={!account}
            onClick={() => setCompose({ open: true, replyTo: null })}
            icon={<PenLine size={13} />}
          >
            Escrever
          </Button>
        </div>
      </header>

      {(error || notice) && (
        <div className="flex flex-col gap-1 px-4 pt-2">
          {error && (
            <p className="flex items-start gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
              <TriangleAlert size={14} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1">{error}</span>
              <button type="button" onClick={() => setError(null)} aria-label="Fechar aviso">
                <X size={13} />
              </button>
            </p>
          )}
          {notice && (
            <p className="flex items-start gap-2 rounded-lg border border-sky-300/20 bg-sky-400/5 px-3 py-2 text-[12px] text-sky-100">
              <Check size={14} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1">{notice}</span>
              <button type="button" onClick={() => setNotice(null)} aria-label="Fechar aviso">
                <X size={13} />
              </button>
            </p>
          )}
        </div>
      )}

      {/* ------------------------------------------------------ três colunas */}
      {accounts.length === 0 ? (
        <div className="grid flex-1 place-items-center px-6 py-10">
          <div className="max-w-lg rounded-2xl border border-white/10 bg-white/[0.03] p-6 text-center">
            <span className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-teal-400 to-sky-500 text-white">
              <Mail size={20} />
            </span>
            <h2 className="mt-3 text-[15px] font-semibold">Traga o seu correio para o IQ OS</h2>
            <p className="mt-1 text-[12.5px] text-muted-foreground">
              Ligue o Gmail, o Outlook/Microsoft 365, o iCloud, o Yahoo, o SAPO ou qualquer servidor IMAP/SMTP e leia,
              organize e escreva mensagens dentro da plataforma.
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
              {providers
                .filter((entry) => entry.id !== "custom")
                .map((entry) => (
                  <span key={entry.id} className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] text-muted-foreground">
                    {entry.label}
                  </span>
                ))}
            </div>
            <div className="mt-5 flex justify-center">
              <Button onClick={() => setAccountDialog({ open: true, editing: null })} icon={<Plug size={14} />}>
                Ligar a primeira conta
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[210px_minmax(280px,1fr)_minmax(320px,1.4fr)]">
          {/* ------------------------------------------------- pastas */}
          <aside className="min-h-0 border-b border-white/8 lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between gap-2 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold uppercase tracking-wide text-muted-foreground">Pastas</h2>
              <button
                type="button"
                onClick={() => accountId && void loadFolders(accountId)}
                aria-label="Recarregar pastas"
                className="grid h-6 w-6 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              >
                <RefreshCw size={12} />
              </button>
            </div>
            <ul className="max-h-[220px] overflow-y-auto px-1.5 pb-2 lg:max-h-[calc(100vh-230px)]">
              {folders.length === 0 && <li className="px-2 py-1 text-[12px] text-muted-foreground">Sem pastas.</li>}
              {folders
                .filter((item) => item.selectable)
                .map((item) => {
                  const { Icon, className } = folderIcon(item);
                  const active = item.id === folder;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setFolder(item.id);
                          setMessage(null);
                        }}
                        className={[
                          "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] transition",
                          active ? "bg-white/[0.12] font-medium text-foreground" : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground",
                        ].join(" ")}
                      >
                        <Icon size={14} className={active ? "text-teal-300" : className} />
                        <span className="min-w-0 flex-1 truncate">{item.label || item.name}</span>
                        {item.unseen ? (
                          <span className="rounded-full bg-teal-400/20 px-1.5 text-[10.5px] font-semibold text-teal-100">{item.unseen}</span>
                        ) : item.messages ? (
                          <span className="text-[10.5px] text-muted-foreground/70">{item.messages}</span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
            </ul>
          </aside>

          {/* ------------------------------------------------ lista */}
          <section className="flex min-h-0 flex-col border-b border-white/8 lg:border-b-0 lg:border-r">
            <div className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
              <div className="relative min-w-0 flex-1">
                <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/75" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Pesquisar assunto ou remetente…"
                  className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2 text-[12.5px] placeholder:text-muted-foreground/60 focus:border-teal-300/50 focus:outline-none"
                />
              </div>
              <button
                type="button"
                onClick={() => setUnreadOnly((value) => !value)}
                aria-pressed={unreadOnly}
                title="Mostrar apenas não lidas"
                className={[
                  "shrink-0 rounded-lg border px-2 py-1.5 text-[11.5px] transition",
                  unreadOnly
                    ? "border-teal-300/40 bg-teal-400/15 text-teal-100"
                    : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground",
                ].join(" ")}
              >
                Não lidas
              </button>
              <button
                type="button"
                onClick={() => void loadMessages()}
                aria-label="Recarregar mensagens"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              >
                <RefreshCw size={13} className={loadingList ? "animate-spin" : undefined} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {loadingList && messages.length === 0 && (
                <p className="flex items-center gap-2 px-3 py-4 text-[12.5px] text-muted-foreground">
                  <Loader2 size={13} className="animate-spin" /> A carregar mensagens…
                </p>
              )}
              {!loadingList && messages.length === 0 && (
                <p className="px-3 py-6 text-center text-[12.5px] text-muted-foreground">
                  {search ? "Nada encontrado para esta pesquisa." : "Sem mensagens nesta pasta."}
                </p>
              )}
              <ul>
                {messages.map((item) => {
                  const active = message?.uid === item.uid;
                  const from = item.from[0];
                  return (
                    <li key={item.uid}>
                      <button
                        type="button"
                        onClick={() => void openMessage(item.uid)}
                        className={[
                          "flex w-full gap-2.5 border-b border-white/5 px-3 py-2.5 text-left transition",
                          active ? "bg-white/[0.1]" : "hover:bg-white/[0.05]",
                        ].join(" ")}
                      >
                        <span
                          className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10.5px] font-semibold ${avatarColor(from)}`}
                        >
                          {initialsOf(from)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-baseline justify-between gap-2">
                            <span className={item.unread ? "truncate text-[12.5px] font-semibold text-foreground" : "truncate text-[12.5px] text-foreground/85"}>
                              {displayAddress(from) || "Desconhecido"}
                            </span>
                            <span className="shrink-0 text-[10.5px] text-muted-foreground">{formatMessageDate(item.date)}</span>
                          </span>
                          <span className="mt-0.5 flex items-center gap-1.5">
                            {item.flagged && <Star size={11} className="shrink-0 fill-amber-300 text-amber-300" />}
                            <span className={item.unread ? "truncate text-[12px] font-medium" : "truncate text-[12px] text-muted-foreground"}>
                              {item.subject}
                            </span>
                          </span>
                          {item.preview && <span className="mt-0.5 line-clamp-2 block text-[11.5px] text-muted-foreground/80">{item.preview}</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {list.has_more && (
                <div className="p-3">
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    loading={loadingList}
                    onClick={() => void loadMessages({ append: true, offset: messages.length })}
                  >
                    Carregar mais ({list.total - messages.length} de {list.total})
                  </Button>
                </div>
              )}
            </div>
          </section>

          {/* ---------------------------------------------- leitura */}
          <section className="flex min-h-0 flex-col">
            {!message && (
              <div className="grid flex-1 place-items-center px-6 py-10 text-center">
                <div>
                  {loadingMessage ? (
                    <p className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                      <Loader2 size={13} className="animate-spin" /> A abrir a mensagem…
                    </p>
                  ) : (
                    <>
                      <MailOpen size={20} className="mx-auto text-muted-foreground" />
                      <p className="mt-2 text-[12.5px] text-muted-foreground">Escolha uma mensagem para a ler.</p>
                    </>
                  )}
                </div>
              </div>
            )}

            {message && (
              <>
                <div className="flex flex-wrap items-center gap-1.5 border-b border-white/8 px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setMessage(null)}
                    className="mr-1 grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-white/8 hover:text-foreground lg:hidden"
                    aria-label="Voltar à lista"
                  >
                    <ArrowLeft size={14} />
                  </button>
                  <Button
                    size="sm"
                    icon={<Reply size={13} />}
                    onClick={() => setCompose({ open: true, replyTo: message })}
                  >
                    Responder
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void runFlag(message.uid, message.unread ? "read" : "unread")}
                    loading={busyAction === `${message.unread ? "read" : "unread"}:${message.uid}`}
                    icon={message.unread ? <CheckCheck size={13} /> : <Mail size={13} />}
                  >
                    {message.unread ? "Marcar lida" : "Marcar não lida"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void runFlag(message.uid, message.flagged ? "unflag" : "flag")}
                    icon={<Star size={13} className={message.flagged ? "fill-amber-300 text-amber-300" : undefined} />}
                  >
                    {message.flagged ? "Remover destaque" : "Destacar"}
                  </Button>
                  <div className="relative">
                    <Button variant="outline" size="sm" onClick={() => setMoveOpen((value) => !value)} icon={<Archive size={13} />}>
                      Mover
                    </Button>
                    {moveOpen && (
                      <>
                        <div className="fixed inset-0 z-[70]" onMouseDown={() => setMoveOpen(false)} aria-hidden="true" />
                        <div className="absolute left-0 top-full z-[75] mt-1 max-h-64 w-56 overflow-y-auto rounded-xl border border-white/10 bg-[#14161b]/97 p-1.5 shadow-2xl backdrop-blur-xl">
                          {moveTargets(folders, folder).map((target) => (
                            <button
                              key={target.id}
                              type="button"
                              onClick={() => void runMove(target.id)}
                              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
                            >
                              <Archive size={12} /> {target.label || target.name}
                            </button>
                          ))}
                          {moveTargets(folders, folder).length === 0 && (
                            <p className="px-2.5 py-1.5 text-[12px] text-muted-foreground">Sem outras pastas.</p>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  <div className="min-w-0 flex-1" />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void runDelete(message.uid)}
                    loading={busyAction === `delete:${message.uid}`}
                    icon={<Trash2 size={13} />}
                  >
                    Apagar
                  </Button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
                  <h2 className="text-[15px] font-semibold leading-snug text-foreground">{message.subject}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                    <span className={`grid h-8 w-8 place-items-center rounded-full text-[11px] font-semibold ${avatarColor(message.from[0])}`}>
                      {initialsOf(message.from[0])}
                    </span>
                    <span className="text-foreground/90">{displayAddress(message.from[0])}</span>
                    <span className="truncate">&lt;{message.from[0]?.email}&gt;</span>
                    <span>· {formatFullDate(message.date)}</span>
                  </div>
                  <dl className="mt-2 grid gap-0.5 text-[11.5px] text-muted-foreground">
                    {message.to.length > 0 && (
                      <div className="flex gap-1.5">
                        <dt className="shrink-0 font-medium">Para:</dt>
                        <dd className="min-w-0 truncate">{addressListText(message.to)}</dd>
                      </div>
                    )}
                    {message.cc.length > 0 && (
                      <div className="flex gap-1.5">
                        <dt className="shrink-0 font-medium">CC:</dt>
                        <dd className="min-w-0 truncate">{addressListText(message.cc)}</dd>
                      </div>
                    )}
                  </dl>

                  {message.attachments.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {message.attachments.map((item) => (
                        <span
                          key={`${item.filename}-${item.size}`}
                          className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px]"
                          title={item.content_type}
                        >
                          <Paperclip size={12} className="text-muted-foreground" />
                          <span className="max-w-[240px] truncate">{item.filename}</span>
                          <span className="text-[10.5px] text-muted-foreground">{formatBytes(item.size)}</span>
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-3 border-t border-white/8 pt-3">
                    {message.body_html ? (
                      <>
                        <div className="mb-2 flex items-center gap-2">
                          <button
                            type="button"
                            role="tab"
                            aria-selected={!showHtml}
                            onClick={() => setShowHtml(false)}
                            className={[
                              "rounded-lg px-2 py-1 text-[11.5px] transition",
                              !showHtml ? "bg-white/[0.14] font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                            ].join(" ")}
                          >
                            Texto
                          </button>
                          <button
                            type="button"
                            role="tab"
                            aria-selected={showHtml}
                            onClick={() => setShowHtml(true)}
                            className={[
                              "rounded-lg px-2 py-1 text-[11.5px] transition",
                              showHtml ? "bg-white/[0.14] font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                            ].join(" ")}
                          >
                            Formatado
                          </button>
                          <span className="text-[10.5px] text-muted-foreground/70">
                            (HTML isolado, sem scripts)
                          </span>
                        </div>
                        {showHtml ? (
                          <iframe
                            title={`Mensagem ${message.uid}`}
                            sandbox=""
                            srcDoc={message.body_html}
                            className="h-[520px] w-full rounded-xl border border-white/10 bg-white"
                          />
                        ) : (
                          <pre className="whitespace-pre-wrap break-words font-sans text-[12.5px] leading-relaxed text-foreground/90">
                            {message.body_text || "(mensagem sem texto simples)"}
                          </pre>
                        )}
                      </>
                    ) : (
                      <pre className="whitespace-pre-wrap break-words font-sans text-[12.5px] leading-relaxed text-foreground/90">
                        {message.body_text || "(mensagem vazia)"}
                      </pre>
                    )}
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {accountDialog.open && (
        <AccountDialog
          providers={providers}
          initial={accountDialog.editing}
          onClose={() => setAccountDialog({ open: false, editing: null })}
          onSaved={(saved) => {
            setAccountDialog({ open: false, editing: null });
            setNotice(`Conta ${saved.email_address} ligada.`);
            void (async () => {
              const accountList = await listEmailAccounts();
              setAccounts(accountList.items);
              setAccountId(saved.id);
            })();
          }}
        />
      )}

      {compose.open && account && (
        <ComposeDialog
          account={account}
          replyTo={compose.replyTo}
          onClose={() => setCompose({ open: false, replyTo: null })}
          onSent={() => {
            setCompose({ open: false, replyTo: null });
            setNotice("Mensagem enviada.");
          }}
        />
      )}
    </div>
  );
}
