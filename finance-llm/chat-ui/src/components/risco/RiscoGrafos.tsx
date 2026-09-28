/**
 * **Área de grafos analíticos 360**: escolhe-se uma empresa e desenha-se a rede
 * que explica o risco — compradores (por valor), órgãos sociais, empresas que
 * ganham aos mesmos compradores, processos do CIRE e os co-intervenientes desses
 * processos.
 *
 * O canvas só é montado **a pedido**: a simulação de forças com muitos nós deixa
 * o browser lento (a lição do dossiê do módulo de padrões), e a disposição
 * hierárquica é a de omissão por ser determinística.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  GitBranch,
  Layers,
  Loader2,
  Network,
  Newspaper,
  Scale,
  ShieldAlert,
  Users,
} from "lucide-react";

import { getRiscoGrafo, sugerirRisco } from "../../riscoApi";
import type { RiscoGrafo360, RiscoSugestao } from "../../riscoApi";
import { GraphCanvas } from "../graph/GraphCanvas";
import { TYPE_COLORS, toStudioGraph } from "../graph/graphStudio";
import type { GraphMetric, StudioNode } from "../graph/graphStudio";
import { Chip, EmptyState, Kpi, Loading, SectionCard, formatCompactEuro, formatDate, formatNumber } from "../padroes/padroesKit";

type Vista = { nif: string; nome: string; pais: string };

export function RiscoGrafos({ empresa }: { empresa: Vista | null }) {
  const [alvo, setAlvo] = useState<Vista | null>(empresa);
  const [texto, setTexto] = useState("");
  const [pais, setPais] = useState(empresa?.pais || "PT");
  const [sugestoes, setSugestoes] = useState<RiscoSugestao[]>([]);
  const [dados, setDados] = useState<RiscoGrafo360 | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [metric, setMetric] = useState<GraphMetric>("valor");
  const [layout, setLayout] = useState<"hierarchical" | "circular" | "network">("hierarchical");
  const [mostrar, setMostrar] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);

  useEffect(() => {
    if (empresa) setAlvo(empresa);
  }, [empresa]);

  const carregar = useCallback(async (vista: Vista) => {
    setCarregando(true);
    setErro("");
    try {
      const resposta = await getRiscoGrafo(vista.pais, vista.nif);
      setDados(resposta);
      setMostrar(true);
    } catch (exc) {
      setDados(null);
      setErro(exc instanceof Error ? exc.message : "Não foi possível obter o grafo 360.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    if (alvo) void carregar(alvo);
  }, [alvo, carregar]);

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

  const grafo = useMemo(() => (dados?.grafo ? toStudioGraph(dados.grafo, metric) : null), [dados, metric]);
  const tipos = useMemo(() => {
    const contagem = new Map<string, number>();
    (dados?.grafo?.nodes || []).forEach((no) => contagem.set(no.type, (contagem.get(no.type) || 0) + 1));
    return [...contagem.entries()];
  }, [dados]);

  return (
    <div className="space-y-5">
      <SectionCard
        title="Grafo analítico 360"
        subtitle="Compradores, órgãos sociais, empresas ligadas e processos do CIRE — a rede que explica o risco de uma empresa"
        icon={Network}
      >
        <div className="flex flex-wrap items-end gap-2">
          <div className="relative min-w-[280px] flex-1">
            <input
              value={texto}
              onChange={(evento) => setTexto(evento.target.value)}
              placeholder="Empresa do grafo (nome, marca ou NIF)…"
              autoComplete="off"
              className="w-full rounded-xl border border-white/12 bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-teal-400/40"
              aria-label="Escolher empresa para o grafo 360"
            />
            {sugestoes.length > 0 && (
              <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-2xl border border-white/12 bg-[#0b1116]/95 p-1.5 shadow-2xl backdrop-blur">
                {sugestoes.map((sugestao) => (
                  <li key={`${sugestao.nif}-${sugestao.nome}`}>
                    <button
                      onClick={() => {
                        setAlvo({ nif: sugestao.nif, nome: sugestao.nome, pais });
                        setTexto("");
                        setSugestoes([]);
                      }}
                      className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-white/[0.06]"
                    >
                      <span className="truncate">{sugestao.nome}</span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">{sugestao.nif}</span>
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
            aria-label="País"
          >
            <option value="PT" className="bg-[#0b1116]">Portugal</option>
            <option value="ES" className="bg-[#0b1116]">Espanha</option>
          </select>
          {alvo && (
            <button
              onClick={() => void carregar({ ...alvo, pais })}
              className="flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-2 text-xs transition hover:text-foreground"
            >
              {carregando ? <Loader2 size={13} className="animate-spin" /> : <GitBranch size={13} />} Recarregar
            </button>
          )}
        </div>
        {alvo && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Empresa em análise: <strong>{alvo.nome}</strong> <span className="font-mono">{alvo.nif}</span> · {alvo.pais}
          </p>
        )}
        {dados?.nota && <p className="mt-1 text-[11px] text-muted-foreground">{dados.nota}</p>}
        {erro && <div className="mt-3"><EmptyState tone="warn">{erro}</EmptyState></div>}
      </SectionCard>

      {!alvo && !erro && (
        <EmptyState>
          Escolha uma empresa (ou abra o dossiê de uma empresa e carregue em «Grafo 360») para desenhar a rede.
        </EmptyState>
      )}

      {carregando && !dados && <Loading label="A montar o grafo 360 (contratos, cargos, CIRE)…" />}

      {dados && !dados.error && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi icon={Layers} label="Nós na rede" value={formatNumber(dados.grafo?.nodes?.length ?? 0)} sub={`${formatNumber(dados.grafo?.edges?.length ?? 0)} ligações`} />
            <Kpi icon={Building2} label="Compradores" value={formatNumber(dados.resumo?.adjudicantes_distintos ?? 0)} sub="entidades distintas" color="text-sky-300" glow="glow-sky" />
            <Kpi icon={Scale} label="Valor na amostra" value={formatCompactEuro(dados.resumo?.valor_total)} sub={`${formatNumber(dados.contratos_total ?? 0)} contratos`} />
            <Kpi
              icon={ShieldAlert}
              label="Insolvências (CIRE)"
              value={formatNumber(dados.insolvencias?.length ?? 0)}
              sub={
                dados.processos_cire?.length
                  ? `a empresa aparece em ${dados.processos_cire.length} processo(s) no total`
                  : dados.lacos?.length
                    ? `${dados.lacos.length} laço(s) identificado(s)`
                    : "sem processos"
              }
              color="text-rose-300"
              glow="glow-rose"
            />
          </div>

          <SectionCard
            title="Rede 360"
            subtitle={`${dados.grafo?.meta?.documents_scanned ?? 0} documentos varridos · dimensão ${
              dados.grafo?.meta?.dimension_a || "empresa"
            }${dados.grafo?.meta?.dimension_b ? ` × ${dados.grafo.meta.dimension_b}` : ""}`}
            icon={Network}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={metric}
                  onChange={(evento) => setMetric(evento.target.value as GraphMetric)}
                  className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
                  aria-label="Métrica"
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
                  aria-label="Disposição"
                >
                  <option value="hierarchical" className="bg-[#0b1116]">Hierárquica</option>
                  <option value="circular" className="bg-[#0b1116]">Circular</option>
                  <option value="network" className="bg-[#0b1116]">Forças</option>
                </select>
                <button onClick={() => setMostrar((valor) => !valor)} className="rounded-xl border border-white/12 px-3 py-1.5 text-xs transition hover:text-foreground">
                  {mostrar ? "Ocultar" : "Desenhar"}
                </button>
              </div>
            }
          >
            {tipos.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {tipos.map(([tipo, total]) => (
                  <span
                    key={tipo}
                    className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5 text-[11px]"
                    style={{ color: TYPE_COLORS[tipo] || TYPE_COLORS.outra }}
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: TYPE_COLORS[tipo] || TYPE_COLORS.outra }} />
                    {tipo} · {total}
                  </span>
                ))}
              </div>
            )}
            {mostrar ? (
              <GraphCanvas
                graph={grafo}
                layout={layout}
                metric={metric}
                layoutVersion={layoutVersion}
                heightClass="h-[540px]"
                nodeSummary={(no: StudioNode) => `${formatNumber(no.count)} contratos · ${formatCompactEuro(no.total_value)}`}
              />
            ) : (
              <EmptyState>Carregue em «Desenhar» para montar o canvas (a simulação é pesada com muitos nós).</EmptyState>
            )}
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Laços e sinais" subtitle="O que liga esta empresa a outras" icon={GitBranch}>
              {dados.lacos?.length || dados.sinais?.length ? (
                <ul className="space-y-2 text-xs">
                  {(dados.lacos || []).slice(0, 10).map((laco, index) => (
                    <li key={index} className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                      <span className="text-muted-foreground">{laco.tipo || "ligação"}: </span>
                      {laco.detalhe || laco.nome || "—"}
                    </li>
                  ))}
                  {(dados.sinais || []).slice(0, 6).map((sinal) => (
                    <li key={sinal.padrao} className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                      <Chip tone="amber">{sinal.padrao}</Chip> <span className="ml-1">{sinal.detalhe}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState>Sem laços identificados na amostra.</EmptyState>
              )}
            </SectionCard>

            <SectionCard title="Órgãos sociais e processos" subtitle="Pessoas ligadas à empresa e insolvências" icon={Users}>
              <div className="space-y-3 text-xs">
                <div>
                  <p className="mb-1 text-muted-foreground">Cargos sociais ({dados.cargos_sociais?.length ?? 0})</p>
                  {dados.cargos_sociais?.length ? (
                    <ul className="space-y-1">
                      {dados.cargos_sociais.slice(0, 8).map((pessoa) => (
                        <li key={pessoa.nif} className="flex items-center justify-between gap-3">
                          <span className="truncate">{pessoa.nome || pessoa.nif}</span>
                          <span className="shrink-0 text-muted-foreground">
                            {(pessoa.cargos || []).map((cargo) => cargo.role || cargo.role_org).filter(Boolean).slice(0, 2).join(", ")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground">Sem cargos sociais registados.</p>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-muted-foreground">
                    Como insolvente ({dados.insolvencias?.length ?? 0})
                  </p>
                  {dados.insolvencias?.length ? (
                    <ul className="space-y-1">
                      {dados.insolvencias.slice(0, 6).map((processo, index) => (
                        <li key={`${processo.processo}-${index}`} className="flex items-center justify-between gap-3">
                          <span className="truncate">{processo.especie || "processo"} · {processo.processo || "—"}</span>
                          <span className="shrink-0 text-muted-foreground">{formatDate(processo.data)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground">Sem processos em que a empresa seja a insolvente.</p>
                  )}
                </div>
                {!!dados.processos_cire?.length && (
                  <div>
                    <p className="mb-1 text-muted-foreground">
                      Outros processos do CIRE onde aparece ({dados.processos_cire.length})
                    </p>
                    <ul className="space-y-1">
                      {dados.processos_cire.slice(0, 4).map((processo, index) => (
                        <li key={`m-${processo.processo}-${index}`} className="truncate text-muted-foreground">
                          {processo.especie || "processo"} · {processo.processo || "—"}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      São processos de terceiros (a empresa pode ser credora ou requerente) — contam como relação,
                      não como insolvência da empresa.
                    </p>
                  </div>
                )}
                {!!dados.noticias?.length && (
                  <div>
                    <p className="mb-1 flex items-center gap-1.5 text-muted-foreground">
                      <Newspaper size={13} /> Menções públicas
                    </p>
                    <ul className="space-y-1">
                      {dados.noticias.slice(0, 5).map((noticia, index) => (
                        <li key={index} className="truncate">
                          {noticia.url ? (
                            <a href={noticia.url} target="_blank" rel="noreferrer" className="hover:text-teal-200">
                              {noticia.titulo || noticia.url}
                            </a>
                          ) : (
                            noticia.titulo || "—"
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
