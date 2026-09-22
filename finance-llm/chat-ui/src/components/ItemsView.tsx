/**
 * Vistas de itens (cartões, lista e imagens) — usadas pela Recolha e pela
 * Pesquisa total.
 *
 * Um «item» mostra sempre **os valores extraídos** (os campos que a fonte
 * recolheu, ou os dados que o âmbito de pesquisa devolve): é isso que distingue
 * uma lista de resultados de uma lista de títulos.
 *
 * As imagens são as que vêm nos dados — o URL original do site, sem cópia local.
 * Envia-se `referrerPolicy="no-referrer"` porque muitos CDNs de imprensa
 * recusam pedidos com a referência de outra página, e um marcador toma o lugar
 * da imagem quando ela já não existe.
 */
import { useState } from "react";
import { ExternalLink, ImageOff, Images, LayoutGrid, List } from "lucide-react";

export type ItemsView = "cards" | "lista" | "imagens";

/** Item já normalizado, seja de recolha, contratos, notícias ou CRM. */
export type DisplayItem = {
  id: string;
  title: string;
  subtitle?: string;
  /** Resumo, entrada ou excerto — o que houver de mais curto. */
  summary?: string;
  url?: string;
  image?: string | null;
  date?: string | null;
  badges?: string[];
  /** Etiquetas clicáveis (a Recolha usa-as como filtro). */
  tags?: string[];
  /** Valores extraídos, mostrados em tabela. */
  values?: Record<string, unknown>;
  /** Ações próprias de cada módulo (abrir ficha, abrir site, …). */
  actions?: React.ReactNode;
};

const dateFormat = new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" });

export function formatItemDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return dateFormat.format(date);
}

function isHttpUrl(value: unknown): value is string {
  return typeof value === "string" && /^(https?:)?\/\//i.test(value.trim()) && !value.startsWith("data:");
}

/** Valores do item: usa `values` ou, em alternativa, o campo `extra.valores`. */
export function valuesOf(item: DisplayItem): Record<string, unknown> {
  const direct = item.values ?? {};
  const nested = (direct as { valores?: unknown }).valores;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    return { ...(nested as Record<string, unknown>), ...direct };
  }
  return direct;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map((entry) => formatValue(entry)).join(" · ");
  if (typeof value === "boolean") return value ? "sim" : "não";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Imagem do item: campo `image` ou o campo de valores que pareça uma imagem. */
export function itemImage(item: DisplayItem): string | null {
  if (isHttpUrl(item.image)) return item.image.trim();
  const values = valuesOf(item);
  for (const name of ["imagem", "image", "img", "thumbnail", "foto", "cover", "imagem_url", "image_url"]) {
    for (const [key, value] of Object.entries(values)) {
      if (key.toLowerCase() === name && isHttpUrl(value)) return String(value).trim();
    }
  }
  for (const [key, value] of Object.entries(values)) {
    if (/(img|image|imagem|foto|thumb|cover|logo)/i.test(key) && isHttpUrl(value)) return String(value).trim();
  }
  return null;
}

