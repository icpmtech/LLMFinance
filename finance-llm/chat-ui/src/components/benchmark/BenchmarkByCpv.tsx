/**
 * **Benchmark conjunto (Portugal, Espanha e França), por CPV** — `/benchmark`.
 *
 * Não compara empresas entre países (os mercados não são comparáveis um a um):
 * agrega por **CPV** e mostra, para cada classificação, o volume, o valor e o
 * preço mediano de cada país. Serve para ver onde há mercado, a que preço e em
 * que geografia — e daí saltar para a página do país com esse CPV.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Briefcase, Building2, Globe2, Loader2, MapPin, RefreshCw, Scale, ShoppingCart, Target } from "lucide-react";

import { Button } from "../ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";
import {
  getBenchmarkByCpv,
  getBenchmarkByEntity,
  type BenchmarkByCpvResponse,
  type BenchmarkByEntityResponse,
  type BenchmarkCountry,
  type BenchmarkMetaAll,
  type BenchmarkRole,
} from "../../benchmarkApi";
import { SeletorAno } from "./BenchmarkPickers";

const MAX_ANOS = 12;
const PAISES_ORDEM: BenchmarkCountry[] = ["pt", "es", "fr"];

const ROTULO_PAIS: Record<BenchmarkCountry, string> = {
  pt: "Portugal",
  es: "Espanha",
  fr: "França",
};

const COR_PAIS: Record<BenchmarkCountry, string> = {
  pt: "text-emerald-300",
  es: "text-amber-300",
  fr: "text-sky-300",
};

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

/** Cartão de um país (volume e preço de referência). */
function CartaoPais({
  short,
  label,
  contracts,
  totalValue,
  median,
}: {
  short: string;
  label: string;
  contracts: number;
  totalValue: number;
  median?: number | null;
}) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex items-center gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/5 text-xs font-semibold">
          {short}
        </div>
        <div className="min-w-0">
          <p className="truncate text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="truncate text-lg font-semibold tabular-nums">{num(contracts)}</p>
          <p className="truncate text-xs text-muted-foreground">
            {moneyShort(totalValue)} · mediana {money(median)}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function BenchmarkByCpv({ meta }: { meta: BenchmarkMetaAll | null }) {
  const [paises, setPaises] = useState<BenchmarkCountry[]>(PAISES_ORDEM);
  const [cpvFiltro, setCpvFiltro] = useState("");
  const [anoDe, setAnoDe] = useState<number | "">("");
  const [anoAte, setAnoAte] = useState<number | "">("");
  const [top, setTop] = useState(40);
  const [dados, setDados] = useState<BenchmarkByCpvResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Empresas (e os seus CPV) — a lista muda de papel com um clique.
  const [papel, setPapel] = useState<BenchmarkRole>("adjudicatario");
  const [empresas, setEmpresas] = useState<BenchmarkByEntityResponse | null>(null);
  const [aCarregarEmpresas, setACarregarEmpresas] = useState(false);

  const anos = useMemo(() => (meta?.years ?? []).slice(0, MAX_ANOS), [meta]);

  const carregarEmpresas = useCallback(
    async (override?: { role?: BenchmarkRole; cpv_code?: string; anoDe?: number | ""; anoAte?: number | "" }) => {
      const de = override?.anoDe ?? anoDe;
      const ate = override?.anoAte ?? anoAte;
      const papelAtual = override?.role ?? papel;
      setACarregarEmpresas(true);
      try {
        const resultado = await getBenchmarkByEntity({
          countries: paises,
          role: papelAtual,
          cpv_code: override?.cpv_code ?? cpvFiltro.trim() ?? undefined,
          year_from: de === "" ? undefined : Number(de),
          year_to: ate === "" ? undefined : Number(ate),
          size: 8,
          cpv_size: 5,
        });
        setEmpresas(resultado);
      } catch (err) {
        setEmpresas(null);
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setACarregarEmpresas(false);
      }
    },
    [paises, papel, cpvFiltro, anoDe, anoAte],
  );

  const carregar = useCallback(
    async (override?: { cpv_code?: string; anoDe?: number | ""; anoAte?: number | "" }) => {
      if (!paises.length) {
        setErro("Escolha pelo menos um país.");
        return;
      }
      const de = override?.anoDe ?? anoDe;
      const ate = override?.anoAte ?? anoAte;
      setACarregar(true);
      setErro(null);
      void carregarEmpresas(override);
      try {
        const resultado = await getBenchmarkByCpv({
          countries: paises,
          cpv_code: override?.cpv_code ?? cpvFiltro.trim() ?? undefined,
          year_from: de === "" ? undefined : Number(de),
          year_to: ate === "" ? undefined : Number(ate),
          top,
        });
        setDados(resultado);
      } catch (err) {
        setDados(null);
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setACarregar(false);
      }
    },
    [paises, cpvFiltro, anoDe, anoAte, top],
  );

  // Primeira leitura ao abrir a página, já com os anos por omissão da meta.
  useEffect(() => {
    if (!meta || dados || aCarregar) return;
    const recentes = (meta.years ?? []).slice(0, MAX_ANOS);
    const de: number | "" = recentes.length ? Math.min(...recentes) : "";
    const ate: number | "" = recentes.length ? Math.max(...recentes) : "";
    setAnoDe(de);
    setAnoAte(ate);
    void carregar({ anoDe: de, anoAte: ate });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta]);

  const alternarPais = (pais: BenchmarkCountry) => {
    setPaises((atuais) => (atuais.includes(pais) ? atuais.filter((p) => p !== pais) : [...atuais, pais]));
  };

  const abrirNoPais = (pais: BenchmarkCountry, codigo: string) => {
    const caminho = `/benchmark/${pais === "pt" ? "portugal" : pais === "es" ? "espanha" : "franca"}`;
    window.location.assign(`${caminho}?cpv=${encodeURIComponent(codigo)}`);
  };

  const colunas = dados?.countries ?? [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Globe2 size={16} /> Segmento por CPV — Portugal, Espanha e França
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div>
              <Label htmlFor="bycpv-filtro">CPV (prefixo, opcional)</Label>
              <Input
                id="bycpv-filtro"
                className="mt-1"
                autoComplete="off"
                placeholder="ex.: 33600"
                value={cpvFiltro}
                onChange={(e) => setCpvFiltro(e.target.value)}
              />
            </div>
            <SeletorAno id="bycpv-ano-de" label="Ano de" anos={anos} value={anoDe} onChange={setAnoDe} />
            <SeletorAno id="bycpv-ano-ate" label="Ano até" anos={anos} value={anoAte} onChange={setAnoAte} />
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Label htmlFor="bycpv-top">Quantos CPV</Label>
                <Input
                  id="bycpv-top"
                  className="mt-1"
                  type="number"
                  min={5}
                  max={200}
                  value={top}
                  onChange={(e) => setTop(Math.max(5, Math.min(200, Number(e.target.value) || 40)))}
                />
              </div>
              <Button
                onClick={() => void carregar()}
                loading={aCarregar}
                icon={<RefreshCw size={16} />}
                className="mb-0.5"
              >
                Atualizar
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Países:</span>
            {PAISES_ORDEM.map((pais) => {
              const activo = paises.includes(pais);
              return (
                <button
                  key={pais}
                  type="button"
                  onClick={() => alternarPais(pais)}
                  className={`rounded-full border px-3 py-1.5 text-xs transition ${
                    activo ? "border-sky-400/40 bg-sky-400/10 text-sky-200" : "border-border text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {ROTULO_PAIS[pais]}
                </button>
              );
            })}
            {cpvFiltro ? (
              <span className="text-xs text-muted-foreground">
                · filtrado por CPV começado em <strong>{cpvFiltro}</strong>
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {erro ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">{erro}</span>
        </div>
      ) : null}

      {aCarregar && !dados ? (
        <div className="flex flex-col items-center justify-center py-14">
          <Loader2 size={30} className="mb-3 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">A cruzar os contratos dos três países…</p>
        </div>
      ) : null}

      {dados ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {dados.countries.map((info) => (
              <CartaoPais
                key={info.country}
                short={info.short}
                label={info.label}
                contracts={info.contracts}
                totalValue={info.total_value}
                median={info.median}
              />
            ))}
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Scale size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">CPV por valor contratado</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">
                {num(dados.items.length)} classificações · clique num CPV para o analisar no país
              </span>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">#</th>
                      <th className="py-2 pr-3">CPV</th>
                      {colunas.map((info) => (
                        <th key={info.country} className={`py-2 pr-3 text-right ${COR_PAIS[info.country]}`}>
                          {info.short}
                        </th>
                      ))}
                      <th className="py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dados.items.map((linha) => (
                      <tr key={linha.code} className="border-b border-border/40 align-top">
                        <td className="py-2 pr-3 text-xs tabular-nums text-muted-foreground">{linha.rank}</td>
                        <td className="py-2 pr-3">
                          <p className="font-medium tabular-nums">{linha.code}</p>
                          <p className="line-clamp-2 max-w-[26rem] text-xs text-muted-foreground">
                            {linha.description || "—"}
                          </p>
                        </td>
                        {colunas.map((info) => {
                          const celula = linha.by_country[info.country];
                          return (
                            <td key={info.country} className="py-2 pr-3 text-right">
                              {celula ? (
                                <button
                                  type="button"
                                  className="text-right transition hover:text-foreground"
                                  title={`Abrir o benchmark de ${info.label} no CPV ${linha.code}`}
                                  onClick={() => abrirNoPais(info.country, linha.code)}
                                >
                                  <span className="block tabular-nums">{num(celula.contracts)}</span>
                                  <span className="block text-xs text-muted-foreground">
                                    {moneyShort(celula.value)} · mediana {moneyShort(celula.median)}
                                  </span>
                                </button>
                              ) : (
                                <span className="text-xs text-muted-foreground/60">—</span>
                              )}
                            </td>
                          );
                        })}
                        <td className="py-2 text-right">
                          <span className="block font-medium tabular-nums">{moneyShort(linha.value)}</span>
                          <span className="block text-xs text-muted-foreground">{num(linha.contracts)} contratos</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* -------------------------------------------- empresas e os seus CPV */}
          <Card>
            <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
              <Briefcase size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Empresas e os seus CPV</CardTitle>
              {aCarregarEmpresas ? <Loader2 size={14} className="animate-spin text-muted-foreground" /> : null}
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (papel === "adjudicatario") return;
                    setPapel("adjudicatario");
                    void carregarEmpresas({ role: "adjudicatario" });
                  }}
                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
                    papel === "adjudicatario"
                      ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"
                      : "border-border text-muted-foreground hover:bg-accent"
                  }`}
                >
                  <ShoppingCart size={13} /> Vendem
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (papel === "adjudicante") return;
                    setPapel("adjudicante");
                    void carregarEmpresas({ role: "adjudicante" });
                  }}
                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
                    papel === "adjudicante"
                      ? "border-sky-400/40 bg-sky-400/10 text-sky-200"
                      : "border-border text-muted-foreground hover:bg-accent"
                  }`}
                >
                  <Building2 size={13} /> Compram
                </button>
                <span className="text-xs text-muted-foreground">
                  clique num CPV para o isolar nos dois quadros
                </span>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {empresas?.items?.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-sm">
                    <thead>
                      <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="py-2 pr-3">País</th>
                        <th className="py-2 pr-3">Empresa</th>
                        <th className="py-2 pr-3 text-right">Contratos</th>
                        <th className="py-2 pr-3 text-right">Valor</th>
                        <th className="py-2 pr-3 text-right">Quota</th>
                        <th className="py-2">CPV principais</th>
                      </tr>
                    </thead>
                    <tbody>
                      {empresas.items.map((linha) => (
                        <tr key={`${linha.country}-${linha.nif}`} className="border-b border-border/40 align-top">
                          <td className="py-2 pr-3">
                            <span className={`text-xs font-semibold ${COR_PAIS[linha.country]}`}>{linha.short}</span>
                          </td>
                          <td className="py-2 pr-3">
                            <p className="max-w-[22rem] truncate font-medium" title={linha.name}>
                              {linha.name}
                            </p>
                            <p className="text-xs text-muted-foreground tabular-nums">
                              {linha.nif !== linha.name ? `${linha.nif} · ` : ""}#{linha.rank ?? "—"} em{" "}
                              {linha.country_label}
                            </p>
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">{num(linha.contracts)}</td>
                          <td className="py-2 pr-3 text-right tabular-nums">{moneyShort(linha.value)}</td>
                          <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                            {linha.share_pct !== null && linha.share_pct !== undefined
                              ? `${linha.share_pct.toLocaleString("pt-PT", { maximumFractionDigits: 2 })} %`
                              : "—"}
                          </td>
                          <td className="py-2">
                            <div className="flex flex-wrap gap-1.5">
                              {linha.cpvs.map((cpv) => (
                                <button
                                  key={cpv.code}
                                  type="button"
                                  title={cpv.description || cpv.code}
                                  onClick={() => {
                                    setCpvFiltro(cpv.code);
                                    void carregar({ cpv_code: cpv.code });
                                  }}
                                  className="rounded-full border border-border px-2 py-0.5 text-xs transition hover:border-sky-400/40 hover:bg-sky-400/10 hover:text-sky-200"
                                >
                                  <span className="tabular-nums">{cpv.code}</span>
                                  <span className="ml-1 text-muted-foreground">{num(cpv.count)}</span>
                                </button>
                              ))}
                              {linha.cpvs.length ? null : <span className="text-xs text-muted-foreground/60">—</span>}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {empresas.items.some((linha) => linha.cpvs.some((cpv) => cpv.description)) ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Os números nas fichas de CPV são contratos dessa empresa nessa classificação.
                    </p>
                  ) : null}
                </div>
              ) : aCarregarEmpresas ? (
                <p className="py-6 text-center text-sm text-muted-foreground">A juntar as empresas…</p>
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Sem empresas para estes filtros. Aumente a janela de anos ou retire o CPV.
                </p>
              )}
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Target size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">Ler esta página</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-0 text-sm text-muted-foreground">
                <p>
                  Cada linha é uma classificação CPV; as colunas mostram quantos contratos e que valor cada país tem
                  nessa classificação (e a mediana do preço por contrato).
                </p>
                <p>
                  Clique num país para abrir o benchmark desse país já no CPV escolhido — aí pode ver o preço de
                  referência, os concorrentes e comparar empresas.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <MapPin size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">Notas</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="list-inside list-disc space-y-1 text-xs text-muted-foreground">
                  {dados.notes.map((nota) => (
                    <li key={nota}>{nota}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
