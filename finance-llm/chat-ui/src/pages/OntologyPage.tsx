/**
 * Ontologia — a camada semântica do IQ OS.
 *
 * Mostra os tipos de objeto da plataforma (Empresa, Contrato, CPV, Região,
 * Marca, Firma, Ticker, Cotação, Notícia, Sentimento, Tópico, Conta, Contacto,
 * Oportunidade, Atividade, Pessoa), as ligações entre eles e as ações
 * disponíveis — com um explorador de objetos e um painel de IA que mostra o
 * contexto ontológico usado para fundamentar respostas (e as valida).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Database,
  Info,
  Layers,
  Link2,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Table2,
  Wand2,
  XCircle,
} from "lucide-react";
import type {
  AiAnswer,
  AiContext,
  ObjectLinksResult,
  ObjectQueryResult,
  OntologyAction,
  OntologyGraph,
  OntologyLinkType,
  OntologyObject,
  OntologyObjectType,
  OntologyObjectTypeSummary,
  OntologyProperty,
  OntologyStatus,
  OntologySummary,
  OntologyTypeLink,
  ResolveResult,
  ValidationResult,
} from "../ontologyApi";
import {
  askOntologyGrounded,
  buildOntologyContext,
  getObjectType,
  getOntologyObject,
  getOntologyStatus,
  getOntologySummary,
  listActions,
  listLinkTypes,
  listObjectTypes,
  queryOntologyObjects,
  resolveOntologyAction,
  resolveOntologyEntities,
  validateWithOntology,
} from "../ontologyApi";

type TabId = "overview" | "types" | "links" | "actions" | "ai";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Visão geral", icon: <Layers size={14} /> },
  { id: "types", label: "Tipos de objeto", icon: <Boxes size={14} /> },
  { id: "links", label: "Ligações", icon: <Link2 size={14} /> },
  { id: "actions", label: "Ações", icon: <Play size={14} /> },
  { id: "ai", label: "IA & validação", icon: <Sparkles size={14} /> },
];

const SOURCE_KIND_LABEL: Record<string, string> = {
  es: "Documentos (Elasticsearch)",
  aggregation: "Agregado (Elasticsearch)",
  derived: "Derivado (combina fontes)",
};

const DOMAIN_ACCENT: Record<string, string> = {
  contratacao: "#0ea5e9",
  mercados: "#f43f5e",
  crm: "#f59e0b",
  pessoas: "#a78bfa",
};

const numberFormat = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 });
const moneyFormat = new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

function formatValue(value: unknown, unit?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return unit === "€" ? moneyFormat.format(value) : numberFormat.format(value);
  }
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (Array.isArray(value)) return value.map((item) => formatValue(item, unit)).join(", ");
  const text = String(value);
  if (unit === "€" && /^\d+(\.\d+)?$/.test(text)) return moneyFormat.format(Number(text));
  return text.length > 160 ? `${text.slice(0, 157)}…` : text;
}

function StatusPill({ tone, children }: { tone: "ok" | "warn" | "error" | "muted"; children: React.ReactNode }) {
  const tones: Record<string, string> = {
    ok: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    warn: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    error: "border-rose-400/30 bg-rose-400/10 text-rose-200",
    muted: "border-white/10 bg-white/5 text-muted-foreground",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3" title={hint}>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/* ---------------------------------------------------------- grafo de tipos */
