/**
 * Administração · **Plataforma**.
 *
 * Edita o **cabeçalho e o rodapé das páginas públicas da plataforma** — a
 * entrada (`/`, `/login` e `/register`): marca, logótipo, navegação, botões e
 * rodapé. É uma definição da plataforma, separada da do site público do CMS
 * (`/site/...`, que se edita em CMS → Aparência).
 *
 * O que se guarda em `/admin/app-shell` é servido a seguir em `/app-shell`, sem
 * reiniciar nada. Deixar o rótulo ou o endereço de um botão vazio **tira-o** do
 * cabeçalho; a marca sem nome volta à predefinição (o cabeçalho nunca fica sem
 * nome). As imagens vão para a biblioteca do CMS (`Media`) e entram aqui como
 * endereço — a mesma biblioteca, sem uma segunda forma de guardar ficheiros.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  Globe2,
  Image as ImageIcon,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";

import { Button } from "../components/ui/Button";
import { getAdminAppShell, saveAdminAppShell } from "../adminApi";
import { cmsMediaUrl, fileToBase64, uploadCmsMedia } from "../cmsApi";
import type { AppShellState, ShellLink } from "../appShellApi";

/** Rascunho do painel: os botões são sempre dois campos (vazios = sem botão). */
type Rascunho = {
  brand: { name: string; tagline: string; logo_url: string; logo_alt: string };
  header: { items: ShellLink[]; cta: ShellLink; secondary: ShellLink };
  footer: { text: string; items: ShellLink[]; social: Record<string, string> };
};

function paraRascunho(doc: AppShellState["shell"] | AppShellState["defaults"]): Rascunho {
  const vazio: ShellLink = { label: "", href: "" };
  return {
    brand: { ...doc.brand },
    header: {
      items: doc.header.items.map((item) => ({ ...item })),
      cta: doc.header.cta ? { ...doc.header.cta } : { ...vazio },
      secondary: doc.header.secondary ? { ...doc.header.secondary } : { ...vazio },
    },
    footer: {
      text: doc.footer.text,
      items: doc.footer.items.map((item) => ({ ...item })),
      social: { ...doc.footer.social },
    },
  };
}

const CLASSE_CAMPO =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-[12.5px] outline-none transition " +
  "placeholder:text-muted-foreground focus:border-teal-300/40 focus:bg-white/[0.06]";

function Campo({
  label,
  value,
  onChange,
  placeholder,
  maxLength,
  wide = false,
}: {
  label: string;
  value: string;
  onChange: (valor: string) => void;
  placeholder?: string;
  maxLength?: number;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "block md:col-span-2" : "block"}>
      <span className="mb-1 block text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className={CLASSE_CAMPO}
      />
    </label>
  );
}

