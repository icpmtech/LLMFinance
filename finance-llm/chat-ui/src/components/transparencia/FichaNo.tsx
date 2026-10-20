/**
 * Ficha de um nó do Grafo da Transparência (pessoa, cargo, entidade ou empresa).
 *
 * Usada em dois sítios com o mesmo conteúdo: no painel lateral do grafo e no
 * mapa, quando se clica numa empresa. Mostra a sede (com a precisão da
 * geocodificação), as ligações a titulares/entidades e, nas empresas, a
 * **contratação pública** do NIF no portal BASE.
 */
import { Building2, ExternalLink, Landmark, Layers, Loader2, MapPin, Network, UserRound } from "lucide-react";

import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { TG_CORES } from "./grafo";
import type { TgMeta, TgNoDetalhe } from "../../transparenciaGrafoApi";

const TIPO_ICONE: Record<string, typeof UserRound> = {
  pessoa: UserRound,
  cargo: Layers,
  entidade: Landmark,
  empresa: Building2,
};

const ROTULOS_DETALHE: Record<string, string> = {
  entidades: "Entidade",
  funcao: "Cargo/função",
  inicio: "Início",
  fim: "Termo",
  remunerado: "Remuneração",
  objeto: "Objeto",
  percentagem: "Percentagem",
  quota: "Quota",
  apoio: "Apoio",
  descricao: "Descrição",
  servico: "Serviço",
  data: "Data",
  natureza: "Natureza",
  declaracao: "Declaração",
};

