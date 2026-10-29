/**
 * Retreino do modelo em direto (WebSocket + gráficos).
 *
 * O backend expõe `/llm/modelo/retreinar/ws`, que envia o retrato completo do
 * estado a cada mudança: fase, passo, perda, tokens e a curva desde o passo 1.
 * Este componente desenha esse fluxo — onde está, o que já passou, e a perda a
 * descer (ou não) — em vez de um contador que só se actualiza por polling.
 *
 * Liga-se sozinho quando há adaptação a correr ou quando o utilizador carrega em
 * «ligar ao vivo»; reconecta com espera crescente e fecha quando a página sai.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Cpu,
  Database,
  Gauge,
  Loader2,
  PlugZap,
  Save,
  Unplug,
} from "lucide-react";
import { urlRetreinoAoVivo, type EstadoAoVivo, type PassoAoVivo } from "../../llmModeloApi";

type Props = {
  /** Estado já conhecido (do polling HTTP), para desenhar antes do WS abrir. */
  aCorrer?: boolean;
  className?: string;
  /** Abre a ligação automaticamente quando já há adaptação a correr. */
  autoLigar?: boolean;
};

const FASES: { id: string; rotulo: string; icone: React.ElementType }[] = [
  { id: "a_preparar", rotulo: "pares e modelo", icone: Database },
  { id: "a_treinar", rotulo: "passos LoRA", icone: Cpu },
  { id: "a_avaliar", rotulo: "perda antes/depois", icone: Gauge },
  { id: "a_guardar", rotulo: "guardar + backup", icone: Save },
];

const ORDEM = FASES.map((f) => f.id);

const formatarSegundos = (total: number) => {
  if (!Number.isFinite(total) || total <= 0) return "—";
  const s = Math.round(total);
  const m = Math.floor(s / 60);
  const resto = s % 60;
  return m > 0 ? `${m}m ${String(resto).padStart(2, "0")}s` : `${resto}s`;
};

const formatarPerda = (valor?: number | null) =>
  typeof valor === "number" ? valor.toFixed(4) : "—";

const formatarData = (valor?: string | null) => {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
};

/** Gráfico de linha da perda por passo, com área e eixo Y anotado. */
function GraficoDePerda({
  pontos,
  altura = 132,
  vazio = "sem passos registados ainda",
}: {
  pontos: PassoAoVivo[];
  altura?: number;
  vazio?: string;
}) {
  const largura = 640;
  const margem = { topo: 10, direita: 8, fundo: 16, esquerda: 34 };

  const dados = pontos.filter((p) => typeof p.perda === "number");
  const geometria = useMemo(() => {
    if (dados.length === 0) return null;
    const valores = dados.map((p) => p.perda);
    const min = Math.min(...valores);
    const max = Math.max(...valores);
    // Uma perda constante daria uma linha a zero de altura: abre-se uma faixa.
    const folga = max === min ? Math.max(0.05, Math.abs(max) * 0.1 || 0.05) : (max - min) * 0.15;
    const topo = max + folga;
    const fundo = Math.max(0, min - folga);
    const areaLargura = largura - margem.esquerda - margem.direita;
    const areaAltura = altura - margem.topo - margem.fundo;
    const x = (i: number) =>
      margem.esquerda + (dados.length === 1 ? areaLargura / 2 : (i / (dados.length - 1)) * areaLargura);
    const y = (v: number) => margem.topo + areaAltura - ((v - fundo) / (topo - fundo || 1)) * areaAltura;
    const linha = dados.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.perda).toFixed(1)}`).join(" ");
    const area = `${linha} L${x(dados.length - 1).toFixed(1)},${(margem.topo + areaAltura).toFixed(1)} L${x(0).toFixed(1)},${(margem.topo + areaAltura).toFixed(1)} Z`;
    return { linha, area, topo, fundo, y, x, ultimo: dados[dados.length - 1] };
  }, [dados, altura]);

  if (!geometria) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border/70 px-2 text-center text-[11px] text-muted-foreground"
        style={{ height: altura }}
      >
        {vazio}
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${largura} ${altura}`}
      className="w-full"
      style={{ height: altura }}
      role="img"
      aria-label="Curva de perda por passo"
    >
      <defs>
        <linearGradient id="gradPerda" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* grelha horizontal com os extremos da escala */}
      {[0, 0.5, 1].map((f) => {
        const yy = margem.topo + (altura - margem.topo - margem.fundo) * f;
        const valor = geometria.topo - (geometria.topo - geometria.fundo) * f;
        return (
          <g key={f}>
            <line
              x1={margem.esquerda}
              x2={largura - margem.direita}
              y1={yy}
              y2={yy}
              className="stroke-border/60"
              strokeWidth="1"
              strokeDasharray={f === 1 ? "0" : "3 4"}
            />
            <text x={2} y={yy + 3.5} className="fill-muted-foreground" style={{ fontSize: 9 }}>
              {valor.toFixed(3)}
            </text>
          </g>
        );
      })}
      <path d={geometria.area} fill="url(#gradPerda)" className="text-primary" />
      <path d={geometria.linha} fill="none" strokeWidth="2" className="stroke-primary" strokeLinejoin="round" />
      <circle
        cx={geometria.x(dados.length - 1)}
        cy={geometria.y(geometria.ultimo.perda)}
        r="3.5"
        className="fill-primary"
      />
      <text
        x={largura - margem.direita}
        y={altura - 3}
        textAnchor="end"
        className="fill-muted-foreground"
        style={{ fontSize: 9 }}
      >
        passo {geometria.ultimo.passo}
      </text>
    </svg>
  );
}

