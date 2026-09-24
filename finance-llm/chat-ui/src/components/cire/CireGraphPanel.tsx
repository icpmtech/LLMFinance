/**
 * Secção «Grafo» do módulo CIRE — rede de insolvências e revitalizações.
 *
 * Constrói grafos a partir do índice `finance_cire`: nós são entidades
 * (insolventes, administradores da insolvência, credores), tribunais, comarcas,
 * tipos/atos e períodos; as arestas ligam valores que aparecem na mesma
 * publicação (ou ligam duas dimensões diferentes, como administrador →
 * insolvente). Inclui receitas prontas, filtros (iguais aos da pesquisa) e
 * navegação: clicar num nó mostra os seus vizinhos e abre as publicações
 * correspondentes na pesquisa.
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
  getCireGraph,
  getCireGraphDimensions,
  getCireStatus,
  type CireGraphDimensions,
  type CireGraphParams,
  type CireGraphResponse,
  type CireFacet,
  type CireSearchParams,
  type CireStatus,
} from "../../cireApi";
import { GraphCanvas } from "../graph/GraphCanvas";
import { SankeyDiagram } from "../graph/SankeyDiagram";
import { TreemapChart } from "../graph/TreemapChart";
import {
  CIRE_COMPONENT_METRIC,
  cireEdgeSummary,
  cireGraphNodes,
  cireGraphToCsv,
  cireLegendEntries,
  cireNeighbours,
  cireNodeSearchParams,
  cireNodeSummary,
  cireTypeLabel,
  downloadCireFile,
  toCireStudioGraph,
  type CireGraphMetric,
  type CireStudioNode,
} from "./cireGraph";

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

/** Opções de amostragem (documentos analisados na varredura). */
const SAMPLES: { value: number; label: string }[] = [
  { value: 5000, label: "5 mil" },
  { value: 20000, label: "20 mil" },
  { value: 50000, label: "50 mil" },
  { value: 0, label: "Todas" },
];

const PAPEIS = ["Insolvente", "Administrador Insolvência", "Credor", "Requerente", "Devedor"];

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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-[11px] text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

const inputClass =
  "mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-[12px] text-foreground outline-none focus:border-emerald-400/40";

