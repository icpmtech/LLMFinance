import { useState, useEffect, useMemo } from "react";
import { ArrowLeft, Search, FileText, MessageSquare, Loader2, Frown, Database } from "lucide-react";
import {
  getContractStatus,
  getContractYears,
  searchContracts,
  autocompleteContracts,
  chatContracts,
  ingestContracts,
} from "../api";
import type {
  ContractItem,
  ContractSearchRequest,
  ContractAutocompleteSuggestion,
  ContractChatSource,
} from "../types";

interface ContractsPageProps {
  onSwitchView: () => void;
}

function formatPrice(n?: number) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

function formatDate(d?: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("pt-PT");
}

function partyNames(parties: ContractItem["adjudicantes"]): string {
  return (
    parties
      ?.flatMap((p) => p.parsed?.map((x) => x.nome).filter(Boolean))
      .join(", ") || "—"
  );
}

function firstNif(parties: ContractItem["adjudicantes"]): string {
  return parties?.flatMap((p) => p.parsed?.map((x) => x.nif).filter(Boolean))[0] || "";
}

export function ContractsPage({ onSwitchView }: ContractsPageProps) {
  const [status, setStatus] = useState<{ total: number; years: number[] } | null>(null);
  const [years, setYears] = useState<{ available: number[]; indexed: { year: number; count: number }[] } | null>(null);
  const [query, setQuery] = useState("");
  const [year, setYear] = useState<number | "">("");
  const [entity, setEntity] = useState("");
  const [nif, setNif] = useState("");
  const [cpv, setCpv] = useState("");
  const [minPrice, setMinPrice] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState<string>("");
  const [from, setFrom] = useState(0);
  const size = 20;
  const [results, setResults] = useState<ContractItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ContractAutocompleteSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatAnswer, setChatAnswer] = useState<string | null>(null);
  const [chatSources, setChatSources] = useState<ContractChatSource[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  useEffect(() => {
    Promise.all([getContractStatus(), getContractYears()])
      .then(([s, y]) => {
        setStatus(s);
        setYears(y);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar estado"));
  }, []);

  const buildRequest = (): ContractSearchRequest => ({
    q: query.trim() || undefined,
    year: year || undefined,
    entity: entity.trim() || undefined,
    nif: nif.trim() || undefined,
    cpv_code: cpv.trim() || undefined,
    min_price: minPrice ? parseFloat(minPrice) : undefined,
    max_price: maxPrice ? parseFloat(maxPrice) : undefined,
    size,
    from,
  });

  const doSearch = async (resetFrom = true) => {
    const nextFrom = resetFrom ? 0 : from;
    setLoading(true);
    setError(null);
    try {
      const req = buildRequest();
      req.from = nextFrom;
      const data = await searchContracts(req);
      setResults(data.items ?? []);
      setTotal(data.total ?? 0);
      setFrom(nextFrom);
      if (data.error) setError(data.error);
    } catch (err) {
      setResults([]);
      setTotal(0);
      setError(err instanceof Error ? err.message : "Erro na pesquisa");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim().length > 1) {
        autocompleteContracts(query.trim(), 8)
          .then((d) => {
            setSuggestions(d.suggestions ?? []);
            setShowSuggestions(true);
          })
          .catch(() => setShowSuggestions(false));
      } else {
        setShowSuggestions(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const handleIngest = async (ingestYear?: number) => {
    if (!ingestYear && !year) {
      setError("Escolhe um ano para indexar");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await ingestContracts({ year: ingestYear || (year as number) });
      setError(`Indexados ${res.indexed_count} contratos. ${res.message || ""}`);
      const [s, y] = await Promise.all([getContractStatus(), getContractYears()]);
      setStatus(s);
      setYears(y);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao indexar");
    } finally {
      setLoading(false);
    }
  };

  const handleChat = async () => {
    if (!chatQuestion.trim()) return;
    setChatLoading(true);
    setChatAnswer(null);
    setChatSources([]);
    try {
      const data = await chatContracts({ question: chatQuestion.trim() });
      setChatAnswer(data.answer);
      setChatSources(data.sources ?? []);
    } catch (err) {
      setChatAnswer(`❌ ${err instanceof Error ? err.message : "Erro no chat"}`);
    } finally {
      setChatLoading(false);
    }
  };

  const pageCount = Math.ceil(total / size) || 1;
  const page = Math.floor(from / size) + 1;

  const indexedYears = useMemo(() => new Set(years?.indexed.map((y) => y.year) ?? []), [years]);

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="max-w-6xl mx-auto px-4 py-6">
        <button
          onClick={onSwitchView}
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition"
        >
          <ArrowLeft size={16} />
          Voltar
        </button>

        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <FileText size={28} />
              Contratos Públicos
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {status ? `${status.total.toLocaleString("pt-PT")} contratos indexados` : "A carregar estado..."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setChatOpen((v) => !v)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition"
            >
              <MessageSquare size={18} />
              {chatOpen ? "Fechar chat" : "Chat IA"}
            </button>
          </div>
        </div>

        {chatOpen && (
          <div className="mb-6 rounded-xl border border-border bg-card p-4">
            <h2 className="font-semibold mb-2 flex items-center gap-2">
              <MessageSquare size={18} /> Perguntar sobre contratos
            </h2>
            <div className="flex gap-2 mb-3">
              <input
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleChat()}
                placeholder="Ex: quantos contratos foram atribuídos à Mota-Engil em 2024?"
                className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                onClick={handleChat}
                disabled={chatLoading || !chatQuestion.trim()}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition disabled:opacity-50"
              >
                {chatLoading ? <Loader2 size={18} className="animate-spin" /> : "Perguntar"}
              </button>
            </div>
            {chatAnswer && (
              <div className="prose prose-sm max-w-none text-foreground">
                <p className="whitespace-pre-wrap">{chatAnswer}</p>
                {chatSources.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-muted-foreground mb-1">Fontes</p>
                    <div className="space-y-1">
                      {chatSources.map((s, i) => (
                        <div key={i} className="text-xs bg-muted rounded px-2 py-1">
                          {s.idcontrato} · {s.objectoContrato} · {formatPrice(s.precoContratual)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <div className="rounded-xl border border-border bg-card p-4 mb-6 space-y-4">
          <div className="relative">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onFocus={() => query.trim().length > 1 && setShowSuggestions(true)}
                  placeholder="Pesquisar por objeto, entidade, NIF, CPV..."
                  className="w-full pl-10 pr-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                />
                {showSuggestions && suggestions.length > 0 && (
                  <div className="absolute z-20 left-0 right-0 top-full mt-1 rounded-lg border border-border bg-card shadow-lg overflow-hidden">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          if (s.type === "cpv" && s.text.match(/^\d/)) {
                            setCpv(s.text);
                          } else {
                            setEntity(s.text);
                            setQuery(s.text);
                          }
                          setShowSuggestions(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-muted transition flex items-center justify-between"
                      >
                        <span className="truncate">{s.text}</span>
                        <span className="text-xs text-muted-foreground ml-2 shrink-0">{s.type} · {s.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => doSearch(true)}
                disabled={loading}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition disabled:opacity-50 flex items-center gap-2"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
                Pesquisar
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Ano</label>
              <select
                value={year}
                onChange={(e) => setYear(e.target.value === "" ? "" : parseInt(e.target.value))}
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">Todos</option>
                {years?.available.map((y) => (
                  <option key={y} value={y}>
                    {y} {indexedYears.has(y) ? "✓" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Entidade</label>
              <input
                value={entity}
                onChange={(e) => setEntity(e.target.value)}
                placeholder="Nome ou NIF"
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">NIF</label>
              <input
                value={nif}
                onChange={(e) => setNif(e.target.value)}
                placeholder="NIF da entidade"
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">CPV</label>
              <input
                value={cpv}
                onChange={(e) => setCpv(e.target.value)}
                placeholder="Código CPV"
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Preço mín. (€)</label>
              <input
                type="number"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                placeholder="0"
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Preço máx. (€)</label>
              <input
                type="number"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder="∞"
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div className="flex items-end gap-2">
              <button
                onClick={() => handleIngest()}
                disabled={loading || !year}
                className="flex-1 px-3 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-accent transition disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <Database size={16} />
                Indexar {year || "ano"}
              </button>
              <button
                onClick={() => {
                  setQuery("");
                  setYear("");
                  setEntity("");
                  setNif("");
                  setCpv("");
                  setMinPrice("");
                  setMaxPrice("");
                  setFrom(0);
                  doSearch(true);
                }}
                className="px-3 py-2 rounded-lg border border-border hover:bg-accent transition"
              >
                Limpar
              </button>
            </div>
          </div>

          {error && (
            <div className={`rounded-lg px-3 py-2 text-sm ${error.startsWith("Indexados") ? "bg-primary/10 text-primary" : "bg-destructive/10 text-destructive"}`}>
              {error}
            </div>
          )}
        </div>

        {results.length > 0 && (
          <div className="mb-4 text-sm text-muted-foreground flex items-center justify-between">
            <span>
              {total.toLocaleString("pt-PT")} resultado{total === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setFrom(Math.max(0, from - size)); doSearch(false); }}
                disabled={from === 0 || loading}
                className="px-3 py-1 rounded-lg border border-border hover:bg-accent disabled:opacity-50 transition"
              >
                Anterior
              </button>
              <span className="text-xs">Página {page} de {pageCount}</span>
              <button
                onClick={() => { setFrom(from + size); doSearch(false); }}
                disabled={from + size >= total || loading}
                className="px-3 py-1 rounded-lg border border-border hover:bg-accent disabled:opacity-50 transition"
              >
                Seguinte
              </button>
            </div>
          </div>
        )}

        {!loading && results.length === 0 && !error && (
          <div className="py-16 flex flex-col items-center gap-3 text-muted-foreground">
            <Frown size={40} />
            <p>Nenhum contrato encontrado.</p>
          </div>
        )}

        <div className="space-y-3">
          {results.map((c, i) => (
            <article
              key={`${c.idcontrato || i}-${i}`}
              className="rounded-xl border border-border bg-card p-4 hover:border-primary/50 transition"
            >
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
                    <span className="bg-muted px-2 py-0.5 rounded">{c.Ano ?? "—"}</span>
                    <span>{c.tipoContrato || c.TipoAnuncio || "Contrato"}</span>
                    {c.idcontrato && <span className="truncate">ID: {c.idcontrato}</span>}
                  </div>
                  <h3 className="font-semibold text-foreground leading-tight mb-1">
                    {c.objectoContrato || "Sem objeto definido"}
                  </h3>
                  {c.descContrato && (
                    <p className="text-sm text-muted-foreground line-clamp-2">{c.descContrato}</p>
                  )}
                  <div className="mt-2 text-sm space-y-1">
                    <p><span className="text-muted-foreground">Adjudicante:</span> {partyNames(c.adjudicantes)} {firstNif(c.adjudicantes) && `(${firstNif(c.adjudicantes)})`}</p>
                    <p><span className="text-muted-foreground">Adjudicatário:</span> {partyNames(c.adjudicatarios)}</p>
                    {c.localExecucao && <p><span className="text-muted-foreground">Local:</span> {c.localExecucao}</p>}
                    {c.cpv && c.cpv.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        CPV: {c.cpv.map((x) => `${x.code} ${x.description}`).join("; ")}
                      </p>
                    )}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-lg font-bold text-primary">{formatPrice(c.precoContratual)}</div>
                  <div className="text-xs text-muted-foreground">
                    Publicação {formatDate(c.dataPublicacao)} · Celebração {formatDate(c.dataCelebracaoContrato)}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>

        {results.length > 0 && (
          <div className="mt-6 flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {total.toLocaleString("pt-PT")} resultado{total === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setFrom(Math.max(0, from - size)); doSearch(false); }}
                disabled={from === 0 || loading}
                className="px-3 py-1 rounded-lg border border-border hover:bg-accent disabled:opacity-50 transition"
              >
                Anterior
              </button>
              <span className="text-xs">Página {page} de {pageCount}</span>
              <button
                onClick={() => { setFrom(from + size); doSearch(false); }}
                disabled={from + size >= total || loading}
                className="px-3 py-1 rounded-lg border border-border hover:bg-accent disabled:opacity-50 transition"
              >
                Seguinte
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
