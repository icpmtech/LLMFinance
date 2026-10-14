/**
 * Página do módulo **Remunerações da Administração Pública**.
 *
 * O quadro que a DGAEP publica todos os anos — *Sistema Remuneratório da
 * Administração Pública* — lido para um modelo por ano:
 *
 * 1. a **Tabela Remuneratória Única (TRU)** — nível → remuneração base mensal,
 *    do nível 5 (Base Remuneratória da Administração Pública, BRAP) ao 115;
 * 2. as **carreiras e categorias** — cada uma com as suas posições
 *    remuneratórias e o nível da TRU que lhes corresponde;
 * 3. os **cargos dirigentes** — âmbito, serviço, cargo, índice, nível e valor;
 * 4. as **notas** e a **base legal** de cada carreira.
 *
 * Com isso responde-se ao que interessa a quem trabalha em funções públicas e a
 * quem escreve sobre elas: «quanto vale esta posição, neste ano?». O simulador
 * usa só o que o quadro publica — suplementos e subsídio de refeição não estão
 * lá e não são estimados.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Building2,
  Calculator,
  ExternalLink,
  Globe2,
  Landmark,
  Loader2,
  RefreshCw,
  Search,
  Table2,
  TrendingUp,
  X,
} from "lucide-react";

import { cmsAppUrl, cmsRemuneracaoUrl, createCmsRemuneracao, publishCmsItem } from "../cmsApi";
import {
  euroExato,
  numero,
} from "../municipiosApi";
import {
  getRemuneracoesApBaseLegal,
  getRemuneracoesApCarreiras,
  getRemuneracoesApDirigentes,
  getRemuneracoesApMeta,
  getRemuneracoesApNiveis,
  getRemuneracoesApNotas,
  getRemuneracoesApSeccoes,
  recolherRemuneracoesAp,
  simularRemuneracaoAp,
  type BaseLegalAp,
  type CarreiraAp,
  type DirigenteAp,
  type NivelTru,
  type NotasAp,
  type ParametrosAp,
  type RemuneracoesApMeta,
  type RemuneracoesApSimulacao,
} from "../remuneracoesApApi";

/* ---------------------------------------------------------------- primitivas */

function Cartao({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`glass-card min-w-0 rounded-2xl p-4 ${className}`}>{children}</div>;
}

function Kpi({ label, valor, nota }: { label: string; valor: string; nota?: string }) {
  return (
    <Cartao className="p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{valor}</p>
      {nota ? <p className="mt-0.5 text-[10px] text-muted-foreground">{nota}</p> : null}
    </Cartao>
  );
}

/** Abas da página: cada uma é um quadro do documento. */
type Aba = "tru" | "carreiras" | "dirigentes" | "simulador" | "notas";

const ABAS: { id: Aba; label: string; icon: React.ReactNode }[] = [
  { id: "tru", label: "Tabela Remuneratória Única", icon: <Table2 size={13} /> },
  { id: "carreiras", label: "Carreiras e posições", icon: <Landmark size={13} /> },
  { id: "dirigentes", label: "Cargos dirigentes", icon: <Building2 size={13} /> },
  { id: "simulador", label: "Simulador", icon: <Calculator size={13} /> },
  { id: "notas", label: "Notas e base legal", icon: <BookOpen size={13} /> },
];

const PAGAMENTOS = 14;

/* -------------------------------------------------------------------- página */

