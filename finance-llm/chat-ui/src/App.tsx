import { useState, useCallback, useEffect } from "react";
import { ChatLayout } from "./components/ChatLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { TickerDetailPage } from "./pages/TickerDetailPage";
import { ForecastPage } from "./pages/ForecastPage";
import { TradingPage } from "./pages/TradingPage";
import { TickerPage } from "./pages/TickerPage";
import { RagPage } from "./pages/RagPage";
import { ElasticPage } from "./pages/ElasticPage";
import { GlobalSearchPage } from "./pages/GlobalSearchPage";
// import { ContractsPage } from "./pages/ContractsPage"; // página legada, mantida no código mas não usada
import { ContractsDashboardPage } from "./pages/ContractsDashboardPage";
import { ContractsSearchPage } from "./pages/ContractsSearchPage";
import { CompanyDirectoryPage } from "./pages/CompanyDirectoryPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import CompanyDashboardPage from "./pages/CompanyDashboardPage";
import { sendChat } from "./sendChat";
import type { Message, ModelBackend } from "./types";

type AppView = "dashboard" | "chat" | "forecast" | "trading" | "tickers" | "ticker-detail" | "rag" | "elastic" | "search" | "contracts" | "contracts-dashboard" | "contracts-search" | "companies" | "companies-search" | "companies-dashboard" | "company-detail";
const COMPANY_DETAIL_KEY = "finance-llm-company-detail";
const TICKER_DETAIL_KEY = "finance-llm-ticker-detail";

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
  const [selectedCompany, setSelectedCompany] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(COMPANY_DETAIL_KEY);
  });
  const [selectedTicker, setSelectedTicker] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(TICKER_DETAIL_KEY);
  });

  const [view, setView] = useState<AppView>(() => {
    if (typeof window === "undefined") return "dashboard";
    const path = window.location.pathname.replace(/\/$/, "");
    if (path === "/rag") return "rag";
    if (path === "/forecast") return "forecast";
    if (path === "/trading") return "trading";
    if (path === "/tickers") return "tickers";
    if (path === "/elastic") return "elastic";
    if (path === "/search") return "search";
    if (path === "/contracts") return "contracts-search";
    if (path === "/contracts/search") return "contracts-search";
    if (path === "/contracts/dashboard") return "contracts-dashboard";
    if (path === "/companies") return "companies-search";
    if (path === "/companies/search") return "companies-search";
    if (path === "/companies/dashboard") return "companies-dashboard";
    if (path.startsWith("/companies/") && !path.startsWith("/companies/search") && !path.startsWith("/companies/dashboard")) {
      const nif = path.replace("/companies/", "").split("/")[0];
      if (nif) setSelectedCompany(nif);
      return "company-detail";
    }
    if (path === "/" || path === "") {
      const saved = localStorage.getItem("finance-llm-view");
      return (saved as AppView) || "dashboard";
    }
    return "dashboard";
  });

  useEffect(() => {
    if (selectedCompany) {
      localStorage.setItem(COMPANY_DETAIL_KEY, selectedCompany);
    } else {
      localStorage.removeItem(COMPANY_DETAIL_KEY);
    }
    if (selectedTicker) {
      localStorage.setItem(TICKER_DETAIL_KEY, selectedTicker);
    } else {
      localStorage.removeItem(TICKER_DETAIL_KEY);
    }
  }, [selectedCompany, selectedTicker]);

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

  const handleSwitchView = (v: string) => {
    if (v === "tickers" || v === "tickers-old") {
      setView("tickers");
      return;
    }
    if (v === "ticker-detail") {
      if (!selectedTicker && typeof window !== "undefined") {
        const saved = localStorage.getItem(TICKER_DETAIL_KEY);
        setSelectedTicker(saved || "AAPL");
      }
      setView("ticker-detail");
      return;
    }
    if (v === "search") {
      setView("search");
      return;
    }
    if (v === "trading") {
      setView("trading");
      return;
    }
    if (v === "contracts") {
      setView("contracts-search");
      return;
    }
    if (v === "contracts-search") {
      setView("contracts-search");
      return;
    }
    if (v === "contracts-dashboard") {
      setView("contracts-dashboard");
      return;
    }
    if (v === "companies") {
      setView("companies-search");
      return;
    }
    if (v === "companies-search") {
      setView("companies-search");
      return;
    }
    if (v === "companies-dashboard") {
      setView("companies-dashboard");
      return;
    }
    setView(v as AppView);
  };

  const handleSelectTicker = (ticker: string) => {
    setSelectedTicker(ticker);
    setView("ticker-detail");
  };

  if (view === "dashboard") return <DashboardPage onSwitchView={handleSwitchView} onSelectTicker={handleSelectTicker} />;
  if (view === "ticker-detail" && selectedTicker) {
    return (
      <TickerDetailPage
        ticker={selectedTicker}
        onBack={() => setView("dashboard")}
        onSwitchView={handleSwitchView}
      />
    );
  }
  if (view === "forecast") return <ForecastPage onSwitchView={() => setView("dashboard")} />;
  if (view === "trading") return <TradingPage onSwitchView={() => setView("dashboard")} />;
  if (view === "tickers") return <TickerPage onSwitchView={() => setView("dashboard")} />;
  if (view === "rag") return <RagPage onSwitchView={() => setView("dashboard")} />;
  if (view === "elastic") return <ElasticPage onSwitchView={() => setView("dashboard")} />;
  if (view === "search") {
    return (
      <GlobalSearchPage
        onSwitchView={() => setView("dashboard")}
        onSelectTicker={handleSelectTicker}
      />
    );
  }
  if (view === "contracts-dashboard") {
    return (
      <ContractsDashboardPage
        onSwitchView={() => setView("dashboard")}
        onSwitchSearch={() => setView("contracts-search")}
      />
    );
  }
  if (view === "contracts-search" || view === "contracts") {
    return (
      <ContractsSearchPage
        onSwitchView={() => setView("dashboard")}
        onSwitchDashboard={() => setView("contracts-dashboard")}
      />
    );
  }
  if (view === "companies-search" || view === "companies") {
    const handleSelectCompany = (nif: string | null) => {
      if (!nif) return;
      setSelectedCompany(nif);
      setView("company-detail");
    };
    return (
      <CompanyDirectoryPage
        onSwitchView={() => setView("dashboard")}
        onSwitchDashboard={() => setView("companies-dashboard")}
        onSelectCompany={handleSelectCompany}
      />
    );
  }
  if (view === "companies-dashboard") {
    const handleSelectCompany = (nif: string | null) => {
      if (!nif) return;
      setSelectedCompany(nif);
      setView("company-detail");
    };
    return (
      <CompanyDashboardPage
        onSwitchView={() => setView("companies-search")}
        onSwitchSearch={() => setView("companies-search")}
        onSelectCompany={handleSelectCompany}
      />
    );
  }
  if (view === "company-detail" && selectedCompany) {
    return (
      <CompanyDetailPage
        nif={selectedCompany}
        onBack={() => setView("companies-search")}
        onSwitchDashboard={() => setView("companies-dashboard")}
      />
    );
  }
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
      onSwitchSearch={() => setView("search")}
      onSwitchTrading={() => setView("trading")}
      onSwitchContracts={() => setView("contracts-search")}
      onSwitchContractsDashboard={() => setView("contracts-dashboard")}
      onSwitchContractsSearch={() => setView("contracts-search")}
      onSwitchCompanies={() => setView("companies-search")}
      onSwitchCompaniesDashboard={() => setView("companies-dashboard")}
      onSwitchCompaniesSearch={() => setView("companies-search")}
    />
  );
}

