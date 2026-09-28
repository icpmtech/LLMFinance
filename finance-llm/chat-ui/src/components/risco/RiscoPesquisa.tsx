/**
 * **Pesquisa de empresas com risco** — a entrada do módulo, tipo motor de busca.
 *
 * Escreve-se o nome (ou o NIF), escolhe-se o país e o motor devolve as empresas
 * do cadastro com contratos, cada uma com o seu **nível de risco** e os fatores
 * que o sustentam. Daqui abrem-se o dossiê 360 e a comparação de várias empresas.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Building2,
  Filter,
  Layers,
  Loader2,
  Search,
  ShieldAlert,
  Scale,
  X,
} from "lucide-react";

import { pesquisarRisco, sugerirRisco } from "../../riscoApi";
import type { RiscoPesquisa, RiscoPesquisaItem, RiscoSugestao } from "../../riscoApi";
import { Chip, EmptyState, Loading, SectionCard, formatCompactEuro, formatDate, formatNumber } from "../padroes/padroesKit";
import { AvisoModelo, RiscoBadge, riscoCor, riscoTone } from "./riscoKit";

const PAISES = [
  { id: "", label: "Todos os países" },
  { id: "PT", label: "Portugal" },
  { id: "ES", label: "Espanha" },
];

const ORDENS = [
  { id: "relevancia", label: "Relevância (nome mais próximo)" },
  { id: "risco", label: "Risco (maior primeiro)" },
  { id: "valor", label: "Valor contratado" },
  { id: "contratos", label: "Nº de contratos" },
];

const TAMANHO = 8;

export function RiscoPesquisa({
  onAbrir,
  selecionadas,
  onAlternarSelecionada,
  onComparar,
  onCompararSelecionadas,
}: {
  onAbrir: (item: RiscoPesquisaItem) => void;
  selecionadas: string[];
  onAlternarSelecionada: (item: RiscoPesquisaItem) => void;
  onComparar: (item: RiscoPesquisaItem) => void;
  onCompararSelecionadas: () => void;
}) {
  const [termo, setTermo] = useState("");
  const [pais, setPais] = useState("");
  const [nivel, setNivel] = useState("");
  const [ordenar, setOrdenar] = useState<"relevancia" | "risco" | "valor" | "contratos">("relevancia");
  const [detalhado, setDetalhado] = useState(false);
  const [pagina, setPagina] = useState(0);
  const [dados, setDados] = useState<RiscoPesquisa | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [sugestoes, setSugestoes] = useState<RiscoSugestao[]>([]);
  const [mostrarSugestoes, setMostrarSugestoes] = useState(false);
  const [aCarregarSugestoes, setACarregarSugestoes] = useState(false);
  const caixaRef = useRef<HTMLDivElement | null>(null);

  const pesquisar = useCallback(
    async (opcoes: { termo: string; pagina: number }) => {
      const texto = opcoes.termo.trim();
      if (texto.length < 2) {
        setDados(null);
        setErro("Escreva pelo menos 2 caracteres (nome, marca ou NIF).");
        return;
      }
      setCarregando(true);
      setErro("");
      try {
        const resposta = await pesquisarRisco({
          q: texto,
          pais: pais || undefined,
          nivel: nivel || undefined,
          ordenar,
          size: TAMANHO,
          from: opcoes.pagina * TAMANHO,
          detalhado,
        });
        setDados(resposta);
        setPagina(opcoes.pagina);
      } catch (exc) {
        setDados(null);
        setErro(exc instanceof Error ? exc.message : "Falhou a pesquisa.");
      } finally {
        setCarregando(false);
      }
    },
    [detalhado, nivel, ordenar, pais],
  );

  // Sugestões enquanto se escreve (com atraso curto, para não bater na API a cada tecla).
  useEffect(() => {
    const texto = termo.trim();
    if (texto.length < 2) {
      setSugestoes([]);
      return;
    }
    let cancelado = false;
    setACarregarSugestoes(true);
    const timer = setTimeout(async () => {
      try {
        const resposta = await sugerirRisco(texto, 8);
        if (!cancelado) setSugestoes(resposta.itens || []);
      } catch {
        if (!cancelado) setSugestoes([]);
      } finally {
        if (!cancelado) setACarregarSugestoes(false);
      }
    }, 220);
    return () => {
      cancelado = true;
      clearTimeout(timer);
    };
  }, [termo]);

  // Fechar a lista de sugestões ao clicar fora.
  useEffect(() => {
    function aoClicar(evento: MouseEvent) {
      if (caixaRef.current && !caixaRef.current.contains(evento.target as Node)) setMostrarSugestoes(false);
    }
    document.addEventListener("mousedown", aoClicar);
    return () => document.removeEventListener("mousedown", aoClicar);
  }, []);

  const totalPaginas = useMemo(() => {
    if (!dados) return 1;
    return Math.max(1, Math.ceil((dados.disponiveis ?? dados.itens.length) / TAMANHO));
  }, [dados]);

  return (
    <div className="space-y-5">
      <section className="glass-card gradient-border overflow-hidden rounded-3xl p-5 md:p-7">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold md:text-2xl">
              <ShieldAlert size={22} className="text-teal-300" />
              Risco das empresas de contratação pública
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Pesquise uma empresa (nome, marca ou NIF) e veja o nível de risco, os contratos que o sustentam e as
              relações com outras empresas. O risco é uma <strong>prioridade de análise</strong> calculada com dados
              públicos — regras calibradas nos dados e ML sobre empresas comparáveis.
            </p>
          </div>
          {selecionadas.length > 0 && (
            <button
              onClick={onCompararSelecionadas}
              className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-xs text-teal-200 transition hover:bg-teal-400/20"
            >
              <Scale size={14} />
              Comparar {selecionadas.length} selecionada(s)
            </button>
          )}
        </div>

        <div ref={caixaRef} className="relative">
          <div className="flex items-center gap-2 rounded-2xl border border-white/12 bg-white/[0.04] px-4 py-3 focus-within:border-teal-400/40">
            <Search size={18} className="shrink-0 text-muted-foreground" />
            <input
              value={termo}
              onChange={(evento) => {
                setTermo(evento.target.value);
                setMostrarSugestoes(true);
              }}
              onFocus={() => setMostrarSugestoes(true)}
              onKeyDown={(evento) => {
                if (evento.key === "Enter") {
                  setMostrarSugestoes(false);
                  void pesquisar({ termo, pagina: 0 });
                }
              }}
              placeholder="Nome da empresa, marca ou NIF…"
              autoComplete="off"
              className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground/70"
              aria-label="Pesquisar empresa por nome, marca ou NIF"
            />
            {aCarregarSugestoes && <Loader2 size={15} className="animate-spin text-muted-foreground" />}
            {termo && (
              <button
                onClick={() => {
                  setTermo("");
                  setSugestoes([]);
                  setDados(null);
                  setErro("");
                }}
                className="rounded-lg p-1 text-muted-foreground transition hover:text-foreground"
                aria-label="Limpar pesquisa"
              >
                <X size={16} />
              </button>
            )}
            <button
              onClick={() => {
                setMostrarSugestoes(false);
                void pesquisar({ termo, pagina: 0 });
              }}
              className="rounded-xl bg-teal-400/15 px-3 py-1.5 text-xs font-medium text-teal-200 transition hover:bg-teal-400/25"
            >
              Analisar
            </button>
          </div>

          {mostrarSugestoes && sugestoes.length > 0 && (
            <ul className="absolute z-20 mt-2 max-h-80 w-full overflow-y-auto rounded-2xl border border-white/12 bg-[#0b1116]/95 p-1.5 shadow-2xl backdrop-blur">
              {sugestoes.map((sugestao) => (
                <li key={`${sugestao.nif}-${sugestao.nome}`}>
                  <button
                    onClick={() => {
                      setTermo(sugestao.nome);
                      setMostrarSugestoes(false);
                      void pesquisar({ termo: sugestao.nome, pagina: 0 });
                    }}
                    className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-white/[0.06]"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Building2 size={14} className="shrink-0 text-muted-foreground" />
                      <span className="truncate">{sugestao.nome}</span>
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {sugestao.nif} · {formatNumber(sugestao.contratos ?? 0)} contratos
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Filter size={13} /> Filtros
          </span>
          <select
            value={pais}
            onChange={(evento) => setPais(evento.target.value)}
            className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
            aria-label="Filtrar por país"
          >
            {PAISES.map((item) => (
              <option key={item.id || "todos"} value={item.id} className="bg-[#0b1116]">
                {item.label}
              </option>
            ))}
          </select>
          <select
            value={ordenar}
            onChange={(evento) => setOrdenar(evento.target.value as "relevancia" | "risco" | "valor" | "contratos")}
            className="rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs outline-none"
            aria-label="Ordenar resultados"
          >
            {ORDENS.map((item) => (
              <option key={item.id} value={item.id} className="bg-[#0b1116]">
                {item.label}
              </option>
            ))}
          </select>
          <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-2.5 py-1.5 text-xs">
            <input
              type="checkbox"
              checked={detalhado}
              onChange={(evento) => setDetalhado(evento.target.checked)}
              className="accent-teal-400"
            />
            Dossiê completo (réguas de CPV + anomalia ML — mais lento)
          </label>
          {dados?.facetas && dados.facetas.some((item) => item.total > 0) && (
            <span className="flex flex-wrap items-center gap-1.5">
              {dados.facetas.map((faceta) => (
                <button
                  key={faceta.nivel}
                  onClick={() => {
                    const novo = nivel === faceta.nivel ? "" : faceta.nivel;
                    setNivel(novo);
                    void pesquisar({ termo, pagina: 0 });
                  }}
                  className={`rounded-full border px-2 py-0.5 text-[11px] transition ${
                    nivel === faceta.nivel ? "border-teal-400/40 bg-teal-400/15 text-teal-200" : "border-white/10 bg-white/[0.04] text-muted-foreground hover:text-foreground"
                  }`}
                  title="Filtrar por este nível"
                >
                  {faceta.label} · {faceta.total}
                </button>
              ))}
            </span>
          )}
        </div>
      </section>

      {carregando && <Loading label="A calcular o risco das empresas encontradas…" />}
      {!carregando && erro && <EmptyState tone="warn">{erro}</EmptyState>}

      {!carregando && dados?.avisos?.length ? (
        <ul className="space-y-1">
          {dados.avisos.map((aviso, indice) => (
            <li key={indice}>
              <EmptyState tone="warn">{aviso}</EmptyState>
            </li>
          ))}
        </ul>
      ) : null}

      {!carregando && dados && dados.itens.length === 0 && !erro && (
        <EmptyState>
          Nenhuma empresa com contratos casou com «{dados.query}». Experimente só parte do nome, uma marca ou o NIF
          (9 dígitos em Portugal).
        </EmptyState>
      )}

      {!carregando && dados && dados.itens.length > 0 && (
        <SectionCard
          title={`${dados.itens.length} empresa(s) pontuada(s)`}
          subtitle={`${dados.total} candidata(s) no cadastro · ${
            dados.disponiveis && dados.disponiveis > dados.itens.length ? `${dados.disponiveis} disponíveis para navegar · ` : ""
          }ordenado por ${ORDENS.find((item) => item.id === (dados.ordenar || ordenar))?.label ?? "risco"}`}
          icon={Layers}
          actions={
            totalPaginas > 1 ? (
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => void pesquisar({ termo, pagina: Math.max(0, pagina - 1) })}
                  disabled={pagina === 0}
                  className="rounded-lg border border-white/12 px-2.5 py-1 transition disabled:opacity-40"
                >
                  Anterior
                </button>
                <span className="text-muted-foreground">
                  {pagina + 1} / {totalPaginas}
                </span>
                <button
                  onClick={() => void pesquisar({ termo, pagina: pagina + 1 })}
                  disabled={pagina + 1 >= totalPaginas}
                  className="rounded-lg border border-white/12 px-2.5 py-1 transition disabled:opacity-40"
                >
                  Seguinte
                </button>
              </div>
            ) : null
          }
        >
          <ul className="space-y-3">
            {dados.itens.map((item) => (
              <ResultadoEmpresa
                key={`${item.pais}-${item.nif}`}
                item={item}
                selecionada={selecionadas.includes(`${item.pais}:${item.nif}`)}
                onAlternar={() => onAlternarSelecionada(item)}
                onAbrir={() => onAbrir(item)}
                onComparar={() => onComparar(item)}
              />
            ))}
          </ul>
          <AvisoModelo risco={dados.itens[0]?.risco ?? null} className="mt-4" />
        </SectionCard>
      )}

      {!carregando && !dados && !erro && (
        <EmptyState>
          Escreva o nome de uma empresa e carregue em <strong>Analisar</strong> (ou Enter). As sugestões mostram o NIF e
          o nº de contratos de cada empresa candidata.
        </EmptyState>
      )}
    </div>
  );
}

function ResultadoEmpresa({
  item,
  selecionada,
  onAlternar,
  onAbrir,
  onComparar,
}: {
  item: RiscoPesquisaItem;
  selecionada: boolean;
  onAlternar: () => void;
  onAbrir: () => void;
  onComparar: () => void;
}) {
  const risco = item.risco;
  const fatores = (risco?.fatores || []).slice(0, 3);
  const analisados = item.contratos_analisados ?? 0;
  // A contagem de insolvências vem do risco (filtrada por papel) — a do cadastro
  // inclui credores (banca, AT, Segurança Social) e daria um número falso.
  const insolvencias = Number(risco?.features?.insolvencias ?? 0);
  return (
    <li
      className="rounded-2xl border p-4 transition"
      style={{ borderColor: `${riscoCor(risco?.nivel)}33`, background: `linear-gradient(90deg, ${riscoCor(risco?.nivel)}0f, transparent 60%)` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={onAbrir} className="truncate text-left text-base font-semibold hover:text-teal-200">
              {item.nome}
            </button>
            <RiscoBadge risco={risco} />
            {item.pais && <Chip tone={item.pais === "PT" ? "teal" : "amber"}>{item.pais}</Chip>}
            {item.tipo && <Chip>{item.tipo}</Chip>}
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
            <span className="font-mono">{item.nif}</span>
            {item.local?.concelho && <span>{item.local.concelho}</span>}
            <span>
              {formatNumber(item.contratos_total ?? item.contratos ?? 0)}{" "}
              {(item.contratos_total ?? item.contratos ?? 0) === 1 ? "contrato" : "contratos"}
              {item.anos?.[0] ? ` · ${item.anos[0]}–${item.anos[1] ?? item.anos[0]}` : ""}
            </span>
            {analisados === 0 && <span className="text-amber-300">sem contratos como adjudicatária</span>}
            {analisados > 0 && typeof item.valor === "number" && item.valor > 0 && <span>{formatCompactEuro(item.valor)}</span>}
            {insolvencias > 0 && (
              <span className="text-rose-300">
                {formatNumber(insolvencias)} processo(s) de insolvência (CIRE, como insolvente)
              </span>
            )}
          </p>
          {fatores.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {fatores.map((fator) => (
                <span key={fator.id} title={(fator.evidencia || []).join(" · ")}>
                  <Chip tone={riscoTone(risco?.nivel)}>
                    {fator.label} · {fator.pontos?.toFixed(0)}/100
                  </Chip>
                </span>
              ))}
            </div>
          )}
          {item.erro && <p className="mt-2 text-[11px] text-amber-300">{item.erro}</p>}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex gap-2">
            <button
              onClick={onAbrir}
              className="flex items-center gap-1.5 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-xs text-teal-200 transition hover:bg-teal-400/20"
            >
              Dossiê 360 <ArrowRight size={13} />
            </button>
            <button
              onClick={onComparar}
              className="flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs text-muted-foreground transition hover:text-foreground"
              title="Comparar esta empresa com outras"
            >
              <Scale size={13} /> Comparar
            </button>
          </div>
          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground">
            <input type="checkbox" checked={selecionada} onChange={onAlternar} className="accent-teal-400" />
            juntar à comparação
          </label>
          {risco?.gerado_em && <span className="text-[10px] text-muted-foreground/70">calculado {formatDate(risco.gerado_em)}</span>}
        </div>
      </div>
    </li>
  );
}
