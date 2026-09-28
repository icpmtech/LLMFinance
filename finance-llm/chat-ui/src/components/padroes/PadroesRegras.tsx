/**
 * Gestão das **regras de deteção** (separador «Regras» da página de padrões).
 *
 * As regras são guardadas no servidor (`/padroes/regras`) e aplicadas pelo motor
 * à amostra: cada contrato que cumpra uma regra ativa aparece em «Contratos
 * apanhados pelas regras», com o detalhe do valor que disparou a condição.
 *
 * Aqui pode: criar/editar regras, ligar/desligar, duplicar, apagar, **repor as
 * predefinições** e guardar/aplicar **templates** (conjuntos temáticos).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Copy,
  Eraser,
  Info,
  Layers,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  applyPadroesTemplate,
  deletePadroesRegra,
  deletePadroesTemplate,
  duplicatePadroesRegra,
  getPadroesRegras,
  resetPadroesRegras,
  savePadroesRegra,
  savePadroesTemplate,
  togglePadroesRegra,
} from "../../padroesApi";
import type {
  PadroesAnalysis,
  PadroesCondicao,
  PadroesCondicaoValor,
  PadroesRegra,
  PadroesRegraHit,
  PadroesRegrasState,
} from "../../padroesApi";
import { Chip, EmptyState, Loading, SectionCard, formatCompactEuro, formatNumber, padraoTone } from "./padroesKit";

type CondicaoForm = {
  campo: string;
  operador: string;
  /** Valor fixo (texto) ou campo comparado. */
  valor: string;
  /** Campo de referência (quando `tipoValor === "campo"`). */
  campoRef: string;
  fator: string;
  tipoValor: "fixo" | "campo";
};

type RegraForm = {
  id?: string;
  label: string;
  descricao: string;
  severidade: string;
  modo: "todas" | "alguma";
  ativo: boolean;
  condicoes: CondicaoForm[];
};

const SEVERIDADE_TONE: Record<string, string> = { alerta: "rose", aviso: "amber", info: "blue" };

function condicaoVazia(campos: { id: string; tipo: string }[]): CondicaoForm {
  return {
    campo: campos.find((campo) => campo.tipo === "numero")?.id ?? campos[0]?.id ?? "valor",
    operador: ">",
    valor: "",
    campoRef: campos.find((campo) => campo.tipo === "numero")?.id ?? "valor",
    fator: "1",
    tipoValor: "fixo",
  };
}

function paraForm(regra: PadroesRegra, campos: { id: string; tipo: string; label: string }[]): RegraForm {
  return {
    id: regra.id,
    label: regra.label,
    descricao: regra.descricao ?? "",
    severidade: regra.severidade || "aviso",
    modo: regra.modo === "alguma" ? "alguma" : "todas",
    ativo: regra.ativo,
    condicoes: (regra.condicoes ?? []).map((condicao) => {
      const referencia = condicao.valor && typeof condicao.valor === "object" ? condicao.valor : null;
      const tipo = campos.find((campo) => campo.id === condicao.campo)?.tipo ?? "numero";
      return {
        campo: condicao.campo,
        operador: condicao.operador,
        valor: referencia ? "" : String(condicao.valor ?? ""),
        campoRef: referencia?.campo ?? campos.find((campo) => campo.tipo === tipo)?.id ?? condicao.campo,
        fator: referencia ? String(referencia.fator ?? 1) : "1",
        tipoValor: referencia ? "campo" : "fixo",
      };
    }),
  };
}

function condicaoValor(condicao: CondicaoForm, tipo: string | undefined): PadroesCondicaoValor {
  if (condicao.tipoValor === "campo") {
    return { campo: condicao.campoRef, fator: Number(condicao.fator) || 1 };
  }
  if (tipo === "numero") return Number(condicao.valor.replace(",", ".")) || 0;
  return condicao.valor;
}

