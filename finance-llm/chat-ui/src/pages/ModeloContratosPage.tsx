/**
 * Modelo de contratos · fine-tuning em directo — página do módulo `/modelo/contratos`.
 *
 * Mostra, com diagramas animados, **o que se está a passar no treino**:
 *
 * 1. **Pipeline** — os índices do Elasticsearch (`contratos`, `finance_entities`,
 *    `finance_subvencoes`) a alimentar o exportador, o dataset, o treino LoRA, o
 *    adaptador e a avaliação. Cada nó acende quando a fase correspondente já
 *    produziu alguma coisa (o fluxo só é animado enquanto há treino a correr).
 * 2. **Treino em directo** — curva de perda que se desenha à medida que chegam
 *    pontos, progresso por passos, ciclos de um passo (lote → forward → perda →
 *    backward → update) e o mapa das 24 camadas do Qwen onde a LoRA escreve.
 * 3. **Avaliação** — base vs adaptador no held-out, fidelidade dos números, e o
 *    histórico guardado em `finance_llm_model_evals`.
 * 4. **Perguntar ao modelo** — a resposta do adaptador a um documento real.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Brain,
  CheckCircle2,
  Database,
  ExternalLink,
  FileJson2,
  FlaskConical,
  Gauge,
  Layers,
  Loader2,
  PauseCircle,
  Play,
  RefreshCw,
  Timer,
  Zap,
} from "lucide-react";
import MatrizDePesos from "../components/modelo/MatrizDePesos";
import GrafoDoModelo from "../components/modelo/GrafoDoModelo";
import LigacoesDeDados from "../components/modelo/LigacoesDeDados";
import ChatDoModelo from "../components/modelo/ChatDoModelo";
import {
  correrAvaliacao,
  getCurvaTreino,
  getLigacoes,
  getMatriz,
  getModeloEstado,
  listarAvaliacoes,
  type Ligacoes,
  type MatrizAdaptador,
  type ModeloEstado,
  type PontoTreino,
  type ResultadoAvaliacao,
} from "../llmModeloApi";
import "../modeloContratos.css";

const CAMADAS_QWEN = 24;
const PROJECOES = ["q", "k", "v", "o", "gate", "up", "down"];

function fmt(valor: number | null | undefined, casas = 2): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return valor.toLocaleString("pt-PT", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function duracao(segundos: number | null | undefined): string {
  if (!segundos) return "—";
  const total = Math.round(segundos);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${s} s`;
  return `${s} s`;
}

function Cartao({
  titulo,
  valor,
  nota,
  icone,
  tom = "primario",
}: {
  titulo: string;
  valor: string;
  nota?: string;
  icone: React.ReactNode;
  tom?: "primario" | "azul" | "ambar" | "rosa";
}) {
  const cores: Record<string, string> = {
    primario: "text-primary border-primary/30",
    azul: "text-sky-400 border-sky-400/30",
    ambar: "text-amber-400 border-amber-400/30",
    rosa: "text-fuchsia-400 border-fuchsia-400/30",
  };
  return (
    <div className="rounded-xl border border-border bg-card/70 p-4">
      <div className={`flex items-center gap-2 text-xs uppercase tracking-wide ${cores[tom]}`}>
        {icone}
        <span className="text-muted-foreground">{titulo}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{valor}</div>
      {nota && <div className="mt-1 text-xs text-muted-foreground">{nota}</div>}
    </div>
  );
}

/** Diagrama do pipeline: ES → exportador → dataset → LoRA → adaptador → avaliação. */
function PipelineDiagram({ estado, avaliacoes }: { estado: ModeloEstado; avaliacoes: number }) {
  const treino = estado.treino?.treino;
  const passos = treino?.passos ?? 0;
  const planeados = treino?.passos_planeados ?? 0;
  const emCurso = estado.metricas.pontos > 0 && planeados > 0 && passos < planeados;
  const datasSet = estado.treino?.dados?.pares_treino ?? 0;

  const nos = [
    {
      id: "es",
      titulo: "Elasticsearch",
      detalhe: estado.fonte_dados.indices.join(" · "),
      ativo: true,
      icone: Database,
    },
    {
      id: "export",
      titulo: "Exportador",
      detalhe: "instruction / input / output",
      ativo: datasSet > 0,
      icone: FileJson2,
    },
    {
      id: "dataset",
      titulo: "Dataset",
      detalhe: `${datasSet} pares · ${estado.treino?.dados?.pares_holdout ?? 0} held-out`,
      ativo: datasSet > 0,
      icone: Layers,
    },
    {
      id: "lora",
      titulo: "Treino LoRA",
      detalhe: planeados ? `${passos}/${planeados} passos` : "ainda sem métricas",
      ativo: estado.metricas.pontos > 0,
      pulsante: emCurso,
      icone: Zap,
    },
    {
      id: "adapter",
      titulo: "Adaptador",
      detalhe: estado.adaptador_disponivel ? "adapter_model.safetensors" : "por treinar",
      ativo: estado.adaptador_disponivel,
      icone: Brain,
    },
    {
      id: "eval",
      titulo: "Avaliação",
      detalhe: avaliacoes ? `${avaliacoes} corridas` : "por correr",
      ativo: avaliacoes > 0,
      icone: Gauge,
    },
  ];

  // Geometria: 6 nós têm de caber sem cortar o último (o `viewBox` anterior
  // deixava a Avaliação fora do SVG). Largura fixa por nó e folga calculada.
  const largura = 960;
  const margem = 8;
  const folga = 12;
  const larguraNo = (largura - margem * 2 - folga * (nos.length - 1)) / nos.length;
  const xDoNo = (i: number) => margem + i * (larguraNo + folga);

  return (
    <svg viewBox={`0 0 ${largura} 150`} className="w-full" role="img" aria-label="Pipeline do fine-tuning">
      <defs>
        <linearGradient id="mc-ligacao" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#10a37f" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#10a37f" stopOpacity="0.85" />
        </linearGradient>
        <filter id="mc-brilho-filtro" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" result="desfoque" />
          <feMerge>
            <feMergeNode in="desfoque" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {nos.slice(0, -1).map((_, i) => {
        const x1 = xDoNo(i) + larguraNo + 1;
        const x2 = xDoNo(i + 1) - 1;
        const ligado = nos[i + 1].ativo;
        return (
          <g key={`lig-${i}`}>
            <line x1={x1} y1={56} x2={x2} y2={56} stroke="#2e323b" strokeWidth={2} />
            <line
              x1={x1}
              y1={56}
              x2={x2}
              y2={56}
              stroke="url(#mc-ligacao)"
              strokeWidth={2.5}
              className={emCurso && ligado ? "mc-fluxo" : undefined}
              opacity={ligado ? 1 : 0.25}
            />
            {ligado && (
              <circle r={3.2} fill="#10a37f" opacity={0.9}>
                <animateMotion dur={`${2.6 + i * 0.2}s`} repeatCount="indefinite" path={`M${x1},56 L${x2},56`} />
              </circle>
            )}
          </g>
        );
      })}
      {nos.map((no, i) => {
        const x = xDoNo(i);
        const Icone = no.icone;
        return (
          <g key={no.id} transform={`translate(${x}, 18)`}>
            <rect
              width={larguraNo}
              height={78}
              rx={14}
              fill={no.ativo ? "rgba(16,163,127,0.10)" : "rgba(30,33,40,0.65)"}
              stroke={no.ativo ? "#10a37f" : "#2e323b"}
              strokeWidth={no.ativo ? 1.6 : 1}
              filter={no.ativo ? "url(#mc-brilho-filtro)" : undefined}
            />
            {no.pulsante && <rect width={larguraNo} height={78} rx={14} fill="none" stroke="#10a37f" className="mc-halo" strokeWidth={2} />}
            <g transform="translate(12, 14)">
              <Icone size={16} color={no.ativo ? "#10a37f" : "#6b7280"} />
            </g>
            <text x={38} y={27} fontSize={12.5} fill={no.ativo ? "#e8e9ec" : "#9aa0aa"} fontWeight={600}>
              {no.titulo}
            </text>
            <foreignObject x={12} y={36} width={larguraNo - 22} height={36}>
              <div className="text-[10.5px] leading-tight text-muted-foreground">{no.detalhe}</div>
            </foreignObject>
          </g>
        );
      })}
    </svg>
  );
}

