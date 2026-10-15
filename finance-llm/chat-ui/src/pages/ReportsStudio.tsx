/**
 * Página **Estúdio de relatórios** — área de criação (administradores e gestores).
 *
 * Fluxo, todo na mesma página:
 *  1. **modelo** (`Modelos`) — parte de um relatório já montado ou de uma folha
 *     em branco;
 *  2. **blocos** — secções, texto, indicadores, gráficos, tabelas, grafos e
 *     texto com IA, sobre as **fontes** de dados da plataforma;
 *  3. **pré-visualizar** — os números são calculados pelas mesmas agregações das
 *     páginas (nunca inventados no cliente);
 *  4. **PDF** — gerado no servidor com o logótipo e o rodapé da plataforma;
 *  5. **publicar** — no catálogo da plataforma (*site*) ou na loja, com preço. O
 *     PDF passa a ser entregue automaticamente a quem compra.
 *
 * O acesso é validado pela API (`/reports/studio/me`): quem não for
 * administrador nem gestor de relatórios não vê sequer o separador.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  Copy,
  FileText,
  LayoutTemplate,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  ShoppingBag,
  Sparkles,
  Store,
  Trash2,
  Wand2,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui";
import { BlockCard, BlockPreview, StudioGraph } from "../components/reports/StudioPreview";
import { StudioBlockEditor } from "../components/reports/StudioBlockEditor";
import {
  createStudioReport,
  deleteStudioFile,
  deleteStudioReport,
  downloadStudioFile,
  duplicateStudioReport,
  generateStudioPdf,
  getStudioMe,
  getStudioReport,
  getStudioSources,
  getStudioState,
  getStudioTemplates,
  listStudioReports,
  publishStudioReport,
  runStudioDraft,
  saveStudioReport,
  studioAssist,
  studioBytes,
  studioDate,
  studioMoney,
  studioReportAssist,
  unpublishStudioReport,
  type StudioAccess,
  type StudioBlock,
  type StudioReport,
  type StudioRun,
  type StudioRunBlock,
  type StudioSources,
  type StudioState,
  type StudioTemplate,
} from "../reportsStudioApi";

type Toast = { message: string; tone: "info" | "ok" | "error" };

const BLOCK_ORDER: StudioBlock["type"][] = ["heading", "text", "note", "ai", "kpi", "chart", "table", "graph", "empresa", "web"];

const BLOCK_BUTTONS: Record<string, string> = {
  heading: "Secção",
  text: "Texto",
  note: "Nota",
  ai: "Texto IA",
  kpi: "Indicadores",
  chart: "Gráfico",
  table: "Tabela",
  graph: "Grafo",
  empresa: "Ficha da empresa",
  web: "Produtos/serviços (web)",
};

function newBlock(type: StudioBlock["type"], sources: StudioSources | null): StudioBlock {
  const source = sources?.sources?.[0];
  const block: StudioBlock = {
    id: `blk-${Math.random().toString(36).slice(2, 10)}`,
    type,
    title: "",
    text: "",
    prompt: "",
    source: "",
    dimensions: [],
    measures: [],
    filters: "",
    search: "",
    chart: "bar",
    limit: 12,
    top_n: 0,
    width: 12,
    format: "",
    empresa: "",
    query: "",
    site: "",
  };
  if (type === "heading") block.title = "Nova secção";
  if (type === "empresa") {
    block.title = "Ficha da empresa";
    block.empresa = "{{empresa}}";
    block.limit = 12;
  }
  if (type === "web") {
    block.title = "Produtos e serviços (pesquisa web)";
    block.query = "{{nome}} produtos e serviços";
    block.limit = 5;
  }
  if (["kpi", "chart", "table", "graph"].includes(type) && source) {
    block.source = source.id;
    block.title = source.label;
    const dimension = String(source.defaults?.dimension || source.dimensions?.[0]?.id || "");
    const measure = String(source.defaults?.measure || source.measures?.[0]?.id || "");
    if (type !== "kpi" && dimension) block.dimensions = [dimension];
    if (measure) block.measures = [measure];
    if (type === "graph") {
      const second = source.dimensions?.find((item) => item.id !== dimension)?.id;
      block.dimensions = [dimension, second || dimension].filter(Boolean) as string[];
      block.limit = 20;
    }
  }
  if (type === "ai") block.prompt = "Escreve o texto desta secção a partir dos dados do relatório.";
  return block;
}

export function ReportsStudioTab({ onError, onToast }: { onError: (message: string | null) => void; onToast?: (toast: Toast) => void }) {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [access, setAccess] = useState<StudioAccess | null>(null);
  const [state, setState] = useState<StudioState | null>(null);
  const [sources, setSources] = useState<StudioSources | null>(null);
  const [templates, setTemplates] = useState<StudioTemplate[]>([]);
  const [reports, setReports] = useState<StudioReport[]>([]);
  const [draft, setDraft] = useState<StudioReport | null>(null);
  const [dirty, setDirty] = useState(false);
  const [run, setRun] = useState<StudioRun | null>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<"blocos" | "preview" | "publicar" | "pdf" | "ia">("blocos");
  const [openBlock, setOpenBlock] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [aiText, setAiText] = useState("");
  const [aiNotes, setAiNotes] = useState<string[]>([]);
  const [publishForm, setPublishForm] = useState({
    price: "0",
    list_price: "0",
    target: "site" as "site" | "loja" | "todos",
    delivery_days: "1",
    max_targets: "1",
    badge: "",
    short_description: "",
    targets_note: "",
  });

  const notify = useCallback(
    (message: string, tone: Toast["tone"] = "info") => {
      onToast?.({ message, tone });
    },
    [onToast],
  );

  const load = useCallback(async () => {
    setLoading(true);
    onError(null);
    try {
      const [me, info, catalog, models, listing] = await Promise.all([
        getStudioMe(),
        getStudioState(),
        getStudioSources(),
        getStudioTemplates(),
        listStudioReports(),
      ]);
      setAccess(me);
      setState(info);
      setSources(catalog);
      setTemplates(models.templates);
      setReports(listing.items);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const sourceOptions = useMemo(() => sources?.sources ?? [], [sources]);
  const chartTypes = useMemo(() => {
    const known = ["bar", "bar-h", "line", "area", "donut", "pie"];
    return (sources?.chart_types ?? []).filter((item) => known.includes(item.id));
  }, [sources]);

  const blockResults = useMemo(() => {
    const map = new Map<string, StudioRunBlock>();
    for (const block of run?.blocks ?? []) map.set(block.id, block);
    return map;
  }, [run]);

  async function refreshList() {
    const listing = await listStudioReports();
    setReports(listing.items);
  }

  async function openReport(id: string) {
    setBusy(true);
    onError(null);
    try {
      const report = await getStudioReport(id);
      setDraft(report);
      setDirty(false);
      setRun(null);
      setTab("blocos");
      setPublishForm((current) => ({
        ...current,
        price: String(report.publication?.site?.price || report.publication?.loja?.price || 0),
        list_price: String(report.publication?.site?.list_price || 0),
      }));
      await preview(report);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function createFromTemplate(templateId: string) {
    setBusy(true);
    onError(null);
    try {
      const created = await createStudioReport({ template: templateId });
      await refreshList();
      setDraft(created.report);
      setDirty(false);
      setTab("blocos");
      setOpenBlock(created.report.blocks[0]?.id ?? null);
      if (created.warnings?.length) notify(`${created.warnings.length} bloco(s) do modelo não se aplicam às fontes atuais.`, "info");
      await preview(created.report);
      notify("Relatório criado.", "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function preview(report: StudioReport | null = draft) {
    if (!report) return;
    if (!report.blocks.length) {
      // Um relatório ainda sem blocos não tem nada para calcular.
      setRun(null);
      return;
    }
    setRunning(true);
    try {
      const result = await runStudioDraft({
        report: {
          title: report.title,
          subtitle: report.subtitle,
          description: report.description,
          summary: report.summary,
          template: report.template,
          vars: report.vars ?? {},
          blocks: report.blocks,
        },
      });
      setRun(result);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  function patchDraft(patch: Partial<StudioReport>) {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setDirty(true);
  }

  function patchBlock(blockId: string, patch: Partial<StudioBlock>) {
    setDraft((current) =>
      current
        ? { ...current, blocks: current.blocks.map((block) => (block.id === blockId ? { ...block, ...patch } : block)) }
        : current,
    );
    setDirty(true);
  }

  function addBlock(type: StudioBlock["type"]) {
    if (!draft) return;
    const block = newBlock(type, sources);
    patchDraft({ blocks: [...draft.blocks, block] });
    setOpenBlock(block.id);
  }

  function removeBlock(blockId: string) {
    if (!draft) return;
    patchDraft({ blocks: draft.blocks.filter((block) => block.id !== blockId) });
  }

  function moveBlock(blockId: string, direction: -1 | 1) {
    if (!draft) return;
    const index = draft.blocks.findIndex((block) => block.id === blockId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= draft.blocks.length) return;
    const blocks = [...draft.blocks];
    [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
    patchDraft({ blocks });
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    onError(null);
    try {
      const saved = await saveStudioReport(draft.id, {
        title: draft.title,
        subtitle: draft.subtitle,
        description: draft.description,
        summary: draft.summary,
        tags: draft.tags,
        targets_note: draft.targets_note,
        vars: draft.vars ?? {},
        blocks: draft.blocks,
      });
      setDraft(saved.report);
      setDirty(false);
      await refreshList();
      if (saved.warnings?.length) notify(`${saved.warnings.length} bloco(s) retirado(s): ${saved.warnings[0]}`, "error");
      else notify("Relatório gravado.", "ok");
      await preview(saved.report);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!draft) return;
    if (!window.confirm(`Apagar o relatório «${draft.title}»?`)) return;
    setBusy(true);
    try {
      await deleteStudioReport(draft.id);
      setDraft(null);
      setRun(null);
      await refreshList();
      notify("Relatório apagado.", "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function duplicate() {
    if (!draft) return;
    setBusy(true);
    try {
      const clone = await duplicateStudioReport(draft.id);
      await refreshList();
      setDraft(clone.report);
      setDirty(false);
      notify("Cópia criada.", "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function buildPdf() {
    if (!draft) return;
    setBusy(true);
    onError(null);
    try {
      if (dirty) await save();
      const result = await generateStudioPdf(draft.id);
      setDraft(result.report);
      setDirty(false);
      notify(`PDF gerado (${studioBytes(result.file.size)}).`, "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!draft) return;
    setBusy(true);
    onError(null);
    try {
      if (dirty) await save();
      const result = await publishStudioReport(draft.id, {
        target: publishForm.target,
        price: Number(publishForm.price) || 0,
        list_price: Number(publishForm.list_price) || 0,
        delivery_days: Number(publishForm.delivery_days) || 1,
        max_targets: Number(publishForm.max_targets) || 1,
        badge: publishForm.badge,
        short_description: publishForm.short_description,
        targets_note: publishForm.targets_note,
      });
      setDraft(result.report);
      await refreshList();
      notify(`Publicado (${result.target}). Preço ${studioMoney(Number(publishForm.price) || 0)}.`, "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function unpublish(target: "site" | "loja") {
    if (!draft) return;
    setBusy(true);
    try {
      const result = await unpublishStudioReport(draft.id, target);
      setDraft(result.report);
      await refreshList();
      notify(`Retirado de ${target}.`, "ok");
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function assist(mode: "sumario" | "texto" | "insights" | "blocos", blockId?: string) {
    setBusy(true);
    onError(null);
    try {
      let target = draft;
      if (!target) {
        const result = await studioAssist({ mode, source: sourceOptions[0]?.id });
        setAiText(result.text);
        setAiNotes([...(result.notes ?? []), ...(result.warnings ?? [])]);
        setTab("ia");
        return;
      }
      if (dirty) {
        // A IA trabalha sobre o relatório gravado: grava primeiro as alterações.
        const saved = await saveStudioReport(target.id, {
          title: target.title,
          subtitle: target.subtitle,
          description: target.description,
          summary: target.summary,
          tags: target.tags,
          targets_note: target.targets_note,
          blocks: target.blocks,
        });
        target = saved.report;
        setDraft(saved.report);
        setDirty(false);
        await refreshList();
      }
      const result = await studioReportAssist(target.id, {
        mode,
        block: blockId,
        prompt: target.blocks.find((item) => item.id === blockId)?.prompt,
      });
      setAiText(result.text);
      setAiNotes([...(result.notes ?? []), ...(result.warnings ?? [])]);
      setTab("ia");
      if (mode === "blocos" && result.blocks?.length) {
        patchDraft({ blocks: [...target.blocks, ...result.blocks] });
        notify(`${result.blocks.length} bloco(s) sugerido(s) juntos ao relatório.`, "ok");
      } else if (mode === "texto" && blockId) {
        patchBlock(blockId, { text: result.text });
        notify("Texto escrito no bloco.", "ok");
      }
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return reports;
    return reports.filter((item) => `${item.title} ${item.subtitle}`.toLowerCase().includes(needle));
  }, [filter, reports]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 size={16} className="animate-spin" /> A carregar o estúdio…
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
      {/* ------------------------------------------------------------ lista */}
      <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-80">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="text-sm">Modelos</CardTitle>
            <Badge variant="info">{templates.length}</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-[11px] text-muted-foreground">
              Comece por um modelo pronto ou por uma folha em branco. Os modelos trazem blocos já ligados às fontes.
            </p>
            <div className="grid gap-2">
              {templates.map((model) => (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => void createFromTemplate(model.id)}
                  disabled={busy}
                  className="rounded-xl border bg-background px-3 py-2 text-left transition hover:border-primary/60 hover:bg-accent/40 disabled:opacity-50"
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <LayoutTemplate size={13} /> {model.name}
                    <span className="ml-auto text-[10px] text-muted-foreground">{model.block_count} blocos</span>
                  </span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">{model.description}</span>
                  {model.warnings.length > 0 && (
                    <span className="mt-1 block text-[10px] text-amber-400">
                      {model.warnings.length} bloco(s) indisponível(is) com as fontes atuais
                    </span>
                  )}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="flex min-h-0 flex-1 flex-col">
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle className="text-sm">Relatórios</CardTitle>
            <Button variant="outline" size="sm" onClick={() => void refreshList()} title="Atualizar">
              <RefreshCw size={13} />
            </Button>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col gap-2">
            <Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Procurar…" autoComplete="off" />
            <div className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
              {filtered.length === 0 && <p className="py-3 text-xs text-muted-foreground">Ainda não há relatórios.</p>}
              {filtered.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void openReport(item.id)}
                  className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                    draft?.id === item.id ? "border-primary/60 bg-primary/10" : "bg-background hover:bg-accent/40"
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{item.title}</span>
                    <Badge variant={item.published ? "success" : "warning"}>{item.status_label}</Badge>
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{item.stats.blocks} blocos</span>
                    {item.stats.charts > 0 && <span>· {item.stats.charts} gráficos</span>}
                    {item.files.length > 0 && <span>· PDF</span>}
                  </span>
                  <span className="mt-0.5 block text-[10px] text-muted-foreground/70">{studioDate(item.updated_at)}</span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </aside>

      {/* ----------------------------------------------------------- editor */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        {!draft ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Estúdio de relatórios</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                Escolha um <strong>modelo</strong> à esquerda para montar um relatório novo. Pode juntar indicadores, gráficos,
                tabelas e grafos sobre as fontes da plataforma, pedir ajuda à IA, gerar o PDF e publicá-lo com preço.
              </p>
              <div className="flex flex-wrap gap-3 text-[11px]">
                <span className="flex items-center gap-1">
                  <FileText size={12} /> {state?.reports?.total ?? 0} relatórios
                </span>
                <span className="flex items-center gap-1">
                  <Check size={12} /> {state?.reports?.published ?? 0} publicados
                </span>
                <span className="flex items-center gap-1">
                  <Sparkles size={12} /> IA {state?.ai ? "disponível" : "sem modelo configurado"}
                </span>
                <span className="flex items-center gap-1">
                  <ShoppingBag size={12} /> {sources?.sources?.length ?? 0} fontes
                </span>
              </div>
              {sources?.problems?.length ? (
                <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                  <AlertCircle size={14} className="mt-0.5 shrink-0" /> {sources.problems[0]}
                </p>
              ) : null}
            </CardContent>
          </Card>
        ) : (
          <>
            <Card>
              <CardContent className="space-y-3 pt-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-2">
                    <Input
                      value={draft.title}
                      onChange={(event) => patchDraft({ title: event.target.value })}
                      placeholder="Título do relatório"
                      className="text-base font-semibold"
                      autoComplete="off"
                    />
                    <Input
                      value={draft.subtitle}
                      onChange={(event) => patchDraft({ subtitle: event.target.value })}
                      placeholder="Subtítulo (aparece no PDF)"
                      autoComplete="off"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={draft.published ? "success" : "warning"}>{draft.status_label}</Badge>
                    {draft.channels.map((channel) => (
                      <Badge key={channel} variant="info">
                        {channel === "site" ? "Plataforma" : "Loja"}
                      </Badge>
                    ))}
                    <Button variant="outline" size="sm" onClick={() => void preview()} loading={running} title="Recalcular">
                      <RefreshCw size={13} />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => void duplicate()} disabled={busy} title="Duplicar">
                      <Copy size={13} />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => void remove()} disabled={busy} title="Apagar">
                      <Trash2 size={13} />
                    </Button>
                    <Button size="sm" onClick={() => void save()} disabled={busy || !dirty} title="Guardar">
                      {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Guardar
                    </Button>
                  </div>
                </div>
                <textarea
                  value={draft.description}
                  onChange={(event) => patchDraft({ description: event.target.value })}
                  rows={2}
                  placeholder="Descrição curta (o que o relatório mostra)."
                  className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                />
                {(draft.vars_spec?.length ?? 0) > 0 && (
                  <div className="space-y-2 rounded-xl border bg-background/60 p-3">
                    <p className="text-xs font-semibold text-foreground/90">Parâmetros do relatório</p>
                    <p className="text-[11px] text-muted-foreground">
                      Os blocos usam estes parâmetros (<code>{"{{empresa}}"}</code>, <code>{"{{nif}}"}</code>, <code>{"{{cae}}"}</code>,{" "}
                      <code>{"{{cpv}}"}</code>, <code>{"{{nome}}"}</code>): para outro relatório, duplique este e mude só a empresa.
                    </p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {(draft.vars_spec ?? []).map((spec) => (
                        <div key={spec.id} className="space-y-1">
                          <Label htmlFor={`var-${spec.id}`}>{spec.label}</Label>
                          <Input
                            id={`var-${spec.id}`}
                            value={draft.vars?.[spec.id] ?? ""}
                            onChange={(event) => patchDraft({ vars: { ...(draft.vars ?? {}), [spec.id]: event.target.value } })}
                            placeholder={spec.id === "empresa" ? "504223933" : ""}
                            autoComplete="off"
                          />
                          {spec.hint ? <p className="text-[11px] text-muted-foreground">{spec.hint}</p> : null}
                        </div>
                      ))}
                    </div>
                    {run?.vars && run.vars.empresa ? (
                      <p className="text-[11px] text-muted-foreground">
                        Resolvido: {run.vars.nome || run.vars.empresa}
                        {run.vars.nif ? ` · NIF ${run.vars.nif}` : ""}
                        {run.vars.cae ? ` · CAE ${run.vars.cae}` : ""}
                        {run.vars.cpv ? ` · CPV ${run.vars.cpv}` : ""}
                      </p>
                    ) : null}
                  </div>
                )}
                <p className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <Badge variant="outline">{access?.role === "manager" ? "Gestor de plataforma" : access?.role === "admin" ? "Administrador" : "Gestor de relatórios"}</Badge>
                  <span>{access?.email}</span>
                  <span>· {state?.ai ? "IA disponível" : "IA sem modelo (texto factual)"}</span>
                  <span>· {state?.pdf ? "PDF ativo" : "PDF indisponível"}</span>
                  <span>· {sourceOptions.length} fontes</span>
                </p>
              </CardContent>
            </Card>

            <Tabs value={tab} onValueChange={(value) => setTab(value as typeof tab)} className="min-h-0 flex-1">
              <TabsList>
                <TabsTrigger value="blocos" active={tab === "blocos"} onClick={() => setTab("blocos")}>
                  Blocos ({draft.blocks.length})
                </TabsTrigger>
                <TabsTrigger value="preview" active={tab === "preview"} onClick={() => setTab("preview")}>
                  Pré-visualizar
                </TabsTrigger>
                <TabsTrigger value="ia" active={tab === "ia"} onClick={() => setTab("ia")}>
                  Assistente
                </TabsTrigger>
                <TabsTrigger value="publicar" active={tab === "publicar"} onClick={() => setTab("publicar")}>
                  Publicar
                </TabsTrigger>
                <TabsTrigger value="pdf" active={tab === "pdf"} onClick={() => setTab("pdf")}>
                  PDF {draft.files.length > 0 ? `(${draft.files.length})` : ""}
                </TabsTrigger>
              </TabsList>

              {/* ----------------------------------------------------- blocos */}
              <TabsContent value="blocos" active={tab === "blocos"} className="mt-3 space-y-3">
                <div className="flex flex-wrap gap-2">
                  {BLOCK_ORDER.map((type) => (
                    <Button key={type} variant="outline" size="sm" onClick={() => addBlock(type)} disabled={busy}>
                      <Plus size={12} /> {BLOCK_BUTTONS[type] ?? type}
                    </Button>
                  ))}
                </div>

                {draft.blocks.length === 0 && (
                  <p className="rounded-xl border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">
                    Sem blocos. Comece por <strong>Indicadores</strong> ou <strong>Gráfico</strong>.
                  </p>
                )}

                {draft.blocks.map((block, index) => {
                  const result = blockResults.get(block.id);
                  const open = openBlock === block.id;
                  return (
                    <div key={block.id} className="space-y-2">
                      <BlockCard
                        title={block.title || block.type}
                        type={block.type}
                        result={result}
                        running={running}
                        actions={
                          <Button variant="ghost" size="sm" onClick={() => setOpenBlock(open ? null : block.id)}>
                            {open ? "Fechar" : "Editar"}
                          </Button>
                        }
                      />
                      {open && (
                        <StudioBlockEditor
                          block={block}
                          index={index}
                          count={draft.blocks.length}
                          sources={sourceOptions}
                          limits={sources?.limits ?? { max_blocks: 60, max_dimensions: 3, max_measures: 6, max_kpi: 4, max_rows: 100, max_graph_edges: 40, max_text: 6000, widths: [12, 6, 4] }}
                          chartTypes={chartTypes}
                          onChange={(patch) => patchBlock(block.id, patch)}
                          onRemove={() => removeBlock(block.id)}
                          onMove={(direction) => moveBlock(block.id, direction)}
                          onAssist={() => void assist("texto", block.id)}
                          busy={busy}
                        />
                      )}
                    </div>
                  );
                })}
              </TabsContent>

              {/* -------------------------------------------------- preview */}
              <TabsContent value="preview" active={tab === "preview"} className="mt-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">
                    {run?.generated_at ? `Calculado a ${studioDate(run.generated_at)}` : "Ainda sem dados."}
                  </p>
                  <Button variant="outline" size="sm" onClick={() => void preview()} loading={running}>
                    <RefreshCw size={13} /> Recalcular
                  </Button>
                </div>
                {run?.problems?.length ? (
                  <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                    {run.problems.length} bloco(s) com problemas: {run.problems[0]}
                  </p>
                ) : null}
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <BookOpen size={16} /> {draft.title}
                    </CardTitle>
                    {draft.subtitle && <p className="text-sm text-muted-foreground">{draft.subtitle}</p>}
                  </CardHeader>
                  <CardContent className="space-y-5">
                    {draft.description && <p className="text-sm text-muted-foreground">{draft.description}</p>}
                    {draft.blocks.map((block) => {
                      const result = blockResults.get(block.id);
                      const width = block.width >= 12 ? "w-full" : block.width === 6 ? "sm:w-[calc(50%-0.5rem)] w-full" : "lg:w-[calc(33%-0.5rem)] w-full";
                      return (
                        <section key={block.id} className={width}>
                          {block.type === "heading" ? (
                            <h3 className="border-b pb-1 text-base font-semibold">{block.title}</h3>
                          ) : (
                            <h4 className="text-sm font-semibold">{block.title}</h4>
                          )}
                          {block.type === "graph" && result ? (
                            <StudioGraph block={result} />
                          ) : (
                            <BlockPreview block={{ title: block.title, type: block.type, text: block.text }} result={result} running={running} />
                          )}
                        </section>
                      );
                    })}
                  </CardContent>
                </Card>
              </TabsContent>

              {/* ------------------------------------------------------- ia */}
              <TabsContent value="ia" active={tab === "ia"} className="mt-3 space-y-3">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Wand2 size={14} /> Assistente de relatórios
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      A IA escreve a partir dos dados já calculados (nunca inventa números). Sem modelo configurado, a plataforma
                      devolve o texto montado com os indicadores e destaques.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" onClick={() => void assist("sumario")} disabled={busy}>
                        <Sparkles size={13} /> Sumário executivo
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => void assist("insights")} disabled={busy}>
                        Destaques dos dados
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => void assist("blocos")} disabled={busy}>
                        Sugerir blocos
                      </Button>
                    </div>
                    {aiNotes.length > 0 && (
                      <ul className="space-y-1 text-[11px] text-muted-foreground">
                        {aiNotes.map((note) => (
                          <li key={note}>· {note}</li>
                        ))}
                      </ul>
                    )}
                    <textarea
                      value={aiText}
                      onChange={(event) => setAiText(event.target.value)}
                      rows={10}
                      className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                      placeholder="O texto do assistente aparece aqui. Pode copiá-lo para um bloco de texto."
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={!aiText || !draft}
                        onClick={() => {
                          const block = newBlock("text", sources);
                          block.title = "Sumário executivo";
                          block.text = aiText;
                          patchDraft({ blocks: [...draft.blocks, block] });
                          notify("Texto juntado como bloco novo.", "ok");
                          setTab("blocos");
                        }}
                      >
                        <Plus size={13} /> Juntar como bloco de texto
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!aiText || !draft}
                        onClick={() => {
                          const aiBlock = draft.blocks.find((item) => item.type === "ai");
                          if (aiBlock) patchBlock(aiBlock.id, { text: aiText });
                          else {
                            const block = newBlock("ai", sources);
                            block.title = "Análise";
                            block.text = aiText;
                            patchDraft({ blocks: [...draft.blocks, block] });
                          }
                          notify("Texto do bloco de IA atualizado.", "ok");
                        }}
                      >
                        <Check size={13} /> Pôr no bloco de IA
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* -------------------------------------------------- publicar */}
              <TabsContent value="publicar" active={tab === "publicar"} className="mt-3 space-y-3">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Store size={14} /> Publicação e preço
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-xs text-muted-foreground">
                      No <strong>catálogo da plataforma</strong> o cliente pede o relatório como qualquer outro pacote. Na{" "}
                      <strong>loja</strong> entra como produto digital. Em ambos, o PDF é entregue automaticamente depois do pagamento.
                    </p>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="space-y-2">
                        <Label htmlFor="publish-target">Onde publicar</Label>
                        <select
                          id="publish-target"
                          value={publishForm.target}
                          onChange={(event) => setPublishForm((current) => ({ ...current, target: event.target.value as typeof current.target }))}
                          className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                        >
                          <option value="site">Plataforma (catálogo de relatórios)</option>
                          <option value="loja">Loja</option>
                          <option value="todos">Ambos</option>
                        </select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="publish-price">Preço (€)</Label>
                        <Input
                          id="publish-price"
                          type="number"
                          min={0}
                          step="0.01"
                          value={publishForm.price}
                          onChange={(event) => setPublishForm((current) => ({ ...current, price: event.target.value }))}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="publish-list">Preço antigo (€)</Label>
                        <Input
                          id="publish-list"
                          type="number"
                          min={0}
                          step="0.01"
                          value={publishForm.list_price}
                          onChange={(event) => setPublishForm((current) => ({ ...current, list_price: event.target.value }))}
                        />
                      </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="space-y-2">
                        <Label htmlFor="publish-days">Dias de entrega</Label>
                        <Input
                          id="publish-days"
                          type="number"
                          min={0}
                          value={publishForm.delivery_days}
                          onChange={(event) => setPublishForm((current) => ({ ...current, delivery_days: event.target.value }))}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="publish-targets">Empresas por pedido</Label>
                        <Input
                          id="publish-targets"
                          type="number"
                          min={1}
                          max={6}
                          value={publishForm.max_targets}
                          onChange={(event) => setPublishForm((current) => ({ ...current, max_targets: event.target.value }))}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="publish-badge">Etiqueta</Label>
                        <Input
                          id="publish-badge"
                          value={publishForm.badge}
                          onChange={(event) => setPublishForm((current) => ({ ...current, badge: event.target.value }))}
                          placeholder="NOVO"
                          autoComplete="off"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="publish-short">Descrição curta (loja)</Label>
                      <Input
                        id="publish-short"
                        value={publishForm.short_description}
                        onChange={(event) => setPublishForm((current) => ({ ...current, short_description: event.target.value }))}
                        placeholder={draft.subtitle || draft.description || "Resumo de uma linha."}
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="publish-note">Nota do relatório (catálogo)</Label>
                      <textarea
                        id="publish-note"
                        value={publishForm.targets_note}
                        onChange={(event) => setPublishForm((current) => ({ ...current, targets_note: event.target.value }))}
                        rows={2}
                        className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                        placeholder="Aparece no fim do PDF (método, limites, fontes)."
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <Button onClick={() => void publish()} disabled={busy}>
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <Store size={14} />} Publicar
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        Vai a {studioMoney(Number(publishForm.price) || 0)} · entrega em {publishForm.delivery_days} dia(s)
                      </span>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      {(["site", "loja"] as const).map((channel) => {
                        const info = draft.publication?.[channel];
                        return (
                          <div key={channel} className="rounded-xl border bg-background p-3">
                            <p className="flex items-center justify-between text-sm font-medium">
                              {channel === "site" ? "Plataforma" : "Loja"}
                              <Badge variant={info?.published ? "success" : "outline"}>{info?.published ? "Publicado" : "Rascunho"}</Badge>
                            </p>
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              {info?.published
                                ? `${studioMoney(info.price)} · ${studioDate(info.at)} · ${info.by || "—"}`
                                : "Ainda não publicado neste canal."}
                            </p>
                            {info?.published && (
                              <Button variant="outline" size="sm" className="mt-2" onClick={() => void unpublish(channel)} disabled={busy}>
                                Retirar
                              </Button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              {/* ------------------------------------------------------- pdf */}
              <TabsContent value="pdf" active={tab === "pdf"} className="mt-3 space-y-3">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <FileText size={14} /> PDF do relatório
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      O PDF é montado no servidor com o logótipo, os gráficos, as tabelas, os grafos e o rodapé da plataforma. É este
                      ficheiro que o cliente recebe depois de pagar.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void buildPdf()} disabled={busy}>
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />} Gerar PDF
                      </Button>
                      <Button variant="outline" onClick={() => void preview()} loading={running}>
                        <RefreshCw size={14} /> Recalcular dados
                      </Button>
                    </div>
                    {draft.files.length === 0 ? (
                      <p className="rounded-xl border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">
                        Ainda não há PDF gerado.
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {draft.files.map((file) => (
                          <li key={file.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2">
                            <span className="min-w-0">
                              <span className="block truncate text-sm">{file.name}</span>
                              <span className="text-[11px] text-muted-foreground">
                                {studioBytes(file.size)} · {studioDate(file.created_at)}
                              </span>
                            </span>
                            <span className="flex gap-2">
                              <Button variant="outline" size="sm" onClick={() => void downloadStudioFile(draft.id, file.id, file.name)}>
                                Descarregar
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                  try {
                                    const result = await deleteStudioFile(draft.id, file.id);
                                    setDraft(result.report);
                                    notify("PDF removido.", "ok");
                                  } catch (err) {
                                    onError((err as Error).message);
                                  }
                                }}
                              >
                                <Trash2 size={13} />
                              </Button>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </div>
  );
}

/** Verificação de acesso: quem não é administrador/gestor não vê o separador. */
export async function studioAvailable(): Promise<boolean> {
  try {
    const me = await getStudioMe();
    return Boolean(me.studio);
  } catch {
    return false;
  }
}

export default ReportsStudioTab;
