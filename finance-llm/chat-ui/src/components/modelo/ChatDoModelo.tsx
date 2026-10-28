/**
 * Chat do modelo: conversa com memória, skills, RAG e raciocínio à vista.
 *
 * - O **prompt de sistema** vem dos perfis guardados (ou é escrito à mão).
 * - Cada resposta traz a **árvore do raciocínio** (skills que correram, memórias
 *   recuperadas, evidências do RAG, verificação dos números) e a fita de tokens.
 * - Um 👍/👎 (com correção opcional) vai para `finance_llm_feedback`; com 3
 *   correções, o botão **retreinar** dá passos de LoRA em cima do adaptador —
 *   é a auto-aprendizagem, com backup e medição da perda antes/depois.
 * - Uma resposta boa pode ser gravada como **skill** (`finance_llm_memoria`):
 *   passa a entrar no prompt das respostas seguintes e nos pares de treino.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Brain,
  CheckCheck,
  Database,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  ToggleLeft,
  Wrench,
} from "lucide-react";
import ArvoreDoRaciocinio from "./ArvoreDoRaciocinio";
import {
  enviarFeedback,
  getEstadoFeedback,
  getEstadoRetreino,
  getPrompts,
  getSkills,
  guardarMemoria,
  listarMemorias,
  pedirRetreino,
  perguntarAoModelo,
  type EstadoFeedback,
  type EstadoRetreino,
  type ItemMemoria,
  type PromptSistema,
  type RespostaModelo,
  type SkillExecutavel,
} from "../../llmModeloApi";

const DADOS_EXEMPLO = `Contrato 772453 - limpeza e desobstrução de coletores
Adjudicante: Município de Condeixa-a-Nova
Adjudicatário: OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS
Tipo: Aquisição de serviços
Procedimento: Ajuste Direto Regime Geral
Preço contratual: 20806.2`;

type Mensagem = {
  id: number;
  papel: "utilizador" | "modelo";
  texto: string;
  resposta?: RespostaModelo;
  instrucao?: string;
  dados?: string;
  avaliada?: "boa" | "ma";
};

export default function ChatDoModelo({
  mostrarPainel = true,
  alturaMinima = 260,
  sistemaOverride = null,
  mostrarSeletorPrompt = true,
  maxTokens = 160,
  temperatura = 0.2,
}: {
  mostrarPainel?: boolean;
  alturaMinima?: number;
  /** Prompt de sistema escrito à mão (playground) — ganha ao `prompt_id`. */
  sistemaOverride?: string | null;
  mostrarSeletorPrompt?: boolean;
  maxTokens?: number;
  temperatura?: number;
}) {
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [instrucao, setInstrucao] = useState("Descreve este contrato público português.");
  const [dados, setDados] = useState(DADOS_EXEMPLO);
  const [aEnviar, setAEnviar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<PromptSistema[]>([]);
  const [promptId, setPromptId] = useState<string>("descrever");
  const [skills, setSkills] = useState<SkillExecutavel[]>([]);
  const [memorias, setMemorias] = useState<ItemMemoria[]>([]);
  const [feedback, setFeedback] = useState<EstadoFeedback | null>(null);
  const [retreino, setRetreino] = useState<EstadoRetreino | null>(null);
  const [raf, setRaf] = useState({ rag: true, memoria: true, skills: true, raciocinio: true });
  const [correcao, setCorrecao] = useState<Record<number, string>>({});
  const [novaMemoria, setNovaMemoria] = useState({ titulo: "", instrucao: "", resposta: "", tipo: "skill" as "skill" | "memoria" });

  const carregarPainel = useCallback(async () => {
    const [listaPrompts, listaSkills, listaMemorias, estadoFeedback, estadoRetreino] = await Promise.all([
      getPrompts().catch(() => ({ prompts: [], total: 0 })),
      getSkills().catch(() => ({ skills: [], total: 0 })),
      listarMemorias().catch(() => ({ itens: [], total: 0 })),
      getEstadoFeedback().catch(() => null),
      getEstadoRetreino().catch(() => null),
    ]);
    setPrompts(listaPrompts.prompts);
    setSkills(listaSkills.skills);
    setMemorias(listaMemorias.itens);
    setFeedback(estadoFeedback);
    setRetreino(estadoRetreino);
  }, []);

  useEffect(() => {
    void carregarPainel();
  }, [carregarPainel]);

  const enviar = async () => {
    if (!instrucao.trim() || aEnviar) return;
    setAEnviar(true);
    setErro(null);
    const textoUtilizador = instrucao.trim();
    setMensagens((antes) => [...antes, { id: Date.now(), papel: "utilizador", texto: textoUtilizador }]);
    try {
      const resposta = await perguntarAoModelo({
        instrucao: textoUtilizador,
        dados,
        prompt_id: sistemaOverride ? null : promptId || null,
        sistema: sistemaOverride || null,
        usar_rag: raf.rag,
        usar_memoria: raf.memoria,
        usar_skills: raf.skills,
        raciocinio: raf.raciocinio,
        max_tokens: maxTokens,
        temperatura,
      });
      setMensagens((antes) => [
        ...antes,
        {
          id: Date.now() + 1,
          papel: "modelo",
          texto: resposta.resposta,
          resposta,
          instrucao: textoUtilizador,
          dados,
        },
      ]);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "O modelo não respondeu");
    } finally {
      setAEnviar(false);
    }
  };

  const avaliar = async (mensagem: Mensagem, nota: number) => {
    if (!mensagem.resposta || !mensagem.instrucao) return;
    const correcaoTexto = (correcao[mensagem.id] ?? "").trim();
    try {
      const resultado = await enviarFeedback({
        instrucao: mensagem.instrucao,
        dados: mensagem.dados ?? "",
        resposta: mensagem.texto,
        correcao: nota < 0 ? correcaoTexto : "",
        nota,
        skills: mensagem.resposta.skills,
        usou_rag: raf.rag,
        raciocinio: raf.raciocinio,
      });
      setMensagens((antes) =>
        antes.map((m) => (m.id === mensagem.id ? { ...m, avaliada: nota > 0 ? "boa" : "ma" } : m)),
      );
      setFeedback((antes) => (antes ? { ...antes, total: antes.total + 1 } : antes));
      if (resultado.pares_de_treino) {
        setFeedback((antes) => (antes ? { ...antes, por_utilizar: resultado.pares_de_treino } : antes));
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Feedback não guardado");
    }
  };

  const guardarComoSkill = async (mensagem: Mensagem) => {
    if (!mensagem.instrucao) return;
    try {
      await guardarMemoria({
        tipo: "skill",
        titulo: mensagem.instrucao.slice(0, 120),
        instrucao: mensagem.instrucao,
        dados: mensagem.dados ?? "",
        resposta: mensagem.texto,
        gatilhos: mensagem.instrucao.toLowerCase().split(/\s+/).filter((p) => p.length > 4).slice(0, 6),
      });
      await carregarPainel();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Skill não guardada");
    }
  };

  const criarMemoria = async () => {
    if (!novaMemoria.titulo.trim()) return;
    try {
      await guardarMemoria({
        tipo: novaMemoria.tipo,
        titulo: novaMemoria.titulo,
        instrucao: novaMemoria.instrucao,
        resposta: novaMemoria.resposta,
        gatilhos: novaMemoria.titulo.toLowerCase().split(/\s+/).filter((p) => p.length > 4).slice(0, 6),
      });
      setNovaMemoria({ titulo: "", instrucao: "", resposta: "", tipo: novaMemoria.tipo });
      await carregarPainel();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Memória não guardada");
    }
  };

  const retreinar = async () => {
    try {
      await pedirRetreino({ passos: 12 });
      setRetreino((antes) => (antes ? { ...antes, a_correr: true, passo: 0, passos: 12 } : antes));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível retreinar");
    }
  };

  useEffect(() => {
    if (!retreino?.a_correr) return;
    const timer = window.setInterval(async () => {
      const estado = await getEstadoRetreino().catch(() => null);
      if (estado) setRetreino(estado);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [retreino?.a_correr]);

  const alternar = (chave: keyof typeof raf) => setRaf((antes) => ({ ...antes, [chave]: !antes[chave] }));

  return (
    <div className={`grid gap-3 ${mostrarPainel ? "lg:grid-cols-[1.55fr_1fr]" : ""}`}>
      <div className="space-y-3">
        <div className="rounded-xl border border-border bg-card/60 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {mostrarSeletorPrompt && (
              <select
                value={promptId}
                onChange={(e) => setPromptId(e.target.value)}
                className="rounded-lg border border-border bg-muted/40 px-2 py-1 text-[11px] outline-none focus:border-primary"
              >
                <option value="">prompt por omissão</option>
                {prompts.map((prompt) => (
                  <option key={prompt.id} value={prompt.id}>
                    {prompt.nome}
                  </option>
                ))}
              </select>
            )}
            {(
              [
                ["rag", "RAG", Database],
                ["memoria", "memória", Brain],
                ["skills", "skills", Wrench],
                ["raciocinio", "raciocínio", Sparkles],
              ] as const
            ).map(([chave, rotulo, Icone]) => (
              <button
                key={chave}
                type="button"
                onClick={() => alternar(chave)}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] transition-colors ${
                  raf[chave] ? "border-primary/50 bg-primary/10 text-primary" : "border-border text-muted-foreground"
                }`}
              >
                <Icone size={11} />
                {rotulo}
                <ToggleLeft size={10} className={raf[chave] ? "opacity-100" : "opacity-40"} />
              </button>
            ))}
          </div>

          <textarea
            value={dados}
            onChange={(e) => setDados(e.target.value)}
            rows={5}
            placeholder="Documento (opcional): campos do contrato/entidade"
            className="w-full rounded-lg border border-border bg-muted/30 px-3 py-2 font-mono text-[11px] outline-none focus:border-primary"
          />
          <div className="mt-2 flex items-end gap-2">
            <input
              value={instrucao}
              onChange={(e) => setInstrucao(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) void enviar();
              }}
              placeholder="Pergunta ou instrução…"
              className="flex-1 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm outline-none focus:border-primary"
            />
            <button
              type="button"
              onClick={() => void enviar()}
              disabled={aEnviar || !instrucao.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              {aEnviar ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
              {aEnviar ? "a gerar" : "Enviar"}
            </button>
          </div>
          {erro && <p className="mt-2 text-[11px] text-destructive">{erro}</p>}
        </div>

        <div className="space-y-3" style={{ minHeight: alturaMinima }}>
          {mensagens.length === 0 && (
            <p className="rounded-xl border border-dashed border-border p-4 text-center text-[11.5px] text-muted-foreground">
              O modelo responde com o adaptador treinado nesta máquina, com as memórias e evidências que tiver. Cada
              resposta mostra a árvore do raciocínio e os pesos dos tokens.
            </p>
          )}
          {mensagens.map((mensagem) =>
            mensagem.papel === "utilizador" ? (
              <div key={mensagem.id} className="ml-auto max-w-[85%] rounded-xl border border-primary/30 bg-primary/10 px-3 py-2 text-[12px]">
                {mensagem.texto}
              </div>
            ) : (
              <div key={mensagem.id} className="space-y-2 rounded-xl border border-border bg-card/60 p-3">
                <div className="flex items-center gap-2 text-[10.5px] text-muted-foreground">
                  <Brain size={12} className="text-primary" />
                  resposta
                  {mensagem.resposta && (
                    <span className="rounded bg-muted/60 px-1.5 py-[1px]">
                      {mensagem.resposta.tokens_gerados} tokens · {mensagem.resposta.duracao_s.toFixed(1)} s
                    </span>
                  )}
                  {mensagem.resposta?.skills.length ? (
                    <span className="rounded bg-primary/15 px-1.5 py-[1px] text-primary">
                      skills: {mensagem.resposta.skills.join(", ")}
                    </span>
                  ) : null}
                  <span className="ml-auto flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => void avaliar(mensagem, 1)}
                      className={`rounded p-1 hover:bg-muted ${mensagem.avaliada === "boa" ? "text-primary" : "text-muted-foreground"}`}
                      title="Resposta boa"
                    >
                      <ThumbsUp size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void avaliar(mensagem, -1)}
                      className={`rounded p-1 hover:bg-muted ${mensagem.avaliada === "ma" ? "text-amber-400" : "text-muted-foreground"}`}
                      title="Resposta má (guarda a correção)"
                    >
                      <ThumbsDown size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void guardarComoSkill(mensagem)}
                      className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-primary"
                      title="Guardar como skill"
                    >
                      <Save size={12} />
                    </button>
                  </span>
                </div>

                <p className="text-[12.5px] leading-relaxed">{mensagem.texto}</p>

                <input
                  value={correcao[mensagem.id] ?? ""}
                  onChange={(e) => setCorrecao((antes) => ({ ...antes, [mensagem.id]: e.target.value }))}
                  placeholder="Correção (opcional) — com 👎 passa a par de treino"
                  className="w-full rounded-lg border border-border bg-muted/20 px-2 py-1 text-[11px] outline-none focus:border-primary"
                />

                {mensagem.resposta && <ArvoreDoRaciocinio resposta={mensagem.resposta} />}
              </div>
            ),
          )}
          {aEnviar && (
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Loader2 size={12} className="animate-spin" /> a recuperar evidências, correr skills e gerar (CPU)…
            </div>
          )}
        </div>
      </div>

      {mostrarPainel && (
        <aside className="space-y-3">
          <div className="rounded-xl border border-border bg-card/60 p-3">
            <div className="mb-2 flex items-center justify-between text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <Wrench size={12} /> skills executáveis ({skills.length})
              </span>
            </div>
            <ul className="space-y-1">
              {skills.map((skill) => (
                <li key={skill.nome} className="rounded-md bg-muted/30 px-2 py-1 text-[10.5px]">
                  <span className="text-foreground">{skill.nome}</span>
                  <span className="ml-1 text-muted-foreground">{skill.descricao}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-border bg-card/60 p-3">
            <div className="mb-2 flex items-center justify-between text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <Brain size={12} /> memória e skills guardadas ({memorias.length})
              </span>
              <button type="button" onClick={() => void carregarPainel()} className="text-muted-foreground hover:text-foreground">
                <RefreshCw size={11} />
              </button>
            </div>
            <ul className="mb-2 max-h-32 space-y-1 overflow-auto">
              {memorias.slice(0, 12).map((item) => (
                <li key={item.id} className="flex items-start gap-1 rounded-md bg-muted/30 px-2 py-1 text-[10.5px]">
                  <span className="rounded bg-primary/15 px-1 text-[9px] uppercase text-primary">{item.tipo}</span>
                  <span className="flex-1 text-foreground">{item.titulo}</span>
                  <span className="text-muted-foreground">{item.usos ?? 0}×</span>
                </li>
              ))}
              {memorias.length === 0 && <li className="text-[10.5px] text-muted-foreground">Ainda sem memórias.</li>}
            </ul>
            <select
              value={novaMemoria.tipo}
              onChange={(e) => setNovaMemoria((antes) => ({ ...antes, tipo: e.target.value as "skill" | "memoria" }))}
              className="mb-1 w-full rounded-md border border-border bg-muted/40 px-2 py-1 text-[10.5px]"
            >
              <option value="skill">skill (entra no prompt e no treino)</option>
              <option value="memoria">memória (facto)</option>
            </select>
            <input
              value={novaMemoria.titulo}
              onChange={(e) => setNovaMemoria((antes) => ({ ...antes, titulo: e.target.value }))}
              placeholder="Título (ex.: resumo de subsídio da FCT)"
              className="mb-1 w-full rounded-md border border-border bg-muted/30 px-2 py-1 text-[10.5px] outline-none focus:border-primary"
            />
            <input
              value={novaMemoria.instrucao}
              onChange={(e) => setNovaMemoria((antes) => ({ ...antes, instrucao: e.target.value }))}
              placeholder="Instrução (o que fazer com os dados)"
              className="mb-1 w-full rounded-md border border-border bg-muted/30 px-2 py-1 text-[10.5px] outline-none focus:border-primary"
            />
            <textarea
              value={novaMemoria.resposta}
              onChange={(e) => setNovaMemoria((antes) => ({ ...antes, resposta: e.target.value }))}
              rows={2}
              placeholder="Resposta de exemplo (também vira par de treino)"
              className="mb-1 w-full rounded-md border border-border bg-muted/30 px-2 py-1 text-[10.5px] outline-none focus:border-primary"
            />
            <button
              type="button"
              onClick={() => void criarMemoria()}
              disabled={!novaMemoria.titulo.trim()}
              className="inline-flex w-full items-center justify-center gap-1 rounded-md bg-primary/90 px-2 py-1 text-[10.5px] font-medium text-primary-foreground disabled:opacity-50"
            >
              <MessageSquarePlus size={11} /> Guardar
            </button>
          </div>

          <div className="rounded-xl border border-border bg-card/60 p-3">
            <div className="mb-2 flex items-center justify-between text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <CheckCheck size={12} /> auto-aprendizagem
              </span>
              {retreino?.a_correr && <span className="text-primary">a treinar…</span>}
            </div>
            <div className="mb-2 grid grid-cols-2 gap-1 text-[10.5px] text-muted-foreground">
              <span>feedback: {feedback?.total ?? 0}</span>
              <span>corrigidos: {feedback?.corrigidos ?? 0}</span>
              <span>pares novos: {feedback?.por_utilizar ?? 0}</span>
              <span>nota média: {feedback?.nota_media ?? "—"}</span>
              <span>versões: {retreino?.versoes ?? 0}</span>
              <span>estado: {retreino?.a_correr ? "a treinar" : "parado"}</span>
            </div>
            {retreino?.a_correr && (
              <div className="mb-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${retreino.passos ? (retreino.passo / retreino.passos) * 100 : 0}%` }}
                  />
                </div>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  passo {retreino.passo}/{retreino.passos} · perda {retreino.perda ?? "—"}
                </p>
              </div>
            )}
            {retreino?.ultimo_resultado && !retreino.a_correr && (
              <p className="mb-2 text-[10px] leading-relaxed text-muted-foreground">
                última adaptação: {retreino.ultimo_resultado.estado} · perda{" "}
                {retreino.ultimo_resultado.perda_antes} → {retreino.ultimo_resultado.perda_depois} ·{" "}
                {retreino.ultimo_resultado.pares} pares
                {retreino.ultimo_resultado.backup ? ` · backup ${retreino.ultimo_resultado.backup}` : ""}
              </p>
            )}
            <button
              type="button"
              onClick={() => void retreinar()}
              disabled={retreino?.a_correr || (feedback?.por_utilizar ?? 0) < 3}
              className="inline-flex w-full items-center justify-center gap-1 rounded-md border border-primary/40 px-2 py-1 text-[10.5px] text-primary disabled:opacity-40"
              title="Precisa de 3 correções novas"
            >
              {retreino?.a_correr ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
              retreinar com o feedback
            </button>
            <p className="mt-1 text-[9.5px] leading-relaxed text-muted-foreground">
              12 passos de LoRA no adaptador, com backup e perda antes/depois.
            </p>
          </div>
        </aside>
      )}
    </div>
  );
}
