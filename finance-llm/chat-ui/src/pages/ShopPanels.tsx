/**
 * Painéis da loja online: panorama, produtos e encomendas.
 *
 * - **Painel** — vendas, encomendas por estado, stock a acabar, avaliações por
 *   moderar e atividade recente.
 * - **Produtos** — catálogo com ficha completa (preço, IVA, stock, imagens,
 *   atributos, SEO), publicação imediata ou agendada.
 * - **Encomendas** — fila de trabalho com estados, pagamentos registados à mão,
 *   notas internas, recibo imprimível e reposição de stock ao anular.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Ban,
  Boxes,
  CalendarClock,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Loader2,
  Package,
  Pencil,
  Printer,
  RefreshCw,
  Send,
  ShoppingBag,
  Truck,
  Trash2,
  Wallet,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import * as shopApi from "../shopApi";
import type { OrderStatus, ShopOrder, ShopOverview, ShopProduct, ShopStatus } from "../shopApi";
import {
  AttributesEditor,
  CheckList,
  Chip,
  EmptyState,
  IconAction,
  ImagePicker,
  ListRow,
  MiniBars,
  MoneyInput,
  NumberInput,
  PanelHeader,
  SelectInput,
  Sheet,
  StatCard,
  StatusPill,
  StatusTabs,
  Stars,
  TagsInput,
  TextArea,
  TextInput,
  Toggle,
  labelClass,
  money,
  percent,
  timeAgo,
} from "../components/shop/ShopKit";

export type ShopSection =
  | "painel"
  | "vitrine"
  | "produtos"
  | "categorias"
  | "encomendas"
  | "clientes"
  | "promocoes"
  | "envios"
  | "avaliacoes"
  | "definicoes";

export type ShopCtx = {
  catalogue: shopApi.ShopCatalogue;
  notify: (message: string, tone?: "info" | "error" | "ok") => void;
  refreshOverview: () => void;
};

const STATUS_TONES: Record<ShopStatus, string> = { rascunho: "slate", agendado: "amber", publicado: "emerald", arquivado: "zinc" };

function productStatusTone(status?: string): string {
  return STATUS_TONES[(status as ShopStatus) ?? "rascunho"] ?? "slate";
}

function orderTone(status?: string): string {
  return { pendente: "amber", pago: "sky", em_preparacao: "violet", enviado: "indigo", entregue: "emerald", cancelado: "rose", reembolsado: "zinc" }[status ?? ""] ?? "slate";
}

function paymentTone(status?: string): string {
  return { pendente: "amber", parcial: "sky", pago: "emerald", reembolsado: "zinc" }[status ?? ""] ?? "slate";
}

function emptyProduct(): Partial<ShopProduct> {
  return {
    name: "",
    sku: "",
    type: "fisico",
    status: "rascunho",
    price: 0,
    compare_at_price: 0,
    cost: 0,
    tax_rate: 23,
    stock: 0,
    stock_min: 0,
    track_stock: true,
    allow_backorder: false,
    unit: "un",
    category_ids: [],
    tags: [],
    image_ids: [],
    image_urls: [],
    attributes: [],
    featured: false,
    order: 0,
    short_description: "",
    description: "",
    internal_notes: "",
  };
}

/* ==================================================================== painel */

