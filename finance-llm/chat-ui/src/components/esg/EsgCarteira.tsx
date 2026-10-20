/**
 * Análise ESG de uma carteira de fornecedores.
 *
 * Duas formas da mesma leitura: a página do módulo (NIFs/nomes escritos pelo
 * analista) e o separador do dossiê de um comprador (carteira já calculada a
 * partir dos contratos). O resultado é o mesmo: distribuição por nível, valor
 * imputado, alertas e a lista com o score de cada fornecedor.
 */
import { useState } from "react";
import { ArrowUpRight, Building2, Loader2, Play, Plus, ShieldAlert, Users } from "lucide-react";

import { analisarCarteiraEsg } from "../../esgApi";
import type { EsgCarteira } from "../../esgApi";
import { EmptyState, Kpi, Loading, SectionCard } from "../padroes/padroesKit";
import { AlertasEsg, EsgBadge, compactEuro, esgCor, num, pct } from "./esgKit";

const INPUT_CLASS =
  "w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-teal-400/50";

function BarraDistribuicao({ item, total }: { item: EsgCarteira["distribuicao"]["niveis"][number]; total: number }) {
  const fracao = total > 0 ? item.n / total : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-[11px]">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.cor || esgCor(item.id) }} />
          {item.label}
        </span>
        <span className="font-mono text-muted-foreground">
          {num(item.n)} · {pct(fracao, 0)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full" style={{ width: `${fracao * 100}%`, backgroundColor: item.cor || esgCor(item.id) }} />
      </div>
    </div>
  );
}

