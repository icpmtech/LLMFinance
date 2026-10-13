/**
 * **Fichas públicas de município** — a secção do CMS que publica, em
 * `/site/municipio/{slug}`, a despesa e a contratação de uma câmara municipal.
 *
 * O editor escolhe o município, os números oficiais (INE + Portal BASE) entram
 * já lidos e guardados na ficha, o texto é escrito por uma pessoa — ou começado
 * a partir de um rascunho que a IA redige com esses números à frente.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Eye, ExternalLink, Loader2, Pencil, Plus, RefreshCw, Save, Search, Sparkles, Trash2, Wand2 } from "lucide-react";

import { Button } from "../components/ui/Button";
import { BlockEditor, IconAction, ListRow, Notice, PanelHeader, SelectInput, Sheet, StatusBadge, TextArea, TextInput, timeAgo } from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsBlock, CmsMunicipio, CmsMunicipioOpcao, CmsSeo, CmsStatus } from "../cmsApi";
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

function textoDoCorpo(blocos: CmsBlock[] | undefined): string {
  const blocosTexto = (blocos ?? []).filter((bloco) => bloco.type === "texto");
  const markdown = blocosTexto.map((bloco) => String((bloco.data as { markdown?: string }).markdown ?? "")).join("\n\n");
  return markdown;
}

/** Blocos de texto substituídos pelo corpo que vem do editor (ou da IA). */
function blocosCom(markdown: string, blocos: CmsBlock[] | undefined): CmsBlock[] {
  const restantes = (blocos ?? []).filter((bloco) => bloco.type !== "texto");
  return markdown.trim() ? [...restantes, { id: `blk_${Date.now()}`, type: "texto", data: { markdown } }] : restantes;
}

