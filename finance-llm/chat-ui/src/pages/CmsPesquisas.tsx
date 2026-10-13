/**
 * **Páginas de pesquisa** — a secção do CMS que publica, em `/site/pesquisa/{slug}`,
 * uma pesquisa congelada sobre os municípios: os filtros (texto, distrito, ano da
 * contratação, ordenação, limite) ficam guardados na página e os números são a
 * fotografia lida quando o editor manda ler — o Portal BASE muda, a página só
 * muda quando alguém a volta a ler.
 *
 * Cada página tem SEO próprio e marca própria: imagem de capa, logótipo e cor de
 * destaque (biblioteca de media do CMS).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Eye, Loader2, Pencil, Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react";

import { Button } from "../components/ui/Button";
import { IconAction, ListRow, MediaPicker, Notice, PanelHeader, SelectInput, Sheet, StatusBadge, TextArea, TextInput, timeAgo } from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsPesquisa, CmsPesquisaFiltros, CmsPesquisaOpcoes, CmsSeo, CmsStatus } from "../cmsApi";
import { HistoryPanel, PublishBar, SeoFields, type CmsCtx } from "./CmsPanels";

function openExternal(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Euros compactos para os destaques do editor («317,6 M €»). */
function milhões(valor?: number | null): string {
  if (!valor) return "—";
  if (Math.abs(valor) >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} mil M €`;
  if (Math.abs(valor) >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M €`;
  if (Math.abs(valor) >= 1_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} mil €`;
  return `${valor.toLocaleString("pt-PT", { maximumFractionDigits: 0 })} €`;
}

const FILTROS_VAZIOS: CmsPesquisaFiltros = {
  q: "",
  distrito: "",
  ano_contratos: null,
  ordenar: "despesas",
  ordem: "desc",
  min_despesas: null,
  limite: 25,
};

export function CmsPesquisasPanel({
  ctx,
  focusId,
  onFocusHandled,
}: {
  ctx: CmsCtx;
  focusId?: string | null;
  onFocusHandled?: () => void;
}) {
  const [paginas, setPaginas] = useState<CmsPesquisa[]>([]);
  const [opcoes, setOpcoes] = useState<CmsPesquisaOpcoes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Partial<CmsPesquisa> | null>(null);
  const [busy, setBusy] = useState(false);
  const [aReler, setAReler] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [lista, escolhas] = await Promise.all([
        cms.listCmsPesquisas({ limit: 300 }),
        cms.getCmsPesquisaOpcoes(),
      ]);
      setPaginas(lista.items);
      setOpcoes(escolhas);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!focusId) return;
    void abrir(focusId);
    onFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  const filtradas = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return paginas;
    return paginas.filter((pagina) =>
      `${pagina.title} ${pagina.slug} ${pagina.descricao_filtros ?? ""}`.toLowerCase().includes(needle),
    );
  }, [paginas, query]);

  const abrir = async (id: string) => {
    setBusy(true);
    try {
      const payload = await cms.getCmsPesquisa(id);
      setDraft(payload.item);
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const criar = async () => {
    setBusy(true);
    try {
      const resultado = await cms.createCmsPesquisa({ filtros: FILTROS_VAZIOS });
      setDraft(resultado.item);
      ctx.notify("Página de pesquisa criada com os filtros lidos.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const filtrosDoDraft = (): CmsPesquisaFiltros => ({ ...FILTROS_VAZIOS, ...(draft?.filtros ?? {}) });

  const definirFiltro = (chave: keyof CmsPesquisaFiltros, valor: string | number | null) =>
    setDraft({ ...(draft ?? {}), filtros: { ...filtrosDoDraft(), [chave]: valor } });

  const guardar = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.updateCmsPesquisa(draft.id, {
        title: draft.title ?? "",
        slug: draft.slug ?? "",
        excerpt: draft.excerpt ?? "",
        intro: draft.intro ?? "",
        filtros: filtrosDoDraft(),
        capa_id: draft.capa_id ?? null,
        logo_id: draft.logo_id ?? null,
        cor: draft.cor ?? "",
        seo: draft.seo as CmsSeo,
      });
      setDraft(resultado.item);
      ctx.notify("Página de pesquisa guardada.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  /** Corre a pesquisa outra vez (com os filtros do editor) e guarda a fotografia. */
  const relerDados = async (guardarFiltros = true) => {
    if (!draft?.id) return;
    setAReler(true);
    try {
      const resultado = await cms.refreshCmsPesquisaDados(draft.id, {
        filtros: filtrosDoDraft(),
        guardar_filtros: guardarFiltros,
      });
      setDraft(resultado.item);
      ctx.notify(resultado.resumo_dos_dados, "ok");
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setAReler(false);
    }
  };

  const publicar = async (at: string | null) => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.publishCmsItem("pesquisas", draft.id, at);
      setDraft(resultado.item as unknown as CmsPesquisa);
      ctx.notify(at ? "Publicação agendada." : "Página publicada no site.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const despublicar = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.unpublishCmsItem("pesquisas", draft.id);
      setDraft(resultado.item as unknown as CmsPesquisa);
      ctx.notify("Página devolvida a rascunho.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const mudarEstado = async (status: CmsStatus) => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.setCmsStatus("pesquisas", draft.id, status);
      setDraft(resultado.item as unknown as CmsPesquisa);
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const apagar = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      await cms.deleteCmsEntity("pesquisas", draft.id);
      ctx.notify("Página apagada.", "ok");
      setDraft(null);
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const filtros = filtrosDoDraft();
  const dados = draft?.dados ?? null;
  const media = ctx.catalogue.media_index;

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Pesquisas"
        hint="Uma página pública com os filtros congelados sobre as despesas municipais (distrito, ano da contratação, ordenação), publicada em /site/pesquisa/{endereço}."
      >
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
        <Button size="sm" variant="primary" icon={<Plus size={13} />} loading={busy} onClick={() => void criar()}>
          Nova pesquisa
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40"
            placeholder="Procurar por título, endereço ou filtros…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {opcoes?.ano_despesas && (
          <span className="pill rounded-full bg-white/[0.06] px-2 py-1 text-[11px] text-muted-foreground">
            Despesa do INE · {opcoes.ano_despesas}
          </span>
        )}
        {opcoes?.anos_contratos?.length ? (
          <span className="pill rounded-full bg-white/[0.06] px-2 py-1 text-[11px] text-muted-foreground">
            Contratação · {opcoes.anos_contratos[opcoes.anos_contratos.length - 1]}→{opcoes.anos_contratos[0]}
          </span>
        ) : null}
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      <Notice>
        Os números da pesquisa são lidos do índice do Portal BASE (contratação, por ano) e do INE (despesa). Ficam
        guardados na página quando a cria ou carrega em «Reler dados» — a página publicada não muda sozinha.
      </Notice>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as páginas de pesquisa…
        </p>
      ) : filtradas.length === 0 ? (
        <Notice>
          Ainda não há páginas de pesquisa. Crie a primeira (por exemplo: o distrito do Porto em 2024) e escolha os
          filtros no editor.
        </Notice>
      ) : (
        <div className="space-y-1.5">
          {filtradas.map((pagina) => (
            <ListRow
              key={pagina.id}
              title={pagina.title}
              subtitle={`/site/pesquisa/${pagina.slug} · ${pagina.descricao_filtros || "sem filtros"} · atualizada ${timeAgo(pagina.updated_at)}`}
              meta={
                <>
                  <StatusBadge
                    status={pagina.status}
                    labels={Object.fromEntries(ctx.catalogue.statuses.map((item) => [item.id, item.label]))}
                  />
                  <span>{pagina.dados?.total ? `${pagina.dados.total} municípios` : "sem dados lidos"}</span>
                  {pagina.dados?.contratos_ano_somados ? (
                    <span>· {milhões(pagina.dados.contratos_ano_somados)} em {pagina.dados.ano_contratos}</span>
                  ) : null}
                </>
              }
              onClick={() => void abrir(pagina.id)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => void abrir(pagina.id)}>
                    <Pencil size={13} />
                  </IconAction>
                  {pagina.status === "publicado" && (
                    <IconAction title="Abrir no site" onClick={() => openExternal(cms.cmsPesquisaUrl(pagina.slug))}>
                      <ExternalLink size={13} />
                    </IconAction>
                  )}
                </>
              }
            />
          ))}
        </div>
      )}

      {draft && (
        <Sheet
          wide
          busy={busy}
          title={draft.id ? `Pesquisa · ${draft.title || draft.slug}` : "Nova pesquisa"}
          subtitle={draft.slug ? `/site/pesquisa/${draft.slug}` : undefined}
          onClose={() => setDraft(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => void apagar()} disabled={!draft.id}>
                Apagar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Fechar
              </Button>
              <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={aReler} onClick={() => void relerDados(true)} disabled={!draft.id}>
                Reler dados
              </Button>
              <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void guardar()} disabled={!draft.id}>
                Guardar
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Título da página" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <TextInput
                label="Endereço (slug)"
                value={draft.slug ?? ""}
                onChange={(next) => setDraft({ ...draft, slug: next })}
                hint="O endereço público: /site/pesquisa/{slug}."
              />
              <TextArea
                label="Resumo (listagens e meta descrição)"
                value={draft.excerpt ?? ""}
                onChange={(next) => setDraft({ ...draft, excerpt: next })}
                rows={2}
                wide
              />
            </div>

            {draft.id && (
              <PublishBar
                status={(draft.status ?? "rascunho") as CmsStatus}
                scheduledAt={draft.scheduled_at}
                onStatus={(next) => void mudarEstado(next)}
                onSchedule={(at) => void publicar(at)}
                onPublish={() => void publicar(null)}
                onUnpublish={() => void despublicar()}
                onOpenSite={() => openExternal(cms.cmsPesquisaUrl(draft.slug ?? ""))}
                onPreview={() => openExternal(cms.cmsPreviewUrl("pesquisas", draft.id as string))}
                busy={busy}
                hasPublicUrl={draft.status === "publicado"}
              />
            )}

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Filtros da pesquisa</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                É isto que fica congelado na página: quem a abrir vê exactamente o que estes filtros dão hoje.
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <TextInput
                  label="Procurar município"
                  value={String(filtros.q ?? "")}
                  onChange={(next) => definirFiltro("q", next)}
                  placeholder="ex.: lisboa"
                />
                <SelectInput
                  label="Distrito"
                  value={String(filtros.distrito ?? "")}
                  onChange={(next) => definirFiltro("distrito", next)}
                  options={(opcoes?.distritos ?? []).map((distrito) => ({ value: distrito, label: distrito }))}
                  placeholder="— todos —"
                />
                <SelectInput
                  label="Contratação (ano)"
                  value={filtros.ano_contratos ? String(filtros.ano_contratos) : ""}
                  onChange={(next) => definirFiltro("ano_contratos", next ? Number(next) : null)}
                  options={(opcoes?.anos_contratos ?? []).map((ano) => ({ value: ano, label: ano }))}
                  placeholder="— todos os anos —"
                />
                <SelectInput
                  label="Ordenar por"
                  value={String(filtros.ordenar ?? "despesas")}
                  onChange={(next) => definirFiltro("ordenar", next)}
                  options={(opcoes?.ordenacoes ?? []).map((item) => ({ value: item.id, label: item.label }))}
                />
                <SelectInput
                  label="Sentido"
                  value={String(filtros.ordem ?? "desc")}
                  onChange={(next) => definirFiltro("ordem", next)}
                  options={[
                    { value: "desc", label: "Decrescente" },
                    { value: "asc", label: "Crescente" },
                  ]}
                />
                <TextInput
                  label="Municípios a listar"
                  value={String(filtros.limite ?? 25)}
                  onChange={(next) => definirFiltro("limite", Number(next) || 25)}
                  hint={`Até ${opcoes?.limite_maximo ?? 200}.`}
                />
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={aReler} onClick={() => void relerDados(true)}>
                  Reler dados
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  {dados?.gerado_em ? `lidos a ${new Date(dados.gerado_em).toLocaleString("pt-PT")}` : "ainda sem dados lidos"}
                </span>
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Marca e imagens desta página</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Capa, logótipo e cor de destaque da página (não muda o resto do site).
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <MediaPicker
                  label="Imagem de capa"
                  value={String(draft.capa_id ?? "")}
                  onChange={(next) => setDraft({ ...draft, capa_id: next || null })}
                  media={media}
                />
                <MediaPicker
                  label="Logótipo"
                  value={String(draft.logo_id ?? "")}
                  onChange={(next) => setDraft({ ...draft, logo_id: next || null })}
                  media={media}
                />
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <TextInput
                      label="Cor de destaque"
                      value={draft.cor ?? ""}
                      onChange={(next) => setDraft({ ...draft, cor: next })}
                      placeholder="#0ea5a4"
                      hint="Vazio = cor do site."
                    />
                  </div>
                  <input
                    type="color"
                    aria-label="Escolher a cor de destaque"
                    value={/^#[0-9a-fA-F]{6}$/.test(draft.cor ?? "") ? String(draft.cor) : "#0ea5a4"}
                    onChange={(event) => setDraft({ ...draft, cor: event.target.value })}
                    className="h-9 w-12 cursor-pointer rounded-lg border border-white/10 bg-transparent"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Texto de entrada</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Markdown que aparece por cima dos números — pode explicar o que a pesquisa mostra e porquê.
              </p>
              <div className="mt-2">
                <TextArea
                  label="Texto (Markdown)"
                  value={draft.intro ?? ""}
                  onChange={(next) => setDraft({ ...draft, intro: next })}
                  rows={5}
                  mono
                />
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">SEO</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Título, descrição, palavras-chave e imagem de partilha (Open Graph e JSON-LD).
              </p>
              <div className="mt-2">
                <SeoFields
                  seo={(draft.seo ?? {}) as CmsSeo}
                  onChange={(next) => setDraft({ ...draft, seo: next })}
                  media={media}
                />
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[12px] font-semibold">
                  Pré-visualização dos números{dados?.total ? ` · ${dados.total} municípios` : ""}
                </p>
                <Button size="sm" variant="ghost" icon={<Eye size={13} />} onClick={() => openExternal(cms.cmsPreviewUrl("pesquisas", draft.id as string))} disabled={!draft.id}>
                  Abrir pré-visualização
                </Button>
              </div>
              {dados?.error ? <Notice tone="error">{dados.error}</Notice> : null}
              {dados?.itens?.length ? (
                <div className="mt-2 max-h-72 overflow-auto">
                  <table className="w-full min-w-[420px] text-[11px]">
                    <thead className="sticky top-0 bg-background/95">
                      <tr className="text-left text-muted-foreground">
                        <th className="py-1 pr-2 font-medium">Município</th>
                        <th className="py-1 pr-2 font-medium">Distrito</th>
                        <th className="py-1 pr-2 text-right font-medium">Despesa</th>
                        <th className="py-1 pr-2 text-right font-medium">
                          {dados.ano_contratos ? `Contratos ${dados.ano_contratos}` : "Contratos"}
                        </th>
                        <th className="py-1 text-right font-medium">
                          {dados.ano_contratos ? `Contratado ${dados.ano_contratos}` : "Contratado"}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.itens.map((linha) => (
                        <tr key={`${linha.geocod ?? linha.nome}`} className="border-t border-white/5">
                          <td className="py-1 pr-2">{linha.nome}</td>
                          <td className="py-1 pr-2 text-muted-foreground">{linha.distrito ?? "—"}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">{milhões(linha.despesas_total)}</td>
                          <td className="py-1 pr-2 text-right tabular-nums">
                            {dados.ano_contratos ? linha.contratos_ano_total?.toLocaleString("pt-PT") : linha.contratos_total?.toLocaleString("pt-PT")}
                          </td>
                          <td className="py-1 text-right tabular-nums">
                            {milhões(dados.ano_contratos ? linha.contratos_ano_valor : linha.contratos_valor)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Carregue em «Reler dados» para ler os números da pesquisa.
                </p>
              )}
            </div>

            {draft.id && (
              <HistoryPanel
                entity="pesquisas"
                itemId={draft.id}
                onRestored={() => void abrir(draft.id as string)}
                notify={ctx.notify}
              />
            )}
          </div>
        </Sheet>
      )}
    </div>
  );
}
