/**
 * Biblioteca da loja: categorias, clientes, promoções, envios, avaliações e
 * definições.
 *
 * São as secções que dão contexto ao catálogo: onde os produtos se arrumam,
 * quem compra, que descontos se aplicam, quanto custam os portes, o que dizem
 * os clientes e como a loja se apresenta (pagamentos, contactos e tema).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Star,
  Trash2,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import * as shopApi from "../shopApi";
import type { ShopCategory, ShopCoupon, ShopCustomer, ShopOrder, ShopReview, ShopSettings, ShopShipping, ShopStatus } from "../shopApi";
import {
  CheckList,
  EmptyState,
  IconAction,
  ImagePicker,
  ListRow,
  MoneyInput,
  Notice,
  NumberInput,
  PanelHeader,
  SelectInput,
  Sheet,
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
import type { ShopCtx } from "./ShopPanels";

const STATUS_TONES: Record<string, string> = { rascunho: "slate", agendado: "amber", publicado: "emerald", arquivado: "zinc" };

function useList<T>(entity: Parameters<typeof shopApi.listShop>[0], options: Record<string, string | undefined>, ctx: ShopCtx) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(options);

  const load = useCallback(() => {
    setLoading(true);
    const parsed = JSON.parse(key) as Parameters<typeof shopApi.listShop<T>>[1];
    shopApi
      .listShop<T>(entity, parsed)
      .then((payload) => setItems(payload.items))
      .catch((error: Error) => ctx.notify(error.message, "error"))
      .finally(() => setLoading(false));
  }, [ctx, entity, key]);

  useEffect(() => {
    const timer = window.setTimeout(load, options.q ? 260 : 0);
    return () => window.clearTimeout(timer);
  }, [load, options.q, options.status]);

  return { items, loading, load };
}

function Loading({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 py-6 text-[12.5px] text-muted-foreground">
      <Loader2 size={14} className="animate-spin" /> {label}
    </p>
  );
}

/** Guardar é sempre igual: chamar a API, avisar, recarregar e fechar. */
function useSaver(ctx: ShopCtx, close: () => void, reload: () => void) {
  const [busy, setBusy] = useState(false);
  const save = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await action();
      ctx.notify(message, "ok");
      close();
      reload();
      ctx.refreshOverview();
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return { busy, save };
}

/* ================================================================ categorias */

export function ShopCategoriesPanel({ ctx }: { ctx: ShopCtx }) {
  const { items, loading, load } = useList<ShopCategory>("categories", {}, ctx);
  const [editing, setEditing] = useState<Partial<ShopCategory> | null>(null);

  return (
    <div className="space-y-3">
      <PanelHeader title="Categorias" hint="Arrumam o catálogo e aparecem no menu da loja. Só as publicadas são visíveis para quem compra.">
        <Button variant="ghost" onClick={() => ctx.refreshOverview()}>
          <RefreshCw size={13} />
        </Button>
        <Button onClick={() => setEditing({ name: "", status: "publicado", order: (items.length + 1) * 10 })}>
          <Plus size={13} className="mr-1.5" /> Nova categoria
        </Button>
      </PanelHeader>

      {loading && items.length === 0 ? (
        <Loading label="A carregar categorias…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sem categorias" hint="Crie categorias para arrumar os produtos na loja." />
      ) : (
        <div className="space-y-1.5">
          {items.map((category) => {
            const parent = items.find((item) => item.id === category.parent_id);
            return (
              <ListRow
                key={category.id}
                image={category.image_url}
                title={`${category.name}${parent ? ` (dentro de ${parent.name})` : ""}`}
                subtitle={`/${category.slug} · ${category.description || "sem descrição"}`}
                badges={
                  <>
                    <StatusPill label={category.status} tone={STATUS_TONES[category.status] ?? "slate"} />
                    {category.featured && <StatusPill label="destaque" tone="violet" />}
                    <StatusPill label={`${category.products ?? 0} produto(s)`} tone="sky" />
                  </>
                }
                onClick={() => setEditing(category)}
                actions={
                  <>
                    <IconAction title="Editar" onClick={() => setEditing(category)}>
                      <Pencil size={12} />
                    </IconAction>
                    <IconAction
                      title="Apagar"
                      danger
                      onClick={() => {
                        if (window.confirm(`Apagar a categoria «${category.name}»? Os produtos ficam sem categoria.`)) {
                          shopApi
                            .deleteShopItem("categories", category.id)
                            .then(() => {
                              ctx.notify("Categoria apagada.", "ok");
                              load();
                            })
                            .catch((error: Error) => ctx.notify(error.message, "error"));
                        }
                      }}
                    >
                      <Trash2 size={12} />
                    </IconAction>
                  </>
                }
              />
            );
          })}
        </div>
      )}

      {editing && <CategorySheet draft={editing} categories={items} ctx={ctx} reload={load} onClose={() => setEditing(null)} />}
    </div>
  );
}

