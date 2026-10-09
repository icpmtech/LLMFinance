/**
 * Página «Relatórios» — área do cliente.
 *
 * Três passos, na mesma página:
 *  1. escolher um pacote do catálogo (corporativo grátis, financeiro resumido,
 *     financeiro detalhado e concorrência);
 *  2. indicar as empresas alvo e (se o pacote for pago) pagar por **MB Way**
 *     para o número configurado na administração — o pedido de pagamento pode
 *     ser enviado para o telemóvel quando existe chave de API;
 *  3. acompanhar o estado em «Os meus relatórios» e descarregar o ficheiro
 *     quando o estado é **Gerado**.
 *
 * O sino no cabeçalho mostra as notificações do utilizador (novo pedido,
 * pagamento confirmado, relatório pronto), com sondagem a cada 30 s.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BadgeCheck,
  Bell,
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui";
import {
  badgeVariant,
  bytes,
  cancelReport,
  createReport,
  declareReportPayment,
  downloadReportFile,
  getMyReports,
  getReportPaymentStatus,
  getReportsCatalogue,
  getReportsNotifications,
  getReportsSummary,
  markReportsNotificationsRead,
  money,
  shortDate,
  type ReportsCatalogue,
  type ReportsNotification,
  type ReportsPackage,
  type ReportsRequest,
  type ReportsSummary,
  type ReportsTarget,
} from "../reportsApi";

type Toast = { id: number; message: string; tone: "info" | "error" | "ok" };

export default function ReportsPage() {
  const [catalogue, setCatalogue] = useState<ReportsCatalogue | null>(null);
  const [summary, setSummary] = useState<ReportsSummary | null>(null);
  const [items, setItems] = useState<ReportsRequest[]>([]);
  const [notifications, setNotifications] = useState<ReportsNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [showBell, setShowBell] = useState(false);
  const [tab, setTab] = useState<"pedir" | "meus">("pedir");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<ReportsPackage | null>(null);
  const [targets, setTargets] = useState<ReportsTarget[]>([{ name: "", nif: "" }]);
  const [notes, setNotes] = useState("");
  const [phone, setPhone] = useState("");
  const [created, setCreated] = useState<ReportsRequest | null>(null);
  const [focus, setFocus] = useState<ReportsRequest | null>(null);
  const [filter, setFilter] = useState("");
  const [payPhone, setPayPhone] = useState("");
  const [payNote, setPayNote] = useState("");
  const [busy, setBusy] = useState(false);

  const notify = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4600);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cataloguePayload, summaryPayload, list, feed] = await Promise.all([
        getReportsCatalogue(),
        getReportsSummary(),
        getMyReports(),
        getReportsNotifications(),
      ]);
      setCatalogue(cataloguePayload);
      setSummary(summaryPayload);
      setItems(list.items);
      setNotifications(feed.items);
      setUnread(feed.unread);
      setSelected((current) => current ?? cataloguePayload.packages.find((item) => item.price > 0) ?? cataloguePayload.packages[0] ?? null);
      setPayPhone((current) => current || "");
      setPhone((current) => current || "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Sondagem das notificações: é assim que o cliente é «avisado». */
  useEffect(() => {
    let previous = unread;
    const timer = window.setInterval(() => {
      void getReportsNotifications(10)
        .then((feed) => {
          setNotifications(feed.items);
          setUnread(feed.unread);
          if (feed.unread > previous) {
            const latest = feed.items.find((item) => !item.read);
            if (latest) notify(`${latest.title}: ${latest.body}`, "ok");
          }
          previous = feed.unread;
        })
        .catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(timer);
  }, [notify, unread]);

  const packages = catalogue?.packages ?? [];
  const settings = catalogue?.settings;
  const filtered = useMemo(() => (filter ? items.filter((item) => item.status === filter) : items), [filter, items]);

  const needsPayment = (request: ReportsRequest | null) => Boolean(request && request.amounts.total > 0 && request.payment.status !== "confirmado");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) {
      notify("Escolha um relatório.", "error");
      return;
    }
    const clean = targets.map((target) => ({ name: target.name.trim(), nif: target.nif.replace(/\D+/g, "") })).filter((target) => target.name || target.nif);
    if (!clean.length) {
      notify("Indique a empresa (nome ou NIF).", "error");
      return;
    }
    setSubmitting(true);
    try {
      const request = await createReport({ package_id: selected.id, targets: clean, notes, mbway_phone: phone });
      setCreated(request);
      notify(`Pedido ${request.reference} criado.`, "ok");
      setTargets([{ name: "", nif: "" }]);
      setNotes("");
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function declare() {
    if (!created) return;
    setBusy(true);
    try {
      const result = await declareReportPayment(created.id, { method: "mbway", mbway_phone: payPhone || phone, note: payNote });
      setCreated(result.request);
      if (result.automatic?.ok) {
        notify("Pedido de pagamento enviado para o seu telemóvel. Aprove no MB Way.", "ok");
      } else if (result.automatic?.configured && result.automatic.message) {
        notify(`MB Way automático indisponível: ${result.automatic.message} — o backoffice confirma o pagamento.`, "info");
      } else {
        notify("Registámos o seu aviso de pagamento. O backoffice vai confirmar.", "ok");
      }
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function checkStatus() {
    if (!created) return;
    setBusy(true);
    try {
      const result = await getReportPaymentStatus(created.id);
      setCreated(result.request);
      notify(result.paid ? "Pagamento confirmado!" : result.message || "Ainda não há confirmação do MB Way.", result.paid ? "ok" : "info");
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function openBell() {
    setShowBell((current) => !current);
    if (!showBell && unread > 0) {
      try {
        const result = await markReportsNotificationsRead();
        setUnread(result.unread);
        setNotifications((current) => current.map((item) => ({ ...item, read: true })));
      } catch {
        /* silencioso */
      }
    }
  }

  async function cancel(request: ReportsRequest) {
    if (!window.confirm(`Cancelar o pedido ${request.reference}?`)) return;
    try {
      await cancelReport(request.id, "Cancelado pelo cliente.");
      notify("Pedido cancelado.", "ok");
      setFocus(null);
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    }
  }

  async function download(request: ReportsRequest, fileId: string, name: string) {
    try {
      await downloadReportFile(request.id, fileId, name);
      notify("Download iniciado.", "ok");
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-sky-500 to-emerald-600 text-white shadow-lg shadow-sky-500/25">
              <FileText size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Relatórios</h1>
              <p className="text-sm text-muted-foreground">
                Peça relatórios corporativos, financeiros e de concorrência — pagamento por MB Way
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {summary && (
              <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
                <span className="flex items-center gap-1">
                  <Clock size={13} /> {summary.in_progress} em curso
                </span>
                <span className="flex items-center gap-1">
                  <CheckCircle2 size={13} /> {summary.ready} prontos
                </span>
                <span className="flex items-center gap-1">
                  <AlertCircle size={13} /> {summary.to_pay} por pagar
                </span>
              </div>
            )}
            <Button variant="outline" size="sm" onClick={() => void load()} title="Atualizar">
              <RefreshCw size={14} />
            </Button>
            <div className="relative">
              <Button variant="outline" size="sm" onClick={() => void openBell()} title="Notificações">
                <Bell size={14} />
                {unread > 0 && (
                  <span className="ml-1 rounded-full bg-rose-500 px-1.5 text-[10px] font-semibold text-white">{unread}</span>
                )}
              </Button>
              {showBell && (
                <div className="absolute right-0 z-40 mt-2 w-[360px] rounded-xl border bg-card p-2 shadow-2xl">
                  <p className="px-2 py-1 text-xs font-semibold text-muted-foreground">Notificações</p>
                  {notifications.length === 0 ? (
                    <p className="px-2 py-4 text-xs text-muted-foreground">Sem novidades.</p>
                  ) : (
                    notifications.map((item) => (
                      <div key={item.id} className="rounded-lg px-2 py-2 text-xs hover:bg-muted/60">
                        <p className="font-medium">{item.title}</p>
                        <p className="text-muted-foreground">{item.body}</p>
                        <p className="mt-1 text-[10px] text-muted-foreground/70">{shortDate(item.created_at)}</p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" /> A carregar relatórios…
          </div>
        )}
        {error && <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{error}</p>}

        {!loading && !error && (
          <Tabs value={tab} onValueChange={(value) => setTab(value as "pedir" | "meus")} className="w-full">
            <TabsList className="mb-4">
              <TabsTrigger value="pedir" active={tab === "pedir"} onClick={() => setTab("pedir")}>
                Pedir relatório
              </TabsTrigger>
              <TabsTrigger value="meus" active={tab === "meus"} onClick={() => setTab("meus")}>
                Os meus relatórios {items.length > 0 ? `(${items.length})` : ""}
              </TabsTrigger>
            </TabsList>

            {/* ------------------------------------------------------ pedir */}
            <TabsContent value="pedir" active={tab === "pedir"} className="space-y-4">
              {created ? (
                <PaymentPanel
                  request={created}
                  settings={settings}
                  busy={busy}
                  payPhone={payPhone || phone}
                  payNote={payNote}
                  onPhone={setPayPhone}
                  onNote={setPayNote}
                  onDeclare={() => void declare()}
                  onCheck={() => void checkStatus()}
                  onClose={() => {
                    setCreated(null);
                    setTab("meus");
                  }}
                  onOpen={(request) => setFocus(request)}
                />
              ) : (
                <>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {packages.map((item) => (
                      <PackageCard
                        key={item.id}
                        item={item}
                        selected={selected?.id === item.id}
                        onSelect={() => setSelected(item)}
                      />
                    ))}
                  </div>

                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-base">
                        <Sparkles size={16} /> Dados do pedido
                        {selected && <Badge variant="info">{selected.title}</Badge>}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <form onSubmit={submit} className="space-y-4">
                        <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <Label>
                              Empresas a analisar
                              {selected ? ` (até ${selected.max_targets})` : ""}
                            </Label>
                            {selected && selected.max_targets > 1 && (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => setTargets((current) => (current.length >= (selected.max_targets || 1) ? current : [...current, { name: "", nif: "" }]))}
                              >
                                <Plus size={13} /> Empresa
                              </Button>
                            )}
                          </div>
                          {targets.map((target, index) => (
                            <div key={index} className="grid gap-2 sm:grid-cols-[1fr_180px_40px]">
                              <Input
                                value={target.name}
                                onChange={(event) =>
                                  setTargets((current) => current.map((item, position) => (position === index ? { ...item, name: event.target.value } : item)))
                                }
                                placeholder="Nome da empresa"
                                autoComplete="off"
                                required={index === 0}
                              />
                              <Input
                                value={target.nif}
                                onChange={(event) =>
                                  setTargets((current) => current.map((item, position) => (position === index ? { ...item, nif: event.target.value } : item)))
                                }
                                placeholder="NIF (opcional)"
                                inputMode="numeric"
                                autoComplete="off"
                              />
                              {targets.length > 1 ? (
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setTargets((current) => current.filter((_, position) => position !== index))}
                                  title="Remover empresa"
                                >
                                  <Trash2 size={13} />
                                </Button>
                              ) : (
                                <span />
                              )}
                            </div>
                          ))}
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="reports-notes">Notas para a equipa (opcional)</Label>
                          <textarea
                            id="reports-notes"
                            value={notes}
                            onChange={(event) => setNotes(event.target.value)}
                            rows={3}
                            maxLength={2000}
                            placeholder="Ex.: preciso de comparar com o concorrente do Algarve; urgente até sexta."
                            className="w-full rounded-xl border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-500/40"
                          />
                        </div>

                        {selected && selected.price > 0 && (
                          <div className="grid gap-3 sm:grid-cols-[220px_1fr] sm:items-end">
                            <div className="space-y-2">
                              <Label htmlFor="reports-phone">Telemóvel (MB Way)</Label>
                              <Input
                                id="reports-phone"
                                value={phone}
                                onChange={(event) => setPhone(event.target.value)}
                                placeholder="912 345 678"
                                inputMode="tel"
                                autoComplete="off"
                              />
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {settings?.mbway_api
                                ? "Se indicar o telemóvel, enviamos o pedido de pagamento MB Way depois de criar o pedido."
                                : `Pagamento por transferência MB Way para ${settings?.mbway_number || "—"}.`}
                            </p>
                          </div>
                        )}

                        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/40 px-4 py-3">
                          <div className="text-sm">
                            <p className="font-medium">
                              Total a pagar: {money(selected?.price ?? 0)}
                              {selected && selected.list_price > selected.price && (
                                <span className="ml-2 text-xs text-muted-foreground line-through">{money(selected.list_price)}</span>
                              )}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {selected && selected.price > 0
                                ? `IVA incluído à taxa de ${settings?.vat_rate ?? 0}% · entrega até ${selected.delivery_days} dia(s)`
                                : "Relatório gratuito — sem pagamento"}
                            </p>
                          </div>
                          <Button type="submit" disabled={submitting || !selected}>
                            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Criar pedido
                          </Button>
                        </div>
                      </form>
                    </CardContent>
                  </Card>
                </>
              )}
            </TabsContent>

            {/* ------------------------------------------------------- meus */}
            <TabsContent value="meus" active={tab === "meus"} className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant={filter === "" ? "default" : "outline"} size="sm" onClick={() => setFilter("")}>
                  Todos ({items.length})
                </Button>
                {summary?.labels &&
                  Object.entries(summary.labels)
                    .filter(([key]) => (summary.by_status[key] || 0) > 0)
                    .map(([key, label]) => (
                      <Button key={key} variant={filter === key ? "default" : "outline"} size="sm" onClick={() => setFilter(key)}>
                        {label} ({summary.by_status[key]})
                      </Button>
                    ))}
              </div>

              {filtered.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
                    <FileText size={22} />
                    <p>Ainda não pediu nenhum relatório.</p>
                    <Button variant="outline" size="sm" onClick={() => setTab("pedir")}>
                      Pedir o primeiro
                    </Button>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-3">
                  {filtered.map((request) => (
                    <RequestRow key={request.id} request={request} onOpen={() => setFocus(request)} onDownload={download} />
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}
      </main>

      {focus && (
        <RequestDetail
          request={focus}
          onClose={() => setFocus(null)}
          onDownload={download}
          onCancel={cancel}
          onPay={(request) => {
            setCreated(request);
            setFocus(null);
            setTab("pedir");
          }}
          canCancel={["aguarda_pagamento", "pagamento_confirmado"].includes(focus.status)}
          needsPayment={needsPayment(focus)}
        />
      )}

      <div className="pointer-events-none fixed bottom-20 right-4 z-[140] flex flex-col items-end gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={[
              "pointer-events-auto max-w-[380px] rounded-xl border px-3 py-2 text-[12px] shadow-xl backdrop-blur",
              toast.tone === "error"
                ? "border-rose-400/30 bg-rose-500/15 text-rose-100"
                : toast.tone === "ok"
                  ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-100"
                  : "border-white/12 bg-[#0b1a24]/95 text-foreground",
            ].join(" ")}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------- peças
function PackageCard({ item, selected, onSelect }: { item: ReportsPackage; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "relative flex h-full flex-col gap-2 rounded-2xl border p-4 text-left transition",
        selected ? "border-sky-500/60 bg-sky-500/5 shadow-lg shadow-sky-500/10" : "hover:border-sky-500/30 hover:bg-muted/40",
      ].join(" ")}
    >
      {item.badge && (
        <span className="absolute -top-2 right-3 rounded-full bg-orange-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
          {item.badge}
        </span>
      )}
      <p className="text-sm font-semibold">{item.title}</p>
      <p className="text-xs text-muted-foreground">{item.subtitle}</p>
      <p className="text-2xl font-bold text-orange-500">
        {item.price > 0 ? money(item.price) : "Grátis"}
        {item.list_price > item.price && <span className="ml-2 text-xs font-normal text-muted-foreground line-through">{money(item.list_price)}</span>}
      </p>
      <p className="text-[11px] text-muted-foreground">{item.note}</p>
      <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
        {item.features.slice(0, 6).map((feature) => (
          <li key={feature} className="flex items-start gap-1">
            <BadgeCheck size={12} className="mt-0.5 shrink-0 text-emerald-400" /> {feature}
          </li>
        ))}
        {item.features.length > 6 && <li className="pl-4">+ {item.features.length - 6} itens…</li>}
      </ul>
      <span className="mt-auto pt-2 text-[11px] font-medium text-sky-400">{selected ? "Selecionado" : "Escolher"}</span>
    </button>
  );
}

function PaymentPanel({
  request,
  settings,
  busy,
  payPhone,
  payNote,
  onPhone,
  onNote,
  onDeclare,
  onCheck,
  onClose,
  onOpen,
}: {
  request: ReportsRequest;
  settings?: ReportsCatalogue["settings"];
  busy: boolean;
  payPhone: string;
  payNote: string;
  onPhone: (value: string) => void;
  onNote: (value: string) => void;
  onDeclare: () => void;
  onCheck: () => void;
  onClose: () => void;
  onOpen: (request: ReportsRequest) => void;
}) {
  const paid = request.payment.status === "confirmado";
  const needsPayment = request.amounts.total > 0 && !paid;
  return (
    <Card className="border-sky-500/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Smartphone size={16} /> Pedido {request.reference}
          <Badge variant={badgeVariant(request.status_style)}>{request.status_label}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border bg-muted/40 p-3">
            <p className="text-xs text-muted-foreground">Relatório</p>
            <p className="text-sm font-medium">{request.package_title}</p>
            <p className="text-xs text-muted-foreground">{request.targets_label}</p>
          </div>
          <div className="rounded-xl border bg-muted/40 p-3">
            <p className="text-xs text-muted-foreground">Total</p>
            <p className="text-sm font-medium">{money(request.amounts.total)}</p>
            <p className="text-xs text-muted-foreground">
              {money(request.amounts.subtotal)} + {money(request.amounts.vat)} IVA
            </p>
          </div>
          <div className="rounded-xl border bg-muted/40 p-3">
            <p className="text-xs text-muted-foreground">Estado do pagamento</p>
            <p className="text-sm font-medium">{request.payment.status_label}</p>
            {request.payment.mbway_reference && <p className="text-xs text-muted-foreground">Ref. MB Way: {request.payment.mbway_reference}</p>}
          </div>
        </div>

        {needsPayment ? (
          <div className="space-y-3 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4">
            <p className="text-sm font-medium">Pagar por MB Way</p>
            <p className="text-xs text-muted-foreground">
              Transfira <strong>{money(request.amounts.total)}</strong> por MB Way para{" "}
              <strong>{settings?.mbway_number || request.payment.mbway_number || "—"}</strong>
              {settings?.mbway_holder ? ` (${settings.mbway_holder})` : ""} e escreva <strong>{request.payment.mbway_reference}</strong> nas observações.
            </p>
            {settings?.payment_instructions && <p className="text-xs text-muted-foreground">{settings.payment_instructions}</p>}
            <div className="grid gap-3 sm:grid-cols-[220px_1fr]">
              <div className="space-y-2">
                <Label htmlFor="pay-phone">Telemóvel MB Way</Label>
                <Input
                  id="pay-phone"
                  value={payPhone}
                  onChange={(event) => onPhone(event.target.value)}
                  placeholder="912 345 678"
                  inputMode="tel"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pay-note">Nota (opcional)</Label>
                <Input
                  id="pay-note"
                  value={payNote}
                  onChange={(event) => onNote(event.target.value)}
                  placeholder="Ex.: paguei agora às 15h20"
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={onDeclare} disabled={busy}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Smartphone size={14} />}{" "}
                {settings?.mbway_api ? "Pedir pagamento MB Way" : "Já paguei — informar"}
              </Button>
              {request.payment.provider_request_id && (
                <Button variant="outline" onClick={onCheck} disabled={busy}>
                  <RefreshCw size={14} /> Verificar pagamento
                </Button>
              )}
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <ShieldCheck size={13} /> Só o backoffice confirma o pagamento
              </span>
            </div>
          </div>
        ) : (
          <p className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            <CheckCircle2 size={15} /> {paid ? "Pagamento confirmado" : "Este relatório não precisa de pagamento"}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpen(request)}>
            <FileText size={14} /> Ver pedido
          </Button>
          <Button variant="outline" onClick={onClose}>
            Ver os meus relatórios
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RequestRow({
  request,
  onOpen,
  onDownload,
}: {
  request: ReportsRequest;
  onOpen: () => void;
  onDownload: (request: ReportsRequest, fileId: string, name: string) => void;
}) {
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-3">
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{request.reference}</span>
          <Badge variant={badgeVariant(request.status_style)}>{request.status_label}</Badge>
          {request.amounts.total > 0 && (
            <Badge variant={badgeVariant(request.payment.status_style)}>{request.payment.status_label}</Badge>
          )}
        </div>
        <p className="mt-1 truncate text-sm font-medium">{request.package_title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {request.targets_label} · criado {shortDate(request.created_at)}
        </p>
      </button>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{request.amounts.total > 0 ? money(request.amounts.total) : "Grátis"}</span>
        {request.files.length > 0 && request.files[0] && (
          <Button variant="outline" size="sm" onClick={() => onDownload(request, request.files[0].id, request.files[0].name)}>
            <Download size={13} /> {bytes(request.files[0].size)}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={onOpen}>
          Detalhe
        </Button>
      </div>
    </Card>
  );
}

function RequestDetail({
  request,
  onClose,
  onDownload,
  onCancel,
  onPay,
  canCancel,
  needsPayment,
}: {
  request: ReportsRequest;
  onClose: () => void;
  onDownload: (request: ReportsRequest, fileId: string, name: string) => void;
  onCancel: (request: ReportsRequest) => void;
  onPay: (request: ReportsRequest) => void;
  canCancel: boolean;
  needsPayment: boolean;
}) {
  return (
    <div className="fixed inset-0 z-[130] flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-[560px] flex-col overflow-y-auto border-l bg-card p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-muted-foreground">{request.reference}</p>
            <h2 className="text-lg font-semibold">{request.package_title}</h2>
            <p className="text-xs text-muted-foreground">{request.targets_label}</p>
          </div>
          <Button variant="outline" size="sm" onClick={onClose}>
            <X size={14} />
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge variant={badgeVariant(request.status_style)}>{request.status_label}</Badge>
          {request.amounts.total > 0 && <Badge variant={badgeVariant(request.payment.status_style)}>Pagamento: {request.payment.status_label}</Badge>}
          <Badge variant="outline">{money(request.amounts.total)}</Badge>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{request.status_hint}</p>

        <div className="mt-4 space-y-1">
          {request.flow.map((step) => (
            <div key={step.id} className="flex items-center gap-2 text-xs">
              <span className={`h-2 w-2 rounded-full ${step.done ? "bg-emerald-400" : "bg-muted-foreground/40"}`} />
              <span className={step.done ? "text-foreground" : "text-muted-foreground"}>{step.label}</span>
            </div>
          ))}
        </div>

        {request.files.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Relatórios disponíveis</p>
            {request.files.map((file) => (
              <div key={file.id} className="flex items-center justify-between gap-2 rounded-xl border bg-muted/40 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm">{file.name}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {bytes(file.size)} · {shortDate(file.uploaded_at)}
                  </p>
                </div>
                <Button size="sm" onClick={() => onDownload(request, file.id, file.name)}>
                  <Download size={13} /> Descarregar
                </Button>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Dados do pedido</p>
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-muted-foreground">Criado</dt>
              <dd>{shortDate(request.created_at)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Entrega prevista</dt>
              <dd className="flex items-center gap-1">
                <CalendarClock size={12} /> {request.package_subtitle || "—"}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-muted-foreground">Empresas</dt>
              <dd className="flex items-center gap-1">
                <Building2 size={12} /> {request.targets_label}
              </dd>
            </div>
            {request.notes && (
              <div className="col-span-2">
                <dt className="text-muted-foreground">Notas</dt>
                <dd className="whitespace-pre-wrap">{request.notes}</dd>
              </div>
            )}
          </dl>
        </div>

        {request.history.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Histórico</p>
            <ul className="space-y-1 text-xs">
              {request.history.map((item) => (
                <li key={item.id} className="rounded-lg border bg-muted/30 px-3 py-2">
                  <p>{item.message}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {shortDate(item.at)} · {item.by}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-5 flex flex-wrap gap-2 border-t pt-4">
          {needsPayment && (
            <Button onClick={() => onPay(request)}>
              <Smartphone size={14} /> Pagar / informar pagamento
            </Button>
          )}
          {canCancel && (
            <Button variant="outline" onClick={() => onCancel(request)}>
              <Trash2 size={14} /> Cancelar pedido
            </Button>
          )}
        </div>
      </aside>
    </div>
  );
}
