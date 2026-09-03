import { useEffect, useRef } from "react";
import { Bot, User, Copy, Check, ThumbsUp, ThumbsDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  streaming?: boolean;
}

function formatTime(ts: string) {
  const d = new Date(ts);
  return d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
}

export function MessageList({ messages, streaming }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
          <Bot size={32} className="text-primary" />
        </div>
        <h1 className="text-2xl font-semibold mb-2">FinanceLLM Chat</h1>
        <p className="text-muted-foreground max-w-md">
          Pergunta-me sobre ações, dividendos, indicadores macro ou dados de mercado. Usa ferramentas financeiras em tempo real.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
      {messages.map((msg) => (
        <MessageItem key={msg.id} message={msg} />
      ))}
      {streaming && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm px-2">
          <span className="w-2 h-2 rounded-full bg-primary animate-bounce" />
          <span className="w-2 h-2 rounded-full bg-primary animate-bounce [animation-delay:150ms]" />
          <span className="w-2 h-2 rounded-full bg-primary animate-bounce [animation-delay:300ms]" />
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}

function MessageItem({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={["max-w-4xl mx-auto flex gap-4", isUser ? "flex-row-reverse" : ""].join(" ")}>
      <div className={[
        "w-8 h-8 rounded-full shrink-0 flex items-center justify-center",
        isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
      ].join(" ")}>
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className={["flex flex-col gap-1 max-w-[85%]", isUser ? "items-end" : "items-start"].join(" ")}>
        <div
          className={[
            "px-4 py-3 rounded-2xl text-sm leading-relaxed prose prose-invert max-w-none",
            isUser
              ? "bg-primary text-primary-foreground rounded-br-none"
              : "bg-muted text-foreground rounded-bl-none border border-border",
          ].join(" ")}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap m-0">{message.content}</p>
          ) : (
            <div className="prose-p:my-1 prose-ul:my-1 prose-ol:my-1">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && (message.sources?.length || message.tools?.length) && (
          <div className="mt-1 flex flex-wrap gap-2">
            {message.tools?.map((tool, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-accent text-accent-foreground text-xs border border-border"
              >
                ⚡ {tool.tool}
              </span>
            ))}
            {message.sources?.map((src, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-secondary text-secondary-foreground text-xs border border-border"
              >
                📊 {src.name}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 text-xs text-muted-foreground px-1">
          <span>{formatTime(message.timestamp)}</span>
          {!isUser && <MessageActions content={message.content} />}
        </div>
      </div>
    </div>
  );
}

function MessageActions({ content }: { content: string }) {
  return (
    <div className="flex items-center gap-1">
      <CopyButton text={content} />
      <button className="p-1 hover:text-foreground transition" title="Boa resposta">
        <ThumbsUp size={14} />
      </button>
      <button className="p-1 hover:text-foreground transition" title="Má resposta">
        <ThumbsDown size={14} />
      </button>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={copy}
      className="p-1 hover:text-foreground transition"
      title={copied ? "Copiado" : "Copiar"}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

import { useState } from "react";
