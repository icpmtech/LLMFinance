/**
 * **Descoberta** — painel de controlo de uma empresa.
 *
 * Dá-se um NIF (ou um nome) e a página recolhe tudo o que a plataforma sabe
 * sobre a empresa, desenha o **grafo de informação** que a liga a essa evidência
 * e mostra a **ontologia** em ação: que tipos de objeto foram instanciados, que
 * tipos de ligação foram materializados e o que falta declarar.
 *
 * A análise é escrita pelo **Hermes**, seguindo as skills da biblioteca
 * partilhada (as mesmas do Chat IA e do RAG) — pode escolher-se o método à mão.
 *
 * A página aceita link direto (`/descoberta/<NIF>`), como o PessoasIQ.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Compass,
  Layers,
  ListChecks,
  Network,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { SankeyDiagram } from "../components/graph/SankeyDiagram";
import { TreemapChart } from "../components/graph/TreemapChart";
import { formatCompact, formatMoney, legendEntries, toStudioGraph, type GraphMetric } from "../components/graph/graphStudio";
import { DescobertaDecisao } from "../components/descoberta/DescobertaDecisao";
import { useWindowMode } from "../layout";
import {
  analisarEmpresa,
  descobrirEmpresa,
  getDescobertaMeta,
  listarSkillsDescoberta,
  nifDoEndereco,
  resolverEmpresa,
  type DescobertaAlvo,
  type DescobertaAnalise,
  type DescobertaMeta,
  type DescobertaRecolha,
  type DescobertaSkills,
} from "../descobertaApi";

/* ----------------------------------------------------------------- helpers */

const texto = (valor: unknown): string => (valor === null || valor === undefined ? "" : String(valor));

const numero = (valor: unknown): number => {
  const convertido = Number(valor);
  return Number.isFinite(convertido) ? convertido : 0;
};

const lista = <T,>(valor: unknown): T[] => (Array.isArray(valor) ? (valor as T[]) : []);

/** Vistas do grafo de informação: três do `GraphCanvas` e duas próprias. */
type VistaGrafo = "network" | "hierarchical" | "circular" | "sankey" | "treemap";

const VISTAS: { id: VistaGrafo; label: string }[] = [
  { id: "network", label: "Rede" },
  { id: "hierarchical", label: "Hierarquia" },
  { id: "circular", label: "Circular" },
  { id: "sankey", label: "Fluxo (Sankey)" },
  { id: "treemap", label: "Peso (treemap)" },
];

