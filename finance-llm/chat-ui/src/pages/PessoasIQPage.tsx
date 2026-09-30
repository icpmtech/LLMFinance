import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  Building2,
  Check,
  Copy,
  Database,
  ExternalLink,
  GitBranch,
  Globe,
  Image as ImageIcon,
  LayoutDashboard,
  Loader2,
  Network,
  PersonStanding,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Users,
  Video,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  API_BASE,
  autocompletePeople,
  collectPersonSocial,
  getCompanyCombinedGraph,
  getCompanyPeople,
  getCompanyPeopleGraph,
  getPeopleFilters,
  getPerson,
  getPerson360,
  getPersonGraph,
  ingestPeopleForCompany,
  ingestPeopleFromCire,
  searchPeople,
  searchPeopleCompanies,
} from "../api";
import {
  devedorPorNif,
  devedoresCollect,
  devedoresFontes,
  devedoresIngest,
  devedoresJob,
  devedoresMeta,
  devedoresPdfUrl,
  devedoresRecolhas,
  devedoresSearch,
  type DevedorFicha,
  type DevedorRegisto,
  type DevedoresFontes,
  type DevedoresJob,
  type DevedoresKpis,
  type DevedoresMeta,
  type DevedoresRecolha,
} from "../devedoresApi";
import type { CompanyPerson, PeopleCompaniesResponse, PeopleCompanyItem, PeopleCompanyResponse } from "../api";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import type { GraphMetric } from "../components/graph/graphStudio";
import { useWindowMode } from "../layout";
import { openWindow } from "../windows";
import {
  Card,
  EmptyState,
  Loading,
  MARKDOWN_COMPONENTS,
  NodeShapeLegend,
  NodeSummaryCard,
  PeoplePicker,
  SEARCH_PAGE_SIZE,
  SORT_LABELS,
  combinedToStudioGraph,
  formatDate,
  openGraphWindow,
  roleLabel,
  type EdgeKindFilter,
  type GraphMode,
  type GraphTarget,
  type NodeKindFilter,
  type PersonTypeFilter,
  type PeopleSort,
} from "../components/people/peopleKit";
import type {
  People360Response,
  PeopleAutocompleteItem,
  PeopleFiltersResponse,
  PeopleGraphResponse,
  PeopleIngestResponse,
  PeopleSearchResponse,
  PeopleSocialCollectResponse,
  PeopleSocialItem,
  PeopleSocialResponse,
  PeopleSocialSourceResult,
  PeopleStatusResponse,
  Person,
  PersonRisk,
  PersonRole,
} from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// `formatDate`, `roleLabel` e `combinedToStudioGraph` vivem em
// `components/people/peopleKit`, partilhados com a janela própria do grafo.
// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

// `Card`, `Loading` e `EmptyState` vivem em `components/people/peopleKit`.

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

type PessoasIQSection = "dashboard" | "search" | "graph" | "score360" | "devedores" | "settings";

const SECTIONS: { id: PessoasIQSection; label: string; icon: React.ElementType }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "search", label: "Pesquisa", icon: Search },
  { id: "graph", label: "Grafo", icon: Network },
  { id: "score360", label: "360", icon: ShieldAlert },
  { id: "devedores", label: "Devedores", icon: AlertTriangle },
  { id: "settings", label: "Configurações", icon: Settings },
];

// ---------------------------------------------------------------------------
// Devedores (listas públicas das Finanças e da Segurança Social)
// ---------------------------------------------------------------------------

const DEVEDORES_PAGE_SIZE = 25;

function dataCurta(valor?: string | null): string {
  if (!valor) return "—";
  return String(valor).slice(0, 10).split("-").reverse().join("/");
}

