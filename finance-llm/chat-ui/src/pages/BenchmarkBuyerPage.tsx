/**
 * **Grafo de relações do benchmark** — `/benchmark/comprador` e `/benchmark/vendedor`.
 *
 * O mesmo desenho radial visto dos dois lados, com a prop `perspectiva`:
 *
 * - **comprador** (`/benchmark/comprador`) — a entidade compra: primeiro anel de
 *   **fornecedores** (dependência desse fornecedor face a este comprador, preço
 *   face à mediana, clientes que tem, CPV cobertos) e segundo anel de
 *   **clientes em comum** (quem mais lhe compra);
 * - **vendedor** (`/benchmark/vendedor`) — a entidade vende: primeiro anel de
 *   **compradores** (peso de cada um no meu volume, a minha quota nas compras
 *   dele, o meu preço face à mediana, quantos fornecedores lhe vendem) e segundo
 *   anel de **concorrentes** que vendem a esses mesmos compradores.
 *
 * Três formas de olhar para os mesmos dados, todas navegáveis:
 *
 * - **grafo** radial (entidade → primeiro anel → segundo anel);
 * - **mapa OSM** com as regiões onde a coisa acontece (compra ou venda);
 * - **tabela** do primeiro anel, com os sinais escritos por extenso.
 *
 * Cada empresa aparece com o seu **site e logótipo** (`/empresas/perfil`), para
 * se reconhecer a marca no grafo e nas listas. Clique num nó/linha/região para
 * ver os detalhes à direita; **botão direito** abre o menu de contexto com as
 * ações (benchmark da empresa, ficha, ontologia, mapa de contratos, copiar
 * identificador). Os rótulos vêm do servidor (`labels`), para o mesmo componente
 * servir as duas leituras.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeEuro,
  Building2,
  Copy,
  ExternalLink,
  FileText,
  GitCompare,
  HandCoins,
  Image as ImageIcon,
  Info,
  Landmark,
  Loader2,
  MapPin,
  Network,
  RefreshCw,
  Search,
  ShoppingCart,
  Users,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import BuyerGraph, { corDoScore, type BuyerNodeRef } from "../components/benchmark/BuyerGraph";
import BuyerMap, { type RegionPoint } from "../components/benchmark/BuyerMap";
import EmpresaLogo from "../components/benchmark/EmpresaLogo";
import { limparNome } from "../components/benchmark/texto";
import { siteDe, usePerfisEmpresas } from "../components/benchmark/usePerfisEmpresas";
import { resolverPerfisEmpresas } from "../empresasPerfil";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "../components/benchmark/ContextMenu";
import { CpvAutocomplete, EmpresaAutocomplete, SeletorAno, type EmpresaBenchmark } from "../components/benchmark/BenchmarkPickers";
import {
  getBenchmarkBuyerGraph,
  getBenchmarkMeta,
  getBenchmarkSellerGraph,
  type BenchmarkBuyerGraphResponse,
  type BenchmarkBuyerSupplier,
  type BenchmarkCountry,
  type BenchmarkMetaAll,
} from "../benchmarkApi";

const MAX_ANOS = 12;
const PAISES: BenchmarkCountry[] = ["pt", "es", "fr"];
const ROTULO_PAIS: Record<BenchmarkCountry, string> = { pt: "Portugal", es: "Espanha", fr: "França" };
const COR_PAIS: Record<BenchmarkCountry, string> = { pt: "text-emerald-300", es: "text-amber-300", fr: "text-sky-300" };

function money(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function moneyShort(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 10_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return money(valor);
}

function num(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT");
}

/** Índice de preço legível (rácios extremos são mix de produtos, não preço). */
function indicePreco(ratio?: number | null, marketMedian?: number | null): { texto: string; cor: string } {
  if (!ratio) return { texto: "sem valores comparáveis", cor: "text-muted-foreground" };
  const texto = ratio > 5 ? `› 5× mediana (${moneyShort(marketMedian)})` : `${ratio.toFixed(2)}× mediana`;
  if (ratio <= 0.8) return { texto, cor: "text-emerald-300" };
  if (ratio >= 1.25) return { texto, cor: "text-amber-300" };
  return { texto, cor: "text-muted-foreground" };
}

