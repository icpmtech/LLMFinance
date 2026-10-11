/**
 * Lorenz 1963 · dinâmica da contratação pública — página do módulo.
 *
 * Segue o modelo pedido, em seis leituras:
 *
 * 1. **Panorama** — estado observado do escopo (contratos, valor, compradores,
 *    fornecedores, concentração, ajuste direto), regime do sistema e alertas.
 * 2. **Sensibilidade** — mapa discreto `s(t+1) = A·s(t) + b` ajustado à série,
 *    divergência `D_t` entre trajetórias vizinhas, expoente de Lyapunov empírico
 *    e o sistema de Lorenz com parâmetros análogos medidos na estrutura.
 * 3. **Propagação** — perturbação de um fornecedor (atraso de 7/30/60 dias):
 *    compradores afetados, exposição, dificuldade de substituição, sobrecusto
 *    potencial, segunda ordem da realocação e mitigações.
 * 4. **CPV** — concentração e fragilidade por classe de CPV.
 * 5. **Entidades** — compradores mais frágeis e quem mais amplifica.
 * 6. **Grafo** — o grafo comprador↔fornecedor desenhado a pedido.
 *
 * Toda a leitura traz `evidencias` (contratos reais) porque o modelo **não
 * prevê** o futuro: identifica riscos emergentes e mostra os dados que os
 * sustentam.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
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
  Share2,
  Sparkles,
  Target,
  TrendingUp,
  Waves,
  Zap,
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

import {
  getLorenzAreas,
  getLorenzCpv,
  getLorenzEvidencias,
  getLorenzGrafo,
  getLorenzMeta,
  getLorenzPanorama,
  getLorenzPropagacao,
  guardarLorenzExecucao,
  type LorenzAlerta,
  type LorenzArea,
  type LorenzComprador,
  type LorenzCpvClasse,
  type LorenzEscopoParams,
  type LorenzEvidencias,
  type LorenzGrafo,
  type LorenzMeta,
  type LorenzPanorama,
  type LorenzPropagacao,
} from "../lorenzApi";
import { Chip, EmptyState, Kpi, Loading, SectionCard, formatCompactEuro, formatNumber, formatPct } from "../components/padroes/padroesKit";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { toStudioGraph, type StudioGraph } from "../components/graph/graphStudio";

type Seccao = "panorama" | "sensibilidade" | "propagacao" | "cpv" | "entidades" | "grafo";

const SECCOES: { id: Seccao; label: string; icon: typeof Activity; hint: string }[] = [
  { id: "panorama", label: "Panorama", icon: Activity, hint: "Estado observado, regime e alertas" },
  { id: "sensibilidade", label: "Sensibilidade", icon: Waves, hint: "Divergência, Lyapunov e sistema de Lorenz" },
  { id: "propagacao", label: "Propagação", icon: Zap, hint: "Atrasos de 7/30/60 dias e efeitos em cadeia" },
  { id: "cpv", label: "CPV", icon: Layers, hint: "Concentração e fragilidade por classe de CPV" },
  { id: "entidades", label: "Entidades", icon: Building2, hint: "Quem depende de quem e quem amplifica" },
  { id: "grafo", label: "Grafo", icon: GitBranch, hint: "Grafo comprador↔fornecedor desenhado a pedido" },
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

/* --------------------------------------------------------------- formatadores */
function corServidade(severidade: string): string {
  if (severidade === "alta") return "rose";
  if (severidade === "média") return "amber";
  return "neutral";
}

function tomRegime(regime?: string | null): string {
  return regime === "amplificador" || regime === "sensivel" ? "amber" : "teal";
}

function rotuloRegime(regime?: string | null): string {
  if (regime === "amplificador") return "Amplificador (margem > 1)";
  if (regime === "dissipador") return "Dissipador (margem < 1)";
  if (regime === "sensivel") return "Sensível (λ > 0)";
  return "—";
}

