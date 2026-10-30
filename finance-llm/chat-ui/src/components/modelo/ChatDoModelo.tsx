/**
 * Chat do modelo — UX conversacional ao estilo ChatGPT.
 *
 * - Painel lateral opcional com memórias, skills, feedback e retreino.
 * - Área de conversa centrada, input flutuante na parte inferior.
 * - Exemplos rápidos, upload de ficheiros e relatório mantidos.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Brain,
  Briefcase,
  Building2,
  Database,
  ExternalLink,
  FileBarChart,
  FileUp,
  FileText,
  Gavel,
  HandCoins,
  History,
  Loader2,
  MessageSquarePlus,
  MoreHorizontal,
  PanelRight,
  PanelRightClose,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wrench,
} from "lucide-react";
import ArvoreDoRaciocinio from "./ArvoreDoRaciocinio";
import PainelDeRetreino from "./PainelDeRetreino";
import {
  enviarFeedback,
  getAdaptadores,
  getPrompts,
  getSkills,
  guardarMemoria,
  listarMemorias,
  perguntarAoModelo,
  type AdaptadorTreinado,
  type ItemMemoria,
  type PromptSistema,
  type RespostaModelo,
  type SkillExecutavel,
} from "../../llmModeloApi";

const CHAVE_STORAGE = "chat_modelo_contratos_historico";
/** Adaptador escolhido no chat (o modelo treinado que responde). */
const CHAVE_ADAPTADOR = "chat_modelo_contratos_adaptador";
/** Evento para o painel de auto-aprendizagem reler os contadores de feedback. */
const EVENTO_ATUALIZAR_RETREINO = "iqos:retreino-atualizar";

const EXEMPLOS: { icone: React.ElementType; titulo: string; instrucao: string; dados: string }[] = [
  {
    icone: Gavel,
    titulo: "Descrever contrato",
    instrucao: "Descreve este contrato público português.",
    dados: `Contrato 772453 - limpeza e desobstrução de coletores
Adjudicante: Município de Condeixa-a-Nova
Adjudicatário: OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS
Tipo: Aquisição de serviços
Procedimento: Ajuste Direto Regime Geral
Preço contratual: 20806.2`,
  },
  {
    icone: Building2,
    titulo: "Perfil de entidade",
    instrucao: "Quem é esta entidade e qual o papel nos contratos públicos?",
    dados: `Entidade: Sónia Maria Pais Pereira Carneiro
NIF: 123456789
País: Portugal
Contratos registados: 6
Como adjudicante: 0 contratos (0,00 €)
Como adjudicatário: 6 contratos
Valor total: 43 534,00 €`,
  },
  {
    icone: HandCoins,
    titulo: "Explicar subsídio",
    instrucao: "Descreve este subsídio público português.",
    dados: `Beneficiário: MARIA CAROLINA TRINDADE GONCALVES
NIF do beneficiário: 222415754
Entidade que atribui: FUNDAÇÃO PARA A CIÊNCIA E A TECNOLOGIA, I. P.
Montante: 2619.28
Finalidade: BOLS
Data da decisão: 2025-06-24`,
  },
  {
    icone: Briefcase,
    titulo: "Auditoria rápida",
    instrucao: "Faz uma auditoria rápida a este contrato.",
    dados: `Contrato 772453 - limpeza e desobstrução de coletores
Adjudicante: Município de Condeixa-a-Nova
Adjudicatário: OLIVEIRA & PIRES - SANEAMENTO E LIMPEZAS
Tipo: Aquisição de serviços
Procedimento: Ajuste Direto Regime Geral
Preço contratual: 20806.2
Prazo de execução: 60 dias`,
  },
];

type Mensagem = {
  id: number;
  papel: "utilizador" | "modelo";
  texto: string;
  resposta?: RespostaModelo;
  instrucao?: string;
  dados?: string;
  avaliada?: "boa" | "ma";
};

type FichaEmpresaChat = {
  nome: string;
  nif: string;
  contratos: number | null;
  valorTotal: number | null;
  adjudicante: { contratos: number | null; valor: number | null } | null;
  adjudicatario: { contratos: number | null; valor: number | null } | null;
};

function registo(valor: unknown): Record<string, unknown> | null {
  if (valor === null || typeof valor !== "object" || Array.isArray(valor)) return null;
  return Object.fromEntries(Object.entries(valor));
}

