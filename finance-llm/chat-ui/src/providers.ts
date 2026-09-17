/**
 * Fornecedores de IA: catálogo, chaves e teste de ligação.
 *
 * O catálogo vem do backend (`/providers`) com o estado das chaves do
 * utilizador. O hook `useProviders` mantém uma cache em módulo partilhada entre
 * a página de Definições e o selector do chat, para não repetir pedidos.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { API_BASE } from "./api";

export type ProviderInfo = {
  id: string;
  label: string;
  kind: "local" | "openai" | "anthropic" | "google";
  base_url?: string;
  env?: string;
  docs_url?: string;
  models: string[];
  default_model: string;
  notes?: string;
  requires_key: boolean;
  configured: boolean;
  key_source: "user" | "env" | "local" | "none";
  key_hint: string;
  has_user_key?: boolean;
  key_optional?: boolean;
  id_prefix: string;
};

export type ProvidersCatalog = {
  providers: ProviderInfo[];
  defaults: { provider?: string; model?: string };
};

export type ChatModelOption = {
  id: string;
  label: string;
  group: string;
  model: string;
  provider?: string;
  usable: boolean;
  note?: string | null;
  default?: boolean;
};

const EMPTY: ProvidersCatalog = { providers: [], defaults: {} };
const CHANGE_EVENT = "finance-llm-providers-changed";

let cache: ProvidersCatalog = EMPTY;
let loading = false;
let loaded = false;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* sem corpo JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function commit(next: ProvidersCatalog) {
  cache = next;
  loaded = true;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => window.removeEventListener(CHANGE_EVENT, onChange);
}

/** Carrega (ou recarrega) o catálogo de fornecedores. */
export async function refreshProviders(): Promise<ProvidersCatalog> {
  if (loading) return cache;
  loading = true;
  try {
    const catalog = await request<ProvidersCatalog>("/providers");
    commit(catalog);
    return catalog;
  } finally {
    loading = false;
  }
}

export function getProvidersCatalog(): ProvidersCatalog {
  return cache;
}

/** Hook do catálogo (com carregamento automático na primeira utilização). */
export function useProviders() {
  const catalog = useSyncExternalStore(subscribe, getProvidersCatalog, getProvidersCatalog);

  useEffect(() => {
    if (!loaded) void refreshProviders().catch(() => undefined);
  }, []);

  const saveKey = useCallback(async (provider: string, apiKey: string) => {
    const next = await request<ProvidersCatalog>("/providers/keys", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_key: apiKey }),
    });
    commit(next);
    return next;
  }, []);

  const saveDefaults = useCallback(async (defaults: { provider?: string; model?: string }) => {
    await request("/providers/defaults", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(defaults),
    });
    await refreshProviders();
  }, []);

  const testProvider = useCallback(async (provider: string, model?: string, apiKey?: string) => {
    return request<{ ok: boolean; message: string; provider: string; model: string }>("/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model, api_key: apiKey || undefined }),
    });
  }, []);

  const chatModels = useCallback(async () => request<{ options: ChatModelOption[]; defaults: { provider?: string; model?: string } }>("/providers/chat-models"), []);

  return { catalog, providers: catalog.providers, defaults: catalog.defaults, loading, refresh: refreshProviders, saveKey, saveDefaults, testProvider, chatModels };
}

/** Opções do selector do chat, agrupadas (locais + cloud). */
export function buildChatOptions(catalog: ProvidersCatalog): ChatModelOption[] {
  const options: ChatModelOption[] = [];
  for (const provider of catalog.providers) {
    if (provider.kind === "local") {
      options.push({
        id: provider.id,
        label: provider.label,
        group: "Modelos locais",
        model: provider.default_model,
        usable: true,
        default: true,
      });
      continue;
    }
    const group = provider.id === "ollama" ? "Local (Ollama)" : "Fornecedores cloud";
    for (const model of provider.models) {
      options.push({
        id: `${provider.id}:${model}`,
        label: `${provider.label} · ${model}`,
        group,
        model,
        provider: provider.id,
        usable: provider.configured,
        note: provider.configured
          ? provider.key_source === "env"
            ? "chave do servidor"
            : provider.key_source === "user"
              ? `chave ${provider.key_hint}`
              : undefined
          : "configure em Definições → Fornecedores de IA",
      });
    }
  }
  return options;
}