export function CmsMunicipiosPanel({
  ctx,
  focusId,
  onFocusHandled,
}: {
  ctx: CmsCtx;
  focusId?: string | null;
  onFocusHandled?: () => void;
}) {
  const [fichas, setFichas] = useState<CmsMunicipio[]>([]);
  const [opcoes, setOpcoes] = useState<CmsMunicipioOpcao[]>([]);
  const [anoDespesas, setAnoDespesas] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Partial<CmsMunicipio> | null>(null);
  const [corpo, setCorpo] = useState("");
  const [instrucoes, setInstrucoes] = useState("");
  const [ai, setAi] = useState<cms.CmsMunicipioTexto | null>(null);
  const [busy, setBusy] = useState(false);
  const [gerando, setGerando] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [lista, escolhas] = await Promise.all([cms.listCmsMunicipios({ limit: 500 }), cms.getCmsMunicipioOpcoes()]);
      setFichas(lista.items);
      setOpcoes(escolhas.items);
      setAnoDespesas(escolhas.ano_despesas ?? null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Vindo do painel (ou da pesquisa) com uma ficha concreta: abre-a já.
  useEffect(() => {
    if (!focusId) return;
    void abrir(focusId);
    onFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  const filtradas = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return fichas;
    return fichas.filter((ficha) =>
      `${ficha.municipio} ${ficha.title} ${ficha.dados?.distrito ?? ""}`.toLowerCase().includes(needle),
    );
  }, [fichas, query]);

  const semFicha = useMemo(() => opcoes.filter((opcao) => !opcao.ficha_id), [opcoes]);

  const abrir = async (id: string) => {
    setBusy(true);
    setAi(null);
    try {
      const payload = await cms.getCmsMunicipio(id);
      setDraft(payload.item);
      setCorpo(textoDoCorpo(payload.item.blocks));
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const criar = async (municipio: string) => {
    if (!municipio) return;
    setBusy(true);
    try {
      const resultado = await cms.createCmsMunicipio({ municipio });
      ctx.notify(`Ficha de ${resultado.item.municipio} criada com os dados oficiais.`, "ok");
      await load();
      await abrir(resultado.item.id);
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const guardar = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.updateCmsMunicipio(draft.id, {
        title: draft.title ?? "",
        slug: draft.slug ?? "",
        excerpt: draft.excerpt ?? "",
        seo: draft.seo ?? {},
        blocks: blocosCom(corpo, draft.blocks),
      });
      setDraft(resultado.item);
      setCorpo(textoDoCorpo(resultado.item.blocks));
      ctx.notify("Ficha guardada.", "ok");
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const atualizarDados = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.refreshCmsMunicipioDados(draft.id);
      setDraft(resultado.item);
      ctx.notify("Dados oficiais atualizados.", "ok");
      await load();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const gerarTexto = async (aplicar: boolean) => {
    if (!draft?.id) return;
    setGerando(true);
    try {
      const resultado = await cms.gerarCmsMunicipioTexto(draft.id, { instrucoes });
      setAi(resultado);
      if (aplicar) {
        setCorpo(resultado.corpo);
        setDraft({
          ...draft,
          title: draft.title || resultado.titulo,
          excerpt: draft.excerpt || resultado.resumo,
          seo: { ...(draft.seo ?? {}), description: resultado.resumo } as CmsSeo,
        });
        ctx.notify("Rascunho da IA aplicado. Reveja e guarde.", "ok");
      } else {
        ctx.notify("Rascunho da IA gerado.", "ok");
      }
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setGerando(false);
    }
  };

  const publicar = async (at: string | null) => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const resultado = await cms.publishCmsItem("municipios", draft.id, at);
      setDraft(resultado.item as unknown as CmsMunicipio);
      ctx.notify(at ? "Publicação agendada." : "Ficha publicada no site.", "ok");
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
      const resultado = await cms.unpublishCmsItem("municipios", draft.id);
      setDraft(resultado.item as unknown as CmsMunicipio);
      ctx.notify("Ficha devolvida a rascunho.", "ok");
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
      const resultado = await cms.setCmsStatus("municipios", draft.id, status);
      setDraft(resultado.item as unknown as CmsMunicipio);
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
      await cms.deleteCmsEntity("municipios", draft.id);
      ctx.notify("Ficha apagada.", "ok");
      setDraft(null);
      await load();
      ctx.refreshOverview();
    } catch (err) {
      ctx.notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const dados = draft?.dados ?? null;
  const contratos = dados?.contratos;
  const anosContrato = useMemo(() => Object.keys(contratos?.por_ano ?? {}).sort().reverse(), [contratos]);

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Municípios"
        hint="Uma ficha pública por município, com a despesa do INE e a contratação do Portal BASE, publicada em /site/municipio/{endereço}."
      >
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
        <Button
          size="sm"
          variant="primary"
          icon={<Plus size={13} />}
          disabled={semFicha.length === 0}
          onClick={() => void criar(semFicha[0]?.municipio ?? "")}
        >
          Nova ficha
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40"
            placeholder="Procurar por município, título ou distrito…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <SelectInput
          label=""
          value=""
          onChange={(next) => void criar(next)}
          options={semFicha.map((opcao) => ({ value: opcao.municipio, label: opcao.municipio }))}
          placeholder={`— publicar um município (${semFicha.length} por publicar) —`}
        />
        {anoDespesas && <span className="pill rounded-full bg-white/[0.06] px-2 py-1 text-[11px] text-muted-foreground">Despesa do INE · {anoDespesas}</span>}
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      <Notice>
        A despesa vem do indicador 0013909 do INE (origem DGAL) e a contratação do Portal BASE. Os valores ficam
        guardados na ficha quando a cria ou carrega em «Atualizar dados» — a página publicada não muda sozinha.
      </Notice>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as fichas…
        </p>
      ) : filtradas.length === 0 ? (
        <Notice>
          Ainda não há fichas de município. Escolha um dos {opcoes.length} municípios acima para criar a primeira.
        </Notice>
      ) : (
        <div className="space-y-1.5">
          {filtradas.map((ficha) => (
            <ListRow
              key={ficha.id}
              title={ficha.title || ficha.municipio}
              subtitle={`/site/municipio/${ficha.slug} · ${ficha.dados?.distrito ?? "—"} · atualizada ${timeAgo(ficha.updated_at)}`}
              meta={
                <>
                  <StatusBadge status={ficha.status} labels={Object.fromEntries(ctx.catalogue.statuses.map((item) => [item.id, item.label]))} />
                  <span>{ficha.dados?.ano_despesas ? `despesa ${milhões(ficha.dados.despesas_total)} (${ficha.dados.ano_despesas})` : "sem dados"}</span>
                  {ficha.dados?.contratos?.total ? <span>· {ficha.dados.contratos.total.toLocaleString("pt-PT")} contratos</span> : null}
                </>
              }
              onClick={() => void abrir(ficha.id)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => void abrir(ficha.id)}>
                    <Pencil size={13} />
                  </IconAction>
                  {ficha.status === "publicado" && (
                    <IconAction title="Abrir no site" onClick={() => openExternal(cms.cmsMunicipioUrl(ficha.slug))}>
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
          title={draft.id ? `Município · ${draft.municipio}` : "Nova ficha de município"}
          subtitle={draft.slug ? `/site/municipio/${draft.slug}` : undefined}
          onClose={() => setDraft(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => void apagar()} disabled={!draft.id}>
                Apagar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Fechar
              </Button>
              <Button size="sm" variant="primary" icon={<Save size={13} />} loading={busy} onClick={() => void guardar()}>
                Guardar
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <TextInput label="Título da página" value={draft.title ?? ""} onChange={(next) => setDraft({ ...draft, title: next })} wide />
              <TextInput label="Endereço (slug)" value={draft.slug ?? ""} onChange={(next) => setDraft({ ...draft, slug: next })} hint="O endereço público: /site/municipio/{slug}." />
              <TextInput label="Município" value={draft.municipio ?? ""} onChange={() => undefined} hint="Ligado à ficha das despesas; não se altera depois de criada." />
              <TextArea label="Resumo (listagens e meta descrição)" value={draft.excerpt ?? ""} onChange={(next) => setDraft({ ...draft, excerpt: next })} rows={2} wide />
            </div>

            {draft.id && (
              <PublishBar
                status={(draft.status ?? "rascunho") as CmsStatus}
                scheduledAt={draft.scheduled_at}
                onStatus={(next) => void mudarEstado(next)}
                onSchedule={(at) => void publicar(at)}
                onPublish={() => void publicar(null)}
                onUnpublish={() => void despublicar()}
                onOpenSite={() => openExternal(cms.cmsMunicipioUrl(draft.slug ?? ""))}
                onPreview={() => openExternal(cms.cmsPreviewUrl("municipios", draft.id as string))}
                busy={busy}
                hasPublicUrl={draft.status === "publicado"}
              />
            )}

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Dados oficiais" hint="Lidos do INE e do Portal BASE e guardados na ficha.">
                <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={busy} disabled={!draft.id} onClick={() => void atualizarDados()}>
                  Atualizar dados
                </Button>
              </PanelHeader>
              {dados ? (
                <div className="space-y-2">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <TextInput label={`Despesa total (${dados.ano_despesas ?? "—"})`} value={milhões(dados.despesas_total)} onChange={() => undefined} />
                    <TextInput label="Despesas correntes" value={milhões(dados.despesas_correntes)} onChange={() => undefined} />
                    <TextInput label="Despesas de capital" value={milhões(dados.despesas_capital)} onChange={() => undefined} />
                    <TextInput label="Despesa com pessoal" value={milhões(dados.despesas_pessoal)} onChange={() => undefined} />
                    <TextInput label="Bens e serviços" value={milhões(dados.despesas_bens_servicos)} onChange={() => undefined} />
                    <TextInput
                      label="Contratação (Portal BASE)"
                      value={contratos?.total ? `${contratos.total.toLocaleString("pt-PT")} contratos · ${milhões(contratos.valor)}` : "sem contratos"}
                      onChange={() => undefined}
                    />
                  </div>
                  {anosContrato.length > 0 && (
                    <div className="rounded-lg border border-white/8 bg-white/[0.02] p-2">
                      <p className="mb-1 text-[11px] font-medium text-muted-foreground">
                        Contratação por ano (Portal BASE) — {anosContrato[anosContrato.length - 1]} a {anosContrato[0]}
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {anosContrato.slice(0, 12).map((ano) => (
                          <span key={ano} className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10.5px] text-muted-foreground tabular-nums">
                            {ano}: {milhões(contratos?.por_ano?.[ano]?.valor)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {dados.recolhido_em && <p className="text-[11px] text-muted-foreground">Recolhido a {timeAgo(dados.recolhido_em)}.</p>}
                </div>
              ) : (
                <p className="text-[12px] text-muted-foreground">Sem dados guardados. Crie a ficha pelo município para os ler automaticamente.</p>
              )}
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Texto da ficha" hint="Markdown. A IA escreve um rascunho a partir dos números; quem publica é sempre uma pessoa.">
                <Button size="sm" variant="secondary" icon={<Sparkles size={13} />} loading={gerando} disabled={!draft.id} onClick={() => void gerarTexto(true)}>
                  Gerar e aplicar
                </Button>
                <Button size="sm" variant="ghost" icon={<Wand2 size={13} />} loading={gerando} disabled={!draft.id} onClick={() => void gerarTexto(false)}>
                  Só gerar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Eye size={13} />}
                  disabled={!draft.id}
                  onClick={() => openExternal(cms.cmsMunicipioPreviewUrl(draft.id as string))}
                >
                  Pré-visualizar
                </Button>
              </PanelHeader>
              <div className="space-y-2">
                <TextInput
                  label="Instruções para a IA (opcional)"
                  value={instrucoes}
                  onChange={setInstrucoes}
                  placeholder="Ex.: destaca a despesa com pessoal e a evolução da contratação de obras."
                  wide
                />
                <TextArea label="Corpo (Markdown)" value={corpo} onChange={setCorpo} rows={14} wide />
                {ai?.resumo_dos_dados && (
                  <details className="rounded-lg border border-white/8 bg-white/[0.02] p-2 text-[11.5px] text-muted-foreground">
                    <summary className="cursor-pointer">Números que a IA recebeu</summary>
                    <pre className="mt-1 whitespace-pre-wrap font-sans">{ai.resumo_dos_dados}</pre>
                  </details>
                )}
                {ai?.ai?.provider && (
                  <p className="text-[11px] text-muted-foreground">
                    Rascunho de {ai.ai.provider_label ?? ai.ai.provider} ({ai.ai.model ?? "modelo predefinido"}). Reveja antes de publicar.
                  </p>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Blocos" hint="Conteúdo por blocos, desenhado na ficha depois dos destaques e dos números." />
              <BlockEditor
                blocks={(draft.blocks ?? []) as never}
                onChange={(next) => setDraft({ ...draft, blocks: next as CmsBlock[] })}
                blockTypes={ctx.catalogue.block_types}
                media={ctx.catalogue.media_index}
                contents={ctx.catalogue.contents_index}
                categories={ctx.catalogue.categories_index}
              />
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <PanelHeader title="Motores de busca" hint="Título, descrição e imagem usados nos resultados e nas partilhas." />
              <SeoFields seo={draft.seo ?? {}} onChange={(next) => setDraft({ ...draft, seo: next })} media={ctx.catalogue.media_index} />
            </div>

            <HistoryPanel entity="municipios" itemId={draft.id} notify={ctx.notify} onRestored={() => void abrir(draft.id as string)} />
          </div>
        </Sheet>
      )}
    </div>
  );
}
