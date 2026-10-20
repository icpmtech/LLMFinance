/**
 * Pesquisa e ranking de empresas no módulo ESG.
 *
 * A primeira pesquisa de uma empresa ainda sem fotografia calcula-a ao vivo
 * (`origem: calculado`) e guarda-a; a partir daí a lista vem do índice. O
 * ranking usa os mesmos filtros, ordenação por score/pilar e exportação CSV.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Download, Loader2, Search, Trophy } from "lucide-react";

import { esgRankingCsvUrl, getEsgRanking, searchEsg, suggestEsg } from "../../esgApi";
import type { EsgEmpresaResumo, EsgMeta, EsgSugestao } from "../../esgApi";
import { Chip, EmptyState, Loading, SectionCard } from "../padroes/padroesKit";
import { EsgBadge, compactEuro, esgCor, num, pct } from "./esgKit";

const ORDENS = [
  { id: "score", label: "Score (maior primeiro)" },
  { id: "score_asc", label: "Score (menor primeiro)" },
  { id: "e", label: "Pilar Ambiente" },
  { id: "s", label: "Pilar Social" },
  { id: "g", label: "Pilar Governação" },
  { id: "valor", label: "Valor contratado" },
  { id: "contratos", label: "Nº de contratos" },
  { id: "nome", label: "Nome" },
];

const NIVEIS = [
  { id: "", label: "Todas" },
  { id: "lider", label: "Líder" },
  { id: "avancado", label: "Avançado" },
  { id: "intermedio", label: "Intermédio" },
  { id: "inicial", label: "Inicial" },
  { id: "fraco", label: "Frágil" },
];

function Tabela({ itens, onAbrir, mostrarPosicao = false }: { itens: EsgEmpresaResumo[]; onAbrir: (item: EsgEmpresaResumo) => void; mostrarPosicao?: boolean }) {
  if (!itens.length) return <EmptyState>Sem empresas para mostrar.</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr className="border-b border-white/10">
            {mostrarPosicao && <th className="py-2 pr-3">#</th>}
            <th className="py-2 pr-3">Empresa</th>
            <th className="py-2 pr-3">Setor</th>
            <th className="py-2 pr-3">Dimensão</th>
            <th className="py-2 pr-3">Score</th>
            <th className="py-2 pr-3">E</th>
            <th className="py-2 pr-3">S</th>
            <th className="py-2 pr-3">G</th>
            <th className="py-2 pr-3">Cobertura</th>
            <th className="py-2 pr-3">Valor</th>
            <th className="py-2" />
          </tr>
        </thead>
        <tbody>
          {itens.map((item) => (
            <tr key={`${item.pais}-${item.nif}`} className="border-b border-white/5 transition hover:bg-white/[0.03]">
              {mostrarPosicao && <td className="py-2 pr-3 font-mono text-[11px] text-muted-foreground">{item.posicao ?? "—"}</td>}
              <td className="max-w-[280px] py-2 pr-3">
                <button onClick={() => onAbrir(item)} className="block max-w-full truncate text-left hover:text-teal-200" title={item.nome}>
                  {item.nome}
                </button>
                <span className="font-mono text-[10px] text-muted-foreground">{item.pais} · {item.nif}</span>
              </td>
              <td className="max-w-[180px] truncate py-2 pr-3 text-[11px] text-muted-foreground" title={item.setor_label || undefined}>
                {item.setor_label || "—"}
              </td>
              <td className="max-w-[150px] truncate py-2 pr-3 text-[11px] text-muted-foreground" title={item.dimensao_label || undefined}>
                {item.dimensao_label || "—"}
              </td>
              <td className="py-2 pr-3">
                <EsgBadge score={item.score} nivel={item.nivel} nivelLabel={item.nivel_label} cor={item.cor} compact />
              </td>
              {(["e", "s", "g"] as const).map((pilar) => {
                const valor = item.pilares?.[pilar] ?? null;
                return (
                  <td key={pilar} className="py-2 pr-3 font-mono text-[11px]" style={{ color: valor === null ? undefined : esgCor(valor >= 60 ? "avancado" : valor >= 40 ? "intermedio" : "inicial") }}>
                    {valor === null ? "—" : valor.toFixed(0)}
                  </td>
                );
              })}
              <td className="py-2 pr-3 text-[11px] text-muted-foreground">{pct(item.cobertura, 0)}</td>
              <td className="py-2 pr-3 text-[11px] text-muted-foreground">{compactEuro(item.valor)}</td>
              <td className="py-2 text-right">
                <button onClick={() => onAbrir(item)} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground">
                  Dossiê <ArrowUpRight size={12} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EsgEmpresas({ meta, onAbrir }: { meta: EsgMeta | null; onAbrir: (item: EsgEmpresaResumo) => void }) {
  const [modo, setModo] = useState<"ranking" | "pesquisa">("ranking");
  const [texto, setTexto] = useState("");
  const [sugestoes, setSugestoes] = useState<EsgSugestao[]>([]);
  const [itens, setItens] = useState<EsgEmpresaResumo[]>([]);
  const [total, setTotal] = useState(0);
  const [origem, setOrigem] = useState("");
  const [nota, setNota] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [pais, setPais] = useState("");
  const [setor, setSetor] = useState("");
  const [dimensao, setDimensao] = useState("");
  const [nivel, setNivel] = useState("");
  const [ordenar, setOrdenar] = useState("score");
  const [pagina, setPagina] = useState(0);
  const porPagina = 20;

  const filtros = useMemo(
    () => ({
      pais: pais || undefined,
      setor: setor || undefined,
      dimensao: dimensao || undefined,
      nivel: nivel || undefined,
      ordenar: modo === "ranking" ? ordenar : "relevancia",
      pilar: modo === "ranking" && ["e", "s", "g"].includes(ordenar) ? ordenar : undefined,
    }),
    [pais, setor, dimensao, nivel, ordenar, modo],
  );

  const carregarRanking = useCallback(() => {
    setCarregando(true);
    setErro("");
    getEsgRanking({ ...filtros, size: porPagina, from: pagina * porPagina })
      .then((resposta) => {
        setItens(resposta.itens || []);
        setTotal(resposta.total || 0);
        setOrigem("indice");
        setNota("");
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível carregar o ranking."))
      .finally(() => setCarregando(false));
  }, [filtros, pagina]);

  useEffect(() => {
    if (modo !== "ranking") return;
    carregarRanking();
  }, [modo, carregarRanking]);

  useEffect(() => {
    if (!texto.trim() || texto.trim().length < 2) {
      setSugestoes([]);
      return;
    }
    let cancelado = false;
    const timer = window.setTimeout(() => {
      suggestEsg(texto.trim(), 6)
        .then((resposta) => {
          if (!cancelado) setSugestoes(resposta.sugestoes || []);
        })
        .catch(() => {
          if (!cancelado) setSugestoes([]);
        });
    }, 220);
    return () => {
      cancelado = true;
      window.clearTimeout(timer);
    };
  }, [texto]);

  const pesquisar = useCallback(
    (termo?: string, alvo?: EsgSugestao) => {
      const q = (termo ?? texto).trim();
      if (!q || q.length < 2) return;
      setCarregando(true);
      setErro("");
      setSugestoes([]);
      searchEsg({ q, ...filtros, size: porPagina, from: 0 })
        .then((resposta) => {
          setItens(resposta.itens || []);
          setTotal(resposta.total || 0);
          setOrigem(resposta.origem || "");
          setNota(resposta.nota || resposta.motivo || "");
          if (alvo) setTexto(alvo.nome);
        })
        .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível pesquisar."))
        .finally(() => setCarregando(false));
    },
    [texto, filtros],
  );

  const mudarModo = (novo: "ranking" | "pesquisa") => {
    setModo(novo);
    setPagina(0);
    setErro("");
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
          <button
            onClick={() => mudarModo("ranking")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition ${modo === "ranking" ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground"}`}
          >
            <Trophy size={13} /> Ranking
          </button>
          <button
            onClick={() => mudarModo("pesquisa")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition ${modo === "pesquisa" ? "bg-teal-400/15 text-teal-200" : "text-muted-foreground"}`}
          >
            <Search size={13} /> Pesquisar
          </button>
        </div>
        <a
          href={esgRankingCsvUrl({ ...filtros, limite: 500 })}
          className="ml-auto flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:text-foreground"
        >
          <Download size={13} /> Exportar CSV
        </a>
      </div>

      {modo === "pesquisa" && (
        <SectionCard title="Pesquisar empresa" subtitle="Nome, marca ou NIF. A primeira consulta calcula e guarda a fotografia ESG." icon={Search}>
          <div className="relative flex flex-wrap items-end gap-2">
            <div className="relative min-w-[260px] flex-1">
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2">
                <Search size={14} className="shrink-0 text-muted-foreground" />
                <input
                  value={texto}
                  onChange={(event) => setTexto(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") pesquisar();
                  }}
                  placeholder="Ex.: Mota-Engil, EDP, 503504564"
                  className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/60"
                />
              </div>
              {sugestoes.length > 0 && (
                <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-white/10 bg-[#0b1116] p-1 shadow-xl">
                  {sugestoes.map((sugestao) => (
                    <li key={`${sugestao.pais}-${sugestao.nif}`}>
                      <button
                        onClick={() => pesquisar(sugestao.nome, sugestao)}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-white/5"
                      >
                        <span className="min-w-0">
                          <span className="block truncate">{sugestao.nome}</span>
                          <span className="block font-mono text-[10px] text-muted-foreground">{sugestao.pais} · {sugestao.nif}</span>
                        </span>
                        <span className="shrink-0 text-[10px] text-muted-foreground">{sugestao.contratos ?? 0} contratos</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <button
              onClick={() => pesquisar()}
              disabled={carregando || texto.trim().length < 2}
              className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-sm text-teal-200 disabled:opacity-40"
            >
              {carregando ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Pesquisar
            </button>
          </div>
          {nota && <p className="mt-2 text-[11px] text-muted-foreground">{nota}</p>}
          {origem === "calculado" && (
            <p className="mt-1 text-[11px] text-teal-300">Fotografia calculada agora e guardada no índice.</p>
          )}
        </SectionCard>
      )}

      <SectionCard title={modo === "ranking" ? "Ranking ESG" : "Resultados"} subtitle={`${num(total)} empresa(s) com os filtros ativos.`} icon={modo === "ranking" ? Trophy : Search}>
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            País
            <select value={pais} onChange={(e) => { setPais(e.target.value); setPagina(0); }} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
              <option value="">Todos</option>
              <option value="PT">Portugal</option>
              <option value="ES">Espanha</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            Setor
            <select value={setor} onChange={(e) => { setSetor(e.target.value); setPagina(0); }} className="max-w-[220px] rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
              <option value="">Todos</option>
              {(meta?.setores || []).map((item) => (
                <option key={item.id} value={item.id}>{item.id} · {item.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            Dimensão
            <select value={dimensao} onChange={(e) => { setDimensao(e.target.value); setPagina(0); }} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
              <option value="">Todas</option>
              <option value="micro">Micro</option>
              <option value="pequena">Pequena</option>
              <option value="media">Média</option>
              <option value="grande">Grande</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            Nível
            <select value={nivel} onChange={(e) => { setNivel(e.target.value); setPagina(0); }} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
              {NIVEIS.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          </label>
          {modo === "ranking" && (
            <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              Ordenar
              <select value={ordenar} onChange={(e) => { setOrdenar(e.target.value); setPagina(0); }} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
                {ORDENS.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
          )}
          {modo === "pesquisa" && (
            <button onClick={() => pesquisar()} className="ml-auto rounded-xl border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:text-foreground">
              Aplicar filtros à pesquisa
            </button>
          )}
        </div>

        {erro && <EmptyState tone="warn">{erro}</EmptyState>}
        {carregando && <Loading label="A carregar empresas…" />}
        {!carregando && !erro && <Tabela itens={itens} onAbrir={onAbrir} mostrarPosicao={modo === "ranking"} />}

        {modo === "ranking" && total > porPagina && (
          <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Página {pagina + 1} de {Math.max(1, Math.ceil(total / porPagina))}</span>
            <div className="flex gap-2">
              <button disabled={pagina === 0} onClick={() => setPagina((p) => Math.max(0, p - 1))} className="rounded-lg border border-white/10 px-2 py-1 disabled:opacity-30">Anterior</button>
              <button disabled={(pagina + 1) * porPagina >= total} onClick={() => setPagina((p) => p + 1)} className="rounded-lg border border-white/10 px-2 py-1 disabled:opacity-30">Seguinte</button>
            </div>
          </div>
        )}
      </SectionCard>

      {modo === "ranking" && itens.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          O ranking mostra apenas fotografias já guardadas. Para incluir empresas novas, pesquise-as ou execute o cálculo em lote.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {itens.slice(0, 3).map((item) => (
          <Chip key={`${item.pais}-${item.nif}-chip`} tone={item.nivel === "fraco" ? "rose" : item.nivel === "inicial" ? "amber" : "teal"}>
            {item.nome.split(" ").slice(0, 2).join(" ")} · {item.score?.toFixed(0) ?? "—"}
          </Chip>
        ))}
      </div>
    </div>
  );
}
