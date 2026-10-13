/**
 * **Administração Central** — as entidades do Setor Institucional das
 * Administrações Públicas (INE / SEC 2010) e os contratos que adjudicam.
 *
 * O INE publica todos os anos, em PDF, a lista das entidades do setor S.13.
 * A página serve o índice construído a partir desse PDF:
 *
 * 1. **Entidades** — a lista pesquisável (Estado, Serviços e Fundos Autónomos e
 *    Instituições Sem Fim Lucrativo), com o NIF com que cada uma contrata, o
 *    valor adjudicado e o tipo de ligação ao cadastro do portal BASE;
 * 2. **Analíticas** — volume e valor dos contratos do setor, evolução anual,
 *    ranking de entidades compradoras, adjudicatárias, CPV e procedimentos;
 * 3. **Contratos** — pesquisa dos contratos adjudicados pelo setor (entidade,
 *    adjudicatária, ano, CPV e valor).
 *
 * Abrir uma entidade mostra a **ficha**: quanto adjudicou, a quem comprou, o que
 * comprou e os contratos mais recentes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart as RePieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Banknote,
  Building2,
  CircleAlert,
  Download,
  ExternalLink,
  FileText,
  Filter,
  Handshake,
  Info,
  Landmark,
  Loader2,
  PackageSearch,
  RefreshCw,
  Search,
  ShoppingCart,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/Tabs";
import { openWindow } from "../windows";
import {
  LIGACAO_LABEL,
  count,
  downloadAdministracaoCentralCsv,
  getAdministracaoCentralAnaliticas,
  getAdministracaoCentralEntidade,
  getAdministracaoCentralMeta,
  money,
  moneyShort,
  reindexarAdministracaoCentral,
  searchAdministracaoCentralContratos,
  searchAdministracaoCentralEntidades,
  shortDate,
  type AdministracaoCentralAnaliticas,
  type AdministracaoCentralContrato,
  type AdministracaoCentralContratosResultado,
  type AdministracaoCentralEntidadesResultado,
  type AdministracaoCentralFicha,
  type AdministracaoCentralLinha,
  type AdministracaoCentralLigacao,
  type AdministracaoCentralMeta,
} from "../administracaoCentralApi";

/* ------------------------------------------------------------------ apoio */

