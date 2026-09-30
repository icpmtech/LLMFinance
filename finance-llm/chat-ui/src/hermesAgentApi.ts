/**
 * Cliente do **motor do Hermes Agent** (`/hermes-agent/*`).
 *
 * O Hermes Agent é o container autónomo da solução. Não partilha nada com a
 * plataforma além do login; este cliente é a ponte que lhe leva o fornecedor de
 * IA que a plataforma já tem — resolve a chave, escreve-a no volume do container
 * (`config.yaml` + `.env`) e recria-o.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type HermesAgentProvider = {
  id: string;
  label: string;
  usable: boolean;
  key_hint: string;
  key_source: string;
  default_model: string;
  models: string[];
  base_url: string;
  hermes_provider: string | null;
  hermes_env: string | null;
  mode: string;
};

export type HermesAgentDiagnose = {
  container: string;
  docker_available: boolean;
  running: boolean;
  config: Record<string, string | null>;
  config_has_api_key?: boolean;
  env_keys: string[];
  applied_at: string;
  wanted: { provider: string | null; model: string | null; base_url: string | null; env: string[] };
  notes: string[];
  in_sync: boolean;
  problems: string[];
};

export type HermesAgentSettings = {
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  llm_custom_key_set: boolean;
  search_provider: string;
  searxng_url: string;
  brave_key_set: boolean;
  applied_at: string;
  updated_at: string;
  updated_by: string;
};

export type HermesAgentView = {
  about: { container: string; profile: string; service: string; home: string; note: string };
  settings: HermesAgentSettings;
  resolved: {
    provider: string;
    label: string;
    known: boolean;
    hermes_provider: string | null;
    env_var: string | null;
    key: string;
    source: string;
    base_url: string;
    model: string;
    uses_custom_provider: boolean;
  };
  plan: {
    config: Record<string, string | null>;
    env: string[];
    clear_env: string[];
    notes: string[];
  };
  providers: HermesAgentProvider[];
  search_providers: { id: string; label: string; description: string }[];
  registry: { total: number; native: string[] };
  diagnose: HermesAgentDiagnose;
  commands: Record<string, string>;
};

export type HermesAgentSettingsPayload = {
  llm_provider?: string;
  llm_model?: string;
  llm_base_url?: string;
  llm_custom_key?: string;
  search_provider?: string;
  searxng_url?: string;
  brave_key?: string;
  recreate?: boolean;
};

/* ----------------------------------------------------------------- helpers */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/* ------------------------------------------------------------------- rotas */

export function getHermesAgentSettings(): Promise<HermesAgentView> {
  return request<HermesAgentView>("/hermes-agent/settings");
}

export function saveHermesAgentSettings(payload: HermesAgentSettingsPayload): Promise<HermesAgentView> {
  return request<HermesAgentView>("/hermes-agent/settings", withBody("PUT", payload));
}

export function applyHermesAgentSettings(
  payload: HermesAgentSettingsPayload = {},
): Promise<{
  applied_at: string;
  resolved: Record<string, unknown>;
  config: string[];
  env_written: string[];
  env_removed: string[];
  recreated: boolean;
  notes: string[];
}> {
  return request("/hermes-agent/settings/apply", withBody("POST", payload));
}

export function getHermesAgentDiagnose(): Promise<HermesAgentDiagnose> {
  return request<HermesAgentDiagnose>("/hermes-agent/diagnose");
}
