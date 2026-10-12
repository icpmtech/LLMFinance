/**
 * Risco e mercado — os dois blocos da descoberta que respondem, com números,
 * às duas perguntas que se fazem antes de decidir sobre uma empresa:
 *
 * 1. **Risco** (`risco_service.risco_empresa`) — qual é o nível, o que o puxa
 *    para cima e quanto do modelo está efetivamente coberto por dados.
 * 2. **Mercado** (`mercado_service.empresa`) — de quem depende, onde está o
 *    valor por CPV, como evoluiu e que alertas o padrão de compra levanta.
 *
 * Nada é calculado no browser além de contas de apresentação (percentagens e
 * somas de barras): os limiares e os pontos vêm do servidor.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { formatCompact, formatMoney } from "../graph/graphStudio";
import { Cartao } from "./DescobertaDecisao";
import type { DescobertaMercado, DescobertaRisco, RiscoComponente } from "../../descobertaApi";

/* ------------------------------------------------------------------ estilo */

const EIXO = "#8b95a5";
const GRADE = "rgba(255,255,255,0.06)";

/** Pontos (0–100) a partir dos quais um componente conta como sinal, não ruído. */
const LIMIAR_FATOR = 50;
const LIMIAR_VIGIAR = 25;

const CORES_ALERTA: Record<string, string> = {
  alta: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  média: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  baixa: "border-white/10 bg-white/5 text-muted-foreground",
};

const ESTADO_CAE: Record<string, string> = {
  compativel: "text-emerald-300",
  compatível: "text-emerald-300",
  parcial: "text-amber-300",
  desconhecida: "text-muted-foreground",
  incompativel: "text-rose-300",
  incompatível: "text-rose-300",
};

function corDoComponente(item: RiscoComponente): string {
  if (!item.disponivel) return "#475569";
  const pontos = item.pontos ?? 0;
  if (pontos >= LIMIAR_FATOR) return "#fb7185";
  if (pontos >= LIMIAR_VIGIAR) return "#fbbf24";
  if (pontos > 0) return "#2dd4bf";
  return "#475569";
}

const pct = (valor: number | null | undefined, decimais = 1) =>
  valor === null || valor === undefined ? "—" : `${(valor * 100).toFixed(decimais)} %`;

const num = (valor: number | null | undefined, decimais = 0) =>
  valor === null || valor === undefined ? "—" : valor.toLocaleString("pt-PT", { minimumFractionDigits: decimais, maximumFractionDigits: decimais });

/* ------------------------------------------------------------------- risco */

