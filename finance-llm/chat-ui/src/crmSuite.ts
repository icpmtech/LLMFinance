/**
 * Estrutura declarativa da arquitetura de CRM do IQ OS (frontend).
 *
 * Espelha o registo do servidor (`api/crm_registry.py`): os mesmos 24 módulos,
 * agrupados por área funcional. Serve para desenhar a navegação, as janelas e o
 * dock **sem** depender de uma chamada à API — os campos e as permissões de cada
 * módulo chegam depois de `GET /crm/suite`.
 *
 * Ao acrescentar um módulo no servidor, acrescenta-se aqui uma linha. Nada mais.
 */
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  BookOpen,
  Building2,
  CalendarClock,
  CalendarDays,
  Columns3,
  FileSignature,
  FileText,
  FolderOpen,
  Gauge,
  Handshake,
  LayoutDashboard,
  LifeBuoy,
  ListChecks,
  ListOrdered,
  Megaphone,
  MessagesSquare,
  Package,
  Route,
  ScrollText,
  Send,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Target,
  TrendingUp,
  Truck,
  UserCog,
  UserPlus,
  Users,
  UsersRound,
  Wrench,
} from "lucide-react";

export type CrmSuiteSection = {
  /** Identificador da secção (igual ao slug do módulo, exceto as vistas de topo). */
  id: string;
  /** Módulo da API que a secção apresenta (`null` nas vistas de topo). */
  slug: string | null;
  label: string;
  hint: string;
  icon: LucideIcon;
  group: string;
  /** Vista/janela correspondente. */
  view: string;
};

export type CrmSuiteGroup = {
  id: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Gradiente do tile no dock (classes Tailwind). */
  gradient: string;
  /** Cor do realce, em `r,g,b`. */
  accent: string;
  sections: CrmSuiteSection[];
};

const moduleView = (slug: string) => `crm-mod:${slug}`;