function CategorySheet({
  draft,
  categories,
  ctx,
  reload,
  onClose,
}: {
  draft: Partial<ShopCategory>;
  categories: ShopCategory[];
  ctx: ShopCtx;
  reload: () => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Partial<ShopCategory>>({ ...draft });
  const [imageId, setImageId] = useState(String(draft.image_id ?? ""));
  const [imageUrl, setImageUrl] = useState(String(draft.image_url ?? ""));
  const { busy, save } = useSaver(ctx, onClose, reload);

  return (
    <Sheet
      title={draft.id ? `Categoria · ${draft.name}` : "Nova categoria"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={() => save(() => (draft.id ? shopApi.updateShopItem("categories", draft.id, { ...form, image_id: imageId || null, image_url: imageUrl }) : shopApi.createShopItem("categories", { ...form, image_id: imageId || null, image_url: imageUrl })), "Categoria guardada.")}>
            <Save size={13} className="mr-1.5" /> Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        <TextInput label="Nome" value={String(form.name ?? "")} onChange={(next) => setForm({ ...form, name: next })} wide />
        <TextInput label="Slug (URL)" value={String(form.slug ?? "")} onChange={(next) => setForm({ ...form, slug: next })} hint="Em branco: gerado a partir do nome." />
        <SelectInput
          label="Categoria ascendente"
          value={String(form.parent_id ?? "")}
          onChange={(next) => setForm({ ...form, parent_id: next || null })}
          options={categories.filter((category) => category.id !== draft.id).map((category) => ({ value: category.id, label: category.name }))}
          placeholder="— nenhuma (raiz) —"
        />
        <SelectInput
          label="Estado"
          value={String(form.status ?? "publicado")}
          onChange={(next) => setForm({ ...form, status: next as ShopStatus })}
          options={[
            { value: "publicado", label: "Publicado" },
            { value: "rascunho", label: "Rascunho" },
            { value: "arquivado", label: "Arquivado" },
          ]}
        />
        <NumberInput label="Ordem" value={Number(form.order ?? 0)} onChange={(next) => setForm({ ...form, order: next })} min={0} />
        <Toggle checked={Boolean(form.featured)} onChange={(next) => setForm({ ...form, featured: next })} label="Categoria em destaque" />
        <TextArea label="Descrição" value={String(form.description ?? "")} onChange={(next) => setForm({ ...form, description: next })} rows={3} />
        <ImagePicker
          ids={imageId ? [imageId] : []}
          urls={imageUrl ? [imageUrl] : []}
          media={ctx.catalogue.media_index}
          label="Imagem da categoria"
          onChange={({ ids, urls }) => {
            setImageId(ids[0] ?? "");
            setImageUrl(urls[0] ?? "");
          }}
        />
        <TextInput label="SEO — título" value={String(form.seo?.title ?? "")} onChange={(next) => setForm({ ...form, seo: { ...(form.seo ?? {}), title: next } })} />
        <TextInput label="SEO — descrição" value={String(form.seo?.description ?? "")} onChange={(next) => setForm({ ...form, seo: { ...(form.seo ?? {}), description: next } })} />
      </div>
    </Sheet>
  );
}

/* ================================================================== clientes */

export function ShopCustomersPanel({ ctx }: { ctx: ShopCtx }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const { items, loading, load } = useList<ShopCustomer>("customers", { q: query || undefined, status }, ctx);
  const [editing, setEditing] = useState<Partial<ShopCustomer> | null>(null);

  const counts = useMemo(
    () => ({ ativo: items.filter((item) => item.status === "ativo").length, bloqueado: items.filter((item) => item.status === "bloqueado").length }),
    [items],
  );

  return (
    <div className="space-y-3">
      <PanelHeader title="Clientes" hint="Ficha de cada comprador, com encomendas, valores gastos e ligação ao CRM. Os clientes nascem sozinhos no checkout da loja.">
        <Button onClick={() => setEditing({ name: "", email: "", status: "ativo", tags: [], billing: {}, shipping_address: {} })}>
          <Plus size={13} className="mr-1.5" /> Novo cliente
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.customer_statuses} counts={counts} />
        <input
          className="min-w-[200px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-300/40"
          placeholder="Pesquisar por nome, email, telefone ou empresa…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <span className="text-[11.5px] text-muted-foreground">{items.length} cliente(s)</span>
      </div>

      {loading && items.length === 0 ? (
        <Loading label="A carregar clientes…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sem clientes" hint="Assim que alguém comprar na loja, o cliente aparece aqui." />
      ) : (
        <div className="space-y-1.5">
          {items.map((customer) => (
            <ListRow
              key={customer.id}
              image=""
              title={customer.name || customer.email}
              subtitle={`${customer.email}${customer.company ? ` · ${customer.company}` : ""}${customer.phone ? ` · ${customer.phone}` : ""}`}
              badges={
                <>
                  <StatusPill label={customer.status} tone={customer.status === "ativo" ? "emerald" : "rose"} />
                  {customer.crm_account_id && <StatusPill label="no CRM" tone="violet" />}
                  {customer.marketing && <StatusPill label="newsletter" tone="sky" />}
                </>
              }
              meta={
                <>
                  <span>{customer.orders_count ?? 0} encomenda(s)</span>
                  <span className="font-medium text-foreground">{money(customer.total_spent ?? 0)}</span>
                </>
              }
              onClick={() => setEditing(customer)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => setEditing(customer)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={() => {
                      if (window.confirm(`Apagar o cliente «${customer.name || customer.email}»?`)) {
                        shopApi
                          .deleteShopItem("customers", customer.id)
                          .then(() => {
                            ctx.notify("Cliente apagado.", "ok");
                            load();
                          })
                          .catch((error: Error) => ctx.notify(error.message, "error"));
                      }
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

      {editing && <CustomerSheet draft={editing} ctx={ctx} reload={load} onClose={() => setEditing(null)} />}
    </div>
  );
}

function CustomerSheet({ draft, ctx, reload, onClose }: { draft: Partial<ShopCustomer>; ctx: ShopCtx; reload: () => void; onClose: () => void }) {
  const [form, setForm] = useState<Partial<ShopCustomer>>({ ...draft, tags: draft.tags ?? [], billing: draft.billing ?? {}, shipping_address: draft.shipping_address ?? {} });
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const { busy, save } = useSaver(ctx, onClose, reload);

  useEffect(() => {
    if (!draft.id) return;
    shopApi
      .listShop<ShopOrder>("orders", { customerId: draft.id })
      .then((payload) => setOrders(payload.items))
      .catch(() => undefined);
  }, [draft.id]);

  const address = (key: "billing" | "shipping_address", label: string) => (
    <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3 sm:col-span-2">
      <p className={labelClass}>{label}</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <TextInput label="Rua" value={String(form[key]?.line1 ?? "")} onChange={(next) => setForm({ ...form, [key]: { ...(form[key] ?? {}), line1: next } })} wide />
        <TextInput label="Complemento" value={String(form[key]?.line2 ?? "")} onChange={(next) => setForm({ ...form, [key]: { ...(form[key] ?? {}), line2: next } })} wide />
        <TextInput label="Código postal" value={String(form[key]?.postal_code ?? "")} onChange={(next) => setForm({ ...form, [key]: { ...(form[key] ?? {}), postal_code: next } })} />
        <TextInput label="Localidade" value={String(form[key]?.city ?? "")} onChange={(next) => setForm({ ...form, [key]: { ...(form[key] ?? {}), city: next } })} />
        <TextInput label="País" value={String(form[key]?.country ?? "Portugal")} onChange={(next) => setForm({ ...form, [key]: { ...(form[key] ?? {}), country: next } })} />
      </div>
    </section>
  );

  return (
    <Sheet
      title={draft.id ? `Cliente · ${draft.name || draft.email}` : "Novo cliente"}
      subtitle={draft.total_spent !== undefined ? `${draft.orders_count ?? 0} encomenda(s) · ${money(draft.total_spent ?? 0)}` : undefined}
      onClose={onClose}
      busy={busy}
      wide
      footer={
        <>
          {draft.id && (
            <Button
              variant="ghost"
              onClick={() =>
                save(() => shopApi.linkShopCustomerToCrm(draft.id as string), "Cliente ligado ao CRM (ou já estava).")
              }
            >
              <Building2 size={13} className="mr-1.5" /> Ligar ao CRM
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={() => save(() => (draft.id ? shopApi.updateShopItem("customers", draft.id, form) : shopApi.createShopItem("customers", form)), "Cliente guardado.")}>
            <Save size={13} className="mr-1.5" /> Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        <TextInput label="Nome" value={String(form.name ?? "")} onChange={(next) => setForm({ ...form, name: next })} />
        <TextInput label="Email" type="email" value={String(form.email ?? "")} onChange={(next) => setForm({ ...form, email: next })} />
        <TextInput label="Telefone" value={String(form.phone ?? "")} onChange={(next) => setForm({ ...form, phone: next })} />
        <TextInput label="NIF" value={String(form.tax_id ?? "")} onChange={(next) => setForm({ ...form, tax_id: next })} />
        <TextInput label="Empresa" value={String(form.company ?? "")} onChange={(next) => setForm({ ...form, company: next })} />
        <SelectInput
          label="Estado"
          value={String(form.status ?? "ativo")}
          onChange={(next) => setForm({ ...form, status: next as ShopCustomer["status"] })}
          options={ctx.catalogue.customer_statuses.map((item) => ({ value: item.id, label: item.label }))}
          hint="Um cliente bloqueado não deve receber encomendas novas."
        />
        <TagsInput label="Etiquetas" value={form.tags ?? []} onChange={(next) => setForm({ ...form, tags: next })} />
        <Toggle checked={Boolean(form.marketing)} onChange={(next) => setForm({ ...form, marketing: next })} label="Aceita receber novidades" />
        <TextArea label="Notas" value={String(form.notes ?? "")} onChange={(next) => setForm({ ...form, notes: next })} rows={3} />
        {address("billing", "Faturação")}
        {address("shipping_address", "Entrega")}

        {draft.id && (
          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3 sm:col-span-2">
            <p className={labelClass}>Encomendas deste cliente</p>
            {orders.length === 0 ? (
              <p className="mt-1 text-[12px] text-muted-foreground">Ainda sem encomendas.</p>
            ) : (
              <ul className="mt-1.5 space-y-1">
                {orders.map((order) => (
                  <li key={order.id} className="flex flex-wrap items-center gap-2 text-[12px]">
                    <span className="font-medium text-foreground">{order.number}</span>
                    <span className="text-muted-foreground">{timeAgo(order.placed_at ?? order.created_at)}</span>
                    <StatusPill label={order.status} tone="sky" />
                    <span className="w-[84px] text-right text-foreground">{money(order.totals?.total ?? order.total ?? 0)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </Sheet>
  );
}

/* ================================================================= promoções */

export function ShopCouponsPanel({ ctx }: { ctx: ShopCtx }) {
  const { items, loading, load } = useList<ShopCoupon>("coupons", {}, ctx);
  const [editing, setEditing] = useState<Partial<ShopCoupon> | null>(null);

  return (
    <div className="space-y-3">
      <PanelHeader title="Promoções" hint="Cupões de desconto ou de portes grátis. Valem no carrinho da loja e são validados outra vez no servidor.">
        <Button onClick={() => setEditing({ code: "", type: "percentagem", value: 10, active: true, min_subtotal: 0, max_uses: 0, product_ids: [], category_ids: [] })}>
          <Plus size={13} className="mr-1.5" /> Novo cupão
        </Button>
      </PanelHeader>

      {loading && items.length === 0 ? (
        <Loading label="A carregar promoções…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sem cupões" hint="Crie um cupão para dar desconto ou portes grátis." />
      ) : (
        <div className="space-y-1.5">
          {items.map((coupon) => (
            <ListRow
              key={coupon.id}
              image=""
              title={coupon.code}
              subtitle={coupon.description || "sem descrição"}
              badges={
                <>
                  <StatusPill label={coupon.active ? "ativo" : "inativo"} tone={coupon.active ? "emerald" : "zinc"} />
                  <StatusPill
                    label={coupon.type === "percentagem" ? `${percent(coupon.value)} de desconto` : coupon.type === "valor" ? `${money(coupon.value)} de desconto` : "portes grátis"}
                    tone="violet"
                  />
                  {coupon.min_subtotal > 0 && <StatusPill label={`mín. ${money(coupon.min_subtotal)}`} tone="sky" />}
                </>
              }
              meta={
                <>
                  <span>{coupon.uses} utilização(ões){coupon.max_uses ? ` de ${coupon.max_uses}` : ""}</span>
                  <span className="text-muted-foreground">
                    {[coupon.product_ids.length ? `${coupon.product_ids.length} produto(s)` : "", coupon.category_ids.length ? `${coupon.category_ids.length} categoria(s)` : ""].filter(Boolean).join(" · ") || "todos os produtos"}
                  </span>
                </>
              }
              onClick={() => setEditing(coupon)}
              actions={
                <>
                  <IconAction title={coupon.active ? "Desativar" : "Ativar"} onClick={() => shopApi.updateShopItem<ShopCoupon>("coupons", coupon.id, { active: !coupon.active }).then(load).catch((error: Error) => ctx.notify(error.message, "error"))}>
                    {coupon.active ? <EyeOff size={12} /> : <Eye size={12} />}
                  </IconAction>
                  <IconAction title="Editar" onClick={() => setEditing(coupon)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction title="Duplicar" onClick={() => shopApi.duplicateShopItem("coupons", coupon.id).then(() => { ctx.notify("Cupão duplicado.", "ok"); load(); }).catch((error: Error) => ctx.notify(error.message, "error"))}>
                    <Copy size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={() => {
                      if (window.confirm(`Apagar o cupão ${coupon.code}?`))
                        shopApi.deleteShopItem("coupons", coupon.id).then(load).catch((error: Error) => ctx.notify(error.message, "error"));
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

      {editing && <CouponSheet draft={editing} ctx={ctx} reload={load} onClose={() => setEditing(null)} />}
    </div>
  );
}

function CouponSheet({ draft, ctx, reload, onClose }: { draft: Partial<ShopCoupon>; ctx: ShopCtx; reload: () => void; onClose: () => void }) {
  const [form, setForm] = useState<Partial<ShopCoupon>>({ ...draft, product_ids: draft.product_ids ?? [], category_ids: draft.category_ids ?? [] });
  const { busy, save } = useSaver(ctx, onClose, reload);

  return (
    <Sheet
      title={draft.id ? `Cupão · ${draft.code}` : "Novo cupão"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={() => save(() => (draft.id ? shopApi.updateShopItem("coupons", draft.id, form) : shopApi.createShopItem("coupons", form)), "Cupão guardado.")}>
            <Save size={13} className="mr-1.5" /> Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        <TextInput label="Código" value={String(form.code ?? "")} onChange={(next) => setForm({ ...form, code: next.toUpperCase() })} hint="É isto que o cliente escreve no carrinho." />
        <SelectInput
          label="Tipo de desconto"
          value={String(form.type ?? "percentagem")}
          onChange={(next) => setForm({ ...form, type: next as ShopCoupon["type"] })}
          options={ctx.catalogue.coupon_types.map((item) => ({ value: item.id, label: item.label }))}
          hint={ctx.catalogue.coupon_types.find((item) => item.id === form.type)?.hint}
        />
        {form.type !== "portes_gratis" && <MoneyInput label={form.type === "percentagem" ? "Percentagem" : "Valor"} value={Number(form.value ?? 0)} onChange={(next) => setForm({ ...form, value: next })} hint={form.type === "percentagem" ? "Entre 0 e 100." : "Descontado ao subtotal."} />}
        <MoneyInput label="Subtotal mínimo" value={Number(form.min_subtotal ?? 0)} onChange={(next) => setForm({ ...form, min_subtotal: next })} hint="0 = sem mínimo." />
        <NumberInput label="Máximo de utilizações" value={Number(form.max_uses ?? 0)} onChange={(next) => setForm({ ...form, max_uses: next })} min={0} hint="0 = sem limite." />
        <SelectInput
          label="Ativo"
          value={form.active === false ? "nao" : "sim"}
          onChange={(next) => setForm({ ...form, active: next === "sim" })}
          options={[
            { value: "sim", label: "Sim" },
            { value: "nao", label: "Não" },
          ]}
        />
        <TextInput label="Começa em" type="datetime-local" value={String(form.starts_at ?? "").slice(0, 16)} onChange={(next) => setForm({ ...form, starts_at: next || null })} />
        <TextInput label="Termina em" type="datetime-local" value={String(form.ends_at ?? "").slice(0, 16)} onChange={(next) => setForm({ ...form, ends_at: next || null })} />
        <TextArea label="Descrição" value={String(form.description ?? "")} onChange={(next) => setForm({ ...form, description: next })} rows={2} hint="Aparece ao cliente quando o cupão é aceite." />
        <CheckList
          label="Só estes produtos"
          values={form.product_ids ?? []}
          onChange={(next) => setForm({ ...form, product_ids: next })}
          options={ctx.catalogue.products_index.map((product) => ({ value: product.id, label: product.name }))}
          emptyHint="Sem produtos… o cupão aplica-se a todos."
          hint="Vazio = aplica-se a todo o carrinho."
        />
        <CheckList
          label="Só estas categorias"
          values={form.category_ids ?? []}
          onChange={(next) => setForm({ ...form, category_ids: next })}
          options={ctx.catalogue.categories_index.map((category) => ({ value: category.id, label: category.name }))}
          emptyHint="Sem categorias… o cupão aplica-se a todos."
        />
        {draft.id && <p className="text-[11.5px] text-muted-foreground sm:col-span-2">Já foi usado {draft.uses ?? 0} vez(es).</p>}
      </div>
    </Sheet>
  );
}

/* ==================================================================== envios */

export function ShopShippingPanel({ ctx }: { ctx: ShopCtx }) {
  const { items, loading, load } = useList<ShopShipping>("shipping", {}, ctx);
  const [editing, setEditing] = useState<Partial<ShopShipping> | null>(null);

  return (
    <div className="space-y-3">
      <PanelHeader title="Envios" hint="Opções de entrega mostradas no carrinho. Nos produtos digitais use um método próprio (custo zero) e marque «digital».">
        <Button onClick={() => setEditing({ name: "", price: 0, free_above: 0, days_min: 1, days_max: 3, zone: "Portugal Continental", active: true, digital: false, order: (items.length + 1) * 10 })}>
          <Plus size={13} className="mr-1.5" /> Novo método
        </Button>
      </PanelHeader>

      {loading && items.length === 0 ? (
        <Loading label="A carregar métodos de envio…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sem métodos de envio" hint="Crie pelo menos um método para poder finalizar encomendas." />
      ) : (
        <div className="space-y-1.5">
          {items.map((method) => (
            <ListRow
              key={method.id}
              image=""
              title={method.name}
              subtitle={`${method.description || "sem descrição"} · ${method.zone}`}
              badges={
                <>
                  <StatusPill label={method.active ? "ativo" : "inativo"} tone={method.active ? "emerald" : "zinc"} />
                  {method.digital && <StatusPill label="digital" tone="violet" />}
                  {method.free_above > 0 && <StatusPill label={`grátis acima de ${money(method.free_above)}`} tone="sky" />}
                </>
              }
              meta={
                <>
                  <span className="font-medium text-foreground">{method.price ? money(method.price) : "grátis"}</span>
                  <span className="text-muted-foreground">{method.days_max ? `${method.days_min}–${method.days_max} dias` : "imediato"}</span>
                </>
              }
              onClick={() => setEditing(method)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => setEditing(method)}>
                    <Pencil size={12} />
                  </IconAction>
                  <IconAction
                    title="Apagar"
                    danger
                    onClick={() => {
                      if (window.confirm(`Apagar o método «${method.name}»?`))
                        shopApi.deleteShopItem("shipping", method.id).then(load).catch((error: Error) => ctx.notify(error.message, "error"));
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

      {editing && <ShippingSheet draft={editing} ctx={ctx} reload={load} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ShippingSheet({ draft, ctx, reload, onClose }: { draft: Partial<ShopShipping>; ctx: ShopCtx; reload: () => void; onClose: () => void }) {
  const [form, setForm] = useState<Partial<ShopShipping>>({ ...draft });
  const { busy, save } = useSaver(ctx, onClose, reload);
  return (
    <Sheet
      title={draft.id ? `Envio · ${draft.name}` : "Novo método de envio"}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={() => save(() => (draft.id ? shopApi.updateShopItem("shipping", draft.id, form) : shopApi.createShopItem("shipping", form)), "Método de envio guardado.")}>
            <Save size={13} className="mr-1.5" /> Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        <TextInput label="Nome" value={String(form.name ?? "")} onChange={(next) => setForm({ ...form, name: next })} wide />
        <MoneyInput label="Custo" value={Number(form.price ?? 0)} onChange={(next) => setForm({ ...form, price: next })} />
        <MoneyInput label="Grátis acima de" value={Number(form.free_above ?? 0)} onChange={(next) => setForm({ ...form, free_above: next })} hint="0 = nunca é grátis." />
        <NumberInput label="Dias mínimos" value={Number(form.days_min ?? 0)} onChange={(next) => setForm({ ...form, days_min: next })} min={0} />
        <NumberInput label="Dias máximos" value={Number(form.days_max ?? 0)} onChange={(next) => setForm({ ...form, days_max: next })} min={0} />
        <TextInput label="Zona" value={String(form.zone ?? "")} onChange={(next) => setForm({ ...form, zone: next })} hint="Ex.: Portugal Continental, Ilhas, Europa." />
        <NumberInput label="Ordem" value={Number(form.order ?? 0)} onChange={(next) => setForm({ ...form, order: next })} min={0} />
        <Toggle checked={Boolean(form.active)} onChange={(next) => setForm({ ...form, active: next })} label="Método ativo" />
        <Toggle checked={Boolean(form.digital)} onChange={(next) => setForm({ ...form, digital: next })} label="Entrega digital" hint="Sugerido quando o carrinho só tem produtos digitais." />
        <TextArea label="Descrição" value={String(form.description ?? "")} onChange={(next) => setForm({ ...form, description: next })} rows={2} />
      </div>
    </Sheet>
  );
}

/* ================================================================ avaliações */

export function ShopReviewsPanel({ ctx }: { ctx: ShopCtx }) {
  const [status, setStatus] = useState("all");
  const { items, loading, load } = useList<ShopReview>("reviews", { status }, ctx);
  const counts = useMemo(() => ({ pendente: items.filter((item) => item.status === "pendente").length }), [items]);

  const moderate = (review: ShopReview, next: "aprovada" | "rejeitada") =>
    shopApi
      .updateShopItem<ShopReview>("reviews", review.id, { status: next })
      .then(() => {
        ctx.notify(next === "aprovada" ? "Avaliação aprovada." : "Avaliação rejeitada.", "ok");
        load();
        ctx.refreshOverview();
      })
      .catch((error: Error) => ctx.notify(error.message, "error"));

  return (
    <div className="space-y-3">
      <PanelHeader title="Avaliações" hint="As avaliações enviadas na loja entram pendentes. Ao aprovar, a nota média do produto é recalculada.">
        <StatusTabs value={status} onChange={setStatus} statuses={ctx.catalogue.review_statuses} counts={counts} />
      </PanelHeader>

      {loading && items.length === 0 ? (
        <Loading label="A carregar avaliações…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sem avaliações" hint="Quando os clientes avaliarem produtos, aparecem aqui para moderação." />
      ) : (
        <div className="space-y-1.5">
          {items.map((review) => (
            <div key={review.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Stars value={review.rating} />
                <span className="text-[12.5px] font-medium text-foreground">{review.title || "(sem título)"}</span>
                <StatusPill label={review.status} tone={{ pendente: "amber", aprovada: "emerald", rejeitada: "rose" }[review.status] ?? "slate"} />
                <span className="text-[11.5px] text-muted-foreground">{review.product_name || ctx.catalogue.products_index.find((item) => item.id === review.product_id)?.name || "produto apagado"}</span>
                <div className="min-w-0 flex-1" />
                <span className="text-[11px] text-muted-foreground">{timeAgo(review.created_at)}</span>
                {review.status !== "aprovada" && (
                  <IconAction title="Aprovar" onClick={() => moderate(review, "aprovada")}>
                    <Star size={12} />
                  </IconAction>
                )}
                {review.status !== "rejeitada" && (
                  <IconAction title="Rejeitar" danger onClick={() => moderate(review, "rejeitada")}>
                    <Trash2 size={12} />
                  </IconAction>
                )}
              </div>
              {review.body && <p className="mt-1.5 text-[12.5px] text-muted-foreground">{review.body}</p>}
              <p className="mt-1 text-[11.5px] text-muted-foreground">
                {review.customer_name}
                {review.email ? ` · ${review.email}` : ""}
              </p>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <input
                  className="min-w-[220px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40"
                  placeholder="Resposta da loja (opcional)"
                  defaultValue={review.reply ?? ""}
                  onBlur={(event) => {
                    if (event.target.value !== (review.reply ?? "")) {
                      shopApi
                        .updateShopItem<ShopReview>("reviews", review.id, { reply: event.target.value })
                        .then(() => {
                          ctx.notify("Resposta guardada.", "ok");
                          load();
                        })
                        .catch((error: Error) => ctx.notify(error.message, "error"));
                    }
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================ definições */

export function ShopSettingsPanel({ ctx }: { ctx: ShopCtx }) {
  const [settings, setSettings] = useState<ShopSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    shopApi
      .getShopSettings()
      .then((payload) => setSettings(payload.settings))
      .catch((error: Error) => ctx.notify(error.message, "error"));
  }, [ctx]);

  const save = async () => {
    if (!settings) return;
    setBusy(true);
    try {
      const payload = await shopApi.saveShopSettings(settings);
      setSettings(payload.settings);
      setDirty(false);
      ctx.notify("Definições da loja guardadas.", "ok");
      ctx.refreshOverview();
    } catch (error) {
      ctx.notify((error as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (!settings) return <Loading label="A carregar definições…" />;
  const update = <K extends keyof ShopSettings>(key: K, value: ShopSettings[K]) => {
    setSettings({ ...settings, [key]: value });
    setDirty(true);
  };

  return (
    <div className="space-y-3">
      <PanelHeader title="Definições da loja" hint="Nome, contactos, impostos, pagamentos e aparência da vitrine em /loja.">
        <Button variant="ghost" onClick={() => window.open("/loja", "_blank")}>
          <Eye size={13} className="mr-1.5" /> Ver loja
        </Button>
        <Button disabled={!dirty || busy} onClick={save}>
          {busy ? <Loader2 size={13} className="mr-1.5 animate-spin" /> : <Save size={13} className="mr-1.5" />} Guardar
        </Button>
      </PanelHeader>

      {!dirty && <Notice tone="info">As alterações só chegam à loja depois de guardar.</Notice>}

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <p className="mb-2 text-[12px] font-semibold text-foreground">Identidade</p>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <TextInput label="Nome da loja" value={settings.store_name} onChange={(next) => update("store_name", next)} />
          <TextInput label="Slogan" value={settings.tagline} onChange={(next) => update("tagline", next)} />
          <TextArea label="Descrição" value={settings.description} onChange={(next) => update("description", next)} rows={2} />
          <TextInput label="Email de contacto" value={settings.email} onChange={(next) => update("email", next)} />
          <TextInput label="Telefone" value={settings.phone} onChange={(next) => update("phone", next)} />
          <TextInput label="NIF da loja" value={settings.tax_id} onChange={(next) => update("tax_id", next)} />
          <TextInput label="Morada" value={settings.address} onChange={(next) => update("address", next)} wide />
          <TextInput label="Rodapé" value={settings.footer_text} onChange={(next) => update("footer_text", next)} wide />
        </div>
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <p className="mb-2 text-[12px] font-semibold text-foreground">Vendas</p>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <MoneyInput label="Encomenda mínima" value={settings.min_order} onChange={(next) => update("min_order", next)} hint="0 = sem mínimo." />
          <NumberInput label="IVA por omissão (%)" value={settings.default_tax_rate} onChange={(next) => update("default_tax_rate", next)} min={0} max={100} />
          <NumberInput label="Aviso de stock baixo (un.)" value={settings.low_stock_threshold} onChange={(next) => update("low_stock_threshold", next)} min={0} />
          <TextInput label="Prefixo das encomendas" value={settings.order_prefix} onChange={(next) => update("order_prefix", next)} hint="Ex.: EN → EN2026-0001." />
          <Toggle checked={settings.prices_include_tax} onChange={(next) => update("prices_include_tax", next)} label="Preços com IVA incluído" hint="Como no retalho português." />
          <Toggle checked={settings.show_stock} onChange={(next) => update("show_stock", next)} label="Mostrar disponibilidade na loja" />
          <Toggle checked={settings.allow_reviews} onChange={(next) => update("allow_reviews", next)} label="Aceitar avaliações de clientes" />
        </div>
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <p className="mb-2 text-[12px] font-semibold text-foreground">Pagamentos</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {ctx.catalogue.payment_methods.map((method) => (
            <div key={method.id} className="space-y-1.5 rounded-lg border border-white/8 bg-white/[0.02] p-2.5">
              <Toggle
                checked={Boolean(settings.payments?.[method.id])}
                onChange={(next) => update("payments", { ...(settings.payments ?? {}), [method.id]: next })}
                label={method.label}
                hint={method.hint}
              />
              <textarea
                className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[11.5px] text-foreground outline-none focus:border-teal-300/40"
                rows={2}
                placeholder="Instruções mostradas ao cliente"
                value={settings.payment_instructions?.[method.id] ?? ""}
                onChange={(event) => update("payment_instructions", { ...(settings.payment_instructions ?? {}), [method.id]: event.target.value })}
              />
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">Os pagamentos são registados à mão na ficha da encomenda — não há gateway externo.</p>
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <p className="mb-2 text-[12px] font-semibold text-foreground">Aparência e SEO</p>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <SelectInput
            label="Tema"
            value={settings.theme}
            onChange={(next) => update("theme", next)}
            options={[
              { value: "claro", label: "Claro" },
              { value: "escuro", label: "Escuro" },
            ]}
          />
          <TextInput label="Cor principal" value={settings.accent} onChange={(next) => update("accent", next)} hint="Hexadecimal, ex.: #0ea5a4" />
          <NumberInput label="Cantos arredondados (px)" value={settings.radius} onChange={(next) => update("radius", next)} min={0} max={28} />
          <TextInput label="Endereço público (base)" value={settings.base_url} onChange={(next) => update("base_url", next)} hint="Ex.: https://loja.exemplo.pt (para SEO e sitemap)." />
          <TextInput label="SEO — título" value={settings.seo?.title ?? ""} onChange={(next) => update("seo", { ...(settings.seo ?? {}), title: next })} />
          <TextInput label="SEO — descrição" value={settings.seo?.description ?? ""} onChange={(next) => update("seo", { ...(settings.seo ?? {}), description: next })} />
          <TextInput label="Google Analytics (ID)" value={settings.analytics_id} onChange={(next) => update("analytics_id", next)} />
          <SelectInput
            label="Indexação"
            value={settings.robots}
            onChange={(next) => update("robots", next)}
            options={[
              { value: "index, follow", label: "Indexar (público)" },
              { value: "noindex, nofollow", label: "Não indexar" },
            ]}
          />
          <TextInput label="Ligação — LinkedIn" value={settings.social?.linkedin ?? ""} onChange={(next) => update("social", { ...(settings.social ?? {}), linkedin: next })} />
          <TextInput label="Ligação — X" value={settings.social?.x ?? ""} onChange={(next) => update("social", { ...(settings.social ?? {}), x: next })} />
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!dirty || busy} onClick={save}>
          {busy ? <Loader2 size={13} className="mr-1.5 animate-spin" /> : <Save size={13} className="mr-1.5" />} Guardar definições
        </Button>
        {settings.updated_at && <span className="text-[11.5px] text-muted-foreground">Última alteração: {timeAgo(settings.updated_at)} {settings.updated_by ? `por ${settings.updated_by}` : ""}</span>}
      </div>
    </div>
  );
}
