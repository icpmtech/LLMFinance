/**
 * Página do módulo **Contactos das juntas de freguesia**.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Info,
  Loader2,
  Mail,
  MapPin,
  Phone,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import {
  getFreguesiaContacto,
  getFreguesiasContactos,
  getFreguesiasContactosStats,
  moradaCompacta,
  recolherFreguesiasContactos,
  telefoneFormatado,
  type FreguesiaContacto,
  type FreguesiaContactoFicha,
  type FreguesiasContactosResponse,
  type FreguesiasContactosStats,
} from "../freguesiasContactosApi";

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

function FichaContacto({ ficha }: { ficha: FreguesiaContactoFicha }) {
  if (ficha.error) {
    return (
      <Cartao className="border-rose-400/20">
        <p className="text-sm text-rose-300">{ficha.error}</p>
      </Cartao>
    );
  }
  const m = ficha as FreguesiaContacto;
  return (
    <div className="space-y-3">
      <Cartao>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">{m.freguesia}</h2>
            <p className="text-xs text-muted-foreground">
              {m.municipio ?? "—"} · Código INE {m.codigo_ine}
            </p>
          </div>
          {m.nif ? <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">NIF {m.nif}</span> : null}
        </div>
      </Cartao>

      {m.nome_presidente ? (
        <Cartao>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Presidente da Junta</p>
          <p className="mt-1 text-sm font-medium">{m.nome_presidente}</p>
        </Cartao>
      ) : null}

      <Cartao>
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Morada</p>
        <p className="mt-1 flex items-start gap-1.5 text-sm">
          <MapPin size={14} className="mt-0.5 shrink-0 text-teal-300/70" />
          {moradaCompacta(m.morada, m.localidade, m.codigo_postal)}
        </p>
      </Cartao>

      <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        {m.telefone ? (
          <Cartao>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Telefone</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm tabular-nums">
              <Phone size={14} className="shrink-0 text-teal-300/70" />
              <a href={`tel:${m.telefone}`} className="hover:underline">{telefoneFormatado(m.telefone)}</a>
            </p>
          </Cartao>
        ) : null}
        {m.email ? (
          <Cartao>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">E-mail</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm">
              <Mail size={14} className="shrink-0 text-teal-300/70" />
              <a href={`mailto:${m.email}`} className="hover:underline">{m.email}</a>
            </p>
          </Cartao>
        ) : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- página */

export default function FreguesiasContactosPage() {
  const [stats, setStats] = useState<FreguesiasContactosStats | null>(null);
  const [dados, setDados] = useState<FreguesiasContactosResponse | null>(null);
  const [detalhe, setDetalhe] = useState<FreguesiaContactoFicha | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [aDetalhar, setADetalhar] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [municipio, setMunicipio] = useState("");
  const [alvoDetalhe, setAlvoDetalhe] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const carregar = useCallback(
    async (pagina = 1) => {
      setACarregar(true);
      setErro(null);
      try {
        const resposta = await getFreguesiasContactos({
          q: q.trim() || undefined,
          municipio: municipio || undefined,
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
    [q, municipio],
  );

  useEffect(() => {
    void carregar(1);
  }, [carregar]);

  useEffect(() => {
    getFreguesiasContactosStats().then(setStats).catch(() => setStats(null));
  }, []);

  const abrir = useCallback((freguesia: FreguesiaContacto) => {
    setAlvoDetalhe(freguesia.codigo_ine);
  }, []);

  useEffect(() => {
    if (!alvoDetalhe) return;
    let ativo = true;
    setADetalhar(true);
    setErro(null);
    getFreguesiaContacto(alvoDetalhe)
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
      await recolherFreguesiasContactos(true);
      await carregar(1);
      setStats(await getFreguesiasContactosStats().catch(() => null));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setARecolher(false);
    }
  }, [carregar]);

  const municipios = useMemo(
    () => (dados?.municipios ?? stats?.por_municipio ?? []).map((d) => d.key).sort((a, b) => a.localeCompare(b)),
    [dados, stats],
  );
  const totalPaginas = dados ? Math.max(1, Math.ceil(dados.total / dados.size)) : 1;

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="space-y-4 p-4 lg:p-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold">Contactos das juntas de freguesia</h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Lista de contactos das juntas de freguesia — presidente, morada, e-mail,
              telefone e código INE. A pesquisa funciona como o Google: procura em qualquer campo.
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
          <Kpi label="Freguesias" valor={String(stats?.documents ?? dados?.total ?? "—")} />
          <Kpi label="Municípios" valor={String(municipios.length)} />
          <Kpi
            label="Com e-mail"
            valor={String(dados?.items?.filter((m) => m.email).length ?? "—")}
            nota="apenas página atual"
          />
          <Kpi
            label="Com telefone"
            valor={String(dados?.items?.filter((m) => m.telefone).length ?? "—")}
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
                placeholder="Procurar freguesia, presidente, e-mail, morada, telefone ou código INE"
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
              value={municipio}
              onChange={(evento) => setMunicipio(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              <option value="">Todos os municípios</option>
              {municipios.map((nome) => (
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
                    <th className="px-3 py-2 font-medium">Freguesia</th>
                    <th className="px-3 py-2 font-medium">Município</th>
                    <th className="px-3 py-2 font-medium">Presidente</th>
                    <th className="px-3 py-2 font-medium">Contacto</th>
                  </tr>
                </thead>
                <tbody>
                  {(dados?.items ?? []).map((m) => (
                    <tr
                      key={m.doc_id || m.codigo_ine}
                      onClick={() => void abrir(m)}
                      className={`cursor-pointer border-t border-white/5 transition hover:bg-white/5 ${
                        detalhe?.codigo_ine === m.codigo_ine ? "bg-white/[0.07]" : ""
                      }`}
                      title="Abrir a ficha desta freguesia"
                    >
                      <td className="px-3 py-1.5 font-medium">
                        <span className="flex items-center gap-2">
                          <Building2 size={11} className="shrink-0 text-teal-300/70" />
                          {m.freguesia}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.municipio ?? "—"}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.nome_presidente ?? "—"}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">
                        {m.email || m.telefone ? (
                          <span className="flex items-center gap-2">
                            {m.email ? <Mail size={11} /> : null}
                            {m.telefone ? <Phone size={11} /> : null}
                            <span className="truncate max-w-[180px]">{m.email || telefoneFormatado(m.telefone)}</span>
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
                        Nenhuma freguesia com os filtros atuais.
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
              <FichaContacto key={detalhe.codigo_ine} ficha={detalhe} />
            ) : (
              <Cartao>
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <Info size={14} /> Escolha uma freguesia
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Clique numa linha para ver os contactos detalhados: presidente, morada,
                  telefone e e-mail.
                </p>
              </Cartao>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
