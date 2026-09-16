import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Building2, FileSearch, Map, Network, RefreshCw, Search, Share2 } from "lucide-react";
import { getContract, getContractAnalytics, getContractNetwork, getContractRegionalAnalytics, getContractRelations } from "../api";
import type { ContractAnalyticsResponse, ContractGraphResponse, ContractItem, ContractRegionalResponse, ContractRelationsResponse } from "../types";

type EmpresasIQTab = "overview" | "network" | "map" | "relations" | "contract";

const money = (value?: number) => value == null ? "—" : new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
const compact = (value?: number) => value == null ? "—" : new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 1 }).format(value);

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`glass-card rounded-2xl border border-white/10 p-5 ${className}`}>{children}</section>;
}

function Header({ tab, onTab }: { tab: EmpresasIQTab; onTab: (tab: EmpresasIQTab) => void }) {
  const tabs: { id: EmpresasIQTab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "Visão geral", icon: <Building2 size={16} /> },
    { id: "network", label: "Rede", icon: <Network size={16} /> },
    { id: "map", label: "Mapa regional", icon: <Map size={16} /> },
    { id: "relations", label: "Relações", icon: <Share2 size={16} /> },
    { id: "contract", label: "Contrato", icon: <FileSearch size={16} /> },
  ];
  return <>
    <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <p className="text-xs uppercase tracking-[0.22em] text-primary">EmpresasIQ / Contratos Públicos</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">A inteligência por trás da contratação pública.</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Explore entidades, fluxos de valor e território a partir dos contratos indexados.</p>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-emerald-400" /> Dados ligados ao Elasticsearch</div>
    </div>
    <div className="mt-7 flex gap-1 overflow-x-auto border-b border-white/10 pb-px">
      {tabs.map((item) => <button key={item.id} onClick={() => onTab(item.id)} className={`flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm transition ${tab === item.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{item.icon}{item.label}</button>)}
    </div>
  </>;
}

function Overview({ analytics, regional, onTab }: { analytics: ContractAnalyticsResponse | null; regional: ContractRegionalResponse | null; onTab: (tab: EmpresasIQTab) => void }) {
  const top = analytics?.top_entities ?? [];
  const max = Math.max(...top.map((row) => row.total_value || 0), 1);
  return <div className="space-y-5">
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[{ label: "Contratos indexados", value: compact(analytics?.total_contracts), note: "universo pesquisável" }, { label: "Valor contratual", value: money(analytics?.total_value), note: "soma publicada" }, { label: "Valor médio", value: money(analytics?.avg_value), note: "por contrato" }, { label: "Regiões NUTS", value: String(regional?.regions.length ?? "—"), note: "com atividade" }].map((item) => <Panel key={item.label} className="relative overflow-hidden"><p className="text-xs text-muted-foreground">{item.label}</p><p className="mt-3 text-2xl font-semibold stat-value">{item.value}</p><p className="mt-2 text-xs text-muted-foreground">{item.note}</p></Panel>)}
    </div>
    <div className="grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
      <Panel><div className="flex items-center justify-between"><div><h2 className="font-semibold">Entidades com maior volume</h2><p className="mt-1 text-xs text-muted-foreground">Valor agregado dos contratos</p></div><button onClick={() => onTab("relations")} className="text-xs text-primary">Ver relações <ArrowUpRight className="inline" size={14} /></button></div><div className="mt-6 space-y-4">{top.slice(0, 7).map((row) => <div key={row.key}><div className="mb-1 flex justify-between gap-4 text-sm"><span className="truncate">{row.description || row.key}</span><span className="text-muted-foreground">{money(row.total_value)}</span></div><div className="h-2 overflow-hidden rounded-full bg-white/8"><div className="h-full rounded-full bg-gradient-to-r from-teal-400 to-blue-400" style={{ width: `${Math.max(4, ((row.total_value || 0) / max) * 100)}%` }} /></div></div>)}</div></Panel>
      <Panel><div className="flex items-center justify-between"><div><h2 className="font-semibold">Pulso regional</h2><p className="mt-1 text-xs text-muted-foreground">NUTS com maior valor</p></div><button onClick={() => onTab("map")} className="text-muted-foreground hover:text-primary"><Map size={18} /></button></div><div className="mt-5 space-y-3">{(regional?.regions ?? []).slice(0, 6).map((region) => <div key={region.key} className="flex items-center justify-between rounded-xl bg-white/[0.03] px-3 py-2.5"><span className="text-sm">{region.key}</span><span className="text-sm font-medium text-primary">{money(region.total_value)}</span></div>)}</div></Panel>
    </div>
  </div>;
}

function NetworkView({ network }: { network: ContractGraphResponse | null }) {
  const nodes = network?.nodes ?? [];
  const edges = network?.edges ?? [];
  return <div className="grid gap-5 xl:grid-cols-[1fr_0.65fr]"><Panel className="min-h-[430px]"><div className="flex items-center justify-between"><div><h2 className="font-semibold">Rede de contratação</h2><p className="mt-1 text-xs text-muted-foreground">{nodes.length} entidades · {edges.length} ligações</p></div><Network className="text-primary" size={20} /></div><div className="relative mt-5 h-[330px] overflow-hidden rounded-xl border border-white/10 bg-[#07151b] p-5"><div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(rgba(65,200,180,.16) 1px, transparent 1px), linear-gradient(90deg, rgba(65,200,180,.16) 1px, transparent 1px)", backgroundSize: "34px 34px" }} />{nodes.slice(0, 18).map((node, index) => <div key={node.id} className="absolute max-w-[130px] truncate rounded-lg border px-2 py-1 text-[10px] shadow-lg" style={{ left: `${10 + ((index * 37) % 78)}%`, top: `${12 + ((index * 53) % 70)}%`, borderColor: node.type === "adjudicante" ? "rgba(45,212,191,.55)" : "rgba(96,165,250,.55)", background: node.type === "adjudicante" ? "rgba(13,87,79,.75)" : "rgba(24,63,111,.75)" }}>{node.label}</div>)}</div></Panel><Panel><h2 className="font-semibold">Ligações de maior intensidade</h2><div className="mt-5 space-y-3">{edges.slice(0, 8).map((edge) => <div key={`${edge.source}-${edge.target}`} className="rounded-xl border border-white/8 p-3"><div className="flex items-center gap-2 text-xs"><span className="truncate text-teal-300">{nodes.find((node) => node.id === edge.source)?.label || edge.source}</span><ArrowUpRight size={13} className="shrink-0 text-muted-foreground" /><span className="truncate text-blue-300">{nodes.find((node) => node.id === edge.target)?.label || edge.target}</span></div><div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>{edge.count} contratos</span><span>{money(edge.value)}</span></div></div>)}</div></Panel></div>;
}

function MapView({ regional }: { regional: ContractRegionalResponse | null }) {
  const max = Math.max(...(regional?.regions ?? []).map((row) => row.total_value || 0), 1);
  return <Panel><div className="flex items-center justify-between"><div><h2 className="font-semibold">Mapa de atividade por NUTS</h2><p className="mt-1 text-xs text-muted-foreground">Distribuição territorial dos contratos</p></div><Map className="text-primary" size={20} /></div><div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{(regional?.regions ?? []).map((region) => <div key={region.key} className="relative overflow-hidden rounded-xl border border-white/10 p-4"><div className="absolute inset-y-0 left-0 bg-teal-400/10" style={{ width: `${Math.max(8, ((region.total_value || 0) / max) * 100)}%` }} /><div className="relative flex items-end justify-between"><span className="font-medium">{region.key}</span><span className="text-xs text-muted-foreground">{region.count} contratos</span></div><p className="relative mt-5 text-xl font-semibold">{money(region.total_value)}</p></div>)}</div></Panel>;
}

function RelationsView({ relations }: { relations: ContractRelationsResponse | null }) {
  return <Panel><div className="flex items-center justify-between"><div><h2 className="font-semibold">Fluxo adjudicante → adjudicatário</h2><p className="mt-1 text-xs text-muted-foreground">Relações agregadas no universo indexado</p></div><Share2 className="text-primary" size={20} /></div><div className="mt-6 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><thead className="text-xs uppercase tracking-wider text-muted-foreground"><tr><th className="pb-3">Adjudicante</th><th className="pb-3">Adjudicatário</th><th className="pb-3 text-right">Contratos</th><th className="pb-3 text-right">Valor</th></tr></thead><tbody>{(relations?.relations ?? []).slice(0, 15).map((relation) => <tr key={`${relation.source}-${relation.target}`} className="border-t border-white/8"><td className="py-3 pr-4">{relation.source_name}</td><td className="py-3 pr-4 text-blue-300">{relation.target_name}</td><td className="py-3 text-right text-muted-foreground">{relation.count}</td><td className="py-3 text-right font-medium">{money(relation.total_value)}</td></tr>)}</tbody></table></div></Panel>;
}

function ContractView({ contract, onSearch }: { contract: ContractItem | null; onSearch: (id: string) => void }) {
  const [value, setValue] = useState("");
  return <div className="mx-auto max-w-4xl space-y-5"><Panel><div className="flex gap-2"><div className="relative flex-1"><Search className="absolute left-3 top-3 text-muted-foreground" size={17} /><input value={value} onChange={(event) => setValue(event.target.value)} placeholder="ID do contrato" className="w-full rounded-xl border border-white/10 bg-white/[0.04] py-2.5 pl-10 pr-3 text-sm outline-none focus:border-primary" /></div><button onClick={() => onSearch(value)} className="rounded-xl bg-primary px-4 text-sm font-medium text-background">Pesquisar</button></div></Panel>{contract && <Panel><p className="text-xs uppercase tracking-wider text-primary">Ficha de contrato</p><h2 className="mt-2 text-xl font-semibold">{contract.objectoContrato || "Contrato sem descrição"}</h2><div className="mt-5 grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">ID</p><p className="mt-1 text-sm">{contract.idcontrato || "—"}</p></div><div><p className="text-xs text-muted-foreground">Valor</p><p className="mt-1 font-medium">{money(contract.precoContratual)}</p></div><div><p className="text-xs text-muted-foreground">Ano</p><p className="mt-1">{contract.Ano || "—"}</p></div></div><p className="mt-5 text-sm leading-6 text-muted-foreground">{contract.descContrato || "Sem descrição adicional publicada."}</p></Panel>}</div>;
}

export default function EmpresasIQPage() {
  const [tab, setTab] = useState<EmpresasIQTab>("overview");
  const [analytics, setAnalytics] = useState<ContractAnalyticsResponse | null>(null);
  const [regional, setRegional] = useState<ContractRegionalResponse | null>(null);
  const [network, setNetwork] = useState<ContractGraphResponse | null>(null);
  const [relations, setRelations] = useState<ContractRelationsResponse | null>(null);
  const [contract, setContract] = useState<ContractItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [nextAnalytics, nextRegional, nextNetwork, nextRelations] = await Promise.all([getContractAnalytics({ top_entities: 10 }), getContractRegionalAnalytics(), getContractNetwork(), getContractRelations()]);
      setAnalytics(nextAnalytics); setRegional(nextRegional); setNetwork(nextNetwork); setRelations(nextRelations);
    } catch (err) { setError(err instanceof Error ? err.message : "Não foi possível carregar os dados."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const content = useMemo(() => {
    if (loading) return <Panel className="py-16 text-center"><RefreshCw className="mx-auto animate-spin text-primary" /><p className="mt-3 text-sm text-muted-foreground">A carregar inteligência contratual...</p></Panel>;
    if (tab === "overview") return <Overview analytics={analytics} regional={regional} onTab={setTab} />;
    if (tab === "network") return <NetworkView network={network} />;
    if (tab === "map") return <MapView regional={regional} />;
    if (tab === "relations") return <RelationsView relations={relations} />;
    return <ContractView contract={contract} onSearch={async (id) => { if (!id.trim()) return; try { setContract(await getContract(id.trim())); } catch (err) { setError(err instanceof Error ? err.message : "Contrato não encontrado."); } }} />;
  }, [analytics, contract, loading, network, regional, relations, tab]);
  return <div className="orbit-bg min-h-screen p-5 md:p-8"><div className="mx-auto max-w-[1500px]"><Header tab={tab} onTab={setTab} />{error && <div className="mt-5 rounded-xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}<div className="mt-6">{content}</div><button onClick={() => void load()} className="mt-6 flex items-center gap-2 text-xs text-muted-foreground hover:text-primary"><RefreshCw size={14} /> Atualizar dados</button></div></div>;
}