function MedidorRisco({ risco }: { risco: DescobertaRisco }) {
  const score = risco.score ?? 0;
  const dados = [{ nome: "score", valor: score, fill: risco.cor || "#a3e635" }];
  return (
    <div className="flex items-center gap-4">
      <div className="relative h-[132px] w-[132px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            data={dados}
            startAngle={212}
            endAngle={-32}
            innerRadius="74%"
            outerRadius="100%"
            barSize={16}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} axisLine={false} />
            <RadialBar dataKey="valor" background={{ fill: "rgba(255,255,255,0.06)" }} cornerRadius={8} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tabular-nums">{num(risco.score, 1)}</span>
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">/ 100</span>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5 text-xs">
        <div className="flex items-center gap-2">
          <span className="rounded-full border px-2 py-0.5 text-[11px] font-medium" style={{ borderColor: `${risco.cor}55`, color: risco.cor }}>
            {risco.nivel_label || risco.nivel}
          </span>
          <span className="text-muted-foreground">faixa {risco.faixa || "—"}</span>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <div className="flex justify-between gap-2 border-b border-white/5">
            <dt className="text-muted-foreground">Cobertura</dt>
            <dd className="tabular-nums">{pct(risco.cobertura, 0)}</dd>
          </div>
          <div className="flex justify-between gap-2 border-b border-white/5">
            <dt className="text-muted-foreground">Confiança</dt>
            <dd>{risco.confianca || "—"}</dd>
          </div>
          <div className="flex justify-between gap-2 border-b border-white/5">
            <dt className="text-muted-foreground">Método</dt>
            <dd className="truncate">{risco.metodo_label || risco.metodo || "—"}</dd>
          </div>
          <div className="flex justify-between gap-2 border-b border-white/5">
            <dt className="text-muted-foreground">Sinais ativos</dt>
            <dd className="tabular-nums">{(risco.componentes || []).filter((item) => (item.pontos ?? 0) > 0).length}</dd>
          </div>
        </dl>
        {risco.avisos?.length ? (
          <p className="flex items-start gap-1.5 pt-0.5 text-[11px] text-amber-200">
            <Info size={12} className="mt-0.5 shrink-0" />
            {risco.avisos[0]}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function FatoresDoRisco({ risco }: { risco: DescobertaRisco }) {
  const componentes = [...(risco.componentes || [])].sort((a, b) => (b.contributo || 0) - (a.contributo || 0));
  const dados = componentes.map((item) => ({
    label: item.label,
    contributo: item.contributo || 0,
    pontos: item.pontos ?? 0,
    peso: (item.peso_efetivo || 0) * 100,
    evidencia: (item.evidencia || [])[0] || (item.disponivel ? "" : "sem dados no portal"),
    cor: corDoComponente(item),
    disponivel: item.disponivel,
  }));
  const ativos = dados.filter((item) => item.contributo > 0);
  if (!ativos.length) {
    return <p className="text-xs text-muted-foreground">Nenhum sinal com pontos suficientes para puxar o risco — o score vem de sinais fracos distribuídos.</p>;
  }
  return (
    <div style={{ height: Math.max(150, dados.length * 26) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={dados} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRADE} horizontal={false} />
          <XAxis type="number" stroke={EIXO} fontSize={11} tickLine={false} axisLine={false} unit=" pts" />
          <YAxis type="category" dataKey="label" stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} width={132} />
          <ReferenceLine x={10} stroke={EIXO} strokeDasharray="3 3" />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const linha = payload[0].payload as (typeof dados)[number];
              return (
                <div className="max-w-[300px] rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs shadow-xl">
                  <p className="font-semibold">{linha.label}</p>
                  <p className="text-muted-foreground">{linha.pontos} pts × peso {linha.peso.toFixed(1)} % = {linha.contributo} pts do score</p>
                  {linha.evidencia ? <p className="mt-1 text-muted-foreground">{linha.evidencia}</p> : null}
                </div>
              );
            }}
          />
          <Bar dataKey="contributo" radius={[0, 6, 6, 0]} barSize={14}>
            {dados.map((item) => (
              <Cell key={item.label} fill={item.cor} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function TabelaComponentes({ risco }: { risco: DescobertaRisco }) {
  const componentes = risco.componentes || [];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pb-1 font-medium">Componente</th>
            <th className="pb-1 text-right font-medium">Pontos</th>
            <th className="pb-1 text-right font-medium">Peso</th>
            <th className="pb-1 text-right font-medium">Contributo</th>
            <th className="pb-1 pl-3 font-medium">Evidência</th>
          </tr>
        </thead>
        <tbody>
          {componentes.map((item) => (
            <tr key={item.id} className={`border-t border-white/5 ${item.disponivel ? "" : "text-muted-foreground/60"}`}>
              <td className="py-1 pr-2">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: corDoComponente(item) }} />
                  <span className="truncate" title={item.descricao}>{item.label}</span>
                </span>
              </td>
              <td className="py-1 text-right tabular-nums">{item.disponivel ? num(item.pontos, 0) : "—"}</td>
              <td className="py-1 text-right tabular-nums">{pct(item.peso_efetivo || item.peso, 0)}</td>
              <td className="py-1 text-right tabular-nums">{item.contributo ? `${num(item.contributo, 1)} pts` : "—"}</td>
              <td className="max-w-[240px] truncate py-1 pl-3 text-muted-foreground" title={(item.evidencia || []).join(" · ")}>
                {(item.evidencia || [])[0] || "sem dados"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        Contributo = pontos × peso efetivo. O peso efetivo sobe quando faltam dados noutros sinais (método{" "}
        {risco.metodo_label || risco.metodo}).
      </p>
    </div>
  );
}

function PainelRisco({ risco }: { risco: DescobertaRisco }) {
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      <Cartao titulo="Nível de risco" porque="Prioridade de análise (0–100), não probabilidade de crime.">
        <MedidorRisco risco={risco} />
      </Cartao>
      <Cartao titulo="O que puxa o risco" porque="Pontos que cada sinal entrega ao score — os pesos não são todos iguais.">
        <FatoresDoRisco risco={risco} />
      </Cartao>
      <Cartao
        titulo="Componentes do modelo"
        porque="Transparência: o que é medido, com que peso, com que evidência e o que ficou sem dados."
        className="xl:col-span-2"
      >
        <TabelaComponentes risco={risco} />
      </Cartao>
    </div>
  );
}

/* ----------------------------------------------------------------- mercado */

function EvolucaoDoMercado({ mercado }: { mercado: DescobertaMercado }) {
  const evolucao: NonNullable<DescobertaMercado["evolucao"]> = mercado.evolucao ?? {};
  const anos = evolucao.anos || [];
  const valores = evolucao.valores || [];
  const dados = anos.map((ano, indice) => ({ ano: String(ano), valor: Number(valores[indice] ?? 0) }));
  if (!dados.length) return <p className="text-xs text-muted-foreground">Sem série temporal de contratos.</p>;
  const ordenados = [...dados].sort((a, b) => a.valor - b.valor);
  const mediana = ordenados[Math.floor(ordenados.length / 2)].valor;
  return (
    <div>
      <div style={{ height: 170 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={dados} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRADE} vertical={false} />
            <XAxis dataKey="ano" stroke={EIXO} fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} tickFormatter={(valor: number) => formatCompact(valor)} width={54} />
            <ReferenceLine y={mediana} stroke={EIXO} strokeDasharray="3 3" label={{ value: "mediana", position: "right", fill: EIXO, fontSize: 10 }} />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const valor = Number((payload[0].payload as { valor: number }).valor);
                return (
                  <div className="rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs shadow-xl">
                    <p className="font-semibold">{label}</p>
                    <p className="tabular-nums">{formatMoney(valor)}</p>
                    <p className="text-muted-foreground">{(mediana ? (valor / mediana - 1) * 100 : 0).toFixed(0)} % face à mediana</p>
                  </div>
                );
              }}
            />
            <Bar dataKey="valor" fill="#38bdf8" radius={[5, 5, 0, 0]} barSize={34} />
            <Line type="monotone" dataKey="valor" stroke="#fbbf24" strokeWidth={1.5} dot={{ r: 2.5 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">Anos com contratos</dt>
          <dd className="tabular-nums">{evolucao.n_anos ?? dados.length}</dd>
        </div>
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">Variação (1.º→último)</dt>
          <dd className={`tabular-nums ${(evolucao.variacao ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>{pct(evolucao.variacao, 0)}</dd>
        </div>
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">CAGR</dt>
          <dd className={`tabular-nums ${(evolucao.cagr ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>{pct(evolucao.cagr, 1)}</dd>
        </div>
      </dl>
    </div>
  );
}

function Dependentes({ mercado }: { mercado: DescobertaMercado }) {
  const dependencia: NonNullable<DescobertaMercado["dependencia"]> = mercado.dependencia ?? {};
  const entidades = [...(mercado.entidades || [])].slice(0, 8).reverse();
  const dados = entidades.map((entidade) => ({
    nome: entidade.nome || entidade.nif,
    quota: (entidade.quota || 0) * 100,
    valor: entidade.valor || 0,
    contratos: entidade.contratos || 0,
  }));
  return (
    <div>
      {dados.length ? (
        <div style={{ height: Math.max(140, dados.length * 30) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={dados} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={GRADE} horizontal={false} />
              <XAxis type="number" stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} unit=" %" domain={[0, 100]} />
              <YAxis type="category" dataKey="nome" stroke={EIXO} fontSize={10} tickLine={false} axisLine={false} width={132} />
              <ReferenceLine x={LIMIAR_FATOR} stroke="#fb7185" strokeDasharray="3 3" label={{ value: "dependência", position: "top", fill: "#fb7185", fontSize: 9 }} />
              <Tooltip
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const linha = payload[0].payload as (typeof dados)[number];
                  return (
                    <div className="max-w-[260px] rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs shadow-xl">
                      <p className="truncate font-semibold">{linha.nome}</p>
                      <p className="tabular-nums">{formatMoney(linha.valor)} · {linha.contratos} contrato(s)</p>
                      <p className="text-muted-foreground">{pct(linha.quota / 100)} do valor da empresa</p>
                    </div>
                  );
                }}
              />
              <Bar dataKey="quota" radius={[0, 6, 6, 0]} barSize={15}>
                {dados.map((item, indice) => (
                  <Cell key={item.nome} fill={indice === dados.length - 1 ? "#fb7185" : "#2dd4bf"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Sem compradores identificados.</p>
      )}
      <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">Maior comprador</dt>
          <dd className="tabular-nums">{pct(dependencia.maior_quota, 0)}</dd>
        </div>
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">Compradores</dt>
          <dd className="tabular-nums">{mercado.entidades_distintas ?? dependencia.n_entidades ?? "—"}</dd>
        </div>
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">HHI</dt>
          <dd className="tabular-nums">{num(dependencia.hhi, 3)}</dd>
        </div>
        <div className="rounded-lg border border-white/5 px-2 py-1">
          <dt className="text-muted-foreground">Sem concurso</dt>
          <dd className="tabular-nums">{pct(mercado.taxa_sem_concurso, 0)}</dd>
        </div>
      </dl>
    </div>
  );
}

function Cpvs({ mercado }: { mercado: DescobertaMercado }) {
  const cpvs = [...(mercado.cpvs || [])].slice(0, 10);
  if (!cpvs.length) return <p className="text-xs text-muted-foreground">Sem contratos classificados por CPV.</p>;
  const maximo = Math.max(...cpvs.map((cpv) => cpv.quota || 0), 0.0001);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pb-1 font-medium">CPV</th>
            <th className="pb-1 font-medium">Peso no valor</th>
            <th className="pb-1 text-right font-medium">Contratos</th>
            <th className="pb-1 text-right font-medium">Valor</th>
            <th className="pb-1 pl-3 font-medium">Valor médio</th>
          </tr>
        </thead>
        <tbody>
          {cpvs.map((cpv) => (
            <tr key={cpv.classe} className="border-t border-white/5">
              <td className="py-1 pr-2">
                <span className="font-medium">{cpv.classe}</span>
                {cpv.divisao && cpv.divisao !== cpv.classe ? <span className="ml-1 text-muted-foreground">div. {cpv.divisao}</span> : null}
              </td>
              <td className="w-[38%] py-1 pr-2">
                <span className="flex items-center gap-2">
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                    <span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-sky-400" style={{ width: `${((cpv.quota || 0) / maximo) * 100}%` }} />
                  </span>
                  <span className="w-10 shrink-0 text-right tabular-nums">{pct(cpv.quota, 0)}</span>
                </span>
              </td>
              <td className="py-1 text-right tabular-nums">{cpv.contratos ?? "—"}</td>
              <td className="py-1 text-right tabular-nums">{formatMoney(cpv.valor || 0)}</td>
              <td className="py-1 pl-3 text-right tabular-nums text-muted-foreground">
                {cpv.contratos ? formatMoney((cpv.valor || 0) / cpv.contratos) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PainelMercado({ mercado }: { mercado: DescobertaMercado }) {
  const alertas = mercado.alertas || [];
  const compatibilidade = mercado.compatibilidade;
  const cae = mercado.cae;
  return (
    <div className="grid gap-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Cartao titulo="Evolução do valor contratado" porque="Carteira a crescer ou a secar — o que decide se vale manter a relação comercial.">
          <EvolucaoDoMercado mercado={mercado} />
        </Cartao>
        <Cartao titulo="Dependência de compradores" porque="Quanto do valor vem de um só comprador — a linha vermelha é o limiar de dependência (50 %).">
          <Dependentes mercado={mercado} />
        </Cartao>
      </div>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,360px)]">
        <Cartao titulo="Onde está o valor (CPV)" porque="Concentração por classe de compra: define quem são os pares e o que comparar.">
          <Cpvs mercado={mercado} />
        </Cartao>
        <div className="grid gap-3">
          <Cartao titulo={`Alertas de padrão (${alertas.length})`} porque="Sinais do próprio perfil de compra: concentração, falta de concurso, CAE, quedas.">
            {alertas.length ? (
              <ul className="space-y-1.5 text-[11px]">
                {alertas.map((alerta) => (
                  <li key={`${alerta.tipo}-${alerta.detalhe}`} className={`flex items-start gap-1.5 rounded-lg border px-2 py-1.5 ${CORES_ALERTA[alerta.severidade] ?? CORES_ALERTA.baixa}`}>
                    {alerta.severidade === "alta" ? <ShieldAlert size={12} className="mt-0.5 shrink-0" /> : <AlertTriangle size={12} className="mt-0.5 shrink-0" />}
                    <span>
                      <span className="font-medium">{alerta.detalhe}</span>
                      <span className="ml-1 opacity-70">({alerta.tipo.replace(/_/g, " ")})</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">Sem alertas de padrão.</p>
            )}
            {mercado.perfil ? <p className="mt-2 text-[11px] text-muted-foreground">Perfil: {mercado.perfil}</p> : null}
          </Cartao>
          <Cartao titulo="CAE e compatibilidade" porque="Se a atividade registada bate com o que a empresa vende ao Estado.">
            <div className="space-y-1.5 text-[11px]">
              <p className="flex justify-between gap-2 border-b border-white/5 pb-1">
                <span className="text-muted-foreground">CAE principal</span>
                <span className="truncate text-right">{cae?.cae_principal_label || cae?.cae_principal || "—"}</span>
              </p>
              <p className="flex justify-between gap-2 border-b border-white/5 pb-1">
                <span className="text-muted-foreground">Concelho</span>
                <span>{cae?.concelho || "—"}</span>
              </p>
              <p className="flex justify-between gap-2 border-b border-white/5 pb-1">
                <span className="text-muted-foreground">Situação</span>
                <span>{cae?.situacao || "—"}</span>
              </p>
              <p className="flex justify-between gap-2 border-b border-white/5 pb-1">
                <span className="text-muted-foreground">Compatibilidade</span>
                <span className={ESTADO_CAE[compatibilidade?.grau || ""] ?? "text-muted-foreground"}>
                  {compatibilidade?.grau || "—"} · {num(compatibilidade?.score, 0)}
                </span>
              </p>
              {compatibilidade?.motivo ? <p className="text-muted-foreground">{compatibilidade.motivo}</p> : null}
            </div>
          </Cartao>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ página */

export default function DescobertaRiscoMercado({
  risco,
  mercado,
}: {
  risco?: DescobertaRisco | null;
  mercado?: DescobertaMercado | null;
}) {
  const temMercado = Boolean(mercado && (mercado.contratos || mercado.valor || mercado.cae?.cae_principal));
  if (!risco && !temMercado) {
    return <p className="text-xs text-muted-foreground">Sem risco nem dados de mercado para esta empresa.</p>;
  }
  return (
    <div className="grid gap-3">
      {risco?.score !== null && risco?.score !== undefined ? <PainelRisco risco={risco} /> : null}
      {risco && (risco.score === null || risco.score === undefined) ? (
        <p className="text-xs text-muted-foreground">Sem contratos suficientes para pontuar o risco desta empresa.</p>
      ) : null}
      {temMercado && mercado ? <PainelMercado mercado={mercado} /> : null}
    </div>
  );
}
