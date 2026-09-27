/**
 * Painéis do leitor de RSS: panorama, lista + leitura de artigos e integrações.
 *
 * A lista e a leitura vivem lado a lado no computador (esquerda: índice; direita:
 * artigo) e **alternam** no telemóvel (lista → artigo, com botão de voltar). Os
 * filtros, que no computador estão sempre à vista, no telemóvel abrem numa
 * gaveta — assim o índice fica com o ecrã quase todo.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  Bookmark,
  BookmarkCheck,
  Bot,
  Building2,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  FileType2,
  Flame,
  Inbox,
  Keyboard,
  Layers,
  ListFilter,
  Loader2,
  Mail,
  RefreshCw,
  Rss,
  Search,
  Share2,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  Wand2,
} from "lucide-react";

import * as rss from "../rssApi";
import type { RssArticle, RssArticleFilters, RssArticleList, RssCatalogue, RssOverview } from "../rssApi";
import {
  Btn,
  Chip,
  CountDot,
  EmptyState,
  IconAction,
  MiniBars,
  Notice,
  PanelHeader,
  Sheet,
  StatCard,
  TONE_CLASS,
  TagEditor,
  TextInput,
  fullDate,
  timeAgo,
  timeUntil,
} from "../components/rss/RssKit";

export type RssSection = "painel" | "artigos" | "guardados" | "fontes" | "pastas" | "sugestoes" | "agenda" | "integracoes";

export type RssTone = "info" | "error" | "ok";

/** Foco pedido por outra secção: um artigo, uma fonte/pasta ou um termo. */
export type RssFocus = { articleId?: string; feedId?: string; q?: string };

export type RssCtx = {
  catalogue: RssCatalogue;
  overview: RssOverview | null;
  /** Muda sempre que algo foi alterado: as listas recarregam. */
  version: number;
  notify: (message: string, tone?: RssTone) => void;
  /** Recarrega catálogo e panorama. */
  refresh: () => void;
  /** Avisa as listas de que devem recarregar. */
  bumpData: () => void;
  goTo: (section: RssSection, focus?: RssFocus) => void;
};

