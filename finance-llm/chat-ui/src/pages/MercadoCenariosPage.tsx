/**
 * Inteligência de mercado · cenários (World Model) e sensibilidade — página do módulo.
 *
 * Seis eventos contrafactuais medidos nos contratos do escopo (não são
 * previsões): perda do maior comprador, entidade que deixa de contratar um
 * fornecedor, entrada de um novo concorrente, contratos a expirar, variação de
 * preços e diversificação de carteira. Cada evento declara as **hipóteses** e
 * traz a **evidência** que o sustenta.
 *
 * A sensibilidade usa a mesma matemática do módulo Lorenz (mapa discreto
 * ajustado à série, divergência `D_t`, expoente de Lyapunov e sistema de Lorenz
 * com parâmetros análogos medidos na estrutura do mercado).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  Building2,
  CalendarClock,
  Coins,
  GitBranch,
  Loader2,
  RefreshCw,
  Share2,
  Sparkles,
  TrendingUp,
  Users,
  Waves,
} from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getLorenzAreas, type LorenzArea } from "../lorenzApi";
import {
  getMercadoCenarios,
  type MercadoCenarios,
  type MercadoEscopoParams,
  type MercadoEvento,
  type MercadoSensibilidade,
} from "../mercadoApi";
import { Chip, EmptyState, Kpi, Loading, SectionCard, formatCompactEuro, formatNumber, formatPct } from "../components/padroes/padroesKit";

const REGIOES = [
  { id: "", label: "Todas as regiões" },
  { id: "PT11", label: "Norte" },
  { id: "PT15", label: "Algarve" },
  { id: "PT16", label: "Centro" },
  { id: "PT17", label: "Área Metropolitana de Lisboa" },
  { id: "PT18", label: "Alentejo" },
  { id: "PT20", label: "Açores" },
  { id: "PT30", label: "Madeira" },
];

/** Ordem de apresentação dos eventos (a mesma do metamodelo). */
const EVENTOS: { id: string; label: string; icon: typeof Coins; resumo: string }[] = [
  { id: "perda_maior_comprador", label: "Perde o maior comprador", icon: Users, resumo: "Volume, dependência residual e nova posição" },
  { id: "entidade_sem_fornecedor", label: "Entidade sem um fornecedor", icon: Building2, resumo: "Exposição por CPV e alternativas observadas" },
  { id: "novo_concorrente", label: "Entra um novo concorrente", icon: TrendingUp, resumo: "Simulação multinomial de concursos" },
  { id: "contratos_a_expirar", label: "Contratos a expirar", icon: CalendarClock, resumo: "Volume exposto à renovação no horizonte" },
  { id: "precos_mais", label: "Preços contratuais aumentam", icon: Coins, resumo: "Sensibilidade uniforme do valor contratado" },
  { id: "diversificacao", label: "Diversifica compradores", icon: Share2, resumo: "Repartir o maior comprador e medir D_i" },
];

