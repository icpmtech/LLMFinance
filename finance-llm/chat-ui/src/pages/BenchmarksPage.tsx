/**
 * Módulo **Benchmarks de produtos** — índice dos estudos.
 *
 * Cada benchmark é um estudo de preços: o mesmo produto comparado em várias
 * lojas online. Aqui criam-se e gerem-se os estudos (nome, categoria, moeda,
 * chave de comparação e as lojas a recolher); cada um tem o **seu índice** no
 * Elasticsearch (`finance_bench_<slug>`), a sua entrada de menu e pode ser
 * publicado como página no site.
 *
 * A recolha acontece na página do benchmark (`BenchmarkDetailPage`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Globe,
  ExternalLink,
  Loader2,
  Package,
  Plus,
  RefreshCw,
  Scale,
  ScanSearch,
  Store as StoreIcon,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import {
  apagarBenchmark,
  criarBenchmark,
  despublicarBenchmark,
  getBenchmarkModelo,
  getBenchmarksMeta,
  listarBenchmarks,
  publicarBenchmark,
  recolherBenchmark,
  sondarLoja,
  type Benchmark,
  type BenchmarkMeta,
  type BenchmarkPayload,
  type BenchmarkScraper,
  type SondaResultado,
} from "../benchmarksApi";
import { refreshBenchmarkMenu } from "../benchmarkMenu";

type LojaForm = {
  name: string;
  url: string;
  template_id: string;
  scraper?: BenchmarkScraper;
  /** `http` (rápido), `dynamic` (JavaScript) ou `stealth` (sites protegidos). */
  fetcher?: string;
};

const LOJA_VAZIA: LojaForm = { name: "", url: "", template_id: "", fetcher: "http" };

const FETCHERS: { id: string; label: string }[] = [
  { id: "http", label: "Pedido simples" },
  { id: "dynamic", label: "Browser (JavaScript)" },
  { id: "stealth", label: "Browser furtivo" },
];

//: O que a sonda consegue trazer. O `field_map` liga cada linha do benchmark ao
//: nome do campo extraído (é o que faz a comparação de preços funcionar).
const CAMPOS_MAPA: { chave: keyof NonNullable<BenchmarkPayload["field_map"]>; label: string; ajuda: string }[] = [
  { chave: "price", label: "Preço", ajuda: "ex.: preco" },
  { chave: "product_name", label: "Nome do produto", ajuda: "ex.: titulo" },
  { chave: "description", label: "Descrição", ajuda: "ex.: descricao" },
  { chave: "image", label: "Imagem", ajuda: "ex.: imagem" },
  { chave: "url", label: "Endereço", ajuda: "ex.: url" },
  { chave: "price_original", label: "Preço antes", ajuda: "ex.: preco_antigo" },
  { chave: "availability", label: "Disponibilidade", ajuda: "ex.: disponibilidade" },
  { chave: "brand", label: "Marca", ajuda: "ex.: marca" },
  { chave: "ean", label: "EAN/GTIN", ajuda: "ex.: ean" },
];

