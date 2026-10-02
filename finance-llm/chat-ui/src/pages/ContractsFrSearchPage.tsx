/**
 * Contratos públicos de França (DECP) — `/contratos-fr`.
 *
 * Pesquisa por texto com autocomplete, facetas clicáveis, lista de resultados
 * com detalhe expansível e importação de ficheiros DECP em segundo plano.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  ChevronUp,
  Database,
  ExternalLink,
  Filter,
  Frown,
  Landmark,
  Languages,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  CONTRATOS_FR_ENTRY_EVENT,
  autocompleteContratosFr,
  getContratoFr,
  getContratosFrMeta,
  getContratosFrStatus,
  importContratosFr,
  searchContratosFr,
  takeContratosFrEntry,
  translateContratosFr,
} from "../contratosFrApi";
import type {
  ContratoFrFacets,
  ContratoFrImportJob,
  ContratoFrItem,
  ContratoFrMeta,
  ContratoFrSearchRequest,
  ContratoFrStats,
  ContratoFrStatus,
  ContratoFrSuggestion,
} from "../contratosFrApi";

interface ContractsFrSearchPageProps {
  onSwitchView?: () => void;
  onSwitchDashboard?: () => void;
  /** Abre a vista de mapa (OSM) com os mesmos filtros. */
  onSwitchMap?: () => void;
}