function rotuloRegime(regime?: string | null): string {
  if (regime === "amplificador") return "Amplificador (margem > 1)";
  if (regime === "dissipador") return "Dissipador (margem < 1)";
  if (regime === "sensivel") return "Sensível (λ > 0)";
  return "—";
}

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/5 py-1 last:border-0">
      <span className="text-[11px] text-muted-foreground">{rotulo}</span>
      <span className="text-right font-mono text-[11.5px]">{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------------- página */

export default function MercadoCenariosPage({ onAbrirMercado }: { onAbrirMercado?: () => void }) {
  const [areasDisponiveis, setAreasDisponiveis] = useState<LorenzArea[]>([]);
  const [area, setArea] = useState("medicamentos");
  const [cpvLivre, setCpvLivre] = useState("");
  const [anoDe, setAnoDe] = useState("2023");
  const [anoAte, setAnoAte] = useState("");
  const [regiao, setRegiao] = useState("");
  const [nif, setNif] = useState("");
  const [horizonte, setHorizonte] = useState("180");
  const [forcaRelativa, setForcaRelativa] = useState("1");
  const [variacaoPrecos, setVariacaoPrecos] = useState("0.1");

  const [dados, setDados] = useState<MercadoCenarios | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    getLorenzAreas()
      .then((resposta) => {
        if (!cancelado && resposta.areas?.length) setAreasDisponiveis(resposta.areas);
      })
      .catch(() => {
        /* a lista de áreas é acessória */
      });
    return () => {
      cancelado = true;
    };
  }, []);

  const params = useMemo<MercadoEscopoParams>(() => {
    const limpo: MercadoEscopoParams = { area };
    if (cpvLivre.trim()) limpo.cpv = cpvLivre.trim();
    if (anoDe) limpo.ano_de = Number(anoDe);
    if (anoAte) limpo.ano_ate = Number(anoAte);
    if (regiao) limpo.regiao = regiao;
    return limpo;
  }, [anoAte, anoDe, area, cpvLivre, regiao]);

  const carregar = useCallback(async () => {
    setACarregar(true);
    setErro(null);
    try {
      const resposta = await getMercadoCenarios({
        ...params,
        nif: nif.trim() || undefined,
        horizonte_dias: Number(horizonte) || undefined,
        forca_relativa: Number(forcaRelativa) || undefined,
        variacao_precos: variacaoPrecos === "" ? undefined : Number(variacaoPrecos),
      });
      setDados(resposta);
    } catch (falha) {
      setDados(null);
      setErro(falha instanceof Error ? falha.message : "Erro ao simular os cenários");
    } finally {
      setACarregar(false);
    }
  }, [forcaRelativa, horizonte, nif, params, variacaoPrecos]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const eventoPorId = useCallback((id: string) => (dados?.eventos ?? []).find((evento) => evento.evento === id) ?? null, [dados]);

  const mapaEventos = useMemo(
    () => EVENTOS.map((item) => ({ ...item, dados: eventoPorId(item.id) })).filter((item) => item.dados !== null),
    [eventoPorId],
  );

  const divergencia = useMemo(() => {
    const serie = dados?.sensibilidade?.divergencia?.D;
    if (!serie) return [];
    return serie.map((valor, indice) => ({ passo: indice, D: valor }));
  }, [dados]);

  const lorenzTrajetoria = useMemo(
    () => (dados?.sensibilidade?.lorenz?.trajetoria ?? []).map((ponto) => ({ x: ponto[0], y: ponto[1], z: ponto[2] })),
    [dados],
  );

  const estadoGrafico = useMemo(
    () =>
      (dados?.sensibilidade?.estado?.coordenadas ?? []).map((linha, indice) => ({
        periodo: dados?.sensibilidade?.estado?.periodos?.[indice] ?? String(indice),
        atividade: linha[0],
        dependencia: linha[1],
        cauda: linha[2],
      })),
    [dados],
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden text-foreground">
      <header className="shrink-0 border-b border-white/10 bg-white/[0.02] px-4 py-3 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <Sparkles size={18} className="text-violet-300" />
              Cenários do mercado · World Model + sensibilidade
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Cada evento é um contrafactual medido nos contratos do escopo — com hipóteses declaradas, evidência e leitura de regime.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {dados?.sensibilidade?.parametros?.regime ? (
              <Chip tone={dados.sensibilidade.parametros.regime === "amplificador" ? "amber" : "teal"} title="Regime do sistema face à fronteira de instabilidade">
                {rotuloRegime(dados.sensibilidade.parametros.regime)}
              </Chip>
            ) : null}
            {onAbrirMercado ? (
              <button
                type="button"
                onClick={onAbrirMercado}
                className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1.5 text-xs text-teal-100 transition hover:bg-teal-400/25"
              >
                <BarChart3 size={13} />
                Mercado
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => void carregar()}
              disabled={aCarregar}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1] disabled:opacity-50"
            >
              {aCarregar ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Recalcular
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-2 text-[11.5px]">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Área</span>
            <select value={area} onChange={(evento) => setArea(evento.target.value)} className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none">
              {areasDisponiveis.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">CPV (prefixos)</span>
            <input
              value={cpvLivre}
              onChange={(evento) => setCpvLivre(evento.target.value)}
              placeholder="ex.: 336"
              className="w-28 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Ano de</span>
            <input
              value={anoDe}
              onChange={(evento) => setAnoDe(evento.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="2018"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Ano até</span>
            <input
              value={anoAte}
              onChange={(evento) => setAnoAte(evento.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="2026"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Região</span>
            <select value={regiao} onChange={(evento) => setRegiao(evento.target.value)} className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none">
              {REGIOES.map((opcao) => (
                <option key={opcao.id} value={opcao.id}>
                  {opcao.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1" title="Empresa alvo dos eventos que a referem">
            <span className="text-muted-foreground">NIF alvo</span>
            <input
              value={nif}
              onChange={(evento) => setNif(evento.target.value.replace(/\D/g, "").slice(0, 9))}
              placeholder="vazio: maior do mercado"
              className="w-36 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 font-mono outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Horizonte (dias)</span>
            <input
              value={horizonte}
              onChange={(evento) => setHorizonte(evento.target.value.replace(/\D/g, "").slice(0, 3))}
              placeholder="180"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1" title="Força do novo concorrente (× mediana do mercado)">
            <span className="text-muted-foreground">Força do entrante</span>
            <input
              value={forcaRelativa}
              onChange={(evento) => setForcaRelativa(evento.target.value.replace(/[^\d.]/g, "").slice(0, 4))}
              placeholder="1.0"
              className="w-16 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1" title="Variação uniforme dos preços contratuais">
            <span className="text-muted-foreground">Δ preços</span>
            <input
              value={variacaoPrecos}
              onChange={(evento) => setVariacaoPrecos(evento.target.value.replace(/[^\d.-]/g, "").slice(0, 6))}
              placeholder="0.1"
              className="w-20 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 outline-none"
            />
          </label>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {erro && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle size={15} />
            {erro}
          </div>
        )}
        {aCarregar && !dados ? <Loading label="A medir os seis eventos e a sensibilidade…" /> : null}

        {dados ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi
                icon={Waves}
                label="Regime do mercado"
                value={dados.sensibilidade?.parametros?.regime === "amplificador" ? "Amplificador" : dados.sensibilidade?.parametros?.regime === "dissipador" ? "Dissipador" : "—"}
                sub={dados.sensibilidade?.parametros?.margem !== undefined ? `margem ${dados.sensibilidade.parametros.margem.toFixed(2)} (ρ_crit ${dados.sensibilidade.parametros.rho_critico?.toFixed(1) ?? "—"})` : undefined}
                color="text-amber-300"
              />
              <Kpi
                icon={TrendingUp}
                label="λ empírico (divergência)"
                value={dados.sensibilidade?.divergencia?.lambda_empirico !== undefined ? dados.sensibilidade.divergencia.lambda_empirico.toFixed(3) : "—"}
                sub={dados.sensibilidade?.divergencia?.regime ? rotuloRegime(dados.sensibilidade.divergencia.regime) : undefined}
                color="text-violet-300"
              />
              <Kpi
                icon={GitBranch}
                label="λ de Lyapunov (Lorenz)"
                value={dados.sensibilidade?.lorenz ? dados.sensibilidade.lorenz.lyapunov.lambda.toFixed(3) : "—"}
                sub={dados.sensibilidade?.lorenz ? `${dados.sensibilidade.lorenz.lyapunov.intervalos} intervalos` : "sem integração"}
                color="text-sky-300"
                glow="glow-sky"
              />
              <Kpi
                icon={CalendarClock}
                label="Períodos analisados"
                value={formatNumber(dados.sensibilidade?.periodos?.length ?? 0)}
                sub={(dados.sensibilidade?.periodos ?? []).join(", ").slice(0, 60)}
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              {mapaEventos.map((item) => (
                <Evento key={item.id} titulo={item.label} resumo={item.resumo} icon={item.icon} evento={item.dados as MercadoEvento} />
              ))}
            </div>

            <Sensibilidade dados={dados.sensibilidade} divergencia={divergencia} lorenz={lorenzTrajetoria} estado={estadoGrafico} heroi={mapaEventos[2]?.dados?.medicao?.empresas as Record<string, unknown>[] | undefined} />

            {dados.notas?.length ? (
              <SectionCard title="Limites de leitura" subtitle="estes eventos não são previsões" icon={AlertTriangle}>
                <ul className="space-y-1 text-[11.5px] text-muted-foreground">
                  {dados.notas.map((nota) => (
                    <li key={nota}>· {nota}</li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-muted-foreground">Gerado em {new Date(dados.gerado_em).toLocaleString("pt-PT")} · {dados.duracao_s.toFixed(1)} s</p>
              </SectionCard>
            ) : null}
          </div>
        ) : null}

        {!dados && !aCarregar && !erro ? <EmptyState>Escolha o escopo e recarregue para simular os eventos.</EmptyState> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ evento */

function Evento({ titulo, resumo, icon: Icone, evento }: { titulo: string; resumo: string; icon: typeof Coins; evento: MercadoEvento }) {
  const medicao = (evento.medicao ?? {}) as Record<string, unknown>;
  return (
    <SectionCard
      title={titulo}
      subtitle={resumo}
      icon={Icone}
      actions={<Chip tone={evento.disponivel ? "teal" : "neutral"}>{evento.disponivel ? "medido" : evento.motivo ?? "indisponível"}</Chip>}
    >
      {!evento.disponivel ? (
        <EmptyState tone="warn">Este evento não é mensurável no escopo escolhido: {evento.motivo ?? "sem dados suficientes"}.</EmptyState>
      ) : (
        <div className="space-y-2 text-[11.5px]">
          <CorpoEvento evento={evento.evento} medicao={medicao} />
          {evento.hipoteses?.length ? (
            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">Hipóteses declaradas</p>
              <ul className="space-y-0.5 text-[11px] text-muted-foreground">
                {evento.hipoteses.map((hipotese) => (
                  <li key={hipotese}>· {hipotese}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {evento.evidencia?.length ? (
            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">Evidência ({evento.evidencia.length})</p>
              <div className="space-y-0.5">
                {evento.evidencia.slice(0, 5).map((linha, indice) => (
                  <p key={`${evento.evento}-${indice}`} className="truncate text-[11px] text-muted-foreground" title={JSON.stringify(linha)}>
                    · {Object.entries(linha).map(([chave, valor]) => `${chave.replace(/_/g, " ")}: ${typeof valor === "number" ? formatNumber(valor) : String(valor ?? "—")}`).join(" · ")}
                  </p>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}

/** Corpo específico de cada evento (os nomes dos campos vêm da API). */
function CorpoEvento({ evento, medicao }: { evento: string; medicao: Record<string, unknown> }) {
  const numero = (campo: string) => (typeof medicao[campo] === "number" ? (medicao[campo] as number) : undefined);
  const objeto = (campo: string) => (medicao[campo] && typeof medicao[campo] === "object" ? (medicao[campo] as Record<string, unknown>) : undefined);

  if (evento === "perda_maior_comprador") {
    return (
      <>
        <Linha rotulo="Comprador perdido">{String(medicao.comprador ?? "—")}</Linha>
        <Linha rotulo="Valor perdido">{formatCompactEuro(numero("valor_perdido") ?? 0)}</Linha>
        <Linha rotulo="Quota do valor">{formatPct(numero("quota_do_valor"))}</Linha>
        <Linha rotulo="Valor residual">{formatCompactEuro(numero("valor_residual") ?? 0)}</Linha>
        <Linha rotulo="D_i antes">{formatNumber(objeto("dependencia_antes")?.hhi as number)}</Linha>
        <Linha rotulo="D_i depois">{formatNumber(objeto("dependencia_depois")?.hhi as number)}</Linha>
        <Linha rotulo="Compradores restantes">{formatNumber(numero("compradores_restantes"))}</Linha>
      </>
    );
  }
  if (evento === "entidade_sem_fornecedor") {
    const alternativas = (medicao.alternativas_no_escopo as Record<string, unknown>[] | undefined) ?? [];
    return (
      <>
        <Linha rotulo="Valor da entidade">{formatCompactEuro(numero("valor_da_entidade") ?? 0)}</Linha>
        <Linha rotulo="Valor do fornecedor">{formatCompactEuro(numero("valor_do_fornecedor") ?? 0)}</Linha>
        <Linha rotulo="Exposição">{formatPct(numero("exposicao"))}</Linha>
        <Linha rotulo="Cobertura das 3 alternativas">{formatPct(numero("cobertura_alternativa_3"))}</Linha>
        <Linha rotulo="Dificuldade de substituição">{formatPct(numero("dificuldade_substituicao"))}</Linha>
        {alternativas.length ? (
          <div className="pt-1">
            <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">Alternativas já observadas</p>
            {alternativas.slice(0, 5).map((alternativa, indice) => (
              <Linha key={`alt-${indice}`} rotulo={String(alternativa.nome ?? "—")}>
                {formatPct(alternativa.quota as number)} · {formatCompactEuro(alternativa.valor as number)}
              </Linha>
            ))}
          </div>
        ) : null}
      </>
    );
  }
  if (evento === "novo_concorrente") {
    const empresas = (medicao.empresas as Record<string, unknown>[] | undefined) ?? [];
    return (
      <>
        <Linha rotulo="Força do entrante">{formatNumber(numero("forca_absoluta"))}</Linha>
        <Linha rotulo="Força mediana do mercado">{formatNumber(numero("forca_mediana_do_mercado"))}</Linha>
        <Linha rotulo="Quota estimada do entrante">{formatPct(numero("quota_estimada_do_entrante"))}</Linha>
        <Linha rotulo="Empresas afetadas">{formatNumber(numero("empresas_afetadas"))}</Linha>
        <Linha rotulo="HHI antes → simulado">
          {formatNumber(numero("hhi_antes"))} → {formatNumber(numero("hhi_simulado"))}
        </Linha>
        {empresas.length ? (
          <div className="pt-1">
            <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">Quota observada → simulada</p>
            {empresas.slice(0, 6).map((empresa, indice) => (
              <Linha key={`emp-${indice}`} rotulo={String(empresa.nome ?? "—")}>
                {formatPct(empresa.quota_observada as number)} → {formatPct(empresa.quota_simulada as number)}{" "}
                <span className={(empresa.variacao as number) < 0 ? "text-rose-300" : "text-teal-300"}>{formatPct(empresa.variacao as number)}</span>
              </Linha>
            ))}
          </div>
        ) : null}
      </>
    );
  }
  if (evento === "contratos_a_expirar") {
    const estrito = objeto("estrito");
    const estimado = objeto("estimado");
    const janela = objeto("janela");
    const amostra = objeto("amostra");
    return (
      <>
        <Linha rotulo="Horizonte">{formatNumber(numero("horizonte_dias"))} dias</Linha>
        <Linha rotulo="Janela">{`${String(janela?.de ?? "—")} → ${String(janela?.ate ?? "—")}`}</Linha>
        <Linha rotulo="Leitura estrita (dataFechoContrato)">
          {formatNumber(estrito?.contratos as number)} contratos · {formatCompactEuro((estrito?.valor as number) ?? 0)}
        </Linha>
        <Linha rotulo="Leitura estimada (celebração + prazo)">
          {formatNumber(estimado?.contratos as number)} contratos · {formatCompactEuro((estimado?.valor as number) ?? 0)}
        </Linha>
        <Linha rotulo="Valor exposto">{formatCompactEuro(numero("valor_exposto") ?? 0)}</Linha>
        <Linha rotulo="Amostra (estimada)">{formatNumber((estimado?.amostra as Record<string, unknown> | undefined)?.lidos as number)} contratos lidos</Linha>
        <Linha rotulo="Cobertura de valor da amostra">
          {formatPct((estimado?.amostra as Record<string, unknown> | undefined)?.cobertura_valor as number)}
        </Linha>
        <Linha rotulo="Prazos ignorados">{formatNumber((estimado?.amostra as Record<string, unknown> | undefined)?.prazos_ignorados as number)}</Linha>
        {amostra ? <Linha rotulo="Candidatos no escopo">{formatNumber(amostra.candidatos_no_escopo as number)}</Linha> : null}
      </>
    );
  }
  if (evento === "precos_mais") {
    const porEmpresa = (medicao.por_empresa as Record<string, unknown>[] | undefined) ?? [];
    return (
      <>
        <Linha rotulo="Variação simulada">{formatPct(numero("variacao"))}</Linha>
        <Linha rotulo="Valor atual">{formatCompactEuro(numero("valor_atual") ?? 0)}</Linha>
        <Linha rotulo="Valor simulado">{formatCompactEuro(numero("valor_simulado") ?? 0)}</Linha>
        <Linha rotulo="Δ valor">{formatCompactEuro(numero("delta_valor") ?? 0)}</Linha>
        {porEmpresa.length ? (
          <div className="pt-1">
            <p className="mb-1 text-[10.5px] uppercase tracking-wide text-muted-foreground">Exposição por empresa</p>
            {porEmpresa.slice(0, 6).map((empresa, indice) => (
              <Linha key={`preco-${indice}`} rotulo={String(empresa.nome ?? "—")}>
                {formatCompactEuro(empresa.delta_valor as number)}
              </Linha>
            ))}
          </div>
        ) : null}
      </>
    );
  }
  if (evento === "diversificacao") {
    const antes = objeto("dependencia_antes");
    const depois = objeto("dependencia_simulada");
    return (
      <>
        <Linha rotulo="Maior comprador">{String(medicao.maior_comprador ?? "—")}</Linha>
        <Linha rotulo="Quota do maior">{formatPct(numero("quota_do_maior"))}</Linha>
        <Linha rotulo="Valor a repartir">{formatCompactEuro(numero("valor_a_repartir") ?? 0)}</Linha>
        <Linha rotulo="D_i antes → simulada">
          {formatNumber(antes?.hhi as number)} → {formatNumber(depois?.hhi as number)}
        </Linha>
        <Linha rotulo="Maior quota antes → simulada">
          {formatPct(antes?.maior_quota as number)} → {formatPct(depois?.maior_quota as number)}
        </Linha>
        <Linha rotulo="Nº de compradores">{formatNumber(antes?.n_entidades as number)}</Linha>
      </>
    );
  }
  return (
    <>
      {Object.entries(medicao)
        .filter(([, valor]) => typeof valor !== "object")
        .slice(0, 8)
        .map(([chave, valor]) => (
          <Linha key={chave} rotulo={chave.replace(/_/g, " ")}>
            {typeof valor === "number" ? formatNumber(valor) : String(valor ?? "—")}
          </Linha>
        ))}
    </>
  );
}

/* ------------------------------------------------------------ sensibilidade */

function Sensibilidade({
  dados,
  divergencia,
  lorenz,
  estado,
  heroi,
}: {
  dados?: MercadoSensibilidade;
  divergencia: { passo: number; D: number }[];
  lorenz: { x: number; y: number; z: number }[];
  estado: { periodo: string; atividade: number; dependencia: number; cauda: number }[];
  heroi?: Record<string, unknown>[];
}) {
  if (!dados?.disponivel) {
    return (
      <SectionCard title="Sensibilidade às condições iniciais" subtitle="o mapa discreto precisa de uma série com pelo menos três períodos" icon={Waves}>
        <EmptyState tone="warn">{dados?.motivo ?? "Sensibilidade indisponível para este escopo."}</EmptyState>
      </SectionCard>
    );
  }
  const parametros = dados.parametros;
  const mapa = dados.mapa;
  return (
    <SectionCard
      title="Sensibilidade às condições iniciais"
      subtitle="A mesma matemática da página Lorenz: mapa ajustado à série, divergência entre trajetórias vizinhas e sistema de Lorenz com parâmetros análogos"
      icon={Waves}
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          {divergencia.length ? (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Divergência entre trajetórias vizinhas ({dados.divergencia?.passos} passos)</p>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={divergencia} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="passo" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} scale="log" domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }}
                      formatter={(valor: unknown) => Number(valor).toExponential(3)}
                    />
                    <Line dataKey="D" stroke="#fb7185" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}

          {estado.length ? (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Coordenadas de estado por período (atividade, dependência, cauda)</p>
              <div className="h-[210px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={estado} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="periodo" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="atividade" name="atividade" fill="#2dd4bf" radius={[4, 4, 0, 0]} />
                    <Line dataKey="dependencia" name="dependência" stroke="#a78bfa" strokeWidth={2} dot={false} />
                    <Line dataKey="cauda" name="cauda" stroke="#fbbf24" strokeWidth={2} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}

          {lorenz.length ? (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                Sistema de Lorenz (σ {parametros?.sigma?.toFixed(2)} · β {parametros?.beta?.toFixed(2)} · ρ {parametros?.rho?.toFixed(1)}) — projeção x·y
              </p>
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                    <XAxis type="number" dataKey="x" tick={{ fontSize: 10 }} name="x" />
                    <YAxis type="number" dataKey="y" tick={{ fontSize: 10 }} name="y" />
                    <Tooltip
                      contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }}
                      formatter={(valor: unknown) => Number(valor).toFixed(2)}
                    />
                    <Scatter data={lorenz} fill="#60a5fa" />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}

          {heroi?.length ? (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Efeito do entrante por empresa (variação simulada)</p>
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={heroi.slice(0, 10).map((empresa) => ({ nome: String(empresa.nome ?? "").slice(0, 18), variacao: empresa.variacao as number }))}
                    margin={{ top: 8, right: 8, bottom: 8, left: 8 }}
                  >
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="nome" tick={{ fontSize: 10 }} interval={0} angle={-18} textAnchor="end" height={56} />
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={(valor: number) => `${(valor * 100).toFixed(0)}%`} />
                    <Tooltip
                      contentStyle={{ background: "rgba(9,12,20,0.94)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 11 }}
                      formatter={(valor: unknown) => formatPct(Number(valor))}
                    />
                    <Bar dataKey="variacao" name="variação" fill="#fb7185" radius={[4, 4, 0, 0]} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}
        </div>

        <aside className="space-y-3 text-[11.5px]">
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Parâmetros análogos</p>
            <Linha rotulo="σ (fornecedores/compradores)">{parametros?.sigma !== undefined ? parametros.sigma.toFixed(2) : "—"}</Linha>
            <Linha rotulo="β (inércia)">{parametros?.beta !== undefined ? parametros.beta.toFixed(2) : "—"}</Linha>
            <Linha rotulo="ρ (pressão)">{parametros?.rho !== undefined ? parametros.rho.toFixed(2) : "—"}</Linha>
            <Linha rotulo="ρ crítico">{parametros?.rho_critico !== undefined ? parametros.rho_critico.toFixed(3) : "—"}</Linha>
            <Linha rotulo="Margem">{parametros?.margem !== undefined ? parametros.margem.toFixed(2) : "—"}</Linha>
            <Linha rotulo="Regime">
              <Chip tone={parametros?.regime === "amplificador" ? "amber" : "teal"}>{rotuloRegime(parametros?.regime)}</Chip>
            </Linha>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Divergência e mapa</p>
            <Linha rotulo="λ empírico">{dados.divergencia?.lambda_empirico !== undefined ? dados.divergencia.lambda_empirico.toFixed(4) : "—"}</Linha>
            <Linha rotulo="Perturbação inicial">{dados.divergencia?.perturbacao_inicial ?? "—"}</Linha>
            <Linha rotulo="Direções">{formatNumber(dados.divergencia?.direcoes)}</Linha>
            <Linha rotulo="R² do mapa">{mapa?.r2 !== undefined ? mapa.r2.toFixed(4) : "—"}</Linha>
            <Linha rotulo="Raio espectral">{mapa?.raio_espectral !== undefined ? mapa.raio_espectral.toFixed(3) : "—"}</Linha>
            <Linha rotulo="Pares ajustados">{formatNumber(mapa?.pares)}</Linha>
            {mapa?.nota ? <p className="mt-1 text-[10.5px] text-muted-foreground">{mapa.nota}</p> : null}
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Lyapunov (sistema de Lorenz)</p>
            <Linha rotulo="λ máximo">{dados.lorenz ? dados.lorenz.lyapunov.lambda.toFixed(4) : "—"}</Linha>
            <Linha rotulo="Tempo total">{dados.lorenz ? dados.lorenz.lyapunov.tempo_total.toFixed(1) : "—"}</Linha>
            <Linha rotulo="Intervalos">{formatNumber(dados.lorenz?.lyapunov.intervalos)}</Linha>
            <Linha rotulo="Regime">{dados.lorenz ? dados.lorenz.lyapunov.regime : "—"}</Linha>
          </div>

          {dados.divergencia?.nota ? <p className="text-[10.5px] text-muted-foreground">{dados.divergencia.nota}</p> : null}
          {dados.parametros?.nota ? <p className="text-[10.5px] text-muted-foreground">{dados.parametros.nota}</p> : null}
          {dados.nota ? <p className="text-[10.5px] text-muted-foreground">{dados.nota}</p> : null}
        </aside>
      </div>
    </SectionCard>
  );
}
