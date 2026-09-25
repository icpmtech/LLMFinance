/**
 * Editor de vitrine — a montra da loja montada por secções, como num construtor
 * de temas (à moda do Shopify): à esquerda o aviso, a apresentação e a lista de
 * secções (com ordem, visibilidade e campos próprios); à direita a
 * **pré-visualização ao vivo** de `/loja`.
 *
 * As alterações são gravadas automaticamente (com um pequeno atraso) e a
 * pré-visualização recarrega logo a seguir, pelo que se vê o resultado enquanto
 * se escreve. Os tipos de secção e os seus campos vêm do servidor
 * (`GET /shop/theme`), tal como no editor de blocos do CMS: acrescentar um tipo
 * novo no backend faz aparecer o editor sem mexer aqui.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  Monitor,
  Plus,
  RefreshCw,
  RotateCcw,
  Smartphone,
  Trash2,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import * as shopApi from "../shopApi";
import type { ShopTheme, ShopThemeCatalogue, ShopThemeField, ShopThemeSection, ShopThemeSectionType } from "../shopApi";
import { EmptyState, Notice, NumberInput, PanelHeader, SelectInput, Sheet, TextArea, TextInput, Toggle, labelClass, timeAgo } from "../components/shop/ShopKit";
import type { ShopCtx } from "./ShopPanels";

const AUTOSAVE_MS = 700;

type Status = "idle" | "saving" | "saved" | "error";

function newSectionId(): string {
  return `sec_${Math.random().toString(36).slice(2, 10)}`;
}

function sectionLabel(types: ShopThemeSectionType[], type: string): string {
  return types.find((entry) => entry.id === type)?.label ?? type;
}

export function ShopThemePanel({ ctx }: { ctx: ShopCtx }) {
  const [catalogue, setCatalogue] = useState<ShopThemeCatalogue | null>(null);
  const [theme, setTheme] = useState<ShopTheme | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [previewVersion, setPreviewVersion] = useState(() => Date.now());
  const dirty = useRef(false);

  const load = useCallback(() => {
    shopApi
      .getShopTheme()
      .then((payload) => {
        setCatalogue(payload);
        setTheme(payload.theme);
        setOpen(payload.theme.sections[0]?.id ?? null);
        dirty.current = false;
        setStatus("idle");
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Gravação automática: escreve, espera um instante e recarrega a pré-visualização.
  useEffect(() => {
    if (!theme || !dirty.current) return;
    setStatus("saving");
    const timer = window.setTimeout(() => {
      shopApi
        .saveShopTheme(theme)
        .then(() => {
          setStatus("saved");
          setError("");
          setPreviewVersion(Date.now());
        })
        .catch((err: Error) => {
          setStatus("error");
          setError(err.message);
        });
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [theme]);

  const update = useCallback((mutate: (current: ShopTheme) => ShopTheme) => {
    dirty.current = true;
    setTheme((current) => (current ? mutate(current) : current));
  }, []);

  const patchSection = useCallback(
    (id: string, patch: Record<string, unknown>) =>
      update((current) => ({
        ...current,
        sections: current.sections.map((section) => (section.id === id ? { ...section, ...patch } : section)),
      })),
    [update],
  );

  const move = (index: number, delta: number) =>
    update((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.sections.length) return current;
      const sections = [...current.sections];
      [sections[index], sections[target]] = [sections[target], sections[index]];
      return { ...current, sections };
    });

  const remove = (id: string) =>
    update((current) => ({ ...current, sections: current.sections.filter((section) => section.id !== id) }));

  const duplicate = (id: string) =>
    update((current) => {
      const index = current.sections.findIndex((section) => section.id === id);
      if (index < 0) return current;
      const clone: ShopThemeSection = { ...current.sections[index], id: newSectionId() };
      const sections = [...current.sections];
      sections.splice(index + 1, 0, clone);
      return { ...current, sections };
    });

  const addSection = (type: string) => {
    const preset = catalogue?.defaults.sections.find((section) => section.type === type);
    const section: ShopThemeSection = { ...(preset ?? { type, enabled: true }), id: newSectionId(), type, enabled: true };
    update((current) => ({ ...current, sections: [...current.sections, section] }));
    setOpen(section.id);
    setAdding(false);
  };

  const restoreDefaults = () => {
    if (!window.confirm("Repor a vitrine predefinida? As alterações atuais perdem-se.")) return;
    shopApi
      .resetShopTheme()
      .then((payload) => {
        setTheme(payload.theme);
        dirty.current = false;
        setStatus("saved");
        setPreviewVersion(Date.now());
      })
      .catch((err: Error) => setError(err.message));
  };

  const previewUrl = useMemo(() => `${shopApi.SHOP_STORE_URL}?preview=1&v=${previewVersion}`, [previewVersion]);

  if (!catalogue || !theme) {
    return error ? (
      <Notice tone="error">{error}</Notice>
    ) : (
      <p className="flex items-center gap-2 py-16 text-[12.5px] text-muted-foreground">
        <Loader2 size={15} className="animate-spin" /> A carregar o editor de vitrine…
      </p>
    );
  }

  const types = catalogue.section_types;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PanelHeader
        title="Vitrine"
        hint="Monte a página inicial da loja por secções e veja o resultado ao lado. As imagens vêm da biblioteca do CMS."
      >
        <span
          className={[
            "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px]",
            status === "saving"
              ? "border-amber-400/30 bg-amber-400/10 text-amber-100"
              : status === "error"
                ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                : "border-white/10 bg-white/[0.04] text-muted-foreground",
          ].join(" ")}
          title={status === "saved" ? `Guardado às ${new Date().toLocaleTimeString("pt-PT")}` : undefined}
        >
          {status === "saving" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          {status === "saving" ? "A guardar…" : status === "error" ? "Erro ao guardar" : status === "saved" ? "Guardado" : "Sem alterações"}
        </span>
        <Button variant="ghost" onClick={restoreDefaults}>
          <RotateCcw size={13} className="mr-1.5" /> Repor
        </Button>
        <a
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12.5px] text-foreground hover:bg-white/[0.1]"
          href={catalogue.store_url}
          target="_blank"
          rel="noreferrer"
        >
          Ver loja
        </a>
      </PanelHeader>

      {error && status === "error" && (
        <div className="mb-2">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(340px,400px)_minmax(0,1fr)]">
        {/* ------------------------------------------------------ editor */}
        <div className="min-h-0 space-y-2.5 overflow-y-auto pr-0.5 lg:max-h-[calc(100vh-260px)]">
          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={`${labelClass} mb-2`}>Aviso da loja</p>
            <div className="space-y-2">
              <Toggle
                checked={theme.announcement.enabled}
                onChange={(next) => update((current) => ({ ...current, announcement: { ...current.announcement, enabled: next } }))}
                label="Mostrar faixa de aviso"
                hint="Aparece no topo de todas as páginas. Sem texto próprio, mostra os portes grátis."
              />
              <TextInput
                label="Texto"
                value={theme.announcement.text}
                onChange={(next) => update((current) => ({ ...current, announcement: { ...current.announcement, text: next } }))}
                placeholder="Portes grátis em encomendas acima de 60 €"
                wide
              />
              <TextInput
                label="Ligação (opcional)"
                value={theme.announcement.link}
                onChange={(next) => update((current) => ({ ...current, announcement: { ...current.announcement, link: next } }))}
                placeholder="/loja/produtos"
              />
              <TextInput
                label="Texto da ligação"
                value={theme.announcement.link_label}
                onChange={(next) => update((current) => ({ ...current, announcement: { ...current.announcement, link_label: next } }))}
                placeholder="Comprar"
              />
            </div>
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <p className={`${labelClass} mb-2`}>Apresentação</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <NumberInput
                label="Produtos por linha"
                value={theme.catalog_columns}
                onChange={(next) => update((current) => ({ ...current, catalog_columns: next }))}
                min={2}
                max={5}
                hint="Aplica-se às grelhas da montra e do catálogo."
              />
              <TextInput
                label="Nota no rodapé"
                value={theme.footer_note ?? ""}
                onChange={(next) => update((current) => ({ ...current, footer_note: next }))}
                hint="Uma linha extra na primeira coluna do rodapé."
              />
            </div>
          </section>

          <section className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center gap-2">
              <p className={labelClass}>Secções da montra</p>
              <span className="text-[10.5px] text-muted-foreground">{theme.sections.length} de {catalogue.max_sections}</span>
              <div className="flex-1" />
              <Button variant="ghost" size="sm" onClick={() => setAdding(true)}>
                <Plus size={12} className="mr-1" /> Secção
              </Button>
            </div>

            {theme.sections.length === 0 && (
              <EmptyState title="Montra sem secções" hint="Acrescente um destaque, produtos, categorias ou vantagens. Sem secções, a loja mostra o catálogo completo." />
            )}

            <div className="space-y-1.5">
              {theme.sections.map((section, index) => {
                const info = types.find((entry) => entry.id === section.type);
                const expanded = open === section.id;
                return (
                  <div key={section.id} className={["rounded-xl border border-white/8 bg-white/[0.02]", section.enabled ? "" : "opacity-60"].join(" ")}>
                    <header className="flex items-center gap-1.5 px-2.5 py-2">
                      <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(expanded ? null : section.id)}>
                        <span className="flex items-center gap-2">
                          <span className="truncate text-[12.5px] font-medium text-foreground">{sectionLabel(types, section.type)}</span>
                          {!section.enabled && <span className="rounded-full border border-white/10 bg-white/[0.04] px-1.5 text-[10px] text-muted-foreground">oculta</span>}
                        </span>
                        <span className="mt-0.5 block truncate text-[10.5px] text-muted-foreground">
                          {String(section.title || info?.hint || "")}
                        </span>
                      </button>
                      <button type="button" title="Subir" onClick={() => move(index, -1)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground">
                        <ArrowUp size={12} />
                      </button>
                      <button type="button" title="Descer" onClick={() => move(index, 1)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground">
                        <ArrowDown size={12} />
                      </button>
                      <button
                        type="button"
                        title={section.enabled ? "Ocultar da loja" : "Mostrar na loja"}
                        onClick={() => patchSection(section.id, { enabled: !section.enabled })}
                        className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                      >
                        {section.enabled ? <Eye size={12} /> : <EyeOff size={12} />}
                      </button>
                      <button type="button" title="Duplicar secção" onClick={() => duplicate(section.id)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground">
                        <Copy size={12} />
                      </button>
                      <button type="button" title="Apagar secção" onClick={() => remove(section.id)} className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-rose-200">
                        <Trash2 size={12} />
                      </button>
                    </header>
                    {expanded && (
                      <div className="border-t border-white/8 px-2.5 py-2.5">
                        <SectionFields
                          fields={info?.fields ?? []}
                          section={section}
                          onChange={(patch) => patchSection(section.id, patch)}
                          ctx={ctx}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        {/* ------------------------------------------------- pré-visualização */}
        <div className="flex min-h-0 flex-col rounded-xl border border-white/8 bg-white/[0.02] p-2.5 lg:max-h-[calc(100vh-260px)]">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className={labelClass}>Pré-visualização</span>
            <span className="text-[10.5px] text-muted-foreground">{timeAgo(new Date(previewVersion).toISOString())}</span>
            <div className="flex-1" />
            <div className="flex items-center gap-0.5 rounded-lg border border-white/8 bg-white/[0.05] p-0.5">
              <button
                type="button"
                onClick={() => setDevice("desktop")}
                title="Ecrã grande"
                className={["rounded-md px-2 py-1", device === "desktop" ? "bg-white/[0.16] text-foreground" : "text-muted-foreground"].join(" ")}
              >
                <Monitor size={12} />
              </button>
              <button
                type="button"
                onClick={() => setDevice("mobile")}
                title="Telemóvel"
                className={["rounded-md px-2 py-1", device === "mobile" ? "bg-white/[0.16] text-foreground" : "text-muted-foreground"].join(" ")}
              >
                <Smartphone size={12} />
              </button>
            </div>
            <button
              type="button"
              onClick={() => setPreviewVersion(Date.now())}
              title="Recarregar a pré-visualização"
              className="rounded-lg border border-white/8 bg-white/[0.04] p-1.5 text-muted-foreground hover:text-foreground"
            >
              <RefreshCw size={12} />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-white/8 bg-white">
            <iframe
              key={previewUrl}
              src={previewUrl}
              title="Pré-visualização da vitrine"
              className="h-full min-h-[520px] w-full border-0"
              style={device === "mobile" ? { width: 420, margin: "0 auto", display: "block" } : undefined}
            />
          </div>
        </div>
      </div>

      {adding && <SectionPicker types={types} onPick={addSection} onClose={() => setAdding(false)} />}
    </div>
  );
}

/* ------------------------------------------------------------------ campos */

function SectionFields({
  fields,
  section,
  onChange,
  ctx,
}: {
  fields: ShopThemeField[];
  section: ShopThemeSection;
  onChange: (patch: Record<string, unknown>) => void;
  ctx: ShopCtx;
}) {
  if (fields.length === 0) {
    return <p className="text-[11.5px] text-muted-foreground">Esta secção não tem campos configuráveis.</p>;
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {fields.map((field) => {
        const value = section[field.key as keyof ShopThemeSection];
        switch (field.kind) {
          case "number":
            return (
              <NumberInput
                key={field.key}
                label={field.label}
                value={Number(value ?? field.min ?? 0)}
                min={field.min}
                max={field.max}
                onChange={(next) => onChange({ [field.key]: next })}
              />
            );
          case "bool":
            return (
              <div key={field.key} className="sm:col-span-2">
                <Toggle checked={Boolean(value)} onChange={(next) => onChange({ [field.key]: next })} label={field.label} />
              </div>
            );
          case "select":
          case "icon":
            return (
              <SelectInput
                key={field.key}
                label={field.label}
                value={String(value ?? "")}
                onChange={(next) => onChange({ [field.key]: next })}
                options={(field.options ?? []).map((option) => ({ value: String(option.value ?? option.id ?? ""), label: option.label }))}
                wide={field.wide}
              />
            );
          case "category":
            return (
              <SelectInput
                key={field.key}
                label={field.label}
                value={String(value ?? "")}
                onChange={(next) => onChange({ [field.key]: next })}
                options={ctx.catalogue.categories_index.map((category) => ({ value: category.id, label: category.name }))}
                placeholder="— todas —"
                wide={field.wide}
              />
            );
          case "media":
            return (
              <SelectInput
                key={field.key}
                label={field.label}
                value={String(value ?? "")}
                onChange={(next) => onChange({ [field.key]: next || null })}
                options={ctx.catalogue.media_index.filter((item) => item.kind === "imagem").map((item) => ({ value: item.id, label: item.title || item.id }))}
                placeholder="— sem imagem —"
                wide={field.wide}
              />
            );
          case "textarea":
            return (
              <TextArea
                key={field.key}
                label={field.label}
                value={String(value ?? "")}
                onChange={(next) => onChange({ [field.key]: next })}
                rows={field.rows ?? 4}
                mono={field.mono}
                wide={field.wide ?? field.kind === "textarea"}
              />
            );
          case "items":
            return <ItemsField key={field.key} field={field} value={(value as Record<string, string>[]) ?? []} onChange={(next) => onChange({ [field.key]: next })} />;
          default:
            return (
              <TextInput
                key={field.key}
                label={field.label}
                value={String(value ?? "")}
                onChange={(next) => onChange({ [field.key]: next })}
                wide={field.wide}
              />
            );
        }
      })}
    </div>
  );
}

function ItemsField({
  field,
  value,
  onChange,
}: {
  field: ShopThemeField;
  value: Record<string, string>[];
  onChange: (next: Record<string, string>[]) => void;
}) {
  const itemFields = field.item_fields ?? [];
  const blank = () => Object.fromEntries(itemFields.map((entry) => [entry.key, entry.kind === "select" || entry.kind === "icon" ? String(entry.options?.[0]?.id ?? "") : ""]));
  return (
    <div className="sm:col-span-2">
      <div className="mb-1.5 flex items-center gap-2">
        <span className={labelClass}>{field.label}</span>
        <button
          type="button"
          onClick={() => onChange([...value, blank()])}
          className="rounded-md border border-white/8 bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
        >
          acrescentar
        </button>
      </div>
      <div className="space-y-2">
        {value.length === 0 && <p className="text-[11.5px] text-muted-foreground">Sem itens.</p>}
        {value.map((item, index) => (
          <div key={index} className="rounded-lg border border-white/8 bg-white/[0.02] p-2">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-[10.5px] text-muted-foreground">#{index + 1}</span>
              <div className="flex-1" />
              <button
                type="button"
                title="Remover"
                onClick={() => onChange(value.filter((_, position) => position !== index))}
                className="rounded p-1 text-muted-foreground hover:text-rose-200"
              >
                <Trash2 size={12} />
              </button>
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {itemFields.map((entry) =>
                entry.kind === "select" || entry.kind === "icon" ? (
                  <SelectInput
                    key={entry.key}
                    label={entry.label}
                    value={item[entry.key] ?? ""}
                    onChange={(next) => onChange(value.map((current, position) => (position === index ? { ...current, [entry.key]: next } : current)))}
                    options={(entry.options ?? []).map((option) => ({ value: String(option.value ?? option.id ?? ""), label: option.label }))}
                  />
                ) : entry.kind === "textarea" ? (
                  <TextArea
                    key={entry.key}
                    label={entry.label}
                    value={item[entry.key] ?? ""}
                    onChange={(next) => onChange(value.map((current, position) => (position === index ? { ...current, [entry.key]: next } : current)))}
                    rows={2}
                    wide
                  />
                ) : (
                  <TextInput
                    key={entry.key}
                    label={entry.label}
                    value={item[entry.key] ?? ""}
                    onChange={(next) => onChange(value.map((current, position) => (position === index ? { ...current, [entry.key]: next } : current)))}
                    wide={entry.wide}
                  />
                ),
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionPicker({ types, onPick, onClose }: { types: ShopThemeSectionType[]; onPick: (type: string) => void; onClose: () => void }) {
  return (
    <Sheet title="Acrescentar secção" subtitle="Escolha o tipo de secção para a montra." onClose={onClose}>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {types.map((type) => (
          <button
            key={type.id}
            type="button"
            onClick={() => onPick(type.id)}
            className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2.5 text-left transition hover:border-teal-300/40 hover:bg-white/[0.06]"
          >
            <span className="block text-[12.5px] font-medium text-foreground">{type.label}</span>
            <span className="mt-0.5 block text-[11px] text-muted-foreground">{type.hint}</span>
          </button>
        ))}
      </div>
    </Sheet>
  );
}
