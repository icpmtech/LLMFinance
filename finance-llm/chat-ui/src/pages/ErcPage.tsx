/**
 * Página do módulo **ERC · Portal da Transparência**.
 *
 * Três vistas sobre a mesma recolha do portal da ERC
 * (`portaltransparencia.erc.pt`):
 *
 * 1. **Painel** — contagens, distritos, tipos de sociedade e funções/cargos;
 * 2. **Entidades** — as entidades proprietárias de órgãos de comunicação social,
 *    com os OCS que detêm, as pessoas dos órgãos sociais e a estrutura de
 *    propriedade (quem as detém e o que detêm);
 * 3. **Pessoas** — as pessoas reguladas, com os cargos (empresas onde são
 *    gerentes/administradoras) e as participações diretas.
 *
 * A recolha corre em segundo plano (`POST /erc/recolher`) e o progresso é
 * seguido por `GET /erc/jobs`. Sem Elasticsearch, a pesquisa cai no disco
 * (`origem: jsonl`), pelo que a página continua a funcionar.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BadgeCheck,
  Building2,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileSpreadsheet,
  Loader2,
  Percent,
  Play,
  RefreshCw,
  Search,
  Tv,
  Users,
} from "lucide-react";

import {
  buscarEntidades,
  buscarOcs,
  buscarPessoas,
  count,
  getErcJobs,
  getErcMeta,
  getErcResumo,
  indexarErc,
  percentagem,
  recolherErc,
  relacaoLabel,
  shortDate,
  ercExportUrl,
  type ErcEntidade,
  type ErcFaceta,
  type ErcJob,
  type ErcMeta,
  type ErcOcs,
  type ErcParticipacao,
  type ErcPessoa,
  type ErcResumo,
} from "../ercApi";

const PAGE_SIZE = 20;

type Aba = "painel" | "entidades" | "pessoas" | "ocs";

const ABAS: { id: Aba; label: string }[] = [
  { id: "painel", label: "Painel" },
  { id: "entidades", label: "Entidades" },
  { id: "pessoas", label: "Pessoas" },
  { id: "ocs", label: "Órgãos de comunicação social" },
];

/* ------------------------------------------------------------- primitivas */

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="glass-card rounded-2xl px-4 py-3" title={hint}>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "sky" | "emerald" | "violet" | "amber";
}) {
  const tones: Record<string, string> = {
    neutral: "border-white/10 bg-white/5 text-muted-foreground",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>{children}</span>
  );
}

