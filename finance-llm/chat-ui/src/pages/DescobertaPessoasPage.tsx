/**
 * **Descoberta de Pessoas** — quem está por trás das empresas.
 *
 * Dão-se uma ou várias empresas (NIF ou nome) e o painel devolve **quem** nelas
 * tem cargos: órgãos sociais, capital, papéis nos processos do CIRE e a rede de
 * cada pessoa para fora do pedido. Com duas ou mais empresas, a pergunta que só
 * aí existe é *quem as liga* — quem se senta nas duas —, e é isso que a lista de
 * ligações e o grafo mostram primeiro.
 *
 * Os números vêm todos do servidor (`api/descoberta_pessoas.py`), calculados a
 * partir dos mesmos índices que o PessoasIQ lê, para o painel e a ficha
 * individual não divergirem.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Compass,
  GitCompareArrows,
  Info,
  Network,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "../components/ui";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { formatCompact, formatMoney, toStudioGraph, type GraphMetric, type StudioGraph } from "../components/graph/graphStudio";
import { resolverEmpresa, type DescobertaAlvo } from "../descobertaApi";
import {
  descobrirPessoas,
  getFichaPessoa,
  getPessoasMeta,
  nifsDoEndereco,
  type PessoaCargo,
  type PessoaFicha,
  type PessoasAtencao,
  type PessoasCargoBarra,
  type PessoasEmpresa,
  type PessoasFonte,
  type PessoasLigacao,
  type PessoasMeta,
  type PessoasPainel,
  type PessoasPessoa,
} from "../descobertaPessoasApi";
import { getWindowMode, useWindowMode } from "../layout";
import { openWindow } from "../windows";

/* ------------------------------------------------------------------ estilo */

type VistaGrafo = "network" | "hierarchical" | "circular";

const VISTAS: { id: VistaGrafo; label: string }[] = [
  { id: "network", label: "Rede" },
  { id: "hierarchical", label: "Hierarquia" },
  { id: "circular", label: "Circular" },
];

const CLASSES: Record<string, { label: string; className: string }> = {
  gestao: { label: "Órgão social", className: "border-teal-500/30 bg-teal-500/10 text-teal-200" },
  capital: { label: "Capital", className: "border-violet-500/30 bg-violet-500/10 text-violet-200" },
  processo: { label: "Processo", className: "border-sky-500/30 bg-sky-500/10 text-sky-200" },
  outro: { label: "Outro", className: "border-white/10 bg-white/5 text-muted-foreground" },
};

const SEVERIDADE: Record<string, { label: string; className: string }> = {
  alerta: { label: "Alertar", className: "border-rose-500/30 bg-rose-500/10 text-rose-200" },
  aviso: { label: "Vigiar", className: "border-amber-500/30 bg-amber-500/10 text-amber-200" },
  info: { label: "Nota", className: "border-white/10 bg-white/5 text-muted-foreground" },
};

