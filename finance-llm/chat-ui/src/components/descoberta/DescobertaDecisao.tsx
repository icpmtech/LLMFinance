/**
 * Gráficos de **decisão** da descoberta.
 *
 * Cada gráfico responde a uma pergunta que se faz antes de decidir — de que
 * depende a empresa, onde está o valor, como contrata, quanto demora a ficar
 * público, o que puxa o risco — e cada cartão diz, numa linha, porque é que
 * aquele gráfico importa.
 *
 * Todos os números vêm calculados do servidor (`api/descoberta_decisao.py`):
 * nenhum é inferido no browser.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { Badge } from "../ui";
import { formatCompact, formatMoney } from "../graph/graphStudio";
import type { DescobertaDecisao } from "../../descobertaApi";

/* ------------------------------------------------------------------ estilo */

const CORES = ["#2dd4bf", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#f472b6", "#4ade80", "#60a5fa"];
const EIXO = "#8b95a5";
const GRADE = "rgba(255,255,255,0.06)";

const SEVERIDADE: Record<string, { label: string; className: string; icon: typeof AlertTriangle }> = {
  alerta: { label: "Alertar", className: "border-rose-500/30 bg-rose-500/10 text-rose-200", icon: ShieldAlert },
  aviso: { label: "Vigiar", className: "border-amber-500/30 bg-amber-500/10 text-amber-200", icon: AlertTriangle },
  info: { label: "Nota", className: "border-white/10 bg-white/5 text-muted-foreground", icon: Info },
};

function Cursor({ active, payload, titulo }: { active?: boolean; payload?: { payload: unknown }[]; titulo: string }) {
  if (!active || !payload?.length) return null;
  const linha = payload[0].payload as Record<string, unknown>;
  const chaves = Object.keys(linha).filter((chave) => chave !== "id" && chave !== "cor");
  return (
    <div className="max-w-[280px] rounded-xl border border-white/10 bg-[#0d1117] p-2 text-xs shadow-xl">
      <p className="truncate font-semibold">{String(linha[titulo] ?? linha.label ?? linha.ano ?? "")}</p>
      {chaves
        .filter((chave) => chave !== titulo)
        .map((chave) => (
          <p key={chave} className="flex justify-between gap-3">
            <span className="text-muted-foreground">{chave}</span>
            <span className="tabular-nums">
              {typeof linha[chave] === "number"
                ? (linha[chave] as number).toLocaleString("pt-PT")
                : String(linha[chave])}
            </span>
          </p>
        ))}
    </div>
  );
}

function Cartao({
  titulo,
  porque,
  children,
  className = "",
}: {
  titulo: string;
  porque: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`glass-card gradient-border rounded-2xl p-3 ${className}`}>
      <p className="text-sm font-semibold">{titulo}</p>
      <p className="mb-2 text-[11px] text-muted-foreground">{porque}</p>
      {children}
    </div>
  );
}

const curto = (valor: string, limite = 26) => (valor.length > limite ? `${valor.slice(0, limite - 1)}…` : valor);

/* --------------------------------------------------------------- componente */

