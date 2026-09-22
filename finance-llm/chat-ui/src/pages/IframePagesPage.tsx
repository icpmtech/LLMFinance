/**
 * Página de gestão de aplicações iframe.
 *
 * Permite adicionar, editar, reordenar, ativar/desativar e remover páginas
 * externas que serão incorporadas na plataforma através de iframes.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ExternalLink,
  Globe2,
  GripVertical,
  Loader2,
  Pencil,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import {
  deleteIframePage,
  getIframePages,
  IFRAME_GRADIENTS,
  IFRAME_ICON_NAMES,
  IFRAME_ICONS,
  reorderIframePages,
  saveIframePage,
  subscribeIframePages,
  type IframePageConfig,
} from "../iframePages";

interface IframePagesPageProps {
  onOpenIframe?: (view: string) => void;
}

function makeId(title: string): string {
  const base = title
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return base || `iframe-${Date.now()}`;
}

function isValidUrl(value: string): boolean {
  if (!value) return false;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function emptyForm(): IframePageConfig {
  return {
    id: "",
    title: "",
    url: "",
    icon: "Globe2",
    accent: "56,189,248",
    gradient: "from-sky-300 via-sky-500 to-sky-700",
    enabled: true,
    createdAt: new Date().toISOString(),
  };
}

function parseAccent(value: string): string {
  const cleaned = value.replace(/[^\d,]/g, "").replace(/,{2,}/g, ",");
  const parts = cleaned.split(",").filter(Boolean).map((p) => Math.max(0, Math.min(255, Number(p) || 0)));
  if (parts.length === 3) return parts.join(",");
  if (parts.length === 0) return "56,189,248";
  while (parts.length < 3) parts.push(parts[parts.length - 1] ?? 0);
  return parts.slice(0, 3).join(",");
}

export default function IframePagesPage({ onOpenIframe }: IframePagesPageProps) {
  const [pages, setPages] = useState<IframePageConfig[]>([]);
  const [editing, setEditing] = useState<IframePageConfig | null>(null);
  const [form, setForm] = useState<IframePageConfig>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPages(getIframePages());
    return subscribeIframePages(() => setPages(getIframePages()));
  }, []);

  useEffect(() => {
    if (editing) setForm({ ...editing });
    else setForm(emptyForm());
    setError(null);
    setSaved(false);
    setPreview(false);
  }, [editing]);

  const canSave = useMemo(() => {
    if (!form.title.trim() || !form.url.trim()) return false;
    return isValidUrl(form.url);
  }, [form]);

  const idForSave = useMemo(() => {
    if (editing) return editing.id;
    const base = makeId(form.title);
    if (!base) return "";
    let candidate = base;
    let counter = 1;
    while (pages.some((p) => p.id === candidate)) {
      candidate = `${base}-${counter}`;
      counter++;
    }
    return candidate;
  }, [editing, form.title, pages]);

  const handleSubmit = useCallback(() => {
    if (!form.title.trim()) {
      setError("Introduza um título para a página.");
      return;
    }
    if (!isValidUrl(form.url)) {
      setError("Introduza um URL válido (http:// ou https://).");
      return;
    }
    setBusy(true);
    const next = saveIframePage({ ...form, id: idForSave, accent: parseAccent(form.accent) });
    if (!next) {
      setError("Não foi possível guardar a página. Verifique os dados.");
      setBusy(false);
      return;
    }
    setEditing(null);
    setSaved(true);
    setError(null);
    setTimeout(() => setSaved(false), 1500);
    setBusy(false);
    if (onOpenIframe && next.enabled) onOpenIframe(`iframe:${next.id}`);
  }, [form, idForSave, onOpenIframe]);

  const handleDelete = useCallback((id: string) => {
    if (!window.confirm("Tem a certeza que pretende remover esta página iframe?")) return;
    deleteIframePage(id);
    if (editing?.id === id) setEditing(null);
  }, [editing]);

  const handleMove = useCallback((id: string, direction: "up" | "down") => {
    const idx = pages.findIndex((p) => p.id === id);
    if (idx < 0) return;
    const target = direction === "up" ? idx - 1 : idx + 1;
    if (target < 0 || target >= pages.length) return;
    const next = [...pages];
    [next[idx], next[target]] = [next[target], next[idx]];
    reorderIframePages(next.map((p) => p.id));
  }, [pages]);

  const handleToggle = useCallback((page: IframePageConfig) => {
    saveIframePage({ ...page, enabled: !page.enabled });
  }, []);

  return (
    <div className="h-full w-full overflow-auto bg-zinc-950 text-zinc-100 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold flex items-center gap-2 text-zinc-100">
              <Globe2 className="text-sky-400" size={22} />
              Páginas iframe
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              Adicione aplicações externas para incorporar na plataforma. Podem ser abertas como
              janelas ou aplicações independentes.
            </p>
          </div>
          {!editing && (
            <button
              onClick={() => setEditing(emptyForm())}
              className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition"
            >
              <Plus size={16} />
              Nova página
            </button>
          )}
        </div>

        {error && (
          <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-200 flex items-start gap-2">
            <X size={16} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-800/60 flex items-center justify-between">
                <h2 className="text-sm font-medium text-zinc-200">
                  {editing ? (editing.id ? "Editar página" : "Nova página") : "Lista de páginas"}
                </h2>
                {editing && (
                  <button
                    onClick={() => setEditing(null)}
                    className="text-xs text-zinc-400 hover:text-zinc-200"
                  >
                    Cancelar
                  </button>
                )}
              </div>

              {editing ? (
                <div className="p-4 space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-zinc-400">Título</label>
                    <input
                      type="text"
                      value={form.title}
                      onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                      placeholder="Ex: Notícias de mercado"
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-zinc-400">URL</label>
                    <input
                      type="url"
                      value={form.url}
                      onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                      placeholder="https://..."
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-zinc-400">Ícone</label>
                      <div className="grid grid-cols-6 gap-1 max-h-28 overflow-auto rounded-lg border border-zinc-700 bg-zinc-950 p-2">
                        {IFRAME_ICON_NAMES.map((name) => {
                          const Icon = IFRAME_ICONS[name];
                          return (
                            <button
                              key={name}
                              type="button"
                              title={name}
                              onClick={() => setForm((f) => ({ ...f, icon: name }))}
                              className={`flex items-center justify-center p-2 rounded-md transition ${
                                form.icon === name
                                  ? "bg-sky-600/30 text-sky-400 ring-1 ring-sky-500"
                                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                              }`}
                            >
                              <Icon size={16} />
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-zinc-400">Gradiente</label>
                      <div className="max-h-28 overflow-auto rounded-lg border border-zinc-700 bg-zinc-950 p-2 space-y-1">
                        {IFRAME_GRADIENTS.map(({ value, label }) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setForm((f) => ({ ...f, gradient: value }))}
                            className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition ${
                              form.gradient === value
                                ? "bg-zinc-800 ring-1 ring-zinc-600"
                                : "hover:bg-zinc-800/50"
                            }`}
                          >
                            <span className={`w-4 h-4 rounded-full bg-gradient-to-br ${value}`} />
                            <span className="text-zinc-300">{label}</span>
                            {form.gradient === value && <Check size={12} className="ml-auto text-sky-400" />}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-zinc-400">Cor de realce (R,G,B)</label>
                    <input
                      type="text"
                      value={form.accent}
                      onChange={(e) => setForm((f) => ({ ...f, accent: e.target.value }))}
                      placeholder="56,189,248"
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-sky-500"
                    />
                  </div>

                  <div className="flex items-center gap-2 pt-1">
                    <input
                      id="iframe-enabled"
                      type="checkbox"
                      checked={form.enabled}
                      onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                      className="rounded border-zinc-600 bg-zinc-800 text-sky-500 focus:ring-sky-500"
                    />
                    <label htmlFor="iframe-enabled" className="text-sm text-zinc-300">
                      Ativa (visível no dock e no menu)
                    </label>
                  </div>

                  <div className="flex items-center justify-between pt-2">
                    <button
                      type="button"
                      onClick={() => setPreview((p) => !p)}
                      disabled={!canSave}
                      className="text-xs inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-zinc-700 text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
                    >
                      <ExternalLink size={12} />
                      {preview ? "Ocultar pré-visualização" : "Pré-visualizar"}
                    </button>

                    <div className="flex items-center gap-2">
                      {saved && (
                        <span className="text-xs text-emerald-400 flex items-center gap-1">
                          <Check size={12} />
                          Guardado
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!canSave || busy}
                        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50 transition"
                      >
                        {busy ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        Guardar
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="divide-y divide-zinc-800/60">
                  {pages.length === 0 ? (
                    <div className="p-8 text-center text-sm text-zinc-500">
                      Nenhuma página iframe configurada.
                      <br />
                      Clique em <strong className="text-zinc-300">Nova página</strong> para começar.
                    </div>
                  ) : (
                    pages.map((page, idx) => {
                      const Icon = IFRAME_ICONS[page.icon] ?? IFRAME_ICONS.Globe2;
                      return (
                        <div
                          key={page.id}
                          className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/40 transition"
                        >
                          <GripVertical size={14} className="text-zinc-600 shrink-0" />
                          <span className={`w-7 h-7 rounded-lg flex items-center justify-center bg-gradient-to-br ${page.gradient} shrink-0`}>
                            <Icon size={15} className="text-white/90" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 text-sm text-zinc-200">
                              <span className="truncate font-medium">{page.title}</span>
                              {!page.enabled && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
                                  Inativa
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-zinc-500 truncate">{page.url}</div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              title="Mover para cima"
                              disabled={idx === 0}
                              onClick={() => handleMove(page.id, "up")}
                              className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 disabled:opacity-30"
                            >
                              <ArrowUp size={14} />
                            </button>
                            <button
                              title="Mover para baixo"
                              disabled={idx === pages.length - 1}
                              onClick={() => handleMove(page.id, "down")}
                              className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 disabled:opacity-30"
                            >
                              <ArrowDown size={14} />
                            </button>
                            <button
                              title="Editar"
                              onClick={() => setEditing(page)}
                              className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400"
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              title={page.enabled ? "Desativar" : "Ativar"}
                              onClick={() => handleToggle(page)}
                              className={`p-1.5 rounded hover:bg-zinc-800 ${page.enabled ? "text-emerald-400" : "text-zinc-500"}`}
                            >
                              <Check size={14} />
                            </button>
                            <button
                              title="Remover"
                              onClick={() => handleDelete(page.id)}
                              className="p-1.5 rounded hover:bg-red-950/40 text-red-400"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden flex flex-col h-[min(70vh,540px)]">
            <div className="px-4 py-3 border-b border-zinc-800/60">
              <h2 className="text-sm font-medium text-zinc-200">Pré-visualização</h2>
            </div>
            <div className="flex-1 bg-zinc-950">
              {preview && editing && canSave ? (
                <iframe
                  src={form.url}
                  title={form.title || "Pré-visualização"}
                  className="h-full w-full border-0"
                  referrerPolicy="strict-origin-when-cross-origin"
                  sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
                />
              ) : (
                <div className="h-full w-full flex flex-col items-center justify-center text-zinc-500 gap-3 p-6 text-center">
                  <Globe2 size={40} className="opacity-20" />
                  <p className="text-sm">
                    {editing
                      ? "Guarde ou clique em Pré-visualizar para ver a página aqui."
                      : "Selecione uma página para editar ou pré-visualizar."}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
