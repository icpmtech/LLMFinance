/**
 * Página **Comparar empresas** do módulo de deteção de padrões.
 *
 * Responde a três perguntas que só fazem sentido com várias empresas à frente:
 *
 * 1. **Como se comparam?** — contratos, valor, desvio do preço base, ajuste
 *    direto, aditivos, concentração e sinais, lado a lado e ordenáveis;
 * 2. **Como se cruzam?** — adjudicantes comuns (concorrem no mesmo cliente),
 *    pessoas comuns (o mesmo gerente), processos do CIRE partilhados e CPV
 *    comuns (o mesmo mercado);
 * 3. **Como é a rede?** — um grafo com as empresas ao centro e, à volta, o
 *    comprador, o mercado e o processo que as liga.
 *
 * O grafo é desenhado **a pedido** (corre no browser e é o passo mais caro):
 * os números da comparação estão prontos antes de qualquer desenho.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Coins,
  FileSpreadsheet,
  FileText,
  Landmark,
  Layers,
  Loader2,
  Network,
  Plus,
  Scale,
  Search,
  ShieldAlert,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compararPadroesEmpresas, exportPadroesEmpresasRelatorio, guardarFicheiroPadroes, sugerirPadroesEmpresas } from "../../padroesApi";
import type { PadroesCruzamento, PadroesEmpresaLinha, PadroesEmpresaSugestao, PadroesEmpresasConjunto, PadroesRelatorioFormato } from "../../padroesApi";
import { GraphCanvas } from "../graph/GraphCanvas";
import { toStudioGraph } from "../graph/graphStudio";
import type { GraphMetric, StudioNode } from "../graph/graphStudio";
import { Chip, EmptyState, FilterField, Kpi, Loading, SectionCard, formatCompactEuro, formatNumber, formatPct, formatRatio, padraoLabel, padraoTone } from "./padroesKit";

const SELECT_CLASS =
  "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground";
const BAR_COLORS = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#f472b6", "#4ade80", "#60a5fa"];

/** Máximo de empresas por comparação (o backend tem o mesmo teto). */
const MAX_EMPRESAS = 12;

type OrdemConjunto = "valor" | "sinais" | "ajuste" | "nome";

