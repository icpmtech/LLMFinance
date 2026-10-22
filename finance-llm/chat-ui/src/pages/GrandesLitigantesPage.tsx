/**
 * Grandes Litigantes — sociedades com mais de 200 ações, procedimentos ou execuções.
 *
 * Fonte oficial: CITIUS / Portal das Custas Processuais (Portaria 200/2011,
 * artigo 13.º do Regulamento das Custas Processuais). A consulta pública publica
 * apenas a faixa de processos (201-500 ou 501+), nunca o número exato.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Building2,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Gavel,
  Info,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/Tabs";
import {
  downloadGrandesLitigantesCsv,
  faixaLabel,
  getGrandesLitigantesFontes,
  getGrandesLitigantesJob,
  getGrandesLitigantesJobs,
  getGrandesLitigantesMeta,
  getGrandesLitigantesRecolhas,
  getGrandesLitigantesSociedade,
  ingestGrandesLitigantes,
  searchGrandesLitigantes,
  startGrandesLitigantesCollect,
  type GrandeLitigante,
  type GrandesLitigantesFicha,
  type GrandesLitigantesFontesResponse,
  type GrandesLitigantesJob,
  type GrandesLitigantesMeta,
  type GrandesLitigantesRecolha,
  type GrandesLitigantesRecolhas,
  type GrandesLitigantesSearchResult,
} from "../grandesLitigantesApi";

type Aba = "pesquisa" | "sociedade" | "recolhas" | "enquadramento";
type SortBy = "relevancia" | "nome" | "ano" | "faixa" | "nipc";

const PAGE_SIZE = 25;
const POLL_MS = 2500;

const SORTS: { id: SortBy; label: string }[] = [
  { id: "relevancia", label: "Relevância" },
  { id: "nome", label: "Nome (A–Z)" },
  { id: "ano", label: "Ano" },
  { id: "faixa", label: "Faixa" },
  { id: "nipc", label: "NIPC" },
];

function Kpi({
  icon,
  label,
  valor,
  nota,
}: {
  icon: ReactNode;
  label: string;
  valor: string;
  nota?: string;
}) {
  return (
    <Card className="glass-card" padding="md">
      <CardHeader className="items-start">
        <CardTitle icon={icon} className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold">{valor}</p>
        {nota ? <p className="mt-1 text-[11px] text-muted-foreground">{nota}</p> : null}
      </CardContent>
    </Card>
  );
}

function FaixaBadge({ faixa }: { faixa?: string }) {
  const variant = faixa === "501+" ? "danger" : faixa === "201-500" ? "warning" : "default";
  return <Badge variant={variant}>{faixaLabel(faixa)}</Badge>;
}

function RecolhaCard({
  recolha,
  onIngest,
  ingesting,
}: {
  recolha: GrandesLitigantesRecolha;
  onIngest: (r: GrandesLitigantesRecolha) => void;
  ingesting: boolean;
}) {
  return (
    <Card className="glass-card">
      <CardHeader>
        <CardTitle icon={<Activity size={16} className="text-emerald-400" />}>
          {recolha.recolha_id}
        </CardTitle>
        <Button variant="secondary" size="sm" onClick={() => onIngest(recolha)} loading={ingesting}>
          Indexar
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-[11px] text-muted-foreground">Ano(s)</p>
            <p>{recolha.anos.join(", ") || "—"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Registos</p>
            <p>{recolha.registos.toLocaleString("pt-PT")}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Páginas</p>
            <p>{recolha.paginas}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Duração</p>
            <p>{recolha.duracao_ms ? `${(recolha.duracao_ms / 1000).toFixed(1)} s` : "—"}</p>
          </div>
        </div>
        {recolha.json_path ? (
          <p className="text-[11px] text-muted-foreground break-all">{recolha.json_path}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function GrandesLitigantesPage() {
  const [aba, setAba] = useState<Aba>("pesquisa");
  const [meta, setMeta] = useState<GrandesLitigantesMeta | null>(null);
  const [fontes, setFontes] = useState<GrandesLitigantesFontesResponse | null>(null);
  const [resultado, setResultado] = useState<GrandesLitigantesSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [nipc, setNipc] = useState("");
  const [ano, setAno] = useState<string>("");
  const [faixa, setFaixa] = useState<string>("");
  const [sort, setSort] = useState<SortBy>("relevancia");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [submitted, setSubmitted] = useState({
    q: "",
    nipc: "",
    ano: undefined as number | undefined,
    faixa: undefined as string | undefined,
  });

  const [sociedadeNipc, setSociedadeNipc] = useState("");
  const [sociedade, setSociedade] = useState<GrandesLitigantesFicha | null>(null);
  const [sociedadeLoading, setSociedadeLoading] = useState(false);

  const [recolhas, setRecolhas] = useState<GrandesLitigantesRecolhas | null>(null);
  const [jobs, setJobs] = useState<GrandesLitigantesJob[]>([]);
  const [collecting, setCollecting] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [lastJobId, setLastJobId] = useState<string | null>(null);

  const anos = useMemo(() => {
    const lista = meta?.anos ?? resultado?.facets?.ano?.map((f) => f.key) ?? [];
    return lista.slice().sort((a, b) => b - a);
  }, [meta, resultado]);

  const loadMeta = useCallback(async () => {
    try {
      setMeta(await getGrandesLitigantesMeta());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar meta.");
    }
  }, []);

  const loadFontes = useCallback(async () => {
    try {
      setFontes(await getGrandesLitigantesFontes());
    } catch {
      /* fontes é opcional */
    }
  }, []);

  const loadRecolhas = useCallback(async () => {
    try {
      setRecolhas(await getGrandesLitigantesRecolhas());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar recolhas.");
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const data = await getGrandesLitigantesJobs();
      setJobs(data.items ?? []);
    } catch {
      /* jobs são opcional */
    }
  }, []);

  useEffect(() => {
    void loadMeta();
    void loadFontes();
    void loadRecolhas();
    void loadJobs();
  }, [loadMeta, loadFontes, loadRecolhas, loadJobs]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchGrandesLitigantes({
          q: submitted.q || undefined,
          nipc: submitted.nipc || undefined,
          ano: submitted.ano,
          faixa: submitted.faixa ? [submitted.faixa] : undefined,
          sort,
          order,
          page: page + 1,
          size: PAGE_SIZE,
        });
        if (cancelled) return;
        setResultado(data);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Erro na pesquisa.");
        setResultado(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [submitted, sort, order, page]);

  useEffect(() => {
    if (!lastJobId) return;
    const id = window.setInterval(async () => {
      try {
        const job = await getGrandesLitigantesJob(lastJobId);
        setJobs((prev) => {
          const rest = prev.filter((j) => j.job_id !== lastJobId);
          return [job, ...rest].slice(0, 20);
        });
        if (job.status === "done" || job.status === "failed" || job.error) {
          window.clearInterval(id);
          setCollecting(false);
          setLastJobId(null);
          void loadMeta();
          void loadRecolhas();
        }
      } catch {
        window.clearInterval(id);
        setCollecting(false);
        setLastJobId(null);
      }
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [lastJobId, loadMeta, loadRecolhas]);

  const submit = useCallback(() => {
    setPage(0);
    setSubmitted({
      q: q.trim(),
      nipc: nipc.trim(),
      ano: ano ? Number(ano) : undefined,
      faixa: faixa || undefined,
    });
  }, [q, nipc, ano, faixa]);

  const clearFilters = useCallback(() => {
    setQ("");
    setNipc("");
    setAno("");
    setFaixa("");
    setSort("relevancia");
    setOrder("desc");
    setPage(0);
    setSubmitted({ q: "", nipc: "", ano: undefined, faixa: undefined });
  }, []);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((resultado?.total ?? 0) / PAGE_SIZE)),
    [resultado?.total],
  );

  const loadSociedade = useCallback(async () => {
    const n = sociedadeNipc.trim();
    if (!n || !/^\d{9}$/.test(n)) {
      setError("Introduza um NIPC válido (9 dígitos).");
      return;
    }
    setSociedadeLoading(true);
    setError(null);
    try {
      setSociedade(await getGrandesLitigantesSociedade(n));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar sociedade.");
      setSociedade(null);
    } finally {
      setSociedadeLoading(false);
    }
  }, [sociedadeNipc]);

  const handleCollect = useCallback(async () => {
    setCollecting(true);
    setError(null);
    try {
      const job = await startGrandesLitigantesCollect({ indexar: true });
      setLastJobId(job.job_id);
      setJobs((prev) => [job, ...prev].slice(0, 20));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao iniciar recolha.");
      setCollecting(false);
    }
  }, []);

  const handleIngest = useCallback(
    async (recolha: GrandesLitigantesRecolha) => {
      setIngesting(true);
      setError(null);
      try {
        await ingestGrandesLitigantes([recolha.recolha_id]);
        void loadMeta();
        void loadRecolhas();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Falha ao indexar.");
      } finally {
        setIngesting(false);
      }
    },
    [loadMeta, loadRecolhas],
  );

  const handleExport = useCallback(() => {
    void downloadGrandesLitigantesCsv({
      q: submitted.q || undefined,
      nipc: submitted.nipc || undefined,
      ano: submitted.ano,
      faixa: submitted.faixa ? [submitted.faixa] : undefined,
      maximo: 10000,
    });
  }, [submitted]);

  const kpis = useMemo(() => {
    if (resultado?.kpis) return resultado.kpis;
    const indice = meta?.indice;
    if (!indice || indice.error || indice.registos === undefined) return null;
    return {
      registos: indice.registos ?? 0,
      sociedades_distintas: indice.registos ?? 0,
      faixa_201_500: 0,
      faixa_501: 0,
      anos: meta?.anos ?? [],
      ano_mais_recente: meta?.ano_mais_recente,
    };
  }, [resultado?.kpis, meta]);

  return (
    <div className="min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full glass-card px-3 py-1 text-xs text-amber-300">
            <Gavel size={14} />
            Portaria 200/2011
          </div>
          <h1 className="mb-2 flex items-center gap-3 text-3xl font-bold">
            <span className="rounded-2xl border border-white/10 bg-gradient-to-br from-amber-500/20 to-red-500/20 p-2">
              <Building2 size={32} className="text-amber-400" />
            </span>
            Grandes Litigantes
          </h1>
          <p className="max-w-3xl text-muted-foreground">
            Sociedades comerciais que intentaram mais de 200 ações, procedimentos ou execuções num ano civil
            (artigo 13.º do Regulamento das Custas Processuais). A consulta pública apenas publica a faixa de
            processos.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Info size={12} />
            <span>Fonte:</span>
            <a
              href={fontes?.fonte?.url || "https://www.citius.mj.pt/portal/consultas/Custas/Portaria200-2011.aspx"}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200"
            >
              CITIUS <ExternalLink size={11} />
            </a>
            {meta?.indice?.registos !== undefined ? (
              <span className="ml-2 rounded-full border border-white/10 bg-white/5 px-2 py-0.5">
                {meta.indice.registos.toLocaleString("pt-PT")} indexados
              </span>
            ) : null}
          </div>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">
            <div className="flex items-start justify-between gap-3">
              <span>{error}</span>
              <button onClick={() => setError(null)} className="text-red-200 hover:text-white">
                <X size={16} />
              </button>
            </div>
          </div>
        ) : null}

        {kpis ? (
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              icon={<Building2 size={18} />}
              label="Registos"
              valor={(kpis.registos ?? 0).toLocaleString("pt-PT")}
              nota={meta?.index}
            />
            <Kpi
              icon={<Building2 size={18} />}
              label="Sociedades distintas"
              valor={(kpis.sociedades_distintas ?? 0).toLocaleString("pt-PT")}
            />
            <Kpi
              icon={<Gavel size={18} />}
              label="201–500 processos"
              valor={(kpis.faixa_201_500 ?? 0).toLocaleString("pt-PT")}
            />
            <Kpi
              icon={<Gavel size={18} />}
              label="501+ processos"
              valor={(kpis.faixa_501 ?? 0).toLocaleString("pt-PT")}
            />
          </div>
        ) : null}

        <Tabs value={aba} onValueChange={(valor) => setAba(valor as Aba)} className="w-full">
          <TabsList className="mb-4 flex-wrap">
            {(
              [
                ["pesquisa", "Pesquisa"],
                ["sociedade", "Ficha por NIPC"],
                ["recolhas", "Recolhas"],
                ["enquadramento", "Enquadramento"],
              ] as const
            ).map(([valor, label]) => (
              <TabsTrigger key={valor} value={valor} active={aba === valor} onClick={() => setAba(valor)}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="pesquisa" active={aba === "pesquisa"} className="space-y-4">
            <Card className="glass-card">
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <div className="md:col-span-2">
                    <Label className="mb-1.5 block text-xs text-muted-foreground">Denominação / NIPC</Label>
                    <Input
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submit()}
                      placeholder="Nome ou parte do nome"
                    />
                  </div>
                  <div>
                    <Label className="mb-1.5 block text-xs text-muted-foreground">NIPC exacto</Label>
                    <Input
                      value={nipc}
                      onChange={(e) => setNipc(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submit()}
                      placeholder="9 dígitos"
                    />
                  </div>
                  <div>
                    <Label className="mb-1.5 block text-xs text-muted-foreground">Ano</Label>
                    <select
                      value={ano}
                      onChange={(e) => setAno(e.target.value)}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="">Todos</option>
                      {anos.map((a) => (
                        <option key={a} value={a}>
                          {a}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <Label className="mb-1.5 block text-xs text-muted-foreground">Faixa</Label>
                    <select
                      value={faixa}
                      onChange={(e) => setFaixa(e.target.value)}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="">Todas</option>
                      <option value="201-500">Entre 201 e 500</option>
                      <option value="501+">501 ou superior</option>
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={submit} loading={loading} icon={<Search size={16} />}>
                    Pesquisar
                  </Button>
                  <Button variant="outline" onClick={clearFilters} icon={<RefreshCw size={16} />}>
                    Limpar
                  </Button>
                  <Button variant="secondary" onClick={handleCollect} loading={collecting} icon={<Activity size={16} />}>
                    Recolher CITIUS
                  </Button>
                  <Button variant="ghost" onClick={handleExport} icon={<Download size={16} />}>
                    CSV
                  </Button>
                  <div className="ml-auto flex items-center gap-2">
                    <select
                      value={sort}
                      onChange={(e) => setSort(e.target.value as SortBy)}
                      className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      {SORTS.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))}
                      className="rounded-md border border-input px-3 py-2 text-sm hover:bg-accent"
                      title={order === "asc" ? "Ascendente" : "Descendente"}
                    >
                      {order === "asc" ? "↑" : "↓"}
                    </button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {resultado ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
                  <span>
                    {(resultado.total ?? 0).toLocaleString("pt-PT")} resultado{resultado.total !== 1 ? "s" : ""}
                  </span>
                  <span className="text-xs">
                    Página {resultado.page ?? page + 1} / {totalPages}
                  </span>
                </div>

                <div className="overflow-hidden rounded-2xl border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-4 py-3">Denominação</th>
                        <th className="px-4 py-3">NIPC</th>
                        <th className="px-4 py-3">Ano</th>
                        <th className="px-4 py-3">Processos</th>
                        <th className="px-4 py-3">Fonte</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(resultado.items ?? []).map((item: GrandeLitigante) => (
                        <tr key={item.doc_id || `${item.nipc}-${item.ano}`} className="hover:bg-accent/40">
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={() => {
                                setSociedadeNipc(item.nipc);
                                void (async () => {
                                  try {
                                    setSociedadeLoading(true);
                                    setAba("sociedade");
                                    setSociedade(await getGrandesLitigantesSociedade(item.nipc));
                                  } catch (err) {
                                    setError(err instanceof Error ? err.message : "Erro ao abrir sociedade.");
                                  } finally {
                                    setSociedadeLoading(false);
                                  }
                                })();
                              }}
                              className="text-left font-medium text-foreground hover:text-sky-300"
                            >
                              {item.denominacao || "(sem nome)"}
                            </button>
                          </td>
                          <td className="px-4 py-3 font-mono text-xs">{item.nipc}</td>
                          <td className="px-4 py-3">{item.ano}</td>
                          <td className="px-4 py-3">
                            <FaixaBadge faixa={item.faixa} />
                          </td>
                          <td className="px-4 py-3 text-xs text-muted-foreground">
                            {item.fonte_label || item.fonte || "CITIUS"}
                          </td>
                        </tr>
                      ))}
                      {resultado.items?.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                            Nenhum resultado.
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 ? (
                  <div className="flex items-center justify-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                      disabled={page === 0 || loading}
                      className="rounded-xl glass-card px-3 py-2 transition hover:bg-white/5 disabled:opacity-50"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <span className="text-sm text-muted-foreground">
                      Página {page + 1} de {totalPages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                      disabled={page >= totalPages - 1 || loading}
                      className="rounded-xl glass-card px-3 py-2 transition hover:bg-white/5 disabled:opacity-50"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </TabsContent>

          <TabsContent value="sociedade" active={aba === "sociedade"} className="space-y-4">
            <Card className="glass-card">
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="w-full sm:w-72">
                    <Label className="mb-1.5 block text-xs text-muted-foreground">NIPC</Label>
                    <Input
                      value={sociedadeNipc}
                      onChange={(e) => setSociedadeNipc(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && loadSociedade()}
                      placeholder="9 dígitos"
                    />
                  </div>
                  <Button onClick={loadSociedade} loading={sociedadeLoading} icon={<Search size={16} />}>
                    Ficha
                  </Button>
                </div>

                {sociedade ? (
                  <div className="space-y-4 border-t border-border pt-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="text-lg font-semibold">{sociedade.denominacao || "(sem nome)"}</h3>
                        <p className="font-mono text-sm text-muted-foreground">{sociedade.nipc}</p>
                      </div>
                      <Badge variant={sociedade.lista ? "danger" : "secondary"}>
                        {sociedade.lista ? "Consta da lista" : "Não consta da lista"}
                      </Badge>
                    </div>

                    {sociedade.lista ? (
                      <>
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                          <Kpi icon={<Gavel size={16} />} label="Anos em lista" valor={sociedade.anos.length.toString()} />
                          <Kpi icon={<Gavel size={16} />} label="Registos" valor={sociedade.total.toString()} />
                        </div>
                        <div className="overflow-hidden rounded-2xl border border-border">
                          <table className="w-full text-sm">
                            <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                              <tr>
                                <th className="px-4 py-3">Ano</th>
                                <th className="px-4 py-3">Faixa</th>
                                <th className="px-4 py-3">Recolha</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                              {sociedade.items.map((item: GrandeLitigante) => (
                                <tr key={item.doc_id || `${item.nipc}-${item.ano}`}>
                                  <td className="px-4 py-3">{item.ano}</td>
                                  <td className="px-4 py-3">
                                    <FaixaBadge faixa={item.faixa} />
                                  </td>
                                  <td className="px-4 py-3 text-xs text-muted-foreground">
                                    {item.recolha_id || item.collected_at?.slice(0, 10) || "—"}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="recolhas" active={aba === "recolhas"} className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted-foreground">
                {recolhas?.total ?? 0} recolha(s), {recolhas?.registos ?? 0} registo(s)
              </p>
              <div className="flex items-center gap-2">
                <Button onClick={handleCollect} loading={collecting} icon={<Activity size={16} />}>
                  Recolher CITIUS
                </Button>
                <Button variant="outline" onClick={() => void loadRecolhas()} icon={<RefreshCw size={16} />}>
                  Actualizar
                </Button>
              </div>
            </div>

            {jobs.length > 0 ? (
              <Card className="glass-card">
                <CardHeader>
                  <CardTitle icon={<Activity size={16} className="text-emerald-400" />}>Jobs recentes</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {jobs.map((job) => (
                    <div
                      key={job.job_id}
                      className={`rounded-xl border p-3 text-sm ${
                        job.status === "failed"
                          ? "border-red-400/30 bg-red-400/10"
                          : job.status === "done"
                            ? "border-emerald-400/30 bg-emerald-400/10"
                            : "border-border bg-muted/40"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs">{job.job_id}</span>
                        <Badge
                          variant={
                            job.status === "done"
                              ? "success"
                              : job.status === "failed"
                                ? "danger"
                                : job.status === "running"
                                  ? "info"
                                  : "secondary"
                          }
                        >
                          {job.status}
                        </Badge>
                      </div>
                      {job.progress ? (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {job.progress.phase || ""}
                          {job.progress.pagina ? ` · página ${job.progress.pagina}` : ""}
                          {job.progress.registos ? ` · ${job.progress.registos} registos` : ""}
                        </p>
                      ) : null}
                      {job.error ? <p className="mt-1 text-xs text-red-300">{job.error}</p> : null}
                    </div>
                  ))}
                </CardContent>
              </Card>
            ) : null}

            {recolhas?.items?.length ? (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {recolhas.items.map((recolha) => (
                  <RecolhaCard key={recolha.recolha_id} recolha={recolha} onIngest={handleIngest} ingesting={ingesting} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nenhuma recolha encontrada.</p>
            )}
          </TabsContent>

          <TabsContent value="enquadramento" active={aba === "enquadramento"} className="space-y-4">
            <Card className="glass-card">
              <CardHeader>
                <CardTitle icon={<Info size={16} />}>Base legal e notas</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
                <p>
                  <strong>Portaria n.º 200/2011, de 20 de maio</strong> — fixa as taxas de justiça devidas pelas
                  sociedades comerciais que, durante o ano civil anterior, tenham intentado mais de 200 ações,
                  procedimentos ou execuções.
                </p>
                <p>
                  <strong>Artigo 13.º do Regulamento das Custas Processuais</strong> — disponibilização da lista
                  anual das sociedades abrangidas pela majoração.
                </p>
                <p>
                  O portal CITIUS apenas publica duas faixas: <strong>Entre 201 e 500</strong> e{" "}
                  <strong>501 ou superior</strong>. Não é divulgado o número exacto de processos por sociedade.
                </p>
                {fontes?.ligacoes?.length ? (
                  <ul className="list-disc space-y-1 pl-5">
                    {fontes.ligacoes.map((lig: { url: string; label?: string }, i: number) => (
                      <li key={i}>
                        <a href={lig.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:text-sky-200">
                          {lig.label || lig.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {meta?.notes ? <p>{meta.notes}</p> : null}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
