/**
 * Estado de autenticação da aplicação.
 *
 * - Ao arrancar, se existir um token guardado, a sessão é revalidada em
 *   `/auth/me` (o servidor é a fonte de verdade: sessões revogadas ou tokens
 *   expirados caem imediatamente).
 * - O token é injetado automaticamente nos pedidos à API (`installAuthFetch`).
 * - As preferências guardadas na conta (vista inicial, posição do dock, barra
 *   lateral escondida, movimento reduzido) são aplicadas quando a sessão abre.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  authApi,
  getToken,
  installAuthFetch,
  setToken,
  type AuthResult,
  type AuthSession,
  type AuthUser,
  type ProfilePatch,
} from "./authApi";

installAuthFetch();

type Status = "loading" | "anonymous" | "authenticated";

type AuthContextValue = {
  status: Status;
  user: AuthUser | null;
  login: (email: string, password: string, remember: boolean) => Promise<AuthUser>;
  register: (data: { name: string; email: string; password: string; title?: string; organization?: string }) => Promise<AuthUser>;
  logout: () => Promise<void>;
  logoutEverywhere: () => Promise<string>;
  updateProfile: (patch: ProfilePatch) => Promise<AuthUser>;
  changePassword: (current: string, next: string) => Promise<string>;
  deleteAccount: (password: string) => Promise<void>;
  refresh: () => Promise<void>;
  sessions: () => Promise<AuthSession[]>;
  revokeSession: (id: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(() => (getToken() ? "loading" : "anonymous"));
  const [user, setUser] = useState<AuthUser | null>(null);

  const applyPreferences = useCallback((next: AuthUser | null) => {
    if (typeof document === "undefined" || !next) return;
    const reduced = Boolean((next.preferences || {}).reduced_motion);
    document.documentElement.classList.toggle("reduce-motion", reduced);
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setStatus("anonymous");
      return;
    }
    try {
      const profile = await authApi.me();
      setUser(profile);
      applyPreferences(profile);
      setStatus("authenticated");
    } catch {
      // Token inválido/expirado ou sessão terminada noutro dispositivo.
      setToken(null);
      setUser(null);
      setStatus("anonymous");
    }
  }, [applyPreferences]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const acceptResult = useCallback(
    (result: AuthResult) => {
      setToken(result.token);
      setUser(result.user);
      applyPreferences(result.user);
      setStatus("authenticated");
      return result.user;
    },
    [applyPreferences],
  );

  const login = useCallback(
    async (email: string, password: string, remember: boolean) =>
      acceptResult(await authApi.login({ email, password, remember })),
    [acceptResult],
  );

  const register = useCallback(
    async (data: { name: string; email: string; password: string; title?: string; organization?: string }) =>
      acceptResult(await authApi.register(data)),
    [acceptResult],
  );

  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
    setStatus("anonymous");
    if (typeof document !== "undefined") document.documentElement.classList.remove("reduce-motion");
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Mesmo que o servidor não responda, a sessão local é encerrada.
    }
    clearSession();
  }, [clearSession]);

  const logoutEverywhere = useCallback(async () => {
    const result = await authApi.revokeOtherSessions();
    return result.message;
  }, []);

  const updateProfile = useCallback(
    async (patch: ProfilePatch) => {
      const updated = await authApi.updateProfile(patch);
      setUser(updated);
      applyPreferences(updated);
      return updated;
    },
    [applyPreferences],
  );

  const changePassword = useCallback(async (current: string, next: string) => {
    const result = await authApi.changePassword({ current_password: current, new_password: next });
    return result.message;
  }, []);

  const deleteAccount = useCallback(
    async (password: string) => {
      await authApi.deleteAccount(password);
      clearSession();
    },
    [clearSession],
  );

  const sessions = useCallback(() => authApi.sessions(), []);

  const revokeSession = useCallback(async (id: string) => {
    await authApi.revokeSession(id);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      login,
      register,
      logout,
      logoutEverywhere,
      updateProfile,
      changePassword,
      deleteAccount,
      refresh,
      sessions,
      revokeSession,
    }),
    [
      status,
      user,
      login,
      register,
      logout,
      logoutEverywhere,
      updateProfile,
      changePassword,
      deleteAccount,
      refresh,
      sessions,
      revokeSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth tem de ser usado dentro de <AuthProvider>.");
  return context;
}

/** Estado público do serviço de contas (para o painel de administração). */
export type { AuthSession, AuthUser, ProfilePatch };
