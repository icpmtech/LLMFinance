import { CreditCard, Mail, Sparkles, XCircle } from "lucide-react";

export function TrialExpiredPage() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-background text-foreground">
      <div className="orbit-bg pointer-events-none absolute inset-0 opacity-80" aria-hidden="true" />
      <div className="relative mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center px-4 py-10 text-center">
        <span className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-rose-400 via-rose-500 to-orange-600 text-white shadow-lg shadow-rose-500/25">
          <Sparkles size={28} />
        </span>

        <h1 className="mt-8 text-2xl font-semibold leading-tight sm:text-3xl">Trial expirado</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          O período de trial de 5 dias terminou. Para continuar a usar o IQ OS, é necessário efetuar o pagamento.
        </p>

        <div className="mt-8 grid gap-3 text-left">
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-rose-400/15 text-rose-300">
              <XCircle size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Acesso desativado</span>
              <span className="block text-xs text-muted-foreground">
                A conta foi suspensa automaticamente após o fim do trial de 5 dias.
              </span>
            </span>
          </div>
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-teal-400/15 text-teal-300">
              <CreditCard size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Reativação por pagamento</span>
              <span className="block text-xs text-muted-foreground">
                Efetue o pagamento para reativar o acesso. Contacte o administrador se precisar de ajuda.
              </span>
            </span>
          </div>
          <div className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-violet-400/15 text-violet-300">
              <Mail size={16} />
            </span>
            <span>
              <span className="block text-sm font-medium">Email enviado</span>
              <span className="block text-xs text-muted-foreground">
                Foi enviado um lembrete para o email associado à conta com as instruções de pagamento.
              </span>
            </span>
          </div>
        </div>

        <p className="mt-8 text-xs text-muted-foreground">
          Em caso de dúvidas, contacte a equipa de suporte.
        </p>
      </div>
    </div>
  );
}

export default TrialExpiredPage;
