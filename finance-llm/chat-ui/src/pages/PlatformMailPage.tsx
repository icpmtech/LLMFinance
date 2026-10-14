/**
 * Aplicação «Correio da plataforma» do IQ OS (Administração → Correio).
 *
 * O **gestor do correio da própria solução**, só visível a contas com o papel
 * `admin`: as caixas do domínio (a que envia o email transacional, o
 * `postmaster@`, o `dmarc@` e as que a administração acrescentar), a lista e a
 * leitura das mensagens, a pesquisa sobre o índice, as conversas e o envio com
 * editor e anexos.
 *
 * Três colunas, como no Outlook: as **caixas e pastas** (com por ler), a **lista
 * de mensagens** (pesquisa, filtros e paginação) e a **leitura** — esta com a
 * conversa da mensagem, os anexos e as ações (responder, reencaminhar, destacar,
 * mover, apagar). A composição abre numa janela própria com **editor de texto
 * formatado**, alternância para HTML, assinatura, CC/BCC e anexos; a cópia
 * enviada fica arquivada na pasta *Sent* da caixa.
 *
 * Esta aplicação distingue-se do «Email» pessoal: aqui não se ligam contas de
 * fornecedores — gere-se o correio do domínio da plataforma, lido por IMAP do
 * servidor da solução e arquivado em Elasticsearch (`finance_mail_messages`),
 * que é o que permite a pesquisa e as contagens.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Bold,
  CalendarClock,
  Check,
  ChevronDown,
  Download,
  Forward,
  Inbox,
  Italic,
  Link2,
  List,
  ListOrdered,
  Loader2,
  Mail,
  MailOpen,
  Mailbox,
  Paperclip,
  PenLine,
  Plug,
  Quote,
  RefreshCw,
  Reply,
  ReplyAll,
  Search,
  Send,
  Settings,
  Star,
  Trash2,
  Underline,
  X,
} from "lucide-react";
import { Button } from "../components/ui";
import { useAuth } from "../auth";
import {
  addressListText,
  avatarColor,
  displayAddress,
  formatBytes,
  formatFullDate,
  formatMessageDate,
  initialsOf,
} from "../emailApi";
import {
  deletePlatformMailAccount,
  deletePlatformMailMessage,
  downloadPlatformMailAttachment,
  getPlatformMailMessage,
  getPlatformMailMeta,
  getPlatformMailStats,
  listPlatformMailAccounts,
  listPlatformMailFolders,
  listPlatformMailMessages,
  movePlatformMailMessage,
  savePlatformMailAccount,
  savePlatformMailSettings,
  sendPlatformMail,
  setPlatformMailFlags,
  syncPlatformMail,
  testPlatformMailAccount,
  type PlatformMailAccount,
  type PlatformMailAccountDraft,
  type PlatformMailAttachment,
  type PlatformMailFolder,
  type PlatformMailList,
  type PlatformMailMessage,
  type PlatformMailStats,
  type PlatformMailSummary,
} from "../platformMailApi";

const ACCOUNT_KEY = "iqos-platform-mail-account";
const FOLDER_KEY = "iqos-platform-mail-folder";
const PAGE_SIZE = 40;

const FIELD =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-[13px] text-foreground placeholder:text-muted-foreground/60 focus:border-teal-300/50 focus:outline-none";
const LABEL = "mb-1 block text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground";
const CHIP = "inline-flex items-center gap-1 rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-muted-foreground";

// --------------------------------------------------------------------- janela
function Modal({
  title,
  hint,
  onClose,
  children,
  wide,
  footer,
}: {
  title: string;
  hint?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  footer?: ReactNode;
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
        className={`relative z-10 flex max-h-[88vh] w-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0d1418] shadow-2xl ${
          wide ? "max-w-4xl" : "max-w-xl"
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
        {footer && <footer className="flex items-center justify-end gap-2 border-t border-white/8 px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- editor
type EditorCommand = { id: string; label: string; icon: ReactNode; value?: string };

const EDITOR_COMMANDS: EditorCommand[] = [
  { id: "bold", label: "Negrito", icon: <Bold size={14} /> },
  { id: "italic", label: "Itálico", icon: <Italic size={14} /> },
  { id: "underline", label: "Sublinhado", icon: <Underline size={14} /> },
  { id: "insertUnorderedList", label: "Lista", icon: <List size={14} /> },
  { id: "insertOrderedList", label: "Lista numerada", icon: <ListOrdered size={14} /> },
  { id: "formatBlock", label: "Citação", icon: <Quote size={14} />, value: "blockquote" },
];

/**
 * Editor de email: texto formatado (o que o Outlook chama «Rich Text») com
 * alternância para o HTML, para quando é preciso mexer na marcação.
 *
 * Usa `contentEditable` e os comandos do browser (`execCommand`), que é o que
 * existe sem acrescentar dependências ao projecto. O valor que sai daqui é
 * **HTML**; o texto simples que acompanha a mensagem é derivado dele na altura
 * do envio (uma mensagem só-HTML é entregue a quem lê em texto por conversão).
 */
function RichTextEditor({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (html: string) => void;
  disabled?: boolean;
}) {
  const area = useRef<HTMLDivElement | null>(null);
  const [showsHtml, setShowsHtml] = useState(false);

  useEffect(() => {
    if (showsHtml) return;
    if (area.current && area.current.innerHTML !== value) area.current.innerHTML = value;
  }, [value, showsHtml]);

  const run = (command: EditorCommand) => {
    area.current?.focus();
    if (command.id === "createLink") {
      const url = window.prompt("Endereço do link (https://…)");
      if (!url) return;
      document.execCommand("createLink", false, url);
    } else {
      document.execCommand(command.id, false, command.value);
    }
    onChange(area.current?.innerHTML ?? "");
  };

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02]">
      <div className="flex flex-wrap items-center gap-1 border-b border-white/8 px-2 py-1.5">
        {EDITOR_COMMANDS.map((command) => (
          <button
            key={command.id}
            type="button"
            title={command.label}
            aria-label={command.label}
            disabled={disabled || showsHtml}
            onClick={() => run(command)}
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground disabled:opacity-40"
          >
            {command.icon}
          </button>
        ))}
        <button
          type="button"
          title="Inserir link"
          aria-label="Inserir link"
          disabled={disabled || showsHtml}
          onClick={() => run({ id: "createLink", label: "Link", icon: <Link2 size={14} /> })}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground disabled:opacity-40"
        >
          <Link2 size={14} />
        </button>
        <button
          type="button"
          onClick={() => run({ id: "removeFormat", label: "Limpar formatação", icon: <X size={14} /> })}
          disabled={disabled || showsHtml}
          className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground disabled:opacity-40"
        >
          Limpar
        </button>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setShowsHtml((current) => !current)}
          className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
        >
          {showsHtml ? "Voltar ao editor" : "Editar HTML"}
        </button>
      </div>
      {showsHtml ? (
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
          rows={12}
          className="w-full resize-y bg-transparent px-3 py-2 font-mono text-[12px] text-foreground focus:outline-none"
        />
      ) : (
        <div
          ref={area}
          contentEditable={!disabled}
          role="textbox"
          aria-multiline="true"
          aria-label="Corpo da mensagem"
          onInput={() => onChange(area.current?.innerHTML ?? "")}
          onBlur={() => onChange(area.current?.innerHTML ?? "")}
          className="min-h-[190px] px-3 py-2 text-[13.5px] leading-relaxed text-foreground focus:outline-none [&_a]:text-teal-300 [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-white/20 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5"
        />
      )}
    </div>
  );
}