export default function RetreinoAoVivo({ aCorrer = false, className = "", autoLigar = true }: Props) {
  const [ligado, setLigado] = useState(false);
  const [estado, setEstado] = useState<EstadoAoVivo | null>(null);
  const [erroLigacao, setErroLigacao] = useState<string | null>(null);
  const [eventos, setEventos] = useState<string[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const tentativasRef = useRef(0);
  const fecharRef = useRef(false);
  const montadoRef = useRef(true);

  const registar = useCallback((texto: string) => {
    setEventos((antes) => {
      const ultimo = antes[antes.length - 1];
      if (ultimo === texto) return antes;
      return [...antes, texto].slice(-40);
    });
  }, []);

  const ligar = useCallback(() => {
    if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) return;
    fecharRef.current = false;
    const url = urlRetreinoAoVivo();
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (falha) {
      setErroLigacao(falha instanceof Error ? falha.message : "WebSocket indisponível");
      return;
    }
    socketRef.current = socket;
    setErroLigacao(null);

    socket.onopen = () => {
      if (!montadoRef.current) return;
      tentativasRef.current = 0;
      setLigado(true);
      registar("ligado ao fluxo do retreino");
    };

    socket.onmessage = (evento) => {
      if (!montadoRef.current) return;
      let dados: EstadoAoVivo;
      try {
        dados = JSON.parse(evento.data as string) as EstadoAoVivo;
      } catch {
        return;
      }
      if (dados.tipo === "ping") return;
      setEstado(dados);
      if (dados.fase) registar(`${dados.fase}${dados.atividade ? ` · ${dados.atividade}` : ""}`);
      if (dados.passo) registar(`passo ${dados.passo}/${dados.passos} · perda ${formatarPerda(dados.perda)}`);
      if (dados.erro) registar(`erro: ${dados.erro}`);
    };

    socket.onerror = () => {
      if (!montadoRef.current) return;
      setErroLigacao("não foi possível abrir o canal em direto");
    };

    socket.onclose = (evento) => {
      if (!montadoRef.current) return;
      setLigado(false);
      if (fecharRef.current) return;
      // 1008 = o servidor recusou a sessão: reconectar não resolve.
      if (evento.code === 1008) {
        setErroLigacao(evento.reason || "sessão inválida para o canal em direto");
        return;
      }
      // Espera crescente (0,5 s → 8 s) para não martelar o servidor.
      const espera = Math.min(8000, 500 * 2 ** tentativasRef.current);
      tentativasRef.current += 1;
      window.setTimeout(() => {
        if (!fecharRef.current && montadoRef.current) ligar();
      }, espera);
    };
  }, [registar]);

  const desligar = useCallback(() => {
    fecharRef.current = true;
    socketRef.current?.close();
    socketRef.current = null;
    setLigado(false);
  }, []);

  useEffect(() => {
    montadoRef.current = true;
    // Ligar mesmo sem treino a correr: o retrato traz a última adaptação, e é
    // isso que impede o painel de abrir vazio depois de um restart.
    if (autoLigar) ligar();
    return () => {
      montadoRef.current = false;
      fecharRef.current = true;
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [autoLigar, aCorrer, ligar]);

  const historico = estado?.historico ?? [];
  const externo = estado?.externo;
  const faseAtual = estado?.fase ?? (aCorrer ? "a_preparar" : "ocioso");
  const indiceFase = ORDEM.indexOf(faseAtual);
  const aCorrerAgora = Boolean(estado?.a_correr ?? aCorrer);
  // Há uma adaptação anterior para mostrar (em memória ou lida do histórico).
  const concluido = Boolean(estado?.ultimo_resultado) || (!aCorrerAgora && historico.length > 0);

  const decorrido = useMemo(() => {
    if (!estado?.iniciado_ts || !estado?.agora_ts) return null;
    return Math.max(0, estado.agora_ts - estado.iniciado_ts);
  }, [estado?.iniciado_ts, estado?.agora_ts]);

  const porPasso = historico.length > 1 ? (decorrido ?? 0) / historico.length : null;
  const restantes = estado ? Math.max(0, estado.passos - estado.passo) : 0;
  const previsao = porPasso && restantes ? porPasso * restantes : null;
  const progresso = estado?.passos ? Math.min(100, Math.round((estado.passo / estado.passos) * 100)) : 0;
  const delta =
    estado && estado.perda_antes != null && estado.perda_depois != null
      ? estado.perda_depois - estado.perda_antes
      : null;

  return (
    <div className={`rounded-xl border border-border bg-card/60 p-3 ${className}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          <Activity size={12} className={aCorrerAgora ? "text-primary" : undefined} />
          {aCorrerAgora || !concluido ? "processo em direto" : "última adaptação"}
        </span>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 text-[10px] ${
              ligado ? "text-primary" : "text-muted-foreground"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${ligado ? "bg-primary animate-pulse" : "bg-muted-foreground/50"}`}
            />
            {ligado ? "ws ligado" : "ws desligado"}
          </span>
          <button
            type="button"
            onClick={() => (ligado ? desligar() : ligar())}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2 py-1 text-[10px] text-foreground hover:bg-muted"
          >
            {ligado ? <Unplug size={10} /> : <PlugZap size={10} />}
            {ligado ? "desligar" : "ligar ao vivo"}
          </button>
        </div>
      </div>

      {/* Fluxo das fases: o que já passou, o que está a acontecer, o que falta. */}
      <ol className="mb-3 flex flex-wrap items-center gap-1">
        {FASES.map((fase, indice) => {
          const feito = indiceFase > indice || faseAtual === "concluido";
          const ativo = indiceFase === indice && aCorrerAgora;
          const Icone = fase.icone;
          return (
            <li key={fase.id} className="flex items-center gap-1">
              <span
                className={[
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition",
                  ativo
                    ? "border-primary/50 bg-primary/15 text-primary"
                    : feito
                      ? "border-primary/25 bg-primary/5 text-primary/80"
                      : "border-border bg-muted/30 text-muted-foreground",
                ].join(" ")}
              >
                {ativo ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : feito ? (
                  <CheckCircle2 size={10} />
                ) : (
                  <Icone size={10} />
                )}
                {fase.rotulo}
              </span>
              {indice < FASES.length - 1 && <Circle size={3} className="fill-border text-border" />}
            </li>
          );
        })}
      </ol>

      {estado?.atividade && (
        <p className="mb-2 truncate text-[11px] text-foreground" title={estado.atividade}>
          {estado.atividade}
        </p>
      )}

      {aCorrerAgora && (
        <div className="mb-2">
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progresso}%` }} />
          </div>
          <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-[10px] text-muted-foreground">
            <span>
              passo {estado?.passo ?? 0}/{estado?.passos ?? 0}
            </span>
            <span>perda {formatarPerda(estado?.perda)}</span>
            <span>{estado?.tokens ?? 0} tokens</span>
            <span>decorrido {formatarSegundos(decorrido ?? 0)}</span>
            {previsao != null && <span>faltam ~{formatarSegundos(previsao)}</span>}
          </div>
        </div>
      )}

      {/* Parado: o mesmo resumo do último ciclo, para o painel não ficar vazio
          quando a página abre depois de um treino já concluído. */}
      {!aCorrerAgora && concluido && (
        <div className="mb-2 flex flex-wrap justify-between gap-x-3 text-[10px] text-muted-foreground">
          <span>
            última: passo {estado?.passo ?? 0}/{estado?.passos ?? 0}
          </span>
          <span>perda final {formatarPerda(estado?.perda_depois ?? estado?.perda)}</span>
          {estado?.tokens ? <span>{estado.tokens} tokens</span> : null}
          <span>{estado?.iniciado ? formatarData(estado.iniciado) : "sem data"}</span>
        </div>
      )}

      <GraficoDePerda
        pontos={historico}
        vazio={
          concluido
            ? "esta adaptação não guardou a curva passo a passo (registos anteriores); a perda antes/depois está abaixo"
            : undefined
        }
      />

      {externo?.disponivel && externo.pontos?.length ? (
        <div className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2">
          <p className="mb-1 flex items-center justify-between text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Cpu size={10} /> treino completo (script)
            </span>
            <span>
              passo {externo.passo}
              {externo.total ? `/${externo.total}` : ""}
              {externo.a_correr ? " · a correr" : " · parado"}
            </span>
          </p>
          <GraficoDePerda
            altura={84}
            pontos={externo.pontos.map((p) => ({ passo: p.step, perda: p.perda }))}
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            {externo.a_correr ? "a correr fora da API" : "corrida fora da API"} · actualizado{" "}
            {externo.atualizado_em ?? "—"}
          </p>
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
        <div className="rounded-lg border border-border/60 bg-background/60 px-2 py-1">
          <p className="text-muted-foreground">perda inicial</p>
          <p className="text-[12px] text-foreground">{formatarPerda(estado?.perda_antes)}</p>
        </div>
        <div className="rounded-lg border border-border/60 bg-background/60 px-2 py-1">
          <p className="text-muted-foreground">perda final</p>
          <p className="text-[12px] text-foreground">{formatarPerda(estado?.perda_depois)}</p>
        </div>
        <div className="rounded-lg border border-border/60 bg-background/60 px-2 py-1">
          <p className="text-muted-foreground">variação</p>
          <p className={`text-[12px] ${delta == null ? "text-foreground" : delta < 0 ? "text-primary" : "text-amber-500"}`}>
            {delta == null ? "—" : `${delta > 0 ? "+" : ""}${formatarPerda(delta)}`}
          </p>
        </div>
      </div>

      {estado?.paragem_pedida && (
        <p className="mt-2 flex items-center gap-1 text-[10px] text-amber-500">
          <AlertTriangle size={11} /> paragem pedida — termina no próximo passo
        </p>
      )}
      {erroLigacao && (
        <p className="mt-2 flex items-center gap-1 text-[10px] text-amber-500">
          <AlertTriangle size={11} /> {erroLigacao}
        </p>
      )}

      {eventos.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">
            registo ({eventos.length})
          </summary>
          <ul className="mt-1 max-h-28 space-y-0.5 overflow-y-auto font-mono text-[10px] text-muted-foreground">
            {eventos.slice(-12).map((linha, indice) => (
              <li key={`${indice}-${linha}`} className="truncate" title={linha}>
                › {linha}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