const CORES = ["#10a37f", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#6366f1"];

const TOM_LIGACAO: Record<AdministracaoCentralLigacao, "success" | "info" | "warning" | "outline" | "danger" | "secondary"> = {
  exato: "success",
  nome: "success",
  prefixo: "info",
  sigla: "info",
  forte: "warning",
  manual: "secondary",
  nenhuma: "outline",
};

/** Tamanho de página da lista de entidades. */
const PAGINA = 30;

type Aba = "entidades" | "analiticas" | "contratos";

type Filtros = {
  q: string;
  subsetor: string;
  ligacao: "" | "com_nif" | "sem_nif" | "com_contratos";
  ordenar: "nome" | "contratos" | "valor" | "subsetor";
};

type FiltrosContratos = {
  q: string;
  subsetor: string;
  ano: string;
  adjudicatario: string;
  cpv: string;
  precoMin: string;
  precoMax: string;
};

const FILTROS_INICIAIS: Filtros = { q: "", subsetor: "", ligacao: "", ordenar: "valor" };
const FILTROS_CONTRATOS_INICIAIS: FiltrosContratos = {
  q: "",
  subsetor: "",
  ano: "",
  adjudicatario: "",
  cpv: "",
  precoMin: "",
  precoMax: "",
};

/** Nome de uma parte de um contrato (adjudicante ou adjudicatária). */
function partes(contrato: AdministracaoCentralContrato, papel: "adjudicantes" | "adjudicatarios"): string {
  const lista = contrato[papel]?.parsed || [];
  return lista.map((parte) => parte?.nome).filter(Boolean).join(", ");
}

function numeroOuNulo(valor: string): number | undefined {
  const limpo = valor.replace(/\s/g, "").replace(",", ".");
  if (!limpo) return undefined;
  const numero = Number(limpo);
  return Number.isFinite(numero) ? numero : undefined;
}

function useDebounce<T>(value: T, delay = 350) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = "text-teal-400",
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="glass-card gradient-border rounded-2xl p-4 md:p-5">
      <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
        <Icon size={18} className={tone} />
        {label}
      </div>
      <p className="stat-value text-xl font-bold md:text-2xl">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

/** Barras horizontais com o valor (ranking de entidades, adjudicatárias, CPV). */
function Ranking({
  titulo,
  icon,
  linhas,
  escolherValor = "valor",
  aoAbrir,
}: {
  titulo: string;
  icon: React.ReactNode;
  linhas: { chave: string; nome: string; valor: number; contratos: number }[];
  escolherValor?: "valor" | "contratos";
  aoAbrir?: (chave: string) => void;
}) {
  const maximo = Math.max(...linhas.map((linha) => (escolherValor === "valor" ? linha.valor : linha.contratos)), 0);
  return (
    <Card>
      <CardHeader className="mb-3">
        <CardTitle icon={icon}>{titulo}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {escolherValor === "valor" ? "valor adjudicado" : "nº de contratos"}
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        {linhas.length === 0 ? <p className="text-sm text-muted-foreground">Sem dados.</p> : null}
        {linhas.map((linha) => {
          const grandeza = escolherValor === "valor" ? linha.valor : linha.contratos;
          const largura = maximo > 0 ? Math.max(2, (grandeza / maximo) * 100) : 0;
          return (
            <div key={linha.chave} className="space-y-1">
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <button
                  type="button"
                  onClick={() => aoAbrir?.(linha.chave)}
                  className={`min-w-0 flex-1 truncate text-left ${
                    aoAbrir ? "text-foreground hover:text-primary hover:underline" : "text-foreground"
                  }`}
                  title={linha.nome}
                >
                  {linha.nome}
                </button>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {escolherValor === "valor" ? moneyShort(linha.valor) : count(linha.contratos)}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-500"
                  style={{ width: `${largura}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/** Gráfico de barras simples a partir de linhas `{key, count, valor}`. */
function Barras({ dados, x, y, rotulo }: { dados: { nome: string; valor: number }[]; x: string; y: string; rotulo: string }) {
  if (dados.length === 0) return <p className="text-sm text-muted-foreground">Sem dados.</p>;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={dados} margin={{ top: 4, right: 8, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" vertical={false} />
        <XAxis dataKey={x} tick={{ fontSize: 11 }} stroke="#94a3b8" />
        <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" width={70} tickFormatter={(v) => moneyShort(Number(v))} />
        <Tooltip
          formatter={(valor) => [moneyShort(Number(valor)), rotulo]}
          contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 12 }}
          labelStyle={{ color: "#e2e8f0" }}
        />
        <Bar dataKey={y} fill="#10a37f" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Tarteira com as primeiras linhas (procedimentos, tipo de contrato…). */
function Tarteira({ dados }: { dados: { nome: string; valor: number }[] }) {
  const visiveis = dados.slice(0, 8);
  if (visiveis.length === 0) return <p className="text-sm text-muted-foreground">Sem dados.</p>;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <RePieChart>
        <Pie data={visiveis} dataKey="valor" nameKey="nome" innerRadius={45} outerRadius={80} paddingAngle={2}>
          {visiveis.map((linha, indice) => (
            <Cell key={linha.nome} fill={CORES[indice % CORES.length]} stroke="rgba(0,0,0,0.2)" />
          ))}
        </Pie>
        <Tooltip
          formatter={(valor, nome) => [`${moneyShort(Number(valor))}`, String(nome)]}
          contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 12 }}
        />
      </RePieChart>
    </ResponsiveContainer>
  );
}

/* ----------------------------------------------------------------- página */

export default function AdministracaoCentralPage() {
  const [aba, setAba] = useState<Aba>("entidades");
  const [meta, setMeta] = useState<AdministracaoCentralMeta | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const [rascunho, setRascunho] = useState<Filtros>(FILTROS_INICIAIS);
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_INICIAIS);
  const [pagina, setPagina] = useState(0);
  const [resultado, setResultado] = useState<AdministracaoCentralEntidadesResultado | null>(null);
  const [carregando, setCarregando] = useState(true);

  const [aSelecionar, setASelecionar] = useState<string | null>(null);
  const [ficha, setFicha] = useState<AdministracaoCentralFicha | null>(null);
  const [fichaErro, setFichaErro] = useState<string | null>(null);
  const [fichaCarregando, setFichaCarregando] = useState(false);
  const painelFicha = useRef<HTMLDivElement | null>(null);

  const [analiticas, setAnaliticas] = useState<AdministracaoCentralAnaliticas | null>(null);
  const [analiticasCarregando, setAnaliticasCarregando] = useState(false);
  const [anoAnaliticas, setAnoAnaliticas] = useState<string>("");

  const [rascunhoContratos, setRascunhoContratos] = useState<FiltrosContratos>(FILTROS_CONTRATOS_INICIAIS);
  const [filtrosContratos, setFiltrosContratos] = useState<FiltrosContratos>(FILTROS_CONTRATOS_INICIAIS);
  const [contratos, setContratos] = useState<AdministracaoCentralContratosResultado | null>(null);
  const [contratosCarregando, setContratosCarregando] = useState(false);
  const [paginaContratos, setPaginaContratos] = useState(0);

  const [aReindexar, setAReindexar] = useState(false);
  const pesquisa = useDebounce(rascunho.q);

  const subsetores = meta?.subsetores ?? [];

  /* ------------------------------------------------------------ pedidos */

  const carregarMeta = useCallback(async () => {
    try {
      setMeta(await getAdministracaoCentralMeta());
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    }
  }, []);

  useEffect(() => {
    void carregarMeta();
  }, [carregarMeta]);

  useEffect(() => {
    setFiltros((atual) => ({ ...atual, q: pesquisa }));
    setPagina(0);
  }, [pesquisa]);

  useEffect(() => {
    let ativo = true;
    setCarregando(true);
    searchAdministracaoCentralEntidades({
      q: filtros.q,
      subsetor: filtros.subsetor,
      ligacao: filtros.ligacao || undefined,
      ordenar: filtros.ordenar,
      size: PAGINA,
      offset: pagina * PAGINA,
    })
      .then((dados) => {
        if (ativo) setResultado(dados);
      })
      .catch((falha: unknown) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : String(falha));
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });
    return () => {
      ativo = false;
    };
  }, [filtros, pagina]);

  const carregarAnaliticas = useCallback(
    async (ano?: string) => {
      setAnaliticasCarregando(true);
      try {
        const dados = await getAdministracaoCentralAnaliticas({
          subsetor: filtros.subsetor || undefined,
          ano: ano ? Number(ano) : undefined,
        });
        setAnaliticas(dados);
        if (dados.aviso) setAviso(dados.aviso);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : String(falha));
      } finally {
        setAnaliticasCarregando(false);
      }
    },
    [filtros.subsetor],
  );

  useEffect(() => {
    if (aba !== "analiticas") return;
    void carregarAnaliticas(anoAnaliticas);
  }, [aba, anoAnaliticas, carregarAnaliticas]);

  useEffect(() => {
    if (aba !== "contratos") return;
    let ativo = true;
    setContratosCarregando(true);
    searchAdministracaoCentralContratos({
      q: filtrosContratos.q,
      subsetor: filtrosContratos.subsetor,
      ano: filtrosContratos.ano ? Number(filtrosContratos.ano) : undefined,
      adjudicatario: filtrosContratos.adjudicatario,
      cpv: filtrosContratos.cpv,
      preco_min: numeroOuNulo(filtrosContratos.precoMin),
      preco_max: numeroOuNulo(filtrosContratos.precoMax),
      size: 20,
      offset: paginaContratos * 20,
    })
      .then((dados) => {
        if (ativo) setContratos(dados);
      })
      .catch((falha: unknown) => {
        if (ativo) setErro(falha instanceof Error ? falha.message : String(falha));
      })
      .finally(() => {
        if (ativo) setContratosCarregando(false);
      });
    return () => {
      ativo = false;
    };
  }, [aba, filtrosContratos, paginaContratos]);

  const abrirEntidade = useCallback(async (identificador: string) => {
    setASelecionar(identificador);
    setFicha(null);
    setFichaErro(null);
    setFichaCarregando(true);
    painelFicha.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      setFicha(await getAdministracaoCentralEntidade(identificador));
    } catch (falha) {
      setFichaErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setFichaCarregando(false);
    }
  }, []);

  const reindexar = useCallback(async () => {
    setAReindexar(true);
    setErro(null);
    try {
      const resultadoIndex = await reindexarAdministracaoCentral(true);
      setAviso(
        `Índice reconstruído: ${count(resultadoIndex.ligadas)} de ${count(resultadoIndex.total)} entidades ligadas a um NIF.`,
      );
      await carregarMeta();
      setFiltros({ ...filtros });
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setAReindexar(false);
    }
  }, [carregarMeta, filtros]);

  /* -------------------------------------------------------------- vistas */

  const linhasAno = useMemo(
    () =>
      (analiticas?.por_ano ?? [])
        .map((linha) => ({ nome: String(linha.key), valor: linha.valor, contratos: linha.count }))
        .sort((a, b) => a.nome.localeCompare(b.nome)),
    [analiticas],
  );

  const rankingEntidades = useMemo(
    () =>
      (analiticas?.top_entidades ?? []).map((item) => ({
        chave: item.id || item.nif,
        nome: item.nome,
        valor: item.valor,
        contratos: item.contratos,
      })),
    [analiticas],
  );

  const linhasDe = useCallback(
    (lista: AdministracaoCentralLinha[] | undefined) =>
      (lista ?? []).map((linha) => ({
        chave: String(linha.key),
        nome: linha.nome || String(linha.key) || "—",
        valor: linha.valor,
        contratos: linha.count,
      })),
    [],
  );

  const abrirDoNif = useCallback(
    (nif: string) => {
      const entidade = resultado?.items.find((item) => item.nif === nif);
      if (entidade) void abrirEntidade(entidade.id);
    },
    [abrirEntidade, resultado],
  );

  const totalPaginas = resultado ? Math.ceil(resultado.total / PAGINA) : 0;
  const totalContratos = contratos ? Math.ceil(contratos.total / 20) : 0;

  /* ------------------------------------------------------------- markup */

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-4 py-4 md:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-300 via-sky-500 to-indigo-700 text-white shadow-lg shadow-sky-500/25">
              <Landmark size={20} />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Administração Central</h1>
              <p className="text-sm text-muted-foreground">
                {meta?.fonte?.designacao ?? "Setor Institucional das Administrações Públicas"}
                {meta?.fonte?.edicao ? ` · ${meta.fonte.edicao}` : ""} — entidades, contratos e adjudicatárias
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {meta ? (
              <>
                <Badge variant="outline" className="gap-1">
                  <Building2 size={12} /> {count(meta.total)} entidades
                </Badge>
                <span title="Entidades com NIF ligado aos contratos do portal BASE">
                  <Badge variant="success" className="gap-1">
                    <Handshake size={12} /> {count(meta.ligadas)} com NIF
                  </Badge>
                </span>
              </>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => void downloadAdministracaoCentralCsv({ q: filtros.q, subsetor: filtros.subsetor })}
            >
              CSV
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<RefreshCw size={14} />}
              loading={aReindexar}
              onClick={() => void reindexar()}
              title="Relê o PDF do INE e refaz as ligações nome→NIF"
            >
              Reindexar
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
            <span className="min-w-0 break-words">{aviso}</span>
            <button type="button" className="ml-auto shrink-0 opacity-70" onClick={() => setAviso(null)}>
              <X size={14} />
            </button>
          </div>
        ) : null}
        {meta?.indice_em_falta ? (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm">
            <CircleAlert size={16} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">
              Ainda não há índice em disco. Carregue em «Reindexar» para o construir a partir do PDF do INE
              ({meta.fonte?.ficheiro}).
            </span>
          </div>
        ) : null}

        <Tabs value={aba} className="space-y-4">
          <TabsList>
            <TabsTrigger value="entidades" active={aba === "entidades"} onClick={() => setAba("entidades")}>
              Entidades
            </TabsTrigger>
            <TabsTrigger value="analiticas" active={aba === "analiticas"} onClick={() => setAba("analiticas")}>
              Analíticas
            </TabsTrigger>
            <TabsTrigger value="contratos" active={aba === "contratos"} onClick={() => setAba("contratos")}>
              Contratos
            </TabsTrigger>
          </TabsList>

          {/* ----------------------------------------------------- entidades */}
          <TabsContent value="entidades" active={aba === "entidades"} className="space-y-4">
            <Card>
              <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
                <div className="space-y-1">
                  <Label className="text-xs">Pesquisar entidade</Label>
                  <div className="relative">
                    <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      className="pl-8"
                      placeholder="Nome, nome usado nos contratos ou NIF"
                      value={rascunho.q}
                      onChange={(evento) => setRascunho({ ...rascunho, q: evento.target.value })}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Subsetor</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={rascunho.subsetor}
                    onChange={(evento) => {
                      setPagina(0);
                      setRascunho({ ...rascunho, subsetor: evento.target.value });
                      setFiltros({ ...filtros, subsetor: evento.target.value });
                    }}
                  >
                    <option value="">Todos os subsetores</option>
                    {subsetores.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id} — {item.nome}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Ligação aos contratos</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={rascunho.ligacao}
                    onChange={(evento) => {
                      setPagina(0);
                      setRascunho({ ...rascunho, ligacao: evento.target.value as Filtros["ligacao"] });
                      setFiltros({ ...filtros, ligacao: evento.target.value as Filtros["ligacao"] });
                    }}
                  >
                    <option value="">Todas</option>
                    <option value="com_nif">Com NIF ligado</option>
                    <option value="com_contratos">Com contratos</option>
                    <option value="sem_nif">Sem NIF (não contrata)</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Ordenar por</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={rascunho.ordenar}
                    onChange={(evento) => {
                      setPagina(0);
                      setRascunho({ ...rascunho, ordenar: evento.target.value as Filtros["ordenar"] });
                      setFiltros({ ...filtros, ordenar: evento.target.value as Filtros["ordenar"] });
                    }}
                  >
                    <option value="valor">Valor adjudicado</option>
                    <option value="contratos">Nº de contratos</option>
                    <option value="nome">Nome (A→Z)</option>
                    <option value="subsetor">Subsetor</option>
                  </select>
                </div>
              </div>
            </Card>

            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>
                {carregando ? "A pesquisar…" : `${count(resultado?.total)} entidades`}
                {filtros.subsetor ? ` · ${filtros.subsetor}` : ""}
              </span>
              <span className="flex items-center gap-2">
                <Filter size={14} />
                {meta?.gerado_em ? `índice de ${shortDate(meta.gerado_em)}` : "índice local"}
              </span>
            </div>

            <div className="grid gap-2">
              {(resultado?.items ?? []).map((entidade) => (
                <button
                  key={entidade.id}
                  type="button"
                  onClick={() => void abrirEntidade(entidade.id)}
                  className={`flex flex-col gap-2 rounded-xl border bg-card px-4 py-3 text-left transition hover:border-primary/60 hover:bg-accent/40 md:flex-row md:items-center md:justify-between ${
                    aSelecionar === entidade.id ? "border-primary/70" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">{entidade.nome}</span>
                      <Badge variant="secondary" className="shrink-0">
                        {entidade.subsetor}
                      </Badge>
                      <span
                        className="shrink-0"
                        title={entidade.nif ? LIGACAO_LABEL[entidade.ligacao] : "Sem NIF ligado nos contratos"}
                      >
                        <Badge variant={TOM_LIGACAO[entidade.ligacao]} className="shrink-0">
                          {entidade.nif ? entidade.nif : "sem NIF"}
                        </Badge>
                      </span>
                    </div>
                    {entidade.nome_contratos && entidade.nome_contratos !== entidade.nome ? (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        nos contratos: {entidade.nome_contratos}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-6 text-right">
                    <div>
                      <p className="text-xs text-muted-foreground">Contratos</p>
                      <p className="font-semibold tabular-nums">{count(entidade.contratos)}</p>
                    </div>
                    <div className="min-w-[110px]">
                      <p className="text-xs text-muted-foreground">Valor adjudicado</p>
                      <p className="font-semibold tabular-nums">{moneyShort(entidade.valor)}</p>
                    </div>
                  </div>
                </button>
              ))}
              {!carregando && (resultado?.items ?? []).length === 0 ? (
                <div className="rounded-xl border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
                  Nenhuma entidade corresponde aos filtros.
                </div>
              ) : null}
            </div>

            {totalPaginas > 1 ? (
              <div className="flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina === 0}
                  onClick={() => setPagina((atual) => Math.max(0, atual - 1))}
                >
                  Anterior
                </Button>
                <span className="text-sm text-muted-foreground">
                  Página {pagina + 1} de {count(totalPaginas)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina + 1 >= totalPaginas}
                  onClick={() => setPagina((atual) => atual + 1)}
                >
                  Seguinte
                </Button>
              </div>
            ) : null}

            {/* --------------------------------------------------- ficha */}
            <div ref={painelFicha}>
              {aSelecionar ? (
                <Card className="space-y-4">
                  {fichaCarregando ? (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 size={14} className="animate-spin" /> A carregar a ficha…
                    </p>
                  ) : null}
                  {fichaErro ? <p className="text-sm text-destructive">{fichaErro}</p> : null}
                  {ficha ? (
                    <>
                      <CardHeader>
                        <div className="min-w-0">
                          <CardTitle icon={<Landmark size={16} />} className="text-base">
                            {ficha.entidade.nome}
                          </CardTitle>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {ficha.entidade.subsetor} — {ficha.entidade.subsetor_nome}
                            {ficha.entidade.nif ? ` · NIF ${ficha.entidade.nif}` : ""}
                            {ficha.entidade.nome_contratos ? ` · nos contratos: ${ficha.entidade.nome_contratos}` : ""}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          {ficha.entidade.nif ? (
                            <Button
                              variant="outline"
                              size="sm"
                              icon={<ExternalLink size={14} />}
                              title="Abrir a ficha do NIF na app de entidades"
                              onClick={() =>
                                openWindow(`company-detail:${ficha.entidade.nif}`, undefined, {
                                  title: ficha.entidade.nome,
                                })
                              }
                            >
                              Ficha da entidade
                            </Button>
                          ) : null}
                          <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={() => setASelecionar(null)}>
                            Fechar
                          </Button>
                        </div>
                      </CardHeader>

                      {ficha.aviso ? (
                        <p className="rounded-xl border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{ficha.aviso}</p>
                      ) : null}

                      {ficha.contratos ? (
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <StatCard icon={FileText} label="Contratos" value={count(ficha.contratos.total)} />
                          <StatCard icon={Banknote} label="Valor adjudicado" value={moneyShort(ficha.contratos.valor)} />
                          <StatCard icon={TrendingUp} label="Contrato médio" value={moneyShort(ficha.contratos.valor_medio)} />
                          <StatCard icon={Sparkles} label="Maior contrato" value={moneyShort(ficha.contratos.valor_maximo)} />
                        </div>
                      ) : null}

                      {ficha.contratos && ficha.contratos.por_ano.length > 0 ? (
                        <Card padding="none">
                          <div className="mb-2">
                            <CardTitle icon={<TrendingUp size={16} />}>Valor adjudicado por ano</CardTitle>
                          </div>
                          <Barras
                            dados={ficha.contratos.por_ano
                              .map((linha) => ({ nome: String(linha.key), valor: linha.valor }))
                              .sort((a, b) => a.nome.localeCompare(b.nome))}
                            x="nome"
                            y="valor"
                            rotulo="Valor"
                          />
                        </Card>
                      ) : null}

                      <div className="grid gap-3 lg:grid-cols-2">
                        <Ranking
                          titulo="Adjudicatárias"
                          icon={<Handshake size={16} />}
                          linhas={linhasDe(ficha.top_adjudicatarios)}
                        />
                        <Ranking titulo="CPV" icon={<PackageSearch size={16} />} linhas={linhasDe(ficha.top_cpv)} escolherValor="contratos" />
                      </div>

                      <Card padding="none">
                        <div className="mb-2">
                          <CardTitle icon={<FileText size={16} />}>Contratos mais recentes</CardTitle>
                        </div>
                        <ContratosTabela contratos={ficha.ultimos ?? []} />
                      </Card>
                    </>
                  ) : null}
                </Card>
              ) : null}
            </div>
          </TabsContent>

          {/* -------------------------------------------------- analíticas */}
          <TabsContent value="analiticas" active={aba === "analiticas"} className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Ano</Label>
                <select
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={anoAnaliticas}
                  onChange={(evento) => setAnoAnaliticas(evento.target.value)}
                >
                  <option value="">Todos os anos</option>
                  {linhasAno
                    .map((linha) => linha.nome)
                    .reverse()
                    .map((ano) => (
                      <option key={ano} value={ano}>
                        {ano}
                      </option>
                    ))}
                </select>
              </div>
              <Button
                variant="outline"
                size="sm"
                icon={<RefreshCw size={14} />}
                loading={analiticasCarregando}
                onClick={() => void carregarAnaliticas(anoAnaliticas)}
              >
                Atualizar
              </Button>
              {analiticas?.atualizado_em ? (
                <span className="text-xs text-muted-foreground">atualizado em {shortDate(analiticas.atualizado_em)}</span>
              ) : null}
            </div>

            {analiticasCarregando && !analiticas ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={14} className="animate-spin" /> A agregar os contratos do setor…
              </p>
            ) : null}

            {analiticas ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <StatCard
                    icon={FileText}
                    label="Contratos adjudicados"
                    value={count(analiticas.total_contratos)}
                    sub={filtros.subsetor ? `subsetor ${filtros.subsetor}` : "todos os subsetores indexados"}
                  />
                  <StatCard icon={Banknote} label="Valor adjudicado" value={moneyShort(analiticas.total_valor)} />
                  <StatCard
                    icon={Building2}
                    label="Entidades compradoras"
                    value={count(analiticas.entidades_com_contratos)}
                    sub="entidades do setor com contratos no período"
                  />
                  <StatCard
                    icon={ShoppingCart}
                    label="Adjudicatárias distintas"
                    value={count(analiticas.adjudicatarias_distintas)}
                  />
                </div>

                <Card>
                  <div className="mb-2">
                    <CardTitle icon={<TrendingUp size={16} />}>Valor adjudicado por ano</CardTitle>
                  </div>
                  <Barras dados={linhasAno} x="nome" y="valor" rotulo="Valor" />
                </Card>

                <Ranking
                  titulo="Entidades que mais adjudicam"
                  icon={<Landmark size={16} />}
                  linhas={rankingEntidades}
                  aoAbrir={(chave) => {
                    const porId = rankingEntidades.find((linha) => linha.chave === chave);
                    if (porId) void abrirEntidade(chave);
                  }}
                />

                <div className="grid gap-3 lg:grid-cols-2">
                  <Ranking
                    titulo="Adjudicatárias do setor"
                    icon={<Handshake size={16} />}
                    linhas={linhasDe(analiticas.top_adjudicatarios)}
                    aoAbrir={(nif) => abrirDoNif(nif)}
                  />
                  <Ranking
                    titulo="CPV mais contratados"
                    icon={<PackageSearch size={16} />}
                    linhas={linhasDe(analiticas.top_cpv)}
                    escolherValor="contratos"
                  />
                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle icon={<Filter size={16} />}>Tipo de procedimento</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Tarteira
                        dados={analiticas.tipos_procedimento.map((linha) => ({
                          nome: linha.nome || String(linha.key),
                          valor: linha.count,
                        }))}
                      />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle icon={<FileText size={16} />}>Tipo de contrato</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Tarteira
                        dados={analiticas.tipos_contrato.map((linha) => ({
                          nome: linha.nome || String(linha.key),
                          valor: linha.count,
                        }))}
                      />
                    </CardContent>
                  </Card>
                </div>
              </>
            ) : null}
          </TabsContent>

          {/* --------------------------------------------------- contratos */}
          <TabsContent value="contratos" active={aba === "contratos"} className="space-y-4">
            <Card>
              <form
                className="grid gap-3 md:grid-cols-3"
                onSubmit={(evento) => {
                  evento.preventDefault();
                  setPaginaContratos(0);
                  setFiltrosContratos({ ...rascunhoContratos });
                }}
              >
                <div className="space-y-1 md:col-span-3">
                  <Label className="text-xs">Objeto do contrato</Label>
                  <Input
                    placeholder="Texto livre (objeto, descrição, entidades)"
                    value={rascunhoContratos.q}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, q: evento.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Subsetor</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={rascunhoContratos.subsetor}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, subsetor: evento.target.value })}
                  >
                    <option value="">Todos os subsetores</option>
                    {subsetores.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Ano</Label>
                  <Input
                    inputMode="numeric"
                    placeholder="2025"
                    value={rascunhoContratos.ano}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, ano: evento.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Adjudicatária</Label>
                  <Input
                    placeholder="Nome da empresa"
                    value={rascunhoContratos.adjudicatario}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, adjudicatario: evento.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">CPV</Label>
                  <Input
                    placeholder="Ex.: 45200000"
                    value={rascunhoContratos.cpv}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, cpv: evento.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Valor mínimo (€)</Label>
                  <Input
                    inputMode="decimal"
                    placeholder="0"
                    value={rascunhoContratos.precoMin}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, precoMin: evento.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Valor máximo (€)</Label>
                  <Input
                    inputMode="decimal"
                    placeholder="1000000"
                    value={rascunhoContratos.precoMax}
                    onChange={(evento) => setRascunhoContratos({ ...rascunhoContratos, precoMax: evento.target.value })}
                  />
                </div>
                <div className="flex items-end gap-2 md:col-span-3">
                  <Button type="submit" icon={<Search size={14} />} loading={contratosCarregando}>
                    Pesquisar
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setRascunhoContratos(FILTROS_CONTRATOS_INICIAIS);
                      setFiltrosContratos(FILTROS_CONTRATOS_INICIAIS);
                      setPaginaContratos(0);
                    }}
                  >
                    Limpar
                  </Button>
                  {contratos ? (
                    <span className="ml-auto text-sm text-muted-foreground">{count(contratos.total)} contratos</span>
                  ) : null}
                </div>
              </form>
            </Card>

            {contratos?.aviso ? (
              <p className="rounded-xl border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">{contratos.aviso}</p>
            ) : null}

            <Card padding="none">
              <ContratosTabela contratos={contratos?.items ?? []} />
            </Card>

            {totalContratos > 1 ? (
              <div className="flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={paginaContratos === 0}
                  onClick={() => setPaginaContratos((atual) => Math.max(0, atual - 1))}
                >
                  Anterior
                </Button>
                <span className="text-sm text-muted-foreground">
                  Página {paginaContratos + 1} de {count(totalContratos)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={paginaContratos + 1 >= totalContratos}
                  onClick={() => setPaginaContratos((atual) => atual + 1)}
                >
                  Seguinte
                </Button>
              </div>
            ) : null}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

/** Lista de contratos do portal BASE (objeto, partes, valor e datas). */
function ContratosTabela({ contratos }: { contratos: AdministracaoCentralContrato[] }) {
  if (contratos.length === 0) {
    return <p className="px-4 py-6 text-center text-sm text-muted-foreground">Sem contratos.</p>;
  }
  return (
    <div className="divide-y">
      {contratos.map((contrato, indice) => {
        const adjudicantes = partes(contrato, "adjudicantes");
        const adjudicatarios = partes(contrato, "adjudicatarios");
        const cpv = contrato.cpv?.[0];
        return (
          <div key={contrato.doc_id || contrato.idcontrato || `${indice}`} className="px-4 py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium" title={contrato.objectoContrato || ""}>
                  {contrato.objectoContrato || contrato.descContrato || "Contrato sem objeto publicado"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {adjudicantes || "—"} <span className="mx-1">→</span> {adjudicatarios || "—"}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {contrato.Ano ? <Badge variant="outline">{contrato.Ano}</Badge> : null}
                  {contrato.tipoprocedimento ? <span>{contrato.tipoprocedimento}</span> : null}
                  {cpv?.code ? (
                    <span>
                      CPV {cpv.code}
                      {cpv.description ? ` — ${cpv.description.slice(0, 60)}` : ""}
                    </span>
                  ) : null}
                  {contrato.localExecucao?.length ? <span>{contrato.localExecucao[0]}</span> : null}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-4 text-right">
                <div>
                  <p className="text-xs text-muted-foreground">
                    {shortDate(contrato.dataCelebracaoContrato || contrato.dataPublicacao)}
                  </p>
                  <p className="font-semibold tabular-nums">
                    {money(contrato.precoContratual ?? contrato.PrecoTotalEfetivo ?? null)}
                  </p>
                </div>
                {contrato.doc_id ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<ExternalLink size={14} />}
                    title="Abrir a ficha do contrato"
                    onClick={() =>
                      openWindow(`contract-detail:${contrato.idcontrato || contrato.doc_id}`, undefined, {
                        title: contrato.objectoContrato || "Ficha do contrato",
                      })
                    }
                  >
                    Ficha
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