/** HTML → texto simples, para acompanhar sempre uma mensagem em texto. */
function htmlToText(html: string): string {
  const caixa = document.createElement("div");
  caixa.innerHTML = html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|blockquote|tr)>/gi, "\n");
  return (caixa.textContent || "").replace(/\n{3,}/g, "\n\n").trim();
}

function stripTags(html: string): string {
  return htmlToText(html);
}


// ---------------------------------------------------------------- composição
type ComposeMode = "new" | "reply" | "replyAll" | "forward";

type ComposeState = {
  open: boolean;
  mode: ComposeMode;
  source: PlatformMailMessage | null;
};

type PendingAttachment = { filename: string; content_type: string; data: string; size: number };

function quoteOriginal(message: PlatformMailMessage, forwarded: boolean): string {
  const cabecalho = forwarded
    ? `<p><br></p><p>—— Mensagem reencaminhada ——<br>
        De: ${escapeHtml(addressListText(message.from))}<br>
        Data: ${escapeHtml(formatFullDate(message.date))}<br>
        Para: ${escapeHtml(addressListText(message.to))}<br>
        Assunto: ${escapeHtml(message.subject)}</p>`
    : `<p><br></p><p>Ao ${escapeHtml(formatFullDate(message.date))}, ${escapeHtml(displayAddress(message.from[0]))} escreveu:</p>`;
  const corpo = message.body_html || `<p>${escapeHtml(message.body_text).replace(/\n/g, "<br>")}</p>`;
  return `${cabecalho}<blockquote style="border-left:2px solid rgba(255,255,255,.2);margin:0;padding-left:12px;color:#94a3b8">${corpo}</blockquote>`;
}

