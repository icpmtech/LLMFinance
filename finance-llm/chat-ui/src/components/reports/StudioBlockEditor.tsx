/**
 * Editor de um bloco do **Estúdio de relatórios**.
 *
 * Cada tipo de bloco mostra só os campos que lhe interessam: os de texto pedem
 * texto (e, no caso da IA, um pedido); os de dados pedem fonte, dimensões,
 * medidas, filtros e limite. As opções de dimensões/medidas vêm do catálogo de
 * fontes, pelo que nunca se escolhe um campo que a fonte não tem.
 */
import { ChevronDown, ChevronUp, Sparkles, Trash2, Wand2 } from "lucide-react";
import { Badge, Button, Input, Label } from "../ui";
import type { StudioBlock, StudioLimits, StudioSource } from "../../reportsStudioApi";

const BLOCK_LABELS: Record<string, string> = {
  heading: "Secção",
  text: "Texto",
  note: "Nota metodológica",
  ai: "Texto com IA",
  kpi: "Indicadores",
  chart: "Gráfico",
  table: "Tabela",
  graph: "Grafo de relações",
};

const DATA_TYPES = ["kpi", "chart", "table", "graph"];

/** `{ano: 2024, regiao: ["Norte"]}` → `"ano=2024\nregiao=Norte"` */
export function filtersToText(filters: StudioBlock["filters"]): string {
  if (!filters) return "";
  if (typeof filters === "string") return filters;
  return Object.entries(filters)
    .map(([key, value]) => {
      if (Array.isArray(value)) return `${key}=${value.join(",")}`;
      if (value && typeof value === "object") {
        const bounds = value as { min?: unknown; max?: unknown };
        return `${key}=${bounds.min ?? ""}..${bounds.max ?? ""}`;
      }
      return `${key}=${value}`;
    })
    .join("\n");
}

