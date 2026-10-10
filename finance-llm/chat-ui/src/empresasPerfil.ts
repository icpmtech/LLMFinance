/**
 * Cliente do módulo **Sites e logótipos das empresas** (`/empresas/perfil/*`).
 *
 * Dá **marca** às empresas do benchmark: o backend procura o site oficial
 * (pesquisa web + validação por HTTP + arbitragem por IA) e extrai o logótipo
 * desse site. O resultado fica em cache no servidor, pelo que:
 *
 * 1. `getPerfisEmpresas` é uma leitura rápida da cache (é o que o grafo faz
 *    ao abrir a análise);
 * 2. `resolverPerfisEmpresas` vai à rede para o que falta, em lotes pequenos
 *    (o servidor limita cada pedido), o que permite mostrar os logótipos à
 *    medida que chegam.
 */
import { API_BASE } from "./api";

export interface EmpresaPerfil {
  nif?: string | null;
  nome?: string | null;
  pais?: string | null;
  /** Site oficial encontrado (ou `null`). */
  site?: string | null;
  dominio?: string | null;
  /** 0 a 1 — quanto a evidência sustenta este site. */
  confianca?: number;
  origem?: string | null;
  motivo?: string | null;
  tem_logo?: boolean;
  /** Caminho pronto para `<img src>` (a rota do logótipo não pede sessão). */
  logo_url?: string | null;
  atualizado?: string | null;
  candidatos?: EmpresaPerfilCandidato[];
  ia?: { provider?: string; modelo?: string; confianca?: number; motivo?: string } | null;
  em_cache?: boolean;
  erro?: string;
}

export interface EmpresaPerfilCandidato {
  url: string;
  titulo?: string;
  pontos?: number;
  motivo?: string;
}

export interface EmpresaPerfilStats {
  total: number;
  com_site: number;
  com_logo: number;
  sem_site: number;
  taxa_site: number;
  taxa_logo: number;
  config: Record<string, unknown>;
  diretorio: string;
}

export interface EmpresaPerfilAlvo {
  nif?: string | null;
  nome?: string | null;
  pais?: "pt" | "es" | "fr";
}

export interface ResolverPerfisResponse {
  perfis: EmpresaPerfil[];
  resolvidos: number;
  com_logo: number;
  stats: EmpresaPerfilStats;
}

/** Perfis já conhecidos (só cache, sem ir à rede). */
export async function getPerfisEmpresas(nifs: string[]): Promise<Record<string, EmpresaPerfil>> {
  const limpos = nifs.map((valor) => String(valor || "").trim()).filter(Boolean).slice(0, 60);
  if (!limpos.length) return {};
  const res = await fetch(`${API_BASE}/empresas/perfil?nifs=${encodeURIComponent(limpos.join(","))}`);
  if (!res.ok) throw new Error(`Erro ao ler os perfis das empresas: ${res.status}`);
  const dados = (await res.json()) as { perfis?: Record<string, EmpresaPerfil> };
  return dados.perfis || {};
}

/** Resolve site e logótipo do que falta (pedido com sessão). */
export async function resolverPerfisEmpresas(
  alvos: EmpresaPerfilAlvo[],
  opcoes: { pais?: "pt" | "es" | "fr"; usarIa?: boolean; forcar?: boolean } = {},
): Promise<ResolverPerfisResponse> {
  const res = await fetch(`${API_BASE}/empresas/perfil/resolver`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      alvos: alvos.slice(0, 12),
      pais: opcoes.pais || "pt",
      usar_ia: opcoes.usarIa ?? true,
      forcar: opcoes.forcar ?? false,
    }),
  });
  if (!res.ok) {
    const texto = await res.text().catch(() => "");
    throw new Error(`Erro ao identificar os sites das empresas: ${res.status} ${texto.slice(0, 160)}`);
  }
  return (await res.json()) as ResolverPerfisResponse;
}

/** Correcção manual do site (backoffice). */
export async function definirSiteEmpresa(nif: string, site: string, nome?: string): Promise<EmpresaPerfil> {
  const res = await fetch(`${API_BASE}/empresas/perfil/${encodeURIComponent(nif)}/site`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ site, nome }),
  });
  if (!res.ok) {
    const texto = await res.text().catch(() => "");
    throw new Error(`Erro ao guardar o site: ${res.status} ${texto.slice(0, 160)}`);
  }
  return (await res.json()) as EmpresaPerfil;
}

/** Cobertura do módulo (painel do administrador). */
export async function getPerfisEmpresasStats(): Promise<EmpresaPerfilStats> {
  const res = await fetch(`${API_BASE}/empresas/perfil/stats`);
  if (!res.ok) throw new Error(`Erro ao obter as estatísticas: ${res.status}`);
  return (await res.json()) as EmpresaPerfilStats;
}

/** Perfis conhecidos (backoffice). */
export async function listarPerfisEmpresas(limite = 200, soComSite = false): Promise<EmpresaPerfil[]> {
  const res = await fetch(`${API_BASE}/empresas/perfil/lista?limite=${limite}&so_com_site=${soComSite}`);
  if (!res.ok) throw new Error(`Erro ao listar os perfis: ${res.status}`);
  const dados = (await res.json()) as { items?: EmpresaPerfil[] };
  return dados.items || [];
}

/** URL absoluto do logótipo (útil fora de `<img src>` directo, ex.: `background-image`). */
export function urlLogoAbsoluto(logoUrl?: string | null): string | null {
  if (!logoUrl) return null;
  if (/^https?:/i.test(logoUrl)) return logoUrl;
  return `${API_BASE}${logoUrl.replace(/^\/api/, "")}`;
}
