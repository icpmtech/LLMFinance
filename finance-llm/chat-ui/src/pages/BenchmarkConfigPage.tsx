/**
 * **Configuração dos benchmarks de produtos** — as opções do módulo e o catálogo
 * de lojas conhecidas.
 *
 * Aqui decide-se o que a sonda e as recolhas usam por omissão: como descarregar
 * as páginas, se a IA propõe seletores e com que fornecedor/modelo, quantas
 * ofertas trazer por loja e quanto esperar entre lojas. Fica guardado no
 * Elasticsearch (documento `__config__` em `finance_benchmarks`), por isso vale
 * para todos os postos e sobrevive a reinícios.
 *
 * O catálogo de lojas é a memória do que já se mediu: endereço de categoria,
 * fetcher necessário e o estado (a funcionar, sem preço na listagem, bloqueada) —
 * evita repetir o erro de apontar a sonda para um caminho que já não existe.
 */
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  RefreshCw,
  Save,
  ScanSearch,
  Sparkles,
} from "lucide-react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import {
  getBenchmarkConfiguracao,
  guardarBenchmarkConfiguracao,
  listarBenchmarks,
  sondarEstudo,
  type Benchmark,
  type BenchmarkConfiguracao,
  type BenchmarkConfiguracaoResposta,
} from "../benchmarksApi";

const CORES_ESTADO: Record<string, "success" | "warning" | "danger" | "outline"> = {
  ok: "success",
  sem_preco: "warning",
  bloqueado: "danger",
};

