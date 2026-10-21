/**
 * Catálogo dos módulos da barra lateral — a **fonte única** de classificação.
 *
 * A barra lateral da plataforma mostra:
 *
 * - as **aplicações**, agrupadas por **módulo** (Visão geral, Contratos,
 *   Empresas, Pessoas, Dados públicos, Mercados, Investigação e IA,
 *   Conhecimento, Recolha, Redes sociais) — e não numa lista única de 50 linhas;
 * - as **secções de CRM**, agrupadas por área funcional;
 * - as **ferramentas** (Elasticsearch, Importar, Terminal, Definições,
 *   Administração, páginas iframe).
 *
 * Este módulo descreve os catálogos para o `AppNav` (menu lateral), o `dock` e a
 * página de administração usarem a **mesma** classificação, sem a repetir.
 */
import { DOCK_CATALOG, type DockApp } from "./dock";
import { CRM_SUITE_GROUPS, CRM_SUITE_SECTIONS } from "./crmSuite";

/** Ferramentas: aparecem no grupo «Ferramentas» da barra lateral. */
export const TOOL_APP_IDS = ["elastic", "import", "cli", "settings", "admin", "admin-mail", "permissions", "iframe-pages"];

/** Vistas de CRM: cada secção da arquitetura tem a sua entrada. */
export const CRM_VIEW_IDS: string[] = CRM_SUITE_SECTIONS.map((section) => section.view);

/** Módulos que nunca podem ser escondidos (trancariam o acesso à plataforma). */
export const RESERVED_MODULES = ["chat", "finder", "settings", "admin", "admin-mail", "permissions"];

export type SidebarModule = {
  id: string;
  label: string;
  hint: string;
};

export type SidebarModuleGroup = {
  id: string;
  label: string;
  hint: string;
  /** Família do grupo: módulo de aplicações, área de CRM ou ferramentas. */
  kind: "apps" | "crm" | "tools";
  items: SidebarModule[];
};

/** Módulo (família) de aplicações: agrupa as aplicações do mesmo domínio. */
export type AppModule = {
  id: string;
  label: string;
  hint: string;
  /** Identificadores das aplicações do módulo, pela ordem em que aparecem. */
  ids: string[];
  /**
   * Fonte dinâmica de entradas, por módulo: o `AppNav` vai buscá-las à API e
   * acrescenta-as ao grupo. Hoje só os benchmarks de produtos (uma entrada de
   * menu por estudo, criada quando o estudo é criado).
   */
  dynamic?: "benchmarks";
};

/**
 * Organização das aplicações por módulo (a ordem aqui é a ordem no menu).
 *
 * «Análise» e «Visão geral» abrem por omissão — a primeira é o painel do
 * analista e a segunda é onde vivem o dashboard, o Finder, o chat e a
 * pesquisa; os restantes abrem a pedido (ou sozinhos, quando lá está a
 * aplicação ativa).
 */
