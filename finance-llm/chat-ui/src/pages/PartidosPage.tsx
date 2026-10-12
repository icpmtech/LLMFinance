/**
 * **Partidos políticos e as suas contas** — financiamento partidário português.
 *
 * Junta as duas fontes oficiais:
 *
 * 1. **Tribunal Constitucional** (`contas_eleicoes-partidos`): por ano, as contas
 *    anuais de cada partido, as listas de ações e meios de propaganda política,
 *    os relatórios da ECFP, os acórdãos e as decisões;
 * 2. **CNE** (`partidos-politicos-1`): o registo oficial dos partidos (inscritos
 *    e extintos), com sigla, data de inscrição, sítio e símbolo.
 *
 * A página dá seis leituras:
 *
 * 1. **Painel** — quantos documentos por ano e por secção, quem entregou e quem
 *    está em falta, e os partidos com mais contas;
 * 2. **Pesquisa** — por texto (inclui o texto dos PDF digitais), ano, secção,
 *    partido e cumprimento, com exportação CSV;
 * 3. **Partido** — ficha do partido: registo da CNE + contas por ano + pessoas
 *    do PessoasIQ ligadas ao partido;
 * 4. **Pessoa** — o partido de uma pessoa (por NIF) e as contas desse partido;
 * 5. **Registo** — o registo oficial da CNE, com pesquisa;
 * 6. **Recolha** — o que está em disco, o que está indexado e os trabalhos.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  Download,
  ExternalLink,
  FileText,
  Gavel,
  Info,
  Landmark,
  ListChecks,
  Loader2,
  RefreshCw,
  Scale,
  Search,
  ScrollText,
  TriangleAlert,
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
  bytes,
  compact,
  count,
  downloadPartidosCsv,
  getPartidosAmostra,
  getPartidosAnos,
  getPartidosFicheiros,
  getPartidosJob,
  getPartidosMeta,
  getPartidosPessoa,
  getPartidosPartido,
  getPartidosPartidoPessoas,
  getPartidosRegisto,
  getPartidosResumo,
  indexarPartidos,
  partidoPdfUrl,
  recolherPartidos,
  searchPartidos,
  secaoLabel,
  shortDate,
  type PartidosAnos,
  type PartidosAmostra,
  type PartidosDocumento,
  type PartidosFichaPartido,
  type PartidosFicheiros,
  type PartidosJob,
  type PartidosMeta,
  type PartidosPessoa,
  type PartidosPessoas,
  type PartidosRegisto,
  type PartidosResumo,
  type PartidosSearchResult,
} from "../partidosApi";

type Aba = "painel" | "pesquisa" | "partido" | "pessoa" | "registo" | "recolha";

type Filtros = {
  q: string;
  ano?: number;
  secao?: string;
  partido?: string;
  entregou?: boolean;
  com_documento?: boolean;
  sort: "relevancia" | "ano" | "partido" | "secao" | "paginas";
  order: "asc" | "desc";
};

const TAMANHO_PAGINA = 20;

const FILTROS_INICIAIS: Filtros = { q: "", sort: "relevancia", order: "desc" };

const SECOES_OPCOES = [
  { valor: "", label: "Todas as secções" },
  { valor: "contas_anuais", label: "Contas anuais" },
  { valor: "lista_acoes", label: "Lista de ações e meios" },
  { valor: "relatorios_ecfp", label: "Relatórios da ECFP" },
  { valor: "acordaos", label: "Acórdãos" },
  { valor: "decisoes_ecfp", label: "Decisões da ECFP" },
];

/** Cartão de indicador. */
function Kpi({ icon, label, valor, nota }: { icon: ReactNode; label: string; valor: string; nota?: string }) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-muted text-muted-foreground">{icon}</div>
        <div className="min-w-0">
          <p className="truncate text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="truncate text-lg font-semibold tabular-nums">{valor}</p>
          {nota ? <p className="truncate text-xs text-muted-foreground">{nota}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

/** Lista horizontal de barras (sem dependências de gráficos). */
function Barras({ itens, formatar }: { itens: { chave: string; valor: number; nota?: string }[]; formatar?: (valor: number) => string }) {
  const maximo = Math.max(1, ...itens.map((item) => Math.abs(item.valor)));
  const escrever = formatar || count;
  return (
    <div className="space-y-2">
      {itens.map((item) => (
        <div key={item.chave} className="space-y-1">
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="min-w-0 flex-1 truncate font-medium" title={item.chave}>
              {item.chave}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {escrever(item.valor)}
              {item.nota ? <span className="ml-2 opacity-70">{item.nota}</span> : null}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-400 to-violet-500"
              style={{ width: `${Math.max(2, (Math.abs(item.valor) / maximo) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Ícone da secção. */
function iconeSecao(secao?: string | null): ReactNode {
  if (secao === "contas_anuais") return <FileText size={12} />;
  if (secao === "lista_acoes") return <ListChecks size={12} />;
  if (secao === "acordaos") return <Gavel size={12} />;
  if (secao === "decisoes_ecfp") return <Scale size={12} />;
  return <ScrollText size={12} />;
}

/** Estado de entrega, com a cor certa. */
function BadgeEntrega({ item }: { item: PartidosDocumento }) {
  if (item.nota) return <Badge variant="outline">Nota</Badge>;
  if (item.agregado) return <Badge variant="info">Documento agregado</Badge>;
  if (item.entregou) return <Badge variant="success">Entregue</Badge>;
  return <Badge variant="danger">{item.motivo ? `Em falta — ${item.motivo}` : "Em falta"}</Badge>;
}

/** Cartão de um documento das contas. */
function LinhaDocumento({ item, onAbrirPartido }: { item: PartidosDocumento; onAbrirPartido?: () => void }) {
  const temPdf = Boolean(item.ficheiro);
  return (
    <div className="rounded-xl border bg-card px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium" title={item.partido_nome || ""}>
            {item.partido_nome || <span className="text-muted-foreground">Sem partido (nota da secção)</span>}
            {item.partido_sigla ? <span className="ml-2 text-xs text-muted-foreground">{item.partido_sigla}</span> : null}
          </p>
          <p className="truncate text-xs text-muted-foreground" title={item.secao_titulo || ""}>
            {iconeSecao(item.secao)}
            <span className="ml-1 align-[2px]">
              {secaoLabel(item.secao)} · {item.ano}
            </span>
          </p>
          {item.observacao ? (
            <p className="mt-1 break-words text-xs text-muted-foreground">{item.observacao}</p>
          ) : null}
        </div>
        <div className="flex flex-col items-end gap-1">
          <BadgeEntrega item={item} />
          <div className="flex flex-wrap justify-end gap-1">
            {item.paginas ? <Badge variant="secondary">{count(item.paginas)} pág.</Badge> : null}
            {item.ficheiro_kb ? <Badge variant="outline">{compact(item.ficheiro_kb)} KB</Badge> : null}
            {item.pdf_digitalizado ? <Badge variant="warning">digitalizado</Badge> : null}
            {item.texto_extraido ? (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 size={11} /> texto
              </Badge>
            ) : null}
          </div>
          <div className="flex flex-wrap justify-end gap-1">
            {temPdf ? (
              <>
                <a
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  href={partidoPdfUrl(item.ano, item.ficheiro as string)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={12} className="mr-1 inline align-[-2px]" />
                  abrir PDF
                </a>
                <a
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  href={partidoPdfUrl(item.ano, item.ficheiro as string, true)}
                >
                  <Download size={12} className="mr-1 inline align-[-2px]" />
                  descarregar
                </a>
              </>
            ) : null}
            {onAbrirPartido && item.partido_chave ? (
              <button
                type="button"
                className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                onClick={onAbrirPartido}
              >
                ficha do partido
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PartidosPage() {
  const [aba, setAba] = useState<Aba>("painel");
  const [meta, setMeta] = useState<PartidosMeta | null>(null);
  const [resumo, setResumo] = useState<PartidosResumo | null>(null);
  const [ficheiros, setFicheiros] = useState<PartidosFicheiros | null>(null);
  const [anos, setAnos] = useState<PartidosAnos | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  // Pesquisa (o rascunho só entra na pesquisa ao carregar em «Pesquisar»).
  const [rascunho, setRascunho] = useState<Filtros>(FILTROS_INICIAIS);
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_INICIAIS);
  const [pagina, setPagina] = useState(1);
  const [resultado, setResultado] = useState<PartidosSearchResult | null>(null);
  const [pesquisando, setPesquisando] = useState(false);

  // Ficha do partido.
  const [partidoTermo, setPartidoTermo] = useState("");
  const [partido, setPartido] = useState<PartidosFichaPartido | null>(null);
  const [partidoPessoas, setPartidoPessoas] = useState<PartidosPessoas | null>(null);
  const [partidoErro, setPartidoErro] = useState<string | null>(null);
  const [partidoCarregando, setPartidoCarregando] = useState(false);

  // Ficha da pessoa.
  const [pessoaNif, setPessoaNif] = useState("");
  const [pessoa, setPessoa] = useState<PartidosPessoa | null>(null);
  const [pessoaErro, setPessoaErro] = useState<string | null>(null);
  const [pessoaCarregando, setPessoaCarregando] = useState(false);

  // Registo da CNE.
  const [registoQ, setRegistoQ] = useState("");
  const [registoSituacao, setRegistoSituacao] = useState<"" | "inscrito" | "extinto">("");
  const [registo, setRegisto] = useState<PartidosRegisto | null>(null);

  // Recolha e indexação.
  const [job, setJob] = useState<PartidosJob | null>(null);
  const [comPdf, setComPdf] = useState(false);
  const [amostra, setAmostra] = useState<PartidosAmostra | null>(null);

  const recarregar = useCallback(async () => {
    setErro(null);
    try {
      const [dadosMeta, dadosFicheiros, dadosAnos] = await Promise.all([
        getPartidosMeta(),
        getPartidosFicheiros(),
        getPartidosAnos(),
      ]);
      setMeta(dadosMeta);
      setFicheiros(dadosFicheiros);
      setAnos(dadosAnos);
      try {
        setResumo(await getPartidosResumo());
      } catch (falha) {
        // O painel depende do Elasticsearch; a página continua a funcionar sem ele.
        setResumo(null);
        setAviso(falha instanceof Error ? falha.message : String(falha));
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  // Pesquisa (corre quando os filtros aplicados ou a página mudam).
  useEffect(() => {
    if (aba !== "pesquisa") return;
    let ativo = true;
    setPesquisando(true);
    searchPartidos({ ...filtros, page: pagina, size: TAMANHO_PAGINA })
      .then((dados) => {
        if (ativo) {
          setResultado(dados);
          setErro(null);
        }
      })
      .catch((falha) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : String(falha));
      })
      .finally(() => {
        if (ativo) setPesquisando(false);
      });
    return () => {
      ativo = false;
    };
  }, [aba, filtros, pagina]);

  // Registo oficial da CNE.
  useEffect(() => {
    if (aba !== "registo") return;
    let ativo = true;
    getPartidosRegisto({ q: registoQ || undefined, situacao: registoSituacao || undefined, size: 100 })
      .then((dados) => {
        if (ativo) setRegisto(dados);
      })
      .catch((falha) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : String(falha));
      });
    return () => {
      ativo = false;
    };
  }, [aba, registoQ, registoSituacao]);

  // Progresso dos trabalhos de recolha/indexação.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const temporizador = window.setInterval(() => {
      getPartidosJob(job.job_id)
        .then((atual) => {
          setJob(atual);
          if (atual.status !== "running") void recarregar();
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(temporizador);
  }, [job, recarregar]);

  const abrirPartido = useCallback(async (termo: string) => {
    const alvo = termo.trim();
    if (!alvo) return;
    setPartidoTermo(alvo);
    setAba("partido");
    setPartidoCarregando(true);
    setPartidoErro(null);
    setPartido(null);
    setPartidoPessoas(null);
    try {
      const ficha = await getPartidosPartido(alvo);
      setPartido(ficha);
      getPartidosPartidoPessoas(alvo)
        .then(setPartidoPessoas)
        .catch(() => setPartidoPessoas(null));
    } catch (falha) {
      setPartidoErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setPartidoCarregando(false);
    }
  }, []);

  const abrirPessoa = useCallback(async (nif: string) => {
    const alvo = nif.trim();
    if (!alvo) return;
    setPessoaNif(alvo);
    setAba("pessoa");
    setPessoaCarregando(true);
    setPessoaErro(null);
    setPessoa(null);
    try {
      setPessoa(await getPartidosPessoa(alvo));
    } catch (falha) {
      setPessoaErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setPessoaCarregando(false);
    }
  }, []);

  const arrancarRecolha = useCallback(
    async (forcar: boolean) => {
      try {
        setJob(await recolherPartidos({ com_pdf: comPdf, forcar, indexar: false }));
        setAba("recolha");
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : String(falha));
      }
    },
    [comPdf]
  );

  const arrancarIndexacao = useCallback(async (forcar: boolean) => {
    try {
      setJob(await indexarPartidos({ forcar }));
      setAba("recolha");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    }
  }, []);

  const anosLista = useMemo(() => (anos?.anos || []).map((item) => item.ano).sort((a, b) => b - a), [anos]);

  const totalPaginas = resultado ? Math.max(1, Math.ceil(resultado.total / TAMANHO_PAGINA)) : 1;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-4 py-4 md:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-violet-400 to-sky-600 text-white shadow-lg shadow-violet-500/25">
              <Landmark size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Partidos políticos e contas</h1>
              <p className="text-sm text-muted-foreground">
                Contas anuais e financiamento partidário (Tribunal Constitucional) e registo oficial dos partidos (CNE)
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {resumo ? (
              <Badge variant="outline" className="gap-1">
                <Database size={12} /> {count(resumo.total)} entradas
              </Badge>
            ) : null}
            {resumo ? <Badge variant="secondary">{count(resumo.partidos_distintos)} partidos</Badge> : null}
            <Button variant="outline" size="sm" onClick={() => void recarregar()}>
              <RefreshCw size={14} className="mr-1.5" /> Atualizar
            </Button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
        {erro ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
            <CircleAlert size={16} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">{erro}</span>
            <button type="button" className="ml-auto shrink-0 opacity-70" onClick={() => setErro(null)}>
              <X size={14} />
            </button>
          </div>
        ) : null}
        {aviso ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border bg-muted/40 px-4 py-3 text-sm">
            <Info size={16} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">Painel indisponível: {aviso}</span>
            <button type="button" className="ml-auto shrink-0 opacity-70" onClick={() => setAviso(null)}>
              <X size={14} />
            </button>
          </div>
        ) : null}

        <Tabs value={aba} onValueChange={(valor) => setAba(valor as Aba)} className="w-full">
          <TabsList className="mb-4 flex-wrap">
            {(
              [
                ["painel", "Painel"],
                ["pesquisa", "Pesquisa"],
                ["partido", "Partido"],
                ["pessoa", "Pessoa"],
                ["registo", "Registo (CNE)"],
                ["recolha", "Recolha"],
              ] as const
            ).map(([valor, label]) => (
              <TabsTrigger key={valor} value={valor} active={aba === valor} onClick={() => setAba(valor)}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* ------------------------------------------------------------ painel */}
          <TabsContent value="painel" active={aba === "painel"} className="space-y-4">
            {carregando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A carregar…
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi
                icon={<ScrollText size={16} />}
                label="Entradas indexadas"
                valor={count(resumo?.total ?? meta?.itens)}
                nota={`${count(meta?.anos_recolhidos)} anos recolhidos`}
              />
              <Kpi
                icon={<Landmark size={16} />}
                label="Partidos com contas"
                valor={count(resumo?.partidos_distintos)}
                nota="chaves distintas"
              />
              <Kpi
                icon={<CheckCircle2 size={16} />}
                label="Documentos entregues"
                valor={count(resumo?.entregues)}
                nota={`${count(resumo?.em_falta)} em falta`}
              />
              <Kpi
                icon={<FileText size={16} />}
                label="PDF guardados"
                valor={count(meta?.pdfs)}
                nota={`${bytes(meta?.pdf_bytes)} em disco · ${count(resumo?.digitalizados)} digitalizações`}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle icon={<CalendarDays size={16} />}>Cumprimento por ano</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  {(resumo?.por_ano || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Sem dados indexados. Abra <strong>Recolha</strong> e corra a recolha e a indexação.
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="text-xs uppercase tracking-wide text-muted-foreground">
                          <tr>
                            <th className="px-2 py-1 text-left">Ano</th>
                            <th className="px-2 py-1 text-right">Entradas</th>
                            <th className="px-2 py-1 text-right">Partidos</th>
                            <th className="px-2 py-1 text-right">Documentos</th>
                            <th className="px-2 py-1 text-right">Em falta</th>
                            <th className="px-2 py-1 text-right">Páginas</th>
                            <th className="px-2 py-1" />
                          </tr>
                        </thead>
                        <tbody>
                          {(resumo?.por_ano || []).map((item) => (
                            <tr key={item.ano} className="border-t">
                              <td className="px-2 py-1.5 font-medium tabular-nums">{item.ano}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{count(item.entradas)}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{count(item.partidos)}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{count(item.documentos)}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{count(item.em_falta)}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{count(item.paginas)}</td>
                              <td className="px-2 py-1.5 text-right">
                                <button
                                  type="button"
                                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                                  onClick={() => void getPartidosAmostra(item.ano, 40).then(setAmostra)}
                                >
                                  amostra
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

              <Card>
                <CardHeader>
                  <CardTitle icon={<Database size={16} />}>Por secção</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  {(resumo?.por_secao || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">Sem dados indexados.</p>
                  ) : (
                    <Barras
                      itens={(resumo?.por_secao || []).map((item) => ({
                        chave: secaoLabel(String(item.key), item.label),
                        valor: item.count || 0,
                      }))}
                    />
                  )}
                </CardContent>
              </Card>

              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle icon={<Landmark size={16} />}>Partidos com mais documentos</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  {(resumo?.top_partidos || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">Sem dados indexados.</p>
                  ) : (
                    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                      {(resumo?.top_partidos || []).slice(0, 18).map((item) => (
                        <button
                          key={item.chave}
                          type="button"
                          onClick={() => void abrirPartido(item.chave)}
                          className="rounded-xl border px-3 py-2 text-left transition hover:border-primary/40 hover:bg-muted/40"
                        >
                          <p className="truncate text-sm font-medium" title={item.nome || item.chave}>
                            {item.nome || item.chave}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {count(item.count)} entradas · {count(item.documentos)} documentos · {count(item.anos)} anos
                            {item.em_falta ? ` · ${count(item.em_falta)} em falta` : ""}
                          </p>
                        </button>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {resumo?.registo?.total ? (
                <Card className="lg:col-span-2">
                  <CardHeader>
                    <CardTitle icon={<BadgeCheck size={16} />}>Registo oficial (CNE)</CardTitle>
                  </CardHeader>
                  <CardContent className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    <Badge variant="success">{count(resumo.registo.inscritos)} inscritos</Badge>
                    <Badge variant="secondary">{count(resumo.registo.extintos)} extintos</Badge>
                    <Badge variant="outline">{count(resumo.registo.com_site)} com sítio</Badge>
                    <Badge variant="outline">{count(resumo.registo.com_descricao)} com descrição</Badge>
                    <button
                      type="button"
                      className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:underline"
                      onClick={() => setAba("registo")}
                    >
                      ver registo
                    </button>
                  </CardContent>
                </Card>
              ) : null}
            </div>

            {amostra ? (
              <Card>
                <CardHeader>
                  <CardTitle icon={<ScrollText size={16} />}>
                    Amostra de {amostra.ano} — {count(amostra.total)} entradas lidas do disco
                  </CardTitle>
                  <button type="button" className="ml-auto opacity-70" onClick={() => setAmostra(null)}>
                    <X size={14} />
                  </button>
                </CardHeader>
                <CardContent className="mt-3 space-y-2">
                  {amostra.error ? (
                    <p className="text-sm text-muted-foreground">{amostra.error}</p>
                  ) : (
                    amostra.items.map((item) => <LinhaDocumento key={item.doc_id} item={item} onAbrirPartido={() => void abrirPartido(item.partido_chave || "")} />)
                  )}
                </CardContent>
              </Card>
            ) : null}
          </TabsContent>

          {/* --------------------------------------------------------- pesquisa */}
          <TabsContent value="pesquisa" active={aba === "pesquisa"} className="space-y-4">
            <Card>
              <CardContent className="space-y-3">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <div className="md:col-span-2">
                    <Label htmlFor="partidos-q">Texto</Label>
                    <Input
                      id="partidos-q"
                      value={rascunho.q}
                      placeholder="Partido, sigla, secção ou texto do PDF («demonstração de resultados»)"
                      onChange={(evento) => setRascunho((atual) => ({ ...atual, q: evento.target.value }))}
                      onKeyDown={(evento) => {
                        if (evento.key === "Enter") {
                          setPagina(1);
                          setFiltros({ ...rascunho });
                        }
                      }}
                    />
                  </div>
                  <div>
                    <Label htmlFor="partidos-ano">Ano</Label>
                    <select
                      id="partidos-ano"
                      className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                      value={rascunho.ano ?? ""}
                      onChange={(evento) =>
                        setRascunho((atual) => ({ ...atual, ano: evento.target.value ? Number(evento.target.value) : undefined }))
                      }
                    >
                      <option value="">Todos os anos</option>
                      {anosLista.map((ano) => (
                        <option key={ano} value={ano}>
                          {ano}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label htmlFor="partidos-secao">Secção</Label>
                    <select
                      id="partidos-secao"
                      className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                      value={rascunho.secao ?? ""}
                      onChange={(evento) => setRascunho((atual) => ({ ...atual, secao: evento.target.value || undefined }))}
                    >
                      {SECOES_OPCOES.map((opcao) => (
                        <option key={opcao.valor} value={opcao.valor}>
                          {opcao.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label htmlFor="partidos-partido">Partido</Label>
                    <Input
                      id="partidos-partido"
                      value={rascunho.partido || ""}
                      placeholder="PCP, CDS-PP, Bloco de Esquerda…"
                      onChange={(evento) => setRascunho((atual) => ({ ...atual, partido: evento.target.value || undefined }))}
                    />
                  </div>
                  <div>
                    <Label htmlFor="partidos-entrega">Cumprimento</Label>
                    <select
                      id="partidos-entrega"
                      className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                      value={rascunho.entregou === undefined ? "" : rascunho.entregou ? "1" : "0"}
                      onChange={(evento) =>
                        setRascunho((atual) => ({
                          ...atual,
                          entregou: evento.target.value === "" ? undefined : evento.target.value === "1",
                        }))
                      }
                    >
                      <option value="">Tudo</option>
                      <option value="1">Só entregues</option>
                      <option value="0">Só em falta</option>
                    </select>
                  </div>
                  <div>
                    <Label htmlFor="partidos-ordem">Ordenar por</Label>
                    <select
                      id="partidos-ordem"
                      className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                      value={`${rascunho.sort}:${rascunho.order}`}
                      onChange={(evento) => {
                        const [sort, order] = evento.target.value.split(":") as [Filtros["sort"], Filtros["order"]];
                        setRascunho((atual) => ({ ...atual, sort, order }));
                      }}
                    >
                      <option value="relevancia:desc">Relevância</option>
                      <option value="ano:desc">Ano (recente primeiro)</option>
                      <option value="ano:asc">Ano (antigo primeiro)</option>
                      <option value="partido:asc">Partido (A→Z)</option>
                      <option value="secao:asc">Secção</option>
                      <option value="paginas:desc">Documentos maiores</option>
                    </select>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => {
                      setPagina(1);
                      setFiltros({ ...rascunho });
                      setAba("pesquisa");
                    }}
                    icon={<Search size={14} />}
                  >
                    Pesquisar
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setRascunho(FILTROS_INICIAIS);
                      setFiltros(FILTROS_INICIAIS);
                      setPagina(1);
                    }}
                  >
                    Limpar
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void downloadPartidosCsv({ ...filtros })}
                    icon={<Download size={14} />}
                  >
                    Exportar CSV
                  </Button>
                  {resultado ? (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {count(resultado.total)} registo(s) · recuperados {count(resultado.kpis?.com_texto)} com texto
                    </span>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            {pesquisando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A pesquisar…
              </div>
            ) : !resultado || resultado.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sem resultados para os filtros escolhidos.</p>
            ) : (
              <div className="space-y-2">
                {resultado.items.map((item) => (
                  <LinhaDocumento key={item.doc_id} item={item} onAbrirPartido={() => void abrirPartido(item.partido_chave || "")} />
                ))}
              </div>
            )}

            {resultado && resultado.total > TAMANHO_PAGINA ? (
              <div className="flex items-center justify-between gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina <= 1}
                  onClick={() => setPagina((valor) => Math.max(1, valor - 1))}
                  icon={<ChevronLeft size={14} />}
                >
                  Anterior
                </Button>
                <span className="text-xs text-muted-foreground">
                  Página {pagina} de {totalPaginas}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina >= totalPaginas}
                  onClick={() => setPagina((valor) => valor + 1)}
                >
                  Seguinte <ChevronRight size={14} />
                </Button>
              </div>
            ) : null}
          </TabsContent>

          {/* ---------------------------------------------------------- partido */}
          <TabsContent value="partido" active={aba === "partido"} className="space-y-4">
            <Card>
              <CardContent className="flex flex-wrap items-end gap-2">
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="partidos-partido-termo">Sigla, chave ou nome do partido</Label>
                  <Input
                    id="partidos-partido-termo"
                    value={partidoTermo}
                    placeholder="PCP, CDS-PP, BE, Bloco de Esquerda…"
                    onChange={(evento) => setPartidoTermo(evento.target.value)}
                    onKeyDown={(evento) => {
                      if (evento.key === "Enter") void abrirPartido(partidoTermo);
                    }}
                  />
                </div>
                <Button size="sm" onClick={() => void abrirPartido(partidoTermo)} icon={<Search size={14} />}>
                  Abrir ficha
                </Button>
              </CardContent>
            </Card>

            {partidoCarregando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A ler a ficha…
              </div>
            ) : null}
            {partidoErro ? (
              <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
                <CircleAlert size={16} className="mt-0.5 shrink-0" />
                <span className="min-w-0 break-words">{partidoErro}</span>
              </div>
            ) : null}

            {partido?.encontrado ? (
              <>
                <Card>
                  <CardContent className="flex flex-wrap items-start gap-4">
                    {partido.registo?.logotipo_url ? (
                      <img
                        src={partido.registo.logotipo_url}
                        alt=""
                        className="h-14 w-14 rounded-xl border bg-white object-contain p-1"
                      />
                    ) : null}
                    <div className="min-w-0 flex-1">
                      <p className="text-base font-semibold">
                        {partido.registo?.denominacao || partido.partido_nome || partido.termo}
                        {partido.registo?.sigla ? (
                          <span className="ml-2 text-sm text-muted-foreground">{partido.registo.sigla}</span>
                        ) : null}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {partido.registo?.situacao ? (
                          <Badge variant={partido.registo.situacao === "inscrito" ? "success" : "secondary"}>
                            {partido.registo.situacao}
                          </Badge>
                        ) : (
                          <Badge variant="warning">sem registo na CNE</Badge>
                        )}
                        {partido.registo?.data_inscricao ? (
                          <span>inscrito em {shortDate(partido.registo.data_inscricao)}</span>
                        ) : null}
                        <span>{count(partido.total)} entradas</span>
                        <span>{count(partido.em_falta)} em falta</span>
                        <span>{count(partido.com_texto)} com texto</span>
                      </div>
                      {partido.registo?.site ? (
                        <a
                          className="mt-1 inline-block text-xs text-muted-foreground underline-offset-2 hover:underline"
                          href={partido.registo.site}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={12} className="mr-1 inline align-[-2px]" />
                          {partido.registo.site}
                        </a>
                      ) : null}
                      {partido.registo?.descricao ? (
                        <p className="mt-2 whitespace-pre-line text-sm text-muted-foreground">{partido.registo.descricao}</p>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>

                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle icon={<CalendarDays size={16} />}>Contas por ano</CardTitle>
                    </CardHeader>
                    <CardContent className="mt-3">
                      <Barras
                        itens={partido.por_ano.map((item) => ({
                          chave: String(item.ano),
                          valor: item.entradas,
                          nota: item.em_falta ? `${item.em_falta} em falta` : undefined,
                        }))}
                      />
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle icon={<Users size={16} />}>
                        Pessoas do partido (PessoasIQ) — {count(partidoPessoas?.total)}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="mt-3">
                      {!partidoPessoas || partidoPessoas.items.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Sem pessoas indexadas com este partido.</p>
                      ) : (
                        <div className="space-y-1">
                          {partidoPessoas.items.map((item) => (
                            <button
                              key={String(item.nif)}
                              type="button"
                              className="flex w-full items-baseline justify-between gap-3 rounded-lg px-2 py-1 text-left text-sm transition hover:bg-muted/50"
                              onClick={() => void abrirPessoa(item.nif || "")}
                            >
                              <span className="min-w-0 truncate">{item.nome || item.nif}</span>
                              <span className="shrink-0 text-xs text-muted-foreground">
                                {item.nif} {item.source ? `· ${item.source}` : ""}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>

                <div>
                  <p className="mb-2 text-sm font-medium">Documentos ({count(partido.documentos.length)})</p>
                  <div className="space-y-2">
                    {partido.documentos.map((item) => (
                      <LinhaDocumento key={item.doc_id} item={item} />
                    ))}
                  </div>
                </div>
              </>
            ) : null}
          </TabsContent>

          {/* ----------------------------------------------------------- pessoa */}
          <TabsContent value="pessoa" active={aba === "pessoa"} className="space-y-4">
            <Card>
              <CardContent className="flex flex-wrap items-end gap-2">
                <div className="min-w-[200px] flex-1">
                  <Label htmlFor="partidos-pessoa-nif">NIF da pessoa</Label>
                  <Input
                    id="partidos-pessoa-nif"
                    value={pessoaNif}
                    placeholder="196700795"
                    onChange={(evento) => setPessoaNif(evento.target.value)}
                    onKeyDown={(evento) => {
                      if (evento.key === "Enter") void abrirPessoa(pessoaNif);
                    }}
                  />
                </div>
                <Button size="sm" onClick={() => void abrirPessoa(pessoaNif)} icon={<Search size={14} />}>
                  Abrir ficha
                </Button>
              </CardContent>
            </Card>

            {pessoaCarregando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A ler a ficha…
              </div>
            ) : null}
            {pessoaErro ? (
              <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
                <CircleAlert size={16} className="mt-0.5 shrink-0" />
                <span className="min-w-0 break-words">{pessoaErro}</span>
              </div>
            ) : null}

            {pessoa ? (
              <>
                <Card>
                  <CardContent className="space-y-1">
                    <p className="text-base font-semibold">{pessoa.pessoa?.nome || pessoa.nif}</p>
                    <p className="text-xs text-muted-foreground">
                      NIF {pessoa.nif}
                      {pessoa.pessoa?.fonte ? ` · ${pessoa.pessoa.fonte}` : ""}
                    </p>
                    {pessoa.partido ? (
                      <button
                        type="button"
                        className="mt-2 inline-flex items-center gap-1 text-sm text-primary underline-offset-2 hover:underline"
                        onClick={() => void abrirPartido(pessoa.partido as string)}
                      >
                        <Landmark size={14} /> {pessoa.partido}
                      </button>
                    ) : (
                      <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                        <TriangleAlert size={14} /> Sem partido no registo desta pessoa.
                      </p>
                    )}
                  </CardContent>
                </Card>

                {pessoa.ficha_partido?.encontrado ? (
                  <div>
                    <p className="mb-2 text-sm font-medium">
                      Contas de {pessoa.ficha_partido.partido_nome || pessoa.ficha_partido.termo} (
                      {count(pessoa.ficha_partido.total)})
                    </p>
                    <div className="space-y-2">
                      {pessoa.ficha_partido.documentos.slice(0, 40).map((item) => (
                        <LinhaDocumento key={item.doc_id} item={item} />
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </TabsContent>

          {/* ---------------------------------------------------------- registo */}
          <TabsContent value="registo" active={aba === "registo"} className="space-y-4">
            <Card>
              <CardContent className="flex flex-wrap items-end gap-2">
                <div className="min-w-[200px] flex-1">
                  <Label htmlFor="partidos-registo-q">Nome ou sigla</Label>
                  <Input
                    id="partidos-registo-q"
                    value={registoQ}
                    placeholder="PCP, Bloco, Chega…"
                    onChange={(evento) => setRegistoQ(evento.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="partidos-registo-situacao">Situação</Label>
                  <select
                    id="partidos-registo-situacao"
                    className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                    value={registoSituacao}
                    onChange={(evento) => setRegistoSituacao(evento.target.value as "" | "inscrito" | "extinto")}
                  >
                    <option value="">Todos</option>
                    <option value="inscrito">Inscritos</option>
                    <option value="extinto">Extintos</option>
                  </select>
                </div>
                {registo ? (
                  <span className="ml-auto text-xs text-muted-foreground">{count(registo.total)} partido(s)</span>
                ) : null}
              </CardContent>
            </Card>

            {!registo || registo.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Sem registo indexado. Abra <strong>Recolha</strong> e recolha o registo da CNE.
              </p>
            ) : (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {registo.items.map((item) => (
                  <button
                    key={item.chave}
                    type="button"
                    onClick={() => void abrirPartido(item.chave)}
                    className="rounded-xl border px-3 py-2 text-left transition hover:border-primary/40 hover:bg-muted/40"
                  >
                    <div className="flex items-start gap-2">
                      {item.logotipo_url ? (
                        <img src={item.logotipo_url} alt="" className="h-8 w-8 shrink-0 rounded-lg border bg-white object-contain p-0.5" />
                      ) : null}
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium" title={item.denominacao}>
                          {item.denominacao}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {item.sigla || "—"}
                          {item.data_inscricao ? ` · ${shortDate(item.data_inscricao)}` : ""}
                        </p>
                      </div>
                    </div>
                    <div className="mt-1">
                      <Badge variant={item.situacao === "inscrito" ? "success" : "secondary"}>{item.situacao || "—"}</Badge>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </TabsContent>

          {/* ---------------------------------------------------------- recolha */}
          <TabsContent value="recolha" active={aba === "recolha"} className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle icon={<Database size={16} />}>Recolha e indexação</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-3">
                <p className="text-sm text-muted-foreground">
                  A pasta dos dados é <code className="rounded bg-muted px-1">{meta?.dir || "data/partidos"}</code>. A recolha
                  lê as páginas anuais do Tribunal Constitucional e o registo da CNE; a indexação escreve em{" "}
                  <code className="rounded bg-muted px-1">finance_partidos</code>,{" "}
                  <code className="rounded bg-muted px-1">finance_partidos_registo</code> e{" "}
                  <code className="rounded bg-muted px-1">finance_partidos_recolhas</code>.
                </p>
                <p className="text-xs text-muted-foreground">
                  As <strong>contas anuais</strong> e as <strong>listas de ações</strong> são digitalizações sem camada de
                  texto: dessas fica o documento e o número de páginas. Os <strong>relatórios</strong> e as{" "}
                  <strong>decisões</strong> da ECFP são digitais e ficam pesquisáveis palavra a palavra.
                </p>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={comPdf} onChange={(evento) => setComPdf(evento.target.checked)} />
                  Descarregar também os PDF (mais lento: ~350 documentos, centenas de MB)
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void arrancarRecolha(false)} icon={<Download size={14} />}>
                    Recolher
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => void arrancarRecolha(true)}>
                    Recolher de novo (forçar)
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => void arrancarIndexacao(false)} icon={<Database size={14} />}>
                    Indexar
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => void arrancarIndexacao(true)}>
                    Reindexar (forçar)
                  </Button>
                </div>

                {job ? (
                  <div className="rounded-xl border bg-muted/30 p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={job.status === "done" ? "success" : job.status === "error" ? "danger" : "info"}>
                        {job.tipo} · {job.status}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{job.progress?.phase || ""}</span>
                      {job.progress?.anos_total ? (
                        <span className="text-xs text-muted-foreground">
                          anos {job.progress.anos_done}/{job.progress.anos_total}
                        </span>
                      ) : null}
                      {job.progress?.registos ? (
                        <span className="text-xs text-muted-foreground">{count(job.progress.registos)} registos</span>
                      ) : null}
                      {job.status === "running" ? <Loader2 size={14} className="animate-spin" /> : null}
                    </div>
                    {job.progress?.current ? (
                      <p className="mt-1 truncate text-xs text-muted-foreground">{job.progress.current}</p>
                    ) : null}
                    {job.message ? <p className="mt-1 text-xs text-muted-foreground">{job.message}</p> : null}
                    {job.error ? <p className="mt-1 break-words text-xs text-destructive">{job.error}</p> : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle icon={<CalendarDays size={16} />}>Anos publicados pelo TC</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                    {(anos?.anos || []).map((item) => (
                      <div key={item.ano} className="rounded-lg border px-2 py-1.5">
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-sm font-medium tabular-nums">{item.ano}</span>
                          {item.recolhido ? (
                            <Badge variant={item.indexados ? "success" : "warning"}>
                              {item.indexados ? "indexado" : "lido"}
                            </Badge>
                          ) : (
                            <Badge variant="outline">por recolher</Badge>
                          )}
                        </div>
                        <p className="text-[11px] text-muted-foreground">
                          {count(item.itens)} entradas · {count(item.documentos)} docs
                          {item.digitalizados ? ` · ${count(item.digitalizados)} digitalizações` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle icon={<FileText size={16} />}>
                    Ficheiros em disco — {count(ficheiros?.pdf_total)} PDF ({bytes(ficheiros?.pdf_bytes)})
                  </CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-2 text-sm">
                  <p className="text-xs text-muted-foreground">
                    {(ficheiros?.paginas || []).length} página(s) do TC · {(ficheiros?.cne || []).length} ficheiro(s) da CNE ·{" "}
                    {(ficheiros?.jsonl || []).length} JSONL
                  </p>
                  <div className="max-h-64 space-y-1 overflow-y-auto">
                    {(ficheiros?.jsonl || []).map((item) => (
                      <div key={item.ficheiro} className="flex items-center justify-between gap-2 text-xs">
                        <span className="min-w-0 truncate">{item.ficheiro}</span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">{bytes(item.bytes)}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle icon={<Info size={16} />}>Fontes</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 grid gap-3 md:grid-cols-2">
                  {(meta?.fontes || []).map((fonte) => (
                    <div key={fonte.id} className="rounded-xl border p-3">
                      <p className="text-sm font-medium">{fonte.nome}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{fonte.descricao}</p>
                      <a
                        className="mt-1 inline-block text-xs text-muted-foreground underline-offset-2 hover:underline"
                        href={fonte.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ExternalLink size={12} className="mr-1 inline align-[-2px]" />
                        {fonte.url}
                      </a>
                      {fonte.secoes?.length ? (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {fonte.secoes.map((secao) => (
                            <Badge key={secao.id} variant="outline">
                              {secao.label}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
