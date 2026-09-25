/**
 * Painéis do CMS — visão geral, **páginas** (por blocos) e **blog**.
 *
 * As páginas e os artigos partilham o mesmo ciclo de vida: rascunho → agendado
 * → publicado → arquivado, com pré-visualização, histórico de revisões e
 * abertura do resultado no site público.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  BookOpen,
  CalendarClock,
  Check,
  Clock,
  Copy,
  ExternalLink,
  Eye,
  FileText,
  Globe2,
  History,
  Loader2,
  Newspaper,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Rocket,
  Save,
  Search,
  Trash2,
  Undo2,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import { MarkdownEditor, type EditorMode } from "../components/office/MarkdownEditor";
import {
  BlockEditor,
  IconAction,
  ListRow,
  MediaPicker,
  Notice,
  PanelHeader,
  SelectInput,
  Sheet,
  StatusBadge,
  StatusTabs,
  TagsInput,
  TextArea,
  TextInput,
  Toggle,
  formatBytes,
  timeAgo,
} from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsCatalogue, CmsCategory, CmsOverview, CmsPage, CmsPost, CmsRevision, CmsStatus } from "../cmsApi";

export type CmsSection = "painel" | "paginas" | "conteudos" | "blog" | "media" | "taxonomia" | "modelos" | "aparencia";

export type CmsCtx = {
  catalogue: CmsCatalogue;
  notify: (message: string, tone?: "info" | "error" | "ok") => void;
  refreshOverview: () => void;
};

const statusLabels: Record<string, string> = {
  rascunho: "Rascunho",
  agendado: "Agendado",
  publicado: "Publicado",
  arquivado: "Arquivado",
};

function openExternal(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

function toLocalInput(value?: string | null): string {
  if (!value) return "";
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) return "";
  const pad = (number: number) => String(number).padStart(2, "0");
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}T${pad(stamp.getHours())}:${pad(stamp.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const stamp = new Date(value);
  return Number.isNaN(stamp.getTime()) ? null : stamp.toISOString();
}

/* ================================================================= visão geral */

