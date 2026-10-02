/**
 * **Recolha Societária** — recolha massiva de dados societários (MJ) para JSON e
 * indexação no Elasticsearch.
 *
 * O módulo responde a duas perguntas:
 *
 * 1. **Que empresas recolher?** — pelos **anos dos contratos** (faceta de anos do
 *    índice de contratos), por **empresa** (firma ou NIF), pelo lado do contrato
 *    (adjudicatário/adjudicante), volume mínimo de contratos/valor e pelo que
 *    ainda não está indexado;
 * 2. **O que já foi recolhido?** — um ficheiro `societario-<NIF>.json` por
 *    entidade, com o total de publicações e a data; a indexação em
 *    `finance_publicacoes_mj` (e no PessoasIQ) é uma passagem separada,
 *    idempotente e pode ser feita só para o que falta.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CalendarRange,
  Database,
  Download,
  FileJson,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";

import {
  apagarRecolhaFicheiro,
  getRecolhaAlvos,
  getRecolhaAnos,
  getRecolhaEmpresa,
  getRecolhaEmpresas,
  getRecolhaExportacoes,
  getRecolhaFicheiro,
  getRecolhaJob,
  getRecolhaJobs,
  getRecolhaMeta,
  ingerirRecolhaExportacoes,
  obterDadosEmpresa,
  startRecolhaJob,
} from "../societarioRecolhaApi";
import type {
  RecolhaAlvo,
  RecolhaAlvos,
  RecolhaAnos,
  RecolhaEmpresaFicha,
  RecolhaEmpresaItem,
  RecolhaExportacoes,
  RecolhaFicheiro,
  RecolhaFicheiroConteudo,
  RecolhaIngestao,
  RecolhaJob,
  RecolhaMeta,
  RecolhaPapel,
} from "../societarioRecolhaApi";
import {
  Chip,
  EmptyState,
  FilterField,
  Kpi,
  Loading,
  SearchInput,
  SectionCard,
  formatCompactEuro,
  formatDate,
  formatNumber,
} from "../components/padroes/padroesKit";

type Tab = "alvos" | "ficheiros";

const TABS: { id: Tab; label: string }[] = [
  { id: "alvos", label: "Alvos e recolha" },
  { id: "ficheiros", label: "Ficheiros JSON e indexação" },
];

const PAPEIS: { id: RecolhaPapel; label: string }[] = [
  { id: "ambos", label: "Adjudicatário ou adjudicante" },
  { id: "adjudicatario", label: "Só adjudicatários (empresas que ganham contratos)" },
  { id: "adjudicante", label: "Só adjudicantes (quem contrata)" },
];

function tamanho(bytes?: number | null): string {
  if (!bytes) return "—";
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} kB`;
  return `${bytes} B`;
}

function ProgressoRecolha({ job }: { job: RecolhaJob }) {
  const progresso = job.progress || {};
  const total = progresso.entities_total || 0;
  const feitas = progresso.entities_done || 0;
  const pct = total ? Math.round((feitas / total) * 100) : job.status === "running" ? 3 : 100;
  const erros = job.result?.errors || [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <Chip tone={job.status === "running" ? "amber" : job.status === "error" ? "rose" : "teal"}>
          {job.status === "running" ? "a correr" : job.status === "error" ? "com erro" : "concluído"}
        </Chip>
        <span>{progresso.phase || "—"}</span>
        <span>
          {formatNumber(feitas)} / {formatNumber(total)} entidades
        </span>
        <span>{formatNumber(progresso.publications || 0)} publicações</span>
        <span>{formatNumber(progresso.files || 0)} ficheiros</span>
        {progresso.current && (
          <span className="truncate">
            agora: {progresso.current.name || progresso.current.nif}
          </span>
        )}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${job.status === "error" ? "from-rose-400 to-rose-600" : "from-teal-300 to-teal-500"}`}
          style={{ width: `${Math.max(3, Math.min(100, pct))}%` }}
        />
      </div>
      {job.error && <EmptyState tone="warn">{job.error}</EmptyState>}
      {job.result?.message && <EmptyState>{job.result.message}</EmptyState>}
      {job.result && !job.result.message && (
        <>
          <p className="text-xs text-muted-foreground">
            {formatNumber(job.result.entities_with_publications || 0)} entidades com publicações ·{" "}
            {formatNumber(job.result.publications || 0)} publicações gravadas em{" "}
            <span className="font-mono">{job.result.export_dir}</span>
            {job.result.ingested ? " · indexadas no Elasticsearch" : " · só exportadas (sem indexar)"}
          </p>
          {(job.result.rate_limited || 0) > 0 && (
            <EmptyState tone="warn">
              {formatNumber(job.result.rate_limited)} entidade(s) ficaram por recolher porque o portal do Ministério da
              Justiça limitou os pedidos. Aumente o ritmo (segundos entre pedidos) e a pausa, e volte a tentar mais tarde.
            </EmptyState>
          )}
        </>
      )}
      {erros.length > 0 && (
        <details className="rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <summary className="cursor-pointer">
            {erros.length} erro(s) na recolha (mostrar)
          </summary>
          <ul className="mt-2 space-y-1">
            {erros.slice(0, 20).map((erro, idx) => (
              <li key={`${erro.nif}-${idx}`}>
                {erro.nif} {erro.name ? `· ${erro.name}` : ""} — {erro.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function SocietarioRecolhaPage() {
  const [tab, setTab] = useState<Tab>("alvos");

  const [meta, setMeta] = useState<RecolhaMeta | null>(null);
  const [anos, setAnos] = useState<RecolhaAnos | null>(null);
  const [erroGeral, setErroGeral] = useState<string | null>(null);

  // Filtros dos alvos
  const [anoIni, setAnoIni] = useState<number | "">("");
  const [anoFim, setAnoFim] = useState<number | "">("");
  const [papel, setPapel] = useState<RecolhaPapel>("ambos");
  const [empresa, setEmpresa] = useState("");
  const [minContratos, setMinContratos] = useState<number | "">(1);
  const [minValor, setMinValor] = useState<number | "">("");
  const [excluirRecolhidas, setExcluirRecolhidas] = useState(true);

  const [alvos, setAlvos] = useState<RecolhaAlvo[] | null>(null);
  const [alvosInfo, setAlvosInfo] = useState<RecolhaAlvos | null>(null);
  const [aCarregarAlvos, setACarregarAlvos] = useState(false);
  const [selecionados, setSelecionados] = useState<string[]>([]);

  // Opções do trabalho
  const [maxEntidades, setMaxEntidades] = useState<number | "">(25);
  const [comDetalhe, setComDetalhe] = useState(true);
  const [maxPaginas, setMaxPaginas] = useState<number | "">(50);
  const [indexarLogo, setIndexarLogo] = useState(true);
  const [intervalo, setIntervalo] = useState<number | "">(4);
  const [pausaLimite, setPausaLimite] = useState<number | "">(90);

  const [job, setJob] = useState<RecolhaJob | null>(null);
  const [aArrancar, setAArrancar] = useState(false);

  // Ficheiros exportados
  const [exportacoes, setExportacoes] = useState<RecolhaExportacoes | null>(null);
  const [aIndexar, setAIndexar] = useState(false);
  const [resultadoIndexacao, setResultadoIndexacao] = useState<RecolhaIngestao | null>(null);
  const [erroFicheiros, setErroFicheiros] = useState<string | null>(null);
  const [preview, setPreview] = useState<RecolhaFicheiroConteudo | null>(null);

  // Pesquisar empresa → obter dados societários → ver os dados
  const [buscaEmpresa, setBuscaEmpresa] = useState("");
  const [sugestoesEmpresa, setSugestoesEmpresa] = useState<RecolhaEmpresaItem[]>([]);
  const [fichaEmpresa, setFichaEmpresa] = useState<RecolhaEmpresaFicha | null>(null);
  const [aCarregarFicha, setACarregarFicha] = useState(false);
  const [aObterDados, setAObterDados] = useState(false);
  const [mostrarDados, setMostrarDados] = useState(true);
  const [erroEmpresa, setErroEmpresa] = useState<string | null>(null);
  const [mensagemEmpresa, setMensagemEmpresa] = useState<string | null>(null);

  const carregarExportacoes = useCallback(async () => {
    try {
      setExportacoes(await getRecolhaExportacoes());
      setErroFicheiros(null);
    } catch (exc) {
      setErroFicheiros(exc instanceof Error ? exc.message : "Erro ao listar os ficheiros exportados");
    }
  }, []);

  /**
   * Recarrega a ficha de empresa (o que existe e os dados). Com `silent` não
   * alterna o estado «a carregar» — serve para refrescar durante a recolha sem
   * fazer piscar a tabela.
   */
  const recarregarFicha = useCallback(async (nif: string, opts?: { silent?: boolean }) => {
    const silencioso = opts?.silent === true;
    if (!silencioso) {
      setACarregarFicha(true);
      setErroEmpresa(null);
    }
    try {
      setFichaEmpresa(await getRecolhaEmpresa(nif, 20));
    } catch (exc) {
      if (!silencioso) {
        setErroEmpresa(exc instanceof Error ? exc.message : "Erro ao obter a ficha da empresa");
        setFichaEmpresa(null);
      }
    } finally {
      if (!silencioso) setACarregarFicha(false);
    }
  }, []);

  const carregarAlvos = useCallback(async () => {
    setACarregarAlvos(true);
    try {
      const res = await getRecolhaAlvos({
        ano_ini: typeof anoIni === "number" ? anoIni : null,
        ano_fim: typeof anoFim === "number" ? anoFim : null,
        papel,
        q: empresa.trim() || undefined,
        min_contracts: typeof minContratos === "number" ? minContratos : undefined,
        min_value: typeof minValor === "number" ? minValor : undefined,
        exclude_collected: excluirRecolhidas,
        limit: 60,
      });
      setAlvos(res.items);
      setAlvosInfo(res);
      setErroGeral(null);
    } catch (exc) {
      setErroGeral(exc instanceof Error ? exc.message : "Erro ao listar os alvos");
      setAlvos([]);
      setAlvosInfo(null);
    } finally {
      setACarregarAlvos(false);
    }
  }, [anoFim, anoIni, empresa, excluirRecolhidas, minContratos, minValor, papel]);

  // Arranque: metadados, anos dos contratos, ficheiros e primeiros alvos.
  useEffect(() => {
    let cancelado = false;
    Promise.all([
      getRecolhaMeta().catch(() => null),
      getRecolhaAnos().catch(() => null),
    ]).then(([metaRes, anosRes]) => {
      if (cancelado) return;
      setMeta(metaRes);
      setAnos(anosRes);
      if (anosRes?.max) {
        setAnoIni((atual) => (atual === "" ? anosRes.max! : atual));
        setAnoFim((atual) => (atual === "" ? anosRes.max! : atual));
      }
    });
    void carregarExportacoes();
    return () => {
      cancelado = true;
    };
  }, [carregarExportacoes]);

  // Primeira pesquisa de alvos quando os anos chegam.
  useEffect(() => {
    if (anos && alvos === null && !aCarregarAlvos) void carregarAlvos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anos]);

  // A recolha corre no servidor: ao abrir a página, retomar o trabalho mais recente.
  useEffect(() => {
    let cancelado = false;
    getRecolhaJobs()
      .then((res) => {
        if (cancelado || !res.items.length) return;
        setJob((atual) => atual ?? res.items[0]);
      })
      .catch(() => undefined);
    return () => {
      cancelado = true;
    };
  }, []);

  // Seguimento do trabalho de recolha, com atualização progressiva do que já
  // ficou guardado (JSON/índice) enquanto o trabalho corre.
  useEffect(() => {
    const jobId = job?.job_id;
    if (!jobId || job?.status !== "running") return;
    let cancelado = false;
    const temporizador = window.setTimeout(async () => {
      try {
        const atual = await getRecolhaJob(jobId);
        if (cancelado) return;
        setJob(atual);
        // Mostra já o que ficou guardado, sem esperar pelo fim do trabalho.
        void carregarExportacoes();
        if (fichaEmpresa) void recarregarFicha(fichaEmpresa.nif, { silent: true });
        if (atual.status !== "running") {
          if (empresa.trim() || excluirRecolhidas) void carregarAlvos();
          if (fichaEmpresa) {
            void recarregarFicha(fichaEmpresa.nif);
            setMensagemEmpresa(
              atual.status === "error"
                ? atual.error || "A recolha terminou com erro."
                : `Recolha concluída: ${formatNumber(atual.result?.publications ?? 0)} publicação(ões) guardadas${atual.result?.ingested ? " e indexadas" : ""}.`,
            );
          }
        }
      } catch {
        /* mantém o último estado conhecido */
      }
    }, 2500);
    return () => {
      cancelado = true;
      window.clearTimeout(temporizador);
    };
  }, [job, carregarAlvos, carregarExportacoes, empresa, excluirRecolhidas, fichaEmpresa, recarregarFicha]);

  const arrancar = useCallback(
    async (nifs: string[] | undefined) => {
      setAArrancar(true);
      setErroGeral(null);
      try {
        const res = await startRecolhaJob({
          ano_ini: nifs ? null : typeof anoIni === "number" ? anoIni : null,
          ano_fim: nifs ? null : typeof anoFim === "number" ? anoFim : null,
          papel,
          q: nifs ? undefined : empresa.trim() || undefined,
          nifs: nifs && nifs.length > 0 ? nifs : undefined,
          min_contracts: typeof minContratos === "number" ? minContratos : 1,
          min_value: typeof minValor === "number" ? minValor : null,
          exclude_collected: nifs ? false : excluirRecolhidas,
          max_entities: typeof maxEntidades === "number" ? maxEntidades : 25,
          with_details: comDetalhe,
          max_pages: typeof maxPaginas === "number" ? maxPaginas : 50,
          min_interval: typeof intervalo === "number" ? intervalo : 4,
          rate_limit_pause: typeof pausaLimite === "number" ? pausaLimite : 90,
          ingest: indexarLogo,
        });
        setJob(res);
        if (res.already_running) setErroGeral(res.message || "Já existe uma recolha a correr.");
      } catch (exc) {
        setErroGeral(exc instanceof Error ? exc.message : "Erro ao arrancar a recolha");
      } finally {
        setAArrancar(false);
      }
    },
    [anoFim, anoIni, comDetalhe, empresa, excluirRecolhidas, indexarLogo, intervalo, maxEntidades, maxPaginas, minContratos, minValor, papel, pausaLimite],
  );

  const indexar = useCallback(
    async (nifs: string[] | undefined, soFaltantes: boolean) => {
      setAIndexar(true);
      setErroFicheiros(null);
      try {
        const res = await ingerirRecolhaExportacoes({ nifs, with_people: true, only_missing: soFaltantes });
        setResultadoIndexacao(res);
        await carregarExportacoes();
      } catch (exc) {
        setErroFicheiros(exc instanceof Error ? exc.message : "Erro ao indexar os ficheiros");
      } finally {
        setAIndexar(false);
      }
    },
    [carregarExportacoes],
  );

  const apagar = useCallback(
    async (nif: string) => {
      try {
        await apagarRecolhaFicheiro(nif);
        if (preview?.nif === nif) setPreview(null);
        await carregarExportacoes();
      } catch (exc) {
        setErroFicheiros(exc instanceof Error ? exc.message : "Erro ao apagar o ficheiro");
      }
    },
    [carregarExportacoes, preview],
  );

  /** Abre a ficha de uma empresa (a partir da pesquisa ou dos alvos). */
  const abrirEmpresa = useCallback(
    async (nif: string, nome?: string | null) => {
      setSugestoesEmpresa([]);
      setBuscaEmpresa(nome ? `${nome} · ${nif}` : nif);
      setMostrarDados(true);
      await recarregarFicha(nif);
    },
    [recarregarFicha],
  );

  /** Recolhe os dados societários da empresa em foco (trabalho em segundo plano). */
  const obterDados = useCallback(async () => {
    const nif = fichaEmpresa?.nif;
    if (!nif) return;
    setAObterDados(true);
    setErroEmpresa(null);
    setMensagemEmpresa(null);
    try {
      const res = await obterDadosEmpresa(nif, {
        with_details: comDetalhe,
        max_pages: typeof maxPaginas === "number" ? maxPaginas : 50,
        min_interval: typeof intervalo === "number" ? intervalo : 4,
        rate_limit_pause: typeof pausaLimite === "number" ? pausaLimite : 90,
        ingest: indexarLogo,
      });
      setJob(res);
      setMensagemEmpresa(
        res.already_running
          ? res.message ||
              "Já existe uma recolha a correr — esta ficha vai sendo atualizada à medida que os dados são guardados."
          : `Recolha iniciada para ${fichaEmpresa?.name || nif}. Os dados vão aparecendo aqui à medida que forem guardados.`,
      );
    } catch (exc) {
      setErroEmpresa(exc instanceof Error ? exc.message : "Erro ao arrancar a recolha da empresa");
    } finally {
      setAObterDados(false);
    }
  }, [comDetalhe, fichaEmpresa, indexarLogo, intervalo, maxPaginas, pausaLimite]);

  // Sugestões enquanto se escreve (firma ou NIF).
  useEffect(() => {
    const termo = buscaEmpresa.trim();
    if (termo.length < 2) {
      setSugestoesEmpresa([]);
      return;
    }
    const controller = new AbortController();
    const temporizador = window.setTimeout(() => {
      getRecolhaEmpresas(termo, 8)
        .then((res) => {
          if (!controller.signal.aborted) setSugestoesEmpresa(res.items || []);
        })
        .catch(() => {
          if (!controller.signal.aborted) setSugestoesEmpresa([]);
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(temporizador);
    };
  }, [buscaEmpresa]);

  /** Empresa escolhida na lista de sugestões. */
  const escolherEmpresa = (item: RecolhaEmpresaItem) => {
    void abrirEmpresa(item.nif, item.name);
  };

  const todosSelecionados = useMemo(
    () => Boolean(alvos?.length) && selecionados.length === alvos!.length,
    [alvos, selecionados.length],
  );

  const alternarTodos = () => {
    if (todosSelecionados) setSelecionados([]);
    else setSelecionados((alvos || []).map((alvo) => alvo.nif));
  };

  const alternarUm = (nif: string) => {
    setSelecionados((atual) => (atual.includes(nif) ? atual.filter((item) => item !== nif) : [...atual, nif]));
  };

  const totalPublicacoesAlvos = useMemo(
    () => (alvos || []).reduce((soma, alvo) => soma + (alvo.publications_count || 0), 0),
    [alvos],
  );

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4 p-3 lg:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Database size={22} className="text-teal-300" />
            Recolha Societária
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Recolha massiva de publicações de atos societários (Ministério da Justiça) para ficheiros JSON e
            indexação em <span className="font-mono">{meta?.index || "finance_publicacoes_mj"}</span>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              aria-pressed={tab === item.id}
              className={[
                "min-h-[40px] rounded-xl px-3 py-2 text-xs transition",
                tab === item.id ? "glass-card text-teal-200 ring-1 ring-teal-400/30" : "text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {item.label}
            </button>
          ))}
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          icon={CalendarRange}
          label="Anos de contratos"
          value={anos ? `${anos.min ?? "—"}–${anos.max ?? "—"}` : "…"}
          sub={anos ? `${formatNumber(anos.years.length)} anos com contratos` : undefined}
        />
        <Kpi
          icon={Building2}
          label="Alvos listados"
          value={formatNumber(alvos?.length ?? 0)}
          sub={alvos ? `${formatNumber(totalPublicacoesAlvos)} publicações já indexadas nestes alvos` : undefined}
          color="text-sky-300"
          glow="glow-blue"
        />
        <Kpi
          icon={FileJson}
          label="Ficheiros JSON"
          value={formatNumber(exportacoes?.total ?? meta?.files ?? 0)}
          sub={exportacoes ? `${formatNumber(exportacoes.publications)} publicações · ${tamanho(exportacoes.bytes)}` : undefined}
          color="text-amber-300"
          glow="glow-amber"
        />
        <Kpi
          icon={FolderOpen}
          label="Pasta de exportação"
          value={exportacoes?.dir ? exportacoes.dir.split(/[\\/]/).slice(-2).join("/") : "…"}
          sub={meta?.export_dir_env ? `configurável por ${meta.export_dir_env}` : undefined}
          color="text-rose-300"
          glow="glow-rose"
        />
      </div>

      {erroGeral && <EmptyState tone="warn">{erroGeral}</EmptyState>}

      {tab === "alvos" && (
        <>
          <SectionCard
            title="Pesquisar empresa"
            subtitle="Procure pela firma ou NIF: se já houver dados societários vê-os aqui; se não, recolha-os agora."
            icon={Building2}
          >
            <div className="relative">
              <SearchInput value={buscaEmpresa} onChange={setBuscaEmpresa} placeholder="Ex.: JAJA, 503106542, MONTEPIO…" />
              {sugestoesEmpresa.length > 0 && (
                <div className="absolute z-30 mt-1 max-h-[320px] w-full overflow-y-auto rounded-xl border border-white/10 bg-[#140f13] p-1 shadow-xl">
                  {sugestoesEmpresa.map((item) => (
                    <button
                      key={item.nif}
                      type="button"
                      onClick={() => escolherEmpresa(item)}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition hover:bg-white/[0.06]"
                    >
                      <Building2 size={15} className="shrink-0 text-sky-300" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-foreground">{item.name || item.nif}</span>
                        <span className="block truncate text-muted-foreground">
                          NIF {item.nif} · {formatNumber(item.contracts_count)} contratos · {formatNumber(item.publications_count)} publicações
                        </span>
                      </span>
                      {(item.publications_count || 0) > 0 || item.exported ? (
                        <Chip tone="teal">{item.exported ? "JSON" : "no índice"}</Chip>
                      ) : (
                        <Chip tone="amber">por obter</Chip>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Escreva a firma ou o NIF e escolha a empresa na lista de sugestões. Também pode chegar aos dados pelos
              filtros dos alvos, abaixo.
            </p>
          </SectionCard>

          {(fichaEmpresa || aCarregarFicha || erroEmpresa) && (
            <SectionCard
              title={fichaEmpresa?.name || (fichaEmpresa ? `NIF ${fichaEmpresa.nif}` : "Empresa")}
              subtitle={
                fichaEmpresa
                  ? `NIF ${fichaEmpresa.nif}` +
                    (fichaEmpresa.exported
                      ? ` · JSON com ${formatNumber(fichaEmpresa.exported_total)} publicações (${formatDate(fichaEmpresa.exported_updated_at)})`
                      : " · sem ficheiro JSON") +
                    ` · ${formatNumber(fichaEmpresa.indexed_publications)} publicações no índice`
                  : undefined
              }
              icon={Building2}
              actions={
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void obterDados()}
                    disabled={aObterDados || !fichaEmpresa || job?.status === "running"}
                    title="Recolher agora os dados societários desta empresa (publicações do MJ) e gravar em JSON"
                    className="flex min-h-[40px] items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-40"
                  >
                    {aObterDados ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                    {fichaEmpresa?.has_data ? "Atualizar dados societários" : "Obter dados societários"}
                  </button>
                  {fichaEmpresa?.has_data && (
                    <button
                      type="button"
                      onClick={() => setMostrarDados((atual) => !atual)}
                      className="min-h-[40px] rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-muted-foreground transition hover:text-foreground"
                    >
                      {mostrarDados ? "Ocultar dados" : "Ver dados"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setFichaEmpresa(null);
                      setErroEmpresa(null);
                      setMensagemEmpresa(null);
                      setBuscaEmpresa("");
                    }}
                    className="min-h-[40px] rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-muted-foreground transition hover:text-foreground"
                  >
                    Fechar
                  </button>
                </div>
              }
            >
              {aCarregarFicha && <Loading label="A procurar dados societários desta empresa…" />}
              {erroEmpresa && <EmptyState tone="warn">{erroEmpresa}</EmptyState>}
              {mensagemEmpresa && (
                <EmptyState>
                  {job?.status === "running" && (
                    <Loader2 size={13} className="mr-1.5 inline animate-spin align-[-2px]" />
                  )}
                  {mensagemEmpresa}
                </EmptyState>
              )}
              {fichaEmpresa && !aCarregarFicha && (
                <>
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                    <Chip tone="blue">{formatNumber(fichaEmpresa.contracts_count)} contratos</Chip>
                    <Chip tone="violet">{formatCompactEuro(fichaEmpresa.total_value)}</Chip>
                    <Chip tone={fichaEmpresa.indexed_publications ? "teal" : "neutral"}>
                      {formatNumber(fichaEmpresa.indexed_publications)} no índice
                    </Chip>
                    <Chip tone={fichaEmpresa.exported ? "teal" : "neutral"}>
                      {fichaEmpresa.exported ? `JSON: ${formatNumber(fichaEmpresa.exported_total)}` : "sem ficheiro JSON"}
                    </Chip>
                    {fichaEmpresa.source === "index" && <Chip tone="amber">dados do índice (sem JSON)</Chip>}
                  </div>

                  {!fichaEmpresa.has_data && !job && (
                    <EmptyState>
                      Ainda não há dados societários desta empresa. Use «Obter dados societários» para recolher as
                      publicações de atos societários no portal do Ministério da Justiça.
                    </EmptyState>
                  )}
                  {!fichaEmpresa.has_data && job?.status === "running" && (
                    <EmptyState>Recolha em curso — os dados já guardados vão aparecendo aqui à medida que chegam.</EmptyState>
                  )}

                  {mostrarDados && fichaEmpresa.items.length > 0 && (
                    <div className="overflow-x-auto">
                      <p className="mb-2 text-xs text-muted-foreground">
                        {formatNumber(fichaEmpresa.items_total)} publicação(ões)
                        {fichaEmpresa.source === "export" ? " no ficheiro JSON" : " no índice"} · a mostrar{" "}
                        {fichaEmpresa.items.length}
                      </p>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                            <th className="py-2 pr-3">Data</th>
                            <th className="py-2 pr-3">Acto</th>
                            <th className="py-2 pr-3">Tipo</th>
                            <th className="py-2 pr-3">Entidade / Firma</th>
                            <th className="py-2 pr-3">Documento</th>
                          </tr>
                        </thead>
                        <tbody>
                          {fichaEmpresa.items.map((item, idx) => (
                            <tr key={item.pub_id || idx} className="border-b border-white/5">
                              <td className="py-2 pr-3 whitespace-nowrap">{item.data_publicacao || "—"}</td>
                              <td className="py-2 pr-3 max-w-md truncate" title={item.acto || ""}>
                                {item.acto || "—"}
                              </td>
                              <td className="py-2 pr-3">{item.tipo_label || "—"}</td>
                              <td className="py-2 pr-3 max-w-xs truncate">{item.firma || item.entidade || "—"}</td>
                              <td className="py-2 pr-3">
                                {item.documento_url ? (
                                  <a
                                    href={item.documento_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-teal-300 hover:underline"
                                  >
                                    Abrir
                                  </a>
                                ) : (
                                  "—"
                                )}
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
          )}

          <SectionCard
            title="Filtros dos alvos"
            subtitle="Escolha pelos anos dos contratos, pela empresa, pelo lado do contrato e pelo volume mínimo."
            icon={CalendarRange}
            actions={
              <button
                type="button"
                onClick={() => void carregarAlvos()}
                disabled={aCarregarAlvos}
                className="flex min-h-[40px] items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-50"
              >
                {aCarregarAlvos ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Procurar alvos
              </button>
            }
          >
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <FilterField label="Ano de contrato (de)">
                <input
                  type="number"
                  min={1900}
                  max={2100}
                  value={anoIni}
                  onChange={(evento) => setAnoIni(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Ano de contrato (até)">
                <input
                  type="number"
                  min={1900}
                  max={2100}
                  value={anoFim}
                  onChange={(evento) => setAnoFim(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Empresa (firma ou NIF)">
                <SearchInput value={empresa} onChange={setEmpresa} placeholder="Ex.: JAJA, 503106542, hospital…" />
              </FilterField>
              <FilterField label="Lado do contrato">
                <select
                  value={papel}
                  onChange={(evento) => setPapel(evento.target.value as RecolhaPapel)}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                >
                  {PAPEIS.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Mínimo de contratos">
                <input
                  type="number"
                  min={1}
                  value={minContratos}
                  onChange={(evento) => setMinContratos(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Valor total mínimo (€)">
                <input
                  type="number"
                  min={0}
                  value={minValor}
                  onChange={(evento) => setMinValor(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Máx. entidades neste trabalho">
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={maxEntidades}
                  onChange={(evento) => setMaxEntidades(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Ritmo (segundos entre pedidos)">
                <input
                  type="number"
                  min={0}
                  max={60}
                  step={0.5}
                  value={intervalo}
                  onChange={(evento) => setIntervalo(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Páginas por entidade">
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={maxPaginas}
                  onChange={(evento) => setMaxPaginas(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
              <FilterField label="Pausa se o portal limitar (s)">
                <input
                  type="number"
                  min={0}
                  max={600}
                  step={10}
                  value={pausaLimite}
                  onChange={(evento) => setPausaLimite(evento.target.value === "" ? "" : Number(evento.target.value))}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-foreground outline-none"
                />
              </FilterField>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              <label className="flex items-center gap-2 text-muted-foreground">
                <input
                  type="checkbox"
                  checked={excluirRecolhidas}
                  onChange={(evento) => setExcluirRecolhidas(evento.target.checked)}
                />
                Só quem ainda não tem publicações indexadas
              </label>
              <label className="flex items-center gap-2 text-muted-foreground">
                <input type="checkbox" checked={comDetalhe} onChange={(evento) => setComDetalhe(evento.target.checked)} />
                Abrir o detalhe de cada publicação (dados societários completos)
              </label>
              <label className="flex items-center gap-2 text-muted-foreground">
                <input type="checkbox" checked={indexarLogo} onChange={(evento) => setIndexarLogo(evento.target.checked)} />
                Indexar logo no Elasticsearch (além de gravar o JSON)
              </label>
            </div>

            {anos && anos.years.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Anos com mais contratos:</span>
                {anos.years.slice(0, 12).map((ano) => (
                  <button
                    key={ano.year}
                    type="button"
                    onClick={() => {
                      setAnoIni(ano.year);
                      setAnoFim(ano.year);
                    }}
                    title={`${formatNumber(ano.contracts)} contratos em ${ano.year}`}
                    className={[
                      "rounded-full border px-2 py-0.5 text-[11px] transition",
                      anoIni === ano.year && anoFim === ano.year
                        ? "border-teal-400/40 bg-teal-400/15 text-teal-200"
                        : "border-white/10 bg-white/5 text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    {ano.year}
                  </button>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Alvos da recolha"
            subtitle="Marque as empresas a recolher ou recolha por filtros. O JSON é gravado por entidade."
            icon={Building2}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={alternarTodos}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  {todosSelecionados ? "Limpar seleção" : "Selecionar visíveis"}
                </button>
                <button
                  type="button"
                  onClick={() => void arrancar(selecionados)}
                  disabled={aArrancar || selecionados.length === 0 || job?.status === "running"}
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
                >
                  {aArrancar ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                  Recolher selecionadas ({selecionados.length})
                </button>
                <button
                  type="button"
                  onClick={() => void arrancar(undefined)}
                  disabled={aArrancar || job?.status === "running"}
                  title="Recolhe pelos filtros, até ao máximo de entidades indicado"
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-40"
                >
                  <Download size={14} />
                  Recolher por filtros
                </button>
              </div>
            }
          >
            {aCarregarAlvos && <Loading label="A procurar as empresas com contratos…" />}
            {!aCarregarAlvos && alvosInfo?.period_truncated && (
              <div className="mb-3">
                <EmptyState tone="warn">
                  O período tem mais empresas do que as {formatNumber(alvosInfo.period_size)} consideradas (ordenadas por
                  volume de contratos no período). Estreite o intervalo de anos, suba o mínimo de contratos ou procure
                  a empresa pela firma/NIF.
                </EmptyState>
              </div>
            )}
            {!aCarregarAlvos && alvos && alvos.length === 0 && (
              <EmptyState>
                Sem empresas para estes filtros. Experimente alargar o intervalo de anos, baixar o mínimo de
                contratos ou desmarcar «só quem ainda não tem publicações indexadas».
              </EmptyState>
            )}
            {!aCarregarAlvos && alvos && alvos.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="w-8 py-2" />
                      <th className="py-2 pr-3">Empresa</th>
                      <th className="py-2 pr-3 text-right">Contratos no período</th>
                      <th className="py-2 pr-3 text-right">Contratos (total)</th>
                      <th className="py-2 pr-3 text-right">Valor no período</th>
                      <th className="py-2 pr-3 text-right">Publicações</th>
                      <th className="py-2 pr-3">Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alvos.map((alvo) => (
                      <tr key={alvo.nif} className="border-b border-white/5 hover:bg-white/[0.03]">
                        <td className="py-2">
                          <input
                            type="checkbox"
                            checked={selecionados.includes(alvo.nif)}
                            onChange={() => alternarUm(alvo.nif)}
                            aria-label={`Selecionar ${alvo.name || alvo.nif}`}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <p className="truncate font-medium text-foreground">{alvo.name || alvo.nif}</p>
                          <p className="font-mono text-[11px] text-muted-foreground">NIF {alvo.nif}</p>
                        </td>
                        <td className="py-2 pr-3 text-right">{formatNumber(alvo.period_contracts)}</td>
                        <td className="py-2 pr-3 text-right text-muted-foreground">{formatNumber(alvo.contracts_count)}</td>
                        <td className="py-2 pr-3 text-right">{formatCompactEuro(alvo.period_value ?? alvo.total_value)}</td>
                        <td className="py-2 pr-3 text-right">{formatNumber(alvo.publications_count)}</td>
                        <td className="py-2 pr-3">
                          {alvo.publications_count > 0 ? (
                            <Chip tone="teal">no índice</Chip>
                          ) : (
                            <Chip tone="amber">por recolher</Chip>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {job && (
            <SectionCard
              title="Trabalho de recolha"
              subtitle={`Trabalho ${job.job_id} · iniciado em ${formatDate(job.started_at)}`}
              icon={Play}
            >
              <ProgressoRecolha job={job} />
            </SectionCard>
          )}
        </>
      )}

      {tab === "ficheiros" && (
        <>
          <SectionCard
            title="Ficheiros exportados"
            subtitle="Um JSON por entidade. A indexação é idempotente e pode ser feita só para o que falta."
            icon={FileJson}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void carregarExportacoes()}
                  className="min-h-[40px] rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  Atualizar
                </button>
                <button
                  type="button"
                  onClick={() => void indexar(undefined, true)}
                  disabled={aIndexar}
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
                >
                  {aIndexar ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
                  Indexar só o que falta
                </button>
                <button
                  type="button"
                  onClick={() => void indexar(undefined, false)}
                  disabled={aIndexar}
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-40"
                >
                  Indexar tudo
                </button>
              </div>
            }
          >
            {erroFicheiros && <EmptyState tone="warn">{erroFicheiros}</EmptyState>}
            {resultadoIndexacao && (
              <div className="mb-3 space-y-1 text-xs text-muted-foreground">
                <p>
                  Indexadas {formatNumber(resultadoIndexacao.entities)} de {formatNumber(resultadoIndexacao.requested)}{" "}
                  entidades · {formatNumber(resultadoIndexacao.indexed)} publicações ·{" "}
                  {formatNumber(resultadoIndexacao.people)} fichas de pessoas atualizadas.
                </p>
                {resultadoIndexacao.errors.length > 0 && (
                  <p className="text-amber-200">
                    {resultadoIndexacao.errors.length} erro(s): {resultadoIndexacao.errors[0].error}
                  </p>
                )}
              </div>
            )}
            {!exportacoes && <Loading label="A ler a pasta de exportação…" />}
            {exportacoes && exportacoes.items.length === 0 && (
              <EmptyState>
                Ainda não há ficheiros JSON. Faça uma recolha no separador «Alvos e recolha» — cada entidade fica
                com um ficheiro <span className="font-mono">societario-&lt;NIF&gt;.json</span>.
              </EmptyState>
            )}
            {exportacoes && exportacoes.items.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Entidade</th>
                      <th className="py-2 pr-3">Ficheiro</th>
                      <th className="py-2 pr-3 text-right">Publicações</th>
                      <th className="py-2 pr-3 text-right">Tamanho</th>
                      <th className="py-2 pr-3">Recolhido em</th>
                      <th className="py-2 pr-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {exportacoes.items.map((ficheiro: RecolhaFicheiro) => (
                      <tr key={ficheiro.nif} className="border-b border-white/5 hover:bg-white/[0.03]">
                        <td className="py-2 pr-3">
                          <p className="truncate font-medium text-foreground">{ficheiro.name || ficheiro.nif}</p>
                          <p className="font-mono text-[11px] text-muted-foreground">NIF {ficheiro.nif}</p>
                        </td>
                        <td className="py-2 pr-3 font-mono text-[11px] text-muted-foreground">{ficheiro.file}</td>
                        <td className="py-2 pr-3 text-right">{formatNumber(ficheiro.total)}</td>
                        <td className="py-2 pr-3 text-right text-muted-foreground">{tamanho(ficheiro.bytes)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{formatDate(ficheiro.updated_at || ficheiro.mtime)}</td>
                        <td className="py-2 pr-3">
                          <div className="flex flex-wrap items-center justify-end gap-1.5">
                            <button
                              type="button"
                              onClick={() => void getRecolhaFicheiro(ficheiro.nif, 20).then(setPreview)}
                              className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
                            >
                              Ver
                            </button>
                            <button
                              type="button"
                              onClick={() => void indexar([ficheiro.nif], false)}
                              disabled={aIndexar}
                              className="rounded-lg border border-teal-400/25 bg-teal-400/10 px-2 py-1 text-[11px] text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
                            >
                              Indexar
                            </button>
                            <button
                              type="button"
                              onClick={() => void apagar(ficheiro.nif)}
                              className="rounded-lg border border-rose-400/25 bg-rose-400/10 px-2 py-1 text-[11px] text-rose-200 transition hover:bg-rose-400/20"
                              aria-label={`Apagar ficheiro de ${ficheiro.nif}`}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {preview && (
            <SectionCard
              title={`Pré-visualização · ${preview.name || preview.nif}`}
              subtitle={`${formatNumber(preview.items_total ?? preview.total ?? preview.items.length)} publicações no ficheiro (a mostrar ${preview.items.length})`}
              icon={FileJson}
              actions={
                <button
                  type="button"
                  onClick={() => setPreview(null)}
                  className="min-h-[36px] rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  Fechar
                </button>
              }
            >
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Data</th>
                      <th className="py-2 pr-3">Acto</th>
                      <th className="py-2 pr-3">Tipo</th>
                      <th className="py-2 pr-3">Entidade / Firma</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.items.map((item, idx) => (
                      <tr key={item.pub_id || idx} className="border-b border-white/5">
                        <td className="py-2 pr-3 whitespace-nowrap">{item.data_publicacao || "—"}</td>
                        <td className="py-2 pr-3 max-w-md truncate" title={item.acto || ""}>
                          {item.acto || "—"}
                        </td>
                        <td className="py-2 pr-3">{item.tipo_label || "—"}</td>
                        <td className="py-2 pr-3 max-w-xs truncate">{item.firma || item.entidade || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          )}

          {meta && (
            <SectionCard title="Como funciona" icon={AlertTriangle}>
              <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                <li>
                  A pesquisa do portal do Ministério da Justiça exige reCAPTCHA: a resolução automática usa a
                  2captcha. A chave é gerida em <span className="font-mono">Administração → Chaves</span> (fica
                  guardada no Elasticsearch); sem chave lá, usa a variável{" "}
                  <span className="font-mono">TWOCAPTCHA_API_KEY</span> ou o <span className="font-mono">.env</span>.
                </li>
                <li>
                  Cada entidade gera <span className="font-mono">societario-&lt;NIF&gt;.json</span> em{" "}
                  <span className="font-mono">{meta.export_dir}</span>; recolhas repetidas juntam ao ficheiro sem
                  duplicar publicações.
                </li>
                <li>A indexação em {meta.index} é idempotente e alimenta também o PessoasIQ com as pessoas/cargos.</li>
                <li>{meta.notes}</li>
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
