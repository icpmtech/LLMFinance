/**
 * **Conjunto** — comparação de várias empresas na Descoberta.
 *
 * Uma empresa responde «o que é isto?»; o conjunto responde ao que só existe com
 * duas ou mais: quem é maior, quem depende mais de um só comprador, o que
 * partilham e o que verificar primeiro. Os números vêm todos do servidor
 * (`api/descoberta_conjunto.py`), calculados com o mesmo motor do painel
 * individual — por isso batem certo com o painel de cada empresa.
 */
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Cell,
} from "recharts";
import { AlertTriangle, GitCompareArrows, Info, Plus, ShieldAlert, X } from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "../ui";
import { GraphCanvas } from "../graph/GraphCanvas";
import { formatCompact, formatMoney, toStudioGraph, type GraphMetric, type StudioGraph } from "../graph/graphStudio";
import DescobertaNodeFicha from "./DescobertaNodeFicha";
import { compararConjunto, resolverEmpresa, type ConjuntoMetrica, type DescobertaConjunto } from "../../descobertaApi";

/* ------------------------------------------------------------------ estilo */

const CORES = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#4ade80", "#f472b6", "#60a5fa"];
const EIXO = "#8b95a5";
const GRADE = "rgba(255,255,255,0.06)";

const SEVERIDADE: Record<string, { label: string; className: string }> = {
  alerta: { label: "Alertar", className: "border-rose-500/30 bg-rose-500/10 text-rose-200" },
  aviso: { label: "Vigiar", className: "border-amber-500/30 bg-amber-500/10 text-amber-200" },
  info: { label: "Nota", className: "border-white/10 bg-white/5 text-muted-foreground" },
};

const texto = (valor: unknown): string => (valor === null || valor === undefined ? "" : String(valor));

function formataValor(metrica: ConjuntoMetrica, valor: number | null): string {
  if (valor === null || valor === undefined) return "—";
  if (metrica.id === "valor_total") return formatMoney(valor);
  if (metrica.unidade === "taxa") return `${Math.round(valor * 100)} %`;
  if (metrica.unidade.startsWith("%")) return `${valor.toFixed(1)} %`;
  if (metrica.unidade === "rácio") return valor.toFixed(2);
  if (metrica.unidade === "índice") return valor.toFixed(3);
  return Number.isInteger(valor) ? valor.toLocaleString("pt-PT") : valor.toFixed(1);
}

/* -------------------------------------------------------------- comparação */

