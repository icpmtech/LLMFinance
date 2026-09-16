import { useState, useEffect, useRef, useCallback } from "react";
import {
  Search,
  Building2,
  Loader2,
  Frown,
  Filter,
  X,
  Database,
  Sparkles,
  Award,
  MapPin,
  HandCoins,
  Briefcase,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  Globe,
} from "lucide-react";
import {
  searchEntities,
  getEntityStats,
  getEntityDetail,
  ingestEntities,
  enrichCompany,
} from "../api";
import type {
  EntityItem,
  EntityStats,
  EntityDetail,
  EntitySearchRequest,
  EntitySortField,
  CompanyEnrichmentResponse,
} from "../types";

interface EntitiesSearchPageProps {
  onSelectCompany?: (nif: string) => void;
  onSwitchDashboard?: () => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function formatCompactPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (n >= 1_000) return `${(n / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} K€`;
  return formatPrice(n);
}

const SORT_OPTIONS: { value: EntitySortField; label: string }[] = [
  { value: "total_value", label: "Valor total" },
  { value: "contracts_count", label: "Nº de contratos" },
  { value: "name", label: "Nome" },
  { value: "as_adjudicante_value", label: "Valor como adjudicante" },
  { value: "as_adjudicatario_count", label: "Contratos como adjudicatário" },
  { value: "as_adjudicante_count", label: "Contratos como adjudicante" },
];

