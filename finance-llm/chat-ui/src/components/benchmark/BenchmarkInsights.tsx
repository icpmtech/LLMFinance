/**
 * **Anomalias, concentração e oportunidades** de uma entidade no seu segmento.
 *
 * Dois cartões que só aparecem depois de haver uma análise feita:
 *
 * - **Anomalias e concentração** — contratos acima do p90 do segmento, se o
 *   preço da empresa está acima/abaixo da mediana do mercado (global e por CPV),
 *   quantos fornecedores há em cada CPV, concentração da carteira e contratos
 *   que ficaram de fora das estatísticas por terem valores fora dos limites;
 * - **Onde pode vender mais** — os CPV que os compradores da empresa contratam
 *   mas onde ela não vende, com a mediana praticada e quem já vende ali.
 *
 * Os números vêm do servidor (`/benchmark/anomalies` e `/benchmark/gaps`), pelo
 * que a explicação mostrada é a mesma que sai no relatório em PDF.
 */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeEuro,
  Lightbulb,
  Loader2,
  ShieldAlert,
  TrendingUp,
  Users,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import EmpresaLogo from "./EmpresaLogo";
import { usePerfisEmpresas } from "./usePerfisEmpresas";
import {
  getBenchmarkAnomalies,
  getBenchmarkGaps,
  type BenchmarkAnomaliesResponse,
  type BenchmarkGapsResponse,
  type BenchmarkQuery,
} from "../../benchmarkApi";
import { limparNome } from "./texto";