function TypeGraph({ graph, onSelect }: { graph: OntologyGraph; onSelect: (typeId: string) => void }) {
  const width = 900;
  const height = 500;
  const layout = useMemo(() => {
    const domains = Array.from(new Set(graph.nodes.map((node) => node.domain)));
    const positions = new Map<string, { x: number; y: number; r: number }>();
    const centerX = width / 2;
    const centerY = height / 2;
    domains.forEach((domain, domainIndex) => {
      const nodes = graph.nodes.filter((node) => node.domain === domain);
      const ring = 120 + domainIndex * 62;
      const offset = (domainIndex * Math.PI) / 6;
      nodes.forEach((node, index) => {
        const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2 + offset;
        const degree = graph.edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
        positions.set(node.id, {
          x: centerX + Math.cos(angle) * ring,
          y: centerY + Math.sin(angle) * ring * 0.72,
          r: 9 + Math.min(9, degree),
        });
      });
    });
    return positions;
  }, [graph]);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[380px] w-full" role="img" aria-label="Grafo de tipos de objeto e ligações">
      <defs>
        <radialGradient id="ontology-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#0f766e" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#0f766e" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={width / 2} cy={height / 2} rx={width / 2.2} ry={height / 2.6} fill="url(#ontology-glow)" />
      {graph.edges.map((edge) => {
        const from = layout.get(edge.source);
        const to = layout.get(edge.target);
        if (!from || !to) return null;
        return (
          <line
            key={edge.id}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke="rgba(148,163,184,0.35)"
            strokeWidth={edge.reverse ? 1.6 : 1}
            strokeDasharray={edge.reverse ? "0" : "4 3"}
          >
            <title>{`${edge.source} ${edge.label} ${edge.target}`}</title>
          </line>
        );
      })}
      {graph.nodes.map((node) => {
        const position = layout.get(node.id);
        if (!position) return null;
        const accent = DOMAIN_ACCENT[node.domain] ?? "#94a3b8";
        return (
          <g key={node.id} className="cursor-pointer" onClick={() => onSelect(node.id)}>
            <circle cx={position.x} cy={position.y} r={position.r} fill={`${accent}33`} stroke={accent} strokeWidth={1.4} />
            <text
              x={position.x}
              y={position.y + position.r + 11}
              textAnchor="middle"
              className="fill-current text-[10px] text-muted-foreground"
              style={{ fontSize: 10 }}
            >
              {node.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* --------------------------------------------------------- explorador */
function FilterInputs({
  properties,
  values,
  onChange,
  options,
}: {
  properties: OntologyProperty[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  options: Record<string, string[]>;
}) {
  if (!properties.length) {
    return <p className="text-[11px] text-muted-foreground">Este tipo não tem propriedades filtráveis.</p>;
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {properties.map((property) => {
        const value = values[property.id] ?? "";
        const setValue = (next: string) => onChange({ ...values, [property.id]: next });
        const listId = `ontology-values-${property.id}`;
        const suggestions = options[property.id] ?? [];
        return (
          <label key={property.id} className="flex flex-col gap-1 text-[11px] text-muted-foreground">
            <span className="font-medium">
              {property.label}
              {property.unit ? <span className="ml-1 opacity-70">({property.unit})</span> : null}
            </span>
            {property.type === "enum" && property.enum ? (
              <select
                value={value}
                onChange={(event) => setValue(event.target.value)}
                className="glass-card rounded-lg border border-white/10 px-2 py-1.5 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              >
                <option value="">Todos</option>
                {property.enum.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : property.type === "boolean" ? (
              <select
                value={value}
                onChange={(event) => setValue(event.target.value)}
                className="glass-card rounded-lg border border-white/10 px-2 py-1.5 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              >
                <option value="">Todos</option>
                <option value="true">Sim</option>
                <option value="false">Não</option>
              </select>
            ) : (
              <>
                <input
                  type={property.type === "number" ? "number" : property.type === "date" ? "date" : "text"}
                  value={value}
                  list={suggestions.length ? listId : undefined}
                  onChange={(event) => setValue(event.target.value)}
                  placeholder={
                    suggestions.length
                      ? `escrever ou escolher entre ${suggestions.length} valores da ontologia…`
                      : property.type === "date"
                        ? "aaaa-mm-dd"
                        : "…"
                  }
                  className="glass-card rounded-lg border border-white/10 px-2 py-1.5 text-xs text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                />
                {suggestions.length ? (
                  <datalist id={listId}>
                    {suggestions.map((option) => (
                      <option key={option} value={option} />
                    ))}
                  </datalist>
                ) : null}
              </>
            )}
          </label>
        );
      })}
    </div>
  );
}

function ObjectTable({
  result,
  columns,
  onSelect,
}: {
  result: ObjectQueryResult;
  columns: OntologyProperty[];
  onSelect: (object: OntologyObject) => void;
}) {
  if (!result.items.length) {
    return (
      <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-6 text-center text-xs text-muted-foreground">
        Sem resultados para esta consulta.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th key={column.id} className="border-b border-white/10 px-2 py-2 font-medium">
                {column.label}
              </th>
            ))}
            <th className="border-b border-white/10 px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {result.items.map((item) => (
            <tr key={item._id} className="transition hover:bg-white/5">
              {columns.map((column) => (
                <td key={column.id} className="border-b border-white/5 px-2 py-1.5 align-top">
                  {formatValue(item[column.id], column.unit)}
                </td>
              ))}
              <td className="border-b border-white/5 px-2 py-1.5 text-right">
                <button
                  type="button"
                  onClick={() => onSelect(item)}
                  className="rounded-lg border border-white/10 px-2 py-1 text-[10px] hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                >
                  Abrir
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ObjectDetail({
  detail,
  onOpenObject,
  onOpenType,
}: {
  detail: { object: OntologyObject; typeLabel: string; properties: OntologyProperty[]; links?: ObjectLinksResult; actions?: OntologyAction[] };
  onOpenObject: (typeId: string, objectId: string) => void;
  onOpenType: (typeId: string) => void;
}) {
  const [actionRequest, setActionRequest] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const runAction = async (action: OntologyAction) => {
    setActionError(null);
    setActionRequest(null);
    try {
      const resolved = await resolveOntologyAction(action.id, { type: detail.object.__type as string, id: detail.object._id });
      setActionRequest(
        `${resolved.method} ${resolved.url || "(sem URL)"}${resolved.body ? `\n${JSON.stringify(resolved.body)}` : ""}`,
      );
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Erro ao resolver a ação");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{String(detail.object._label)}</span>
        <StatusPill tone="muted">{detail.typeLabel}</StatusPill>
        <code className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">{detail.object._id}</code>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {detail.properties
          .filter((property) => detail.object[property.id] !== null && detail.object[property.id] !== undefined)
          .map((property) => (
            <div key={property.id} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{property.label}</p>
              <p className="text-xs">{formatValue(detail.object[property.id], property.unit)}</p>
            </div>
          ))}
      </div>

      {detail.links?.links?.length ? (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-semibold">
            <Link2 size={13} className="text-teal-300" /> Ligações
          </p>
          {detail.links.links.map((group) => (
            <div key={`${group.id}-${group.direction}`} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
              <p className="text-[11px]">
                <span className="font-medium">{group.label}</span>{" "}
                <span className="text-muted-foreground">
                  {group.direction === "reverse" ? "←" : "→"} {group.other_label} ({group.count ?? group.items.length})
                </span>
              </p>
              {group.items.length ? (
                <ul className="mt-1 space-y-0.5">
                  {group.items.slice(0, 6).map((item) => (
                    <li key={item._id}>
                      <button
                        type="button"
                        onClick={() => onOpenObject(group.other_type, item._id)}
                        className="text-left text-[11px] text-teal-200 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                      >
                        {String(item._label)}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[10px] text-muted-foreground">Sem objetos ligados.</p>
              )}
              {group.notes?.length ? <p className="mt-1 text-[10px] text-amber-200/80">{group.notes.join(" ")}</p> : null}
            </div>
          ))}
        </div>
      ) : null}

      {detail.actions?.length ? (
        <div className="space-y-1.5">
          <p className="flex items-center gap-1.5 text-xs font-semibold">
            <Play size={13} className="text-teal-300" /> Ações
          </p>
          <div className="flex flex-wrap gap-1.5">
            {detail.actions.map((action) => (
              <button
                key={action.id}
                type="button"
                onClick={() => runAction(action)}
                title={action.description}
                className="rounded-lg border border-white/10 px-2 py-1 text-[10px] hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              >
                {action.label}
                {action.requires_session ? " · sessão" : ""}
              </button>
            ))}
          </div>
          {actionRequest ? (
            <pre className="overflow-x-auto rounded-xl border border-white/10 bg-black/30 p-2 text-[10px] text-teal-100">{actionRequest}</pre>
          ) : null}
          {actionError ? <p className="text-[10px] text-rose-200">{actionError}</p> : null}
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => onOpenType(String(detail.object.__type))}
        className="text-[10px] text-muted-foreground underline hover:text-foreground"
      >
        Ver definição do tipo
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ página */
export default function OntologyPage() {
  const [tab, setTab] = useState<TabId>("overview");
  const [summary, setSummary] = useState<OntologySummary | null>(null);
  const [types, setTypes] = useState<OntologyObjectTypeSummary[]>([]);
  const [links, setLinks] = useState<OntologyLinkType[]>([]);
  const [actions, setActions] = useState<OntologyAction[]>([]);
  const [status, setStatus] = useState<OntologyStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [typeDetail, setTypeDetail] = useState<{
    object_type: OntologyObjectType;
    links: OntologyTypeLink[];
    actions: OntologyAction[];
    source_kind?: string;
    session_required?: boolean;
  } | null>(null);
  const [typeSearch, setTypeSearch] = useState("");

  const [explorerSearch, setExplorerSearch] = useState("");
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(20);
  const [queryResult, setQueryResult] = useState<ObjectQueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [querying, setQuerying] = useState(false);
  const [openObject, setOpenObject] = useState<{
    object: OntologyObject;
    typeLabel: string;
    properties: OntologyProperty[];
    links?: ObjectLinksResult;
    actions?: OntologyAction[];
  } | null>(null);

  const [question, setQuestion] = useState("Quais os contratos da EDP e o valor total?");
  const [aiContext, setAiContext] = useState<AiContext | null>(null);
  const [aiAnswer, setAiAnswer] = useState<AiAnswer | null>(null);
  const [aiBusy, setAiBusy] = useState<"context" | "answer" | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [resolveText, setResolveText] = useState("");
  const [resolveResult, setResolveResult] = useState<ResolveResult | null>(null);
  const [draftAnswer, setDraftAnswer] = useState("");
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([getOntologySummary(), listObjectTypes(), listLinkTypes(), listActions(), getOntologyStatus()])
      .then(([summaryResponse, typesResponse, linksResponse, actionsResponse, statusResponse]) => {
        if (cancelled) return;
        setSummary(summaryResponse);
        setTypes(typesResponse.items);
        setLinks(linksResponse.items);
        setActions(actionsResponse.items);
        setStatus(statusResponse);
        setSelectedType((current) => current ?? typesResponse.items[0]?.id ?? null);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Erro ao carregar a ontologia");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    if (!selectedType) {
      setTypeDetail(null);
      return;
    }
    let cancelled = false;
    getObjectType(selectedType)
      .then((response) => {
        if (!cancelled) setTypeDetail(response);
      })
      .catch(() => {
        if (!cancelled) setTypeDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedType]);

  const activeType = typeDetail?.object_type;

  const runQuery = useCallback(
    async (typeId: string, search: string, filters: Record<string, string>, size: number) => {
      setQuerying(true);
      setQueryError(null);
      try {
        const parsed: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(filters)) {
          if (value === "") continue;
          const property = activeType?.properties.find((item) => item.id === key);
          if (property?.type === "number") parsed[key] = Number(value);
          else if (property?.type === "boolean") parsed[key] = value === "true";
          else parsed[key] = value;
        }
        const result = await queryOntologyObjects(typeId, { search, filters: parsed, size });
        setQueryResult(result);
      } catch (error) {
        setQueryError(error instanceof Error ? error.message : "Erro na consulta");
        setQueryResult(null);
      } finally {
        setQuerying(false);
      }
    },
    [activeType],
  );

  useEffect(() => {
    if (!activeType) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (cancelled) return;
      void runQuery(activeType.id, explorerSearch, filterValues, pageSize);
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeType?.id, explorerSearch, filterValues, pageSize]);

  const openObjectDetail = useCallback(
    async (typeId: string, objectId: string) => {
      try {
        const response = await getOntologyObject(typeId, objectId, { withLinks: true });
        const summaryEntry = types.find((item) => item.id === typeId);
        const definition = typeId === activeType?.id && activeType ? activeType : (await getObjectType(typeId)).object_type;
        setOpenObject({
          object: { ...response.object, __type: typeId },
          typeLabel: response.label ?? summaryEntry?.label ?? definition.label,
          properties: definition.properties,
          links: response.links,
          actions: response.actions,
        });
      } catch (error) {
        setQueryError(error instanceof Error ? error.message : "Erro ao abrir o objeto");
      }
    },
    [activeType, types],
  );

  const filterableProperties = useMemo(() => {
    if (!activeType) return [];
    const priority = ["ano", "regiao", "nif", "papel", "tipo_contrato", "procedimento", "estado", "origem", "fase", "titulo"];
    const all = activeType.properties.filter((property) => property.filterable || property.searchable);
    return all
      .slice()
      .sort((left, right) => priority.indexOf(left.id) - priority.indexOf(right.id))
      .slice(0, 9);
  }, [activeType]);

  // Valores válidos vêm da própria ontologia (`values_from`): região, CPV, tópico, ticker.
  const valueSourceIds = useMemo(() => {
    if (!activeType) return [];
    const ids = new Set<string>();
    for (const property of filterableProperties) {
      if (property.values_from) ids.add(property.values_from);
    }
    return Array.from(ids).sort();
  }, [activeType, filterableProperties]);

  const [valueOptions, setValueOptions] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!valueSourceIds.length) {
      setValueOptions({});
      return;
    }
    let cancelled = false;
    Promise.all(
      valueSourceIds.map(async (sourceId) => {
        try {
          const result = await queryOntologyObjects(sourceId, { size: 200 });
          return [sourceId, result.items.map((item) => String(item._label))] as const;
        } catch {
          return [sourceId, [] as string[]] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, string[]> = {};
      for (const [sourceId, values] of entries) {
        if (values.length) next[sourceId] = values;
      }
      setValueOptions(next);
    });
    return () => {
      cancelled = true;
    };
  }, [valueSourceIds]);

  const filterOptions = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const property of filterableProperties) {
      const source = property.values_from;
      if (source && valueOptions[source]?.length) map[property.id] = valueOptions[source];
    }
    return map;
  }, [filterableProperties, valueOptions]);

  const columns = useMemo(() => {
    if (!activeType) return [];
    const pk = activeType.properties.find((property) => property.pk)?.id;
    const preferred = ["nome", "titulo", "assunto", "objecto", "simbolo", "data", "ano", "valor_total", "contratos", "preco", "cargo", "fase", "media", "descricao"];
    const chosen = ["contrato", "empresa", "firma"].includes(activeType.id)
      ? ["idcontrato", "objecto", "preco", "ano", "regiao"]
      : preferred;
    const list: OntologyProperty[] = [];
    for (const id of chosen) {
      const property = activeType.properties.find((item) => item.id === id);
      if (property && !list.some((item) => item.id === property.id)) list.push(property);
      if (list.length >= 5) break;
    }
    if (pk) {
      const pkProperty = activeType.properties.find((item) => item.id === pk);
      if (pkProperty && !list.some((item) => item.id === pk)) list.unshift(pkProperty);
    }
    return list.slice(0, 5);
  }, [activeType]);

  const handleAsk = async (mode: "context" | "answer") => {
    setAiBusy(mode);
    setAiError(null);
    try {
      if (mode === "context") {
        setAiContext(await buildOntologyContext(question, 5, 3));
        setAiAnswer(null);
      } else {
        const response = await askOntologyGrounded(question);
        setAiAnswer(response);
        setAiContext(response.context);
        setValidation(response.validation);
        setDraftAnswer("");
      }
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "Erro na consulta à ontologia");
    } finally {
      setAiBusy(null);
    }
  };

  const handleValidate = async () => {
    setAiError(null);
    try {
      setValidation(await validateWithOntology(draftAnswer, question, aiContext));
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "Erro na validação");
    }
  };

  const handleResolve = async () => {
    setAiError(null);
    try {
      setResolveResult(await resolveOntologyEntities(resolveText, 6));
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "Erro na resolução de entidades");
    }
  };

  const filteredTypes = useMemo(() => {
    const needle = typeSearch.trim().toLowerCase();
    if (!needle) return types;
    return types.filter(
      (item) =>
        item.label.toLowerCase().includes(needle) ||
        item.id.includes(needle) ||
        (item.description ?? "").toLowerCase().includes(needle),
    );
  }, [typeSearch, types]);

  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-4 px-4 py-4">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold">
            <Boxes className="text-teal-300" size={22} /> Ontologia
          </h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            A camada semântica do IQ OS: tipos de objeto, propriedades, ligações e ações ligados aos dados reais.
            É a mesma definição que fundamenta e valida as respostas da IA.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={status?.elasticsearch ? "ok" : "error"}>
            <Database size={11} /> {status?.elasticsearch ? "Elasticsearch ligado" : "Elasticsearch indisponível"}
          </StatusPill>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="glass-card flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
          >
            <RefreshCw size={14} /> Atualizar
          </button>
        </div>
      </header>

      {loadError ? (
        <p className="rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-100">{loadError}</p>
      ) : null}

      <nav className="flex flex-wrap gap-1.5" aria-label="Secções da ontologia">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id ? "page" : undefined}
            className={[
              "flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
              tab === item.id
                ? "border-teal-400/40 bg-teal-400/10 text-teal-200"
                : "glass-card border-white/10 text-muted-foreground hover:bg-white/5",
            ].join(" ")}
          >
            {item.icon} {item.label}
          </button>
        ))}
      </nav>

      {loading && !summary ? (
        <div className="glass-card flex items-center gap-2 rounded-2xl px-4 py-10 text-sm text-muted-foreground">
          <Loader2 className="animate-spin" size={16} /> A carregar a ontologia…
        </div>
      ) : null}

      {tab === "overview" && summary ? (
        <div className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <Kpi label="Tipos de objeto" value={summary.totals.object_types} hint="entidades da plataforma modeladas" />
            <Kpi label="Ligações" value={summary.totals.link_types} hint="relações entre tipos" />
            <Kpi label="Ações" value={summary.totals.actions} hint="operações disponíveis" />
            <Kpi label="Personalizados" value={summary.totals.custom} hint="criados sobre a base" />
            <Kpi label="Exigem sessão" value={summary.totals.session_required} hint="dados privados (CRM)" />
          </div>

          <section className="glass-card gradient-border rounded-2xl p-4">
            <h3 className="text-sm font-semibold">Grafo de tipos de objeto</h3>
            <p className="text-[11px] text-muted-foreground">
              Cada círculo é um tipo; as linhas contínuas têm ligação inversa definida, as tracejadas são unidirecionais.
              Clique num tipo para ver a definição.
            </p>
            <TypeGraph
              graph={summary.graph}
              onSelect={(typeId) => {
                setSelectedType(typeId);
                setTab("types");
              }}
            />
          </section>

          <div className="grid gap-3 md:grid-cols-2">
            {summary.domains.map((domain) => (
              <section key={domain.id} className="glass-card rounded-2xl p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{domain.label}</h3>
                  <StatusPill tone="muted">{domain.object_types ?? 0} tipos</StatusPill>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">{domain.description}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {summary.graph.nodes
                    .filter((node) => node.domain === domain.id)
                    .map((node) => (
                      <button
                        key={node.id}
                        type="button"
                        onClick={() => {
                          setSelectedType(node.id);
                          setTab("types");
                        }}
                        className="rounded-lg border border-white/10 px-2 py-1 text-[10px] hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                        title={`${node.properties} propriedades · origem: ${SOURCE_KIND_LABEL[node.source_kind] ?? node.source_kind}`}
                      >
                        {node.label}
                      </button>
                    ))}
                </div>
              </section>
            ))}
          </div>

          {status?.sources?.length ? (
            <section className="glass-card rounded-2xl p-4">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Database size={14} className="text-teal-300" /> Fontes de dados
              </h3>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="border-b border-white/10 px-2 py-1.5">Índice</th>
                      <th className="border-b border-white/10 px-2 py-1.5">Documentos</th>
                      <th className="border-b border-white/10 px-2 py-1.5">Tipos de objeto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.sources.map((source) => (
                      <tr key={source.index}>
                        <td className="border-b border-white/5 px-2 py-1.5 font-mono text-[11px]">{source.index}</td>
                        <td className="border-b border-white/5 px-2 py-1.5">
                          {source.documents === null ? "—" : numberFormat.format(source.documents)}
                        </td>
                        <td className="border-b border-white/5 px-2 py-1.5 text-muted-foreground">
                          {source.object_types.join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          <section className="glass-card rounded-2xl p-4 text-[11px] text-muted-foreground">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <Info size={14} className="text-teal-300" /> Notas de honestidade dos dados
            </h3>
            <ul className="mt-1.5 list-disc space-y-1 pl-5">
              {summary.limits.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
              <li>Os tipos do CRM exigem sessão: cada utilizador só vê os seus registos (administradores veem toda a equipa).</li>
              <li>Versão {summary.version} · atualizada em {new Date(summary.updated_at).toLocaleString("pt-PT")}.</li>
            </ul>
          </section>
        </div>
      ) : null}

      {tab === "types" ? (
        <div className="grid gap-3 xl:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="glass-card rounded-2xl p-3">
            <label className="flex items-center gap-2 rounded-xl border border-white/10 px-2 py-1.5">
              <Search size={14} className="text-muted-foreground" />
              <input
                value={typeSearch}
                onChange={(event) => setTypeSearch(event.target.value)}
                placeholder="Filtrar tipos…"
                className="w-full bg-transparent text-xs outline-none"
              />
            </label>
            <ul className="mt-2 max-h-[520px] space-y-1 overflow-y-auto pr-1">
              {filteredTypes.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedType(item.id);
                      setOpenObject(null);
                      setQueryResult(null);
                    }}
                    aria-current={selectedType === item.id ? "true" : undefined}
                    className={[
                      "w-full rounded-xl border px-2.5 py-2 text-left text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50",
                      selectedType === item.id
                        ? "border-teal-400/40 bg-teal-400/10 text-teal-100"
                        : "border-white/10 hover:bg-white/5",
                    ].join(" ")}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">{item.label}</span>
                      {item.session_required ? <ShieldCheck size={12} className="text-amber-200" /> : null}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-muted-foreground">
                      {item.properties} propriedades · {item.links.out}↗ {item.links.in}↘
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <div className="space-y-3">
            {activeType ? (
              <section className="glass-card gradient-border rounded-2xl p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold">{activeType.label}</h3>
                  <StatusPill tone="muted">{SOURCE_KIND_LABEL[activeType.binding.kind] ?? activeType.binding.kind}</StatusPill>
                  {activeType.builtin ? <StatusPill tone="muted">base</StatusPill> : <StatusPill tone="warn">personalizado</StatusPill>}
                  {typeDetail?.session_required ? <StatusPill tone="warn">exige sessão</StatusPill> : null}
                  {activeType.resolvable ? <StatusPill tone="ok">resolvível por nome/NIF</StatusPill> : null}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{activeType.description}</p>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Fonte: {(activeType.binding.sources ?? []).join(", ") || "—"}
                  {activeType.binding.index ? ` · índice ${activeType.binding.index}` : ""}
                  {activeType.binding.nested ? ` · campo aninhado ${activeType.binding.nested}` : ""}
                  {activeType.query_hint ? ` · ${activeType.query_hint}` : ""}
                </p>

                <h4 className="mt-3 flex items-center gap-1.5 text-xs font-semibold">
                  <Table2 size={13} className="text-teal-300" /> Propriedades
                </h4>
                <div className="mt-1 overflow-x-auto">
                  <table className="w-full text-left text-[11px]">
                    <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="border-b border-white/10 px-2 py-1.5">Propriedade</th>
                        <th className="border-b border-white/10 px-2 py-1.5">Tipo</th>
                        <th className="border-b border-white/10 px-2 py-1.5">Campo de origem</th>
                        <th className="border-b border-white/10 px-2 py-1.5">Capacidades</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeType.properties.map((property) => (
                        <tr key={property.id}>
                          <td className="border-b border-white/5 px-2 py-1.5">
                            {property.label}
                            {property.pk ? <span className="ml-1 text-[9px] text-teal-200">PK</span> : null}
                          </td>
                          <td className="border-b border-white/5 px-2 py-1.5 text-muted-foreground">
                            {property.type}
                            {property.unit ? ` (${property.unit})` : ""}
                            {property.enum?.length ? `: ${property.enum.join(", ")}` : ""}
                          </td>
                          <td className="border-b border-white/5 px-2 py-1.5 font-mono text-[10px] text-muted-foreground">
                            {property.field ?? "—"}
                          </td>
                          <td className="border-b border-white/5 px-2 py-1.5 text-muted-foreground">
                            {[property.searchable ? "pesquisa" : null, property.filterable ? "filtro" : null, property.sortable ? "ordenação" : null]
                              .filter(Boolean)
                              .join(", ") || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <h4 className="flex items-center gap-1.5 text-xs font-semibold">
                      <Link2 size={13} className="text-teal-300" /> Ligações ({typeDetail?.links.length ?? 0})
                    </h4>
                    <ul className="mt-1 space-y-1">
                      {(typeDetail?.links ?? []).map((link) => (
                        <li key={`${link.id}-${link.direction}`} className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px]">
                          <span className="font-medium">{link.label}</span>{" "}
                          <span className="text-muted-foreground">
                            {link.direction === "reverse" ? "← " : "→ "}
                            {link.other_label}
                            {link.cardinality ? ` · ${link.cardinality}` : ""}
                          </span>
                          {!link.available ? <span className="ml-1 text-[10px] text-amber-200/80">sem inverso definido</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="flex items-center gap-1.5 text-xs font-semibold">
                      <Play size={13} className="text-teal-300" /> Ações ({(typeDetail?.actions ?? []).length})
                    </h4>
                    <ul className="mt-1 space-y-1">
                      {(typeDetail?.actions ?? []).map((action) => (
                        <li key={action.id} className="rounded-xl border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px]">
                          <span className="font-medium">{action.label}</span>
                          <span className="ml-1 text-[10px] text-muted-foreground">
                            {action.kind}
                            {action.requires_session ? " · sessão" : ""}
                          </span>
                          <p className="text-[10px] text-muted-foreground">{action.description}</p>
                        </li>
                      ))}
                      {!(typeDetail?.actions ?? []).length ? (
                        <li className="text-[11px] text-muted-foreground">Sem ações definidas para este tipo.</li>
                      ) : null}
                    </ul>
                  </div>
                </div>
              </section>
            ) : null}

            {activeType ? (
              <section className="glass-card rounded-2xl p-4">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                  <Search size={14} className="text-teal-300" /> Explorador de objetos
                </h3>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <input
                    value={explorerSearch}
                    onChange={(event) => setExplorerSearch(event.target.value)}
                    placeholder={`Pesquisar em ${activeType.label.toLowerCase()}…`}
                    className="glass-card min-w-[220px] flex-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
                  />
                  <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    Resultados
                    <select
                      value={pageSize}
                      onChange={(event) => setPageSize(Number(event.target.value))}
                      className="glass-card rounded-lg border border-white/10 px-2 py-1.5 text-xs text-foreground"
                    >
                      {[10, 20, 50, 100].map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      setFilterValues({});
                      setExplorerSearch("");
                    }}
                    className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] hover:bg-white/10"
                  >
                    Limpar
                  </button>
                </div>

                <div className="mt-2">
                  <FilterInputs
                    properties={filterableProperties}
                    values={filterValues}
                    onChange={setFilterValues}
                    options={filterOptions}
                  />
                </div>

                {queryResult ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span>
                      {numberFormat.format(queryResult.total)} objetos
                      {queryResult.exact ? "" : " (amostra)"}
                    </span>
                    {queryResult.notes.map((note) => (
                      <StatusPill key={note} tone="muted">
                        {note}
                      </StatusPill>
                    ))}
                  </div>
                ) : null}

                {queryError ? (
                  <p className="mt-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-[11px] text-rose-100">{queryError}</p>
                ) : null}

                <div className="mt-2">
                  {querying ? (
                    <p className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
                      <Loader2 className="animate-spin" size={14} /> A consultar…
                    </p>
                  ) : queryResult ? (
                    <ObjectTable result={queryResult} columns={columns} onSelect={(object) => void openObjectDetail(activeType.id, object._id)} />
                  ) : null}
                </div>
              </section>
            ) : null}

            {openObject ? (
              <section className="glass-card gradient-border rounded-2xl p-4">
                <ObjectDetail
                  detail={openObject}
                  onOpenObject={(typeId, objectId) => {
                    setSelectedType(typeId);
                    void openObjectDetail(typeId, objectId);
                  }}
                  onOpenType={(typeId) => setSelectedType(typeId)}
                />
              </section>
            ) : null}
          </div>
        </div>
      ) : null}

      {tab === "links" ? (
        <section className="glass-card rounded-2xl p-4">
          <h3 className="text-sm font-semibold">Ligações entre tipos de objeto</h3>
          <p className="text-[11px] text-muted-foreground">
            Cada ligação define como navegar entre objetos. «Inversa» significa que a ontologia sabe seguir a relação nos
            dois sentidos.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="border-b border-white/10 px-2 py-2">Ligação</th>
                  <th className="border-b border-white/10 px-2 py-2">De</th>
                  <th className="border-b border-white/10 px-2 py-2">Para</th>
                  <th className="border-b border-white/10 px-2 py-2">Cardinalidade</th>
                  <th className="border-b border-white/10 px-2 py-2">Inversa</th>
                  <th className="border-b border-white/10 px-2 py-2">Descrição</th>
                </tr>
              </thead>
              <tbody>
                {links.map((link) => (
                  <tr key={link.id} className="hover:bg-white/5">
                    <td className="border-b border-white/5 px-2 py-1.5">
                      <span className="font-medium">{link.label}</span>
                      <code className="ml-1 rounded bg-white/5 px-1 text-[10px] text-muted-foreground">{link.id}</code>
                    </td>
                    <td className="border-b border-white/5 px-2 py-1.5">{link.from_label ?? link.from}</td>
                    <td className="border-b border-white/5 px-2 py-1.5">
                      <span className="inline-flex items-center gap-1">
                        <ArrowRight size={11} className="text-teal-300" /> {link.to_label ?? link.to}
                      </span>
                    </td>
                    <td className="border-b border-white/5 px-2 py-1.5 text-muted-foreground">{link.cardinality ?? "—"}</td>
                    <td className="border-b border-white/5 px-2 py-1.5">
                      {link.has_reverse ? <StatusPill tone="ok">sim</StatusPill> : <StatusPill tone="muted">não</StatusPill>}
                    </td>
                    <td className="border-b border-white/5 px-2 py-1.5 text-muted-foreground">{link.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {tab === "actions" ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {actions.map((action) => (
            <section key={action.id} className="glass-card rounded-2xl p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold">{action.label}</h3>
                <StatusPill tone="muted">{action.kind}</StatusPill>
                {action.requires_session ? <StatusPill tone="warn">sessão</StatusPill> : null}
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">{action.description}</p>
              <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                {action.object_type ?? "global"} · {action.method ?? (action.kind === "navigate" ? "GET" : "POST")}{" "}
                {action.url ?? action.target ?? "—"}
              </p>
              {action.params?.length ? (
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Parâmetros: {action.params.map((param) => `${param.id} (${param.from}${param.property ? `:${param.property}` : ""})`).join(", ")}
                </p>
              ) : null}
              <button
                type="button"
                onClick={async () => {
                  setTab("ai");
                  setAiError(null);
                  try {
                    const resolved = await resolveOntologyAction(action.id);
                    setAiError(
                      `Pedido de «${action.label}»: ${resolved.method} ${resolved.url || "(precisa de um objeto)"}${
                        resolved.body ? ` · ${JSON.stringify(resolved.body)}` : ""
                      }`,
                    );
                  } catch (error) {
                    setAiError(error instanceof Error ? error.message : "Erro ao resolver a ação");
                  }
                }}
                className="mt-2 flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1 text-[10px] hover:bg-white/10"
              >
                <Wand2 size={11} /> Ver pedido
              </button>
            </section>
          ))}
        </div>
      ) : null}

      {tab === "ai" ? (
        <div className="space-y-3">
          <section className="glass-card gradient-border rounded-2xl p-4">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles size={14} className="text-teal-300" /> Contexto ontológico (grounding)
            </h3>
            <p className="text-[11px] text-muted-foreground">
              A IA recebe estes objetos e relações verificados antes de responder. Não há inferência fora dos dados: o que
              não consta aqui é declarado como desconhecido.
            </p>
            <div className="mt-2 flex flex-col gap-2 md:flex-row">
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ex.: Quais os contratos da EDP e o valor total?"
                className="glass-card flex-1 rounded-lg border border-white/10 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={aiBusy !== null || !question.trim()}
                  onClick={() => void handleAsk("context")}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40"
                >
                  {aiBusy === "context" ? <Loader2 className="animate-spin" size={13} /> : <Search size={13} />} Construir contexto
                </button>
                <button
                  type="button"
                  disabled={aiBusy !== null || !question.trim()}
                  onClick={() => void handleAsk("answer")}
                  className="flex items-center gap-1.5 rounded-lg border border-teal-400/40 bg-teal-400/10 px-3 py-2 text-xs text-teal-100 hover:bg-teal-400/20 disabled:opacity-40"
                >
                  {aiBusy === "answer" ? <Loader2 className="animate-spin" size={13} /> : <Sparkles size={13} />} Resposta fundamentada
                </button>
              </div>
            </div>

            {aiError ? (
              <p className="mt-2 rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[11px] text-amber-100">{aiError}</p>
            ) : null}

            {aiContext ? (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap gap-2 text-[11px]">
                  <StatusPill tone="ok">
                    {aiContext.objects.length} {aiContext.objects.length === 1 ? "objeto" : "objetos"}
                  </StatusPill>
                  <StatusPill tone="muted">
                    {aiContext.relations.length} {aiContext.relations.length === 1 ? "relação" : "relações"}
                  </StatusPill>
                  <StatusPill tone="muted">{aiContext.elapsed_ms} ms</StatusPill>
                  {aiContext.mentions.map((mention) => (
                    <StatusPill key={mention} tone="muted">
                      menção: {mention}
                    </StatusPill>
                  ))}
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  {aiContext.objects.map((object) => (
                    <div key={`${object.type}-${object.id}`} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                      <p className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="font-medium">
                          {object.type_label}: {object.label}
                        </span>
                        <span className="text-muted-foreground">{Math.round(object.confidence * 100)}%</span>
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        id {object.id} · {object.matched_on} · menção «{object.mention}»
                      </p>
                    </div>
                  ))}
                  {!aiContext.objects.length ? (
                    <p className="text-[11px] text-muted-foreground">
                      Não foram identificados objetos da ontologia nesta pergunta.
                    </p>
                  ) : null}
                </div>

                {aiContext.relations.length ? (
                  <div className="space-y-1">
                    {aiContext.relations.map((relation, index) => (
                      <p key={`${relation.link}-${index}`} className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11px]">
                        <span className="font-medium">{relation.from.label}</span> {relation.label}{" "}
                        <span className="text-muted-foreground">
                          ({relation.direction === "reverse" ? "inverso" : "direto"} → {relation.to_type_label})
                        </span>
                        : {relation.items.map((item) => item.label).join(", ")}
                      </p>
                    ))}
                  </div>
                ) : null}

                <details className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <summary className="cursor-pointer text-[11px] font-medium">Contexto textual entregue à IA</summary>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-teal-100">{aiContext.grounding}</pre>
                </details>

                {aiContext.suggested_tools.length ? (
                  <p className="text-[10px] text-muted-foreground">
                    Ferramentas sugeridas: {aiContext.suggested_tools.slice(0, 6).join(" · ")}
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          {aiAnswer ? (
            <section className="glass-card rounded-2xl p-4">
              <h3 className="text-sm font-semibold">Resposta fundamentada (sem modelo generativo)</h3>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-xl border border-white/10 bg-black/20 p-3 text-[11px]">
                {aiAnswer.answer}
              </pre>
            </section>
          ) : null}

          <section className="glass-card rounded-2xl p-4">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <ShieldCheck size={14} className="text-teal-300" /> Validação anti-alucinação
            </h3>
            <p className="text-[11px] text-muted-foreground">
              Cola uma resposta (da IA ou escrita à mão) para verificar se as entidades, valores, anos e tickers existem
              nos dados usados como contexto.
            </p>
            <textarea
              value={draftAnswer}
              onChange={(event) => setDraftAnswer(event.target.value)}
              rows={4}
              placeholder="Ex.: A EDP (NIF 503504564) tem 174 contratos e 37,5 M€ em contratos."
              className="glass-card mt-2 w-full rounded-lg border border-white/10 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={!draftAnswer.trim()}
                onClick={() => void handleValidate()}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/10 disabled:opacity-40"
              >
                <ShieldCheck size={13} /> Validar resposta
              </button>
              <button
                type="button"
                disabled={!draftAnswer.trim()}
                onClick={() => setDraftAnswer("")}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/10 disabled:opacity-40"
              >
                Limpar
              </button>
            </div>

            {validation ? (
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  {validation.supported ? (
                    <StatusPill tone="ok">
                      <CheckCircle2 size={11} /> fundamentada
                    </StatusPill>
                  ) : (
                    <StatusPill tone="error">
                      <XCircle size={11} /> entidades não confirmadas
                    </StatusPill>
                  )}
                  <StatusPill tone={validation.score >= 0.9 ? "ok" : validation.score >= 0.6 ? "warn" : "error"}>
                    confiança {(validation.score * 100).toFixed(0)}%
                  </StatusPill>
                </div>
                <ul className="space-y-1">
                  {validation.checks.map((check, index) => (
                    <li key={`${check.kind}-${index}`} className="flex items-start gap-2 text-[11px]">
                      {check.status === "ok" ? (
                        <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-300" />
                      ) : check.status === "aviso" ? (
                        <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-300" />
                      ) : (
                        <XCircle size={13} className="mt-0.5 shrink-0 text-rose-300" />
                      )}
                      <span>
                        <span className="font-medium">{check.kind}</span>
                        {check.value !== null && check.value !== undefined ? ` «${String(check.value)}»` : ""}: {check.message}
                      </span>
                    </li>
                  ))}
                </ul>
                {validation.notes?.length ? (
                  <p className="text-[10px] text-muted-foreground">Notas: {validation.notes.join(" · ")}</p>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="glass-card rounded-2xl p-4">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Wand2 size={14} className="text-teal-300" /> Resolução de entidades
            </h3>
            <p className="text-[11px] text-muted-foreground">
              Mostra como a plataforma interpreta um texto: que objetos canónicos (NIF, nome, ticker) são reconhecidos e
              com que confiança.
            </p>
            <div className="mt-2 flex gap-2">
              <input
                value={resolveText}
                onChange={(event) => setResolveText(event.target.value)}
                placeholder="Ex.: contratos da GALP, NIF 500233810, marcas da SONAE"
                className="glass-card flex-1 rounded-lg border border-white/10 px-3 py-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50"
              />
              <button
                type="button"
                disabled={!resolveText.trim()}
                onClick={() => void handleResolve()}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40"
              >
                <Search size={13} /> Resolver
              </button>
            </div>
            {resolveResult ? (
              <div className="mt-2 space-y-1">
                <p className="text-[10px] text-muted-foreground">Menções: {resolveResult.mentions.join(", ") || "—"}</p>
                {resolveResult.entities.map((entity, index) => (
                  <p key={`${entity.type}-${entity.object._id}-${index}`} className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-[11px]">
                    <span className="font-medium">{entity.type_label}</span>: {String(entity.object._label)}{" "}
                    <span className="text-muted-foreground">
                      ({(entity.confidence * 100).toFixed(0)}% · {entity.matched_on})
                    </span>
                  </p>
                ))}
                {!resolveResult.entities.length ? (
                  <p className="text-[11px] text-muted-foreground">Nenhum objeto canónico reconhecido neste texto.</p>
                ) : null}
                {resolveResult.notes?.length ? (
                  <p className="text-[10px] text-muted-foreground">{resolveResult.notes.join(" · ")}</p>
                ) : null}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