export function CmsOverviewPanel({
  overview,
  onOpenSection,
  onOpenItem,
}: {
  overview: CmsOverview;
  onOpenSection: (section: CmsSection) => void;
  onOpenItem: (entity: "pages" | "posts", id: string) => void;
}) {
  const cards: { label: string; value: string; hint: string; run: () => void }[] = [
    {
      label: "Páginas publicadas",
      value: String(overview.pages.published),
      hint: `${overview.pages.by_status.rascunho ?? 0} rascunho(s) · ${overview.pages.total} no total`,
      run: () => onOpenSection("paginas"),
    },
    {
      label: "Artigos no blog",
      value: String(overview.posts.published),
      hint: `${overview.posts.by_status.rascunho ?? 0} rascunho(s) · ${overview.words.toLocaleString("pt-PT")} palavras`,
      run: () => onOpenSection("blog"),
    },
    {
      label: "Conteúdos reutilizáveis",
      value: String(overview.contents),
      hint: "Blocos com nome, partilhados por várias páginas",
      run: () => onOpenSection("conteudos"),
    },
    {
      label: "Media",
      value: String(overview.media.total),
      hint: formatBytes(overview.media.bytes),
      run: () => onOpenSection("media"),
    },
  ];

  const settings = overview.site.settings;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <button
            key={card.label}
            type="button"
            onClick={card.run}
            className="rounded-xl border border-white/8 bg-white/[0.03] p-3 text-left transition hover:border-teal-300/30 hover:bg-teal-400/[0.06]"
          >
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{card.label}</p>
            <p className="mt-1 text-[22px] font-semibold leading-none text-foreground">{card.value}</p>
            <p className="mt-1.5 text-[11px] text-muted-foreground">{card.hint}</p>
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <PanelHeader title="Site público" hint="O que está publicado neste momento, a partir das definições do CMS.">
          <Button size="sm" variant="secondary" icon={<Globe2 size={13} />} onClick={() => openExternal(cms.cmsPublicUrl("/"))}>
            Abrir o site
          </Button>
          <Button size="sm" variant="secondary" icon={<Newspaper size={13} />} onClick={() => openExternal(cms.cmsPublicUrl("/blog"))}>
            Ver o blog
          </Button>
          <Button size="sm" variant="ghost" icon={<Pencil size={13} />} onClick={() => onOpenSection("aparencia")}>
            Aparência
          </Button>
        </PanelHeader>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-[11px] text-muted-foreground">Nome</p>
            <p className="text-[12.5px] text-foreground">{settings.site_name || "—"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Endereço base (canónicos)</p>
            <p className="truncate text-[12.5px] text-foreground">{settings.base_url || "(relativo)"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Página inicial</p>
            <p className="truncate text-[12.5px] text-foreground">{overview.site.home ? `/site/${overview.site.home}` : "automática"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Aparência</p>
            <p className="text-[12.5px] text-foreground">
              {settings.theme === "escuro" ? "Escuro" : "Claro"} · <span style={{ color: settings.accent }}>{settings.accent}</span>
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Agendamentos" hint="Conteúdo que se publica sozinho quando chegar a hora." />
          {overview.scheduled.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">Nada agendado.</p>
          ) : (
            <ul className="space-y-1.5">
              {overview.scheduled.map((item) => (
                <li key={`${item.entity}-${item.id}`}>
                  <ListRow
                    icon={<CalendarClock size={13} />}
                    title={item.title || "(sem título)"}
                    subtitle={new Date(item.at).toLocaleString("pt-PT")}
                    badges={<span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10.5px] text-amber-100">agendado</span>}
                    onClick={() => onOpenItem(item.entity, item.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Alterações recentes" hint="Últimos documentos guardados no CMS." />
          {overview.recent.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">Ainda não há registos.</p>
          ) : (
            <ul className="space-y-1.5">
              {overview.recent.map((item) => (
                <li key={`${item.entity}-${item.id}`}>
                  <ListRow
                    icon={item.entity === "pages" ? <FileText size={13} /> : <Newspaper size={13} />}
                    title={item.title || "(sem título)"}
                    subtitle={`${item.entity === "pages" ? "Página" : "Artigo"} · ${timeAgo(item.at)}${item.by ? ` · ${item.by}` : ""}`}
                    badges={<StatusBadge status={item.status} labels={statusLabels} />}
                    onClick={() => onOpenItem(item.entity as "pages" | "posts", item.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <PanelHeader title="Atividade" hint="Quem criou, alterou, publicou ou restaurou o quê." />
        <ul className="space-y-1 text-[11.5px] text-muted-foreground">
          {overview.activity.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2">
              <Clock size={11} />
              <span className="text-foreground/80">{timeAgo(item.at)}</span>
              <span className="rounded bg-white/[0.06] px-1.5 py-0.5">{item.action}</span>
              <span className="truncate text-foreground">{item.label || item.entity}</span>
              <span className="text-muted-foreground/70">{item.entity}</span>
              {item.actor && <span className="text-muted-foreground/70">· {item.actor}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ================================================================== comuns */

function SeoFields({
  seo,
  onChange,
  media,
}: {
  seo: cms.CmsSeo;
  onChange: (next: cms.CmsSeo) => void;
  media: cms.CmsCatalogue["media_index"];
}) {
  const value = seo ?? {};
  const set = (key: keyof cms.CmsSeo, next: unknown) => onChange({ ...value, [key]: next });
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <TextInput label="Título para os motores de busca" value={String(value.title ?? "")} onChange={(next) => set("title", next)} wide />
      <TextArea label="Descrição" value={String(value.description ?? "")} onChange={(next) => set("description", next)} rows={2} wide />
      <TagsInput label="Palavras-chave" value={(value.keywords as string[]) ?? []} onChange={(next) => set("keywords", next)} />
      <MediaPicker
        label="Imagem de partilha"
        value={String(value.image_id ?? "")}
        onChange={(next) => set("image_id", next || null)}
        media={media}
      />
      <Toggle
        label="Não indexar (noindex)"
        hint="A página fica acessível mas fora dos motores de busca e do sitemap."
        checked={Boolean(value.noindex)}
        onChange={(next) => set("noindex", next)}
      />
    </div>
  );
}

function PublishBar({
  status,
  scheduledAt,
  onStatus,
  onSchedule,
  onPublish,
  onUnpublish,
  onOpenSite,
  onPreview,
  busy,
  hasPublicUrl,
}: {
  status: CmsStatus;
  scheduledAt?: string | null;
  onStatus: (status: CmsStatus) => void;
  onSchedule: (at: string | null) => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onOpenSite: () => void;
  onPreview: () => void;
  busy: boolean;
  hasPublicUrl: boolean;
}) {
  const [when, setWhen] = useState(toLocalInput(scheduledAt));
  useEffect(() => setWhen(toLocalInput(scheduledAt)), [scheduledAt]);

  return (
    <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={status} labels={statusLabels} />
        <div className="flex-1" />
        <Button size="sm" variant="secondary" icon={<Eye size={13} />} onClick={onPreview}>
          Pré-visualizar
        </Button>
        <Button size="sm" variant="secondary" icon={<ExternalLink size={13} />} onClick={onOpenSite} disabled={!hasPublicUrl}>
          Ver no site
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" icon={<Rocket size={13} />} loading={busy} onClick={onPublish}>
          Publicar agora
        </Button>
        <Button size="sm" variant="secondary" icon={<Undo2 size={13} />} onClick={onUnpublish} disabled={status === "rascunho"}>
          Despublicar
        </Button>
        <Button size="sm" variant="outline" icon={<Archive size={13} />} onClick={() => onStatus("arquivado")}>
          Arquivar
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[11.5px] font-medium text-muted-foreground">Agendar publicação</span>
          <input type="datetime-local" className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-foreground" value={when} onChange={(event) => setWhen(event.target.value)} />
        </label>
        <Button size="sm" variant="secondary" icon={<CalendarClock size={13} />} onClick={() => onSchedule(fromLocalInput(when))} disabled={!when}>
          Agendar
        </Button>
        {status === "agendado" && scheduledAt && (
          <span className="text-[11.5px] text-amber-100">Publica em {new Date(scheduledAt).toLocaleString("pt-PT")}</span>
        )}
      </div>
    </div>
  );
}

function HistoryPanel({
  entity,
  itemId,
  onRestored,
  notify,
}: {
  entity: string;
  itemId?: string;
  onRestored: () => void;
  notify: CmsCtx["notify"];
}) {
  const [items, setItems] = useState<CmsRevision[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    if (!itemId) return;
    setLoading(true);
    try {
      const payload = await cms.getCmsRevisions(entity, itemId);
      setItems(payload.items);
    } catch (error) {
      notify((error as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [entity, itemId, notify]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  if (!itemId) return null;

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="flex items-center gap-2">
        <History size={13} className="text-teal-200" />
        <span className="text-[12px] font-medium text-foreground">Histórico</span>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" onClick={() => setOpen((value) => !value)}>
          {open ? "Fechar" : "Ver revisões"}
        </Button>
      </div>
      {open && (
        <div className="mt-2 space-y-1.5">
          {loading && <p className="text-[12px] text-muted-foreground">A carregar…</p>}
          {!loading && items.length === 0 && <p className="text-[12px] text-muted-foreground">Sem revisões guardadas.</p>}
          {items.map((revision) => (
            <div key={revision.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-2.5 py-1.5">
              <span className="text-[11.5px] text-foreground">{new Date(revision.at).toLocaleString("pt-PT")}</span>
              <span className="text-[11px] text-muted-foreground">{revision.note || "revisão"}</span>
              {revision.author && <span className="text-[11px] text-muted-foreground/70">· {revision.author}</span>}
              <div className="flex-1" />
              <Button
                size="sm"
                variant="ghost"
                icon={<RotateCcw size={12} />}
                onClick={async () => {
                  try {
                    await cms.restoreCmsRevision(revision.id);
                    notify("Revisão restaurada.", "ok");
                    onRestored();
                    void load();
                  } catch (error) {
                    notify((error as Error).message, "error");
                  }
                }}
              >
                Restaurar
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* =================================================================== páginas */

type PageNode = CmsPage & { children: PageNode[] };

function buildTree(pages: CmsPage[]): PageNode[] {
  const nodes = new Map<string, PageNode>();
  pages.forEach((page) => nodes.set(page.id, { ...page, children: [] }));
  const roots: PageNode[] = [];
  nodes.forEach((node) => {
    const parent = node.parent_id ? nodes.get(node.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  });
  const sort = (list: PageNode[]) => {
    list.sort((a, b) => (a.menu_order ?? 0) - (b.menu_order ?? 0) || a.title.localeCompare(b.title));
    list.forEach((node) => sort(node.children));
  };
  sort(roots);
  return roots;
}

function emptyPage(template?: cms.CmsTemplate): Partial<CmsPage> {
  return {
    title: "",
    status: "rascunho",
    show_in_menu: true,
    menu_order: 0,
    blocks: template?.blocks ? template.blocks.map((block) => ({ ...block, id: `blk_${Math.random().toString(36).slice(2, 10)}` })) : [],
    seo: { title: "", description: "", keywords: [], image_id: null, noindex: false },
    excerpt: "",
    parent_id: null,
  };
}

export function CmsPagesPanel({ ctx, focusId, onFocusHandled }: { ctx: CmsCtx; focusId?: string | null; onFocusHandled?: () => void }) {
  const [pages, setPages] = useState<CmsPage[]>([]);
  const [templates, setTemplates] = useState<cms.CmsTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<Partial<CmsPage> | null>(null);
  const [busy, setBusy] = useState(false);

  const media = ctx.catalogue.media_index;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [payload, templatePayload] = await Promise.all([cms.listCmsPages({ limit: 300 }), cms.listCmsTemplates({ limit: 100 })]);
      setPages(payload.items);
      setTemplates(templatePayload.items);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = useCallback(
    async (id: string) => {
      try {
        const payload = await cms.getCmsPage(id);
        setDraft(payload.item);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [],
  );

  useEffect(() => {
    if (focusId) {
      void open(focusId);
      onFocusHandled?.();
    }
  }, [focusId, open, onFocusHandled]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return pages.filter((page) => {
      if (status !== "all" && page.status !== status) return false;
      if (!needle) return true;
      return `${page.title} ${page.path} ${page.slug}`.toLowerCase().includes(needle);
    });
  }, [pages, query, status]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    pages.forEach((page) => {
      result[page.status] = (result[page.status] ?? 0) + 1;
    });
    return result;
  }, [pages]);

  const save = async (): Promise<CmsPage | null> => {
    if (!draft) return null;
    setBusy(true);
    try {
      const payload = {
        title: draft.title ?? "",
        slug: draft.slug,
        parent_id: draft.parent_id ?? null,
        template: draft.template,
        blocks: draft.blocks ?? [],
        status: draft.status ?? "rascunho",
        show_in_menu: draft.show_in_menu ?? true,
        menu_order: draft.menu_order ?? 0,
        menu_label: draft.menu_label ?? "",
        excerpt: draft.excerpt ?? "",
        seo: draft.seo,
      };
      const result = draft.id ? await cms.updateCmsPage(draft.id, payload) : await cms.createCmsPage(payload);
      setDraft(result.item);
      ctx.notify("Página guardada.", "ok");
      await load();
      ctx.refreshOverview();
      return result.item;
    } catch (err) {
      ctx.notify((err as Error).message, "error");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const publish = async (at?: string | null) => {
    let current = draft;
    if (!current?.id || current.status === "rascunho") {
      const saved = await save();
      if (!saved) return;
      current = saved;
    }
    if (!current?.id) return;
    setBusy(true);
    try {
      const result = await cms.publishCmsItem("pages", current.id, at ?? null);
      setDraft(result.item);
      ctx.notify(at ? "Página agendada." : "Página publicada.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const unpublish = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const result = await cms.unpublishCmsItem("pages", draft.id);
      setDraft(result.item);
      ctx.notify("Página devolvida a rascunho.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const applyStatus = async (next: CmsStatus) => {
    if (!draft?.id) {
      setDraft((current) => (current ? { ...current, status: next } : current));
      return;
    }
    try {
      const result = await cms.setCmsStatus("pages", draft.id, next);
      setDraft(result.item);
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  };

  const remove = async (page: CmsPage) => {
    if (!window.confirm(`Apagar a página «${page.title}»? As revisões ficam guardadas no histórico.`)) return;
    try {
      await cms.deleteCmsEntity("pages", page.id);
      ctx.notify("Página apagada.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  };

  const duplicate = async (page: CmsPage) => {
    try {
      await cms.duplicateCmsEntity("pages", page.id);
      ctx.notify("Página duplicada.", "ok");
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  };

  const renderNodes = (nodes: PageNode[], depth = 0): ReactNode =>
    nodes.map((node) => (
      <div key={node.id} className="space-y-1.5">
        <ListRow
          icon={node.children.length ? <BookOpen size={13} /> : <FileText size={13} />}
          title={node.title || "(sem título)"}
          subtitle={`/${node.path || ""}${node.path ? "" : " (raiz)"} · ${node.blocks_count ?? 0} bloco(s) · ${timeAgo(node.updated_at)}`}
          badges={<StatusBadge status={node.status} labels={statusLabels} />}
          onClick={() => void open(node.id)}
          meta={
            node.children.length ? (
              <button
                type="button"
                className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10.5px] hover:bg-white/[0.12]"
                onClick={() => setCollapsed((set) => {
                  const next = new Set(set);
                  if (next.has(node.id)) next.delete(node.id);
                  else next.add(node.id);
                  return next;
                })}
              >
                {collapsed.has(node.id) ? `mostrar ${node.children.length}` : `ocultar ${node.children.length}`}
              </button>
            ) : undefined
          }
          actions={
            <>
              <IconAction title="Editar" onClick={() => void open(node.id)}>
                <Pencil size={12} />
              </IconAction>
              {node.status === "publicado" && (
                <IconAction title="Ver no site" onClick={() => openExternal(cms.cmsPublicUrl(node.path ? `/${node.path}` : "/"))}>
                  <ExternalLink size={12} />
                </IconAction>
              )}
              <IconAction title="Duplicar" onClick={() => void duplicate(node)}>
                <Copy size={12} />
              </IconAction>
              <IconAction title="Apagar" danger onClick={() => void remove(node)}>
                <Trash2 size={12} />
              </IconAction>
            </>
          }
        />
        {node.children.length > 0 && !collapsed.has(node.id) && <div className="ml-5 space-y-1.5 border-l border-white/8 pl-3">{renderNodes(node.children, depth + 1)}</div>}
      </div>
    ));

  const parentOptions = pages
    .filter((page) => page.id !== draft?.id)
    .map((page) => ({ value: page.id, label: page.path ? `/${page.path}` : `${page.title} (raiz do site)` }));

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Páginas"
        hint="Cada página é uma sequência de blocos (destaque, texto, imagens, cartões, perguntas…). Pode aninhar páginas: o caminho público segue a ascendência."
      >
        <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setDraft(emptyPage())}>
          Nova página
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" placeholder="Procurar página por título ou caminho…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.statuses} counts={counts} />
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as páginas…
        </p>
      ) : tree.length === 0 ? (
        <Notice>Nenhuma página corresponde ao filtro.</Notice>
      ) : (
        <div className="space-y-1.5">{renderNodes(tree)}</div>
      )}

      {draft && (
        <Sheet
          wide
          busy={busy}
          title={draft.id ? `Página · ${draft.title || "(sem título)"}` : "Nova página"}
          subtitle={draft.id ? `/site/${draft.path || ""}` : "Preencha o título; o endereço é gerado a partir dele."}
          onClose={() => setDraft(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Fechar
              </Button>
              <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void save()}>
                Guardar
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Título" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <TextInput label="Endereço (slug)" value={draft.slug ?? ""} onChange={(next) => setDraft({ ...draft, slug: next })} hint="Deixe vazio para gerar do título." />
              <SelectInput
                label="Página ascendente"
                value={String(draft.parent_id ?? "")}
                onChange={(next) => setDraft({ ...draft, parent_id: next || null })}
                options={parentOptions}
                placeholder="— nenhuma (raiz) —"
              />
              <SelectInput
                label="Modelo de partida"
                value={String(draft.template ?? "")}
                onChange={(next) => setDraft({ ...draft, template: next })}
                options={templates.filter((item) => item.kind === "page").map((item) => ({ value: item.id, label: item.name }))}
                placeholder="— página padrão —"
              />
              <TextArea label="Resumo (usado em listagens e SEO)" value={draft.excerpt ?? ""} onChange={(next) => setDraft({ ...draft, excerpt: next })} rows={2} wide />
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Menu" hint="Como a página aparece no menu do cabeçalho do site." />
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="sm:col-span-3">
                  <Toggle label="Mostrar no menu do site" checked={draft.show_in_menu ?? true} onChange={(next) => setDraft({ ...draft, show_in_menu: next })} />
                </div>
                <TextInput label="Texto no menu" value={draft.menu_label ?? ""} onChange={(next) => setDraft({ ...draft, menu_label: next })} placeholder="(usa o título)" />
                <SelectInput
                  label="Ordem"
                  value={String(draft.menu_order ?? 0)}
                  onChange={(next) => setDraft({ ...draft, menu_order: Number(next) })}
                  options={Array.from({ length: 11 }, (_, index) => ({ value: String(index), label: String(index) }))}
                />
              </div>
            </div>

            {draft.id && (
              <PublishBar
                status={(draft.status ?? "rascunho") as CmsStatus}
                scheduledAt={draft.scheduled_at}
                onStatus={(next) => void applyStatus(next)}
                onSchedule={(at) => void publish(at)}
                onPublish={() => void publish()}
                onUnpublish={() => void unpublish()}
                onOpenSite={() => openExternal(cms.cmsPublicUrl(draft.path ? `/${draft.path}` : "/"))}
                onPreview={() => openExternal(cms.cmsPreviewUrl("pages", draft.id as string))}
                busy={busy}
                hasPublicUrl={draft.status === "publicado"}
              />
            )}

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Blocos" hint="A ordem dos blocos é a ordem na página publicada." />
              <BlockEditor
                blocks={(draft.blocks ?? []) as never}
                onChange={(next) => setDraft({ ...draft, blocks: next as CmsPage["blocks"] })}
                blockTypes={ctx.catalogue.block_types}
                media={media}
                contents={ctx.catalogue.contents_index}
                categories={ctx.catalogue.categories_index}
              />
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Motores de busca" hint="Título, descrição e imagem usados nos resultados e nas partilhas." />
              <SeoFields seo={draft.seo ?? {}} onChange={(next) => setDraft({ ...draft, seo: next })} media={media} />
            </div>

            <HistoryPanel entity="pages" itemId={draft.id} notify={ctx.notify} onRestored={() => void open(draft.id as string)} />
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* ====================================================================== blog */

function emptyPost(): Partial<CmsPost> {
  return {
    title: "",
    markdown: "## Introdução\n\n",
    excerpt: "",
    category_ids: [],
    tags: [],
    status: "rascunho",
    featured: false,
    seo: { title: "", description: "", keywords: [], image_id: null, noindex: false },
  };
}

export function CmsPostsPanel({ ctx, focusId, onFocusHandled }: { ctx: CmsCtx; focusId?: string | null; onFocusHandled?: () => void }) {
  const [posts, setPosts] = useState<CmsPost[]>([]);
  const [categories, setCategories] = useState<CmsCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [draft, setDraft] = useState<Partial<CmsPost> | null>(null);
  const [mode, setMode] = useState<EditorMode>("split");
  const [busy, setBusy] = useState(false);

  const media = ctx.catalogue.media_index;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [payload, taxonomy] = await Promise.all([cms.listCmsPosts({ limit: 300 }), cms.getCmsTaxonomy()]);
      setPosts(payload.items);
      setCategories(taxonomy.categories);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = useCallback(async (id: string) => {
    try {
      const payload = await cms.getCmsPost(id);
      setDraft(payload.item);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    if (focusId) {
      void open(focusId);
      onFocusHandled?.();
    }
  }, [focusId, open, onFocusHandled]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return posts.filter((post) => {
      if (status !== "all" && post.status !== status) return false;
      if (categoryFilter && !(post.category_ids ?? []).includes(categoryFilter)) return false;
      if (!needle) return true;
      return `${post.title} ${post.slug} ${post.excerpt ?? ""} ${(post.tags ?? []).join(" ")}`.toLowerCase().includes(needle);
    });
  }, [posts, query, status, categoryFilter]);

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    posts.forEach((post) => {
      result[post.status] = (result[post.status] ?? 0) + 1;
    });
    return result;
  }, [posts]);

  const save = async (): Promise<CmsPost | null> => {
    if (!draft) return null;
    setBusy(true);
    try {
      const payload = {
        title: draft.title ?? "",
        slug: draft.slug,
        excerpt: draft.excerpt ?? "",
        markdown: draft.markdown ?? "",
        cover_id: draft.cover_id ?? null,
        category_ids: draft.category_ids ?? [],
        tags: draft.tags ?? [],
        author: draft.author ?? "",
        featured: draft.featured ?? false,
        status: draft.status ?? "rascunho",
        seo: draft.seo,
      };
      const result = draft.id ? await cms.updateCmsPost(draft.id, payload) : await cms.createCmsPost(payload);
      setDraft(result.item);
      ctx.notify("Artigo guardado.", "ok");
      await load();
      ctx.refreshOverview();
      return result.item;
    } catch (err) {
      ctx.notify((err as Error).message, "error");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const publish = async (at?: string | null) => {
    let current = draft;
    if (!current?.id || current.status === "rascunho") {
      const saved = await save();
      if (!saved) return;
      current = saved;
    }
    if (!current?.id) return;
    setBusy(true);
    try {
      const result = await cms.publishCmsItem("posts", current.id, at ?? null);
      setDraft(result.item);
      ctx.notify(at ? "Artigo agendado." : "Artigo publicado.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const unpublish = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const result = await cms.unpublishCmsItem("posts", draft.id);
      setDraft(result.item);
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (post: CmsPost) => {
    if (!window.confirm(`Apagar o artigo «${post.title}»?`)) return;
    try {
      await cms.deleteCmsEntity("posts", post.id);
      ctx.notify("Artigo apagado.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  };

  const toggleCategory = (id: string) => {
    const current = new Set(draft?.category_ids ?? []);
    if (current.has(id)) current.delete(id);
    else current.add(id);
    setDraft({ ...draft, category_ids: [...current] });
  };

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Blog"
        hint="Artigos em Markdown com categorias, etiquetas, capa, autor e SEO. O blog público vive em /site/blog."
      >
        <Button size="sm" variant="secondary" icon={<Newspaper size={13} />} onClick={() => openExternal(cms.cmsPublicUrl("/blog"))}>
          Abrir o blog
        </Button>
        <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setDraft(emptyPost())}>
          Novo artigo
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" placeholder="Procurar artigo…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.statuses} counts={counts} />
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
      </div>

      {categories.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Categoria:</span>
          <button
            type="button"
            onClick={() => setCategoryFilter("")}
            className={`rounded-full border px-2 py-0.5 text-[11px] ${categoryFilter === "" ? "border-teal-300/40 bg-teal-400/15 text-teal-100" : "border-white/10 text-muted-foreground hover:text-foreground"}`}
          >
            todas
          </button>
          {categories.map((category) => (
            <button
              key={category.id}
              type="button"
              onClick={() => setCategoryFilter(category.id)}
              className={`rounded-full border px-2 py-0.5 text-[11px] ${categoryFilter === category.id ? "border-teal-300/40 bg-teal-400/15 text-teal-100" : "border-white/10 text-muted-foreground hover:text-foreground"}`}
            >
              {category.name} · {category.posts ?? 0}
            </button>
          ))}
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar o blog…
        </p>
      ) : filtered.length === 0 ? (
        <Notice>Nenhum artigo corresponde ao filtro.</Notice>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((post) => (
            <ListRow
              key={post.id}
              icon={<Newspaper size={13} />}
              title={post.title || "(sem título)"}
              subtitle={`/${post.slug} · ${post.reading_minutes ?? 1} min · ${(post.tags ?? []).join(", ") || "sem etiquetas"}`}
              badges={
                <>
                  <StatusBadge status={post.status} labels={statusLabels} />
                  {post.featured && <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10.5px] text-amber-100">destaque</span>}
                </>
              }
              meta={<span>{post.published_at ? new Date(post.published_at).toLocaleDateString("pt-PT") : timeAgo(post.updated_at)}</span>}
              onClick={() => void open(post.id)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => void open(post.id)}>
                    <Pencil size={12} />
                  </IconAction>
                  {post.status === "publicado" && (
                    <IconAction title="Ver no site" onClick={() => openExternal(cms.cmsPublicUrl(`/blog/${post.slug}`))}>
                      <ExternalLink size={12} />
                    </IconAction>
                  )}
                  <IconAction title="Duplicar" onClick={() => void cms.duplicateCmsEntity("posts", post.id).then(() => load()).catch((err) => ctx.notify((err as Error).message, "error"))}>
                    <Copy size={12} />
                  </IconAction>
                  <IconAction title="Apagar" danger onClick={() => void remove(post)}>
                    <Trash2 size={12} />
                  </IconAction>
                </>
              }
            />
          ))}
        </div>
      )}

      {draft && (
        <Sheet
          wide
          busy={busy}
          title={draft.id ? `Artigo · ${draft.title || "(sem título)"}` : "Novo artigo"}
          subtitle={draft.id ? `/site/blog/${draft.slug}` : "Escreva em Markdown; a capa e a taxonomia vêm ao lado."}
          onClose={() => setDraft(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Fechar
              </Button>
              <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void save()}>
                Guardar
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Título" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <TextInput label="Endereço (slug)" value={draft.slug ?? ""} onChange={(next) => setDraft({ ...draft, slug: next })} hint="Vazio = gerado do título." />
              <TextInput label="Autor" value={draft.author ?? ""} onChange={(next) => setDraft({ ...draft, author: next })} />
              <TextArea label="Resumo" value={draft.excerpt ?? ""} onChange={(next) => setDraft({ ...draft, excerpt: next })} rows={2} wide />
              <MediaPicker label="Imagem de capa" value={String(draft.cover_id ?? "")} onChange={(next) => setDraft({ ...draft, cover_id: next || null })} media={media} />
              <TagsInput label="Etiquetas" value={draft.tags ?? []} onChange={(next) => setDraft({ ...draft, tags: next })} />
              <div className="sm:col-span-2">
                <Toggle label="Artigo em destaque" checked={draft.featured ?? false} onChange={(next) => setDraft({ ...draft, featured: next })} />
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Categorias" hint="Uma categoria pode agrupar vários artigos (páginas /site/categoria/<slug>)." />
              <div className="flex flex-wrap gap-1.5">
                {categories.length === 0 && <p className="text-[12px] text-muted-foreground">Ainda não há categorias — crie-as na secção «Taxonomia».</p>}
                {categories.map((category) => {
                  const active = (draft.category_ids ?? []).includes(category.id);
                  return (
                    <button
                      key={category.id}
                      type="button"
                      onClick={() => toggleCategory(category.id)}
                      className={`rounded-full border px-2.5 py-1 text-[11.5px] transition ${active ? "border-teal-300/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground"}`}
                    >
                      {active && <Check size={10} className="mr-1 inline" />}
                      {category.name}
                    </button>
                  );
                })}
              </div>
            </div>

            {draft.id && (
              <PublishBar
                status={(draft.status ?? "rascunho") as CmsStatus}
                scheduledAt={draft.scheduled_at}
                onStatus={(next) => setDraft({ ...draft, status: next })}
                onSchedule={(at) => void publish(at)}
                onPublish={() => void publish()}
                onUnpublish={() => void unpublish()}
                onOpenSite={() => openExternal(cms.cmsPublicUrl(`/blog/${draft.slug}`))}
                onPreview={() => openExternal(cms.cmsPreviewUrl("posts", draft.id as string))}
                busy={busy}
                hasPublicUrl={draft.status === "publicado"}
              />
            )}

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Corpo do artigo" hint="Markdown com tabelas, listas, citações e código." />
              <MarkdownEditor
                value={draft.markdown ?? ""}
                onChange={(next) => setDraft({ ...draft, markdown: next })}
                mode={mode}
                onModeChange={setMode}
                heightClass="h-[52vh] min-h-[320px]"
              />
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Motores de busca" hint="Se ficar vazio, usa-se o título e o resumo do artigo." />
              <SeoFields seo={draft.seo ?? {}} onChange={(next) => setDraft({ ...draft, seo: next })} media={media} />
            </div>

            <HistoryPanel entity="posts" itemId={draft.id} notify={ctx.notify} onRestored={() => void open(draft.id as string)} />
          </div>
        </Sheet>
      )}
    </div>
  );
}
