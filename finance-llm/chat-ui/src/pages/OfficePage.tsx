/**
 * Office IQ OS — leitura e escrita de conteúdos.
 *
 * A aplicação onde o trabalho fica escrito: documentos em **Markdown** (notas,
 * dossiês, relatórios, atas, páginas) numa estante com pastas e etiquetas,
 * pesquisa, duplicação, exportação (.md/.html) e leitura com tipografia própria.
 *
 * Os **dossiês 360** guardados entram aqui como documentos editáveis: o dossiê
 * continua vivo na Pesquisa 360 e o documento é a sua versão de trabalho — a
 * origem fica registada e uma nova importação atualiza o mesmo documento.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Download,
  FileText,
  Folder,
  FolderPlus,
  Layers,
  Loader2,
  Pin,
  Plus,
  Printer,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
  Copy,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import { MarkdownEditor, type EditorMode } from "../components/office/MarkdownEditor";
import {
  deleteOfficeDocument,
  duplicateOfficeDocument,
  getOfficeDocument,
  listOfficeAvailableDossiers,
  listOfficeDocuments,
  OFFICE_OPEN_KEY,
  OFFICE_TEMPLATES,
  officeDocumentFromDossier,
  officeExportUrl,
  patchOfficeDocument,
  saveOfficeDocument,
  saveOfficeFolder,
  type OfficeDocument,
  type OfficeFolder,
  type OfficeListPayload,
  type OfficeStats,
} from "../officeApi";

export type OfficeSection = "documentos" | "dossies";

export const OFFICE_SECTIONS: { id: OfficeSection; label: string; icon: React.ReactNode }[] = [
  { id: "documentos", label: "Documentos", icon: <FileText size={14} /> },
  { id: "dossies", label: "Dossiês 360", icon: <Layers size={14} /> },
];

export const OFFICE_SECTION_VIEWS: Record<OfficeSection, string> = {
  documentos: "office",
  dossies: "office-dossies",
};

export function officeSectionForView(view: string): OfficeSection | null {
  const entry = (Object.entries(OFFICE_SECTION_VIEWS) as [OfficeSection, string][]).find(([, id]) => id === view);
  return entry ? entry[0] : null;
}

const numberFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 });
const AUTOSAVE_MS = 1600;

function timeAgo(value?: string | null): string {
  if (!value) return "—";
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return String(value).slice(0, 16).replace("T", " ");
  const minutes = Math.round((Date.now() - stamp) / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  return new Date(stamp).toLocaleDateString("pt-PT");
}

const KIND_STYLE: Record<string, string> = {
  nota: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  dossier: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  relatorio: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  ata: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  pagina: "border-white/10 bg-white/5 text-slate-300",
};

export default function OfficePage({
  section,
  onSectionChange,
  initialDocumentId,
}: {
  section?: OfficeSection;
  onSectionChange?: (section: OfficeSection) => void;
  initialDocumentId?: string | null;
} = {}) {
  const { user } = useAuth();
  const [list, setList] = useState<OfficeListPayload | null>(null);
  const [stats, setStats] = useState<OfficeStats | null>(null);
  const [document, setDocument] = useState<OfficeDocument | null>(null);
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [mode, setMode] = useState<EditorMode>("split");
  const [query, setQuery] = useState("");
  const [folderFilter, setFolderFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [current, setCurrent] = useState<OfficeSection>(section ?? "documentos");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<"novo" | "guardar" | "importar" | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [newForm, setNewForm] = useState({ title: "", template: "nota", folder_id: "", tags: "" });
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderForm, setFolderForm] = useState({ name: "", color: "56,189,248" });
  const [dossiers, setDossiers] = useState<{ id: string; title: string; term?: string; items?: number | null; document_id?: string | null; saved_at?: string | null }[]>([]);
  const editorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (section) setCurrent(section);
  }, [section]);

  const goTo = useCallback(
    (next: OfficeSection) => {
      setCurrent(next);
      onSectionChange?.(next);
    },
    [onSectionChange],
  );

  /* ------------------------------------------------------------ carregar */

  const refreshList = useCallback(async () => {
    try {
      const payload = await listOfficeDocuments({
        folderId: folderFilter || undefined,
        q: query || undefined,
        kind: kindFilter || undefined,
      });
      setList(payload);
      setStats(payload.stats);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível ler os documentos.");
    }
  }, [folderFilter, kindFilter, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refreshList(), query ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [refreshList, query]);

  const openDocument = useCallback(async (id: string) => {
    try {
      const payload = await getOfficeDocument(id);
      setDocument(payload.document);
      setDraft(payload.document.markdown ?? "");
      setTitle(payload.document.title ?? "");
      setDirty(false);
      setSavedAt(payload.document.updated_at ?? null);
      goTo("documentos");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível abrir o documento.");
    }
  }, [goTo]);

  /* Abre o documento que outra aplicação mandou abrir (ex.: dossiê vindo da 360). */
  useEffect(() => {
    const requested = initialDocumentId ?? (typeof window !== "undefined" ? window.localStorage.getItem(OFFICE_OPEN_KEY) : null);
    if (!requested) return;
    if (typeof window !== "undefined") window.localStorage.removeItem(OFFICE_OPEN_KEY);
    void openDocument(requested);
  }, [initialDocumentId, openDocument]);

  /* ------------------------------------------------------------- guardar */

  const persist = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!document) return;
      if (!user) {
        setError("Entrar na plataforma para guardar documentos.");
        return;
      }
      setSaving(true);
      try {
        const payload = await saveOfficeDocument({
          id: document.id,
          title: title || document.title,
          markdown: draft,
          kind: document.kind,
          folder_id: document.folder_id ?? null,
          tags: document.tags,
          pinned: document.pinned,
        });
        setDocument(payload.document);
        setSavedAt(payload.document.updated_at ?? null);
        setDirty(false);
        if (!options.silent) setNotice("Documento guardado.");
        void refreshList();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível guardar.");
      } finally {
        setSaving(false);
      }
    },
    [dirty, document, draft, refreshList, title, user],
  );

  /* Gravação automática enquanto se escreve. */
  useEffect(() => {
    if (!dirty || !document) return;
    const timer = window.setTimeout(() => void persist({ silent: true }), AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [dirty, document, draft, persist]);

  /* Ctrl/Cmd+S força a gravação imediata. */
  useEffect(() => {
    const node = editorRef.current;
    if (!node) return;
    const onSave = () => void persist();
    node.addEventListener("office-save", onSave as EventListener);
    return () => node.removeEventListener("office-save", onSave as EventListener);
  }, [persist]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /* --------------------------------------------------------------- ações */

  const createDocument = useCallback(async () => {
    if (!user) {
      setError("Entrar na plataforma para criar documentos.");
      return;
    }
    if (!newForm.title.trim()) {
      setError("O documento precisa de um título.");
      return;
    }
    setBusy("novo");
    try {
      const payload = await saveOfficeDocument({
        title: newForm.title,
        kind: newForm.template,
        template: newForm.template,
        folder_id: newForm.folder_id || null,
        tags: newForm.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      setNewOpen(false);
      setNewForm({ title: "", template: "nota", folder_id: "", tags: "" });
      await refreshList();
      await openDocument(payload.document.id);
      setNotice("Documento criado.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível criar o documento.");
    } finally {
      setBusy(null);
    }
  }, [newForm, openDocument, refreshList, user]);

  const createFolder = useCallback(async () => {
    if (!user) {
      setError("Entrar na plataforma para criar pastas.");
      return;
    }
    if (!folderForm.name.trim()) {
      setError("A pasta precisa de um nome.");
      return;
    }
    try {
      await saveOfficeFolder({ name: folderForm.name, color: folderForm.color });
      setFolderForm({ name: "", color: "56,189,248" });
      setFolderOpen(false);
      await refreshList();
      setNotice("Pasta criada.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível criar a pasta.");
    }
  }, [folderForm, refreshList, user]);

  const removeDocument = useCallback(
    async (id: string) => {
      try {
        await deleteOfficeDocument(id);
        if (document?.id === id) {
          setDocument(null);
          setDraft("");
          setTitle("");
        }
        await refreshList();
        setNotice("Documento apagado.");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível apagar.");
      }
    },
    [document, refreshList],
  );

  const duplicate = useCallback(
    async (id: string) => {
      try {
        const payload = await duplicateOfficeDocument(id);
        await refreshList();
        await openDocument(payload.document.id);
        setNotice("Documento duplicado.");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível duplicar.");
      }
    },
    [openDocument, refreshList],
  );

  const togglePin = useCallback(
    async (id: string, pinned: boolean) => {
      try {
        await patchOfficeDocument(id, { pinned: !pinned });
        await refreshList();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível fixar.");
      }
    },
    [refreshList],
  );

  const moveToFolder = useCallback(
    async (id: string, folderId: string) => {
      try {
        await patchOfficeDocument(id, { folder_id: folderId || null });
        if (document?.id === id) setDocument((current) => (current ? { ...current, folder_id: folderId || null } : current));
        await refreshList();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível mover.");
      }
    },
    [document, refreshList],
  );

  const loadDossiers = useCallback(async () => {
    try {
      const payload = await listOfficeAvailableDossiers(60);
      setDossiers(payload.items as typeof dossiers);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível ler os dossiês.");
    }
  }, []);

  useEffect(() => {
    if (current === "dossies") void loadDossiers();
  }, [current, loadDossiers]);

  const importDossier = useCallback(
    async (dossierId: string, createNew = false) => {
      if (!user) {
        setError("Entrar na plataforma para trazer dossiês.");
        return;
      }
      setBusy("importar");
      try {
        const payload = await officeDocumentFromDossier(dossierId, { createNew });
        await refreshList();
        await openDocument(payload.document.id);
        setNotice(`«${payload.dossier.title}» ${createNew ? "copiado" : "aberto"} no Office.`);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível trazer o dossiê.");
      } finally {
        setBusy(null);
      }
    },
    [openDocument, refreshList, user],
  );

  const folders: OfficeFolder[] = list?.folders ?? [];
  const documents = list?.items ?? [];
  const currentFolder = folders.find((folder) => folder.id === document?.folder_id) ?? null;

  const outline = useMemo(() => {
    if (!draft) return [];
    return draft
      .split("\n")
      .filter((line) => /^#{1,3}\s+/.test(line))
      .map((line) => {
        const level = line.match(/^#+/)?.[0].length ?? 1;
        return { level, text: line.replace(/^#+\s+/, "") };
      })
      .slice(0, 14);
  }, [draft]);

  return (
    <div className="mx-auto flex h-full w-full max-w-[1500px] flex-col px-4 pb-8 pt-6 sm:px-6" ref={editorRef}>
      <header className="flex flex-wrap items-start gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-teal-200 via-sky-500 to-indigo-700 text-white shadow-lg shadow-sky-500/25">
          <BookOpen size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">Office IQ OS</h1>
          <p className="text-sm text-muted-foreground">
            Ler e escrever conteúdos em Markdown — notas, relatórios, atas e os dossiês da Pesquisa 360, com pastas,
            pesquisa e exportação.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] text-slate-300">
            {stats ? `${numberFormat.format(stats.documents)} documentos · ${numberFormat.format(stats.words)} palavras` : "…"}
          </span>
          <button
            type="button"
            onClick={() => setFolderOpen((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10"
          >
            <FolderPlus size={13} /> Pasta
          </button>
          <button
            type="button"
            onClick={() => setNewOpen((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-2 text-xs font-medium text-white shadow-lg shadow-indigo-500/25 transition hover:brightness-110"
          >
            <Plus size={13} /> Novo documento
          </button>
        </div>
      </header>

      <nav className="mt-4 flex flex-wrap gap-1 rounded-2xl border border-white/10 bg-white/5 p-1" aria-label="Secções do Office">
        {OFFICE_SECTIONS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => goTo(entry.id)}
            aria-current={current === entry.id ? "page" : undefined}
            className={[
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[12px] transition focus-visible:ring-2 focus-visible:ring-sky-400",
              current === entry.id ? "bg-white/10 font-medium text-foreground" : "text-muted-foreground hover:bg-white/5",
            ].join(" ")}
          >
            {entry.icon} {entry.label}
          </button>
        ))}
      </nav>

      {error ? (
        <div className="mt-3 flex items-center gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} /> {error}
          <button type="button" onClick={() => setError(null)} className="ml-auto rounded-lg px-2 py-0.5 hover:bg-white/10">
            <X size={12} />
          </button>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-3 flex items-center gap-2 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-100">
          <Check size={14} /> {notice}
        </div>
      ) : null}

      {/* formulários */}
      {newOpen ? (
        <div className="glass-card mt-3 rounded-2xl p-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <label className="text-[11px] text-muted-foreground sm:col-span-2">
              Título
              <input
                value={newForm.title}
                onChange={(event) => setNewForm((current) => ({ ...current, title: event.target.value }))}
                placeholder="Relatório de mercado — setembro"
                className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
              />
            </label>
            <label className="text-[11px] text-muted-foreground">
              Modelo
              <select
                value={newForm.template}
                onChange={(event) => setNewForm((current) => ({ ...current, template: event.target.value }))}
                className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none"
              >
                {OFFICE_TEMPLATES.map((template) => (
                  <option key={template.id} value={template.id} className="bg-[#0b1a24]">
                    {template.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[11px] text-muted-foreground">
              Pasta
              <select
                value={newForm.folder_id}
                onChange={(event) => setNewForm((current) => ({ ...current, folder_id: event.target.value }))}
                className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none"
              >
                <option value="" className="bg-[#0b1a24]">
                  Sem pasta
                </option>
                {folders.map((folder) => (
                  <option key={folder.id} value={folder.id} className="bg-[#0b1a24]">
                    {folder.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[11px] text-muted-foreground sm:col-span-2">
              Etiquetas
              <input
                value={newForm.tags}
                onChange={(event) => setNewForm((current) => ({ ...current, tags: event.target.value }))}
                placeholder="mercado, setembro"
                className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
              />
            </label>
            <div className="flex items-end gap-2 sm:col-span-2">
              <button
                type="button"
                onClick={() => void createDocument()}
                disabled={busy === "novo"}
                className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-2 text-[11.5px] font-medium text-white transition hover:brightness-110 disabled:opacity-60"
              >
                {busy === "novo" ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Criar
              </button>
              <p className="text-[10.5px] text-muted-foreground">
                {OFFICE_TEMPLATES.find((template) => template.id === newForm.template)?.hint}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {folderOpen ? (
        <div className="glass-card mt-3 flex flex-wrap items-end gap-2 rounded-2xl p-3">
          <label className="text-[11px] text-muted-foreground">
            Nome da pasta
            <input
              value={folderForm.name}
              onChange={(event) => setFolderForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Mercados"
              className="mt-1 h-9 w-56 rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
            />
          </label>
          <div className="flex items-center gap-1.5">
            {["56,189,248", "16,185,129", "245,158,11", "244,63,94", "167,139,250"].map((color) => (
              <button
                key={color}
                type="button"
                onClick={() => setFolderForm((current) => ({ ...current, color }))}
                className={`h-6 w-6 rounded-full border-2 transition ${folderForm.color === color ? "border-white" : "border-transparent"}`}
                style={{ background: `rgb(${color})` }}
                aria-label={`Cor ${color}`}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={() => void createFolder()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-2 text-[11.5px] font-medium text-white transition hover:brightness-110"
          >
            <FolderPlus size={12} /> Criar pasta
          </button>
        </div>
      ) : null}

      {/* corpo */}
      <div className="mt-4 grid min-h-0 flex-1 gap-4 lg:grid-cols-[300px_1fr]">
        {/* estante */}
        <aside className="flex min-h-0 flex-col gap-3">
          <div className="glass-card rounded-2xl p-2.5">
            <div className="relative">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Pesquisar documentos…"
                className="h-9 w-full rounded-xl border border-white/10 bg-white/5 pl-8 pr-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
                aria-label="Pesquisar documentos"
              />
              <Search size={13} className="pointer-events-none absolute left-2.5 top-3 text-muted-foreground" />
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <button
                type="button"
                onClick={() => setFolderFilter("")}
                className={[
                  "rounded-full border px-2 py-0.5 text-[10.5px] transition",
                  folderFilter === "" ? "border-sky-300/40 bg-sky-400/15 text-sky-100" : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
                ].join(" ")}
              >
                Tudo
              </button>
              {folders.map((folder) => (
                <button
                  key={folder.id}
                  type="button"
                  onClick={() => setFolderFilter(folder.id === folderFilter ? "" : folder.id)}
                  className={[
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] transition",
                    folderFilter === folder.id ? "border-sky-300/40 bg-sky-400/15 text-sky-100" : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
                  ].join(" ")}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: `rgb(${folder.color ?? "148,163,184"})` }} />
                  {folder.name} <span className="text-muted-foreground">{folder.documents ?? 0}</span>
                </button>
              ))}
              <select
                value={kindFilter}
                onChange={(event) => setKindFilter(event.target.value)}
                className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-slate-300 outline-none"
                aria-label="Filtrar por tipo"
              >
                <option value="" className="bg-[#0b1a24]">
                  Todos os tipos
                </option>
                {(list?.kinds ?? []).map((kind) => (
                  <option key={kind.id} value={kind.id} className="bg-[#0b1a24]">
                    {kind.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="glass-card min-h-0 flex-1 overflow-auto rounded-2xl p-2">
            {documents.length ? (
              <ul className="space-y-1">
                {documents.map((entry) => (
                  <li key={entry.id}>
                    <div
                      className={[
                        "group rounded-xl border px-2.5 py-2 transition",
                        document?.id === entry.id ? "border-sky-300/40 bg-sky-400/10" : "border-transparent hover:border-white/10 hover:bg-white/5",
                      ].join(" ")}
                    >
                      <button type="button" onClick={() => void openDocument(entry.id)} className="w-full text-left">
                        <div className="flex items-center gap-2">
                          {entry.pinned ? <Pin size={11} className="text-amber-300" /> : <FileText size={11} className="text-slate-400" />}
                          <span className="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{entry.title}</span>
                          <span className={`rounded-full border px-1.5 py-0.5 text-[9.5px] ${KIND_STYLE[entry.kind] ?? KIND_STYLE.nota}`}>
                            {entry.kind_label}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-[10.5px] text-muted-foreground">{entry.excerpt || "—"}</p>
                        <p className="mt-0.5 text-[10px] text-muted-foreground">
                          {entry.folder ? `${entry.folder} · ` : ""}
                          {entry.words} palavras · {timeAgo(entry.updated_at)}
                          {entry.source?.type === "dossier360" ? " · dossiê 360" : ""}
                        </p>
                      </button>
                      <div className="mt-1 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => void togglePin(entry.id, entry.pinned)}
                          title={entry.pinned ? "Desafixar" : "Fixar no topo"}
                          className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-white/10"
                        >
                          <Pin size={10} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void duplicate(entry.id)}
                          title="Duplicar"
                          className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-white/10"
                        >
                          <Copy size={10} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void removeDocument(entry.id)}
                          title="Apagar"
                          className="rounded-md border border-rose-400/25 bg-rose-400/10 px-1.5 py-0.5 text-[10px] text-rose-100 hover:bg-rose-400/20"
                        >
                          <Trash2 size={10} />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-2 py-6 text-center text-[11.5px] text-muted-foreground">
                {query ? "Nada encontrado para esta pesquisa." : "Ainda não há documentos. Crie um ou traga um dossiê 360."}
              </p>
            )}
          </div>

          {stats ? (
            <div className="glass-card rounded-2xl p-2.5 text-[11px] text-muted-foreground">
              <p className="mb-1 text-[11.5px] font-medium text-foreground">Estante</p>
              {numberFormat.format(stats.documents)} documentos · {numberFormat.format(stats.words)} palavras · {stats.folders} pastas
              <div className="mt-1.5 flex flex-wrap gap-1">
                {stats.by_kind.map((entry) => (
                  <span key={entry.value} className={`rounded-full border px-2 py-0.5 text-[10px] ${KIND_STYLE[entry.value] ?? KIND_STYLE.nota}`}>
                    {entry.label} {entry.count}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </aside>

        {/* leitor/editor */}
        {current === "documentos" ? (
          document ? (
            <section className="glass-card flex min-h-0 flex-col rounded-2xl p-4">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={title}
                  onChange={(event) => {
                    setTitle(event.target.value);
                    setDirty(true);
                  }}
                  className="min-w-[200px] flex-1 rounded-xl border border-transparent bg-transparent px-1 py-1 text-lg font-semibold text-foreground outline-none transition hover:border-white/10 focus:border-sky-300/40"
                  aria-label="Título do documento"
                />
                <span className={`rounded-full border px-2 py-0.5 text-[10px] ${KIND_STYLE[document.kind] ?? KIND_STYLE.nota}`}>
                  {document.source?.type === "dossier360" ? "Dossiê 360" : document.kind}
                </span>
                {document.source?.type === "dossier360" ? (
                  <span className="text-[10px] text-muted-foreground">origem: {document.source.term ?? document.source.id}</span>
                ) : null}
                <span className={`text-[10.5px] ${dirty ? "text-amber-200" : "text-muted-foreground"}`}>
                  {saving ? "a guardar…" : dirty ? "alterações por guardar" : `guardado ${timeAgo(savedAt)}`}
                </span>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void persist()}
                  disabled={saving || !dirty}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-sky-400/25 bg-sky-400/10 px-3 py-1.5 text-[11.5px] text-sky-100 transition hover:bg-sky-400/20 disabled:opacity-50"
                >
                  {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Guardar
                </button>
                <label className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2 py-1.5 text-[11.5px] text-slate-200">
                  <Folder size={12} />
                  <select
                    value={document.folder_id ?? ""}
                    onChange={(event) => void moveToFolder(document.id, event.target.value)}
                    className="bg-transparent text-[11.5px] text-slate-100 outline-none"
                    aria-label="Pasta do documento"
                  >
                    <option value="" className="bg-[#0b1a24]">
                      Sem pasta
                    </option>
                    {folders.map((folder) => (
                      <option key={folder.id} value={folder.id} className="bg-[#0b1a24]">
                        {folder.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => window.open(officeExportUrl(document.id, "md"), "_blank", "noopener,noreferrer")}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11.5px] text-slate-200 transition hover:bg-white/10"
                >
                  <Download size={12} /> .md
                </button>
                <button
                  type="button"
                  onClick={() => window.open(officeExportUrl(document.id, "html"), "_blank", "noopener,noreferrer")}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11.5px] text-slate-200 transition hover:bg-white/10"
                >
                  <Printer size={12} /> imprimir (.html)
                </button>
                <button
                  type="button"
                  onClick={() => void duplicate(document.id)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11.5px] text-slate-200 transition hover:bg-white/10"
                >
                  <Copy size={12} /> duplicar
                </button>
                <span className="ml-auto text-[10.5px] text-muted-foreground">
                  {currentFolder ? `pasta ${currentFolder.name} · ` : ""}
                  {document.words} palavras · autor {document.author ?? "—"}
                </span>
              </div>

              {outline.length ? (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 border-b border-white/10 pb-2">
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Índice</span>
                  {outline.map((entry, index) => (
                    <span
                      key={`${entry.text}-${index}`}
                      className={`rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-slate-300 ${entry.level === 1 ? "font-medium text-foreground" : ""}`}
                    >
                      {entry.text}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="mt-3 flex min-h-0 flex-1 flex-col">
                <MarkdownEditor
                  value={draft}
                  onChange={(next) => {
                    setDraft(next);
                    setDirty(true);
                  }}
                  mode={mode}
                  onModeChange={setMode}
                  readOnly={!user}
                />
              </div>
            </section>
          ) : (
            <section className="glass-card grid min-h-[320px] place-items-center rounded-2xl p-6 text-center">
              <div>
                <BookOpen size={26} className="mx-auto text-sky-300" />
                <p className="mt-2 text-sm font-medium">Escolher um documento</p>
                <p className="mt-1 max-w-md text-xs text-muted-foreground">
                  Abra um documento da estante à esquerda, crie um novo (nota, relatório, ata) ou traga um dossiê da
                  Pesquisa 360 para continuar a escrever aqui.
                </p>
                <div className="mt-3 flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => setNewOpen(true)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-100 transition hover:bg-white/10"
                  >
                    <Plus size={13} /> Novo documento
                  </button>
                  <button
                    type="button"
                    onClick={() => goTo("dossies")}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-violet-400/25 bg-violet-400/10 px-3 py-2 text-xs text-violet-100 transition hover:bg-violet-400/20"
                  >
                    <Layers size={13} /> Trazer dossiê 360
                  </button>
                </div>
              </div>
            </section>
          )
        ) : (
          /* secção dos dossiês 360 */
          <section className="glass-card min-h-0 rounded-2xl p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Layers size={15} className="text-violet-300" />
              <p className="text-[13px] font-medium">Dossiês 360 guardados</p>
              <span className="text-[11px] text-muted-foreground">
                trazer para o Office cria (ou atualiza) um documento editável com a síntese, os indicadores e as fontes
              </span>
              <button
                type="button"
                onClick={() => void loadDossiers()}
                className="ml-auto inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11.5px] text-slate-200 transition hover:bg-white/10"
              >
                <RefreshCw size={12} /> atualizar
              </button>
            </div>
            {dossiers.length ? (
              <ul className="mt-3 space-y-2">
                {dossiers.map((entry) => (
                  <li key={entry.id} className="rounded-2xl border border-white/10 bg-white/[0.02] p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[12.5px] font-medium text-foreground">{entry.title}</span>
                      {entry.document_id ? <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10px] text-emerald-200">já no Office</span> : null}
                      <span className="ml-auto text-[10px] text-muted-foreground">{timeAgo(entry.saved_at)}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      tema: {entry.term ?? "—"} · {entry.items ?? 0} itens
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => void importDossier(entry.id, false)}
                        disabled={busy === "importar"}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/25 bg-violet-400/10 px-2.5 py-1 text-[10.5px] text-violet-100 transition hover:bg-violet-400/20 disabled:opacity-60"
                      >
                        {busy === "importar" ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                        {entry.document_id ? "atualizar documento" : "trazer para o Office"}
                      </button>
                      {entry.document_id ? (
                        <button
                          type="button"
                          onClick={() => void openDocument(String(entry.document_id))}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[10.5px] text-slate-100 transition hover:bg-white/10"
                        >
                          <FileText size={11} /> abrir documento
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => void importDossier(entry.id, true)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[10.5px] text-slate-100 transition hover:bg-white/10"
                      >
                        <Copy size={11} /> criar cópia
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-[11.5px] text-muted-foreground">
                Ainda não há dossiês guardados. Na Pesquisa 360, construa o «Dossiê 360» de um tema e use «Guardar
                dossiê» — depois aparece aqui, pronto a editar.
              </p>
            )}
            {folders.length ? (
              <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.02] p-2.5">
                <p className="text-[11px] text-muted-foreground">
                  Pasta de destino ao trazer um dossiê: use o seletor de pasta do documento depois de o abrir (ou o
                  formulário «Novo documento»).
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {folders.map((folder) => (
                    <span key={folder.id} className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-slate-300">
                      <Folder size={10} /> {folder.name}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        )}
      </div>
    </div>
  );
}
