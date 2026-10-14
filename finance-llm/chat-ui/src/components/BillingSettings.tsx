import { useCallback, useEffect, useState } from "react";
import { Check, CreditCard, Loader2, RefreshCw, Smartphone, Wallet } from "lucide-react";
import { useAuth } from "../auth";

export type BillingPlan = {
  id: string;
  name: string;
  price_monthly: number;
  price_yearly: number;
  modules: string[];
  description: string;
};

export type BillingPayment = {
  id: string;
  plan_id: string;
  interval: string;
  amount: number;
  currency: string;
  method: string;
  status: string;
  created_at: string;
  paid_at?: string | null;
};

export type BillingSubscription = {
  plan_id: string;
  plan: BillingPlan;
  status: string;
  current_period_start: string | null;
  current_period_end: string | null;
  trial_expires_at: string | null;
  is_active: boolean;
  expired: boolean;
  payment_method: string | null;
};

const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))).detail || `Erro ${response.status}`;
    throw new Error(detail);
  }
  return response.json() as T;
}

export function getBillingPlans(): Promise<{ plans: BillingPlan[] }> {
  return request("/api/billing/plans");
}

export function getSubscription(): Promise<{ subscription: BillingSubscription; payments: BillingPayment[] }> {
  return request("/api/billing/subscription");
}

export function subscribePlan(planId: string, interval: string, method: string): Promise<Record<string, unknown>> {
  return request("/api/billing/subscribe", {
    method: "POST",
    body: JSON.stringify({ plan_id: planId, interval, method }),
  });
}

export function requestMbway(paymentId: string, phone: string): Promise<Record<string, unknown>> {
  return request("/api/billing/mbway/request", {
    method: "POST",
    body: JSON.stringify({ payment_id: paymentId, phone }),
  });
}

export function checkMbwayStatus(paymentId: string): Promise<Record<string, unknown>> {
  return request("/api/billing/mbway/status", {
    method: "POST",
    body: JSON.stringify({ payment_id: paymentId }),
  });
}

export function capturePayPal(paymentId: string): Promise<Record<string, unknown>> {
  return request("/api/billing/paypal/capture", {
    method: "POST",
    body: JSON.stringify({ payment_id: paymentId }),
  });
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("pt-PT", { hour12: false });
}

function formatAmount(amount?: number, currency?: string) {
  if (amount === undefined || amount === null) return "—";
  return `${amount.toFixed(2)} ${currency || "EUR"}`;
}

