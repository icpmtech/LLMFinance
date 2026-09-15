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
    <aside className="hidden md:flex w-72 shrink-0 flex-col h-full border-r border-border bg-sidebar/50 backdrop-blur-xl">
      <div className="p-4 border-b border-border">
        <button
          onClick={onNew}
          className="neumorphic-btn w-full flex items-center justify-center gap-2 text-sm font-medium"
        >
          <Plus size={18} />
          Nova conversa
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1">
        {conversations.length === 0 ? (
          <p className="text-sm text-muted-foreground px-3 py-6 text-center">
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
                  ? "bg-primary/15 text-primary border border-primary/20"
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
    </aside>
  );
}
