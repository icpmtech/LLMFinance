/**
 * **Benchmark de preços e concorrência** — `/benchmark`.
 *
 * Dá uma entidade do sistema (empresa que vende ao Estado ou entidade que
 * compra) e um CPV, e mostra:
 *
 * 1. **Preço de referência** — como se comportam os valores do segmento
 *    (mediana, quartis, média, mínimo e máximo) e onde cai o preço da empresa;
 * 2. **Concorrência** — quem são os pares (mesmo papel) e em que posição fica;
 * 3. **Historial** — as contrapartes com quem a empresa já contratou;
 * 4. **Oportunidades** — contrapartes do segmento com que nunca contratou.
 *
 * O separador **Comparar** junta até `MAX_COMPARE` empresas no mesmo segmento.
 * A página é **por país** (`pt`/`es`/`fr`); com o âmbito `all` mostra antes o
 * quadro conjunto por CPV (`BenchmarkByCpv`), porque os mercados não se
 * comparam empresa a empresa entre países.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight,
  BadgeEuro,
  Building2,
  Compass,
  Handshake,
  Info,
  Landmark,
  Loader2,
  RefreshCw,
  Scale,
  ShoppingCart,
  Target,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Label } from "../components/ui/Label";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/Tabs";
import BenchmarkByCpv from "../components/benchmark/BenchmarkByCpv";
import BenchmarkCompare from "../components/benchmark/BenchmarkCompare";
import { CpvAutocomplete, EmpresaAutocomplete, type EmpresaBenchmark } from "../components/benchmark/BenchmarkPickers";
import {
  getBenchmarkEntity,
  getBenchmarkMeta,
  type BenchmarkCountry,
  type BenchmarkMetaAll,
  type BenchmarkResponse,
  type BenchmarkRole,
  type BenchmarkRow,
  type BenchmarkScope,
} from "../benchmarkApi";

const PAGE_MAX_YEARS = 12;

/** Modos da página: análise de uma empresa ou comparação de várias. */
type Modo = "empresa" | "comparar";

