/**
 * Página de pesquisa de políticos de Portugal.
 *
 * Consolida deputados do Parlamento.pt e políticos da Wikipédia PT num único
 * motor de pesquisa. Cada cartão mostra foto, nome, fonte, partido e resumo,
 * com ligação para a ficha no PessoasIQ (incluindo grafo de relações).
 */
import {
  ExternalLink,
  Filter,
  Globe,
  Image as ImageIcon,
  Landmark,
  Loader2,
  PersonStanding,
  Search,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE,
  enrichPolitician,
  getPersonGraph,
  getPoliticianGraph,
  getPoliticianPartyNews,
  getPoliticianProfile,
  searchPeople,
} from "../api";
import { Card, EmptyState, Loading, openGraphWindow } from "../components/people/peopleKit";
import type { PeopleGraphResponse, PeopleSearchResponse, Person, PoliticianProfile } from "../types";

// ---------------------------------------------------------------------------
// Tipos e constantes
// ---------------------------------------------------------------------------

type SourceFilter = "all" | "deputados" | "wikipedia";
type PoliticianSort = "relevance" | "name";

const POLITICOS_TAG = "politicos-portugal";

const SOURCE_OPTS: { key: SourceFilter; label: string; icon: React.ElementType }[] = [
  { key: "all", label: "Todas as fontes", icon: Users },
  { key: "deputados", label: "Deputados (Parlamento/CNN/Público)", icon: Landmark },
  { key: "wikipedia", label: "Políticos (Wikipédia)", icon: Globe },
];

const SORT_OPTS: { key: PoliticianSort; label: string }[] = [
  { key: "relevance", label: "Mais relevantes" },
  { key: "name", label: "Nome (A-Z)" },
];

const PAGE_SIZE = 24;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function normalizeParty(party?: string | null): string | null {
  if (!party) return null;
  const p = party.trim();
  return p.length > 0 && p !== "—" ? p : null;
}

function personPhotoUrl(person: Person): string | null {
  // Preferir caminho local servido pelo backend; fallback para URL absoluta.
  const localPath = (person as any).photo_path || (person as any).metadata?.photo_path;
  if (localPath) {
    return `${API_BASE.replace(/\/$/, "")}/${localPath.replace(/^data\//, "data/")}`;
  }
  const external = (person as any).photo_url;
  if (external && typeof external === "string" && !external.includes("parlamento.pt")) {
    return external;
  }
  return null;
}

function personSummary(person: Person): string | null {
  return (person as any).biography || (person as any).summary || (person as any).metadata?.summary || null;
}

function personSourceLabel(person: Person): string {
  const src = person.source || "";
  if (src.includes("parlamento")) return "Parlamento.pt";
  if (src.includes("wikipedia") || src.includes("wiki")) return "Wikipédia";
  return src || "—";
}

function personExternalUrl(person: Person): string | null {
  const meta = (person as any).metadata || {};
  return meta.wiki_url || meta.url_biografia || person.source || null;
}

// ---------------------------------------------------------------------------
// Componentes UI
// ---------------------------------------------------------------------------