export function EntitiesSearchPage({ onSelectCompany, onSwitchDashboard }: EntitiesSearchPageProps) {
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("");
  const [onlyWithNif, setOnlyWithNif] = useState(false);
  const [role, setRole] = useState<EntitySearchRequest["role"]>("all");
  const [minContracts, setMinContracts] = useState("");
  const [minValue, setMinValue] = useState("");
  const [sortBy, setSortBy] = useState<EntitySortField>("total_value");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const size = 25;
  const [items, setItems] = useState<EntityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [stats, setStats] = useState<EntityStats | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const [expandedNif, setExpandedNif] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, EntityDetail>>({});
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null);
  const [enriching, setEnriching] = useState<string | null>(null);
  const [enrichResult, setEnrichResult] = useState<Record<string, CompanyEnrichmentResponse>>({});

  const loadMoreRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  // Próximo offset a pedir; mantido em ref para a paginação não depender do estado.
  const nextFromRef = useRef(0);

  const buildRequest = useCallback(
    (nextFrom: number): EntitySearchRequest => ({
      q: query.trim() || undefined,
      country: country || undefined,
      only_with_nif: onlyWithNif || undefined,
      role: role || "all",
      min_contracts: minContracts ? parseInt(minContracts, 10) : undefined,
      min_value: minValue ? parseFloat(minValue) : undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      size,
      from: nextFrom,
    }),
    [query, country, onlyWithNif, role, minContracts, minValue, sortBy, sortOrder],
  );

  const doSearch = useCallback(
    async (resetFrom = true) => {
      const nextFrom = resetFrom ? 0 : nextFromRef.current;
      if (resetFrom) {
        setLoading(true);
        nextFromRef.current = 0;
      } else {
        setLoadingMore(true);
      }
      setError(null);
      const reqId = ++requestIdRef.current;
      try {
        const data = await searchEntities(buildRequest(nextFrom));
        // Ignorar respostas antigas se entretanto houve nova pesquisa.
        if (reqId !== requestIdRef.current) return;
        const batch = data.items ?? [];
        setItems((prev) => (resetFrom ? batch : [...prev, ...batch]));
        setTotal(data.total ?? 0);
        nextFromRef.current = nextFrom + batch.length;
        if (data.error) setError(data.error);
      } catch (err) {
        if (reqId !== requestIdRef.current) return;
        if (resetFrom) {
          setItems([]);
          setTotal(0);
        }
        setError(err instanceof Error ? err.message : "Erro na pesquisa");
      } finally {
        if (reqId === requestIdRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [buildRequest],
  );

  useEffect(() => {
    getEntityStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  useEffect(() => {
    doSearch(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [country, onlyWithNif, role, sortBy, sortOrder]);

  useEffect(() => {
    const el = loadMoreRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (first.isIntersecting && items.length < total && !loading && !loadingMore) {
          doSearch(false);
        }
      },
      { rootMargin: "240px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [items.length, total, loading, loadingMore, doSearch]);

  const activeFilters = [country, onlyWithNif, role !== "all", minContracts, minValue].filter(Boolean).length;

  const clearFilters = () => {
    setQuery("");
    setCountry("");
    setOnlyWithNif(false);
    setRole("all");
    setMinContracts("");
    setMinValue("");
    setSortBy("total_value");
    setSortOrder("desc");
  };

  const toggleRow = async (item: EntityItem) => {
    const key = item.doc_id ?? item.nif ?? item.name;
    if (expandedNif === key) {
      setExpandedNif(null);
      return;
    }
    setExpandedNif(key);
    if (item.nif && !details[item.nif]) {
      setLoadingDetail(key);
      try {
        const detail = await getEntityDetail(item.nif);
        setDetails((prev) => ({ ...prev, [item.nif as string]: detail }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao obter a ficha");
      } finally {
        setLoadingDetail(null);
      }
    }
  };

  const runEnrich = async (item: EntityItem) => {
    if (!item.nif) return;
    setEnriching(item.nif);
    setError(null);
    try {
      const result = await enrichCompany(item.nif, {
        include_trademarks: true,
        include_firmas: true,
        max_trademarks: 40,
        max_firmas: 15,
        trademark_detail_limit: 8,
      });
      setEnrichResult((prev) => ({ ...prev, [item.nif as string]: result }));
      // Recarregar a ficha para mostrar marcas/firmas atualizadas.
      const detail = await getEntityDetail(item.nif);
      setDetails((prev) => ({ ...prev, [item.nif as string]: detail }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro no enriquecimento");
    } finally {
      setEnriching(null);
    }
  };

  const runImport = async () => {
    setImporting(true);
    setImportError(null);
    setImportMsg(null);
    try {
      const res = await ingestEntities({ refresh: true });
      setImportMsg(res.message ?? `${res.indexed_count} entidades importadas`);
      const refreshed = await getEntityStats().catch(() => null);
      if (refreshed) {
        setStats(refreshed);
        setTotal(refreshed.total);
      }
      doSearch(true);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Erro na importação");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="eiq-page" style={{ padding: "1.5rem", maxWidth: 1400, margin: "0 auto" }}>
      {/* Cabeçalho */}
      <header style={{ marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <h1 style={{ display: "flex", alignItems: "center", gap: ".6rem", fontSize: "1.5rem", margin: 0 }}>
              <Building2 size={26} />
              Pesquisa de Empresas
            </h1>
            <p style={{ margin: ".35rem 0 0", opacity: 0.75, fontSize: ".9rem" }}>
              Cadastro de entidades do portal base, com enriquecimento de marcas (INPI) e firmas (RNPC).
            </p>
          </div>
          <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={runImport}
              disabled={importing}
              title="Importar data/entidades-gov-portal-base/entidades.json para o Elasticsearch"
              style={{ display: "flex", alignItems: "center", gap: ".4rem", padding: ".5rem .85rem", borderRadius: 8, cursor: importing ? "wait" : "pointer" }}
            >
              {importing ? <Loader2 size={16} className="spin" /> : <Database size={16} />}
              {importing ? "A importar…" : "Importar entidades.json"}
            </button>
            {onSwitchDashboard && (
              <button type="button" onClick={onSwitchDashboard} style={{ padding: ".5rem .85rem", borderRadius: 8, cursor: "pointer" }}>
                Dashboard
              </button>
            )}
          </div>
        </div>

        {importMsg && (
          <div style={{ marginTop: ".75rem", padding: ".6rem .8rem", borderRadius: 8, background: "rgba(34,197,94,.12)", border: "1px solid rgba(34,197,94,.35)", fontSize: ".85rem" }}>
            {importMsg}
          </div>
        )}
        {importError && (
          <div style={{ marginTop: ".75rem", padding: ".6rem .8rem", borderRadius: 8, background: "rgba(239,68,68,.12)", border: "1px solid rgba(239,68,68,.35)", fontSize: ".85rem" }}>
            {importError}
          </div>
        )}
      </header>

      {/* KPIs */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: ".75rem", marginBottom: "1.25rem" }}>
          {[
            { label: "Entidades", value: stats.total.toLocaleString("pt-PT"), icon: <Building2 size={16} /> },
            { label: "Com NIF", value: stats.with_nif.toLocaleString("pt-PT"), icon: <Award size={16} /> },
            { label: "Contratos", value: stats.total_contracts.toLocaleString("pt-PT"), icon: <Briefcase size={16} /> },
            { label: "Valor total", value: formatCompactPrice(stats.total_value), icon: <HandCoins size={16} /> },
            { label: "Adjudicantes", value: stats.adjudicante_count.toLocaleString("pt-PT"), icon: <Globe size={16} /> },
            { label: "Adjudicatários", value: stats.adjudicatario_count.toLocaleString("pt-PT"), icon: <Globe size={16} /> },
          ].map((kpi) => (
            <div key={kpi.label} style={{ padding: ".7rem .85rem", borderRadius: 10, border: "1px solid rgba(148,163,184,.25)", background: "rgba(148,163,184,.06)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: ".35rem", fontSize: ".75rem", opacity: 0.75 }}>
                {kpi.icon}
                {kpi.label}
              </div>
              <div style={{ fontSize: "1.05rem", fontWeight: 600, marginTop: ".2rem" }}>{kpi.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Barra de pesquisa */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          doSearch(true);
        }}
        style={{ display: "flex", gap: ".5rem", marginBottom: ".75rem", flexWrap: "wrap" }}
      >
        <div style={{ position: "relative", flex: "1 1 320px", minWidth: 240 }}>
          <Search size={16} style={{ position: "absolute", left: ".7rem", top: "50%", transform: "translateY(-50%)", opacity: 0.6 }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Nome da empresa ou NIF (ex.: PRIMAVERA, SONAE, 503140600)"
            aria-label="Pesquisar empresa"
            style={{ width: "100%", padding: ".6rem .8rem .6rem 2.1rem", borderRadius: 8, border: "1px solid rgba(148,163,184,.35)", background: "transparent", color: "inherit" }}
          />
        </div>
        <button type="submit" disabled={loading} style={{ padding: ".6rem 1.1rem", borderRadius: 8, cursor: loading ? "wait" : "pointer", display: "flex", alignItems: "center", gap: ".4rem" }}>
          {loading ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
          Pesquisar
        </button>
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          style={{ padding: ".6rem .9rem", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: ".4rem" }}
        >
          <Filter size={16} />
          Filtros
          {activeFilters > 0 && (
            <span style={{ background: "rgba(59,130,246,.25)", borderRadius: 999, padding: "0 .45rem", fontSize: ".75rem" }}>{activeFilters}</span>
          )}
          {advancedOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </form>

      {/* Filtros avançados */}
      {advancedOpen && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: ".75rem", padding: ".9rem", borderRadius: 10, border: "1px solid rgba(148,163,184,.25)", marginBottom: "1rem" }}>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            País
            <select value={country} onChange={(e) => setCountry(e.target.value)} style={{ padding: ".45rem", borderRadius: 6 }}>
              <option value="">Todos</option>
              {(stats?.countries ?? []).filter((c) => c.country).map((c) => (
                <option key={c.country} value={c.country}>
                  {c.country} ({c.count.toLocaleString("pt-PT")})
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            Papel
            <select value={role} onChange={(e) => setRole(e.target.value as EntitySearchRequest["role"])} style={{ padding: ".45rem", borderRadius: 6 }}>
              <option value="all">Todos</option>
              <option value="adjudicante">Adjudicante</option>
              <option value="adjudicatario">Adjudicatário</option>
            </select>
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            Mín. contratos
            <input type="number" min={0} value={minContracts} onChange={(e) => setMinContracts(e.target.value)} placeholder="ex.: 10" style={{ padding: ".45rem", borderRadius: 6, border: "1px solid rgba(148,163,184,.35)", background: "transparent", color: "inherit" }} />
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            Mín. valor (€)
            <input type="number" min={0} value={minValue} onChange={(e) => setMinValue(e.target.value)} placeholder="ex.: 1000000" style={{ padding: ".45rem", borderRadius: 6, border: "1px solid rgba(148,163,184,.35)", background: "transparent", color: "inherit" }} />
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            Ordenar por
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as EntitySortField)} style={{ padding: ".45rem", borderRadius: 6 }}>
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".25rem" }}>
            Direção
            <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value as "asc" | "desc")} style={{ padding: ".45rem", borderRadius: 6 }}>
              <option value="desc">Descendente</option>
              <option value="asc">Ascendente</option>
            </select>
          </label>
          <label style={{ fontSize: ".8rem", display: "flex", alignItems: "center", gap: ".4rem", alignSelf: "end", paddingBottom: ".45rem" }}>
            <input type="checkbox" checked={onlyWithNif} onChange={(e) => setOnlyWithNif(e.target.checked)} />
            Apenas com NIF válido
          </label>
          <button type="button" onClick={clearFilters} style={{ alignSelf: "end", padding: ".45rem .8rem", borderRadius: 6, cursor: "pointer", display: "flex", alignItems: "center", gap: ".35rem", justifyContent: "center" }}>
            <X size={14} />
            Limpar
          </button>
        </div>
      )}

      {/* Resultado */}
      {error && (
        <div style={{ padding: ".7rem .85rem", borderRadius: 8, background: "rgba(239,68,68,.12)", border: "1px solid rgba(239,68,68,.35)", marginBottom: "1rem", fontSize: ".85rem" }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: ".6rem", fontSize: ".85rem", opacity: 0.8 }}>
        <span>
          {loading ? "A pesquisar…" : `${total.toLocaleString("pt-PT")} empresas`}
          {items.length > 0 && !loading && ` · a mostrar ${items.length}`}
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: ".3rem" }}>
          <ArrowUpDown size={13} />
          {SORT_OPTIONS.find((o) => o.value === sortBy)?.label} ({sortOrder === "desc" ? "↓" : "↑"})
        </span>
      </div>

      {/* Lista */}
      {loading && items.length === 0 ? (
        <div style={{ display: "flex", alignItems: "center", gap: ".5rem", padding: "2rem", justifyContent: "center", opacity: 0.7 }}>
          <Loader2 size={18} className="spin" /> A carregar empresas…
        </div>
      ) : items.length === 0 ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: ".5rem", padding: "2.5rem", opacity: 0.7 }}>
          <Frown size={30} />
          <span>Sem resultados. Tente outro termo ou importe o `entidades.json`.</span>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: ".5rem" }}>
          {items.map((item) => {
            const key = item.doc_id ?? item.nif ?? item.name;
            const isOpen = expandedNif === key;
            const detail = item.nif ? details[item.nif] : undefined;
            const enrich = item.nif ? enrichResult[item.nif] : undefined;
            return (
              <div key={key} style={{ border: "1px solid rgba(148,163,184,.25)", borderRadius: 10, overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", gap: ".75rem", padding: ".7rem .85rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => toggleRow(item)}
                    style={{ flex: "1 1 320px", textAlign: "left", background: "none", border: "none", cursor: "pointer", color: "inherit", padding: 0, minWidth: 220 }}
                  >
                    <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: ".4rem" }}>
                      {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      {item.name}
                    </div>
                    <div style={{ fontSize: ".78rem", opacity: 0.7, display: "flex", gap: ".75rem", flexWrap: "wrap", marginTop: ".2rem" }}>
                      <span>{item.nif ? `NIF ${item.nif}` : "sem NIF"}</span>
                      {item.country && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: ".2rem" }}>
                          <MapPin size={11} />
                          {item.country}
                        </span>
                      )}
                      {item.as_adjudicante_count > 0 && <span>adjudicante</span>}
                      {item.as_adjudicatario_count > 0 && <span>adjudicatário</span>}
                    </div>
                  </button>
                  <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: ".7rem", opacity: 0.65 }}>contratos</div>
                      <div style={{ fontWeight: 600 }}>{item.contracts_count.toLocaleString("pt-PT")}</div>
                    </div>
                    <div style={{ textAlign: "right", minWidth: 120 }}>
                      <div style={{ fontSize: ".7rem", opacity: 0.65 }}>valor total</div>
                      <div style={{ fontWeight: 600 }}>{formatCompactPrice(item.total_value)}</div>
                    </div>
                    <div style={{ display: "flex", gap: ".35rem" }}>
                      {item.nif && (
                        <button
                          type="button"
                          onClick={() => runEnrich(item)}
                          disabled={enriching === item.nif}
                          title="Obter marcas (INPI) e firmas (RNPC) e guardar na ficha"
                          style={{ display: "flex", alignItems: "center", gap: ".3rem", padding: ".4rem .7rem", borderRadius: 7, cursor: enriching === item.nif ? "wait" : "pointer", fontSize: ".8rem" }}
                        >
                          {enriching === item.nif ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                          Enriquecer
                        </button>
                      )}
                      {item.nif && onSelectCompany && (
                        <button type="button" onClick={() => onSelectCompany(item.nif as string)} style={{ padding: ".4rem .7rem", borderRadius: 7, cursor: "pointer", fontSize: ".8rem" }}>
                          Ficha
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {isOpen && (
                  <div style={{ padding: ".85rem", borderTop: "1px solid rgba(148,163,184,.2)", background: "rgba(148,163,184,.04)", fontSize: ".85rem" }}>
                    {loadingDetail === key && (
                      <div style={{ display: "flex", alignItems: "center", gap: ".4rem", opacity: 0.7 }}>
                        <Loader2 size={14} className="spin" /> A carregar ficha…
                      </div>
                    )}

                    {enrich && (
                      <div style={{ marginBottom: ".7rem", padding: ".55rem .7rem", borderRadius: 8, background: "rgba(59,130,246,.1)", border: "1px solid rgba(59,130,246,.3)", fontSize: ".8rem" }}>
                        <b>Enriquecimento concluído</b>
                        {" · "}
                        marcas: {enrich.trademarks?.indexed_count ?? 0} indexadas
                        {" · "}
                        firmas: {enrich.firmas?.indexed_count ?? 0} indexadas
                        {enrich.trademarks?.error && <div>Erro marcas: {enrich.trademarks.error}</div>}
                        {enrich.firmas?.error && <div>Erro firmas: {enrich.firmas.error}</div>}
                      </div>
                    )}

                    {detail ? (
                      <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
                        <div>
                          <h4 style={{ display: "flex", alignItems: "center", gap: ".35rem", margin: "0 0 .5rem", fontSize: ".9rem" }}>
                            <Award size={15} /> Marcas INPI ({detail.trademarks_total ?? 0})
                          </h4>
                          {(detail.trademarks ?? []).length === 0 ? (
                            <p style={{ opacity: 0.65, margin: 0, fontSize: ".8rem" }}>
                              Sem marcas guardadas. Use «Enriquecer» para as obter.
                            </p>
                          ) : (
                            <ul style={{ margin: 0, paddingLeft: "1rem", display: "grid", gap: ".35rem" }}>
                              {(detail.trademarks ?? []).slice(0, 12).map((tm) => (
                                <li key={tm.doc_id ?? `${tm.nord}`}>
                                  <b>{tm.mark_name ?? "—"}</b>
                                  {tm.current_phase ? ` · ${tm.current_phase}` : ""}
                                  {tm.application_date ? ` · ${tm.application_date}` : ""}
                                  {tm.holder_name ? ` · titular: ${tm.holder_name}` : ""}
                                  {typeof tm.holder_similarity === "number" && (
                                    <span style={{ opacity: 0.7 }}> · semelhança {Math.round(tm.holder_similarity * 100)}%</span>
                                  )}
                                  {tm.nice_classes && tm.nice_classes.length > 0 && (
                                    <span style={{ opacity: 0.7 }}> · classes {tm.nice_classes.map((c) => c.split(":")[0]).join(", ")}</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <div>
                          <h4 style={{ display: "flex", alignItems: "center", gap: ".35rem", margin: "0 0 .5rem", fontSize: ".9rem" }}>
                            <Building2 size={15} /> Firmas RNPC ({detail.firmas_total ?? 0})
                          </h4>
                          {(detail.firmas ?? []).length === 0 ? (
                            <p style={{ opacity: 0.65, margin: 0, fontSize: ".8rem" }}>
                              Sem firmas guardadas. Use «Enriquecer» para as obter.
                            </p>
                          ) : (
                            <ul style={{ margin: 0, paddingLeft: "1rem", display: "grid", gap: ".35rem" }}>
                              {(detail.firmas ?? []).slice(0, 12).map((f) => (
                                <li key={f.doc_id ?? `${f.nome}-${f.nipc ?? ""}`}>
                                  <b>{f.nome ?? "—"}</b>
                                  {f.nipc ? ` · NIF ${f.nipc}` : ""}
                                  {f.concelho_sede ? ` · ${f.concelho_sede}` : ""}
                                  {f.cae_principal ? ` · CAE ${f.cae_principal}` : ""}
                                  {typeof f.score === "number" ? ` · ${f.score}%` : ""}
                                  {typeof f.name_similarity === "number" && (
                                    <span style={{ opacity: 0.7 }}> · semelhança {Math.round(f.name_similarity * 100)}%</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <div style={{ gridColumn: "1 / -1", display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: ".8rem", opacity: 0.8 }}>
                          <span>Valor como adjudicante: {formatPrice(detail.as_adjudicante_value)}</span>
                          <span>Contratos como adjudicante: {detail.as_adjudicante_count}</span>
                          <span>Contratos como adjudicatário: {detail.as_adjudicatario_count}</span>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: ".3rem" }}>
                            <RefreshCw size={12} /> {detail.ingested_at?.slice(0, 19).replace("T", " ") ?? "—"}
                          </span>
                        </div>
                      </div>
                    ) : (
                      loadingDetail !== key && !enrich && (
                        <p style={{ opacity: 0.7, margin: 0, fontSize: ".8rem" }}>
                          {item.nif
                            ? "Abra «Enriquecer» para obter marcas do INPI e firmas do RNPC."
                            : "Esta entidade não tem NIF válido, pelo que não pode ser enriquecida automaticamente."}
                        </p>
                      )
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <div ref={loadMoreRef} style={{ height: 1 }} />
          {loadingMore && (
            <div style={{ display: "flex", alignItems: "center", gap: ".4rem", justifyContent: "center", padding: ".8rem", opacity: 0.7 }}>
              <Loader2 size={16} className="spin" /> A carregar mais…
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default EntitiesSearchPage;
