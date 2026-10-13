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
 * mais» sem trocar de ecrã. Cada linha mostra ainda os **anos mais recentes**
 * de contratação do município (Portal BASE), para o ano escolhido no filtro não
 * ser a única janela sobre a série.
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
  getMunicipioFornecedores,
  getMunicipiosDespesas,
  getMunicipiosDespesasMeta,
  numero,
  recolherMunicipiosDespesas,
  type MunicipioDespesas,
  type MunicipioFicha,
  type MunicipioFornecedores,
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

function FichaMunicipio({
  ficha,
  anoSelecionado,
}: {
  ficha: MunicipioFicha;
  /** Ano escolhido no filtro da lista: fica destacado na série. */
  anoSelecionado?: string;
}) {
  const [todosFornecedores, setTodosFornecedores] = useState(false);
  const [fornecedores, setFornecedores] = useState<MunicipioFornecedores | null>(null);
  const [aCarregarFornecedores, setACarregarFornecedores] = useState(false);
  const [buscaFornecedor, setBuscaFornecedor] = useState("");
  const [termoFornecedor, setTermoFornecedor] = useState("");
  const [paginaFornecedores, setPaginaFornecedores] = useState(1);
  const [erroFornecedores, setErroFornecedores] = useState<string | null>(null);
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
    | {
        total?: number;
        valor?: number;
        por_ano?: Record<string, { contratos: number; valor: number }>;
        fornecedores?: { nome: string; contratos: number; valor: number }[];
        tipos?: { key: string; count: number; valor?: number }[];
        cpv?: { divisao: string; descricao?: string | null; tipo?: string; contratos: number; valor: number }[];
        ano?: number;
        ano_total?: number;
        ano_valor?: number;
        ano_maximo?: number | null;
        ano_fornecedores?: { nome: string; contratos: number; valor: number }[];
        ano_tipos?: { key: string; count: number; valor?: number }[];
        ano_cpv?: { divisao: string; descricao?: string | null; tipo?: string; contratos: number; valor: number }[];
      }
    | undefined;

  // Com um ano escolhido no filtro, a contratação mostrada é a **desse ano**,
  // calculada no índice do Portal BASE (é a única fonte com contratação ano a
  // ano); sem ano, são os totais de 2012 até hoje. A despesa do INE não segue o
  // ano: o indicador só publica um ano e fica identificado como tal.
  const anoDoFiltro = anoSelecionado && contratos?.ano === Number(anoSelecionado) ? anoSelecionado : null;
  const principaisFornecedores =
    (anoDoFiltro ? contratos?.ano_fornecedores : contratos?.fornecedores) ?? [];
  const tipos = (anoDoFiltro ? contratos?.ano_tipos : contratos?.tipos) ?? [];

  const serie = useMemo(() => {
    const dados = (contratos?.por_ano ?? ficha.contratos_por_ano) || {};
    return Object.entries(dados)
      .map(([ano, v]) => ({ ano, ...v }))
      .sort((a, b) => a.ano.localeCompare(b.ano))
      .slice(-14);
  }, [contratos, ficha.contratos_por_ano]);

  const maxSerie = useMemo(() => Math.max(1, ...serie.map((s) => s.valor)), [serie]);
  // Tipos de despesa: as divisões de CPV do ano escolhido (ou de todo o período).
  const tiposDespesa = (anoDoFiltro ? contratos?.ano_cpv : contratos?.cpv) ?? [];
  const maxTiposDespesa = useMemo(
    () => Math.max(1, ...tiposDespesa.map((t) => t.valor)),
    [tiposDespesa],
  );

  // A lista completa de fornecedores é pedida ao índice quando o utilizador a
  // abre (e de novo quando muda o ano, a pesquisa ou a página): a ficha só traz
  // os maiores, que é o que interessa à primeira vista.
  useEffect(() => {
    if (!todosFornecedores) return;
    let ativo = true;
    setACarregarFornecedores(true);
    setErroFornecedores(null);
    getMunicipioFornecedores(ficha.geocod || ficha.nome, {
      ano: anoSelecionado || undefined,
      q: termoFornecedor || undefined,
      size: 50,
      page: paginaFornecedores,
    })
      .then((resposta) => {
        if (ativo) setFornecedores(resposta);
      })
      .catch((excecao) => {
        if (ativo) setErroFornecedores(excecao instanceof Error ? excecao.message : String(excecao));
      })
      .finally(() => {
        if (ativo) setACarregarFornecedores(false);
      });
    return () => {
      ativo = false;
    };
  }, [todosFornecedores, ficha.nome, ficha.geocod, anoSelecionado, termoFornecedor, paginaFornecedores]);

  const totalPaginasFornecedores = fornecedores
    ? Math.max(1, Math.ceil(fornecedores.total / Math.max(1, fornecedores.size)))
    : 1;
  const correntes = ficha.despesas_correntes ?? 0;
  const capital = ficha.despesas_capital ?? 0;
  const totalCorrenteCapital = correntes + capital;
  const ano = ficha.ano_despesas ?? null;
  // O INE só tem a despesa do ano que publica: com outro ano escolhido — ou num
  // município sem despesa publicada —, mostra-se a contratação do Portal BASE,
  // que é a plataforma com o dado por ano (índice `contratos`).
  const mostraIne =
    ficha.despesas_total != null && (!anoSelecionado || Number(anoSelecionado) === Number(ano));

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
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            {anoDoFiltro ? (
              <span
                className="rounded-full bg-sky-400/10 px-2 py-0.5 text-[11px] text-sky-200"
                title="Contratação calculada no índice do Portal BASE para o ano escolhido na lista."
              >
                contratação de {anoDoFiltro}
              </span>
            ) : null}
            {mostraIne ? (
              <span
                className="rounded-full bg-teal-400/10 px-2 py-0.5 text-[11px] text-teal-200"
                title={`Despesa do INE do ano ${ano} — o indicador 0013909 só publica um ano (2021→2023). O ano da página vem do Portal BASE.`}
              >
                despesa INE de {ano}
              </span>
            ) : (
              <span
                className="rounded-full bg-violet-400/10 px-2 py-0.5 text-[11px] text-violet-200"
                title={
                  ficha.despesas_total == null
                    ? "O INE não publica despesa para este município — os valores mostrados são do Portal BASE."
                    : `O INE não publica despesa para ${anoSelecionado} — os valores mostrados são do Portal BASE.`
                }
              >
                sem INE · Portal BASE
              </span>
            )}
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3 text-[11px] @3xl:grid-cols-4">
          <div>
            <p className="text-muted-foreground">
              Contratos {anoDoFiltro ?? ""} <span className="opacity-60">· Portal BASE</span>
            </p>
            <p className="text-base font-semibold tabular-nums">
              {numero(anoDoFiltro ? contratos?.ano_total ?? 0 : ficha.contratos_total)}
            </p>
            {anoDoFiltro ? (
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                de {numero(ficha.contratos_total)} desde {ficha.contratos_primeiro_ano}
              </p>
            ) : null}
          </div>
          <div>
            <p className="text-muted-foreground">
              Valor contratado {anoDoFiltro ?? ""} <span className="opacity-60">· Portal BASE</span>
            </p>
            <p className="text-base font-semibold tabular-nums">
              {euroCompacto(anoDoFiltro ? contratos?.ano_valor ?? 0 : ficha.contratos_valor)}
            </p>
            {anoDoFiltro ? (
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                de {euroCompacto(ficha.contratos_valor)} no total
              </p>
            ) : null}
          </div>
          {mostraIne ? (
            <>
              <div>
                <p className="text-muted-foreground">
                  Despesa total <span className="opacity-60">· INE {ano ?? ""}</span>
                </p>
                <p className="text-base font-semibold tabular-nums">{euroCompacto(ficha.despesas_total)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">
                  Com pessoal <span className="opacity-60">· INE {ano ?? ""}</span>
                </p>
                <p className="text-base font-semibold tabular-nums">
                  {euroCompacto(ficha.despesas_pessoal)}
                </p>
              </div>
            </>
          ) : (
            <>
              <div>
                <p className="text-muted-foreground">
                  Maior contrato {anoDoFiltro ?? ""} <span className="opacity-60">· Portal BASE</span>
                </p>
                <p className="text-base font-semibold tabular-nums">
                  {anoDoFiltro
                    ? euroCompacto(contratos?.ano_maximo ?? 0)
                    : euroCompacto(principaisFornecedores[0]?.valor)}
                </p>
                {!anoDoFiltro && principaisFornecedores[0] ? (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">maior fornecedor</p>
                ) : null}
              </div>
              <div>
                <p className="text-muted-foreground">
                  Principal fornecedor {anoDoFiltro ?? ""}{" "}
                  <span className="opacity-60">· Portal BASE</span>
                </p>
                <p
                  className="truncate text-base font-semibold"
                  title={principaisFornecedores[0]?.nome}
                >
                  {principaisFornecedores[0]?.nome ?? "—"}
                </p>
                {anoDoFiltro && principaisFornecedores[0] ? (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {numero(principaisFornecedores[0].contratos)} contratos ·{" "}
                    {euroCompacto(principaisFornecedores[0].valor)}
                  </p>
                ) : null}
              </div>
            </>
          )}
        </div>
        {ficha.contratos_primeiro_ano && ficha.contratos_ultimo_ano ? (
          <p className="mt-2 text-[10px] text-muted-foreground">
            Contratação no Portal BASE de {ficha.contratos_primeiro_ano} a {ficha.contratos_ultimo_ano}.
          </p>
        ) : null}
      </Cartao>

      <div className="grid gap-4 @3xl:grid-cols-2">
        <Cartao>
          {mostraIne ? (
            <>
              <h3 className="text-xs font-semibold">
                Despesa por classificador económico{ano ? ` · INE ${ano}` : ""}
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
            </>
          ) : (
            <>
              <h3 className="text-xs font-semibold">
                Tipos de despesa (CPV){anoDoFiltro ? ` · ${anoDoFiltro}` : ""}
              </h3>
              <p className="mt-1 text-[10px] text-muted-foreground">
                {ficha.despesas_total == null
                  ? "Este município não tem despesa publicada pelo INE — a contratação é classificada pelas divisões de CPV do Portal BASE."
                  : `O INE só publica a despesa de ${ano} (2021→2023): mostramos a contratação de ${anoSelecionado}, pelas divisões de CPV do Portal BASE.`}
              </p>
              <div className="mt-3 space-y-2">
                {tiposDespesa.length ? (
                  tiposDespesa.map((linha) => (
                    <Barra
                      key={linha.divisao}
                      rotulo={`${linha.divisao} · ${linha.tipo ?? linha.descricao ?? "CPV"} (${numero(
                        linha.contratos,
                      )})`}
                      valor={linha.valor}
                      maximo={maxTiposDespesa}
                      tom="violet"
                    />
                  ))
                ) : (
                  <p className="text-[11px] text-muted-foreground">
                    Sem contratos com CPV atribuído a este município neste período.
                  </p>
                )}
              </div>
            </>
          )}
        </Cartao>

        <Cartao>
          <h3 className="text-xs font-semibold">Contratação pública por ano</h3>
          <p className="mt-1 text-[10px] text-muted-foreground">
            Portal BASE
            {anoSelecionado ? ` · ${anoSelecionado} é o ano escolhido no filtro` : ""}
          </p>
          {serie.length ? (
            <>
              <div className="mt-3 space-y-1.5">
                {serie.map((ponto) => {
                  const ativo = Boolean(anoSelecionado) && ponto.ano === anoSelecionado;
                  return (
                    <div
                      key={ponto.ano}
                      className={`flex items-center gap-2 ${ativo ? "rounded bg-teal-400/10" : ""}`}
                    >
                      <span
                        className={`w-10 shrink-0 text-[10px] tabular-nums ${
                          ativo ? "text-teal-200" : "text-muted-foreground"
                        }`}
                      >
                        {ponto.ano}
                      </span>
                      <div className="h-2 min-w-0 flex-1 rounded-full bg-white/5">
                        <div
                          className={`h-2 rounded-full ${ativo ? "bg-teal-300/80" : "bg-sky-400/60"}`}
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
                  );
                })}
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

      {principaisFornecedores.length ? (
        <Cartao>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="text-xs font-semibold">
                Principais fornecedores{anoDoFiltro ? ` em ${anoDoFiltro}` : " do município"}
              </h3>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Portal BASE
                {anoDoFiltro ? " · contratos celebrados nesse ano" : " · desde 2012"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setTodosFornecedores((aberto) => !aberto);
                setPaginaFornecedores(1);
              }}
              className="min-h-[28px] rounded-lg border border-input px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
            >
              {todosFornecedores ? "Ver só os maiores" : "Ver todos os fornecedores"}
            </button>
          </div>

          {todosFornecedores ? (
            <>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <div className="relative min-w-[180px] flex-1">
                  <Search
                    size={13}
                    className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground"
                  />
                  <input
                    value={buscaFornecedor}
                    onChange={(evento) => setBuscaFornecedor(evento.target.value)}
                    onKeyDown={(evento) => {
                      if (evento.key !== "Enter") return;
                      setTermoFornecedor(buscaFornecedor);
                      setPaginaFornecedores(1);
                    }}
                    placeholder="Procurar fornecedor (Enter)"
                    className="w-full rounded-lg border border-input bg-background py-1.5 pl-8 pr-2 text-xs"
                  />
                </div>
                <span className="text-[10px] text-muted-foreground">
                  {aCarregarFornecedores
                    ? "a carregar…"
                    : `${numero(fornecedores?.total ?? 0)} fornecedores${
                        fornecedores?.valor_somado
                          ? ` · ${euroCompacto(fornecedores.valor_somado)} atribuídos`
                          : ""
                      }`}
                </span>
              </div>
              {erroFornecedores ? (
                <p className="mt-2 text-[11px] text-rose-300">{erroFornecedores}</p>
              ) : null}
              <div className="mt-2 max-h-72 overflow-auto">
                <table className="w-full min-w-[380px] text-[11px]">
                  <thead className="sticky top-0 bg-background/95">
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1 pr-2 font-medium">Fornecedor</th>
                      <th className="py-1 pl-2 text-right font-medium whitespace-nowrap">Contratos</th>
                      <th className="py-1 pl-2 text-right font-medium whitespace-nowrap">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(fornecedores?.items ?? []).map((f) => (
                      <tr key={f.nome} className="border-t border-white/5">
                        <td className="py-1 pr-2">{f.nome}</td>
                        <td className="py-1 pl-2 text-right align-top tabular-nums">
                          {numero(f.contratos)}
                        </td>
                        <td className="py-1 pl-2 text-right align-top tabular-nums whitespace-nowrap">
                          {euroCompacto(f.valor)}
                        </td>
                      </tr>
                    ))}
                    {!aCarregarFornecedores && !(fornecedores?.items ?? []).length ? (
                      <tr>
                        <td colSpan={3} className="py-3 text-center text-muted-foreground">
                          Nenhum fornecedor com esse nome.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                <span>
                  página {fornecedores?.page ?? 1} de {totalPaginasFornecedores}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPaginaFornecedores((pagina) => Math.max(1, pagina - 1))}
                    disabled={(fornecedores?.page ?? 1) <= 1 || aCarregarFornecedores}
                    className="rounded-lg border border-white/10 px-2 py-1 transition hover:text-foreground disabled:opacity-40"
                  >
                    Anterior
                  </button>
                  <button
                    type="button"
                    onClick={() => setPaginaFornecedores((pagina) => pagina + 1)}
                    disabled={
                      (fornecedores?.page ?? 1) >= totalPaginasFornecedores || aCarregarFornecedores
                    }
                    className="rounded-lg border border-white/10 px-2 py-1 transition hover:text-foreground disabled:opacity-40"
                  >
                    Seguinte
                  </button>
                </div>
              </div>
            </>
          ) : (
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
                  {principaisFornecedores.map((f) => (
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
          )}
          {tipos.length ? (
            <p className="mt-2 text-[10px] text-muted-foreground">
              Tipos: {tipos.slice(0, 4).map((t) => `${t.key} (${t.count})`).join(" · ")}
            </p>
          ) : null}
        </Cartao>
      ) : anoDoFiltro ? (
        <Cartao>
          <p className="text-[11px] text-muted-foreground">
            Sem contratos atribuídos a este município no Portal BASE em {anoDoFiltro}.
          </p>
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
  const [alvoDetalhe, setAlvoDetalhe] = useState<string | null>(null);
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

  const abrir = useCallback((municipio: MunicipioDespesas) => {
    setAlvoDetalhe(municipio.geocod || municipio.nome);
  }, []);

  useEffect(() => {
    // A área aberta segue o ano escolhido: mudar de ano recarrega a ficha, e a
    // agregação do ano é feita no índice do Portal BASE (não no INE).
    if (!alvoDetalhe) return;
    let ativo = true;
    setADetalhar(true);
    setErro(null);
    getMunicipioFicha(alvoDetalhe, anoContratos || undefined)
      .then((resposta) => {
        if (ativo) setDetalhe(resposta);
      })
      .catch((excecao) => {
        if (ativo) setErro(excecao instanceof Error ? excecao.message : String(excecao));
      })
      .finally(() => {
        if (ativo) setADetalhar(false);
      });
    return () => {
      ativo = false;
    };
  }, [alvoDetalhe, anoContratos]);

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
              {meta?.designacao ? ` ${meta.designacao}` : ""} Valores em euros: despesa de{" "}
              {meta?.ultimo_periodo ?? "um ano"} (o único ano que o INE publica) e contratação de{" "}
              {meta?.anos_contratos?.length
                ? `${meta.anos_contratos[meta.anos_contratos.length - 1]} a ${meta.anos_contratos[0]}`
                : "vários anos"}
              .
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

          {(meta?.totais_recentes ?? []).length ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground">
                Portal BASE, anos mais recentes:
              </span>
              {(meta?.totais_recentes ?? []).map((total) => {
                const ativo = anoContratos === total.ano;
                return (
                  <button
                    key={total.ano}
                    type="button"
                    onClick={() => setAnoContratos(ativo ? "" : total.ano)}
                    title={`${numero(total.contratos)} contratos, ${euroCompacto(total.valor)} em ${total.ano} — clique para escolher este ano`}
                    className={`rounded-full border px-2 py-0.5 text-[10px] tabular-nums transition ${
                      ativo
                        ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                        : "border-white/10 text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {total.ano} · {euroCompacto(total.valor)}
                  </button>
                );
              })}
            </div>
          ) : null}
        </section>

        {erro ? (
          <Cartao className="text-center">
            <p className="text-sm text-rose-300">{erro}</p>
          </Cartao>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,min(46%,860px))]">
          <div className="min-w-0 space-y-3">
            <Cartao className="overflow-x-auto p-0">
              <table className="w-full min-w-[860px] text-[11px]">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Município</th>
                    <th className="px-3 py-2 font-medium">Distrito</th>
                    <th
                      className="px-3 py-2 text-right font-medium whitespace-nowrap"
                      title={`${meta?.fonte_despesas ?? "INE · indicador 0013909 (DGAL)"} — o INE só publica o ano ${meta?.ultimo_periodo ?? "mais recente"}`}
                    >
                      Despesa total
                      {meta?.ultimo_periodo ? (
                        <span className="font-normal opacity-60"> {meta.ultimo_periodo}</span>
                      ) : null}
                    </th>
                    <th
                      className="px-3 py-2 text-right font-medium whitespace-nowrap"
                      title="Despesas com pessoal, do mesmo ano do INE"
                    >
                      Com pessoal
                    </th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">
                      {dados?.ano_contratos ? `Contratos ${dados.ano_contratos}` : "Contratos"}
                    </th>
                    <th className="px-3 py-2 text-right font-medium whitespace-nowrap">
                      {dados?.ano_contratos ? `Contratado ${dados.ano_contratos}` : "Valor contratado"}
                    </th>
                    <th
                      className="px-3 py-2 text-right font-medium whitespace-nowrap"
                      title="Os anos mais recentes de contratação de cada município (Portal BASE)"
                    >
                      Anos mais recentes
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
                      <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                        {m.contratos_recentes?.length ? (
                          m.contratos_recentes.map((ponto) => (
                            <span
                              key={ponto.ano}
                              className="ml-2 first:ml-0"
                              title={`${numero(ponto.contratos)} contratos em ${ponto.ano}`}
                            >
                              <span className="text-muted-foreground">{ponto.ano}</span>{" "}
                              {euroCompacto(ponto.valor)}
                            </span>
                          ))
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {dados && dados.items.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
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
              <FichaMunicipio
                key={detalhe.nome}
                ficha={detalhe}
                anoSelecionado={anoContratos || undefined}
              />
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
