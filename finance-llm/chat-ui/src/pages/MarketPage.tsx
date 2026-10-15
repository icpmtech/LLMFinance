/**
 * Página **Mercado** (`/market`): os tickers da plataforma agrupados por país.
 *
 * Não há aqui números escritos à mão. Tudo vem de uma leitura ao Yahoo Finance
 * (`GET /market/by-country`), que devolve, por país:
 *
 * * os **tickers** com a variação **do dia** (`lastPrice / previousClose − 1`);
 * * os **agregados** do país (cotados, altas/baixas, variação média, capitalização);
 * * o **melhor e o pior** de cada país, para o cabeçalho do grupo;
 * * a **origem do país** de cada linha — `yahoo` (campo `country`), `mercado`
 *   (sufixo do símbolo, ex.: `.LS` → Portugal) ou `desconhecido`.
 *
 * Um ticker sem cotação aparece com o motivo à vista, nunca com um valor
 * suposto; e o grupo «sem país identificado» existe para que um instrumento sem
 * país (índices, cripto) não desapareça da vista.
 *
 * A leitura é a pedido: o botão «Atualizar» volta a ler o Yahoo, e o servidor
 * guarda a resposta durante um minuto (o Yahoo não serve dados em menos do que
 * isso).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowLeft,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Coins,
  Globe2,
  Layers,
  Loader2,
  Minus,
  RefreshCw,
  Search,
  TrendingUp,
} from "lucide-react";
import { getMarketByCountry, getMarketMeta, type MarketByCountry, type MarketCountryGroup, type MarketCountryTicker, type MarketMeta } from "../marketApi";

/** Quantos tickers ler por pedido. O universo da plataforma tem ~90 e cada
 *  ticker é uma leitura ao Yahoo: o valor por omissão é o que mantém a página
 *  rápida, e o utilizador pode pedir o universo todo. */
const LIMITES = [
  { valor: 40, label: "40 tickers" },
  { valor: 60, label: "60 tickers" },
  { valor: 120, label: "Universo todo" },
];

/** Etiqueta curta da origem do país (coluna «País por»). */
const ORIGEM_LABEL: Record<string, string> = {
  yahoo: "Yahoo",
  mercado: "sufixo do mercado",
  desconhecido: "sem país",
  cache: "leitura anterior",
};

/** Estilo do distintivo de cada país, pela variação média. */
const RANK_STYLE: Record<string, string> = {
  "em-alta": "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  "em-baixa": "border-rose-400/30 bg-rose-400/10 text-rose-200",
  estavel: "border-slate-400/25 bg-slate-400/10 text-slate-300",
  "sem-cotacao": "border-white/10 bg-white/5 text-muted-foreground",
};

function num(valor?: number | null): string {
  return typeof valor === "number" && Number.isFinite(valor) ? String(valor) : "—";
}

function variacao(valor?: number | null): string {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return "—";
  return `${valor > 0 ? "+" : ""}${valor.toFixed(2)} %`;
}

/** Cor da variação: verde sobe, vermelho desce, cinzento fica. */
function tomVariacao(valor?: number | null): string {
  if (typeof valor !== "number" || !Number.isFinite(valor) || valor === 0) return "text-muted-foreground";
  return valor > 0 ? "text-emerald-300" : "text-rose-300";
}

function SetaVariacao({ valor }: { valor?: number | null }) {
  if (typeof valor !== "number" || !Number.isFinite(valor) || valor === 0) return <Minus size={12} />;
  return valor > 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />;
}

/** Capitalização em forma curta a partir do valor em bruto (a serra do backend
 *  já formata, mas o agregado do país vem em bruto). */
function capitalizacao(valor?: number | null): string {
  if (typeof valor !== "number" || !Number.isFinite(valor) || valor <= 0) return "—";
  if (valor >= 1e12) return `${(valor / 1e12).toFixed(2)} t`;
  if (valor >= 1e9) return `${(valor / 1e9).toFixed(2)} b`;
  if (valor >= 1e6) return `${(valor / 1e6).toFixed(2)} m`;
  return valor.toFixed(0);
}

function hora(iso: string): string {
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? iso : data.toLocaleTimeString("pt-PT");
}

