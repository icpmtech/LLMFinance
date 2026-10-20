/**
 * **Grafo da Transparência** — a rede das declarações únicas da EPT.
 *
 * Liga **pessoas → cargos → entidades públicas** e as **empresas** do registo de
 * interesses (atividades, filiação, sociedades, apoios e serviços prestados).
 * A sede de cada empresa é geocodificada a partir do «Local da sede», o que
 * permite ver **onde estão as empresas** no mapa.
 *
 * Quatro vistas: o grafo interativo, o mapa das sedes, a lista de empresas e a
 * construção/indexação do grafo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  Landmark,
  Layers,
  Loader2,
  MapPin,
  Maximize2,
  Network,
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
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { MapaEmpresas } from "../components/transparencia/MapaEmpresas";
import {
  TG_CORES,
  arestaResumo,
  legendaDe,
  noResumo,
  toStudioGraph,
  type TgStudioNode,
} from "../components/transparencia/grafo";
import {
  construirTg,
  getTgEmpresas,
  getTgGrafo,
  getTgJob,
  getTgMapa,
  getTgMeta,
  getTgNo,
  getTgStats,
  indexarTg,
  tgExportUrl,
  type TgEmpresa,
  type TgGrafoResposta,
  type TgJob,
  type TgMapaResposta,
  type TgMeta,
  type TgNoDetalhe,
  type TgStats,
} from "../transparenciaGrafoApi";

type Aba = "grafo" | "mapa" | "empresas" | "recolha";
type ModoMapa = "pontos" | "concelhos";

const ABAS: { id: Aba; label: string }[] = [
  { id: "grafo", label: "Grafo" },
  { id: "mapa", label: "Mapa das empresas" },
  { id: "empresas", label: "Empresas" },
  { id: "recolha", label: "Construção e índice" },
];

const TIPO_ICONE: Record<string, typeof Users> = {
  pessoa: UserRound,
  cargo: Layers,
  entidade: Landmark,
  empresa: Building2,
};

function contagem(valor?: number | null): string {
  return (valor ?? 0).toLocaleString("pt-PT");
}

function dataCurta(valor?: string | null): string {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor.slice(0, 10);
  return data.toLocaleDateString("pt-PT");
}

function anosTexto(anos?: number[]): string {
  if (!anos?.length) return "—";
  if (anos.length === 1) return String(anos[0]);
  return `${anos[0]}–${anos[anos.length - 1]}`;
}

function formatarDetalhe(detalhe: Record<string, unknown>): { rotulo: string; valor: string }[] {
  const rotulos: Record<string, string> = {
    entidades: "Entidade",
    funcao: "Cargo/função",
    inicio: "Início",
    fim: "Termo",
    remunerado: "Remuneração",
    objeto: "Objeto",
    percentagem: "Percentagem",
    quota: "Quota",
    apoio: "Apoio",
    descricao: "Descrição",
    servico: "Serviço",
    data: "Data",
    natureza: "Natureza",
    declaracao: "Declaração",
  };
  const saida: { rotulo: string; valor: string }[] = [];
  for (const [chave, valor] of Object.entries(detalhe || {})) {
    if (valor === null || valor === undefined || valor === "") continue;
    const texto = Array.isArray(valor) ? valor.filter(Boolean).join(", ") : String(valor);
    if (!texto) continue;
    saida.push({ rotulo: rotulos[chave] ?? chave, valor: texto });
  }
  return saida;
}

export default function TransparenciaGrafoPage() {
  const [aba, setAba] = useState<Aba>("grafo");
  const [meta, setMeta] = useState<TgMeta | null>(null);
  const [stats, setStats] = useState<TgStats | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  // Grafo
  const [filtroQ, setFiltroQ] = useState("");
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroRelacao, setFiltroRelacao] = useState("");
  const [filtroAno, setFiltroAno] = useState("");
  const [limite, setLimite] = useState(80);
  const [resposta, setResposta] = useState<TgGrafoResposta | null>(null);
  const [aCarregarGrafo, setACarregarGrafo] = useState(false);
  const [selecionado, setSelecionado] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<TgNoDetalhe | null>(null);
  const [fichaModal, setFichaModal] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);

  // Mapa
  const [modoMapa, setModoMapa] = useState<ModoMapa>("concelhos");
  const [mapa, setMapa] = useState<TgMapaResposta | null>(null);
  const [mapaQ, setMapaQ] = useState("");
  const [mapaTipo, setMapaTipo] = useState("empresa");
  const [concelhoAtivo, setConcelhoAtivo] = useState<string | null>(null);
  const [aCarregarMapa, setACarregarMapa] = useState(false);

  // Empresas
  const [empresas, setEmpresas] = useState<TgEmpresa[]>([]);
  const [empresasTotal, setEmpresasTotal] = useState(0);
  const [empresasQ, setEmpresasQ] = useState("");
  const [empresasPagina, setEmpresasPagina] = useState(0);
  const [aCarregarEmpresas, setACarregarEmpresas] = useState(false);
  const paginaTamanho = 40;

  // Trabalhos
  const [job, setJob] = useState<TgJob | null>(null);
  const [forcar, setForcar] = useState(false);
  const [indexar, setIndexar] = useState(true);
  const [limiteDeclaracoes, setLimiteDeclaracoes] = useState("");
  const [aArrancar, setAArrancar] = useState(false);
  const timerRef = useRef<number | null>(null);

  const grafo = useMemo(() => toStudioGraph(resposta), [resposta]);
  const legenda = useMemo(() => legendaDe(grafo), [grafo]);
  const nosGrafo = useMemo(() => (grafo?.nodes ?? []) as TgStudioNode[], [grafo]);

  const carregarResumo = useCallback(async () => {
    try {
      const [metaAtual, statsAtual] = await Promise.all([getTgMeta(), getTgStats()]);
      setMeta(metaAtual);
      setStats(statsAtual);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao ler o estado do módulo");
    }
  }, []);

  const carregarGrafo = useCallback(
    async (opcoes?: { foco?: string; limpar?: boolean }) => {
      setACarregarGrafo(true);
      try {
        const dados = await getTgGrafo({
          q: opcoes?.limpar ? undefined : filtroQ || undefined,
          tipo: opcoes?.limpar ? undefined : filtroTipo || undefined,
          relacao: opcoes?.limpar ? undefined : filtroRelacao || undefined,
          ano: opcoes?.limpar ? undefined : filtroAno ? Number(filtroAno) : undefined,
          limit: limite,
          foco: opcoes?.foco,
          profundidade: opcoes?.foco ? 2 : 1,
        });
        setResposta(dados);
        setLayoutVersion((valor) => valor + 1);
        if (dados.error) setErro(dados.error);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao construir o grafo");
      } finally {
        setACarregarGrafo(false);
      }
    },
    [filtroAno, filtroQ, filtroRelacao, filtroTipo, limite],
  );

  const abrirNo = useCallback(async (noId: string) => {
    setSelecionado(noId);
    setDetalhe(null);
    try {
      setDetalhe(await getTgNo(noId));
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao abrir o nó");
    }
  }, []);

  const carregarMapa = useCallback(
    async (concelho?: string) => {
      setACarregarMapa(true);
      setConcelhoAtivo(concelho ?? null);
      try {
        setMapa(
          await getTgMapa({
            q: mapaQ || undefined,
            concelho,
            tipo: mapaTipo,
            limite_pontos: 1500,
          }),
        );
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao carregar o mapa");
      } finally {
        setACarregarMapa(false);
      }
    },
    [mapaQ, mapaTipo],
  );

  const carregarEmpresas = useCallback(
    async (pagina = 0) => {
      setACarregarEmpresas(true);
      try {
        const dados = await getTgEmpresas({
          q: empresasQ || undefined,
          limit: paginaTamanho,
          offset: pagina * paginaTamanho,
          ordenar: "grau",
        });
        setEmpresas(dados.items);
        setEmpresasTotal(dados.total);
        setEmpresasPagina(pagina);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao listar empresas");
      } finally {
        setACarregarEmpresas(false);
      }
    },
    [empresasQ],
  );

  const acompanharJob = useCallback((inicial: TgJob) => {
    setJob(inicial);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = window.setInterval(async () => {
      try {
        const atual = await getTgJob(inicial.job_id);
        setJob(atual);
        if (atual.status !== "running") {
          if (timerRef.current) window.clearInterval(timerRef.current);
          timerRef.current = null;
          await carregarResumo();
          await carregarGrafo();
          await carregarMapa();
        }
      } catch {
        if (timerRef.current) window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }, 1200);
  }, [carregarGrafo, carregarMapa, carregarResumo]);

  useEffect(() => {
    if (!fichaModal) return;
    const fechar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") setFichaModal(false);
    };
    window.addEventListener("keydown", fechar);
    return () => window.removeEventListener("keydown", fechar);
  }, [fichaModal]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const abaInicial = params.get("aba");
    if (abaInicial && ABAS.some((item) => item.id === abaInicial)) setAba(abaInicial as Aba);
    const noInicial = params.get("no");
    if (noInicial) void abrirNo(noInicial);
    void carregarResumo();
    void carregarGrafo();
    void carregarMapa();
    void carregarEmpresas(0);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
    // Só no arranque; as vistas seguintes são pedidas pelos controlos.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const iniciarConstrucao = async () => {
    setAArrancar(true);
    setErro(null);
    try {
      const respostaJob = await construirTg({
        forcar,
        indexar,
        limite_declaracoes: limiteDeclaracoes ? Number(limiteDeclaracoes) : null,
      });
      acompanharJob(respostaJob);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao arrancar a construção");
    } finally {
      setAArrancar(false);
    }
  };

  const iniciarIndexacao = async () => {
    setAArrancar(true);
    setErro(null);
    try {
      acompanharJob(await indexarTg());
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setAArrancar(false);
    }
  };

  const limparFiltros = () => {
    setFiltroQ("");
    setFiltroTipo("");
    setFiltroRelacao("");
    setFiltroAno("");
    void carregarGrafo({ limpar: true });
  };

  const erros = erro ? (
    <Card className="border-destructive/40">
      <p className="flex items-center gap-2 text-xs text-destructive">
        <TriangleAlert size={14} /> {erro}
        <button type="button" className="ml-auto opacity-70 hover:opacity-100" onClick={() => setErro(null)}>
          <X size={13} />
        </button>
      </p>
    </Card>
  ) : null;

  const jobProgresso = useMemo(() => {
    const progresso = job?.progress || {};
    if (progresso.registos) return Math.min(100, Math.round((progresso.registos / Math.max(1, stats?.nos ?? 1)) * 100));
    if (progresso.titularidades) return 60;
    if (progresso.declaracoes) return 30;
    return job?.status === "running" ? 8 : 0;
  }, [job, stats?.nos]);

  /** Conteúdo da ficha do nó — usado no painel lateral e no modal. */
  const renderFicha = () => {
    if (!selecionado) {
      return (
        <div className="space-y-3 text-[11.5px] text-muted-foreground">
          <p>Selecione um nó no grafo para ver a ficha, as ligações e a origem. Pode arrastar os nós para os organizar.</p>
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-wide">Nós mais ligados neste grafo</p>
            {nosGrafo.slice(0, 12).map((no) => (
              <button
                key={no.id}
                type="button"
                onClick={() => void abrirNo(no.id)}
                className="flex w-full items-center gap-2 rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5 text-left hover:bg-muted/60"
              >
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: no.color }} />
                <span className="min-w-0 flex-1 truncate text-foreground">{no.label}</span>
                <span className="shrink-0 text-[10px]">{no.grau}</span>
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (!detalhe) {
      return (
        <p className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> a abrir…
        </p>
      );
    }
    return (
      <div className="space-y-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
            {(() => {
              const Icone = TIPO_ICONE[detalhe.no.tipo] ?? Layers;
              return <Icone size={15} style={{ color: TG_CORES[detalhe.no.tipo] }} />;
            })()}
            <span className="min-w-0 break-words">{detalhe.no.nome}</span>
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
            <Badge variant="secondary">{meta?.tipos?.[detalhe.no.tipo]?.curto ?? detalhe.no.tipo}</Badge>
            {detalhe.no.nif && <span>NIF {detalhe.no.nif}</span>}
            {detalhe.no.anos?.length ? <span>· {anosTexto(detalhe.no.anos)}</span> : null}
          </p>
        </div>

        {detalhe.no.local_sede && (
          <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5 text-[11px]">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Sede</p>
            <p className="text-foreground">{detalhe.no.concelho ?? detalhe.no.local_sede}</p>
            <p className="text-[10px] text-muted-foreground">
              {detalhe.no.local_sede}
              {detalhe.no.precisao_geo ? ` · ${meta?.precisoes?.[detalhe.no.precisao_geo] ?? detalhe.no.precisao_geo}` : ""}
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Ligações</p>
            <p className="text-foreground">{contagem(detalhe.no.grau)}</p>
          </div>
          <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Declarações</p>
            <p className="text-foreground">{contagem(detalhe.no.declaracoes)}</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="outline"
            icon={<Network size={12} />}
            onClick={() => {
              setAba("grafo");
              void carregarGrafo({ foco: detalhe.no.no_id });
            }}
          >
            Expandir no grafo
          </Button>
          {detalhe.no.tipo === "pessoa" && (
            <a
              href={`/entidade-transparencia?titular=${encodeURIComponent(detalhe.no.ref_id ?? "")}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink size={12} /> Declarações
            </a>
          )}
          {detalhe.no.tipo === "empresa" && (
            <a
              href={`/empresas-iq/${encodeURIComponent(detalhe.no.nif ?? "")}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <ExternalLink size={12} /> EmpresasIQ
            </a>
          )}
          <button
            type="button"
            onClick={() => setFichaModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <Maximize2 size={12} /> Abrir em janela
          </button>
        </div>

        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {contagem(detalhe.total_vizinhos)} ligações
          </p>
          {detalhe.vizinhos.map((vizinho, indice) => {
            const Icone = TIPO_ICONE[vizinho.no.type] ?? Layers;
            return (
              <button
                key={`${vizinho.no.id}-${vizinho.relacao}-${indice}`}
                type="button"
                onClick={() => void abrirNo(vizinho.no.id)}
                className="w-full rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5 text-left hover:bg-muted/60"
              >
                <p className="flex items-center gap-1.5 text-[11.5px] text-foreground">
                  <Icone size={12} style={{ color: TG_CORES[vizinho.no.type] }} />
                  <span className="min-w-0 flex-1 truncate">{vizinho.no.label}</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">×{vizinho.peso}</span>
                </p>
                <p className="pl-4 text-[10px] text-muted-foreground">
                  {vizinho.sentido === "saida" ? vizinho.relacao_label : `← ${vizinho.relacao_label}`}
                  {vizinho.anos.length ? ` · ${anosTexto(vizinho.anos)}` : ""}
                </p>
                {formatarDetalhe(vizinho.detalhe).slice(0, 3).map((item) => (
                  <p key={item.rotulo} className="truncate pl-4 text-[9.5px] text-muted-foreground/80">
                    {item.rotulo}: {item.valor}
                  </p>
                ))}
              </button>
            );
          })}
          {!detalhe.vizinhos.length && (
            <p className="text-[11px] text-muted-foreground">
              Este nó não tem ligações no grafo (aparece apenas como referência).
            </p>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background text-foreground orbit-bg">
      <header className="border-b border-border bg-card/60 px-4 py-3 lg:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
              <Network size={22} className="text-teal-300" />
              Grafo da Transparência
            </h1>
            <p className="text-xs text-muted-foreground">
              Pessoas, cargos, entidades públicas e empresas das declarações únicas da EPT — com o mapa das sedes
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{contagem(stats?.nos)} nós</Badge>
            <Badge variant="secondary">{contagem(stats?.arestas)} arestas</Badge>
            <Badge variant="secondary">{contagem(stats?.empresas)} empresas</Badge>
            <Badge variant="secondary">{contagem(stats?.com_geo)} com sede no mapa</Badge>
            <a
              href="/entidade-transparencia"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              <ShieldCheck size={13} /> Declarações
            </a>
            <Button
              size="sm"
              variant="outline"
              icon={<RefreshCw size={13} />}
              onClick={() => {
                void carregarResumo();
                void carregarGrafo();
                void carregarMapa();
                void carregarEmpresas(empresasPagina);
              }}
            >
              Atualizar
            </Button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-3 lg:p-6">
        <Tabs value={aba} onValueChange={(valor) => setAba(valor as Aba)} className="space-y-4">
          <TabsList>
            <TabsTrigger value="grafo" active={aba === "grafo"} onClick={() => setAba("grafo")}>
              <Network size={13} className="mr-1 inline" /> Grafo
            </TabsTrigger>
            <TabsTrigger value="mapa" active={aba === "mapa"} onClick={() => setAba("mapa")}>
              <MapPin size={13} className="mr-1 inline" /> Mapa das empresas
            </TabsTrigger>
            <TabsTrigger value="empresas" active={aba === "empresas"} onClick={() => setAba("empresas")}>
              <Building2 size={13} className="mr-1 inline" /> Empresas
            </TabsTrigger>
            <TabsTrigger value="recolha" active={aba === "recolha"} onClick={() => setAba("recolha")}>
              <Database size={13} className="mr-1 inline" /> Construção e índice
            </TabsTrigger>
          </TabsList>

          {erros}

          {/* ------------------------------------------------------------ grafo */}
          <TabsContent value="grafo" active={aba === "grafo"} className="space-y-4">
            <Card>
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(evento) => {
                  evento.preventDefault();
                  void carregarGrafo();
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="tg-q">Pesquisar</Label>
                  <div className="relative">
                    <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="tg-q"
                      value={filtroQ}
                      onChange={(evento) => setFiltroQ(evento.target.value)}
                      placeholder="nome, NIF ou concelho…"
                      autoComplete="off"
                      className="pl-7"
                    />
                  </div>
                </div>
                <div className="w-[150px]">
                  <Label htmlFor="tg-tipo">Tipo de nó</Label>
                  <select
                    id="tg-tipo"
                    value={filtroTipo}
                    onChange={(evento) => setFiltroTipo(evento.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                  >
                    <option value="">Todos</option>
                    {Object.entries(meta?.tipos ?? {}).map(([chave, info]) => (
                      <option key={chave} value={chave}>
                        {info.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="w-[170px]">
                  <Label htmlFor="tg-relacao">Relação</Label>
                  <select
                    id="tg-relacao"
                    value={filtroRelacao}
                    onChange={(evento) => setFiltroRelacao(evento.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                  >
                    <option value="">Todas</option>
                    {Object.entries(meta?.relacoes ?? {}).map(([chave, info]) => (
                      <option key={chave} value={chave}>
                        {info.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="w-[100px]">
                  <Label htmlFor="tg-ano">Ano</Label>
                  <Input
                    id="tg-ano"
                    type="number"
                    min={1990}
                    max={2100}
                    value={filtroAno}
                    onChange={(evento) => setFiltroAno(evento.target.value)}
                    placeholder="Todos"
                  />
                </div>
                <div className="w-[110px]">
                  <Label htmlFor="tg-nos">Nós</Label>
                  <select
                    id="tg-nos"
                    value={limite}
                    onChange={(evento) => setLimite(Number(evento.target.value))}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                  >
                    {[30, 60, 80, 120, 200, 300].map((opcao) => (
                      <option key={opcao} value={opcao}>
                        {opcao}
                      </option>
                    ))}
                  </select>
                </div>
                <Button type="submit" size="sm" icon={<Search size={13} />} loading={aCarregarGrafo}>
                  Construir grafo
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={limparFiltros}>
                  Limpar
                </Button>
              </form>
              <p className="mt-2 text-[10.5px] text-muted-foreground">
                {resposta?.meta?.documents_scanned
                  ? `${contagem(resposta.meta.documents_matching)} nós correspondem ao filtro, de ${contagem(
                      resposta.meta.total_nos,
                    )} no grafo · ${contagem(resposta.meta.total_arestas)} arestas no total`
                  : "O grafo lê as declarações da EPT já recolhidas."}
              </p>
            </Card>

            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
              <Card padding="none" className="relative overflow-hidden">
                <GraphCanvas
                  graph={grafo}
                  layout="network"
                  metric="contratos"
                  unitLabel="ligações"
                  selectedNodeId={selecionado}
                  loading={aCarregarGrafo}
                  layoutVersion={layoutVersion}
                  heightClass="h-[560px]"
                  labels="auto"
                  nodeSummary={noResumo}
                  edgeSummary={arestaResumo}
                  onNodeClick={(no) => {
                    setFichaModal(true);
                    void abrirNo(no.id);
                  }}
                />
                <div className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-2">
                  {legenda.map((item) => (
                    <span key={item.key} className="inline-flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
                      {item.label} · {item.total}
                    </span>
                  ))}
                  <button
                    type="button"
                    onClick={() => setLayoutVersion((valor) => valor + 1)}
                    className="ml-auto text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Reorganizar
                  </button>
                </div>
              </Card>

              <Card className="flex min-h-[560px] flex-col !p-0">
                <CardHeader className="border-b border-border px-3 py-2">
                  <CardTitle icon={<Layers size={14} />}>Ficha do nó</CardTitle>
                  {selecionado && (
                    <span className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setFichaModal(true)}
                        className="text-muted-foreground hover:text-foreground"
                        aria-label="Abrir ficha em janela"
                        title="Abrir ficha em janela"
                      >
                        <Maximize2 size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSelecionado(null);
                          setDetalhe(null);
                        }}
                        className="text-muted-foreground hover:text-foreground"
                        aria-label="Fechar ficha"
                      >
                        <X size={14} />
                      </button>
                    </span>
                  )}
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-y-auto p-3">{renderFicha()}</CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* ------------------------------------------------------------- mapa */}
          <TabsContent value="mapa" active={aba === "mapa"} className="space-y-4">
            <Card>
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(evento) => {
                  evento.preventDefault();
                  void carregarMapa();
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="tg-mapa-q">Pesquisar empresas</Label>
                  <div className="relative">
                    <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="tg-mapa-q"
                      value={mapaQ}
                      onChange={(evento) => setMapaQ(evento.target.value)}
                      placeholder="nome, NIF ou concelho…"
                      autoComplete="off"
                      className="pl-7"
                    />
                  </div>
                </div>
                <div className="w-[160px]">
                  <Label htmlFor="tg-mapa-tipo">Entidades no mapa</Label>
                  <select
                    id="tg-mapa-tipo"
                    value={mapaTipo}
                    onChange={(evento) => setMapaTipo(evento.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                  >
                    <option value="empresa">Empresas</option>
                    <option value="entidade">Entidades públicas</option>
                    <option value="empresa,entidade">Empresas e entidades</option>
                  </select>
                </div>
                <div className="flex items-center gap-1 rounded-lg border border-border p-0.5">
                  {(["concelhos", "pontos"] as ModoMapa[]).map((modo) => (
                    <button
                      key={modo}
                      type="button"
                      onClick={() => setModoMapa(modo)}
                      className={`rounded-md px-2.5 py-1.5 text-[11px] ${
                        modoMapa === modo ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {modo === "concelhos" ? "Por concelho" : "Por empresa"}
                    </button>
                  ))}
                </div>
                <Button type="submit" size="sm" icon={<MapPin size={13} />} loading={aCarregarMapa}>
                  Atualizar mapa
                </Button>
                <a
                  href={tgExportUrl({ vista: "empresas", q: mapaQ || undefined, tipo: mapaTipo })}
                  className="mb-0.5 inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Download size={13} /> CSV
                </a>
              </form>
              <p className="mt-2 text-[10.5px] text-muted-foreground">
                {mapa
                  ? `${contagem(mapa.total)} empresa(s) com sede resolvida · ${contagem(mapa.total_concelhos)} concelho(s) · ${contagem(
                      mapa.sem_geo,
                    )} sem coordenadas (não são colocadas no mapa; listadas abaixo)`
                  : "A sede vem do «Local da sede» do registo de interesses, resolvida para o concelho."}
              </p>
              {concelhoAtivo && (
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant="info">
                    Concelho: {concelhoAtivo}
                    <button
                      type="button"
                      onClick={() => void carregarMapa()}
                      className="ml-1 opacity-70 hover:opacity-100"
                      aria-label="Limpar filtro de concelho"
                    >
                      <X size={11} />
                    </button>
                  </Badge>
                  <button
                    type="button"
                    onClick={() => void carregarMapa()}
                    className="text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    ver todos os concelhos
                  </button>
                </div>
              )}
            </Card>

            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
              <Card padding="none" className="overflow-hidden">
                <MapaEmpresas
                  pontos={mapa?.pontos ?? []}
                  concelhos={mapa?.concelhos ?? []}
                  modo={modoMapa}
                  onSelecionar={(ponto) => {
                    if (ponto.id.startsWith("concelho:")) {
                      void carregarMapa(ponto.nome);
                    } else {
                      void abrirNo(ponto.id);
                      setAba("grafo");
                    }
                  }}
                />
              </Card>

              <Card className="!p-0">
                <CardHeader className="border-b border-border px-3 py-2">
                  <CardTitle icon={<MapPin size={14} />}>Concelhos com mais empresas</CardTitle>
                </CardHeader>
                <CardContent className="max-h-[480px] overflow-y-auto p-3">
                  {(mapa?.concelhos ?? []).map((item) => {
                    const maximo = Math.max(1, ...(mapa?.concelhos ?? []).map((outro) => outro.empresas));
                    return (
                      <button
                        key={item.concelho}
                        type="button"
                        onClick={() => void carregarMapa(item.concelho)}
                        className="mb-1.5 w-full text-left"
                        title={`Ver apenas ${item.concelho}`}
                      >
                        <span className="flex items-center justify-between text-[11px] text-foreground">
                          <span className="truncate">{item.concelho}</span>
                          <span className="ml-2 shrink-0 tabular-nums text-muted-foreground">{contagem(item.empresas)}</span>
                        </span>
                        <span className="mt-0.5 block h-1 overflow-hidden rounded-full bg-border">
                          <span
                            className="block h-full rounded-full bg-sky-400/70"
                            style={{ width: `${Math.max(4, Math.round((item.empresas / maximo) * 100))}%` }}
                          />
                        </span>
                      </button>
                    );
                  })}
                  {!mapa?.concelhos?.length && (
                    <p className="text-[11px] text-muted-foreground">Sem concelhos para os filtros atuais.</p>
                  )}
                  <button
                    type="button"
                    onClick={() => void carregarMapa()}
                    className="mt-2 text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Limpar filtro de concelho
                  </button>
                </CardContent>
              </Card>
            </div>

            {mapa && mapa.sem_geo > 0 && (
              <Card padding="none" className="overflow-hidden">
                <CardHeader className="border-b border-border px-3 py-2">
                  <CardTitle icon={<MapPin size={14} />}>
                    Sem coordenadas
                    <Badge variant="warning" className="ml-2">{contagem(mapa.sem_geo)}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <p className="border-b border-border px-3 py-2 text-[10.5px] text-muted-foreground">
                    Estas entidades não têm coordenadas resolvidas na sede e, por isso, não são colocadas no mapa.
                    Continuam no grafo e podem ser abertas na ficha — a lista respeita a pesquisa e o concelho ativos.
                    {mapa.sem_geo_itens.length < mapa.sem_geo
                      ? ` A mostrar ${contagem(mapa.sem_geo_itens.length)} de ${contagem(mapa.sem_geo)}.`
                      : ""}
                  </p>
                  {mapa.sem_geo_itens.length === 0 ? (
                    <p className="px-3 py-3 text-[11px] text-muted-foreground">Sem entidades para os filtros atuais.</p>
                  ) : (
                    <div className="max-h-[360px] overflow-y-auto">
                      <table className="w-full text-left text-[11.5px]">
                        <thead className="sticky top-0 border-b border-border bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
                          <tr>
                            <th className="px-3 py-2">Entidade</th>
                            <th className="px-3 py-2">NIF</th>
                            <th className="px-3 py-2">Sede declarada</th>
                            <th className="px-3 py-2">Concelho</th>
                            <th className="px-3 py-2 text-right">Ligações</th>
                            <th className="px-3 py-2">Anos</th>
                            <th className="px-3 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {mapa.sem_geo_itens.map((item) => (
                            <tr key={item.no_id} className="border-b border-border/60 last:border-0 hover:bg-muted/30">
                              <td className="max-w-[260px] truncate px-3 py-1.5" title={item.nome}>{item.nome}</td>
                              <td className="px-3 py-1.5 font-mono text-[10.5px] text-muted-foreground">{item.nif || "—"}</td>
                              <td className="max-w-[220px] truncate px-3 py-1.5 text-muted-foreground" title={item.local_sede || undefined}>{item.local_sede || "—"}</td>
                              <td className="max-w-[150px] truncate px-3 py-1.5 text-muted-foreground" title={item.concelho || undefined}>{item.concelho || "—"}</td>
                              <td className="px-3 py-1.5 text-right font-mono">{contagem(item.ligacoes)}</td>
                              <td className="max-w-[120px] truncate px-3 py-1.5 text-muted-foreground">{item.anos?.length ? item.anos.join(", ") : "—"}</td>
                              <td className="px-3 py-1.5 text-right">
                                <button
                                  type="button"
                                  onClick={() => {
                                    void abrirNo(item.no_id);
                                    setAba("grafo");
                                  }}
                                  className="rounded-md border border-border px-2 py-1 text-[10.5px] text-muted-foreground hover:text-foreground"
                                >
                                  Abrir ficha
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* --------------------------------------------------------- empresas */}
          <TabsContent value="empresas" active={aba === "empresas"} className="space-y-4">
            <Card>
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(evento) => {
                  evento.preventDefault();
                  void carregarEmpresas(0);
                }}
              >
                <div className="min-w-[240px] flex-1">
                  <Label htmlFor="tg-empresas-q">Empresas do registo de interesses</Label>
                  <div className="relative">
                    <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="tg-empresas-q"
                      value={empresasQ}
                      onChange={(evento) => setEmpresasQ(evento.target.value)}
                      placeholder="nome, NIF ou concelho…"
                      autoComplete="off"
                      className="pl-7"
                    />
                  </div>
                </div>
                <Button type="submit" size="sm" icon={<Search size={13} />} loading={aCarregarEmpresas}>
                  Pesquisar
                </Button>
                <a
                  href={tgExportUrl({ vista: "empresas", q: empresasQ || undefined })}
                  className="mb-0.5 inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Download size={13} /> CSV
                </a>
              </form>
              <p className="mt-2 text-[10.5px] text-muted-foreground">
                {contagem(empresasTotal)} empresa(s) · ordenadas pelas ligações a titulares
              </p>
            </Card>

            <Card padding="none" className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11.5px]">
                  <thead className="border-b border-border bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Empresa</th>
                      <th className="px-3 py-2">NIF</th>
                      <th className="px-3 py-2">Sede</th>
                      <th className="px-3 py-2">Concelho</th>
                      <th className="px-3 py-2 text-right">Ligações</th>
                      <th className="px-3 py-2">Anos</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {empresas.map((empresa) => (
                      <tr key={empresa.no_id} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                        <td className="max-w-[320px] px-3 py-1.5">
                          <span className="line-clamp-2 text-foreground">{empresa.nome}</span>
                          {empresa.detalhes?.natureza ? (
                            <span className="block truncate text-[10px] text-muted-foreground">
                              {String(empresa.detalhes.natureza)}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{empresa.nif ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{empresa.local_sede ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">
                          {empresa.concelho ?? "—"}
                          {empresa.precisao_label ? (
                            <span className="block text-[9.5px] text-muted-foreground/70">{empresa.precisao_label}</span>
                          ) : null}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-foreground">{contagem(empresa.ligacoes)}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{anosTexto(empresa.anos)}</td>
                        <td className="px-3 py-1.5 text-right">
                          <button
                            type="button"
                            onClick={() => {
                              void abrirNo(empresa.no_id);
                              setAba("grafo");
                            }}
                            className="rounded-lg border border-border px-2 py-1 text-[10.5px] text-muted-foreground hover:text-foreground"
                          >
                            Ficha
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!empresas.length && (
                      <tr>
                        <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                          {aCarregarEmpresas ? "a carregar…" : "Sem empresas para os filtros atuais."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
                <span>
                  {contagem(empresasPagina * paginaTamanho + 1)}–
                  {contagem(Math.min(empresasTotal, (empresasPagina + 1) * paginaTamanho))} de {contagem(empresasTotal)}
                </span>
                <span className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={empresasPagina === 0}
                    onClick={() => void carregarEmpresas(empresasPagina - 1)}
                  >
                    Anterior
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={(empresasPagina + 1) * paginaTamanho >= empresasTotal}
                    onClick={() => void carregarEmpresas(empresasPagina + 1)}
                  >
                    Seguinte
                  </Button>
                </span>
              </div>
            </Card>
          </TabsContent>

          {/* ---------------------------------------------------------- recolha */}
          <TabsContent value="recolha" active={aba === "recolha"} className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle icon={<Database size={15} />}>Construir o grafo</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-3">
                  <p className="text-[11px] text-muted-foreground">
                    Lê as declarações normalizadas do módulo Entidade para a Transparência, extrai as pessoas,
                    cargos, entidades públicas e empresas, geocodifica as sedes e grava o grafo em disco.
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label htmlFor="tg-limite">Limite de declarações</Label>
                      <Input
                        id="tg-limite"
                        type="number"
                        min={1}
                        value={limiteDeclaracoes}
                        onChange={(evento) => setLimiteDeclaracoes(evento.target.value)}
                        placeholder="Todas"
                      />
                    </div>
                    <div className="space-y-2 pt-5 text-xs">
                      <label className="flex items-center gap-2">
                        <input type="checkbox" checked={forcar} onChange={(evento) => setForcar(evento.target.checked)} />
                        Reconstruir mesmo que esteja atualizado
                      </label>
                      <label className="flex items-center gap-2">
                        <input type="checkbox" checked={indexar} onChange={(evento) => setIndexar(evento.target.checked)} />
                        Indexar no fim
                      </label>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" icon={<Network size={13} />} loading={aArrancar && job?.tipo === "construir"} onClick={() => void iniciarConstrucao()}>
                      Construir grafo
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Database size={13} />}
                      loading={aArrancar && job?.tipo === "indexar"}
                      onClick={() => void iniciarIndexacao()}
                    >
                      Indexar agora
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
                          className="h-full rounded-full bg-teal-400/70 transition-all"
                          style={{ width: `${job.status === "done" ? 100 : jobProgresso}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-muted-foreground">
                        {job.progress?.declaracoes ? `${contagem(job.progress.declaracoes)} declarações lidas` : ""}
                        {job.progress?.titularidades ? ` · ${contagem(job.progress.titularidades)} titularidades` : ""}
                        {job.progress?.registos ? ` · ${contagem(job.progress.registos)} registos` : ""}
                        {job.progress?.current ? ` · ${job.progress.current}` : ""}
                      </p>
                      {job.error && <p className="text-[10px] text-destructive">{job.error}</p>}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle icon={<Layers size={15} />}>Estado do módulo</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-2 text-[11px] text-muted-foreground">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      ["Pessoas", stats?.pessoas],
                      ["Cargos", stats?.cargos],
                      ["Entidades públicas", stats?.entidades],
                      ["Empresas", stats?.empresas],
                      ["Nós", stats?.nos],
                      ["Arestas", stats?.arestas],
                      ["Com sede no mapa", stats?.com_geo],
                      ["Declarações lidas", stats?.declaracoes_lidas],
                    ].map(([rotulo, valor]) => (
                      <div key={String(rotulo)} className="rounded-lg border border-border/70 bg-muted/40 px-2.5 py-1.5">
                        <p className="text-[10px] uppercase tracking-wide">{rotulo}</p>
                        <p className="text-xs text-foreground">{contagem(Number(valor ?? 0))}</p>
                      </div>
                    ))}
                  </div>
                  <p>
                    Índice: {stats?.fonte_indexada ? "Elasticsearch" : "disco (Elasticsearch indisponível)"}
                    {stats?.indice_desatualizado
                      ? ` · atrasado (${contagem(stats?.indice?.nos ?? 0)} nós indexados)`
                      : ""}{" "}
                    · atualizado {dataCurta(stats?.atualizado_em)}
                  </p>
                  {meta && (
                    <>
                      <p className="break-all">
                        Dados: <code className="rounded bg-muted px-1">{meta.pasta}</code>
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

            <Card>
              <CardHeader>
                <CardTitle icon={<Network size={15} />}>Como se lê o grafo</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(meta?.relacoes ?? {}).map(([chave, info]) => (
                  <div key={chave} className="rounded-lg border border-border/70 bg-muted/30 px-2.5 py-1.5">
                    <p className="font-mono text-[10px] text-foreground">{chave}</p>
                    <p>{info.label}</p>
                    <p className="text-[10px] text-muted-foreground/80">{contagem(stats?.relacoes?.[chave] ?? 0)} aresta(s)</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {fichaModal && selecionado && (
          <div
            className="fixed inset-0 z-[80] flex items-start justify-center overflow-y-auto bg-black/65 p-4 backdrop-blur-sm"
            onMouseDown={(evento) => {
              if (evento.target === evento.currentTarget) setFichaModal(false);
            }}
            role="dialog"
            aria-modal="true"
            aria-label="Ficha do nó"
          >
            <div
              className="glass-card my-6 w-full max-w-3xl rounded-2xl border border-border shadow-2xl"
              onMouseDown={(evento) => evento.stopPropagation()}
            >
              <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  <Layers size={15} className="text-teal-300" /> Ficha do nó
                </h2>
                <button
                  type="button"
                  onClick={() => setFichaModal(false)}
                  className="rounded-lg p-1 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  aria-label="Fechar janela da ficha"
                >
                  <X size={16} />
                </button>
              </header>
              <div className="max-h-[78vh] overflow-y-auto p-4">{renderFicha()}</div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
