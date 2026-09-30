/**
 * **Recolha de Empresas** — recolha massiva de diretórios web (Iberinform.pt)
 * organizada por distrito/concelho.
 *
 * Funcionalidades:
 * 1. Arrancar uma recolha por distrito/concelho e páginas;
 * 2. Ver progresso dos jobs em curso e histórico;
 * 3. Listar e pré-visualizar exportações JSON;
 * 4. Testar a recolha de uma ficha individual.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Download,
  FileJson,
  FolderOpen,
  Globe2,
  Loader2,
  MapPin,
  Play,
  RefreshCw,
  Search,
} from "lucide-react";

import {
  getEmpresasRecolhaJob,
  getEmpresasRecolhaMeta,
  listEmpresasRecolhaExports,
  listEmpresasRecolhaJobs,
  previewEmpresaDetail,
  readEmpresasRecolhaExport,
  runEmpresasRecolhaSync,
  startEmpresasRecolhaJob,
  type EmpresasRecolhaExportContent,
  type EmpresasRecolhaExportFile,
  type EmpresasRecolhaItem,
  type EmpresasRecolhaJob,
  type EmpresasRecolhaMeta,
  type EmpresasRecolhaResult,
} from "../empresasRecolhaApi";
import {
  Chip,
  EmptyState,
  FilterField,
  Loading,
  SearchInput,
  SectionCard,
  formatDate,
  formatNumber,
} from "../components/padroes/padroesKit";

function tamanho(bytes?: number | null): string {
  if (!bytes) return "—";
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} kB`;
  return `${bytes} B`;
}

function nomeDistritoConcelho(file: EmpresasRecolhaExportFile): string {
  return `${file.distrito || "?"} / ${file.concelho || "?"}`;
}

export default function EmpresasRecolhaPage() {
  const [meta, setMeta] = useState<EmpresasRecolhaMeta | null>(null);
  const [erroGeral, setErroGeral] = useState<string | null>(null);

  const [distrito, setDistrito] = useState("");
  const [concelho, setConcelho] = useState("");
  const [startPage, setStartPage] = useState<number | "">(1);
  const [maxPages, setMaxPages] = useState<number | "">(1);
  const [detail, setDetail] = useState(true);
  const [delay, setDelay] = useState<number | "">(1.0);
  const [ingest, setIngest] = useState(false);

  const [jobs, setJobs] = useState<EmpresasRecolhaJob[] | null>(null);
  const [exports, setExports] = useState<EmpresasRecolhaExportFile[] | null>(null);
  const [selectedExport, setSelectedExport] = useState<EmpresasRecolhaExportContent | null>(null);

  const [aCarregar, setACarregar] = useState(false);
  const [aArrancar, setAArrancar] = useState(false);
  const [resultadoSync, setResultadoSync] = useState<EmpresasRecolhaResult | null>(null);

  const [urlDetalhe, setUrlDetalhe] = useState("");
  const [preview, setPreview] = useState<EmpresasRecolhaItem | null>(null);
  const [aCarregarPreview, setACarregarPreview] = useState(false);

  const [filtroDistrito, setFiltroDistrito] = useState("");
  const [filtroConcelho, setFiltroConcelho] = useState("");

  const carregar = useCallback(async () => {
    setACarregar(true);
    setErroGeral(null);
    try {
      const m = await getEmpresasRecolhaMeta();
      setMeta(m);
      const j = await listEmpresasRecolhaJobs(20);
      setJobs(j.jobs);
      const e = await listEmpresasRecolhaExports(filtroDistrito || undefined, filtroConcelho || undefined, 100);
      setExports(e.files);
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregar(false);
    }
  }, [filtroDistrito, filtroConcelho]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  useEffect(() => {
    if (!jobs?.some((j) => j.status === "running")) return;
    const id = setInterval(async () => {
      const atualizados: EmpresasRecolhaJob[] = [];
      for (const j of jobs) {
        if (j.status !== "running" || !j.job_id) {
          atualizados.push(j);
          continue;
        }
        try {
          const atual = await getEmpresasRecolhaJob(j.job_id);
          atualizados.push(atual);
        } catch {
          atualizados.push(j);
        }
      }
      setJobs(atualizados);
    }, 2000);
    return () => clearInterval(id);
  }, [jobs]);

  const handleSync = async () => {
    if (!distrito.trim() || !concelho.trim()) {
      setErroGeral("Distrito e concelho são obrigatórios.");
      return;
    }
    setAArrancar(true);
    setErroGeral(null);
    setResultadoSync(null);
    try {
      const res = await runEmpresasRecolhaSync({
        distrito: distrito.trim(),
        concelho: concelho.trim(),
        start_page: Number(startPage || 1),
        max_pages: Number(maxPages || 1),
        detail,
        delay: Number(delay || 1),
        ingest,
      });
      setResultadoSync(res);
      await carregar();
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setAArrancar(false);
    }
  };

  const handleJob = async () => {
    if (!distrito.trim() || !concelho.trim()) {
      setErroGeral("Distrito e concelho são obrigatórios.");
      return;
    }
    setAArrancar(true);
    setErroGeral(null);
    try {
      await startEmpresasRecolhaJob({
        distrito: distrito.trim(),
        concelho: concelho.trim(),
        start_page: Number(startPage || 1),
        max_pages: Number(maxPages || 1),
        detail,
        delay: Number(delay || 1),
        ingest,
      });
      const j = await listEmpresasRecolhaJobs(20);
      setJobs(j.jobs);
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setAArrancar(false);
    }
  };

  const handlePreviewExport = async (path: string) => {
    try {
      setSelectedExport(await readEmpresasRecolhaExport(path));
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    }
  };

  const handlePreviewDetail = async () => {
    if (!urlDetalhe.trim()) return;
    setACarregarPreview(true);
    setErroGeral(null);
    setPreview(null);
    try {
      setPreview(await previewEmpresaDetail(urlDetalhe.trim()));
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregarPreview(false);
    }
  };

  const exportacoesFiltradas = useMemo(() => {
    if (!exports) return [];
    return exports.filter((f) => {
      const okDistrito = !filtroDistrito || (f.distrito?.toLowerCase() || "").includes(filtroDistrito.toLowerCase());
      const okConcelho = !filtroConcelho || (f.concelho?.toLowerCase() || "").includes(filtroConcelho.toLowerCase());
      return okDistrito && okConcelho;
    });
  }, [exports, filtroDistrito, filtroConcelho]);

  // Sugestão: se o utilizador filtrar distritos mas só restar um, podemos
  // expor a função `getEmpresasRecolhaConcelhos` num dropdown futuro.

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 p-2">
            <Building2 size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Recolha de Empresas</h1>
            <p className="text-xs text-muted-foreground">Diretórios web → JSON por distrito/concelho</p>
          </div>
        </div>
        <button
          onClick={carregar}
          disabled={aCarregar}
          className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
        >
          {aCarregar ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Atualizar
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        {erroGeral && <EmptyState tone="warn">{erroGeral}</EmptyState>}

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <SectionCard
              title="Nova recolha"
              subtitle="Escolha distrito, concelho e quantas páginas recolher"
              icon={Globe2}
              actions={
                <div className="flex gap-2">
                  <button
                    onClick={handleJob}
                    disabled={aArrancar}
                    className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-2 text-sm font-medium text-white hover:from-cyan-400 hover:to-blue-500 disabled:opacity-50"
                  >
                    {aArrancar ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    Em segundo plano
                  </button>
                  <button
                    onClick={handleSync}
                    disabled={aArrancar}
                    className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
                  >
                    Síncrona
                  </button>
                </div>
              }
            >
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <FilterField label="Distrito">
                  <input
                    value={distrito}
                    onChange={(e) => setDistrito(e.target.value)}
                    placeholder="Ex.: Évora"
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/60"
                  />
                </FilterField>
                <FilterField label="Concelho">
                  <input
                    value={concelho}
                    onChange={(e) => setConcelho(e.target.value)}
                    placeholder="Ex.: Alandroal"
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/60"
                  />
                </FilterField>
                <FilterField label="Página inicial">
                  <input
                    type="number"
                    min={1}
                    value={startPage}
                    onChange={(e) => setStartPage(Number(e.target.value))}
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none"
                  />
                </FilterField>
                <FilterField label="N.º páginas">
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={maxPages}
                    onChange={(e) => setMaxPages(Number(e.target.value))}
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none"
                  />
                </FilterField>
                <FilterField label="Delay detalhe (s)">
                  <input
                    type="number"
                    step={0.1}
                    min={0}
                    max={10}
                    value={delay}
                    onChange={(e) => setDelay(Number(e.target.value))}
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none"
                  />
                </FilterField>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={detail}
                    onChange={(e) => setDetail(e.target.checked)}
                    className="rounded border-white/20"
                  />
                  Recolher detalhe
                </label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={ingest}
                    onChange={(e) => setIngest(e.target.checked)}
                    className="rounded border-white/20"
                  />
                  Indexar no finance_scraped
                </label>
              </div>
            </SectionCard>

            <SectionCard title="Jobs" subtitle="Recolhas em curso e histórico" icon={Play}>
              {!jobs && <Loading label="A carregar jobs…" />}
              {jobs && jobs.length === 0 && <EmptyState>Sem recolhas registadas.</EmptyState>}
              {jobs && jobs.length > 0 && (
                <div className="space-y-2">
                  {jobs.map((j) => (
                    <div key={j.job_id} className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">{j.job_id}</span>
                        <Chip tone={j.status === "running" ? "amber" : j.status === "error" ? "rose" : "teal"}>
                          {j.status}
                        </Chip>
                        {j.payload && (
                          <span className="text-xs text-muted-foreground">
                            {j.payload.distrito} / {j.payload.concelho} · pág.{j.payload.start_page} · {j.payload.max_pages} pág.
                          </span>
                        )}
                      </div>
                      {j.result && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {formatNumber(j.result.items_count || 0)} itens · {j.result.file || ""}
                        </p>
                      )}
                      {j.error && <p className="mt-1 text-xs text-rose-300">{j.error}</p>}
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>

            <SectionCard title="Detalhe individual" subtitle="Testar a recolha de uma ficha concreta" icon={Search}>
              <div className="flex gap-2">
                <input
                  value={urlDetalhe}
                  onChange={(e) => setUrlDetalhe(e.target.value)}
                  placeholder="https://www.iberinform.pt/empresa/24050518/..."
                  className="min-w-0 flex-1 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/60"
                />
                <button
                  onClick={handlePreviewDetail}
                  disabled={aCarregarPreview || !urlDetalhe.trim()}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
                >
                  {aCarregarPreview ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                  Testar
                </button>
              </div>
              {preview && (
                <div className="mt-3 max-h-64 overflow-auto rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-muted-foreground">
                  <pre>{JSON.stringify(preview, null, 2)}</pre>
                </div>
              )}
            </SectionCard>
          </div>

          <div className="space-y-6">
            {resultadoSync && (
              <SectionCard title="Resultado síncrono" icon={Download}>
                <div className="space-y-2 text-sm">
                  <p>
                    <span className="text-muted-foreground">Itens:</span>{" "}
                    <strong>{formatNumber(Number(resultadoSync.items_count || 0))}</strong>
                  </p>
                  <p className="break-all text-xs text-muted-foreground">{String(resultadoSync.file || "")}</p>
                </div>
              </SectionCard>
            )}

            <SectionCard
              title="Exportações"
              subtitle={`Pasta: ${meta?.export_dir || "—"}`}
              icon={FileJson}
            >
              <div className="mb-3 space-y-2">
                <SearchInput
                  value={filtroDistrito}
                  onChange={setFiltroDistrito}
                  placeholder="Filtrar distrito"
                />
                <SearchInput
                  value={filtroConcelho}
                  onChange={setFiltroConcelho}
                  placeholder="Filtrar concelho"
                />
              </div>
              {!exports && <Loading label="A carregar exportações…" />}
              {exports && exportacoesFiltradas.length === 0 && <EmptyState>Sem exportações.</EmptyState>}
              {exportacoesFiltradas.length > 0 && (
                <div className="max-h-[500px] space-y-2 overflow-auto pr-1">
                  {exportacoesFiltradas.map((f) => (
                    <button
                      key={f.path}
                      onClick={() => handlePreviewExport(f.file)}
                      className="w-full rounded-xl border border-white/10 bg-white/5 p-3 text-left text-sm hover:bg-white/10"
                    >
                      <div className="flex items-center gap-2">
                        <MapPin size={14} className="text-cyan-300" />
                        <span className="font-medium">{nomeDistritoConcelho(f)}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatDate(f.mtime)} · {tamanho(f.bytes)}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </SectionCard>

            {selectedExport && (
              <SectionCard
                title={`${selectedExport.distrito} / ${selectedExport.concelho}`}
                subtitle={`${formatNumber(selectedExport.items.length)} itens · run ${selectedExport.run_id}`}
                icon={FolderOpen}
              >
                <div className="max-h-[400px] overflow-auto rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-muted-foreground">
                  <pre>{JSON.stringify(selectedExport.items.slice(0, 5), null, 2)}</pre>
                  {selectedExport.items.length > 5 && (
                    <p className="mt-2 text-muted-foreground">… mais {selectedExport.items.length - 5} itens</p>
                  )}
                </div>
              </SectionCard>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
