/**
 * **Remunerações da Administração Pública** — a secção do CMS que publica, em
 * `/site/remuneracoes/{endereço}`, o quadro consolidado da DGAEP de um ano: a
 * Tabela Remuneratória Única, as carreiras com as suas posições remuneratórias,
 * os cargos dirigentes, as notas e a base legal.
 *
 * O ano fica guardado na página e os números são a **fotografia** lida quando o
 * editor a mandou ler (`Reler modelo`): a DGAEP atualiza os PDF, a página
 * publicada só muda quando alguém a volta a ler. A marca (cor, logótipo e
 * imagem de capa) e o SEO são do documento.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ExternalLink, Eye, Loader2, Newspaper, Pencil, Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react";

import { Button } from "../components/ui/Button";
import { BlockEditor, IconAction, ListRow, MediaPicker, Notice, PanelHeader, SelectInput, Sheet, StatusBadge, TextArea, TextInput, timeAgo } from "../components/cms/CmsKit";
import * as cms from "../cmsApi";
import type { CmsRemuneracao, CmsRemuneracaoOpcoes, CmsRemuneracaoSeccao, CmsStatus } from "../cmsApi";
import { HistoryPanel, PublishBar, SeoFields, type CmsCtx } from "./CmsPanels";

function openExternal(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Euros com cêntimos, para os valores do quadro («878,41 €»). */
function euros(valor?: number | null): string {
  if (valor == null) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

export function CmsRemuneracoesPanel({
  ctx,
  focusId,
  onFocusHandled,
}: {
  ctx: CmsCtx;
  focusId?: string | null;
  onFocusHandled?: () => void;
}) {
  const [paginas, setPaginas] = useState<CmsRemuneracao[]>([]);
  const [opcoes, setOpcoes] = useState<CmsRemuneracaoOpcoes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Partial<CmsRemuneracao> | null>(null);
  const [busy, setBusy] = useState(false);
  const [aReler, setAReler] = useState(false);
  const [aBlog, setABlog] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [lista, escolhas] = await Promise.all([cms.listCmsRemuneracoes(), cms.getCmsRemuneracaoOpcoes()]);
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

  const filtradas = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return paginas;
    return paginas.filter((pagina) => `${pagina.title} ${pagina.slug} ${pagina.ano ?? ""}`.toLowerCase().includes(needle));
  }, [paginas, query]);

  const abrir = useCallback(async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const { item } = await cms.getCmsRemuneracao(id);
      setDraft(item);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!focusId) return;
    void abrir(focusId);
    onFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  const criar = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const ano = opcoes?.ano ?? opcoes?.anos?.[0];
      if (!ano) {
        setError("Ainda não há nenhum ano recolhido da DGAEP. Corra a recolha em Remunerações da Administração Pública.");
        return;
      }
      const { item } = await cms.createCmsRemuneracao({ ano });
      ctx.notify(`Página de ${ano} criada com o modelo já lido.`, "ok");
      await load();
      setDraft(item);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [opcoes, ctx, load]);

  const guardar = useCallback(async () => {
    if (!draft?.id) return;
    setBusy(true);
    setError(null);
    try {
      const { item } = await cms.updateCmsRemuneracao(draft.id, draft);
      setDraft(item);
      await load();
      ctx.notify("Página guardada.", "ok");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draft, ctx, load]);

  const relerModelo = useCallback(
    async (guardarAno = true) => {
      if (!draft?.id) return;
      setAReler(true);
      setError(null);
      try {
        const resultado = await cms.refreshCmsRemuneracaoModelo(draft.id, {
          ano: draft.ano ?? undefined,
          guardar_ano: guardarAno,
        });
        setDraft(resultado.item);
        await load();
        ctx.notify(resultado.resumo_dos_dados, "ok");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setAReler(false);
      }
    },
    [draft, ctx, load],
  );

  const publicar = useCallback(
    async (at: string | null) => {
      if (!draft?.id) return;
      setBusy(true);
      try {
        const { item } = await cms.publishCmsItem("remuneracoes", draft.id, at);
        setDraft({ ...draft, ...(item as CmsRemuneracao) });
        await load();
        ctx.notify(at ? "Publicação agendada." : "Página publicada.", "ok");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [draft, ctx, load],
  );

  const despublicar = useCallback(async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      const { item } = await cms.unpublishCmsItem("remuneracoes", draft.id);
      setDraft({ ...draft, ...(item as CmsRemuneracao) });
      await load();
      ctx.notify("Página despublicada.", "info");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draft, ctx, load]);

  const mudarEstado = useCallback(
    async (status: CmsStatus) => {
      if (!draft?.id) return;
      setBusy(true);
      try {
        const { item } = await cms.setCmsStatus("remuneracoes", draft.id, status);
        setDraft({ ...draft, ...(item as CmsRemuneracao) });
        await load();
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [draft, load],
  );

  const apagar = useCallback(async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      await cms.deleteCmsEntity("remuneracoes", draft.id);
      setDraft(null);
      await load();
      ctx.notify("Página apagada.", "info");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draft, ctx, load]);

  const dados = draft?.dados ?? null;
  const carreiras = dados?.carreiras ?? [];
  const media = ctx.catalogue.media_index;

  /** As secções pela ordem guardada; as que faltarem entram no fim. */
  const ordemSeccoes = useMemo(() => {
    const conhecidas = (opcoes?.mostrar ?? []).map((item) => item.id);
    const guardada = (draft?.ordem ?? []).filter((chave) => conhecidas.includes(chave));
    return [...new Set(guardada), ...conhecidas.filter((chave) => !guardada.includes(chave))];
  }, [draft?.ordem, opcoes]);

  const infoDaSeccao = useCallback(
    (chave: string) => (opcoes?.mostrar ?? []).find((item) => item.id === chave),
    [opcoes],
  );

  const valorDaSeccao = useCallback(
    (chave: string): CmsRemuneracaoSeccao => draft?.seccoes?.[chave] ?? { titulo: "", sub: "" },
    [draft],
  );

  const ligarSeccao = useCallback((chave: string, ligada: boolean) => {
    setDraft((atual) => (atual ? { ...atual, mostrar: { ...(atual.mostrar ?? {}), [chave]: ligada } } : atual));
  }, []);

  /** Guarda o título ou o subtítulo de uma secção (o vazio volta ao do modelo). */
  const definirSeccao = useCallback(
    (chave: string, campo: "titulo" | "sub", valor: string) => {
      setDraft((atual) => {
        if (!atual) return atual;
        const seccoes = atual.seccoes ?? {};
        const padrao = infoDaSeccao(chave);
        const base = seccoes[chave] ?? { titulo: padrao?.titulo ?? "", sub: padrao?.sub ?? "" };
        return { ...atual, seccoes: { ...seccoes, [chave]: { ...base, [campo]: valor } } };
      });
    },
    [infoDaSeccao],
  );

  const moverSeccao = useCallback(
    (posicao: number, delta: number) => {
      setDraft((atual) => {
        if (!atual) return atual;
        const destino = posicao + delta;
        if (destino < 0 || destino >= ordemSeccoes.length) return atual;
        const lista = [...ordemSeccoes];
        [lista[posicao], lista[destino]] = [lista[destino], lista[posicao]];
        return { ...atual, ordem: lista };
      });
    },
    [ordemSeccoes],
  );

  /** Cria no blog o rascunho que anuncia esta página (o quadro fica na página). */
  const criarArtigo = useCallback(async () => {
    if (!draft?.id) return;
    setABlog(true);
    setError(null);
    try {
      const resultado = await cms.createCmsRemuneracaoArtigo(draft.id, {});
      setDraft(resultado.item);
      await load();
      ctx.notify(resultado.resumo, "ok");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setABlog(false);
    }
  }, [draft, ctx, load]);

  return (
    <div className="space-y-3">
      <PanelHeader
        title="Remunerações da Administração Pública"
        hint="Uma página pública com o quadro da DGAEP de um ano (TRU, carreiras, dirigentes, notas e base legal), publicada em /site/remuneracoes/{endereço}."
      >
        <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} onClick={() => void load()}>
          Atualizar
        </Button>
        <Button size="sm" variant="primary" icon={<Plus size={13} />} loading={busy} onClick={() => void criar()}>
          Nova página
        </Button>
      </PanelHeader>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={13} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <input
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-8 pr-2.5 text-[12.5px] text-foreground outline-none focus:border-teal-300/40"
            placeholder="Procurar por título, endereço ou ano…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {opcoes?.anos?.length ? (
          <span className="pill rounded-full bg-white/[0.06] px-2 py-1 text-[11px] text-muted-foreground">
            Quadros recolhidos · {opcoes.anos[opcoes.anos.length - 1]}→{opcoes.anos[0]}
          </span>
        ) : null}
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      <Notice>
        O modelo é lido dos PDF que a DGAEP publica por ano e fica guardado na página quando a cria ou carrega em
        «Reler modelo» — a página publicada não muda sozinha.
      </Notice>

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-[12.5px] text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as páginas…
        </p>
      ) : filtradas.length === 0 ? (
        <Notice>
          Ainda não há páginas do modelo. Crie a primeira (por exemplo, o quadro de {opcoes?.ano ?? "2026"}) e ajuste o
          texto, a marca e o SEO no editor.
        </Notice>
      ) : (
        <div className="space-y-1.5">
          {filtradas.map((pagina) => (
            <ListRow
              key={pagina.id}
              title={pagina.title}
              subtitle={`/site/remuneracoes/${pagina.slug} · quadro de ${pagina.ano ?? "—"} · atualizada ${timeAgo(pagina.updated_at)}`}
              meta={
                <>
                  <StatusBadge
                    status={pagina.status}
                    labels={Object.fromEntries(ctx.catalogue.statuses.map((item) => [item.id, item.label]))}
                  />
                  {pagina.dados?.contagens ? (
                    <span>
                      {pagina.dados.contagens.niveis} níveis · {pagina.dados.contagens.posicoes} posições ·{" "}
                      {pagina.dados.contagens.dirigentes} dirigentes
                    </span>
                  ) : (
                    <span>sem modelo lido</span>
                  )}
                  {pagina.dados?.parametros?.brap ? <span>· BRAP {euros(pagina.dados.parametros.brap)}</span> : null}
                </>
              }
              onClick={() => void abrir(pagina.id)}
              actions={
                <>
                  <IconAction title="Editar" onClick={() => void abrir(pagina.id)}>
                    <Pencil size={13} />
                  </IconAction>
                  {pagina.status === "publicado" && (
                    <IconAction title="Abrir no site" onClick={() => openExternal(cms.cmsRemuneracaoUrl(pagina.slug))}>
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
          title={draft.id ? `Remunerações · ${draft.title || draft.slug}` : "Nova página"}
          subtitle={draft.slug ? `/site/remuneracoes/${draft.slug}` : undefined}
          onClose={() => setDraft(null)}
          footer={
            <>
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => void apagar()} disabled={!draft.id}>
                Apagar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Fechar
              </Button>
              <Button
                size="sm"
                variant="secondary"
                icon={<RefreshCw size={13} />}
                loading={aReler}
                onClick={() => void relerModelo(true)}
                disabled={!draft.id}
              >
                Reler modelo
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
                hint="O endereço público: /site/remuneracoes/{slug}."
              />
              <SelectInput
                label="Ano do quadro"
                value={draft.ano ? String(draft.ano) : ""}
                onChange={(next) => setDraft({ ...draft, ano: next ? Number(next) : null })}
                options={(opcoes?.anos ?? []).map((ano) => ({ value: String(ano), label: String(ano) }))}
                hint="Depois de mudar, carregue em «Reler modelo» para trazer os números desse ano."
              />
              <TextInput
                label="Texto de entrada (Markdown)"
                value={draft.intro ?? ""}
                onChange={(next) => setDraft({ ...draft, intro: next })}
                placeholder="Explica o que é o quadro e como se lê."
                wide
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
                onOpenSite={() => openExternal(cms.cmsRemuneracaoUrl(draft.slug ?? ""))}
                onPreview={() => openExternal(cms.cmsPreviewUrl("remuneracoes", draft.id as string))}
                busy={busy}
                hasPublicUrl={draft.status === "publicado"}
              />
            )}

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Marca e estilo</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Capa, logótipo, cor de destaque e estilo das secções. Vale só para esta página — não muda o resto do
                site.
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
                      placeholder="#1d4ed8"
                      hint="Aceita `#rrggbb`; vazio usa a cor do site."
                    />
                  </div>
                  <input
                    type="color"
                    aria-label="Escolher a cor de destaque"
                    value={/^#[0-9a-fA-F]{6}$/.test(draft.cor ?? "") ? String(draft.cor) : "#1d4ed8"}
                    onChange={(event) => setDraft({ ...draft, cor: event.target.value })}
                    className="h-9 w-12 cursor-pointer rounded-lg border border-white/10 bg-transparent"
                  />
                </div>
                <SelectInput
                  label="Estilo das secções"
                  value={draft.estilo ?? opcoes?.estilos?.[0]?.id ?? "cartoes"}
                  onChange={(next) => setDraft({ ...draft, estilo: next })}
                  options={(opcoes?.estilos ?? []).map((item) => ({ value: item.id, label: item.label }))}
                  hint="Muda só a superfície: cartões, linhas de separação ou cabeçalhos em faixa."
                />
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Secções da página</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Renomeie, desligue ou troque a ordem dos quadros. Deixe o título vazio para voltar ao do modelo. O texto
                de entrada e os blocos aparecem antes das secções.
              </p>
              <div className="mt-2 space-y-1.5">
                {ordemSeccoes.map((chave, posicao) => {
                  const info = infoDaSeccao(chave);
                  const valor = valorDaSeccao(chave);
                  const ligada = draft.mostrar?.[chave] !== false;
                  return (
                    <div
                      key={chave}
                      className={`rounded-lg border p-2 transition ${
                        ligada ? "border-white/10 bg-white/[0.02]" : "border-white/5 opacity-60"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          aria-pressed={ligada}
                          onClick={() => ligarSeccao(chave, !ligada)}
                          className={`rounded-full border px-2 py-0.5 text-[10.5px] transition ${
                            ligada ? "border-teal-300/40 bg-teal-300/10 text-teal-100" : "border-white/10 text-muted-foreground"
                          }`}
                        >
                          {ligada ? "Ligada" : "Desligada"}
                        </button>
                        <span className="flex-1 truncate text-[11.5px] font-medium">{info?.label ?? chave}</span>
                        <IconAction title="Subir na página" onClick={() => moverSeccao(posicao, -1)}>
                          <ArrowUp size={12} />
                        </IconAction>
                        <IconAction title="Descer na página" onClick={() => moverSeccao(posicao, 1)}>
                          <ArrowDown size={12} />
                        </IconAction>
                      </div>
                      <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
                        <TextInput
                          label="Título da secção"
                          value={valor.titulo}
                          onChange={(next) => definirSeccao(chave, "titulo", next)}
                          placeholder={info?.titulo}
                        />
                        <TextInput
                          label="Subtítulo"
                          value={valor.sub}
                          onChange={(next) => definirSeccao(chave, "sub", next)}
                          placeholder={info?.sub}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Carreiras em destaque</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                As carreiras escolhidas ganham um gráfico com as posições remuneratórias. Sem escolha, a página fica só
                com a tabela-resumo.
              </p>
              <div className="mt-2 max-h-56 overflow-auto">
                <div className="flex flex-wrap gap-1.5">
                  {carreiras.map((item) => {
                    const chave = item.carreira ?? "";
                    if (!chave) return null;
                    const escolhida = (draft.destacar ?? []).includes(chave);
                    return (
                      <button
                        key={`${chave}-${item.categoria}`}
                        type="button"
                        onClick={() =>
                          setDraft({
                            ...draft,
                            destacar: escolhida
                              ? (draft.destacar ?? []).filter((valor) => valor !== chave)
                              : [...(draft.destacar ?? []), chave].slice(0, 12),
                          })
                        }
                        className={`rounded-lg border px-2 py-1 text-[11px] transition ${
                          escolhida ? "border-amber-300/40 bg-amber-300/10 text-amber-100" : "border-white/10 text-muted-foreground"
                        }`}
                      >
                        {chave}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Pré-visualização do modelo</p>
              {dados?.error ? <Notice tone="error">{dados.error}</Notice> : null}
              {dados && !dados.error ? (
                <>
                  <div className="mt-2 flex flex-wrap gap-4 text-[11px]">
                    <span>
                      <strong className="text-foreground">{euros(dados.parametros?.brap)}</strong> · BRAP do nível 5
                    </span>
                    <span>{dados.contagens?.niveis ?? 0} níveis da TRU</span>
                    <span>{dados.contagens?.carreiras ?? 0} carreiras/categorias</span>
                    <span>{dados.contagens?.posicoes ?? 0} posições</span>
                    <span>{dados.contagens?.dirigentes ?? 0} cargos dirigentes</span>
                  </div>
                  {dados.parametros?.brap_nota ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">{dados.parametros.brap_nota}</p>
                  ) : null}
                  <div className="mt-2 max-h-64 overflow-auto">
                    <table className="w-full min-w-[420px] text-[11px]">
                      <thead className="sticky top-0 bg-background/95">
                        <tr className="text-left text-muted-foreground">
                          <th className="py-1 pr-2 font-medium">Nível</th>
                          <th className="py-1 pr-2 text-right font-medium">Remuneração base</th>
                          <th className="py-1 font-medium">Nota</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(dados.niveis ?? []).slice(0, 40).map((nivel) => (
                          <tr key={nivel.nivel} className="border-t border-white/5">
                            <td className="py-1 pr-2 tabular-nums">{nivel.nivel}</td>
                            <td className="py-1 pr-2 text-right tabular-nums">{euros(nivel.valor)}</td>
                            <td className="py-1 text-muted-foreground">{nivel.nota ?? ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    {(dados.niveis ?? []).length} níveis na fotografia · lida a{" "}
                    {dados.gerado_em ? new Date(dados.gerado_em).toLocaleString("pt-PT") : "—"}
                  </p>
                </>
              ) : (
                <p className="mt-2 text-[11px] text-muted-foreground">Carregue em «Reler modelo» para ler o quadro.</p>
              )}
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Blocos e imagens</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Texto, imagens, galerias e destaques na página. A ordem dos blocos é a ordem publicada, entre o texto de
                entrada e as secções.
              </p>
              <div className="mt-2">
                <BlockEditor
                  blocks={(draft.blocks ?? []) as never}
                  onChange={(next) => setDraft({ ...draft, blocks: next as CmsRemuneracao["blocks"] })}
                  blockTypes={ctx.catalogue.block_types}
                  media={media}
                  contents={ctx.catalogue.contents_index}
                  categories={ctx.catalogue.categories_index}
                />
              </div>
            </div>

            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <p className="text-[12px] font-semibold">Blog</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Cria no blog o artigo que anuncia este quadro: nasce rascunho, com a capa, o resumo e a ligação para a
                página. Publica-se no blog como qualquer artigo.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant={draft.artigo_id ? "secondary" : "primary"}
                  icon={<Newspaper size={13} />}
                  loading={aBlog}
                  onClick={() => void criarArtigo()}
                  disabled={!draft.id}
                >
                  {draft.artigo_id ? "Criar outro artigo" : "Criar artigo no blog"}
                </Button>
                {draft.artigo_id ? (
                  <button
                    type="button"
                    className="text-[11.5px] text-teal-200 hover:underline"
                    onClick={() => openExternal(`/cms/blog?id=${draft.artigo_id}`)}
                  >
                    Abrir o artigo no blog
                  </button>
                ) : null}
              </div>
            </div>

            <SeoFields
              seo={draft.seo ?? { title: "", description: "", keywords: [], image_id: null, noindex: false }}
              onChange={(seo) => setDraft({ ...draft, seo })}
              media={media}
            />

            {draft.id && (
              <HistoryPanel
                entity="remuneracoes"
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

/** Botão de pré-visualização usado no cabeçalho das listagens (mantém o ícone). */
export const CmsRemuneracoesPreviewIcon = Eye;
