/**
 * Página do módulo **Despesas das câmaras municipais**.
 *
 * Uma **área por município**, juntando duas fontes que se cruzam:
 *
 * 1. a **despesa** do indicador 0013909 do INE (origem DGAL), pelo
 *    classificador económico (`D` total, `D1` corrente, `D2` capital e o
 *    detalhe `D11`…`D25`), em euros. O INE publica em milhares de euros e o
 *    backend converte;
 * 2. a **contratação pública** em que o município é adjudicante, agregada do
 *    Portal BASE — quantos contratos, quanto valem, por ano e os principais
 *    fornecedores.
 *
 * A lista ordena-se por qualquer uma das duas (no Elasticsearch, não no
 * browser), para se poder responder a «onde se gasta mais» e «onde se contrata
 * mais» sem trocar de ecrã.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Info,
  Loader2,
  MapPin,
  RefreshCw,
  Scale,
  Search,
  TrendingUp,
  X,
} from "lucide-react";

import {
  euroCompacto,
  getMunicipioFicha,
  getMunicipiosDespesas,
  getMunicipiosDespesasMeta,
  numero,
  recolherMunicipiosDespesas,
  type MunicipioDespesas,
  type MunicipioFicha,
  type MunicipiosDespesasMeta,
  type MunicipiosDespesasResponse,
} from "../municipiosApi";

/* ------------------------------------------------------------------ opções */

const ORDENACOES = [
  { id: "despesas", label: "Despesa total" },
  { id: "pessoal", label: "Despesas com pessoal" },
  { id: "bens_servicos", label: "Bens e serviços" },
  { id: "capital", label: "Despesas de capital" },
  { id: "contratos", label: "Valor contratado" },
  { id: "contratos_total", label: "N.º de contratos" },
  { id: "nome", label: "Nome" },
] as const;

/** Os classificadores que ganham barra na ficha, por ordem de leitura. */
const CLASSIFICADORES_FICHA = [
  "D",
  "D1",
  "D11",
  "D12",
  "D13",
  "D14",
  "D15",
  "D2",
  "D21",
  "D22",
  "D221",
  "D222",
  "D23",
  "D24",
  "D25",
] as const;

/* ---------------------------------------------------------------- primitivas */

