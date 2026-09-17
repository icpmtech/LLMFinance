/**
 * Página de entrada: iniciar sessão e criar conta.
 *
 * As contas vivem no Elasticsearch (`finance_users`) e as sessões em
 * `finance_sessions`, pelo que o registo é imediato e o login abre uma sessão
 * real (revogável a partir das definições, noutro dispositivo).
 */
import { useState } from "react";
import {
  AlertCircle,
  Building2,
  Check,
  Eye,
  EyeOff,
  Loader2,
  Lock,
  LogIn,
  Mail,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  User,
  UserPlus,
} from "lucide-react";
import { useAuth } from "../auth";

type Mode = "login" | "register";

const HIGHLIGHTS = [
  { icon: TrendingUp, title: "Mercados e previsões", text: "Cotações, sentimento, ARIMA e Kronos." },
  { icon: Building2, title: "Contratos e empresas", text: "Mais de 2 milhões de contratos públicos." },
  { icon: ShieldCheck, title: "Conta segura", text: "Sessões auditáveis e terminação remota." },
];

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [organization, setOrganization] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const passwordIssues = [
    { ok: password.length >= 8, label: "8 caracteres" },
    { ok: /[A-Za-zÀ-ÿ]/.test(password), label: "uma letra" },
    { ok: /\d/.test(password), label: "um dígito" },
  ];
  const passwordStrong = passwordIssues.every((item) => item.ok);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError(null);

    if (mode === "register") {
      if (name.trim().length < 2) return setError("Indique o seu nome completo.");
      if (!passwordStrong) return setError("A palavra-passe ainda não cumpre os requisitos indicados.");
    }
    if (!email.trim() || !password) return setError("Preencha o email e a palavra-passe.");

    setBusy(true);
    try {
      if (mode === "login") {
        await login(email.trim(), password, remember);
      } else {
        await register({
          name: name.trim(),
          email: email.trim(),
          password,
          title: title.trim() || undefined,
          organization: organization.trim() || undefined,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível concluir o pedido.");
      setBusy(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-background text-foreground">
      <div className="orbit-bg pointer-events-none absolute inset-0 opacity-80" aria-hidden="true" />
      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col items-center justify-center gap-8 px-4 py-10 lg:flex-row lg:items-stretch lg:gap-12">
        {/* Apresentação */}
        <section className="flex w-full max-w-lg flex-col justify-center lg:w-1/2">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 via-teal-500 to-blue-600 text-white shadow-lg shadow-teal-500/25">
              <Sparkles size={20} />
            </span>
            <div>
              <p className="text-lg font-semibold leading-tight">IQ OS</p>
              <p className="text-xs text-muted-foreground">Plataforma de inteligência financeira</p>
            </div>
          </div>

          <h1 className="mt-8 text-3xl font-semibold leading-tight sm:text-4xl">
            Toda a informação de mercados e contratação pública,
            <span className="text-glow-teal text-teal-300"> com IA a ajudar a decidir.</span>
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            Entre com a sua conta para aceder aos dados, guardar pastas de análise e manter as preferências
            sincronizadas entre dispositivos.
          </p>

          <ul className="mt-8 space-y-3">
            {HIGHLIGHTS.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.title} className="glass-card flex items-start gap-3 rounded-2xl px-4 py-3">
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-teal-400/15 text-teal-300">
                    <Icon size={16} />
                  </span>
                  <span>
                    <span className="block text-sm font-medium">{item.title}</span>
                    <span className="block text-xs text-muted-foreground">{item.text}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        {/* Formulário */}
        <section className="w-full max-w-md self-center">
          <div className="glass-modal gradient-border rounded-3xl p-6 sm:p-7">
            <div className="flex gap-1 rounded-xl bg-white/5 p-1" role="tablist" aria-label="Entrar ou criar conta">
              {(["login", "register"] as Mode[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={mode === item}
                  onClick={() => switchMode(item)}
                  className={[
                    "flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
                    mode === item ? "bg-teal-400/20 text-teal-200" : "text-muted-foreground hover:bg-white/5",
                  ].join(" ")}
                >
                  {item === "login" ? <LogIn size={15} /> : <UserPlus size={15} />}
                  {item === "login" ? "Entrar" : "Criar conta"}
                </button>
              ))}
            </div>

            <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
              {mode === "register" && (
                <Field label="Nome completo" icon={<User size={15} />}>
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    autoComplete="name"
                    placeholder="Ana Ribeiro"
                    className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  />
                </Field>
              )}

              <Field label="Email" icon={<Mail size={15} />}>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  placeholder="nome@empresa.pt"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                />
              </Field>

              <Field label="Palavra-passe" icon={<Lock size={15} />}>
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  placeholder="••••••••"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "Ocultar palavra-passe" : "Mostrar palavra-passe"}
                  className="rounded-lg p-1 text-muted-foreground transition hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </Field>

              {mode === "register" && (
                <>
                  <div className="flex flex-wrap gap-2">
                    {passwordIssues.map((item) => (
                      <span
                        key={item.label}
                        className={[
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                          item.ok
                            ? "border-teal-300/30 bg-teal-400/10 text-teal-200"
                            : "border-white/10 bg-white/5 text-muted-foreground",
                        ].join(" ")}
                      >
                        {item.ok ? <Check size={11} /> : null}
                        {item.label}
                      </span>
                    ))}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Cargo (opcional)" icon={<User size={15} />}>
                      <input
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="Analista"
                        className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                      />
                    </Field>
                    <Field label="Organização (opcional)" icon={<Building2 size={15} />}>
                      <input
                        value={organization}
                        onChange={(event) => setOrganization(event.target.value)}
                        placeholder="Empresa"
                        className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                      />
                    </Field>
                  </div>
                </>
              )}

              {mode === "login" && (
                <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                    className="h-4 w-4 rounded border-white/20 bg-white/5 accent-teal-400"
                  />
                  Manter sessão iniciada durante 30 dias
                </label>
              )}

              {error && (
                <p
                  role="alert"
                  className="flex items-start gap-2 rounded-xl border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
                >
                  <AlertCircle size={14} className="mt-0.5 shrink-0" />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={busy}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : mode === "login" ? <LogIn size={15} /> : <UserPlus size={15} />}
                {busy ? "A processar…" : mode === "login" ? "Entrar" : "Criar conta"}
              </button>
            </form>

            <p className="mt-4 text-center text-[11px] leading-relaxed text-muted-foreground">
              {mode === "login" ? (
                <>
                  Ainda não tem conta?{" "}
                  <button
                    type="button"
                    onClick={() => switchMode("register")}
                    className="text-teal-300 underline-offset-2 hover:underline"
                  >
                    Crie uma agora
                  </button>
                </>
              ) : (
                <>
                  Já tem conta?{" "}
                  <button
                    type="button"
                    onClick={() => switchMode("login")}
                    className="text-teal-300 underline-offset-2 hover:underline"
                  >
                    Inicie sessão
                  </button>
                </>
              )}
              <span className="mt-2 block">
                As contas e as sessões são guardadas no Elasticsearch. A palavra-passe é derivada com scrypt e nunca é
                guardada em texto simples.
              </span>
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

function Field({
  label,
  icon,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 transition focus-within:border-teal-300/40 focus-within:bg-white/[0.06]">
        <span className="text-muted-foreground">{icon}</span>
        {children}
      </span>
    </label>
  );
}

export default LoginPage;
