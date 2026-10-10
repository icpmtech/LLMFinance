/**
 * **Cruzar empresas de países diferentes** — `/benchmark/cruzar`.
 *
 * Cada empresa vem do seu próprio registo (PT, ES ou FR) e é analisada no
 * mercado dela; o que se compara **entre países** é aquilo que é comparável:
 *
 * - o **CPV** (a única classificação comum aos três registos) — onde as
 *   empresas se encontram e quanto pesa cada uma nessa classificação;
 * - as **contrapartes em comum** — quem compra (ou vende) a duas ou mais delas;
 * - a **posição relativa** dentro de cada mercado (índice de preço, quota,
 *   ranking), porque os preços absolutos não são comparáveis entre países.
 *
 * O grafo (Mermaid) é gerado a partir dos mesmos dados: empresas de um lado,
 * CPV (ou contrapartes) comuns do outro.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeEuro,
  Building2,
  GitCompare,
  Globe2,
  Handshake,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Scale,
  ShoppingCart,
  Target,
  Trash2,
} from "lucide-react";

import { Button } from "../ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";
import { MermaidDiagram } from "../world/MermaidDiagram";
import {
  MAX_CROSS,
  compareBenchmarkCross,
  getBenchmarkMeta,
  type BenchmarkCountry,
  type BenchmarkCrossResponse,
  type BenchmarkMetaAll,
  type BenchmarkRole,
} from "../../benchmarkApi";
import { EmpresaAutocomplete, SeletorAno, type EmpresaBenchmark } from "./BenchmarkPickers";

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

/** Cores dos nós do grafo (fundos escuros combinam com o tema da app). */
const ESTILO_PAIS: Record<BenchmarkCountry, string> = {
  pt: "#065f46",
  es: "#78350f",
  fr: "#1e3a8a",
};

function money(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function moneyShort(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} M€`;
  if (abs >= 10_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return money(value);
}

function num(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT");
}

function indice(valor?: number | null): { texto: string; cor: string } {
  if (valor === undefined || valor === null) return { texto: "—", cor: "text-muted-foreground" };
  const texto = `${valor.toLocaleString("pt-PT", { maximumFractionDigits: 2 })}× mediana do mercado`;
  if (valor < 0.9) return { texto, cor: "text-emerald-300" };
  if (valor > 1.1) return { texto, cor: "text-amber-300" };
  return { texto, cor: "text-muted-foreground" };
}

/** Linha do configurador: país + empresa escolhida. */
type Linha = { id: number; country: BenchmarkCountry; empresa: EmpresaBenchmark | null };

/** Identificador seguro para o Mermaid (só letras e dígitos). */
function idSeguro(prefixo: string, valor: string): string {
  return `${prefixo}${valor.replace(/[^A-Za-z0-9]/g, "")}`.slice(0, 40) || `${prefixo}X`;
}

/** Texto Mermaid do grafo: empresas ↔ CPV (ou ↔ contrapartes) em comum. */
function grafoMermaid(
  dados: BenchmarkCrossResponse,
  modo: "cpv" | "contrapartes",
): string {
  const ligacoes =
    modo === "cpv"
      ? dados.shared_cpvs.map((item) => ({
          id: idSeguro("cpv", item.code || ""),
          titulo: `${item.code}${item.description ? `<br/>${item.description.slice(0, 42)}` : ""}`,
          rotulo: item.code || "",
          item,
        }))
      : dados.shared_counterparties.map((item) => ({
          id: idSeguro("ctr", item.nif || item.name || ""),
          titulo: `${(item.name || item.nif || "").slice(0, 38)}`,
          rotulo: item.name || item.nif || "",
          item,
        }));

  const linhas: string[] = ["flowchart LR"];
  dados.companies.forEach((empresa, indiceEmpresa) => {
    const id = `e${indiceEmpresa}`;
    linhas.push(`  ${id}["${empresa.name.slice(0, 34)}<br/>${empresa.short}"]:::pais_${empresa.country}`);
  });

  for (const ligacao of ligacoes) {
    linhas.push(`  ${ligacao.id}["${ligacao.titulo}"]:::alvo`);
    for (const empresa of ligacao.item.companies) {
      const indiceEmpresa = dados.companies.findIndex(
        (candidata) => candidata.short === empresa.short && candidata.name === empresa.name,
      );
      if (indiceEmpresa < 0) continue;
      linhas.push(`  e${indiceEmpresa} -->|"${num(empresa.count)}"| ${ligacao.id}`);
    }
  }

  for (const pais of PAISES_ORDEM) {
    if (!dados.companies.some((empresa) => empresa.country === pais)) continue;
    linhas.push(`  classDef pais_${pais} fill:${ESTILO_PAIS[pais]},stroke:#94a3b8,color:#f8fafc`);
  }
  linhas.push("  classDef alvo fill:#111827,stroke:#64748b,color:#e2e8f0");
  return linhas.join("\n");
}

