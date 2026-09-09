import { useState, useCallback, useEffect } from "react";
import { ChatLayout } from "./components/ChatLayout";
import { ForecastPage } from "./pages/ForecastPage";
import { TickerPage } from "./pages/TickerPage";
import { RagPage } from "./pages/RagPage";
import { ElasticPage } from "./pages/ElasticPage";
import { sendChat } from "./sendChat";
import type { Message, ModelBackend } from "./types";

type AppView = "chat" | "forecast" | "tickers" | "rag" | "elastic";

const STORAGE_KEY = "finance-llm-conversations";

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function makeMessage(role: Message["role"], content: string): Message {
  return {
    id: generateId(),
    role,
    content,
    timestamp: new Date().toISOString(),
  };
}

function titleFromText(text: string) {
  return text.length > 40 ? text.slice(0, 37) + "..." : text;
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [backend, setBackend] = useState<ModelBackend>("gpt2");
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<AppView>(() => {
    if (typeof window === "undefined") return "chat";
    const path = window.location.pathname.replace(/\/$/, "");
    if (path === "/rag") return "rag";
    if (path === "/forecast") return "forecast";
    if (path === "/tickers") return "tickers";
    if (path === "/elastic") return "elastic";
    const saved = localStorage.getItem("finance-llm-view");
    return (saved as AppView) || "chat";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  }, [conversations]);

  useEffect(() => {
    localStorage.setItem("finance-llm-view", view);
  }, [view]);

  const ensureActiveConversation = useCallback(
    (text: string) => {
      if (activeId) return activeId;
      const newId = generateId();
      const newConv: Conversation = {
        id: newId,
        title: titleFromText(text),
        messages: [],
      };
      setConversations((prev) => [newConv, ...prev]);
      setActiveId(newId);
      return newId;
    },
    [activeId],
  );

  const updateConversation = useCallback((id: string, msgs: Message[]) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, messages: msgs } : c)),
    );
    setMessages(msgs);
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      const id = ensureActiveConversation(text);
      const userMsg = makeMessage("user", text);
      const currentMessages = [...messages, userMsg];
      updateConversation(id, currentMessages);
      setLoading(true);

      let assistantMsg = makeMessage("assistant", "");

      try {
        const result = await sendChat(currentMessages, backend);
        assistantMsg = {
          ...assistantMsg,
          content: result.message.content,
          sources: result.sources,
          tools: result.tools,
        };
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.id === assistantMsg.id) {
            return [...prev.slice(0, -1), assistantMsg];
          }
          return [...prev, assistantMsg];
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Erro desconhecido";
        assistantMsg = { ...assistantMsg, content: `❌ ${message}` };
        setMessages((prev) => [...prev, assistantMsg]);
      } finally {
        setLoading(false);
        updateConversation(id, [...currentMessages, assistantMsg]);
      }
    },
    [messages, backend, ensureActiveConversation, updateConversation],
  );

  const handleSelect = useCallback(
    (id: string) => {
      setActiveId(id);
      setMessages(conversations.find((c) => c.id === id)?.messages || []);
    },
    [conversations],
  );

  const handleNew = useCallback(() => {
    setActiveId(null);
    setMessages([]);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    },
    [activeId],
  );

  if (view === "forecast") return <ForecastPage onSwitchView={() => setView("chat")} />;
  if (view === "tickers") return <TickerPage onSwitchView={() => setView("chat")} />;
  if (view === "rag") return <RagPage onSwitchView={() => setView("chat")} />;
  if (view === "elastic") return <ElasticPage onSwitchView={() => setView("chat")} />;
  return (
    <ChatLayout
      conversations={conversations}
      activeId={activeId}
      messages={messages}
      loading={loading}
      streaming={false}
      backend={backend}
      onSelectConversation={handleSelect}
      onNewConversation={handleNew}
      onDeleteConversation={handleDelete}
      onSend={handleSend}
      onBackendChange={setBackend}
      onSwitchView={() => setView("forecast")}
      onSwitchTickers={() => setView("tickers")}
      onSwitchRag={() => setView("rag")}
      onSwitchElastic={() => setView("elastic")}
    />
  );
}

