/**
 * **Entidade para a Transparência** — declarações únicas dos titulares de
 * cargos políticos e altos cargos públicos.
 *
 * A pesquisa segue a cascata da própria plataforma: **entidade → cargo → nome
 * do titular**. Ao escolher um titular, abrem-se as suas declarações; cada uma
 * mostra as secções normalizadas (facto determinante, dados pessoais,
 * rendimentos, ativo, passivo) e o **registo de interesses** em tabela.
 *
 * A ficha do titular liga ao PessoasIQ (`/pessoas-iq/politicos?nif=…`), que é a
 * «ficha do político» da plataforma. Também aceita ligações diretas
 * (`?titular=<id>&declaracao=<id>`), usadas pelo separador de transparência
 * dessa mesma ficha.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  FileJson,
  FileText,
  Landmark,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
  UserRound,
  Users,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/Tabs";
import {
  eptEntidadeJsonUrl,
  eptExportIndiceUrl,
  eptExportUrl,
  exportarEpt,
  getEptCargos,
  getEptDeclaracao,
  getEptDeclaracoes,
  getEptEntidades,
  getEptJob,
  getEptMeta,
  getEptStats,
  getEptTitular,
  getEptTitulares,
  indexarEpt,
  recolherEpt,
  recolherEptTitular,
  type EptDeclaracao,
  type EptDeclaracaoResumo,
  type EptJob,
  type EptMeta,
  type EptOpcao,
  type EptSecao,
  type EptStats,
  type EptTitular,
} from "../entidadeTransparenciaApi";

type Aba = "pesquisa" | "recolha";

function norm(valor?: string | null): string {
  return (valor || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function dataCurta(valor?: string | null): string {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor.slice(0, 10);
  return data.toLocaleDateString("pt-PT");
}

function contagem(valor?: number | null): string {
  return (valor ?? 0).toLocaleString("pt-PT");
}

/** Link para a ficha do político no PessoasIQ. */
function perfilPoliticoUrl(nif?: string | null): string {
  return `/pessoas-iq/politicos${nif ? `?nif=${encodeURIComponent(nif)}` : ""}`;
}

/* ------------------------------------------------------------------ UI base */

function ValorCampo({ rotulo, valor }: { rotulo: string; valor: string | number | boolean | null }) {
  if (valor === null || valor === undefined || valor === "") return null;
  let texto = String(valor);
  if (typeof valor === "boolean") texto = valor ? "Sim" : "Não";
  return (
    <div className="min-w-0 rounded-lg border border-border/70 bg-muted/40 px-2.5 py-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{rotulo || "Campo"}</p>
      <p className="truncate text-xs text-foreground" title={texto}>
        {texto}
      </p>
    </div>
  );
}

