/**
 * Cartão do modelo, catálogo de indicadores, fontes e estado do módulo ESG.
 *
 * Um score sem os pressupostos à vista não se pode usar: aqui ficam os pesos,
 * os limiares, as fontes (internas, declaradas e de referência), o catálogo
 * GRI/ESRS e a taxonomia CPV que serve de proxy.
 */
import { useState } from "react";
import { BookOpen, Database, Globe2, Landmark, Leaf, ListChecks, Search, Server, ShieldCheck, SlidersHorizontal } from "lucide-react";

import type { EsgMeta } from "../../esgApi";
import { Chip, EmptyState, SectionCard } from "../padroes/padroesKit";
import { ESG_PILAR_CORES, data, num, pct } from "./esgKit";

const TIPOS: Record<string, { label: string; tone: string }> = {
  interna: { label: "Índice da plataforma", tone: "teal" },
  declarada: { label: "Declarada pela empresa", tone: "blue" },
  referencia: { label: "Fonte aberta de referência", tone: "neutral" },
};

export function EsgModelo({ meta }: { meta: EsgMeta | null }) {
  const [filtro, setFiltro] = useState("");
  if (!meta) return <EmptyState>Cartão do modelo indisponível.</EmptyState>;
  const cartao = meta.cartao_modelo;
  const indicadores = (meta.indicadores || []).filter((item) => {
    const texto = filtro.trim().toLowerCase();
    if (!texto) return true;
    return `${item.codigo} ${item.label} ${item.grupo}`.toLowerCase().includes(texto);
  });
  const porPilar = {
    e: indicadores.filter((item) => item.pilar === "e"),
    s: indicadores.filter((item) => item.pilar === "s"),
    g: indicadores.filter((item) => item.pilar === "g"),
  };

  return (
    <div className="space-y-4">
      <SectionCard title={`${cartao.rotulo} · ${cartao.versao}`} subtitle="Pilares, pesos e limiares do score." icon={SlidersHorizontal}>
        <p className="mb-4 rounded-xl border border-sky-400/20 bg-sky-400/5 px-3 py-2 text-[11px] text-sky-100">{cartao.aviso}</p>
        <div className="grid gap-4 lg:grid-cols-3">
          {cartao.pilares.map((pilar) => (
            <div key={pilar.id} className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
              <p className="flex items-center justify-between gap-2 text-sm font-medium" style={{ color: ESG_PILAR_CORES[pilar.id] }}>
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ESG_PILAR_CORES[pilar.id] }} />
                  {pilar.label}
                </span>
                <span className="font-mono text-xs text-muted-foreground">peso {pct(pilar.peso, 0)}</span>
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">{pilar.descricao}</p>
              <ul className="mt-3 space-y-2">
                {pilar.componentes.map((componente) => (
                  <li key={componente.id} className="rounded-lg border border-white/5 bg-white/[0.02] p-2 text-[11px]">
                    <div className="flex items-start justify-between gap-2">
                      <span>{componente.label}</span>
                      <span className="shrink-0 font-mono text-muted-foreground">{pct(componente.peso, 0)}</span>
                    </div>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{componente.metodo}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                      {componente.melhor >= componente.pior
                        ? `${componente.pior} → ${componente.melhor} (${componente.unidade})`
                        : `${componente.pior} → ${componente.melhor} (menor é melhor)`}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {cartao.niveis.map((nivel) => (
            <div key={nivel.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="flex items-center gap-2 text-xs" style={{ color: nivel.cor }}>
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: nivel.cor }} />
                {nivel.label}
              </p>
              <p className="mt-1 font-mono text-lg">{nivel.min.toFixed(0)}+</p>
              <p className="text-[10px] text-muted-foreground">score mínimo</p>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Fontes de dados" subtitle="O que é lido internamente, o que é declarado e o que é referência." icon={Database}>
        <div className="grid gap-2 md:grid-cols-2">
          {(meta.fontes || []).map((fonte) => {
            const tipo = TIPOS[fonte.tipo] || { label: fonte.tipo, tone: "neutral" };
            return (
              <div key={fonte.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium">{fonte.label}</span>
                  <Chip tone={tipo.tone}>{tipo.label}</Chip>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">{fonte.uso}</p>
                {fonte.url && (
                  <a href={fonte.url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[10px] text-sky-300 hover:underline">
                    {fonte.url}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </SectionCard>

      <SectionCard title="Enquadramento europeu e IAPMEI" subtitle="Taxonomia UE, ODS, normas de relato e percurso de alinhamento." icon={Landmark}>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="flex items-center gap-2 text-xs font-medium text-emerald-200"><Landmark size={14} /> Taxonomia Europeia</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {num(meta.taxonomia?.total_atividades)} atividades oficiais, {num(meta.taxonomia?.objetivos?.length)} objetivos ambientais e{" "}
              {num(meta.taxonomia?.salvaguardas?.length)} salvaguardas mínimas. Fonte: {meta.taxonomia?.fonte?.label}.
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {(meta.taxonomia?.objetivos || []).map((objetivo) => (
                <Chip key={objetivo.id} tone="neutral" title={objetivo.label}>{objetivo.id} · {objetivo.curto}</Chip>
              ))}
            </div>
            <a href={meta.taxonomia?.fonte?.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-[10px] text-sky-300 hover:underline">
              {meta.taxonomia?.fonte?.url}
            </a>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="flex items-center gap-2 text-xs font-medium text-sky-200"><ShieldCheck size={14} /> Salvaguardas e DNSH</p>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              {(meta.taxonomia?.salvaguardas || []).map((item) => (
                <div key={item.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1 text-[10px]">
                  <p className="font-medium">{item.label}</p>
                  <p className="truncate text-muted-foreground" title={item.descricao}>{item.descricao}</p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[10px] text-muted-foreground">
              O módulo acompanha indicadores declarados; não substitui os critérios técnicos nem a verificação oficial.
            </p>
          </div>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="flex items-center gap-2 text-xs font-medium text-violet-200"><Globe2 size={14} /> ODS</p>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              {(meta.taxonomia?.ods || []).map((ods) => (
                <div key={ods.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1 text-[10px]">
                  <p style={{ color: ods.cor }}>ODS {ods.id} · {ods.label}</p>
                  <p className="truncate text-muted-foreground">{ods.grupos.join(" · ")}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="flex items-center gap-2 text-xs font-medium text-amber-200"><BookOpen size={14} /> Normas de relato</p>
            <div className="mt-2 space-y-1">
              {(meta.taxonomia?.normas_relato || []).map((norma) => (
                <a key={norma.id} href={norma.url} target="_blank" rel="noreferrer" className="block rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1 text-[10px] hover:border-sky-400/30">
                  <p className="flex items-center justify-between gap-2"><span>{norma.label}</span><span className="text-muted-foreground">{norma.ambito}</span></p>
                  <p className="truncate text-muted-foreground">{norma.uso}</p>
                </a>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <p className="flex items-center gap-2 text-xs font-medium text-teal-200"><ListChecks size={14} /> Percurso IAPMEI / UN Global Compact</p>
          <div className="mt-2 grid gap-1 md:grid-cols-5">
            {(meta.taxonomia?.passos || []).map((passo) => (
              <div key={passo.id} className="rounded-lg border border-white/5 bg-white/[0.02] p-2 text-[10px]">
                <p className="font-mono text-[9px] text-emerald-300">PASSO {passo.id}</p>
                <p className="font-medium">{passo.label}</p>
                <p className="mt-0.5 text-muted-foreground">{passo.descricao}</p>
                <p className="mt-1 text-sky-200/80">{passo.no_iqos}</p>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Catálogo de indicadores declarados"
        subtitle={`${num(meta.indicadores?.length)} indicadores; a ingestão valida o código e o score usa apenas os pontuáveis.`}
        icon={BookOpen}
        actions={
          <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-2.5 py-1.5">
            <Search size={13} className="text-muted-foreground" />
            <input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="Filtrar código, nome ou grupo" className="w-52 bg-transparent text-xs outline-none placeholder:text-muted-foreground/60" />
          </div>
        }
      >
        {indicadores.length === 0 ? (
          <EmptyState>Nenhum indicador corresponde ao filtro.</EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-3">
            {(["e", "s", "g"] as const).map((pilar) => (
              <div key={pilar}>
                <p className="mb-2 flex items-center gap-2 text-xs font-medium" style={{ color: ESG_PILAR_CORES[pilar] }}>
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ESG_PILAR_CORES[pilar] }} />
                  {pilar === "e" ? "Ambiente" : pilar === "s" ? "Social" : "Governação"}
                  <span className="text-[10px] text-muted-foreground">({porPilar[pilar].length})</span>
                </p>
                <ul className="space-y-1.5">
                  {porPilar[pilar].map((item) => (
                    <li key={item.codigo} className="rounded-lg border border-white/5 bg-white/[0.02] p-2 text-[11px]" title={item.descricao}>
                      <p className="flex items-start justify-between gap-2">
                        <span>{item.label}</span>
                        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{item.unidade}</span>
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{item.codigo}</p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {item.pontuavel
                          ? item.melhor !== null && item.pior !== null && item.melhor < item.pior
                            ? `menor é melhor (${item.pior} → ${item.melhor})`
                            : `maior é melhor (${item.pior} → ${item.melhor})`
                          : "indicador de contexto (não pontua)"}
                        {item.fonte_sugerida ? ` · ${item.fonte_sugerida}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Taxonomia CPV usada como proxy" subtitle="Sinais de ambiente, social e economia circular por divisão CPV." icon={Leaf}>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="sticky top-0 bg-[#0b1116] text-[10px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-white/10">
                <th className="py-2 pr-3">Divisão</th>
                <th className="py-2 pr-3">Descrição</th>
                <th className="py-2 pr-3">Sinais</th>
              </tr>
            </thead>
            <tbody>
              {(meta.cpv_taxonomia || []).map((item) => (
                <tr key={item.divisao} className="border-b border-white/5">
                  <td className="py-1.5 pr-3 font-mono text-[11px]">{item.divisao}</td>
                  <td className="py-1.5 pr-3 text-[11px]">{item.label}</td>
                  <td className="py-1.5 pr-3">
                    <div className="flex flex-wrap gap-1">
                      {item.verde && <Chip tone="teal">verde</Chip>}
                      {item.social && <Chip tone="blue">social</Chip>}
                      {item.circular && <Chip tone="violet">circular</Chip>}
                      {item.marrom && <Chip tone="rose">carbónico</Chip>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Estado do módulo" subtitle="Índices, última fotografia e execuções." icon={Server}>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            {Object.entries(meta.status?.indices || {}).map(([nome, info]) => (
              <div key={nome} className="flex items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px]">
                <span className="font-mono">{nome}</span>
                <span className="text-muted-foreground">
                  {info.existe ? `${num(info.total)} documento(s)` : "não criado"} {info.erro ? `· ${info.erro}` : ""}
                </span>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3 text-[11px] text-muted-foreground">
            <p>Modelo <span className="font-mono text-foreground">{meta.status?.modelo_versao}</span></p>
            <p className="mt-1">Última fotografia: {data(meta.status?.ultima_atualizacao)}</p>
            <p className="mt-1">Índice principal: <span className="font-mono">finance_esg_empresas</span></p>
            <p className="mt-1">Indicadores: <span className="font-mono">finance_esg_indicadores</span></p>
            <p className="mt-1">Execuções: <span className="font-mono">finance_esg_recolhas</span></p>
            <p className="mt-2 text-[10px]">A leitura é pública; a ingestão de indicadores e o cálculo em lote exigem sessão com escrita no módulo ESG.</p>
          </div>
        </div>
        {(meta.status?.ultimas_execucoes || []).length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr className="border-b border-white/10">
                  <th className="py-2 pr-3">Tipo</th>
                  <th className="py-2 pr-3">Estado</th>
                  <th className="py-2 pr-3">Total</th>
                  <th className="py-2 pr-3">Processados</th>
                  <th className="py-2 pr-3">Erros</th>
                  <th className="py-2">Início</th>
                </tr>
              </thead>
              <tbody>
                {(meta.status?.ultimas_execucoes || []).map((item, index) => {
                  const exec = item as Record<string, unknown>;
                  return (
                    <tr key={String(exec.run_id || index)} className="border-b border-white/5 text-[11px]">
                      <td className="py-1.5 pr-3">{String(exec.tipo || "—")}</td>
                      <td className="py-1.5 pr-3">{String(exec.estado || "—")}</td>
                      <td className="py-1.5 pr-3 font-mono">{String(exec.total ?? "—")}</td>
                      <td className="py-1.5 pr-3 font-mono">{String(exec.processados ?? "—")}</td>
                      <td className="py-1.5 pr-3 font-mono">{String(exec.erros ?? "—")}</td>
                      <td className="py-1.5">{data(String(exec.iniciado_em || ""))}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
