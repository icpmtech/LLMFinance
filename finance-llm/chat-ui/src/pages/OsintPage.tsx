import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui";
import { Loader2, Search, Scan, Trash2, ExternalLink, Network, User, Mail, Building2, Check } from "lucide-react";
import { API_BASE } from "../api";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import type { StudioGraph, StudioNode, StudioEdge } from "../components/graph/graphStudio";

type OsintKind = "username" | "email" | "nif";

type OsintProfileDetail = {
  display_name?: string | null;
  bio?: string | null;
  avatar?: string | null;
  followers?: string | null;
  joined?: string | null;
  links?: string[];
  metrics?: Record<string, unknown>;
  fields?: Record<string, unknown>;
};

type OsintLeads = { emails?: string[]; urls?: string[] };

type OsintProfileHit = {
  status: string;
  site_name: string;
  category: string;
  url?: string | null;
  reason?: string | null;
  extra?: Record<string, unknown>;
  media?: Record<string, string>;
  profile?: OsintProfileDetail;
  leads?: OsintLeads;
  confidence?: string | null;
};

type OsintPivot = {
  handle?: string | null;
  kind?: string | null;
  source_site?: string | null;
  source_key?: string | null;
  site?: string | null;
  url?: string | null;
};

type OsintStats = {
  platforms_found?: number;
  platforms_with_name?: number;
  platforms_with_avatar?: number;
  names?: string[];
  emails?: string[];
  pivot_count?: number;
  pivot_sites?: string[];
  nif_valid?: boolean | null;
  related?: string[];
  aliases?: string[];
  people?: string[];
};

type OsintGraphNode = {
  id: string;
  label: string;
  group: string;
  url?: string | null;
  details?: string | null;
  avatar?: string | null;
  confidence?: string | null;
};
type OsintGraphEdge = { source: string; target: string; label?: string | null };
type OsintGraph = { nodes: OsintGraphNode[]; edges: OsintGraphEdge[] };

type OsintScanResponse = {
  target: string;
  kind: OsintKind;
  total: number;
  found: number;
  not_found: number;
  errors: number;
  duration_s?: number | null;
  category?: string | null;
  categories?: string[];
  platforms_per_category?: Record<string, number>;
  hits: OsintProfileHit[];
  pivots?: OsintPivot[];
  stats?: OsintStats;
  graph: OsintGraph;
  saved: boolean;
  saved_id?: string | null;
  error?: string | null;
};

type OsintSearchItem = {
  id: string;
  target: string;
  kind: string;
  category?: string | null;
  found: number;
  total: number;
  scanned_at?: string | null;
  top_sites: string[];
  names?: string[];
  emails?: string[];
  pivots?: number;
  stats?: OsintStats;
};

type OsintSearchResponse = {
  total: number;
  items: OsintSearchItem[];
  from_: number;
  size: number;
  error?: string | null;
};

type OsintPreset = {
  id: string;
  label: string;
  hint: string;
  username: string[];
  email: string[];
};

type OsintCategoriesResponse = {
  username: string[];
  email: string[];
  nif?: string[];
  defaults?: Partial<Record<OsintKind, string | null>>;
  platforms?: { username: Record<string, number>; email: Record<string, number> };
  presets?: OsintPreset[];
};

/** Valida um NIF português (dígito de controlo, módulo 11). */
function isValidNif(value: string): boolean {
  const digits = (value || "").replace(/\D/g, "");
  if (!/^\d{9}$/.test(digits) || "04".includes(digits[0])) return false;
  const total = digits
    .slice(0, 8)
    .split("")
    .reduce((sum, digit, index) => sum + Number(digit) * (9 - index), 0);
  const check = 11 - (total % 11);
  return (check >= 10 ? 0 : check) === Number(digits[8]);
}

const COLORS: Record<string, string> = {
  username: "#d946ef",
  email: "#8b5cf6",
  site: "#2dd4bf",
  finance: "#f59e0b",
  social: "#3b82f6",
  gaming: "#ef4444",
  dev: "#10b981",
  other: "#94a3b8",
};

