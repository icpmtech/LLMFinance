/**
 * Biblioteca do leitor de RSS: fontes, pastas, sugestões e agenda.
 *
 * É onde o leitor se «alimenta»: subscrever (por endereço ou OPML), arrumar em
 * pastas, seguir as sugestões de economia/mercados e definir a recolha
 * automática (cron).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Download,
  FileUp,
  Loader2,
  MailOpen,
  Pencil,
  Plus,
  RefreshCw,
  Rss,
  Search,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";

import * as rss from "../rssApi";
import type { RssFeed, RssFolder, RssRule, RssSchedule, RssSettings, RssSuggestion } from "../rssApi";
import {
  Btn,
  Chip,
  CountDot,
  EmptyState,
  Field,
  IconAction,
  ListRow,
  Notice,
  NumberInput,
  PanelHeader,
  SelectInput,
  Sheet,
  StatusPill,
  TagsInput,
  TextArea,
  TextInput,
  Toggle,
  TONE_CLASS,
  fullDate,
  timeAgo,
} from "../components/rss/RssKit";
import type { RssCtx } from "./RssPanels";

/* ==========================================================================
   Fontes
   ========================================================================== */
export function RssFeedsPanel({ ctx }: { ctx: RssCtx }) {
  const [folderFilter, setFolderFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [feeds, setFeeds] = useState<RssFeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<RssFeed | null>(null);
  const [subscribeOpen, setSubscribeOpen] = useState(false);
  const [opmlOpen, setOpmlOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await rss.listRssFeeds(folderFilter === "all" ? null : folderFilter, query || undefined);
      setFeeds(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx, folderFilter, query]);

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  const run = useCallback(
    async (key: string, label: string, action: () => Promise<string>) => {
      setBusy(key);
      try {
        const message = await action();
        ctx.notify(`${label}: ${message}`, "ok");
        await load();
        ctx.refresh();
      } catch (err) {
        ctx.notify(`${label}: ${(err as Error).message}`, "error");
      } finally {
        setBusy(null);
      }
    },
    [ctx, load],
  );

  const folderOptions = useMemo(
    () => [{ value: "all", label: "Todas as pastas" }, { value: "root", label: "Sem pasta" }, ...ctx.catalogue.folders.map((folder) => ({ value: folder.id, label: folder.name }))],
    [ctx.catalogue.folders],
  );

  return (
    <div className="space-y-3">
      <PanelHeader title="Fontes" hint="Feeds RSS/Atom subscritos. A recolha pode ser manual ou por agenda (ver Agenda).">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setSubscribeOpen(true)}
            className="flex items-center gap-1.5 rounded-lg border border-teal-300/40 bg-teal-500/15 px-2.5 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25"
          >
            <Plus size={13} /> Subscrever feed
          </button>
          <button
            type="button"
            onClick={() => setOpmlOpen(true)}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            <Upload size={13} /> Importar OPML
          </button>
          <a
            href={rss.rssOpmlUrl()}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            <Download size={13} /> Exportar
          </a>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void run("all", "Recolha", async () => {
                const payload = await rss.fetchAllRssFeeds(false);
                return `${payload.feeds} fonte(s), ${payload.added} artigo(s) novos${payload.errors ? `, ${payload.errors} erro(s)` : ""}`;
              })
            }
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground disabled:opacity-50"
          >
            {busy === "all" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Recolher todas
          </button>
        </div>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-3 text-[12.5px] outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
            placeholder="Pesquisar fontes por título, URL ou etiqueta…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="w-[220px]">
          <select
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[12px] outline-none focus:border-teal-300/40"
            value={folderFilter}
            onChange={(event) => setFolderFilter(event.target.value)}
          >
            {folderOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as fontes…
        </p>
      ) : feeds.length === 0 ? (
        <EmptyState
          title="Sem fontes"
          hint="Subscreva um feed pelo endereço (basta o endereço do site — o leitor descobre o feed) ou importe uma lista OPML."
          action={
            <button
              type="button"
              onClick={() => setSubscribeOpen(true)}
              className="mt-1 rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100"
            >
              Subscrever o primeiro feed
            </button>
          }
        />
      ) : (
        <ul className="space-y-1.5">
          {feeds.map((feed) => (
            <li key={feed.id}>
              <ListRow
                icon={<Rss size={13} />}
                title={feed.title}
                subtitle={`${rss.rssHost(feed.url)}${feed.folder_name ? ` · ${feed.folder_name}` : ""}${feed.tags.length ? ` · ${feed.tags.join(", ")}` : ""}`}
                badges={
                  <>
                    <StatusPill label={feed.status_label || "—"} tone={feed.status_tone || "slate"} />
                    {!feed.enabled && <StatusPill label="Inativa" tone="slate" />}
                    <CountDot value={feed.unread ?? 0} title="por ler" />
                  </>
                }
                meta={
                  <span title={feed.last_fetch_at ?? undefined}>
                    {feed.articles ?? 0} artigos · {feed.last_fetch_at ? timeAgo(feed.last_fetch_at) : "nunca"}
                  </span>
                }
                actions={
                  <>
                    <IconAction
                      title="Recolher agora"
                      onClick={() =>
                        void run(feed.id, `Recolha de ${feed.title}`, async () => {
                          const payload = await rss.fetchRssFeed(feed.id, false);
                          if (payload.status === "erro") throw new Error(payload.error || "falhou");
                          return `${payload.added} novo(s)`;
                        })
                      }
                    >
                      {busy === feed.id ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    </IconAction>
                    <IconAction
                      title="Marcar tudo como lido"
                      onClick={() =>
                        void run(`${feed.id}:read`, feed.title, async () => {
                          const payload = await rss.readAllRssFeedArticles(feed.id);
                          return `${payload.updated} lido(s)`;
                        })
                      }
                    >
                      <MailOpen size={12} />
                    </IconAction>
                    <IconAction
                      title="Limpar os lidos"
                      onClick={() =>
                        void run(`${feed.id}:purge`, feed.title, async () => {
                          const payload = await rss.purgeReadRssFeedArticles(feed.id);
                          return `${payload.removed} removido(s)`;
                        })
                      }
                    >
                      <Trash2 size={12} />
                    </IconAction>
                    <IconAction title="Editar" onClick={() => setEditing(feed)}>
                      <Pencil size={12} />
                    </IconAction>
                    <IconAction
                      title="Apagar fonte (com os artigos)"
                      danger
                      onClick={() =>
                        void run(`${feed.id}:delete`, feed.title, async () => {
                          const payload = await rss.deleteRssFeed(feed.id);
                          return `${payload.articles_removed} artigo(s) removidos`;
                        })
                      }
                    >
                      <Trash2 size={12} />
                    </IconAction>
                    <IconAction title="Ver os artigos desta fonte" onClick={() => ctx.goTo("artigos", { feedId: feed.id })}>
                      <Rss size={12} />
                    </IconAction>
                  </>
                }
              />
              {feed.last_error && feed.last_status === "erro" && (
                <p className="mt-1 flex items-center gap-1.5 pl-9 text-[11px] text-rose-200">
                  <AlertTriangle size={11} /> {feed.last_error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {editing && <FeedSheet ctx={ctx} feed={editing} onClose={() => setEditing(null)} onSaved={() => void load()} />}
      {subscribeOpen && <SubscribeSheet ctx={ctx} onClose={() => setSubscribeOpen(false)} onSaved={() => void load()} />}
      {opmlOpen && <OpmlSheet ctx={ctx} onClose={() => setOpmlOpen(false)} onSaved={() => void load()} />}
    </div>
  );
}

/** Gaveta de edição de uma fonte (título, pasta, etiquetas, ativa). */
function FeedSheet({ ctx, feed, onClose, onSaved }: { ctx: RssCtx; feed: RssFeed; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(feed.title);
  const [folderId, setFolderId] = useState(feed.folder_id ?? "");
  const [tags, setTags] = useState<string[]>(feed.tags ?? []);
  const [enabled, setEnabled] = useState(feed.enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await rss.patchRssFeed(feed.id, { title, folder_id: folderId || null, tags, enabled });
      ctx.notify(`Fonte «${title}» atualizada.`, "ok");
      onSaved();
      ctx.refresh();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      title={feed.title}
      subtitle={rss.rssHost(feed.url)}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void save()}
            className="rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-50"
          >
            Guardar
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        <TextInput label="Título" value={title} onChange={setTitle} />
        <SelectInput
          label="Pasta"
          value={folderId}
          onChange={setFolderId}
          placeholder="— sem pasta —"
          options={ctx.catalogue.folders.map((folder) => ({ value: folder.id, label: folder.name }))}
        />
        <TagsInput label="Etiquetas" value={tags} onChange={setTags} />
        <Toggle checked={enabled} onChange={setEnabled} label="Ativa" hint="As fontes inativas não são recolhidas pela agenda." />
        <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3 text-[11.5px] text-muted-foreground">
          <p>
            <strong className="text-foreground">Endereço:</strong> {feed.url}
          </p>
          {feed.site_url && (
            <p className="mt-1">
              <strong className="text-foreground">Sítio:</strong> {feed.site_url}
            </p>
          )}
          <p className="mt-1">
            <strong className="text-foreground">Estado:</strong> {feed.status_label || "—"} · {feed.last_fetch_at ? fullDate(feed.last_fetch_at) : "nunca recolhido"}
          </p>
          {feed.last_error && <p className="mt-1 text-rose-200">{feed.last_error}</p>}
        </div>
      </div>
    </Sheet>
  );
}

/** Gaveta de subscrição: descobre o feed a partir do endereço do site. */
function SubscribeSheet({ ctx, onClose, onSaved }: { ctx: RssCtx; onClose: () => void; onSaved: () => void }) {
  const [url, setUrl] = useState("");
  const [folderId, setFolderId] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<string[]>([]);

  const submit = async () => {
    if (!url.trim()) {
      setError("Indique o endereço do feed ou do site.");
      return;
    }
    setBusy(true);
    setError(null);
    setCandidates([]);
    try {
      const payload = await rss.createRssFeed({ url: url.trim(), folder_id: folderId || null, tags });
      ctx.notify(`«${payload.feed.title}» subscrito (+${payload.added} artigo(s)).`, "ok");
      onSaved();
      ctx.refresh();
      onClose();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      const match = /candidatos?:?\s*(\[.*\])/.exec(message);
      if (match) {
        try {
          setCandidates(JSON.parse(match[1].replace(/'/g, '"')) as string[]);
        } catch {
          setCandidates([]);
        }
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      title="Subscrever feed"
      subtitle="Aceita o endereço do feed (RSS/Atom) ou o endereço do site — o leitor procura o feed."
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void submit()}
            className="rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-50"
          >
            {busy ? "A subscrever…" : "Subscrever"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        <TextInput
          label="Endereço"
          value={url}
          onChange={setUrl}
          autoFocus
          onEnter={() => void submit()}
          placeholder="https://exemplo.pt ou https://exemplo.pt/rss"
          hint="Dica: também pode subscrever pelo catálogo de sugestões."
        />
        <SelectInput
          label="Pasta"
          value={folderId}
          onChange={setFolderId}
          placeholder="— sem pasta —"
          options={ctx.catalogue.folders.map((folder) => ({ value: folder.id, label: folder.name }))}
        />
        <TagsInput label="Etiquetas" value={tags} onChange={setTags} placeholder="economia, portugal" />
        {candidates.length > 0 && (
          <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
            <p className="mb-1 text-[11.5px] text-muted-foreground">Endereços testados:</p>
            <ul className="space-y-0.5 text-[11.5px] text-foreground/80">
              {candidates.map((candidate) => (
                <li key={candidate} className="truncate">
                  {candidate}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Sheet>
  );
}

/** Gaveta de importação OPML (colar ou escolher ficheiro). */
function OpmlSheet({ ctx, onClose, onSaved }: { ctx: RssCtx; onClose: () => void; onSaved: () => void }) {
  const [text, setText] = useState("");
  const [folderId, setFolderId] = useState("");
  const [fetchLimit, setFetchLimit] = useState(12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const pickFile = (file?: File | null) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result ?? ""));
    reader.readAsText(file);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = await rss.importRssOpml(text, folderId || null, fetchLimit);
      ctx.notify(
        `${payload.feeds_created} fonte(s) importadas${payload.folders_created ? `, ${payload.folders_created} pasta(s)` : ""} · ${payload.fetched} recolhidas agora, ${payload.pending} por recolher.`,
        "ok",
      );
      onSaved();
      ctx.refresh();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      title="Importar OPML"
      subtitle="Cole a lista (exportada de outro leitor) ou escolha o ficheiro .opml."
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={busy || !text.trim()}
            onClick={() => void submit()}
            className="rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-50"
          >
            {busy ? "A importar…" : "Importar"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        <div className="flex flex-wrap items-end gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground"
          >
            <FileUp size={13} /> Escolher ficheiro
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".opml,.xml,text/xml,application/xml"
            className="hidden"
            onChange={(event) => pickFile(event.target.files?.[0])}
          />
          <div className="w-[200px]">
            <SelectInput
              label="Pasta para todas"
              value={folderId}
              onChange={setFolderId}
              placeholder="— respeitar o OPML —"
              options={ctx.catalogue.folders.map((folder) => ({ value: folder.id, label: folder.name }))}
            />
          </div>
          <div className="w-[170px]">
            <NumberInput label="Recolher agora" value={fetchLimit} onChange={setFetchLimit} min={0} max={60} hint="Máx. de fontes a recolher de imediato." />
          </div>
        </div>
        <TextArea label="Conteúdo OPML" value={text} onChange={setText} rows={12} mono placeholder='<?xml version="1.0"?><opml version="2.0">…' />
      </div>
    </Sheet>
  );
}

/* ==========================================================================
   Pastas
   ========================================================================== */
export function RssFoldersPanel({ ctx }: { ctx: RssCtx }) {
  const [folders, setFolders] = useState<RssFolder[]>([]);
  const [editing, setEditing] = useState<RssFolder | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const payload = await rss.listRssFolders();
      setFolders(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  const remove = async (folder: RssFolder) => {
    setBusy(folder.id);
    try {
      const payload = await rss.deleteRssFolder(folder.id);
      ctx.notify(`Pasta «${folder.name}» apagada${payload.feeds_moved ? ` (${payload.feeds_moved} fonte(s) sem pasta)` : ""}.`, "ok");
      await load();
      ctx.refresh();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Pastas" hint="Arrume as fontes por tema. Uma pasta pode ter várias fontes; uma fonte só pertence a uma pasta.">
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 rounded-lg border border-teal-300/40 bg-teal-500/15 px-2.5 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25"
        >
          <Plus size={13} /> Nova pasta
        </button>
      </PanelHeader>

      {folders.length === 0 ? (
        <EmptyState title="Sem pastas" hint="Crie uma pasta (por exemplo «Economia» ou «Reguladores») e arrume lá as fontes." />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {folders.map((folder) => (
            <li key={folder.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="flex items-start gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${TONE_CLASS[folder.color] ?? TONE_CLASS.teal}`}>{folder.color}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12.5px] font-medium text-foreground">{folder.name}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {folder.feeds ?? 0} fonte(s) · {folder.unread ?? 0} por ler
                  </p>
                </div>
                <IconAction title="Ver os artigos da pasta" onClick={() => ctx.goTo("artigos", { feedId: `folder:${folder.id}` })}>
                  <Rss size={12} />
                </IconAction>
                <IconAction title="Editar a pasta" onClick={() => setEditing(folder)}>
                  <Pencil size={12} />
                </IconAction>
                <IconAction title="Apagar a pasta" danger onClick={() => void remove(folder)}>
                  {busy === folder.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                </IconAction>
              </div>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <FolderSheet
          ctx={ctx}
          folder={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => void load()}
        />
      )}
    </div>
  );
}

function FolderSheet({ ctx, folder, onClose, onSaved }: { ctx: RssCtx; folder: RssFolder | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(folder?.name ?? "");
  const [color, setColor] = useState(folder?.color ?? "teal");
  const [order, setOrder] = useState(folder?.order ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (folder) await rss.patchRssFolder(folder.id, { name, color, order });
      else await rss.createRssFolder({ name, color, order });
      ctx.notify(`Pasta «${name}» ${folder ? "atualizada" : "criada"}.`, "ok");
      onSaved();
      ctx.refresh();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      title={folder ? `Pasta «${folder.name}»` : "Nova pasta"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={() => void save()}
            className="rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-50"
          >
            Guardar
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        <TextInput label="Nome" value={name} onChange={setName} autoFocus />
        <Field label="Cor">
          <div className="flex flex-wrap gap-1.5">
            {ctx.catalogue.colors.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setColor(option)}
                className={[
                  "rounded-full border px-2.5 py-1 text-[11.5px] transition",
                  color === option ? "border-teal-300/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.08]",
                ].join(" ")}
              >
                {option}
              </button>
            ))}
          </div>
        </Field>
        <NumberInput label="Ordem" value={order} onChange={setOrder} min={0} max={999} hint="As pastas com ordem menor aparecem primeiro." />
      </div>
    </Sheet>
  );
}

/* ==========================================================================
   Sugestões
   ========================================================================== */
export function RssSuggestionsPanel({ ctx }: { ctx: RssCtx }) {
  const [items, setItems] = useState<RssSuggestion[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await rss.getRssSuggestions();
      setItems(payload.items);
      setCategories(payload.categories);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  const visible = category === "all" ? items : items.filter((item) => item.category === category);

  const subscribe = async (ids: string[]) => {
    if (!ids.length) return;
    setBusy(true);
    try {
      const payload = await rss.subscribeRssSuggestions({ ids });
      ctx.notify(
        payload.failed.length ? `${payload.subscribed} subscrito(s); ${payload.failed.length} falhou/falharam: ${payload.failed[0]}` : `${payload.subscribed} feed(s) subscritos.`,
        payload.failed.length ? "error" : "ok",
      );
      setSelected([]);
      await load();
      ctx.refresh();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Sugestões" hint="Fontes de economia, mercados, reguladores e imprensa nacional e internacional, prontas a subscrever num clique.">
        <button
          type="button"
          disabled={busy || selected.length === 0}
          onClick={() => void subscribe(selected)}
          className="flex items-center gap-1.5 rounded-lg border border-teal-300/40 bg-teal-500/15 px-2.5 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-40"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Subscrever selecionadas ({selected.length})
        </button>
      </PanelHeader>

      <div className="flex flex-wrap gap-1.5">
        <Chip active={category === "all"} onClick={() => setCategory("all")}>
          Todas
        </Chip>
        {categories.map((item) => (
          <Chip key={item} active={category === item} onClick={() => setCategory(item)}>
            {item}
          </Chip>
        ))}
      </div>

      <ul className="grid gap-2 lg:grid-cols-2">
        {visible.map((item) => (
          <li key={item.id} className="flex items-start gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <input
              type="checkbox"
              className="mt-1 h-3.5 w-3.5 accent-teal-400"
              disabled={item.subscribed}
              checked={item.subscribed || selected.includes(item.id)}
              onChange={(event) =>
                setSelected((current) => (event.target.checked ? [...new Set([...current, item.id])] : current.filter((value) => value !== item.id)))
              }
            />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
                <span className="truncate">{item.title}</span>
                {item.subscribed && <CheckCircle2 size={13} className="shrink-0 text-emerald-300" />}
              </p>
              <p className="text-[11px] text-muted-foreground">{item.hint}</p>
              <p className="mt-0.5 truncate text-[10.5px] text-muted-foreground/70">{rss.rssHost(item.url)} · {item.category}</p>
            </div>
            {!item.subscribed && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void subscribe([item.id])}
                className="shrink-0 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground disabled:opacity-50"
              >
                Subscrever
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ==========================================================================
   Agenda
   ========================================================================== */
export function RssSchedulePanel({ ctx }: { ctx: RssCtx }) {
  const [schedule, setSchedule] = useState<RssSchedule | null>(null);
  const [draft, setDraft] = useState<RssSettings | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const payload = await rss.getRssSchedule();
      setSchedule(payload);
      setDraft(payload.settings ?? null);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  const save = async () => {
    if (!draft) return;
    setBusy("save");
    setError(null);
    try {
      const payload = await rss.saveRssSchedule(draft);
      setSchedule(payload.schedule);
      setDraft(payload.settings);
      ctx.notify("Agenda guardada.", "ok");
      ctx.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const field = (patch: Partial<RssSettings>) => setDraft((current) => (current ? { ...current, ...patch } : current));

  if (!draft) {
    return (
      <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar a agenda…
      </p>
    );
  }

  const presets: { label: string; cron: string }[] = [
    { label: "A cada 15 min", cron: "*/15 * * * *" },
    { label: "A cada hora", cron: "0 * * * *" },
    { label: "De 3 em 3 horas", cron: "0 */3 * * *" },
    { label: "Todos os dias às 7h", cron: "0 7 * * *" },
    { label: "Dias úteis às 8h e 18h", cron: "0 8,18 * * 1-5" },
  ];

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Agenda"
        hint="Quando o leitor vai sozinho buscar artigos. A recolha manual (em Fontes) continua disponível a qualquer momento."
      >
        <button
          type="button"
          disabled={busy !== null}
          onClick={() =>
            void (async () => {
              setBusy("now");
              try {
                const payload = await rss.fetchAllRssFeeds(false);
                ctx.notify(`Recolha: ${payload.feeds} fonte(s), ${payload.added} novo(s)${payload.errors ? `, ${payload.errors} erro(s)` : ""}.`, "ok");
                await load();
                ctx.refresh();
              } catch (err) {
                ctx.notify((err as Error).message, "error");
              } finally {
                setBusy(null);
              }
            })()
          }
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground disabled:opacity-50"
        >
          {busy === "now" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Recolher agora
        </button>
      </PanelHeader>

      {schedule && (
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Agendador</p>
            <p className="mt-0.5 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
              <CalendarClock size={14} className={schedule.running ? "text-emerald-300" : "text-rose-300"} />
              {schedule.running ? "ativo" : "inativo"}
            </p>
            {schedule.error && <p className="mt-0.5 text-[10.5px] text-rose-200">{schedule.error}</p>}
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Próxima recolha</p>
            <p className="mt-0.5 text-[13px] font-semibold text-foreground">{schedule.next_run_at ? fullDate(schedule.next_run_at) : "—"}</p>
            <p className="mt-0.5 text-[10.5px] text-muted-foreground">{schedule.scheduled ? schedule.cron : "sem job agendado"}</p>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Última execução</p>
            <p className="mt-0.5 text-[13px] font-semibold text-foreground">{schedule.last_run_at ? fullDate(schedule.last_run_at) : "—"}</p>
            {schedule.last_result && (
              <p className="mt-0.5 text-[10.5px] text-muted-foreground">
                {"feeds" in schedule.last_result ? `${schedule.last_result.feeds} fonte(s), ${schedule.last_result.added} novo(s)` : String(schedule.last_result)}
              </p>
            )}
          </div>
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}

      <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Toggle
              checked={draft.auto_fetch}
              onChange={(next) => field({ auto_fetch: next })}
              label="Recolha automática"
              hint="Desligada, só recolhe quando pedir (Recolher agora)."
            />
          </div>
          <TextInput
            label="Expressão cron"
            value={draft.cron}
            onChange={(next) => field({ cron: next })}
            hint="Cinco campos: minuto hora dia mês dia-da-semana (ex.: 0 * * * *)."
          />
          <TextInput label="Fuso horário" value={draft.timezone} onChange={(next) => field({ timezone: next })} hint="Ex.: Europe/Lisbon." />
          <div className="sm:col-span-2">
            <Field label="Periodicidade frequente">
              <div className="flex flex-wrap gap-1.5">
                {presets.map((preset) => (
                  <Chip key={preset.cron} active={draft.cron === preset.cron} onClick={() => field({ cron: preset.cron })} title={preset.cron}>
                    {preset.label}
                  </Chip>
                ))}
              </div>
            </Field>
          </div>
          <NumberInput
            label="Artigos por fonte"
            value={draft.max_articles_per_feed}
            onChange={(next) => field({ max_articles_per_feed: next })}
            min={20}
            max={5000}
            hint="Favoritos e guardados nunca são removidos."
          />
          <NumberInput
            label="Retenção (dias)"
            value={draft.retention_days}
            onChange={(next) => field({ retention_days: next })}
            min={0}
            max={3650}
            hint="0 = guardar tudo."
          />
          <div className="sm:col-span-2">
            <TagsInput label="Etiquetas por omissão" value={draft.default_tags ?? []} onChange={(next) => field({ default_tags: next })} placeholder="mercados, portugal" />
          </div>
          <div className="sm:col-span-2">
            <Toggle
              checked={draft.mark_read_on_open}
              onChange={(next) => field({ mark_read_on_open: next })}
              label="Marcar como lido ao abrir"
              hint="Aplicado ao abrir um artigo na lista."
            />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void save()}
            className="rounded-lg border border-teal-300/40 bg-teal-500/15 px-3 py-1.5 text-[12px] font-medium text-teal-100 transition hover:bg-teal-500/25 disabled:opacity-50"
          >
            {busy === "save" ? "A guardar…" : "Guardar agenda"}
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              void (async () => {
                setBusy("reload");
                try {
                  const payload = await rss.reloadRssSchedule();
                  setSchedule(payload);
                  ctx.notify("Agendador recarregado.", "ok");
                } catch (err) {
                  ctx.notify((err as Error).message, "error");
                } finally {
                  setBusy(null);
                }
              })()
            }
            className="rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground disabled:opacity-50"
          >
            {busy === "reload" ? "A recarregar…" : "Recarregar agendador"}
          </button>
        </div>
      </section>
    </div>
  );
}

/* ==========================================================================
   Regras automáticas
   ========================================================================== */
const EMPTY_RULE: RssRule = { id: "", term: "", actions: [], tags: [], enabled: true };

export function RssRulesPanel({ ctx }: { ctx: RssCtx }) {
  const [rules, setRules] = useState<RssRule[]>([]);
  const [draft, setDraft] = useState<RssRule>(EMPTY_RULE);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const actions = ctx.catalogue.rule_actions ?? [];

  const load = useCallback(async () => {
    try {
      const payload = await rss.getRssRules();
      setRules(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load, ctx.version]);

  const persist = useCallback(
    async (next: RssRule[], applyNow: boolean) => {
      setBusy("save");
      setError(null);
      try {
        const payload = await rss.saveRssRules(next, applyNow);
        setRules(payload.rules);
        const extra = applyNow ? ` ${payload.applied} artigo(s) alterados, ${payload.matched} correspondência(s).` : "";
        ctx.notify(`Regras guardadas.${extra}`, "ok");
        await load();
        ctx.refresh();
        return true;
      } catch (err) {
        setError((err as Error).message);
        return false;
      } finally {
        setBusy(null);
      }
    },
    [ctx, load],
  );

  const addRule = useCallback(async () => {
    if (draft.term.trim().length < 2 || (!draft.actions.length && !draft.tags.length)) {
      setError("A regra precisa de um termo (2+ letras) e de pelo menos uma ação ou etiqueta.");
      return;
    }
    const next = [...rules, { ...draft, id: "", term: draft.term.trim(), tags: draft.tags }];
    if (await persist(next, false)) setDraft(EMPTY_RULE);
  }, [draft, persist, rules]);

  const toggleAction = (id: string) =>
    setDraft((current) => ({
      ...current,
      actions: current.actions.includes(id) ? current.actions.filter((value) => value !== id) : [...current.actions, id],
    }));

  return (
    <section className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
      <PanelHeader
        title="Regras automáticas"
        hint="Aplicadas aos artigos novos de cada recolha: se o termo aparecer no título, no resumo ou nas categorias, a regra guarda, marca como favorito/lido e junta etiquetas."
      >
        <Btn
          disabled={busy !== null || rules.length === 0}
          onClick={() =>
            void (async () => {
              setBusy("apply");
              try {
                const payload = await rss.applyRssRules(true);
                ctx.notify(`Regras aplicadas: ${payload.applied} artigo(s) alterados, ${payload.matched} correspondência(s).`, "ok");
                await load();
                ctx.refresh();
              } catch (err) {
                ctx.notify((err as Error).message, "error");
              } finally {
                setBusy(null);
              }
            })()
          }
        >
          {busy === "apply" ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Aplicar agora
        </Btn>
      </PanelHeader>

      {error && (
        <div className="mb-2">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {/* Nova regra */}
      <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput
            label="Termo a encontrar"
            value={draft.term}
            onChange={(next) => setDraft((current) => ({ ...current, term: next }))}
            placeholder="ex.: juros, habitação, IA"
            hint="Comparação sem acentos nem maiúsculas."
          />
          <TagsInput
            label="Etiquetas a juntar"
            value={draft.tags}
            onChange={(next) => setDraft((current) => ({ ...current, tags: next }))}
            placeholder="macroeconomia, imobiliário"
          />
          <div className="sm:col-span-2">
            <Field label="Ações">
              <div className="flex flex-wrap gap-1.5">
                {actions.map((action) => (
                  <Chip key={action.id} active={draft.actions.includes(action.id)} onClick={() => toggleAction(action.id)}>
                    {action.label}
                  </Chip>
                ))}
              </div>
            </Field>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Btn variant="primary" disabled={busy !== null} onClick={() => void addRule()}>
            {busy === "save" ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Adicionar regra
          </Btn>
          <Btn
            disabled={busy !== null || draft.term.trim().length < 2}
            onClick={() =>
              void (async () => {
                if (await persist([...rules, { ...draft, id: "", term: draft.term.trim() }], true)) setDraft(EMPTY_RULE);
              })()
            }
          >
            <Sparkles size={13} /> Adicionar e aplicar aos artigos
          </Btn>
        </div>
      </div>

      {/* Lista */}
      {rules.length === 0 ? (
        <p className="mt-3 text-[11.5px] text-muted-foreground">
          Sem regras. Um exemplo útil: termo <em>juros</em> → guardar + favorito + etiqueta <em>macroeconomia</em>.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {rules.map((rule, index) => (
            <li key={rule.id || `${rule.term}-${index}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2">
              <input
                type="checkbox"
                aria-label={`Ativar a regra ${rule.term}`}
                className="h-4 w-4 accent-teal-400"
                checked={rule.enabled}
                onChange={(event) => {
                  const next = rules.map((item, position) => (position === index ? { ...item, enabled: event.target.checked } : item));
                  void persist(next, false);
                }}
              />
              <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[11.5px] text-foreground">{rule.term}</span>
              <span className="text-[11.5px] text-muted-foreground">
                {rule.actions.length ? rule.actions.join(" · ") : "só etiquetas"}
                {rule.tags.length ? ` → ${rule.tags.join(", ")}` : ""}
              </span>
              <span className="ml-auto text-[10.5px] text-muted-foreground">
                {rule.hits ?? 0} artigo(s)
                <button
                  type="button"
                  aria-label={`Remover a regra ${rule.term}`}
                  className="ml-2 align-middle text-muted-foreground transition hover:text-rose-200"
                  onClick={() => void persist(rules.filter((_item, position) => position !== index), false)}
                >
                  <Trash2 size={13} className="inline" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