/** Lista de contagens em barras (distritos, funções, tipos). */
function BarList({ titulo, itens }: { titulo: string; itens: ErcFaceta[] }) {
  const maximo = Math.max(1, ...itens.map((item) => item.count));
  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-xs font-semibold">{titulo}</h3>
      {itens.length === 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">Sem dados recolhidos.</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {itens.map((item) => (
            <li key={String(item.key)} className="text-[11px]">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate" title={String(item.key)}>
                  {String(item.key)}
                </span>
                <span className="tabular-nums text-muted-foreground">{count(item.count)}</span>
              </div>
              <div className="mt-0.5 h-1 w-full rounded-full bg-white/5">
                <div className="h-1 rounded-full bg-sky-400/60" style={{ width: `${(item.count / maximo) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Tabela de ligações de capital (detentores ou detidas). */
function Participacoes({ titulo, itens }: { titulo: string; itens?: ErcParticipacao[] }) {
  if (!itens?.length) return null;
  return (
    <div>
      <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{titulo}</h4>
      <table className="mt-1 w-full text-[11px]">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 text-left font-medium">Nome</th>
            <th className="py-1 text-left font-medium">Relação</th>
            <th className="py-1 text-right font-medium">Detenção</th>
            <th className="py-1 text-right font-medium">Direitos de voto</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((item, indice) => (
            <tr key={`${item.id ?? item.nome}-${indice}`} className="border-t border-white/5">
              <td className="py-1 pr-2">
                <span className="inline-flex items-center gap-1">
                  {item.e_pessoa ? <Users size={11} /> : <Building2 size={11} />}
                  <span className="truncate" title={item.nome}>
                    {item.nome}
                  </span>
                </span>
              </td>
              <td className="py-1 pr-2 text-muted-foreground">{relacaoLabel(item)}</td>
              <td className="py-1 text-right tabular-nums">{percentagem(item.percentagem, item.percentagem_valor)}</td>
              <td className="py-1 text-right tabular-nums">
                {percentagem(item.direitos_voto, item.direitos_voto_valor)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Cartão de uma entidade, com as listas que o portal publica por separadores. */
function EntidadeCard({ entidade }: { entidade: ErcEntidade }) {
  const [aberto, setAberto] = useState(false);
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <button type="button" onClick={() => setAberto((valor) => !valor)} className="min-w-0 text-left">
          <h3 className="truncate text-sm font-semibold" title={entidade.nome}>
            {entidade.nome}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {[entidade.tipo_sociedade, entidade.actividade_principal, entidade.distrito].filter(Boolean).join(" · ") || "—"}
          </p>
        </button>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="violet">
            <Tv size={10} /> {count(entidade.n_ocs)} OCS
          </Badge>
          <Badge tone="sky">
            <Users size={10} /> {count(entidade.n_pessoas)} pessoas
          </Badge>
          <Badge tone="emerald">
            <Percent size={10} /> {count(entidade.n_detentores)} detentores
          </Badge>
          {entidade.url ? (
            <a
              href={entidade.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
              title="Abrir a ficha no portal da ERC"
            >
              <ExternalLink size={11} /> Portal
            </a>
          ) : null}
        </div>
      </div>

      {aberto ? (
        <div className="mt-3 space-y-3 border-t border-white/5 pt-3">
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Capital social</dt>
              <dd>{entidade.capital_social ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Contabilidade organizada</dt>
              <dd>{entidade.contabilidade_organizada === null ? "—" : entidade.contabilidade_organizada ? "Sim" : "Não"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Detém OCS</dt>
              <dd>{entidade.detem_ocs === null ? "—" : entidade.detem_ocs ? "Sim" : "Não"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Registo ERC</dt>
              <dd>{entidade.nr_registo ?? "—"}</dd>
            </div>
          </dl>

          {entidade.pessoas?.length ? (
            <div>
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Órgãos sociais ({entidade.pessoas.length})
              </h4>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {entidade.pessoas.map((pessoa, indice) => (
                  <li key={`${pessoa.id ?? pessoa.nome}-${indice}`}>
                    <Badge>
                      <BadgeCheck size={10} /> {pessoa.nome}
                      {pessoa.funcao ? ` · ${pessoa.funcao}` : ""}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {entidade.ocs?.length ? (
            <div>
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Órgãos de comunicação social ({entidade.ocs.length})
              </h4>
              <ul className="mt-1 space-y-0.5 text-[11px]">
                {entidade.ocs.map((ocs, indice) => (
                  <li key={`${ocs.designacao}-${indice}`} className="flex items-center justify-between gap-2">
                    <span className="truncate" title={ocs.designacao}>
                      {ocs.designacao}
                    </span>
                    <span className="text-muted-foreground">{[ocs.tipo, ocs.distrito].filter(Boolean).join(" · ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <Participacoes titulo="Entidades detentoras" itens={entidade.detentores} />
          <Participacoes titulo="Entidades detidas" itens={entidade.detidas} />

          {entidade.recolhido_em ? (
            <p className="text-[10px] text-muted-foreground">Recolhido em {shortDate(entidade.recolhido_em)}</p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

/** Cartão de uma pessoa regulada. */
function PessoaCard({ pessoa }: { pessoa: ErcPessoa }) {
  const [aberto, setAberto] = useState(false);
  return (
    <article className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <button type="button" onClick={() => setAberto((valor) => !valor)} className="min-w-0 text-left">
          <h3 className="truncate text-sm font-semibold" title={pessoa.nome}>
            {pessoa.nome}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {[pessoa.actividade_principal, pessoa.distrito].filter(Boolean).join(" · ") || "—"}
          </p>
        </button>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="sky">
            <BadgeCheck size={10} /> {count(pessoa.n_empresas)} cargos
          </Badge>
          <Badge tone="emerald">
            <Percent size={10} /> {count(pessoa.n_participacoes)} participações
          </Badge>
          {pessoa.url ? (
            <a
              href={pessoa.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-sky-200 hover:text-sky-100"
            >
              <ExternalLink size={11} /> Portal
            </a>
          ) : null}
        </div>
      </div>

      {aberto ? (
        <div className="mt-3 space-y-3 border-t border-white/5 pt-3">
          {pessoa.orgaos?.length ? (
            <div>
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Órgãos sociais ({pessoa.orgaos.length})
              </h4>
              <ul className="mt-1 space-y-0.5 text-[11px]">
                {pessoa.orgaos.map((orgao, indice) => (
                  <li key={`${orgao.id ?? orgao.nome}-${indice}`} className="flex items-center justify-between gap-2">
                    <span className="truncate" title={orgao.nome}>
                      {orgao.nome}
                    </span>
                    <span className="text-muted-foreground">
                      {[orgao.tipo_orgao, orgao.funcao].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <Participacoes titulo="Participações diretas" itens={pessoa.participacoes} />
          {pessoa.recolhido_em ? (
            <p className="text-[10px] text-muted-foreground">Recolhido em {shortDate(pessoa.recolhido_em)}</p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

/** Cartão de um órgão de comunicação social. */
function OcsCard({ ocs }: { ocs: ErcOcs }) {
  return (
    <article className="glass-card rounded-2xl px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="truncate text-sm font-semibold" title={ocs.designacao}>
          {ocs.designacao}
        </h3>
        <div className="flex items-center gap-1.5">
          {ocs.tipo ? <Badge tone="violet">{ocs.tipo}</Badge> : null}
          {ocs.distrito ? <Badge>{ocs.distrito}</Badge> : null}
        </div>
      </div>
      {ocs.entidade_proprietaria ? (
        <p className="mt-0.5 text-[11px] text-muted-foreground">Proprietária: {ocs.entidade_proprietaria}</p>
      ) : null}
    </article>
  );
}

/** Barra de progresso do trabalho de recolha. */
function ProgressoJob({ job }: { job: ErcJob }) {
  const progresso = job.progress ?? {};
  const total = job.tipo === "indexar" ? progresso.registos ?? 0 : (progresso.entidades_total ?? 0) + (progresso.pessoas_total ?? 0);
  const feito = (progresso.entidades_done ?? 0) + (progresso.pessoas_done ?? 0);
  const percentual = total ? Math.min(100, (feito / total) * 100) : undefined;
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="inline-flex items-center gap-2">
          {job.status === "running" ? <Loader2 size={13} className="animate-spin" /> : null}
          <strong className="capitalize">{job.tipo}</strong>
          <span className="text-muted-foreground">{progresso.phase ?? job.status}</span>
        </span>
        <span className="tabular-nums text-muted-foreground">
          {count(progresso.entidades_done)}/{count(progresso.entidades_total)} entidades ·{" "}
          {count(progresso.pessoas_done)}/{count(progresso.pessoas_total)} pessoas
          {progresso.current ? ` · ${progresso.current}` : ""}
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-white/5">
        <div
          className="h-1.5 rounded-full bg-emerald-400/70 transition-all"
          style={{ width: `${percentual ?? (job.status === "running" ? 8 : 100)}%` }}
        />
      </div>
      {job.error ? <p className="mt-2 text-[11px] text-red-300">{job.error}</p> : null}
      {job.finished_at ? (
        <p className="mt-1 text-[10px] text-muted-foreground">Terminado em {shortDate(job.finished_at)}</p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ página */

export default function ErcPage() {
  const [aba, setAba] = useState<Aba>("painel");
  const [meta, setMeta] = useState<ErcMeta | null>(null);
  const [resumo, setResumo] = useState<ErcResumo | null>(null);
  const [jobs, setJobs] = useState<ErcJob[]>([]);
  const [jobVisivel, setJobVisivel] = useState<ErcJob | null>(null);
  const seguidoRef = useRef(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const [distrito, setDistrito] = useState("");
  const [tipoSociedade, setTipoSociedade] = useState("");
  const [empresa, setEmpresa] = useState("");
  const [funcao, setFuncao] = useState("");
  const [tipoOcs, setTipoOcs] = useState("");
  const [q, setQ] = useState("");
  const [termo, setTermo] = useState("");
  const [pagina, setPagina] = useState(0);

  const [entidades, setEntidades] = useState<ErcEntidade[]>([]);
  const [pessoas, setPessoas] = useState<ErcPessoa[]>([]);
  const [ocs, setOcs] = useState<ErcOcs[]>([]);
  const [total, setTotal] = useState(0);
  const [origem, setOrigem] = useState<string | null>(null);
  const [aCarregar, setACarregar] = useState(false);

  const carregarPainel = useCallback(async () => {
    try {
      const [novoMeta, novoResumo] = await Promise.all([getErcMeta(), getErcResumo()]);
      setMeta(novoMeta);
      setResumo(novoResumo);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Falha ao carregar o módulo.");
    }
  }, []);

  const carregarJobs = useCallback(async () => {
    try {
      const resultado = await getErcJobs();
      const items = resultado.items ?? [];
      setJobs(items);
      // Só se mostra o painel do trabalho se ele estiver a correr (ou se o
      // vimos correr nesta sessão): assim não aparece um trabalho antigo.
      const corrente = items.find((item) => item.status === "running");
      if (corrente) {
        seguidoRef.current = true;
        setJobVisivel(corrente);
      } else if (seguidoRef.current && items[0]) {
        setJobVisivel(items[0]);
      }
    } catch {
      /* o painel de trabalhos é informativo */
    }
  }, []);

  useEffect(() => {
    void carregarPainel();
    void carregarJobs();
  }, [carregarPainel, carregarJobs]);

  const aCorrer = useMemo(() => jobs.some((job) => job.status === "running"), [jobs]);

  useEffect(() => {
    if (!aCorrer) return;
    const id = window.setInterval(() => {
      void carregarJobs();
    }, 4000);
    return () => window.clearInterval(id);
  }, [aCorrer, carregarJobs]);

  useEffect(() => {
    if (!aCorrer) return;
    const id = window.setInterval(() => {
      void carregarPainel();
    }, 15000);
    return () => window.clearInterval(id);
  }, [aCorrer, carregarPainel]);

  const consulta = useMemo(
    () => ({
      q: termo || undefined,
      distrito: distrito || undefined,
      tipo_sociedade: tipoSociedade || undefined,
      empresa: empresa || undefined,
      funcao: funcao || undefined,
      tipo: tipoOcs || undefined,
      page: pagina + 1,
      size: PAGE_SIZE,
    }),
    [termo, distrito, tipoSociedade, empresa, funcao, tipoOcs, pagina],
  );

  useEffect(() => {
    if (aba === "painel") return;
    let cancelado = false;
    setACarregar(true);
    const pedido =
      aba === "entidades"
        ? buscarEntidades({ q: consulta.q, distrito: consulta.distrito, tipo_sociedade: consulta.tipo_sociedade, page: consulta.page, size: consulta.size })
        : aba === "pessoas"
          ? buscarPessoas({ q: consulta.q, distrito: consulta.distrito, empresa: consulta.empresa, funcao: consulta.funcao, page: consulta.page, size: consulta.size })
          : buscarOcs({ q: consulta.q, distrito: consulta.distrito, tipo: consulta.tipo, page: consulta.page, size: consulta.size });

    pedido
      .then((resultado) => {
        if (cancelado) return;
        setErro(resultado.error ? String(resultado.error) : null);
        setTotal(resultado.total ?? 0);
        setOrigem(resultado.origem ?? null);
        if (aba === "entidades") setEntidades((resultado.items ?? []) as ErcEntidade[]);
        else if (aba === "pessoas") setPessoas((resultado.items ?? []) as ErcPessoa[]);
        else setOcs((resultado.items ?? []) as ErcOcs[]);
      })
      .catch((err) => {
        if (!cancelado) setErro(err instanceof Error ? err.message : "Falha na pesquisa.");
      })
      .finally(() => {
        if (!cancelado) setACarregar(false);
      });
    return () => {
      cancelado = true;
    };
  }, [aba, consulta]);

  const submeter = (event?: React.FormEvent) => {
    event?.preventDefault();
    setPagina(0);
    setTermo(q.trim());
  };

  const limpar = () => {
    setQ("");
    setTermo("");
    setDistrito("");
    setTipoSociedade("");
    setEmpresa("");
    setFuncao("");
    setTipoOcs("");
    setPagina(0);
  };

  const [abordagem, setAbordagem] = useState(false);
  const [limite, setLimite] = useState("");
  const [trabalhadores, setTrabalhadores] = useState(3);
  const [guardarHtml, setGuardarHtml] = useState(false);
  const [comFinanceiro, setComFinanceiro] = useState(false);
  const [retomar, setRetomar] = useState(true);

  const recolher = async () => {
    setOcupado(true);
    try {
      await recolherErc({
        limite: limite ? Number(limite) : undefined,
        trabalhadores,
        guardar_html: guardarHtml,
        com_financeiro: comFinanceiro,
        saltar_existentes: retomar,
      });
      await carregarJobs();
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não foi possível arrancar a recolha.");
    } finally {
      setOcupado(false);
    }
  };

  const indexar = async () => {
    setOcupado(true);
    try {
      await indexarErc({ forcar: false });
      await carregarJobs();
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não foi possível arrancar a indexação.");
    } finally {
      setOcupado(false);
    }
  };

  const distritos = useMemo(() => (resumo?.distritos ?? []).map((item) => String(item.key)), [resumo]);
  const tiposSociedade = useMemo(() => (resumo?.tipos_sociedade ?? []).map((item) => String(item.key)), [resumo]);
  const tiposOcs = useMemo(() => (resumo?.tipos_ocs ?? []).map((item) => String(item.key)), [resumo]);

  const from = total ? pagina * PAGE_SIZE + 1 : 0;
  const to = Math.min(total, (pagina + 1) * PAGE_SIZE);
  const ultimaPagina = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
  const semDados = (meta?.contagens.entidades ?? 0) === 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Tv size={18} /> ERC · Portal da Transparência
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Entidades proprietárias de órgãos de comunicação social, as pessoas dos seus órgãos sociais, os OCS detidos
            e a estrutura de propriedade (quem detém quem), recolhidos de{" "}
            <a href={meta?.portal ?? "https://portaltransparencia.erc.pt"} target="_blank" rel="noreferrer" className="underline">
              portaltransparencia.erc.pt
            </a>
            .
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setAbordagem((valor) => !valor)}
            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${
              abordagem ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-100" : "border-white/10 bg-white/5 hover:bg-white/10"
            }`}
            title="Opções da recolha do portal (segundo plano)"
          >
            <Play size={13} /> Recolher
          </button>
          <button
            type="button"
            onClick={indexar}
            disabled={ocupado}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-50"
            title="Indexar o que está em disco no Elasticsearch"
          >
            <FileSpreadsheet size={13} /> Indexar
          </button>
          <a
            href={ercExportUrl("entidades")}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
          >
            <Download size={13} /> CSV
          </a>
          <button
            type="button"
            onClick={() => {
              void carregarPainel();
              void carregarJobs();
            }}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
          >
            {aCarregar ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Atualizar
          </button>
        </div>
      </header>

      {erro ? <div className="glass-card rounded-2xl border-red-400/20 p-3 text-[11px] text-red-200">{erro}</div> : null}

      {jobVisivel ? <ProgressoJob job={jobVisivel} /> : null}

      {abordagem ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void recolher();
          }}
          className="glass-card space-y-3 rounded-2xl p-4"
        >
          <h2 className="text-xs font-semibold">Recolha do portal da ERC</h2>
          <p className="text-[11px] text-muted-foreground">
            Corre em segundo plano no servidor; o progresso aparece acima. Com <strong>retomar</strong> ligado, o que já
            está gravado não é relido — parar e recomeçar não repete trabalho.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Limite de entidades
              <input
                value={limite}
                onChange={(event) => setLimite(event.target.value.replace(/\D/g, ""))}
                placeholder="todas"
                className="w-28 rounded-xl border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Pedidos em paralelo
              <select
                value={trabalhadores}
                onChange={(event) => setTrabalhadores(Number(event.target.value))}
                className="rounded-xl border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-foreground"
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <input type="checkbox" checked={retomar} onChange={(event) => setRetomar(event.target.checked)} />
              Retomar (ignorar o que já está gravado)
            </label>
            <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <input type="checkbox" checked={guardarHtml} onChange={(event) => setGuardarHtml(event.target.checked)} />
              Guardar o HTML das páginas
            </label>
            <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={comFinanceiro}
                onChange={(event) => setComFinanceiro(event.target.checked)}
              />
              Incluir dados financeiros (mais lento)
            </label>
            <button
              type="submit"
              disabled={ocupado}
              className="inline-flex items-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50"
            >
              {ocupado ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} Arrancar recolha
            </button>
          </div>
        </form>
      ) : null}

      <nav className="flex flex-wrap gap-1.5">
        {ABAS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              setAba(item.id);
              setPagina(0);
            }}
            className={`rounded-xl border px-3 py-1.5 text-xs ${
              aba === item.id ? "border-sky-400/40 bg-sky-400/10 text-sky-100" : "border-white/10 bg-white/5 hover:bg-white/10"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Entidades" value={count(meta?.contagens.entidades)} hint={`portal: ${count(meta?.listagem.total_portal)}`} />
        <Kpi label="Pessoas" value={count(meta?.contagens.pessoas)} hint={resumo ? `${count(resumo.pessoas_com_cargos)} com cargos` : undefined} />
        <Kpi label="OCS" value={count(meta?.contagens.ocs)} />
        <Kpi
          label="Distritos"
          value={count(meta?.contagens.distritos)}
          hint={meta?.listagem.cached_at ? `listagem de ${shortDate(meta.listagem.cached_at)}` : undefined}
        />
      </div>

      {semDados ? (
        <div className="glass-card rounded-2xl p-4 text-xs text-muted-foreground">
          Ainda não há dados recolhidos. Carregue em <strong>Recolher</strong> (corre em segundo plano no servidor) ou
          use <code>POST /erc/recolher</code> com um <code>limite</code> para uma amostra.
        </div>
      ) : null}

      {aba === "painel" ? (
        <div className="grid gap-3 lg:grid-cols-3">
          <BarList titulo="Distritos" itens={resumo?.distritos ?? []} />
          <BarList titulo="Funções/cargos" itens={(resumo?.funcoes ?? []).slice(0, 12)} />
          <BarList titulo="Tipos de OCS" itens={resumo?.tipos_ocs ?? []} />
          <BarList titulo="Tipos de sociedade" itens={resumo?.tipos_sociedade ?? []} />
          <BarList titulo="Atividade principal" itens={resumo?.actividades ?? []} />
          <div className="glass-card rounded-2xl p-4 text-[11px] text-muted-foreground">
            <h3 className="text-xs font-semibold text-foreground">Índices</h3>
            <ul className="mt-2 space-y-1">
              <li>
                Entidades: <code>{meta?.indices.entidades ?? "—"}</code>
              </li>
              <li>
                Pessoas: <code>{meta?.indices.pessoas ?? "—"}</code>
              </li>
              <li>
                OCS: <code>{meta?.indices.ocs ?? "—"}</code>
              </li>
              <li>
                Recolhas: <code>{meta?.indices.recolhas ?? "—"}</code>
              </li>
            </ul>
            <p className="mt-2">
              Pasta de dados: <code>{meta?.data_dir ?? "—"}</code>
            </p>
            <p className="mt-2">
              {count(resumo?.entidades_sem_ocs)} entidades sem OCS · {count(resumo?.pessoas_com_participacoes)} pessoas com
              participações
            </p>
          </div>
        </div>
      ) : (
        <>
          <form onSubmit={submeter} className="glass-card flex flex-wrap items-end gap-2 rounded-2xl p-3">
            <label className="flex min-w-[240px] flex-1 flex-col gap-1 text-[11px] text-muted-foreground">
              Pesquisar
              <span className="relative">
                <Search size={13} className="absolute left-2 top-2.5 text-muted-foreground" />
                <input
                  id="erc-search"
                  value={q}
                  onChange={(event) => setQ(event.target.value)}
                  placeholder={
                    aba === "entidades"
                      ? "Nome, OCS detido ou pessoa dos órgãos sociais…"
                      : aba === "pessoas"
                        ? "Nome, empresa ou participação…"
                        : "Designação ou entidade proprietária…"
                  }
                  className="w-full rounded-xl border border-white/10 bg-black/20 py-2 pl-7 pr-2 text-xs text-foreground"
                />
              </span>
            </label>

            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Distrito
              <select
                value={distrito}
                onChange={(event) => setDistrito(event.target.value)}
                className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
              >
                <option value="">Todos</option>
                {distritos.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>

            {aba === "entidades" ? (
              <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                Tipo de sociedade
                <select
                  value={tipoSociedade}
                  onChange={(event) => setTipoSociedade(event.target.value)}
                  className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
                >
                  <option value="">Todos</option>
                  {tiposSociedade.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            {aba === "pessoas" ? (
              <>
                <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                  Empresa
                  <input
                    value={empresa}
                    onChange={(event) => setEmpresa(event.target.value)}
                    placeholder="ex.: Rádio Regional"
                    className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
                  />
                </label>
                <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                  Função
                  <input
                    value={funcao}
                    onChange={(event) => setFuncao(event.target.value)}
                    placeholder="ex.: Gerente"
                    className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
                  />
                </label>
              </>
            ) : null}

            {aba === "ocs" ? (
              <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                Tipo
                <select
                  value={tipoOcs}
                  onChange={(event) => setTipoOcs(event.target.value)}
                  className="rounded-xl border border-white/10 bg-black/20 px-2 py-2 text-xs text-foreground"
                >
                  <option value="">Todos</option>
                  {tiposOcs.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <button
              type="submit"
              className="inline-flex items-center gap-2 rounded-xl border border-sky-400/30 bg-sky-400/10 px-3 py-2 text-xs text-sky-100 hover:bg-sky-400/20"
            >
              <Search size={13} /> Pesquisar
            </button>
            <button
              type="button"
              onClick={limpar}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10"
            >
              Limpar
            </button>
          </form>

          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>
              {count(total)} resultado(s) · {total ? `${from}–${to}` : "sem resultados"}
              {origem ? ` · fonte: ${origem}` : ""}
            </span>
            <span className="flex items-center gap-1.5">
              <a href={ercExportUrl(aba === "pessoas" ? "pessoas" : aba === "ocs" ? "ocs" : "entidades")} className="inline-flex items-center gap-1 hover:text-foreground">
                <Download size={11} /> Exportar este conjunto
              </a>
            </span>
          </div>

          {aCarregar ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" /> A carregar…
            </p>
          ) : null}

          <div className="space-y-2">
            {aba === "entidades"
              ? entidades.map((item) => <EntidadeCard key={item.doc_id} entidade={item} />)
              : aba === "pessoas"
                ? pessoas.map((item) => <PessoaCard key={item.doc_id} pessoa={item} />)
                : ocs.map((item) => <OcsCard key={item.doc_id ?? item.designacao} ocs={item} />)}
            {!aCarregar && total === 0 ? (
              <p className="glass-card rounded-2xl p-4 text-xs text-muted-foreground">
                Sem resultados. {semDados ? "Comece por correr a recolha." : "Tente outro termo ou limpe os filtros."}
              </p>
            ) : null}
          </div>

          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setPagina((valor) => Math.max(0, valor - 1))}
              disabled={pagina === 0}
              className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40"
            >
              <ChevronLeft size={13} /> Anterior
            </button>
            <span className="text-[11px] text-muted-foreground">
              Página {pagina + 1} de {Math.max(1, ultimaPagina + 1)}
            </span>
            <button
              type="button"
              onClick={() => setPagina((valor) => Math.min(ultimaPagina, valor + 1))}
              disabled={pagina >= ultimaPagina}
              className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40"
            >
              Seguinte <ChevronRight size={13} />
            </button>
          </div>
        </>
      )}
    </div>
  );
}
