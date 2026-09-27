/**
 * Leitor de RSS do IQ OS — painel, artigos, guardados, fontes, pastas,
 * sugestões, agenda e integrações.
 *
 * A aplicação onde se lê a imprensa: subscreve feeds (RSS/Atom) por endereço ou
 * OPML, agrupa-os em pastas, recolhe os artigos à mão ou por agenda cron, lê e
 * marca (lido, favorito, guardado) — e leva qualquer artigo para o Office, o
 * sentimento, o CRM ou o RAG, com resumo por IA.
 *
 * A secção vive no caminho (`/rss/artigos`, `/rss/fontes`, …), como no CMS e na
 * Loja: só existe a vista `rss` no `App.tsx`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bookmark,
  CalendarClock,
  Inbox,
  Layers,
  Loader2,
  Rss,
  Search,
  Sparkles,
  LayoutDashboard,
  RefreshCw,
  FolderTree,
  X,
} from "lucide-react";

import * as rss from "../rssApi";
import type { RssCatalogue, RssOverview, RssSearchHit } from "../rssApi";
import { Notice } from "../components/rss/RssKit";
import {
  RssIntegrationsPanel,
  RssOverviewPanel,
  RssReader,
  type RssCtx,
  type RssFocus,
  type RssSection,
  type RssTone,
} from "./RssPanels";
import { RssFeedsPanel, RssFoldersPanel, RssRulesPanel, RssSchedulePanel, RssSuggestionsPanel } from "./RssLibrary";

export const RSS_SECTIONS: { id: RssSection; label: string; path: string; icon: React.ReactNode; hint: string }[] = [
  { id: "painel", label: "Painel", path: "/rss", icon: <LayoutDashboard size={13} />, hint: "Panorama, fontes com mais por ler e temas do momento" },
  { id: "artigos", label: "Artigos", path: "/rss/artigos", icon: <Inbox size={13} />, hint: "Lista e leitura: filtrar, ler, favoritar e guardar" },
  { id: "guardados", label: "Guardados", path: "/rss/guardados", icon: <Bookmark size={13} />, hint: "O que ficou marcado para ler ou reutilizar" },
  { id: "fontes", label: "Fontes", path: "/rss/fontes", icon: <Rss size={13} />, hint: "Subscrever feeds, importar/exportar OPML e recolher" },
  { id: "pastas", label: "Pastas", path: "/rss/pastas", icon: <FolderTree size={13} />, hint: "Agrupar as fontes por tema" },
  { id: "sugestoes", label: "Sugestões", path: "/rss/sugestoes", icon: <Sparkles size={13} />, hint: "Catálogo de fontes de economia, mercados e reguladores" },
  { id: "agenda", label: "Agenda", path: "/rss/agenda", icon: <CalendarClock size={13} />, hint: "Recolha automática (cron), regras automáticas, limites e retenção" },
  { id: "integracoes", label: "Integrações", path: "/rss/integracoes", icon: <Layers size={13} />, hint: "Office, sentimento, CRM, RAG e boletins por IA" },
];

/** Secção a partir do caminho (`/rss/...`). */
export function rssSectionFromPath(path: string): RssSection {
  const clean = (path || "").replace(/\/+$/, "");
  const found = RSS_SECTIONS.find((section) => section.path === clean);
  return found ? found.id : "painel";
}

export function rssPathForSection(section: RssSection): string {
  return RSS_SECTIONS.find((entry) => entry.id === section)?.path ?? "/rss";
}

