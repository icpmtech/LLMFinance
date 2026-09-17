/**
 * Cartões de indicadores (KPIs) de um ticker.
 *
 * Os KPIs do `TickerInfo.kpis` vêm do Yahoo Finance como números crus: rácios
 * (P/E, P/BV), percentagens em fração (margens, ROE, variação 52 semanas),
 * valores monetários (receitas, dívida, caixa), contagens (ações, analistas) e
 * escalas (recomendação 1-5). Uma heurística única — «se for pequeno é
 * percentagem» — mostrada em badges soltos dava resultados errados
 * (ex.: nº de analistas 19 → «1900%», valor contabilístico 9,66 → «965,60%»).
 *
 * Aqui cada indicador tem o seu formato declarado e os KPIs ficam agrupados por
 * tema em cartões: Valorização, Margens & crescimento, Resultados, Balanço,
 * Analistas & preços-alvo e Mercado & capital.
 */
import { Activity, BarChart3, DollarSign, Layers, PieChart, Target, TrendingUp } from "lucide-react";

type KpiFormat =
  /** Fração (0,26 → 26,00%). */
  | "percent"
  /** Rácio simples (16,02). */
  | "ratio"
  /** Escala de 1 a 5 (recomendação dos analistas). */
  | "scale"
  /** Valor monetário (usa a moeda do ticker). */
  | "currency"
  /** Valor monetário grande, abreviado (3,92 B). */
  | "compactCurrency"
  /** Contagem inteira (19). */
  | "count"
  /** Contagem grande, abreviada (7,70 B). */
  | "compactCount"
  /** Número simples. */
  | "plain";

type KpiSpec = { key: string; label: string; format: KpiFormat; hint?: string; /** Mostra o sinal «+» (variações e crescimentos). */ signed?: boolean };

type KpiGroup = { id: string; title: string; icon: typeof TrendingUp; specs: KpiSpec[] };

/** Grupos e formatação de cada indicador (a ordem é a ordem no cartão). */
const KPI_GROUPS: KpiGroup[] = [
  {
    id: "valuation",
    title: "Valorização",
    icon: TrendingUp,
    specs: [
      { key: "trailingPE", label: "P/E (12M)", format: "ratio", hint: "Preço / lucro dos últimos 12 meses" },
      { key: "forwardPE", label: "P/E estimado", format: "ratio", hint: "Preço / lucro estimado para o próximo ano" },
      { key: "priceToBook", label: "P/BV", format: "ratio", hint: "Preço / valor contabilístico" },
      { key: "priceToSalesTrailing12Months", label: "P/Vendas", format: "ratio" },
      { key: "enterpriseValue", label: "Enterprise value", format: "compactCurrency", hint: "Capitalização + dívida líquida" },
      { key: "enterpriseToRevenue", label: "EV/Vendas", format: "ratio" },
      { key: "enterpriseToEbitda", label: "EV/EBITDA", format: "ratio" },
      { key: "bookValue", label: "Valor contab. / ação", format: "currency" },
      { key: "totalDebtPerShare", label: "Dívida / ação", format: "currency" },
    ],
  },
  {
    id: "margins",
    title: "Margens & crescimento",
    icon: PieChart,
    specs: [
      { key: "grossMargins", label: "Margem bruta", format: "percent" },
      { key: "ebitdaMargins", label: "Margem EBITDA", format: "percent" },
      { key: "operatingMargins", label: "Margem operacional", format: "percent" },
      { key: "profitMargins", label: "Margem líquida", format: "percent" },
      { key: "revenueGrowth", label: "Crescimento das receitas", format: "percent", signed: true },
      { key: "earningsGrowth", label: "Crescimento dos lucros", format: "percent", signed: true },
      { key: "returnOnAssets", label: "ROA", format: "percent", hint: "Rentabilidade dos ativos" },
      { key: "returnOnEquity", label: "ROE", format: "percent", hint: "Rentabilidade dos capitais próprios" },
    ],
  },
  {
    id: "results",
    title: "Resultados (12 meses)",
    icon: BarChart3,
    specs: [
      { key: "totalRevenue", label: "Receitas totais", format: "compactCurrency" },
      { key: "grossProfits", label: "Lucro bruto", format: "compactCurrency" },
      { key: "ebitda", label: "EBITDA", format: "compactCurrency" },
      { key: "netIncomeToCommon", label: "Lucro líquido", format: "compactCurrency" },
      { key: "trailingEps", label: "EPS (12M)", format: "currency", hint: "Lucro por ação" },
      { key: "forwardEps", label: "EPS estimado", format: "currency" },
      { key: "revenuePerShare", label: "Receita / ação", format: "currency" },
    ],
  },
  {
    id: "balance",
    title: "Balanço & liquidez",
    icon: DollarSign,
    specs: [
      { key: "totalCash", label: "Caixa total", format: "compactCurrency" },
      { key: "totalDebt", label: "Dívida total", format: "compactCurrency" },
      { key: "currentRatio", label: "Rácio corrente", format: "ratio", hint: "Ativo corrente / passivo corrente" },
      { key: "quickRatio", label: "Rácio rápido", format: "ratio", hint: "Liquidez imediata (sem inventários)" },
    ],
  },
  {
    id: "analysts",
    title: "Analistas & preços-alvo",
    icon: Target,
    specs: [
      { key: "targetLowPrice", label: "Alvo mínimo", format: "currency" },
      { key: "targetMedianPrice", label: "Alvo mediano", format: "currency" },
      { key: "targetMeanPrice", label: "Alvo médio", format: "currency" },
      { key: "targetHighPrice", label: "Alvo máximo", format: "currency" },
      { key: "recommendationMean", label: "Recomendação média", format: "scale", hint: "1 = compra forte · 5 = venda forte" },
      { key: "numberOfAnalystOpinions", label: "Nº de analistas", format: "count" },
    ],
  },
  {
    id: "market",
    title: "Mercado & capital",
    icon: Layers,
    specs: [
      { key: "currentPrice", label: "Preço atual", format: "currency" },
      { key: "beta", label: "Beta", format: "ratio", hint: "Volatilidade face ao mercado" },
      { key: "52WeekChange", label: "Variação 52 semanas", format: "percent", signed: true },
      { key: "SandP52WeekChange", label: "Variação S&P 500 (52S)", format: "percent", signed: true },
      { key: "sharesOutstanding", label: "Ações emitidas", format: "compactCount" },
      { key: "impliedSharesOutstanding", label: "Ações implícitas", format: "compactCount" },
      { key: "floatShares", label: "Ações em circulação (float)", format: "compactCount" },
      { key: "heldPercentInsiders", label: "Capital (insiders)", format: "percent" },
      { key: "heldPercentInstitutions", label: "Capital (institucional)", format: "percent" },
      { key: "shortRatio", label: "Short ratio (dias)", format: "ratio" },
      { key: "shortPercentOfFloat", label: "Short % do float", format: "percent" },
    ],
  },
];

