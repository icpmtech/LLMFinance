/**
 * Inteligência de mercado · empresas, entidades e dependências — página do módulo.
 *
 * Segue o modelo de inteligência empresarial para contratação pública:
 *
 * 1. **Mercados** — define os mercados comparáveis (classe de CPV + empresas com
 *    CAE compatível + período) e diz a **cobertura de CAE** de cada um: é o
 *    limite honesto do modelo (sem CAE no registo não se afirma atividade).
 * 2. **Benchmark** — compara as empresas do mesmo mercado: contratos, valor,
 *    quota `P_i`, entidades distintas, maior entidade, `D_i` (concentração da
 *    carteira de compradores), evolução anual, CAE e compatibilidade com o CPV.
 * 3. **Dependências** — leitura recíproca: empresa→entidades (`D_i`) e
 *    entidade→fornecedores (quota do maior fornecedor e alternativas observadas).
 * 4. **Grafo** — malha `empresa → contrato → entidade → CPV → CAE`, datada,
 *    desenhada a pedido.
 * 5. **Evidências** — os contratos que sustentam qualquer indicador.
 *
 * Toda a leitura traz as limitações declaradas: quota do mercado **definido**
 * (não quota de mercado total), concentração ≠ dependência económica, partilha
 * de clientes ≠ coordenação.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  Building2,
  Coins,
  FileSearch,
  Gauge,
  GitBranch,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Scale,
  Share2,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getLorenzAreas, type LorenzArea } from "../lorenzApi";
import {
  getMercadoBenchmark,
  getMercadoDependencias,
  getMercadoEmpresa,
  getMercadoEvidencias,
  getMercadoGrafo,
  getMercadoMercados,
  getMercadoMeta,
  getMercadoPares,
  guardarMercadoExecucao,
  type MercadoBenchmark,
  type MercadoDependencias,
  type MercadoEmpresaFicha,
  type MercadoEscopoParams,
  type MercadoEvidencias,
  type MercadoGrafo,
  type MercadoMercados,
  type MercadoMeta,
  type MercadoPares,
} from "../mercadoApi";
import { Chip, EmptyState, Kpi, Loading, SectionCard, formatCompactEuro, formatNumber, formatPct } from "../components/padroes/padroesKit";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { toStudioGraph, type StudioGraph } from "../components/graph/graphStudio";

type Seccao = "mercados" | "benchmark" | "dependencias" | "grafo" | "evidencias";

const SECCOES: { id: Seccao; label: string; icon: typeof BarChart3; hint: string }[] = [
  { id: "mercados", label: "Mercados", icon: Layers, hint: "Classes de CPV, empresas com CAE compatível e cobertura do registo" },
  { id: "benchmark", label: "Benchmark", icon: BarChart3, hint: "Comparação entre empresas do mesmo mercado" },
  { id: "dependencias", label: "Dependências", icon: Share2, hint: "Empresa→entidades e entidade→fornecedores" },
  { id: "grafo", label: "Grafo", icon: GitBranch, hint: "Empresa → contrato → entidade → CPV → CAE" },
  { id: "evidencias", label: "Evidências", icon: FileSearch, hint: "Contratos que sustentam os indicadores" },
];

const REGIOES = [
  { id: "", label: "Todas as regiões" },
  { id: "PT11", label: "Norte" },
  { id: "PT15", label: "Algarve" },
  { id: "PT16", label: "Centro" },
  { id: "PT17", label: "Área Metropolitana de Lisboa" },
  { id: "PT18", label: "Alentejo" },
  { id: "PT20", label: "Açores" },
  { id: "PT30", label: "Madeira" },
];

/* ------------------------------------------------------------------- tons */

function tomGrau(grau?: string | null): string {
  if (grau === "alta") return "teal";
  if (grau === "média-alta") return "blue";
  if (grau === "média") return "violet";
  if (grau === "baixa") return "amber";
  return "neutral";
}

function tomQualidade(grau?: string | null): string {
  if (grau === "boa") return "teal";
  if (grau === "aceitável") return "amber";
  return "rose";
}

function tomSeveridade(severidade?: string | null): string {
  if (severidade === "alta") return "rose";
  if (severidade === "média") return "amber";
  return "neutral";
}

function tomCompatibilidade(grau?: string | null): string {
  return tomGrau(grau);
}