export default function RemuneracoesApPage() {
  const [meta, setMeta] = useState<RemuneracoesApMeta | null>(null);
  const [ano, setAno] = useState<string>("");
  const [aba, setAba] = useState<Aba>("tru");
  const [niveis, setNiveis] = useState<NivelTru[]>([]);
  const [parametros, setParametros] = useState<ParametrosAp | null>(null);
  const [truNotas, setTruNotas] = useState<string[]>([]);
  const [carreiras, setCarreiras] = useState<CarreiraAp[]>([]);
  const [totalCarreiras, setTotalCarreiras] = useState(0);
  const [seccoes, setSeccoes] = useState<string[]>([]);
  const [busca, setBusca] = useState("");
  const [termo, setTermo] = useState("");
  const [seccao, setSeccao] = useState("");
  const [dirigentes, setDirigentes] = useState<DirigenteAp[]>([]);
  const [ambitos, setAmbitos] = useState<string[]>([]);
  const [ambito, setAmbito] = useState("");
  const [notas, setNotas] = useState<NotasAp[]>([]);
  const [baseLegal, setBaseLegal] = useState<BaseLegalAp[]>([]);
  const [aCarregar, setACarregar] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Publicação no CMS: a página pública do quadro deste ano.
  const [aPublicar, setAPublicar] = useState(false);
  const [erroPublicar, setErroPublicar] = useState<string | null>(null);
  const [paginaNoCms, setPaginaNoCms] = useState<{ id: string; title: string; slug: string; ano: number } | null>(null);

  // Simulador: nível, carreira/posição ou cargo dirigente escolhido.
  const [nivelSimulado, setNivelSimulado] = useState<string>("");
  const [carreiraSimulada, setCarreiraSimulada] = useState("");
  const [posicaoSimulada, setPosicaoSimulada] = useState("");
  const [cargoSimulado, setCargoSimulado] = useState("");
  const [simulacao, setSimulacao] = useState<RemuneracoesApSimulacao | null>(null);
  const [aSimular, setASimular] = useState(false);

  const carregarNucleo = useCallback(async (anoEscolhido?: string) => {
    setACarregar(true);
    setErro(null);
    try {
      const [nucleo, metaAtual] = await Promise.all([
        getRemuneracoesApNiveis(anoEscolhido ? Number(anoEscolhido) : undefined),
        getRemuneracoesApMeta(),
      ]);
      setNiveis(nucleo.itens);
      setParametros(nucleo.parametros);
      setTruNotas(nucleo.notas ?? []);
      setMeta(metaAtual);
      setAno(String(nucleo.ano));
      if (!nivelSimulado) {
        // Começa na BRAP: é a referência de todos os vencimentos da AP.
        setNivelSimulado(String(nucleo.parametros?.brap ? 5 : nucleo.itens[0]?.nivel ?? ""));
      }
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setACarregar(false);
    }
  }, [nivelSimulado]);

  useEffect(() => {
    void carregarNucleo();
    // Só no arranque: o ano escolhido é aplicado em `carregarNucleo(ano)`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const carregarCarreiras = useCallback(async () => {
    try {
      const [resposta, listaSeccoes] = await Promise.all([
        getRemuneracoesApCarreiras({
          ano: ano ? Number(ano) : undefined,
          q: termo || undefined,
          seccao: seccao || undefined,
          size: 60,
        }),
        getRemuneracoesApSeccoes(ano ? Number(ano) : undefined),
      ]);
      setCarreiras(resposta.itens);
      setTotalCarreiras(resposta.total);
      setSeccoes(listaSeccoes.itens);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    }
  }, [ano, termo, seccao]);

  useEffect(() => {
    if (aba !== "carreiras") return;
    void carregarCarreiras();
  }, [aba, carregarCarreiras]);

  useEffect(() => {
    if (aba !== "dirigentes" && aba !== "simulador") return;
    let ativo = true;
    // O filtro de âmbito é da tabela; o simulador precisa da lista completa.
    const filtro = aba === "dirigentes" ? ambito || undefined : undefined;
    getRemuneracoesApDirigentes({ ano: ano ? Number(ano) : undefined, ambito: filtro })
      .then((resposta) => {
        if (!ativo) return;
        setDirigentes(resposta.itens);
        if (resposta.ambitos.length) setAmbitos(resposta.ambitos);
      })
      .catch((excecao) => {
        if (ativo) setErro(excecao instanceof Error ? excecao.message : String(excecao));
      });
    return () => {
      ativo = false;
    };
  }, [aba, ano, ambito]);

  useEffect(() => {
    if (aba !== "notas") return;
    let ativo = true;
    Promise.all([
      getRemuneracoesApNotas({ ano: ano ? Number(ano) : undefined }),
      getRemuneracoesApBaseLegal({ ano: ano ? Number(ano) : undefined }),
    ])
      .then(([listaNotas, legal]) => {
        if (!ativo) return;
        setNotas(listaNotas.itens);
        setBaseLegal(legal.tabelas);
      })
      .catch((excecao) => {
        if (ativo) setErro(excecao instanceof Error ? excecao.message : String(excecao));
      });
    return () => {
      ativo = false;
    };
  }, [aba, ano]);

  const valorDoNivel = useMemo(() => {
    const mapa = new Map<number, number | null>();
    for (const item of niveis) mapa.set(item.nivel, item.valor);
    return mapa;
  }, [niveis]);

  /** Chave estável de um cargo dirigente (o mesmo cargo existe em vários âmbitos). */
  const chaveDoCargo = (item: DirigenteAp) =>
    [item.ambito ?? "", item.grupo ?? "", item.cargo, item.indice ?? ""].join(" · ");

  const cargoEscolhido = useMemo(
    () => dirigentes.find((item) => chaveDoCargo(item) === cargoSimulado) ?? null,
    [dirigentes, cargoSimulado],
  );

  const simular = useCallback(async () => {
    setASimular(true);
    setErro(null);
    try {
      const resultado = await simularRemuneracaoAp({
        ano: ano ? Number(ano) : undefined,
        nivel: !carreiraSimulada && !cargoEscolhido && nivelSimulado ? Number(nivelSimulado) : undefined,
        carreira: carreiraSimulada || undefined,
        posicao: posicaoSimulada || undefined,
        cargo: cargoEscolhido?.cargo || undefined,
        ambito: cargoEscolhido?.ambito || undefined,
        grupo: cargoEscolhido?.grupo || undefined,
        indice: cargoEscolhido?.indice ?? undefined,
        pagamentos: PAGAMENTOS,
      });
      setSimulacao(resultado);
    } catch (excecao) {
      setSimulacao(null);
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setASimular(false);
    }
  }, [ano, nivelSimulado, carreiraSimulada, posicaoSimulada, cargoEscolhido]);

  useEffect(() => {
    if (aba !== "simulador") return;
    void simular();
  }, [aba, simular]);

  const recolher = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      await recolherRemuneracoesAp(true);
      await carregarNucleo(ano);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setARecolher(false);
    }
  }, [ano, carregarNucleo]);

  // A página pública nasce já com a fotografia do ano que está no ecrã (tabelas,
  // série, carreiras, dirigentes, notas e base legal) e é publicada de imediato;
  // o SEO, a marca e as imagens editam-se depois no CMS.
  const publicarNoCms = useCallback(async () => {
    const anoEscolhido = Number(ano);
    if (!anoEscolhido) return;
    setAPublicar(true);
    setErroPublicar(null);
    try {
      const criada = await createCmsRemuneracao({ ano: anoEscolhido });
      const publicada = await publishCmsItem("remuneracoes", criada.item.id);
      const item = publicada.item as unknown as { id: string; title: string; slug: string };
      setPaginaNoCms({ id: item.id, title: item.title, slug: item.slug, ano: anoEscolhido });
    } catch (excecao) {
      setErroPublicar(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setAPublicar(false);
    }
  }, [ano]);

  const anos = meta?.anos ?? [];
  const contagens = meta?.stats?.contagens ?? {};

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="space-y-4 p-4 lg:p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Remunerações da Administração Pública</h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              O quadro consolidado da{" "}
              {meta?.fonte_url ? (
                <a className="underline hover:text-foreground" href={meta.fonte_url} target="_blank" rel="noreferrer">
                  {meta?.fonte ?? "DGAEP"}
                </a>
              ) : (
                meta?.fonte ?? "DGAEP"
              )}{" "}
              — Tabela Remuneratória Única, carreiras e categorias, cargos dirigentes e base legal —, lido dos PDF
              publicados por ano{meta?.parametros?.versao ? ` (documento de ${meta.parametros.versao})` : ""}. A
              remuneração é a <strong className="text-foreground">base mensal</strong> publicada; suplementos e subsídio
              de refeição não fazem parte deste quadro.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {anos.length ? (
              <select
                value={ano}
                onChange={(evento) => void carregarNucleo(evento.target.value)}
                className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
                title="Ano do quadro da DGAEP"
              >
                {anos.map((valor) => (
                  <option key={valor} value={valor}>
                    {valor}
                  </option>
                ))}
              </select>
            ) : null}
            <button
              type="button"
              onClick={() => void publicarNoCms()}
              disabled={aPublicar || !ano}
              className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
              title="Criar no CMS a página pública do quadro deste ano (tabelas, série, carreiras, dirigentes, simulador, notas e base legal) e publicá-la."
            >
              {aPublicar ? <Loader2 size={13} className="animate-spin" /> : <Globe2 size={13} />}
              {aPublicar ? "a publicar…" : "Publicar no CMS"}
            </button>
            <button
              type="button"
              onClick={() => void recolher()}
              disabled={aRecolher}
              className="flex min-h-[36px] items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
              title="Descarregar outra vez os PDF da DGAEP e reler o modelo."
            >
              {aRecolher ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Recolher da DGAEP
            </button>
          </div>
        </header>

        {erroPublicar ? (
          <Cartao className="border-rose-400/20">
            <p className="text-sm text-rose-300">Não foi possível publicar no CMS: {erroPublicar}</p>
          </Cartao>
        ) : null}

        {paginaNoCms ? (
          <Cartao className="border-teal-400/20">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                Página <strong className="text-foreground">{paginaNoCms.title}</strong> publicada no CMS com o quadro de{" "}
                {paginaNoCms.ano}. O SEO, as imagens, a marca e o que a página mostra editam-se lá.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <a
                  href={cmsRemuneracaoUrl(paginaNoCms.slug)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  <ExternalLink size={13} /> Página no site
                </a>
                <a
                  href={cmsAppUrl("remuneracoes", paginaNoCms.id)}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  <Globe2 size={13} /> Editar no CMS
                </a>
              </div>
            </div>
          </Cartao>
        ) : null}

        {erro ? (
          <Cartao className="border-rose-400/20">
            <p className="text-sm text-rose-300">{erro}</p>
          </Cartao>
        ) : null}

        {!anos.length && !aCarregar ? (
          <Cartao>
            <p className="text-sm font-semibold">Ainda não há nenhum ano recolhido</p>
            <p className="mt-2 text-xs text-muted-foreground">
              A recolha descarrega os PDF do Sistema Remuneratório da Administração Pública (2020 a 2026) e lê deles a
              TRU, as carreiras, os dirigentes e a base legal. Carregue em «Recolher da DGAEP».
            </p>
          </Cartao>
        ) : null}

        <section className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
          <Kpi
            label="BRAP"
            valor={euroExato(parametros?.brap)}
            nota={parametros?.brap ? "nível 5 da TRU" : "nível 5 sem valor publicado"}
          />
          <Kpi
            label="Níveis da TRU"
            valor={numero(contagens.niveis)}
            nota={
              parametros?.nivel_maximo
                ? `do nível ${parametros.nivel_minimo ?? 5} ao ${parametros.nivel_maximo}`
                : undefined
            }
          />
          <Kpi
            label="Posições remuneratórias"
            valor={numero(contagens.posicoes)}
            nota={contagens.carreiras ? `${numero(contagens.carreiras)} carreiras/categorias` : undefined}
          />
          <Kpi
            label="Cargos dirigentes"
            valor={numero(contagens.dirigentes)}
            nota="índice, nível e remuneração"
          />
        </section>

        <nav className="flex flex-wrap items-center gap-1.5">
          {ABAS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setAba(item.id)}
              className={`flex min-h-[32px] items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition ${
                aba === item.id
                  ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                  : "border-white/10 text-muted-foreground hover:text-foreground"
              }`}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        {aba === "tru" ? (
          <div className="grid gap-4 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Cartao className="p-0">
              <div className="max-h-[560px] overflow-auto">
                <table className="w-full min-w-[420px] text-[11px]">
                  <thead className="sticky top-0 bg-background/95">
                    <tr className="text-left text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Nível</th>
                      <th className="px-3 py-2 text-right font-medium">Remuneração base mensal</th>
                      <th className="px-3 py-2 font-medium">Nota</th>
                    </tr>
                  </thead>
                  <tbody>
                    {niveis.map((item) => (
                      <tr key={item.nivel} className="border-t border-white/5">
                        <td className="px-3 py-1.5 tabular-nums">{item.nivel}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">
                          {item.valor != null ? euroExato(item.valor) : "—"}
                        </td>
                        <td className="px-3 py-1.5 text-muted-foreground">{item.nota ?? ""}</td>
                      </tr>
                    ))}
                    {aCarregar ? (
                      <tr>
                        <td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                          <Loader2 size={13} className="mr-1.5 inline animate-spin" /> a carregar…
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </Cartao>
            <div className="min-w-0 space-y-3">
              <Cartao>
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <TrendingUp size={14} /> Como se lê a tabela
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  O <strong className="text-foreground">nível 5</strong> é a Base Remuneratória da Administração Pública
                  (BRAP): é o valor de referência a que estão ligados o salário mínimo da função pública e várias
                  prestações. Os níveis 1 a 4 aparecem com a nota <span className="text-foreground">{truNotas.length ? "«a)»" : "—"}</span>
                  : o quadro remete-os para a BRAP em vez de lhes dar valor próprio.
                </p>
                {truNotas.length ? (
                  <ul className="mt-3 space-y-1.5 text-[11px] text-muted-foreground">
                    {truNotas.map((nota) => (
                      <li key={nota}>· {nota}</li>
                    ))}
                  </ul>
                ) : null}
              </Cartao>
              <Cartao>
                <p className="text-sm font-semibold">Evolução do nível 5</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Os anos recolhidos ficam todos no modelo: escolha outro ano em cima para comparar os valores.
                </p>
                <p className="mt-3 text-2xl font-semibold tabular-nums">{euroExato(parametros?.brap)}</p>
                <p className="text-[11px] text-muted-foreground">BRAP de {ano || "—"}</p>
              </Cartao>
            </div>
          </div>
        ) : null}

        {aba === "carreiras" ? (
          <div className="space-y-3">
            <Cartao>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-[220px] flex-1">
                  <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
                  <input
                    value={busca}
                    onChange={(evento) => setBusca(evento.target.value)}
                    onKeyDown={(evento) => evento.key === "Enter" && setTermo(busca.trim())}
                    placeholder="Procurar carreira ou categoria (ex.: técnico superior)"
                    className="w-full rounded-lg border border-input bg-background py-1.5 pl-8 pr-8 text-xs"
                  />
                  {busca ? (
                    <button
                      type="button"
                      onClick={() => {
                        setBusca("");
                        setTermo("");
                      }}
                      aria-label="Limpar"
                      className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
                    >
                      <X size={13} />
                    </button>
                  ) : null}
                </div>
                <select
                  value={seccao}
                  onChange={(evento) => setSeccao(evento.target.value)}
                  className="max-w-[320px] rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
                >
                  <option value="">Todas as secções</option>
                  {seccoes.map((nome) => (
                    <option key={nome} value={nome}>
                      {nome}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setTermo(busca.trim())}
                  className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
                >
                  Procurar
                </button>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                <strong className="text-foreground">{numero(totalCarreiras)}</strong> carreiras/categorias no filtro. Cada
                linha traz as posições remuneratórias e o nível da TRU de cada uma.
              </p>
            </Cartao>

            {carreiras.map((item) => (
              <Cartao key={`${item.seccao}-${item.carreira}-${item.categoria}-${item.variante ?? ""}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-sm font-semibold">
                    {item.carreira}
                    {item.categoria && item.categoria !== item.carreira ? (
                      <span className="text-muted-foreground"> · {item.categoria}</span>
                    ) : null}
                  </h2>
                  <p className="text-[10px] text-muted-foreground">
                    {item.seccao}
                    {item.variante ? ` · ${item.variante}` : ""}
                  </p>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {item.posicoes.map((posicao) => (
                    <span
                      key={`${posicao.posicao}-${posicao.nivel}`}
                      className="rounded-lg border border-white/10 px-2 py-1 text-[11px] tabular-nums"
                      title={`posição ${posicao.posicao} · nível ${posicao.niveis_texto ?? posicao.nivel ?? "—"}`}
                    >
                      <span className="text-muted-foreground">{posicao.posicao}</span>{" "}
                      <span className="font-semibold">{euroExato(posicao.remuneracao)}</span>
                      {posicao.niveis_texto ? (
                        <span className="text-muted-foreground"> · n.º {posicao.niveis_texto}</span>
                      ) : null}
                    </span>
                  ))}
                </div>
                {item.minimo && item.maximo ? (
                  <p className="mt-2 text-[10px] text-muted-foreground">
                    de {euroExato(item.minimo)} a {euroExato(item.maximo)}
                  </p>
                ) : null}
              </Cartao>
            ))}
          </div>
        ) : null}

        {aba === "dirigentes" ? (
          <div className="space-y-3">
            <Cartao>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={ambito}
                  onChange={(evento) => setAmbito(evento.target.value)}
                  className="max-w-[420px] rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
                >
                  <option value="">Todos os âmbitos</option>
                  {ambitos.map((nome) => (
                    <option key={nome} value={nome}>
                      {nome}
                    </option>
                  ))}
                </select>
                <span className="text-[11px] text-muted-foreground">{numero(dirigentes.length)} cargos</span>
              </div>
            </Cartao>
            <Cartao className="p-0">
              <div className="max-h-[560px] overflow-auto">
                <table className="w-full min-w-[720px] text-[11px]">
                  <thead className="sticky top-0 bg-background/95">
                    <tr className="text-left text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Âmbito</th>
                      <th className="px-3 py-2 font-medium">Serviço</th>
                      <th className="px-3 py-2 font-medium">Cargo</th>
                      <th className="px-3 py-2 text-right font-medium">Índice</th>
                      <th className="px-3 py-2 text-right font-medium">Nível TRU</th>
                      <th className="px-3 py-2 text-right font-medium">Remuneração base</th>
                      <th className="px-3 py-2 text-right font-medium">Simulador</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dirigentes.map((item, indice) => (
                      <tr key={`${item.ambito}-${item.cargo}-${item.indice}-${indice}`} className="border-t border-white/5">
                        <td className="px-3 py-1.5 text-muted-foreground">{item.ambito ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{item.grupo ?? "—"}</td>
                        <td className="px-3 py-1.5 font-medium">{item.cargo}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{item.indice ?? "—"}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{item.niveis_texto ?? "—"}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{euroExato(item.remuneracao)}</td>
                        <td className="px-3 py-1.5 text-right">
                          {item.remuneracao != null ? (
                            <button
                              type="button"
                              onClick={() => {
                                setNivelSimulado("");
                                setCarreiraSimulada("");
                                setPosicaoSimulada("");
                                setCargoSimulado(chaveDoCargo(item));
                                setAba("simulador");
                              }}
                              className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-2 py-1 text-[11px] text-teal-200 transition hover:bg-teal-400/20"
                              title="Ver esta remuneração no simulador, com o valor do ano."
                            >
                              Simular
                            </button>
                          ) : (
                            <span className="text-[11px] text-muted-foreground">sem valor</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Cartao>
          </div>
        ) : null}

        {aba === "simulador" ? (
          <div className="grid gap-4 @3xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
            <Cartao>
              <p className="text-sm font-semibold">Quanto vale uma posição</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Escolha um nível da TRU, uma carreira com a posição remuneratória ou um cargo dirigente. A conta é a
                remuneração base mensal publicada, mais o valor do ano ({PAGAMENTOS} pagamentos: 12 mensalidades,
                subsídio de férias e subsídio de Natal).
              </p>
              <div className="mt-3 space-y-2">
                <label className="block text-[11px] text-muted-foreground">
                  Nível da TRU
                  <select
                    value={nivelSimulado}
                    onChange={(evento) => {
                      setNivelSimulado(evento.target.value);
                      setCarreiraSimulada("");
                      setPosicaoSimulada("");
                      setCargoSimulado("");
                    }}
                    className="mt-1 w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                  >
                    <option value="">— escolher —</option>
                    {niveis
                      .filter((item) => item.valor != null)
                      .map((item) => (
                        <option key={item.nivel} value={item.nivel}>
                          {item.nivel} — {euroExato(item.valor)}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="block text-[11px] text-muted-foreground">
                  Carreira/categoria
                  <select
                    value={carreiraSimulada}
                    onChange={(evento) => {
                      setCarreiraSimulada(evento.target.value);
                      setPosicaoSimulada("");
                      setNivelSimulado("");
                      setCargoSimulado("");
                    }}
                    className="mt-1 w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                  >
                    <option value="">— escolher —</option>
                    {carreiras.map((item) => (
                      <option
                        key={`${item.carreira}-${item.categoria}-${item.seccao}`}
                        value={item.carreira}
                      >
                        {item.carreira}
                        {item.categoria !== item.carreira ? ` · ${item.categoria}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
                {carreiraSimulada ? (
                  <label className="block text-[11px] text-muted-foreground">
                    Posição remuneratória
                    <select
                      value={posicaoSimulada}
                      onChange={(evento) => setPosicaoSimulada(evento.target.value)}
                      className="mt-1 w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                    >
                      <option value="">última posição da carreira</option>
                      {(carreiras.find((item) => item.carreira === carreiraSimulada)?.posicoes ?? []).map((posicao) => (
                        <option key={`${posicao.posicao}-${posicao.nivel}`} value={posicao.posicao}>
                          {posicao.posicao} — {euroExato(posicao.remuneracao)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label className="block text-[11px] text-muted-foreground">
                  Cargo dirigente
                  <select
                    value={cargoSimulado}
                    onChange={(evento) => {
                      setCargoSimulado(evento.target.value);
                      setNivelSimulado("");
                      setCarreiraSimulada("");
                      setPosicaoSimulada("");
                    }}
                    className="mt-1 w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                  >
                    <option value="">— escolher —</option>
                    {dirigentes.map((item) => (
                      <option key={`${item.ambito}-${item.grupo}-${item.cargo}-${item.indice}`} value={chaveDoCargo(item)}>
                        {item.cargo} · {item.grupo ?? "—"} ({item.ambito ?? "—"}) — {euroExato(item.remuneracao)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void simular()}
                  disabled={aSimular}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/10 px-2.5 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-40"
                >
                  {aSimular ? <Loader2 size={13} className="animate-spin" /> : <Calculator size={13} />}
                  Simular
                </button>
              </div>
            </Cartao>

            <Cartao>
              {simulacao ? (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Remuneração base mensal</p>
                      <p className="mt-1 text-2xl font-semibold tabular-nums">
                        {euroExato(simulacao.remuneracao_base_mensal)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                        Ano ({simulacao.pagamentos_por_ano} pagamentos)
                      </p>
                      <p className="mt-1 text-2xl font-semibold tabular-nums">
                        {euroExato(simulacao.remuneracao_base_anual)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-3 text-[11px] text-muted-foreground">
                    {simulacao.origem.via}
                    {simulacao.origem.nivel ? ` · nível ${simulacao.origem.nivel}` : ""}
                    {simulacao.origem.posicao ? ` · posição ${simulacao.origem.posicao}` : ""}
                    {simulacao.origem.carreira ? ` · ${simulacao.origem.carreira}` : ""}
                    {simulacao.origem.cargo ? ` · ${simulacao.origem.cargo}` : ""}
                    {simulacao.origem.indice ? ` · índice ${simulacao.origem.indice}` : ""}
                    {simulacao.origem.seccao ? ` · ${simulacao.origem.seccao}` : ""}
                  </p>
                  {simulacao.origem.niveis ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Níveis da TRU do cargo: {simulacao.origem.niveis}
                    </p>
                  ) : null}
                  {simulacao.origem.nota ? (
                    <p className="mt-1 text-[11px] text-amber-200">Nota do quadro: {simulacao.origem.nota}</p>
                  ) : null}
                  <ul className="mt-3 space-y-1 text-[10px] text-muted-foreground">
                    {simulacao.notas.map((nota) => (
                      <li key={nota}>· {nota}</li>
                    ))}
                  </ul>
                  {simulacao.posicoes_disponiveis.length ? (
                    <div className="mt-3">
                      <p className="text-[11px] font-semibold">Posições desta carreira</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {simulacao.posicoes_disponiveis.map((posicao, indice) => (
                          <span
                            key={`${posicao.posicao}-${indice}`}
                            className="rounded-lg border border-white/10 px-2 py-1 text-[11px] tabular-nums"
                          >
                            <span className="text-muted-foreground">{posicao.posicao}</span> ·{" "}
                            {euroExato(posicao.remuneracao)} · n.º {posicao.nivel ?? "—"}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">Escolha uma posição e carregue em «Simular».</p>
              )}
            </Cartao>
          </div>
        ) : null}

        {aba === "notas" ? (
          <div className="space-y-3">
            {notas.map((item) => (
              <Cartao key={item.seccao}>
                <p className="text-sm font-semibold">{item.titulo ?? `Notas sobre ${item.seccao}`}</p>
                <p className="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
                  {item.texto.join("\n")}
                </p>
              </Cartao>
            ))}
            {baseLegal.length ? (
              <Cartao className="p-0">
                <div className="max-h-[520px] overflow-auto">
                  <table className="w-full min-w-[900px] text-[11px]">
                    <thead className="sticky top-0 bg-background/95">
                      <tr className="text-left text-muted-foreground">
                        <th className="px-3 py-2 font-medium">Carreira</th>
                        <th className="px-3 py-2 font-medium">Grau</th>
                        <th className="px-3 py-2 font-medium">Estrutura da carreira</th>
                        <th className="px-3 py-2 font-medium">Estrutura remuneratória</th>
                        <th className="px-3 py-2 font-medium">Outras componentes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {baseLegal.flatMap((tabela) =>
                        tabela.linhas.map((linha, indice) => (
                          <tr key={`${tabela.seccao}-${indice}`} className="border-t border-white/5">
                            <td className="px-3 py-1.5 font-medium">{linha["Designação da carreira"]}</td>
                            <td className="px-3 py-1.5 text-muted-foreground">{linha["Grau"]}</td>
                            <td className="px-3 py-1.5 text-muted-foreground">
                              {linha["Legislação - Estrutura da carreira"]}
                            </td>
                            <td className="px-3 py-1.5 text-muted-foreground">
                              {linha["Legislação - Estrutura remuneratória"]}
                            </td>
                            <td className="px-3 py-1.5 text-muted-foreground">
                              {linha["Legislação - Outras componentes remuneratórias"]}
                            </td>
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                </div>
              </Cartao>
            ) : null}
          </div>
        ) : null}

        <footer className="pb-2 text-[10px] text-muted-foreground">
          {meta?.fonte ? (
            <>
              Quadro:{" "}
              <a className="underline hover:text-foreground" href={meta.fonte_url} target="_blank" rel="noreferrer">
                {meta.fonte}
              </a>
              .{" "}
            </>
          ) : null}
          {anos.length ? `Anos recolhidos: ${anos.slice().reverse().join(", ")}. ` : null}
          {meta?.unidade ? `Unidade: ${meta.unidade}.` : null}
          {valorDoNivel.size && parametros?.brap
            ? ` Nível 5 = ${euroExato(parametros.brap)} (BRAP).`
            : null}
        </footer>
      </div>
    </div>
  );
}
