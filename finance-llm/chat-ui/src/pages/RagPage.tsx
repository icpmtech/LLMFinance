/**
 * RAG BloombergGPT (documentos, chat e grafo vetorial).
 *
 * A página vive **dentro de uma janela** do IQ OS (ou em modo página), pelo que
 * não usa `min-h-screen`: ocupa exatamente a altura que recebe — cabeçalho fixo
 * em cima, coluna de upload/ajuda a rolar por dentro e o chat a preencher o
 * resto. Assim o chat rola sozinho (mensagens com scroll e caixa de envio sempre
 * visível) em vez de arrastar a página toda dentro da janela.
 */
import { useEffect, useMemo, useState } from "react";
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
import { useWindowMode } from "../layout";
import { BookOpen, FileUp, Sparkles } from "lucide-react";

interface RagPageProps {
  onSwitchView: () => void;
}

export function RagPage({ onSwitchView }: RagPageProps) {
  const { windowMode } = useWindowMode();
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

  const indexed = useMemo(() => documents.filter((doc) => doc.indexed).length, [documents]);

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
    <div className="@container flex h-full min-h-0 w-full flex-col">
      {/* Cabeçalho compacto (mesmo padrão das outras aplicações do IQ OS) */}
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-teal-400/85 to-sky-500/85 text-white shadow-lg shadow-teal-500/20">
          <BookOpen size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold leading-tight">RAG BloombergGPT</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Documentos, chat e grafo vetorial ·{" "}
            {documents.length === 0
              ? "sem documentos"
              : `${documents.length} documento${documents.length === 1 ? "" : "s"} · ${indexed} indexado${indexed === 1 ? "" : "s"}`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-1 rounded-full border border-teal-500/20 bg-teal-500/10 px-2.5 py-0.5 text-[11px] font-medium text-teal-300 sm:inline-flex">
            <Sparkles size={11} />
            Premium
          </span>
          {!windowMode && (
            <Button variant="secondary" size="sm" onClick={onSwitchView}>
              Voltar ao Chat
            </Button>
          )}
        </div>
      </header>

      {/* Corpo: em janelas/campos largos upload/ajuda à esquerda e chat à direita;
          em janelas estreitas empilha e é a coluna do corpo que rola. As variantes
          `@…` medem a **largura da janela** (container query), não o ecrã. */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 @4xl:flex-row @4xl:gap-4 @4xl:overflow-hidden @4xl:p-4">
        <div className="flex max-h-[30%] w-full shrink-0 flex-col gap-3 overflow-y-auto @4xl:h-full @4xl:max-h-none @4xl:min-h-0 @4xl:w-[336px] @5xl:w-[372px]">
          <div className="glass-card gradient-border rounded-2xl p-1">
            <PdfUploader onUpload={refresh} />
          </div>

          <div className="glass-card gradient-border rounded-2xl p-1">
            <Card padding="md" className="shrink-0 border-0 bg-transparent shadow-none">
              <CardHeader className="mb-3">
                <CardTitle icon={<FileUp size={18} className="text-primary" />}>Como funciona</CardTitle>
              </CardHeader>
              <ul className="list-disc space-y-2 pl-4 text-sm text-muted-foreground">
                <li>O upload converte o PDF para Markdown.</li>
                <li>O texto é dividido em chunks e indexado vetorialmente (FAISS).</li>
                <li>O BloombergGPT-style responde com base nos documentos.</li>
                <li>Cada documento tem detalhes, histórico, edição, grafo e reprocessamento.</li>
              </ul>
            </Card>
          </div>
        </div>

        {/* O chat recebe o resto da altura da janela e rola por dentro (é a
            área com prioridade, para a caixa de envio ficar sempre à vista). */}
        <div className="flex min-h-[300px] min-w-0 flex-1 flex-col @4xl:min-h-0">
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
  );
}
