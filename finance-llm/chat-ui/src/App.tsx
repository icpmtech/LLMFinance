import { useState, useCallback, useEffect } from "react";
import { ChatLayout } from "./components/ChatLayout";
import { AppNav, type AppView as AppNavView } from "./components/AppNav";
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
import EmpresasIQPage from "./pages/EmpresasIQPage";
import { sendChat } from "./sendChat";
import type { Message, ModelBackend } from "./types";

type AppView = AppNavView | "chat" | "ticker-detail" | "empresas-iq";
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
      if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) return "empresas-iq";
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
    const onPop = () => {
      if (typeof window === "undefined") return;
      const path = window.location.pathname.replace(/\/$/, "");
      let next: AppView = "dashboard";
      if (path === "/chat") next = "chat";
      else if (path === "/dashboard") next = "dashboard";
      else if (path === "/forecast") next = "forecast";
      else if (path === "/trading") next = "trading";
      else if (path === "/tickers") next = "tickers";
      else if (path.startsWith("/tickers/")) {
        const symbol = path.replace("/tickers/", "").split("/")[0];
        if (symbol) setSelectedTicker(symbol);
        next = "ticker-detail";
      } else if (path === "/rag") next = "rag";
      else if (path === "/elastic") next = "elastic";
      else if (path === "/search") next = "search";
      else if (path === "/contracts" || path === "/contracts/search") next = "contracts-search";
      else if (path === "/contracts/dashboard") next = "contracts-dashboard";
      else if (path === "/companies" || path === "/companies/search") next = "companies-search";
      else if (path === "/companies/dashboard") next = "companies-dashboard";
        else if (path === "/empresas-iq" || path.startsWith("/empresas-iq/")) next = "empresas-iq";
      else if (path.startsWith("/companies/")) {
        const nif = path.replace("/companies/", "").split("/")[0];
        if (nif) setSelectedCompany(nif);
        next = "company-detail";
      }
      setView(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

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

  const setViewAndHistory = useCallback((next: AppView) => {
    setView(next);
    let path = "/";
    if (next === "chat") path = "/chat";
    else if (next === "dashboard") path = "/dashboard";
    else if (next === "forecast") path = "/forecast";
    else if (next === "trading") path = "/trading";
    else if (next === "tickers" || next === "ticker-detail") path = selectedTicker ? `/tickers/${selectedTicker}` : "/tickers";
    else if (next === "rag") path = "/rag";
    else if (next === "elastic") path = "/elastic";
    else if (next === "search") path = "/search";
    else if (next === "contracts-search" || next === "contracts") path = "/contracts/search";
    else if (next === "contracts-dashboard") path = "/contracts/dashboard";
    else if (next === "companies-search" || next === "companies") path = "/companies/search";
    else if (next === "companies-dashboard") path = "/companies/dashboard";
    else if (next === "empresas-iq") path = "/empresas-iq";
    else if (next === "company-detail" && selectedCompany) path = `/companies/${selectedCompany}`;
    if (typeof window !== "undefined" && window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
  }, [selectedCompany, selectedTicker]);

  const handleSwitchView = (v: string) => {
    if (v === "tickers" || v === "tickers-old") {
      setViewAndHistory("tickers");
      return;
    }
    if (v === "ticker-detail") {
      if (!selectedTicker && typeof window !== "undefined") {
        const saved = localStorage.getItem(TICKER_DETAIL_KEY);
        setSelectedTicker(saved || "AAPL");
        setViewAndHistory("ticker-detail");
      } else {
        setViewAndHistory("ticker-detail");
      }
      return;
    }
    if (v === "search") {
      setViewAndHistory("search");
      return;
    }
    if (v === "trading") {
      setViewAndHistory("trading");
      return;
    }
    if (v === "contracts" || v === "contracts-search") {
      setViewAndHistory("contracts-search");
      return;
    }
    if (v === "contracts-dashboard") {
      setViewAndHistory("contracts-dashboard");
      return;
    }
    if (v === "companies" || v === "companies-search") {
      setViewAndHistory("companies-search");
      return;
    }
    if (v === "companies-dashboard") {
      setViewAndHistory("companies-dashboard");
      return;
    }
    if (v === "empresas-iq") {
      setViewAndHistory("empresas-iq");
      return;
    }
    setViewAndHistory(v as AppView);
  };

  const handleSelectTicker = (ticker: string) => {
    setSelectedTicker(ticker);
    setViewAndHistory("ticker-detail");
  };

  const renderContent = () => {
    if (view === "dashboard") return <DashboardPage onSwitchView={handleSwitchView} onSelectTicker={handleSelectTicker} />;
      if (view === "empresas-iq") return <EmpresasIQPage onNavigate={(v) => {
        if (v === "chat" || v === "dashboard" || v === "search" || v.startsWith("contracts") || v.startsWith("companies") || v === "tickers" || v === "forecast" || v === "trading" || v === "rag" || v === "elastic") {
          setViewAndHistory(v as AppView);
        }
      }} />;
    if (view === "ticker-detail" && selectedTicker) {
      return (
        <TickerDetailPage
          ticker={selectedTicker}
          onBack={() => setViewAndHistory("tickers")}
          onSwitchView={handleSwitchView}
        />
      );
    }
    if (view === "forecast") return <ForecastPage />;
    if (view === "trading") return <TradingPage />;
    if (view === "tickers") return <TickerPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (view === "rag") return <RagPage onSwitchView={() => setViewAndHistory("dashboard")} />;
    if (view === "elastic") return <ElasticPage />;
    if (view === "search") {
      return (
        <GlobalSearchPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSelectTicker={handleSelectTicker}
        />
      );
    }
    if (view === "contracts-dashboard") {
      return (
        <ContractsDashboardPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchSearch={() => setViewAndHistory("contracts-search")}
        />
      );
    }
    if (view === "contracts-search" || view === "contracts") {
      return (
        <ContractsSearchPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchDashboard={() => setViewAndHistory("contracts-dashboard")}
        />
      );
    }
    if (view === "companies-search" || view === "companies") {
      const handleSelectCompany = (nif: string | null) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      return (
        <CompanyDirectoryPage
          onSwitchView={() => setViewAndHistory("dashboard")}
          onSwitchDashboard={() => setViewAndHistory("companies-dashboard")}
          onSelectCompany={handleSelectCompany}
        />
      );
    }
    if (view === "companies-dashboard") {
      const handleSelectCompany = (nif: string | null) => {
        if (!nif) return;
        setSelectedCompany(nif);
        setViewAndHistory("company-detail");
      };
      return (
        <CompanyDashboardPage
          onSwitchView={() => setViewAndHistory("companies-search")}
          onSwitchSearch={() => setViewAndHistory("companies-search")}
          onSelectCompany={handleSelectCompany}
        />
      );
    }
    if (view === "company-detail" && selectedCompany) {
      return (
        <CompanyDetailPage
          nif={selectedCompany}
          onBack={() => setViewAndHistory("companies-search")}
          onSwitchDashboard={() => setViewAndHistory("companies-dashboard")}
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
        onNavigate={setViewAndHistory}
      />
    );
  };

  if (view === "chat") {
    return renderContent();
  }

  if (view === "empresas-iq") {
    return renderContent();
  }

  return (
    <div className="min-h-screen w-full bg-background text-foreground flex">
      <AppNav active={view as AppNavView} onNavigate={(v) => setViewAndHistory(v as AppView)} onBackToChat={() => setViewAndHistory("chat")} />
      <main className="flex-1 min-w-0 min-h-screen overflow-y-auto pt-14 md:pt-0">
        {renderContent()}
      </main>
    </div>
  );
}

