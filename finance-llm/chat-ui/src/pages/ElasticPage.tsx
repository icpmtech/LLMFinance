import { useEffect, useState } from "react";
import { ArrowLeft, Database, Search, Trash2, Upload, Activity } from "lucide-react";
import {
  getElasticStatus,
  ingestElasticPrices,
  ingestElasticNews,
  ingestElasticTicker,
  searchElasticPrices,
  searchElasticNews,
  listElasticTickers,
  deleteElasticTicker,
} from "../api";
import type {
  ElasticStatus,
  ElasticSearchPoint,
  ElasticSearchNewsItem,
} from "../types";

interface ElasticPageProps {
  onSwitchView: () => void;
}

const formatDate = (d?: string) => {
  if (!d) return "-";
  try {
    return new Date(d).toLocaleDateString();
  } catch {
    return d;
  }
};

export function ElasticPage({ onSwitchView }: ElasticPageProps) {
  const [status, setStatus] = useState<ElasticStatus | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [ticker, setTicker] = useState("");
  const [period, setPeriod] = useState("1y");
  const [interval, setInterval] = useState("1d");
  const [query, setQuery] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [prices, setPrices] = useState<ElasticSearchPoint[]>([]);
  const [news, setNews] = useState<ElasticSearchNewsItem[]>([]);
  const [activeTab, setActiveTab] = useState<"prices" | "news">("prices");

  const show = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(null), 5000);
  };

  const refreshStatus = async () => {
    try {
      const s = await getElasticStatus();
      setStatus(s);
    } catch (err) {
      setStatus({
        available: false,
        message: err instanceof Error ? err.message : "Erro desconhecido",
      });
    }
  };

  const refreshTickers = async () => {
    try {
      const t = await listElasticTickers();
      setTickers(t.tickers);
    } catch {
      setTickers([]);
    }
  };

  useEffect(() => {
    refreshStatus();
    refreshTickers();
  }, []);

  const handleIngestPrices = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticPrices(ticker.trim().toUpperCase(), period, interval);
      show(`Preços: ${res.indexed_count}/${res.total_points} indexados`);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar preços");
    } finally {
      setLoading(false);
    }
  };

  const handleIngestNews = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticNews(ticker.trim().toUpperCase());
      show(`Notícias: ${res.indexed_count}/${res.total_items} indexadas`);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar notícias");
    } finally {
      setLoading(false);
    }
  };

  const handleIngestAll = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await ingestElasticTicker(ticker.trim().toUpperCase(), { period, interval });
      show(
        `Indexado ${res.ticker}: ${res.prices.indexed_count} preços, ${res.news.indexed_count} notícias`,
      );
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao indexar ticker");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchPrices = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await searchElasticPrices(
        ticker.trim().toUpperCase(),
        startDate || undefined,
        endDate || undefined,
      );
      setPrices(res.points);
      setActiveTab("prices");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao pesquisar preços");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchNews = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    try {
      const res = await searchElasticNews(
        ticker.trim().toUpperCase(),
        query || undefined,
        startDate || undefined,
        endDate || undefined,
      );
      setNews(res.items);
      setActiveTab("news");
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao pesquisar notícias");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!ticker.trim()) return;
    if (!window.confirm(`Apagar todos os dados Elasticsearch para ${ticker.trim().toUpperCase()}?`)) return;
    setLoading(true);
    try {
      const res = await deleteElasticTicker(ticker.trim().toUpperCase());
      show(
        `Apagado ${res.ticker}: ${res.prices_deleted ?? 0} preços, ${res.news_deleted ?? 0} notícias`,
      );
      setPrices([]);
      setNews([]);
      await refreshTickers();
    } catch (err) {
      show(err instanceof Error ? err.message : "Erro ao apagar dados");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={onSwitchView}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border hover:bg-accent transition"
            >
              <ArrowLeft size={18} /> Voltar
            </button>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Database size={28} /> Elasticsearch
            </h1>
          </div>
          <button
            onClick={() => {
              refreshStatus();
              refreshTickers();
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition"
          >
            <Activity size={18} /> Atualizar estado
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2 flex items-center gap-2">
              <Activity size={18} /> Estado
            </h2>
            <p>
              <span className={status?.available ? "text-green-500" : "text-red-500"}>
                {status?.available ? "Disponível" : "Indisponível"}
              </span>
            </p>
            <p className="text-sm text-muted-foreground">{status?.message}</p>
            {status?.version && <p className="text-sm">v{status.version}</p>}
          </div>

          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2 flex items-center gap-2">
              <Database size={18} /> Tickers indexados
            </h2>
            <p className="text-2xl font-bold">{tickers.length}</p>
            <p className="text-sm text-muted-foreground truncate">
              {tickers.slice(0, 6).join(", ")}
              {tickers.length > 6 ? "..." : ""}
            </p>
          </div>

          <div className="p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold mb-2">Ações rápidas</h2>
            <p className="text-sm text-muted-foreground">
              Use o formulário abaixo para indexar preços, notícias e pesquisar por ticker.
            </p>
          </div>
        </div>

        {message && (
          <div className="p-3 rounded-lg bg-accent border border-border text-sm">{message}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4 p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold flex items-center gap-2">
              <Upload size={18} /> Ingestão
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="Ticker (ex: AAPL)"
                className="px-3 py-2 rounded-lg bg-background border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
              >
                <option value="1mo">1 mês</option>
                <option value="3mo">3 meses</option>
                <option value="6mo">6 meses</option>
                <option value="1y">1 ano</option>
                <option value="2y">2 anos</option>
                <option value="5y">5 anos</option>
                <option value="10y">10 anos</option>
                <option value="max">Máximo</option>
              </select>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
              >
                <option value="1d">Diário</option>
                <option value="1wk">Semanal</option>
                <option value="1mo">Mensal</option>
              </select>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleIngestPrices}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar preços
              </button>
              <button
                onClick={handleIngestNews}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar notícias
              </button>
              <button
                onClick={handleIngestAll}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 hover:bg-primary/90 transition"
              >
                <Upload size={16} /> Indexar tudo
              </button>
            </div>
          </div>

          <div className="space-y-4 p-4 rounded-xl bg-card border border-border">
            <h2 className="font-semibold flex items-center gap-2">
              <Search size={18} /> Pesquisa
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
                placeholder="Data início"
              />
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="px-3 py-2 rounded-lg bg-background border border-border"
                placeholder="Data fim"
              />
            </div>

            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Termo nas notícias (opcional)"
              className="w-full px-3 py-2 rounded-lg bg-background border border-border"
            />

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleSearchPrices}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary text-secondary-foreground disabled:opacity-50 hover:bg-secondary/90 transition"
              >
                <Search size={16} /> Preços
              </button>
              <button
                onClick={handleSearchNews}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary text-secondary-foreground disabled:opacity-50 hover:bg-secondary/90 transition"
              >
                <Search size={16} /> Notícias
              </button>
              <button
                onClick={handleDelete}
                disabled={loading || !ticker.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive text-destructive-foreground disabled:opacity-50 hover:bg-destructive/90 transition"
              >
                <Trash2 size={16} /> Apagar
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-xl bg-card border border-border overflow-hidden">
          <div className="flex border-b border-border">
            <button
              onClick={() => setActiveTab("prices")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "prices" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Preços ({prices.length})
            </button>
            <button
              onClick={() => setActiveTab("news")}
              className={`px-4 py-2 text-sm font-medium ${
                activeTab === "news" ? "bg-accent text-foreground" : "text-muted-foreground"
              }`}
            >
              Notícias ({news.length})
            </button>
          </div>

          <div className="p-4 max-h-[500px] overflow-auto">
            {activeTab === "prices" ? (
              prices.length === 0 ? (
                <p className="text-muted-foreground text-sm">Sem preços para mostrar.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-muted-foreground border-b border-border">
                      <tr>
                        <th className="pb-2">Data</th>
                        <th className="pb-2">Abertura</th>
                        <th className="pb-2">Máxima</th>
                        <th className="pb-2">Mínima</th>
                        <th className="pb-2">Fecho</th>
                        <th className="pb-2">Volume</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prices.map((p, idx) => (
                        <tr key={idx} className="border-b border-border last:border-0">
                          <td className="py-2">{formatDate(p.date)}</td>
                          <td className="py-2">{p.open?.toFixed(2)}</td>
                          <td className="py-2">{p.high?.toFixed(2)}</td>
                          <td className="py-2">{p.low?.toFixed(2)}</td>
                          <td className="py-2">{p.close?.toFixed(2)}</td>
                          <td className="py-2">{p.volume?.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            ) : news.length === 0 ? (
              <p className="text-muted-foreground text-sm">Sem notícias para mostrar.</p>
            ) : (
              <div className="space-y-3">
                {news.map((n, idx) => (
                  <div key={idx} className="p-3 rounded-lg bg-background border border-border">
                    <h3 className="font-medium">{n.title || "Sem título"}</h3>
                    <p className="text-sm text-muted-foreground">
                      {n.publisher} • {formatDate(n.published)}
                    </p>
                    {n.summary && <p className="text-sm mt-1">{n.summary}</p>}
                    {n.url && (
                      <a
                        href={n.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm text-blue-500 hover:underline"
                      >
                        Ver fonte
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