/** Rótulo curto da concentração da carteira (HHI). */
function rotuloHhi(hhi?: number | null): string {
  const valor = hhi ?? 0;
  if (valor >= 0.5) return "muito concentrada";
  if (valor >= 0.25) return "concentrada";
  if (valor >= 0.1) return "moderada";
  return "diversificada";
}

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/5 py-1 last:border-0">
      <span className="text-[11px] text-muted-foreground">{rotulo}</span>
      <span className="text-right font-mono text-[11.5px]">{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------------- página */

export default function MercadoPage({ onAbrirCenarios }: { onAbrirCenarios?: () => void }) {
  const [meta, setMeta] = useState<MercadoMeta | null>(null);
  const [areasDisponiveis, setAreasDisponiveis] = useState<LorenzArea[]>([]);
  const [seccao, setSeccao] = useState<Seccao>("benchmark");

  /* escopo */
  const [area, setArea] = useState("todas");
  const [cpvLivre, setCpvLivre] = useState("");
  const [anoDe, setAnoDe] = useState("");
  const [anoAte, setAnoAte] = useState("");
  const [regiao, setRegiao] = useState("");
  const [texto, setTexto] = useState("");
  const [nifsTexto, setNifsTexto] = useState("");

  /* dados */
  const [benchmark, setBenchmark] = useState<MercadoBenchmark | null>(null);
  const [mercados, setMercados] = useState<MercadoMercados | null>(null);
  const [dependencias, setDependencias] = useState<MercadoDependencias | null>(null);
  const [grafoResposta, setGrafoResposta] = useState<MercadoGrafo | null>(null);
  const [evidencias, setEvidencias] = useState<MercadoEvidencias | null>(null);
  const [evidenciaTitulo, setEvidenciaTitulo] = useState<string | null>(null);

  const [aCarregar, setACarregar] = useState(false);
  const [aCarregarMercados, setACarregarMercados] = useState(false);
  const [aCarregarDependencias, setACarregarDependencias] = useState(false);
  const [aDesenhar, setADesenhar] = useState(false);
  const [aProcurarEvidencia, setAProcurarEvidencia] = useState(false);
  const [aGravar, setAGravar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  /* ficha da empresa + pares */
  const [ficha, setFicha] = useState<MercadoEmpresaFicha | null>(null);
  const [pares, setPares] = useState<MercadoPares | null>(null);
  const [aCarregarFicha, setACarregarFicha] = useState(false);

  /* grafo */
  const [layout, setLayout] = useState<"hierarchical" | "network" | "circular">("hierarchical");
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);

  const params = useMemo<MercadoEscopoParams>(() => {
    const limpo: MercadoEscopoParams = { area };
    if (cpvLivre.trim()) limpo.cpv = cpvLivre.trim();
    if (anoDe) limpo.ano_de = Number(anoDe);
    if (anoAte) limpo.ano_ate = Number(anoAte);
    if (regiao) limpo.regiao = regiao;
    if (texto.trim()) limpo.texto = texto.trim();
    return limpo;
  }, [anoAte, anoDe, area, cpvLivre, regiao, texto]);

  const nifs = useMemo(
    () => nifsTexto.split(/[,;\s]+/).map((item) => item.trim()).filter((item) => item.length >= 5),
    [nifsTexto],
  );

  /* --------------------------------------------------------- carregamentos */

  useEffect(() => {
    let cancelado = false;
    getMercadoMeta()
      .then((resposta) => {
        if (!cancelado) setMeta(resposta);
      })
      .catch(() => {
        /* o metamodelo é acessório */
      });
    getLorenzAreas()
      .then((resposta) => {
        if (!cancelado && resposta.areas?.length) setAreasDisponiveis(resposta.areas);
      })
      .catch(() => {
        /* idem */
      });
    return () => {
      cancelado = true;
    };
  }, []);

  const carregarBenchmark = useCallback(
    async (alvo?: MercadoEscopoParams & { cpv?: string }) => {
      setACarregar(true);
      setErro(null);
      try {
        const resposta = await getMercadoBenchmark({ ...params, ...alvo, nifs, limite: nifs.length ? undefined : 20 });
        if (resposta.erro) throw new Error(resposta.erro);
        setBenchmark(resposta);
      } catch (falha) {
        setBenchmark(null);
        setErro(falha instanceof Error ? falha.message : "Erro ao medir o mercado");
      } finally {
        setACarregar(false);
      }
    },
    [nifs, params],
  );

  useEffect(() => {
    void carregarBenchmark();
  }, [carregarBenchmark]);

  const carregarMercados = useCallback(
    async (top = 12) => {
      setACarregarMercados(true);
      setErro(null);
      try {
        const resposta = await getMercadoMercados({ ...params, top });
        if (resposta.erro) throw new Error(resposta.erro);
        setMercados(resposta);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao definir os mercados");
      } finally {
        setACarregarMercados(false);
      }
    },
    [params],
  );

  const carregarDependencias = useCallback(async () => {
    setACarregarDependencias(true);
    setErro(null);
    try {
      const resposta = await getMercadoDependencias({ ...params, nifs });
      setDependencias(resposta);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao medir as dependências");
    } finally {
      setACarregarDependencias(false);
    }
  }, [nifs, params]);

  const procurarEvidencias = useCallback(
    async (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => {
      const { nifs: alvos, ...resto } = filtros;
      const fornecedorFiltro = filtros.fornecedor_nif ?? (alvos?.length === 1 ? alvos[0] : undefined);
      setAProcurarEvidencia(true);
      setSeccao("evidencias");
      setEvidenciaTitulo(titulo);
      try {
        const resposta = await getMercadoEvidencias({
          ...params,
          ...resto,
          fornecedor_nif: fornecedorFiltro,
          limite: 25,
        });
        setEvidencias(resposta);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao procurar evidências");
      } finally {
        setAProcurarEvidencia(false);
      }
    },
    [params],
  );

  const abrirFicha = useCallback(
    async (nif: string) => {
      setACarregarFicha(true);
      setErro(null);
      try {
        const [empresa, comparacao] = await Promise.all([
          getMercadoEmpresa(nif, { area, ano_de: params.ano_de, ano_ate: params.ano_ate, regiao: params.regiao }),
          getMercadoPares(nif, { ...params, limite: 8 }),
        ]);
        setFicha(empresa);
        setPares(comparacao);
      } catch (falha) {
        setFicha(null);
        setPares(null);
        setErro(falha instanceof Error ? falha.message : "Erro ao abrir a ficha da empresa");
      } finally {
        setACarregarFicha(false);
      }
    },
    [anoDe, anoAte, area, params, regiao],
  );

  const desenharGrafo = useCallback(async () => {
    setADesenhar(true);
    setErro(null);
    try {
      const resposta = await getMercadoGrafo({ ...params, nifs, contratos: 24 });
      setGrafoResposta(resposta);
      setNoSelecionado(null);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao construir o grafo");
    } finally {
      setADesenhar(false);
    }
  }, [nifs, params]);

  const gravarExecucao = useCallback(async () => {
    setAGravar(true);
    setErro(null);
    try {
      const etiqueta = areasDisponiveis.find((item) => item.id === area)?.label ?? area;
      const resposta = await guardarMercadoExecucao({ ...params, nifs, titulo: `Mercado · ${etiqueta}` });
      setAviso(`Execução guardada (${resposta.run_id}).`);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao guardar a execução (é preciso sessão)");
    } finally {
      setAGravar(false);
    }
  }, [area, areasDisponiveis, nifs, params]);

  /* carregamento por secção (mercados/dependências só quando pedidos) */
  useEffect(() => {
    if (seccao === "mercados" && !mercados) void carregarMercados();
    if (seccao === "dependencias" && !dependencias) void carregarDependencias();
  }, [carregarDependencias, carregarMercados, dependencias, mercados, seccao]);

  const grafoPreparado = useMemo(() => prepararGrafo(grafoResposta), [grafoResposta]);
  const studioGraph = useMemo<StudioGraph | null>(() => toStudioGraph(grafoPreparado as never, "valor"), [grafoPreparado]);

  const serieEvolucao = useMemo(
    () =>
      (benchmark?.empresas ?? []).map((empresa) => ({
        nome: (empresa.nome ?? empresa.nif).slice(0, 22),
        valor: empresa.valor,
        quota: empresa.quota,
        contratos: empresa.contratos,
      })),
    [benchmark],
  );

  const noAtual = useMemo(
    () => (grafoPreparado?.nodes ?? []).find((no) => no.id === noSelecionado) ?? null,
    [grafoPreparado, noSelecionado],
  );

  /* ------------------------------------------------------------------- ecrã */
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden text-foreground">
      <header className="shrink-0 border-b border-white/10 bg-white/[0.02] px-4 py-3 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <Scale size={18} className="text-teal-300" />
              Inteligência de mercado · empresas, entidades e dependências
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {meta?.descricao ??
                "Compara empresas dentro do mesmo mercado (CPV + CAE + período), mede dependências recíprocas com as entidades públicas e segue a evolução no tempo."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {benchmark?.mercado ? (
              <Chip tone={tomQualidade(benchmark.mercado.cobertura_cae >= 0.7 ? "boa" : benchmark.mercado.cobertura_cae >= 0.4 ? "aceitável" : "limitada")} title="Cobertura de CAE das empresas do mercado">
                CAE {formatPct(benchmark.mercado.cobertura_cae, 0)} · {benchmark.mercado.empresas} empresas
              </Chip>
            ) : null}
            {onAbrirCenarios ? (
              <button
                type="button"
                onClick={onAbrirCenarios}
                className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-400/15 px-3 py-1.5 text-xs text-violet-100 transition hover:bg-violet-400/25"
              >
                <Play size={13} />
                Cenários
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => {
                void carregarBenchmark();
                setMercados(null);
                setDependencias(null);
                setGrafoResposta(null);
              }}
              disabled={aCarregar}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1] disabled:opacity-50"
            >
              {aCarregar ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Recalcular
            </button>
            <button
              type="button"
              onClick={() => void gravarExecucao()}
              disabled={aGravar || !benchmark}
              title="Guardar esta execução (exige sessão)"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1] disabled:opacity-50"
            >
              {aGravar ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
              Guardar
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-2 text-[11.5px]">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Área</span>
            <select value={area} onChange={(evento) => setArea(evento.target.value)} className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none">
              {areasDisponiveis.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">CPV do mercado</span>
            <input
              value={cpvLivre}
              onChange={(evento) => setCpvLivre(evento.target.value)}
              placeholder="ex.: 3360"
              className="w-28 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Ano de</span>
            <input
              value={anoDe}
              onChange={(evento) => setAnoDe(evento.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="2018"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Ano até</span>
            <input
              value={anoAte}
              onChange={(evento) => setAnoAte(evento.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="2026"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Região</span>
            <select value={regiao} onChange={(evento) => setRegiao(evento.target.value)} className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none">
              {REGIOES.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[150px] flex-1 flex-col gap-1">
            <span className="text-muted-foreground">Texto no objeto/partes</span>
            <input
              value={texto}
              onChange={(evento) => setTexto(evento.target.value)}
              placeholder="ex.: manutenção de equipamento"
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex min-w-[190px] flex-1 flex-col gap-1" title="Sem NIFs, o mercado é o universo das maiores empresas do escopo">
            <span className="text-muted-foreground">NIFs a comparar (vírgulas)</span>
            <input
              value={nifsTexto}
              onChange={(evento) => setNifsTexto(evento.target.value)}
              placeholder="ex.: 500000000, 501234567"
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 font-mono outline-none"
            />
          </label>
        </div>

        <nav className="mt-3 flex flex-wrap gap-1">
          {SECCOES.map((item) => {
            const Icone = item.icon;
            const ativo = seccao === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setSeccao(item.id)}
                title={item.hint}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
                  ativo ? "border-teal-400/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.08]"
                }`}
              >
                <Icone size={13} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {erro && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle size={15} />
            {erro}
          </div>
        )}
        {aviso && <div className="mb-3 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-xs text-teal-100">{aviso}</div>}
        {aCarregar && !benchmark ? <Loading label="A comparar empresas, entidades e dependências…" /> : null}

        {seccao === "mercados" ? (
          <Mercados
            dados={mercados}
            aCarregar={aCarregarMercados}
            onRecarregar={(top) => void carregarMercados(top)}
            onVerEvidencias={procurarEvidencias}
            onFocarMercado={(cpv) => {
              setCpvLivre(cpv);
              setSeccao("benchmark");
            }}
          />
        ) : null}

        {seccao === "benchmark" ? (
          <Benchmark
            dados={benchmark}
            aCarregar={aCarregar}
            serie={serieEvolucao}
            ficha={ficha}
            pares={pares}
            aCarregarFicha={aCarregarFicha}
            onAbrirFicha={(nif) => void abrirFicha(nif)}
            onFecharFicha={() => {
              setFicha(null);
              setPares(null);
            }}
            onVerEvidencias={procurarEvidencias}
          />
        ) : null}

        {seccao === "dependencias" ? (
          <Dependencias
            dados={dependencias}
            aCarregar={aCarregarDependencias}
            onRecarregar={() => void carregarDependencias()}
            onVerEvidencias={procurarEvidencias}
            onAbrirFicha={(nif) => {
              setSeccao("benchmark");
              void abrirFicha(nif);
            }}
          />
        ) : null}

        {seccao === "grafo" ? (
          <Grafo
            grafo={studioGraph}
            resposta={grafoPreparado}
            noAtual={noAtual}
            layout={layout}
            setLayout={setLayout}
            aDesenhar={aDesenhar}
            onDesenhar={() => void desenharGrafo()}
            onSelecionar={setNoSelecionado}
            onVerEvidencias={procurarEvidencias}
          />
        ) : null}

        {seccao === "evidencias" ? (
          <Evidencias dados={evidencias} titulo={evidenciaTitulo} aCarregar={aProcurarEvidencia} onProcurar={() => void procurarEvidencias({}, "Contratos do escopo")} />
        ) : null}

        {meta ? <Notas meta={meta} /> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ preparar */

/**
 * Dá a cada nó o tipo que o desenho usa na legenda (`contrato` e `cae` deixam de
 * cair no «outros») e evita a coloração por lados: aqui há cinco dimensões.
 */
function prepararGrafo(grafo: MercadoGrafo | null): MercadoGrafo | null {
  if (!grafo || grafo.erro) return grafo;
  const tipoPorDimensao: Record<string, string> = {
    empresa: "concorrente",
    entidade: "entidade",
    cpv: "cpv",
    cae: "cae",
    contrato: "contrato",
  };
  return {
    ...grafo,
    nodes: grafo.nodes.map((no) => ({ ...no, type: tipoPorDimensao[no.dimension] ?? no.type })),
    meta: { ...grafo.meta, dimension_b: grafo.meta.dimension_a },
  };
}

/* ----------------------------------------------------------------- Mercados */

function Mercados({
  dados,
  aCarregar,
  onRecarregar,
  onVerEvidencias,
  onFocarMercado,
}: {
  dados: MercadoMercados | null;
  aCarregar: boolean;
  onRecarregar: (top?: number) => void;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => void;
  onFocarMercado: (cpv: string) => void;
}) {
  return (
    <div className="space-y-4">
      <SectionCard
        title="Mercados comparáveis"
        subtitle="Cada mercado é uma classe de CPV + as empresas com CAE compatível + o período escolhido"
        icon={Layers}
        actions={
          <div className="flex items-center gap-1.5">
            {[6, 12, 20].map((quantidade) => (
              <button
                key={quantidade}
                type="button"
                onClick={() => onRecarregar(quantidade)}
                disabled={aCarregar}
                className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
              >
                top {quantidade}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onRecarregar()}
              disabled={aCarregar}
              className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
            >
              {aCarregar ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {dados ? "Recalcular" : "Definir mercados"}
            </button>
          </div>
        }
      >
        {aCarregar && !dados ? <Loading label="A definir os mercados comparáveis…" /> : null}
        {!dados && !aCarregar ? (
          <EmptyState>
            Defina os mercados do escopo: o motor pega nas maiores classes de CPV, lê o CAE das empresas no registo (`finance_entities`) e mede a
            compatibilidade com o CPV de cada classe.
          </EmptyState>
        ) : null}
        {dados ? (
          <div className="space-y-3">
            <p className="text-[11px] text-muted-foreground">
              {formatNumber(dados.total_documentos)} contratos no escopo · {dados.mercados.length} classes de CPV analisadas
            </p>
            <div className="grid gap-3 xl:grid-cols-2">
              {dados.mercados.map((mercado) => (
                <article key={mercado.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <header className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="flex items-center gap-2 font-mono text-sm">
                        CPV {mercado.cpv_classe}
                        <Chip tone={tomQualidade(mercado.qualidade.grau)} title={mercado.qualidade.motivo}>
                          {mercado.qualidade.grau}
                        </Chip>
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {formatCompactEuro(mercado.valor)} · {formatNumber(mercado.contratos)} contratos · {formatNumber(mercado.compradores)} compradores
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Chip tone="violet" title="Índice de concentração da classe de CPV">
                        HHI {mercado.hhi.toFixed(3)}
                      </Chip>
                      <Chip tone="blue" title="Quota do maior fornecedor da classe">
                        líder {formatPct(mercado.quota_lider)}
                      </Chip>
                    </div>
                  </header>

                  <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-3">
                    <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
                      <p className="text-muted-foreground">Empresas no mercado</p>
                      <p className="font-mono text-sm">{formatNumber(mercado.empresas_analisadas)}</p>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
                      <p className="text-muted-foreground">Com CAE no registo</p>
                      <p className="font-mono text-sm">
                        {formatNumber(mercado.empresas_com_cae)} ({formatPct(mercado.cobertura_cae, 0)})
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
                      <p className="text-muted-foreground">Valor com CAE compatível</p>
                      <p className="font-mono text-sm">{formatPct(mercado.cobertura_valor_compativel, 0)}</p>
                    </div>
                  </div>

                  <table className="mt-3 w-full text-[11.5px]">
                    <thead className="text-left text-muted-foreground">
                      <tr>
                        <th className="py-1">Empresa</th>
                        <th className="py-1 text-right">Valor</th>
                        <th className="py-1 text-right">Quota</th>
                        <th className="py-1 text-right">CAE</th>
                        <th className="py-1 text-right">Compat.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mercado.empresas.slice(0, 6).map((empresa) => (
                        <tr key={`${mercado.id}-${empresa.nif}`} className="border-t border-white/5">
                          <td className="max-w-[190px] truncate py-1" title={empresa.nome ?? empresa.nif}>
                            {empresa.nome ?? empresa.nif}
                          </td>
                          <td className="py-1 text-right font-mono">{formatCompactEuro(empresa.valor)}</td>
                          <td className="py-1 text-right font-mono">{formatPct(empresa.quota)}</td>
                          <td className="py-1 text-right font-mono" title={empresa.cae_label ?? undefined}>
                            {empresa.cae_principal ?? "—"}
                          </td>
                          <td className="py-1 text-right">
                            <Chip tone={tomCompatibilidade(empresa.compatibilidade)} title={empresa.compatibilidade_motivo ?? undefined}>
                              {empresa.compatibilidade}
                            </Chip>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {mercado.caes_dominantes.length ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {mercado.caes_dominantes.map((cae) => (
                        <Chip key={`${mercado.id}-${cae.cae}`} tone="neutral" title={cae.label ?? undefined}>
                          CAE {cae.cae} · {cae.empresas} emp. · {formatCompactEuro(cae.valor)}
                        </Chip>
                      ))}
                    </div>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => onFocarMercado(mercado.cpv_classe)}
                      className="inline-flex items-center gap-1 rounded-lg border border-teal-400/30 bg-teal-400/10 px-2.5 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/20"
                    >
                      <Target size={12} /> comparar neste mercado
                    </button>
                    <button
                      type="button"
                      onClick={() => onVerEvidencias({ cpv_prefixo: mercado.cpv_classe }, `Contratos · CPV ${mercado.cpv_classe}`)}
                      className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                    >
                      <FileSearch size={12} /> ver contratos
                    </button>
                  </div>
                </article>
              ))}
            </div>
            {dados.notas?.length ? (
              <ul className="space-y-1 text-[11px] text-muted-foreground">
                {dados.notas.map((nota) => (
                  <li key={nota}>· {nota}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}

/* ---------------------------------------------------------------- Benchmark */

function Benchmark({
  dados,
  aCarregar,
  serie,
  ficha,
  pares,
  aCarregarFicha,
  onAbrirFicha,
  onFecharFicha,
  onVerEvidencias,
}: {
  dados: MercadoBenchmark | null;
  aCarregar: boolean;
  serie: { nome: string; valor: number; quota: number; contratos: number }[];
  ficha: MercadoEmpresaFicha | null;
  pares: MercadoPares | null;
  aCarregarFicha: boolean;
  onAbrirFicha: (nif: string) => void;
  onFecharFicha: () => void;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => void;
}) {
  if (!dados) {
    return <EmptyState>Escolha o escopo e recarregue para comparar as empresas do mercado.</EmptyState>;
  }
  const mercado = dados.mercado;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Coins} label="Valor do mercado" value={formatCompactEuro(mercado.valor)} sub={`${formatNumber(mercado.contratos)} contratos`} />
        <Kpi icon={Users} label="Empresas comparadas" value={formatNumber(mercado.empresas)} sub={`${mercado.empresas_compativeis} com CAE compatível`} color="text-sky-300" glow="glow-sky" />
        <Kpi icon={Target} label="Quota do líder" value={formatPct(mercado.quota_lider)} sub={`HHI do mercado ${mercado.hhi.toFixed(3)}`} color="text-violet-300" />
        <Kpi
          icon={Building2}
          label="Mercado de referência"
          value={mercado.cpv ? `CPV ${mercado.cpv}` : "—"}
          sub={`${mercado.area_label ?? mercado.area ?? "todas as áreas"} · ${mercado.ano_de ?? "—"}–${mercado.ano_ate ?? "—"}`}
          color="text-amber-300"
        />
      </div>

      {dados.avisos?.length ? (
        <div className="space-y-1">
          {dados.avisos.map((aviso) => (
            <EmptyState key={aviso} tone="warn">
              {aviso}
            </EmptyState>
          ))}
        </div>
      ) : null}

      {serie.length ? (
        <SectionCard title="Valor e quota por empresa" subtitle="P_i é a quota do valor publicado dentro deste mercado" icon={BarChart3}>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={serie} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="nome" tick={{ fontSize: 10 }} interval={0} angle={-18} textAnchor="end" height={58} />
                <YAxis yAxisId="valor" tick={{ fontSize: 10 }} tickFormatter={(valor: number) => `${Math.round(valor / 1_000_000)}M`} />
                <YAxis yAxisId="quota" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(valor: number) => `${Math.round(valor * 100)}%`} />
                <Tooltip
                  contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }}
                  formatter={(valor: unknown, nome: unknown) => (nome === "quota" ? formatPct(Number(valor)) : formatCompactEuro(Number(valor)))}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="valor" dataKey="valor" name="valor" fill="#2dd4bf" radius={[4, 4, 0, 0]} />
                <Line yAxisId="quota" dataKey="quota" name="quota" stroke="#a78bfa" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>
      ) : null}

      <SectionCard
        title="Benchmark entre empresas do mesmo mercado"
        subtitle={`${dados.empresas.length} empresas · clique numa linha para abrir a ficha`}
        icon={BarChart3}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1000px] text-[11.5px]">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-white/10">
                <th className="py-1.5">#</th>
                <th className="py-1.5">Empresa</th>
                <th className="py-1.5 text-right">Contratos</th>
                <th className="py-1.5 text-right">Valor</th>
                <th className="py-1.5 text-right">Quota P_i</th>
                <th className="py-1.5 text-right">Entidades</th>
                <th className="py-1.5">Maior entidade</th>
                <th className="py-1.5 text-right">D_i</th>
                <th className="py-1.5 text-right">Evolução</th>
                <th className="py-1.5 text-right">CAE</th>
                <th className="py-1.5 text-right">Compat.</th>
                <th className="py-1.5">Sinais</th>
                <th className="py-1.5" />
              </tr>
            </thead>
            <tbody>
              {dados.empresas.map((empresa) => (
                <tr
                  key={empresa.nif}
                  onClick={() => onAbrirFicha(empresa.nif)}
                  className="cursor-pointer border-b border-white/5 transition hover:bg-white/[0.04]"
                >
                  <td className="py-1.5 font-mono text-muted-foreground">{empresa.posicao}</td>
                  <td className="max-w-[210px] py-1.5">
                    <p className="truncate" title={empresa.nome}>
                      {empresa.nome}
                    </p>
                    <p className="truncate text-[10.5px] text-muted-foreground" title={empresa.perfil}>
                      {empresa.perfil}
                    </p>
                  </td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(empresa.contratos)}</td>
                  <td className="py-1.5 text-right font-mono">{formatCompactEuro(empresa.valor)}</td>
                  <td className="py-1.5 text-right font-mono">{formatPct(empresa.quota)}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(empresa.entidades_distintas)}</td>
                  <td className="max-w-[180px] truncate py-1.5" title={empresa.maior_entidade?.nome ?? undefined}>
                    {empresa.maior_entidade?.nome ?? "—"}
                    {empresa.maior_entidade?.quota !== undefined ? (
                      <span className="ml-1 font-mono text-[10.5px] text-muted-foreground">{formatPct(empresa.maior_entidade.quota, 0)}</span>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-right font-mono" title={rotuloHhi(empresa.dependencia?.hhi)}>
                    {empresa.dependencia?.hhi !== undefined ? empresa.dependencia.hhi.toFixed(3) : "—"}
                  </td>
                  <td
                    className={`py-1.5 text-right font-mono ${
                      (empresa.evolucao?.variacao ?? 0) < -0.1 ? "text-rose-300" : (empresa.evolucao?.variacao ?? 0) > 0.1 ? "text-teal-300" : ""
                    }`}
                  >
                    {empresa.evolucao?.variacao !== null && empresa.evolucao?.variacao !== undefined ? formatPct(empresa.evolucao.variacao, 0) : "—"}
                  </td>
                  <td className="py-1.5 text-right font-mono" title={empresa.cae_label ?? undefined}>
                    {empresa.cae_principal ?? "—"}
                  </td>
                  <td className="py-1.5 text-right">
                    <Chip tone={tomCompatibilidade(empresa.compatibilidade)} title={empresa.compatibilidade_motivo ?? undefined}>
                      {empresa.compatibilidade}
                    </Chip>
                  </td>
                  <td className="py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {empresa.alertas?.slice(0, 2).map((alerta) => (
                        <Chip key={`${empresa.nif}-${alerta.tipo}`} tone={tomSeveridade(alerta.severidade)} title={alerta.detalhe}>
                          {alerta.tipo.replace(/_/g, " ")}
                        </Chip>
                      ))}
                    </div>
                  </td>
                  <td className="py-1.5 text-right">
                    <button
                      type="button"
                      onClick={(evento) => {
                        evento.stopPropagation();
                        onVerEvidencias({ nifs: [empresa.nif] }, `Contratos · ${empresa.nome}`);
                      }}
                      className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                    >
                      contratos
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {dados.limites?.nota ? <p className="mt-2 text-[11px] text-muted-foreground">Limite declarado: {dados.limites.nota}</p> : null}
      </SectionCard>

      {aCarregarFicha ? <Loading label="A abrir a ficha da empresa…" /> : null}
      {ficha ? <FichaEmpresa ficha={ficha} pares={pares} onFechar={onFecharFicha} onVerEvidencias={onVerEvidencias} /> : null}

      {dados.notas?.length ? (
        <SectionCard title="Limites de leitura" subtitle="o que estes indicadores não dizem" icon={AlertTriangle}>
          <ul className="space-y-1 text-[11.5px] text-muted-foreground">
            {dados.notas.map((nota) => (
              <li key={nota}>· {nota}</li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
      {aCarregar ? <p className="text-[11px] text-muted-foreground">A recalcular…</p> : null}
    </div>
  );
}

/* ------------------------------------------------------------ FichaEmpresa */

function FichaEmpresa({
  ficha,
  pares,
  onFechar,
  onVerEvidencias,
}: {
  ficha: MercadoEmpresaFicha;
  pares: MercadoPares | null;
  onFechar: () => void;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => void;
}) {
  const evolucao = (ficha.evolucao?.anos ?? []).map((ano, indice) => ({
    ano: String(ano),
    valor: ficha.evolucao?.valores?.[indice] ?? 0,
  }));
  return (
    <SectionCard
      title={ficha.nome || ficha.nif}
      subtitle={`NIF ${ficha.nif} · CAE ${ficha.cae?.cae_principal ?? "—"} ${ficha.cae?.cae_principal_label ?? ""} · compatibilidade ${ficha.compatibilidade?.grau ?? "—"}`}
      icon={Building2}
      actions={
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onVerEvidencias({ nifs: [ficha.nif] }, `Contratos · ${ficha.nome}`)}
            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
          >
            <FileSearch size={12} /> contratos
          </button>
          <button type="button" onClick={onFechar} className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]">
            fechar
          </button>
        </div>
      }
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <div className="grid gap-2 text-[11.5px] sm:grid-cols-3">
            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-muted-foreground">Valor contratado</p>
              <p className="font-mono text-sm">{formatCompactEuro(ficha.valor)}</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-muted-foreground">Contratos / entidades</p>
              <p className="font-mono text-sm">
                {formatNumber(ficha.contratos)} / {formatNumber(ficha.entidades_distintas)}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-muted-foreground">Sem procedimento competitivo</p>
              <p className="font-mono text-sm">{formatPct(ficha.taxa_sem_concurso, 0)}</p>
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[11px] text-muted-foreground">Perfil</p>
            <p className="text-[12px]">{ficha.perfil}</p>
          </div>

          {ficha.alertas?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {ficha.alertas.map((alerta) => (
                <Chip key={alerta.tipo} tone={tomSeveridade(alerta.severidade)} title={alerta.detalhe}>
                  {alerta.tipo.replace(/_/g, " ")}
                </Chip>
              ))}
            </div>
          ) : null}

          {evolucao.length > 1 ? (
            <div className="h-[190px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={evolucao} margin={{ top: 8, right: 8, bottom: 4, left: 8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="ano" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(valor: number) => `${Math.round(valor / 1_000_000)}M`} />
                  <Tooltip
                    contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }}
                    formatter={(valor: unknown) => formatCompactEuro(Number(valor))}
                  />
                  <Line dataKey="valor" stroke="#2dd4bf" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : null}

          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-[11.5px]">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-white/10">
                  <th className="py-1">Comprador</th>
                  <th className="py-1 text-right">Valor</th>
                  <th className="py-1 text-right">Contratos</th>
                  <th className="py-1 text-right">Quota</th>
                </tr>
              </thead>
              <tbody>
                {ficha.entidades?.slice(0, 10).map((entidade) => (
                  <tr key={`${ficha.nif}-${entidade.nif ?? entidade.nome}`} className="border-b border-white/5">
                    <td className="max-w-[260px] truncate py-1" title={entidade.nome}>
                      {entidade.nome ?? entidade.nif}
                    </td>
                    <td className="py-1 text-right font-mono">{formatCompactEuro(entidade.valor)}</td>
                    <td className="py-1 text-right font-mono">{formatNumber(entidade.contratos)}</td>
                    <td className="py-1 text-right font-mono">{formatPct(entidade.quota)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="space-y-3">
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Dependência de compradores</p>
            <Linha rotulo="D_i (HHI da carteira)">{ficha.dependencia?.hhi !== undefined ? ficha.dependencia.hhi.toFixed(3) : "—"}</Linha>
            <Linha rotulo="Maior comprador">{ficha.dependencia?.maior_quota !== undefined ? formatPct(ficha.dependencia.maior_quota) : "—"}</Linha>
            <Linha rotulo="Nº de compradores">{formatNumber(ficha.dependencia?.n_entidades)}</Linha>
            <Linha rotulo="Leitura">{rotuloHhi(ficha.dependencia?.hhi)}</Linha>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Classes de CPV</p>
            {ficha.cpvs?.slice(0, 8).map((cpv) => (
              <Linha key={`${ficha.nif}-${cpv.classe}`} rotulo={`CPV ${cpv.classe}`}>
                {formatCompactEuro(cpv.valor)}
              </Linha>
            ))}
            {!ficha.cpvs?.length ? <p className="text-[11px] text-muted-foreground">sem CPV no escopo</p> : null}
          </div>

          {pares?.pares?.length ? (
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Empresas comparáveis</p>
              {pares.pares.slice(0, 8).map((par) => (
                <Linha key={par.nif} rotulo={par.nome}>
                  {formatPct(par.quota)}
                </Linha>
              ))}
              {pares.notas?.length ? <p className="mt-2 text-[10.5px] text-muted-foreground">{pares.notas[0]}</p> : null}
            </div>
          ) : null}
        </aside>
      </div>
    </SectionCard>
  );
}

/* ------------------------------------------------------------ Dependências */

function Dependencias({
  dados,
  aCarregar,
  onRecarregar,
  onVerEvidencias,
  onAbrirFicha,
}: {
  dados: MercadoDependencias | null;
  aCarregar: boolean;
  onRecarregar: () => void;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => void;
  onAbrirFicha: (nif: string) => void;
}) {
  if (!dados) {
    return (
      <SectionCard title="Dependências recíprocas" subtitle="empresa→entidades e entidade→fornecedores" icon={Share2}>
        <button
          type="button"
          onClick={onRecarregar}
          disabled={aCarregar}
          className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1.5 text-xs text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
        >
          {aCarregar ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          Medir dependências
        </button>
      </SectionCard>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Users} label="Empresas medidas" value={formatNumber(dados.totais.empresas)} />
        <Kpi icon={Building2} label="Entidades analisadas" value={formatNumber(dados.totais.entidades)} color="text-sky-300" glow="glow-sky" />
        <Kpi icon={AlertTriangle} label="Entidades críticas" value={formatNumber(dados.totais.entidades_criticas)} sub="maior fornecedor ≥ 60 % do valor" color="text-rose-300" />
        <Kpi icon={Gauge} label="Empresas dependentes" value={formatNumber(dados.totais.empresas_dependentes)} sub="maior comprador ≥ 50 % do valor" color="text-amber-300" />
      </div>

      <SectionCard title="Empresa → entidades" subtitle="D_i é o HHI da carteira de compradores: concentração, não dependência económica" icon={Share2}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[11.5px]">
            <thead className="text-left text-muted-foreground">
              <tr className="border-b border-white/10">
                <th className="py-1.5">Empresa</th>
                <th className="py-1.5 text-right">Valor</th>
                <th className="py-1.5 text-right">Contratos</th>
                <th className="py-1.5 text-right">Entidades</th>
                <th className="py-1.5 text-right">D_i</th>
                <th className="py-1.5">Maior comprador</th>
                <th className="py-1.5" />
              </tr>
            </thead>
            <tbody>
              {dados.empresas.map((empresa) => (
                <tr key={empresa.nif} className="border-b border-white/5 hover:bg-white/[0.04]">
                  <td className="max-w-[230px] truncate py-1.5" title={empresa.nome}>
                    {empresa.nome}
                  </td>
                  <td className="py-1.5 text-right font-mono">{formatCompactEuro(empresa.valor)}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(empresa.contratos)}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(empresa.entidades_distintas)}</td>
                  <td className="py-1.5 text-right font-mono">{empresa.dependencia?.hhi !== undefined ? empresa.dependencia.hhi.toFixed(3) : "—"}</td>
                  <td className="max-w-[220px] truncate py-1.5" title={empresa.maior_entidade?.nome ?? undefined}>
                    {empresa.maior_entidade?.nome ?? "—"}{" "}
                    {empresa.maior_entidade?.quota !== undefined ? (
                      <span className="font-mono text-[10.5px] text-muted-foreground">{formatPct(empresa.maior_entidade.quota, 0)}</span>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-right">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => onAbrirFicha(empresa.nif)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                      >
                        ficha
                      </button>
                      <button
                        type="button"
                        onClick={() => onVerEvidencias({ nifs: [empresa.nif] }, `Contratos · ${empresa.nome}`)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                      >
                        contratos
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Entidade → fornecedores" subtitle="Exposição da entidade a cada fornecedor e alternativas já observadas no escopo" icon={Building2}>
        <div className="space-y-2">
          {dados.entidades.map((entidade) => (
            <article key={entidade.nif} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
              <header className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[12.5px]" title={entidade.nome}>
                    {entidade.nome}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {formatCompactEuro(entidade.valor)} · {formatNumber(entidade.contratos)} contratos · {formatNumber(entidade.fornecedores)} fornecedores · D{" "}
                    {entidade.dependencia?.hhi !== undefined ? entidade.dependencia.hhi.toFixed(3) : "—"}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {entidade.critico ? <Chip tone="rose">maior fornecedor ≥ 60 %</Chip> : null}
                  {entidade.cpv_principal ? <Chip tone="violet">CPV {entidade.cpv_principal.classe}</Chip> : null}
                  <button
                    type="button"
                    onClick={() => onVerEvidencias({ comprador_nif: entidade.nif }, `Contratos · ${entidade.nome}`)}
                    className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                  >
                    contratos
                  </button>
                </div>
              </header>
              <div className="mt-2 grid gap-2 text-[11.5px] lg:grid-cols-2">
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <p className="text-muted-foreground">Maior fornecedor</p>
                  <p className="truncate" title={entidade.maior_fornecedor?.nome ?? undefined}>
                    {entidade.maior_fornecedor?.nome ?? "—"}{" "}
                    <span className="font-mono text-teal-200">{formatPct(entidade.maior_fornecedor?.quota)}</span>
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <p className="text-muted-foreground">Alternativas observadas</p>
                  <p className="truncate">
                    {entidade.alternativas?.length
                      ? entidade.alternativas.map((alternativa) => `${alternativa.nome} (${formatPct(alternativa.quota, 0)})`).join(" · ")
                      : "sem alternativa no escopo"}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      </SectionCard>

      {dados.notas?.length ? (
        <SectionCard title="Limites de leitura" subtitle="o que a concentração não prova" icon={AlertTriangle}>
          <ul className="space-y-1 text-[11.5px] text-muted-foreground">
            {dados.notas.map((nota) => (
              <li key={nota}>· {nota}</li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
      <button
        type="button"
        onClick={onRecarregar}
        disabled={aCarregar}
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
      >
        {aCarregar ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
        Recalcular dependências
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ Grafo */

function Grafo({
  grafo,
  resposta,
  noAtual,
  layout,
  setLayout,
  aDesenhar,
  onDesenhar,
  onSelecionar,
  onVerEvidencias,
}: {
  grafo: StudioGraph | null;
  resposta: MercadoGrafo | null;
  noAtual: MercadoGrafo["nodes"][number] | null;
  layout: "hierarchical" | "network" | "circular";
  setLayout: (layout: "hierarchical" | "network" | "circular") => void;
  aDesenhar: boolean;
  onDesenhar: () => void;
  onSelecionar: (id: string | null) => void;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string; nifs?: string[] }, titulo: string) => void;
}) {
  return (
    <SectionCard
      title="Grafo temporal · empresa → contrato → entidade → CPV → CAE"
      subtitle="As cinco camadas do modelo, com as relações datadas: atividade registada, vende neste mercado, contrata com, adjudicado a, comprado por"
      icon={GitBranch}
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          {(["hierarchical", "network", "circular"] as const).map((opcao) => (
            <button
              key={opcao}
              type="button"
              onClick={() => setLayout(opcao)}
              className={`rounded-lg border px-2 py-1 text-[11.5px] transition ${
                layout === opcao ? "border-teal-400/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.04] hover:bg-white/[0.09]"
              }`}
            >
              {opcao === "hierarchical" ? "hierarquia" : opcao === "network" ? "rede" : "círculo"}
            </button>
          ))}
          <button
            type="button"
            onClick={onDesenhar}
            disabled={aDesenhar}
            className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
          >
            {aDesenhar ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {grafo ? "Reconstruir" : "Construir grafo"}
          </button>
        </div>
      }
    >
      {!grafo ? (
        <EmptyState>
          {aDesenhar
            ? "A construir o grafo…"
            : "O grafo liga as empresas do escopo aos contratos, entidades, classes de CPV e CAE: a espessura é o valor e cada aresta traz a relação observada."}
        </EmptyState>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <GraphCanvas
            graph={grafo}
            layout={layout}
            metric="valor"
            unitLabel="€"
            heightClass="h-[560px]"
            selectedNodeId={noAtual?.id ?? null}
            nodeSummary={(no) => `${no.role ?? no.dimension} · ${formatCompactEuro(no.total_value ?? no.value)} · ${formatNumber(no.count)} contratos`}
            edgeSummary={(aresta) => `${formatCompactEuro(aresta.value)} · ${formatNumber(aresta.count)} contratos`}
            onNodeClick={(no) => onSelecionar(no.id === noAtual?.id ? null : no.id)}
          />
          <aside className="space-y-2 text-xs">
            {resposta?.meta ? (
              <p className="text-[11px] text-muted-foreground">
                {formatNumber(resposta.meta.nodes_returned)} nós · {formatNumber(resposta.meta.edges_returned)} arestas
              </p>
            ) : null}
            {noAtual ? (
              <>
                <p className="font-medium">{noAtual.label}</p>
                <p className="text-muted-foreground">
                  {noAtual.dimension} · {formatCompactEuro(noAtual.total_value)} · {formatNumber(noAtual.count)} contratos
                </p>
                <Linha rotulo="Papel">{noAtual.role}</Linha>
                {noAtual.cae ? <Linha rotulo="CAE">{noAtual.cae}</Linha> : null}
                {noAtual.compatibilidade ? (
                  <Linha rotulo="Compatibilidade">
                    <Chip tone={tomCompatibilidade(noAtual.compatibilidade)}>{noAtual.compatibilidade}</Chip>
                  </Linha>
                ) : null}
                {noAtual.fim ? <Linha rotulo="Fim">{noAtual.fim}</Linha> : null}
                {noAtual.dimension === "empresa" || noAtual.dimension === "entidade" ? (
                  <button
                    type="button"
                    onClick={() =>
                      onVerEvidencias(
                        noAtual.dimension === "entidade" ? { comprador_nif: noAtual.key } : { nifs: [noAtual.key] },
                        `Contratos · ${noAtual.label}`,
                      )
                    }
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                  >
                    <FileSearch size={12} /> ver contratos
                  </button>
                ) : null}
              </>
            ) : (
              <EmptyState>Clique num nó para ver o resumo; as empresas abrem os seus contratos.</EmptyState>
            )}
            {resposta?.meta?.notas?.length ? (
              <ul className="space-y-1 text-[10.5px] text-muted-foreground">
                {resposta.meta.notas.map((nota) => (
                  <li key={nota}>· {nota}</li>
                ))}
              </ul>
            ) : null}
          </aside>
        </div>
      )}
    </SectionCard>
  );
}

/* ------------------------------------------------------------- Evidências */

function Evidencias({ dados, titulo, aCarregar, onProcurar }: { dados: MercadoEvidencias | null; titulo: string | null; aCarregar: boolean; onProcurar: () => void }) {
  return (
    <SectionCard
      title={titulo ?? "Evidências"}
      subtitle="Os contratos que sustentam os indicadores — cada leitura chega ao dado de origem"
      icon={FileSearch}
      actions={
        <button
          type="button"
          onClick={onProcurar}
          disabled={aCarregar}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
        >
          {aCarregar ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          contratos do escopo
        </button>
      }
    >
      {!dados ? (
        <EmptyState>Clique em «ver contratos» num indicador para listar os contratos que o sustentam.</EmptyState>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground">{formatNumber(dados.total)} contratos no escopo dos filtros (a mostrar até 25).</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-[11.5px]">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-white/10">
                  <th className="py-1.5">Contrato</th>
                  <th className="py-1.5">Objeto</th>
                  <th className="py-1.5 text-right">Valor</th>
                  <th className="py-1.5">Data</th>
                  <th className="py-1.5">Adjudicante</th>
                  <th className="py-1.5">Adjudicatário</th>
                  <th className="py-1.5">CPV</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens?.map((item) => (
                  <tr key={item.idcontrato} className="border-b border-white/5">
                    <td className="py-1.5 font-mono">{item.idcontrato}</td>
                    <td className="max-w-[280px] truncate py-1.5" title={item.objeto ?? undefined}>
                      {item.objeto ?? "—"}
                    </td>
                    <td className="py-1.5 text-right font-mono">{formatCompactEuro(item.valor)}</td>
                    <td className="py-1.5">{item.data ?? item.ano ?? "—"}</td>
                    <td className="max-w-[170px] truncate py-1.5" title={item.adjudicante}>
                      {item.adjudicante}
                    </td>
                    <td className="max-w-[170px] truncate py-1.5" title={item.adjudicatario}>
                      {item.adjudicatario}
                    </td>
                    <td className="py-1.5 font-mono">{item.cpv ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

/* ------------------------------------------------------------------ Notas */

function Notas({ meta }: { meta: MercadoMeta }) {
  return (
    <SectionCard title="Como este módulo mede" subtitle={meta.titulo} icon={TrendingUp} className="mt-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Indicadores</p>
          {meta.indicadores.map((indicador) => (
            <Linha key={indicador.id} rotulo={indicador.label}>
              <span className="font-mono">{indicador.formula}</span>
            </Linha>
          ))}
        </div>
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Camadas</p>
          {meta.arquitetura.map((camada) => (
            <Linha key={camada.camada} rotulo={camada.label}>
              <span className="text-[10.5px] text-muted-foreground">{camada.detalhe}</span>
            </Linha>
          ))}
        </div>
      </div>
      {meta.limites?.length ? (
        <ul className="mt-3 space-y-1 text-[11px] text-muted-foreground">
          {meta.limites.map((limite) => (
            <li key={limite}>· {limite}</li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  );
}
