/**
 * Página do módulo **EU Taxonomy Navigator**.
 *
 * Mostra o panorama oficial da Taxonomia UE (objetivos, setores, contagens),
 * permite pesquisar atividades em inglês e português, filtrar por setor,
 * objetivo e NACE, e acionar a recolha/tradução para administradores.
 */
import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Globe2,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  Sprout,
  Target,
} from "lucide-react";

import {
  Chip,
  EmptyState,
  Kpi,
  Loading,
  SearchInput,
  SectionCard,
} from "../components/padroes/padroesKit";
import { useAuth } from "../auth";
import { useToast } from "../toast";
import {
  coletarEuTaxonomy,
  getEuTaxonomyActivity,
  getEuTaxonomyPanorama,
  getEuTaxonomyStatus,
  searchEuTaxonomy,
  traduzirEuTaxonomy,
  type EuTaxonomyActivity,
  type EuTaxonomyPanorama,
} from "../euTaxonomyApi";

const OBJECTIVE_COLORS: Record<number, string> = {
  41: "#34d399",
  42: "#38bdf8",
  43: "#22d3ee",
  44: "#a78bfa",
  45: "#fbbf24",
  46: "#fb7185",
};

function ObjectivePill({ id, label }: { id: number; label?: string }) {
  const cor = OBJECTIVE_COLORS[id] || "#94a3b8";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px]"
      style={{ borderColor: `${cor}55`, backgroundColor: `${cor}14`, color: cor }}
      title={label || `Objetivo ${id}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cor }} />
      {id} · {label || "Objetivo"}
    </span>
  );
}

function ActivityRow({
  item,
  onSelect,
}: {
  item: EuTaxonomyActivity;
  onSelect: (id: number) => void;
}) {
  const name = item.name_pt || item.name_en;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3 hover:border-white/20">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="cursor-pointer text-sm font-medium hover:text-teal-300" onClick={() => onSelect(item.activity_id)}>
            {name}
          </h3>
          {item.name_pt && item.name_en !== item.name_pt && (
            <p className="text-[11px] text-muted-foreground">{item.name_en}</p>
          )}
        </div>
        <Chip tone="teal">{item.sector_pt || item.sector_en}</Chip>
      </div>
      {item.description_pt || item.description_en ? (
        <p className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">
          {item.description_pt || item.description_en}
        </p>
      ) : null}
      {item.objectives?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {item.objectives.map((obj) => (
            <ObjectivePill key={obj.objective_id} id={obj.objective_id} label={obj.objective_short_pt || obj.objective_short_en} />
          ))}
        </div>
      )}
      {item.nace_codes?.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {item.nace_codes.map((nace) => (
            <span key={nace} className="font-mono text-[10px] text-muted-foreground">{nace}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EuTaxonomyPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const isAdmin = user?.role === "admin" || user?.role === "manager";

  const [panorama, setPanorama] = useState<EuTaxonomyPanorama | null>(null);
  const [status, setStatus] = useState<{ snapshot_exists: boolean; count?: number; es_available?: boolean } | null>(null);
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("");
  const [objectiveId, setObjectiveId] = useState<number | undefined>(undefined);
  const [results, setResults] = useState<{ total: number; items: EuTaxonomyActivity[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [selected, setSelected] = useState<EuTaxonomyActivity | null>(null);

  const loadPanorama = async () => {
    try {
      const data = await getEuTaxonomyPanorama();
      setPanorama(data);
    } catch (error) {
      toast({ message: String(error), tone: "error" });
    }
  };

  const loadStatus = async () => {
    try {
      const data = await getEuTaxonomyStatus();
      setStatus(data);
    } catch {
      setStatus({ snapshot_exists: false });
    }
  };

  useEffect(() => {
    loadPanorama();
    loadStatus();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchEuTaxonomy({
          q: q || undefined,
          kind: "activity",
          sector: sector || undefined,
          objective_id: objectiveId,
          size: 50,
        });
        setResults({
          total: data.total,
          items: data.items.filter((it) => it.kind === "activity") as EuTaxonomyActivity[],
        });
      } catch (error) {
        toast({ message: String(error), tone: "error" });
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, sector, objectiveId]);

  const sectors = useMemo(
    () => (panorama?.sectors || []).map((s) => s.sector_pt || s.sector_en).sort(),
    [panorama],
  );

  const handleCollect = async () => {
    setCollecting(true);
    try {
      const data = await coletarEuTaxonomy({ force: false, translate: false });
      if (data.error) throw new Error(data.error);
      toast({
        message: `Recolhidos ${data.totals?.activities || 0} itens e indexados ${data.index?.indexed_count || 0}.`,
        tone: "success",
      });
      await loadPanorama();
      await loadStatus();
      const search = await searchEuTaxonomy({ kind: "activity", size: 50 });
      setResults({ total: search.total, items: search.items as EuTaxonomyActivity[] });
    } catch (error) {
      toast({ message: String(error), tone: "error" });
    } finally {
      setCollecting(false);
    }
  };

  const handleTranslate = async () => {
    setTranslating(true);
    try {
      const data = await traduzirEuTaxonomy({});
      if (data.error) throw new Error(data.error);
      toast({
        message: `Traduzidos ${data.translated_names || 0} nomes e ${data.translated_descriptions || 0} descrições.`,
        tone: "success",
      });
      await loadPanorama();
      const search = await searchEuTaxonomy({ kind: "activity", size: 50 });
      setResults({ total: search.total, items: search.items as EuTaxonomyActivity[] });
    } catch (error) {
      toast({ message: String(error), tone: "error" });
    } finally {
      setTranslating(false);
    }
  };

  const handleSelect = async (id: number) => {
    try {
      const data = await getEuTaxonomyActivity(id);
      setSelected(data);
    } catch (error) {
      toast({ message: String(error), tone: "error" });
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Sprout size={22} className="text-emerald-400" />
            EU Taxonomy Navigator
          </h1>
          <p className="text-[11px] text-muted-foreground">
            Atividades, objetivos e setores oficiais do Compass da Comissão Europeia.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <>
              <button
                onClick={handleCollect}
                disabled={collecting}
                className="neumorphic-btn flex items-center gap-1.5 text-xs"
              >
                {collecting ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Recolher
              </button>
              <button
                onClick={handleTranslate}
                disabled={translating || !status?.snapshot_exists}
                className="neumorphic-btn flex items-center gap-1.5 text-xs"
              >
                {translating ? <Loader2 size={14} className="animate-spin" /> : <Globe2 size={14} />}
                Traduzir PT
              </button>
            </>
          )}
          <a
            href="https://ec.europa.eu/sustainable-finance-taxonomy/home"
            target="_blank"
            rel="noreferrer"
            className="neumorphic-btn flex items-center gap-1.5 text-xs"
          >
            <BookOpen size={14} />
            Fonte oficial
          </a>
        </div>
      </header>

      {panorama && (
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi icon={Layers} label="Atividades" value={String(panorama.totals.activities)} sub="oficiais do Compass" />
          <Kpi icon={Target} label="Objetivos" value={String(panorama.totals.objectives)} sub="ambientais" />
          <Kpi icon={Globe2} label="Setores" value={String(panorama.totals.sectors)} sub="económicos" />
          <Kpi icon={Search} label="Indexados" value={String(status?.count ?? "—")} sub={status?.es_available ? "Elasticsearch" : "indisponível"} />
        </div>
      )}

      {panorama && (
        <SectionCard title="Objetivos ambientais" subtitle="Os seis objetivos do Regulamento (UE) 2020/852" icon={Target}>
          <div className="flex flex-wrap gap-2">
            {panorama.objectives.map((obj) => (
              <button
                key={obj.id}
                onClick={() => setObjectiveId(objectiveId === obj.id ? undefined : obj.id)}
                className={`rounded-full border px-3 py-1 text-[11px] transition ${
                  objectiveId === obj.id ? "border-white/30 bg-white/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                }`}
                style={{ color: obj.color }}
              >
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: obj.color }} />
                {obj.id} · {obj.name_pt}
              </button>
            ))}
          </div>
        </SectionCard>
      )}

      <SectionCard
        title="Pesquisar atividades"
        subtitle="Pesquise por nome (EN/PT), setor, objetivo ou NACE"
        icon={Search}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs outline-none"
            >
              <option value="">Todos os setores</option>
              {sectors.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            {objectiveId && (
              <Chip tone="teal">
                Objetivo {objectiveId}
                <button onClick={() => setObjectiveId(undefined)} className="ml-1">×</button>
              </Chip>
            )}
          </div>
        }
      >
        <SearchInput value={q} onChange={setQ} placeholder="Ex.: afforestation, floresta, energia solar..." />

        {loading && <Loading label="A pesquisar..." />}

        {!loading && results && results.total === 0 && (
          <EmptyState tone="info">Nenhuma atividade encontrada para «{q || "(vazio)"}».</EmptyState>
        )}

        {!loading && results && results.total > 0 && (
          <div className="mt-4 space-y-3">
            <p className="text-[11px] text-muted-foreground">{results.total} resultado(s)</p>
            {results.items.map((item) => (
              <ActivityRow key={item.activity_id} item={item} onSelect={handleSelect} />
            ))}
          </div>
        )}
      </SectionCard>

      {selected && (
        <SectionCard title={selected.name_pt || selected.name_en} subtitle={selected.sector_pt || selected.sector_en} icon={BookOpen}>
          <div className="space-y-3">
            <p className="text-[11px] text-muted-foreground">ID: {selected.activity_id} · NACE: {selected.nace_codes.join(", ") || "—"}</p>
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <h4 className="mb-1 text-[11px] font-medium">Descrição (PT)</h4>
              <p className="text-[12px] leading-relaxed text-foreground">{selected.description_pt || selected.description_en}</p>
              {selected.description_pt && selected.description_en !== selected.description_pt && (
                <>
                  <h4 className="mb-1 mt-3 text-[11px] font-medium">Descrição original (EN)</h4>
                  <p className="text-[12px] leading-relaxed text-muted-foreground">{selected.description_en}</p>
                </>
              )}
            </div>
            {selected.objectives?.length > 0 && (
              <div>
                <h4 className="mb-1 text-[11px] font-medium">Objetivos</h4>
                <div className="flex flex-wrap gap-1">
                  {selected.objectives.map((obj) => (
                    <ObjectivePill key={obj.objective_id} id={obj.objective_id} label={obj.objective_short_pt || obj.objective_short_en} />
                  ))}
                </div>
              </div>
            )}
            <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-sky-300 hover:underline">
              Ver ficha oficial <ArrowUpRight size={12} />
            </a>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
