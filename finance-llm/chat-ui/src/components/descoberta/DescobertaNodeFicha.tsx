/**
 * Ficha de um **nó do grafo**: o que aquela bolha é, que números tem, com quem
 * se liga e o que a plataforma sabe dela.
 *
 * O grafo identifica os nós por pictograma (tipo) e tamanho (métrica); o nome, o
 * identificador, as ligações e a evidência estão aqui, para o grafo poder ficar
 * limpo. As ações (isolar a vizinhança, ver só este tipo, esconder o tipo, abrir
 * no módulo certo) estão no rodapé — as mesmas do menu do lado direito do grafo.
 */
import { useEffect } from "react";
import { Copy, ExternalLink, Eye, EyeOff, Focus, X } from "lucide-react";
import { Badge, Button } from "../ui";
import { formatCompact, formatMoney, typeLabel } from "../graph/graphStudio";
import { DIMENSAO_LABEL, corDoNo } from "./descobertaGrafo";
import type { StudioGraph, StudioNode } from "../graph/graphStudio";

type Bloco = { titulo: string; itens: { rotulo: string; valor: string }[] };

const lista = <T,>(valor: unknown): T[] => (Array.isArray(valor) ? (valor as T[]) : []);
const texto = (valor: unknown): string => (valor === null || valor === undefined ? "" : String(valor));
const numero = (valor: unknown): number => {
  const convertido = Number(valor);
  return Number.isFinite(convertido) ? convertido : 0;
};

/**
 * Evidência da plataforma para o nó, lida das secções já recolhidas.
 *
 * Não vai buscar nada de novo: o painel já tem os contratos, as pessoas, os
 * processos e a imprensa em memória — a ficha só os filtra pelo nó.
 */
