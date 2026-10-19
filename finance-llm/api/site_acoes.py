"""Ações das páginas de conteúdo: partilhar e guardar nos favoritos.

O mesmo bloco serve o blog e os estudos de benchmark: «Partilhar» (menu com as
redes, mais a partilha do sistema quando o browser a tem) e «Guardar», que
marca a página com uma estrela.

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
from urllib.parse import quote, quote_plus

#: Chave do `localStorage`. Muda de nome sempre que o formato dos itens mudar.
CHAVE_FAVORITOS = "sabemos:favoritos:v1"
CAMINHO_FAVORITOS = "/site/favoritos"

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


def _ligacoes_partilha(url: str, titulo: str) -> str:
    texto = quote_plus(f"{titulo} {url}")
    assunto = quote(titulo)
    redes = (
        ("WhatsApp", f"https://wa.me/?text={texto}"),
        ("X", f"https://x.com/intent/post?text={quote_plus(titulo)}&url={quote_plus(url)}"),
        ("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={quote_plus(url)}"),
        ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={quote_plus(url)}"),
        ("Email", f"mailto:?subject={assunto}&body={texto}"),
    )
    return "".join(
        f'<a class="site-partilha-item" role="menuitem" href="{escape(destino, quote=True)}"'
        ' target="_blank" rel="noopener">'
        f"{escape(nome)}</a>"
        for nome, destino in redes
    )


def barra_acoes(
    *,
    url: str,
    titulo: str,
    tipo: str = "pagina",
    chave: str = "",
    extra: str = "",
) -> str:
    """A barra «Partilhar · Guardar · ver favoritos» de uma página.

    `url` é o endereço que se partilha (absoluto quando o site tem `base_url`);
    `chave` identifica o favorito e por omissão é o próprio `url`. `extra` entra
    à frente dos botões — o blog mete aí o descarregamento do relatório.
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
    return (
        '<div class="site-acoes">'
        + extra
        + '<details class="site-partilha">'
        + f'<summary class="site-acao">{_ICONE_PARTILHAR}Partilhar</summary>'
        + '<div class="site-partilha-menu" role="menu" aria-label="Partilhar esta página">'
        + _ligacoes_partilha(url, titulo)
        + '<button type="button" class="site-partilha-item" role="menuitem" data-partilhar hidden'
        + f' data-url="{escape(url, quote=True)}" data-titulo="{escape(titulo, quote=True)}">'
        + "Partilhar…</button>"
        + '<button type="button" class="site-partilha-item" role="menuitem"'
        + f' data-copiar="{escape(url, quote=True)}">Copiar ligação</button>'
        + "</div></details>"
        + f'<button type="button" class="site-acao site-acao--guardar" data-favoritar {atributos}>'
        + _ICONE_ESTRELA
        + '<span data-favoritar-rotulo>Guardar</span></button>'
        + '<a class="site-acao site-acao--ligacao" href="'
        + CAMINHO_FAVORITOS
        + '" data-favoritos-ligacao hidden>'
        + '<span data-favoritos-contagem>0</span> favoritos</a>'
        + "</div>"
        + script()
    )


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
