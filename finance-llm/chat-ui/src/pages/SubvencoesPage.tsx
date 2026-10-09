/**
 * **Subvenções públicas** — listagem anual das subvenções e outros benefícios
 * públicos concedidos por entidades públicas (Lei n.º 64/2013, de 27/08).
 *
 * A IGF publica um `.ods` por ano (aqui: `data/subvencoes/2024/…` e
 * `data/subvencoes/lista-subvpublicas2025_1.ods`). A página lê essa pasta
 * **por ano**, indexa os registos e dá quatro leituras:
 *
 * 1. **Painel** — quanto foi atribuído, a quem e por quem, com totais por ano;
 * 2. **Pesquisa** — por ano, NIF, entidade, beneficiário, valor, datas e texto;
 * 3. **Ficha** — o que um NIF recebeu, ou o que uma entidade atribuiu;
 * 4. **Ficheiros** — o que está no disco, o que já foi lido e a indexação.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BadgeEuro,
  Building2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Coins,
  Database,
  Download,
  FileSpreadsheet,
  HandCoins,
  Info,
  Landmark,
  Loader2,
  RefreshCw,
  Search,
  TrendingUp,
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
  count,
  downloadSubvencoesCsv,
  getSubvencoesAmostra,
  getSubvencoesBeneficiario,
  getSubvencoesEntidade,
  getSubvencoesFicheiros,
  getSubvencoesJob,
  getSubvencoesLotes,
  getSubvencoesMeta,
  getSubvencoesResumo,
  indexarSubvencoes,
  lerSubvencoes,
  mesLabel,
  money,
  moneyShort,
  searchSubvencoes,
  shortDate,
  tipoLabel,
  type Subvencao,
  type SubvencoesFichaBeneficiario,
  type SubvencoesFichaEntidade,
  type SubvencoesFicheiro,
  type SubvencoesJob,
  type SubvencoesLotes,
  type SubvencoesMeta,
  type SubvencoesResumo,
  type SubvencoesSearchResult,
} from "../subvencoesApi";

type Aba = "painel" | "pesquisa" | "ficha" | "ficheiros";
type Ordenacao = "montante" | "data" | "beneficiario" | "entidade" | "ano";
type Ficha = SubvencoesFichaBeneficiario | SubvencoesFichaEntidade;

/** Filtros que a pesquisa usa (só mudam quando se carrega em «Pesquisar»). */
type Filtros = {
  q: string;
  ano?: number;
  nif_beneficiario?: string;
  nif_entidade?: string;
  tipo_ato?: string;
  beneficiario_tipo?: string;
  fundamento_legal?: string;
  montante_min?: number;
  montante_max?: number;
  data_from?: string;
  data_to?: string;
  sort: Ordenacao;
  order: "asc" | "desc";
};

const TAMANHO_PAGINA = 20;

const FILTROS_INICIAIS: Filtros = { q: "", sort: "montante", order: "desc" };

const TIPOS_BENEFICIARIO_OPCOES = [
  { valor: "", label: "Todos" },
  { valor: "pessoa_coletiva", label: "Pessoa coletiva" },
  { valor: "pessoa_singular", label: "Pessoa singular" },
  { valor: "entidade_publica", label: "Entidade pública" },
  { valor: "empresario_individual", label: "Empresário individual" },
  { valor: "outro", label: "Outro" },
];

