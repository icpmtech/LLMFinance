/**
 * Playground do modelo de contratos (`/modelo/playground`).
 *
 * Sítio para experimentar antes de confiar: escrever um **prompt de sistema**,
 * escolher um perfil da plataforma, mexer na temperatura e nos tokens, e ver a
 * resposta com a árvore do raciocínio, a fita de tokens (probabilidades) e a
 * verificação dos números. O prompt pode ser guardado em
 * `finance_llm_prompts` e reutilizado no chat.
 */
import { useEffect, useMemo, useState } from "react";
import { FlaskConical, Loader2, Save, Sparkles, Wand2 } from "lucide-react";
import ChatDoModelo from "../components/modelo/ChatDoModelo";
import { getPrompts, guardarPrompt, type PromptSistema } from "../llmModeloApi";

const EXEMPLO_DADOS = `Entidade: Sónia Maria Pais Pereira Carneiro
NIF: 123456789
País: Portugal
Contratos registados: 6
Como adjudicante: 0 contratos (0,00 €)
Como adjudicatário: 6 contratos
Valor total: 43 534,00 €`;

export default function ModeloPlaygroundPage() {
  const [prompts, setPrompts] = useState<PromptSistema[]>([]);
  const [promptId, setPromptId] = useState("descrever");
  const [sistema, setSistema] = useState("");
  const [temperatura, setTemperatura] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(160);
  const [aGuardar, setAGuardar] = useState(false);
  const [mensagem, setMensagem] = useState<string | null>(null);

  useEffect(() => {
    void getPrompts()
      .then((dados) => {
        setPrompts(dados.prompts);
        const escolhido = dados.prompts.find((p) => p.id === "descrever") ?? dados.prompts[0];
        if (escolhido) {
          setPromptId(escolhido.id);
          setSistema(escolhido.texto);
        }
      })
      .catch(() => setPrompts([]));
  }, []);

  const escolhido = useMemo(() => prompts.find((p) => p.id === promptId), [prompts, promptId]);

  const escolher = (id: string) => {
    const prompt = prompts.find((p) => p.id === id);
    setPromptId(id);
    if (prompt) setSistema(prompt.texto);
  };

  const guardar = async () => {
    if (!sistema.trim()) return;
    setAGuardar(true);
    setMensagem(null);
    try {
      const nome = escolhido ? `${escolhido.nome} (cópia)` : "Prompt do playground";
      const resultado = await guardarPrompt({
        prompt_id: `${promptId || "playground"}-${Date.now().toString(36)}`,
        nome,
        texto: sistema,
      });
      setMensagem(`Prompt guardado como ${resultado.id}.`);
      const actualizados = await getPrompts();
      setPrompts(actualizados.prompts);
    } catch (falha) {
      setMensagem(falha instanceof Error ? falha.message : "Não foi possível guardar");
    } finally {
      setAGuardar(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1180px] space-y-4 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <FlaskConical size={22} className="text-primary" />
            Playground do modelo
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Testar o adaptador de contratos com prompt de sistema, temperatura e contexto controlados. Cada resposta
            mostra a árvore do raciocínio, os pesos por token e a verificação dos números.
          </p>
        </div>
        <span className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
          {sistema.length} caracteres no prompt
        </span>
      </header>

      <section className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div className="rounded-2xl border border-border bg-card/40 p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
              <Wand2 size={14} className="text-primary" /> prompt de sistema
            </span>
            <button
              type="button"
              onClick={() => void guardar()}
              disabled={aGuardar || !sistema.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-[11px] hover:bg-muted disabled:opacity-50"
            >
              {aGuardar ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
              guardar como perfil
            </button>
          </div>
          <textarea
            value={sistema}
            onChange={(e) => setSistema(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-border bg-muted/30 px-3 py-2 text-[12px] leading-relaxed outline-none focus:border-primary"
            placeholder="És um assistente que…"
          />
          {mensagem && <p className="mt-2 text-[11px] text-primary">{mensagem}</p>}
          <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
            O prompt é o primeiro sinal que o modelo vê: entra como mensagem <code>system</code> antes do contexto
            (memória, evidências) e do documento. Perfis guardados ficam em <code>finance_llm_prompts</code> e aparecem
            no chat.
          </p>
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-border bg-card/40 p-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">perfis da plataforma</div>
            <ul className="space-y-1">
              {prompts.map((prompt) => (
                <li key={prompt.id}>
                  <button
                    type="button"
                    onClick={() => escolher(prompt.id)}
                    className={`w-full rounded-lg px-2 py-1.5 text-left text-[11.5px] transition-colors ${
                      prompt.id === promptId ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/50"
                    }`}
                  >
                    {prompt.nome}
                    {prompt.predefinido && <span className="ml-1 text-[9px] uppercase opacity-70">base</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-border bg-card/40 p-4 text-[11px]">
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">parâmetros</div>
            <label className="mb-2 block">
              <span className="flex justify-between text-muted-foreground">
                <span>temperatura</span>
                <span className="text-foreground">{temperatura.toFixed(1)}</span>
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={temperatura}
                onChange={(e) => setTemperatura(Number(e.target.value))}
                className="w-full accent-[#10a37f]"
              />
            </label>
            <label className="block">
              <span className="flex justify-between text-muted-foreground">
                <span>máx. tokens</span>
                <span className="text-foreground">{maxTokens}</span>
              </span>
              <input
                type="range"
                min={32}
                max={400}
                step={16}
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value))}
                className="w-full accent-[#10a37f]"
              />
            </label>
            <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
              Em CPU, cada resposta leva segundos: 160 tokens é ~2-3 frases e o que o treino viu.
            </p>
          </div>

          <div className="rounded-2xl border border-primary/25 bg-primary/5 p-4 text-[10.5px] leading-relaxed text-muted-foreground">
            <div className="mb-1 flex items-center gap-1 text-primary">
              <Sparkles size={12} /> modelo afinado
            </div>
            Qwen2.5-0.5B-Instruct + LoRA r=16 treinado com contratos, entidades e subsídios. Sem GPU, sem servidor de
            inferência: corre no próprio backend.
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-card/40 p-4">
        <ChatDoModelo
          mostrarPainel={false}
          mostrarSeletorPrompt={false}
          sistemaOverride={sistema}
          temperatura={temperatura}
          maxTokens={maxTokens}
          alturaMinima={200}
        />
      </section>

      <p className="pb-2 text-[10.5px] text-muted-foreground">
        Documento de exemplo: {EXEMPLO_DADOS.split("\n")[0]} …
      </p>
    </div>
  );
}
