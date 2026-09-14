import { Trash2, Plus, MessageSquare, TrendingUp, LineChart, FolderOpen, Database, Search, CandlestickChart, FileText } from "lucide-react";

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
  onSwitchSearch?: () => void;
  onSwitchTrading?: () => void;
  onSwitchContracts?: () => void;
}

export function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, onSwitchView, onSwitchTickers, onSwitchRag, onSwitchElastic, onSwitchSearch, onSwitchTrading, onSwitchContracts }: SidebarProps) {
  return (
    <aside className="fixed bottom-0 left-0 right-0 z-50 bg-sidebar border-t border-border flex flex-row items-center justify-around h-16 px-2 md:static md:w-64 md:h-full md:flex-col md:border-r md:border-t-0 md:px-0 md:py-0 shrink-0">
      <div className="flex flex-row items-center justify-around w-full h-full md:flex-col md:h-auto md:p-4 md:space-y-2 md:space-x-0 overflow-x-auto">
        {onSwitchSearch && (
          <button
            onClick={onSwitchSearch}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <Search size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Pesquisar</span>
          </button>
        )}
        <button
          onClick={onNew}
          className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-primary text-foreground md:text-primary-foreground font-medium hover:opacity-90 transition shrink-0"
        >
          <Plus size={20} className="md:size-[18px]" />
          <span className="text-[10px] md:text-sm">Nova</span>
        </button>
        {onSwitchView && (
          <button
            onClick={onSwitchView}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <TrendingUp size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Previsões</span>
          </button>
        )}
        {onSwitchTrading && (
          <button
            onClick={onSwitchTrading}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <CandlestickChart size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Trading</span>
          </button>
        )}
        {onSwitchTickers && (
          <button
            onClick={onSwitchTickers}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <LineChart size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Tickers</span>
          </button>
        )}
        {onSwitchRag && (
          <button
            onClick={onSwitchRag}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <FolderOpen size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">RAG</span>
          </button>
        )}
        {onSwitchElastic && (
          <button
            onClick={onSwitchElastic}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <Database size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Elastic</span>
          </button>
        )}
        {onSwitchContracts && (
          <button
            onClick={onSwitchContracts}
            className="flex flex-col md:flex-row items-center justify-center gap-1 md:gap-2 px-2 md:w-full md:px-4 md:py-3 rounded-xl md:bg-card md:border md:border-border text-foreground font-medium hover:bg-accent transition shrink-0"
          >
            <FileText size={20} className="md:size-[18px]" />
            <span className="text-[10px] md:text-sm">Contratos</span>
          </button>
        )}
      </div>

      <div className="hidden md:flex flex-1 overflow-y-auto px-3 py-2 space-y-1 flex-col">
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

      <div className="hidden md:block p-4 border-t border-border">
        <p className="text-xs text-muted-foreground">
          FinanceLLM Chat
        </p>
      </div>
    </aside>
  );
}
