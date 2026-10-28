/**
 * Chat do modelo de contratos — página dedicada (`/modelo/chat`).
 *
 * Reutiliza o componente conversacional ChatDoModelo com painel e selector de
 * prompt visíveis, num layout de ecrã completo sem o pipeline de fine-tuning.
 */
import ChatDoModelo from "../components/modelo/ChatDoModelo";

export default function ChatModeloPage() {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <ChatDoModelo
        mostrarPainel={true}
        mostrarSeletorPrompt={true}
        mostrarExemplos={true}
        guardarHistoricoAtivo={true}
      />
    </div>
  );
}
