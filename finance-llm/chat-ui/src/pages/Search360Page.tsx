/**
 * Pesquisa 360 — o meta-modelo de analítica e exploração do IQ OS.
 *
 * Uma pergunta, todas as fontes: a plataforma (Elasticsearch + ontologia),
 * documentos e ficheiros, Wikipédia, Wikidata, Banco Mundial, dados.gov.pt,
 * OpenAlex, Crossref e a web aberta. Tudo normalizado, com o plano de pesquisa
 * à vista, e quatro formas de olhar para o mesmo assunto:
 *
 * - **Busca** — resultados federados com facetas e filtros por fonte;
 * - **Dossiê 360** — síntese com citações, indicadores e o que cada fonte deu;
 * - **Grafo** — navegação do tema para entidades, documentos e dados;
 * - **Biblioteca** — pastas por família de fonte e ficheiros com ícone próprio.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Boxes,
  Database,
  Download,
  ExternalLink,
  FileText,
  Folder,
  FolderPlus,
  Globe2,
  GraduationCap,
  Info,
  Layers,
  LineChart,
  Loader2,
  Network,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Table2,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { useAuth } from "../auth";
import { Search360Graph } from "../components/search360/Search360Graph";
import { getWindowMode } from "../layout";
import { OFFICE_OPEN_KEY, officeDocumentFromDossier } from "../officeApi";
import { estimateWorkspace, openWindow } from "../windows";
import {
  deleteSearch360Dossier,
  deleteSearch360Project,
  getSearch360Meta,
  getSearch360Topic,
  getSearch360Dossier,
  kindLabel,
  listSearch360Dossiers,
  listSearch360Projects,
  refreshSearch360Dossier,
  saveSearch360Dossier,
  saveSearch360Project,
  search360DossierExportUrl,
  searchSearch360,
  suggestSearch360,
  TOPIC_STARTERS,
  updateSearch360Dossier,
  type Search360Graph as Search360GraphData,
  type Search360GraphNode,
  type Search360Item,
  type Search360LibraryFolder,
  type Search360Meta,
  type Search360Metric,
  type Search360Project,
  type Search360SavedDossier,
  type Search360SearchResult,
  type Search360Source,
  type Search360StoredDossier,
  type Search360Topic,
} from "../search360Api";

export type Search360Section = "busca" | "dossie" | "projetos" | "grafo" | "biblioteca";

export const SEARCH360_SECTIONS: { id: Search360Section; label: string; icon: React.ReactNode }[] = [
  { id: "busca", label: "Busca federada", icon: <Search size={14} /> },
  { id: "dossie", label: "Dossiê 360", icon: <Layers size={14} /> },
  { id: "projetos", label: "Projetos e dossiês", icon: <FolderPlus size={14} /> },
  { id: "grafo", label: "Grafo de exploração", icon: <Network size={14} /> },
  { id: "biblioteca", label: "Biblioteca", icon: <Folder size={14} /> },
];

/** Contrato com `App.tsx` (sub-rotas do módulo). */
export const SEARCH360_SECTION_VIEWS: Record<Search360Section, string> = {
  busca: "search360",
  dossie: "search360-dossie",
  projetos: "search360-projetos",
  grafo: "search360-grafo",
  biblioteca: "search360-biblioteca",
};

export function search360SectionForView(view: string): Search360Section | null {
  const entry = (Object.entries(SEARCH360_SECTION_VIEWS) as [Search360Section, string][]).find(([, id]) => id === view);
  return entry ? entry[0] : null;
}

const numberFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 });
const valueFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 });

const KIND_ICON: Record<string, React.ReactNode> = {
  entity: <Boxes size={14} />,
  article: <BookOpen size={14} />,
  document: <FileText size={14} />,
  dataset: <Table2 size={14} />,
  metric: <LineChart size={14} />,
  news: <Globe2 size={14} />,
  file: <FileText size={14} />,
  topic: <Search size={14} />,
  summary: <Sparkles size={14} />,
};

const FAMILY_ICON: Record<string, React.ReactNode> = {
  internal: <Database size={14} />,
  documents: <Folder size={14} />,
  encyclopedia: <BookOpen size={14} />,
  opendata: <Table2 size={14} />,
  research: <GraduationCap size={14} />,
  web: <Globe2 size={14} />,
  ai: <Sparkles size={14} />,
};

function kindIcon(kind: string): React.ReactNode {
  return KIND_ICON[kind] ?? <FileText size={14} />;
}

/** Abre uma ligação no browser do sistema (o IQ OS não impõe um browser próprio). */
function openLink(url: string) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

/* ------------------------------------------------------------------ peças */

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
      {hint ? <p className="text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Badge({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "sky" | "emerald" | "amber" | "violet" }) {
  const tones: Record<string, string> = {
    slate: "border-white/10 bg-white/5 text-slate-300",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-100",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  };
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>{children}</span>;
}

/** Mini-série de um indicador (SVG em linha, sem dependências). */
function Sparkline({ points, height = 34 }: { points: { year: number; value: number }[]; height?: number }) {
  if (points.length < 2) return null;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 220;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((point.value - min) / span) * (height - 4) - 2;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const rising = values[values.length - 1] >= values[0];
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-9 w-full" preserveAspectRatio="none" aria-hidden="true">
      <path d={path} fill="none" stroke={rising ? "#34d399" : "#fb7185"} strokeWidth="1.6" />
    </svg>
  );
}

function ItemCard({
  entry,
  active,
  onSelect,
  onOpen,
  onUseAsTopic,
}: {
  entry: Search360Item;
  active: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onUseAsTopic: () => void;
}) {
  return (
    <div
      className={[
        "cursor-pointer rounded-2xl border p-3 transition",
        active ? "border-sky-300/40 bg-sky-400/10" : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]",
      ].join(" ")}
      onClick={onSelect}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/5 text-slate-200">
          {kindIcon(entry.kind)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-medium text-foreground">{entry.title}</span>
            <Badge tone="slate">{entry.source_label}</Badge>
            <Badge tone="violet">{kindLabel(entry.kind)}</Badge>
            {entry.date ? <Badge tone="slate">{entry.date}</Badge> : null}
            {entry.also_in?.length ? <Badge tone="sky">também em {entry.also_in.length} fonte(s)</Badge> : null}
          </div>
          {entry.subtitle ? <p className="mt-1 text-[11px] text-muted-foreground">{entry.subtitle}</p> : null}
          {entry.snippet ? <p className="mt-1 line-clamp-2 text-[11.5px] leading-relaxed text-slate-300/90">{entry.snippet}</p> : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {entry.url ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onOpen();
              }}
              title="Abrir no browser"
              className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10px] text-slate-200 transition hover:bg-white/10"
            >
              <ExternalLink size={11} /> abrir
            </button>
          ) : null}
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onUseAsTopic();
            }}
            className="inline-flex items-center gap-1 rounded-lg border border-sky-400/25 bg-sky-400/10 px-2 py-1 text-[10px] text-sky-100 transition hover:bg-sky-400/20"
            title="Investigar este item como novo tema"
          >
            <Wand2 size={11} /> investigar
          </button>
        </div>
      </div>
    </div>
  );
}

