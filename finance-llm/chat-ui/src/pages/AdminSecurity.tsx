/**
 * Administração · **Segurança** (verificação em dois passos no login).
 *
 * O login em duas etapas é opcional e decidido aqui:
 *
 * - **desligado** — só entra quem ativar a verificação na própria conta;
 * - **apenas administradores** — contas `admin` são sempre desafiadas;
 * - **todas as contas** — ninguém entra apenas com a palavra-passe.
 *
 * O código de 6 dígitos é gerado no servidor e enviado por email (SMTP
 * configurado em «Chaves»), com validade própria, limite de tentativas e
 * intervalo mínimo entre reenvios. Se o email não estiver configurado, a
 * política ativa trancaria o acesso — por isso o aviso aparece aqui antes de
 * guardar.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, MailCheck, RefreshCw, Save, ShieldCheck } from "lucide-react";

import { getAdminMfaPolicy, saveAdminMfaPolicy, type MfaPolicy, type MfaPolicyPatch } from "../adminApi";

function NumberField({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={Number.isFinite(value) ? value : min}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] outline-none focus:border-teal-400/40"
      />
      <span className="mt-1 block text-[10.5px] text-muted-foreground">
        {hint} ({min}–{max})
      </span>
    </label>
  );
}

export function AdminSecurityTab({ onError }: { onError: (message: string | null) => void }) {
  const [state, setState] = useState<MfaPolicy | null>(null);
  const [form, setForm] = useState<MfaPolicyPatch | null>(null);
  const [busy, setBusy] = useState<"load" | "save" | null>("load");
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((next: MfaPolicy) => {
    setState(next);
    setForm({
      policy: next.policy,
      code_ttl_seconds: next.code_ttl_seconds,
      max_attempts: next.max_attempts,
      resend_cooldown_seconds: next.resend_cooldown_seconds,
    });
  }, []);

  const load = useCallback(async () => {
    setBusy("load");
    try {
      const result = await getAdminMfaPolicy();
      apply(result);
      onError(result.error || null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao carregar a política de verificação em dois passos.");
    } finally {
      setBusy(null);
    }
  }, [apply, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!form) return;
    setBusy("save");
    setNotice(null);
    try {
      const result = await saveAdminMfaPolicy(form);
      apply(result);
      setNotice("Política guardada. Aplica-se ao próximo início de sessão.");
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao guardar a política.");
    } finally {
      setBusy(null);
    }
  };

  const dirty = Boolean(
    form &&
      state &&
      (form.policy !== state.policy ||
        form.code_ttl_seconds !== state.code_ttl_seconds ||
        form.max_attempts !== state.max_attempts ||
        form.resend_cooldown_seconds !== state.resend_cooldown_seconds),
  );

  if (!form || !state) {
    return (
      <div className="flex items-center gap-2 p-4 text-[12px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar a política de verificação em dois passos…
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <header className="flex flex-wrap items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-teal-400/15 text-teal-200">
            <ShieldCheck size={13} />
          </span>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold">Verificação em dois passos (MFA)</p>
            <p className="text-[11px] text-muted-foreground">
              Depois da palavra-passe, o utilizador introduz um código de 6 dígitos enviado por email.
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void load()}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] transition hover:bg-white/[0.09]"
            >
              <RefreshCw size={12} className={busy === "load" ? "animate-spin" : ""} /> Atualizar
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy === "save" || !dirty}
              className="flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/10 px-2.5 py-1 text-[11.5px] text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
            >
              {busy === "save" ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Guardar
            </button>
          </div>
        </header>

        {notice && (
          <p className="mt-2 flex items-center gap-1.5 rounded-lg border border-teal-400/20 bg-teal-400/10 px-2.5 py-1.5 text-[11.5px] text-teal-200">
            <CheckCircle2 size={12} /> {notice}
          </p>
        )}

        {state.warning && (
          <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-400/25 bg-amber-400/10 px-2.5 py-1.5 text-[11.5px] text-amber-100">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {state.warning}
          </p>
        )}

        <div className="mt-3 grid gap-3 @xl:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wide text-muted-foreground">Quem é desafiado</span>
            <select
              value={form.policy}
              onChange={(event) => setForm({ ...form, policy: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] outline-none focus:border-teal-400/40"
            >
              {state.policies.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[10.5px] text-muted-foreground">
              Cada utilizador pode ainda ativar a verificação na própria conta, nas definições.
            </span>
          </label>

          <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2">
            <MailCheck size={14} className={state.email_configured ? "text-teal-300" : "text-amber-300"} />
            <div className="min-w-0">
              <p className="text-[11.5px] font-medium">Envio por email</p>
              <p className="text-[10.5px] text-muted-foreground">
                {state.email_configured ? "SMTP configurado." : "SMTP por configurar — ver «Chaves»."}
              </p>
            </div>
          </div>

          <NumberField
            label="Validade do código (segundos)"
            hint="Tempo que o código recebido continua válido"
            value={form.code_ttl_seconds}
            min={state.limits.code_ttl_seconds[0]}
            max={state.limits.code_ttl_seconds[1]}
            onChange={(value) => setForm({ ...form, code_ttl_seconds: value })}
          />
          <NumberField
            label="Tentativas por código"
            hint="Após este número de erros o código é anulado"
            value={form.max_attempts}
            min={state.limits.max_attempts[0]}
            max={state.limits.max_attempts[1]}
            onChange={(value) => setForm({ ...form, max_attempts: value })}
          />
          <NumberField
            label="Intervalo entre reenvios (segundos)"
            hint="Tempo mínimo antes de poder pedir outro código"
            value={form.resend_cooldown_seconds}
            min={state.limits.resend_cooldown_seconds[0]}
            max={state.limits.resend_cooldown_seconds[1]}
            onChange={(value) => setForm({ ...form, resend_cooldown_seconds: value })}
          />
        </div>

        <p className="mt-3 text-[10.5px] leading-relaxed text-muted-foreground">
          Estado atual: <span className="text-foreground">{state.label}</span>
          {state.updated_at ? ` · atualizado em ${state.updated_at}` : ""}
          {state.updated_by ? ` por ${state.updated_by}` : ""}.
        </p>
      </section>

      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <p className="text-[12px] font-medium">Como funciona</p>
        <ul className="mt-1.5 space-y-1 text-[11.5px] leading-relaxed text-muted-foreground">
          <li>· O código de 6 dígitos é gerado no servidor e nunca é guardado em claro (só o HMAC).</li>
          <li>· Cada código serve uma única vez e expira ao fim do prazo configurado.</li>
          <li>
            · Repetir o login até 60 s depois reutiliza o mesmo código (evita ficar com um email inválido à frente);
            passado esse intervalo, um login novo gera outro e anula o anterior.
          </li>
          <li>· As tentativas erradas ficam registadas nos eventos e o número de pedidos por conta é limitado.</li>
          <li>· «Apenas administradores» protege as contas com mais privilégios sem incomodar os restantes utilizadores.</li>
        </ul>
      </section>
    </div>
  );
}