/** Lista de ligações (rótulo + endereço), com ordem, remoção e limite. */
function ListaDeLigacoes({
  titulo,
  itens,
  onChange,
  limites,
}: {
  titulo: string;
  itens: ShellLink[];
  onChange: (proximos: ShellLink[]) => void;
  limites: AppShellState["limits"];
}) {
  const trocar = (posicao: number, passo: number) => {
    const destino = posicao + passo;
    if (destino < 0 || destino >= itens.length) return;
    const proximos = itens.map((item) => ({ ...item }));
    [proximos[posicao], proximos[destino]] = [proximos[destino], proximos[posicao]];
    onChange(proximos);
  };

  return (
    <div>
      <p className="mb-2 text-[12.5px] font-semibold">{titulo}</p>
      {itens.length === 0 && (
        <p className="mb-2 text-[11.5px] text-muted-foreground">
          Sem ligações. Acrescente as que quer mostrar (por exemplo «Blog» → <span className="font-mono">/site/blog</span>).
        </p>
      )}
      <div className="space-y-2">
        {itens.map((item, posicao) => (
          <div key={`${item.href}-${posicao}`} className="flex flex-wrap items-center gap-2">
            <input
              value={item.label}
              onChange={(event) =>
                onChange(itens.map((outro, indice) => (indice === posicao ? { ...outro, label: event.target.value } : outro)))
              }
              placeholder="Rótulo"
              maxLength={limites.label}
              className={`${CLASSE_CAMPO} sm:max-w-[200px]`}
            />
            <input
              value={item.href}
              onChange={(event) =>
                onChange(itens.map((outro, indice) => (indice === posicao ? { ...outro, href: event.target.value } : outro)))
              }
              placeholder="/site/blog"
              maxLength={limites.href}
              className={`${CLASSE_CAMPO} font-mono sm:max-w-[280px]`}
            />
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => trocar(posicao, -1)}
                disabled={posicao === 0}
                aria-label="Subir a ligação"
                className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.09] disabled:opacity-40"
              >
                <ArrowUp size={12} />
              </button>
              <button
                type="button"
                onClick={() => trocar(posicao, 1)}
                disabled={posicao === itens.length - 1}
                aria-label="Descer a ligação"
                className="rounded-lg border border-white/10 bg-white/[0.04] p-1.5 text-muted-foreground transition hover:bg-white/[0.09] disabled:opacity-40"
              >
                <ArrowDown size={12} />
              </button>
              <button
                type="button"
                onClick={() => onChange(itens.filter((_, indice) => indice !== posicao))}
                aria-label="Remover a ligação"
                className="rounded-lg border border-rose-400/20 bg-rose-500/10 p-1.5 text-rose-200 transition hover:bg-rose-500/20"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="mt-2"
        icon={<Plus size={13} />}
        onClick={() => onChange([...itens, { label: "", href: "" }])}
        disabled={itens.length >= limites.links}
      >
        Adicionar ligação
      </Button>
      {itens.length >= limites.links && (
        <span className="ml-2 text-[11px] text-amber-200">Limite de {limites.links} ligações.</span>
      )}
    </div>
  );
}

export function AdminPlatformTab({ onError }: { onError: (message: string | null) => void }) {
  const [estado, setEstado] = useState<AppShellState | null>(null);
  const [rascunho, setRascunho] = useState<Rascunho | null>(null);
  const [busy, setBusy] = useState<"load" | "save" | "logo" | null>("load");
  const [aviso, setAviso] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setBusy("load");
    try {
      const resultado = await getAdminAppShell();
      setEstado(resultado);
      setRascunho(paraRascunho(resultado.shell));
      setAviso(null);
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao carregar o cabeçalho da plataforma.");
    } finally {
      setBusy(null);
    }
  }, [onError]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const guardar = async () => {
    if (!rascunho) return;
    setBusy("save");
    setAviso(null);
    try {
      const resultado = await saveAdminAppShell(rascunho);
      setEstado(resultado);
      setRascunho(paraRascunho(resultado.shell));
      setAviso("Cabeçalho e rodapé das páginas públicas atualizados. Já valem na próxima visita.");
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao gravar o cabeçalho da plataforma.");
    } finally {
      setBusy(null);
    }
  };

  const carregarLogotipo = async (ficheiro: File | undefined) => {
    if (!ficheiro || !rascunho) return;
    setBusy("logo");
    setAviso(null);
    try {
      const data = await fileToBase64(ficheiro);
      const resultado = await uploadCmsMedia({
        filename: ficheiro.name,
        mime: ficheiro.type || "application/octet-stream",
        data,
        title: "Logótipo da plataforma",
      });
      const endereco = cmsMediaUrl(resultado.item);
      setRascunho({ ...rascunho, brand: { ...rascunho.brand, logo_url: endereco } });
      setAviso("Imagem carregada para a biblioteca do CMS. Guarde para a usar no cabeçalho.");
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao carregar a imagem.");
    } finally {
      setBusy(null);
    }
  };

  if (!rascunho || !estado) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={15} className="animate-spin" /> A carregar o cabeçalho da plataforma…
        </p>
      </div>
    );
  }

  const limites = estado.limits;
  const externo = /^https?:\/\//i.test(rascunho.brand.logo_url);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
      <div className="glass-card gradient-border shrink-0 rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <Globe2 size={16} /> Plataforma — cabeçalho e rodapé públicos
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              O que a plataforma mostra a quem ainda não entrou (a entrada em <span className="font-mono">/login</span>,{" "}
              <span className="font-mono">/register</span> e a página inicial). É independente do site público, que se edita
              em CMS → Aparência.
              {estado.shell.updated_at ? (
                <>
                  {" "}
                  Última alteração: {new Date(estado.shell.updated_at).toLocaleString("pt-PT", { hour12: false })}
                  {estado.shell.updated_by ? ` por ${estado.shell.updated_by}` : ""}.
                </>
              ) : null}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => void carregar()} disabled={busy !== null}>
              {busy === "load" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Recarregar
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setRascunho(paraRascunho(estado.defaults));
                setAviso("Predefinições carregadas no formulário. Guarde para as aplicar.");
              }}
              disabled={busy !== null}
            >
              <RotateCcw size={14} /> Repor predefinições
            </Button>
            <Button onClick={() => void guardar()} disabled={busy !== null} loading={busy === "save"}>
              <Save size={14} /> Guardar
            </Button>
          </div>
        </div>
        {aviso && <p className="mt-3 text-[11.5px] text-teal-200">{aviso}</p>}
      </div>

      {/* Marca */}
      <section className="glass-card shrink-0 rounded-2xl p-5">
        <h3 className="mb-3 text-[13px] font-semibold">Marca</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <Campo
            label="Nome"
            value={rascunho.brand.name}
            onChange={(valor) => setRascunho({ ...rascunho, brand: { ...rascunho.brand, name: valor } })}
            placeholder="IQ OS"
            maxLength={limites.label}
          />
          <Campo
            label="Frase de topo"
            value={rascunho.brand.tagline}
            onChange={(valor) => setRascunho({ ...rascunho, brand: { ...rascunho.brand, tagline: valor } })}
            placeholder="Plataforma de inteligência financeira"
            maxLength={limites.text}
          />
          <Campo
            label="Endereço do logótipo"
            value={rascunho.brand.logo_url}
            onChange={(valor) => setRascunho({ ...rascunho, brand: { ...rascunho.brand, logo_url: valor } })}
            placeholder="Vazio usa a marca em gradiente da plataforma"
            maxLength={limites.href}
            wide
          />
          <Campo
            label="Texto alternativo do logótipo"
            value={rascunho.brand.logo_alt}
            onChange={(valor) => setRascunho({ ...rascunho, brand: { ...rascunho.brand, logo_alt: valor } })}
            placeholder="O nome, quando fica em branco"
            maxLength={limites.label}
          />
          <div className="flex items-center gap-3">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-[12.5px] transition hover:bg-white/[0.08]">
              <ImageIcon size={14} />
              {busy === "logo" ? "A carregar…" : "Carregar imagem"}
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  void carregarLogotipo(event.target.files?.[0]);
                  event.target.value = "";
                }}
                disabled={busy !== null}
              />
            </label>
            {rascunho.brand.logo_url ? (
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={13} />}
                onClick={() => setRascunho({ ...rascunho, brand: { ...rascunho.brand, logo_url: "" } })}
                disabled={busy !== null}
              >
                Remover
              </Button>
            ) : null}
          </div>
        </div>

        {/* Pré-visualização da marca: é a peça que o visitante vê primeiro. */}
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
          {rascunho.brand.logo_url ? (
            <img src={rascunho.brand.logo_url} alt="" className="h-10 w-auto max-w-[200px] object-contain" />
          ) : (
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 via-teal-500 to-blue-600 text-white">
              <Sparkles size={18} />
            </span>
          )}
          <span className="min-w-0">
            <span className="block text-sm font-semibold leading-tight">{rascunho.brand.name || "IQ OS"}</span>
            {rascunho.brand.tagline ? (
              <span className="block text-[11.5px] text-muted-foreground">{rascunho.brand.tagline}</span>
            ) : null}
          </span>
          {externo && (
            <a
              href={rascunho.brand.logo_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground transition hover:text-foreground"
            >
              <ExternalLink size={11} /> ver imagem
            </a>
          )}
        </div>
      </section>

      {/* Cabeçalho */}
      <section className="glass-card shrink-0 rounded-2xl p-5">
        <h3 className="mb-3 text-[13px] font-semibold">Cabeçalho</h3>
        <ListaDeLigacoes
          titulo="Navegação"
          itens={rascunho.header.items}
          onChange={(itens) => setRascunho({ ...rascunho, header: { ...rascunho.header, items: itens } })}
          limites={limites}
        />
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-2 text-[12.5px] font-semibold">Botão principal</p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={rascunho.header.cta.label}
                onChange={(event) =>
                  setRascunho({ ...rascunho, header: { ...rascunho.header, cta: { ...rascunho.header.cta, label: event.target.value } } })
                }
                placeholder="Criar conta"
                maxLength={limites.label}
                className={`${CLASSE_CAMPO} sm:max-w-[160px]`}
              />
              <input
                value={rascunho.header.cta.href}
                onChange={(event) =>
                  setRascunho({ ...rascunho, header: { ...rascunho.header, cta: { ...rascunho.header.cta, href: event.target.value } } })
                }
                placeholder="/register"
                maxLength={limites.href}
                className={`${CLASSE_CAMPO} font-mono sm:max-w-[200px]`}
              />
            </div>
          </div>
          <div>
            <p className="mb-2 text-[12.5px] font-semibold">Botão secundário</p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={rascunho.header.secondary.label}
                onChange={(event) =>
                  setRascunho({
                    ...rascunho,
                    header: { ...rascunho.header, secondary: { ...rascunho.header.secondary, label: event.target.value } },
                  })
                }
                placeholder="Entrar"
                maxLength={limites.label}
                className={`${CLASSE_CAMPO} sm:max-w-[160px]`}
              />
              <input
                value={rascunho.header.secondary.href}
                onChange={(event) =>
                  setRascunho({
                    ...rascunho,
                    header: { ...rascunho.header, secondary: { ...rascunho.header.secondary, href: event.target.value } },
                  })
                }
                placeholder="/login"
                maxLength={limites.href}
                className={`${CLASSE_CAMPO} font-mono sm:max-w-[200px]`}
              />
            </div>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Deixar o rótulo ou o endereço vazio tira o botão do cabeçalho.
        </p>
      </section>

      {/* Rodapé */}
      <section className="glass-card shrink-0 rounded-2xl p-5">
        <h3 className="mb-3 text-[13px] font-semibold">Rodapé</h3>
        <div className="grid gap-3">
          <Campo
            label="Frase do rodapé"
            value={rascunho.footer.text}
            onChange={(valor) => setRascunho({ ...rascunho, footer: { ...rascunho.footer, text: valor } })}
            placeholder="Sabemos Studio · IQ OS"
            maxLength={limites.text}
            wide
          />
        </div>
        <div className="mt-3">
          <ListaDeLigacoes
            titulo="Ligações"
            itens={rascunho.footer.items}
            onChange={(itens) => setRascunho({ ...rascunho, footer: { ...rascunho.footer, items: itens } })}
            limites={limites}
          />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {estado.social.map((rede) => (
            <Campo
              key={rede.key}
              label={rede.label}
              value={rascunho.footer.social[rede.key] ?? ""}
              onChange={(valor) =>
                setRascunho({ ...rascunho, footer: { ...rascunho.footer, social: { ...rascunho.footer.social, [rede.key]: valor } } })
              }
              placeholder={rede.key === "email" ? "geral@sabemos.studio" : "https://…"}
              maxLength={limites.href}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
