/**
 * **Como me comparo por CPV e ano** — preço da entidade contra a média do mercado.
 *
 * Para cada CPV do perfil da empresa: média e mediana minhas vs as do mercado
 * (mesmo CPV e mesmos anos), rácio, quota de valor, número de concorrentes (e os
 * três maiores), a série ano a ano com a leitura de cada ano e o **risco** com o
 * motivo escrito (preço acima, a agravar, amostra pequena, posição dominante).
 *
 * A série é desenhada como uma linha (rácio por ano) com a faixa 0,90–1,25×
 * assinalada — acima dela é onde o preço começa a ser um risco.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LineChart, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import {
  getBenchmarkPriceRisk,
  type BenchmarkPriceRiskCpv,
  type BenchmarkPriceRiskResponse,
  type BenchmarkQuery,
} from "../../benchmarkApi";
import { limparNome } from "./texto";

const LARGURA_SERIE = 132;
const ALTURA_SERIE = 34;

function money(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function moneyShort(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 10_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return money(valor);
}

function num(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT");
}

function corRisco(risco: string): string {
  if (risco === "alto") return "border-rose-400/30 bg-rose-400/10 text-rose-200";
  if (risco === "médio") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  if (risco === "baixo") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  return "border-border bg-white/[0.03] text-muted-foreground";
}

function corRatio(ratio?: number | null): string {
  if (!ratio) return "text-muted-foreground";
  if (ratio >= 1.25) return "text-rose-300";
  if (ratio > 0.9) return "text-amber-300";
  return "text-emerald-300";
}

/** Série do rácio por ano (linha) com a banda competitiva marcada. */
function SerieRatio({ linha }: { linha: BenchmarkPriceRiskCpv }) {
  const pontos = useMemo(() => {
    const anos = [...linha.years].reverse().filter((ano) => ano.ratio);
    if (anos.length < 2) return null;
    const ratios = anos.map((ano) => Number(ano.ratio));
    const maximo = Math.max(1.6, ...ratios);
    const minimo = Math.min(0.6, ...ratios);
    const passo = LARGURA_SERIE / (anos.length - 1);
    const y = (valor: number) =>
      ALTURA_SERIE - ((valor - minimo) / Math.max(0.001, maximo - minimo)) * (ALTURA_SERIE - 6) - 3;
    const coordenadas = anos.map((ano, indice) => `${indice * passo},${y(Number(ano.ratio))}`);
    return {
      caminho: coordenadas.join(" "),
      banda: { topo: y(1.25), base: y(0.9) },
      anos: anos.map((ano) => ano.year),
      ultimo: ratios[ratios.length - 1],
      ultimoX: (anos.length - 1) * passo,
      ultimoY: y(ratios[ratios.length - 1]),
    };
  }, [linha]);

  if (!pontos) {
    return <span className="text-xs text-muted-foreground">sem série anual</span>;
  }
  return (
    <svg width={LARGURA_SERIE} height={ALTURA_SERIE} className="overflow-visible">
      <rect
        x={0}
        y={Math.min(pontos.banda.topo, pontos.banda.base)}
        width={LARGURA_SERIE}
        height={Math.abs(pontos.banda.base - pontos.banda.topo)}
        fill="rgba(16,185,129,0.10)"
      />
      <polyline points={pontos.caminho} fill="none" stroke="#38bdf8" strokeWidth={1.6} />
      <circle cx={pontos.ultimoX} cy={pontos.ultimoY} r={3} fill={pontos.ultimo >= 1.25 ? "#fb7185" : "#34d399"} />
      <title>{`${pontos.anos.join(" → ")}`}</title>
    </svg>
  );
}

