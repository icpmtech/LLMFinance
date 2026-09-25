/**
 * Biblioteca do CMS — **conteúdos** reutilizáveis, **media**, **taxonomia**,
 * **modelos** e **aparência** (definições do site + menus).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
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
  formatBytes,
  timeAgo,
} from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsCategory, CmsContent, CmsMedia, CmsMenu, CmsMenuItem, CmsSettings, CmsTemplate } from "../cmsApi";
import type { CmsCtx } from "./CmsPanels";

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

export function CmsAppearancePanel({ ctx }: { ctx: CmsCtx }) {
  const [settings, setSettings] = useState<CmsSettings | null>(null);
  const [menus, setMenus] = useState<MenuDraft[]>([]);
  const [pages, setPages] = useState<{ id: string; title: string; path: string }[]>([]);
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
      const result = await cms.saveCmsMenu({ id: menu.id, name: menu.name, location: menu.location, items: menu.items });
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

  const moveItem = (menu: MenuDraft, index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= menu.items.length) return;
    const items = [...menu.items];
    [items[index], items[target]] = [items[target], items[index]];
    patchMenuItems(menu.id, items);
  };

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
      <PanelHeader title="Aparência" hint="Nome, descrição, tema, cor de realce, SEO, menus e rodapé do site público.">
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
          <PanelHeader title="Ligações" hint="Aparecem no rodapé do site." />
          <div className="grid gap-2 sm:grid-cols-2">
            {(["email", "linkedin", "x", "github"] as const).map((key) => (
              <TextInput
                key={key}
                label={key === "x" ? "X (Twitter)" : key === "email" ? "Email" : key === "linkedin" ? "LinkedIn" : "GitHub"}
                value={String(settings.social?.[key] ?? "")}
                onChange={(next) => set("social", { ...settings.social, [key]: next })}
              />
            ))}
          </div>
        </div>
      </div>

      {menus.map((menu) => (
        <div key={menu.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <PanelHeader title={menu.name} hint={menu.location === "header" ? "Menu do cabeçalho do site." : "Menu do rodapé do site."}>
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
            {menu.items.map((item, index) => (
              <div key={item.id} className="flex flex-wrap items-end gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-2.5 py-2">
                <TextInput
                  label="Texto"
                  value={item.label}
                  onChange={(next) => patchMenuItems(menu.id, menu.items.map((entry) => (entry.id === item.id ? { ...entry, label: next } : entry)))}
                />
                <SelectInput
                  label="Página"
                  value={String(item.page_id ?? "")}
                  onChange={(next) => patchMenuItems(menu.id, menu.items.map((entry) => (entry.id === item.id ? { ...entry, page_id: next || null } : entry)))}
                  options={pageOptions}
                  placeholder="— nenhuma —"
                />
                <TextInput
                  label="…ou URL"
                  value={item.href}
                  onChange={(next) => patchMenuItems(menu.id, menu.items.map((entry) => (entry.id === item.id ? { ...entry, href: next } : entry)))}
                  placeholder="/site/blog"
                />
                <div className="flex items-center gap-1 pb-1">
                  <IconAction title="Subir" onClick={() => moveItem(menu, index, -1)}>
                    <ArrowUp size={12} />
                  </IconAction>
                  <IconAction title="Descer" onClick={() => moveItem(menu, index, 1)}>
                    <ArrowDown size={12} />
                  </IconAction>
                  <IconAction title="Remover" danger onClick={() => patchMenuItems(menu.id, menu.items.filter((entry) => entry.id !== item.id))}>
                    <Trash2 size={12} />
                  </IconAction>
                </div>
              </div>
            ))}
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={12} />}
              onClick={() => patchMenuItems(menu.id, [...menu.items, { id: `mi_${Math.random().toString(36).slice(2, 8)}`, label: "", href: "", page_id: null, new_tab: false }])}
            >
              Acrescentar item
            </Button>
          </div>
        </div>
      ))}

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