export function ShopOverviewPanel({ ctx }: { ctx: ShopCtx }) {
  const [overview, setOverview] = useState<ShopOverview | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    shopApi
      .getShopOverview()
      .then(setOverview)
      .catch((error: Error) => ctx.notify(error.message, "error"))
      .finally(() => setLoading(false));
  }, [ctx]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !overview) {
    return (
      <div className="flex items-center gap-2 px-1 py-8 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar o panorama da loja…
      </div>
    );
  }
  if (!overview) return <EmptyState title="Sem dados" hint="Não foi possível carregar o panorama." />;

  return (
    <div className="space-y-4">
      <PanelHeader title="Panorama da loja" hint="Vendas confirmadas, encomendas em curso e o que precisa de atenção hoje.">
        <Button variant="ghost" onClick={load}>
          <RefreshCw size={13} className="mr-1.5" /> Atualizar
        </Button>
        <a className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12.5px] text-foreground hover:bg-white/[0.1]" href={overview.store.url} target="_blank" rel="noreferrer">
          <ExternalLink size={13} /> Abrir loja
        </a>
      </PanelHeader>

      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Receita confirmada" value={money(overview.revenue.total)} hint={`${overview.revenue.paid_orders} encomenda(s) paga(s)`} />
        <StatCard label="Este mês" value={money(overview.revenue.month)} hint={`Ticket médio ${money(overview.revenue.average_ticket)}`} tone="sky" />
        <StatCard label="Encomendas abertas" value={String(overview.orders.open)} hint={`${overview.orders.pending} à espera de pagamento`} tone="amber" />
        <StatCard label="Por receber" value={money(overview.revenue.pending)} hint="Encomendas ainda não pagas" tone="rose" />
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <MiniBars data={overview.series} label="Receita por dia" />
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">Produtos mais vendidos</p>
          {overview.top_products.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">Ainda sem vendas registadas.</p>
          ) : (
            <ul className="space-y-1.5">
              {overview.top_products.map((item) => (
                <li key={item.id} className="flex items-center gap-2 text-[12px]">
                  <span className="min-w-0 flex-1 truncate text-foreground">{item.name}</span>
                  <span className="text-muted-foreground">{item.units} un.</span>
                  <span className="w-[86px] text-right text-foreground">{money(item.revenue)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-center gap-2">
            <ShoppingBag size={13} className="text-teal-200" />
            <p className="text-[11.5px] font-medium text-muted-foreground">Encomendas recentes</p>
          </div>
          {overview.recent_orders.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">Sem encomendas.</p>
          ) : (
            <ul className="space-y-1.5">
              {overview.recent_orders.map((order) => (
                <li key={order.id} className="flex flex-wrap items-center gap-2 text-[12px]">
                  <span className="font-medium text-foreground">{order.number}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{order.customer || "—"}</span>
                  <StatusPill label={order.status} tone={orderTone(order.status)} />
                  <StatusPill label={order.payment_status} tone={paymentTone(order.payment_status)} />
                  <span className="w-[80px] text-right text-foreground">{money(order.total)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-center gap-2">
            <Boxes size={13} className="text-amber-200" />
            <p className="text-[11.5px] font-medium text-muted-foreground">Stock a precisar de atenção</p>
          </div>
          {overview.products.out_of_stock.length === 0 && overview.products.low_stock.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">Todo o stock está em níveis saudáveis.</p>
          ) : (
            <ul className="space-y-1.5">
              {overview.products.out_of_stock.map((item) => (
                <li key={item.id} className="flex items-center gap-2 text-[12px]">
                  <span className="min-w-0 flex-1 truncate text-foreground">{item.name}</span>
                  <StatusPill label="esgotado" tone="rose" />
                </li>
              ))}
              {overview.products.low_stock.map((item) => (
                <li key={item.id} className="flex items-center gap-2 text-[12px]">
                  <span className="min-w-0 flex-1 truncate text-foreground">{item.name}</span>
                  <span className="text-muted-foreground">{item.stock} un.</span>
                  <StatusPill label="stock baixo" tone="amber" />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">Catálogo</p>
          <p className="text-[12px] text-muted-foreground">
            {overview.products.published} publicado(s) · {overview.products.drafts} rascunho(s) · {overview.products.featured} em destaque
          </p>
          <p className="mt-1 text-[12px] text-muted-foreground">
            {overview.shipping} método(s) de envio ativo(s)
          </p>
        </section>
        <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">Clientes</p>
          <p className="text-[12px] text-foreground">{overview.customers.total} cliente(s)</p>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{overview.customers.new_month} novo(s) este mês</p>
          <ul className="mt-1.5 space-y-1">
            {overview.customers.top.map((customer) => (
              <li key={customer.id} className="flex items-center gap-2 text-[11.5px]">
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{customer.name || customer.email}</span>
                <span className="text-foreground">{money(customer.spent)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">Avaliações e promoções</p>
          <p className="text-[12px] text-foreground">
            <Stars value={overview.reviews.average} /> média de {overview.reviews.total} avaliação(ões)
          </p>
          {overview.reviews.pending > 0 && (
            <p className="mt-1.5">
              <StatusPill label={`${overview.reviews.pending} por moderar`} tone="amber" />
            </p>
          )}
          <p className="mt-1.5 text-[12px] text-muted-foreground">
            {overview.coupons.active} cupão(ões) ativo(s) · {overview.coupons.uses} utilização(ões)
          </p>
        </section>
      </div>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <p className="mb-2 text-[11.5px] font-medium text-muted-foreground">Atividade recente</p>
        {overview.activity.length === 0 ? (
          <p className="text-[12px] text-muted-foreground">Sem registos.</p>
        ) : (
          <ul className="space-y-1.5">
            {overview.activity.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center gap-2 text-[11.5px]">
                <span className="w-[54px] shrink-0 text-muted-foreground">{timeAgo(entry.at)}</span>
                <StatusPill label={entry.action} tone="sky" />
                <span className="min-w-0 flex-1 truncate text-foreground">{entry.label || entry.entity_id}</span>
                <span className="text-muted-foreground">{entry.actor}</span>
                {entry.detail && <span className="text-muted-foreground/80">{entry.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/* ================================================================== produtos */

export function ShopProductsPanel({ ctx }: { ctx: ShopCtx }) {
  const [items, setItems] = useState<ShopProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("all");
  const [stock, setStock] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Partial<ShopProduct> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    shopApi
      .listShop<ShopProduct>("products", { status, stock: stock || undefined, categoryId: categoryId || undefined, q: query || undefined })
      .then((payload) => {
        setItems(payload.items);
        setTotal(payload.total);
      })
      .catch((error: Error) => ctx.notify(error.message, "error"))
      .finally(() => setLoading(false));
  }, [ctx, status, stock, categoryId, query]);

  useEffect(() => {
    const timer = window.setTimeout(load, query ? 260 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  const counts = useMemo(
    () => ({
      rascunho: items.filter((item) => item.status === "rascunho").length,
      agendado: items.filter((item) => item.status === "agendado").length,
      publicado: items.filter((item) => item.status === "publicado").length,
      arquivado: items.filter((item) => item.status === "arquivado").length,
    }),
    [items],
  );

  const save = async (draft: Partial<ShopProduct>, publish = false) => {
    setBusy(true);
    try {
      const payload = {
        ...draft,
        category_ids: draft.category_ids ?? [],
        image_ids: draft.image_ids ?? [],
        image_urls: draft.image_urls ?? [],
        attributes: (draft.attributes ?? []).filter((attribute) => attribute.label || attribute.value),
      };
      const saved = draft.id
        ? (await shopApi.updateShopItem<ShopProduct>("products", draft.id, payload)).item
        : (await shopApi.createShopItem<ShopProduct>("products", payload)).item;
      if (publish && saved.status !== "publicado") await shopApi.publishShopItem<ShopProduct>("products", saved.id);
      ctx.notify(publish ? "Produto guardado e publicado." : "Produto guardado.", "ok");
      setEditing(null);
      load();
      ctx.refreshOverview();
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const act = async (label: string, run: () => Promise<unknown>) => {
    try {
      await run();
      ctx.notify(label, "ok");
      load();
      ctx.refreshOverview();
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    }
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Produtos" hint="Catálogo da loja: preços, IVA, stock, imagens e publicação. Os produtos publicados aparecem em /loja.">
        <a className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12.5px] text-foreground hover:bg-white/[0.1]" href="/loja/produtos" target="_blank" rel="noreferrer">
          <ExternalLink size={13} /> Ver loja
        </a>
        <Button onClick={() => setEditing(emptyProduct())}>
          <Package size={13} className="mr-1.5" /> Novo produto
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.product_statuses} counts={counts} />
        <select className="rounded-lg border border-white/10 bg-white/[0.05] px-2 py-1.5 text-[12px] text-foreground" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
          <option value="">Todas as categorias</option>
          {ctx.catalogue.categories_index.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
        <select className="rounded-lg border border-white/10 bg-white/[0.05] px-2 py-1.5 text-[12px] text-foreground" value={stock} onChange={(event) => setStock(event.target.value)}>
          <option value="">Todo o stock</option>
          <option value="low">Stock baixo</option>
          <option value="out">Sem stock</option>
        </select>
        <input
          className="min-w-[180px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
          placeholder="Pesquisar por nome, SKU ou etiqueta…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <span className="text-[11.5px] text-muted-foreground">{total} produto(s)</span>
      </div>

      {loading && items.length === 0 ? (
        <p className="flex items-center gap-2 py-6 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar produtos…
        </p>
      ) : items.length === 0 ? (
        <EmptyState title="Sem produtos" hint="Crie o primeiro produto para começar a vender." action={<Button onClick={() => setEditing(emptyProduct())}>Novo produto</Button>} />
      ) : (
        <div className="space-y-1.5">
          {items.map((product) => (
            <ListRow
              key={product.id}
              image={product.image_url}
              title={product.name}
              subtitle={`${product.sku || "sem SKU"} · ${product.type}${product.category_ids.length ? ` · ${product.category_ids.length} categoria(s)` : ""}`}
              badges={
                <>
                  <StatusPill label={product.status} tone={productStatusTone(product.status)} />
                  {product.featured && <StatusPill label="destaque" tone="violet" />}
                  {product.track_stock && product.stock <= 0 && <StatusPill label="esgotado" tone="rose" />}
                  {product.track_stock && product.stock > 0 && product.stock <= 5 && <StatusPill label={`${product.stock} un.`} tone="amber" />}
                  {!product.track_stock && <StatusPill label="sem stock" tone="zinc" />}
                </>
              }
              meta={
                <>
                  <span className="font-medium text-foreground">{money(product.price)}</span>
                  <span>IVA {percent(product.tax_rate)}</span>
                  <Stars value={product.rating_avg} count={product.rating_count} />
                </>
              }
              onClick={() => setEditing(product)}
              actions={
                <>
                  {product.status === "publicado" ? (
                    <a
                      className="rounded-md border border-white/8 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.1] hover:text-teal-200"
                      title={`Ver «${product.name}» na loja`}
                      href={`/loja/produto/${product.slug}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={12} />
                    </a>
                  ) : (
                    <span
                      className="rounded-md border border-white/8 bg-white/[0.02] p-1.5 text-muted-foreground/40"
                      title="Só os produtos publicados têm página na loja"
                    >
                      <ExternalLink size={12} />
                    </span>
                  )}
                  {product.status === "publicado" ? (
                    <IconAction title="Retirar da loja" onClick={() => act("Produto retirado da loja.", () => shopApi.unpublishShopItem("products", product.id))}>
                      <EyeOff size={12} />
                    </IconAction>
                  ) : (
                    <IconAction title="Publicar" onClick={() => act("Produto publicado.", () => shopApi.publishShopItem("products", product.id))}>
                      <Eye size={12} />
                    </IconAction>
                  )}
                  <IconAction title="Editar" onClick={() => setEditing(product)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction title="Duplicar" onClick={() => act("Produto duplicado.", () => shopApi.duplicateShopItem("products", product.id))}>
                    <Copy size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={() => {
                      if (window.confirm(`Apagar «${product.name}»?`)) act("Produto apagado.", () => shopApi.deleteShopItem("products", product.id));
                    }}
                  >
                    <Trash2 size={12} />
                  </IconAction>
                </>
              }
            />
          ))}
        </div>
      )}

      {editing && <ProductSheet draft={editing} ctx={ctx} busy={busy} onClose={() => setEditing(null)} onSave={save} />}
    </div>
  );
}

function ProductSheet({
  draft,
  ctx,
  busy,
  onClose,
  onSave,
}: {
  draft: Partial<ShopProduct>;
  ctx: ShopCtx;
  busy: boolean;
  onClose: () => void;
  onSave: (draft: Partial<ShopProduct>, publish?: boolean) => void;
}) {
  const [form, setForm] = useState<Partial<ShopProduct>>({ ...draft, attributes: draft.attributes ?? [], image_ids: draft.image_ids ?? [], image_urls: draft.image_urls ?? [] });
  const [schedule, setSchedule] = useState(String(draft.scheduled_at ?? ""));
  const set = <K extends keyof ShopProduct>(key: K, value: ShopProduct[K]) => setForm((current) => ({ ...current, [key]: value }));
  const margin = Number(form.price ?? 0) - Number(form.cost ?? 0);

  return (
    <Sheet
      title={draft.id ? `Produto · ${draft.name}` : "Novo produto"}
      subtitle={draft.id ? `SKU ${draft.sku || "—"} · ${draft.status}` : "Preencha o essencial: nome, preço e imagens."}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          {draft.id && (
            <Button
              variant="ghost"
              onClick={() => onSave({ ...form, status: "arquivado" })}
            >
              <Archive size={13} className="mr-1.5" /> Arquivar
            </Button>
          )}
          <Button variant="ghost" onClick={() => onSave(form)}>
            Guardar
          </Button>
          <Button onClick={() => onSave(form, true)}>
            <Send size={13} className="mr-1.5" /> Guardar e publicar
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        <TextInput label="Nome" value={String(form.name ?? "")} onChange={(next) => set("name", next)} wide />
        <TextInput label="Referência (SKU)" value={String(form.sku ?? "")} onChange={(next) => set("sku", next)} hint="Em branco: gerado a partir do nome." />
        <SelectInput
          label="Tipo"
          value={String(form.type ?? "fisico")}
          onChange={(next) => set("type", next as ShopProduct["type"])}
          options={ctx.catalogue.product_types.map((item) => ({ value: item.id, label: item.label }))}
          hint={ctx.catalogue.product_types.find((item) => item.id === form.type)?.hint}
        />
        <MoneyInput label="Preço de venda" value={Number(form.price ?? 0)} onChange={(next) => set("price", next)} />
        <MoneyInput label="Preço antes (riscado)" value={Number(form.compare_at_price ?? 0)} onChange={(next) => set("compare_at_price", next)} hint="0 = sem promoção." />
        <MoneyInput label="Custo" value={Number(form.cost ?? 0)} onChange={(next) => set("cost", next)} hint={`Margem por unidade: ${money(margin)}`} />
        <NumberInput label="IVA (%)" value={Number(form.tax_rate ?? 23)} onChange={(next) => set("tax_rate", next)} min={0} max={100} step={1} />
        <SelectInput
          label="Unidade"
          value={String(form.unit ?? "un")}
          onChange={(next) => set("unit", next)}
          options={ctx.catalogue.units.map((unit) => ({ value: unit, label: unit }))}
        />
        <NumberInput label="Stock" value={Number(form.stock ?? 0)} onChange={(next) => set("stock", next)} min={0} />
        <NumberInput label="Stock mínimo" value={Number(form.stock_min ?? 0)} onChange={(next) => set("stock_min", next)} min={0} hint="Abaixo deste valor entra nos avisos." />
        <Toggle checked={Boolean(form.track_stock)} onChange={(next) => set("track_stock", next)} label="Controlar stock" hint="Produtos digitais normalmente não precisam." />
        <Toggle checked={Boolean(form.allow_backorder)} onChange={(next) => set("allow_backorder", next)} label="Aceitar encomendas sem stock" hint="Mostra «sob encomenda» em vez de esgotado." />
        <Toggle checked={Boolean(form.featured)} onChange={(next) => set("featured", next)} label="Destaque na vitrine" hint="Aparece primeiro no catálogo." />
        <NumberInput label="Ordem na loja" value={Number(form.order ?? 0)} onChange={(next) => set("order", next)} min={0} />

        <CheckList
          label="Categorias"
          values={form.category_ids ?? []}
          onChange={(next) => set("category_ids", next)}
          options={ctx.catalogue.categories_index.map((category) => ({ value: category.id, label: category.name }))}
          emptyHint="Ainda não há categorias. Crie-as na secção «Categorias»."
        />
        <TagsInput label="Etiquetas" value={form.tags ?? []} onChange={(next) => set("tags", next)} />

        <TextArea label="Descrição curta" value={String(form.short_description ?? "")} onChange={(next) => set("short_description", next)} rows={2} hint="Uma linha, para o cartão do catálogo." />
        <TextArea label="Descrição (Markdown)" value={String(form.description ?? "")} onChange={(next) => set("description", next)} rows={8} mono />

        <ImagePicker
          ids={form.image_ids ?? []}
          urls={form.image_urls ?? []}
          media={ctx.catalogue.media_index}
          onChange={({ ids, urls }) => setForm((current) => ({ ...current, image_ids: ids, image_urls: urls }))}
        />
        <AttributesEditor value={form.attributes ?? []} onChange={(next) => set("attributes", next)} />

        <NumberInput label="Peso (kg)" value={Number(form.weight_kg ?? 0)} onChange={(next) => set("weight_kg", next)} min={0} step={0.01} />
        <div className="grid grid-cols-3 gap-2">
          <NumberInput label="Comp. (cm)" value={Number(form.length_cm ?? 0)} onChange={(next) => set("length_cm", next)} min={0} />
          <NumberInput label="Larg. (cm)" value={Number(form.width_cm ?? 0)} onChange={(next) => set("width_cm", next)} min={0} />
          <NumberInput label="Alt. (cm)" value={Number(form.height_cm ?? 0)} onChange={(next) => set("height_cm", next)} min={0} />
        </div>

        <TextArea label="Notas internas" value={String(form.internal_notes ?? "")} onChange={(next) => set("internal_notes", next)} rows={3} hint="Não aparece na loja." />
        <TextInput label="SEO — título" value={String(form.seo?.title ?? "")} onChange={(next) => set("seo", { ...(form.seo ?? {}), title: next })} />
        <TextInput label="SEO — descrição" value={String(form.seo?.description ?? "")} onChange={(next) => set("seo", { ...(form.seo ?? {}), description: next })} />
        <TextInput label="SEO — palavras-chave" value={(form.seo?.keywords ?? []).join(", ")} onChange={(next) => set("seo", { ...(form.seo ?? {}), keywords: next.split(",").map((part) => part.trim()).filter(Boolean) })} />

        <div className="sm:col-span-2">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2.5">
            <CalendarClock size={13} className="text-amber-200" />
            <span className={labelClass}>Agendar publicação</span>
            <input
              type="datetime-local"
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[12px] text-foreground"
              value={schedule}
              onChange={(event) => setSchedule(event.target.value)}
            />
            <Button
              variant="ghost"
              disabled={!schedule}
              onClick={() => {
                if (schedule) onSave({ ...form, status: "agendado", scheduled_at: schedule });
              }}
            >
              Agendar
            </Button>
            <span className="text-[11px] text-muted-foreground">O produto publica-se sozinho quando a data chegar.</span>
          </div>
        </div>
      </div>
    </Sheet>
  );
}

/* ================================================================ encomendas */

export function ShopOrdersPanel({ ctx }: { ctx: ShopCtx }) {
  const [items, setItems] = useState<ShopOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("all");
  const [paymentStatus, setPaymentStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<ShopOrder | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    shopApi
      .listShop<ShopOrder>("orders", { status, paymentStatus, q: query || undefined })
      .then((payload) => {
        setItems(payload.items);
        setTotal(payload.total);
      })
      .catch((error: Error) => ctx.notify(error.message, "error"))
      .finally(() => setLoading(false));
  }, [ctx, status, paymentStatus, query]);

  useEffect(() => {
    const timer = window.setTimeout(load, query ? 260 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    items.forEach((order) => {
      tally[order.status] = (tally[order.status] ?? 0) + 1;
    });
    return tally;
  }, [items]);

  const openOrder = async (id: string) => {
    try {
      const payload = await shopApi.getShopItem<ShopOrder>("orders", id);
      setOpen(payload.item);
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    }
  };

  const flow = ctx.catalogue.order_statuses.reduce<Record<string, OrderStatus[]>>((accumulator, item) => {
    accumulator[item.id] = item.next;
    return accumulator;
  }, {});

  return (
    <div className="space-y-3">
      <PanelHeader title="Encomendas" hint="Cada encomenda guarda preços, stock, pagamento e seguimento. O pagamento é registado à mão (MB Way, transferência, numerário…).">
        <Button variant="ghost" onClick={load}>
          <RefreshCw size={13} className="mr-1.5" /> Atualizar
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.order_statuses} counts={counts} />
        <select className="rounded-lg border border-white/10 bg-white/[0.05] px-2 py-1.5 text-[12px] text-foreground" value={paymentStatus} onChange={(event) => setPaymentStatus(event.target.value)}>
          <option value="all">Qualquer pagamento</option>
          {ctx.catalogue.payment_statuses.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.label}
            </option>
          ))}
        </select>
        <input
          className="min-w-[180px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
          placeholder="Pesquisar por número, cliente, email ou método de pagamento…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <span className="text-[11.5px] text-muted-foreground">{total} encomenda(s)</span>
      </div>

      {loading && items.length === 0 ? (
        <p className="flex items-center gap-2 py-6 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar encomendas…
        </p>
      ) : items.length === 0 ? (
        <EmptyState title="Sem encomendas" hint="Assim que alguém comprar na loja, a encomenda aparece aqui." />
      ) : (
        <div className="space-y-1.5">
          {items.map((order) => (
            <ListRow
              key={order.id}
              image=""
              title={`${order.number} · ${order.customer?.name || order.customer?.email || "sem cliente"}`}
              subtitle={`${order.items_count ?? order.items?.length ?? 0} artigo(s) · pago por ${order.payment?.method ?? "—"} · ${timeAgo(order.placed_at ?? order.created_at)}`}
              badges={
                <>
                  <StatusPill label={order.status} tone={orderTone(order.status)} />
                  <StatusPill label={order.payment?.status ?? "pendente"} tone={paymentTone(order.payment?.status)} />
                  {order.coupon_code && <StatusPill label={order.coupon_code} tone="violet" />}
                  {order.source === "loja" && <StatusPill label="online" tone="sky" />}
                </>
              }
              meta={<span className="font-medium text-foreground">{money(order.totals?.total ?? order.total ?? 0)}</span>}
              onClick={() => openOrder(order.id)}
              actions={
                <>
                  <IconAction title="Ver ficha" onClick={() => openOrder(order.id)}>
                    <FileText size={12} />
                  </IconAction>
                  <a
                    className="rounded-md border border-white/8 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.1] hover:text-foreground"
                    title="Imprimir"
                    href={shopApi.shopOrderPrintUrl(order.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Printer size={12} />
                  </a>
                </>
              }
            />
          ))}
        </div>
      )}

      {open && (
        <OrderSheet
          order={open}
          ctx={ctx}
          flow={flow}
          onClose={() => setOpen(null)}
          onRefresh={async () => {
            await openOrder(open.id);
            load();
            ctx.refreshOverview();
          }}
        />
      )}
    </div>
  );
}

function OrderSheet({
  order,
  ctx,
  flow,
  onClose,
  onRefresh,
}: {
  order: ShopOrder;
  ctx: ShopCtx;
  flow: Record<string, OrderStatus[]>;
  onClose: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [statusNote, setStatusNote] = useState("");
  const [payment, setPayment] = useState({ method: order.payment?.method ?? "transferencia", amount: Number(order.totals?.total ?? order.total ?? 0), reference: "", note: "" });

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      ctx.notify(label, "ok");
      await onRefresh();
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const totals = order.totals ?? {
    subtotal: order.subtotal ?? 0,
    discount_total: order.discount_total ?? 0,
    shipping_total: order.shipping_total ?? 0,
    tax_total: order.tax_total ?? 0,
    total: order.total ?? 0,
  };
  const next = flow[order.status] ?? [];

  return (
    <Sheet
      title={`Encomenda ${order.number}`}
      subtitle={`${order.customer?.name || ""} ${order.customer?.email ? `· ${order.customer.email}` : ""}`}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          <a className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12.5px] text-foreground hover:bg-white/[0.1]" href={shopApi.shopOrderPrintUrl(order.id)} target="_blank" rel="noreferrer">
            <Printer size={13} /> Imprimir
          </a>
          <Button
            variant="ghost"
            onClick={() => {
              if (window.confirm("Apagar esta encomenda? O stock reservado não é reposto.")) run("Encomenda apagada.", () => shopApi.deleteShopItem("orders", order.id)).then(onClose);
            }}
          >
            <Trash2 size={13} className="mr-1.5" /> Apagar
          </Button>
        </>
      }
    >
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={labelClass}>Artigos</p>
            <div className="mt-1.5 space-y-1.5">
              {(order.items ?? []).map((line) => (
                <div key={line.id} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                  <span className="min-w-0 flex-1 truncate text-foreground">{line.name}</span>
                  <span className="text-muted-foreground">
                    {line.quantity} × {money(line.unit_price)}
                  </span>
                  <span className="w-[86px] text-right font-medium text-foreground">{money(line.quantity * line.unit_price - (line.discount ?? 0))}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 space-y-1 border-t border-white/8 pt-2 text-[12.5px]">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Subtotal</span>
                <span>{money(totals.subtotal)}</span>
              </div>
              {Number(totals.discount_total) > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Desconto {order.coupon_code}</span>
                  <span>−{money(totals.discount_total)}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted-foreground">Portes · {order.shipping_method?.name ?? "—"}</span>
                <span>{Number(totals.shipping_total) ? money(totals.shipping_total) : "grátis"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">IVA incluído</span>
                <span>{money(totals.tax_total)}</span>
              </div>
              <div className="flex justify-between border-t border-white/8 pt-1.5 text-[14px] font-semibold">
                <span>Total</span>
                <span>{money(totals.total)}</span>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={labelClass}>Cliente e entrega</p>
            <p className="mt-1 text-[12.5px] text-foreground">{order.customer?.name || "—"}</p>
            <p className="text-[11.5px] text-muted-foreground">
              {order.customer?.email} {order.customer?.phone ? `· ${order.customer.phone}` : ""} {order.customer?.tax_id ? `· NIF ${order.customer.tax_id}` : ""}
            </p>
            {order.customer?.company && <p className="text-[11.5px] text-muted-foreground">{order.customer.company}</p>}
            <p className="mt-1.5 text-[11.5px] text-muted-foreground">
              {[order.shipping_address?.line1, order.shipping_address?.line2, order.shipping_address?.postal_code, order.shipping_address?.city, order.shipping_address?.country]
                .filter(Boolean)
                .join(", ") || "Sem morada de entrega"}
            </p>
            {!order.customer_id && <p className="mt-1.5"><StatusPill label="sem ficha de cliente" tone="amber" /></p>}
          </section>

          {order.notes && (
            <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className={labelClass}>Notas do cliente</p>
              <p className="mt-1 whitespace-pre-wrap text-[12.5px] text-foreground">{order.notes}</p>
            </section>
          )}

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={labelClass}>Notas internas</p>
            {order.internal_notes ? <p className="mt-1 whitespace-pre-wrap text-[12px] text-muted-foreground">{order.internal_notes}</p> : <p className="mt-1 text-[11.5px] text-muted-foreground">Sem notas.</p>}
            <div className="mt-2 flex flex-col gap-2">
              <textarea className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" rows={2} placeholder="Acrescentar nota interna…" value={note} onChange={(event) => setNote(event.target.value)} />
              <Button
                variant="ghost"
                disabled={!note.trim()}
                onClick={() => run("Nota guardada.", async () => {
                  await shopApi.addShopOrderNote(order.id, note.trim());
                  setNote("");
                })}
              >
                <Send size={13} className="mr-1.5" /> Guardar nota
              </Button>
            </div>
          </section>
        </div>

        <div className="space-y-3">
          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center gap-2">
              <Truck size={13} className="text-teal-200" />
              <p className={labelClass}>Estado e seguimento</p>
            </div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              <StatusPill label={order.status} tone={orderTone(order.status)} />
              <StatusPill label={`pagamento: ${order.payment?.status ?? "pendente"}`} tone={paymentTone(order.payment?.status)} />
              {order.stock_reserved && <StatusPill label="stock reservado" tone="sky" />}
            </div>
            {next.length === 0 ? (
              <p className="text-[11.5px] text-muted-foreground">Esta encomenda já está encerrada ({order.status}).</p>
            ) : (
              <div className="space-y-2">
                <input className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40" placeholder="Nota do passo (opcional)" value={statusNote} onChange={(event) => setStatusNote(event.target.value)} />
                <div className="flex flex-wrap gap-1.5">
                  {next.map((target) => (
                    <Chip
                      key={target}
                      onClick={() =>
                        run(`Estado: ${target}.`, async () => {
                          await shopApi.setShopOrderStatus(order.id, target, statusNote);
                          setStatusNote("");
                        })
                      }
                    >
                      {target === "cancelado" ? <Ban size={11} className="mr-1 inline" /> : null}
                      {ctx.catalogue.order_statuses.find((item) => item.id === target)?.label ?? target}
                    </Chip>
                  ))}
                </div>
                <p className="text-[10.5px] text-muted-foreground">Anular ou reembolsar repõe automaticamente o stock reservado.</p>
              </div>
            )}
            {(order.timeline ?? []).length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-white/8 pt-2">
                {[...(order.timeline ?? [])].reverse().map((step, index) => (
                  <li key={`${step.at}-${index}`} className="text-[11.5px] text-muted-foreground">
                    <span className="text-foreground">{step.status}</span> · {timeAgo(step.at)}
                    {step.note ? ` — ${step.note}` : ""} <span className="opacity-70">({step.actor || "plataforma"})</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center gap-2">
              <Wallet size={13} className="text-emerald-200" />
              <p className={labelClass}>Pagamento</p>
            </div>
            <p className="text-[11.5px] text-muted-foreground">
              Recebido {money(order.payment?.amount ?? 0)} de {money(totals.total)}
              {order.payment?.paid_at ? ` · ${new Date(order.payment.paid_at).toLocaleString("pt-PT")}` : ""}
            </p>
            <div className="mt-2 grid gap-2">
              <select className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground" value={payment.method} onChange={(event) => setPayment({ ...payment, method: event.target.value })}>
                {ctx.catalogue.payment_methods.map((method) => (
                  <option key={method.id} value={method.id}>
                    {method.label}
                  </option>
                ))}
              </select>
              <input
                type="number"
                step="0.01"
                className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground"
                value={payment.amount}
                onChange={(event) => setPayment({ ...payment, amount: Number(event.target.value) })}
              />
              <input
                className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground"
                placeholder="Referência (ex.: MB-123)"
                value={payment.reference}
                onChange={(event) => setPayment({ ...payment, reference: event.target.value })}
              />
              <Button onClick={() => run("Pagamento registado.", () => shopApi.registerShopPayment(order.id, payment))}>
                <Wallet size={13} className="mr-1.5" /> Registar pagamento
              </Button>
              {order.payment?.status === "pago" && (
                <Button
                  variant="ghost"
                  onClick={() =>
                    run("Pagamento devolvido.", async () => {
                      await shopApi.registerShopPayment(order.id, { method: payment.method, amount: 0, status: "reembolsado", note: "Devolução registada" });
                    })
                  }
                >
                  <ArchiveRestore size={13} className="mr-1.5" /> Registar devolução
                </Button>
              )}
            </div>
            {(order.payment?.history ?? []).length > 0 && (
              <ul className="mt-2 space-y-1 border-t border-white/8 pt-2">
                {(order.payment?.history ?? []).map((entry, index) => (
                  <li key={`${entry.at}-${index}`} className="text-[11px] text-muted-foreground">
                    {entry.status} · {money(entry.amount)} · {timeAgo(entry.at)} {entry.actor ? `(${entry.actor})` : ""}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={labelClass}>Origem</p>
            <p className="mt-1 text-[11.5px] text-muted-foreground">
              {order.source === "loja" ? "Loja online (/loja)" : "Criada na plataforma"} · {order.created_at ? new Date(order.created_at).toLocaleString("pt-PT") : ""}
            </p>
          </section>
        </div>
      </div>
    </Sheet>
  );
}