export function ItemThumb({
  src,
  alt,
  className = "h-16 w-24",
}: {
  src: string | null;
  alt: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div
        className={`grid shrink-0 place-items-center rounded-lg border border-white/10 bg-black/30 text-muted-foreground ${className}`}
        aria-hidden="true"
      >
        <ImageOff size={14} />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-lg border border-white/10 object-cover ${className}`}
    />
  );
}

/** Tabela de valores extraídos (fora a ligação e a imagem, que já se veem). */
export function ItemValues({
  item,
  max = 8,
  dense,
}: {
  item: DisplayItem;
  max?: number;
  dense?: boolean;
}) {
  const image = itemImage(item);
  const entries = Object.entries(valuesOf(item)).filter(([key, value]) => {
    const name = key.toLowerCase();
    if (name === "url" || name === "link" || name === "href" || name === "valores") return false;
    if (value === null || value === undefined || value === "") return false;
    if (isHttpUrl(value) && value === image) return false;
    if (typeof value === "object" && !Array.isArray(value)) return false;
    return true;
  });
  if (!entries.length) return null;
  const shown = entries.slice(0, max);
  const hidden = entries.length - shown.length;
  return (
    <dl className={`mt-1.5 ${dense ? "space-y-0.5" : "grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5"} text-[10px]`}>
      {shown.map(([key, value]) => {
        const formatted = formatValue(value);
        if (dense) {
          return (
            <div key={key} className="flex gap-1">
              <dt className="shrink-0 text-muted-foreground">{key}:</dt>
              <dd className="truncate" title={formatted}>
                {formatted}
              </dd>
            </div>
          );
        }
        return (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="truncate" title={formatted}>
              {formatted}
            </dd>
          </div>
        );
      })}
      {hidden > 0 ? <p className="col-span-2 mt-0.5 text-[10px] text-muted-foreground">+{hidden} campos</p> : null}
    </dl>
  );
}

function ItemBadges({
  item,
  onTagClick,
}: {
  item: DisplayItem;
  onTagClick?: (tag: string) => void;
}) {
  const badges = item.badges ?? [];
  const tags = item.tags ?? [];
  if (!badges.length && !tags.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      {badges.slice(0, 4).map((badge, index) => (
        <span key={`${badge}-${index}`} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
          {badge}
        </span>
      ))}
      {tags.slice(0, 6).map((tag) =>
        onTagClick ? (
          <button
            key={tag}
            type="button"
            onClick={() => onTagClick(tag)}
            className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10"
          >
            #{tag}
          </button>
        ) : (
          <span key={tag} className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
            #{tag}
          </span>
        ),
      )}
    </div>
  );
}

function ItemLink({ url, compact }: { url: string; compact?: boolean }) {
  const label = url.replace(/^https?:\/\//, "");
  if (compact) {
    return (
      <a href={url} target="_blank" rel="noreferrer" className="mt-1 block truncate text-[10px] text-sky-300 hover:underline">
        {label}
      </a>
    );
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="mt-2 inline-flex items-center gap-1 text-[10px] text-sky-300 hover:underline"
      title={url}
    >
      <ExternalLink size={10} /> {label.slice(0, 70)}
    </a>
  );
}

/** Cartão: imagem, título, proveniência, resumo e valores. */
export function ItemCard({
  item,
  onTagClick,
}: {
  item: DisplayItem;
  onTagClick?: (tag: string) => void;
}) {
  const image = itemImage(item);
  return (
    <article className="glass-card flex h-full flex-col overflow-hidden rounded-2xl">
      {image ? <ItemThumb src={image} alt={item.title || "imagem do item"} className="h-36 w-full !rounded-none !border-0" /> : null}
      <div className="flex flex-1 flex-col p-3">
        <div className="flex flex-wrap items-start gap-2">
          <p className="min-w-0 flex-1 text-xs font-medium">{item.title || item.id}</p>
          {item.date ? <span className="text-[10px] text-muted-foreground">{formatItemDate(item.date)}</span> : null}
        </div>
        {item.subtitle ? <p className="mt-0.5 truncate text-[10px] text-muted-foreground">{item.subtitle}</p> : null}
        {item.summary ? <p className="mt-1 line-clamp-3 text-[11px] text-muted-foreground">{item.summary}</p> : null}
        <ItemValues item={item} max={6} />
        <ItemBadges item={item} onTagClick={onTagClick} />
        {item.url ? <ItemLink url={item.url} /> : null}
        {item.actions ? <div className="mt-2 flex flex-wrap items-center gap-2">{item.actions}</div> : null}
      </div>
    </article>
  );
}

/** Linha compacta (vista de lista). */
export function ItemRow({
  item,
  onTagClick,
}: {
  item: DisplayItem;
  onTagClick?: (tag: string) => void;
}) {
  const image = itemImage(item);
  return (
    <li className="glass-card rounded-2xl px-3 py-2">
      <div className="flex items-start gap-3">
        <ItemThumb src={image} alt={item.title || "imagem do item"} className="h-12 w-16" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="min-w-0 flex-1 truncate text-xs font-medium">{item.title || item.id}</p>
            {item.subtitle ? (
              <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground">
                {item.subtitle}
              </span>
            ) : null}
            {item.date ? <span className="text-[10px] text-muted-foreground">{formatItemDate(item.date)}</span> : null}
          </div>
          {item.summary ? <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{item.summary}</p> : null}
          <ItemValues item={item} max={10} dense />
          <ItemBadges item={item} onTagClick={onTagClick} />
          {item.url ? <ItemLink url={item.url} compact /> : null}
          {item.actions ? <div className="mt-1.5 flex flex-wrap items-center gap-2">{item.actions}</div> : null}
        </div>
      </div>
    </li>
  );
}

/** Mosaico de imagens, com o título e os valores por baixo. */
export function ItemImageTile({ item }: { item: DisplayItem }) {
  const image = itemImage(item);
  return (
    <figure className="glass-card overflow-hidden rounded-2xl">
      <ItemThumb src={image} alt={item.title || "imagem do item"} className="h-40 w-full !rounded-none !border-0" />
      <figcaption className="p-2">
        <p className="line-clamp-2 text-[11px] font-medium">{item.title || item.id}</p>
        {item.subtitle ? <p className="truncate text-[10px] text-muted-foreground">{item.subtitle}</p> : null}
        <ItemValues item={item} max={4} dense />
      </figcaption>
    </figure>
  );
}

/** Seletor da vista: cartões, lista ou imagens. */
export function ItemsViewToggle({ value, onChange }: { value: ItemsView; onChange: (next: ItemsView) => void }) {
  const options: { id: ItemsView; label: string; icon: React.ReactNode }[] = [
    { id: "cards", label: "Cartões", icon: <LayoutGrid size={12} /> },
    { id: "lista", label: "Lista", icon: <List size={12} /> },
    { id: "imagens", label: "Imagens", icon: <Images size={12} /> },
  ];
  return (
    <div className="inline-flex items-center gap-0.5 rounded-xl border border-white/10 bg-white/5 p-0.5" role="group" aria-label="Vista dos itens">
      {options.map((option) => {
        const active = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.id)}
            title={option.label}
            className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] transition focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 ${
              active ? "bg-white/15 font-medium text-foreground" : "text-muted-foreground hover:bg-white/10"
            }`}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Lista de itens na vista escolhida. A grelha adapta-se à largura disponível
 * (`auto-fill`): o painel das execuções é estreito, o da pesquisa é largo.
 */
export function ItemsCollection({
  items,
  view,
  onTagClick,
  className,
}: {
  items: DisplayItem[];
  view: ItemsView;
  onTagClick?: (tag: string) => void;
  className?: string;
}) {
  if (view === "imagens") {
    const comImagem = items.filter((item) => itemImage(item));
    if (!comImagem.length) {
      return (
        <p className={`py-6 text-center text-xs text-muted-foreground ${className ?? ""}`}>
          Nenhum destes itens tem imagem recolhida. Ligue o campo da imagem na definição da fonte (ou escolha a vista de cartões).
        </p>
      );
    }
    return (
      <div className={className}>
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
          {comImagem.map((item) => (
            <ItemImageTile key={item.id} item={item} />
          ))}
        </div>
        {comImagem.length < items.length ? (
          <p className="mt-2 text-[10px] text-muted-foreground">
            {items.length - comImagem.length} itens sem imagem ficaram de fora desta vista.
          </p>
        ) : null}
      </div>
    );
  }
  if (view === "lista") {
    return (
      <ul className={`space-y-2 ${className ?? ""}`}>
        {items.map((item) => (
          <ItemRow key={item.id} item={item} onTagClick={onTagClick} />
        ))}
      </ul>
    );
  }
  return (
    <div className={`grid gap-2 ${className ?? ""}`} style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
      {items.map((item) => (
        <ItemCard key={item.id} item={item} onTagClick={onTagClick} />
      ))}
    </div>
  );
}
