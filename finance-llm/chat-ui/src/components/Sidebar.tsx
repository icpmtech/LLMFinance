import { Trash2, Plus, MessageSquare, TrendingUp, LineChart, FolderOpen, Database } from "lucide-react";

interface Conversation {
  id: string;
  title: string;
}

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onSwitchView?: () => void;
  onSwitchTickers?: () => void;
  onSwitchRag?: () => void;
  onSwitchElastic?: () => void;
}

export function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, onSwitchView, onSwitchTickers, onSwitchRag, onSwitchElastic }: SidebarProps) {
  return (
    <aside className="w-64 bg-sidebar border-r border-border flex flex-col h-full shrink-0">
      <div className="p-4 space-y-2">
        <button
          onClick={onNew}
          className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          <Plus size={18} />
          Nova conversa
        </button>
        {onSwitchView && (
          <button
            onClick={onSwitchView}
            className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-card border border-border text-foreground font-medium hover:bg-accent transition"
          >
            <TrendingUp size={18} />
            Previsões
          </button>
        )}
        {onSwitchTickers && (
          <button
            onClick={onSwitchTickers}
            className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-card border border-border text-foreground font-medium hover:bg-accent transition"
          >
            <LineChart size={18} />
            Tickers
          </button>
        )}
        {onSwitchRag && (
          <button
            onClick={onSwitchRag}
            className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-card border border-border text-foreground font-medium hover:bg-accent transition"
          >
            <FolderOpen size={18} />
            RAG Docs
          </button>
        )}
        {onSwitchElastic && (
          <button
            onClick={onSwitchElastic}
            className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-card border border-border text-foreground font-medium hover:bg-accent transition"
          >
            <Database size={18} />
            Elasticsearch
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {conversations.length === 0 ? (
          <p className="text-sm text-muted-foreground px-3 py-4 text-center">
            Sem conversas anteriores.
          </p>
        ) : (
          conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => onSelect(conv.id)}
              className={[
                "group flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-left transition",
                activeId === conv.id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/50",
              ].join(" ")}
            >
              <MessageSquare size={16} className="shrink-0" />
              <span className="flex-1 truncate">{conv.title}</span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(conv.id);
                }}
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition"
                title="Apagar"
              >
                <Trash2 size={14} />
              </span>
            </button>
          ))
        )}
      </div>

      <div className="p-4 border-t border-border">
        <p className="text-xs text-muted-foreground">
          FinanceLLM Chat
        </p>
      </div>
    </aside>
  );
}