function money(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function moneyShort(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 10_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return money(value);
}

function num(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT");
}

function corSeveridade(severidade: string): string {
  if (severidade === "alta") return "border-rose-400/30 bg-rose-400/10 text-rose-200";
  if (severidade === "media") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  return "border-border bg-white/[0.03] text-muted-foreground";
}

function corVeredicto(texto: string): string {
  if (/um só fornecedor|dominado/.test(texto)) return "text-rose-300";
  if (/pouca concorrência|acima da mediana/.test(texto)) return "text-amber-300";
  if (/abaixo da mediana/.test(texto)) return "text-emerald-300";
  return "text-muted-foreground";
}

export default function BenchmarkInsights({ query, ativo }: { query: BenchmarkQuery | null; ativo: boolean }) {
  const [anomalias, setAnomalias] = useState<BenchmarkAnomaliesResponse | null>(null);
  const [lacunas, setLacunas] = useState<BenchmarkGapsResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const chave = useMemo(() => (query ? JSON.stringify(query) : ""), [query]);

  // Concorrentes que já vendem nestes CPV: traz-se a marca de cada um (cache do
  // servidor primeiro; os que faltam são resolvidos em segundo plano).
  const concorrentes = useMemo(() => {
    const mapa = new Map<string, { nif?: string | null; nome?: string | null }>();
    for (const lacuna of lacunas?.gaps ?? []) {
      for (const concorrente of lacuna.competition ?? []) {
        const identificador = concorrente.nif || concorrente.name;
        if (identificador && !mapa.has(identificador)) {
          mapa.set(identificador, { nif: concorrente.nif, nome: concorrente.name });
        }
      }
    }
    return Array.from(mapa.values()).slice(0, 12);
  }, [lacunas]);

  const { perfis } = usePerfisEmpresas(concorrentes, { ativo, pais: query?.country ?? "pt" });

  useEffect(() => {
    if (!ativo || !query) {
      setAnomalias(null);
      setLacunas(null);
      return;
    }
    let vivo = true;
    setACarregar(true);
    setErro(null);
    Promise.all([
      getBenchmarkAnomalies({ ...query, top_cpvs: 6 }),
      // As oportunidades ignoram o CPV escolhido: o objetivo é encontrar outros.
      getBenchmarkGaps({
        nif: query.nif,
        name: query.name,
        role: query.role,
        country: query.country,
        year_from: query.year_from,
        year_to: query.year_to,
        top_buyers: 25,
        size: 12,
      }),
    ])
      .then(([primeiro, segundo]) => {
        if (!vivo) return;
        setAnomalias(primeiro);
        setLacunas(segundo);
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
    <div className="space-y-4">
      {aCarregar && !anomalias ? (
        <div className="flex items-center gap-2 rounded-xl border border-border/60 px-3 py-3 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" /> A procurar anomalias e oportunidades…
        </div>
      ) : null}

      {erro ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">{erro}</span>
        </div>
      ) : null}

      {/* ------------------------------------------ anomalias e concentração */}
      {anomalias && !anomalias.error ? (
        <Card>
          <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
            <ShieldAlert size={16} className="text-muted-foreground" />
            <CardTitle className="text-sm">Anomalias de preço e concentração</CardTitle>
            <span className="ml-auto text-xs text-muted-foreground">
              mediana do segmento {money(anomalias.reference.median)} · p90 {money(anomalias.reference.p90)}
            </span>
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            {anomalias.items.length ? (
              <ul className="space-y-2">
                {anomalias.items.map((item) => (
                  <li
                    key={`${item.kind}-${item.title}`}
                    className={`rounded-xl border px-3 py-2 text-xs ${corSeveridade(item.severity)}`}
                  >
                    <p className="font-medium">{item.title}</p>
                    <p className="mt-0.5 opacity-90">{item.detail}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sem sinais relevantes: preços na linha do mercado e concorrência normal para o perfil.
              </p>
            )}

            {anomalias.outliers.length ? (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted-foreground">
                  <BadgeEuro size={13} /> Contratos acima do p90
                </p>
                <ul className="divide-y divide-border/50">
                  {anomalias.outliers.map((contrato, indice) => (
                    <li key={`${contrato.id ?? indice}`} className="flex flex-wrap items-center gap-2 py-1.5 text-xs">
                      <span className="min-w-0 flex-1 truncate" title={contrato.object ?? ""}>
                        {contrato.object || "—"}
                      </span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{contrato.counterpart || "—"}</span>
                      <span className="shrink-0 font-medium tabular-nums">{moneyShort(contrato.value)}</span>
                      {contrato.times_p90 ? (
                        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 tabular-nums">
                          {contrato.times_p90.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}× p90
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {anomalias.by_cpv.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">CPV</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 pr-3 text-right">Quota</th>
                      <th className="py-2 pr-3 text-right">Mediana empresa</th>
                      <th className="py-2 pr-3 text-right">Mediana mercado</th>
                      <th className="py-2 pr-3 text-right">Fornecedores</th>
                      <th className="py-2">Leitura</th>
                    </tr>
                  </thead>
                  <tbody>
                    {anomalias.by_cpv.map((linha) => (
                      <tr key={linha.code} className="border-b border-border/40 align-top">
                        <td className="py-2 pr-3">
                          <p className="font-medium tabular-nums">{linha.code}</p>
                          <p className="line-clamp-1 max-w-[22rem] text-xs text-muted-foreground">
                            {linha.description || "—"}
                          </p>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {num(linha.contracts)}
                          <span className="block text-xs text-muted-foreground">de {num(linha.market_contracts)}</span>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {linha.share_pct !== null && linha.share_pct !== undefined
                            ? `${linha.share_pct.toLocaleString("pt-PT", { maximumFractionDigits: 1 })} %`
                            : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{money(linha.entity_median)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{money(linha.market_median)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{num(linha.suppliers)}</td>
                        <td className="py-2 text-xs">
                          <span className={corVeredicto(linha.competition_verdict)}>{linha.competition_verdict}</span>
                          <span className="block text-muted-foreground">
                            {linha.ratio
                              ? `${linha.ratio.toLocaleString("pt-PT", { maximumFractionDigits: 2 })}× — ${linha.price_verdict}`
                              : linha.price_verdict}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Como ler estes sinais</summary>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {anomalias.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </details>
          </CardContent>
        </Card>
      ) : null}

      {/* --------------------------------------------------- oportunidades */}
      {lacunas && !lacunas.error ? (
        <Card>
          <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
            <Lightbulb size={16} className="text-muted-foreground" />
            <CardTitle className="text-sm">
              {lacunas.role === "adjudicatario" ? "Onde pode vender mais" : "O que pode comprar e ainda não compra"}
            </CardTitle>
            <span className="ml-auto text-xs text-muted-foreground">
              base: {num(lacunas.buyers.length)} contrapartes · {num(lacunas.entity.cpvs_known)} CPV conhecidos
            </span>
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            <p className="text-xs text-muted-foreground">
              {lacunas.role === "adjudicatario"
                ? "CPV que estes compradores contratam no período e onde esta empresa não tem contratos."
                : "CPV que estes fornecedores vendem no período e onde esta entidade não compra."}
            </p>
            {lacunas.gaps.length ? (
              <ul className="divide-y divide-border/50">
                {lacunas.gaps.map((linha) => (
                  <li key={linha.code} className="py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium tabular-nums">{linha.code}</span>
                      <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground" title={linha.description ?? ""}>
                        {linha.description || "—"}
                      </span>
                      <span className="text-sm font-medium tabular-nums">{moneyShort(linha.value)}</span>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {num(linha.contracts)} contratos · mediana {money(linha.median)}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Users size={12} /> {linha.buyers_total} destes compradores
                      </span>
                      <span className="flex items-center gap-1">
                        <TrendingUp size={12} /> já vendem ali:
                        {linha.competition.slice(0, 2).map((concorrente) => (
                          <span
                            key={concorrente.nif}
                            className="inline-flex items-center gap-1 rounded-full border border-border pl-0.5 pr-2 py-0.5"
                          >
                            <EmpresaLogo
                              nome={concorrente.name}
                              nif={concorrente.nif}
                              logoUrl={perfis[concorrente.nif]?.logo_url}
                              size={16}
                            />
                            {limparNome(concorrente.name).slice(0, 26) || concorrente.nif}
                          </span>
                        ))}
                      </span>
                      <span className="truncate">
                        {linha.buyers
                          .slice(0, 2)
                          .map((comprador) => `${limparNome(comprador.name).slice(0, 24) || comprador.nif} (${num(comprador.count)})`)
                          .join(" · ")}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Não há CPV destes compradores onde a empresa não venda — a carteira já cobre o que eles compram.
              </p>
            )}
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Como ler estas oportunidades</summary>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {lacunas.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </details>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