const numero = new Intl.NumberFormat("pt-PT");
const euro = new Intl.NumberFormat("pt-PT", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});
const euroCompacto = new Intl.NumberFormat("pt-PT", {
  style: "currency",
  currency: "EUR",
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatarEuro(valor?: number | null): string {
  const numeroValor = Number(valor ?? 0);
  if (Math.abs(numeroValor) >= 1_000_000) return euroCompacto.format(numeroValor);
  return euro.format(numeroValor);
}

export function anosTexto(anos?: number[]): string {
  if (!anos?.length) return "—";
  if (anos.length === 1) return String(anos[0]);
  return `${anos[0]}–${anos[anos.length - 1]}`;
}

export function formatarDetalhe(detalhe: Record<string, unknown>): { rotulo: string; valor: string }[] {
  const saida: { rotulo: string; valor: string }[] = [];
  for (const [chave, valor] of Object.entries(detalhe || {})) {
    if (valor === null || valor === undefined || valor === "") continue;
    const texto = Array.isArray(valor) ? valor.filter(Boolean).join(", ") : String(valor);
    if (!texto) continue;
    saida.push({ rotulo: ROTULOS_DETALHE[chave] ?? chave, valor: texto });
  }
  return saida;
}

export function FichaNo({
  detalhe,
  carregando = false,
  meta,
  onAbrir,
  onVerNoGrafo,
  mostrarVerNoGrafo = true,
  vazio,
}: {
  detalhe: TgNoDetalhe | null;
  carregando?: boolean;
  meta: TgMeta | null;
  onAbrir?: (noId: string) => void;
  onVerNoGrafo?: (noId: string) => void;
  mostrarVerNoGrafo?: boolean;
  vazio?: React.ReactNode;
}) {
  if (carregando || (detalhe && !detalhe.no)) {
    return (
      <p className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Loader2 size={13} className="animate-spin" /> a abrir…
      </p>
    );
  }
  if (!detalhe) {
    return <>{vazio ?? <p className="text-[11.5px] text-muted-foreground">Selecione um nó para ver a ficha.</p>}</>;
  }

  const no = detalhe.no;
  const Icone = TIPO_ICONE[no.tipo] ?? Layers;
  const contratacao = detalhe.contratacao;

  return (
    <div className="space-y-3">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Icone size={15} style={{ color: TG_CORES[no.tipo] }} />
          <span className="min-w-0 break-words">{no.nome}</span>
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
          <Badge variant="secondary">{meta?.tipos?.[no.tipo]?.curto ?? no.tipo}</Badge>
          {no.nif && <span>NIF {no.nif}</span>}
          {no.anos?.length ? <span>· {anosTexto(no.anos)}</span> : null}
        </p>
      </div>

      {no.local_sede && (
        <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5 text-[11px]">
          <p className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            <MapPin size={10} /> Sede
          </p>
          <p className="text-foreground">{no.concelho ?? no.local_sede}</p>
          <p className="text-[10px] text-muted-foreground">
            {no.local_sede}
            {no.precisao_geo ? ` · ${meta?.precisoes?.[no.precisao_geo] ?? no.precisao_geo}` : ""}
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Ligações</p>
          <p className="text-foreground">{numero.format(no.grau ?? 0)}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Declarações</p>
          <p className="text-foreground">{numero.format(no.declaracoes ?? 0)}</p>
        </div>
      </div>

      {no.nif && (
        <div className="rounded-lg border border-sky-400/25 bg-sky-400/5 px-2 py-1.5 text-[11px]">
          <p className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-sky-200/80">
            <Building2 size={10} /> Contratação pública · portal BASE
          </p>
          {contratacao ? (
            contratacao.disponivel ? (
              contratacao.contratos ? (
                <>
                  <p className="text-foreground">
                    {numero.format(contratacao.contratos)} contrato(s) ·{" "}
                    <span className="font-medium">{formatarEuro(contratacao.valor)}</span>
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {contratacao.adjudicantes?.length
                      ? `Principais adjudicantes (maiores contratos): ${contratacao.adjudicantes.join(" · ")}`
                      : "Sem adjudicantes identificados"}
                  </p>
                  <p className="text-[10px] text-muted-foreground">{anosTexto(contratacao.anos)}</p>
                </>
              ) : (
                <p className="text-muted-foreground">Sem contratos públicos registados para este NIF.</p>
              )
            ) : (
              <p className="text-muted-foreground">Índice de contratos indisponível neste momento.</p>
            )
          ) : (
            <p className="text-muted-foreground">A carregar contratação pública…</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {mostrarVerNoGrafo && onVerNoGrafo && (
          <Button size="sm" variant="outline" icon={<Network size={12} />} onClick={() => onVerNoGrafo(no.no_id)}>
            Ver no grafo
          </Button>
        )}
        {no.tipo === "pessoa" && (
          <a
            href={`/entidade-transparencia?titular=${encodeURIComponent(no.ref_id ?? "")}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <ExternalLink size={12} /> Declarações
          </a>
        )}
        {no.tipo === "empresa" && no.nif && (
          <a
            href={`/empresas-iq/${encodeURIComponent(no.nif)}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <ExternalLink size={12} /> EmpresasIQ
          </a>
        )}
      </div>

      <div className="space-y-1.5">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {numero.format(detalhe.total_vizinhos)} ligações
        </p>
        {detalhe.vizinhos.map((vizinho, indice) => {
          const IconeVizinho = TIPO_ICONE[vizinho.no.type] ?? Layers;
          return (
            <button
              key={`${vizinho.no.id}-${vizinho.relacao}-${indice}`}
              type="button"
              onClick={() => onAbrir?.(vizinho.no.id)}
              className="w-full rounded-lg border border-border/70 bg-muted/30 px-2 py-1.5 text-left hover:bg-muted/60"
            >
              <p className="flex items-center gap-1.5 text-[11.5px] text-foreground">
                <IconeVizinho size={12} style={{ color: TG_CORES[vizinho.no.type] }} />
                <span className="min-w-0 flex-1 truncate">{vizinho.no.label}</span>
                <span className="shrink-0 text-[10px] text-muted-foreground">×{vizinho.peso}</span>
              </p>
              <p className="pl-4 text-[10px] text-muted-foreground">
                {vizinho.sentido === "saida" ? vizinho.relacao_label : `← ${vizinho.relacao_label}`}
                {vizinho.anos.length ? ` · ${anosTexto(vizinho.anos)}` : ""}
              </p>
              {formatarDetalhe(vizinho.detalhe).slice(0, 3).map((item) => (
                <p key={item.rotulo} className="truncate pl-4 text-[9.5px] text-muted-foreground/80">
                  {item.rotulo}: {item.valor}
                </p>
              ))}
            </button>
          );
        })}
        {!detalhe.vizinhos.length && (
          <p className="text-[11px] text-muted-foreground">
            Este nó não tem ligações no grafo (aparece apenas como referência).
          </p>
        )}
      </div>
    </div>
  );
}
