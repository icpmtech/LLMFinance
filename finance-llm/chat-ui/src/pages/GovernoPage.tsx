/**
 * **Governo** — os ministérios, os membros da composição e as nomeações dos
 * gabinetes, com o grafo de relações.
 *
 * A página serve o grafo *ministério → membro → gabinete* recolhido do
 * `portugal.gov.pt`: mostra os totais (pastas, membros e despachos), deixa
 * filtrar por pasta, procurar por nome ou cargo e abrir a ficha de cada membro.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CircleAlert,
  Landmark,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Users,
  Wallet,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import {
  fetchGovernoOverview,
  type GovernoArea,
  type GovernoMembroResumo,
  type GovernoOverview,
} from "../governoApi";

interface GovernoPageProps {
  /** Pasta escolhida por link (`/governo?area=<slug>`). */
  initialArea?: string;
  /** Abre uma vista da aplicação (`governo-ficha:<id>`, `governo-pessoa:<nif>`). */
  onOpenView?: (view: string, title?: string) => void;
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <span className="rounded-xl bg-primary/10 p-2 text-primary">{icon}</span>
        <div>
          <div className="text-lg font-semibold leading-tight">{new Intl.NumberFormat("pt-PT").format(value)}</div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function MemberCard({
  membro,
  onOpen,
}: {
  membro: GovernoMembroResumo;
  onOpen: (membro: GovernoMembroResumo) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(membro)}
      className="group flex w-full items-center gap-3 rounded-xl border border-border/60 bg-card/60 p-3 text-left transition hover:border-primary/40 hover:bg-accent/40"
    >
      {membro.foto ? (
        <img
          src={membro.foto}
          alt={membro.nome}
          loading="lazy"
          className="h-12 w-12 shrink-0 rounded-full object-cover ring-1 ring-border"
        />
      ) : (
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Users size={18} />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{membro.nome}</span>
        <span className="block truncate text-xs text-muted-foreground">{membro.cargo}</span>
      </span>
      <ArrowRight size={14} className="shrink-0 text-muted-foreground transition group-hover:text-primary" />
    </button>
  );
}

export default function GovernoPage({ initialArea = "", onOpenView }: GovernoPageProps) {
  const [overview, setOverview] = useState<GovernoOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [area, setArea] = useState(initialArea);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchGovernoOverview()
      .then(setOverview)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const abrirMembro = useCallback(
    (membro: GovernoMembroResumo) => {
      if (onOpenView) onOpenView(`governo-ficha:${membro.id}`, membro.nome);
      else if (typeof window !== "undefined") window.location.assign(`/governo/ficha/${encodeURIComponent(membro.id)}`);
    },
    [onOpenView],
  );

  const areas = overview?.areas ?? [];
  const membros = useMemo(() => {
    const termo = query.trim().toLowerCase();
    return (overview?.membros ?? []).filter((membro) => {
      if (area && membro.area_slug !== area) return false;
      if (!termo) return true;
      return `${membro.nome} ${membro.cargo}`.toLowerCase().includes(termo);
    });
  }, [overview, area, query]);

  const areaAtiva: GovernoArea | undefined = areas.find((item) => item.area_slug === area);
  const graph = overview?.graph ?? null;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Landmark size={18} /> Governo
          </h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Ministérios, membros da composição e nomeações dos gabinetes recolhidos do{" "}
            <a href="https://portugal.gov.pt/gc24/governo/nomeacoes" target="_blank" rel="noreferrer" className="underline">
              portugal.gov.pt
            </a>
            , com o despacho do Diário da República e o rendimento de cada designação. Abra um membro para ver a ficha
            com as remunerações do gabinete e as relações em grafo.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={load} loading={loading}>
          Atualizar
        </Button>
      </header>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-destructive">
            <CircleAlert size={16} /> {error}
          </CardContent>
        </Card>
      )}

      {overview && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat icon={<Landmark size={16} />} label="Ministérios" value={overview.stats.ministerios} />
          <Stat icon={<Users size={16} />} label="Membros do Governo" value={overview.stats.membros} />
          <Stat icon={<Wallet size={16} />} label="Nomeações" value={overview.stats.nomeacoes} />
          <Stat icon={<Network size={16} />} label="Documentos recolhidos" value={overview.stats.scraped} />
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Network size={16} /> Grafo de relações
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            Ministério → membro → gabinete (espessura = nomeações)
          </span>
        </CardHeader>
        <CardContent>
          <GraphCanvas
            graph={graph}
            layout="network"
            metric="contratos"
            unitLabel="nomeações"
            heightClass="h-[560px]"
            nodeSummary={(node) => {
              const subtitle = (node as unknown as { subtitle?: string }).subtitle;
              return `${node.label}${subtitle ? ` · ${subtitle}` : ""}`;
            }}
            edgeSummary={(edge) => `${(edge as unknown as { role?: string }).role ?? ""} · ${edge.count ?? 0} nomeações`}
            onNodeClick={(node) => {
              const memberId = (node as unknown as { member_id?: string }).member_id;
              if (memberId) abrirMembro({ id: memberId, nome: node.label, cargo: "" } as GovernoMembroResumo);
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users size={16} /> Membros do Governo
          </CardTitle>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Nome ou cargo…"
                className="h-8 w-56 pl-7 text-xs"
              />
            </div>
            <Badge variant="outline">{membros.length}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setArea("")}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                area === "" ? "border-primary/50 bg-primary/15 text-primary" : "border-border/60 text-muted-foreground hover:bg-accent"
              }`}
            >
              Todas as pastas
            </button>
            {areas.map((item) => (
              <button
                key={item.area_slug}
                type="button"
                onClick={() => setArea(item.area_slug)}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  area === item.area_slug
                    ? "border-primary/50 bg-primary/15 text-primary"
                    : "border-border/60 text-muted-foreground hover:bg-accent"
                }`}
              >
                {item.area}
              </button>
            ))}
          </div>

          {areaAtiva && (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
              <strong className="text-foreground">{areaAtiva.area}</strong>
              {areaAtiva.titular ? ` · titular: ${areaAtiva.titular}` : ""}
              {` · ${areaAtiva.secretarios_count ?? 0} secretários de Estado · ${areaAtiva.nomeacoes_count ?? 0} nomeações`}
              {areaAtiva.url && (
                <>
                  {" · "}
                  <a href={areaAtiva.url} target="_blank" rel="noreferrer" className="underline">
                    ver no portugal.gov.pt
                  </a>
                </>
              )}
            </div>
          )}

          {loading && !overview ? (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 size={16} className="animate-spin" /> A carregar a composição do Governo…
            </div>
          ) : (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {membros.map((membro) => (
                <MemberCard key={membro.id} membro={membro} onOpen={abrirMembro} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
