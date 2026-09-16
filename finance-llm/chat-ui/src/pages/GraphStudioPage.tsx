/**
 * Estúdio de Grafos — cria grafos e visualizações a partir dos dados dos contratos
 * (entidades, CPV, território, procedimentos, tempo) e dos valores.
 *
 * Combina um construtor por dimensões (backend `/contracts/analytics/graph`) com
 * quatro visualizações: rede, hierárquica/circular, Sankey (fluxos) e treemap.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  Circle,
  Download,
  FileText,
  GitBranch,
  Info,
  Layers,
  List,
  Loader2,
  Network,
  RefreshCw,
  Route,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { buildContractGraph, getContractRegionalAnalytics, getContractYears, searchContracts } from "../api";
import type {
  ContractGraphBuildResponse,
  ContractItem,
  ContractRegionalRow,
  GraphDimensionOption,
} from "../types";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { SankeyDiagram } from "../components/graph/SankeyDiagram";
import { TreemapChart } from "../components/graph/TreemapChart";
import {
  METRIC_LABELS,
  RECIPES,
  downloadFile,
  edgeWeight,
  formatCompact,
  formatMoney,
  graphSummary,
  graphToCsv,
  legendEntries,
  metricLabel,
  nodeContractQuery,
  nodeValue,
  toStudioGraph,
  type GraphMetric,
  type Recipe,
  type StudioNode,
  type StudioView,
} from "../components/graph/graphStudio";

const VIEW_OPTIONS: { id: StudioView; label: string; icon: typeof Network }[] = [
  { id: "network", label: "Rede", icon: Network },
  { id: "hierarchical", label: "Hierárquica", icon: GitBranch },
  { id: "circular", label: "Circular", icon: Circle },
  { id: "sankey", label: "Fluxos", icon: Route },
  { id: "treemap", label: "Treemap", icon: Layers },
  { id: "list", label: "Lista", icon: List },
];

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold text-foreground">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  id,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  id: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground" htmlFor={id}>
      {label}
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-[#07151b]">
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function GraphStudioPage() {
  const [dimensions, setDimensions] = useState<GraphDimensionOption[]>([]);
  const [recipeId, setRecipeId] = useState<string>(RECIPES[0].id);
  const [dimensionA, setDimensionA] = useState<string>(RECIPES[0].dimensionA);
  const [dimensionB, setDimensionB] = useState<string>(RECIPES[0].dimensionB ?? "");
  const [metric, setMetric] = useState<GraphMetric>(RECIPES[0].metric);
  const [view, setView] = useState<StudioView>(RECIPES[0].view);
  const [year, setYear] = useState<string>("");
  const [region, setRegion] = useState<string>("");
  const [minValue, setMinValue] = useState<string>("");
  const [limit, setLimit] = useState<number>(RECIPES[0].limit);
  const [edgeLimit, setEdgeLimit] = useState<number>(400);
  const [sample, setSample] = useState<number>(3000);
  const [mode, setMode] = useState<"auto" | "exato" | "amostra">("auto");
  const [sampleOrder, setSampleOrder] = useState<"valor" | "recentes">("valor");
  const [showFilters, setShowFilters] = useState(true);

  const [years, setYears] = useState<number[]>([]);
  const [regions, setRegions] = useState<ContractRegionalRow[]>([]);
  const [data, setData] = useState<ContractGraphBuildResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StudioNode | null>(null);
  const [selectedContracts, setSelectedContracts] = useState<ContractItem[] | null>(null);
  const [layoutVersion, setLayoutVersion] = useState(0);

  useEffect(() => {
    Promise.all([getContractYears(), getContractRegionalAnalytics()])
      .then(([yearResponse, regionalResponse]) => {
        setYears(yearResponse.available ?? []);
        setRegions(regionalResponse.regions ?? []);
      })
      .catch(() => undefined);
    getContractGraphDimensionsFallback()
      .then(setDimensions)
      .catch(() => undefined);
  }, []);

  const graph = useMemo(() => toStudioGraph(data, metric), [data, metric]);
  const summary = useMemo(() => graphSummary(graph, metric), [graph, metric]);

  const requestParams = useMemo(
    () => ({
      dimension_a: dimensionA,
      dimension_b: dimensionB || null,
      metric,
      mode,
      year: year ? Number(year) : undefined,
      region: region || undefined,
      min_value: minValue ? Number(minValue) : undefined,
      limit,
      edge_limit: edgeLimit,
      sample,
      sample_order: sampleOrder,
    }),
    [dimensionA, dimensionB, edgeLimit, limit, metric, minValue, mode, region, sample, sampleOrder, year],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      buildContractGraph(requestParams)
        .then((response) => {
          if (cancelled) return;
          if (response.error) {
            setError(response.error);
            setData(null);
            return;
          }
          setData(response);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : "Erro ao construir o grafo");
          setData(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [requestParams]);

  // Ao mudar o grafo, limpa a seleção anterior.
  useEffect(() => {
    setSelected(null);
    setSelectedContracts(null);
  }, [requestParams]);

  useEffect(() => {
    if (!selected) {
      setSelectedContracts(null);
      return;
    }
    const query = nodeContractQuery(selected);
    if (!query) {
      setSelectedContracts([]);
      return;
    }
    let cancelled = false;
    setSelectedContracts(null);
    searchContracts({ ...query, size: 8, sort_by: "precoContratual", sort_order: "desc" })
      .then((response) => {
        if (!cancelled) setSelectedContracts(response.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setSelectedContracts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const applyRecipe = useCallback((recipe: Recipe) => {
    setRecipeId(recipe.id);
    setDimensionA(recipe.dimensionA);
    setDimensionB(recipe.dimensionB ?? "");
    setMetric(recipe.metric);
    setView(recipe.view);
    setLimit(recipe.limit);
  }, []);

  const handleNodeClick = useCallback((node: StudioNode) => {
    setSelected((current) => (current?.id === node.id ? null : node));
  }, []);

  const handleEdgeClick = useCallback(() => {
    setSelected(null);
  }, []);

  const dimensionOptions = useMemo(
    () =>
      (dimensions.length > 0
        ? dimensions
        : [
            { key: "adjudicante", label: "Entidade adjudicante", type: "entidade" },
            { key: "adjudicatario", label: "Entidade adjudicatária", type: "entidade" },
            { key: "cpv_classe", label: "CPV — classe (4 dígitos)", type: "cpv" },
            { key: "regiao", label: "Região (NUTS)", type: "regiao" },
          ]
      ).map((dimension) => ({ value: dimension.key, label: dimension.label })),
    [dimensions],
  );

  const metricName = METRIC_LABELS[metric];
  const coverage = data?.meta?.coverage_value_share;
  const exactMode = data?.meta?.mode === "exato";
  const twoSided = Boolean(dimensionB) && dimensionB !== dimensionA;
  const legend = useMemo(() => (graph ? legendEntries(graph.nodes) : []), [graph]);
  const sankeyAvailable = Boolean(dimensionB) && Boolean(graph && graph.edges.length > 0);

  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-bold">Grafos &amp; Visualizações</h2>
          <p className="text-sm text-muted-foreground">
            Construa grafos a partir dos contratos públicos: entidades, classificação CPV, território,
            procedimentos, tempo — com métrica de contratos ou de valor.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setLayoutVersion((version) => version + 1)}
            className="glass-card flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          >
            <RefreshCw size={14} /> Recalcular layout
          </button>
          <button
            type="button"
            disabled={!graph}
            onClick={() => graph && downloadFile(`grafo-${dimensionA}-${dimensionB || "nos"}.csv`, graphToCsv(graph, metric), "text/csv")}
            className="glass-card flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 disabled:opacity-40"
          >
            <Download size={14} /> CSV
          </button>
          <button
            type="button"
            disabled={!data}
            onClick={() =>
              data &&
              downloadFile(
                `grafo-${dimensionA}-${dimensionB || "nos"}.json`,
                JSON.stringify(data, null, 2),
                "application/json",
              )
            }
            className="glass-card flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 disabled:opacity-40"
          >
            <Download size={14} /> JSON
          </button>
        </div>
      </header>

      {/* Receitas prontas */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {RECIPES.map((recipe) => {
          const active = recipe.id === recipeId;
          return (
            <button
              key={recipe.id}
              type="button"
              onClick={() => applyRecipe(recipe)}
              aria-pressed={active}
              title={recipe.description}
              className={[
                "shrink-0 rounded-xl border px-3 py-2 text-left text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
                active
                  ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                  : "glass-card border-white/10 text-muted-foreground hover:bg-white/5",
              ].join(" ")}
            >
              <span className="block font-medium">{recipe.label}</span>
              <span className="mt-0.5 block max-w-[190px] text-[10px] leading-4 opacity-80">{recipe.description}</span>
            </button>
          );
        })}
      </div>

      {/* Construtor */}
      <section className="glass-card gradient-border rounded-2xl p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <SlidersHorizontal size={15} className="text-teal-300" /> Construtor
          </h3>
          <button
            type="button"
            onClick={() => setShowFilters((open) => !open)}
            aria-expanded={showFilters}
            className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          >
            {showFilters ? "Ocultar" : "Mostrar"}
          </button>
        </div>

        {showFilters && (
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <Select
              id="studio-dimension-a"
              label="Nós (dimensão A)"
              value={dimensionA}
              onChange={(value) => {
                setDimensionA(value);
                setRecipeId("custom");
              }}
              options={dimensionOptions}
            />
            <Select
              id="studio-dimension-b"
              label="Arestas (dimensão B)"
              value={dimensionB}
              onChange={(value) => {
                setDimensionB(value);
                setRecipeId("custom");
              }}
              options={[{ value: "", label: "— sem arestas (nós) —" }, ...dimensionOptions]}
            />
            <Select
              id="studio-metric"
              label="Métrica"
              value={metric}
              onChange={(value) => setMetric(value as GraphMetric)}
              options={[
                { value: "valor", label: "Valor contratado" },
                { value: "contratos", label: "Nº de contratos" },
              ]}
            />
            <Select
              id="studio-year"
              label="Ano"
              value={year}
              onChange={setYear}
              options={[{ value: "", label: "Todos os anos" }, ...years.map((value) => ({ value: String(value), label: String(value) }))]}
            />
            <Select
              id="studio-region"
              label="Região"
              value={region}
              onChange={setRegion}
              options={[
                { value: "", label: "Todas as regiões" },
                ...regions.map((row) => ({ value: row.key, label: `${row.key} (${formatCompact(row.count)})` })),
              ]}
            />
            <Select
              id="studio-mode"
              label="Cobertura"
              value={mode}
              onChange={(value) => setMode(value as "auto" | "exato" | "amostra")}
              options={[
                { value: "auto", label: "Automático (exato sempre que possível)" },
                { value: "exato", label: "Exato — todos os contratos" },
                { value: "amostra", label: "Amostra rápida" },
              ]}
            />
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground" htmlFor="studio-min-value">
              Valor mínimo (€)
              <input
                id="studio-min-value"
                type="number"
                min={0}
                step={50000}
                value={minValue}
                onChange={(event) => setMinValue(event.target.value)}
                placeholder="0"
                className="rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              />
            </label>
            <Select
              id="studio-order"
              label="Ordem da amostra"
              value={sampleOrder}
              onChange={(value) => setSampleOrder(value as "valor" | "recentes")}
              options={[
                { value: "valor", label: "Maior valor" },
                { value: "recentes", label: "Mais recentes" },
              ]}
            />
            <Select
              id="studio-limit"
              label="Nº de nós"
              value={String(limit)}
              onChange={(value) => setLimit(Number(value))}
              options={[
                { value: "25", label: "25" },
                { value: "50", label: "50" },
                { value: "100", label: "100" },
                { value: "200", label: "200" },
                { value: "500", label: "500" },
                { value: "1000", label: "1 000" },
                { value: "0", label: "Todos" },
              ]}
            />
            <Select
              id="studio-edge-limit"
              label="Nº de arestas"
              value={String(edgeLimit)}
              onChange={(value) => setEdgeLimit(Number(value))}
              options={[
                { value: "200", label: "200" },
                { value: "400", label: "400" },
                { value: "2000", label: "2 000" },
                { value: "10000", label: "10 000" },
                { value: "0", label: "Todas" },
              ]}
            />
            <Select
              id="studio-sample"
              label="Contratos analisados (amostra)"
              value={String(sample)}
              onChange={(value) => setSample(Number(value))}
              options={[
                { value: "1000", label: "1 000" },
                { value: "3000", label: "3 000" },
                { value: "10000", label: "10 000" },
                { value: "50000", label: "50 000" },
                { value: "0", label: "Todos (varredura completa)" },
              ]}
            />
            <div className="col-span-2 flex items-end gap-2 md:col-span-4 xl:col-span-2">
              <Select
                id="studio-view"
                label="Visualização"
                value={view}
                onChange={(value) => setView(value as StudioView)}
                options={VIEW_OPTIONS.map((option) => ({ value: option.id, label: option.label }))}
              />
            </div>
          </div>
        )}
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {/* Indicadores */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi
          label={exactMode ? "Contratos (exato)" : "Contratos analisados"}
          value={exactMode ? formatCompact(data?.meta?.documents_matching ?? 0) : formatCompact(data?.meta?.documents_scanned ?? 0)}
          hint={
            exactMode
              ? "100% dos contratos do filtro"
              : `de ${formatCompact(data?.meta?.documents_matching ?? 0)} com estes filtros`
          }
        />
        <Kpi label="Nós / Arestas" value={`${summary.nodes} / ${summary.edges}`} hint={`${metricName}`} />
        <Kpi
          label={metric === "valor" ? "Valor representado" : "Contratos representados"}
          value={metric === "valor" ? formatMoney(summary.total) : formatCompact(summary.total)}
          hint={
            twoSided
              ? "soma do lado A (sem duplicar)"
              : coverage != null
              ? `Cobertura do lado A: ${(coverage * 100).toFixed(0)}%`
              : undefined
          }
        />
        <Kpi
          label="Valor analisado"
          value={formatMoney(data?.meta?.scanned_value ?? 0)}
          hint={data?.meta?.omitted_edges ? `${data.meta.omitted_edges} arestas omitidas` : "sem omissões"}
        />
      </div>

      {data?.meta?.notes && data.meta.notes.length > 0 && (
        <div
          className={[
            "flex flex-wrap items-start gap-2 rounded-xl border px-3 py-2 text-[11px]",
            data.meta.complete
              ? "border-emerald-300/25 bg-emerald-300/5 text-emerald-100"
              : data.meta.scan_capped
              ? "border-rose-300/30 bg-rose-300/5 text-rose-100"
              : "border-amber-300/25 bg-amber-300/5 text-amber-100",
          ].join(" ")}
        >
          <Info size={13} className="mt-0.5 shrink-0" />
          <span>
            <strong className="font-semibold">
              {data.meta.complete
                ? "Dados completos"
                : data.meta.scan_capped
                ? "Limite do servidor atingido"
                : "Amostra parcial"}
            </strong>
            {" — "}
            {data.meta.notes.join(" ")}
          </span>
          {data.meta.limits && (
            <span className="text-[10px] opacity-80">
              Tetos: {formatCompact(data.meta.limits.max_scan)} contratos · {formatCompact(data.meta.limits.max_nodes)} nós ·{" "}
              {formatCompact(data.meta.limits.max_edges)} arestas
            </span>
          )}
        </div>
      )}

      {(summary.nodes > 800 || summary.edges > 4000) && (
        <div className="flex items-center gap-2 rounded-xl border border-teal-300/20 bg-teal-300/5 px-3 py-2 text-[11px] text-teal-100">
          <Layers size={13} />
          Grafo grande ({formatCompact(summary.nodes)} nós · {formatCompact(summary.edges)} arestas): as vistas
          <strong className="px-1">Treemap</strong>, <strong className="px-1">Fluxos</strong> e{" "}
          <strong className="px-1">Lista</strong> são mais legíveis; na vista de rede reduza os nós ou use filtros.
        </div>
      )}

      {sample === 0 && !exactMode && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-300/25 bg-amber-300/5 px-3 py-2 text-[11px] text-amber-100">
          <Info size={13} />
          Varredura completa: em conjuntos grandes pode demorar dezenas de segundos (a rede de concorrência não
          aceita agregações). Aplique filtros de ano, região ou valor mínimo para acelerar.
        </div>
      )}

      {/* Visualizações */}
      <div className="flex flex-col gap-4 xl:flex-row">
        <section className="glass-card min-w-0 flex-1 overflow-hidden p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              {VIEW_OPTIONS.map((option) => {
                const disabled =
                  (option.id === "sankey" && !sankeyAvailable) ||
                  (option.id === "treemap" && !graph) ||
                  (option.id !== "treemap" && option.id !== "list" && !graph);
                const Icon = option.icon;
                return (
                  <button
                    key={option.id}
                    type="button"
                    disabled={disabled}
                    aria-pressed={view === option.id}
                    onClick={() => setView(option.id)}
                    title={
                      disabled && option.id === "sankey"
                        ? "Escolha uma dimensão B (arestas) para ver fluxos"
                        : `Vista ${option.label}`
                    }
                    className={[
                      "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
                      view === option.id
                        ? "border-teal-400/30 bg-teal-400/15 text-teal-300"
                        : "border-white/10 hover:bg-white/5",
                      disabled ? "cursor-not-allowed opacity-40" : "",
                    ].join(" ")}
                  >
                    <Icon size={14} />
                    {option.label}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              {legend.map((entry) => (
                <span key={entry.key} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: entry.color }} />
                  {entry.label}
                </span>
              ))}
            </div>
          </div>

          {view === "sankey" ? (
            sankeyAvailable && graph ? (
              <SankeyDiagram nodes={graph.nodes} edges={graph.edges} metric={metric} height={560} onNodeClick={handleNodeClick} />
            ) : (
              <div className="flex h-[460px] flex-col items-center justify-center rounded-xl bg-[#07151b] text-sm text-muted-foreground">
                <Route size={28} className="mb-2 opacity-40" />
                Escolha uma dimensão B para desenhar o fluxo.
              </div>
            )
          ) : view === "treemap" ? (
            <TreemapChart nodes={graph?.nodes ?? []} metric={metric} height={560} onNodeClick={handleNodeClick} />
          ) : view === "list" ? (
            <div className="max-h-[560px] overflow-auto rounded-xl border border-white/10">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-[#07151b] text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">Nó</th>
                    <th className="px-3 py-2">Dimensão</th>
                    <th className="px-3 py-2 text-right">Contratos</th>
                    <th className="px-3 py-2 text-right">Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.topNodes.map((node) => (
                    <tr
                      key={node.id}
                      className="cursor-pointer border-t border-white/5 hover:bg-white/5"
                      onClick={() => handleNodeClick(node)}
                    >
                      <td className="max-w-[280px] truncate px-3 py-2 text-foreground">{node.label}</td>
                      <td className="px-3 py-2 text-muted-foreground">{node.role ?? node.dimension}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{formatCompact(node.count)}</td>
                      <td className="px-3 py-2 text-right text-teal-300">{formatMoney(node.total_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {summary.topNodes.length === 0 && (
                <p className="py-10 text-center text-sm text-muted-foreground">Sem nós para apresentar.</p>
              )}
            </div>
          ) : (
            <GraphCanvas
              graph={graph}
              layout={view === "hierarchical" ? "hierarchical" : view === "circular" ? "circular" : "network"}
              metric={metric}
              loading={loading}
              layoutVersion={layoutVersion}
              selectedNodeId={selected?.id ?? null}
              onNodeClick={handleNodeClick}
              onEdgeClick={handleEdgeClick}
            />
          )}
        </section>

        {/* Painel lateral */}
        <aside className="w-full shrink-0 space-y-3 xl:w-[360px]">
          {selected ? (
            <div className="glass-card rounded-2xl p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">{selected.label}</p>
                  <p className="text-[11px] text-muted-foreground">{selected.role ?? selected.dimension}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground hover:bg-white/5"
                >
                  Limpar
                </button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5">
                  <p className="text-[10px] text-muted-foreground">Contratos analisados</p>
                  <p className="text-foreground">{formatCompact(selected.count)}</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5">
                  <p className="text-[10px] text-muted-foreground">Valor</p>
                  <p className="text-teal-300">{formatMoney(selected.total_value)}</p>
                </div>
              </div>

              <h4 className="mt-4 mb-2 flex items-center gap-1.5 text-xs font-semibold">
                <FileText size={13} className="text-teal-300" /> Contratos de maior valor
              </h4>
              {selectedContracts === null ? (
                <p className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
                  <Loader2 size={13} className="animate-spin" /> a carregar…
                </p>
              ) : selectedContracts.length === 0 ? (
                <p className="py-2 text-xs text-muted-foreground">Sem contratos para este filtro.</p>
              ) : (
                <ul className="space-y-1.5">
                  {selectedContracts.map((contract, index) => (
                    <li
                      key={contract.idcontrato ?? `${contract.objectoContrato}-${index}`}
                      className="rounded-lg border border-white/10 bg-white/[0.03] p-2"
                    >
                      <p className="line-clamp-2 text-[11px] text-foreground">
                        {contract.objectoContrato ?? contract.descContrato ?? "Contrato sem objeto"}
                      </p>
                      <p className="mt-1 flex justify-between gap-2 text-[10px] text-muted-foreground">
                        <span>{contract.Ano ?? "—"}</span>
                        <span className="text-teal-300">
                          {formatMoney(contract.precoContratual ?? contract.PrecoTotalEfetivo)}
                        </span>
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="glass-card rounded-2xl p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <BarChart3 size={15} className="text-teal-300" /> Maiores nós
              </h3>
              <ul className="space-y-1">
                {summary.topNodes.slice(0, 10).map((node) => (
                  <li key={node.id}>
                    <button
                      type="button"
                      onClick={() => handleNodeClick(node)}
                      className="w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                    >
                      <span className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: node.color }} />
                        <span className="truncate text-xs text-foreground">{node.label}</span>
                      </span>
                      <span className="mt-0.5 block pl-4 text-[10px] text-muted-foreground">
                        {metricLabel(metric, nodeValue(node, metric))} · {formatCompact(node.count)} contratos
                      </span>
                    </button>
                  </li>
                ))}
                {summary.topNodes.length === 0 && (
                  <li className="py-2 text-xs text-muted-foreground">Sem dados.</li>
                )}
              </ul>
            </div>
          )}

          <div className="glass-card rounded-2xl p-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Route size={15} className="text-teal-300" /> Ligações mais fortes
            </h3>
            <ul className="space-y-1.5">
              {summary.topEdges.slice(0, 8).map((edge) => (
                <li key={`${edge.source}-${edge.target}`} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
                  <p className="truncate text-[11px] text-teal-300">
                    {graph?.nodes.find((node) => node.id === edge.source)?.label ?? edge.source}
                  </p>
                  <p className="truncate text-[11px] text-blue-300">
                    → {graph?.nodes.find((node) => node.id === edge.target)?.label ?? edge.target}
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    {metricLabel(metric, edgeWeight(edge, metric))} · {formatCompact(edge.count)} contratos
                  </p>
                </li>
              ))}
              {summary.topEdges.length === 0 && (
                <li className="py-2 text-xs text-muted-foreground">
                  Este grafo não tem arestas (dimensão única).
                </li>
              )}
            </ul>
          </div>

          <div className="glass-card rounded-2xl p-4 text-[11px] text-muted-foreground">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
              <Search size={15} className="text-teal-300" /> Como explorar
            </h3>
            <p className="mb-1">• Clique num nó para ver os contratos de maior valor desse agrupamento.</p>
            <p className="mb-1">• Dimensões iguais (ex.: concorrente × concorrente) criam redes de co-ocorrência.</p>
            <p className="mb-1">• Sem dimensão B obtém só nós — ideal para treemap e rankings.</p>
            <p>
              • Todos os números vêm de contratos agregados (contagem e valor); mude a métrica sem recarregar os dados.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

/** Carrega as dimensões disponíveis, com fallback local se o endpoint falhar. */
async function getContractGraphDimensionsFallback(): Promise<GraphDimensionOption[]> {
  const { getGraphDimensions } = await import("../api");
  const response = await getGraphDimensions();
  return response.dimensions ?? [];
}