export default function BenchmarkPriceRisk({ query, ativo }: { query: BenchmarkQuery | null; ativo: boolean }) {
  const [dados, setDados] = useState<BenchmarkPriceRiskResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const chave = useMemo(() => (query ? JSON.stringify(query) : ""), [query]);

  useEffect(() => {
    if (!ativo || !query) {
      setDados(null);
      return;
    }
    let vivo = true;
    setACarregar(true);
    setErro(null);
    getBenchmarkPriceRisk({ ...query, top_cpvs: 8, top_years: 6 })
      .then((resultado) => {
        if (vivo) setDados(resultado.error ? null : resultado);
      })
      .catch((err: unknown) => {
        if (vivo) setErro(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (vivo) setACarregar(false);
      });
    return () => {
      vivo = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave, ativo]);

  if (!ativo || !query) return null;

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
        <LineChart size={16} className="text-muted-foreground" />
        <CardTitle className="text-sm">Como me comparo por CPV e ano</CardTitle>
        {aCarregar ? <Loader2 size={14} className="animate-spin text-muted-foreground" /> : null}
        {dados ? (
          <span className="ml-auto text-xs text-muted-foreground">
            média do mercado do segmento {money(dados.reference.avg)} · mediana {money(dados.reference.median)}
          </span>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {erro ? (
          <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span className="flex-1">{erro}</span>
          </div>
        ) : null}

        {dados ? (
          <>
            {dados.summary.items.length ? (
              <ul className="space-y-2">
                {dados.summary.items.map((item) => (
                  <li
                    key={`${item.kind}-${item.title}`}
                    className={`rounded-xl border px-3 py-2 text-xs ${corRisco(
                      item.severity === "alta" ? "alto" : item.severity === "media" ? "médio" : "info",
                    )}`}
                  >
                    <p className="font-medium">{item.title}</p>
                    <p className="mt-0.5 opacity-90">{item.detail}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sem desvios relevantes: em todos os CPV lidos o preço está dentro do intervalo esperado.
              </p>
            )}

            <div className="overflow-x-auto">
              <table className="w-full min-w-[1000px] text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">CPV</th>
                    <th className="py-2 pr-3 text-right">Contratos</th>
                    <th className="py-2 pr-3 text-right">Média minha</th>
                    <th className="py-2 pr-3 text-right">Média do mercado</th>
                    <th className="py-2 pr-3 text-right">Rácio</th>
                    <th className="py-2 pr-3 text-right">Quota</th>
                    <th className="py-2 pr-3 text-right">Concorrentes</th>
                    <th className="py-2 pr-3">Série por ano</th>
                    <th className="py-2">Risco</th>
                  </tr>
                </thead>
                <tbody>
                  {dados.items.map((linha) => (
                    <tr key={linha.code} className="border-b border-border/40 align-top">
                      <td className="py-2 pr-3">
                        <p className="font-medium tabular-nums">{linha.code}</p>
                        <p className="line-clamp-1 max-w-[20rem] text-xs text-muted-foreground">
                          {linha.description || "—"}
                        </p>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {num(linha.contracts)}
                        <span className="block text-xs text-muted-foreground">de {num(linha.market_contracts)}</span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {money(linha.avg)}
                        <span className="block text-xs text-muted-foreground">mediana {money(linha.median)}</span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {money(linha.market_avg)}
                        <span className="block text-xs text-muted-foreground">mediana {money(linha.market_median)}</span>
                      </td>
                      <td className={`py-2 pr-3 text-right tabular-nums ${corRatio(linha.ratio)}`}>
                        {linha.ratio ? `${linha.ratio.toFixed(2)}×` : "—"}
                        {linha.ratio_median ? (
                          <span className="block text-xs text-muted-foreground">mediana {linha.ratio_median.toFixed(2)}×</span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {linha.share_pct !== null && linha.share_pct !== undefined
                          ? `${linha.share_pct.toLocaleString("pt-PT", { maximumFractionDigits: 1 })} %`
                          : "—"}
                        <span className="block text-xs text-muted-foreground">{moneyShort(linha.value)}</span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {num(linha.suppliers)}
                        <span className="block max-w-[12rem] truncate text-xs text-muted-foreground">
                          {linha.competitors.map((item) => limparNome(item.name).split(" ")[0]).slice(0, 3).join(", ")}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <SerieRatio linha={linha} />
                        <span className="block text-[10px] tabular-nums text-muted-foreground">
                          {linha.years
                            .slice(0, 4)
                            .map((ano) => `${ano.year}:${ano.ratio ? ano.ratio.toFixed(2) : "—"}`)
                            .join(" · ")}
                        </span>
                      </td>
                      <td className="py-2">
                        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${corRisco(linha.risk)}`}>
                          {linha.risk}
                        </span>
                        <span className="mt-1 block max-w-[18rem] text-[11px] text-muted-foreground">
                          {linha.risk_reason}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Como ler (e o que não se conclui)</summary>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {dados.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </details>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
