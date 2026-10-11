/**
 * Módulo **Benchmarks de produtos** — página de um estudo (`/benchmarks/<slug>`).
 *
 * Mostra o resultado da comparação (o mesmo produto entre lojas), as ofertas
 * recolhidas, o ranking das lojas e os KPIs; permite correr a recolha, publicar
 * no site e ver a página pública com pesquisa.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ExternalLink,
  Globe,
  Info,
  Loader2,
  Package,
  RefreshCw,
  Scale,
  Search,
  Store as StoreIcon,
  TrendingDown,
  Upload,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import {
  despublicarBenchmark,
  obterAnalise,
  obterBenchmark,
  obterComparacao,
  obterOfertas,
  publicarBenchmark,
  recolherBenchmark,
  type Benchmark,
  type BenchmarkAnalysis,
  type BenchmarkComparison,
  type BenchmarkOffer,
  type BenchmarkOrdem,
} from "../benchmarksApi";

type Aba = "comparacao" | "ofertas";

function num(valor?: number | null, casas = 0): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return valor.toLocaleString("pt-PT", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function eur(valor: number | null | undefined, moeda = "EUR"): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${moeda}`;
}

function pct(valor?: number | null): string {
  return valor === null || valor === undefined ? "—" : `${valor.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}%`;
}

function dataCurta(iso?: string | null): string {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? "—" : data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

export function BenchmarkDetailPage({ slug, onBack }: { slug: string; onBack?: () => void }) {
  const [benchmark, setBenchmark] = useState<Benchmark | null>(null);
  const [analise, setAnalise] = useState<BenchmarkAnalysis | null>(null);
  const [comparacao, setComparacao] = useState<BenchmarkComparison[]>([]);
  const [ofertas, setOfertas] = useState<BenchmarkOffer[]>([]);
  const [aba, setAba] = useState<Aba>("comparacao");
  const [pesquisa, setPesquisa] = useState("");
  const [loja, setLoja] = useState("");
  const [ordem, setOrdem] = useState<BenchmarkOrdem>("dispersao");
  const [minLojas, setMinLojas] = useState(1);
  const [carregando, setCarregando] = useState(true);
  const [aTrabalhar, setATrabalhar] = useState("");
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [aberto, setAberto] = useState<string | null>(null);

  const carregar = useCallback(
    async (filtros?: { q?: string; loja?: string; ordem?: BenchmarkOrdem; minLojas?: number }) => {
      setErro("");
      try {
        const [definicao, estudo] = await Promise.all([obterBenchmark(slug), obterAnalise(slug)]);
        setBenchmark(definicao);
        setAnalise(estudo);
        const alvo = {
          q: filtros?.q ?? pesquisa,
          loja: filtros?.loja ?? loja,
          ordem: filtros?.ordem ?? ordem,
          minLojas: filtros?.minLojas ?? minLojas,
        };
        const [lista, listaOfertas] = await Promise.all([
          obterComparacao(slug, {
            q: alvo.q || undefined,
            loja: alvo.loja || undefined,
            ordem: alvo.ordem,
            min_lojas: alvo.minLojas,
            size: 80,
          }),
          obterOfertas(slug, { q: alvo.q || undefined, loja: alvo.loja || undefined, size: 80 }),
        ]);
        setComparacao(lista.items ?? []);
        setOfertas(listaOfertas.items ?? []);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao carregar o estudo");
      } finally {
        setCarregando(false);
      }
    },
    [slug, pesquisa, loja, ordem, minLojas],
  );

  useEffect(() => {
    setCarregando(true);
    void carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const moeda = benchmark?.currency ?? "EUR";
  const kpis = analise?.kpis;

  const lojas = useMemo(() => analise?.stores ?? [], [analise]);

  async function recolher() {
    setATrabalhar("recolher");
    setErro("");
    setAviso("");
    try {
      const resumo = await recolherBenchmark(slug, { limite_por_loja: 300 });
      setAviso(
        `Recolha concluída: ${num(resumo.offers)} ofertas` +
          (resumo.errors?.length ? ` · ${resumo.errors.length} erro(s)` : ""),
      );
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro na recolha");
    } finally {
      setATrabalhar("");
    }
  }

  async function alternarPublicacao() {
    setATrabalhar("publicar");
    setErro("");
    setAviso("");
    try {
      if (benchmark?.public) {
        await despublicarBenchmark(slug);
        setAviso("Estudo retirado do site.");
      } else {
        const resultado = await publicarBenchmark(slug);
        setAviso(`Publicado no site: ${resultado.url}`);
      }
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao publicar");
    } finally {
      setATrabalhar("");
    }
  }

  if (carregando) {
    return (
      <Card padding="lg">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" /> A carregar o estudo {slug}…
        </p>
      </Card>
    );
  }

  if (!benchmark) {
    return (
      <Card padding="lg">
        <p className="text-sm text-red-300">{erro || "Benchmark não encontrado."}</p>
        {onBack && (
          <Button className="mt-3" variant="outline" icon={<ArrowLeft size={15} />} onClick={onBack}>
            Voltar
          </Button>
        )}
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            {onBack && (
              <Button size="sm" variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>
                Benchmarks
              </Button>
            )}
            <Badge variant={benchmark.public ? "success" : "outline"}>
              {benchmark.public ? "publicado no site" : "privado"}
            </Badge>
            <Badge variant="info">compara por {benchmark.match_on ?? "nome"}</Badge>
            <span className="font-mono text-xs text-muted-foreground">finance_bench_{benchmark.slug.replace(/-/g, "_")}</span>
          </div>
          <h2 className="mt-1 flex items-center gap-2 text-2xl font-bold">
            <Scale size={22} className="text-teal-300" />
            {benchmark.name}
          </h2>
          <p className="text-sm text-muted-foreground">
            {benchmark.description || "Comparação de preços entre lojas."} · última recolha{" "}
            {dataCurta(benchmark.last_run?.at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" icon={<RefreshCw size={15} />} loading={aTrabalhar === "recolher"} onClick={() => void recolher()}>
            Recolher
          </Button>
          <Button variant="outline" loading={aTrabalhar === "publicar"} icon={<Upload size={15} />} onClick={() => void alternarPublicacao()}>
            {benchmark.public ? "Retirar do site" : "Publicar no site"}
          </Button>
          {benchmark.public && (
            <a
              className="inline-flex items-center gap-1 rounded-xl border border-teal-400/30 px-3 py-2 text-sm text-teal-200 hover:bg-teal-400/10"
              href={`/site/benchmarks/${benchmark.slug}/pesquisa`}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={14} /> Página pública
            </a>
          )}
        </div>
      </div>

      {erro && <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{erro}</div>}
      {aviso && <div className="rounded-xl border border-teal-400/25 bg-teal-400/10 px-4 py-3 text-sm text-teal-100">{aviso}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {[
          { icon: <Package size={16} />, label: "Ofertas", valor: num(kpis?.offers) },
          { icon: <Scale size={16} />, label: "Produtos", valor: num(kpis?.products) },
          { icon: <StoreIcon size={16} />, label: "Lojas com dados", valor: num(kpis?.stores) },
          { icon: <TrendingDown size={16} />, label: "Dispersão média", valor: pct(kpis?.avg_spread_pct) },
          { icon: <Globe size={16} />, label: "Poupança potencial", valor: eur(kpis?.potential_saving_eur, moeda) },
        ].map((kpi) => (
          <Card key={kpi.label} padding="md">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-xs uppercase tracking-wide">{kpi.label}</span>
              {kpi.icon}
            </div>
            <p className="mt-1 text-2xl font-semibold">{kpi.valor}</p>
          </Card>
        ))}
      </div>

      {lojas.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Ranking das lojas</CardTitle>
            <span className="text-xs text-muted-foreground">índice de preço: 100 = média do estudo</span>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Loja</th>
                    <th className="py-2 pr-3 text-right">Ofertas</th>
                    <th className="py-2 pr-3 text-right">Produtos</th>
                    <th className="py-2 pr-3 text-right">Preço médio</th>
                    <th className="py-2 pr-3 text-right">Índice</th>
                  </tr>
                </thead>
                <tbody>
                  {lojas.map((linha) => (
                    <tr key={linha.store_id} className="border-b border-border/40">
                      <td className="py-2 pr-3">{linha.store_name || linha.store_id}</td>
                      <td className="py-2 pr-3 text-right">{num(linha.ofertas)}</td>
                      <td className="py-2 pr-3 text-right">{num(linha.produtos)}</td>
                      <td className="py-2 pr-3 text-right">{eur(linha.preco_medio, moeda)}</td>
                      <td className="py-2 pr-3 text-right">
                        <span className={(linha.indice_preco ?? 100) <= 100 ? "text-emerald-400" : "text-amber-400"}>
                          {linha.indice_preco === null || linha.indice_preco === undefined ? "—" : linha.indice_preco}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant={aba === "comparacao" ? "primary" : "outline"} icon={<Scale size={14} />} onClick={() => setAba("comparacao")}>
              Comparação ({comparacao.length})
            </Button>
            <Button size="sm" variant={aba === "ofertas" ? "primary" : "outline"} icon={<Package size={14} />} onClick={() => setAba("ofertas")}>
              Ofertas ({ofertas.length})
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="md:col-span-2">
              <Label className="text-xs">Produto, marca ou referência</Label>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-3 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={pesquisa}
                  onChange={(e) => setPesquisa(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void carregar()}
                  placeholder="ex.: portátil 16GB"
                />
              </div>
            </div>
            <div>
              <Label className="text-xs">Loja</Label>
              <select
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={loja}
                onChange={(e) => {
                  setLoja(e.target.value);
                  void carregar({ loja: e.target.value });
                }}
              >
                <option value="">todas</option>
                {lojas.map((linha) => (
                  <option key={linha.store_id} value={linha.store_id}>
                    {linha.store_name || linha.store_id}
                  </option>
                ))}
              </select>
            </div>
            <div>
              {aba === "comparacao" ? (
                <>
                  <Label className="text-xs">Ordenar por</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={ordem}
                    onChange={(e) => {
                      const valor = e.target.value as BenchmarkOrdem;
                      setOrdem(valor);
                      void carregar({ ordem: valor });
                    }}
                  >
                    <option value="dispersao">maior dispersão</option>
                    <option value="poupanca">maior poupança</option>
                    <option value="lojas">mais lojas</option>
                    <option value="preco">preço mais baixo</option>
                    <option value="nome">nome</option>
                  </select>
                </>
              ) : (
                <>
                  <Label className="text-xs">Mínimo de lojas</Label>
                  <Input
                    type="number"
                    min={1}
                    value={minLojas}
                    onChange={(e) => setMinLojas(Number(e.target.value) || 1)}
                    onBlur={() => void carregar({ minLojas })}
                  />
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" icon={<Search size={14} />} onClick={() => void carregar()}>
              Procurar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPesquisa("");
                setLoja("");
                setMinLojas(1);
                setOrdem("dispersao");
                void carregar({ q: "", loja: "", minLojas: 1, ordem: "dispersao" });
              }}
            >
              Limpar
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              {benchmark.stores?.length ?? 0} loja(s) configurada(s) · recolha atualiza as ofertas de cada loja
            </span>
          </div>

          {aba === "comparacao" ? (
            comparacao.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="py-2 pr-3">Produto</th>
                      <th className="py-2 pr-3 text-right">Lojas</th>
                      <th className="py-2 pr-3 text-right">Mínimo</th>
                      <th className="py-2 pr-3 text-right">Máximo</th>
                      <th className="py-2 pr-3 text-right">Dispersão</th>
                      <th className="py-2 pr-3">Loja mais barata</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparacao.map((produto) => (
                      <>
                        <tr
                          key={produto.product_key}
                          className="cursor-pointer border-b border-border/40 hover:bg-white/[0.03]"
                          onClick={() => setAberto(aberto === produto.product_key ? null : produto.product_key)}
                        >
                          <td className="py-2 pr-3">
                            <p className="font-medium">{produto.product_name}</p>
                            <p className="text-xs text-muted-foreground">{produto.brand || "sem marca"}</p>
                          </td>
                          <td className="py-2 pr-3 text-right">{num(produto.stores)}</td>
                          <td className="py-2 pr-3 text-right text-emerald-400">{eur(produto.price_min, moeda)}</td>
                          <td className="py-2 pr-3 text-right text-red-300">{eur(produto.price_max, moeda)}</td>
                          <td className="py-2 pr-3 text-right">{pct(produto.spread_pct)}</td>
                          <td className="py-2 pr-3">
                            {produto.best?.url ? (
                              <a
                                className="inline-flex items-center gap-1 text-teal-300 hover:underline"
                                href={produto.best.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {produto.best.store_name || produto.best.store_id} <ExternalLink size={12} />
                              </a>
                            ) : (
                              produto.best?.store_name || "—"
                            )}
                          </td>
                        </tr>
                        {aberto === produto.product_key && (
                          <tr key={`${produto.product_key}:ofertas`} className="border-b border-border/40 bg-white/[0.02]">
                            <td colSpan={6} className="py-2">
                              <div className="grid gap-1.5">
                                {produto.all_offers?.map((oferta, indice) => (
                                  <div key={`${oferta.store_id}-${indice}`} className="flex items-center justify-between gap-3 text-xs">
                                    <span className="text-muted-foreground">{oferta.store_name || oferta.store_id}</span>
                                    <span className={indice === 0 ? "text-emerald-400" : ""}>{eur(oferta.price, moeda)}</span>
                                    {oferta.url && (
                                      <a className="text-teal-300 hover:underline" href={oferta.url} target="_blank" rel="noreferrer">
                                        abrir
                                      </a>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Info size={15} /> Sem produtos para estes filtros. Corra a recolha ou baixe o mínimo de lojas.
              </p>
            )
          ) : ofertas.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3">Produto</th>
                    <th className="py-2 pr-3">Loja</th>
                    <th className="py-2 pr-3 text-right">Preço</th>
                    <th className="py-2 pr-3 text-right">Antes</th>
                    <th className="py-2 pr-3">Disponibilidade</th>
                    <th className="py-2 pr-3">Recolhido</th>
                  </tr>
                </thead>
                <tbody>
                  {ofertas.map((oferta, indice) => (
                    <tr key={oferta._id ?? `${oferta.store_id}-${indice}`} className="border-b border-border/40">
                      <td className="py-2 pr-3">
                        {oferta.url ? (
                          <a className="hover:underline" href={oferta.url} target="_blank" rel="noreferrer">
                            {oferta.product_name}
                          </a>
                        ) : (
                          oferta.product_name
                        )}
                      </td>
                      <td className="py-2 pr-3 text-muted-foreground">{oferta.store_name || oferta.store_id}</td>
                      <td className="py-2 pr-3 text-right">{eur(oferta.price, oferta.currency ?? moeda)}</td>
                      <td className="py-2 pr-3 text-right text-muted-foreground">
                        {oferta.price_original ? eur(oferta.price_original, oferta.currency ?? moeda) : "—"}
                      </td>
                      <td className="py-2 pr-3">
                        {oferta.availability ? (
                          <Badge variant={oferta.in_stock === false ? "danger" : "outline"}>{oferta.availability}</Badge>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted-foreground">{dataCurta(oferta.collected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Info size={15} /> Ainda não há ofertas neste benchmark. Use «Recolher» para ir buscar os preços às lojas.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default BenchmarkDetailPage;
