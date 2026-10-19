/**
 * Gating de módulos pelo plano de subscrição.
 *
 * O backend é a fonte de verdade, mas o frontend pode esconder ícones do dock,
 * barra lateral e rotas para utilizadores cujo plano não inclui o módulo.
 */
import { useMemo } from "react";
import { useAuth } from "./auth";
import type { AuthUser } from "./authApi";
import { isAnalystProfile } from "./sidebarAccess";

export type PlanModuleMap = Record<string, string[]>;

/** Nomes apresentáveis dos planos, alinhados com `PLANS` no backend. */
export const PLAN_NAMES: Record<string, string> = {
  basic: "Básico",
  pro: "Profissional",
  enterprise: "Enterprise",
};

export function planName(planId?: string | null): string {
  if (!planId) return "—";
  return PLAN_NAMES[planId] || planId;
}

const DEFAULT_PLAN_MODULES: PlanModuleMap = {
  basic: [
    "dashboard",
    "finder",
    "contracts",
    "contracts-es",
    "contracts-fr",
    "empresas",
    "pessoas",
    "search360",
  ],
  pro: [
    "dashboard",
    "finder",
    "contracts",
    "contracts-es",
    "contracts-fr",
    "empresas",
    "pessoas",
    "search360",
    "mercado",
    "sentiment",
    "benchmark",
    "reports",
    "email",
    "rss",
  ],
  enterprise: [
    "dashboard",
    "finder",
    "contracts",
    "contracts-es",
    "contracts-fr",
    "empresas",
    "pessoas",
    "search360",
    "mercado",
    "sentiment",
    "benchmark",
    "reports",
    "email",
    "rss",
    "crm",
    "scraper",
    "social",
    "hermes",
    "jarvis",
    "world",
    "ontology",
    "gleif",
  ],
};

/**
 * Mapeia ids de aplicação do dock para ids de módulo de subscrição.
 * Valores `null` significam que a entrada é sempre visível (não depende do plano).
 */
const DOCK_APP_MODULE: Record<string, string | null> = {
  chat: null,
  "empresas-iq": "empresas",
  "pessoas-iq": "pessoas",
  "pessoas-iq-politicos": "pessoas",
  descoberta: "empresas",
  "descoberta-pessoas": "pessoas",
  "companies-global": "empresas",
  search360: "search360",
  hermes: "hermes",
  jarvis: "jarvis",
  office: null,
  cms: null,
  rss: "rss",
  noticias: "rss",
  shop: null,
  email: "email",
  crm: "crm",
  "crm-accounts": "crm",
  "crm-contacts": "crm",
  "crm-agenda": "crm",
  "crm-dashboard": "crm",
  "crm-analytics": "crm",
  "crm-dashboards": "crm",
  scraper: "scraper",
  "scraper-templates": "scraper",
  "scraper-execucoes": "scraper",
  "scraper-pesquisa": "scraper",
  "scraper-agenda": "scraper",
  social: "social",
  "social-canais": "social",
  "social-execucoes": "social",
  "social-modelos": "social",
  "social-agenda": "social",
  "social-estado": "social",
  world: "world",
  "world-rede": "world",
  padroes: "world",
  lorenz: "world",
  mercado: "mercado",
  "mercado-cenarios": "mercado",
  sentimento: "sentiment",
  vortal: null,
  osint: null,
  reports: "reports",
  "report-studio": "reports",
  subvencoes: null,
  "administracao-central": null,
  governo: null,
  partidos: null,
  "entidade-transparencia": null,
  erc: null,
  remuneracoes: null,
  "remuneracoes-ap": null,
  "municipios-despesas": null,
  simulador: null,
  mirofish: null,
  risco: "empresas",
  societario: null,
  "empresas-recolha": null,
  arquivo: null,
  gleif: "gleif",
  "gleif-mapa": "gleif",
  "gleif-ingestao": "gleif",
  finder: "finder",
  dashboard: "dashboard",
  pesquisa: "search360",
  search: "search360",
  browser: null,
  "contracts-search": "contracts",
  "contracts-dashboard": "contracts",
  "contracts-eco": "contracts",
  "contracts-map": "contracts",
  benchmark: "benchmark",
  benchmarks: "benchmark",
  "benchmark-pt": "benchmark",
  "benchmark-es": "benchmark",
  "benchmark-fr": "benchmark",
  "benchmark-cross": "benchmark",
  "benchmark-buyer": "benchmark",
  "benchmark-seller": "benchmark",
  "contratos-es": "contracts-es",
  "contratos-es-dashboard": "contracts-es",
  "contratos-fr": "contracts-fr",
  "contratos-fr-dashboard": "contracts-fr",
  "contratos-fr-mapa": "contracts-fr",
  "entities-search": "empresas",
  "entities-dashboard": "empresas",
  "entities-adjudicantes": "empresas",
  "entities-adjudicatarios": "empresas",
  "entities-compare": "empresas",
  tickers: "mercado",
  "ticker-chart": "mercado",
  forecast: "mercado",
  trading: "mercado",
  ontology: "ontology",
  researcher: null,
  agents: null,
  rag: null,
  elastic: null,
  import: null,
  compare: null,
  settings: null,
  admin: null,
  permissions: null,
  "admin-mail": null,
  cli: null,
  cire: null,
  citacoes: null,
  contribuintes: null,
  landing: null,
  login: null,
  register: null,
};

function planModules(user: AuthUser | null): string[] {
  if (!user) return [];
  const planId = user.subscription?.plan_id || "basic";
  return DEFAULT_PLAN_MODULES[planId] || DEFAULT_PLAN_MODULES.basic;
}

/** Papéis da equipa da plataforma (vêem a Área de análise sem o perfil de CRM). */
const STAFF_ROLES = new Set(["admin", "manager"]);

/**
 * A «Área de análise» não se compra: é do perfil de CRM «Analista de dados».
 * A equipa da plataforma vê-a sempre para poder acompanhar o módulo.
 */
function canSeeAnalystArea(user: AuthUser): boolean {
  return STAFF_ROLES.has(user.role) || isAnalystProfile();
}

export function canAccessDockApp(user: AuthUser | null, appId: string): boolean {
  if (!user) return false;
  if (appId === "analise") return canSeeAnalystArea(user);
  if (user.role === "admin") return true;
  const moduleId = DOCK_APP_MODULE[appId];
  if (moduleId === null) return true;
  if (!moduleId) return true;
  return planModules(user).includes(moduleId);
}

export function usePlanModules(): string[] {
  const { user } = useAuth();
  return useMemo(() => planModules(user), [user]);
}
