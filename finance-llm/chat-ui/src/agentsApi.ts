/**
 * API helpers para o construtor de agentes dinâmicos.
 * Usa o fetch instrumentado em authApi.ts (token é injetado automaticamente).
 */
import { API_BASE } from "./api";

export interface AgentGraphNode {
  id: string;
  label?: string;
  kind?: "prompt" | "tool" | "rag" | "conditional" | "supervisor" | "output";
  prompt?: string;
  tools?: string[];
  output_key?: string;
  next?: string;
  condition?: Record<string, unknown> | null;
}

export interface AgentGraphEdge {
  source: string;
  target: string;
  condition?: Record<string, unknown> | null;
}

export interface AgentGraphDefinition {
  nodes: AgentGraphNode[];
  edges: AgentGraphEdge[];
}

export interface AgentToolRef {
  tool_id: string;
  provider?: string | null;
  name?: string | null;
  description?: string | null;
  params?: Record<string, unknown> | null;
  enabled?: boolean;
}

export interface AgentConfig {
  agent_id?: string;
  owner_id?: string;
  name: string;
  description?: string;
  icon?: string;
  tags?: string[];
  backend?: string | null;
  model?: string | null;
  temperature?: number;
  max_tokens?: number;
  system_prompt?: string;
  graph?: AgentGraphDefinition;
  tools?: AgentToolRef[];
  rag_index?: string | null;
  rag_mode?: "dense" | "hybrid" | "hybrid_rerank" | "crag" | "crag_rerank" | null;
  enabled?: boolean;
  is_public?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AgentRunRequest {
  agent_id: string;
  message: string;
  context?: Record<string, unknown>;
  stream?: boolean;
  thread_id?: string;
}

export interface AgentRunMessage {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls?: Record<string, unknown>[];
}

export interface AgentRunStep {
  kind: "node" | "tool" | "tool_result" | "rag" | "thought" | "error";
  name?: string;
  content?: string;
  payload?: Record<string, unknown>;
}

export interface AgentRunResponse {
  agent_id: string;
  thread_id: string;
  message: AgentRunMessage;
  steps: AgentRunStep[];
  sources: {
    chunk_id: string;
    doc_id: string;
    doc_title: string;
    page?: number;
    text: string;
    score?: number;
  }[];
  elapsed_seconds?: number;
  error?: string;
}

export interface ToolCatalogItem {
  tool_id: string;
  name: string;
  description: string;
}

export interface ToolCatalogResponse {
  tools: ToolCatalogItem[];
}

export async function listAgentConfigs(): Promise<AgentConfig[]> {
  const res = await fetch(`${API_BASE}/agents`);
  if (!res.ok) throw new Error(`Erro ao listar agentes: ${res.status}`);
  const data = await res.json();
  return data.agents ?? [];
}

export async function getAgentConfig(agentId: string): Promise<AgentConfig> {
  const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}`);
  if (!res.ok) throw new Error(`Erro ao obter agente: ${res.status}`);
  return res.json();
}

export async function saveAgentConfig(payload: AgentConfig): Promise<AgentConfig> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao guardar agente: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function deleteAgentConfig(agentId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Erro ao apagar agente: ${res.status}`);
}

export async function runAgent(agentId: string, message: string, context?: Record<string, unknown>): Promise<AgentRunResponse> {
  const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, message, context } satisfies AgentRunRequest),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Erro ao executar agente: ${res.status} - ${text}`);
  }
  return res.json();
}

export async function fetchToolsCatalog(): Promise<ToolCatalogItem[]> {
  const res = await fetch(`${API_BASE}/agents/tools/catalog`);
  if (!res.ok) throw new Error(`Erro ao obter catálogo de ferramentas: ${res.status}`);
  const data: ToolCatalogResponse = await res.json();
  return data.tools ?? [];
}

export function streamAgent(
  agentId: string,
  message: string,
  onChunk: (chunk: string) => void,
  onDone?: () => void,
  onError?: (err: Error) => void,
  context?: Record<string, unknown>,
): () => void {
  const abort = new AbortController();
  const url = `${API_BASE}/agents/${encodeURIComponent(agentId)}/stream`;

  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, message, context } satisfies AgentRunRequest),
    signal: abort.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Erro no stream: ${res.status} - ${text}`);
      }
      if (!res.body) throw new Error("Stream vazio");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const cleaned = part.replace(/^data:\s*/gm, "").trim();
          if (cleaned) onChunk(cleaned);
        }
      }
      onDone?.();
    })
    .catch((err) => {
      if ((err as Error).name === "AbortError") return;
      onError?.(err);
    });

  return () => abort.abort();
}
