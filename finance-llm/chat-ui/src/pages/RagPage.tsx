import { useEffect, useState } from "react";
import { deleteRagDocument, listRagDocuments } from "../api";
import type { RagDocument } from "../types";
import { PdfUploader } from "../components/PdfUploader";
import { RagChat } from "../components/RagChat";

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

  return (
    <div className="flex flex-col h-screen w-full overflow-hidden bg-background text-foreground">
      <header className="h-14 border-b border-border flex items-center justify-between px-6 bg-card/50 shrink-0">
        <h2 className="font-semibold">RAG BloombergGPT — Documentos & Chat</h2>
        <button
          onClick={onSwitchView}
          className="text-sm px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition"
        >
          Voltar ao Chat
        </button>
      </header>

      <main className="flex-1 min-h-0 p-4">
        <div className="flex flex-col lg:flex-row gap-4 h-full">
          <div className="lg:w-[360px] xl:w-[400px] shrink-0 flex flex-col gap-4 h-full min-h-0 overflow-y-auto lg:overflow-visible">
            <PdfUploader onUpload={refresh} />
            <div className="bg-card border border-border rounded-2xl p-4 shrink-0">
              <h4 className="font-medium text-sm mb-2">Como funciona</h4>
              <ul className="text-xs text-muted-foreground space-y-1 list-disc pl-4">
                <li>Upload converte PDF para Markdown.</li>
                <li>O texto é dividido em chunks e indexado vetorialmente (FAISS).</li>
                <li>O BloombergGPT-style responde apenas com base nos documentos.</li>
              </ul>
            </div>
          </div>

          <div className="flex-1 min-h-0 h-full">
            <RagChat
              documents={documents}
              loadingDocs={loadingDocs}
              onDeleteDocument={handleDelete}
              onRefreshDocuments={refresh}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