export const CRM_SUITE_GROUPS: CrmSuiteGroup[] = [
  {
    id: "visao",
    label: "Visão",
    hint: "Pipeline, agenda e relatórios",
    icon: LayoutDashboard,
    gradient: "from-rose-300 via-rose-500 to-pink-600",
    accent: "244,63,94",
    sections: [
      { id: "pipeline", slug: "opportunities", label: "Pipeline", hint: "Quadro de oportunidades por fase", icon: Columns3, group: "visao", view: "crm" },
      { id: "agenda", slug: "activities", label: "Agenda", hint: "Compromissos e tarefas por prazo", icon: CalendarClock, group: "visao", view: "crm-agenda" },
      { id: "dashboard", slug: null, label: "Relatórios", hint: "Indicadores do trabalho comercial", icon: Gauge, group: "visao", view: "crm-dashboard" },
    ],
  },
  {
    id: "analytics",
    label: "Analytics",
    hint: "Vendas, clientes, operações e cross-sell assistido por IA",
    icon: BarChart3,
    gradient: "from-indigo-200 via-indigo-500 to-violet-700",
    accent: "99,102,241",
    sections: [
      { id: "analytics", slug: null, label: "Analytics", hint: "Receita, margem, CLV, SLA e cross-sell", icon: BarChart3, group: "analytics", view: "crm-analytics" },
    ],
  },
  {
    id: "relacao",
    label: "Relação com o cliente",
    hint: "Contas, contactos, leads, oportunidades, casos, atividades, encomendas e contratos",
    icon: Handshake,
    gradient: "from-amber-200 via-amber-400 to-orange-600",
    accent: "245,158,11",
    sections: [
      { id: "accounts", slug: "accounts", label: "Contas", hint: "Empresas cliente, prospectos e parceiros", icon: Building2, group: "relacao", view: "crm-accounts" },
      { id: "contacts", slug: "contacts", label: "Contactos", hint: "Pessoas de contacto das contas", icon: Users, group: "relacao", view: "crm-contacts" },
      { id: "leads", slug: "leads", label: "Leads", hint: "Contactos ainda não qualificados", icon: UserPlus, group: "relacao", view: moduleView("leads") },
      { id: "opportunities", slug: "opportunities", label: "Oportunidades", hint: "Negócio em curso, valor e fase", icon: Target, group: "relacao", view: moduleView("opportunities") },
      { id: "cases", slug: "cases", label: "Casos", hint: "Pedidos de apoio e SLA", icon: LifeBuoy, group: "relacao", view: moduleView("cases") },
      { id: "activities", slug: "activities", label: "Atividades", hint: "Tarefas, chamadas, reuniões e notas", icon: ListChecks, group: "relacao", view: moduleView("activities") },
      { id: "orders", slug: "orders", label: "Encomendas", hint: "Encomendas do rascunho à faturação", icon: ShoppingCart, group: "relacao", view: moduleView("orders") },
      { id: "order-lines", slug: "order-lines", label: "Linhas de encomenda", hint: "Produtos, quantidades e margem de cada encomenda", icon: ListOrdered, group: "relacao", view: moduleView("order-lines") },
      { id: "work-orders", slug: "work-orders", label: "Ordens de trabalho", hint: "Instalações, manutenções e SLA da operação", icon: Wrench, group: "relacao", view: moduleView("work-orders") },
      { id: "contracts", slug: "contracts", label: "Contratos", hint: "Contratos, renovações e valores", icon: FileSignature, group: "relacao", view: moduleView("contracts") },
    ],
  },
  {
    id: "comercial",
    label: "Comercial e catálogo",
    hint: "Produtos, propostas e previsões",
    icon: Package,
    gradient: "from-lime-200 via-emerald-400 to-teal-600",
    accent: "16,185,129",
    sections: [
      { id: "products", slug: "products", label: "Produtos", hint: "Catálogo com preços e margens", icon: Package, group: "comercial", view: moduleView("products") },
      { id: "quotes", slug: "quotes", label: "Propostas", hint: "Propostas com linhas e totais", icon: FileText, group: "comercial", view: moduleView("quotes") },
      { id: "forecasts", slug: "forecasts", label: "Previsões", hint: "Objetivos e previsão de venda", icon: TrendingUp, group: "comercial", view: moduleView("forecasts") },
    ],
  },
  {
    id: "compras",
    label: "Compras e fornecedores",
    hint: "Fornecedores, condições de compra e custo de aquisição",
    icon: Truck,
    gradient: "from-orange-200 via-orange-400 to-red-600",
    accent: "249,115,22",
    sections: [
      { id: "suppliers", slug: "suppliers", label: "Fornecedores", hint: "Condições, prazos, pontualidade e custo de aquisição", icon: Truck, group: "compras", view: moduleView("suppliers") },
    ],
  },
  {
    id: "marketing",
    label: "Marketing",
    hint: "Campanhas, públicos, atividades e jornadas",
    icon: Megaphone,
    gradient: "from-fuchsia-300 via-purple-500 to-indigo-600",
    accent: "167,139,250",
    sections: [
      { id: "campaigns", slug: "campaigns", label: "Campanhas", hint: "Campanhas, orçamento e retorno", icon: Megaphone, group: "marketing", view: moduleView("campaigns") },
      { id: "campaign-members", slug: "campaign-members", label: "Membros de campanha", hint: "Quem está em cada campanha", icon: UsersRound, group: "marketing", view: moduleView("campaign-members") },
      { id: "marketing-activities", slug: "marketing-activities", label: "Atividades de marketing", hint: "Envios e publicações", icon: Send, group: "marketing", view: moduleView("marketing-activities") },
      { id: "marketing-journeys", slug: "marketing-journeys", label: "Jornadas", hint: "Automatismos de nutrição", icon: Route, group: "marketing", view: moduleView("marketing-journeys") },
    ],
  },
  {
    id: "administracao",
    label: "Administração",
    hint: "Utilizadores, equipas e perfis de acesso",
    icon: ShieldCheck,
    gradient: "from-slate-300 via-slate-500 to-slate-700",
    accent: "148,163,184",
    sections: [
      { id: "users", slug: "users", label: "Utilizadores", hint: "Perfil, área, departamento e equipa", icon: UserCog, group: "administracao", view: moduleView("users") },
      { id: "teams", slug: "teams", label: "Equipas", hint: "Equipas, responsáveis e objetivos", icon: UsersRound, group: "administracao", view: moduleView("teams") },
      { id: "roles", slug: "roles", label: "Perfis de acesso", hint: "Módulos, ações e âmbito de visibilidade", icon: ShieldCheck, group: "administracao", view: moduleView("roles") },
    ],
  },
  {
    id: "operacao",
    label: "Operação e auditoria",
    hint: "Eventos e registo de auditoria",
    icon: Activity,
    gradient: "from-sky-200 via-sky-400 to-blue-600",
    accent: "56,189,248",
    sections: [
      { id: "events", slug: "events", label: "Eventos", hint: "Reuniões, webinars, feiras e formações", icon: CalendarDays, group: "operacao", view: moduleView("events") },
      { id: "audit", slug: "audit", label: "Auditoria", hint: "Quem alterou o quê e quando", icon: ScrollText, group: "operacao", view: moduleView("audit") },
    ],
  },
  {
    id: "conhecimento",
    label: "Conhecimento",
    hint: "Documentos e base de conhecimento",
    icon: BookOpen,
    gradient: "from-cyan-200 via-teal-400 to-emerald-600",
    accent: "20,184,166",
    sections: [
      { id: "documents", slug: "documents", label: "Documentos", hint: "Ficheiros ligados a contas e negócio", icon: FolderOpen, group: "conhecimento", view: moduleView("documents") },
      { id: "knowledge", slug: "knowledge", label: "Conhecimento", hint: "Procedimentos, FAQs e políticas", icon: BookOpen, group: "conhecimento", view: moduleView("knowledge") },
    ],
  },
  {
    id: "inteligencia",
    label: "Inteligência artificial",
    hint: "Perceções e interações do assistente",
    icon: Sparkles,
    gradient: "from-teal-200 via-sky-500 to-indigo-700",
    accent: "129,140,248",
    sections: [
      { id: "ai-insights", slug: "ai-insights", label: "Perceções de IA", hint: "Riscos, oportunidades e recomendações", icon: Sparkles, group: "inteligencia", view: moduleView("ai-insights") },
      { id: "ai-interactions", slug: "ai-interactions", label: "Interações de IA", hint: "Perguntas e respostas do assistente", icon: MessagesSquare, group: "inteligencia", view: moduleView("ai-interactions") },
    ],
  },
];

