import { useEffect, useState } from "react";
import {
  deleteRagDocument,
  getRagDocumentHistory,
  listRagDocuments,
  reprocessRagDocument,
  updateRagDocument,
} from "../api";
import type { RagDocument, RagDocumentHistoryItem } from "../types";
import { PdfUploader } from "../components/PdfUploader";
import { RagChat } from "../components/RagChat";
import { Card, CardHeader, CardTitle, Button } from "../components/ui";
import { FileUp, BookOpen, Sparkles } from "lucide-react";

interface RagPageProps {
  onSwitchView: () => void;
}

export function RagPage({ onSwitchView }: RagPageProps) {
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);

  const refresh = async () => {
    setLoadingDocs(true);
    try {
      const docs = await listRagDocuments();
      setDocuments(docs);
    } catch (err) {
      console.error("listRagDocuments error:", err);
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleDelete = async (docId: string) => {
    await deleteRagDocument(docId);
    await refresh();
  };

  const handleUpdate = async (docId: string, title: string) => {
    await updateRagDocument(docId, { title });
    await refresh();
  };

  const handleReprocess = async (
    docId: string,
    converter: "auto" | "markitdown" | "pymupdf",
  ) => {
    await reprocessRagDocument(docId, converter);
  };

  const handleLoadHistory = async (docId: string): Promise<RagDocumentHistoryItem[]> => {
    const data = await getRagDocumentHistory(docId);
    return data.history;
  };

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <section className="mb-8 fade-in">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="h-12 w-12 rounded-2xl gradient-border flex items-center justify-center glow-teal">
                <BookOpen size={24} className="text-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-glow-teal">
                    RAG BloombergGPT
                  </h1>
                  <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 border border-teal-500/20 px-2.5 py-0.5 text-xs font-medium text-teal-400">
                    <Sparkles size={12} />
                    Premium
                  </span>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  Documentos, chat e grafo vetorial.
                </p>
              </div>
            </div>
            <Button variant="secondary" size="sm" onClick={onSwitchView}>
              Voltar ao Chat
            </Button>
          </div>
        </section>

        <div className="flex flex-col lg:flex-row gap-6 h-full">
          <div className="lg:w-[360px] xl:w-[420px] shrink-0 flex flex-col gap-6 h-full min-h-0 overflow-y-auto lg:overflow-visible">
            <div className="glass-card gradient-border rounded-2xl p-1 glow-amber">
              <PdfUploader onUpload={refresh} />
            </div>

            <div className="glass-card gradient-border rounded-2xl p-1 glow-blue">
              <Card padding="md" className="shrink-0 bg-transparent border-0 shadow-none">
                <CardHeader className="mb-3">
                  <CardTitle icon={<FileUp size={18} className="text-primary" />}>Como funciona</CardTitle>
                </CardHeader>
                <ul className="text-sm text-muted-foreground space-y-2 list-disc pl-4">
                  <li>O upload converte PDF para Markdown.</li>
                  <li>O texto é dividido em chunks e indexado vetorialmente (FAISS).</li>
                  <li>O BloombergGPT-style responde com base nos documentos.</li>
                  <li>Cada documento tem detalhes, histórico, edição, grafo e reprocessamento.</li>
                </ul>
              </Card>
            </div>
          </div>

          <div className="flex-1 min-h-0 h-full">
            <div className="glass-panel gradient-border rounded-2xl p-0 overflow-hidden glow-teal h-full">
              <RagChat
                documents={documents}
                loadingDocs={loadingDocs}
                onDeleteDocument={handleDelete}
                onUpdateDocument={handleUpdate}
                onReprocessDocument={handleReprocess}
                onLoadHistory={handleLoadHistory}
                onRefreshDocuments={refresh}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