function Kpi({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex items-start gap-3">
        <span className="mt-0.5 text-muted-foreground">{icon}</span>
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="truncate text-lg font-semibold tabular-nums">{value}</p>
          {hint ? <p className="truncate text-xs text-muted-foreground">{hint}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default function BenchmarkBuyerPage({
  onSwitchView,
  perspectiva = "comprador",
}: {
  onSwitchView?: () => void;
  /**
   * De que lado se lê o grafo.
   *
   * - `comprador` — quem compra ao centro, fornecedores no primeiro anel e
   *   clientes comuns no segundo (`/benchmark/comprador`);
   * - `vendedor` — quem vende ao centro, **compradores** no primeiro anel e
   *   **concorrentes** no segundo (`/benchmark/vendedor`).
   *
   * O desenho, as tabelas e os menus são os mesmos; só muda a leitura dos nós.
   */
  perspectiva?: "comprador" | "vendedor";
}) {
  const vendedor = perspectiva === "vendedor";
  const [meta, setMeta] = useState<BenchmarkMetaAll | null>(null);
  const [pais, setPais] = useState<BenchmarkCountry>("pt");
  const [comprador, setComprador] = useState<EmpresaBenchmark | null>(null);
  const [cpv, setCpv] = useState("");
  const [anoDe, setAnoDe] = useState<number | "">("");
  const [anoAte, setAnoAte] = useState<number | "">("");
  const [dados, setDados] = useState<BenchmarkBuyerGraphResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [selecionado, setSelecionado] = useState<BuyerNodeRef | null>(null);
  const [regiaoAtiva, setRegiaoAtiva] = useState<string | null>(null);
  const { menu, abrir, fechar } = useContextMenu();

  const anos = useMemo(() => (meta?.years ?? []).slice(0, MAX_ANOS), [meta]);

  // Texto e rótulos que mudam com a perspetiva: o resto da página é igual.
  const t = useMemo(
    () =>
      vendedor
        ? {
            titulo: "Benchmark de quem vende",
            subtitulo:
              "A quem vendo, quanto pesa cada comprador, com quem disputo essas compras, a que preço vendo e onde — em grafo, mapa e tabela. Portugal, Espanha e França.",
            configTitulo: "Vendedor e segmento",
            entidadeLabel: "Vendedor (empresa que vende)",
            entidadeRole: "adjudicatario" as const,
            acao: "Analisar quem me compra",
            aCarregar: "A analisar compradores, concorrentes e regiões…",
            grafo: "Grafo de compradores",
            kpiMediana: "Mediana que pratico",
            tabela: "Compradores por peso nas minhas vendas",
            anel2: "Concorrentes (2º anel)",
            alternativas: "Compram o que vendo, mas nunca me compraram",
            mapa: "Onde vendo",
          }
        : {
            titulo: "Benchmark do comprador",
            subtitulo:
              "Fornecedores, forças e fraquezas de cada relação, clientes comuns e regiões de execução — em grafo, mapa e tabela. Portugal, Espanha e França.",
            configTitulo: "Comprador e segmento",
            entidadeLabel: "Comprador (entidade que compra)",
            entidadeRole: "adjudicante" as const,
            acao: "Analisar fornecedores",
            aCarregar: "A analisar fornecedores, clientes e regiões…",
            grafo: "Grafo de fornecedores",
            kpiMediana: "Mediana paga",
            tabela: "Fornecedores por peso na compra",
            anel2: "Clientes comuns (2º anel)",
            alternativas: "No mercado, mas nunca lhe venderam",
            mapa: "Regiões de execução",
          },
    [vendedor],
  );

  // Rótulos do grafo: vêm do servidor (`labels`) para as duas páginas falarem
  // a mesma língua; sem resposta ainda, usa-se o mesmo texto por omissão.
  const rot = dados?.labels ?? {
    entity: vendedor ? "Vendedor" : "Comprador",
    ring1: vendedor ? "Compradores" : "Fornecedores",
    ring2: vendedor ? "Concorrentes" : "Clientes em comum",
    ring1_one: vendedor ? "Comprador" : "Fornecedor",
    ring2_one: vendedor ? "Concorrente" : "Cliente",
    share: vendedor ? "Peso no meu volume" : "Quota no comprador",
    dependency: vendedor ? "A minha quota nas compras dele" : "Dependência deste comprador",
    count: vendedor ? "Fornecedores do comprador" : "Clientes no mercado",
    counterpart: vendedor ? "comprador" : "fornecedor",
    price: vendedor ? "O meu preço face ao mercado" : "Preço face à mediana do mercado",
    ring2_hint: "",
    regions_hint: "",
  };

  // Empresas do grafo (comprador, fornecedores e clientes): vai-se buscar o site
  // e o logótipo de cada uma — primeiro o que já está em cache no servidor, o
  // resto é resolvido em lotes pequenos (IA + scraper) e aparece à medida que chega.
  const { perfis, aResolver, progresso, erro: erroPerfis, repetir: repetirPerfis } = usePerfisEmpresas(
    useMemo(() => {
      if (!dados) return [];
      return [
        { nif: dados.buyer.nif, nome: dados.buyer.name, pais },
        ...dados.suppliers.map((linha) => ({ nif: linha.nif, nome: linha.name, pais })),
        ...dados.clients.map((linha) => ({ nif: linha.nif, nome: linha.name, pais })),
      ];
    }, [dados, pais]),
    { ativo: Boolean(dados), pais },
  );

  const analisar = useCallback(
    async (override?: { entidade?: EmpresaBenchmark | null; cpv?: string; pais?: BenchmarkCountry }) => {
      const alvo = override?.entidade ?? comprador;
      const codigo = override?.cpv ?? cpv;
      const paisAlvo = override?.pais ?? pais;
      if (!alvo) {
        setErro("Escolha primeiro o comprador.");
        return;
      }
      setACarregar(true);
      setErro(null);
      try {
        const comum = {
          nif: alvo.nif || undefined,
          name: alvo.name,
          country: paisAlvo,
          cpv_code: codigo.trim() || undefined,
          year_from: anoDe === "" ? undefined : Number(anoDe),
          year_to: anoAte === "" ? undefined : Number(anoAte),
        };
        const resultado = vendedor
          ? await getBenchmarkSellerGraph({ ...comum, top_buyers: 12, top_competitors: 8 })
          : await getBenchmarkBuyerGraph({ ...comum, top_suppliers: 12, top_clients: 8 });
        setDados(resultado.error ? null : resultado);
        setSelecionado(null);
        setRegiaoAtiva(null);
        if (resultado.error) setErro(resultado.error);
      } catch (err) {
        setDados(null);
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setACarregar(false);
      }
    },
    [comprador, cpv, pais, anoDe, anoAte, vendedor],
  );

  // Arranque: meta + parâmetros do URL (as ligações de outras páginas trazem
  // `pais`, `nif`, `name` e `cpv`).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const paisUrl = params.get("pais") as BenchmarkCountry | null;
    const nifUrl = params.get("nif") || "";
    const nomeUrl = params.get("name") || "";
    const cpvUrl = params.get("cpv") || "";
    if (paisUrl && PAISES.includes(paisUrl)) setPais(paisUrl);
    if (cpvUrl) setCpv(cpvUrl);
    getBenchmarkMeta("all")
      .then((resultado) => {
        setMeta(resultado);
        const recentes = (resultado.years ?? []).slice(0, MAX_ANOS);
        if (recentes.length) {
          setAnoDe(Math.min(...recentes));
          setAnoAte(Math.max(...recentes));
        }
        if (nifUrl || nomeUrl) {
          const alvo: EmpresaBenchmark = { nif: nifUrl, name: nomeUrl || nifUrl, contracts: 0 };
          setComprador(alvo);
          void analisar({ entidade: alvo, cpv: cpvUrl, pais: paisUrl && PAISES.includes(paisUrl) ? paisUrl : "pt" });
        }
      })
      .catch((err: unknown) => setErro(err instanceof Error ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const abrirBenchmarkDaEmpresa = (nif?: string | null, nome?: string, papel: "adjudicatario" | "adjudicante" = "adjudicatario", paisAlvo?: BenchmarkCountry) => {
    const caminho = `/benchmark/${(paisAlvo ?? pais) === "pt" ? "portugal" : (paisAlvo ?? pais) === "es" ? "espanha" : "franca"}`;
    const params = new URLSearchParams();
    if (nif) params.set("nif", nif);
    if (nome) params.set("name", nome);
    params.set("role", papel);
    if (cpv.trim()) params.set("cpv", cpv.trim());
    window.location.assign(`${caminho}?${params.toString()}`);
  };

  const abrirComprador = (nif?: string | null, nome?: string) => {
    const params = new URLSearchParams({ pais });
    if (nif) params.set("nif", nif);
    if (nome) params.set("name", nome);
    if (cpv.trim()) params.set("cpv", cpv.trim());
    window.location.assign(`/benchmark/comprador?${params.toString()}`);
  };

  const copiar = (texto: string) => {
    void navigator.clipboard?.writeText(texto);
  };

  // Saltar para a mesma empresa lida do outro lado da mesa: quem vende vê-se
  // como comprador (e vice-versa) com os mesmos filtros.
  const alternarPerspetiva = () => {
    const params = new URLSearchParams({ pais });
    const nif = dados?.buyer.nif || comprador?.nif || "";
    const nome = dados?.buyer.name || comprador?.name || "";
    if (nif) params.set("nif", nif);
    if (nome) params.set("name", nome);
    if (cpv.trim()) params.set("cpv", cpv.trim());
    window.location.assign(`${vendedor ? "/benchmark/comprador" : "/benchmark/vendedor"}?${params.toString()}`);
  };

  const itensDoFornecedor = (fornecedor: BenchmarkBuyerSupplier): ContextMenuItem[] => [
    {
      id: "detalhes",
      label: "Ver forças e fraquezas",
      icon: <Info size={13} />,
      onSelect: () => {
        setSelecionado({ kind: "supplier", supplier: fornecedor });
        fechar();
      },
    },
    {
      id: "site",
      label: siteDe(perfis, fornecedor) ? "Abrir o site da empresa" : "Descobrir o site da empresa",
      icon: <ExternalLink size={13} />,
      hint: siteDe(perfis, fornecedor)?.replace(/^https?:\/\//, "") || undefined,
      onSelect: () => {
        const site = siteDe(perfis, fornecedor);
        fechar();
        if (site) {
          window.open(site, "_blank", "noopener");
          return;
        }
        void resolverPerfisEmpresas([{ nif: fornecedor.nif, nome: fornecedor.name, pais }], { pais }).then(
          (resposta) => {
            const siteNovo = resposta.perfis?.[0]?.site;
            if (siteNovo) window.open(siteNovo, "_blank", "noopener");
          },
        );
      },
    },
    {
      id: "benchmark",
      label: "Benchmark desta empresa",
      icon: <GitCompare size={13} />,
      onSelect: () => {
        fechar();
        abrirBenchmarkDaEmpresa(fornecedor.nif, fornecedor.name, "adjudicatario");
      },
    },
    {
      id: "ficha",
      label: pais === "pt" ? "Abrir ficha da empresa" : "Abrir contratos do país",
      icon: <Building2 size={13} />,
      onSelect: () => {
        fechar();
        window.location.assign(pais === "pt" ? `/companies/${encodeURIComponent(fornecedor.nif)}` : `/banco-de-empresas`);
      },
    },
    {
      id: "ontologia",
      label: "Ver na Ontologia",
      icon: <Network size={13} />,
      onSelect: () => {
        fechar();
        window.location.assign("/ontology");
      },
    },
    { id: "copiar", label: "Copiar identificador", icon: <Copy size={13} />, hint: fornecedor.nif, onSelect: () => { copiar(fornecedor.nif); fechar(); } },
  ];

  const itensDaRegiao = (ponto: RegionPoint): ContextMenuItem[] => [
    {
      id: "ver",
      label: "Detalhe da região",
      icon: <MapPin size={13} />,
      onSelect: () => {
        setRegiaoAtiva(ponto.region.code);
        fechar();
      },
    },
    {
      id: "mapa",
      label: "Abrir o mapa de contratos",
      icon: <ExternalLink size={13} />,
      onSelect: () => {
        fechar();
        window.location.assign("/contracts/map");
      },
    },
    {
      id: "contratos",
      label: "Ver contratos deste comprador neste CPV",
      icon: <FileText size={13} />,
      disabled: !cpv.trim(),
      // Na página do vendedor o segmento é o meu: a leitura do comprador não
      // faz sentido aqui, por isso a opção só aparece a quem compra.
      hidden: vendedor,
      onSelect: () => {
        fechar();
        abrirComprador(dados?.buyer.nif, dados?.buyer.name);
      },
    },
    { id: "copiar", label: "Copiar código da região", icon: <Copy size={13} />, hint: ponto.region.code.slice(0, 14), onSelect: () => { copiar(ponto.region.code); fechar(); } },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            {vendedor ? <HandCoins size={22} className="text-emerald-400" /> : <ShoppingCart size={22} className="text-sky-400" />}
            {t.titulo}
          </h1>
          <p className="text-sm text-muted-foreground">{t.subtitulo}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {dados ? (
            <Button variant="outline" size="md" icon={<RefreshCw size={15} />} onClick={() => void analisar()} disabled={aCarregar}>
              Atualizar
            </Button>
          ) : null}
          <Button
            variant="outline"
            size="md"
            icon={vendedor ? <ShoppingCart size={15} /> : <HandCoins size={15} />}
            onClick={alternarPerspetiva}
          >
            {vendedor ? "Ver do lado de quem compra" : "Ver do lado de quem vende"}
          </Button>
          {onSwitchView ? (
            <Button variant="outline" size="md" onClick={onSwitchView}>
              Fechar
            </Button>
          ) : null}
        </div>
      </header>

      {/* ------------------------------------------------------ configurador */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Landmark size={16} /> {t.configTitulo}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div>
              <Label htmlFor="buyer-pais">País</Label>
              <select
                id="buyer-pais"
                className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                value={pais}
                onChange={(e) => {
                  setPais(e.target.value as BenchmarkCountry);
                  setComprador(null);
                  setDados(null);
                }}
              >
                {PAISES.map((item) => (
                  <option key={item} value={item}>
                    {ROTULO_PAIS[item]}
                  </option>
                ))}
              </select>
            </div>
            <EmpresaAutocomplete
              id="buyer-entidade"
              country={pais}
              role={t.entidadeRole}
              value={comprador}
              onSelect={setComprador}
              onClear={() => setComprador(null)}
              label={t.entidadeLabel}
            />
            <CpvAutocomplete id="buyer-cpv" country={pais} value={cpv} onChange={setCpv} />
            <SeletorAno id="buyer-ano-de" label="Ano de" anos={anos} value={anoDe} onChange={setAnoDe} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <SeletorAno id="buyer-ano-ate" label="Ano até" anos={anos} value={anoAte} onChange={setAnoAte} />
            <div className="flex items-end">
              <Button
                className="w-full"
                onClick={() => void analisar()}
                loading={aCarregar}
                disabled={!comprador}
                icon={<Search size={16} />}
              >
                {t.acao}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {erro ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">{erro}</span>
        </div>
      ) : null}

      {aCarregar && !dados ? (
        <div className="flex flex-col items-center justify-center py-14">
          <Loader2 size={30} className="mb-3 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">{t.aCarregar}</p>
        </div>
      ) : null}

      {dados ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              icon={vendedor ? <HandCoins size={16} /> : <ShoppingCart size={16} />}
              label={rot.entity}
              value={limparNome(dados.buyer.name).slice(0, 32)}
              hint={`${num(dados.buyer.contracts)} contratos · ${moneyShort(dados.buyer.total_value)}`}
            />
            <Kpi
              icon={<BadgeEuro size={16} />}
              label={t.kpiMediana}
              value={money(dados.buyer.median)}
              hint={`mercado ${money(dados.buyer.market_median)} · p90 ${moneyShort(dados.buyer.market_p90)}`}
            />
            <Kpi
              icon={<Building2 size={16} />}
              label={rot.ring1}
              value={num(dados.suppliers.length)}
              hint={
                dados.suppliers.length
                  ? `risco em ${dados.suppliers.filter((linha) => linha.score < 30).length} · favorável em ${
                      dados.suppliers.filter((linha) => linha.score >= 70).length
                    }`
                  : undefined
              }
            />
            <Kpi
              icon={<Users size={16} />}
              label={vendedor ? "Concorrentes" : "Clientes comuns"}
              value={num(dados.clients.length)}
              hint={`${num(dados.regions.length)} ${vendedor ? "regiões onde vendo" : "regiões de execução"}`}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[2fr_1fr]">
            <div className="space-y-4">
              <Card>
                <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
                  <Network size={16} className="text-muted-foreground" />
                  <CardTitle className="text-sm">{t.grafo}</CardTitle>
                  <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                    {aResolver > 0 ? (
                      <span className="inline-flex items-center gap-1 text-sky-300">
                        <Loader2 size={12} className="animate-spin" />
                        a identificar marcas ({progresso.concluidos}/{progresso.total})
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 transition hover:bg-accent"
                        title="Voltar a procurar os sites e logótipos das empresas deste grafo"
                        onClick={repetirPerfis}
                      >
                        <ImageIcon size={12} />
                        marcas {Object.keys(perfis).filter((chave) => perfis[chave]?.logo_url).length}/{progresso.total} · repetir
                      </button>
                    )}
                    {erroPerfis ? <span className="text-amber-300" title={erroPerfis}>marcas indisponíveis</span> : null}
                    {dados.country_label}
                  </span>
                </CardHeader>
                <CardContent className="pt-0">
                  <BuyerGraph
                    dados={dados}
                    perfis={perfis}
                    selecionado={selecionado}
                    onSelect={setSelecionado}
                    onContexto={(evento, no) => {
                      if (no.kind === "supplier") {
                        abrir(evento, {
                          title: limparNome(no.supplier.name),
                          subtitle: `${moneyShort(no.supplier.value)} · ${no.supplier.contracts} contratos`,
                          items: itensDoFornecedor(no.supplier),
                        });
                        return;
                      }
                      if (no.kind === "client") {
                        abrir(evento, {
                          title: limparNome(no.name),
                          subtitle: vendedor ? "Concorrente que vende aos mesmos compradores" : "Cliente comum dos fornecedores",
                          items: [
                            {
                              id: "benchmark",
                              label: vendedor ? "Benchmark deste concorrente" : "Abrir o benchmark deste comprador",
                              icon: vendedor ? <GitCompare size={13} /> : <ShoppingCart size={13} />,
                              onSelect: () => {
                                fechar();
                                if (vendedor) abrirBenchmarkDaEmpresa(no.nif, no.name, "adjudicatario");
                                else abrirComprador(no.nif, no.name);
                              },
                            },
                            { id: "copiar", label: "Copiar identificador", icon: <Copy size={13} />, hint: no.nif, onSelect: () => { copiar(no.nif); fechar(); } },
                          ],
                        });
                        return;
                      }
                      abrir(evento, {
                        title: limparNome(dados.buyer.name),
                        subtitle: vendedor ? "Vendedor analisado" : "Comprador analisado",
                        items: [
                          {
                            id: "benchmark-comprador",
                            label: "Atualizar esta análise",
                            icon: <RefreshCw size={13} />,
                            onSelect: () => {
                              fechar();
                              void analisar();
                            },
                          },
                          {
                            id: "ficha",
                            label: pais === "pt" ? "Abrir ficha do comprador" : "Abrir contratos do país",
                            icon: <Building2 size={13} />,
                            onSelect: () => {
                              fechar();
                              window.location.assign(pais === "pt" ? `/companies/${encodeURIComponent(dados.buyer.nif || "")}` : "/banco-de-empresas");
                            },
                          },
                          {
                            id: "copiar",
                            label: "Copiar identificador",
                            icon: <Copy size={13} />,
                            hint: dados.buyer.nif || "",
                            onSelect: () => {
                              copiar(dados.buyer.nif || "");
                              fechar();
                            },
                          },
                        ],
                      });
                    }}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
                  <MapPin size={16} className="text-muted-foreground" />
                  <CardTitle className="text-sm">{t.mapa} (OSM)</CardTitle>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {num(dados.regions.length)} regiões · botão direito em cada ponto para opções
                  </span>
                </CardHeader>
                <CardContent className="pt-0">
                  {dados.regions.length ? (
                    <BuyerMap
                      regioes={dados.regions}
                      selecionada={regiaoAtiva}
                      onSelect={(ponto) => setRegiaoAtiva(ponto.region.code)}
                      onContexto={(evento, ponto) =>
                        abrir(evento, {
                          title: ponto.region.code,
                          subtitle: `${num(ponto.region.contracts)} contratos · ${moneyShort(ponto.region.value)}${
                            ponto.exact ? "" : " · posição aproximada"
                          }`,
                          items: itensDaRegiao(ponto),
                        })
                      }
                    />
                  ) : (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      Sem regiões identificadas neste segmento.
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* --------------------------------------------------- detalhe */}
            <div className="space-y-4">
              <Card>
                <CardHeader className="flex flex-row items-center gap-2 pb-2">
                  <Info size={16} className="text-muted-foreground" />
                  <CardTitle className="text-sm">Detalhe</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 pt-0 text-sm">
                  {selecionado?.kind === "supplier" ? (
                    <>
                      <div className="flex items-start gap-2.5">
                        <EmpresaLogo
                          nome={selecionado.supplier.name}
                          nif={selecionado.supplier.nif}
                          logoUrl={perfis[selecionado.supplier.nif]?.logo_url}
                          size={44}
                        />
                        <div className="min-w-0">
                          <p className="font-medium">{limparNome(selecionado.supplier.name)}</p>
                          <p className="text-xs tabular-nums text-muted-foreground">
                            {selecionado.supplier.nif} · {selecionado.supplier.status}
                          </p>
                          {siteDe(perfis, selecionado.supplier) ? (
                            <a
                              href={siteDe(perfis, selecionado.supplier) as string}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-sky-400 hover:underline"
                            >
                              <ExternalLink size={11} />
                              {siteDe(perfis, selecionado.supplier)?.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                            </a>
                          ) : null}
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 pt-1 text-xs">
                        <span className="text-muted-foreground">{vendedor ? "Vendido a este comprador" : "Valor com o comprador"}</span>
                        <span className="text-right tabular-nums">{money(selecionado.supplier.value)}</span>
                        <span className="text-muted-foreground">Contratos</span>
                        <span className="text-right tabular-nums">{num(selecionado.supplier.contracts)}</span>
                        <span className="text-muted-foreground">{rot.share}</span>
                        <span className="text-right tabular-nums">{selecionado.supplier.share_pct ?? "—"} %</span>
                        <span className="text-muted-foreground">{rot.dependency}</span>
                        <span className="text-right tabular-nums">{selecionado.supplier.dependency_pct ?? "—"} %</span>
                        <span className="text-muted-foreground">{rot.price}</span>
                        <span className={`text-right tabular-nums ${indicePreco(selecionado.supplier.price_index, dados.buyer.market_median).cor}`}>
                          {indicePreco(selecionado.supplier.price_index, dados.buyer.market_median).texto}
                        </span>
                        <span className="text-muted-foreground">{rot.count}</span>
                        <span className="text-right tabular-nums">{num(selecionado.supplier.client_count)}</span>
                        <span className="text-muted-foreground">{vendedor ? "CPV que lhe vendo" : "CPV cobertos"}</span>
                        <span className="text-right tabular-nums">
                          {num(selecionado.supplier.cpvs_here)} de {num(selecionado.supplier.cpvs_market)}
                        </span>
                        <span className="text-muted-foreground">{vendedor ? "Última venda" : "Última compra"}</span>
                        <span className="text-right tabular-nums">{selecionado.supplier.last_date?.slice(0, 10) ?? "—"}</span>
                      </div>
                      <div className="space-y-1 pt-1">
                        {selecionado.supplier.strengths.map((forca) => (
                          <p key={forca} className="rounded-xl border border-emerald-400/25 bg-emerald-400/5 px-2 py-1 text-xs text-emerald-200">
                            + {forca}
                          </p>
                        ))}
                        {selecionado.supplier.weaknesses.map((fraqueza) => (
                          <p key={fraqueza} className="rounded-xl border border-amber-400/25 bg-amber-400/5 px-2 py-1 text-xs text-amber-200">
                            − {fraqueza}
                          </p>
                        ))}
                      </div>
                      <div className="flex gap-2 pt-1">
                        <Button
                          variant="outline"
                          size="md"
                          onClick={() => abrirBenchmarkDaEmpresa(selecionado.supplier.nif, selecionado.supplier.name)}
                        >
                          Benchmark da empresa
                        </Button>
                      </div>
                    </>
                  ) : selecionado?.kind === "client" ? (
                    <>
                      <p className="font-medium">{limparNome(selecionado.name)}</p>
                      <p className="text-xs tabular-nums text-muted-foreground">{selecionado.nif}</p>
                      <p className="text-xs text-muted-foreground">
                        {vendedor
                          ? "Fornecedor que vende aos mesmos compradores — o meu concorrente direto."
                          : "Comprador que usa os mesmos fornecedores — candidato a comparação de preços."}
                      </p>
                      <Button variant="outline" size="md" onClick={() => abrirBenchmarkDaEmpresa(selecionado.nif, selecionado.name)}>
                        {vendedor ? "Benchmark desta empresa" : "Benchmark deste comprador"}
                      </Button>
                    </>
                  ) : (
                    <>
                      <div className="flex items-start gap-2.5">
                        <EmpresaLogo
                          nome={dados.buyer.name}
                          nif={dados.buyer.nif}
                          logoUrl={dados.buyer.nif ? perfis[dados.buyer.nif]?.logo_url : undefined}
                          size={44}
                        />
                        <div className="min-w-0">
                          <p className="font-medium">{limparNome(dados.buyer.name)}</p>
                          <p className="text-xs tabular-nums text-muted-foreground">
                            {dados.buyer.nif || "—"} · {dados.country_label}
                          </p>
                          {siteDe(perfis, { nif: dados.buyer.nif, nome: dados.buyer.name }) ? (
                            <a
                              href={siteDe(perfis, { nif: dados.buyer.nif, nome: dados.buyer.name }) as string}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-sky-400 hover:underline"
                            >
                              <ExternalLink size={11} />
                              {siteDe(perfis, { nif: dados.buyer.nif, nome: dados.buyer.name })
                                ?.replace(/^https?:\/\/(www\.)?/, "")
                                .replace(/\/$/, "")}
                            </a>
                          ) : null}
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 pt-1 text-xs">
                        <span className="text-muted-foreground">Contratos</span>
                        <span className="text-right tabular-nums">{num(dados.buyer.contracts)}</span>
                        <span className="text-muted-foreground">Valor</span>
                        <span className="text-right tabular-nums">{moneyShort(dados.buyer.total_value)}</span>
                        <span className="text-muted-foreground">{t.kpiMediana}</span>
                        <span className="text-right tabular-nums">{money(dados.buyer.median)}</span>
                        <span className="text-muted-foreground">Mediana do mercado</span>
                        <span className="text-right tabular-nums">{money(dados.buyer.market_median)}</span>
                        <span className="text-muted-foreground">{vendedor ? "Peso no mercado do segmento" : "Quota de valor"}</span>
                        <span className="text-right tabular-nums">{dados.buyer.share_pct ?? "—"} %</span>
                      </div>
                      <p className="pt-1 text-xs text-muted-foreground">
                        {vendedor
                          ? "Clique num comprador (no grafo, na tabela ou na lista) para ver as forças e fraquezas dessa relação."
                          : "Clique num fornecedor (no grafo, no mapa da tabela ou na lista) para ver as forças e fraquezas dessa relação."}
                      </p>
                    </>
                  )}
                </CardContent>
              </Card>

              {dados.alternatives.length ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t.alternativas}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 pt-0 text-xs">
                    {dados.alternatives.map((linha) => (
                      <button
                        key={linha.nif || linha.name}
                        type="button"
                        className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition hover:bg-accent"
                        onClick={() => linha.nif && abrirComprador(linha.nif, linha.name)}
                      >
                        <span className="min-w-0 flex-1 truncate">{limparNome(linha.name)}</span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">{moneyShort(linha.value)}</span>
                      </button>
                    ))}
                  </CardContent>
                </Card>
              ) : null}

              {dados.clients.length ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t.anel2}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 pt-0 text-xs">
                    {dados.clients.map((cliente) => (
                      <button
                        key={cliente.nif}
                        type="button"
                        className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition hover:bg-accent"
                        onClick={() => abrirComprador(cliente.nif, cliente.name)}
                      >
                        <span className="min-w-0 flex-1 truncate">{limparNome(cliente.name)}</span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">{num(cliente.contracts)}</span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">{moneyShort(cliente.value)}</span>
                      </button>
                    ))}
                  </CardContent>
                </Card>
              ) : null}
            </div>
          </div>

          {/* ------------------------------------------------------- tabela */}
          <Card>
            <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
              <Users size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">{t.tabela}</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">
                botão direito numa linha para as opções · {ROTULO_PAIS[pais]}
              </span>
            </CardHeader>
            <CardContent className="pt-0">
              {dados.suppliers.length ? (
                <div className="overflow-x-auto" data-context-scope>
                  <table className="w-full min-w-[980px] text-sm">
                    <thead>
                      <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="py-2 pr-3">{rot.ring1_one}</th>
                        <th className="py-2 pr-3 text-right">Valor</th>
                        <th className="py-2 pr-3 text-right">{vendedor ? "Peso" : "Quota"}</th>
                        <th className="py-2 pr-3 text-right">{vendedor ? "A minha quota" : "Dependência"}</th>
                        <th className="py-2 pr-3 text-right">Preço</th>
                        <th className="py-2 pr-3 text-right">{vendedor ? "Fornecedores" : "Clientes"}</th>
                        <th className="py-2 pr-3 text-right">CPV</th>
                        <th className="py-2">Forças e fraquezas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.suppliers.map((linha) => {
                        const preco = indicePreco(linha.price_index, dados.buyer.market_median);
                        return (
                          <tr
                            key={linha.nif}
                            className={`cursor-pointer border-b border-border/40 align-top transition hover:bg-white/[0.03] ${
                              selecionado?.kind === "supplier" && selecionado.supplier.nif === linha.nif ? "bg-white/[0.05]" : ""
                            }`}
                            onClick={() => setSelecionado({ kind: "supplier", supplier: linha })}
                            onContextMenu={(evento) =>
                              abrir(evento, {
                                title: limparNome(linha.name),
                                subtitle: `${moneyShort(linha.value)} · ${num(linha.contracts)} contratos`,
                                items: itensDoFornecedor(linha),
                              })
                            }
                          >
                            <td className="py-2 pr-3">
                              <div className="flex items-center gap-2">
                                <EmpresaLogo
                                  nome={linha.name}
                                  nif={linha.nif}
                                  logoUrl={perfis[linha.nif]?.logo_url}
                                  size={30}
                                />
                                <span className="min-w-0">
                                  <span className="flex items-center gap-1.5 font-medium">
                                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: corDoScore(linha.score) }} />
                                    <span className="min-w-0 truncate" title={limparNome(linha.name)}>
                                      {limparNome(linha.name)}
                                    </span>
                                  </span>
                                  <span className="flex items-center gap-1 text-xs tabular-nums text-muted-foreground">
                                    {linha.nif} · {linha.status}
                                    {siteDe(perfis, linha) ? (
                                      <a
                                        href={siteDe(perfis, linha) as string}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={(evento) => evento.stopPropagation()}
                                        className="truncate text-sky-400 hover:underline"
                                        title={siteDe(perfis, linha) as string}
                                      >
                                        {siteDe(perfis, linha)?.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                                      </a>
                                    ) : null}
                                  </span>
                                </span>
                              </div>
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums">{moneyShort(linha.value)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{linha.share_pct ?? "—"} %</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{linha.dependency_pct ?? "—"} %</td>
                            <td className={`py-2 pr-3 text-right text-xs tabular-nums ${preco.cor}`}>{preco.texto}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">{num(linha.client_count)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums">
                              {num(linha.cpvs_here)}
                              <span className="text-muted-foreground">/{num(linha.cpvs_market)}</span>
                            </td>
                            <td className="py-2">
                              <div className="flex flex-wrap gap-1">
                                {linha.strengths.slice(0, 2).map((forca) => (
                                  <span
                                    key={`f-${linha.nif}-${forca}`}
                                    className="rounded-full border border-emerald-400/25 bg-emerald-400/5 px-2 py-0.5 text-[10px] text-emerald-200"
                                  >
                                    {forca}
                                  </span>
                                ))}
                                {linha.weaknesses.slice(0, 2).map((fraqueza) => (
                                  <span
                                    key={`w-${linha.nif}-${fraqueza}`}
                                    className="rounded-full border border-amber-400/25 bg-amber-400/5 px-2 py-0.5 text-[10px] text-amber-200"
                                  >
                                    {fraqueza}
                                  </span>
                                ))}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Sem fornecedores identificados neste segmento. Experimente outro CPV ou uma janela de anos maior.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <GitCompare size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Como ler (ontologia deste grafo)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-0 text-xs text-muted-foreground">
              <div className="flex flex-wrap gap-2">
                {dados.ontology.object_types.map((tipo) => (
                  <span key={tipo.id} className={`rounded-full border border-border px-2 py-0.5 ${COR_PAIS[pais]}`}>
                    {tipo.label}
                  </span>
                ))}
                {dados.ontology.link_types.map((ligacao) => (
                  <span key={ligacao.id} className="rounded-full border border-border px-2 py-0.5">
                    {ligacao.from} → {ligacao.to} ({ligacao.label})
                  </span>
                ))}
              </div>
              <ul className="list-inside list-disc space-y-0.5">
                {dados.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <ContextMenu menu={menu} />
    </div>
  );
}
