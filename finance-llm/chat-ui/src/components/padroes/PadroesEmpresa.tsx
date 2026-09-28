/**
 * Painel **Empresa** do módulo de deteção de padrões.
 *
 * Fluxo: pesquisar (nome, marca ou NIF) → escolher a empresa → analisar.
 *
 * A análise responde às perguntas que se fazem a uma adjudicatária concreta:
 * quanto vale o seu portefólio, em que CPV, com que procedimentos, a quem vende,
 * que regras cumpre (e com que contratos), quem mais ganha aos mesmos
 * adjudicantes, quem são os gerentes, se está em insolvência e onde aparece.
 *
 * A régua de comparação **não** é o valor global: cada CPV é comparado com os
 * seus pares (mediana e MAD do log do valor), para que «atípico» signifique
 * atípico no setor.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Coins,
  ExternalLink,
  FileSearch,
  Gavel,
  Landmark,
  Loader2,
  Network,
  Newspaper,
  Percent,
  RefreshCw,
  Scale,
  Search,
  ShieldAlert,
  TrendingUp,
  Users,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analisarPadroesEmpresa, sugerirPadroesEmpresas } from "../../padroesApi";
import type { PadroesEmpresaAnalise, PadroesEmpresaContrato, PadroesEmpresaSugestao } from "../../padroesApi";
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
  formatEuro,
  formatNumber,
  formatPct,
  formatRatio,
  padraoLabel,
  padraoTone,
} from "./padroesKit";
import { PadroesEmpresaIA } from "./PadroesEmpresaIA";

const BAR_COLORS = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#4ade80"];
const SELECT_CLASS =
  "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground";

/** Pesquisa insensível a maiúsculas e acentos. */
function normalizar(value?: string | null): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

/** Chave de memória da última empresa analisada (para reabrir a página). */
const MEMORIA_KEY = "padroes:empresa";

/** Linhas de contrato renderizadas de uma vez (a tabela pode ter milhares). */
const LINHAS_TABELA = 150;

type OrdemContratos = "severidade" | "valor" | "ano" | "desvio";

