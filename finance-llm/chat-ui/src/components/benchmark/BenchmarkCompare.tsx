/**
 * **Comparação de empresas** do módulo Benchmark (até `MAX_COMPARE`).
 *
 * O utilizador escolhe o segmento (papel + CPV + anos + região) e junta até 10
 * empresas do sistema. O servidor devolve, para cada uma, os indicadores do
 * segmento — contratos, valor, média, mediana, quota, posição no ranking e o
 * índice de preço face à mediana do mercado — mais o preço de referência do
 * mercado (uma só vez) e o ranking do segmento com as empresas assinaladas.
 */
import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BadgeEuro,
  Building2,
  Grid3X3,
  Handshake,
  Info,
  Scale,
  ShoppingCart,
  Target,
  Trophy,
  Users,
  X,
} from "lucide-react";

import { Button } from "../ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";
import {
  MAX_COMPARE,
  compareBenchmarkEntities,
  type BenchmarkCompareResponse,
  type BenchmarkCountry,
  type BenchmarkMetaAll,
  type BenchmarkRole,
} from "../../benchmarkApi";
import { CpvAutocomplete, EmpresaAutocomplete, SeletorAno, type EmpresaBenchmark } from "./BenchmarkPickers";

const MAX_ANOS = 12;

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

function pct(value?: number | null, digits = 2): string {
  if (value === undefined || value === null) return "—";
  return `${value.toLocaleString("pt-PT", { maximumFractionDigits: digits, minimumFractionDigits: digits })} %`;
}

/** Chave estável de uma empresa (NIF quando existe, senão o nome). */
function chaveEmpresa(empresa: { nif?: string; name: string }): string {
  return empresa.nif ? `nif:${empresa.nif}` : `nome:${empresa.name.toLowerCase()}`;
}
/** Cor da célula do índice de preço (abaixo é bom para quem compra, é critério). */
function corPosicao(posicao?: string | null): string {
  if (posicao === "abaixo") return "text-emerald-300";
  if (posicao === "acima") return "text-amber-300";
  return "text-muted-foreground";
}

/** Segmento efetivamente analisado (o que está nos resultados, não o do formulário). */
type Segmento = {
  role: BenchmarkRole;
  cpv?: string;
  anoDe?: number | "";
  anoAte?: number | "";
  regiao?: string;
};

function descricaoSegmento(segmento: Segmento | null): string {
  if (!segmento) return "";
  const partes: string[] = [segmento.cpv ? `CPV ${segmento.cpv}` : "todo o mercado filtrado"];
  if (segmento.anoDe !== "" && segmento.anoDe !== undefined) {
    partes.push(
      segmento.anoAte !== "" && segmento.anoAte !== undefined && segmento.anoAte !== segmento.anoDe
        ? `${segmento.anoDe}–${segmento.anoAte}`
        : `desde ${segmento.anoDe}`,
    );
  }
  if (segmento.regiao) partes.push(segmento.regiao);
  return partes.join(" · ");
}

