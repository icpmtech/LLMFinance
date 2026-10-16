/**
 * Cabeçalho e rodapé das páginas públicas da plataforma (`/app-shell`).
 *
 * Quem chega sem sessão vê as páginas de entrada (`/`, `/login` e `/register`).
 * O que elas mostram no cabeçalho e no rodapé — marca, logótipo, navegação,
 * botões e redes sociais — é uma definição **da plataforma**, independente da do
 * site público do CMS, e edita-se no backoffice (Administração → Plataforma).
 *
 * A leitura é aberta (`GET /app-shell`) e tolerante a falhas: sem resposta da
 * API, as páginas usam `DEFAULT_APP_SHELL` e continuam a funcionar — a entrada
 * não pode depender desta configuração para abrir.
 */
import { API_BASE } from "./api";

export type ShellLink = { label: string; href: string };

export type ShellSocial = { key: string; label: string; href: string };

/** O que as páginas desenham (já resolvido pelo servidor). */
export type AppShell = {
  brand: { name: string; tagline: string; logo_url: string; logo_alt: string };
  header: { items: ShellLink[]; cta: ShellLink | null; secondary: ShellLink | null };
  footer: { text: string; items: ShellLink[]; social: ShellSocial[] };
  updated_at: string;
};

/** A configuração como o backoffice a lê e grava (inclui o estado da gravação). */
export type AppShellDocument = {
  brand: { name: string; tagline: string; logo_url: string; logo_alt: string };
  header: { items: ShellLink[]; cta: ShellLink | null; secondary: ShellLink | null };
  footer: { text: string; items: ShellLink[]; social: Record<string, string> };
  updated_at: string;
  updated_by: string;
  configured: boolean;
};

export type AppShellDefaults = {
  brand: { name: string; tagline: string; logo_url: string; logo_alt: string };
  header: { items: ShellLink[]; cta: ShellLink | null; secondary: ShellLink | null };
  footer: { text: string; items: ShellLink[]; social: Record<string, string> };
};

export type AppShellState = {
  shell: AppShellDocument;
  defaults: AppShellDefaults;
  limits: { links: number; label: number; href: number; text: number };
  social: { key: string; label: string }[];
  saved?: boolean;
};

/** O que se mostra enquanto a API não responde (igual à predefinição do servidor). */
export const DEFAULT_APP_SHELL: AppShell = {
  brand: { name: "IQ OS", tagline: "Plataforma de inteligência financeira", logo_url: "", logo_alt: "IQ OS" },
  header: {
    items: [],
    cta: { label: "Criar conta", href: "/register" },
    secondary: { label: "Entrar", href: "/login" },
  },
  footer: {
    text: "Sabemos Studio · IQ OS — Plataforma de Inteligência Financeira",
    items: [
      { label: "Entrar", href: "/login" },
      { label: "Criar conta", href: "/register" },
    ],
    social: [],
  },
  updated_at: "",
};

/**
 * Configuração em vigor.
 *
 * Um campo em falta na resposta não deixa o cabeçalho sem marca: completa-se com
 * a predefinição local, que é a mesma do servidor.
 */
export async function getAppShell(): Promise<AppShell> {
  const response = await fetch(`${API_BASE}/app-shell`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Erro ${response.status} ao ler o cabeçalho da plataforma.`);
  const corpo = (await response.json()) as Partial<AppShell>;
  return {
    brand: { ...DEFAULT_APP_SHELL.brand, ...(corpo.brand || {}) },
    header: { ...DEFAULT_APP_SHELL.header, ...(corpo.header || {}) },
    footer: { ...DEFAULT_APP_SHELL.footer, ...(corpo.footer || {}) },
    updated_at: corpo.updated_at || "",
  };
}

/** `true` quando o endereço sai da plataforma (abre em janela nova). */
export function linkExterno(href: string): boolean {
  return /^https?:\/\//i.test(href);
}