export function DescobertaDecisao({ decisao }: { decisao: DescobertaDecisao }) {
  const { resumo, concentracao, procedimento, precos, concorrencia, prazos, risco, perfil, atencao } = decisao;

  const concentracaoCurva = concentracao.curva.map((linha) => ({
    ...linha,
    nome: curto(linha.nome, 18),
    valor: Math.round(linha.valor),
  }));

  const componentesRisco = risco.componentes
    .filter((item) => item.disponivel)
    .map((item) => ({
      label: curto(item.label, 30),
      pontos: item.pontos ?? 0,
      contributo: Math.round((item.contributo ?? 0) * 1000) / 10,
    }))
    .sort((a, b) => b.pontos - a.pontos);

  const corRisco = (pontos: number) => (pontos >= 50 ? "#fb7185" : pontos >= 30 ? "#fbbf24" : "#2dd4bf");

  const procedimentoDados = procedimento.itens.map((item, indice) => ({
    nome: curto(item.procedimento, 34),
    contratos: item.contratos,
    quota: item.quota,
    cor: item.ajuste_direto ? "#fb7185" : CORES[indice % CORES.length],
  }));

  const valorPorFaixa = [
    ...precos.itens.map((linha) => ({ ...linha, grupo: `Preço ${linha.faixa}` })),
    ...concorrencia.itens.map((linha) => ({ ...linha, grupo: `Concorrência ${linha.faixa}` })),
  ]
    .filter((linha) => linha.contratos > 0)
    .sort((a, b) => b.valor - a.valor);

  return (
    <div className="space-y-3">
      <div className="glass-card gradient-border rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">Leitura</Badge>
          {risco.nivel_label ? (
            <span
              className="rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
              style={{
                borderColor: `${risco.cor ?? "#94a3b8"}55`,
                background: `${risco.cor ?? "#94a3b8"}22`,
                color: risco.cor ?? "#94a3b8",
              }}
            >
              risco {risco.nivel_label}
              {risco.score !== null && risco.score !== undefined ? ` ${risco.score}/100` : ""}
              {risco.confianca ? ` · confiança ${risco.confianca}` : ""}
            </span>
          ) : null}
          <span className="text-[11px] text-muted-foreground">
            {resumo.contratos_lidos} contratos lidos de {resumo.contratos} · {resumo.anos[0] ?? "—"}–
            {resumo.anos[resumo.anos.length - 1] ?? "—"}
          </span>
        </div>
        <p className="mt-2 text-sm">{decisao.leitura}</p>
      </div>

      <Cartao
        titulo="O que verificar primeiro"
        porque="Regras objetivas que disparam nesta empresa, por severidade — é por aqui que se começa."
      >
        <div className="space-y-1.5">
          {atencao.length ? (
            atencao.map((ponto) => {
              const estilo = SEVERIDADE[ponto.severidade] ?? SEVERIDADE.info;
              const Icone = estilo.icon;
              return (
                <div key={`${ponto.severidade}-${ponto.titulo}`} className={`rounded-xl border px-3 py-2 ${estilo.className}`}>
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Icone size={14} /> {ponto.titulo}
                  </p>
                  <p className="mt-0.5 text-[11.5px] opacity-90">{ponto.detalhe}</p>
                  <p className="mt-0.5 text-[11.5px] opacity-75">→ {ponto.verificar}</p>
                </div>
              );
            })
          ) : (
            <p className="text-xs text-muted-foreground">Nenhuma regra disparou: sem pontos de atenção automáticos.</p>
          )}
        </div>
      </Cartao>

      <Cartao
        titulo="Evolução anual"
        porque="A carteira cresce, estagna ou concentra-se? Valor (barras), contratos e compradores novos (linhas)."
        className="xl:col-span-2"
      >
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={decisao.evolucao} margin={{ left: 8, right: 12, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} vertical={false} />
            <XAxis dataKey="ano" stroke={EIXO} fontSize={11} />
            <YAxis yAxisId="valor" stroke={EIXO} fontSize={11} tickFormatter={(valor) => formatCompact(Number(valor))} />
            <YAxis yAxisId="contratos" orientation="right" stroke={EIXO} fontSize={11} />
            <Tooltip content={<Cursor titulo="ano" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="valor" dataKey="valor" name="Valor (€)" fill="#2dd4bf" radius={[6, 6, 0, 0]} />
            <Line yAxisId="contratos" dataKey="contratos" name="Contratos" stroke="#38bdf8" strokeWidth={2} dot={false} />
            <Line
              yAxisId="contratos"
              dataKey="novos_adjudicantes"
              name="Compradores novos"
              stroke="#fbbf24"
              strokeWidth={1.6}
              strokeDasharray="4 3"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </Cartao>

      <Cartao
        titulo="Curva de concentração (Pareto)"
        porque="Quantos compradores fazem 80% do valor? Poucos compradores é pouca folga negocial."
        className="xl:col-span-2"
      >
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={concentracaoCurva} margin={{ left: 8, right: 12, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} vertical={false} />
            <XAxis dataKey="nome" stroke={EIXO} fontSize={10} interval={0} angle={-18} textAnchor="end" height={54} />
            <YAxis yAxisId="quota" stroke={EIXO} fontSize={11} unit="%" />
            <YAxis yAxisId="acumulada" orientation="right" stroke={EIXO} fontSize={11} domain={[0, 100]} unit="%" />
            <Tooltip content={<Cursor titulo="nome" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <ReferenceLine
              yAxisId="acumulada"
              y={80}
              stroke="#fb7185"
              strokeDasharray="4 3"
              label={{ value: "80%", fontSize: 10, fill: "#fb7185" }}
            />
            <Bar yAxisId="quota" dataKey="quota" name="Quota do comprador (%)" fill="#a78bfa" radius={[6, 6, 0, 0]} />
            <Line
              yAxisId="acumulada"
              dataKey="quota_acumulada"
              name="Acumulada (%)"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={{ r: 2 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <p className="mt-1 text-[11px] text-muted-foreground">
          HHI {concentracao.hhi ?? "—"} · maior comprador {concentracao.top1 ?? "—"}% · três maiores {concentracao.top3 ?? "—"}%
          {concentracao.hhi === null || concentracao.hhi === undefined
            ? ""
            : concentracao.hhi >= 2500
              ? " · carteira concentrada"
              : " · carteira diversificada"}
        </p>
      </Cartao>

      <Cartao titulo="Quem compra" porque="Top de adjudicantes por valor — a dependência lê-se aqui.">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart
            data={concentracao.top.map((linha) => ({ ...linha, nome: curto(linha.nome, 22) }))}
            layout="vertical"
            margin={{ left: 8, right: 16 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} horizontal={false} />
            <XAxis type="number" stroke={EIXO} fontSize={11} unit="%" />
            <YAxis type="category" dataKey="nome" stroke={EIXO} fontSize={10} width={140} />
            <Tooltip content={<Cursor titulo="nome" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="quota" name="Quota (%)" radius={[0, 6, 6, 0]}>
              {concentracao.top.map((linha, indice) => (
                <Cell key={`${linha.nif}-${indice}`} fill={CORES[indice % CORES.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Cartao>

      <Cartao titulo="Onde está o valor (CPV)" porque="Um CPV dominante muda o risco setorial e os pares de comparação.">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart
            data={decisao.cpv.map((linha) => ({
              nome: curto(linha.descricao || linha.cpv, 24),
              quota: linha.quota,
              valor: Math.round(linha.valor),
            }))}
            layout="vertical"
            margin={{ left: 8, right: 16 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} horizontal={false} />
            <XAxis type="number" stroke={EIXO} fontSize={11} unit="%" />
            <YAxis type="category" dataKey="nome" stroke={EIXO} fontSize={10} width={150} />
            <Tooltip content={<Cursor titulo="nome" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="quota" name="Quota (%)" radius={[0, 6, 6, 0]}>
              {decisao.cpv.map((linha, indice) => (
                <Cell key={linha.cpv} fill={CORES[indice % CORES.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Cartao>

      <Cartao titulo="Como contrata (procedimento)" porque="Concurso vs ajuste direto é o sinal de transparência mais direto.">
        <ResponsiveContainer width="100%" height={250}>
          <PieChart>
            <Tooltip content={<Cursor titulo="nome" />} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Pie
              data={procedimentoDados}
              dataKey="contratos"
              nameKey="nome"
              innerRadius={48}
              outerRadius={86}
              paddingAngle={2}
              stroke="none"
            >
              {procedimentoDados.map((linha) => (
                <Cell key={linha.nome} fill={linha.cor} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {procedimento.taxa_ajuste_direto !== null && procedimento.taxa_ajuste_direto !== undefined
            ? `${Math.round(procedimento.taxa_ajuste_direto * 100)}% dos contratos por ajuste direto`
            : "Sem dados de procedimento"}
        </p>
      </Cartao>

      <Cartao titulo="Tamanho dos contratos" porque="Mostra se o negócio vive de muitos contratos pequenos ou de poucos grandes.">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={decisao.escaloes} margin={{ left: 8, right: 12, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} vertical={false} />
            <XAxis dataKey="escalao" stroke={EIXO} fontSize={10} interval={0} angle={-15} textAnchor="end" height={46} />
            <YAxis stroke={EIXO} fontSize={11} />
            <Tooltip content={<Cursor titulo="escalao" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="contratos" name="Contratos" fill="#38bdf8" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Cartao>

      <Cartao titulo="Preço face ao preço base" porque="Adjudicado acima do base pede justificação; abaixo, é desconto.">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={precos.itens} margin={{ left: 8, right: 12, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} vertical={false} />
            <XAxis dataKey="faixa" stroke={EIXO} fontSize={10} interval={0} angle={-15} textAnchor="end" height={50} />
            <YAxis stroke={EIXO} fontSize={11} />
            <Tooltip content={<Cursor titulo="faixa" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="contratos" name="Contratos" radius={[6, 6, 0, 0]}>
              {precos.itens.map((linha, indice) => (
                <Cell key={linha.faixa} fill={linha.faixa.startsWith(">") ? "#fb7185" : CORES[indice % CORES.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="mt-1 text-[11px] text-muted-foreground">
          mediana adjudicado/base {precos.mediana ?? "—"}
          {precos.taxa_aditivo !== null && precos.taxa_aditivo !== undefined
            ? ` · ${Math.round(precos.taxa_aditivo * 100)}% com valor efetivo acima do contratual`
            : ""}
        </p>
      </Cartao>

      <Cartao titulo="Concorrência registada" porque="Sem concorrentes no processo, o preço não foi testado pelo mercado.">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={concorrencia.itens} margin={{ left: 8, right: 12, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} vertical={false} />
            <XAxis dataKey="faixa" stroke={EIXO} fontSize={11} />
            <YAxis stroke={EIXO} fontSize={11} />
            <Tooltip content={<Cursor titulo="faixa" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="contratos" name="Contratos" radius={[6, 6, 0, 0]}>
              {concorrencia.itens.map((linha, indice) => (
                <Cell key={linha.faixa} fill={linha.faixa.startsWith("0") ? "#fb7185" : CORES[indice % CORES.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="mt-1 text-[11px] text-muted-foreground">
          mediana de {concorrencia.mediana ?? "—"} concorrente(s) por contrato ({concorrencia.com_dados} contratos com dados)
        </p>
      </Cartao>

      <Cartao titulo="Prazos do procedimento" porque="Dias entre decisão e publicação: quanto mais alto, mais tarde se pode reagir.">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={prazos.itens} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} horizontal={false} />
            <XAxis type="number" stroke={EIXO} fontSize={11} unit=" d" />
            <YAxis type="category" dataKey="fase" stroke={EIXO} fontSize={10} width={150} />
            <Tooltip content={<Cursor titulo="fase" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="dias" name="Dias (mediana)" fill="#a78bfa" radius={[0, 6, 6, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Cartao>

      <Cartao titulo="Perfil de uma vista" porque="Dimensões normalizadas (100 = melhor). O detalhe mostra sempre o número cru.">
        <ResponsiveContainer width="100%" height={250}>
          <RadarChart data={perfil} outerRadius="72%">
            <PolarGrid stroke={GRADE} />
            <PolarAngleAxis dataKey="label" stroke={EIXO} fontSize={10} />
            <PolarRadiusAxis domain={[0, 100]} stroke={EIXO} fontSize={9} />
            <Tooltip content={<Cursor titulo="label" />} />
            <Radar dataKey="valor" name="Perfil" stroke="#2dd4bf" fill="#2dd4bf" fillOpacity={0.35} />
          </RadarChart>
        </ResponsiveContainer>
        <div className="mt-1 space-y-0.5 text-[11px]">
          {perfil.map((dimensao) => (
            <p key={dimensao.id} className="flex justify-between gap-3">
              <span className="text-muted-foreground">{dimensao.label}</span>
              <span className="truncate tabular-nums">
                {dimensao.valor ?? "—"} · {dimensao.detalhe}
              </span>
            </p>
          ))}
        </div>
      </Cartao>

      <Cartao
        titulo="Risco componente a componente"
        porque="O que puxa o risco para cima (barras) e o peso de cada componente na pontuação final."
      >
        <ResponsiveContainer width="100%" height={Math.max(200, componentesRisco.length * 34)}>
          <BarChart data={componentesRisco} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRADE} horizontal={false} />
            <XAxis type="number" domain={[0, 100]} stroke={EIXO} fontSize={11} />
            <YAxis type="category" dataKey="label" stroke={EIXO} fontSize={10} width={180} />
            <Tooltip content={<Cursor titulo="label" />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="pontos" name="Pontos (0–100)" radius={[0, 6, 6, 0]}>
              {componentesRisco.map((linha) => (
                <Cell key={linha.label} fill={corRisco(linha.pontos)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        {risco.fatores.length ? (
          <div className="mt-2 space-y-0.5 text-[11px]">
            <p className="text-muted-foreground">O que mais pesa:</p>
            {risco.fatores.map((fator, indice) => (
              <p key={`${fator.label}-${indice}`} className="flex justify-between gap-3">
                <span>{fator.label}</span>
                <span className="tabular-nums text-muted-foreground">
                  {fator.pontos ?? "—"} pontos · contributo {(Math.round((fator.contributo ?? 0) * 1000) / 10).toFixed(1)}
                </span>
              </p>
            ))}
          </div>
        ) : null}
        <p className="mt-1 text-[11px] text-muted-foreground">
          {risco.metodo_label ? `${risco.metodo_label} · ` : ""}
          cobertura {risco.cobertura !== null && risco.cobertura !== undefined ? `${Math.round(risco.cobertura * 100)}%` : "—"}
          {resumo.insolvencias ? ` · ${resumo.insolvencias} processo(s) no CIRE` : ""}
          {precos.mediana_efetiva !== null && precos.mediana_efetiva !== undefined
            ? ` · valor efetivo/contratual mediano ${precos.mediana_efetiva}`
            : ""}
        </p>
      </Cartao>

      <Cartao titulo="Valor em jogo por faixa" porque="Onde está o dinheiro: contratos e valor somado em cada faixa de preço e concorrência.">
        <div className="space-y-1 text-[11.5px]">
          {valorPorFaixa.length ? (
            valorPorFaixa.map((linha) => (
              <p key={linha.grupo} className="flex justify-between gap-3 border-b border-white/5 pb-0.5">
                <span className="truncate text-muted-foreground">{linha.grupo}</span>
                <span className="shrink-0 tabular-nums">
                  {formatMoney(linha.valor)} · {linha.contratos} contrato(s)
                </span>
              </p>
            ))
          ) : (
            <p className="text-muted-foreground">Sem faixas com contratos.</p>
          )}
        </div>
      </Cartao>
    </div>
  );
}
