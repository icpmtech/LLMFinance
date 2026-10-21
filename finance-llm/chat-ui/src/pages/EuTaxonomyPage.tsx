/**
 * Módulo **EU Taxonomy Navigator**.
 *
 * Mostra o panorama oficial da Taxonomia Europeia (seis objetivos ambientais,
 * setores e contagens de atividades do Compass), permite pesquisar atividades
 * em inglês e português — com filtro por setor, objetivo e código NACE — e
 * abrir a ficha de cada atividade com a descrição original e a tradução.
 *
 * A recolha (download da API oficial, normalização, índice Elasticsearch e
 * snapshot JSON) e a tradução para PT exigem sessão com permissão de escrita
 * no módulo `eu-taxonomy` (administradores e gestores de plataforma).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  ExternalLink,
  Globe2,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  Sprout,
  Target,
} from "lucide-react";

import { useAuth } from "../auth";
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
import { EmptyState, Loading } from "../components/padroes/padroesKit";

const OBJECTIVE_COLORS: Record<number, string> = {
  41: "#34d399",
  42: "#38bdf8",
  43: "#22d3ee",
  44: "#a78bfa",
  45: "#fbbf24",
  46: "#fb7185",
};

function num(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return new Intl.NumberFormat("pt-PT").format(value);
}

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "sky" | "emerald" | "violet";
}) {
  const tones: Record<string, string> = {
    neutral: "border-white/10 bg-white/5 text-muted-foreground",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function ObjectivePill({ id, label }: { id: number; label?: string }) {
  const cor = OBJECTIVE_COLORS[id] || "#94a3b8";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]"
      style={{ borderColor: `${cor}55`, backgroundColor: `${cor}14`, color: cor }}
      title={label || `Objetivo ${id}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cor }} />
      {id} · {label || "Objetivo"}
    </span>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="glass-card gradient-border rounded-2xl p-4">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="stat-value mt-1 text-xl font-bold md:text-2xl">{value}</p>
      {sub ? <p className="mt-1 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function ActivityCard({ item, onSelect }: { item: EuTaxonomyActivity; onSelect: (id: number) => void }) {
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3
            className="cursor-pointer text-sm font-semibold hover:text-teal-200"
            onClick={() => onSelect(item.activity_id)}
            title="Abrir a ficha da atividade"
          >
            {item.name_pt || item.name_en}
          </h3>
          {item.name_pt && item.name_pt !== item.name_en ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground">{item.name_en}</p>
          ) : null}
        </div>
        <Badge tone="emerald">{item.sector_pt || item.sector_en}</Badge>
      </div>

      {item.description_pt || item.description_en ? (
        <p className="mt-2 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">
          {item.description_pt || item.description_en}
        </p>
      ) : null}

      {(item.objectives?.length ?? 0) > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {item.objectives.map((objetivo) => (
            <ObjectivePill
              key={objetivo.objective_id}
              id={objetivo.objective_id}
              label={objetivo.objective_short_pt || objetivo.objective_short_en}
            />
          ))}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-3">
        {(item.nace_codes?.length ?? 0) > 0 && (
          <span className="font-mono text-[10px] text-muted-foreground">NACE {item.nace_codes.join(", ")}</span>
        )}
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[10px] text-sky-200 hover:text-sky-100"
          >
            Ficha oficial <ExternalLink size={10} />
          </a>
        ) : null}
      </div>
    </article>
  );
}

export default function EuTaxonomyPage() {
  const { user } = useAuth();
  const canWrite = user?.role === "admin" || user?.role === "manager";

  const [panorama, setPanorama] = useState<EuTaxonomyPanorama | null>(null);
  const [status, setStatus] = useState<{
    index: string;
    snapshot_exists: boolean;
    es_available: boolean;
    count?: number;
    error?: string;
  } | null>(null);
  const [results, setResults] = useState<{ total: number; items: EuTaxonomyActivity[] } | null>(null);
  const [selected, setSelected] = useState<EuTaxonomyActivity | null>(null);
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("");
  const [objectiveId, setObjectiveId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  const loadPanorama = useCallback(async () => {
    try {
      setPanorama(await getEuTaxonomyPanorama());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar o panorama da Taxonomia.");
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getEuTaxonomyStatus());
    } catch (err) {
      setStatus({ index: "finance_eu_taxonomy", snapshot_exists: false, es_available: false, error: String(err) });
    }
  }, []);

  useEffect(() => {
    loadPanorama();
    loadStatus();
  }, [loadPanorama, loadStatus]);

  const pesquisar = useCallback(async (termo: string, setorAlvo: string, objetivo: number | undefined) => {
    setLoading(true);
    try {
      const resposta = await searchEuTaxonomy({
        q: termo || undefined,
        kind: "activity",
        sector: setorAlvo || undefined,
        objective_id: objetivo,
        size: 50,
      });
      setResults({
        total: resposta.total,
        items: resposta.items.filter((item) => item.kind === "activity") as EuTaxonomyActivity[],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "A pesquisa falhou.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => pesquisar(q, sector, objectiveId), 250);
    return () => window.clearTimeout(timer);
  }, [q, sector, objectiveId, pesquisar]);

  const setores = useMemo(
    () => (panorama?.sectors || []).map((item) => item.sector_pt || item.sector_en).sort(),
    [panorama],
  );

  const handleColetar = async () => {
    setCollecting(true);
    setError("");
    setAviso("");
    try {
      const resposta = await coletarEuTaxonomy({ force: false, translate: false });
      if (resposta.error) throw new Error(resposta.error);
      setAviso(
        `Recolha concluída: ${num(resposta.totals?.activities)} atividades, ` +
          `${num(resposta.totals?.objectives)} objetivos e ${num(resposta.totals?.sectors)} setores; ` +
          `${num(resposta.index?.indexed_count)} documentos indexados.`,
      );
      await loadPanorama();
      await loadStatus();
      await pesquisar(q, sector, objectiveId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "A recolha falhou.");
    } finally {
      setCollecting(false);
    }
  };

  const handleTraduzir = async () => {
    setTranslating(true);
    setError("");
    setAviso("");
    try {
      const resposta = await traduzirEuTaxonomy({});
      if (resposta.error) throw new Error(resposta.error);
      setAviso(
        `Tradução concluída: ${num(resposta.translated_names)} nomes e ` +
          `${num(resposta.translated_descriptions)} descrições em português.`,
      );
      await loadPanorama();
      await pesquisar(q, sector, objectiveId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "A tradução falhou.");
    } finally {
      setTranslating(false);
    }
  };

  const handleSelecionar = async (activityId: number) => {
    try {
      setSelected(await getEuTaxonomyActivity(activityId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível abrir a atividade.");
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Sprout size={22} className="text-emerald-300" />
            EU Taxonomy Navigator
          </h1>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Atividades, objetivos e setores oficiais do Compass da Comissão Europeia — original em inglês e tradução em
            português.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canWrite ? (
            <>
              <button
                type="button"
                onClick={handleColetar}
                disabled={collecting}
                className="neumorphic-btn flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                {collecting ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Recolher
              </button>
              <button
                type="button"
                onClick={handleTraduzir}
                disabled={translating || !status?.snapshot_exists}
                className="neumorphic-btn flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                {translating ? <Loader2 size={14} className="animate-spin" /> : <Globe2 size={14} />}
                Traduzir PT
              </button>
            </>
          ) : null}
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

      {error ? (
        <div className="mb-4">
          <EmptyState tone="warn">{error}</EmptyState>
        </div>
      ) : null}
      {aviso ? (
        <div className="mb-4">
          <EmptyState>{aviso}</EmptyState>
        </div>
      ) : null}

      {panorama ? (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="Atividades" value={num(panorama.totals.activities)} sub="oficiais do Compass" />
          <Kpi label="Objetivos" value={num(panorama.totals.objectives)} sub="ambientais" />
          <Kpi label="Setores" value={num(panorama.totals.sectors)} sub="económicos" />
          <Kpi
            label="Indexados"
            value={num(status?.count)}
            sub={status?.es_available ? status.index : "Elasticsearch indisponível"}
          />
        </div>
      ) : null}

      {panorama ? (
        <section className="glass-card gradient-border mb-5 rounded-2xl p-5">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Target size={16} className="text-teal-300" />
            Objetivos ambientais
          </h2>
          <div className="flex flex-wrap gap-2">
            {panorama.objectives.map((objetivo) => {
              const ativo = objectiveId === objetivo.id;
              return (
                <button
                  key={objetivo.id}
                  type="button"
                  onClick={() => setObjectiveId(ativo ? undefined : objetivo.id)}
                  className={`rounded-full border px-3 py-1 text-[11px] transition ${
                    ativo ? "border-white/30 bg-white/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                  }`}
                  style={{ color: objetivo.color }}
                  title={objetivo.name_en}
                >
                  <span
                    className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
                    style={{ backgroundColor: objetivo.color }}
                  />
                  {objetivo.id} · {objetivo.name_pt}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="glass-card gradient-border mb-5 rounded-2xl p-5">
        <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Search size={16} className="text-teal-300" />
              Pesquisar atividades
            </h2>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Pesquise por nome (EN/PT), setor, objetivo ambiental ou código NACE/CAE.
            </p>
          </div>
          <select
            value={sector}
            onChange={(event) => setSector(event.target.value)}
            className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs outline-none"
            aria-label="Filtrar por setor"
          >
            <option value="">Todos os setores</option>
            {setores.map((nome) => (
              <option key={nome} value={nome}>
                {nome}
              </option>
            ))}
          </select>
        </header>

        <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2">
          <Search size={14} className="shrink-0 text-muted-foreground" />
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Ex.: afforestation, floresta, energia solar, água…"
            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/60"
          />
          {q ? (
            <button type="button" onClick={() => setQ("")} className="shrink-0 text-muted-foreground hover:text-foreground">
              ×
            </button>
          ) : null}
        </div>

        <div className="mt-3">
          {loading ? (
            <Loading label="A pesquisar no Compass…" />
          ) : results && results.total > 0 ? (
            <>
              <p className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <Layers size={12} />
                {num(results.total)} atividade(s) encontrada(s)
                {objectiveId ? <Badge tone="violet">objetivo {objectiveId}</Badge> : null}
                {sector ? <Badge tone="sky">{sector}</Badge> : null}
              </p>
              <div className="space-y-3">
                {results.items.map((item) => (
                  <ActivityCard key={item.activity_id} item={item} onSelect={handleSelecionar} />
                ))}
              </div>
            </>
          ) : results ? (
            <EmptyState>
              Nenhuma atividade encontrada{q ? ` para «${q}»` : ""}
              {sector ? ` no setor «${sector}»` : ""}. Execute a recolha se o índice estiver vazio.
            </EmptyState>
          ) : null}
        </div>
      </section>

      {selected ? (
        <section className="glass-card gradient-border rounded-2xl p-5">
          <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <BookOpen size={16} className="text-teal-300" />
                {selected.name_pt || selected.name_en}
              </h2>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Atividade {selected.activity_id} · {selected.sector_pt || selected.sector_en}
                {selected.nace_codes?.length ? ` · NACE ${selected.nace_codes.join(", ")}` : ""}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-[11px] text-muted-foreground hover:text-foreground"
            >
              Fechar
            </button>
          </header>

          {(selected.objectives?.length ?? 0) > 0 && (
            <div className="mb-3 flex flex-wrap gap-1">
              {selected.objectives.map((objetivo) => (
                <ObjectivePill
                  key={objetivo.objective_id}
                  id={objetivo.objective_id}
                  label={objetivo.objective_short_pt || objetivo.objective_short_en}
                />
              ))}
            </div>
          )}

          {selected.description_pt ? (
            <div className="mb-3">
              <h3 className="mb-1 text-[11px] font-medium text-foreground">Descrição (português)</h3>
              <p className="text-[12px] leading-relaxed text-foreground">{selected.description_pt}</p>
            </div>
          ) : null}

          <div>
            <h3 className="mb-1 text-[11px] font-medium text-foreground">
              {selected.description_pt ? "Descrição original (inglês)" : "Descrição (inglês)"}
            </h3>
            <p className="text-[12px] leading-relaxed text-muted-foreground">{selected.description_en || "—"}</p>
          </div>

          {selected.url ? (
            <a
              href={selected.url}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
            >
              Ver ficha oficial no EU Taxonomy Navigator <ArrowUpRight size={12} />
            </a>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
