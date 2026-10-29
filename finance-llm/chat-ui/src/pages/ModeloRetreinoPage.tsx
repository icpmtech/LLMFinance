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
import { Brain, Layers, Sparkles } from "lucide-react";
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
    } catch (falha) {
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
    () =>
      Boolean(aoVivo?.a_correr) ||
      (modelo?.treino?.treino?.passos ?? 0) > 0 ||
      (modelo?.metricas?.pontos ?? 0) > 0,
    [aoVivo, modelo],
  );

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
