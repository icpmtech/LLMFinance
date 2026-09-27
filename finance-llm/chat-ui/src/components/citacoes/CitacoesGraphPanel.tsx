/**
 * Secção «Grafo» do módulo das citações editais (CITIUS).
 *
 * Constrói grafos a partir do índice `finance_citacoes_edital`: nós são partes e
 * intervenientes (parte ativa, parte passiva, agentes de execução, credores,
 * NIF do documento), tribunais e comarcas, tipo/ato/espécie do processo,
 * modelos do documento analisado e períodos; as arestas ligam valores que
 * aparecem no mesmo édito (ou ligam duas dimensões, ex.: parte ativa → parte
 * passiva).
 *
 * Inclui uma **pesquisa** própria (texto livre, tipo, comarca, papel, NIF, datas
 * e «só com documento analisado»), receitas prontas, várias vistas (rede,
 * hierárquico, circular, fluxos, treemap e lista) e navegação: clicar num nó
 * mostra os vizinhos e abre os éditos correspondentes na Pesquisa.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Download,
  Focus,
  Gavel,
  Info,
  Link2,
  Loader2,
  RefreshCw,
  Search,
  Share2,
  Table2,
  X,
} from "lucide-react";
import {
  getCitacoesGraph,
  getCitacoesGraphDimensions,
  getCitacoesStatus,
  type CitacoesGraphDimensions,
  type CitacoesGraphParams,
  type CitacoesGraphResponse,
  type CitacoesSearchParams,
  type CitacoesStatus,
} from "../../citacoesApi";
import { GraphCanvas } from "../graph/GraphCanvas";
import { SankeyDiagram } from "../graph/SankeyDiagram";
import { TreemapChart } from "../graph/TreemapChart";
import { formatCompact, formatMoney, type StudioGraph } from "../graph/graphStudio";
import {
  CITACOES_COMPONENT_METRIC,
  CITACOES_METRIC_LABELS,
  citacoesEdgeSummary,
  citacoesGraphEdges,
  citacoesGraphNodes,
  citacoesGraphSummary,
  citacoesGraphToCsv,
  citacoesLegendEntries,
  citacoesNeighbours,
  citacoesNodeSearchParams,
  citacoesNodeSummary,
  citacoesTypeLabel,
  citacoesUnitLabel,
  downloadCitacoesFile,
  toCitacoesStudioGraph,
  type CitacoesGraphMetric,
  type CitacoesStudioNode,
} from "./citacoesGraph";

const numberFormat = new Intl.NumberFormat("pt-PT");

type View = "network" | "hierarchical" | "circular" | "sankey" | "treemap" | "list";

const VIEWS: { id: View; label: string }[] = [
  { id: "network", label: "Rede" },
  { id: "hierarchical", label: "Hierárquico" },
  { id: "circular", label: "Circular" },
  { id: "sankey", label: "Fluxos" },
  { id: "treemap", label: "Treemap" },
  { id: "list", label: "Lista" },
];

const PAPEIS = [
  "Exequente",
  "Executado",
  "Réu",
  "Requerente",
  "Requerido",
  "Credor",
  "Agente de Execução (Sol.)",
  "Autor",
];

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-white/10 bg-white/5 p-4 ${className}`}>{children}</div>;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold text-foreground">{value}</div>
      {hint ? <div className="text-[10px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

const inputClass =
  "mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-amber-400/40";

export default function CitacoesGraphPanel({
  onOpenSearch,
}: {
  /** Navegação: abre a pesquisa com os filtros do nó escolhido. */
  onOpenSearch: (params: CitacoesSearchParams) => void;
}) {
  const [dimensions, setDimensions] = useState<CitacoesGraphDimensions | null>(null);
  const [status, setStatus] = useState<CitacoesStatus | null>(null);
  const [response, setResponse] = useState<CitacoesGraphResponse | null>(null);
  const [graph, setGraph] = useState<StudioGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [layoutVersion, setLayoutVersion] = useState(0);

  // Critérios (pesquisa do grafo + dimensões).
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState("");
  const [comarca, setComarca] = useState("");
  const [papel, setPapel] = useState("");
  const [nif, setNif] = useState("");
  const [modelo, setModelo] = useState("");
  const [dataFrom, setDataFrom] = useState("");
  const [dataTo, setDataTo] = useState("");
  const [soComTexto, setSoComTexto] = useState(false);
  const [dimensionA, setDimensionA] = useState("parte_ativa");
  const [dimensionB, setDimensionB] = useState("parte_passiva");
  const [metric, setMetric] = useState<CitacoesGraphMetric>("editais");
  const [limit, setLimit] = useState(60);
  const [view, setView] = useState<View>("network");

  useEffect(() => {
    getCitacoesGraphDimensions()
      .then(setDimensions)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    getCitacoesStatus().then(setStatus).catch(() => undefined);
  }, []);

  const params: CitacoesGraphParams = useMemo(
    () => ({
      dimension_a: dimensionA,
      dimension_b: dimensionB || null,
      metric,
      q: q || undefined,
      tipo: tipo || undefined,
      comarca_judicial: comarca || undefined,
      papel: papel || undefined,
      nif: nif || undefined,
      modelo: modelo || undefined,
      data_from: dataFrom || undefined,
      data_to: dataTo || undefined,
      has_texto: soComTexto ? true : undefined,
      limit,
      edge_limit: 400,
    }),
    [comarca, dataFrom, dataTo, dimensionA, dimensionB, limit, metric, modelo, nif, papel, q, soComTexto, tipo],
  );

  const build = useCallback(
    async (next: CitacoesGraphParams) => {
      setLoading(true);
      setError(null);
      try {
        const payload = await getCitacoesGraph(next);
        setResponse(payload);
        setGraph(toCitacoesStudioGraph(payload, (next.metric ?? "editais") as CitacoesGraphMetric));
        setSelectedId(null);
        setLayoutVersion((value) => value + 1);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const refreshDimensions = useCallback(async () => {
    try {
      setDimensions(await getCitacoesGraphDimensions());
      await build(params);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [build, params]);

  // Constrói o primeiro grafo assim que as dimensões chegam (a secção não abre vazia).
  useEffect(() => {
    if (!dimensions) return;
    void build(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimensions]);

  const labelFor = (key: string) =>
    dimensions?.dimensions.find((item) => item.key === key)?.label ?? key;
  const shortFor = (key: string) => dimensions?.dimensions.find((item) => item.key === key)?.short ?? key;

  const applyRecipe = (id: string) => {
    const recipe = dimensions?.recipes.find((item) => item.id === id);
    if (!recipe) return;
    setDimensionA(recipe.dimension_a);
    setDimensionB(recipe.dimension_b ?? "");
    setMetric(recipe.metric);
    setView((recipe.view as View) ?? "network");
    setLimit(recipe.limit);
    void build({
      ...params,
      dimension_a: recipe.dimension_a,
      dimension_b: recipe.dimension_b,
      metric: recipe.metric,
      limit: recipe.limit,
    });
  };

  const nodes = citacoesGraphNodes(graph);
  const edges = citacoesGraphEdges(graph);
  const meta = response?.meta ?? null;
  const summary = citacoesGraphSummary(graph);
  const legend = citacoesLegendEntries(nodes);
  const selected = nodes.find((node) => node.id === selectedId) ?? null;
  const neighbours = useMemo(
    () => (selectedId ? citacoesNeighbours(graph, selectedId, metric) : []),
    [graph, metric, selectedId],
  );

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void build(params);
  };

  const clearFilters = () => {
    setQ("");
    setTipo("");
    setComarca("");
    setPapel("");
    setNif("");
    setModelo("");
    setDataFrom("");
    setDataTo("");
    setSoComTexto(false);
    void build({ ...params, q: undefined, tipo: undefined, comarca_judicial: undefined, papel: undefined, nif: undefined, modelo: undefined, data_from: undefined, data_to: undefined, has_texto: undefined });
  };

  return (
    <div className="space-y-4">
      {error ? (
        <Card className="flex items-start gap-2 border-amber-400/25 bg-amber-400/5 text-[11.5px] text-amber-200">
          <AlertTriangle size={14} />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} className="opacity-70 hover:opacity-100">
            ×
          </button>
        </Card>
      ) : null}

      {/* Pesquisa e critérios */}
      <Card className="space-y-3">
        <form className="flex flex-wrap items-end gap-3" onSubmit={onSubmit}>
          <div className="min-w-[240px] flex-1">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
              Pesquisar nos éditos
            </label>
            <div className="relative">
              <Search size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="interveniente, processo, tribunal, texto do PDF…"
                autoComplete="off"
                className={`${inputClass} pl-7`}
              />
            </div>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Tipo</label>
            <select value={tipo} onChange={(event) => setTipo(event.target.value)} className={inputClass}>
              <option value="">Todos</option>
              <option value="Citação">Citação</option>
              <option value="Notificação">Notificação</option>
              <option value="Anúncio">Anúncio</option>
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Papel</label>
            <select value={papel} onChange={(event) => setPapel(event.target.value)} className={inputClass}>
              <option value="">Todos</option>
              {PAPEIS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="w-[150px]">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Comarca</label>
            <input
              value={comarca}
              onChange={(event) => setComarca(event.target.value)}
              placeholder="ex.: Santarém"
              autoComplete="off"
              className={inputClass}
            />
          </div>
          <div className="w-[130px]">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">NIF</label>
            <input
              value={nif}
              onChange={(event) => setNif(event.target.value)}
              placeholder="do documento"
              autoComplete="off"
              className={inputClass}
            />
          </div>
          <div className="w-[140px]">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Modelo</label>
            <input
              value={modelo}
              onChange={(event) => setModelo(event.target.value)}
              placeholder="ex.: 547/0.05"
              autoComplete="off"
              className={inputClass}
            />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">De</label>
            <input type="date" value={dataFrom} onChange={(event) => setDataFrom(event.target.value)} className={inputClass} />
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Até</label>
            <input type="date" value={dataTo} onChange={(event) => setDataTo(event.target.value)} className={inputClass} />
          </div>
          <label className="flex items-center gap-1.5 pb-2 text-[11px] text-muted-foreground">
            <input type="checkbox" checked={soComTexto} onChange={(event) => setSoComTexto(event.target.checked)} />
            só com PDF analisado
          </label>
          <button
            type="submit"
            className="mb-0.5 inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-[11.5px] text-amber-100 hover:bg-amber-500/30"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />} Construir grafo
          </button>
          <button
            type="button"
            onClick={clearFilters}
            className="mb-0.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
          >
            Limpar
          </button>
        </form>

        <div className="flex flex-wrap items-end gap-3 border-t border-white/10 pt-3">
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Receitas</label>
            <select
              value=""
              onChange={(event) => applyRecipe(event.target.value)}
              className={inputClass}
              title="Grafos prontos para perguntas frequentes"
            >
              <option value="">Escolher uma receita…</option>
              {(dimensions?.recipes ?? []).map((recipe) => (
                <option key={recipe.id} value={recipe.id}>
                  {recipe.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Dimensão A (nós)</label>
            <select value={dimensionA} onChange={(event) => setDimensionA(event.target.value)} className={inputClass}>
              {(dimensions?.dimensions ?? []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Dimensão B (arestas)</label>
            <select value={dimensionB} onChange={(event) => setDimensionB(event.target.value)} className={inputClass}>
              <option value="">— sem arestas —</option>
              {(dimensions?.dimensions ?? []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Métrica</label>
            <select
              value={metric}
              onChange={(event) => setMetric(event.target.value as CitacoesGraphMetric)}
              className={inputClass}
            >
              <option value="editais">{CITACOES_METRIC_LABELS.editais}</option>
              <option value="mencoes">{CITACOES_METRIC_LABELS.mencoes}</option>
            </select>
          </div>
          <div className="w-[110px]">
            <label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Nós</label>
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))} className={inputClass}>
              {[20, 40, 60, 100, 200].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={() => void refreshDimensions()}
            disabled={loading}
            className="mb-0.5 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Atualizar
          </button>
          <div className="mb-0.5 ml-auto flex items-center gap-2">
            <select
              value={view}
              onChange={(event) => setView(event.target.value as View)}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-[11.5px] text-foreground outline-none focus:border-amber-400/40"
            >
              {VIEWS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setLayoutVersion((value) => value + 1)}
              title="Reorganizar o grafo"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <Focus size={12} /> Reorganizar
            </button>
            <button
              type="button"
              disabled={!graph}
              onClick={() => graph && downloadCitacoesFile("citacoes-grafo.csv", citacoesGraphToCsv(graph), "text/csv")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-40"
            >
              <Download size={12} /> CSV
            </button>
          </div>
        </div>

        {dimensions ? (
          <p className="text-[10.5px] text-muted-foreground">
            {dimensions.recipes.length} receitas · {dimensions.dimensions.length} dimensões ·{" "}
            {numberFormat.format(status?.documents ?? 0)} éditos no índice ·{" "}
            {numberFormat.format(status?.with_texto ?? 0)} com documento analisado
          </p>
        ) : null}
      </Card>

      {/* Resumo */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Nós" value={numberFormat.format(summary.nodes)} hint={`${summary.edges} arestas`} />
        <Stat label="Éditos analisados" value={numberFormat.format(meta?.documents_scanned ?? 0)} hint={`de ${numberFormat.format(meta?.documents_matching ?? 0)}`} />
        <Stat label="Com PDF analisado" value={numberFormat.format(meta?.documents_with_text ?? 0)} />
        <Stat label="Valor em jogo" value={formatMoney(meta?.documents_value ?? 0)} hint="valor das execuções" />
        <Stat
          label={metric === "mencoes" ? "Menções (topo)" : "Éditos (topo)"}
          value={numberFormat.format(nodes.reduce((acc, node) => Math.max(acc, node.value), 0))}
          hint={`por ${shortFor(dimensionA).toLowerCase()}`}
        />
      </div>

      {/* Visualização */}
      <Card className="relative !p-0">
        {loading ? (
          <div className="flex h-[560px] items-center justify-center gap-2 text-[12px] text-muted-foreground">
            <Loader2 size={14} className="animate-spin" /> a construir o grafo…
          </div>
        ) : view === "sankey" ? (
          !dimensionB ? (
            <p className="p-6 text-center text-[12px] text-muted-foreground">
              Os fluxos precisam de duas dimensões (escolha uma dimensão B, ex.: papel → tribunal).
            </p>
          ) : (
            <SankeyDiagram
              nodes={nodes}
              edges={edges}
              metric={CITACOES_COMPONENT_METRIC}
              height={560}
              unitLabel={citacoesUnitLabel(metric)}
              onNodeClick={(node) => setSelectedId(node.id)}
            />
          )
        ) : view === "treemap" ? (
          <TreemapChart
            nodes={nodes.filter((node) => !dimensionB || node.dimension === dimensionA)}
            metric={CITACOES_COMPONENT_METRIC}
            height={560}
            unitLabel={citacoesUnitLabel(metric)}
            areaHint={`área = ${citacoesUnitLabel(metric)} por ${shortFor(dimensionA).toLowerCase()}`}
            onNodeClick={(node) => setSelectedId(node.id)}
          />
        ) : view === "list" ? (
          <NodeTable graph={graph} labelFor={labelFor} onSelect={setSelectedId} onOpenSearch={onOpenSearch} />
        ) : (
          <GraphCanvas
            graph={graph}
            layout={view === "hierarchical" ? "hierarchical" : view === "circular" ? "circular" : "network"}
            metric={CITACOES_COMPONENT_METRIC}
            selectedNodeId={selectedId}
            loading={loading}
            layoutVersion={layoutVersion}
            unitLabel={citacoesUnitLabel(metric)}
            nodeSummary={citacoesNodeSummary}
            edgeSummary={citacoesEdgeSummary}
            heightClass="h-[560px]"
            onNodeClick={(node) => setSelectedId(node.id)}
          />
        )}

        {legend.length > 1 ? (
          <div className="absolute left-3 top-3 z-10 flex flex-wrap gap-2 rounded-xl border border-white/10 bg-[#07151b]/85 px-2 py-1.5">
            {legend.map((item) => (
              <span key={item.key} className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
                {item.label}
              </span>
            ))}
          </div>
        ) : null}
      </Card>

      {meta ? (
        <Card className="space-y-1.5">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Info size={13} /> Como ler este grafo
          </div>
          <p className="text-[11.5px] text-muted-foreground">
            Nós = {labelFor(meta.dimension_a).toLowerCase()}
            {meta.dimension_b ? ` × ${labelFor(meta.dimension_b).toLowerCase()}` : ""} · métrica ={" "}
            {metric === "mencoes" ? "menções a intervenientes" : "éditos distintos"} · tamanho/espessura pela métrica,
            valor em euros nos detalhes.
          </p>
          {meta.directed ? (
            <p className="text-[11px] text-sky-300">
              Arestas dirigidas: {shortFor(meta.dimension_a)} → {shortFor(meta.dimension_b ?? "")}.
            </p>
          ) : null}
          {(meta.notes ?? []).map((note, index) => (
            <p key={index} className="text-[11px] text-amber-200/90">
              • {note}
            </p>
          ))}
        </Card>
      ) : null}

      {selected ? (
        <Card className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: selected.color }} />
                <span className="break-words text-sm font-semibold text-foreground">{selected.label}</span>
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {citacoesTypeLabel(selected.type)} · {labelFor(selected.dimension)}
                {selected.nif ? ` · NIF ${selected.nif}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onOpenSearch(citacoesNodeSearchParams(selected))}
                className="flex items-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-400/15 px-2.5 py-1.5 text-[11px] text-amber-100 hover:bg-amber-400/25"
              >
                <Search size={12} /> Ver éditos
              </button>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="rounded-lg border border-white/10 bg-white/5 p-1.5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                aria-label="Fechar detalhe"
              >
                <X size={12} />
              </button>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            <Stat label="Éditos" value={numberFormat.format(selected.editais)} />
            <Stat label="Menções" value={numberFormat.format(selected.mencoes)} />
            <Stat label="Valor" value={formatMoney(selected.valor)} hint="execuções nos éditos em que aparece" />
          </div>

          {selected.keys && selected.keys.length ? (
            <p className="text-[11px] text-muted-foreground">
              Papéis: <span className="text-foreground">{selected.keys.join(", ")}</span>
            </p>
          ) : null}

          {neighbours.length ? (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Link2 size={12} /> Ligados a
              </div>
              {neighbours.map((item) => (
                <button
                  key={`${item.edge.source}-${item.edge.target}-${item.node?.id}`}
                  type="button"
                  onClick={() => setSelectedId(item.node?.id ?? null)}
                  className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-left text-[11px] hover:bg-white/10"
                >
                  <span className="truncate text-foreground">
                    {item.node?.label}
                    <span className="ml-2 text-muted-foreground">{labelFor(item.node?.dimension ?? "")}</span>
                  </span>
                  <span className="shrink-0 text-muted-foreground">
                    {numberFormat.format(item.edge.count)} éditos
                    {item.edge.mentions && item.edge.mentions !== item.edge.count
                      ? ` · ${numberFormat.format(item.edge.mentions)} menções`
                      : ""}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------- lista */

function NodeTable({
  graph,
  labelFor,
  onSelect,
  onOpenSearch,
}: {
  graph: StudioGraph | null;
  labelFor: (key: string) => string;
  onSelect: (id: string) => void;
  onOpenSearch: (params: CitacoesSearchParams) => void;
}) {
  const nodes = [...citacoesGraphNodes(graph)].sort((a, b) => b.value - a.value);
  const edges = [...citacoesGraphEdges(graph)].sort((a, b) => b.count - a.count);
  const labelOf = (id: string) => nodes.find((node) => node.id === id)?.label ?? id;

  if (!nodes.length) {
    return (
      <p className="p-6 text-center text-[12px] text-muted-foreground">
        Sem nós: ajuste os filtros ou recolha éditos na secção «Recolha».
      </p>
    );
  }

  return (
    <div className="max-h-[560px] space-y-4 overflow-y-auto p-3">
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Table2 size={12} /> Nós ({numberFormat.format(nodes.length)})
        </div>
        <table className="w-full text-left text-[11px]">
          <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="py-1">Valor</th>
              <th className="py-1">Dimensão</th>
              <th className="py-1 text-right">Éditos</th>
              <th className="py-1 text-right">Menções</th>
              <th className="py-1 text-right">Valor (€)</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {nodes.slice(0, 200).map((node) => (
              <tr key={node.id} className="border-t border-white/5">
                <td className="py-1 pr-2">
                  <button type="button" onClick={() => onSelect(node.id)} className="flex items-center gap-1.5 text-left hover:underline">
                    <span className="h-2 w-2 rounded-full" style={{ background: node.color }} />
                    <span className="text-foreground">{node.label}</span>
                  </button>
                </td>
                <td className="py-1 pr-2 text-muted-foreground">{labelFor(node.dimension)}</td>
                <td className="py-1 text-right text-foreground">{numberFormat.format(node.editais)}</td>
                <td className="py-1 text-right text-muted-foreground">{numberFormat.format(node.mencoes)}</td>
                <td className="py-1 text-right text-muted-foreground">
                  {node.valor ? formatMoney(node.valor) : "—"}
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onOpenSearch(citacoesNodeSearchParams(node))}
                    className="rounded-lg border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
                  >
                    éditos
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {edges.length ? (
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Share2 size={12} /> Ligações ({numberFormat.format(edges.length)})
          </div>
          <table className="w-full text-left text-[11px]">
            <tbody>
              {edges.slice(0, 200).map((edge) => (
                <tr key={`${edge.source}-${edge.target}`} className="border-t border-white/5">
                  <td className="py-1 pr-2 text-foreground">{labelOf(edge.source)}</td>
                  <td className="py-1 pr-2 text-muted-foreground">↔</td>
                  <td className="py-1 pr-2 text-foreground">{labelOf(edge.target)}</td>
                  <td className="py-1 text-right text-muted-foreground">{formatCompact(edge.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <p className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
        <Gavel size={12} /> O valor em euros vem da análise dos PDF dos éditos (valor da execução).
      </p>
    </div>
  );
}

export type { CitacoesStudioNode };