function toStudioGraph(graph: OsintGraph | null | undefined): StudioGraph | null {
  if (!graph || !graph.nodes?.length) return null;
  const nodes: StudioNode[] = graph.nodes.map((n) => ({
    id: n.id,
    key: n.id,
    label: n.label,
    dimension: n.group,
    type: n.group === "username" || n.group === "email" ? "person" : "source",
    role: n.group,
    count: graph.edges.filter((e) => e.source === n.id || e.target === n.id).length,
    total_value: 0,
    value: graph.edges.filter((e) => e.source === n.id || e.target === n.id).length,
    radius: n.group === "username" || n.group === "email" ? 18 : 12,
    color: COLORS[n.group] || COLORS.other,
    legendKey: n.group,
    legendLabel: n.group,
    url: n.url ?? null,
    details: n.details ?? null,
  })) as unknown as StudioNode[];
  const edges: StudioEdge[] = graph.edges.map((e) => ({
    source: e.source,
    target: e.target,
    count: 1,
    value: 1,
    weight: 1,
    label: e.label ?? undefined,
  })) as unknown as StudioEdge[];
  return { nodes, edges, meta: {} as StudioGraph["meta"] };
}

async function authFetch(path: string, init?: RequestInit) {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("finance-llm-token") : null;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

const CONFIDENCE_STYLE: Record<string, { label: string; className: string }> = {
  confirmed: { label: "confirmado", className: "bg-emerald-600" },
  likely: { label: "provável", className: "bg-teal-600" },
  candidate: { label: "candidato", className: "bg-slate-500" },
  conflicting: { label: "em conflito", className: "bg-amber-600" },
  cross: { label: "conta cruzada", className: "bg-fuchsia-600" },
};

/** Descarrega o relatório do scan (json, csv ou pdf) usando o token da sessão. */
async function downloadReport(docId: string, format: "json" | "csv" | "pdf") {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("finance-llm-token") : null;
  const res = await fetch(`${API_BASE}/osint/report/${encodeURIComponent(docId)}?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] || `osint-${docId.replace(/[^\w.-]+/g, "_")}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Rótulo curto de uma ligação, tolerante a caminhos internos da app. */
function linkLabel(link: string): string {
  if (link.startsWith("/")) return "ficha interna";
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return link.slice(0, 24);
  }
}

/** Cartão de um resultado: avatar, nome, bio, métricas, pistas e ligações. */
function ProfileCard({ hit }: { hit: OsintProfileHit }) {
  const profile = hit.profile || {};
  const metrics = Object.entries(profile.metrics || {});
  const emails = hit.leads?.emails || [];
  const confidence = CONFIDENCE_STYLE[hit.confidence || ""] || null;
  return (
    <Card className="flex flex-col gap-2 p-3">
      <div className="flex items-start gap-3">
        {profile.avatar ? (
          <img
            src={profile.avatar}
            alt=""
            className="h-10 w-10 shrink-0 rounded-full object-cover ring-1 ring-border"
            referrerPolicy="no-referrer"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
          />
        ) : (
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
            <User size={16} />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium">{profile.display_name || hit.site_name}</span>
            {confidence && <Badge className={`${confidence.className} text-[10px]`}>{confidence.label}</Badge>}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {hit.site_name} · {hit.category}
            {profile.followers ? ` · ${profile.followers} seguidores` : ""}
          </div>
        </div>
      </div>

      {profile.bio && <p className="line-clamp-3 text-xs text-muted-foreground">{profile.bio}</p>}

      {metrics.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {metrics.slice(0, 6).map(([key, value]) => (
            <Badge key={key} variant="outline" className="text-[10px]">{key}: {String(value)}</Badge>
          ))}
        </div>
      )}

      {profile.joined && (
        <div className="text-[11px] text-muted-foreground">Desde {String(profile.joined).slice(0, 10)}</div>
      )}

      {emails.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {emails.map((email) => (
            <Badge key={email} className="bg-sky-600 text-[10px]">
              <Mail size={10} className="mr-1" /> {email}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-wrap gap-2 pt-1 text-xs">
        {hit.url && (
          <a href={hit.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            {hit.url.startsWith("/") ? "Abrir ficha" : "Perfil"} <ExternalLink size={12} />
          </a>
        )}
        {(profile.links || []).slice(0, 3).map((link) => (
          <a key={link} href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-muted-foreground hover:underline">
            {linkLabel(link)} <ExternalLink size={11} />
          </a>
        ))}
      </div>
    </Card>
  );
}

/** Contas cruzadas: plataformas para onde o perfil aponta, mesmo sem scan. */
function PivotList({ pivots }: { pivots: OsintPivot[] }) {
  if (!pivots.length) return null;
  const isInternal = pivots.some((p) => p.kind === "alias");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Network size={16} /> {isInternal ? `Relacionados (${pivots.length})` : `Contas cruzadas (${pivots.length})`}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">
          {pivots.some((p) => p.kind === "alias")
            ? "Entidades ligadas, pessoas com cargos registados e nomes alternativos que o sistema associa a este alvo."
            : "Ligações que os perfis encontrados expõem noutras plataformas — não foram pesquisadas, mas apontam para o mesmo alvo."}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {pivots.map((pivot) => (
            <div key={`${pivot.site}-${pivot.source_site}-${pivot.source_key}-${pivot.url}`} className="rounded-lg border p-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{pivot.site || pivot.source_key}</span>
                <Badge variant="outline" className="text-[10px]">{pivot.kind || "link"}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {pivot.handle ? `@${pivot.handle} · ` : ""}via {pivot.source_site}/{pivot.source_key}
              </div>
              {pivot.url ? (
                <a href={pivot.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline">
                  {pivot.url.startsWith("/") ? "Abrir ficha" : "Abrir"} <ExternalLink size={11} />
                </a>
              ) : (
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {pivot.handle ? `NIF ${pivot.handle} — ` : ""}testar com um novo scan
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Pistas: emails e URLs descobertos nos perfis. */
function LeadsCard({ hits }: { hits: OsintProfileHit[] }) {
  const emails = Array.from(new Set(hits.flatMap((h) => h.leads?.emails || [])));
  const urls = Array.from(new Set(hits.flatMap((h) => h.leads?.urls || [])));
  if (!emails.length && !urls.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pistas nos perfis</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {emails.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Emails</div>
            <div className="flex flex-wrap gap-1">
              {emails.map((email) => (
                <Badge key={email} className="bg-sky-600 text-[11px]">
                  <Mail size={10} className="mr-1" /> {email}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {urls.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Ligações ({urls.length})</div>
            <div className="flex flex-wrap gap-1">
              {urls.slice(0, 20).map((url) => (
                <a key={url} href={url} target="_blank" rel="noreferrer" className="rounded border px-2 py-0.5 text-[11px] text-primary hover:underline">
                  {(() => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } })()}
                </a>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function OsintPage() {
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<OsintKind>("username");
  const [selected, setSelected] = useState<string[]>([]);
  const [fullScan, setFullScan] = useState(false);
  const [categories, setCategories] = useState<OsintCategoriesResponse>({ username: [], email: [], nif: [] });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OsintScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchQ, setSearchQ] = useState("");
  const [searchKind, setSearchKind] = useState<OsintKind | "">("");
  const [searchResult, setSearchResult] = useState<OsintSearchResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("scan");
  const [graph, setGraph] = useState<OsintGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  // Filtro local dos resultados ("Todos", "Encontrados", "Sem perfil", "Erros").
  const [hitFilter, setHitFilter] = useState<"found" | "missing" | "error" | "all">("found");
  const [hitQuery, setHitQuery] = useState("");

  useEffect(() => {
    authFetch("/osint/categories")
      .then((data) => {
        const parsed = data as OsintCategoriesResponse;
        setCategories({
          username: parsed.username ?? [],
          email: parsed.email ?? [],
          nif: [],
          defaults: parsed.defaults,
          platforms: parsed.platforms,
          presets: parsed.presets,
        });
      })
      .catch(() => setCategories({ username: [], email: [], nif: [] }));
  }, []);

  // Ao mudar de tipo, a seleção anterior deixa de fazer sentido.
  useEffect(() => {
    setSelected([]);
    setFullScan(false);
  }, [kind]);

  useEffect(() => {
    if (activeTab === "saved") loadSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const availableCategories = useMemo(() => categories[kind] || [], [categories, kind]);
  const platformCounts = useMemo(
    () => (kind === "email" ? categories.platforms?.email : categories.platforms?.username) || {},
    [categories, kind],
  );
  const defaultCategory = useMemo(
    () => categories.defaults?.[kind] || availableCategories[0] || null,
    [categories, kind, availableCategories],
  );
  const isNif = kind === "nif";

  // Quantas plataformas o scan escolhido vai verificar (aviso de custo antes de
  // arrancar: 30 plataformas não é o mesmo que 573).
  const plannedPlatforms = useMemo(() => {
    if (isNif) return 0;
    if (fullScan) return Object.values(platformCounts).reduce((sum, n) => sum + n, 0);
    if (!selected.length) return platformCounts[defaultCategory || ""] || 0;
    return selected.reduce((sum, name) => sum + (platformCounts[name] || 0), 0);
  }, [isNif, fullScan, selected, platformCounts, defaultCategory]);

  const estimateSeconds = Math.max(5, Math.round(plannedPlatforms / 26));

  function toggleCategory(name: string) {
    setSelected((prev) => (prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]));
  }

  function applyPreset(preset: OsintPreset) {
    const names = kind === "email" ? preset.email : preset.username;
    if (!names.length) {
      setFullScan(true);
      setSelected([]);
      return;
    }
    setFullScan(false);
    setSelected(names.filter((name) => availableCategories.includes(name)));
  }

  async function runScan(e?: React.FormEvent) {
    e?.preventDefault();
    const value = target.trim();
    if (!value) return;
    if (kind === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setError("Email inválido: escreva um endereço como nome@dominio.com");
      return;
    }
    if (kind === "nif" && !isValidNif(value)) {
      setError("NIF inválido: são 9 dígitos e o dígito de controlo tem de conferir (ex.: 500189412).");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setHitFilter("found");
    setHitQuery("");
    try {
      const payload: Record<string, unknown> = { target: value, kind };
      if (!isNif) {
        payload.categories = selected;
        payload.full_scan = fullScan;
      }
      const data = (await authFetch("/osint/scan", {
        method: "POST",
        body: JSON.stringify(payload),
      })) as OsintScanResponse;
      setResult(data);
      if (data.saved && data.saved_id) {
        setGraph(data.graph);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadSaved() {
    setSearchLoading(true);
    try {
      const payload: Record<string, unknown> = { q: searchQ.trim(), size: 50, from: 0 };
      if (searchKind) payload.kind = searchKind;
      const data = (await authFetch("/osint/search", {
        method: "POST",
        body: JSON.stringify(payload),
      })) as OsintSearchResponse;
      setSearchResult(data);
    } catch (err) {
      setSearchResult({ total: 0, items: [], from_: 0, size: 50, error: err instanceof Error ? err.message : String(err) });
    } finally {
      setSearchLoading(false);
    }
  }

  async function deleteScan(id: string) {
    await authFetch(`/osint/saved/${encodeURIComponent(id)}`, { method: "DELETE" });
    loadSaved();
  }

  async function showGraph(id: string) {
    setGraphLoading(true);
    try {
      const data = (await authFetch(`/osint/graph/${encodeURIComponent(id)}`)) as OsintGraph;
      setGraph(data);
      setActiveTab("graph");
    } catch (err) {
      setGraph(null);
    } finally {
      setGraphLoading(false);
    }
  }

  const foundHits = useMemo(() => (result?.hits || []).filter((h) => h.status.toLowerCase() === "found"), [result]);
  const missingCount = useMemo(
    () => (result?.hits || []).filter((h) => h.status.toLowerCase() === "not found").length,
    [result],
  );
  const errorCount = useMemo(
    () => (result?.hits || []).filter((h) => h.status.toLowerCase() === "error").length,
    [result],
  );
  // Filtro local: estado + texto (plataforma/nome/categoria), para não obrigar a
  // repetir o scan quando só se quer encontrar um cartão.
  const filteredHits = useMemo(() => {
    const hits = result?.hits || [];
    const byStatus = hits.filter((h) => {
      const status = h.status.toLowerCase();
      if (hitFilter === "found") return status === "found";
      if (hitFilter === "missing") return status === "not found";
      if (hitFilter === "error") return status === "error";
      return true;
    });
    const query = hitQuery.trim().toLowerCase();
    if (!query) return byStatus;
    return byStatus.filter((h) =>
      [h.site_name, h.category, h.profile?.display_name, h.profile?.bio]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [result, hitFilter, hitQuery]);
  const graphData = useMemo(() => toStudioGraph(graph || result?.graph), [graph, result]);

  async function exportCurrent(format: "json" | "csv" | "pdf") {
    const docId = result?.saved_id;
    if (!docId) return;
    try {
      await downloadReport(docId, format);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white shadow-lg shadow-violet-500/25">
            <Scan size={20} />
          </div>
          <div>
            <h1 className="text-lg font-semibold">OSINT</h1>
            <p className="text-sm text-muted-foreground">Pesquisa de usernames e emails em plataformas com user-scanner</p>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="mb-4">
            <TabsTrigger value="scan" active={activeTab === "scan"} onClick={() => setActiveTab("scan")}>Novo scan</TabsTrigger>
            <TabsTrigger value="results" active={activeTab === "results"} onClick={() => setActiveTab("results")}>Resultado atual</TabsTrigger>
            <TabsTrigger value="graph" active={activeTab === "graph"} onClick={() => setActiveTab("graph")}>Grafo</TabsTrigger>
            <TabsTrigger value="saved" active={activeTab === "saved"} onClick={() => setActiveTab("saved")}>Guardados</TabsTrigger>
          </TabsList>

          <TabsContent value="scan" active={activeTab === "scan"} className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Search size={16} /> Novo scan
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={runScan} className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
                    <div className="space-y-2">
                      <Label htmlFor="osint-target">Alvo</Label>
                      <Input
                        id="osint-target"
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                        placeholder={kind === "email" ? "nome@email.com" : kind === "nif" ? "500189412" : "username"}
                        autoComplete="off"
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Tipo de alvo</Label>
                      <div className="flex rounded-xl border p-1">
                        {([
                          { id: "username", label: "Username", icon: <User size={14} /> },
                          { id: "email", label: "Email", icon: <Mail size={14} /> },
                          { id: "nif", label: "NIF", icon: <Building2 size={14} /> },
                        ] as const).map((option) => (
                          <button
                            key={option.id}
                            type="button"
                            onClick={() => setKind(option.id)}
                            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
                              kind === option.id ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            {option.icon} {option.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {isNif ? (
                    <p className="text-sm text-muted-foreground">
                      O NIF é validado (dígito de controlo) e cruzado com os dados internos: contribuintes,
                      contratos, societário, CIRE, cadastro e ontologia.
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Label>Categorias a varrer</Label>
                        <div className="flex items-center gap-2 text-xs">
                          <button
                            type="button"
                            onClick={() => { setSelected([]); setFullScan(false); }}
                            className={`rounded-full border px-2.5 py-1 transition ${!selected.length && !fullScan ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                          >
                            Recomendada ({defaultCategory ?? "—"})
                          </button>
                          <button
                            type="button"
                            onClick={() => { setSelected([...availableCategories]); setFullScan(false); }}
                            className={`rounded-full border px-2.5 py-1 transition ${selected.length === availableCategories.length && availableCategories.length > 0 ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                          >
                            Todas
                          </button>
                          <button
                            type="button"
                            onClick={() => { setSelected([]); setFullScan(false); }}
                            className="rounded-full border px-2.5 py-1 text-muted-foreground transition hover:text-foreground"
                          >
                            Limpar
                          </button>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-1.5">
                        {availableCategories.map((name) => {
                          const isOn = selected.includes(name);
                          const count = platformCounts[name];
                          return (
                            <button
                              key={name}
                              type="button"
                              onClick={() => { setFullScan(false); toggleCategory(name); }}
                              title={count ? `${count} plataformas` : undefined}
                              className={`rounded-full border px-3 py-1 text-xs transition ${
                                isOn
                                  ? "border-violet-400 bg-violet-500/15 text-foreground"
                                  : "border-border text-muted-foreground hover:border-violet-300 hover:text-foreground"
                              }`}
                            >
                              {isOn && <Check size={11} className="mr-1 inline" />}
                              {name}
                              {count ? <span className="ml-1.5 opacity-60">{count}</span> : null}
                            </button>
                          );
                        })}
                      </div>

                      {(categories.presets || []).length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs text-muted-foreground">Predefinições:</span>
                          {(categories.presets || []).map((preset) => (
                            <button
                              key={preset.id}
                              type="button"
                              onClick={() => applyPreset(preset)}
                              title={preset.hint}
                              className="rounded-full border border-dashed px-3 py-1 text-xs text-muted-foreground transition hover:border-violet-300 hover:text-foreground"
                            >
                              {preset.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {!isNif && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/40 px-4 py-3">
                      <div className="text-xs text-muted-foreground">
                        {fullScan ? (
                          <span className="font-medium text-amber-600">
                            Varredura completa: todas as {Object.keys(platformCounts).length} categorias.
                          </span>
                        ) : (
                          <>
                            Vai verificar{" "}
                            <strong className="text-foreground">{plannedPlatforms.toLocaleString("pt-PT")}</strong>{" "}
                            plataformas em{" "}
                            <strong className="text-foreground">
                              {(selected.length || (fullScan ? 0 : 1)) === 1
                                ? "1 categoria"
                                : `${selected.length} categorias`}
                            </strong>
                            {" · estimativa ~"}
                            {estimateSeconds >= 60
                              ? `${Math.round(estimateSeconds / 60)} min`
                              : `${estimateSeconds} s`}
                          </>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <label className="flex items-center gap-2 text-xs text-muted-foreground">
                          <input
                            type="checkbox"
                            checked={fullScan}
                            onChange={(e) => {
                              setFullScan(e.target.checked);
                              if (e.target.checked) setSelected([]);
                            }}
                          />
                          Todas as plataformas
                        </label>
                        <Button type="submit" disabled={loading || !target.trim()} className="gap-2">
                          {loading ? <Loader2 size={16} className="animate-spin" /> : <Scan size={16} />}
                          {loading ? "A pesquisar…" : "Pesquisar"}
                        </Button>
                      </div>
                    </div>
                  )}

                  {isNif && (
                    <div className="flex justify-end">
                      <Button type="submit" disabled={loading || !target.trim()} className="gap-2">
                        {loading ? <Loader2 size={16} className="animate-spin" /> : <Scan size={16} />}
                        {loading ? "A recolher…" : "Recolher dados"}
                      </Button>
                    </div>
                  )}
                </form>
              </CardContent>
            </Card>

            {error && (
              <div className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
                {error}
              </div>
            )}

            {result && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      {result.kind === "email" ? <Mail size={16} /> : result.kind === "nif" ? <Building2 size={16} /> : <User size={16} />}
                      {result.target}
                    </span>
                    <div className="flex gap-2 text-sm font-normal">
                      <Badge variant="outline">
                        {result.kind === "nif" ? `${result.total} fontes internas` : `${result.total} sites`}
                      </Badge>
                      <Badge className="bg-emerald-600">{result.found} com dados</Badge>
                      {result.kind !== "nif" && (
                        <Badge variant="secondary">{result.not_found} não encontrados</Badge>
                      )}
                      {result.errors > 0 && <Badge variant="danger">{result.errors} erros</Badge>}
                    </div>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
                    <span>
                      {result.kind === "nif" ? (
                        <>
                          NIF validado: <strong>{result.stats?.nif_valid ? "sim" : "não"}</strong> ·
                        </>
                      ) : (
                        <>
                          Categorias:{" "}
                          <strong>
                            {(result.categories || []).length
                              ? (result.categories || []).join(", ")
                              : result.category || "completa"}
                          </strong>{" "}
                          ·
                        </>
                      )}{" "}
                      Duração: {result.duration_s ?? "—"} s · Guardado: {result.saved ? "sim" : "não"}
                    </span>
                    {result.saved_id && (
                      <span className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => exportCurrent("json")}>JSON</Button>
                        <Button size="sm" variant="outline" onClick={() => exportCurrent("csv")}>CSV</Button>
                        <Button size="sm" variant="outline" onClick={() => exportCurrent("pdf")}>PDF</Button>
                      </span>
                    )}
                  </div>

                  {Object.keys(result.platforms_per_category || {}).length > 1 && (
                    <div className="flex flex-wrap gap-1.5 text-[11px]">
                      {Object.entries(result.platforms_per_category || {}).map(([name, count]) => (
                        <span key={name} className="rounded-full border px-2 py-0.5 text-muted-foreground">
                          {name}: {count}
                        </span>
                      ))}
                    </div>
                  )}

                  {result.kind === "nif" && result.stats && (
                    <div className="flex flex-wrap gap-2 text-xs">
                      <Badge variant="outline">{result.stats.platforms_found} fontes com dados</Badge>
                      {(result.stats.people || []).length > 0 && (
                        <Badge className="bg-indigo-600">{(result.stats.people || []).length} pessoas</Badge>
                      )}
                      {(result.stats.related || []).length > 0 && (
                        <Badge className="bg-fuchsia-600">{(result.stats.related || []).length} entidades ligadas</Badge>
                      )}
                      {(result.stats.aliases || []).length > 0 && (
                        <Badge variant="secondary">{(result.stats.aliases || []).length} nomes alternativos</Badge>
                      )}
                    </div>
                  )}

                  {foundHits.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Nenhum perfil encontrado nesta pesquisa.{(result.errors || 0) > 0 && (
                        <span className="ml-1">
                          Houve {result.errors} plataformas que não responderam — voltar a tentar pode dar mais resultados.
                        </span>
                      )}
                    </p>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {foundHits.map((h) => (
                        <ProfileCard key={h.site_name} hit={h} />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {result && <LeadsCard hits={foundHits} />}
            {result && <PivotList pivots={result.pivots || []} />}
          </TabsContent>

          <TabsContent value="results" active={activeTab === "results"} className="space-y-4">
            {!result ? (
              <p className="text-sm text-muted-foreground">Ainda não foi executado nenhum scan.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/40 px-4 py-3">
                  <Input
                    value={hitQuery}
                    onChange={(e) => setHitQuery(e.target.value)}
                    placeholder="Filtrar por plataforma, nome, categoria…"
                    className="h-9 max-w-xs"
                    autoComplete="off"
                  />
                  <div className="flex gap-1">
                    {([
                      { id: "found", label: `Encontrados (${foundHits.length})` },
                      { id: "missing", label: `Sem perfil (${missingCount})` },
                      { id: "error", label: `Erros (${errorCount})` },
                      { id: "all", label: `Todos (${result.hits.length})` },
                    ] as const).map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => setHitFilter(option.id)}
                        className={`rounded-full border px-3 py-1 text-xs transition ${
                          hitFilter === option.id
                            ? "border-violet-400 bg-violet-500/15 text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <span className="ml-auto text-xs text-muted-foreground">
                    a mostrar {filteredHits.length}
                  </span>
                </div>

                {filteredHits.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nada corresponde ao filtro.</p>
                ) : hitFilter === "found" ? (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {filteredHits.map((h) => <ProfileCard key={`found-${h.site_name}`} hit={h} />)}
                  </div>
                ) : (
                  <Card>
                    <CardContent className="space-y-1 pt-4 text-xs text-muted-foreground">
                      {filteredHits.slice(0, 300).map((h) => (
                        <div key={`${h.site_name}-${h.status}`} className="flex items-center justify-between gap-2">
                          <span>{h.site_name} · {h.category}</span>
                          <Badge variant={h.status.toLowerCase() === "error" ? "danger" : "secondary"} className="text-[10px]">
                            {h.status}
                          </Badge>
                        </div>
                      ))}
                      {filteredHits.length > 300 && (
                        <p className="pt-2">A mostrar 300 de {filteredHits.length}.</p>
                      )}
                    </CardContent>
                  </Card>
                )}

                <LeadsCard hits={result.hits} />
                <PivotList pivots={result.pivots || []} />
              </>
            )}
          </TabsContent>

          <TabsContent value="graph" active={activeTab === "graph"} className="space-y-4">
            {graphLoading && <div className="flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin" /> A carregar grafo…</div>}
            {!graphData ? (
              <p className="text-sm text-muted-foreground">Sem grafo para mostrar. Execute um scan ou selecione um resultado guardado.</p>
            ) : (
              <Card className="overflow-hidden">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base"><Network size={16} /> Grafo de plataformas</CardTitle>
                </CardHeader>
                <CardContent>
                  <GraphCanvas
                    graph={graphData}
                    layout="network"
                    metric="contratos"
                    unitLabel="ligações"
                    heightClass="h-[520px]"
                    nodeSummary={(node) => {
                      const n = node as unknown as OsintGraphNode & { count?: number };
                      return `${n.label} · ${n.group}${n.details ? " · " + n.details : ""}`;
                    }}
                    edgeSummary={(edge) => `Ligação · ${(edge as unknown as { label?: string }).label || ""}`}
                    onNodeClick={(node) => {
                      const url = (node as unknown as { url?: string }).url;
                      if (url && typeof window !== "undefined") window.open(url, "_blank", "noopener,noreferrer");
                    }}
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="saved" active={activeTab === "saved"} className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Pesquisar scans guardados</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-2">
                    <Label>Alvo / nome / email / site</Label>
                    <Input
                      value={searchQ}
                      onChange={(e) => setSearchQ(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") loadSaved(); }}
                      placeholder="username, empresa, email, plataforma…"
                      autoComplete="off"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Tipo</Label>
                    <select className="h-10 rounded-md border bg-background px-3 text-sm" value={searchKind} onChange={(e) => setSearchKind(e.target.value as OsintKind | "")}>
                      <option value="">Todos</option>
                      <option value="username">Username</option>
                      <option value="email">Email</option>
                      <option value="nif">NIF</option>
                    </select>
                  </div>
                  <Button onClick={loadSaved} disabled={searchLoading} className="gap-2">
                    {searchLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />} Pesquisar
                  </Button>
                  {searchResult && (
                    <span className="pb-2 text-xs text-muted-foreground">
                      {searchResult.total} resultado{searchResult.total === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>

            {searchResult?.error && (
              <div className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">{searchResult.error}</div>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(searchResult?.items || []).map((item) => (
                <Card key={item.id} className="p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-medium">
                      {item.kind === "email" ? <Mail size={14} /> : <User size={14} />}
                      {item.target}
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => showGraph(item.id)} title="Ver grafo">
                        <Network size={14} />
                      </Button>
                      <Button size="sm" variant="ghost" className="text-destructive" onClick={() => deleteScan(item.id)} title="Apagar">
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">{item.kind} · {item.category || "padrão"}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline">{item.total} sites</Badge>
                    <Badge className="bg-emerald-600">{item.found} encontrados</Badge>
                    {(item.pivots || 0) > 0 && <Badge className="bg-fuchsia-600">{item.pivots} cruzadas</Badge>}
                    {(item.emails || []).length > 0 && <Badge className="bg-sky-600">{(item.emails || []).length} emails</Badge>}
                  </div>
                  {(item.names || []).length > 0 && (
                    <div className="mt-2 text-xs">Nomes: <strong>{(item.names || []).slice(0, 3).join(", ")}</strong></div>
                  )}
                  {item.top_sites.length > 0 && (
                    <div className="mt-2 text-xs text-muted-foreground">{item.top_sites.slice(0, 5).join(", ")}</div>
                  )}
                  {(item.emails || []).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {(item.emails || []).slice(0, 3).map((email) => (
                        <Badge key={email} className="bg-sky-600 text-[10px]">{email}</Badge>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap gap-1">
                    <Button size="sm" variant="outline" onClick={() => downloadReport(item.id, "json")}>JSON</Button>
                    <Button size="sm" variant="outline" onClick={() => downloadReport(item.id, "csv")}>CSV</Button>
                    <Button size="sm" variant="outline" onClick={() => downloadReport(item.id, "pdf")}>PDF</Button>
                  </div>
                  {item.scanned_at && <div className="mt-2 text-[11px] text-muted-foreground">{new Date(item.scanned_at).toLocaleString("pt-PT")}</div>}
                </Card>
              ))}
            </div>
            {(searchResult?.total || 0) > (searchResult?.items?.length || 0) && (
              <p className="text-sm text-muted-foreground">A mostrar {searchResult?.items.length} de {searchResult?.total} resultados.</p>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
