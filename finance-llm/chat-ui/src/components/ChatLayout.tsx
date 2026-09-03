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
}: ChatLayoutProps) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={onSelectConversation}
        onNew={onNewConversation}
        onDelete={onDeleteConversation}
      />

      <main className="flex-1 flex flex-col min-w-0">
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
