/**
 * **Empresas & Risco** — nível de risco por empresa com ML + IA.
 *
 * Quatro leituras da mesma pergunta («que empresas olhar primeiro e porquê?»):
 *
 * 1. **Pesquisa** — motor de busca de empresas (nome, marca ou NIF) com o risco
 *    de cada uma e o que o sustenta;
 * 2. **Dossiê 360** — risco completo (réguas de CPV + anomalia ML), contratos
 *    associados com risco por contrato, relações e parecer por IA;
 * 3. **Comparar** — risco lado a lado, cruzamentos (compradores, pessoas,
 *    processos, CPV) e rede do conjunto;
 * 4. **Grafos 360** — grafo analítico da empresa (compradores, órgãos sociais,
 *    empresas ligadas, CIRE) desenhado a pedido.
 *
 * O `cartao_modelo` (`/risco/meta`) tem separador próprio porque um número de
 * risco sem os pressupostos à vista não se pode usar.
 */
import { useCallback, useEffect, useState } from "react";
import { Gauge, Info, Network, Scale, Search, ShieldAlert } from "lucide-react";

import { getRiscoMeta } from "../riscoApi";
import type { RiscoMeta, RiscoPesquisaItem } from "../riscoApi";
import { EmptyState, Loading, SectionCard } from "../components/padroes/padroesKit";
import { RiscoComparar } from "../components/risco/RiscoComparar";
import { RiscoDossie } from "../components/risco/RiscoDossie";
import { RiscoGrafos } from "../components/risco/RiscoGrafos";
import { RiscoPesquisa } from "../components/risco/RiscoPesquisa";
import { riscoCor } from "../components/risco/riscoKit";

type Tab = "pesquisa" | "dossie" | "comparar" | "grafos" | "modelo";

const TABS: { id: Tab; label: string; icon: typeof Search }[] = [
  { id: "pesquisa", label: "Pesquisar empresas", icon: Search },
  { id: "dossie", label: "Dossiê 360", icon: ShieldAlert },
  { id: "comparar", label: "Comparar empresas", icon: Scale },
  { id: "grafos", label: "Grafos analíticos", icon: Network },
  { id: "modelo", label: "Modelo de risco", icon: Gauge },
];

type Alvo = { nif: string; nome: string; pais: string };

/** Lê `?tab=…&nif=…` do URL (a app tem router manual, sem react-router). */
function lerUrl(): { tab: Tab; alvo: Alvo | null } {
  if (typeof window === "undefined") return { tab: "pesquisa", alvo: null };
  const parametros = new URLSearchParams(window.location.search);
  const pedido = parametros.get("tab");
  const tab = (TABS.some((item) => item.id === pedido) ? pedido : "pesquisa") as Tab;
  const nif = parametros.get("nif");
  if (!nif) return { tab, alvo: null };
  return {
    tab,
    alvo: { nif, pais: parametros.get("pais") || "PT", nome: parametros.get("nome") || nif },
  };
}