export default function RssPage() {
  const [section, setSection] = useState<RssSection>(() => (typeof window === "undefined" ? "painel" : rssSectionFromPath(window.location.pathname)));
  const [catalogue, setCatalogue] = useState<RssCatalogue | null>(null);
  const [overview, setOverview] = useState<RssOverview | null>(null);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; message: string; tone: RssTone }[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RssSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [focus, setFocus] = useState<RssFocus>({});
  const focusToken = useRef(0);

  const notify = useCallback((message: string, tone: RssTone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4600);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cataloguePayload, overviewPayload] = await Promise.all([rss.getRssCatalogue(), rss.getRssOverview()]);
      setCatalogue(cataloguePayload);
      setOverview(overviewPayload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A navegação da secção vive no caminho: `/rss/artigos`, `/rss/fontes`, …
  useEffect(() => {
    const onPop = () => setSection(rssSectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const changeSection = useCallback((next: RssSection, target?: RssFocus) => {
    setSection(next);
    setFocus(target ? { ...target } : {});
    focusToken.current += 1;
    if (typeof window !== "undefined") {
      const path = rssPathForSection(next);
      if (window.location.pathname !== path) window.history.pushState({}, "", path);
    }
  }, []);

  const ctx: RssCtx = useMemo(
    () => ({
      catalogue: catalogue ?? ({} as RssCatalogue),
      overview,
      version,
      notify,
      refresh: () => void load(),
      bumpData: () => setVersion((current) => current + 1),
      goTo: changeSection,
    }),
    [catalogue, overview, version, notify, load, changeSection],
  );

  // Pesquisa global (artigos e fontes) com atraso curto.
  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setHits([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      void rss
        .searchRss(needle)
        .then((payload) => {
          if (!cancelled) setHits(payload.items);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 260);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const openHit = useCallback(
    (hit: RssSearchHit) => {
      setHits([]);
      setQuery("");
      if (hit.kind === "article") changeSection("artigos", { articleId: hit.id });
      else changeSection("artigos", { feedId: hit.id });
    },
    [changeSection],
  );

  const collectAll = useCallback(async () => {
    setBusy(true);
    try {
      const payload = await rss.fetchAllRssFeeds(false);
      notify(
        `Recolha: ${payload.feeds} fonte(s), ${payload.added} artigo(s) novos${payload.errors ? `, ${payload.errors} com erro` : ""}.`,
        payload.errors ? "error" : "ok",
      );
      setVersion((current) => current + 1);
      await load();
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }, [load, notify]);

  const totals = catalogue?.totals;
  const inReader = section === "artigos" || section === "guardados";

  return (
    <div className="@container relative flex h-full min-h-[520px] flex-col bg-background text-foreground">
      <header className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 pb-2 pt-2 backdrop-blur-xl md:top-0">
        <div className="flex flex-wrap items-center gap-2 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-orange-200 via-amber-400 to-rose-500 text-white">
            <Rss size={15} />
          </span>
          <h1 className="text-[14px] font-semibold">Leitor RSS</h1>
          {totals && (
            <>
              <span className="rounded-full bg-teal-400/15 px-2 py-0.5 text-[10.5px] text-teal-100">{totals.unread} por ler</span>
              <span className="hidden rounded-full bg-white/[0.08] px-2 py-0.5 text-[10.5px] text-muted-foreground sm:inline-block">
                {totals.articles} artigo(s) · {totals.feeds} fonte(s)
              </span>
            </>
          )}
          {overview?.schedule?.auto_fetch && overview.schedule.next_run_at && (
            <span className="hidden rounded-full bg-sky-400/15 px-2 py-0.5 text-[10.5px] text-sky-100 sm:inline-block">
              próxima recolha {new Date(overview.schedule.next_run_at).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {overview && overview.feeds.with_error > 0 && (
            <span className="rounded-full bg-rose-400/15 px-2 py-0.5 text-[10.5px] text-rose-100">{overview.feeds.with_error} com erro</span>
          )}
          <div className="min-w-0 flex-1" />

          {/* No telemóvel, pesquisa + ações ocupam uma linha própria. */}
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <div className="relative min-w-0 flex-1 sm:flex-none">
              <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
              <input
                className="min-h-[40px] w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-7 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40 sm:w-[min(280px,60vw)]"
                placeholder="Pesquisar artigos e fontes…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            {query && (
              <button type="button" className="absolute right-2 top-2 text-muted-foreground hover:text-foreground" onClick={() => setQuery("")} title="Limpar">
                <X size={13} />
              </button>
            )}
            {(hits.length > 0 || searching) && (
              <div className="absolute right-0 top-full z-30 mt-1 w-[min(440px,92vw)] rounded-xl border border-white/12 bg-[#08181f] p-1.5 shadow-2xl">
                {searching && <p className="px-2 py-1.5 text-[11.5px] text-muted-foreground">A procurar…</p>}
                {hits.map((hit) => (
                  <button
                    key={`${hit.kind}-${hit.id}`}
                    type="button"
                    onClick={() => openHit(hit)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.08]"
                  >
                    <span className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                      {hit.kind === "article" ? "artigo" : "fonte"}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] text-foreground">{hit.title || "(sem título)"}</span>
                      <span className="block truncate text-[10.5px] text-muted-foreground">{hit.subtitle}</span>
                    </span>
                    {hit.kind === "feed" && hit.unread ? <span className="text-[10px] text-teal-200">{hit.unread}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            disabled={busy}
            onClick={() => void collectAll()}
            className="flex min-h-[44px] items-center gap-1.5 rounded-lg border border-teal-300/40 bg-teal-500/15 px-2.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 disabled:opacity-50 sm:min-h-[34px]"
            title="Recolher todas as fontes ativas"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Recolher
          </button>
          <button
            type="button"
            onClick={() => {
              void load();
              notify("Atualizado.", "ok");
            }}
            className="flex min-h-[44px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 sm:min-h-[34px]"
            title="Recarregar o leitor"
          >
            <RefreshCw size={13} /> Atualizar
          </button>
          </div>
        </div>

        <div className="mx-4 mt-2 flex flex-nowrap items-center gap-1 overflow-x-auto rounded-[8px] border border-white/8 bg-white/[0.05] p-0.5 [scrollbar-width:none] md:flex-wrap [&::-webkit-scrollbar]:hidden">
          {RSS_SECTIONS.map((entry) => {
            const active = section === entry.id;
            return (
              <button
                key={entry.id}
                type="button"
                role="tab"
                aria-selected={active}
                title={entry.hint}
                onClick={() => changeSection(entry.id)}
                className={[
                  "flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 text-[12px] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/50 md:min-h-0 md:py-1",
                  active ? "bg-white/[0.16] font-medium text-foreground shadow-sm" : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
                ].join(" ")}
              >
                <span className={active ? "text-teal-300" : undefined}>{entry.icon}</span>
                <span className="whitespace-nowrap">{entry.label}</span>
                {entry.id === "artigos" && totals?.unread ? <span className="rounded-full bg-teal-400/20 px-1.5 text-[10px] text-teal-100">{totals.unread}</span> : null}
                {entry.id === "guardados" && totals?.saved ? <span className="rounded-full bg-sky-400/20 px-1.5 text-[10px] text-sky-100">{totals.saved}</span> : null}
              </button>
            );
          })}
        </div>
      </header>

      <div className={["min-h-0 flex-1 px-3 py-3 sm:px-4 sm:py-4", inReader ? "overflow-hidden" : "overflow-y-auto"].join(" ")}>
        {error && (
          <div className="mb-3">
            <Notice tone="error">
              <AlertTriangle size={12} className="mr-1 inline" /> {error}
            </Notice>
          </div>
        )}

        {loading || !catalogue ? (
          <p className="flex items-center gap-2 py-16 text-[12.5px] text-muted-foreground">
            <Loader2 size={15} className="animate-spin" /> A carregar o leitor…
          </p>
        ) : section === "painel" ? (
          <RssOverviewPanel ctx={ctx} onOpenArticle={(articleId) => changeSection("artigos", { articleId })} />
        ) : section === "artigos" ? (
          <RssReader
            key={`inbox-${focusToken.current}`}
            ctx={ctx}
            mode="inbox"
            focusArticleId={focus.articleId}
            focusFeedId={focus.feedId}
            focusQuery={focus.q}
          />
        ) : section === "guardados" ? (
          <RssReader
            key={`saved-${focusToken.current}`}
            ctx={ctx}
            mode="saved"
            focusArticleId={focus.articleId}
            focusFeedId={focus.feedId}
            focusQuery={focus.q}
          />
        ) : section === "fontes" ? (
          <RssFeedsPanel ctx={ctx} />
        ) : section === "pastas" ? (
          <RssFoldersPanel ctx={ctx} />
        ) : section === "sugestoes" ? (
          <RssSuggestionsPanel ctx={ctx} />
        ) : section === "agenda" ? (
          <div className="space-y-4">
            <RssSchedulePanel ctx={ctx} />
            <RssRulesPanel ctx={ctx} />
          </div>
        ) : (
          <RssIntegrationsPanel ctx={ctx} />
        )}
      </div>

      <div className="pointer-events-none fixed bottom-20 right-4 z-[140] flex flex-col items-end gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={[
              "pointer-events-auto max-w-[min(400px,calc(100vw-2rem))] rounded-xl border px-3 py-2 text-[12px] shadow-xl backdrop-blur",
              toast.tone === "error"
                ? "border-rose-400/30 bg-rose-500/15 text-rose-100"
                : toast.tone === "ok"
                  ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-100"
                  : "border-white/12 bg-[#0b1a24]/95 text-foreground",
            ].join(" ")}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