function evidenciaDoNo(node: StudioNode, secoes: Record<string, Record<string, unknown>>): Bloco[] {
  const chave = String(node.key ?? node.id.split(":").slice(1).join(":"));
  const dimensao = String(node.dimension || node.type || "").toLowerCase();
  const contratos = lista<Record<string, unknown>>((secoes.contratos as Record<string, unknown>)?.contratos);
  const blocos: Bloco[] = [];

  if (dimensao === "empresa") {
    const cadastro = (secoes.cadastro as Record<string, unknown>)?.cadastro as Record<string, unknown> | undefined;
    const resumo = ((secoes.contratos as Record<string, unknown>)?.resumo as Record<string, unknown>) || {};
    blocos.push({
      titulo: "Cadastro e contratação",
      itens: [
        { rotulo: "Nome", valor: texto(cadastro?.name) || node.label },
        { rotulo: "NIF", valor: chave },
        { rotulo: "Contratos lidos", valor: formatCompact(node.count) },
        { rotulo: "Valor", valor: formatMoney(node.total_value) },
        { rotulo: "Valor mediano", valor: formatMoney(numero(resumo.valor_mediano)) },
        { rotulo: "Ajuste direto", valor: `${Math.round(numero(resumo.taxa_ajuste_direto) * 100)} %` },
      ],
    });
    // Sinais do padrão de contratação que tocam a empresa analisada.
    const sinais = lista<Record<string, unknown>>((secoes.contratos as Record<string, unknown>)?.sinais);
    if (sinais.length) {
      blocos.push({
        titulo: `Sinais (${sinais.length})`,
        itens: sinais.slice(0, 8).map((sinal) => ({
          rotulo: texto(sinal.padrao),
          valor: `${texto(sinal.detalhe)}${sinal.total ? ` · ${formatCompact(numero(sinal.total))}` : ""}`,
        })),
      });
    }
    return blocos;
  }

  if (dimensao === "adjudicante") {
    const adjudicantes = lista<Record<string, unknown>>((secoes.rede as Record<string, unknown>)?.adjudicantes);
    const registo = adjudicantes.find((item) => texto(item.nif) === chave);
    const meus = contratos.filter((contrato) => texto(contrato.adjudicante_nif) === chave);
    blocos.push({
      titulo: "Comprador",
      itens: [
        { rotulo: "Nome", valor: texto(registo?.nome) || node.label },
        { rotulo: "NIF", valor: chave },
        { rotulo: "Contratos", valor: formatCompact(meus.length || node.count) },
        { rotulo: "Valor", valor: formatMoney(registo ? numero(registo.valor) : node.total_value) },
        { rotulo: "Quota no valor", valor: registo ? `${(numero(registo.quota) * 100).toFixed(1)} %` : "—" },
      ],
    });
    if (meus.length) {
      blocos.push({
        titulo: `Contratos com este comprador (${meus.length})`,
        itens: meus
          .slice()
          .sort((a, b) => numero(b.valor) - numero(a.valor))
          .slice(0, 6)
          .map((contrato) => ({
            rotulo: texto(contrato.ano),
            valor: `${formatMoney(numero(contrato.valor))} · ${texto(contrato.objeto).slice(0, 70)}`,
          })),
      });
    }
    return blocos;
  }

  if (dimensao === "cpv") {
    const classe = chave.split("-")[0];
    const meus = contratos.filter((contrato) => texto(contrato.cpv).replace("-", "").startsWith(classe.slice(0, 4)));
    const valor = meus.reduce((total, contrato) => total + numero(contrato.valor), 0);
    blocos.push({
      titulo: "Classificação",
      itens: [
        { rotulo: "CPV", valor: chave },
        { rotulo: "Descrição", valor: texto(meus[0]?.cpv_desc) || node.label },
        { rotulo: "Contratos", valor: formatCompact(meus.length || node.count) },
        { rotulo: "Valor", valor: formatMoney(valor || node.total_value) },
        { rotulo: "Valor médio", valor: meus.length ? formatMoney(valor / meus.length) : "—" },
      ],
    });
    if (meus.length) {
      blocos.push({
        titulo: "Contratos nesta classificação",
        itens: meus
          .slice()
          .sort((a, b) => numero(b.valor) - numero(a.valor))
          .slice(0, 6)
          .map((contrato) => ({
            rotulo: `${texto(contrato.ano)} · ${texto(contrato.adjudicante).slice(0, 30)}`,
            valor: `${formatMoney(numero(contrato.valor))} · ${texto(contrato.objeto).slice(0, 60)}`,
          })),
      });
    }
    return blocos;
  }

  if (dimensao === "pessoa") {
    const pessoas = lista<Record<string, unknown>>((secoes.pessoas as Record<string, unknown>)?.pessoas);
    const cargosSociais = lista<Record<string, unknown>>((secoes.rede as Record<string, unknown>)?.cargos_sociais);
    const pessoa = pessoas.find((item) => texto(item.nif) === chave);
    const ligada = cargosSociais.find((item) => texto(item.nif) === chave);
    const cargos = lista<Record<string, unknown>>(pessoa?.roles || ligada?.cargos);
    blocos.push({
      titulo: "Pessoa",
      itens: [
        { rotulo: "Nome", valor: texto(pessoa?.name || pessoa?.nome || ligada?.nome) || node.label },
        { rotulo: "NIF", valor: chave || "—" },
        { rotulo: "Cargos nesta empresa", valor: formatCompact(numero(pessoa?.cargos_empresa) || cargos.length || node.count) },
        ...(pessoa?.roles_total ? [{ rotulo: "Cargos no total", valor: formatCompact(numero(pessoa.roles_total)) }] : []),
        ...(pessoa?.companies_total && numero(pessoa.companies_total) > 1
          ? [{ rotulo: "Empresas", valor: formatCompact(numero(pessoa.companies_total)) }]
          : []),
      ],
    });
    if (cargos.length) {
      blocos.push({
        titulo: `Cargos (${cargos.length})`,
        itens: cargos.slice(0, 8).map((cargo) => ({
          rotulo: texto(cargo.date).slice(0, 10) || "—",
          valor: [texto(cargo.role_org), texto(cargo.role), texto(cargo.acto)].filter(Boolean).join(" · ") || "cargo registado",
        })),
      });
    }
    return blocos;
  }

  if (dimensao === "processo") {
    const insolvencias = lista<Record<string, unknown>>((secoes.cire as Record<string, unknown>)?.insolvencias);
    const processo = insolvencias.find((item) => texto(item.processo) === chave || texto(item.id) === chave);
    blocos.push({
      titulo: "Processo do CIRE",
      itens: [
        { rotulo: "Processo", valor: chave || node.label },
        { rotulo: "Espécie", valor: texto(processo?.especie || processo?.ato) || "—" },
        { rotulo: "Tribunal", valor: texto(processo?.tribunal) || "—" },
        { rotulo: "Data", valor: texto(processo?.data).slice(0, 10) || "—" },
        { rotulo: "Papel", valor: texto(processo?.papel) || "interveniente" },
      ],
    });
    if (processo?.objeto) {
      blocos.push({ titulo: "Objeto", itens: [{ rotulo: "Descrição", valor: texto(processo.objeto).slice(0, 240) }] });
    }
    return blocos;
  }

  if (dimensao === "noticia") {
    const noticias = lista<Record<string, unknown>>((secoes.noticias as Record<string, unknown>)?.items);
    const noticia = noticias.find((item) => texto(item.link || item.url) === chave);
    blocos.push({
      titulo: "Menção na imprensa",
      itens: [
        { rotulo: "Título", valor: texto(noticia?.titulo || noticia?.title) || node.label },
        { rotulo: "Fonte", valor: texto(noticia?.fonte || noticia?.source) || "—" },
        { rotulo: "Data", valor: texto(noticia?.data || noticia?.published).slice(0, 10) || "—" },
        { rotulo: "Ligação", valor: chave },
      ],
    });
    return blocos;
  }

  if (dimensao === "firma" || dimensao === "marca") {
    const itens = lista<Record<string, unknown>>(
      ((dimensao === "firma" ? secoes.firmas : secoes.marcas) as Record<string, unknown>)?.items,
    );
    const item = itens.find((candidato) =>
      [texto(candidato.nif), texto(candidato.id), texto(candidato.nome), texto(candidato.firma), texto(candidato.marca)].includes(chave),
    );
    blocos.push({
      titulo: dimensao === "firma" ? "Firma / nome comercial" : "Marca registada",
      itens: [
        { rotulo: "Nome", valor: texto(item?.nome || item?.firma || item?.marca) || node.label },
        { rotulo: "NIF", valor: texto(item?.nif) || chave },
        { rotulo: "Estado", valor: texto(item?.situacao || item?.estado) || "—" },
        { rotulo: "Classe", valor: texto(item?.classe) || "—" },
      ],
    });
    return blocos;
  }

  if (dimensao === "subvencao") {
    const itens = lista<Record<string, unknown>>((secoes.subvencoes as Record<string, unknown>)?.items);
    const item = itens.find((candidato) => texto(candidato.id || candidato.programa) === chave);
    blocos.push({
      titulo: "Subvenção",
      itens: [
        { rotulo: "Programa", valor: texto(item?.programa) || node.label },
        { rotulo: "Entidade", valor: texto(item?.entidade) || "—" },
        { rotulo: "Valor", valor: formatMoney(item ? numero(item.valor) : node.total_value) },
        { rotulo: "Ano", valor: texto(item?.ano) || "—" },
      ],
    });
    return blocos;
  }

  return blocos;
}

