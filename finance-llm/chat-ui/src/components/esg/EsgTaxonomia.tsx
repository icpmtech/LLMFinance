/**
 * **Taxonomia UE** — elegibilidade das empresas face aos seis objetivos
 * ambientais do Regulamento (UE) 2020/852.
 *
 * A página não declara alinhamento: sem critérios técnicos, DNSH e
 * salvaguardas mínimas documentados, a classificação máxima é «elegível,
 * alinhamento por verificar». A lista de atividades vem do EU Taxonomy Compass.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Building2,
  CheckCircle2,
  Globe2,
  Landmark,
  Layers,
  ListChecks,
  Search,
  ShieldCheck,
  Target,
} from "lucide-react";

import {
  getEsgTaxonomia,
  getEsgTaxonomiaAtividades,
  getEsgTaxonomiaEmpresa,
  suggestEsg,
} from "../../esgApi";
import type {
  EsgMeta,
  EsgSugestao,
  EsgTaxonomiaAtividade,
  EsgTaxonomiaEmpresa,
  EsgTaxonomiaPanorama,
} from "../../esgApi";
import { Chip, EmptyState, Kpi, Loading, SectionCard } from "../padroes/padroesKit";
import { num, pct } from "./esgKit";

const ALINHAMENTO_TONE: Record<string, string> = {
  sem_dados: "neutral",
  nao_elegivel: "rose",
  elegivel_nao_verificado: "amber",
};

const ALINHAMENTO_LABEL: Record<string, string> = {
  sem_dados: "Sem dados para avaliar",
  nao_elegivel: "Sem atividade elegível identificada",
  elegivel_nao_verificado: "Elegível — alinhamento por verificar",
};

function ObjetivoPill({ id, label, cor }: { id: number; label?: string; cor?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px]"
      style={{ borderColor: `${cor || "#94a3b8"}55`, backgroundColor: `${cor || "#94a3b8"}14`, color: cor || "#cbd5e1" }}
      title={label || `Objetivo ${id}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cor || "#94a3b8" }} />
      {id} · {label || "Objetivo"}
    </span>
  );
}

function DetalheEmpresa({ dados, avisos }: { dados: EsgTaxonomiaEmpresa; avisos?: string[] }) {
  const tone = ALINHAMENTO_TONE[dados.alinhamento] || "neutral";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
        <div>
          <p className="text-[11px] text-muted-foreground">CAE/NACE</p>
          <p className="font-mono text-sm">{dados.nace || "n/d"}{dados.secao ? ` · secção ${dados.secao}` : ""}</p>
        </div>
        <Chip tone={tone}>{dados.alinhamento_label || ALINHAMENTO_LABEL[dados.alinhamento] || dados.alinhamento}</Chip>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Atividades elegíveis</p>
          <p className="mt-1 font-mono text-xl">{num(dados.n_atividades)}</p>
          <p className="text-[10px] text-muted-foreground">{dados.match === "nace" ? "match por CAE/NACE" : dados.match === "setor" ? "proxy pelo setor/CPV" : "sem match"}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Objetivos ambientais</p>
          <p className="mt-1 font-mono text-xl">{num(dados.objetivos?.length)}/6</p>
          <p className="text-[10px] text-muted-foreground">contributo significativo potencial</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Verificação</p>
          <p className="mt-1 font-mono text-xl">{pct(dados.cobertura_verificacao, 0)}</p>
          <p className="text-[10px] text-muted-foreground">DNSH + salvaguardas com indicador</p>
        </div>
      </div>

      {dados.objetivos?.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium">Objetivos com atividade elegível</p>
          <div className="flex flex-wrap gap-1.5">
            {dados.objetivos.map((objetivo) => (
              <ObjetivoPill key={objetivo.id} id={objetivo.id} label={objetivo.curto || objetivo.label} cor={objetivo.cor} />
            ))}
          </div>
        </div>
      )}

      {dados.atividades?.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><Layers size={13} /> Atividades do Compass</p>
          <div className="max-h-64 overflow-auto rounded-xl border border-white/10">
            <table className="w-full min-w-[520px] text-left text-[11px]">
              <thead className="sticky top-0 bg-[#0b1116] text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr className="border-b border-white/10">
                  <th className="px-2 py-1.5">Atividade</th>
                  <th className="px-2 py-1.5">Setor</th>
                  <th className="px-2 py-1.5">NACE</th>
                  <th className="px-2 py-1.5">Objetivos</th>
                </tr>
              </thead>
              <tbody>
                {dados.atividades.map((atividade) => (
                  <tr key={atividade.id} className="border-b border-white/5 last:border-0">
                    <td className="max-w-[250px] px-2 py-1.5">
                      <a href={atividade.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 hover:text-sky-300">
                        <span className="line-clamp-2">{atividade.nome}</span>
                        <ArrowUpRight size={11} className="mt-0.5 shrink-0" />
                      </a>
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">{atividade.setor}</td>
                    <td className="px-2 py-1.5 font-mono text-muted-foreground">{atividade.nace_match || atividade.nace.slice(0, 2).join(", ") || "—"}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {atividade.objetivos.map((objetivo) => (
                          <ObjetivoPill key={`${atividade.id}-${objetivo.id}`} id={objetivo.id} label={objetivo.curto || objetivo.label || undefined} cor={objetivo.cor || undefined} />
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><ShieldCheck size={13} /> DNSH — sem prejuízo significativo</p>
          <div className="space-y-1">
            {(dados.dnsh || []).map((item) => (
              <div key={item.objetivo} className="flex items-center justify-between gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5 text-[10.5px]">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: item.cor }} />
                  <span className="truncate">{item.label}</span>
                </span>
                <Chip tone={item.status === "com indicador" ? "teal" : "neutral"}>
                  {item.status === "com indicador" ? `${item.indicadores.length} indicador(es)` : "sem evidência"}
                </Chip>
              </div>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><CheckCircle2 size={13} /> Salvaguardas mínimas</p>
          <div className="space-y-1">
            {(dados.salvaguardas || []).map((item) => (
              <div key={item.id} className="rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5 text-[10.5px]" title={item.descricao}>
                <div className="flex items-center justify-between gap-2">
                  <span>{item.label}</span>
                  <Chip tone={item.status === "sem evidência" ? "rose" : item.status === "evidência parcial" ? "teal" : "amber"}>{item.status}</Chip>
                </div>
                {item.indicadores.length > 0 && <p className="mt-0.5 truncate font-mono text-[9.5px] text-muted-foreground">{item.indicadores.join(" · ")}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {(dados.ods?.length > 0 || dados.materialidade?.length > 0) && (
        <div className="grid gap-3 lg:grid-cols-2">
          {dados.ods?.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><Globe2 size={13} /> ODS com evidência</p>
              <div className="flex flex-wrap gap-1.5">
                {dados.ods.map((ods) => (
                  <span key={ods.id} className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: `${ods.cor}55`, backgroundColor: `${ods.cor}14`, color: ods.cor }}>
                    ODS {ods.id} · {ods.label}
                  </span>
                ))}
              </div>
            </div>
          )}
          {dados.materialidade?.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><Target size={13} /> Temas materiais</p>
              <div className="flex flex-wrap gap-1.5">
                {dados.materialidade.map((tema) => (
                  <Chip key={tema.tema} tone={tema.relevancia === "alta" ? "amber" : "neutral"} title={tema.origem}>{tema.tema}</Chip>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[10.5px] text-amber-100">
        <p className="flex items-start gap-1.5">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>{(avisos && avisos[0]) || dados.avisos?.[0] || "Elegibilidade não é alinhamento: faltam critérios técnicos, DNSH e salvaguardas verificadas."}</span>
        </p>
      </div>

      <a href={dados.url_compass} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-sky-300 hover:underline">
        Abrir o EU Taxonomy Compass <ArrowUpRight size={11} />
      </a>
    </div>
  );
}

export function EsgTaxonomia({ meta }: { meta: EsgMeta | null }) {
  const [panorama, setPanorama] = useState<EsgTaxonomiaPanorama | null>(meta?.taxonomia || null);
  const [erroPanorama, setErroPanorama] = useState("");

  const [consulta, setConsulta] = useState("");
  const [setorAtividade, setSetorAtividade] = useState("");
  const [objetivoAtividade, setObjetivoAtividade] = useState("");
  const [atividades, setAtividades] = useState<EsgTaxonomiaAtividade[]>([]);
  const [totalAtividades, setTotalAtividades] = useState(0);
  const [carregandoAtividades, setCarregandoAtividades] = useState(false);
  const [erroAtividades, setErroAtividades] = useState("");

  const [nomeEmpresa, setNomeEmpresa] = useState("");
  const [sugestoes, setSugestoes] = useState<EsgSugestao[]>([]);
  const [alvo, setAlvo] = useState<{ nif: string; nome: string; pais: string } | null>(null);
  const [detalhe, setDetalhe] = useState<EsgTaxonomiaEmpresa | null>(null);
  const [avisosEmpresa, setAvisosEmpresa] = useState<string[]>([]);
  const [carregandoEmpresa, setCarregandoEmpresa] = useState(false);
  const [erroEmpresa, setErroEmpresa] = useState("");

  useEffect(() => {
    if (panorama) return;
    getEsgTaxonomia()
      .then(setPanorama)
      .catch((exc: unknown) => setErroPanorama(exc instanceof Error ? exc.message : "Não foi possível carregar a Taxonomia UE."));
  }, [panorama]);

  useEffect(() => {
    let cancelado = false;
    const timer = window.setTimeout(() => {
      setCarregandoAtividades(true);
      setErroAtividades("");
      getEsgTaxonomiaAtividades({
        q: consulta.trim() || undefined,
        setor: setorAtividade || undefined,
        objetivo: objetivoAtividade ? Number(objetivoAtividade) : undefined,
        size: 40,
      })
        .then((resposta) => {
          if (cancelado) return;
          setAtividades(resposta.itens || []);
          setTotalAtividades(resposta.total || 0);
        })
        .catch((exc: unknown) => {
          if (!cancelado) setErroAtividades(exc instanceof Error ? exc.message : "Não foi possível pesquisar atividades.");
        })
        .finally(() => {
          if (!cancelado) setCarregandoAtividades(false);
        });
    }, 220);
    return () => {
      cancelado = true;
      window.clearTimeout(timer);
    };
  }, [consulta, setorAtividade, objetivoAtividade]);

  useEffect(() => {
    const texto = nomeEmpresa.trim();
    if (texto.length < 3 || alvo?.nome === texto) {
      setSugestoes([]);
      return;
    }
    let cancelado = false;
    const timer = window.setTimeout(() => {
      suggestEsg(texto, 6)
        .then((resposta) => {
          if (!cancelado) setSugestoes(resposta.sugestoes || []);
        })
        .catch(() => {
          if (!cancelado) setSugestoes([]);
        });
    }, 250);
    return () => {
      cancelado = true;
      window.clearTimeout(timer);
    };
  }, [nomeEmpresa, alvo?.nome]);

  const abrirEmpresa = useCallback((item: EsgSugestao) => {
    setAlvo({ nif: item.nif, nome: item.nome, pais: item.pais || "PT" });
    setNomeEmpresa(item.nome);
    setSugestoes([]);
  }, []);

  useEffect(() => {
    if (!alvo) {
      setDetalhe(null);
      return;
    }
    setCarregandoEmpresa(true);
    setErroEmpresa("");
    getEsgTaxonomiaEmpresa(alvo.pais, alvo.nif)
      .then((resposta) => {
        setDetalhe(resposta.taxonomia);
        setAvisosEmpresa(resposta.avisos || []);
      })
      .catch((exc: unknown) => setErroEmpresa(exc instanceof Error ? exc.message : "Não foi possível avaliar a empresa."))
      .finally(() => setCarregandoEmpresa(false));
  }, [alvo]);

  const setores = useMemo(() => panorama?.setores || [], [panorama]);

  if (!panorama && erroPanorama) return <EmptyState tone="warn">{erroPanorama}</EmptyState>;
  if (!panorama) return <Loading label="A carregar a Taxonomia Europeia…" />;

  return (
    <div className="space-y-4">
      <SectionCard
        title="Taxonomia Europeia — elegibilidade, não certificação"
        subtitle={`${panorama.total_atividades} atividades oficiais · sincronizado em ${panorama.fonte.sincronizado_em}`}
        icon={Landmark}
        actions={
          <a href={panorama.fonte.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-sky-300 hover:underline">
            EU Taxonomy Compass <ArrowUpRight size={11} />
          </a>
        }
      >
        <p className="mb-3 rounded-xl border border-sky-400/20 bg-sky-400/5 px-3 py-2 text-[11px] text-sky-100">{panorama.fonte.aviso}</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi icon={Target} label="Objetivos ambientais" value={num(panorama.objetivos.length)} sub="Regulamento (UE) 2020/852" />
          <Kpi icon={Layers} label="Atividades elegíveis" value={num(panorama.total_atividades)} sub="lista oficial do Compass" color="text-sky-300" />
          <Kpi icon={Building2} label="Setores cobertos" value={num(setores.length)} sub="setores do Compass" color="text-violet-300" />
          <Kpi icon={ShieldCheck} label="Salvaguardas mínimas" value={num(panorama.salvaguardas.length)} sub="direitos humanos, trabalho, anticorrupção e fiscalidade" color="text-amber-300" />
        </div>
      </SectionCard>

      <SectionCard title="Os seis objetivos ambientais" subtitle="Uma atividade é elegível se contribuir significativamente para pelo menos um objetivo e não prejudicar os restantes." icon={Target}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {panorama.objetivos.map((objetivo) => (
            <div key={objetivo.id} className="rounded-2xl border border-white/10 bg-white/[0.02] p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="flex items-center gap-2 text-xs font-medium" style={{ color: objetivo.cor }}>
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: objetivo.cor }} />
                  {objetivo.curto}
                </p>
                <span className="font-mono text-[10px] text-muted-foreground">{num(objetivo.n_atividades)} atividades</span>
              </div>
              <p className="mt-1 text-[10.5px] text-muted-foreground">{objetivo.descricao || objetivo.label}</p>
              <ul className="mt-2 space-y-1">
                {(objetivo.atividades || []).slice(0, 4).map((atividade) => (
                  <li key={atividade.id} className="truncate text-[10px] text-muted-foreground" title={atividade.nome}>· {atividade.nome}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Percurso de alinhamento (IAPMEI / UN Global Compact)" subtitle="Cinco passos, do ponto de partida ao reporte." icon={ListChecks}>
        <div className="grid gap-2 md:grid-cols-5">
          {panorama.passos.map((passo) => (
            <div key={passo.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
              <p className="font-mono text-[10px] text-emerald-300">PASSO {passo.id}</p>
              <p className="mt-0.5 text-[11px] font-medium">{passo.label}</p>
              <p className="mt-1 text-[10px] text-muted-foreground">{passo.descricao}</p>
              <p className="mt-1.5 text-[10px] text-sky-200/80">{passo.no_iqos}</p>
            </div>
          ))}
        </div>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <SectionCard title="Atividades da Taxonomia" subtitle="Pesquise por nome, setor, objetivo ou CAE/NACE." icon={Search}>
          <div className="mb-2 flex flex-wrap gap-2">
            <input
              value={consulta}
              onChange={(event) => setConsulta(event.target.value)}
              placeholder="Pesquisar atividade…"
              className="min-w-[180px] flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs outline-none placeholder:text-muted-foreground/60"
            />
            <select value={setorAtividade} onChange={(event) => setSetorAtividade(event.target.value)} className="rounded-xl border border-white/10 bg-[#0b1116] px-2 py-1.5 text-xs">
              <option value="">Todos os setores</option>
              {setores.map((item) => (
                <option key={item.setor} value={item.setor}>{item.setor} ({item.n})</option>
              ))}
            </select>
            <select value={objetivoAtividade} onChange={(event) => setObjetivoAtividade(event.target.value)} className="rounded-xl border border-white/10 bg-[#0b1116] px-2 py-1.5 text-xs">
              <option value="">Todos os objetivos</option>
              {panorama.objetivos.map((objetivo) => (
                <option key={objetivo.id} value={objetivo.id}>{objetivo.id} · {objetivo.curto}</option>
              ))}
            </select>
          </div>
          {erroAtividades && <EmptyState tone="warn">{erroAtividades}</EmptyState>}
          {carregandoAtividades ? (
            <Loading label="A filtrar atividades…" />
          ) : atividades.length === 0 ? (
            <EmptyState>Nenhuma atividade corresponde aos filtros.</EmptyState>
          ) : (
            <>
              <p className="mb-1 text-[10px] text-muted-foreground">{num(totalAtividades)} atividade(s); a mostrar as primeiras {num(atividades.length)}.</p>
              <div className="max-h-[430px] overflow-auto rounded-xl border border-white/10">
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
                    {atividades.map((atividade) => (
                      <tr key={atividade.id} className="border-b border-white/5 last:border-0">
                        <td className="max-w-[230px] px-2 py-1.5">
                          <a href={atividade.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 hover:text-sky-300">
                            <span className="line-clamp-2">{atividade.nome}</span>
                            <ArrowUpRight size={10} className="mt-0.5 shrink-0" />
                          </a>
                        </td>
                        <td className="px-2 py-1.5 text-muted-foreground">{atividade.setor}</td>
                        <td className="px-2 py-1.5 font-mono text-[10px] text-muted-foreground">{atividade.nace.slice(0, 3).join(", ") || "—"}</td>
                        <td className="px-2 py-1.5">
                          <div className="flex flex-wrap gap-1">
                            {atividade.objetivos.map((objetivo) => (
                              <ObjetivoPill key={`${atividade.id}-${objetivo.id}`} id={objetivo.id} label={objetivo.curto || objetivo.label || undefined} cor={objetivo.cor || undefined} />
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </SectionCard>

        <SectionCard title="Avaliar uma empresa" subtitle="Pesquise pelo nome ou NIF para ver a elegibilidade face à Taxonomia." icon={Building2}>
          <div className="relative">
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5">
              <Search size={13} className="text-muted-foreground" />
              <input
                value={nomeEmpresa}
                onChange={(event) => {
                  setNomeEmpresa(event.target.value);
                  setAlvo(null);
                }}
                placeholder="Nome ou NIF da empresa…"
                className="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground/60"
              />
            </div>
            {sugestoes.length > 0 && (
              <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-xl border border-white/10 bg-[#0b1116] shadow-xl">
                {sugestoes.map((item) => (
                  <li key={`${item.pais}-${item.nif}`}>
                    <button onClick={() => abrirEmpresa(item)} className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-[11px] hover:bg-white/5">
                      <span className="min-w-0 truncate">{item.nome}</span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{item.nif}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-3">
            {!alvo && <EmptyState>Escolha uma empresa para calcular a elegibilidade a partir do CAE/NACE.</EmptyState>}
            {erroEmpresa && <EmptyState tone="warn">{erroEmpresa}</EmptyState>}
            {carregandoEmpresa && <Loading label="A cruzar o CAE com o Compass…" />}
            {detalhe && !carregandoEmpresa && <DetalheEmpresa dados={detalhe} avisos={avisosEmpresa} />}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Salvaguardas mínimas e DNSH" subtitle="O que o módulo consegue acompanhar com indicadores declarados — e o que continua a exigir verificação." icon={ShieldCheck}>
        <div className="grid gap-3 lg:grid-cols-2">
          <div>
            <p className="mb-1.5 text-[11px] font-medium">Salvaguardas sociais mínimas</p>
            <div className="space-y-1.5">
              {panorama.salvaguardas.map((item) => (
                <div key={item.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5 text-[10.5px]">
                  <p className="flex items-center justify-between gap-2 font-medium"><span>{item.label}</span><Chip tone="neutral">{item.fonte || "UE"}</Chip></p>
                  <p className="mt-0.5 text-muted-foreground">{item.descricao}</p>
                  <p className="mt-1 font-mono text-[9.5px] text-muted-foreground">{item.indicadores.join(" · ")}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium"><BookOpen size={13} /> Normas de relato</p>
            <div className="space-y-1.5">
              {panorama.normas_relato.map((norma) => (
                <a key={norma.id} href={norma.url} target="_blank" rel="noreferrer" className="block rounded-xl border border-white/10 bg-white/[0.02] p-2.5 text-[10.5px] transition hover:border-sky-400/30">
                  <p className="flex items-center justify-between gap-2 font-medium"><span>{norma.label}</span><Chip tone="blue">{norma.ambito}</Chip></p>
                  <p className="mt-0.5 text-muted-foreground">{norma.uso}</p>
                </a>
              ))}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Objetivos de Desenvolvimento Sustentável" subtitle="Os 17 ODS e os grupos de indicadores que lhes dão evidência." icon={Globe2}>
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {panorama.ods.map((ods) => (
            <div key={ods.id} className="rounded-xl border border-white/10 bg-white/[0.02] px-2.5 py-1.5 text-[10.5px]">
              <p className="flex items-center gap-1.5 font-medium" style={{ color: ods.cor }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: ods.cor }} />
                ODS {ods.id} · {ods.label}
              </p>
              <p className="mt-0.5 text-[9.5px] text-muted-foreground">{ods.grupos.join(" · ")}</p>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