/** Curva de perda que se desenha à medida que o treino avança. */
function CurvaDePerda({ pontos, emCurso }: { pontos: PontoTreino[]; emCurso: boolean }) {
  const largura = 780;
  const altura = 250;
  const margem = { esq: 48, dir: 18, topo: 18, fundo: 34 };
  const larguraUtil = largura - margem.esq - margem.dir;
  const alturaUtil = altura - margem.topo - margem.fundo;

  const geometria = useMemo(() => {
    if (!pontos.length) return null;
    const perdas = pontos.map((p) => p.perda);
    const min = Math.min(...perdas);
    const max = Math.max(...perdas);
    const folga = (max - min) * 0.12 || 0.1;
    const piso = Math.max(0, min - folga);
    const teto = max + folga;
    const x = (i: number) => margem.esq + (pontos.length === 1 ? larguraUtil / 2 : (i / (pontos.length - 1)) * larguraUtil);
    const y = (v: number) => margem.topo + (1 - (v - piso) / (teto - piso || 1)) * alturaUtil;
    const linha = pontos.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.perda).toFixed(1)}`).join(" ");
    const area = `${linha} L${x(pontos.length - 1).toFixed(1)},${margem.topo + alturaUtil} L${x(0).toFixed(1)},${margem.topo + alturaUtil} Z`;
    return { x, y, linha, area, piso, teto };
  }, [pontos, larguraUtil, alturaUtil, margem.esq, margem.topo]);

  if (!geometria) {
    return (
      <div className="flex h-[250px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        Sem métricas ainda — o treino escreve a primeira linha ao passo 1.
      </div>
    );
  }

  const ultimo = pontos[pontos.length - 1];
  const marcas = [geometria.teto, (geometria.teto + geometria.piso) / 2, geometria.piso];

  return (
    <svg viewBox={`0 0 ${largura} ${altura}`} className="w-full" role="img" aria-label="Curva de perda do treino">
      <defs>
        <linearGradient id="mc-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10a37f" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#10a37f" stopOpacity="0" />
        </linearGradient>
      </defs>
      {marcas.map((valor, i) => (
        <g key={`marca-${i}`}>
          <line
            x1={margem.esq}
            y1={geometria.y(valor)}
            x2={largura - margem.dir}
            y2={geometria.y(valor)}
            stroke="#2e323b"
            strokeDasharray="3 5"
            strokeWidth={1}
          />
          <text x={margem.esq - 8} y={geometria.y(valor) + 4} textAnchor="end" fontSize={10.5} fill="#9aa0aa">
            {valor.toFixed(2)}
          </text>
        </g>
      ))}
      <path d={geometria.area} fill="url(#mc-area)" />
      <path
        d={geometria.linha}
        fill="none"
        stroke="#10a37f"
        strokeWidth={2.4}
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        className="mc-curva"
        style={{ ["--mc-tamanho" as string]: 1 }}
      />
      <circle cx={geometria.x(pontos.length - 1)} cy={geometria.y(ultimo.perda)} r={4.5} fill="#10a37f" className={emCurso ? "mc-pulso" : undefined} />
      <text
        x={geometria.x(pontos.length - 1) - 10}
        y={geometria.y(ultimo.perda) - 12}
        textAnchor="end"
        fontSize={11}
        fill="#e8e9ec"
        fontWeight={600}
      >
        {ultimo.tokens.toLocaleString("pt-PT")} tokens · perda {ultimo.perda.toFixed(3)}
      </text>
      <text x={margem.esq} y={altura - 10} fontSize={10.5} fill="#9aa0aa">
        passo {pontos[0].step}
      </text>
      <text x={largura - margem.dir} y={altura - 10} textAnchor="end" fontSize={10.5} fill="#9aa0aa">
        passo {ultimo.step}
      </text>
    </svg>
  );
}

/** O ciclo de um passo de treino: o que acontece entre duas actualizações. */
function CicloDeUmPasso({ ativo, paresPorPasso }: { ativo: boolean; paresPorPasso: number }) {
  const etapas = [
    { titulo: "Lote", nota: `${paresPorPasso} pares do dataset` },
    { titulo: "Forward", nota: "24 camadas do Qwen" },
    { titulo: "Perda", nota: "só nos tokens da resposta" },
    { titulo: "Backward", nota: "gradientes nas matrizes LoRA" },
    { titulo: "Update", nota: "AdamW · lr 2e-4" },
  ];
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-card/60 p-4">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <Activity size={14} className={ativo ? "text-primary mc-pulso" : "text-muted-foreground"} />
        ciclo de um passo
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {etapas.map((etapa, i) => (
          <div key={etapa.titulo} className="flex items-center gap-2">
            <div
              className="rounded-lg border border-border bg-muted/60 px-3 py-2"
              style={ativo ? { animation: "mc-gradiente 2.6s ease-in-out infinite", animationDelay: `${i * 0.45}s` } : undefined}
            >
              <div className="text-xs font-semibold">{etapa.titulo}</div>
              <div className="text-[10.5px] text-muted-foreground">{etapa.nota}</div>
            </div>
            {i < etapas.length - 1 && <ArrowRight size={14} className="text-muted-foreground/60" />}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Onde a LoRA escreve: 24 camadas × 7 projecções, com o gradiente a percorrer. */
function MapaDaLoRA({ emCurso }: { emCurso: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <Layers size={14} className="text-primary" />
        camadas do modelo onde a LoRA escreve (r=16)
      </div>
      <div className="flex gap-3">
        <div className="flex flex-col-reverse justify-between py-[1px] text-[9px] text-muted-foreground">
          {Array.from({ length: CAMADAS_QWEN }, (_, i) => (
            <span key={i}>{i + 1}</span>
          ))}
        </div>
        <div className="flex-1">
          <div className="flex gap-1">
            {PROJECOES.map((projecao) => (
              <div key={projecao} className="flex-1">
                <div className="mb-1 text-center text-[9px] uppercase tracking-wide text-muted-foreground">{projecao}</div>
                <div className="flex flex-col-reverse gap-[3px]">
                  {Array.from({ length: CAMADAS_QWEN }, (_, camada) => (
                    <div
                      key={camada}
                      className={`h-[6px] rounded-[2px] bg-primary/25 ${emCurso ? "mc-celula" : ""}`}
                      style={emCurso ? { animationDelay: `${((camada + PROJECOES.indexOf(projecao)) % 12) * 0.16}s` } : undefined}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
        LoRA não reescreve as 24 camadas: aprende duas matrizes pequenas (A·B) por projecção. O modelo base fica
        intacto no disco — o adaptador são ~8,8 M de parâmetros num ficheiro de 34 MB.
      </p>
    </div>
  );
}

function BarraComparativa({ rotulo, base, treinado, inverter = false }: { rotulo: string; base: number; treinado: number; inverter?: boolean }) {
  const maximo = Math.max(base, treinado, 1e-6);
  const melhor = inverter ? treinado < base : treinado > base;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{rotulo}</span>
        <span className={melhor ? "text-primary" : "text-amber-400"}>{melhor ? "adaptador melhor" : "adaptador pior"}</span>
      </div>
      {[
        { nome: "base", valor: base, classe: "bg-slate-500", destaque: false },
        { nome: "adaptador", valor: treinado, classe: melhor ? "bg-primary" : "bg-amber-400", destaque: true },
      ].map((linha) => (
        <div key={linha.nome} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{linha.nome}</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full transition-all duration-700 ${linha.classe}`}
              style={{ width: `${(linha.valor / maximo) * 100}%` }}
            />
          </div>
          <span className={`w-14 text-right text-[10px] tabular-nums ${linha.destaque ? "text-foreground" : "text-muted-foreground"}`}>
            {fmt(linha.valor, 3)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ModeloContratosPage() {
  const [estado, setEstado] = useState<ModeloEstado | null>(null);
  const [curva, setCurva] = useState<PontoTreino[]>([]);
  const [avaliacoes, setAvaliacoes] = useState<ResultadoAvaliacao[]>([]);
  const [erroEstado, setErroEstado] = useState<string | null>(null);
  const [aCarregar, setACarregar] = useState(true);
  const [aAvaliar, setAAvaliar] = useState(false);
  const [resultado, setResultado] = useState<ResultadoAvaliacao | null>(null);
  const [matriz, setMatriz] = useState<MatrizAdaptador | null>(null);
  const [ligacoes, setLigacoes] = useState<Ligacoes | null>(null);
  const [camadaSelecionada, setCamadaSelecionada] = useState(23);
  // Relógio explícito: a frescura do último ponto de treino tem de ser decidida
  // fora do render (ler `Date.now()` no render é impuro e o React não re-renderiza
  // sozinho quando o tempo passa).
  const [agora, setAgora] = useState(() => Date.now() / 1000);

  useEffect(() => {
    const relogio = window.setInterval(() => setAgora(Date.now() / 1000), 30000);
    return () => window.clearInterval(relogio);
  }, []);

  const carregar = useCallback(async () => {
    try {
      const [ficha, pontos, historico, pesos, proveniencia] = await Promise.all([
        getModeloEstado(),
        getCurvaTreino(400).catch(() => ({ pontos: [], total: 0 })),
        listarAvaliacoes(12).catch(() => ({ avaliacoes: [], total: 0 })),
        getMatriz().catch(() => null),
        getLigacoes().catch(() => null),
      ]);
      setEstado(ficha);
      setCurva(pontos.pontos);
      setAvaliacoes(historico.avaliacoes);
      setResultado((anterior) => anterior ?? historico.avaliacoes[0] ?? null);
      setMatriz(pesos);
      setLigacoes(proveniencia);
      setErroEstado(null);
    } catch (erro) {
      setErroEstado(erro instanceof Error ? erro.message : "Falha ao ler o estado do modelo");
    } finally {
      setACarregar(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const treino = estado?.treino?.treino;
  const passos = treino?.passos ?? (curva.length ? curva[curva.length - 1].step : 0);
  const planeados = treino?.passos_planeados ?? 0;
  const ultimo = curva.length ? curva[curva.length - 1] : null;
  // «Em curso» não se decide pelo plano (que muda de corrida para corrida, ex.:
  // 30 passos e depois 50 ao retomar): decide-se pelo instante do último ponto.
  // Um treino pausado ou interrompido deixa de acender ao fim de 4 minutos.
  const segundosDesdeOPonto = ultimo?.ts ? agora - ultimo.ts : null;
  const emCurso = !estado?.pausado && segundosDesdeOPonto !== null && segundosDesdeOPonto < 240;
  const percentagem = planeados ? Math.min(100, (passos / planeados) * 100) : 0;
  const anterior = curva.length > 1 ? curva[curva.length - 2] : null;
  const velocidade = ultimo && anterior && ultimo.segundos > anterior.segundos
    ? (ultimo.tokens - anterior.tokens) / (ultimo.segundos - anterior.segundos)
    : null;

  useEffect(() => {
    if (!emCurso) return;
    const timer = window.setInterval(() => void carregar(), 8000);
    return () => window.clearInterval(timer);
  }, [emCurso, carregar]);

  const avaliar = async () => {
    setAAvaliar(true);
    try {
      const r = await correrAvaliacao({ limite: 8, gerar: 2 });
      setResultado(r);
      await carregar();
    } catch (erro) {
      setErroEstado(erro instanceof Error ? erro.message : "Falha na avaliação");
    } finally {
      setAAvaliar(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Brain size={22} className="text-primary" />
            Modelo de contratos
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Fine-tuning LoRA do <span className="text-foreground">{estado?.modelo_base ?? "Qwen2.5-0.5B-Instruct"}</span> com
            contratos, entidades e subsídios extraídos do Elasticsearch. O adaptador é avaliado num conjunto held-out que o
            treino nunca viu.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
              estado?.pausado
                ? "border-amber-400/40 text-amber-400"
                : emCurso
                  ? "border-primary/40 text-primary"
                  : "border-border text-muted-foreground"
            }`}
          >
            {estado?.pausado ? <PauseCircle size={13} /> : emCurso ? <Activity size={13} className="mc-pulso" /> : <CheckCircle2 size={13} />}
            {estado?.pausado ? "pausado" : emCurso ? "a treinar" : estado?.adaptador_disponivel ? "adaptador pronto" : "sem adaptador"}
          </span>
          <button
            type="button"
            onClick={() => void carregar()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted"
          >
            <RefreshCw size={13} className={aCarregar ? "animate-spin" : undefined} />
            Actualizar
          </button>
        </div>
      </header>

      {erroEstado && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertCircle size={16} className="mt-0.5 text-destructive" />
          <div>
            <div className="font-medium">Não foi possível ler o estado do modelo</div>
            <div className="text-muted-foreground">{erroEstado}</div>
          </div>
        </div>
      )}

      {estado && (
        <>
          <section className="rounded-2xl border border-border bg-card/40 p-4">
            <PipelineDiagram estado={estado} avaliacoes={avaliacoes.length} />
          </section>

          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Cartao
              titulo="Perda"
              valor={ultimo ? fmt(ultimo.perda, 3) : "—"}
              nota={ultimo ? `perplexidade ${fmt(ultimo.perplexidade, 2)}` : "sem métricas"}
              icone={<Gauge size={13} />}
            />
            <Cartao
              titulo="Progresso"
              valor={planeados ? `${passos}/${planeados}` : "—"}
              nota={planeados ? `${fmt(percentagem, 0)}% do plano` : `${curva.length} pontos registados`}
              icone={<Activity size={13} />}
              tom="azul"
            />
            <Cartao
              titulo="Tokens vistos"
              valor={ultimo ? ultimo.tokens.toLocaleString("pt-PT") : "—"}
              nota={velocidade ? `${fmt(velocidade, 1)} tok/s nesta CPU` : "velocidade por medir"}
              icone={<Zap size={13} />}
              tom="ambar"
            />
            <Cartao
              titulo="Tempo de treino"
              valor={duracao(ultimo?.segundos ?? treino?.segundos)}
              nota={treino?.concluido_em ? `fim: ${new Date(treino.concluido_em).toLocaleString("pt-PT")}` : "corrida em curso"}
              icone={<Timer size={13} />}
              tom="rosa"
            />
          </section>

          <section className="grid gap-3 xl:grid-cols-[1fr_1.05fr]">
            <GrafoDoModelo
              matriz={matriz}
              camadaSelecionada={camadaSelecionada}
              onSelecionar={setCamadaSelecionada}
              animar={emCurso}
            />
            <MatrizDePesos
              matriz={matriz}
              camadaSelecionada={camadaSelecionada}
              onSelecionar={setCamadaSelecionada}
              animar={emCurso}
            />
          </section>

          <section>
            <LigacoesDeDados ligacoes={ligacoes} animar={emCurso} />
          </section>

          <section className="space-y-3 rounded-2xl border border-border bg-card/40 p-4">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="flex items-center gap-2 uppercase tracking-wide">
                <Activity size={14} className="text-primary" />
                curva de perda
              </span>
              <span>{estado.metricas.pontos} pontos · {estado.pausado ? "treino pausado" : emCurso ? "em directo" : "parado"}</span>
            </div>
            <div className="relative h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-700"
                style={{ width: `${percentagem}%` }}
              />
              {emCurso && <div className="mc-brilho absolute inset-0" />}
            </div>
            <CurvaDePerda pontos={curva} emCurso={emCurso} />
          </section>

          <section className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-3">
              <CicloDeUmPasso
                ativo={emCurso}
                paresPorPasso={(estado.treino?.treino?.batch_size ?? 1) * (estado.treino?.treino?.grad_accum ?? 4)}
              />
              <div className="rounded-xl border border-border bg-card/60 p-4 text-sm">
                <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                  <Database size={14} className="text-primary" />
                  de onde vêm os dados
                </div>
                <ul className="space-y-1.5 text-muted-foreground">
                  {estado.fonte_dados.indices.map((indice) => (
                    <li key={indice} className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary/70" />
                      <code className="text-foreground">{indice}</code>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  Exportados com <code>{estado.fonte_dados.exportador}</code> para{" "}
                  <code>{estado.treino?.dados?.ficheiro ?? estado.fonte_dados.ficheiro}</code>. Cada par é um documento real
                  (instrução + campos + resposta de referência), por isso o modelo aprende o vocabulário dos contratos e não
                  frases inventadas.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  LoRA r={estado.treino?.lora?.r ?? 16} · alpha={estado.treino?.lora?.alpha ?? 32} · lr{" "}
                  {estado.treino?.treino?.lr ?? "2e-4"} · batch {estado.treino?.treino?.batch_size ?? 1} ×{" "}
                  {estado.treino?.treino?.grad_accum ?? 4}
                </p>
              </div>
            </div>
            <MapaDaLoRA emCurso={emCurso} />
          </section>

          <section className="space-y-3 rounded-2xl border border-border bg-card/40 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                <Gauge size={14} className="text-primary" />
                avaliação no held-out
              </span>
              <button
                type="button"
                onClick={() => void avaliar()}
                disabled={aAvaliar || !estado.adaptador_disponivel}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
              >
                {aAvaliar ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                {aAvaliar ? "a medir (pode levar minutos)" : "Correr avaliação"}
              </button>
            </div>

            {resultado && (resultado.treinado ?? resultado.base) ? (
              <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
                <div className="space-y-3">
                  <BarraComparativa
                    rotulo="perplexidade (menor é melhor)"
                    base={resultado.base?.perplexidade ?? 0}
                    treinado={resultado.treinado?.perplexidade ?? 0}
                    inverter
                  />
                  <BarraComparativa
                    rotulo="exatidão por token (maior é melhor)"
                    base={resultado.base?.exactidao_token ?? 0}
                    treinado={resultado.treinado?.exactidao_token ?? 0}
                  />
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>pares: {resultado.conjunto?.pares ?? "—"}</span>
                    <span>fontes: {(resultado.conjunto?.origem ?? []).join(", ") || "—"}</span>
                    <span>duração: {duracao(resultado.duracao_s)}</span>
                    <span>fidelidade numérica: {resultado.fidelidade_numerica == null ? "—" : `${fmt(resultado.fidelidade_numerica * 100, 0)}%`}</span>
                  </div>
                </div>
                <div className="space-y-2">
                  {avaliacoes.slice(0, 5).map((item, i) => (
                    <div key={item.id ?? i} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-xs">
                      <span className="text-muted-foreground">{item.criado_em ? new Date(item.criado_em).toLocaleString("pt-PT") : `corrida ${i + 1}`}</span>
                      <span className={((item.delta?.perplexidade ?? 0) < 0) ? "text-primary" : "text-amber-400"}>
                        Δ perplexidade {fmt(item.delta?.perplexidade ?? 0, 2)}
                      </span>
                    </div>
                  ))}
                  {!avaliacoes.length && <span className="text-xs text-muted-foreground">Ainda sem histórico no Elasticsearch.</span>}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sem avaliação guardada. Corre a avaliação para comparar o modelo base com o adaptador nos pares held-out.
              </p>
            )}
          </section>

          <section className="space-y-3 rounded-2xl border border-border bg-card/40 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                <Brain size={14} className="text-primary" />
                chat do modelo · memória, skills, RAG e raciocínio
              </span>
              <a
                href="/modelo/playground"
                onClick={(e) => {
                  e.preventDefault();
                  window.history.pushState({}, "", "/modelo/playground");
                  window.dispatchEvent(new PopStateEvent("popstate"));
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <FlaskConical size={11} />
                abrir no playground
                <ExternalLink size={10} />
              </a>
            </div>
            <ChatDoModelo />
          </section>
        </>
      )}

      {!estado && aCarregar && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={15} className="animate-spin" /> A ler a ficha do modelo…
        </div>
      )}
    </div>
  );
}
