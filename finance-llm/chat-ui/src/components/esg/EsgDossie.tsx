/**
 * Dossiê ESG de uma empresa: score, pilares, evolução, indicadores, contratos
 * e carteira de fornecedores.
 *
 * O número não vem sozinho: cada componente mostra a evidência e o método, e o
 * benchmark só aparece quando há pares suficientes (mínimo definido no cartão).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  Building2,
  Calendar,
  CheckCircle2,
  FileText,
  Globe2,
  Info,
  Landmark,
  Layers,
  Leaf,
  Package,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getEsgEmpresa, getEsgFornecedores } from "../../esgApi";
import type { EsgCarteira, EsgEmpresa, EsgMeta, EsgTaxonomiaEmpresa } from "../../esgApi";
import { Chip, EmptyState, Kpi, Loading, SectionCard } from "../padroes/padroesKit";
import { CarteiraResultado } from "./EsgCarteira";
import {
  AvisoEsg,
  BenchmarkEsg,
  Bloco,
  ComponentesEsg,
  EsgBadge,
  EsgGauge,
  ESG_PILAR_CORES,
  FatoresEsg,
  PilarBars,
  compactEuro,
  data,
  euros,
  num,
  pct,
} from "./esgKit";

type Aba = "visao" | "componentes" | "historico" | "indicadores" | "taxonomia" | "contratos" | "fornecedores";

const ABAS: { id: Aba; label: string }[] = [
  { id: "visao", label: "Visão geral" },
  { id: "componentes", label: "Componentes" },
  { id: "historico", label: "Evolução" },
  { id: "indicadores", label: "Indicadores declarados" },
  { id: "taxonomia", label: "Taxonomia UE" },
  { id: "contratos", label: "Contratos" },
  { id: "fornecedores", label: "Fornecedores" },
];

function LinhaIndicador({ label, valor, unidade, pontos }: { label: string; valor: number; unidade?: string | null; pontos?: number | null }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-2 text-[11px]">
      <span className="min-w-0 truncate text-muted-foreground" title={label}>{label}</span>
      <span className="shrink-0 font-mono">
        {num(valor, 1)} <span className="text-[10px] text-muted-foreground">{unidade || ""}</span>
        {pontos !== null && pontos !== undefined && <span className="ml-1 text-[10px] text-muted-foreground">({pontos.toFixed(0)}/100)</span>}
      </span>
    </div>
  );
}

function SecaoTaxonomia({ tax }: { tax: EsgTaxonomiaEmpresa }) {
  const tone = tax.alinhamento === "elegivel_nao_verificado" ? "amber" : tax.alinhamento === "nao_elegivel" ? "rose" : "neutral";
  return (
    <div className="space-y-4">
      <SectionCard
        title="Taxonomia UE — elegibilidade"
        subtitle={`CAE/NACE ${tax.nace || "n/d"} · ${tax.match === "nace" ? "correspondência por CAE/NACE" : tax.match === "setor" ? "proxy pelo setor/CPV" : "sem correspondência"}`}
        icon={Landmark}
        actions={
          <a href={tax.url_compass} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-sky-300 hover:underline">
            Compass <ArrowUpRight size={11} />
          </a>
        }
      >
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
          <div>
            <p className="text-[11px] text-muted-foreground">Estado</p>
            <p className="text-sm font-medium">{tax.alinhamento_label}</p>
          </div>
          <Chip tone={tone}>{tax.elegivel ? `${num(tax.n_atividades)} atividade(s) elegível(is)` : "sem atividade elegível"}</Chip>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Objetivos</p>
            <p className="mt-1 font-mono text-xl">{num(tax.objetivos?.length)}/6</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Verificação</p>
            <p className="mt-1 font-mono text-xl">{pct(tax.cobertura_verificacao, 0)}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">ODS com evidência</p>
            <p className="mt-1 font-mono text-xl">{num(tax.ods?.length)}</p>
          </div>
        </div>
        {tax.objetivos?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tax.objetivos.map((objetivo) => (
              <span key={objetivo.id} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: `${objetivo.cor}55`, backgroundColor: `${objetivo.cor}14`, color: objetivo.cor }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: objetivo.cor }} />
                {objetivo.id} · {objetivo.curto || objetivo.label}
              </span>
            ))}
          </div>
        )}
        <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[10.5px] text-amber-100">
          <p className="flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>{tax.avisos?.[0] || "Elegibilidade não é alinhamento: os critérios técnicos, o DNSH e as salvaguardas têm de ser verificados."}</span>
          </p>
        </div>
      </SectionCard>

      {tax.atividades?.length > 0 && (
        <SectionCard title="Atividades elegíveis" subtitle="Lista oficial do EU Taxonomy Compass para o CAE/NACE desta empresa." icon={Layers}>
          <div className="max-h-[360px] overflow-auto rounded-xl border border-white/10">
            <table className="w-full min-w-[560px] text-left text-[11px]">
              <thead className="sticky top-0 bg-[#0b1116] text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr className="border-b border-white/10">
                  <th className="px-2 py-1.5">Atividade</th>
                  <th className="px-2 py-1.5">Setor</th>
                  <th className="px-2 py-1.5">NACE</th>
                  <th className="px-2 py-1.5">Objetivos</th>
                </tr>
              </thead>
              <tbody>
                {tax.atividades.map((atividade) => (
                  <tr key={atividade.id} className="border-b border-white/5 last:border-0">
                    <td className="max-w-[260px] px-2 py-1.5">
                      <a href={atividade.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 hover:text-sky-300">
                        <span className="line-clamp-2">{atividade.nome}</span>
                        <ArrowUpRight size={10} className="mt-0.5 shrink-0" />
                      </a>
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">{atividade.setor}</td>
                    <td className="px-2 py-1.5 font-mono text-[10px] text-muted-foreground">{atividade.nace_match || atividade.nace.slice(0, 2).join(", ") || "—"}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {atividade.objetivos.map((objetivo) => (
                          <Chip key={`${atividade.id}-${objetivo.id}`} tone="neutral">{objetivo.id} · {objetivo.curto || objetivo.label}</Chip>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="DNSH — sem prejuízo significativo" subtitle="Indicadores declarados que o módulo consegue associar a cada objetivo." icon={ShieldCheck}>
          <div className="space-y-1">
            {(tax.dnsh || []).map((item) => (
              <div key={item.objetivo} className="flex items-center justify-between gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5 text-[10.5px]">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: item.cor }} />
                  <span className="truncate">{item.label}</span>
                </span>
                <Chip tone={item.status === "com indicador" ? "teal" : "neutral"}>{item.status === "com indicador" ? `${item.indicadores.length} indicador(es)` : "sem evidência"}</Chip>
              </div>
            ))}
          </div>
        </SectionCard>
        <SectionCard title="Salvaguardas mínimas" subtitle="Direitos humanos, trabalho, anticorrupção e fiscalidade." icon={CheckCircle2}>
          <div className="space-y-1">
            {(tax.salvaguardas || []).map((item) => (
              <div key={item.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5 text-[10.5px]" title={item.descricao}>
                <div className="flex items-center justify-between gap-2">
                  <span>{item.label}</span>
                  <Chip tone={item.status === "sem evidência" ? "rose" : item.status === "evidência parcial" ? "teal" : "amber"}>{item.status}</Chip>
                </div>
                {item.indicadores.length > 0 && <p className="mt-0.5 truncate font-mono text-[9.5px] text-muted-foreground">{item.indicadores.join(" · ")}</p>}
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      {(tax.ods?.length > 0 || tax.materialidade?.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {tax.ods?.length > 0 && (
            <SectionCard title="ODS com evidência" subtitle="Objetivos de Desenvolvimento Sustentável ligados aos indicadores declarados." icon={Globe2}>
              <div className="flex flex-wrap gap-1.5">
                {tax.ods.map((ods) => (
                  <span key={ods.id} className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: `${ods.cor}55`, backgroundColor: `${ods.cor}14`, color: ods.cor }}>
                    ODS {ods.id} · {ods.label}
                  </span>
                ))}
              </div>
            </SectionCard>
          )}
          {tax.materialidade?.length > 0 && (
            <SectionCard title="Temas materiais" subtitle="Ponto de partida do passo 2 do percurso IAPMEI." icon={Target}>
              <div className="flex flex-wrap gap-1.5">
                {tax.materialidade.map((tema) => (
                  <Chip key={tema.tema} tone={tema.relevancia === "alta" ? "amber" : "neutral"} title={tema.origem}>{tema.tema}</Chip>
                ))}
              </div>
            </SectionCard>
          )}
        </div>
      )}
    </div>
  );
}

export function EsgDossie({
  nif,
  pais,
  nome,
  meta,
  onVoltar,
  onAbrirEmpresa,
}: {
  nif: string;
  pais: string;
  nome?: string;
  meta: EsgMeta | null;
  onVoltar?: () => void;
  onAbrirEmpresa?: (nif: string, nome: string, pais: string) => void;
}) {
  const [doc, setDoc] = useState<EsgEmpresa | null>(null);
  const [aba, setAba] = useState<Aba>("visao");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [fornecedores, setFornecedores] = useState<EsgCarteira | null>(null);
  const [carregandoFornecedores, setCarregandoFornecedores] = useState(false);
  const [erroFornecedores, setErroFornecedores] = useState("");

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getEsgEmpresa(pais, nif, { incluir_fornecedores: false, historico_anos: 3 })
      .then((resposta) => {
        setDoc(resposta);
        setFornecedores(null);
        setErroFornecedores("");
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível abrir o dossiê ESG."))
      .finally(() => setCarregando(false));
  }, [pais, nif]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const carregarFornecedores = useCallback(() => {
    if (!doc) return;
    setCarregandoFornecedores(true);
    setErroFornecedores("");
    getEsgFornecedores(pais, nif, { limite: 500, calcular_em_falta: true, max_calcular: 12 })
      .then(setFornecedores)
      .catch((exc: unknown) => setErroFornecedores(exc instanceof Error ? exc.message : "Não foi possível carregar os fornecedores."))
      .finally(() => setCarregandoFornecedores(false));
  }, [doc, pais, nif]);

  const serie = useMemo(() => {
    if (!doc) return [];
    return (doc.historico || [])
      .slice()
      .sort((a, b) => a.ano - b.ano)
      .map((item) => ({
        ano: String(item.ano),
        score: item.score,
        pares: doc.benchmark?.historico_pares?.[item.ano] ?? null,
        e: item.pilares?.e ?? null,
        s: item.pilares?.s ?? null,
        g: item.pilares?.g ?? null,
      }));
  }, [doc]);

  const indicadoresPorPilar = useMemo(() => {
    type Linha = import("../../esgApi").EsgIndicadorValor & { pontos?: number | null };
    const mapa: Record<"e" | "s" | "g", Linha[]> = { e: [], s: [], g: [] };
    if (!doc) return mapa;
    const catalogo = new Map((meta?.indicadores || []).map((item) => [item.codigo, item]));
    for (const valor of doc.indicadores?.valores || []) {
      const def = catalogo.get(valor.codigo);
      const pilar = (def?.pilar || valor.pilar || "g") as "e" | "s" | "g";
      const pontos = doc.indicadores?.score?.[pilar]?.detalhes?.find((item) => item.codigo === valor.codigo)?.pontos ?? null;
      mapa[pilar].push({ ...valor, label: def?.label || valor.label, unidade: def?.unidade || valor.unidade, pontos });
    }
    return mapa;
  }, [doc, meta]);

  if (carregando && !doc) return <Loading label="A calcular o dossiê ESG…" />;
  if (erro && !doc) {
    return (
      <div className="space-y-3">
        <EmptyState tone="warn">{erro}</EmptyState>
        <div className="flex gap-2">
          {onVoltar && <button onClick={onVoltar} className="rounded-xl border border-white/10 px-3 py-2 text-sm">Voltar</button>}
          <button onClick={carregar} className="rounded-xl border border-white/10 px-3 py-2 text-sm">Tentar novamente</button>
        </div>
      </div>
    );
  }
  if (!doc) return null;

  const empresa = doc.empresa || doc;
  const cartao = doc.cartao_modelo || meta?.cartao_modelo;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {onVoltar && (
            <button onClick={onVoltar} className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              <ArrowLeft size={13} /> Voltar à pesquisa
            </button>
          )}
          <h2 className="text-xl font-semibold">{doc.name || nome || nif}</h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <span className="font-mono">{doc.pais} · {doc.nif}</span>
            <span>·</span>
            <span>{doc.setor_label || "Setor n/d"}{doc.setor_fonte ? ` (${doc.setor_fonte})` : ""}</span>
            <span>·</span>
            <span>{doc.dimensao_label || "Dimensão n/d"}</span>
            {doc.cae_principal && <><span>·</span><span>CAE {doc.cae_principal}</span></>}
            {empresa.devedor && <Chip tone="rose">lista de devedores</Chip>}
            {(empresa.insolvencias || 0) > 0 && <Chip tone="rose">CIRE</Chip>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <EsgBadge score={doc.score} nivel={doc.nivel} nivelLabel={doc.nivel_label} cor={doc.cor} />
          <Chip tone={doc.confianca === "alta" ? "teal" : doc.confianca === "média" ? "blue" : "amber"}>
            confiança {doc.confianca}
          </Chip>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {ABAS.map((item) => (
          <button
            key={item.id}
            onClick={() => setAba(item.id)}
            className={`rounded-xl px-3 py-2 text-sm transition ${aba === item.id ? "glass-card border-teal-400/25 bg-teal-400/10 text-teal-200" : "glass-card text-muted-foreground hover:text-foreground"}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {aba === "visao" && (
        <div className="space-y-4">
          <SectionCard title="Score ESG" subtitle={`Modelo ${doc.modelo_versao} · ano de referência ${doc.ano} · ${doc.contratos} contrato(s) e ${compactEuro(doc.valor)} na base.`} icon={Leaf}>
            <div className="grid gap-5 lg:grid-cols-[200px_1fr]">
              <div className="flex flex-col items-center gap-2">
                <EsgGauge score={doc.score} nivelLabel={doc.nivel_label} cor={doc.cor} cobertura={doc.cobertura} />
                <p className="text-center text-[11px] text-muted-foreground">
                  {doc.confianca === "sem dados" ? "Sem dados suficientes" : `Confiança ${doc.confianca}`} · {doc.score_detalhe?.n_indicadores ?? 0} indicador(es) declarado(s)
                </p>
              </div>
              <div className="space-y-3">
                <PilarBars pilares={doc.pilares_detalhe || []} />
                <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3 text-[11px] text-muted-foreground">
                  <p className="flex items-center gap-1.5">
                    <Info size={13} className="text-sky-300" />
                    O score global renormaliza pelos pilares com dados. {pct(doc.cobertura, 0)} de cobertura significa que os restantes
                    componentes não entraram — não que valham zero.
                  </p>
                  <p className="mt-1">{cartao?.aviso}</p>
                </div>
              </div>
            </div>
          </SectionCard>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi icon={Building2} label="Contratos na base" value={num(doc.contratos)} sub={`${num(doc.adjudicantes)} compradores distintos`} />
            <Kpi icon={Package} label="Valor contratado" value={compactEuro(doc.valor)} sub={`${num(empresa.contratos_registados ?? doc.contratos)} registados no cadastro`} color="text-sky-300" glow="glow-blue" />
            <Kpi icon={Users} label="Fornecedores (como comprador)" value={doc.fornecedores_count === null || doc.fornecedores_count === undefined ? "—" : num(doc.fornecedores_count)} sub="carteira analisada no separador" color="text-violet-300" />
            <Kpi icon={Calendar} label="Atualizado" value={data(doc.atualizado_em)} sub={`ano ${doc.ano} · ${doc.anos} anos de série`} color="text-teal-300" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Benchmark de pares" subtitle="Mesmo setor (CAE) e mesma dimensão de carteira." icon={BarChart3}>
              <BenchmarkEsg benchmark={doc.benchmark} />
            </SectionCard>
            <SectionCard title="O que puxa o score" subtitle="Contributo de cada componente face a uma base de 50 pontos." icon={Leaf}>
              <FatoresEsg fatores={doc.score_detalhe?.fatores || []} />
            </SectionCard>
          </div>

          {doc.avisos?.length > 0 && (
            <SectionCard title="Avisos de leitura" subtitle="O que falta e o que deve ser tido em conta." icon={Info}>
              <div className="space-y-1.5">
                {doc.avisos.map((aviso, index) => (
                  <p key={index} className="flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-100">
                    <Info size={13} className="mt-0.5 shrink-0 text-amber-300" />
                    {aviso}
                  </p>
                ))}
              </div>
            </SectionCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Principais CPV" subtitle="Peso no valor da carteira." icon={Package}>
              {(doc.evidencias?.cpv_top || []).length === 0 ? (
                <EmptyState>Sem CPV registados.</EmptyState>
              ) : (
                <ul className="space-y-2">
                  {(doc.evidencias?.cpv_top || []).map((item) => (
                    <li key={`${item.divisao}-${item.label}`} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="min-w-0 truncate" title={item.label}><span className="font-mono text-muted-foreground">{item.divisao}</span> · {item.label}</span>
                      <span className="shrink-0 font-mono text-muted-foreground">{pct(item.peso, 1)} · {compactEuro(item.valor)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            <SectionCard title="Principais compradores" subtitle="Concentração da carteira." icon={Building2}>
              {(doc.evidencias?.compradores || []).length === 0 ? (
                <EmptyState>Sem compradores registados.</EmptyState>
              ) : (
                <ul className="space-y-2">
                  {(doc.evidencias?.compradores || []).map((item) => (
                    <li key={item.nif || item.nome || "comprador"} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="min-w-0 truncate" title={item.nome || undefined}>{item.nome || item.nif || "—"}</span>
                      <span className="shrink-0 font-mono text-muted-foreground">{pct(item.peso, 1)} · {compactEuro(item.valor)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          </div>
        </div>
      )}

      {aba === "componentes" && (
        <SectionCard title="Componentes do score" subtitle="Cada barra é um componente; a evidência mostra o valor que a sustenta." icon={Leaf}>
          <ComponentesEsg componentes={doc.componentes || []} />
        </SectionCard>
      )}

      {aba === "historico" && (
        <div className="space-y-4">
          <SectionCard title="Evolução do score" subtitle="Série de três anos e mediana dos pares (quando há amostra)." icon={BarChart3}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={serie} margin={{ top: 8, right: 14, bottom: 0, left: -20 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="ano" tick={{ fontSize: 11, fill: "currentColor", opacity: 0.7 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0b1116", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="score" name="Empresa" stroke="#2dd4bf" strokeWidth={2} connectNulls />
                  <Line type="monotone" dataKey="pares" name="Mediana dos pares" stroke="#94a3b8" strokeDasharray="4 4" strokeWidth={1.5} connectNulls />
                  <Line type="monotone" dataKey="e" name="Ambiente" stroke={ESG_PILAR_CORES.e} strokeWidth={1.2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="s" name="Social" stroke={ESG_PILAR_CORES.s} strokeWidth={1.2} dot={false} connectNulls />
                  <Line type="monotone" dataKey="g" name="Governação" stroke={ESG_PILAR_CORES.g} strokeWidth={1.2} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </SectionCard>
          <SectionCard title="Tabela da série" subtitle="Score, pilares, contratos e indicadores por ano." icon={Calendar}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-white/10">
                    <th className="py-2 pr-3">Ano</th>
                    <th className="py-2 pr-3">Score</th>
                    <th className="py-2 pr-3">E</th>
                    <th className="py-2 pr-3">S</th>
                    <th className="py-2 pr-3">G</th>
                    <th className="py-2 pr-3">Cobertura</th>
                    <th className="py-2 pr-3">Contratos</th>
                    <th className="py-2 pr-3">Valor</th>
                    <th className="py-2">Indicadores</th>
                  </tr>
                </thead>
                <tbody>
                  {(doc.historico || []).map((item) => (
                    <tr key={item.ano} className="border-b border-white/5">
                      <td className="py-2 pr-3 font-mono text-[11px]">{item.ano}</td>
                      <td className="py-2 pr-3"><EsgBadge score={item.score} nivel={item.nivel} nivelLabel={item.nivel_label} compact /></td>
                      <td className="py-2 pr-3 font-mono text-[11px]">{item.pilares?.e?.toFixed(0) ?? "—"}</td>
                      <td className="py-2 pr-3 font-mono text-[11px]">{item.pilares?.s?.toFixed(0) ?? "—"}</td>
                      <td className="py-2 pr-3 font-mono text-[11px]">{item.pilares?.g?.toFixed(0) ?? "—"}</td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{pct(item.cobertura, 0)}</td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{num(item.contratos)}</td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{compactEuro(item.valor)}</td>
                      <td className="py-2 text-[11px] text-muted-foreground">{num(item.n_indicadores)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>
      )}

      {aba === "indicadores" && (
        <div className="space-y-4">
          {(!doc.indicadores?.valores || doc.indicadores.valores.length === 0) ? (
            <EmptyState tone="warn">
              A empresa ainda não tem indicadores de relatórios de sustentabilidade no índice. Os componentes de emissões, formação,
              acidentes e governance ficam indisponíveis até serem ingeridos (GRI/ESRS) — não são inventados.
            </EmptyState>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                {(["e", "s", "g"] as const).map((pilar) => (
                  <div key={pilar} className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                    <p className="flex items-center gap-2 text-xs" style={{ color: ESG_PILAR_CORES[pilar] }}>
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ESG_PILAR_CORES[pilar] }} />
                      {pilar === "e" ? "Ambiente" : pilar === "s" ? "Social" : "Governação"}
                    </p>
                    <p className="mt-1 font-mono text-2xl">{doc.indicadores.score?.[pilar]?.score?.toFixed(1) ?? "—"}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {num(doc.indicadores.score?.[pilar]?.n)} indicador(es) · {pilar === "e" ? "emissões, energia, água e resíduos" : pilar === "s" ? "emprego, formação, segurança e diversidade" : "conselho, ética, denúncias e transparência"}
                    </p>
                  </div>
                ))}
              </div>
              <div className="grid gap-4 lg:grid-cols-3">
                {(["e", "s", "g"] as const).map((pilar) => (
                  <Bloco key={pilar} title={pilar === "e" ? "Ambiente" : pilar === "s" ? "Social" : "Governação"}>
                    {(indicadoresPorPilar[pilar] || []).length === 0 ? (
                      <EmptyState>Sem indicadores deste pilar.</EmptyState>
                    ) : (
                      <div className="space-y-1.5">
                        {(indicadoresPorPilar[pilar] || []).map((item) => (
                          <LinhaIndicador key={`${item.codigo}-${item.fonte || ""}`} label={item.label || item.codigo} valor={item.valor} unidade={item.unidade} pontos={item.pontos ?? null} />
                        ))}
                      </div>
                    )}
                  </Bloco>
                ))}
              </div>
              <SectionCard title="Fontes dos indicadores" subtitle={`Ano ${doc.indicadores.ano} · ${doc.indicadores.fontes.length} fonte(s).`} icon={FileText}>
                <div className="flex flex-wrap gap-2">
                  {(doc.indicadores.fontes || []).map((fonte) => (
                    <Chip key={fonte} tone="blue">{fonte}</Chip>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Os indicadores declarados são da responsabilidade de quem os publica. A verificação externa é assinalada na ingestão
                  e tem precedência sobre a declaração simples.
                </p>
              </SectionCard>
            </>
          )}
        </div>
      )}

      {aba === "taxonomia" && (
        doc.taxonomia ? (
          <SecaoTaxonomia tax={doc.taxonomia} />
        ) : (
          <EmptyState tone="warn">
            A empresa ainda não tem leitura de Taxonomia UE. Recalcule o dossiê para gerar a ligação ao CAE/NACE e às atividades do Compass.
          </EmptyState>
        )
      )}

      {aba === "contratos" && (
        <SectionCard title="Contratos que sustentam a leitura" subtitle={`${num(doc.contratos)} contrato(s) no ano ${doc.ano}; os maiores estão listados primeiro.`} icon={FileText}>
          {(doc.evidencias?.contratos || []).length === 0 ? (
            <EmptyState>Sem contratos registados para esta empresa.</EmptyState>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-white/10">
                    <th className="py-2 pr-3">Ano</th>
                    <th className="py-2 pr-3">Objeto</th>
                    <th className="py-2 pr-3">Comprador</th>
                    <th className="py-2 pr-3">CPV</th>
                    <th className="py-2 pr-3">Valor</th>
                    <th className="py-2 pr-3">Sinais</th>
                  </tr>
                </thead>
                <tbody>
                  {(doc.evidencias?.contratos || []).map((item) => (
                    <tr key={item.id || `${item.objeto}-${item.valor}`} className="border-b border-white/5">
                      <td className="py-2 pr-3 font-mono text-[11px]">{item.ano ?? "—"}</td>
                      <td className="max-w-[320px] py-2 pr-3">
                        <span className="block truncate text-[12px]" title={item.objeto || undefined}>{item.objeto || "—"}</span>
                        <span className="text-[10px] text-muted-foreground">{item.procedimento || "procedimento n/d"}</span>
                      </td>
                      <td className="max-w-[220px] truncate py-2 pr-3 text-[11px] text-muted-foreground" title={item.adjudicante || undefined}>{item.adjudicante || "—"}</td>
                      <td className="max-w-[180px] truncate py-2 pr-3 text-[11px] text-muted-foreground" title={item.cpv_desc || undefined}>{item.cpv || "—"}</td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{euros(item.valor)}</td>
                      <td className="py-2 pr-3">
                        <div className="flex flex-wrap gap-1">
                          {item.ecologico && <Chip tone="teal">ecológico</Chip>}
                          {item.ajuste_direto && <Chip tone="amber">ajuste direto</Chip>}
                          {item.n_concorrentes !== null && item.n_concorrentes !== undefined && (
                            <Chip tone={item.n_concorrentes <= 1 ? "rose" : "neutral"}>{item.n_concorrentes} concorrente(s)</Chip>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {aba === "fornecedores" && (
        <div className="space-y-3">
          <SectionCard title="Carteira de fornecedores" subtitle="Contratos em que esta empresa é compradora; o valor é repartido pelos fornecedores identificados." icon={Users}>
            {!fornecedores && !carregandoFornecedores && (
              <button onClick={carregarFornecedores} className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-sm text-teal-200">
                <Users size={14} /> Analisar fornecedores
              </button>
            )}
            {carregandoFornecedores && <Loading label="A carregar e calcular fornecedores…" />}
            {erroFornecedores && <EmptyState tone="warn">{erroFornecedores}</EmptyState>}
          </SectionCard>
          {fornecedores && (
            <CarteiraResultado
              dados={fornecedores}
              titulo="Fornecedores do comprador"
              onAbrir={onAbrirEmpresa ? (nifFornecedor: string, nomeFornecedor: string) => onAbrirEmpresa(nifFornecedor, nomeFornecedor, pais) : undefined}
            />
          )}
        </div>
      )}

      <AvisoEsg aviso={cartao?.aviso || meta?.aviso} />
    </div>
  );
}