function formatMoney(n?: number | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

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

const FACET_CONFIG: { key: keyof ContratoFrFacets; label: string; request: keyof ContratoFrSearchRequest }[] = [
  { key: "ano", label: "Ano", request: "ano" },
  { key: "nature", label: "Natureza", request: "nature" },
  { key: "procedure", label: "Procedimento", request: "procedure" },
  { key: "forme_prix", label: "Forma de preço", request: undefined as unknown as keyof ContratoFrSearchRequest },
  { key: "lieu_execution_type", label: "Tipo de local", request: "lieu_execution_type" },
  { key: "acheteur", label: "Acheteur", request: "acheteur" },
  { key: "adjudicatario", label: "Adjudicatário", request: "adjudicatario" },
  { key: "cpv", label: "CPV", request: "cpv_code" },
];

const PAGE_SIZE = 20;

/** Chave onde fica a escolha «traduzir com IA» (desligada por omissão). */
const TRADUZIR_KEY = "finance-llm-contratos-fr-traduzir";

/** Normaliza como o servidor normaliza (chave da cache de tradução). */
function chaveTraducao(texto: string): string {
  return texto.replace(/\s+/g, " ").trim();
}

export function ContractsFrSearchPage({ onSwitchView, onSwitchDashboard, onSwitchMap }: ContractsFrSearchPageProps) {
  const [entryRequest, setEntryRequest] = useState(() => takeContratosFrEntry());
  const [status, setStatus] = useState<ContratoFrStatus | null>(null);
  const [meta, setMeta] = useState<ContratoFrMeta | null>(null);
  const [query, setQuery] = useState(entryRequest?.q ?? "");
  const [ano, setAno] = useState<number | "">("");
  const [nature, setNature] = useState("");
  const [procedure, setProcedure] = useState("");
  const [acheteur, setAcheteur] = useState(entryRequest?.acheteur ?? "");
  const [acheteurId, setAcheteurId] = useState("");
  const [adjudicatario, setAdjudicatario] = useState(entryRequest?.adjudicatario ?? "");
  const [adjudicatarioId, setAdjudicatarioId] = useState("");
  const [cpv, setCpv] = useState("");
  const [lieuExecutionCode, setLieuExecutionCode] = useState(entryRequest?.lieu_execution_code ?? "");
  const [lieuExecutionType, setLieuExecutionType] = useState(entryRequest?.lieu_execution_type ?? "");
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [dateField, setDateField] = useState("date_publication");
  const [sortBy, setSortBy] = useState("relevance");

  const [results, setResults] = useState<ContratoFrItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<ContratoFrFacets>({});
  const [stats, setStats] = useState<ContratoFrStats | null>(null);
  const [from, setFrom] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [openDocId, setOpenDocId] = useState<string | null>(null);
  const [pinnedDoc, setPinnedDoc] = useState<ContratoFrItem | null>(null);

  const [suggestions, setSuggestions] = useState<ContratoFrSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importFilename, setImportFilename] = useState("");
  const [importLimit, setImportLimit] = useState("");
  const [jobs, setJobs] = useState<ContratoFrImportJob[]>([]);
  const [importError, setImportError] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);

  /* ------------------------------------------- tradução FR→PT a pedido (IA) */
  const [traduzir, setTraduzir] = useState(() => {
    try {
      return typeof window !== "undefined" && window.localStorage.getItem(TRADUZIR_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [traducoes, setTraducoes] = useState<Record<string, string>>({});
  const [aTraduzir, setATraduzir] = useState(false);
  const [erroTraducao, setErroTraducao] = useState<string | null>(null);
  const [iaTraducao, setIaTraducao] = useState<{ provider_label?: string; model?: string } | null>(null);
  const traducoesRef = useRef<Record<string, string>>({});

  /** Texto em português (ou o original, enquanto não houver tradução). */
  const tr = useCallback(
    (texto?: string | null): string => {
      const valor = texto ?? "";
      if (!valor) return "";
      return traducoes[chaveTraducao(valor)] ?? valor;
    },
    [traducoes],
  );

  const buildRequest = useCallback(
    (offset: number): ContratoFrSearchRequest => ({
      q: query.trim() || undefined,
      ano: ano === "" ? undefined : Number(ano),
      nature: nature || undefined,
      procedure: procedure || undefined,
      acheteur: acheteur || undefined,
      acheteur_id: acheteurId.trim() || undefined,
      adjudicatario: adjudicatario || undefined,
      adjudicatario_id: adjudicatarioId.trim() || undefined,
      cpv_code: cpv.trim() || undefined,
      lieu_execution_code: lieuExecutionCode.trim() || undefined,
      lieu_execution_type: lieuExecutionType || undefined,
      min_value: minValue ? Number(minValue) : undefined,
      max_value: maxValue ? Number(maxValue) : undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      date_field: dateField,
      size: PAGE_SIZE,
      from: offset,
      sort_by: sortBy,
      with_facets: true,
    }),
    [
      query,
      ano,
      nature,
      procedure,
      acheteur,
      acheteurId,
      adjudicatario,
      adjudicatarioId,
      cpv,
      lieuExecutionCode,
      lieuExecutionType,
      minValue,
      maxValue,
      startDate,
      endDate,
      dateField,
      sortBy,
    ],
  );

  const doSearch = useCallback(
    async (resetFrom = true, request?: ContratoFrSearchRequest) => {
      const offset = resetFrom ? 0 : from;
      if (resetFrom) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const data = await searchContratosFr(request ?? buildRequest(offset));
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
    // O endpoint /contracts-fr/imports ainda não está implementado no cliente;
    // deixa a lista vazia para evitar erro.
    setJobs([]);
  }, []);

  useEffect(() => {
    Promise.all([getContratosFrStatus(), getContratosFrMeta()])
      .then(([s, m]) => {
        setStatus(s);
        setMeta(m);
        if (m.sources.length && importFilename === "") {
          const latest = m.sources.reduce((acc, z) => (z.ano && z.ano > acc ? z.ano : acc), m.sources[0].ano ?? 0);
          const latestFile = m.sources.find((z) => z.ano === latest)?.filename ?? "";
          setImportFilename(latestFile);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
    void doSearch(true);
    void loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const docId = entryRequest?.doc;
    if (!docId) return;
    void (async () => {
      try {
        const doc = (await getContratoFr(docId)) as ContratoFrItem & { error?: string };
        if (doc?.error) return;
        setPinnedDoc(doc);
        setOpenDocId(doc.doc_id ?? docId);
      } catch {
        /* contrato indisponível: a pesquisa normal continua */
      }
    })();
  }, [entryRequest]);

  useEffect(() => {
    const onEntry = () => {
      const entry = takeContratosFrEntry();
      if (!entry) return;
      setEntryRequest(entry);
      setAno("");
      setNature("");
      setProcedure("");
      setCpv("");
      setLieuExecutionCode("");
      setLieuExecutionType("");
      setMinValue("");
      setMaxValue("");
      setStartDate("");
      setEndDate("");
      setQuery(entry.q ?? "");
      setAcheteur(entry.acheteur ?? "");
      setAdjudicatario(entry.adjudicatario ?? "");
      // Pedido vindo do mapa: filtra pelo local de execução (departamento/região).
      setLieuExecutionCode(entry.lieu_execution_code ?? "");
      setLieuExecutionType(entry.lieu_execution_type ?? "");
      if (!entry.doc) {
        void doSearch(true, {
          q: entry.q || undefined,
          acheteur: entry.acheteur || undefined,
          adjudicatario: entry.adjudicatario || undefined,
          lieu_execution_code: entry.lieu_execution_code || undefined,
          lieu_execution_type: entry.lieu_execution_type || undefined,
          date_field: "date_publication",
          sort_by: "relevance",
          size: PAGE_SIZE,
          from: 0,
        });
      }
    };
    window.addEventListener(CONTRATOS_FR_ENTRY_EVENT, onEntry);
    return () => window.removeEventListener(CONTRATOS_FR_ENTRY_EVENT, onEntry);
  }, [doSearch]);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setShowSuggestions(false);
      return;
    }
    const timer = setTimeout(() => {
      autocompleteContratosFr(text, 8)
        .then((d) => {
          setSuggestions(d.suggestions ?? []);
          setShowSuggestions((d.suggestions ?? []).length > 0);
        })
        .catch(() => setShowSuggestions(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const applyFacet = (key: keyof ContratoFrFacets, value: string | number) => {
    const config = FACET_CONFIG.find((f) => f.key === key);
    if (!config) return;
    const asString = String(value);
    const next: Record<string, string> = {
      nature,
      procedure,
      lieuExecutionType,
      cpv,
      acheteur,
      adjudicatario,
    };
    let nextAno: number | "" = ano;
    if (config.request === "ano") {
      nextAno = ano === Number(value) ? "" : Number(value);
    } else if (config.request === "cpv_code") {
      next.cpv = next.cpv === asString ? "" : asString;
    } else if (config.request === "lieu_execution_type") {
      next.lieuExecutionType = next.lieuExecutionType === asString ? "" : asString;
    } else if (config.request === "acheteur") {
      next.acheteur = next.acheteur === asString ? "" : asString;
    } else if (config.request === "adjudicatario") {
      next.adjudicatario = next.adjudicatario === asString ? "" : asString;
    }
    setNature(next.nature);
    setProcedure(next.procedure);
    setLieuExecutionType(next.lieuExecutionType);
    setCpv(next.cpv);
    setAcheteur(next.acheteur);
    setAdjudicatario(next.adjudicatario);
    setAno(nextAno);

    const request: ContratoFrSearchRequest = {
      ...buildRequest(0),
      ano: nextAno === "" ? undefined : Number(nextAno),
      nature: next.nature || undefined,
      procedure: next.procedure || undefined,
      lieu_execution_type: next.lieuExecutionType || undefined,
      cpv_code: next.cpv || undefined,
      acheteur: next.acheteur || undefined,
      adjudicatario: next.adjudicatario || undefined,
    };
    void doSearch(true, request);
  };

  const clearFilters = () => {
    setAno("");
    setNature("");
    setProcedure("");
    setAcheteur("");
    setAcheteurId("");
    setAdjudicatario("");
    setAdjudicatarioId("");
    setCpv("");
    setLieuExecutionCode("");
    setLieuExecutionType("");
    setMinValue("");
    setMaxValue("");
    setStartDate("");
    setEndDate("");
    void doSearch(true, { q: query.trim() || undefined, size: PAGE_SIZE, from: 0, sort_by: sortBy, with_facets: true });
  };

  const activeFilters = useMemo(
    () =>
      [
        ano !== "" && { label: "Ano", value: String(ano), field: "ano" as const, clear: () => setAno("") },
        nature && { label: "Natureza", value: nature, field: "nature" as const, clear: () => setNature("") },
        procedure && { label: "Procedimento", value: procedure, field: "procedure" as const, clear: () => setProcedure("") },
        lieuExecutionType && { label: "Tipo de local", value: lieuExecutionType, field: "lieu_execution_type" as const, clear: () => setLieuExecutionType("") },
        cpv && { label: "CPV", value: cpv, field: "cpv_code" as const, clear: () => setCpv("") },
        acheteur && { label: "Acheteur", value: acheteur, field: "acheteur" as const, clear: () => setAcheteur("") },
        acheteurId && { label: "ID acheteur", value: acheteurId, field: "acheteur_id" as const, clear: () => setAcheteurId("") },
        adjudicatario && { label: "Adjudicatário", value: adjudicatario, field: "adjudicatario" as const, clear: () => setAdjudicatario("") },
        adjudicatarioId && { label: "ID adjudicatário", value: adjudicatarioId, field: "adjudicatario_id" as const, clear: () => setAdjudicatarioId("") },
        lieuExecutionCode && { label: "Código local", value: lieuExecutionCode, field: "lieu_execution_code" as const, clear: () => setLieuExecutionCode("") },
        minValue && { label: "Valor ≥", value: `€ ${minValue}`, field: "min_value" as const, clear: () => setMinValue("") },
        maxValue && { label: "Valor ≤", value: `€ ${maxValue}`, field: "max_value" as const, clear: () => setMaxValue("") },
        startDate && { label: "De", value: startDate, field: "start_date" as const, clear: () => setStartDate("") },
        endDate && { label: "Até", value: endDate, field: "end_date" as const, clear: () => setEndDate("") },
      ].filter(Boolean) as {
        label: string;
        value: string;
        field: keyof ContratoFrSearchRequest;
        clear: () => void;
      }[],
    [ano, nature, procedure, lieuExecutionType, cpv, acheteur, acheteurId, adjudicatario, adjudicatarioId, lieuExecutionCode, minValue, maxValue, startDate, endDate],
  );

  const removeFilter = (field: keyof ContratoFrSearchRequest, clear: () => void) => {
    clear();
    const request = buildRequest(0);
    delete request[field];
    void doSearch(true, request);
  };

  const startImport = async () => {
    if (!importFilename) {
      setImportError("Escolhe um ficheiro DECP para importar");
      return;
    }
    setImportError(null);
    try {
      const job = await importContratosFr({
        filename: importFilename,
        limit: importLimit ? Number(importLimit) : undefined,
        index: true,
      });
      setJobs((prev) => [job, ...prev]);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Erro ao arrancar a importação");
    }
  };

  const hasMore = results.length < total;
  const totalValue = stats?.valor_sum ?? null;

  const displayResults = useMemo(() => {
    if (!pinnedDoc) return results;
    const pinnedId = pinnedDoc.doc_id;
    return [pinnedDoc, ...results.filter((row) => (row.doc_id ?? "") !== (pinnedId ?? ""))];
  }, [pinnedDoc, results]);

  /**
   * Textos franceses que a página mostra: objeto/natureza/procedimento/forma de
   * preço/tipo de local dos resultados e os rótulos das facetas correspondentes.
   */
  const textosParaTraduzir = useMemo(() => {
    const conjunto = new Set<string>();
    const juntar = (valor?: string | null) => {
      const limpo = valor ? chaveTraducao(valor) : "";
      if (limpo) conjunto.add(limpo);
    };
    for (const item of displayResults) {
      juntar(item.objet);
      juntar(item.nature);
      juntar(item.procedure);
      juntar(item.forme_prix);
      juntar(item.lieu_execution_type);
    }
    for (const chave of ["nature", "procedure", "forme_prix", "lieu_execution_type"] as const) {
      for (const valor of facets[chave] ?? []) juntar(String(valor.label ?? valor.value));
    }
    return [...conjunto];
  }, [displayResults, facets]);

  useEffect(() => {
    if (!traduzir) return;
    const emFalta = textosParaTraduzir.filter((texto) => !(texto in traducoesRef.current));
    if (!emFalta.length) return;
    let ativo = true;
    setATraduzir(true);
    setErroTraducao(null);
    translateContratosFr(emFalta.slice(0, 150))
      .then((resposta) => {
        if (!ativo) return;
        traducoesRef.current = { ...traducoesRef.current, ...(resposta.translations ?? {}) };
        setTraducoes(traducoesRef.current);
        setIaTraducao(resposta.ai ?? null);
      })
      .catch((err: unknown) => {
        if (ativo) setErroTraducao(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (ativo) setATraduzir(false);
      });
    return () => {
      ativo = false;
    };
  }, [traduzir, textosParaTraduzir]);

  const alternarTraducao = () => {
    setTraduzir((atual) => {
      const proximo = !atual;
      try {
        window.localStorage.setItem(TRADUZIR_KEY, proximo ? "1" : "0");
      } catch {
        /* sem localStorage: a escolha vale só para esta sessão */
      }
      return proximo;
    });
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Landmark size={22} className="text-amber-400" />
            Contratos França
          </h1>
          <p className="text-sm text-muted-foreground">
            Données Essentielles de la Commande Publique (DECP) — data.gouv.fr
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
            onClick={alternarTraducao}
            title="Traduzir os textos franceses (objeto, natureza, procedimento) para português com o fornecedor de IA configurado"
            className={`px-3 py-2 rounded-xl border transition text-sm flex items-center gap-2 ${
              traduzir ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-border hover:bg-white/5"
            }`}
          >
            {aTraduzir ? <Loader2 size={15} className="animate-spin" /> : <Languages size={15} />}
            {traduzir ? "Traduzir (IA) · ligado" : "Traduzir (IA)"}
          </button>
          <button
            onClick={() => setImportOpen((v) => !v)}
            className="px-3 py-2 rounded-xl bg-secondary text-secondary-foreground hover:bg-accent transition text-sm flex items-center gap-2"
          >
            <Database size={15} /> Importar DECP
          </button>
          {onSwitchView && (
            <button
              onClick={onSwitchView}
              className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm"
            >
              Fechar
            </button>
          )}
          {onSwitchMap && (
            <button
              onClick={onSwitchMap}
              className="px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2"
            >
              <MapPin size={15} /> Mapa
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

      {erroTraducao ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span className="flex-1">Tradução por IA indisponível: {erroTraducao}</span>
        </div>
      ) : traduzir ? (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/5 px-3 py-2 text-xs text-emerald-200/90">
          {aTraduzir ? <Loader2 size={13} className="animate-spin" /> : <Languages size={13} />}
          {aTraduzir
            ? "A traduzir os textos franceses…"
            : `Textos em português${iaTraducao?.provider_label ? ` (IA: ${iaTraducao.provider_label}${iaTraducao.model ? ` · ${iaTraducao.model}` : ""})` : ""}`}
          <span className="text-emerald-200/60">· passe o rato para ver o texto original</span>
        </div>
      ) : null}

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
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Valor total (filtro)</p>
          <p className="text-3xl font-bold stat-value text-glow-amber mt-1 whitespace-nowrap">{formatMoneyCompact(totalValue)}</p>
          {stats?.valor_avg ? (
            <p className="text-xs text-muted-foreground mt-1">Média {formatMoney(stats.valor_avg)}</p>
          ) : null}
        </div>
        <div className="glass-card gradient-border rounded-2xl p-5 relative z-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Filtros ativos</p>
          <p className="text-3xl font-bold stat-value mt-1">{activeFilters.length}</p>
        </div>
      </div>

      {importOpen && (
        <div className="glass-card rounded-2xl p-5 mb-6">
          <h2 className="font-semibold mb-3 flex items-center gap-2">
            <Database size={17} /> Importar DECP para o Elasticsearch
          </h2>
          <p className="text-xs text-muted-foreground mb-3">
            Lê <code>data/contratos-franca/decp-*.json</code>, normaliza e indexa em <code>contratos_fr</code>.
          </p>
          <div className="flex flex-wrap gap-3 items-end">
            <label className="flex flex-col gap-1 text-sm">
              Ficheiro
              <select
                className="bg-background border border-border rounded-lg px-3 py-2 text-sm min-w-[220px]"
                value={importFilename}
                onChange={(e) => setImportFilename(e.target.value)}
              >
                <option value="">—</option>
                {(meta?.sources ?? []).map((s) => (
                  <option key={s.filename} value={s.filename}>
                    {s.filename} ({s.size_mb} MB)
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Limite (opcional)
              <input
                type="number"
                className="bg-background border border-border rounded-lg px-3 py-2 text-sm w-32"
                value={importLimit}
                onChange={(e) => setImportLimit(e.target.value)}
                placeholder="todos"
              />
            </label>
            <button
              onClick={() => void startImport()}
              className="px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition text-sm"
            >
              Importar
            </button>
          </div>
          {importError && <p className="text-sm text-red-400 mt-3">{importError}</p>}
          {jobs.length > 0 && (
            <div className="mt-4 space-y-2">
              {jobs.slice(0, 5).map((j) => (
                <div key={j.id} className="text-xs flex items-center gap-2">
                  <span
                    className={`inline-block w-2 h-2 rounded-full ${
                      j.state === "done" ? "bg-green-400" : j.state === "error" ? "bg-red-400" : "bg-amber-400 animate-pulse"
                    }`}
                  />
                  {j.filename ?? importFilename}: {j.state} — {j.message ?? `${j.indexed ?? 0}/${j.docs ?? 0}`}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-6">
        <aside className="w-full lg:w-72 shrink-0 space-y-4">
          <div className="glass-card rounded-2xl p-4">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <Filter size={16} /> Filtros
            </h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground">Ano</label>
                <select
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={ano}
                  onChange={(e) => {
                    const v = e.target.value;
                    setAno(v === "" ? "" : Number(v));
                    void doSearch(true, { ...buildRequest(0), ano: v === "" ? undefined : Number(v) });
                  }}
                >
                  <option value="">Todos</option>
                  {(status?.years ?? []).map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Natureza</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={nature}
                  onChange={(e) => setNature(e.target.value)}
                  placeholder="Marché, Marché de partenariat..."
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Procedimento</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={procedure}
                  onChange={(e) => setProcedure(e.target.value)}
                  placeholder="Appel d'offres ouvert..."
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">ID acheteur</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={acheteurId}
                  onChange={(e) => setAcheteurId(e.target.value)}
                  placeholder="SIRET/SIREN"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">ID adjudicatário</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={adjudicatarioId}
                  onChange={(e) => setAdjudicatarioId(e.target.value)}
                  placeholder="SIRET"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">CPV</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={cpv}
                  onChange={(e) => setCpv(e.target.value)}
                  placeholder="90500000-2"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-muted-foreground">Valor ≥</label>
                  <input
                    type="number"
                    className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                    value={minValue}
                    onChange={(e) => setMinValue(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Valor ≤</label>
                  <input
                    type="number"
                    className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                    value={maxValue}
                    onChange={(e) => setMaxValue(e.target.value)}
                  />
                </div>
              </div>
              <button
                onClick={() => void doSearch(true)}
                className="w-full px-3 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition text-sm"
              >
                Aplicar filtros
              </button>
              <button
                onClick={clearFilters}
                className="w-full px-3 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm"
              >
                Limpar
              </button>
            </div>
          </div>

          <div className="glass-card rounded-2xl p-4">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <BarChart3 size={16} /> Facetas
            </h2>
            <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
              {FACET_CONFIG.map(({ key, label }) => {
                const values = facets[key] ?? [];
                const [open, setOpen] = useState(true);
                if (!values.length) return null;
                return (
                  <div key={key}>
                    <button
                      onClick={() => setOpen((v) => !v)}
                      className="w-full flex items-center justify-between text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                      {label} ({values.length})
                      {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                    {open && (
                      <ul className="mt-1 space-y-1">
                        {values.slice(0, 12).map((v) => (
                          <li key={String(v.value)}>
                            <button
                              onClick={() => applyFacet(key, v.value)}
                              className="w-full text-left text-sm px-2 py-1 rounded hover:bg-white/5 flex justify-between"
                            >
                              <span className="truncate cursor-help" title={v.label ?? String(v.value)}>
                                {tr(v.label ?? String(v.value))}
                              </span>
                              <span className="text-muted-foreground text-xs">{v.count.toLocaleString("pt-PT")}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </aside>

        <main className="flex-1 min-w-0">
          <div className="relative mb-4">
            <div className="flex items-center gap-2 glass-card rounded-2xl px-4 py-2">
              <Search size={18} className="text-muted-foreground" />
              <input
                ref={searchInputRef}
                type="text"
                className="flex-1 bg-transparent border-none outline-none text-sm"
                placeholder="Pesquisar objetos, CPV, procedimentos..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setShowSuggestions(false);
                    void doSearch(true);
                  }
                }}
              />
              {query && (
                <button onClick={() => { setQuery(""); void doSearch(true, { size: PAGE_SIZE, from: 0, with_facets: true }); }}>
                  <X size={16} className="text-muted-foreground" />
                </button>
              )}
              <button
                onClick={() => setAdvancedOpen((v) => !v)}
                className="text-xs flex items-center gap-1 text-muted-foreground hover:text-foreground"
              >
                <Filter size={14} /> Avançado
              </button>
              <button
                onClick={() => void doSearch(true)}
                className="px-3 py-1.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition text-sm"
              >
                Pesquisar
              </button>
            </div>
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-10 w-full mt-1 glass-card rounded-2xl p-2 shadow-lg">
                {suggestions.map((s) => (
                  <button
                    key={`${s.type}-${s.text}`}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-white/5 rounded-xl flex items-center gap-2"
                    onClick={() => {
                      setQuery(s.text);
                      setShowSuggestions(false);
                      void doSearch(true, { ...buildRequest(0), q: s.text });
                    }}
                  >
                    <span className="text-xs uppercase text-muted-foreground">{s.type}</span>
                    <span className="truncate">{s.text}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{s.count.toLocaleString("pt-PT")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {advancedOpen && (
            <div className="glass-card rounded-2xl p-4 mb-4 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-muted-foreground">Data de</label>
                <input
                  type="date"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Data até</label>
                <input
                  type="date"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Campo data</label>
                <select
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={dateField}
                  onChange={(e) => setDateField(e.target.value)}
                >
                  <option value="date_publication">Publicação</option>
                  <option value="date_notification">Notificação</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Ordenar</label>
                <select
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                >
                  <option value="relevance">Relevância</option>
                  <option value="montant">Valor</option>
                  <option value="date_publication">Data publicação</option>
                  <option value="date_notification">Data notificação</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Código local</label>
                <input
                  type="text"
                  className="w-full bg-background border border-border rounded-lg px-2 py-1.5 text-sm mt-1"
                  value={lieuExecutionCode}
                  onChange={(e) => setLieuExecutionCode(e.target.value)}
                  placeholder="Código postal / NUTS"
                />
              </div>
            </div>
          )}

          {activeFilters.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {activeFilters.map((f) => (
                <span
                  key={f.field}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-primary/10 text-primary text-xs"
                >
                  {f.label}: {f.value}
                  <button onClick={() => removeFilter(f.field, f.clear)}>
                    <X size={12} />
                  </button>
                </span>
              ))}
              <button onClick={clearFilters} className="text-xs text-muted-foreground hover:text-foreground underline">
                Limpar todos
              </button>
            </div>
          )}

          {error && (
            <div className="glass-card rounded-2xl p-4 mb-4 border-red-400/30 flex items-center gap-3">
              <Frown size={18} className="text-red-400" />
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}

          {loading && results.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 size={32} className="animate-spin text-primary mb-3" />
              <p className="text-sm text-muted-foreground">A pesquisar contratos de França...</p>
            </div>
          )}

          {!loading && results.length === 0 && !error && (
            <div className="flex flex-col items-center justify-center py-16">
              <Search size={32} className="text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">Nenhum contrato encontrado.</p>
            </div>
          )}

          <div className="space-y-3">
            {displayResults.map((item) => {
              const docId = item.doc_id ?? item.id ?? "";
              const open = openDocId === docId;
              return (
                <div key={docId} className="glass-card rounded-2xl p-4">
                  <div className="flex flex-col md:flex-row md:items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-sm leading-snug" title={item.objet ?? undefined}>
                        {tr(item.objet) || "—"}
                      </h3>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground mt-2">
                        <span title={item.nature ?? undefined}>{tr(item.nature) || "—"}</span>
                        <span title={item.procedure ?? undefined}>{tr(item.procedure) || "—"}</span>
                        <span>Publicação: {formatDate(item.date_publication)}</span>
                        <span>Notificação: {formatDate(item.date_notification)}</span>
                        <span className="font-semibold text-foreground">{formatMoney(item.montant ?? item.valor)}</span>
                      </div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {item.code_cpv && (
                          <span className="px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground text-xs">
                            CPV {item.code_cpv}
                          </span>
                        )}
                        {item.forme_prix && (
                          <span
                            className="px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground text-xs cursor-help"
                            title={item.forme_prix}
                          >
                            {tr(item.forme_prix)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setOpenDocId(open ? null : docId)}
                        className="px-3 py-1.5 rounded-xl border border-border hover:bg-white/5 text-xs flex items-center gap-1"
                      >
                        {open ? "Fechar" : "Detalhe"}
                        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                      <a
                        href={`/contracts-fr/${encodeURIComponent(docId)}`}
                        target="_blank"
                        rel="noreferrer"
                        className="p-1.5 rounded-xl border border-border hover:bg-white/5"
                        title="Abrir em nova aba"
                      >
                        <ExternalLink size={14} />
                      </a>
                    </div>
                  </div>
                  {open && (
                    <div className="mt-4 pt-4 border-t border-border text-sm space-y-2">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <span className="text-xs text-muted-foreground">ID</span>
                          <p>{item.id}</p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Doc ID</span>
                          <p className="break-all">{item.doc_id}</p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Acheteur</span>
                          <p>{item.acheteur_nom || item.acheteur_id || "—"}</p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Adjudicatário</span>
                          <p>
                            {item.adjudicatario_nom || item.adjudicatario_id || "—"} {item.adjudicatario_type_identifiant ? `(${item.adjudicatario_type_identifiant})` : ""}
                          </p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Local execução</span>
                          <p title={item.lieu_execution_type ?? undefined}>
                            {item.lieu_execution_code || "—"}{" "}
                            {item.lieu_execution_type ? `(${tr(item.lieu_execution_type)})` : ""}
                          </p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Duração</span>
                          <p>{item.duree_mois ? `${item.duree_mois} meses` : "—"}</p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Ofertas recebidas</span>
                          <p>{item.offres_recues ?? "—"}</p>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground">Fonte</span>
                          <p>{item.source || item.fonte || "—"}</p>
                        </div>
                      </div>
                      {item.cpv && item.cpv.length > 0 && (
                        <div>
                          <span className="text-xs text-muted-foreground">CPV</span>
                          <p>{item.cpv.map((c) => `${c.code}${c.nom ? ` — ${c.nom}` : ""}`).join("; ")}</p>
                        </div>
                      )}
                      {item.titulaires && item.titulaires.length > 0 && (
                        <div>
                          <span className="text-xs text-muted-foreground">Titulares</span>
                          <ul className="list-disc list-inside">
                            {item.titulaires.map((t, i) => (
                              <li key={i}>
                                {t.nom || t.id || "—"} {t.type_identifiant ? `(${t.type_identifiant})` : ""}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {hasMore && (
            <div className="flex justify-center mt-6">
              <button
                onClick={() => void doSearch(false)}
                disabled={loadingMore}
                className="px-4 py-2 rounded-xl border border-border hover:bg-white/5 transition text-sm flex items-center gap-2 disabled:opacity-50"
              >
                {loadingMore && <Loader2 size={16} className="animate-spin" />}
                Carregar mais
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