function num(valor?: number | null, casas = 0): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return valor.toLocaleString("pt-PT", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function eur(valor: number | null | undefined, moeda = "EUR"): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${moeda}`;
}

function dataCurta(iso?: string | null): string {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? "—" : data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

export function BenchmarksPage({ onOpen }: { onOpen?: (slug: string) => void }) {
  const [meta, setMeta] = useState<BenchmarkMeta | null>(null);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [indices, setIndices] = useState<string[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [aTrabalhar, setATrabalhar] = useState("");
  const [criarAberto, setCriarAberto] = useState(false);

  // --- formulário de criação ---
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [categoria, setCategoria] = useState("");
  const [moeda, setMoeda] = useState("EUR");
  const [chave, setChave] = useState("nome");
  const [lojas, setLojas] = useState<LojaForm[]>([{ ...LOJA_VAZIA }]);
  const [mapa, setMapa] = useState<Record<string, string>>({
    price: "preco",
    product_name: "titulo",
    url: "url",
    image: "imagem",
    description: "descricao",
  });
  const [aCarregarModelo, setACarregarModelo] = useState<number | null>(null);
  // --- sonda (análise da página + IA) ---
  const [aSondar, setASondar] = useState<number | null>(null);
  const [sondas, setSondas] = useState<Record<number, SondaResultado | undefined>>({});
  const [sondaIA, setSondaIA] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const [metadados, listagem] = await Promise.all([getBenchmarksMeta(), listarBenchmarks()]);
      setMeta(metadados);
      setBenchmarks(listagem.items ?? []);
      setIndices(listagem.indexes ?? []);
      // A barra lateral tem uma entrada por benchmark: mantém-se em dia.
      void refreshBenchmarkMenu();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao carregar os benchmarks");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const totais = useMemo(() => {
    const ofertas = benchmarks.reduce((soma, b) => soma + (b.stats?.offers ?? 0), 0);
    const produtos = benchmarks.reduce((soma, b) => soma + (b.stats?.products ?? 0), 0);
    const lojas = benchmarks.reduce((soma, b) => soma + (b.stores?.length ?? 0), 0);
    return { ofertas, produtos, lojas, publicos: benchmarks.filter((b) => b.public).length };
  }, [benchmarks]);

  async function usarModelo(indice: number, templateId: string) {
    setLojas((atual) => atual.map((loja, i) => (i === indice ? { ...loja, template_id: templateId } : loja)));
    if (!templateId) return;
    setACarregarModelo(indice);
    try {
      const modelo = await getBenchmarkModelo(templateId);
      setLojas((atual) =>
        atual.map((loja, i) =>
          i === indice
            ? {
                ...loja,
                scraper: modelo.scraper,
                url: loja.url || (modelo.site ? `https://${modelo.site}/` : loja.url),
                name: loja.name || modelo.name || loja.name,
              }
            : loja,
        ),
      );
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao carregar o modelo");
    } finally {
      setACarregarModelo(null);
    }
  }

  /**
   * Sonda uma loja: analisa a página e mostra o que lá encontrou (preço, imagem,
   * descrição) antes de guardar seja o que for. Os seletores só entram na loja
   * quando o utilizador aceitar.
   */
  async function sondar(indice: number) {
    const loja = lojas[indice];
    if (!loja?.url.trim()) {
      setErro("Indique o endereço da página de produtos desta loja antes de sondar.");
      return;
    }
    setASondar(indice);
    setErro("");
    setAviso("");
    setSondas((atual) => ({ ...atual, [indice]: undefined }));
    try {
      const resultado = await sondarLoja({
        url: loja.url.trim(),
        fetcher: loja.fetcher || "http",
        use_ai: sondaIA,
        nome_loja: loja.name.trim(),
        hint: [nome.trim() || categoria.trim(), "preço, imagem e descrição"].filter(Boolean).join(" · "),
      });
      setSondas((atual) => ({ ...atual, [indice]: resultado }));
      if (!resultado.amostra?.length) {
        setErro("A sonda não extraiu nenhum produto. Experimente o «Browser (JavaScript)» ou outro endereço.");
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "A sonda falhou");
    } finally {
      setASondar(null);
    }
  }

  /** Aceita a proposta da sonda: guarda os seletores na loja e completa o mapa. */
  function usarSondagem(indice: number) {
    const sonda = sondas[indice];
    const scraper = sonda?.loja_sugerida?.scraper;
    if (!sonda || !scraper) return;
    setLojas((atual) =>
      atual.map((loja, i) =>
        i === indice
          ? { ...loja, scraper, name: loja.name.trim() || sonda.loja_sugerida?.name || loja.name }
          : loja,
      ),
    );
    const novos = sonda.field_map ?? {};
    setMapa((atual) => {
      const resultado = { ...atual };
      for (const [chave, campo] of Object.entries(novos)) {
        // Só preenche o que está vazio: uma escolha do utilizador não é substituída.
        if (campo && !String(resultado[chave] ?? "").trim()) resultado[chave] = String(campo);
      }
      return resultado;
    });
    setAviso(
      `Seletores de «${sonda.loja_sugerida?.name}» aceites (${sonda.campos?.length ?? 0} campo(s)` +
        (sonda.origem === "ia" ? ", proposta da IA" : ", proposta determinística") +
        "). Ajuste o que precisar e crie o benchmark.",
    );
    setSondas((atual) => ({ ...atual, [indice]: undefined }));
  }

  async function submeter(evento: React.FormEvent) {
    evento.preventDefault();
    setErro("");
    setAviso("");
    const usaveis = lojas.filter((loja) => loja.name.trim() && loja.url.trim());
    if (!nome.trim()) {
      setErro("Indique o nome do benchmark.");
      return;
    }
    if (!usaveis.length) {
      setErro("Indique pelo menos uma loja (nome e endereço).");
      return;
    }
    setATrabalhar("criar");
    try {
      const payload: BenchmarkPayload = {
        name: nome.trim(),
        description: descricao.trim(),
        category: categoria.trim(),
        currency: moeda,
        match_on: chave as BenchmarkPayload["match_on"],
        field_map: Object.fromEntries(Object.entries(mapa).filter(([, valor]) => valor.trim())),
        stores: usaveis.map((loja) => ({
          name: loja.name.trim(),
          url: loja.url.trim(),
          template_id: loja.template_id || undefined,
          scraper: loja.scraper,
          enabled: true,
        })),
      };
      const criado = await criarBenchmark(payload);
      setAviso(`Benchmark «${criado.name}» criado com o índice próprio. Já pode recolher.`);
      setCriarAberto(false);
      setNome("");
      setDescricao("");
      setCategoria("");
      setLojas([{ ...LOJA_VAZIA }]);
      await carregar();
      onOpen?.(criado.slug);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao criar o benchmark");
    } finally {
      setATrabalhar("");
    }
  }

  async function recolher(slug: string) {
    setATrabalhar(`recolher:${slug}`);
    setErro("");
    setAviso("");
    try {
      const resumo = await recolherBenchmark(slug, { limite_por_loja: 300 });
      const lojasOk = (resumo.stores ?? []).filter((loja) => loja.status === "ok").length;
      setAviso(
        `Recolha de «${slug}»: ${num(resumo.offers)} ofertas recolhidas em ${lojasOk} loja(s)` +
          (resumo.errors?.length ? ` · ${resumo.errors.length} erro(s)` : ""),
      );
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro na recolha");
    } finally {
      setATrabalhar("");
    }
  }

  async function publicar(benchmark: Benchmark) {
    setATrabalhar(`publicar:${benchmark.slug}`);
    setErro("");
    setAviso("");
    try {
      if (benchmark.public) {
        await despublicarBenchmark(benchmark.slug);
        setAviso(`«${benchmark.name}» retirado do site.`);
      } else {
        const resultado = await publicarBenchmark(benchmark.slug);
        setAviso(`Publicado em ${resultado.url}.`);
      }
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao publicar");
    } finally {
      setATrabalhar("");
    }
  }

  async function apagar(benchmark: Benchmark) {
    if (!window.confirm(`Apagar «${benchmark.name}» e o índice de ofertas dele?`)) return;
    setATrabalhar(`apagar:${benchmark.slug}`);
    setErro("");
    try {
      await apagarBenchmark(benchmark.slug);
      setAviso(`«${benchmark.name}» apagado.`);
      await carregar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao apagar");
    } finally {
      setATrabalhar("");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold">
            <Scale size={22} className="text-teal-300" />
            Benchmarks de produtos
          </h2>
          <p className="text-sm text-muted-foreground">
            O mesmo produto comparado entre lojas: cada estudo tem o seu índice, a sua entrada e pode ser publicado no site.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" icon={<RefreshCw size={15} />} onClick={() => void carregar()} loading={carregando}>
            Atualizar
          </Button>
          <Button
            icon={criarAberto ? <X size={15} /> : <Plus size={15} />}
            onClick={() => setCriarAberto((aberto) => !aberto)}
          >
            {criarAberto ? "Fechar" : "Novo benchmark"}
          </Button>
        </div>
      </div>

      {erro && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{erro}</div>
      )}
      {aviso && (
        <div className="rounded-xl border border-teal-400/25 bg-teal-400/10 px-4 py-3 text-sm text-teal-100">{aviso}</div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { icon: <Scale size={16} />, label: "Benchmarks", valor: num(benchmarks.length) },
          { icon: <Globe size={16} />, label: "Publicados no site", valor: num(totais.publicos) },
          { icon: <Package size={16} />, label: "Ofertas recolhidas", valor: num(totais.ofertas) },
          { icon: <StoreIcon size={16} />, label: "Lojas em recolha", valor: num(totais.lojas) },
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

      {criarAberto && (
        <Card>
          <CardHeader>
            <CardTitle>Novo benchmark</CardTitle>
            <span className="text-xs text-muted-foreground">
              O índice <span className="font-mono">finance_bench_&lt;slug&gt;</span> é criado logo a seguir.
            </span>
          </CardHeader>
          <CardContent>
            <form className="space-y-5" onSubmit={submeter}>
              <div className="grid gap-3 md:grid-cols-4">
                <div className="md:col-span-2">
                  <Label>Nome do estudo</Label>
                  <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Portáteis 16 GB" />
                </div>
                <div>
                  <Label>Categoria</Label>
                  <Input value={categoria} onChange={(e) => setCategoria(e.target.value)} placeholder="ex.: Informática" />
                </div>
                <div>
                  <Label>Moeda</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={moeda}
                    onChange={(e) => setMoeda(e.target.value)}
                  >
                    {(meta?.currencies ?? ["EUR"]).map((moedaOpcao) => (
                      <option key={moedaOpcao} value={moedaOpcao}>
                        {moedaOpcao}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="md:col-span-3">
                  <Label>Descrição</Label>
                  <Input
                    value={descricao}
                    onChange={(e) => setDescricao(e.target.value)}
                    placeholder="O que está a ser comparado e com que critério"
                  />
                </div>
                <div>
                  <Label>O que é «o mesmo produto»</Label>
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={chave}
                    onChange={(e) => setChave(e.target.value)}
                  >
                    {(meta?.match_keys ?? [{ id: "nome", label: "Nome do produto", hint: "" }]).map((opcao) => (
                      <option key={opcao.id} value={opcao.id}>
                        {opcao.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label>Lojas a comparar</Label>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 accent-teal-400"
                        checked={sondaIA}
                        onChange={(e) => setSondaIA(e.target.checked)}
                      />
                      Sonda com IA
                    </label>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      icon={<Plus size={14} />}
                      onClick={() => setLojas((atual) => [...atual, { ...LOJA_VAZIA }])}
                    >
                      Adicionar loja
                    </Button>
                  </div>
                </div>
                {lojas.map((loja, indice) => (
                  <div key={indice} className="space-y-2 rounded-xl border border-border/60 p-3">
                    <div className="grid gap-2 md:grid-cols-12">
                      <div className="md:col-span-3">
                        <Input
                          value={loja.name}
                          onChange={(e) =>
                            setLojas((atual) => atual.map((l, i) => (i === indice ? { ...l, name: e.target.value } : l)))
                          }
                          placeholder="Nome da loja"
                        />
                      </div>
                      <div className="md:col-span-4">
                        <Input
                          value={loja.url}
                          onChange={(e) =>
                            setLojas((atual) => atual.map((l, i) => (i === indice ? { ...l, url: e.target.value } : l)))
                          }
                          placeholder="https://loja.pt/categoria"
                        />
                      </div>
                      <div className="md:col-span-2">
                        <select
                          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                          value={loja.fetcher ?? "http"}
                          onChange={(e) =>
                            setLojas((atual) =>
                              atual.map((l, i) => (i === indice ? { ...l, fetcher: e.target.value } : l)),
                            )
                          }
                          title="Como descarregar a página: pedido simples, browser com JavaScript ou browser furtivo"
                        >
                          {FETCHERS.map((opcao) => (
                            <option key={opcao.id} value={opcao.id}>
                              {opcao.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="md:col-span-3">
                        <select
                          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                          value={loja.template_id}
                          onChange={(e) => void usarModelo(indice, e.target.value)}
                        >
                          <option value="">Seletores próprios (ou modelo…)</option>
                          {(meta?.templates ?? []).map((modelo) => (
                            <option key={modelo.id} value={modelo.id}>
                              {modelo.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        icon={aSondar === indice ? <Loader2 size={14} className="animate-spin" /> : <ScanSearch size={14} />}
                        onClick={() => void sondar(indice)}
                        disabled={aSondar !== null}
                      >
                        Sonda (IA)
                      </Button>
                      {loja.scraper && (
                        <span className="text-xs text-muted-foreground">
                          Seletores: {loja.scraper.list?.selector || "(sem lista)"} · {(loja.scraper.fields ?? []).length}{" "}
                          campo(s)
                        </span>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="ml-auto"
                        icon={<Trash2 size={14} />}
                        onClick={() => setLojas((atual) => atual.filter((_, i) => i !== indice))}
                        disabled={lojas.length === 1}
                      />
                    </div>
                    {aCarregarModelo === indice && (
                      <p className="text-xs text-muted-foreground">A carregar o modelo de seletores…</p>
                    )}
                    {sondas[indice] && (
                      <SondaPainel
                        sonda={sondas[indice]!}
                        onUsar={() => usarSondagem(indice)}
                        onFechar={() => setSondas((atual) => ({ ...atual, [indice]: undefined }))}
                      />
                    )}
                  </div>
                ))}
              </div>

              <div className="space-y-2">
                <Label>Campos da recolha (opcional)</Label>
                <p className="text-xs text-muted-foreground">
                  Indique o nome do campo extraído que traz cada dado. Em branco, o módulo procura por nomes conhecidos
                  (preço, título, marca…).
                </p>
                <div className="grid gap-2 md:grid-cols-3">
                  {CAMPOS_MAPA.map((campo) => (
                    <div key={campo.chave}>
                      <Label className="text-xs">{campo.label}</Label>
                      <Input
                        value={mapa[campo.chave] ?? ""}
                        onChange={(e) => setMapa((atual) => ({ ...atual, [campo.chave]: e.target.value }))}
                        placeholder={campo.ajuda}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button type="submit" loading={aTrabalhar === "criar"} icon={<Plus size={15} />}>
                  Criar benchmark
                </Button>
                <Button type="button" variant="ghost" onClick={() => setCriarAberto(false)}>
                  Cancelar
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {carregando && !benchmarks.length ? (
        <Card padding="lg">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" /> A carregar benchmarks…
          </p>
        </Card>
      ) : !benchmarks.length ? (
        <Card padding="lg">
          <p className="text-sm text-muted-foreground">
            Ainda não há benchmarks. Crie o primeiro: escolha as lojas, os seletores e o que faz «o mesmo produto».
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {benchmarks.map((benchmark, indice) => (
            <Card key={benchmark.slug}>
              <CardHeader>
                <div>
                  <CardTitle className="flex items-center gap-2">
                    {benchmark.name}
                    {benchmark.public ? <Badge variant="success">no site</Badge> : <Badge variant="outline">privado</Badge>}
                  </CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {benchmark.category || "sem categoria"} · {benchmark.stores?.length ?? 0} loja(s) ·{" "}
                    <span className="font-mono">{indices[indice] ?? `finance_bench_${benchmark.slug}`}</span>
                  </p>
                </div>
                <Badge variant="info">iguais por: {benchmark.match_on ?? "nome"}</Badge>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    { label: "ofertas", valor: num(benchmark.stats?.offers) },
                    { label: "produtos", valor: num(benchmark.stats?.products) },
                    { label: "lojas", valor: num(benchmark.stats?.stores) },
                  ].map((item) => (
                    <div key={item.label} className="rounded-lg border border-border/60 px-2 py-1.5">
                      <p className="text-lg font-semibold">{item.valor}</p>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{item.label}</p>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Última recolha: {dataCurta(benchmark.last_run?.at)} · preço médio{" "}
                  {eur(benchmark.stats?.avg_price, benchmark.currency)}
                  {benchmark.stats?.price_min != null && benchmark.stats?.price_max != null && (
                    <>
                      {" "}· {eur(benchmark.stats.price_min, benchmark.currency)} a{" "}
                      {eur(benchmark.stats.price_max, benchmark.currency)}
                    </>
                  )}
                </p>
                {(benchmark.stats?.stores ?? 0) < 2 && (benchmark.stats?.offers ?? 0) > 0 && (
                  <p className="text-xs text-amber-200">
                    {benchmark.stats?.stores === 0
                      ? "Ainda sem ofertas: use «Recolher»."
                      : "Só uma loja: para comparar preços são precisas duas ou mais."}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" icon={<BarChart3 size={14} />} onClick={() => onOpen?.(benchmark.slug)}>
                    Abrir estudo
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    icon={<RefreshCw size={14} />}
                    loading={aTrabalhar === `recolher:${benchmark.slug}`}
                    onClick={() => void recolher(benchmark.slug)}
                  >
                    Recolher
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    icon={<Upload size={14} />}
                    loading={aTrabalhar === `publicar:${benchmark.slug}`}
                    onClick={() => void publicar(benchmark)}
                  >
                    {benchmark.public ? "Retirar do site" : "Publicar no site"}
                  </Button>
                  {benchmark.public && benchmark.public_path && (
                    <a
                      className="inline-flex items-center gap-1 self-center text-xs text-teal-300 hover:underline"
                      href={`/site/benchmarks/${benchmark.slug}/pesquisa`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={13} /> pesquisa pública
                    </a>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Trash2 size={14} />}
                    loading={aTrabalhar === `apagar:${benchmark.slug}`}
                    onClick={() => void apagar(benchmark)}
                  >
                    Apagar
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * O que a sonda encontrou numa página — mostrado **antes** de se aceitar nada.
 *
 * A amostra é o que decide: se a imagem, o preço e a descrição aparecerem aqui,
 * é o que vai para o benchmark depois de recolher.
 */
function SondaPainel({
  sonda,
  onUsar,
  onFechar,
}: {
  sonda: SondaResultado;
  onUsar: () => void;
  onFechar: () => void;
}) {
  const campos = Object.entries(sonda.campos_detetados ?? {}).filter(([, seletor]) => Boolean(seletor));
  return (
    <div className="space-y-3 rounded-lg border border-teal-400/30 bg-teal-400/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant={sonda.ok ? "success" : "warning"}>
            {sonda.ok ? `${sonda.amostra?.length ?? 0} produto(s) de amostra` : "sem produtos"}
          </Badge>
          {sonda.origem && (
            <span className="rounded-md bg-background/60 px-2 py-0.5 text-muted-foreground">
              {sonda.origem === "ia" ? `IA · ${sonda.ai?.model || sonda.ai?.provider_label || "modelo"}` : "análise determinística"}
            </span>
          )}
          {sonda.bloqueado && (
            <Badge variant="danger">site recusou o pedido{sonda.http_status ? ` (HTTP ${sonda.http_status})` : ""}</Badge>
          )}
          {sonda.robots?.permitido === false && <Badge variant="warning">robots.txt proíbe</Badge>}
          {sonda.robots?.permitido === true && (
            <span className="text-muted-foreground">robots.txt permite</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" onClick={onUsar} disabled={!sonda.loja_sugerida?.scraper}>
            Usar estes seletores
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onFechar}>
            Descartar
          </Button>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Lista: <span className="font-mono">{sonda.loja_sugerida?.scraper?.list?.selector || "(não detetada)"}</span>
        {campos.length > 0 && (
          <>
            {" · "}
            {campos.map(([chave, seletor]) => `${chave}=${seletor}`).join(" · ")}
          </>
        )}
      </p>

      {sonda.notas && <p className="text-xs italic text-muted-foreground">Nota do modelo: {sonda.notas}</p>}
      {(sonda.avisos ?? []).map((aviso) => (
        <p key={aviso} className="text-xs text-amber-200">
          {aviso}
        </p>
      ))}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {(sonda.amostra ?? []).slice(0, 6).map((oferta, indice) => (
          <div key={`${oferta.product_key ?? indice}`} className="flex gap-2 rounded-lg border border-border/50 p-2">
            {oferta.image ? (
              <img
                src={oferta.image}
                alt=""
                className="h-16 w-16 shrink-0 rounded-md object-contain bg-white/5"
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-md border border-dashed border-border/60 text-[10px] text-muted-foreground">
                sem imagem
              </div>
            )}
            <div className="min-w-0 space-y-1">
              <p className="line-clamp-2 text-xs font-medium">{oferta.product_name || "(sem nome)"}</p>
              <p className="text-sm font-semibold text-teal-200">
                {oferta.price !== null && oferta.price !== undefined ? eur(oferta.price, oferta.currency ?? "EUR") : "sem preço"}
              </p>
              {oferta.description ? (
                <p className="line-clamp-2 text-[11px] text-muted-foreground">{oferta.description}</p>
              ) : (
                <p className="text-[11px] text-muted-foreground/70">sem descrição</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default BenchmarksPage;
