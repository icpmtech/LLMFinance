import { useState, useRef, useEffect } from "react";
import { Send, Loader2, FileText, Trash2, MessageSquare, Bot } from "lucide-react";
import type { RagChatResponse, RagDocument, RagSource } from "../types";

interface RagChatProps {
  documents: RagDocument[];
  loadingDocs: boolean;
  onDeleteDocument: (docId: string) => Promise<void>;
  onRefreshDocuments: () => Promise<void>;
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function RagChat({
  documents,
  loadingDocs,
  onDeleteDocument,
  onRefreshDocuments,
}: RagChatProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<{ id: string; role: "user" | "assistant"; content: string; sources?: RagSource[] }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async () => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setError(null);
    const q = question.trim();
    setQuestion("");
    const userMsg = { id: generateId(), role: "user" as const, content: q };
    const loadingMsg = { id: generateId(), role: "assistant" as const, content: "A pensar..." };
    setMessages((prev) => [...prev, userMsg, loadingMsg]);

    try {
      const { askRag } = await import("../api");
      const res: RagChatResponse = await askRag({ question: q, top_k: 5, temperature: 0.1, max_new_tokens: 64 });
      setMessages((prev) => prev.map((m) => (m.id === loadingMsg.id ? { id: generateId(), role: "assistant", content: res.answer, sources: res.sources } : m)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
      setMessages((prev) => prev.map((m) => (m.id === loadingMsg.id ? { id: generateId(), role: "assistant", content: "❌ Não foi possível responder." } : m)));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 gap-4">
      {/* Documentos */}
      <aside className="w-72 xl:w-80 bg-card border border-border rounded-2xl flex flex-col h-full min-h-0 overflow-hidden">
        <div className="p-4 border-b border-border flex items-center justify-between shrink-0">
          <h3 className="font-semibold flex items-center gap-2">
            <FileText size={18} />
            Documentos
          </h3>
          <button
            onClick={onRefreshDocuments}
            disabled={loadingDocs}
            className="text-xs text-muted-foreground hover:text-foreground transition"
          >
            {loadingDocs ? "A carregar..." : "Atualizar"}
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhum documento indexado. Usa o upload para adicionar PDFs.
            </p>
          ) : (
            documents.map((doc) => (
              <div
                key={doc.doc_id}
                className="group flex items-start gap-2 p-3 rounded-xl bg-muted/50 hover:bg-muted transition"
              >
                <FileText size={16} className="shrink-0 mt-0.5 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{doc.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {doc.pages} pág. {doc.indexed ? "• indexado" : ""}
                  </p>
                </div>
                <button
                  onClick={() => onDeleteDocument(doc.doc_id)}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition"
                  title="Apagar"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Chat */}
      <div className="rag-chat-container flex-1 min-h-0 flex flex-col bg-card border border-border rounded-2xl h-full overflow-hidden">
        <div className="p-4 border-b border-border shrink-0">
          <h3 className="font-semibold flex items-center gap-2">
            <Bot size={18} />
            Chat RAG BloombergGPT
          </h3>
          <p className="text-xs text-muted-foreground">
            Respostas baseadas apenas nos documentos carregados.
          </p>
        </div>

        <div className="rag-messages flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] p-4 rounded-2xl text-sm ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground rounded-br-md"
                    : "bg-muted text-foreground rounded-bl-md"
                }`}
              >
                {msg.role === "assistant" && <Bot size={14} className="inline mr-2 mb-0.5 text-muted-foreground" />}
                {msg.role === "user" && <MessageSquare size={14} className="inline mr-2 mb-0.5" />}
                <div className="whitespace-pre-wrap">{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-border/50 space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">Fontes:</p>
                    {msg.sources.map((s, idx) => (
                      <p key={idx} className="text-xs text-muted-foreground truncate" title={s.text}>
                        {idx + 1}. {s.doc_title} {s.page ? `(p. ${s.page})` : ""}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex gap-3 justify-start">
              <div className="bg-muted p-4 rounded-2xl rounded-bl-md flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" />
                A pensar...
              </div>
            </div>
          )}
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="p-4 border-t border-border shrink-0">
          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              disabled={loading}
              placeholder="Pergunta sobre os documentos carregados..."
              className="flex-1 bg-muted rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 border border-transparent focus:border-primary transition"
            />
            <button
              onClick={handleSend}
              disabled={!question.trim() || loading}
              className="px-4 py-3 rounded-xl bg-primary text-primary-foreground disabled:opacity-40 hover:opacity-90 transition"
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
