/**
 * Loja online IQ OS — catálogo, encomendas, clientes e promoções.
 *
 * A aplicação onde se **gere a loja**: produtos com preço, IVA, stock e imagens,
 * encomendas com pagamento registado à mão e seguimento, clientes, cupões,
 * métodos de envio, avaliações e as definições da vitrine.
 *
 * O resultado público vive em `/loja/…` (montra, ficha de produto, carrinho e
 * finalização de compra), servido pela própria API com carrinho no browser e
 * preços sempre recalculados no servidor.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgePercent,
  LayoutDashboard,
  Loader2,
  Package,
  RefreshCw,
  Search,
  Settings2,
  ShoppingBag,
  Star,
  Tags,
  Truck,
  Users,
  X,
} from "lucide-react";

import { Notice, timeAgo } from "../components/shop/ShopKit";
import { ShopCategoriesPanel, ShopCouponsPanel, ShopCustomersPanel, ShopReviewsPanel, ShopSettingsPanel, ShopShippingPanel } from "./ShopLibrary";
import { ShopOrdersPanel, ShopOverviewPanel, ShopProductsPanel, type ShopCtx, type ShopSection } from "./ShopPanels";
import * as shopApi from "../shopApi";
import type { ShopCatalogue, ShopOverview, ShopSearchHit } from "../shopApi";

export const SHOP_SECTIONS: { id: ShopSection; label: string; path: string; icon: React.ReactNode; hint: string }[] = [
  { id: "painel", label: "Painel", path: "/shop", icon: <LayoutDashboard size={13} />, hint: "Vendas, encomendas abertas e stock a acabar" },
  { id: "produtos", label: "Produtos", path: "/shop/produtos", icon: <Package size={13} />, hint: "Catálogo: preços, IVA, stock, imagens e publicação" },
  { id: "encomendas", label: "Encomendas", path: "/shop/encomendas", icon: <ShoppingBag size={13} />, hint: "Fila de trabalho, pagamentos e seguimento" },
  { id: "categorias", label: "Categorias", path: "/shop/categorias", icon: <Tags size={13} />, hint: "Arrumação do catálogo e menu da loja" },
  { id: "clientes", label: "Clientes", path: "/shop/clientes", icon: <Users size={13} />, hint: "Fichas de comprador e ligação ao CRM" },
  { id: "promocoes", label: "Promoções", path: "/shop/promocoes", icon: <BadgePercent size={13} />, hint: "Cupões de desconto e portes grátis" },
  { id: "envios", label: "Envios", path: "/shop/envios", icon: <Truck size={13} />, hint: "Métodos de entrega, custos e prazos" },
  { id: "avaliacoes", label: "Avaliações", path: "/shop/avaliacoes", icon: <Star size={13} />, hint: "Moderação e resposta às opiniões dos clientes" },
  { id: "definicoes", label: "Definições", path: "/shop/definicoes", icon: <Settings2 size={13} />, hint: "Contactos, impostos, pagamentos e aparência" },
];

/** Secção a partir do caminho (`/shop/...`). */
export function shopSectionFromPath(path: string): ShopSection {
  const clean = (path || "").replace(/\/+$/, "");
  const found = SHOP_SECTIONS.find((section) => section.path === clean);
  return found ? found.id : "painel";
}

export function shopPathForSection(section: ShopSection): string {
  return SHOP_SECTIONS.find((entry) => entry.id === section)?.path ?? "/shop";
}

const ENTITY_SECTION: Record<string, ShopSection> = {
  products: "produtos",
  orders: "encomendas",
  categories: "categorias",
  customers: "clientes",
  coupons: "promocoes",
  shipping: "envios",
  reviews: "avaliacoes",
};

