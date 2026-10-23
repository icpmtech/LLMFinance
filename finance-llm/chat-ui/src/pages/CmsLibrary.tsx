/**
 * Biblioteca do CMS — **conteúdos** reutilizáveis, **media**, **taxonomia**,
 * **modelos**, **contactos** recebidos pelo site e **aparência** (definições do
 * site + menus).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  CornerDownRight,
  ExternalLink,
  FileText,
  Inbox,
  Link2,
  Loader2,
  Mail,
  Palette,
  Pencil,
  Plus,
  RefreshCw,
  Recycle,
  Save,
  Search,
  Tags,
  Trash2,
  Upload,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import {
  BlockEditor,
  IconAction,
  ListRow,
  MediaPicker,
  Notice,
  PanelHeader,
  SelectInput,
  Sheet,
  TextArea,
  TextInput,
  Toggle,
  formatBytes,
  timeAgo,
} from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type {
  CmsCategory,
  CmsContacto,
  CmsContent,
  CmsMedia,
  CmsMenu,
  CmsMenuItem,
  CmsMenuTheme,
  CmsPartilha,
  CmsPartilhaModelo,
  CmsSettings,
  CmsTemplate,
} from "../cmsApi";
import type { CmsCtx } from "./CmsPanels";
import { useAuth } from "../auth";

function openExternal(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

/* ================================================================ conteúdos */

const KIND_FIELDS: Record<string, { key: string; label: string }[]> = {
  hero: [
    { key: "title", label: "Título" },
    { key: "subtitle", label: "Subtítulo" },
  ],
  cta: [
    { key: "title", label: "Título" },
    { key: "text", label: "Texto" },
    { key: "button_label", label: "Botão — texto" },
    { key: "button_href", label: "Botão — ligação" },
  ],
  aviso: [{ key: "tone", label: "Tom (info, green, amber, red)" }],
  citacao: [{ key: "author", label: "Autor" }],
  contactos: [
    { key: "email", label: "Email" },
    { key: "phone", label: "Telefone" },
    { key: "address", label: "Morada" },
  ],
};