export function PadroesEmpresa({ pais, onDossie }: { pais: string; onDossie?: (nif?: string | null) => void }) {
  const [texto, setTexto] = useState("");
  const [sugestoes, setSugestoes] = useState<PadroesEmpresaSugestao[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [aberto, setAberto] = useState(false);
  const [empresa, setEmpresa] = useState<PadroesEmpresaSugestao | null>(null);
  const [analise, setAnalise] = useState<PadroesEmpresaAnalise | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [anoFrom, setAnoFrom] = useState("");
  const [anoTo, setAnoTo] = useState("");
  const [maxContratos, setMaxContratos] = useState(400);
  const [contratoQuery, setContratoQuery] = useState("");
  const [soSinalizados, setSoSinalizados] = useState(false);
  const [padraoFiltro, setPadraoFiltro] = useState("");
  const [ordem, setOrdem] = useState<OrdemContratos>("severidade");
  const caixa = useRef<HTMLDivElement | null>(null);

  /** Analisa uma empresa concreta (chamado pela pesquisa e pela memória). */
  const analisar = useCallback(
    async (alvo: { nif?: string | null; nome?: string | null }, refresh = false) => {
      if (!alvo.nif && !alvo.nome) return;
      setLoading(true);
      setErro(null);
      setAnalise(null);
      setContratoQuery("");
      setPadraoFiltro("");
      setSoSinalizados(false);
      try {
        const dados = await analisarPadroesEmpresa({
          nif: alvo.nif ?? undefined,
          nome: alvo.nif ? undefined : (alvo.nome ?? undefined),
          pais,
          ano_from: anoFrom ? Number(anoFrom) : null,
          ano_to: anoTo ? Number(anoTo) : null,
          max_contratos: maxContratos,
          refresh,
        });
        if (dados.error) {
          setErro(dados.error);
          return;
        }
        setAnalise(dados);
        setAberto(false);
        if (dados.nif) {
          try {
            localStorage.setItem(MEMORIA_KEY, JSON.stringify({ nif: dados.nif, nome: dados.nome, pais }));
          } catch {
            /* memória indisponível */
          }
        }
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro desconhecido");
      } finally {
        setLoading(false);
      }
    },
    [anoFrom, anoTo, maxContratos, pais],
  );

  // Pesquisa com atraso (evita um pedido por tecla).
  useEffect(() => {
    const termo = texto.trim();
    if (termo.length < 3) {
      setSugestoes([]);
      setAviso(null);
      return;
    }
    let ativo = true;
    const timer = window.setTimeout(() => {
      setAProcurar(true);
      sugerirPadroesEmpresas(termo, { pais, limit: 8 })
        .then((resposta) => {
          if (!ativo) return;
          setSugestoes(resposta.items ?? []);
          setAberto((resposta.items ?? []).length > 0);
          setAviso(resposta.detail ?? null);
        })
        .catch(() => {
          if (ativo) setSugestoes([]);
        })
        .finally(() => {
          if (ativo) setAProcurar(false);
        });
    }, 320);
    return () => {
      ativo = false;
      window.clearTimeout(timer);
    };
  }, [texto, pais]);

  // Fechar as sugestões ao clicar fora.
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (caixa.current && !caixa.current.contains(event.target as Node)) setAberto(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Reabrir a última empresa analisada (a página é usada em investigação longa).
  useEffect(() => {
    try {
      const guardado = localStorage.getItem(MEMORIA_KEY);
      if (!guardado) return;
      const dados = JSON.parse(guardado) as { nif?: string; nome?: string; pais?: string };
      if (!dados?.nif || (dados.pais ?? "PT") !== pais) return;
      setEmpresa({ nif: dados.nif, nome: dados.nome });
      void analisar({ nif: dados.nif });
    } catch {
      /* memória indisponível */
    }
    // Só na montagem: depois disso a análise é sempre explícita.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resumo = analise?.resumo;
  const contratos = useMemo(() => {
    const termo = normalizar(contratoQuery);
    const items = (analise?.contratos ?? []).filter((item) => {
      if (soSinalizados && !(item.razoes ?? []).length) return false;
      if (padraoFiltro && !(item.razoes ?? []).some((razao) => razao.padrao === padraoFiltro)) return false;
      if (!termo) return true;
      return normalizar(`${item.objeto ?? ""} ${item.adjudicante ?? ""} ${item.cpv ?? ""} ${item.cpv_desc ?? ""}`).includes(termo);
    });
    const ordenado = [...items];
    ordenado.sort((a, b) => {
      if (ordem === "valor") return (b.valor ?? 0) - (a.valor ?? 0);
      if (ordem === "ano") return (b.ano ?? 0) - (a.ano ?? 0);
      if (ordem === "desvio") return (b.z_cpv ?? 0) - (a.z_cpv ?? 0);
      return 0; // já vem ordenado por severidade e valor
    });
    return ordenado;
  }, [analise, contratoQuery, padraoFiltro, soSinalizados, ordem]);

  const padroesPresentes = useMemo(
    () => [...new Set((analise?.sinais ?? []).map((sinal) => sinal.padrao))],
    [analise],
  );

  const graficoAnos = useMemo(
    () => (analise?.por_ano ?? []).map((item) => ({ ano: String(item.ano), contratos: item.contratos, valor: item.valor ?? 0 })),
    [analise],
  );

  return (
    <div className="flex flex-col gap-5">
      {/* ------------------------------------------------------------ pesquisa */}
      <SectionCard
        icon={Search}
        title="Pesquisar e analisar uma empresa"
        subtitle="Nome, marca ou NIF. A análise cobre os contratos em que a empresa é adjudicatária e as suas relações."
      >
        <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,0.7fr))]">
          <div className="relative" ref={caixa}>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2.5">
              {aProcurar ? (
                <Loader2 size={15} className="shrink-0 animate-spin text-teal-300" />
              ) : (
                <Search size={15} className="shrink-0 text-muted-foreground" />
              )}
              <input
                value={texto}
                onChange={(event) => {
                  setTexto(event.target.value);
                  setAviso(null);
                }}
                onFocus={() => setAberto(sugestoes.length > 0)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && texto.trim().length >= 3) {
                    setAberto(false);
                    void analisar({ nif: sugestoes[0]?.nif, nome: sugestoes[0]?.nif ? undefined : texto.trim() });
                  }
                }}
                placeholder="ex.: cimontubo · 503439800 · mota-engil"
                className="w-full bg-transparent text-sm normal-case tracking-normal text-foreground outline-none placeholder:text-muted-foreground/60"
              />
            </div>
            {aberto && sugestoes.length > 0 && (
              <ul className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-white/10 bg-[#0b1220]/95 p-1 shadow-xl backdrop-blur">
                {sugestoes.map((item) => (
                  <li key={`${item.nif}-${item.fonte ?? ""}`}>
                    <button
                      onClick={() => {
                        setTexto(item.nome ?? item.nif);
                        setAberto(false);
                        setEmpresa(item);
                        void analisar({ nif: item.nif });
                      }}
                      className="flex w-full items-start justify-between gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-white/10"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-foreground">{item.nome ?? item.nif}</span>
                        <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                          {item.nif}
                          {item.concelho ? ` · ${item.concelho}` : ""}
                          {item.fonte === "cadastro" ? " · cadastro" : " · contratos"}
                        </span>
                      </span>
                      <span className="shrink-0 text-right text-[11px] text-muted-foreground">
                        <span className="block">{formatNumber(item.contratos)} contratos</span>
                        <span className="block">{formatCompactEuro(item.valor)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <FilterField label="Ano de">
            <input value={anoFrom} onChange={(e) => setAnoFrom(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="2018" className={SELECT_CLASS} />
          </FilterField>
          <FilterField label="Ano até">
            <input value={anoTo} onChange={(e) => setAnoTo(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="2026" className={SELECT_CLASS} />
          </FilterField>
          <FilterField label="Contratos a analisar">
            <select value={maxContratos} onChange={(e) => setMaxContratos(Number(e.target.value))} className={SELECT_CLASS}>
              {[100, 200, 400, 700, 1000].map((valor) => (
                <option key={valor} value={valor}>
                  {valor}
                </option>
              ))}
            </select>
          </FilterField>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <button
            onClick={() => void analisar({ nif: empresa?.nif, nome: empresa?.nif ? undefined : texto.trim() }, true)}
            disabled={(!empresa?.nif && texto.trim().length < 3) || loading}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-muted-foreground transition hover:text-foreground disabled:opacity-40"
            title="Ignorar a cache e recalcular (exige sessão)"
          >
            <RefreshCw size={13} /> Recalcular
          </button>
          {empresa?.nif && (
            <Chip tone="teal">
              <Building2 size={11} /> {empresa.nome ?? empresa.nif} · {empresa.nif}
            </Chip>
          )}
          {onDossie && analise?.nif && (
            <button
              onClick={() => onDossie(analise.nif)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-teal-200 transition hover:text-teal-100"
            >
              <FileSearch size={13} /> Abrir dossiê
            </button>
          )}
          {analise?.cache && <Chip title="Resultado servido da cache (15 min)">cache</Chip>}
          {aviso && <span className="text-muted-foreground">{aviso}</span>}
        </div>

        {erro && (
          <div className="mt-3">
            <EmptyState tone="warn">{erro}</EmptyState>
          </div>
        )}
        {!erro && !analise && !loading && (
          <div className="mt-3">
            <EmptyState>
              Comece por escrever o nome da empresa (ou o NIF) e escolha uma das sugestões: a análise mostra o portefólio, os CPV onde
              atua, as regras que cumpre e quem se cruza com ela.
            </EmptyState>
          </div>
        )}
      </SectionCard>

      {loading && <Loading label="A analisar a empresa (contratos, pautas de CPV, regras e relações)…" />}

      {analise && (
        <>
          {/* ------------------------------------------------------------ fichas */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              icon={FileSearch}
              label="Contratos analisados"
              value={formatNumber(resumo?.contratos)}
              sub={`${formatNumber(analise.contratos_total)} registados${analise.anos ? ` · ${analise.anos[0]}–${analise.anos[1]}` : ""}`}
            />
            <Kpi
              icon={Coins}
              label="Valor adjudicado"
              value={formatCompactEuro(resumo?.valor_total)}
              sub={`mediana ${formatEuro(resumo?.valor_mediano, 0)}`}
              color="text-amber-300"
              glow="glow-amber"
            />
            <Kpi
              icon={ShieldAlert}
              label="Contratos com sinais"
              value={formatNumber(resumo?.contratos_com_sinais)}
              sub={`${formatNumber(resumo?.contratos_atipicos_cpv)} atípicos no CPV`}
              color="text-rose-300"
              glow="glow-rose"
            />
            <Kpi
              icon={Scale}
              label="Desvio mediano do preço base"
              value={formatRatio(resumo?.desvio_mediano)}
              sub="adjudicado ÷ preço base"
              color="text-sky-300"
              glow="glow-blue"
            />
            <Kpi
              icon={Percent}
              label="Ajuste direto"
              value={formatPct(resumo?.taxa_ajuste_direto)}
              sub="dos contratos da empresa"
              color="text-violet-300"
            />
            <Kpi
              icon={TrendingUp}
              label="Aditivos registados"
              value={formatPct(resumo?.taxa_aditivo)}
              sub="valor efetivo > 1,15× contratado"
              color="text-rose-300"
            />
            <Kpi
              icon={Landmark}
              label="Adjudicantes distintos"
              value={formatNumber(resumo?.adjudicantes_distintos)}
              sub={`maior concentra ${formatPct(resumo?.concentracao_adjudicante)}`}
              color="text-teal-300"
            />
            <Kpi
              icon={Network}
              label="CPV distintos"
              value={formatNumber(resumo?.cpvs)}
              sub={resumo?.insolvente ? "insolvência registada (CIRE)" : "sem processos no CIRE"}
              color={resumo?.insolvente ? "text-rose-300" : "text-teal-300"}
            />
          </div>

          {resumo?.insolvente && (
            <EmptyState tone="warn">
              <strong>Insolvência/PER registada</strong> no CIRE para {analise.nome}. Uma empresa insolvente a receber contratos públicos é o
              caso mais flagrante que este motor procura.
            </EmptyState>
          )}

          {/* ------------------------------------------- IA, browser e relatório */}
          <PadroesEmpresaIA
            analise={analise}
            pais={pais}
            anoFrom={anoFrom}
            anoTo={anoTo}
            maxContratos={maxContratos}
            onAbrirGuardada={(doc) => {
              if (doc.analise) {
                setAnalise(doc.analise);
                setEmpresa({ nif: doc.nif, nome: doc.nome });
              }
            }}
          />

          {/* ------------------------------------------------------------- sinais */}
          <SectionCard
            icon={AlertTriangle}
            title="Regras que a empresa cumpre"
            subtitle={
              analise.sinais.length
                ? "Cada linha é uma regra ativa do registo, com o número de contratos e um exemplo."
                : "Nenhuma regra ativa se aplica aos contratos analisados nesta janela."
            }
            actions={<Chip>{analise.regras_ativas?.length ?? 0} regras ativas</Chip>}
          >
            {analise.sinais.length === 0 ? (
              <EmptyState>
                Sem sinais de regra. Vale a pena ver os contratos atípicos no CPV (coluna «σ no CPV») e comparar com as réguas do setor.
              </EmptyState>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Sinal</th>
                      <th className="py-2 pr-3">Severidade</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 pr-3 text-right">Taxa</th>
                      <th className="py-2">Exemplo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analise.sinais.map((sinal) => (
                      <tr key={sinal.padrao} className="border-t border-white/5 align-top">
                        <td className="w-[280px] py-2 pr-3 text-xs">
                          <button
                            onClick={() => setPadraoFiltro(sinal.padrao)}
                            className="text-left text-teal-200 transition hover:text-teal-100"
                            title={sinal.descricao ?? undefined}
                          >
                            {sinal.label ?? padraoLabel(sinal.padrao)}
                          </button>
                          <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{sinal.padrao}</div>
                        </td>
                        <td className="w-[110px] py-2 pr-3">
                          <Chip tone={padraoTone(sinal.padrao)}>{sinal.severidade ?? "—"}</Chip>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(sinal.contratos)}</td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(sinal.taxa)}</td>
                        <td className="w-[380px] py-2 text-xs text-muted-foreground">
                          {sinal.exemplos?.[0] ? (
                            <button
                              onClick={() => setContratoQuery(sinal.exemplos[0].objeto ?? "")}
                              className="block max-w-[360px] truncate text-left transition hover:text-foreground"
                              title={sinal.exemplos[0].objeto ?? undefined}
                            >
                              {sinal.exemplos[0].ano ? `${sinal.exemplos[0].ano} · ` : ""}
                              {sinal.exemplos[0].objeto}
                            </button>
                          ) : (
                            "—"
                          )}
                          {sinal.exemplos?.[0]?.detalhe && (
                            <div className="mt-0.5 text-[11px] text-amber-200/80">{sinal.exemplos[0].detalhe}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {/* ------------------------------------------------- perfil e relações */}
          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <SectionCard icon={Coins} title="Perfil do portefólio" subtitle="Contratos e valor por ano; CPV, procedimento e adjudicantes no detalhe abaixo.">
              {graficoAnos.length === 0 ? (
                <EmptyState>Sem datas de publicação para distribuir por ano.</EmptyState>
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={graficoAnos} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                      <XAxis dataKey="ano" tick={{ fontSize: 11, fill: "rgba(255,255,255,0.55)" }} />
                      <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "rgba(255,255,255,0.55)" }} />
                      <Tooltip
                        contentStyle={{ background: "#0b1220", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 12 }}
                        formatter={(value) => [formatCompactEuro(Number(value ?? 0)), "Valor adjudicado"]}
                      />
                      <Bar yAxisId="left" dataKey="valor" radius={[6, 6, 0, 0]}>
                        {graficoAnos.map((_, indice) => (
                          <Cell key={indice} fill={BAR_COLORS[indice % BAR_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Coins size={13} /> Escalões de valor
                  </h3>
                  <ul className="space-y-1 text-xs">
                    {Object.entries(resumo?.escaloes ?? {}).map(([faixa, quantidade]) => (
                      <li key={faixa} className="flex items-center justify-between">
                        <span className="text-muted-foreground">{faixa}</span>
                        <span className="font-mono">{formatNumber(quantidade)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/5 p-3">
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Gavel size={13} /> Procedimentos
                  </h3>
                  <ul className="space-y-1 text-xs">
                    {(analise.por_procedimento ?? []).slice(0, 5).map((item) => (
                      <li key={item.procedimento} className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-muted-foreground" title={item.procedimento}>
                          {item.procedimento}
                        </span>
                        <span className="shrink-0 font-mono">
                          {formatNumber(item.contratos)} · {formatCompactEuro(item.valor)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </SectionCard>

            <SectionCard
              icon={Network}
              title="Relações"
              subtitle="Pares no mesmo adjudicante, gerentes, insolvências e menções públicas."
            >
              <div className="flex flex-col gap-4">
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Building2 size={13} /> Também vencem aos mesmos adjudicantes
                  </h3>
                  {(analise.relacoes?.empresas ?? []).length === 0 ? (
                    <p className="text-xs text-muted-foreground">Sem pares identificados nos adjudicantes principais.</p>
                  ) : (
                    <ul className="max-h-52 space-y-1 overflow-y-auto pr-1 text-xs">
                      {(analise.relacoes?.empresas ?? []).slice(0, 20).map((par) => (
                        <li key={`${par.nif}-${par.adjudicante ?? ""}`} className="flex items-center justify-between gap-2">
                          <button
                            onClick={() => void analisar({ nif: par.nif })}
                            className="min-w-0 truncate text-left text-teal-200 transition hover:text-teal-100"
                            title={`Analisar ${par.nome ?? par.nif}`}
                          >
                            {par.nome ?? par.nif}
                          </button>
                          <span className="shrink-0 font-mono text-muted-foreground">
                            {formatNumber(par.contratos)} · {formatCompactEuro(par.valor)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Users size={13} /> Órgãos sociais
                  </h3>
                  {(analise.relacoes?.cargos_sociais ?? []).length === 0 ? (
                    <p className="text-xs text-muted-foreground">Sem cargos de gerência publicados para este NIF.</p>
                  ) : (
                    <ul className="max-h-40 space-y-1 overflow-y-auto pr-1 text-xs">
                      {(analise.relacoes?.cargos_sociais ?? []).slice(0, 15).map((pessoa) => (
                        <li key={pessoa.nif ?? pessoa.nome} className="flex items-start justify-between gap-2">
                          <span className="min-w-0 truncate">{pessoa.nome}</span>
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {(pessoa.cargos ?? [])
                              .slice(0, 2)
                              .map((cargo) => cargo.role_org ?? cargo.role)
                              .filter(Boolean)
                              .join(", ")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {(analise.relacoes?.insolvencias ?? []).length > 0 && (
                  <div>
                    <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-rose-200">
                      <ShieldAlert size={13} /> Insolvências (CIRE)
                    </h3>
                    <ul className="space-y-1 text-xs">
                      {(analise.relacoes?.insolvencias ?? []).map((item) => (
                        <li key={`${item.processo}-${item.data}`} className="text-muted-foreground">
                          <span className="text-rose-200">{item.especie ?? "processo"}</span> · {formatDate(item.data)}
                          {item.tribunal ? ` · ${item.tribunal}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Newspaper size={13} /> Menções em notícias
                  </h3>
                  {(analise.relacoes?.noticias ?? []).length === 0 ? (
                    <p className="text-xs text-muted-foreground">Sem menções recentes nas fontes recolhidas (RSS, recolha e redes sociais).</p>
                  ) : (
                    <ul className="max-h-44 space-y-1.5 overflow-y-auto pr-1 text-xs">
                      {(analise.relacoes?.noticias ?? []).slice(0, 12).map((noticia) => (
                        <li key={noticia.url ?? noticia.titulo}>
                          <a
                            href={noticia.url ?? "#"}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-start gap-1.5 text-teal-200 transition hover:text-teal-100"
                          >
                            <ExternalLink size={11} className="mt-0.5 shrink-0" />
                            <span className="line-clamp-2">{noticia.titulo}</span>
                          </a>
                          <div className="mt-0.5 pl-4 text-[10px] text-muted-foreground">
                            {noticia.fonte ?? noticia.canal} · {formatDate(noticia.data)}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </SectionCard>
          </div>

          {/* --------------------------------------------------- CPV e adjudicantes */}
          <div className="grid gap-5 xl:grid-cols-2">
            <SectionCard
              icon={Scale}
              title="Onde atua (por CPV)"
              subtitle="Comparação com a régua do setor: ajuste direto e aditivos do CPV no total nacional."
            >
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">CPV</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 pr-3 text-right">Valor</th>
                      <th className="py-2 pr-3 text-right">Empresa · ajuste</th>
                      <th className="py-2 pr-3 text-right">Setor · ajuste</th>
                      <th className="py-2 text-right">Aditivos</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(analise.por_cpv ?? []).map((linha) => {
                      const regua = (analise.reguas_cpv ?? []).find((item) => item.cpv === linha.cpv);
                      const desvio = regua?.taxa_ajuste_direto != null && linha.taxa_ajuste_direto != null && regua.taxa_ajuste_direto > 0
                        ? linha.taxa_ajuste_direto / regua.taxa_ajuste_direto
                        : null;
                      return (
                        <tr key={linha.cpv} className="border-t border-white/5 align-top">
                          <td className="w-[240px] py-2 pr-3 text-xs">
                            <div className="truncate" title={linha.descricao ?? undefined}>
                              {linha.descricao ?? `CPV ${linha.cpv}`}
                            </div>
                            <div className="font-mono text-[10px] text-muted-foreground">
                              {linha.cpv}
                              {regua ? ` · ${formatNumber(regua.contratos)} pares` : ""}
                            </div>
                          </td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.contratos)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(linha.valor)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(linha.taxa_ajuste_direto)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs text-muted-foreground">
                            {formatPct(regua?.taxa_ajuste_direto ?? null)}
                            {desvio != null && desvio >= 2 && (
                              <Chip tone="amber" title="Muito acima da taxa do setor">
                                ×{desvio.toFixed(1)}
                              </Chip>
                            )}
                          </td>
                          <td className="whitespace-nowrap py-2 text-right text-xs">
                            {formatNumber(linha.aditivos)}
                            <div className="text-[10px] text-muted-foreground">{formatPct(linha.taxa_aditivo)}</div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard icon={Landmark} title="A quem vende" subtitle="Os adjudicantes onde está mais valor concentrado.">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Adjudicante</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 pr-3 text-right">Valor</th>
                      <th className="py-2 text-right">Parte do valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(analise.adjudicantes ?? []).map((item) => {
                      const parte = resumo?.valor_total ? (item.valor ?? 0) / resumo.valor_total : null;
                      return (
                        <tr key={item.nif ?? item.nome} className="border-t border-white/5">
                          <td className="w-[280px] py-2 pr-3 text-xs">
                            <div className="truncate" title={item.nome ?? undefined}>
                              {item.nome ?? item.nif}
                            </div>
                            <div className="font-mono text-[10px] text-muted-foreground">{item.nif}</div>
                          </td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(item.contratos)}</td>
                          <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(item.valor)}</td>
                          <td className="whitespace-nowrap py-2 text-right text-xs">{formatPct(parte)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </div>

          {/* ---------------------------------------------------------- contratos */}
          <SectionCard
            icon={FileSearch}
            title="Contratos da empresa"
            subtitle={analise.aviso}
            actions={
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-muted-foreground">
                  {contratos.length > LINHAS_TABELA
                    ? `a mostrar ${formatNumber(LINHAS_TABELA)} de ${formatNumber(contratos.length)} filtrados`
                    : `${formatNumber(contratos.length)} de ${formatNumber(analise.contratos_analisados)}`}
                </span>
              </div>
            }
          >
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <FilterField label="Pesquisar" className="sm:col-span-2">
                <SearchInput value={contratoQuery} onChange={setContratoQuery} placeholder="objeto, adjudicante ou CPV" />
              </FilterField>
              <FilterField label="Padrão">
                <select value={padraoFiltro} onChange={(e) => setPadraoFiltro(e.target.value)} className={SELECT_CLASS}>
                  <option value="">todos</option>
                  {padroesPresentes.map((padrao) => (
                    <option key={padrao} value={padrao}>
                      {padraoLabel(padrao)}
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField label="Ordenar por">
                <select value={ordem} onChange={(e) => setOrdem(e.target.value as OrdemContratos)} className={SELECT_CLASS}>
                  <option value="severidade">severidade</option>
                  <option value="valor">valor</option>
                  <option value="desvio">σ no CPV</option>
                  <option value="ano">ano</option>
                </select>
              </FilterField>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <button
                onClick={() => setSoSinalizados((valor) => !valor)}
                className={`flex items-center gap-1.5 rounded-lg px-2 py-1 transition ${
                  soSinalizados ? "border border-amber-400/25 bg-amber-400/15 text-amber-200" : "border border-white/10 text-muted-foreground"
                }`}
              >
                <AlertTriangle size={13} /> só com sinais
              </button>
              {(contratoQuery || padraoFiltro || soSinalizados) && (
                <button
                  onClick={() => {
                    setContratoQuery("");
                    setPadraoFiltro("");
                    setSoSinalizados(false);
                  }}
                  className="rounded-lg border border-white/10 px-2 py-1 text-muted-foreground transition hover:text-foreground"
                >
                  limpar filtros
                </button>
              )}
            </div>

            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
                <thead>
                  <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Contrato</th>
                    <th className="py-2 pr-3 text-right">Valor</th>
                    <th className="py-2 pr-3 text-right">Base</th>
                    <th className="py-2 pr-3 text-right">Efetivo</th>
                    <th className="py-2 pr-3 text-right">σ no CPV</th>
                    <th className="py-2 pr-3 text-right">Concorrentes</th>
                    <th className="py-2">Sinais</th>
                  </tr>
                </thead>
                <tbody>
                  {contratos.slice(0, LINHAS_TABELA).map((contrato: PadroesEmpresaContrato) => (
                    <tr key={contrato.id} className="border-t border-white/5 align-top">
                      <td className="w-[360px] py-2 pr-3 text-xs">
                        <div className="line-clamp-2" title={contrato.objeto ?? undefined}>
                          {contrato.objeto ?? contrato.id}
                        </div>
                        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                          {contrato.ano ?? "—"} · {contrato.data_publicacao ?? "sem data"} · {contrato.cpv ?? "—"}
                        </div>
                        <div className="mt-0.5 truncate text-[10px] text-muted-foreground" title={contrato.adjudicante ?? undefined}>
                          {contrato.adjudicante ?? contrato.adjudicante_nif ?? "—"} · {contrato.procedimento ?? "—"}
                        </div>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(contrato.valor)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs text-muted-foreground">{formatRatio(contrato.ratio_base)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                        {formatRatio(contrato.ratio_efetivo)}
                        {(contrato.ratio_efetivo ?? 0) > 1.15 && <Chip tone="rose">aditivo</Chip>}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                        {(contrato.z_cpv ?? 0) > 0 ? `σ ${(contrato.z_cpv ?? 0).toFixed(1)}` : "—"}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(contrato.n_concorrentes)}</td>
                      <td className="w-[300px] py-2 text-xs">
                        {(contrato.razoes ?? []).length === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <div className="flex max-w-[290px] flex-wrap gap-1">
                            {(contrato.razoes ?? []).map((razao) => (
                              <Chip key={razao.padrao} tone={padraoTone(razao.padrao)} title={razao.detalhe}>
                                {padraoLabel(razao.padrao)}
                              </Chip>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {contratos.length === 0 && (
                <div className="mt-3">
                  <EmptyState tone="warn">Nenhum contrato corresponde aos filtros aplicados.</EmptyState>
                </div>
              )}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

export default PadroesEmpresa;