export function CarteiraResultado({
  dados,
  onAbrir,
  titulo = "Carteira de fornecedores",
}: {
  dados: EsgCarteira;
  onAbrir?: (nif: string, nome: string) => void;
  titulo?: string;
}) {
  const fornecedores = dados.fornecedores || [];
  const resumo = dados.resumo;
  const totalNiveis = (dados.distribuicao?.niveis || []).reduce((soma, item) => soma + item.n, 0);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Users} label="Fornecedores" value={num(resumo.n_fornecedores)} sub={`${num(resumo.n_sem_score)} sem score`} />
        <Kpi icon={Building2} label="Score médio ponderado" value={resumo.score_medio_ponderado?.toFixed(1) ?? "—"} sub={`cobertura ${pct(resumo.cobertura_score, 0)} do valor`} color="text-teal-300" glow="glow-teal" />
        <Kpi icon={ShieldAlert} label="Concentração (top 10)" value={pct(resumo.top10_peso, 0)} sub="parte do valor nos 10 maiores" color="text-amber-300" glow="glow-amber" />
        <Kpi icon={ShieldAlert} label="Em nível Inicial/Frágil" value={num(resumo.n_fracos)} sub="prioridade de diálogo ESG" color="text-rose-300" glow="glow-rose" />
      </div>

      <AlertasEsg alertas={dados.alertas} />

      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <SectionCard title="Distribuição por nível" subtitle="Nº de fornecedores e peso no valor." icon={ShieldAlert}>
          {totalNiveis === 0 ? (
            <EmptyState>Sem fornecedores identificados.</EmptyState>
          ) : (
            <div className="space-y-3">
              {(dados.distribuicao?.niveis || []).map((item) => (
                <BarraDistribuicao key={item.id} item={item} total={totalNiveis} />
              ))}
            </div>
          )}
          <p className="mt-3 text-[11px] text-muted-foreground">{dados.metodologia}</p>
        </SectionCard>

        <SectionCard title={titulo} subtitle={`${num(fornecedores.length)} fornecedor(es) · valor imputado ${compactEuro(resumo.valor_total)}`} icon={Users}>
          {fornecedores.length === 0 ? (
            <EmptyState>A empresa não tem contratos como comprador (ou os fornecedores não estão identificados no portal).</EmptyState>
          ) : (
            <div className="max-h-[420px] overflow-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="sticky top-0 bg-[#0b1116] text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr className="border-b border-white/10">
                    <th className="py-2 pr-3">Fornecedor</th>
                    <th className="py-2 pr-3">Score</th>
                    <th className="py-2 pr-3">Pilares</th>
                    <th className="py-2 pr-3">Contratos</th>
                    <th className="py-2 pr-3">Valor</th>
                    <th className="py-2 pr-3">Peso</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {fornecedores.map((item) => (
                    <tr key={`${item.nif || item.nome}-${item.contratos}`} className="border-b border-white/5 hover:bg-white/[0.03]">
                      <td className="max-w-[240px] py-2 pr-3">
                        <span className="block truncate" title={item.nome}>{item.nome}</span>
                        <span className="font-mono text-[10px] text-muted-foreground">{item.nif || "sem NIF"} · {item.setor_label || "setor n/d"}</span>
                      </td>
                      <td className="py-2 pr-3">
                        <EsgBadge score={item.score} nivel={item.nivel} nivelLabel={item.nivel_label} cor={item.cor} compact />
                      </td>
                      <td className="py-2 pr-3 font-mono text-[10px] text-muted-foreground">
                        E {item.pilares?.e?.toFixed(0) ?? "—"} · S {item.pilares?.s?.toFixed(0) ?? "—"} · G {item.pilares?.g?.toFixed(0) ?? "—"}
                      </td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{num(item.contratos)}</td>
                      <td className="py-2 pr-3 text-[11px] text-muted-foreground">{compactEuro(item.valor)}</td>
                      <td className="py-2 pr-3 font-mono text-[11px] text-muted-foreground">{pct(item.peso, 1)}</td>
                      <td className="py-2 text-right">
                        {onAbrir && item.nif && (
                          <button onClick={() => onAbrir(item.nif!, item.nome)} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground">
                            Dossiê <ArrowUpRight size={12} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

export function EsgCarteiraPage({ onAbrir }: { onAbrir?: (nif: string, nome: string) => void }) {
  const [nifs, setNifs] = useState("");
  const [nomes, setNomes] = useState("");
  const [pais, setPais] = useState("PT");
  const [calcular, setCalcular] = useState(true);
  const [dados, setDados] = useState<EsgCarteira | null>(null);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(false);

  const analisar = () => {
    const listaNifs = nifs.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean);
    const listaNomes = nomes.split(/[\n;]+/).map((item) => item.trim()).filter(Boolean);
    if (listaNifs.length === 0 && listaNomes.length === 0) {
      setErro("Indique pelo menos um NIF ou nome de fornecedor.");
      return;
    }
    setCarregando(true);
    setErro("");
    analisarCarteiraEsg({ nifs: listaNifs, nomes: listaNomes, pais, calcular_em_falta: calcular })
      .then((resposta) => {
        setDados({
          distribuicao: {
            niveis: (resposta.resumo?.distribuicao || []).map((item) => ({
              ...item,
              valor: 0,
              peso_n: null,
              peso_valor: null,
            })),
          },
          fornecedores: (resposta.itens || []).map((item) => ({
            nif: item.nif,
            nome: item.nome || item.nif,
            contratos: item.contratos || 0,
            valor: item.valor || 0,
            ecologicos: 0,
            ajuste_direto: 0,
            sociais: 0,
            score: item.score,
            nivel: item.nivel,
            nivel_label: item.nivel_label,
            cor: item.cor,
            pilares: item.pilares || {},
            cobertura: item.cobertura,
            dimensao: item.dimensao,
            dimensao_label: item.dimensao_label,
            setor: item.setor,
            setor_label: item.setor_label,
            tem_score: item.score !== null,
          })),
          alertas: resposta.alertas || [],
          metodologia: resposta.metodologia,
          resumo: {
            n_fornecedores: resposta.resumo?.n ?? 0,
            score_medio_ponderado: resposta.resumo?.score_medio ?? null,
            cobertura_score: resposta.resumo?.cobertura_media ?? null,
            n_sem_score: (resposta.resumo?.n ?? 0) - (resposta.resumo?.com_score ?? 0),
            n_fracos: (resposta.itens || []).filter((item) => item.nivel === "inicial" || item.nivel === "fraco").length,
            valor_total: (resposta.itens || []).reduce((soma, item) => soma + (item.valor || 0), 0),
            top10_peso: null,
          },
        });
      })
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível analisar a carteira."))
      .finally(() => setCarregando(false));
  };

  return (
    <div className="space-y-4">
      <SectionCard
        title="Analisar uma carteira de fornecedores"
        subtitle="Cole os NIFs ou os nomes; cada fornecedor é pontuado com o mesmo motor ESG do dossiê."
        icon={Users}
      >
        <div className="grid gap-3 lg:grid-cols-2">
          <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
            NIFs (separados por vírgula, espaço ou linha)
            <textarea value={nifs} onChange={(e) => setNifs(e.target.value)} rows={4} placeholder="500197814, 503504564" className={`${INPUT_CLASS} font-mono`} />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
            Nomes (um por linha)
            <textarea value={nomes} onChange={(e) => setNomes(e.target.value)} rows={4} placeholder={"Mota-Engil\nEDP"} className={INPUT_CLASS} />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            País
            <select value={pais} onChange={(e) => setPais(e.target.value)} className="rounded-xl border border-white/10 bg-[#0b1116] px-2.5 py-2 text-sm normal-case tracking-normal text-foreground">
              <option value="PT">Portugal</option>
              <option value="ES">Espanha</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <input type="checkbox" checked={calcular} onChange={(e) => setCalcular(e.target.checked)} className="accent-teal-400" />
            Calcular quem ainda não tem fotografia ESG
          </label>
          <button onClick={analisar} disabled={carregando} className="ml-auto flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-4 py-2 text-sm text-teal-200 disabled:opacity-40">
            {carregando ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Analisar carteira
          </button>
        </div>
        {erro && <div className="mt-3"><EmptyState tone="warn">{erro}</EmptyState></div>}
      </SectionCard>

      {carregando && <Loading label="A calcular a carteira…" />}
      {dados && !carregando && <CarteiraResultado dados={dados} onAbrir={onAbrir} />}
      {!dados && !carregando && (
        <EmptyState>
          <span className="flex items-center gap-1.5">
            <Plus size={13} /> Indique os fornecedores para ver a distribuição por nível ESG, o valor imputado e os alertas.
          </span>
        </EmptyState>
      )}
    </div>
  );
}