function TabelaRegistos({ tabela }: { tabela: { nome: string; registos: Record<string, string>[]; total?: number } }) {
  if (!tabela.registos.length) return null;
  const colunas = Array.from(
    tabela.registos.reduce((set, registo) => {
      Object.keys(registo).forEach((chave) => set.add(chave));
      return set;
    }, new Set<string>()),
  );
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium text-foreground">
        {tabela.nome}
        <span className="ml-1.5 text-muted-foreground">({tabela.total ?? tabela.registos.length})</span>
      </p>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="min-w-full divide-y divide-border text-[11px]">
          <thead className="bg-muted/60">
            <tr>
              {colunas.map((coluna) => (
                <th key={coluna} className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium text-muted-foreground">
                  {coluna}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {tabela.registos.map((registo, indice) => (
              <tr key={indice} className="align-top">
                {colunas.map((coluna) => (
                  <td key={coluna} className="px-2.5 py-1.5 text-foreground">
                    {registo[coluna] ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SecaoDeclaracao({ secao, nivel = 0 }: { secao: EptSecao; nivel?: number }) {
  const vazia = !secao.campos.length && !secao.tabelas.length && !secao.subsecoes.length;
  if (vazia) return null;
  return (
    <div className={nivel === 0 ? "space-y-3" : "space-y-2"}>
      <p className={nivel === 0 ? "text-xs font-semibold text-foreground" : "text-[11px] font-medium text-foreground"}>
        {secao.titulo}
      </p>
      {secao.campos.length > 0 && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {secao.campos.map((campo) => (
            <ValorCampo key={campo.chave} rotulo={campo.rotulo} valor={campo.valor} />
          ))}
        </div>
      )}
      {secao.tabelas.map((tabela) => (
        <TabelaRegistos key={tabela.chave} tabela={tabela} />
      ))}
      {secao.subsecoes.length > 0 && (
        <div className="space-y-2 border-l border-border/70 pl-3">
          {secao.subsecoes.map((sub) => (
            <SecaoDeclaracao key={sub.chave} secao={sub} nivel={nivel + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Visualizador de uma declaração (secções + interesses). */
function DeclaracaoDetalhe({
  declaracao,
  loading,
  onClose,
}: {
  declaracao: EptDeclaracao | null;
  loading: boolean;
  onClose: () => void;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar a declaração…
      </div>
    );
  }
  if (!declaracao) return null;
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">
            Declaração {declaracao.declaracao_id} · {declaracao.ano || "—"}
          </p>
          <p className="text-[11px] text-muted-foreground">
            {declaracao.natureza || "—"} · {declaracao.estado || "—"} · entregue {dataCurta(declaracao.entrega)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-border p-1.5 text-muted-foreground transition hover:text-foreground"
          aria-label="Fechar declaração"
        >
          <X size={15} />
        </button>
      </div>

      <div className="grid gap-1.5 sm:grid-cols-2">
        <ValorCampo rotulo="Entidade" valor={declaracao.entidade ?? null} />
        <ValorCampo rotulo="Órgão" valor={declaracao.orgao ?? null} />
        <ValorCampo rotulo="Cargo" valor={declaracao.cargo ?? null} />
        <ValorCampo rotulo="Início" valor={dataCurta(declaracao.inicio)} />
        <ValorCampo rotulo="Fim" valor={dataCurta(declaracao.fim)} />
      </div>

      {declaracao.interesses?.length > 0 && (
        <div className="rounded-xl border border-emerald-400/25 bg-emerald-400/[0.06] p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-emerald-200">
            <ShieldCheck size={14} /> Registo de interesses
          </p>
          {(declaracao.interesses || []).map((interesse, indice) => (
            <div key={`${interesse.tipo}-${indice}`} className="mb-2 last:mb-0">
              <p className="text-[11px] font-medium text-foreground">{interesse.tipo}</p>
              <div className="mt-1 grid gap-1.5 sm:grid-cols-2">
                {Object.entries(interesse.valores).map(([chave, valor]) => (
                  <ValorCampo key={chave} rotulo={chave} valor={valor} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-4 border-t border-border pt-3">
        {(declaracao.secoes || []).map((secao) => (
          <SecaoDeclaracao key={secao.chave} secao={secao} />
        ))}
      </div>

      {declaracao.ao_vivo && (
        <p className="text-[10px] text-amber-300">
          Lida ao vivo da EPT (ainda não indexada). Recolhe o titular para guardar e pesquisar.
        </p>
      )}

      <a
        href="https://entidadetransparencia.pt/"
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-xs text-teal-300 hover:underline"
      >
        <ExternalLink size={13} /> Confirmar na plataforma da EPT
      </a>
    </div>
  );
}

/* --------------------------------------------------------------- Página */

export default function EntidadeTransparenciaPage() {
  const [aba, setAba] = useState<Aba>("pesquisa");
  const [meta, setMeta] = useState<EptMeta | null>(null);
  const [stats, setStats] = useState<EptStats | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const [entidades, setEntidades] = useState<EptOpcao[]>([]);
  const [filtroEntidade, setFiltroEntidade] = useState("");
  const [cargos, setCargos] = useState<EptOpcao[]>([]);
  const [entidadeId, setEntidadeId] = useState("");
  const [cargoId, setCargoId] = useState("");
  const [nome, setNome] = useState("");
  const [loadingCascata, setLoadingCascata] = useState(false);

  const [resultados, setResultados] = useState<EptOpcao[]>([]);
  const [totalResultados, setTotalResultados] = useState(0);
  const [pesquisouNome, setPesquisouNome] = useState(false);

  const [texto, setTexto] = useState("");
  const [resultadosTexto, setResultadosTexto] = useState<EptDeclaracaoResumo[]>([]);
  const [totalTexto, setTotalTexto] = useState(0);
  const [pesquisandoTexto, setPesquisandoTexto] = useState(false);
  const [pesquisouTexto, setPesquisouTexto] = useState(false);
  const [soInteresses, setSoInteresses] = useState(false);

  const [titular, setTitular] = useState<EptTitular | null>(null);
  const [titularLoading, setTitularLoading] = useState(false);

  const [declaracao, setDeclaracao] = useState<EptDeclaracao | null>(null);
  const [declaracaoLoading, setDeclaracaoLoading] = useState(false);

  const [job, setJob] = useState<EptJob | null>(null);
  const [limiteTitulares, setLimiteTitulares] = useState("");
  const [limiteDeclaracoes, setLimiteDeclaracoes] = useState("");
  const [forcar, setForcar] = useState(false);
  const [indexarNoFim, setIndexarNoFim] = useState(true);
  const [aRecolher, setARecolher] = useState(false);

  const pollRef = useRef<number | null>(null);

  /* ------------------------------------------------------------ carregar */

  const carregarResumo = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([getEptMeta(), getEptStats()]);
      setMeta(m);
      setStats(s);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao carregar o módulo");
    }
  }, []);

  const abrirTitular = useCallback(async (id: string, declaracaoId?: string | null) => {
    if (!id) return;
    setTitularLoading(true);
    setErro(null);
    try {
      const dados = await getEptTitular(id, { ao_vivo: true });
      setTitular(dados);
      const params = new URLSearchParams(window.location.search);
      params.set("titular", id);
      if (declaracaoId) params.set("declaracao", declaracaoId);
      else params.delete("declaracao");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
      if (declaracaoId) {
        void abrirDeclaracao(declaracaoId);
      } else {
        setDeclaracao(null);
      }
    } catch (err) {
      setTitular(null);
      setErro(err instanceof Error ? err.message : "Erro ao abrir o titular");
    } finally {
      setTitularLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const abrirDeclaracao = useCallback(async (id: string) => {
    setDeclaracaoLoading(true);
    try {
      const dados = await getEptDeclaracao(id);
      setDeclaracao(dados);
      const params = new URLSearchParams(window.location.search);
      if (params.get("titular")) params.set("declaracao", id);
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao abrir a declaração");
    } finally {
      setDeclaracaoLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregarResumo();
    (async () => {
      try {
        const resposta = await getEptEntidades();
        setEntidades(resposta.items);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao carregar as entidades");
      }
    })();
    const params = new URLSearchParams(window.location.search);
    const titularParam = params.get("titular");
    if (titularParam) {
      void abrirTitular(titularParam, params.get("declaracao"));
    } else {
      const nomeParam = params.get("nome");
      if (nomeParam) {
        setNome(nomeParam);
        setPesquisouNome(true);
        getEptTitulares({ q: nomeParam, size: 200 })
          .then((resposta) => {
            setResultados(resposta.items);
            setTotalResultados(resposta.total);
          })
          .catch(() => undefined);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Passo 1 → passo 2.
  useEffect(() => {
    setCargoId("");
    setResultados([]);
    setTotalResultados(0);
    if (!entidadeId) {
      setCargos([]);
      return;
    }
    let activo = true;
    setLoadingCascata(true);
    getEptCargos({ entidade_id: entidadeId })
      .then((resposta) => {
        if (activo) setCargos(resposta.items);
      })
      .catch((err) => {
        if (activo) setErro(err instanceof Error ? err.message : "Erro ao carregar os cargos");
      })
      .finally(() => {
        if (activo) setLoadingCascata(false);
      });
    return () => {
      activo = false;
    };
  }, [entidadeId]);

  // Passo 2 → passo 3.
  useEffect(() => {
    setResultados([]);
    setTotalResultados(0);
    if (!entidadeId && !cargoId) return;
    let activo = true;
    setLoadingCascata(true);
    getEptTitulares({ entidade_id: entidadeId || undefined, cargo_id: cargoId || undefined, size: 2000 })
      .then((resposta) => {
        if (!activo) return;
        setResultados(resposta.items);
        setTotalResultados(resposta.total);
      })
      .catch((err) => {
        if (activo) setErro(err instanceof Error ? err.message : "Erro ao carregar os titulares");
      })
      .finally(() => {
        if (activo) setLoadingCascata(false);
      });
    return () => {
      activo = false;
    };
  }, [entidadeId, cargoId]);

  // Pesquisa por nome sem entidade/cargo: usa o índice de titulares.
  const pesquisarNome = useCallback(async () => {
    if (!nome.trim()) return;
    setLoadingCascata(true);
    setErro(null);
    setPesquisouNome(true);
    try {
      const resposta = await getEptTitulares({
        entidade_id: entidadeId || undefined,
        cargo_id: cargoId || undefined,
        q: nome.trim(),
        size: 2000,
      });
      setResultados(resposta.items);
      setTotalResultados(resposta.total);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao pesquisar titulares");
    } finally {
      setLoadingCascata(false);
    }
  }, [nome, entidadeId, cargoId]);

  const visiveis = useMemo(() => {
    if (!nome.trim()) return resultados;
    const alvo = norm(nome);
    return resultados.filter((item) => norm(item.nome).includes(alvo));
  }, [resultados, nome]);

  const entidadesVisiveis = useMemo(() => {
    const alvo = norm(filtroEntidade);
    return alvo ? entidades.filter((entidade) => norm(entidade.nome).includes(alvo)) : entidades;
  }, [entidades, filtroEntidade]);

  const opcoesEntidade = useMemo(() => {
    const lista = entidadesVisiveis.slice(0, 300);
    if (entidadeId && !lista.some((entidade) => entidade.id === entidadeId)) {
      const selecionada = entidades.find((entidade) => entidade.id === entidadeId);
      if (selecionada) lista.unshift(selecionada);
    }
    return lista;
  }, [entidadesVisiveis, entidades, entidadeId]);

  const pesquisarTexto = useCallback(async () => {
    if (!texto.trim()) return;
    setPesquisandoTexto(true);
    setErro(null);
    setPesquisouTexto(true);
    try {
      const resposta = await getEptDeclaracoes({
        q: texto.trim(),
        com_interesses: soInteresses || undefined,
        sort: "relevance",
        size: 50,
      });
      setResultadosTexto(resposta.items);
      setTotalTexto(resposta.total);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro na pesquisa de declarações");
    } finally {
      setPesquisandoTexto(false);
    }
  }, [texto, soInteresses]);

  /* ------------------------------------------------------------- trabalhos */

  const acompanharJob = useCallback(
    (inicial: EptJob) => {
      setJob(inicial);
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (inicial.status !== "running") return;
      pollRef.current = window.setInterval(async () => {
        try {
          const actual = await getEptJob(inicial.job_id);
          setJob(actual);
          if (actual.status !== "running") {
            if (pollRef.current) window.clearInterval(pollRef.current);
            pollRef.current = null;
            void carregarResumo();
            if (titular) void abrirTitular(titular.titular.titular_id);
          }
        } catch {
          /* um poll falhado não interrompe o trabalho */
        }
      }, 2500);
    },
    [carregarResumo, abrirTitular, titular],
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const iniciarRecolha = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      const resposta = await recolherEpt({
        entidade_id: entidadeId || undefined,
        cargo_id: cargoId || undefined,
        limite_titulares: limiteTitulares ? Number(limiteTitulares) : undefined,
        limite_declaracoes: limiteDeclaracoes ? Number(limiteDeclaracoes) : undefined,
        forcar,
        indexar: indexarNoFim,
      });
      acompanharJob(resposta);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao iniciar a recolha");
    } finally {
      setARecolher(false);
    }
  }, [entidadeId, cargoId, limiteTitulares, limiteDeclaracoes, forcar, indexarNoFim, acompanharJob]);

  const iniciarIndexacao = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      const resposta = await indexarEpt(false);
      acompanharJob(resposta);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setARecolher(false);
    }
  }, [acompanharJob]);

  const iniciarExportacao = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      const resposta = await exportarEpt(entidadeId ? [entidadeId] : undefined);
      acompanharJob(resposta);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao exportar os JSON por entidade");
    } finally {
      setARecolher(false);
    }
  }, [entidadeId, acompanharJob]);

  const recolherTitular = useCallback(async () => {
    if (!titular) return;
    setARecolher(true);
    try {
      const resposta = await recolherEptTitular(titular.titular.titular_id);
      acompanharJob(resposta);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao recolher o titular");
    } finally {
      setARecolher(false);
    }
  }, [titular, acompanharJob]);

  /* --------------------------------------------------------------- render */

  const jobProgresso = useMemo(() => {
    const progresso = job?.progress || {};
    if (job?.tipo === "indexar") return progresso.registos ?? 0;
    if (progresso.titulares_total) {
      return Math.round(((progresso.titulares_done ?? 0) / progresso.titulares_total) * 100);
    }
    return 0;
  }, [job]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background text-foreground orbit-bg">
      <header className="border-b border-border bg-card/60 px-4 py-3 lg:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
              <ShieldCheck size={22} className="text-emerald-300" />
              Entidade para a Transparência
            </h1>
            <p className="text-xs text-muted-foreground">
              Declarações únicas de titulares de cargos políticos e altos cargos públicos
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{contagem(stats?.titulares)} titulares</Badge>
            <Badge variant="secondary">{contagem(stats?.declaracoes)} declarações</Badge>
            <Badge variant="secondary">{contagem(stats?.titularidades)} titularidades</Badge>
            <a
              href="https://entidadetransparencia.pt/"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              <ExternalLink size={13} /> EPT
            </a>
            <Button size="sm" variant="outline" icon={<RefreshCw size={13} />} onClick={() => void carregarResumo()}>
              Atualizar
            </Button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-3 lg:p-6">
        <Tabs value={aba} onValueChange={(valor) => setAba(valor as Aba)} className="space-y-4">
          <TabsList>
            <TabsTrigger value="pesquisa" active={aba === "pesquisa"} onClick={() => setAba("pesquisa")}>
              <Search size={13} className="mr-1 inline" /> Pesquisa
            </TabsTrigger>
            <TabsTrigger value="recolha" active={aba === "recolha"} onClick={() => setAba("recolha")}>
              <Database size={13} className="mr-1 inline" /> Recolha e índice
            </TabsTrigger>
          </TabsList>

          {erro && (
            <Card className="border-destructive/40">
              <p className="flex items-center gap-2 text-xs text-destructive">
                <TriangleAlert size={14} /> {erro}
              </p>
            </Card>
          )}

          <TabsContent value="pesquisa" active={aba === "pesquisa"} className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle icon={<Search size={15} />}>Pesquisar por entidade, cargo e nome</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-3">
                <div className="grid gap-3 lg:grid-cols-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="ept-entidade">1. Entidade</Label>
                    <Input
                      value={filtroEntidade}
                      onChange={(evento) => setFiltroEntidade(evento.target.value)}
                      placeholder="Filtrar entidades…"
                      autoComplete="off"
                      className="mb-1"
                    />
                    <select
                      id="ept-entidade"
                      value={entidadeId}
                      onChange={(evento) => setEntidadeId(evento.target.value)}
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                    >
                      <option value="">Todas as entidades ({contagem(entidades.length)})</option>
                      {opcoesEntidade.map((entidade) => (
                        <option key={entidade.id} value={entidade.id}>
                          {entidade.nome}
                        </option>
                      ))}
                    </select>
                    {entidadesVisiveis.length > opcoesEntidade.length && (
                      <p className="text-[10px] text-muted-foreground">
                        A mostrar {opcoesEntidade.length} de {contagem(entidadesVisiveis.length)} — refine o filtro.
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="ept-cargo">2. Cargo</Label>
                    <select
                      id="ept-cargo"
                      value={cargoId}
                      disabled={!entidadeId}
                      onChange={(evento) => setCargoId(evento.target.value)}
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
                    >
                      <option value="">{entidadeId ? `Todos os cargos (${contagem(cargos.length)})` : "Escolha primeiro a entidade"}</option>
                      {cargos.map((cargo) => (
                        <option key={cargo.id} value={cargo.id}>
                          {cargo.nome}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="ept-nome">3. Nome do titular</Label>
                    <div className="flex gap-2">
                      <Input
                        id="ept-nome"
                        value={nome}
                        onChange={(evento) => setNome(evento.target.value)}
                        onKeyDown={(evento) => {
                          if (evento.key === "Enter") {
                            evento.preventDefault();
                            void pesquisarNome();
                          }
                        }}
                        placeholder="Nome ou parte do nome…"
                        autoComplete="off"
                      />
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={<Search size={13} />}
                        loading={loadingCascata}
                        onClick={() => void pesquisarNome()}
                        disabled={!nome.trim()}
                      >
                        Procurar
                      </Button>
                    </div>
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  {entidadeId || cargoId
                    ? `A mostrar titulares da cascata${visiveis.length !== resultados.length ? ` (filtrados para ${visiveis.length})` : ""}.`
                    : pesquisouNome
                      ? `Pesquisa por nome: ${contagem(totalResultados)} titular(es).`
                      : "Escolha uma entidade e um cargo para percorrer os titulares, ou procure diretamente pelo nome."}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle icon={<FileText size={15} />}>Pesquisar no conteúdo das declarações</CardTitle>
                <a
                  href={eptExportUrl({ q: texto || undefined })}
                  className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  <Download size={12} /> CSV
                </a>
              </CardHeader>
              <CardContent className="mt-3 space-y-2">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <div className="flex flex-1 gap-2">
                    <Input
                      value={texto}
                      onChange={(evento) => setTexto(evento.target.value)}
                      onKeyDown={(evento) => {
                        if (evento.key === "Enter") {
                          evento.preventDefault();
                          void pesquisarTexto();
                        }
                      }}
                      placeholder="Ex.: nome de uma entidade, cargo, «IFRRU», valor ou descrição…"
                      autoComplete="off"
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Search size={13} />}
                      loading={pesquisandoTexto}
                      onClick={() => void pesquisarTexto()}
                      disabled={!texto.trim()}
                    >
                      Pesquisar
                    </Button>
                  </div>
                  <label className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={soInteresses} onChange={(evento) => setSoInteresses(evento.target.checked)} />
                    Só com registo de interesses
                  </label>
                </div>
                {resultadosTexto.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[11px] text-muted-foreground">
                      {contagem(totalTexto)} declaração(ões){totalTexto > resultadosTexto.length ? ` · a mostrar ${resultadosTexto.length}` : ""}
                    </p>
                    <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
                      {resultadosTexto.map((item) => (
                        <button
                          key={item.declaracao_id}
                          type="button"
                          onClick={() => item.titular_id && void abrirTitular(item.titular_id, item.declaracao_id)}
                          className="flex w-full items-center gap-2 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5 text-left transition hover:bg-accent/40"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs text-foreground">{item.titular || "—"}</span>
                            <span className="block truncate text-[10px] text-muted-foreground">
                              {item.ano || "—"} · {item.natureza || "—"} · {item.entidade || "—"}
                            </span>
                          </span>
                          {item.tem_registo_interesses && <ShieldCheck size={12} className="shrink-0 text-emerald-300" />}
                          <ArrowRight size={12} className="shrink-0 text-muted-foreground" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {!pesquisandoTexto && pesquisouTexto && totalTexto === 0 && resultadosTexto.length === 0 && (
                  <p className="text-[11px] text-muted-foreground">Sem resultados para «{texto}».</p>
                )}
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,560px)]">
              <div className="space-y-3">
                {loadingCascata && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 size={14} className="animate-spin" /> A carregar…
                  </div>
                )}
                {!loadingCascata && visiveis.length === 0 && (entidadeId || cargoId || pesquisouNome) && (
                  <Card>
                    <p className="text-xs text-muted-foreground">Sem titulares para esta combinação.</p>
                  </Card>
                )}
                <div className="grid gap-2 sm:grid-cols-2">
                  {visiveis.slice(0, 200).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => void abrirTitular(item.id)}
                      className={[
                        "flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition",
                        titular?.titular.titular_id === item.id
                          ? "border-emerald-400/40 bg-emerald-400/10"
                          : "border-border bg-card hover:border-emerald-400/30 hover:bg-accent/40",
                      ].join(" ")}
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                        <UserRound size={15} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-foreground">{item.nome}</span>
                        <span className="block truncate text-[10px] text-muted-foreground">
                          {(item as { declaracoes_total?: number }).declaracoes_total != null
                            ? `${contagem((item as { declaracoes_total?: number }).declaracoes_total)} declaração(ões)`
                            : `Id ${item.id}`}
                        </span>
                      </span>
                      <ArrowRight size={14} className="shrink-0 text-muted-foreground" />
                    </button>
                  ))}
                </div>
                {visiveis.length > 200 && (
                  <p className="text-[11px] text-muted-foreground">
                    A mostrar os primeiros 200 de {contagem(visiveis.length)}. Refine pela entidade, cargo ou nome.
                  </p>
                )}
              </div>

              <div className="space-y-4">
                {titularLoading && (
                  <Card>
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 size={14} className="animate-spin" /> A abrir a ficha do titular…
                    </p>
                  </Card>
                )}

                {titular && !titularLoading && (
                  <Card>
                    <CardHeader>
                      <CardTitle icon={<Landmark size={15} />}>{titular.titular.nome || "Titular"}</CardTitle>
                      <button
                        type="button"
                        onClick={() => {
                          setTitular(null);
                          setDeclaracao(null);
                          const params = new URLSearchParams(window.location.search);
                          params.delete("titular");
                          params.delete("declaracao");
                          window.history.replaceState(null, "", `${window.location.pathname}${params.toString() ? `?${params}` : ""}`);
                        }}
                        className="rounded-lg border border-border p-1.5 text-muted-foreground hover:text-foreground"
                        aria-label="Fechar ficha"
                      >
                        <X size={14} />
                      </button>
                    </CardHeader>
                    <CardContent className="mt-3 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">Id {titular.titular.titular_id}</Badge>
                        <Badge variant="secondary">{contagem(titular.titular.declaracoes_total ?? titular.declaracoes.total)} declarações</Badge>
                        {titular.titular.ultima_declaracao && (
                          <Badge variant="secondary">última em {dataCurta(titular.titular.ultima_declaracao)}</Badge>
                        )}
                      </div>

                      {titular.posicoes.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Cargos</p>
                          <div className="flex flex-wrap gap-1.5">
                            {Array.from(new Set(titular.posicoes.map((posicao) => `${posicao.cargo || "—"} · ${posicao.entidade || "—"}`)))
                              .slice(0, 8)
                              .map((texto) => (
                                <span key={texto} className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                                  {texto}
                                </span>
                              ))}
                          </div>
                        </div>
                      )}

                      {titular.pessoa.encontrado && titular.pessoa.pessoa?.nif ? (
                        <div className="space-y-1">
                          <a
                            href={perfilPoliticoUrl(titular.pessoa.pessoa.nif)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-xs text-emerald-200 transition hover:bg-emerald-400/20"
                          >
                            <Users size={13} /> Abrir ficha do político
                            <span className="text-[10px] text-emerald-300/80">
                              ({Math.round((titular.pessoa.pessoa.pontuacao ?? 0) * 100)}% de semelhança)
                            </span>
                          </a>
                          {titular.pessoa.ambiguo && (
                            <p className="text-[10px] text-amber-300">
                              Há mais do que uma pessoa com nome semelhante no PessoasIQ — confirme os candidatos antes de usar a ligação.
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="text-[10px] text-muted-foreground">
                          Sem correspondência segura no PessoasIQ (ligação por nome, para não trocar homónimos).
                        </p>
                      )}

                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          icon={<Download size={13} />}
                          loading={aRecolher && job?.tipo === "recolher"}
                          onClick={() => void recolherTitular()}
                        >
                          Recolher este titular
                        </Button>
                        <a
                          href={eptExportUrl({ titular_id: titular.titular.titular_id })}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                        >
                          <FileText size={13} /> CSV
                        </a>
                        {titular.posicoes[0]?.entidade_id && (
                          <a
                            href={eptEntidadeJsonUrl(titular.posicoes[0].entidade_id)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                          >
                            <FileJson size={13} /> JSON da entidade
                          </a>
                        )}
                      </div>

                      <div className="space-y-2 border-t border-border pt-3">
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          Declarações ({titular.declaracoes.items.length})
                        </p>
                        {titular.declaracoes.items.length === 0 && (
                          <p className="text-xs text-muted-foreground">
                            Sem declarações indexadas. Use «Recolher este titular» para as ler agora.
                          </p>
                        )}
                        <div className="space-y-1.5">
                          {titular.declaracoes.items.map((item: EptDeclaracaoResumo) => (
                            <button
                              key={item.declaracao_id}
                              type="button"
                              onClick={() => void abrirDeclaracao(item.declaracao_id)}
                              className={[
                                "flex w-full items-center gap-3 rounded-lg border px-2.5 py-2 text-left transition",
                                declaracao?.declaracao_id === item.declaracao_id
                                  ? "border-emerald-400/40 bg-emerald-400/10"
                                  : "border-border bg-muted/30 hover:bg-accent/40",
                              ].join(" ")}
                            >
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-xs text-foreground">
                                  {item.ano || "—"} · {item.natureza || "—"} · {item.cargo || "—"}
                                </span>
                                <span className="block truncate text-[10px] text-muted-foreground">
                                  {item.entidade || "—"} · entregue {dataCurta(item.entrega)}
                                </span>
                              </span>
                              {item.tem_registo_interesses && (
                                <ShieldCheck size={13} className="shrink-0 text-emerald-300" />
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {(declaracao || declaracaoLoading) && (
                  <Card>
                    <CardContent>
                      <DeclaracaoDetalhe
                        declaracao={declaracao}
                        loading={declaracaoLoading}
                        onClose={() => {
                          setDeclaracao(null);
                          const params = new URLSearchParams(window.location.search);
                          params.delete("declaracao");
                          window.history.replaceState(null, "", `${window.location.pathname}${params.toString() ? `?${params}` : ""}`);
                        }}
                      />
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="recolha" active={aba === "recolha"} className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle icon={<Database size={15} />}>Recolher e indexar</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-3">
                  <p className="text-[11px] text-muted-foreground">
                    A recolha percorre <strong>entidade → cargo → titular</strong> na plataforma da EPT, guarda as
                    declarações em JSONL e indexa em <code className="rounded bg-muted px-1">finance_ept_declaracoes</code>.
                    Sem entidade, percorre o catálogo completo (demorado: uma pausa por pedido).
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label htmlFor="ept-recolha-entidade">Entidade</Label>
                      <Input
                        value={filtroEntidade}
                        onChange={(evento) => setFiltroEntidade(evento.target.value)}
                        placeholder="Filtrar entidades…"
                        autoComplete="off"
                        className="mb-1"
                      />
                      <select
                        id="ept-recolha-entidade"
                        value={entidadeId}
                        onChange={(evento) => setEntidadeId(evento.target.value)}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                      >
                        <option value="">Todas</option>
                        {opcoesEntidade.map((entidade) => (
                          <option key={entidade.id} value={entidade.id}>
                            {entidade.nome}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="ept-recolha-cargo">Cargo</Label>
                      <select
                        id="ept-recolha-cargo"
                        value={cargoId}
                        disabled={!entidadeId}
                        onChange={(evento) => setCargoId(evento.target.value)}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
                      >
                        <option value="">Todos</option>
                        {cargos.map((cargo) => (
                          <option key={cargo.id} value={cargo.id}>
                            {cargo.nome}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="ept-limite-titulares">Máx. titulares</Label>
                      <Input
                        id="ept-limite-titulares"
                        type="number"
                        min={1}
                        value={limiteTitulares}
                        onChange={(evento) => setLimiteTitulares(evento.target.value)}
                        placeholder="Sem limite"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="ept-limite-declaracoes">Máx. declarações/titular</Label>
                      <Input
                        id="ept-limite-declaracoes"
                        type="number"
                        min={1}
                        value={limiteDeclaracoes}
                        onChange={(evento) => setLimiteDeclaracoes(evento.target.value)}
                        placeholder="Todas"
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-4 text-xs">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={forcar} onChange={(evento) => setForcar(evento.target.checked)} />
                      Reler o que já existe
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={indexarNoFim}
                        onChange={(evento) => setIndexarNoFim(evento.target.checked)}
                      />
                      Indexar no fim
                    </label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      icon={<Download size={13} />}
                      loading={aRecolher && job?.tipo === "recolher"}
                      onClick={() => void iniciarRecolha()}
                    >
                      Iniciar recolha
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Database size={13} />}
                      loading={aRecolher && job?.tipo === "indexar"}
                      onClick={() => void iniciarIndexacao()}
                    >
                      Indexar agora
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<FileJson size={13} />}
                      loading={aRecolher && job?.tipo === "exportar"}
                      onClick={() => void iniciarExportacao()}
                    >
                      Exportar JSON por entidade
                    </Button>
                  </div>

                  {job && (
                    <div className="space-y-2 rounded-xl border border-border bg-muted/30 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <Badge variant="secondary">{job.tipo}</Badge>
                        <span className="text-muted-foreground">{job.progress?.phase || job.status}</span>
                        {job.status === "running" && <Loader2 size={12} className="animate-spin text-muted-foreground" />}
                        {job.status === "done" && <CheckCircle2 size={12} className="text-emerald-300" />}
                        {job.status === "error" && <TriangleAlert size={12} className="text-destructive" />}
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-border">
                        <div
                          className="h-full rounded-full bg-emerald-400/70 transition-all"
                          style={{ width: `${Math.min(100, jobProgresso)}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-muted-foreground">
                        {job.tipo === "exportar"
                          ? `${contagem(job.progress?.registos)} entidade(s) exportada(s) em JSON`
                          : job.progress?.titulares_total
                            ? `${contagem(job.progress.titulares_done)} / ${contagem(job.progress.titulares_total)} titulares`
                            : `${contagem(job.progress?.registos)} registos`}
                        {job.tipo !== "exportar" && job.progress?.declaracoes
                          ? ` · ${contagem(job.progress.declaracoes)} declarações novas`
                          : ""}
                        {job.progress?.current ? ` · ${job.progress.current}` : ""}
                      </p>
                      {job.error && <p className="text-[10px] text-destructive">{job.error}</p>}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle icon={<Building2 size={15} />}>Estado do módulo</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-2 text-[11px] text-muted-foreground">
                  <div className="grid grid-cols-2 gap-2">
                    <ValorCampo rotulo="Entidades" valor={stats?.entidades ?? "—"} />
                    <ValorCampo rotulo="Cargos" valor={stats?.cargos ?? "—"} />
                    <ValorCampo rotulo="Titulares" valor={stats?.titulares ?? 0} />
                    <ValorCampo rotulo="Titularidades" valor={stats?.titularidades ?? 0} />
                    <ValorCampo rotulo="Declarações" valor={stats?.declaracoes ?? 0} />
                    <ValorCampo rotulo="Com interesses" valor={stats?.com_registo_interesses ?? 0} />
                  </div>
                  <p>
                    Índice: {stats?.fonte_indexada ? "Elasticsearch" : "disco (Elasticsearch indisponível)"} · atualizado{" "}
                    {dataCurta(stats?.atualizado_em)}
                  </p>
                  {meta && (
                    <>
                      <p className="break-all">
                        Dados: <code className="rounded bg-muted px-1">{meta.pasta}</code>
                      </p>
                      <p className="break-all">
                        JSON por entidade:{" "}
                        <a
                          href={eptExportIndiceUrl()}
                          target="_blank"
                          rel="noreferrer"
                          className="text-teal-300 hover:underline"
                        >
                          entidades/_index.json
                        </a>
                      </p>
                      <p className="break-all">
                        Índices:{" "}
                        {meta.indices.map((indice) => (
                          <code key={indice} className="mr-1 rounded bg-muted px-1">
                            {indice}
                          </code>
                        ))}
                      </p>
                      <p className="break-all">
                        Fonte:{" "}
                        <a href={meta.fonte_url} target="_blank" rel="noreferrer" className="text-teal-300 hover:underline">
                          {meta.fonte_url}
                        </a>
                      </p>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