export default function ShopPage() {
  const [section, setSection] = useState<ShopSection>(() => (typeof window === "undefined" ? "painel" : shopSectionFromPath(window.location.pathname)));
  const [catalogue, setCatalogue] = useState<ShopCatalogue | null>(null);
  const [overview, setOverview] = useState<ShopOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<{ id: number; message: string; tone: "info" | "error" | "ok" }[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ShopSearchHit[]>([]);
  const [searching, setSearching] = useState(false);

  const notify = useCallback((message: string, tone: "info" | "error" | "ok" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4200);
  }, []);

  const refreshOverview = useCallback(() => {
    void shopApi
      .getShopOverview()
      .then(setOverview)
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cataloguePayload, overviewPayload] = await Promise.all([shopApi.getShopCatalogue(), shopApi.getShopOverview()]);
      setCatalogue(cataloguePayload);
      setOverview(overviewPayload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A navegação da secção vive no caminho: `/shop/produtos`, `/shop/encomendas`…
  useEffect(() => {
    const onPop = () => setSection(shopSectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const changeSection = useCallback((next: ShopSection) => {
    setSection(next);
    if (typeof window !== "undefined") {
      const path = shopPathForSection(next);
      if (window.location.pathname !== path) window.history.pushState({}, "", path);
    }
  }, []);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setHits([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      void shopApi
        .searchShop(needle)
        .then((payload) => {
          if (!cancelled) setHits(payload.items);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 260);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const ctx: ShopCtx = useMemo(
    () => ({ catalogue: catalogue ?? ({} as ShopCatalogue), notify, refreshOverview }),
    [catalogue, notify, refreshOverview],
  );

  const openHit = useCallback(
    (hit: ShopSearchHit) => {
      setHits([]);
      setQuery("");
      const target = ENTITY_SECTION[hit.entity];
      if (target) changeSection(target);
    },
    [changeSection],
  );

  return (
    <div className="@container relative flex h-full min-h-[520px] flex-col bg-background text-foreground">
      <header className="sticky top-16 z-20 border-b border-white/8 bg-[#07151b]/85 pb-2 pt-2 backdrop-blur-xl md:top-0">
        <div className="flex flex-wrap items-center gap-2 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-teal-300 via-emerald-500 to-sky-600 text-white">
            <ShoppingBag size={15} />
          </span>
          <h1 className="text-[14px] font-semibold">Loja online</h1>
          {overview && (
            <>
              <span className="rounded-full bg-teal-400/15 px-2 py-0.5 text-[10.5px] text-teal-100">
                {overview.revenue.paid_orders} vendas · {overview.products.published} produto(s) à venda
              </span>
              {overview.orders.pending > 0 && (
                <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-[10.5px] text-amber-100">{overview.orders.pending} por pagar</span>
              )}
              {overview.reviews.pending > 0 && (
                <span className="rounded-full bg-violet-400/15 px-2 py-0.5 text-[10.5px] text-violet-100">{overview.reviews.pending} avaliação(ões) por moderar</span>
              )}
            </>
          )}
          <div className="min-w-0 flex-1" />

          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              className="w-[min(280px,60vw)] rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-7 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
              placeholder="Pesquisar na loja…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <button type="button" className="absolute right-2 top-2 text-muted-foreground hover:text-foreground" onClick={() => setQuery("")} title="Limpar">
                <X size={13} />
              </button>
            )}
            {(hits.length > 0 || searching) && (
              <div className="absolute right-0 top-full z-30 mt-1 w-[min(420px,92vw)] rounded-xl border border-white/12 bg-[#08181f] p-1.5 shadow-2xl">
                {searching && <p className="px-2 py-1.5 text-[11.5px] text-muted-foreground">A procurar…</p>}
                {hits.map((hit) => (
                  <button
                    key={`${hit.entity}-${hit.id}`}
                    type="button"
                    onClick={() => openHit(hit)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.08]"
                  >
                    <span className="rounded bg-white/[0.08] px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">{hit.entity}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] text-foreground">{hit.title || "(sem título)"}</span>
                      <span className="block truncate text-[10.5px] text-muted-foreground">{hit.subtitle}</span>
                    </span>
                    <span className="text-[10.5px] text-muted-foreground">{timeAgo(hit.updated_at)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <a
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
            href="/loja"
            target="_blank"
            rel="noreferrer"
            title="Abrir a loja pública"
          >
            Abrir loja
          </a>
          <button
            type="button"
            onClick={() => {
              void load();
              notify("Atualizado.", "ok");
            }}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.09] hover:text-foreground"
            title="Recarregar a loja"
          >
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>

        <div className="mx-4 mt-2 flex flex-wrap items-center gap-1 rounded-[8px] border border-white/8 bg-white/[0.05] p-0.5">
          {SHOP_SECTIONS.map((entry) => {
            const active = section === entry.id;
            return (
              <button
                key={entry.id}
                type="button"
                role="tab"
                aria-selected={active}
                title={entry.hint}
                onClick={() => changeSection(entry.id)}
                className={[
                  "flex shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 py-1 text-[12px] transition",
                  active ? "bg-white/[0.16] font-medium text-foreground shadow-sm" : "text-muted-foreground hover:bg-white/[0.07] hover:text-foreground",
                ].join(" ")}
              >
                <span className={active ? "text-teal-300" : undefined}>{entry.icon}</span>
                <span className="whitespace-nowrap">{entry.label}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error && (
          <div className="mb-3">
            <Notice tone="error">
              <AlertTriangle size={12} className="mr-1 inline" /> {error}
            </Notice>
          </div>
        )}

        {loading || !catalogue || !overview ? (
          <p className="flex items-center gap-2 py-16 text-[12.5px] text-muted-foreground">
            <Loader2 size={15} className="animate-spin" /> A carregar a loja…
          </p>
        ) : section === "painel" ? (
          <ShopOverviewPanel ctx={ctx} />
        ) : section === "produtos" ? (
          <ShopProductsPanel ctx={ctx} />
        ) : section === "encomendas" ? (
          <ShopOrdersPanel ctx={ctx} />
        ) : section === "categorias" ? (
          <ShopCategoriesPanel ctx={ctx} />
        ) : section === "clientes" ? (
          <ShopCustomersPanel ctx={ctx} />
        ) : section === "promocoes" ? (
          <ShopCouponsPanel ctx={ctx} />
        ) : section === "envios" ? (
          <ShopShippingPanel ctx={ctx} />
        ) : section === "avaliacoes" ? (
          <ShopReviewsPanel ctx={ctx} />
        ) : (
          <ShopSettingsPanel ctx={ctx} />
        )}
      </div>

      <div className="pointer-events-none fixed bottom-5 left-1/2 z-[140] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={[
              "pointer-events-auto rounded-xl border px-3.5 py-2 text-[12.5px] shadow-2xl backdrop-blur",
              toast.tone === "error"
                ? "border-rose-400/30 bg-rose-950/85 text-rose-100"
                : toast.tone === "ok"
                  ? "border-emerald-400/30 bg-emerald-950/85 text-emerald-100"
                  : "border-white/12 bg-[#08181f]/95 text-foreground",
            ].join(" ")}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