export default function BenchmarkCompare({ meta, country }: { meta: BenchmarkMetaAll | null; country: BenchmarkCountry }) {
  const [selecionadas, setSelecionadas] = useState<EmpresaBenchmark[]>([]);
  const [role, setRole] = useState<BenchmarkRole>("adjudicatario");
  const [cpv, setCpv] = useState("");
  const [anoDe, setAnoDe] = useState<number | "">("");
  const [anoAte, setAnoAte] = useState<number | "">("");
  const [regiao, setRegiao] = useState("");
  const [top, setTop] = useState(10);

  const [dados, setDados] = useState<BenchmarkCompareResponse | null>(null);
  const [segmento, setSegmento] = useState<Segmento | null>(null);
  const [aCarregar, setACarregar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const anos = useMemo(() => (meta?.years ?? []).slice(0, MAX_ANOS), [meta]);
  const vender = role === "adjudicatario";
  const cheio = selecionadas.length >= MAX_COMPARE;

  const juntar = useCallback((empresa: EmpresaBenchmark) => {
    setSelecionadas((atuais) => {
      const chave = chaveEmpresa({ nif: empresa.nif, name: empresa.name });
      if (atuais.some((item) => chaveEmpresa({ nif: item.nif, name: item.name }) === chave)) return atuais;
      if (atuais.length >= MAX_COMPARE) return atuais;
      return [...atuais, empresa];
    });
  }, []);

  const remover = (indice: number) => setSelecionadas((atuais) => atuais.filter((_, i) => i !== indice));

  const comparar = useCallback(
    async (override?: { cpv_code?: string }) => {
      if (selecionadas.length < 2) {
        setErro("Escolha pelo menos duas empresas para comparar.");
        return;
      }
      const codigoCpv = override?.cpv_code ?? cpv;
      setACarregar(true);
      setErro(null);
      try {
        const resultado = await compareBenchmarkEntities({
          entities: selecionadas.map((empresa) => ({ nif: empresa.nif || undefined, name: empresa.name })),
          role,
          country,
          cpv_code: codigoCpv || undefined,
          year_from: anoDe === "" ? undefined : Number(anoDe),
          year_to: anoAte === "" ? undefined : Number(anoAte),
          region: regiao.trim() || undefined,
          top,
        });
        setDados(resultado);
        setSegmento({
          role,
          cpv: codigoCpv || undefined,
          anoDe,
          anoAte,
          regiao: regiao.trim() || undefined,
        });
      } catch (err) {
        setDados(null);
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setACarregar(false);
      }
    },
    [selecionadas, role, cpv, anoDe, anoAte, regiao, top, country],
  );

  /** Escolher um CPV a partir do perfil de uma empresa ou dos CPV em comum. */
  const analisarCpv = (codigo: string) => {
    setCpv(codigo);
    void comparar({ cpv_code: codigo });
  };

  const alternarPapel = (proximo: BenchmarkRole) => {
    setRole(proximo);
    if (dados) setDados(null);
  };
  const maxValor = dados ? Math.max(...dados.entities.map((linha) => linha.total_value), 0) : 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Users size={16} /> Empresas a comparar
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              {selecionadas.length}/{MAX_COMPARE}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <EmpresaAutocomplete
              id="benchmark-compare-entidade"
              country={country}
              role={role}
              label="Adicionar empresa"
              placeholder={cheio ? "Limite de 10 empresas atingido" : "Nome, NIF ou SIRET…"}
              onSelect={juntar}
              limparAposEscolher
            />
            <div>
              <Label>Papel comum</Label>
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  onClick={() => alternarPapel("adjudicatario")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    vender ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <BadgeEuro size={15} /> Vendem
                </button>
                <button
                  type="button"
                  onClick={() => alternarPapel("adjudicante")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    !vender ? "border-sky-400/40 bg-sky-400/10 text-sky-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <ShoppingCart size={15} /> Compram
                </button>
              </div>
            </div>
            <CpvAutocomplete id="benchmark-compare-cpv" country={country} value={cpv} onChange={setCpv} />
          </div>

          {selecionadas.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {selecionadas.map((empresa, indice) => (
                <span
                  key={chaveEmpresa({ nif: empresa.nif, name: empresa.name })}
                  className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-white/5 px-3 py-1.5 text-xs"
                >
                  <Building2 size={12} className="shrink-0 text-muted-foreground" />
                  <span className="truncate font-medium">{empresa.name}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {empresa.nif && empresa.nif !== empresa.name ? `${empresa.nif} · ` : ""}
                    {num(empresa.contracts)} contr.
                  </span>
                  <button
                    type="button"
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                    onClick={() => remover(indice)}
                    aria-label={`Remover ${empresa.name}`}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
              <button
                type="button"
                className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent"
                onClick={() => setSelecionadas([])}
              >
                Limpar lista
              </button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Junte 2 a {MAX_COMPARE} empresas (fornecedores ou entidades que compram) para as comparar no mesmo segmento.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <SeletorAno id="benchmark-compare-ano-de" label="Ano de" anos={anos} value={anoDe} onChange={setAnoDe} />
            <SeletorAno id="benchmark-compare-ano-ate" label="Ano até" anos={anos} value={anoAte} onChange={setAnoAte} />
            <div>
              <Label htmlFor="benchmark-compare-regiao">Região / distrito</Label>
              <Input
                id="benchmark-compare-regiao"
                className="mt-1"
                placeholder="ex.: Lisboa, PT11…"
                value={regiao}
                onChange={(e) => setRegiao(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="benchmark-compare-top">Posições no ranking</Label>
              <Input
                id="benchmark-compare-top"
                className="mt-1"
                type="number"
                min={1}
                max={50}
                value={top}
                onChange={(e) => setTop(Math.max(1, Math.min(50, Number(e.target.value) || 10)))}
              />
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                onClick={() => void comparar()}
                disabled={selecionadas.length < 2}
                loading={aCarregar}
                icon={<Scale size={16} />}
              >
                Comparar empresas
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {erro ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">{erro}</span>
        </div>
      ) : null}

      {dados ? (
        <>
          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Scale size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Preço de referência do segmento</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">
                {num(dados.reference.contracts)} contratos · {moneyShort(dados.reference.total_value)}
              </span>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 pt-0 sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">Média do mercado</p>
                <p className="text-sm font-medium tabular-nums">{money(dados.reference.avg)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Mediana do mercado</p>
                <p className="text-sm font-medium tabular-nums">{money(dados.reference.median)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">p25 – p75</p>
                <p className="text-sm font-medium tabular-nums">
                  {moneyShort(dados.reference.p25)} – {moneyShort(dados.reference.p75)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{vender ? "Fornecedores" : "Compradores"} no mercado</p>
                <p className="text-sm font-medium tabular-nums">{num(dados.market.peers)}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Trophy size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Comparação direta</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">{descricaoSegmento(segmento)}</span>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1180px] text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">#</th>
                      <th className="py-2 pr-3">Empresa</th>
                      <th className="py-2 pr-3 text-right">Contratos</th>
                      <th className="py-2 pr-3 text-right">Valor</th>
                      <th className="py-2 pr-3 text-right">Média</th>
                      <th className="py-2 pr-3 text-right">Mediana</th>
                      <th className="py-2 pr-3 text-right">vs mercado</th>
                      <th className="py-2 pr-3 text-right">Posição</th>
                      <th className="py-2 pr-3 text-right">Quota</th>
                      <th className="py-2 pr-3">CPV principais</th>
                      <th className="py-2">{vender ? "Quem compra" : "Quem vende"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dados.entities.map((linha) => (
                      <tr key={chaveEmpresa({ nif: linha.nif ?? undefined, name: linha.name })} className="border-b border-border/40 align-top">
                        <td className="py-2 pr-3 text-xs tabular-nums text-muted-foreground">{linha.order ?? "—"}</td>
                        <td className="py-2 pr-3">
                          <p className="max-w-[18rem] truncate font-medium" title={linha.name}>
                            {linha.name}
                          </p>
                          <div className="mt-1 h-1.5 w-full max-w-[18rem] overflow-hidden rounded-full bg-white/5">
                            <div
                              className="h-full rounded-full bg-sky-400/60"
                              style={{ width: `${maxValor ? Math.max(2, (100 * linha.total_value) / maxValor) : 0}%` }}
                            />
                          </div>
                          {linha.nif ? <p className="mt-0.5 text-xs text-muted-foreground">NIF {linha.nif}</p> : null}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{num(linha.contracts)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{money(linha.total_value)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{money(linha.avg_value)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{money(linha.median_value)}</td>
                        <td className={`py-2 pr-3 text-right tabular-nums ${corPosicao(linha.price_position)}`}>
                          {linha.price_index !== undefined && linha.price_index !== null
                            ? `${linha.price_index.toLocaleString("pt-PT", { maximumFractionDigits: 2 })}× ${linha.price_position ?? ""}`
                            : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{linha.rank ? `${linha.rank}º` : "—"}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pct(linha.share_pct)}</td>
                        <td className="py-2 pr-3">
                          {linha.top_cpv.length === 0 ? (
                            <span className="text-xs text-muted-foreground">—</span>
                          ) : (
                            <div className="flex max-w-[15rem] flex-wrap gap-1">
                              {linha.top_cpv.slice(0, 3).map((cpv) => (
                                <button
                                  key={cpv.code}
                                  type="button"
                                  onClick={() => analisarCpv(cpv.code)}
                                  className={`rounded-full border px-2 py-0.5 text-xs tabular-nums transition hover:bg-accent ${
                                    segmento?.cpv && (cpv.code === segmento.cpv || cpv.code.startsWith(segmento.cpv))
                                      ? "border-sky-400/50 text-sky-200"
                                      : "border-border"
                                  }`}
                                  title={`${cpv.code} ${cpv.description || ""} · ${num(cpv.count)} contratos · ${moneyShort(cpv.value)}\n(clique para analisar este segmento)`}
                                >
                                  {cpv.code} <span className="text-muted-foreground">{num(cpv.count)}</span>
                                </button>
                              ))}
                              {linha.top_cpv.length > 3 ? (
                                <span
                                  className="px-1 text-xs text-muted-foreground"
                                  title={linha.top_cpv.slice(3).map((c) => `${c.code} (${num(c.count)})`).join("\n")}
                                >
                                  +{linha.top_cpv.length - 3}
                                </span>
                              ) : null}
                            </div>
                          )}
                        </td>
                        <td className="py-2">
                          {linha.buyers.length === 0 ? (
                            <span className="text-xs text-muted-foreground">—</span>
                          ) : (
                            <ul className="max-w-[18rem] space-y-0.5 text-xs">
                              {linha.buyers.slice(0, 3).map((comprador) => (
                                <li key={comprador.nif} className="flex items-baseline gap-2">
                                  <span className="min-w-0 flex-1 truncate" title={comprador.name}>
                                    {comprador.name}
                                  </span>
                                  <span className="shrink-0 tabular-nums text-muted-foreground">
                                    {num(comprador.count)} · {moneyShort(comprador.value)}
                                  </span>
                                </li>
                              ))}
                              {linha.buyers_total && linha.buyers_total > linha.buyers.length ? (
                                <li className="text-muted-foreground">
                                  … de {num(linha.buyers_total)} {vender ? "compradores" : "fornecedores"}
                                </li>
                              ) : null}
                            </ul>
                          )}
                        </td>
                      </tr>
                    ))}
                    <tr className="bg-white/5 text-xs text-muted-foreground">
                      <td className="py-2 pr-3">—</td>
                      <td className="py-2 pr-3 font-medium">Mercado (segmento)</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{num(dados.reference.contracts)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{moneyShort(dados.reference.total_value)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(dados.reference.avg)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{money(dados.reference.median)}</td>
                      <td className="py-2 pr-3 text-right">1,00× referência</td>
                      <td className="py-2 pr-3 text-right">—</td>
                      <td className="py-2 pr-3 text-right">100 %</td>
                      <td className="py-2 pr-3">—</td>
                      <td className="py-2">—</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {dados.ranking.length > 0 ? (
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Target size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">Ranking do segmento por valor</CardTitle>
                <span className="ml-auto text-xs text-muted-foreground">as empresas comparadas estão assinaladas</span>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="divide-y divide-border/60">
                  {dados.ranking.map((linha) => (
                    <li
                      key={linha.nif}
                      className={`flex items-baseline gap-3 py-2 ${linha.selected ? "text-emerald-300" : ""}`}
                    >
                      <span className="w-6 shrink-0 text-xs tabular-nums text-muted-foreground">{linha.rank ?? "—"}</span>
                      <span className={`min-w-0 flex-1 truncate text-sm ${linha.selected ? "font-semibold" : ""}`} title={linha.name}>
                        {linha.name}
                      </span>
                      <span className="shrink-0 text-sm font-medium tabular-nums">{moneyShort(linha.value)}</span>
                      <span className="w-28 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                        {num(linha.count)} contr. · {pct(linha.share_pct)}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {dados.shared_buyers.length > 0 ? (
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Handshake size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">
                  {vender ? "Compradores em comum" : "Fornecedores em comum"}
                </CardTitle>
                <span className="ml-auto text-xs text-muted-foreground">
                  contrapartes de duas ou mais empresas comparadas
                </span>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="divide-y divide-border/60">
                  {dados.shared_buyers.map((item) => (
                    <li key={item.nif} className="py-2">
                      <div className="flex items-baseline gap-3">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={item.name}>
                          {item.name}
                        </span>
                        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                          {num(item.companies_total)} empresas
                        </span>
                        <span className="shrink-0 text-sm font-medium tabular-nums">{moneyShort(item.value)}</span>
                      </div>
                      <p className="truncate text-xs text-muted-foreground" title={item.companies.join(" · ")}>
                        {item.companies.join(" · ")}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {dados.shared_cpvs.length > 0 ? (
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Grid3X3 size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">CPV em comum</CardTitle>
                <span className="ml-auto text-xs text-muted-foreground">clique para analisar o segmento</span>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="divide-y divide-border/60">
                  {dados.shared_cpvs.map((item) => (
                    <li key={item.code} className="py-2">
                      <button
                        type="button"
                        className="flex w-full items-baseline gap-3 text-left transition hover:text-foreground"
                        onClick={() => analisarCpv(item.code)}
                        title={`Analisar o segmento ${item.code}`}
                      >
                        <span className="w-28 shrink-0 text-sm font-medium tabular-nums">{item.code}</span>
                        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                          {item.description || "—"}
                        </span>
                        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                          {num(item.companies_total)} empresas
                        </span>
                        <span className="w-28 shrink-0 text-right text-sm font-medium tabular-nums">
                          {moneyShort(item.value)}
                        </span>
                      </button>
                      <p className="truncate pl-28 text-xs text-muted-foreground" title={item.companies.join(" · ")}>
                        {item.companies.join(" · ")}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {dados.notes.length > 0 ? (
            <div className="rounded-xl border border-border/60 bg-white/5 px-3 py-2 text-xs text-muted-foreground">
              <ul className="list-inside list-disc space-y-0.5">
                {dados.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}

      {!dados && !aCarregar ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <VazioComparar />
        </div>
      ) : null}
    </div>
  );
}

/** Estado vazio do modo de comparação. */
function VazioComparar(): ReactNode {
  return (
    <>
      <Users size={30} className="mb-3 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        Escolha duas a {MAX_COMPARE} empresas, defina o segmento (CPV e anos) e compare contratos, valores, preço face ao
        mercado e posição no ranking.
      </p>
    </>
  );
}
