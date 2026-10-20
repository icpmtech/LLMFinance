/**
 * Painel agregado do módulo ESG: médias, distribuições e destaques.
 *
 * Lê `/esg/analitica` e usa o mesmo cartão do modelo para os nomes e cores das
 * faixas. Quando o índice ainda está vazio, explica como o popular (pesquisar
 * uma empresa ou executar o cálculo em lote) em vez de mostrar zeros.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart3, Building2, Gauge, Landmark, Layers, Leaf, Loader2, RefreshCw, Target } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getEsgAnalitica } from "../../esgApi";
import type { EsgAnalitica, EsgEmpresaResumo, EsgMeta } from "../../esgApi";
import { EmptyState, Kpi, Loading, SectionCard } from "../padroes/padroesKit";
import { ESG_PILAR_CORES, EsgBadge, compactEuro, data, esgCor, num, pct } from "./esgKit";

function Destaques({ itens, onAbrir }: { itens?: EsgEmpresaResumo[]; onAbrir: (item: EsgEmpresaResumo) => void }) {
  if (!itens?.length) return <EmptyState>Sem empresas para destacar.</EmptyState>;
  return (
    <ul className="space-y-2">
      {itens.map((item) => (
        <li key={`${item.pais}-${item.nif}`}>
          <button
            onClick={() => onAbrir(item)}
            className="flex w-full items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-left transition hover:border-teal-400/30 hover:bg-teal-400/5"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm">{item.nome}</span>
              <span className="block truncate text-[11px] text-muted-foreground">
                {item.setor_label || "Setor n/d"} · {item.dimensao_label || "Dimensão n/d"}
              </span>
            </span>
            <EsgBadge score={item.score} nivel={item.nivel} nivelLabel={item.nivel_label} cor={item.cor} compact />
          </button>
        </li>
      ))}
    </ul>
  );
}

export function EsgPainel({ meta, onAbrir }: { meta: EsgMeta | null; onAbrir: (item: EsgEmpresaResumo) => void }) {
  const [dados, setDados] = useState<EsgAnalitica | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [pais, setPais] = useState("");
  const [setor, setSetor] = useState("");
  const [dimensao, setDimensao] = useState("");
  const [ano, setAno] = useState("");

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getEsgAnalitica({
      pais: pais || undefined,
      setor: setor || undefined,
      dimensao: dimensao || undefined,
      ano: ano ? Number(ano) : undefined,
    })
      .then(setDados)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível carregar o painel."))
      .finally(() => setCarregando(false));
  }, [pais, setor, dimensao, ano]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const pilares = useMemo(
    () => [
      { id: "e", label: "Ambiente", valor: dados?.media_pilares?.e ?? null },
      { id: "s", label: "Social", valor: dados?.media_pilares?.s ?? null },
      { id: "g", label: "Governação", valor: dados?.media_pilares?.g ?? null },
    ],
    [dados],
  );

  const setores = useMemo(
    () =>
      (dados?.setores || [])
        .filter((item) => item.setor)
        .map((item) => ({ ...item, curto: item.setor.length > 26 ? `${item.setor.slice(0, 24)}…` : item.setor })),
    [dados],
  );

  const niveis = useMemo(
    () =>
      (dados?.niveis || []).map((item) => ({
        ...item,
        label: item.label || item.id,
        cor: item.cor || esgCor(item.id),
      })),
    [dados],
  );

  if (carregando && !dados) {
    return <Loading label="A carregar o painel ESG…" />;
  }

  if (erro) {
    return (
      <div className="space-y-3">
        <EmptyState tone="warn">{erro}</EmptyState>
        <button onClick={carregar} className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm hover:text-foreground">
          <RefreshCw size={14} /> Tentar novamente
        </button>
      </div>
    );
  }

  if (!dados?.disponivel) {
    return (
      <div className="space-y-3">
        <EmptyState tone="warn">
          {dados?.motivo || "Ainda não há empresas no índice ESG."}
          {dados?.como_popular && <span className="mt-1 block">{dados.como_popular}</span>}
        </EmptyState>
        <p className="text-xs text-muted-foreground">
          O painel enche-se à medida que as empresas são calculadas: abra uma empresa em <strong>Empresas</strong> (a primeira
          consulta calcula e guarda) ou execute o cálculo em lote com sessão de administrador/gestor.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          País
          <select value={pais} onChange={(e) => setPais(e.target.value)} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
            <option value="">Todos</option>
            <option value="PT">Portugal</option>
            <option value="ES">Espanha</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          Setor (CAE)
          <select value={setor} onChange={(e) => setSetor(e.target.value)} className="max-w-[240px] rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
            <option value="">Todos</option>
            {(meta?.setores || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.id} · {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          Dimensão
          <select value={dimensao} onChange={(e) => setDimensao(e.target.value)} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
            <option value="">Todas</option>
            <option value="micro">Micro carteira</option>
            <option value="pequena">Pequena carteira</option>
            <option value="media">Média carteira</option>
            <option value="grande">Grande carteira</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          Ano
          <input value={ano} onChange={(e) => setAno(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="2026" className="w-24 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-2 text-sm text-foreground outline-none" />
        </label>
        <button onClick={carregar} className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
          {carregando ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Atualizar
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Building2} label="Empresas com fotografia ESG" value={num(dados.total)} sub={`${num(dados.niveis?.reduce((soma, item) => soma + item.n, 0))} nas faixas`} />
        <Kpi icon={Gauge} label="Score ESG médio" value={dados.media_score?.toFixed(1) ?? "—"} sub={`cobertura média ${pct(dados.media_cobertura, 0)}`} color="text-emerald-300" glow="glow-teal" />
        <Kpi icon={Leaf} label="Pilar Ambiente (média)" value={dados.media_pilares?.e?.toFixed(1) ?? "—"} sub={`Social ${dados.media_pilares?.s?.toFixed(1) ?? "—"} · Governação ${dados.media_pilares?.g?.toFixed(1) ?? "—"}`} color="text-teal-300" />
        <Kpi icon={Target} label="Última atualização" value={data(dados.ultima_atualizacao)} sub="fotografias no índice" color="text-sky-300" glow="glow-blue" />
      </div>

      {dados.taxonomia && (
        <SectionCard
          title="Taxonomia Europeia"
          subtitle="Elegibilidade face aos seis objetivos ambientais; alinhamento exige critérios técnicos, DNSH e salvaguardas verificadas."
          icon={Landmark}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Avaliadas</p>
              <p className="mt-1 font-mono text-xl">{num(dados.taxonomia.avaliadas)}</p>
              <p className="text-[10px] text-muted-foreground">{num(dados.taxonomia.sem_dados)} sem dados</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Elegíveis</p>
              <p className="mt-1 font-mono text-xl text-amber-300">{num(dados.taxonomia.elegiveis)}</p>
              <p className="text-[10px] text-muted-foreground">alinhamento por verificar</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Sem atividade elegível</p>
              <p className="mt-1 font-mono text-xl">{num(dados.taxonomia.alinhamento.find((item) => item.id === "nao_elegivel")?.n)}</p>
              <p className="text-[10px] text-muted-foreground">CAE/NACE sem correspondência</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Objetivos com empresas</p>
              <p className="mt-1 font-mono text-xl">{num(dados.taxonomia.objetivos.length)}/6</p>
              <p className="text-[10px] text-muted-foreground">contributo significativo potencial</p>
            </div>
          </div>
          {dados.taxonomia.objetivos.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {dados.taxonomia.objetivos.map((objetivo) => (
                <span
                  key={objetivo.id}
                  className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]"
                  style={{ borderColor: `${objetivo.cor}55`, backgroundColor: `${objetivo.cor}14`, color: objetivo.cor }}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: objetivo.cor }} />
                  {objetivo.id} · {objetivo.curto || objetivo.label} ({objetivo.n})
                </span>
              ))}
            </div>
          )}
        </SectionCard>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Média por pilar" subtitle="Escala 0–100; barras sem valor significam pilar sem dados." icon={BarChart3}>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={pilares} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "currentColor", opacity: 0.7 }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "#0b1116", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [`${Number(value).toFixed(1)}/100`, "Média"]} />
                <Bar dataKey="valor" radius={[8, 8, 0, 0]}>
                  {pilares.map((item) => (
                    <Cell key={item.id} fill={ESG_PILAR_CORES[item.id]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Distribuição por faixa" subtitle="Quantas empresas em cada nível do score." icon={Layers}>
          <div className="h-56">
            {niveis.length === 0 ? (
              <EmptyState>Sem faixas calculadas.</EmptyState>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={niveis} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: "currentColor", opacity: 0.7 }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0b1116", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [`${value} empresas`, "Nº"]} />
                  <Bar dataKey="n" radius={[8, 8, 0, 0]}>
                    {niveis.map((item) => (
                      <Cell key={item.id} fill={item.cor} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Score médio por setor" subtitle="Secção CAE (ou CPV dominante quando não há CAE)." icon={Building2}>
          <div className="h-64">
            {setores.length === 0 ? (
              <EmptyState>Sem setores com score.</EmptyState>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={setores} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: "currentColor", opacity: 0.6 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="curto" width={150} tick={{ fontSize: 10, fill: "currentColor", opacity: 0.7 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0b1116", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} formatter={(value) => [`${Number(value).toFixed(1)}/100`, "Média"]} />
                  <Bar dataKey="score_medio" radius={[0, 6, 6, 0]} fill="#2dd4bf" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Dimensões, distritos e anos" subtitle="Onde está o score e como se distribui a carteira." icon={Layers}>
          <div className="space-y-3 text-xs">
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Dimensão da carteira</p>
              <div className="flex flex-wrap gap-1.5">
                {(dados.dimensoes || []).map((item) => (
                  <span key={item.dimensao} className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1">
                    {item.dimensao} · <span className="font-mono">{item.score_medio?.toFixed(1) ?? "—"}</span> ({item.n})
                  </span>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Distrito</p>
              <div className="flex flex-wrap gap-1.5">
                {(dados.distritos || []).filter((item) => item.distrito).map((item) => (
                  <span key={item.distrito} className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1">
                    {item.distrito} · <span className="font-mono">{item.score_medio?.toFixed(1) ?? "—"}</span> ({item.n})
                  </span>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Ano de referência</p>
              <div className="flex flex-wrap gap-1.5">
                {(dados.anos || []).map((item) => (
                  <span key={item.ano} className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1">
                    {item.ano} · <span className="font-mono">{item.score_medio?.toFixed(1) ?? "—"}</span> ({item.n})
                  </span>
                ))}
              </div>
            </div>
            {dados.setores && dados.setores.length > 0 && (
              <div>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Cobertura por setor</p>
                <ul className="space-y-1">
                  {dados.setores.filter((item) => item.setor).slice(0, 6).map((item) => (
                    <li key={item.setor} className="flex justify-between gap-2">
                      <span className="truncate">{item.setor}</span>
                      <span className="font-mono text-muted-foreground">{pct(item.cobertura_media, 0)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Melhores scores" subtitle="Topo do ranking com os filtros ativos." icon={Leaf}>
          <Destaques itens={dados.destaques_positivos} onAbrir={onAbrir} />
        </SectionCard>
        <SectionCard title="Prioridades de análise" subtitle="Scores mais baixos — não é uma acusação, é onde olhar primeiro." icon={Gauge}>
          <Destaques itens={dados.destaques_negativos} onAbrir={onAbrir} />
        </SectionCard>
      </div>

      <p className="text-[11px] text-muted-foreground">
        {num(dados.total)} empresas · score médio {dados.media_score?.toFixed(1) ?? "—"} · cobertura média{" "}
        {pct(dados.media_cobertura, 0)} · valor total da amostra {compactEuro(dados.destaques_positivos?.reduce((soma, item) => soma + (item.valor || 0), 0))}.
        O painel agrega apenas fotografias já guardadas; abra uma empresa para calcular a primeira.
      </p>
    </div>
  );
}
