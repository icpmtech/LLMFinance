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
  saveSentimentToDossier,
  saveSentimentToOffice,
  type SentimentAnalysis,
  type SentimentEngineId,
  type SentimentMeta,
  type SentimentOrigin,
} from "../sentimentApi";

const numberFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 });

const ORIGINS: { id: SentimentOrigin; label: string; hint: string; icon: React.ReactNode }[] = [
  { id: "scraped", label: "Recolha", hint: "Itens recolhidos de sites", icon: <Globe2 size={14} /> },
  { id: "news", label: "Notícias", hint: "Notícias indexadas de mercado", icon: <LineChart size={14} /> },
  { id: "dossier", label: "Dossiê", hint: "Evidência de um dossiê de análise", icon: <Landmark size={14} /> },
  { id: "office", label: "Documento", hint: "Documento do editor Office", icon: <FileText size={14} /> },
  { id: "text", label: "Texto", hint: "Texto colado à mão", icon: <Wand2 size={14} /> },
];

function tone(polarity: number): string {
  if (polarity >= 0.15) return "text-emerald-300";
  if (polarity <= -0.15) return "text-rose-300";
  return "text-muted-foreground";
}

function labelChip(label: string): string {
  if (label === "positivo") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  if (label === "negativo") return "border-rose-400/30 bg-rose-400/10 text-rose-200";
  return "border-white/10 bg-white/5 text-muted-foreground";
}

/** Barra de polaridade (-1 a 1) com marca central. */
function PolarityBar({ value, width = 120 }: { value: number; width?: number }) {
  const clamped = Math.max(-1, Math.min(1, value || 0));
  const percent = Math.abs(clamped) * (width / 2);
  const positive = clamped >= 0;
  return (
    <span className="inline-flex items-center" style={{ width }} title={clamped.toFixed(3)}>
      <span className="relative block h-2 w-full rounded-full bg-white/10">
        <span className="absolute left-1/2 top-[-2px] h-3 w-px bg-white/20" />
        <span
          className={`absolute top-0 h-2 rounded-full ${positive ? "bg-emerald-400/70" : "bg-rose-400/70"}`}
          style={positive ? { left: "50%", width: percent } : { right: "50%", width: percent }}
        />
      </span>
    </span>
  );
}

function Kpi({ label, value, hint, tone: toneClass }: { label: string; value: React.ReactNode; hint?: string; tone?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${toneClass ?? ""}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

interface SentimentPageProps {
  onNavigate?: (view: string) => void;
}

export default function SentimentPage({ onNavigate }: SentimentPageProps) {
  const { user } = useAuth();
  const [meta, setMeta] = useState<SentimentMeta | null>(null);
  const [origin, setOrigin] = useState<SentimentOrigin>("scraped");
  const [engine, setEngine] = useState<SentimentEngineId>("lexicon");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(60);
  const [text, setText] = useState("");
  const [dossiers, setDossiers] = useState<{ id: string; title: string; term?: string; has_sentiment?: boolean }[]>([]);
  const [documents, setDocuments] = useState<{ id: string; title: string; kind: string }[]>([]);
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
      dossierId: origin === "dossier" ? dossierId : undefined,
      documentId: origin === "office" ? documentId : undefined,
    }),
    [origin, query, limit, engine, dossierId, documentId],
  );

  const run = async () => {
    setLoading(true);
    setError(null);
    setOfficeDoc(null);
    try {
      const payload =
        origin === "text"
          ? await analyzeSentimentText({ text, title: query || undefined, engine })
          : await analyzeSentimentCorpus(corpusRequest());
      setAnalysis(payload);
      if (!payload.rows?.length) setError("A análise não encontrou documentos com texto para avaliar.");
    } catch (err) {
      setAnalysis(null);
      setError(err instanceof Error ? err.message : "Falha na análise de sentimento.");
    } finally {
      setLoading(false);
    }
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
      const title = `Sentimento — ${originLabel(origin)}${query ? ` · ${query}` : ""}`;
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
            type="button"
            onClick={() => void run()}
            disabled={loading || (origin === "text" ? !text.trim() : false)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-400 to-indigo-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {loading ? "A analisar…" : "Analisar"}
          </button>
        </div>
      </header>

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
      <section className="glass-card mt-5 rounded-2xl p-4">
        <nav className="flex flex-wrap gap-1" aria-label="Origem dos dados">
          {ORIGINS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setOrigin(entry.id)}
              aria-current={origin === entry.id ? "true" : undefined}
              title={entry.hint}
              className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 ${
                origin === entry.id ? "bg-white/10 font-medium" : "text-muted-foreground hover:bg-white/5"
              }`}
            >
              {entry.icon}
              {entry.label}
            </button>
          ))}
        </nav>

        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px]">
          {origin === "text" ? (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">Texto a analisar</span>
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={5}
                placeholder="Cole aqui uma notícia, um comunicado, um relatório…"
                className={`${inputClass} mt-1 h-auto py-2 leading-relaxed`}
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
          ) : (
            <label className="block">
              <span className="text-[11px] text-muted-foreground">
                {origin === "scraped" ? "Termo na recolha (opcional)" : "Termo nas notícias (ticker, tema)"}
              </span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={origin === "scraped" ? "ex.: combustíveis" : "ex.: EDP ou AAPL"}
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
      </section>

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
  );
}

function originLabel(origin: SentimentOrigin): string {
  return ORIGINS.find((entry) => entry.id === origin)?.label ?? origin;
}

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400";