function TabelaComparacao({ conjunto }: { conjunto: DescobertaConjunto }) {
  const empresas = conjunto.empresas;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pb-1 font-medium">Métrica</th>
            {empresas.map((empresa, indice) => (
              <th key={empresa.nif} className="pb-1 text-right font-medium">
                <span className="flex items-center justify-end gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: CORES[indice % CORES.length] }} />
                  <span className="max-w-[160px] truncate" title={empresa.nome}>
                    {empresa.nome}
                  </span>
                </span>
              </th>
            ))}
            <th className="pb-1 pl-3 font-medium">Melhor</th>
          </tr>
        </thead>
        <tbody>
          {conjunto.comparacao.map((metrica) => (
            <tr key={metrica.id} className="border-t border-white/5">
              <td className="py-1 pr-2" title={metrica.porque}>
                <span className="block truncate font-medium">{metrica.label}</span>
                <span className="block truncate text-[10px] text-muted-foreground">{metrica.porque}</span>
              </td>
              {empresas.map((empresa) => {
                const valor = metrica.valores.find((item) => item.nif === empresa.nif);
                const destaque = valor?.melhor
                  ? "text-emerald-300 font-semibold"
                  : metrica.pior?.nif === empresa.nif
                    ? "text-amber-300"
                    : "";
                return (
                  <td key={empresa.nif} className={`py-1 text-right tabular-nums ${destaque}`}>
                    {formataValor(metrica, valor?.valor ?? null)}
                  </td>
                );
              })}
              <td className="max-w-[160px] truncate py-1 pl-3 text-muted-foreground">
                {metrica.melhor ? `${metrica.melhor.nome} (${metrica.melhor.texto})` : "sem dados"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        Verde: melhor da linha · Âmbar: o mais exposto. Métricas sem valores em nenhuma empresa ficam a «—».
      </p>
    </div>
  );
}

function RadarPerfis({ conjunto }: { conjunto: DescobertaConjunto }) {
  const dimensoes = conjunto.perfil.dimensoes;
  const dados = dimensoes.map((dimensao) => {
    const linha: Record<string, string | number> = { dimensao: dimensao.label };
    conjunto.perfil.series.forEach((serie) => {
      linha[serie.nome] = serie.valores[dimensao.id] ?? 0;
    });
    return linha;
  });
  if (!dimensoes.length) return <p className="text-xs text-muted-foreground">Sem perfil calculado.</p>;
  return (
    <div style={{ height: 340 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={dados} outerRadius="72%">
          <PolarGrid stroke={GRADE} />
          <PolarAngleAxis dataKey="dimensao" tick={{ fill: EIXO, fontSize: 10 }} />
          <PolarRadiusAxis domain={[0, 100]} tick={{ fill: EIXO, fontSize: 9 }} axisLine={false} />
          {conjunto.perfil.series.map((serie, indice) => (
            <Radar
              key={serie.nif}
              name={serie.nome}
              dataKey={serie.nome}
              stroke={CORES[indice % CORES.length]}
              fill={CORES[indice % CORES.length]}
              fillOpacity={0.12}
              strokeWidth={2}
            />
          ))}
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className="max-w-[280px] rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs shadow-xl">
                  <p className="font-semibold">{label}</p>
                  {payload.map((item) => (
                    <p key={item.name} className="flex justify-between gap-3">
                      <span className="truncate text-muted-foreground">{item.name}</span>
                      <span className="tabular-nums">{Math.round(Number(item.value))}/100</span>
                    </p>
                  ))}
                </div>
              );
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Cruzamentos({ conjunto }: { conjunto: DescobertaConjunto }) {
  const grupos: { id: keyof DescobertaConjunto["cruzamentos"]; titulo: string; chave: (item: NonNullable<DescobertaConjunto["cruzamentos"]["cpvs"]>[number]) => string }[] = [
    { id: "adjudicantes", titulo: "Compradores comuns", chave: (item) => texto(item.nome || item.nif) },
    { id: "cpvs", titulo: "Classificações comuns", chave: (item) => `${texto(item.cpv)} ${texto(item.descricao)}`.trim() },
    { id: "pessoas", titulo: "Pessoas comuns", chave: (item) => texto(item.nome || item.nif) },
    { id: "processos", titulo: "Processos comuns", chave: (item) => `${texto(item.processo || item.especie)} ${texto(item.especie)}`.trim() },
  ];
  const algum = grupos.some((grupo) => ((conjunto.cruzamentos[grupo.id] as unknown[]) || []).length);
  if (!algum) {
    return <p className="text-xs text-muted-foreground">Estas empresas não partilham compradores, classificações, pessoas nem processos na amostra.</p>;
  }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {grupos.map((grupo) => {
        const itens = (conjunto.cruzamentos[grupo.id] as unknown[]) || [];
        if (!itens.length) return null;
        return (
          <div key={String(grupo.id)} className="rounded-xl border border-white/5 p-2.5">
            <p className="mb-1.5 text-xs font-semibold">
              {grupo.titulo} ({itens.length})
            </p>
            <ul className="max-h-56 space-y-1 overflow-y-auto text-[11px]">
              {(itens as NonNullable<DescobertaConjunto["cruzamentos"]["cpvs"]>).map((item, indice) => (
                <li key={`${grupo.chave(item)}-${indice}`} className="border-b border-white/5 pb-1">
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 truncate" title={grupo.chave(item)}>
                      {grupo.chave(item)}
                    </span>
                    <span className="shrink-0 text-right tabular-nums text-muted-foreground">
                      {item.n_empresas} empresas
                      {item.valor ? ` · ${formatMoney(item.valor)}` : ""}
                    </span>
                  </div>
                  <p className="truncate text-[10px] text-muted-foreground">{item.empresas_nome.join(" · ")}</p>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function GraficoValores({ conjunto }: { conjunto: DescobertaConjunto }) {
  const metrica = conjunto.comparacao.find((item) => item.id === "valor_total");
  if (!metrica) return null;
  const dados = metrica.valores.map((valor, indice) => ({
    nome: valor.nome.length > 22 ? `${valor.nome.slice(0, 20)}…` : valor.nome,
    valor: valor.valor ?? 0,
    cor: CORES[indice % CORES.length],
  }));
  return (
    <div style={{ height: Math.max(180, dados.length * 34) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={dados} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRADE} horizontal={false} />
          <XAxis type="number" stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} tickFormatter={(valor: number) => formatCompact(valor)} />
          <YAxis type="category" dataKey="nome" stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} width={150} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            formatter={(valor) => formatMoney(Number(valor))}
          />
          <Bar dataKey="valor" radius={[0, 6, 6, 0]} barSize={16}>
            {dados.map((item) => (
              <Cell key={item.nome} fill={item.cor} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------- vista */

export default function DescobertaConjunto({
  onAbrirEmpresa,
}: {
  onAbrirEmpresa: (nif: string) => void;
}) {
  const [consulta, setConsulta] = useState("");
  const [alvos, setAlvos] = useState<{ nif: string; nome: string }[]>([]);
  const [candidatos, setCandidatos] = useState<{ nif: string; nome: string }[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const [aComparar, setAComparar] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [conjunto, setConjunto] = useState<DescobertaConjunto | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [metric, setMetric] = useState<GraphMetric>("valor");
  const [vista, setVista] = useState<"network" | "hierarchical" | "circular">("network");
  const [fichaNo, setFichaNo] = useState<string | null>(null);
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);

  const grafoStudio = useMemo<StudioGraph | null>(
    () => toStudioGraph(conjunto?.grafo ?? null, metric),
    [conjunto?.grafo, metric],
  );
  const noFicha = useMemo(
    () => (grafoStudio && fichaNo ? grafoStudio.nodes.find((no) => no.id === fichaNo) ?? null : null),
    [fichaNo, grafoStudio],
  );

  const juntar = (nif: string, nome: string) => {
    setAlvos((atual) => (atual.some((alvo) => alvo.nif === nif || alvo.nome === nome) ? atual : [...atual, { nif, nome }]));
    setConsulta("");
    setCandidatos([]);
  };

  const procurar = async () => {
    const texto = consulta.trim();
    if (texto.length < 2) return;
    setAProcurar(true);
    setErro(null);
    try {
      const resolucao = await resolverEmpresa(texto);
      const itens = (resolucao.items || []).filter((item) => item.nif);
      // Um NIF exato com um só resultado entra logo; o nome vem do cadastro para
      // o chip não ficar só com o número.
      if (/^\d{9}$/.test(texto) || itens.length === 1) {
        const alvo = itens.find((item) => textoValido(item.nif) === texto) || itens[0];
        juntar(texto, textoValido(alvo?.nome) || texto);
        return;
      }
      if (itens.length > 1) {
        setCandidatos(itens.map((item) => ({ nif: textoValido(item.nif), nome: textoValido(item.nome) || textoValido(item.nif) })));
        return;
      }
      setCandidatos([]);
      setErro(resolucao.detail || "Nada encontrado para esse nome ou NIF.");
    } catch (falha) {
      // O resolver pode não conhecer o número (empresa sem nome no cadastro): o
      // NIF continua a valer como alvo, porque o servidor o resolve depois.
      if (/^\d{9}$/.test(texto)) {
        juntar(texto, texto);
        return;
      }
      setErro(falha instanceof Error ? falha.message : String(falha));
      setCandidatos([]);
    } finally {
      setAProcurar(false);
    }
  };

  const comparar = async () => {
    if (alvos.length < 2) {
      setErro("Indique pelo menos duas empresas para comparar.");
      return;
    }
    setAComparar(true);
    setErro(null);
    setSegundos(0);
    const inicio = Date.now();
    const relogio = window.setInterval(() => setSegundos(Math.round((Date.now() - inicio) / 1000)), 500);
    try {
      const resultado = await compararConjunto(alvos.map((alvo) => alvo.nif), [], { maxEmpresas: 6 });
      setConjunto(resultado);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
      setConjunto(null);
    } finally {
      window.clearInterval(relogio);
      setAComparar(false);
    }
  };

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="mb-2">
          <CardTitle icon={<GitCompareArrows size={16} className="text-primary" />}>Empresas a comparar ({alvos.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            {alvos.map((alvo, indice) => (
              <span
                key={alvo.nif}
                className="flex items-center gap-1.5 rounded-full border px-2.5 py-1"
                style={{ borderColor: `${CORES[indice % CORES.length]}55`, background: `${CORES[indice % CORES.length]}18` }}
              >
                <span className="max-w-[220px] truncate" title={`${alvo.nome} · ${alvo.nif}`}>
                  {alvo.nome || alvo.nif}
                </span>
                <button
                  type="button"
                  className="rounded-full p-0.5 hover:bg-white/10"
                  onClick={() => setAlvos((atual) => atual.filter((item) => item.nif !== alvo.nif))}
                  aria-label={`Remover ${alvo.nome || alvo.nif}`}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
            {!alvos.length ? <span className="text-muted-foreground">Ainda sem empresas — procure por NIF ou nome.</span> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={consulta}
              onChange={(evento) => setConsulta(evento.target.value)}
              onKeyDown={(evento) => {
                if (evento.key === "Enter") void procurar();
              }}
              placeholder="NIF (9 dígitos) ou nome da empresa"
              className="max-w-[320px]"
            />
            <Button variant="outline" onClick={() => void procurar()} loading={aProcurar} disabled={aProcurar || consulta.trim().length < 2}>
              <Plus size={14} /> Adicionar
            </Button>
            <Button onClick={() => void comparar()} loading={aComparar} disabled={aComparar || alvos.length < 2}>
              <GitCompareArrows size={14} /> Comparar {alvos.length >= 2 ? `${alvos.length} empresas` : ""}
            </Button>
            {alvos.length ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setAlvos([]);
                  setConjunto(null);
                }}
              >
                Limpar
              </Button>
            ) : null}
            {aComparar ? (
              <span className="text-muted-foreground">
                A recolher as 16 fontes de cada empresa e a cruzar… {segundos}s
              </span>
            ) : null}
          </div>
          {candidatos.length ? (
            <div className="space-y-1 rounded-xl border border-white/5 p-2">
              <p className="text-muted-foreground">Várias empresas correspondem — escolha uma:</p>
              <div className="flex flex-wrap gap-2">
                {candidatos.map((candidato) => (
                  <Button key={candidato.nif} size="sm" variant="outline" onClick={() => juntar(candidato.nif, candidato.nome)}>
                    {candidato.nome} · {candidato.nif}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
          {erro ? <p className="text-rose-300">{erro}</p> : null}
          <p className="text-[11px] text-muted-foreground">
            Cada empresa é recolhida e analisada como no painel individual; o cruzamento usa as mesmas regras da página de Padrões.
            A primeira comparação de um conjunto novo demora ~15–25 s (recolha + amostra nacional); as seguintes ficam em cache.
          </p>
        </CardContent>
      </Card>

      {conjunto ? (
        <>
          <Card>
            <CardContent className="space-y-1 text-sm">
              <p className="font-medium">{conjunto.leitura}</p>
              <p className="text-[11px] text-muted-foreground">
                {conjunto.pedido.analisadas} empresa(s) analisada(s) · {formatCompact(Number(conjunto.totais.contratos || 0))} contratos ·{" "}
                {formatMoney(Number(conjunto.totais.valor_total || 0))} · gerado {texto(conjunto.gerado_em).slice(11, 19)} UTC
              </p>
              {conjunto.avisos.length ? (
                <p className="flex items-start gap-1.5 text-[11px] text-amber-200">
                  <Info size={12} className="mt-0.5 shrink-0" /> {conjunto.avisos.join(" · ")}
                </p>
              ) : null}
            </CardContent>
          </Card>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader className="mb-2">
                <CardTitle>Comparação métrica a métrica</CardTitle>
              </CardHeader>
              <CardContent>
                <TabelaComparacao conjunto={conjunto} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="mb-2">
                <CardTitle>Perfil de cada empresa</CardTitle>
              </CardHeader>
              <CardContent>
                <RadarPerfis conjunto={conjunto} />
                <p className="text-[10px] text-muted-foreground">Todas as dimensões estão na mesma direção: quanto mais cheio, melhor.</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
            <Card>
              <CardHeader className="mb-2">
                <CardTitle>Escala contratada</CardTitle>
              </CardHeader>
              <CardContent>
                <GraficoValores conjunto={conjunto} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="mb-2">
                <CardTitle>Empresas do conjunto</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 sm:grid-cols-2">
                {conjunto.empresas.map((empresa, indice) => (
                  <button
                    key={empresa.nif}
                    type="button"
                    onClick={() => onAbrirEmpresa(empresa.nif)}
                    className="rounded-xl border border-white/5 p-2.5 text-left transition-colors hover:border-primary/40 hover:bg-white/5"
                  >
                    <p className="flex items-center gap-1.5 text-xs font-semibold">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CORES[indice % CORES.length] }} />
                      <span className="truncate">{empresa.nome}</span>
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">{empresa.nif}</p>
                    <div className="mt-1 grid grid-cols-2 gap-1 text-[11px]">
                      <span className="text-muted-foreground">Contratos</span>
                      <span className="text-right tabular-nums">{formatCompact(empresa.contratos_lidos ?? 0)}</span>
                      <span className="text-muted-foreground">Valor</span>
                      <span className="text-right tabular-nums">{formatMoney(empresa.valor_total ?? 0)}</span>
                      <span className="text-muted-foreground">Maior comprador</span>
                      <span className="text-right tabular-nums">{empresa.top1 === null ? "—" : `${empresa.top1.toFixed(1)} %`}</span>
                      <span className="text-muted-foreground">Risco</span>
                      <span className="text-right tabular-nums" style={{ color: empresa.risco.cor || undefined }}>
                        {empresa.risco.score === null ? "—" : `${empresa.risco.score} (${empresa.risco.nivel_label})`}
                      </span>
                    </div>
                    {empresa.erro ? <p className="mt-1 text-[10px] text-rose-300">{empresa.erro}</p> : null}
                    <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">{empresa.leitura}</p>
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="mb-2">
              <CardTitle>O que as empresas partilham</CardTitle>
            </CardHeader>
            <CardContent>
              <Cruzamentos conjunto={conjunto} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="mb-2">
              <CardTitle>Rede do conjunto</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_220px]">
              {grafoStudio && grafoStudio.nodes.length ? (
                <GraphCanvas
                  graph={grafoStudio}
                  layout={vista}
                  metric={metric}
                  unitLabel="€"
                  heightClass="h-[480px]"
                  labels="selecao"
                  selectedNodeId={noSelecionado}
                  nodeSummary={(no) => `${no.role || no.dimension} · ${formatCompact(no.count)} · ${formatMoney(no.total_value)}`}
                  edgeSummary={(aresta) => `${formatMoney(aresta.value)} · ${formatCompact(aresta.count)}`}
                  onNodeClick={(no) => {
                    setNoSelecionado(no.id);
                    setFichaNo(no.id);
                  }}
                />
              ) : (
                <p className="text-xs text-muted-foreground">Sem rede para este conjunto.</p>
              )}
              <div className="space-y-2 text-xs">
                <div className="flex gap-2">
                  <Button size="sm" variant={metric === "valor" ? "primary" : "outline"} onClick={() => setMetric("valor")}>
                    Valor
                  </Button>
                  <Button size="sm" variant={metric === "contratos" ? "primary" : "outline"} onClick={() => setMetric("contratos")}>
                    Contagem
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(["network", "hierarchical", "circular"] as const).map((opcao) => (
                    <Button key={opcao} size="sm" variant={vista === opcao ? "primary" : "outline"} onClick={() => setVista(opcao)}>
                      {opcao === "network" ? "Rede" : opcao === "hierarchical" ? "Hierarquia" : "Circular"}
                    </Button>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Liga as empresas comparadas pelos compradores, pessoas e processos partilhados (as mesmas ligações que a página de
                  Padrões desenha). Clique num nó para abrir a ficha.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="mb-2">
              <CardTitle>O que verificar primeiro ({conjunto.atencao.length})</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-[11px]">
              {conjunto.atencao.length ? (
                conjunto.atencao.slice(0, 20).map((ponto, indice) => (
                  <div
                    key={`${ponto.nif}-${ponto.titulo}-${indice}`}
                    className={`flex items-start gap-2 rounded-lg border px-2 py-1.5 ${(SEVERIDADE[ponto.severidade] || SEVERIDADE.info).className}`}
                  >
                    {ponto.severidade === "alerta" ? <ShieldAlert size={12} className="mt-0.5 shrink-0" /> : <AlertTriangle size={12} className="mt-0.5 shrink-0" />}
                    <span className="min-w-0">
                      <span className="font-medium">{ponto.titulo}</span>
                      <span className="ml-1 opacity-80">· {ponto.nome}</span>
                      <span className="block text-muted-foreground">{ponto.detalhe}</span>
                      {ponto.verificar ? <span className="block text-muted-foreground">A verificar: {ponto.verificar}</span> : null}
                    </span>
                    <Badge variant="outline" className="ml-auto shrink-0">
                      {(SEVERIDADE[ponto.severidade] || SEVERIDADE.info).label}
                    </Badge>
                  </div>
                ))
              ) : (
                <p className="text-muted-foreground">Sem pontos de atenção no conjunto.</p>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}

      {noFicha && grafoStudio ? (
        <DescobertaNodeFicha
          node={noFicha}
          grafo={grafoStudio}
          secoes={{}}
          onClose={() => setFichaNo(null)}
          onSelecionar={(nodeId) => {
            setNoSelecionado(nodeId);
            setFichaNo(nodeId);
          }}
          onIsolar={() => setFichaNo(null)}
          onVerTipo={() => setFichaNo(null)}
          onEsconderTipo={() => setFichaNo(null)}
          onAbrirNoModulo={(no) => {
            const chave = String(no.key ?? no.id.split(":").slice(1).join(":"));
            setFichaNo(null);
            if (no.dimension === "empresa") onAbrirEmpresa(chave);
          }}
        />
      ) : null}
    </div>
  );
}

/** NIF de um alvo resolvido (o resolver devolve o NIF já normalizado). */
function textoValido(valor: unknown): string {
  return texto(valor);
}
