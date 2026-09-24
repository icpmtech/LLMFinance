/**
 * Pesquisa social — recolha e pesquisa de publicações do LinkedIn, TikTok,
 * Reddit e Facebook.
 *
 * A aplicação organiza-se em seis secções, com a **pesquisa** em primeiro lugar
 * (a caixa única, no estilo da Pesquisa total, com resultados em cartões, lista
 * ou imagens):
 *
 * - **Pesquisa** — procurar publicações indexadas, filtrar por plataforma,
 *   canal, etiqueta e sentimento; mostra as facetas e o tom do conjunto.
 * - **Canais** — as definições de recolha (plataforma + variante + alvo), com o
 *   estado das credenciais, recolha imediata, teste de amostra, agenda cron e o
 *   interruptor de cada uma.
 * - **Execuções** — histórico das recolhas, com contagens, notas do coletor (o
 *   que a plataforma devolveu) e as publicações gravadas.
 * - **Modelos** — canais prontos a criar (LinkedIn de uma empresa, subreddit,
 *   hashtag do TikTok, página do Facebook), com teste ao vivo antes de guardar.
 * - **Agenda** — jobs de cron ativos e a próxima execução de cada canal.
 * - **Estado** — diagnóstico do ambiente (HTTP, Scrapling, browsers, proxy,
 *   Elasticsearch) e a volumetria por plataforma.
 *
 * O que cada plataforma permite sem credenciais está explicado nos modelos e no
 * estado do canal: o LinkedIn (página pública) e o Reddit (listagem de
 * subreddit) funcionam diretos; a pesquisa do Reddit e o Facebook pedem chaves,
 * e a interface di-lo onde as obter.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  AtSign,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Database,
  Globe2,
  Hash,
  Layers,
  Loader2,
  MessageCircle,
  Play,
  Plus,
  RefreshCw,
  Rss,
  Search,
  Settings2,
  ShieldAlert,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  createChannelFromTemplate,
  createSocialChannel,
  deleteSocialChannel,
  getSocialMeta,
  getSocialRun,
  getSocialRunItems,
  getSocialStats,
  getSocialStatus,
  listSocialChannels,
  listSocialJobs,
  listSocialRuns,
  listSocialTemplates,
  platformLabel,
  PLATFORM_COLORS,
  previewSavedSocialChannel,
  previewSocialChannel,
  previewSocialTemplate,
  reloadSocialJobs,
  runSocialChannel,
  RUN_STATUS_STYLE,
  searchSocial,
  toDisplayItem,
  updateSocialChannel,
  type SocialChannel,
  type SocialChannelParams,
  type SocialMeta,
  type SocialPost,
  type SocialPreview,
  type SocialRun,
  type SocialSearchParams,
  type SocialSearchResult,
  type SocialStats,
  type SocialStatus,
  type SocialTemplate,
} from "../socialApi";
import { ItemsCollection, ItemsViewToggle, type ItemsView } from "../components/ItemsView";
import { useAuth } from "../auth";

/* ------------------------------------------------------------- navegação */

export type SocialSection = "pesquisa" | "canais" | "execucoes" | "modelos" | "agenda" | "estado";

export const SOCIAL_SECTIONS: { id: SocialSection; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "pesquisa", label: "Pesquisa", icon: <Search size={13} />, hint: "Pesquisar publicações recolhidas" },
  { id: "canais", label: "Canais", icon: <Globe2 size={13} />, hint: "Definições de recolha por plataforma" },
  { id: "execucoes", label: "Execuções", icon: <Play size={13} />, hint: "Histórico das recolhas e publicações" },
  { id: "modelos", label: "Modelos", icon: <Layers size={13} />, hint: "Canais prontos a criar" },
  { id: "agenda", label: "Agenda", icon: <CalendarClock size={13} />, hint: "Cron e próximas recolhas" },
  { id: "estado", label: "Estado", icon: <Settings2 size={13} />, hint: "Ambiente, indexação e volumetria" },
];

/** Vista da plataforma correspondente a cada secção (usada pelo App/dock). */
export const SOCIAL_SECTION_VIEWS: Record<SocialSection, string> = {
  pesquisa: "social",
  canais: "social-canais",
  execucoes: "social-execucoes",
  modelos: "social-modelos",
  agenda: "social-agenda",
  estado: "social-estado",
};

export function socialSectionForView(view: string): SocialSection | null {
  const entry = (Object.entries(SOCIAL_SECTION_VIEWS) as [SocialSection, string][]).find(([, value]) => value === view);
  return entry ? entry[0] : null;
}

export function socialSectionTitle(section: SocialSection): string {
  return `Pesquisa social · ${SOCIAL_SECTIONS.find((entry) => entry.id === section)?.label ?? "Pesquisa"}`;
}

/* ------------------------------------------------------------- utilitários */

const numberFormat = new Intl.NumberFormat("pt-PT");
const compactFormat = new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  linkedin: <AtSign size={13} />,
  tiktok: <Hash size={13} />,
  reddit: <MessageCircle size={13} />,
  facebook: <Rss size={13} />,
};

const EXAMPLES = ["EDP", "Galp", "inteligência artificial", "benfica", "energia"];

function platformIcon(platform?: string): React.ReactNode {
  return PLATFORM_ICONS[String(platform ?? "")] ?? <Globe2 size={13} />;
}

function PlatformPill({ platform, label }: { platform?: string; label?: string }) {
  const color = PLATFORM_COLORS[String(platform ?? "")] ?? "#64748b";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]"
      style={{ borderColor: `${color}55`, background: `${color}22`, color }}
    >
      {platformIcon(platform)}
      {label ?? platformLabel(platform)}
    </span>
  );
}