export function BillingSettings() {
  const { user } = useAuth();
  void user;
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [subscription, setSubscription] = useState<BillingSubscription | null>(null);
  const [payments, setPayments] = useState<BillingPayment[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [selectedPlan, setSelectedPlan] = useState("");
  const [interval, setInterval] = useState<"monthly" | "yearly">("monthly");
  const [method, setMethod] = useState("mbway");
  const [phone, setPhone] = useState("");
  const [pendingPaymentId, setPendingPaymentId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      const [plansData, subData] = await Promise.all([getBillingPlans(), getSubscription()]);
      setPlans(plansData.plans);
      setSubscription(subData.subscription);
      setPayments(subData.payments);
      if (subData.subscription.plan_id) setSelectedPlan(subData.subscription.plan_id);
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao carregar billing." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /* Regresso dos gateways: o Stripe volta com `billing=success` e o PayPal com
     `billing=paypal&payment_id=...` (a ordem é capturada aqui). Limpa os
     parâmetros do URL para o aviso não reaparecer num refresh. */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const status = params.get("billing");
    if (!status) return;
    const paymentId = params.get("payment_id") || "";
    const clean = () => {
      const url = new URL(window.location.href);
      ["billing", "payment_id", "token"].forEach((key) => url.searchParams.delete(key));
      window.history.replaceState({}, "", url.toString());
    };
    if (status === "paypal" && paymentId) {
      void (async () => {
        try {
          const result = await capturePayPal(paymentId);
          setMessage({
            kind: result.ok ? "ok" : "error",
            text: result.ok ? "Pagamento PayPal confirmado. Subscrição ativada." : "Não foi possível capturar o pagamento PayPal.",
          });
          await load();
        } catch (error) {
          setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao capturar o PayPal." });
        }
      })();
    } else if (status === "success") {
      setMessage({ kind: "ok", text: "Pagamento recebido. A subscrição é ativada assim que o gateway confirmar." });
      void load();
    } else if (status === "cancel") {
      setMessage({ kind: "error", text: "Pagamento cancelado." });
    }
    clean();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubscribe = async () => {
    if (!selectedPlan) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await subscribePlan(selectedPlan, interval, method);
      if (!result.ok) {
        const notConfigured = result.configured === false;
        setMessage({
          kind: "error",
          text: notConfigured
            ? `${String(result.error)} Um administrador pode configurar a chave em Administração → Chaves e integrações.`
            : String(result.error || "Pagamento não iniciado."),
        });
        setBusy(false);
        return;
      }
      if (method === "mbway") {
        setPendingPaymentId(String(result.payment_id));
        setMessage({ kind: "ok", text: String(result.instructions || "Indique o telemóvel para receber o pedido MB Way.") });
      } else if (method === "stripe") {
        const url = result.checkout_url ? String(result.checkout_url) : "";
        if (url) {
          window.location.href = url;
          return;
        }
        setMessage({ kind: "error", text: "O Stripe não devolveu a página de pagamento." });
      } else if (method === "paypal") {
        const url = result.approval_url ? String(result.approval_url) : "";
        if (url) {
          window.location.href = url;
          return;
        }
        setMessage({ kind: "error", text: "O PayPal não devolveu a página de aprovação." });
      } else if (method === "transfer") {
        setMessage({
          kind: "ok",
          text: String(result.instructions || "Transferência registada. O acesso é ativado após confirmação."),
        });
      }
      await load();
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao subscrever." });
    } finally {
      setBusy(false);
    }
  };

  const handleMbwayRequest = async () => {
    if (!pendingPaymentId || !phone) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await requestMbway(pendingPaymentId, phone);
      setMessage({
        kind: result.ok ? "ok" : "error",
        text: String(result.message || (result.ok ? "Pedido MB Way enviado." : "Erro MB Way.")),
      });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro MB Way." });
    } finally {
      setBusy(false);
    }
  };

  const handleMbwayCheck = async () => {
    if (!pendingPaymentId) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await checkMbwayStatus(pendingPaymentId);
      if (result.paid || result.status === "pago") {
        setMessage({ kind: "ok", text: "Pagamento confirmado. Subscrição ativada." });
        setPendingPaymentId(null);
        await load();
      } else {
        setMessage({ kind: "error", text: String(result.status_label || "Ainda não confirmado.") });
      }
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao verificar MB Way." });
    } finally {
      setBusy(false);
    }
  };

  const currentPlan = plans.find((p) => p.id === (subscription?.plan_id || selectedPlan));

  return (
    <section className="glass-card rounded-2xl p-5">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <CreditCard size={15} className="text-teal-300" /> Billing / Subscrição
        </h2>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1 text-[11px] transition hover:bg-white/5 disabled:opacity-40"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Atualizar
        </button>
      </header>

      {message && (
        <p
          className={[
            "mb-4 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs",
            message.kind === "ok"
              ? "border-teal-300/30 bg-teal-400/10 text-teal-200"
              : "border-rose-400/25 bg-rose-500/10 text-rose-200",
          ].join(" ")}
        >
          {message.kind === "ok" ? <Check size={14} className="mt-0.5 shrink-0" /> : null}
          {message.text}
        </p>
      )}

      {subscription && (
        <div className="mb-5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Subscrição atual</p>
          <p className="mt-1 text-lg font-semibold text-teal-300">{subscription.plan.name}</p>
          <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
            <span>Estado: <strong className="text-foreground">{subscription.is_active ? "Ativa" : subscription.expired ? "Expirada" : "Inativa"}</strong></span>
            <span>Válida até: <strong className="text-foreground">{formatDate(subscription.current_period_end)}</strong></span>
            {subscription.trial_expires_at && (
              <span>Trial até: <strong className="text-foreground">{formatDate(subscription.trial_expires_at)}</strong></span>
            )}
          </div>
        </div>
      )}

      <p className="mb-2 text-xs text-muted-foreground">Escolha um plano e o método de pagamento.</p>

      <div className="mb-3 grid gap-2">
        {plans.map((plan) => (
          <label
            key={plan.id}
            className={[
              "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition",
              selectedPlan === plan.id
                ? "border-teal-400/40 bg-teal-400/10"
                : "border-white/10 bg-white/[0.03] hover:bg-white/[0.05]",
            ].join(" ")}
          >
            <input
              type="radio"
              name="plan"
              value={plan.id}
              checked={selectedPlan === plan.id}
              onChange={() => setSelectedPlan(plan.id)}
              className="mt-1 accent-teal-400"
            />
            <div className="flex-1">
              <p className="text-sm font-medium">{plan.name}</p>
              <p className="text-[11px] text-muted-foreground">{plan.description}</p>
              <p className="mt-1 text-xs text-teal-300">
                {interval === "yearly"
                  ? `${plan.price_yearly.toFixed(2)} €/ano`
                  : `${plan.price_monthly.toFixed(2)} €/mês`}
              </p>
              <p className="mt-1 text-[10px] text-muted-foreground">Módulos: {plan.modules.join(", ")}</p>
            </div>
          </label>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {[
          { value: "monthly", label: "Mensal" },
          { value: "yearly", label: "Anual" },
        ].map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => setInterval(opt.value as "monthly" | "yearly")}
            className={[
              "rounded-lg border px-3 py-1 text-[11px] transition",
              interval === opt.value
                ? "border-teal-400/40 bg-teal-400/15 text-teal-200"
                : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.06]",
            ].join(" ")}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { id: "mbway", label: "MB Way", icon: Smartphone },
          { id: "transfer", label: "Transferência", icon: Wallet },
          { id: "stripe", label: "Cartão (Stripe)", icon: CreditCard },
          { id: "paypal", label: "PayPal", icon: CreditCard },
        ].map((m) => {
          const Icon = m.icon;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setMethod(m.id)}
              className={[
                "flex items-center justify-center gap-2 rounded-lg border px-2 py-2 text-[11px] transition",
                method === m.id
                  ? "border-teal-400/40 bg-teal-400/15 text-teal-200"
                  : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.06]",
              ].join(" ")}
            >
              <Icon size={13} /> {m.label}
            </button>
          );
        })}
      </div>

      {method === "mbway" && pendingPaymentId && (
        <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <label className="block text-[11px] uppercase tracking-wide text-muted-foreground">Telemóvel MB Way</label>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="912345678"
            className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-sm outline-none"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void handleMbwayRequest()}
              disabled={busy || !phone}
              className="rounded-lg bg-teal-400/15 px-3 py-1.5 text-xs text-teal-200 transition hover:bg-teal-400/25 disabled:opacity-40"
            >
              Enviar pedido
            </button>
            <button
              type="button"
              onClick={() => void handleMbwayCheck()}
              disabled={busy}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-40"
            >
              Verificar pagamento
            </button>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => void handleSubscribe()}
        disabled={busy || !selectedPlan}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 disabled:opacity-60"
      >
        {busy ? <Loader2 size={15} className="animate-spin" /> : <CreditCard size={15} />}
        {busy ? "A processar…" : `Pagar ${currentPlan ? formatAmount(interval === "yearly" ? currentPlan.price_yearly : currentPlan.price_monthly) : ""}`}
      </button>

      {payments.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">Histórico de pagamentos</p>
          <ul className="space-y-1">
            {payments.map((payment) => (
              <li
                key={payment.id}
                className="flex items-center justify-between rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-[11px]"
              >
                <span>
                  {payment.plan_id} · {payment.method} · {formatAmount(payment.amount, payment.currency)}
                </span>
                <span
                  className={[
                    "rounded-full px-2 py-0.5 text-[10px]",
                    payment.status === "paid"
                      ? "bg-teal-400/15 text-teal-200"
                      : "bg-amber-400/15 text-amber-200",
                  ].join(" ")}
                >
                  {payment.status === "paid" ? "pago" : "pendente"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