/** Todas as secções, em ordem, com o grupo a que pertencem. */
export const CRM_SUITE_SECTIONS: CrmSuiteSection[] = CRM_SUITE_GROUPS.flatMap((group) => group.sections);

const SECTION_INDEX = new Map(CRM_SUITE_SECTIONS.map((section) => [section.id, section]));

/** Vista/janela de cada secção. */
export const CRM_SECTION_VIEWS: Record<string, string> = Object.fromEntries(
  CRM_SUITE_SECTIONS.map((section) => [section.id, section.view]),
);

/** Vistas antigas (antes dos módulos genéricos) aceites para não quebrar ligações. */
const LEGACY_VIEW_SECTIONS: Record<string, string> = {
  crm: "pipeline",
  "crm-accounts": "accounts",
  "crm-contacts": "contacts",
  "crm-agenda": "agenda",
  "crm-dashboard": "dashboard",
};

/** Secção a partir do identificador de vista (ou `null`). */
export function crmSuiteSectionForView(view: string): string | null {
  if (!view) return null;
  // Cada secção tem uma vista única — é o critério seguro, porque há secções
  // que partilham o mesmo módulo (o Pipeline e as Oportunidades, a Agenda e as
  // Atividades): a vista distingue-as.
  const direct = CRM_SUITE_SECTIONS.find((section) => section.view === view);
  if (direct) return direct.id;
  if (LEGACY_VIEW_SECTIONS[view]) return LEGACY_VIEW_SECTIONS[view];
  return null;
}