function StatusPill({ status }: { status?: string }) {
  const style = RUN_STATUS_STYLE[String(status ?? "")] ?? RUN_STATUS_STYLE.error;
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] ${style.className}`}>{style.label}</span>;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

function toDisplayItems(posts: SocialPost[]) {
  return posts.map(toDisplayItem);
}

/* ------------------------------------------------------------------ página */

interface SocialPageProps {
  section?: SocialSection;
  onSectionChange?: (next: SocialSection) => void;
}

export default function SocialPage({ section, onSectionChange }: SocialPageProps) {
  const { user } = useAuth();
  const canWrite = Boolean(user);
  const [meta, setMeta] = useState<SocialMeta | null>(null);
  const [status, setStatus] = useState<SocialStatus | null>(null);
  const [stats, setStats] = useState<SocialStats | null>(null);
  const [internal, setInternal] = useState<SocialSection>(section ?? "pesquisa");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (section) setInternal(section);
  }, [section]);

  const go = useCallback(
    (next: SocialSection) => {
      setInternal(next);
      onSectionChange?.(next);
    },
    [onSectionChange],
  );

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextStats] = await Promise.all([getSocialStatus(), getSocialStats()]);
      setStatus(nextStatus);
      setStats(nextStats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível ler o estado da pesquisa social");
    }
  }, []);

  useEffect(() => {
    getSocialMeta()
      .then(setMeta)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Metadados indisponíveis"));
    void refresh();
  }, [refresh]);

  const indexed = status?.indexed_items ?? 0;

  return (
    // `h-full` (e não `h-screen`): em modo janela a moldura do IQ OS dá uma
    // altura definida e o `main` rola por dentro; em modo página a altura é do
    // conteúdo e quem rola é o shell — com `h-screen` a página excedia o shell
    // (que reserva 112 px em baixo) e o cabeçalho deixava de responder a cliques.
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-6 py-3">
        <div className="rounded-xl bg-gradient-to-br from-sky-300/30 via-fuchsia-500/25 to-slate-900 p-2 text-sky-100">
          <Users size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-foreground">Pesquisa social</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            LinkedIn, TikTok, Reddit e Facebook: recolher, agendar e pesquisar publicações
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {meta ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              índice <span className="font-mono text-foreground">{meta.index}</span> · {numberFormat.format(indexed)} publicações
            </span>
          ) : null}
          {status?.scheduler?.available && status.scheduler.jobs_total ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-muted-foreground">
              {status.scheduler.jobs_total} agenda(s) ativa(s)
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => void refresh()}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            <RefreshCw size={12} /> Atualizar
          </button>
        </div>
      </header>

      <nav className="flex flex-wrap items-center gap-1 border-b border-white/10 px-6 py-2">
        {SOCIAL_SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => go(item.id)}
            title={item.hint}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11.5px] transition ${
              internal === item.id ? "bg-sky-400/15 text-sky-200" : "text-muted-foreground hover:bg-white/5 hover:text-foreground"
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {(error || notice) && (
          <div className="mb-3 flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
            {error ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
            <span className="flex-1">{error ?? notice}</span>
            <button
              type="button"
              className="opacity-70 hover:opacity-100"
              onClick={() => {
                setError(null);
                setNotice(null);
              }}
            >
              ×
            </button>
          </div>
        )}

        {internal === "pesquisa" && <SearchSection meta={meta} />}
        {internal === "canais" && (
          <ChannelsSection
            meta={meta}
            canWrite={canWrite}
            onNotice={setNotice}
            onError={setError}
            onChanged={() => void refresh()}
          />
        )}
        {internal === "execucoes" && <RunsSection onError={setError} />}
        {internal === "modelos" && (
          <TemplatesSection canWrite={canWrite} onNotice={setNotice} onError={setError} onChanged={() => void refresh()} />
        )}
        {internal === "agenda" && <ScheduleSection onError={setError} onChanged={() => void refresh()} />}
        {internal === "estado" && <StatusSection meta={meta} status={status} stats={stats} />}
      </main>
    </div>
  );
}

/* --------------------------------------------------------------- pesquisa */

function SearchSection({ meta }: { meta: SocialMeta | null }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [platform, setPlatform] = useState("");
  const [channelId, setChannelId] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [tag, setTag] = useState("");
  const [sort, setSort] = useState<NonNullable<SocialSearchParams["sort"]>>("recent");
  const [result, setResult] = useState<SocialSearchResult | null>(null);
  const [channels, setChannels] = useState<SocialChannel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ItemsView>("cards");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    listSocialChannels()
      .then((payload) => setChannels(payload.items))
      .catch(() => setChannels([]));
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await searchSocial({
        q: query.trim() || undefined,
        platform: platform || undefined,
        channel_id: channelId || undefined,
        sentiment: sentiment ? [sentiment] : undefined,
        tag: tag ? [tag] : undefined,
        sort,
        size: 24,
      });
      if (payload.error) throw new Error(payload.error);
      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pesquisa falhou");
    } finally {
      setLoading(false);
    }
  }, [query, platform, channelId, sentiment, tag, sort]);

  useEffect(() => {
    if (!submitted && !result) return;
    void run();
  }, [run, submitted, result]);

  const submit = (term?: string, nextPlatform?: string) => {
    const value = (term ?? query).trim();
    setQuery(value);
    setSubmitted(value);
    if (nextPlatform !== undefined) setPlatform(nextPlatform);
    setTag("");
    setSentiment("");
    void run();
  };

  const posts = result?.items ?? [];
  const items = useMemo(() => toDisplayItems(posts), [posts]);
  const facets = result?.facets ?? {};
  const summary = result?.sentiment;

  const searchBox = (compact: boolean) => (
    <div className="relative w-full">
      <div
        className={`flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 shadow-lg shadow-black/20 backdrop-blur focus-within:border-sky-400/40 focus-within:ring-2 focus-within:ring-sky-400/30 ${
          compact ? "h-11" : "h-14"
        }`}
      >
        <Search size={compact ? 16 : 20} className="shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Pesquisar nas redes sociais: empresa, pessoa, hashtag ou tema…"
          aria-label="Pesquisar publicações das redes sociais"
          className={`w-full bg-transparent outline-none placeholder:text-muted-foreground ${compact ? "text-sm" : "text-base"}`}
        />
        {query ? (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              inputRef.current?.focus();
            }}
            aria-label="Limpar pesquisa"
            className="rounded-full p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            <X size={compact ? 13 : 16} />
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => submit()}
          className="hidden shrink-0 rounded-full bg-gradient-to-r from-sky-400 to-fuchsia-600 px-4 py-1.5 text-xs font-medium text-white sm:inline-flex"
        >
          Pesquisar
        </button>
      </div>
    </div>
  );

  if (!submitted && !result) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pb-24 pt-12 sm:pt-20">
        <span className="grid h-14 w-14 place-items-center rounded-3xl bg-gradient-to-br from-sky-300 via-fuchsia-500 to-indigo-600 text-white shadow-xl shadow-fuchsia-500/25">
          <Users size={26} />
        </span>
        <h2 className="mt-4 bg-gradient-to-r from-sky-200 via-fuchsia-200 to-indigo-200 bg-clip-text text-4xl font-semibold tracking-tight text-transparent sm:text-5xl">
          Pesquisa social
        </h2>
        <p className="mt-2 max-w-xl text-center text-sm text-muted-foreground">
          Uma caixa para o que as redes sociais dizem: publicações do{" "}
          <strong className="font-medium text-foreground">LinkedIn</strong>, vídeos e hashtags do{" "}
          <strong className="font-medium text-foreground">TikTok</strong>, conversas do{" "}
          <strong className="font-medium text-foreground">Reddit</strong> e páginas do{" "}
          <strong className="font-medium text-foreground">Facebook</strong> — recolhidas por canais, agendadas por cron e
          pesquisáveis com facetas e sentimento.
        </p>
        <div className="mt-7 w-full">{searchBox(false)}</div>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
          <button
            type="button"
            onClick={() => setPlatform("")}
            className={`rounded-full border px-3 py-1 text-[11px] ${
              !platform ? "border-sky-400/30 bg-sky-400/10 text-sky-200" : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
            }`}
          >
            Todas as plataformas
          </button>
          {(meta?.platforms ?? []).map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setPlatform(entry.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] ${
                platform === entry.id
                  ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
                  : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10"
              }`}
            >
              {platformIcon(entry.id)}
              {entry.label}
            </button>
          ))}
        </div>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              {example}
            </button>
          ))}
        </div>
        <p className="mt-6 max-w-xl text-center text-[11px] text-muted-foreground">
          Ainda sem publicações? Crie canais na secção <strong className="text-foreground">Canais</strong> (ou use um{" "}
          <strong className="text-foreground">Modelo</strong>) e recolha com um clique ou por cron.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">{searchBox(true)}</div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <select
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            className={`rounded-full border px-2.5 py-1 outline-none ${
              platform ? "border-sky-400/30 bg-sky-400/10 text-sky-100" : "border-white/10 bg-white/5 text-muted-foreground"
            }`}
          >
            <option value="">Plataforma</option>
            {(meta?.platforms ?? []).map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
          <select
            value={channelId}
            onChange={(event) => setChannelId(event.target.value)}
            className={`rounded-full border px-2.5 py-1 outline-none ${
              channelId ? "border-sky-400/30 bg-sky-400/10 text-sky-100" : "border-white/10 bg-white/5 text-muted-foreground"
            }`}
          >
            <option value="">Canal</option>
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.name}
              </option>
            ))}
          </select>
          <select
            value={sentiment}
            onChange={(event) => setSentiment(event.target.value)}
            className={`rounded-full border px-2.5 py-1 outline-none ${
              sentiment ? "border-sky-400/30 bg-sky-400/10 text-sky-100" : "border-white/10 bg-white/5 text-muted-foreground"
            }`}
          >
            <option value="">Sentimento</option>
            <option value="positivo">Positivo</option>
            <option value="neutro">Neutro</option>
            <option value="negativo">Negativo</option>
          </select>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as NonNullable<SocialSearchParams["sort"]>)}
            className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-muted-foreground outline-none"
          >
            <option value="recent">Mais recentes</option>
            <option value="relevance">Relevância</option>
            <option value="engagement">Mais reações</option>
            <option value="views">Mais vistas</option>
            <option value="oldest">Mais antigas</option>
          </select>
          <ItemsViewToggle value={view} onChange={setView} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span>
          {loading ? "a pesquisar…" : result ? `${numberFormat.format(result.total)} publicações` : "—"}
          {submitted ? ` para «${submitted}»` : ""}
        </span>
        {(facets.platforms ?? []).slice(0, 6).map((facet) => (
          <button
            key={facet.key}
            type="button"
            onClick={() => setPlatform(platform === facet.key ? "" : facet.key)}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${
              platform === facet.key ? "border-sky-400/40 bg-sky-400/10 text-sky-200" : "border-white/10 bg-white/5"
            }`}
          >
            {platformIcon(facet.key)}
            {platformLabel(facet.key)} <span className="text-foreground">{numberFormat.format(facet.count)}</span>
          </button>
        ))}
        {summary && summary.analyzed ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
            tom {summary.label} · {summary.polarity >= 0 ? "+" : ""}
            {summary.polarity.toFixed(2)} ({Math.round(summary.coverage * 100)}% analisado)
          </span>
        ) : null}
        {tag ? (
          <button
            type="button"
            onClick={() => setTag("")}
            className="inline-flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-400/10 px-2 py-0.5 text-sky-200"
          >
            #{tag} <X size={10} />
          </button>
        ) : null}
      </div>

      {(facets.tags ?? []).length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {(facets.tags ?? []).slice(0, 14).map((facet) => (
            <button
              key={facet.key}
              type="button"
              onClick={() => setTag(facet.key)}
              className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
            >
              #{facet.key} <span className="text-foreground">{facet.count}</span>
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-rose-400/25 bg-rose-400/5 px-3 py-2 text-[11.5px] text-rose-200">{error}</div>
      ) : null}

      {items.length ? (
        <ItemsCollection items={items} view={view} onTagClick={setTag} />
      ) : !loading ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-8 text-center text-[11.5px] text-muted-foreground">
          Sem publicações para estes filtros. Recolha os canais na secção «Canais» ou ajuste a pesquisa.
        </div>
      ) : null}
    </div>
  );
}

/* ----------------------------------------------------------------- canais */

const EMPTY_CHANNEL: SocialChannelParams = {
  platform: "linkedin",
  kind: "company",
  target: "",
  name: "",
  limit: 25,
  schedule: { cron: "0 */6 * * *", timezone: "Europe/Lisbon" },
  tags: [],
};

function ChannelsSection({
  meta,
  canWrite,
  onNotice,
  onError,
  onChanged,
}: {
  meta: SocialMeta | null;
  canWrite: boolean;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const [channels, setChannels] = useState<SocialChannel[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<SocialChannelParams | null>(null);
  const [preview, setPreview] = useState<SocialPreview | null>(null);
  const [run, setRun] = useState<SocialRun | null>(null);
  const [runPosts, setRunPosts] = useState<SocialPost[]>([]);
  const [runView, setRunView] = useState<ItemsView>("lista");
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listSocialChannels();
      setChannels(payload.items);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível listar os canais");
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    },
    [],
  );

  const kindsFor = (platform?: string) => (meta?.platforms ?? []).find((entry) => entry.id === platform)?.kinds ?? [];

  const watchRun = useCallback(
    (runId: string, channelId: string) => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      const tick = async () => {
        try {
          const { item } = await getSocialRun(runId, channelId);
          setRun(item);
          if (item.status !== "running") {
            if (pollRef.current) window.clearInterval(pollRef.current);
            pollRef.current = null;
            setBusy(null);
            onNotice(`${item.channel_name}: ${item.items_count ?? 0} publicações (${item.indexed_count ?? 0} indexadas).`);
            const items = await getSocialRunItems(runId, channelId, 100);
            setRunPosts(items.items);
            await load();
            onChanged();
          }
        } catch (err) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(null);
          onError(err instanceof Error ? err.message : "A recolha falhou");
        }
      };
      void tick();
      pollRef.current = window.setInterval(() => void tick(), 2500);
    },
    [load, onChanged, onError, onNotice],
  );

  const startRun = async (channel: SocialChannel) => {
    setBusy(channel.id);
    setRun(null);
    setRunPosts([]);
    try {
      const result = await runSocialChannel(channel.id);
      if (result.run_id) watchRun(result.run_id, channel.id);
      else setBusy(null);
    } catch (err) {
      setBusy(null);
      onError(err instanceof Error ? err.message : "Não foi possível arrancar a recolha");
    }
  };

  const toggle = async (channel: SocialChannel) => {
    try {
      await updateSocialChannel(channel.id, { enabled: !channel.enabled });
      onNotice(`${channel.name}: agenda ${channel.enabled ? "desligada" : "ligada"}.`);
      await load();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível alterar a agenda");
    }
  };

  const remove = async (channel: SocialChannel) => {
    try {
      await deleteSocialChannel(channel.id, true);
      onNotice(`${channel.name}: canal apagado (com as publicações indexadas).`);
      await load();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível apagar o canal");
    }
  };

  const test = async (channel: SocialChannel) => {
    setBusy(channel.id);
    setPreview(null);
    try {
      const result = await previewSavedSocialChannel(channel.id, 3);
      setPreview({ ...result, channel: { ...(result.channel ?? channel), id: channel.id } });
    } catch (err) {
      onError(err instanceof Error ? err.message : "O teste falhou");
    } finally {
      setBusy(null);
    }
  };

  const testDraft = async () => {
    if (!draft) return;
    setBusy("draft");
    setPreview(null);
    try {
      const result = await previewSocialChannel(draft, 3);
      setPreview({ ...result, channel: { ...(result.channel ?? {}), id: "draft" } as SocialChannel });
    } catch (err) {
      onError(err instanceof Error ? err.message : "O teste falhou");
    } finally {
      setBusy(null);
    }
  };

  const saveDraft = async () => {
    if (!draft) return;
    setBusy("draft");
    try {
      await createSocialChannel(draft);
      onNotice(`${draft.name || draft.target}: canal criado.`);
      setDraft(null);
      setPreview(null);
      await load();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível guardar o canal");
    } finally {
      setBusy(null);
    }
  };

  const kinds = kindsFor(draft?.platform);
  const needsCredentials = kinds.find((kind) => kind.id === draft?.kind)?.credentials ?? false;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11.5px] text-muted-foreground">
          {loading ? "a carregar…" : `${channels.length} canais · ${channels.filter((c) => c.enabled).length} com agenda ativa`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-white/10"
          >
            <RefreshCw size={12} /> Recarregar
          </button>
          <button
            type="button"
            disabled={!canWrite}
            onClick={() => setDraft({ ...EMPTY_CHANNEL })}
            title={canWrite ? "Criar um canal" : "Precisa de sessão iniciada"}
            className="flex items-center gap-1.5 rounded-full bg-gradient-to-r from-sky-400 to-fuchsia-600 px-3 py-1 text-[11px] font-medium text-white disabled:opacity-50"
          >
            <Plus size={12} /> Novo canal
          </button>
        </div>
      </div>

      {draft ? (
        <div className="rounded-2xl border border-sky-400/25 bg-sky-400/[0.04] p-3">
          <div className="flex items-center gap-2">
            <Plus size={13} className="text-sky-300" />
            <span className="text-[11.5px] font-medium text-foreground">Novo canal</span>
            <button type="button" className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => setDraft(null)}>
              <X size={13} />
            </button>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-[10.5px] text-muted-foreground">
              Plataforma
              <select
                value={draft.platform}
                onChange={(event) => {
                  const platform = event.target.value;
                  const first = kindsFor(platform)[0];
                  setDraft({ ...draft, platform, kind: first?.id ?? "", target: "" });
                }}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              >
                {(meta?.platforms ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Variante
              <select
                value={draft.kind}
                onChange={(event) => setDraft({ ...draft, kind: event.target.value })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              >
                {kinds.map((kind) => (
                  <option key={kind.id} value={kind.id}>
                    {kind.label}
                    {kind.credentials ? " (credenciais)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Alvo
              <input
                value={draft.target ?? ""}
                onChange={(event) => setDraft({ ...draft, target: event.target.value })}
                placeholder={kinds.find((kind) => kind.id === draft.kind)?.target ?? "alvo"}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              />
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Nome (opcional)
              <input
                value={draft.name ?? ""}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                placeholder="LinkedIn · Empresa X"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              />
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Publicações por recolha
              <input
                type="number"
                min={1}
                max={meta?.max_limit ?? 200}
                value={draft.limit ?? 25}
                onChange={(event) => setDraft({ ...draft, limit: Number(event.target.value) })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              />
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Agenda (cron)
              <select
                value={draft.schedule?.cron ?? ""}
                onChange={(event) => setDraft({ ...draft, schedule: { ...draft.schedule, cron: event.target.value } })}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              >
                <option value="">sem agenda</option>
                {(meta?.cron_presets ?? []).map((preset) => (
                  <option key={preset.cron} value={preset.cron}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Etiquetas (separadas por vírgula)
              <input
                value={(draft.tags ?? []).join(", ")}
                onChange={(event) =>
                  setDraft({ ...draft, tags: event.target.value.split(",").map((entry) => entry.trim()).filter(Boolean) })
                }
                placeholder="energia, empresa"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              />
            </label>
            <label className="text-[10.5px] text-muted-foreground">
              Proxy (opcional)
              <input
                value={String(draft.options?.proxy ?? "")}
                onChange={(event) => setDraft({ ...draft, options: { ...draft.options, proxy: event.target.value } })}
                placeholder="http://utilizador:pass@servidor:porta"
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11.5px] text-foreground outline-none"
              />
            </label>
          </div>

          {needsCredentials ? (
            <div className="mt-2 rounded-lg border border-amber-400/25 bg-amber-400/5 px-2.5 py-2 text-[10.5px] text-amber-200">
              <div className="flex items-center gap-1.5">
                <ShieldAlert size={12} /> Esta variante exige credenciais
              </div>
              <div className="mt-1 grid gap-2 sm:grid-cols-2">
                {draft.platform === "reddit" ? (
                  <>
                    <input
                      value={String(draft.options?.client_id ?? "")}
                      onChange={(event) => setDraft({ ...draft, options: { ...draft.options, client_id: event.target.value } })}
                      placeholder="client_id"
                      className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[11px] text-foreground outline-none"
                    />
                    <input
                      type="password"
                      value={String(draft.options?.client_secret ?? "")}
                      onChange={(event) => setDraft({ ...draft, options: { ...draft.options, client_secret: event.target.value } })}
                      placeholder="client_secret"
                      className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[11px] text-foreground outline-none"
                    />
                  </>
                ) : (
                  <input
                    type="password"
                    value={String(draft.options?.access_token ?? "")}
                    onChange={(event) => setDraft({ ...draft, options: { ...draft.options, access_token: event.target.value } })}
                    placeholder="access_token (Graph API)"
                    className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[11px] text-foreground outline-none sm:col-span-2"
                  />
                )}
              </div>
              <p className="mt-1 opacity-80">
                {(meta?.platforms ?? []).find((entry) => entry.id === draft.platform)?.credential_hint}
              </p>
            </div>
          ) : null}

          <p className="mt-2 text-[10.5px] text-muted-foreground">{kinds.find((kind) => kind.id === draft.kind)?.notes}</p>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void testDraft()}
              className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-muted-foreground hover:bg-white/10 disabled:opacity-50"
            >
              {busy === "draft" ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Testar recolha
            </button>
            <button
              type="button"
              disabled={busy !== null || !draft.target}
              onClick={() => void saveDraft()}
              className="rounded-full bg-gradient-to-r from-sky-400 to-fuchsia-600 px-3 py-1 text-[11px] font-medium text-white disabled:opacity-50"
            >
              Guardar canal
            </button>
          </div>

          {preview && preview.channel?.id === "draft" ? <PreviewPanel preview={preview} /> : null}
        </div>
      ) : null}

      <div className="space-y-2">
        {channels.map((channel) => {
          const credentials = channel.credentials;
          return (
            <div key={channel.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
              <div className="flex flex-wrap items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-[12.5px] font-medium text-foreground">{channel.name}</span>
                    <PlatformPill platform={channel.platform} label={channel.platform_label} />
                    <span className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {channel.kind_label ?? channel.kind}
                    </span>
                    {credentials?.required ? (
                      credentials.ok ? (
                        <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-1.5 py-0.5 text-[10px] text-emerald-200">
                          credenciais ok
                        </span>
                      ) : (
                        <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                          faltam credenciais
                        </span>
                      )
                    ) : null}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[10.5px] text-muted-foreground">
                    <span className="font-mono">{channel.target}</span>
                    <span>· limite {channel.limit}</span>
                    <span>· {channel.schedule?.cron ? `cron ${channel.schedule.cron}` : "sem agenda"}</span>
                    {(channel.tags ?? []).map((tag) => (
                      <span key={tag} className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={channel.enabled}
                    aria-label={`Agenda de ${channel.name}`}
                    onClick={() => void toggle(channel)}
                    disabled={!canWrite}
                    title={channel.enabled ? "Desligar a agenda" : "Ligar a agenda"}
                    className={`h-5 w-9 shrink-0 rounded-full border transition disabled:opacity-50 ${
                      channel.enabled ? "border-emerald-400/40 bg-emerald-400/30" : "border-white/15 bg-white/10"
                    }`}
                  >
                    <span className={`block h-4 w-4 rounded-full bg-white transition ${channel.enabled ? "translate-x-4" : "translate-x-0.5"}`} />
                  </button>
                  <button
                    type="button"
                    disabled={busy !== null || !canWrite}
                    onClick={() => void startRun(channel)}
                    className="flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1 text-[11px] text-emerald-200 hover:bg-emerald-400/20 disabled:opacity-50"
                  >
                    {busy === channel.id ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Recolher
                  </button>
                  <button
                    type="button"
                    disabled={busy !== null || !canWrite}
                    onClick={() => void test(channel)}
                    title="Recolher uma amostra sem guardar"
                    className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-white/10 disabled:opacity-50"
                  >
                    Testar
                  </button>
                  <button
                    type="button"
                    disabled={!canWrite}
                    onClick={() => void remove(channel)}
                    title="Apagar o canal (e as publicações indexadas)"
                    className="rounded-full border border-rose-400/25 bg-rose-400/10 px-2 py-1 text-[11px] text-rose-200 hover:bg-rose-400/20 disabled:opacity-50"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
              {credentials && credentials.required && !credentials.ok ? (
                <p className="mt-1.5 text-[10.5px] text-amber-200">
                  {credentials.hint} (campos em falta: {credentials.missing.join(", ")})
                </p>
              ) : null}
              {preview && preview.channel?.id === channel.id ? <PreviewPanel preview={preview} /> : null}
            </div>
          );
        })}
        {!channels.length && !loading ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-6 text-center text-[11.5px] text-muted-foreground">
            Ainda não há canais. Crie um em «Novo canal» ou use um «Modelo».
          </div>
        ) : null}
      </div>

      {run ? (
        <div className="rounded-2xl border border-sky-400/20 bg-sky-400/[0.04] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11.5px] font-medium text-foreground">{run.channel_name}</span>
            <StatusPill status={run.status} />
            <span className="text-[10.5px] text-muted-foreground">
              {run.items_count ?? 0} publicações · {run.indexed_count ?? 0} indexadas · {run.seconds ?? 0}s
            </span>
            {run.counters?.length ? (
              <span className="text-[10.5px] text-muted-foreground">
                {run.counters.map((counter) => `${numberFormat.format(counter.count)} ${counter.key}`).join(" · ")}
              </span>
            ) : null}
          </div>
          {run.error ? (
            <p className="mt-1 text-[11px] text-rose-200">
              {run.error}
              {run.hint ? <span className="text-muted-foreground"> — {run.hint}</span> : null}
            </p>
          ) : null}
          {(run.notes ?? []).length ? (
            <ul className="mt-1 space-y-0.5 text-[10.5px] text-muted-foreground">
              {(run.notes ?? []).map((note) => (
                <li key={note}>· {note}</li>
              ))}
            </ul>
          ) : null}
          {runPosts.length ? (
            <div className="mt-2">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[10.5px] text-muted-foreground">{runPosts.length} publicações gravadas</span>
                <ItemsViewToggle value={runView} onChange={setRunView} />
              </div>
              <ItemsCollection items={toDisplayItems(runPosts)} view={runView} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: SocialPreview }) {
  return (
    <div
      className={`mt-2 rounded-xl border px-2.5 py-2 text-[10.5px] ${
        preview.ok ? "border-emerald-400/25 bg-emerald-400/5 text-emerald-100" : "border-amber-400/25 bg-amber-400/5 text-amber-200"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">
          {preview.ok ? `${preview.count ?? 0} publicações em amostra` : `Sem recolha (${preview.status})`}
        </span>
        {preview.seconds ? <span className="opacity-80">{preview.seconds}s</span> : null}
      </div>
      {preview.error ? <p className="mt-1">{preview.error}</p> : null}
      {preview.hint ? <p className="mt-0.5 opacity-80">{preview.hint}</p> : null}
      {(preview.notes ?? []).map((note) => (
        <p key={note} className="mt-0.5 opacity-80">
          · {note}
        </p>
      ))}
      {(preview.items ?? []).slice(0, 3).map((item) => (
        <p key={item.item_id} className="mt-1 truncate text-foreground/90">
          {platformLabel(item.platform)} · {item.title || item.text || item.post_id}
        </p>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- execuções */

function RunsSection({ onError }: { onError: (message: string) => void }) {
  const [runs, setRuns] = useState<SocialRun[]>([]);
  const [selected, setSelected] = useState<SocialRun | null>(null);
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [view, setView] = useState<ItemsView>("lista");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await listSocialRuns({ limit: 60 });
      setRuns(payload.items);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível listar as execuções");
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = async (run: SocialRun) => {
    setSelected(run);
    setPosts([]);
    try {
      const payload = await getSocialRunItems(run.run_id, run.channel_id, 200);
      setPosts(payload.items);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível ler as publicações");
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(340px,460px)]">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <span>{loading ? "a carregar…" : `${runs.length} execuções`}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="ml-auto flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] hover:bg-white/10"
          >
            <RefreshCw size={12} /> Recarregar
          </button>
        </div>
        {runs.map((run) => (
          <button
            key={`${run.channel_id}-${run.run_id}`}
            type="button"
            onClick={() => void open(run)}
            className={`flex w-full flex-col gap-1 rounded-xl border px-3 py-2 text-left transition ${
              selected?.run_id === run.run_id ? "border-sky-400/40 bg-sky-400/10" : "border-white/10 bg-white/[0.02] hover:bg-white/[0.06]"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <PlatformPill platform={run.platform} />
              <span className="truncate text-[12px] font-medium text-foreground">{run.channel_name}</span>
              <StatusPill status={run.status} />
              <span className="ml-auto text-[10px] text-muted-foreground">{formatDate(run.started_at)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[10.5px] text-muted-foreground">
              <span>{run.items_count ?? 0} publicações</span>
              <span>· {run.indexed_count ?? 0} indexadas</span>
              {run.seconds ? <span>· {run.seconds}s</span> : null}
              <span>· {run.trigger}</span>
              {run.sentiment_count ? <span>· {run.sentiment_count} com sentimento</span> : null}
            </div>
            {run.error ? <span className="text-[10.5px] text-rose-300">{run.error}</span> : null}
          </button>
        ))}
        {!runs.length && !loading ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-6 text-center text-[11.5px] text-muted-foreground">
            Ainda não há execuções. Recolha um canal na secção «Canais».
          </div>
        ) : null}
      </div>

      <div className="min-w-0 space-y-2">
        {selected ? (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11.5px] font-medium text-foreground">{selected.channel_name}</span>
              <StatusPill status={selected.status} />
            </div>
            <div className="mt-1 grid grid-cols-2 gap-2 text-[11px]">
              {[
                { label: "Publicações", value: numberFormat.format(selected.items_count ?? 0) },
                { label: "Indexadas", value: numberFormat.format(selected.indexed_count ?? 0) },
                { label: "Duração", value: selected.seconds ? `${selected.seconds}s` : "—" },
                { label: "Sentimento", value: numberFormat.format(selected.sentiment_count ?? 0) },
                { label: "Reações", value: numberFormat.format(selected.likes ?? 0) },
                { label: "Comentários", value: numberFormat.format(selected.comments ?? 0) },
                { label: "Partilhas", value: numberFormat.format(selected.shares ?? 0) },
                { label: "Vistas", value: numberFormat.format(selected.views ?? 0) },
              ].map((kpi) => (
                <div key={kpi.label} className="rounded-xl border border-white/10 bg-black/20 px-2.5 py-2">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{kpi.label}</div>
                  <div className="text-[13px] font-semibold text-foreground">{kpi.value}</div>
                </div>
              ))}
            </div>
            {(selected.notes ?? []).length ? (
              <ul className="mt-2 space-y-0.5 text-[10.5px] text-muted-foreground">
                {(selected.notes ?? []).map((note) => (
                  <li key={note}>· {note}</li>
                ))}
              </ul>
            ) : null}
            {selected.error ? (
              <p className="mt-1.5 text-[11px] text-rose-200">
                {selected.error}
                {selected.hint ? <span className="text-muted-foreground"> — {selected.hint}</span> : null}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-[11.5px] text-muted-foreground">
            Escolha uma execução para ver as contagens, as notas do coletor e as publicações gravadas.
          </div>
        )}

        {posts.length ? (
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10.5px] text-muted-foreground">{posts.length} publicações</span>
              <ItemsViewToggle value={view} onChange={setView} />
            </div>
            <ItemsCollection items={toDisplayItems(posts)} view={view} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- modelos */

function TemplatesSection({
  canWrite,
  onNotice,
  onError,
  onChanged,
}: {
  canWrite: boolean;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const [templates, setTemplates] = useState<SocialTemplate[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<SocialPreview | null>(null);

  useEffect(() => {
    listSocialTemplates()
      .then((payload) => {
        setTemplates(payload.items);
        setTargets(Object.fromEntries(payload.items.map((item) => [item.id, item.target])));
      })
      .catch((err: unknown) => onError(err instanceof Error ? err.message : "Modelos indisponíveis"));
  }, [onError]);

  const create = async (template: SocialTemplate) => {
    setBusy(template.id);
    try {
      await createChannelFromTemplate(template.id, { target: targets[template.id] ?? template.target, enabled: false });
      onNotice(`${template.name}: canal criado (ligue a agenda na secção «Canais»).`);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível criar o canal");
    } finally {
      setBusy(null);
    }
  };

  const test = async (template: SocialTemplate) => {
    setBusy(template.id);
    setPreview(null);
    try {
      const result = await previewSocialTemplate(template.id, 3, { target: targets[template.id] ?? template.target });
      setPreview({ ...result, channel: { ...(result.channel ?? {}), id: template.id } as SocialChannel });
    } catch (err) {
      onError(err instanceof Error ? err.message : "O teste falhou");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-[11.5px] text-muted-foreground">
        Modelos prontos a criar. O teste recolhe uma amostra ao vivo (não guarda nada); os que precisam de credenciais
        di-lo-ão, com a indicação de onde obtê-las.
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        {templates.map((template) => (
          <div key={template.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <PlatformPill platform={template.platform} />
              <span className="text-[12px] font-medium text-foreground">{template.name}</span>
              {template.requires_credentials ? (
                <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                  exige credenciais
                </span>
              ) : null}
              {template.cron ? (
                <span className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {template.cron}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">{template.description}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                value={targets[template.id] ?? ""}
                onChange={(event) => setTargets({ ...targets, [template.id]: event.target.value })}
                placeholder={template.target}
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[11.5px] text-foreground outline-none"
              />
              <button
                type="button"
                disabled={busy !== null || !canWrite}
                onClick={() => void test(template)}
                className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-white/10 disabled:opacity-50"
              >
                {busy === template.id ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Testar
              </button>
              <button
                type="button"
                disabled={busy !== null || !canWrite}
                onClick={() => void create(template)}
                className="rounded-full bg-gradient-to-r from-sky-400 to-fuchsia-600 px-3 py-1 text-[11px] font-medium text-white disabled:opacity-50"
              >
                Criar canal
              </button>
            </div>
            {preview && preview.channel?.id === template.id ? <PreviewPanel preview={preview} /> : null}
          </div>
        ))}
        {!templates.length ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-6 text-center text-[11.5px] text-muted-foreground lg:col-span-2">
            Sem modelos disponíveis.
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- agenda */

function ScheduleSection({ onError, onChanged }: { onError: (message: string) => void; onChanged: () => void }) {
  const [jobs, setJobs] = useState<{ id: string; channel_id: string; name: string; next_run_time?: string | null }[]>([]);
  const [channels, setChannels] = useState<SocialChannel[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [jobsPayload, channelsPayload] = await Promise.all([listSocialJobs(), listSocialChannels()]);
      setJobs(jobsPayload.jobs ?? []);
      setAvailable(Boolean(jobsPayload.available));
      setChannels(channelsPayload.items);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível ler a agenda");
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = async () => {
    setBusy(true);
    try {
      await reloadSocialJobs();
      await load();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Não foi possível recarregar a agenda");
    } finally {
      setBusy(false);
    }
  };

  const withCron = channels.filter((channel) => channel.schedule?.cron);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
        <CalendarClock size={14} />
        <span>
          {available === null
            ? "a ler a agenda…"
            : available
              ? `${jobs.length} recolha(s) agendada(s) · ${withCron.length} canal(is) com cron`
              : "O agendador (APScheduler) não está disponível — as recolhas manuais continuam a funcionar."}
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => void reload()}
          className="ml-auto flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] hover:bg-white/10 disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Reaplicar definições
        </button>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="text-[11.5px] font-medium text-foreground">Próximas recolhas</div>
          <div className="mt-2 space-y-1">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center gap-2 text-[11px]">
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{job.name}</span>
                <span className="text-foreground">{formatDate(job.next_run_time)}</span>
              </div>
            ))}
            {!jobs.length ? <div className="text-[11px] text-muted-foreground">Nenhuma recolha agendada.</div> : null}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="text-[11.5px] font-medium text-foreground">Cron por canal</div>
          <div className="mt-2 space-y-1">
            {withCron.map((channel) => (
              <div key={channel.id} className="flex items-center gap-2 text-[11px]">
                <PlatformPill platform={channel.platform} />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{channel.name}</span>
                <span className="font-mono text-foreground">{channel.schedule.cron}</span>
                <span
                  className={`rounded-full border px-1.5 py-0.5 text-[10px] ${
                    channel.enabled
                      ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                      : "border-white/10 bg-white/5 text-muted-foreground"
                  }`}
                >
                  {channel.enabled ? "ativa" : "desligada"}
                </span>
              </div>
            ))}
            {!withCron.length ? (
              <div className="text-[11px] text-muted-foreground">
                Nenhum canal com cron. Defina a periodicidade na secção «Canais» (ou ao criar um modelo).
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- estado */

function StatusSection({ meta, status, stats }: { meta: SocialMeta | null; status: SocialStatus | null; stats: SocialStats | null }) {
  const charts = useMemo(
    () =>
      (status?.indexed_platforms ?? []).map((facet) => ({
        label: platformLabel(facet.key),
        key: facet.key,
        count: facet.count,
      })),
    [status?.indexed_platforms],
  );

  const checks = [
    { label: "Cliente HTTP", value: status?.http_client ? String(status.http_client) : "em falta" },
    { label: "Scrapling", value: status?.scrapling ? `sim (${status.scrapling_version ?? "—"})` : "não instalado" },
    { label: "Browsers", value: status?.browsers ? "instalados" : "não instalados" },
    { label: "Proxy", value: status?.proxy_configured ? "configurado" : "sem proxy" },
    { label: "Elasticsearch", value: status?.elasticsearch ? "disponível" : "indisponível" },
    { label: "Agendador", value: status?.scheduler?.available ? `${status.scheduler.jobs_total ?? 0} job(s)` : "inativo" },
    { label: "Interpretador", value: status?.python_version ?? "—" },
  ];

  const cards = [
    { label: "Publicações indexadas", value: status?.indexed_items ?? 0, icon: <Database size={14} /> },
    { label: "Canais", value: stats?.channels ?? 0, icon: <Globe2 size={14} /> },
    { label: "Canais com agenda", value: stats?.channels_enabled ?? 0, icon: <CalendarClock size={14} /> },
    { label: "Execuções", value: stats?.runs ?? 0, icon: <Play size={14} /> },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
            <div className="flex items-center gap-2 text-muted-foreground">
              {card.icon}
              <span className="text-[11px]">{card.label}</span>
            </div>
            <div className="mt-1 text-[20px] font-semibold text-foreground">{numberFormat.format(card.value)}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="text-[11.5px] font-medium text-foreground">Ambiente</div>
          <div className="mt-2 space-y-1">
            {checks.map((check) => (
              <div key={check.label} className="flex items-center gap-2 text-[11px]">
                <span className="text-muted-foreground">{check.label}</span>
                <span className="ml-auto text-foreground">{check.value}</span>
              </div>
            ))}
          </div>
          {status?.scrapling_error ? (
            <p className="mt-2 rounded-lg border border-amber-400/25 bg-amber-400/5 px-2 py-1 text-[10.5px] text-amber-200">
              {status.scrapling_error}
            </p>
          ) : null}
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center gap-2 text-[11.5px] font-medium text-foreground">
            <BarChart3 size={13} className="text-sky-300" /> Publicações por plataforma
          </div>
          <div className="mt-2 h-[220px]">
            {charts.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={charts} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e323b" horizontal={false} />
                  <XAxis type="number" stroke="#9aa0aa" fontSize={11} tickFormatter={(value) => compactFormat.format(Number(value))} />
                  <YAxis type="category" dataKey="label" stroke="#9aa0aa" fontSize={11} width={100} />
                  <Tooltip
                    contentStyle={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 10, fontSize: 11 }}
                    formatter={(value) => [numberFormat.format(Number(value)), "Publicações"]}
                  />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                    {charts.map((entry) => (
                      <Cell key={entry.key} fill={PLATFORM_COLORS[entry.key] ?? "#64748b"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="grid h-full place-items-center text-center text-[11px] text-muted-foreground">
                Ainda sem publicações indexadas. Recolha um canal para começar.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <div className="text-[11.5px] font-medium text-foreground">O que cada plataforma permite</div>
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          {(meta?.platforms ?? status?.platforms ?? []).map((entry) => (
            <div key={entry.id} className="rounded-xl border border-white/10 bg-black/20 p-2.5">
              <PlatformPill platform={entry.id} label={entry.label} />
              <ul className="mt-1.5 space-y-0.5 text-[10.5px] text-muted-foreground">
                {entry.kinds.map((kind) => (
                  <li key={kind.id}>
                    <span className="text-foreground">{kind.label}</span> — {kind.notes}
                    {kind.credentials ? <span className="text-amber-200"> (exige credenciais)</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
