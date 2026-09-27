/**
 * Análise de sentimento — léxico PT + estatística (pandas/scikit-learn), com
 * modelo neuronal opcional.
 *
 * Analisa um texto, os dados recolhidos de sites, as notícias, um dossiê de
 * análise ou um documento do Office. O resultado pode ser **guardado no dossiê**
 * (passa a fazer parte da evidência e do relatório exportado) e **levado para o
 * editor Office** como documento pronto a editar.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Copy,
  Database,
  Download,
  FileText,
  Globe2,
  Landmark,
  LineChart,
  Loader2,
  RefreshCw,
  Sparkles,
  Tag,
  TrendingDown,
  TrendingUp,
  Wand2,
} from "lucide-react";
import { useAuth } from "../auth";
import { listOfficeDocuments } from "../officeApi";
import { listSearch360Dossiers } from "../search360Api";
import {
  analyzeSentimentCorpus,
  analyzeSentimentText,
  downloadText,
  getSentimentMeta,
  listSentimentSources,
  saveSentimentToDossier,
  saveSentimentToOffice,
  type SentimentAnalysis,
  type SentimentEngineId,
  type SentimentMeta,
  type SentimentOrigin,
  type SentimentSource,
} from "../sentimentApi";
import SentimentMarketPanel from "./SentimentMarket";
import { Kpi, PolarityBar, focusRing, labelChip, tap, tone } from "../components/sentiment/SentimentKit";

const numberFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 });

const ORIGINS: { id: SentimentOrigin; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "scraped", label: "Recolha", hint: "Itens recolhidos de sites", icon: <Globe2 size={14} /> },
  { id: "news", label: "Notícias", hint: "Notícias indexadas de mercado", icon: <LineChart size={14} /> },
  { id: "dossier", label: "Dossiê", hint: "Evidência de um dossiê de análise", icon: <Landmark size={14} /> },
  { id: "office", label: "Documento", hint: "Documento do editor Office", icon: <FileText size={14} /> },
  { id: "text", label: "Texto", hint: "Texto colado à mão", icon: <Wand2 size={14} /> },
];

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(".", ",")} M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} mil`;
  return String(value);
}

interface SentimentPageProps {
  onNavigate?: (view: string) => void;
}

export default function SentimentPage({ onNavigate }: SentimentPageProps) {
  const { user } = useAuth();
  const [view, setView] = useState<"corpus" | "mercado">("corpus");
  const [meta, setMeta] = useState<SentimentMeta | null>(null);
  const [origin, setOrigin] = useState<SentimentOrigin>("scraped");
  const [engine, setEngine] = useState<SentimentEngineId>("lexicon");
  const [query, setQuery] = useState("");
  const [newsTicker, setNewsTicker] = useState("");
  const [limit, setLimit] = useState(60);
  const [text, setText] = useState("");
  const [dossiers, setDossiers] = useState<{ id: string; title: string; term?: string; has_sentiment?: boolean }[]>([]);
  const [documents, setDocuments] = useState<{ id: string; title: string; kind: string }[]>([]);
  const [sources, setSources] = useState<SentimentSource[]>([]);
  const [accounts, setAccounts] = useState<{ id: string; label?: string; address?: string }[]>([]);
  const [accountId, setAccountId] = useState("");
  const [dossierId, setDossierId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [targetDossierId, setTargetDossierId] = useState("");
  const [analysis, setAnalysis] = useState<SentimentAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingDossier, setSavingDossier] = useState(false);
  const [savingOffice, setSavingOffice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [officeDoc, setOfficeDoc] = useState<{ id: string; title: string } | null>(null);

  useEffect(() => {
    getSentimentMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
    listSearch360Dossiers({ limit: 60 })
      .then((payload) => setDossiers((payload.items ?? []) as never))
      .catch(() => setDossiers([]));
    listOfficeDocuments({})
      .then((payload) => setDocuments((payload.items ?? []) as never))
      .catch(() => setDocuments([]));
    listSentimentSources()
      .then((payload) => {
        setSources(payload.items ?? []);
        setAccounts(payload.accounts ?? []);
      })
      .catch(() => setSources([]));
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const corpusRequest = useCallback(
    () => ({
      origin,
      q: query || undefined,
      limit,
      engine,
      ticker: origin === "news" ? newsTicker.trim().toUpperCase() || undefined : undefined,
      dossierId: origin === "dossier" ? dossierId : undefined,
      documentId: origin === "office" ? documentId : undefined,
      accountId: origin === "email" ? accountId : undefined,
    }),
    [origin, query, limit, engine, dossierId, documentId, accountId, newsTicker],
  );

  const sourceGroups = useMemo(() => [...new Set(sources.map((entry) => entry.group))], [sources]);
  const selectedSource = sources.find((entry) => entry.id === origin);

  const run = async (override?: { origin: SentimentOrigin; ticker?: string }) => {
    setLoading(true);
    setError(null);
    setOfficeDoc(null);
    try {
      const effectiveOrigin = override?.origin ?? origin;
      const payload =
        effectiveOrigin === "text"
          ? await analyzeSentimentText({ text, title: query || undefined, engine })
          : await analyzeSentimentCorpus({
              ...corpusRequest(),
              origin: effectiveOrigin,
              ticker: override?.ticker ?? corpusRequest().ticker,
            });
      setAnalysis(payload);
      if (!payload.rows?.length) setError("A análise não encontrou documentos com texto para avaliar.");
    } catch (err) {
      setAnalysis(null);
      setError(err instanceof Error ? err.message : "Falha na análise de sentimento.");
    } finally {
      setLoading(false);
    }
  };

  /** O painel de mercado manda analisar as notícias de um ticker no corpus. */
  const analyseTicker = (ticker: string) => {
    setOrigin("news");
    setNewsTicker(ticker);
    setView("corpus");
    void run({ origin: "news", ticker });
  };

  const saveDossier = async () => {
    if (!targetDossierId) {
      setError("Escolha o dossiê onde guardar a análise.");
      return;
    }
    setSavingDossier(true);
    setError(null);
    try {
      await saveSentimentToDossier({ ...corpusRequest(), dossierId: targetDossierId, title: undefined });
      setNotice("Análise guardada no dossiê — já faz parte do relatório exportado e do Office.");
      setDossiers((previous) => previous.map((item) => (item.id === targetDossierId ? { ...item, has_sentiment: true } : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível guardar no dossiê.");
    } finally {
      setSavingDossier(false);
    }
  };

  const createOffice = async () => {
    if (!analysis) return;
    setSavingOffice(true);
    setError(null);
    try {
      const title = `Sentimento — ${originLabel(origin, sources)}${query ? ` · ${query}` : ""}`;
      const result = await saveSentimentToOffice({
        title,
        analysis,
        dossierId: targetDossierId || undefined,
        tags: ["sentimento", origin],
      });
      setOfficeDoc({ id: result.document.id, title: result.document.title });
      setDocuments((previous) => [{ id: result.document.id, title: result.document.title, kind: "relatorio" }, ...previous]);
      setNotice(`Documento «${result.document.title}» criado no Office (${result.document.words} palavras).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível criar o documento no Office.");
    } finally {
      setSavingOffice(false);
    }
  };

  const copyMarkdown = async () => {
    if (!analysis?.markdown) return;
    try {
      await navigator.clipboard.writeText(analysis.markdown);
      setNotice("Relatório Markdown copiado — pode colar em qualquer documento do Office.");
    } catch {
      setError("O navegador não autorizou a cópia para a área de transferência.");
    }
  };

  const engineOptions = meta?.engines ?? [];
  const neural = engineOptions.find((entry) => entry.id === "neural");
  const distribution = analysis?.distribution ?? [];
  const totalDocs = analysis?.summary.documents ?? 0;

  const positives = useMemo(() => (analysis?.terms ?? []).filter((term) => term.weight > 0).slice(0, 10), [analysis]);
  const negatives = useMemo(() => (analysis?.terms ?? []).filter((term) => term.weight < 0).slice(0, 10), [analysis]);

  return (
    <div className="mx-auto w-full max-w-[1300px] px-4 pb-32 pt-6 sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-fuchsia-300 via-violet-500 to-indigo-600 text-white shadow-lg shadow-violet-500/25">
            <BarChart3 size={20} />
          </span>
          <div>
            <h1 className="text-xl font-semibold">Análise de sentimento</h1>
            <p className="text-sm text-muted-foreground">
              Léxico PT (negação e intensificadores) + estatística com pandas e palavras-chave TF-IDF — sobre a recolha, notícias,
              dossiês ou documentos do Office.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="engine">
            Motor de análise
          </label>
          <select
            id="engine"
            value={engine}
            onChange={(event) => setEngine(event.target.value as SentimentEngineId)}
            className={inputClass}
            title={neural?.available ? "Modelo neuronal disponível" : "Modelo neuronal indisponível (fica no léxico)"}
          >
            {engineOptions.map((entry) => (
              <option key={entry.id} value={entry.id} disabled={entry.id === "neural" && !entry.available}>
                {entry.label}
                {entry.id === "neural" && !entry.available ? " (indisponível)" : ""}
              </option>
            ))}
            <option value="auto">Automático (neuronal se disponível)</option>
          </select>
          <button
            type="submit"
            form="sentimento-form"
            disabled={loading || (origin === "text" ? !text.trim() : false)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-400 to-indigo-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {loading ? "A analisar…" : "Analisar"}
          </button>
        </div>
      </header>

      {/* ------------------------------------------------ vistas da página */}
      <div className="mt-4 flex gap-2 overflow-x-auto [scrollbar-width:none]">
        {(
          [
            { id: "corpus" as const, label: "Análise de corpus", icon: <Wand2 size={14} /> },
            { id: "mercado" as const, label: "Mercado", icon: <Activity size={14} /> },
          ]
        ).map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setView(entry.id)}
            aria-pressed={view === entry.id}
            className={`${tap} ${focusRing} inline-flex shrink-0 items-center gap-2 rounded-xl border px-4 text-xs font-medium transition ${
              view === entry.id
                ? "border-violet-400/40 bg-violet-500/20 text-violet-100"
                : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
            }`}
          >
            {entry.icon} {entry.label}
          </button>
        ))}
      </div>

      <div className={view === "corpus" ? "contents" : "hidden"}>
      {meta ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">léxico: {meta.lexicon_size} termos</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">{meta.keywords}</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">{meta.aggregation}</span>
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
            limites: ±{meta.thresholds.positive}
          </span>
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} className="mt-0.5" />
          <span className="flex-1">{error}</span>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-100">
          <CheckCircle2 size={14} /> {notice}
        </div>
      ) : null}

      {/* ------------------------------------------------ origem dos dados */}
      <form
        id="sentimento-form"
        className="glass-card mt-5 rounded-2xl p-4"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_140px]">
          <label className="block">
            <span className="text-[11px] text-muted-foreground">Fonte do sistema</span>
            <select
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              className={`${inputClass} mt-1`}
              title={selectedSource?.hint}
              aria-label="Fonte do sistema a analisar"
            >
              {sourceGroups.map((group) => (
                <optgroup key={group} label={group}>
                  {sources
                    .filter((entry) => entry.group === group)
                    .map((entry) => (
                      <option key={entry.id} value={entry.id} disabled={entry.blocked}>
                        {entry.label} · {formatCount(entry.available)}
                        {entry.blocked ? " (exige sessão)" : ""}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
            <span className="mt-1 block text-[10px] text-muted-foreground">
              {selectedSource?.hint}
              {selectedSource?.blocked ? ` — ${selectedSource.blocked_reason}` : ""}
            </span>
          </label>

          {origin === "news" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Ticker (opcional)</span>
              <input
                value={newsTicker}
                onChange={(event) => setNewsTicker(event.target.value)}
                className={`${inputClass} mt-1 font-mono`}
                placeholder="ex.: EDP.LS"
                title="Limita as notícias analisadas a este ticker"
              />
            </label>
          ) : origin === "dossier" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Dossiê de análise</span>
              <select value={dossierId} onChange={(event) => setDossierId(event.target.value)} className={`${inputClass} mt-1`}>
                <option value="">(escolher dossiê)</option>
                {dossiers.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                    {item.has_sentiment ? " · com sentimento" : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : origin === "office" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Documento do Office</span>
              <select value={documentId} onChange={(event) => setDocumentId(event.target.value)} className={`${inputClass} mt-1`}>
                <option value="">(escolher documento)</option>
                {documents.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
          ) : origin === "email" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Caixa de correio</span>
              <select value={accountId} onChange={(event) => setAccountId(event.target.value)} className={`${inputClass} mt-1`}>
                <option value="">(escolher conta)</option>
                {accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label || item.address || item.id}
                  </option>
                ))}
              </select>
            </label>
          ) : origin === "text" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Título (opcional)</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} className={`${inputClass} mt-1`} placeholder="ex.: Comunicado de resultados" />
            </label>
          ) : (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">
                {origin === "news"
                  ? "Termo nas notícias (ticker ou tema)"
                  : origin === "contracts"
                    ? "Termo nos contratos (objeto, entidade)"
                    : "Termo a pesquisar (opcional)"}
              </span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={origin === "news" ? "ex.: EDP ou AAPL" : origin === "contracts" ? "ex.: energia, limpeza" : "ex.: combustíveis"}
                className={`${inputClass} mt-1`}
              />
            </label>
          )}

          <label className="block">
            <span className="text-[11px] text-muted-foreground">Documentos (máx.)</span>
            <input
              type="number"
              min={1}
              max={200}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value) || 60)}
              className={`${inputClass} mt-1`}
            />
          </label>
        </div>

        {origin === "text" ? (
          <label className="mt-3 block">
            <span className="text-[11px] text-muted-foreground">Texto a analisar</span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={5}
              placeholder="Cole aqui uma notícia, um comunicado, um relatório…"
              className={`${inputClass} mt-1 h-auto py-2 leading-relaxed`}
            />
          </label>
        ) : null}
        <p className="mt-2 text-[10px] text-muted-foreground">
          Enter para analisar · as fontes com sessão (CRM, email) só ficam disponíveis depois de iniciar sessão ·
          os resultados podem ser guardados no dossiê e abertos no Office
        </p>
      </form>

      {/* ------------------------------------------------------- resultados */}
      {analysis ? (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi
              label="Sentimento médio"
              value={`${analysis.summary.mean_polarity >= 0 ? "+" : ""}${analysis.summary.mean_polarity.toFixed(3)}`}
              hint={analysis.summary.label}
              tone={tone(analysis.summary.mean_polarity)}
            />
            <Kpi
              label="IC 95 %"
              value={
                analysis.summary.ci95
                  ? `[${analysis.summary.ci95[0].toFixed(2)}, ${analysis.summary.ci95[1].toFixed(2)}]`
                  : "—"
              }
              hint="intervalo de confiança da média"
            />
            <Kpi label="Documentos" value={numberFormat.format(totalDocs)} hint={`motor: ${analysis.summary.engine}`} />
            <Kpi
              label="Cobertura"
              value={`${((analysis.summary.coverage ?? 0) * 100).toFixed(0)}%`}
              hint={`${analysis.summary.documents_with_signal ?? 0} com termos de sentimento · ${analysis.summary.documents_without_signal ?? 0} sem`}
            />
            <Kpi
              label="Positivos"
              value={numberFormat.format(analysis.summary.positive)}
              hint={`${((analysis.summary.positive_share ?? 0) * 100).toFixed(0)}% do corpus`}
              tone="text-emerald-300"
            />
            <Kpi
              label="Negativos"
              value={numberFormat.format(analysis.summary.negative)}
              hint={`${((analysis.summary.negative_share ?? 0) * 100).toFixed(0)}% do corpus`}
              tone="text-rose-300"
            />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]">
            <div className="space-y-4">
              {/* distribuição */}
              <section className="glass-card rounded-2xl p-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  <BarChart3 size={15} /> Distribuição
                </h2>
                <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-white/5">
                  {distribution.map((entry) => {
                    const share = totalDocs ? entry.count / totalDocs : 0;
                    const colour =
                      entry.label === "positivo" ? "bg-emerald-400/70" : entry.label === "negativo" ? "bg-rose-400/70" : "bg-slate-400/40";
                    return <span key={entry.label} style={{ width: `${share * 100}%` }} className={colour} title={`${entry.label}: ${entry.count}`} />;
                  })}
                </div>
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  {distribution.map((entry) => (
                    <span key={entry.label} className="inline-flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full border border-white/10 bg-white/10" />
                      {entry.label}: {entry.count}
                    </span>
                  ))}
                </div>
              </section>

              {/* documentos */}
              <section className="glass-card rounded-2xl p-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  <FileText size={15} /> Documentos analisados
                </h2>
                <ul className="mt-2 divide-y divide-white/5">
                  {analysis.rows.map((row) => (
                    <li key={row.id} className="flex flex-wrap items-center gap-2 py-2 text-xs">
                      <span className="min-w-0 flex-1 truncate" title={row.title}>
                        {row.title || row.id}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">{row.source}</span>
                      <PolarityBar value={row.polarity} width={90} />
                      <span className={`w-14 shrink-0 text-right tabular-nums ${tone(row.polarity)}`}>
                        {row.polarity >= 0 ? "+" : ""}
                        {row.polarity.toFixed(2)}
                      </span>
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${labelChip(row.label)}`}>{row.label}</span>
                    </li>
                  ))}
                </ul>
              </section>

              {/* termos */}
              <div className="grid gap-4 sm:grid-cols-2">
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
                    <TrendingUp size={15} /> Termos positivos
                  </h2>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {positives.length ? (
                      positives.map((term) => (
                        <span key={term.term} className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-[10px] text-emerald-100">
                          {term.term} ×{term.count} ({term.weight >= 0 ? "+" : ""}
                          {term.weight.toFixed(1)})
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-muted-foreground">Sem termos positivos relevantes.</span>
                    )}
                  </div>
                </section>
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-rose-200">
                    <TrendingDown size={15} /> Termos negativos
                  </h2>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {negatives.length ? (
                      negatives.map((term) => (
                        <span key={term.term} className="rounded-full border border-rose-400/25 bg-rose-400/10 px-2 py-0.5 text-[10px] text-rose-100">
                          {term.term} ×{term.count} ({term.weight.toFixed(1)})
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-muted-foreground">Sem termos negativos relevantes.</span>
                    )}
                  </div>
                </section>
              </div>
            </div>

            {/* lateral: métodos + integrações */}
            <aside className="space-y-3">
              {analysis.by_tag.length ? (
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Tag size={12} /> Aspetos (por etiqueta/secção)
                  </h2>
                  <ul className="mt-2 space-y-1">
                    {analysis.by_tag.slice(0, 10).map((row) => (
                      <li key={row.tag} className="flex items-center gap-2 text-[11px]">
                        <span className="min-w-0 flex-1 truncate" title={row.tag}>
                          {row.tag}
                        </span>
                        <span className="text-muted-foreground">{row.documents}</span>
                        <span className={`tabular-nums ${tone(row.polarity)}`}>
                          {row.polarity >= 0 ? "+" : ""}
                          {row.polarity.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {analysis.by_source.length ? (
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Database size={12} /> Por fonte
                  </h2>
                  <ul className="mt-2 space-y-1">
                    {analysis.by_source.slice(0, 10).map((row) => (
                      <li key={row.source} className="flex items-center gap-2 text-[11px]">
                        <span className="min-w-0 flex-1 truncate">{row.source}</span>
                        <span className="text-muted-foreground">{row.documents}</span>
                        <span className={`tabular-nums ${tone(row.polarity)}`}>
                          {row.polarity >= 0 ? "+" : ""}
                          {row.polarity.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {analysis.keywords.length ? (
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <Tag size={12} /> Palavras-chave (TF-IDF)
                  </h2>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {analysis.keywords.slice(0, 18).map((keyword) => (
                      <span key={keyword.term} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
                        {keyword.term}
                      </span>
                    ))}
                  </div>
                </section>
              ) : null}

              {analysis.by_day.length ? (
                <section className="glass-card rounded-2xl p-4">
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Evolução diária</h2>
                  <ul className="mt-2 space-y-1">
                    {analysis.by_day.slice(-8).map((row) => (
                      <li key={row.day} className="flex items-center gap-2 text-[11px]">
                        <span className="w-20 shrink-0 text-muted-foreground">{row.day}</span>
                        <PolarityBar value={row.polarity} width={110} />
                        <span className={`tabular-nums ${tone(row.polarity)}`}>
                          {row.polarity >= 0 ? "+" : ""}
                          {row.polarity.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {/* guardar / integrar */}
              <section className="glass-card rounded-2xl p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Guardar e integrar</h2>

                <label className="mt-2 block">
                  <span className="text-[11px] text-muted-foreground">Guardar no dossiê de análise</span>
                  <select value={targetDossierId} onChange={(event) => setTargetDossierId(event.target.value)} className={`${inputClass} mt-1`}>
                    <option value="">(escolher dossiê)</option>
                    {dossiers.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.title}
                        {item.has_sentiment ? " · já tem sentimento" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void saveDossier()}
                    disabled={savingDossier || !targetDossierId || !user}
                    title={user ? "Fica registada no dossiê, com histórico" : "Precisa de sessão"}
                    className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-400 to-indigo-600 px-3 py-2 text-[11px] font-medium text-white disabled:opacity-50"
                  >
                    {savingDossier ? <Loader2 size={12} className="animate-spin" /> : <Database size={12} />} Guardar no dossiê
                  </button>
                  <button
                    type="button"
                    onClick={() => void createOffice()}
                    disabled={savingOffice || !user}
                    title={user ? "Cria um documento editável no Office" : "Precisa de sessão"}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] hover:bg-white/10 disabled:opacity-50"
                  >
                    {savingOffice ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />} Criar no Office
                  </button>
                </div>

                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => analysis.markdown && downloadText("sentimento.md", analysis.markdown, "text/markdown;charset=utf-8")}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] hover:bg-white/10"
                  >
                    <Download size={12} /> Markdown
                  </button>
                  <button
                    type="button"
                    onClick={() => analysis.csv && downloadText("sentimento.csv", analysis.csv)}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] hover:bg-white/10"
                  >
                    <Download size={12} /> CSV (pandas)
                  </button>
                  <button
                    type="button"
                    onClick={() => void copyMarkdown()}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] hover:bg-white/10"
                  >
                    <Copy size={12} /> Copiar relatório
                  </button>
                </div>

                {officeDoc ? (
                  <button
                    type="button"
                    onClick={() => onNavigate?.("office")}
                    className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-sky-400/25 bg-sky-400/10 px-3 py-2 text-[11px] text-sky-100 hover:bg-sky-400/20"
                  >
                    <FileText size={12} /> Abrir «{officeDoc.title}» no Office
                  </button>
                ) : null}

                {!user ? (
                  <p className="mt-2 text-[10px] text-amber-200">
                    Para guardar no dossiê ou criar o documento no Office é precisa uma sessão iniciada.
                  </p>
                ) : null}
              </section>

              <section className="glass-card rounded-2xl p-4 text-[10px] leading-relaxed text-muted-foreground">
                <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                  <RefreshCw size={12} /> Como é calculado
                </h2>
                <p className="mt-2">
                  Cada termo do léxico soma o seu peso; <strong className="text-foreground">negações</strong> invertem o sinal na janela de 3
                  palavras e <strong className="text-foreground">intensificadores</strong> («muito», «ligeiramente») ajustam a magnitude. A
                  polaridade do documento é normalizada pela raiz dos termos encontrados; a agregação (média, mediana, desvio, IC 95 %,
                  por fonte e por dia) é feita com pandas.
                </p>
              </section>
            </aside>
          </div>
        </>
      ) : null}
      </div>

      {view === "mercado" ? <SentimentMarketPanel onAnalyseTicker={analyseTicker} /> : null}
    </div>
  );
}

function originLabel(origin: SentimentOrigin, sources: SentimentSource[] = []): string {
  return sources.find((entry) => entry.id === origin)?.label ?? ORIGINS.find((entry) => entry.id === origin)?.label ?? origin;
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400";
