/**
 * **SEC · Filings EDGAR** — pesquisa de empresas, recolha de filings,
 * pesquisa de documentos/factos e análise agregada.
 */
import { useCallback, useEffect, useState } from "react";
import {
  BarChart3,
  BookOpen,
  Building2,
  Calendar,
  Download,
  ExternalLink,
  FileText,
  Globe2,
  LayoutDashboard,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import type {
  SecAnalytics,
  SecBucket,
  SecCompany,
  SecFact,
  SecFilingItem,
  SecMeta,
  SecSchedule,
} from "../secApi";
import {
  fetchSecDocument,
  getSecAnalytics,
  getSecFactsXbrl,
  getSecFilings,
  getSecFiling,
  getSecMeta,
  getSecSchedule,
  indexSecFactsXbrl,
  ingestSecFilings,
  reloadSecSchedule,
  runSecSchedule,
  searchSecCompanies,
  searchSecFacts,
  searchSecFilings,
} from "../secApi";
import { EmptyState, FilterField, Loading, SearchInput, SectionCard } from "../components/padroes/padroesKit";

type Aba = "painel" | "empresas" | "filings" | "facts" | "xbrl" | "documentos" | "analytics" | "agendador";

const ABAS: { id: Aba; label: string; icon: typeof BookOpen }[] = [
  { id: "painel", label: "Painel", icon: LayoutDashboard },
  { id: "empresas", label: "Empresas", icon: Building2 },
  { id: "filings", label: "Filings indexados", icon: FileText },
  { id: "facts", label: "Factos", icon: Sparkles },
  { id: "xbrl", label: "XBRL", icon: BarChart3 },
  { id: "documentos", label: "Documentos", icon: BookOpen },
  { id: "analytics", label: "Análises", icon: BarChart3 },
  { id: "agendador", label: "Agendador", icon: Calendar },
];

const FORMS = ["8-K", "10-K", "10-Q", "20-F", "40-F", "6-K", "S-1", "DEF 14A"];

const FACT_CATEGORIES = ["revenue", "net_income", "eps", "eps_diluted", "assets", "liabilities", "cash", "equity", "long_term_debt", "operating_income"];

function useSecMeta() {
  const [meta, setMeta] = useState<SecMeta | null>(null);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(false);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getSecMeta()
      .then(setMeta)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível carregar o módulo SEC."))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    const t = setTimeout(carregar, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  return { meta, erro, carregando, recarregar: carregar };
}

function PainelTab({ meta }: { meta: SecMeta | null }) {
  const indices = meta?.status?.indices ?? {};
  return (
    <div className="space-y-4">
      <SectionCard title="Sobre o SEC EDGAR" subtitle="Filings oficiais da U.S. Securities and Exchange Commission" icon={ShieldCheck}>
        <div className="space-y-3 text-sm leading-relaxed text-foreground/90">
          <p>
            O EDGAR (Electronic Data Gathering, Analysis, and Retrieval) é o sistema público da SEC onde as empresas
            cotadas nos EUA submetem os seus relatórios e comunicações oficiais (10-K, 10-Q, 8-K, etc.).
          </p>
          <p className="text-muted-foreground">
            Fonte: {" "}
            <a href={meta?.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
              {meta?.fonte}
            </a>
          </p>
        </div>
      </SectionCard>

      <SectionCard title="Índices" subtitle="Documentos indexados no Elasticsearch" icon={BarChart3}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(indices).map(([name, stat]) => (
            <div key={name} className="glass-card rounded-xl p-4">
              <h3 className="mb-1 text-xs font-medium uppercase text-muted-foreground">{name}</h3>
              <p className="text-2xl font-semibold">{stat.count ?? 0}</p>
              <p className="text-[11px] text-muted-foreground">documentos</p>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function EmpresasTab() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<SecCompany[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [selecionada, setSelecionada] = useState<SecCompany | null>(null);
  const [filings, setFilings] = useState<SecFilingItem[]>([]);
  const [ingesting, setIngesting] = useState(false);

  const pesquisar = useCallback(() => {
    if (!q.trim()) {
      setItems([]);
      return;
    }
    setCarregando(true);
    setErro("");
    searchSecCompanies(q, 20)
      .then((res) => setItems(res.items))
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao pesquisar empresas."))
      .finally(() => setCarregando(false));
  }, [q]);

  const carregarFilings = useCallback((company: SecCompany) => {
    setSelecionada(company);
    setFilings([]);
    getSecFilings(company.cik, 40)
      .then((res) => setFilings(res.items))
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao obter filings."));
  }, []);

  const ingest = async (company: SecCompany) => {
    setIngesting(true);
    try {
      await ingestSecFilings(company.cik, 20);
      carregarFilings(company);
    } catch (exc) {
      setErro(exc instanceof Error ? exc.message : "Erro ao indexar filings.");
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <SectionCard title="Pesquisar empresas" subtitle="Nome ou ticker (ex.: AAPL, Tesla)" icon={Search}
        actions={
          <button
            onClick={pesquisar}
            disabled={carregando}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {carregando ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          </button>
        }
      >
        <div className="mb-4">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar empresa..." />
        </div>
        {erro && <EmptyState tone="warn">{erro}</EmptyState>}
        <div className="space-y-2">
          {items.map((item) => (
            <button
              key={item.cik}
              onClick={() => carregarFilings(item)}
              className={`flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition ${
                selecionada?.cik === item.cik
                  ? "border-teal-400/50 bg-teal-400/10"
                  : "border-white/10 bg-white/[0.03] hover:border-teal-400/30 hover:bg-teal-400/5"
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{item.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">{item.ticker} · CIK {item.cik}</p>
              </div>
              <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] uppercase text-muted-foreground">
                {item.ticker || "—"}
              </span>
            </button>
          ))}
          {!carregando && items.length === 0 && !erro && <EmptyState>Pesquisa uma empresa para começar.</EmptyState>}
          {carregando && <Loading label="A pesquisar empresas..." />}
        </div>
      </SectionCard>

      <SectionCard
        title={selecionada ? `Filings · ${selecionada.ticker}` : "Filings recentes"}
        subtitle={selecionada ? selecionada.name : "Seleciona uma empresa à esquerda"}
        icon={FileText}
        actions={
          selecionada ? (
            <button
              onClick={() => ingest(selecionada)}
              disabled={ingesting}
              className="flex items-center gap-1 rounded-lg bg-teal-500/20 px-3 py-1.5 text-xs text-teal-200 hover:bg-teal-500/30 disabled:opacity-50"
            >
              {ingesting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              Indexar
            </button>
          ) : null
        }
      >
        <div className="space-y-2">
          {filings.map((f) => (
            <div
              key={f.accession_number}
              className="flex items-start justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{f.form}</p>
                <p className="text-[11px] text-muted-foreground">
                  <Calendar size={12} className="mr-1 inline" />
                  {f.date}
                </p>
                <p className="truncate text-xs text-muted-foreground">{f.description}</p>
              </div>
              {f.url && (
                <a
                  href={f.url}
                  target="_blank"
                  rel="noreferrer"
                  className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-800/60 hover:text-white"
                  title="Abrir documento"
                >
                  <ExternalLink size={16} />
                </a>
              )}
            </div>
          ))}
          {!carregando && filings.length === 0 && selecionada && <EmptyState>Nenhum filing encontrado.</EmptyState>}
          {!selecionada && <EmptyState>Seleciona uma empresa para ver os filings.</EmptyState>}
        </div>
      </SectionCard>
    </div>
  );
}

function FilingsTab() {
  const [q, setQ] = useState("");
  const [ticker, setTicker] = useState("");
  const [form, setForm] = useState("");
  const [items, setItems] = useState<SecFilingItem[]>([]);
  const [total, setTotal] = useState(0);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");

  const pesquisar = useCallback(() => {
    setCarregando(true);
    setErro("");
    searchSecFilings({ q: q || undefined, ticker: ticker || undefined, form: form || undefined, size: 50 })
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao pesquisar filings."))
      .finally(() => setCarregando(false));
  }, [q, ticker, form]);

  useEffect(() => {
    const t = setTimeout(pesquisar, 0);
    return () => clearTimeout(t);
  }, [pesquisar]);

  return (
    <SectionCard title="Filings indexados" subtitle="Pesquisa nos documentos recolhidos da SEC" icon={FileText}>
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar filings..." />
        </div>
        <FilterField label="Ticker">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
          />
        </FilterField>
        <FilterField label="Form">
          <select
            value={form}
            onChange={(e) => setForm(e.target.value)}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
          >
            <option value="">Todos</option>
            {FORMS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </FilterField>
        <button
          onClick={pesquisar}
          disabled={carregando}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      {erro && <EmptyState tone="warn">{erro}</EmptyState>}
      <p className="mb-2 text-xs text-muted-foreground">{total} resultado(s)</p>

      <div className="space-y-2">
        {items.map((f) => (
          <div
            key={f.accession_number}
            className="flex items-start justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {f.company_name} · {f.form}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {f.ticker} · {f.date}
              </p>
              <p className="truncate text-xs text-muted-foreground">{f.description}</p>
            </div>
            {f.url && (
              <a
                href={f.url}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-800/60 hover:text-white"
                title="Abrir documento"
              >
                <ExternalLink size={16} />
              </a>
            )}
          </div>
        ))}
        {!carregando && items.length === 0 && !erro && <EmptyState>Nenhum filing indexado.</EmptyState>}
        {carregando && <Loading label="A pesquisar filings..." />}
      </div>
    </SectionCard>
  );
}

function FactsTab() {
  const [q, setQ] = useState("");
  const [ticker, setTicker] = useState("");
  const [form, setForm] = useState("");
  const [items, setItems] = useState<SecFact[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");

  const pesquisar = useCallback(() => {
    setCarregando(true);
    setErro("");
    searchSecFacts({ q: q || undefined, ticker: ticker || undefined, form: form || undefined, size: 50 })
      .then((res) => setItems(res.items))
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao pesquisar factos."))
      .finally(() => setCarregando(false));
  }, [q, ticker, form]);

  useEffect(() => {
    const t = setTimeout(pesquisar, 0);
    return () => clearTimeout(t);
  }, [pesquisar]);

  return (
    <SectionCard title="Factos extraídos" subtitle="Métricas e frases financeiras identificadas nos filings" icon={Sparkles}>
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar factos..." />
        </div>
        <FilterField label="Ticker">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
          />
        </FilterField>
        <FilterField label="Form">
          <select
            value={form}
            onChange={(e) => setForm(e.target.value)}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
          >
            <option value="">Todos</option>
            {FORMS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </FilterField>
        <button
          onClick={pesquisar}
          disabled={carregando}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      {erro && <EmptyState tone="warn">{erro}</EmptyState>}

      <div className="space-y-2">
        {items.map((f) => (
          <div key={`${f.filing_id}-${f.text.slice(0, 40)}`} className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
            <p className="text-sm leading-relaxed">{f.text}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {f.company_name} · {f.ticker} · {f.form} · <span className="rounded bg-white/10 px-1.5 py-0.5">{f.category}</span>
            </p>
          </div>
        ))}
        {!carregando && items.length === 0 && !erro && <EmptyState>Nenhum facto encontrado. Indexa filings primeiro.</EmptyState>}
        {carregando && <Loading label="A pesquisar factos..." />}
      </div>
    </SectionCard>
  );
}

function DocumentosTab() {
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [docId, setDocId] = useState("");
  const [doc, setDoc] = useState<SecFilingItem | null>(null);

  const carregarPorUrl = useCallback(() => {
    if (!url.trim()) return;
    setCarregando(true);
    setErro("");
    fetchSecDocument(url)
      .then((res) => {
        if (res.error) setErro(res.error);
        else setText(res.text);
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao obter documento."))
      .finally(() => setCarregando(false));
  }, [url]);

  const carregarPorId = useCallback(() => {
    if (!docId.trim()) return;
    setCarregando(true);
    setErro("");
    getSecFiling(docId)
      .then((res) => {
        setDoc(res);
        setText(res.text || "");
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao obter documento indexado."))
      .finally(() => setCarregando(false));
  }, [docId]);

  return (
    <SectionCard title="Visualizador de documentos" subtitle="Descarrega o texto integral de um documento SEC" icon={BookOpen}>
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <FilterField label="URL do documento EDGAR">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.sec.gov/Archives/edgar/data/..."
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <button
          onClick={carregarPorUrl}
          disabled={carregando || !url}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <Globe2 size={16} />}
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <FilterField label="ID do documento indexado">
            <input
              value={docId}
              onChange={(e) => setDocId(e.target.value)}
              placeholder="0000320193-24-000123"
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <button
          onClick={carregarPorId}
          disabled={carregando || !docId}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
        </button>
      </div>

      {erro && <EmptyState tone="warn">{erro}</EmptyState>}
      {doc && (
        <div className="mb-3 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm">
          <span className="font-medium">{doc.company_name}</span> · {doc.form} · {doc.date}
        </div>
      )}

      {text ? (
        <div className="max-h-[60vh] overflow-auto rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{text}</pre>
        </div>
      ) : (
        !carregando && !erro && <EmptyState>Insere um URL ou ID para visualizar o documento.</EmptyState>
      )}
      {carregando && <Loading label="A carregar documento..." />}
    </SectionCard>
  );
}

function XbrlTab() {
  const [cik, setCik] = useState("");
  const [facts, setFacts] = useState<SecFact[]>([]);
  const [companyName, setCompanyName] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [category, setCategory] = useState("");
  const [indexing, setIndexing] = useState(false);

  const carregar = useCallback(() => {
    if (!cik.trim()) return;
    setCarregando(true);
    setErro("");
    getSecFactsXbrl(cik)
      .then((res) => {
        if (res.error) {
          setErro(res.error);
          return;
        }
        setFacts(res.facts);
        setCompanyName(res.company_name);
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao carregar factos XBRL."))
      .finally(() => setCarregando(false));
  }, [cik]);

  const indexar = async () => {
    if (!cik.trim()) return;
    setIndexing(true);
    try {
      await indexSecFactsXbrl(cik);
      setErro("");
    } catch (exc) {
      setErro(exc instanceof Error ? exc.message : "Erro ao indexar factos XBRL.");
    } finally {
      setIndexing(false);
    }
  };

  const filtered = category ? facts.filter((f) => f.category === category) : facts;

  return (
    <SectionCard title="Factos XBRL" subtitle="Métricas financeiras estruturadas da SEC (companyfacts API)" icon={BarChart3}
      actions={
        cik ? (
          <button
            onClick={indexar}
            disabled={indexing}
            className="flex items-center gap-1 rounded-lg bg-teal-500/20 px-3 py-1.5 text-xs text-teal-200 hover:bg-teal-500/30 disabled:opacity-50"
          >
            {indexing ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Indexar no ES
          </button>
        ) : null
      }
    >
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <FilterField label="CIK da empresa">
            <input
              value={cik}
              onChange={(e) => setCik(e.target.value)}
              placeholder="0000320193"
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <FilterField label="Categoria">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
          >
            <option value="">Todas</option>
            {FACT_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </FilterField>
        <button
          onClick={carregar}
          disabled={carregando || !cik}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
        </button>
      </div>

      {companyName && <p className="mb-3 text-sm text-muted-foreground">{companyName}</p>}
      {erro && <EmptyState tone="warn">{erro}</EmptyState>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.slice(0, 60).map((f) => (
          <div key={`${f.concept}-${f.end}-${f.fp}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <p className="text-xs font-medium text-muted-foreground">{f.label || f.concept}</p>
            <p className="text-lg font-semibold">
              {f.value !== undefined ? f.value.toLocaleString("en-US") : "—"} <span className="text-xs font-normal text-muted-foreground">{f.unit}</span>
            </p>
            <p className="text-[11px] text-muted-foreground">
              {f.form || "—"} · FY{f.fy ?? "—"} {f.fp || ""} · {f.end || ""}
            </p>
          </div>
        ))}
      </div>
      {!carregando && filtered.length === 0 && !erro && <EmptyState>Indica um CIK para carregar factos XBRL.</EmptyState>}
      {carregando && <Loading label="A carregar factos XBRL..." />}
    </SectionCard>
  );
}

function AgendadorTab() {
  const [schedule, setSchedule] = useState<SecSchedule | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [ticker, setTicker] = useState("");

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getSecSchedule()
      .then(setSchedule)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao carregar agendador."))
      .finally(() => setCarregando(false));
  }, []);

  const recarregar = async () => {
    setCarregando(true);
    try {
      const res = await reloadSecSchedule();
      setSchedule(res);
    } catch (exc) {
      setErro(exc instanceof Error ? exc.message : "Erro ao recarregar.");
    } finally {
      setCarregando(false);
    }
  };

  const executar = async () => {
    if (!ticker.trim()) return;
    try {
      await runSecSchedule(ticker);
      setTicker("");
    } catch (exc) {
      setErro(exc instanceof Error ? exc.message : "Erro ao executar recolha.");
    }
  };

  useEffect(() => {
    const t = setTimeout(carregar, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  return (
    <SectionCard title="Agendador SEC" subtitle="Recolha automática de filings para os tickers guardados" icon={Calendar}
      actions={
        <button
          onClick={recarregar}
          disabled={carregando}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      }
    >
      {schedule && <p className="mb-3 text-sm text-muted-foreground">{schedule.started ? `${schedule.job_count} jobs configurados` : `Inativo${schedule.error ? `: ${schedule.error}` : ""}`}</p>}
      {erro && <EmptyState tone="warn">{erro}</EmptyState>}

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <FilterField label="Executar agora para o ticker">
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="AAPL"
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <button
          onClick={executar}
          disabled={!ticker}
          className="self-end rounded-lg bg-teal-500/20 px-3 py-2 text-sm text-teal-200 hover:bg-teal-500/30 disabled:opacity-50"
        >
          Executar
        </button>
      </div>

      <div className="space-y-2">
        {schedule?.jobs.map((job: { id: string; name: string; next_run?: string }) => (
          <div key={job.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">{job.name}</p>
              <p className="text-[11px] text-muted-foreground">{job.next_run ? new Date(job.next_run).toLocaleString("pt-PT") : "—"}</p>
            </div>
          </div>
        ))}
        {!carregando && schedule?.jobs.length === 0 && <EmptyState>Nenhum ticker na lista local. Adiciona tickers em Ações/Mercado.</EmptyState>}
      </div>
    </SectionCard>
  );
}

function AnalyticsTab() {
  const [data, setData] = useState<SecAnalytics | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getSecAnalytics()
      .then(setData)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao carregar análises."))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    const t = setTimeout(carregar, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  return (
    <SectionCard title="Análise agregada" subtitle="Distribuição por tipo de form, ano e ticker" icon={BarChart3}>
      <div className="mb-4 flex justify-end">
        <button
          onClick={carregar}
          disabled={carregando}
          className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      {erro && <EmptyState tone="warn">{erro}</EmptyState>}

      <div className="grid gap-4 lg:grid-cols-3">
        <BucketCard title="Por tipo de form" items={data?.by_form || []} />
        <BucketCard title="Por ano" items={data?.by_year || []} />
        <BucketCard title="Por ticker" items={data?.by_ticker || []} />
      </div>

      {carregando && <Loading label="A carregar análises..." />}
    </SectionCard>
  );
}

function BucketCard({ title, items }: { title: string; items: SecBucket[] }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <h3 className="mb-3 text-sm font-medium">{title}</h3>
      <div className="space-y-1">
        {items.map((b) => (
          <div key={b.value} className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{b.value}</span>
            <span className="font-medium">{b.count.toLocaleString("pt-PT")}</span>
          </div>
        ))}
        {items.length === 0 && <EmptyState>Sem dados.</EmptyState>}
      </div>
    </div>
  );
}

export default function SecPage() {
  const [tab, setTab] = useState<Aba>("painel");
  const { meta, erro, carregando, recarregar } = useSecMeta();

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <ShieldCheck size={24} className="text-sky-300" />
              SEC · Filings EDGAR
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Pesquisa de empresas, recolha de filings, pesquisa de documentos e factos,
              e análise agregada dos dados da U.S. Securities and Exchange Commission.
            </p>
          </div>
          <button
            onClick={recarregar}
            disabled={carregando}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          </button>
        </header>

        <nav className="mb-5 flex flex-wrap gap-1 rounded-xl border border-white/10 bg-black/30 p-1">
          {ABAS.map((a) => (
            <button
              key={a.id}
              onClick={() => setTab(a.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition ${
                tab === a.id ? "bg-teal-500/20 text-teal-200" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <a.icon size={14} />
              {a.label}
            </button>
          ))}
        </nav>

        {erro && <EmptyState tone="warn">{erro}</EmptyState>}
        {carregando && !meta && <Loading label="A carregar módulo SEC..." />}

        {tab === "painel" && <PainelTab meta={meta} />}
        {tab === "empresas" && <EmpresasTab />}
        {tab === "filings" && <FilingsTab />}
        {tab === "facts" && <FactsTab />}
        {tab === "xbrl" && <XbrlTab />}
        {tab === "documentos" && <DocumentosTab />}
        {tab === "analytics" && <AnalyticsTab />}
        {tab === "agendador" && <AgendadorTab />}
      </div>
    </div>
  );
}
