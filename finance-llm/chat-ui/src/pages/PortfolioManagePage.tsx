import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Briefcase,
  Eye,
  ListOrdered,
  Plus,
  RefreshCw,
  Trash2,
  ArrowUpRight,
  ArrowDownRight,
  Wallet,
  AlertTriangle,
  Upload,
} from "lucide-react";
import {
  addPortfolioTicker,
  addWatchlistItem,
  cancelOrder,
  createPortfolio,
  createWatchlist,
  deletePortfolio,
  deleteWatchlist,
  importPortfolioCsv,
  listOrders,
  listPortfolios,
  listWatchlists,
  placeOrder,
  removePortfolioTicker,
  removeWatchlistItem,
  type SavedOrder,
  type SavedPortfolio,
  type SavedWatchlist,
  type TickerSearchItem,
} from "../portfolioApi";
import { TickerPicker } from "../components/portfolio/TickerPicker";
import { PortfolioLoading } from "../components/portfolio/PortfolioLoading";
import { portfolioIdFromUrl } from "../portfolioScope";

type Tab = "carteiras" | "watchlists" | "ordens";

export function PortfolioManagePage() {
  const [tab, setTab] = useState<Tab>("carteiras");
  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [watchlists, setWatchlists] = useState<SavedWatchlist[]>([]);
  const [orders, setOrders] = useState<SavedOrder[]>([]);
  // Chega j? com a carteira escolhida no dashboard (`?portfolio=`).
  const [selectedPortfolio, setSelectedPortfolio] = useState<string | null>(() => portfolioIdFromUrl());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pfs, wls, ords] = await Promise.all([listPortfolios(), listWatchlists(), listOrders()]);
      setPortfolios(pfs);
      setWatchlists(wls);
      setOrders(ords);
      setSelectedPortfolio((prev) => prev ?? pfs[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar dados");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = useMemo(
    () => portfolios.find((p) => p.id === selectedPortfolio) ?? portfolios[0] ?? null,
    [portfolios, selectedPortfolio],
  );

  const run = async (fn: () => Promise<unknown>, message?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      await load();
      if (message) setNotice(message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Operação falhou");
    } finally {
      setBusy(false);
    }
  };

  const runImport = async (file: File) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const text = await file.text();
      const rows = parseCsvRows(text);
      const result = await importPortfolioCsv({
        name: file.name.replace(/\.csv$/i, ""),
        currency: "EUR",
        deposit_cash: true,
        future_dates_as_today: true,
        rows,
      });
      await load();
      if (result.skipped?.length) {
        setNotice(`${result.imported} posições importadas. ${result.skipped.length} linhas ignoradas.`);
      } else if (result.imported > 0) {
        setNotice("Carteira importada do CSV.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Importação falhou");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0b0d10] p-4 text-slate-200 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <Briefcase className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-white">Gestão de carteiras</h1>
              <p className="text-sm text-slate-400">
                Crie carteiras, adicione tickers, acompanhe watchlists e registe ordens. Cada conta tem o seu
                próprio índice de dados.
              </p>
            </div>
          </div>
          <button
            onClick={() => void load()}
            disabled={busy}
            className="inline-flex items-center gap-2 self-start rounded-md bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${busy || loading ? "animate-spin" : ""}`} />
            Atualizar
          </button>
        </header>

        <nav className="flex flex-wrap gap-2">
          {(
            [
              { id: "carteiras", label: "Carteiras", icon: Briefcase },
              { id: "watchlists", label: "Watchlists", icon: Eye },
              { id: "ordens", label: "Ordens", icon: ListOrdered },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={[
                "inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium transition",
                tab === id ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700",
              ].join(" ")}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>

        {error && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-200">{error}</div>
        )}
        {notice && (
          <div className="rounded-lg border border-emerald-900/50 bg-emerald-950/30 p-3 text-sm text-emerald-200">
            {notice}
          </div>
        )}

        {loading && portfolios.length === 0 && watchlists.length === 0 ? (
          <PortfolioLoading />
        ) : (
          <>
            {tab === "carteiras" && (
              <CarteirasTab
                portfolios={portfolios}
                active={active}
                busy={busy}
                onSelect={setSelectedPortfolio}
                onCreate={(name, cash, currency) =>
                  run(() => createPortfolio({ name, cash, currency }), `Carteira "${name}" criada.`)
                }
                onDelete={(id) => run(() => deletePortfolio(id), "Carteira apagada.")}
                onAddTicker={(portfolioId, item, quantity, avgPrice) =>
                  run(
                    () =>
                      addPortfolioTicker(portfolioId, {
                        ticker: item.ticker,
                        name: item.name,
                        quantity,
                        avg_price: avgPrice,
                        fill_price: avgPrice <= 0,
                      }),
                    `${item.ticker} adicionado.`,
                  )
                }
                onRemoveTicker={(portfolioId, ticker) =>
                  run(() => removePortfolioTicker(portfolioId, ticker), `${ticker} removido.`)
                }
                onImportCsv={(file) => void runImport(file)}
              />
            )}

            {tab === "watchlists" && (
              <WatchlistsTab
                watchlists={watchlists}
                busy={busy}
                onCreate={(name) => run(() => createWatchlist({ name }), `Watchlist "${name}" criada.`)}
                onDelete={(id) => run(() => deleteWatchlist(id), "Watchlist apagada.")}
                onAddItem={(listId, item) =>
                  run(() => addWatchlistItem(listId, { ticker: item.ticker, name: item.name }), `${item.ticker} adicionado.`)
                }
                onRemoveItem={(listId, ticker) =>
                  run(() => removeWatchlistItem(listId, ticker), `${ticker} removido.`)
                }
              />
            )}

            {tab === "ordens" && (
              <OrdensTab
                portfolios={portfolios}
                orders={orders}
                busy={busy}
                selectedPortfolio={active?.id ?? null}
                onPlace={(payload) => run(() => placeOrder(payload), "Ordem executada.")}
                onCancel={(orderId) => run(() => cancelOrder(orderId), "Ordem cancelada.")}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Carteiras
// ---------------------------------------------------------------------------
type CarteirasTabProps = {
  portfolios: SavedPortfolio[];
  active: SavedPortfolio | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: (name: string, cash: number, currency: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onAddTicker: (portfolioId: string, item: TickerSearchItem, quantity: number, avgPrice: number) => Promise<void>;
  onRemoveTicker: (portfolioId: string, ticker: string) => Promise<void>;
  onImportCsv?: (file: File) => void;
};

function CarteirasTab({
  portfolios,
  active,
  busy,
  onSelect,
  onCreate,
  onDelete,
  onAddTicker,
  onRemoveTicker,
  onImportCsv,
}: CarteirasTabProps) {
  const [name, setName] = useState("");
  const [cash, setCash] = useState(100000);
  const [currency, setCurrency] = useState("USD");
  const [quantity, setQuantity] = useState(0);
  const [avgPrice, setAvgPrice] = useState(0);

  const create = async () => {
    const clean = name.trim();
    if (!clean) return;
    await onCreate(clean, Number(cash) || 0, currency);
    setName("");
  };

  const add = async (item: TickerSearchItem) => {
    if (!active) return;
    await onAddTicker(active.id, item, Number(quantity) || 0, Number(avgPrice) || 0);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            <Plus className="h-4 w-4" /> Nova carteira
          </h2>
          <div className="space-y-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Nome da carteira"
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
            />
            <div className="flex gap-2">
              <input
                type="number"
                value={cash}
                onChange={(e) => setCash(Number(e.target.value))}
                placeholder="Caixa inicial"
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
              />
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
              >
                {["USD", "EUR", "GBP"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={() => void create()}
              disabled={busy || !name.trim()}
              className="w-full rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Criar carteira
            </button>
          </div>
        </div>

        {onImportCsv && <CsvImportCard busy={busy} onImport={onImportCsv} />}

        <div className="rounded-lg border border-slate-800 bg-slate-900/50">
          <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            As minhas carteiras
          </h2>
          {portfolios.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-500">Ainda não tem carteiras.</p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {portfolios.map((pf) => (
                <li key={pf.id}>
                  <button
                    onClick={() => onSelect(pf.id)}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-4 py-3 text-left transition",
                      active?.id === pf.id ? "bg-emerald-600/10" : "hover:bg-slate-800/60",
                    ].join(" ")}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-100">{pf.name}</span>
                      <span className="block text-xs text-slate-500">
                        {pf.ticker_count} tickers · {pf.currency} {pf.cash.toLocaleString()}
                      </span>
                    </span>
                    <Trash2
                      className="h-4 w-4 shrink-0 text-slate-600 hover:text-rose-400"
                      onClick={(event) => {
                        event.stopPropagation();
                        void onDelete(pf.id);
                      }}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {!active ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
            Crie uma carteira para começar a adicionar tickers.
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Kpi label="Carteira" value={active.name} icon={Briefcase} />
              <Kpi label="Posições" value={String(active.ticker_count)} icon={ListOrdered} />
              <Kpi label="Caixa" value={`${active.currency} ${active.cash.toLocaleString()}`} icon={Wallet} />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                Adicionar ticker
              </h2>
              <div className="grid gap-2 md:grid-cols-[1fr_120px_120px]">
                <TickerPicker onPick={(item) => void add(item)} />
                <input
                  type="number"
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                  placeholder="Qtd."
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
                />
                <input
                  type="number"
                  value={avgPrice}
                  onChange={(e) => setAvgPrice(Number(e.target.value))}
                  placeholder="Preço médio (0 = mercado)"
                  className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
                />
              </div>
            </div>

            <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50">
              <table className="w-full text-sm">
                <thead className="bg-slate-900 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Ticker</th>
                    <th className="px-4 py-2">Nome</th>
                    <th className="px-4 py-2 text-right">Qtd.</th>
                    <th className="px-4 py-2 text-right">Preço médio</th>
                    <th className="px-4 py-2 text-right">Custo</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {active.tickers.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                        Sem posições. Pesquise um ticker acima.
                      </td>
                    </tr>
                  )}
                  {active.tickers.map((position) => (
                    <tr key={position.ticker}>
                      <td className="px-4 py-2 font-medium text-slate-100">{position.ticker}</td>
                      <td className="px-4 py-2 text-slate-400">{position.name}</td>
                      <td className="px-4 py-2 text-right text-slate-300">{position.quantity}</td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {position.avg_price ? position.avg_price.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {position.avg_price && position.quantity
                          ? (position.avg_price * position.quantity).toLocaleString(undefined, {
                              maximumFractionDigits: 2,
                            })
                          : "—"}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => void onRemoveTicker(active.id, position.ticker)}
                          className="text-slate-600 hover:text-rose-400"
                          aria-label={`Remover ${position.ticker}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Watchlists
// ---------------------------------------------------------------------------
function WatchlistsTab({
  watchlists,
  busy,
  onCreate,
  onDelete,
  onAddItem,
  onRemoveItem,
}: {
  watchlists: SavedWatchlist[];
  busy: boolean;
  onCreate: (name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onAddItem: (listId: string, item: TickerSearchItem) => Promise<void>;
  onRemoveItem: (listId: string, ticker: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const active = watchlists.find((w) => w.id === activeId) ?? watchlists[0] ?? null;

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
            <Plus className="h-4 w-4" /> Nova watchlist
          </h2>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nome da watchlist"
            className="mb-2 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
          />
          <button
            onClick={async () => {
              if (!name.trim()) return;
              await onCreate(name.trim());
              setName("");
            }}
            disabled={busy || !name.trim()}
            className="w-full rounded-md bg-cyan-600 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            Criar watchlist
          </button>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/50">
          <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            As minhas watchlists
          </h2>
          {watchlists.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-500">Ainda não tem watchlists.</p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {watchlists.map((list) => (
                <li key={list.id}>
                  <button
                    onClick={() => setActiveId(list.id)}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-4 py-3 text-left",
                      active?.id === list.id ? "bg-cyan-600/10" : "hover:bg-slate-800/60",
                    ].join(" ")}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-100">{list.name}</span>
                      <span className="block text-xs text-slate-500">{list.item_count} tickers</span>
                    </span>
                    <Trash2
                      className="h-4 w-4 shrink-0 text-slate-600 hover:text-rose-400"
                      onClick={(event) => {
                        event.stopPropagation();
                        void onDelete(list.id);
                      }}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {!active ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
            Crie uma watchlist para acompanhar tickers.
          </div>
        ) : (
          <>
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                Adicionar a «{active.name}»
              </h2>
              <TickerPicker onPick={(item) => void onAddItem(active.id, item)} />
            </div>

            <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50">
              <table className="w-full text-sm">
                <thead className="bg-slate-900 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Ticker</th>
                    <th className="px-4 py-2">Nome</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {active.items.length === 0 && (
                    <tr>
                      <td colSpan={3} className="px-4 py-6 text-center text-slate-500">
                        Watchlist vazia.
                      </td>
                    </tr>
                  )}
                  {active.items.map((item) => (
                    <tr key={item.ticker}>
                      <td className="px-4 py-2 font-medium text-slate-100">{item.ticker}</td>
                      <td className="px-4 py-2 text-slate-400">{item.name}</td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => void onRemoveItem(active.id, item.ticker)}
                          className="text-slate-600 hover:text-rose-400"
                          aria-label={`Remover ${item.ticker}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ordens
// ---------------------------------------------------------------------------
function OrdensTab({
  portfolios,
  orders,
  busy,
  selectedPortfolio,
  onPlace,
  onCancel,
}: {
  portfolios: SavedPortfolio[];
  orders: SavedOrder[];
  busy: boolean;
  selectedPortfolio: string | null;
  onPlace: (payload: {
    portfolio_id: string;
    ticker: string;
    side: "buy" | "sell";
    quantity: number;
    order_type?: "market" | "limit";
    limit_price?: number;
  }) => Promise<void>;
  onCancel: (orderId: string) => Promise<void>;
}) {
  const [portfolioId, setPortfolioId] = useState(selectedPortfolio ?? "");
  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [quantity, setQuantity] = useState(1);
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [limitPrice, setLimitPrice] = useState(0);

  useEffect(() => {
    if (!portfolioId && selectedPortfolio) setPortfolioId(selectedPortfolio);
  }, [portfolioId, selectedPortfolio]);

  const submit = async () => {
    if (!portfolioId || !ticker.trim() || quantity <= 0) return;
    await onPlace({
      portfolio_id: portfolioId,
      ticker: ticker.trim().toUpperCase(),
      side,
      quantity: Number(quantity),
      order_type: orderType,
      limit_price: orderType === "limit" ? Number(limitPrice) : 0,
    });
    setTicker("");
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">Nova ordem</h2>
        <div className="space-y-2">
          <select
            value={portfolioId}
            onChange={(e) => setPortfolioId(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
          >
            <option value="">Selecionar carteira…</option>
            {portfolios.map((pf) => (
              <option key={pf.id} value={pf.id}>
                {pf.name} ({pf.currency})
              </option>
            ))}
          </select>

          <TickerPicker
            onPick={(item) => setTicker(item.ticker)}
            placeholder="Ticker (pesquise ou escreva)"
          />
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="Ticker"
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
          />

          <div className="flex gap-2">
            <button
              onClick={() => setSide("buy")}
              className={[
                "flex-1 rounded-md px-3 py-2 text-sm font-semibold",
                side === "buy" ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-300",
              ].join(" ")}
            >
              <ArrowUpRight className="mr-1 inline h-4 w-4" />
              Comprar
            </button>
            <button
              onClick={() => setSide("sell")}
              className={[
                "flex-1 rounded-md px-3 py-2 text-sm font-semibold",
                side === "sell" ? "bg-rose-600 text-white" : "bg-slate-800 text-slate-300",
              ].join(" ")}
            >
              <ArrowDownRight className="mr-1 inline h-4 w-4" />
              Vender
            </button>
          </div>

          <div className="flex gap-2">
            <input
              type="number"
              value={quantity}
              min={1}
              onChange={(e) => setQuantity(Number(e.target.value))}
              placeholder="Qtd."
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
            />
            <select
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as "market" | "limit")}
              className="rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
            >
              <option value="market">Mercado</option>
              <option value="limit">Limite</option>
            </select>
          </div>

          {orderType === "limit" && (
            <input
              type="number"
              value={limitPrice}
              onChange={(e) => setLimitPrice(Number(e.target.value))}
              placeholder="Preço limite"
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:outline-none"
            />
          )}

          <button
            onClick={() => void submit()}
            disabled={busy || !portfolioId || !ticker.trim() || quantity <= 0}
            className="w-full rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-600 disabled:opacity-50"
          >
            Enviar ordem
          </button>
          <p className="flex items-start gap-1 text-[11px] text-slate-500">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            O preço de execução é a cotação ao vivo do Yahoo Finance. Ordens limite ficam pendentes até o preço
            satisfazer o limite.
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50">
        <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          Histórico de ordens
        </h2>
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2">Data</th>
              <th className="px-4 py-2">Ticker</th>
              <th className="px-4 py-2">Lado</th>
              <th className="px-4 py-2 text-right">Qtd.</th>
              <th className="px-4 py-2 text-right">Preço</th>
              <th className="px-4 py-2">Estado</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {orders.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                  Sem ordens registadas.
                </td>
              </tr>
            )}
            {orders.map((order) => (
              <tr key={order.id}>
                <td className="px-4 py-2 text-slate-400">
                  {order.placed_at ? new Date(order.placed_at).toLocaleString() : "—"}
                </td>
                <td className="px-4 py-2 font-medium text-slate-100">{order.ticker}</td>
                <td className={`px-4 py-2 ${order.side === "buy" ? "text-emerald-400" : "text-rose-400"}`}>
                  {order.side === "buy" ? "Compra" : "Venda"}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">{order.quantity}</td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {order.filled_price ? order.filled_price.toFixed(2) : "—"}
                </td>
                <td className="px-4 py-2">
                  <StatusBadge status={order.status} />
                </td>
                <td className="px-4 py-2 text-right">
                  {order.status === "pending" && (
                    <button
                      onClick={() => void onCancel(order.id)}
                      className="text-xs text-amber-400 hover:text-amber-300"
                    >
                      Cancelar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: SavedOrder["status"] }) {
  const styles: Record<SavedOrder["status"], string> = {
    filled: "bg-emerald-500/10 text-emerald-400",
    pending: "bg-amber-500/10 text-amber-400",
    cancelled: "bg-slate-500/10 text-slate-400",
    rejected: "bg-rose-500/10 text-rose-400",
  };
  const labels: Record<SavedOrder["status"], string> = {
    filled: "Executada",
    pending: "Pendente",
    cancelled: "Cancelada",
    rejected: "Rejeitada",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? styles.pending}`}>
      {labels[status] ?? status}
    </span>
  );
}

function Kpi({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-2 truncate text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function parseCsvRows(text: string): { symbol: string; side?: string; quantity?: number; price?: number; fees?: number; date?: string; note?: string }[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim().toLowerCase().replace(/\s+/g, "_"));
  const col = (name: string, ...fallbacks: string[]) => {
    for (const n of [name, ...fallbacks]) {
      const idx = headers.findIndex((h) => h === n.toLowerCase());
      if (idx >= 0) return idx;
    }
    return -1;
  };
  const symbolIdx = col("symbol", "ticker", "ativo");
  const sideIdx = col("transaction_type", "side", "tipo");
  const qtyIdx = col("quantity", "qty", "quantidade", "shares");
  const priceIdx = col("purchase_price", "price", "preço", "preco");
  const feeIdx = col("commission", "fees", "comissao", "comissão");
  const dateIdx = col("trade_date", "date", "data");
  const noteIdx = col("comment", "notes", "nota", "note");
  if (symbolIdx < 0) return [];
  const out: ReturnType<typeof parseCsvRows> = [];
  for (let i = 1; i < lines.length; i++) {
    const raw = parseCsvLine(lines[i]);
    if (!raw[symbolIdx]?.trim()) continue;
    const symbol = raw[symbolIdx].trim();
    const sideRaw = sideIdx >= 0 ? raw[sideIdx]?.trim().toLowerCase() : "";
    const side = symbol.startsWith("$") || symbol.toLowerCase() === "cash_tx" ? "deposit" : sideRaw === "sell" ? "sell" : "buy";
    out.push({
      symbol,
      side,
      quantity: qtyIdx >= 0 ? parseFloatLocale(raw[qtyIdx]) : undefined,
      price: priceIdx >= 0 ? parseFloatLocale(raw[priceIdx]) : undefined,
      fees: feeIdx >= 0 ? parseFloatLocale(raw[feeIdx]) : undefined,
      date: dateIdx >= 0 ? raw[dateIdx] || undefined : undefined,
      note: noteIdx >= 0 ? raw[noteIdx] || undefined : undefined,
    });
  }
  return out;
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let inQuotes = false;
  for (const ch of line) {
    if (ch === '"') {
      inQuotes = !inQuotes;
      continue;
    }
    if (ch === "," && !inQuotes) {
      cells.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  cells.push(current);
  return cells;
}

function parseFloatLocale(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const normalized = value.trim().replace(/\./g, "").replace(",", ".");
  const n = Number(normalized);
  return Number.isFinite(n) ? n : undefined;
}

function CsvImportCard({ busy, onImport }: { busy: boolean; onImport: (file: File) => void }) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onImport(file);
    if (inputRef.current) inputRef.current.value = "";
  };
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
        <Upload className="h-4 w-4" /> Importar CSV
      </h2>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) onImport(f); }}
        className={[
          "flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center transition",
          drag ? "border-emerald-500 bg-emerald-500/10" : "border-slate-700 hover:border-slate-500",
        ].join(" ")}
        onClick={() => inputRef.current?.click()}
      >
        <Upload className="h-6 w-6 text-slate-500" />
        <span className="text-sm text-slate-300">Arraste um CSV ou clique para escolher</span>
        <span className="text-xs text-slate-500">Colunas: Symbol, Transaction Type, Quantity, Purchase Price, Commission, Trade Date, Comment</span>
      </div>
      <input ref={inputRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onChange} disabled={busy} />
    </div>
  );
}

