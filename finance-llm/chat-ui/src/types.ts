export type Role = "user" | "assistant" | "system";

export interface Message {
  id: string;
  role: Role;
  content: string;
  timestamp: string;
  sources?: Source[];
  tools?: ToolCall[];
}

export interface Source {
  name: string;
  url?: string;
  value?: string;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  output?: string;
}

export type ModelBackend = "gpt2" | "mistral";

export interface ChatRequest {
  messages: { role: Role; content: string; timestamp?: string }[];
  model?: string;
  backend?: ModelBackend;
  stream?: boolean;
}

export interface ChatResponse {
  message: {
    role: Role;
    content: string;
    timestamp?: string;
  };
  sources: Source[];
  tools: ToolCall[];
}
