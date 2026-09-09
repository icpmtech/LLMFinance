import { useState, useRef, useEffect, useCallback } from "react";
import {
  Send,
  Loader2,
  FileText,
  Trash2,
  MessageSquare,
  Bot,
  History,
  Edit2,
  RefreshCw,
  Check,
  X,
  Sparkles,
  Network,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import type { RagChatResponse, RagDocument, RagDocumentHistoryItem, RagSource } from "../types";
import { askRag, explainRagAnswer, streamRagAnswer } from "../api";
import { Button, Card, CardHeader, CardTitle, Badge } from "./ui";
import { DocumentGraph } from "./DocumentGraph";

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

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: RagSource[];
  explanation?: string;
  model?: string;
  elapsed?: number;
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
  const [streaming, setStreaming] = useState(false);
  const [llmMode, setLlmMode] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState<string | "">("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<RagDocument | null>(null);
  const [history, setHistory] = useState<RagDocumentHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [reprocessingId, setReprocessingId] = useState<string | null>(null);
  const [reprocessDoc, setReprocessDoc] = useState<RagDocument | null>(null);
  const [reprocessConverter, setReprocessConverter] = useState<"auto" | "markitdown" | "pymupdf">("auto");
  const [graphDoc, setGraphDoc] = useState<RagDocument | null>(null);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const selectedDocObj = documents.find((d) => d.doc_id === selectedDocId) || null;

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

  const toggleSources = (id: string) => {
    setExpandedSources((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleSend = useCallback(async () => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setStreaming(false);
    setError(null);
    const q = question.trim();
    setQuestion("");
    const userMsg: ChatMessage = { id: generateId(), role: "user", content: q };
    const loadingId = generateId();
    const loadingMsg: ChatMessage = { id: loadingId, role: "assistant", content: "A pensar..." };
    setMessages((prev) => [...prev, userMsg, loadingMsg]);

    try {
      if (llmMode) {
        await streamRagAnswer(
          { question: q, top_k: 5, temperature: 0.1, max_new_tokens: 128, doc_id: selectedDocId || undefined, stream: true },
          (token) => {
            setStreaming(true);
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last?.id !== loadingId) return prev;
              return [...prev.slice(0, -1), { ...last, content: last.content === "A pensar..." ? token : last.content + token }];
            });
          },
          (sources) => {
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last?.id !== loadingId) return prev;
              return [...prev.slice(0, -1), { ...last, sources }];
            });
          },
        );
      } else {
        const res: RagChatResponse = await askRag({
          question: q,
          top_k: 5,
          temperature: 0.1,
          max_new_tokens: 128,
          doc_id: selectedDocId || undefined,
        });
        setMessages((prev) =>
          prev.map((m) => (m.id === loadingId ? { id: generateId(), role: "assistant", content: res.answer, sources: res.sources, model: res.model_used, elapsed: res.elapsed_seconds } : m)),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
      setMessages((prev) => prev.map((m) => (m.id === loadingId ? { id: generateId(), role: "assistant", content: "❌ Não foi possível responder." } : m)));
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  }, [question, loading, llmMode, selectedDocId]);

  const handleExplain = async (msgId: string) => {
    const msg = messages.find((m) => m.id === msgId);
    if (!msg) return;
    try {
      const res = await explainRagAnswer({ question: msg.content, top_k: 5 });
      setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, explanation: res.analysis } : m)));
    } catch (e) {
      console.error(e);
    }
  };

  const openDetails = (doc: RagDocument) => setSelectedDoc(doc);
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

  const closeReprocess = () => setReprocessDoc(null);

  const confirmReprocess = async () => {
    if (!reprocessDoc) return;
    setReprocessingId(reprocessDoc.doc_id);
    setReprocessDoc(null);
    try {
      await onReprocessDocument(reprocessDoc.doc_id, reprocessConverter);
      await onRefreshDocuments();
    } finally {
      setReprocessingId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 gap-4">
      {/* Documentos */}
      <aside className="w-72 xl:w-80 bg-card border border-border rounded-2xl flex flex-col h-full min-h-0 overflow-hidden shadow-sm">
        <CardHeader className="p-4 border-b border-border shrink-0">
          <CardTitle icon={<FileText size={18} className="text-primary" />}>Documentos</CardTitle>
          <Button variant="ghost" size="sm" loading={loadingDocs} onClick={onRefreshDocuments}>
            {loadingDocs ? "A carregar..." : "Atualizar"}
          </Button>
        </CardHeader>

        <div className="p-3 border-b border-border">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Selecionar contexto (opcional)</label>
          <select
            value={selectedDocId}
            onChange={(e) => setSelectedDocId(e.target.value)}
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
          >
            <option value="">Todos os documentos</option>
            {documents.map((doc) => (
              <option key={doc.doc_id} value={doc.doc_id}>
                {doc.title}
              </option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhum documento indexado. Usa o upload para adicionar PDFs.
            </p>
          ) : (
            documents.map((doc) => (
              <Card
                key={doc.doc_id}
                padding="sm"
                className={`group transition hover:border-primary/30 ${selectedDocId === doc.doc_id ? "border-primary/60 bg-primary/5" : "bg-muted/40"}`}
              >
                <div className="flex items-start gap-2">
                  <Button variant="ghost" size="sm" className="p-1 h-auto" onClick={() => openDetails(doc)} title="Ver detalhes">
                    <History size={16} />
                  </Button>
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setSelectedDocId(doc.doc_id)}>
                    {editingId === doc.doc_id ? (
                      <input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") confirmEdit(doc.doc_id);
                          if (e.key === "Escape") cancelEdit();
                        }}
                        className="w-full text-sm bg-background border border-border rounded-lg px-2 py-1"
                        autoFocus
                      />
                    ) : (
                      <p className="text-sm font-medium truncate">{doc.title}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {doc.pages} pág. • {doc.converter || "auto"} {doc.indexed && <Badge variant="success" className="ml-1">indexado</Badge>}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-end gap-1 mt-2 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition">
                  {editingId === doc.doc_id ? (
                    <>
                      <Button variant="ghost" size="sm" className="p-1 h-auto" onClick={() => confirmEdit(doc.doc_id)} title="Guardar">
                        <Check size={14} className="text-emerald-400" />
                      </Button>
                      <Button variant="ghost" size="sm" className="p-1 h-auto" onClick={cancelEdit} title="Cancelar">
                        <X size={14} className="text-destructive" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="ghost" size="sm" className="p-1 h-auto" onClick={() => startEdit(doc)} title="Editar título">
                        <Edit2 size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="p-1 h-auto"
                        onClick={() => setGraphDoc(doc)}
                        title="Ver grafo"
                      >
                        <Network size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="p-1 h-auto"
                        onClick={() => openReprocess(doc)}
                        loading={reprocessingId === doc.doc_id}
                        title="Reprocessar"
                      >
                        {reprocessingId !== doc.doc_id && <RefreshCw size={14} />}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="p-1 h-auto"
                        onClick={() => onDeleteDocument(doc.doc_id)}
                        title="Apagar"
                      >
                        <Trash2 size={14} className="text-destructive" />
                      </Button>
                    </>
                  )}
                </div>
              </Card>
            ))
          )}
        </div>
      </aside>

      {/* Chat */}
      <div className="flex-1 min-h-0 flex flex-col bg-card border border-border rounded-2xl h-full overflow-hidden shadow-sm">
        <div className="p-4 border-b border-border shrink-0 flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold flex items-center gap-2">
              <Bot size={18} className="text-primary" />
              Chat RAG BloombergGPT
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Respostas baseadas apenas nos documentos carregados.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {selectedDocObj && <Badge variant="info">{selectedDocObj.title}</Badge>}
            <Button
              variant={llmMode ? "primary" : "outline"}
              size="sm"
              icon={<Sparkles size={14} />}
              onClick={() => setLlmMode((v) => !v)}
              title={llmMode ? "Desativar modo LLM streaming" : "Ativar modo LLM streaming"}
            >
              LLM
            </Button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] p-4 rounded-2xl text-sm ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground rounded-br-md"
                    : "bg-muted text-foreground rounded-bl-md border border-border"
                }`}
              >
                <div className="flex items-center gap-2 mb-1 text-xs opacity-80">
                  {msg.role === "assistant" ? <Bot size={12} /> : <MessageSquare size={12} />}
                  <span className="capitalize">{msg.role === "user" ? "Tu" : "BloombergGPT"}</span>
                  {msg.model && <span className="ml-auto">{msg.model}</span>}
                </div>
                <div className="whitespace-pre-wrap">{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-border/50">
                    <button
                      onClick={() => toggleSources(msg.id)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-1"
                    >
                      {expandedSources[msg.id] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      Fontes ({msg.sources.length})
                    </button>
                    {expandedSources[msg.id] && (
                      <div className="space-y-1">
                        {msg.sources.map((s, idx) => (
                          <p key={idx} className="text-xs text-muted-foreground truncate" title={s.text}>
                            {idx + 1}. {s.doc_title} {s.page ? `(p. ${s.page})` : ""}
                            {s.score != null && <span className="ml-1 text-sky-400">({s.score.toFixed(2)})</span>}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {msg.explanation && (
                  <div className="mt-3 pt-3 border-t border-border/50 text-xs text-muted-foreground">
                    <strong>Porque esta resposta?</strong> <br />{msg.explanation}
                  </div>
                )}
                {msg.role === "assistant" && !msg.explanation && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2 h-auto py-1 px-2 text-xs"
                    onClick={() => handleExplain(msg.id)}
                    icon={<Sparkles size={12} />}
                  >
                    Explicar resposta
                  </Button>
                )}
              </div>
            </div>
          ))}
          {loading && !streaming && (
            <div className="flex gap-3 justify-start">
              <div className="bg-muted p-4 rounded-2xl rounded-bl-md flex items-center gap-2 text-sm text-muted-foreground border border-border">
                <Loader2 size={16} className="animate-spin" />
                A pensar...
              </div>
            </div>
          )}
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 p-3 rounded-xl">
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
              placeholder={llmMode ? "Pergunta em modo LLM streaming..." : "Pergunta sobre os documentos carregados..."}
              className="flex-1 bg-muted rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 border border-transparent focus:border-primary transition"
            />
            <Button
              onClick={handleSend}
              disabled={!question.trim() || loading}
              loading={loading}
              icon={<Send size={18} />}
              size="lg"
            >
              Enviar
            </Button>
          </div>
        </div>
      </div>

      {/* Detalhes / Histórico */}
      {selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md max-h-[80vh] flex flex-col" padding="none">
            <CardHeader className="p-4 border-b border-border shrink-0">
              <CardTitle icon={<History size={18} className="text-primary" />}>Detalhes do documento</CardTitle>
              <Button variant="ghost" size="sm" className="p-1 h-auto" onClick={closeDetails}>
                <X size={18} />
              </Button>
            </CardHeader>

            <div className="p-5 overflow-y-auto space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Título</p>
                  <p className="font-medium">{selectedDoc.title}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Ficheiro</p>
                  <p className="font-medium truncate">{selectedDoc.filename}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Páginas</p>
                  <p className="font-medium">{selectedDoc.pages}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Tamanho</p>
                  <p className="font-medium">{selectedDoc.size_bytes ? `${(selectedDoc.size_bytes / 1024).toFixed(1)} KB` : "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Conversor</p>
                  <p className="font-medium capitalize">{selectedDoc.converter || "auto"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Estado</p>
                  <p className="font-medium">{selectedDoc.indexed ? <Badge variant="success">indexado</Badge> : <Badge>pendente</Badge>}</p>
                </div>
                <div className="space-y-1 col-span-2">
                  <p className="text-xs text-muted-foreground">Criado / Atualizado</p>
                  <p className="font-medium">{formatDate(selectedDoc.created_at)} • {formatDate(selectedDoc.updated_at)}</p>
                </div>
              </div>

              <hr className="border-border" />

              <h5 className="text-sm font-medium flex items-center gap-2">
                <History size={14} className="text-primary" /> Histórico
              </h5>
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
              <Button variant="secondary" size="sm" onClick={closeDetails}>Fechar</Button>
            </div>
          </Card>
        </div>
      )}

      {/* Reprocessar modal */}
      {reprocessDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-sm" padding="none">
            <CardHeader className="p-4 border-b border-border">
              <CardTitle icon={<RefreshCw size={18} className="text-primary" />}>Reprocessar documento</CardTitle>
            </CardHeader>
            <div className="p-5 space-y-3">
              <p className="text-sm text-muted-foreground">
                Escolhe o conversor para regenerar o Markdown, chunks e embeddings de
                <span className="text-foreground font-medium"> {reprocessDoc.title}</span>.
              </p>
              <label className="text-sm font-medium">Conversor PDF → Markdown</label>
              <select
                value={reprocessConverter}
                onChange={(e) => setReprocessConverter(e.target.value as "auto" | "markitdown" | "pymupdf")}
                className="w-full text-sm bg-background border border-border rounded-xl px-3 py-2.5"
              >
                <option value="auto">Auto (markitdown → PyMuPDF fallback)</option>
                <option value="markitdown">Microsoft markitdown</option>
                <option value="pymupdf">PyMuPDF</option>
              </select>
            </div>
            <div className="p-4 border-t border-border flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={closeReprocess}>Cancelar</Button>
              <Button
                size="sm"
                onClick={confirmReprocess}
                loading={reprocessingId === reprocessDoc.doc_id}
              >
                Reprocessar
              </Button>
            </div>
          </Card>
        </div>
      )}

      {graphDoc && <DocumentGraph doc={graphDoc} onClose={() => setGraphDoc(null)} />}
    </div>
  );
}