export default function BenchmarkCross({ onOpenCountry }: { onOpenCountry?: (pais: BenchmarkCountry, cpv: string) => void }) {
  const [meta, setMeta] = useState<BenchmarkMetaAll | null>(null);
  const [linhas, setLinhas] = useState<Linha[]>([
    { id: 1, country: "pt", empresa: null },
    { id: 2, country: "es", empresa: null },
  ]);
  const [proximoId, setProximoId] = useState(3);
  const [role, setRole] = useState<BenchmarkRole>("adjudicatario");
  const [cpv, setCpv] = useState("");
  const [anoDe, setAnoDe] = useState<number | "">("");
  const [anoAte, setAnoAte] = useState<number | "">("");
  const [dados, setDados] = useState<BenchmarkCrossResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [modoGrafo, setModoGrafo] = useState<"cpv" | "contrapartes">("cpv");

  const anos = useMemo(() => (meta?.years ?? []).slice(0, MAX_ANOS), [meta]);
  const vender = role === "adjudicatario";
  const escolhidas = linhas.filter((linha) => linha.empresa);

  useEffect(() => {
    getBenchmarkMeta("all")
      .then((resultado) => {
        setMeta(resultado);
        const recentes = (resultado.years ?? []).slice(0, MAX_ANOS);
        if (recentes.length) {
          setAnoDe(Math.min(...recentes));
          setAnoAte(Math.max(...recentes));
        }
      })
      .catch((err: unknown) => setErro(err instanceof Error ? err.message : String(err)));
  }, []);

  const cruzar = useCallback(async () => {
    if (escolhidas.length < 2) {
      setErro("Escolha pelo menos duas empresas (podem ser de países diferentes).");
      return;
    }
    setACarregar(true);
    setErro(null);
    try {
      const resultado = await compareBenchmarkCross({
        entities: escolhidas.map((linha) => ({
          country: linha.country,
          nif: linha.empresa?.nif || undefined,
          name: linha.empresa?.name || undefined,
        })),
        role,
        cpv_code: cpv.trim() || undefined,
        year_from: anoDe === "" ? undefined : Number(anoDe),
        year_to: anoAte === "" ? undefined : Number(anoAte),
        top: 20,
      });
      setDados(resultado);
    } catch (err) {
      setDados(null);
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregar(false);
    }
  }, [escolhidas, role, cpv, anoDe, anoAte]);

  const mudarPais = (id: number, country: BenchmarkCountry) =>
    setLinhas((atuais) => atuais.map((linha) => (linha.id === id ? { ...linha, country, empresa: null } : linha)));

  const escolher = (id: number, empresa: EmpresaBenchmark) =>
    setLinhas((atuais) => atuais.map((linha) => (linha.id === id ? { ...linha, empresa } : linha)));

  const limparLinha = (id: number) =>
    setLinhas((atuais) => atuais.map((linha) => (linha.id === id ? { ...linha, empresa: null } : linha)));

  const juntarLinha = () =>
    setLinhas((atuais) => {
      if (atuais.length >= MAX_CROSS) return atuais;
      const usados = new Set(atuais.map((linha) => linha.country));
      const livre = PAISES_ORDEM.find((pais) => !usados.has(pais)) ?? "pt";
      return [...atuais, { id: proximoId, country: livre, empresa: null }];
    });

  const removerLinha = (id: number) => {
    setLinhas((atuais) => (atuais.length <= 2 ? atuais : atuais.filter((linha) => linha.id !== id)));
  };

  useEffect(() => {
    setProximoId((atual) => atual + 1);
  }, [linhas.length]);

  const grafo = useMemo(() => (dados ? grafoMermaid(dados, modoGrafo) : ""), [dados, modoGrafo]);

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------ configurador */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitCompare size={16} /> Empresas a cruzar (países diferentes)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            {linhas.map((linha, indice) => (
              <div key={linha.id} className="grid grid-cols-1 gap-3 lg:grid-cols-[10rem_1fr_auto]">
                <div>
                  <Label htmlFor={`cross-pais-${linha.id}`}>País</Label>
                  <select
                    id={`cross-pais-${linha.id}`}
                    className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                    value={linha.country}
                    onChange={(e) => mudarPais(linha.id, e.target.value as BenchmarkCountry)}
                  >
                    {PAISES_ORDEM.map((pais) => (
                      <option key={pais} value={pais}>
                        {ROTULO_PAIS[pais]}
                      </option>
                    ))}
                  </select>
                </div>
                <EmpresaAutocomplete
                  id={`cross-empresa-${linha.id}`}
                  country={linha.country}
                  role={role}
                  value={linha.empresa}
                  onSelect={(empresa) => escolher(linha.id, empresa)}
                  onClear={() => limparLinha(linha.id)}
                  label={`Empresa ${indice + 1}`}
                />
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    size="md"
                    onClick={() => removerLinha(linha.id)}
                    disabled={linhas.length <= 2}
                    icon={<Trash2 size={15} />}
                  >
                    Remover
                  </Button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="md"
              onClick={juntarLinha}
              disabled={linhas.length >= MAX_CROSS}
              icon={<Plus size={15} />}
            >
              Juntar empresa
            </Button>
            <span className="text-xs text-muted-foreground">
              {escolhidas.length}/{MAX_CROSS} escolhidas
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div>
              <Label>Papel comum</Label>
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  onClick={() => setRole("adjudicatario")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    vender ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <ShoppingCart size={15} /> Vendem
                </button>
                <button
                  type="button"
                  onClick={() => setRole("adjudicante")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    !vender ? "border-sky-400/40 bg-sky-400/10 text-sky-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <Building2 size={15} /> Compram
                </button>
              </div>
            </div>
            <div>
              <Label htmlFor="cross-cpv">CPV (prefixo, opcional)</Label>
              <Input
                id="cross-cpv"
                className="mt-1"
                autoComplete="off"
                placeholder="ex.: 33600"
                value={cpv}
                onChange={(e) => setCpv(e.target.value)}
              />
            </div>
            <SeletorAno id="cross-ano-de" label="Ano de" anos={anos} value={anoDe} onChange={setAnoDe} />
            <SeletorAno id="cross-ano-ate" label="Ano até" anos={anos} value={anoAte} onChange={setAnoAte} />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => void cruzar()}
              loading={aCarregar}
              disabled={escolhidas.length < 2}
              icon={<Globe2 size={16} />}
            >
              Cruzar mercados
            </Button>
            {dados ? (
              <Button
                variant="outline"
                size="md"
                icon={<RefreshCw size={15} />}
                onClick={() => void cruzar()}
                disabled={aCarregar}
              >
                Atualizar
              </Button>
            ) : null}
          </div>

          <p className="text-xs text-muted-foreground">
            {vender
              ? "Empresas que vendem ao Estado: o cruzamento mostra os CPV e os compradores que têm em comum."
              : "Entidades que compram: o cruzamento mostra os CPV e os fornecedores que têm em comum."}
          </p>
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
          <p className="text-sm text-muted-foreground">A analisar cada empresa no seu mercado…</p>
        </div>
      ) : null}

      {dados ? (
        <>
          {/* ------------------------------------------- cartões por empresa */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {dados.companies.map((empresa) => {
              const posicao = indice(empresa.price_index);
              return (
                <Card key={`${empresa.country}-${empresa.nif}`} className="min-w-0">
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <span className={`text-xs font-semibold ${COR_PAIS[empresa.country]}`}>{empresa.short}</span>
                      <span className="min-w-0 truncate" title={empresa.name}>
                        {empresa.name}
                      </span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 pt-0 text-sm">
                    {!empresa.present ? (
                      <p className="text-xs text-amber-200">Sem contratos neste segmento.</p>
                    ) : (
                      <>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Contratos</span>
                          <span className="tabular-nums">{num(empresa.contracts)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Valor</span>
                          <span className="tabular-nums">{moneyShort(empresa.total_value)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Mediana da empresa</span>
                          <span className="tabular-nums">{money(empresa.median)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Mediana do mercado</span>
                          <span className="tabular-nums">{money(empresa.market.median)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Índice de preço</span>
                          <span className={`text-xs tabular-nums ${posicao.cor}`}>{posicao.texto}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">Posição no país</span>
                          <span className="tabular-nums">
                            {empresa.rank ? `#${empresa.rank}` : "—"}
                            {empresa.share_pct !== null && empresa.share_pct !== undefined
                              ? ` · ${empresa.share_pct.toLocaleString("pt-PT", { maximumFractionDigits: 2 })} %`
                              : ""}
                          </span>
                        </div>
                      </>
                    )}
                    {empresa.recent?.length ? (
                      <div className="pt-1">
                        <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Contratos recentes</p>
                        <ul className="space-y-1">
                          {empresa.recent.slice(0, 3).map((contrato) => (
                            <li key={`${empresa.nif}-${contrato.idcontrato ?? contrato.date}`} className="text-xs">
                              <span className="block truncate text-muted-foreground" title={contrato.objecto ?? ""}>
                                {contrato.objecto || "—"}
                              </span>
                              <span className="tabular-nums">
                                {moneyShort(contrato.value)} · {contrato.date?.slice(0, 10) ?? "—"}
                                {contrato.counterpart ? ` · ${contrato.counterpart.slice(0, 28)}` : ""}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* ---------------------------------------------------- CPV em comum */}
          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Target size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">CPV em comum</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">
                {num(dados.shared_cpvs.length)} classificações onde duas ou mais destas empresas atuam
              </span>
            </CardHeader>
            <CardContent className="pt-0">
              {dados.shared_cpvs.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[820px] text-sm">
                    <thead>
                      <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="py-2 pr-3">CPV</th>
                        {dados.companies.map((empresa) => (
                          <th key={`${empresa.country}-${empresa.nif}`} className="py-2 pr-3 text-right">
                            <span className={COR_PAIS[empresa.country]}>{empresa.short}</span>
                            <span className="block max-w-[10rem] truncate font-normal normal-case text-muted-foreground">
                              {empresa.name}
                            </span>
                          </th>
                        ))}
                        <th className="py-2 text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.shared_cpvs.map((item) => (
                        <tr key={item.code} className="border-b border-border/40 align-top">
                          <td className="py-2 pr-3">
                            <p className="font-medium tabular-nums">{item.code}</p>
                            <p className="line-clamp-2 max-w-[24rem] text-xs text-muted-foreground">
                              {item.description || "—"}
                            </p>
                          </td>
                          {dados.companies.map((empresa) => {
                            const parte = item.companies.find(
                              (linha) => linha.short === empresa.short && linha.name === empresa.name,
                            );
                            return (
                              <td
                                key={`${empresa.country}-${empresa.nif}-${item.code}`}
                                className="py-2 pr-3 text-right"
                              >
                                {parte ? (
                                  <>
                                    <span className="block tabular-nums">{num(parte.count)}</span>
                                    <span className="block text-xs text-muted-foreground">
                                      {moneyShort(parte.value)}
                                    </span>
                                  </>
                                ) : (
                                  <span className="text-xs text-muted-foreground/60">—</span>
                                )}
                              </td>
                            );
                          })}
                          <td className="py-2 text-right">
                            <span className="block font-medium tabular-nums">{num(item.contracts)}</span>
                            <span className="block text-xs text-muted-foreground">{moneyShort(item.value)}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Estas empresas não partilham nenhum dos CPV principais. Tente um CPV concreto ou junte empresas do
                  mesmo setor.
                </p>
              )}
            </CardContent>
          </Card>

          {/* ------------------------------------------------ relações + grafo */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Handshake size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">{dados.counterparty_label} em comum</CardTitle>
                <span className="ml-auto text-xs text-muted-foreground">
                  {num(dados.shared_counterparties.length)} entidades
                </span>
              </CardHeader>
              <CardContent className="pt-0">
                {dados.shared_counterparties.length ? (
                  <ul className="max-h-[26rem] space-y-2 overflow-y-auto pr-1">
                    {dados.shared_counterparties.slice(0, 40).map((item) => (
                      <li key={item.nif} className="flex items-start gap-2 text-sm">
                        <BadgeEuro size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate" title={item.name || item.nif}>
                            {item.name || item.nif}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {item.companies.map((empresa) => `${empresa.short} ${num(empresa.count)}`).join(" · ")}
                          </p>
                        </div>
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                          {moneyShort(item.value)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    Sem {dados.counterparty_label.toLowerCase()} em comum entre estas empresas.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Network size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">Como se relacionam</CardTitle>
                <div className="ml-auto flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setModoGrafo("cpv")}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      modoGrafo === "cpv"
                        ? "border-sky-400/40 bg-sky-400/10 text-sky-200"
                        : "border-border text-muted-foreground hover:bg-accent"
                    }`}
                  >
                    CPV comuns
                  </button>
                  <button
                    type="button"
                    onClick={() => setModoGrafo("contrapartes")}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      modoGrafo === "contrapartes"
                        ? "border-sky-400/40 bg-sky-400/10 text-sky-200"
                        : "border-border text-muted-foreground hover:bg-accent"
                    }`}
                  >
                    {dados.counterparty_label}
                  </button>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                {modoGrafo === "cpv" && !dados.shared_cpvs.length ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    Sem CPV comuns para desenhar. O grafo aparece quando as empresas partilham classificações.
                  </p>
                ) : modoGrafo === "contrapartes" && !dados.shared_counterparties.length ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    Sem {dados.counterparty_label.toLowerCase()} em comum para desenhar.
                  </p>
                ) : (
                  <MermaidDiagram code={grafo} height={360} />
                )}
                <p className="mt-2 text-xs text-muted-foreground">
                  Cada ligação é o número de contratos dessa empresa no CPV (ou com aquela contraparte). Os países
                  aparecem pela cor do nó.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* ----------------------------------------------------------- notas */}
          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Scale size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Como ler o cruzamento</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <ul className="list-inside list-disc space-y-1 text-xs text-muted-foreground">
                {dados.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
              {onOpenCountry && dados.shared_cpvs.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="text-xs text-muted-foreground">Aprofundar um CPV num país:</span>
                  {dados.shared_cpvs.slice(0, 4).map((item) => (
                    <span key={item.code} className="flex gap-1">
                      {dados.companies.map((empresa) => (
                        <button
                          key={`${empresa.country}-${item.code}`}
                          type="button"
                          onClick={() => onOpenCountry(empresa.country, item.code || "")}
                          className={`rounded-full border border-border px-2 py-0.5 text-xs transition hover:border-sky-400/40 hover:bg-sky-400/10 ${COR_PAIS[empresa.country]}`}
                        >
                          {empresa.short} {item.code}
                        </button>
                      ))}
                    </span>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
