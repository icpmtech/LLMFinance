/**
 * Página de auto-aprendizagem do modelo de contratos (`/modelo/retreino`).
 *
 * Concentra o que antes só existia espalhado: estado do adaptador, formulário
 * de retreino (passos e learning rate), paragem, versões guardadas com
 * reverção, histórico de adaptações, reindexação do corpus RAG e avaliação.
 *
 * Agora também mostra, em direto, **o que se está a passar no treino**:
 * pipeline de dados, grafo do modelo, matriz de pesos LoRA e animações
 * sincronizadas com o WebSocket `/llm/modelo/retreinar/ws`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brain, Database, Layers, Sparkles } from "lucide-react";
import PainelDeRetreino from "../components/modelo/PainelDeRetreino";
import GrafoDoModelo from "../components/modelo/GrafoDoModelo";
import MatrizDePesos from "../components/modelo/MatrizDePesos";
import LigacoesDeDados from "../components/modelo/LigacoesDeDados";
import {
  getLigacoes,
  getMatriz,
  getModeloEstado,
  urlRetreinoAoVivo,
  type EstadoAoVivo,
  type Ligacoes,
  type MatrizAdaptador,
  type ModeloEstado,
} from "../llmModeloApi";

const formatarNumero = (valor?: number | null, casas = 3) =>
  typeof valor === "number" && Number.isFinite(valor) ? valor.toFixed(casas) : "—";

const formatarDuracao = (segundos?: number | null) => {
  if (!segundos || segundos <= 0) return "—";
  const total = Math.round(segundos);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${s} s`;
  return `${s} s`;
};

function Estatistica({ rotulo, valor, nota }: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{rotulo}</p>
      <p className="mt-0.5 truncate text-[13px] font-medium tabular-nums text-foreground" title={valor}>
        {valor}
      </p>
      {nota && (
        <p className="truncate text-[10px] text-muted-foreground" title={nota}>
          {nota}
        </p>
      )}
    </div>
  );
}

export default function ModeloRetreinoPage() {
  const [modelo, setModelo] = useState<ModeloEstado | null>(null);
  const [matriz, setMatriz] = useState<MatrizAdaptador | null>(null);
  const [ligacoes, setLigacoes] = useState<Ligacoes | null>(null);
  const [camadaSelecionada, setCamadaSelecionada] = useState(23);
  const [aCarregarGrafo, setACarregarGrafo] = useState(true);
  const [erroGrafo, setErroGrafo] = useState<string | null>(null);

  // Estado ao vivo vindo do WebSocket do retreino.
  const [aoVivo, setAoVivo] = useState<EstadoAoVivo | null>(null);
  const [ligadoWs, setLigadoWs] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const montadoRef = useRef(true);
  const tentativasRef = useRef(0);
  const fecharRef = useRef(false);

  const carregarGrafo = useCallback(async () => {
    setACarregarGrafo(true);
    setErroGrafo(null);
    try {
      const [estado, pesos, proveniencia] = await Promise.all([
        getModeloEstado(),
        getMatriz(),
        getLigacoes(),
      ]);
      if (!montadoRef.current) return;
      setModelo(estado);
      setMatriz(pesos);
      setLigacoes(proveniencia);
      setErroGrafo(null);
    } catch (falha) {
      if (!montadoRef.current) return;
      setErroGrafo(falha instanceof Error ? falha.message : "Falha ao ler o grafo");
    } finally {
      if (montadoRef.current) setACarregarGrafo(false);
    }
  }, []);

  useEffect(() => {
    montadoRef.current = true;
    void carregarGrafo();
    return () => {
      montadoRef.current = false;
      fecharRef.current = true;
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [carregarGrafo]);

  const ligarWs = useCallback(() => {
    if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) return;
    fecharRef.current = false;
    const url = urlRetreinoAoVivo();
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch {
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      if (!montadoRef.current) return;
      tentativasRef.current = 0;
      setLigadoWs(true);
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
      setAoVivo(dados);
      // Quando o treino arranca ou avança, refresca também a matriz/ligações.
      if (dados.a_correr && dados.fase === "a_treinar" && (dados.passo ?? 0) % 4 === 1) {
        void carregarGrafo();
      }
    };

    socket.onerror = () => {
      if (!montadoRef.current) return;
      setLigadoWs(false);
    };

    socket.onclose = (evento) => {
      if (!montadoRef.current) return;
      setLigadoWs(false);
      if (fecharRef.current) return;
      if (evento.code === 1008) return;
      const espera = Math.min(8000, 500 * 2 ** tentativasRef.current);
      tentativasRef.current += 1;
      window.setTimeout(() => {
        if (!fecharRef.current && montadoRef.current) ligarWs();
      }, espera);
    };
  }, [carregarGrafo]);

  useEffect(() => {
    ligarWs();
  }, [ligarWs]);

  const aCorrer = useMemo(
    () => Boolean(aoVivo?.a_correr) || Boolean(aoVivo?.externo?.a_correr),
    [aoVivo],
  );

  const treino = modelo?.treino?.treino;
  const passosFeitos = treino?.passos ?? 0;
  const passosPlaneados = treino?.passos_planeados ?? 0;
  const tokensTreino = treino?.tokens ?? modelo?.metricas?.tokens ?? 0;

  return (
    <div className="w-full bg-background">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <header className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Brain size={18} />
          </div>
          <div>
            <h1 className="text-lg font-medium text-foreground">Auto-aprendizagem do modelo</h1>
            <p className="mt-0.5 max-w-2xl text-[12px] leading-relaxed text-muted-foreground">
              Adaptação LoRA incremental do <span className="text-foreground">Qwen 0.5B + LoRA</span> de contratos
              públicos. Cada execução usa as correções humanas e as skills com exemplo, guarda o adaptador anterior,
              mede a perda antes e depois e fica registada no histórico.
            </p>
          </div>
        </header>

        <div className="mb-4 flex items-start gap-2 rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
          <Sparkles size={13} className="mt-0.5 shrink-0 text-primary" />
          <span>
            O retreino precisa de pelo menos <span className="text-foreground">3 pares com correção</span>. Se todos os
            pares já foram usados, ative <span className="text-foreground">«reutilizar pares já treinados»</span> para
            repetir a adaptação com o mesmo material.
          </span>
        </div>

        <PainelDeRetreino variante="pagina" />

        <section className="mt-5 rounded-2xl border border-border bg-card/40 p-4">
          <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Database size={14} className="text-primary" />
            dados e treino
          </div>
          {!modelo ? (
            <p className="text-[11px] text-muted-foreground">Sem ficha do modelo — verifique a API.</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              <Estatistica
                rotulo="modelo base"
                valor={modelo.modelo_base ?? "—"}
                nota={modelo.adaptador_disponivel ? "adaptador carregado" : "sem adaptador"}
              />
              <Estatistica
                rotulo="pares no dataset"
                valor={String(modelo.treino?.dados?.pares_treino ?? ligacoes?.dataset.pares ?? "—")}
                nota={`held-out ${modelo.treino?.dados?.pares_holdout ?? ligacoes?.dataset.pares_holdout ?? "—"}`}
              />
              <Estatistica
                rotulo="passos do treino"
                valor={passosPlaneados ? `${passosFeitos}/${passosPlaneados}` : String(passosFeitos)}
                nota={`${treino?.epocas ?? "—"} épocas · lr ${treino?.lr ?? "—"}`}
              />
              <Estatistica
                rotulo="perda final"
                valor={formatarNumero(treino?.perda_final)}
                nota={`perplexidade ${formatarNumero(modelo.metricas?.ultima_perplexidade)}`}
              />
              <Estatistica
                rotulo="tokens vistos"
                valor={tokensTreino ? tokensTreino.toLocaleString("pt-PT") : "—"}
                nota={`${modelo.metricas?.pontos ?? 0} pontos na curva`}
              />
              <Estatistica
                rotulo="tempo de treino"
                valor={formatarDuracao(treino?.segundos)}
                nota={treino?.concluido_em ? `fim: ${treino.concluido_em}` : "sem fim registado"}
              />
            </div>
          )}
          {(modelo?.treino?.dados?.fontes?.length ?? 0) > 0 && (
            <p className="mt-2 text-[10.5px] text-muted-foreground">
              fontes: {modelo?.treino?.dados?.fontes?.join(" · ")} · dataset{" "}
              {modelo?.treino?.dados?.ficheiro ?? modelo?.fonte_dados?.ficheiro ?? "—"}
            </p>
          )}
        </section>

        <section className="mt-5 rounded-2xl border border-border bg-card/40 p-4">
          <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Layers size={14} className="text-primary" />
            grafo do modelo e ligações de dados
            <span
              className={`ml-auto inline-flex items-center gap-1 text-[10px] ${
                ligadoWs ? "text-primary" : "text-muted-foreground"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${ligadoWs ? "bg-primary animate-pulse" : "bg-muted-foreground/50"}`} />
              {ligadoWs ? "ws ligado" : "ws desligado"}
            </span>
          </div>

          {erroGrafo ? (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[11px] text-amber-400">
              {erroGrafo}
            </div>
          ) : aCarregarGrafo ? (
            <p className="text-[11px] text-muted-foreground">A ler grafo e ligações…</p>
          ) : (
            <>
              <div className="mb-3 grid gap-3 xl:grid-cols-[1fr_1.05fr]">
                <GrafoDoModelo
                  matriz={matriz}
                  camadaSelecionada={camadaSelecionada}
                  onSelecionar={setCamadaSelecionada}
                  animar={aCorrer}
                />
                <MatrizDePesos
                  matriz={matriz}
                  camadaSelecionada={camadaSelecionada}
                  onSelecionar={setCamadaSelecionada}
                  animar={aCorrer}
                />
              </div>
              <LigacoesDeDados ligacoes={ligacoes} animar={aCorrer} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
