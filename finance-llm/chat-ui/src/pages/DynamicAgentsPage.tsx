/**
 * Construtor visual de agentes dinâmicos do IQ OS.
 *
 * Permite criar, editar e executar agentes LangGraph configuráveis (tools,
 * prompts, RAG, nós/edges personalizados). A interface segue o padrão das
 * outras aplicações do IQ OS: cabeçalho compacto, painéis em glass-card e
 * layout responsável por container query.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  BrainCircuit,
  Check,
  ChevronRight,
  Copy,
  Download,
  Edit3,
  Loader2,
  MessageSquare,
  Network,
  FileText,
  Play,
  Plus,
  Save,
  Search,
  Send,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X,
  Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "../auth";
import { useWindowMode } from "../layout";
import {
  type AgentConfig,
  type AgentGraphDefinition,
  type AgentGraphEdge,
  type AgentGraphNode,
  type AgentRunResponse,
  type AgentRunStep,
  type AgentToolRef,
  type ToolCatalogItem,
  deleteAgentConfig,
  fetchToolsCatalog,
  listAgentConfigs,
  runAgent,
  saveAgentConfig,
  streamAgent,
} from "../agentsApi";

interface DynamicAgentsPageProps {
  onSwitchView: () => void;
}

const BACKENDS = [
  { id: "openai", label: "OpenAI" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "xai", label: "xAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "google", label: "Google" },
  { id: "groq", label: "Groq" },
  { id: "mistral", label: "Mistral AI" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "ollama", label: "Ollama" },
];

const RAG_MODES = [
  { id: "", label: "Desligado" },
  { id: "dense", label: "Denso" },
  { id: "hybrid", label: "Híbrido" },
  { id: "hybrid_rerank", label: "Híbrido + rerank" },
  { id: "crag", label: "CRAG" },
  { id: "crag_rerank", label: "CRAG + rerank" },
];

const NODE_KINDS: { id: AgentGraphNode["kind"]; label: string; color: string }[] = [
  { id: "prompt", label: "Prompt", color: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  { id: "tool", label: "Tool", color: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
  { id: "rag", label: "RAG", color: "bg-teal-500/20 text-teal-300 border-teal-500/30" },
  { id: "conditional", label: "Condicional", color: "bg-purple-500/20 text-purple-300 border-purple-500/30" },
  { id: "supervisor", label: "Supervisor", color: "bg-rose-500/20 text-rose-300 border-rose-500/30" },
  { id: "output", label: "Output", color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
];

const inputClass =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-teal-400/50 focus:outline-none focus:ring-2 focus:ring-teal-400/20";

const selectClass =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:border-teal-400/50 focus:outline-none focus:ring-2 focus:ring-teal-400/20";

const btnBase =
  "inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-teal-400/20 disabled:opacity-50 disabled:cursor-not-allowed";

const textareaClass =
  "min-h-[96px] w-full resize-y rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-teal-400/50 focus:outline-none focus:ring-2 focus:ring-teal-400/20";

function emptyGraph(): AgentGraphDefinition {
  return { nodes: [], edges: [] };
}

function emptyAgent(): AgentConfig {
  return {
    agent_id: "",
    name: "Novo agente",
    description: "",
    icon: "Bot",
    tags: [],
    backend: "openai",
    model: "",
    temperature: 0.2,
    max_tokens: 1024,
    system_prompt: "",
    graph: emptyGraph(),
    tools: [],
    rag_index: "",
    rag_mode: null,
    enabled: true,
    is_public: false,
  };
}

function generateId(prefix = "id"): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function classNames(...args: (string | false | null | undefined)[]): string {
  return args.filter(Boolean).join(" ");
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

export default function DynamicAgentsPage({ onSwitchView }: DynamicAgentsPageProps) {
  const { windowMode } = useWindowMode();
  const { user } = useAuth();

  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [selected, setSelected] = useState<AgentConfig | null>(null);
  const [draft, setDraft] = useState<AgentConfig>(emptyAgent());
  const [catalog, setCatalog] = useState<ToolCatalogItem[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [activeTab, setActiveTab] = useState<"editor" | "graph" | "run" | "json">("editor");
  const [runInput, setRunInput] = useState("");
  const [runResponse, setRunResponse] = useState<AgentRunResponse | null>(null);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const runEndRef = useRef<HTMLDivElement>(null);

  const refreshAgents = useCallback(async () => {
    setLoadingAgents(true);
    setError(null);
    try {
      const list = await listAgentConfigs();
      setAgents(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar agentes");
    } finally {
      setLoadingAgents(false);
    }
  }, []);

  useEffect(() => {
    refreshAgents();
    fetchToolsCatalog()
      .then(setCatalog)
      .catch((err) => setError(err instanceof Error ? err.message : "Erro ao carregar ferramentas"));
  }, [refreshAgents]);

  useEffect(() => {
    if (selected) {
      setDraft(clone(selected));
    } else {
      setDraft(emptyAgent());
    }
  }, [selected]);

  const filteredAgents = useMemo(() => {
    const term = searchTerm.toLowerCase();
    if (!term) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(term) ||
        (a.description || "").toLowerCase().includes(term) ||
        (a.tags || []).some((t) => t.toLowerCase().includes(term)),
    );
  }, [agents, searchTerm]);

  const backendLabel = useMemo(
    () => BACKENDS.find((b) => b.id === (draft.backend || "openai"))?.label || "OpenAI",
    [draft.backend],
  );

  const updateDraft = useCallback(<K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  const addNode = useCallback(() => {
    const id = generateId("node");
    const node: AgentGraphNode = {
      id,
      label: `Nó ${(draft.graph?.nodes.length || 0) + 1}`,
      kind: "prompt",
      prompt: "",
      tools: [],
      output_key: "",
      next: "",
    };
    setDraft((prev) => ({
      ...prev,
      graph: { nodes: [...(prev.graph?.nodes || []), node], edges: prev.graph?.edges || [] },
    }));
  }, [draft.graph?.nodes.length]);

  const updateNode = useCallback((index: number, patch: Partial<AgentGraphNode>) => {
    setDraft((prev) => {
      const nodes = [...(prev.graph?.nodes || [])];
      nodes[index] = { ...nodes[index], ...patch };
      return { ...prev, graph: { ...prev.graph, nodes } };
    });
  }, []);

  const removeNode = useCallback((index: number) => {
    setDraft((prev) => {
      const nodeId = prev.graph?.nodes[index].id;
      const nodes = prev.graph?.nodes.filter((_, i) => i !== index) || [];
      const edges =
        prev.graph?.edges.filter((e) => e.source !== nodeId && e.target !== nodeId) || [];
      return { ...prev, graph: { nodes, edges } };
    });
  }, []);

  const addEdge = useCallback(() => {
    const nodes = draft.graph?.nodes || [];
    if (nodes.length < 2) return;
    const edge: AgentGraphEdge = {
      source: nodes[0].id,
      target: nodes[1].id,
    };
    setDraft((prev) => ({
      ...prev,
      graph: { nodes: prev.graph?.nodes || [], edges: [...(prev.graph?.edges || []), edge] },
    }));
  }, [draft.graph?.nodes]);

  const updateEdge = useCallback((index: number, patch: Partial<AgentGraphEdge>) => {
    setDraft((prev) => {
      const edges = [...(prev.graph?.edges || [])];
      edges[index] = { ...edges[index], ...patch };
      return { ...prev, graph: { ...prev.graph, edges } };
    });
  }, []);

  const removeEdge = useCallback((index: number) => {
    setDraft((prev) => {
      const edges = prev.graph?.edges.filter((_, i) => i !== index) || [];
      return { ...prev, graph: { ...prev.graph, edges } };
    });
  }, []);

  const toggleTool = useCallback((toolId: string) => {
    setDraft((prev) => {
      const exists = prev.tools?.find((t) => t.tool_id === toolId);
      let tools = prev.tools || [];
      if (exists) {
        tools = tools.filter((t) => t.tool_id !== toolId);
      } else {
        const cat = catalog.find((c) => c.tool_id === toolId);
        const ref: AgentToolRef = {
          tool_id: toolId,
          name: cat?.name || toolId,
          description: cat?.description || "",
          enabled: true,
        };
        tools = [...tools, ref];
      }
      return { ...prev, tools };
    });
  }, [catalog]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const payload: AgentConfig = {
        ...draft,
        owner_id: user?.id || draft.owner_id,
      };
      const saved = await saveAgentConfig(payload);
      setSelected(saved);
      await refreshAgents();
      setActiveTab("run");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao guardar");
    } finally {
      setSaving(false);
    }
  }, [draft, refreshAgents, user?.id]);

  const handleDelete = useCallback(async () => {
    if (!draft.agent_id) return;
    if (!confirm("Apagar este agente?")) return;
    setSaving(true);
    try {
      await deleteAgentConfig(draft.agent_id);
      setSelected(null);
      setDraft(emptyAgent());
      await refreshAgents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao apagar");
    } finally {
      setSaving(false);
    }
  }, [draft.agent_id, refreshAgents]);

  const handleRun = useCallback(async () => {
    if (!draft.agent_id || !runInput.trim()) return;
    setRunning(true);
    setRunResponse(null);
    setStreamText("");
    setError(null);
    try {
      if (runInput.trim().startsWith("/stream") || runInput.trim().startsWith("/s")) {
        let text = "";
        const stop = streamAgent(
          draft.agent_id,
          runInput,
          (chunk) => {
            text += chunk;
            setStreamText(text);
          },
          () => {
            setRunning(false);
          },
          (err) => {
            setError(err.message);
            setRunning(false);
          },
        );
        return () => stop();
      }
      const response = await runAgent(draft.agent_id, runInput);
      setRunResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao executar");
    } finally {
      setRunning(false);
    }
    return undefined;
  }, [draft.agent_id, runInput]);

  const handleNew = useCallback(() => {
    setSelected(null);
    setDraft(emptyAgent());
    setActiveTab("editor");
    setRunResponse(null);
    setStreamText("");
    setError(null);
  }, []);

  const handleDuplicate = useCallback(() => {
    const copy = clone(draft);
    copy.agent_id = "";
    copy.name = `${copy.name} (cópia)`;
    setSelected(null);
    setDraft(copy);
    setActiveTab("editor");
  }, [draft]);

  const handleExport = useCallback(() => {
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${draft.name.replace(/\s+/g, "_")}.agent.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [draft]);

  const handleImport = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const imported = JSON.parse(String(reader.result)) as AgentConfig;
        imported.agent_id = "";
        setSelected(null);
        setDraft(imported);
        setActiveTab("editor");
        setError(null);
      } catch {
        setError("Ficheiro JSON inválido");
      }
    };
    reader.readAsText(file);
  }, []);

  useEffect(() => {
    runEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runResponse, streamText]);

  const renderStep = (step: AgentRunStep, idx: number) => {
    const colors: Record<string, string> = {
      node: "border-blue-500/20 bg-blue-500/10 text-blue-300",
      tool: "border-amber-500/20 bg-amber-500/10 text-amber-300",
      tool_result: "border-amber-500/20 bg-amber-500/10 text-amber-300",
      rag: "border-teal-500/20 bg-teal-500/10 text-teal-300",
      thought: "border-purple-500/20 bg-purple-500/10 text-purple-300",
      error: "border-rose-500/20 bg-rose-500/10 text-rose-300",
    };
    return (
      <div
        key={idx}
        className={classNames(
          "rounded-xl border px-3 py-2 text-xs",
          colors[step.kind] || "border-white/10 bg-white/[0.03] text-muted-foreground",
        )}
      >
        <span className="font-semibold uppercase tracking-wider">{step.kind}</span>
        {step.name && <span className="ml-2 opacity-80">{step.name}</span>}
        {step.content && (
          <div className="mt-1 whitespace-pre-wrap opacity-90">{step.content}</div>
        )}
      </div>
    );
  };

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col">
      {/* Cabeçalho */}
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-400/85 to-fuchsia-500/85 text-white shadow-lg shadow-violet-500/20">
          <Bot size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold leading-tight">Agentes Dinâmicos</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Construtor visual de agentes LangGraph · {agents.length} agente{agents.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-1 rounded-full border border-violet-500/20 bg-violet-500/10 px-2.5 py-0.5 text-[11px] font-medium text-violet-300 sm:inline-flex">
            <Sparkles size={11} />
            Premium
          </span>
          {!windowMode && (
            <button className={classNames(btnBase, "border border-white/10 bg-white/[0.04] hover:bg-white/[0.08]")} onClick={onSwitchView}>
              Voltar ao Chat
            </button>
          )}
        </div>
      </header>

      {/* Corpo */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 @4xl:flex-row @4xl:gap-4 @4xl:p-4">
        {/* Barra lateral de agentes */}
        <div className="flex h-auto min-h-[160px] w-full shrink-0 flex-col gap-3 @4xl:h-full @4xl:w-[300px] @5xl:w-[340px]">
          <div className="glass-card gradient-border rounded-2xl p-3">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <BrainCircuit size={16} className="text-violet-400" />
                Agentes
              </h2>
              <button
                className={classNames(btnBase, "bg-primary text-primary-foreground hover:bg-primary/90")}
                onClick={handleNew}
              >
                <Plus size={15} />
                Novo
              </button>
            </div>
            <div className="relative mb-3">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="Pesquisar agentes..."
                className={classNames(inputClass, "pl-9")}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="flex max-h-[320px] flex-col gap-2 overflow-y-auto pr-1 @4xl:max-h-none @4xl:flex-1">
              {loadingAgents ? (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" />
                  A carregar...
                </div>
              ) : filteredAgents.length === 0 ? (
                <div className="py-6 text-center text-xs text-muted-foreground">
                  Nenhum agente encontrado.
                  <br />
                  Cria o primeiro com “Novo”.
                </div>
              ) : (
                filteredAgents.map((agent) => (
                  <button
                    key={agent.agent_id || agent.name}
                    onClick={() => setSelected(agent)}
                    className={classNames(
                      "flex items-start gap-2 rounded-xl border px-3 py-2 text-left transition-colors",
                      selected?.agent_id === agent.agent_id
                        ? "border-violet-500/30 bg-violet-500/10"
                        : "border-white/8 bg-white/[0.02] hover:bg-white/[0.05]",
                    )}
                  >
                    <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-400/60 to-fuchsia-500/60 text-white">
                      <Bot size={14} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{agent.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {agent.backend || "auto"} · {agent.model || "default"}
                      </div>
                    </div>
                    {!agent.enabled && (
                      <span className="rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        off
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Painel principal */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          {/* Tabs */}
          <div className="flex shrink-0 items-center gap-2 overflow-x-auto">
            {(
              [
                { id: "editor", label: "Editor", icon: Edit3 },
                { id: "graph", label: "Grafo", icon: Network },
                { id: "run", label: "Executar", icon: Play },
                { id: "json", label: "JSON", icon: FileText },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={classNames(
                  btnBase,
                  "gap-1.5 border px-3 py-1.5 text-xs",
                  activeTab === id
                    ? "border-violet-500/30 bg-violet-500/15 text-violet-200"
                    : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]",
                )}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <label
                className={classNames(
                  btnBase,
                  "cursor-pointer border border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]",
                )}
              >
                <Upload size={14} />
                Importar
                <input
                  type="file"
                  accept="application/json"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && handleImport(e.target.files[0])}
                />
              </label>
              <button
                className={classNames(btnBase, "border border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]")}
                onClick={handleExport}
              >
                <Download size={14} />
                Exportar
              </button>
              <button
                className={classNames(btnBase, "border border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06]")}
                onClick={handleDuplicate}
              >
                <Copy size={14} />
                Duplicar
              </button>
              {draft.agent_id && (
                <button
                  className={classNames(btnBase, "border border-rose-500/20 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20")}
                  onClick={handleDelete}
                  disabled={saving}
                >
                  <Trash2 size={14} />
                </button>
              )}
              <button
                className={classNames(btnBase, "bg-primary text-primary-foreground hover:bg-primary/90")}
                onClick={handleSave}
                disabled={saving || !draft.name.trim()}
              >
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                Guardar
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              <X size={14} className="shrink-0" />
              {error}
            </div>
          )}

          {/* Conteúdo da tab */}
          <div className="glass-card gradient-border min-h-0 flex-1 overflow-y-auto rounded-2xl p-4">
            {activeTab === "editor" && (
              <div className="mx-auto max-w-4xl space-y-6">
                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Settings2 size={16} className="text-violet-400" />
                    Identidade
                  </h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5 sm:col-span-2">
                      <label className="text-xs text-muted-foreground">Nome</label>
                      <input
                        className={inputClass}
                        value={draft.name}
                        onChange={(e) => updateDraft("name", e.target.value)}
                        placeholder="ex: Analista de Contratos"
                      />
                    </div>
                    <div className="space-y-1.5 sm:col-span-2">
                      <label className="text-xs text-muted-foreground">Descrição</label>
                      <input
                        className={inputClass}
                        value={draft.description || ""}
                        onChange={(e) => updateDraft("description", e.target.value)}
                        placeholder="Para que serve este agente?"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Tags (separadas por vírgula)</label>
                      <input
                        className={inputClass}
                        value={(draft.tags || []).join(", ")}
                        onChange={(e) =>
                          updateDraft(
                            "tags",
                            e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                          )
                        }
                        placeholder="contratos, análise, ..."
                      />
                    </div>
                    <div className="flex items-center gap-4">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-primary"
                          checked={draft.enabled}
                          onChange={(e) => updateDraft("enabled", e.target.checked)}
                        />
                        Ativo
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-primary"
                          checked={draft.is_public}
                          onChange={(e) => updateDraft("is_public", e.target.checked)}
                        />
                        Público
                      </label>
                    </div>
                  </div>
                </section>

                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Sparkles size={16} className="text-violet-400" />
                    Modelo
                  </h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Backend</label>
                      <select
                        className={selectClass}
                        value={draft.backend || "openai"}
                        onChange={(e) => updateDraft("backend", e.target.value)}
                      >
                        {BACKENDS.map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Modelo</label>
                      <input
                        className={inputClass}
                        value={draft.model || ""}
                        onChange={(e) => updateDraft("model", e.target.value)}
                        placeholder="ex: gpt-4o"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Temperatura ({draft.temperature})</label>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={0.05}
                        className="w-full accent-primary"
                        value={draft.temperature ?? 0.2}
                        onChange={(e) => updateDraft("temperature", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Max tokens</label>
                      <input
                        type="number"
                        min={1}
                        max={8192}
                        className={inputClass}
                        value={draft.max_tokens ?? 1024}
                        onChange={(e) => updateDraft("max_tokens", parseInt(e.target.value, 10))}
                      />
                    </div>
                  </div>
                </section>

                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <MessageSquare size={16} className="text-violet-400" />
                    System prompt
                  </h3>
                  <textarea
                    className={textareaClass}
                    value={draft.system_prompt || ""}
                    onChange={(e) => updateDraft("system_prompt", e.target.value)}
                    placeholder="Instruções de sistema para o agente..."
                  />
                </section>

                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Wand2 size={16} className="text-violet-400" />
                    Ferramentas ({draft.tools?.length || 0})
                  </h3>
                  {catalog.length === 0 ? (
                    <div className="text-xs text-muted-foreground">A carregar catálogo...</div>
                  ) : (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {catalog.map((tool) => {
                        const enabled = draft.tools?.some((t) => t.tool_id === tool.tool_id && t.enabled);
                        return (
                          <button
                            key={tool.tool_id}
                            onClick={() => toggleTool(tool.tool_id)}
                            className={classNames(
                              "flex flex-col items-start gap-1 rounded-xl border px-3 py-2 text-left transition-colors",
                              enabled
                                ? "border-violet-500/30 bg-violet-500/10"
                                : "border-white/8 bg-white/[0.02] hover:bg-white/[0.05]",
                            )}
                          >
                            <div className="flex items-center gap-2 text-sm font-medium">
                              {enabled ? <Check size={14} className="text-violet-400" /> : <Zap size={14} className="text-muted-foreground" />}
                              {tool.name}
                            </div>
                            <div className="text-[11px] leading-snug text-muted-foreground">{tool.description}</div>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </section>

                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Search size={16} className="text-violet-400" />
                    RAG opcional
                  </h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Índice</label>
                      <input
                        className={inputClass}
                        value={draft.rag_index || ""}
                        onChange={(e) => updateDraft("rag_index", e.target.value || null)}
                        placeholder="Nome do índice RAG"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs text-muted-foreground">Modo</label>
                      <select
                        className={selectClass}
                        value={draft.rag_mode || ""}
                        onChange={(e) => updateDraft("rag_mode", (e.target.value || null) as AgentConfig["rag_mode"])}
                      >
                        {RAG_MODES.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </section>
              </div>
            )}

            {activeTab === "graph" && (
              <div className="mx-auto max-w-5xl space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <BrainCircuit size={16} className="text-violet-400" />
                    Nós do grafo
                  </h3>
                  <div className="flex items-center gap-2">
                    <button className={classNames(btnBase, "bg-primary text-primary-foreground hover:bg-primary/90")} onClick={addNode}>
                      <Plus size={15} />
                      Nó
                    </button>
                    <button className={classNames(btnBase, "border border-white/10 bg-white/[0.04] hover:bg-white/[0.08]")} onClick={addEdge}>
                      <Plus size={15} />
                      Ligação
                    </button>
                  </div>
                </div>

                {draft.graph?.nodes.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-6 text-center text-sm text-muted-foreground">
                    O grafo está vazio. O motor usa ReAct por omissão.
                    <br />
                    Adiciona nós para criar um fluxo personalizado.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {draft.graph?.nodes.map((node, idx) => (
                      <div
                        key={node.id}
                        className={classNames(
                          "rounded-xl border bg-white/[0.02] p-3",
                          NODE_KINDS.find((k) => k.id === node.kind)?.color.split(" ").slice(1).join(" ") || "border-white/8",
                        )}
                      >
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span
                              className={classNames(
                                "rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                                NODE_KINDS.find((k) => k.id === node.kind)?.color || "border-white/10 bg-white/[0.04] text-muted-foreground",
                              )}
                            >
                              {NODE_KINDS.find((k) => k.id === node.kind)?.label}
                            </span>
                            <input
                              className={classNames(inputClass, "w-[140px]")}
                              value={node.label || ""}
                              onChange={(e) => updateNode(idx, { label: e.target.value })}
                              placeholder="Nome do nó"
                            />
                          </div>
                          <button
                            className={classNames(btnBase, "border border-rose-500/20 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20")}
                            onClick={() => removeNode(idx)}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div className="space-y-1">
                            <label className="text-[11px] text-muted-foreground">ID</label>
                            <input className={inputClass} value={node.id} readOnly />
                          </div>
                          <div className="space-y-1">
                            <label className="text-[11px] text-muted-foreground">Tipo</label>
                            <select
                              className={selectClass}
                              value={node.kind || "prompt"}
                              onChange={(e) => updateNode(idx, { kind: e.target.value as AgentGraphNode["kind"] })}
                            >
                              {NODE_KINDS.map((k) => (
                                <option key={k.id} value={k.id}>
                                  {k.label}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[11px] text-muted-foreground">Next</label>
                            <select
                              className={selectClass}
                              value={node.next || ""}
                              onChange={(e) => updateNode(idx, { next: e.target.value || undefined })}
                            >
                              <option value="">—</option>
                              {draft.graph?.nodes
                                .filter((n) => n.id !== node.id)
                                .map((n) => (
                                  <option key={n.id} value={n.id}>
                                    {n.label || n.id}
                                  </option>
                                ))}
                            </select>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[11px] text-muted-foreground">Output key</label>
                            <input
                              className={inputClass}
                              value={node.output_key || ""}
                              onChange={(e) => updateNode(idx, { output_key: e.target.value || undefined })}
                              placeholder="ex: resposta"
                            />
                          </div>
                        </div>
                        {(node.kind === "prompt" || node.kind === "supervisor" || node.kind === "rag") && (
                          <div className="mt-3 space-y-1">
                            <label className="text-[11px] text-muted-foreground">Prompt / instrução</label>
                            <textarea
                              className={textareaClass}
                              value={node.prompt || ""}
                              onChange={(e) => updateNode(idx, { prompt: e.target.value })}
                              placeholder="Instrução deste nó..."
                            />
                          </div>
                        )}
                        {node.kind === "tool" && (
                          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                              <label className="text-[11px] text-muted-foreground">Tools (separadas por vírgula)</label>
                              <input
                                className={inputClass}
                                value={(node.tools || []).join(", ")}
                                onChange={(e) =>
                                  updateNode(idx, {
                                    tools: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                                  })
                                }
                                placeholder="stock_info, news, ..."
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {draft.graph && draft.graph.edges.length > 0 && (
                  <div className="space-y-3 pt-2">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <ChevronRight size={16} className="text-violet-400" />
                      Ligações ({draft.graph.edges.length})
                    </h3>
                    {draft.graph.edges.map((edge, idx) => (
                      <div key={idx} className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2">
                        <select
                          className={selectClass}
                          value={edge.source}
                          onChange={(e) => updateEdge(idx, { source: e.target.value })}
                        >
                          {draft.graph?.nodes.map((n) => (
                            <option key={n.id} value={n.id}>
                              {n.label || n.id}
                            </option>
                          ))}
                        </select>
                        <ChevronRight size={16} className="text-muted-foreground" />
                        <select
                          className={selectClass}
                          value={edge.target}
                          onChange={(e) => updateEdge(idx, { target: e.target.value })}
                        >
                          {draft.graph?.nodes.map((n) => (
                            <option key={n.id} value={n.id}>
                              {n.label || n.id}
                            </option>
                          ))}
                        </select>
                        <input
                          className={classNames(inputClass, "min-w-[120px] flex-1")}
                          value={edge.condition ? JSON.stringify(edge.condition) : ""}
                          onChange={(e) => {
                            try {
                              const val = e.target.value ? JSON.parse(e.target.value) : null;
                              updateEdge(idx, { condition: val });
                            } catch {
                              // ignore invalid JSON while typing
                            }
                          }}
                          placeholder='Condição JSON ex: {"if": "x>0"}'
                        />
                        <button
                          className={classNames(btnBase, "border border-rose-500/20 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20")}
                          onClick={() => removeEdge(idx)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === "run" && (
              <div className="mx-auto flex h-full max-w-4xl flex-col gap-3">
                {!draft.agent_id ? (
                  <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Bot size={32} className="opacity-30" />
                    Guarda o agente antes de executar.
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded-md border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 text-violet-300">
                        {draft.name}
                      </span>
                      <span>{backendLabel}</span>
                      <span>·</span>
                      <span>{draft.model || "default"}</span>
                      <span>·</span>
                      <span>T {draft.temperature}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <textarea
                        className={classNames(textareaClass, "min-h-[80px] flex-1")}
                        value={runInput}
                        onChange={(e) => setRunInput(e.target.value)}
                        placeholder="Escreve uma mensagem para o agente..."
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleRun();
                          }
                        }}
                      />
                      <button
                        className={classNames(btnBase, "h-[80px] w-14 shrink-0 bg-primary text-primary-foreground hover:bg-primary/90")}
                        onClick={handleRun}
                        disabled={running || !runInput.trim()}
                      >
                        {running ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                      </button>
                    </div>

                    {(runResponse || streamText) && (
                      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-2xl border border-white/8 bg-white/[0.02] p-4">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-semibold">Resposta</h4>
                          <button
                            className={classNames(
                              btnBase,
                              "border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-muted-foreground hover:bg-white/[0.08]",
                            )}
                            onClick={() => {
                              const text = runResponse?.message?.content || streamText || "";
                              navigator.clipboard.writeText(text);
                              setCopied(true);
                              setTimeout(() => setCopied(false), 1200);
                            }}
                          >
                            {copied ? <Check size={13} /> : <Copy size={13} />}
                            {copied ? "Copiado" : "Copiar"}
                          </button>
                        </div>
                        <div className="prose prose-invert max-w-none text-sm">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {runResponse?.message?.content || streamText}
                          </ReactMarkdown>
                        </div>
                        {runResponse && runResponse.steps.length > 0 && (
                          <div className="space-y-2 pt-2">
                            <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                              Passos ({runResponse.steps.length})
                            </h5>
                            <div className="space-y-2">{runResponse.steps.map(renderStep)}</div>
                          </div>
                        )}
                        {runResponse && runResponse.sources.length > 0 && (
                          <div className="space-y-2 pt-2">
                            <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                              Fontes ({runResponse.sources.length})
                            </h5>
                            <ul className="space-y-1 text-xs text-muted-foreground">
                              {runResponse.sources.map((s, i) => (
                                <li key={i} className="border-l-2 border-teal-500/30 pl-2">
                                  [{i + 1}] {s.doc_title || s.doc_id}
                                  {s.score !== undefined && ` · score ${s.score.toFixed(3)}`}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div ref={runEndRef} />
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {activeTab === "json" && (
              <div className="relative">
                <pre className="rounded-xl border border-white/8 bg-black/30 p-4 text-xs text-foreground/80">
                  {JSON.stringify(draft, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