export function BenchmarkConfigPage() {
  const [dados, setDados] = useState<BenchmarkConfiguracaoResposta | null>(null);
  const [config, setConfig] = useState<BenchmarkConfiguracao | null>(null);
  const [estudos, setEstudos] = useState<Benchmark[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [aGuardar, setAGuardar] = useState(false);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  // --- sonda rápida a partir do catálogo ---
  const [estudoSonda, setEstudoSonda] = useState("");
  const [aLoja, setALoja] = useState("");
  const [aSondar, setASondar] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const [resposta, listagem] = await Promise.all([getBenchmarkConfiguracao(), listarBenchmarks()]);
      setDados(resposta);
      setConfig(resposta.configuracao);
      setEstudos(listagem.items ?? []);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao carregar a configuração");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  function alterar<K extends keyof BenchmarkConfiguracao>(chave: K, valor: BenchmarkConfiguracao[K]) {
    setConfig((atual) => (atual ? { ...atual, [chave]: valor } : atual));
  }

  async function guardar() {
    if (!config) return;
    setAGuardar(true);
    setErro("");
    setAviso("");
    try {
      const resposta = await guardarBenchmarkConfiguracao(config);
      setConfig(resposta.configuracao);
      setAviso("Configuração guardada. A próxima sonda e as recolhas usam estes valores.");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao guardar");
    } finally {
      setAGuardar(false);
    }
  }

  /** Sonda uma loja do catálogo e guarda os seletores num estudo (num clique). */
  async function sondarNoEstudo(lojaId: string) {
    const loja = (dados?.lojas ?? []).find((l) => l.id === lojaId);
    if (!estudoSonda || !loja) {
      setErro("Escolha o estudo de destino e uma loja do catálogo.");
      return;
    }
    setASondar(true);
    setErro("");
    setAviso("");
    setALoja(lojaId);
    try {
      const resultado = await sondarEstudo(estudoSonda, {
        url: loja.url,
        fetcher: loja.fetcher,
        loja_nome: loja.nome,
        guardar: true,
      });
      const campos = resultado.loja_guardada?.campos?.length ?? 0;
      setAviso(
        resultado.loja_guardada
          ? `«${loja.nome}» guardada no estudo com ${campos} campo(s) e ${resultado.amostra?.length ?? 0} produto(s) de amostra.`
          : `A sonda correu mas não guardou: ${resultado.erro || "sem seletores validados"}.`,
      );
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "A sonda falhou");
    } finally {
      setASondar(false);
      setALoja("");
    }
  }

  const fornecedorAtual = (dados?.fornecedores ?? []).find((f) => f.id === (config?.provider || ""));

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold">
            <ScanSearch size={22} className="text-teal-300" />
            Configuração dos benchmarks
          </h2>
          <p className="text-sm text-muted-foreground">
            O que a sonda e as recolhas usam por omissão, e o catálogo de lojas com o que já se mediu em cada uma.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" icon={<RefreshCw size={15} />} onClick={() => void carregar()} loading={carregando}>
            Atualizar
          </Button>
          <Button icon={<Save size={15} />} onClick={() => void guardar()} loading={aGuardar} disabled={!config}>
            Guardar
          </Button>
        </div>
      </div>

      {erro && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{erro}</div>
      )}
      {aviso && (
        <div className="rounded-xl border border-teal-400/25 bg-teal-400/10 px-4 py-3 text-sm text-teal-100">{aviso}</div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recolha</CardTitle>
            <span className="text-xs text-muted-foreground">
              Aplicado à sonda e a cada recolha (o limite da recolha ainda pode ser mudado ao recolher).
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label>Como descarregar</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.fetcher ?? ""}
                  onChange={(e) => alterar("fetcher", e.target.value)}
                >
                  {(dados?.fetchers ?? []).map((opcao) => (
                    <option key={opcao.id} value={opcao.id}>
                      {opcao.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {(dados?.fetchers ?? []).find((f) => f.id === config?.fetcher)?.hint}
                </p>
              </div>
              <div>
                <Label>Moeda por omissão</Label>
                <Input value={config?.moeda ?? ""} onChange={(e) => alterar("moeda", e.target.value)} maxLength={3} />
                <p className="mt-1 text-[11px] text-muted-foreground">Estudos novos usam esta moeda quando não indicam outra.</p>
              </div>
              <div>
                <Label>Ofertas por loja (limite)</Label>
                <Input
                  type="number"
                  min={1}
                  max={5000}
                  value={config?.limite_por_loja ?? 200}
                  onChange={(e) => alterar("limite_por_loja", Number(e.target.value))}
                />
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Protege contra listagens com paginação infinita. Não guarda mais do que isto por loja.
                </p>
              </div>
              <div>
                <Label>Espera entre lojas (segundos)</Label>
                <Input
                  type="number"
                  min={0}
                  max={60}
                  step={0.5}
                  value={config?.pausa_segundos ?? 2}
                  onChange={(e) => alterar("pausa_segundos", Number(e.target.value))}
                />
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Recolhas seguidas ao mesmo site são a forma mais rápida de apanhar um bloqueio.
                </p>
              </div>
              <div>
                <Label>Categoria por omissão</Label>
                <Input
                  value={config?.categoria_padrao ?? ""}
                  onChange={(e) => alterar("categoria_padrao", e.target.value)}
                  placeholder="ex.: Informática"
                />
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-teal-400"
                    checked={Boolean(config?.respeitar_robots)}
                    onChange={(e) => alterar("respeitar_robots", e.target.checked)}
                  />
                  Respeitar o robots.txt
                </label>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles size={16} className="text-teal-300" />
              Proposta por IA
            </CardTitle>
            <span className="text-xs text-muted-foreground">
              A análise determinística corre sempre; a IA é uma segunda opinião, validada antes de ser mostrada.
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-teal-400"
                checked={Boolean(config?.use_ai)}
                onChange={(e) => alterar("use_ai", e.target.checked)}
              />
              Pedir proposta à IA por omissão
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label>Fornecedor</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.provider ?? ""}
                  onChange={(e) => {
                    alterar("provider", e.target.value);
                    alterar("model", "");
                  }}
                >
                  <option value="">O configurado na plataforma</option>
                  {(dados?.fornecedores ?? []).map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                      {f.tem_chave ? "" : " (sem chave)"}
                      {f.predefinido ? " · predefinido" : ""}
                    </option>
                  ))}
                </select>
                {fornecedorAtual && !fornecedorAtual.tem_chave && (
                  <p className="mt-1 text-[11px] text-amber-200">
                    <AlertTriangle size={11} className="mr-1 inline" />
                    Sem chave configurada — a sonda cai na análise determinística.
                  </p>
                )}
              </div>
              <div>
                <Label>Modelo</Label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={config?.model ?? ""}
                  onChange={(e) => alterar("model", e.target.value)}
                >
                  <option value="">{fornecedorAtual?.default_model || "por omissão do fornecedor"}</option>
                  {(fornecedorAtual?.models ?? []).map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <Label>Contexto enviado à IA</Label>
              <Input
                value={config?.hint ?? ""}
                onChange={(e) => alterar("hint", e.target.value)}
                placeholder="ex.: portáteis, preço com IVA, ignorar acessórios"
              />
            </div>
            <p className="flex items-start gap-2 text-[11px] text-muted-foreground">
              <Info size={13} className="mt-0.5 shrink-0" />
              Um modelo local grande (8B em CPU) pode não responder em 90 s — a sonda mostra a análise determinística e
              diz porquê. Um fornecedor cloud responde em segundos.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScanSearch size={16} className="text-teal-300" />
            Catálogo de lojas
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            Endereços de categoria e o fetcher que cada site exige — com o estado medido, para não se repetir uma
            tentativa que já se sabe falhar.
          </span>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="w-64">
              <Label className="text-xs">Estudo de destino</Label>
              <select
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={estudoSonda}
                onChange={(e) => setEstudoSonda(e.target.value)}
              >
                <option value="">escolher…</option>
                {(estudos ?? []).map((estudo) => (
                  <option key={estudo.slug} value={estudo.slug}>
                    {estudo.name} · {estudo.stores?.length ?? 0} loja(s)
                  </option>
                ))}
              </select>
            </div>
            <p className="text-[11px] text-muted-foreground">
              «Sondar e guardar» valida a página e escreve os seletores nessa loja do estudo escolhido.
            </p>
          </div>

          <div className="grid gap-2 lg:grid-cols-2">
            {(dados?.lojas ?? []).map((loja) => (
              <div key={loja.id} className="flex items-start justify-between gap-3 rounded-lg border border-border/60 p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{loja.nome}</span>
                    <Badge variant={CORES_ESTADO[loja.estado] ?? "outline"}>{loja.estado}</Badge>
                    <span className="text-[11px] text-muted-foreground">fetcher {loja.fetcher}</span>
                  </div>
                  <p className="truncate text-[11px] text-muted-foreground">{loja.url}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{loja.nota}</p>
                </div>
                <Button
                  size="sm"
                  variant={loja.estado === "bloqueado" ? "outline" : "primary"}
                  icon={aSondar && aLoja === loja.id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                  disabled={aSondar || !estudoSonda}
                  onClick={() => void sondarNoEstudo(loja.id)}
                >
                  Sondar e guardar
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default BenchmarkConfigPage;