function ChipPicker({
  options,
  selected,
  onToggle,
  limit,
  empty,
}: {
  options: { id: string; label: string; format?: string | null }[];
  selected: string[];
  onToggle: (id: string) => void;
  limit: number;
  empty: string;
}) {
  if (!options.length) return <p className="text-[11px] text-muted-foreground">{empty}</p>;
  return (
    <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-xl border bg-background p-2">
      {options.map((option) => {
        const active = selected.includes(option.id);
        const full = !active && selected.length >= limit;
        return (
          <button
            key={option.id}
            type="button"
            disabled={full}
            onClick={() => onToggle(option.id)}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
              active ? "border-primary bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground"
            } ${full ? "cursor-not-allowed opacity-40" : ""}`}
            title={option.id}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function StudioBlockEditor({
  block,
  index,
  count,
  sources,
  limits,
  chartTypes,
  onChange,
  onRemove,
  onMove,
  onAssist,
  busy,
}: {
  block: StudioBlock;
  index: number;
  count: number;
  sources: StudioSource[];
  limits: StudioLimits;
  chartTypes: { id: string; label: string }[];
  onChange: (patch: Partial<StudioBlock>) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
  onAssist: () => void;
  busy?: boolean;
}) {
  const isData = DATA_TYPES.includes(block.type);
  const source = sources.find((item) => item.id === block.source);
  const dimensions = source?.dimensions ?? [];
  const measures = source?.measures ?? [];
  const toggle = (key: "dimensions" | "measures", id: string) => {
    const current = block[key] ?? [];
    onChange({ [key]: current.includes(id) ? current.filter((item) => item !== id) : [...current, id] } as Partial<StudioBlock>);
  };

  return (
    <div className="space-y-3 rounded-xl border bg-card/40 p-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <Label htmlFor={`title-${block.id}`}>Título do bloco</Label>
          <Input
            id={`title-${block.id}`}
            value={block.title}
            onChange={(event) => onChange({ title: event.target.value })}
            placeholder={BLOCK_LABELS[block.type]}
            autoComplete="off"
          />
        </div>
        <div className="flex items-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => onMove(-1)} disabled={index === 0} title="Subir">
            <ChevronUp size={14} />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onMove(1)} disabled={index === count - 1} title="Descer">
            <ChevronDown size={14} />
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove} title="Remover bloco">
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {!isData && (
        <div className="space-y-2">
          <Label htmlFor={`text-${block.id}`}>{block.type === "ai" ? "Texto final (o PDF usa este texto)" : "Texto"}</Label>
          <textarea
            id={`text-${block.id}`}
            value={block.text}
            onChange={(event) => onChange({ text: event.target.value })}
            rows={block.type === "heading" ? 2 : 5}
            className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
            placeholder={block.type === "heading" ? "Enquadramento, âmbito e período." : "Escreva aqui…"}
          />
        </div>
      )}

      {block.type === "ai" && (
        <div className="space-y-2">
          <Label htmlFor={`prompt-${block.id}`}>Pedido à IA</Label>
          <textarea
            id={`prompt-${block.id}`}
            value={block.prompt}
            onChange={(event) => onChange({ prompt: event.target.value })}
            rows={2}
            className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
            placeholder="Ex.: escreve o sumário executivo a partir dos indicadores deste relatório."
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={onAssist} loading={busy}>
              <Wand2 size={13} /> Redigir com IA
            </Button>
            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Sparkles size={11} /> Sem modelo configurado, fica o texto montado com os dados.
            </span>
          </div>
        </div>
      )}

      {isData && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={`source-${block.id}`}>Fonte</Label>
              <select
                id={`source-${block.id}`}
                value={block.source}
                onChange={(event) => onChange({ source: event.target.value, dimensions: [], measures: [] })}
                className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
              >
                <option value="">Escolher fonte…</option>
                {sources.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            {block.type === "chart" && (
              <div className="space-y-2">
                <Label htmlFor={`chart-${block.id}`}>Tipo de gráfico</Label>
                <select
                  id={`chart-${block.id}`}
                  value={block.chart}
                  onChange={(event) => onChange({ chart: event.target.value })}
                  className="w-full rounded-xl border bg-background px-3 py-2 text-sm"
                >
                  {chartTypes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {block.type !== "kpi" && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Dimensões</Label>
                <span className="text-[11px] text-muted-foreground">
                  {block.type === "graph" ? "exatamente 2 (origem e destino)" : "até 2"} · {block.dimensions.length} escolhida(s)
                </span>
              </div>
              <ChipPicker
                options={dimensions}
                selected={block.dimensions}
                onToggle={(id) => toggle("dimensions", id)}
                limit={block.type === "graph" ? 2 : block.type === "table" ? 2 : 1}
                empty="Escolha primeiro a fonte."
              />
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Medidas</Label>
              <span className="text-[11px] text-muted-foreground">
                {block.type === "kpi" ? `até ${limits.max_kpi}` : "1 a 2"} · {block.measures.length} escolhida(s)
              </span>
            </div>
            <ChipPicker
              options={measures}
              selected={block.measures}
              onToggle={(id) => toggle("measures", id)}
              limit={block.type === "kpi" ? limits.max_kpi : block.type === "table" ? limits.max_measures : 1}
              empty="Escolha primeiro a fonte."
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor={`limit-${block.id}`}>Grupos a trazer</Label>
              <Input
                id={`limit-${block.id}`}
                type="number"
                min={1}
                max={limits.max_rows}
                value={String(block.limit)}
                onChange={(event) => onChange({ limit: Number(event.target.value) || 1 })}
              />
            </div>
            {(block.type === "chart" || block.type === "table") && (
              <div className="space-y-2">
                <Label htmlFor={`top-${block.id}`}>Mostrar apenas (Top-N)</Label>
                <Input
                  id={`top-${block.id}`}
                  type="number"
                  min={0}
                  max={limits.max_rows}
                  value={String(block.top_n)}
                  onChange={(event) => onChange({ top_n: Number(event.target.value) || 0 })}
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor={`filters-${block.id}`}>Filtros</Label>
              <textarea
                id={`filters-${block.id}`}
                value={filtersToText(block.filters)}
                onChange={(event) => onChange({ filters: event.target.value })}
                rows={2}
                className="w-full rounded-xl border bg-background px-3 py-2 text-xs"
                placeholder="ano=2024&#10;regiao=Norte,Centro"
              />
            </div>
          </div>

          {source && (
            <p className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <Badge variant="outline">{source.label}</Badge>
              {source.defaults?.dimension ? <span>sugestão: {source.defaults.dimension}</span> : null}
            </p>
          )}
        </>
      )}

      <div className="flex items-center gap-2">
        <Label className="text-[11px]">Largura</Label>
        <select
          value={String(block.width)}
          onChange={(event) => onChange({ width: Number(event.target.value) })}
          className="rounded-lg border bg-background px-2 py-1 text-xs"
        >
          {limits.widths.map((width) => (
            <option key={width} value={String(width)}>
              {width >= 12 ? "Toda a largura" : width === 6 ? "Meia largura" : "Um terço"}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
