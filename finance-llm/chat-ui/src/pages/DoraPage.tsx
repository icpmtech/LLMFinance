/**
 * **DORA · Resiliência Operacional Digital** — Register of Information,
 * incidentes ICT, riscos ICT, workflows de conformidade, relatórios ITS/RTS e
 * conteúdo original/traduzido da EIOPA.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  FileText,
  Filter,
  Globe2,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import type {
  DoraConteudoIdioma,
  DoraIncidente,
  DoraMeta,
  DoraRegistoItem,
  DoraRelatorio,
  DoraRisco,
  DoraWorkflow,
} from "../doraApi";
import {
  generateDoraRelatorio,
  getDoraMeta,
  ingestDoraConteudo,
  saveDoraIncidente,
  saveDoraRegisto,
  saveDoraRisco,
  saveDoraWorkflow,
  searchDoraConteudo,
  searchDoraIncidentes,
  searchDoraRegisto,
  searchDoraRelatorios,
  searchDoraRiscos,
  searchDoraWorkflows,
} from "../doraApi";
import { EmptyState, FilterField, Loading, SearchInput, SectionCard } from "../components/padroes/padroesKit";

type Aba = "painel" | "registo" | "incidentes" | "riscos" | "workflows" | "relatorios" | "conteudo";

const ABAS: { id: Aba; label: string; icon: typeof BookOpen }[] = [
  { id: "painel", label: "Painel", icon: ShieldCheck },
  { id: "registo", label: "Register of Information", icon: Layers },
  { id: "incidentes", label: "Incidentes ICT", icon: AlertTriangle },
  { id: "riscos", label: "Riscos ICT", icon: ShieldAlert },
  { id: "workflows", label: "Automações", icon: Workflow },
  { id: "relatorios", label: "Relatórios ITS/RTS", icon: FileText },
  { id: "conteudo", label: "Conteúdo EIOPA", icon: BookOpen },
];

function useDoraMeta() {
  const [meta, setMeta] = useState<DoraMeta | null>(null);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getDoraMeta()
      .then(setMeta)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível carregar o módulo DORA."))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  return { meta, erro, carregando, recarregar: carregar };
}

function IdiomaSwitch({ idioma, setIdioma }: { idioma: "pt" | "en"; setIdioma: (v: "pt" | "en") => void }) {
  return (
    <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-black/30 p-1">
      {(["pt", "en"] as const).map((v) => (
        <button
          key={v}
          onClick={() => setIdioma(v)}
          className={`rounded-md px-2 py-1 text-xs ${idioma === v ? "bg-teal-500/20 text-teal-200" : "text-muted-foreground hover:text-foreground"}`}
        >
          {v.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function PainelTab({ meta }: { meta: DoraMeta | null }) {
  const pt = meta?.conteudo?.pt;
  const pilares = pt?.pilares ?? [];
  return (
    <div className="space-y-4">
      <SectionCard title="Sobre o DORA" subtitle="Resiliência operacional digital do setor financeiro" icon={ShieldCheck}>
        <div className="space-y-3 text-sm leading-relaxed text-foreground/90">
          <p>{pt?.introducao}</p>
          <p className="text-muted-foreground">{pt?.porque}</p>
        </div>
      </SectionCard>

      <SectionCard title="Pilares regulatórios" subtitle="Áreas cobertas pelo DORA" icon={Layers}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {pilares.map((p) => (
            <div key={p.id} className="glass-card rounded-xl p-4">
              <h3 className="mb-1 text-sm font-medium">{p.titulo}</h3>
              <p className="text-xs text-muted-foreground">{p.descricao}</p>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function RegisterTab() {
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState<"" | DoraRegistoItem["tipo"]>("");
  const [items, setItems] = useState<DoraRegistoItem[]>([]);
  const [total, setTotal] = useState(0);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [modal, setModal] = useState<DoraRegistoItem | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    searchDoraRegisto({ q: q || undefined, tipo: tipo || undefined, size: 50 })
      .then((res) => {
        setItems(res.items as DoraRegistoItem[]);
        setTotal(res.total);
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Erro ao pesquisar registo."))
      .finally(() => setCarregando(false));
  }, [q, tipo]);

  useEffect(() => {
    carregar();
  }, [carregando]);

  const guardar = async (item: DoraRegistoItem) => {
    try {
      await saveDoraRegisto(item);
      setModal(null);
      carregar();
    } catch (exc) {
      setErro(exc instanceof Error ? exc.message : "Erro ao guardar.");
    }
  };

  return (
    <SectionCard
      title="Register of Information"
      subtitle="Entidades, funções de negócio, sistemas, fornecedores e contratos"
      icon={Layers}
      actions={
        <button
          onClick={() => setModal({ tipo: "entidade", nome: "" })}
          className="flex items-center gap-1 rounded-lg bg-teal-500/20 px-3 py-1.5 text-xs text-teal-200 hover:bg-teal-500/30"
        >
          <Plus size={14} /> Novo
        </button>
      }
    >
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[200px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar registo..." />
        </div>
        <FilterField label="Tipo">
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as DoraRegistoItem["tipo"])}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none"
          >
            <option value="">Todos</option>
            <option value="entidade">Entidade</option>
            <option value="funcao">Função de negócio</option>
            <option value="sistema">Sistema</option>
            <option value="fornecedor">Fornecedor ICT</option>
            <option value="contrato">Contrato</option>
          </select>
        </FilterField>
        <button
          onClick={carregar}
          disabled={carregando}
          className="self-end rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      {erro && <EmptyState tone="warn">{erro}</EmptyState>}

      <div className="space-y-2">
        {items.map((item) => (
          <button
            key={`${item.tipo}-${item.id}`}
            onClick={() => setModal(item)}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-left transition hover:border-teal-400/30 hover:bg-teal-400/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.nome}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {item.tipo} {item.entidade_nome ? `· ${item.entidade_nome}` : ""}
              </p>
            </div>
            <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] uppercase text-muted-foreground">
              {item.tipo}
            </span>
          </button>
        ))}
        {!carregando && items.length === 0 && !erro && <EmptyState>Nenhum item encontrado.</EmptyState>}
        {carregando && <Loading label="A carregar registo..." />}
      </div>

      {modal && (
        <RegistoModal item={modal} onClose={() => setModal(null)} onSave={guardar} />
      )}
    </SectionCard>
  );
}

function RegistoModal({
  item,
  onClose,
  onSave,
}: {
  item: DoraRegistoItem;
  onClose: () => void;
  onSave: (i: DoraRegistoItem) => void;
}) {
  const [form, setForm] = useState<DoraRegistoItem>(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0b0f19] p-5">
        <h3 className="mb-4 text-base font-semibold">{item.id ? "Editar item" : "Novo item"}</h3>
        <div className="space-y-3">
          <FilterField label="Tipo">
            <select
              value={form.tipo}
              onChange={(e) => setForm({ ...form, tipo: e.target.value as DoraRegistoItem["tipo"] })}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            >
              <option value="entidade">Entidade</option>
              <option value="funcao">Função de negócio</option>
              <option value="sistema">Sistema</option>
              <option value="fornecedor">Fornecedor ICT</option>
              <option value="contrato">Contrato</option>
            </select>
          </FilterField>
          <FilterField label="Nome">
            <input
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
          <FilterField label="Descrição">
            <textarea
              value={form.descricao || ""}
              onChange={(e) => setForm({ ...form, descricao: e.target.value })}
              rows={3}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Cancelar</button>
          <button
            onClick={() => onSave(form)}
            className="rounded-lg bg-teal-500/20 px-4 py-2 text-sm text-teal-200 hover:bg-teal-500/30"
          >
            Guardar
          </button>
        </div>
      </div>
    </div>
  );
}

function IncidentesTab() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<DoraIncidente[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [modal, setModal] = useState<DoraIncidente | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    searchDoraIncidentes({ q: q || undefined, size: 50 })
      .then((res) => setItems(res.items as DoraIncidente[]))
      .finally(() => setCarregando(false));
  }, [q]);

  useEffect(() => {
    carregar();
  }, [carregando]);

  const guardar = async (item: DoraIncidente) => {
    await saveDoraIncidente(item);
    setModal(null);
    carregar();
  };

  return (
    <SectionCard
      title="Incidentes ICT"
      subtitle="Reporte e classificação de incidentes significativos"
      icon={AlertTriangle}
      actions={
        <button
          onClick={() => setModal({ titulo: "", severidade: "medio", estado: "aberto" })}
          className="flex items-center gap-1 rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-500/30"
        >
          <Plus size={14} /> Novo
        </button>
      }
    >
      <div className="mb-4 flex gap-3">
        <div className="min-w-[240px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar incidentes..." />
        </div>
        <button onClick={carregar} className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => setModal(item)}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-left transition hover:border-amber-400/30 hover:bg-amber-400/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.titulo}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {item.estado} · {item.severidade} {item.sistema ? `· ${item.sistema}` : ""}
              </p>
            </div>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase ${
                item.severidade === "critico"
                  ? "bg-rose-500/20 text-rose-200"
                  : item.severidade === "alto"
                    ? "bg-amber-500/20 text-amber-200"
                    : "bg-sky-500/20 text-sky-200"
              }`}
            >
              {item.severidade}
            </span>
          </button>
        ))}
        {!carregando && items.length === 0 && <EmptyState>Nenhum incidente registado.</EmptyState>}
        {carregando && <Loading label="A carregar incidentes..." />}
      </div>
      {modal && <IncidenteModal item={modal} onClose={() => setModal(null)} onSave={guardar} />}
    </SectionCard>
  );
}

function IncidenteModal({
  item,
  onClose,
  onSave,
}: {
  item: DoraIncidente;
  onClose: () => void;
  onSave: (i: DoraIncidente) => void;
}) {
  const [form, setForm] = useState<DoraIncidente>(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0b0f19] p-5">
        <h3 className="mb-4 text-base font-semibold">{item.id ? "Editar incidente" : "Novo incidente"}</h3>
        <div className="space-y-3">
          <FilterField label="Título">
            <input value={form.titulo} onChange={(e) => setForm({ ...form, titulo: e.target.value })} className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm" />
          </FilterField>
          <div className="grid grid-cols-2 gap-3">
            <FilterField label="Severidade">
              <select
                value={form.severidade}
                onChange={(e) => setForm({ ...form, severidade: e.target.value as DoraIncidente["severidade"] })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              >
                <option value="critico">Crítico</option>
                <option value="alto">Alto</option>
                <option value="medio">Médio</option>
                <option value="baixo">Baixo</option>
                <option value="informacao">Informação</option>
              </select>
            </FilterField>
            <FilterField label="Estado">
              <select
                value={form.estado}
                onChange={(e) => setForm({ ...form, estado: e.target.value as DoraIncidente["estado"] })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              >
                <option value="aberto">Aberto</option>
                <option value="em_analise">Em análise</option>
                <option value="contido">Contido</option>
                <option value="resolvido">Resolvido</option>
                <option value="fechado">Fechado</option>
              </select>
            </FilterField>
          </div>
          <FilterField label="Descrição">
            <textarea
              value={form.descricao || ""}
              onChange={(e) => setForm({ ...form, descricao: e.target.value })}
              rows={3}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Cancelar</button>
          <button onClick={() => onSave(form)} className="rounded-lg bg-amber-500/20 px-4 py-2 text-sm text-amber-200 hover:bg-amber-500/30">Guardar</button>
        </div>
      </div>
    </div>
  );
}

function RiscosTab() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<DoraRisco[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [modal, setModal] = useState<DoraRisco | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    searchDoraRiscos({ q: q || undefined, size: 50 })
      .then((res) => setItems(res.items as DoraRisco[]))
      .finally(() => setCarregando(false));
  }, [q]);

  useEffect(() => {
    carregar();
  }, [carregando]);

  const guardar = async (item: DoraRisco) => {
    await saveDoraRisco(item);
    setModal(null);
    carregar();
  };

  return (
    <SectionCard
      title="Riscos ICT"
      subtitle="Gestão de riscos operacionais digitais"
      icon={ShieldAlert}
      actions={
        <button
          onClick={() => setModal({ nome: "", impacto: "medio", probabilidade: "possivel" })}
          className="flex items-center gap-1 rounded-lg bg-rose-500/20 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/30"
        >
          <Plus size={14} /> Novo
        </button>
      }
    >
      <div className="mb-4 flex gap-3">
        <div className="min-w-[240px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar riscos..." />
        </div>
        <button onClick={carregar} className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => setModal(item)}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-left transition hover:border-rose-400/30 hover:bg-rose-400/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.nome}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                impacto {item.impacto} · probabilidade {item.probabilidade}
              </p>
            </div>
          </button>
        ))}
        {!carregando && items.length === 0 && <EmptyState>Nenhum risco registado.</EmptyState>}
        {carregando && <Loading label="A carregar riscos..." />}
      </div>
      {modal && <RiscoModal item={modal} onClose={() => setModal(null)} onSave={guardar} />}
    </SectionCard>
  );
}

function RiscoModal({
  item,
  onClose,
  onSave,
}: {
  item: DoraRisco;
  onClose: () => void;
  onSave: (i: DoraRisco) => void;
}) {
  const [form, setForm] = useState<DoraRisco>(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0b0f19] p-5">
        <h3 className="mb-4 text-base font-semibold">{item.id ? "Editar risco" : "Novo risco"}</h3>
        <div className="space-y-3">
          <FilterField label="Nome">
            <input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm" />
          </FilterField>
          <div className="grid grid-cols-2 gap-3">
            <FilterField label="Impacto">
              <select
                value={form.impacto}
                onChange={(e) => setForm({ ...form, impacto: e.target.value as DoraRisco["impacto"] })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              >
                <option value="critico">Crítico</option>
                <option value="alto">Alto</option>
                <option value="medio">Médio</option>
                <option value="baixo">Baixo</option>
              </select>
            </FilterField>
            <FilterField label="Probabilidade">
              <select
                value={form.probabilidade}
                onChange={(e) => setForm({ ...form, probabilidade: e.target.value as DoraRisco["probabilidade"] })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              >
                <option value="quase_certo">Quase certo</option>
                <option value="provavel">Provável</option>
                <option value="possivel">Possível</option>
                <option value="improvavel">Improvável</option>
                <option value="raro">Raro</option>
              </select>
            </FilterField>
          </div>
          <FilterField label="Mitigação">
            <textarea
              value={form.mitigacao || ""}
              onChange={(e) => setForm({ ...form, mitigacao: e.target.value })}
              rows={3}
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
            />
          </FilterField>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Cancelar</button>
          <button onClick={() => onSave(form)} className="rounded-lg bg-rose-500/20 px-4 py-2 text-sm text-rose-200 hover:bg-rose-500/30">Guardar</button>
        </div>
      </div>
    </div>
  );
}

function WorkflowsTab() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<DoraWorkflow[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [modal, setModal] = useState<DoraWorkflow | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    searchDoraWorkflows({ q: q || undefined, size: 50 })
      .then((res) => setItems(res.items as DoraWorkflow[]))
      .finally(() => setCarregando(false));
  }, [q]);

  useEffect(() => {
    carregar();
  }, [carregando]);

  const guardar = async (item: DoraWorkflow) => {
    await saveDoraWorkflow(item);
    setModal(null);
    carregar();
  };

  return (
    <SectionCard
      title="Automações"
      subtitle="Workflows para ciclos de conformidade DORA"
      icon={Workflow}
      actions={
        <button
          onClick={() => setModal({ nome: "", ativo: true, trigger: "manual", acao: "notificar" })}
          className="flex items-center gap-1 rounded-lg bg-violet-500/20 px-3 py-1.5 text-xs text-violet-200 hover:bg-violet-500/30"
        >
          <Plus size={14} /> Novo
        </button>
      }
    >
      <div className="mb-4 flex gap-3">
        <div className="min-w-[240px] flex-1">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar workflows..." />
        </div>
        <button onClick={carregar} className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => setModal(item)}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-left transition hover:border-violet-400/30 hover:bg-violet-400/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.nome}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {item.trigger} → {item.acao} {item.ativo ? "· ativo" : "· inativo"}
              </p>
            </div>
          </button>
        ))}
        {!carregando && items.length === 0 && <EmptyState>Nenhum workflow configurado.</EmptyState>}
        {carregando && <Loading label="A carregar workflows..." />}
      </div>
      {modal && <WorkflowModal item={modal} onClose={() => setModal(null)} onSave={guardar} />}
    </SectionCard>
  );
}

function WorkflowModal({
  item,
  onClose,
  onSave,
}: {
  item: DoraWorkflow;
  onClose: () => void;
  onSave: (i: DoraWorkflow) => void;
}) {
  const [form, setForm] = useState<DoraWorkflow>(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0b0f19] p-5">
        <h3 className="mb-4 text-base font-semibold">{item.id ? "Editar workflow" : "Novo workflow"}</h3>
        <div className="space-y-3">
          <FilterField label="Nome">
            <input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm" />
          </FilterField>
          <div className="grid grid-cols-2 gap-3">
            <FilterField label="Trigger">
              <input
                value={form.trigger || ""}
                onChange={(e) => setForm({ ...form, trigger: e.target.value })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </FilterField>
            <FilterField label="Ação">
              <input
                value={form.acao || ""}
                onChange={(e) => setForm({ ...form, acao: e.target.value })}
                className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              />
            </FilterField>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.ativo}
              onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
              className="rounded border-white/20"
            />
            Ativo
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Cancelar</button>
          <button onClick={() => onSave(form)} className="rounded-lg bg-violet-500/20 px-4 py-2 text-sm text-violet-200 hover:bg-violet-500/30">Guardar</button>
        </div>
      </div>
    </div>
  );
}

function RelatoriosTab() {
  const [items, setItems] = useState<DoraRelatorio[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [gerando, setGerando] = useState(false);

  const carregar = useCallback(() => {
    setCarregando(true);
    searchDoraRelatorios({ size: 50 })
      .then((res) => setItems(res.items as DoraRelatorio[]))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregando]);

  const gerar = async () => {
    setGerando(true);
    try {
      await generateDoraRelatorio({
        tipo: "register-of-information",
        entidade_id: "demo",
        nome: "Relatório Register of Information",
        formato: "json",
      });
      carregar();
    } finally {
      setGerando(false);
    }
  };

  return (
    <SectionCard
      title="Relatórios ITS/RTS"
      subtitle="Relatórios de conformidade gerados a partir do registo"
      icon={FileText}
      actions={
        <button
          onClick={gerar}
          disabled={gerando}
          className="flex items-center gap-1 rounded-lg bg-sky-500/20 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
        >
          {gerando ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          Gerar relatório
        </button>
      }
    >
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{item.nome}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {item.tipo} · {item.formato} · {new Date(item.created_at).toLocaleDateString("pt-PT")}
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] text-sky-200">
              {item.formato}
            </span>
          </div>
        ))}
        {!carregando && items.length === 0 && <EmptyState>Nenhum relatório gerado.</EmptyState>}
        {carregando && <Loading label="A carregar relatórios..." />}
      </div>
    </SectionCard>
  );
}

function ConteudoTab({ conteudo }: { conteudo: DoraConteudo | undefined }) {
  const [idioma, setIdioma] = useState<"pt" | "en">("pt");
  const [q, setQ] = useState("");
  const [resultados, setResultados] = useState<Record<string, unknown>[]>([]);
  const [carregando, setCarregando] = useState(false);

  const pesquisar = useCallback(() => {
    if (!q.trim()) {
      setResultados([]);
      return;
    }
    setCarregando(true);
    searchDoraConteudo({ q, idioma, size: 20 })
      .then((res) => setResultados(res.items))
      .finally(() => setCarregando(false));
  }, [q, idioma]);

  useEffect(() => {
    pesquisar();
  }, [pesquisar]);

  const c = conteudo?.[idioma];
  return (
    <div className="space-y-4">
      <SectionCard title="Conteúdo EIOPA" subtitle="Original e tradução PT do portal DORA" icon={BookOpen} actions={<IdiomaSwitch idioma={idioma} setIdioma={setIdioma} />}>
        <div className="mb-4">
          <SearchInput value={q} onChange={setQ} placeholder="Pesquisar no conteúdo DORA..." />
        </div>

        {resultados.length > 0 && (
          <div className="mb-4 space-y-2">
            {resultados.map((r, i) => (
              <div key={i} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <p className="text-sm font-medium">{String(r.titulo || "")}</p>
                <p className="text-[11px] text-muted-foreground">{String(r.texto || "").slice(0, 200)}…</p>
              </div>
            ))}
            {carregando && <Loading label="A pesquisar..." />}
          </div>
        )}

        <div className="space-y-4 text-sm leading-relaxed">
          <p>{c?.introducao}</p>
          <p className="text-muted-foreground">{c?.porque}</p>
          <p className="text-muted-foreground">{c?.oversight}</p>
        </div>

        <div className="mt-5">
          <h4 className="mb-2 text-sm font-medium">Pilares regulatórios</h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {c?.pilares.map((p) => (
              <div key={p.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <p className="text-sm font-medium">{p.titulo}</p>
                <p className="text-[11px] text-muted-foreground">{p.descricao}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5">
          <h4 className="mb-2 text-sm font-medium">Provisões legais (nível 2)</h4>
          <ul className="space-y-1 text-xs">
            {c?.provisoes_legais.nivel_2.map((p, i) => (
              <li key={i}>
                <a href={p.url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                  {p.titulo}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </SectionCard>
    </div>
  );
}

export default function DoraPage() {
  const [tab, setTab] = useState<Aba>("painel");
  const { meta, erro, carregando, recarregar } = useDoraMeta();

  return (
    <div className="@container min-h-screen w-full bg-background text-foreground orbit-bg">
      <div className="mx-auto max-w-[1500px] px-4 py-6 @2xl:px-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <ShieldCheck size={24} className="text-sky-300" />
              DORA · Resiliência Operacional Digital
            </h1>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Register of Information, gestão de incidentes e riscos ICT, workflows de conformidade,
              relatórios alinhados com RTS/ITS e conteúdo original/traduzido da EIOPA.
            </p>
          </div>
          <button
            onClick={recarregar}
            disabled={carregando}
            className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {carregando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          </button>
        </header>

        <nav className="mb-5 flex flex-wrap gap-1 rounded-xl border border-white/10 bg-black/30 p-1">
          {ABAS.map((a) => (
            <button
              key={a.id}
              onClick={() => setTab(a.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition ${
                tab === a.id ? "bg-teal-500/20 text-teal-200" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <a.icon size={14} />
              {a.label}
            </button>
          ))}
        </nav>

        {erro && <EmptyState tone="warn">{erro}</EmptyState>}
        {carregando && !meta && <Loading label="A carregar módulo DORA..." />}

        {tab === "painel" && <PainelTab meta={meta} />}
        {tab === "registo" && <RegisterTab />}
        {tab === "incidentes" && <IncidentesTab />}
        {tab === "riscos" && <RiscosTab />}
        {tab === "workflows" && <WorkflowsTab />}
        {tab === "relatorios" && <RelatoriosTab />}
        {tab === "conteudo" && <ConteudoTab conteudo={meta?.conteudo} />}
      </div>
    </div>
  );
}
