/**
 * Escopo ativo do módulo de portfólio.
 *
 * Os módulos (sumário, relatórios, previsões, otimização, attribution e risco)
 * calculam sempre sobre uma **carteira do utilizador**. A escolha é guardada no
 * URL (`?portfolio=<id>`) — para os links entre módulos a manterem — e em
 * `localStorage`, para sobreviver a navegações sem parâmetros.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { getPortfolioSources, type PortfolioSources, type SavedPortfolio, type SavedWatchlist } from "./portfolioApi";

const STORAGE_KEY = "iqos-portfolio-id";

export function readStoredPortfolioId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function storePortfolioId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* modo privado: ignora */
  }
}

/** `?portfolio=` do URL, com recurso ao último escolhido. */
export function portfolioIdFromUrl(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get("portfolio");
  return fromUrl || readStoredPortfolioId();
}

/** Junta o escopo a um caminho interno (`/portfolio/risk?portfolio=…`). */
export function withPortfolioScope(path: string, portfolioId: string | null): string {
  if (!portfolioId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}portfolio=${encodeURIComponent(portfolioId)}`;
}

export type PortfolioScope = {
  portfolios: SavedPortfolio[];
  watchlists: SavedWatchlist[];
  /** Carteira em uso; `null` = carteira de demonstração. */
  portfolioId: string | null;
  active: SavedPortfolio | null;
  loading: boolean;
  error: string | null;
  select: (id: string | null) => void;
  reload: () => Promise<void>;
  setSourcesAfterMutation: (sources: PortfolioSources) => void;
};

export function usePortfolioScope(): PortfolioScope {
  const [sources, setSources] = useState<PortfolioSources>({
    portfolios: [],
    watchlists: [],
    has_portfolio: false,
    has_watchlist: false,
  });
  const [portfolioId, setPortfolioId] = useState<string | null>(() => portfolioIdFromUrl());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getPortfolioSources();
      setSources(next);
      setPortfolioId((current) => {
        if (current && next.portfolios.some((pf) => pf.id === current)) return current;
        const fallback = next.portfolios[0]?.id ?? null;
        storePortfolioId(fallback);
        return fallback;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar carteiras");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const select = useCallback((id: string | null) => {
    setPortfolioId(id);
    storePortfolioId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("portfolio", id);
    else url.searchParams.delete("portfolio");
    window.history.replaceState(window.history.state, "", url.toString());
  }, []);

  const active = useMemo(
    () => sources.portfolios.find((pf) => pf.id === portfolioId) ?? null,
    [sources.portfolios, portfolioId],
  );

  return {
    portfolios: sources.portfolios,
    watchlists: sources.watchlists,
    portfolioId,
    active,
    loading,
    error,
    select,
    reload: load,
    setSourcesAfterMutation: setSources,
  };
}
