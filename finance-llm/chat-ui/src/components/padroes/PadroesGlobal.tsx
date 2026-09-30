/**
 * **Dashboard global** — o universo inteiro, numa só leitura.
 *
 * O resto do módulo «Deteção de padrões» trabalha sobre amostras. Aqui a pergunta
 * é outra: *o que dizem os 2,2 M de contratos portugueses (4 M espanhóis), ano a
 * ano?* As métricas vêm de agregações do Elasticsearch sobre o índice inteiro,
 * materializadas em `finance_padroes_global` por um processo de sincronização —
 * o dashboard é rápido porque lê documentos já prontos.
 *
 * Em cima disso há a **pesquisa tipo Google**: texto livre e filtros de período
 * (dia, semana, mês, ano), empresa, adjudicante, CPV, procedimento, valor e
 * concorrentes, com facetas calculadas sobre o universo e não sobre uma amostra.
 * Os âmbitos «Empresas», «Recolha (pessoas e empresas)» e «Notícias» usam a
 * pesquisa unificada do IQ OS, para a mesma caixa servir para tudo.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AlertTriangle,
  BarChart3,
  Building2,
  CalendarRange,
  FileSearch,
  Globe2,
  Layers,
  ListFilter,
  Newspaper,
  Percent,
  RefreshCw,
  Scale,
  Search,
  Sigma,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import {
  getPadroesGlobal,
  getPadroesGlobalEstado,
  getPadroesGlobalMeta,
  pesquisarPadroesGlobal,
  sincronizarPadroesGlobal,
} from "../../padroesApi";
import type {
  PadroesGlobalContrato,
  PadroesGlobalDashboard,
  PadroesGlobalEstado,
  PadroesGlobalFiltros,
  PadroesGlobalGranularidade,
  PadroesGlobalMeta,
  PadroesGlobalPesquisa,
} from "../../padroesApi";
import { searchSuggest, unifiedSearch } from "../../searchApi";
import type { SearchGroup, SearchScopeId, SearchSuggestion } from "../../searchApi";
import {
  Chip,
  EmptyState,
  FilterField,
  Kpi,
  Loading,
  SectionCard,
  formatCompactEuro,
  formatDate,
  formatNumber,
  formatPct,
} from "./padroesKit";

const SELECT_CLASS =
  "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground";
const INPUT_CLASS = SELECT_CLASS;

/** Âmbitos da caixa de pesquisa (o primeiro é o universo de contratos). */
type Ambito = "contratos" | "all" | "entities" | "scraped" | "news";

const AMBITOS: { id: Ambito; label: string; icon: typeof Search; hint: string }[] = [
  { id: "contratos", label: "Contratos", icon: FileSearch, hint: "Universo de contratos públicos (com filtros e facetas)" },
  { id: "all", label: "Tudo", icon: Globe2, hint: "Todos os âmbitos do IQ OS" },
  { id: "entities", label: "Empresas", icon: Building2, hint: "Cadastro de entidades e empresas" },
  { id: "scraped", label: "Pessoas / recolha", icon: Users, hint: "Dados recolhidos (inclui pessoas e empresas)" },
  { id: "news", label: "Notícias", icon: Newspaper, hint: "Notícias de mercado" },
];

const GRANULARIDADES: { id: PadroesGlobalGranularidade; label: string }[] = [
  { id: "dia", label: "Dia" },
  { id: "semana", label: "Semana" },
  { id: "mes", label: "Mês" },
  { id: "ano", label: "Ano" },
];

type Estado = {
  q: string;
  granularidade: PadroesGlobalGranularidade;
  dataFrom: string;
  dataTo: string;
  campoData: "publicacao" | "decisao" | "assinatura";
  anoFrom: string;
  anoTo: string;
  empresa: string;
  adjudicante: string;
  cpv: string;
  procedimento: string;
  valorMin: string;
  valorMax: string;
  concorrentesMin: string;
  concorrentesMax: string;
  soAditivo: boolean;
  soAjusteDireto: boolean;
  size: number;
};

const ESTADO_INICIAL: Estado = {
  q: "",
  granularidade: "mes",
  dataFrom: "",
  dataTo: "",
  campoData: "publicacao",
  anoFrom: "",
  anoTo: "",
  empresa: "",
  adjudicante: "",
  cpv: "",
  procedimento: "",
  valorMin: "",
  valorMax: "",
  concorrentesMin: "",
  concorrentesMax: "",
  soAditivo: false,
  soAjusteDireto: false,
  size: 25,
};

function aNumero(valor: string): number | undefined {
  const limpo = valor.replace(/[^\d.,]/g, "").replace(",", ".");
  if (!limpo) return undefined;
  const numero = Number(limpo);
  return Number.isFinite(numero) ? numero : undefined;
}

