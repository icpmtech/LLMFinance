import { Send, Loader2 } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import type { ModelBackend } from "../types";

interface ChatInputProps {
  onSend: (text: string) => void;
  loading?: boolean;
  backend?: ModelBackend;
  onBackendChange?: (backend: ModelBackend) => void;
}

export function ChatInput({ onSend, loading, backend = "gpt2", onBackendChange }: ChatInputProps) {
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    onSend(trimmed);
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(e);
    }
  };

  return (
    <form onSubmit={submit} className="p-4 border-t border-border bg-card">
      <div className="max-w-4xl mx-auto flex items-center gap-2 mb-2">
        <label className="text-xs text-muted-foreground">Modelo:</label>
        <select
          value={backend}
          onChange={(e) => onBackendChange?.(e.target.value as ModelBackend)}
          disabled={loading}
          className="text-xs bg-muted rounded-md px-2 py-1 outline-none focus:ring-1 focus:ring-primary/50"
        >
          <option value="gpt2">GPT-2 Finance</option>
          <option value="mistral">Mistral Finance</option>
          <option value="bloomberg">BloombergGPT-style (RAG)</option>
        </select>
      </div>
      <div className="max-w-4xl mx-auto relative">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
          placeholder="Pergunta sobre finanças, ações, indicadores macro..."
          className="w-full resize-none max-h-40 bg-muted rounded-2xl pl-4 pr-12 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 border border-transparent focus:border-primary transition"
        />
        <button
          type="submit"
          disabled={!text.trim() || loading}
          className="absolute right-2 bottom-2 p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </div>
      <p className="text-center text-xs text-muted-foreground mt-2">
        O FinanceLLM pode cometer erros. Verifica dados críticos antes de investir.
      </p>
    </form>
  );
}