export default function RiscoPage() {
  const [{ tab: tabInicial, alvo: alvoInicial }] = useState(lerUrl);
  const [tab, setTab] = useState<Tab>(tabInicial);
  const [empresa, setEmpresa] = useState<Alvo | null>(alvoInicial);
  const [selecionadas, setSelecionadas] = useState<Alvo[]>([]);
  const [alvosComparar, setAlvosComparar] = useState<Alvo[]>([]);
  const [empresaGrafo, setEmpresaGrafo] = useState<Alvo | null>(null);
  const [meta, setMeta] = useState<RiscoMeta | null>(null);
  const [erroMeta, setErroMeta] = useState("");

  useEffect(() => {
    let cancelado = false;
    getRiscoMeta()
      .then((resposta) => {
        if (!cancelado) setMeta(resposta);
      })
      .catch((exc: unknown) => {
        if (!cancelado) setErroMeta(exc instanceof Error ? exc.message : "Não foi possível obter o cartão do modelo.");
      });
    return () => {
      cancelado = true;
    };
  }, []);

  // A vista vive na query string (`?tab=…&nif=…`): partilhar o link abre o mesmo dossiê.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const proximo = new URLSearchParams();
    proximo.set("tab", tab);
    if (tab === "dossie" && empresa) {
      proximo.set("nif", empresa.nif);
      proximo.set("pais", empresa.pais);
      proximo.set("nome", empresa.nome);
    }
    const caminho = `${window.location.pathname}?${proximo.toString()}`;
    if (`${window.location.pathname}${window.location.search}` !== caminho) {
      window.history.replaceState({}, "", caminho);
    }
  }, [tab, empresa]);

  const abrirDossie = useCallback((item: Alvo) => {
    setEmpresa(item);
    setTab("dossie");
  }, []);

  const alternarSelecionada = useCallback((item: RiscoPesquisaItem) => {
    const alvo: Alvo = { nif: item.nif, nome: item.nome, pais: item.pais || "PT" };
    setSelecionadas((atual) =>
      atual.some((entrada) => entrada.nif === alvo.nif && entrada.pais === alvo.pais)
        ? atual.filter((entrada) => !(entrada.nif === alvo.nif && entrada.pais === alvo.pais))
        : [...atual, alvo],
    );
  }, []);

  const irParaComparar = useCallback((alvos: Alvo[]) => {
    setAlvosComparar(alvos);
    setTab("comparar");
  }, []);

  const irParaGrafo = useCallback((item: Alvo) => {
    setEmpresaGrafo(item);
    setTab("grafos");
  }, []);

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <ShieldAlert size={24} className="text-teal-300" />
              Empresas &amp; Risco
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Nível de risco por empresa adjudicatária (0–100) a partir de regras calibradas nos dados e de modelos de
              ML sobre empresas comparáveis, com contratos associados, comparação de várias empresas, grafos analíticos
              360 e parecer por IA.
            </p>
          </div>
          {meta && (
            <div className="glass-card rounded-2xl px-3 py-2 text-[11px] text-muted-foreground">
              <p>
                Modelo <span className="font-mono text-foreground">{meta.cartao_modelo.versao}</span> ·{" "}
                {meta.ml.disponivel ? `ML: ${meta.ml.algoritmos.length} algoritmos` : "ML indisponível"}
              </p>
              <p className="mt-0.5">
                {meta.cartao_modelo.componentes.length} componentes · {meta.metodos ? Object.keys(meta.metodos).length : 0} métodos
              </p>
            </div>
          )}
        </header>

        <nav className="mb-5 flex flex-wrap gap-2" aria-label="Secções do módulo">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              aria-current={tab === id ? "page" : undefined}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                tab === id ? "glass-card border-teal-400/25 bg-teal-400/10 text-teal-200" : "glass-card text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon size={15} />
              {label}
              {id === "comparar" && selecionadas.length > 0 && (
                <span className="rounded-full bg-teal-400/20 px-1.5 text-[11px] text-teal-200">{selecionadas.length}</span>
              )}
            </button>
          ))}
        </nav>

        {tab === "pesquisa" && (
          <RiscoPesquisa
            onAbrir={(item) => abrirDossie({ nif: item.nif, nome: item.nome, pais: item.pais || "PT" })}
            selecionadas={selecionadas.map((item) => `${item.pais}:${item.nif}`)}
            onAlternarSelecionada={alternarSelecionada}
            onComparar={(item) => irParaComparar([{ nif: item.nif, nome: item.nome, pais: item.pais || "PT" }])}
            onCompararSelecionadas={() => irParaComparar(selecionadas)}
          />
        )}

        {tab === "dossie" && !empresa && (
          <EmptyState>
            Escolha uma empresa no separador <strong>Pesquisar empresas</strong> para abrir o dossiê 360.
          </EmptyState>
        )}

        {tab === "dossie" && empresa && (
          <RiscoDossie
            key={`${empresa.pais}:${empresa.nif}`}
            nif={empresa.nif}
            pais={empresa.pais}
            onVoltar={() => setTab("pesquisa")}
            onComparar={(nif, pais) => irParaComparar([{ nif, nome: empresa.nome, pais }])}
            onGrafo={(nif, pais) => irParaGrafo({ nif, nome: empresa.nome, pais })}
          />
        )}

        {tab === "comparar" && <RiscoComparar iniciais={alvosComparar.length ? alvosComparar : selecionadas} />}

        {tab === "grafos" && <RiscoGrafos empresa={empresaGrafo} />}

        {tab === "modelo" && (
          <div className="space-y-4">
            {erroMeta && <EmptyState tone="warn">{erroMeta}</EmptyState>}
            {!meta && !erroMeta && <Loading label="A carregar o cartão do modelo…" />}
            {meta && (
              <>
                <SectionCard title="Como se calcula o risco" subtitle={meta.cartao_modelo.rotulo} icon={Info}>
                  <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-400/[0.07] p-3 text-xs text-amber-100">
                    {meta.cartao_modelo.aviso}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[860px] border-collapse text-left text-sm">
                      <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                        <tr>
                          <th className="pb-2 pr-3">Componente</th>
                          <th className="pb-2 pr-3">Peso</th>
                          <th className="pb-2 pr-3">A 0 pontos</th>
                          <th className="pb-2 pr-3">A 100 pontos</th>
                          <th className="pb-2 pr-3">Método</th>
                        </tr>
                      </thead>
                      <tbody>
                        {meta.cartao_modelo.componentes.map((item) => (
                          <tr key={item.id} className="border-t border-white/[0.06] align-top">
                            <td className="py-2 pr-3">
                              <span>{item.label}</span>
                              <span className="block text-[11px] text-muted-foreground">{item.descricao}</span>
                            </td>
                            <td className="py-2 pr-3 whitespace-nowrap font-mono">{Math.round(item.peso * 100)}%</td>
                            <td className="py-2 pr-3 whitespace-nowrap font-mono text-muted-foreground">
                              {item.limiar_zero} {item.unidade}
                            </td>
                            <td className="py-2 pr-3 whitespace-nowrap font-mono text-muted-foreground">
                              {item.limiar_saturacao} {item.unidade}
                            </td>
                            <td className="py-2 pr-3 text-[11px] text-muted-foreground">{item.metodo}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </SectionCard>

                <div className="grid gap-4 lg:grid-cols-2">
                  <SectionCard title="Faixas de risco" subtitle="Onde caem os scores 0–100" icon={Gauge}>
                    <ul className="space-y-2">
                      {meta.cartao_modelo.niveis.map((nivel, indice) => {
                        const anterior = indice === 0 ? 0 : meta.cartao_modelo.niveis[indice - 1].max;
                        const topo = Math.min(100, nivel.max);
                        return (
                          <li key={nivel.id} className="flex items-center gap-3">
                            <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: nivel.cor || riscoCor(nivel.id) }} />
                            <span className="w-36 shrink-0 text-sm">{nivel.label}</span>
                            <span className="font-mono text-[11px] text-muted-foreground">
                              {anterior}–{topo}
                            </span>
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
                              <span
                                className="block h-full rounded-full"
                                style={{ width: `${topo - anterior}%`, backgroundColor: nivel.cor || riscoCor(nivel.id) }}
                              />
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </SectionCard>

                  <SectionCard title="Machine learning e IA" subtitle="O que o número usa e o que a IA acrescenta" icon={Info}>
                    <ul className="space-y-2 text-xs">
                      <li>
                        <span className="text-muted-foreground">Biblioteca: </span>
                        {meta.ml.biblioteca || "scikit-learn indisponível (só regras)"}
                      </li>
                      <li>
                        <span className="text-muted-foreground">Algoritmos: </span>
                        {meta.ml.algoritmos.join("; ")}
                      </li>
                      <li>
                        <span className="text-muted-foreground">Features do modelo de anomalia: </span>
                        {meta.ml.features.join(", ")}
                      </li>
                      <li>
                        <span className="text-muted-foreground">Risco por contrato: </span>
                        severidade das regras + aditivo + valor atípico (σ por CPV) + ajuste direto sem concorrência +
                        transparência tardia
                      </li>
                      <li>
                        <span className="text-muted-foreground">IA: </span>
                        {String((meta.ia as Record<string, unknown>)?.ontology_ai ?? false) === "true" || (meta.ia as Record<string, unknown>)?.ask_model
                          ? "o parecer é escrito pelo modelo configurado (nunca altera o score); sem modelo, sai factual"
                          : "sem modelo configurado — o parecer sai factual"}
                      </li>
                      <li>
                        <span className="text-muted-foreground">Fontes: </span>
                        {meta.fontes.join("; ")}
                      </li>
                      <li>
                        <span className="text-muted-foreground">Cache: </span>
                        {Math.round((meta.cache?.ttl_segundos || 0) / 60)} min · {meta.cache?.entradas ?? 0} entradas
                      </li>
                    </ul>
                  </SectionCard>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
