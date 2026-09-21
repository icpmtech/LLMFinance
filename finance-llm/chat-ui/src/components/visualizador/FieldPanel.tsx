/**
 * Painel de campos do Visualizador (coluna esquerda).
 *
 * Escolhe o dataset, mostra as suas dimensões/medidas (clicar acrescenta ao
 * visual ativo — como no Power BI), aplica filtros e sugere análises prontas.
 */
import { useEffect, useState } from "react";
import {
  BarChart3,
  CalendarRange,
  Database,
  Hash,
  ListFilter,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Tag,
  Type,
  CheckSquare,
  X,
} from "lucide-react";
import type { DatasetDetail, VisualDimension, VisualizadorMeta, VisualSuggestion } from "../../visualizadorApi";
import { getVisualValues } from "../../visualizadorApi";

function dimensionIcon(dimension: VisualDimension) {
  if (dimension.type === "date") return <CalendarRange size={12} />;
  if (dimension.type === "number") return <Hash size={12} />;
  if (dimension.type === "boolean") return <CheckSquare size={12} />;
  if (dimension.type === "text") return <Type size={12} />;
  return <Tag size={12} />;
}

function FilterRow({
  datasetId,
  dimension,
  value,
  filters,
  onChange,
}: {
  datasetId: string;
  dimension: VisualDimension;
  value: unknown;
  filters: Record<string, unknown>;
  onChange: (filters: Record<string, unknown>) => void;
}) {
  const [options, setOptions] = useState<(string | number)[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || dimension.type === "number" || dimension.type === "date" || (dimension.enum?.length ?? 0) > 0) return;
    let cancelled = false;
    setLoading(true);
    getVisualValues({ dataset: datasetId, field: dimension.id, limit: 40 })
      .then((response) => {
        if (!cancelled) setOptions(response.items ?? []);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, datasetId, dimension.id, dimension.type, dimension.enum]);

  const setValue = (next: unknown) => {
    const updated = { ...filters };
    if (next === "" || next === null || next === undefined) delete updated[dimension.id];
    else updated[dimension.id] = next;
    onChange(updated);
  };

  const inputClass = "w-full px-2 py-1.5 rounded-lg glass-card text-xs";

  if (dimension.type === "number") {
    const range = (value && typeof value === "object" ? value : {}) as { min?: number; max?: number };
    return (
      <div className="flex items-center gap-1.5">
        <input type="number" placeholder="mín" value={range.min ?? ""} aria-label={`${dimension.label} mínimo`}
               onChange={(event) => setValue({ ...range, min: event.target.value === "" ? undefined : Number(event.target.value) })}
               className={inputClass} />
        <input type="number" placeholder="máx" value={range.max ?? ""} aria-label={`${dimension.label} máximo`}
               onChange={(event) => setValue({ ...range, max: event.target.value === "" ? undefined : Number(event.target.value) })}
               className={inputClass} />
      </div>
    );
  }

  if (dimension.type === "date") {
    const range = (value && typeof value === "object" ? value : {}) as { min?: string; max?: string };
    return (
      <div className="flex items-center gap-1.5">
        <input type="date" value={range.min ?? ""} aria-label={`${dimension.label} desde`}
               onChange={(event) => setValue({ ...range, min: event.target.value || undefined })} className={inputClass} />
        <input type="date" value={range.max ?? ""} aria-label={`${dimension.label} até`}
               onChange={(event) => setValue({ ...range, max: event.target.value || undefined })} className={inputClass} />
      </div>
    );
  }

  if (dimension.type === "boolean") {
    return (
      <select value={value === undefined ? "" : String(value)} onChange={(event) => setValue(event.target.value || undefined)}
              aria-label={dimension.label} className={inputClass}>
        <option value="">todos</option>
        <option value="true">sim</option>
        <option value="false">não</option>
      </select>
    );
  }

  if ((dimension.enum?.length ?? 0) > 0) {
    return (
      <select value={String(value ?? "")} onChange={(event) => setValue(event.target.value || undefined)}
              aria-label={dimension.label} className={inputClass}>
        <option value="">todos</option>
        {dimension.enum?.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    );
  }

  return (
    <div className="relative">
      <input
        value={typeof value === "string" ? value : ""}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onChange={(event) => setValue(event.target.value)}
        placeholder="escrever…"
        aria-label={dimension.label}
        className={inputClass}
      />
      {open && (loading || options.length > 0) && (
        <div className="absolute z-20 mt-1 w-full max-h-44 overflow-y-auto rounded-xl glass-modal p-1 text-xs">
          {loading && <div className="px-2 py-1.5 text-muted-foreground flex items-center gap-1.5"><Loader2 size={11} className="animate-spin" /> a carregar…</div>}
          {options.slice(0, 40).map((option) => (
            <button key={String(option)} type="button" onMouseDown={() => setValue(String(option))}
                    className="block w-full text-left px-2 py-1 rounded-lg hover:bg-white/10 truncate">
              {String(option)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function FieldPanel({
  meta,
  detail,
  datasetId,
  onSelectDataset,
  filters,
  onFiltersChange,
  search,
  onSearchChange,
  onAddField,
  onApplySuggestion,
  onNewVisual,
}: {
  meta: VisualizadorMeta | null;
  detail: DatasetDetail | null;
  datasetId: string;
  onSelectDataset: (id: string) => void;
  filters: Record<string, unknown>;
  onFiltersChange: (filters: Record<string, unknown>) => void;
  search: string;
  onSearchChange: (value: string) => void;
  onAddField: (kind: "dimension" | "measure", id: string) => void;
  onApplySuggestion: (suggestion: VisualSuggestion) => void;
  onNewVisual: () => void;
}) {
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [fieldQuery, setFieldQuery] = useState("");

  const domains = meta?.domains ?? [];
  const datasets = meta?.datasets ?? [];
  const dataset = detail?.dataset ?? null;

  const needle = fieldQuery.trim().toLowerCase();
  const visibleDimensions = (detail?.dimensions ?? []).filter(
    (dimension) => !needle || dimension.label.toLowerCase().includes(needle) || dimension.id.toLowerCase().includes(needle));
  const visibleMeasures = (detail?.measures ?? []).filter((measure) => {
    if (!needle) return true;
    return (measure.label || measure.id).toLowerCase().includes(needle) || measure.id.toLowerCase().includes(needle);
  });

  const filterFields = (detail?.filters ?? []).slice(0, showAllFilters ? 40 : 6);
  const activeFilters = Object.keys(filters).filter((key) => filters[key] !== undefined && filters[key] !== "");
  const filterLabels: Record<string, string> = {};
  for (const dimension of detail?.dimensions ?? []) filterLabels[dimension.id] = dimension.label;

  return (
    <aside className="space-y-4">
      <section className="glass-card gradient-border rounded-2xl p-4 space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
          <Database size={13} /> Dataset
        </h2>
        <select
          value={datasetId}
          onChange={(event) => onSelectDataset(event.target.value)}
          aria-label="Dataset"
          className="w-full px-2.5 py-2 rounded-xl glass-card text-sm"
        >
          {domains.map((domain) => (
            <optgroup key={domain.id} label={domain.label}>
              {domain.datasets.map((id) => {
                const item = datasets.find((entry) => entry.id === id);
                if (!item) return null;
                return (
                  <option key={id} value={id} disabled={!item.available}>
                    {item.label}{item.available ? "" : " (requer sessão)"}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>

        {dataset && (
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground">{dataset.description}</p>
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              <span className="px-2 py-0.5 rounded-full glass-card">{dataset.kind === "local" ? "fonte local" : dataset.index ?? dataset.kind}</span>
              <span className="px-2 py-0.5 rounded-full glass-card">{dataset.dimensions} dimensões</span>
              <span className="px-2 py-0.5 rounded-full glass-card">{dataset.measures} medidas</span>
              {dataset.requires_session && <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300">privado</span>}
            </div>
            {dataset.note && <p className="text-[11px] text-amber-300">{dataset.note}</p>}
            {(dataset.notes ?? []).slice(0, 1).map((note, index) => (
              <p key={index} className="text-[10px] text-muted-foreground">{note}</p>
            ))}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <button type="button" onClick={onNewVisual}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl glass-card text-xs hover:bg-white/5">
            <Plus size={12} /> Novo visual
          </button>
        </div>
      </section>

      {detail && (
        <section className="glass-card gradient-border rounded-2xl p-4 space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <Search size={13} /> Pesquisar no dataset
          </h2>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={dataset?.kind === "local" ? "filtrar registos…" : "texto livre (ex.: objeto do contrato)"}
            aria-label="Pesquisa no dataset"
            className="w-full px-2.5 py-2 rounded-xl glass-card text-sm"
          />
          <input
            value={fieldQuery}
            onChange={(event) => setFieldQuery(event.target.value)}
            placeholder="filtrar a lista de campos…"
            aria-label="Filtrar campos"
            className="w-full px-2.5 py-2 rounded-xl glass-card text-xs"
          />
        </section>
      )}

      {detail && (
        <section className="glass-card gradient-border rounded-2xl p-4 space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <ListFilter size={13} /> Filtros
          </h2>
          {activeFilters.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pb-1">
              {activeFilters.map((key) => (
                <button key={key} type="button"
                        onClick={() => {
                          const updated = { ...filters };
                          delete updated[key];
                          onFiltersChange(updated);
                        }}
                        className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/15 text-primary text-[10px]"
                        title="Remover filtro">
                  {filterLabels[key] ?? key} <X size={9} />
                </button>
              ))}
              <button type="button" onClick={() => onFiltersChange({})}
                      className="flex items-center gap-1 px-2 py-0.5 rounded-full glass-card text-[10px] text-muted-foreground hover:text-foreground">
                <RotateCcw size={9} /> Limpar
              </button>
            </div>
          )}
          <div className="space-y-2">
            {filterFields.map((dimension) => (
              <div key={dimension.id} className="space-y-1">
                <label className="text-[11px] text-muted-foreground">{dimension.label}</label>
                <FilterRow datasetId={datasetId} dimension={dimension} value={filters[dimension.id]}
                           filters={filters} onChange={onFiltersChange} />
              </div>
            ))}
          </div>
          {(detail.filters?.length ?? 0) > 6 && (
            <button type="button" onClick={() => setShowAllFilters((value) => !value)}
                    className="text-[11px] text-primary hover:underline">
              {showAllFilters ? "menos filtros" : `mais filtros (${detail.filters.length})`}
            </button>
          )}
        </section>
      )}

      {detail && detail.suggestions.length > 0 && (
        <section className="glass-card gradient-border rounded-2xl p-4 space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <Sparkles size={13} /> Sugestões
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {detail.suggestions.map((suggestion) => (
              <button key={suggestion.title} type="button" onClick={() => onApplySuggestion(suggestion)}
                      className="px-2.5 py-1 rounded-full glass-card text-[11px] hover:bg-white/5">
                {suggestion.title}
              </button>
            ))}
          </div>
        </section>
      )}

      {detail && (
        <section className="glass-card gradient-border rounded-2xl p-4 space-y-3">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <Tag size={13} /> Dimensões ({visibleDimensions.length})
            </h2>
            <p className="text-[10px] text-muted-foreground mt-1">Clique para acrescentar ao visual ativo.</p>
            <div className="flex flex-wrap gap-1.5 mt-2 max-h-40 overflow-y-auto">
              {visibleDimensions.map((dimension) => (
                <button key={dimension.id} type="button" onClick={() => onAddField("dimension", dimension.id)}
                        title={`${dimension.label} · ${dimension.type}${dimension.nested ? ` · ${dimension.nested}` : ""}`}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg glass-card text-[11px] hover:bg-white/5">
                  {dimensionIcon(dimension)} <span className="truncate max-w-[9rem]">{dimension.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <BarChart3 size={13} /> Medidas ({visibleMeasures.length})
            </h2>
            <div className="flex flex-wrap gap-1.5 mt-2 max-h-40 overflow-y-auto">
              {visibleMeasures.map((measure) => (
                <button key={measure.id} type="button" onClick={() => onAddField("measure", measure.id)}
                        title={`${measure.label} · ${measure.kind}`}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg glass-card text-[11px] hover:bg-white/5">
                  <span className="truncate max-w-[9rem]">{measure.label || measure.id}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      )}
    </aside>
  );
}