/** Tickler a filtrar (símbolo, nome, setor ou país). */
function combina(ticker: MarketCountryTicker, grupo: MarketCountryGroup, termo: string): boolean {
  const alvo = `${ticker.ticker} ${ticker.name ?? ""} ${ticker.sector ?? ""} ${grupo.country_label}`.toLowerCase();
  return alvo.includes(termo);
}

export default function MarketPage({ onSelectTicker, onBack }: { onSelectTicker?: (ticker: string) => void; onBack?: () => void }) {
  const [dados, setDados] = useState<MarketByCountry | null>(null);
  const [meta, setMeta] = useState<MarketMeta | null>(null);
  const [limite, setLimite] = useState(LIMITES[0].valor);
  const [termo, setTermo] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [atualizando, setAtualizando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  /** Grupos fechados pelo utilizador (o resto fica aberto). */
  const [fechados, setFechados] = useState<Set<string>>(new Set());

  const carregar = useCallback(async (opcoes: { refresh?: boolean; limiteNovo?: number } = {}) => {
    const alvo = opcoes.limiteNovo ?? limite;
    if (opcoes.refresh) setAtualizando(true);
    else setCarregando(true);
    try {
      const resposta = await getMarketByCountry({ limit: alvo, refresh: opcoes.refresh });
      setDados(resposta);
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setCarregando(false);
      setAtualizando(false);
    }
  }, [limite]);

  useEffect(() => {
    void carregar({ limiteNovo: limite });
  }, [carregar, limite]);

  useEffect(() => {
    getMarketMeta().then(setMeta).catch(() => setMeta(null));
  }, []);

  const filtro = termo.trim().toLowerCase();

  /** Grupos (e tickers) que passam o filtro de pesquisa. */
  const grupos = useMemo(() => {
    if (!dados) return [];
    if (!filtro) return dados.countries;
    return dados.countries
      .map((grupo) => ({ ...grupo, tickers: grupo.tickers.filter((ticker) => combina(ticker, grupo, filtro)) }))
      .filter((grupo) => grupo.tickers.length > 0);
  }, [dados, filtro]);

  const visiveis = useMemo(() => grupos.reduce((total, grupo) => total + grupo.tickers.length, 0), [grupos]);

  function alternar(pais: string) {
    setFechados((atual) => {
      const seguinte = new Set(atual);
      if (seguinte.has(pais)) seguinte.delete(pais);
      else seguinte.add(pais);
      return seguinte;
    });
  }

  const totais = dados?.totals;

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        {/* ---------------------------------------------------------- cabeçalho */}
        <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <button
              onClick={() => (onBack ? onBack() : window.history.back())}
              className="mt-1 flex h-8 w-8 items-center justify-center rounded-full glass-card text-muted-foreground transition hover:text-foreground"
              title="Voltar"
            >
              <ArrowLeft size={16} />
            </button>
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-semibold">
                <Globe2 size={22} className="text-teal-300" />
                Mercado
              </h1>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                Os tickers que a plataforma segue, agrupados por país, com a variação do dia. O país vem do Yahoo Finance
                (a mesma fonte da ficha do ticker); quando não responde, o sufixo do mercado decide — e cada linha diz de
                onde veio.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="sr-only">Quantos tickers ler</span>
              <select
                value={limite}
                onChange={(evento) => setLimite(Number(evento.target.value))}
                className="rounded-lg border border-white/10 bg-[#0d1117] px-2 py-1.5 text-xs text-foreground"
              >
                {LIMITES.map((opcao) => (
                  <option key={opcao.valor} value={opcao.valor}>
                    {opcao.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => void carregar({ refresh: true })}
              disabled={atualizando}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-foreground transition hover:bg-white/10 disabled:opacity-50"
              title="Voltar a ler as cotações no Yahoo Finance"
            >
              {atualizando ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Atualizar
            </button>
          </div>
        </header>

        {/* --------------------------------------------------------------- erro */}
        {erro && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/5 p-3 text-sm text-rose-200">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Não foi possível ler o mercado</p>
              <p className="text-rose-200/80">{erro}</p>
            </div>
          </div>
        )}

        {/* -------------------------------------------------------------- painel */}
        <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {[
            { label: "Tickers lidos", valor: totais ? `${totais.quoted}/${totais.tickers}` : "—", icon: Layers },
            { label: "Países", valor: dados ? String(dados.countries.filter((grupo) => !grupo.unknown).length) : "—", icon: Globe2 },
            { label: "Em alta", valor: totais ? String(totais.advancers) : "—", icon: ArrowUpRight, tom: "text-emerald-300" },
            { label: "Em baixa", valor: totais ? String(totais.decliners) : "—", icon: ArrowDownRight, tom: "text-rose-300" },
            {
              label: "Variação média",
              valor: totais ? variacao(totais.average_change_pct) : "—",
              icon: TrendingUp,
              tom: tomVariacao(totais?.average_change_pct),
            },
            { label: "Capitalização", valor: capitalizacao(totais?.market_cap), icon: Coins },
          ].map((cartao) => (
            <article key={cartao.label} className="glass-card rounded-2xl p-3">
              <p className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <cartao.icon size={12} />
                {cartao.label}
              </p>
              <p className={`mt-1 text-lg font-semibold ${cartao.tom ?? ""}`}>{cartao.valor}</p>
            </article>
          ))}
        </section>

        {/* ------------------------------------------------------------ pesquisa */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="relative flex min-w-[240px] flex-1 items-center">
            <Search size={14} className="absolute left-3 text-muted-foreground" />
            <input
              value={termo}
              onChange={(evento) => setTermo(evento.target.value)}
              placeholder="Filtrar por símbolo, nome, setor ou país (ex.: EDP, Utilities, Portugal)"
              className="w-full rounded-xl border border-white/10 bg-[#0d1117] py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {dados ? (
              <>
                {visiveis} de {dados.universe.requested} tickers · {dados.source} · lido às {hora(dados.generated_at)}
                {dados.universe.available > dados.universe.requested ? ` · universo com ${dados.universe.available}` : ""}
              </>
            ) : (
              "a ler o mercado…"
            )}
          </p>
        </div>

        {/* ------------------------------------------------------------- estados */}
        {carregando && !dados && (
          <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.02] p-6 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" />
            A ler as cotações do Yahoo Finance…
          </div>
        )}

        {dados && grupos.length === 0 && (
          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 text-sm text-muted-foreground">
            {filtro ? `Nenhum ticker corresponde a «${termo}».` : "Não há tickers para mostrar."}
          </div>
        )}

        {/* -------------------------------------------------------------- países */}
        <div className="space-y-4">
          {grupos.map((grupo) => {
            const fechado = filtro ? false : fechados.has(grupo.country);
            return (
              <section key={grupo.country} className="glass-card overflow-hidden rounded-2xl">
                <button
                  type="button"
                  onClick={() => alternar(grupo.country)}
                  className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.03]"
                >
                  <Globe2 size={16} className={grupo.unknown ? "text-slate-400" : "text-teal-300"} />
                  <span className="text-base font-semibold">{grupo.country_label}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${RANK_STYLE[grupo.rank.id] ?? RANK_STYLE.estavel}`}>
                    {grupo.rank.label} {grupo.stats.average_change_pct !== null ? variacao(grupo.stats.average_change_pct) : ""}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {grupo.stats.quoted}/{grupo.stats.tickers} cotados
                    {grupo.stats.without_quote > 0 ? ` · ${grupo.stats.without_quote} sem cotação` : ""}
                    {grupo.stats.market_cap ? ` · ${capitalizacao(grupo.stats.market_cap)}` : ""}
                  </span>
                  <span className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
                    {grupo.best && (
                      <span className="text-emerald-300">
                        melhor {grupo.best.ticker} {variacao(grupo.best.change_pct)}
                      </span>
                    )}
                    {grupo.worst && (
                      <span className="text-rose-300">
                        pior {grupo.worst.ticker} {variacao(grupo.worst.change_pct)}
                      </span>
                    )}
                    <span>{fechado ? "▸" : "▾"}</span>
                  </span>
                </button>

                {!fechado && (
                  <div className="overflow-x-auto border-t border-white/5">
                    <table className="w-full min-w-[820px] text-sm">
                      <thead className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                        <tr className="border-b border-white/5">
                          <th className="px-4 py-2 text-left">Ticker</th>
                          <th className="px-3 py-2 text-left">Empresa</th>
                          <th className="px-3 py-2 text-left">Setor</th>
                          <th className="px-3 py-2 text-right">Preço</th>
                          <th className="px-3 py-2 text-right">Dia</th>
                          <th className="px-3 py-2 text-right">Capitalização</th>
                          <th className="px-3 py-2 text-left">País por</th>
                          <th className="px-4 py-2 text-right">Ficha</th>
                        </tr>
                      </thead>
                      <tbody>
                        {grupo.tickers.map((ticker) => (
                          <tr key={ticker.ticker} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                            <td className="px-4 py-2 font-medium">{ticker.ticker}</td>
                            <td className="max-w-[280px] truncate px-3 py-2 text-foreground/90" title={ticker.name ?? undefined}>
                              {ticker.name ?? "—"}
                            </td>
                            <td className="max-w-[200px] truncate px-3 py-2 text-muted-foreground" title={ticker.sector ?? undefined}>
                              {ticker.sector ?? "—"}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {ticker.price_label ?? num(ticker.price)}
                            </td>
                            <td className={`px-3 py-2 text-right tabular-nums ${tomVariacao(ticker.change_pct)}`}>
                              <span className="inline-flex items-center justify-end gap-1">
                                <SetaVariacao valor={ticker.change_pct} />
                                {ticker.change_label ?? variacao(ticker.change_pct)}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {ticker.market_cap_label ?? capitalizacao(ticker.market_cap)}
                            </td>
                            <td className="px-3 py-2 text-[11px] text-muted-foreground">
                              {ticker.error ? (
                                <span className="inline-flex items-center gap-1 text-amber-200/90">
                                  <AlertTriangle size={11} />
                                  {ticker.error}
                                </span>
                              ) : (
                                <span className="flex items-center gap-1">
                                  {ticker.country_source === "yahoo" ? (
                                    <CheckCircle2 size={11} className="text-emerald-300/80" />
                                  ) : (
                                    <Building2 size={11} />
                                  )}
                                  {ORIGEM_LABEL[ticker.country_source] ?? ticker.country_source}
                                  {ticker.exchange ? ` · ${ticker.exchange}` : ""}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-right">
                              {onSelectTicker ? (
                                <button
                                  type="button"
                                  onClick={() => onSelectTicker(ticker.ticker)}
                                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] transition hover:bg-white/10"
                                >
                                  abrir
                                </button>
                              ) : (
                                <span className="text-[11px] text-muted-foreground">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            );
          })}
        </div>

        {/* -------------------------------------------------- erros e ressalvas */}
        {dados && dados.universe.errors.length > 0 && (
          <section className="mt-5 rounded-2xl border border-amber-400/25 bg-amber-400/5 p-4">
            <p className="flex items-center gap-2 text-sm font-medium text-amber-100">
              <AlertTriangle size={15} />
              {dados.universe.errors.length} ticker(s) sem cotação
            </p>
            <p className="mt-1 text-xs text-amber-100/70">
              Estes símbolos não são preenchidos com um valor suposto — ficam identificados e continuam a contar para o
              país.
            </p>
            <ul className="mt-2 space-y-1">
              {dados.universe.errors.map((item) => (
                <li key={item.ticker} className="text-xs text-amber-100/90">
                  <span className="font-medium">{item.ticker}</span>
                  {item.country_label ? ` (${item.country_label})` : ""} — {item.error ?? "sem cotação"}
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="mt-5 space-y-2 text-[11px] text-muted-foreground">
          {dados && <p>{dados.caveat}</p>}
          {meta && (
            <p>
              Fonte: {meta.source} (universo da plataforma: {meta.universe} tickers). País de cada linha:{" "}
              {meta.country_sources.yahoo}, {meta.country_sources.mercado}, ou {meta.country_sources.desconhecido}. A
              resposta é guardada {Math.round(meta.cache_seconds)} s no servidor.
            </p>
          )}
          {meta?.country_cache && (
            <p>
              O país aprendido de cada ticker fica em {meta.country_cache}: uma leitura ao Yahoo por símbolo, não por
              visita.
            </p>
          )}
        </footer>
      </div>
    </div>
  );
}
