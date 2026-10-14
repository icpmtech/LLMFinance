import { Clock, Mail, ShieldCheck, Sparkles } from "lucide-react";

export function PendingApprovalPage() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-background text-foreground">
      <div className="orbit-bg pointer-events-none absolute inset-0 opacity-80" aria-hidden="true" />
      <div className="relative mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center px-4 py-10 text-center">
        <span className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 via-teal-500 to-blue-600 text-white shadow-lg shadow-teal-500/25">
          <Sparkles size={28} />
        </span>

        <h1 className="mt-8 text-2xl font-semibold leading-tight sm:text-3xl">Conta criada com sucesso</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          O registo foi recebido. Antes de aceder à plataforma, um administrador tem de aprovar o email.
        </p>

        <div className="mt-8 grid gap-3 text-left">
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-amber-400/15 text-amber-300">
              <Clock size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Pendente de aprovação</span>
              <span className="block text-xs text-muted-foreground">
                Um administrador vai validar o registo e aprovar o acesso.
              </span>
            </span>
          </div>
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-teal-400/15 text-teal-300">
              <Mail size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Email de confirmação</span>
              <span className="block text-xs text-muted-foreground">
                Assim que aprovada, receberá um email com o início do trial de 5 dias.
              </span>
            </span>
          </div>
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-violet-400/15 text-violet-300">
              <ShieldCheck size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Acesso controlado</span>
              <span className="block text-xs text-muted-foreground">
                Passado o trial de 5 dias, será necessário efetuar o pagamento para manter o acesso.
              </span>
            </span>
          </div>
        </div>

        <p className="mt-8 text-xs text-muted-foreground">
          Pode fechar esta página. Voltaremos a contactá-lo por email.
        </p>
      </div>
    </div>
  );
}

export default PendingApprovalPage;
