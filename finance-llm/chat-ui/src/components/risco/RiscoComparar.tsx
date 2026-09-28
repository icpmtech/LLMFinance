/**
 * **Comparar várias empresas** pelo risco: escolhe-se um conjunto (com
 * sugestões do cadastro), corre-se a análise de cada uma e compara-se lado a
 * lado — risco, carteira, concentração, aditivos — com os **cruzamentos**
 * (compradores, pessoas, processos e CPV partilhados) e a rede desenhada a pedido.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Building2,
  GitBranch,
  Loader2,
  Network,
  Plus,
  Scale,
  ShieldAlert,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";

import { compararRisco, sugerirRisco } from "../../riscoApi";
import type { RiscoComparacao, RiscoLinha, RiscoSugestao } from "../../riscoApi";
import { GraphCanvas } from "../graph/GraphCanvas";
import { toStudioGraph } from "../graph/graphStudio";
import type { GraphMetric, StudioNode } from "../graph/graphStudio";
import { Chip, EmptyState, Loading, SectionCard, formatCompactEuro, formatPct, formatNumber } from "../padroes/padroesKit";
import { AvisoModelo, RiscoBadge, riscoCor, riscoTone } from "./riscoKit";

type Alvo = { nif: string; nome: string; pais: string };

const MAX_EMPRESAS = 12;

export function RiscoComparar({ iniciais, paisInicial = "PT" }: { iniciais: Alvo[]; paisInicial?: string }) {
  const [alvos, setAlvos] = useState<Alvo[]>(iniciais);
  const [texto, setTexto] = useState("");
  const [pais, setPais] = useState(paisInicial);
  const [sugestoes, setSugestoes] = useState<RiscoSugestao[]>([]);
  const [detalhado, setDetalhado] = useState(true);
  const [dados, setDados] = useState<RiscoComparacao | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [metric, setMetric] = useState<GraphMetric>("valor");
  const [layout, setLayout] = useState<"hierarchical" | "circular" | "network">("hierarchical");
  const [mostrarRede, setMostrarRede] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);

  useEffect(() => {
    setAlvos(iniciais);
  }, [iniciais]);

  useEffect(() => {
    const termo = texto.trim();
    if (termo.length < 2) {
      setSugestoes([]);
      return;
    }
    let cancelado = false;
    const timer = setTimeout(async () => {
      try {
        const resposta = await sugerirRisco(termo, 6);
        if (!cancelado) setSugestoes(resposta.itens || []);
      } catch {
        if (!cancelado) setSugestoes([]);
      }
    }, 220);
    return () => {
      cancelado = true;
      clearTimeout(timer);
    };
  }, [texto]);

  const adicionar = useCallback(
    (item: Alvo) => {
      setAlvos((atual) => {
        if (atual.length >= MAX_EMPRESAS) return atual;
        if (atual.some((alvo) => alvo.nif === item.nif && alvo.pais === item.pais)) return atual;
        return [...atual, item];
      });
      setTexto("");
      setSugestoes([]);
    },
    [],
  );

  const comparar = useCallback(async () => {
    if (alvos.length === 0) {
      setErro("Adicione pelo menos uma empresa.");
      return;
    }
    setCarregando(true);
    setErro("");
    try {
      const resposta = await compararRisco({ nifs: alvos.filter((alvo) => alvo.pais === pais).map((alvo) => alvo.nif), nomes: [], pais, detalhado });
      setDados(resposta);
    } catch (exc) {
      setDados(null);
      setErro(exc instanceof Error ? exc.message : "Falhou a comparação.");
    } finally {
      setCarregando(false);
    }
  }, [alvos, detalhado, pais]);

  const grafo = useMemo(() => (dados?.grafo ? toStudioGraph(dados.grafo, metric) : null), [dados, metric]);
  const resumo = dados?.risco_resumo;

  return (
    <div className="space-y-5">
      <SectionCard
        title="Comparar empresas pelo risco"
        subtitle={`Escolha até ${MAX_EMPRESAS} empresas (NIF ou nome). A comparação dá o risco lado a lado, os cruzamentos e a rede.`}
        icon={Scale}
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="relative min-w-[280px] flex-1">
              <input
                value={texto}
                onChange={(evento) => setTexto(evento.target.value)}
                placeholder="Adicionar empresa (nome, marca ou NIF)…"
                autoComplete="off"
                className="w-full rounded-xl border border-white/12 bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-teal-400/40"
                aria-label="Adicionar empresa à comparação"
              />
              {sugestoes.length > 0 && (
                <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-2xl border border-white/12 bg-[#0b1116]/95 p-1.5 shadow-2xl backdrop-blur">
                  {sugestoes.map((sugestao) => (
                    <li key={`${sugestao.nif}-${sugestao.nome}`}>
                      <button
                        onClick={() => adicionar({ nif: sugestao.nif, nome: sugestao.nome, pais })}
                        className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-white/[0.06]"
                      >
                        <span className="truncate">{sugestao.nome}</span>
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {sugestao.nif} · {formatNumber(sugestao.contratos ?? 0)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <select
              value={pais}
              onChange={(evento) => setPais(evento.target.value)}
              className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-2 text-xs outline-none"
              aria-label="País do conjunto"
            >
              <option value="PT" className="bg-[#0b1116]">Portugal</option>
              <option value="ES" className="bg-[#0b1116]">Espanha</option>
            </select>
            <button
              onClick={() => void comparar()}
              disabled={carregando || alvos.length === 0}
              className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-50"
            >
              {carregando ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              Comparar
            </button>
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-3 py-2 text-xs">
              <input type="checkbox" checked={detalhado} onChange={(evento) => setDetalhado(evento.target.checked)} className="accent-teal-400" />
              dossiê completo
            </label>
          </div>

          {alvos.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {alvos.map((alvo) => (
                <span key={`${alvo.pais}:${alvo.nif}`} className="inline-flex items-center gap-1.5 rounded-full border border-white/12 bg-white/[0.04] px-2.5 py-1 text-[11px]">
                  <Building2 size={12} className="text-muted-foreground" />
                  {alvo.nome}
                  <button onClick={() => setAlvos((atual) => atual.filter((item) => !(item.nif === alvo.nif && item.pais === alvo.pais)))} aria-label={`Remover ${alvo.nome}`}>
                    <Trash2 size={12} className="text-muted-foreground transition hover:text-rose-300" />
                  </button>
                </span>
              ))}
              <button onClick={() => setAlvos([])} className="text-[11px] text-muted-foreground underline transition hover:text-foreground">
                limpar
              </button>
            </div>
          )}
          {alvos.length === 0 && (
            <EmptyState>
              <span className="flex items-center gap-1.5">
                <Plus size={13} /> Escolha empresas na pesquisa (caixa «juntar à comparação») ou escreva aqui o nome.
              </span>
            </EmptyState>
          )}
          {erro && <EmptyState tone="warn">{erro}</EmptyState>}
        </div>
      </SectionCard>

      {carregando && <Loading label="A calcular o risco e os cruzamentos do conjunto…" />}

      {dados?.error && !carregando && <EmptyState tone="warn">{dados.error}</EmptyState>}

      {dados && !dados.error && !carregando && (
        <>
          {resumo && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="glass-card gradient-border rounded-2xl p-4">
                <p className="text-xs text-muted-foreground">Empresas comparadas</p>
                <p className="stat-value text-xl font-bold">{resumo.empresas}</p>
              </div>
              <div className="glass-card gradient-border rounded-2xl p-4">
                <p className="text-xs text-muted-foreground">Risco médio / máximo</p>
                <p className="stat-value text-xl font-bold">
                  {resumo.score_medio ?? "—"} <span className="text-sm text-muted-foreground">/ {resumo.score_maximo ?? "—"}</span>
                </p>
              </div>
              <div className="glass-card gradient-border rounded-2xl p-4">
                <p className="text-xs text-muted-foreground">Por nível</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {Object.entries(resumo.por_nivel || {})
                    .filter(([, total]) => total > 0)
                    .map(([nivel, total]) => (
                      <Chip key={nivel} tone={riscoTone(nivel)}>
                        {nivel} · {total}
                      </Chip>
                    ))}
                </div>
              </div>
              <div className="glass-card gradient-border rounded-2xl p-4">
                <p className="text-xs text-muted-foreground">Para olhar primeiro</p>
                {resumo.criticas?.length ? (
                  <ul className="mt-1 space-y-0.5 text-[11px]">
                    {resumo.criticas.slice(0, 3).map((item) => (
                      <li key={item.nif} className="truncate">
                        {item.nome} · <span className="font-mono">{item.score}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-[11px] text-muted-foreground">Nenhuma empresa em nível crítico.</p>
                )}
              </div>
            </div>
          )}

          <SectionCard
            title="Risco e carteira lado a lado"
            subtitle="Ordenado pelo risco: quem olhar primeiro, com os números que sustentam a ordem"
            icon={BarChart3}
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1020px] border-collapse text-left text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="pb-2 pr-3">#</th>
                    <th className="pb-2 pr-3">Empresa</th>
                    <th className="pb-2 pr-3">Risco</th>
                    <th className="pb-2 pr-3">Contratos</th>
                    <th className="pb-2 pr-3">Valor</th>
                    <th className="pb-2 pr-3">Ajuste direto</th>
                    <th className="pb-2 pr-3">Aditivos</th>
                    <th className="pb-2 pr-3">Concentração</th>
                    <th className="pb-2 pr-3">Compradores</th>
                    <th className="pb-2 pr-3">CIRE</th>
                  </tr>
                </thead>
                <tbody>
                  {(dados.empresas || []).map((linha, index) => (
                    <LinhaComparacao key={String(linha.nif)} linha={linha} posicao={index + 1} />
                  ))}
                </tbody>
              </table>
            </div>
            <AvisoModelo risco={dados.empresas?.[0]?.risco ?? null} className="mt-4" />
            {!!dados.avisos?.length && (
              <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                {dados.avisos.map((aviso, index) => (
                  <li key={index}>· {aviso}</li>
                ))}
              </ul>
            )}
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Compradores comuns" subtitle="Quem compra a duas ou mais empresas do conjunto" icon={Building2}>
              <ListaCruzamento
                vazio="Nenhum comprador comum."
                itens={(dados.cruzamentos?.adjudicantes || []).map((item) => ({
                  chave: item.nif || item.nome || "",
                  titulo: item.nome || item.nif || "—",
                  detalhe: `${formatNumber(item.contratos)} contratos · ${formatCompactEuro(item.valor)}`,
                  etiquetas: (item.empresas || []).length ? [`${item.empresas!.length} empresas`] : [],
                }))}
              />
            </SectionCard>
            <SectionCard title="Pessoas comuns" subtitle="Gerentes/órgãos sociais partilhados" icon={Users}>
              <ListaCruzamento
                vazio="Nenhuma pessoa partilhada."
                itens={(dados.cruzamentos?.pessoas || []).map((item) => ({
                  chave: item.nif || item.nome || "",
                  titulo: item.nome || item.nif || "—",
                  detalhe: (item.cargos || []).join(", ") || "órgão social",
                  etiquetas: [`${(item.empresas || []).length} empresas`],
                }))}
              />
            </SectionCard>
            <SectionCard title="Processos partilhados" subtitle="Insolvências/PER com mais de uma empresa do conjunto" icon={ShieldAlert}>
              <ListaCruzamento
                vazio="Nenhum processo partilhado."
                itens={(dados.cruzamentos?.processos || []).map((item) => ({
                  chave: item.processo || item.especie || "",
                  titulo: item.especie || "processo",
                  detalhe: [item.processo, item.tribunal].filter(Boolean).join(" · "),
                  etiquetas: [`${(item.empresas || []).length} empresas`],
                }))}
              />
            </SectionCard>
            <SectionCard title="Mercado comum (CPV)" subtitle="Onde as empresas do conjunto competem" icon={GitBranch}>
              <ListaCruzamento
                vazio="Nenhum CPV comum."
                itens={(dados.cruzamentos?.cpv || []).map((item) => ({
                  chave: item.cpv || "",
                  titulo: `${item.cpv} · ${item.descricao || ""}`,
                  detalhe: "",
                  etiquetas: [`${(item.empresas || []).length} empresas`],
                }))}
              />
            </SectionCard>
          </div>

          {dados.grafo && (
            <SectionCard
              title="Rede do conjunto"
              subtitle={`${dados.grafo.nodes?.length ?? 0} nós · ${dados.grafo.edges?.length ?? 0} ligações`}
              icon={Network}
              actions={
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={metric}
                    onChange={(evento) => setMetric(evento.target.value as GraphMetric)}
                    className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
                    aria-label="Métrica da rede"
                  >
                    <option value="valor" className="bg-[#0b1116]">Valor</option>
                    <option value="contratos" className="bg-[#0b1116]">Contratos</option>
                  </select>
                  <select
                    value={layout}
                    onChange={(evento) => {
                      setLayout(evento.target.value as "hierarchical" | "circular" | "network");
                      setLayoutVersion((valor) => valor + 1);
                    }}
                    className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
                    aria-label="Disposição da rede"
                  >
                    <option value="hierarchical" className="bg-[#0b1116]">Hierárquica</option>
                    <option value="circular" className="bg-[#0b1116]">Circular</option>
                    <option value="network" className="bg-[#0b1116]">Forças</option>
                  </select>
                  <button
                    onClick={() => setMostrarRede((valor) => !valor)}
                    className="rounded-xl border border-white/12 px-3 py-1.5 text-xs transition hover:text-foreground"
                  >
                    {mostrarRede ? "Ocultar rede" : "Desenhar rede"}
                  </button>
                </div>
              }
            >
              {mostrarRede ? (
                <GraphCanvas
                  graph={grafo}
                  layout={layout}
                  metric={metric}
                  layoutVersion={layoutVersion}
                  heightClass="h-[460px]"
                  nodeSummary={(no: StudioNode) => `${formatNumber(no.count)} contratos · ${formatCompactEuro(no.total_value)}`}
                />
              ) : (
                <EmptyState>
                  A rede só é desenhada a pedido (a simulação de forças é pesada no browser). Carregue em «Desenhar rede».
                </EmptyState>
              )}
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}

function LinhaComparacao({ linha, posicao }: { linha: RiscoLinha; posicao: number }) {
  const resumo = linha.resumo || {};
  const risco = linha.risco;
  return (
    <tr className="border-t border-white/[0.06]">
      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{posicao}</td>
      <td className="max-w-[260px] py-2 pr-3">
        <span className="truncate">{linha.nome || linha.nif}</span>
        <span className="block font-mono text-[10px] text-muted-foreground">{linha.nif}</span>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        <RiscoBadge risco={risco} />
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatNumber(linha.contratos_analisados ?? resumo.contratos)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatCompactEuro(resumo.valor_total)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatPct(resumo.taxa_ajuste_direto)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatPct(resumo.taxa_aditivo)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatPct(resumo.concentracao_adjudicante)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatNumber(resumo.adjudicantes_distintos)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {linha.insolvencias ? (
          <span style={{ color: riscoCor("critico") }}>{formatNumber(linha.insolvencias)}</span>
        ) : (
          <span className="text-muted-foreground">não</span>
        )}
      </td>
    </tr>
  );
}

function ListaCruzamento({
  itens,
  vazio,
}: {
  itens: { chave: string; titulo: string; detalhe: string; etiquetas: string[] }[];
  vazio: string;
}) {
  if (!itens.length) return <EmptyState>{vazio}</EmptyState>;
  return (
    <ul className="space-y-2 text-xs">
      {itens.slice(0, 10).map((item) => (
        <li key={item.chave} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
          <span className="min-w-0 flex-1 truncate">{item.titulo}</span>
          <span className="flex shrink-0 items-center gap-2">
            {item.detalhe && <span className="text-[11px] text-muted-foreground">{item.detalhe}</span>}
            {item.etiquetas.map((etiqueta) => (
              <Chip key={etiqueta} tone="blue">
                {etiqueta}
              </Chip>
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}