export default function CireGraphPanel({
  onOpenSearch,
}: {
  /** Navegação: abre a pesquisa do CIRE com os filtros do nó escolhido. */
  onOpenSearch: (params: CireSearchParams) => void;
}) {
  const [dimensions, setDimensions] = useState<CireGraphDimensions | null>(null);
  const [status, setStatus] = useState<CireStatus | null>(null);

  // dimensões e métrica
  const [dimensionA, setDimensionA] = useState("administrador");
  const [dimensionB, setDimensionB] = useState("insolvente");
  const [metric, setMetric] = useState<CireGraphMetric>("publicacoes");
  const [coverage, setCoverage] = useState<"auto" | "exato" | "amostra">("auto");
  const [sample, setSample] = useState(20000);
  const [limit, setLimit] = useState(60);
  const [edgeLimit, setEdgeLimit] = useState(400);
  const [minCount, setMinCount] = useState(1);

  // filtros (os mesmos da pesquisa)
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState("");
  const [comarca, setComarca] = useState("");
  const [especie, setEspecie] = useState("");
  const [papel, setPapel] = useState("");
  const [nif, setNif] = useState("");
  const [dataFrom, setDataFrom] = useState("");
  const [dataTo, setDataTo] = useState("");

  const [view, setView] = useState<View>("network");
  const [recipeId, setRecipeId] = useState("admin-insolvente");
  const [data, setData] = useState<CireGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    getCireGraphDimensions().then(setDimensions).catch(() => undefined);
    getCireStatus().then(setStatus).catch(() => undefined);
  }, []);

  const params = useMemo<CireGraphParams>(() => {
    const fullScan = coverage === "exato" || sample === 0;
    return {
      dimension_a: dimensionA,
      dimension_b: dimensionB || undefined,
      metric,
      mode: coverage,
      sample: fullScan ? 0 : sample,
      limit,
      edge_limit: edgeLimit,
      min_count: minCount,
      q: q || undefined,
      tipo: tipo || undefined,
      comarca: comarca || undefined,
      especie: especie || undefined,
      papel: papel || undefined,
      nif: nif || undefined,
      data_from: dataFrom || undefined,
      data_to: dataTo || undefined,
    };
  }, [
    comarca,
    coverage,
    dataFrom,
    dataTo,
    dimensionA,
    dimensionB,
    edgeLimit,
    especie,
    limit,
    metric,
    minCount,
    nif,
    papel,
    q,
    sample,
    tipo,
  ]);

  const run = useCallback(
    async (next: CireGraphParams = params) => {
      if (!next.dimension_a) return;
      setLoading(true);
      setError(null);
      try {
        const response = await getCireGraph(next);
        if (response.error) throw new Error(response.error);
        setData(response);
        setSelectedId(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [params],
  );

  // primeira carga (com a receita por omissão)
  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const graph = useMemo(() => toCireStudioGraph(data, metric), [data, metric]);
  const legend = useMemo(() => (graph ? cireLegendEntries(graph.nodes) : []), [graph]);
  const meta = data?.meta;

  /** Treemap/sankey funcionam melhor com um só lado do grafo. */
  const graphForArea = useMemo(() => {
    if (!graph) return null;
    const twoSided = Boolean(meta?.dimension_b) && meta?.dimension_b !== meta?.dimension_a;
    if (!twoSided) return graph;
    const keep = new Set(graph.nodes.filter((node) => node.dimension === meta?.dimension_a).map((node) => node.id));
    return { ...graph, nodes: graph.nodes.filter((node) => keep.has(node.id)), edges: [] };
  }, [graph, meta?.dimension_a, meta?.dimension_b]);

  const applyRecipe = useCallback(
    (id: string) => {
      const recipe = dimensions?.recipes.find((item) => item.id === id);
      if (!recipe) return;
      setRecipeId(id);
      setDimensionA(recipe.dimension_a);
      setDimensionB(recipe.dimension_b ?? "");
      setMetric(recipe.metric);
      setView(recipe.view as View);
      setLimit(recipe.limit);
      setSelectedId(null);
      void run({
        ...params,
        dimension_a: recipe.dimension_a,
        dimension_b: recipe.dimension_b ?? undefined,
        metric: recipe.metric,
        limit: recipe.limit,
        mode: coverage,
        sample: coverage === "exato" || sample === 0 ? 0 : sample,
      });
    },
    [coverage, dimensions?.recipes, params, run, sample],
  );

  const selected = useMemo(
    () => cireGraphNodes(graph).find((node) => node.id === selectedId) ?? null,
    [graph, selectedId],
  );
  const neighbours = useMemo(
    () => (selected ? cireNeighbours(graph, selected.id, metric) : []),
    [graph, metric, selected],
  );

  const dimensionOptions = dimensions?.dimensions ?? [];
  const labelFor = (key: string) => dimensionOptions.find((item) => item.key === key)?.label ?? key;
  const shortFor = (key: string) => dimensionOptions.find((item) => item.key === key)?.short ?? key;

  const facetSelect = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    facet?: CireFacet[],
  ) => (
    <Field label={label}>
      <select className={inputClass} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Todos</option>
        {(facet ?? []).slice(0, 60).map((item) => (
          <option key={item.key} value={item.key}>
            {item.key} ({numberFormat.format(item.count)})
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
      {/* ------------------------------------------------------------ filtros */}
      <aside className="space-y-3">
        <Card className="space-y-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Gavel size={13} /> Receitas
          </div>
          <div className="flex flex-wrap gap-1">
            {(dimensions?.recipes ?? []).map((recipe) => (
              <button
                key={recipe.id}
                type="button"
                onClick={() => applyRecipe(recipe.id)}
                title={recipe.description}
                className={`rounded-full border px-2 py-0.5 text-[10.5px] transition ${
                  recipeId === recipe.id
                    ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-200"
                    : "border-white/10 bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                }`}
              >
                {recipe.label}
              </button>
            ))}
          </div>
        </Card>

        <Card className="space-y-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Share2 size={13} /> Dimensões
          </div>
          <Field label="Nós (dimensão A)">
            <select className={inputClass} value={dimensionA} onChange={(event) => setDimensionA(event.target.value)}>
              {dimensionOptions.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Arestas (dimensão B) — «Nenhuma» devolve só nós">
            <select className={inputClass} value={dimensionB} onChange={(event) => setDimensionB(event.target.value)}>
              <option value="">Nenhuma</option>
              {dimensionOptions.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Métrica">
            <select
              className={inputClass}
              value={metric}
              onChange={(event) => setMetric(event.target.value as CireGraphMetric)}
            >
              <option value="publicacoes">Nº de publicações</option>
              <option value="mencoes">Menções a intervenientes</option>
            </select>
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Cobertura">
              <select
                className={inputClass}
                value={coverage}
                onChange={(event) => setCoverage(event.target.value as "auto" | "exato" | "amostra")}
              >
                <option value="auto">Auto</option>
                <option value="exato">Exata</option>
                <option value="amostra">Amostra</option>
              </select>
            </Field>
            <Field label="Amostra">
              <select
                className={inputClass}
                value={sample}
                disabled={coverage === "exato"}
                onChange={(event) => setSample(Number(event.target.value))}
              >
                {SAMPLES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Mín. publ.">
              <input
                type="number"
                min={1}
                max={1000}
                value={minCount}
                onChange={(event) => setMinCount(Math.max(1, Number(event.target.value) || 1))}
                className={inputClass}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Nº de nós (0 = todos)">
              <input
                type="number"
                min={0}
                value={limit}
                onChange={(event) => setLimit(Math.max(0, Number(event.target.value) || 0))}
                className={inputClass}
              />
            </Field>
            <Field label="Nº de arestas">
              <input
                type="number"
                min={0}
                value={edgeLimit}
                onChange={(event) => setEdgeLimit(Math.max(0, Number(event.target.value) || 0))}
                className={inputClass}
              />
            </Field>
          </div>
        </Card>

        <Card className="space-y-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Search size={13} /> Filtros
          </div>
          <Field label="Texto livre (interveniente, processo, ato)">
            <input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void run()}
              placeholder="ex.: construção civil"
              className={inputClass}
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            {facetSelect("Tipo", tipo, setTipo, status?.by_tipo)}
            {facetSelect("Comarca", comarca, setComarca, status?.top_comarcas)}
          </div>
          <Field label="Espécie do processo">
            <select className={inputClass} value={especie} onChange={(event) => setEspecie(event.target.value)}>
              <option value="">Todas</option>
              {(status?.by_especie ?? []).slice(0, 40).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.key} ({numberFormat.format(item.count)})
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Papel">
              <select className={inputClass} value={papel} onChange={(event) => setPapel(event.target.value)}>
                <option value="">Todos</option>
                {PAPEIS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="NIF/NIPC">
              <input
                value={nif}
                onChange={(event) => setNif(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && void run()}
                placeholder="500189412"
                className={`${inputClass} font-mono`}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Publicado de">
              <input type="date" value={dataFrom} onChange={(event) => setDataFrom(event.target.value)} className={inputClass} />
            </Field>
            <Field label="até">
              <input type="date" value={dataTo} onChange={(event) => setDataTo(event.target.value)} className={inputClass} />
            </Field>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => void run()}
              disabled={loading}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-400/15 px-3 py-1.5 text-[11.5px] font-medium text-emerald-100 hover:bg-emerald-400/25 disabled:opacity-50"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Construir grafo
            </button>
            <button
              type="button"
              onClick={() => {
                setQ("");
                setTipo("");
                setComarca("");
                setEspecie("");
                setPapel("");
                setNif("");
                setDataFrom("");
                setDataTo("");
                setMinCount(1);
              }}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-[11.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              Limpar
            </button>
          </div>
        </Card>
      </aside>

      {/* -------------------------------------------------------------- grafo */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setView(item.id)}
                aria-pressed={view === item.id}
                className={`rounded-lg px-2.5 py-1 text-[11px] transition ${
                  view === item.id ? "bg-emerald-400/15 text-emerald-200" : "text-muted-foreground hover:bg-white/10 hover:text-foreground"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={!graph}
              onClick={() =>
                graph && downloadCireFile("cire-grafo.csv", cireGraphToCsv(graph), "text/csv;charset=utf-8")
              }
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] text-muted-foreground hover:bg-white/10 hover:text-foreground disabled:opacity-40"
            >
              <Download size={12} /> CSV
            </button>
          </div>
        </div>

        {error ? (
          <Card className="flex items-start gap-2 border-rose-400/25 bg-rose-400/5 text-[11.5px] text-rose-200">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </Card>
        ) : null}

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Nós"
            value={numberFormat.format(meta?.kept_nodes ?? 0)}
            hint={meta && meta.nodes_total > meta.kept_nodes ? `de ${numberFormat.format(meta.nodes_total)} agregados` : undefined}
          />
          <Stat
            label="Arestas"
            value={numberFormat.format(meta?.kept_edges ?? 0)}
            hint={meta && meta.edges_total > meta.kept_edges ? `de ${numberFormat.format(meta.edges_total)}` : undefined}
          />
          <Stat
            label="Publicações no filtro"
            value={numberFormat.format(meta?.documents_matching ?? 0)}
            hint={meta ? `${numberFormat.format(meta.documents_scanned)} analisadas` : undefined}
          />
          <Stat
            label={metric === "mencoes" ? "Menções (topo)" : "Publicações (topo)"}
            value={numberFormat.format(
              graph?.nodes.reduce((acc, node) => Math.max(acc, node.value), 0) ?? 0,
            )}
            hint={`por ${shortFor(dimensionA).toLowerCase()}`}
          />
        </div>

        <Card className="relative !p-0">
          {view === "sankey" ? (
            !dimensionB ? (
              <p className="p-6 text-center text-[12px] text-muted-foreground">
                Os fluxos precisam de duas dimensões (escolha uma dimensão B, ex.: tipo → espécie).
              </p>
            ) : (
              <SankeyDiagram
                nodes={graph?.nodes ?? []}
                edges={graph?.edges ?? []}
                metric={CIRE_COMPONENT_METRIC}
                height={560}
                unitLabel={metric === "mencoes" ? "menções" : "publicações"}
                onNodeClick={(node) => setSelectedId(node.id)}
              />
            )
          ) : view === "treemap" ? (
            <TreemapChart
              nodes={graphForArea?.nodes ?? []}
              metric={CIRE_COMPONENT_METRIC}
              height={560}
              unitLabel={metric === "mencoes" ? "menções" : "publicações"}
              areaHint={`área = ${metric === "mencoes" ? "menções" : "publicações"} por ${shortFor(dimensionA).toLowerCase()}`}
              onNodeClick={(node) => setSelectedId(node.id)}
            />
          ) : view === "list" ? (
            <NodeTable
              graph={graph}
              metric={metric}
              labelFor={labelFor}
              onSelect={(id) => setSelectedId(id)}
              onOpenSearch={onOpenSearch}
            />
          ) : (
            <GraphCanvas
              graph={graph}
              layout={view === "hierarchical" ? "hierarchical" : view === "circular" ? "circular" : "network"}
              metric={CIRE_COMPONENT_METRIC}
              selectedNodeId={selectedId}
              loading={loading}
              unitLabel={metric === "mencoes" ? "menções" : "publicações"}
              nodeSummary={cireNodeSummary}
              edgeSummary={cireEdgeSummary}
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
              {metric === "mencoes" ? "menções a intervenientes" : "publicações distintas"} · cobertura ={" "}
              {meta.mode === "exato" ? "agregação exata" : meta.mode === "varredura-total" ? "todas as publicações" : "amostra"}.
            </p>
            {meta.directed ? (
              <p className="text-[11px] text-sky-300">
                Arestas dirigidas: {shortFor(meta.dimension_a)} → {shortFor(meta.dimension_b ?? "")}.
              </p>
            ) : null}
            {meta.notes.map((note, index) => (
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
                  <span className="text-sm font-semibold text-foreground break-words">{selected.label}</span>
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {cireTypeLabel(selected.type)} · {labelFor(selected.dimension)}
                  {selected.nif ? ` · NIF ${selected.nif}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onOpenSearch(cireNodeSearchParams(selected))}
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-400/15 px-2.5 py-1.5 text-[11px] text-emerald-100 hover:bg-emerald-400/25"
                >
                  <Search size={12} /> Ver publicações
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
              <Stat label="Publicações" value={numberFormat.format(selected.publicacoes)} />
              <Stat label="Menções" value={numberFormat.format(selected.mencoes)} />
              <Stat label="Ligações no grafo" value={numberFormat.format(neighbours.length)} hint="arestas visíveis" />
            </div>

            {neighbours.length > 0 ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                  <Link2 size={12} /> Vizinhos mais fortes
                </div>
                {neighbours.map(({ node, edge }) => (
                  <button
                    key={edge.source + edge.target}
                    type="button"
                    onClick={() => node && setSelectedId(node.id)}
                    className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-left text-[11px] hover:bg-white/10"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: node?.color ?? "#94a3b8" }} />
                      <span className="truncate text-foreground">{node?.label ?? "—"}</span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">{node ? labelFor(node.dimension) : ""}</span>
                    </span>
                    <span className="shrink-0 text-muted-foreground">
                      {numberFormat.format(edge.count)} publ.
                      {edge.mentions !== undefined && edge.mentions !== edge.count
                        ? ` · ${numberFormat.format(edge.mentions)} menções`
                        : ""}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Focus size={12} /> Sem ligações visíveis (escolha uma dimensão B para ver relações).
              </p>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  );
}

/** Tabela de nós (alternativa ao desenho, para grafos grandes). */
function NodeTable({
  graph,
  metric,
  labelFor,
  onSelect,
  onOpenSearch,
}: {
  graph: ReturnType<typeof toCireStudioGraph>;
  metric: CireGraphMetric;
  labelFor: (key: string) => string;
  onSelect: (id: string) => void;
  onOpenSearch: (params: CireSearchParams) => void;
}) {
  const nodes = cireGraphNodes(graph);
  if (nodes.length === 0) {
    return <p className="p-6 text-center text-[12px] text-muted-foreground">Sem nós para a combinação escolhida.</p>;
  }
  return (
    <div className="max-h-[560px] overflow-auto">
      <table className="w-full text-[11.5px]">
        <thead className="sticky top-0 bg-[#07151b] text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Nó</th>
            <th className="px-3 py-2">Dimensão</th>
            <th className="px-3 py-2 text-right">Publicações</th>
            <th className="px-3 py-2 text-right">Menções</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {nodes.map((node: CireStudioNode) => {
            const rich = node;
            return (
              <tr key={node.id} className="border-t border-white/5">
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => onSelect(node.id)}
                    className="flex items-center gap-2 text-left text-foreground hover:text-emerald-200"
                  >
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: node.color }} />
                    <span className="truncate">{node.label}</span>
                  </button>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{labelFor(node.dimension)}</td>
                <td className="px-3 py-2 text-right">{numberFormat.format(rich.publicacoes)}</td>
                <td className="px-3 py-2 text-right">{numberFormat.format(rich.mencoes)}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => onOpenSearch(cireNodeSearchParams(node))}
                    className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[10.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
                    title="Ver publicações deste nó"
                  >
                    <Table2 size={11} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[10.5px] text-muted-foreground">
        Ordenado por {metric === "mencoes" ? "menções" : "publicações"}.
      </p>
    </div>
  );
}
