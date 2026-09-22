/**
 * Contratos públicos de Espanha (PLACSP) — pesquisa com facetas.
 *
 * Segue o desenho da página de contratos portugueses (`ContractsSearchPage`):
 * pesquisa por texto com autocomplete, facetas laterais clicáveis, lista de
 * resultados com detalhe expansível e importação de anos (normalização dos ZIPs
 * + indexação no Elasticsearch) em segundo plano.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  Database,
  ExternalLink,
  Filter,
  Frown,
  Landmark,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  CONTRATOS_ES_ENTRY_EVENT,
  autocompleteContratosEs,
  getContratoEs,
  getContratosEsImports,
  getContratosEsMeta,
  getContratosEsStatus,
  importContratosEs,
  searchContratosEs,
  takeContratosEsEntry,
} from "../contratosEsApi";
import type {
  ContratoEsFacets,
  ContratoEsImportJob,
  ContratoEsItem,
  ContratoEsMeta,
  ContratoEsSearchRequest,
  ContratoEsStats,
  ContratoEsStatus,
  ContratoEsSuggestion,
} from "../contratosEsApi";

interface ContractsEsSearchPageProps {
  onSwitchView?: () => void;
  onSwitchDashboard?: () => void;
}

function formatMoney(n?: number | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

/** Valores somados podem ser muito grandes: usa sufixos para caber no cartão. */
function formatMoneyCompact(n?: number | null) {
  if (n === undefined || n === null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} M€`;
  if (abs >= 10_000) return `${(n / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return formatMoney(n);
}

function formatDate(d?: string) {
  if (!d) return "—";
  const date = new Date(d);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString("pt-PT");
}

/** Facetas laterais: chave devolvida pela API → campo do pedido + rótulo. */
const FACET_CONFIG: { key: keyof ContratoEsFacets; label: string; request: keyof ContratoEsSearchRequest }[] = [
  { key: "fonte", label: "Fonte", request: "fonte" },
  { key: "ano", label: "Ano", request: "ano" },
  { key: "tipo", label: "Tipo de contrato", request: "tipo" },
  { key: "estado", label: "Estado", request: "estado" },
  { key: "procedimiento", label: "Procedimento", request: "procedimiento" },
  { key: "localidad", label: "Localidade", request: "localidad" },
  { key: "nuts", label: "NUTS", request: "nuts" },
  { key: "cpv", label: "CPV", request: "cpv_code" },
  { key: "organo", label: "Órgão adjudicante", request: "organo" },
  { key: "adjudicatario", label: "Adjudicatário", request: "adjudicatario" },
];

const FONTE_LABELS: Record<string, string> = {
  licitaciones: "Licitações",
  menores: "Contratos menores",
};

const PAGE_SIZE = 20;

export function ContractsEsSearchPage({ onSwitchView, onSwitchDashboard }: ContractsEsSearchPageProps) {
  // Pedido vindo de outra app (ex.: Pesquisa total): contrato concreto ou uma
  // pesquisa focada num órgão adjudicante / empresa adjudicatária.
  const [entryRequest, setEntryRequest] = useState(() => takeContratosEsEntry());
  const [status, setStatus] = useState<ContratoEsStatus | null>(null);
  const [meta, setMeta] = useState<ContratoEsMeta | null>(null);
  const [query, setQuery] = useState(entryRequest?.q ?? "");
  const [ano, setAno] = useState<number | "">("");
  const [fonte, setFonte] = useState("");
  const [tipo, setTipo] = useState("");
  const [estado, setEstado] = useState("");
  const [procedimiento, setProcedimiento] = useState("");
  const [localidad, setLocalidad] = useState("");
  const [nuts, setNuts] = useState("");
  const [organo, setOrgano] = useState(entryRequest?.organo ?? "");
  const [adjudicatario, setAdjudicatario] = useState(entryRequest?.adjudicatario ?? "");
  const [adjudicatarioNif, setAdjudicatarioNif] = useState("");
  const [organismoId, setOrganismoId] = useState("");
  const [cpv, setCpv] = useState("");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [dateField, setDateField] = useState("fecha_publicacion");
  const [sortBy, setSortBy] = useState("relevancia");

  const [results, setResults] = useState<ContratoEsItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<ContratoEsFacets>({});
  const [stats, setStats] = useState<ContratoEsStats | null>(null);
  const [from, setFrom] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [openDocId, setOpenDocId] = useState<string | null>(null);
  /** Contrato aberto a partir de outra app (Pesquisa total), fixado no topo. */
  const [pinnedDoc, setPinnedDoc] = useState<ContratoEsItem | null>(null);

  const [suggestions, setSuggestions] = useState<ContratoEsSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importFonte, setImportFonte] = useState("licitaciones");
  const [importAno, setImportAno] = useState<number | "">("");
  const [importLimit, setImportLimit] = useState("");
  const [jobs, setJobs] = useState<ContratoEsImportJob[]>([]);
  const [importError, setImportError] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);

  const buildRequest = useCallback(
    (offset: number): ContratoEsSearchRequest => ({
      q: query.trim() || undefined,
      ano: ano === "" ? undefined : Number(ano),
      fonte: fonte || undefined,
      tipo: tipo || undefined,
      estado: estado || undefined,
      procedimiento: procedimiento || undefined,
      localidad: localidad || undefined,
      nuts: nuts || undefined,
      organo: organo || undefined,
      adjudicatario: adjudicatario || undefined,
      adjudicatario_nif: adjudicatarioNif.trim() || undefined,
      organismo_id: organismoId.trim() || undefined,
      cpv_code: cpv.trim() || undefined,
      min_value: minValue ? Number(minValue) : undefined,
      max_value: maxValue ? Number(maxValue) : undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      date_field: dateField,
      size: PAGE_SIZE,
      from: offset,
      sort_by: sortBy,
    }),
    [
      query,
      ano,
      fonte,
      tipo,
      estado,
      procedimiento,
      localidad,
      nuts,
      organo,
      adjudicatario,
      adjudicatarioNif,
      organismoId,
      cpv,
      minValue,
      maxValue,
      startDate,
      endDate,
      dateField,
      sortBy,
    ],
  );

  const doSearch = useCallback(
    async (resetFrom = true, request?: ContratoEsSearchRequest) => {
      const offset = resetFrom ? 0 : from;
      if (resetFrom) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const data = await searchContratosEs(request ?? buildRequest(offset));
        setResults((prev) => (resetFrom ? data.items ?? [] : [...prev, ...(data.items ?? [])]));
        setTotal(data.total ?? 0);
        setFacets(data.facets ?? {});
        setStats(data.stats ?? null);
        setFrom(offset + (data.items ?? []).length);
      } catch (err) {
        if (resetFrom) {
          setResults([]);
          setTotal(0);
        }
        setError(err instanceof Error ? err.message : "Erro na pesquisa");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [buildRequest, from],
  );

  const loadJobs = useCallback(async () => {
    try {
      const data = await getContratosEsImports();
      setJobs(data.jobs ?? []);
    } catch {
      /* sem sessão ou API indisponível: a lista fica vazia */
    }
  }, []);

  useEffect(() => {
    Promise.all([getContratosEsStatus(), getContratosEsMeta()])
      .then(([s, m]) => {
        setStatus(s);
        setMeta(m);
        if (m.zips.length && importAno === "") {
          const latest = m.zips.reduce((acc, z) => (z.ano > acc ? z.ano : acc), m.zips[0].ano);
          setImportAno(latest);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
    void doSearch(true);
    void loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Contrato pedido por outra aplicação (ex.: Pesquisa total): abre o detalhe fixado.
  useEffect(() => {
    const docId = entryRequest?.doc;
    if (!docId) return;
    void (async () => {
      try {
        const doc = (await getContratoEs(docId)) as ContratoEsItem & { error?: string };
        if (doc?.error) return;
        setPinnedDoc(doc);
        setOpenDocId(doc.doc_id ?? docId);
      } catch {
        /* contrato indisponível: a pesquisa normal continua a funcionar */
      }
    })();
  }, [entryRequest]);

  // Pedido de outra aplicação com a página **já montada** (janela aberta): aplica
  // os filtros e pesquisa, em vez de ficar à espera de um novo arranque.
  useEffect(() => {
    const onEntry = () => {
      const entry = takeContratosEsEntry();
      if (!entry) return;
      setEntryRequest(entry);
      // Um pedido novo começa do zero: limpa os filtros anteriores da página.
      setAno("");
      setFonte("");
      setTipo("");
      setEstado("");
      setProcedimiento("");
      setLocalidad("");
      setCpv("");
      setNuts(entry.nuts ?? "");
      setAdjudicatarioNif("");
      setOrganismoId("");
      setMinValue("");
      setMaxValue("");
      setStartDate("");
      setEndDate("");
      setQuery(entry.q ?? "");
      setOrgano(entry.organo ?? "");
      setAdjudicatario(entry.adjudicatario ?? "");
      if (!entry.doc) {
        void doSearch(true, {
          q: entry.q || undefined,
          organo: entry.organo || undefined,
          adjudicatario: entry.adjudicatario || undefined,
          nuts: entry.nuts || undefined,
          date_field: "fecha_publicacion",
          sort_by: "relevancia",
          size: PAGE_SIZE,
          from: 0,
        });
      }
    };
    window.addEventListener(CONTRATOS_ES_ENTRY_EVENT, onEntry);
    return () => window.removeEventListener(CONTRATOS_ES_ENTRY_EVENT, onEntry);
  }, [doSearch]);

  // Autocomplete (órgãos, adjudicatários e CPV) com atraso curto.
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setShowSuggestions(false);
      return;
    }
    const timer = setTimeout(() => {
      autocompleteContratosEs(text, 8)
        .then((d) => {
          setSuggestions(d.suggestions ?? []);
          setShowSuggestions((d.suggestions ?? []).length > 0);
        })
        .catch(() => setShowSuggestions(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  // Progresso das importações: só faz polling enquanto houver trabalhos a correr.
  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const running = jobs.some((j) => !j.finished);
    if (!running) return;
    pollRef.current = window.setInterval(() => {
      void loadJobs();
    }, 3000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [jobs, loadJobs]);

  const applyFacet = (key: keyof ContratoEsFacets, value: string | number) => {
    const config = FACET_CONFIG.find((f) => f.key === key);
    if (!config) return;
    const asString = String(value);
    const next: Record<string, string> = {
      fonte,
      tipo,
      estado,
      procedimiento,
      localidad,
      nuts,
      cpv,
      organo,
      adjudicatario,
    };
    let nextAno: number | "" = ano;
    if (config.request === "ano") {
      nextAno = ano === Number(value) ? "" : Number(value);
    } else {
      const field = config.request === "cpv_code" ? "cpv" : (config.request as string);
      next[field] = next[field] === asString ? "" : asString;
    }
    const nextFilters = { ...next };
    setFonte(nextFilters.fonte);
    setTipo(nextFilters.tipo);
    setEstado(nextFilters.estado);
    setProcedimiento(nextFilters.procedimiento);
    setLocalidad(nextFilters.localidad);
    setNuts(nextFilters.nuts);
    setCpv(nextFilters.cpv);
    setOrgano(nextFilters.organo);
    setAdjudicatario(nextFilters.adjudicatario);
    setAno(nextAno);

    const request: ContratoEsSearchRequest = {
      ...buildRequest(0),
      ano: nextAno === "" ? undefined : Number(nextAno),
      fonte: nextFilters.fonte || undefined,
      tipo: nextFilters.tipo || undefined,
      estado: nextFilters.estado || undefined,
      procedimiento: nextFilters.procedimiento || undefined,
      localidad: nextFilters.localidad || undefined,
      nuts: nextFilters.nuts || undefined,
      cpv_code: nextFilters.cpv || undefined,
      organo: nextFilters.organo || undefined,
      adjudicatario: nextFilters.adjudicatario || undefined,
    };
    void doSearch(true, request);
  };

  const clearFilters = () => {
    setAno("");
    setFonte("");
    setTipo("");
    setEstado("");
    setProcedimiento("");
    setLocalidad("");
    setNuts("");
    setOrgano("");
    setAdjudicatario("");
    setAdjudicatarioNif("");
    setOrganismoId("");
    setCpv("");
    setMinValue("");
    setMaxValue("");
    setStartDate("");
    setEndDate("");
    void doSearch(true, { q: query.trim() || undefined, size: PAGE_SIZE, from: 0, sort_by: sortBy });
  };

  const activeFilters = useMemo(
    () =>
      [
        fonte && { label: "Fonte", value: FONTE_LABELS[fonte] ?? fonte, field: "fonte" as const, clear: () => setFonte("") },
        ano !== "" && { label: "Ano", value: String(ano), field: "ano" as const, clear: () => setAno("") },
        tipo && { label: "Tipo", value: tipo, field: "tipo" as const, clear: () => setTipo("") },
        estado && { label: "Estado", value: estado, field: "estado" as const, clear: () => setEstado("") },
        procedimiento && { label: "Procedimento", value: procedimiento, field: "procedimiento" as const, clear: () => setProcedimiento("") },
        localidad && { label: "Localidade", value: localidad, field: "localidad" as const, clear: () => setLocalidad("") },
        nuts && { label: "NUTS", value: nuts, field: "nuts" as const, clear: () => setNuts("") },
        cpv && { label: "CPV", value: cpv, field: "cpv_code" as const, clear: () => setCpv("") },
        organo && { label: "Órgão", value: organo, field: "organo" as const, clear: () => setOrgano("") },
        adjudicatario && { label: "Adjudicatário", value: adjudicatario, field: "adjudicatario" as const, clear: () => setAdjudicatario("") },
        adjudicatarioNif && { label: "NIF", value: adjudicatarioNif, field: "adjudicatario_nif" as const, clear: () => setAdjudicatarioNif("") },
        organismoId && { label: "DIR3", value: organismoId, field: "organismo_id" as const, clear: () => setOrganismoId("") },
        minValue && { label: "Valor ≥", value: `€ ${minValue}`, field: "min_value" as const, clear: () => setMinValue("") },
        maxValue && { label: "Valor ≤", value: `€ ${maxValue}`, field: "max_value" as const, clear: () => setMaxValue("") },
        startDate && { label: "De", value: startDate, field: "start_date" as const, clear: () => setStartDate("") },
        endDate && { label: "Até", value: endDate, field: "end_date" as const, clear: () => setEndDate("") },
      ].filter(Boolean) as {
        label: string;
        value: string;
        field: keyof ContratoEsSearchRequest;
        clear: () => void;
      }[],
    [fonte, ano, tipo, estado, procedimiento, localidad, nuts, cpv, organo, adjudicatario, adjudicatarioNif, organismoId, minValue, maxValue, startDate, endDate],
  );

  /**
   * Remove um filtro e pesquisa já sem ele.
   *
   * O estado do React só está atualizado no render seguinte, por isso não basta
   * chamar `clear()` e refazer a pesquisa com o pedido corrente: o filtro removido
   * voltava a ser aplicado (bug do fecho obsoleto).
   */
  const removeFilter = (field: keyof ContratoEsSearchRequest, clear: () => void) => {
    clear();
    const request = buildRequest(0);
    delete request[field];
    void doSearch(true, request);
  };

  const startImport = async () => {
    if (importAno === "") {
      setImportError("Escolhe um ano para importar");
      return;
    }
    setImportError(null);
    try {
      const job = await importContratosEs({
        fonte: importFonte,
        ano: Number(importAno),
        limit: importLimit ? Number(importLimit) : undefined,
        index: true,
      });
      setJobs((prev) => [job, ...prev]);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Erro ao arrancar a importação");
    }
  };

  const hasMore = results.length < total;
  const totalValue = stats?.valor_adjudicado_sum ?? null;

  // O contrato pedido por outra app aparece primeiro, sem se repetir na lista.
  const displayResults = useMemo(() => {
    if (!pinnedDoc) return results;
    const pinnedId = pinnedDoc.doc_id;
    return [pinnedDoc, ...results.filter((row) => (row.doc_id ?? "") !== (pinnedId ?? ""))];
  }, [pinnedDoc, results]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Landmark size={22} className="text-amber-400" />
            Contratos Espanha
          </h1>
          <p className="text-sm text-muted-foreground">
            Plataforma de Contratación del Sector Público (PLACSP) — licitações e contratos menores
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void doSearch(true)}
            className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2"
          >
            <RefreshCw size={15} /> Atualizar
          </button>
          <button
            onClick={() => setImportOpen((v) => !v)}
            className="px-3 py-2 rounded-xl bg-secondary text-secondary-foreground hover:bg-accent transition text-sm flex items-center gap-2"
          >
            <Database size={15} /> Importar ano
          </button>
          {onSwitchView && (
            <button
              onClick={onSwitchView}
              className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm"
            >
              Fechar
            </button>
          )}
          {onSwitchDashboard && (
            <button
              onClick={onSwitchDashboard}
              className="px-3 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition text-sm flex items-center gap-2"
            >
              <BarChart3 size={15} /> Dashboard
            </button>
          )}
        </div>
      </header>

      {/* Cartões de resumo — isolate para não sobrepor a barra de pesquisa */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6 isolation-auto">
        <div className="glass-card gradient-border rounded-2xl p-5 glow-blue relative z-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Contratos indexados</p>
          <p className="text-3xl font-bold stat-value text-glow-blue mt-1">
            {status ? status.total.toLocaleString("pt-PT") : "—"}
          </p>
          {status?.years?.length ? (
            <p className="text-xs text-muted-foreground mt-1">
              Anos: {status.years.slice(0, 8).join(", ")}
              {status.years.length > 8 ? "…" : ""}
            </p>
          ) : null}
        </div>
        <div className="glass-card gradient-border rounded-2xl p-5 glow-teal relative z-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Resultados</p>
          <p className="text-3xl font-bold stat-value text-glow-teal mt-1">{total.toLocaleString("pt-PT")}</p>
        </div>
        <div className="glass-card gradient-border rounded-2xl p-5 glow-amber relative z-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor adjudicado (filtro)</p>
          <p className="text-3xl font-bold stat-value text-glow-amber mt-1 whitespace-nowrap">{formatMoneyCompact(totalValue)}</p>
          {stats?.valor_adjudicado_avg ? (
            <p className="text-xs text-muted-foreground mt-1">Média {formatMoney(stats.valor_adjudicado_avg)}</p>
          ) : null}
        </div>
        <div className="glass-card gradient-border rounded-2xl p-5 relative z-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Filtros ativos</p>
          <p className="text-3xl font-bold stat-value mt-1">{activeFilters.length}</p>
        </div>
      </div>

      {/* Importação */}
      {importOpen && (
        <div className="glass-card rounded-2xl p-5 mb-6">
          <h2 className="font-semibold mb-3 flex items-center gap-2">
            <Database size={17} /> Importar do PLACSP para o Elasticsearch
          </h2>
          <p className="text-xs text-muted-foreground mb-3">
            Lê os ZIP/ATOM em <code>data/contratos-espanha</code>, normaliza para JSONL e indexa em{" "}
            <code>contratos_es</code>. Cada ano tem centenas de milhares de contratos — use o limite para uma
            amostra rápida.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Fonte</label>
              <select
                value={importFonte}
                onChange={(e) => setImportFonte(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              >
                <option value="licitaciones">Licitações</option>
                <option value="menores">Contratos menores</option>
                <option value="ambos">Ambos</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Ano (ZIP disponível)</label>
              <select
                value={importAno}
                onChange={(e) => setImportAno(e.target.value ? Number(e.target.value) : "")}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              >
                <option value="">—</option>
                {(meta?.zips ?? [])
                  .filter((z) => importFonte === "ambos" || z.fonte === importFonte)
                  .map((z) => (
                    <option key={`${z.fonte}-${z.ano}`} value={z.ano}>
                      {z.ano} · {FONTE_LABELS[z.fonte] ?? z.fonte}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Limite (opcional)</label>
              <input
                value={importLimit}
                onChange={(e) => setImportLimit(e.target.value.replace(/\D/g, ""))}
                placeholder="ex.: 5000"
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={() => void startImport()}
                className="w-full px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition flex items-center justify-center gap-2"
              >
                <Database size={16} /> Importar
              </button>
            </div>
          </div>
          {importError && <div className="mt-3 rounded-xl px-3 py-2 text-sm bg-destructive/10 text-destructive">{importError}</div>}

          {jobs.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Importações</p>
              {jobs.slice(0, 6).map((job) => (
                <div key={job.id} className="rounded-xl border border-border/60 px-3 py-2 text-sm flex flex-col md:flex-row md:items-center md:justify-between gap-1">
                  <span className="flex items-center gap-2">
                    {!job.finished && <Loader2 size={14} className="animate-spin text-primary" />}
                    <span className="font-medium">
                      {job.ano} · {FONTE_LABELS[job.fonte] ?? job.fonte}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {job.state === "error" ? job.message : `${job.stage ?? job.state}`}
                    </span>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {(job.docs ?? 0).toLocaleString("pt-PT")} docs
                    {job.indexed ? ` · ${job.indexed.toLocaleString("pt-PT")} indexados` : ""}
                    {job.atoms_total ? ` · ficheiros ${job.atoms_done ?? 0}/${job.atoms_total}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Pesquisa — z-10 para ficar acima dos cards de resumo em caso de overlap visual */}
      <div className="glass-card rounded-2xl p-5 mb-6 relative z-10">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={searchInputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => query.trim().length > 1 && setShowSuggestions(suggestions.length > 0)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setShowSuggestions(false);
                  void doSearch(true);
                }
              }}
              placeholder="Pesquisar por objeto, órgão, adjudicatário, expediente ou CPV…"
              className="w-full pl-11 pr-3 py-3 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60 text-base"
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-20 left-0 right-0 top-full mt-1 rounded-xl border border-border bg-card/95 backdrop-blur-md shadow-lg overflow-hidden">
                {suggestions.map((s, i) => (
                  <button
                    key={`${s.type}-${i}`}
                    onClick={() => {
                      if (s.type === "cpv") setCpv(s.text);
                      else if (s.type === "organo") setOrgano(s.text);
                      else setAdjudicatario(s.text);
                      setShowSuggestions(false);
                      void doSearch(true, {
                        ...buildRequest(0),
                        q: undefined,
                        cpv_code: s.type === "cpv" ? s.text : cpv || undefined,
                        organo: s.type === "organo" ? s.text : organo || undefined,
                        adjudicatario: s.type === "adjudicatario" ? s.text : adjudicatario || undefined,
                      });
                    }}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-white/5 transition flex items-center justify-between"
                  >
                    <span className="truncate">{s.text}</span>
                    <span className="text-xs text-muted-foreground ml-2 shrink-0">
                      {s.type} · {s.count}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={() => void doSearch(true)}
            disabled={loading}
            className="px-5 py-3 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2 font-medium shadow-lg shadow-primary/20"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
            Pesquisar
          </button>
          <button
            onClick={() => setAdvancedOpen((v) => !v)}
            className="px-4 py-3 rounded-xl border border-border hover:bg-white/5 transition flex items-center justify-center gap-2"
          >
            <Filter size={16} /> Filtros {advancedOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {activeFilters.map((f) => (
            <button
              key={`${f.label}-${f.value}`}
              onClick={() => removeFilter(f.field, f.clear)}
              className="px-2 py-1 rounded-full text-xs glass-card flex items-center gap-1 hover:bg-white/5"
            >
              <span className="text-muted-foreground">{f.label}:</span> {f.value}
              <X size={12} />
            </button>
          ))}
          {(activeFilters.length > 0 || query) && (
            <button onClick={clearFilters} className="text-xs text-muted-foreground underline hover:text-foreground">
              limpar tudo
            </button>
          )}
        </div>

        {advancedOpen && (
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">NIF do adjudicatário</label>
              <input
                value={adjudicatarioNif}
                onChange={(e) => setAdjudicatarioNif(e.target.value)}
                placeholder="ex.: B98411234"
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Código DIR3 do órgão</label>
              <input
                value={organismoId}
                onChange={(e) => setOrganismoId(e.target.value)}
                placeholder="ex.: EA0003016"
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Valor mínimo (€)</label>
              <input
                value={minValue}
                onChange={(e) => setMinValue(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="0"
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Valor máximo (€)</label>
              <input
                value={maxValue}
                onChange={(e) => setMaxValue(e.target.value.replace(/[^\d.]/g, ""))}
                placeholder="sem limite"
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Campo de data</label>
              <select
                value={dateField}
                onChange={(e) => setDateField(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              >
                <option value="fecha_publicacion">Publicação</option>
                <option value="fecha_adjudicacion">Adjudicação</option>
                <option value="fecha_actualizacion">Atualização</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Data de</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Data até</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Ordenar por</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-background/60 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
              >
                <option value="relevancia">Relevância</option>
                <option value="fecha_publicacion">Data de publicação</option>
                <option value="fecha_adjudicacion">Data de adjudicação</option>
                <option value="valor_adjudicado">Valor adjudicado</option>
                <option value="valor_base">Valor base</option>
                <option value="num_ofertas">Nº de ofertas</option>
                <option value="ano">Ano</option>
              </select>
            </div>
          </div>
        )}

        {error && <div className="mt-4 rounded-xl px-3 py-2 text-sm bg-destructive/10 text-destructive">{error}</div>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        {/* Facetas */}
        <aside className="space-y-4">
          {FACET_CONFIG.map((facet) => {
            const buckets = facets[facet.key] ?? [];
            if (!buckets.length) return null;
            return (
              <div key={facet.key} className="glass-card rounded-2xl p-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">{facet.label}</p>
                <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
                  {buckets.slice(0, 15).map((b) => {
                    const active =
                      facet.request === "ano"
                        ? ano === Number(b.value)
                        : facet.request === "cpv_code"
                          ? cpv === String(b.value)
                          : ({ fonte, tipo, estado, procedimiento, localidad, nuts, organo, adjudicatario }[
                              facet.request as "fonte"
                            ] ?? "") === String(b.value);
                    return (
                      <button
                        key={String(b.value)}
                        onClick={() => applyFacet(facet.key, b.value)}
                        className={`w-full text-left text-xs px-2 py-1 rounded-lg transition flex items-start justify-between gap-2 ${
                          active ? "bg-primary/20 text-foreground" : "hover:bg-white/5 text-muted-foreground"
                        }`}
                        title={b.label ?? String(b.value)}
                      >
                        <span className="truncate">{b.label ?? b.value}</span>
                        <span className="shrink-0 text-[10px] opacity-70">{b.count.toLocaleString("pt-PT")}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </aside>

        {/* Resultados */}
        <section>
          <div className="mb-3 text-sm text-muted-foreground">
            {loading ? "A pesquisar…" : `${results.length.toLocaleString("pt-PT")} de ${total.toLocaleString("pt-PT")} resultado${total === 1 ? "" : "s"}`}
          </div>

          {!loading && results.length === 0 && !error && (
            <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground fade-in">
              <div className="inline-flex p-5 rounded-3xl glass-card mb-2">
                <Frown size={40} className="opacity-60" />
              </div>
              <p>Nenhum contrato encontrado.</p>
              <p className="text-sm">Experimenta pesquisar por objeto, órgão adjudicante ou CPV.</p>
            </div>
          )}

          <div className="space-y-4">
            {displayResults.map((c, i) => {
              const open = openDocId === (c.doc_id ?? String(i));
              return (
                <article
                  key={c.doc_id ?? `${c.id_expediente}-${i}`}
                  className="glass-card gradient-border rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300"
                >
                  <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2 flex-wrap">
                        <span className="px-2 py-0.5 rounded-full glass-card">{c.ano ?? "—"}</span>
                        {c.estado_label && <span className="px-2 py-0.5 rounded-full glass-card">{c.estado_label}</span>}
                        {c.tipo_contrato_label && <span>{c.tipo_contrato_label}</span>}
                        {c.es_menor && <span className="px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300">contrato menor</span>}
                        {pinnedDoc?.doc_id && pinnedDoc.doc_id === c.doc_id && (
                          <span className="px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300">aberto da Pesquisa total</span>
                        )}
                        <span className="truncate">Exp.: {c.id_expediente}</span>
                      </div>
                      <h3 className="font-semibold text-foreground leading-tight mb-1 truncate-2-lines">
                        {c.objeto || "Sem objeto definido"}
                      </h3>
                      <div className="mt-2 text-sm space-y-1">
                        <p className="flex items-start gap-1">
                          <span className="text-muted-foreground shrink-0">Órgão:</span>
                          <span className="truncate">
                            {c.organo_nombre ?? "—"}
                            {c.organo_ciudad ? ` (${c.organo_ciudad})` : ""}
                          </span>
                        </p>
                        <p className="truncate">
                          <span className="text-muted-foreground">Adjudicatário:</span> {c.adjudicatario_nombre ?? "—"}
                          {c.adjudicatario_nif ? ` (${c.adjudicatario_nif})` : ""}
                        </p>
                        {(c.localidad || c.nuts) && (
                          <p className="text-xs text-muted-foreground">
                            Local: {[c.localidad, c.nuts].filter(Boolean).join(" · ")}
                          </p>
                        )}
                        {c.cpv?.length ? (
                          <p className="text-xs text-muted-foreground">CPV: {c.cpv.map((x) => `${x.code} ${x.nombre ?? ""}`.trim()).join("; ")}</p>
                        ) : null}
                      </div>
                    </div>
                    <div className="shrink-0 md:text-right">
                      <div className="text-lg font-bold stat-value text-glow-amber">{formatMoney(c.valor_adjudicado ?? c.valor_base)}</div>
                      <div className="text-xs text-muted-foreground">
                        {c.valor_adjudicado ? "Adjudicado" : "Valor base"} · {c.moneda ?? "EUR"}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        Publicação {formatDate(c.fecha_publicacion)} · Adjudicação {formatDate(c.fecha_adjudicacion)}
                      </div>
                      <div className="mt-2 flex md:justify-end gap-2">
                        <button
                          onClick={() => setOpenDocId(open ? null : (c.doc_id ?? String(i)))}
                          className="px-3 py-1 rounded-lg border border-border text-xs hover:bg-white/5 transition flex items-center gap-1"
                        >
                          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />} Detalhe
                        </button>
                        {c.enlace && (
                          <a
                            href={c.enlace}
                            target="_blank"
                            rel="noreferrer"
                            className="px-3 py-1 rounded-lg border border-border text-xs hover:bg-white/5 transition flex items-center gap-1"
                          >
                            <ExternalLink size={13} /> PLACSP
                          </a>
                        )}
                      </div>
                    </div>
                  </div>

                  {open && (
                    <div className="mt-4 border-t border-border/50 pt-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                      <p><span className="text-muted-foreground">Resultado:</span> {c.resultado_label || c.resultado || "—"}</p>
                      <p><span className="text-muted-foreground">Procedimento:</span> {c.procedimiento_label || c.procedimiento || "—"}</p>
                      <p><span className="text-muted-foreground">Nº de ofertas:</span> {c.num_ofertas ?? "—"}</p>
                      <p><span className="text-muted-foreground">Valor base:</span> {formatMoney(c.valor_base)}</p>
                      <p><span className="text-muted-foreground">Valor adjudicado c/ IVA:</span> {formatMoney(c.valor_adjudicado_con_iva)}</p>
                      <p><span className="text-muted-foreground">Valor estimado:</span> {formatMoney(c.valor_estimado)}</p>
                      <p><span className="text-muted-foreground">Prazo de apresentação:</span> {formatDate(c.fecha_limite)} {c.hora_limite ?? ""}</p>
                      <p><span className="text-muted-foreground">Duração:</span> {c.duracion_valor ?? "—"} {c.duracion_unidad ?? ""}</p>
                      <p><span className="text-muted-foreground">Lotes:</span> {c.num_lotes ?? 0}</p>
                      <p><span className="text-muted-foreground">DIR3 do órgão:</span> {c.organo_id ?? "—"}</p>
                      <p className="md:col-span-2">
                        <span className="text-muted-foreground">Contacto do órgão:</span>{" "}
                        {[c.organo_email, c.organo_web].filter(Boolean).join(" · ") || "—"}
                      </p>
                      {c.descripcion && (
                        <p className="md:col-span-2">
                          <span className="text-muted-foreground">Descrição:</span> {c.descripcion}
                        </p>
                      )}
                      {c.documentos?.length ? (
                        <p className="md:col-span-2 truncate">
                          <span className="text-muted-foreground">Documentos:</span> {c.documentos.join(", ")}
                        </p>
                      ) : null}
                      <p className="md:col-span-2 text-[10px] text-muted-foreground/70">
                        Última atualização no PLACSP: {formatDate(c.fecha_actualizacion)} · fonte: {c.fonte}
                      </p>
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          <div className="py-8 flex flex-col items-center justify-center text-muted-foreground">
            {loadingMore && (
              <div className="flex items-center gap-2 text-sm">
                <Loader2 size={18} className="animate-spin" />
                A carregar mais contratos…
              </div>
            )}
            {!loadingMore && hasMore && results.length > 0 && (
              <button
                onClick={() => void doSearch(false)}
                disabled={loading}
                className="px-4 py-2 rounded-xl border border-border hover:bg-white/5 transition disabled:opacity-50 text-sm"
              >
                Carregar mais
              </button>
            )}
            {!loadingMore && !hasMore && results.length > 0 && <span className="text-xs">Fim dos resultados</span>}
          </div>
        </section>
      </div>
    </div>
  );
}
