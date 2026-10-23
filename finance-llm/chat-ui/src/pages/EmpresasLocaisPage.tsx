/**
 * Página do módulo **Empresas locais**.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Building2,
  Info,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import {
  dataFormatada,
  getEmpresaLocal,
  getEmpresasLocais,
  getEmpresasLocaisStats,
  participacaoFormatada,
  recolherEmpresasLocais,
  type EmpresaLocal,
  type EmpresaLocalFicha,
  type EmpresasLocaisResponse,
  type EmpresasLocaisStats,
} from "../empresasLocaisApi";

/* ------------------------------------------------------------------ opções */

function Cartao({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`glass-card min-w-0 rounded-2xl p-4 ${className}`}>{children}</div>;
}

function Kpi({ label, valor, nota }: { label: string; valor: string; nota?: string }) {
  return (
    <Cartao className="p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{valor}</p>
      {nota ? <p className="mt-0.5 text-[10px] text-muted-foreground">{nota}</p> : null}
    </Cartao>
  );
}

/* ------------------------------------------------------------------- ficha */

function FichaEmpresa({ ficha }: { ficha: EmpresaLocalFicha }) {
  if (ficha.error) {
    return (
      <Cartao className="border-rose-400/20">
        <p className="text-sm text-rose-300">{ficha.error}</p>
      </Cartao>
    );
  }
  const m = ficha as EmpresaLocal;
  return (
    <div className="space-y-3">
      <Cartao>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">{m.designacao}</h2>
            {m.setor ? <p className="text-xs text-muted-foreground">Setor: {m.setor}</p> : null}
          </div>
          {m.participacao_pct !== undefined && m.participacao_pct !== null ? (
            <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
              {participacaoFormatada(m.participacao_pct)}
            </span>
          ) : null}
        </div>
      </Cartao>

      <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Entidade local participante</p>
          <p className="mt-1 text-sm font-medium">{m.entidade_local || "—"}</p>
        </Cartao>
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Influência dominante</p>
          <p className="mt-1 text-sm font-medium">{m.entidade_dominante || "—"}</p>
        </Cartao>
      </div>

      <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Participação</p>
          <p className="mt-1 text-sm font-medium">{participacaoFormatada(m.participacao_pct)}</p>
        </Cartao>
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Data de constituição</p>
          <p className="mt-1 text-sm font-medium">{dataFormatada(m.data_constituicao)}</p>
        </Cartao>
      </div>

      {m.observacoes ? (
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Observações</p>
          <p className="mt-1 text-sm">{m.observacoes}</p>
        </Cartao>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------- página */

export default function EmpresasLocaisPage() {
  const [stats, setStats] = useState<EmpresasLocaisStats | null>(null);
  const [dados, setDados] = useState<EmpresasLocaisResponse | null>(null);
  const [detalhe, setDetalhe] = useState<EmpresaLocalFicha | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [aDetalhar, setADetalhar] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [entidadeLocal, setEntidadeLocal] = useState("");
  const [setor, setSetor] = useState("");
  const [alvoDetalhe, setAlvoDetalhe] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const carregar = useCallback(
    async (pagina = 1) => {
      setACarregar(true);
      setErro(null);
      try {
        const resposta = await getEmpresasLocais({
          q: q.trim() || undefined,
          entidade_local: entidadeLocal || undefined,
          setor: setor || undefined,
          page: pagina,
          size: 30,
        });
        setDados(resposta);
        setPage(pagina);
      } catch (excecao) {
        setErro(excecao instanceof Error ? excecao.message : String(excecao));
      } finally {
        setACarregar(false);
      }
    },
    [q, entidadeLocal, setor],
  );

  useEffect(() => {
    void carregar(1);
  }, [carregar]);

  useEffect(() => {
    getEmpresasLocaisStats().then(setStats).catch(() => setStats(null));
  }, []);

  const abrir = useCallback((empresa: EmpresaLocal) => {
    setAlvoDetalhe(empresa.doc_id || empresa.slug || null);
  }, []);

  useEffect(() => {
    if (!alvoDetalhe) return;
    let ativo = true;
    setADetalhar(true);
    setErro(null);
    getEmpresaLocal(alvoDetalhe)
      .then((resposta) => {
        if (ativo) setDetalhe(resposta);
      })
      .catch((excecao) => {
        if (ativo) setErro(excecao instanceof Error ? excecao.message : String(excecao));
      })
      .finally(() => {
        if (ativo) setADetalhar(false);
      });
    return () => {
      ativo = false;
    };
  }, [alvoDetalhe]);

  const recolher = useCallback(async () => {
    setARecolher(true);
    setErro(null);
    try {
      await recolherEmpresasLocais(true);
      await carregar(1);
      setStats(await getEmpresasLocaisStats().catch(() => null));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setARecolher(false);
    }
  }, [carregar]);

  const entidades = useMemo(
    () => (dados?.entidades ?? stats?.por_entidade ?? []).map((d) => d.key).sort((a, b) => a.localeCompare(b)),
    [dados, stats],
  );
  const setores = useMemo(
    () => (dados?.setores ?? stats?.por_setor ?? []).map((d) => d.key).sort((a, b) => a.localeCompare(b)),
    [dados, stats],
  );
  const totalPaginas = dados ? Math.max(1, Math.ceil(dados.total / dados.size)) : 1;

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="space-y-4 p-4 lg:p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Empresas locais</h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Empresas com participação de entidades locais — designação, entidade participante,
              participação (%), setor e data de constituição.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void recolher()}
            disabled={aRecolher}
            className="flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
          >
            {aRecolher ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Recolher de novo
          </button>
        </header>

        <section className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
          <Kpi label="Empresas" valor={String(stats?.documents ?? dados?.total ?? "—")} />
          <Kpi label="Entidades locais" valor={String(entidades.length)} />
          <Kpi label="Setores" valor={String(setores.length)} />
          <Kpi
            label="Participação 100%"
            valor={String(dados?.items?.filter((m) => m.participacao_pct === 100).length ?? "—")}
            nota="apenas página atual"
          />
        </section>

        <section className="glass-card min-w-0 rounded-2xl p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
              <input
                value={q}
                onChange={(evento) => setQ(evento.target.value)}
                onKeyDown={(evento) => evento.key === "Enter" && void carregar(1)}
                placeholder="Procurar empresa, entidade local ou setor"
                className="w-full rounded-lg border border-input bg-background py-1.5 pl-8 pr-8 text-xs"
              />
              {q ? (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    void carregar(1);
                  }}
                  aria-label="Limpar"
                  className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
                >
                  <X size={13} />
                </button>
              ) : null}
            </div>

            <select
              value={entidadeLocal}
              onChange={(evento) => setEntidadeLocal(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              <option value="">Todas as entidades</option>
              {entidades.map((nome) => (
                <option key={nome} value={nome}>
                  {nome}
                </option>
              ))}
            </select>

            <select
              value={setor}
              onChange={(evento) => setSetor(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              <option value="">Todos os setores</option>
              {setores.map((nome) => (
                <option key={nome} value={nome}>
                  {nome}
                </option>
              ))}
            </select>
          </div>
        </section>

        {erro ? (
          <Cartao className="text-center">
            <p className="text-sm text-rose-300">{erro}</p>
          </Cartao>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,min(46%,860px))]">
          <div className="min-w-0 space-y-3">
            <Cartao className="overflow-x-auto p-0">
              <table className="w-full min-w-[640px] text-[11px]">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Empresa</th>
                    <th className="px-3 py-2 font-medium">Entidade local</th>
                    <th className="px-3 py-2 font-medium">Setor</th>
                    <th className="px-3 py-2 font-medium">Participação</th>
                  </tr>
                </thead>
                <tbody>
                  {(dados?.items ?? []).map((m) => (
                    <tr
                      key={m.doc_id || m.slug}
                      onClick={() => void abrir(m)}
                      className={`cursor-pointer border-t border-white/5 transition hover:bg-white/5 ${
                        detalhe?.doc_id === m.doc_id ? "bg-white/[0.07]" : ""
                      }`}
                      title="Abrir a ficha desta empresa"
                    >
                      <td className="px-3 py-1.5 font-medium">
                        <span className="flex items-center gap-2">
                          <Building2 size={11} className="shrink-0 text-teal-300/70" />
                          {m.designacao}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.entidade_local ?? "—"}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.setor ?? "—"}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {m.participacao_pct !== undefined && m.participacao_pct !== null ? (
                          <span className="flex items-center gap-1.5">
                            <Briefcase size={11} className="shrink-0 text-teal-300/70" />
                            {participacaoFormatada(m.participacao_pct)}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                  {dados && dados.items.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                        Nenhuma empresa com os filtros atuais.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Cartao>

            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] text-muted-foreground">
                {aCarregar ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" /> a carregar…
                  </span>
                ) : (
                  `página ${page} de ${totalPaginas}`
                )}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void carregar(Math.max(1, page - 1))}
                  disabled={page <= 1 || aCarregar}
                  className="rounded-lg border border-white/10 px-2 py-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
                >
                  Anterior
                </button>
                <button
                  type="button"
                  onClick={() => void carregar(Math.min(totalPaginas, page + 1))}
                  disabled={page >= totalPaginas || aCarregar}
                  className="rounded-lg border border-white/10 px-2 py-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-40"
                >
                  Seguinte
                </button>
              </div>
            </div>
          </div>

          <div className="min-w-0">
            {aDetalhar ? (
              <Cartao className="flex h-40 items-center justify-center text-xs text-muted-foreground">
                <Loader2 size={14} className="mr-2 animate-spin" /> A carregar a ficha…
              </Cartao>
            ) : detalhe ? (
              <FichaEmpresa key={detalhe.doc_id} ficha={detalhe} />
            ) : (
              <Cartao>
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <Info size={14} /> Escolha uma empresa
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Clique numa linha para ver a ficha detalhada: participação, entidades,
                  setor e observações.
                </p>
              </Cartao>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
