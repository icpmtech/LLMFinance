import { useState, useRef, useEffect } from "react";
import { Send, Loader2, FileText, Trash2, MessageSquare, Bot, History, Edit2, RefreshCw, Check, X } from "lucide-react";
import type { RagChatResponse, RagDocument, RagDocumentHistoryItem, RagSource } from "../types";

interface RagChatProps {
  documents: RagDocument[];
  loadingDocs: boolean;
  onDeleteDocument: (docId: string) => Promise<void>;
  onUpdateDocument: (docId: string, title: string) => Promise<void>;
  onReprocessDocument: (docId: string, converter: "auto" | "markitdown" | "pymupdf") => Promise<void>;
  onLoadHistory: (docId: string) => Promise<RagDocumentHistoryItem[]>;
  onRefreshDocuments: () => Promise<void>;
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function formatDate(ts?: number) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("pt-PT");
}

export function RagChat({
  documents,
  loadingDocs,
  onDeleteDocument,
  onUpdateDocument,
  onReprocessDocument,
  onLoadHistory,
  onRefreshDocuments,
}: RagChatProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<{ id: string; role: "user" | "assistant"; content: string; sources?: RagSource[] }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<RagDocument | null>(null);
  const [history, setHistory] = useState<RagDocumentHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [reprocessingId, setReprocessingId] = useState<string | null>(null);
  const [reprocessDoc, setReprocessDoc] = useState<RagDocument | null>(null);
  const [reprocessConverter, setReprocessConverter] = useState<"auto" | "markitdown" | "pymupdf">("auto");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (!selectedDoc) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    onLoadHistory(selectedDoc.doc_id)
      .then(setHistory)
      .catch((e) => console.error(e))
      .finally(() => setHistoryLoading(false));
  }, [selectedDoc, onLoadHistory]);

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

  const openDetails = (doc: RagDocument) => {
    setSelectedDoc(doc);
  };

  const closeDetails = () => {
    setSelectedDoc(null);
    setHistory([]);
  };

  const startEdit = (doc: RagDocument) => {
    setEditingId(doc.doc_id);
    setEditTitle(doc.title);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditTitle("");
  };

  const confirmEdit = async (docId: string) => {
    if (!editTitle.trim()) return;
    await onUpdateDocument(docId, editTitle.trim());
    setEditingId(null);
  };

  const openReprocess = (doc: RagDocument) => {
    setReprocessDoc(doc);
    setReprocessConverter(doc.converter || "auto");
  };

  const closeReprocess = () => {
    setReprocessDoc(null);
  };

  const confirmReprocess = async () => {
    if (!reprocessDoc) return;
    setReprocessingId(reprocessDoc.doc_id);
    setReprocessDoc(null);
    try {
      await onReprocessDocument(reprocessDoc.doc_id, reprocessConverter);
    } finally {
      setReprocessingId(null);
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
                className="group flex flex-col gap-2 p-3 rounded-xl bg-muted/50 hover:bg-muted transition"
              >
                <div className="flex items-start gap-2">
                  <button onClick={() => openDetails(doc)} className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground" title="Ver detalhes">
                    <History size={16} />
                  </button>
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => openDetails(doc)}>
                    {editingId === doc.doc_id ? (
                      <input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") confirmEdit(doc.doc_id);
                          if (e.key === "Escape") cancelEdit();
                        }}
                        className="w-full text-sm bg-background border border-border rounded px-2 py-1"
                        autoFocus
                      />
                    ) : (
                      <p className="text-sm font-medium truncate">{doc.title}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {doc.pages} pág. • {doc.converter || "auto"} {doc.indexed ? "• indexado" : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-end gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition">
                  {editingId === doc.doc_id ? (
                    <>
                      <button onClick={() => confirmEdit(doc.doc_id)} className="p-1 hover:text-green-600" title="Guardar">
                        <Check size={14} />
                      </button>
                      <button onClick={cancelEdit} className="p-1 hover:text-destructive" title="Cancelar">
                        <X size={14} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => startEdit(doc)} className="p-1 hover:text-primary" title="Editar título">
                        <Edit2 size={14} />
                      </button>
                      <button
                        onClick={() => openReprocess(doc)}
                        disabled={reprocessingId === doc.doc_id}
                        className="p-1 hover:text-primary disabled:opacity-40"
                        title="Reprocessar"
                      >
                        {reprocessingId === doc.doc_id ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                      </button>
                      <button
                        onClick={() => onDeleteDocument(doc.doc_id)}
                        className="p-1 hover:text-destructive"
                        title="Apagar"
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </div>
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

      {/* Detalhes / Histórico */}
      {selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-card border border-border rounded-2xl w-full max-w-md max-h-[80vh] flex flex-col shadow-lg">
            <div className="p-4 border-b border-border flex items-center justify-between shrink-0">
              <h4 className="font-semibold flex items-center gap-2">
                <History size={18} />
                Histórico do documento
              </h4>
              <button onClick={closeDetails} className="p-1 hover:text-destructive">
                <X size={18} />
              </button>
            </div>
            <div className="p-4 overflow-y-auto space-y-3">
              <div className="text-sm space-y-1">
                <p><span className="font-medium">Título:</span> {selectedDoc.title}</p>
                <p><span className="font-medium">Ficheiro:</span> {selectedDoc.filename}</p>
                <p><span className="font-medium">Páginas:</span> {selectedDoc.pages}</p>
                <p><span className="font-medium">Tamanho:</span> {selectedDoc.size_bytes ? `${(selectedDoc.size_bytes / 1024).toFixed(1)} KB` : "—"}</p>
                <p><span className="font-medium">Conversor:</span> {selectedDoc.converter || "auto"}</p>
                <p><span className="font-medium">Criado:</span> {formatDate(selectedDoc.created_at)}</p>
                <p><span className="font-medium">Atualizado:</span> {formatDate(selectedDoc.updated_at)}</p>
              </div>
              <hr className="border-border" />
              <h5 className="text-sm font-medium">Ações</h5>
              {historyLoading ? (
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> A carregar histórico...
                </p>
              ) : history.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sem histórico registado.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {history.map((h, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="font-medium capitalize shrink-0">{h.action}</span>
                      <span className="text-muted-foreground">{h.detail}</span>
                      <span className="text-xs text-muted-foreground ml-auto">{formatDate(h.timestamp)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="p-4 border-t border-border flex justify-end shrink-0">
              <button onClick={closeDetails} className="px-4 py-2 rounded-lg bg-muted hover:bg-muted/80 text-sm">Fechar</button>
            </div>
          </div>
        </div>
      )}

      {/* Reprocessar modal */}
      {reprocessDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-card border border-border rounded-2xl w-full max-w-sm flex flex-col shadow-lg">
            <div className="p-4 border-b border-border">
              <h4 className="font-semibold flex items-center gap-2">
                <RefreshCw size={18} />
                Reprocessar documento
              </h4>
            </div>
            <div className="p-4 space-y-3">
              <p className="text-sm">
                Escolhe o conversor para regenerar o Markdown, chunks e embeddings de
                <span className="font-medium"> {reprocessDoc.title}</span>.
              </p>
              <label className="text-sm font-medium">Conversor PDF → Markdown</label>
              <select
                value={reprocessConverter}
                onChange={(e) => setReprocessConverter(e.target.value as "auto" | "markitdown" | "pymupdf")}
                className="w-full text-sm bg-background border border-border rounded-lg px-3 py-2"
              >
                <option value="auto">Auto (markitdown → PyMuPDF fallback)</option>
                <option value="markitdown">Microsoft markitdown</option>
                <option value="pymupdf">PyMuPDF</option>
              </select>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <button onClick={closeReprocess} className="px-4 py-2 rounded-lg bg-muted hover:bg-muted/80 text-sm">Cancelar</button>
              <button
                onClick={confirmReprocess}
                disabled={reprocessingId === reprocessDoc.doc_id}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 text-sm"
              >
                {reprocessingId === reprocessDoc.doc_id ? (
                  <span className="flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" /> A processar...
                  </span>
                ) : (
                  "Reprocessar"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
