import { useState, useCallback } from "react";
import { Upload, FileJson, FileSpreadsheet, FileArchive, X, Check, AlertTriangle, Database } from "lucide-react";
import { Button } from "../components/ui/Button";
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { previewImportFile, ingestImport } from "../api";
import type {
  ImportFileType,
  ImportDataType,
  ImportPreviewResponse,
  ImportIngestResponse,
} from "../types";

interface ImportPageProps {
  onSwitchView?: () => void;
}

type ImportStage = "idle" | "previewing" | "preview" | "ingesting" | "done" | "error";

const ACCEPTED_EXTENSIONS: Record<ImportFileType, string> = {
  zip: ".zip,application/zip,application/x-zip-compressed",
  xlsx: ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel",
  json: ".json,application/json",
};

const ACCEPTED = Object.values(ACCEPTED_EXTENSIONS).join(",");

function detectFileType(file: File): ImportFileType {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "zip";
  if (name.endsWith(".xlsx") || name.endsWith(".xls")) return "xlsx";
  return "json";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function translateDataType(type: ImportDataType): string {
  if (type === "contracts") return "Contratos públicos";
  if (type === "entities") return "Entidades";
  return "Deteção automática";
}

function translateFileType(type: ImportFileType): string {
  if (type === "zip") return "ZIP";
  if (type === "xlsx") return "Excel";
  return "JSON";
}

export function ImportPage({ onSwitchView }: ImportPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dataType, setDataType] = useState<ImportDataType>("auto");
  const [stage, setStage] = useState<ImportStage>("idle");
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [result, setResult] = useState<ImportIngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linkEntities, setLinkEntities] = useState(true);
  const [hardReprocess, setHardReprocess] = useState(false);
  const [maxRecords, setMaxRecords] = useState<number | "">("");

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const dropped = e.dataTransfer.files[0];
      if (dropped) {
        setFile(dropped);
        setPreview(null);
        setResult(null);
        setError(null);
        setStage("idle");
      }
    },
    []
  );

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setPreview(null);
      setResult(null);
      setError(null);
      setStage("idle");
    }
  }, []);

  const clearFile = useCallback(() => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setStage("idle");
  }, []);

  const handlePreview = useCallback(async () => {
    if (!file) return;
    setStage("previewing");
    setError(null);
    try {
      const res = await previewImportFile(file, dataType);
      setPreview(res);
      setStage("preview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao pré-visualizar ficheiro");
      setStage("error");
    }
  }, [file, dataType]);

  const handleIngest = useCallback(async () => {
    if (!preview) return;
    setStage("ingesting");
    setError(null);
    try {
      const request = {
        data_type: preview.data_type,
        file_type: preview.file_type,
        filename: preview.filename,
        rows: preview.rows,
        options: {
          link_entities: linkEntities,
          max_records: maxRecords ? Number(maxRecords) : undefined,
          skip_validation: false,
          hard_reprocess: hardReprocess,
        },
      };
      const res = await ingestImport(request);
      setResult(res);
      setStage(res.success ? "done" : "error");
      if (!res.success) {
        setError(res.error || "Importação concluída com erros");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao importar");
      setStage("error");
    }
  }, [preview, linkEntities, maxRecords, hardReprocess]);

  return (
    <div className="min-h-screen bg-background p-4 md:p-6 lg:p-8">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex items-center gap-4">
          {onSwitchView && (
            <Button variant="ghost" size="sm" icon={<Database size={16} />} onClick={onSwitchView}>
              Voltar
            </Button>
          )}
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Importar dados</h1>
            <p className="text-sm text-muted-foreground">
              Carrega ficheiros ZIP, Excel ou JSON com entidades ou contratos públicos.
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Ficheiro</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {!file ? (
              <div
                onDrop={handleDrop}
                onDragOver={(e) => e.preventDefault()}
                className="border-2 border-dashed border-border rounded-2xl p-8 text-center hover:border-primary/60 hover:bg-accent/50 transition-colors cursor-pointer"
              >
                <input
                  type="file"
                  accept={ACCEPTED}
                  onChange={handleFileInput}
                  className="hidden"
                  id="import-file-input"
                />
                <label htmlFor="import-file-input" className="cursor-pointer block">
                  <div className="mx-auto w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                    <Upload className="text-primary" size={28} />
                  </div>
                  <p className="text-sm font-medium text-foreground">
                    Arrasta ficheiros para aqui ou clica para selecionar
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    ZIP, Excel (.xlsx) ou JSON (.json)
                  </p>
                </label>
              </div>
            ) : (
              <div className="flex items-center justify-between p-4 border border-border rounded-xl bg-card">
                <div className="flex items-center gap-3">
                  {detectFileType(file) === "zip" && <FileArchive className="text-primary" size={24} />}
                  {detectFileType(file) === "xlsx" && <FileSpreadsheet className="text-emerald-500" size={24} />}
                  {detectFileType(file) === "json" && <FileJson className="text-amber-500" size={24} />}
                  <div>
                    <p className="text-sm font-medium text-foreground">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
                  </div>
                </div>
                <button
                  onClick={clearFile}
                  className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                  aria-label="Remover ficheiro"
                >
                  <X size={18} />
                </button>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Tipo de dados</label>
                <select
                  value={dataType}
                  onChange={(e) => setDataType(e.target.value as ImportDataType)}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value="auto">Deteção automática</option>
                  <option value="entities">Entidades</option>
                  <option value="contracts">Contratos</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Máximo de registos</label>
                <input
                  type="number"
                  min={1}
                  placeholder="Todos"
                  value={maxRecords}
                  onChange={(e) => setMaxRecords(e.target.value === "" ? "" : Number(e.target.value))}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </div>
              <div className="flex items-end">
                <label className="inline-flex items-center gap-2 text-sm text-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={linkEntities}
                    onChange={(e) => setLinkEntities(e.target.checked)}
                    className="rounded border-border text-primary focus:ring-primary/40"
                  />
                  Ligar entidades aos contratos
                </label>
              </div>
              <div className="flex items-end">
                <label className="inline-flex items-center gap-2 text-sm text-foreground cursor-pointer" title="Apaga contratos existentes com os mesmos IDs e reindexa">
                  <input
                    type="checkbox"
                    checked={hardReprocess}
                    onChange={(e) => setHardReprocess(e.target.checked)}
                    className="rounded border-border text-destructive focus:ring-destructive/40"
                  />
                  Hard reprocess
                </label>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button
                onClick={handlePreview}
                disabled={!file || stage === "previewing" || stage === "ingesting"}
                loading={stage === "previewing"}
                icon={<FileJson size={16} />}
              >
                Pré-visualizar
              </Button>
              <Button
                variant="primary"
                onClick={handlePreview}
                disabled={!file || stage === "previewing" || stage === "ingesting"}
                loading={stage === "ingesting"}
                icon={<Database size={16} />}
              >
                Importar tudo
              </Button>
            </div>
          </CardContent>
        </Card>

        {error && (
          <div className="flex items-start gap-3 p-4 rounded-xl bg-destructive/10 text-destructive border border-destructive/20">
            <AlertTriangle size={20} className="shrink-0 mt-0.5" />
            <div className="text-sm">{error}</div>
          </div>
        )}

        {preview && stage !== "idle" && (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Pré-visualização</CardTitle>
                <div className="flex gap-2">
                  <Badge variant="secondary">{translateDataType(preview.data_type)}</Badge>
                  <Badge variant="outline">{translateFileType(preview.file_type)}</Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Ficheiro</p>
                  <p className="text-sm font-medium truncate">{preview.filename}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Total de registos</p>
                  <p className="text-sm font-medium">{preview.total_rows.toLocaleString("pt-PT")}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Amostra</p>
                  <p className="text-sm font-medium">{preview.rows.length.toLocaleString("pt-PT")}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Campos</p>
                  <p className="text-sm font-medium">{preview.sample_schema.join(", ")}</p>
                </div>
              </div>

              {preview.warnings.length > 0 && (
                <div className="flex items-start gap-2 text-sm text-amber-600 bg-amber-50 dark:bg-amber-950/20 p-3 rounded-lg">
                  <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                  <ul className="list-disc pl-4 space-y-1">
                    {preview.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="min-w-full text-sm">
                  <thead className="bg-muted/50 text-muted-foreground">
                    <tr>
                      {preview.sample_schema.slice(0, 8).map((col) => (
                        <th key={col} className="px-3 py-2 text-left font-medium whitespace-nowrap">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {preview.rows.slice(0, 10).map((row, idx) => (
                      <tr key={idx} className="hover:bg-accent/30">
                        {preview.sample_schema.slice(0, 8).map((col) => {
                          const value = (row.raw as Record<string, unknown>)[col];
                          return (
                            <td key={col} className="px-3 py-2 text-foreground whitespace-nowrap">
                              {value === null || value === undefined ? "—" : String(value).slice(0, 60)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={clearFile}>
                  Cancelar
                </Button>
                <Button
                  onClick={handleIngest}
                  loading={stage === "ingesting"}
                  disabled={stage === "ingesting"}
                  icon={<Database size={16} />}
                >
                  Confirmar importação
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {result && stage === "done" && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Check className="text-emerald-500" size={20} />
                <CardTitle>Importação concluída</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Indexados</p>
                  <p className="text-lg font-semibold">{result.indexed_count.toLocaleString("pt-PT")}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Total processado</p>
                  <p className="text-lg font-semibold">{result.total.toLocaleString("pt-PT")}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Erros</p>
                  <p className="text-lg font-semibold">{result.errors.toLocaleString("pt-PT")}</p>
                </div>
                <div className="p-3 rounded-lg border border-border bg-accent/40">
                  <p className="text-xs text-muted-foreground">Entidades ligadas</p>
                  <p className="text-lg font-semibold">{result.linked_entities.toLocaleString("pt-PT")}</p>
                </div>
              </div>
              {(result.duplicate_count && result.duplicate_count > 0) || (result.deleted_count && result.deleted_count > 0) ? (
                <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
                  {result.duplicate_count && result.duplicate_count > 0 && (
                    <div className="p-3 rounded-lg border border-border bg-amber-50 dark:bg-amber-950/20">
                      <p className="text-xs text-amber-700">Duplicados detetados</p>
                      <p className="text-lg font-semibold text-amber-800">{result.duplicate_count.toLocaleString("pt-PT")}</p>
                    </div>
                  )}
                  {result.deleted_count && result.deleted_count > 0 && (
                    <div className="p-3 rounded-lg border border-border bg-destructive/10">
                      <p className="text-xs text-destructive">Apagados (hard reprocess)</p>
                      <p className="text-lg font-semibold text-destructive">{result.deleted_count.toLocaleString("pt-PT")}</p>
                    </div>
                  )}
                </div>
              ) : null}
              {result.message && <p className="mt-4 text-sm text-muted-foreground">{result.message}</p>}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

export default ImportPage;