/** Aviso de dívida ao Estado (Finanças / Segurança Social) para um NIF/NIPC. */
function DebtBadge({ nif }: { nif: string }) {
  const [ficha, setFicha] = useState<DevedorFicha | null>(null);

  useEffect(() => {
    let vivo = true;
    setFicha(null);
    if (!nif) return () => undefined;
    devedorPorNif(nif)
      .then((resposta) => {
        if (vivo) setFicha(resposta);
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [nif]);

  if (!ficha || !ficha.devedor) return null;
  const porEntidade = ficha.items.reduce<Record<string, DevedorRegisto[]>>((acc, item) => {
    const chave = item.entidade_label || item.entidade;
    acc[chave] = [...(acc[chave] || []), item];
    return acc;
  }, {});

  return (
    <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-amber-200">
        <AlertTriangle size={15} /> Devedor ao Estado
      </p>
      {Object.entries(porEntidade).map(([entidade, registos]) => (
        <p key={entidade} className="mt-1.5 text-amber-100/90">
          <span className="font-medium">{entidade}</span>:{" "}
          {registos
            .map(
              (registo) =>
                `${registo.escalao} (${registo.tipo_label ?? registo.tipo}, lista de ${dataCurta(
                  registo.lista_atualizada_em,
                )}, recolhida em ${dataCurta(registo.collected_at)})`,
            )
            .join(" · ")}
        </p>
      ))}
    </div>
  );
}

/**
 * Ficha de um devedor que **não** tem ficha de pessoa/empresa no PessoasIQ.
 *
 * As listas de devedores são a única fonte de alguns NIF (não têm publicações
 * societárias nem contratos): em vez de «pessoa não encontrada», o PessoasIQ
 * mostra o que as listas publicam — escalão, entidade credora e datas.
 */
function DevedorFichaPanel({
  ficha,
  onClose,
  onOpenTab,
}: {
  ficha: DevedorFicha;
  onClose: () => void;
  onOpenTab: () => void;
}) {
  const [temFicha, setTemFicha] = useState<boolean | null>(null);

  useEffect(() => {
    let vivo = true;
    setTemFicha(null);
    getPerson(ficha.nif)
      .then(() => {
        if (vivo) setTemFicha(true);
      })
      .catch(() => {
        if (vivo) setTemFicha(false);
      });
    return () => {
      vivo = false;
    };
  }, [ficha.nif]);

  const nome = ficha.nome || `NIF ${ficha.nif}`;
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <Building2 size={22} className="shrink-0 text-amber-300" />
            {nome}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            NIF {ficha.nif} · {ficha.total} registo{ficha.total === 1 ? "" : "s"} nas listas de devedores
            {ficha.maior_valor_min ? ` · dívida a partir de ${ficha.maior_valor_min.toLocaleString("pt-PT")} €` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-white/10 p-1.5 text-muted-foreground transition hover:text-foreground"
          aria-label="Fechar"
        >
          <X size={16} />
        </button>
      </div>

      <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-amber-200">
          <AlertTriangle size={15} /> Devedor ao Estado
        </p>
        <ul className="mt-1.5 space-y-1 text-xs text-amber-100/90">
          {ficha.items.map((registo) => (
            <li key={registo.doc_id} className="flex flex-wrap items-center gap-x-2">
              <span className="font-medium">{registo.escalao}</span>
              <span className="text-muted-foreground">·</span>
              <span>{registo.entidade_label ?? registo.entidade}</span>
              <span className="text-muted-foreground">·</span>
              <span>{registo.tipo_label ?? registo.tipo}</span>
              <span className="text-muted-foreground">·</span>
              <span>
                lista de {dataCurta(registo.lista_atualizada_em)}, recolhida em {dataCurta(registo.collected_at)}
              </span>
              {registo.base && (
                <a
                  href={devedoresPdfUrl(registo.base)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-teal-300 hover:underline"
                >
                  <ExternalLink size={11} /> PDF
                </a>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onOpenTab}
          className="flex items-center gap-2 rounded-xl border border-amber-400/20 bg-amber-400/10 px-3 py-1.5 text-sm text-amber-200 transition hover:bg-amber-400/20"
        >
          <Search size={16} /> Pesquisar nas listas
        </button>
        {temFicha && (
          <span className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-muted-foreground">
            <Check size={14} className="text-emerald-300" /> Também tem ficha societária
          </span>
        )}
      </div>

      {temFicha === false && (
        <p className="text-xs text-muted-foreground">
          Este NIF não tem publicações societárias nem contratos indexados: os dados acima vêm das listas
          públicas de devedores (Finanças e Segurança Social).
        </p>
      )}
    </div>
  );
}

/** Cartão de indicadores das listas de devedores. */
function DevedoresKpiRow({ kpis }: { kpis: DevedoresKpis }) {
  const cartoes: { label: string; valor: string; detalhe?: string }[] = [
    { label: "Registos", valor: kpis.registos.toLocaleString("pt-PT"), detalhe: `${kpis.devedores_distintos.toLocaleString("pt-PT")} NIF distintos (aprox.)` },
    { label: "Singulares", valor: kpis.singulares.toLocaleString("pt-PT"), detalhe: "Pessoas" },
    { label: "Coletivos", valor: kpis.coletivos.toLocaleString("pt-PT"), detalhe: "Empresas" },
    { label: "Finanças", valor: kpis.financas.toLocaleString("pt-PT"), detalhe: `${kpis.ficheiros} ficheiros` },
    { label: "Segurança Social", valor: kpis.seguranca_social.toLocaleString("pt-PT"), detalhe: kpis.seguranca_social ? "Recolhida" : "Não recolhida" },
    { label: "Lista de", valor: dataCurta(kpis.ultima_lista), detalhe: `Recolha: ${dataCurta(kpis.ultima_recolha)}` },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 @2xl:grid-cols-3 @4xl:grid-cols-6">
      {cartoes.map((cartao) => (
        <div key={cartao.label} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{cartao.label}</p>
          <p className="mt-0.5 truncate text-lg font-semibold text-foreground">{cartao.valor}</p>
          {cartao.detalhe && <p className="truncate text-[11px] text-muted-foreground">{cartao.detalhe}</p>}
        </div>
      ))}
    </div>
  );
}

/**
 * Secção «Devedores» do PessoasIQ: área de pesquisa nas listas públicas de
 * devedores (Finanças e Segurança Social), com os ficheiros recolhidos (PDF +
 * JSON + data da recolha) e a recolha das listas a pedido.
 */
function DevedoresSection({ onPickNif }: { onPickNif: (nif: string) => void }) {
  const [meta, setMeta] = useState<DevedoresMeta | null>(null);
  const [fontes, setFontes] = useState<DevedoresFontes | null>(null);
  const [recolhas, setRecolhas] = useState<DevedoresRecolha[]>([]);
  const [kpis, setKpis] = useState<DevedoresKpis | null>(null);
  const [itens, setItens] = useState<DevedorRegisto[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aIndexar, setAIndexar] = useState(false);
  const [job, setJob] = useState<DevedoresJob | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<DevedorFicha | null>(null);
  const [detalheTemFicha, setDetalheTemFicha] = useState(false);
  const [aCarregarDetalhe, setACarregarDetalhe] = useState(false);

  const [q, setQ] = useState("");
  const [nif, setNif] = useState("");
  const [tipo, setTipo] = useState("");
  const [entidade, setEntidade] = useState("");
  const [escalao, setEscalao] = useState("");
  const [sort, setSort] = useState<"relevancia" | "nome" | "escalao" | "recolha" | "lista">("escalao");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const pesquisar = useCallback(
    async (pagina = 1) => {
      setCarregando(true);
      setErro(null);
      try {
        const resposta = await devedoresSearch({
          q: q.trim() || undefined,
          nif: nif.trim() || undefined,
          tipo: tipo || undefined,
          entidade: entidade || undefined,
          escalao: escalao ? [escalao] : undefined,
          sort,
          order,
          page: pagina,
          size: DEVEDORES_PAGE_SIZE,
        });
        if (resposta.error) setErro(resposta.error);
        setItens(resposta.items ?? []);
        setTotal(resposta.total ?? 0);
        setKpis(resposta.kpis ?? null);
        setPage(pagina);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro na pesquisa de devedores");
      } finally {
        setCarregando(false);
      }
    },
    [q, nif, tipo, entidade, escalao, sort, order],
  );

  const carregarContexto = useCallback(async () => {
    try {
      const [m, f, r] = await Promise.all([devedoresMeta(), devedoresFontes(), devedoresRecolhas()]);
      setMeta(m);
      setFontes(f);
      setRecolhas(r.items ?? []);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao carregar as fontes");
    }
  }, []);

  useEffect(() => {
    void carregarContexto();
    void pesquisar(1);
    // Só na entrada na secção: a pesquisa seguinte é sempre explícita.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Progresso da recolha (a recolha corre no servidor, em segundo plano).
  useEffect(() => {
    if (!jobId) return;
    let vivo = true;
    const timer = window.setInterval(async () => {
      try {
        const estado = await devedoresJob(jobId);
        if (!vivo) return;
        setJob(estado);
        if (estado.status !== "running") {
          window.clearInterval(timer);
          setJobId(null);
          await carregarContexto();
          await pesquisar(1);
        }
      } catch {
        /* o trabalho pode ter saído da lista; ignora-se */
      }
    }, 2500);
    return () => {
      vivo = false;
      window.clearInterval(timer);
    };
  }, [jobId, carregarContexto, pesquisar]);

  const recolher = async (payload: { ficheiros?: string[]; entidades?: ("financas" | "seguranca_social")[]; forcar?: boolean }) => {
    setErro(null);
    try {
      const resposta = await devedoresCollect({ entidades: payload.entidades ?? ["financas"], ...payload });
      setJob(resposta);
      if (resposta.already_running) {
        setJobId(resposta.job_id);
      } else {
        setJobId(resposta.job_id);
      }
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao arrancar a recolha");
    }
  };

  const indexar = async () => {
    setAIndexar(true);
    setErro(null);
    try {
      await devedoresIngest();
      await carregarContexto();
      await pesquisar(1);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro a indexar os ficheiros");
    } finally {
      setAIndexar(false);
    }
  };

  const paginas = Math.max(1, Math.ceil(total / DEVEDORES_PAGE_SIZE));

  /**
   * Detalhe de um devedor (todas as listas em que o NIF aparece).
   *
   * A ficha do PessoasIQ só existe quando há publicações societárias indexadas
   * para o NIF — um devedor pode muito bem não ter nenhuma. Por isso o detalhe
   * abre aqui e o botão para a ficha só aparece se essa ficha existir.
   */
  const abrirDetalhe = async (nifAlvo: string) => {
    setACarregarDetalhe(true);
    setDetalheTemFicha(false);
    setDetalhe(null);
    try {
      const ficha = await devedorPorNif(nifAlvo);
      setDetalhe(ficha);
      getPerson(nifAlvo)
        .then(() => setDetalheTemFicha(true))
        .catch(() => setDetalheTemFicha(false));
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao abrir o detalhe do devedor");
    } finally {
      setACarregarDetalhe(false);
    }
  };

  return (
    <div className="space-y-4">
      {kpis && <DevedoresKpiRow kpis={kpis} />}

      <Card>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <AlertTriangle size={16} className="text-amber-300" /> Listas públicas de devedores
            </h3>
            <p className="text-[11px] text-muted-foreground">
              {meta ? `${meta.recolhas} recolha(s) · ${meta.ficheiros} ficheiro(s) · ${meta.registos_recolhidos.toLocaleString("pt-PT")} registos guardados` : "a carregar…"}
            </p>
          </div>

          <div className="flex min-h-[44px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-amber-400/40">
            <Search size={18} className="shrink-0 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void pesquisar(1);
              }}
              placeholder="Nome do devedor…"
              autoComplete="off"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <input
              value={nif}
              onChange={(e) => setNif(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void pesquisar(1);
              }}
              placeholder="NIF/NIPC"
              inputMode="numeric"
              autoComplete="off"
              className="w-[110px] bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <button
              type="button"
              onClick={() => void pesquisar(1)}
              className="shrink-0 rounded-lg bg-amber-400/15 px-3 py-1.5 text-xs font-medium text-amber-200 transition hover:bg-amber-400/25"
            >
              Pesquisar
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value)}
              aria-label="Tipo de contribuinte"
              className="min-h-[40px] rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">Singulares e coletivos</option>
              <option value="singulares">Contribuintes singulares</option>
              <option value="coletivos">Contribuintes coletivos</option>
            </select>
            <select
              value={entidade}
              onChange={(e) => setEntidade(e.target.value)}
              aria-label="Entidade credora"
              className="min-h-[40px] rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">Finanças e Segurança Social</option>
              <option value="financas">Finanças</option>
              <option value="seguranca_social">Segurança Social</option>
            </select>
            <select
              value={escalao}
              onChange={(e) => setEscalao(e.target.value)}
              aria-label="Escalão da dívida"
              className="min-h-[40px] max-w-[260px] rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">Todos os escalões</option>
              {(fontes?.financas.ficheiros ?? [])
                .map((ficheiro) => ficheiro.escalao)
                .concat((fontes?.seguranca_social.escaloes ?? []).map((item) => item.escalao))
                .filter((valor, indice, lista) => lista.indexOf(valor) === indice)
                .map((valor) => (
                  <option key={valor} value={valor}>
                    {valor}
                  </option>
                ))}
            </select>
            <select
              value={`${sort}:${order}`}
              onChange={(e) => {
                const [novoSort, novaOrdem] = e.target.value.split(":") as [
                  "relevancia" | "nome" | "escalao" | "recolha" | "lista",
                  "asc" | "desc",
                ];
                setSort(novoSort);
                setOrder(novaOrdem);
              }}
              aria-label="Ordenação"
              className="min-h-[40px] rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground"
            >
              <option value="escalao:desc">Maior escalão primeiro</option>
              <option value="escalao:asc">Menor escalão primeiro</option>
              <option value="nome:asc">Nome (A→Z)</option>
              <option value="recolha:desc">Recolha mais recente</option>
              <option value="lista:desc">Lista mais recente</option>
            </select>
            <button
              type="button"
              onClick={() => {
                setQ("");
                setNif("");
                setTipo("");
                setEntidade("");
                setEscalao("");
                setSort("escalao");
                setOrder("desc");
                void pesquisar(1);
              }}
              className="min-h-[40px] rounded-lg border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              Limpar
            </button>
            {carregando && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
          </div>
        </div>
      </Card>

      {erro && (
        <Card className="border-rose-400/30 bg-rose-400/5 p-4">
          <p className="text-sm text-rose-300">{erro}</p>
        </Card>
      )}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            Resultados <span className="text-muted-foreground">({total.toLocaleString("pt-PT")})</span>
          </h3>
          {total > 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => void pesquisar(page - 1)}
                className="rounded-lg border border-white/10 px-2 py-1 transition hover:text-foreground disabled:opacity-40"
              >
                Anterior
              </button>
              <span>
                Página {page} de {paginas}
              </span>
              <button
                type="button"
                disabled={page >= paginas}
                onClick={() => void pesquisar(page + 1)}
                className="rounded-lg border border-white/10 px-2 py-1 transition hover:text-foreground disabled:opacity-40"
              >
                Seguinte
              </button>
            </div>
          )}
        </div>

        {itens.length === 0 && !carregando ? (
          <EmptyState message="Sem devedores para estes filtros." icon={AlertTriangle} />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-xs">
              <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-2 py-2">Nome</th>
                  <th className="px-2 py-2">NIF/NIPC</th>
                  <th className="px-2 py-2">Tipo</th>
                  <th className="px-2 py-2">Entidade</th>
                  <th className="px-2 py-2">Escalão</th>
                  <th className="px-2 py-2">Lista</th>
                  <th className="px-2 py-2">Recolha</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody>
                {itens.map((item) => (
                  <tr key={item.doc_id} className="border-t border-white/[0.06] hover:bg-white/[0.03]">
                    <td className="max-w-[260px] px-2 py-2">
                      <span className="block truncate text-foreground" title={item.nome}>
                        {item.nome}
                      </span>
                      <span className="text-[11px] text-muted-foreground">{item.ficheiro}</span>
                    </td>
                    <td className="px-2 py-2 font-mono text-[11px] text-muted-foreground">{item.nif}</td>
                    <td className="px-2 py-2 text-muted-foreground">{item.tipo_label ?? item.tipo}</td>
                    <td className="px-2 py-2 text-muted-foreground">{item.entidade_label ?? item.entidade}</td>
                    <td className="px-2 py-2 text-amber-200">{item.escalao}</td>
                    <td className="px-2 py-2 text-muted-foreground">{dataCurta(item.lista_atualizada_em)}</td>
                    <td className="px-2 py-2 text-muted-foreground">{dataCurta(item.collected_at)}</td>
                    <td className="px-2 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void abrirDetalhe(item.nif)}
                        className="rounded-lg border border-white/10 px-2 py-1 text-[11px] transition hover:text-foreground"
                      >
                        Detalhes
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {(aCarregarDetalhe || detalhe) && (
          <div className="mt-3 rounded-xl border border-amber-400/25 bg-amber-400/[0.06] p-3">
            {aCarregarDetalhe && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={13} className="animate-spin" /> A obter as listas deste NIF…
              </p>
            )}
            {detalhe && (
              <>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                      <AlertTriangle size={15} /> {detalhe.nome || `NIF ${detalhe.nif}`}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      NIF {detalhe.nif} · {detalhe.total} registo{detalhe.total === 1 ? "" : "s"} em{" "}
                      {detalhe.entidades.length} entidade{detalhe.entidades.length === 1 ? "" : "s"}
                      {detalhe.maior_valor_min ? ` · escalão a partir de ${detalhe.maior_valor_min.toLocaleString("pt-PT")} €` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {detalheTemFicha && (
                      <button
                        type="button"
                        onClick={() => onPickNif(detalhe.nif)}
                        className="flex items-center gap-1.5 rounded-lg bg-white/[0.06] px-2 py-1 text-[11px] text-teal-200 transition hover:bg-white/[0.12]"
                      >
                        <PersonStanding size={12} /> Abrir ficha no PessoasIQ
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setDetalhe(null)}
                      className="rounded-lg border border-white/10 p-1 text-muted-foreground transition hover:text-foreground"
                      aria-label="Fechar detalhe"
                    >
                      <X size={12} />
                    </button>
                  </div>
                </div>
                <ul className="mt-2 space-y-1">
                  {detalhe.items.map((registo) => (
                    <li key={registo.doc_id} className="flex flex-wrap items-center gap-x-2 text-[11px] text-amber-100/90">
                      <span className="font-medium">{registo.escalao}</span>
                      <span className="text-muted-foreground">·</span>
                      <span>{registo.entidade_label ?? registo.entidade}</span>
                      <span className="text-muted-foreground">·</span>
                      <span>{registo.tipo_label ?? registo.tipo}</span>
                      <span className="text-muted-foreground">·</span>
                      <span>
                        {registo.ficheiro} (lista de {dataCurta(registo.lista_atualizada_em)}, recolhida em{" "}
                        {dataCurta(registo.collected_at)})
                      </span>
                    </li>
                  ))}
                </ul>
                {!detalheTemFicha && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    Sem ficha no PessoasIQ (não há publicações societárias indexadas para este NIF).
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">Recolhas e ficheiros</h3>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void recolher({ entidades: ["financas"], forcar: false })}
              disabled={Boolean(jobId)}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-400/15 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-400/25 disabled:opacity-40"
            >
              <RefreshCw size={13} /> Recolher agora
            </button>
            <button
              type="button"
              onClick={() => void recolher({ entidades: ["financas"], forcar: true })}
              disabled={Boolean(jobId)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
            >
              Recolher tudo de novo
            </button>
            <button
              type="button"
              onClick={() => void indexar()}
              disabled={aIndexar}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
            >
              {aIndexar ? <Loader2 size={13} className="animate-spin" /> : <Database size={13} />} Indexar JSON
            </button>
            <button
              type="button"
              onClick={() => void recolher({ entidades: ["seguranca_social"] })}
              disabled={Boolean(jobId)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
              title="Lista da Segurança Social: recolha experimental (a fonte recusa clientes automáticos)"
            >
              Segurança Social
            </button>
          </div>
        </div>

        {job && (
          <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
            <p className="flex items-center gap-2 text-foreground">
              {job.status === "running" ? (
                <Loader2 size={13} className="animate-spin text-emerald-300" />
              ) : job.status === "done" ? (
                <Check size={13} className="text-emerald-300" />
              ) : (
                <AlertTriangle size={13} className="text-amber-300" />
              )}
              Recolha {job.job_id} · {job.progress?.phase}
              {typeof job.result?.registos === "number" && ` · ${job.result.registos.toLocaleString("pt-PT")} registos`}
            </p>
            {job.progress?.current?.ficheiro && (
              <p className="mt-1 text-muted-foreground">
                A processar {job.progress.current.ficheiro}
                {job.progress.current.escalao ? ` · ${job.progress.current.escalao}` : ""}
              </p>
            )}
            {job.error && <p className="mt-1 text-rose-300">{job.error}</p>}
          </div>
        )}

        {recolhas.length > 0 && (
          <div className="mt-3 max-h-[320px] overflow-y-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-2 py-2">Ficheiro</th>
                  <th className="px-2 py-2">Tipo</th>
                  <th className="px-2 py-2">Escalão</th>
                  <th className="px-2 py-2">Registos</th>
                  <th className="px-2 py-2">Lista</th>
                  <th className="px-2 py-2">Recolha</th>
                  <th className="px-2 py-2">Ficheiros</th>
                </tr>
              </thead>
              <tbody>
                {recolhas.map((recolha) => (
                  <tr key={recolha.recolha_id} className="border-t border-white/[0.06]">
                    <td className="px-2 py-2 text-foreground">{recolha.ficheiro}</td>
                    <td className="px-2 py-2 text-muted-foreground">{recolha.tipo_label ?? recolha.tipo}</td>
                    <td className="px-2 py-2 text-amber-200">{recolha.escalao}</td>
                    <td className="px-2 py-2 text-muted-foreground">{(recolha.registos ?? 0).toLocaleString("pt-PT")}</td>
                    <td className="px-2 py-2 text-muted-foreground">{dataCurta(recolha.lista_atualizada_em)}</td>
                    <td className="px-2 py-2 text-muted-foreground">{dataCurta(recolha.collected_at)}</td>
                    <td className="px-2 py-2">
                      <span className="flex items-center gap-2">
                        {recolha.pdf_path && (
                          <a
                            href={devedoresPdfUrl(recolha.base)}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1 text-teal-300 hover:underline"
                          >
                            <ExternalLink size={12} /> PDF
                          </a>
                        )}
                        {recolha.source_url && (
                          <a
                            href={recolha.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1 text-muted-foreground hover:underline"
                          >
                            <Globe size={12} /> Fonte
                          </a>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {fontes && (
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            <span className="text-foreground">Finanças:</span> {fontes.financas.recolhidos}/{fontes.financas.total} ficheiros
            recolhidos (6 escalões de singulares e 6 de coletivos). <span className="text-foreground">Segurança Social:</span>{" "}
            {fontes.seguranca_social.nota}
          </p>
        )}

        {meta && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Dados em <span className="text-foreground">{meta.export_dir}</span> (PDF em <code>pdf/</code>, JSON em{" "}
            <code>json/</code>) · índice <code>{meta.index}</code>
            {meta.indice?.registos !== undefined ? ` · ${meta.indice.registos.toLocaleString("pt-PT")} documentos` : ""}
          </p>
        )}
      </Card>
    </div>
  );
}

function SectionTabs({
  active,
  onChange,
}: {
  active: PessoasIQSection;
  onChange: (section: PessoasIQSection) => void;
}) {
  return (
    <div className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 px-3 py-2 lg:px-4 backdrop-blur-xl">
      {/* O menu das secções fica centrado na barra (e desliza se não couber). */}
      <div className="flex justify-center">
        <div
          role="tablist"
          aria-label="Secções do PessoasIQ"
          className="dock-scroll flex max-w-full items-center gap-0.5 overflow-x-auto rounded-[10px] border border-white/8 bg-white/[0.05] p-0.5"
        >
          {SECTIONS.map((item) => {
            const Icon = item.icon;
            const isActive = item.id === active;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => onChange(item.id)}
                title={item.label}
                className={[
                  "flex shrink-0 items-center gap-1.5 rounded-[8px] px-3 py-2 text-[13px] transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 min-h-[40px]",
                  isActive
                    ? "bg-white/[0.16] font-medium text-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
                ].join(" ")}
              >
                <Icon size={15} className={isActive ? "text-teal-300" : undefined} />
                <span className="whitespace-nowrap">{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Topbar({
  q,
  setQ,
  onSearch,
}: {
  q: string;
  setQ: (v: string) => void;
  onSearch: () => void;
}) {
  return (
    <header className="min-h-16 border-b border-white/10 bg-[#07151b]/80 backdrop-blur flex flex-wrap items-center gap-2 px-3 py-2 lg:px-4 lg:py-0 sticky top-0 z-30">
      <label className="flex flex-1 items-center gap-2 min-w-0 max-w-2xl min-h-[44px] rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
        <PersonStanding size={18} className="text-rose-300 shrink-0" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Nome, NIF, cargo, empresa…"
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground focus:ring-0"
        />
      </label>
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        <button
          onClick={onSearch}
          className="min-h-[40px] px-4 py-2 rounded-xl bg-rose-400/10 text-rose-300 border border-rose-400/20 text-sm hover:bg-rose-400/20 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
        >
          Pesquisar
        </button>
        <button
          className="min-h-[40px] min-w-[40px] p-2 rounded-xl hover:bg-white/5 text-muted-foreground transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
          aria-label="Configurações"
          title="Configurações"
        >
          <Settings size={18} />
        </button>
        <div
          className="w-8 h-8 rounded-full bg-gradient-to-br from-rose-400 to-orange-500 flex items-center justify-center text-xs font-bold text-white"
          aria-label="Utilizador PM"
          title="Utilizador PM"
        >
          PM
        </div>
      </div>
    </header>
  );
}

function DashboardSection({ status, onSection }: { status: PeopleStatusResponse | null; onSection: (s: PessoasIQSection) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card glow="rose">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pessoas/cargos indexados</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">{status?.documents ?? 0}</p>
        </Card>
        <Card glow="blue">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Empresas com pessoas</p>
          <p className="mt-1 text-2xl font-semibold text-foreground">{status?.total_company_links ?? 0}</p>
        </Card>
        <Card glow="teal">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Cargos mais comuns</p>
          <div className="mt-2 space-y-1">
            {(status?.top_roles ?? []).slice(0, 3).map((role) => (
              <div key={role.key} className="flex items-center justify-between text-xs">
                <span className="truncate">{role.key}</span>
                <span className="text-muted-foreground">{role.count}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card
          glow="rose"
          className="cursor-pointer hover:bg-white/[0.03] transition"
          onClick={() => onSection("search")}
        >
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pesquisar</p>
          <p className="mt-2 flex items-center gap-2 text-sm font-medium text-rose-300">
            Abrir pesquisa <ArrowRight size={14} />
          </p>
        </Card>
      </div>
    </div>
  );
}

function RoleRow({ role }: { role: PersonRole }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-foreground">{roleLabel(role.role, role.event)}</p>
          {role.role_org && <p className="text-xs text-muted-foreground">{role.role_org}</p>}
        </div>
        {role.quota !== null && role.quota !== undefined && (
          <span className="shrink-0 rounded-full bg-amber-400/10 px-2 py-0.5 text-xs text-amber-300">
            {role.quota.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {role.company_nif && (
          <span className="flex items-center gap-1">
            <Building2 size={12} />
            {role.company_name || role.company_nif}
          </span>
        )}
        {role.date && <span>Data: {formatDate(role.date)}</span>}
        {role.publication_date && <span>Publicação: {formatDate(role.publication_date)}</span>}
        {role.acto && <span className="truncate max-w-xs">Acto: {role.acto}</span>}
        {role.tribunal && <span className="truncate max-w-xs">Tribunal: {role.tribunal}</span>}
        {role.causa && <span className="truncate max-w-xs">Causa: {role.causa}</span>}
      </div>
    </div>
  );
}

function PersonDetailPanel({
  person,
  onClose,
  onGraph,
  on360,
}: {
  person: Person;
  onClose: () => void;
  onGraph: () => void;
  on360: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <PersonStanding size={22} className="text-rose-300" />
            {person.name}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            NIF {person.nif} · {person.is_company ? "Entidade coletiva" : "Pessoa singular"} ·{" "}
            {person.roles_count} cargos · {person.companies_count} empresas
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-white/10 p-1.5 text-muted-foreground hover:text-foreground transition"
          aria-label="Fechar"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onGraph}
          className="flex items-center gap-2 rounded-xl bg-rose-400/10 px-3 py-1.5 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition"
        >
          <GitBranch size={16} /> Ver grafo
        </button>
        <button
          type="button"
          onClick={on360}
          className="flex items-center gap-2 rounded-xl bg-teal-400/10 px-3 py-1.5 text-sm text-teal-200 border border-teal-400/20 hover:bg-teal-400/20 transition"
        >
          <ShieldAlert size={16} /> 360 · risco e redes
        </button>
      </div>

      <DebtBadge nif={person.nif} />

      {person.roles.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Cargos e empresas</h3>
          <div className="max-h-[420px] overflow-y-auto space-y-2 pr-1">
            {person.roles.map((role, idx) => (
              <RoleRow key={`${role.publication_id || idx}-${idx}`} role={role} />
            ))}
          </div>
        </div>
      )}

      {person.first_seen && person.last_seen && (
        <p className="text-xs text-muted-foreground">
          Primeira deteção: {formatDate(person.first_seen)} · Última deteção: {formatDate(person.last_seen)}
        </p>
      )}
    </div>
  );
}

function CompanyPersonRow({ person, onOpen }: { person: CompanyPerson; onOpen: () => void }) {
  const cargos = person.cargos_empresa ?? 1;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left text-sm transition hover:bg-white/[0.06]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 font-medium text-foreground">
            {person.is_company ? (
              <Building2 size={14} className="shrink-0 text-blue-300" />
            ) : (
              <PersonStanding size={14} className="shrink-0 text-rose-300" />
            )}
            <span className="truncate">{person.name}</span>
          </p>
          <p className="text-xs text-muted-foreground">NIF {person.nif}</p>
        </div>
        <span className="shrink-0 rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-muted-foreground">
          {cargos} cargo{cargos === 1 ? "" : "s"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="text-teal-300">{roleLabel(person.cargo, person.event)}</span>
        {person.role_org && <span>{person.role_org}</span>}
        {person.date && <span>Data: {formatDate(person.date)}</span>}
        {person.roles_total ? <span>{person.roles_total} cargos no total</span> : null}
      </div>
    </button>
  );
}

/**
 * Ficha de empresa no PessoasIQ: a empresa e quem lá tem cargos.
 *
 * A empresa não precisa de ter ficha própria no índice de pessoas — o vínculo é
 * o cargo que as pessoas nela têm (publicações societárias e processos do CIRE).
 */
function CompanyDetailPanel({
  company,
  detail,
  loading,
  error,
  onClose,
  onGraph,
  onSelectPerson,
}: {
  company: PeopleCompanyItem;
  detail: PeopleCompanyResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onGraph: () => void;
  onSelectPerson: (nif: string) => void;
}) {
  const people = detail?.people ?? [];
  const nome = detail?.name || company.name || `NIF ${company.nif}`;
  const total = people.length || company.people_count;
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <Building2 size={22} className="shrink-0 text-blue-300" />
            {nome}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            NIF {company.nif} · Empresa · {total} pessoa{total === 1 ? "" : "s"} com cargos
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-white/10 p-1.5 text-muted-foreground transition hover:text-foreground"
          aria-label="Fechar"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onGraph}
          className="flex items-center gap-2 rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-1.5 text-sm text-rose-300 transition hover:bg-rose-400/20"
        >
          <GitBranch size={16} /> Ver grafo
        </button>
      </div>

      <DebtBadge nif={company.nif} />

      {loading && <p className="text-sm text-muted-foreground">A carregar as pessoas desta empresa…</p>}
      {error && (
        <p className="rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}
      {!loading && !error && people.length === 0 && (
        <p className="text-sm text-muted-foreground">Sem pessoas com cargos indexados nesta empresa.</p>
      )}
      {people.length > 0 && (
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          <h3 className="text-sm font-semibold text-foreground">Pessoas e cargos nesta empresa</h3>
          {people.map((pessoa) => (
            <CompanyPersonRow
              key={pessoa.nif}
              person={pessoa}
              onOpen={() => onSelectPerson(pessoa.nif)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SearchSection({
  initialQ,
  onSelectPerson,
  onSelectCompany,
  onSelectNif,
}: {
  initialQ: string;
  onSelectPerson: (person: Person) => void;
  onSelectCompany: (company: PeopleCompanyItem) => void;
  onSelectNif: (nif: string) => void;
}) {
  const [q, setQ] = useState(initialQ);
  const [companies, setCompanies] = useState<PeopleCompaniesResponse | null>(null);
  const [devedores, setDevedores] = useState<DevedorRegisto[]>([]);
  const [personType, setPersonType] = useState<PersonTypeFilter>("all");
  const [role, setRole] = useState("");
  const [origin, setOrigin] = useState<"" | "cire" | "societario">("");
  const [minRoles, setMinRoles] = useState<number | "">("");
  const [sort, setSort] = useState<PeopleSort>("relevance");
  const [results, setResults] = useState<PeopleSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facets, setFacets] = useState<PeopleFiltersResponse | null>(null);

  // Autocomplete (sugestões enquanto se escreve).
  const [suggestions, setSuggestions] = useState<PeopleAutocompleteItem[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [typing, setTyping] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const hasSearchedRef = useRef(false);

  const PERSON_TYPE_OPTS: { key: PersonTypeFilter; label: string }[] = [
    { key: "all", label: "Todos" },
    { key: "person", label: "Pessoas" },
    { key: "company", label: "Entidades" },
  ];

  const runSearch = useCallback(
    async (
      value: string,
      type: PersonTypeFilter,
      opts?: { from?: number; nif?: string; append?: boolean; role?: string; origin?: "cire" | "societario"; minRoles?: number; sort?: PeopleSort },
    ) => {
      const term = value.trim();
      const nif = opts?.nif;
      if (!term && !nif) {
        setResults(null);
        return;
      }
      const append = Boolean(opts?.append);
      const from = opts?.from ?? 0;
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      setShowSuggestions(false);
      hasSearchedRef.current = true;
      try {
        const resp = await searchPeople(term || undefined, {
          nif,
          isCompany: type === "company" ? true : type === "person" ? false : undefined,
          role: opts?.role ?? (role.trim() || undefined),
          origin: (opts?.origin ?? origin) || undefined,
          minRoles: opts?.minRoles ?? (typeof minRoles === "number" ? minRoles : undefined),
          sort: opts?.sort ?? sort,
          size: SEARCH_PAGE_SIZE,
          from,
        });
        setResults((prev) =>
          append && prev ? { ...resp, items: [...prev.items, ...resp.items], from: 0 } : resp,
        );
        if (!append) {
          // Pesquisa por empresa: a empresa pode não ter ficha própria, porque o
          // vínculo é o cargo que as pessoas nela têm.
          const empresas = await searchPeopleCompanies(term || nif || "", 8).catch(() => null);
          setCompanies(empresas);
          // Alguns NIF só existem nas listas públicas de devedores (não têm
          // publicações societárias): mostra-se o que as listas publicam.
          const termoDevedores = (nif || term).replace(/\D/g, "");
          const porNif = termoDevedores.length === 9;
          const lista = await devedoresSearch(
            porNif
              ? { nif: termoDevedores, size: 8, sort: "escalao", order: "desc" }
              : { q: term || undefined, size: 8, sort: "escalao", order: "desc" },
          ).catch(() => null);
          setDevedores(lista?.items ?? []);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao pesquisar");
        if (!append) setResults(null);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [minRoles, origin, role, sort],
  );

  // Pesquisa inicial (quando a página abre com um termo) e facetas dos filtros.
  useEffect(() => {
    if (initialQ) void runSearch(initialQ, personType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    getPeopleFilters()
      .then(setFacets)
      .catch(() => setFacets(null));
  }, []);

  // Autocomplete com debounce; cancela o pedido anterior quando se continua a
  // escrever (evita resultados fora de ordem).
  useEffect(() => {
    const term = q.trim();
    if (!showSuggestions || term.length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setTyping(true);
      try {
        const items = await autocompletePeople(term, {
          limit: 8,
          isCompany: personType === "company" ? true : personType === "person" ? false : undefined,
          signal: controller.signal,
        });
        setSuggestions(items);
        setActiveIndex(items.length ? 0 : -1);
      } catch {
        // pedido cancelado ou sem rede: mantém as sugestões anteriores
      } finally {
        if (!controller.signal.aborted) setTyping(false);
      }
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [q, personType, showSuggestions]);

  // Fechar sugestões ao clicar fora.
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setShowSuggestions(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Mudar um filtro volta a pesquisar (sem refazer a pesquisa a cada tecla).
  useEffect(() => {
    if (!hasSearchedRef.current) return;
    void runSearch(q, personType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personType, role, origin, minRoles, sort]);

  const pickSuggestion = (item: PeopleAutocompleteItem) => {
    setSuggestions([]);
    setShowSuggestions(false);
    setActiveIndex(-1);
    setQ(item.name);
    void runSearch(item.name, personType, { nif: item.nif || undefined });
  };

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" && suggestions.length) {
      event.preventDefault();
      setShowSuggestions(true);
      setActiveIndex((prev) => (prev + 1) % suggestions.length);
      return;
    }
    if (event.key === "ArrowUp" && suggestions.length) {
      event.preventDefault();
      setActiveIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
      return;
    }
    if (event.key === "Escape") {
      setShowSuggestions(false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const active = showSuggestions && activeIndex >= 0 ? suggestions[activeIndex] : undefined;
      if (active) pickSuggestion(active);
      else void runSearch(q, personType);
    }
  };

  const activeFilters: { key: string; label: string; clear: () => void }[] = [];
  if (personType !== "all") {
    activeFilters.push({
      key: "type",
      label: personType === "person" ? "Só pessoas" : "Só entidades",
      clear: () => setPersonType("all"),
    });
  }
  if (role) activeFilters.push({ key: "role", label: `Cargo: ${role}`, clear: () => setRole("") });
  if (origin) {
    activeFilters.push({
      key: "origin",
      label: `Origem: ${origin === "cire" ? "CIRE (insolvências)" : "Societário (MJ)"}`,
      clear: () => setOrigin(""),
    });
  }
  if (typeof minRoles === "number") {
    activeFilters.push({ key: "min", label: `Mín. ${minRoles} cargos`, clear: () => setMinRoles("") });
  }
  if (sort !== "relevance") {
    activeFilters.push({ key: "sort", label: `Ordenar: ${SORT_LABELS[sort]}`, clear: () => setSort("relevance") });
  }

  const clearFilters = () => {
    setPersonType("all");
    setRole("");
    setOrigin("");
    setMinRoles("");
    setSort("relevance");
  };

  const loadedCount = results?.items.length ?? 0;
  const hasMore = Boolean(results && loadedCount < results.total);

  return (
    <div className="space-y-4">
      <Card>
        <div ref={boxRef} className="flex flex-col gap-3">
          <div className="relative">
            <div className="flex min-h-[44px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
              <Search size={18} className="shrink-0 text-muted-foreground" />
              <input
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setShowSuggestions(true);
                }}
                onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                onKeyDown={onInputKeyDown}
                placeholder="Nome, NIF, cargo ou empresa…"
                autoComplete="off"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={showSuggestions && suggestions.length > 0}
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {typing && <Loader2 size={14} className="shrink-0 animate-spin text-muted-foreground" />}
              {q && (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    setSuggestions([]);
                  }}
                  aria-label="Limpar pesquisa"
                  className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-30 mt-1 max-h-[320px] w-full overflow-y-auto rounded-xl border border-white/10 bg-[#140f13] p-1 shadow-xl">
                {suggestions.map((item, idx) => (
                  <button
                    key={`${item.nif || item.name}-${idx}`}
                    type="button"
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => pickSuggestion(item)}
                    className={[
                      "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition",
                      idx === activeIndex ? "bg-white/[0.10]" : "hover:bg-white/[0.06]",
                    ].join(" ")}
                  >
                    {item.is_company ? (
                      <Building2 size={15} className="shrink-0 text-blue-300" />
                    ) : (
                      <PersonStanding size={15} className="shrink-0 text-rose-300" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-foreground">{item.name}</span>
                      <span className="block truncate text-muted-foreground">
                        NIF {item.nif || "—"}
                        {item.role ? ` · ${item.role}` : ""}
                        {item.company_name ? ` · ${item.company_name}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 text-right text-muted-foreground">
                      <span className="block">{item.roles_count} cargos</span>
                      <span className="block">{item.companies_count} empresas</span>
                    </span>
                    {item.origin === "cire" && (
                      <span className="shrink-0 rounded-full bg-amber-400/15 px-2 py-0.5 text-[10px] text-amber-200">
                        CIRE
                      </span>
                    )}
                  </button>
                ))}
                <p className="px-3 py-1 text-[10px] text-muted-foreground">
                  ↑↓ navegar · Enter escolher · Esc fechar
                </p>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
            <div className="flex w-full items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] p-0.5 lg:w-auto">
              {PERSON_TYPE_OPTS.map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => setPersonType(opt.key)}
                  className={[
                    "min-h-[44px] flex-1 rounded-md px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 lg:min-h-[40px] lg:flex-initial",
                    personType === opt.key
                      ? "bg-white/[0.16] font-medium text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              aria-label="Filtrar por cargo ou papel"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 lg:min-h-[40px] lg:w-[220px]"
            >
              <option value="">Todos os cargos</option>
              {role && !(facets?.roles || []).some((r) => r.key.toLowerCase() === role.toLowerCase()) && (
                <option value={role}>{role}</option>
              )}
              {(facets?.roles || []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.key} ({item.count.toLocaleString("pt-PT")})
                </option>
              ))}
            </select>
            <select
              value={origin}
              onChange={(e) => setOrigin(e.target.value as "" | "cire" | "societario")}
              aria-label="Filtrar por origem dos dados"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 lg:min-h-[40px] lg:w-[230px]"
            >
              <option value="">Qualquer origem</option>
              <option value="cire">
                CIRE / insolvências{facets?.with_cire ? ` (${facets.with_cire.toLocaleString("pt-PT")})` : ""}
              </option>
              <option value="societario">Societário (publicações MJ)</option>
            </select>
            <input
              type="number"
              min={0}
              value={minRoles}
              onChange={(e) => setMinRoles(e.target.value === "" ? "" : Math.max(0, Number(e.target.value)))}
              placeholder="Mín. cargos"
              aria-label="Número mínimo de cargos"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 lg:min-h-[40px] lg:w-[120px]"
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as PeopleSort)}
              aria-label="Ordenar resultados"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 lg:min-h-[40px] lg:w-[170px]"
            >
              {(Object.keys(SORT_LABELS) as PeopleSort[]).map((key) => (
                <option key={key} value={key}>
                  {SORT_LABELS[key]}
                </option>
              ))}
            </select>
            <button
              onClick={() => void runSearch(q, personType)}
              disabled={loading}
              className="min-h-[40px] w-full rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-2 text-sm text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50 lg:w-auto"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Pesquisar"}
            </button>
          </div>

          {activeFilters.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted-foreground">Filtros:</span>
              {activeFilters.map((filter) => (
                <button
                  key={filter.key}
                  type="button"
                  onClick={filter.clear}
                  className="flex items-center gap-1 rounded-full bg-white/[0.08] px-2 py-1 text-muted-foreground transition hover:text-foreground"
                >
                  {filter.label}
                  <X size={12} />
                </button>
              ))}
              <button
                type="button"
                onClick={clearFilters}
                className="rounded-full border border-white/10 px-2 py-1 text-muted-foreground transition hover:text-foreground"
              >
                Limpar filtros
              </button>
            </div>
          )}
        </div>
      </Card>

      {error && (
        <Card className="p-6 text-center">
          <p className="text-rose-300">{error}</p>
        </Card>
      )}

      {!results && !loading && !error && (
        <EmptyState message="Introduza um termo para pesquisar pessoas, empresas e cargos." />
      )}

      {loading && <Loading message="A pesquisar pessoas, empresas e cargos…" />}

      {results && results.total === 0 && !loading && !(companies && companies.items.length > 0) && devedores.length === 0 && (
        <EmptyState message="Nenhuma pessoa, empresa ou cargo encontrado." />
      )}

      {!loading && devedores.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle size={14} className="text-amber-300" />
            Devedores nas listas públicas ({devedores.length}) · Finanças e Segurança Social
          </p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {devedores.map((registo) => (
              <button
                key={registo.doc_id}
                type="button"
                onClick={() => onSelectNif(registo.nif)}
                className="flex min-h-[44px] items-center gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-left transition hover:bg-amber-400/[0.12]"
              >
                <AlertTriangle size={18} className="shrink-0 text-amber-300" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{registo.nome}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    NIF {registo.nif} · {registo.escalao}
                  </span>
                </span>
                <span className="shrink-0 rounded-full bg-amber-400/15 px-2 py-0.5 text-[11px] text-amber-200">
                  lista {dataCurta(registo.lista_atualizada_em)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!loading && companies && companies.items.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Building2 size={14} className="text-blue-300" />
            Empresas com pessoas ({companies.items.length}) · abra para ver a empresa e quem lá tem cargos
          </p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {companies.items.map((empresa) => (
              <button
                key={empresa.nif}
                type="button"
                onClick={() => onSelectCompany(empresa)}
                className="flex min-h-[44px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-left transition hover:bg-white/[0.08]"
              >
                <Building2 size={18} className="shrink-0 text-blue-300" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {empresa.name || `Empresa ${empresa.nif}`}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    NIF {empresa.nif} · {empresa.roles_count} cargo{empresa.roles_count === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="shrink-0 rounded-full bg-blue-400/10 px-2 py-0.5 text-[11px] text-blue-200">
                  {empresa.people_count} pessoa{empresa.people_count === 1 ? "" : "s"}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {results && results.total > 0 && !loading && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {results.total.toLocaleString("pt-PT")} resultado{results.total === 1 ? "" : "s"}
            {loadedCount < results.total ? ` · a mostrar ${loadedCount}` : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {results.items.map((person) => (
              <Card
                key={person.nif}
                className="cursor-pointer hover:bg-white/[0.03] transition"
                onClick={() => onSelectPerson(person)}
              >
                <div className="flex items-start justify-between gap-2 min-h-[44px]">
                  <div className="min-w-0">
                    <p className="font-medium text-foreground truncate">{person.name}</p>
                    <p className="text-xs text-muted-foreground">NIF {person.nif}</p>
                  </div>
                  {person.is_company ? (
                    <Building2 size={18} className="text-blue-300 shrink-0" />
                  ) : (
                    <PersonStanding size={18} className="text-rose-300 shrink-0" />
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-white/[0.06] px-2 py-1 text-muted-foreground">
                    {person.roles_count} cargos
                  </span>
                  <span className="rounded-full bg-white/[0.06] px-2 py-1 text-muted-foreground">
                    {person.companies_count} empresas
                  </span>
                </div>
                {person.roles.slice(0, 2).map((role, idx) => (
                  <p key={idx} className="mt-1 text-xs text-muted-foreground truncate">
                    {roleLabel(role.role, role.event)} · {role.company_name || role.company_nif || "—"}
                  </p>
                ))}
              </Card>
            ))}
          </div>
          {hasMore && (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() =>
                  void runSearch(q, personType, { from: loadedCount, append: true })
                }
                disabled={loadingMore}
                className="min-h-[40px] rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-foreground transition hover:bg-white/[0.08] disabled:opacity-50"
              >
                {loadingMore ? <Loader2 size={16} className="animate-spin" /> : "Carregar mais"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// `NodeShapeLegend`, os tipos do grafo/pesquisa (GraphMode, NodeKindFilter,
// EdgeKindFilter, PeopleSort, SORT_LABELS, SEARCH_PAGE_SIZE), o `NodeSummaryCard`
// e o `MARKDOWN_COMPONENTS` vivem em `components/people/peopleKit`.

/**
 * Explorador do grafo de pessoas/cargos.
 *
 * É o mesmo componente na secção «Grafo» do PessoasIQ e na janela própria
 * `pessoas-graph:*` — a única diferença é o `withPicker` (pesquisa de pessoas
 * com autocomplete e filtros dentro do próprio painel) e os atalhos de ficha
 * que só fazem sentido na janela (`standalone`).
 */
export function GraphSection({
  person,
  initialNif = "",
  initialCompanyNif = "",
  initialMode = "person",
  initialLabel = null,
  withPicker = false,
  standalone = false,
  className = "",
  heightClass = "h-[50vh] min-h-[300px] sm:h-[58vh] lg:h-[68vh] max-h-[640px]",
  detailHeightClass = "max-h-[40vh] sm:max-h-[55vh] lg:max-h-[520px]",
}: {
  person: Person | null;
  initialNif?: string;
  initialCompanyNif?: string;
  initialMode?: GraphMode;
  initialLabel?: string | null;
  /** Mostrar a pesquisa de pessoas com autocomplete e filtros dentro do grafo. */
  withPicker?: boolean;
  /** A correr numa janela própria: mostra atalhos para fichas e para o PessoasIQ. */
  standalone?: boolean;
  className?: string;
  heightClass?: string;
  detailHeightClass?: string;
}) {
  const [nif, setNif] = useState(person?.nif || initialNif);
  const [companyNif, setCompanyNif] = useState(initialCompanyNif);
  const [mode, setMode] = useState<GraphMode>(person?.nif ? "person" : initialMode);
  const [label, setLabel] = useState<string | null>(initialLabel ?? null);
  // Sem gestor de janelas (modo «ecrã inteiro») não há onde abrir «Nova janela».
  const { windowMode: graphWindowMode } = useWindowMode();
  const [graphData, setGraphData] = useState<PeopleGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [layoutVersion, setLayoutVersion] = useState(0);

  // Filtros dinâmicos no grafo renderizado
  const [nodeKind, setNodeKind] = useState<NodeKindFilter>("all");
  const [edgeKind, setEdgeKind] = useState<EdgeKindFilter>("all");
  const [minValue, setMinValue] = useState<number | "">("");
  const [searchText, setSearchText] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const effectiveMode: GraphMode = useMemo(() => {
    if (mode === "combined" && companyNif.trim()) return "combined";
    if (mode === "person" && nif.trim()) return "person";
    if (mode === "company" && companyNif.trim()) return "company";
    if (companyNif.trim()) return "company";
    return "person";
  }, [mode, nif, companyNif]);

  const loadGraph = useCallback(async () => {
    if (!nif.trim() && !companyNif.trim()) return;
    setLoading(true);
    setError(null);
    try {
      let resp: PeopleGraphResponse;
      if (effectiveMode === "combined" && companyNif.trim()) {
        resp = await getCompanyCombinedGraph(companyNif.trim(), { contractLimit: 100 });
      } else if (effectiveMode === "company" && companyNif.trim()) {
        resp = await getCompanyPeopleGraph(companyNif.trim());
      } else {
        resp = await getPersonGraph(nif.trim());
      }
      setGraphData(resp);
      setLabel(resp.person_name || resp.company_name || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar grafo");
    } finally {
      setLoading(false);
    }
  }, [companyNif, effectiveMode, nif]);

  useEffect(() => {
    if (person?.nif) {
      setNif(person.nif);
      setCompanyNif("");
      setMode("person");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [person?.nif]);

  /**
   * Carrega o grafo sozinho quando o modo ou os NIF mudam: trocar de
   * Pessoa/Empresa/Combinado (ou colar um NIF) deve mostrar logo o grafo, sem
   * obrigar a carregar no botão. O atraso evita um pedido por cada tecla.
   */
  useEffect(() => {
    const target = (effectiveMode === "person" ? nif : companyNif).trim();
    if (!/^\d{9}$/.test(target)) return;
    const timer = window.setTimeout(() => {
      void loadGraph();
    }, 450);
    return () => window.clearTimeout(timer);
  }, [companyNif, effectiveMode, loadGraph, nif]);

  const filteredGraphData = useMemo(() => {
    if (!graphData) return null;
    const term = searchText.trim().toLowerCase();
    const min = typeof minValue === "number" ? minValue : 0;

    let nodes = graphData.nodes;
    let edges = graphData.edges;

    // 1) Edge type/value filters first so we know which edges are available.
    if (edgeKind !== "all") {
      edges = edges.filter((e) => e.type === edgeKind);
    }
    if (min > 0) {
      // Contratos filtram por euros; arestas de cargos filtram pelo nº de cargos
      // (não têm valor monetário).
      edges = edges.filter((e) => {
        const amount = e.type === "contract" ? (typeof e.value === "number" ? e.value : 0) : (e.count || 0);
        return amount >= min;
      });
    }

    // 2) Node type filter keeps matching nodes plus the central company anchor
    //    and any node that is still linked by the surviving edges.
    if (nodeKind !== "all") {
      const central = nodes.find((n) => n.is_company) || nodes.find((n) => n.type === "company");
      const matched = nodes.filter((n) => n.type === nodeKind);
      const keepIds = new Set<string>([
        ...(central ? [central.id] : []),
        ...matched.map((n) => n.id),
      ]);
      nodes = nodes.filter((n) => keepIds.has(n.id));
      const connectedIds = new Set(edges.flatMap((e) => [e.source, e.target]));
      nodes = nodes.filter((n) => connectedIds.has(n.id));
    }

    // 3) Always keep only edges whose endpoints are still present.
    const keepNodeIds = new Set(nodes.map((n) => n.id));
    edges = edges.filter((e) => keepNodeIds.has(e.source) && keepNodeIds.has(e.target));

    // 4) Text search filters by node label/nif/type and keeps connected neighbours.
    if (term) {
      const matchedNodeIds = new Set(
        nodes
          .filter((n) =>
            (n.label || "").toLowerCase().includes(term) ||
            (n.nif || "").toLowerCase().includes(term) ||
            (n.type || "").toLowerCase().includes(term),
          )
          .map((n) => n.id),
      );
      edges = edges.filter((e) => matchedNodeIds.has(e.source) || matchedNodeIds.has(e.target));
      const connectedIds = new Set(edges.flatMap((e) => [e.source, e.target]));
      nodes = nodes.filter((n) => matchedNodeIds.has(n.id) || connectedIds.has(n.id));
      const finalNodeIds = new Set(nodes.map((n) => n.id));
      edges = edges.filter((e) => finalNodeIds.has(e.source) && finalNodeIds.has(e.target));
    }

    return {
      ...graphData,
      nodes,
      edges,
      node_count: nodes.length,
      edge_count: edges.length,
    };
  }, [graphData, nodeKind, edgeKind, minValue, searchText]);

  const studioGraph = useMemo(() => combinedToStudioGraph(filteredGraphData), [filteredGraphData]);

  /** O grafo só tem valores em euros quando inclui arestas de contratos. */
  const hasContractEdges = useMemo(
    () => Boolean(graphData?.edges?.some((edge) => edge.type === "contract")),
    [graphData],
  );

  /** NIF do alvo atual (pessoa, ou empresa nos modos Empresa/Combinado). */
  const targetNif = (effectiveMode === "person" ? nif : companyNif).trim();

  /** Escolher uma pessoa/entidade na pesquisa carrega logo o respetivo grafo. */
  const applyPickerTarget = useCallback((target: GraphTarget, item?: { name?: string } | null) => {
    setLabel(item?.name ?? null);
    setSelectedNodeId(null);
    if (target.mode === "person") {
      setNif(target.nif);
      setCompanyNif("");
    } else {
      setCompanyNif(target.nif);
      setNif("");
    }
    setMode(target.mode);
  }, []);

  return (
    <div className={`flex min-h-0 flex-col gap-3 ${className}`}>
      {withPicker && (
        <PeoplePicker
          onPick={(target, item) => applyPickerTarget(target, item)}
          onOpenDetail={(target) =>
            openWindow(
              `${target.mode === "person" ? "person-detail" : "company-detail"}:${target.nif}`,
              undefined,
              { title: target.nif },
            )
          }
        />
      )}

      <Card className="p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="min-w-0">
              <label className="block text-[11px] text-muted-foreground">Pessoa (NIF)</label>
              <input
                value={nif}
                onChange={(e) => setNif(e.target.value)}
                placeholder="NIF da pessoa"
                aria-label="NIF da pessoa"
                className="mt-1 min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50 sm:w-[220px]"
              />
            </div>
            <div className="min-w-0">
              <label className="block text-[11px] text-muted-foreground">ou Empresa (NIF)</label>
              <input
                value={companyNif}
                onChange={(e) => setCompanyNif(e.target.value)}
                placeholder="NIF da empresa"
                aria-label="NIF da empresa"
                className="mt-1 min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50 sm:w-[220px]"
              />
            </div>
            <button
              onClick={() => void loadGraph()}
              disabled={loading || (!nif.trim() && !companyNif.trim())}
              className="min-h-[44px] rounded-xl bg-rose-400/10 px-4 py-2 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition disabled:opacity-40 sm:self-end"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Carregar grafo"}
            </button>
            {graphWindowMode && targetNif.length === 9 && (
              <button
                type="button"
                onClick={() => openGraphWindow(effectiveMode, targetNif, label)}
                title="Abrir o grafo deste alvo numa janela independente (com pesquisa e filtros dentro dela)"
                className="flex min-h-[44px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-4 py-2 text-sm text-foreground transition hover:bg-white/[0.09] sm:self-end"
              >
                <ExternalLink size={15} />
                Nova janela
              </button>
            )}
            {standalone && targetNif.length === 9 && (
              <>
                <button
                  type="button"
                  onClick={() =>
                    openWindow(
                      `${effectiveMode === "person" ? "person-detail" : "company-detail"}:${targetNif}`,
                      undefined,
                      { title: label || targetNif },
                    )
                  }
                  className="flex min-h-[44px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-4 py-2 text-sm text-foreground transition hover:bg-white/[0.09] sm:self-end"
                >
                  <Users size={15} />
                  Abrir ficha
                </button>
                <button
                  type="button"
                  onClick={() => openWindow("pessoas-iq", undefined)}
                  className="flex min-h-[44px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-4 py-2 text-sm text-foreground transition hover:bg-white/[0.09] sm:self-end"
                >
                  <Network size={15} />
                  Abrir PessoasIQ
                </button>
              </>
            )}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="flex flex-wrap items-center gap-2">
              {(["person", "company", "combined"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={mode === option}
                  onClick={() => setMode(option)}
                  className={[
                    "min-h-[44px] rounded-xl px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px]",
                    mode === option
                      ? "glass-card text-rose-200 ring-1 ring-rose-400/30"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {option === "person" ? "Pessoa" : option === "company" ? "Empresa" : "Combinado"}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {(["network", "hierarchical", "circular"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={layout === option}
                  onClick={() => {
                    setLayout(option);
                    setLayoutVersion((v) => v + 1);
                  }}
                  className={[
                    "min-h-[44px] rounded-xl px-3 py-2 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px]",
                    layout === option
                      ? "glass-card text-rose-200 ring-1 ring-rose-400/30"
                      : "text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  {option === "network" ? "Rede" : option === "hierarchical" ? "Hierárquico" : "Circular"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Card>

      <Card className="py-3 px-4">
        <div className="flex flex-col gap-3 text-xs sm:flex-row sm:flex-wrap sm:items-center">
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Pesquisar nó…"
              aria-label="Pesquisar nó no grafo"
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-[200px]"
            />
            <select
              value={nodeKind}
              onChange={(e) => setNodeKind(e.target.value as NodeKindFilter)}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-auto"
            >
              <option value="all">Todos os nós</option>
              <option value="person">Pessoas</option>
              <option value="company">Empresas</option>
              <option value="entity">Entidades</option>
            </select>
            <select
              value={edgeKind}
              onChange={(e) => setEdgeKind(e.target.value as EdgeKindFilter)}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-auto"
            >
              <option value="all">Todas as ligações</option>
              <option value="role">Cargos/sócios</option>
              <option value="contract">Contratos</option>
            </select>
            <input
              type="number"
              min={0}
              value={minValue}
              onChange={(e) => setMinValue(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder={hasContractEdges ? "Valor mínimo (€)" : "Mínimo de cargos"}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40 sm:min-h-[40px] sm:w-[140px]"
            />
          </div>
          {effectiveMode === "combined" && graphData?.meta && (
            <span className="text-muted-foreground sm:ml-auto">
              {graphData.meta.people_edge_count ?? 0} cargos · {graphData.meta.contract_nodes ?? 0} entidades ·{" "}
              {graphData.meta.contract_count_total ?? 0} contratos ·{" "}
              {(graphData.meta.contract_value_total ?? 0).toLocaleString("pt-PT", {
                style: "currency",
                currency: "EUR",
                maximumFractionDigits: 0,
              })}
            </span>
          )}
        </div>
      </Card>

      {(effectiveMode === "combined" || filteredGraphData) && (
        <Card className="py-2 px-3">
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <NodeShapeLegend />
            {effectiveMode === "combined" && (
              <>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-[#38bdf8]" />
                  Empresa central
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-3 rounded-full bg-[#a78bfa]" />
                  Entidades contratuais
                </span>
              </>
            )}
            {filteredGraphData && (
              <span className="ml-auto text-muted-foreground">
                Visíveis: {filteredGraphData.node_count} nós · {filteredGraphData.edge_count} arestas
              </span>
            )}
          </div>
        </Card>
      )}

      {error && (
        <Card className="p-6 text-center">
          <p className="text-rose-300">{error}</p>
        </Card>
      )}

      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[1fr_minmax(0,420px)]">
        <Card className="flex flex-col p-3 lg:min-h-0 w-full">
          {studioGraph && studioGraph.nodes.length > 0 ? (
            <GraphCanvas
              graph={studioGraph}
              layout={layout}
              metric={"contratos" as GraphMetric}
              layoutVersion={layoutVersion}
              loading={loading}
              heightClass={heightClass}
              selectedNodeId={selectedNodeId}
              onNodeClick={(node) => setSelectedNodeId(node.id)}
            />
          ) : (
            <div className={`flex ${heightClass} flex-col items-center justify-center text-sm text-muted-foreground`}>
              <Network size={32} className="mb-3 opacity-40" />
              {loading ? "A construir grafo…" : "Pesquise uma pessoa ou empresa para visualizar as ligações."}
            </div>
          )}
        </Card>

        <Card className="flex flex-col p-4 lg:col-span-1 lg:min-h-0 w-full">
          <h4 className="text-sm font-semibold shrink-0">Detalhe do nó</h4>
          <div className={`mt-3 min-h-0 flex-1 overflow-y-auto ${detailHeightClass}`}>
            {selectedNodeId && graphData ? (
              (() => {
                const node = graphData.nodes.find((n) => n.id === selectedNodeId);
                const connected = graphData.edges.filter(
                  (e) => e.source === selectedNodeId || e.target === selectedNodeId,
                );
                if (!node) return <p className="text-xs text-muted-foreground">Nó não encontrado.</p>;
                return (
                  <div className="space-y-3 text-xs">
                    <p className="font-medium text-sm">{node.label}</p>
                    <p className="text-muted-foreground">
                      Tipo: {node.type === "company" ? "Empresa central" : node.type === "entity" ? "Entidade" : "Pessoa"}
                      <br />
                      {node.nif && <span>NIF: {node.nif}</span>}
                      <br />
                      Ligações: {connected.length}
                    </p>
                    {standalone && node.nif && (
                      <button
                        type="button"
                        onClick={() =>
                          openWindow(
                            `${node.type === "person" ? "person-detail" : "company-detail"}:${node.nif}`,
                            undefined,
                            { title: node.label },
                          )
                        }
                        className="flex min-h-[34px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-[11px] text-foreground transition hover:bg-white/[0.08]"
                      >
                        <ExternalLink size={12} />
                        Abrir ficha de {node.label}
                      </button>
                    )}
                    <div className="space-y-2">
                      {connected.map((edge, idx) => {
                        const otherId = edge.source === selectedNodeId ? edge.target : edge.source;
                        const other = graphData.nodes.find((n) => n.id === otherId);
                        // Cargos não são euros: só as arestas de contratos agregam
                        // valor monetário — as de cargo transportam a contagem.
                        const isContract = edge.type === "contract";
                        const money = typeof edge.value === "number" ? edge.value : 0;
                        const times =
                          typeof edge.count === "number" && edge.count > 0
                            ? edge.count
                            : !isContract && money > 0
                              ? money
                              : 0;
                        return (
                          <div key={idx} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                            <p className="font-medium">{edge.label || edge.role || "Ligação"}</p>
                            <p className="text-muted-foreground">{other?.label || otherId}</p>
                            {isContract && money > 0 && (
                              <p className="text-rose-200">
                                {money.toLocaleString("pt-PT", { style: "currency", currency: "EUR" })}
                              </p>
                            )}
                            {times > 1 && (
                              <p className="text-muted-foreground">
                                {times} {isContract ? "contratos" : "cargos/ocorrências"}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <NodeSummaryCard
                      nodeId={node.id}
                      nif={node.nif}
                      name={node.label}
                      kind={node.type}
                    />
                  </div>
                );
              })()
            ) : (
              <p className="text-xs text-muted-foreground">Clique num nó do grafo para ver detalhes e ligações.</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Análise 360 (dados públicos, risco, relações e ficha analítica)
// ---------------------------------------------------------------------------

/** Metadados de apresentação das fontes de recolha. */
const SOCIAL_SOURCES: { id: string; label: string; icon: React.ElementType; color: string }[] = [
  { id: "media", label: "Imagens e vídeos", icon: ImageIcon, color: "#fbbf24" },
  { id: "internet", label: "Internet", icon: Globe, color: "#34d399" },
  { id: "linkedin", label: "LinkedIn", icon: Briefcase, color: "#38bdf8" },
  { id: "tiktok", label: "TikTok", icon: Video, color: "#f472b6" },
  { id: "facebook", label: "Facebook", icon: Users, color: "#60a5fa" },
];

const RISK_TONE: Record<string, string> = {
  baixo: "#2dd4bf",
  "médio": "#fbbf24",
  alto: "#fb923c",
  "crítico": "#fb7185",
};

const STATUS_LABEL: Record<string, string> = {
  ok: "recolhido",
  empty: "sem resultados",
  blocked: "bloqueado",
  credentials: "precisa de credenciais",
  error: "erro",
  skipped: "não pedido",
};

const STATUS_COLOR: Record<string, string> = {
  ok: "text-teal-300 border-teal-400/25 bg-teal-400/10",
  empty: "text-muted-foreground border-white/10 bg-white/[0.04]",
  blocked: "text-amber-300 border-amber-400/25 bg-amber-400/10",
  credentials: "text-amber-300 border-amber-400/25 bg-amber-400/10",
  error: "text-rose-300 border-rose-400/25 bg-rose-400/10",
  skipped: "text-muted-foreground border-white/10 bg-white/[0.04]",
};

// `MARKDOWN_COMPONENTS` (render do Markdown da ficha/360) vive no kit partilhado.
function RiskMeter({ risk }: { risk: PersonRisk }) {
  const tone = RISK_TONE[risk.level] || "#fb7185";
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Pontuação de risco</p>
          <p className="text-3xl font-semibold" style={{ color: tone }}>
            {risk.score.toFixed(1)}
            <span className="ml-1 text-sm text-muted-foreground">/100</span>
          </p>
        </div>
        <div className="text-right text-xs">
          <p className="font-medium capitalize" style={{ color: tone }}>
            {risk.level}
          </p>
          <p className="text-muted-foreground">confiança {risk.confidence}</p>
        </div>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white/[0.08]">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, risk.score)}%`, background: tone }} />
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{risk.disclaimer}</p>
    </div>
  );
}

function SourceStatusRow({ result }: { result: PeopleSocialSourceResult }) {
  const [open, setOpen] = useState(false);
  const meta = SOCIAL_SOURCES.find((item) => item.id === result.source);
  const Icon = meta?.icon || Globe;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 text-left text-sm"
      >
        <Icon size={15} style={{ color: meta?.color || "#94a3b8" }} />
        <span className="font-medium">{result.label}</span>
        <span className={`ml-auto rounded-full border px-2 py-0.5 text-[11px] ${STATUS_COLOR[result.status] || STATUS_COLOR.empty}`}>
          {STATUS_LABEL[result.status] || result.status}
        </span>
      </button>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        {result.found} ligação(ões) encontrada(s) · {result.urls_checked} lida(s) · {result.items} item(ns) ·{" "}
        {result.indexed} guardado(s)
      </p>
      {open && (
        <div className="mt-2 space-y-2">
          {result.notes.length > 0 && (
            <ul className="space-y-1 text-[11px] text-amber-200/90">
              {result.notes.map((note, index) => (
                <li key={index} className="flex gap-1.5">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  <span className="break-words">{note}</span>
                </li>
              ))}
            </ul>
          )}
          {result.links.length > 0 && (
            <ul className="space-y-1 text-[11px]">
              {result.links.map((link, index) => (
                <li key={index} className="flex items-start gap-1.5">
                  <ExternalLink size={11} className="mt-0.5 shrink-0 text-muted-foreground" />
                  <a
                    className="truncate text-teal-300 hover:underline"
                    href={link.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    title={link.url || ""}
                  >
                    {link.title || link.url}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function MediaGallery({ social }: { social: PeopleSocialResponse | null }) {
  if (!social || (social.total === 0 && !social.images.length && !social.videos.length && !social.texts.length)) {
    return (
      <p className="text-xs text-muted-foreground">
        Ainda não há conteúdos recolhidos. Use «Obter dados das redes e da internet».
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {social.images.length > 0 && (
        <div>
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <ImageIcon size={13} /> Imagens ({social.images.length})
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {social.images.slice(0, 12).map((image: PeopleSocialItem, index: number) => (
              <a
                key={`${image.url}-${index}`}
                href={image.url || image.image || "#"}
                target="_blank"
                rel="noreferrer"
                className="group overflow-hidden rounded-lg border border-white/10"
                title={image.title || image.url || ""}
              >
                <img
                  src={image.image || ""}
                  alt={image.title || "imagem"}
                  loading="lazy"
                  className="h-24 w-full object-cover transition group-hover:opacity-80"
                  onError={(event) => {
                    (event.currentTarget as HTMLImageElement).style.visibility = "hidden";
                  }}
                />
                <span className="block truncate px-2 py-1 text-[10px] text-muted-foreground">
                  {image.platform || "web"}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}

      {social.videos.length > 0 && (
        <div>
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <Video size={13} /> Vídeos ({social.videos.length})
          </p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {social.videos.slice(0, 8).map((video: PeopleSocialItem, index: number) => (
              <a
                key={`${video.url}-${index}`}
                href={video.video || video.url || "#"}
                target="_blank"
                rel="noreferrer"
                className="group flex gap-2 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] p-2"
                title={video.title || video.url || ""}
              >
                {video.thumbnail && (
                  <img
                    src={video.thumbnail}
                    alt={video.title || "vídeo"}
                    loading="lazy"
                    className="h-14 w-24 shrink-0 rounded object-cover"
                    onError={(event) => {
                      (event.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                )}
                <span className="min-w-0 text-[11px]">
                  <span className="line-clamp-2 text-teal-200 group-hover:underline">{video.title || video.video || video.url}</span>
                  {video.platform && <span className="mt-0.5 block text-muted-foreground">{video.platform}</span>}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}

      {social.texts.length > 0 && (
        <div>
          <p className="text-xs font-medium text-foreground">Textos e publicações ({social.texts.length})</p>
          <ul className="mt-2 space-y-2">
            {social.texts.slice(0, 12).map((item: PeopleSocialItem, index: number) => (
              <li key={`${item.url}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="flex items-start justify-between gap-2">
                  <a className="text-xs font-medium text-foreground hover:text-teal-200" href={item.url || "#"} target="_blank" rel="noreferrer">
                    {item.title || item.url}
                  </a>
                  <span className="shrink-0 text-[10px] uppercase text-muted-foreground">{item.platform || "web"}</span>
                </div>
                {item.text && <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">{item.text}</p>}
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                  {item.date && <span>{formatDate(item.date)}</span>}
                  {item.sentiment && (
                    <span
                      className={
                        item.sentiment === "negativo"
                          ? "text-rose-300"
                          : item.sentiment === "positivo"
                            ? "text-teal-300"
                            : "text-muted-foreground"
                      }
                    >
                      tom {item.sentiment}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Dossier360Section({
  person,
  onPickNif,
}: {
  person: Person | null;
  onPickNif: (nif: string) => void;
}) {
  const [nifInput, setNifInput] = useState("");
  const [report, setReport] = useState<People360Response | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [withAi, setWithAi] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [collectResult, setCollectResult] = useState<PeopleSocialCollectResponse | null>(null);
  const [collectError, setCollectError] = useState<string | null>(null);
  const [chosenSources, setChosenSources] = useState<string[]>(SOCIAL_SOURCES.map((item) => item.id));
  const [layout, setLayout] = useState<"network" | "hierarchical" | "circular">("network");
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [copied, setCopied] = useState(false);

  const nif = person?.nif || "";

  const load = useCallback(async () => {
    if (!nif) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getPerson360(nif, { withAi, cireSize: 200, socialSize: 200 });
      setReport(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao obter a análise 360");
    } finally {
      setLoading(false);
    }
  }, [nif, withAi]);

  useEffect(() => {
    setReport(null);
    setCollectResult(null);
    setCollectError(null);
    if (nif) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nif]);

  const runCollect = async () => {
    if (!nif || chosenSources.length === 0) return;
    setCollecting(true);
    setCollectError(null);
    setCollectResult(null);
    try {
      const result = await collectPersonSocial(nif, { sources: chosenSources, limit: 6 });
      setCollectResult(result);
      await load();
    } catch (err) {
      setCollectError(err instanceof Error ? err.message : "Erro ao obter dados públicos");
    } finally {
      setCollecting(false);
    }
  };

  const toggleSource = (id: string) => {
    setChosenSources((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  const copyDossier = async () => {
    const text = report?.analysis?.text || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const graph = useMemo(() => combinedToStudioGraph(report?.graph ?? null), [report]);
  const social = (report?.social as unknown as PeopleSocialResponse) || null;
  const risk = report?.risk;

  if (!person) {
    return (
      <div className="space-y-4">
        <Card glow="rose" className="p-6">
          <h3 className="text-sm font-semibold">Análise 360 de uma pessoa</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Escolha uma pessoa na Pesquisa ou indique o NIF. A análise junta a ficha do societário, os processos
            de insolvência, o que é público nas redes e na internet, a pontuação de risco, o grafo de relações e a
            ficha analítica.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              value={nifInput}
              onChange={(event) => setNifInput(event.target.value)}
              placeholder="NIF da pessoa"
              className="min-h-[44px] w-[220px] rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
            />
            <button
              type="button"
              disabled={!nifInput.trim()}
              onClick={() => onPickNif(nifInput.trim())}
              className="min-h-[44px] rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-2 text-sm text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-40"
            >
              Abrir 360
            </button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card glow="rose" className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Análise 360</p>
            <h3 className="truncate text-lg font-semibold text-foreground">{person.name}</h3>
            <p className="text-xs text-muted-foreground">
              NIF {person.nif} · {person.is_company ? "pessoa coletiva" : "pessoa singular"} · {person.roles_count} cargo(s) ·{" "}
              {person.companies_count} empresa(s)
            </p>
            {report?.generated_at && (
              <p className="mt-0.5 text-[11px] text-muted-foreground">Gerado em {formatDate(report.generated_at)}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex min-h-[40px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-muted-foreground">
              <input type="checkbox" checked={withAi} onChange={(event) => setWithAi(event.target.checked)} />
              Ficha com IA
            </label>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="flex min-h-[40px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-foreground transition hover:bg-white/[0.07] disabled:opacity-40"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Atualizar
            </button>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-xs font-medium text-foreground">Obter dados públicos (redes sociais e internet)</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Pesquisa o nome (com o NIF e as empresas da ficha, para não trocar homónimos), lê as páginas públicas e
            guarda texto, imagem e vídeo na ficha. O que as plataformas bloquearem fica registado como ligação.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {SOCIAL_SOURCES.map((item) => {
              const Icon = item.icon;
              const active = chosenSources.includes(item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleSource(item.id)}
                  className={[
                    "flex min-h-[40px] items-center gap-1.5 rounded-xl border px-3 text-xs transition",
                    active
                      ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  <Icon size={14} style={{ color: active ? item.color : undefined }} />
                  {item.label}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => void runCollect()}
              disabled={collecting || chosenSources.length === 0}
              className="flex min-h-[40px] items-center gap-2 rounded-xl border border-teal-400/25 bg-teal-400/10 px-4 text-sm text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
            >
              {collecting ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {collecting ? "A recolher…" : "Obter dados"}
            </button>
          </div>
          {collecting && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              A pesquisar e a ler páginas públicas… pode demorar até um minuto.
            </p>
          )}
          {collectError && <p className="mt-2 text-[11px] text-rose-300">{collectError}</p>}
          {collectResult && (
            <div className="mt-3 space-y-2">
              <p className="text-[11px] text-muted-foreground">
                {collectResult.items_indexed} de {collectResult.items} item(ns) guardados em {collectResult.sources.length}{" "}
                fonte(s).
                {collectResult.engine_hint ? ` ${collectResult.engine_hint}` : ""}
              </p>
              <div className="grid gap-2 md:grid-cols-2">
                {collectResult.sources.map((result) => (
                  <SourceStatusRow key={result.source} result={result} />
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>

      {error && (
        <Card className="p-5">
          <p className="text-sm text-rose-300">{error}</p>
        </Card>
      )}

      {loading && !report && <Loading message="A construir a análise 360…" />}

      {report && risk && (
        <>
          <Card glow="rose" className="p-5">
            <div className="flex items-center gap-2">
              <ShieldAlert size={16} className="text-rose-300" />
              <h4 className="text-sm font-semibold">Risco</h4>
              <span className="ml-auto text-[11px] text-muted-foreground">
                {report.risk.risk_factors} fator(es) de risco · {report.risk.data_points} dados
              </span>
            </div>
            <div className="mt-3">
              <RiskMeter risk={risk} />
            </div>
            <ul className="mt-4 space-y-2">
              {risk.factors.map((factor) => {
                const positive = factor.points > 0;
                return (
                  <li key={factor.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-medium text-foreground">{factor.label}</p>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                          positive ? "bg-rose-400/10 text-rose-300" : "bg-teal-400/10 text-teal-300"
                        }`}
                      >
                        {positive ? "+" : ""}
                        {factor.points.toFixed(1)}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{factor.evidence}</p>
                  </li>
                );
              })}
            </ul>
          </Card>

          <Card className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <Network size={16} className="text-teal-300" />
              <h4 className="text-sm font-semibold">Grafo de relações</h4>
              <span className="text-[11px] text-muted-foreground">
                {report.graph.node_count} nós · {report.graph.edge_count} arestas ·{" "}
                {String(report.graph.meta?.companies ?? 0)} empresas ·{" "}
                {String(report.graph.meta?.co_intervenientes ?? 0)} co-intervenientes ·{" "}
                {String(report.graph.meta?.sites ?? 0)} sites
              </span>
              <div className="ml-auto flex items-center gap-2">
                {(["network", "hierarchical", "circular"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={layout === option}
                    onClick={() => {
                      setLayout(option);
                      setLayoutVersion((value) => value + 1);
                    }}
                    className={[
                      "min-h-[36px] rounded-xl px-3 text-xs transition",
                      layout === option
                        ? "glass-card text-teal-200 ring-1 ring-teal-400/30"
                        : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    {option === "network" ? "Rede" : option === "hierarchical" ? "Hierárquico" : "Circular"}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2">
              <NodeShapeLegend compact />
            </div>
            <div className="mt-3">
              {graph && graph.nodes.length > 1 ? (
                <GraphCanvas
                  graph={graph}
                  layout={layout}
                  metric={"contratos" as GraphMetric}
                  layoutVersion={layoutVersion}
                  heightClass="h-[46vh] min-h-[320px] max-h-[560px]"
                  unitLabel="ligações"
                />
              ) : (
                <p className="py-8 text-center text-xs text-muted-foreground">
                  Sem relações para desenhar (nem cargos, nem processos comuns, nem páginas).
                </p>
              )}
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex items-center gap-2">
              <Globe size={16} className="text-teal-300" />
              <h4 className="text-sm font-semibold">Presença digital</h4>
              <span className="ml-auto text-[11px] text-muted-foreground">
                {social?.total ?? 0} registo(s)
                {social?.last_collected ? ` · última recolha ${formatDate(social.last_collected)}` : ""}
              </span>
            </div>
            {social && social.by_platform.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                {social.by_platform.map((row) => (
                  <span key={row.key} className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-muted-foreground">
                    {row.key}: {row.count}
                  </span>
                ))}
                {typeof social.sentiment?.average_polarity === "number" && (
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-muted-foreground">
                    polaridade média {Number(social.sentiment.average_polarity).toFixed(2)}
                  </span>
                )}
              </div>
            )}
            <div className="mt-3">
              <MediaGallery social={social} />
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles size={16} className="text-teal-300" />
              <h4 className="text-sm font-semibold">Ficha analítica</h4>
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground">
                {report.analysis?.mode === "ai" ? "redigida por IA" : "apenas factos"}
              </span>
              <button
                type="button"
                onClick={() => void copyDossier()}
                className="ml-auto flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-foreground transition hover:bg-white/[0.07]"
              >
                {copied ? <Check size={13} className="text-teal-300" /> : <Copy size={13} />}
                {copied ? "Copiado" : "Copiar"}
              </button>
            </div>
            {(report.analysis?.notes?.length || report.analysis?.warnings?.length) && (
              <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                {(report.analysis.notes || []).map((note, index) => (
                  <li key={`note-${index}`}>· {note}</li>
                ))}
                {(report.analysis.warnings || []).map((warning, index) => (
                  <li key={`warn-${index}`} className="text-amber-200/90">
                    ! {warning}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-2">
              <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                {report.analysis?.text || "_Sem ficha analítica._"}
              </Markdown>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function IngestPanel() {
  const [nif, setNif] = useState("");
  const [result, setResult] = useState<PeopleIngestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cireLimit, setCireLimit] = useState<string>("");
  const [cireCompanies, setCireCompanies] = useState(false);
  const [cireJob, setCireJob] = useState<{ status: string; progress: Record<string, unknown>; result?: Record<string, unknown> | null } | null>(null);
  const [cireError, setCireError] = useState<string | null>(null);
  const [cireLoading, setCireLoading] = useState(false);

  const run = async () => {
    if (!nif.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await ingestPeopleForCompany(nif.trim());
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setLoading(false);
    }
  };

  const runCire = async () => {
    setCireLoading(true);
    setCireError(null);
    setCireJob(null);
    try {
      const parsed = cireLimit.trim() ? Number(cireLimit.trim()) : null;
      const job = await ingestPeopleFromCire({
        limit: parsed && parsed > 0 ? parsed : null,
        include_companies: cireCompanies,
        wait: true,
      });
      setCireJob({ status: job.status, progress: job.progress || {}, result: (job.result || null) as Record<string, unknown> | null });
      if (job.error) setCireError(job.error);
    } catch (err) {
      setCireError(err instanceof Error ? err.message : "Erro ao indexar pessoas do CIRE");
    } finally {
      setCireLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card glow="rose">
        <h3 className="text-sm font-semibold">Indexar pessoas/cargos por empresa</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Extrai pessoas e cargos das publicações societárias indexadas para o NIF indicado.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={nif}
            onChange={(e) => setNif(e.target.value)}
            placeholder="NIF da empresa"
            className="w-[200px] rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/50"
          />
          <button
            onClick={run}
            disabled={loading || !nif.trim()}
            className="rounded-xl bg-rose-400/10 px-3 py-2 text-sm text-rose-300 border border-rose-400/20 hover:bg-rose-400/20 transition disabled:opacity-40"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : "Indexar"}
          </button>
        </div>
        {result && (
          <p className="mt-3 text-xs text-teal-300">
            Indexados {result.indexed_count} registos a partir de {result.total} publicações.
          </p>
        )}
        {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
      </Card>

      <Card glow="blue">
        <h3 className="text-sm font-semibold">Indexar pessoas do CIRE (insolvências)</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Percorre as publicações do CIRE e transforma cada interveniente pessoa singular numa ficha com cargos
          (Credor, Insolvente, Administrador da insolvência, …). Os cargos do societário são preservados.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={cireLimit}
            onChange={(e) => setCireLimit(e.target.value)}
            placeholder="Limite de publicações (opcional)"
            className="w-[240px] rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/50"
          />
          <label className="flex min-h-[40px] items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={cireCompanies}
              onChange={(e) => setCireCompanies(e.target.checked)}
            />
            Incluir pessoas coletivas
          </label>
          <button
            onClick={() => void runCire()}
            disabled={cireLoading}
            className="flex min-h-[40px] items-center gap-2 rounded-xl border border-sky-400/20 bg-sky-400/10 px-3 py-2 text-sm text-sky-200 transition hover:bg-sky-400/20 disabled:opacity-40"
          >
            {cireLoading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={15} />}
            {cireLoading ? "A indexar…" : "Indexar pessoas do CIRE"}
          </button>
        </div>
        {cireLoading && (
          <p className="mt-3 text-xs text-muted-foreground">
            A percorrer as publicações do CIRE (sem limite, são ~164 mil) — pode demorar alguns minutos.
          </p>
        )}
        {cireJob?.result && (
          <p className="mt-3 text-xs text-teal-300">
            {String(cireJob.result.message || "")}
            {cireJob.result.message ? " " : ""}
            Indexadas {String(cireJob.result.indexed_count ?? 0)} fichas de {String(cireJob.result.publications ?? 0)}{" "}
            publicações ({String(cireJob.result.intervenientes ?? 0)} intervenientes).
          </p>
        )}
        {cireError && <p className="mt-3 text-xs text-rose-300">{cireError}</p>}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PessoasIQPage({ nif: nifProp }: { nif?: string } = {}) {
  const [section, setSection] = useState<PessoasIQSection>("dashboard");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<PeopleStatusResponse | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [selectedDevedor, setSelectedDevedor] = useState<DevedorFicha | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<PeopleCompanyItem | null>(null);
  const [companyDetail, setCompanyDetail] = useState<PeopleCompanyResponse | null>(null);
  const [companyLoading, setCompanyLoading] = useState(false);
  const [companyError, setCompanyError] = useState<string | null>(null);
  /**
   * Alvo empresa do grafo mostrado na secção «Grafo».
   *
   * Em modo janelas o grafo abre numa janela própria; em modo «ecrã inteiro» o
   * gestor de janelas não é renderizado (a janela ficava invisível), pelo que o
   * grafo passa a ser mostrado na própria página.
   */
  const [graphCompany, setGraphCompany] = useState<{ nif: string; name: string | null } | null>(null);
  const { windowMode } = useWindowMode();

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/people/status`);
      if (res.ok) setStatus(await res.json());
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  /**
   * Abre a ficha de empresa: a empresa e as pessoas com cargos nela.
   * Devolve o detalhe (ou lança) para quem precise de saber se a empresa existe.
   */
  const openCompany = useCallback(async (nif: string, name?: string | null) => {
    setSelectedCompany({ nif, name: name ?? null, people_count: 0, roles_count: 0 });
    setSelectedPerson(null);
    setCompanyDetail(null);
    setCompanyError(null);
    setDetailError(null);
    setCompanyLoading(true);
    try {
      const res = await getCompanyPeople(nif);
      setCompanyDetail(res);
      setSelectedCompany((prev) =>
        prev && prev.nif === nif
          ? { ...prev, name: res.name ?? prev.name, people_count: res.people.length }
          : prev,
      );
      if (!res.people.length && !res.name) {
        setCompanyError("Nenhuma pessoa com cargos indexados nesta empresa.");
      }
      return res;
    } catch (err) {
      setCompanyError(err instanceof Error ? err.message : "Erro ao obter a empresa");
      throw err;
    } finally {
      setCompanyLoading(false);
    }
  }, []);

  /**
   * Abre um NIF seja de onde for: ficha de pessoa → empresa com dados →
   * listas públicas de devedores.
   *
   * Há NIF que **só** existem nas listas de devedores (nem publicações
   * societárias, nem contratos, nem cargos): nesses casos mostra-se a ficha da
   * dívida — com o nome que a própria lista publica — em vez de «não encontrado».
   */
  const abrirNif = useCallback(
    async (nif: string, secao: PessoasIQSection = "search") => {
      if (!/^\d{9}$/.test(nif)) {
        setDetailError("NIF inválido (9 dígitos).");
        return;
      }
      setDetailLoading(true);
      setDetailError(null);
      try {
        const person = await getPerson(nif).catch(() => null);
        if (person) {
          setSelectedPerson(person);
          setSelectedCompany(null);
          setCompanyDetail(null);
          setSelectedDevedor(null);
          setSection(secao);
          return;
        }
        // A empresa do PessoasIQ só conta se tiver nome ou pessoas com cargos.
        const empresa = await openCompany(nif).catch(() => null);
        if (empresa && (empresa.people.length > 0 || empresa.name)) {
          setSelectedDevedor(null);
          setSection(secao);
          return;
        }
        const ficha = await devedorPorNif(nif).catch(() => null);
        if (ficha?.devedor) {
          setSelectedCompany(null);
          setCompanyDetail(null);
          setCompanyError(null);
          setSelectedPerson(null);
          setSelectedDevedor(ficha);
          setSection(secao);
          return;
        }
        if (empresa) {
          // Empresa conhecida, mas sem pessoas: fica o painel dela com o aviso.
          setSection(secao);
          return;
        }
        setDetailError(
          ficha?.error
            ? `Sem dados para o NIF ${nif}: ${ficha.error}`
            : `Sem dados para o NIF ${nif} (sem publicações societárias, contratos ou listas de devedores).`,
        );
        setSelectedDevedor(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [openCompany],
  );

  /**
   * Abre a ficha de uma pessoa: pelo NIF recebido em prop (janela `person-detail:`
   * aberta a partir do societário) ou pelo NIF no URL (`/pessoas-iq/<NIF>`).
   */
  useEffect(() => {
    const fromUrl = window.location.pathname.match(/^\/pessoas-iq\/([^/]+)$/);
    const nif = (nifProp || (fromUrl ? decodeURIComponent(fromUrl[1]) : "")).trim();
    if (!/^\d{9}$/.test(nif)) return;
    void abrirNif(nif, "search");
  }, [nifProp, abrirNif]);

  const handleSearchTopbar = () => {
    setSection("search");
  };

  const handleSelectPerson = (person: Person) => {
    setSelectedPerson(person);
    setSelectedCompany(null);
    setSelectedDevedor(null);
  };

  /** Pessoa escolhida dentro do painel de empresa: abre a ficha da pessoa. */
  const handlePickPersonFromCompany = useCallback(async (nif: string) => {
    setCompanyLoading(true);
    setCompanyError(null);
    try {
      const person = await getPerson(nif);
      setSelectedCompany(null);
      setCompanyDetail(null);
      setSelectedPerson(person);
    } catch (err) {
      setCompanyError(err instanceof Error ? err.message : "Erro ao obter a pessoa");
    } finally {
      setCompanyLoading(false);
    }
  }, []);

  const handleGraphForSelected = () => {
    // Modo janelas: grafo numa janela própria; senão, na secção da própria página.
    if (windowMode && selectedPerson?.nif) {
      openGraphWindow("person", selectedPerson.nif, selectedPerson.name);
      return;
    }
    setGraphCompany(null);
    setSection("graph");
  };

  /** Grafo de uma empresa (painel de empresa): janela própria ou secção da página. */
  const handleGraphForCompany = useCallback(
    (empresa: { nif: string; name?: string | null }) => {
      if (windowMode) {
        openGraphWindow("company", empresa.nif, empresa.name ?? null);
        return;
      }
      setGraphCompany({ nif: empresa.nif, name: empresa.name ?? null });
      setSection("graph");
    },
    [windowMode],
  );

  const handle360ForSelected = () => {
    setSection("score360");
  };

  /** Abre a ficha de uma pessoa pelo NIF (secção 360 sem pessoa selecionada). */
  const handlePickNif = useCallback(
    async (nif: string) => {
      await abrirNif(nif, "score360");
    },
    [abrirNif],
  );

  const content = useMemo(() => {
    if (detailLoading) return <Loading message="A carregar ficha…" />;
    if (detailError) {
      return (
        <Card className="p-8 text-center">
          <p className="text-rose-300">{detailError}</p>
        </Card>
      );
    }

    switch (section) {
      case "dashboard":
        return <DashboardSection status={status} onSection={setSection} />;
      case "search":
        return (
          <SearchSection
            initialQ={q}
            onSelectPerson={handleSelectPerson}
            onSelectNif={(value) => void abrirNif(value)}
            onSelectCompany={(empresa) => void openCompany(empresa.nif, empresa.name)}
          />
        );
      case "graph":
        return (
          <GraphSection
            key={graphCompany ? `empresa:${graphCompany.nif}` : `pessoa:${selectedPerson?.nif ?? ""}`}
            person={graphCompany ? null : selectedPerson}
            initialCompanyNif={graphCompany?.nif ?? ""}
            initialMode={graphCompany ? "company" : "person"}
            initialLabel={graphCompany?.name ?? null}
          />
        );
      case "score360":
        return <Dossier360Section person={selectedPerson} onPickNif={(value) => void handlePickNif(value)} />;
      case "devedores":
        return <DevedoresSection onPickNif={(value) => void handlePickNif(value)} />;
      case "settings":
        return <IngestPanel />;
      default:
        return null;
    }
  }, [detailError, detailLoading, q, section, selectedPerson, status, handlePickNif, openCompany, graphCompany]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background text-foreground orbit-bg">
      <Topbar q={q} setQ={setQ} onSearch={handleSearchTopbar} />
      <SectionTabs active={section} onChange={setSection} />
      <main className="@container min-w-0 flex-1 overflow-y-auto p-3 lg:p-6">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_minmax(0,420px)]">
          <div className={`min-w-0 ${section === "graph" || section === "score360" ? "lg:col-span-2" : "space-y-4"}`}>{content}</div>

          {selectedCompany && section !== "graph" && section !== "score360" && (
            <aside className="min-w-0 space-y-4">
              <Card glow="blue">
                <CompanyDetailPanel
                  company={selectedCompany}
                  detail={companyDetail}
                  loading={companyLoading}
                  error={companyError}
                  onClose={() => {
                    setSelectedCompany(null);
                    setCompanyDetail(null);
                    setCompanyError(null);
                  }}
                  onGraph={() =>
                    handleGraphForCompany({
                      nif: selectedCompany.nif,
                      name: selectedCompany.name ?? null,
                    })
                  }
                  onSelectPerson={(nif) => void handlePickPersonFromCompany(nif)}
                />
              </Card>
            </aside>
          )}

          {!selectedCompany && selectedPerson && section !== "graph" && section !== "score360" && (
            <aside className="min-w-0 space-y-4">
              <Card glow="rose">
                <PersonDetailPanel
                  person={selectedPerson}
                  onClose={() => setSelectedPerson(null)}
                  onGraph={handleGraphForSelected}
                  on360={handle360ForSelected}
                />
              </Card>
            </aside>
          )}

          {!selectedCompany && !selectedPerson && selectedDevedor && section !== "graph" && section !== "score360" && (
            <aside className="min-w-0 space-y-4">
              <Card>
                <DevedorFichaPanel
                  ficha={selectedDevedor}
                  onClose={() => setSelectedDevedor(null)}
                  onOpenTab={() => setSection("devedores")}
                />
              </Card>
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}
