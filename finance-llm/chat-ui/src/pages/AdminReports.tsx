/**
 * Backoffice de relatórios — separador da aplicação «Administração».
 *
 * É aqui que a equipa (administradores ou contas marcadas em
 * *Definições → Contas de backoffice*) vê os pedidos que chegam, confirma os
 * pagamentos por MB Way, avança o estado (em produção → gerado → entregue) e
 * anexa o relatório produzido, que fica logo disponível na área «Relatórios» do
 * cliente.
 *
 * O sino (e a faixa de aviso) fazem a **notificação**: a caixa é sondada a cada
 * 30 s e, quando entra um pedido novo ou há pagamentos por confirmar, aparece o
 * aviso sem ser preciso recarregar.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BadgeEuro,
  Bell,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Paperclip,
  RefreshCw,
  Search,
  Settings2,
  Smartphone,
  Trash2,
  Upload,
  UserCheck,
  XCircle,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui";
import {
  addReportNote,
  badgeVariant,
  bytes,
  decideReportsPayment,
  deleteReportFile,
  downloadReportFile,
  downloadReportsExport,
  getReportsAdmin,
  getReportsBackofficeMe,
  getReportsInbox,
  money,
  patchReportsRequest,
  saveReportsAdminSettings,
  saveReportsPackage,
  deleteReportsPackage,
  shortDate,
  uploadReportFile,
  type ReportsAdminPayload,
  type ReportsBackofficeInbox,
  type ReportsPackage,
  type ReportsRequest,
} from "../reportsApi";

type SubTab = "pedidos" | "definicoes" | "catalogo";

export function AdminReportsTab({ onError }: { onError: (message: string | null) => void }) {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [inbox, setInbox] = useState<ReportsBackofficeInbox | null>(null);
  const [admin, setAdmin] = useState<ReportsAdminPayload | null>(null);
  const [tab, setTab] = useState<SubTab>("pedidos");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [alert, setAlert] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const knownPending = useRef<number | null>(null);

  const focus = useMemo(() => inbox?.items.find((item) => item.id === focusId) ?? null, [focusId, inbox]);

  const loadInbox = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!options.silent) setBusy(true);
      try {
        const payload = await getReportsInbox({ status, q: query, mine });
        setInbox(payload);
        setAllowed(true);
        onError(null);
        setFocusId((current) => {
          // Mantém a ficha aberta se o pedido continuar na vista filtrada; em
          // telemóvel não abre sozinha (esconderia a lista).
          if (current && payload.items.some((item) => item.id === current)) return current;
          return window.matchMedia("(max-width: 767px)").matches ? null : payload.items[0]?.id ?? null;
        });
        // Aviso quando entram pedidos novos ou há pagamentos por confirmar.
        const pending = (payload.stats.pending_payment || 0) + (payload.stats.awaiting_confirm || 0);
        if (knownPending.current !== null && pending > knownPending.current) {
          setAlert(`Chegaram novos pedidos (${pending} por tratar).`);
        }
        knownPending.current = pending;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Erro ao carregar os pedidos.";
        if (/403|Sem acesso/i.test(message)) {
          setAllowed(false);
        } else {
          onError(message);
        }
      } finally {
        if (!options.silent) setBusy(false);
      }
    },
    [mine, onError, query, status],
  );

  const loadAdmin = useCallback(async () => {
    try {
      setAdmin(await getReportsAdmin());
    } catch {
      setAdmin(null);
    }
  }, []);

  useEffect(() => {
    void getReportsBackofficeMe()
      .then((me) => {
        setAllowed(me.backoffice);
        if (me.backoffice) {
          void loadInbox();
          void loadAdmin();
        }
      })
      .catch(() => setAllowed(false));
  }, [loadAdmin, loadInbox]);

  useEffect(() => {
    if (allowed !== true) return undefined;
    const timer = window.setInterval(() => void loadInbox({ silent: true }), 30000);
    return () => window.clearInterval(timer);
  }, [allowed, loadInbox]);

  /** Em telemóvel (uma coluna) só se mostra a lista **ou** a ficha do pedido. */
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const sync = () => setNarrow(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (allowed === true) void loadInbox();
  }, [allowed, loadInbox]);

  async function act(action: () => Promise<ReportsRequest | void>, message: string) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      setNotice(message);
      await loadInbox({ silent: true });
      await loadAdmin();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Operação falhou.");
    } finally {
      setBusy(false);
    }
  }

  if (allowed === false) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
          <AlertTriangle size={22} className="text-amber-400" />
          <p>Esta conta não tem acesso ao backoffice de relatórios.</p>
          <p className="text-xs">
            Um administrador pode autorizá-la em <strong>Definições → Contas de backoffice</strong> (o papel <code>admin</code> tem sempre
            acesso).
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
      {alert && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <span className="flex items-center gap-2">
            <Bell size={14} /> {alert}
          </span>
          <button type="button" onClick={() => setAlert(null)}>
            <XCircle size={14} />
          </button>
        </div>
      )}

      <Tabs value={tab} onValueChange={(value) => setTab(value as SubTab)} className="flex min-h-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="pedidos" active={tab === "pedidos"} onClick={() => setTab("pedidos")}>
              Pedidos {inbox ? `(${inbox.stats.open + inbox.stats.awaiting_confirm})` : ""}
            </TabsTrigger>
            <TabsTrigger value="definicoes" active={tab === "definicoes"} onClick={() => setTab("definicoes")}>
              Definições
            </TabsTrigger>
            <TabsTrigger value="catalogo" active={tab === "catalogo"} onClick={() => setTab("catalogo")}>
              Catálogo
            </TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-2">
            {inbox && (
              <div className="hidden items-center gap-2 text-[11px] text-muted-foreground sm:flex">
                <span>{inbox.stats.total} pedidos</span>
                <span>·</span>
                <span>{inbox.stats.awaiting_confirm} pagamentos a confirmar</span>
                <span>·</span>
                <span>{money(inbox.stats.revenue)} faturado</span>
              </div>
            )}
            <Button variant="outline" size="sm" onClick={() => void loadInbox()} title="Atualizar">
              {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            </Button>
            <Button variant="outline" size="sm" onClick={() => void downloadReportsExport(status).catch((error) => onError((error as Error).message))}>
              <Download size={13} /> CSV
            </Button>
          </div>
        </div>

        {notice && (
          <p className="mt-2 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 size={13} /> {notice}
          </p>
        )}

        {/* ------------------------------------------------------- pedidos */}
        <TabsContent value="pedidos" active={tab === "pedidos"} className="mt-3 flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
          <div className={`flex w-full shrink-0 flex-col gap-2 md:w-[340px] ${narrow && focus ? "hidden" : ""}`}>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Referência, cliente, empresa…"
                  className="pl-7"
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              <button
                type="button"
                onClick={() => setStatus("")}
                className={`rounded-full border px-2 py-0.5 text-[11px] ${status === "" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                Todos
              </button>
              {(inbox?.statuses ?? []).map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => setStatus(entry.id)}
                  className={`rounded-full border px-2 py-0.5 text-[11px] ${
                    status === entry.id ? "bg-primary text-primary-foreground" : "text-muted-foreground"
                  }`}
                >
                  {entry.label}
                  {inbox?.stats.by_status?.[entry.id] ? ` (${inbox.stats.by_status[entry.id]})` : ""}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setMine((current) => !current)}
                className={`rounded-full border px-2 py-0.5 text-[11px] ${mine ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                Só os meus
              </button>
            </div>

            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {(inbox?.items ?? []).length === 0 && <p className="px-1 py-6 text-center text-xs text-muted-foreground">Sem pedidos nesta vista.</p>}
              {(inbox?.items ?? []).map((request) => (
                <button
                  key={request.id}
                  type="button"
                  onClick={() => setFocusId(request.id)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    focusId === request.id ? "border-sky-500/60 bg-sky-500/5" : "hover:border-sky-500/30 hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{request.reference}</span>
                    <Badge variant={badgeVariant(request.status_style)}>{request.status_label}</Badge>
                  </div>
                  <p className="mt-1 truncate text-sm font-medium">{request.package_title}</p>
                  <p className="truncate text-[11px] text-muted-foreground">{request.targets_label}</p>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="truncate">{request.requester.name || request.requester.email}</span>
                    <span>{money(request.amounts.total)}</span>
                  </div>
                  {request.assigned_to && (
                    <p className="mt-1 flex items-center gap-1 truncate text-[10px] text-muted-foreground">
                      <UserCheck size={10} /> {request.assigned_to}
                    </p>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className={`min-h-0 flex-1 overflow-y-auto ${narrow && !focus ? "hidden" : ""}`}>
            {narrow && focus && (
              <button
                type="button"
                onClick={() => setFocusId(null)}
                className="mb-2 flex items-center gap-1 rounded-lg border px-2 py-1 text-xs text-muted-foreground"
              >
                <ArrowLeft size={13} /> Voltar à lista
              </button>
            )}
            {focus ? (
              <RequestWorkbench
                request={focus}
                busy={busy}
                onError={onError}
                onAssign={() =>
                  act(
                    () => patchReportsRequest(focus.id, { status: focus.status, assigned_to: inbox?.me.email ?? "" }),
                    "Pedido atribuído a si.",
                  )
                }
                onPayment={(action, note) =>
                  act(() => decideReportsPayment(focus.id, { action, note }), action === "confirm" ? "Pagamento confirmado." : "Pagamento rejeitado.")
                }
                onStatus={(next, note, internal) =>
                  act(() => patchReportsRequest(focus.id, { status: next, note, internal }), `Estado atualizado para ${next}.`)
                }
                onNote={(message, internal) => act(() => addReportNote(focus.id, { message, internal }), "Nota registada.")}
                onUpload={async (file) => {
                  setBusy(true);
                  try {
                    await uploadReportFile(focus.id, file, true);
                    setNotice("Relatório anexado e disponibilizado ao cliente.");
                    await loadInbox({ silent: true });
                  } catch (error) {
                    onError((error as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
                onDeleteFile={(fileId) => act(() => deleteReportFile(focus.id, fileId).then(() => undefined), "Ficheiro removido.")}
                fileInput={fileInput}
              />
            ) : (
              <Card>
                <CardContent className="py-10 text-center text-sm text-muted-foreground">Escolha um pedido na lista.</CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* ---------------------------------------------------- definições */}
        <TabsContent value="definicoes" active={tab === "definicoes"} className="mt-3 min-h-0 flex-1 overflow-y-auto">
          <ReportsSettingsPanel payload={admin} onError={onError} onSaved={setNotice} reload={loadAdmin} canEdit />
        </TabsContent>

        {/* ------------------------------------------------------ catálogo */}
        <TabsContent value="catalogo" active={tab === "catalogo"} className="mt-3 min-h-0 flex-1 overflow-y-auto">
          <CataloguePanel payload={admin} onError={onError} onSaved={setNotice} reload={loadAdmin} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ------------------------------------------------------------------- pedido
function RequestWorkbench({
  request,
  busy,
  onError,
  onAssign,
  onPayment,
  onStatus,
  onNote,
  onUpload,
  onDeleteFile,
  fileInput,
}: {
  request: ReportsRequest;
  busy: boolean;
  onError: (message: string | null) => void;
  onAssign: () => void;
  onPayment: (action: "confirm" | "reject", note: string) => void;
  onStatus: (next: string, note: string, internal: boolean) => void;
  onNote: (message: string, internal: boolean) => void;
  onUpload: (file: File) => void;
  onDeleteFile: (fileId: string) => void;
  fileInput: React.RefObject<HTMLInputElement | null>;
}) {
  const [note, setNote] = useState("");
  const [paymentNote, setPaymentNote] = useState("");
  const paymentPending = ["pendente", "aguarda_confirmacao"].includes(request.payment.status);

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            <span className="font-mono text-xs text-muted-foreground">{request.reference}</span>
            {request.package_title}
            <Badge variant={badgeVariant(request.status_style)}>{request.status_label}</Badge>
            {request.amounts.total > 0 && <Badge variant={badgeVariant(request.payment.status_style)}>{request.payment.status_label}</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted-foreground">Cliente</p>
            <p>{request.requester.name || "—"}</p>
            <p className="text-xs text-muted-foreground">{request.requester.email}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Empresas</p>
            <p>{request.targets_label}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Valor</p>
            <p>
              {money(request.amounts.total)} <span className="text-xs text-muted-foreground">({money(request.amounts.vat)} IVA)</span>
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Criado</p>
            <p>{shortDate(request.created_at)}</p>
          </div>
          {request.notes && (
            <div className="sm:col-span-2">
              <p className="text-xs text-muted-foreground">Notas do cliente</p>
              <p className="whitespace-pre-wrap text-sm">{request.notes}</p>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
            <Button variant="outline" size="sm" onClick={onAssign} disabled={busy}>
              <UserCheck size={13} /> Atribuir a mim
            </Button>
            {request.payment.mbway_phone && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Smartphone size={13} /> MB Way: {request.payment.mbway_phone}
              </span>
            )}
            {request.payment.mbway_reference && (
              <span className="text-xs text-muted-foreground">Ref. {request.payment.mbway_reference}</span>
            )}
            {request.payment.paid_at && <span className="text-xs text-muted-foreground">Pago em {shortDate(request.payment.paid_at)}</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BadgeEuro size={15} /> Pagamento
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {paymentPending ? (
            <>
              <p className="text-xs text-muted-foreground">
                Confirme depois de ver o MB Way no telemóvel/extrato. A confirmação avança o pedido para <strong>Pagamento confirmado</strong> e avisa o
                cliente.
              </p>
              <Input value={paymentNote} onChange={(event) => setPaymentNote(event.target.value)} placeholder="Nota (ex.: MB Way 912345678 às 15h20)" autoComplete="off" />
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => onPayment("confirm", paymentNote)} disabled={busy}>
                  <CheckCircle2 size={14} /> Confirmar pagamento
                </Button>
                <Button variant="outline" onClick={() => onPayment("reject", paymentNote)} disabled={busy}>
                  <XCircle size={14} /> Rejeitar
                </Button>
              </div>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Pagamento {request.payment.status_label.toLowerCase()}
              {request.payment.confirmed_by ? ` por ${request.payment.confirmed_by}` : ""}
              {request.payment.automatic ? " (automático, MB Way)" : ""}.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText size={15} /> Produção e entrega
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {request.next_statuses.map((entry) => (
              <Button key={entry.id} variant="outline" size="sm" disabled={busy} onClick={() => onStatus(entry.id, note, false)}>
                {entry.label}
              </Button>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
            <div className="space-y-2">
              <Label htmlFor="workbench-note">Nota (vai para o histórico)</Label>
              <Input
                id="workbench-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Ex.: à espera do balanço de 2025"
                autoComplete="off"
              />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={busy || !note} onClick={() => onNote(note, false)}>
                Nota pública
              </Button>
              <Button variant="outline" size="sm" disabled={busy || !note} onClick={() => onNote(note, true)}>
                Nota interna
              </Button>
            </div>
          </div>

          <div className="rounded-xl border border-dashed p-3">
            <p className="mb-2 flex items-center gap-2 text-xs font-medium">
              <Paperclip size={13} /> Relatório produzido (fica disponível para o cliente)
            </p>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUpload(file);
                event.target.value = "";
              }}
            />
            <Button variant="outline" size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>
              <Upload size={13} /> Anexar ficheiro
            </Button>
            <p className="mt-2 text-[11px] text-muted-foreground">PDF, DOCX, XLSX, CSV, ZIP… até 25 MB. Anexar marca o pedido como «Gerado».</p>
          </div>

          {request.files.length > 0 && (
            <div className="space-y-2">
              {request.files.map((file) => (
                <div key={file.id} className="flex items-center justify-between gap-2 rounded-xl border bg-muted/40 px-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm">{file.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {bytes(file.size)} · {shortDate(file.uploaded_at)} · {file.uploaded_by}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void downloadReportFile(request.id, file.id, file.name).catch((error) => onError((error as Error).message))}
                    >
                      <Download size={13} />
                    </Button>
                    <Button variant="outline" size="sm" disabled={busy} onClick={() => onDeleteFile(file.id)}>
                      <Trash2 size={13} />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Histórico</CardTitle>
        </CardHeader>
        <CardContent>
          {request.internal_note && (
            <p className="mb-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Nota interna: {request.internal_note}
            </p>
          )}
          <ul className="space-y-1 text-xs">
            {request.history.map((item) => (
              <li key={item.id} className="rounded-lg border bg-muted/30 px-3 py-2">
                <p>{item.message}</p>
                <p className="text-[10px] text-muted-foreground">
                  {shortDate(item.at)} · {item.by} {item.visibility === "internal" ? "· interno" : ""}
                </p>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- definições
export function ReportsSettingsPanel({
  payload,
  onError,
  onSaved,
  reload,
  canEdit,
}: {
  payload: ReportsAdminPayload | null;
  onError: (message: string | null) => void;
  onSaved: (message: string) => void;
  reload: () => Promise<void> | void;
  canEdit: boolean;
}) {
  const [form, setForm] = useState({
    mbway_number: "",
    mbway_holder: "",
    mbway_enabled: true,
    mbway_provider: "ifthenpay",
    mbway_api_key: "",
    mbway_api_url: "",
    auto_confirm_mbway_api: true,
    iban: "",
    payment_instructions: "",
    vat_rate: 23,
    default_delivery_days: 2,
    backoffice_users: "",
    notify_extra_emails: "",
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!payload) return;
    const data = payload.settings;
    setForm({
      mbway_number: data.mbway_number || "",
      mbway_holder: data.mbway_holder || "",
      mbway_enabled: Boolean(data.mbway_enabled),
      mbway_provider: data.mbway_provider || "ifthenpay",
      mbway_api_key: "",
      mbway_api_url: data.mbway_api_url || "",
      auto_confirm_mbway_api: Boolean(data.auto_confirm_mbway_api),
      iban: data.iban || "",
      payment_instructions: data.payment_instructions || "",
      vat_rate: Number(data.vat_rate || 23),
      default_delivery_days: Number(data.default_delivery_days || 2),
      backoffice_users: (data.backoffice_users || []).join("\n"),
      notify_extra_emails: (data.notify_extra_emails || []).join("\n"),
    });
  }, [payload]);

  if (!payload) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Só os administradores podem editar a configuração dos relatórios.
        </CardContent>
      </Card>
    );
  }

  async function save() {
    setBusy(true);
    onError(null);
    try {
      await saveReportsAdminSettings({
        mbway_number: form.mbway_number,
        mbway_holder: form.mbway_holder,
        mbway_enabled: form.mbway_enabled,
        mbway_provider: form.mbway_provider,
        mbway_api_url: form.mbway_api_url,
        auto_confirm_mbway_api: form.auto_confirm_mbway_api,
        iban: form.iban,
        payment_instructions: form.payment_instructions,
        vat_rate: Number(form.vat_rate),
        default_delivery_days: Number(form.default_delivery_days),
        backoffice_users: form.backoffice_users.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean),
        notify_extra_emails: form.notify_extra_emails.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean),
        ...(form.mbway_api_key ? { mbway_api_key: form.mbway_api_key } : {}),
      });
      onSaved("Configuração de relatórios guardada.");
      setForm((current) => ({ ...current, mbway_api_key: "" }));
      await reload();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Não foi possível guardar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Settings2 size={15} /> Pagamento e backoffice
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="mbway-number">Número MB Way</Label>
            <Input
              id="mbway-number"
              value={form.mbway_number}
              onChange={(event) => setForm((current) => ({ ...current, mbway_number: event.target.value }))}
              placeholder="919520386"
              inputMode="tel"
              autoComplete="off"
              disabled={!canEdit}
            />
            <p className="text-[11px] text-muted-foreground">É o número que o cliente vê no pedido.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mbway-holder">Titular</Label>
            <Input
              id="mbway-holder"
              value={form.mbway_holder}
              onChange={(event) => setForm((current) => ({ ...current, mbway_holder: event.target.value }))}
              placeholder="IQ OS, Lda."
              autoComplete="off"
              disabled={!canEdit}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mbway-enabled">Estado</Label>
            <select
              id="mbway-enabled"
              value={form.mbway_enabled ? "1" : "0"}
              onChange={(event) => setForm((current) => ({ ...current, mbway_enabled: event.target.value === "1" }))}
              className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              disabled={!canEdit}
            >
              <option value="1">MB Way ativo</option>
              <option value="0">Desativado</option>
            </select>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="mbway-provider">Integração automática</Label>
            <select
              id="mbway-provider"
              value={form.mbway_provider}
              onChange={(event) => setForm((current) => ({ ...current, mbway_provider: event.target.value }))}
              className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              disabled={!canEdit}
            >
              <option value="ifthenpay">IFTThenPay (API)</option>
              <option value="manual">Manual (só transferência)</option>
            </select>
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="mbway-key">Chave de API (MbWayKey)</Label>
            <Input
              id="mbway-key"
              value={form.mbway_api_key}
              onChange={(event) => setForm((current) => ({ ...current, mbway_api_key: event.target.value }))}
              placeholder={payload.settings.mbway_api_set ? `Configurada ${payload.settings.mbway_api_hint}` : "Deixe vazio para só transferência manual"}
              autoComplete="off"
              disabled={!canEdit}
            />
            <p className="text-[11px] text-muted-foreground">
              Com chave, o cliente pode receber o <strong>pedido de pagamento no telemóvel</strong> e o pagamento confirma-se sozinho.
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="mbway-url">URL da API</Label>
            <Input
              id="mbway-url"
              value={form.mbway_api_url}
              onChange={(event) => setForm((current) => ({ ...current, mbway_api_url: event.target.value }))}
              placeholder="https://mbway.ifthenpay.com/ifthenpaymbw.ashx"
              autoComplete="off"
              disabled={!canEdit}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mbway-auto">Confirmação automática</Label>
            <select
              id="mbway-auto"
              value={form.auto_confirm_mbway_api ? "1" : "0"}
              onChange={(event) => setForm((current) => ({ ...current, auto_confirm_mbway_api: event.target.value === "1" }))}
              className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              disabled={!canEdit}
            >
              <option value="1">Sim</option>
              <option value="0">Não</option>
            </select>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="vat-rate">Taxa de IVA (%)</Label>
            <Input
              id="vat-rate"
              value={String(form.vat_rate)}
              onChange={(event) => setForm((current) => ({ ...current, vat_rate: Number(event.target.value.replace(",", ".")) || 0 }))}
              inputMode="decimal"
              autoComplete="off"
              disabled={!canEdit}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="delivery-days">Dias de entrega (por omissão)</Label>
            <Input
              id="delivery-days"
              value={String(form.default_delivery_days)}
              onChange={(event) => setForm((current) => ({ ...current, default_delivery_days: Number(event.target.value) || 0 }))}
              inputMode="numeric"
              autoComplete="off"
              disabled={!canEdit}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="iban">IBAN (opcional)</Label>
            <Input
              id="iban"
              value={form.iban}
              onChange={(event) => setForm((current) => ({ ...current, iban: event.target.value }))}
              placeholder="PT50 …"
              autoComplete="off"
              disabled={!canEdit}
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="instructions">Instruções de pagamento mostradas ao cliente</Label>
          <textarea
            id="instructions"
            value={form.payment_instructions}
            onChange={(event) => setForm((current) => ({ ...current, payment_instructions: event.target.value }))}
            rows={3}
            className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
            disabled={!canEdit}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="backoffice">Contas de backoffice (uma por linha)</Label>
            <textarea
              id="backoffice"
              value={form.backoffice_users}
              onChange={(event) => setForm((current) => ({ ...current, backoffice_users: event.target.value }))}
              rows={4}
              placeholder="ana@empresa.pt&#10;rui@empresa.pt"
              className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              disabled={!canEdit}
            />
            <p className="text-[11px] text-muted-foreground">Recebem os pedidos e podem tratá-los. Os administradores têm sempre acesso.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="extra-emails">Emails extra avisados de cada pedido</Label>
            <textarea
              id="extra-emails"
              value={form.notify_extra_emails}
              onChange={(event) => setForm((current) => ({ ...current, notify_extra_emails: event.target.value }))}
              rows={4}
              placeholder="producao@empresa.pt"
              className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              disabled={!canEdit}
            />
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] text-muted-foreground">
            Última alteração: {payload.settings.updated_at ? shortDate(payload.settings.updated_at) : "—"} {payload.settings.updated_by}
          </p>
          <Button onClick={() => void save()} disabled={busy || !canEdit}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Guardar
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ catálogo
function CataloguePanel({
  payload,
  onError,
  onSaved,
  reload,
}: {
  payload: ReportsAdminPayload | null;
  onError: (message: string | null) => void;
  onSaved: (message: string) => void;
  reload: () => Promise<void> | void;
}) {
  const [editing, setEditing] = useState<ReportsPackage | null>(null);
  const [busy, setBusy] = useState(false);

  if (!payload) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Só os administradores podem editar o catálogo de relatórios.
        </CardContent>
      </Card>
    );
  }

  async function save(item: Partial<ReportsPackage>) {
    setBusy(true);
    onError(null);
    try {
      await saveReportsPackage(item);
      onSaved("Catálogo atualizado.");
      setEditing(null);
      await reload();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Não foi possível gravar o pacote.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {editing && (
        <Card className="border-sky-500/40">
          <CardHeader>
            <CardTitle className="text-base">{editing.id ? `Editar «${editing.title}»` : "Novo pacote"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-2">
                <Label>Título</Label>
                <Input value={editing.title} onChange={(event) => setEditing({ ...editing, title: event.target.value })} autoComplete="off" />
              </div>
              <div className="space-y-2">
                <Label>Subtítulo</Label>
                <Input value={editing.subtitle} onChange={(event) => setEditing({ ...editing, subtitle: event.target.value })} autoComplete="off" />
              </div>
              <div className="space-y-2">
                <Label>Etiqueta</Label>
                <Input value={editing.badge} onChange={(event) => setEditing({ ...editing, badge: event.target.value })} placeholder="RECOMENDADO" autoComplete="off" />
              </div>
              <div className="space-y-2">
                <Label>Preço (€)</Label>
                <Input
                  value={String(editing.price)}
                  onChange={(event) => setEditing({ ...editing, price: Number(event.target.value.replace(",", ".")) || 0 })}
                  inputMode="decimal"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label>Preço antigo (€)</Label>
                <Input
                  value={String(editing.list_price)}
                  onChange={(event) => setEditing({ ...editing, list_price: Number(event.target.value.replace(",", ".")) || 0 })}
                  inputMode="decimal"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label>Dias de entrega</Label>
                <Input
                  value={String(editing.delivery_days)}
                  onChange={(event) => setEditing({ ...editing, delivery_days: Number(event.target.value) || 0 })}
                  inputMode="numeric"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label>Empresas por pedido</Label>
                <Input
                  value={String(editing.max_targets)}
                  onChange={(event) => setEditing({ ...editing, max_targets: Number(event.target.value) || 1 })}
                  inputMode="numeric"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label>Estado</Label>
                <select
                  value={editing.active ? "1" : "0"}
                  onChange={(event) => setEditing({ ...editing, active: event.target.value === "1" })}
                  className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                >
                  <option value="1">Ativo</option>
                  <option value="0">Inativo</option>
                </select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Itens incluídos (um por linha)</Label>
              <textarea
                value={editing.features.join("\n")}
                onChange={(event) => setEditing({ ...editing, features: event.target.value.split("\n") })}
                rows={6}
                className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditing(null)}>
                Cancelar
              </Button>
              <Button disabled={busy} onClick={() => void save(editing)}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Guardar pacote
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Preços finais (IVA incluído). Alterações aplicam-se aos pedidos novos.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            setEditing({
              id: "",
              code: "",
              title: "",
              subtitle: "",
              note: "",
              price: 0,
              list_price: 0,
              badge: "",
              max_targets: 1,
              delivery_days: Number(payload.settings.default_delivery_days || 2),
              active: true,
              features: [],
            })
          }
        >
          Novo pacote
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {payload.catalogue.map((item) => (
          <Card key={item.id}>
            <CardContent className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">{item.title}</p>
                  <p className="text-xs text-muted-foreground">{item.subtitle}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold text-orange-500">{item.price > 0 ? money(item.price) : "Grátis"}</p>
                  {item.list_price > item.price && <p className="text-[11px] text-muted-foreground line-through">{money(item.list_price)}</p>}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <Badge variant={item.active ? "success" : "secondary"}>{item.active ? "Ativo" : "Inativo"}</Badge>
                <span>{item.delivery_days} dia(s)</span>
                <span>· até {item.max_targets} empresa(s)</span>
                <span>· {item.features.length} itens</span>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => setEditing(item)}>
                  Editar
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (!window.confirm(`Remover «${item.title}» do catálogo?`)) return;
                    void deleteReportsPackage(item.id)
                      .then(() => {
                        onSaved("Pacote removido.");
                        return reload();
                      })
                      .catch((error) => onError((error as Error).message));
                  }}
                >
                  <Trash2 size={13} />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
