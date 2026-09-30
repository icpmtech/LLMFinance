/**
 * **Recolha de Empresas** — recolha massiva de diretórios web (Iberinform.pt).
 *
 * Dois modos:
 * 1. **Concelho** — um concelho, um intervalo de páginas (ou todas as páginas);
 * 2. **Distrito inteiro** — todos os concelhos do distrito, todas as páginas de
 *    cada um, com progresso por concelho e retoma a partir do manifesto.
 *
 * O catálogo de distritos e concelhos é lido do próprio diretório, pelo que a
 * lista está sempre atualizada (e mostra o volume de empresas que o site anuncia).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Download,
  FileJson,
  FolderOpen,
  Globe2,
  Layers,
  Loader2,
  MapPin,
  Play,
  RefreshCw,
  Search,
} from "lucide-react";

import {
  getCatalogo,
  getDistritoEstado,
  getEmpresasRecolhaJob,
  getEmpresasRecolhaMeta,
  listEmpresasRecolhaExports,
  listEmpresasRecolhaJobs,
  previewEmpresaDetail,
  readEmpresasRecolhaExport,
  runEmpresasRecolhaSync,
  startDistritoJob,
  startEmpresasRecolhaJob,
  type EmpresasRecolhaCatalogo,
  type EmpresasRecolhaExportContent,
  type EmpresasRecolhaExportFile,
  type EmpresasRecolhaItem,
  type EmpresasRecolhaJob,
  type EmpresasRecolhaLocal,
  type EmpresasRecolhaManifesto,
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

/** Estimativa grosseira do tempo de recolha (segundos por empresa com detalhe). */
const SEGUNDOS_POR_EMPRESA = 3.2;

function estimativa(empresas: number | null | undefined, delay: number, paralelo: number): string {
  if (!empresas) return "—";
  const porEmpresa = Math.max(1.2, SEGUNDOS_POR_EMPRESA - 0.5 + delay);
  const segundos = (empresas * porEmpresa) / Math.max(1, paralelo);
  if (segundos < 120) return `~${Math.round(segundos)} s`;
  if (segundos < 7200) return `~${Math.round(segundos / 60)} min`;
  return `~${(segundos / 3600).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} h`;
}

type Modo = "concelho" | "distrito";

