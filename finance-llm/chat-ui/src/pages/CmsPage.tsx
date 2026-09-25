/**
 * CMS IQ OS — páginas e conteúdos do site, blog, media e publicação.
 *
 * A aplicação onde se **escreve o site**: páginas construídas por blocos,
 * artigos de blog em Markdown, conteúdos reutilizáveis, biblioteca de media,
 * modelos, taxonomia, menus e aparência. Tudo com rascunho, agendamento,
 * publicação imediata, histórico de revisões e auditoria.
 *
 * O resultado público vive em `/site/…` (aplicado pela própria API, com URLs
 * legíveis, RSS, sitemap e `robots.txt`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  FileText,
  Globe2,
  Hash,
  LayoutDashboard,
  Loader2,
  Newspaper,
  Palette,
  RefreshCw,
  Recycle,
  Search,
  X,
} from "lucide-react";

import { CmsAppearancePanel, CmsContentsPanel, CmsMediaPanel, CmsTaxonomyPanel, CmsTemplatesPanel } from "./CmsLibrary";
import { CmsOverviewPanel, CmsPagesPanel, CmsPostsPanel, type CmsCtx, type CmsSection } from "./CmsPanels";
import { Notice } from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsCatalogue, CmsOverview, CmsSearchHit } from "../cmsApi";

export const CMS_SECTIONS: { id: CmsSection; label: string; path: string; icon: React.ReactNode; hint: string }[] = [
  { id: "painel", label: "Painel", path: "/cms", icon: <LayoutDashboard size={13} />, hint: "Panorama, agendamentos e atividade" },
  { id: "paginas", label: "Páginas", path: "/cms/paginas", icon: <FileText size={13} />, hint: "Páginas por blocos, com hierarquia e menu" },
  { id: "conteudos", label: "Conteúdos", path: "/cms/conteudos", icon: <Recycle size={13} />, hint: "Blocos com nome, reutilizados em várias páginas" },
  { id: "blog", label: "Blog", path: "/cms/blog", icon: <Newspaper size={13} />, hint: "Artigos, categorias, etiquetas e capas" },
  { id: "media", label: "Media", path: "/cms/media", icon: <BookOpen size={13} />, hint: "Biblioteca de imagens e documentos" },
  { id: "taxonomia", label: "Taxonomia", path: "/cms/taxonomia", icon: <Hash size={13} />, hint: "Categorias e etiquetas do blog" },
  { id: "modelos", label: "Modelos", path: "/cms/modelos", icon: <Palette size={13} />, hint: "Estruturas de blocos prontas a usar" },
  { id: "aparencia", label: "Aparência", path: "/cms/aparencia", icon: <Globe2 size={13} />, hint: "Definições do site, menus, SEO e rodapé" },
];

/** Secção a partir do caminho (`/cms/...`). */
export function cmsSectionFromPath(path: string): CmsSection {
  const clean = (path || "").replace(/\/+$/, "");
  const found = CMS_SECTIONS.find((section) => section.path === clean);
  return found ? found.id : "painel";
}

export function cmsPathForSection(section: CmsSection): string {
  return CMS_SECTIONS.find((entry) => entry.id === section)?.path ?? "/cms";
}