export default function DescobertaNodeFicha({
  node,
  grafo,
  secoes,
  onClose,
  onSelecionar,
  onIsolar,
  onVerTipo,
  onEsconderTipo,
  onAbrirNoModulo,
}: {
  node: StudioNode;
  grafo: StudioGraph;
  secoes: Record<string, Record<string, unknown>>;
  onClose: () => void;
  onSelecionar: (nodeId: string) => void;
  onIsolar: (node: StudioNode) => void;
  onVerTipo: (node: StudioNode) => void;
  onEsconderTipo: (node: StudioNode) => void;
  onAbrirNoModulo: (node: StudioNode) => void;
}) {
  useEffect(() => {
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") onClose();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onClose]);

  const cor = node.color || corDoNo(node);
  const dimensao = String(node.dimension || node.type || "outra");
  const ligacoes = grafo.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const outroId = edge.source === node.id ? edge.target : edge.source;
      const outro = grafo.nodes.find((candidato) => candidato.id === outroId);
      return { outro, edge };
    })
    .filter((item): item is { outro: StudioNode; edge: (typeof grafo.edges)[number] } => Boolean(item.outro))
    .sort((a, b) => (b.edge.value || b.edge.count || 0) - (a.edge.value || a.edge.count || 0));
  const totalGrafo = grafo.nodes.reduce((total, candidato) => total + (candidato.total_value || 0), 0);
  const blocos = evidenciaDoNo(node, secoes);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:p-8" onClick={onClose}>
      <div
        className="glass-card gradient-border w-full max-w-3xl rounded-2xl p-4 shadow-2xl"
        onClick={(evento) => evento.stopPropagation()}
        role="dialog"
        aria-label={`Ficha do nó ${node.label}`}
      >
        <header className="flex items-start gap-3">
          <span
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border text-xs font-semibold"
            style={{ borderColor: `${cor}66`, background: `${cor}1a`, color: cor }}
          >
            {DIMENSAO_LABEL[dimensao]?.sigla || typeLabel(node.type || dimensao).slice(0, 2)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold">{node.label}</p>
            <p className="truncate text-xs text-muted-foreground">
              {DIMENSAO_LABEL[dimensao]?.label || typeLabel(node.type || dimensao)} · {node.role || dimensao}
            </p>
            <p className="truncate font-mono text-[11px] text-muted-foreground">{node.id}</p>
          </div>
          <button type="button" className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5" onClick={onClose} aria-label="Fechar ficha">
            <X size={16} />
          </button>
        </header>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-xl border border-white/5 px-2.5 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Contratos</p>
            <p className="truncate text-sm font-semibold tabular-nums">{formatCompact(node.count)}</p>
          </div>
          <div className="rounded-xl border border-white/5 px-2.5 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Valor</p>
            <p className="truncate text-sm font-semibold tabular-nums">{formatMoney(node.total_value)}</p>
          </div>
          <div className="rounded-xl border border-white/5 px-2.5 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Ligações</p>
            <p className="truncate text-sm font-semibold tabular-nums">{ligacoes.length}</p>
          </div>
          <div className="rounded-xl border border-white/5 px-2.5 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Peso no valor</p>
            <p className="truncate text-sm font-semibold tabular-nums">
              {totalGrafo > 0 ? `${(((node.total_value || 0) / totalGrafo) * 100).toFixed(1)} %` : "—"}
            </p>
          </div>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <section className="rounded-xl border border-white/5 p-2.5">
            <p className="mb-1.5 text-xs font-semibold">Ligações no grafo ({ligacoes.length})</p>
            {ligacoes.length ? (
              <ul className="max-h-56 space-y-1 overflow-y-auto text-[11px]">
                {ligacoes.map(({ outro, edge }) => (
                  <li key={`${outro.id}-${edge.relation}`} className="flex items-start justify-between gap-2 border-b border-white/5 pb-1">
                    <button type="button" className="min-w-0 flex-1 text-left hover:text-primary" onClick={() => onSelecionar(outro.id)}>
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: outro.color || corDoNo(outro) }} />
                        <span className="truncate">{outro.label}</span>
                      </span>
                      <span className="truncate text-muted-foreground">
                        {edge.source === node.id ? "→ " : "← "}
                        {edge.relation || "ligação"}
                      </span>
                    </button>
                    <span className="shrink-0 text-right tabular-nums text-muted-foreground">
                      {formatCompact(edge.count)}
                      <br />
                      {formatMoney(edge.value)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[11px] text-muted-foreground">Sem ligações nesta vista.</p>
            )}
          </section>

          <section className="space-y-2">
            {blocos.length ? (
              blocos.map((bloco) => (
                <div key={bloco.titulo} className="rounded-xl border border-white/5 p-2.5">
                  <p className="mb-1.5 text-xs font-semibold">{bloco.titulo}</p>
                  <dl className="space-y-1 text-[11px]">
                    {bloco.itens.map((item, indice) => (
                      <div key={`${item.rotulo}-${indice}`} className="flex justify-between gap-3 border-b border-white/5 pb-1">
                        <dt className="shrink-0 text-muted-foreground">{item.rotulo}</dt>
                        <dd className="min-w-0 truncate text-right" title={item.valor}>
                          {item.valor}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))
            ) : (
              <p className="rounded-xl border border-white/5 p-2.5 text-[11px] text-muted-foreground">
                Sem evidência detalhada para este tipo de nó — os números do grafo vêm das ligações acima.
              </p>
            )}
          </section>
        </div>

        <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/5 pt-3">
          <Button variant="secondary" onClick={() => onIsolar(node)}>
            <Focus size={14} /> Isolar vizinhança
          </Button>
          <Button variant="secondary" onClick={() => onVerTipo(node)}>
            <Eye size={14} /> Ver só {DIMENSAO_LABEL[dimensao]?.label || dimensao}
          </Button>
          <Button variant="secondary" onClick={() => onEsconderTipo(node)}>
            <EyeOff size={14} /> Esconder tipo
          </Button>
          <Button variant="secondary" onClick={() => onAbrirNoModulo(node)}>
            <ExternalLink size={14} /> Abrir no módulo
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              void navigator.clipboard?.writeText(String(node.key ?? node.id));
            }}
          >
            <Copy size={14} /> Copiar identificador
          </Button>
          <Badge>{dimensao}</Badge>
        </footer>
      </div>
    </div>
  );
}
