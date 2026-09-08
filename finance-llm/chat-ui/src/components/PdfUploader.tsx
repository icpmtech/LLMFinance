import { useState, type ChangeEvent } from "react";
import { Upload, Loader2, FileText, CheckCircle, AlertCircle } from "lucide-react";

interface PdfUploaderProps {
  onUpload?: () => void;
}

export function PdfUploader({ onUpload }: PdfUploaderProps) {
  const [file, setFile] = useState<File | null>(null);
  const [converter, setConverter] = useState<"auto" | "markitdown" | "pymupdf">("auto");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ message: string; title: string; pages: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected && selected.name.toLowerCase().endsWith(".pdf")) {
      setFile(selected);
      setError(null);
      setResult(null);
    } else if (selected) {
      setError("Apenas ficheiros PDF são permitidos.");
    }
  };

  const submit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const { uploadPdf } = await import("../api");
      const res = await uploadPdf(file, converter);
      setResult({ message: res.message, title: res.title, pages: res.pages });
      onUpload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      setUploading(false);
      setFile(null);
    }
  };

  return (
    <div className="p-6 bg-card border border-border rounded-2xl space-y-4">
      <h3 className="font-semibold text-lg flex items-center gap-2">
        <Upload size={20} />
        Upload de PDF
      </h3>
      <p className="text-sm text-muted-foreground">
        O PDF é convertido automaticamente para Markdown, fragmentado e indexado no RAG.
      </p>

      <label className="flex flex-col items-center justify-center gap-2 p-6 border-2 border-dashed border-border rounded-xl hover:bg-accent/50 transition cursor-pointer">
        <input type="file" accept=".pdf" onChange={handleSelect} className="hidden" disabled={uploading} />
        <FileText size={32} className="text-muted-foreground" />
        <span className="text-sm text-muted-foreground">
          {file ? file.name : "Clique para selecionar um PDF"}
        </span>
      </label>

      <div className="flex flex-col gap-2">
        <label htmlFor="converter" className="text-sm font-medium">Conversor PDF → Markdown</label>
        <select
          id="converter"
          value={converter}
          onChange={(e) => setConverter(e.target.value as "auto" | "markitdown" | "pymupdf")}
          disabled={uploading}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="auto">Auto (markitdown → PyMuPDF fallback)</option>
          <option value="markitdown">Microsoft markitdown</option>
          <option value="pymupdf">PyMuPDF</option>
        </select>
        <p className="text-xs text-muted-foreground">
          O <strong>markitdown</strong> é a API da Microsoft para converter PDFs em Markdown limpo.
        </p>
      </div>

      {file && (
        <button
          onClick={submit}
          disabled={uploading}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition disabled:opacity-60"
        >
          {uploading ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
          {uploading ? "A indexar..." : "Converter e indexar"}
        </button>
      )}

      {result && (
        <div className="flex items-start gap-2 text-sm text-green-600 bg-green-50 dark:bg-green-950/30 p-3 rounded-lg">
          <CheckCircle size={18} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">{result.message}</p>
            <p className="text-muted-foreground">
              {result.title} • {result.pages} página(s)
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
          <AlertCircle size={18} className="shrink-0 mt-0.5" />
          {error}
        </div>
      )}
    </div>
  );
}