function numeroFicha(valor: unknown): number | null {
  if (typeof valor !== "number" && typeof valor !== "string") return null;
  if (typeof valor === "string" && !valor.trim()) return null;
  const numero = Number(valor);
  return Number.isFinite(numero) ? numero : null;
}

function lerPapelEmpresa(valor: unknown): FichaEmpresaChat["adjudicante"] {
  const papel = registo(valor);
  if (!papel) return null;
  return {
    contratos: numeroFicha(papel.contracts_count),
    valor: numeroFicha(papel.total_value),
  };
}

function fichaEmpresaDaResposta(resposta?: RespostaModelo): FichaEmpresaChat | null {
  const passo = resposta?.passos.find(
    (item) => item.fase === "skill" && item.titulo.includes("ficha_entidade"),
  );
  const resultado = registo(passo?.dados.resultado);
  if (!resultado || resultado.encontrado !== true) return null;
  const nome = typeof resultado.nome === "string" ? resultado.nome.trim() : "";
  const nif = typeof resultado.nif === "string" ? resultado.nif.trim() : "";
  if (!nome && !nif) return null;

  return {
    nome: nome || "Empresa",
    nif,
    contratos: numeroFicha(resultado.contratos),
    valorTotal: numeroFicha(resultado.valor_total),
    adjudicante: lerPapelEmpresa(resultado.adjudicante),
    adjudicatario: lerPapelEmpresa(resultado.adjudicatario),
  };
}

function formatarContagem(valor: number | null): string {
  return valor === null ? "—" : valor.toLocaleString("pt-PT");
}

function formatarValorEmpresa(valor: number | null): string {
  return valor === null
    ? "—"
    : valor.toLocaleString("pt-PT", { style: "currency", currency: "EUR" });
}

function guardarHistorico(lista: Mensagem[]) {
  try {
    // Não guardamos objectos RespostaModelo inteiros (são grandes); guardamos só o texto.
    const enxuto = lista.map((m) => ({
      ...m,
      resposta: undefined,
      dados: m.dados?.slice(0, 4000) ?? "",
      texto: m.texto?.slice(0, 4000) ?? "",
    }));
    sessionStorage.setItem(CHAVE_STORAGE, JSON.stringify(enxuto));
  } catch {
    /* ignorar quota excedida */
  }
}

function carregarHistorico(): Mensagem[] {
  try {
    const raw = sessionStorage.getItem(CHAVE_STORAGE);
    return raw ? (JSON.parse(raw) as Mensagem[]) : [];
  } catch {
    return [];
  }
}

function lerFicheiroComoTexto(ficheiro: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Não foi possível ler o ficheiro"));
    reader.readAsText(ficheiro);
  });
}

function classificarMensagem(texto: string): string | null {
  const t = texto.toLowerCase();
  if (t.includes("relatório") || t.includes("report")) return "relatório";
  if (t.includes("auditoria")) return "auditoria";
  if (t.includes("contrato")) return "contrato";
  if (t.includes("subsídio") || t.includes("bols")) return "subsídio";
  if (t.includes("entidade")) return "entidade";
  return null;
}