/** Etiquetas conhecidas, indexadas por chave (para valores fora dos grupos). */
const SPEC_BY_KEY = new Map<string, KpiSpec>(
  KPI_GROUPS.flatMap((group) => group.specs.map((spec) => [spec.key, spec] as const)),
);

/** Etiquetas legíveis para chaves conhecidas do Yahoo que não estão nos grupos. */
const EXTRA_LABELS: Record<string, string> = {
  marketCap: "Capitalização bolsista",
  dividendYield: "Dividend yield",
  trailingAnnualDividendYield: "Dividend yield (12M)",
  payoutRatio: "Rácio de distribuição",
  earningsPerShare: "EPS",
  debtToEquity: "Dívida / capitais próprios",
  freeCashflow: "Cash-flow livre",
  operatingCashflow: "Cash-flow operacional",
  totalAssets: "Ativo total",
  totalLiabilities: "Passivo total",
  netDebt: "Dívida líquida",
  pegRatio: "PEG",
  enterpriseToEbitdaMargin: "EV/EBITDA",
  regularMarketPrice: "Preço de mercado",
  regularMarketChangePercent: "Variação do dia",
  fiftyTwoWeekHigh: "Máximo 52 semanas",
  fiftyTwoWeekLow: "Mínimo 52 semanas",
  averageVolume: "Volume médio",
  volume: "Volume",
  numberOfEmployees: "Nº de colaboradores",
};

const PERCENT_SUSPECT_KEYS = new Set([
  "heldPercentInsiders",
  "heldPercentInstitutions",
  "shortPercentOfFloat",
  "grossMargins",
  "ebitdaMargins",
  "operatingMargins",
  "profitMargins",
  "revenueGrowth",
  "earningsGrowth",
  "returnOnAssets",
  "returnOnEquity",
  "52WeekChange",
  "SandP52WeekChange",
]);

/** Formato por omissão de uma chave desconhecida, a partir do nome. */
function guessFormat(key: string): KpiFormat {
  if (PERCENT_SUSPECT_KEYS.has(key)) return "percent";
  if (/percent|margin|growth|yield|change/i.test(key)) return "percent";
  if (/count|shares|volume|employees|opinions|analyst/i.test(key)) return "compactCount";
  if (/price|revenue|profit|cash|debt|ebitda|income|value|assets|liabilities/i.test(key)) return "compactCurrency";
  return "plain";
}

