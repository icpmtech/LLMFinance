/**
 * **Sonda de lojas** — a página onde se descobre como recolher uma página.
 *
 * O percurso é o de quem está a montar um estudo: cola-se o endereço de uma
 * categoria (ou escolhe-se uma loja do catálogo), escolhe-se como descarregar
 * (pedido simples, Chromium ou browser furtivo) e se a IA deve afinar os
 * seletores. A sonda devolve o que **encontrou**: a lista, o mapa de campos e
 * uma amostra real com foto, preço e descrição — antes de guardar seja o que for.
 *
 * No fim, o resultado pode ir para um estudo (existente ou novo), que é o que
 * liga a sonda à recolha.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  ImageOff,
  Loader2,
  Plus,
  RefreshCw,
  ScanSearch,
  Sparkles,
  Store as StoreIcon,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import {
  criarBenchmark,
  getBenchmarkConfiguracao,
  listarBenchmarks,
  sondarEstudo,
  sondarLoja,
  type Benchmark,
  type BenchmarkConfiguracaoResposta,
  type SondaResultado,
} from "../benchmarksApi";
import { refreshBenchmarkMenu } from "../benchmarkMenu";

function eur(valor?: number | null, moeda = "EUR"): string {
  if (valor === null || valor === undefined) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${moeda}`;
}

const CORES_ESTADO: Record<string, "success" | "warning" | "danger" | "outline"> = {
  ok: "success",
  sem_preco: "warning",
  bloqueado: "danger",
};

export function BenchmarkSondaPage({ onAbrirEstudo }: { onAbrirEstudo?: (slug: string) => void }) {
  const [config, setConfig] = useState<BenchmarkConfiguracaoResposta | null>(null);
  const [estudos, setEstudos] = useState<Benchmark[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");

  // --- formulário da sonda ---
  const [url, setUrl] = useState("");
  const [nomeLoja, setNomeLoja] = useState("");
  const [fetcher, setFetcher] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [hint, setHint] = useState("");
  const [destino, setDestino] = useState("");
  const [novoEstudoNome, setNovoEstudoNome] = useState("");

  const [aSondar, setASondar] = useState(false);
  const [resultado, setResultado] = useState<SondaResultado | null>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const [configuracao, listagem] = await Promise.all([getBenchmarkConfiguracao(), listarBenchmarks()]);
      setConfig(configuracao);
      setEstudos(listagem.items ?? []);
      setFetcher((atual) => atual || configuracao.configuracao.fetcher);
      setUseAi(configuracao.configuracao.use_ai);
      setHint((atual) => atual || configuracao.configuracao.hint);
      setProvider(configuracao.configuracao.provider || "");
      setModel(configuracao.configuracao.model || "");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao carregar a configuração");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const fornecedorAtual = useMemo(
    () => (config?.fornecedores ?? []).find((f) => f.id === provider) ?? null,
    [config, provider],
  );

  async function sondar() {
    if (!url.trim()) {
      setErro("Indique o endereço da página de produtos.");
      return;
    }
    setASondar(true);
    setErro("");
    setAviso("");
    setResultado(null);
    try {
      const comum = {
        url: url.trim(),
        fetcher: fetcher || undefined,
        hint: hint.trim() || undefined,
        use_ai: useAi,
        provider: provider || undefined,
        model: model || undefined,
        loja_nome: nomeLoja.trim() || undefined,
      };
      const resposta = destino
        ? await sondarEstudo(destino, { ...comum, guardar: true })
        : await sondarLoja(comum);
      setResultado(resposta);
      if (resposta.loja_guardada) {
        setAviso(
          `«${resposta.loja_guardada.name}» guardada no estudo com ${resposta.loja_guardada.campos.length} campo(s). ` +
            "Já pode recolher.",
        );
        void refreshBenchmarkMenu();
      } else if (!resposta.ok && !resposta.amostra?.length) {
        setErro(resposta.erro || "A sonda não extraiu produtos desta página.");
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "A sonda falhou");
    } finally {
      setASondar(false);
    }
  }

  /** Cria um estudo novo já com a loja sondada (nome da loja + seletores). */
  async function criarEstudoComSonda() {
    const proposta = resultado?.loja_sugerida;
    if (!proposta?.scraper) {
      setErro("Sonde uma página antes de criar o estudo.");
      return;
    }
    if (!novoEstudoNome.trim()) {
      setErro("Indique o nome do estudo novo.");
      return;
    }
    setASondar(true);
    setErro("");
    try {
      const criado = await criarBenchmark({
        name: novoEstudoNome.trim(),
        description: `Estudo criado a partir da sonda de ${proposta.name || url}.`,
        category: config?.configuracao.categoria_padrao || "",
        currency: config?.configuracao.moeda || "EUR",
        match_on: "nome",
        field_map: (resultado?.field_map ?? {}) as Record<string, string>,
        stores: [{ name: proposta.name || nomeLoja || url, url: url.trim(), enabled: true, scraper: proposta.scraper }],
      });
      setAviso(`Estudo «${criado.name}» criado com a loja sondada.`);
      setDestino(criado.slug);
      setNovoEstudoNome("");
      await carregar();
      void refreshBenchmarkMenu();
      onAbrirEstudo?.(criado.slug);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao criar o estudo");
    } finally {
      setASondar(false);
    }
  }

  function usarLojaConhecida(loja: { nome: string; url: string; fetcher: string }) {
    setNomeLoja(loja.nome);
    setUrl(loja.url);
    setFetcher(loja.fetcher);
    setResultado(null);
    setAviso(`Loja «${loja.nome}» carregada (fetcher ${loja.fetcher}). Carregue em «Sondar».`);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold">
            <ScanSearch size={22} className="text-teal-300" />
            Sonda de lojas
          </h2>
          <p className="text-sm text-muted-foreground">
            Descobre como recolher uma página: lista de produtos, preço, imagem e descrição — com IA opcional. O
            resultado guardado num estudo passa a ser o que a recolha usa.
          </p>
        </div>
        <Button variant="outline" icon={<RefreshCw size={15} />} onClick={() => void carregar()} loading={carregando}>
          Atualizar
        </Button>
      </div>

      {erro && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{erro}</div>
      )}
      {aviso && (
        <div className="rounded-xl border border-teal-400/25 bg-teal-400/10 px-4 py-3 text-sm text-teal-100">{aviso}</div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Sondar uma página</CardTitle>
            <span className="text-xs text-muted-foreground">
              Sem indicação em contrário usa a configuração do módulo (fetcher {config?.configuracao.fetcher ?? "—"}).
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-6">
              <div className="md:col-span-4">
                <Label>Endereço da categoria</Label>
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.loja.pt/categoria/produtos"
                  autoComplete="off"
                />
              </div>
              <div className="md:col-span-2">
                <Label>Nome da loja</Label>
                <Input
                  value={nomeLoja}
                  onChange={(e) => setNomeLoja(e.target.value)}
                  placeholder="ex.: Worten"
                  autoComplete="off"
                />
              </div>
              <div className="md:col-span-2">
                <Label>Como descarregar</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={fetcher}
                  onChange={(e) => setFetcher(e.target.value)}
                >
                  {(config?.fetchers ?? []).map((opcao) => (
                    <option key={opcao.id} value={opcao.id}>
                      {opcao.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <Label>Fornecedor de IA</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value);
                    setModel("");
                  }}
                >
                  <option value="">O configurado na plataforma</option>
                  {(config?.fornecedores ?? []).map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                      {f.tem_chave ? "" : " (sem chave)"}
                      {f.predefinido ? " · predefinido" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <Label>Modelo</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                >
                  <option value="">{fornecedorAtual?.default_model || "modelo por omissão"}</option>
                  {(fornecedorAtual?.models ?? []).map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-4">
                <Label>Contexto para a IA (opcional)</Label>
                <Input
                  value={hint}
                  onChange={(e) => setHint(e.target.value)}
                  placeholder="ex.: portáteis, preço com IVA"
                  autoComplete="off"
                />
              </div>
              <div className="md:col-span-2 flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-teal-400"
                    checked={useAi}
                    onChange={(e) => setUseAi(e.target.checked)}
                  />
                  <Sparkles size={14} className="text-teal-300" />
                  Pedir proposta à IA
                </label>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <div className="md:col-span-2">
                <Label>Guardar em</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={destino}
                  onChange={(e) => setDestino(e.target.value)}
                >
                  <option value="">Só ver (não guardar)</option>
                  {estudos.map((estudo) => (
                    <option key={estudo.slug} value={estudo.slug}>
                      {estudo.name} · {estudo.stores?.length ?? 0} loja(s)
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-end gap-2">
                <Button
                  icon={aSondar ? <Loader2 size={15} className="animate-spin" /> : <ScanSearch size={15} />}
                  onClick={() => void sondar()}
                  disabled={aSondar}
                >
                  Sondar
                </Button>
                <Button
                  variant="outline"
                  icon={<Plus size={15} />}
                  onClick={() => void criarEstudoComSonda()}
                  disabled={aSondar || !resultado?.loja_sugerida?.scraper}
                >
                  Criar estudo
                </Button>
              </div>
            </div>
            {destino && (
              <p className="text-xs text-muted-foreground">
                Com um estudo escolhido, os seletores validados são **guardados na loja** (criada ou substituída) e a
                recolha seguinte já os usa.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Lojas conhecidas</CardTitle>
            <span className="text-xs text-muted-foreground">
              {config?.lojas_resumo
                ? `${config.lojas_resumo.total} endereços · ${Object.entries(config.lojas_resumo.por_estado)
                    .map(([estado, total]) => `${total} ${estado}`)
                    .join(" · ")}`
                : "a carregar…"}
            </span>
          </CardHeader>
          <CardContent className="space-y-2">
            {(config?.lojas ?? []).map((loja) => (
              <div key={loja.id} className="rounded-lg border border-border/60 p-2">
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    className="text-left text-sm font-medium hover:underline"
                    onClick={() => usarLojaConhecida(loja)}
                  >
                    {loja.nome}
                  </button>
                  <Badge variant={CORES_ESTADO[loja.estado] ?? "outline"}>{loja.estado}</Badge>
                </div>
                <p className="truncate text-[11px] text-muted-foreground">{loja.url}</p>
                <p className="mt-1 text-[11px] text-muted-foreground">{loja.nota}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {resultado && (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              Resultado
              <Badge variant={resultado.ok ? "success" : "warning"}>
                {resultado.amostra?.length ?? 0} produto(s) de amostra
              </Badge>
              {resultado.origem && (
                <Badge variant="info">
                  {resultado.origem === "ia" ? `IA · ${resultado.ai?.model || resultado.ai?.provider_label || "modelo"}` : "análise determinística"}
                </Badge>
              )}
              {resultado.bloqueado && <Badge variant="danger">site recusou o pedido (HTTP {resultado.http_status})</Badge>}
              {resultado.robots?.permitido === false && <Badge variant="warning">robots.txt proíbe</Badge>}
            </CardTitle>
            <span className="text-xs text-muted-foreground">
              Lista: <span className="font-mono">{resultado.loja_sugerida?.scraper?.list?.selector || "(não detetada)"}</span>
              {resultado.loja_guardada ? ` · guardada em «${resultado.loja_guardada.name}»` : ""}
            </span>
          </CardHeader>
          <CardContent className="space-y-3">
            {(resultado.avisos ?? []).map((item) => (
              <p key={item} className="flex items-start gap-2 text-xs text-amber-200">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {item}
              </p>
            ))}
            {resultado.notas && <p className="text-xs italic text-muted-foreground">Nota do modelo: {resultado.notas}</p>}

            {(resultado.campos ?? []).length > 0 && (
              <div className="flex flex-wrap gap-1 text-[11px]">
                {(resultado.campos ?? []).map((campo) => (
                  <span key={campo} className="rounded-md bg-white/5 px-2 py-0.5 font-mono">
                    {campo}: {resultado.campos_detetados?.[campo] ?? "—"}
                  </span>
                ))}
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(resultado.amostra ?? []).map((oferta, indice) => (
                <div key={`${oferta.product_key ?? indice}`} className="flex gap-3 rounded-xl border border-border/60 p-3">
                  {oferta.image ? (
                    <img
                      src={oferta.image}
                      alt=""
                      className="h-20 w-20 shrink-0 rounded-lg bg-white/5 object-contain"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg border border-dashed border-border/60 text-muted-foreground">
                      <ImageOff size={18} />
                    </div>
                  )}
                  <div className="min-w-0 space-y-1">
                    <p className="line-clamp-2 text-sm font-medium">{oferta.product_name || "(sem nome)"}</p>
                    <p className="text-base font-semibold text-teal-200">
                      {eur(oferta.price, oferta.currency ?? config?.configuracao.moeda ?? "EUR")}
                    </p>
                    {oferta.description && (
                      <p className="line-clamp-2 text-xs text-muted-foreground">{oferta.description}</p>
                    )}
                    {oferta.url && (
                      <a
                        className="inline-flex items-center gap-1 text-[11px] text-teal-300 hover:underline"
                        href={oferta.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ExternalLink size={11} /> ver na loja
                      </a>
                    )}
                  </div>
                </div>
              ))}
              {!resultado.amostra?.length && (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <AlertTriangle size={15} />
                  {resultado.erro || "Sem ofertas de amostra."}
                </p>
              )}
            </div>

            {resultado.loja_sugerida?.scraper && (
              <div className="space-y-2 rounded-xl border border-border/60 p-3">
                <p className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 size={15} className="text-emerald-400" />
                  Definição validada — pode entrar num estudo
                </p>
                <p className="text-xs text-muted-foreground">
                  {resultado.loja_sugerida.scraper.fields?.length ?? 0} campo(s) · fetcher{" "}
                  {resultado.loja_sugerida.scraper.fetcher} · mapa{" "}
                  {JSON.stringify(resultado.field_map ?? {})}
                </p>
                <div className="flex flex-wrap items-end gap-2">
                  <div className="w-64">
                    <Label className="text-xs">Nome do estudo novo</Label>
                    <Input
                      value={novoEstudoNome}
                      onChange={(e) => setNovoEstudoNome(e.target.value)}
                      placeholder="ex.: Portáteis (lojas)"
                      autoComplete="off"
                    />
                  </div>
                  <Button variant="outline" icon={<StoreIcon size={15} />} onClick={() => void criarEstudoComSonda()}>
                    Criar estudo com esta loja
                  </Button>
                  {destino && (
                    <Button variant="ghost" onClick={() => onAbrirEstudo?.(destino)}>
                      Abrir o estudo
                    </Button>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default BenchmarkSondaPage;