const ESTADO_FONTE: Record<string, { label: string; className: string }> = {  ok: { label: "ok", className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
  vazio: { label: "vazio", className: "border-white/10 bg-white/5 text-muted-foreground" },
  erro: { label: "erro", className: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  tempo: { label: "tempo", className: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
};

function Kpi({ rotulo, valor, nota }: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="glass-card gradient-border rounded-2xl px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{rotulo}</p>
      <p className="mt-0.5 truncate text-lg font-semibold">{valor}</p>
      {nota ? <p className="truncate text-[11px] text-muted-foreground">{nota}</p> : null}
    </div>
  );
}

function ChaveValor({ dados }: { dados: Record<string, unknown> }) {
  const linhas = Object.entries(dados)
    .filter(([, valor]) => valor !== null && valor !== undefined && valor !== "")
    .filter(([, valor]) => !Array.isArray(valor) || valor.length > 0)
    .slice(0, 24);
  if (!linhas.length) return <p className="text-xs text-muted-foreground">Sem dados.</p>;
  return (
    <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
      {linhas.map(([chave, valor]) => (
        <div key={chave} className="flex min-w-0 gap-2 border-b border-white/5 pb-1">
          <dt className="shrink-0 text-muted-foreground">{chave}</dt>
          <dd className="min-w-0 flex-1 truncate text-right">
            {Array.isArray(valor)
              ? valor.map((item) => (typeof item === "object" ? JSON.stringify(item) : texto(item))).join(", ")
              : typeof valor === "object"
                ? JSON.stringify(valor)
                : texto(valor)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function DescobertaPage({ onBack }: { onBack?: () => void } = {}) {
  const { windowMode } = useWindowMode();
  const [meta, setMeta] = useState<DescobertaMeta | null>(null);
  const [consulta, setConsulta] = useState(() => nifDoEndereco());
  const [candidatos, setCandidatos] = useState<DescobertaAlvo[] | null>(null);
  const [aProcurar, setAProcurar] = useState(false);
  const [recolha, setRecolha] = useState<DescobertaRecolha | null>(null);
  const [aDescobrir, setADescobrir] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aba, setAba] = useState("decisao");
  const [vista, setVista] = useState<VistaGrafo>("network");
  const [metric, setMetric] = useState<GraphMetric>("valor");
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);
  const [skills, setSkills] = useState<DescobertaSkills | null>(null);
  const [profundidade, setProfundidade] = useState<"rapida" | "profunda">("rapida");
  const [skillId, setSkillId] = useState("");
  const [pergunta, setPergunta] = useState("");
  const [analise, setAnalise] = useState<DescobertaAnalise | null>(null);
  const [aAnalisar, setAAnalisar] = useState(false);
  const [erroAnalise, setErroAnalise] = useState<string | null>(null);

  const descobrir = useCallback(async (nif: string, nome?: string) => {
    const alvo = (nif || "").trim();
    if (!alvo) return;
    setADescobrir(true);
    setErro(null);
    setNoSelecionado(null);
    try {
      const resultado = await descobrirEmpresa(alvo, { nome });
      setRecolha(resultado);
      setCandidatos(null);
      window.history.replaceState(null, "", `/descoberta/${resultado.nif}`);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
      setRecolha(null);
    } finally {
      setADescobrir(false);
    }
  }, []);

  useEffect(() => {
    getDescobertaMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
    listarSkillsDescoberta()
      .then(setSkills)
      .catch(() => setSkills(null));
    const nif = nifDoEndereco();
    if (nif) void descobrir(nif);
  }, [descobrir]);

  const procurar = async () => {
    const valor = consulta.trim();
    if (valor.length < 2) return;
    if (/^\d{9}$/.test(valor)) {
      await descobrir(valor);
      return;
    }
    setAProcurar(true);
    setErro(null);
    try {
      const resultado = await resolverEmpresa(valor);
      setCandidatos(resultado.items || []);
      if (!resultado.items?.length) setErro(resultado.detail || "Sem resultados para esta pesquisa.");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
      setCandidatos([]);
    } finally {
      setAProcurar(false);
    }
  };

  const correrAnalise = async () => {
    if (!recolha) return;
    setAAnalisar(true);
    setErroAnalise(null);
    try {
      const resultado = await analisarEmpresa(recolha.nif, {
        pergunta: pergunta.trim() || undefined,
        profundidade,
        skill_id: skillId || undefined,
        nome: recolha.nome,
      });
      setAnalise(resultado);
    } catch (falha) {
      setErroAnalise(falha instanceof Error ? falha.message : String(falha));
      setAnalise(null);
    } finally {
      setAAnalisar(false);
    }
  };

  const grafoStudio = useMemo(
    () => toStudioGraph(recolha?.grafo ?? null, metric),
    [recolha?.grafo, metric],
  );
  const legenda = useMemo(() => (grafoStudio ? legendEntries(grafoStudio.nodes) : []), [grafoStudio]);

  const secoes = recolha?.secoes ?? {};
  const contratos = lista<Record<string, unknown>>((secoes.contratos as Record<string, unknown>)?.contratos);
  const sinais = lista<Record<string, unknown>>((secoes.contratos as Record<string, unknown>)?.sinais);
  const pessoas = lista<Record<string, unknown>>((secoes.pessoas as Record<string, unknown>)?.pessoas);
  const insolvencias = lista<Record<string, unknown>>((secoes.cire as Record<string, unknown>)?.insolvencias);
  const marcas = lista<Record<string, unknown>>((secoes.marcas as Record<string, unknown>)?.items);
  const firmas = lista<Record<string, unknown>>((secoes.firmas as Record<string, unknown>)?.items);
  const subvencoes = lista<Record<string, unknown>>((secoes.subvencoes as Record<string, unknown>)?.items);
  const devedores = lista<Record<string, unknown>>((secoes.devedores as Record<string, unknown>)?.items);
  const noticias = lista<Record<string, unknown>>((secoes.noticias as Record<string, unknown>)?.items);
  const societario = lista<Record<string, unknown>>((secoes.societario as Record<string, unknown>)?.items);

  const fontesResumo = meta?.fontes ?? [];
  const ontologia = recolha?.ontologia ?? null;

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-300 via-fuchsia-500 to-indigo-600 text-white shadow-lg shadow-fuchsia-500/20">
          <Compass size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold leading-tight">Descoberta</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Uma empresa, todas as fontes, o grafo de informação, a ontologia, os números para decidir e a análise do Hermes
            {recolha ? ` · ${recolha.nome} (${recolha.nif})` : ""}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {meta ? (
            <span className="hidden items-center gap-1 rounded-full border border-violet-500/20 bg-violet-500/10 px-2.5 py-0.5 text-[11px] font-medium text-violet-300 sm:inline-flex">
              <Sparkles size={11} />
              {meta.fontes.length} fontes · {meta.skills.total} skills
              {ontologia ? ` · ontologia ${recolha?.ontologia?.ontologia ?? "IQ OS"}` : ""}
            </span>
          ) : null}
          {!windowMode && onBack ? (
            <Button variant="secondary" size="sm" onClick={onBack}>
              Voltar ao Chat
            </Button>
          ) : null}
        </div>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 px-4 py-2.5">
        <div className="relative min-w-[240px] flex-1">
          <Input
            value={consulta}
            onChange={(event) => setConsulta(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void procurar();
            }}
            placeholder="NIF (9 dígitos) ou nome da empresa…"
            className="pl-8"
          />
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        </div>
        <Button onClick={() => void procurar()} loading={aProcurar || aDescobrir} icon={<Search size={15} />}>
          Descobrir
        </Button>
        {recolha ? (
          <Button
            variant="outline"
            onClick={() => void descobrir(recolha.nif, recolha.nome)}
            loading={aDescobrir}
            icon={<RefreshCw size={15} />}
          >
            Atualizar
          </Button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 @4xl:p-4">
        {erro ? (
          <p className="mb-3 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle size={14} /> {erro}
          </p>
        ) : null}

        {candidatos && candidatos.length ? (
          <Card className="mb-4">
            <CardHeader className="mb-2">
              <CardTitle icon={<ListChecks size={16} className="text-primary" />}>
                {candidatos.length} empresa(s) para «{consulta}»
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {candidatos.map((alvo) => (
                <button
                  key={`${alvo.nif}-${alvo.nome}`}
                  type="button"
                  onClick={() => void descobrir(alvo.nif || "", alvo.nome || undefined)}
                  className="flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2 text-left text-sm transition hover:border-primary/40 hover:bg-primary/5"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{alvo.nome || alvo.nif}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {alvo.nif} · {formatCompact(alvo.contratos)} contratos · {formatMoney(alvo.valor)}
                      {alvo.concelho ? ` · ${alvo.concelho}` : ""}
                    </span>
                  </span>
                  {(alvo.papeis || []).slice(0, 3).map((papel) => (
                    <Badge key={papel} variant="secondary">
                      {papel}
                    </Badge>
                  ))}
                </button>
              ))}
            </CardContent>
          </Card>
        ) : null}

        {!recolha ? (
          <Card>
            <CardHeader className="mb-2">
              <CardTitle icon={<Compass size={16} className="text-primary" />}>Como funciona</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>Escreva o NIF (ou o nome) de uma empresa e a plataforma faz, de uma vez:</p>
              <ul className="list-disc space-y-1 pl-4">
                {(fontesResumo.length ? fontesResumo : []).map((fonte) => (
                  <li key={fonte.id}>
                    <span className="text-foreground">{fonte.label}</span> — {fonte.descricao}
                  </li>
                ))}
              </ul>
              <p>
                Depois monta o <span className="text-foreground">grafo de informação</span> dessa empresa, projeta-o
                sobre a <span className="text-foreground">ontologia</span> do IQ OS, calcula os{" "}
                <span className="text-foreground">números de decisão</span> (evolução, concentração, preços,
                concorrência e pontos de atenção) e deixa o <span className="text-foreground">Hermes</span> escrever a
                análise citada.
              </p>
            </CardContent>
          </Card>
        ) : null}

        {recolha ? (
          <>
            <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
              <Kpi rotulo="Contratos" valor={formatCompact(recolha.kpis.contratos)} nota={`${formatMoney(recolha.kpis.valor_total)} de valor lido`} />
              <Kpi rotulo="Adjudicantes" valor={formatCompact(recolha.kpis.adjudicantes)} nota={recolha.kpis.maior_adjudicante?.nome} />
              <Kpi
                rotulo="Concentração"
                valor={recolha.kpis.concentracao_maior === null || recolha.kpis.concentracao_maior === undefined ? "—" : `${recolha.kpis.concentracao_maior}%`}
                nota="no maior adjudicante"
              />
              <Kpi rotulo="Ajuste direto" valor={recolha.kpis.taxa_ajuste_direto === null || recolha.kpis.taxa_ajuste_direto === undefined ? "—" : `${Math.round(numero(recolha.kpis.taxa_ajuste_direto) * 100)}%`} />
              <Kpi
                rotulo="Risco"
                valor={recolha.kpis.risco ? texto(recolha.kpis.risco) : "—"}
                nota={recolha.kpis.risco_pontos ? `${Math.round(numero(recolha.kpis.risco_pontos))} pontos` : undefined}
              />
              <Kpi rotulo="Recolha" valor={`${recolha.ms} ms`} nota={`${recolha.recolhidas}/${recolha.fontes.length} fontes com dados`} />
            </div>

            <Tabs value={aba} className="space-y-3">
              <TabsList className="flex-wrap">
                <TabsTrigger value="decisao" active={aba === "decisao"} onClick={() => setAba("decisao")}>
                  Decisão
                </TabsTrigger>
                <TabsTrigger value="resumo" active={aba === "resumo"} onClick={() => setAba("resumo")}>
                  Resumo
                </TabsTrigger>
                <TabsTrigger value="grafo" active={aba === "grafo"} onClick={() => setAba("grafo")}>
                  Grafo
                </TabsTrigger>
                <TabsTrigger value="ontologia" active={aba === "ontologia"} onClick={() => setAba("ontologia")}>
                  Ontologia
                </TabsTrigger>
                <TabsTrigger value="fontes" active={aba === "fontes"} onClick={() => setAba("fontes")}>
                  Fontes
                </TabsTrigger>
                <TabsTrigger value="analise" active={aba === "analise"} onClick={() => setAba("analise")}>
                  Análise (Hermes)
                </TabsTrigger>
              </TabsList>

              <TabsContent value="decisao" active={aba === "decisao"} className="space-y-3">
                {recolha.decisao ? (
                  <DescobertaDecisao decisao={recolha.decisao} />
                ) : (
                  <Card>
                    <CardContent className="text-sm text-muted-foreground">
                      Sem decisão calculada — recolha esta empresa com «incluir decisão».
                    </CardContent>
                  </Card>
                )}
              </TabsContent>

              <TabsContent value="resumo" active={aba === "resumo"} className="space-y-3">
                {sinais.length ? (
                  <div className="flex flex-wrap gap-2">
                    {sinais.map((sinal) => (
                      <span
                        key={texto(sinal.padrao)}
                        className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-200"
                      >
                        <span className="font-medium">{texto(sinal.padrao)}</span> · {texto(sinal.detalhe)}
                      </span>
                    ))}
                  </div>
                ) : null}

                <Card>
                  <CardHeader className="mb-2">
                    <CardTitle icon={<Network size={16} className="text-primary" />}>
                      Contratos ({contratos.length} lidos)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="text-left text-muted-foreground">
                        <tr>
                          <th className="pb-1 pr-3 font-medium">Ano</th>
                          <th className="pb-1 pr-3 font-medium">Objeto</th>
                          <th className="pb-1 pr-3 font-medium">Adjudicante</th>
                          <th className="pb-1 pr-3 font-medium">CPV</th>
                          <th className="pb-1 text-right font-medium">Valor</th>
                        </tr>
                      </thead>
                      <tbody>
                        {contratos.slice(0, 40).map((contrato, indice) => (
                          <tr key={texto(contrato.id) || indice} className="border-t border-white/5">
                            <td className="py-1 pr-3 text-muted-foreground">{texto(contrato.ano)}</td>
                            <td className="max-w-[380px] truncate py-1 pr-3" title={texto(contrato.objeto)}>
                              {texto(contrato.objeto)}
                            </td>
                            <td className="max-w-[220px] truncate py-1 pr-3">{texto(contrato.adjudicante)}</td>
                            <td className="py-1 pr-3 text-muted-foreground">{texto(contrato.cpv)}</td>
                            <td className="py-1 text-right tabular-nums">{formatMoney(numero(contrato.valor))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {contratos.length > 40 ? (
                      <p className="pt-2 text-[11px] text-muted-foreground">A mostrar 40 de {contratos.length}.</p>
                    ) : null}
                  </CardContent>
                </Card>

                <div className="grid gap-3 lg:grid-cols-2">
                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>Pessoas e cargos ({pessoas.length})</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-1.5 text-xs">
                      {pessoas.length ? (
                        pessoas.slice(0, 20).map((pessoa, indice) => (
                          <div key={texto(pessoa.nif) || indice} className="border-b border-white/5 pb-1">
                            <p className="font-medium">{texto(pessoa.nome)}</p>
                            <p className="text-muted-foreground">
                              {lista<Record<string, unknown>>(pessoa.cargos)
                                .map((cargo) => texto(cargo.role_org || cargo.role))
                                .filter(Boolean)
                                .slice(0, 3)
                                .join(" · ") || "cargo registado"}
                            </p>
                          </div>
                        ))
                      ) : (
                        <p className="text-muted-foreground">Sem cargos registados.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>Insolvências ({insolvencias.length})</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-1.5 text-xs">
                      {insolvencias.length ? (
                        insolvencias.slice(0, 12).map((processo, indice) => (
                          <div key={texto(processo.processo) || indice} className="border-b border-white/5 pb-1">
                            <p className="font-medium">{texto(processo.especie || processo.ato)}</p>
                            <p className="text-muted-foreground">
                              {texto(processo.tribunal)} · {texto(processo.data).slice(0, 10)}
                            </p>
                          </div>
                        ))
                      ) : (
                        <p className="text-muted-foreground">Sem processos do CIRE.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>Marcas e firmas ({marcas.length + firmas.length})</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-1.5 text-xs">
                      {marcas.slice(0, 8).map((marca, indice) => (
                        <div key={`m-${indice}`} className="flex justify-between gap-2 border-b border-white/5 pb-1">
                          <span className="truncate">{texto(marca.nome || marca.marca)}</span>
                          <span className="shrink-0 text-muted-foreground">{texto(marca.estado || marca.classe)}</span>
                        </div>
                      ))}
                      {firmas.slice(0, 5).map((firma, indice) => (
                        <div key={`f-${indice}`} className="flex justify-between gap-2 border-b border-white/5 pb-1">
                          <span className="truncate">{texto(firma.nome || firma.firma)}</span>
                          <span className="shrink-0 text-muted-foreground">{texto(firma.situacao)}</span>
                        </div>
                      ))}
                      {!marcas.length && !firmas.length ? (
                        <p className="text-muted-foreground">Sem registos do INPI/RNPC.</p>
                      ) : null}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>
                        Subvenções, devedores e imprensa ({subvencoes.length + devedores.length + noticias.length})
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-xs">
                      {subvencoes.slice(0, 5).map((subvencao, indice) => (
                        <div key={`s-${indice}`} className="flex justify-between gap-2 border-b border-white/5 pb-1">
                          <span className="truncate">{texto(subvencao.entidade || subvencao.programa)}</span>
                          <span className="shrink-0 tabular-nums">{formatMoney(numero(subvencao.valor))}</span>
                        </div>
                      ))}
                      {devedores.length ? (
                        <p className="text-rose-300">Consta nas listas de devedores ({devedores.length} registo(s)).</p>
                      ) : null}
                      {noticias.slice(0, 5).map((noticia, indice) => (
                        <div key={`n-${indice}`} className="border-b border-white/5 pb-1">
                          <p className="truncate">{texto(noticia.titulo || noticia.title)}</p>
                          <p className="text-muted-foreground">{texto(noticia.fonte || noticia.source)}</p>
                        </div>
                      ))}
                      {!subvencoes.length && !devedores.length && !noticias.length ? (
                        <p className="text-muted-foreground">Sem subvenções, devedores ou menções na imprensa.</p>
                      ) : null}
                    </CardContent>
                  </Card>
                </div>

                <div className="grid gap-3 lg:grid-cols-2">
                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>Atos societários ({societario.length})</CardTitle>
                    </CardHeader>
                    <CardContent>
                      {societario.length ? (
                        <ChaveValor dados={societario[0] as Record<string, unknown>} />
                      ) : (
                        <p className="text-xs text-muted-foreground">Sem publicações de registo comercial.</p>
                      )}
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="mb-2">
                      <CardTitle>Risco e mercado</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <ChaveValor dados={((secoes.risco as Record<string, unknown>)?.risco as Record<string, unknown>) ?? {}} />
                      {(secoes.mercado as Record<string, unknown>) ? (
                        <ChaveValor dados={(secoes.mercado as Record<string, unknown>) as Record<string, unknown>} />
                      ) : null}
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              <TabsContent value="grafo" active={aba === "grafo"}>
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
                  {grafoStudio ? (
                    vista === "sankey" ? (
                      <SankeyDiagram
                        nodes={grafoStudio.nodes}
                        edges={grafoStudio.edges}
                        metric={metric}
                        unitLabel="€"
                        height={560}
                        onNodeClick={(no) => setNoSelecionado((atual) => (atual === no.id ? null : no.id))}
                      />
                    ) : vista === "treemap" ? (
                      <TreemapChart
                        nodes={grafoStudio.nodes}
                        metric={metric}
                        unitLabel="€"
                        height={560}
                        onNodeClick={(no) => setNoSelecionado((atual) => (atual === no.id ? null : no.id))}
                      />
                    ) : (
                      <GraphCanvas
                        graph={grafoStudio}
                        layout={vista}
                        metric={metric}
                        unitLabel="€"
                        heightClass="h-[560px]"
                        selectedNodeId={noSelecionado}
                        nodeSummary={(no) => `${no.role || no.dimension} · ${formatCompact(no.count)} · ${formatMoney(no.total_value)}`}
                        edgeSummary={(aresta) => `${formatMoney(aresta.value)} · ${formatCompact(aresta.count)}`}
                        onNodeClick={(no) => setNoSelecionado((atual) => (atual === no.id ? null : no.id))}
                      />
                    )
                  ) : (
                    <Card>
                      <CardContent className="text-sm text-muted-foreground">Sem grafo para esta empresa.</CardContent>
                    </Card>
                  )}
                  <div className="space-y-3">
                    <Card>
                      <CardHeader className="mb-2">
                        <CardTitle icon={<Layers size={16} className="text-primary" />}>Camadas</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-1 text-xs">
                        {Object.entries((recolha.grafo?.meta?.camadas as Record<string, number>) ?? {}).map(([tipo, total]) => (
                          <div key={tipo} className="flex justify-between border-b border-white/5 pb-1">
                            <span className="text-muted-foreground">{tipo}</span>
                            <span className="tabular-nums">{total}</span>
                          </div>
                        ))}
                        <div className="flex gap-2 pt-1">
                          <Button size="sm" variant={metric === "valor" ? "primary" : "outline"} onClick={() => setMetric("valor")}>
                            Valor
                          </Button>
                          <Button size="sm" variant={metric === "contratos" ? "primary" : "outline"} onClick={() => setMetric("contratos")}>
                            Contagem
                          </Button>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {VISTAS.map((opcao) => (
                            <Button
                              key={opcao.id}
                              size="sm"
                              variant={vista === opcao.id ? "primary" : "outline"}
                              onClick={() => setVista(opcao.id)}
                            >
                              {opcao.label}
                            </Button>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="mb-2">
                        <CardTitle>Legenda</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-1 text-xs">
                        {legenda.map((entrada) => (
                          <div key={entrada.key} className="flex items-center gap-2">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ background: entrada.color }} />
                            <span className="truncate">{entrada.label}</span>
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="ontologia" active={aba === "ontologia"} className="space-y-3">
                {ontologia ? (
                  <>
                    <div className="grid gap-2 sm:grid-cols-3">
                      <Kpi
                        rotulo="Tipos da ontologia"
                        valor={`${ontologia.cobertura.tipos_declarados_usados}/${ontologia.cobertura.tipos_instanciados}`}
                        nota={`${ontologia.cobertura.percent_tipos ?? 0}% do que descobrimos já é falado pela ontologia`}
                      />
                      <Kpi
                        rotulo="Ligações declaradas"
                        valor={String(ontologia.cobertura.ligacoes_declaradas)}
                        nota={`${ontologia.cobertura.ligacoes_materializadas} materializadas nesta empresa`}
                      />
                      <Kpi
                        rotulo="Lacunas"
                        valor={String(ontologia.lacunas.tipos.length + ontologia.lacunas.ligacoes.length)}
                        nota="tipos e ligações a acrescentar"
                      />
                    </div>

                    <Card>
                      <CardHeader className="mb-2">
                        <CardTitle icon={<Layers size={16} className="text-primary" />}>Tipos de objeto instanciados</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2 text-xs">
                        {ontologia.tipos.map((tipo) => (
                          <div key={tipo.id} className="rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">{tipo.label}</span>
                              <span className="text-muted-foreground">{tipo.id}</span>
                              <Badge variant={tipo.declarado ? "secondary" : "outline"}>
                                {tipo.declarado ? "declarado" : "não declarado"}
                              </Badge>
                              {tipo.declarado ? (
                                <Badge variant={tipo.origem_declarada ? "secondary" : "outline"}>
                                  {tipo.origem_declarada ? "origem declarada" : `origem: ${tipo.indice_usado ?? "—"}`}
                                </Badge>
                              ) : null}
                              <span className="ml-auto tabular-nums text-muted-foreground">{tipo.instancias} instância(s)</span>
                            </div>
                            {tipo.exemplos.length ? (
                              <p className="mt-1 truncate text-muted-foreground">
                                {tipo.exemplos.map((exemplo) => exemplo.label).filter(Boolean).slice(0, 4).join(" · ")}
                              </p>
                            ) : null}
                          </div>
                        ))}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="mb-2">
                        <CardTitle icon={<Network size={16} className="text-primary" />}>Relações provadas pela recolha</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-1.5 text-xs">
                        {ontologia.ligacoes.map((ligacao) => (
                          <div key={ligacao.id} className="flex flex-wrap items-center gap-2 border-b border-white/5 pb-1.5">
                            <span className="font-medium">{ligacao.label}</span>
                            <span className="text-muted-foreground">
                              {ligacao.from} → {ligacao.to}
                            </span>
                            <Badge variant={ligacao.declarado ? "secondary" : "outline"}>
                              {ligacao.declarado ? ligacao.id : "por declarar"}
                            </Badge>
                            <span className="min-w-0 flex-1 truncate text-muted-foreground">{ligacao.evidencia}</span>
                            <span className="tabular-nums">{ligacao.quantidade}</span>
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  </>
                ) : (
                  <Card>
                    <CardContent className="text-sm text-muted-foreground">Ontologia indisponível.</CardContent>
                  </Card>
                )}
              </TabsContent>

              <TabsContent value="fontes" active={aba === "fontes"}>
                <Card>
                  <CardHeader className="mb-2">
                    <CardTitle icon={<ListChecks size={16} className="text-primary" />}>
                      Fontes da descoberta ({recolha.recolhidas}/{recolha.fontes.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="text-left text-muted-foreground">
                        <tr>
                          <th className="pb-1 pr-3 font-medium">Fonte</th>
                          <th className="pb-1 pr-3 font-medium">Grupo</th>
                          <th className="pb-1 pr-3 font-medium">Ontologia</th>
                          <th className="pb-1 pr-3 font-medium">Estado</th>
                          <th className="pb-1 pr-3 text-right font-medium">Registos</th>
                          <th className="pb-1 text-right font-medium">Tempo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recolha.fontes.map((fonte) => {
                          const estado = ESTADO_FONTE[fonte.estado] ?? ESTADO_FONTE.vazio;
                          return (
                            <tr key={fonte.id} className="border-t border-white/5">
                              <td className="py-1 pr-3">
                                <span className="font-medium">{fonte.label}</span>
                                {fonte.erro ? (
                                  <span className="block truncate text-[11px] text-rose-300" title={fonte.erro}>
                                    {fonte.erro}
                                  </span>
                                ) : null}
                              </td>
                              <td className="py-1 pr-3 text-muted-foreground">{fonte.grupo}</td>
                              <td className="py-1 pr-3 text-muted-foreground">{fonte.ontologia ?? "—"}</td>
                              <td className="py-1 pr-3">
                                <span className={`rounded-full border px-2 py-0.5 text-[11px] ${estado.className}`}>
                                  {estado.label}
                                </span>
                              </td>
                              <td className="py-1 pr-3 text-right tabular-nums">{fonte.total}</td>
                              <td className="py-1 text-right tabular-nums text-muted-foreground">
                                {fonte.ms ? `${fonte.ms} ms` : "—"}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="analise" active={aba === "analise"} className="space-y-3">
                <Card>
                  <CardHeader className="mb-2">
                    <CardTitle icon={<Sparkles size={16} className="text-primary" />}>Análise do Hermes</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <textarea
                      value={pergunta}
                      onChange={(event) => setPergunta(event.target.value)}
                      rows={3}
                      placeholder={`Pergunta (por omissão: o que faz, com quem contrata, que riscos e o que verificar — ancorada nos números de ${recolha.nome}).`}
                      className="w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/40"
                    />
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="text-xs">
                        <span className="mb-1 block text-muted-foreground">Profundidade</span>
                        <select
                          value={profundidade}
                          onChange={(event) => setProfundidade(event.target.value as "rapida" | "profunda")}
                          className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                        >
                          <option value="rapida">Resposta rápida</option>
                          <option value="profunda">Investigação profunda</option>
                        </select>
                      </label>
                      <label className="min-w-[260px] flex-1 text-xs">
                        <span className="mb-1 block text-muted-foreground">
                          Skill (método) — {skills ? `${skills.total} na biblioteca` : "a carregar"}
                        </span>
                        <select
                          value={skillId}
                          onChange={(event) => setSkillId(event.target.value)}
                          className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                        >
                          <option value="">Deixar o Hermes escolher (ou criar)</option>
                          {(skills?.skills ?? []).map((skill) => (
                            <option key={skill.id} value={skill.id}>
                              {skill.nome} · {skill.passos} passos · {skill.usos} usos
                            </option>
                          ))}
                        </select>
                      </label>
                      <Button onClick={() => void correrAnalise()} loading={aAnalisar} icon={<Sparkles size={15} />}>
                        Analisar
                      </Button>
                    </div>
                    {erroAnalise ? (
                      <p className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                        <AlertTriangle size={14} /> {erroAnalise}
                      </p>
                    ) : null}
                  </CardContent>
                </Card>

                {analise ? (
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
                    <Card>
                      <CardHeader className="mb-2">
                        <CardTitle>
                          Resposta {analise.mode === "factual" ? "(modo factual)" : analise.mode === "empty" ? "(sem evidências)" : ""}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3 text-sm">
                        <p className="whitespace-pre-wrap">{analise.text}</p>
                        {analise.skill ? (
                          <p className="text-[11px] text-muted-foreground">
                            Skill seguida: <span className="text-foreground">{analise.skill.name}</span>
                            {analise.skill.mode ? ` · ${analise.skill.mode}` : ""}
                            {analise.skill_imposta ? " · imposta no painel" : ""}
                          </p>
                        ) : null}
                        {analise.followups?.length ? (
                          <div className="flex flex-wrap gap-1.5">
                            {analise.followups.map((seguinte) => (
                              <button
                                key={seguinte}
                                type="button"
                                onClick={() => setPergunta(seguinte)}
                                className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                              >
                                {seguinte}
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </CardContent>
                    </Card>
                    <Card className="max-h-[560px] overflow-y-auto">
                      <CardHeader className="mb-2">
                        <CardTitle>Evidências ({analise.evidence.length})</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2 text-xs">
                        {analise.evidence.map((item) => (
                          <div key={item.n} className="border-b border-white/5 pb-1.5">
                            <p>
                              <span className="mr-1 font-medium text-primary">[{item.n}]</span>
                              {item.title}
                            </p>
                            <p className="text-muted-foreground">
                              {item.source}
                              {item.date ? ` · ${texto(item.date).slice(0, 10)}` : ""}
                            </p>
                          </div>
                        ))}
                        {!analise.evidence.length ? (
                          <p className="text-muted-foreground">Sem evidências citadas.</p>
                        ) : null}
                      </CardContent>
                    </Card>
                  </div>
                ) : null}
              </TabsContent>
            </Tabs>
          </>
        ) : null}
      </div>

      {!recolha ? (
        <div className="shrink-0 border-t border-white/8 px-4 py-2 text-[11px] text-muted-foreground">
          {meta
            ? `${meta.limites.fontes} fontes · até ${meta.limites.nos_grafo} nós no grafo · ${meta.limites.paralelo} recolhas em paralelo (limite ${meta.limites.timeout_fonte}s por fonte)`
            : "A carregar o catálogo de fontes…"}
        </div>
      ) : null}
    </div>
  );
}