export function CmsContentsPanel({ ctx }: { ctx: CmsCtx }) {
  const [items, setItems] = useState<CmsContent[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Partial<CmsContent> | null>(null);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await cms.listCmsContents({ limit: 300 });
      setItems(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? items.filter((item) => `${item.title} ${item.kind} ${(item.tags ?? []).join(" ")}`.toLowerCase().includes(needle)) : items;
  }, [items, query]);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const payload = {
        title: draft.title ?? "",
        kind: draft.kind ?? "texto",
        body: draft.body ?? "",
        data: draft.data ?? {},
        tags: draft.tags ?? [],
        notes: draft.notes ?? "",
      };
      const result = draft.id ? await cms.updateCmsContent(draft.id, payload) : await cms.createCmsContent(payload);
      setDraft(result.item);
      ctx.notify("Conteúdo guardado.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const fields = KIND_FIELDS[draft?.kind ?? "texto"] ?? [];

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Conteúdos"
        hint="Blocos com nome próprio (um rodapé, uma chamada à ação, contactos…) que várias páginas podem inserir com o bloco «Conteúdo reutilizado». Alterar aqui muda em todas as páginas."
      >
        <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setDraft({ title: "", kind: "texto", body: "", data: {}, tags: [] })}>
          Novo conteúdo
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" placeholder="Procurar conteúdo…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
      </div>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar conteúdos…
        </p>
      ) : filtered.length === 0 ? (
        <Notice>Nenhum conteúdo guardado.</Notice>
      ) : (
        <div className="space-y-1.5">
          {filtered.map((item) => (
            <ListRow
              key={item.id}
              icon={<Recycle size={13} />}
              title={item.title}
              subtitle={`${item.kind} · usado em ${item.uses ?? 0} bloco(s) · ${timeAgo(item.updated_at)}`}
              meta={<span>{(item.tags ?? []).join(", ") || "sem etiquetas"}</span>}
              onClick={() => setDraft(item)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => setDraft(item)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction title="Duplicar" onClick={() => void cms.duplicateCmsEntity<CmsContent>("contents", item.id).then(() => load()).catch((err) => ctx.notify((err as Error).message, "error"))}>
                    <Copy size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={async () => {
                      if (!window.confirm(`Apagar o conteúdo «${item.title}»?`)) return;
                      try {
                        await cms.deleteCmsEntity("contents", item.id);
                        await load();
                        ctx.refreshOverview();
                        ctx.notify("Conteúdo apagado.", "ok");
                      } catch (err) {
                        ctx.notify((err as Error).message, "error");
                      }
                    }}
                  >
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
          busy={busy}
          title={draft.id ? `Conteúdo · ${draft.title || "(sem nome)"}` : "Novo conteúdo"}
          subtitle="O corpo é Markdown; os campos extra dependem do tipo."
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
              <TextInput label="Nome" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <SelectInput
                label="Tipo"
                value={draft.kind ?? "texto"}
                onChange={(next) => setDraft({ ...draft, kind: next })}
                options={ctx.catalogue.content_kinds.map((item) => ({ value: item.id, label: item.label }))}
                wide
              />
              <TextArea label="Corpo (Markdown)" value={draft.body ?? ""} onChange={(next) => setDraft({ ...draft, body: next })} rows={6} wide />
            </div>

            {fields.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-2 rounded-xl border border-white/8 bg-white/[0.03] p-3">
                {fields.map((field) => (
                  <TextInput
                    key={field.key}
                    label={field.label}
                    value={String((draft.data ?? {})[field.key] ?? "")}
                    onChange={(next) => setDraft({ ...draft, data: { ...(draft.data ?? {}), [field.key]: next } })}
                    wide={field.key === "text" || field.key === "address" || field.key === "title" || field.key === "subtitle"}
                  />
                ))}
              </div>
            )}

            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Etiquetas" value={(draft.tags ?? []).join(", ")} onChange={(next) => setDraft({ ...draft, tags: next.split(",").map((tag) => tag.trim()).filter(Boolean) })} />
              <TextInput label="Notas internas" value={draft.notes ?? ""} onChange={(next) => setDraft({ ...draft, notes: next })} />
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <button type="button" className="text-[11.5px] text-muted-foreground underline" onClick={() => setAdvanced((value) => !value)}>
                {advanced ? "Esconder" : "Mostrar"} dados avançados (JSON)
              </button>
              {advanced && (
                <TextArea
                  label="data"
                  value={JSON.stringify(draft.data ?? {}, null, 2)}
                  onChange={(next) => {
                    try {
                      setDraft({ ...draft, data: JSON.parse(next) as Record<string, string> });
                    } catch {
                      /* JSON ainda inválido: mantém o que estava */
                    }
                  }}
                  rows={8}
                  mono
                />
              )}
            </div>
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* ==================================================================== media */

export function CmsMediaPanel({ ctx }: { ctx: CmsCtx }) {
  const [items, setItems] = useState<CmsMedia[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [draft, setDraft] = useState<CmsMedia | null>(null);
  const [usage, setUsage] = useState<{ entity: string; id: string; title: string; where: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [externalUrl, setExternalUrl] = useState("");
  const [dragging, setDragging] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await cms.listCmsMedia({ limit: 300 });
      setItems(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (kind && item.kind !== kind) return false;
      if (!needle) return true;
      return `${item.title} ${item.filename} ${(item.tags ?? []).join(" ")}`.toLowerCase().includes(needle);
    });
  }, [items, query, kind]);

  const upload = async (files: FileList | File[]) => {
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const data = await cms.fileToBase64(file);
        await cms.uploadCmsMedia({ filename: file.name, mime: file.type || "application/octet-stream", data, title: file.name });
      }
      ctx.notify("Ficheiro(s) carregado(s).", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const openDetail = async (media: CmsMedia) => {
    setDraft(media);
    setUsage([]);
    try {
      const payload = await cms.getCmsMediaUsage(media.id);
      setUsage(payload.items);
    } catch {
      /* uso é informativo */
    }
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const result = await cms.updateCmsMedia(draft.id, {
        title: draft.title,
        alt: draft.alt,
        caption: draft.caption,
        credit: draft.credit,
        tags: draft.tags,
      });
      setDraft(result.item);
      ctx.notify("Media atualizado.", "ok");
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Media" hint="Imagens, PDF e outros ficheiros usados nas páginas e nos artigos. Ficam guardados na plataforma e servidos em /cms/media/<id>/raw.">
        <Button size="sm" variant="secondary" icon={<Link2 size={13} />} onClick={() => setDraft(null)}>
          Registar URL
        </Button>
      </PanelHeader>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (event.dataTransfer.files.length) void upload(event.dataTransfer.files);
        }}
        className={`rounded-xl border border-dashed px-4 py-6 text-center transition ${dragging ? "border-teal-300/50 bg-teal-400/10" : "border-white/12 bg-white/[0.02]"}`}
      >
        <p className="text-[12.5px] text-foreground">Arraste ficheiros para aqui ou escolha do computador.</p>
        <p className="mt-1 text-[11px] text-muted-foreground">Imagens, PDF e outros formatos até 12 MB por ficheiro.</p>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-teal-500/90 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-teal-400">
            <Upload size={13} />
            Escolher ficheiros
            <input
              type="file"
              multiple
              className="hidden"
              onChange={(event) => {
                if (event.target.files?.length) void upload(event.target.files);
                event.target.value = "";
              }}
            />
          </label>
          {busy && (
            <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> A carregar…
            </span>
          )}
        </div>
        <div className="mx-auto mt-3 flex max-w-xl flex-wrap items-center gap-2">
          <input className="min-w-[220px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-teal-300/40" placeholder="…ou cole um URL de imagem externo" value={externalUrl} onChange={(event) => setExternalUrl(event.target.value)} />
          <Button
            size="sm"
            variant="secondary"
            onClick={async () => {
              if (!externalUrl.trim()) return;
              try {
                await cms.registerCmsMediaUrl({ url: externalUrl.trim() });
                setExternalUrl("");
                await load();
                ctx.notify("Media externo registado.", "ok");
              } catch (err) {
                ctx.notify((err as Error).message, "error");
              }
            }}
          >
            Registar
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" placeholder="Procurar media…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <SelectInput label="" value={kind} onChange={setKind} options={[{ value: "imagem", label: "Imagens" }, { value: "documento", label: "Documentos" }]} placeholder="Todos os tipos" />
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
      </div>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar a biblioteca…
        </p>
      ) : filtered.length === 0 ? (
        <Notice>Ainda não há media na biblioteca.</Notice>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {filtered.map((media) => (
            <div key={media.id} className="overflow-hidden rounded-xl border border-white/8 bg-white/[0.03]">
              <button type="button" onClick={() => void openDetail(media)} className="block w-full">
                {media.kind === "imagem" ? (
                  <img src={cms.cmsMediaUrl(media)} alt={media.alt || media.title} className="h-32 w-full object-cover" />
                ) : (
                  <div className="grid h-32 w-full place-items-center bg-white/[0.04] text-muted-foreground">
                    <FileText size={26} />
                  </div>
                )}
              </button>
              <div className="px-2.5 py-2">
                <p className="truncate text-[12px] font-medium text-foreground">{media.title || media.filename}</p>
                <p className="mt-0.5 text-[10.5px] text-muted-foreground">
                  {media.mime} · {media.size ? formatBytes(media.size) : "externo"}
                </p>
                <div className="mt-1.5 flex items-center gap-1">
                  <IconAction title="Editar" onClick={() => void openDetail(media)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction title="Copiar URL" onClick={() => void navigator.clipboard.writeText(cms.cmsMediaUrl(media)).then(() => ctx.notify("URL copiado.", "ok"))}>
                    <Link2 size={12} />
                  </IconAction>
                  <IconAction title="Abrir" onClick={() => openExternal(cms.cmsMediaUrl(media))}>
                    <ExternalLink size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={async () => {
                      if (!window.confirm(`Apagar «${media.title || media.filename}»?`)) return;
                      try {
                        await cms.deleteCmsEntity("media", media.id);
                        await load();
                        ctx.refreshOverview();
                        ctx.notify("Media apagado.", "ok");
                      } catch (err) {
                        ctx.notify((err as Error).message, "error");
                      }
                    }}
                  >
                    <Trash2 size={12} />
                  </IconAction>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {draft && (
        <Sheet
          busy={busy}
          title={draft.title || draft.filename}
          subtitle={draft.mime}
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
            {draft.kind === "imagem" && <img src={cms.cmsMediaUrl(draft)} alt={draft.alt || ""} className="max-h-64 w-full rounded-xl border border-white/8 object-contain" />}
            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Título" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <TextInput label="Texto alternativo" value={draft.alt ?? ""} onChange={(next) => setDraft({ ...draft, alt: next })} wide hint="Descreve a imagem para quem não a vê." />
              <TextInput label="Legenda" value={draft.caption ?? ""} onChange={(next) => setDraft({ ...draft, caption: next })} />
              <TextInput label="Crédito" value={draft.credit ?? ""} onChange={(next) => setDraft({ ...draft, credit: next })} />
              <TextInput label="Etiquetas" value={(draft.tags ?? []).join(", ")} onChange={(next) => setDraft({ ...draft, tags: next.split(",").map((tag) => tag.trim()).filter(Boolean) })} wide />
              <div className="sm:col-span-2">
                <TextInput label="URL" value={cms.cmsMediaUrl(draft)} onChange={() => undefined} wide />
              </div>
            </div>
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Onde é usado" hint="Se estiver em uso, apagar deixa imagens em falta nas páginas indicadas." />
              {usage.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">Sem utilizações registadas.</p>
              ) : (
                <ul className="space-y-1 text-[12px] text-foreground">
                  {usage.map((entry) => (
                    <li key={`${entry.entity}-${entry.id}-${entry.where}`}>
                      {entry.entity === "pages" ? "Página" : entry.entity === "posts" ? "Artigo" : "Definições"}: <span className="font-medium">{entry.title}</span>{" "}
                      <span className="text-muted-foreground">({entry.where})</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* ================================================================ taxonomia */

export function CmsTaxonomyPanel({ ctx }: { ctx: CmsCtx }) {
  const [categories, setCategories] = useState<CmsCategory[]>([]);
  const [tags, setTags] = useState<{ tag: string; posts: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<Partial<CmsCategory> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await cms.getCmsTaxonomy();
      setCategories(payload.categories);
      setTags(payload.tags);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const payload = { name: draft.name ?? "", slug: draft.slug, description: draft.description ?? "", color: draft.color ?? "", parent_id: draft.parent_id ?? null };
      const result = draft.id ? await cms.updateCmsCategory(draft.id, payload) : await cms.createCmsCategory(payload);
      setDraft(result.item);
      ctx.notify("Categoria guardada.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Taxonomia" hint="Categorias (agrupam artigos, com página pública própria) e etiquetas (livres, acumuladas a partir dos artigos).">
        <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setDraft({ name: "", description: "", color: "#0ea5a4", parent_id: null })}>
          Nova categoria
        </Button>
      </PanelHeader>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar…
        </p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <PanelHeader title="Categorias" hint="Aparecem no topo do blog e em /site/categoria/<slug>." />
            <div className="space-y-1.5">
              {categories.length === 0 && <p className="text-[12px] text-muted-foreground">Sem categorias.</p>}
              {categories.map((category) => (
                <ListRow
                  key={category.id}
                  icon={<span className="h-3 w-3 rounded-full" style={{ background: category.color || "#64748b" }} />}
                  title={category.name}
                  subtitle={`/site/categoria/${category.slug} · ${category.posts ?? 0} artigo(s)`}
                  onClick={() => setDraft(category)}
                  actions={
                    <>
                      <IconAction title="Editar" onClick={() => setDraft(category)}>
                        <Pencil size={12} />
                      </IconAction>
                      <IconAction title="Apagar" danger onClick={async () => {
                        if (!window.confirm(`Apagar a categoria «${category.name}»? Os artigos ficam sem esta categoria.`)) return;
                        try {
                          await cms.deleteCmsEntity("categories", category.id);
                          await load();
                          ctx.refreshOverview();
                        } catch (err) {
                          ctx.notify((err as Error).message, "error");
                        }
                      }}>
                        <Trash2 size={12} />
                      </IconAction>
                    </>
                  }
                />
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <PanelHeader title="Etiquetas" hint="Criadas ao escrever os artigos; aqui vê os números e as páginas públicas." />
            <div className="flex flex-wrap gap-1.5">
              {tags.length === 0 && <p className="text-[12px] text-muted-foreground">Sem etiquetas.</p>}
              {tags.map((entry) => (
                <button
                  key={entry.tag}
                  type="button"
                  onClick={() => openExternal(cms.cmsPublicUrl(`/etiqueta/${encodeURIComponent(entry.tag)}`))}
                  className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
                  title="Abrir a página pública da etiqueta"
                >
                  <Tags size={10} className="mr-1 inline" />
                  {entry.tag} · {entry.posts}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {draft && (
        <Sheet
          busy={busy}
          title={draft.id ? `Categoria · ${draft.name}` : "Nova categoria"}
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
          <div className="grid gap-2 sm:grid-cols-2">
            <TextInput label="Nome" value={draft.name ?? ""} onChange={(next) => setDraft({ ...draft, name: next })} wide />
            <TextInput label="Endereço (slug)" value={draft.slug ?? ""} onChange={(next) => setDraft({ ...draft, slug: next })} hint="Vazio = gerado do nome." />
            <TextInput label="Cor" value={draft.color ?? ""} onChange={(next) => setDraft({ ...draft, color: next })} placeholder="#0ea5a4" />
            <TextArea label="Descrição" value={draft.description ?? ""} onChange={(next) => setDraft({ ...draft, description: next })} rows={3} wide />
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* =============================================================== contactos */

const ESTADOS_CONTACTO: { id: CmsContacto["estado"]; label: string }[] = [
  { id: "novo", label: "Novo" },
  { id: "em_curso", label: "Em curso" },
  { id: "tratado", label: "Tratado" },
];

const TOM_CONTACTO: Record<string, string> = {
  novo: "border-teal-300/30 bg-teal-400/10 text-teal-100",
  em_curso: "border-amber-300/30 bg-amber-400/10 text-amber-100",
  tratado: "border-emerald-300/30 bg-emerald-400/10 text-emerald-100",
};

/** Mensagens recebidas pelo formulário do site (`POST /site/contacto`). */
export function CmsContactosPanel({ ctx }: { ctx: CmsCtx }) {
  const [items, setItems] = useState<CmsContacto[]>([]);
  const [loading, setLoading] = useState(true);
  const [filtro, setFiltro] = useState<"todos" | CmsContacto["estado"]>("todos");
  const [aberto, setAberto] = useState<CmsContacto | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await cms.listCmsContactos();
      setItems(payload.items ?? []);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const guardar = async (contacto: CmsContacto, campos: Partial<CmsContacto>) => {
    setBusy(true);
    try {
      const result = await cms.updateCmsContacto(contacto.id, campos);
      setAberto(result.item);
      setItems((atuais) => atuais.map((item) => (item.id === result.item.id ? result.item : item)));
      ctx.notify("Contacto atualizado.", "ok");
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const visiveis = filtro === "todos" ? items : items.filter((item) => item.estado === filtro);
  const contagem = (estado: CmsContacto["estado"]) => items.filter((item) => item.estado === estado).length;

  return (
    <div className="space-y-3">
      <PanelHeader title="Contactos" hint="Pedidos enviados pelo formulário do site. Responda pelo email indicado — a resposta sai da sua caixa de correio.">
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap gap-1.5">
        {(["todos", "novo", "em_curso", "tratado"] as const).map((estado) => (
          <button
            key={estado}
            type="button"
            onClick={() => setFiltro(estado)}
            className={[
              "rounded-full border px-2.5 py-1 text-[11.5px] transition",
              filtro === estado ? "border-teal-300/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:bg-white/[0.09]",
            ].join(" ")}
          >
            {estado === "todos" ? "Todos" : ESTADOS_CONTACTO.find((item) => item.id === estado)?.label} ·{" "}
            {estado === "todos" ? items.length : contagem(estado)}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar…
        </p>
      ) : visiveis.length === 0 ? (
        <p className="rounded-xl border border-dashed border-white/12 px-3 py-8 text-center text-[12px] text-muted-foreground">
          Sem contactos nesta vista. O formulário da página «Contactos» do site escreve aqui.
        </p>
      ) : (
        <div className="space-y-1.5">
          {visiveis.map((contacto) => (
            <ListRow
              key={contacto.id}
              icon={<Inbox size={13} />}
              title={contacto.nome + (contacto.organizacao ? ` · ${contacto.organizacao}` : "")}
              subtitle={`${contacto.email}${contacto.assunto ? ` · ${contacto.assunto}` : ""} · ${timeAgo(contacto.created_at)}`}
              badges={
                <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${TOM_CONTACTO[contacto.estado] ?? ""}`}>
                  {ESTADOS_CONTACTO.find((item) => item.id === contacto.estado)?.label ?? contacto.estado}
                </span>
              }
              meta={<span className="hidden sm:inline">{contacto.mensagem.slice(0, 60)}</span>}
              onClick={() => setAberto(contacto)}
              actions={
                <>
                  <IconAction title="Responder por email" onClick={() => openExternal(`mailto:${contacto.email}${contacto.assunto ? `?subject=${encodeURIComponent(`Re: ${contacto.assunto}`)}` : ""}`)}>
                    <Mail size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={async () => {
                      if (!window.confirm(`Apagar a mensagem de ${contacto.nome}?`)) return;
                      try {
                        await cms.deleteCmsEntity("contactos", contacto.id);
                        setItems((atuais) => atuais.filter((item) => item.id !== contacto.id));
                        ctx.notify("Contacto apagado.", "ok");
                        ctx.refreshOverview();
                      } catch (err) {
                        ctx.notify((err as Error).message, "error");
                      }
                    }}
                  >
                    <Trash2 size={12} />
                  </IconAction>
                </>
              }
            />
          ))}
        </div>
      )}

      {aberto && (
        <Sheet
          busy={busy}
          title={`${aberto.nome}${aberto.organizacao ? ` · ${aberto.organizacao}` : ""}`}
          onClose={() => setAberto(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" onClick={() => setAberto(null)}>
                Fechar
              </Button>
              <Button size="sm" variant="secondary" loading={busy} onClick={() => void guardar(aberto, { estado: aberto.estado, notas: aberto.notas ?? "" })}>
                Guardar notas
              </Button>
              <Button size="sm" variant="primary" icon={<Mail size={13} />} onClick={() => openExternal(`mailto:${aberto.email}`)}>
                Responder
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-1 text-[12.5px] sm:grid-cols-2">
              <p>
                <span className="text-muted-foreground">Email: </span>
                <a className="text-teal-200" href={`mailto:${aberto.email}`}>
                  {aberto.email}
                </a>
              </p>
              <p>
                <span className="text-muted-foreground">Assunto: </span>
                {aberto.assunto || "—"}
              </p>
            </div>
            <SelectInput
              label="Estado"
              value={aberto.estado}
              onChange={(next) => void guardar(aberto, { estado: next as CmsContacto["estado"] })}
              options={ESTADOS_CONTACTO.map((item) => ({ value: item.id, label: item.label }))}
              wide
            />
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3 text-[12.5px] whitespace-pre-wrap text-foreground">
              {aberto.mensagem}
            </div>
            <TextArea label="Notas internas" value={aberto.notas ?? ""} onChange={(next) => setAberto({ ...aberto, notas: next })} rows={3} />
            <p className="text-[11px] text-muted-foreground">
              Recebido {timeAgo(aberto.created_at)} · consentimento {aberto.consentimento ? "dado" : "não registado"}
              {aberto.origem ? ` · origem ${aberto.origem}` : ""}
            </p>
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* ================================================================= modelos */

export function CmsTemplatesPanel({ ctx }: { ctx: CmsCtx }) {
  const [items, setItems] = useState<CmsTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<Partial<CmsTemplate> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await cms.listCmsTemplates({ limit: 100 });
      setItems(payload.items);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const payload = { name: draft.name ?? "", kind: draft.kind ?? "page", description: draft.description ?? "", blocks: draft.blocks ?? [] };
      const result = draft.id ? await cms.updateCmsTemplate(draft.id, payload) : await cms.createCmsTemplate(payload);
      setDraft(result.item);
      ctx.notify("Modelo guardado.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Modelos" hint="Estruturas de blocos prontas a usar numa página nova (landing, institucional, artigo…).">
        <Button size="sm" variant="primary" icon={<Plus size={13} />} onClick={() => setDraft({ name: "", kind: "page", description: "", blocks: [] })}>
          Novo modelo
        </Button>
      </PanelHeader>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar modelos…
        </p>
      ) : items.length === 0 ? (
        <Notice>Sem modelos definidos.</Notice>
      ) : (
        <div className="space-y-1.5">
          {items.map((template) => (
            <ListRow
              key={template.id}
              icon={<Palette size={13} />}
              title={template.name}
              subtitle={`${template.kind === "page" ? "Página" : "Artigo"} · ${(template.blocks ?? []).length} bloco(s) · ${template.description || "sem descrição"}`}
              badges={template.builtin ? <span className="rounded-full border border-white/12 bg-white/[0.06] px-2 py-0.5 text-[10.5px] text-muted-foreground">de origem</span> : undefined}
              onClick={() => setDraft({ ...template, blocks: template.blocks ?? [] })}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => setDraft({ ...template, blocks: template.blocks ?? [] })}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction title="Duplicar" onClick={() => void cms.duplicateCmsEntity<CmsTemplate>("templates", template.id).then(() => load()).catch((err) => ctx.notify((err as Error).message, "error"))}>
                    <Copy size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={async () => {
                      if (!window.confirm(`Apagar o modelo «${template.name}»?`)) return;
                      try {
                        await cms.deleteCmsEntity("templates", template.id);
                        await load();
                        ctx.refreshOverview();
                      } catch (err) {
                        ctx.notify((err as Error).message, "error");
                      }
                    }}
                  >
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
          title={draft.id ? `Modelo · ${draft.name}` : "Novo modelo"}
          subtitle="Os blocos do modelo são copiados para a página nova (ficam independentes)."
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
              <TextInput label="Nome" value={draft.name ?? ""} onChange={(next) => setDraft({ ...draft, name: next })} wide />
              <SelectInput
                label="Serve para"
                value={draft.kind ?? "page"}
                onChange={(next) => setDraft({ ...draft, kind: next as "page" | "post" })}
                options={ctx.catalogue.template_kinds.map((item) => ({ value: item.id, label: item.label }))}
              />
              <TextInput label="Descrição" value={draft.description ?? ""} onChange={(next) => setDraft({ ...draft, description: next })} wide />
            </div>
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Blocos do modelo" />
              <BlockEditor
                blocks={(draft.blocks ?? []) as never}
                onChange={(next) => setDraft({ ...draft, blocks: next as CmsTemplate["blocks"] })}
                blockTypes={ctx.catalogue.block_types}
                heroStyles={ctx.catalogue.hero_styles}
                heroTones={ctx.catalogue.hero_tones}
                media={ctx.catalogue.media_index}
                contents={ctx.catalogue.contents_index}
                categories={ctx.catalogue.categories_index}
              />
            </div>
          </div>
        </Sheet>
      )}
    </div>
  );
}

/* =============================================================== aparência */

type MenuDraft = CmsMenu & { saved?: boolean };

/** Profundidade máxima dos submenus, igual à que o servidor aceita. */
const MENU_MAX_DEPTH = 2;

function newMenuItem(): CmsMenuItem {
  return { id: `mi_${Math.random().toString(36).slice(2, 8)}`, label: "", href: "", page_id: null, new_tab: false };
}

/** Aplica uma alteração a um item, onde quer que ele esteja na árvore. */
function mapMenuItem(items: CmsMenuItem[], id: string, mutate: (item: CmsMenuItem) => CmsMenuItem): CmsMenuItem[] {
  return items.map((item) => {
    if (item.id === id) return mutate(item);
    return item.children?.length ? { ...item, children: mapMenuItem(item.children, id, mutate) } : item;
  });
}

/** Retira um item (e os submenus que ele abria) da árvore. */
function removeMenuItem(items: CmsMenuItem[], id: string): CmsMenuItem[] {
  return items
    .filter((item) => item.id !== id)
    .map((item) => (item.children?.length ? { ...item, children: removeMenuItem(item.children, id) } : item));
}

/** Troca um item com o irmão de cima ou de baixo (dentro do mesmo nível). */
function moveMenuItem(items: CmsMenuItem[], id: string, delta: number): CmsMenuItem[] {
  const index = items.findIndex((entry) => entry.id === id);
  if (index >= 0) {
    const target = index + delta;
    if (target < 0 || target >= items.length) return items;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  }
  return items.map((item) => (item.children?.length ? { ...item, children: moveMenuItem(item.children, id, delta) } : item));
}

export function CmsAppearancePanel({ ctx }: { ctx: CmsCtx }) {
  const { user } = useAuth();
  const isAdmin = (user?.role ?? "member") === "admin";
  const [settings, setSettings] = useState<CmsSettings | null>(null);
  const [menus, setMenus] = useState<MenuDraft[]>([]);
  const [menuThemes, setMenuThemes] = useState<CmsMenuTheme[]>([]);
  const [pages, setPages] = useState<{ id: string; title: string; path: string }[]>([]);
  const [modelos, setModelos] = useState<CmsPartilhaModelo[]>(() => ctx.catalogue.partilha_modelos ?? []);
  const [novoModelo, setNovoModelo] = useState("");
  const [modeloBusy, setModeloBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [menuBusy, setMenuBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [payload, menuPayload, pagesPayload] = await Promise.all([
        cms.getCmsSettings(),
        cms.listCmsMenus(),
        cms.listCmsPages({ limit: 300 }),
      ]);
      setSettings(payload.settings);
      setMenus(menuPayload.items.map((menu) => ({ ...menu, items: menu.items ?? [] })));
      setMenuThemes(menuPayload.themes ?? []);
      setPages(pagesPayload.items.filter((page) => page.status === "publicado").map((page) => ({ id: page.id, title: page.title, path: page.path })));
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }, [ctx]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveSettings = async () => {
    if (!settings) return;
    setBusy(true);
    try {
      const result = await cms.saveCmsSettings(settings);
      setSettings(result.settings);
      ctx.notify("Definições guardadas.", "ok");
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const saveMenu = async (menu: MenuDraft) => {
    setMenuBusy(menu.id);
    try {
      const result = await cms.saveCmsMenu({
        id: menu.id,
        name: menu.name,
        location: menu.location,
        menu_theme: menu.menu_theme,
        menu_template: menu.menu_template,
        items: menu.items,
      });
      setMenus((current) => current.map((entry) => (entry.id === menu.id ? { ...result.menu, items: result.menu.items ?? [] } : entry)));
      ctx.notify("Menu guardado.", "ok");
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setMenuBusy(null);
    }
  };

  const patchMenuItems = (menuId: string, items: CmsMenuItem[]) => {
    setMenus((current) => current.map((menu) => (menu.id === menuId ? { ...menu, items } : menu)));
  };

  const mutateMenuItem = (menu: MenuDraft, id: string, mutate: (item: CmsMenuItem) => CmsMenuItem) =>
    patchMenuItems(menu.id, mapMenuItem(menu.items, id, mutate));

  const patchMenuTheme = (menu: MenuDraft, themeId: string) => {
    const theme = menuThemes.find((entry) => entry.id === themeId);
    const templateId = theme?.templates[0]?.id ?? "padrao";
    setMenus((current) => current.map((entry) => (entry.id === menu.id ? { ...entry, menu_theme: themeId, menu_template: templateId } : entry)));
  };

  const patchMenuTemplate = (menu: MenuDraft, templateId: string) => {
    setMenus((current) => current.map((entry) => (entry.id === menu.id ? { ...entry, menu_template: templateId } : entry)));
  };

  /* -------------------------------------------------- partilha e favoritos */
  const partilha: CmsPartilha = settings?.partilha ?? ctx.catalogue.partilha;
  const redesEscolhidas = useMemo(() => new Set(partilha.redes ?? []), [partilha.redes]);
  // As redes de perfil (GitHub) ficam nas ligações, não no menu de partilha.
  const redesDoMenu = useMemo(
    () => ctx.catalogue.redes_partilha.filter((rede) => rede.menu !== "nao"),
    [ctx.catalogue.redes_partilha],
  );

  const patchPartilha = (patch: Partial<CmsPartilha>) =>
    setSettings((current) => (current ? { ...current, partilha: { ...current.partilha, ...patch } } : current));

  /** Liga/desliga uma rede e guarda a lista pela ordem do catálogo. */
  const alternarRede = (redeId: string) => {
    const proximas = new Set(redesEscolhidas);
    if (proximas.has(redeId)) proximas.delete(redeId);
    else proximas.add(redeId);
    patchPartilha({ redes: redesDoMenu.map((rede) => rede.id).filter((id) => proximas.has(id)), modelo: "" });
  };

  /** Aplica um modelo de configuração (grava já no servidor — só administradores). */
  const aplicarModelo = async (modelo: CmsPartilhaModelo) => {
    setModeloBusy(modelo.id);
    try {
      const result = await cms.applyCmsPartilhaModelo(modelo.id);
      setSettings(result.settings);
      ctx.notify(`Modelo «${modelo.name}» aplicado.`, "ok");
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setModeloBusy(null);
    }
  };

  const criarModelo = async () => {
    const nome = novoModelo.trim();
    if (!nome) return;
    setModeloBusy("novo");
    try {
      const result = await cms.saveCmsPartilhaModelo({ name: nome, description: "Guardado a partir da configuração atual.", partilha });
      setModelos(result.modelos);
      // A lista personalizada das definições acompanha (senão a próxima gravação
      // da aparência repunha os modelos antigos por cima).
      setSettings((current) => (current ? { ...current, partilha_modelos: result.modelos.filter((item) => !item.builtin) } : current));
      setNovoModelo("");
      ctx.notify("Modelo criado.", "ok");
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setModeloBusy(null);
    }
  };

  const apagarModelo = async (modelo: CmsPartilhaModelo) => {
    if (!window.confirm(`Apagar o modelo «${modelo.name}»?`)) return;
    setModeloBusy(modelo.id);
    try {
      const result = await cms.deleteCmsPartilhaModelo(modelo.id);
      setModelos(result.modelos);
      setSettings((current) => (current ? { ...current, partilha_modelos: result.modelos.filter((item) => !item.builtin) } : current));
      ctx.notify("Modelo apagado.", "ok");
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setModeloBusy(null);
    }
  };

  /**
   * Editor de um nível do menu. Cada item pode abrir um **submenu**: um segundo
   * (e terceiro) nível, indentado por baixo do item que o abre e com os mesmos
   * campos — texto, página ou URL, ordem e remoção.
   */
  const renderMenuItems = (menu: MenuDraft, items: CmsMenuItem[], depth: number): ReactNode =>
    items.map((item) => {
      const filhos = item.children ?? [];
      return (
        <div key={item.id} className="space-y-1.5">
          <div
            className="flex flex-wrap items-end gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-2.5 py-2"
            data-testid={depth === 0 ? "cms-menu-item" : "cms-menu-subitem"}
          >
            {depth > 0 && (
              <span className="self-center rounded-full border border-white/10 px-2 py-0.5 text-[10.5px] text-muted-foreground">
                {depth === 1 ? "Subitem" : "Sub-subitem"}
              </span>
            )}
            <TextInput label="Texto" value={item.label} onChange={(next) => mutateMenuItem(menu, item.id, (entry) => ({ ...entry, label: next }))} />
            <SelectInput
              label="Página"
              value={String(item.page_id ?? "")}
              onChange={(next) => mutateMenuItem(menu, item.id, (entry) => ({ ...entry, page_id: next || null }))}
              options={pageOptions}
              placeholder="— nenhuma —"
            />
            <TextInput
              label="…ou URL"
              value={item.href}
              onChange={(next) => mutateMenuItem(menu, item.id, (entry) => ({ ...entry, href: next }))}
              placeholder="/site/blog"
            />
            <div className="flex items-center gap-1 pb-1">
              <IconAction title="Subir" onClick={() => patchMenuItems(menu.id, moveMenuItem(menu.items, item.id, -1))}>
                <ArrowUp size={12} />
              </IconAction>
              <IconAction title="Descer" onClick={() => patchMenuItems(menu.id, moveMenuItem(menu.items, item.id, 1))}>
                <ArrowDown size={12} />
              </IconAction>
              {depth < MENU_MAX_DEPTH && (
                <IconAction
                  title="Acrescentar subitem"
                  onClick={() => mutateMenuItem(menu, item.id, (entry) => ({ ...entry, children: [...(entry.children ?? []), newMenuItem()] }))}
                >
                  <CornerDownRight size={12} />
                </IconAction>
              )}
              <IconAction title="Remover" danger onClick={() => patchMenuItems(menu.id, removeMenuItem(menu.items, item.id))}>
                <Trash2 size={12} />
              </IconAction>
            </div>
          </div>
          {filhos.length > 0 && (
            <div className="ml-3 space-y-1.5 border-l border-white/10 pl-2.5">{renderMenuItems(menu, filhos, depth + 1)}</div>
          )}
        </div>
      );
    });

  const set = <K extends keyof CmsSettings>(key: K, value: CmsSettings[K]) => setSettings((current) => (current ? { ...current, [key]: value } : current));

  if (loading || !settings) {
    return (
      <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar a aparência…
      </p>
    );
  }

  const pageOptions = pages.map((page) => ({ value: page.id, label: `${page.title} — ${page.path ? `/${page.path}` : "raiz do site"}` }));

  return (
    <div className="space-y-3">
      <PanelHeader title="Aparência" hint="Nome, descrição, tema, cor de realce, SEO, partilha, menus e rodapé do site público.">
        <Button size="sm" variant="secondary" icon={<ExternalLink size={13} />} onClick={() => openExternal(cms.cmsPublicUrl("/"))}>
          Abrir o site
        </Button>
        <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void saveSettings()}>
          Guardar definições
        </Button>
      </PanelHeader>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Identidade" />
          <div className="grid gap-2 sm:grid-cols-2">
            <TextInput label="Nome do site" value={settings.site_name} onChange={(next) => set("site_name", next)} />
            <TextInput label="Frase de topo" value={settings.tagline} onChange={(next) => set("tagline", next)} />
            <TextArea label="Descrição" value={settings.description} onChange={(next) => set("description", next)} rows={3} wide />
            <TextInput label="Endereço base (URLs absolutos)" value={settings.base_url} onChange={(next) => set("base_url", next)} wide hint="Ex.: https://site.exemplo.pt — usado nas canónicas, RSS, sitemap e partilhas." />
            <TextInput label="Idioma" value={settings.language} onChange={(next) => set("language", next)} />
            <TextInput label="Texto do rodapé" value={settings.footer_text} onChange={(next) => set("footer_text", next)} />
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Aparência e estrutura" />
          <div className="grid gap-2 sm:grid-cols-2">
            <SelectInput
              label="Tema"
              value={settings.theme}
              onChange={(next) => set("theme", next)}
              options={[
                { value: "claro", label: "Claro" },
                { value: "escuro", label: "Escuro" },
              ]}
            />
            <TextInput label="Cor de realce" value={settings.accent} onChange={(next) => set("accent", next)} placeholder="#0ea5a4" />
            <SelectInput
              label="Cantos"
              value={String(settings.radius)}
              onChange={(next) => set("radius", Number(next))}
              options={[0, 6, 10, 14, 18, 24].map((value) => ({ value: String(value), label: `${value} px` }))}
            />
            <SelectInput
              label="Artigos por página"
              value={String(settings.posts_per_page)}
              onChange={(next) => set("posts_per_page", Number(next))}
              options={[6, 9, 12, 18, 24].map((value) => ({ value: String(value), label: String(value) }))}
            />
            <SelectInput label="Página inicial" value={settings.home_page_id} onChange={(next) => set("home_page_id", next)} options={pageOptions} placeholder="— automática —" />
            <SelectInput label="Página do blog" value={settings.blog_page_id} onChange={(next) => set("blog_page_id", next)} options={pageOptions} placeholder="— índice gerado —" />
            <MediaPicker label="Logótipo" value={String(settings.logo_id ?? "")} onChange={(next) => set("logo_id", next || null)} media={ctx.catalogue.media_index} />
            <MediaPicker label="Favicon" value={String(settings.favicon_id ?? "")} onChange={(next) => set("favicon_id", next || null)} media={ctx.catalogue.media_index} />
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Motores de busca" hint="Por omissão, cada página usa o seu próprio SEO." />
          <div className="grid gap-2 sm:grid-cols-2">
            <TextInput label="Título (SEO)" value={String(settings.seo?.title ?? "")} onChange={(next) => set("seo", { ...settings.seo, title: next })} />
            <TextInput label="Palavras-chave" value={(settings.seo?.keywords ?? []).join(", ")} onChange={(next) => set("seo", { ...settings.seo, keywords: next.split(",").map((item) => item.trim()).filter(Boolean) })} />
            <TextArea label="Descrição" value={String(settings.seo?.description ?? "")} onChange={(next) => set("seo", { ...settings.seo, description: next })} rows={2} wide />
            <MediaPicker label="Imagem de partilha" value={String(settings.seo?.image_id ?? "")} onChange={(next) => set("seo", { ...settings.seo, image_id: next || null })} media={ctx.catalogue.media_index} />
            <TextInput label="Robots" value={settings.robots} onChange={(next) => set("robots", next)} />
            <TextInput label="Analytics (Google)" value={settings.analytics_id} onChange={(next) => set("analytics_id", next)} placeholder="G-XXXXXXX" />
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title="Ligações" hint="Endereços que aparecem no cabeçalho e no rodapé do site. Vazio = escondido." />
          <div className="grid gap-2 sm:grid-cols-2">
            {ctx.catalogue.redes_partilha.map((rede) => (
              <TextInput
                key={rede.id}
                label={rede.label}
                value={String(settings.social?.[rede.id] ?? "")}
                onChange={(next) => set("social", { ...settings.social, [rede.id]: next })}
                placeholder={rede.id === "email" ? "geral@exemplo.pt" : rede.perfil}
              />
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3 lg:col-span-2">
          <PanelHeader
            title="Partilha e favoritos"
            hint="Redes do menu «Partilhar» nos artigos e nos cartões do blog, e fila de redes no cabeçalho do site."
          >
            {isAdmin ? (
              <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void saveSettings()}>
                Guardar definições
              </Button>
            ) : (
              <span className="rounded-full border border-white/12 bg-white/[0.06] px-2 py-0.5 text-[10.5px] text-muted-foreground">
                só administradores
              </span>
            )}
          </PanelHeader>
          {!isAdmin && (
            <Notice>
              As redes de partilha, os modelos de configuração e a fila do cabeçalho são definidos por um administrador.
              O que está aplicado continua a valer no site.
            </Notice>
          )}
          <fieldset disabled={!isAdmin} className="mt-2 space-y-3 disabled:opacity-60">
            <div>
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Redes no menu de partilha</p>
              <div className="flex flex-wrap gap-1.5" data-testid="cms-partilha-redes">
                {redesDoMenu.map((rede) => {
                  const ativa = redesEscolhidas.has(rede.id);
                  return (
                    <button
                      key={rede.id}
                      type="button"
                      aria-pressed={ativa}
                      onClick={() => alternarRede(rede.id)}
                      title={rede.tipo === "copiar" ? "Copia a ligação e abre a rede" : `Partilhar no ${rede.label}`}
                      className={
                        ativa
                          ? "rounded-full border border-teal-300/60 bg-teal-400/15 px-2.5 py-1 text-[11.5px] font-medium text-teal-100"
                          : "rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] text-muted-foreground hover:border-white/25"
                      }
                    >
                      {rede.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-[10.5px] text-muted-foreground/70">
                TikTok, Instagram e YouTube não têm ligação de partilha: o botão copia a ligação do artigo e abre a rede.
                «Copiar ligação» e «Partilhar…» aparecem sempre.
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <Toggle
                checked={partilha.cartoes}
                onChange={(next) => patchPartilha({ cartoes: next })}
                label="Ações nos cartões do blog"
                hint="Estrela e partilha em cada artigo da lista."
              />
              <Toggle
                checked={partilha.cabecalho}
                onChange={(next) => patchPartilha({ cabecalho: next })}
                label="Barra no topo do blog"
                hint="Partilhar e guardar o índice do blog."
              />
              <Toggle
                checked={partilha.guardar}
                onChange={(next) => patchPartilha({ guardar: next })}
                label="Botão «Guardar» (favoritos)"
                hint="A estrela que guarda no navegador."
              />
              <Toggle
                checked={partilha.redes_cabecalho}
                onChange={(next) => patchPartilha({ redes_cabecalho: next })}
                label="Redes no cabeçalho do site"
                hint="Fila «Redes» com os endereços preenchidos em Ligações."
              />
            </div>

            <div className="rounded-lg border border-white/8 bg-white/[0.02] p-2.5">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Modelos de configuração
                {partilha.modelo && (
                  <span className="ml-2 rounded-full border border-teal-300/40 bg-teal-400/10 px-2 py-0.5 text-[10px] normal-case text-teal-100">
                    em vigor: {modelos.find((item) => item.id === partilha.modelo)?.name ?? partilha.modelo}
                  </span>
                )}
              </p>
              <ul className="mt-1.5 space-y-1">
                {modelos.map((modelo) => (
                  <li
                    key={modelo.id}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-2 py-1.5"
                  >
                    <span className="text-[12px] font-medium text-foreground">{modelo.name}</span>
                    {modelo.builtin && (
                      <span className="rounded-full border border-white/12 bg-white/[0.06] px-2 py-0.5 text-[10px] text-muted-foreground">
                        de origem
                      </span>
                    )}
                    <span className="min-w-0 flex-1 text-[11px] text-muted-foreground">{modelo.description}</span>
                    <span className="text-[10.5px] text-muted-foreground/70">
                      {(modelo.partilha?.redes ?? []).length} rede(s)
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={modeloBusy === modelo.id}
                      onClick={() => void aplicarModelo(modelo)}
                    >
                      Aplicar
                    </Button>
                    {isAdmin && !modelo.builtin && (
                      <IconAction title="Apagar modelo" danger onClick={() => void apagarModelo(modelo)}>
                        <Trash2 size={12} />
                      </IconAction>
                    )}
                  </li>
                ))}
              </ul>
              {isAdmin && (
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <TextInput
                    label="Guardar a configuração atual como modelo"
                    value={novoModelo}
                    onChange={setNovoModelo}
                    placeholder="Ex.: Campanha de outono"
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Plus size={12} />}
                    loading={modeloBusy === "novo"}
                    disabled={!novoModelo.trim()}
                    onClick={() => void criarModelo()}
                  >
                    Criar modelo
                  </Button>
                </div>
              )}
            </div>
          </fieldset>
        </div>
      </div>

      {menus.map((menu) => {
        const currentTheme = menuThemes.find((entry) => entry.id === (menu.menu_theme || "pastilhas"));
        const templateOptions = currentTheme?.templates ?? [{ id: "padrao", label: "Padrão" }];
        return (
        <div key={menu.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader
            title={menu.name}
            hint={
              menu.location === "header"
                ? "Menu do cabeçalho do site. Um item com subitens abre-os por baixo (no telemóvel, indentados)."
                : "Menu do rodapé do site. Os subitens aparecem ao lado do item que os abre."
            }
          >
            <div className="flex flex-wrap items-end gap-2">
              <SelectInput
                label="Tema do menu"
                value={menu.menu_theme || "pastilhas"}
                onChange={(next) => patchMenuTheme(menu, next)}
                options={menuThemes.map((entry) => ({ value: entry.id, label: entry.label }))}
              />
              <SelectInput
                label="Variação"
                value={menu.menu_template || "padrao"}
                onChange={(next) => patchMenuTemplate(menu, next)}
                options={templateOptions.map((entry) => ({ value: entry.id, label: entry.label }))}
              />
            </div>
            <Button size="sm" variant="ghost" onClick={() => {
              const items: CmsMenuItem[] = [
                ...pages
                  .slice(0, 8)
                  .map((page) => ({ id: `mi_${Math.random().toString(36).slice(2, 8)}`, label: page.title, href: "", page_id: page.id, new_tab: false })),
                { id: `mi_${Math.random().toString(36).slice(2, 8)}`, label: "Blog", href: "/site/blog", page_id: null, new_tab: false },
              ];
              patchMenuItems(menu.id, items);
            }}>
              Gerar das páginas
            </Button>
            <Button size="sm" variant="primary" icon={<Save size={13} />} loading={menuBusy === menu.id} onClick={() => void saveMenu(menu)}>
              Guardar menu
            </Button>
          </PanelHeader>

          <div className="space-y-1.5">
            {menu.items.length === 0 && <p className="text-[12px] text-muted-foreground">Menu vazio. Acrescente itens ou gere a partir das páginas.</p>}
            {renderMenuItems(menu, menu.items, 0)}
            <Button size="sm" variant="secondary" icon={<Plus size={12} />} onClick={() => patchMenuItems(menu.id, [...menu.items, newMenuItem()])}>
              Acrescentar item
            </Button>
          </div>
        </div>
      );
      })}

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <PanelHeader title="Ficheiros do site" hint="Ficheiros gerados automaticamente a partir do conteúdo publicado." />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => openExternal(cms.cmsPublicUrl("/rss.xml"))}>
            RSS
          </Button>
          <Button size="sm" variant="secondary" onClick={() => openExternal(cms.cmsPublicUrl("/sitemap.xml"))}>
            Sitemap
          </Button>
          <Button size="sm" variant="secondary" onClick={() => openExternal(cms.cmsPublicUrl("/robots.txt"))}>
            robots.txt
          </Button>
        </div>
      </div>
    </div>
  );
}