/** Bordas laterais de um cartão de indicador. */
function Kpi({
  icon,
  label,
  valor,
  nota,
}: {
  icon: ReactNode;
  label: string;
  valor: string;
  nota?: string;
}) {
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
function Barras({
  itens,
  formatarValor = moneyShort,
  formatarChave = (chave: string) => chave,
}: {
  itens: { chave: string; valor: number; nota?: string }[];
  formatarValor?: (valor: number) => string;
  formatarChave?: (chave: string) => string;
}) {
  const maximo = Math.max(1, ...itens.map((item) => Math.abs(item.valor)));
  return (
    <div className="space-y-2">
      {itens.map((item) => (
        <div key={item.chave} className="space-y-1">
          <div className="flex items-baseline justify-between gap-3 text-xs">
            {/* `min-w-0` é obrigatório: sem ele um filho de `flex` com `truncate`
                não encolhe, cresce até à largura do texto e estoura o cartão. */}
            <span className="min-w-0 flex-1 truncate font-medium" title={item.chave}>
              {formatarChave(item.chave)}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {formatarValor(item.valor)}
              {item.nota ? <span className="ml-2 opacity-70">{item.nota}</span> : null}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-500"
              style={{ width: `${Math.max(2, (Math.abs(item.valor) / maximo) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Cartão de uma subvenção na lista (empilha em ecrãs estreitos). */
function LinhaSubvencao({ item, onAbrir }: { item: Subvencao; onAbrir: () => void }) {
  return (
    <button
      type="button"
      onClick={onAbrir}
      className="w-full rounded-xl border bg-card px-3 py-3 text-left transition hover:border-primary/40 hover:bg-muted/40"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium" title={item.beneficiario || ""}>
            {item.beneficiario || <span className="text-muted-foreground">Beneficiário não identificado</span>}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {item.nif_beneficiario ? `NIF ${item.nif_beneficiario}` : "sem NIF"}
            {item.beneficiario_estrangeiro ? " · estrangeiro" : ""}
            {" · "}
            {tipoLabel(item.beneficiario_tipo)}
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground" title={item.entidade || ""}>
            <Landmark size={12} className="mr-1 inline align-[-2px]" />
            {item.entidade || "Entidade desconhecida"}
            {item.nif_entidade ? ` (${item.nif_entidade})` : ""}
          </p>
        </div>
        <div className="text-right">
          <p className="whitespace-nowrap font-semibold tabular-nums">{money(item.montante)}</p>
          <p className="whitespace-nowrap text-xs text-muted-foreground">{shortDate(item.data_decisao)}</p>
          <div className="mt-1 flex justify-end gap-1">
            {item.ano ? <Badge variant="outline">lista {item.ano}</Badge> : null}
            {item.tipo_ato ? <Badge variant="secondary">{item.tipo_ato}</Badge> : null}
          </div>
        </div>
      </div>
    </button>
  );
}

export default function SubvencoesPage() {
  const [aba, setAba] = useState<Aba>("painel");
  const [meta, setMeta] = useState<SubvencoesMeta | null>(null);
  const [resumo, setResumo] = useState<SubvencoesResumo | null>(null);
  const [ficheiros, setFicheiros] = useState<SubvencoesFicheiro[]>([]);
  const [lotes, setLotes] = useState<SubvencoesLotes | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  // Rascunho dos filtros (só entram na pesquisa ao carregar em «Pesquisar»).
  const [rascunho, setRascunho] = useState<Filtros>(FILTROS_INICIAIS);
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_INICIAIS);
  const [pagina, setPagina] = useState(1);
  const [resultado, setResultado] = useState<SubvencoesSearchResult | null>(null);
  const [pesquisando, setPesquisando] = useState(false);

  const [detalhe, setDetalhe] = useState<Subvencao | null>(null);

  const [fichaTipo, setFichaTipo] = useState<"beneficiario" | "entidade">("beneficiario");
  const [fichaNif, setFichaNif] = useState("");
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [fichaErro, setFichaErro] = useState<string | null>(null);
  const [fichaCarregando, setFichaCarregando] = useState(false);

  const [job, setJob] = useState<SubvencoesJob | null>(null);
  const [amostra, setAmostra] = useState<{ ano: number; total: number; items: Subvencao[] } | null>(null);

  const anosDisponiveis = useMemo(() => {
    const valores = new Set<number>();
    (meta?.anos || []).forEach((item) => {
      if (item.ano !== null && item.ano !== undefined) valores.add(item.ano);
    });
    (resumo?.por_ano || []).forEach((item) => {
      if (item.ano !== null && item.ano !== undefined) valores.add(item.ano);
    });
    return Array.from(valores).sort((a, b) => b - a);
  }, [meta, resumo]);

  const recarregar = useCallback(async () => {
    setErro(null);
    try {
      const [dadosMeta, dadosFicheiros, dadosLotes] = await Promise.all([
        getSubvencoesMeta(),
        getSubvencoesFicheiros(),
        getSubvencoesLotes(),
      ]);
      setMeta(dadosMeta);
      setFicheiros(dadosFicheiros.items || []);
      setLotes(dadosLotes);
      try {
        setResumo(await getSubvencoesResumo());
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
    searchSubvencoes({ ...filtros, page: pagina, size: TAMANHO_PAGINA })
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

  // Progresso dos trabalhos de leitura/indexação.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const temporizador = window.setInterval(() => {
      getSubvencoesJob(job.job_id)
        .then((atual) => {
          setJob(atual);
          if (atual.status !== "running") {
            void recarregar();
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(temporizador);
  }, [job, recarregar]);

  const pesquisar = useCallback(() => {
    setPagina(1);
    setDetalhe(null);
    setFiltros({ ...rascunho });
    setAba("pesquisa");
  }, [rascunho]);

  const abrirFicha = useCallback(async (nif: string, tipo: "beneficiario" | "entidade") => {
    if (!nif) return;
    setFichaTipo(tipo);
    setFichaNif(nif);
    setAba("ficha");
    setFichaCarregando(true);
    setFichaErro(null);
    setFicha(null);
    try {
      const dados = tipo === "beneficiario" ? await getSubvencoesBeneficiario(nif) : await getSubvencoesEntidade(nif);
      setFicha(dados);
    } catch (falha) {
      setFichaErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setFichaCarregando(false);
    }
  }, []);

  const executarAmostra = useCallback(async (ano: number) => {
    try {
      setAmostra(await getSubvencoesAmostra(ano, 20));
    } catch (falha) {
      setAviso(falha instanceof Error ? falha.message : String(falha));
    }
  }, []);

  const iniciarLer = useCallback(
    async (forcar: boolean) => {
      try {
        setAviso(null);
        setJob(await lerSubvencoes({ forcar }));
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : String(falha));
      }
    },
    []
  );

  const iniciarIndexar = useCallback(async (forcar: boolean) => {
    try {
      setAviso(null);
      setJob(await indexarSubvencoes({ forcar }));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    }
  }, []);

  const exportar = useCallback(async () => {
    try {
      await downloadSubvencoesCsv({ ...filtros });
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    }
  }, [filtros]);

  const kpis = resultado?.kpis;
  const kpisResumo = resumo?.kpis;

  // A ficha pode ser de beneficiário (tem `tipo`) ou de entidade (tem `beneficiarios`).
  const fichaLista = ficha ? ("entidades" in ficha && ficha.entidades ? ficha.entidades : "beneficiarios" in ficha && ficha.beneficiarios ? ficha.beneficiarios : []) : [];
  const fichaListaTitulo = ficha && "entidades" in ficha ? "Entidades que atribuíram" : "Beneficiários";
  const fichaTipoBeneficiario = ficha && "tipo" in ficha ? ficha.tipo : null;
  const fichaRotuloLista = fichaListaTitulo === "Entidades que atribuíram" ? "Entidades" : "Beneficiários";

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-4 py-4 md:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-emerald-400 to-sky-600 text-white shadow-lg shadow-emerald-500/25">
              <HandCoins size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Subvenções públicas</h1>
              <p className="text-sm text-muted-foreground">
                Subvenções e outros benefícios públicos por ano (Lei n.º 64/2013, de 27/08)
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {meta ? (
              <Badge variant="outline" className="gap-1">
                <Database size={12} /> {count(meta.indice?.registos)} indexados
              </Badge>
            ) : null}
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
            <span className="min-w-0 break-words">
              Painel indisponível: {aviso}
            </span>
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
                ["ficha", "Ficha"],
                ["ficheiros", "Ficheiros"],
              ] as const
            ).map(([valor, label]) => (
              <TabsTrigger key={valor} value={valor} active={aba === valor} onClick={() => setAba(valor)}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* ---------------------------------------------------------- painel */}
          <TabsContent value="painel" active={aba === "painel"} className="space-y-4">
            {carregando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A carregar…
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi
                icon={<Coins size={16} />}
                label="Montante atribuído"
                valor={carregando && !kpisResumo ? "…" : moneyShort(kpisResumo?.montante)}
                nota={carregando && !kpisResumo ? "a carregar" : `${count(kpisResumo?.registos)} registos`}
              />
              <Kpi
                icon={<Users size={16} />}
                label="Beneficiários distintos"
                valor={carregando && !kpisResumo ? "…" : count(kpisResumo?.beneficiarios)}
                nota="por NIF/NIPC"
              />
              <Kpi
                icon={<Landmark size={16} />}
                label="Entidades obrigadas"
                valor={carregando && !kpisResumo ? "…" : count(kpisResumo?.entidades)}
                nota="quem reporta"
              />
              <Kpi
                icon={<FileSpreadsheet size={16} />}
                label="Anos lidos"
                valor={carregando && !meta ? "…" : count(meta?.lidos)}
                nota={`${count(meta?.ficheiros_disco)} ficheiro(s) no disco`}
              />
            </div>

            <Card>
              <CardHeader>
                <CardTitle icon={<CalendarDays size={16} />}>Por ano de listagem</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-3">
                {carregando && (resumo?.por_ano || []).length === 0 ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 size={14} className="animate-spin" /> A ler a pasta e a consultar o índice…
                  </p>
                ) : (resumo?.por_ano || []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Sem dados indexados. Abra o separador <strong>Ficheiros</strong> e leia a pasta.
                  </p>
                ) : (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {(resumo?.por_ano || []).map((item) => (
                      <div key={String(item.ano)} className="rounded-xl border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold">{item.ano ?? "sem ano"}</span>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setRascunho({ ...FILTROS_INICIAIS, ano: item.ano ?? undefined });
                              setFiltros({ ...FILTROS_INICIAIS, ano: item.ano ?? undefined });
                              setPagina(1);
                              setAba("pesquisa");
                            }}
                          >
                            ver registos
                          </Button>
                        </div>
                        <p className="mt-1 text-lg font-semibold tabular-nums">{moneyShort(item.montante)}</p>
                        <p className="text-xs text-muted-foreground">
                          {count(item.registos)} registos · {count(item.beneficiarios)} beneficiários ·{" "}
                          {count(item.entidades)} entidades
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {(item.tipo_ato || []).slice(0, 4).map((tipo) => (
                            <Badge key={String(tipo.key)} variant="secondary">
                              {tipo.key || "—"} · {count(tipo.count)}
                            </Badge>
                          ))}
                        </div>
                        <button
                          type="button"
                          className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:underline"
                          onClick={() => void executarAmostra(item.ano ?? 0)}
                        >
                          ver amostra lida do disco
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {amostra ? (
                  <div className="rounded-xl border bg-muted/30 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">
                        Amostra de {amostra.ano} — {count(amostra.total)} registos lidos em disco
                      </p>
                      <button type="button" onClick={() => setAmostra(null)}>
                        <X size={14} />
                      </button>
                    </div>
                    <div className="space-y-2">
                      {amostra.items.map((item) => (
                        <div key={item.doc_id} className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                          <span className="min-w-0 truncate">{item.beneficiario}</span>
                          <span className="shrink-0 tabular-nums">
                            {money(item.montante)} · {shortDate(item.data_decisao)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle icon={<Landmark size={16} />}>Quem mais atribuiu</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  <Barras
                    itens={(resumo?.top_entidades || []).slice(0, 10).map((item) => ({
                      chave: item.nome || String(item.key || "—"),
                      valor: item.montante || 0,
                      nota: `${count(item.count)} reg.`,
                    }))}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle icon={<BadgeEuro size={16} />}>Quem mais recebeu</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  <Barras
                    itens={(resumo?.top_beneficiarios || []).slice(0, 10).map((item) => ({
                      chave: item.nome || String(item.key || "—"),
                      valor: item.montante || 0,
                      nota: `${count(item.count)} reg.`,
                    }))}
                  />
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
              <Card>
                <CardHeader>
                  <CardTitle icon={<TrendingUp size={16} />}>Decisões por mês</CardTitle>
                </CardHeader>
                <CardContent className="mt-3">
                  {carregando && (resumo?.por_mes || []).length === 0 ? (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 size={14} className="animate-spin" /> a carregar…
                    </p>
                  ) : (resumo?.por_mes || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">Sem datas de decisão nos dados indexados.</p>
                  ) : (
                    <>
                      <Barras
                        itens={(resumo?.por_mes || [])
                          .filter((mes) => mes.count > 0)
                          .slice(-18)
                          .map((mes) => ({
                            chave: String(mes.key || ""),
                            valor: mes.montante,
                            nota: `${count(mes.count)} reg.`,
                          }))}
                        formatarChave={mesLabel}
                      />
                      <p className="mt-3 text-xs text-muted-foreground">
                        O mesmo apoio pode aparecer em mais do que uma listagem anual: o filtro por ano
                        (`lista 2024` / `lista 2025`) mostra a versão de cada ficheiro.
                      </p>
                    </>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle icon={<Users size={16} />}>Tipo de beneficiário</CardTitle>
                </CardHeader>
                <CardContent className="mt-3 space-y-2">
                  {(resumo?.por_tipo_beneficiario || []).map((item) => (
                    <div key={String(item.key)} className="flex items-center justify-between gap-2 text-sm">
                      <span className="min-w-0 flex-1 truncate">{item.label || tipoLabel(item.key)}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{count(item.count)}</span>
                    </div>
                  ))}
                  <p className="pt-2 text-xs text-muted-foreground">
                    O tipo é deduzido do prefixo do NIF — o ficheiro da IGF não publica o tipo.
                  </p>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* -------------------------------------------------------- pesquisa */}
          <TabsContent value="pesquisa" active={aba === "pesquisa"} className="space-y-4">
            <Card>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="subv-q">Texto livre</Label>
                    <Input
                      id="subv-q"
                      value={rascunho.q}
                      autoComplete="off"
                      onChange={(evento) => setRascunho({ ...rascunho, q: evento.target.value })}
                      onKeyDown={(evento) => {
                        if (evento.key === "Enter") pesquisar();
                      }}
                      placeholder="Beneficiário, entidade, finalidade ou NIF"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-ano">Ano da listagem</Label>
                    <select
                      id="subv-ano"
                      className="h-10 w-full rounded-xl border bg-background px-3 text-sm"
                      value={rascunho.ano ?? ""}
                      onChange={(evento) =>
                        setRascunho({ ...rascunho, ano: evento.target.value ? Number(evento.target.value) : undefined })
                      }
                    >
                      <option value="">Todos os anos</option>
                      {anosDisponiveis.map((valor) => (
                        <option key={valor} value={valor}>
                          {valor}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-tipo-benef">Tipo de beneficiário</Label>
                    <select
                      id="subv-tipo-benef"
                      className="h-10 w-full rounded-xl border bg-background px-3 text-sm"
                      value={rascunho.beneficiario_tipo ?? ""}
                      onChange={(evento) =>
                        setRascunho({ ...rascunho, beneficiario_tipo: evento.target.value || undefined })
                      }
                    >
                      {TIPOS_BENEFICIARIO_OPCOES.map((opcao) => (
                        <option key={opcao.valor} value={opcao.valor}>
                          {opcao.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-nif-benef">NIF do beneficiário</Label>
                    <Input
                      id="subv-nif-benef"
                      value={rascunho.nif_beneficiario ?? ""}
                      autoComplete="off"
                      inputMode="numeric"
                      onChange={(evento) => setRascunho({ ...rascunho, nif_beneficiario: evento.target.value })}
                      placeholder="500189412"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-nif-ent">NIF da entidade</Label>
                    <Input
                      id="subv-nif-ent"
                      value={rascunho.nif_entidade ?? ""}
                      autoComplete="off"
                      inputMode="numeric"
                      onChange={(evento) => setRascunho({ ...rascunho, nif_entidade: evento.target.value })}
                      placeholder="500051054"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-montante-min">Montante mínimo (€)</Label>
                    <Input
                      id="subv-montante-min"
                      value={rascunho.montante_min ?? ""}
                      autoComplete="off"
                      inputMode="decimal"
                      onChange={(evento) =>
                        setRascunho({
                          ...rascunho,
                          montante_min: evento.target.value ? Number(evento.target.value) : undefined,
                        })
                      }
                      placeholder="1000000"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-decisao-from">Decisão de</Label>
                    <Input
                      id="subv-decisao-from"
                      type="date"
                      value={rascunho.data_from ?? ""}
                      onChange={(evento) => setRascunho({ ...rascunho, data_from: evento.target.value || undefined })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-decisao-to">Decisão até</Label>
                    <Input
                      id="subv-decisao-to"
                      type="date"
                      value={rascunho.data_to ?? ""}
                      onChange={(evento) => setRascunho({ ...rascunho, data_to: evento.target.value || undefined })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="subv-ordenar">Ordenar por</Label>
                    <select
                      id="subv-ordenar"
                      className="h-10 w-full rounded-xl border bg-background px-3 text-sm"
                      value={`${rascunho.sort}:${rascunho.order}`}
                      onChange={(evento) => {
                        const [sort, order] = evento.target.value.split(":") as [Ordenacao, "asc" | "desc"];
                        setRascunho({ ...rascunho, sort, order });
                      }}
                    >
                      <option value="montante:desc">Montante (maior primeiro)</option>
                      <option value="montante:asc">Montante (menor primeiro)</option>
                      <option value="data:desc">Data da decisão (recente)</option>
                      <option value="data:asc">Data da decisão (antiga)</option>
                      <option value="beneficiario:asc">Beneficiário (A→Z)</option>
                      <option value="entidade:asc">Entidade (A→Z)</option>
                      <option value="ano:desc">Ano da listagem</option>
                    </select>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={pesquisar}>
                    <Search size={14} className="mr-1.5" /> Pesquisar
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setRascunho(FILTROS_INICIAIS);
                      setFiltros(FILTROS_INICIAIS);
                      setPagina(1);
                    }}
                  >
                    Limpar
                  </Button>
                  <Button variant="outline" onClick={() => void exportar()}>
                    <Download size={14} className="mr-1.5" /> Exportar CSV
                  </Button>
                  {pesquisando ? (
                    <span className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 size={14} className="animate-spin" /> a pesquisar…
                    </span>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            {resultado ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Kpi icon={<Coins size={16} />} label="Registos" valor={count(resultado.total)} nota={`${resultado.pages} página(s)`} />
                <Kpi icon={<BadgeEuro size={16} />} label="Montante" valor={moneyShort(kpis?.montante)} />
                <Kpi
                  icon={<Users size={16} />}
                  label="Beneficiários"
                  valor={count(kpis?.beneficiarios_distintos)}
                  nota="distintos no filtro"
                />
                <Kpi
                  icon={<Landmark size={16} />}
                  label="Entidades"
                  valor={count(kpis?.entidades_distintas)}
                  nota="distintas no filtro"
                />
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
              <div className="space-y-2">
                {(resultado?.items || []).map((item) => (
                  <LinhaSubvencao key={item.doc_id} item={item} onAbrir={() => setDetalhe(item)} />
                ))}
                {resultado && resultado.items.length === 0 && !pesquisando ? (
                  <p className="rounded-xl border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
                    Sem resultados para estes filtros.
                  </p>
                ) : null}
                {resultado && resultado.pages > 1 ? (
                  <div className="flex items-center justify-between gap-3 pt-1">
                    <Button variant="outline" size="sm" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>
                      <ChevronLeft size={14} className="mr-1" /> Anterior
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      página {resultado.page} de {resultado.pages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={pagina >= resultado.pages}
                      onClick={() => setPagina(pagina + 1)}
                    >
                      Seguinte <ChevronRight size={14} className="ml-1" />
                    </Button>
                  </div>
                ) : null}
              </div>

              <div className="space-y-3">
                {detalhe ? (
                  <Card>
                    <CardHeader>
                      <CardTitle icon={<HandCoins size={16} />}>Registo</CardTitle>
                      <button type="button" className="opacity-70" onClick={() => setDetalhe(null)}>
                        <X size={14} />
                      </button>
                    </CardHeader>
                    <CardContent className="mt-3 space-y-3 text-sm">
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Montante</p>
                        <p className="text-lg font-semibold tabular-nums">{money(detalhe.montante)}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Decisão</p>
                        <p>{shortDate(detalhe.data_decisao)}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Beneficiário</p>
                        <p className="break-words">{detalhe.beneficiario || "—"}</p>
                        <p className="text-xs text-muted-foreground">
                          {detalhe.nif_beneficiario ? `NIF ${detalhe.nif_beneficiario}` : "sem NIF"} ·{" "}
                          {tipoLabel(detalhe.beneficiario_tipo)}
                          {detalhe.beneficiario_estrangeiro ? " · estrangeiro (nota b)" : ""}
                        </p>
                        {detalhe.nif_beneficiario ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="mt-1 px-0"
                            onClick={() => void abrirFicha(String(detalhe.nif_beneficiario), "beneficiario")}
                          >
                            abrir ficha do beneficiário →
                          </Button>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Entidade obrigada</p>
                        <p className="break-words">{detalhe.entidade || "—"}</p>
                        <p className="text-xs text-muted-foreground">
                          {detalhe.nif_entidade ? `NIF ${detalhe.nif_entidade}` : "sem NIF"}
                        </p>
                        {detalhe.nif_entidade ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="mt-1 px-0"
                            onClick={() => void abrirFicha(String(detalhe.nif_entidade), "entidade")}
                          >
                            abrir ficha da entidade →
                          </Button>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Finalidade</p>
                        <p className="whitespace-pre-line break-words text-xs">{detalhe.finalidade || "—"}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase text-muted-foreground">Fundamento legal</p>
                        <p className="text-xs">
                          {detalhe.fundamento_legal || "—"}
                          {detalhe.data_ato ? ` · ${shortDate(detalhe.data_ato)}` : ""}
                        </p>
                      </div>
                      <div className="border-t pt-2 text-xs text-muted-foreground">
                        <p>
                          Listagem de <strong>{detalhe.ano ?? "—"}</strong> · linha {detalhe.linha} ·{" "}
                          {detalhe.folha || detalhe.ficheiro}
                        </p>
                        <p className="break-all">{detalhe.ficheiro}</p>
                      </div>
                    </CardContent>
                  </Card>
                ) : null}

                <Card>
                  <CardHeader>
                    <CardTitle icon={<Landmark size={16} />}>Resumo do filtro</CardTitle>
                  </CardHeader>
                  <CardContent className="mt-3 space-y-4">
                    <div>
                      <p className="mb-2 text-xs uppercase text-muted-foreground">Entidades (por montante)</p>
                      <Barras
                        itens={(resultado?.facets.top_entidades || []).slice(0, 6).map((item) => ({
                          chave: item.nome || String(item.key || "—"),
                          valor: item.montante || 0,
                          nota: `${count(item.count)} reg.`,
                        }))}
                      />
                    </div>
                    <div>
                      <p className="mb-2 text-xs uppercase text-muted-foreground">Beneficiários (por montante)</p>
                      <Barras
                        itens={(resultado?.facets.top_beneficiarios || []).slice(0, 6).map((item) => ({
                          chave: item.nome || String(item.key || "—"),
                          valor: item.montante || 0,
                          nota: `${count(item.count)} reg.`,
                        }))}
                      />
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </TabsContent>

          {/* ------------------------------------------------------------ ficha */}
          <TabsContent value="ficha" active={aba === "ficha"} className="space-y-4">
            <Card>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[200px] flex-1 space-y-2">
                    <Label htmlFor="subv-ficha-nif">NIF</Label>
                    <Input
                      id="subv-ficha-nif"
                      value={fichaNif}
                      autoComplete="off"
                      inputMode="numeric"
                      onChange={(evento) => setFichaNif(evento.target.value)}
                      onKeyDown={(evento) => {
                        if (evento.key === "Enter") void abrirFicha(fichaNif, fichaTipo);
                      }}
                      placeholder="500189412"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Perspetiva</Label>
                    <div className="flex rounded-xl border p-1">
                      {(
                        [
                          ["beneficiario", "Recebeu"],
                          ["entidade", "Atribuiu"],
                        ] as const
                      ).map(([valor, label]) => (
                        <button
                          key={valor}
                          type="button"
                          onClick={() => setFichaTipo(valor)}
                          className={`rounded-lg px-3 py-2 text-sm transition ${
                            fichaTipo === valor
                              ? "bg-primary text-primary-foreground shadow-sm"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <Button onClick={() => void abrirFicha(fichaNif, fichaTipo)}>
                    <Search size={14} className="mr-1.5" /> Abrir ficha
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  «Recebeu» mostra o que o NIF recebeu de todas as entidades públicas; «Atribuiu» mostra o que
                  uma entidade pública deu, por beneficiário.
                </p>
              </CardContent>
            </Card>

            {fichaCarregando ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> A abrir ficha…
              </div>
            ) : null}
            {fichaErro ? (
              <p className="rounded-xl border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">{fichaErro}</p>
            ) : null}

            {ficha ? (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle icon={<Building2 size={16} />}>{ficha.nome || ficha.nif}</CardTitle>
                    <Badge variant="outline">NIF {ficha.nif}</Badge>
                  </CardHeader>
                  <CardContent className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <Kpi icon={<Coins size={16} />} label="Total" valor={money(ficha.montante)} nota={`${count(ficha.total)} registos`} />
                    <Kpi
                      icon={<CalendarDays size={16} />}
                      label="Anos"
                      valor={count((ficha.por_ano || []).length)}
                      nota={(ficha.por_ano || []).map((item) => item.ano).join(", ") || "—"}
                    />
                    {"tipo" in ficha ? (
                      <Kpi icon={<Users size={16} />} label="Tipo" valor={tipoLabel(fichaTipoBeneficiario)} />
                    ) : null}
                    <Kpi
                      icon={<Landmark size={16} />}
                      label={fichaRotuloLista}
                      valor={count(fichaLista.length)}
                      nota="acima do limite de listagem"
                    />
                  </CardContent>
                </Card>

                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle icon={<CalendarDays size={16} />}>Por ano de listagem</CardTitle>
                    </CardHeader>
                    <CardContent className="mt-3">
                      <Barras
                        itens={(ficha.por_ano || []).map((item) => ({
                          chave: String(item.ano),
                          valor: item.montante,
                          nota: `${count(item.registos)} reg.`,
                        }))}
                        formatarChave={(chave) => `Listagem ${chave}`}
                      />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle icon={<Landmark size={16} />}>{fichaListaTitulo}</CardTitle>
                    </CardHeader>
                    <CardContent className="mt-3">
                      <Barras
                        itens={fichaLista.slice(0, 10).map((item) => ({
                          chave: item.nome || String(item.nif || "—"),
                          valor: item.montante,
                          nota: `${count(item.registos)} reg.`,
                        }))}
                      />
                    </CardContent>
                  </Card>
                </div>

                <div className="space-y-2">
                  {(ficha.items || []).slice(0, 60).map((item) => (
                    <LinhaSubvencao
                      key={item.doc_id}
                      item={item}
                      onAbrir={() => {
                        setDetalhe(item);
                        setAba("pesquisa");
                      }}
                    />
                  ))}
                  {(ficha.items || []).length > 60 ? (
                    <p className="text-xs text-muted-foreground">
                      A mostrar 60 de {count(ficha.items.length)} registos desta ficha (limite de listagem).
                    </p>
                  ) : null}
                </div>
              </>
            ) : null}
          </TabsContent>

          {/* -------------------------------------------------------- ficheiros */}
          <TabsContent value="ficheiros" active={aba === "ficheiros"} className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle icon={<FileSpreadsheet size={16} />}>Pasta de dados</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-3">
                <p className="break-all text-xs text-muted-foreground">
                  {meta?.dir || "—"} <span className="opacity-70">({meta?.dir_env})</span>
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void iniciarLer(false)} disabled={job?.status === "running"}>
                    <RefreshCw size={14} className="mr-1.5" /> Ler pasta (por ano)
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void iniciarLer(true)}
                    disabled={job?.status === "running"}
                  >
                    Reler tudo
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void iniciarIndexar(false)}
                    disabled={job?.status === "running"}
                  >
                    <Database size={14} className="mr-1.5" /> Indexar
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void iniciarIndexar(true)}
                    disabled={job?.status === "running"}
                  >
                    Reindexar
                  </Button>
                </div>
                {job ? (
                  <div className="rounded-xl border bg-muted/30 px-4 py-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">
                        {job.tipo === "ler" ? "Leitura" : "Indexação"} · {job.status}
                        {job.already_running ? " (já a correr)" : ""}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {count(job.progress?.ficheiros_done)}/{count(job.progress?.ficheiros_total)} ficheiros ·{" "}
                        {count(job.progress?.registos)} registos
                      </span>
                    </div>
                    {job.progress?.phase ? (
                      <p className="mt-1 text-xs text-muted-foreground">{job.progress.phase}</p>
                    ) : null}
                    {job.progress?.current ? (
                      <p className="mt-1 break-all text-xs text-muted-foreground">{job.progress.current}</p>
                    ) : null}
                    {job.status === "running" ? (
                      <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 size={12} className="animate-spin" /> a decorrer… (cada ficheiro tem ~200 mil
                        linhas)
                      </p>
                    ) : null}
                    {job.message ? <p className="mt-1 text-xs">{job.message}</p> : null}
                    {job.error ? <p className="mt-1 text-xs text-amber-600">{job.error}</p> : null}
                    {job.result ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        {job.result.lidos_total !== undefined
                          ? `${count(job.result.lidos_total)} ficheiro(s) lido(s), ${count(
                              job.result.reutilizados_total
                            )} já estavam lidos, ${count(job.result.registos)} registos.`
                          : `${count(job.result.indexados)} registos indexados em ${count(
                              job.result.ficheiros
                            )} ficheiro(s).`}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle icon={<CalendarDays size={16} />}>Ficheiros por ano</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-2">
                {(meta?.anos || []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nenhum `.ods` encontrado nesta pasta. Coloque os ficheiros da IGF em{" "}
                    <code className="rounded bg-muted px-1">{meta?.dir || "data/subvencoes"}</code> — um por ano,
                    ou numa subpasta por ano (ex.: <code className="rounded bg-muted px-1">2024/</code>).
                  </p>
                ) : (
                  (meta?.anos || []).map((item) => (
                    <div key={String(item.ano)} className="rounded-xl border p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">{item.ano ?? "sem ano"}</span>
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span>{count(item.ficheiros)} ficheiro(s)</span>
                          <span>{bytes(item.bytes)}</span>
                          <span>{count(item.registos)} registos</span>
                          <span>{money(item.montante)}</span>
                          {item.pendentes > 0 ? (
                            <Badge variant="warning">{count(item.pendentes)} por ler</Badge>
                          ) : (
                            <Badge variant="success">lido</Badge>
                          )}
                        </div>
                      </div>
                      <div className="mt-2 space-y-1">
                        {item.ficheiros_disco.map((ficheiro) => (
                          <p key={ficheiro.rel_path} className="break-all text-xs text-muted-foreground">
                            {ficheiro.rel_path} · {bytes(ficheiro.bytes)} · ano pelo {ficheiro.ano_origem || "?"}
                          </p>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle icon={<Database size={16} />}>Lotes lidos</CardTitle>
              </CardHeader>
              <CardContent className="mt-3 space-y-2">
                {lotes && lotes.items.length > 0 ? (
                  <>
                    <p className="text-xs text-muted-foreground">
                      {count(lotes.registos)} registos lidos de {count(lotes.total)} ficheiro(s) ·{" "}
                      {money(lotes.montante)}
                    </p>
                    {lotes.items.map((lote) => (
                      <div key={lote.rel_path} className="rounded-xl border p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="break-all text-sm font-medium">{lote.rel_path}</span>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <Badge variant="outline">{lote.ano ?? "sem ano"}</Badge>
                            {lote.indexados !== undefined && lote.indexados > 0 ? (
                              <Badge variant="success">{count(lote.indexados)} indexados</Badge>
                            ) : (
                              <Badge variant="warning">por indexar</Badge>
                            )}
                          </div>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          folha {lote.folha || "—"} · {count(lote.registos)} registos ·{" "}
                          {count(lote.ignoradas)} linhas ignoradas · {money(lote.montante_total)} · decisões{" "}
                          {shortDate(lote.primeira_decisao)} a {shortDate(lote.ultima_decisao)}
                        </p>
                      </div>
                    ))}
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Ainda não há ficheiros lidos. Use <strong>Ler pasta (por ano)</strong>.
                  </p>
                )}
                {ficheiros.length === 0 && meta && meta.ficheiros_disco > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    A pasta tem {count(meta.ficheiros_disco)} ficheiro(s) detetado(s).
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