/* ------------------------------------------------------------------- página */
export default function LorenzPage() {
  const [meta, setMeta] = useState<LorenzMeta | null>(null);
  const [areasDisponiveis, setAreasDisponiveis] = useState<LorenzArea[]>([]);
  const [seccao, setSeccao] = useState<Seccao>("panorama");

  /* escopo */
  const [area, setArea] = useState("todas");
  const [cpvLivre, setCpvLivre] = useState("");
  const [anoDe, setAnoDe] = useState<string>("");
  const [anoAte, setAnoAte] = useState<string>("");
  const [regiao, setRegiao] = useState("");
  const [nif, setNif] = useState("");
  const [texto, setTexto] = useState("");

  /* dados */
  const [dados, setDados] = useState<LorenzPanorama | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [aGravar, setAGravar] = useState(false);

  /* propagação */
  const [fornecedorSel, setFornecedorSel] = useState("");
  const [atraso, setAtraso] = useState(30);
  const [propagacao, setPropagacao] = useState<LorenzPropagacao | null>(null);
  const [aPropagar, setAPropagar] = useState(false);

  /* evidências + grafo */
  const [evidencias, setEvidencias] = useState<LorenzEvidencias | null>(null);
  const [evidenciaTitulo, setEvidenciaTitulo] = useState<string | null>(null);
  const [aProcurarEvidencia, setAProcurarEvidencia] = useState(false);
  const [grafoResposta, setGrafoResposta] = useState<LorenzGrafo | null>(null);
  const [aDesenharGrafo, setADesenharGrafo] = useState(false);
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("hierarchical");

  const params = useMemo<LorenzEscopoParams>(() => {
    const limpo: LorenzEscopoParams = { area };
    if (cpvLivre.trim()) limpo.cpv = cpvLivre.trim();
    if (anoDe) limpo.ano_de = Number(anoDe);
    if (anoAte) limpo.ano_ate = Number(anoAte);
    if (regiao) limpo.regiao = regiao;
    if (nif.trim()) limpo.nif = nif.trim();
    if (texto.trim()) limpo.texto = texto.trim();
    return limpo;
  }, [anoAte, anoDe, area, cpvLivre, nif, regiao, texto]);

  /* ------------------------------------------------------------- carregamentos */
  useEffect(() => {
    let cancelado = false;
    getLorenzMeta()
      .then((resposta) => {
        if (cancelado) return;
        setMeta(resposta);
        setAreasDisponiveis(resposta.areas);
      })
      .catch(() => {
        /* o meta é acessório: a página funciona sem ele */
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

  const carregar = useCallback(async () => {
    setACarregar(true);
    setErro(null);
    setAviso(null);
    setEvidencias(null);
    setEvidenciaTitulo(null);
    setGrafoResposta(null);
    try {
      const resposta = await getLorenzPanorama(params);
      setDados(resposta);
      setPropagacao(null);
      const primeiro = resposta.amplificadores?.[0];
      setFornecedorSel(primeiro?.nif ? String(primeiro.nif) : "");
    } catch (falha) {
      setDados(null);
      setErro(falha instanceof Error ? falha.message : "Erro ao calcular o panorama");
    } finally {
      setACarregar(false);
    }
  }, [params]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const propagar = useCallback(
    async (fornecedorNif?: string, dias?: number) => {
      const alvo = fornecedorNif ?? fornecedorSel;
      if (!alvo) return;
      setAPropagar(true);
      setErro(null);
      try {
        const resposta = await getLorenzPropagacao({ ...params, fornecedor_nif: alvo, atraso_dias: dias ?? atraso });
        setPropagacao(resposta);
        setEvidencias(resposta.evidencias ?? null);
        setEvidenciaTitulo(resposta.origem?.nome ? `Contratos com ${resposta.origem.nome}` : null);
      } catch (falha) {
        setPropagacao(null);
        setErro(falha instanceof Error ? falha.message : "Erro ao simular a propagação");
      } finally {
        setAPropagar(false);
      }
    },
    [atraso, fornecedorSel, params],
  );

  const procurarEvidencias = useCallback(
    async (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string }, titulo: string) => {
      setAProcurarEvidencia(true);
      try {
        const resposta = await getLorenzEvidencias({ ...params, ...filtros, limite: 15 });
        setEvidencias(resposta);
        setEvidenciaTitulo(titulo);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao procurar evidências");
      } finally {
        setAProcurarEvidencia(false);
      }
    },
    [params],
  );

  const desenharGrafo = useCallback(async () => {
    setADesenharGrafo(true);
    try {
      const resposta = await getLorenzGrafo({ ...params, limite_fornecedores: 45 });
      setGrafoResposta(resposta);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao construir o grafo");
    } finally {
      setADesenharGrafo(false);
    }
  }, [params]);

  const gravarExecucao = useCallback(async () => {
    setAGravar(true);
    setErro(null);
    try {
      const etiqueta = areasDisponiveis.find((item) => item.id === area)?.label ?? area;
      const resposta = await guardarLorenzExecucao({ ...params, titulo: `Lorenz · ${etiqueta}` });
      setAviso(`Execução guardada (${resposta.run_id}).`);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao guardar a execução (é preciso sessão)");
    } finally {
      setAGravar(false);
    }
  }, [area, areasDisponiveis, params]);

  const studioGraph = useMemo<StudioGraph | null>(() => toStudioGraph(grafoResposta as never, "valor"), [grafoResposta]);

  const serieGrafico = useMemo(
    () =>
      (dados?.serie.periodos ?? []).map((periodo) => ({
        periodo: periodo.periodo,
        contratos: periodo.contratos,
        valor: periodo.valor,
        concentracao: periodo.quota_top1,
        cauda: periodo.cauda,
      })),
    [dados],
  );

  const divergenciaGrafico = useMemo(() => {
    const serie = dados?.dinamica.divergencia?.D;
    if (!serie) return [];
    return serie.map((valor, indice) => ({ passo: indice, D: valor }));
  }, [dados]);

  const lorenzGrafico = useMemo(
    () =>
      (dados?.dinamica.lorenz?.trajetoria ?? []).map((ponto) => ({ x: ponto[0], y: ponto[1], z: ponto[2] })),
    [dados],
  );

  const estadoGrafico = useMemo(
    () =>
      (dados?.estado.coordenadas ?? []).map((linha, indice) => ({
        periodo: dados?.estado.periodos?.[indice] ?? String(indice),
        atividade: linha[0],
        dependencia: linha[1],
        cauda: linha[2],
      })),
    [dados],
  );

  /* ------------------------------------------------------------------- ecrã */
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden text-foreground">
      {/* Cabeçalho */}
      <header className="shrink-0 border-b border-white/10 bg-white/[0.02] px-4 py-3 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <Sparkles size={18} className="text-teal-300" />
              Lorenz 1963 · dinâmica da contratação pública
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {meta?.descricao ??
                "Sensibilidade às condições iniciais, propagação de perturbações e cenários alternativos no grafo comprador↔fornecedor."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {dados && (
              <Chip tone={tomRegime(dados.kpis.regime_lorenz)} title="Regime do sistema face à fronteira de instabilidade">
                {rotuloRegime(dados.kpis.regime_lorenz)}
              </Chip>
            )}
            <button
              type="button"
              onClick={() => void carregar()}
              disabled={aCarregar}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1] disabled:opacity-50"
            >
              {aCarregar ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Recalcular
            </button>
            <button
              type="button"
              onClick={() => void gravarExecucao()}
              disabled={aGravar || !dados}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1] disabled:opacity-50"
              title="Guardar esta execução (exige sessão)"
            >
              {aGravar ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
              Guardar
            </button>
          </div>
        </div>

        {/* Escopo */}
        <div className="mt-3 flex flex-wrap items-end gap-2 text-[11.5px]">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Área</span>
            <select
              value={area}
              onChange={(evento) => setArea(evento.target.value)}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            >
              {areasDisponiveis.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">CPV (prefixos)</span>
            <input
              value={cpvLivre}
              onChange={(evento) => setCpvLivre(evento.target.value)}
              placeholder="ex.: 336,45"
              className="w-32 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
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
            <select
              value={regiao}
              onChange={(evento) => setRegiao(evento.target.value)}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            >
              {REGIOES.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">NIF</span>
            <input
              value={nif}
              onChange={(evento) => setNif(evento.target.value.replace(/\D/g, "").slice(0, 9))}
              placeholder="500000000"
              className="w-28 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex min-w-[160px] flex-1 flex-col gap-1">
            <span className="text-muted-foreground">Texto no objeto/partes</span>
            <input
              value={texto}
              onChange={(evento) => setTexto(evento.target.value)}
              placeholder="ex.: manutenção de equipamento"
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
        </div>

        {/* Secções */}
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
                  ativo
                    ? "border-teal-400/40 bg-teal-400/15 text-teal-100"
                    : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.08]"
                }`}
              >
                <Icone size={13} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </header>

      {/* Corpo */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {erro && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle size={15} />
            {erro}
          </div>
        )}
        {aviso && (
          <div className="mb-3 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-xs text-teal-100">{aviso}</div>
        )}
        {aCarregar && !dados ? <Loading label="A medir o estado, as dependências e a dinâmica…" /> : null}
        {!aCarregar && !dados && !erro ? (
          <EmptyState>Escolha uma área (ou «Todas as áreas») e recarregue para medir o escopo.</EmptyState>
        ) : null}

        {dados && seccao === "panorama" ? (
          <Panorama
            dados={dados}
            serieGrafico={serieGrafico}
            estadoGrafico={estadoGrafico}
            onVerEvidencias={procurarEvidencias}
          />
        ) : null}

        {dados && seccao === "sensibilidade" ? (
          <Sensibilidade dados={dados} divergenciaGrafico={divergenciaGrafico} lorenzGrafico={lorenzGrafico} estadoGrafico={estadoGrafico} />
        ) : null}

        {dados && seccao === "propagacao" ? (
          <Propagacao
            dados={dados}
            fornecedorSel={fornecedorSel}
            setFornecedorSel={setFornecedorSel}
            atraso={atraso}
            setAtraso={setAtraso}
            propagacao={propagacao}
            aPropagar={aPropagar}
            onSimular={propagar}
          />
        ) : null}

        {dados && seccao === "cpv" ? (
          <Cpv
            params={params}
            dados={dados}
            onVerEvidencias={procurarEvidencias}
            carregarMais={async () => {
              const resposta = await getLorenzCpv(params);
              setDados({ ...dados, cpvs: resposta });
            }}
          />
        ) : null}

        {dados && seccao === "entidades" ? (
          <Entidades dados={dados} onVerEvidencias={procurarEvidencias} onPropagar={(nifAlvo) => { setSeccao("propagacao"); setFornecedorSel(nifAlvo); void propagar(nifAlvo); }} />
        ) : null}

        {dados && seccao === "grafo" ? (
          <Grafo
            grafo={studioGraph}
            aDesenhar={aDesenharGrafo}
            layout={layout}
            setLayout={setLayout}
            onDesenhar={desenharGrafo}
            resumo={grafoResposta?.meta as Record<string, unknown> | undefined}
            onVerEvidencias={procurarEvidencias}
          />
        ) : null}

        {/* Evidências (transversal às secções) */}
        {evidencias && (
          <div className="mt-4">
            <SectionCard
              title={evidenciaTitulo ?? "Evidências"}
              subtitle={`${formatNumber(evidencias.total)} contratos no escopo · mostram-se os maiores`}
              icon={FileSearch}
              actions={
                <button
                  type="button"
                  onClick={() => {
                    setEvidencias(null);
                    setEvidenciaTitulo(null);
                  }}
                  className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.1]"
                >
                  Fechar
                </button>
              }
            >
              {aProcurarEvidencia ? (
                <Loading label="A procurar contratos…" />
              ) : evidencias.itens.length === 0 ? (
                <EmptyState>Sem contratos para estes filtros.</EmptyState>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] border-collapse text-left text-xs">
                    <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-2 py-1.5 font-medium">Nº</th>
                        <th className="px-2 py-1.5 font-medium">Objeto</th>
                        <th className="px-2 py-1.5 font-medium">Adjudicante</th>
                        <th className="px-2 py-1.5 font-medium">Adjudicatário</th>
                        <th className="px-2 py-1.5 font-medium">CPV</th>
                        <th className="px-2 py-1.5 text-right font-medium">Valor</th>
                        <th className="px-2 py-1.5 text-right font-medium">Data</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evidencias.itens.map((item) => (
                        <tr key={item.idcontrato} className="border-t border-white/5">
                          <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[10.5px] text-muted-foreground">{item.idcontrato}</td>
                          <td className="max-w-[320px] px-2 py-1.5">
                            <span className="line-clamp-2" title={item.objeto ?? ""}>
                              {item.objeto || "—"}
                            </span>
                          </td>
                          <td className="max-w-[200px] px-2 py-1.5 text-muted-foreground">
                            <span className="line-clamp-1" title={item.adjudicante}>
                              {item.adjudicante || "—"}
                            </span>
                          </td>
                          <td className="max-w-[200px] px-2 py-1.5 text-muted-foreground">
                            <span className="line-clamp-1" title={item.adjudicatario}>
                              {item.adjudicatario || "—"}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-2 py-1.5 text-muted-foreground">{item.cpv || "—"}</td>
                          <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{formatCompactEuro(item.valor)}</td>
                          <td className="whitespace-nowrap px-2 py-1.5 text-right text-muted-foreground">
                            {(item.data ?? "").slice(0, 10) || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          </div>
        )}

        {meta?.notas?.length ? (
          <div className="mt-4 space-y-1.5">
            {meta.notas.map((nota) => (
              <EmptyState key={nota}>{nota}</EmptyState>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- 1. Panorama */
function Panorama({
  dados,
  serieGrafico,
  estadoGrafico,
  onVerEvidencias,
}: {
  dados: LorenzPanorama;
  serieGrafico: { periodo: string; contratos: number; valor: number; concentracao: number; cauda: number }[];
  estadoGrafico: { periodo: string; atividade: number; dependencia: number; cauda: number }[];
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string }, titulo: string) => void;
}) {
  const kpis = dados.kpis;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={FileSearch} label="Contratos no escopo" value={formatNumber(kpis.contratos)} sub={`${kpis.periodos} períodos · ${kpis.primeiro_periodo}–${kpis.ultimo_periodo}`} />
        <Kpi icon={Coins} label="Valor contratado" value={formatCompactEuro(kpis.valor)} sub={`média ${formatCompactEuro(kpis.valor_medio)}`} color="text-amber-300" glow="glow-amber" />
        <Kpi icon={Gauge} label="Concentração média (top1)" value={formatPct(kpis.quota_top1_media)} sub={`HHI médio ${kpis.hhi_medio.toFixed(3)} · ${kpis.compradores_analisados} compradores`} color="text-sky-300" glow="glow-blue" />
        <Kpi icon={Target} label="Sem concurso (ajuste direto)" value={formatPct(kpis.taxa_ajuste_direto)} sub={`${kpis.cpvs_single_source} de ${kpis.cpvs_analisados} CPV com um só fornecedor`} color="text-rose-300" glow="glow-rose" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <SectionCard title="Estado observado por período" subtitle="Contratos (barras) e valor (linha) — o que o sistema fez, não o que fará" icon={TrendingUp}>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={serieGrafico} margin={{ left: 4, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="periodo" stroke="#9aa0aa" fontSize={11} />
                <YAxis yAxisId="contratos" stroke="#9aa0aa" fontSize={11} tickFormatter={(valor) => formatNumber(Number(valor))} />
                <YAxis yAxisId="valor" orientation="right" stroke="#9aa0aa" fontSize={11} tickFormatter={(valor) => formatCompactEuro(Number(valor))} />
                <Tooltip
                  contentStyle={{ background: "#0f1218", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }}
                  formatter={(valor, nome) => (nome === "valor" ? formatCompactEuro(Number(valor)) : formatNumber(Number(valor)))}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="contratos" dataKey="contratos" name="Contratos" fill="#2dd4bf" radius={[4, 4, 0, 0]} maxBarSize={26} />
                <Line yAxisId="valor" type="monotone" dataKey="valor" name="Valor" stroke="#fbbf24" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Coeficiente de dependência por período (quota do maior fornecedor):{" "}
            {serieGrafico.map((linha) => `${linha.periodo} ${(linha.concentracao * 100).toFixed(1)} %`).join(" · ") || "—"}
          </p>
        </SectionCard>

        <div className="space-y-3">
          <SectionCard title="Regime do sistema" subtitle="Medido na estrutura, comparado com a fronteira de instabilidade" icon={Gauge}>
            <dl className="space-y-2 text-xs">
              <Linha rotulo="σ (oferta/procura)" valor={dados.dinamica.lorenz?.parametros.sigma?.toFixed(2) ?? "—"} />
              <Linha rotulo="β (dissipação)" valor={dados.dinamica.lorenz?.parametros.beta?.toFixed(2) ?? "—"} />
              <Linha rotulo="ρ / ρ crítico" valor={`${dados.dinamica.lorenz?.parametros.rho?.toFixed(1) ?? "—"} / ${dados.dinamica.lorenz?.parametros.rho_critico?.toFixed(1) ?? "—"}`} />
              <Linha rotulo="Margem sobre a fronteira" valor={dados.dinamica.lorenz?.parametros.margem?.toFixed(2) ?? "—"} />
              <Linha rotulo="λ do sistema (Lorenz)" valor={dados.dinamica.lorenz?.lyapunov.lambda?.toFixed(3) ?? "—"} />
              <Linha rotulo="λ empírico (dados)" valor={dados.dinamica.divergencia?.lambda_empirico?.toFixed(3) ?? "—"} />
            </dl>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Chip tone={tomRegime(kpis.regime_lorenz)}>{rotuloRegime(kpis.regime_lorenz)}</Chip>
              <Chip tone={tomRegime(kpis.regime_dados)}>{rotuloRegime(kpis.regime_dados)}</Chip>
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">{dados.dinamica.lorenz?.parametros.nota}</p>
          </SectionCard>

          <SectionCard title="Coordenadas do estado (normalizadas)" subtitle="atividade · dependência · cauda" icon={BarChart3}>
            <div className="h-[180px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={estadoGrafico} margin={{ left: 4, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="periodo" stroke="#9aa0aa" fontSize={11} />
                  <YAxis stroke="#9aa0aa" fontSize={11} />
                  <Tooltip contentStyle={{ background: "#0f1218", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} />
                  <Line type="monotone" dataKey="atividade" stroke="#2dd4bf" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="dependencia" stroke="#fbbf24" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="cauda" stroke="#f472b6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </SectionCard>
        </div>
      </div>

      <SectionCard
        title="Alertas emergentes"
        subtitle={`${dados.dependencias.alertas.length} sinais · dependência ${dados.dependencias.alertas_por_origem?.dependencia ?? 0} · CPV ${
          dados.dependencias.alertas_por_origem?.cpv ?? 0
        } · amplificação ${dados.dependencias.alertas_por_origem?.amplificacao ?? 0}`}
        icon={AlertTriangle}
      >
        {dados.dependencias.alertas.length === 0 ? (
          <EmptyState>Sem concentração anómala neste escopo — o mercado está disperso.</EmptyState>
        ) : (
          <ul className="space-y-2">
            {dados.dependencias.alertas.map((alerta, indice) => (
              <li key={`${alerta.tipo}-${alerta.entidade}-${indice}`} className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={corServidade(alerta.severidade)}>{alerta.severidade}</Chip>
                  <span className="text-xs font-medium">{alerta.entidade}</span>
                  <Chip tone="neutral">{alerta.tipo.replace(/_/g, " ")}</Chip>
                </div>
                <p className="mt-1 text-[12px]">{alerta.medida}</p>
                {alerta.detalhe && <p className="text-[11px] text-muted-foreground">{alerta.detalhe}</p>}
                {alerta.nif && alerta.origem === "amplificacao" && (
                  <button
                    type="button"
                    onClick={() => onVerEvidencias({ fornecedor_nif: String(alerta.nif) }, `Contratos com ${alerta.entidade}`)}
                    className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                  >
                    <FileSearch size={11} /> verificar contratos
                  </button>
                )}
                {alerta.origem === "cpv" && (
                  <button
                    type="button"
                    onClick={() =>
                      onVerEvidencias(
                        { cpv_prefixo: String(alerta.entidade).replace(/[^\d]/g, "") },
                        `${alerta.entidade} · contratos`,
                      )
                    }
                    className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                  >
                    <FileSearch size={11} /> verificar contratos
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionCard title="Cobertura da medição" subtitle="o que ficou de fora, para não se ler o resultado como absoluto" icon={Share2}>
          <dl className="space-y-1.5 text-xs">
            {Object.entries(dados.cobertura).map(([chave, valor]) => (
              <Linha key={chave} rotulo={chave.replace(/_/g, " ")} valor={typeof valor === "number" ? formatNumber(valor) : "—"} />
            ))}
            <Linha rotulo="tempo de cálculo" valor={`${dados.duracao_s.toFixed(2)} s`} />
          </dl>
        </SectionCard>
        <SectionCard title="Hipóteses do modelo" subtitle="tudo o que não vem dos dados está escrito" icon={Waves}>
          <ul className="space-y-1.5 text-[11.5px] text-muted-foreground">
            {dados.hipoteses.map((hipotese) => (
              <li key={hipotese} className="flex gap-2">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-300/70" />
                {hipotese}
              </li>
            ))}
            {dados.notas.map((nota) => (
              <li key={nota} className="flex gap-2">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300/70" />
                {nota}
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>
    </div>
  );
}

/* -------------------------------------------------------- 2. Sensibilidade */
function Sensibilidade({
  dados,
  divergenciaGrafico,
  lorenzGrafico,
  estadoGrafico,
}: {
  dados: LorenzPanorama;
  divergenciaGrafico: { passo: number; D: number }[];
  lorenzGrafico: { x: number; y: number; z: number }[];
  estadoGrafico: { periodo: string; atividade: number; dependencia: number; cauda: number }[];
}) {
  const mapa = dados.dinamica.mapa;
  const divergencia = dados.dinamica.divergencia;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          icon={Waves}
          label="λ empírico (dados)"
          value={divergencia.lambda_empirico !== undefined ? divergencia.lambda_empirico.toFixed(3) : "—"}
          sub={divergencia.regime ? rotuloRegime(divergencia.regime) : divergencia.motivo ?? "série insuficiente"}
          color="text-amber-300"
          glow="glow-amber"
        />
        <Kpi
          icon={Gauge}
          label="Raio espectral do mapa"
          value={mapa.raio_espectral !== undefined ? mapa.raio_espectral.toFixed(3) : "—"}
          sub={mapa.raio_espectral !== undefined && mapa.raio_espectral > 1 ? "> 1 amplifica perturbações" : "≤ 1 contrai perturbações"}
          color="text-sky-300"
          glow="glow-blue"
        />
        <Kpi icon={BarChart3} label="R² do ajuste" value={mapa.r2 !== undefined ? mapa.r2.toFixed(3) : "—"} sub={`${mapa.pares ?? 0} pares de períodos`} />
        <Kpi
          icon={Zap}
          label="λ do sistema (Lorenz)"
          value={dados.dinamica.lorenz?.lyapunov.lambda.toFixed(3) ?? "—"}
          sub={dados.dinamica.lorenz ? rotuloRegime(dados.dinamica.lorenz.lyapunov.regime) : "—"}
          color="text-violet-300"
          glow="glow-rose"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionCard
          title="Divergência entre trajetórias vizinhas"
          subtitle="D(t) = ‖s(A) − s(B)‖: duas simulações partem de estados quase iguais e divergem (ou não) ao longo do tempo"
          icon={Waves}
        >
          {divergenciaGrafico.length === 0 ? (
            <EmptyState tone="warn">{divergencia.motivo ?? "Sem série suficiente para estimar a divergência."}</EmptyState>
          ) : (
            <>
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={divergenciaGrafico} margin={{ left: 4, right: 8, top: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="passo" stroke="#9aa0aa" fontSize={11} />
                    <YAxis scale="log" domain={["auto", "auto"]} stroke="#9aa0aa" fontSize={11} />
                    <Tooltip
                      contentStyle={{ background: "#0f1218", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }}
                      formatter={(valor) => Number(valor).toExponential(3)}
                    />
                    <Line type="monotone" dataKey="D" stroke="#fbbf24" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">{divergencia.nota}</p>
            </>
          )}
        </SectionCard>

        <SectionCard
          title="Sistema de Lorenz (parâmetros análogos)"
          subtitle={`σ=${dados.dinamica.lorenz?.parametros.sigma?.toFixed(2) ?? "—"} · ρ=${dados.dinamica.lorenz?.parametros.rho?.toFixed(1) ?? "—"} · β=${dados.dinamica.lorenz?.parametros.beta?.toFixed(2) ?? "—"} · ρ crítico=${dados.dinamica.lorenz?.parametros.rho_critico?.toFixed(1) ?? "—"}`}
          icon={Activity}
        >
          {lorenzGrafico.length === 0 ? (
            <EmptyState tone="warn">Sem parâmetros suficientes para integrar o sistema.</EmptyState>
          ) : (
            <>
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={lorenzGrafico} margin={{ left: 4, right: 8, top: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="x" stroke="#9aa0aa" fontSize={11} type="number" domain={["auto", "auto"]} />
                    <YAxis stroke="#9aa0aa" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#0f1218", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="x" name="x (atividade)" stroke="#2dd4bf" strokeWidth={1.6} dot={false} />
                    <Line type="monotone" dataKey="y" name="y (dependência)" stroke="#fbbf24" strokeWidth={1.6} dot={false} />
                    <Line type="monotone" dataKey="z" name="z (acumulação)" stroke="#f472b6" strokeWidth={1.6} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">{dados.dinamica.lorenz?.lyapunov.nota}</p>
            </>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Como ler isto" subtitle="o que o modelo afirma e o que não afirma" icon={Sparkles}>
        <ul className="space-y-1.5 text-[11.5px] text-muted-foreground">
          <li>• O mapa discreto é ajustado à **série observada**; com poucos períodos anuais é uma indicação de regime, não um modelo validado fora da amostra.</li>
          <li>• λ &gt; 0 significa que condições iniciais vizinhas se afastam: pequenas diferenças de estrutura passam a importar muito.</li>
          <li>• O sistema de Lorenz clássico não descreve contratos: σ, β e ρ são **análogos** medidos na estrutura (oferta/procura, memória, dependência) e a fronteira ρ crítico é a do sistema original.</li>
          <li>• Nada aqui é previsão: sem stocks, prazos de entrega e criticidade técnica, o que se mede é exposição estrutural.</li>
        </ul>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <MiniMatriz titulo="Matriz A (mapa)" matriz={mapa.A} />
          <MiniMatriz titulo="Vetor b" vetor={mapa.b} />
          <MiniMatriz titulo="Estado normalizado" vetor={dados.kpis.coordenadas ?? undefined} />
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          Série normalizada usada no ajuste: {estadoGrafico.length} períodos ({dados.estado.rotulos?.join(" · ") ?? "atividade · dependência · cauda"}).
        </p>
      </SectionCard>
    </div>
  );
}

/* ----------------------------------------------------------- 3. Propagação */
function Propagacao({
  dados,
  fornecedorSel,
  setFornecedorSel,
  atraso,
  setAtraso,
  propagacao,
  aPropagar,
  onSimular,
}: {
  dados: LorenzPanorama;
  fornecedorSel: string;
  setFornecedorSel: (valor: string) => void;
  atraso: number;
  setAtraso: (valor: number) => void;
  propagacao: LorenzPropagacao | null;
  aPropagar: boolean;
  onSimular: (fornecedorNif?: string, dias?: number) => void;
}) {
  return (
    <div className="space-y-4">
      <SectionCard
        title="Cenário de perturbação"
        subtitle="Escolha o fornecedor a perturbar e o atraso; a cascata usa a dependência observada nos contratos"
        icon={Zap}
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            {[7, 30, 60].map((dias) => (
              <button
                key={dias}
                type="button"
                onClick={() => setAtraso(dias)}
                className={`rounded-lg border px-2.5 py-1 text-[11.5px] transition ${
                  atraso === dias ? "border-amber-400/40 bg-amber-400/15 text-amber-100" : "border-white/10 bg-white/[0.04] hover:bg-white/[0.09]"
                }`}
              >
                {dias} dias
              </button>
            ))}
            <button
              type="button"
              onClick={() => onSimular()}
              disabled={aPropagar || !fornecedorSel}
              className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 transition hover:bg-teal-400/25 disabled:opacity-50"
            >
              {aPropagar ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Simular propagação
            </button>
          </div>
        }
      >
        <div className="flex flex-wrap items-end gap-2 text-[11.5px]">
          <label className="flex min-w-[280px] flex-1 flex-col gap-1">
            <span className="text-muted-foreground">Fornecedor (ordenado por amplificação)</span>
            <select
              value={fornecedorSel}
              onChange={(evento) => setFornecedorSel(evento.target.value)}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            >
              {dados.amplificadores.map((item) => (
                <option key={String(item.nif ?? item.nome)} value={String(item.nif ?? "")}>
                  {item.nome} — amplificação {item.amplificacao.toFixed(3)} · {item.compradores} compradores
                </option>
              ))}
            </select>
          </label>
          <span className="text-muted-foreground">
            prémio de urgência a {atraso} dias: {(100 * (propagacao?.premio_urgencia ?? 0)).toFixed(1)} %
          </span>
        </div>
      </SectionCard>

      {!propagacao ? (
        <EmptyState>Escolha o atraso e carregue em «Simular propagação» para ver a cascata com as evidências.</EmptyState>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi icon={Coins} label="Sobrecusto potencial" value={formatCompactEuro(propagacao.impacto_total_estimado)} sub={`${propagacao.diretos.length} compradores afetados`} color="text-amber-300" glow="glow-amber" />
            <Kpi icon={Building2} label="Compradores críticos" value={formatNumber(propagacao.diretos.filter((linha) => linha.critico).length)} sub={`limiar ${formatPct(0.6)} de dependência`} color="text-rose-300" glow="glow-rose" />
            <Kpi icon={Share2} label="Novos frágeis (2.ª ordem)" value={formatNumber(propagacao.novos_fragies.length)} sub="a realocação desloca a concentração" color="text-violet-300" glow="glow-rose" />
            <Kpi icon={GitBranch} label="Atraso simulado" value={`${propagacao.atraso_dias} dias`} sub={`perda de capacidade ${formatPct(propagacao.perda_capacidade)}`} />
          </div>

          <SectionCard title="Cenários 7 / 30 / 60 dias" subtitle="o mesmo fornecedor, três magnitudes de atraso" icon={BarChart3}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left text-xs">
                <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">Atraso</th>
                    <th className="px-3 py-1.5 text-right font-medium">Prémio</th>
                    <th className="px-3 py-1.5 text-right font-medium">Impacto</th>
                    <th className="px-3 py-1.5 text-right font-medium">Afetados</th>
                    <th className="px-3 py-1.5 text-right font-medium">Críticos</th>
                    <th className="px-3 py-1.5 text-right font-medium">Novos frágeis</th>
                    <th className="px-3 py-1.5 text-right font-medium">vs 7 dias</th>
                  </tr>
                </thead>
                <tbody>
                  {(propagacao.cenarios ?? []).map((linha) => (
                    <tr key={linha.atraso_dias} className="border-t border-white/5">
                      <td className="px-3 py-1.5">{linha.atraso_dias} dias</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(linha.premio)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatCompactEuro(linha.impacto_total)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(linha.compradores_afetados)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(linha.criticos)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(linha.novos_fragies)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{linha.fator_vs_7d ? `${linha.fator_vs_7d.toFixed(2)}×` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard
            title="Entidades afetadas"
            subtitle={`Origem: ${propagacao.origem.nome} (${formatCompactEuro(propagacao.origem.valor)} no escopo)`}
            icon={Building2}
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-left text-xs">
                <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">Comprador</th>
                    <th className="px-3 py-1.5 text-right font-medium">Dependência</th>
                    <th className="px-3 py-1.5 text-right font-medium">Exposto</th>
                    <th className="px-3 py-1.5 text-right font-medium">Dificuldade de substituição</th>
                    <th className="px-3 py-1.5 text-right font-medium">Sobrecusto</th>
                    <th className="px-3 py-1.5 font-medium">Alternativas observadas</th>
                  </tr>
                </thead>
                <tbody>
                  {propagacao.diretos.map((linha) => (
                    <tr key={String(linha.comprador_nif ?? linha.comprador_nome)} className="border-t border-white/5">
                      <td className="px-3 py-1.5">
                        {linha.comprador_nome}
                        {linha.critico && (
                          <span className="ml-2">
                            <Chip tone="rose">crítico</Chip>
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(linha.quota)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatCompactEuro(linha.exposto)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(linha.dificuldade_substituicao)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-amber-200">{formatCompactEuro(linha.sobrecusto_estimado)}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {linha.alternativas.length === 0
                          ? "nenhuma no mesmo CPV"
                          : linha.alternativas
                              .map((alternativa) => `${alternativa.nome} (${formatPct(alternativa.quota)})`)
                              .join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Segunda ordem" subtitle="a procura realocada aumenta a concentração noutros fornecedores" icon={Share2}>
              {propagacao.segunda_ordem.length === 0 ? (
                <EmptyState>Sem realocação relevante (os compradores afetados não têm alternativa observada).</EmptyState>
              ) : (
                <ul className="space-y-2">
                  {propagacao.segunda_ordem.map((linha) => (
                    <li key={String(linha.nif ?? linha.nome)} className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{linha.nome}</span>
                        {linha.nova_dependencia && <Chip tone="amber">passa a frágil</Chip>}
                      </div>
                      <p className="mt-1 text-muted-foreground">
                        recebe {formatCompactEuro(linha.valor_realocado)} de {linha.n_compradores} comprador(es) · nova quota estimada{" "}
                        {formatPct(linha.nova_quota_estimada)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard title="Medidas de mitigação" subtitle="com números e alternativas verificadas nos contratos" icon={Target}>
              <ul className="space-y-2">
                {propagacao.mitigacoes.map((medida, indice) => (
                  <li key={`${medida.entidade}-${indice}`} className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2 text-xs">
                    <p className="font-medium">{medida.entidade}</p>
                    <p className="mt-0.5 text-muted-foreground">{medida.acao}</p>
                  </li>
                ))}
              </ul>
              <div className="mt-3 space-y-1.5">
                {propagacao.hipoteses.map((hipotese) => (
                  <EmptyState key={hipotese}>{hipotese}</EmptyState>
                ))}
              </div>
            </SectionCard>
          </div>

          {propagacao.sensibilidade && (
            <SectionCard
              title="Elasticidade ao choque"
              subtitle={`${propagacao.sensibilidade.inclinacao.toFixed(0)} € de sobrecusto por unidade de perda de capacidade`}
              icon={Gauge}
            >
              <div className="grid gap-3 sm:grid-cols-3">
                {propagacao.sensibilidade.pontos.map((ponto) => (
                  <div key={ponto.perda} className="glass-card rounded-xl p-3">
                    <p className="text-[11px] text-muted-foreground">perda de {formatPct(ponto.perda)}</p>
                    <p className="stat-value text-lg font-bold">{formatCompactEuro(ponto.impacto)}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {ponto.afetados} afetados · {ponto.novos_fragies} novos frágeis
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">{propagacao.sensibilidade.nota}</p>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- 4. CPV */
function Cpv({
  dados,
  onVerEvidencias,
  carregarMais,
}: {
  params: LorenzEscopoParams;
  dados: LorenzPanorama;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string }, titulo: string) => void;
  carregarMais: () => Promise<void>;
}) {
  const classes = dados.cpvs.classes;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi icon={Layers} label="Classes de CPV medidas" value={formatNumber(classes.length)} sub={`${formatNumber(dados.cpvs.single_source)} com um só fornecedor relevante`} />
        <Kpi
          icon={AlertTriangle}
          label="Valor em classes frágeis"
          value={formatCompactEuro(classes.filter((classe) => classe.single_source).reduce((soma, classe) => soma + classe.valor, 0))}
          sub="quota do dominante ≥ 60 %"
          color="text-rose-300"
          glow="glow-rose"
        />
        <Kpi
          icon={Target}
          label="Fragilidade média"
          value={classes.length ? (classes.reduce((soma, classe) => soma + classe.fragilidade, 0) / classes.length).toFixed(3) : "—"}
          sub="quota do topo × (1 − alternativas)"
          color="text-amber-300"
          glow="glow-amber"
        />
      </div>

      <SectionCard
        title="Concentração por classe de CPV"
        subtitle="clique numa linha para ver os contratos que sustentam o número"
        icon={Layers}
        actions={
          <button
            type="button"
            onClick={() => void carregarMais()}
            className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.1]"
          >
            Recalcular CPV
          </button>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1000px] border-collapse text-left text-xs">
            <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 font-medium">Classe</th>
                <th className="px-3 py-1.5 text-right font-medium">Valor</th>
                <th className="px-3 py-1.5 text-right font-medium">Contratos</th>
                <th className="px-3 py-1.5 text-right font-medium">Fornecedores</th>
                <th className="px-3 py-1.5 text-right font-medium">Compradores</th>
                <th className="px-3 py-1.5 text-right font-medium">Quota top1</th>
                <th className="px-3 py-1.5 text-right font-medium">HHI</th>
                <th className="px-3 py-1.5 font-medium">Dominante</th>
                <th className="px-3 py-1.5 text-right font-medium">Fragilidade</th>
                <th className="px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {classes.map((classe) => (
                <tr key={classe.classe} className="border-t border-white/5 hover:bg-white/[0.04]">
                  <td className="whitespace-nowrap px-3 py-1.5 font-mono">{classe.classe}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{formatCompactEuro(classe.valor)}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{formatNumber(classe.contratos)}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{formatNumber(classe.fornecedores.length)}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{classe.compradores !== undefined ? formatNumber(classe.compradores) : "—"}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
                    {formatPct(classe.quota_top1)}
                    {classe.single_source && (
                      <span className="ml-1.5">
                        <Chip tone="rose">1 fonte</Chip>
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{classe.hhi.toFixed(3)}</td>
                  <td className="max-w-[220px] truncate px-3 py-1.5 text-muted-foreground" title={classe.dominante?.nome}>
                    {classe.dominante?.nome ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{classe.fragilidade.toFixed(3)}</td>
                  <td className="px-3 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => onVerEvidencias({ cpv_prefixo: classe.classe }, `CPV ${classe.classe} · contratos maiores`)}
                      className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                    >
                      <FileSearch size={11} /> contratos
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {dados.cpvs.notas?.length ? (
          <div className="mt-3 space-y-1.5">
            {dados.cpvs.notas.map((nota) => (
              <EmptyState key={nota}>{nota}</EmptyState>
            ))}
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}

/* ----------------------------------------------------------- 5. Entidades */
function Entidades({
  dados,
  onVerEvidencias,
  onPropagar,
}: {
  dados: LorenzPanorama;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string }, titulo: string) => void;
  onPropagar: (nifAlvo: string) => void;
}) {
  const compradores: LorenzComprador[] = dados.dependencias.compradores;
  const fornecedores = dados.dependencias.fornecedores;
  return (
    <div className="space-y-4">
      <SectionCard
        title="Quem amplifica mais"
        subtitle="alcance × exposição × dificuldade de substituição — e quais relações contribuem para cada um"
        icon={Zap}
      >
        <ul className="space-y-2">
          {dados.amplificadores.map((linha) => (
            <li key={String(linha.nif ?? linha.nome)} className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium">{linha.nome}</span>
                <Chip tone={linha.amplificacao >= 0.12 ? "rose" : "amber"}>amplificação {linha.amplificacao.toFixed(3)}</Chip>
                <span className="text-[11px] text-muted-foreground">
                  {linha.compradores} compradores · {formatPct(linha.exposicao)} do valor · dificuldade média{" "}
                  {formatPct(linha.dificuldade_media)}
                </span>
                <div className="ml-auto flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => linha.nif && onPropagar(String(linha.nif))}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                  >
                    <Play size={11} /> propagar
                  </button>
                  <button
                    type="button"
                    onClick={() => linha.nif && onVerEvidencias({ fornecedor_nif: String(linha.nif) }, `Contratos com ${linha.nome}`)}
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                  >
                    <FileSearch size={11} /> contratos
                  </button>
                </div>
              </div>
              <div className="mt-2 grid gap-1.5 text-[11px] text-muted-foreground sm:grid-cols-2 xl:grid-cols-3">
                {linha.contribuintes.map((contribuinte) => (
                  <span key={`${linha.nif}-${contribuinte.nif}`}>
                    {contribuinte.comprador}: {formatPct(contribuinte.quota)} da compra · dificuldade{" "}
                    {formatPct(contribuinte.dificuldade_substituicao)}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionCard title="Compradores mais frágeis" subtitle="dependência do maior fornecedor e alternativa disponível no CPV" icon={Building2}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-left text-xs">
              <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Comprador</th>
                  <th className="px-3 py-1.5 text-right font-medium">Quota top1</th>
                  <th className="px-3 py-1.5 text-right font-medium">Alternativa</th>
                  <th className="px-3 py-1.5 text-right font-medium">Fragilidade</th>
                  <th className="px-3 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {compradores.slice(0, 25).map((comprador) => (
                  <tr key={String(comprador.nif ?? comprador.nome)} className="border-t border-white/5">
                    <td className="max-w-[240px] px-3 py-1.5">
                      <span className="line-clamp-1" title={comprador.nome}>
                        {comprador.nome}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(comprador.quota_top1)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(comprador.alternativa_top1 ?? 0)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{(comprador.fragilidade ?? 0).toFixed(3)}</td>
                    <td className="px-3 py-1.5 text-right">
                      <button
                        type="button"
                        onClick={() => comprador.nif && onVerEvidencias({ comprador_nif: String(comprador.nif) }, `Contratos de ${comprador.nome}`)}
                        className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] hover:bg-white/[0.09]"
                      >
                        <FileSearch size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Fornecedores mais expostos" subtitle="valor no escopo, quota máxima num comprador e quantos dependem dele" icon={Share2}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-left text-xs">
              <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Fornecedor</th>
                  <th className="px-3 py-1.5 text-right font-medium">Valor</th>
                  <th className="px-3 py-1.5 text-right font-medium">Quota máx.</th>
                  <th className="px-3 py-1.5 text-right font-medium">Compradores</th>
                  <th className="px-3 py-1.5 text-right font-medium">Depend. média</th>
                </tr>
              </thead>
              <tbody>
                {fornecedores.slice(0, 25).map((fornecedor) => (
                  <tr key={String(fornecedor.nif ?? fornecedor.nome)} className="border-t border-white/5">
                    <td className="max-w-[240px] px-3 py-1.5">
                      <span className="line-clamp-1" title={fornecedor.nome}>
                        {fornecedor.nome}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatCompactEuro(fornecedor.valor)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(fornecedor.quota_max ?? 0)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(fornecedor.n_compradores ?? 0)}</td>                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPct(fornecedor.dependencia_media ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 6. Grafo */
function Grafo({
  grafo,
  aDesenhar,
  layout,
  setLayout,
  onDesenhar,
  resumo,
  onVerEvidencias,
}: {
  grafo: StudioGraph | null;
  aDesenhar: boolean;
  layout: "network" | "hierarchical" | "circular";
  setLayout: (valor: "network" | "hierarchical" | "circular") => void;
  onDesenhar: () => void;
  resumo?: Record<string, unknown>;
  onVerEvidencias: (filtros: { comprador_nif?: string; fornecedor_nif?: string; cpv_prefixo?: string }, titulo: string) => void;
}) {
  const [selecionado, setSelecionado] = useState<string | null>(null);
  const noSelecionado = useMemo(
    () => grafo?.nodes.find((no) => no.id === selecionado) ?? null,
    [grafo, selecionado],
  );
  return (
    <div className="space-y-4">
      <SectionCard
        title="Grafo comprador ↔ fornecedor"
        subtitle="o desenho é caro: construa-o a pedido"
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
              ? "A construir o grafo comprador↔fornecedor…"
              : "O grafo mostra os maiores compradores do escopo e os seus fornecedores; a espessura da ligação é o valor e cada aresta traz a quota do fornecedor no comprador."}
          </EmptyState>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
            <GraphCanvas
              graph={grafo}
              layout={layout}
              metric="valor"
              unitLabel="€"
              heightClass="h-[560px]"
              selectedNodeId={selecionado}
              nodeSummary={(no) =>
                `${no.role ?? no.dimension} · ${formatCompactEuro(no.total_value)} · ${formatNumber(no.count)} contratos`
              }
              edgeSummary={(aresta) => `${formatCompactEuro(aresta.value)} · ${formatNumber(aresta.count)} contratos`}
              onNodeClick={(no) => setSelecionado((atual) => (atual === no.id ? null : no.id))}
            />
            <div className="space-y-2 text-xs">
              {noSelecionado ? (
                <>
                  <p className="font-medium">{noSelecionado.label}</p>
                  <p className="text-muted-foreground">
                    {noSelecionado.role ?? noSelecionado.dimension} · {formatCompactEuro(noSelecionado.total_value)} ·{" "}
                    {formatNumber(noSelecionado.count)} contratos
                  </p>
                  <button
                    type="button"
                    onClick={() =>
                      onVerEvidencias(
                        noSelecionado.dimension === "comprador"
                          ? { comprador_nif: noSelecionado.key }
                          : { fornecedor_nif: noSelecionado.key },
                        `Contratos · ${noSelecionado.label}`,
                      )
                    }
                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                  >
                    <FileSearch size={12} /> ver contratos
                  </button>
                </>
              ) : (
                <EmptyState>Clique num nó para ver o resumo e os contratos que o sustentam.</EmptyState>
              )}
              {resumo ? (
                <div className="space-y-1 text-[11px] text-muted-foreground">
                  {Object.entries(resumo)
                    .filter(([, valor]) => typeof valor === "number")
                    .map(([chave, valor]) => (
                      <Linha key={chave} rotulo={chave.replace(/_/g, " ")} valor={formatNumber(Number(valor))} />
                    ))}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </SectionCard>
    </div>
  );
}

/* --------------------------------------------------------------- auxiliares */
function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{rotulo}</dt>
      <dd className="tabular-nums">{valor}</dd>
    </div>
  );
}

function MiniMatriz({ titulo, matriz, vetor }: { titulo: string; matriz?: number[][]; vetor?: number[] }) {
  const conteudo = matriz ?? (vetor ? vetor.map((valor) => [valor]) : []);
  if (conteudo.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">{titulo}</p>
      <pre className="overflow-x-auto rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-[10.5px] leading-tight text-muted-foreground">
        {conteudo.map((linha) => linha.map((valor) => valor.toFixed(3).padStart(8)).join(" ")).join("\n")}
      </pre>
    </div>
  );
}

/* Reexportações para os testes de UI/manutenção encontrarem os tipos. */
export type { LorenzAlerta, LorenzCpvClasse };