export function PadroesRegras({
  analysis,
  onChanged,
}: {
  /** Análise atual (dá as contagens por regra e os contratos apanhados). */
  analysis: PadroesAnalysis | null;
  /** Chamado depois de alterar regras (para recalcular a análise). */
  onChanged: () => void;
}) {
  const [estado, setEstado] = useState<PadroesRegrasState | null>(null);
  const [loading, setLoading] = useState(true);
  const [aGuardar, setAGuardar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [form, setForm] = useState<RegraForm | null>(null);
  const [templateNome, setTemplateNome] = useState("");
  const [templateDescricao, setTemplateDescricao] = useState("");
  const [filtroSeveridade, setFiltroSeveridade] = useState("");
  const [filtroRegra, setFiltroRegra] = useState("");
  const [limiteHits, setLimiteHits] = useState(25);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      setEstado(await getPadroesRegras());
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao carregar as regras");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const campos = estado?.campos ?? [];
  const operadores = estado?.operadores ?? [];

  const contagens = useMemo(() => {
    const mapa = new Map<string, number>();
    (analysis?.regras?.ativas ?? []).forEach((regra) => mapa.set(regra.id, regra.contratos ?? 0));
    return mapa;
  }, [analysis]);

  const hits: PadroesRegraHit[] = useMemo(() => {
    const items = analysis?.regras_hits ?? [];
    return items.filter((item) => {
      if (filtroSeveridade && item.severidade !== filtroSeveridade) return false;
      if (filtroRegra && !(item.regras ?? []).includes(filtroRegra)) return false;
      return true;
    });
  }, [analysis, filtroSeveridade, filtroRegra]);

  const executar = useCallback(
    async (acao: () => Promise<unknown>, mensagem: string, recarregarAnalise = true) => {
      setAGuardar(true);
      setErro(null);
      try {
        await acao();
        setAviso(mensagem);
        await carregar();
        if (recarregarAnalise) onChanged();
      } catch (err) {
        const texto = err instanceof Error ? err.message : "Erro inesperado";
        setErro(texto.includes("401") ? "Inicie sessão para gerir as regras (as alterações exigem sessão)." : texto);
      } finally {
        setAGuardar(false);
      }
    },
    [carregar, onChanged],
  );

  const guardarForm = useCallback(async () => {
    if (!form) return;
    const condicoes: PadroesCondicao[] = form.condicoes.map((condicao) => ({
      campo: condicao.campo,
      operador: condicao.operador,
      valor: condicaoValor(condicao, campos.find((campo) => campo.id === condicao.campo)?.tipo),
    }));
    await executar(
      () =>
        savePadroesRegra({
          id: form.id,
          label: form.label,
          descricao: form.descricao,
          severidade: form.severidade,
          modo: form.modo,
          ativo: form.ativo,
          condicoes,
        }),
      form.id ? "Regra atualizada." : "Regra criada.",
    );
    setForm(null);
  }, [form, campos, executar]);

  if (loading && !estado) return <Loading label="A carregar as regras…" />;
  if (!estado) {
    return <EmptyState tone="warn">{erro ?? "Não foi possível carregar as regras."}</EmptyState>;
  }

  return (
    <div className="space-y-5">
      {/* ----------------------------------------------------- ações globais */}
      <SectionCard
        icon={Layers}
        title="Regras de deteção"
        subtitle={`${formatNumber(estado.regras.length)} regras guardadas · ${formatNumber(estado.regras.filter((r) => r.ativo).length)} ativas · ${formatNumber(estado.templates.length)} templates`}
        actions={
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              onClick={() => setForm({ id: undefined, label: "", descricao: "", severidade: "aviso", modo: "todas", ativo: true, condicoes: [condicaoVazia(campos)] })}
              className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-teal-400/90 to-sky-500/90 px-3 py-1.5 font-semibold text-black transition hover:brightness-110"
            >
              <Plus size={13} /> Nova regra
            </button>
            <button
              onClick={() => void executar(() => resetPadroesRegras(true), "Predefinições repostas (personalizadas mantidas).")}
              disabled={aGuardar}
              className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 transition hover:bg-white/5 disabled:opacity-50"
              title="Reescreve as regras predefinidas e mantém as que criou"
            >
              <RotateCcw size={13} /> Repor predefinidas
            </button>
            <button
              onClick={() => void executar(() => resetPadroesRegras(false), "Todas as regras voltaram ao estado de fábrica.")}
              disabled={aGuardar}
              className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 transition hover:bg-white/5 disabled:opacity-50"
            >
              <Eraser size={13} /> Só predefinições
            </button>
          </div>
        }
      >
        {erro && (
          <div className="mb-3">
            <EmptyState tone="warn">{erro}</EmptyState>
          </div>
        )}
        {aviso && (
          <div className="mb-3">
            <EmptyState>{aviso}</EmptyState>
          </div>
        )}

        {/* -------------------------------------------------------- templates */}
        <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Sparkles size={14} className="text-teal-300" />
            <span className="font-semibold text-foreground">Templates de regras</span>
            <span>— aplicar liga só as regras do conjunto; guardar cria um novo a partir das ativas.</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {estado.templates.map((template) => (
              <div
                key={template.id}
                className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs"
                title={template.descricao ?? undefined}
              >
                <span className="font-semibold">{template.nome}</span>
                <Chip>{template.regras?.length ?? 0} regras</Chip>
                {template.origem === "predefinido" && <Chip tone="teal">predefinido</Chip>}
                <button
                  onClick={() => void executar(() => applyPadroesTemplate(template.id), `Template «${template.nome}» aplicado.`)}
                  disabled={aGuardar}
                  className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-2 py-0.5 text-teal-200 transition hover:bg-teal-400/20 disabled:opacity-50"
                >
                  aplicar
                </button>
                <button
                  onClick={() => void executar(() => deletePadroesTemplate(template.id), `Template «${template.nome}» apagado.`, false)}
                  disabled={aGuardar}
                  className="text-muted-foreground transition hover:text-rose-300 disabled:opacity-50"
                  title="Apagar template"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            {estado.templates.length === 0 && <span className="text-xs text-muted-foreground">Sem templates guardados.</span>}
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="flex min-w-0 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>Guardar as regras ativas como template</span>
              <input
                value={templateNome}
                onChange={(event) => setTemplateNome(event.target.value)}
                placeholder="nome do template"
                className="w-52 rounded-xl border border-white/10 bg-black/30 px-3 py-1.5 text-sm normal-case tracking-normal text-foreground"
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>Descrição (opcional)</span>
              <input
                value={templateDescricao}
                onChange={(event) => setTemplateDescricao(event.target.value)}
                placeholder="para que serve este conjunto"
                className="w-64 rounded-xl border border-white/10 bg-black/30 px-3 py-1.5 text-sm normal-case tracking-normal text-foreground"
              />
            </label>
            <button
              onClick={() => {
                const nome = templateNome.trim();
                if (nome.length < 2) {
                  setErro("Dê um nome ao template (mínimo 2 caracteres).");
                  return;
                }
                void executar(
                  () => savePadroesTemplate({ nome, descricao: templateDescricao }),
                  `Template «${nome}» guardado.`,
                  false,
                );
                setTemplateNome("");
                setTemplateDescricao("");
              }}
              disabled={aGuardar}
              className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-50"
            >
              <Save size={13} /> Guardar template
            </button>
          </div>
        </div>

        {/* ------------------------------------------------------------ formulário */}
        {form && (
          <div className="mb-4 rounded-xl border border-teal-400/25 bg-teal-400/5 p-3">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold">{form.id ? "Editar regra" : "Nova regra"}</span>
              <button onClick={() => setForm(null)} className="text-muted-foreground hover:text-foreground">
                <X size={15} />
              </button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground lg:col-span-2">
                <span>Nome da regra</span>
                <input
                  value={form.label}
                  onChange={(event) => setForm({ ...form, label: event.target.value })}
                  placeholder="ex.: Grande contrato sem concurso"
                  className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground"
                />
              </label>
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                <span>Severidade</span>
                <select
                  value={form.severidade}
                  onChange={(event) => setForm({ ...form, severidade: event.target.value })}
                  className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground"
                >
                  {estado.severidades.map((severidade) => (
                    <option key={severidade.id} value={severidade.id}>
                      {severidade.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                <span>Condições</span>
                <select
                  value={form.modo}
                  onChange={(event) => setForm({ ...form, modo: event.target.value as "todas" | "alguma" })}
                  className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground"
                >
                  <option value="todas">todas (E)</option>
                  <option value="alguma">alguma (OU)</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground lg:col-span-3">
                <span>Descrição</span>
                <input
                  value={form.descricao}
                  onChange={(event) => setForm({ ...form, descricao: event.target.value })}
                  placeholder="porque é que este sinal importa"
                  className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground"
                />
              </label>
              <label className="flex items-end gap-2 pb-1 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.ativo}
                  onChange={(event) => setForm({ ...form, ativo: event.target.checked })}
                  className="accent-teal-400"
                />
                ativa
              </label>
            </div>

            <div className="mt-3 space-y-2">
              {form.condicoes.map((condicao, index) => {
                const definicao = campos.find((campo) => campo.id === condicao.campo);
                const numericos = campos.filter((campo) => campo.tipo === "numero");
                return (
                  <div key={index} className="flex flex-wrap items-end gap-2 rounded-lg border border-white/10 bg-black/20 p-2">
                    <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <span>Campo {index + 1}</span>
                      <select
                        value={condicao.campo}
                        onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, campo: event.target.value } : item)) })}
                        className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                      >
                        {campos.map((campo) => (
                          <option key={campo.id} value={campo.id}>
                            {campo.label}
                            {campo.escopo === "cpv" ? " (CPV)" : campo.escopo === "global" ? " (global)" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex w-36 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <span>Operador</span>
                      <select
                        value={condicao.operador}
                        onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, operador: event.target.value } : item)) })}
                        className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                      >
                        {operadores
                          .filter((operador) => operador.tipos.includes(definicao?.tipo ?? "numero"))
                          .map((operador) => (
                            <option key={operador.id} value={operador.id}>
                              {operador.label}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="flex w-40 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      <span>Comparar com</span>
                      <select
                        value={condicao.tipoValor}
                        onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, tipoValor: event.target.value as "fixo" | "campo" } : item)) })}
                        className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                      >
                        <option value="fixo">valor fixo</option>
                        <option value="campo" disabled={definicao?.tipo !== "numero"}>
                          outro campo
                        </option>
                      </select>
                    </label>
                    {condicao.tipoValor === "fixo" ? (
                      <label className="flex w-40 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                        <span>Valor {definicao?.unidade ? `(${definicao.unidade})` : ""}</span>
                        <input
                          value={condicao.valor}
                          onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, valor: event.target.value } : item)) })}
                          placeholder={definicao?.tipo === "texto" ? "texto" : "0"}
                          className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                        />
                      </label>
                    ) : (
                      <>
                        <label className="flex w-48 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                          <span>Campo de referência</span>
                          <select
                            value={condicao.campoRef}
                            onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, campoRef: event.target.value } : item)) })}
                            className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                          >
                            {numericos.map((campo) => (
                              <option key={campo.id} value={campo.id}>
                                {campo.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex w-24 flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                          <span>Fator</span>
                          <input
                            value={condicao.fator}
                            onChange={(event) => setForm({ ...form, condicoes: form.condicoes.map((item, i) => (i === index ? { ...item, fator: event.target.value } : item)) })}
                            className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs normal-case tracking-normal text-foreground"
                          />
                        </label>
                      </>
                    )}
                    <button
                      onClick={() =>
                        setForm({
                          ...form,
                          condicoes: form.condicoes.length > 1 ? form.condicoes.filter((_, i) => i !== index) : form.condicoes,
                        })
                      }
                      className="mb-0.5 text-muted-foreground transition hover:text-rose-300"
                      title="Remover condição"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                );
              })}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => setForm({ ...form, condicoes: [...form.condicoes, condicaoVazia(campos)] })}
                  className="flex items-center gap-1.5 rounded-xl glass-card px-3 py-1.5 text-xs transition hover:bg-white/5"
                >
                  <Plus size={13} /> Adicionar condição
                </button>
                <button
                  onClick={() => void guardarForm()}
                  disabled={aGuardar || form.label.trim().length < 2}
                  className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-teal-400/90 to-sky-500/90 px-3 py-1.5 text-xs font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
                >
                  {aGuardar ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Guardar regra
                </button>
              </div>
            </div>
          </div>
        )}

        {/* -------------------------------------------------------- lista de regras */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-3">Ativa</th>
                <th className="py-2 pr-3">Regra</th>
                <th className="py-2 pr-3">Condição</th>
                <th className="py-2 pr-3 text-right">Contratos</th>
                <th className="py-2 text-right">Ações</th>
              </tr>
            </thead>
            <tbody>
              {estado.regras.map((regra) => (
                  <tr key={regra.id} className="border-t border-white/5 align-top">
                    <td className="py-2 pr-3">
                      <button
                        onClick={() => void executar(() => togglePadroesRegra(regra.id), regra.ativo ? "Regra desligada." : "Regra ligada.")}
                        disabled={aGuardar}
                        className={`h-4 w-8 rounded-full ${regra.ativo ? "bg-teal-400/70" : "bg-white/15"} relative transition disabled:opacity-50`}
                        title={regra.ativo ? "Desligar" : "Ligar"}
                      >
                        <span
                          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${regra.ativo ? "left-4" : "left-0.5"}`}
                        />
                      </button>
                    </td>
                    <td className="w-[280px] py-2 pr-3 text-xs">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold">{regra.label}</span>
                        <Chip tone={SEVERIDADE_TONE[regra.severidade] ?? "neutral"}>{regra.severidade}</Chip>
                        {regra.origem === "predefinida" && <Chip>predefinida</Chip>}
                      </div>
                      {regra.descricao && <p className="mt-0.5 text-[11px] text-muted-foreground">{regra.descricao}</p>}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-muted-foreground">
                      {(regra.modo === "alguma" ? " OU " : " E ").length > 0 &&
                        regra.condicoes
                          .map((condicao) => {
                            const campo = campos.find((item) => item.id === condicao.campo);
                            const referencia = condicao.valor && typeof condicao.valor === "object" ? condicao.valor : null;
                            const alvo = referencia
                              ? `${referencia.fator && referencia.fator !== 1 ? `${referencia.fator}×` : ""}${campos.find((item) => item.id === referencia.campo)?.label ?? referencia.campo}`
                              : String(condicao.valor);
                            return `${campo?.label ?? condicao.campo} ${condicao.operador} ${alvo}`;
                          })
                          .join(regra.modo === "alguma" ? " OU " : " E ")}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">
                      {regra.ativo ? formatNumber(contagens.get(regra.id) ?? 0) : "—"}
                    </td>
                    <td className="whitespace-nowrap py-2 text-right">
                      <div className="flex items-center justify-end gap-2 text-muted-foreground">
                        <button
                          onClick={() => setForm(paraForm(regra, campos))}
                          className="transition hover:text-teal-200"
                          title="Editar"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => void executar(() => duplicatePadroesRegra(regra.id), "Regra duplicada.", false)}
                          disabled={aGuardar}
                          className="transition hover:text-sky-200 disabled:opacity-50"
                          title="Duplicar"
                        >
                          <Copy size={14} />
                        </button>
                        <button
                          onClick={() => void executar(() => deletePadroesRegra(regra.id), "Regra apagada.")}
                          disabled={aGuardar}
                          className="transition hover:text-rose-300 disabled:opacity-50"
                          title="Apagar"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* --------------------------------------------------- contratos apanhados */}
      <SectionCard
        icon={ShieldAlert}
        title="Contratos apanhados pelas regras"
        subtitle="Independente dos modelos: basta cumprir uma regra ativa. O detalhe mostra a condição e o valor que a disparou."
        actions={
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
              {formatNumber(Math.min(hits.length, limiteHits))} de {formatNumber(hits.length)}
            </span>
            <select
              value={filtroSeveridade}
              onChange={(event) => setFiltroSeveridade(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-xs"
            >
              <option value="">todas as severidades</option>
              <option value="alerta">só alertas</option>
              <option value="aviso">só avisos</option>
              <option value="info">só informação</option>
            </select>
            <select
              value={filtroRegra}
              onChange={(event) => setFiltroRegra(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-xs"
            >
              <option value="">todas as regras</option>
              {(analysis?.regras?.ativas ?? []).map((regra) => (
                <option key={regra.id} value={regra.id}>
                  {regra.label}
                </option>
              ))}
            </select>
            <select
              value={limiteHits}
              onChange={(event) => setLimiteHits(Number(event.target.value))}
              className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-xs"
            >
              {[10, 25, 50, 100, 300].map((valor) => (
                <option key={valor} value={valor}>
                  {valor} linhas
                </option>
              ))}
            </select>
          </div>
        }
      >
        {hits.length === 0 ? (
          <EmptyState>
            Nenhum contrato cumpre as regras ativas nesta amostra. Ligue mais regras, alargue a amostra ou afrouxe os
            limites das condições.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-sm">
              <thead>
                <tr className="whitespace-nowrap text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">Severidade</th>
                  <th className="py-2 pr-3">Ano</th>
                  <th className="py-2 pr-3">Objeto</th>
                  <th className="py-2 pr-3">Adjudicatária</th>
                  <th className="py-2 pr-3 text-right">Valor</th>
                  <th className="py-2">Regras cumpridas</th>
                </tr>
              </thead>
              <tbody>
                {hits.slice(0, limiteHits).map((item, index) => (
                  <tr key={`${item.id ?? index}`} className="border-t border-white/5 align-top">
                    <td className="py-2 pr-3">
                      <Chip tone={SEVERIDADE_TONE[item.severidade ?? ""] ?? "neutral"}>{item.severidade ?? "—"}</Chip>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-xs">{item.ano ?? "—"}</td>
                    <td className="w-[300px] py-2 pr-3 text-xs">
                      <div className="line-clamp-2">{item.objeto || "—"}</div>
                      <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                        CPV {item.cpv ?? "—"} · {item.procedimento ?? "—"}
                      </div>
                    </td>
                    <td className="w-[170px] py-2 pr-3 text-xs">{item.adjudicataria ?? "—"}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right text-xs">{formatCompactEuro(item.valor)}</td>
                    <td className="w-[360px] py-2 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {(item.rotulos ?? []).slice(0, 4).map((rotulo, posicao) => (
                          <Chip
                            key={`${rotulo}-${posicao}`}
                            tone={padraoTone((item.regras ?? [])[posicao] ?? "")}
                            title={(item.detalhes ?? [])[posicao] ?? undefined}
                          >
                            {rotulo}
                          </Chip>
                        ))}
                        {(item.rotulos ?? []).length > 4 && (
                          <Chip title={(item.detalhes ?? []).slice(4).join(" · ")}>+{(item.rotulos ?? []).length - 4}</Chip>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* ------------------------------------------------- padrões não avaliáveis */}
      <SectionCard
        icon={Info}
        title="Padrões que não se expressam por regra"
        subtitle="Dependem de modelos, do grafo de relações ou de notícias — aparecem sempre que o motor corre."
      >
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {estado.padroes_nao_avaliaveis.map((padrao) => (
            <div key={padrao.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{padrao.label}</span>
                <Chip>{padrao.tipo}</Chip>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">{padrao.descricao}</p>
              <p className="mt-1 font-mono text-[10px] text-muted-foreground/80">{padrao.metodo}</p>
            </div>
          ))}
        </div>
        <div className="mt-3">
          <EmptyState>
            <AlertTriangle size={12} className="mr-1 inline" />
            Uma regra é uma hipótese de trabalho: servir para priorizar inspeção, não prova de ilícito.
          </EmptyState>
        </div>
      </SectionCard>
    </div>
  );
}
