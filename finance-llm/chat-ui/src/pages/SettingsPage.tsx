/**
 * Definições da conta: perfil, preferências, segurança e sessões.
 *
 * Tudo o que aparece aqui são dados reais: o perfil e as preferências vivem no
 * documento do utilizador (`finance_users`) e a lista de sessões vem de
 * `finance_sessions`. Alterar a palavra-passe revoga as outras sessões.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ProvidersSettings } from "../components/ProvidersSettings";
import { InstallAppSettings } from "../components/InstallAppSettings";
import {
  AlertCircle,
  AppWindow,
  Building2,
  CalendarClock,
  Check,
  CheckCircle2,
  Clock,
  Globe2,
  KeyRound,
  LayoutDashboard,
  Loader2,
  LogOut,
  Mail,
  MonitorSmartphone,
  Palette,
  PanelLeftClose,
  Phone,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { useAuth } from "../auth";
import type { AuthSession, AuthUser } from "../authApi";
import { updateDockPrefs } from "../dock";
import { setSidebarHidden, useWindowMode } from "../layout";

const VIEW_OPTIONS: { value: string; label: string }[] = [
  { value: "dashboard", label: "Dashboard" },
  { value: "chat", label: "Chat IA" },
  { value: "empresas-iq", label: "EmpresasIQ" },
  { value: "search", label: "Pesquisa Global" },
  { value: "contracts-search", label: "Contratos públicos" },
  { value: "contracts-dashboard", label: "Dashboard de contratos" },
  { value: "entities-search", label: "Empresas" },
  { value: "tickers", label: "Mercados" },
  { value: "forecast", label: "Previsões" },
  { value: "trading", label: "Trading simulado" },
  { value: "rag", label: "RAG Documentos" },
];

const LOCALES = ["pt-PT", "pt-BR", "en-GB", "en-US", "es-ES", "fr-FR"];
const TIMEZONES = ["Europe/Lisbon", "Europe/Madrid", "Europe/London", "Europe/Paris", "America/Sao_Paulo", "UTC"];

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-PT", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function describeAgent(agent: string) {
  if (!agent) return "Cliente desconhecido";
  const browser =
    /Edg\//.test(agent) ? "Edge" : /OPR\//.test(agent) ? "Opera" : /Chrome\//.test(agent) ? "Chrome" : /Firefox\//.test(agent) ? "Firefox" : /Safari\//.test(agent) ? "Safari" : "Browser";
  const system = /Windows/.test(agent) ? "Windows" : /Mac OS X/.test(agent) ? "macOS" : /Android/.test(agent) ? "Android" : /iPhone|iPad/.test(agent) ? "iOS" : /Linux/.test(agent) ? "Linux" : "";
  return system ? `${browser} · ${system}` : browser;
}

export default function SettingsPage() {
  const { user, updateProfile, changePassword, logoutEverywhere, deleteAccount, sessions, revokeSession, logout } = useAuth();

  const [profile, setProfile] = useState({ name: "", title: "", organization: "", phone: "", locale: "pt-PT", timezone: "Europe/Lisbon" });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMessage, setProfileMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const [passwords, setPasswords] = useState({ current: "", next: "", confirm: "" });
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const [sessionList, setSessionList] = useState<AuthSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [dangerMessage, setDangerMessage] = useState<string | null>(null);

  const preferences = (user?.preferences || {}) as Record<string, unknown>;
  const { windowMode, setWindowMode } = useWindowMode();

  useEffect(() => {
    if (!user) return;
    setProfile({
      name: user.name,
      title: user.title,
      organization: user.organization,
      phone: user.phone,
      locale: user.locale,
      timezone: user.timezone,
    });
  }, [user]);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError(null);
    try {
      setSessionList(await sessions());
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "Não foi possível carregar as sessões.");
    } finally {
      setSessionsLoading(false);
    }
  }, [sessions]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const profileDirty = useMemo(() => {
    if (!user) return false;
    return (
      profile.name !== user.name ||
      profile.title !== user.title ||
      profile.organization !== user.organization ||
      profile.phone !== user.phone ||
      profile.locale !== user.locale ||
      profile.timezone !== user.timezone
    );
  }, [profile, user]);

  const saveProfile = async () => {
    setSavingProfile(true);
    setProfileMessage(null);
    try {
      await updateProfile(profile);
      setProfileMessage({ kind: "ok", text: "Perfil atualizado e guardado no Elasticsearch." });
    } catch (error) {
      setProfileMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao guardar." });
    } finally {
      setSavingProfile(false);
    }
  };

  const savePreference = async (patch: Record<string, unknown>) => {
    setProfileMessage(null);
    try {
      await updateProfile({ preferences: patch });
      if ("sidebar_hidden" in patch) setSidebarHidden(Boolean(patch.sidebar_hidden));
      if ("dock_position" in patch) {
        updateDockPrefs({ position: patch.dock_position as "bottom" | "left" | "right" });
      }
      if (typeof patch.window_mode === "boolean") setWindowMode(patch.window_mode);
    } catch (error) {
      setProfileMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao guardar preferência." });
    }
  };

  const submitPassword = async () => {
    setPasswordMessage(null);
    if (passwords.next !== passwords.confirm) {
      setPasswordMessage({ kind: "error", text: "A confirmação não corresponde à nova palavra-passe." });
      return;
    }
    setSavingPassword(true);
    try {
      const message = await changePassword(passwords.current, passwords.next);
      setPasswords({ current: "", next: "", confirm: "" });
      setPasswordMessage({ kind: "ok", text: message });
      void loadSessions();
    } catch (error) {
      setPasswordMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro ao alterar." });
    } finally {
      setSavingPassword(false);
    }
  };

  const terminateOthers = async () => {
    setSessionsError(null);
    try {
      await logoutEverywhere();
      void loadSessions();
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "Erro ao terminar sessões.");
    }
  };

  const removeSession = async (id: string) => {
    setSessionsError(null);
    try {
      await revokeSession(id);
      setSessionList((previous) => previous.filter((item) => item.id !== id));
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : "Erro ao terminar a sessão.");
    }
  };

  const confirmDelete = async () => {
    setDangerMessage(null);
    if (deleteConfirm !== "APAGAR") {
      setDangerMessage("Escreva APAGAR para confirmar.");
      return;
    }
    setDeleting(true);
    try {
      await deleteAccount(deletePassword);
    } catch (error) {
      setDangerMessage(error instanceof Error ? error.message : "Erro ao apagar a conta.");
      setDeleting(false);
    }
  };

  if (!user) return null;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Sparkles size={13} className="text-teal-300" /> Conta
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Definições</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Perfil, preferências e segurança — tudo guardado na sua conta.
          </p>
        </div>
        <div className="flex items-center gap-3 rounded-2xl glass-card px-4 py-3">
          <Avatar user={user} size={44} />
          <div className="leading-tight">
            <p className="text-sm font-medium">{user.name}</p>
            <p className="text-xs text-muted-foreground">{user.email}</p>
            <p className="mt-0.5 text-[11px] text-teal-300">
              {user.role === "admin" ? "Administrador" : "Membro"} · {user.login_count} início(s) de sessão
            </p>
          </div>
        </div>
      </header>

      {profileMessage && <Banner kind={profileMessage.kind} text={profileMessage.text} />}

      {/* Perfil */}
      <Card
        title="Perfil"
        icon={<User size={15} className="text-teal-300" />}
        action={
          <button
            type="button"
            onClick={saveProfile}
            disabled={!profileDirty || savingProfile}
            className="flex items-center gap-2 rounded-xl bg-teal-400/15 px-3 py-1.5 text-xs font-medium text-teal-200 transition hover:bg-teal-400/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60 disabled:opacity-40"
          >
            {savingProfile ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            Guardar
          </button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Nome completo" value={profile.name} onChange={(value) => setProfile((p) => ({ ...p, name: value }))} icon={<User size={14} />} />
          <TextInput label="Cargo" value={profile.title} onChange={(value) => setProfile((p) => ({ ...p, title: value }))} icon={<Sparkles size={14} />} placeholder="Ex.: Analista de risco" />
          <TextInput label="Organização" value={profile.organization} onChange={(value) => setProfile((p) => ({ ...p, organization: value }))} icon={<Building2 size={14} />} placeholder="Ex.: IQ OS" />
          <TextInput label="Telefone" value={profile.phone} onChange={(value) => setProfile((p) => ({ ...p, phone: value }))} icon={<Phone size={14} />} placeholder="+351 …" />
          <SelectInput
            label="Idioma"
            value={profile.locale}
            options={LOCALES.map((value) => ({ value, label: value }))}
            onChange={(value) => setProfile((p) => ({ ...p, locale: value }))}
            icon={<Globe2 size={14} />}
          />
          <SelectInput
            label="Fuso horário"
            value={profile.timezone}
            options={TIMEZONES.map((value) => ({ value, label: value }))}
            onChange={(value) => setProfile((p) => ({ ...p, timezone: value }))}
            icon={<Clock size={14} />}
          />
          <ReadOnlyInput label="Email (identificador da conta)" value={user.email} icon={<Mail size={14} />} />
          <ReadOnlyInput label="Identificador" value={user.id} icon={<KeyRound size={14} />} />
        </div>
      </Card>

      {/* Preferências */}
      <Card title="Preferências" icon={<Palette size={15} className="text-teal-300" />}>
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectInput
            label="Vista inicial ao entrar"
            value={String(preferences.default_view ?? "dashboard")}
            options={VIEW_OPTIONS}
            onChange={(value) => void savePreference({ default_view: value })}
            icon={<LayoutDashboard size={14} />}
          />
          <SelectInput
            label="Posição do dock"
            value={String(preferences.dock_position ?? "bottom")}
            options={[
              { value: "bottom", label: "Em baixo" },
              { value: "left", label: "À esquerda" },
              { value: "right", label: "À direita" },
            ]}
            onChange={(value) => void savePreference({ dock_position: value })}
            icon={<MonitorSmartphone size={14} />}
          />
        </div>
        <div className="mt-4 space-y-3">
          <ToggleRow
            label="Modo janelas"
            hint="Cada página abre numa janela flutuante (mover, redimensionar, minimizar, encaixar) em vez de ocupar todo o ecrã."
            icon={<AppWindow size={14} />}
            checked={windowMode}
            onChange={(value) => void savePreference({ window_mode: value })}
          />
          <ToggleRow
            label="Esconder a barra lateral"
            hint="Pode alternar a qualquer momento com Ctrl+B ou pela pega lateral."
            icon={<PanelLeftClose size={14} />}
            checked={Boolean(preferences.sidebar_hidden)}
            onChange={(value) => void savePreference({ sidebar_hidden: value })}
          />
          <ToggleRow
            label="Reduzir animações"
            hint="Desativa transições e animações em toda a plataforma."
            icon={<Sparkles size={14} />}
            checked={Boolean(preferences.reduced_motion)}
            onChange={(value) => void savePreference({ reduced_motion: value })}
          />
        </div>
      </Card>

      {/* Segurança */}
      <Card
        title="Segurança"
        icon={<ShieldCheck size={15} className="text-teal-300" />}
        action={
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <CalendarClock size={12} /> Palavra-passe alterada: {formatDate(user.password_updated_at)}
          </span>
        }
      >
        {passwordMessage && <Banner kind={passwordMessage.kind} text={passwordMessage.text} />}
        <div className="grid gap-4 sm:grid-cols-3">
          <PasswordInput label="Palavra-passe atual" value={passwords.current} onChange={(value) => setPasswords((p) => ({ ...p, current: value }))} />
          <PasswordInput label="Nova palavra-passe" value={passwords.next} onChange={(value) => setPasswords((p) => ({ ...p, next: value }))} />
          <PasswordInput label="Confirmar nova" value={passwords.confirm} onChange={(value) => setPasswords((p) => ({ ...p, confirm: value }))} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={submitPassword}
            disabled={savingPassword || !passwords.current || !passwords.next}
            className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs font-medium transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60 disabled:opacity-40"
          >
            {savingPassword ? <Loader2 size={13} className="animate-spin" /> : <KeyRound size={13} />}
            Alterar palavra-passe
          </button>
          <p className="text-[11px] text-muted-foreground">
            Mínimo de 8 caracteres, com letras e dígitos. As outras sessões são terminadas.
          </p>
        </div>
      </Card>

      {/* Sessões */}
      <Card
        title="Sessões ativas"
        icon={<MonitorSmartphone size={15} className="text-teal-300" />}
        action={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void loadSessions()}
              aria-label="Atualizar sessões"
              className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-white/5 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
            >
              <RefreshCw size={13} className={sessionsLoading ? "animate-spin" : ""} />
            </button>
            <button
              type="button"
              onClick={() => void terminateOthers()}
              className="flex items-center gap-1.5 rounded-xl border border-white/10 px-2.5 py-1.5 text-[11px] transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
            >
              <LogOut size={12} /> Terminar as outras
            </button>
          </div>
        }
      >
        {sessionsError && <Banner kind="error" text={sessionsError} />}
        {sessionsLoading && sessionList.length === 0 ? (
          <p className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> A carregar sessões…
          </p>
        ) : sessionList.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">Sem sessões ativas registadas.</p>
        ) : (
          <ul className="divide-y divide-white/5">
            {sessionList.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm">
                    {describeAgent(item.user_agent)}
                    {item.current && (
                      <span className="rounded-full border border-teal-300/30 bg-teal-400/10 px-2 py-0.5 text-[10px] text-teal-200">
                        Sessão atual
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    Início {formatDate(item.created_at)} · última atividade {formatDate(item.last_seen_at)} · expira{" "}
                    {formatDate(item.expires_at)}
                    {item.ip ? ` · ${item.ip}` : ""}
                  </p>
                </div>
                {!item.current && (
                  <button
                    type="button"
                    onClick={() => void removeSession(item.id)}
                    className="flex items-center gap-1.5 rounded-xl border border-rose-400/20 px-2.5 py-1.5 text-[11px] text-rose-200 transition hover:bg-rose-400/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50"
                  >
                    <LogOut size={12} /> Terminar
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Fornecedores de IA */}
      <ProvidersSettings />

      {/* Aplicação (instalação/offline) */}
      <InstallAppSettings />

      {/* Conta */}
      <Card title="Informação da conta" icon={<ShieldCheck size={15} className="text-teal-300" />}>
        <dl className="grid gap-4 text-sm sm:grid-cols-3">
          <Info label="Perfil de acesso" value={user.role === "admin" ? "Administrador" : "Membro"} />
          <Info label="Conta criada" value={formatDate(user.created_at)} />
          <Info label="Último início de sessão" value={formatDate(user.last_login_at)} />
          <Info label="Inícios de sessão" value={String(user.login_count)} />
          <Info label="Estado" value={user.status === "active" ? "Ativa" : "Suspensa"} />
          <Info label="Última alteração" value={formatDate(user.updated_at)} />
        </dl>
        <button
          type="button"
          onClick={() => void logout()}
          className="mt-4 flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <LogOut size={13} /> Terminar sessão nesta aplicação
        </button>
      </Card>

      {/* Zona de perigo */}
      <Card title="Zona de perigo" icon={<ShieldAlert size={15} className="text-rose-300" />} tone="danger">        {dangerMessage && <Banner kind="error" text={dangerMessage} />}
        <p className="text-xs leading-relaxed text-muted-foreground">
          Apagar a conta remove o utilizador e todas as sessões do Elasticsearch. Esta ação não pode ser revertida.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <PasswordInput label="Confirme a palavra-passe" value={deletePassword} onChange={setDeletePassword} />
          <TextInput label='Escreva "APAGAR" para confirmar' value={deleteConfirm} onChange={setDeleteConfirm} icon={<AlertCircle size={14} />} placeholder="APAGAR" />
        </div>
        <button
          type="button"
          onClick={() => void confirmDelete()}
          disabled={deleting || !deletePassword || deleteConfirm !== "APAGAR"}
          className="mt-4 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200 transition hover:bg-rose-500/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50 disabled:opacity-40"
        >
          {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          Apagar conta definitivamente
        </button>
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- peças */

export function Avatar({ user, size = 32 }: { user: Pick<AuthUser, "initials" | "name" | "email">; size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-teal-400 to-blue-500 font-semibold text-white shadow-lg shadow-teal-500/20"
      style={{ width: size, height: size, fontSize: Math.max(11, Math.round(size * 0.36)) }}
      title={`${user.name} · ${user.email}`}
      aria-hidden="true"
    >
      {user.initials}
    </span>
  );
}

function Card({
  title,
  icon,
  action,
  tone,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  tone?: "danger";
  children: React.ReactNode;
}) {
  return (
    <section
      className={[
        "glass-card rounded-2xl p-5",
        tone === "danger" ? "border border-rose-400/20" : "",
      ].join(" ")}
    >
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function Banner({ kind, text }: { kind: "ok" | "error"; text: string }) {
  const Icon = kind === "ok" ? CheckCircle2 : AlertCircle;
  return (
    <p
      role={kind === "error" ? "alert" : undefined}
      className={[
        "mb-4 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs",
        kind === "ok"
          ? "border-teal-300/30 bg-teal-400/10 text-teal-200"
          : "border-rose-400/25 bg-rose-500/10 text-rose-200",
      ].join(" ")}
    >
      <Icon size={14} className="mt-0.5 shrink-0" />
      {text}
    </p>
  );
}

function FieldShell({ label, icon, children }: { label: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 transition focus-within:border-teal-300/40">
        {icon ? <span className="text-muted-foreground">{icon}</span> : null}
        {children}
      </span>
    </label>
  );
}

function TextInput({
  label,
  value,
  onChange,
  icon,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  icon?: React.ReactNode;
  placeholder?: string;
}) {
  return (
    <FieldShell label={label} icon={icon}>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
    </FieldShell>
  );
}

function PasswordInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <FieldShell label={label} icon={<KeyRound size={14} />}>
      <input
        type="password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="new-password"
        className="w-full bg-transparent text-sm outline-none"
      />
    </FieldShell>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
  icon,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  icon?: React.ReactNode;
}) {
  return (
    <FieldShell label={label} icon={icon}>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full bg-transparent text-sm outline-none [&>option]:bg-[#14161b]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

function ReadOnlyInput({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <FieldShell label={label} icon={icon}>
      <input readOnly value={value} className="w-full bg-transparent text-sm text-muted-foreground outline-none" />
    </FieldShell>
  );
}

function ToggleRow({
  label,
  hint,
  icon,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  icon?: React.ReactNode;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2.5">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm">
          {icon ? <span className="text-muted-foreground">{icon}</span> : null}
          {label}
        </p>
        {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={[
          "relative h-5 w-9 shrink-0 rounded-full border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60",
          checked ? "border-teal-300/40 bg-teal-400/70" : "border-white/12 bg-white/10",
        ].join(" ")}
      >
        <span className={["absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5"].join(" ")} />
      </button>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
    </div>
  );
}
