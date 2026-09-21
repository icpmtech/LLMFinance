/**
 * Skills do IQ OS (`/skills/*`) — o **método** que os assistentes seguem antes de
 * responder (Hermes, Chat IA e RAG partilham a mesma biblioteca).
 *
 * Uma skill tem nome, quando usar, passos, verificações e as ferramentas da
 * plataforma a tocar. São criadas automaticamente a partir da pergunta: se já
 * existir uma suficientemente parecida é essa que é usada; se não, é criada uma
 * nova (escrita pelo modelo de IA ou, sem modelo, montada a partir das
 * capacidades reais da plataforma).
 */
import { API_BASE } from "./api";
import type { SkillRef } from "./types";

export type HermesSkill = SkillRef & {
  question?: string;
  keywords?: string[];
  source?: string;
  created_at?: string;
  updated_at?: string;
  last_used_at?: string | null;
  last_mode?: string;
  examples?: string[];
};

export type SkillsStatus = {
  total: number;
  enabled: number;
  uses: number;
  by_quality: Record<string, number>;
  path: string;
  updated_at?: string;
};

export type SkillsPayload = { skills: HermesSkill[]; status: SkillsStatus };

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

function withBody(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/* ------------------------------------------------------------------- rotas */

export function listSkills(): Promise<SkillsPayload> {
  return request<SkillsPayload>("/skills");
}

export function matchSkill(question: string): Promise<{ question: string; skill: HermesSkill | null; score: number }> {
  return request("/skills/match", withBody("POST", { question }));
}

/** Escolhe (ou cria, sem responder) a skill que este pedido ia usar. */
export function ensureSkill(question: string, options: { backend?: string; modelDraft?: boolean } = {}): Promise<{
  question: string;
  created: boolean;
  merged: boolean;
  mode: string;
  score: number;
  skill: HermesSkill;
}> {
  return request(
    "/skills/ensure",
    withBody("POST", { question, backend: options.backend, model_draft: options.modelDraft ?? true }),
  );
}

export function saveSkill(payload: Partial<HermesSkill> & { name?: string }): Promise<{ saved: boolean; skill: HermesSkill; status: SkillsStatus }> {
  return request("/skills", withBody("POST", payload));
}

export function patchSkill(id: string, payload: Partial<HermesSkill>): Promise<{ saved: boolean; skill: HermesSkill }> {
  return request(`/skills/${encodeURIComponent(id)}`, withBody("PATCH", payload));
}

export function deleteSkill(id: string): Promise<{ removed: boolean; id: string; status: SkillsStatus }> {
  return request(`/skills/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function clearSkills(): Promise<{ removed: number; status: SkillsStatus }> {
  return request("/skills", { method: "DELETE" });
}
