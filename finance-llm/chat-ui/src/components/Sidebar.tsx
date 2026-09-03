import { Trash2, Plus, MessageSquare } from "lucide-react";

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
}

export function Sidebar({ conversations, activeId, onSelect, onNew, onDelete }: SidebarProps) {
  return (
    <aside className="w-64 bg-sidebar border-r border-border flex flex-col h-full shrink-0">
      <div className="p-4">
        <button
          onClick={onNew}
          className="flex items-center justify-center gap-2 w-full px-4 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          <Plus size={18} />
          Nova conversa
        </button>
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
