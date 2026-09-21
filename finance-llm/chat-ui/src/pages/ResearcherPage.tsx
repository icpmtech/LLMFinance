/**
 * Investigador de contratação pública — interface para o PublicContractsResearcher.
 */
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Link2,
  Loader2,
  Microscope,
  Network,
  Play,
  Search,
  ShieldCheck,
} from "lucide-react";
const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";

interface ResearchStep {
  iteration: number;
  tool: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  elapsed_ms: number;
  evidence_added: number;
}

interface Evidence {
  source_id: string;
  source_type: string;
  fact: string;
  confidence: number;
}

interface Entity {
  nif?: string;
  nome?: string;
  role?: string;
}

interface Relationship {
  entity?: string;
  nif?: string;
  contracts?: number;
  value?: number;
}

interface ResearchResult {
  status: string;
  report?: string;
  iterations?: number;
  tool_calls?: number;
  elapsed_seconds?: number;
  entities?: Entity[];
  relationships?: Relationship[];
  evidence?: Evidence[];
  steps?: ResearchStep[];
  warnings?: string[];
  message?: string;
}

const TOOL_COLORS: Record<string, string> = {
  search_contracts: "bg-blue-500/20 text-blue-300",
  get_company: "bg-emerald-500/20 text-emerald-300",
  aggregate_contracts: "bg-purple-500/20 text-purple-300",
  find_relationships: "bg-amber-500/20 text-amber-300",
};

export function ResearcherPage() {
  const [query, setQuery] = useState(
    "Investiga a relação entre a EDP e contratos de software no distrito do Porto entre 2022 e 2026",
  );
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openSteps, setOpenSteps] = useState(false);
  const [openEvidence, setOpenEvidence] = useState(false);
  const reportRef = useRef<HTMLDivElement | null>(null);

  const runInvestigation = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/researcher/investigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query }),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ResearchResult;
      if (data.status === "error") {
        setError(data.message || "Erro desconhecido");
      } else {
        setResult(data);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (result?.report && reportRef.current) {
      reportRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result?.report]);

  return (
    <div className="h-full w-full overflow-y-auto bg-background p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-gradient-to-br from-zinc-800 via-zinc-900 to-black p-3 text-white shadow">
            <Microscope size={28} />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              Investigador de Contratação Pública
            </h1>
            <p className="text-sm text-muted-foreground">
              Pesquisa iterativa sobre contratos, entidades, CPV, locais e relações adjudicantes/adjudicatários.
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
          <label className="mb-2 block text-sm font-medium text-card-foreground">
            Pergunta de investigação
          </label>
          <div className="flex flex-col gap-3 md:flex-row">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={3}
              className="flex-1 rounded-xl border border-border bg-muted p-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="Ex: Investiga a relação entre a EDP e contratos de software no distrito do Porto entre 2022 e 2026"
            />
            <button
              onClick={runInvestigation}
              disabled={loading || !query.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground shadow hover:opacity-90 disabled:opacity-60"
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
              {loading ? "A investigar…" : "Investigar"}
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive">
            <AlertTriangle size={20} />
            <p className="text-sm">{error}</p>
          </div>
        )}

        {result && (
          <div ref={reportRef} className="space-y-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                icon={<CheckCircle2 size={18} />}
                label="Iterações"
                value={result.iterations ?? 0}
              />
              <StatCard
                icon={<Search size={18} />}
                label="Chamadas a ferramentas"
                value={result.tool_calls ?? 0}
              />
              <StatCard
                icon={<ShieldCheck size={18} />}
                label="Entidades identificadas"
                value={result.entities?.length ?? 0}
              />
              <StatCard
                icon={<Link2 size={18} />}
                label="Relações encontradas"
                value={result.relationships?.length ?? 0}
              />
            </div>

            <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
              <div className="mb-4 flex items-center gap-2 text-card-foreground">
                <FileText size={20} />
                <h2 className="text-lg font-semibold">Relatório</h2>
              </div>
              <article className="prose prose-invert max-w-none text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.report}</ReactMarkdown>
              </article>
            </div>

            {result.warnings && result.warnings.length > 0 && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200">
                <div className="mb-2 flex items-center gap-2 text-amber-300">
                  <AlertTriangle size={18} />
                  <span className="font-semibold">Avisos</span>
                </div>
                <ul className="list-disc space-y-1 pl-5 text-sm text-amber-100">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            <Collapsible open={openSteps} onToggle={setOpenSteps} label="Passos de investigação">
              <div className="space-y-2">
                {result.steps?.map((s) => (
                  <div
                    key={s.iteration}
                    className="rounded-xl border border-border bg-muted p-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            TOOL_COLORS[s.tool] || "bg-muted-foreground/20 text-muted-foreground"
                          }`}
                        >
                          {s.tool}
                        </span>
                        <span className="text-xs text-muted-foreground">#{s.iteration}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">{s.elapsed_ms} ms</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {JSON.stringify(s.arguments)}
                    </p>
                    <p className="mt-1 text-xs text-foreground">-&gt; {s.result_summary}</p>
                  </div>
                ))}
              </div>
            </Collapsible>

            <Collapsible open={openEvidence} onToggle={setOpenEvidence} label="Evidências recolhidas">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {result.evidence?.map((e, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-border bg-muted p-3 text-xs"
                  >
                    <div className="flex items-center justify-between text-muted-foreground">
                      <span>{e.source_type}</span>
                      <span>confiança {e.confidence}</span>
                    </div>
                    <p className="mt-1 text-foreground">{e.fact}</p>
                    <p className="mt-1 text-muted-foreground">{e.source_id}</p>
                  </div>
                ))}
              </div>
            </Collapsible>

            {result.relationships && result.relationships.length > 0 && (
              <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                <div className="mb-3 flex items-center gap-2 text-card-foreground">
                  <Network size={18} />
                  <h3 className="font-semibold">Relações</h3>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {result.relationships.slice(0, 12).map((r, i) => (
                    <div
                      key={i}
                      className="rounded-xl border border-border bg-muted p-3"
                    >
                      <p className="text-sm font-medium text-foreground">{r.entity}</p>
                      <p className="text-xs text-muted-foreground">NIF {r.nif}</p>
                      <p className="mt-1 text-xs text-card-foreground">
                        {r.contracts} contratos • {r.value?.toLocaleString("pt-PT")} €
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4">
      <div className="text-muted-foreground">{icon}</div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-xl font-bold text-foreground">{value}</p>
      </div>
    </div>
  );
}

function Collapsible({
  open,
  onToggle,
  label,
  children,
}: {
  open: boolean;
  onToggle: (v: boolean) => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <button
        onClick={() => onToggle(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="font-semibold text-foreground">{label}</span>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

export default ResearcherPage;