/** Cartão de político com foto, identificação e metadados. */
function PoliticianCard({
  person,
  onOpenDetail,
}: {
  person: Person;
  onOpenDetail: (person: Person) => void;
}) {
  const photoUrl = personPhotoUrl(person);
  const party = normalizeParty((person as any).metadata?.party || (person as any).party);
  const summary = personSummary(person);
  const source = personSourceLabel(person);
  const external = personExternalUrl(person);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl border border-white/10 bg-white/[0.04]">
          {photoUrl ? (
            <img
              src={photoUrl}
              alt={person.name}
              loading="lazy"
              className="h-full w-full object-cover object-top"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-muted-foreground">
              <ImageIcon size={24} />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-foreground">{person.name}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="truncate">{source}</span>
            {party && (
              <>
                <span>·</span>
                <span className="truncate text-amber-200">{party}</span>
              </>
            )}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">NIF {person.nif}</p>
        </div>
      </div>

      {summary && (
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
          {summary.slice(0, 260).replace(/\s+/g, " ")}
          {summary.length > 260 ? "…" : ""}
        </p>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          onClick={() => onOpenDetail(person)}
          className="inline-flex min-h-[32px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.06] px-3 py-1.5 text-xs text-foreground transition hover:bg-white/[0.10]"
        >
          <PersonStanding size={14} /> Ficha
        </button>
        {external && (
          <a
            href={external}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-[32px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-muted-foreground transition hover:bg-white/[0.08]"
          >
            <ExternalLink size={14} /> Fonte
          </a>
        )}
      </div>
    </Card>
  );
}

/** Perfil político enriquecido: técnico, biográfico, notícias e grafo. */
function usePoliticianProfile(_person: Person | null) {
  const [profile, setProfile] = useState<PoliticianProfile | null>(null);
  const [partyNews, setPartyNews] = useState<{ total: number; items: any[]; warnings?: string[] } | null>(null);
  const [politicalGraph, setPoliticalGraph] = useState<PeopleGraphResponse | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [newsLoading, setNewsLoading] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"summary" | "technical" | "biography" | "news" | "graph">("summary");
  const [error, setError] = useState<string | null>(null);

  const loadProfile = useCallback(async (nif: string) => {
    setProfileLoading(true);
    setError(null);
    try {
      const [p, news, graph] = await Promise.all([
        getPoliticianProfile(nif, { reuseHours: 24 }).catch(() => null),
        getPoliticianPartyNews(nif, 12).catch(() => ({ party: null, total: 0, items: [], warnings: [] })),
        getPoliticianGraph(nif, { maxCoParty: 20, limitPartyNews: 12 }).catch(() => null),
      ]);
      setProfile(p);
      setPartyNews(news as any);
      setPoliticalGraph(graph);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar perfil político");
    } finally {
      setProfileLoading(false);
      setNewsLoading(false);
      setGraphLoading(false);
    }
  }, []);

  const enrich = useCallback(async (nif: string, backend?: string) => {
    setProfileLoading(true);
    setError(null);
    try {
      const p = await enrichPolitician(nif, { backend, save: true, reuseHours: 0 });
      setProfile(p);
      const news = await getPoliticianPartyNews(nif, 12).catch(() => ({ party: null, total: 0, items: [], warnings: [] }));
      const graph = await getPoliticianGraph(nif, { maxCoParty: 20, limitPartyNews: 12 }).catch(() => null);
      setPartyNews(news as any);
      setPoliticalGraph(graph);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao enriquecer perfil político");
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setProfile(null);
    setPartyNews(null);
    setPoliticalGraph(null);
    setError(null);
    setActiveTab("summary");
  }, []);

  return {
    profile,
    partyNews,
    politicalGraph,
    profileLoading,
    newsLoading,
    graphLoading,
    activeTab,
    setActiveTab,
    error,
    loadProfile,
    enrich,
    reset,
  };
}

function ProfileTextBlock({
  title,
  mode,
  text,
  notes,
  warnings,
}: {
  title: string;
  mode?: string | null;
  text?: string | null;
  notes?: string[];
  warnings?: string[];
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
        {mode && <span className="text-[10px] text-amber-200">{mode}</span>}
      </div>
      {text ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs leading-relaxed text-foreground">
          {text}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Sem conteúdo gerado.</p>
      )}
      {notes && notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-4 text-[11px] text-muted-foreground">
          {notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {warnings && warnings.length > 0 && (
        <ul className="list-disc space-y-1 pl-4 text-[11px] text-rose-300">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Painel lateral com detalhe do político e grafo de relações. */
function PoliticianDetailPanel({
  person,
  graph,
  graphLoading,
  onClose,
}: {
  person: Person;
  graph: PeopleGraphResponse | null;
  graphLoading: boolean;
  onClose: () => void;
}) {
  const {
    profile,
    partyNews,
    politicalGraph,
    profileLoading,
    activeTab,
    setActiveTab,
    error,
    loadProfile,
    enrich,
  } = usePoliticianProfile(person);

  useEffect(() => {
    void loadProfile(person.nif);
  }, [person.nif, loadProfile]);

  const photoUrl = personPhotoUrl(person);
  const party = normalizeParty((person as any).metadata?.party || (person as any).party);
  const office = (person as any).metadata?.office || (person as any).office || null;
  const term = (person as any).metadata?.term || (person as any).term || null;
  const birthDate = (person as any).metadata?.birth_date || (person as any).birth_date || null;
  const nationality = (person as any).metadata?.nationality || (person as any).nationality || null;
  const occupation = (person as any).metadata?.occupation || (person as any).occupation || null;
  const summary = personSummary(person);
  const external = personExternalUrl(person);

  const tabs: { key: typeof activeTab; label: string }[] = [
    { key: "summary", label: "Resumo" },
    { key: "technical", label: "Perfil técnico" },
    { key: "biography", label: "Biografia" },
    { key: "news", label: `Notícias ${partyNews && partyNews.total > 0 ? `(${partyNews.total})` : ""}` },
    { key: "graph", label: "Grafo político" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-xl border border-white/10 bg-white/[0.04]">
          {photoUrl ? (
            <img
              src={photoUrl}
              alt={person.name}
              className="h-full w-full object-cover object-top"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-muted-foreground">
              <ImageIcon size={28} />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h2 className="text-lg font-bold leading-tight text-foreground">{person.name}</h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-white/10 p-1.5 text-muted-foreground transition hover:text-foreground"
              aria-label="Fechar"
            >
              <X size={16} />
            </button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">NIF {person.nif}</p>
          <p className="mt-1 text-xs text-amber-200">{personSourceLabel(person)}</p>
        </div>
      </div>

      {(party || office || term || birthDate || nationality || occupation) && (
        <div className="space-y-1.5 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
          {party && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Partido:</span>
              <span className="font-medium text-foreground">{party}</span>
            </p>
          )}
          {office && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Cargo:</span>
              <span className="font-medium text-foreground">{office}</span>
            </p>
          )}
          {term && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Mandato:</span>
              <span className="font-medium text-foreground">{term}</span>
            </p>
          )}
          {birthDate && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Nascimento:</span>
              <span className="font-medium text-foreground">{birthDate}</span>
            </p>
          )}
          {nationality && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Nacionalidade:</span>
              <span className="font-medium text-foreground">{nationality}</span>
            </p>
          )}
          {occupation && (
            <p className="flex items-start gap-2">
              <span className="text-muted-foreground">Profissão:</span>
              <span className="font-medium text-foreground">{occupation}</span>
            </p>
          )}
        </div>
      )}

      {summary && (
        <div className="text-xs leading-relaxed text-muted-foreground">
          <p>{summary.slice(0, 600).replace(/\s+/g, " ")}</p>
          {summary.length > 600 && <p className="mt-1 italic">…</p>}
        </div>
      )}

      {external && (
        <a
          href={external}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-teal-300 hover:underline"
        >
          <ExternalLink size={13} /> Abrir página da fonte
        </a>
      )}

      <div className="flex items-center justify-between border-t border-white/10 pt-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <Users size={16} className="text-rose-300" /> Enriquecimento político
        </h3>
        <button
          type="button"
          onClick={() => void enrich(person.nif)}
          disabled={profileLoading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.06] px-2.5 py-1 text-[11px] text-foreground transition hover:bg-white/[0.10] disabled:opacity-50"
        >
          {profileLoading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {profileLoading ? "A gerar…" : "Gerar / atualizar"}
        </button>
      </div>
      {error && <p className="text-xs text-rose-300">{error}</p>}

      <div className="flex flex-wrap gap-1.5">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={[
              "rounded-lg border px-2.5 py-1.5 text-[11px] transition",
              activeTab === t.key
                ? "border-rose-400/30 bg-rose-400/15 text-rose-200"
                : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "summary" && (
        <div className="space-y-3 text-xs text-muted-foreground">
          <p>
            {profile
              ? `Perfil político gerado em ${profile.generated_at || "—"} com ${profile.evidence_count} evidências.`
              : "Seleciona um separador ou clica em \"Gerar / atualizar\" para produzir o perfil político com IA."}
          </p>
          {profile?.party && (
            <p>
              Partido indexado: <span className="text-foreground">{profile.party}</span>
            </p>
          )}
          {profile?.cached && <p className="text-amber-200">Resultado reaproveitado do cache.</p>}
          {profile?.technical_profile?.text && (
            <ProfileTextBlock title="Destaques técnicos" text={profile.technical_profile.text.slice(0, 320) + "…"} />
          )}
          {profile?.biographical_profile?.text && (
            <ProfileTextBlock title="Destaques biográficos" text={profile.biographical_profile.text.slice(0, 320) + "…"} />
          )}
        </div>
      )}

      {activeTab === "technical" && (
        <ProfileTextBlock
          title="Perfil técnico"
          mode={profile?.technical_profile?.mode}
          text={profile?.technical_profile?.text}
          notes={profile?.technical_profile?.notes}
          warnings={profile?.technical_profile?.warnings}
        />
      )}

      {activeTab === "biography" && (
        <ProfileTextBlock
          title="Perfil biográfico"
          mode={profile?.biographical_profile?.mode}
          text={profile?.biographical_profile?.text}
          notes={profile?.biographical_profile?.notes}
          warnings={profile?.biographical_profile?.warnings}
        />
      )}

      {activeTab === "news" && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Notícias do partido {party ? `· ${party}` : ""}
          </h4>
          {!partyNews || partyNews.total === 0 ? (
            <p className="text-xs text-muted-foreground">Sem notícias de partido para este político.</p>
          ) : (
            <div className="grid gap-2">
              {partyNews.items.slice(0, 12).map((item: any, idx: number) => (
                <div key={idx} className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                  <p className="text-xs font-medium text-foreground">{item.title || item.name || "Sem título"}</p>
                  {item.snippet && <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{item.snippet}</p>}
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                    {item.source && <span>{item.source}</span>}
                    {item.date && <span>{item.date}</span>}
                    {item.url && (
                      <a href={item.url} target="_blank" rel="noreferrer" className="text-teal-300 hover:underline">
                        Abrir
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {partyNews?.warnings && partyNews.warnings.length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-[11px] text-rose-300">
              {partyNews.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeTab === "graph" && (
        <div className="space-y-3">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Grafo político</h4>
            <button
              type="button"
              onClick={() => openGraphWindow("person", person.nif, person.name)}
              className="text-[11px] text-teal-300 hover:underline"
            >
              Abrir em janela
            </button>
          </div>
          {graphLoading && <Loading message="A carregar grafo…" />}
          {!graphLoading && graph && graph.node_count === 0 && (
            <p className="text-xs text-muted-foreground">Sem relações indexadas para este político.</p>
          )}
          {!graphLoading && graph && graph.node_count > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {graph.node_count} nós · {graph.edge_count} arestas
              </p>
              <div className="grid gap-2">
                {graph.nodes.slice(0, 12).map((node) => (
                  <div
                    key={node.id}
                    className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: (node as any).kind === "party" ? "#fbbf24" : (node as any).kind === "office" ? "#a78bfa" : "#fb7185" }}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs text-foreground">{node.label}</span>
                    <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{(node as any).kind || node.type}</span>
                  </div>
                ))}
              </div>
              {graph.edges.length > 0 && (
                <div className="mt-2 space-y-1">
                  {graph.edges.slice(0, 8).map((edge, idx) => (
                    <p key={idx} className="text-[11px] text-muted-foreground">
                      <span className="text-foreground">{(edge as any).source_name || edge.source}</span>
                      <span className="mx-1 text-teal-300">→</span>
                      <span className="text-foreground">{(edge as any).target_name || edge.target}</span>
                      {(edge as any).relation_label && <span className="ml-1 text-muted-foreground">({(edge as any).relation_label})</span>}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
          {politicalGraph && politicalGraph.node_count > 0 && (
            <div className="border-t border-white/10 pt-2">
              <p className="mb-2 text-xs font-medium text-foreground">Grafo político enriquecido</p>
              <p className="text-xs text-muted-foreground">
                {politicalGraph.node_count} nós · {politicalGraph.edge_count} arestas
              </p>
              <div className="mt-2 grid gap-2">
                {politicalGraph.nodes.slice(0, 10).map((node) => (
                  <div
                    key={`p-${node.id}`}
                    className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2"
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: (node as any).kind === "party" ? "#fbbf24" : (node as any).kind === "office" ? "#a78bfa" : "#fb7185" }}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs text-foreground">{node.label}</span>
                    <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{(node as any).kind || node.type}</span>
                  </div>
                ))}
              </div>
              {politicalGraph.edges.length > 0 && (
                <div className="mt-2 space-y-1">
                  {politicalGraph.edges.slice(0, 8).map((edge, idx) => (
                    <p key={idx} className="text-[11px] text-muted-foreground">
                      <span className="text-foreground">{edge.source}</span>
                      <span className="mx-1 text-teal-300">→</span>
                      <span className="text-foreground">{edge.target}</span>
                      {edge.label && <span className="ml-1 text-muted-foreground">({edge.label})</span>}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Página principal
// ---------------------------------------------------------------------------

export default function PoliticosPortugalPage() {
  const [q, setQ] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [party, setParty] = useState("");
  const [sort, setSort] = useState<PoliticianSort>("relevance");
  const [results, setResults] = useState<PeopleSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Person | null>(null);
  const [graph, setGraph] = useState<PeopleGraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);

  const boxRef = useRef<HTMLDivElement | null>(null);
  const hasSearchedRef = useRef(false);

  const runSearch = useCallback(
    async (value: string, opts?: { from?: number; append?: boolean }) => {
      const term = value.trim();
      if (!term && sourceFilter === "all" && !party) {
        // Sem termo e sem filtro, pesquisa tudo para mostrar resultados.
      }
      const append = Boolean(opts?.append);
      const from = opts?.from ?? 0;
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      hasSearchedRef.current = true;
      try {
        let extra: { source?: string; tag?: string } = { tag: POLITICOS_TAG };
        if (sourceFilter === "deputados") {
          extra = { tag: POLITICOS_TAG, source: "assembleia-republica" };
        } else if (sourceFilter === "wikipedia") {
          extra = { tag: POLITICOS_TAG, source: "wikipedia" };
        }
        const resp = await searchPeople(term || undefined, {
          ...extra,
          party: party.trim() || undefined,
          sort: sort === "name" ? "name" : "relevance",
          size: PAGE_SIZE,
          from,
        });
        if (resp.error) throw new Error(resp.error);
        setResults((prev) =>
          append && prev ? { ...resp, items: [...prev.items, ...resp.items], from: 0 } : resp,
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao pesquisar");
        if (!append) setResults(null);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [sourceFilter, party, sort],
  );

  // Pesquisa inicial: todos os políticos.
  useEffect(() => {
    void runSearch("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refazer pesquisa quando filtros mudam.
  useEffect(() => {
    if (!hasSearchedRef.current) return;
    void runSearch(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, party, sort]);

  const loadGraph = useCallback(async (nif: string) => {
    setGraphLoading(true);
    try {
      const resp = await getPersonGraph(nif);
      setGraph(resp);
    } catch (err) {
      setGraph(null);
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const handleSelect = useCallback(
    (person: Person) => {
      setSelected(person);
      setGraph(null);
      void loadGraph(person.nif);
    },
    [loadGraph],
  );

  const handleCloseDetail = useCallback(() => {
    setSelected(null);
    setGraph(null);
  }, []);

  const activeFilters = useMemo(() => {
    const list: { key: string; label: string; clear: () => void }[] = [];
    if (sourceFilter !== "all") {
      const label = SOURCE_OPTS.find((o) => o.key === sourceFilter)?.label || sourceFilter;
      list.push({ key: "source", label, clear: () => setSourceFilter("all") });
    }
    if (party.trim()) {
      list.push({ key: "party", label: `Partido: ${party.trim()}`, clear: () => setParty("") });
    }
    if (sort !== "relevance") {
      list.push({ key: "sort", label: `Ordenar: ${SORT_OPTS.find((o) => o.key === sort)?.label || sort}`, clear: () => setSort("relevance") });
    }
    return list;
  }, [sourceFilter, party, sort]);

  const clearFilters = () => {
    setSourceFilter("all");
    setParty("");
    setSort("relevance");
  };

  const loadedCount = results?.items.length ?? 0;
  const hasMore = Boolean(results && loadedCount < results.total);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background text-foreground orbit-bg">
      <header className="border-b border-white/10 bg-white/[0.02] px-4 py-3 lg:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold text-foreground">
              <Landmark size={22} className="text-rose-300" />
              Políticos de Portugal
            </h1>
            <p className="text-xs text-muted-foreground">
              Deputados do Parlamento.pt e políticos da Wikipédia PT
            </p>
          </div>

          <div ref={boxRef} className="flex w-full flex-col gap-2 lg:w-auto lg:min-w-[520px]">
            <div className="flex min-h-[44px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
              <Search size={18} className="shrink-0 text-muted-foreground" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void runSearch(q);
                  }
                }}
                placeholder="Nome, partido ou cargo…"
                autoComplete="off"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {q && (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    void runSearch("");
                  }}
                  className="rounded-md p-1 text-muted-foreground hover:text-foreground"
                  aria-label="Limpar"
                >
                  <X size={14} />
                </button>
              )}
              <button
                type="button"
                onClick={() => void runSearch(q)}
                disabled={loading}
                className="shrink-0 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-1.5 text-xs text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : "Pesquisar"}
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {SOURCE_OPTS.map((opt) => {
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setSourceFilter(opt.key)}
                    className={[
                      "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition",
                      sourceFilter === opt.key
                        ? "border-rose-400/30 bg-rose-400/15 text-rose-200"
                        : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    <Icon size={14} /> {opt.label}
                  </button>
                );
              })}
              <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1">
                <Filter size={13} className="text-muted-foreground" />
                <input
                  value={party}
                  onChange={(e) => setParty(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void runSearch(q);
                    }
                  }}
                  placeholder="Partido…"
                  autoComplete="off"
                  className="min-w-[120px] bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                />
              </div>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as PoliticianSort)}
                className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-foreground outline-none"
              >
                {SORT_OPTS.map((opt) => (
                  <option key={opt.key} value={opt.key}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {activeFilters.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted-foreground">Filtros:</span>
                {activeFilters.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    onClick={f.clear}
                    className="flex items-center gap-1 rounded-full bg-white/[0.08] px-2 py-1 text-muted-foreground transition hover:text-foreground"
                  >
                    {f.label} <X size={12} />
                  </button>
                ))}
                <button
                  type="button"
                  onClick={clearFilters}
                  className="rounded-full border border-white/10 px-2 py-1 text-muted-foreground transition hover:text-foreground"
                >
                  Limpar
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="@container min-w-0 flex-1 overflow-y-auto p-3 lg:p-6">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_minmax(0,420px)]">
          <div className="min-w-0 space-y-4">
            {error && (
              <Card className="p-6 text-center">
                <p className="text-rose-300">{error}</p>
              </Card>
            )}

            {loading && !results && <Loading message="A pesquisar políticos…" />}

            {!loading && results && results.total === 0 && (
              <EmptyState message="Nenhum político encontrado com os filtros atuais." />
            )}

            {results && results.total > 0 && !loading && (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  {results.total.toLocaleString("pt-PT")} resultado{results.total === 1 ? "" : "s"}
                  {loadedCount < results.total ? ` · a mostrar ${loadedCount}` : ""}
                </p>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {results.items.map((person) => (
                    <PoliticianCard key={person.nif} person={person} onOpenDetail={handleSelect} />
                  ))}
                </div>
                {hasMore && (
                  <div className="flex justify-center pt-2">
                    <button
                      type="button"
                      onClick={() => void runSearch(q, { from: loadedCount, append: true })}
                      disabled={loadingMore}
                      className="min-h-[40px] rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-foreground transition hover:bg-white/[0.08] disabled:opacity-50"
                    >
                      {loadingMore ? <Loader2 size={16} className="animate-spin" /> : "Carregar mais"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {selected && (
            <aside className="min-w-0">
              <Card glow="rose">
                <PoliticianDetailPanel person={selected} graph={graph} graphLoading={graphLoading} onClose={handleCloseDetail} />
              </Card>
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}