export const APP_MODULES: AppModule[] = [
  {
    id: "analise",
    label: "Análise",
    hint: "Painel de trabalho do analista: indicadores, série anual e leitura assistida",
    ids: ["analise"],
  },
  {
    id: "visao-geral",
    label: "Visão geral",
    hint: "Dashboard, Finder, chat, browser e pesquisa",
    ids: ["dashboard", "finder", "chat", "browser", "search", "pesquisa", "deep-search"],
  },
  {
    id: "contratos",
    label: "Contratos públicos",
    hint: "Pesquisa, análise, mapa e contratação ecológica",
    ids: ["contracts-search", "contracts-dashboard", "contracts-eco", "contracts-map"],
  },
  {
    id: "contratos-es",
    label: "Contratos de Espanha",
    hint: "Plataforma de contratação do setor público (PLACSP)",
    ids: ["contratos-es", "contratos-es-dashboard"],
  },
  {
    id: "contratos-fr",
    label: "Contratos de França",
    hint: "Données Essentielles de la Commande Publique (DECP)",
    ids: ["contratos-fr", "contratos-fr-dashboard", "contratos-fr-mapa"],
  },
  {
    id: "benchmark",
    label: "Benchmark",
    hint: "Preço de referência, concorrência e oportunidades — Portugal, Espanha e França",
    ids: ["benchmark", "benchmark-pt", "benchmark-es", "benchmark-fr", "benchmark-cross", "benchmark-buyer", "benchmark-seller"],
  },
  {
    id: "benchmarks-produtos",
    label: "Benchmarks de produtos",
    hint: "O mesmo produto comparado entre lojas online (recolha de preços, índice próprio)",
    // Cada benchmark criado acrescenta a sua própria entrada ao menu.
    ids: ["benchmarks"],
    dynamic: "benchmarks",
  },
  {
    id: "empresas",
    label: "Empresas",
    hint: "Risco, diretórios, fichas, adjudicantes e comparação de entidades",
    ids: [
      "descoberta",
      "risco",
      "empresas-iq",
      "entities-search",
      "entities-dashboard",
      "entities-adjudicantes",
      "entities-adjudicatarios",
      "entities-compare",
      "compare",
      "companies-global",
    ],
  },
  {
    id: "sustentabilidade",
    label: "Sustentabilidade",
    hint: "Score ESG por empresa, pilares E/S/G, benchmark e carteira de fornecedores",
    ids: ["esg"],
  },
  {
    id: "dora",
    label: "DORA",
    hint: "Resiliência operacional digital: Register of Information, incidentes ICT, riscos, workflows e relatórios ITS/RTS",
    ids: ["dora"],
  },
  {
    id: "pessoas",
    label: "Pessoas",
    hint: "Pessoas, cargos, políticos e as contas dos partidos",
    ids: ["descoberta-pessoas", "pessoas-iq-pesquisa", "pessoas-iq", "pessoas-iq-politicos", "partidos", "entidade-transparencia", "transparencia-grafo"],
  },
  {
    id: "dados-publicos",
    label: "Dados públicos",
    hint: "Insolvências, citações editais, contribuintes, societário, registos LEI, subvenções, remunerações dos eleitos locais, despesas das câmaras municipais, comunicação social (ERC) e o Governo",
    ids: ["cire", "citacoes", "contribuintes", "societario", "gleif", "gleif-mapa", "gleif-ingestao", "subvencoes", "administracao-central", "governo", "remuneracoes", "municipios-despesas", "municipios-contactos", "erc", "vortal"],
  },
  {
    id: "mercados",
    label: "Mercados e previsão",
    hint: "Cotações, gráficos, previsões e simulação de negociação",
    ids: ["tickers", "market", "ticker-chart", "forecast", "trading"],
  },
  {
    id: "investigacao",
    label: "Investigação e IA",
    hint: "Pesquisa 360, Hermes, Jarvis, investigador, agentes e RAG",
    ids: ["search360", "hermes", "jarvis", "researcher", "world", "world-rede", "padroes", "lorenz", "mercado", "mercado-cenarios", "osint", "simulador", "mirofish", "agents", "rag"],
  },
  {
    id: "conhecimento",
    label: "Conhecimento e conteúdos",
    hint: "Office, documentos, email, visualizador, sentimento e ontologia",
    ids: ["office", "docs", "email", "visualizador", "sentimento", "ontology"],
  },
  {
    id: "relatorios",
    label: "Relatórios",
    hint: "Relatórios a pedido (pagamento MB Way) e o estúdio onde a equipa os cria, gera em PDF e publica com preço",
    ids: ["reports", "report-studio"],
  },
  {
    id: "noticias",
    label: "Notícias e feeds",
    hint: "Leitor de RSS e índice de notícias: recolher e procurar por ticker, tema e tom",
    ids: ["rss", "noticias"],
  },
  {
    id: "comercio",
    label: "Comércio",
    hint: "Loja online: catálogo, encomendas e clientes",
    ids: ["shop"],
  },
  {
    id: "recolha",
    label: "Recolha de dados",
    hint: "Recolha de sites, templates, execuções, agenda, Arquivo.pt e diretórios de empresas",
    ids: ["scraper", "scraper-templates", "scraper-execucoes", "scraper-pesquisa", "scraper-agenda", "arquivo", "racius", "empresas-recolha"],
  },
  {
    id: "social",
    label: "Redes sociais",
    hint: "Canais, execuções, modelos, agenda e estado",
    ids: ["social", "social-canais", "social-execucoes", "social-modelos", "social-agenda", "social-estado"],
  },
];

const APP_INDEX: Map<string, DockApp> = new Map(DOCK_CATALOG.map((app) => [app.id, app]));

/** Aplicação do catálogo por identificador (o menu tira daqui ícone e etiqueta). */
export function dockAppById(id: string): DockApp | undefined {
  return APP_INDEX.get(id);
}

const fromApp = (app: DockApp): SidebarModule => ({ id: app.id, label: app.label, hint: app.hint });

/**
 * Módulos da barra lateral, agrupados como o utilizador os vê:
 * aplicações **por módulo** → áreas de CRM → ferramentas.
 */
export function sidebarCatalog(): SidebarModuleGroup[] {
  const crmViews = new Set(CRM_VIEW_IDS);
  const excluded = (id: string) => TOOL_APP_IDS.includes(id) || crmViews.has(id);

  const used = new Set<string>();
  const groups: SidebarModuleGroup[] = [];
  for (const module of APP_MODULES) {
    const items = module.ids
      .filter((id) => !excluded(id))
      .map((id) => APP_INDEX.get(id))
      .filter((app): app is DockApp => Boolean(app))
      .map(fromApp);
    if (items.length === 0) continue;
    items.forEach((item) => used.add(item.id));
    groups.push({ id: `app-${module.id}`, label: module.label, hint: module.hint, kind: "apps", items });
  }

  /* Aplicações que ainda não pertencem a nenhum módulo: mostram-se à parte, em
     vez de desaparecerem do menu (e a administração pode escondê-las). */
  const others = DOCK_CATALOG.filter((app) => !used.has(app.id) && !excluded(app.id)).map(fromApp);
  if (others.length > 0) {
    groups.push({
      id: "app-outras",
      label: "Outras aplicações",
      hint: "Aplicações ainda sem módulo atribuído",
      kind: "apps",
      items: others,
    });
  }

  groups.push(
    ...CRM_SUITE_GROUPS.map((group) => ({
      id: `crm-${group.id}`,
      label: group.id === "visao" ? "CRM" : `CRM · ${group.label}`,
      hint: group.hint,
      kind: "crm" as const,
      items: group.sections.map((section) => ({
        id: section.view,
        label: section.label,
        hint: section.hint,
      })),
    })),
  );

  groups.push({
    id: "tools",
    label: "Ferramentas",
    hint: "Elasticsearch, importação, terminal, definições, administração e correio da plataforma",
    kind: "tools",
    items: DOCK_CATALOG.filter((app) => TOOL_APP_IDS.includes(app.id)).map(fromApp),
  });

  return groups;
}

/** Todos os módulos da barra lateral (grupos + itens). */
export function sidebarModules(): SidebarModule[] {
  return sidebarCatalog().flatMap((group) => group.items);
}