function money(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

function moneyShort(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} M€`;
  if (abs >= 10_000) return `${(value / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return money(value);
}

function num(value?: number | null): string {
  if (value === undefined || value === null) return "—";
  return value.toLocaleString("pt-PT");
}

function pct(value?: number | null, digits = 1): string {
  if (value === undefined || value === null) return "—";
  return `${value.toLocaleString("pt-PT", { maximumFractionDigits: digits, minimumFractionDigits: digits })} %`;
}

function shortDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString("pt-PT");
}

/** Cartão de indicador. */
function Kpi({ icon, label, value, nota }: { icon: ReactNode; label: string; value: string; nota?: string }) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/5 text-muted-foreground">{icon}</div>
        <div className="min-w-0">
          <p className="truncate text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="truncate text-lg font-semibold tabular-nums">{value}</p>
          {nota ? <p className="truncate text-xs text-muted-foreground">{nota}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

/** Tabela de ranking (concorrentes, contrapartes, oportunidades). */
function TabelaRanking({
  titulo,
  icon,
  rows,
  vazio,
  destaqueNif,
  mostrarMotivo,
}: {
  titulo: string;
  icon: ReactNode;
  rows: BenchmarkRow[];
  vazio: string;
  destaqueNif?: string;
  mostrarMotivo?: boolean;
}) {
  const maxValue = rows.reduce((max, row) => Math.max(max, row.value ?? 0), 0);
  return (
    <Card className="min-w-0">
      <CardHeader className="flex flex-row items-center gap-2 pb-2">
        <span className="text-muted-foreground">{icon}</span>
        <CardTitle className="text-sm">{titulo}</CardTitle>
        <span className="ml-auto text-xs text-muted-foreground">{rows.length}</span>
      </CardHeader>
      <CardContent className="pt-0">
        {rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{vazio}</p>
        ) : (
          <ul className="divide-y divide-border/60">
            {rows.map((row) => {
              const destaque = destaqueNif && row.nif === destaqueNif;
              const largura = maxValue ? Math.max(2, (100 * (row.value ?? 0)) / maxValue) : 0;
              return (
                <li key={row.nif} className="py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="w-6 shrink-0 text-xs tabular-nums text-muted-foreground">{row.rank ?? "—"}</span>
                    <span className={`min-w-0 flex-1 truncate text-sm ${destaque ? "font-semibold text-emerald-300" : ""}`} title={row.name}>
                      {row.name}
                    </span>
                    <span className="shrink-0 text-sm font-medium tabular-nums">{moneyShort(row.value)}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 pl-8">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div
                        className={`h-full rounded-full ${destaque ? "bg-emerald-400/70" : "bg-sky-400/60"}`}
                        style={{ width: `${largura}%` }}
                      />
                    </div>
                    <span className="w-32 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                      {num(row.count)} contratos · {pct(row.share_pct)}
                    </span>
                  </div>
                  {mostrarMotivo && row.why ? (
                    <p className="pl-8 pt-0.5 text-xs text-muted-foreground/80">{row.why}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Régua de percentis: mercado (p10…p90) com o marcador do preço da empresa. */
function ReguaPreco({ dados }: { dados: BenchmarkResponse }) {
  const { reference, entity } = dados;
  const maximo = Math.max(reference.max ?? 0, entity.median_value ?? 0, reference.p90 ?? 0);
  if (!maximo) {
    return <p className="py-4 text-sm text-muted-foreground">Sem valores suficientes para a régua de preços.</p>;
  }
  const pos = (value?: number | null) => (value ? Math.min(100, Math.max(0, (100 * value) / maximo)) : 0);
  const marcas: { label: string; value?: number | null }[] = [
    { label: "mín.", value: reference.min },
    { label: "p10", value: reference.p10 },
    { label: "p25", value: reference.p25 },
    { label: "mediana", value: reference.median },
    { label: "p75", value: reference.p75 },
    { label: "p90", value: reference.p90 },
    { label: "máx.", value: reference.max },
  ];
  return (
    <div className="space-y-4">
      <div className="relative h-9">
        <div className="absolute inset-x-0 top-4 h-2 rounded-full bg-white/5" />
        <div
          className="absolute top-4 h-2 rounded-full bg-sky-400/40"
          style={{ left: `${pos(reference.p25)}%`, width: `${Math.max(1, pos(reference.p75) - pos(reference.p25))}%` }}
        />
        {entity.median_value ? (
          <div
            className="absolute -top-1 z-10 h-6 w-1 rounded-full bg-emerald-300 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
            style={{ left: `${Math.min(99, pos(entity.median_value))}%` }}
            title={`Mediana da empresa: ${money(entity.median_value)}`}
          />
        ) : null}
      </div>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
        {marcas.map((marca) => (
          <div key={marca.label} className="min-w-0">
            <p className="text-xs text-muted-foreground">{marca.label}</p>
            <p className="truncate text-sm font-medium tabular-nums">{moneyShort(marca.value)}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Barra azul: intervalo interquartil do mercado (p25–p75) de {num(reference.contracts)} contratos com valor.
        {entity.median_value ? " Marca verde: mediana da empresa." : ""}
      </p>
    </div>
  );
}

export default function BenchmarkPage({
  scope = "pt",
  onSwitchView,
}: {
  /** País da página (`pt`/`es`/`fr`) ou `all` para o quadro conjunto por CPV. */
  scope?: BenchmarkScope;
  onSwitchView?: () => void;
}) {
  const [meta, setMeta] = useState<BenchmarkMetaAll | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const [entidade, setEntidade] = useState<EmpresaBenchmark | null>(null);
  const [modo, setModo] = useState<Modo>("empresa");

  const [role, setRole] = useState<BenchmarkRole>("adjudicatario");
  const [cpv, setCpv] = useState("");
  const [anoDe, setAnoDe] = useState<number | "">("");
  const [anoAte, setAnoAte] = useState<number | "">("");
  const [regiao, setRegiao] = useState("");

  const [dados, setDados] = useState<BenchmarkResponse | null>(null);
  const [aCarregar, setACarregar] = useState(false);

  const soPais = scope !== "all";
  const pais: BenchmarkCountry = scope === "all" ? "pt" : scope;
  const infoPais = useMemo(
    () => meta?.countries?.find((item) => item.country === pais) ?? null,
    [meta, pais],
  );

  useEffect(() => {
    getBenchmarkMeta(scope)
      .then((resultado) => {
        setMeta(resultado);
        const anos = (resultado.years ?? []).slice(0, PAGE_MAX_YEARS);
        if (anos.length) {
          setAnoDe(Math.min(...anos));
          setAnoAte(Math.max(...anos));
        }
        // CPV vindo do quadro conjunto (`?cpv=33600000`): fica no filtro à
        // espera de uma entidade — sem entidade não há análise a fazer, por isso
        // não se dispara nenhum pedido (nem se mostra erro).
        const daUrl = new URLSearchParams(window.location.search).get("cpv");
        if (daUrl) setCpv(daUrl);
      })
      .catch((err: unknown) => setErro(err instanceof Error ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const escolherEntidade = useCallback((empresa: EmpresaBenchmark) => {
    setEntidade(empresa);
  }, []);

  const analisar = useCallback(
    async (override?: { role?: BenchmarkRole; cpv_code?: string; entidade?: EmpresaBenchmark | null }) => {
      const alvo = override?.entidade ?? entidade;
      if (!alvo) {
        setErro("Escolha primeiro uma entidade do sistema.");
        return;
      }
      const papel = override?.role ?? role;
      const codigoCpv = override?.cpv_code ?? cpv;
      setACarregar(true);
      setErro(null);
      try {
        const resultado = await getBenchmarkEntity({
          nif: alvo.nif || undefined,
          name: alvo.name,
          role: papel,
          country: pais,
          cpv_code: codigoCpv || undefined,
          year_from: anoDe === "" ? undefined : Number(anoDe),
          year_to: anoAte === "" ? undefined : Number(anoAte),
          region: regiao.trim() || undefined,
          top: 12,
        });
        setDados(resultado);
      } catch (err) {
        setDados(null);
        setErro(err instanceof Error ? err.message : String(err));
      } finally {
        setACarregar(false);
      }
    },
    [entidade, role, cpv, anoDe, anoAte, regiao, pais],
  );

  const alternarPapel = (proximo: BenchmarkRole) => {
    setRole(proximo);
    if (dados) void analisar({ role: proximo });
  };

  const escolherCpv = (codigo: string) => {
    setCpv(codigo);
    if (codigo) void analisar({ cpv_code: codigo });
  };

  const limpar = () => {
    setEntidade(null);
    setCpv("");
    setDados(null);
    setErro(null);
  };

  const anos = useMemo(() => (meta?.years ?? []).slice(0, PAGE_MAX_YEARS), [meta]);
  const vender = role === "adjudicatario";
  const rotuloContraparte = vender ? "Compradores" : "Fornecedores";
  const rotuloConcorrente = vender ? "Fornecedores concorrentes" : "Entidades compradoras";

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Scale size={22} className="text-sky-400" />
            Benchmark {soPais ? `· ${infoPais?.label ?? ""}` : "· Portugal, Espanha e França"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {soPais
              ? `Preço de referência por CPV, concorrentes, historial de contrapartes e oportunidades — ${infoPais?.label ?? ""}${infoPais ? ` (${num(infoPais.total)} contratos)` : ""}.`
              : "Quadro conjunto dos três países por CPV: volume, valor e preço mediano de cada mercado."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {soPais ? (
            <>
              <Button variant="outline" size="md" icon={<RefreshCw size={15} />} onClick={() => void analisar()} disabled={!entidade}>
                Atualizar
              </Button>
              <Button variant="outline" size="md" onClick={limpar} disabled={!entidade && !dados}>
                Limpar
              </Button>
            </>
          ) : null}
          {onSwitchView ? (
            <Button variant="outline" size="md" onClick={onSwitchView}>
              Fechar
            </Button>
          ) : null}
        </div>
      </header>

      {!soPais ? (
        <BenchmarkByCpv meta={meta} />
      ) : (
        <>
      <Tabs value={modo} className="mb-6">
        <TabsList>
          <TabsTrigger value="empresa" active={modo === "empresa"} onClick={() => setModo("empresa")}>
            Uma empresa
          </TabsTrigger>
          <TabsTrigger value="comparar" active={modo === "comparar"} onClick={() => setModo("comparar")}>
            Comparar até 10
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {modo === "comparar" ? (
        <BenchmarkCompare meta={meta} country={pais} />
      ) : (
        <>
          {/* -------------------------------------------------- configurador */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Compass size={16} /> Entidade e segmento
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {/* entidade */}
            <EmpresaAutocomplete
              id="benchmark-entidade"
              country={pais}
              role={role}
              value={entidade}
              onSelect={escolherEntidade}
              onClear={() => setEntidade(null)}
            />

            {/* papel */}
            <div>
              <Label>Papel da entidade</Label>
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  onClick={() => alternarPapel("adjudicatario")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    vender ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <BadgeEuro size={15} /> Vende (adjudicatário)
                </button>
                <button
                  type="button"
                  onClick={() => alternarPapel("adjudicante")}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    !vender ? "border-sky-400/40 bg-sky-400/10 text-sky-200" : "border-border hover:bg-accent"
                  }`}
                >
                  <ShoppingCart size={15} /> Compra (adjudicante)
                </button>
              </div>
            </div>

            {/* CPV */}
            <CpvAutocomplete id="benchmark-cpv" country={pais} value={cpv} onChange={escolherCpv} />
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div>
              <Label htmlFor="benchmark-ano-de">Ano de</Label>
              <select
                id="benchmark-ano-de"
                className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                value={anoDe}
                onChange={(e) => setAnoDe(e.target.value === "" ? "" : Number(e.target.value))}
              >
                <option value="">Todos</option>
                {anos.map((ano) => (
                  <option key={ano} value={ano}>
                    {ano}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="benchmark-ano-ate">Ano até</Label>
              <select
                id="benchmark-ano-ate"
                className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                value={anoAte}
                onChange={(e) => setAnoAte(e.target.value === "" ? "" : Number(e.target.value))}
              >
                <option value="">Todos</option>
                {anos.map((ano) => (
                  <option key={ano} value={ano}>
                    {ano}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="benchmark-regiao">Região / distrito</Label>
              <Input
                id="benchmark-regiao"
                className="mt-1"
                placeholder="ex.: Lisboa, PT11…"
                value={regiao}
                onChange={(e) => setRegiao(e.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button className="w-full" onClick={() => void analisar()} disabled={!entidade} loading={aCarregar} icon={<TrendingUp size={16} />}>
                Analisar mercado
              </Button>
            </div>
          </div>

          {entidade ? (
            <p className="text-xs text-muted-foreground">
              {entidade.name}
              {entidade.nif && entidade.nif !== entidade.name ? ` · ${entidade.nif}` : ""} ·{" "}
              {num(entidade.contracts)} contratos no total
              {entidade.total_value ? ` · ${moneyShort(entidade.total_value)}` : ""}
              {cpv ? ` · segmento CPV ${cpv}` : " · sem CPV (todo o mercado filtrado)"}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {erro ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">{erro}</span>
        </div>
      ) : null}

      {aCarregar && !dados ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Loader2 size={30} className="mb-3 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">A calcular o benchmark do segmento…</p>
        </div>
      ) : null}

      {!dados && !aCarregar ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Target size={32} className="mb-3 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Escolha uma entidade (e, se quiser, um CPV) para ver o preço de referência, a concorrência e as oportunidades.
          </p>
        </div>
      ) : null}

      {dados ? (
        <div className="space-y-6">
          {!dados.entity.present ? (
            <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
              <Info size={14} className="mt-0.5 shrink-0" />
              <span className="flex-1">
                A entidade não tem contratos neste papel no segmento escolhido — os valores da empresa aparecem a zero.
                Mude o papel (vende/compra) ou o intervalo de anos.
              </span>
            </div>
          ) : null}

          {/* KPIs */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
            <Kpi icon={<Building2 size={16} />} label="Contratos da entidade" value={num(dados.entity.contracts)} />
            <Kpi icon={<BadgeEuro size={16} />} label="Valor da entidade" value={moneyShort(dados.entity.total_value)} />
            <Kpi
              icon={<Scale size={16} />}
              label="Mediana da entidade"
              value={moneyShort(dados.entity.median_value)}
              nota={`mercado ${moneyShort(dados.reference.median)}`}
            />
            <Kpi
              icon={<TrendingUp size={16} />}
              label="Índice de preço"
              value={dados.entity.price_index === null || dados.entity.price_index === undefined ? "—" : `${dados.entity.price_index.toLocaleString("pt-PT", { maximumFractionDigits: 2 })}×`}
              nota="mediana empresa ÷ mediana mercado"
            />
            <Kpi
              icon={<Trophy size={16} />}
              label="Posição"
              value={dados.entity.rank ? `${dados.entity.rank}º` : "—"}
              nota={`de ${num(dados.market.peers)} ${vender ? "fornecedores" : "compradores"}`}
            />
            <Kpi
              icon={<Users size={16} />}
              label="Quota de valor"
              value={pct(dados.entity.share_pct)}
              nota={`${pct(dados.entity.count_share_pct)} dos contratos`}
            />
          </div>

          {/* preço de referência */}
          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Scale size={16} className="text-muted-foreground" />
              <CardTitle className="text-sm">Preço de referência do segmento</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground">
                {num(dados.market.contracts)} contratos · {moneyShort(dados.reference.total_value)}
              </span>
            </CardHeader>
            <CardContent className="space-y-4">
              <ReguaPreco dados={dados} />
              <div className="grid grid-cols-3 gap-3 border-t border-border/60 pt-4 sm:grid-cols-5">
                <div>
                  <p className="text-xs text-muted-foreground">Média do mercado</p>
                  <p className="text-sm font-medium tabular-nums">{money(dados.reference.avg)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Mediana do mercado</p>
                  <p className="text-sm font-medium tabular-nums">{money(dados.reference.median)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Média da empresa</p>
                  <p className="text-sm font-medium tabular-nums">{money(dados.entity.avg_value)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{rotuloContraparte} no segmento</p>
                  <p className="text-sm font-medium tabular-nums">{num(dados.market.counterparts)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Último contrato</p>
                  <p className="text-sm font-medium tabular-nums">{shortDate(dados.entity.last_date)}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* CPV da empresa (quando não há CPV escolhido) */}
          {!cpv && dados.entity.top_cpv.length > 0 ? (
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Target size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">CPV principais da entidade</CardTitle>
                <span className="ml-auto text-xs text-muted-foreground">clique para analisar o segmento</span>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2 pt-0">
                {dados.entity.top_cpv.map((item) => (
                  <button
                    key={item.code}
                    type="button"
                    className="group inline-flex max-w-full items-center gap-2 rounded-full border border-border px-3 py-1.5 text-xs transition hover:border-sky-400/40 hover:bg-sky-400/10"
                    onClick={() => escolherCpv(item.code)}
                    title={item.description}
                  >
                    <span className="font-medium">{item.code}</span>
                    <span className="max-w-[22rem] truncate text-muted-foreground group-hover:text-foreground">
                      {item.description || "—"}
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {num(item.count)} · {moneyShort(item.value)}
                    </span>
                    <ArrowRight size={12} className="text-muted-foreground" />
                  </button>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {/* concorrência + mercado */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TabelaRanking
              titulo={`${rotuloConcorrente} (pares no segmento)`}
              icon={<Users size={16} />}
              rows={dados.competitors}
              vazio="Sem pares neste segmento."
              destaqueNif={dados.entity.nif ?? undefined}
            />
            <TabelaRanking
              titulo={`${rotuloContraparte} do segmento (mercado)`}
              icon={vender ? <Landmark size={16} /> : <Handshake size={16} />}
              rows={dados.counterparties}
              vazio="Sem contrapartes neste segmento."
            />
          </div>

          {/* historial + oportunidades */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TabelaRanking
              titulo={`Historial: ${rotuloContraparte.toLowerCase()} com contrato`}
              icon={<Handshake size={16} />}
              rows={dados.history}
              vazio="A entidade ainda não tem contratos neste segmento."
            />
            <TabelaRanking
              titulo="Oportunidades"
              icon={<Target size={16} />}
              rows={dados.opportunities}
              vazio="Sem oportunidades novas neste segmento."
              mostrarMotivo
            />
          </div>

          {/* histórico recente */}
          {dados.entity.recent.length > 0 ? (
            <Card>
              <CardHeader className="flex flex-row items-center gap-2 pb-2">
                <Compass size={16} className="text-muted-foreground" />
                <CardTitle className="text-sm">Contratos recentes da entidade no segmento</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <ul className="divide-y divide-border/60">
                  {dados.entity.recent.map((contrato, index) => (
                    <li key={`${contrato.idcontrato ?? index}`} className="flex flex-col gap-1 py-2 md:flex-row md:items-center md:gap-3">
                      <span className="min-w-0 flex-1 truncate text-sm" title={contrato.objecto ?? undefined}>
                        {contrato.objecto || "—"}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">{contrato.counterpart || "—"}</span>
                      <span className="shrink-0 text-sm font-medium tabular-nums">{moneyShort(contrato.value)}</span>
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{shortDate(contrato.date)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {dados.notes.length > 0 ? (
            <div className="rounded-xl border border-border/60 bg-white/5 px-3 py-2 text-xs text-muted-foreground">
              <ul className="list-inside list-disc space-y-0.5">
                {dados.notes.map((nota) => (
                  <li key={nota}>{nota}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
        </>
      )}
        </>
      )}
    </div>
  );
}
