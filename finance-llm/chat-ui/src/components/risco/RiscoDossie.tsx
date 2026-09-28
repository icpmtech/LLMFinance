/**
 * **Dossiê 360 de uma empresa**: nível de risco, componentes que o sustentam,
 * contratos associados (com risco por contrato), relações e parecer por IA.
 *
 * O dossiê completo corre a análise do módulo de padrões (réguas de CPV por
 * setor) e o modelo de anomalia sobre a população de empresas comparáveis — por
 * isso demora mais na primeira vez e fica em cache depois.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  ArrowLeft,
  Brain,
  Building2,
  Coins,
  FileSearch,
  Gauge,
  Landmark,
  Network,
  Newspaper,
  RefreshCw,
  Scale,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";

import { getRiscoEmpresa, pedirParecerRisco } from "../../riscoApi";
import type { RiscoContrato, RiscoEmpresa, RiscoParecer } from "../../riscoApi";
import { MARKDOWN_COMPONENTS } from "../people/peopleKit";
import {
  Chip,
  EmptyState,
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
} from "../padroes/padroesKit";
import { AnomaliaMl, AvisosRisco, AvisoModelo, ComponentesRisco, RiscoBadge, RiscoGauge, riscoCor, riscoTone } from "./riscoKit";

type OrdemContratos = "risco" | "valor" | "ano";

export function RiscoDossie({
  nif,
  pais,
  onVoltar,
  onComparar,
  onGrafo,
}: {
  nif: string;
  pais: string;
  onVoltar: () => void;
  onComparar: (nif: string, pais: string) => void;
  onGrafo: (nif: string, pais: string) => void;
}) {
  const [dados, setDados] = useState<RiscoEmpresa | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [detalhado, setDetalhado] = useState(true);
  const [parecer, setParecer] = useState<RiscoParecer | null>(null);
  const [aPedirParecer, setAPedirParecer] = useState(false);
  const [erroParecer, setErroParecer] = useState("");
  const [filtro, setFiltro] = useState("");
  const [ordem, setOrdem] = useState<OrdemContratos>("risco");

  const carregar = useCallback(
    async (opcoes: { detalhado: boolean }) => {
      setCarregando(true);
      setErro("");
      setParecer(null);
      setErroParecer("");
      try {
        const resposta = await getRiscoEmpresa(pais, nif, { detalhado: opcoes.detalhado, max_contratos: 400 });
        setDados(resposta);
      } catch (exc) {
        setDados(null);
        setErro(exc instanceof Error ? exc.message : "Não foi possível obter o risco desta empresa.");
      } finally {
        setCarregando(false);
      }
    },
    [nif, pais],
  );

  useEffect(() => {
    void carregar({ detalhado });
  }, [carregar, detalhado]);

  const risco = dados?.risco ?? null;
  const resumo = dados?.resumo ?? null;
  // Insolvências do CIRE filtradas por papel: o cadastro/análise contam também
  // os processos em que a empresa é **credora** (banca, AT, Segurança Social).
  const insolvencias = dados?.insolvencias ?? [];

  const contratos = useMemo(() => {
    const lista = [...(dados?.contratos || [])];
    const texto = filtro.trim().toLowerCase();
    const filtrada = texto
      ? lista.filter((item) =>
          [item.objeto, item.cpv, item.cpv_desc, item.adjudicante, item.procedimento]
            .filter(Boolean)
            .some((valor) => String(valor).toLowerCase().includes(texto)),
        )
      : lista;
    if (ordem === "valor") return filtrada.sort((a, b) => (b.valor || 0) - (a.valor || 0));
    if (ordem === "ano") return filtrada.sort((a, b) => (b.ano || 0) - (a.ano || 0));
    return filtrada.sort((a, b) => ((b.risco?.score ?? -1) as number) - ((a.risco?.score ?? -1) as number));
  }, [dados, filtro, ordem]);

  async function pedirParecer() {
    setAPedirParecer(true);
    setErroParecer("");
    try {
      const resposta = await pedirParecerRisco({ nif, pais, detalhado: true });
      setParecer(resposta.ia);
    } catch (exc) {
      setErroParecer(exc instanceof Error ? exc.message : "A IA não respondeu.");
    } finally {
      setAPedirParecer(false);
    }
  }

  if (carregando && !dados) {
    return (
      <div className="space-y-4">
        <button onClick={onVoltar} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft size={14} /> Voltar à pesquisa
        </button>
        <Loading label={detalhado ? "A correr o dossiê completo (réguas de CPV e anomalia ML)…" : "A calcular a triagem…"} />
      </div>
    );
  }

  if (erro && !dados) {
    return (
      <div className="space-y-4">
        <button onClick={onVoltar} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft size={14} /> Voltar à pesquisa
        </button>
        <EmptyState tone="warn">{erro}</EmptyState>
      </div>
    );
  }

  if (!dados) return null;

  const fichaLocal = (dados.ficha || {}) as Record<string, unknown>;
  const local = (fichaLocal.local || fichaLocal.location || {}) as Record<string, string>;
  const supervisionado = risco?.modelo_supervisionado;

  return (
    <div className="space-y-5">
      <section className="glass-card gradient-border rounded-3xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <button onClick={onVoltar} className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
              <ArrowLeft size={14} /> Voltar à pesquisa
            </button>
            <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold md:text-2xl">
              <Building2 size={20} className="text-teal-300" />
              {dados.nome}
              <RiscoBadge risco={risco} />
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
              <span className="font-mono">{dados.nif}</span>
              <span>{dados.pais_label || dados.pais}</span>
              {(local.concelho || local.distrito) && <span>{[local.concelho, local.distrito].filter(Boolean).join(", ")}</span>}
              <span>
                {formatNumber(dados.contratos_analisados ?? 0)} de {formatNumber(dados.contratos_total ?? 0)} contratos analisados
              </span>
              {dados.anos?.[0] && <span>anos {dados.anos[0]}–{dados.anos[1] ?? dados.anos[0]}</span>}
              {dados.cache && <span className="opacity-70">(cache)</span>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-3 py-1.5 text-xs">
              <input type="checkbox" checked={detalhado} onChange={(evento) => setDetalhado(evento.target.checked)} className="accent-teal-400" />
              dossiê completo
            </label>
            <button
              onClick={() => void carregar({ detalhado })}
              className="flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs transition hover:text-foreground"
            >
              <RefreshCw size={13} className={carregando ? "animate-spin" : ""} /> Recalcular
            </button>
            <button
              onClick={() => onGrafo(dados.nif, dados.pais)}
              className="flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs transition hover:text-foreground"
            >
              <Network size={13} /> Grafo 360
            </button>
            <button
              onClick={() => onComparar(dados.nif, dados.pais)}
              className="flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs transition hover:text-foreground"
            >
              <Scale size={13} /> Comparar
            </button>
            <button
              onClick={() => void pedirParecer()}
              disabled={aPedirParecer}
              className="flex items-center gap-1.5 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-xs text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-50"
            >
              {aPedirParecer ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}
              Parecer por IA
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <SectionCard title="Nível de risco" subtitle={risco?.metodo_label} icon={Gauge}>
          <div className="flex flex-col items-center gap-3">
            <RiscoGauge risco={risco} />
            <div className="grid w-full grid-cols-2 gap-2 text-center text-[11px]">
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-2">
                <p className="text-muted-foreground">Confiança</p>
                <p className="font-semibold capitalize">{risco?.confianca || "—"}</p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-2">
                <p className="text-muted-foreground">Cobertura</p>
                <p className="font-semibold">{formatPct(risco?.cobertura, 0)}</p>
              </div>
            </div>
            {risco?.fatores && risco.fatores.length > 0 && (
              <div className="w-full">
                <p className="mb-1 text-[11px] text-muted-foreground">O que puxa o risco</p>
                <div className="flex flex-wrap gap-1.5">
                  {risco.fatores.map((fator) => (
                    <span key={fator.id} title={(fator.evidencia || []).join(" · ")}>
                      <Chip tone={riscoTone(risco?.nivel)}>
                        {fator.label} · {fator.pontos?.toFixed(0)}
                      </Chip>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <AvisoModelo risco={risco} />
            <AvisosRisco risco={risco} />
          </div>
        </SectionCard>

        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi icon={Coins} label="Valor adjudicado" value={formatCompactEuro(resumo?.valor_total)} sub={`mediana ${formatEuro(resumo?.valor_mediano)}`} />
            <Kpi icon={FileSearch} label="Ajuste direto" value={formatPct(resumo?.taxa_ajuste_direto)} sub={`aditivos ${formatPct(resumo?.taxa_aditivo)}`} color="text-amber-300" glow="glow-amber" />
            <Kpi icon={Landmark} label="Concentração" value={formatPct(resumo?.concentracao_adjudicante)} sub={`${formatNumber(resumo?.adjudicantes_distintos)} compradores`} color="text-sky-300" glow="glow-sky" />
            <Kpi
              icon={AlertTriangle}
              label="Contratos com sinais"
              value={formatNumber(resumo?.contratos_com_sinais)}
              sub={`${formatNumber(resumo?.contratos_atipicos_cpv)} atípicos no CPV${
                insolvencias.length ? ` · ${insolvencias.length} processo(s) de insolvência` : ""
              }`}
              color="text-rose-300"
              glow="glow-rose"
            />
          </div>

          <SectionCard title="Componentes do risco" subtitle="Pontos de cada sinal, peso efetivo e a evidência que o sustenta" icon={ShieldAlert}>
            <ComponentesRisco componentes={risco?.componentes || []} />
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Modelo de anomalia (ML)" subtitle="IsolationForest sobre empresas comparáveis" icon={Brain}>
              <AnomaliaMl risco={risco} />
              {supervisionado?.disponivel && (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Sinal de aditivo (supervisionado, Gradient Boosting): AUC {formatRatio(supervisionado.auc)} · lift no decil
                  superior {formatRatio(supervisionado.lift_top_decile)} · rótulo «{supervisionado.rotulo}».
                </p>
              )}
            </SectionCard>

            <SectionCard title="Cadastro" subtitle="O que o IQ OS sabe da empresa fora dos contratos" icon={Building2}>
              {Object.keys(fichaLocal).length === 0 && !dados.ficha ? (
                <EmptyState>Sem ficha de cadastro para este NIF.</EmptyState>
              ) : (
                <ul className="space-y-1.5 text-xs">
                  {!!(dados.ficha as Record<string, unknown>)?.nome && <li><span className="text-muted-foreground">Designação: </span>{(dados.ficha as Record<string, unknown>).nome as string}</li>}
                  {!!(dados.ficha as Record<string, unknown>)?.type && <li><span className="text-muted-foreground">Tipo: </span>{(dados.ficha as Record<string, unknown>).type as string}</li>}
                  {(local.concelho || local.distrito || local.pais) && (
                    <li>
                      <span className="text-muted-foreground">Localização: </span>
                      {[local.freguesia, local.concelho, local.distrito, local.pais].filter(Boolean).join(", ")}
                    </li>
                  )}
                  {Array.isArray((dados.ficha as Record<string, unknown>)?.roles) && (
                    <li className="flex flex-wrap items-center gap-1.5">
                      <span className="text-muted-foreground">Papéis:</span>
                      {((dados.ficha as Record<string, unknown>).roles as string[]).map((papel) => (
                        <Chip key={papel}>{papel}</Chip>
                      ))}
                    </li>
                  )}
                  {Array.isArray((dados.cadastro as Record<string, unknown>)?.source_labels) && (
                    <li className="flex flex-wrap items-center gap-1.5">
                      <span className="text-muted-foreground">Fontes:</span>
                      {((dados.cadastro as Record<string, unknown>).source_labels as string[]).map((fonte) => (
                        <Chip key={fonte} tone="blue">{fonte}</Chip>
                      ))}
                    </li>
                  )}
                  {!!dados.anos?.[0] && <li><span className="text-muted-foreground">Contratação observada: </span>{dados.anos[0]}–{dados.anos[1] ?? dados.anos[0]}</li>}
                </ul>
              )}
            </SectionCard>
          </div>
        </div>
      </div>

      {parecer && (
        <SectionCard
          title="Parecer de risco"
          subtitle={
            parecer.mode === "ai"
              ? `Redigido por ${parecer.backend?.provider || "IA"}:${parecer.backend?.model || ""}`
              : "Sem modelo configurado: parecer factual com os mesmos números"
          }
          icon={Sparkles}
        >
          <div className="prose prose-invert max-w-none prose-sm">
            <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
              {parecer.text}
            </Markdown>
          </div>
          {parecer.notes?.length ? (
            <ul className="mt-3 space-y-1 text-[11px] text-muted-foreground">
              {parecer.notes.map((nota, index) => (
                <li key={index}>· {nota}</li>
              ))}
            </ul>
          ) : null}
          {parecer.warnings?.length ? (
            <ul className="mt-2 space-y-1 text-[11px] text-amber-300">
              {parecer.warnings.map((aviso, index) => (
                <li key={index}>· {aviso}</li>
              ))}
            </ul>
          ) : null}
        </SectionCard>
      )}
      {erroParecer && <EmptyState tone="warn">{erroParecer}</EmptyState>}

      {!!dados.sinais?.length && (
        <SectionCard title="Sinais de regra" subtitle="Regras do módulo de deteção de padrões cumpridas por estes contratos" icon={AlertTriangle}>
          <ul className="grid gap-2 md:grid-cols-2">
            {dados.sinais.map((sinal) => (
              <li key={sinal.padrao} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm">{sinal.label || sinal.padrao}</span>
                  <span className="flex items-center gap-1.5">
                    <Chip tone={sinal.severidade === "alerta" ? "rose" : sinal.severidade === "aviso" ? "amber" : "neutral"}>
                      {sinal.severidade || "info"}
                    </Chip>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {formatNumber(sinal.contratos)} · {formatPct(sinal.taxa)}
                    </span>
                  </span>
                </div>
                {!!sinal.exemplos?.length && (
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    Ex.: {sinal.exemplos[0].objeto || "—"} {sinal.exemplos[0].detalhe ? `· ${sinal.exemplos[0].detalhe}` : ""}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard
        title="Contratos associados"
        subtitle={`${formatNumber(contratos.length)} contrato(s) nesta vista · risco por contrato a partir das regras, aditivos, valores atípicos e concorrência`}
        icon={FileSearch}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {dados.contratos_resumo && (
              <span className="flex flex-wrap gap-1.5">
                {Object.entries(dados.contratos_resumo.por_nivel)
                  .filter(([, total]) => total > 0)
                  .map(([nivel, total]) => (
                    <Chip key={nivel} tone={riscoTone(nivel)}>
                      {nivel} · {total}
                    </Chip>
                  ))}
              </span>
            )}
            <select
              value={ordem}
              onChange={(evento) => setOrdem(evento.target.value as OrdemContratos)}
              className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
              aria-label="Ordenar contratos"
            >
              <option value="risco" className="bg-[#0b1116]">Risco</option>
              <option value="valor" className="bg-[#0b1116]">Valor</option>
              <option value="ano" className="bg-[#0b1116]">Ano</option>
            </select>
          </div>
        }
      >
        <div className="mb-3 max-w-md">
          <SearchInput value={filtro} onChange={setFiltro} placeholder="Filtrar por objeto, CPV, comprador ou procedimento…" />
        </div>
        {contratos.length === 0 ? (
          <EmptyState>Sem contratos para mostrar com este filtro. Ative o «dossiê completo» para ver os contratos.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="pb-2 pr-3">Risco</th>
                  <th className="pb-2 pr-3">Ano</th>
                  <th className="pb-2 pr-3">Objeto</th>
                  <th className="pb-2 pr-3">Valor</th>
                  <th className="pb-2 pr-3">Comprador</th>
                  <th className="pb-2 pr-3">Procedimento</th>
                  <th className="pb-2 pr-3">Conc.</th>
                  <th className="pb-2 pr-3">σ CPV</th>
                  <th className="pb-2 pr-3">Aditivo</th>
                </tr>
              </thead>
              <tbody>
                {contratos.slice(0, 300).map((item, index) => (
                  <LinhaContrato key={item.id || `${item.ano}-${index}`} item={item} />
                ))}
              </tbody>
            </table>
            {contratos.length > 300 && (
              <p className="mt-2 text-[11px] text-muted-foreground">A mostrar os 300 contratos de maior risco de {formatNumber(contratos.length)}.</p>
            )}
          </div>
        )}
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Quem compra" subtitle="Compradores por valor adjudicado" icon={Landmark}>
          {dados.adjudicantes?.length ? (
            <ul className="space-y-1.5 text-xs">
              {dados.adjudicantes.slice(0, 10).map((item) => (
                <li key={item.nif || item.nome || ""} className="flex items-center justify-between gap-3">
                  <span className="truncate">{item.nome || item.nif}</span>
                  <span className="shrink-0 font-mono text-muted-foreground">
                    {formatNumber(item.contratos)} · {formatCompactEuro(item.valor)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>Sem compradores na amostra.</EmptyState>
          )}
        </SectionCard>

        <SectionCard title="Relações" subtitle="Pessoas, empresas ligadas, insolvências e menções" icon={Users}>
          <div className="space-y-3 text-xs">
            {!!dados.relacoes?.cargos_sociais?.length && (
              <div>
                <p className="mb-1 text-muted-foreground">Órgãos sociais ({dados.relacoes.cargos_sociais.length})</p>
                <ul className="space-y-1">
                  {dados.relacoes.cargos_sociais.slice(0, 6).map((pessoa) => (
                    <li key={pessoa.nif} className="flex items-center justify-between gap-3">
                      <span className="truncate">{pessoa.nome || pessoa.nif}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {(pessoa.cargos || []).map((cargo) => cargo.role || cargo.role_org).filter(Boolean).slice(0, 2).join(", ")}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!dados.relacoes?.empresas?.length && (
              <div>
                <p className="mb-1 text-muted-foreground">Empresas que ganham aos mesmos compradores</p>
                <ul className="space-y-1">
                  {dados.relacoes.empresas.slice(0, 6).map((outra) => (
                    <li key={outra.nif || outra.nome || ""} className="flex items-center justify-between gap-3">
                      <span className="truncate">{outra.nome || outra.nif}</span>
                      <span className="shrink-0 font-mono text-muted-foreground">{formatNumber(outra.contratos)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {insolvencias.length > 0 && (
              <div>
                <p className="mb-1 text-rose-300">Insolvências / PER — como insolvente ({insolvencias.length})</p>
                <ul className="space-y-1">
                  {insolvencias.slice(0, 5).map((processo, index) => (
                    <li key={`${processo.processo}-${index}`} className="flex items-center justify-between gap-3">
                      <span className="truncate">
                        {processo.especie || "processo"} {processo.processo ? `· ${processo.processo}` : ""}
                      </span>
                      <span className="shrink-0 text-muted-foreground">{formatDate(processo.data)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!dados.relacoes?.noticias?.length && (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-muted-foreground">
                  <Newspaper size={13} /> Menções públicas
                </p>
                <ul className="space-y-1">
                  {dados.relacoes.noticias.slice(0, 5).map((noticia, index) => (
                    <li key={index} className="truncate">
                      {noticia.url ? (
                        <a href={noticia.url} target="_blank" rel="noreferrer" className="hover:text-teal-200">
                          {noticia.titulo || noticia.url}
                        </a>
                      ) : (
                        noticia.titulo || "—"
                      )}
                      <span className="text-muted-foreground"> · {noticia.fonte || ""} {formatDate(noticia.data)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!dados.relacoes?.cargos_sociais?.length &&
              !dados.relacoes?.empresas?.length &&
              insolvencias.length === 0 &&
              !dados.relacoes?.noticias?.length && <EmptyState>Sem relações registadas na amostra.</EmptyState>}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function LinhaContrato({ item }: { item: RiscoContrato }) {
  const cor = item.risco?.cor || riscoCor(item.risco?.nivel);
  return (
    <tr className="border-t border-white/[0.06] align-top">
      <td className="py-2 pr-3 whitespace-nowrap">
        <span
          className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px]"
          style={{ borderColor: `${cor}55`, backgroundColor: `${cor}1a`, color: cor }}
          title={(item.risco?.razoes || []).join(" · ")}
        >
          {item.risco?.score?.toFixed(0) ?? "—"}
        </span>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{item.ano ?? "—"}</td>
      <td className="max-w-[420px] py-2 pr-3">
        <span className="line-clamp-2">{item.objeto || "—"}</span>
        {!!item.sinais?.length && (
          <span className="mt-1 block text-[10px] text-muted-foreground">{item.sinais.join(", ")}</span>
        )}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatEuro(item.valor)}</td>
      <td className="max-w-[220px] py-2 pr-3"><span className="line-clamp-2">{item.adjudicante || "—"}</span></td>
      <td className="max-w-[180px] py-2 pr-3"><span className="line-clamp-2 text-muted-foreground">{item.procedimento || "—"}</span></td>
      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{item.n_concorrentes ?? "—"}</td>
      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{item.z_cpv ? `${item.z_cpv.toFixed(1)}σ` : "—"}</td>
      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{formatRatio(item.ratio_efetivo)}</td>
    </tr>
  );
}
