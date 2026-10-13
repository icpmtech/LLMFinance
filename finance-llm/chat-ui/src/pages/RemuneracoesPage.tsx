/**
 * Página do módulo **Remunerações dos Eleitos Locais**.
 *
 * Junta as duas peças que só fazem sentido juntas:
 *
 * 1. a **tabela oficial** dos abonos — a remuneração do presidente da
 *    junta/câmara é uma percentagem da remuneração do Presidente da República,
 *    por escalão de eleitores (freguesias: Lei n.º 11/96; municípios: Estatuto
 *    dos Eleitos Locais, Lei n.º 29/87);
 * 2. o **território** — quantos eleitores inscritos tem cada concelho e cada
 *    freguesia (recenseamento do MAI) e onde fica cada um.
 *
 * É o cruzamento que dá a resposta: só sabendo quantos eleitores tem o concelho
 * (ou a freguesia) se sabe em que escalão cai e, portanto, quanto é que recebe.
 *
 * O mapa é do **OpenStreetMap** e é navegável (arrastar, roda do rato, +/−,
 * enquadrar): pinta um ponto por concelho pelo valor da métrica escolhida e, ao
 * escolher um concelho, mostra as freguesias desse município — cada uma com os
 * seus eleitores e o abono que lhe cabe.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Info,
  Layers,
  Loader2,
  MapPin,
  RefreshCw,
  Scale,
  Search,
  Users,
} from "lucide-react";

import MapaOSM, { type MapaPonto, type MetricaMapa } from "../components/remuneracoes/MapaOSM";
import {
  buscarConcelhos,
  buscarFreguesias,
  buscarPessoas,
  euro,
  getCamaras,
  getConcelho,
  getMapaRemuneracoes,
  getMunicipios,
  getRemuneracoesMeta,
  getRemuneracoesStats,
  getRemuneracoesTabelas,
  nivelLabel,
  notaCriacao,
  numero,
  percentagem,
  recolherRemuneracoes,
  type RemuneracoesCamara,
  type RemuneracoesConcelho,
  type RemuneracoesConcelhoDetail,
  type RemuneracoesEleitos,
  type RemuneracoesEscalao,
  type RemuneracoesFreguesia,
  type RemuneracoesMapa,
  type RemuneracoesMeta,
  type RemuneracoesMunicipio,
  type RemuneracoesPessoa,
  type RemuneracoesRubrica,
  type RemuneracoesStats,
  type RemuneracoesTabela,
  type RemuneracoesVerba,
} from "../remuneracoesApi";

const PAGE_SIZE = 500;

type Aba = "mapa" | "concelhos" | "brasões" | "freguesias" | "eleitos" | "camaras" | "tabela";

const ABAS: { id: Aba; label: string }[] = [
  { id: "mapa", label: "Mapa" },
  { id: "concelhos", label: "Concelhos" },
  { id: "brasões", label: "Brasões" },
  { id: "freguesias", label: "Freguesias" },
  { id: "eleitos", label: "Eleitos" },
  { id: "camaras", label: "Câmaras" },
  { id: "tabela", label: "Tabela de abonos" },
];

const METRICAS: { id: MetricaMapa; label: string }[] = [
  { id: "eleitores", label: "Eleitores" },
  { id: "votantes", label: "Votantes" },
  { id: "remuneracao", label: "Abono mensal" },
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

function Etiqueta({ children, tom = "neutral" }: { children: React.ReactNode; tom?: string }) {
  const tons: Record<string, string> = {
    neutral: "border-white/10 bg-white/5 text-muted-foreground",
    sky: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] ${tons[tom] ?? tons.neutral}`}
    >
      {children}
    </span>
  );
}

/** Converte uma peça do mapa da API no ponto que o `MapaOSM` desenha. */
function pontoDoMapa(feature: {
  id: number;
  nome: string;
  lat?: number | null;
  lon?: number | null;
  eleitores?: number | null;
  votantes?: number | null;
  escalao?: string | null;
  remuneracao_mensal?: number | null;
  distrito?: string | null;
  concelho?: string | null;
  nivel?: string;
  camara?: {
    foto?: string | null;
    autor?: string | null;
    licenca?: string | null;
    pagina?: string | null;
  } | null;
  brasao?: string | null;
  brasao_autor?: string | null;
  brasao_licenca?: string | null;
  criacao?: string | null;
  criacao_ano?: number | null;
  codigo?: string | null;
  populacao_2021?: number | null;
}): MapaPonto {
  const contexto =
    feature.nivel === "freguesia" ? feature.concelho ?? null : feature.distrito ?? null;
  return {
    id: feature.id,
    nome: feature.nome,
    lat: feature.lat ?? Number.NaN,
    lon: feature.lon ?? Number.NaN,
    eleitores: feature.eleitores,
    votantes: feature.votantes,
    escalao: feature.escalao,
    remuneracao_mensal: feature.remuneracao_mensal,
    contexto,
    foto: feature.camara?.foto ?? null,
    foto_autor: feature.camara?.autor ?? null,
    foto_licenca: feature.camara?.licenca ?? null,
    foto_pagina: feature.camara?.pagina ?? null,
    brasao: feature.brasao ?? null,
    brasao_autor: feature.brasao_autor ?? null,
    brasao_licenca: feature.brasao_licenca ?? null,
    criacao: feature.criacao ?? null,
    criacao_ano: feature.criacao_ano ?? null,
    codigo: feature.codigo ?? null,
    populacao_2021: feature.populacao_2021 ?? null,
  };
}

/**
 * Quem foi eleito em 2025: presidente da câmara, vereadores e o que cada um recebe.
 *
 * Os nomes são os do **Mapa Oficial da CNE** (é o único sítio onde saem os nomes
 * dos vereadores); os mandatos de cada lista e o número de vereadores por partido
 * vêm do MAI. O que o mapa oficial não publicar é dito — nunca inventado.
 */