function escapeHtml(value: string): string {
  return (value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function ComposeWindow({
  accounts,
  accountId,
  compose,
  onClose,
  onSent,
}: {
  accounts: PlatformMailAccount[];
  accountId: string;
  compose: ComposeState;
  onClose: () => void;
  onSent: (mensagem: string) => void;
}) {
  const origem = compose.source;
  const encaminhar = compose.mode === "forward";
  const [fromId, setFromId] = useState(accountId);
  const [to, setTo] = useState(() => (encaminhar || !origem ? "" : addressListText(origem.from)));
  const [cc, setCc] = useState("");
  const [bcc, setBcc] = useState("");
  const [showsCopies, setShowsCopies] = useState(false);
  const [subject, setSubject] = useState(() => {
    if (!origem) return "";
    const prefixo = encaminhar ? "Fwd: " : "Re: ";
    return /^(re|fwd|fw):/i.test(origem.subject) ? origem.subject : `${prefixo}${origem.subject}`;
  });
  const [html, setHtml] = useState(() => (origem ? quoteOriginal(origem, encaminhar) : ""));
  const [includeSignature, setIncludeSignature] = useState(true);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const account = accounts.find((item) => item.id === fromId) ?? null;

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const lidos: PendingAttachment[] = [];
    for (const file of Array.from(files)) {
      const buffer = await file.arrayBuffer();
      let binario = "";
      const bytes = new Uint8Array(buffer);
      for (let index = 0; index < bytes.length; index += 1) binario += String.fromCharCode(bytes[index]);
      lidos.push({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data: window.btoa(binario),
        size: file.size,
      });
    }
    setAttachments((current) => [...current, ...lidos]);
  };

  const enviar = async () => {
    setError(null);
    const destinatarios = to
      .split(/[;,]/)
      .map((parte) => parte.trim())
      .filter(Boolean);
    if (!destinatarios.length) {
      setError("Indique pelo menos um destinatário.");
      return;
    }
    if (!stripTags(html) && !html.trim()) {
      setError("Escreva o corpo da mensagem.");
      return;
    }
    setSending(true);
    try {
      const resultado = await sendPlatformMail({
        account: fromId,
        to: destinatarios,
        cc: cc ? cc.split(/[;,]/).map((parte) => parte.trim()).filter(Boolean) : [],
        bcc: bcc ? bcc.split(/[;,]/).map((parte) => parte.trim()).filter(Boolean) : [],
        subject,
        body_text: htmlToText(html),
        body_html: html,
        include_signature: includeSignature,
        in_reply_to: origem?.message_id || undefined,
        references: origem ? [origem.references, origem.message_id].filter(Boolean).join(" ").trim() : undefined,
        attachments: attachments.map((item) => ({ filename: item.filename, content_type: item.content_type, data: item.data })),
      });
      const aviso = resultado.appended_to_sent ? "" : ` ${resultado.warning ?? "A cópia não ficou em Sent."}`;
      onSent(`Mensagem enviada para ${resultado.to.join(", ")}.${aviso}`);
      onClose();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSending(false);
    }
  };

  const fechar = () => {
    const escreveu = Boolean(to.trim() || subject.trim() || stripTags(html));
    if (escreveu && !window.confirm("Fechar sem enviar? O texto escrito perde-se.")) return;
    onClose();
  };

  return (
    <Modal
      wide
      title={encaminhar ? "Reencaminhar mensagem" : compose.mode === "new" ? "Nova mensagem" : "Responder"}
      hint={account ? `${account.label} · ${account.email_address}` : undefined}
      onClose={fechar}
      footer={
        <>
          <span className="mr-auto text-[11.5px] text-muted-foreground">
            A cópia enviada fica em <strong className="text-foreground/80">Sent</strong> da caixa.
          </span>
          <Button variant="ghost" size="sm" onClick={fechar} disabled={sending}>
            Cancelar
          </Button>
          <Button variant="primary" size="sm" icon={<Send size={14} />} loading={sending} onClick={enviar}>
            Enviar
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && (
          <p className="flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-200">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            {error}
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <div>
            <label className={LABEL} htmlFor="compose-from">
              De
            </label>
            <select id="compose-from" className={FIELD} value={fromId} onChange={(event) => setFromId(event.target.value)}>
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} — {item.email_address}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={() => setShowsCopies((current) => !current)}
              className="rounded-lg border border-white/10 px-3 py-2 text-[12px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
            >
              {showsCopies ? "Esconder CC/BCC" : "Mostrar CC/BCC"}
            </button>
          </div>
        </div>

        <div>
          <label className={LABEL} htmlFor="compose-to">
            Para
          </label>
          <input
            id="compose-to"
            className={FIELD}
            value={to}
            onChange={(event) => setTo(event.target.value)}
            placeholder="nome@exemplo.pt, outro@exemplo.pt"
          />
        </div>

        {showsCopies && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="compose-cc">
                Cc
              </label>
              <input id="compose-cc" className={FIELD} value={cc} onChange={(event) => setCc(event.target.value)} />
            </div>
            <div>
              <label className={LABEL} htmlFor="compose-bcc">
                Bcc
              </label>
              <input id="compose-bcc" className={FIELD} value={bcc} onChange={(event) => setBcc(event.target.value)} />
            </div>
          </div>
        )}

        <div>
          <label className={LABEL} htmlFor="compose-subject">
            Assunto
          </label>
          <input id="compose-subject" className={FIELD} value={subject} onChange={(event) => setSubject(event.target.value)} />
        </div>

        <div>
          <span className={LABEL}>Mensagem</span>
          <RichTextEditor value={html} onChange={setHtml} disabled={sending} />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground">
            <Paperclip size={13} />
            Anexar ficheiros
            <input
              type="file"
              multiple
              className="hidden"
              onChange={(event) => {
                void addFiles(event.target.files);
                event.target.value = "";
              }}
            />
          </label>
          <label className="inline-flex items-center gap-2 text-[12px] text-muted-foreground">
            <input type="checkbox" checked={includeSignature} onChange={(event) => setIncludeSignature(event.target.checked)} />
            Incluir assinatura da caixa
          </label>
        </div>

        {attachments.length > 0 && (
          <ul className="space-y-1.5">
            {attachments.map((item, index) => (
              <li
                key={`${item.filename}-${index}`}
                className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[12.5px]"
              >
                <Paperclip size={13} className="text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-foreground">{item.filename}</span>
                <span className="text-[11px] text-muted-foreground">{formatBytes(item.size)}</span>
                <button
                  type="button"
                  aria-label={`Remover ${item.filename}`}
                  onClick={() => setAttachments((current) => current.filter((_, posicao) => posicao !== index))}
                  className="grid h-6 w-6 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
                >
                  <X size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------- caixas e agenda
type MailboxForm = PlatformMailAccountDraft;

function emptyMailbox(defaults: PlatformMailMetaDefaults | null): MailboxForm {
  return {
    label: "",
    email_address: "",
    display_name: "",
    password: "",
    imap_host: defaults?.imap_host ?? "",
    imap_port: defaults?.imap_port ?? 993,
    imap_security: defaults?.imap_security ?? "ssl",
    smtp_host: defaults?.smtp_host ?? defaults?.imap_host ?? "",
    smtp_port: defaults?.smtp_port ?? 587,
    smtp_security: defaults?.smtp_security ?? "starttls",
    folders: defaults?.sync_folders ?? ["INBOX", "Sent"],
    signature: "",
    enabled: true,
  };
}

type PlatformMailMetaDefaults = {
  imap_host: string;
  imap_port: number;
  imap_security: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_security?: string;
  sync_folders: string[];
};

function MailboxDialog({
  accounts,
  defaults,
  settings,
  syncSeconds,
  autoSync,
  onClose,
  onChanged,
  onError,
  onNotice,
}: {
  accounts: PlatformMailAccount[];
  defaults: PlatformMailMetaDefaults | null;
  settings: { auto_sync: boolean; sync_seconds: number };
  syncSeconds: number;
  autoSync: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onError: (mensagem: string) => void;
  onNotice: (mensagem: string) => void;
}) {
  const [form, setForm] = useState<MailboxForm>(() => emptyMailbox(defaults));
  const [editing, setEditing] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [teste, setTeste] = useState<string | null>(null);
  const [agenda, setAgenda] = useState({ auto_sync: autoSync, sync_seconds: syncSeconds, guardada: settings });
  const [busy, setBusy] = useState<string | null>(null);

  const escolher = (conta: PlatformMailAccount) => {
    setEditing(conta.id);
    setTeste(null);
    setForm({
      id: conta.id,
      label: conta.label,
      email_address: conta.email_address,
      display_name: conta.display_name ?? "",
      password: "",
      imap_host: conta.imap_host,
      imap_port: conta.imap_port,
      imap_security: conta.imap_security,
      smtp_host: conta.smtp_host,
      smtp_port: conta.smtp_port,
      smtp_security: conta.smtp_security,
      folders: conta.folders,
      signature: conta.signature ?? "",
      enabled: conta.enabled,
    });
  };

  const testar = async () => {
    setTesting(true);
    setTeste(null);
    try {
      const resultado = await testPlatformMailAccount(form);
      setTeste(
        `IMAP: ${resultado.imap ? "ligou" : "falhou"} · SMTP: ${resultado.smtp ? "ligou" : "falhou"} · ${
          resultado.folders
        } pasta(s)${resultado.unread_inbox != null ? ` · ${resultado.unread_inbox} por ler na entrada` : ""}`,
      );
    } catch (exc) {
      setTeste(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setTesting(false);
    }
  };

  const gravar = async () => {
    setSaving(true);
    try {
      await savePlatformMailAccount(form);
      await onChanged();
      onNotice("Caixa de correio guardada.");
      setEditing(null);
      setForm(emptyMailbox(defaults));
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  };

  const apagar = async (conta: PlatformMailAccount) => {
    if (!window.confirm(`Remover a caixa ${conta.email_address}? O correio no servidor não é tocado.`)) return;
    setBusy(`apagar-${conta.id}`);
    try {
      await deletePlatformMailAccount(conta.id);
      await onChanged();
      onNotice("Caixa removida.");
      if (editing === conta.id) {
        setEditing(null);
        setForm(emptyMailbox(defaults));
      }
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const sincronizar = async (conta: PlatformMailAccount | null, full: boolean) => {
    setBusy(conta ? `sync-${conta.id}` : "sync-todas");
    try {
      const resultado = await syncPlatformMail({ account: conta?.id, full });
      const erros = resultado.errors.length ? ` Erros: ${resultado.errors.join(" · ")}` : "";
      onNotice(`${resultado.indexed} mensagem(ns) indexada(s) de ${resultado.accounts.length} caixa(s).${erros}`);
      await onChanged();
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const gravarAgenda = async () => {
    setBusy("agenda");
    try {
      await savePlatformMailSettings({ auto_sync: agenda.auto_sync, sync_seconds: agenda.sync_seconds });
      setAgenda((current) => ({ ...current, guardada: { auto_sync: current.auto_sync, sync_seconds: current.sync_seconds } }));
      await onChanged();
      onNotice("Agenda da sincronização guardada.");
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      wide
      title="Caixas de correio e agenda"
      hint="As caixas do domínio da plataforma e de quanto em quanto tempo o correio novo é arquivado."
      onClose={onClose}
    >
      <div className="space-y-5">
        <section>
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Caixas ligadas</h3>
          <ul className="space-y-1.5">
            {accounts.map((conta) => (
              <li
                key={conta.id}
                className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 ${
                  editing === conta.id ? "border-teal-300/40 bg-teal-300/5" : "border-white/10 bg-white/[0.02]"
                }`}
              >
                <Mailbox size={14} className="text-muted-foreground" />
                <button type="button" onClick={() => escolher(conta)} className="min-w-0 text-left">
                  <span className="block truncate text-[13px] text-foreground">{conta.label}</span>
                  <span className="block truncate text-[11.5px] text-muted-foreground">
                    {conta.email_address} · {conta.imap_host}:{conta.imap_port} · pastas {conta.folders.join(", ")}
                  </span>
                </button>
                {conta.source === "env" && <span className={CHIP}>do SMTP da plataforma</span>}
                {!conta.enabled && <span className={CHIP}>desligada</span>}
                {conta.last_error && (
                  <span className="rounded-full border border-amber-400/30 px-2 py-0.5 text-[11px] text-amber-200">{conta.last_error}</span>
                )}
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => void sincronizar(conta, false)}
                  className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
                >
                  {busy === `sync-${conta.id}` ? "A sincronizar…" : "Sincronizar"}
                </button>
                {conta.source !== "env" && (
                  <button
                    type="button"
                    onClick={() => void apagar(conta)}
                    className="rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-red-500/10 hover:text-red-200"
                  >
                    {busy === `apagar-${conta.id}` ? "A remover…" : "Remover"}
                  </button>
                )}
              </li>
            ))}
            {!accounts.length && (
              <li className="rounded-lg border border-amber-400/30 bg-amber-500/5 px-3 py-2 text-[12.5px] text-amber-200">
                Ainda não há caixas. Sem SMTP configurado em <strong>Administração → Chaves e integrações</strong>, a caixa da
                plataforma não aparece — acrescente uma abaixo ou configure o SMTP.
              </li>
            )}
          </ul>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={13} />}
              loading={busy === "sync-todas"}
              onClick={() => void sincronizar(null, false)}
            >
              Sincronizar todas
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void sincronizar(null, true)} disabled={busy !== null}>
              Reindexar tudo (completa)
            </Button>
          </div>
        </section>

        <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
            {editing ? "Alterar caixa" : "Ligar nova caixa"}
          </h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="mb-email">
                Endereço
              </label>
              <input
                id="mb-email"
                className={FIELD}
                value={form.email_address ?? ""}
                onChange={(event) => setForm({ ...form, email_address: event.target.value })}
                placeholder="postmaster@sabemos.studio"
              />
            </div>
            <div>
              <label className={LABEL} htmlFor="mb-label">
                Nome
              </label>
              <input
                id="mb-label"
                className={FIELD}
                value={form.label ?? ""}
                onChange={(event) => setForm({ ...form, label: event.target.value })}
                placeholder="Postmaster"
              />
            </div>
            <div>
              <label className={LABEL} htmlFor="mb-password">
                Palavra-passe
              </label>
              <input
                id="mb-password"
                type="password"
                className={FIELD}
                value={form.password ?? ""}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                placeholder={editing ? "deixe vazio para manter" : "a palavra-passe da caixa"}
              />
            </div>
            <div>
              <label className={LABEL} htmlFor="mb-imap">
                Servidor IMAP
              </label>
              <div className="flex gap-2">
                <input
                  id="mb-imap"
                  className={FIELD}
                  value={form.imap_host ?? ""}
                  onChange={(event) => setForm({ ...form, imap_host: event.target.value })}
                />
                <input
                  className={`${FIELD} w-20`}
                  value={String(form.imap_port ?? "")}
                  onChange={(event) => setForm({ ...form, imap_port: Number(event.target.value) || 0 })}
                  aria-label="Porta IMAP"
                />
              </div>
            </div>
            <div>
              <label className={LABEL} htmlFor="mb-security">
                Segurança do IMAP
              </label>
              <select
                id="mb-security"
                className={FIELD}
                value={form.imap_security ?? "ssl"}
                onChange={(event) => setForm({ ...form, imap_security: event.target.value })}
              >
                <option value="ssl">ssl (993)</option>
                <option value="starttls">starttls (143)</option>
                <option value="plain">sem cifra</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="mb-folders">
                Pastas a sincronizar
              </label>
              <input
                id="mb-folders"
                className={FIELD}
                value={(form.folders ?? []).join(", ")}
                onChange={(event) =>
                  setForm({ ...form, folders: event.target.value.split(",").map((parte) => parte.trim()).filter(Boolean) })
                }
                placeholder="INBOX, Sent"
              />
            </div>
            <div className="sm:col-span-2">
              <label className={LABEL} htmlFor="mb-signature">
                Assinatura
              </label>
              <textarea
                id="mb-signature"
                rows={2}
                className={FIELD}
                value={form.signature ?? ""}
                onChange={(event) => setForm({ ...form, signature: event.target.value })}
                placeholder="IQ OS — Inteligência Financeira"
              />
            </div>
          </div>

          {teste && <p className="mt-2 text-[12px] text-muted-foreground">{teste}</p>}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" icon={<Plug size={13} />} loading={testing} onClick={testar}>
              Testar ligação
            </Button>
            <Button variant="primary" size="sm" icon={<Check size={13} />} loading={saving} onClick={gravar}>
              {editing ? "Guardar alterações" : "Ligar caixa"}
            </Button>
            {editing && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEditing(null);
                  setForm(emptyMailbox(defaults));
                  setTeste(null);
                }}
              >
                Cancelar edição
              </Button>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
            <CalendarClock size={13} />
            Agenda da sincronização
          </h3>
          <div className="flex flex-wrap items-end gap-3">
            <label className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <input
                type="checkbox"
                checked={agenda.auto_sync}
                onChange={(event) => setAgenda({ ...agenda, auto_sync: event.target.checked })}
              />
              Trazer correio novo automaticamente
            </label>
            <div>
              <label className={LABEL} htmlFor="agenda-segundos">
                De quanto em quanto tempo (segundos)
              </label>
              <input
                id="agenda-segundos"
                className={`${FIELD} w-36`}
                value={agenda.sync_seconds}
                onChange={(event) => setAgenda({ ...agenda, sync_seconds: Number(event.target.value.replace(/\D/g, "")) || 0 })}
              />
            </div>
            <Button variant="secondary" size="sm" loading={busy === "agenda"} onClick={gravarAgenda}>
              Guardar agenda
            </Button>
            <span className="text-[11.5px] text-muted-foreground">
              Actual: {agenda.guardada.auto_sync ? `${agenda.guardada.sync_seconds}s` : "desligada"} · 0 segundos desliga.
            </span>
          </div>
        </section>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------- listas
function FolderButton({
  conta,
  active,
  onSelect,
}: {
  conta: PlatformMailFolder;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition ${
        active ? "bg-teal-300/10 text-foreground" : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground"
      }`}
    >
      {conta.sent ? <Send size={13} /> : conta.trash ? <Trash2 size={13} /> : <Inbox size={13} />}
      <span className="min-w-0 flex-1 truncate">{conta.label || conta.name}</span>
      {typeof conta.unseen === "number" && conta.unseen > 0 && (
        <span className="rounded-full bg-teal-300/15 px-1.5 text-[10.5px] font-semibold text-teal-200">{conta.unseen}</span>
      )}
      {conta.indexed ? <span className="text-[10.5px] text-muted-foreground/70">{conta.indexed}</span> : null}
    </button>
  );
}

function MessageRow({
  mensagem,
  active,
  onOpen,
}: {
  mensagem: PlatformMailSummary;
  active: boolean;
  onOpen: () => void;
}) {
  const endereco = mensagem.from;
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`flex w-full gap-2.5 border-b border-white/5 px-3 py-2.5 text-left transition ${
        active ? "bg-teal-300/10" : "hover:bg-white/[0.04]"
      }`}
    >
      <span
        className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white/90"
        style={{ background: avatarColor(endereco) }}
      >
        {initialsOf(endereco)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className={`min-w-0 flex-1 truncate text-[12.5px] ${mensagem.unseen ? "font-semibold text-foreground" : "text-foreground/85"}`}>
            {displayAddress(endereco) || "(sem remetente)"}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground">{formatMessageDate(mensagem.date)}</span>
        </span>
        <span className="mt-0.5 flex items-center gap-1.5">
          {mensagem.unseen && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-teal-300" />}
          <span className={`min-w-0 flex-1 truncate text-[12.5px] ${mensagem.unseen ? "font-medium text-foreground" : "text-foreground/80"}`}>
            {mensagem.subject || "(sem assunto)"}
          </span>
          {mensagem.flagged && <Star size={12} className="shrink-0 text-amber-300" />}
          {mensagem.has_attachments && <Paperclip size={12} className="shrink-0 text-muted-foreground" />}
          {mensagem.direction === "out" && <Send size={11} className="shrink-0 text-muted-foreground/70" />}
        </span>
        <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">{mensagem.snippet || "—"}</span>
      </span>
    </button>
  );
}

function ReadingPane({
  detail,
  summary,
  siblings,
  loading,
  showHtml,
  folderOptions,
  onToggleHtml,
  onReply,
  onReplyAll,
  onForward,
  onFlag,
  onRead,
  onMove,
  onDelete,
  onOpenSibling,
  onDownload,
  busy,
}: {
  detail: { message: PlatformMailMessage; stale: boolean; warning?: string; source: string } | null;
  summary: PlatformMailSummary | null;
  siblings: PlatformMailSummary[];
  loading: boolean;
  showHtml: boolean;
  folderOptions: PlatformMailFolder[];
  onToggleHtml: () => void;
  onReply: () => void;
  onReplyAll: () => void;
  onForward: () => void;
  onFlag: () => void;
  onRead: () => void;
  onMove: (target: string) => void;
  onDelete: () => void;
  onOpenSibling: (mensagem: PlatformMailSummary) => void;
  onDownload: (anexo: PlatformMailAttachment, index: number) => void;
  busy: string | null;
}) {
  const [moveOpen, setMoveOpen] = useState(false);
  if (loading && !detail) {
    return (
      <div className="grid h-full place-items-center text-muted-foreground">
        <Loader2 size={18} className="animate-spin" />
      </div>
    );
  }
  if (!detail || !summary) {
    return (
      <div className="grid h-full place-items-center px-6 text-center text-[12.5px] text-muted-foreground">
        <div>
          <MailOpen size={22} className="mx-auto mb-2 opacity-60" />
          Escolha uma mensagem para a ler aqui.
        </div>
      </div>
    );
  }

  const mensagem = detail.message;
  const semCorpo = !mensagem.body_text.trim() && !mensagem.body_html.trim();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-white/8 px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold leading-snug text-foreground">{mensagem.subject || "(sem assunto)"}</h2>
            <p className="mt-1 text-[12.5px] text-muted-foreground">
              <span className="text-foreground/85">{displayAddress(mensagem.from[0])}</span>
              {mensagem.from[0]?.email && ` <${mensagem.from[0].email}>`}
            </p>
            <p className="mt-0.5 text-[11.5px] text-muted-foreground">
              Para {addressListText(mensagem.to) || "—"}
              {mensagem.cc.length > 0 && ` · Cc ${addressListText(mensagem.cc)}`}
            </p>
            <p className="mt-0.5 text-[11.5px] text-muted-foreground">{formatFullDate(mensagem.date)}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
            <button
              type="button"
              onClick={onReply}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title="Responder"
              aria-label="Responder"
            >
              <Reply size={14} />
            </button>
            <button
              type="button"
              onClick={onReplyAll}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title="Responder a todos"
              aria-label="Responder a todos"
            >
              <ReplyAll size={14} />
            </button>
            <button
              type="button"
              onClick={onForward}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title="Reencaminhar"
              aria-label="Reencaminhar"
            >
              <Forward size={14} />
            </button>
            <button
              type="button"
              onClick={onFlag}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title={mensagem.flagged ? "Tirar destaque" : "Destacar"}
              aria-label="Destacar"
            >
              <Star size={14} className={mensagem.flagged ? "text-amber-300" : ""} />
            </button>
            <button
              type="button"
              onClick={onRead}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title={mensagem.unread ? "Marcar como lida" : "Marcar como não lida"}
              aria-label="Alternar lida"
            >
              <Mail size={14} />
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setMoveOpen((current) => !current)}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              >
                Mover <ChevronDown size={12} />
              </button>
              {moveOpen && (
                <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-lg border border-white/10 bg-[#0d1418] shadow-xl">
                  {folderOptions
                    .filter((item) => item.selectable && item.name !== mensagem.folder)
                    .map((item) => (
                      <button
                        key={item.name}
                        type="button"
                        onClick={() => {
                          setMoveOpen(false);
                          onMove(item.name);
                        }}
                        className="block w-full px-3 py-1.5 text-left text-[12px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
                      >
                        {item.label || item.name}
                      </button>
                    ))}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={onDelete}
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-red-500/10 hover:text-red-200"
              title="Apagar"
              aria-label="Apagar"
            >
              {busy === "apagar" ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          </div>
        </div>
        {detail.warning && (
          <p className="mt-2 flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-500/5 px-3 py-1.5 text-[11.5px] text-amber-200">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {detail.warning}
          </p>
        )}
        {detail.source === "elasticsearch" && !detail.warning && (
          <p className="mt-2 text-[11.5px] text-muted-foreground">A mostrar a cópia arquivada (o servidor não respondeu).</p>
        )}
      </header>

      {mensagem.attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 border-b border-white/8 px-4 py-2">
          {mensagem.attachments.map((anexo, index) => (
            <button
              key={`${anexo.filename}-${index}`}
              type="button"
              onClick={() => onDownload(anexo, index)}
              className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title={`Descarregar ${anexo.filename}`}
            >
              <Paperclip size={12} />
              <span className="max-w-[220px] truncate">{anexo.filename}</span>
              <span className="text-[10.5px] text-muted-foreground/70">{formatBytes(anexo.size)}</span>
              <Download size={12} />
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {semCorpo ? (
          <p className="text-[12.5px] text-muted-foreground">A mensagem não tem corpo de texto.</p>
        ) : showHtml && mensagem.body_html ? (
          <iframe
            title="Corpo da mensagem"
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            srcDoc={`<base target="_blank"><style>body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13.5px;line-height:1.6;color:#e6edf2;background:transparent;word-break:break-word}img{max-width:100%;height:auto}a{color:#5eead4}blockquote{border-left:2px solid rgba(255,255,255,.2);margin:0;padding-left:12px;color:#94a3b8}table{max-width:100%}</style>${
              mensagem.body_html
            }`}
            className="h-[min(60vh,520px)] w-full rounded-lg border border-white/8 bg-white/[0.015]"
          />
        ) : (
          <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-foreground/90">
            {mensagem.body_text || stripTags(mensagem.body_html) || "—"}
          </pre>
        )}

        {mensagem.body_html && mensagem.body_text && (
          <button
            type="button"
            onClick={onToggleHtml}
            className="mt-3 rounded-md border border-white/10 px-2.5 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
          >
            {showHtml ? "Ver em texto simples" : "Ver com formatação"}
          </button>
        )}

        {siblings.length > 1 && (
          <section className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
              Nesta conversa ({siblings.length})
            </h3>
            <ul className="space-y-1">
              {siblings.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onOpenSibling(item)}
                    className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition ${
                      item.id === summary.id ? "bg-teal-300/10 text-foreground" : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground"
                    }`}
                  >
                    <span className="w-36 shrink-0 truncate">{displayAddress(item.from)}</span>
                    <span className="min-w-0 flex-1 truncate">{item.subject}</span>
                    <span className="shrink-0 text-[11px]">{formatMessageDate(item.date)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------- página
export default function PlatformMailPage() {
  const { user } = useAuth();
  const [accounts, setAccounts] = useState<PlatformMailAccount[]>([]);
  const [defaults, setDefaults] = useState<PlatformMailMetaDefaults | null>(null);
  const [stats, setStats] = useState<PlatformMailStats | null>(null);
  const [accountId, setAccountId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(ACCOUNT_KEY) ?? "";
  });
  const [folder, setFolder] = useState<string>(() => {
    if (typeof window === "undefined") return "INBOX";
    return window.localStorage.getItem(FOLDER_KEY) ?? "INBOX";
  });
  const [folders, setFolders] = useState<PlatformMailFolder[]>([]);
  const [list, setList] = useState<PlatformMailList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState(false);
  const [detail, setDetail] = useState<{
    message: PlatformMailMessage;
    stale: boolean;
    warning?: string;
    source: string;
  } | null>(null);
  const [selected, setSelected] = useState<PlatformMailSummary | null>(null);
  const [siblings, setSiblings] = useState<PlatformMailSummary[]>([]);
  const [showHtml, setShowHtml] = useState(true);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [unseenOnly, setUnseenOnly] = useState(false);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [withAttachments, setWithAttachments] = useState(false);
  const [sort, setSort] = useState("date_desc");
  const [compose, setCompose] = useState<ComposeState>({ open: false, mode: "new", source: null });
  const [mailboxDialog, setMailboxDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const itemsRef = useRef(0);

  const podeAdministrar = (user?.role ?? "member") === "admin";
  const account = useMemo(() => accounts.find((item) => item.id === accountId) ?? null, [accounts, accountId]);
  const folderOptions = useMemo(() => folders.filter((item) => item.selectable), [folders]);

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

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const carregarContas = useCallback(async () => {
    const [meta, contas] = await Promise.all([getPlatformMailMeta(), listPlatformMailAccounts()]);
    setDefaults(meta.defaults);
    setAccounts(contas.items);
    setAccountId((current) => {
      if (current && contas.items.some((item) => item.id === current)) return current;
      return contas.items[0]?.id ?? "";
    });
  }, []);

  const carregarStats = useCallback(async () => {
    try {
      setStats(await getPlatformMailStats());
    } catch {
      setStats(null);
    }
  }, []);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        await carregarContas();
        if (vivo) void carregarStats();
      } catch (exc) {
        if (vivo) setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (vivo) setLoading(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, [carregarContas, carregarStats]);

  const carregarPastas = useCallback(async (id: string) => {
    try {
      const payload = await listPlatformMailFolders(id);
      setFolders(payload.items);
      const nomes = payload.items.map((item) => item.name);
      setFolder((current) => (nomes.includes(current) ? current : (payload.sync_folders[0] ?? nomes[0] ?? "INBOX")));
    } catch (exc) {
      setFolders([]);
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    if (!accountId) return;
    void carregarPastas(accountId);
  }, [accountId, carregarPastas]);

  const carregarLista = useCallback(
    async (options: { append?: boolean } = {}) => {
      if (!accountId) return;
      setLoadingList(true);
      setError(null);
      try {
        const payload = await listPlatformMailMessages({
          account: accountId,
          folder,
          q: search || undefined,
          unseen: unseenOnly || undefined,
          flagged: flaggedOnly || undefined,
          attachments: withAttachments || undefined,
          sort,
          limit: PAGE_SIZE,
          offset: options.append ? itemsRef.current : 0,
        });
        itemsRef.current = options.append ? itemsRef.current + payload.items.length : payload.items.length;
        setList((current) =>
          options.append && current ? { ...payload, items: [...current.items, ...payload.items] } : payload,
        );
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
        if (!options.append) setList(null);
      } finally {
        setLoadingList(false);
      }
    },
    [accountId, folder, search, unseenOnly, flaggedOnly, withAttachments, sort],
  );

  useEffect(() => {
    itemsRef.current = 0;
    setSelected(null);
    setDetail(null);
    setSiblings([]);
    void carregarLista();
  }, [carregarLista]);

  const abrir = useCallback(
    async (mensagem: PlatformMailSummary) => {
      setSelected(mensagem);
      setLoadingMessage(true);
      setError(null);
      try {
        const payload = await getPlatformMailMessage(mensagem.id);
        setDetail(payload);
        setShowHtml(Boolean(payload.message.body_html));
        setList((current) =>
          current
            ? { ...current, items: current.items.map((item) => (item.id === mensagem.id ? { ...item, unseen: false } : item)) }
            : current,
        );
        if (mensagem.thread_key) {
          try {
            const conversa = await listPlatformMailMessages({
              account: accountId,
              thread: mensagem.thread_key,
              limit: 20,
              sort: "date_asc",
              exclude_drafts: false,
              offset: 0,
            });
            setSiblings(conversa.items);
          } catch {
            setSiblings([]);
          }
        } else {
          setSiblings([]);
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
        setDetail(null);
      } finally {
        setLoadingMessage(false);
      }
    },
    [accountId],
  );

  const sincronizar = async (full: boolean) => {
    setSyncing(true);
    setError(null);
    try {
      const resultado = await syncPlatformMail({ account: accountId || undefined, full });
      const erros = resultado.errors.length ? ` Erros: ${resultado.errors.join(" · ")}` : "";
      setNotice(`${resultado.indexed} mensagem(ns) indexada(s).${erros}`);
      await Promise.all([carregarLista(), carregarPastas(accountId), carregarStats()]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSyncing(false);
    }
  };

  const alternarSinalizador = async (acao: "read" | "unread" | "flag" | "unflag") => {
    if (!selected) return;
    setBusy("sinalizador");
    try {
      await setPlatformMailFlags(selected.id, acao);
      const lida = acao === "read" ? false : acao === "unread" ? true : selected.unseen;
      const destacada = acao === "flag" ? true : acao === "unflag" ? false : selected.flagged;
      setSelected({ ...selected, unseen: lida, flagged: destacada });
      setDetail((current) => (current ? { ...current, message: { ...current.message, unread: lida, flagged: destacada } } : current));
      setList((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === selected.id ? { ...item, unseen: lida, flagged: destacada } : item,
              ),
            }
          : current,
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const mover = async (target: string) => {
    if (!selected) return;
    setBusy("mover");
    try {
      await movePlatformMailMessage(selected.id, target);
      setNotice(`Mensagem movida para «${target}».`);
      setSelected(null);
      setDetail(null);
      await carregarLista();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const apagar = async () => {
    if (!selected) return;
    if (!window.confirm(`Apagar «${selected.subject}»? Esta ação remove a mensagem do servidor.`)) return;
    setBusy("apagar");
    try {
      await deletePlatformMailMessage(selected.id);
      setNotice("Mensagem apagada.");
      setSelected(null);
      setDetail(null);
      setSiblings([]);
      await carregarLista();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const descarregar = async (anexo: PlatformMailAttachment, index: number) => {
    if (!selected) return;
    setBusy(`anexo-${index}`);
    try {
      await downloadPlatformMailAttachment(selected.id, index);
    } catch (exc) {
      setError(`${anexo.filename}: ${exc instanceof Error ? exc.message : String(exc)}`);
    } finally {
      setBusy(null);
    }
  };

  if (!podeAdministrar) {
    return (
      <div className="grid h-full place-items-center p-6 text-center">
        <div className="max-w-md">
          <AlertTriangle size={22} className="mx-auto mb-2 text-amber-300" />
          <h1 className="text-[15px] font-semibold text-foreground">Área reservada à administração</h1>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            O correio da plataforma só está disponível para contas com o papel <strong>admin</strong>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="border-b border-white/8 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Mailbox size={17} className="text-teal-300" />
            <div>
              <h1 className="text-[14.5px] font-semibold text-foreground">Correio da plataforma</h1>
              <p className="text-[11.5px] text-muted-foreground">
                {stats
                  ? `${stats.totals.messages} mensagem(ns) arquivada(s) · ${stats.totals.unseen} por ler · ${stats.index.size}`
                  : "A carregar o panorama…"}
              </p>
            </div>
          </div>

          <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
            <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                className={`${FIELD} pl-8`}
                placeholder="Pesquisar assunto, corpo ou remetente"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Pesquisar no correio"
              />
            </div>
            <select className={`${FIELD} w-auto`} value={accountId} onChange={(event) => setAccountId(event.target.value)} aria-label="Caixa">
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <select className={`${FIELD} w-auto`} value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Ordenar">
              <option value="date_desc">Mais recentes</option>
              <option value="date_asc">Mais antigas</option>
              <option value="sender">Remetente</option>
              <option value="subject">Assunto</option>
              <option value="size">Maiores</option>
            </select>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={13} />}
              loading={syncing}
              onClick={() => void sincronizar(false)}
              disabled={!accountId}
            >
              Sincronizar
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<PenLine size={13} />}
              onClick={() => setCompose({ open: true, mode: "new", source: null })}
              disabled={!accounts.length}
            >
              Nova mensagem
            </Button>
            <button
              type="button"
              onClick={() => setMailboxDialog(true)}
              className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-muted-foreground transition hover:bg-white/8 hover:text-foreground"
              title="Caixas de correio e agenda"
              aria-label="Caixas de correio e agenda"
            >
              <Settings size={14} />
            </button>
          </div>
        </div>

        {(error || notice) && (
          <div className="mt-2 space-y-1">
            {error && (
              <p className="flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-1.5 text-[12px] text-red-200">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">{error}</span>
                <button type="button" onClick={() => setError(null)} aria-label="Fechar aviso">
                  <X size={12} />
                </button>
              </p>
            )}
            {notice && (
              <p className="flex items-start gap-2 rounded-lg border border-teal-300/30 bg-teal-300/5 px-3 py-1.5 text-[12px] text-teal-100">
                <Check size={13} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">{notice}</span>
                <button type="button" onClick={() => setNotice(null)} aria-label="Fechar aviso">
                  <X size={12} />
                </button>
              </p>
            )}
          </div>
        )}
      </header>

      {loading ? (
        <div className="grid flex-1 place-items-center text-muted-foreground">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[220px_minmax(280px,380px)_1fr]">
          <aside className="min-h-0 overflow-y-auto border-r border-white/8 px-2 py-3">
            {account && (
              <div className="mb-3 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2">
                <p className="flex items-center gap-1.5 truncate text-[12px] text-foreground">
                  <Mailbox size={12} className="shrink-0 text-teal-300" />
                  {account.label}
                </p>
                <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{account.email_address}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {account.imap_host}:{account.imap_port} · {account.imap_security}
                </p>
                <p className="truncate text-[10.5px] text-muted-foreground/80">
                  {account.last_sync_at ? `Sincronizada em ${formatFullDate(account.last_sync_at)}` : "Ainda sem sincronização"}
                </p>
              </div>
            )}

            <p className={`${LABEL} px-2.5`}>Pastas</p>
            <div className="space-y-0.5">
              {folders.map((item) => (
                <FolderButton key={item.id || item.name} conta={item} active={item.name === folder} onSelect={() => setFolder(item.name)} />
              ))}
              {!folders.length && <p className="px-2.5 text-[12px] text-muted-foreground">Sem pastas: escolha uma caixa.</p>}
            </div>

            <p className={`${LABEL} mt-4 px-2.5`}>Filtros</p>
            <div className="space-y-1 px-1">
              <label className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-[12px] text-muted-foreground">
                <input type="checkbox" checked={unseenOnly} onChange={(event) => setUnseenOnly(event.target.checked)} />
                Só por ler {list?.facets.unseen != null && <span className="text-muted-foreground/70">({list.facets.unseen})</span>}
              </label>
              <label className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-[12px] text-muted-foreground">
                <input type="checkbox" checked={flaggedOnly} onChange={(event) => setFlaggedOnly(event.target.checked)} />
                Só destacadas
              </label>
              <label className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-[12px] text-muted-foreground">
                <input type="checkbox" checked={withAttachments} onChange={(event) => setWithAttachments(event.target.checked)} />
                Só com anexos
              </label>
            </div>

            {stats && (
              <>
                <p className={`${LABEL} mt-4 px-2.5`}>Panorama</p>
                <dl className="space-y-1 px-2.5 text-[11.5px] text-muted-foreground">
                  <div className="flex justify-between gap-2">
                    <dt>Caixas</dt>
                    <dd className="text-foreground/80">{stats.enabled_accounts}/{stats.accounts}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt>Conversas</dt>
                    <dd className="text-foreground/80">{stats.totals.threads}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt>Com anexos</dt>
                    <dd className="text-foreground/80">{stats.totals.with_attachments}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt>Índice</dt>
                    <dd className="text-foreground/80">{stats.es_available ? stats.index.name : "sem Elasticsearch"}</dd>
                  </div>
                </dl>
                {stats.mailboxes.some((item) => item.last_error) && (
                  <ul className="mt-2 space-y-1 px-2.5">
                    {stats.mailboxes
                      .filter((item) => item.last_error)
                      .map((item) => (
                        <li key={item.id} className="text-[11px] text-amber-200">
                          {item.label}: {item.last_error}
                        </li>
                      ))}
                  </ul>
                )}
              </>
            )}
          </aside>

          <section className="flex min-h-0 flex-col border-r border-white/8">
            <header className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{folder}</span>
              <span className="text-[11.5px] text-muted-foreground">
                {list ? `${list.total} mensagem(ns)` : "—"}
                {list?.source === "imap" && " · modo direto"}
              </span>
              {loadingList && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {list?.items.length ? (
                list.items.map((item) => (
                  <MessageRow key={item.id} mensagem={item} active={item.id === selected?.id} onOpen={() => void abrir(item)} />
                ))
              ) : (
                <p className="p-4 text-[12.5px] text-muted-foreground">
                  {loadingList ? "A carregar…" : "Sem mensagens nesta pasta. Sincronize para trazer o correio."}
                </p>
              )}
              {list?.has_more && (
                <div className="p-3">
                  <Button variant="ghost" size="sm" loading={loadingList} onClick={() => void carregarLista({ append: true })}>
                    Carregar mais
                  </Button>
                </div>
              )}
            </div>
          </section>

          <section className="min-h-0">
            <ReadingPane
              detail={detail}
              summary={selected}
              siblings={siblings}
              loading={loadingMessage}
              showHtml={showHtml}
              folderOptions={folderOptions}
              onToggleHtml={() => setShowHtml((current) => !current)}
              onReply={() => setCompose({ open: true, mode: "reply", source: detail?.message ?? null })}
              onReplyAll={() => setCompose({ open: true, mode: "replyAll", source: detail?.message ?? null })}
              onForward={() => setCompose({ open: true, mode: "forward", source: detail?.message ?? null })}
              onFlag={() => void alternarSinalizador(detail?.message.flagged ? "unflag" : "flag")}
              onRead={() => void alternarSinalizador(detail?.message.unread ? "read" : "unread")}
              onMove={(target) => void mover(target)}
              onDelete={() => void apagar()}
              onOpenSibling={(item) => void abrir(item)}
              onDownload={(anexo, index) => void descarregar(anexo, index)}
              busy={busy}
            />
          </section>
        </div>
      )}

      {compose.open && (
        <ComposeWindow
          accounts={accounts}
          accountId={accountId || accounts[0]?.id || ""}
          compose={compose}
          onClose={() => setCompose({ open: false, mode: "new", source: null })}
          onSent={(mensagem) => {
            setNotice(mensagem);
            void Promise.all([carregarLista(), carregarStats()]);
          }}
        />
      )}

      {mailboxDialog && (
        <MailboxDialog
          accounts={accounts}
          defaults={defaults}
          settings={stats?.settings ?? { auto_sync: true, sync_seconds: 300 }}
          syncSeconds={stats?.settings.sync_seconds ?? 300}
          autoSync={stats?.settings.auto_sync ?? true}
          onClose={() => setMailboxDialog(false)}
          onChanged={async () => {
            await carregarContas();
            await Promise.all([carregarStats(), accountId ? carregarPastas(accountId) : Promise.resolve()]);
          }}
          onError={setError}
          onNotice={setNotice}
        />
      )}
    </div>
  );
}
