/**
 * Página **Deteção de padrões** (`/padroes`).
 *
 * Cruza contratos públicos (PT e ES), empresas, pessoas, insolvências e notícias
 * para sinalizar o que foge ao padrão — com a explicação de cada sinal:
 *
 * 1. **Padrões por CPV** — onde é que o ajuste direto, os aditivos e os desvios
 *    de preço fogem à média nacional.
 * 2. **Contratos sinalizados** — o que foi isolado pelo consenso dos algoritmos
 *    (Isolation Forest, LOF, K-Means, One-Class SVM, DBSCAN e z-score por CPV).
 * 3. **Empresas** — o mesmo olhar agregado por adjudicatária (LOF de entidades).
 * 4. **Rede** — adjudicante → adjudicatária, laços societários e insolvências
 *    partilhadas.
 * 5. **Risco de aditivo** — modelo supervisionado (Gradient Boosting) treinado
 *    com o rótulo derivado do próprio portal.
 * 6. **Notícias** — menções públicas das empresas sinalizadas.
 *
 * O `dossiê` (painel lateral) mostra todos os sinais de uma entidade de uma só vez.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Brain,
  Building2,
  Coins,
  ExternalLink,
  FileSearch,
  Filter,
  Gavel,
  Landmark,
  Layers,
  Loader2,
  Network,
  Newspaper,
  Percent,
  RefreshCw,
  Scan,
  Scale,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Target,
  TrendingDown,
  Users,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPadroesAnalysis, getPadroesDossie, getPadroesMeta, getPadroesNews } from "../padroesApi";
import type {
  PadroesAnalysis,
  PadroesDossie,
  PadroesMeta,
  PadroesNoticia,
  PadroesParams,
} from "../padroesApi";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { toStudioGraph } from "../components/graph/graphStudio";
import type { GraphMetric, StudioNode } from "../components/graph/graphStudio";
import { PadroesRegras } from "../components/padroes/PadroesRegras";
import { PadroesEmpresa } from "../components/padroes/PadroesEmpresa";
import { PadroesEmpresasComparar } from "../components/padroes/PadroesEmpresasComparar";
import {
  Chip,
  DETECTOR_LABELS,
  DETECTOR_SHORT,
  EmptyState,
  FilterField,
  Kpi,
  Loading,
  ScoreBar,
  SearchInput,
  SectionCard,
  detectorTone,
  formatCompactEuro,
  formatDate,
  formatNumber,
  formatPct,
  formatRatio,
  motivoCurto,
  padraoLabel,
  padraoTone,
} from "../components/padroes/padroesKit";

type Tab = "visao" | "contratos" | "empresas" | "empresa" | "comparar" | "rede" | "risco" | "noticias" | "regras";

const TABS: { id: Tab; label: string; icon: typeof Scan }[] = [
  { id: "visao", label: "Padrões por CPV", icon: Layers },
  { id: "contratos", label: "Contratos sinalizados", icon: FileSearch },
  { id: "empresas", label: "Empresas", icon: Building2 },
  { id: "empresa", label: "Analisar empresa", icon: Search },
  { id: "comparar", label: "Comparar empresas", icon: Scale },
  { id: "rede", label: "Rede de relações", icon: Network },
  { id: "risco", label: "Risco de aditivo", icon: Brain },
  { id: "noticias", label: "Notícias", icon: Newspaper },
  { id: "regras", label: "Regras", icon: SlidersHorizontal },
];

const BAR_COLORS = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#f472b6", "#4ade80", "#60a5fa"];

/** Ids canónicos dos detetores (evita repetir opções quando há nomes legados). */
const DETECTOR_OPTIONS = ["isolation_forest", "lof", "kmeans", "one_class_svm", "dbscan", "z_cpv"];

const SELECT_CLASS =
  "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground";
const INPUT_CLASS = SELECT_CLASS;

type OrdemContratos = "score" | "valor" | "desvio" | "ano";

/** Pesquisa insensível a maiúsculas e acentos («roche» encontra «Roche Farmacêutica»). */
function normalizar(value?: string | null): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

/** Detalhe por trás de um sinal do dossiê: o que está contado no chip. */
type DetalheSinal = { titulo: string; nota?: string; itens: { texto: string; extra?: string }[] };

/**
 * Abre o sinal: um chip diz «20 processo(s) no CIRE», mas quem analisa quer ver
 * **quais**. O detalhe é derivado da amostra já carregada no dossiê (contratos,
 * cargos, processos), pelo que não custa um pedido novo.
 */
function detalheDoSinal(padrao: string, dossie: PadroesDossie): DetalheSinal | null {
  const contratos = dossie.contratos ?? [];
  const comAditivo = contratos
    .filter((contrato) => (contrato.ratio_efetivo ?? 0) > 1.15)
    .sort((a, b) => (b.ratio_efetivo ?? 0) - (a.ratio_efetivo ?? 0));
  switch (padrao) {
    case "insolvencia": {
      const itens = (dossie.insolvencias ?? []).map((row) => ({
        texto: `${row.especie ?? "processo"}${row.ato ? ` · ${row.ato}` : ""}`,
        extra: [row.processo, row.tribunal, formatDate(row.data)].filter((parte) => parte && parte !== "—").join(" · "),
      }));
      const total = dossie.insolvencias_total ?? itens.length;
      return {
        titulo: "Processos no CIRE",
        nota: itens.length < total ? `a mostrar ${itens.length} de ${total}` : `${itens.length} processo(s)`,
        itens,
      };
    }
    case "rede_pessoas": {
      const itens = (dossie.cargos_sociais ?? []).map((pessoa) => ({
        texto: pessoa.nome ?? pessoa.nif ?? "—",
        extra: (pessoa.cargos ?? [])
          .map((cargo) => [cargo.role_org, cargo.role, cargo.acto].filter(Boolean).join(" "))
          .filter(Boolean)
          .join(" · "),
      }));
      return { titulo: "Órgãos sociais registados", nota: `${itens.length} pessoa(s)`, itens };
    }
    case "aditivo_valor":
      return {
        titulo: "Contratos com valor efetivo acima do contratado",
        nota: `${comAditivo.length} contrato(s) · efetivo > 1,15× contratado`,
        itens: comAditivo.slice(0, 12).map((contrato) => ({
          texto: contrato.objeto ?? contrato.id ?? "—",
          extra: `${formatRatio(contrato.ratio_efetivo)} · ${formatCompactEuro(contrato.valor)} · ${contrato.ano ?? "—"} · ${contrato.adjudicante ?? "—"}`,
        })),
      };
    case "desvio_preco_alto": {
      const ordenados = [...contratos]
        .filter((contrato) => contrato.ratio_base != null)
        .sort((a, b) => (b.ratio_base ?? 0) - (a.ratio_base ?? 0));
      return {
        titulo: "Contratos mais acima do preço base",
        nota: `mediana ${formatRatio(dossie.resumo.desvio_mediano)}`,
        itens: ordenados.slice(0, 12).map((contrato) => ({
          texto: contrato.objeto ?? contrato.id ?? "—",
          extra: `${formatRatio(contrato.ratio_base)} do base · ${formatCompactEuro(contrato.valor)} · ${contrato.ano ?? "—"}`,
        })),
      };
    }
    case "ajuste_direto_atipico": {
      const ajustes = contratos.filter((contrato) => contrato.ajuste_direto);
      return {
        titulo: "Contratos por ajuste direto",
        nota: `${ajustes.length} de ${contratos.length} · ${formatPct(dossie.resumo.taxa_ajuste_direto)}`,
        itens: ajustes.slice(0, 12).map((contrato) => ({
          texto: contrato.objeto ?? contrato.id ?? "—",
          extra: `${contrato.procedimento ?? "—"} · ${formatCompactEuro(contrato.valor)} · ${contrato.ano ?? "—"}`,
        })),
      };
    }
    case "concentracao_fornecedor": {
      const porAdjudicante = new Map<string, { nome: string; valor: number; contratos: number }>();
      contratos.forEach((contrato) => {
        const chave = contrato.adjudicante_nif ?? contrato.adjudicante ?? "?";
        const atual = porAdjudicante.get(String(chave)) ?? { nome: contrato.adjudicante ?? String(chave), valor: 0, contratos: 0 };
        atual.valor += contrato.valor ?? 0;
        atual.contratos += 1;
        porAdjudicante.set(String(chave), atual);
      });
      const total = [...porAdjudicante.values()].reduce((soma, item) => soma + item.valor, 0);
      const itens = [...porAdjudicante.entries()]
        .sort((a, b) => b[1].valor - a[1].valor)
        .map(([chave, item]) => ({
          texto: item.nome,
          extra: `${item.contratos} contratos · ${formatCompactEuro(item.valor)}${total ? ` · ${formatPct(item.valor / total)} do valor` : ""}${chave !== item.nome ? ` · ${chave}` : ""}`,
        }));
      return { titulo: "A quem vende", nota: `${itens.length} adjudicante(s)`, itens };
    }
    default:
      return null;
  }
}