const ESTADO_FONTE: Record<string, { label: string; className: string }> = {
  ok: { label: "ok", className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
  vazio: { label: "vazio", className: "border-white/10 bg-white/5 text-muted-foreground" },
  erro: { label: "erro", className: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  tempo: { label: "tempo", className: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
};

const texto = (valor: unknown): string => (valor === null || valor === undefined ? "" : String(valor));

const dataCurta = (valor: string): string => (valor ? valor.slice(0, 10) : "—");

function classeBadge(classe: string) {
  const spec = CLASSES[classe] ?? CLASSES.outro;
  return <Badge className={spec.className}>{spec.label}</Badge>;
}

function Kpi({ rotulo, valor, nota }: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="glass-card gradient-border rounded-2xl px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{rotulo}</p>
      <p className="mt-0.5 truncate text-lg font-semibold">{valor}</p>
      {nota ? <p className="truncate text-[11px] text-muted-foreground">{nota}</p> : null}
    </div>
  );
}

/** Abre a ficha de uma pessoa no PessoasIQ: janela em modo janelas, página em modo página. */
function abrirPessoaIQ(nif: string) {
  if (!nif) return;
  if (getWindowMode()) {
    openWindow(`person-detail:${nif}`, undefined, { title: `Pessoas IQ · ${nif}`, rect: { width: 980, height: 760 } });
    return;
  }
  if (typeof window === "undefined") return;
  window.history.pushState({}, "", `/pessoas-iq/${encodeURIComponent(nif)}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/* --------------------------------------------------------------- tabela */

function TabelaPessoas({ pessoas, onAbrir }: { pessoas: PessoasPessoa[]; onAbrir: (pessoa: PessoasPessoa) => void }) {
  if (!pessoas.length) {
    return <p className="text-xs text-muted-foreground">Nenhuma pessoa encontrada para estas empresas.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="pb-1 font-medium">Pessoa</th>
            <th className="pb-1 font-medium">Cargo atual</th>
            <th className="pb-1 font-medium">Empresas do pedido</th>
            <th className="pb-1 text-right font-medium">Cargos</th>
            <th className="pb-1 text-right font-medium">Universo</th>
            <th className="pb-1 pl-3 text-right font-medium">Registo</th>
          </tr>
        </thead>
        <tbody>
          {pessoas.map((pessoa) => (
            <tr
              key={pessoa.nif}
              onClick={() => onAbrir(pessoa)}
              className="cursor-pointer border-t border-white/5 align-top transition-colors hover:bg-white/5"
            >
              <td className="py-1.5 pr-2">
                <div className="flex items-center gap-1.5">
                  <span className="max-w-[220px] truncate font-medium" title={pessoa.nome}>
                    {pessoa.nome}
                  </span>
                  {pessoa.ligacao ? (
                    <Badge className="border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200">
                      liga {pessoa.empresas_pedido}
                    </Badge>
                  ) : null}
                  {classeBadge(pessoa.classe)}
                </div>
                <p className="truncate text-[10px] text-muted-foreground">
                  {pessoa.nif}
                  {pessoa.is_company ? " · sociedade" : ""}
                  {(pessoa.devedores?.devedor ? " · listas de devedores" : "")}
                </p>
              </td>
              <td className="max-w-[190px] py-1.5 pr-2">
                <span className="block truncate" title={`${pessoa.cargo_atual} · ${pessoa.role_org}`}>
                  {pessoa.cargo_atual || "—"}
                </span>
                <span className="block truncate text-[10px] text-muted-foreground">{pessoa.role_org}</span>
              </td>
              <td className="py-1.5 pr-2">
                <div className="flex flex-wrap gap-1">
                  {pessoa.empresas.map((empresa) => (
                    <span
                      key={empresa.nif}
                      className="max-w-[150px] truncate rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px]"
                      title={`${empresa.nome} · ${empresa.cargo_atual}`}
                    >
                      {empresa.nome}
                    </span>
                  ))}
                </div>
                {pessoa.outras_empresas.length ? (
                  <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    + {pessoa.outras_empresas.length} fora do pedido
                  </p>
                ) : null}
              </td>
              <td className="py-1.5 text-right tabular-nums">{pessoa.cargos_pedido}</td>
              <td className="py-1.5 text-right tabular-nums">
                {pessoa.empresas_universo || "—"}
                {pessoa.cargos_universo ? (
                  <span className="block text-[10px] text-muted-foreground">{pessoa.cargos_universo} cargos</span>
                ) : null}
              </td>
              <td className="py-1.5 pl-3 text-right tabular-nums text-muted-foreground">
                {dataCurta(pessoa.desde)}
                {pessoa.ultimo && pessoa.ultimo !== pessoa.desde ? ` → ${dataCurta(pessoa.ultimo)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        Clique numa pessoa para ver a ficha com todos os cargos. «Universo» é o que a plataforma já conhece desta pessoa
        fora das empresas pedidas.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------- ligações */

function Ligacoes({ ligacoes, onAbrir }: { ligacoes: PessoasLigacao[]; onAbrir: (nif: string) => void }) {
  if (!ligacoes.length) {
    return (
      <p className="text-xs text-muted-foreground">
        Nenhuma pessoa aparece em duas das empresas do pedido: não há ligação societária registada entre elas.
      </p>
    );
  }
  return (
    <ul className="max-h-[320px] space-y-1.5 overflow-y-auto text-[11px]">
      {ligacoes.map((ligacao) => (
        <li key={ligacao.nif} className="rounded-xl border border-white/5 p-2">
          <button type="button" className="w-full text-left" onClick={() => onAbrir(ligacao.nif)}>
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 flex-1 truncate font-semibold" title={ligacao.nome}>
                {ligacao.nome}
              </span>
              <span className="shrink-0 text-muted-foreground">{ligacao.empresas_pedido} empresas</span>
            </div>
            <p className="truncate text-[10px] text-muted-foreground">{ligacao.nif}</p>
          </button>
          <div className="mt-1 flex flex-wrap gap-1">
            {ligacao.empresas.map((empresa) => (
              <span
                key={empresa.nif}
                className="max-w-[190px] truncate rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-1.5 py-0.5 text-[10px] text-fuchsia-200"
                title={`${empresa.nome} · ${empresa.cargo}`}
              >
                {empresa.nome} · {empresa.cargo || "cargo registado"}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ----------------------------------------------------------------- grafo */

function GrafoPessoas({ painel }: { painel: PessoasPainel }) {
  const [metrica, setMetrica] = useState<GraphMetric>("contratos");
  const [vista, setVista] = useState<VistaGrafo>("network");
  const [selecionado, setSelecionado] = useState<string | null>(null);

  const grafoStudio = useMemo<StudioGraph | null>(
    () => toStudioGraph(painel.grafo ?? null, metrica),
    [painel.grafo, metrica],
  );
  const fichaNo = useMemo(
    () => (grafoStudio && selecionado ? grafoStudio.nodes.find((no) => no.id === selecionado) ?? null : null),
    [grafoStudio, selecionado],
  );

  if (!grafoStudio || !grafoStudio.nodes.length) {
    return <p className="text-xs text-muted-foreground">Sem rede de pessoas para este pedido.</p>;
  }

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_230px]">
      <GraphCanvas
        graph={grafoStudio}
        layout={vista}
        metric={metrica}
        unitLabel={metrica === "valor" ? "€ de capital" : "cargos"}
        heightClass="h-[460px]"
        labels="selecao"
        selectedNodeId={selecionado}
        nodeSummary={(no) => `${no.role || no.dimension} · ${formatCompact(no.count)} cargo(s)`}
        edgeSummary={(aresta) => aresta.relation || "cargo"}
        onNodeClick={(no) => setSelecionado(no.id)}
      />
      <div className="space-y-2 text-xs">
        <div className="flex gap-2">
          <Button size="sm" variant={metrica === "contratos" ? "primary" : "outline"} onClick={() => setMetrica("contratos")}>
            Cargos
          </Button>
          <Button size="sm" variant={metrica === "valor" ? "primary" : "outline"} onClick={() => setMetrica("valor")}>
            Capital
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {VISTAS.map((opcao) => (
            <Button key={opcao.id} size="sm" variant={vista === opcao.id ? "primary" : "outline"} onClick={() => setVista(opcao.id)}>
              {opcao.label}
            </Button>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          As empresas do pedido ligadas a quem nelas tem cargos registados ({painel.grafo?.meta.camadas?.pessoa ?? 0} pessoas
          no desenho). Clique num nó para ver o cargo; os papéis processuais do CIRE são evidência, não ligação.
        </p>
        {fichaNo ? (
          <div className="rounded-xl border border-white/10 bg-white/5 p-2 text-[11px]">
            <p className="truncate font-semibold">{fichaNo.label}</p>
            <p className="truncate text-muted-foreground">{fichaNo.role}</p>
            <p className="text-muted-foreground">
              {formatCompact(fichaNo.count)} cargo(s)
              {fichaNo.total_value ? ` · ${formatMoney(fichaNo.total_value)} de capital` : ""}
            </p>
            {fichaNo.type === "pessoa" ? (
              <Button size="sm" variant="outline" className="mt-1.5" onClick={() => abrirPessoaIQ(fichaNo.key)}>
                Abrir no PessoasIQ
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- cargos */

function BarrasCargos({ cargos }: { cargos: PessoasCargoBarra[] }) {
  if (!cargos.length) return <p className="text-xs text-muted-foreground">Sem cargos para distribuir.</p>;
  const maximo = Math.max(...cargos.map((cargo) => cargo.pessoas), 1);
  return (
    <ul className="space-y-1.5 text-[11px]">
      {cargos.map((cargo) => (
        <li key={cargo.cargo}>
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 flex-1 truncate" title={cargo.cargo}>
              {cargo.cargo}
            </span>
            <span className="shrink-0 text-muted-foreground tabular-nums">
              {cargo.pessoas} · {cargo.empresas} empresa(s)
            </span>
          </div>
          <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className={`h-full rounded-full ${
                cargo.classe === "gestao"
                  ? "bg-teal-400/70"
                  : cargo.classe === "capital"
                    ? "bg-violet-400/70"
                    : cargo.classe === "processo"
                      ? "bg-sky-400/70"
                      : "bg-slate-400/60"
              }`}
              style={{ width: `${Math.max(4, (cargo.pessoas / maximo) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------- empresas */

function EmpresasDoPedido({ empresas, onEmpresa }: { empresas: PessoasEmpresa[]; onEmpresa: (nif: string) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {empresas.map((empresa) => (
        <button
          key={empresa.nif}
          type="button"
          onClick={() => onEmpresa(empresa.nif)}
          className="rounded-xl border border-white/5 p-2.5 text-left transition-colors hover:border-primary/40 hover:bg-white/5"
        >
          <p className="flex items-center gap-1.5 text-xs font-semibold">
            <Building2 size={12} className="shrink-0 text-muted-foreground" />
            <span className="truncate" title={empresa.nome}>
              {empresa.nome}
            </span>
          </p>
          <p className="truncate text-[11px] text-muted-foreground">{empresa.nif}</p>
          <div className="mt-1 grid grid-cols-2 gap-1 text-[11px]">
            <span className="text-muted-foreground">Pessoas</span>
            <span className="text-right tabular-nums">
              {formatCompact(empresa.pessoas)}
              {empresa.truncado ? " (lista limitada)" : ""}
            </span>
            <span className="text-muted-foreground">Processos CIRE</span>
            <span className="text-right tabular-nums">{formatCompact(empresa.processos)}</span>
            <span className="text-muted-foreground">Papéis em processos</span>
            <span className="text-right tabular-nums">{formatCompact(empresa.cire_pessoas)}</span>
          </div>
          {empresa.erro ? <p className="mt-1 text-[10px] text-rose-300">{empresa.erro}</p> : null}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- atenção */

function Atencao({ atencao }: { atencao: PessoasAtencao[] }) {
  if (!atencao.length) return <p className="text-xs text-muted-foreground">Sem pontos de atenção no pedido.</p>;
  return (
    <ul className="space-y-1.5 text-[11px]">
      {atencao.map((ponto, indice) => {
        const spec = SEVERIDADE[ponto.severidade] ?? SEVERIDADE.info;
        return (
          <li key={`${ponto.titulo}-${indice}`} className="rounded-xl border border-white/5 p-2">
            <div className="flex items-start justify-between gap-2">
              <p className="min-w-0 flex-1 font-medium">{ponto.titulo}</p>
              <Badge className={spec.className}>{spec.label}</Badge>
            </div>
            <p className="mt-0.5 text-muted-foreground">{ponto.detalhe}</p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">A verificar: {ponto.verificar}</p>
          </li>
        );
      })}
    </ul>
  );
}

/* ----------------------------------------------------------------- fontes */

function PainelFontes({ fontes, avisos }: { fontes: PessoasFonte[]; avisos: string[] }) {
  return (
    <div className="space-y-2 text-[11px]">
      {avisos.map((aviso) => (
        <p key={aviso} className="flex items-start gap-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-amber-200">
          <Info size={12} className="mt-0.5 shrink-0" /> {aviso}
        </p>
      ))}
      <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
        {fontes.map((fonte) => {
          const spec = ESTADO_FONTE[fonte.estado] ?? ESTADO_FONTE.vazio;
          return (
            <li key={fonte.id} className="rounded-xl border border-white/5 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 flex-1 truncate font-medium" title={fonte.descricao}>
                  {fonte.label}
                </span>
                <Badge className={spec.className}>{spec.label}</Badge>
              </div>
              <p className="truncate text-muted-foreground" title={fonte.descricao}>
                {formatCompact(fonte.total)} · {fonte.indice ?? "—"}
                {fonte.ms ? ` · ${fonte.ms} ms` : ""}
              </p>
              {fonte.nota ? <p className="truncate text-[10px] text-muted-foreground">{fonte.nota}</p> : null}
              {fonte.erro ? <p className="truncate text-[10px] text-rose-300">{fonte.erro}</p> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------ ficha modal */

function CargosDaEmpresa({ cargos }: { cargos: PessoaCargo[] }) {
  return (
    <ul className="mt-1 space-y-1 text-[11px]">
      {cargos.map((cargo, indice) => (
        <li key={`${cargo.role}-${cargo.data}-${indice}`} className="border-b border-white/5 pb-1 last:border-0">
          <div className="flex items-start justify-between gap-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{cargo.role || "cargo registado"}</span>
              <span className="block truncate text-[10px] text-muted-foreground" title={cargo.role_org}>
                {cargo.role_org}
                {cargo.ato ? ` · ${cargo.ato}` : ""}
              </span>
            </span>
            <span className="shrink-0 text-right tabular-nums text-muted-foreground">
              {dataCurta(cargo.data)}
              {cargo.quota ? <span className="block text-[10px]">{formatMoney(cargo.quota)}</span> : null}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function FichaPessoa({ ficha, aCarregar, onClose }: { ficha: PessoaFicha | null; aCarregar: boolean; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:p-8" onClick={onClose}>
      <div
        className="glass-card gradient-border w-full max-w-3xl rounded-2xl p-4"
        onClick={(evento) => evento.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 truncate text-sm font-semibold">
              <UserRound size={15} className="shrink-0 text-primary" />
              {ficha?.nome || "A carregar…"}
            </p>
            <p className="truncate text-[11px] text-muted-foreground">
              {ficha ? `${ficha.nif} · ${ficha.classe_label} · ${ficha.cargos_total} cargo(s) em ${ficha.empresas_total} empresa(s)` : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {ficha ? (
              <Button size="sm" variant="outline" onClick={() => abrirPessoaIQ(ficha.nif)}>
                Abrir no PessoasIQ
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={onClose} aria-label="Fechar ficha">
              <X size={14} />
            </Button>
          </div>
        </div>

        {aCarregar ? <p className="mt-3 text-xs text-muted-foreground">A juntar os cargos desta pessoa…</p> : null}
        {ficha && !ficha.encontrada ? (
          <p className="mt-3 text-xs text-rose-300">{ficha.erro || "Pessoa não encontrada."}</p>
        ) : null}

        {ficha?.encontrada ? (
          <div className="mt-3 space-y-3">
            {ficha.avisos.map((aviso) => (
              <p key={aviso} className="flex items-start gap-1.5 text-[11px] text-amber-200">
                <Info size={12} className="mt-0.5 shrink-0" /> {aviso}
              </p>
            ))}
            {ficha.perfil ? (
              <div className="rounded-xl border border-white/5 p-2 text-[11px]">
                <p className="font-medium">Perfil público</p>
                <p className="text-muted-foreground">
                  {[ficha.perfil.cargo_publico, ficha.perfil.partido, ficha.perfil.legislatura].filter(Boolean).join(" · ") || "—"}
                </p>
                {ficha.perfil.biografia ? (
                  <p className="mt-1 line-clamp-4 text-muted-foreground">{ficha.perfil.biografia}</p>
                ) : null}
              </div>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-2">
              {ficha.empresas.map((empresa) => (
                <div
                  key={empresa.nif}
                  className={`rounded-xl border p-2.5 ${
                    empresa.no_pedido ? "border-fuchsia-500/25 bg-fuchsia-500/5" : "border-white/5"
                  }`}
                >
                  <p className="flex items-center gap-1.5 text-[11.5px] font-semibold">
                    <Building2 size={12} className="shrink-0 text-muted-foreground" />
                    <span className="truncate" title={empresa.nome}>
                      {empresa.nome}
                    </span>
                    {empresa.no_pedido ? <Badge className="border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200">pedido</Badge> : null}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {empresa.nif} · {empresa.cargos_total} cargo(s)
                    {empresa.desde ? ` · desde ${dataCurta(empresa.desde)}` : ""}
                  </p>
                  <CargosDaEmpresa cargos={empresa.cargos} />
                </div>
              ))}
            </div>
            {ficha.quotas.length ? (
              <div className="rounded-xl border border-white/5 p-2 text-[11px]">
                <p className="font-medium">Capital</p>
                <ul className="mt-1 space-y-1">
                  {ficha.quotas.map((quota, indice) => (
                    <li key={`${quota.empresa_nif}-${indice}`} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate">{quota.empresa}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {formatMoney(quota.quota)} · {dataCurta(quota.data)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ vista */

export default function DescobertaPessoasPage({ onBack }: { onBack?: () => void } = {}) {
  const { windowMode } = useWindowMode();
  const [meta, setMeta] = useState<PessoasMeta | null>(null);
  const [consulta, setConsulta] = useState("");
  // Abrir por link direto (`/descoberta-pessoas?nifs=...`) já traz as empresas.
  const [empresas, setEmpresas] = useState<{ nif: string; nome: string }[]>(() =>
    nifsDoEndereco().map((nif) => ({ nif, nome: "" })),
  );
  const [candidatos, setCandidatos] = useState<DescobertaAlvo[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const [painel, setPainel] = useState<PessoasPainel | null>(null);
  const [aDescobrir, setADescobrir] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [erro, setErro] = useState<string | null>(null);
  const [fichaNo, setFichaNo] = useState<string | null>(null);
  const [ficha, setFicha] = useState<PessoaFicha | null>(null);
  const [aCarregarFicha, setACarregarFicha] = useState(false);
  const iniciado = useRef(false);

  const nifs = useMemo(() => empresas.map((empresa) => empresa.nif), [empresas]);

  useEffect(() => {
    getPessoasMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);

  const juntar = useCallback((nif: string, nome: string) => {
    const alvo = nif.trim();
    if (!alvo) return;
    setEmpresas((atual) => (atual.some((empresa) => empresa.nif === alvo) ? atual : [...atual, { nif: alvo, nome: nome || alvo }]));
    setConsulta("");
    setCandidatos([]);
  }, []);

  const descobrir = useCallback(
    async (lista: { nif: string; nome: string }[]) => {
      if (!lista.length) {
        setErro("Indique pelo menos uma empresa (NIF de 9 dígitos ou nome).");
        return;
      }
      setADescobrir(true);
      setErro(null);
      setSegundos(0);
      const relogio = window.setInterval(() => setSegundos((atual) => atual + 1), 1000);
      try {
        const resultado = await descobrirPessoas(
          lista.map((empresa) => empresa.nif),
          { maxEmpresas: 6, nomes: lista.map((empresa) => empresa.nome) },
        );
        setPainel(resultado);
        if (typeof window !== "undefined") {
          window.history.replaceState(null, "", `/descoberta-pessoas?nifs=${encodeURIComponent(lista.map((e) => e.nif).join(","))}`);
        }
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : String(falha));
        setPainel(null);
      } finally {
        window.clearInterval(relogio);
        setADescobrir(false);
      }
    },
    [],
  );

  // O pedido do endereço é descoberto uma vez, à entrada.
  useEffect(() => {
    if (iniciado.current) return;
    iniciado.current = true;
    if (empresas.length) void descobrir(empresas);
    // Só à entrada: `empresas` nesta altura é o que veio do endereço.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const procurar = async () => {
    const valor = consulta.trim();
    if (valor.length < 2) return;
    if (/^\d{9}$/.test(valor)) {
      juntar(valor, valor);
      return;
    }
    setAProcurar(true);
    setErro(null);
    try {
      const resolucao = await resolverEmpresa(valor);
      const itens = (resolucao.items || []).filter((item) => item.nif);
      if (itens.length === 1) {
        juntar(texto(itens[0].nif), texto(itens[0].nome) || valor);
        return;
      }
      if (itens.length > 1) {
        setCandidatos(itens);
        return;
      }
      setCandidatos([]);
      setErro(resolucao.detail || "Nada encontrado para esse nome ou NIF.");
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
      setCandidatos([]);
    } finally {
      setAProcurar(false);
    }
  };

  const abrirFicha = useCallback(
    async (nif: string) => {
      setFichaNo(nif);
      setFicha(null);
      setACarregarFicha(true);
      try {
        const resultado = await getFichaPessoa(nif, nifs);
        setFicha(resultado);
      } catch (falha) {
        setFicha({
          nif,
          nome: nif,
          encontrada: false,
          erro: falha instanceof Error ? falha.message : String(falha),
          is_company: false,
          classe: "outro",
          classe_label: "Outro",
          cargos_total: 0,
          empresas_total: 0,
          primeiro: "",
          ultimo: "",
          origens: [],
          empresas: [],
          quotas: [],
          perfil: null,
          nas_empresas_pedido: null,
          avisos: [],
        });
      } finally {
        setACarregarFicha(false);
      }
    },
    [nifs],
  );

  const kpis = painel?.kpis;

  return (
    <div className="@container flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-white/8 bg-white/[0.02] px-4 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-pink-300 via-rose-500 to-fuchsia-600 text-white shadow-lg shadow-rose-500/20">
          <Compass size={17} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold leading-tight">Descoberta de Pessoas</h1>
          <p className="truncate text-[11.5px] text-muted-foreground">
            Uma ou várias empresas → quem nelas tem cargos, o capital, os papéis nos processos e quem liga as empresas
            {painel ? ` · ${painel.pessoas.length} pessoa(s) em ${painel.empresas.length} empresa(s)` : ""}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {meta ? (
            <span className="hidden items-center gap-1 rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-0.5 text-[11px] font-medium text-rose-200 sm:inline-flex">
              <Sparkles size={11} />
              {meta.fontes.length} fontes · até {meta.limites.empresas} empresas · até {meta.limites.pessoas_por_empresa} pessoas por empresa
            </span>
          ) : null}
          {!windowMode && onBack ? (
            <Button variant="secondary" size="sm" onClick={onBack}>
              Voltar ao Chat
            </Button>
          ) : null}
        </div>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/8 px-4 py-2.5">
        <div className="relative min-w-[240px] flex-1">
          <Input
            value={consulta}
            onChange={(evento) => setConsulta(evento.target.value)}
            onKeyDown={(evento) => {
              if (evento.key === "Enter") void procurar();
            }}
            placeholder="NIF (9 dígitos) ou nome da empresa…"
            className="pl-8"
          />
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        </div>
        <Button variant="outline" onClick={() => void procurar()} loading={aProcurar} disabled={aProcurar || consulta.trim().length < 2}>
          <Plus size={14} /> Adicionar empresa
        </Button>
        <Button onClick={() => void descobrir(empresas)} loading={aDescobrir} disabled={aDescobrir || !empresas.length}>
          <Users size={14} /> Descobrir pessoas
        </Button>
        {painel ? (
          <Button variant="outline" onClick={() => void descobrir(empresas)} loading={aDescobrir} icon={<RefreshCw size={14} />}>
            Atualizar
          </Button>
        ) : null}
        {empresas.length ? (
          <Button
            variant="ghost"
            onClick={() => {
              setEmpresas([]);
              setPainel(null);
              setCandidatos([]);
              if (typeof window !== "undefined") window.history.replaceState(null, "", "/descoberta-pessoas");
            }}
          >
            Limpar
          </Button>
        ) : null}
        {aDescobrir ? <span className="text-[11px] text-muted-foreground">A ler cargos, capital e processos… {segundos}s</span> : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 @4xl:p-4">
        <Card className="mb-3">
          <CardHeader className="mb-2">
            <CardTitle icon={<Building2 size={16} className="text-primary" />}>Empresas do pedido ({empresas.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              {empresas.map((empresa) => (
                <span key={empresa.nif} className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
                  <span className="max-w-[220px] truncate" title={`${empresa.nome} · ${empresa.nif}`}>
                    {empresa.nome || empresa.nif}
                  </span>
                  <button
                    type="button"
                    className="rounded-full p-0.5 hover:bg-white/10"
                    aria-label={`Remover ${empresa.nome || empresa.nif}`}
                    onClick={() => setEmpresas((atual) => atual.filter((item) => item.nif !== empresa.nif))}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
              {!empresas.length ? (
                <span className="text-muted-foreground">
                  Ainda sem empresas — procure por NIF ou nome. Uma empresa responde «quem manda aqui?»; várias respondem também
                  «quem as liga?».
                </span>
              ) : null}
            </div>
            {candidatos.length ? (
              <div className="space-y-1 rounded-xl border border-white/5 p-2">
                <p className="text-muted-foreground">Várias empresas correspondem — escolha uma:</p>
                <div className="flex flex-wrap gap-2">
                  {candidatos.map((candidato) => (
                    <Button
                      key={`${candidato.nif}-${candidato.nome}`}
                      size="sm"
                      variant="outline"
                      onClick={() => juntar(texto(candidato.nif), texto(candidato.nome))}
                    >
                      {candidato.nome} · {candidato.nif}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
            {erro ? (
              <p className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-rose-200">
                <AlertTriangle size={14} /> {erro}
              </p>
            ) : null}
            <p className="text-[11px] text-muted-foreground">
              Lê os cargos de órgão social por empresa, o capital com quota, a rede de cada pessoa e os processos do CIRE em
              que as empresas são parte; verifica ainda as listas de devedores para os titulares mais relevantes.
            </p>
          </CardContent>
        </Card>

        {painel ? (
          <>
            {kpis ? (
              <div className="mb-3 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
                <Kpi rotulo="Pessoas" valor={formatCompact(kpis.pessoas)} nota={`${kpis.cargos} cargo(s) lidos`} />
                <Kpi
                  rotulo="Ligam empresas"
                  valor={formatCompact(kpis.em_varias)}
                  nota={kpis.em_varias ? "têm cargo em duas ou mais do pedido" : "nenhuma pessoa em duas empresas"}
                />
                <Kpi
                  rotulo="Órgãos sociais"
                  valor={formatCompact(kpis.gestao)}
                  nota={`${kpis.capital} com capital · ${kpis.processo} só em processos`}
                />
                <Kpi
                  rotulo="Empresas"
                  valor={formatCompact(kpis.empresas)}
                  nota={`${kpis.empresas_sem_pessoas} sem cargos registados`}
                />
                <Kpi
                  rotulo="Cargo mais frequente"
                  valor={kpis.cargo_top?.cargo ?? "—"}
                  nota={kpis.cargo_top ? `${kpis.cargo_top.pessoas} pessoa(s) · ${kpis.cargo_top.empresas} empresa(s)` : undefined}
                />
                <Kpi
                  rotulo="Cargos por pessoa"
                  valor={kpis.profundidade === null ? "—" : kpis.profundidade.toFixed(2)}
                  nota={`${kpis.universo_multi} com cargos em várias empresas`}
                />
                <Kpi
                  rotulo="Processos CIRE"
                  valor={formatCompact(kpis.processos)}
                  nota={`${kpis.cire_pessoas} titular(es) nos processos`}
                />
                <Kpi
                  rotulo="Listas de devedores"
                  valor={formatCompact(kpis.devedores)}
                  nota={kpis.devedores ? "titulares encontrados nas listas" : "nenhum titular encontrado"}
                />
              </div>
            ) : null}

            <Card className="mb-3">
              <CardContent className="space-y-1 text-sm">
                <p className="font-medium">{painel.leitura}</p>
                <p className="text-[11px] text-muted-foreground">
                  {painel.pedido.analisadas} empresa(s) analisada(s) · {painel.pessoas.length} pessoa(s) · gerado{" "}
                  {texto(painel.gerado_em).slice(11, 19)} UTC · {painel.ms} ms
                </p>
              </CardContent>
            </Card>

            <div className="mb-3 grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle icon={<Users size={16} className="text-primary" />}>Pessoas encontradas ({painel.pessoas.length})</CardTitle>
                </CardHeader>
                <CardContent>
                  <TabelaPessoas pessoas={painel.pessoas} onAbrir={(pessoa) => void abrirFicha(pessoa.nif)} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle icon={<GitCompareArrows size={16} className="text-fuchsia-300" />}>
                    Quem liga as empresas ({painel.ligacoes.length})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Ligacoes ligacoes={painel.ligacoes} onAbrir={(nif) => void abrirFicha(nif)} />
                </CardContent>
              </Card>
            </div>

            <Card className="mb-3">
              <CardHeader className="mb-2">
                <CardTitle icon={<Network size={16} className="text-primary" />}>Rede de pessoas</CardTitle>
              </CardHeader>
              <CardContent>
                <GrafoPessoas painel={painel} />
              </CardContent>
            </Card>

            <div className="mb-3 grid gap-3 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle>Cargos no conjunto</CardTitle>
                </CardHeader>
                <CardContent>
                  <BarrasCargos cargos={painel.cargos} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle>Empresas do pedido</CardTitle>
                </CardHeader>
                <CardContent>
                  <EmpresasDoPedido empresas={painel.empresas} onEmpresa={(nif) => abrirPessoaIQ(nif)} />
                  <p className="mt-2 text-[10px] text-muted-foreground">
                    «Papéis em processos» são pessoas com NIF nos processos do CIRE desta empresa — credores, insolventes e
                    administradores de insolvência, que não são órgãos sociais.
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="mb-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle>O que verificar primeiro ({painel.atencao.length})</CardTitle>
                </CardHeader>
                <CardContent>
                  <Atencao atencao={painel.atencao} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="mb-2">
                  <CardTitle>Fontes ({painel.fontes.length})</CardTitle>
                </CardHeader>
                <CardContent>
                  <PainelFontes fontes={painel.fontes} avisos={painel.avisos} />
                </CardContent>
              </Card>
            </div>
          </>
        ) : (
          <Card>
            <CardContent className="text-xs text-muted-foreground">
              Escolha as empresas e carregue em «Descobrir pessoas». O painel dá os titulares de cada empresa, quem se senta em
              mais do que uma, os papéis nos processos do CIRE e as listas de devedores.
            </CardContent>
          </Card>
        )}
      </div>

      {fichaNo ? <FichaPessoa ficha={ficha} aCarregar={aCarregarFicha} onClose={() => setFichaNo(null)} /> : null}
    </div>
  );
}