export default function ChatDoModelo({
  mostrarPainel = true,
  alturaMinima = 260,
  sistemaOverride = null,
  mostrarSeletorPrompt = true,
  maxTokens = 160,
  temperatura = 0.2,
  guardarHistoricoAtivo = true,
  mostrarExemplos = true,
}: {
  mostrarPainel?: boolean;
  alturaMinima?: number;
  /** Prompt de sistema escrito à mão (playground) — ganha ao `prompt_id`. */
  sistemaOverride?: string | null;
  mostrarSeletorPrompt?: boolean;
  maxTokens?: number;
  temperatura?: number;
  guardarHistoricoAtivo?: boolean;
  mostrarExemplos?: boolean;
}) {
  const [_alturaMinima] = useState(alturaMinima);
  const [_mostrarExemplos] = useState(mostrarExemplos);
  void _alturaMinima;
  void _mostrarExemplos;
  const [mensagens, setMensagens] = useState<Mensagem[]>(() => carregarHistorico());
  const [instrucao, setInstrucao] = useState("");
  const [dados, setDados] = useState("");
  const [aEnviar, setAEnviar] = useState(false);
  const [aGerarRelatorio, setAGerarRelatorio] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const ficheiroRef = useRef<HTMLInputElement | null>(null);
  const [prompts, setPrompts] = useState<PromptSistema[]>([]);
  const [promptId, setPromptId] = useState<string>("consultar");
  const [skills, setSkills] = useState<SkillExecutavel[]>([]);
  const [memorias, setMemorias] = useState<ItemMemoria[]>([]);
  const [raf, setRaf] = useState({ rag: true, memoria: true, skills: true, raciocinio: true });
  const [correcao, setCorrecao] = useState<Record<number, string>>({});
  const [novaMemoria, setNovaMemoria] = useState({ titulo: "", instrucao: "", resposta: "", tipo: "skill" as "skill" | "memoria" });
  const [painelAberto, setPainelAberto] = useState(mostrarPainel);
  const fimRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [mostrarOpcoes, setMostrarOpcoes] = useState<number | null>(null);
  // Modelo treinado escolhido: `""` = o adaptador predefinido da plataforma.
  const [adaptadores, setAdaptadores] = useState<AdaptadorTreinado[]>([]);
  const [adaptadorId, setAdaptadorId] = useState<string>(() => {
    try {
      return window.localStorage.getItem(CHAVE_ADAPTADOR) ?? "";
    } catch {
      return "";
    }
  });

  const escolherAdaptador = (id: string) => {
    setAdaptadorId(id);
    try {
      if (id) window.localStorage.setItem(CHAVE_ADAPTADOR, id);
      else window.localStorage.removeItem(CHAVE_ADAPTADOR);
    } catch {
      /* modo privado: fica só em memória */
    }
  };

  const carregarPainel = useCallback(async () => {
    const [listaPrompts, listaSkills, listaMemorias, listaAdaptadores] = await Promise.all([
      getPrompts().catch(() => ({ prompts: [], total: 0 })),
      getSkills().catch(() => ({ skills: [], total: 0 })),
      listarMemorias().catch(() => ({ itens: [], total: 0 })),
      getAdaptadores().catch(() => ({ adaptadores: [], total: 0 })),
    ]);
    setPrompts(listaPrompts.prompts);
    setSkills(listaSkills.skills);
    setMemorias(listaMemorias.itens);
    // Só os adaptadores treinados sobre o mesmo modelo base que o chat carrega:
    // um LoRA de outro modelo devolveria texto sem sentido.
    setAdaptadores(listaAdaptadores.adaptadores.filter((a) => a.compativel));
    // O adaptador guardado pode ter desaparecido (pasta apagada, versão
    // revertida): nesse caso volta-se ao predefinido em vez de falhar no envio.
    setAdaptadorId((atual) => {
      if (!atual) return atual;
      return listaAdaptadores.adaptadores.some((a) => a.id === atual && a.compativel) ? atual : "";
    });
  }, []);

  useEffect(() => {
    void carregarPainel();
  }, [carregarPainel]);

  useEffect(() => {
    if (guardarHistoricoAtivo) {
      guardarHistorico(mensagens);
    }
  }, [mensagens, guardarHistoricoAtivo]);

  useEffect(() => {
    if (fimRef.current) fimRef.current.scrollIntoView({ behavior: "smooth" });
  }, [mensagens, aEnviar]);

  const substituirConversa = (novaInstrucao: string, novosDados: string) => {
    setDados(novosDados);
    setErro(null);
    void enviar(novaInstrucao, novosDados);
  };

  const iniciarNovaConversa = () => {
    setMensagens([]);
    setInstrucao("");
    setDados("");
    setCorrecao({});
    setErro(null);
    try {
      sessionStorage.removeItem(CHAVE_STORAGE);
    } catch {
      /* noop */
    }
  };

  const adicionarMensagem = (mensagem: Mensagem) => {
    setMensagens((antes) => [...antes, mensagem]);
  };

  const enviar = async (instrucaoCustom?: string, dadosCustom?: string) => {
    const pergunta = (instrucaoCustom ?? instrucao).trim();
    const doc = dadosCustom ?? dados;
    if (!pergunta || aEnviar) return;
    setAEnviar(true);
    setErro(null);
    setInstrucao("");
    adicionarMensagem({ id: Date.now(), papel: "utilizador", texto: pergunta, dados: doc });
    try {
      const resposta = await perguntarAoModelo({
        instrucao: pergunta,
        dados: doc,
        prompt_id: sistemaOverride ? null : promptId || null,
        sistema: sistemaOverride || null,
        usar_rag: raf.rag,
        usar_memoria: raf.memoria,
        usar_skills: raf.skills,
        raciocinio: raf.raciocinio,
        max_tokens: maxTokens,
        temperatura,
        adaptador: adaptadorId || null,
      });
      adicionarMensagem({
        id: Date.now() + 1,
        papel: "modelo",
        texto: resposta.resposta,
        resposta,
        instrucao: pergunta,
        dados: doc,
      });
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "O modelo não respondeu");
    } finally {
      setAEnviar(false);
    }
  };

  const gerarRelatorio = async () => {
    if (mensagens.length === 0) return;
    setAGerarRelatorio(true);
    setErro(null);
    const pares = mensagens
      .filter((m): m is Mensagem & { resposta: RespostaModelo } => m.papel === "modelo" && !!m.resposta)
      .map((m) => `Pedido: ${m.instrucao ?? ""}\nDocumento:\n${m.dados ?? ""}\nResposta:\n${m.texto}`)
      .join("\n\n---\n\n");
    const instrucaoRelatorio = "Resume as respostas anteriores num relatório curto e estruturado: pontos-chave, números verificados e recomendações.";
    adicionarMensagem({ id: Date.now(), papel: "utilizador", texto: "📄 Gerar relatório da conversa", dados: pares });
    try {
      const resposta = await perguntarAoModelo({
        instrucao: instrucaoRelatorio,
        dados: pares,
        prompt_id: null,
        sistema: sistemaOverride || null,
        usar_rag: false,
        usar_memoria: false,
        usar_skills: false,
        raciocinio: true,
        max_tokens: 320,
        temperatura: 0.1,
        adaptador: adaptadorId || null,
      });
      adicionarMensagem({
        id: Date.now() + 1,
        papel: "modelo",
        texto: resposta.resposta,
        resposta,
        instrucao: instrucaoRelatorio,
        dados: pares,
      });
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível gerar o relatório");
    } finally {
      setAGerarRelatorio(false);
    }
  };

  const handleFicheiro = async (ficheiro: File | undefined) => {
    if (!ficheiro) return;
    setErro(null);
    try {
      const texto = await lerFicheiroComoTexto(ficheiro);
      if (ficheiro.type === "application/json") {
        // Normalizar documentos JSON (ex.: resposta do contrato/entidade).
        try {
          const obj = JSON.parse(texto);
          setDados(JSON.stringify(obj, null, 2));
          setInstrucao((antes) => (antes.trim() ? antes : "Descreve este contrato p?blico portugu?s."));
        } catch {
          setDados(texto);
        }
      } else {
        setDados(texto);
        setInstrucao((antes) => (antes.trim() ? antes : "Descreve este contrato p?blico portugu?s."));
      }
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Ficheiro inválido");
    }
  };

  /**
   * Escolher um perfil troca também a instrução.
   *
   * O prompt de sistema diz «audita», mas a instrução continuava a ser
   * «Descreve este contrato público português.» — o modelo recebia dois pedidos
   * contrários e obedecia ao que tinha decorado. Cada perfil traz a instrução
   * com que foi treinado; só a substituímos se o utilizador não escreveu nada
   * de seu (ou se ainda estava na instrução de outro perfil).
   */
  const escolherPerfil = (novoId: string) => {
    setPromptId(novoId);
    const perfil = prompts.find((p) => p.id === novoId);
    const padrao = perfil?.instrucao?.trim();
    if (!padrao) return;
    const dasPerfis = new Set(prompts.map((p) => p.instrucao?.trim()).filter(Boolean));
    setInstrucao((antes) => (!antes.trim() || dasPerfis.has(antes.trim()) ? padrao : antes));
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i];
      if (item.kind === "file") {
        const ficheiro = item.getAsFile();
        if (ficheiro) void handleFicheiro(ficheiro);
        return;
      }
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
      // O painel de auto-aprendizagem mostra os contadores de feedback: avisá-lo
      // para reler em vez de duplicar o estado aqui.
      window.dispatchEvent(new CustomEvent(EVENTO_ATUALIZAR_RETREINO));
      void resultado;
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

  const alternar = (chave: keyof typeof raf) => setRaf((antes) => ({ ...antes, [chave]: !antes[chave] }));

  const area = classificarMensagem(instrucao);

  return (
    <div className="relative flex h-full min-h-[520px] flex-col overflow-hidden rounded-2xl border border-border bg-background">
      <header className="flex items-center justify-between border-b border-border bg-card/40 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sparkles size={16} />
          </div>
          <div>
            <h3 className="text-sm font-medium text-foreground">Modelo de contratos</h3>
            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span>{adaptadorId ? `${adaptadorId} · LoRA` : "Qwen 0.5B + LoRA"}</span>
              <span>· memória, skills, RAG e raciocínio</span>
              {adaptadores.length > 1 && (
                <label className="flex items-center gap-1" title="Escolher o modelo treinado que responde">
                  <select
                    value={adaptadorId}
                    onChange={(evento) => escolherAdaptador(evento.target.value)}
                    disabled={aEnviar}
                    className="rounded-md border border-border bg-background px-1.5 py-0.5 text-[10.5px] text-foreground outline-none focus:border-primary disabled:opacity-50"
                  >
                    {adaptadores.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id}
                        {item.origem === "soup" ? " (soup)" : ""}
                        {item.atual ? " · predefinido" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void gerarRelatorio()}
            disabled={aGerarRelatorio || mensagens.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-[11px] text-foreground hover:bg-muted disabled:opacity-40"
          >
            {aGerarRelatorio ? <Loader2 size={12} className="animate-spin" /> : <FileBarChart size={12} />}
            Gerar relatório
          </button>
          <button
            type="button"
            onClick={iniciarNovaConversa}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-[11px] text-foreground hover:bg-muted"
            title="Nova conversa"
          >
            <Plus size={12} /> Novo
          </button>
          {mostrarPainel && (
            <button
              type="button"
              onClick={() => setPainelAberto((a) => !a)}
              className={`inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] hover:bg-muted ${painelAberto ? "bg-primary/10 text-primary" : "bg-background text-foreground"}`}
              title={painelAberto ? "Fechar painel" : "Abrir painel"}
            >
              {painelAberto ? <PanelRightClose size={12} /> : <PanelRight size={12} />}
              Painel
            </button>
          )}
        </div>
      </header>

      <div className="relative flex flex-1 overflow-hidden">
        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 space-y-5 overflow-y-auto px-4 py-5 md:px-8 lg:px-12">
            {mensagens.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-5 py-12 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                  <Brain size={24} />
                </div>
                <div className="max-w-md space-y-1">
                  <p className="text-sm font-medium text-foreground">Como posso ajudar?</p>
                  <p className="text-[12px] leading-relaxed text-muted-foreground">
                    O modelo corre localmente nesta máquina. Escolhe um exemplo, carrega um documento ou escreve uma
                    pergunta. Cada resposta mostra a árvore do raciocínio e os pesos dos tokens.
                  </p>
                </div>
                <div className="grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
                  {EXEMPLOS.map((exemplo, i) => {
                    const Icone = exemplo.icone;
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => substituirConversa(exemplo.instrucao, exemplo.dados)}
                        className="group flex items-start gap-3 rounded-xl border border-border bg-card/40 p-3 text-left transition-colors hover:border-primary/30 hover:bg-primary/5"
                      >
                        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-primary group-hover:border-primary/30">
                          <Icone size={14} />
                        </div>
                        <div>
                          <p className="text-[12px] font-medium text-foreground">{exemplo.titulo}</p>
                          <p className="text-[11px] text-muted-foreground">{exemplo.instrucao}</p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {mensagens.map((mensagem) =>
              mensagem.papel === "utilizador" ? (
                <div key={mensagem.id} className="flex justify-end">
                  <div className="relative max-w-[90%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[13px] text-primary-foreground shadow-sm md:max-w-[80%]">
                    {mensagem.texto}
                  </div>
                </div>
              ) : (
                <div key={mensagem.id} className="flex gap-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Sparkles size={13} />
                  </div>
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="rounded-2xl rounded-tl-md border border-border bg-card/60 p-4 shadow-sm">
                      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">{mensagem.texto}</p>
                    </div>

                    {(() => {
                      const empresa = fichaEmpresaDaResposta(mensagem.resposta);
                      if (!empresa) return null;
                      const hrefFicha = /^\d{9}$/.test(empresa.nif)
                        ? `/companies/${encodeURIComponent(empresa.nif)}`
                        : "/companies/search";

                      return (
                        <section
                          aria-label={`Detalhes da empresa ${empresa.nome}`}
                          className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm"
                        >
                          <div className="flex items-start gap-3 border-b border-border/70 px-4 py-3">
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                              <Building2 size={17} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <h3 className="truncate text-sm font-semibold text-foreground">{empresa.nome}</h3>
                              <p className="mt-0.5 text-[11px] text-muted-foreground">
                                {empresa.nif ? `NIF ${empresa.nif}` : "Ficha de empresa"}
                              </p>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-4">
                            <div>
                              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Contratos</p>
                              <p className="mt-1 text-sm font-semibold text-foreground">
                                {formatarContagem(empresa.contratos)}
                              </p>
                            </div>
                            <div>
                              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Valor total</p>
                              <p className="mt-1 text-sm font-semibold text-foreground">
                                {formatarValorEmpresa(empresa.valorTotal)}
                              </p>
                            </div>
                            {empresa.adjudicante && (
                              <div>
                                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                  Como adjudicante
                                </p>
                                <p className="mt-1 text-sm font-semibold text-foreground">
                                  {formatarContagem(empresa.adjudicante.contratos)} contratos
                                </p>
                                <p className="text-[11px] text-muted-foreground">
                                  {formatarValorEmpresa(empresa.adjudicante.valor)}
                                </p>
                              </div>
                            )}
                            {empresa.adjudicatario && (
                              <div>
                                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                                  Como adjudicatária
                                </p>
                                <p className="mt-1 text-sm font-semibold text-foreground">
                                  {formatarContagem(empresa.adjudicatario.contratos)} contratos
                                </p>
                                <p className="text-[11px] text-muted-foreground">
                                  {formatarValorEmpresa(empresa.adjudicatario.valor)}
                                </p>
                              </div>
                            )}
                          </div>

                          <div className="flex flex-wrap gap-2 border-t border-border/70 px-4 py-3">
                            <a
                              href={hrefFicha}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1.5 text-[11px] font-medium text-primary hover:bg-primary/15"
                            >
                              <Building2 size={12} />
                              Ficha da empresa
                              <ExternalLink size={11} />
                            </a>
                            <a
                              href="/contracts/search"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] text-foreground hover:bg-muted"
                            >
                              <FileText size={12} />
                              Pesquisar contratos
                              <ExternalLink size={11} />
                            </a>
                            <a
                              href="/contracts/dashboard"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] text-foreground hover:bg-muted"
                            >
                              <FileBarChart size={12} />
                              Dashboard de contratos
                              <ExternalLink size={11} />
                            </a>
                          </div>
                        </section>
                      );
                    })()}

                    <div className="flex flex-wrap items-center gap-2">
                      {mensagem.resposta && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
                          <History size={10} />
                          {mensagem.resposta.tokens_gerados} tokens · {mensagem.resposta.duracao_s.toFixed(1)} s
                        </span>
                      )}
                      {mensagem.resposta?.skills.length ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">
                          <Wrench size={10} />
                          {mensagem.resposta.skills.join(", ")}
                        </span>
                      ) : null}

                      <div className="relative ml-auto flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => void avaliar(mensagem, 1)}
                          className={`rounded p-1 hover:bg-muted ${mensagem.avaliada === "boa" ? "text-primary" : "text-muted-foreground"}`}
                          title="Resposta boa"
                        >
                          <ThumbsUp size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void avaliar(mensagem, -1)}
                          className={`rounded p-1 hover:bg-muted ${mensagem.avaliada === "ma" ? "text-amber-400" : "text-muted-foreground"}`}
                          title="Resposta má"
                        >
                          <ThumbsDown size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setMostrarOpcoes((id) => (id === mensagem.id ? null : mensagem.id))}
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                          title="Mais opções"
                        >
                          <MoreHorizontal size={13} />
                        </button>
                        {mostrarOpcoes === mensagem.id && (
                          <div className="absolute right-0 top-full z-10 mt-1 w-44 rounded-lg border border-border bg-background p-1 shadow-lg">
                            <button
                              type="button"
                              onClick={() => {
                                void guardarComoSkill(mensagem);
                                setMostrarOpcoes(null);
                              }}
                              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[11px] text-foreground hover:bg-muted"
                            >
                              <Save size={12} /> Guardar como skill
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {mensagem.avaliada === "ma" && (
                      <input
                        value={correcao[mensagem.id] ?? ""}
                        onChange={(e) => setCorrecao((antes) => ({ ...antes, [mensagem.id]: e.target.value }))}
                        placeholder="Correção (opcional) — com 👎 passa a par de treino"
                        className="w-full rounded-lg border border-border bg-muted/20 px-3 py-2 text-[11px] outline-none focus:border-primary"
                      />
                    )}

                    {mensagem.resposta && <ArvoreDoRaciocinio resposta={mensagem.resposta} />}
                  </div>
                </div>
              ),
            )}

            {aEnviar && (
              <div className="flex gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Sparkles size={13} />
                </div>
                <div className="flex items-center gap-2 py-2 text-[12px] text-muted-foreground">
                  <Loader2 size={13} className="animate-spin" />
                  a recuperar evidências, correr skills e gerar (CPU)…
                </div>
              </div>
            )}
            <div ref={fimRef} />
          </div>

          <div className="border-t border-border bg-background/95 p-3 backdrop-blur md:p-4">
            <div className="mx-auto max-w-3xl space-y-2">
              <div className="flex items-center justify-between gap-2 px-1">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <History size={11} />
                  {mensagens.filter((m) => m.papel === "utilizador").length} pedidos ·{" "}
                  {mensagens.filter((m) => m.papel === "modelo").length} respostas
                </div>
                <div className="flex items-center gap-1.5">
                  {(
                    [
                      ["rag", "RAG", Database],
                      ["memoria", "Memória", Brain],
                      ["skills", "Skills", Wrench],
                      ["raciocinio", "Raciocínio", Sparkles],
                    ] as const
                  ).map(([chave, rotulo, Icone]) => (
                    <button
                      key={chave}
                      type="button"
                      onClick={() => alternar(chave)}
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                        raf[chave]
                          ? "border-primary/40 bg-primary/10 text-primary"
                          : "border-border bg-muted/30 text-muted-foreground hover:text-foreground"
                      }`}
                      title={rotulo}
                    >
                      <Icone size={10} />
                      <span className="hidden sm:inline">{rotulo}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-muted/30 p-2 shadow-sm transition-colors focus-within:border-primary focus-within:bg-muted/50">
                {dados.trim() && (
                  <div className="mb-2 flex items-center justify-between rounded-lg bg-background/60 px-3 py-1.5">
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <FileUp size={11} />
                      Documento carregado · {dados.length.toLocaleString()} caracteres
                    </span>
                    <button
                      type="button"
                      onClick={() => setDados("")}
                      className="text-[11px] text-destructive hover:underline"
                    >
                      limpar
                    </button>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  <textarea
                    ref={inputRef}
                    value={instrucao}
                    onChange={(e) => {
                      setInstrucao(e.target.value);
                      e.target.style.height = "auto";
                      e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void enviar();
                      }
                    }}
                    onPaste={handlePaste}
                    rows={1}
                    placeholder="Mensagem para o modelo…"
                    className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent px-3 py-2.5 text-[13px] outline-none placeholder:text-muted-foreground"
                    style={{ lineHeight: "1.4" }}
                  />
                  <div className="flex items-center gap-1 pb-1 pr-1">
                    <input ref={ficheiroRef} type="file" accept=".json,.txt,.csv,.md,.pdf" className="hidden" onChange={(e) => void handleFicheiro(e.target.files?.[0])} />
                    <button
                      type="button"
                      onClick={() => ficheiroRef.current?.click()}
                      className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="Carregar documento (Ctrl+V cola diretamente)"
                    >
                      <FileUp size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void enviar()}
                      disabled={aEnviar || !instrucao.trim()}
                      className="rounded-xl bg-primary p-2 text-primary-foreground shadow-sm transition-transform active:scale-95 disabled:opacity-40"
                    >
                      {aEnviar ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 px-1">
                <div className="flex items-center gap-1.5">
                  {mostrarSeletorPrompt && (
                    <select
                      value={promptId}
                      onChange={(e) => escolherPerfil(e.target.value)}
                      className="rounded-lg border border-border bg-muted/40 px-2 py-1 text-[11px] outline-none focus:border-primary"
                    >
                      <option value="">Prompt por omissão</option>
                      {prompts.map((prompt) => (
                        <option key={prompt.id} value={prompt.id}>
                          {prompt.nome}
                        </option>
                      ))}
                    </select>
                  )}
                  {area && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">
                      <Sparkles size={10} />
                      {area}
                    </span>
                  )}
                </div>
                <span className="hidden text-[10px] text-muted-foreground sm:inline">Shift+Enter para nova linha · Enter para enviar</span>
              </div>

              {erro && <p className="rounded-lg bg-destructive/10 px-3 py-2 text-[11px] text-destructive">{erro}</p>}
            </div>
          </div>
        </main>

        {mostrarPainel && painelAberto && (
          <aside className="hidden shrink-0 border-l border-border bg-card/40 p-3 sm:block sm:w-80 lg:w-96">
            <div className="mb-3 flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <Wrench size={12} /> skills ({skills.length})
              </span>
            </div>
            <ul className="mb-5 space-y-1">
              {skills.map((skill) => (
                <li key={skill.nome} className="rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px]">
                  <span className="font-medium text-foreground">{skill.nome}</span>
                  <p className="text-[10px] text-muted-foreground">{skill.descricao}</p>
                </li>
              ))}
            </ul>

            <div className="mb-3 flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <Brain size={12} /> memória ({memorias.length})
              </span>
              <button type="button" onClick={() => void carregarPainel()} className="text-muted-foreground hover:text-foreground">
                <RefreshCw size={11} />
              </button>
            </div>
            <ul className="mb-4 max-h-40 space-y-1 overflow-auto">
              {memorias.slice(0, 12).map((item) => (
                <li key={item.id} className="flex items-start gap-1.5 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px]">
                  <span className="rounded bg-primary/15 px-1 py-[1px] text-[9px] uppercase text-primary">{item.tipo}</span>
                  <span className="flex-1 leading-tight text-foreground">{item.titulo}</span>
                  <span className="text-muted-foreground">{item.usos ?? 0}×</span>
                </li>
              ))}
            </ul>

            <div className="mb-3 flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <MessageSquarePlus size={12} /> guardar memória
              </span>
            </div>
            <div className="space-y-1.5">
              <select
                value={novaMemoria.tipo}
                onChange={(e) => setNovaMemoria((antes) => ({ ...antes, tipo: e.target.value as "skill" | "memoria" }))}
                className="w-full rounded-lg border border-border bg-muted/40 px-2 py-1 text-[11px]"
              >
                <option value="skill">Skill (prompt + treino)</option>
                <option value="memoria">Memória (facto)</option>
              </select>
              <input
                value={novaMemoria.titulo}
                onChange={(e) => setNovaMemoria((antes) => ({ ...antes, titulo: e.target.value }))}
                placeholder="Título"
                className="w-full rounded-lg border border-border bg-muted/30 px-2 py-1 text-[11px] outline-none focus:border-primary"
              />
              <input
                value={novaMemoria.instrucao}
                onChange={(e) => setNovaMemoria((antes) => ({ ...antes, instrucao: e.target.value }))}
                placeholder="Instrução"
                className="w-full rounded-lg border border-border bg-muted/30 px-2 py-1 text-[11px] outline-none focus:border-primary"
              />
              <textarea
                value={novaMemoria.resposta}
                onChange={(e) => setNovaMemoria((antes) => ({ ...antes, resposta: e.target.value }))}
                rows={2}
                placeholder="Resposta de exemplo"
                className="w-full rounded-lg border border-border bg-muted/30 px-2 py-1 text-[11px] outline-none focus:border-primary"
              />
              <button
                type="button"
                onClick={() => void criarMemoria()}
                disabled={!novaMemoria.titulo.trim()}
                className="inline-flex w-full items-center justify-center gap-1 rounded-lg bg-primary/90 px-2 py-1.5 text-[11px] font-medium text-primary-foreground disabled:opacity-50"
              >
                Guardar
              </button>
            </div>

            <PainelDeRetreino variante="painel" className="mt-5" />
          </aside>
        )}
      </div>
    </div>
  );
}