export default function CmsPage() {
  const [section, setSection] = useState<CmsSection>(() => (typeof window === "undefined" ? "painel" : cmsSectionFromPath(window.location.pathname)));
  const [catalogue, setCatalogue] = useState<CmsCatalogue | null>(null);
  const [overview, setOverview] = useState<CmsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<{ id: number; message: string; tone: "info" | "error" | "ok" }[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<CmsSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [focus, setFocus] = useState<{ entity: "pages" | "posts"; id: string } | null>(null);

  const notify = useCallback((message: string, tone: "info" | "error" | "ok" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4200);
  }, []);

  const refreshOverview = useCallback(() => {
    void cms
      .getCmsOverview()
      .then(setOverview)
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cataloguePayload, overviewPayload] = await Promise.all([cms.getCmsCatalogue(), cms.getCmsOverview()]);
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

  // A navegação da secção vive no caminho: `/cms/paginas`, `/cms/blog`, …
  useEffect(() => {
    const onPop = () => setSection(cmsSectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const changeSection = useCallback((next: CmsSection) => {
    setSection(next);
    if (typeof window !== "undefined") {
      const path = cmsPathForSection(next);
      if (window.location.pathname !== path) window.history.pushState({}, "", path);
    }
  }, []);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setHits([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      void cms
        .searchCms(needle)
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
    (hit: CmsSearchHit) => {
      setHits([]);
      setQuery("");
      if (hit.entity === "pages" || hit.entity === "posts") {
        changeSection(hit.entity === "pages" ? "paginas" : "blog");
        setFocus({ entity: hit.entity, id: hit.id });
        return;
      }
      if (hit.entity === "contents") changeSection("conteudos");
      else if (hit.entity === "media") changeSection("media");
      else if (hit.entity === "categories") changeSection("taxonomia");
      else if (hit.entity === "templates") changeSection("modelos");
    },
    [changeSection],
  );

  const ctx: CmsCtx = useMemo(
    () => ({ catalogue: catalogue ?? ({} as CmsCatalogue), notify, refreshOverview }),
    [catalogue, notify, refreshOverview],
  );

  return (
    <div className="@container relative flex h-full min-h-[520px] flex-col bg-background text-foreground">
      <header className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 pb-2 pt-2 backdrop-blur-xl md:top-0">
        <div className="flex flex-wrap items-center gap-2 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-teal-300 via-sky-500 to-indigo-600 text-white">
            <Globe2 size={15} />
          </span>
          <h1 className="text-[14px] font-semibold">CMS</h1>
          {overview && (
            <span className="rounded-full bg-teal-400/15 px-2 py-0.5 text-[10.5px] text-teal-100">
              {overview.pages.published} página(s) · {overview.posts.published} artigo(s) publicados
            </span>
          )}
          {overview?.scheduled.length ? (
            <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-[10.5px] text-amber-100">{overview.scheduled.length} agendado(s)</span>
          ) : null}
          <div className="min-w-0 flex-1" />

          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              className="w-[min(280px,60vw)] rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-7 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
              placeholder="Pesquisar no CMS…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <button type="button" className="absolute right-2 top-2 text-muted-foreground hover:text-foreground" onClick={() => setQuery("")} title="Limpar">
                <X size={13} />
              </button>
            )}
            {(hits.length > 0 || searching) && (
              <div className="absolute right-0 top-full z-30 mt-1 w-[min(420px,92vw)] rounded-xl border border-white/12 bg-[#08181f] p-1.5 shadow-2xl">
                {searching && <p className="px-2 py-1.5 text-[11.5px] text-muted-foreground">A procurar…</p>}
                {hits.map((hit) => (
                  <button
                    key={`${hit.entity}-${hit.id}`}
                    type="button"
                    onClick={() => openHit(hit)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.08]"
                  >
                    <span className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">{hit.entity}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] text-foreground">{hit.title || "(sem título)"}</span>
                      <span className="block truncate text-[10.5px] text-muted-foreground">{hit.subtitle}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              void load();
              notify("Atualizado.", "ok");
            }}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
            title="Recarregar o CMS"
          >
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-1 rounded-[8px] border border-white/8 bg-white/[0.05] p-0.5 mx-4">
          {CMS_SECTIONS.map((entry) => {
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
                  "flex shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 py-1 text-[12px] transition",
                  active ? "bg-white/[0.16] font-medium text-foreground shadow-sm" : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
                ].join(" ")}
              >
                <span className={active ? "text-teal-300" : undefined}>{entry.icon}</span>
                <span className="whitespace-nowrap">{entry.label}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error && (
          <div className="mb-3">
            <Notice tone="error">
              <AlertTriangle size={12} className="mr-1 inline" /> {error}
            </Notice>
          </div>
        )}

        {loading || !catalogue || !overview ? (
          <p className="flex items-center gap-2 py-16 text-[12.5px] text-muted-foreground">
            <Loader2 size={15} className="animate-spin" /> A carregar o CMS…
          </p>
        ) : section === "painel" ? (
          <CmsOverviewPanel
            overview={overview}
            onOpenSection={changeSection}
            onOpenItem={(entity, id) => {
              changeSection(entity === "pages" ? "paginas" : "blog");
              setFocus({ entity, id });
            }}
          />
        ) : section === "paginas" ? (
          <CmsPagesPanel ctx={ctx} focusId={focus?.entity === "pages" ? focus.id : null} onFocusHandled={() => setFocus(null)} />
        ) : section === "blog" ? (
          <CmsPostsPanel ctx={ctx} focusId={focus?.entity === "posts" ? focus.id : null} onFocusHandled={() => setFocus(null)} />
        ) : section === "conteudos" ? (
          <CmsContentsPanel ctx={ctx} />
        ) : section === "media" ? (
          <CmsMediaPanel ctx={ctx} />
        ) : section === "taxonomia" ? (
          <CmsTaxonomyPanel ctx={ctx} />
        ) : section === "modelos" ? (
          <CmsTemplatesPanel ctx={ctx} />
        ) : (
          <CmsAppearancePanel ctx={ctx} />
        )}
      </div>

      <div className="pointer-events-none fixed bottom-20 right-4 z-[140] flex flex-col items-end gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={[
              "pointer-events-auto max-w-[380px] rounded-xl border px-3 py-2 text-[12px] shadow-xl backdrop-blur",
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