function Cartao({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
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

/** Barra proporcional simples, com o rótulo à esquerda e o valor à direita. */
function Barra({
  rotulo,
  valor,
  maximo,
  tom = "teal",
}: {
  rotulo: string;
  valor?: number | null;
  maximo: number;
  tom?: "teal" | "amber" | "violet";
}) {
  const largura = maximo > 0 ? Math.min(100, ((valor ?? 0) / maximo) * 100) : 0;
  const cor =
    tom === "amber" ? "bg-amber-400/60" : tom === "violet" ? "bg-violet-400/60" : "bg-teal-400/60";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">{rotulo}</span>
        <span className="text-[11px] tabular-nums">{euroCompacto(valor)}</span>
      </div>
      <div className="mt-0.5 h-1.5 w-full rounded-full bg-white/5">
        <div className={`h-1.5 rounded-full ${cor}`} style={{ width: `${largura}%` }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- ficha */

function FichaMunicipio({ ficha }: { ficha: MunicipioFicha }) {
  const classificadores = ficha.classificadores ?? {};
  const valores = useMemo(() => {
    const linhas = CLASSIFICADORES_FICHA.map((codigo) => ({
      codigo,
      etiqueta: classificadores[codigo] ?? codigo,
      valor: (ficha as unknown as Record<string, number | null | undefined>)[
        `despesas_${campoDoCodigo(codigo)}`
      ] ?? null,
    }));
    return linhas;
  }, [ficha, classificadores]);

  const maximo = useMemo(
    () => Math.max(1, ...valores.map((l) => l.valor ?? 0)),
    [valores],
  );

  const contratos = ficha.contratos_detalhe as
    | { total?: number; valor?: number; por_ano?: Record<string, { contratos: number; valor: number }>; fornecedores?: { nome: string; contratos: number; valor: number }[]; tipos?: { key: string; count: number }[] }
    | undefined;

  const serie = useMemo(() => {
    const dados = (contratos?.por_ano ?? ficha.contratos_por_ano) || {};
    return Object.entries(dados)
      .map(([ano, v]) => ({ ano, ...v }))
      .sort((a, b) => a.ano.localeCompare(b.ano))
      .slice(-14);
  }, [contratos, ficha.contratos_por_ano]);

  const maxSerie = useMemo(() => Math.max(1, ...serie.map((s) => s.valor)), [serie]);
  const correntes = ficha.despesas_correntes ?? 0;
  const capital = ficha.despesas_capital ?? 0;
  const totalCorrenteCapital = correntes + capital;
  const ano = ficha.ano_despesas ?? null;

  return (
    <div className="space-y-4">
      <Cartao>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Building2 size={18} className="shrink-0 text-teal-300" />
              <span className="truncate">{ficha.nome}</span>
            </h2>
            <p className="mt-1 text-[11px] text-muted-foreground">
              <MapPin size={11} className="mr-1 inline" />
              {[ficha.distrito, ficha.nuts_nome].filter(Boolean).join(" · ") || "sem distrito identificado"}
              {ficha.geocod ? ` · INE ${ficha.geocod}` : ""}
            </p>
          </div>
          {ano ? (
            <span className="shrink-0 rounded-full bg-teal-400/10 px-2 py-0.5 text-[11px] text-teal-200">
              despesa de {ano}
            </span>
          ) : (
            <span className="shrink-0 rounded-full bg-amber-400/10 px-2 py-0.5 text-[11px] text-amber-200">
              sem despesa publicada
            </span>
          )}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 text-[11px] @3xl:grid-cols-4">
          <div>
            <p className="text-muted-foreground">Despesa total</p>
            <p className="text-base font-semibold tabular-nums">{euroCompacto(ficha.despesas_total)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Com pessoal</p>
            <p className="text-base font-semibold tabular-nums">{euroCompacto(ficha.despesas_pessoal)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Contratos</p>
            <p className="text-base font-semibold tabular-nums">{numero(ficha.contratos_total)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Valor contratado</p>
            <p className="text-base font-semibold tabular-nums">{euroCompacto(ficha.contratos_valor)}</p>
          </div>
        </div>
        {ficha.contratos_primeiro_ano && ficha.contratos_ultimo_ano ? (
          <p className="mt-2 text-[10px] text-muted-foreground">
            Contratação no Portal BASE de {ficha.contratos_primeiro_ano} a {ficha.contratos_ultimo_ano}.
          </p>
        ) : null}
      </Cartao>

      <div className="grid gap-4 @3xl:grid-cols-2">
        <Cartao>
          <h3 className="text-xs font-semibold">
            Despesa por classificador económico{ano ? ` · ${ano}` : ""}
          </h3>
          {totalCorrenteCapital > 0 ? (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Corrente{" "}
              <strong className="text-foreground">
                {((correntes / totalCorrenteCapital) * 100).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} %
              </strong>{" "}
              · Capital{" "}
              <strong className="text-foreground">
                {((capital / totalCorrenteCapital) * 100).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} %
              </strong>
            </p>
          ) : null}
          <div className="mt-3 space-y-2">
            {valores.map((linha) => (
              <Barra
                key={linha.codigo}
                rotulo={`${linha.codigo} · ${linha.etiqueta}`}
                valor={linha.valor}
                maximo={maximo}
                tom={
                  linha.codigo === "D"
                    ? "amber"
                    : linha.codigo.startsWith("D2")
                      ? "violet"
                      : "teal"
                }
              />
            ))}
          </div>
        </Cartao>

        <Cartao>
          <h3 className="text-xs font-semibold">Contratação pública por ano</h3>
          {serie.length ? (
            <>
              <div className="mt-3 space-y-1.5">
                {serie.map((ponto) => (
                  <div key={ponto.ano} className="flex items-center gap-2">
                    <span className="w-10 shrink-0 text-[10px] tabular-nums text-muted-foreground">
                      {ponto.ano}
                    </span>
                    <div className="h-2 min-w-0 flex-1 rounded-full bg-white/5">
                      <div
                        className="h-2 rounded-full bg-sky-400/60"
                        style={{ width: `${(ponto.valor / maxSerie) * 100}%` }}
                      />
                    </div>
                    <span className="w-20 shrink-0 text-right text-[10px] tabular-nums">
                      {euroCompacto(ponto.valor)}
                    </span>
                    <span className="w-14 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">
                      {numero(ponto.contratos)}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-2 flex justify-end gap-2 text-[10px] text-muted-foreground">
                <span className="w-20 text-right">valor</span>
                <span className="w-14 text-right">contratos</span>
              </div>
            </>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Sem contratos atribuídos a este município no Portal BASE.
            </p>
          )}
        </Cartao>
      </div>

      {contratos?.fornecedores?.length ? (
        <Cartao>
          <h3 className="text-xs font-semibold">Principais fornecedores do município</h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[380px] text-[11px]">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 pr-2 font-medium">Fornecedor</th>
                  <th className="py-1 pl-2 text-right font-medium whitespace-nowrap">Contratos</th>
                  <th className="py-1 pl-2 text-right font-medium whitespace-nowrap">Valor</th>
                </tr>
              </thead>
              <tbody>
                {contratos.fornecedores.map((f) => (
                  <tr key={f.nome} className="border-t border-white/5">
                    <td className="py-1 pr-2">{f.nome}</td>
                    <td className="py-1 pl-2 text-right align-top tabular-nums">{numero(f.contratos)}</td>
                    <td className="py-1 pl-2 text-right align-top tabular-nums whitespace-nowrap">
                      {euroCompacto(f.valor)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {contratos.tipos?.length ? (
            <p className="mt-2 text-[10px] text-muted-foreground">
              Tipos: {contratos.tipos.slice(0, 4).map((t) => `${t.key} (${t.count})`).join(" · ")}
            </p>
          ) : null}
        </Cartao>
      ) : null}

      {ficha.adjudicantes?.length ? (
        <Cartao>
          <h3 className="text-xs font-semibold">Como o município aparece no Portal BASE</h3>
          <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
            {ficha.adjudicantes.map((a) => (
              <li key={a} className="truncate" title={a}>
                {a}
              </li>
            ))}
          </ul>
        </Cartao>
      ) : null}
    </div>
  );
}

/** `D11` → `pessoal` (o nome do campo no índice). */
function campoDoCodigo(codigo: string): string {
  const mapa: Record<string, string> = {
    D: "total",
    D1: "correntes",
    D2: "capital",
    D11: "pessoal",
    D12: "bens_servicos",
    D13: "juros",
    D14: "transferencias_freguesias",
    D15: "outras_correntes",
    D21: "bens_capital",
    D22: "transferencias_capital",
    D221: "transferencias_capital_freguesias",
    D222: "outras_transferencias_capital",
    D23: "outras_capital",
    D24: "ativos_financeiros",
    D25: "passivos_financeiros",
  };
  return mapa[codigo] ?? codigo.toLowerCase();
}

/* -------------------------------------------------------------------- página */

export default function MunicipiosDespesasPage() {
  const [meta, setMeta] = useState<MunicipiosDespesasMeta | null>(null);
  const [dados, setDados] = useState<MunicipiosDespesasResponse | null>(null);
  const [detalhe, setDetalhe] = useState<MunicipioFicha | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [aDetalhar, setADetalhar] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [distrito, setDistrito] = useState("");
  const [anoContratos, setAnoContratos] = useState("");
  const [ordenar, setOrdenar] = useState<string>("despesas");
  const [ordem, setOrdem] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const carregar = useCallback(
    async (pagina = 1) => {
      setACarregar(true);
      setErro(null);
      try {
        const resposta = await getMunicipiosDespesas({
          q: q.trim() || undefined,
          distrito: distrito || undefined,
          ano_contratos: anoContratos ? Number(anoContratos) : undefined,
          ordenar,
          ordem,
          page: pagina,
          size: 30,
        });
        setDados(resposta);
        setPage(pagina);
      } catch (excecao) {
        setErro(excecao instanceof Error ? excecao.message : String(excecao));
      } finally {
        setACarregar(false);
      }
    },
    [q, distrito, anoContratos, ordenar, ordem],
  );

  useEffect(() => {
    // `carregar` muda de identidade quando um filtro muda: é ele que traz a
    // lista do filtro que o utilizador acabou de escolher.
    void carregar(1);
  }, [carregar]);

  useEffect(() => {
    getMunicipiosDespesasMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);

  const abrir = useCallback(async (municipio: MunicipioDespesas) => {
    setADetalhar(true);
    setErro(null);
    try {
      setDetalhe(await getMunicipioFicha(municipio.geocod || municipio.nome));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setADetalhar(false);
    }
  }, []);

  const recolher = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      await recolherMunicipiosDespesas(true);
      await carregar(1);
      setMeta(await getMunicipiosDespesasMeta().catch(() => null));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setARecolher(false);
    }
  }, [carregar]);

  const distritos = useMemo(
    () => (dados?.distritos ?? []).map((d) => d.key).sort((a, b) => a.localeCompare(b)),
    [dados],
  );
  const totalPaginas = dados ? Math.max(1, Math.ceil(dados.total / dados.size)) : 1;
  const indice = meta?.indice;

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="space-y-4 p-4 lg:p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Despesas das câmaras municipais</h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              A despesa de cada município pelo classificador económico —{" "}
              {meta?.fonte_despesas ?? "INE · indicador 0013909 (DGAL)"} — cruzada com a
              contratação pública em que o município é adjudicante ({meta?.fonte_contratos ?? "Portal BASE"}).
              {meta?.designacao ? ` ${meta.designacao}` : ""} Valores em euros
              {meta?.ultimo_periodo ? `, ano ${meta.ultimo_periodo}` : ""}.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void recolher()}
            disabled={aRecolher}
            className="flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
          >
            {aRecolher ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Recolher de novo
          </button>
        </header>

        <section className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
          <Kpi label="Municípios" valor={numero(indice?.documents ?? meta?.diagnostico?.municipios)} />
          <Kpi
            label="Despesa somada"
            valor={euroCompacto(indice?.total_despesas)}
            nota={meta?.ultimo_periodo ? `ano ${meta.ultimo_periodo}` : undefined}
          />
          <Kpi
            label={dados?.ano_contratos ? `Contratado em ${dados.ano_contratos}` : "Valor contratado"}
            valor={euroCompacto(
              dados?.ano_contratos ? dados.contratos_ano_somados : indice?.total_contratos,
            )}
            nota={
              dados?.ano_contratos
                ? `${numero(dados.contratos_ano_total_somados)} contratos · Portal BASE`
                : "Portal BASE"
            }
          />
          <Kpi
            label="Sem despesa publicada"
            valor={numero(indice?.sem_despesas)}
            nota="o INE não publica o valor («//»)"
          />
        </section>

        <section className="glass-card min-w-0 rounded-2xl p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
              <input
                value={q}
                onChange={(evento) => setQ(evento.target.value)}
                onKeyDown={(evento) => evento.key === "Enter" && void carregar(1)}
                placeholder="Procurar município ou código INE"
                className="w-full rounded-lg border border-input bg-background py-1.5 pl-8 pr-8 text-xs"
              />
              {q ? (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    void carregar(1);
                  }}
                  aria-label="Limpar"
                  className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
                >
                  <X size={13} />
                </button>
              ) : null}
            </div>

            <select
              value={distrito}
              onChange={(evento) => setDistrito(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              <option value="">Todos os distritos</option>
              {distritos.map((nome) => (
                <option key={nome} value={nome}>
                  {nome}
                </option>
              ))}
            </select>

            <select
              value={anoContratos}
              onChange={(evento) => setAnoContratos(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
              title="Ver e ordenar a contratação de um ano do Portal BASE"
            >
              <option value="">Contratação: todos os anos</option>
              {(meta?.anos_contratos ?? []).map((ano) => (
                <option key={ano} value={ano}>
                  Contratação em {ano}
                </option>
              ))}
            </select>

            <select
              value={ordenar}
              onChange={(evento) => setOrdenar(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              {ORDENACOES.map((item) => (
                <option key={item.id} value={item.id}>
                  Ordenar por {item.label.toLowerCase()}
                  {anoContratos && (item.id === "contratos" || item.id === "contratos_total")
                    ? ` (${anoContratos})`
                    : ""}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => setOrdem(ordem === "desc" ? "asc" : "desc")}
              className="min-h-[32px] rounded-lg border border-input px-2 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
              title="Inverter a ordem"
            >
              {ordem === "desc" ? "↓ decrescente" : "↑ crescente"}
            </button>
          </div>

          <p className="mt-2 text-[11px] text-muted-foreground">
            <strong className="text-foreground">{numero(dados?.total)}</strong> municípios.
            {dados?.despesas_somadas ? (
              <>
                {" "}
                Despesa somada: <strong className="text-foreground">{euroCompacto(dados.despesas_somadas)}</strong> ·
                contratado: <strong className="text-foreground">{euroCompacto(dados.contratos_somados)}</strong>.
                {dados.ano_contratos ? (
                  <>
                    {" "}
                    Em <strong className="text-foreground">{dados.ano_contratos}</strong> foram celebrados{" "}
                    <strong className="text-foreground">{numero(dados.contratos_ano_total_somados)}</strong> contratos, no
                    valor de <strong className="text-foreground">{euroCompacto(dados.contratos_ano_somados)}</strong>.
                  </>
                ) : null}
              </>
            ) : null}
            {meta?.atualizado_no_ine ? ` INE atualizado em ${meta.atualizado_no_ine}.` : null}
          </p>
        </section>

        {erro ? (
          <Cartao className="text-center">
            <p className="text-sm text-rose-300">{erro}</p>
          </Cartao>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,min(46%,860px))]">
          <div className="min-w-0 space-y-3">
            <Cartao className="overflow-x-auto p-0">
              <table className="w-full min-w-[560px] text-[11px]">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Município</th>
                    <th className="px-3 py-2 font-medium">Distrito</th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">Despesa total</th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">Com pessoal</th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">
                      {dados?.ano_contratos ? `Contratos ${dados.ano_contratos}` : "Contratos"}
                    </th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">
                      {dados?.ano_contratos ? `Contratado ${dados.ano_contratos}` : "Valor contratado"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(dados?.items ?? []).map((m) => (
                    <tr
                      key={m.doc_id || m.nome}
                      onClick={() => void abrir(m)}
                      className={`cursor-pointer border-t border-white/5 transition hover:bg-white/5 ${
                        detalhe?.nome === m.nome ? "bg-white/[0.07]" : ""
                      }`}
                      title="Abrir a área deste município"
                    >
                      <td className="px-3 py-1.5 font-medium">
                        <span className="flex items-center gap-2">
                          <Scale size={11} className="shrink-0 text-teal-300/70" />
                          {m.nome}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.distrito ?? "—"}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                        {euroCompacto(m.despesas_total)}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                        {euroCompacto(m.despesas_pessoal)}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {m.contratos_ano_total ?? numero(m.contratos_total)}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                        {euroCompacto(m.contratos_ano_valor ?? m.contratos_valor)}
                      </td>
                    </tr>
                  ))}
                  {dados && dados.items.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                        Nenhum município com os filtros atuais.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Cartao>

            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] text-muted-foreground">
                {aCarregar ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" /> a carregar…
                  </span>
                ) : (
                  `página ${page} de ${totalPaginas}`
                )}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void carregar(Math.max(1, page - 1))}
                  disabled={page <= 1 || aCarregar}
                  className="rounded-lg border border-white/10 px-2 py-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
                >
                  Anterior
                </button>
                <button
                  type="button"
                  onClick={() => void carregar(Math.min(totalPaginas, page + 1))}
                  disabled={page >= totalPaginas || aCarregar}
                  className="rounded-lg border border-white/10 px-2 py-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
                >
                  Seguinte
                </button>
              </div>
            </div>
          </div>

          <div className="min-w-0">
            {aDetalhar ? (
              <Cartao className="flex h-40 items-center justify-center text-xs text-muted-foreground">
                <Loader2 size={14} className="mr-2 animate-spin" /> A carregar o município…
              </Cartao>
            ) : detalhe ? (
              <FichaMunicipio key={detalhe.nome} ficha={detalhe} />
            ) : (
              <Cartao>
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <Info size={14} /> Escolha um município
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Cada município tem uma área própria com a despesa por classificador económico, a
                  contratação pública por ano e os principais fornecedores.
                </p>
                <p className="mt-2 text-[10px] text-muted-foreground">
                  <TrendingUp size={10} className="mr-1 inline" />
                  Os valores do INE vêm em milhares de euros (potência de 10 = 3) e são apresentados já
                  convertidos em euros.
                </p>
              </Cartao>
            )}
          </div>
        </div>

        <footer className="pb-2 text-[10px] text-muted-foreground">
          {meta?.fonte_despesas ? (
            <>
              Despesas:{" "}
              <a className="underline hover:text-foreground" href={meta.fonte_despesas_url ?? "#"} target="_blank" rel="noreferrer">
                {meta.fonte_despesas}
              </a>
              .{" "}
            </>
          ) : null}
          {meta?.fonte_dados_gov ? (
            <>
              Conjunto de dados:{" "}
              <a className="underline hover:text-foreground" href={meta.fonte_dados_gov} target="_blank" rel="noreferrer">
                dados.gov.pt
              </a>
              .{" "}
            </>
          ) : null}
          {meta?.recolhido_em ? `Recolhido em ${meta.recolhido_em}. ` : null}
          {meta?.diagnostico?.adjudicantes_nao_atribuidos ? (
            <>
              {numero(meta.diagnostico.adjudicantes_nao_atribuidos)} adjudicantes não atribuídos a um
              município ({euroCompacto(meta.diagnostico.valor_nao_atribuido)}) — associações
              intermunicipais e empresas de capitais públicos, que não pertencem a um só concelho.
            </>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
