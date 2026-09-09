import { useState, useRef, useEffect, type ChangeEvent } from "react";
import { Upload, FileText, CheckCircle, AlertCircle, Clock } from "lucide-react";
import { Button } from "./ui";

interface PdfUploaderProps {
  onUpload?: () => void;
  estimatedSecondsPerMB?: number;
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function PdfUploader({ onUpload, estimatedSecondsPerMB = 15 }: PdfUploaderProps) {
  const [file, setFile] = useState<File | null>(null);
  const [converter, setConverter] = useState<"auto" | "markitdown" | "pymupdf">("auto");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [estimatedTotal, setEstimatedTotal] = useState(0);
  const [result, setResult] = useState<{ message: string; title: string; pages: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef<number>(0);

  const clearTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => () => clearTimer(), []);

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
    setProgress(0);
    setElapsed(0);
    const totalEstimate = Math.max(10, file.size / (1024 * 1024) * estimatedSecondsPerMB);
    setEstimatedTotal(totalEstimate);
    startRef.current = Date.now();

    timerRef.current = setInterval(() => {
      const elapsedSeconds = (Date.now() - startRef.current) / 1000;
      setElapsed(elapsedSeconds);
      setProgress((prev) => {
        const next = Math.min(95, (elapsedSeconds / totalEstimate) * 100);
        return next > prev ? next : prev + 0.5;
      });
    }, 1000);

    try {
      const { uploadPdf } = await import("../api");
      const res = await uploadPdf(file, converter);
      setResult({ message: res.message, title: res.title, pages: res.pages });
      setProgress(100);
      onUpload?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      clearTimer();
      setUploading(false);
      setFile(null);
    }
  };

  const remaining = Math.max(0, estimatedTotal - elapsed);

  return (
    <div className="bg-card border border-border rounded-2xl shadow-sm overflow-hidden">
      <div className="p-5 border-b border-border bg-muted/30">
        <h3 className="font-semibold text-lg flex items-center gap-2">
          <Upload size={20} className="text-primary" />
          Upload de PDF
        </h3>
        <p className="text-sm text-muted-foreground mt-1">
          O PDF é convertido para Markdown, fragmentado e indexado no RAG.
        </p>
      </div>

      <div className="p-5 space-y-5">
        <label
          className={`
            flex flex-col items-center justify-center gap-3 p-8 border-2 border-dashed rounded-xl
            transition cursor-pointer
            ${file ? "border-primary/40 bg-primary/5" : "border-border hover:border-primary/40 hover:bg-accent/50"}
            ${uploading ? "opacity-60 cursor-not-allowed" : ""}
          `}
        >
          <input type="file" accept=".pdf" onChange={handleSelect} className="hidden" disabled={uploading} />
          <FileText size={36} className="text-muted-foreground" />
          <div className="text-center">
            <span className="text-sm font-medium text-foreground block">
              {file ? file.name : "Clique para selecionar um PDF"}
            </span>
            <span className="text-xs text-muted-foreground">
              {file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Apenas .pdf"}
            </span>
          </div>
        </label>

        <div className="space-y-2">
          <label htmlFor="converter" className="text-sm font-medium">
            Conversor PDF → Markdown
          </label>
          <select
            id="converter"
            value={converter}
            onChange={(e) => setConverter(e.target.value as "auto" | "markitdown" | "pymupdf")}
            disabled={uploading}
            className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
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
          <Button
            onClick={submit}
            loading={uploading}
            icon={uploading ? undefined : <Upload size={18} />}
            size="lg"
            className="w-full"
          >
            {uploading ? "A indexar..." : "Converter e indexar"}
          </Button>
        )}

        {uploading && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <Clock size={12} />
                {remaining > 0 ? `Tempo estimado restante: ${formatTime(remaining)}` : "A finalizar..."}
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-700 ease-out"
                style={{ width: `${Math.min(100, progress)}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground text-center">
              Decorrido: {formatTime(elapsed)}
            </p>
          </div>
        )}

        {result && (
          <div className="flex items-start gap-3 text-sm bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 p-4 rounded-xl">
            <CheckCircle size={18} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">{result.message}</p>
              <p className="text-emerald-300/80">
                {result.title} • {result.pages} página(s)
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-3 text-sm bg-destructive/10 border border-destructive/20 text-destructive p-4 rounded-xl">
            <AlertCircle size={18} className="shrink-0 mt-0.5" />
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
