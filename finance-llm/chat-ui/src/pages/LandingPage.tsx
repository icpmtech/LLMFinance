/**
 * Landing page pública do IQ OS.
 *
 * Apresenta a plataforma, as principais famílias de ferramentas e os caminhos
 * para criar conta ou iniciar sessão. É a primeira página vista por utilizadores
 * anónimos em `/`.
 */
import {
  ArrowRight,
  BarChart3,
  Bot,
  Building2,
  FileText,
  Globe,
  Layers,
  Lock,
  Mail,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import { TawkChat } from "../components/TawkChat";

const CATEGORIES = [
  {
    icon: TrendingUp,
    title: "Mercados e previsões",
    description:
      "Cotações em tempo real, histórico de preços, indicadores técnicos, sentimento de notícias e pipelines ARIMA e Kronos para previsão.",
    examples: ["Cotações", "Sentimento", "ARIMA", "Kronos"],
  },
  {
    icon: Building2,
    title: "Contratos e empresas",
    description:
      "Pesquise e analise mais de 2 milhões de contratos públicos de Portugal, Espanha e França. Fichas de empresa, marcas, firmas e relações adjudicante ↔ adjudicatário.",
    examples: ["Contratos PT", "PLACSP", "DECP", "EmpresasIQ"],
  },
  {
    icon: Search,
    title: "Pesquisa e investigação",
    description:
      "Pesquisa total sobre todos os âmbitos, Search360 com dossiês de tema, Hermes para respostas citadas e Researcher para relatórios com audit trail.",
    examples: ["Pesquisa", "Search360", "Hermes", "Researcher"],
  },
  {
    icon: Bot,
    title: "Assistentes de IA",
    description:
      "Chat com Jarvis, agentes dinâmicos configuráveis, RAG sobre os seus documentos e integração com LLMs locais ou via API.",
    examples: ["Jarvis", "Agentes", "RAG", "Skills"],
  },
  {
    icon: Layers,
    title: "Visualização e dados",
    description:
      "Dashboards interativos, gráfos de entidades, mapas geográficos, Sankey, treemaps e um visualizador analítico para explorar os dados.",
    examples: ["Dashboards", "Grafos", "Mapas", "Visualizador"],
  },
  {
    icon: Users,
    title: "Gestão comercial",
    description:
      "CRM integrado com as entidades do cadastro, agenda comercial, oportunidades e pipelines. Ligue contas a NIFs e acompanhe contratos.",
    examples: ["CRM", "Contas", "Oportunidades", "Agenda"],
  },
];

const FEATURES = [
  { icon: ShieldCheck, title: "Conta segura", text: "Palavra-passe derivada com scrypt e sessões auditáveis." },
  { icon: Globe, title: "Multi-país", text: "Dados de Portugal, Espanha e França numa só plataforma." },
  { icon: BarChart3, title: "Pronto a analisar", text: "Indicadores e agregações calculados automaticamente." },
  { icon: Lock, title: "Privacidade", text: "As contas e sessões são guardadas no Elasticsearch privado." },
];

export function LandingPage() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-background text-foreground">
      <div className="orbit-bg pointer-events-none absolute inset-0 opacity-80" aria-hidden="true" />

      {/* Header */}
      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 via-teal-500 to-blue-600 text-white shadow-lg shadow-teal-500/25">
            <Sparkles size={20} />
          </span>
          <div>
            <p className="text-lg font-semibold leading-tight">IQ OS</p>
            <p className="text-xs text-muted-foreground">Plataforma de inteligência financeira · Sabemos Studio</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <a
            href="/login"
            className="hidden rounded-xl px-4 py-2 text-sm font-medium text-muted-foreground transition hover:text-foreground sm:inline-block"
          >
            Entrar
          </a>
          <a
            href="/register"
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70"
          >
            Criar conta
            <ArrowRight size={15} />
          </a>
        </div>
      </header>

      <main className="relative z-10">
        {/* Hero */}
        <section className="mx-auto max-w-6xl px-4 pb-12 pt-6 sm:pb-16 sm:pt-10 lg:pb-20 lg:pt-14">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="text-4xl font-semibold leading-tight sm:text-5xl lg:text-6xl">
              Toda a informação de mercados e contratação pública,{" "}
              <span className="text-glow-teal text-teal-300">com IA a ajudar a decidir.</span>
            </h1>
            <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
              Sabemos Studio apresenta o IQ OS: cotações, contratos públicos, empresas, notícias e ferramentas de IA num
              único espaço de trabalho. Crie uma conta gratuita e comece a explorar.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a
                href="/register"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-6 py-3 text-base font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70 sm:w-auto"
              >
                Criar conta gratuita
                <ArrowRight size={18} />
              </a>
              <a
                href="/login"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-base font-medium text-foreground transition hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70 sm:w-auto"
              >
                Já tenho conta
              </a>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              A palavra-passe é derivada com scrypt e nunca é guardada em texto simples.
            </p>
          </div>
        </section>

        {/* Tools grid */}
        <section className="mx-auto max-w-6xl px-4 pb-16 sm:pb-20">
          <div className="text-center">
            <h2 className="text-2xl font-semibold sm:text-3xl">Ferramentas do IQ OS, por Sabemos Studio</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
              Escolha a área que quer explorar. Cada módulo liga-se aos mesmos dados, para não perder contexto.
            </p>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CATEGORIES.map((category) => {
              const Icon = category.icon;
              return (
                <div
                  key={category.title}
                  className="glass-card flex flex-col gap-4 rounded-2xl p-5 transition hover:border-white/15 hover:bg-white/[0.03]"
                >
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal-400/15 text-teal-300">
                    <Icon size={20} />
                  </span>
                  <div>
                    <h3 className="text-base font-semibold">{category.title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{category.description}</p>
                  </div>
                  <div className="mt-auto flex flex-wrap gap-2">
                    {category.examples.map((example) => (
                      <span
                        key={example}
                        className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground"
                      >
                        {example}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* How to access */}
        <section className="border-y border-white/5 bg-white/[0.02] py-14 sm:py-20">
          <div className="mx-auto max-w-6xl px-4">
            <div className="grid gap-10 lg:grid-cols-2 lg:items-center">
              <div>
                <h2 className="text-2xl font-semibold sm:text-3xl">Como aceder ao IQ OS, da Sabemos Studio</h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  A plataforma da Sabemos Studio funciona no browser, sem instalação. Crie uma conta em segundos e aceda a
                  todos os módulos a partir da barra lateral ou do dock.
                </p>
                <ul className="mt-6 space-y-4">
                  <li className="flex items-start gap-3">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-teal-400/15 text-teal-300 text-xs font-semibold">
                      1
                    </span>
                    <span className="text-sm text-muted-foreground">
                      <strong className="text-foreground">Crie uma conta</strong> com email e palavra-passe. O registo
                      é imediato e a conta fica ativa de seguida.
                    </span>
                  </li>
                  <li className="flex items-start gap-3">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-teal-400/15 text-teal-300 text-xs font-semibold">
                      2
                    </span>
                    <span className="text-sm text-muted-foreground">
                      <strong className="text-foreground">Inicie sessão</strong> em qualquer dispositivo. As suas
                      preferências e pastas sincronizam automaticamente.
                    </span>
                  </li>
                  <li className="flex items-start gap-3">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-teal-400/15 text-teal-300 text-xs font-semibold">
                      3
                    </span>
                    <span className="text-sm text-muted-foreground">
                      <strong className="text-foreground">Explore os módulos</strong>: mercados, contratos, empresas,
                      pesquisa, IA, CRM e visualizadores.
                    </span>
                  </li>
                </ul>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <a
                    href="/register"
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110"
                  >
                    <Sparkles size={16} />
                    Começar agora
                  </a>
                  <a
                    href="/login"
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-5 py-2.5 text-sm font-medium text-foreground transition hover:bg-white/10"
                  >
                    <Mail size={16} />
                    Entrar com email
                  </a>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                {FEATURES.map((feature) => {
                  const Icon = feature.icon;
                  return (
                    <div
                      key={feature.title}
                      className="glass-card flex flex-col gap-3 rounded-2xl p-4"
                    >
                      <Icon size={18} className="text-teal-300" />
                      <div>
                        <p className="text-sm font-medium">{feature.title}</p>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{feature.text}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {/* Modules preview */}
        <section className="mx-auto max-w-6xl px-4 py-14 sm:py-20">
          <div className="text-center">
            <h2 className="text-2xl font-semibold sm:text-3xl">Outras ferramentas disponíveis na Sabemos Studio</h2>
            <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">
              Além dos módulos principais, o IQ OS inclui ferramentas especializadas para recolha, análise e gestão de
              informação.
            </p>
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { icon: FileText, label: "Office", desc: "Documentos e dossiês guardados" },
              { icon: Mail, label: "Email", desc: "Contas de correio integradas" },
              { icon: Globe, label: "World", desc: "Entidades globais e LEI" },
              { icon: Search, label: "Scraper", desc: "Recolha de fontes web" },
              { icon: FileText, label: "CMS", desc: "Páginas e blog" },
              { icon: Layers, label: "Loja", desc: "Catálogo de produtos" },
              { icon: FileText, label: "RSS", desc: "Leitor de feeds" },
              { icon: FileText, label: "Documentos API", desc: "Swagger e documentação" },
            ].map((tool) => {
              const Icon = tool.icon;
              return (
                <div
                  key={tool.label}
                  className="glass-card flex items-center gap-3 rounded-xl p-3 transition hover:border-white/15 hover:bg-white/[0.03]"
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/5 text-muted-foreground">
                    <Icon size={16} />
                  </span>
                  <div>
                    <p className="text-sm font-medium">{tool.label}</p>
                    <p className="text-xs text-muted-foreground">{tool.desc}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto max-w-6xl px-4 pb-16 pt-4 sm:pb-20">
          <div className="glass-modal gradient-border rounded-3xl p-8 text-center sm:p-10">
            <h2 className="text-2xl font-semibold sm:text-3xl">Experimente o IQ OS da Sabemos Studio hoje</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
              Crie a sua conta gratuita e aceda a mercados, contratos, empresas e IA num só sítio.
            </p>
            <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a
                href="/register"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-6 py-3 text-base font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 sm:w-auto"
              >
                Criar conta
                <ArrowRight size={18} />
              </a>
              <a
                href="/login"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-base font-medium text-foreground transition hover:bg-white/10 sm:w-auto"
              >
                Entrar
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/5 py-6">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 sm:flex-row">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Sparkles size={16} className="text-teal-300" />
            <span>Sabemos Studio · IQ OS — Plataforma de Inteligência Financeira</span>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <a href="/login" className="transition hover:text-foreground">
              Entrar
            </a>
            <a href="/register" className="transition hover:text-foreground">
              Criar conta
            </a>
          </div>
        </div>
      </footer>

      {/* Apoio ao cliente (Tawk.to) — só na landing page pública. */}
      <TawkChat />
    </div>
  );
}

export default LandingPage;
