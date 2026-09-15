import { Sidebar } from "./Sidebar";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import type { Message, ModelBackend } from "../types";

interface Conversation {
  id: string;
  title: string;
}

interface ChatLayoutProps {
  conversations: Conversation[];
  activeId: string | null;
  messages: Message[];
  loading: boolean;
  streaming: boolean;
  backend: ModelBackend;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: string) => void;
  onSend: (text: string) => void;
  onBackendChange: (backend: ModelBackend) => void;
  onSwitchView?: () => void;
  onSwitchTickers?: () => void;
  onSwitchRag?: () => void;
  onSwitchElastic?: () => void;
  onSwitchSearch?: () => void;
  onSwitchTrading?: () => void;
  onSwitchContracts?: () => void;
  onSwitchContractsDashboard?: () => void;
  onSwitchContractsSearch?: () => void;
}

export function ChatLayout({
  conversations,
  activeId,
  messages,
  loading,
  streaming,
  backend,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onSend,
  onBackendChange,
  onSwitchView,
  onSwitchTickers,
  onSwitchRag,
  onSwitchElastic,
  onSwitchSearch,
  onSwitchTrading,
  onSwitchContracts,
  onSwitchContractsDashboard,
  onSwitchContractsSearch,
}: ChatLayoutProps) {
  return (
    <div className="flex flex-col md:flex-row h-screen w-full overflow-hidden bg-background text-foreground pb-16 md:pb-0">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={onSelectConversation}
        onNew={onNewConversation}
        onDelete={onDeleteConversation}
        onSwitchView={onSwitchView}
        onSwitchTickers={onSwitchTickers}
        onSwitchRag={onSwitchRag}
        onSwitchElastic={onSwitchElastic}
        onSwitchSearch={onSwitchSearch}
        onSwitchTrading={onSwitchTrading}
        onSwitchContracts={onSwitchContracts}
        onSwitchContractsDashboard={onSwitchContractsDashboard}
        onSwitchContractsSearch={onSwitchContractsSearch}
      />

      <main className="flex-1 flex flex-col min-w-0 min-h-0">
        <header className="h-14 border-b border-border flex items-center px-6 bg-card/50">
          <h2 className="font-semibold">{activeId ? conversations.find((c) => c.id === activeId)?.title || "Conversa" : "Nova conversa"}</h2>
        </header>

        <MessageList messages={messages} streaming={streaming} />
        <ChatInput
          onSend={onSend}
          loading={loading || streaming}
          backend={backend}
          onBackendChange={onBackendChange}
        />
      </main>
    </div>
  );
}