export function PadroesEmpresasComparar({ pais, onDossie }: { pais: string; onDossie?: (nif?: string | null) => void }) {
  const [escolhidas, setEscolhidas] = useState<PadroesEmpresaSugestao[]>([]);
  const [texto, setTexto] = useState("");
  const [sugestoes, setSugestoes] = useState<PadroesEmpresaSugestao[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const [aberto, setAberto] = useState(false);
  const [anoFrom, setAnoFrom] = useState("");
  const [anoTo, setAnoTo] = useState("");
  const [maxContratos, setMaxContratos] = useState(120);
  const [conjunto, setConjunto] = useState<PadroesEmpresasConjunto | null>(null);
  const [aComparar, setAComparar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ordem, setOrdem] = useState<OrdemConjunto>("valor");
  const [mostrarRede, setMostrarRede] = useState(false);
  const [layout, setLayout] = useState<"hierarchical" | "circular" | "network">("hierarchical");
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [metric, setMetric] = useState<GraphMetric>("valor");
  const caixa = useRef<HTMLDivElement | null>(null);

  const nifs = useMemo(() => escolhidas.map((empresa) => empresa.nif).filter(Boolean) as string[], [escolhidas]);

  // Sugestões (evita um pedido por tecla).
  useEffect(() => {
    const termo = texto.trim();
    if (termo.length < 3) {
      setSugestoes([]);
      return;
    }
    let ativo = true;
    const timer = window.setTimeout(() => {
      setAProcurar(true);
      sugerirPadroesEmpresas(termo, { pais, limit: 8 })
        .then((resposta) => {
          if (!ativo) return;
          setSugestoes((resposta.items ?? []).filter((item) => !nifs.includes(item.nif)));
          setAberto(true);
        })
        .catch(() => ativo && setSugestoes([]))
        .finally(() => ativo && setAProcurar(false));
    }, 320);
    return () => {
      ativo = false;
      window.clearTimeout(timer);
    };
  }, [texto, pais, nifs]);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (caixa.current && !caixa.current.contains(event.target as Node)) setAberto(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const acrescentar = useCallback((item: PadroesEmpresaSugestao) => {
    setEscolhidas((lista) => (lista.some((empresa) => empresa.nif === item.nif) || lista.length >= MAX_EMPRESAS ? lista : [...lista, item]));
    setTexto("");
    setSugestoes([]);
    setAberto(false);
  }, []);

  const remover = useCallback((nif: string) => {
    setEscolhidas((lista) => lista.filter((empresa) => empresa.nif !== nif));
  }, []);

  const comparar = useCallback(async () => {
    if (escolhidas.length < 2) {
      setErro("Escolha pelo menos duas empresas para comparar.");
      return;
    }
    setAComparar(true);
    setErro(null);
    setConjunto(null);
    setMostrarRede(false);
    try {
      const dados = await compararPadroesEmpresas({
        nifs,
        pais,
        ano_from: anoFrom ? Number(anoFrom) : null,
        ano_to: anoTo ? Number(anoTo) : null,
        max_contratos: maxContratos,
        max_empresas: MAX_EMPRESAS,
      });
      if (dados.error) {
        setErro(dados.error);
        return;
      }
      setConjunto(dados);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro na comparação");
    } finally {
      setAComparar(false);
    }
  }, [anoFrom, anoTo, escolhidas.length, maxContratos, nifs, pais]);

  const descarregar = useCallback(
    async (formato: PadroesRelatorioFormato) => {
      setErro(null);
      try {
        const resposta = await exportPadroesEmpresasRelatorio(
          { nifs, pais, ano_from: anoFrom ? Number(anoFrom) : null, ano_to: anoTo ? Number(anoTo) : null, max_contratos: maxContratos, max_empresas: MAX_EMPRESAS },
          formato,
        );
        guardarFicheiroPadroes(resposta.blob, resposta.filename);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao gerar o relatório");
      }
    },
    [anoFrom, anoTo, maxContratos, nifs, pais],
  );

  const linhas = useMemo(() => {
    const itens = [...(conjunto?.empresas ?? [])];
    itens.sort((a, b) => {
      if (ordem === "sinais") return (b.resumo.contratos_com_sinais ?? 0) - (a.resumo.contratos_com_sinais ?? 0);
      if (ordem === "ajuste") return (b.resumo.taxa_ajuste_direto ?? 0) - (a.resumo.taxa_ajuste_direto ?? 0);
      if (ordem === "nome") return String(a.nome ?? a.nif).localeCompare(String(b.nome ?? b.nif), "pt");
      return (b.resumo.valor_total ?? 0) - (a.resumo.valor_total ?? 0);
    });
    return itens;
  }, [conjunto, ordem]);

  const grafico = useMemo(
    () =>
      (conjunto?.empresas ?? []).map((empresa, indice) => ({
        nome: String(empresa.nome ?? empresa.nif).slice(0, 26),
        valor: empresa.resumo.valor_total ?? 0,
        ajuste: Number(((empresa.resumo.taxa_ajuste_direto ?? 0) * 100).toFixed(1)),
        cor: BAR_COLORS[indice % BAR_COLORS.length],
      })),
    [conjunto],
  );

  const grafo = useMemo(
    () => (conjunto?.grafo ? toStudioGraph(conjunto.grafo, metric) : null),
    [conjunto, metric],
  );
  const resumoNo = useCallback(
    (node: StudioNode) =>
      `${node.label} · ${node.role ?? ""}${node.count ? ` · ${formatNumber(node.count)}` : ""}${
        node.total_value ? ` · ${formatCompactEuro(node.total_value)}` : ""
      }`,
    [],
  );

  const totais = conjunto?.totais;
  const cruzamentos = conjunto?.cruzamentos;

  return (
    <div className="flex flex-col gap-5">
      {/* ------------------------------------------------------- escolha */}
      <SectionCard
        icon={Layers}
        title="Comparar empresas"
        subtitle="Escolha duas ou mais empresas (nome, marca ou NIF) para comparar contratos, portefólio e rede."
        actions={
          conjunto ? (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {(["pdf", "xlsx", "csv"] as const).map((formato, indice) => {
                const Icone = indice === 1 ? FileSpreadsheet : FileText;
                return (
                  <button
                    key={formato}
                    onClick={() => void descarregar(formato)}
                    className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-teal-200 transition hover:text-teal-100"
                  >
                    <Icone size={13} /> {formato === "xlsx" ? "Excel" : formato.toUpperCase()}
                  </button>
                );
              })}
            </div>
          ) : undefined
        }
      >
        <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,0.6fr))]">
          <div className="relative" ref={caixa}>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2.5">
              {aProcurar ? <Loader2 size={15} className="shrink-0 animate-spin text-teal-300" /> : <Search size={15} className="shrink-0 text-muted-foreground" />}
              <input
                value={texto}
                onChange={(event) => setTexto(event.target.value)}
                onFocus={() => setAberto(sugestoes.length > 0)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && sugestoes[0]) acrescentar(sugestoes[0]);
                }}
                placeholder="ex.: cimontubo · mota-engil · 503439800"
                className="w-full bg-transparent text-sm normal-case tracking-normal text-foreground outline-none placeholder:text-muted-foreground/60"
              />
              {texto && (
                <button onClick={() => setTexto("")} className="shrink-0 text-muted-foreground hover:text-foreground">
                  <X size={13} />
                </button>
              )}
            </div>
            {aberto && sugestoes.length > 0 && (
              <ul className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-white/10 bg-[#0b1220]/95 p-1 shadow-xl backdrop-blur">
                {sugestoes.map((item) => (
                  <li key={item.nif}>
                    <button
                      onClick={() => acrescentar(item)}
                      className="flex w-full items-start justify-between gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-white/10"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-foreground">{item.nome ?? item.nif}</span>
                        <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                          {item.nif}
                          {item.concelho ? ` · ${item.concelho}` : ""}
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
          <FilterField label="Contratos por empresa">
            <select value={maxContratos} onChange={(e) => setMaxContratos(Number(e.target.value))} className={SELECT_CLASS}>
              {[60, 120, 200, 300].map((valor) => (
                <option key={valor} value={valor}>
                  {valor}
                </option>
              ))}
            </select>
          </FilterField>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {escolhidas.map((empresa) => (
            <span key={empresa.nif} className="flex items-center gap-2 rounded-full border border-teal-400/25 bg-teal-400/10 px-2.5 py-1 text-xs text-teal-100">
              <Building2 size={12} />
              {empresa.nome ?? empresa.nif}
              <button onClick={() => remover(empresa.nif)} className="text-teal-200/70 transition hover:text-teal-100" title="Retirar">
                <X size={12} />
              </button>
            </span>
          ))}
          {escolhidas.length === 0 && <span className="text-xs text-muted-foreground">Ainda não escolheu empresas.</span>}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <button
            onClick={() => void comparar()}
            disabled={aComparar || escolhidas.length < 2}
            className="flex items-center gap-1.5 rounded-lg border border-teal-400/25 bg-teal-400/10 px-3 py-1.5 text-teal-100 transition hover:bg-teal-400/20 disabled:opacity-40"
          >
            {aComparar ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            comparar {escolhidas.length >= 2 ? `${escolhidas.length} empresas` : ""}
          </button>
          <span className="text-muted-foreground">
            até {MAX_EMPRESAS} empresas · cada uma com {formatNumber(maxContratos)} contratos analisados
          </span>
        </div>

        {erro && (
          <div className="mt-3">
            <EmptyState tone="warn">{erro}</EmptyState>
          </div>
        )}
        {aComparar && (
          <div className="mt-3">
            <Loading label="A analisar cada empresa e a cruzar adjudicantes, gerentes e processos…" />
          </div>
        )}
        {!conjunto && !aComparar && !erro && (
          <div className="mt-3">
            <EmptyState>
              Escolha as empresas e clique em comparar. O resultado traz a comparação lado a lado, o que se cruza entre elas
              (comprador, gerente, processo e mercado) e a rede do conjunto.
            </EmptyState>
          </div>
        )}
      </SectionCard>

      {conjunto && (
        <>
          {/* -------------------------------------------------------- KPIs */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi icon={Building2} label="Empresas comparadas" value={formatNumber(totais?.empresas)} sub={`de ${formatNumber(totais?.empresas_pedidas)} pedidas`} />
            <Kpi icon={Coins} label="Valor adjudicado (soma)" value={formatCompactEuro(totais?.valor_total)} sub={`mediana ${formatCompactEuro(totais?.valor_mediano)}`} color="text-amber-300" glow="glow-amber" />
            <Kpi icon={FileText} label="Contratos analisados" value={formatNumber(totais?.contratos)} sub={`de ${formatNumber(totais?.contratos_total_portal)} registados`} color="text-sky-300" glow="glow-blue" />
            <Kpi
              icon={ShieldAlert}
              label="Insolventes no conjunto"
              value={formatNumber(totais?.insolventes)}
              sub={`${formatNumber(totais?.com_sinais)} com sinais`}
              color={totais?.insolventes ? "text-rose-300" : "text-teal-300"}
              glow={totais?.insolventes ? "glow-rose" : "glow-teal"}
            />
          </div>

          {(conjunto.avisos ?? []).length > 0 && (
            <EmptyState tone="warn">
              Empresas ignoradas: {(conjunto.avisos ?? []).join(" · ")}
            </EmptyState>
          )}

          {/* --------------------------------------------- comparação */}
          <SectionCard
            icon={Scale}
            title="Comparação lado a lado"
            subtitle="Contratos, valor, desvio do preço base, ajuste direto, aditivos, concentração e sinais."
            actions={
              <FilterField label="Ordenar por">
                <select value={ordem} onChange={(e) => setOrdem(e.target.value as OrdemConjunto)} className={SELECT_CLASS}>
                  <option value="valor">Valor</option>
                  <option value="sinais">Contratos com sinais</option>
                  <option value="ajuste">Ajuste direto</option>
                  <option value="nome">Nome</option>
                </select>
              </FilterField>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
                <thead>
                  <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Empresa</th>
                    <th className="py-2 pr-3 text-right">Contratos</th>
                    <th className="py-2 pr-3 text-right">Valor</th>
                    <th className="py-2 pr-3 text-right">Valor mediano</th>
                    <th className="py-2 pr-3 text-right">Desvio</th>
                    <th className="py-2 pr-3 text-right">Ajuste direto</th>
                    <th className="py-2 pr-3 text-right">Aditivos</th>
                    <th className="py-2 pr-3 text-right">Adjudicantes</th>
                    <th className="py-2 pr-3 text-right">Concentração</th>
                    <th className="py-2 pr-3 text-right">Com sinais</th>
                    <th className="py-2">Sinais</th>
                  </tr>
                </thead>
                <tbody>
                  {linhas.map((linha: PadroesEmpresaLinha) => (
                    <tr key={linha.nif} className="border-t border-white/5 align-top">
                      <td className="w-[260px] py-2 pr-3 text-xs">
                        <button
                          onClick={() => onDossie?.(linha.nif)}
                          className="block max-w-[240px] truncate text-left text-teal-200 transition hover:text-teal-100"
                          title={`Abrir o dossiê de ${linha.nome ?? linha.nif}`}
                        >
                          {linha.nome ?? linha.nif}
                        </button>
                        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                          {linha.nif}
                          {linha.anos ? ` · ${linha.anos[0]}–${linha.anos[1]}` : ""}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {linha.resumo.insolvente && (
                            <Chip tone="rose">
                              <ShieldAlert size={11} /> insolvência
                            </Chip>
                          )}
                          {linha.severidade && linha.severidade !== "info" && (
                            <Chip tone={linha.severidade === "alerta" ? "rose" : "amber"}>{linha.severidade}</Chip>
                          )}
                        </div>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.resumo.contratos)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(linha.resumo.valor_total)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs text-muted-foreground">{formatCompactEuro(linha.resumo.valor_mediano)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatRatio(linha.resumo.desvio_mediano)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(linha.resumo.taxa_ajuste_direto)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(linha.resumo.taxa_aditivo)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(linha.resumo.adjudicantes_distintos)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatPct(linha.resumo.concentracao_adjudicante)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                        {formatNumber(linha.resumo.contratos_com_sinais)}
                        <div className="text-[10px] text-muted-foreground">{formatNumber(linha.resumo.contratos_atipicos_cpv)} atípicos</div>
                      </td>
                      <td className="w-[260px] py-2">
                        <div className="flex max-w-[250px] flex-wrap gap-1">
                          {(linha.sinais ?? []).length === 0 ? (
                            <span className="text-[11px] text-muted-foreground">—</span>
                          ) : (
                            (linha.sinais ?? []).slice(0, 5).map((sinal) => (
                              <Chip key={sinal.padrao} tone={padraoTone(sinal.padrao)} title={sinal.exemplos?.[0]?.detalhe ?? undefined}>
                                {sinal.label ?? padraoLabel(sinal.padrao)} · {formatNumber(sinal.contratos)}
                              </Chip>
                            ))
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          {/* -------------------------------------------------------- gráfico */}
          <SectionCard icon={Coins} title="Valor adjudicado vs ajuste direto" subtitle="Onde está o dinheiro e onde é que ele é decidido sem concurso.">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={grafico} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="nome" tick={{ fontSize: 10, fill: "rgba(255,255,255,0.55)" }} interval={0} angle={-12} textAnchor="end" height={54} />
                  <YAxis tick={{ fontSize: 10, fill: "rgba(255,255,255,0.55)" }} />
                  <Tooltip
                    contentStyle={{ background: "#0b1220", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, fontSize: 12 }}
                    formatter={(valor) => [formatCompactEuro(Number(valor ?? 0)), "Valor adjudicado"]}
                  />
                  <Bar dataKey="valor" radius={[6, 6, 0, 0]}>
                    {grafico.map((item) => (
                      <Cell key={item.nome} fill={item.cor} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
              {grafico.map((item) => (
                <Chip key={item.nome} title={`ajuste direto ${item.ajuste}%`}>
                  {item.nome}: {item.ajuste}% ajuste direto
                </Chip>
              ))}
            </div>
          </SectionCard>

          {/* ---------------------------------------------------- cruzamentos */}
          <div className="grid gap-5 xl:grid-cols-2">
            <SectionCard
              icon={Landmark}
              title="Adjudicantes comuns"
              subtitle="As empresas vendem ao mesmo comprador — concorrência no mesmo cliente (não é, por si, ilícito)."
            >
              <TabelaCruzamento
                vazio="Nenhum adjudicante aparece em duas empresas desta amostra."
                itens={cruzamentos?.adjudicantes ?? []}
                colunas={["Adjudicante", "Empresas", "Contratos", "Valor"]}
                linha={(item) => [
                  <span className="block truncate" title={item.nome ?? undefined}>
                    {item.nome ?? item.nif}
                  </span>,
                  <span className="block truncate text-muted-foreground" title={(item.empresas_nome ?? []).join(" · ")}>
                    {item.empresas_nome?.join(" · ")}
                  </span>,
                  formatNumber(item.contratos),
                  formatCompactEuro(item.valor),
                ]}
                onDossie={onDossie}
                nifDe={(item) => item.nif}
              />
            </SectionCard>

            <SectionCard
              icon={Users}
              title="Pessoas comuns"
              subtitle="O mesmo gerente com cargo de órgão social em duas empresas — ligação societária."
            >
              <TabelaCruzamento
                vazio="Sem pessoas com cargos em duas empresas desta amostra."
                itens={cruzamentos?.pessoas ?? []}
                colunas={["Pessoa", "Cargos", "Empresas"]}
                linha={(item) => [
                  <span className="block truncate">{item.nome ?? item.nif}</span>,
                  <span className="block truncate text-muted-foreground">{(item.cargos ?? []).join(", ") || "—"}</span>,
                  <span className="block truncate text-muted-foreground" title={(item.empresas_nome ?? []).join(" · ")}>
                    {item.empresas_nome?.join(" · ")}
                  </span>,
                ]}
              />
            </SectionCard>

            <SectionCard icon={ShieldAlert} title="Processos do CIRE partilhados" subtitle="Empresas do conjunto que aparecem no mesmo processo de insolvência.">
              <TabelaCruzamento
                vazio="Sem processos de insolvência partilhados nesta amostra."
                itens={cruzamentos?.processos ?? []}
                colunas={["Processo", "Espécie", "Empresas"]}
                linha={(item) => [
                  <span className="block font-mono text-[11px]">{item.processo ?? "—"}</span>,
                  <span className="block truncate text-muted-foreground">{item.especie ?? "—"}</span>,
                  <span className="block truncate text-muted-foreground" title={(item.empresas_nome ?? []).join(" · ")}>
                    {item.empresas_nome?.join(" · ")}
                  </span>,
                ]}
              />
            </SectionCard>

            <SectionCard icon={Layers} title="CPV comuns" subtitle="O mesmo mercado: classificação em que as empresas coincidem.">
              <TabelaCruzamento
                vazio="Sem CPV coincidentes nesta amostra."
                itens={cruzamentos?.cpvs ?? []}
                colunas={["CPV", "Descrição", "Empresas", "Contratos", "Valor"]}
                linha={(item) => [
                  <span className="font-mono text-[11px]">{item.cpv}</span>,
                  <span className="block truncate" title={item.descricao ?? undefined}>
                    {item.descricao ?? "—"}
                  </span>,
                  formatNumber(item.n_empresas),
                  formatNumber(item.contratos),
                  formatCompactEuro(item.valor),
                ]}
              />
            </SectionCard>
          </div>

          {/* ------------------------------------------------------- rede */}
          <SectionCard
            icon={Network}
            title="Rede das empresas comparadas"
            subtitle="Empresas ao centro, ligadas pelo comprador, pelo mercado (CPV), pelo gerente e pelo processo."
            actions={
              <div className="flex flex-wrap items-center gap-1 text-xs">
                {mostrarRede && (
                  <>
                    {(["hierarchical", "circular", "network"] as const).map((opcao) => (
                      <button
                        key={opcao}
                        onClick={() => {
                          setLayout(opcao);
                          setLayoutVersion((valor) => valor + 1);
                        }}
                        className={`rounded-lg px-2 py-1 transition ${layout === opcao ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground hover:text-foreground"}`}
                      >
                        {opcao === "network" ? "rede" : opcao === "hierarchical" ? "hierárquico" : "circular"}
                      </button>
                    ))}
                    <span className="mx-1 text-white/10">|</span>
                    {(["valor", "contratos"] as const).map((opcao) => (
                      <button
                        key={opcao}
                        onClick={() => setMetric(opcao)}
                        className={`rounded-lg px-2 py-1 transition ${metric === opcao ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground hover:text-foreground"}`}
                      >
                        {opcao}
                      </button>
                    ))}
                    <span className="mx-1 text-white/10">|</span>
                  </>
                )}
                <button
                  onClick={() => setMostrarRede((valor) => !valor)}
                  className={`rounded-lg border px-2 py-1 transition ${
                    mostrarRede ? "border-white/10 text-muted-foreground hover:text-foreground" : "border-teal-400/30 bg-teal-400/10 text-teal-100"
                  }`}
                >
                  {mostrarRede ? "ocultar rede" : "desenhar rede"}
                </button>
              </div>
            }
          >
            {!mostrarRede ? (
              <p className="text-xs text-muted-foreground">
                {grafo
                  ? `${formatNumber(grafo.nodes.length)} nós e ${formatNumber(grafo.edges.length)} ligações prontos a desenhar · ` +
                    `${formatNumber((conjunto.grafo?.nodes ?? []).filter((no) => no.dimension === "adjudicante").length)} compradores · ` +
                    `${formatNumber((conjunto.grafo?.nodes ?? []).filter((no) => no.type === "pessoa").length)} pessoas · ` +
                    `${formatNumber((conjunto.grafo?.nodes ?? []).filter((no) => no.type === "cpv").length)} mercados.`
                  : "Sem rede para desenhar."}
                {" "}O desenho corre no browser, por isso só é feito quando o pedir.
              </p>
            ) : grafo && grafo.nodes.length > 1 ? (
              <>
                <GraphCanvas graph={grafo} layout={layout} metric={metric} layoutVersion={layoutVersion} heightClass="h-[460px]" nodeSummary={resumoNo} />
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Verde = entidades (empresas comparadas e compradores) · lilás = mercado (CPV partilhado) · rosa = pessoas · azul =
                  processos do CIRE. Só aparecem compradores, pessoas, processos e mercados que tocam **duas ou mais** empresas do
                  conjunto (mais os maiores compradores de cada uma, para dar contexto).
                </p>
              </>
            ) : (
              <EmptyState>Sem ligações entre estas empresas na amostra analisada.</EmptyState>
            )}
          </SectionCard>

          {/* -------------------------------------------------------- CPV */}
          {(conjunto.por_cpv ?? []).length > 0 && (
            <SectionCard icon={Sparkles} title="Distribuição por CPV (conjunto)" subtitle="Onde está concentrado o valor das empresas comparadas.">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">CPV</th>
                      <th className="py-2 pr-3 text-right">Empresas</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 text-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(conjunto.por_cpv ?? []).map((item) => (
                      <tr key={item.cpv} className="border-t border-white/5">
                        <td className="w-[380px] py-2 pr-3 text-xs">
                          <div className="truncate" title={item.descricao ?? undefined}>
                            {item.descricao ?? `CPV ${item.cpv}`}
                          </div>
                          <div className="font-mono text-[10px] text-muted-foreground">{item.cpv}</div>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(item.empresas)}</td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatNumber(item.contratos)}</td>
                        <td className="whitespace-nowrap py-2 text-right text-xs">{formatCompactEuro(item.valor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          )}

          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-300" />
            {conjunto.aviso ?? "Comparação a partir de uma amostra dos contratos de cada empresa."}
          </p>
        </>
      )}
    </div>
  );
}

/** Tabela simples de cruzamentos (todas com a mesma forma: item → colunas). */
function TabelaCruzamento({
  itens,
  colunas,
  linha,
  vazio,
  onDossie,
  nifDe,
}: {
  itens: PadroesCruzamento[];
  colunas: string[];
  linha: (item: PadroesCruzamento) => React.ReactNode[];
  vazio: string;
  onDossie?: (nif?: string | null) => void;
  nifDe?: (item: PadroesCruzamento) => string | null | undefined;
}) {
  if (itens.length === 0) return <EmptyState>{vazio}</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-collapse text-left text-sm">
        <thead>
          <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
            {colunas.map((coluna) => (
              <th key={coluna} className="py-2 pr-3 last:text-right">
                {coluna}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {itens.slice(0, 40).map((item, indice) => (
            <tr key={`${item.nif ?? item.cpv ?? item.processo}-${indice}`} className="border-t border-white/5 align-top text-xs">
              {linha(item).map((celula, coluna) => (
                <td key={coluna} className="max-w-[280px] py-2 pr-3">
                  {coluna === 0 && nifDe && onDossie && nifDe(item) ? (
                    <button onClick={() => onDossie(nifDe(item))} className="block max-w-[260px] truncate text-left text-teal-200 transition hover:text-teal-100">
                      {celula}
                    </button>
                  ) : (
                    celula
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default PadroesEmpresasComparar;
