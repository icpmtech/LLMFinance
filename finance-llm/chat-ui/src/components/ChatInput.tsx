import { Send, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ModelBackend } from "../types";
import { buildChatOptions, useProviders } from "../providers";

interface ChatInputProps {
  onSend: (text: string) => void;
  loading?: boolean;
  backend?: ModelBackend;
  onBackendChange?: (backend: ModelBackend) => void;
}

export function ChatInput({ onSend, loading, backend = "gpt2", onBackendChange }: ChatInputProps) {
  const [text, setText] = useState("");
  const { catalog } = useProviders();

  /* Modelos locais + fornecedores externos, agrupados no selector. */
  const options = useMemo(() => buildChatOptions(catalog), [catalog]);
  const groups = useMemo(() => {
    const map = new Map<string, typeof options>();
    for (const option of options) {
      const list = map.get(option.group) ?? [];
      list.push(option);
      map.set(option.group, list);
    }
    return [...map.entries()];
  }, [options]);

  const current = options.find((option) => option.id === backend);
  const currentUsable = current ? current.usable : true;

  useEffect(() => {
    // Se o backend escolhido deixou de estar utilizável (sem chave), volta ao primeiro que funciona.
    if (options.length === 0 || currentUsable) return;
    const fallback = options.find((option) => option.usable);
    if (fallback) onBackendChange?.(fallback.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUsable, options.length]);

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
          className="text-xs bg-muted rounded-md px-2 py-1 outline-none focus:ring-1 focus:ring-primary/50 max-w-[360px]"
          title="Modelos locais da plataforma ou fornecedores externos (chaves em Definições → Fornecedores de IA)"
        >
          {groups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.usable}>
                  {option.label}
                  {option.usable ? "" : " — sem chave"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {current?.note && <span className="text-[11px] text-muted-foreground truncate">{current.note}</span>}
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
        O IQ OS pode cometer erros. Verifica dados críticos antes de investir.
      </p>
    </form>
  );
}