/** Texto simples a partir do HTML do feed (nunca injeta HTML no documento). */
export function plainFromHtml(value?: string | null): string {
  if (!value) return "";
  return String(value)
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|blockquote|tr)>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x([0-9a-f]+);/gi, (_match, code: string) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(\d+);/g, (_match, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&#39;|&apos;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/* ==========================================================================
   Painel (panorama)
   ========================================================================== */
export function RssOverviewPanel({ ctx, onOpenArticle }: { ctx: RssCtx; onOpenArticle: (articleId: string) => void }) {
  const { overview, catalogue } = ctx;
  if (!overview) return <p className="py-10 text-center text-[12.5px] text-muted-foreground">A carregar o panorama…</p>;
  const schedule = overview.schedule;
  const activeRules = (overview.rules ?? []).filter((rule) => rule.enabled);
  const ruleHits = activeRules.reduce((total, rule) => total + (rule.hits ?? 0), 0);
  const topFeeds = overview.top_feeds ?? [];
  const topVolume = Math.max(1, ...topFeeds.map((feed) => feed.articles ?? 0));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Não lidos" value={String(overview.articles.unread)} hint="por ler" tone="teal" />
        <StatCard label="Artigos" value={String(overview.articles.total)} hint={`${overview.articles.today} hoje`} tone="sky" />
        <StatCard label="Hoje e semana" value={String(overview.articles.week)} hint="últimos 7 dias" tone="indigo" />
        <StatCard label="Guardados" value={String(overview.articles.saved)} hint={`${overview.articles.favorite} favoritos`} tone="violet" />
        <StatCard label="Fontes" value={String(overview.feeds.total)} hint={`${overview.feeds.enabled} ativas`} tone="emerald" />
        <StatCard
          label="Recolha"
          value={schedule?.auto_fetch ? "Automática" : "Manual"}
          hint={schedule?.next_run_at ? timeUntil(schedule.next_run_at) : schedule?.cron || "sem agenda"}
          tone={overview.feeds.with_error ? "rose" : "slate"}
        />
      </div>

      {overview.feeds.with_error > 0 && (
        <Notice tone="error">
          {overview.feeds.with_error} fonte(s) com erro na última recolha — ver em <strong>Fontes</strong>.
        </Notice>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3 lg:col-span-2">
          <PanelHeader title="Últimos artigos" hint="O que chegou mais recentemente, de todas as fontes.">
            <Btn onClick={() => ctx.goTo("artigos")}>
              <Inbox size={13} /> Ver todos
            </Btn>
          </PanelHeader>
          {overview.recent.length === 0 ? (
            <EmptyState
              title="Ainda não há artigos"
              hint="Subscreva um feed em Fontes ou escolha uma das Sugestões."
              action={
                <Btn variant="primary" onClick={() => ctx.goTo("sugestoes")}>
                  <Sparkles size={13} /> Ver sugestões
                </Btn>
              }
            />
          ) : (
            <ul className="space-y-1.5">
              {overview.recent.map((article) => (
                <li key={article.id}>
                  <button
                    type="button"
                    onClick={() => onOpenArticle(article.id)}
                    className="flex w-full items-start gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-2.5 text-left transition hover:border-white/14 hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 sm:py-2"
                  >
                    <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${article.read ? "bg-white/20" : "bg-teal-300"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] text-foreground">{article.title}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {article.feed_title} · {timeAgo(article.published_at)}
                      </span>
                    </span>
                    {article.has_digest && <Sparkles size={12} className="mt-1 shrink-0 text-violet-300" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="space-y-3">
          <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <h2 className="mb-2 text-[13px] font-semibold text-foreground">Chegada por dia</h2>
            <MiniBars data={overview.series ?? []} />
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <h2 className="mb-2 text-[13px] font-semibold text-foreground">Fontes por volume</h2>
            {topFeeds.length === 0 ? (
              <p className="text-[11.5px] text-muted-foreground">Sem fontes.</p>
            ) : (
              <ul className="space-y-1.5">
                {topFeeds.slice(0, 5).map((feed) => (
                  <li key={feed.id}>
                    <button
                      type="button"
                      onClick={() => ctx.goTo("artigos", { feedId: feed.id })}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] text-foreground">{feed.title}</span>
                        <span className="mt-1 block h-1 w-full overflow-hidden rounded-full bg-white/8">
                          <span
                            className="block h-full rounded-full bg-gradient-to-r from-teal-500/60 to-teal-300"
                            style={{ width: `${Math.max(4, ((feed.articles ?? 0) / topVolume) * 100)}%` }}
                          />
                        </span>
                      </span>
                      <span className="shrink-0 text-[10.5px] text-muted-foreground">{feed.articles ?? 0}</span>
                      <CountDot value={feed.unread ?? 0} title="por ler" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(overview.trending ?? []).length > 0 && (
            <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
              <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                <Flame size={13} className="text-amber-300" /> Temas do momento
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {overview.trending.map((item) => (
                  <button
                    key={item.term}
                    type="button"
                    onClick={() => ctx.goTo("artigos", { q: item.term })}
                    className="min-h-[34px] rounded-full border border-white/10 bg-white/[0.04] px-2.5 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50"
                  >
                    {item.term} <span className="text-[10px] opacity-70">{item.articles}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
              <SlidersHorizontal size={13} className="text-teal-300" /> Regras automáticas
            </h2>
            {activeRules.length === 0 ? (
              <p className="text-[11.5px] text-muted-foreground">
                Nenhuma regra ativa. Em <strong>Agenda → Regras</strong> pode guardar e etiquetar automaticamente o que interessa.
              </p>
            ) : (
              <>
                <p className="text-[11.5px] text-muted-foreground">
                  {activeRules.length} regra(s) · {ruleHits} artigo(s) tratados
                </p>
                <div className="mt-2 space-y-1">
                  {activeRules.slice(0, 4).map((rule) => (
                    <p key={rule.id} className="truncate text-[11.5px] text-foreground/85">
                      <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">{rule.term}</span>{" "}
                      {(rule.actions || []).join(", ") || "etiquetar"}
                      {rule.tags?.length ? ` → ${rule.tags.join(", ")}` : ""}
                    </p>
                  ))}
                </div>
              </>
            )}
            <Btn className="mt-2" onClick={() => ctx.goTo("agenda")}>
              Abrir a agenda
            </Btn>
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <h2 className="mb-2 text-[13px] font-semibold text-foreground">Pastas</h2>
            {catalogue.folders.length === 0 ? (
              <p className="text-[11.5px] text-muted-foreground">Sem pastas. Crie uma em Pastas para arrumar as fontes.</p>
            ) : (
              <ul className="space-y-1.5">
                {catalogue.folders.map((folder) => (
                  <li key={folder.id}>
                    <button
                      type="button"
                      onClick={() => ctx.goTo("artigos", { feedId: `folder:${folder.id}` })}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50"
                    >
                      <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${TONE_CLASS[folder.color] ?? TONE_CLASS.teal}`}>
                        {folder.feeds ?? 0}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[12px] text-foreground">{folder.name}</span>
                      <CountDot value={folder.unread ?? 0} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {overview.activity.length > 0 && (
        <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
          <h2 className="mb-2 text-[13px] font-semibold text-foreground">Atividade recente</h2>
          <ul className="space-y-1">
            {overview.activity.slice(0, 8).map((item) => (
              <li key={item.id} className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
                <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] uppercase">{item.action}</span>
                <span className="min-w-0 flex-1 truncate text-foreground">{item.subject}</span>
                <span className="shrink-0 text-[10.5px]">{timeAgo(item.at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/* ==========================================================================
   Lista + leitura
   ========================================================================== */
type ReaderFilters = {
  feedId: string | null;
  folderId: string | null;
  q: string;
  unread: boolean | null;
  favorite: boolean;
  saved: boolean;
  tag: string | null;
  order: "asc" | "desc";
};

const readerDefaults = (mode: "inbox" | "saved"): ReaderFilters => ({
  feedId: null,
  folderId: null,
  q: "",
  unread: mode === "saved" ? null : true,
  favorite: false,
  saved: mode === "saved",
  tag: null,
  order: "desc",
});

function ArticleRow({
  article,
  active,
  onOpen,
  onToggle,
}: {
  article: RssArticle;
  active: boolean;
  onOpen: () => void;
  onToggle: (patch: { read?: boolean; favorite?: boolean; saved?: boolean }) => void;
}) {
  return (
    <li>
      <div
        className={[
          "group flex items-start gap-2 rounded-lg border px-2.5 py-2.5 transition sm:py-2",
          active ? "border-teal-300/40 bg-teal-400/[0.08]" : "border-white/8 bg-white/[0.03] hover:border-white/16 hover:bg-white/[0.06]",
        ].join(" ")}
      >
        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${article.read ? "bg-white/20" : "bg-teal-300"}`} />
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50"
        >
          <span className={`block text-[12.5px] leading-snug ${article.read ? "text-foreground/80" : "font-medium text-foreground"}`}>{article.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
            <span className="truncate">{article.feed_title}</span>
            <span>·</span>
            <span>{timeAgo(article.published_at)}</span>
            {article.reading_minutes ? <span className="text-muted-foreground/70">· {article.reading_minutes} min</span> : null}
            {article.has_digest ? <Sparkles size={11} className="text-violet-300" /> : null}
            {(article.tags ?? []).slice(0, 3).map((tag) => (
              <span key={tag} className="rounded-full bg-teal-400/10 px-1.5 text-[10px] text-teal-100">
                {tag}
              </span>
            ))}
          </span>
          {article.summary && <span className="mt-1 line-clamp-2 block text-[11.5px] text-muted-foreground">{article.summary}</span>}
        </button>
        <span className="flex shrink-0 items-center gap-0.5 sm:opacity-70 sm:transition sm:group-hover:opacity-100">
          <button
            type="button"
            title={article.favorite ? "Remover dos favoritos" : "Marcar como favorito"}
            aria-label={article.favorite ? "Remover dos favoritos" : "Marcar como favorito"}
            onClick={() => onToggle({ favorite: !article.favorite })}
            className={`grid min-h-[44px] min-w-[44px] place-items-center rounded transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 sm:min-h-0 sm:min-w-0 sm:p-1 ${
              article.favorite ? "text-amber-300" : "text-muted-foreground"
            }`}
          >
            <Star size={13} fill={article.favorite ? "currentColor" : "none"} />
          </button>
          <button
            type="button"
            title={article.saved ? "Remover dos guardados" : "Guardar"}
            aria-label={article.saved ? "Remover dos guardados" : "Guardar"}
            onClick={() => onToggle({ saved: !article.saved })}
            className={`grid min-h-[44px] min-w-[44px] place-items-center rounded transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 sm:min-h-0 sm:min-w-0 sm:p-1 ${
              article.saved ? "text-sky-300" : "text-muted-foreground"
            }`}
          >
            {article.saved ? <BookmarkCheck size={13} /> : <Bookmark size={13} />}
          </button>
        </span>
      </div>
    </li>
  );
}

export function RssReader({
  ctx,
  mode,
  focusArticleId,
  focusFeedId,
  focusQuery,
}: {
  ctx: RssCtx;
  mode: "inbox" | "saved";
  focusArticleId?: string | null;
  focusFeedId?: string | null;
  focusQuery?: string | null;
}) {
  const [filters, setFilters] = useState<ReaderFilters>(() => readerDefaults(mode));
  const [data, setData] = useState<RssArticleList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [article, setArticle] = useState<RssArticle | null>(null);
  const [related, setRelated] = useState<RssArticle[]>([]);
  const [loadingArticle, setLoadingArticle] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [sentiment, setSentiment] = useState<rss.RssSentimentResult | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [crmOpen, setCrmOpen] = useState(false);
  const [crmAccount, setCrmAccount] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const searchRef = useRef<HTMLInputElement | null>(null);
  /** Focos já tratados (evita reabrir o mesmo artigo a cada render). */
  const handled = useRef<{ article?: string; feed?: string; query?: string }>({});

  const feedOptions = useMemo(
    () => [{ value: "", label: "Todas as fontes" }, ...ctx.catalogue.feeds.map((feed) => ({ value: feed.id, label: feed.title }))],
    [ctx.catalogue.feeds],
  );
  const folderOptions = useMemo(
    () => [{ value: "", label: "Todas as pastas" }, ...ctx.catalogue.folders.map((folder) => ({ value: folder.id, label: folder.name }))],
    [ctx.catalogue.folders],
  );
  const tagOptions = useMemo(() => ctx.catalogue.tags ?? [], [ctx.catalogue.tags]);

  const apiFilters: RssArticleFilters = useMemo(
    () => ({
      feed_id: filters.feedId,
      folder_id: filters.folderId,
      q: filters.q || null,
      unread: filters.unread,
      favorite: filters.favorite ? true : null,
      saved: filters.saved ? true : null,
      tag: filters.tag,
      order: filters.order,
      limit: 40,
    }),
    [filters],
  );

  const load = useCallback(
    async (offset = 0) => {
      setLoading(true);
      setError(null);
      try {
        const payload = await rss.listRssArticles({ ...apiFilters, offset });
        setData((current) => (offset > 0 && current ? { ...payload, items: [...current.items, ...payload.items] } : payload));
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [apiFilters],
  );

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  // Focos pedidos por outra secção (painel, fontes, temas, pesquisa).
  useEffect(() => {
    if (focusFeedId && handled.current.feed !== focusFeedId) {
      handled.current.feed = focusFeedId;
      if (focusFeedId.startsWith("folder:")) {
        const folderId = focusFeedId.slice("folder:".length);
        setFilters((current) => ({ ...current, folderId, feedId: null, unread: null, saved: mode === "saved" }));
      } else {
        setFilters((current) => ({ ...current, feedId: focusFeedId, folderId: null, unread: null, saved: mode === "saved" }));
      }
    }
    if (focusQuery && handled.current.query !== focusQuery) {
      handled.current.query = focusQuery;
      setSearchTerm(focusQuery);
      setFilters((current) => ({ ...current, q: focusQuery, unread: null }));
    }
  }, [focusFeedId, focusQuery, mode]);

  const openArticle = useCallback(
    async (articleId: string) => {
      setLoadingArticle(true);
      setSentiment(null);
      setMobileOpen(true);
      try {
        const payload = await rss.getRssArticle(articleId, true);
        setArticle(payload.article);
        setRelated(payload.related ?? []);
        setData((current) =>
          current ? { ...current, items: current.items.map((item) => (item.id === articleId ? { ...item, read: true } : item)) } : current,
        );
      } catch (err) {
        ctx.notify((err as Error).message, "error");
      } finally {
        setLoadingArticle(false);
      }
    },
    [ctx],
  );

  useEffect(() => {
    if (!focusArticleId || handled.current.article === focusArticleId) return;
    handled.current.article = focusArticleId;
    void openArticle(focusArticleId);
  }, [focusArticleId, openArticle]);

  const toggle = useCallback(
    async (articleId: string, patch: { read?: boolean; favorite?: boolean; saved?: boolean; tags?: string[] }) => {
      try {
        const payload = await rss.patchRssArticle(articleId, patch);
        setData((current) =>
          current ? { ...current, items: current.items.map((item) => (item.id === articleId ? { ...item, ...payload.article } : item)) } : current,
        );
        setArticle((current) => (current && current.id === articleId ? { ...current, ...payload.article } : current));
        ctx.refresh();
      } catch (err) {
        ctx.notify((err as Error).message, "error");
      }
    },
    [ctx],
  );

  const runAction = useCallback(
    async (key: string, label: string, action: () => Promise<string>) => {
      if (!article) return;
      setBusyAction(key);
      try {
        const message = await action();
        ctx.notify(`${label}: ${message}`, "ok");
        ctx.refresh();
      } catch (err) {
        ctx.notify(`${label}: ${(err as Error).message}`, "error");
      } finally {
        setBusyAction(null);
      }
    },
    [article, ctx],
  );

  const markAllRead = useCallback(async () => {
    try {
      const payload = await rss.readAllRssArticles({ feed_id: filters.feedId, folder_id: filters.folderId, q: filters.q || null });
      ctx.notify(`${payload.updated} artigo(s) marcados como lidos.`, "ok");
      void load();
      ctx.refresh();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx, filters, load]);

  const purgeRead = useCallback(async () => {
    try {
      const payload = await rss.purgeReadRssArticles({ feed_id: filters.feedId });
      ctx.notify(`${payload.removed} artigo(s) lidos removidos.`, "ok");
      void load();
      ctx.refresh();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx, filters, load]);

  const submitSearch = useCallback(
    (value?: string) => {
      const next = (value ?? searchTerm).trim();
      setSearchTerm(next);
      setFilters((current) => ({ ...current, q: next }));
    },
    [searchTerm],
  );

  const share = useCallback(async () => {
    if (!article) return;
    const url = article.url || window.location.href;
    try {
      if (typeof navigator !== "undefined" && navigator.share) {
        await navigator.share({ title: article.title, text: (article.summary ?? "").slice(0, 140), url });
        return;
      }
      await navigator.clipboard.writeText(url);
      ctx.notify("Ligação copiada.", "ok");
    } catch {
      /* o utilizador cancelou a partilha */
    }
  }, [article, ctx]);

  // Atalhos de teclado (computador): j/k, Enter/o, s, f, m, /.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if (typing) return;
      const items = data?.items ?? [];
      const index = items.findIndex((item) => item.id === article?.id);
      const move = (delta: number) => {
        const next = items[Math.max(0, Math.min(items.length - 1, (index < 0 ? 0 : index) + delta))];
        if (next) void openArticle(next.id);
      };
      switch (event.key) {
        case "j":
          event.preventDefault();
          move(1);
          break;
        case "k":
          event.preventDefault();
          move(-1);
          break;
        case "Enter":
        case "o":
          if (article?.url) window.open(article.url, "_blank", "noopener");
          break;
        case "s":
          if (article) void toggle(article.id, { saved: !article.saved });
          break;
        case "f":
          if (article) void toggle(article.id, { favorite: !article.favorite });
          break;
        case "m":
          if (article) void toggle(article.id, { read: !article.read });
          break;
        case "/":
          event.preventDefault();
          searchRef.current?.focus();
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [article, data, openArticle, toggle]);

  const selectedFeed = ctx.catalogue.feeds.find((feed) => feed.id === filters.feedId);
  const activeFilterCount =
    (filters.feedId ? 1 : 0) +
    (filters.folderId ? 1 : 0) +
    (filters.q ? 1 : 0) +
    (filters.unread === true ? 1 : 0) +
    (filters.favorite ? 1 : 0) +
    (filters.saved ? 1 : 0) +
    (filters.tag ? 1 : 0);

  const filtersNode = (
    <div className="space-y-3">
      <div className="relative">
        <Search size={13} className="absolute left-2.5 top-3 text-muted-foreground" />
        <input
          ref={searchRef}
          className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-2 pl-8 pr-3 text-[12.5px] outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
          placeholder="Pesquisar nos artigos…  ( / )"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitSearch();
          }}
        />
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Chip active={filters.unread === true} onClick={() => setFilters((c) => ({ ...c, unread: c.unread === true ? null : true }))}>
          Por ler
        </Chip>
        <Chip active={filters.favorite} onClick={() => setFilters((c) => ({ ...c, favorite: !c.favorite }))}>
          Favoritos
        </Chip>
        <Chip active={filters.saved} onClick={() => setFilters((c) => ({ ...c, saved: !c.saved }))}>
          Guardados
        </Chip>
        <Chip active={filters.order === "asc"} onClick={() => setFilters((c) => ({ ...c, order: c.order === "asc" ? "desc" : "asc" }))} title="Ordenar pela data">
          {filters.order === "asc" ? "Mais antigos" : "Mais recentes"}
        </Chip>
      </div>
      {tagOptions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tagOptions.slice(0, 10).map((tag) => (
            <Chip key={tag} active={filters.tag === tag} onClick={() => setFilters((c) => ({ ...c, tag: c.tag === tag ? null : tag }))}>
              #{tag}
            </Chip>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        <select
          aria-label="Filtrar por pasta"
          className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 text-[12px] outline-none focus:border-teal-300/40 sm:min-h-[34px]"
          value={filters.folderId ?? ""}
          onChange={(event) => setFilters((c) => ({ ...c, folderId: event.target.value || null, feedId: null }))}
        >
          {folderOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Filtrar por fonte"
          className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 text-[12px] outline-none focus:border-teal-300/40 sm:min-h-[34px]"
          value={filters.feedId ?? ""}
          onChange={(event) => setFilters((c) => ({ ...c, feedId: event.target.value || null }))}
        >
          {feedOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap gap-2">
        <Btn onClick={() => setFilters(readerDefaults(mode))}>
          <RefreshCw size={12} /> Limpar filtros
        </Btn>
        <Btn onClick={() => void markAllRead()}>
          <Mail size={12} /> Marcar tudo como lido
        </Btn>
        <Btn onClick={() => void purgeRead()}>
          <Trash2 size={12} /> Limpar lidos
        </Btn>
      </div>
      {data && (
        <p className="text-[11.5px] text-muted-foreground">
          {data.total} artigo(s) no filtro · {data.unread} por ler no total
        </p>
      )}
    </div>
  );

  return (
    <div className="flex h-full min-h-0 gap-3">
      {/* Índice */}
      <div className={["flex min-h-0 min-w-0 flex-col lg:w-[420px] lg:shrink-0", mobileOpen ? "hidden lg:flex" : "flex w-full"].join(" ")}>
        <div className="mb-2 space-y-2">
          <div className="hidden lg:block">{filtersNode}</div>

          {/* Barra do telemóvel/tablet: pesquisa, filtros e atualizar */}
          <div className="flex items-center gap-2 lg:hidden">
            <Btn onClick={() => setFiltersOpen(true)} title="Abrir filtros">
              <ListFilter size={14} /> Filtros
              {activeFilterCount > 0 && <span className="rounded-full bg-teal-400/20 px-1.5 text-[10px] text-teal-100">{activeFilterCount}</span>}
            </Btn>
            <Btn onClick={() => void load()} title="Atualizar a lista">
              <RefreshCw size={14} /> Atualizar
            </Btn>
            <div className="min-w-0 flex-1" />
            <IconAction title="Exportar CSV" onClick={() => window.open(rss.rssExportUrl(apiFilters, "csv"), "_blank")}>
              <Download size={14} />
            </IconAction>
          </div>

          <div className="hidden items-center gap-1.5 lg:flex">
            <Btn onClick={() => void load()}>
              <RefreshCw size={12} /> Atualizar
            </Btn>
            <a
              href={rss.rssExportUrl(apiFilters, "csv")}
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground"
            >
              <Download size={12} /> CSV
            </a>
            <a
              href={rss.rssExportUrl(apiFilters, "md")}
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground"
            >
              <FileType2 size={12} /> Markdown
            </a>
            <Btn variant="ghost" onClick={() => setShortcutsOpen(true)} title="Atalhos de teclado">
              <Keyboard size={13} />
            </Btn>
          </div>

          <p className="text-[11px] text-muted-foreground">
            {data ? `${data.total} artigo(s)` : "—"}
            {selectedFeed ? ` de ${selectedFeed.title}` : ""} · {data?.unread ?? 0} por ler
            {filters.tag ? ` · #${filters.tag}` : ""}
            {filters.q ? ` · «${filters.q}»` : ""}
          </p>
        </div>

        {error && (
          <div className="mb-2">
            <Notice tone="error">{error}</Notice>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
          {loading && !data ? (
            <p className="flex items-center gap-2 py-8 text-[12.5px] text-muted-foreground">
              <Loader2 size={14} className="animate-spin" /> A carregar…
            </p>
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              title={mode === "saved" ? "Sem artigos guardados" : "Sem artigos"}
              hint="Recolha as fontes ou alargue os filtros (por ler, pasta, fonte, etiqueta)."
              action={
                <Btn variant="primary" onClick={() => ctx.goTo("fontes")}>
                  <Rss size={13} /> Ver as fontes
                </Btn>
              }
            />
          ) : (
            <>
              <ul className="space-y-1.5">
                {data.items.map((item) => (
                  <ArticleRow
                    key={item.id}
                    article={item}
                    active={article?.id === item.id}
                    onOpen={() => void openArticle(item.id)}
                    onToggle={(patch) => void toggle(item.id, patch)}
                  />
                ))}
              </ul>
              {data.has_more && (
                <Btn wide className="mt-2" onClick={() => void load(data.items.length)}>
                  Carregar mais ({data.total - data.items.length})
                </Btn>
              )}
            </>
          )}
        </div>
      </div>

      {/* Leitura */}
      <div
        className={[
          "min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain rounded-xl border border-white/8 bg-white/[0.02]",
          mobileOpen ? "block" : "hidden lg:block",
        ].join(" ")}
      >
        {!article ? (
          <div className="flex h-full items-center justify-center p-3">
            <EmptyState
              title="Escolha um artigo"
              hint="O texto completo, as etiquetas, os temas relacionados e as ações (IA, Office, sentimento, CRM, RAG) aparecem aqui."
            />
          </div>
        ) : (
          <>
            {/* Cabeçalho colado: voltar (telemóvel), partilhar e abrir original */}
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-white/8 bg-[#08181f]/95 px-3 py-2 backdrop-blur">
              <Btn className="lg:hidden" onClick={() => setMobileOpen(false)} title="Voltar à lista">
                <ArrowLeft size={14} /> Lista
              </Btn>
              <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground">
                {article.feed_title} · {fullDate(article.published_at)}
              </span>
              <IconAction title="Partilhar" onClick={() => void share()}>
                <Share2 size={14} />
              </IconAction>
              {article.url && (
                <a
                  href={article.url}
                  target="_blank"
                  rel="noreferrer"
                  title="Abrir o original"
                  aria-label="Abrir o original"
                  className="grid min-h-[44px] min-w-[44px] place-items-center rounded-md border border-white/8 bg-white/[0.04] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground sm:min-h-0 sm:min-w-0 sm:p-1.5"
                >
                  <ExternalLink size={14} />
                </a>
              )}
            </div>

            <article className="mx-auto max-w-[820px] p-3 pb-16 sm:pb-6">
              <h1 className="text-[16px] font-semibold leading-snug text-foreground sm:text-[18px]">{article.title}</h1>
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
                {article.author && <span>{article.author}</span>}
                {article.reading_minutes ? <span>· {article.reading_minutes} min de leitura</span> : null}
                {article.published_at ? <span>· {timeAgo(article.published_at)}</span> : null}
              </p>

              {/* Ações: linha deslizável no telemóvel, enrolada no computador */}
              <div className="-mx-3 mt-3 flex gap-1.5 overflow-x-auto px-3 pb-1 lg:mx-0 lg:flex-wrap lg:px-0">
                <Chip active={article.favorite} onClick={() => void toggle(article.id, { favorite: !article.favorite })}>
                  <Star size={11} className="mr-1 inline" fill={article.favorite ? "currentColor" : "none"} />
                  Favorito
                </Chip>
                <Chip active={article.saved} onClick={() => void toggle(article.id, { saved: !article.saved })}>
                  <Bookmark size={11} className="mr-1 inline" />
                  Guardar
                </Chip>
                <Chip active={article.read} onClick={() => void toggle(article.id, { read: !article.read })}>
                  {article.read ? "Lido" : "Não lido"}
                </Chip>
                <Btn
                  variant="ai"
                  disabled={busyAction !== null}
                  onClick={() =>
                    void runAction("digest", "Resumo IA", async () => {
                      const payload = await rss.rssArticleDigest(article.id);
                      setArticle((current) => (current ? { ...current, digest: payload.digest, has_digest: true } : current));
                      return "resumo criado";
                    })
                  }
                >
                  {busyAction === "digest" ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} Resumo IA
                </Btn>
                <Btn
                  disabled={busyAction !== null}
                  onClick={() =>
                    void runAction("office", "Office", async () => {
                      const payload = await rss.rssArticleToOffice(article.id);
                      return `documento «${payload.document.title}» criado`;
                    })
                  }
                >
                  {busyAction === "office" ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />} Office
                </Btn>
                <Btn
                  disabled={busyAction !== null}
                  onClick={() =>
                    void runAction("sentiment", "Sentimento", async () => {
                      const payload = await rss.rssArticleSentiment(article.id);
                      setSentiment(payload);
                      const label = String((payload.analysis as { label?: string } | undefined)?.label ?? "");
                      return label ? `resultado: ${label}` : "análise concluída";
                    })
                  }
                >
                  {busyAction === "sentiment" ? <Loader2 size={12} className="animate-spin" /> : <Flame size={12} />} Sentimento
                </Btn>
                <Btn onClick={() => setCrmOpen(true)}>
                  <Building2 size={12} /> CRM
                </Btn>
                <Btn
                  disabled={busyAction !== null}
                  onClick={() =>
                    void runAction("rag", "RAG", async () => {
                      const payload = await rss.rssArticleToRag(article.id);
                      return `${payload.chunks} fragmento(s) indexados`;
                    })
                  }
                >
                  {busyAction === "rag" ? <Loader2 size={12} className="animate-spin" /> : <Layers size={12} />} RAG
                </Btn>
              </div>

              {/* Etiquetas do artigo */}
              <section className="mt-3 rounded-xl border border-white/8 bg-white/[0.03] p-2.5">
                <p className="mb-1 text-[11px] font-medium text-muted-foreground">Etiquetas do artigo</p>
                <TagEditor value={article.tags ?? []} onChange={(next) => void toggle(article.id, { tags: next })} suggestions={tagOptions} hint="etiquetar…" />
                {(article.feed_tags?.length ?? 0) > 0 && (
                  <p className="mt-1 text-[10.5px] text-muted-foreground/80">Da fonte: {(article.feed_tags ?? []).join(", ")}</p>
                )}
              </section>

              {article.digest && (
                <section className="mt-3 rounded-xl border border-violet-400/25 bg-violet-500/[0.08] p-3">
                  <h2 className="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold text-violet-100">
                    <Sparkles size={13} /> Resumo (IA)
                  </h2>
                  <div className="whitespace-pre-line text-[12.5px] leading-relaxed text-foreground/90">{article.digest}</div>
                </section>
              )}

              {sentiment && (
                <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
                  <h2 className="mb-1 text-[12.5px] font-semibold text-foreground">Sentimento</h2>
                  <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap text-[11.5px] text-muted-foreground">
                    {JSON.stringify(sentiment.analysis, null, 2)}
                  </pre>
                </section>
              )}

              {loadingArticle ? (
                <p className="flex items-center gap-2 py-6 text-[12.5px] text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" /> A abrir o artigo…
                </p>
              ) : (
                <div className="mt-3 whitespace-pre-line text-[13.5px] leading-[1.75] text-foreground/90 sm:text-[13px]">
                  {plainFromHtml(article.content || article.summary) || "O feed não enviou o texto do artigo. Use «Original» para o ler no sítio de origem."}
                </div>
              )}

              {(article.categories?.length ?? 0) > 0 && (
                <div className="mt-4 flex flex-wrap gap-1.5 border-t border-white/8 pt-3">
                  {article.categories?.map((category) => (
                    <button
                      key={category}
                      type="button"
                      onClick={() => ctx.goTo("artigos", { q: category })}
                      className="min-h-[34px] rounded-full border border-sky-400/25 bg-sky-400/10 px-2.5 text-[11px] text-sky-100 transition hover:bg-sky-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50"
                    >
                      {category}
                    </button>
                  ))}
                </div>
              )}

              {related.length > 0 && (
                <section className="mt-4 border-t border-white/8 pt-3">
                  <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                    <ChevronRight size={14} className="text-teal-300" /> Também sobre este tema
                  </h2>
                  <ul className="space-y-1.5">
                    {related.map((item) => (
                      <li key={item.id}>
                        <button
                          type="button"
                          onClick={() => void openArticle(item.id)}
                          className="flex w-full items-start gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-2.5 text-left transition hover:border-white/14 hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 sm:py-2"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block text-[12.5px] leading-snug text-foreground/90">{item.title}</span>
                            <span className="mt-0.5 block truncate text-[10.5px] text-muted-foreground">
                              {item.feed_title} · {timeAgo(item.published_at)}
                            </span>
                          </span>
                          <span className="mt-0.5 shrink-0 text-[10.5px] text-muted-foreground">{(item.score ?? 0) >= 6 ? "mesmo tema" : "relacionado"}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </article>
          </>
        )}
      </div>

      {filtersOpen && (
        <Sheet title="Filtros" subtitle="Refine o que aparece no índice." onClose={() => setFiltersOpen(false)}>
          {filtersNode}
        </Sheet>
      )}

      {shortcutsOpen && (
        <Sheet title="Atalhos de teclado" subtitle="Funcionam quando o cursor não está num campo de texto." onClose={() => setShortcutsOpen(false)}>
          <ul className="space-y-1.5 text-[12.5px] text-muted-foreground">
            {[
              ["j / k", "artigo seguinte / anterior"],
              ["Enter ou o", "abrir o original no browser"],
              ["s", "guardar / remover dos guardados"],
              ["f", "favorito"],
              ["m", "marcar como lido / não lido"],
              ["/", "ir para a pesquisa"],
            ].map(([key, label]) => (
              <li key={key} className="flex items-center gap-2">
                <kbd className="rounded border border-white/12 bg-white/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-foreground">{key}</kbd>
                <span>{label}</span>
              </li>
            ))}
          </ul>
        </Sheet>
      )}

      {crmOpen && article && (
        <Sheet
          title="Registar no CRM"
          subtitle="Cria uma nota (atividade) com a ligação para o artigo."
          onClose={() => setCrmOpen(false)}
          busy={busyAction === "crm"}
          footer={
            <>
              <Btn onClick={() => setCrmOpen(false)}>Cancelar</Btn>
              <Btn
                variant="primary"
                disabled={busyAction === "crm"}
                onClick={() =>
                  void runAction("crm", "CRM", async () => {
                    const payload = await rss.rssArticleToCrm(article.id, crmAccount.trim() || null);
                    setCrmOpen(false);
                    return `nota criada (${payload.item.subject.slice(0, 60)})`;
                  })
                }
              >
                Criar nota
              </Btn>
            </>
          }
        >
          <TextInput label="Conta do CRM (id, opcional)" value={crmAccount} onChange={setCrmAccount} hint="Deixe vazio para criar a nota sem conta associada." />
        </Sheet>
      )}
    </div>
  );
}

/* ==========================================================================
   Integrações
   ========================================================================== */
export function RssIntegrationsPanel({ ctx }: { ctx: RssCtx }) {
  const [folderId, setFolderId] = useState<string>("");
  const [limit, setLimit] = useState(12);
  const [busy, setBusy] = useState<string | null>(null);
  const [digest, setDigest] = useState<{ markdown: string; articles: number; ai?: rss.RssAiInfo } | null>(null);

  const buildDigest = useCallback(async () => {
    setBusy("digest");
    try {
      const payload = await rss.rssDigestCollection({ folder_id: folderId || null, unread: true, limit, save_to_office: false });
      setDigest({ markdown: payload.markdown, articles: payload.articles, ai: payload.ai });
      ctx.notify(`Boletim com ${payload.articles} artigo(s).`, "ok");
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }, [ctx, folderId, limit]);

  const saveDigest = useCallback(async () => {
    if (!digest) return;
    setBusy("office");
    try {
      const payload = await rss.rssDigestCollection({ folder_id: folderId || null, unread: true, limit, save_to_office: true });
      setDigest({ markdown: payload.markdown, articles: payload.articles, ai: payload.ai });
      ctx.notify(payload.office?.ok ? "Boletim guardado no Office." : `Office: ${payload.office?.error ?? "falhou"}`, payload.office?.ok ? "ok" : "error");
      ctx.refresh();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }, [ctx, digest, folderId, limit]);

  const cards: { icon: ReactNode; title: string; hint: string }[] = [
    { icon: <FileText size={15} />, title: "Office", hint: "Cada artigo abre como nota em Markdown com a fonte e a ligação original." },
    { icon: <Flame size={15} />, title: "Sentimento", hint: "O motor de sentimento da plataforma analisa o texto do artigo." },
    { icon: <Building2 size={15} />, title: "CRM", hint: "O artigo é registado como atividade (nota) numa conta, com o resumo." },
    { icon: <Layers size={15} />, title: "RAG", hint: "O artigo é convertido em Markdown, dividido em fragmentos e indexado." },
    { icon: <Sparkles size={15} />, title: "IA", hint: "Resumo de um artigo ou boletim dos não lidos, com o fornecedor configurado." },
    { icon: <Download size={15} />, title: "Exportar", hint: "CSV (Excel) ou Markdown dos artigos, com os filtros da lista — no índice." },
  ];

  const fileLink = "inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground sm:min-h-[34px]";

  return (
    <div className="space-y-4">
      <PanelHeader
        title="Integrações"
        hint="O leitor não vive isolado: qualquer artigo pode seguir para o Office, o sentimento, o CRM e o RAG, e a IA resume o que interessa."
      />

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <div key={card.title} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className="flex items-center gap-2 text-[12.5px] font-semibold text-foreground">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/[0.06] text-teal-200">{card.icon}</span>
              {card.title}
            </p>
            <p className="mt-1.5 text-[11.5px] text-muted-foreground">{card.hint}</p>
          </div>
        ))}
      </div>

      <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <PanelHeader title="Boletim por IA" hint="Resume os artigos por ler (opcionalmente de uma pasta) e pode guardá-lo no Office como relatório." />
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex w-[200px] flex-col gap-1 sm:w-[240px]">
            <span className="text-[11.5px] font-medium text-muted-foreground">Pasta</span>
            <select
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 text-[12px] outline-none focus:border-teal-300/40 sm:min-h-[34px]"
              value={folderId}
              onChange={(event) => setFolderId(event.target.value)}
            >
              <option value="">Todas as pastas</option>
              {ctx.catalogue.folders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex w-[110px] flex-col gap-1">
            <span className="text-[11.5px] font-medium text-muted-foreground">Artigos</span>
            <input
              type="number"
              min={1}
              max={24}
              className="min-h-[44px] w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 text-[12px] outline-none focus:border-teal-300/40 sm:min-h-[34px]"
              value={limit}
              onChange={(event) => setLimit(Math.max(1, Math.min(24, Number(event.target.value) || 12)))}
            />
          </label>
          <Btn variant="ai" disabled={busy !== null} onClick={() => void buildDigest()}>
            {busy === "digest" ? <Loader2 size={12} className="animate-spin" /> : <Bot size={12} />} Preparar boletim
          </Btn>
          <Btn disabled={busy !== null || !digest} onClick={() => void saveDigest()}>
            {busy === "office" ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />} Guardar no Office
          </Btn>
          <Btn className="sm:ml-auto" onClick={() => ctx.goTo("artigos")}>
            <ChevronRight size={12} /> Ir para os artigos
          </Btn>
        </div>
        {digest && (
          <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11.5px] text-muted-foreground">
              {digest.articles} artigo(s){digest.ai?.model ? ` · ${digest.ai.model}` : ""}
            </p>
            <pre className="max-h-[320px] overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-foreground/90">{digest.markdown}</pre>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <PanelHeader title="Ligações rápidas" hint="Atalhos para as aplicações onde os artigos passam a viver." />
        <div className="flex flex-wrap gap-2">
          <a href="/office" className={fileLink}>
            <FileText size={12} /> Office
          </a>
          <a href="/sentimento" className={fileLink}>
            <Flame size={12} /> Sentimento
          </a>
          <a href="/crm" className={fileLink}>
            <Building2 size={12} /> CRM
          </a>
          <a href="/rag" className={fileLink}>
            <Layers size={12} /> RAG
          </a>
          <a href={rss.rssOpmlUrl()} className={fileLink}>
            <Rss size={12} /> Exportar OPML
          </a>
          <a href={rss.rssExportUrl({}, "csv")} className={fileLink}>
            <Download size={12} /> Exportar artigos (CSV)
          </a>
        </div>
      </section>
    </div>
  );
}