/** Quantos filtros estão ligados (para o contador do botão «limpar»). */
function filtrosAtivos(estado: Estado): number {
  let total = 0;
  if (estado.q) total += 1;
  if (estado.dataFrom || estado.dataTo) total += 1;
  if (estado.anoFrom || estado.anoTo) total += 1;
  if (estado.empresa) total += 1;
  if (estado.adjudicante) total += 1;
  if (estado.cpv) total += 1;
  if (estado.procedimento) total += 1;
  if (estado.valorMin || estado.valorMax) total += 1;
  if (estado.concorrentesMin || estado.concorrentesMax) total += 1;
  if (estado.soAditivo) total += 1;
  if (estado.soAjusteDireto) total += 1;
  return total;
}

export function PadroesGlobal({ pais, onDossie }: { pais: string; onDossie?: (nif?: string | null) => void }) {
  const [dashboard, setDashboard] = useState<PadroesGlobalDashboard | null>(null);
  const [meta, setMeta] = useState<PadroesGlobalMeta | null>(null);
  const [estadoSync, setEstadoSync] = useState<PadroesGlobalEstado | null>(null);
  const [resultado, setResultado] = useState<PadroesGlobalPesquisa | null>(null);
  const [grupos, setGrupos] = useState<SearchGroup[]>([]);
  const [filtros, setFiltros] = useState<Estado>(ESTADO_INICIAL);
  const [ambito, setAmbito] = useState<Ambito>("contratos");
  const [sugestoes, setSugestoes] = useState<SearchSuggestion[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [pesquisando, setPesquisando] = useState(false);
  const [sincronizando, setSincronizando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [pagina, setPagina] = useState(0);

  const anosMaterializados = meta?.anos ?? dashboard?.meta?.anos ?? [];

  /* ----------------------------------------------------------- leitura inicial */

  const carregar = useCallback(
    async (granularidade: PadroesGlobalGranularidade) => {
      setCarregando(true);
      try {
        const [painel, informacao] = await Promise.all([getPadroesGlobal({ pais, granularidade }), getPadroesGlobalMeta(pais)]);
        if (painel.error) throw new Error(painel.error);
        setDashboard(painel);
        setMeta(informacao);
        setEstadoSync(informacao.estado ?? painel.estado ?? null);
        setErro(null);
        return painel;
      } catch (problema) {
        setErro(problema instanceof Error ? problema.message : "falha ao ler o universo");
        return null;
      } finally {
        setCarregando(false);
      }
    },
    [pais],
  );

  useEffect(() => {
    void carregar(filtros.granularidade);
    // Uma mudança de país recomeça tudo: o resultado de uma pesquisa anterior é
    // de outro universo.
    setResultado(null);
    setGrupos([]);
    setPagina(0);
  }, [carregar, pais, filtros.granularidade]);

  /* ------------------------------------------------------------ sincronização */

  // Enquanto o processo corre, a página acompanha o estado e recarrega no fim.
  useEffect(() => {
    if (!estadoSync?.a_correr) return;
    const relogio = window.setInterval(() => {
      void getPadroesGlobalEstado()
        .then((novo) => {
          setEstadoSync(novo);
          if (!novo.a_correr) {
            setSincronizando(false);
            void carregar(filtros.granularidade);
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(relogio);
  }, [estadoSync?.a_correr, carregar, filtros.granularidade]);

  const sincronizar = useCallback(async () => {
    setSincronizando(true);
    setErro(null);
    try {
      const resposta = await sincronizarPadroesGlobal({ pais });
      setEstadoSync({ ...resposta, a_correr: true });
    } catch (problema) {
      setSincronizando(false);
      setErro(problema instanceof Error ? problema.message : "falha a arrancar a sincronização");
    }
  }, [pais]);

  /* --------------------------------------------------------------- pesquisa */

  // Sugestões enquanto se escreve (empresas, pessoas, notícias e contratos).
  useEffect(() => {
    const termo = filtros.q.trim();
    if (termo.length < 3) {
      setSugestoes([]);
      return;
    }
    const temporizador = window.setTimeout(() => {
      void searchSuggest(termo, 6)
        .then((resposta) => setSugestoes(resposta.items ?? []))
        .catch(() => setSugestoes([]));
    }, 250);
    return () => window.clearTimeout(temporizador);
  }, [filtros.q]);

  const pesquisar = useCallback(
    async (paginaPedida = 0, estado: Estado = filtros) => {
      setPesquisando(true);
      setErro(null);
      try {
        if (ambito === "contratos") {
          const payload: PadroesGlobalFiltros = {
            pais,
            q: estado.q || undefined,
            data_from: estado.dataFrom || undefined,
            data_to: estado.dataTo || undefined,
            campo_data: estado.campoData,
            ano_from: aNumero(estado.anoFrom) ?? null,
            ano_to: aNumero(estado.anoTo) ?? null,
            empresa: estado.empresa || undefined,
            adjudicante: estado.adjudicante || undefined,
            cpv: estado.cpv || undefined,
            procedimento: estado.procedimento || undefined,
            valor_min: aNumero(estado.valorMin) ?? null,
            valor_max: aNumero(estado.valorMax) ?? null,
            concorrentes_min: aNumero(estado.concorrentesMin) ?? null,
            concorrentes_max: aNumero(estado.concorrentesMax) ?? null,
            so_aditivo: estado.soAditivo,
            so_ajuste_direto: estado.soAjusteDireto,
            granularidade: estado.granularidade,
            // Os topos e a série são os agregados caros: pedem-se só na primeira página.
            facets: paginaPedida === 0,
            size: estado.size,
            from: paginaPedida * estado.size,
          };
          const resposta = await pesquisarPadroesGlobal(payload);
          if (resposta.error) throw new Error(resposta.error);
          // Ao mudar de página não se pedem os topos/série (agregados caros):
          // mantém-se o que já estava desenhado, para o painel não piscar.
          setResultado((anterior) =>
            paginaPedida > 0 && anterior
              ? {
                  ...resposta,
                  serie: resposta.serie?.length ? resposta.serie : anterior.serie,
                  facetas: resposta.facetas?.cpvs?.length ? resposta.facetas : anterior.facetas,
                }
              : resposta,
          );
          setGrupos([]);
        } else {
          const resposta = await unifiedSearch({ q: estado.q, scope: ambito as SearchScopeId, size: 12, offset: paginaPedida * 12 });
          if (resposta.error) throw new Error(resposta.error);
          setGrupos(resposta.groups ?? []);
          setResultado(null);
        }
        setPagina(paginaPedida);
        setSugestoes([]);
      } catch (problema) {
        setErro(problema instanceof Error ? problema.message : "falha na pesquisa");
      } finally {
        setPesquisando(false);
      }
    },
    [ambito, filtros, pais],
  );

  const limparPesquisa = useCallback(() => {
    setResultado(null);
    setGrupos([]);
    setFiltros((atual) => ({ ...ESTADO_INICIAL, granularidade: atual.granularidade }));
    setPagina(0);
  }, []);

  /* ------------------------------------------------------------------ gráficos */

  const serie = useMemo(() => {
    const pontos = (resultado?.serie?.length ? resultado.serie : dashboard?.serie) ?? [];
    return pontos.map((ponto) => ({
      periodo: ponto.periodo?.length === 10 || ponto.periodo?.includes("T") ? String(ponto.periodo).slice(0, 10) : ponto.periodo,
      contratos: ponto.contratos ?? 0,
      valor: ponto.valor ?? 0,
    }));
  }, [resultado?.serie, dashboard?.serie]);

  const ativos = filtrosAtivos(filtros);
  const contratos = resultado?.items ?? [];
  const kpis = resultado?.kpis;
  const porAno = dashboard?.por_ano ?? [];
  // O backend aceita `from` até 10 000: a paginação para aí (e diz que parou).
  const maxPaginas = Math.max(1, Math.floor(10000 / (resultado?.pagina?.size || filtros.size)) + 1);
  const totalPaginas = resultado ? Math.min(maxPaginas, Math.max(1, Math.ceil((resultado.total ?? 0) / (resultado.pagina?.size || filtros.size)))) : 1;
  const paginacaoTruncada = Boolean(resultado) && Math.ceil((resultado?.total ?? 0) / (resultado?.pagina?.size || filtros.size)) > maxPaginas;
  const topCpv = resultado?.facetas?.cpvs?.length ? resultado.facetas.cpvs : dashboard?.top_cpv ?? [];
  const topAdjudicatarias = resultado?.facetas?.adjudicatarias?.length ? resultado.facetas.adjudicatarias : dashboard?.top_adjudicatarias ?? [];
  const topAdjudicantes = resultado?.facetas?.adjudicantes ?? [];
  const procedimentos = resultado?.facetas?.procedimentos?.length ? resultado.facetas.procedimentos : dashboard?.procedimentos ?? [];

  const abrirContratosDoAno = (ano: number) => {
    const novo: Estado = { ...ESTADO_INICIAL, granularidade: filtros.granularidade, anoFrom: String(ano), anoTo: String(ano) };
    setFiltros(novo);
    void pesquisar(0, novo);
  };

  return (
    <div className="space-y-5">
      {/* ---------------------------------------------------- estado do universo */}
      <SectionCard
        icon={Globe2}
        title="Universo de contratos públicos"
        subtitle={meta?.aviso ?? "Métricas calculadas por agregação sobre o índice inteiro (sem amostra)."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={(estadoSync?.a_correr ?? false) ? "amber" : "teal"}>
              {estadoSync?.a_correr ? "a sincronizar…" : meta?.guardado ? "materializado" : "sem métricas"}
            </Chip>
            <button
              onClick={() => void sincronizar()}
              disabled={sincronizando || (estadoSync?.a_correr ?? false)}
              className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
            >
              <RefreshCw size={13} className={estadoSync?.a_correr ? "animate-spin" : undefined} />
              {estadoSync?.a_correr ? "a agregar o universo…" : "sincronizar universo"}
            </button>
          </div>
        }
      >
        <div className="grid gap-3 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide">Índice agregado</p>
            <p className="mt-0.5 font-mono text-[11px] text-foreground">{meta?.indice ?? dashboard?.indice ?? "—"}</p>
            <p className="mt-0.5">{formatNumber(meta?.documentos_universo ?? dashboard?.totais?.documentos_universo)} contratos varridos</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide">Anos materializados</p>
            <p className="mt-0.5 text-foreground">
              {anosMaterializados.length ? `${anosMaterializados[0]}–${anosMaterializados[anosMaterializados.length - 1]}` : "—"}
            </p>
            <p className="mt-0.5">{formatNumber(anosMaterializados.length)} ano(s) · {formatNumber(meta?.documentos)} documentos</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide">Última agregação</p>
            <p className="mt-0.5 text-foreground">{meta?.materializado_em ? formatDate(meta.materializado_em) : "—"}</p>
            <p className="mt-0.5">
              {meta?.duracao_s != null ? `${meta.duracao_s.toFixed(1)} s a varrer o índice` : "sem duração registada"}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide">Processo</p>
            <p className="mt-0.5 text-foreground">{estadoSync?.a_correr ? "a correr" : estadoSync?.erro ? "falhou" : "em repouso"}</p>
            <p className="mt-0.5">
              {estadoSync?.erro
                ? estadoSync.erro
                : estadoSync?.resultado?.anos?.length
                  ? `${estadoSync.resultado.anos.join(", ")}`
                  : (estadoSync?.progresso ?? "pronto a sincronizar")}
            </p>
          </div>
        </div>
        {!meta?.guardado && !carregando && (
          <div className="mt-3">
            <EmptyState tone="warn">
              Ainda não há métricas do universo materializadas: as agregações percorrem mais de 2 milhões de contratos e demoram
              dezenas de segundos. Carregue em «sincronizar universo» — corre em segundo plano e a página acompanha o progresso.
            </EmptyState>
          </div>
        )}
        {erro && (
          <div className="mt-3">
            <EmptyState tone="warn">{erro}</EmptyState>
          </div>
        )}
      </SectionCard>

      {/* ------------------------------------------------------- caixa de pesquisa */}
      <section className="glass-card gradient-border rounded-2xl p-5">
        <div className="flex flex-wrap items-center gap-1.5">
          {AMBITOS.map(({ id, label, icon: Icon, hint }) => (
            <button
              key={id}
              title={hint}
              onClick={() => setAmbito(id)}
              className={`flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs transition ${
                ambito === id ? "bg-teal-400/10 text-teal-200 border border-teal-400/25" : "border border-white/10 text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        <div className="relative mt-3">
          <div className="flex items-center gap-3 rounded-2xl border border-white/15 bg-black/40 px-4 py-3">
            <Search size={18} className="shrink-0 text-teal-300" />
            <input
              value={filtros.q}
              onChange={(event) => setFiltros((atual) => ({ ...atual, q: event.target.value }))}
              onKeyDown={(event) => {
                if (event.key === "Enter") void pesquisar(0);
              }}
              placeholder={
                ambito === "contratos"
                  ? "Pesquisar no universo: objeto, empresa, adjudicante, CPV, NIF…"
                  : "Pesquisar em todo o IQ OS (empresas, pessoas, notícias…)"
              }
              className="w-full bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground/60"
            />
            {filtros.q && (
              <button onClick={() => setFiltros((atual) => ({ ...atual, q: "" }))} className="text-muted-foreground hover:text-foreground">
                <X size={15} />
              </button>
            )}
            <button
              onClick={() => void pesquisar(0)}
              disabled={pesquisando}
              className="shrink-0 rounded-xl bg-teal-400/15 px-3 py-1.5 text-sm text-teal-100 transition hover:bg-teal-400/25 disabled:opacity-50"
            >
              {pesquisando ? "a procurar…" : "pesquisar"}
            </button>
          </div>

          {sugestoes.length > 0 && (
            <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-white/10 bg-[#0d1117] shadow-xl">
              {sugestoes.map((sugestao, indice) => (
                <button
                  key={`${sugestao.text}-${indice}`}
                  onClick={() => {
                    setFiltros((atual) => ({ ...atual, q: sugestao.text }));
                    setSugestoes([]);
                  }}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs transition hover:bg-white/5"
                >
                  <span className="truncate">{sugestao.text}</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">{sugestao.hint ?? sugestao.scope}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {ambito === "contratos" ? (
          <>
            <div className="mt-4 grid gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
              <FilterField label="Granularidade">
                <select
                  value={filtros.granularidade}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, granularidade: event.target.value as PadroesGlobalGranularidade }))}
                  className={SELECT_CLASS}
                >
                  {GRANULARIDADES.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Campo de data">
                <select
                  value={filtros.campoData}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, campoData: event.target.value as Estado["campoData"] }))}
                  className={SELECT_CLASS}
                >
                  <option value="publicacao">Publicação</option>
                  <option value="decisao">Decisão</option>
                  <option value="assinatura">Assinatura</option>
                </select>
              </FilterField>
              <FilterField label="Data de">
                <input
                  type="date"
                  value={filtros.dataFrom}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, dataFrom: event.target.value }))}
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Data até">
                <input
                  type="date"
                  value={filtros.dataTo}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, dataTo: event.target.value }))}
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Ano de">
                <input
                  value={filtros.anoFrom}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, anoFrom: event.target.value.replace(/\D/g, "").slice(0, 4) }))}
                  placeholder="min"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Ano até">
                <input
                  value={filtros.anoTo}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, anoTo: event.target.value.replace(/\D/g, "").slice(0, 4) }))}
                  placeholder="max"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Empresa (NIF ou nome)">
                <input
                  value={filtros.empresa}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, empresa: event.target.value }))}
                  placeholder="503439800 / ACME"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Adjudicante (NIF ou nome)">
                <input
                  value={filtros.adjudicante}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, adjudicante: event.target.value }))}
                  placeholder="Município…"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="CPV (prefixo)">
                <input
                  value={filtros.cpv}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, cpv: event.target.value.replace(/\D/g, "").slice(0, 8) }))}
                  placeholder="45000000"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Procedimento">
                <input
                  value={filtros.procedimento}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, procedimento: event.target.value }))}
                  placeholder="ajuste direto…"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Valor mínimo (€)">
                <input
                  value={filtros.valorMin}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, valorMin: event.target.value.replace(/[^\d]/g, "") }))}
                  placeholder="0"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Valor máximo (€)">
                <input
                  value={filtros.valorMax}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, valorMax: event.target.value.replace(/[^\d]/g, "") }))}
                  placeholder="sem limite"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Concorrentes ≥">
                <input
                  value={filtros.concorrentesMin}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, concorrentesMin: event.target.value.replace(/\D/g, "").slice(0, 3) }))}
                  placeholder="min"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Concorrentes ≤">
                <input
                  value={filtros.concorrentesMax}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, concorrentesMax: event.target.value.replace(/\D/g, "").slice(0, 3) }))}
                  placeholder="max"
                  className={INPUT_CLASS}
                />
              </FilterField>
              <FilterField label="Mostrar">
                <select
                  value={filtros.size}
                  onChange={(event) => setFiltros((atual) => ({ ...atual, size: Number(event.target.value) }))}
                  className={SELECT_CLASS}
                >
                  {[25, 50, 100].map((valor) => (
                    <option key={valor} value={valor}>
                      {valor} linhas
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Sinais">
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setFiltros((atual) => ({ ...atual, soAditivo: !atual.soAditivo }))}
                    className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-2 text-[11px] normal-case transition ${
                      filtros.soAditivo ? "border-rose-400/30 bg-rose-400/10 text-rose-200" : "border-white/10 bg-black/30 text-muted-foreground"
                    }`}
                  >
                    <TrendingUp size={12} /> com aditivo
                  </button>
                  <button
                    onClick={() => setFiltros((atual) => ({ ...atual, soAjusteDireto: !atual.soAjusteDireto }))}
                    className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-2 text-[11px] normal-case transition ${
                      filtros.soAjusteDireto ? "border-amber-400/30 bg-amber-400/10 text-amber-200" : "border-white/10 bg-black/30 text-muted-foreground"
                    }`}
                  >
                    <Percent size={12} /> ajuste direto
                  </button>
                </div>
              </FilterField>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <button
                onClick={() => void pesquisar(0)}
                disabled={pesquisando}
                className="flex items-center gap-1.5 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 py-1.5 text-teal-100 transition hover:bg-teal-400/20 disabled:opacity-50"
              >
                <ListFilter size={13} /> aplicar filtros
              </button>
              <button
                onClick={limparPesquisa}
                className="flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 text-muted-foreground transition hover:text-foreground"
              >
                <X size={13} /> limpar {ativos > 0 ? `(${ativos})` : ""}
              </button>
              <span className="text-muted-foreground">
                {resultado
                  ? `${formatNumber(resultado.total)} contrato(s) no universo com estes filtros`
                  : "sem pesquisa: o painel mostra o universo completo (anos agregados)"}
              </span>
            </div>
          </>
        ) : (
          <p className="mt-3 text-[11px] text-muted-foreground">
            {AMBITOS.find((item) => item.id === ambito)?.hint} — a pesquisa unificada devolve grupos por área; escolha «Contratos» para
            usar os filtros de período, empresa e concorrentes sobre o universo.
          </p>
        )}
      </section>

      {/* ----------------------------------------------------------------- KPIs */}
      {ambito === "contratos" && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            icon={Layers}
            label={resultado ? "Contratos (filtrados)" : "Contratos no universo"}
            value={formatNumber(resultado ? resultado.total : dashboard?.totais?.contratos)}
            sub={
              resultado
                ? `de ${formatNumber(dashboard?.totais?.documentos_universo)} no universo agregado`
                : `${formatNumber(anosMaterializados.length)} ano(s) agregados`
            }
            color="text-teal-300"
          />
          <Kpi
            icon={Sigma}
            label="Valor contratado"
            value={formatCompactEuro(resultado ? kpis?.valor : dashboard?.totais?.valor)}
            sub={`mediana ${formatCompactEuro(resultado ? kpis?.valor_mediano : dashboard?.totais?.valor_mediano)} · médio ${formatCompactEuro(
              resultado ? kpis?.valor_medio : dashboard?.totais?.valor_medio,
            )}`}
            color="text-sky-300"
            glow="glow-blue"
          />
          <Kpi
            icon={Scale}
            label="Ajuste direto"
            value={formatPct(resultado ? kpis?.ajuste_direto?.taxa : dashboard?.totais?.ajuste_direto?.taxa)}
            sub={`${formatNumber(resultado ? kpis?.ajuste_direto?.contratos : dashboard?.totais?.ajuste_direto?.contratos)} contratos · ${formatPct(
              resultado ? kpis?.ajuste_direto?.taxa_valor : dashboard?.totais?.ajuste_direto?.taxa_valor,
            )} do valor · inclui consulta prévia e contratação excluída (critério do motor)`}
            color="text-amber-300"
          />
          <Kpi
            icon={AlertTriangle}
            label="Sem concorrentes registados"
            value={formatNumber(resultado ? kpis?.sem_concorrentes : dashboard?.totais?.sem_concorrentes)}
            sub={
              resultado
                ? "contratos filtrados sem partes concorrentes registadas"
                : `${formatPct(dashboard?.totais?.taxa_sem_concorrentes)} do universo (campo de concorrentes vazio)`
            }
            color="text-rose-300"
            glow="glow-rose"
          />
        </div>
      )}

      {/* ------------------------------------------------------------ série */}
      {(serie.length > 0 || carregando) && ambito === "contratos" && (
        <SectionCard
          icon={BarChart3}
          title={resultado ? "Série dos contratos filtrados" : "Série do universo"}
          subtitle={`Contratos e valor por ${
            (GRANULARIDADES.find((item) => item.id === (resultado?.granularidade ?? filtros.granularidade))?.label ?? "mês").toLowerCase()
          } · o dia e a semana só fazem sentido com filtros de período.`}
        >
          {carregando && serie.length === 0 ? (
            <Loading label="A ler as métricas do universo…" />
          ) : (
            <div className="h-[280px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={serie} margin={{ left: 4, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="periodo" stroke="#8b95a5" fontSize={10} minTickGap={18} />
                  <YAxis yAxisId="contratos" stroke="#8b95a5" fontSize={10} width={54} tickFormatter={(valor) => formatNumber(Number(valor))} />
                  <YAxis
                    yAxisId="valor"
                    orientation="right"
                    stroke="#8b95a5"
                    fontSize={10}
                    width={62}
                    tickFormatter={(valor) => formatCompactEuro(Number(valor))}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null;
                      const ponto = payload[0].payload as { contratos: number; valor: number };
                      return (
                        <div className="rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs">
                          <p className="font-semibold">{String(label)}</p>
                          <p>{formatNumber(ponto.contratos)} contratos</p>
                          <p className="text-muted-foreground">{formatCompactEuro(ponto.valor)}</p>
                        </div>
                      );
                    }}
                  />
                  <Bar yAxisId="contratos" dataKey="contratos" fill="#2dd4bf" radius={[4, 4, 0, 0]} maxBarSize={26} />
                  <Line yAxisId="valor" type="monotone" dataKey="valor" stroke="#fbbf24" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>
      )}

      {/* ------------------------------------------------- resultados da pesquisa */}
      {ambito === "contratos" && resultado && (
        <SectionCard
          icon={Search}
          title="Contratos encontrados"
          subtitle={`Página ${pagina + 1} de ${formatNumber(totalPaginas)} · ordenados pela publicação mais recente.${
            paginacaoTruncada ? " Alargue os filtros: o Elasticsearch só pagina até 10 000 resultados." : ""
          }`}
          actions={
            <div className="flex items-center gap-2 text-xs">
              <button
                onClick={() => void pesquisar(Math.max(0, pagina - 1))}
                disabled={pagina === 0 || pesquisando}
                className="rounded-xl border border-white/10 px-2.5 py-1 transition hover:bg-white/5 disabled:opacity-40"
              >
                anterior
              </button>
              <button
                onClick={() => void pesquisar(Math.min(totalPaginas - 1, pagina + 1))}
                disabled={pagina + 1 >= totalPaginas || pesquisando}
                className="rounded-xl border border-white/10 px-2.5 py-1 transition hover:bg-white/5 disabled:opacity-40"
              >
                seguinte
              </button>
            </div>
          }
        >
          {contratos.length === 0 ? (
            <EmptyState>Nenhum contrato cumpre estes filtros. Alargue o período ou tire a pesquisa de texto.</EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1180px] border-collapse text-left text-sm">
                <thead>
                  <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Ano</th>
                    <th className="py-2 pr-3">Publicação</th>
                    <th className="py-2 pr-3">Objeto</th>
                    <th className="py-2 pr-3">Adjudicatária</th>
                    <th className="py-2 pr-3">Adjudicante</th>
                    <th className="py-2 pr-3 text-right">Valor</th>
                    <th className="py-2 pr-3 text-right">Base</th>
                    <th className="py-2 pr-3 text-right">Efetivo</th>
                    <th className="py-2 pr-3 text-right">Conc.</th>
                    <th className="py-2">Sinais</th>
                  </tr>
                </thead>
                <tbody>
                  {contratos.map((contrato: PadroesGlobalContrato, indice: number) => (
                    <tr key={`${contrato.id ?? indice}`} className="border-t border-white/5 align-top">
                      <td className="whitespace-nowrap py-2 pr-3 text-xs">{contrato.ano ?? "—"}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted-foreground">{formatDate(contrato.data_publicacao)}</td>
                      <td className="w-[320px] py-2 pr-3 text-xs">
                        <div className="line-clamp-2">{contrato.objeto || "—"}</div>
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                          CPV {contrato.cpv ?? "—"}
                          {contrato.cpv_desc ? ` · ${contrato.cpv_desc}` : ""}
                        </div>
                      </td>
                      <td className="w-[200px] py-2 pr-3 text-xs">
                        {contrato.adjudicataria ? (
                          <button
                            onClick={() => onDossie?.(contrato.adjudicataria_nif)}
                            className="block max-w-[190px] truncate text-left text-teal-200 transition hover:text-teal-100"
                            title="Abrir dossiê"
                          >
                            {contrato.adjudicataria}
                          </button>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                        {contrato.adjudicataria_nif && (
                          <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{contrato.adjudicataria_nif}</div>
                        )}
                      </td>
                      <td className="w-[190px] py-2 pr-3 text-xs text-muted-foreground">
                        <div className="line-clamp-2">{contrato.adjudicante ?? "—"}</div>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(contrato.valor)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs text-muted-foreground">
                        {formatCompactEuro(contrato.preco_base)}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs text-muted-foreground">
                        {formatCompactEuro(contrato.valor_efetivo)}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                        {contrato.n_concorrentes ?? "—"}
                      </td>
                      <td className="w-[210px] py-2">
                        <div className="flex flex-wrap gap-1">
                          {contrato.ajuste_direto && <Chip tone="amber">ajuste direto</Chip>}
                          {(contrato.ratio_efetivo ?? 0) > 1.15 && <Chip tone="rose">aditivo {contrato.ratio_efetivo?.toFixed(2)}×</Chip>}
                          {(contrato.n_concorrentes ?? 1) === 0 && <Chip tone="blue">sem concorrentes</Chip>}
                          {(contrato.dias_publicacao ?? 0) > 180 && <Chip tone="violet">publicação tardia</Chip>}
                        </div>
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">{contrato.procedimento ?? "—"}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {/* ------------------------------------------------ resultados por área (IQ OS) */}
      {ambito !== "contratos" && grupos.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-2">
          {grupos.map((grupo) => (
            <SectionCard
              key={grupo.scope}
              icon={grupo.scope === "news" ? Newspaper : grupo.scope === "scraped" ? Users : Building2}
              title={grupo.label}
              subtitle={`${formatNumber(grupo.total)} resultado(s) · ${grupo.took_ms} ms`}
            >
              {grupo.error ? (
                <EmptyState tone="warn">{grupo.error}</EmptyState>
              ) : grupo.items.length === 0 ? (
                <EmptyState>Sem resultados nesta área.</EmptyState>
              ) : (
                <ul className="space-y-2">
                  {grupo.items.map((item) => (
                    <li key={`${grupo.scope}-${item.id}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                      <p className="text-sm font-medium">{item.title || item.id}</p>
                      {item.subtitle && <p className="text-[11px] text-muted-foreground">{item.subtitle}</p>}
                      {item.snippet && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.snippet}</p>}
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        {(item.badges ?? []).slice(0, 4).map((etiqueta) => (
                          <Chip key={etiqueta}>{etiqueta}</Chip>
                        ))}
                        {item.date && <span className="text-[10px] text-muted-foreground">{formatDate(item.date)}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          ))}
        </div>
      )}

      {/* ------------------------------------------------------------ por ano */}
      {ambito === "contratos" && !resultado && porAno.length > 0 && (
        <SectionCard
          icon={CalendarRange}
          title="Ano a ano, no universo inteiro"
          subtitle="Cada linha é uma agregação sobre todos os contratos do ano (não uma amostra). Clique no ano para ver os contratos."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
              <thead>
                <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">Ano</th>
                  <th className="py-2 pr-3 text-right">Contratos</th>
                  <th className="py-2 pr-3 text-right">Valor</th>
                  <th className="py-2 pr-3 text-right">Mediana</th>
                  <th className="py-2 pr-3 text-right">Máximo</th>
                  <th className="py-2 pr-3 text-right">Ajuste direto</th>
                  <th className="py-2 pr-3 text-right">Aditivos</th>
                  <th className="py-2 pr-3 text-right">Sem concorrentes</th>
                  <th className="py-2 text-right">Ação</th>
                </tr>
              </thead>
              <tbody>
                {porAno.map((linha) => (
                  <tr key={linha.ano} className="border-t border-white/5">
                    <td className="whitespace-nowrap py-2 pr-3 font-mono text-xs">{linha.ano}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">{formatNumber(linha.contratos)}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">{formatCompactEuro(linha.valor)}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">{formatCompactEuro(linha.valor_mediano)}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right text-muted-foreground">{formatCompactEuro(linha.valor_maximo)}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">
                      {formatPct(linha.ajuste_direto?.taxa)}
                      <div className="text-[10px] text-muted-foreground">{formatNumber(linha.ajuste_direto?.contratos)} contratos</div>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">
                      {formatNumber(linha.aditivos)}
                      <div className="text-[10px] text-muted-foreground">{formatCompactEuro(linha.valor_aditivos)}</div>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">
                      {formatPct(linha.taxa_sem_concorrentes)}
                      <div className="text-[10px] text-muted-foreground">{formatNumber(linha.sem_concorrentes)} contratos</div>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => abrirContratosDoAno(linha.ano)}
                        className="rounded-lg border border-white/10 px-2 py-1 text-[11px] transition hover:bg-white/5"
                      >
                        ver contratos
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {/* ---------------------------------------------------------------- topos */}
      {ambito === "contratos" && (topCpv.length > 0 || topAdjudicatarias.length > 0 || procedimentos.length > 0) && (
        <div className="grid gap-5 xl:grid-cols-2">
          <SectionCard
            icon={Layers}
            title="Top CPV"
            subtitle={resultado ? "Nos contratos filtrados." : "Somado dos topos de cada ano (aproximação declarada)."}
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] border-collapse text-left text-sm">
                <thead>
                  <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">CPV</th>
                    <th className="py-2 pr-3 text-right">Contratos</th>
                    <th className="py-2 text-right">Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {topCpv.slice(0, 15).map((linha) => (
                    <tr key={linha.cpv} className="border-t border-white/5">
                      <td className="whitespace-nowrap py-2 pr-3 font-mono text-xs">{linha.cpv}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.contratos)}</td>
                      <td className="whitespace-nowrap py-2 text-right text-xs">{formatCompactEuro(linha.valor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard
            icon={Building2}
            title="Top adjudicatárias"
            subtitle={resultado ? "Nos contratos filtrados." : "Somado dos topos de cada ano."}
          >
            <div className="max-h-[420px] overflow-y-auto pr-1">
              <table className="w-full min-w-[420px] border-collapse text-left text-sm">
                <thead>
                  <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Empresa</th>
                    <th className="py-2 pr-3 text-right">Contratos</th>
                    <th className="py-2 text-right">Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {topAdjudicatarias.slice(0, 15).map((linha) => (
                    <tr key={`${linha.nif}`} className="border-t border-white/5">
                      <td className="w-[240px] py-2 pr-3 text-xs">
                        {linha.nif && onDossie ? (
                          <button
                            onClick={() => onDossie(linha.nif)}
                            className="block max-w-[230px] truncate text-left text-teal-200 transition hover:text-teal-100"
                            title="Abrir dossiê"
                          >
                            {linha.nome ?? linha.nif}
                          </button>
                        ) : (
                          <span className="block max-w-[230px] truncate">{linha.nome ?? linha.nif ?? "—"}</span>
                        )}
                        <div className="font-mono text-[10px] text-muted-foreground">{linha.nif}</div>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.contratos)}</td>
                      <td className="whitespace-nowrap py-2 text-right text-xs">{formatCompactEuro(linha.valor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {procedimentos.length > 0 && (
            <SectionCard icon={Percent} title="Procedimentos" subtitle="Como o universo (ou o filtro) reparte os contratos por tipo de procedimento." className="xl:col-span-2">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Procedimento</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 text-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {procedimentos.slice(0, 15).map((linha) => (
                      <tr key={linha.procedimento} className="border-t border-white/5">
                        <td className="py-2 pr-3 text-xs">{linha.procedimento}</td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.contratos)}</td>
                        <td className="whitespace-nowrap py-2 text-right text-xs">{formatCompactEuro(linha.valor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          )}

          {topAdjudicantes.length > 0 && (
            <SectionCard icon={Building2} title="Top adjudicantes (compradores)" subtitle="Nos contratos filtrados." className="xl:col-span-2">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Comprador</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 text-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topAdjudicantes.slice(0, 15).map((linha) => (
                      <tr key={`${linha.nif}`} className="border-t border-white/5">
                        <td className="py-2 pr-3 text-xs">
                          <span className="block max-w-[420px] truncate">{linha.nome ?? linha.nif ?? "—"}</span>
                          <span className="font-mono text-[10px] text-muted-foreground">{linha.nif}</span>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.contratos)}</td>
                        <td className="whitespace-nowrap py-2 text-right text-xs">{formatCompactEuro(linha.valor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          )}
        </div>
      )}
    </div>
  );
}

export default PadroesGlobal;