export default function EmpresasRecolhaPage() {
  const [meta, setMeta] = useState<EmpresasRecolhaMeta | null>(null);
  const [catalogo, setCatalogo] = useState<EmpresasRecolhaCatalogo | null>(null);
  const [aCarregarCatalogo, setACarregarCatalogo] = useState(false);
  const [erroGeral, setErroGeral] = useState<string | null>(null);

  const [modo, setModo] = useState<Modo>("distrito");
  const [distrito, setDistrito] = useState("");
  const [concelho, setConcelho] = useState("");
  const [startPage, setStartPage] = useState<number | "">(1);
  const [maxPages, setMaxPages] = useState<number | "">(1);
  const [allPages, setAllPages] = useState(true);
  const [detail, setDetail] = useState(true);
  const [delay, setDelay] = useState<number | "">(0.5);
  const [paralelo, setParalelo] = useState<number | "">(4);
  const [ingest, setIngest] = useState(false);
  const [skipDone, setSkipDone] = useState(true);

  const [jobs, setJobs] = useState<EmpresasRecolhaJob[] | null>(null);
  const [exports, setExports] = useState<EmpresasRecolhaExportFile[] | null>(null);
  const [selectedExport, setSelectedExport] = useState<EmpresasRecolhaExportContent | null>(null);
  const [manifesto, setManifesto] = useState<EmpresasRecolhaManifesto | null>(null);

  const [aCarregar, setACarregar] = useState(false);
  const [aArrancar, setAArrancar] = useState(false);
  const [resultadoSync, setResultadoSync] = useState<EmpresasRecolhaResult | null>(null);

  const [urlDetalhe, setUrlDetalhe] = useState("");
  const [preview, setPreview] = useState<EmpresasRecolhaItem | null>(null);
  const [aCarregarPreview, setACarregarPreview] = useState(false);

  const [filtroDistrito, setFiltroDistrito] = useState("");
  const [filtroConcelho, setFiltroConcelho] = useState("");

  const carregarCatalogo = useCallback(async (refresh = false) => {
    setACarregarCatalogo(true);
    try {
      setCatalogo(await getCatalogo(refresh));
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregarCatalogo(false);
    }
  }, []);

  const carregar = useCallback(async () => {
    setACarregar(true);
    setErroGeral(null);
    try {
      const m = await getEmpresasRecolhaMeta();
      setMeta(m);
      const j = await listEmpresasRecolhaJobs(20);
      setJobs(j.jobs);
      const e = await listEmpresasRecolhaExports(filtroDistrito || undefined, filtroConcelho || undefined, 200);
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
    void carregarCatalogo(false);
  }, [carregarCatalogo]);

  // Manifesto do distrito escolhido (estado por concelho).
  useEffect(() => {
    if (!distrito) {
      setManifesto(null);
      return;
    }
    const slug = catalogo?.distritos.find((d) => d.nome === distrito)?.slug || distrito;
    getDistritoEstado(slug)
      .then(setManifesto)
      .catch(() => setManifesto(null));
  }, [distrito, catalogo, jobs]);

  useEffect(() => {
    if (!jobs?.some((j) => j.status === "running" || j.status === "pending")) return;
    const id = setInterval(async () => {
      const atualizados: EmpresasRecolhaJob[] = [];
      for (const j of jobs) {
        if ((j.status !== "running" && j.status !== "pending") || !j.job_id) {
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
    }, 3000);
    return () => clearInterval(id);
  }, [jobs]);

  const distritosDisponiveis = catalogo?.distritos ?? [];
  const distritoAtual = useMemo(
    () => distritosDisponiveis.find((d) => d.nome === distrito || d.slug === distrito) ?? null,
    [distritosDisponiveis, distrito],
  );
  const concelhosDoDistrito: EmpresasRecolhaLocal[] = distritoAtual?.concelhos ?? [];
  const concelhoAtual = useMemo(
    () => concelhosDoDistrito.find((c) => c.nome === concelho || c.slug === concelho) ?? null,
    [concelhosDoDistrito, concelho],
  );

  const empresasAlvo = modo === "distrito" ? distritoAtual?.empresas ?? null : concelhoAtual?.empresas ?? null;
  const totalConcelhosFeitos = manifesto ? Object.values(manifesto.concelhos || {}).filter((c) => c.ok).length : 0;
  const totalConcelhosAlvo = concelhosDoDistrito.length;

  const validar = (): boolean => {
    if (!distrito.trim()) {
      setErroGeral("Escolha um distrito.");
      return false;
    }
    if (modo === "concelho" && !concelho.trim()) {
      setErroGeral("Escolha um concelho.");
      return false;
    }
    return true;
  };

  const requisicao = () => ({
    distrito: distritoAtual?.slug || distrito,
    concelho: concelhoAtual?.slug || concelho,
    start_page: Number(startPage || 1),
    max_pages: allPages ? 500 : Number(maxPages || 1),
    all_pages: allPages,
    detail,
    delay: Number(delay ?? 0.5),
    ingest,
  });

  const handleSync = async () => {
    if (!validar() || modo === "distrito") return;
    setAArrancar(true);
    setErroGeral(null);
    setResultadoSync(null);
    try {
      const res = await runEmpresasRecolhaSync(requisicao());
      setResultadoSync(res);
      await carregar();
    } catch (err) {
      setErroGeral(err instanceof Error ? err.message : String(err));
    } finally {
      setAArrancar(false);
    }
  };

  const handleJob = async () => {
    if (!validar()) return;
    setAArrancar(true);
    setErroGeral(null);
    try {
      if (modo === "distrito") {
        await startDistritoJob({
          distrito: distritoAtual?.slug || distrito,
          start_page: Number(startPage || 1),
          max_pages: 500,
          detail,
          delay: Number(delay ?? 0.5),
          ingest,
          skip_done: skipDone,
          paralelo: Number(paralelo || 1),
        });
      } else {
        await startEmpresasRecolhaJob(requisicao());
      }
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

  const seletor = "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none";
  const botao = "flex items-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-50";

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 p-2">
            <Building2 size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Recolha de Empresas</h1>
            <p className="text-xs text-muted-foreground">
              Iberinform.pt · {formatNumber(catalogo?.total_distritos)} distritos,{" "}
              {formatNumber(catalogo?.total_concelhos)} concelhos e {formatNumber(catalogo?.total_empresas)} empresas no
              diretório
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void carregarCatalogo(true)}
            disabled={aCarregarCatalogo}
            className={`${botao} border border-white/10 bg-white/5 hover:bg-white/10`}
          >
            {aCarregarCatalogo ? <Loader2 size={14} className="animate-spin" /> : <Globe2 size={14} />}
            Catálogo
          </button>
          <button
            onClick={carregar}
            disabled={aCarregar}
            className={`${botao} border border-white/10 bg-white/5 hover:bg-white/10`}
          >
            {aCarregar ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Atualizar
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        {erroGeral && <EmptyState tone="warn">{erroGeral}</EmptyState>}

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <SectionCard
              title="Nova recolha"
              subtitle={
                modo === "distrito"
                  ? "Todos os concelhos do distrito, todas as páginas de cada um"
                  : "Um concelho, com o intervalo de páginas pretendido"
              }
              icon={Globe2}
              actions={
                <div className="flex gap-2">
                  <button
                    onClick={handleJob}
                    disabled={aArrancar}
                    className={`${botao} bg-gradient-to-r from-cyan-500 to-blue-600 font-medium text-white hover:from-cyan-400 hover:to-blue-500`}
                  >
                    {aArrancar ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    Em segundo plano
                  </button>
                  <button
                    onClick={handleSync}
                    disabled={aArrancar || modo === "distrito"}
                    title={modo === "distrito" ? "O distrito inteiro só corre em segundo plano" : undefined}
                    className={`${botao} border border-white/10 bg-white/5 hover:bg-white/10`}
                  >
                    Síncrona
                  </button>
                </div>
              }
            >
              <div className="mb-4 flex gap-2">
                {(["distrito", "concelho"] as Modo[]).map((opcao) => (
                  <button
                    key={opcao}
                    onClick={() => setModo(opcao)}
                    className={`${botao} ${
                      modo === opcao
                        ? "bg-white/15 font-medium text-foreground"
                        : "border border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
                    }`}
                  >
                    {opcao === "distrito" ? <Layers size={14} /> : <MapPin size={14} />}
                    {opcao === "distrito" ? "Distrito inteiro" : "Só um concelho"}
                  </button>
                ))}
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <FilterField label="Distrito">
                  <select
                    value={distrito}
                    onChange={(e) => {
                      setDistrito(e.target.value);
                      setConcelho("");
                    }}
                    className={seletor}
                  >
                    <option value="">— escolher —</option>
                    {distritosDisponiveis.map((d) => (
                      <option key={d.slug} value={d.nome}>
                        {d.nome}
                        {d.empresas ? ` (${formatNumber(d.empresas)})` : ""}
                      </option>
                    ))}
                  </select>
                </FilterField>
                <FilterField
                  label={`Concelho${concelhosDoDistrito.length ? ` · ${concelhosDoDistrito.length}` : ""}`}
                >
                  <select
                    value={concelho}
                    onChange={(e) => setConcelho(e.target.value)}
                    disabled={modo === "distrito" || !concelhosDoDistrito.length}
                    className={`${seletor} disabled:opacity-40`}
                  >
                    <option value="">{modo === "distrito" ? "todos" : "— escolher —"}</option>
                    {concelhosDoDistrito.map((c) => (
                      <option key={c.slug} value={c.nome}>
                        {c.nome}
                        {c.empresas ? ` (${formatNumber(c.empresas)})` : ""}
                      </option>
                    ))}
                  </select>
                </FilterField>
                <FilterField label="Página inicial">
                  <input
                    type="number"
                    min={1}
                    value={startPage}
                    onChange={(e) => setStartPage(Number(e.target.value))}
                    className={seletor}
                  />
                </FilterField>
                <FilterField label="N.º páginas">
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={maxPages}
                    disabled={allPages}
                    onChange={(e) => setMaxPages(Number(e.target.value))}
                    className={`${seletor} disabled:opacity-40`}
                  />
                </FilterField>
                <FilterField label="Delay detalhe (s)">
                  <input
                    type="number"
                    step={0.05}
                    min={0}
                    max={10}
                    value={delay}
                    onChange={(e) => setDelay(Number(e.target.value))}
                    className={seletor}
                  />
                </FilterField>
                {modo === "distrito" && (
                  <FilterField label="Concelhos em paralelo">
                    <input
                      type="number"
                      min={1}
                      max={6}
                      value={paralelo}
                      onChange={(e) => setParalelo(Number(e.target.value))}
                      className={seletor}
                    />
                  </FilterField>
                )}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={allPages}
                    onChange={(e) => setAllPages(e.target.checked)}
                    className="rounded border-white/20"
                  />
                  Ler todas as páginas
                </label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={detail}
                    onChange={(e) => setDetail(e.target.checked)}
                    className="rounded border-white/20"
                  />
                  Recolher detalhe das fichas
                </label>
                {modo === "distrito" && (
                  <label className="flex items-center gap-2 text-sm text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={skipDone}
                      onChange={(e) => setSkipDone(e.target.checked)}
                      className="rounded border-white/20"
                    />
                    Saltar concelhos já concluídos
                  </label>
                )}
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
              {empresasAlvo != null && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Volume anunciado pelo site:{" "}
                  <strong className="text-foreground">{formatNumber(empresasAlvo)} empresas</strong>
                  {detail && (
                    <>
                      {" "}
                      · duração estimada{" "}
                      {estimativa(empresasAlvo, Number(delay ?? 0.5), modo === "distrito" ? Number(paralelo || 1) : 1)}
                    </>
                  )}
                </p>
              )}
            </SectionCard>

            {modo === "distrito" && distritoAtual && (
              <SectionCard
                title={`Concelhos de ${distritoAtual.nome}`}
                subtitle={`${totalConcelhosFeitos}/${totalConcelhosAlvo} concluídos`}
                icon={Layers}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  {concelhosDoDistrito.map((c) => {
                    const estado = manifesto?.concelhos?.[c.slug];
                    const tone = estado?.ok ? "teal" : estado?.error ? "rose" : "neutral";
                    return (
                      <div
                        key={c.slug}
                        className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm"
                      >
                        <span className="truncate">{c.nome}</span>
                        <span className="flex shrink-0 items-center gap-2">
                          {c.empresas ? (
                            <span className="text-xs text-muted-foreground">{formatNumber(c.empresas)}</span>
                          ) : null}
                          <Chip tone={tone}>
                            {estado?.ok ? `${formatNumber(estado.items_count)} ✓` : estado?.error ? "erro" : "por recolher"}
                          </Chip>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </SectionCard>
            )}

            <SectionCard title="Trabalhos" subtitle="Recolhas em curso e histórico" icon={Play}>
              {!jobs && <Loading label="A carregar trabalhos…" />}
              {jobs && jobs.length === 0 && <EmptyState>Sem recolhas registadas.</EmptyState>}
              {jobs && jobs.length > 0 && (
                <div className="space-y-2">
                  {jobs.map((j) => {
                    const progresso = j.progress as
                      | { indice?: number; total?: number; concelho?: string }
                      | null
                      | undefined;
                    const resultado = j.result as
                      | { items_count?: number; total_items?: number; concelhos_ok?: number; total_concelhos?: number; file?: string }
                      | null
                      | undefined;
                    return (
                      <div key={j.job_id} className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-xs text-muted-foreground">{j.job_id}</span>
                          <Chip tone={j.status === "running" ? "amber" : j.status === "error" ? "rose" : "teal"}>
                            {j.status}
                          </Chip>
                          {j.payload?.distrito && (
                            <span className="text-xs text-muted-foreground">
                              {j.payload.distrito}
                              {j.payload.concelho ? ` / ${j.payload.concelho}` : " · todos os concelhos"}
                            </span>
                          )}
                          {typeof j.concelhos_feitos === "number" && j.concelhos_feitos > 0 && (
                            <span className="text-xs text-muted-foreground">· {j.concelhos_feitos} concelhos feitos</span>
                          )}
                        </div>
                        {j.status === "running" && progresso?.concelho && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            a recolher <strong className="text-foreground">{progresso.concelho}</strong>
                            {typeof progresso.indice === "number" && typeof progresso.total === "number"
                              ? ` (${progresso.indice + 1}/${progresso.total})`
                              : ""}
                          </p>
                        )}
                        {resultado && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {formatNumber(resultado.total_items ?? resultado.items_count ?? 0)} empresas
                            {resultado.concelhos_ok != null
                              ? ` · ${resultado.concelhos_ok}/${resultado.total_concelhos} concelhos`
                              : ""}
                            {resultado.file ? ` · ${resultado.file}` : ""}
                          </p>
                        )}
                        {j.error && <p className="mt-1 text-xs text-rose-300">{j.error}</p>}
                      </div>
                    );
                  })}
                </div>
              )}
            </SectionCard>

            <SectionCard title="Detalhe individual" subtitle="Testar a recolha de uma ficha concreta" icon={Search}>
              <div className="flex gap-2">
                <input
                  value={urlDetalhe}
                  onChange={(e) => setUrlDetalhe(e.target.value)}
                  placeholder="https://www.iberinform.pt/empresa/24050518/..."
                  autoComplete="off"
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
                    <strong>{formatNumber(Number(resultadoSync.items_count || 0))}</strong>                    {resultadoSync.pages ? (
                      <span className="text-muted-foreground"> · {formatNumber(resultadoSync.pages)} páginas</span>
                    ) : null}                  </p>
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
                subtitle={`${formatNumber(selectedExport.items.length)} empresas · run ${selectedExport.run_id}`}
                icon={FolderOpen}
              >
                <div className="max-h-[400px] overflow-auto rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-muted-foreground">
                  <pre>{JSON.stringify(selectedExport.items.slice(0, 5), null, 2)}</pre>
                  {selectedExport.items.length > 5 && (
                    <p className="mt-2 text-muted-foreground">… mais {selectedExport.items.length - 5} empresas</p>
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
