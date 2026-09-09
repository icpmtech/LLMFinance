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
import { FileUp, BookOpen } from "lucide-react";

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
    <div className="flex flex-col h-screen w-full overflow-hidden bg-background text-foreground">
      <header className="h-16 border-b border-border flex items-center justify-between px-6 bg-card/80 shrink-0 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-primary/20 flex items-center justify-center">
            <BookOpen size={20} className="text-primary" />
          </div>
          <div>
            <h2 className="font-semibold leading-tight">RAG BloombergGPT</h2>
            <p className="text-xs text-muted-foreground">Documentos, chat e grafo vetorial</p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={onSwitchView}>
          Voltar ao Chat
        </Button>
      </header>

      <main className="flex-1 min-h-0 p-4 lg:p-6">
        <div className="flex flex-col lg:flex-row gap-4 lg:gap-6 h-full">
          <div className="lg:w-[360px] xl:w-[420px] shrink-0 flex flex-col gap-4 lg:gap-6 h-full min-h-0 overflow-y-auto lg:overflow-visible">
            <PdfUploader onUpload={refresh} />

            <Card padding="md" className="shrink-0">
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

          <div className="flex-1 min-h-0 h-full">
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
      </main>
    </div>
  );
}
