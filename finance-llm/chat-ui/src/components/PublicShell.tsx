/**
 * Cabeçalho e rodapé das páginas públicas da plataforma.
 *
 * Usados pela entrada (`/login`, `/register`) e pela landing (`/`), para que as
 * duas mostrem a mesma navegação e o mesmo rodapé — editáveis no backoffice
 * (Administração → **Plataforma**), sem passar por aqui.
 *
 * Enquanto a configuração não chega (ou se a API falhar), desenha-se a
 * predefinição: a página de entrada nunca fica à espera de um pedido para poder
 * aparecer.
 */
import { useState } from "react";
import { ArrowRight, Menu, Sparkles, X } from "lucide-react";

import { linkExterno, type AppShell, type ShellLink } from "../appShellApi";
import { useAppShell } from "../appShell";

/** Atributos de um link que sai da plataforma (janela nova, sem perder a página). */
function externo(href: string) {
  return linkExterno(href) ? { target: "_blank", rel: "noreferrer" } : {};
}

function Marca({ brand }: { brand: AppShell["brand"] }) {
  return (
    <>
      {brand.logo_url ? (
        <img
          src={brand.logo_url}
          alt={brand.logo_alt}
          className="h-10 w-auto max-w-[200px] object-contain"
          height={40}
        />
      ) : (
        <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-teal-400 via-teal-500 to-blue-600 text-white shadow-lg shadow-teal-500/25">
          <Sparkles size={20} />
        </span>
      )}
      <span className="min-w-0">
        <span className="block text-lg font-semibold leading-tight">{brand.name}</span>
        {brand.tagline ? (
          <span className="block text-xs text-muted-foreground">{brand.tagline}</span>
        ) : null}
      </span>
    </>
  );
}

/** Botão que abre o painel do telemóvel (o `className` decide em que ecrãs existe). */
function BotaoDoMenu({
  className,
  aberto,
  onToggle,
}: {
  className: string;
  aberto: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={aberto}
      aria-controls="menu-publico"
      aria-label={aberto ? "Fechar o menu" : "Abrir o menu"}
      className={`rounded-xl border border-white/10 bg-white/5 p-2 text-muted-foreground transition hover:bg-white/10 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70 ${className}`}
    >
      {aberto ? <X size={18} /> : <Menu size={18} />}
    </button>
  );
}

export function PublicHeader() {
  const { brand, header } = useAppShell();
  const [aberto, setAberto] = useState(false);
  const links = header.items;
  const ligacao = "rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition hover:text-foreground";
  const ligacaoDoPainel =
    "rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition hover:bg-white/5 hover:text-foreground";
  const alternar = () => setAberto((valor) => !valor);
  // O painel do telemóvel leva a navegação e, quando não cabem no cabeçalho, os
  // dois botões (é o único caminho para «Entrar» em ecrãs estreitos).
  const temBotoes = Boolean(header.secondary || header.cta);
  const temPainel = links.length > 0 || temBotoes;

  return (
    <header className="relative z-30 mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-5">
      <a href="/" className="flex items-center gap-3" aria-label={`${brand.name} — início`}>
        <Marca brand={brand} />
      </a>

      {links.length > 0 ? (
        <nav aria-label="Navegação principal" className="hidden items-center gap-1 md:flex">
          {links.map((link: ShellLink) => (
            <a key={link.href} href={link.href} className={ligacao} {...externo(link.href)}>
              {link.label}
            </a>
          ))}
        </nav>
      ) : null}

      <div className="flex items-center gap-2">
        {header.secondary ? (
          <a
            href={header.secondary.href}
            className="hidden rounded-xl px-4 py-2 text-sm font-medium text-muted-foreground transition hover:text-foreground sm:inline-block"
            {...externo(header.secondary.href)}
          >
            {header.secondary.label}
          </a>
        ) : null}
        {header.cta ? (
          <a
            href={header.cta.href}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/70"
            {...externo(header.cta.href)}
          >
            {header.cta.label}
            <ArrowRight size={15} />
          </a>
        ) : null}
        {links.length > 0 ? (
          <BotaoDoMenu className="md:hidden" aberto={aberto} onToggle={alternar} />
        ) : temBotoes ? (
          // Sem navegação, o painel serve os botões que o cabeçalho não mostra em
          // ecrãs estreitos: o botão existe só onde eles faltam.
          <BotaoDoMenu className="sm:hidden" aberto={aberto} onToggle={alternar} />
        ) : null}
      </div>

      {/* Painel do telemóvel: a navegação que no ecrã grande está ao lado e, abaixo
          de `sm`, os dois botões (que aí não cabem no cabeçalho). */}
      {aberto && temPainel ? (
        <nav
          id="menu-publico"
          aria-label="Navegação principal"
          className="absolute inset-x-4 top-full flex flex-col gap-1 rounded-2xl border border-white/10 bg-background/95 p-2 shadow-2xl backdrop-blur-xl md:hidden"
        >
          {links.map((link: ShellLink) => (
            <a
              key={link.href}
              href={link.href}
              className={ligacaoDoPainel}
              onClick={() => setAberto(false)}
              {...externo(link.href)}
            >
              {link.label}
            </a>
          ))}

          {/* Os botões do cabeçalho, quando não cabem nele (abaixo de `sm`). */}
          {header.secondary ? (
            <a
              href={header.secondary.href}
              className={`sm:hidden ${ligacaoDoPainel}`}
              onClick={() => setAberto(false)}
              {...externo(header.secondary.href)}
            >
              {header.secondary.label}
            </a>
          ) : null}
          {header.cta ? (
            <a
              href={header.cta.href}
              className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-blue-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-teal-500/20 transition hover:brightness-110 sm:hidden"
              onClick={() => setAberto(false)}
              {...externo(header.cta.href)}
            >
              {header.cta.label}
              <ArrowRight size={15} />
            </a>
          ) : null}
        </nav>
      ) : null}
    </header>
  );
}

export function PublicFooter() {
  const { brand, footer } = useAppShell();
  const ligacao = "transition hover:text-foreground";

  return (
    <footer className="relative z-10 border-t border-white/5 py-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 sm:flex-row">
        <div className="flex items-center gap-2 text-center text-sm text-muted-foreground sm:text-left">
          <Sparkles size={16} className="text-teal-300" />
          {/* Sem frase de rodapé, fica o nome da plataforma: nunca fica vazio. */}
          <span>{footer.text || brand.name}</span>
        </div>
        {footer.items.length > 0 || footer.social.length > 0 ? (
          <nav aria-label="Ligações do rodapé" className="flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground">
            {footer.items.map((link: ShellLink) => (
              <a key={link.href} href={link.href} className={ligacao} {...externo(link.href)}>
                {link.label}
              </a>
            ))}
            {footer.social.map((rede) => (
              <a key={rede.key} href={rede.href} className={ligacao} {...externo(rede.href)}>
                {rede.label}
              </a>
            ))}
          </nav>
        ) : null}
      </div>
    </footer>
  );
}