/**
 * Segmento de URL de cada secção.
 *
 * As secções cujo slug coincide com uma rota JSON do CRM
 * (`/crm/activities` responde com a lista de atividades da API) usam o nome
 * português, como já acontecia com contas/contactos/agenda/relatórios.
 */
const SECTION_PATHS: Record<string, string> = {
  accounts: "contas",
  contacts: "contactos",
  agenda: "agenda",
  dashboard: "relatorios",
  activities: "atividades",
  analytics: "indicadores",
};

/** Caminho de URL de uma vista do CRM (secção ou módulo). */
export function crmSuitePathForView(view: string): string {
  if (view.startsWith("crm-mod:")) {
    const slug = view.slice("crm-mod:".length);
    return `/crm/${SECTION_PATHS[slug] ?? slug}`;
  }
  const section = CRM_SUITE_SECTIONS.find((item) => item.view === view);
  if (!section) return "/crm";
  return `/crm/${SECTION_PATHS[section.id] ?? section.id}`;
}

/** Secção a partir de um caminho de URL (`/crm/...`) ou `null`. */
export function crmSuiteSectionFromPath(path: string): string | null {
  if (!path.startsWith("/crm")) return null;
  const rest = path.replace(/^\/crm\/?/, "").replace(/\/$/, "");
  if (!rest) return "pipeline";
  const aliases: Record<string, string> = {
    contas: "accounts",
    contactos: "contacts",
    agenda: "agenda",
    relatorios: "dashboard",
    indicadores: "analytics",
    atividades: "activities",
    relatório: "dashboard",
    oportunidades: "opportunities",
    casos: "cases",
    encomendas: "orders",
    contratos: "contracts",
    produtos: "products",
    propostas: "quotes",
    previsoes: "forecasts",
    campanhas: "campaigns",
    "campanhas-membros": "campaign-members",
    "marketing-atividades": "marketing-activities",
    "marketing-jornadas": "marketing-journeys",
    utilizadores: "users",
    equipas: "teams",
    perfis: "roles",
    rbac: "roles",
    admin: "users",
    eventos: "events",
    auditoria: "audit",
    documentos: "documents",
    conhecimento: "knowledge",
    "ia-percecoes": "ai-insights",
    "ia-interacoes": "ai-interactions",
    todos: "dashboard",
  };
  const key = aliases[rest] ?? rest;
  return SECTION_INDEX.has(key) ? key : null;
}

/** Secção pelo id (ou `undefined`). */
export function crmSuiteSection(id: string): CrmSuiteSection | undefined {
  return SECTION_INDEX.get(id);
}

/** Grupo de uma secção. */
export function crmSuiteGroupOf(sectionId: string): CrmSuiteGroup | undefined {
  return CRM_SUITE_GROUPS.find((group) => group.sections.some((section) => section.id === sectionId));
}

/** Vista de uma secção de CRM. */
export function crmSuiteViewFor(sectionId: string): string {
  return CRM_SECTION_VIEWS[sectionId] ?? "crm";
}

/**
 * Secções cujo conteúdo é o **módulo genérico** (lista, filtros, ficha e campos
 * declarados no servidor). As restantes têm vistas próprias (pipeline, agenda,
 * relatórios) ou painéis especializados (contas e contactos).
 */
const CUSTOM_SECTIONS = new Set(["pipeline", "agenda", "dashboard", "accounts", "contacts", "analytics"]);

export function crmSuiteIsModuleSection(sectionId: string): boolean {
  const section = SECTION_INDEX.get(sectionId);
  return Boolean(section?.slug) && !CUSTOM_SECTIONS.has(sectionId);
}