function FolderTree({ folders, onOpen }: { folders: Search360LibraryFolder[]; onOpen: (url: string) => void }) {  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <div className="space-y-2">
      {folders.map((folder) => {
        const expanded = open[folder.id] ?? true;
        return (
          <div key={folder.id} className="glass-card rounded-2xl p-3">
            <button
              type="button"
              onClick={() => setOpen((current) => ({ ...current, [folder.id]: !expanded }))}
              className="flex w-full items-center gap-2 text-left"
            >
              <span className="grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-white/5 text-slate-200">
                {FAMILY_ICON[folder.id] ?? <Folder size={14} />}
              </span>
              <span className="flex-1 text-[13px] font-medium text-foreground">{folder.label}</span>
              <span className="text-[11px] text-muted-foreground">{folder.count} ficheiros</span>
              <span className="text-[11px] text-muted-foreground">{expanded ? "▾" : "▸"}</span>
            </button>
            {expanded ? (
              <div className="mt-2 space-y-2 border-l border-white/10 pl-3">
                {folder.subfolders.map((sub) => (
                  <div key={sub.id}>
                    <p className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                      <Folder size={12} /> {sub.label} · {sub.files.length}
                    </p>
                    <ul className="mt-1 space-y-1">
                      {sub.files.map((file) => (
                        <li key={file.id} className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-[11.5px] text-slate-200 hover:bg-white/5">
                          <span className="text-slate-400">{kindIcon(file.kind)}</span>
                          <span className="min-w-0 flex-1 truncate">{file.label}</span>
                          {file.date ? <span className="shrink-0 text-[10px] text-muted-foreground">{file.date}</span> : null}
                          {file.url ? (
                            <button
                              type="button"
                              onClick={() => onOpen(String(file.url))}
                              className="shrink-0 rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-200 transition hover:bg-white/10"
                            >
                              abrir
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function MetricCard({ metric }: { metric: Search360Metric }) {
  const rising = (metric.change_pct ?? 0) >= 0;
  return (
    <div className="glass-card rounded-2xl p-3">
      <p className="text-[12px] font-medium text-foreground">{metric.label}</p>
      <p className="text-[10px] text-muted-foreground">
        {metric.indicator} · {metric.country}
      </p>
      <Sparkline points={metric.points} />
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-[15px] font-semibold">{valueFormat.format(metric.last.value)}</span>
        <span className={`text-[11px] ${rising ? "text-emerald-300" : "text-rose-300"}`}>
          {rising ? "▲" : "▼"} {valueFormat.format(Math.abs(metric.change))}
          {metric.change_pct !== null ? ` (${valueFormat.format(Math.abs(metric.change_pct))}%)` : ""}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {metric.first.year} → {metric.last.year}
        </span>
      </div>
      {metric.url ? (
        <button
          type="button"
          onClick={() => openLink(String(metric.url))}
          className="mt-1 inline-flex items-center gap-1 text-[10px] text-sky-300 hover:underline"
        >
          <ArrowUpRight size={10} /> fonte
        </button>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ página */

export default function Search360Page({
  section,
  onSectionChange,
}: {
  section?: Search360Section;
  onSectionChange?: (section: Search360Section) => void;
} = {}) {
  const { user } = useAuth();
  const [meta, setMeta] = useState<Search360Meta | null>(null);
  const [term, setTerm] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [result, setResult] = useState<Search360SearchResult | null>(null);
  const [dossier, setDossier] = useState<Search360Topic | null>(null);
  const [graphData, setGraphData] = useState<Search360GraphData | null>(null);
  const [selectedItem, setSelectedItem] = useState<Search360Item | null>(null);
  const [selectedNode, setSelectedNode] = useState<Search360GraphNode | null>(null);
  const [suggestions, setSuggestions] = useState<{ label: string; hint?: string; source?: string; value?: string }[]>([]);
  const [loading, setLoading] = useState<"busca" | "dossie" | "grafo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [current, setCurrent] = useState<Search360Section>(section ?? "busca");
  const inputRef = useRef<HTMLInputElement | null>(null);

  /* projetos e dossiês guardados */
  const [projects, setProjects] = useState<Search360Project[]>([]);
  const [savedDossiers, setSavedDossiers] = useState<Search360SavedDossier[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem("finance-llm-search360-project") ?? "";
  });
  const [savedDossierId, setSavedDossierId] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveForm, setSaveForm] = useState({ title: "", project_id: "", tags: "", notes: "" });
  const [projectForm, setProjectForm] = useState({ name: "", description: "", color: "99,102,241", tags: "" });
  const [projectFormOpen, setProjectFormOpen] = useState(false);
  const [busy, setBusy] = useState<"guardar" | "atualizar" | "projeto" | null>(null);
  const [dossierFilter, setDossierFilter] = useState<"projeto" | "todos" | "sem-projeto">("todos");

  const canSave = Boolean(user);

  useEffect(() => {
    if (section) setCurrent(section);
  }, [section]);

  const goTo = useCallback(
    (next: Search360Section) => {
      setCurrent(next);
      onSectionChange?.(next);
    },
    [onSectionChange],
  );

  /* metadados do metamodelo (arranque a quente) */
  useEffect(() => {
    getSearch360Meta()
      .then(setMeta)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /* sugestões enquanto se escreve */
  useEffect(() => {
    const clean = term.trim();
    if (clean.length < 3 || clean === submitted) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      suggestSearch360(clean, 6)
        .then((payload) => {
          if (!cancelled) setSuggestions(payload.suggestions ?? []);
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        });
    }, 320);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [term, submitted]);

  const runSearch = useCallback(
    async (value: string) => {
      const clean = value.trim();
      if (!clean) return;
      setSubmitted(clean);
      setSuggestions([]);
      setLoading("busca");
      setError(null);
      setSelectedItem(null);
      try {
        const payload = await searchSearch360({ term: clean, sources: selectedSources.length ? selectedSources : undefined, limit: 6 });
        setResult(payload);
        setGraphData(null);
        setDossier(null);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "A pesquisa falhou.");
      } finally {
        setLoading(null);
      }
    },
    [selectedSources],
  );

  const runDossier = useCallback(async () => {
    const clean = (submitted || term).trim();
    if (!clean) return;
    setLoading("dossie");
    setError(null);
    try {
      const payload = await getSearch360Topic({
        term: clean,
        sources: selectedSources.length ? selectedSources : undefined,
        limit: 6,
        synthesis: true,
      });
      setDossier(payload);
      if (!result) setResult({ ...payload, entities: [] });
      if (payload.graph) setGraphData(payload.graph);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "O dossiê falhou.");
    } finally {
      setLoading(null);
    }
  }, [result, selectedSources, submitted, term]);

  /* ------------------------------------------------- projetos e dossiês */

  const refreshSaved = useCallback(async () => {
    try {
      const [projectsPayload, dossiersPayload] = await Promise.all([
        listSearch360Projects(),
        listSearch360Dossiers({ limit: 120 }),
      ]);
      setProjects(projectsPayload.items);
      setSavedDossiers(dossiersPayload.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível ler os projetos.");
    }
  }, []);

  useEffect(() => {
    void refreshSaved();
  }, [refreshSaved]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (activeProjectId) window.localStorage.setItem("finance-llm-search360-project", activeProjectId);
    else window.localStorage.removeItem("finance-llm-search360-project");
  }, [activeProjectId]);

  const openSaveForm = useCallback(() => {
    if (!dossier) {
      setError("Construa primeiro o dossiê 360 do tema (botão «Dossiê 360»).");
      return;
    }
    if (!user) {
      setError("Entrar na plataforma para guardar dossiês.");
      return;
    }
    setSaveForm({
      title: savedDossierId ? (dossier.term ?? "") + " — dossiê 360" : `${dossier.term} — dossiê 360`,
      project_id: activeProjectId,
      tags: "",
      notes: "",
    });
    setSaveOpen(true);
  }, [activeProjectId, dossier, savedDossierId, user]);

  const submitSave = useCallback(async () => {
    if (!dossier) return;
    setBusy("guardar");
    setError(null);
    try {
      const payload = await saveSearch360Dossier({
        id: savedDossierId ?? undefined,
        title: saveForm.title || `${dossier.term} — dossiê 360`,
        term: dossier.term,
        project_id: saveForm.project_id || null,
        tags: saveForm.tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        notes: saveForm.notes || undefined,
        topic: dossier,
      });
      setSavedDossierId(payload.dossier.id);
      setSaveOpen(false);
      setNotice(`Dossiê «${payload.summary.title}» guardado${payload.summary.project_id ? " no projeto" : ""}.`);
      if (saveForm.project_id) setActiveProjectId(saveForm.project_id);
      await refreshSaved();
      goTo("projetos");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível guardar o dossiê.");
    } finally {
      setBusy(null);
    }
  }, [dossier, goTo, refreshSaved, saveForm, savedDossierId]);

  const openSavedDossier = useCallback(async (id: string) => {
    setLoading("dossie");
    setError(null);
    try {
      const stored: Search360StoredDossier = await getSearch360Dossier(id);
      const snapshot = stored.snapshot;
      if (!snapshot) throw new Error("Este dossiê não tem retrato guardado.");
      setTerm(snapshot.term ?? "");
      setSubmitted(snapshot.term ?? "");
      setResult({ ...snapshot, entities: [], stats: snapshot.stats, term: snapshot.term });
      setDossier(snapshot);
      setGraphData(snapshot.graph ?? null);
      setSavedDossierId(id);
      setSelectedItem(null);
      setSelectedNode(null);
      if (stored.project_id) setActiveProjectId(stored.project_id);
      setNotice(`Dossiê «${stored.title}» aberto (guardado em ${String(stored.saved_at ?? stored.created_at ?? "").slice(0, 16).replace("T", " ")}).`);
      goTo("dossie");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível abrir o dossiê.");
    } finally {
      setLoading(null);
    }
  }, [goTo]);

  const refreshSavedDossier = useCallback(
    async (id: string) => {
      setBusy("atualizar");
      setError(null);
      try {
        const payload = await refreshSearch360Dossier(id);
        setNotice(`«${payload.summary.title}» atualizado com a pesquisa de agora.`);
        await refreshSaved();
        if (savedDossierId === id) await openSavedDossier(id);
        else {
          const stored = await getSearch360Dossier(id);
          setTerm(stored.snapshot?.term ?? "");
          setSubmitted(stored.snapshot?.term ?? "");
          setResult({ ...stored.snapshot, entities: [] });
          setDossier(stored.snapshot);
          setGraphData(stored.snapshot?.graph ?? null);
          setSavedDossierId(id);
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o dossiê.");
      } finally {
        setBusy(null);
      }
    },
    [openSavedDossier, refreshSaved, savedDossierId],
  );

  const removeDossier = useCallback(
    async (id: string) => {
      try {
        await deleteSearch360Dossier(id);
        if (savedDossierId === id) setSavedDossierId(null);
        setNotice("Dossiê apagado.");
        await refreshSaved();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível apagar o dossiê.");
      }
    },
    [refreshSaved, savedDossierId],
  );

  const moveDossier = useCallback(
    async (id: string, projectId: string) => {
      try {
        await updateSearch360Dossier(id, { project_id: projectId || null });
        setNotice(projectId ? "Dossiê movido para o projeto." : "Dossiê sem projeto.");
        await refreshSaved();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível mover o dossiê.");
      }
    },
    [refreshSaved],
  );

  const submitProject = useCallback(async () => {
    if (!projectForm.name.trim()) {
      setError("O projeto precisa de um nome.");
      return;
    }
    if (!user) {
      setError("Entrar na plataforma para criar projetos.");
      return;
    }
    setBusy("projeto");
    setError(null);
    try {
      const payload = await saveSearch360Project({
        name: projectForm.name,
        description: projectForm.description || undefined,
        color: projectForm.color,
        tags: projectForm.tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      setActiveProjectId(payload.project.id);
      setProjectForm({ name: "", description: "", color: "99,102,241", tags: "" });
      setProjectFormOpen(false);
      setNotice(`Projeto «${payload.project.name}» criado.`);
      await refreshSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível criar o projeto.");
    } finally {
      setBusy(null);
    }
  }, [projectForm, refreshSaved, user]);

  const removeProject = useCallback(
    async (id: string) => {
      try {
        await deleteSearch360Project(id);
        if (activeProjectId === id) setActiveProjectId("");
        setNotice("Projeto removido (os dossiês ficaram sem projeto).");
        await refreshSaved();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível remover o projeto.");
      }
    },
    [activeProjectId, refreshSaved],
  );

  const visibleDossiers = useMemo(() => {
    if (dossierFilter === "projeto" && activeProjectId) return savedDossiers.filter((entry) => entry.project_id === activeProjectId);
    if (dossierFilter === "sem-projeto") return savedDossiers.filter((entry) => !entry.project_id);
    return savedDossiers;
  }, [activeProjectId, dossierFilter, savedDossiers]);

  const activeProject = projects.find((entry) => entry.id === activeProjectId) ?? null;

  const toggleSource = (id: string) => {
    setSelectedSources((current) =>
      current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id],
    );
  };

  /** Ligações de conteúdo: abrem no browser (o IQ OS não impõe um browser próprio). */
  const openUrl = (url: string) => {
    openLink(url);
  };

  /** Descarregamentos (exportações da API): também no browser do sistema. */
  const downloadUrl = (url: string) => {
    openLink(url);
  };

  /**
   * Envia o dossiê guardado para o **Office IQ OS** como documento editável
   * (a síntese, os indicadores e as fontes ficam no texto) e abre a aplicação.
   */
  const openInOffice = useCallback(
    async (dossierId: string, createNew = false) => {
      if (!user) {
        setError("Entrar na plataforma para abrir no Office.");
        return;
      }
      try {
        const payload = await officeDocumentFromDossier(dossierId, { createNew });
        if (typeof window !== "undefined") window.localStorage.setItem(OFFICE_OPEN_KEY, payload.document.id);
        if (getWindowMode()) {
          openWindow("office", estimateWorkspace());
        } else if (typeof window !== "undefined") {
          // Modo página: navega para o Office (não há gestor de janelas).
          window.history.pushState({}, "", "/office");
          window.dispatchEvent(new PopStateEvent("popstate"));
        }
        setNotice(`«${payload.document.title}» ${createNew ? "copiado" : "aberto"} no Office IQ OS.`);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Não foi possível abrir no Office.");
      }
    },
    [user],
  );

  const evidenceByNumber = useMemo(() => {
    const map = new Map<number, { title: string; source: string; url?: string | null }>();
    for (const entry of dossier?.synthesis?.evidence ?? []) {
      map.set(entry.n, { title: entry.title, source: entry.source, url: entry.url });
    }
    return map;
  }, [dossier]);

  /** Converte as citações `[n]` da síntese em ligações para a evidência. */
  const renderSynthesis = (text: string) => {
    const parts = text.split(/(\[\d+\])/g);
    return parts.map((part, index) => {
      const match = /^\[(\d+)\]$/.exec(part);
      if (!match) return <span key={index}>{part}</span>;
      const reference = evidenceByNumber.get(Number(match[1]));
      if (!reference) return <span key={index}>{part}</span>;
      return (
        <a
          key={index}
          href={reference.url ?? undefined}
          onClick={(event) => {
            if (!reference.url) return;
            event.preventDefault();
            openUrl(String(reference.url));
          }}
          title={`${reference.title} — ${reference.source}`}
          className="mx-0.5 rounded bg-sky-400/15 px-1 text-[11px] text-sky-200 hover:bg-sky-400/25"
        >
          [{match[1]}]
        </a>
      );
    });
  };

  const availableSources: Search360Source[] = meta?.sources ?? [];
  const items = result?.items ?? dossier?.items ?? [];
  const folders = dossier?.library?.folders ?? [];
  const metrics = dossier?.metrics ?? [];

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 pb-32 pt-6 sm:px-6">
      {/* ---------------------------------------------------------- cabeçalho */}
      <header className="flex flex-wrap items-start gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-sky-300 via-indigo-500 to-violet-700 text-white shadow-lg shadow-indigo-500/25">
          <Search size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">Pesquisa 360</h1>
          <p className="text-sm text-muted-foreground">
            Meta-modelo de analítica: um tema, todas as fontes — plataforma, documentos, enciclopédia, dados abertos,
            investigação, web e IA — com dossiê, grafo e biblioteca.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {user ? <Badge tone="emerald">sessão iniciada</Badge> : <Badge tone="amber">só dados públicos</Badge>}
          <div className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-2 py-1.5">
            <FolderPlus size={13} className="text-slate-300" />
            <select
              value={activeProjectId}
              onChange={(event) => setActiveProjectId(event.target.value)}
              className="bg-transparent text-[11.5px] text-slate-100 outline-none"
              aria-label="Projeto ativo"
            >
              <option value="" className="bg-[#0b1a24]">
                Sem projeto
              </option>
              {projects.map((project) => (
                <option key={project.id} value={project.id} className="bg-[#0b1a24]">
                  {project.name} ({project.dossier_count ?? 0})
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={() => {
              setProjectFormOpen(true);
              goTo("projetos");
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10"
          >
            <FolderPlus size={13} /> Novo projeto
          </button>
          <button
            type="button"
            onClick={() => {
              setResult(null);
              setDossier(null);
              setGraphData(null);
              setSelectedItem(null);
              setSavedDossierId(null);
              setTerm("");
              setSubmitted("");
              inputRef.current?.focus();
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10"
          >
            <RefreshCw size={13} /> Nova pesquisa
          </button>
        </div>
      </header>

      {/* ---------------------------------------------------------- indicadores */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <Kpi label="Fontes no metamodelo" value={availableSources.length} hint={`${new Set(availableSources.map((entry) => entry.family)).size} famílias`} />
        <Kpi label="Índices internos" value={meta?.indexes.length ?? 0} hint={meta ? `${numberFormat.format(meta.indexes.reduce((total, entry) => total + entry.documents, 0))} documentos` : "…"} />
        <Kpi label="Itens encontrados" value={items.length} hint={result ? `${result.stats.sources_with_results}/${result.stats.sources_queried} fontes com resultados` : "sem pesquisa"} />
        <Kpi label="Tempo" value={result ? `${result.stats.ms} ms` : "—"} hint={result?.cached ? "de cache" : "execução federada"} />
        <Kpi label="Conjuntos de dados" value={(result?.facets?.kind ?? []).find((entry) => entry.value === "dataset")?.count ?? 0} hint="dados abertos" />
        <Kpi label="Indicadores" value={metrics.length} hint={metrics.length ? "séries temporais" : "no dossiê"} />
      </div>

      {/* ------------------------------------------------------------- procura */}
      <div className="glass-card mt-4 rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[260px] flex-1">
            <input
              ref={inputRef}
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void runSearch(term);
              }}
              placeholder="Ex.: energia renovável em Portugal, EDP, contratos de saúde…"
              className="h-11 w-full rounded-xl border border-white/10 bg-white/5 pl-9 pr-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-sky-300/40"
              aria-label="Tema a investigar"
            />
            <Search size={15} className="pointer-events-none absolute left-3 top-3.5 text-muted-foreground" />
            {suggestions.length ? (
              <div className="absolute left-0 right-0 top-12 z-20 overflow-hidden rounded-xl border border-white/10 bg-[#0b1a24] shadow-xl">
                {suggestions.map((suggestion, index) => (
                  <button
                    key={`${suggestion.label}-${index}`}
                    type="button"
                    onClick={() => {
                      setTerm(suggestion.value ?? suggestion.label ?? "");
                      void runSearch(suggestion.value ?? suggestion.label ?? "");
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-slate-200 hover:bg-white/10"
                  >
                    <Boxes size={12} className="text-slate-400" />
                    <span className="flex-1 truncate">{suggestion.label}</span>
                    <span className="text-[10px] text-muted-foreground">{suggestion.hint ?? suggestion.source}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void runSearch(term)}
            disabled={loading === "busca"}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-4 text-sm font-medium text-white shadow-lg shadow-indigo-500/25 transition hover:brightness-110 disabled:opacity-60"
          >
            {loading === "busca" ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} Pesquisar
          </button>
          <button
            type="button"
            onClick={() => void runDossier()}
            disabled={loading === "dossie" || !(submitted || term)}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 text-sm text-slate-100 transition hover:bg-white/10 disabled:opacity-60"
          >
            {loading === "dossie" ? <Loader2 size={15} className="animate-spin" /> : <Layers size={15} />} Dossiê 360
          </button>
        </div>

        {/* temas para começar */}
        {!submitted ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">Começar com:</span>
            {TOPIC_STARTERS.map((starter) => (
              <button
                key={starter}
                type="button"
                onClick={() => {
                  setTerm(starter);
                  void runSearch(starter);
                }}
                className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-200 transition hover:bg-white/10"
              >
                {starter}
              </button>
            ))}
          </div>
        ) : null}

        {/* fontes */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Fontes:</span>
          <button
            type="button"
            onClick={() => setSelectedSources([])}
            className={[
              "rounded-full border px-2.5 py-1 text-[11px] transition",
              selectedSources.length === 0 ? "border-sky-300/40 bg-sky-400/15 text-sky-100" : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
            ].join(" ")}
          >
            automático
          </button>
          {availableSources
            .filter((source) => source.family !== "ai")
            .map((source) => {
              const active = selectedSources.includes(source.id);
              return (
                <button
                  key={source.id}
                  type="button"
                  onClick={() => toggleSource(source.id)}
                  title={source.description}
                  className={[
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition",
                    active ? "border-sky-300/40 bg-sky-400/15 text-sky-100" : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
                  ].join(" ")}
                >
                  {FAMILY_ICON[source.family] ?? <Database size={12} />}
                  {source.label}
                  {source.available === false ? <span className="text-rose-300">•</span> : null}
                </button>
              );
            })}
          <span className="ml-1 inline-flex items-center gap-1 text-[10px] text-muted-foreground">
            <Sparkles size={11} /> a IA sintetiza o dossiê
          </span>
        </div>
      </div>

      {/* ------------------------------------------------------------ secções */}
      <nav className="mt-4 flex flex-wrap gap-1 rounded-2xl border border-white/10 bg-white/5 p-1" aria-label="Secções da pesquisa 360">
        {SEARCH360_SECTIONS.map((entry) => (
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
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-xs text-rose-100">
          <AlertTriangle size={14} /> {error}
          <button type="button" onClick={() => setError(null)} className="ml-auto rounded-lg px-2 py-0.5 hover:bg-white/10">
            <X size={12} />
          </button>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-100">{notice}</div>
      ) : null}

      {/* --------------------------------------------------------------- corpo */}
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-4">
          {current === "busca" ? (
            <>
              {result?.plan ? (
                <div className="glass-card rounded-2xl p-3">
                  <p className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                    <Info size={13} className="text-sky-300" /> Plano de pesquisa
                    <Badge tone="sky">{result.plan.strategy}</Badge>
                    {result.plan.auto ? <Badge tone="slate">fontes automáticas</Badge> : <Badge tone="violet">fontes escolhidas</Badge>}
                  </p>
                  <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                    {result.plan.steps.map((step) => (
                      <li key={step.source_id} className="rounded-xl border border-white/5 bg-white/[0.02] px-2.5 py-1.5">
                        <p className="text-[11.5px] font-medium text-slate-100">{step.label}</p>
                        <p className="text-[11px] text-muted-foreground">{step.why}</p>
                      </li>
                    ))}
                  </ul>
                  {result.plan.keywords.length ? (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Palavras-chave: {result.plan.keywords.join(" · ")}
                      {result.plan.tickers.length ? ` · tickers: ${result.plan.tickers.join(", ")}` : ""}
                      {result.plan.nifs.length ? ` · NIF: ${result.plan.nifs.join(", ")}` : ""}
                    </p>
                  ) : null}
                </div>
              ) : null}

              {loading === "busca" ? (
                <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
                  <Loader2 size={16} className="animate-spin" /> A consultar as fontes em paralelo…
                </div>
              ) : items.length ? (
                <div className="space-y-2">
                  {items.map((entry) => (
                    <ItemCard
                      key={entry.id}
                      entry={entry}
                      active={selectedItem?.id === entry.id}
                      onSelect={() => setSelectedItem(entry)}
                      onOpen={() => (entry.url ? openUrl(String(entry.url)) : setSelectedItem(entry))}
                      onUseAsTopic={() => {
                        setTerm(entry.title);
                        void runSearch(entry.title);
                        goTo("busca");
                      }}
                    />
                  ))}
                </div>
              ) : (
                <div className="glass-card rounded-2xl px-6 py-12 text-center">
                  <Search size={22} className="mx-auto text-sky-300" />
                  <p className="mt-2 text-sm font-medium">Investigue um tema</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Escreva um tema (ou comece por uma sugestão) e a plataforma consulta todas as fontes em paralelo.
                  </p>
                </div>
              )}
            </>
          ) : null}

          {current === "dossie" ? (
            !dossier ? (
              <div className="glass-card rounded-2xl px-6 py-12 text-center">
                <Layers size={22} className="mx-auto text-sky-300" />
                <p className="mt-2 text-sm font-medium">Sem dossiê</p>
                <p className="mt-1 text-xs text-muted-foreground">Faça uma pesquisa e use «Dossiê 360» para juntar tudo sobre o tema.</p>
                <button
                  type="button"
                  onClick={() => void runDossier()}
                  disabled={!(submitted || term) || loading === "dossie"}
                  className="mt-3 inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-100 transition hover:bg-white/10 disabled:opacity-60"
                >
                  {loading === "dossie" ? <Loader2 size={13} className="animate-spin" /> : <Layers size={13} />} Construir dossiê
                </button>
              </div>
            ) : (
              <>
                <div className="glass-card rounded-2xl p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Sparkles size={14} className="text-sky-300" />
                    <p className="text-[13px] font-medium">Síntese — {dossier.term}</p>
                    <Badge tone={dossier.synthesis?.mode === "ai" ? "emerald" : "slate"}>
                      {dossier.synthesis?.mode === "ai" ? `IA · ${dossier.synthesis.backend.model ?? dossier.synthesis.backend.provider}` : "factual (sem modelo)"}
                    </Badge>
                    {dossier.cached ? <Badge tone="slate">de cache</Badge> : null}
                    {savedDossierId ? <Badge tone="violet">guardado</Badge> : null}
                    {activeProject ? <Badge tone="sky">{activeProject.name}</Badge> : null}
                    <span className="ml-auto text-[10px] text-muted-foreground">{dossier.stats.items} itens · {dossier.stats.ms} ms</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={openSaveForm}
                      disabled={busy === "guardar"}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-sky-400/25 bg-sky-400/10 px-3 py-1.5 text-[11.5px] text-sky-100 transition hover:bg-sky-400/20 disabled:opacity-60"
                    >
                      {busy === "guardar" ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                      {savedDossierId ? "Atualizar dossiê guardado" : "Guardar dossiê"}
                    </button>
                    {savedDossierId ? (
                      <>
                        <button
                          type="button"
                          onClick={() => void refreshSavedDossier(savedDossierId)}
                          disabled={busy === "atualizar"}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-100 transition hover:bg-white/10 disabled:opacity-60"
                        >
                          {busy === "atualizar" ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Repesquisar tema
                        </button>
                        <button
                          type="button"
                          onClick={() => void openInOffice(savedDossierId)}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-violet-400/25 bg-violet-400/10 px-3 py-1.5 text-[11.5px] text-violet-100 transition hover:bg-violet-400/20"
                          title="Abrir este dossiê como documento editável no Office IQ OS"
                        >
                          <BookOpen size={12} /> Abrir no Office
                        </button>
                        <button
                          type="button"
                          onClick={() => downloadUrl(search360DossierExportUrl(savedDossierId, "md"))}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-100 transition hover:bg-white/10"
                        >
                          <Download size={12} /> Exportar .md
                        </button>
                        <button
                          type="button"
                          onClick={() => downloadUrl(search360DossierExportUrl(savedDossierId, "json"))}
                          className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-100 transition hover:bg-white/10"
                        >
                          <Download size={12} /> .json
                        </button>
                      </>
                    ) : null}
                    {!canSave ? <span className="text-[11px] text-amber-200">Entre na plataforma para guardar dossiês.</span> : null}
                  </div>
                  {saveOpen ? (
                    <div className="mt-3 grid gap-2 rounded-2xl border border-sky-400/20 bg-sky-400/5 p-3 sm:grid-cols-2">
                      <label className="text-[11px] text-muted-foreground sm:col-span-2">
                        Título
                        <input
                          value={saveForm.title}
                          onChange={(event) => setSaveForm((current) => ({ ...current, title: event.target.value }))}
                          className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
                        />
                      </label>
                      <label className="text-[11px] text-muted-foreground">
                        Projeto
                        <select
                          value={saveForm.project_id}
                          onChange={(event) => setSaveForm((current) => ({ ...current, project_id: event.target.value }))}
                          className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none"
                        >
                          <option value="" className="bg-[#0b1a24]">
                            Sem projeto
                          </option>
                          {projects.map((project) => (
                            <option key={project.id} value={project.id} className="bg-[#0b1a24]">
                              {project.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="text-[11px] text-muted-foreground">
                        Etiquetas (separadas por vírgula)
                        <input
                          value={saveForm.tags}
                          onChange={(event) => setSaveForm((current) => ({ ...current, tags: event.target.value }))}
                          placeholder="energia, pt, 2026"
                          className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
                        />
                      </label>
                      <label className="text-[11px] text-muted-foreground sm:col-span-2">
                        Notas (ficam no dossiê e na exportação)
                        <textarea
                          value={saveForm.notes}
                          onChange={(event) => setSaveForm((current) => ({ ...current, notes: event.target.value }))}
                          rows={2}
                          className="mt-1 w-full rounded-xl border border-white/10 bg-white/5 px-2 py-1 text-[12px] text-slate-100 outline-none focus:border-sky-300/40"
                        />
                      </label>
                      <div className="flex items-center gap-2 sm:col-span-2">
                        <button
                          type="button"
                          onClick={() => void submitSave()}
                          disabled={busy === "guardar"}
                          className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-1.5 text-[11.5px] font-medium text-white transition hover:brightness-110 disabled:opacity-60"
                        >
                          {busy === "guardar" ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Guardar
                        </button>
                        <button
                          type="button"
                          onClick={() => setSaveOpen(false)}
                          className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-200 transition hover:bg-white/10"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <div className="mt-3 space-y-2 whitespace-pre-line text-[12.5px] leading-relaxed text-slate-200">
                    {renderSynthesis(dossier.synthesis?.text ?? "")}
                  </div>
                  {dossier.synthesis?.notes?.length ? (
                    <p className="mt-3 text-[11px] text-muted-foreground">{dossier.synthesis.notes.join(" ")}</p>
                  ) : null}
                  {dossier.synthesis?.warnings?.length ? (
                    <p className="mt-1 text-[11px] text-amber-200">{dossier.synthesis.warnings.join(" ")}</p>
                  ) : null}
                </div>

                {metrics.length ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {metrics.map((metric) => (
                      <MetricCard key={metric.indicator} metric={metric} />
                    ))}
                  </div>
                ) : null}

                <div className="glass-card rounded-2xl p-3">
                  <p className="text-[12px] font-medium">O que cada fonte deu</p>
                  <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                    {dossier.per_source.map((row) => (
                      <div key={row.source_id} className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-2.5 py-1.5">
                        <span className="text-slate-300">{FAMILY_ICON[row.family] ?? <Database size={13} />}</span>
                        <span className="flex-1 text-[11.5px] text-slate-100">{row.label}</span>
                        <span className="text-[11px] text-muted-foreground">{row.items} itens</span>
                        <span className={`text-[10px] ${row.ok ? "text-emerald-300" : "text-amber-200"}`}>{row.ok ? `${row.ms} ms` : "falhou"}</span>
                      </div>
                    ))}
                  </div>
                  {dossier.warnings.length ? (
                    <ul className="mt-2 space-y-1 text-[11px] text-amber-200">
                      {dossier.warnings.map((warning) => (
                        <li key={warning}>• {warning}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>

                {dossier.synthesis?.evidence?.length ? (
                  <div className="glass-card rounded-2xl p-3">
                    <p className="text-[12px] font-medium">Evidências citadas</p>
                    <ol className="mt-2 space-y-1">
                      {dossier.synthesis.evidence.map((entry) => (
                        <li key={entry.n} className="flex items-center gap-2 text-[11.5px] text-slate-200">
                          <span className="w-6 shrink-0 text-right text-muted-foreground">[{entry.n}]</span>
                          <span className="min-w-0 flex-1 truncate">{entry.title}</span>
                          <Badge tone="slate">{entry.source}</Badge>
                          {entry.url ? (
                            <button
                              type="button"
                              onClick={() => openUrl(String(entry.url))}
                              className="shrink-0 rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] transition hover:bg-white/10"
                            >
                              abrir
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </>
            )
          ) : null}

          {current === "projetos" ? (
            <>
              {/* criar projeto */}
              <div className="glass-card rounded-2xl p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <FolderPlus size={14} className="text-indigo-300" />
                  <p className="text-[12.5px] font-medium">Projetos</p>
                  <Badge tone="slate">{projects.length}</Badge>
                  <Badge tone="sky">{savedDossiers.length} dossiês guardados</Badge>
                  <button
                    type="button"
                    onClick={() => setProjectFormOpen((current) => !current)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-100 transition hover:bg-white/10"
                  >
                    <FolderPlus size={12} /> {projectFormOpen ? "Fechar" : "Criar projeto"}
                  </button>
                </div>
                {projectFormOpen ? (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <label className="text-[11px] text-muted-foreground">
                      Nome
                      <input
                        value={projectForm.name}
                        onChange={(event) => setProjectForm((current) => ({ ...current, name: event.target.value }))}
                        placeholder="Transição energética"
                        className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-indigo-300/40"
                      />
                    </label>
                    <label className="text-[11px] text-muted-foreground">
                      Etiquetas
                      <input
                        value={projectForm.tags}
                        onChange={(event) => setProjectForm((current) => ({ ...current, tags: event.target.value }))}
                        placeholder="energia, regulatório"
                        className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-indigo-300/40"
                      />
                    </label>
                    <label className="text-[11px] text-muted-foreground sm:col-span-2">
                      Descrição
                      <input
                        value={projectForm.description}
                        onChange={(event) => setProjectForm((current) => ({ ...current, description: event.target.value }))}
                        placeholder="O que este projeto investiga e para quê"
                        className="mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/5 px-2 text-[12px] text-slate-100 outline-none focus:border-indigo-300/40"
                      />
                    </label>
                    <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
                      <div className="flex items-center gap-1.5">
                        {["99,102,241", "16,185,129", "245,158,11", "244,63,94", "56,189,248", "167,139,250"].map((color) => (
                          <button
                            key={color}
                            type="button"
                            onClick={() => setProjectForm((current) => ({ ...current, color }))}
                            className={`h-6 w-6 rounded-full border-2 transition ${projectForm.color === color ? "border-white" : "border-transparent"}`}
                            style={{ background: `rgb(${color})` }}
                            aria-label={`Cor ${color}`}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => void submitProject()}
                        disabled={busy === "projeto"}
                        className="ml-auto inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-1.5 text-[11.5px] font-medium text-white transition hover:brightness-110 disabled:opacity-60"
                      >
                        {busy === "projeto" ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Criar
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              {/* lista de projetos */}
              {projects.length ? (
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {projects.map((project) => {
                    const active = project.id === activeProjectId;
                    return (
                      <div
                        key={project.id}
                        className={[
                          "rounded-2xl border p-3 transition",
                          active ? "border-indigo-300/40 bg-indigo-400/10" : "border-white/10 bg-white/[0.03] hover:border-white/20",
                        ].join(" ")}
                      >
                        <div className="flex items-start gap-2">
                          <span className="mt-0.5 h-3 w-3 shrink-0 rounded-full" style={{ background: `rgb(${project.color ?? "99,102,241"})` }} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[12.5px] font-medium text-foreground">{project.name}</p>
                            <p className="text-[11px] text-muted-foreground">
                              {project.dossier_count ?? 0} dossiês
                              {project.updated_at ? ` · ${String(project.updated_at).slice(0, 10)}` : ""}
                            </p>
                            {project.description ? <p className="mt-1 line-clamp-2 text-[11px] text-slate-300/80">{project.description}</p> : null}
                            {project.tags?.length ? (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {project.tags.map((tag) => (
                                  <Badge key={tag} tone="violet">
                                    {tag}
                                  </Badge>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => {
                              setActiveProjectId(active ? "" : project.id);
                              setDossierFilter(active ? "todos" : "projeto");
                            }}
                            className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-slate-100 transition hover:bg-white/10"
                          >
                            {active ? "Retirar seleção" : "Trabalhar neste projeto"}
                          </button>
                          <button
                            type="button"
                            onClick={() => void removeProject(project.id)}
                            className="ml-auto rounded-lg border border-rose-400/25 bg-rose-400/10 px-2 py-1 text-[10.5px] text-rose-100 transition hover:bg-rose-400/20"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="glass-card rounded-2xl px-6 py-10 text-center">
                  <FolderPlus size={22} className="mx-auto text-indigo-300" />
                  <p className="mt-2 text-sm font-medium">Ainda não há projetos</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Um projeto agrupa dossiês sobre o mesmo assunto (ex.: «Transição energética»), para voltar a eles meses
                    depois.
                  </p>
                </div>
              )}

              {/* dossiês guardados */}
              <div className="glass-card rounded-2xl p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Layers size={14} className="text-sky-300" />
                  <p className="text-[12.5px] font-medium">Dossiês guardados</p>
                  <div className="ml-auto flex flex-wrap gap-1.5">
                    {(
                      [
                        ["todos", "Todos"],
                        ["projeto", activeProject ? `Projeto: ${activeProject.name}` : "Projeto"],
                        ["sem-projeto", "Sem projeto"],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setDossierFilter(id)}
                        className={[
                          "rounded-full border px-2.5 py-1 text-[11px] transition",
                          dossierFilter === id ? "border-sky-300/40 bg-sky-400/15 text-sky-100" : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10",
                        ].join(" ")}
                      >
                        {label}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => void refreshSaved()}
                      className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300 transition hover:bg-white/10"
                      title="Voltar a ler os dossiês guardados"
                    >
                      <RefreshCw size={11} />
                    </button>
                  </div>
                </div>
                {visibleDossiers.length ? (
                  <ul className="mt-2 space-y-2">
                    {visibleDossiers.map((entry) => {
                      const project = projects.find((item) => item.id === entry.project_id);
                      return (
                        <li
                          key={entry.id}
                          className={[
                            "rounded-2xl border p-3 transition",
                            savedDossierId === entry.id ? "border-sky-300/40 bg-sky-400/10" : "border-white/10 bg-white/[0.02] hover:border-white/20",
                          ].join(" ")}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[12.5px] font-medium text-foreground">{entry.title}</span>
                            {project ? <Badge tone="sky">{project.name}</Badge> : <Badge tone="slate">sem projeto</Badge>}
                            <Badge tone={entry.synthesis_mode === "ai" ? "emerald" : "slate"}>
                              {entry.synthesis_mode === "ai" ? "IA" : "factual"}
                            </Badge>
                            {entry.tags.map((tag) => (
                              <Badge key={tag} tone="violet">
                                {tag}
                              </Badge>
                            ))}
                            <span className="ml-auto text-[10px] text-muted-foreground">
                              {String(entry.saved_at ?? entry.created_at ?? "").slice(0, 16).replace("T", " ")}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            tema: {entry.term ?? "—"} · {entry.items ?? 0} itens de {entry.sources ?? 0} fontes · {entry.metrics} indicadores ·{" "}
                            {entry.evidence} evidências
                          </p>
                          {entry.notes ? <p className="mt-1 line-clamp-2 text-[11.5px] text-slate-300/85">{entry.notes}</p> : null}
                          <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() => void openSavedDossier(entry.id)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/25 bg-sky-400/10 px-2 py-1 text-[10.5px] text-sky-100 transition hover:bg-sky-400/20"
                            >
                              <Layers size={11} /> abrir
                            </button>
                            <button
                              type="button"
                              onClick={() => void refreshSavedDossier(entry.id)}
                              disabled={busy === "atualizar"}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-slate-100 transition hover:bg-white/10 disabled:opacity-60"
                            >
                              {busy === "atualizar" ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} repesquisar
                            </button>
                            <button
                              type="button"
                              onClick={() => void openInOffice(entry.id)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/25 bg-violet-400/10 px-2 py-1 text-[10.5px] text-violet-100 transition hover:bg-violet-400/20"
                              title="Abrir no Office IQ OS"
                            >
                              <BookOpen size={11} /> Office
                            </button>
                            <button
                              type="button"
                              onClick={() => downloadUrl(search360DossierExportUrl(entry.id, "md"))}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-slate-100 transition hover:bg-white/10"
                            >
                              <Download size={11} /> .md
                            </button>
                            <label className="ml-auto inline-flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
                              <Pencil size={11} /> projeto
                              <select
                                value={entry.project_id ?? ""}
                                onChange={(event) => void moveDossier(entry.id, event.target.value)}
                                className="rounded-lg border border-white/10 bg-white/5 px-1.5 py-1 text-[10.5px] text-slate-100 outline-none"
                              >
                                <option value="" className="bg-[#0b1a24]">
                                  sem projeto
                                </option>
                                {projects.map((item) => (
                                  <option key={item.id} value={item.id} className="bg-[#0b1a24]">
                                    {item.name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <button
                              type="button"
                              onClick={() => void removeDossier(entry.id)}
                              className="rounded-lg border border-rose-400/25 bg-rose-400/10 px-2 py-1 text-[10.5px] text-rose-100 transition hover:bg-rose-400/20"
                              title="Apagar dossiê"
                            >
                              <Trash2 size={11} />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mt-3 text-[11.5px] text-muted-foreground">
                    Sem dossiês neste filtro. Faça uma pesquisa, construa o «Dossiê 360» e guarde-o — fica aqui, com a
                    evidência e a síntese do momento.
                  </p>
                )}
              </div>
            </>
          ) : null}

          {current === "grafo" ? (
            <>
              <Search360Graph
                graph={graphData}
                selectedId={selectedNode?.id ?? null}
                loading={loading === "grafo"}
                onSelect={(node) => setSelectedNode(node)}
                onOpen={(node) => {
                  if (node.url) openUrl(node.url);
                }}
              />
              {!graphData ? (
                <div className="glass-card flex flex-wrap items-center gap-2 rounded-2xl px-4 py-3 text-xs text-muted-foreground">
                  <Network size={14} /> Sem grafo ainda.
                  <button
                    type="button"
                    onClick={() => void runDossier()}
                    className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-100 transition hover:bg-white/10"
                  >
                    Construir a partir do tema
                  </button>
                </div>
              ) : null}
              {selectedNode ? (
                <div className="glass-card rounded-2xl p-3">
                  <div className="flex items-center gap-2">
                    <span className="grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-white/5">{kindIcon(selectedNode.kind)}</span>
                    <p className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{selectedNode.label}</p>
                    <Badge tone="violet">{kindLabel(selectedNode.kind)}</Badge>
                    {selectedNode.source_label ? <Badge tone="slate">{selectedNode.source_label}</Badge> : null}
                  </div>
                  {selectedNode.snippet ? <p className="mt-2 text-[11.5px] text-slate-300/90">{selectedNode.snippet}</p> : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {selectedNode.url ? (
                      <button
                        type="button"
                        onClick={() => openUrl(String(selectedNode.url))}
                        className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-100 transition hover:bg-white/10"
                      >
                        <ExternalLink size={11} /> abrir no browser
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => {
                        setTerm(selectedNode.label);
                        void runSearch(selectedNode.label);
                        goTo("busca");
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-sky-400/25 bg-sky-400/10 px-2 py-1 text-[11px] text-sky-100 transition hover:bg-sky-400/20"
                    >
                      <Wand2 size={11} /> investigar como tema
                    </button>
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {current === "biblioteca" ? (
            folders.length ? (
              <FolderTree folders={folders} onOpen={openUrl} />
            ) : (
              <div className="glass-card rounded-2xl px-6 py-12 text-center">
                <Folder size={22} className="mx-auto text-sky-300" />
                <p className="mt-2 text-sm font-medium">Biblioteca vazia</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Depois de uma pesquisa, o tema aparece organizado em pastas por família de fonte e ficheiros por tipo.
                </p>
              </div>
            )
          ) : null}
        </div>

        {/* -------------------------------------------------------- lateral */}
        <aside className="space-y-3">
          {selectedItem ? (
            <div className="glass-card rounded-2xl p-3">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 grid h-8 w-8 place-items-center rounded-xl border border-white/10 bg-white/5">{kindIcon(selectedItem.kind)}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium text-foreground">{selectedItem.title}</p>
                  <p className="text-[11px] text-muted-foreground">{selectedItem.source_label} · {kindLabel(selectedItem.kind)}</p>
                </div>
                <button type="button" onClick={() => setSelectedItem(null)} className="rounded-lg px-1.5 py-0.5 text-muted-foreground hover:bg-white/10">
                  <X size={12} />
                </button>
              </div>
              {selectedItem.snippet ? <p className="mt-2 text-[11.5px] leading-relaxed text-slate-300/90">{selectedItem.snippet}</p> : null}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {selectedItem.badges.map((badge) => (
                  <Badge key={badge} tone="slate">{badge}</Badge>
                ))}
              </div>
              {selectedItem.url ? (
                <button
                  type="button"
                  onClick={() => openUrl(String(selectedItem.url))}
                  className="mt-3 inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-100 transition hover:bg-white/10"
                >
                  <ExternalLink size={11} /> abrir no browser
                </button>
              ) : null}
              {Object.keys(selectedItem.data ?? {}).length ? (
                <dl className="mt-3 space-y-1 border-t border-white/10 pt-2 text-[11px]">
                  {Object.entries(selectedItem.data)
                    .filter(([, value]) => value !== null && value !== undefined && value !== "")
                    .slice(0, 8)
                    .map(([key, value]) => (
                      <div key={key} className="flex gap-2">
                        <dt className="w-24 shrink-0 text-muted-foreground">{key}</dt>
                        <dd className="min-w-0 flex-1 truncate text-slate-200">{typeof value === "object" ? JSON.stringify(value).slice(0, 80) : String(value)}</dd>
                      </div>
                    ))}
                </dl>
              ) : null}
            </div>
          ) : null}

          {result?.facets ? (
            <div className="glass-card rounded-2xl p-3">
              <p className="text-[12px] font-medium">Facetas</p>
              {(["family", "kind", "source", "year"] as const).map((key) => {
                const entries = result.facets[key] ?? [];
                if (!entries.length) return null;
                return (
                  <div key={key} className="mt-2">
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{key === "family" ? "família" : key === "kind" ? "tipo" : key === "source" ? "fonte" : "ano"}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {entries.slice(0, 8).map((entry) => (
                        <span key={entry.value} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-slate-200">
                          {key === "kind" ? kindLabel(entry.value) : entry.value} <span className="text-muted-foreground">{entry.count}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          {meta?.indexes?.length ? (
            <div className="glass-card rounded-2xl p-3">
              <p className="text-[12px] font-medium">Plataforma IQ OS</p>
              <ul className="mt-2 space-y-1">
                {meta.indexes.slice(0, 8).map((entry) => (
                  <li key={entry.index} className="flex items-center gap-2 text-[11px]">
                    <Database size={11} className="text-slate-400" />
                    <span className="flex-1 truncate text-slate-200">{entry.label}</span>
                    <span className="text-muted-foreground">{numberFormat.format(entry.documents)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="glass-card rounded-2xl p-3 text-[11px] text-muted-foreground">
            <p className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-foreground">
              <Info size={12} /> Como funciona
            </p>
            O plano de pesquisa escolhe as fontes pelo tipo de tema (entidade, tema ou investigação). As fontes externas
            são consultadas em paralelo com tempo limite próprio; o que falhar aparece no dossiê, sem inventar dados. A
            síntese só usa as evidências numeradas e cita-as.
          </div>
        </aside>
      </div>
    </div>
  );
}
