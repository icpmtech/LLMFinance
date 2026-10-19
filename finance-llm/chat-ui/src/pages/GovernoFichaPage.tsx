/**
 * **Ficha do Governo** — o detalhe de um membro do Governo (`/governo/ficha/<id>`)
 * ou de uma pessoa de entidade ligada a ele (`/governo/pessoa/<nif>`).
 *
 * A mesma página serve os dois casos porque a pergunta é a mesma — «quem é esta
 * pessoa e o que está ligado a ela?»:
 *
 * - **membro do Governo** — cargo, biografia oficial, remunerações do gabinete
 *   (despesa por despacho, com bruto e líquido), relações (ministério, gabinete,
 *   despachos e a ficha da pessoa em entidades) e o grafo da ficha;
 * - **pessoa de entidade** — cargos societários, empresas participadas e, quando
 *   o nome coincide com um membro do Governo, o atalho para essa ficha.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CircleAlert,
  ExternalLink,
  FileText,
  Landmark,
  Loader2,
  Network,
  RefreshCw,
  UserRound,
  Users,
  Wallet,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/Tabs";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import {
  dataCurta,
  euros,
  fetchGovernoMembro,
  fetchGovernoPessoa,
  type GovernoFicha,
  type GovernoFichaMembro,
  type GovernoFichaPessoa,
  type GovernoRelacao,
} from "../governoApi";

interface GovernoFichaPageProps {
  /** Identificador do membro (`governo-composicao:<hash>`). */
  memberId?: string;
  /** NIF (ou identificador público) de uma pessoa em entidades. */
  nif?: string;
  /** Navegação interna (`governo-pessoa:<nif>`, `governo-ficha:<id>`). */
  onNavigate?: (view: string, title?: string) => void;
  onBack?: () => void;
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/60 p-3">
      <div className="text-base font-semibold leading-tight">{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

function RelacaoLinha({ relacao, onNavigate }: { relacao: GovernoRelacao; onNavigate?: GovernoFichaPageProps["onNavigate"] }) {
  if (relacao.tipo === "pessoa") {
    const abrir = () => {
      if (!relacao.nif) return;
      if (onNavigate) onNavigate(`governo-pessoa:${relacao.nif}`, relacao.label ?? undefined);
      else if (typeof window !== "undefined") window.location.assign(`/governo/pessoa/${encodeURIComponent(relacao.nif)}`);
    };
    return (
      <button
        type="button"
        onClick={abrir}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-left text-xs transition hover:border-primary/40 hover:bg-accent/40"
      >
        <span className="flex min-w-0 items-center gap-2">
          <UserRound size={13} className="shrink-0 text-emerald-400" />
          <span className="min-w-0">
            <span className="block truncate font-medium">{relacao.label ?? relacao.nif}</span>
            <span className="block truncate text-[11px] text-muted-foreground">
              Pessoa em entidades · {relacao.cargos ?? 0} cargos · {relacao.empresas ?? 0} empresas
            </span>
          </span>
        </span>
        <span className="shrink-0 text-[11px] text-primary">abrir ficha</span>
      </button>
    );
  }
  if (relacao.tipo === "dre") {
    return (
      <a
        href={relacao.url ?? "#"}
        target="_blank"
        rel="noreferrer"
        className="flex items-start justify-between gap-2 rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-xs transition hover:border-primary/40 hover:bg-accent/40"
      >
        <span className="min-w-0">
          <span className="block truncate font-medium">{relacao.label ?? "Despacho"}</span>
          <span className="block truncate text-[11px] text-muted-foreground">
            {dataCurta(relacao.data)} · {relacao.sumario ?? ""}
          </span>
        </span>
        <ExternalLink size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
      </a>
    );
  }
  const Icone = relacao.tipo === "ministerio" ? Landmark : relacao.tipo === "gabinete" ? Users : FileText;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-xs">
      <Icone size={13} className="mt-0.5 shrink-0 text-sky-400" />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{relacao.label ?? relacao.tipo}</div>
        <div className="truncate text-[11px] text-muted-foreground">
          {relacao.tipo === "gabinete"
            ? `${relacao.total ?? 0} nomeações · ${euros(relacao.total_bruto_eur)} de rendimento bruto`
            : `${relacao.papel ?? ""}${relacao.area_slug ? ` · ${relacao.area_slug}` : ""}`}
        </div>
      </div>
      {relacao.url && (
        <a href={relacao.url} target="_blank" rel="noreferrer" className="shrink-0 text-muted-foreground hover:text-primary">
          <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

function GrafoFicha({ ficha }: { ficha: GovernoFicha }) {
  return (
    <div>
      <GraphCanvas
        graph={ficha.grafo}
        layout="network"
        metric="contratos"
        unitLabel="nomeações"
        heightClass="h-[520px]"
        nodeSummary={(node) => {
          const dados = node as unknown as { subtitle?: string; bruto_eur?: number; data_nomeacao?: string };
          if (dados.bruto_eur) return `${euros(dados.bruto_eur)} · ${dataCurta(dados.data_nomeacao)}`;
          return `${node.label}${dados.subtitle ? ` · ${dados.subtitle}` : ""}`;
        }}
        edgeSummary={(edge) => `${(edge as unknown as { role?: string }).role ?? ""}`}
      />
      <p className="mt-2 text-[11px] text-muted-foreground">
        {(ficha.grafo.meta?.notes ?? []).join(" ")}
      </p>
    </div>
  );
}

function FichaMembro({
  ficha,
  onNavigate,
}: {
  ficha: GovernoFichaMembro;
  onNavigate?: GovernoFichaPageProps["onNavigate"];
}) {
  const [tab, setTab] = useState("resumo");
  const { membro, ministerio, remuneracoes, relacoes, grafo } = ficha;
  const despachos = useMemo(() => relacoes.filter((relacao) => relacao.tipo === "dre"), [relacoes]);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-start gap-4 p-4">
          {membro.foto ? (
            <img
              src={membro.foto}
              alt={membro.nome}
              className="h-24 w-24 shrink-0 rounded-2xl object-cover ring-1 ring-border"
            />
          ) : (
            <span className="flex h-24 w-24 shrink-0 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
              <UserRound size={28} />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold leading-tight">{membro.nome}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge variant="info">{membro.cargo}</Badge>
              {membro.grupo && <Badge variant="outline">{membro.grupo}</Badge>}
              {membro.area_nome && <Badge variant="secondary">{membro.area_nome}</Badge>}
              <Badge variant="default">
                {dataCurta(membro.periodo_inicio)} → {dataCurta(membro.periodo_fim)}
              </Badge>
            </div>
            {membro.biografia && (
              <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-line pr-1 text-xs leading-relaxed text-muted-foreground">
                {membro.biografia}
              </p>
            )}
            {membro.url && (
              <a
                href={membro.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-[11px] text-primary underline"
              >
                perfil oficial no portugal.gov.pt <ExternalLink size={10} />
              </a>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Nomeações no gabinete" value={String(remuneracoes.total)} />
        <Kpi label="Rendimento bruto" value={euros(remuneracoes.total_bruto_eur)} />
        <Kpi label="Rendimento líquido" value={euros(remuneracoes.total_liquido_eur)} />
        <Kpi label="Média bruta" value={euros(remuneracoes.media_bruta_eur)} />
      </div>

      <Tabs value={tab}>
        <TabsList>
          <TabsTrigger value="resumo" active={tab === "resumo"} onClick={() => setTab("resumo")}>
            Relações
          </TabsTrigger>
          <TabsTrigger value="remuneracoes" active={tab === "remuneracoes"} onClick={() => setTab("remuneracoes")}>
            Remunerações
          </TabsTrigger>
          <TabsTrigger value="grafo" active={tab === "grafo"} onClick={() => setTab("grafo")}>
            Grafo
          </TabsTrigger>
        </TabsList>

        <TabsContent value="resumo" active={tab === "resumo"} className="space-y-3">
          {ministerio && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Landmark size={16} /> Pasta
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 text-xs sm:grid-cols-3">
                <div>
                  <div className="text-muted-foreground">Ministério</div>
                  <div className="font-medium">{ministerio.area ?? "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Titular</div>
                  <div className="font-medium">{ministerio.titular ?? "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Secretários de Estado</div>
                  <div className="font-medium">{ministerio.secretarios_count ?? 0}</div>
                </div>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Network size={16} /> Relações
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {relacoes.length === 0 && <p className="text-xs text-muted-foreground">Sem relações registadas.</p>}
              {relacoes.slice(0, 12).map((relacao, index) => (
                <RelacaoLinha key={`${relacao.tipo}-${index}`} relacao={relacao} onNavigate={onNavigate} />
              ))}
              {despachos.length > 12 && (
                <p className="pt-1 text-[11px] text-muted-foreground">
                  + {despachos.length - 12} despachos na lista de remunerações.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="remuneracoes" active={tab === "remuneracoes"} className="space-y-3">
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Wallet size={16} /> Remunerações do gabinete
              </CardTitle>
              <span className="text-xs text-muted-foreground">
                {remuneracoes.total} designações · mínimo {euros(remuneracoes.min_bruta_eur)} · máximo{" "}
                {euros(remuneracoes.max_bruta_eur)}
              </span>
            </CardHeader>
            <CardContent className="space-y-3">
              {remuneracoes.por_funcao.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {remuneracoes.por_funcao.map((item) => (
                    <Badge key={item.funcao} variant="secondary">
                      {item.funcao}: {item.total} · {euros(item.bruto)}
                    </Badge>
                  ))}
                </div>
              )}
              <div className="max-h-[520px] overflow-auto rounded-lg border border-border/60">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-muted/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Nome</th>
                      <th className="px-3 py-2">Função</th>
                      <th className="px-3 py-2">Data</th>
                      <th className="px-3 py-2 text-right">Bruto</th>
                      <th className="px-3 py-2 text-right">Líquido</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {remuneracoes.linhas.map((linha) => (
                      <tr key={linha.id} className="border-t border-border/40 hover:bg-accent/30">
                        <td className="px-3 py-1.5">{linha.nome ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{linha.funcao ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{dataCurta(linha.data_nomeacao)}</td>
                        <td className="px-3 py-1.5 text-right font-medium">{euros(linha.rendimento_bruto_eur)}</td>
                        <td className="px-3 py-1.5 text-right text-muted-foreground">
                          {euros(linha.rendimento_liquido_eur)}
                        </td>
                        <td className="px-3 py-1.5 text-right">
                          {linha.dre_url && (
                            <a
                              href={linha.dre_url}
                              target="_blank"
                              rel="noreferrer"
                              title={linha.dre_titulo ?? "Diário da República"}
                              className="text-muted-foreground hover:text-primary"
                            >
                              <FileText size={12} />
                            </a>
                          )}
                        </td>
                      </tr>
                    ))}
                    {remuneracoes.linhas.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                          Sem nomeações associadas a este membro.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="grafo" active={tab === "grafo"}>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Network size={16} /> Relações em grafo
              </CardTitle>
            </CardHeader>
            <CardContent>
              <GrafoFicha ficha={ficha} />
              <p className="mt-1 text-[11px] text-muted-foreground">
                {grafo.nodes.length} nós · {grafo.edges.length} relações
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function FichaPessoa({
  ficha,
  onNavigate,
}: {
  ficha: GovernoFichaPessoa;
  onNavigate?: GovernoFichaPageProps["onNavigate"];
}) {
  const [tab, setTab] = useState("cargos");
  const { pessoa, governo } = ficha;
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-start gap-4 p-4">
          <span className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
            <UserRound size={26} />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold leading-tight">{pessoa.nome}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline">NIF {pessoa.nif}</Badge>
              <Badge variant="info">{pessoa.roles_count} cargos</Badge>
              <Badge variant="secondary">{pessoa.companies_count} empresas</Badge>
              {governo && (
                <button
                  type="button"
                  onClick={() => {
                    if (!governo.id) return;
                    if (onNavigate) onNavigate(`governo-ficha:${governo.id}`, pessoa.nome);
                    else if (typeof window !== "undefined")
                      window.location.assign(`/governo/ficha/${encodeURIComponent(governo.id)}`);
                  }}
                  className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] text-primary hover:bg-primary/20"
                >
                  {governo.cargo} · abrir ficha do Governo
                </button>
              )}
            </div>
            {(pessoa.first_seen || pessoa.last_seen) && (
              <p className="mt-2 text-[11px] text-muted-foreground">
                Registo de {dataCurta(pessoa.first_seen)} a {dataCurta(pessoa.last_seen)}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Tabs value={tab}>
        <TabsList>
          <TabsTrigger value="cargos" active={tab === "cargos"} onClick={() => setTab("cargos")}>
            Cargos
          </TabsTrigger>
          <TabsTrigger value="empresas" active={tab === "empresas"} onClick={() => setTab("empresas")}>
            Empresas
          </TabsTrigger>
          <TabsTrigger value="grafo" active={tab === "grafo"} onClick={() => setTab("grafo")}>
            Grafo
          </TabsTrigger>
        </TabsList>

        <TabsContent value="cargos" active={tab === "cargos"}>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users size={16} /> Cargos registados
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-[520px] overflow-auto rounded-lg border border-border/60">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-muted/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">Cargo</th>
                      <th className="px-3 py-2">Empresa</th>
                      <th className="px-3 py-2">Data</th>
                      <th className="px-3 py-2">Registo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pessoa.latest_roles.map((cargo, index) => (
                      <tr key={`${cargo.company_nif}-${index}`} className="border-t border-border/40 hover:bg-accent/30">
                        <td className="px-3 py-1.5 font-medium">{cargo.role ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{cargo.company_name ?? cargo.company_nif ?? "—"}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{dataCurta(cargo.date)}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{cargo.acto ?? cargo.event ?? "—"}</td>
                      </tr>
                    ))}
                    {pessoa.latest_roles.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                          Sem cargos indexados.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="empresas" active={tab === "empresas"}>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Landmark size={16} /> Empresas
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {pessoa.companies.map((empresa) => (
                <div key={empresa.nif} className="rounded-lg border border-border/60 bg-card/60 px-3 py-2 text-xs">
                  <div className="truncate font-medium">{empresa.name ?? empresa.nif}</div>
                  <div className="text-[11px] text-muted-foreground">NIF {empresa.nif}</div>
                </div>
              ))}
              {pessoa.companies.length === 0 && <p className="text-xs text-muted-foreground">Sem empresas ligadas.</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="grafo" active={tab === "grafo"}>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Network size={16} /> Relações em grafo
              </CardTitle>
            </CardHeader>
            <CardContent>
              <GrafoFicha ficha={ficha} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function GovernoFichaPage({ memberId, nif, onNavigate, onBack }: GovernoFichaPageProps) {
  const [ficha, setFicha] = useState<GovernoFicha | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!memberId && !nif) {
      setError("Ficha sem identificador.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const pedido = nif ? fetchGovernoPessoa(nif) : fetchGovernoMembro(String(memberId));
    pedido
      .then((dados) => setFicha(dados as GovernoFicha))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [memberId, nif]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<ArrowLeft size={14} />}
            onClick={() => {
              if (onBack) onBack();
              else if (onNavigate) onNavigate("governo");
              else if (typeof window !== "undefined") window.location.assign("/governo");
            }}
          >
            Governo
          </Button>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={load} loading={loading}>
          Atualizar
        </Button>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-destructive">
            <CircleAlert size={16} /> {error}
          </CardContent>
        </Card>
      )}

      {loading && !ficha && (
        <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" /> A carregar a ficha…
        </div>
      )}

      {ficha && (ficha.kind === "membro" ? (
        <FichaMembro ficha={ficha} onNavigate={onNavigate} />
      ) : (
        <FichaPessoa ficha={ficha} onNavigate={onNavigate} />
      ))}
    </div>
  );
}

