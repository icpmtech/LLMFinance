/**
 * Motor alternativo de treino: o CLI do **Soup** (`soup-cli`).
 *
 * O loop incremental da plataforma (`/llm/modelo/retreinar`) treina em CPU com
 * pausa e retoma próprias. O Soup faz o mesmo trabalho de outra forma: um YAML
 * descreve o modelo base, o dataset, o LoRA e a validação, e `soup train`
 * trata do resto (LoRA, quantização, `val_split`). Este painel não reimplementa
 * nada disso — lista os configs de `training/soup/`, valida-os com
 * `soup train --dry-run` e acompanha a corrida que o backend lança.
 *
 * Quando o CLI não está instalado, ou está só a instalação leve (sem o extra
 * `[train]`), o painel diz isso e mostra o comando do contentor que já traz as
 * dependências — é melhor do que um botão que falha sem explicação.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Cpu, Loader2, Play, Square, Terminal } from "lucide-react";
import {
  getEstadoSoup,
  pararSoup,
  treinarComSoup,
  validarConfigSoup,
  type ConfigSoup,
  type EstadoSoup,
} from "../../llmModeloApi";

const formatarData = (valor?: string | null) => {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
};

export default function PainelDoSoup({ className = "" }: { className?: string }) {
  const [estado, setEstado] = useState<EstadoSoup | null>(null);
  const [configs, setConfigs] = useState<ConfigSoup[]>([]);
  const [escolhido, setEscolhido] = useState<string>("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [aviso, setAviso] = useState<{ tipo: "erro" | "ok" | "info"; texto: string } | null>(null);
  // Falha ao **ler** o estado (servidor a reiniciar, 502 do proxy): não é o
  // mesmo que «CLI não instalado», e mostrar essa conclusão seria mentira.
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const montado = useRef(true);

  const recarregar = useCallback(async () => {
    try {
      const resposta = await getEstadoSoup();
      if (!montado.current) return;
      // O Qwen primeiro: é o modelo que o chat e as páginas do modelo usam, e
      // é o único cujos adaptadores aparecem depois no seletor do chat.
      const ordenados = [...resposta.configs].sort((a, b) => {
        const qwen = (c: ConfigSoup) => (c.base ?? "").toLowerCase().includes("qwen");
        if (qwen(a) === qwen(b)) return 0;
        return qwen(a) ? -1 : 1;
      });
      setConfigs(ordenados);
      setEstado(resposta.estado);
      setErroCarga(null);
      setEscolhido((atual) => {
        if (atual && ordenados.some((c) => c.nome === atual)) return atual;
        return ordenados[0]?.nome ?? "";
      });
    } catch (falha) {
      if (!montado.current) return;
      setErroCarga(falha instanceof Error ? falha.message : "não foi possível ler o estado do Soup");
    }
  }, []);

  useEffect(() => {
    montado.current = true;
    void recarregar();
    // Falha transitória (contentor a arrancar) não pode ficar «presa»: tenta
    // outra vez ao voltar à janela e de vez em quando, mesmo parado.
    const aoFocar = () => void recarregar();
    window.addEventListener("focus", aoFocar);
    const timer = window.setInterval(() => void recarregar(), 15000);
    return () => {
      montado.current = false;
      window.removeEventListener("focus", aoFocar);
      window.clearInterval(timer);
    };
  }, [recarregar]);

  const aCorrer = Boolean(estado?.a_correr);
  useEffect(() => {
    if (!aCorrer) return;
    const timer = window.setInterval(() => void recarregar(), 2500);
    return () => window.clearInterval(timer);
  }, [aCorrer, recarregar]);

  const config = configs.find((c) => c.nome === escolhido) ?? null;

  const executar = async (chave: string, acao: () => Promise<string>) => {
    setOcupado(chave);
    setAviso(null);
    try {
      const texto = await acao();
      if (!montado.current) return;
      setAviso({ tipo: "ok", texto });
    } catch (falha) {
      if (!montado.current) return;
      setAviso({ tipo: "erro", texto: falha instanceof Error ? falha.message : "A ação falhou" });
    } finally {
      if (!montado.current) return;
      setOcupado(null);
      void recarregar();
    }
  };

  const validar = () =>
    executar("validar", async () => {
      const r = await validarConfigSoup(escolhido);
      return r.ok ? `Config válido: ${r.mensagem}` : `Config inválido: ${r.mensagem}`;
    });

  const treinar = () =>
    executar("treinar", async () => {
      const r = await treinarComSoup(escolhido, true);
      // O `soup train` pode morrer nos primeiros instantes (falta o extra
      // `[train]`, dataset inválido): relê-se o estado para não anunciar um
      // arranque que já falhou.
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      const depois = await getEstadoSoup();
      if (montado.current) {
        setEstado(depois.estado);
        setConfigs(depois.configs);
      }      if (depois.estado.fase === "erro" && !depois.estado.a_correr) {
        throw new Error(depois.estado.erro || "o Soup terminou com erro ao arrancar");
      }
      return `Treino do Soup lançado com ${r.config}.`;
    });

  const parar = () =>
    executar("parar", async () => {
      const r = await pararSoup();
      return r.ok ? "Corrida do Soup terminada." : r.motivo || "Não havia treino a correr.";
    });

  const comando = estado?.comando_contentor?.replace("{config}", config?.caminho ?? "…") ?? "";
  const progresso = estado?.passos ? Math.min(100, Math.round((estado.passo / estado.passos) * 100)) : 0;

  return (
    <div className={`rounded-2xl border border-border bg-card/40 p-4 ${className}`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        <span className="flex items-center gap-1">
          <Cpu size={12} /> motor Soup (soup-cli)
        </span>
        <span className="flex items-center gap-2 text-[10px] normal-case">
          {erroCarga ? (
            <button
              type="button"
              onClick={() => void recarregar()}
              className="inline-flex items-center gap-1 text-red-400 hover:underline"
              title={erroCarga}
            >
              <AlertTriangle size={11} /> estado indisponível — repetir
            </button>
          ) : !estado ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Loader2 size={11} className="animate-spin" /> a ler…
            </span>
          ) : estado.disponivel ? (
            estado.treino_disponivel ? (
              <span className="inline-flex items-center gap-1 text-primary">
                <CheckCircle2 size={11} /> {estado.versao ?? "soup"} · treino disponível
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-amber-500" title="falta o extra [train]: peft, trl, datasets, accelerate">
                <AlertTriangle size={11} /> {estado.versao ?? "soup"} · só validação
              </span>
            )
          ) : (
            <span className="inline-flex items-center gap-1 text-amber-500">
              <AlertTriangle size={11} /> CLI não instalado
            </span>
          )}
          {aCorrer && (
            <span className="inline-flex items-center gap-1 text-primary">
              <Loader2 size={11} className="animate-spin" /> a treinar
            </span>
          )}
        </span>
      </div>

      <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground">
        Treino de uma só tacada a partir de um YAML (modelo base, dataset, LoRA e validação). O config e o dataset
        vêm de <code className="text-foreground">training/soup/</code>; o resultado fica no <code className="text-foreground">output</code>
        do YAML.
      </p>

      <label className="mb-2 flex flex-col gap-0.5 text-[10px] text-muted-foreground">
        config
        <select
          value={escolhido}
          disabled={aCorrer}
          onChange={(evento) => setEscolhido(evento.target.value)}
          className="rounded-lg border border-border bg-background px-2 py-1 text-[11px] text-foreground outline-none focus:border-primary disabled:opacity-50"
        >
          {configs.length === 0 && (
            <option value="">{erroCarga ? "estado indisponível" : "sem configs em training/soup/"}</option>
          )}
          {configs.map((item) => (
            <option key={item.nome} value={item.nome}>
              {item.nome}
            </option>
          ))}
        </select>
      </label>

      {config && (
        <div className="mb-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[10.5px] text-muted-foreground sm:grid-cols-4">
          <span className="truncate" title={config.base ?? ""}>
            base: <span className="text-foreground">{config.base ?? "—"}</span>
          </span>
          <span>
            pares: <span className="text-foreground">{config.pares ?? "—"}</span>
          </span>
          <span>
            épocas: <span className="text-foreground">{config.epocas ?? "—"}</span> · lr{" "}
            <span className="text-foreground">{config.lr ?? "—"}</span>
          </span>
          <span>
            LoRA r: <span className="text-foreground">{config.lora_r ?? "—"}</span> · quant{" "}
            <span className="text-foreground">{config.quantizacao ?? "—"}</span>
          </span>
          <span className="col-span-2 truncate sm:col-span-4" title={config.dataset ?? ""}>
            dataset: <span className={config.dataset_existe ? "text-foreground" : "text-amber-500"}>{config.dataset ?? "—"}</span>
            {config.dataset_existe ? "" : " (não existe — exporte primeiro)"}
          </span>
          <span className="col-span-2 truncate sm:col-span-4" title={config.saida ?? ""}>
            saída: <span className="text-foreground">{config.saida ?? "—"}</span>
          </span>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => void validar()}
          disabled={!config || ocupado !== null || aCorrer}
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[11px] text-foreground transition hover:bg-muted disabled:opacity-40"
        >
          {ocupado === "validar" ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
          validar config
        </button>
        <button
          type="button"
          onClick={() => void treinar()}
          disabled={
            !config || !config.dataset_existe || !estado?.treino_disponivel || aCorrer || ocupado !== null
          }
          className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-primary/40 bg-primary/10 px-2 py-1.5 text-[11px] font-medium text-primary transition hover:bg-primary/20 disabled:opacity-40"
        >
          {ocupado === "treinar" ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
          treinar com Soup
        </button>
        <button
          type="button"
          onClick={() => void parar()}
          disabled={!aCorrer || ocupado !== null}
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[11px] text-foreground transition hover:bg-muted disabled:opacity-40"
        >
          {ocupado === "parar" ? <Loader2 size={11} className="animate-spin" /> : <Square size={11} />}
          parar
        </button>
      </div>

      {aCorrer && (
        <div className="mt-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progresso}%` }} />
          </div>
          <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-[10px] text-muted-foreground">
            <span>{estado?.fase}</span>
            <span>
              passo {estado?.passo ?? 0}
              {estado?.passos ? `/${estado.passos}` : ""}
            </span>
            <span>perda {typeof estado?.perda === "number" ? estado.perda.toFixed(4) : "—"}</span>
            <span>início {formatarData(estado?.iniciado)}</span>
          </div>
        </div>
      )}

      {!aCorrer && estado?.fase && estado.fase !== "ocioso" && (
        <p className="mt-2 text-[10px] text-muted-foreground">
          última corrida: <span className="text-foreground">{estado.fase}</span>
          {estado.codigo_saida !== null ? ` · código ${estado.codigo_saida}` : ""} · {formatarData(estado.concluido)}
          {estado.config ? ` · ${estado.config}` : ""}
        </p>
      )}

      {estado?.erro && (
        <p className="mt-2 flex items-start gap-1 text-[10px] leading-relaxed text-amber-500">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" /> {estado.erro}
        </p>
      )}

      {erroCarga && (
        <p className="mt-2 flex items-start gap-1 text-[10px] leading-relaxed text-red-400">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" /> {erroCarga}
        </p>
      )}

      {aviso && (
        <p
          className={`mt-2 text-[10px] leading-relaxed ${
            aviso.tipo === "erro" ? "text-red-400" : aviso.tipo === "ok" ? "text-primary" : "text-muted-foreground"
          }`}
        >
          {aviso.texto}
        </p>
      )}

      {!estado?.treino_disponivel && (
        <div className="mt-2 rounded-lg border border-border/60 bg-background/60 p-2">
          <p className="mb-1 flex items-center gap-1 text-[10px] text-muted-foreground">
            <Terminal size={10} />
            {estado?.disponivel
              ? "aqui só se valida configs (falta o extra [train]) — para treinar, no contentor:"
              : "sem CLI nesta máquina — corra no contentor (já traz soup-cli[train]):"}
          </p>
          <code className="block break-all rounded bg-muted px-2 py-1 font-mono text-[10px] text-foreground">
            {comando}
          </code>
          <p className="mt-1 text-[10px] text-muted-foreground">
            Numa máquina onde o treino deva correr directamente:{" "}
            <code className="text-foreground">pip install "soup-cli[train]"</code>.
          </p>
        </div>
      )}

      {(estado?.log?.length ?? 0) > 0 && (
        <details className="mt-2" open={aCorrer}>
          <summary className="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">
            saída do Soup ({estado?.log?.length})
          </summary>
          <ul className="mt-1 max-h-32 space-y-0.5 overflow-y-auto font-mono text-[10px] text-muted-foreground">
            {estado?.log?.slice(-14).map((linha, indice) => (
              <li key={`${indice}-${linha}`} className="truncate" title={linha}>
                › {linha}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
