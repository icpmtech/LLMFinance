/**
 * **ESG · Sustentabilidade** — score por empresa, evolução, carteira de
 * fornecedores e fontes.
 *
 * Quatro leituras:
 *
 * 1. **Painel** — médias por pilar, distribuições e destaques;
 * 2. **Empresas** — ranking e pesquisa (a primeira consulta calcula e guarda);
 * 3. **Taxonomia UE** — elegibilidade face aos seis objetivos ambientais,
 *    atividades do Compass, DNSH e salvaguardas mínimas;
 * 4. **Carteira** — análise ESG de um conjunto de fornecedores;
 * 5. **Modelo e fontes** — pesos, limiares, catálogo GRI/ESRS, ODS e Taxonomia UE.
 *
 * O dossiê de uma empresa abre num separador próprio e vive na query string
 * (`?tab=dossie&nif=…&pais=…`), para o link poder ser partilhado.
 */
import { useCallback, useEffect, useState } from "react";
import { BarChart3, Leaf, Search, Users, BookOpen, Gauge, Landmark } from "lucide-react";

import { getEsgMeta } from "../esgApi";
import type { EsgEmpresaResumo, EsgMeta } from "../esgApi";
import { EsgCarteiraPage } from "../components/esg/EsgCarteira";
import { EsgDossie } from "../components/esg/EsgDossie";
import { EsgEmpresas } from "../components/esg/EsgEmpresas";
import { EsgModelo } from "../components/esg/EsgModelo";
import { EsgPainel } from "../components/esg/EsgPainel";
import { EsgTaxonomia } from "../components/esg/EsgTaxonomia";
import { EmptyState, Loading } from "../components/padroes/padroesKit";

type Aba = "painel" | "empresas" | "taxonomia" | "carteira" | "modelo" | "dossie";

const ABAS: { id: Aba; label: string; icon: typeof BarChart3 }[] = [
  { id: "painel", label: "Painel", icon: BarChart3 },
  { id: "empresas", label: "Empresas", icon: Search },
  { id: "taxonomia", label: "Taxonomia UE", icon: Landmark },
  { id: "carteira", label: "Carteira de fornecedores", icon: Users },
  { id: "modelo", label: "Modelo e fontes", icon: BookOpen },
];

type Alvo = { nif: string; nome: string; pais: string };

function lerUrl(): { tab: Aba; alvo: Alvo | null } {
  if (typeof window === "undefined") return { tab: "painel", alvo: null };
  const params = new URLSearchParams(window.location.search);
  const pedido = params.get("tab");
  const tab = (["painel", "empresas", "taxonomia", "carteira", "modelo", "dossie"].includes(String(pedido)) ? pedido : "painel") as Aba;
  const nif = params.get("nif");
  if (!nif) return { tab, alvo: null };
  return { tab: "dossie", alvo: { nif, nome: params.get("nome") || nif, pais: params.get("pais") || "PT" } };
}

export default function EsgPage() {
  const [{ tab: tabInicial, alvo: alvoInicial }] = useState(lerUrl);
  const [tab, setTab] = useState<Aba>(tabInicial);
  const [alvo, setAlvo] = useState<Alvo | null>(alvoInicial);
  const [meta, setMeta] = useState<EsgMeta | null>(null);
  const [erroMeta, setErroMeta] = useState("");

  useEffect(() => {
    let cancelado = false;
    getEsgMeta()
      .then((resposta) => {
        if (!cancelado) setMeta(resposta);
      })
      .catch((exc: unknown) => {
        if (!cancelado) setErroMeta(exc instanceof Error ? exc.message : "Não foi possível carregar o cartão do modelo ESG.");
      });
    return () => {
      cancelado = true;
    };
  }, []);

  // A vista vive na query string: partilhar o link abre o mesmo dossiê.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    params.set("tab", tab);
    if (tab === "dossie" && alvo) {
      params.set("nif", alvo.nif);
      params.set("pais", alvo.pais);
      params.set("nome", alvo.nome);
    }
    const caminho = `${window.location.pathname}?${params.toString()}`;
    if (`${window.location.pathname}${window.location.search}` !== caminho) {
      window.history.replaceState({}, "", caminho);
    }
  }, [tab, alvo]);

  const abrir = useCallback((item: EsgEmpresaResumo) => {
    setAlvo({ nif: item.nif, nome: item.nome, pais: item.pais || "PT" });
    setTab("dossie");
  }, []);

  const abrirPorNif = useCallback((nif: string, nome: string, pais: string) => {
    setAlvo({ nif, nome, pais });
    setTab("dossie");
  }, []);

  const total = meta?.status?.indices?.["finance_esg_empresas"]?.total ?? 0;

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <Leaf size={24} className="text-emerald-300" />
              ESG · Sustentabilidade
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Score ESG por empresa (0–100) nas vertentes Ambiente, Social e Governação, com cobertura e confiança, série de três anos,
              benchmark de setor e dimensão, indicadores dos relatórios de sustentabilidade, análise da carteira de fornecedores e
              elegibilidade face à Taxonomia Europeia (com DNSH e salvaguardas mínimas por verificar).
            </p>
          </div>
          {meta && (
            <div className="glass-card rounded-2xl px-3 py-2 text-[11px] text-muted-foreground">
              <p>
                Modelo <span className="font-mono text-foreground">{meta.cartao_modelo.versao}</span> · {meta.cartao_modelo.pilares.length} pilares
              </p>
              <p className="mt-0.5">
                {total.toLocaleString("pt-PT")} empresa(s) com fotografia · {meta.indicadores.length} indicadores catalogados
              </p>
            </div>
          )}
        </header>

        {erroMeta && <EmptyState tone="warn">{erroMeta}</EmptyState>}

        <nav className="mb-5 flex flex-wrap gap-2" aria-label="Secções do módulo">
          {ABAS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              aria-current={tab === id ? "page" : undefined}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                tab === id ? "glass-card border-emerald-400/25 bg-emerald-400/10 text-emerald-200" : "glass-card text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
          {tab === "dossie" && alvo && (
            <span className="flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">
              <Gauge size={15} />
              {alvo.nome}
            </span>
          )}
        </nav>

        {!meta && !erroMeta && <Loading label="A carregar o cartão do modelo ESG…" />}

        {meta && tab === "painel" && <EsgPainel meta={meta} onAbrir={abrir} />}
        {meta && tab === "empresas" && <EsgEmpresas meta={meta} onAbrir={abrir} />}
        {meta && tab === "taxonomia" && <EsgTaxonomia meta={meta} />}
        {meta && tab === "carteira" && <EsgCarteiraPage onAbrir={(nif, nome) => abrirPorNif(nif, nome, "PT")} />}
        {meta && tab === "modelo" && <EsgModelo meta={meta} />}
        {meta && tab === "dossie" && alvo && (
          <EsgDossie
            nif={alvo.nif}
            pais={alvo.pais}
            nome={alvo.nome}
            meta={meta}
            onVoltar={() => setTab("empresas")}
            onAbrirEmpresa={abrirPorNif}
          />
        )}
        {meta && tab === "dossie" && !alvo && (
          <EmptyState>
            Escolha uma empresa no separador <strong>Empresas</strong> para abrir o dossiê ESG.
          </EmptyState>
        )}
      </div>
    </div>
  );
}