function decimals(value: number) {
  const abs = Math.abs(value);
  if (abs === 0) return 2;
  if (abs < 1) return 3;
  return 2;
}

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString("pt-PT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Abreviação compacta em pt-PT (1,23 mM / 3,92 B) — usada em valores grandes. */
function compact(value: number) {
  return new Intl.NumberFormat("pt-PT", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function recommendationLabel(value: number): string {
  if (value <= 1.5) return "compra forte";
  if (value <= 2.5) return "compra";
  if (value <= 3.5) return "neutro";
  if (value <= 4.5) return "venda";
  return "venda forte";
}

/** Valor formatado de um indicador, segundo o seu tipo. */
export function formatKpi(spec: KpiSpec, value: number, currency?: string | null): string {
  const unit = currency && currency !== "N/A" ? ` ${currency}` : "";
  switch (spec.format) {
    case "percent": {
      const percent = value * 100;
      const sign = spec.signed && percent > 0 ? "+" : "";
      return `${sign}${formatNumber(percent)}%`;
    }
    case "ratio":
      return formatNumber(value, decimals(value));
    case "scale":
      return `${formatNumber(value, 2)} · ${recommendationLabel(value)}`;
    case "currency":
      return `${formatNumber(value, decimals(value))}${unit}`;
    case "compactCurrency":
      return `${compact(value)}${unit}`;
    case "count":
      return formatNumber(value, 0);
    case "compactCount":
      return Math.abs(value) >= 10_000 ? compact(value) : formatNumber(value, 0);
    default:
      return formatNumber(value, decimals(value));
  }
}

type Row = { key: string; label: string; text: string; raw: number; spec: KpiSpec };

function buildRows(kpis: Record<string, number> | undefined, currency: string | undefined | null) {
  const groups = KPI_GROUPS.map((group) => {
    const rows: Row[] = [];
    for (const spec of group.specs) {
      const raw = kpis?.[spec.key];
      if (typeof raw !== "number" || Number.isNaN(raw)) continue;
      rows.push({ key: spec.key, label: spec.label, text: formatKpi(spec, raw, currency), raw, spec });
    }
    return { ...group, rows };
  }).filter((group) => group.rows.length > 0);

  const used = new Set(groups.flatMap((group) => group.rows.map((row) => row.key)));
  const extras: Row[] = Object.entries(kpis ?? {})
    .filter(([key, value]) => !used.has(key) && typeof value === "number" && !Number.isNaN(value))
    .map(([key, value]) => {
      const spec: KpiSpec = { key, label: EXTRA_LABELS[key] ?? key.replace(/([A-Z])/g, " $1").trim(), format: guessFormat(key) };
      return { key, label: spec.label, text: formatKpi(spec, value, currency), raw: value, spec };
    });

  if (extras.length > 0) {
    groups.push({ id: "other", title: "Outros indicadores", icon: Activity, specs: [], rows: extras });
  }
  return groups;
}

/** Cartões temáticos com os indicadores do ticker. */
export function TickerKpiCards({
  kpis,
  currency,
  className = "",
}: {
  kpis?: Record<string, number>;
  currency?: string | null;
  className?: string;
}) {
  const groups = buildRows(kpis, currency);
  if (groups.length === 0) return null;

  return (
    <div className={`grid gap-4 @2xl:grid-cols-2 @5xl:grid-cols-3 ${className}`}>
      {groups.map((group) => {
        const Icon = group.icon;
        return (
          <section
            key={group.id}
            className="min-w-0 rounded-xl gradient-border glass-card p-4"
            aria-label={group.title}
          >
            <header className="mb-3 flex items-center gap-2">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-cyan-500/15 text-cyan-400">
                <Icon size={15} />
              </span>
              <h3 className="min-w-0 truncate text-sm font-semibold text-white">{group.title}</h3>
              <span className="ml-auto shrink-0 text-[10.5px] text-slate-500">{group.rows.length}</span>
            </header>
            <dl className="space-y-1.5">
              {group.rows.map((row) => {
                const negative = row.spec.format === "percent" && row.raw < 0;
                const positive = row.spec.format === "percent" && row.raw > 0;
                return (
                  <div
                    key={row.key}
                    className="flex items-baseline justify-between gap-3 border-b border-white/5 pb-1 last:border-0 last:pb-0"
                    title={`${row.key} = ${row.raw}${row.spec.hint ? ` — ${row.spec.hint}` : ""}`}
                  >
                    <dt className="min-w-0 truncate text-[12px] text-slate-400">{row.label}</dt>
                    <dd
                      className={[
                        "shrink-0 whitespace-nowrap text-[12.5px] font-medium tabular-nums",
                        negative ? "text-rose-300" : positive ? "text-teal-300" : "text-white",
                      ].join(" ")}
                    >
                      {row.text}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        );
      })}
    </div>
  );
}

/** Chaves conhecidas (para documentação/diagnóstico). */
export const KNOWN_KPI_KEYS = [...SPEC_BY_KEY.keys()];