export default function PadroesPage() {
  const [pais, setPais] = useState("PT");
  const [anoFrom, setAnoFrom] = useState("");
  const [anoTo, setAnoTo] = useState("");
  const [cpv, setCpv] = useState("");
  const [contamination, setContamination] = useState(0.02);
  const [perYear, setPerYear] = useState(1200);
  const [analysis, setAnalysis] = useState<PadroesAnalysis | null>(null);
  const [meta, setMeta] = useState<PadroesMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("visao");
  const [dossie, setDossie] = useState<PadroesDossie | null>(null);
  const [dossieLoading, setDossieLoading] = useState(false);
  const [noticias, setNoticias] = useState<{ items: PadroesNoticia[]; procuradas: string[] } | null>(null);
  const [noticiasLoading, setNoticiasLoading] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [detector, setDetector] = useState("");
  const [contratoQuery, setContratoQuery] = useState("");
  const [padraoFiltro, setPadraoFiltro] = useState("");
  const [anoContratoDe, setAnoContratoDe] = useState("");
  const [anoContratoAte, setAnoContratoAte] = useState("");
  const [valorMinimo, setValorMinimo] = useState("");
  const [soAditivo, setSoAditivo] = useState(false);
  const [ordem, setOrdem] = useState<OrdemContratos>("score");
  const [limite, setLimite] = useState(100);
  const [riscoQuery, setRiscoQuery] = useState("");
  const [riscoMin, setRiscoMin] = useState(0);
  const [riscoAnoDe, setRiscoAnoDe] = useState("");
  const [riscoAnoAte, setRiscoAnoAte] = useState("");
  const [riscoValorMin, setRiscoValorMin] = useState("");
  const [riscoAditivo, setRiscoAditivo] = useState<"" | "sim" | "nao">("");
  const [riscoOrdem, setRiscoOrdem] = useState<"probabilidade" | "valor" | "ano">("probabilidade");
  const [riscoLimite, setRiscoLimite] = useState(25);
  const [dossieQuery, setDossieQuery] = useState("");
  const [dossieAnoDe, setDossieAnoDe] = useState("");
  const [dossieAnoAte, setDossieAnoAte] = useState("");
  const [dossieValorMin, setDossieValorMin] = useState("");
  const [dossieAditivo, setDossieAditivo] = useState<"" | "sim" | "nao">("");
  const [dossieOrdem, setDossieOrdem] = useState<"recente" | "valor" | "desvio">("recente");
  const [dossieLimite, setDossieLimite] = useState(25);
  const [entidadeQuery, setEntidadeQuery] = useState("");
  const [soInsolventes, setSoInsolventes] = useState(false);
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [dossieLayout, setDossieLayout] = useState<"network" | "hierarchical" | "circular">("hierarchical");
  const [dossieLayoutVersion, setDossieLayoutVersion] = useState(0);
  const [dossieMetric, setDossieMetric] = useState<GraphMetric>("contratos");
  const [sinalAberto, setSinalAberto] = useState<string | null>(null);
  /** O grafo do dossiê só é desenhado a pedido: é o passo mais caro da página. */
  const [mostrarGrafo, setMostrarGrafo] = useState(false);

  const params: PadroesParams = useMemo(
    () => ({
      pais,
      ano_from: anoFrom ? Number(anoFrom) : null,
      ano_to: anoTo ? Number(anoTo) : null,
      cpv: cpv.trim() || null,
      per_year: perYear,
      contamination,
      seed: 42,
    }),
    [pais, anoFrom, anoTo, cpv, perYear, contamination],
  );

  const run = useCallback(
    async (refresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const payload = await getPadroesAnalysis(params, refresh);
        if (payload.error) {
          setError(payload.error);
          setAnalysis(null);
        } else {
          setAnalysis(payload);
          setNoticias(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro desconhecido");
      } finally {
        setLoading(false);
      }
    },
    [params],
  );

  useEffect(() => {
    getPadroesMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);

  useEffect(() => {
    void run(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDossie = useCallback(
    async (nif?: string | null) => {
      if (!nif) return;
      setDossieLoading(true);
      setDossie(null);
      // Cada entidade abre com os filtros limpos (não herda a pesquisa anterior).
      setDossieQuery("");
      setDossieAnoDe("");
      setDossieAnoAte("");
      setDossieValorMin("");
      setDossieAditivo("");
      setDossieOrdem("recente");
      setSinalAberto(null);
      setMostrarGrafo(false);
      try {
        const data = await getPadroesDossie(nif, pais);
        setDossie(data);
      } catch {
        setDossie(null);
      } finally {
        setDossieLoading(false);
      }
    },
    [pais],
  );

  const loadNoticias = useCallback(async () => {
    setNoticiasLoading(true);
    try {
      const data = await getPadroesNews({ ...params, limit: 8 });
      setNoticias({ items: data.items ?? [], procuradas: data.procuradas ?? [] });
    } catch {
      setNoticias({ items: [], procuradas: [] });
    } finally {
      setNoticiasLoading(false);
    }
  }, [params]);

  const overview = analysis?.overview;
  const relacoes = analysis?.relacoes;
  const graph = useMemo(() => (relacoes ? toStudioGraph(relacoes, "valor") : null), [relacoes]);
  const grafoDossie = useMemo(
    () => (dossie?.grafo ? toStudioGraph(dossie.grafo, dossieMetric) : null),
    [dossie, dossieMetric],
  );
  // Resumo do nó estável: uma função nova a cada render obrigava o canvas a
  // redesenhar sem necessidade.
  const resumoNoDossie = useCallback(
    (node: StudioNode) =>
      `${node.label} · ${node.role ?? ""}${node.count ? ` · ${formatNumber(node.count)} ${dossieMetric === "valor" ? "" : "contratos"}` : ""}`,
    [dossieMetric],
  );

  const cpvChart = useMemo(
    () =>
      [...(analysis?.cpvs ?? [])]
        .filter((row) => (row.contratos ?? 0) >= 2)
        .slice(0, 12)
        .map((row) => ({
          cpv: row.cpv,
          nome: row.descricao || `CPV ${row.cpv}`,
          relevancia: Number(((row.relevancia ?? 0) * 100).toFixed(1)),
          ajuste: Number(((row.taxa_ajuste_direto ?? 0) * 100).toFixed(1)),
        })),
    [analysis],
  );

  const padroesDisponiveis = useMemo(() => {
    const ids = new Set<string>();
    (analysis?.anomalias ?? []).forEach((item) => (item.razoes ?? []).forEach((razao) => ids.add(razao.padrao)));
    return [...ids].sort((a, b) => padraoLabel(a).localeCompare(padraoLabel(b), "pt"));
  }, [analysis]);

  const contratos = useMemo(() => {
    const termo = normalizar(contratoQuery);
    const anoDe = anoContratoDe ? Number(anoContratoDe) : null;
    const anoAte = anoContratoAte ? Number(anoContratoAte) : null;
    const valorMin = valorMinimo ? Number(valorMinimo) : 0;

    const items = (analysis?.anomalias ?? []).filter((item) => {
      if (minScore > 0 && (item.score ?? 0) < minScore) return false;
      if (detector && !(item.detetores ?? []).includes(detector)) return false;
      if (padraoFiltro && !(item.razoes ?? []).some((razao) => razao.padrao === padraoFiltro)) return false;
      if (anoDe !== null && (item.ano ?? 0) < anoDe) return false;
      if (anoAte !== null && (item.ano ?? 0) > anoAte) return false;
      if (valorMin > 0 && (item.valor ?? 0) < valorMin) return false;
      if (soAditivo && !((item.ratio_efetivo ?? 0) > 1.15)) return false;
      if (termo) {
        const alvo = normalizar(
          [
            item.objeto,
            item.cpv,
            item.cpv_desc,
            item.procedimento,
            item.adjudicante,
            ...(item.adjudicatarios ?? []).flatMap((parte) => [parte.nome, parte.nif]),
          ]
            .filter(Boolean)
            .join(" "),
        );
        if (!alvo.includes(termo)) return false;
      }
      return true;
    });

    const comparadores: Record<OrdemContratos, (a: (typeof items)[number], b: (typeof items)[number]) => number> = {
      score: (a, b) => (b.score ?? 0) - (a.score ?? 0),
      valor: (a, b) => (b.valor ?? 0) - (a.valor ?? 0),
      desvio: (a, b) => (b.ratio_base ?? 0) - (a.ratio_base ?? 0),
      ano: (a, b) => (b.ano ?? 0) - (a.ano ?? 0),
    };
    return [...items].sort(comparadores[ordem]).slice(0, limite);
  }, [analysis, minScore, detector, padraoFiltro, anoContratoDe, anoContratoAte, valorMinimo, soAditivo, ordem, limite, contratoQuery]);

  const filtrosAtivos =
    (contratoQuery ? 1 : 0) +
    (detector ? 1 : 0) +
    (padraoFiltro ? 1 : 0) +
    (anoContratoDe ? 1 : 0) +
    (anoContratoAte ? 1 : 0) +
    (valorMinimo ? 1 : 0) +
    (minScore > 0 ? 1 : 0) +
    (soAditivo ? 1 : 0);

  const limparFiltrosContratos = useCallback(() => {
    setContratoQuery("");
    setDetector("");
    setPadraoFiltro("");
    setAnoContratoDe("");
    setAnoContratoAte("");
    setValorMinimo("");
    setMinScore(0);
    setSoAditivo(false);
    setOrdem("score");
  }, []);

  // ------------------------------------------------------------- risco (modelo)
  const riscoBase = analysis?.risco_aditivo?.top_contratos ?? [];

  const riscoContratos = useMemo(() => {
    const termo = normalizar(riscoQuery);
    const anoDe = riscoAnoDe ? Number(riscoAnoDe) : null;
    const anoAte = riscoAnoAte ? Number(riscoAnoAte) : null;
    const valorMin = riscoValorMin ? Number(riscoValorMin) : 0;

    const items = riscoBase.filter((row) => {
      if (riscoMin > 0 && (row.probabilidade ?? 0) < riscoMin) return false;
      if (anoDe !== null && (row.ano ?? 0) < anoDe) return false;
      if (anoAte !== null && (row.ano ?? 0) > anoAte) return false;
      if (valorMin > 0 && (row.valor ?? 0) < valorMin) return false;
      if (riscoAditivo === "sim" && !row.teve_aditivo) return false;
      if (riscoAditivo === "nao" && row.teve_aditivo) return false;
      if (termo) {
        const alvo = normalizar(
          [row.objeto, row.cpv, row.adjudicatario, row.adjudicatario_nif, row.adjudicante].filter(Boolean).join(" "),
        );
        if (!alvo.includes(termo)) return false;
      }
      return true;
    });

    const comparadores = {
      probabilidade: (a: (typeof items)[number], b: (typeof items)[number]) => (b.probabilidade ?? 0) - (a.probabilidade ?? 0),
      valor: (a: (typeof items)[number], b: (typeof items)[number]) => (b.valor ?? 0) - (a.valor ?? 0),
      ano: (a: (typeof items)[number], b: (typeof items)[number]) => (b.ano ?? 0) - (a.ano ?? 0),
    };
    return [...items].sort(comparadores[riscoOrdem]).slice(0, riscoLimite);
  }, [riscoBase, riscoQuery, riscoMin, riscoAnoDe, riscoAnoAte, riscoValorMin, riscoAditivo, riscoOrdem, riscoLimite]);

  const riscoFiltrosAtivos =
    (riscoQuery ? 1 : 0) +
    (riscoMin > 0 ? 1 : 0) +
    (riscoAnoDe ? 1 : 0) +
    (riscoAnoAte ? 1 : 0) +
    (riscoValorMin ? 1 : 0) +
    (riscoAditivo ? 1 : 0);

  const limparFiltrosRisco = useCallback(() => {
    setRiscoQuery("");
    setRiscoMin(0);
    setRiscoAnoDe("");
    setRiscoAnoAte("");
    setRiscoValorMin("");
    setRiscoAditivo("");
    setRiscoOrdem("probabilidade");
  }, []);

  // ------------------------------------------------------- dossiê (contratos)
  const limparFiltrosDossie = useCallback(() => {
    setDossieQuery("");
    setDossieAnoDe("");
    setDossieAnoAte("");
    setDossieValorMin("");
    setDossieAditivo("");
    setDossieOrdem("recente");
  }, []);

  const dossieContratos = useMemo(() => {
    const termo = normalizar(dossieQuery);
    const anoDe = dossieAnoDe ? Number(dossieAnoDe) : null;
    const anoAte = dossieAnoAte ? Number(dossieAnoAte) : null;
    const valorMin = dossieValorMin ? Number(dossieValorMin) : 0;

    const items = (dossie?.contratos ?? []).filter((contrato) => {
      if (anoDe !== null && (contrato.ano ?? 0) < anoDe) return false;
      if (anoAte !== null && (contrato.ano ?? 0) > anoAte) return false;
      if (valorMin > 0 && (contrato.valor ?? 0) < valorMin) return false;
      if (dossieAditivo === "sim" && !((contrato.ratio_efetivo ?? 0) > 1.15)) return false;
      if (dossieAditivo === "nao" && (contrato.ratio_efetivo ?? 0) > 1.15) return false;
      if (termo) {
        const alvo = normalizar(
          [contrato.objeto, contrato.cpv, contrato.cpv_desc, contrato.procedimento, contrato.adjudicante]
            .filter(Boolean)
            .join(" "),
        );
        if (!alvo.includes(termo)) return false;
      }
      return true;
    });

    const comparadores = {
      // A API já devolve por data de publicação descendente.
      recente: () => 0,
      valor: (a: (typeof items)[number], b: (typeof items)[number]) => (b.valor ?? 0) - (a.valor ?? 0),
      desvio: (a: (typeof items)[number], b: (typeof items)[number]) => (b.ratio_base ?? 0) - (a.ratio_base ?? 0),
    };
    const ordenados = [...items].sort(comparadores[dossieOrdem]);
    return ordenados.slice(0, dossieLimite);
  }, [dossie, dossieQuery, dossieAnoDe, dossieAnoAte, dossieValorMin, dossieAditivo, dossieOrdem, dossieLimite]);

  const dossieFiltrosAtivos =
    (dossieQuery ? 1 : 0) + (dossieAnoDe ? 1 : 0) + (dossieAnoAte ? 1 : 0) + (dossieValorMin ? 1 : 0) + (dossieAditivo ? 1 : 0);

  const empresas = useMemo(() => {
    const query = entidadeQuery.trim().toLowerCase();
    return (analysis?.entidades ?? []).filter((entity) => {
      if (soInsolventes && !entity.insolvente) return false;
      if (!query) return true;
      return `${entity.nome ?? ""} ${entity.nif}`.toLowerCase().includes(query);
    });
  }, [analysis, entidadeQuery, soInsolventes]);

  const defs = meta?.padroes ?? analysis?.padroes ?? [];

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        {/* ---------------------------------------------------------- cabeçalho */}
        <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <button
              onClick={() => window.history.back()}
              className="mt-1 flex h-8 w-8 items-center justify-center rounded-full glass-card text-muted-foreground transition hover:text-foreground"
              title="Voltar"
            >
              <ArrowLeft size={16} />
            </button>
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
                <Scan size={24} className="text-teal-300" />
                Deteção de padrões
              </h1>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                Contratação pública, empresas, pessoas e notícias numa só leitura: o que é atípico, em que CPV, com que
                relações. Sem rótulos de fraude — o motor isola <strong>desvios estatísticos</strong> e explica cada um.
              </p>
            </div>
          </div>
          <div className="flex flex-col items-start gap-2 lg:items-end">
            <div className="flex items-center gap-2">
              <Chip tone="teal">
                <Sparkles size={12} /> {analysis?.pais_label ?? "—"}
              </Chip>
              {overview?.cobertura?.coverage !== undefined && (
                <Chip title="Fração do universo lida na amostra estratificada por ano">
                  amostra {formatPct(overview.cobertura.coverage, 2)}
                </Chip>
              )}
              {analysis?.duracao_s !== null && analysis?.duracao_s !== undefined && (
                <Chip title="Tempo de cálculo (cache de 15 min)">{analysis.duracao_s.toFixed(1)} s</Chip>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => void run(true)}
                disabled={loading}
                className="flex items-center gap-2 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
                title="Recalcular ignorando a cache (exige sessão)"
              >
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Recalcular
              </button>
            </div>
          </div>
        </header>

        {/* ------------------------------------------------------------ filtros */}
        <div className="glass-card mb-5 rounded-2xl p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Portal
              <select
                value={pais}
                onChange={(event) => setPais(event.target.value)}
                className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground"
              >
                <option value="PT">Portugal (BASE)</option>
                <option value="ES">Espanha (PLACSP)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Ano de
              <input
                value={anoFrom}
                onChange={(event) => setAnoFrom(event.target.value.replace(/\D/g, "").slice(0, 4))}
                placeholder="todos"
                className="w-24 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Ano até
              <input
                value={anoTo}
                onChange={(event) => setAnoTo(event.target.value.replace(/\D/g, "").slice(0, 4))}
                placeholder="atual"
                className="w-24 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              CPV (prefixo)
              <input
                value={cpv}
                onChange={(event) => setCpv(event.target.value.replace(/\D/g, "").slice(0, 8))}
                placeholder="45, 3020…"
                className="w-32 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Contratos/ano
              <input
                type="number"
                min={100}
                max={5000}
                step={100}
                value={perYear}
                onChange={(event) => setPerYear(Number(event.target.value) || 1200)}
                className="w-28 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Contaminação <span className="text-muted-foreground/70">{formatPct(contamination, 1)}</span>
              <input
                type="range"
                min={0.005}
                max={0.1}
                step={0.005}
                value={contamination}
                onChange={(event) => setContamination(Number(event.target.value))}
                className="w-36 accent-teal-400"
              />
            </label>
            <button
              onClick={() => void run(false)}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-teal-400/90 to-sky-500/90 px-4 py-2 text-sm font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Filter size={16} />}
              Analisar
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-5">
            <EmptyState tone="warn">{error}</EmptyState>
          </div>
        )}

        {loading && !analysis && <Loading label="A ler contratos e a correr os detectores…" />}

        {analysis && (
          <>
            {/* ------------------------------------------------------------- KPIs */}
            <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Kpi
                icon={FileSearch}
                label="Contratos analisados"
                value={formatNumber(overview?.contratos_analisados)}
                sub={
                  overview?.anos
                    ? `${overview.anos[0]}–${overview.anos[1]} · universo ${formatNumber(overview.cobertura?.documents_matching)} contratos`
                    : undefined
                }
              />
              <Kpi
                icon={Coins}
                label="Valor analisado"
                value={formatCompactEuro(overview?.valor_analisado)}
                sub={`mediana ${formatCompactEuro(overview?.valor_mediano)}`}
                color="text-amber-300"
                glow="glow-amber"
              />
              <Kpi
                icon={Gavel}
                label="Ajuste direto"
                value={formatPct(overview?.taxa_ajuste_direto)}
                sub="sem concurso público"
                color="text-rose-300"
                glow="glow-rose"
              />
              <Kpi
                icon={Scale}
                label="Desvio mediano"
                value={formatRatio(overview?.desvio_mediano)}
                sub="adjudicado ÷ preço base"
                color="text-sky-300"
                glow="glow-blue"
              />
              <Kpi
                icon={AlertTriangle}
                label="Contratos sinalizados"
                value={formatNumber(overview?.contratos_sinalizados)}
                sub={`${formatPct(overview?.taxa_sinalizacao)} da amostra · ${formatPct(overview?.taxa_aditivo)} com aditivo`}
                color="text-rose-300"
                glow="glow-rose"
              />
              <Kpi
                icon={Building2}
                label="Empresas sinalizadas"
                value={`${formatNumber(overview?.entidades_sinalizadas)}/${formatNumber(overview?.entidades)}`}
                sub={`${formatNumber(overview?.cpvs)} CPV analisados`}
                color="text-violet-300"
              />
            </div>

            {/* ------------------------------------------------------------- tabs */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                    tab === id
                      ? "glass-card bg-teal-400/10 text-teal-200 border-teal-400/25"
                      : "glass-card text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Icon size={15} />
                  {label}
                  {id === "contratos" && <span className="text-[11px] opacity-70">{contratos.length}</span>}
                  {id === "empresas" && <span className="text-[11px] opacity-70">{empresas.length}</span>}
                  {id === "regras" && (
                    <span className="text-[11px] opacity-70">
                      {formatNumber(analysis.regras?.ativas?.length ?? 0)}/{formatNumber(analysis.regras?.total_regras ?? 0)}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* ------------------------------------------------------ padrões CPV */}
            {tab === "visao" && (
              <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
                <SectionCard
                  icon={BarChart3}
                  title="CPV com mais sinais"
                  subtitle="Relevância = combinação do ajuste direto acima da média nacional, taxa de aditivos e desvio de preço."
                >
                  <div className="h-[300px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={cpvChart} layout="vertical" margin={{ left: 8, right: 16 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                        <XAxis type="number" stroke="#8b95a5" fontSize={11} />
                        <YAxis type="category" dataKey="cpv" stroke="#8b95a5" fontSize={11} width={40} />
                        <Tooltip
                          cursor={{ fill: "rgba(255,255,255,0.04)" }}
                          content={({ active, payload }) => {
                            if (!active || !payload || payload.length === 0) return null;
                            const row = payload[0].payload as { cpv: string; nome: string; relevancia: number; ajuste: number };
                            return (
                              <div className="rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs">
                                <p className="font-semibold">CPV {row.cpv}</p>
                                <p className="text-muted-foreground">{row.nome}</p>
                                <p className="mt-1">relevância {row.relevancia}</p>
                                <p className="text-muted-foreground">ajuste direto {row.ajuste} %</p>
                              </div>
                            );
                          }}
                        />
                        <Bar dataKey="relevancia" radius={[0, 6, 6, 0]}>
                          {cpvChart.map((entry, index) => (
                            <Cell key={entry.cpv} fill={BAR_COLORS[index % BAR_COLORS.length]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </SectionCard>

                <SectionCard
                  icon={Target}
                  title="O que o motor procura"
                  subtitle="Regras guardadas (editáveis) + padrões que dependem de modelos, grafo ou notícias."
                  actions={
                    <button
                      onClick={() => setTab("regras")}
                      className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
                    >
                      <SlidersHorizontal size={13} /> gerir regras
                    </button>
                  }
                >
                  <div className="max-h-[300px] space-y-2 overflow-y-auto pr-1">
                    {defs.map((padrao) => (
                      <div key={padrao.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold">{padrao.label}</span>
                          <div className="flex items-center gap-1">
                            {padrao.severidade && <Chip tone={padraoTone(padrao.id)}>{padrao.severidade}</Chip>}
                            <Chip tone={padrao.editavel === false ? "neutral" : "teal"}>
                              {padrao.editavel === false ? padrao.tipo : "regra"}
                            </Chip>
                            {padrao.ativo === false && <Chip tone="amber">desligada</Chip>}
                          </div>
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">{padrao.descricao}</p>
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground/80">{padrao.metodo}</p>
                      </div>
                    ))}
                  </div>
                </SectionCard>

                <SectionCard
                  icon={Layers}
                  title="Tabela por CPV"
                  subtitle="Ordenada pela relevância dos sinais (não pelo volume)."
                  className="xl:col-span-2"
                >
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[940px] border-collapse text-left text-sm">
                      <thead>
                        <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                          <th className="py-2 pr-3">CPV</th>
                          <th className="py-2 pr-3">Descrição</th>
                          <th className="py-2 pr-3 text-right">Contratos</th>
                          <th className="py-2 pr-3 text-right">Valor</th>
                          <th className="py-2 pr-3 text-right">Desvio</th>
                          <th className="py-2 pr-3 text-right">Ajuste direto</th>
                          <th className="py-2 pr-3 text-right">Aditivos</th>
                          <th className="py-2 pr-3 text-right">Sinalizados</th>
                          <th className="py-2 text-right">Relevância</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(analysis.cpvs ?? []).slice(0, 40).map((row) => (
                          <tr key={row.cpv} className="border-t border-white/5">
                            <td className="whitespace-nowrap py-2 pr-3 font-mono text-xs">{row.cpv}</td>
                            <td className="py-2 pr-3 text-xs text-muted-foreground">
                              <span className="block max-w-[260px] truncate" title={row.descricao ?? undefined}>
                                {row.descricao ?? "—"}
                              </span>
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatNumber(row.contratos)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatCompactEuro(row.valor_total)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatRatio(row.desvio_mediano)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatPct(row.taxa_ajuste_direto)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatPct(row.taxa_aditivo)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatNumber(row.contratos_sinalizados)}</td>
                            <td className="py-2 text-right">
                              <div className="flex justify-end">
                                <ScoreBar score={row.relevancia} />
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </SectionCard>
              </div>
            )}

            {/* -------------------------------------------------------- contratos */}
            {tab === "contratos" && (
              <SectionCard
                icon={FileSearch}
                title="Contratos sinalizados"
                subtitle="Score = percentil de consenso dos detectores. Só entra quem tem score alto e ≥ 2 detetores de acordo."
                actions={
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
                      {formatNumber(contratos.length)} de {formatNumber((analysis.anomalias ?? []).length)}
                    </span>
                    {filtrosAtivos > 0 && (
                      <button
                        onClick={limparFiltrosContratos}
                        className="flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-1 transition hover:bg-white/5"
                      >
                        <X size={12} /> limpar {filtrosAtivos}
                      </button>
                    )}
                  </div>
                }
              >
                {/* --------------------------------------------------- filtros */}
                <div className="mb-4 grid gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                  <FilterField label="Pesquisar" className="sm:col-span-2 xl:col-span-2">
                    <SearchInput
                      value={contratoQuery}
                      onChange={setContratoQuery}
                      placeholder="objeto, empresa, adjudicante, CPV…"
                    />
                  </FilterField>

                  <FilterField label={`Score mínimo · ${minScore.toFixed(2)}`}>
                    <input
                      type="range"
                      min={0}
                      max={0.99}
                      step={0.05}
                      value={minScore}
                      onChange={(event) => setMinScore(Number(event.target.value))}
                      className="mt-2 accent-teal-400"
                    />
                  </FilterField>

                  <FilterField label="Detetor">
                    <select
                      value={detector}
                      onChange={(event) => setDetector(event.target.value)}
                      className={SELECT_CLASS}
                    >
                      <option value="">todos</option>
                      {DETECTOR_OPTIONS.map((id) => (
                        <option key={id} value={id}>
                          {DETECTOR_LABELS[id] ?? id}
                        </option>
                      ))}
                    </select>
                  </FilterField>

                  <FilterField label="Padrão">
                    <select value={padraoFiltro} onChange={(event) => setPadraoFiltro(event.target.value)} className={SELECT_CLASS}>
                      <option value="">todos</option>
                      {padroesDisponiveis.map((id) => (
                        <option key={id} value={id}>
                          {padraoLabel(id)}
                        </option>
                      ))}
                    </select>
                  </FilterField>

                  <FilterField label="Ano de">
                    <input
                      value={anoContratoDe}
                      onChange={(event) => setAnoContratoDe(event.target.value.replace(/\D/g, "").slice(0, 4))}
                      placeholder="min"
                      className={INPUT_CLASS}
                    />
                  </FilterField>

                  <FilterField label="Ano até">
                    <input
                      value={anoContratoAte}
                      onChange={(event) => setAnoContratoAte(event.target.value.replace(/\D/g, "").slice(0, 4))}
                      placeholder="max"
                      className={INPUT_CLASS}
                    />
                  </FilterField>

                  <FilterField label="Valor mínimo (€)">
                    <input
                      value={valorMinimo}
                      onChange={(event) => setValorMinimo(event.target.value.replace(/[^\d]/g, ""))}
                      placeholder="0"
                      className={INPUT_CLASS}
                    />
                  </FilterField>

                  <FilterField label="Ordenar por">
                    <select
                      value={ordem}
                      onChange={(event) => setOrdem(event.target.value as OrdemContratos)}
                      className={SELECT_CLASS}
                    >
                      <option value="score">Score (maior primeiro)</option>
                      <option value="valor">Valor (maior primeiro)</option>
                      <option value="desvio">Desvio de preço (maior)</option>
                      <option value="ano">Ano (mais recente)</option>
                    </select>
                  </FilterField>

                  <FilterField label="Mostrar">
                    <select
                      value={limite}
                      onChange={(event) => setLimite(Number(event.target.value))}
                      className={SELECT_CLASS}
                    >
                      {[25, 50, 100, 200, 400].map((value) => (
                        <option key={value} value={value}>
                          {value} linhas
                        </option>
                      ))}
                    </select>
                  </FilterField>

                  <FilterField label="Só com aditivo">
                    <button
                      onClick={() => setSoAditivo((value) => !value)}
                      className={`mt-0.5 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs normal-case tracking-normal transition ${
                        soAditivo
                          ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                          : "border-white/10 bg-black/30 text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <span className={`h-2 w-2 rounded-full ${soAditivo ? "bg-rose-300" : "bg-white/20"}`} />
                      {soAditivo ? "valor efetivo > contratual" : "todos os contratos"}
                    </button>
                  </FilterField>
                </div>

                {contratos.length === 0 ? (
                  <EmptyState>
                    Nenhum contrato corresponde aos filtros. Alivie o score mínimo, tire a pesquisa de texto ou alargue os
                    anos.
                  </EmptyState>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1180px] border-collapse text-left text-sm">
                      <thead>
                        <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                          <th className="py-2 pr-3">Score</th>
                          <th className="py-2 pr-3">Ano</th>
                          <th className="py-2 pr-3">Objeto</th>
                          <th className="py-2 pr-3">Adjudicatária</th>
                          <th className="py-2 pr-3">Adjudicante</th>
                          <th className="py-2 pr-3 text-right">Valor</th>
                          <th className="py-2 pr-3 text-right">Base</th>
                          <th className="py-2 pr-3">Sinais</th>
                        </tr>
                      </thead>
                      <tbody>
                        {contratos.map((item, index) => (
                          <tr key={`${item.id ?? index}`} className="border-t border-white/5 align-top">
                            <td className="w-[190px] py-2 pr-3">
                              <ScoreBar score={item.score} />
                              <div className="mt-1 flex flex-wrap gap-1">
                                {(item.detetores ?? []).slice(0, 3).map((name) => (
                                  <Chip key={name} tone={detectorTone(name)} title={DETECTOR_LABELS[name] ?? name}>
                                    {DETECTOR_SHORT[name] ?? name}
                                  </Chip>
                                ))}
                                {(item.detetores ?? []).length > 3 && (
                                  <Chip title={(item.detetores ?? []).map((name) => DETECTOR_LABELS[name] ?? name).join(", ")}>
                                    +{(item.detetores ?? []).length - 3}
                                  </Chip>
                                )}
                                <Chip title="nº de detetores de acordo">votos {item.votos}</Chip>
                              </div>
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-xs">{item.ano ?? "—"}</td>
                            <td className="w-[280px] py-2 pr-3 text-xs">
                              <div className="line-clamp-2">{item.objeto || "—"}</div>
                              <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                                CPV {item.cpv ?? "—"} · {item.procedimento ?? "—"}
                                {item.ajuste_direto && " · ajuste direto"}
                              </div>
                            </td>
                            <td className="w-[190px] py-2 pr-3 text-xs">
                              {(item.adjudicatarios ?? []).length === 0 ? (
                                "—"
                              ) : (
                                (item.adjudicatarios ?? []).slice(0, 2).map((party) => (
                                  <button
                                    key={`${party.nif ?? party.nome}`}
                                    onClick={() => void openDossie(party.nif)}
                                    className="block max-w-[180px] truncate text-left text-teal-200 transition hover:text-teal-100"
                                    title="Abrir dossiê"
                                  >
                                    {party.nome ?? party.nif}
                                  </button>
                                ))
                              )}
                            </td>
                            <td className="w-[170px] py-2 pr-3 text-xs text-muted-foreground">
                              <div className="line-clamp-2">{item.adjudicante ?? "—"}</div>
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                              {formatCompactEuro(item.valor)}
                              <div className="text-[10px] text-muted-foreground">{formatRatio(item.ratio_base)}</div>
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                              {formatCompactEuro(item.preco_base)}
                              <div className="text-[10px] text-muted-foreground">
                                {item.n_concorrentes !== null && item.n_concorrentes !== undefined
                                  ? `${item.n_concorrentes} conc.`
                                  : "—"}
                              </div>
                            </td>
                            <td className="w-[300px] py-2 pr-3">
                              <div className="flex flex-wrap gap-1">
                                {(item.razoes ?? []).slice(0, 4).map((razao) => (
                                  <Chip key={`${razao.padrao}-${razao.detalhe}`} tone={padraoTone(razao.padrao)} title={razao.detalhe}>
                                    {padraoLabel(razao.padrao)}
                                  </Chip>
                                ))}
                                {(item.razoes ?? []).length > 4 && (
                                  <Chip title={(item.razoes ?? []).slice(4).map((razao) => razao.detalhe).join(" · ")}>
                                    +{(item.razoes ?? []).length - 4}
                                  </Chip>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </SectionCard>
            )}

            {/* --------------------------------------------------------- empresas */}
            {tab === "empresas" && (
              <SectionCard
                icon={Building2}
                title="Empresas e entidades adjudicatárias"
                subtitle="Score = LOF no espaço de features da entidade (contratos, valor, concentração, ajuste direto, sinalizações)."
                actions={
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/30 px-2 py-1">
                      <Search size={13} className="text-muted-foreground" />
                      <input
                        value={entidadeQuery}
                        onChange={(event) => setEntidadeQuery(event.target.value)}
                        placeholder="nome ou NIF"
                        className="w-40 bg-transparent text-xs outline-none"
                      />
                    </div>
                    <button
                      onClick={() => setSoInsolventes((value) => !value)}
                      className={`flex items-center gap-1.5 rounded-lg px-2 py-1 transition ${
                        soInsolventes ? "bg-rose-400/15 text-rose-200 border-rose-400/25" : "border-white/10 text-muted-foreground"
                      }`}
                    >
                      <ShieldAlert size={13} /> só insolventes
                    </button>
                  </div>
                }
              >
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                        <th className="py-2 pr-3">Empresa</th>
                        <th className="py-2 pr-3">Score</th>
                        <th className="py-2 pr-3 text-right">Contratos</th>
                        <th className="py-2 pr-3 text-right">Valor</th>
                        <th className="py-2 pr-3 text-right">Ajuste direto</th>
                        <th className="py-2 pr-3 text-right">1.º adjudicante</th>
                        <th className="py-2 pr-3 text-right">Adjudicantes</th>
                        <th className="py-2 pr-3 text-right">Sinalizados</th>
                        <th className="py-2">Motivos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {empresas.slice(0, 150).map((entity) => (
                        <tr key={entity.nif} className="border-t border-white/5 align-top">
                          <td className="w-[250px] py-2 pr-3 text-xs">
                            <button
                              onClick={() => void openDossie(entity.nif)}
                              className="block max-w-[230px] truncate text-left text-teal-200 transition hover:text-teal-100"
                              title={entity.nome ?? entity.nif}
                            >
                              {entity.nome ?? entity.nif}
                            </button>
                            <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{entity.nif}</div>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {entity.insolvente && (
                                <Chip tone="rose">
                                  <ShieldAlert size={11} /> insolvência
                                </Chip>
                              )}
                              {entity.cpv_principal && <Chip>CPV {entity.cpv_principal}</Chip>}
                            </div>
                          </td>
                          <td className="w-[130px] py-2 pr-3">
                            <ScoreBar score={entity.score} />
                          </td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(entity.contratos)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(entity.valor_total)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(entity.taxa_ajuste_direto)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(entity.parte_do_maior_adjudicante)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(entity.adjudicantes_distintos)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                            {formatNumber(entity.contratos_sinalizados)}
                            <div className="text-[10px] text-muted-foreground">{formatPct(entity.taxa_sinalizacao)}</div>
                          </td>
                          <td className="w-[330px] py-2">
                            <div className="flex max-w-[320px] flex-wrap gap-1">
                              {(entity.motivos ?? []).length === 0 ? (
                                <span className="text-[11px] text-muted-foreground">—</span>
                              ) : (
                                (entity.motivos ?? []).map((motivo) => (
                                  <Chip key={motivo} tone={padraoTone(entity.padrao ?? "")} title={motivo}>
                                    {motivoCurto(motivo)}
                                  </Chip>
                                ))
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </SectionCard>
            )}

            {tab === "empresa" && <PadroesEmpresa pais={pais} onDossie={(nif) => void openDossie(nif)} />}

            {/* ---------------------------------------------------- comparar empresas */}
            {tab === "comparar" && <PadroesEmpresasComparar pais={pais} onDossie={(nif) => void openDossie(nif)} />}

            {/* ------------------------------------------------------------- rede */}
            {tab === "rede" && (
              <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
                <SectionCard
                  icon={Network}
                  title="Rede adjudicante → adjudicatária"
                  subtitle={`${formatNumber(graph?.nodes.length)} nós · ${formatNumber(graph?.edges.length)} ligações (valor contratado).`}
                  actions={
                    <div className="flex items-center gap-1 text-xs">
                      {(["network", "hierarchical", "circular"] as const).map((option) => (
                        <button
                          key={option}
                          onClick={() => {
                            setLayout(option);
                            setLayoutVersion((value) => value + 1);
                          }}
                          className={`rounded-lg px-2 py-1 transition ${
                            layout === option ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          {option === "network" ? "rede" : option === "hierarchical" ? "hierárquico" : "circular"}
                        </button>
                      ))}
                    </div>
                  }
                >
                  <GraphCanvas
                    graph={graph}
                    layout={layout}
                    metric="valor"
                    layoutVersion={layoutVersion}
                    heightClass="h-[520px]"
                    nodeSummary={(node) => `${node.label} · ${formatCompactEuro(node.value)}`}
                  />
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    As ligações pessoa→empresa usam apenas <strong>órgãos sociais</strong> (o índice de pessoas é dominado
                    por papéis processuais do CIRE, que não indicam gestão).
                  </p>
                </SectionCard>

                <div className="space-y-5">
                  <SectionCard
                    icon={AlertTriangle}
                    title="Laços detetados"
                    subtitle="Empresas que partilham pessoa e ganham ao mesmo adjudicante, e insolvências partilhadas."
                  >
                    {(!relacoes?.lacos || relacoes.lacos.length === 0) ? (
                      <EmptyState>
                        Sem laços na amostra atual. É um resultado válido: significa que os dados disponíveis não ligam as
                        adjudicatárias entre si.
                      </EmptyState>
                    ) : (
                      <ul className="max-h-[300px] space-y-2 overflow-y-auto pr-1">
                        {relacoes.lacos.slice(0, 40).map((laco, index) => (
                          <li key={`${laco.tipo}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
                            <div className="flex items-center gap-2">
                              <Chip tone={laco.tipo === "insolvencia_partilhada" ? "rose" : "violet"}>{laco.tipo}</Chip>
                              {laco.valor ? <span className="text-muted-foreground">{formatCompactEuro(laco.valor)}</span> : null}
                            </div>
                            <p className="mt-1.5 text-muted-foreground">{laco.detalhe}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </SectionCard>

                  <SectionCard
                    icon={Landmark}
                    title="Concentração de fornecedor"
                    subtitle="Adjudicantes em que uma só empresa leva ≥ 50 % do valor da amostra."
                  >
                    {(!relacoes?.concentracao || relacoes.concentracao.length === 0) ? (
                      <EmptyState>Sem concentrações acima de 50 % na amostra.</EmptyState>
                    ) : (
                      <ul className="max-h-[280px] space-y-2 overflow-y-auto pr-1">
                        {relacoes.concentracao.slice(0, 30).map((row, index) => (
                          <li key={`${row.adjudicante}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-amber-200">{formatPct(row.parte_do_valor)}</span>
                              <span className="text-muted-foreground">
                                {row.contratos} de {row.contratos_do_adjudicante} contratos
                              </span>
                            </div>
                            <p className="mt-1">{row.empresa}</p>
                            <p className="text-muted-foreground">
                              recebe de {row.adjudicante} · {formatCompactEuro(row.valor)}
                            </p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </SectionCard>

                  <SectionCard
                    icon={ShieldAlert}
                    title="Adjudicatárias em insolvência"
                    subtitle="Cruzamento por NIF com o CIRE (só o insolvente conta)."
                  >
                    {(!relacoes?.insolventes || relacoes.insolventes.length === 0) ? (
                      <EmptyState>Nenhuma adjudicatária da amostra é insolvente.</EmptyState>
                    ) : (
                      <ul className="max-h-[240px] space-y-2 overflow-y-auto pr-1">
                        {relacoes.insolventes.slice(0, 25).map((row, index) => (
                          <li key={`${row.nif}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
                            <button
                              onClick={() => void openDossie(row.nif)}
                              className="text-left font-semibold text-rose-200 hover:text-rose-100"
                            >
                              {row.nome ?? row.nif}
                            </button>
                            <p className="mt-1 text-muted-foreground">
                              {row.especie ?? "—"} · {formatDate(row.data)} · {row.tribunal ?? "—"}
                            </p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </SectionCard>
                </div>
              </div>
            )}

            {/* ------------------------------------------------------------ risco */}
            {tab === "risco" && (
              <div className="grid gap-5 xl:grid-cols-[1fr_1.4fr]">
                <SectionCard
                  icon={Brain}
                  title="Modelo supervisionado"
                  subtitle="Gradient Boosting treinado com o rótulo derivado do portal (valor efetivo > 115 % do contratual)."
                >
                  {!analysis.risco_aditivo?.disponivel ? (
                    <EmptyState tone="warn">
                      {analysis.risco_aditivo?.motivo ?? "Modelo indisponível com esta amostra."}{" "}
                      Aumente os contratos por ano ou alargue o intervalo de anos.
                    </EmptyState>
                  ) : (
                    <>
                      <div className="mb-4 grid grid-cols-2 gap-3">
                        <Kpi
                          icon={Activity}
                          label="ROC AUC (teste)"
                          value={formatRatio(analysis.risco_aditivo.auc ?? undefined)}
                          sub={analysis.risco_aditivo.validacao}
                          color="text-sky-300"
                          glow="glow-blue"
                        />
                        <Kpi
                          icon={TrendingDown}
                          label="Average precision"
                          value={formatRatio(analysis.risco_aditivo.average_precision ?? undefined)}
                          sub={`prevalência ${formatPct(analysis.risco_aditivo.prevalencia)}`}
                          color="text-amber-300"
                          glow="glow-amber"
                        />
                        <Kpi
                          icon={Target}
                          label="Lift no topo 10 %"
                          value={`${(analysis.risco_aditivo.lift_top_decile ?? 0).toFixed(2)}×`}
                          sub={`${formatNumber(analysis.risco_aditivo.positivos)} aditivos em ${formatNumber(analysis.risco_aditivo.contratos)}`}
                          color="text-rose-300"
                          glow="glow-rose"
                        />
                        <Kpi
                          icon={Percent}
                          label="Prevalência"
                          value={formatPct(analysis.risco_aditivo.prevalencia)}
                          sub={analysis.risco_aditivo.rotulo}
                        />
                      </div>
                      <EmptyState tone="warn">
                        {analysis.risco_aditivo.aviso} Sinais para priorizar inspeção, não prova de ilícito.
                      </EmptyState>
                      <div className="mt-4 space-y-2">
                        {(analysis.risco_aditivo.importancias ?? []).slice(0, 8).map((row) => (
                          <div key={row.feature}>
                            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                              <span className="font-mono">{row.feature}</span>
                              <span>{(Number(row.importancia ?? 0) * 100).toFixed(1)}%</span>
                            </div>
                            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-teal-300 to-sky-500"
                                style={{ width: `${Math.min(100, Number(row.importancia ?? 0) * 400)}%` }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </SectionCard>

                <SectionCard
                  icon={FileSearch}
                  title="Contratos com maior risco estimado"
                  subtitle="A probabilidade vem do modelo; «teve aditivo» mostra o que o portal registou (só verificável depois)."
                  actions={
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
                        {formatNumber(riscoContratos.length)} de {formatNumber(riscoBase.length)}
                      </span>
                      {riscoFiltrosAtivos > 0 && (
                        <button
                          onClick={limparFiltrosRisco}
                          className="flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-1 transition hover:bg-white/5"
                        >
                          <X size={12} /> limpar {riscoFiltrosAtivos}
                        </button>
                      )}
                    </div>
                  }
                >
                  {riscoBase.length === 0 ? (
                    <EmptyState>Sem previsões com esta amostra.</EmptyState>
                  ) : (
                    <>
                      {/* ----------------------------------------------- filtros */}
                      <div className="mb-4 grid gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
                        <FilterField label="Pesquisar" className="sm:col-span-2 xl:col-span-2">
                          <SearchInput
                            value={riscoQuery}
                            onChange={setRiscoQuery}
                            placeholder="objeto, adjudicatária, adjudicante, CPV…"
                          />
                        </FilterField>

                        <FilterField label={`Probabilidade ≥ ${riscoMin.toFixed(2)}`}>
                          <input
                            type="range"
                            min={0}
                            max={0.99}
                            step={0.05}
                            value={riscoMin}
                            onChange={(event) => setRiscoMin(Number(event.target.value))}
                            className="mt-2 accent-teal-400"
                          />
                        </FilterField>

                        <FilterField label="Ano de">
                          <input
                            value={riscoAnoDe}
                            onChange={(event) => setRiscoAnoDe(event.target.value.replace(/\D/g, "").slice(0, 4))}
                            placeholder="min"
                            className={INPUT_CLASS}
                          />
                        </FilterField>

                        <FilterField label="Ano até">
                          <input
                            value={riscoAnoAte}
                            onChange={(event) => setRiscoAnoAte(event.target.value.replace(/\D/g, "").slice(0, 4))}
                            placeholder="max"
                            className={INPUT_CLASS}
                          />
                        </FilterField>

                        <FilterField label="Valor mínimo (€)">
                          <input
                            value={riscoValorMin}
                            onChange={(event) => setRiscoValorMin(event.target.value.replace(/[^\d]/g, ""))}
                            placeholder="0"
                            className={INPUT_CLASS}
                          />
                        </FilterField>

                        <FilterField label="Aditivo registado">
                          <select
                            value={riscoAditivo}
                            onChange={(event) => setRiscoAditivo(event.target.value as "" | "sim" | "nao")}
                            className={SELECT_CLASS}
                          >
                            <option value="">todos</option>
                            <option value="sim">só com aditivo</option>
                            <option value="nao">só sem aditivo</option>
                          </select>
                        </FilterField>

                        <FilterField label="Ordenar por">
                          <select
                            value={riscoOrdem}
                            onChange={(event) => setRiscoOrdem(event.target.value as "probabilidade" | "valor" | "ano")}
                            className={SELECT_CLASS}
                          >
                            <option value="probabilidade">Probabilidade (maior)</option>
                            <option value="valor">Valor (maior)</option>
                            <option value="ano">Ano (mais recente)</option>
                          </select>
                        </FilterField>

                        <FilterField label="Mostrar">
                          <select
                            value={riscoLimite}
                            onChange={(event) => setRiscoLimite(Number(event.target.value))}
                            className={SELECT_CLASS}
                          >
                            {[10, 25, 50, 100, 200].map((value) => (
                              <option key={value} value={value}>
                                {value} linhas
                              </option>
                            ))}
                          </select>
                        </FilterField>
                      </div>

                      {riscoContratos.length === 0 ? (
                        <EmptyState>
                          Nenhum contrato corresponde aos filtros. Baixe a probabilidade mínima ou tire a pesquisa de texto.
                        </EmptyState>
                      ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[880px] border-collapse text-left text-sm">
                        <thead>
                          <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                            <th className="py-2 pr-3">Prob.</th>
                            <th className="py-2 pr-3">Ano</th>
                            <th className="py-2 pr-3">Objeto</th>
                            <th className="py-2 pr-3">Adjudicatária</th>
                            <th className="py-2 pr-3 text-right">Valor</th>
                            <th className="py-2 text-right">Aditivo</th>
                          </tr>
                        </thead>
                        <tbody>
                          {riscoContratos.map((row, index) => (
                            <tr key={`${row.id ?? index}`} className="border-t border-white/5 align-top">
                              <td className="w-[130px] py-2 pr-3">
                                <ScoreBar score={row.probabilidade} />
                              </td>
                              <td className="whitespace-nowrap py-2 pr-3 text-xs">{row.ano ?? "—"}</td>
                              <td className="w-[340px] py-2 pr-3 text-xs">
                                <div className="line-clamp-2">{row.objeto || "—"}</div>
                                <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                                  CPV {row.cpv ?? "—"} · {row.adjudicante ?? "—"}
                                </div>
                              </td>
                              <td className="w-[200px] py-2 pr-3 text-xs">
                                <button
                                  onClick={() => void openDossie(row.adjudicatario_nif)}
                                  className="block max-w-[190px] truncate text-left text-teal-200 transition hover:text-teal-100"
                                  title={row.adjudicatario ?? row.adjudicatario_nif ?? undefined}
                                >
                                  {row.adjudicatario ?? row.adjudicatario_nif ?? "—"}
                                </button>
                              </td>
                              <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(row.valor)}</td>
                              <td className="whitespace-nowrap py-2 text-right">
                                {row.teve_aditivo ? <Chip tone="rose">sim</Chip> : <Chip>não</Chip>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                      )}
                    </>
                  )}
                </SectionCard>

                <SectionCard
                  icon={Layers}
                  title="Como o motor trabalha"
                  subtitle="Algoritmos usados nesta análise e features que entraram no modelo."
                  className="xl:col-span-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {(analysis.deteccao.algoritmos ?? []).map((name) => (
                      <Chip key={name} tone={detectorTone(name)}>
                        {DETECTOR_LABELS[name] ?? name}
                      </Chip>
                    ))}
                    <Chip title="percentil de consenso a partir do qual se sinaliza">
                      limiar {analysis.deteccao.limiar_consenso?.toFixed(2) ?? "—"}
                    </Chip>
                    <Chip title="semente aleatória (reprodutibilidade)">semente {analysis.deteccao.semente}</Chip>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Features usadas</p>
                      <div className="flex flex-wrap gap-1">
                        {(analysis.deteccao.features ?? []).map((name) => (
                          <Chip key={name} tone="teal">
                            <span className="font-mono">{name}</span>
                          </Chip>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Excluídas (sem cobertura)</p>
                      <div className="flex flex-wrap gap-1">
                        {(analysis.deteccao.features_excluidas ?? []).length === 0 ? (
                          <span className="text-[11px] text-muted-foreground">nenhuma</span>
                        ) : (
                          (analysis.deteccao.features_excluidas ?? []).map((name) => (
                            <Chip key={name}>
                              <span className="font-mono">{name}</span>
                            </Chip>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                  {analysis.deteccao.aviso && (
                    <div className="mt-3">
                      <EmptyState tone="warn">{analysis.deteccao.aviso}</EmptyState>
                    </div>
                  )}
                </SectionCard>
              </div>
            )}

            {/* --------------------------------------------------------- notícias */}
            {tab === "noticias" && (
              <SectionCard
                icon={Newspaper}
                title="Menções em notícias"
                subtitle="Leitor RSS, recolha de sites e redes sociais, para as empresas com maior score."
                actions={
                  <button
                    onClick={() => void loadNoticias()}
                    disabled={noticiasLoading}
                    className="flex items-center gap-2 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
                  >
                    {noticiasLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                    Procurar menções
                  </button>
                }
              >
                {!noticias ? (
                  <EmptyState>
                    A pesquisa de notícias é feita a pedido (consulta o leitor RSS, o índice de recolha e as redes sociais).
                  </EmptyState>
                ) : noticias.items.length === 0 ? (
                  <EmptyState>
                    Sem menções para {noticias.procuradas.length} empresa(s) procuradas. Os índices de notícias podem estar
                    vazios ou as empresas não aparecem na imprensa.
                  </EmptyState>
                ) : (
                  <div className="space-y-4">
                    <p className="text-[11px] text-muted-foreground">
                      Procuradas: <span className="text-foreground">{noticias.procuradas.join(", ") || "—"}</span>
                    </p>
                    <ul className="space-y-2">
                      {noticias.items.map((item, index) => (
                        <li key={`${item.url ?? item.titulo}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                          <div className="flex flex-wrap items-center gap-2 text-[11px]">
                            <Chip tone={item.canal === "rss" ? "teal" : item.canal === "social" ? "violet" : "blue"}>
                              {item.canal}
                            </Chip>
                            <span className="text-muted-foreground">{item.fonte ?? "—"}</span>
                            <span className="text-muted-foreground">{formatDate(item.data)}</span>
                            {item.sentimento && (
                              <Chip tone={item.sentimento === "negativo" ? "rose" : item.sentimento === "positivo" ? "teal" : "neutral"}>
                                {item.sentimento}
                              </Chip>
                            )}
                            <span className="text-teal-200">{item.entidade_nome}</span>
                          </div>
                          <p className="mt-1.5 text-sm font-medium">{item.titulo ?? "(sem título)"}</p>
                          {item.resumo && <p className="mt-1 text-xs text-muted-foreground">{item.resumo}</p>}
                          {item.url && (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-sky-300 hover:text-sky-200"
                            >
                              abrir <ExternalLink size={11} />
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </SectionCard>
            )}

            {/* ------------------------------------------------------------ regras */}
            {tab === "regras" && <PadroesRegras analysis={analysis} onChanged={() => void run(false)} />}

            <p className="mt-6 flex items-start gap-2 text-[11px] text-muted-foreground">
              <Users size={13} className="mt-0.5 shrink-0" />
              {meta?.aviso ??
                "Os padrões são sinais estatísticos para priorizar inspeção e não prova de ilícito: um desvio pode ter justificação legal."}
            </p>
          </>
        )}
      </div>

      {/* ------------------------------------------------------------- dossiê */}
      {(dossie || dossieLoading) && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={() => setDossie(null)}>
          <aside
            className="h-full w-full max-w-4xl overflow-y-auto border-l border-white/10 bg-[#0b0f14] p-5 shadow-2xl fade-in"
            onClick={(event) => event.stopPropagation()}
          >
            {dossieLoading && !dossie ? (
              <Loading label="A compor o dossiê…" />
            ) : dossie ? (
              <>
                <header className="mb-4 flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-bold">{dossie.nome ?? dossie.nif}</h2>
                    <p className="font-mono text-xs text-muted-foreground">
                      NIF {dossie.nif} · {dossie.pais} · {formatNumber(dossie.contratos_total)} contratos
                    </p>
                  </div>
                  <button
                    onClick={() => setDossie(null)}
                    className="rounded-lg glass-card px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    fechar
                  </button>
                </header>

                <div className="mb-4 grid grid-cols-2 gap-3">
                  <Kpi icon={Coins} label="Valor (amostra)" value={formatCompactEuro(dossie.resumo.valor_total)} />
                  <Kpi
                    icon={Scale}
                    label="Desvio mediano"
                    value={formatRatio(dossie.resumo.desvio_mediano)}
                    color="text-sky-300"
                    glow="glow-blue"
                  />
                  <Kpi
                    icon={Gavel}
                    label="Ajuste direto"
                    value={formatPct(dossie.resumo.taxa_ajuste_direto)}
                    color="text-rose-300"
                    glow="glow-rose"
                  />
                  <Kpi
                    icon={Building2}
                    label="Adjudicantes distintos"
                    value={formatNumber(dossie.resumo.adjudicantes_distintos)}
                    sub={`aditivos ${formatPct(dossie.resumo.taxa_aditivo)}`}
                  />
                </div>

                {(dossie.sinais ?? []).length > 0 && (
                  <SectionCard icon={AlertTriangle} title="Sinais" className="mb-4" subtitle="Clique num sinal para ver o que está por trás da contagem.">
                    <div className="flex flex-wrap gap-2">
                      {dossie.sinais.map((sinal) => {
                        const detalhe = detalheDoSinal(sinal.padrao, dossie);
                        const aberto = sinalAberto === sinal.padrao;
                        return (
                          <button
                            key={`${sinal.padrao}-${sinal.detalhe}`}
                            onClick={() => setSinalAberto(aberto ? null : sinal.padrao)}
                            title={detalhe ? "ver quais" : sinal.detalhe}
                            className={`rounded-full border px-2.5 py-1 text-left text-[11px] transition ${
                              aberto ? "border-teal-400/40 bg-teal-400/10 text-teal-100" : "border-white/10 hover:bg-white/5"
                            }`}
                          >
                            <span className={aberto ? "" : "text-muted-foreground"}>{padraoLabel(sinal.padrao)}:</span>{" "}
                            {sinal.detalhe}
                            {detalhe && <span className="ml-1.5 text-teal-300">{aberto ? "▾" : "▸"}</span>}
                          </button>
                        );
                      })}
                    </div>

                    {sinalAberto &&
                      (() => {
                        const sinal = (dossie.sinais ?? []).find((item) => item.padrao === sinalAberto);
                        const detalhe = sinal ? detalheDoSinal(sinal.padrao, dossie) : null;
                        if (!detalhe) return null;
                        return (
                          <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
                            <div className="mb-2 flex items-center justify-between gap-2">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-200">{detalhe.titulo}</p>
                              {detalhe.nota && <span className="text-[10px] text-muted-foreground">{detalhe.nota}</span>}
                            </div>
                            {detalhe.itens.length === 0 ? (
                              <p className="text-xs text-muted-foreground">Sem itens na amostra do dossiê.</p>
                            ) : (
                              <ul className="max-h-64 space-y-1 overflow-y-auto pr-1 text-xs">
                                {detalhe.itens.map((item, index) => (
                                  <li key={`${item.texto}-${index}`} className="rounded-lg border border-white/5 px-2 py-1.5">
                                    <p className="line-clamp-2 text-foreground/90">{item.texto}</p>
                                    {item.extra && <p className="mt-0.5 text-[10px] text-muted-foreground">{item.extra}</p>}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        );
                      })()}
                  </SectionCard>
                )}

                <SectionCard
                  icon={Network}
                  title="Grafo de análise"
                  subtitle="Empresa ↔ adjudicantes, órgãos sociais e processos do CIRE (com quem mais lá aparece)."
                  className="mb-4"
                  actions={
                    <div className="flex flex-wrap items-center gap-1 text-xs">
                      {mostrarGrafo && (
                        <>
                          {(["hierarchical", "circular", "network"] as const).map((option) => (
                            <button
                              key={option}
                              onClick={() => {
                                setDossieLayout(option);
                                setDossieLayoutVersion((value) => value + 1);
                              }}
                              className={`rounded-lg px-2 py-1 transition ${
                                dossieLayout === option ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground hover:text-foreground"
                              }`}
                            >
                              {option === "network" ? "rede" : option === "hierarchical" ? "hierárquico" : "circular"}
                            </button>
                          ))}
                          <span className="mx-1 text-white/10">|</span>
                          {(["contratos", "valor"] as const).map((option) => (
                            <button
                              key={option}
                              onClick={() => setDossieMetric(option)}
                              className={`rounded-lg px-2 py-1 transition ${
                                dossieMetric === option ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground hover:text-foreground"
                              }`}
                            >
                              {option}
                            </button>
                          ))}
                          <span className="mx-1 text-white/10">|</span>
                        </>
                      )}
                      <button
                        onClick={() => setMostrarGrafo((valor) => !valor)}
                        className={`rounded-lg border px-2 py-1 transition ${
                          mostrarGrafo
                            ? "border-white/10 text-muted-foreground hover:text-foreground"
                            : "border-teal-400/30 bg-teal-400/10 text-teal-100"
                        }`}
                        title="Desenhar o grafo (simulação no browser: é o passo mais caro do dossiê)"
                      >
                        {mostrarGrafo ? "ocultar grafo" : "desenhar grafo"}
                      </button>
                    </div>
                  }
                >
                  {!mostrarGrafo ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <p className="text-xs text-muted-foreground">
                        {grafoDossie
                          ? `${formatNumber(grafoDossie.nodes.length)} nós e ${formatNumber(grafoDossie.edges.length)} ligações prontos a desenhar (${formatNumber((dossie.grafo?.nodes ?? []).filter((no) => no.type === "pessoa").length)} pessoas, ${formatNumber((dossie.grafo?.nodes ?? []).filter((no) => no.type === "processo").length)} processos).`
                          : "Sem relações para desenhar nesta entidade."}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        As listas completas (contratos, cargos, processos e intervenientes) estão nas secções abaixo.
                      </p>
                    </div>
                  ) : grafoDossie && (grafoDossie.nodes.length ?? 0) > 1 ? (
                    <>
                      <GraphCanvas
                        graph={grafoDossie}
                        layout={dossieLayout}
                        metric={dossieMetric}
                        layoutVersion={dossieLayoutVersion}
                        heightClass="h-[360px]"
                        nodeSummary={resumoNoDossie}
                      />
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        Verde = entidades (a empresa e quem lhe compra) · rosa = pessoas (órgãos sociais e papéis
                        processuais) · azul = processos do CIRE. As ligações pessoa→empresa usam apenas{" "}
                        <strong>órgãos sociais</strong>.
                      </p>
                    </>
                  ) : (
                    <EmptyState>
                      Sem relações para desenhar nesta entidade: não foram encontrados adjudicantes na amostra, cargos de órgãos
                      sociais registados nem processos no CIRE.
                    </EmptyState>
                  )}
                </SectionCard>

                {(dossie.lacos ?? []).length > 0 && (
                  <SectionCard
                    icon={Users}
                    title="Quem se cruza nos processos"
                    subtitle="Intervenientes dos processos do CIRE desta empresa (administradores, credores, outras empresas)."
                    className="mb-4"
                  >
                    <ul className="max-h-64 space-y-1 overflow-y-auto pr-1 text-xs">
                      {(dossie.lacos ?? []).map((laco, index) => (
                        <li
                          key={`${laco.processo}-${laco.nif}-${index}`}
                          className="flex items-start justify-between gap-3 rounded-lg border border-rose-400/15 bg-rose-400/[0.04] px-2 py-1.5"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-rose-100">{laco.nome ?? laco.nif}</span>
                            <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                              {laco.papel ?? "interveniente"} · processo {laco.processo ?? "—"}
                            </span>
                          </span>
                          {laco.nif && (
                            <button
                              onClick={() => void openDossie(laco.nif)}
                              className="shrink-0 rounded-lg border border-white/10 px-2 py-0.5 text-[10px] text-teal-200 transition hover:bg-white/5"
                              title="Abrir o dossiê desta entidade"
                            >
                              abrir
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </SectionCard>
                )}

                <SectionCard
                  icon={FileSearch}
                  title="Contratos"
                  subtitle={`${formatNumber(dossieContratos.length)} de ${formatNumber(dossie.contratos.length)} contratos da amostra (${formatNumber(dossie.contratos_total)} no portal).`}
                  className="mb-4"
                  actions={
                    dossieFiltrosAtivos > 0 ? (
                      <button
                        onClick={limparFiltrosDossie}
                        className="flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-1 text-xs text-muted-foreground transition hover:bg-white/5"
                      >
                        <X size={12} /> limpar {dossieFiltrosAtivos}
                      </button>
                    ) : undefined
                  }
                >
                  {/* ------------------------------------------- filtros do dossiê */}
                  <div className="mb-3 grid gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:grid-cols-2">
                    <FilterField label="Pesquisar" className="sm:col-span-2">
                      <SearchInput
                        value={dossieQuery}
                        onChange={setDossieQuery}
                        placeholder="objeto, CPV, procedimento, adjudicante…"
                      />
                    </FilterField>
                    <FilterField label="Ano de">
                      <input
                        value={dossieAnoDe}
                        onChange={(event) => setDossieAnoDe(event.target.value.replace(/\D/g, "").slice(0, 4))}
                        placeholder="min"
                        className={INPUT_CLASS}
                      />
                    </FilterField>
                    <FilterField label="Ano até">
                      <input
                        value={dossieAnoAte}
                        onChange={(event) => setDossieAnoAte(event.target.value.replace(/\D/g, "").slice(0, 4))}
                        placeholder="max"
                        className={INPUT_CLASS}
                      />
                    </FilterField>
                    <FilterField label="Valor mínimo (€)">
                      <input
                        value={dossieValorMin}
                        onChange={(event) => setDossieValorMin(event.target.value.replace(/[^\d]/g, ""))}
                        placeholder="0"
                        className={INPUT_CLASS}
                      />
                    </FilterField>
                    <FilterField label="Aditivo registado">
                      <select
                        value={dossieAditivo}
                        onChange={(event) => setDossieAditivo(event.target.value as "" | "sim" | "nao")}
                        className={SELECT_CLASS}
                      >
                        <option value="">todos</option>
                        <option value="sim">só com aditivo</option>
                        <option value="nao">só sem aditivo</option>
                      </select>
                    </FilterField>
                    <FilterField label="Ordenar por">
                      <select
                        value={dossieOrdem}
                        onChange={(event) => setDossieOrdem(event.target.value as "recente" | "valor" | "desvio")}
                        className={SELECT_CLASS}
                      >
                        <option value="recente">Mais recente</option>
                        <option value="valor">Valor (maior)</option>
                        <option value="desvio">Desvio de preço (maior)</option>
                      </select>
                    </FilterField>
                    <FilterField label="Mostrar">
                      <select
                        value={dossieLimite}
                        onChange={(event) => setDossieLimite(Number(event.target.value))}
                        className={SELECT_CLASS}
                      >
                        {[10, 25, 50, 100, 300].map((value) => (
                          <option key={value} value={value}>
                            {value} linhas
                          </option>
                        ))}
                      </select>
                    </FilterField>
                  </div>

                  {dossieContratos.length === 0 ? (
                    <EmptyState>Nenhum contrato corresponde aos filtros.</EmptyState>
                  ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[640px] border-collapse text-left text-xs">
                      <thead>
                        <tr className="whitespace-nowrap text-[10px] uppercase tracking-wide text-muted-foreground">
                          <th className="py-2 pr-3">Data</th>
                          <th className="py-2 pr-3">Objeto</th>
                          <th className="py-2 pr-3">Adjudicante</th>
                          <th className="py-2 pr-3 text-right">Valor</th>
                          <th className="py-2 pr-3 text-right">Desvio</th>
                          <th className="py-2 text-right">Concorr.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dossieContratos.map((contrato, index) => (
                          <tr key={`${contrato.id ?? index}`} className="border-t border-white/5 align-top">
                            <td className="whitespace-nowrap py-2 pr-3">
                              {formatDate(contrato.data_publicacao) !== "—"
                                ? formatDate(contrato.data_publicacao)
                                : (contrato.ano ?? "—")}
                            </td>
                            <td className="w-[290px] py-2 pr-3">
                              <div className="line-clamp-2">{contrato.objeto || "—"}</div>
                              <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                                CPV {contrato.cpv ?? "—"} · {contrato.procedimento ?? "—"}
                                {contrato.ajuste_direto && " · ajuste direto"}
                              </div>
                            </td>
                            <td className="w-[150px] py-2 pr-3 text-muted-foreground">
                              <div className="line-clamp-2">{contrato.adjudicante ?? "—"}</div>
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">
                              {formatCompactEuro(contrato.valor)}
                              {(contrato.ratio_efetivo ?? 0) > 1.15 && (
                                <div className="text-[10px] text-rose-300">aditivo {formatRatio(contrato.ratio_efetivo)}</div>
                              )}
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right">{formatRatio(contrato.ratio_base)}</td>
                            <td className="whitespace-nowrap py-2 text-right">
                              {contrato.n_concorrentes ?? "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  )}
                </SectionCard>

                <SectionCard icon={Users} title="Cargos e processos" className="mb-4">
                  {dossie.cargos_sociais.length === 0 && dossie.intervenientes_cire.length === 0 && dossie.insolvencias.length === 0 ? (
                    <EmptyState>Sem cargos sociais nem processos associados a este NIF.</EmptyState>
                  ) : (
                    <div className="space-y-3 text-xs">
                      {dossie.cargos_sociais.length > 0 && (
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                            Órgãos sociais ({dossie.cargos_sociais.length})
                          </p>
                          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
                            {dossie.cargos_sociais.map((person) => (
                              <li key={person.nif} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                                <span className="font-semibold">{person.nome}</span>
                                <span className="ml-2 text-muted-foreground">
                                  {person.cargos.map((cargo) => `${cargo.role ?? ""} (${cargo.role_org ?? ""})`).join(", ")}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {dossie.insolvencias.length > 0 && (
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                            Insolvências (CIRE)
                            {dossie.insolvencias_total && dossie.insolvencias_total > dossie.insolvencias.length
                              ? ` · a mostrar ${dossie.insolvencias.length} de ${dossie.insolvencias_total}`
                              : ` · ${dossie.insolvencias.length} processo(s)`}
                          </p>
                          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
                            {dossie.insolvencias.map((row, index) => (
                              <li key={`${row.processo}-${index}`} className="rounded-lg border border-rose-400/20 bg-rose-400/5 p-2">
                                <span className="text-rose-200">{row.especie ?? "—"}</span>
                                <span className="ml-2 text-muted-foreground">
                                  {formatDate(row.data)} · {row.tribunal ?? "—"}
                                </span>
                                <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                                  {row.processo ?? "sem número"} {row.ato ? `· ${row.ato}` : ""}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {(dossie.intervenientes_processos ?? []).length > 0 && (
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                            Intervenientes nos processos ({(dossie.intervenientes_processos ?? []).length})
                          </p>
                          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
                            {(dossie.intervenientes_processos ?? []).map((row, index) => (
                              <li
                                key={`${row.processo}-${row.nif}-${index}`}
                                className="flex items-start justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1"
                              >
                                <span className="min-w-0">
                                  <span className="block truncate">{row.nome ?? row.nif}</span>
                                  <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                                    {row.papel ?? "interveniente"} · {row.processo}
                                  </span>
                                </span>
                                <span className="flex shrink-0 flex-col items-end gap-1">
                                  <span className="font-mono text-[10px] text-muted-foreground">{row.nif}</span>
                                  <button
                                    onClick={() => void openDossie(row.nif)}
                                    className="rounded-lg border border-white/10 px-2 py-0.5 text-[10px] text-teal-200 transition hover:bg-white/5"
                                  >
                                    abrir
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {dossie.intervenientes_cire.length > 0 && (
                        <div>
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                            Intervenientes em processos
                          </p>
                          <p className="text-muted-foreground">
                            {dossie.intervenientes_cire
                              .slice(0, 8)
                              .map((person) => `${person.nome} (${person.cargos[0]?.role ?? "—"})`)
                              .join(" · ")}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </SectionCard>

                <SectionCard icon={Newspaper} title="Notícias">
                  {dossie.noticias.length === 0 ? (
                    <EmptyState>Sem menções encontradas nos índices de notícias.</EmptyState>
                  ) : (
                    <ul className="space-y-2 text-xs">
                      {dossie.noticias.map((item, index) => (
                        <li key={`${item.url ?? item.titulo}-${index}`} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                          <p className="font-medium">{item.titulo ?? "(sem título)"}</p>
                          <p className="text-muted-foreground">
                            {item.canal} · {item.fonte ?? "—"} · {formatDate(item.data)}
                          </p>
                          {item.url && (
                            <a href={item.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:text-sky-200">
                              abrir <ExternalLink size={10} className="inline" />
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </SectionCard>
              </>
            ) : (
              <EmptyState tone="warn">Não foi possível compor o dossiê.</EmptyState>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
