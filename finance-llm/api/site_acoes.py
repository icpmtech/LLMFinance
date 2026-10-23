"""Ações das páginas de conteúdo: partilhar e guardar nos favoritos.

O mesmo bloco serve o blog e os estudos de benchmark: «Partilhar» (menu com as
redes, mais a partilha do sistema quando o browser a tem) e «Guardar», que
marca a página com uma estrela.

As redes vivem numa só lista (`REDES`): o menu de partilha, a fila do cabeçalho,
o rodapé e o painel do CMS leem daqui, pelo que acrescentar uma rede é acrescentar
uma linha. Três delas — TikTok, Instagram e YouTube — não têm endereço de
partilha (o conteúdo entra pela aplicação): nessas o botão copia a ligação e abre
a rede, com o aviso de que basta colar.

Os favoritos vivem **no browser** (`localStorage`): não há sessão no site
público e não faz sentido pedir uma conta para guardar um artigo. O preço disto
é que a lista não viaja entre dispositivos — a página `/site/favoritos` diz
isso com todas as letras.

O HTML é estático (links de partilha calculados no servidor) e o script só
trata do que precisa de JavaScript: o estado do botão, a cópia da ligação e a
lista de favoritos. Sem JavaScript a página continua a ler-se e o menu de
partilha continua a abrir (`<details>`).
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, quote_plus

#: Chave do `localStorage`. Muda de nome sempre que o formato dos itens mudar.
CHAVE_FAVORITOS = "sabemos:favoritos:v1"
CAMINHO_FAVORITOS = "/site/favoritos"

#: Catálogo das redes: a mesma lista em todo o lado (menu de partilha, fila do
#: cabeçalho, rodapé e painel do CMS). `tipo` diz como se partilha:
#:
#: * `partilha` — a rede aceita o endereço no próprio link (`?url=…`);
#: * `copiar`   — a rede não aceita (TikTok, Instagram, YouTube): copia-se a
#:   ligação, abre-se a rede e o aviso diz para colar.
#:
#: `perfil` é o endereço público usado no cabeçalho e no rodapé quando o editor
#: o preenche nas definições.
REDES: Tuple[Dict[str, str], ...] = (
    {"id": "whatsapp", "label": "WhatsApp", "tipo": "partilha", "perfil": "https://wa.me/"},
    {"id": "x", "label": "X", "tipo": "partilha", "perfil": "https://x.com/"},
    {"id": "facebook", "label": "Facebook", "tipo": "partilha", "perfil": "https://www.facebook.com/"},
    {"id": "linkedin", "label": "LinkedIn", "tipo": "partilha", "perfil": "https://www.linkedin.com/"},
    {"id": "instagram", "label": "Instagram", "tipo": "copiar", "perfil": "https://www.instagram.com/"},
    {"id": "tiktok", "label": "TikTok", "tipo": "copiar", "perfil": "https://www.tiktok.com/"},
    {"id": "youtube", "label": "YouTube", "tipo": "copiar", "perfil": "https://www.youtube.com/"},
    {"id": "reddit", "label": "Reddit", "tipo": "partilha", "perfil": "https://www.reddit.com/"},
    {"id": "telegram", "label": "Telegram", "tipo": "partilha", "perfil": "https://t.me/"},
    {"id": "threads", "label": "Threads", "tipo": "partilha", "perfil": "https://www.threads.net/"},
    {"id": "bluesky", "label": "Bluesky", "tipo": "partilha", "perfil": "https://bsky.app/"},
    {"id": "pinterest", "label": "Pinterest", "tipo": "partilha", "perfil": "https://www.pinterest.com/"},
    {"id": "tumblr", "label": "Tumblr", "tipo": "partilha", "perfil": "https://www.tumblr.com/"},
    # O GitHub não é destino de partilha de um artigo: entra só nas ligações de
    # perfil (cabeçalho e rodapé), por isso fica fora do menu de partilha.
    {"id": "github", "label": "GitHub", "tipo": "perfil", "perfil": "https://github.com/", "menu": "nao"},
    {"id": "email", "label": "Email", "tipo": "partilha", "perfil": ""},
)

#: Índice por identificador (e a ordem em que o menu as mostra).
REDES_POR_ID: Dict[str, Dict[str, str]] = {rede["id"]: rede for rede in REDES}

#: Redes que podem entrar no menu de partilha (todas menos as de perfil).
REDES_MENU: Tuple[Dict[str, str], ...] = tuple(rede for rede in REDES if rede.get("menu") != "nao")

#: O que o menu mostra enquanto ninguém escolher outra coisa no CMS.
REDES_PADRAO: Tuple[str, ...] = (
    "whatsapp",
    "x",
    "facebook",
    "linkedin",
    "instagram",
    "tiktok",
    "youtube",
    "reddit",
    "telegram",
    "threads",
    "bluesky",
    "pinterest",
    "tumblr",
    "email",
)

#: Acima disto, o menu abre em duas colunas (senão ficava mais alto do que o ecrã).
REDES_MENU_LARGO = 8


def redes_do_catalogo() -> List[Dict[str, str]]:
    """Cópia da lista das redes, para o painel do CMS e para o `catalogue()`."""
    return [dict(rede) for rede in REDES]


def redes_validas(valor: Any) -> List[str]:
    """Identificadores aceites para o menu de partilha, sem repetições.

    A ordem é a do catálogo (o painel mostra-as assim) e as redes que só servem
    de ligação de perfil (GitHub) ficam de fora.
    """
    if isinstance(valor, str):
        escolhidas = {valor.strip().lower()}
    elif isinstance(valor, Sequence):
        escolhidas = {str(item).strip().lower() for item in valor if str(item or "").strip()}
    else:
        escolhidas = set()
    return [rede["id"] for rede in REDES_MENU if rede["id"] in escolhidas]


def perfis_configurados(social: Any) -> List[Tuple[str, str, str]]:
    """Redes com endereço público preenchido: `(id, rótulo, href)`.

    É o que o cabeçalho e o rodapé mostram. O email chega sem esquema e ganha
    `mailto:`; o resto é um endereço http(s) escrito tal e qual.
    """
    if not isinstance(social, dict):
        return []
    perfis: List[Tuple[str, str, str]] = []
    for rede in REDES:
        valor = str(social.get(rede["id"]) or "").strip()
        if not valor:
            continue
        if rede["id"] == "email":
            href = valor if valor.lower().startswith("mailto:") else f"mailto:{valor}"
        else:
            href = valor
        perfis.append((rede["id"], rede["label"], href))
    return perfis


_ICONE_PARTILHAR = (
    '<svg class="site-acao-icone" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/>'
    '<path d="m16 6-4-4-4 4"/><path d="M12 2v13"/></svg>'
)

_ICONE_ESTRELA = (
    '<svg class="site-acao-icone" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<path d="m12 3 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.8 6.2 20.9l1.1-6.5L2.6 9.8l6.5-.9z"/></svg>'
)

#: Um script por página: o segundo componente que o pedir não o repete.
#: O estado lê-se sempre do `localStorage`, por isso a ordem dos blocos no HTML
#: não interessa — os botões encontram-se por atributo.
_SCRIPT = """
<script>(function () {
  if (window.SabemosFavoritos) return;
  window.SabemosFavoritos = 1;
  var CHAVE = "__CHAVE__";
  var TIPOS = { artigo: "Artigo", estudo: "Estudo", produto: "Produto", pagina: "Página" };

  function ler() {
    try {
      var valor = JSON.parse(localStorage.getItem(CHAVE) || "[]");
      if (Object.prototype.toString.call(valor) !== "[object Array]") return [];
      return valor.filter(function (item) { return item && item.id; });
    } catch (erro) { return []; }
  }

  function gravar(lista) {
    try { localStorage.setItem(CHAVE, JSON.stringify(lista.slice(0, 300))); } catch (erro) {}
  }

  function aviso(texto) {
    var caixa = document.querySelector("[data-sabemos-aviso]");
    if (!caixa) {
      caixa = document.createElement("div");
      caixa.className = "site-aviso";
      caixa.setAttribute("role", "status");
      caixa.setAttribute("aria-live", "polite");
      caixa.setAttribute("data-sabemos-aviso", "");
      document.body.appendChild(caixa);
    }
    caixa.textContent = texto;
    caixa.classList.add("site-aviso--visivel");
    clearTimeout(aviso.t);
    aviso.t = setTimeout(function () { caixa.classList.remove("site-aviso--visivel"); }, 3200);
  }

  function item(el) {
    return {
      id: el.getAttribute("data-chave") || location.pathname,
      u: el.getAttribute("data-url") || location.href,
      t: el.getAttribute("data-titulo") || document.title,
      k: el.getAttribute("data-tipo") || "pagina",
      i: el.getAttribute("data-imagem") || "",
      p: el.getAttribute("data-preco") || "",
      n: el.getAttribute("data-nota") || ""
    };
  }

  function posicao(lista, id) {
    for (var i = 0; i < lista.length; i++) { if (lista[i].id === id) return i; }
    return -1;
  }

  function sincronizar() {
    var lista = ler();
    var botoes = document.querySelectorAll("[data-favoritar]");
    for (var i = 0; i < botoes.length; i++) {
      var botao = botoes[i];
      var guardado = posicao(lista, botao.getAttribute("data-chave") || location.pathname) >= 0;
      botao.setAttribute("aria-pressed", guardado ? "true" : "false");
      botao.setAttribute("title", guardado ? "Remover dos favoritos" : "Guardar nos favoritos");
      var rotulo = botao.querySelector("[data-favoritar-rotulo]");
      if (rotulo) rotulo.textContent = guardado ? "Guardado" : "Guardar";
    }
    var ligacoes = document.querySelectorAll("[data-favoritos-ligacao]");
    for (var j = 0; j < ligacoes.length; j++) {
      ligacoes[j].hidden = !lista.length;
      var contagem = ligacoes[j].querySelector("[data-favoritos-contagem]");
      if (contagem) contagem.textContent = String(lista.length);
    }
    desenhar(lista);
  }

  function desenhar(lista) {
    var alvo = document.querySelector("[data-favoritos-itens]");
    if (!alvo) return;
    while (alvo.firstChild) alvo.removeChild(alvo.firstChild);
    lista.forEach(function (favorito) {
      var linha = document.createElement("li");
      linha.className = "site-favorito";
      if (favorito.i) {
        var imagem = document.createElement("img");
        imagem.className = "site-favorito-img";
        imagem.src = favorito.i;
        imagem.alt = "";
        imagem.loading = "lazy";
        imagem.addEventListener("error", function () { imagem.remove(); });
        linha.appendChild(imagem);
      }
      var texto = document.createElement("div");
      texto.className = "site-favorito-txt";
      var titulo = document.createElement("a");
      titulo.className = "site-favorito-titulo";
      titulo.href = favorito.u || "#";
      titulo.textContent = favorito.t || favorito.u || "Sem título";
      texto.appendChild(titulo);
      var meta = document.createElement("p");
      meta.className = "site-favorito-meta";
      var tipo = document.createElement("span");
      tipo.textContent = TIPOS[favorito.k] || "Página";
      meta.appendChild(tipo);
      if (favorito.p) {
        var preco = document.createElement("strong");
        preco.textContent = favorito.p;
        meta.appendChild(preco);
      }
      if (favorito.n) {
        var nota = document.createElement("span");
        nota.textContent = favorito.n;
        meta.appendChild(nota);
      }
      if (favorito.d) {
        var data = document.createElement("span");
        try { data.textContent = new Date(favorito.d).toLocaleDateString("pt-PT"); } catch (erro) {}
        meta.appendChild(data);
      }
      texto.appendChild(meta);
      linha.appendChild(texto);
      var remover = document.createElement("button");
      remover.type = "button";
      remover.className = "site-favorito-remover";
      remover.textContent = "Remover";
      remover.setAttribute("data-favoritos-remover", favorito.id);
      linha.appendChild(remover);
      alvo.appendChild(linha);
    });
    var vazio = document.querySelector("[data-favoritos-vazio]");
    if (vazio) vazio.hidden = lista.length > 0;
    var acoes = document.querySelector("[data-favoritos-acoes]");
    if (acoes) acoes.hidden = !lista.length;
    var total = document.querySelector("[data-favoritos-total]");
    if (total) total.textContent = String(lista.length);
  }

  function alternar(el) {
    var novo = item(el);
    var lista = ler();
    var indice = posicao(lista, novo.id);
    if (indice >= 0) {
      lista.splice(indice, 1);
      gravar(lista);
      aviso("Removido dos favoritos");
    } else {
      novo.d = Date.now();
      lista.unshift(novo);
      gravar(lista);
      aviso("Guardado nos favoritos");
    }
    sincronizar();
  }

  function copiar(texto) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(texto);
    }
    return new Promise(function (resolver, rejeitar) {
      try {
        var caixa = document.createElement("textarea");
        caixa.value = texto;
        caixa.setAttribute("readonly", "");
        caixa.style.position = "fixed";
        caixa.style.top = "-1000px";
        document.body.appendChild(caixa);
        caixa.select();
        var feito = document.execCommand("copy");
        document.body.removeChild(caixa);
        feito ? resolver() : rejeitar();
      } catch (erro) { rejeitar(); }
    });
  }

  function fecharMenus(exceto) {
    var menus = document.querySelectorAll("details.site-partilha[open]");
    for (var i = 0; i < menus.length; i++) {
      if (menus[i] !== exceto && !menus[i].contains(exceto)) menus[i].open = false;
    }
  }

  // O menu é mais largo do que um cartão: ao abrir, desloca-se o mínimo para
  // caber no ecrã (o mesmo menu serve a barra do artigo, encostada à esquerda,
  // e o cartão, onde o botão pode estar perto da margem direita).
  function alinharMenu(detalhe) {
    var menu = detalhe.querySelector(".site-partilha-menu");
    if (!menu) return;
    menu.style.removeProperty("--desvio");
    if (!menu.offsetWidth) return;
    var margem = 10;
    // No cartão a caixa é presa ao ecrã (`position: fixed`): fica por cima do
    // botão quando cabe, senão por baixo, e encostada à esquerda dele.
    if (detalhe.closest(".site-cartao-acoes")) {
      var alvo = detalhe.getBoundingClientRect();
      var altura = menu.offsetHeight;
      var topo = alvo.top - altura - 8;
      if (topo < margem) {
        topo = alvo.bottom + 8;
        if (topo + altura > window.innerHeight - margem) topo = Math.max(margem, window.innerHeight - altura - margem);
      }
      menu.style.top = Math.round(topo) + "px";
      menu.style.bottom = "auto";
      menu.style.left = Math.round(alvo.left) + "px";
    }
    var caixa = menu.getBoundingClientRect();
    var desvio = 0;
    if (caixa.right > window.innerWidth - margem) desvio = window.innerWidth - margem - caixa.right;
    if (caixa.left + desvio < margem) desvio = margem - caixa.left;
    if (desvio) menu.style.setProperty("--desvio", Math.round(desvio) + "px");
  }

  document.addEventListener("toggle", function (evento) {
    var alvo = evento.target;
    if (!alvo || alvo.tagName !== "DETAILS" || !alvo.classList || !alvo.classList.contains("site-partilha")) return;
    if (alvo.open) alinharMenu(alvo);
  }, true);

  window.addEventListener("resize", function () {
    var abertos = document.querySelectorAll("details.site-partilha[open]");
    for (var i = 0; i < abertos.length; i++) alinharMenu(abertos[i]);
  });

  document.addEventListener("click", function (evento) {
    var alvo = evento.target;
    if (!alvo || !alvo.closest) return;

    var favoritar = alvo.closest("[data-favoritar]");
    if (favoritar) { evento.preventDefault(); alternar(favoritar); return; }

    var copiarBotao = alvo.closest("[data-copiar]");
    if (copiarBotao) {
      evento.preventDefault();
      var endereco = copiarBotao.getAttribute("data-copiar") || location.href;
      copiar(endereco).then(
        function () { aviso("Ligação copiada"); },
        function () { aviso("Não foi possível copiar"); }
      );
      fecharMenus(null);
      return;
    }

    // Redes sem endereço de partilha (TikTok, Instagram, YouTube): a ligação vai
    // para a área de transferência e o browser abre a rede — o aviso diz para
    // colar. O `href` segue o caminho normal (nova janela), sem `preventDefault`.
    var copiarEAbrir = alvo.closest("[data-partilha-copiar]");
    if (copiarEAbrir) {
      var nome = copiarEAbrir.getAttribute("data-partilha-rede") || "rede social";
      copiar(copiarEAbrir.getAttribute("data-partilha-copiar") || location.href).then(
        function () { aviso("Ligação copiada — cole no " + nome); },
        function () {}
      );
      fecharMenus(null);
      return;
    }

    var remover = alvo.closest("[data-favoritos-remover]");
    if (remover) {
      evento.preventDefault();
      var lista = ler();
      var indice = posicao(lista, remover.getAttribute("data-favoritos-remover"));
      if (indice >= 0) {
        lista.splice(indice, 1);
        gravar(lista);
        sincronizar();
        aviso("Removido dos favoritos");
      }
      return;
    }

    var limpar = alvo.closest("[data-favoritos-limpar]");
    if (limpar) {
      evento.preventDefault();
      if (window.confirm("Remover todos os favoritos deste navegador?")) {
        gravar([]);
        sincronizar();
        aviso("Favoritos removidos");
      }
      return;
    }

    var menuAberto = alvo.closest("details.site-partilha");
    fecharMenus(menuAberto);
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape") fecharMenus(null);
  });

  var nativo = document.querySelector("[data-partilhar]");
  if (nativo && navigator.share) {
    nativo.hidden = false;
    nativo.addEventListener("click", function () {
      navigator.share({
        title: nativo.getAttribute("data-titulo") || document.title,
        url: nativo.getAttribute("data-url") || location.href
      }).catch(function () {});
    });
  }

  window.addEventListener("storage", sincronizar);
  sincronizar();
})();</script>
"""


def script() -> str:
    """O script das ações, com a chave dos favoritos já dentro."""
    return _SCRIPT.replace("__CHAVE__", CHAVE_FAVORITOS).strip()


def _destino_da_rede(rede: str, url: str, titulo: str, imagem: str = "") -> str:
    """Endereço de partilha da rede (o próprio sítio quando não aceita uma)."""
    texto = quote_plus(f"{titulo} {url}")
    alvo = quote_plus(url)
    etiqueta = quote_plus(titulo)
    assunto = quote(titulo)
    if rede == "whatsapp":
        return f"https://wa.me/?text={texto}"
    if rede == "x":
        return f"https://x.com/intent/post?text={etiqueta}&url={alvo}"
    if rede == "facebook":
        return f"https://www.facebook.com/sharer/sharer.php?u={alvo}"
    if rede == "linkedin":
        return f"https://www.linkedin.com/sharing/share-offsite/?url={alvo}"
    if rede == "reddit":
        return f"https://www.reddit.com/submit?url={alvo}&title={etiqueta}"
    if rede == "telegram":
        return f"https://t.me/share/url?url={alvo}&text={etiqueta}"
    if rede == "threads":
        return f"https://www.threads.net/intent/post?text={texto}"
    if rede == "bluesky":
        return f"https://bsky.app/intent/compose?text={texto}"
    if rede == "pinterest":
        return (
            "https://www.pinterest.com/pin/create/button/"
            f"?url={alvo}&description={etiqueta}" + (f"&media={quote_plus(imagem)}" if imagem else "")
        )
    if rede == "tumblr":
        return f"https://www.tumblr.com/widgets/share/tool?canonicalUrl={alvo}&title={etiqueta}"
    if rede == "email":
        return f"mailto:?subject={assunto}&body={texto}"
    # TikTok, Instagram e YouTube e GitHub: sem link de partilha — abre-se a rede
    # (o script copia a ligação antes) e o endereço do perfil vem do catálogo.
    return REDES_POR_ID[rede]["perfil"] or url


def _ligacoes_partilha(
    url: str,
    titulo: str,
    redes: Optional[Sequence[str]] = None,
    imagem: str = "",
) -> str:
    """Itens do menu de partilha, pelas redes escolhidas (por omissão, todas)."""
    escolhidas = redes_validas(redes) if redes is not None else list(REDES_PADRAO)
    partes: List[str] = []
    for rede in escolhidas:
        info = REDES_POR_ID.get(rede)
        if not info:
            continue
        destino = _destino_da_rede(rede, url, titulo, imagem)
        copiar = (
            f' data-partilha-copiar="{escape(url, quote=True)}"'
            f' data-partilha-rede="{escape(info["label"], quote=True)}"'
            if info["tipo"] == "copiar"
            else ""
        )
        partes.append(
            f'<a class="site-partilha-item" role="menuitem" href="{escape(destino, quote=True)}"'
            f' target="_blank" rel="noopener"{copiar}>{escape(info["label"])}</a>'
        )
    return "".join(partes)


def _menu_partilha(
    url: str,
    titulo: str,
    *,
    redes: Optional[Sequence[str]] = None,
    imagem: str = "",
    resumo: str = "",
    rotulo: str = "Partilhar",
    atributos_resumo: str = "",
    aria: str = "Partilhar esta página",
) -> str:
    """O `<details>` do menu de partilha (abre sem JavaScript)."""
    escolhidas = redes_validas(redes) if redes is not None else list(REDES_PADRAO)
    largura = " site-partilha-menu--redes" if len(escolhidas) > REDES_MENU_LARGO else ""
    itens = _ligacoes_partilha(url, titulo, escolhidas, imagem)
    return (
        '<details class="site-partilha">'
        f'<summary class="{escape(resumo or "site-acao", quote=True)}"{atributos_resumo}>'
        f"{_ICONE_PARTILHAR}{escape(rotulo) if rotulo else ''}</summary>"
        f'<div class="site-partilha-menu{largura}" role="menu" aria-label="{escape(aria, quote=True)}">'
        + itens
        + '<button type="button" class="site-partilha-item" role="menuitem" data-partilhar hidden'
        + f' data-url="{escape(url, quote=True)}" data-titulo="{escape(titulo, quote=True)}">'
        + "Partilhar…</button>"
        + '<button type="button" class="site-partilha-item" role="menuitem"'
        + f' data-copiar="{escape(url, quote=True)}">Copiar ligação</button>'
        + "</div></details>"
    )


def barra_acoes(
    *,
    url: str,
    titulo: str,
    tipo: str = "pagina",
    chave: str = "",
    extra: str = "",
    redes: Optional[Sequence[str]] = None,
    guardar: bool = True,
    imagem: str = "",
    com_script: bool = True,
) -> str:
    """A barra «Partilhar · Guardar · ver favoritos» de uma página.

    `url` é o endereço que se partilha (absoluto quando o site tem `base_url`);
    `chave` identifica o favorito e por omissão é o próprio `url`. `extra` entra
    à frente dos botões — o blog mete aí o descarregamento do relatório.
    `redes` são as redes do menu (por omissão, as de `REDES_PADRAO`) e `guardar`
    desliga o botão dos favoritos. `com_script=False` serve as listas: o script
    entra uma vez por página (ver `script()`).
    """
    url = str(url or "")
    titulo = str(titulo or "")
    chave = str(chave or url)
    atributos = (
        f'data-chave="{escape(chave, quote=True)}"'
        f' data-url="{escape(url, quote=True)}"'
        f' data-titulo="{escape(titulo, quote=True)}"'
        f' data-tipo="{escape(tipo, quote=True)}"'
    )
    guardar_html = (
        f'<button type="button" class="site-acao site-acao--guardar" data-favoritar {atributos}>'
        + _ICONE_ESTRELA
        + '<span data-favoritar-rotulo>Guardar</span></button>'
        if guardar
        else ""
    )
    return (
        '<div class="site-acoes">'
        + extra
        + _menu_partilha(url, titulo, redes=redes, imagem=imagem)
        + guardar_html
        + '<a class="site-acao site-acao--ligacao" href="'
        + CAMINHO_FAVORITOS
        + '" data-favoritos-ligacao hidden>'
        + '<span data-favoritos-contagem>0</span> favoritos</a>'
        + "</div>"
        + (script() if com_script else "")
    )


def acoes_do_cartao(
    *,
    chave: str,
    url: str,
    titulo: str,
    tipo: str = "artigo",
    imagem: str = "",
    redes: Optional[Sequence[str]] = None,
    guardar: bool = True,
) -> str:
    """A estrela e a partilha de um cartão numa lista (blog, estudos, produtos).

    Não traz script — a página que o usa chama `script()` uma vez. As duas ações
    ficam em círculos pequenos, por cima do cartão (ver `.site-cartao-acoes`).
    """
    escolhidas = redes_validas(redes) if redes is not None else list(REDES_PADRAO)
    if not escolhidas and not guardar:
        return ""
    url = str(url or "")
    titulo = str(titulo or "")
    partes: List[str] = []
    if escolhidas:
        partes.append(
            _menu_partilha(
                url,
                titulo,
                redes=escolhidas,
                imagem=imagem,
                resumo="site-fav-icone site-fav-icone--partilha",
                rotulo="",
                atributos_resumo=f' aria-label="Partilhar «{escape(titulo, quote=True)}»" title="Partilhar"',
                aria="Partilhar este artigo",
            )
        )
    if guardar:
        partes.append(
            botao_favorito(
                chave=chave,
                url=url,
                titulo=titulo,
                tipo=tipo,
                imagem=imagem,
            )
        )
    return f'<div class="site-cartao-acoes">{"".join(partes)}</div>'



def botao_favorito(
    *,
    chave: str,
    url: str,
    titulo: str,
    tipo: str = "produto",
    imagem: str = "",
    preco: str = "",
    nota: str = "",
    classe: str = "",
) -> str:
    """A estrela de um cartão (produto ou artigo numa lista).

    Não traz script: quem o põe na página já traz a barra de ações, e o script
    encontra os botões todos por atributo.
    """
    atributos = (
        f'data-chave="{escape(str(chave), quote=True)}"'
        f' data-url="{escape(str(url), quote=True)}"'
        f' data-titulo="{escape(str(titulo), quote=True)}"'
        f' data-tipo="{escape(str(tipo), quote=True)}"'
    )
    for nome, valor in (("data-imagem", imagem), ("data-preco", preco), ("data-nota", nota)):
        if valor:
            atributos += f' {nome}="{escape(str(valor), quote=True)}"'
    return (
        f'<button type="button" class="site-fav-icone {escape(classe, quote=True).strip()}"'
        f' data-favoritar {atributos} aria-pressed="false" aria-label="Guardar nos favoritos">'
        + _ICONE_ESTRELA
        + "</button>"
    )


def lista_favoritos() -> str:
    """O corpo da página `/site/favoritos` (a lista é desenhada pelo script)."""
    return (
        '<div class="site-favoritos" data-favoritos-lista>'
        '<p class="site-favoritos-vazio" data-favoritos-vazio>'
        "Ainda não guardou nada. Use a estrela «Guardar» num artigo ou num estudo "
        "e ele aparece aqui."
        "</p>"
        '<ul class="site-favoritos-lista" data-favoritos-itens></ul>'
        '<div class="site-favoritos-acoes" data-favoritos-acoes hidden>'
        '<span class="site-favoritos-total"><strong data-favoritos-total>0</strong> guardados</span>'
        '<button type="button" class="btn ghost" data-favoritos-limpar>Limpar favoritos</button>'
        "</div>"
        '<noscript><p class="site-favoritos-nota">Os favoritos são guardados no seu '
        "navegador e precisam de JavaScript para aparecer.</p></noscript>"
        "</div>"
        + script()
    )
