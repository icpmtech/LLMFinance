/**
 * Página de auto-aprendizagem do modelo de contratos (`/modelo/retreino`).
 *
 * Concentra o que antes só existia espalhado: estado do adaptador, formulário
 * de retreino (passos e learning rate), paragem, versões guardadas com
 * reverção, histórico de adaptações, reindexação do corpus RAG e avaliação.
 */
import { Brain, Sparkles } from "lucide-react";
import PainelDeRetreino from "../components/modelo/PainelDeRetreino";

export default function ModeloRetreinoPage() {
  return (
    <div className="w-full bg-background">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
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
      </div>
    </div>
  );
}