function EleitosConcelho({ eleitos }: { eleitos?: RemuneracoesEleitos | null }) {
  if (!eleitos || (!eleitos.presidente && !eleitos.vereadores?.por_partido?.length)) {
    return (
      <div className="glass-card rounded-2xl p-4 text-[11px] text-muted-foreground">
        Ainda não há eleitos recolhidos. Corra <code>POST /remuneracoes/eleitos/recolher</code> para
        os trazer do MAI (Autárquicas 2025).
      </div>
    );
  }

  const presidente = eleitos.presidente ?? null;
  const partidos = eleitos.vereadores?.por_partido ?? [];
  const pessoas = eleitos.pessoas ?? [];
  const maior = Math.max(1, ...partidos.map((p) => p.vereadores ?? 0));

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold">Eleitos em 2025 · Câmara Municipal</h3>
        <span className="text-[10px] text-muted-foreground">
          {numero(eleitos.vereadores?.total_mandatos)} mandatos · {numero(eleitos.vereadores?.total)}{" "}
          vereadores
        </span>
      </div>

      {presidente ? (
        <div className="mt-2 rounded-xl border border-amber-300/20 bg-amber-300/5 p-3">
          <p className="text-[10px] uppercase tracking-wide text-amber-200/80">
            Presidente da câmara eleito
          </p>
          <p className="text-sm font-semibold">{presidente.nome}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <Etiqueta tom="amber">{presidente.sigla ?? "—"}</Etiqueta>
            {presidente.partido ? <span>{presidente.partido}</span> : null}
            <span className="tabular-nums">
              {numero(presidente.votos)} votos ({percentagem(presidente.percentagem, 2)})
            </span>
            <span className="tabular-nums">{numero(presidente.mandatos)} mandatos na lista</span>
          </p>
        </div>
      ) : null}

      <ul className="mt-3 space-y-1.5">
        {partidos.map((partido) => (
          <li key={partido.sigla ?? partido.votos ?? 0} className="text-[11px]">
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5">
                <span className="font-medium">{partido.sigla}</span>
                {partido.presidentes ? (
                  <Etiqueta tom="amber">presidência</Etiqueta>
                ) : null}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {numero(partido.vereadores)} vereadores · {numero(partido.mandatos)} mandatos ·{" "}
                {percentagem(partido.percentagem, 2)}
              </span>
            </div>
            <div className="mt-0.5 h-1 w-full rounded-full bg-white/5">
              <div
                className={`h-1 rounded-full ${partido.presidentes ? "bg-amber-300/70" : "bg-sky-400/60"}`}
                style={{ width: `${((partido.vereadores ?? 0) / maior) * 100}%` }}
              />
            </div>
            {partido.nomes?.length ? (
              <p className="mt-1 flex flex-wrap gap-1">
                {partido.nomes.map((nome) =>
                  nome ? (
                    <span
                      key={nome}
                      className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                    >
                      {nome}
                    </span>
                  ) : null,
                )}
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      {pessoas.length ? (
        <div className="mt-3">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Quem foi eleito e quanto recebe
          </p>
          <ul className="mt-1 divide-y divide-white/5">
            {pessoas.map((pessoa) => (
              <li
                key={`${pessoa.nome}-${pessoa.tipo}`}
                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1 text-[11px]"
              >
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  <span className="font-medium">{pessoa.nome}</span>
                  <Etiqueta tom={pessoa.tipo === "presidente" ? "amber" : "sky"}>
                    {pessoa.sigla ?? "—"}
                  </Etiqueta>
                  <span className="text-muted-foreground">{pessoa.cargo ?? "Vereador"}</span>
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {euro(pessoa.remuneracao_mensal)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {eleitos.nomes?.fonte ? (
        <p className="mt-2 text-[10px] text-muted-foreground">
          Nomes: {eleitos.nomes.fonte}
          {eleitos.nomes.total_eleitos
            ? ` — ${numero(eleitos.nomes.total_eleitos)} eleitos para a câmara`
            : ""}
          . Mandatos por lista: MAI (Autárquicas 2025).
        </p>
      ) : eleitos.nota ? (
        <p className="mt-2 text-[10px] text-muted-foreground">{eleitos.nota}</p>
      ) : null}

      {eleitos.nomes?.lacuna?.faltam ? (
        <p className="mt-1 text-[10px] text-amber-200/80">
          O Mapa Oficial não publica {numero(eleitos.nomes.lacuna.faltam)} dos{" "}
          {numero(eleitos.nomes.lacuna.mandatos)} mandatos deste município: por isso faltam nomes à
          lista.
        </p>
      ) : null}

      {eleitos.nomes?.divergencia ? (
        <p className="mt-1 text-[10px] text-amber-200/80">
          Divergência entre fontes: o MAI indica {eleitos.nomes.divergencia.nome_no_mai} e o Mapa
          Oficial {eleitos.nomes.divergencia.nome_no_mapa}. Vale o Mapa Oficial.
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------ pessoas */

const CARGOS: { id: string; label: string }[] = [
  { id: "", label: "Todos os cargos" },
  { id: "presidente", label: "Presidentes de câmara" },
  { id: "vereador", label: "Vereadores" },
  { id: "presidente_junta", label: "Presidentes de junta" },
  { id: "assembleia_freguesia", label: "Assembleias de freguesia" },
];

/** Quem foi eleito, onde e quanto recebe — a lista de pessoas, pesquisável. */
function ListaPessoas() {
  const [pessoas, setPessoas] = useState<RemuneracoesPessoa[]>([]);
  const [total, setTotal] = useState(0);
  const [porTipo, setPorTipo] = useState<Record<string, number>>({});
  const [busca, setBusca] = useState("");
  const [cargo, setCargo] = useState("");
  const [nivel, setNivel] = useState("");
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [fonte, setFonte] = useState<{ fonte?: string | null; url?: string | null; recolhido?: string | null }>({});

  useEffect(() => {
    const temporizador = window.setTimeout(async () => {
      setACarregar(true);
      try {
        const resposta = await buscarPessoas({
          q: busca || undefined,
          cargo: cargo || undefined,
          nivel: nivel || undefined,
          size: 200,
        });
        setPessoas(resposta.items);
        setTotal(resposta.total);
        setPorTipo(resposta.por_tipo ?? {});
        setFonte({ fonte: resposta.fonte, url: resposta.fonte_url, recolhido: resposta.recolhido_em });
        setErro(null);
      } catch (excecao) {
        setErro(excecao instanceof Error ? excecao.message : String(excecao));
      } finally {
        setACarregar(false);
      }
    }, 300);
    return () => window.clearTimeout(temporizador);
  }, [busca, cargo, nivel]);

  return (
    <div className="space-y-3">
      <div className="glass-card rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Procurar por nome, município, freguesia ou partido"
              className="w-full rounded-lg border border-white/10 bg-white/5 py-1.5 pl-8 pr-3 text-xs outline-none placeholder:text-muted-foreground focus:border-teal-400/40"
            />
          </div>
          <select
            value={cargo}
            onChange={(evento) => setCargo(evento.target.value)}
            className="rounded-lg border border-white/10 bg-[#07151b] px-2 py-1.5 text-xs"
          >
            {CARGOS.map((opcao) => (
              <option key={opcao.id} value={opcao.id}>
                {opcao.label}
              </option>
            ))}
          </select>
          <select
            value={nivel}
            onChange={(evento) => setNivel(evento.target.value)}
            className="rounded-lg border border-white/10 bg-[#07151b] px-2 py-1.5 text-xs"
          >
            <option value="">Municípios e freguesias</option>
            <option value="municipio">Só municípios</option>
            <option value="freguesia">Só freguesias</option>
          </select>
          {aCarregar ? <Loader2 size={14} className="animate-spin text-muted-foreground" /> : null}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          <strong className="text-foreground">{numero(total)}</strong> pessoas eleitas
          {Object.keys(porTipo).length
            ? ` — ${Object.entries(porTipo)
                .map(([tipo, quantos]) => `${numero(quantos)} ${rotuloTipo(tipo)}`)
                .join(" · ")}`
            : ""}
          . {fonte.fonte ? <>Fonte: {fonte.recolhido ? `${fonte.fonte}, recolhido em ${fonte.recolhido.slice(0, 10)}` : fonte.fonte}.</> : null}
        </p>
      </div>

      {erro ? <p className="text-[11px] text-rose-300">{erro}</p> : null}

      <div className="glass-card overflow-x-auto rounded-2xl p-3">
        <table className="w-full min-w-[760px] text-[11px]">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Nome</th>
              <th className="py-1.5 pr-3 font-medium">Cargo</th>
              <th className="py-1.5 pr-3 font-medium">Município</th>
              <th className="py-1.5 pr-3 font-medium">Freguesia</th>
              <th className="py-1.5 pr-3 font-medium">Lista</th>
              <th className="py-1.5 pr-3 text-right font-medium">Remuneração mensal</th>
              <th className="py-1.5 text-right font-medium">Eleitores</th>
            </tr>
          </thead>
          <tbody>
            {pessoas.map((pessoa, indice) => (
              <tr key={`${pessoa.nome}-${pessoa.concelho}-${indice}`} className="border-t border-white/5">
                <td className="py-1.5 pr-3 font-medium">{pessoa.nome}</td>
                <td className="py-1.5 pr-3 text-muted-foreground">{pessoa.cargo}</td>
                <td className="py-1.5 pr-3">{pessoa.concelho ?? "—"}</td>
                <td className="py-1.5 pr-3 text-muted-foreground">{pessoa.freguesia ?? "—"}</td>
                <td className="py-1.5 pr-3">{pessoa.sigla ?? "—"}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{euro(pessoa.remuneracao_mensal)}</td>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {numero(pessoa.eleitores)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {pessoas.length === 0 && !aCarregar ? (
          <p className="mt-3 text-[11px] text-muted-foreground">
            Sem resultados. Se a lista estiver vazia no total, recolha os nomes com{" "}
            <code>POST /remuneracoes/eleitos/nomes/recolher</code>.
          </p>
        ) : null}
        {total > pessoas.length ? (
          <p className="mt-2 text-[10px] text-muted-foreground">
            A mostrar {numero(pessoas.length)} de {numero(total)} — refine a pesquisa para ver as restantes.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function rotuloTipo(tipo: string): string {
  const rotulos: Record<string, string> = {
    presidente: "presidentes de câmara",
    vereador: "vereadores",
    presidente_junta: "presidentes de junta",
    assembleia_freguesia: "membros de assembleias de freguesia",
  };
  return rotulos[tipo] ?? tipo;
}

/* ------------------------------------------------------------- câmaras */

/** Os edifícios das câmaras, com foto, créditos e ligação à Wikipédia. */
function GaleriaCamaras() {
  const [camaras, setCamaras] = useState<RemuneracoesCamara[]>([]);
  const [total, setTotal] = useState(0);
  const [busca, setBusca] = useState("");
  const [apenasComFoto, setApenasComFoto] = useState(true);
  const [aCarregar, setACarregar] = useState(false);
  const [fonte, setFonte] = useState<{ nome?: string | null; pagina?: string | null }>({});

  useEffect(() => {
    const temporizador = window.setTimeout(async () => {
      setACarregar(true);
      try {
        const resposta = await getCamaras({
          q: busca || undefined,
          apenas_com_foto: apenasComFoto,
        });
        setCamaras(resposta.items);
        setTotal(resposta.total);
        setFonte({ nome: resposta.fonte, pagina: resposta.pagina });
      } catch {
        setCamaras([]);
      } finally {
        setACarregar(false);
      }
    }, 300);
    return () => window.clearTimeout(temporizador);
  }, [busca, apenasComFoto]);

  return (
    <div className="space-y-3">
      <div className="glass-card rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Procurar câmara municipal ou município"
              className="w-full rounded-lg border border-white/10 bg-white/5 py-1.5 pl-8 pr-3 text-xs outline-none placeholder:text-muted-foreground focus:border-teal-400/40"
            />
          </div>
          <label className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={apenasComFoto}
              onChange={(evento) => setApenasComFoto(evento.target.checked)}
              className="accent-teal-400"
            />
            Só com fotografia
          </label>
          {aCarregar ? <Loader2 size={14} className="animate-spin text-muted-foreground" /> : null}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          <strong className="text-foreground">{numero(total)}</strong> edifícios.{" "}
          {fonte.nome ? <>Fonte: {fonte.nome}. </> : null}
          {fonte.pagina ? (
            <a className="underline hover:text-foreground" href={fonte.pagina} target="_blank" rel="noreferrer">
              Lista das câmaras municipais (Wikipédia)
            </a>
          ) : null}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {camaras.map((camara) => (
          <figure key={camara.wikidata} className="glass-card overflow-hidden rounded-2xl">
            {camara.credito?.url ? (
              <img
                src={camara.credito.url}
                alt={camara.designacao ?? "Câmara municipal"}
                loading="lazy"
                className="h-40 w-full object-cover"
              />
            ) : (
              <div className="flex h-40 w-full items-center justify-center bg-white/5 text-[11px] text-muted-foreground">
                Sem fotografia
              </div>
            )}
            <figcaption className="space-y-1 p-3">
              <p className="text-xs font-semibold">{camara.municipio ?? camara.designacao}</p>
              <p className="text-[11px] text-muted-foreground">{camara.designacao}</p>
              {camara.patrimonio ? <Etiqueta tom="violet">{camara.patrimonio}</Etiqueta> : null}
              <p className="text-[10px] text-muted-foreground">
                {camara.lat !== null && camara.lat !== undefined
                  ? `${camara.lat.toFixed(4)}, ${camara.lon?.toFixed(4)}`
                  : "sem coordenadas"}
                {camara.sipa ? ` · SIPA ${camara.sipa}` : ""}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {camara.credito?.autor ? <>© {camara.credito.autor} </> : null}
                {camara.credito?.licenca ? <>· {camara.credito.licenca}</> : null}
                {camara.credito?.pagina ? (
                  <>
                    {" "}
                    ·{" "}
                    <a className="underline hover:text-foreground" href={camara.credito.pagina} target="_blank" rel="noreferrer">
                      Commons
                    </a>
                  </>
                ) : null}
                {camara.artigo ? (
                  <>
                    {" "}
                    ·{" "}
                    <a className="underline hover:text-foreground" href={camara.artigo} target="_blank" rel="noreferrer">
                      Wikipédia
                    </a>
                  </>
                ) : null}
              </p>
            </figcaption>
          </figure>
        ))}
      </div>
      {camaras.length === 0 && !aCarregar ? (
        <p className="text-[11px] text-muted-foreground">
          Sem fotografias para mostrar. Recolha-as com <code>POST /remuneracoes/camaras/recolher</code>.
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- brasões */

/**
 * Os brasões dos 308 municípios e as datas de criação dos concelhos.
 *
 * A lista e as datas vêm da tabela da Wikipédia «Lista de municípios de
 * Portugal»; os brasões são ficheiros do Wikimedia Commons, com autor e licença.
 * Onde a tabela não traz imagem, o brasão vem do Wikidata e é dito qual foi o
 * caso — como tudo o resto no módulo, nada se inventa.
 */
function GaleriaBrasoes() {
  const [municipios, setMunicipios] = useState<RemuneracoesMunicipio[]>([]);
  const [resumo, setResumo] = useState({ total: 0, comBrasao: 0, comData: 0 });
  const [busca, setBusca] = useState("");
  const [ordem, setOrdem] = useState<"nome" | "criacao" | "populacao">("nome");
  const [aCarregar, setACarregar] = useState(false);
  const [fonte, setFonte] = useState<{ nome?: string | null; pagina?: string | null }>({});

  useEffect(() => {
    const temporizador = window.setTimeout(async () => {
      setACarregar(true);
      try {
        const resposta = await getMunicipios({ q: busca || undefined, ordem });
        setMunicipios(resposta.items);
        setResumo({
          total: resposta.total,
          comBrasao: resposta.com_brasao,
          comData: resposta.com_data_criacao,
        });
        setFonte({ nome: resposta.fonte, pagina: resposta.fonte_url });
      } catch {
        setMunicipios([]);
      } finally {
        setACarregar(false);
      }
    }, 300);
    return () => window.clearTimeout(temporizador);
  }, [busca, ordem]);

  return (
    <div className="space-y-3">
      <div className="glass-card rounded-2xl p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Procurar município, distrito ou código (ex.: ABT)"
              className="w-full rounded-lg border border-white/10 bg-white/5 py-1.5 pl-8 pr-3 text-xs outline-none placeholder:text-muted-foreground focus:border-teal-400/40"
            />
          </div>
          <select
            value={ordem}
            onChange={(evento) => setOrdem(evento.target.value as "nome" | "criacao" | "populacao")}
            className="rounded-lg border border-white/10 bg-[#07151b] px-2 py-1.5 text-xs"
          >
            <option value="nome">Ordem alfabética</option>
            <option value="criacao">Mais antigos primeiro</option>
            <option value="populacao">Maior população (2021)</option>
          </select>
          {aCarregar ? <Loader2 size={14} className="animate-spin text-muted-foreground" /> : null}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          <strong className="text-foreground">{numero(resumo.total)}</strong> municípios ·{" "}
          <strong className="text-foreground">{numero(resumo.comBrasao)}</strong> com brasão ·{" "}
          <strong className="text-foreground">{numero(resumo.comData)}</strong> com data de criação.{" "}
          {fonte.nome ? <>Fonte: {fonte.nome}. </> : null}
          {fonte.pagina ? (
            <a className="underline hover:text-foreground" href={fonte.pagina} target="_blank" rel="noreferrer">
              Lista de municípios de Portugal (Wikipédia)
            </a>
          ) : null}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {municipios.map((municipio) => (
          <figure
            key={municipio.nome}
            className="glass-card flex items-start gap-3 rounded-2xl p-3"
          >
            {municipio.brasao?.foto ? (
              <img
                src={municipio.brasao.foto}
                alt={`Brasão de ${municipio.nome}`}
                loading="lazy"
                className="h-20 w-16 shrink-0 object-contain"
              />
            ) : (
              <div className="flex h-20 w-16 shrink-0 items-center justify-center rounded-lg bg-white/5 text-[10px] text-muted-foreground">
                sem brasão
              </div>
            )}
            <figcaption className="min-w-0 space-y-1">
              <p className="text-xs font-semibold">{municipio.nome}</p>
              <p className="text-[11px] text-muted-foreground">
                {municipio.distrito ?? "—"}
                {municipio.codigo ? ` · ${municipio.codigo}` : ""}
              </p>
              <p className="text-[11px]">
                <span className="text-muted-foreground">Criado em </span>
                <span className="font-medium tabular-nums">
                  {municipio.criacao_ano ?? "—"}
                </span>
                {notaCriacao(municipio.criacao) ? (
                  <span className="text-muted-foreground"> — {notaCriacao(municipio.criacao)}</span>
                ) : null}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {numero(municipio.eleitores)} eleitores · {euro(municipio.remuneracao_mensal)}
                {municipio.populacao_2021 ? ` · ${numero(municipio.populacao_2021)} hab. (2021)` : ""}
              </p>
              {municipio.brasao?.origem === "Wikidata (P94)" ? (
                <p className="text-[10px] text-amber-200/80">
                  Brasão completado pelo Wikidata (a tabela não o traz)
                </p>
              ) : null}
              {municipio.brasao?.pagina ? (
                <p className="text-[10px] text-muted-foreground">
                  {municipio.brasao.autor ? <>© {municipio.brasao.autor} </> : null}
                  {municipio.brasao.licenca ? <>· {municipio.brasao.licenca} </> : null}
                  <a
                    className="underline hover:text-foreground"
                    href={municipio.brasao.pagina}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Commons
                  </a>
                </p>
              ) : null}
            </figcaption>
          </figure>
        ))}
      </div>
      {municipios.length === 0 && !aCarregar ? (
        <p className="text-[11px] text-muted-foreground">
          Sem brasões para mostrar. Recolha-os com{" "}
          <code>POST /remuneracoes/municipios/recolher</code>.
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------- blocos de abonos */

function ListaVerbas({ verbas }: { verbas: RemuneracoesVerba[] }) {
  if (!verbas.length) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Sem valores na tabela para este escalão. A tabela dos municípios ainda não foi importada.
      </p>
    );
  }
  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-1 font-medium">Regime</th>
          <th className="py-1 font-medium">Verba</th>
          <th className="py-1 font-medium">Cargo</th>
          <th className="py-1 text-right font-medium">Valor</th>
        </tr>
      </thead>
      <tbody>
        {verbas
          .filter((verba) => verba.valor !== null || verbas.length <= 6)
          .map((verba, indice) => (
            <tr key={`${verba.id}-${indice}`} className="border-t border-white/5">
              <td className="py-1 align-top text-muted-foreground">{verba.regime ?? "—"}</td>
              <td className="py-1 align-top">
                <span className="block">{verba.grupo ?? "—"}</span>
                {verba.modalidade ? (
                  <span className="text-[10px] text-muted-foreground">{verba.modalidade}</span>
                ) : null}
              </td>
              <td className="py-1 align-top text-muted-foreground">{verba.cargo ?? "—"}</td>
              <td className="py-1 text-right align-top tabular-nums">
                {euro(verba.valor)}
                {verba.percentagem !== null && verba.percentagem !== undefined ? (
                  <span className="ml-1 text-[10px] text-muted-foreground">
                    ({percentagem(verba.percentagem)})
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}

/* --------------------------------------------------- ficha de um concelho */

function FichaConcelho({
  detalhe,
  metrica,
  onAbrirNoMapa,
}: {
  detalhe: RemuneracoesConcelhoDetail;
  metrica: MetricaMapa;
  onAbrirNoMapa: () => void;
}) {
  const [freguesiaAberta, setFreguesiaAberta] = useState<RemuneracoesFreguesia | null>(null);

  if (detalhe.error) {
    return <div className="glass-card rounded-2xl p-4 text-sm text-rose-300">{detalhe.error}</div>;
  }

  const freguesia = freguesiaAberta ?? detalhe.freguesias[0] ?? null;
  const pontos: MapaPonto[] = detalhe.freguesias.map((f) => pontoDoMapa({ ...f, nivel: "freguesia" }));

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex items-start gap-3">
            {detalhe.brasao?.foto ? (
              <img
                src={detalhe.brasao.foto}
                alt={`Brasão de ${detalhe.nome}`}
                className="h-16 w-14 shrink-0 object-contain"
                title={
                  [detalhe.brasao.autor ? `© ${detalhe.brasao.autor}` : null, detalhe.brasao.licenca]
                    .filter(Boolean)
                    .join(" · ") || undefined
                }
              />
            ) : null}
            <div>
              <h2 className="text-lg font-semibold">{detalhe.nome}</h2>
              <p className="text-xs text-muted-foreground">
                <MapPin size={12} className="mr-1 inline" />
                {detalhe.distrito} · {numero(detalhe.total_freguesias)} freguesias
                {detalhe.codigo ? ` · ${detalhe.codigo}` : ""}
                {detalhe.lat !== null && detalhe.lat !== undefined ? (
                  <>
                    {" "}
                    · {detalhe.lat.toFixed(3)}, {detalhe.lon?.toFixed(3)}
                  </>
                ) : null}
              </p>
              {detalhe.criacao ? (
                <p className="mt-1 text-[11px]">
                  <span className="uppercase tracking-wide text-muted-foreground">Criado em </span>
                  <span className="font-medium tabular-nums">{detalhe.criacao_ano ?? "—"}</span>
                  {notaCriacao(detalhe.criacao) ? (
                    <span className="text-muted-foreground"> — {notaCriacao(detalhe.criacao)}</span>
                  ) : null}
                </p>
              ) : null}
              {detalhe.populacao_2021 ? (
                <p className="text-[11px] text-muted-foreground">
                  {numero(detalhe.populacao_2021)} habitantes no censo de 2021
                </p>
              ) : null}
              {detalhe.brasao?.pagina ? (
                <p className="text-[10px] text-muted-foreground">
                  {detalhe.brasao.autor ? <>© {detalhe.brasao.autor} </> : null}
                  {detalhe.brasao.licenca ? <>· {detalhe.brasao.licenca} </> : null}
                  <a
                    className="underline hover:text-foreground"
                    href={detalhe.brasao.pagina}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Commons
                  </a>
                </p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={onAbrirNoMapa}
              className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] transition hover:bg-white/10"
              title="Situar este concelho no mapa do país"
            >
              <CrosshairMini /> Ver no mapa do país
            </button>
            <Etiqueta tom="sky">
              <Users size={11} /> {numero(detalhe.eleitores)} eleitores
            </Etiqueta>
            <Etiqueta tom="emerald">{numero(detalhe.votantes)} votantes</Etiqueta>
            <Etiqueta>{numero(detalhe.mandatos)} mandatos</Etiqueta>
          </div>
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">Eleitores (concelho)</dt>
            <dd className="text-base font-semibold tabular-nums">{numero(detalhe.eleitores)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Eleitores (freguesias)</dt>
            <dd className="text-base font-semibold tabular-nums">
              {numero(detalhe.total_eleitores_freguesias)}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Escalão do município</dt>
            <dd className="text-base font-semibold">{detalhe.escalao ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Abono mensal do presidente</dt>
            <dd className="text-base font-semibold tabular-nums">{euro(detalhe.remuneracao_mensal)}</dd>
          </div>
        </dl>
      </div>

      <EleitosConcelho eleitos={detalhe.eleitos} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="glass-card rounded-2xl p-4">
          <h3 className="text-xs font-semibold">Remunerações das freguesias por escalão de eleitores</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Total mensal dos presidentes de junta:{" "}
            <strong className="text-foreground">
              {euro(detalhe.remuneracoes_freguesias.total_mensal_presidentes)}
            </strong>{" "}
            (regime de exclusividade, tempo inteiro).
          </p>
          <ul className="mt-3 space-y-1.5">
            {detalhe.remuneracoes_freguesias.por_escalao.map((linha) => (
              <li key={linha.escalao_id} className="text-[11px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate">{linha.escalao ?? "Sem escalão"}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {numero(linha.freguesias)} freg. · {numero(linha.eleitores)} eleitores ·{" "}
                    {euro(linha.remuneracao_mensal)} cada
                  </span>
                </div>
                <div className="mt-0.5 h-1 w-full rounded-full bg-white/5">
                  <div
                    className="h-1 rounded-full bg-teal-400/60"
                    style={{
                      width: `${(linha.freguesias / Math.max(1, detalhe.total_freguesias)) * 100}%`,
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="glass-card rounded-2xl p-4">
          <h3 className="text-xs font-semibold">
            Freguesias {freguesia ? `· ${freguesia.nome}` : ""}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1">
            {detalhe.freguesias.slice(0, 60).map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFreguesiaAberta(f)}
                className={`rounded-full border px-2 py-0.5 text-[10px] transition ${
                  freguesia?.id === f.id
                    ? "border-amber-400/50 bg-amber-400/15 text-amber-100"
                    : "border-white/10 bg-white/5 text-muted-foreground hover:text-foreground"
                }`}
              >
                {f.nome} · {numero(f.eleitores)}
              </button>
            ))}
            {detalhe.freguesias.length > 60 ? (
              <span className="px-2 py-0.5 text-[10px] text-muted-foreground">
                +{detalhe.freguesias.length - 60} freguesias
              </span>
            ) : null}
          </div>

          {freguesia ? (
            <div className="mt-3">
              <div className="mb-2 flex flex-wrap gap-1.5">
                <Etiqueta tom="sky">{numero(freguesia.eleitores)} eleitores</Etiqueta>
                <Etiqueta tom="emerald">{numero(freguesia.votantes)} votantes</Etiqueta>
                <Etiqueta tom="violet">{freguesia.escalao ?? "sem escalão"}</Etiqueta>
                <Etiqueta tom="amber">Presidente: {euro(freguesia.remuneracao_mensal)}</Etiqueta>
              </div>
              <ListaVerbas verbas={freguesia.verbas} />
            </div>
          ) : null}
        </div>
      </div>

      <div className="glass-card rounded-2xl p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold">
            Mapa das freguesias de {detalhe.nome} — OpenStreetMap
          </h3>
          <Etiqueta tom="sky">
            <Layers size={11} /> {pontos.filter((p) => Number.isFinite(p.lat)).length} de{" "}
            {detalhe.total_freguesias} freguesias no mapa
          </Etiqueta>
        </div>
        <MapaOSM
          pontos={pontos}
          selecionado={freguesia?.id ?? null}
          onSelecionar={(ponto) =>
            setFreguesiaAberta(detalhe.freguesias.find((f) => f.id === ponto.id) ?? null)
          }
          metrica={metrica}
          altura={360}
          semCoordenadas={detalhe.freguesias_sem_coordenadas}
          legenda="Clique numa freguesia para ver os abonos que lhe cabem. As coordenadas são as da Wikidata, as mesmas que servem o OpenStreetMap."
        />
      </div>
    </div>
  );
}

function CrosshairMini() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
    </svg>
  );
}

/* ------------------------------------------------------ tabela de abonos */

function TabelaAbonos({ tabela }: { tabela: RemuneracoesTabela }) {
  const porRegime = useMemo(() => {
    const mapa = new Map<string, RemuneracoesRubrica[]>();
    for (const rubrica of tabela.rubricas) {
      const chave = rubrica.regime || "—";
      mapa.set(chave, [...(mapa.get(chave) ?? []), rubrica]);
    }
    return [...mapa.entries()];
  }, [tabela.rubricas]);

  if (tabela.estado === "por_importar" || tabela.rubricas.length === 0) {
    return (
      <div className="glass-card rounded-2xl p-4">
        <h3 className="text-sm font-semibold">{tabela.titulo ?? nivelLabel(tabela.nivel)}</h3>
        <p className="mt-2 text-[11px] text-muted-foreground">{tabela.nota}</p>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Escalões definidos: {tabela.escaloes.map((e) => e.designacao).join(" · ")}
        </p>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Importe os valores com <code>POST /remuneracoes/tabelas/import</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <h3 className="text-sm font-semibold">{tabela.titulo ?? nivelLabel(tabela.nivel)}</h3>
        {tabela.nota ? <p className="mt-1 text-[11px] text-muted-foreground">{tabela.nota}</p> : null}
      </div>
      {porRegime.map(([regime, rubricas]) => (
        <div key={regime} className="glass-card overflow-x-auto rounded-2xl p-4">
          <h4 className="mb-2 text-xs font-semibold">{regime}</h4>
          <table className="w-full min-w-[720px] text-[11px]">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 pr-3 font-medium">Verba</th>
                <th className="py-1 pr-3 font-medium">Cargo</th>
                <th className="py-1 pr-3 font-medium">Modalidade</th>
                {tabela.escaloes.map((escalao) => (
                  <th key={escalao.id} className="py-1 pl-3 text-right font-medium">
                    <span className="block">{escalao.designacao}</span>
                    {escalao.percentagem_pr !== null && escalao.percentagem_pr !== undefined ? (
                      <span className="text-[10px] text-muted-foreground">
                        {percentagem(escalao.percentagem_pr)} do PR
                      </span>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rubricas.map((rubrica) => (
                <tr key={rubrica.id} className="border-t border-white/5">
                  <td className="py-1.5 pr-3 align-top">{rubrica.grupo}</td>
                  <td className="py-1.5 pr-3 align-top text-muted-foreground">{rubrica.cargo}</td>
                  <td className="py-1.5 pr-3 align-top text-muted-foreground">
                    {rubrica.modalidade || "—"}
                  </td>
                  {tabela.escaloes.map((escalao) => {
                    const valor = rubrica.valores?.[escalao.id];
                    const pct = rubrica.percentagens?.[escalao.id];
                    return (
                      <td key={escalao.id} className="py-1.5 pl-3 text-right align-top tabular-nums">
                        {valor === null || valor === undefined ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          euro(valor)
                        )}
                        {pct !== null && pct !== undefined ? (
                          <span className="ml-1 text-[10px] text-muted-foreground">
                            ({percentagem(pct)})
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- simulador */

function Simulador({ escaloesFreguesia }: { escaloesFreguesia: RemuneracoesEscalao[] }) {
  const [valor, setValor] = useState("5000");
  const numeroEleitores = Number.parseInt(valor.replace(/\D/g, ""), 10);
  const escalao = useMemo(() => {
    if (!Number.isFinite(numeroEleitores)) return null;
    const candidatos = [...escaloesFreguesia].sort(
      (a, b) => (b.min_eleitores ?? 0) - (a.min_eleitores ?? 0),
    );
    for (const candidato of candidatos) {
      const minimo = candidato.min_eleitores;
      const maximo = candidato.max_eleitores;
      if (minimo !== null && minimo !== undefined && numeroEleitores < minimo) continue;
      if (maximo !== null && maximo !== undefined && numeroEleitores >= maximo) continue;
      return candidato;
    }
    return null;
  }, [numeroEleitores, escaloesFreguesia]);

  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold">
        <Scale size={13} /> Em que escalão cai uma freguesia com N eleitores?
      </h3>
      <input
        value={valor}
        onChange={(evento) => setValor(evento.target.value)}
        inputMode="numeric"
        className="mt-2 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        placeholder="Número de eleitores inscritos"
      />
      <p className="mt-2 text-[11px]">
        {escalao ? (
          <>
            <strong>{escalao.designacao}</strong>
            {escalao.percentagem_pr !== null && escalao.percentagem_pr !== undefined
              ? ` — ${percentagem(escalao.percentagem_pr)} da remuneração do Presidente da República`
              : null}
          </>
        ) : (
          <span className="text-muted-foreground">Indique um número de eleitores.</span>
        )}
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- página */

export default function RemuneracoesPage() {
  const [aba, setAba] = useState<Aba>("mapa");
  const [meta, setMeta] = useState<RemuneracoesMeta | null>(null);
  const [stats, setStats] = useState<RemuneracoesStats | null>(null);
  const [tabelas, setTabelas] = useState<RemuneracoesTabela[]>([]);
  const [mapa, setMapa] = useState<RemuneracoesMapa | null>(null);
  const [distrito, setDistrito] = useState("");
  const [metrica, setMetrica] = useState<MetricaMapa>("eleitores");
  const [selecionado, setSelecionado] = useState<number | null>(null);
  const [detalhe, setDetalhe] = useState<RemuneracoesConcelhoDetail | null>(null);
  const [concelhos, setConcelhos] = useState<RemuneracoesConcelho[]>([]);
  const [totalConcelhos, setTotalConcelhos] = useState(0);
  const [freguesias, setFreguesias] = useState<RemuneracoesFreguesia[]>([]);
  const [totalFreguesias, setTotalFreguesias] = useState(0);
  const [busca, setBusca] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [aRecolher, setARecolher] = useState(false);

  const carregarBase = useCallback(async () => {
    try {
      const [metaResposta, statsResposta, tabelasResposta] = await Promise.all([
        getRemuneracoesMeta(),
        getRemuneracoesStats(),
        getRemuneracoesTabelas(),
      ]);
      setMeta(metaResposta);
      setStats(statsResposta);
      setTabelas(tabelasResposta.tabelas);
      setErro(null);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    }
  }, []);

  const carregarMapa = useCallback(async (filtroDistrito: string) => {
    try {
      setMapa(await getMapaRemuneracoes({ nivel: "municipio", distrito: filtroDistrito || undefined }));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    }
  }, []);

  const abrirConcelho = useCallback(async (id: number) => {
    setSelecionado(id);
    setACarregar(true);
    try {
      setDetalhe(await getConcelho(id));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setACarregar(false);
    }
  }, []);

  useEffect(() => {
    void carregarBase();
  }, [carregarBase]);

  useEffect(() => {
    void carregarMapa(distrito);
  }, [distrito, carregarMapa]);

  useEffect(() => {
    const temporizador = window.setTimeout(async () => {
      try {
        if (aba === "concelhos" || aba === "mapa") {
          const resposta = await buscarConcelhos({
            q: busca || undefined,
            distrito: distrito || undefined,
            size: PAGE_SIZE,
          });
          setConcelhos(resposta.items);
          setTotalConcelhos(resposta.total);
        }
        if (aba === "freguesias") {
          const resposta = await buscarFreguesias({
            q: busca || undefined,
            distrito: distrito || undefined,
            size: PAGE_SIZE,
          });
          setFreguesias(resposta.items);
          setTotalFreguesias(resposta.total);
        }
      } catch (excecao) {
        setErro(excecao instanceof Error ? excecao.message : String(excecao));
      }
    }, 300);
    return () => window.clearTimeout(temporizador);
  }, [aba, busca, distrito]);

  const recarregarTudo = useCallback(async () => {
    setARecolher(true);
    try {
      await recolherRemuneracoes({ incluir_freguesias: true });
      await carregarBase();
      await carregarMapa(distrito);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : String(excecao));
    } finally {
      setARecolher(false);
    }
  }, [carregarBase, carregarMapa, distrito]);

  const escaloesFreguesia = useMemo(
    () => tabelas.find((t) => t.nivel === "freguesia")?.escaloes ?? [],
    [tabelas],
  );

  const distritos = useMemo(
    () => [...new Set(concelhos.map((c) => c.distrito))].filter(Boolean).sort(),
    [concelhos],
  );

  const pontosMapa = useMemo<MapaPonto[]>(
    () => (mapa ? mapa.features.map((feature) => pontoDoMapa(feature)) : []),
    [mapa],
  );

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Remunerações dos Eleitos Locais</h1>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            {meta?.tabela.documento ?? "Tabela de Abonos dos Eleitos Locais"} — cruzada com o número
            de eleitores inscritos de cada concelho e freguesia
            {meta?.eleicao ? ` (${meta.eleicao})` : ""}. A remuneração de cada cargo é uma
            percentagem da remuneração do Presidente da República, por escalão de eleitores: nas
            freguesias pela Lei n.º 11/96, nos municípios pelo Estatuto dos Eleitos Locais
            (Lei n.º 29/87).
          </p>
        </div>
        <button
          type="button"
          onClick={() => void recarregarTudo()}
          disabled={aRecolher}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs transition hover:bg-white/10 disabled:opacity-50"
          title="Ir buscar o recenseamento e a cartografia ao MAI e reindexar"
        >
          {aRecolher ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          {aRecolher ? "A recolher do MAI…" : "Recolher do MAI"}
        </button>
      </header>

      {erro ? (
        <div className="glass-card rounded-2xl border-rose-400/30 p-3 text-[11px] text-rose-200">
          {erro}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi
          label="Concelhos"
          value={numero(stats?.total_concelhos)}
          hint={`${numero(stats?.concelhos_com_coordenadas)} no mapa`}
        />
        <Kpi
          label="Freguesias"
          value={numero(stats?.total_freguesias)}
          hint={`${numero(stats?.freguesias_com_coordenadas)} com coordenadas`}
        />
        <Kpi
          label="Eleitores nos concelhos"
          value={numero(stats?.total_eleitores_concelhos)}
          hint={meta?.fonte_territorios ?? undefined}
        />
        <Kpi label="Eleitores nas freguesias" value={numero(stats?.total_eleitores_freguesias)} />
        <Kpi
          label="Tabelas"
          value={tabelas.length}
          hint={tabelas.map((t) => `${t.ano} ${nivelLabel(t.nivel)} (${t.estado})`).join(" · ")}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
          {ABAS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setAba(item.id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                aba === item.id
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {aba !== "tabela" ? (
          <>
            <label className="relative min-w-[200px] flex-1">
              <Search
                size={13}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <input
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
                placeholder={aba === "freguesias" ? "Procurar freguesia…" : "Procurar concelho…"}
                className="w-full rounded-lg border border-input bg-background py-1.5 pl-8 pr-3 text-xs"
              />
            </label>
            <select
              value={distrito}
              onChange={(evento) => setDistrito(evento.target.value)}
              className="rounded-lg border border-input bg-background px-2 py-1.5 text-xs"
            >
              <option value="">Todos os distritos</option>
              {distritos.map((nome) => (
                <option key={nome} value={nome}>
                  {nome}
                </option>
              ))}
            </select>
          </>
        ) : null}

        {aba === "mapa" ? (
          <div className="inline-flex gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
            {METRICAS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setMetrica(item.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  metrica === item.id
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                title={`Pintar o mapa por ${item.label.toLowerCase()}`}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {aba === "mapa" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,520px)]">
          <div className="space-y-3">
            <MapaOSM
              pontos={pontosMapa}
              selecionado={selecionado}
              onSelecionar={(ponto) => void abrirConcelho(ponto.id)}
              metrica={metrica}
              semCoordenadas={mapa?.sem_coordenadas ?? []}
              legenda={`${numero(mapa?.total ?? 0)} concelhos · abonos por escalão de eleitores (municípios: Estatuto dos Eleitos Locais, Lei n.º 29/87). Clique num concelho para abrir a ficha e ver as suas freguesias.`}
            />
            <div className="glass-card rounded-2xl p-3 text-[11px] text-muted-foreground">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <Info size={13} /> Como ler o mapa
              </p>
              <p className="mt-1">
                O tamanho e a cor de cada ponto seguem o valor escolhido
                («{METRICAS.find((m) => m.id === metrica)?.label}»). Os eleitores inscritos são os do
                recenseamento do MAI ({meta?.eleicao ?? "Autárquicas 2025"}); as coordenadas são as
                da Wikidata, as mesmas que servem o OpenStreetMap.
              </p>
              {stats && stats.freguesias_por_escalao.length ? (
                <ul className="mt-2 space-y-1">
                  {stats.freguesias_por_escalao.map((linha) => (
                    <li key={linha.escalao_id}>
                      <div className="flex items-center justify-between gap-2">
                        <span>{linha.escalao ?? "Sem escalão"}</span>
                        <span className="tabular-nums">
                          {numero(linha.count)} freguesias · {numero(linha.eleitores)} eleitores
                        </span>
                      </div>
                      <div className="mt-0.5 h-1 w-full rounded-full bg-white/5">
                        <div
                          className="h-1 rounded-full bg-amber-400/60"
                          style={{
                            width: `${(linha.count / Math.max(1, stats.total_freguesias)) * 100}%`,
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
          <div>
            {aCarregar ? (
              <div className="glass-card flex h-40 items-center justify-center rounded-2xl text-xs text-muted-foreground">
                <Loader2 size={14} className="mr-2 animate-spin" /> A carregar o concelho…
              </div>
            ) : detalhe ? (
              <FichaConcelho
                key={detalhe.id}
                detalhe={detalhe}
                metrica={metrica}
                onAbrirNoMapa={() => setSelecionado(detalhe.id)}
              />
            ) : (
              <div className="glass-card rounded-2xl p-6 text-xs text-muted-foreground">
                <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                  <Info size={14} /> Escolha um concelho no mapa
                </p>
                <p className="mt-2">
                  Cada concelho mostra o número de eleitores inscritos, o escalão em que cai, os
                  abonos que lhe correspondem e a mesma conta para cada uma das suas freguesias —
                  com um mapa próprio das freguesias.
                </p>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {aba === "concelhos" ? (
        <div className="glass-card overflow-x-auto rounded-2xl p-4">
          <p className="mb-3 text-[11px] text-muted-foreground">
            {numero(totalConcelhos)} concelhos
            {distrito ? ` no distrito de ${distrito}` : ""}
            {busca ? ` que correspondem a «${busca}»` : ""}.
          </p>
          <table className="w-full min-w-[900px] text-[11px]">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Concelho</th>
                <th className="py-1.5 pr-3 font-medium">Criado em</th>
                <th className="py-1.5 pr-3 font-medium">Distrito</th>
                <th className="py-1.5 pr-3 text-right font-medium">Eleitores</th>
                <th className="py-1.5 pr-3 text-right font-medium">Votantes</th>
                <th className="py-1.5 pr-3 text-right font-medium">Mandatos</th>
                <th className="py-1.5 pr-3 text-right font-medium">Freguesias</th>
                <th className="py-1.5 pr-3 font-medium">Escalão do município</th>
                <th className="py-1.5 text-right font-medium">Presidente (mensal)</th>
              </tr>
            </thead>
            <tbody>
              {concelhos.map((concelho) => (
                <tr
                  key={concelho.id}
                  className="cursor-pointer border-t border-white/5 hover:bg-white/5"
                  onClick={() => {
                    setAba("mapa");
                    void abrirConcelho(concelho.id);
                  }}
                  title="Abrir a ficha deste concelho no mapa"
                >
                  <td className="py-1.5 pr-3 font-medium">
                    <span className="inline-flex items-center gap-2">
                      {concelho.brasao?.foto ? (
                        <img
                          src={concelho.brasao.foto}
                          alt={`Brasão de ${concelho.nome}`}
                          className="h-6 w-5 shrink-0 object-contain"
                        />
                      ) : null}
                      {concelho.nome}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-muted-foreground" title={concelho.criacao ?? undefined}>
                    {concelho.criacao_ano ? `${concelho.criacao_ano}` : "—"}
                  </td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{concelho.distrito}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{numero(concelho.eleitores)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{numero(concelho.votantes)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{numero(concelho.mandatos)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {numero(concelho.total_freguesias)}
                  </td>
                  <td className="py-1.5 pr-3">{concelho.escalao ?? "—"}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {euro(concelho.remuneracao_mensal)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {concelhos.length === 0 ? (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Sem concelhos recolhidos. Use «Recolher do MAI».
            </p>
          ) : null}
        </div>
      ) : null}

      {aba === "freguesias" ? (
        <div className="glass-card overflow-x-auto rounded-2xl p-4">
          <p className="mb-3 text-[11px] text-muted-foreground">
            {numero(totalFreguesias)} freguesias
            {distrito ? ` no distrito de ${distrito}` : ""}. Cada linha traz quem preside a junta e
            quanto recebe cada pessoa da freguesia — presidente, vogais e assembleia — pela tabela
            oficial do ano.
          </p>
          <table className="w-full min-w-[1180px] text-[11px]">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Freguesia</th>
                <th className="py-1.5 pr-3 font-medium">Concelho</th>
                <th className="py-1.5 pr-3 font-medium">Distrito</th>
                <th className="py-1.5 pr-3 text-right font-medium">Eleitores</th>
                <th className="py-1.5 pr-3 font-medium">Escalão</th>
                <th className="py-1.5 pr-3 font-medium">Presidente da junta</th>
                <th className="py-1.5 pr-3 text-right font-medium">Presidente (mensal)</th>
                <th className="py-1.5 pr-3 text-right font-medium">Vogal (senha)</th>
                <th className="py-1.5 pr-3 text-right font-medium">Secretário (compensação)</th>
                <th className="py-1.5 pr-3 text-right font-medium">Assembleia (senha)</th>
                <th className="py-1.5 text-right font-medium">Membros</th>
              </tr>
            </thead>
            <tbody>
              {freguesias.map((freguesia) => {
                const valores = freguesia.pessoas_valores ?? {};
                return (
                  <tr key={freguesia.id} className="border-t border-white/5">
                    <td className="py-1.5 pr-3 font-medium">{freguesia.nome}</td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{freguesia.concelho}</td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{freguesia.distrito}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{numero(freguesia.eleitores)}</td>
                    <td className="py-1.5 pr-3">{freguesia.escalao ?? "—"}</td>
                    <td className="py-1.5 pr-3">
                      {freguesia.presidente_nome ? (
                        <span className="inline-flex items-center gap-1.5">
                          {freguesia.presidente_nome}
                          {freguesia.presidente_sigla ? (
                            <Etiqueta tom="sky">{freguesia.presidente_sigla}</Etiqueta>
                          ) : null}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {euro(freguesia.remuneracao_mensal)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {euro(valores.senha_vogal ?? valores.compensacao_vogal)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {euro(valores.compensacao_secretario ?? valores.secretario)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {euro(valores.senha_assembleia)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                      {numero(freguesia.total_membros_assembleia)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-[10px] text-muted-foreground">
            «—» nas colunas de vogais, secretários e assembleia quer dizer que a tabela oficial de
            2026 não fixa valor para o escalão dessa freguesia (as senhas e compensações são
            fixadas apenas nalguns escalões).
          </p>
          {freguesias.length === 0 ? (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Sem freguesias recolhidas (a recolha das ~3259 freguesias é a parte mais demorada).
            </p>
          ) : null}
        </div>
      ) : null}

      {aba === "eleitos" ? <ListaPessoas /> : null}

      {aba === "brasões" ? <GaleriaBrasoes /> : null}

      {aba === "camaras" ? <GaleriaCamaras /> : null}

      {aba === "tabela" ? (
        <div className="space-y-4">
          {meta ? (
            <div className="glass-card rounded-2xl p-4 text-[11px]">
              <p className="text-sm font-semibold">{meta.tabela.documento}</p>
              <dl className="mt-2 grid gap-2 sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">Presidente da República</dt>
                  <dd className="tabular-nums">
                    {euro(meta.tabela.referencias?.remuneracao_presidente_republica)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    Presidente de câmara (≤ 10 mil eleitores)
                  </dt>
                  <dd className="tabular-nums">
                    {euro(
                      meta.tabela.referencias
                        ?.remuneracao_presidente_camara_municipio_10mil_ou_menos_eleitores,
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Subsídio de refeição</dt>
                  <dd className="tabular-nums">{euro(meta.tabela.referencias?.subsidio_refeicao)}</dd>
                </div>
              </dl>
              {meta.tabela.atualizacao ? (
                <p className="mt-2 text-muted-foreground">{meta.tabela.atualizacao}</p>
              ) : null}
            </div>
          ) : null}

          <Simulador escaloesFreguesia={escaloesFreguesia} />

          {tabelas.map((tabela) => (
            <TabelaAbonos key={`${tabela.ano}-${tabela.nivel}`} tabela={tabela} />
          ))}

          {stats && stats.freguesias_por_escalao.length ? (
            <div className="glass-card rounded-2xl p-4">
              <h3 className="text-xs font-semibold">Freguesias por escalão de eleitores</h3>
              <ul className="mt-2 space-y-1.5">
                {stats.freguesias_por_escalao.map((linha) => (
                  <li key={linha.escalao_id} className="text-[11px]">
                    <div className="flex items-center justify-between gap-2">
                      <span>{linha.escalao ?? "Sem escalão"}</span>
                      <span className="tabular-nums text-muted-foreground">
                        {numero(linha.count)} freguesias · {numero(linha.eleitores)} eleitores
                      </span>
                    </div>
                    <div className="mt-0.5 h-1 w-full rounded-full bg-white/5">
                      <div
                        className="h-1 rounded-full bg-amber-400/60"
                        style={{
                          width: `${(linha.count / Math.max(1, stats.total_freguesias)) * 100}%`,
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <p className="pb-2 text-[10px] text-muted-foreground">
        {meta?.fonte_territorios
          ? `Recenseamento: ${meta.fonte_territorios}. `
          : ""}
        {meta?.fonte_geo ? `Coordenadas: ${meta.fonte_geo}. ` : ""}
        {meta?.recolhido_em ? `Recolhido em ${meta.recolhido_em}. ` : ""}
        Valores da tabela de abonos em euros, por mês.
      </p>
    </div>
  );
}
