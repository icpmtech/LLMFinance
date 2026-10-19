"""Renderização do site público do CMS (`/site/...`).

Converte o modelo do `cms_store` em HTML pronto a servir: páginas por blocos,
artigos de blog, índice do blog (com paginação, categoria e etiqueta), RSS,
sitemap e `robots.txt`.

O HTML é **autónomo** (CSS embutido, JS mínimo) para poder ser servido por
qualquer proxy e indexado pelos motores de busca: cada página leva `title`,
`meta description`, canónica, Open Graph e JSON-LD. A aparência vem das
definições do site (`theme`, `accent`, `radius`). O único script de terceiros é
o widget de apoio ao cliente (`api/tawk.py`).
"""
from __future__ import annotations

import functools
import html
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

import markdown as markdown_lib

from api import captcha
from api import cms_store as store
from api import tawk

logger = logging.getLogger(__name__)

MD_EXTENSIONS = ["extra", "sane_lists", "nl2br", "toc"]

#: Pagamentos de remuneração base num ano: 12 mensalidades, subsídio de férias e
#: subsídio de Natal (Lei n.º 35/2014, LTFP, artigos 149.º a 152.º).
PAGAMENTOS_PUBLICO = 14

#: Limite do `<title>` já com o sufixo da marca: acima disto os motores de busca
#: cortam (e os resultados passam a mostrar uma frase a meio).
LIMITE_TITULO_HEAD = 70
#: Abaixo disto não vale a pena cortar o título para lhe colar a marca.
MINIMO_TITULO_HEAD = 24

_THEMES: Dict[str, Dict[str, str]] = {
    "claro": {
        "bg": "#f7f8fa",
        "surface": "#ffffff",
        "text": "#101828",
        "muted": "#5b6472",
        "border": "#e4e7ec",
        "code": "#f1f3f6",
        "shadow": "0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.06)",
    },
    "escuro": {
        "bg": "#0b1020",
        "surface": "#131a2e",
        "text": "#f2f4f8",
        "muted": "#9aa4b8",
        "border": "#26304a",
        "code": "#1b2440",
        "shadow": "0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.35)",
    },
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _md(text: str) -> str:
    """Markdown → HTML (com tabelas, listas e código)."""
    if not (text or "").strip():
        return ""
    try:
        markup = markdown_lib.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")
    except Exception as exc:  # pragma: no cover - markdown robusto
        logger.warning("Falha a converter Markdown (%s); a devolver texto.", exc)
        return f"<p>{_esc(text)}</p>"
    return _envolver_tabelas(markup)


_TABELA_RE = re.compile(r"<table>.*?</table>", re.S | re.I)


def _envolver_tabelas(markup: str) -> str:
    """Põe cada tabela dentro de um contentor que rola na horizontal.

    Num telefone uma tabela de sete colunas não cabe no ecrã: sem isto, ou
    esmaga o texto numa coluna de três letras, ou empurra a página toda para o
    lado. A partir de quatro colunas o contentor ganha uma largura mínima, para
    rolar em vez de apertar.
    """

    def troca(encontro: "re.Match[str]") -> str:
        tabela = encontro.group(0)
        classe = "tabela-rolavel larga" if tabela.lower().count("<th") >= 4 else "tabela-rolavel"
        return f'<div class="{classe}">{tabela}</div>'

    return _TABELA_RE.sub(troca, markup)


def _garantir_h1(body: str, titulo: str) -> str:
    """Garante um `<h1>` no corpo da página, sem o repetir.

    O cabeçalho das páginas montadas a blocos vinha **só** do bloco «hero»: uma
    página feita com outros blocos (texto, KPIs, tabelas) saía sem `<h1>` nenhum
    — o erro «H1 tag missing» dos relatórios de SEO. Sem hero (e sem um `<h1>`
    vindo do Markdown), o título do documento passa a ser o cabeçalho; com hero,
    o corpo já traz o seu e não se acrescenta outro.
    """
    if not titulo or "<h1" in body.lower():
        return body
    return f'<section class="section"><h1>{_esc(titulo)}</h1></section>{body}'


def _cortar_em_palavras(texto: str, limite: int) -> str:
    """Encurta `texto` ao `limite` sem cortar uma palavra (nem deixar pontuação solta)."""
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rstrip()
    espaco = corte.rfind(" ")
    if espaco >= max(limite // 2, 1):
        corte = corte[:espaco]
    return corte.rstrip(" .,;:·–—-")


def _titulo_do_head(title: str, site_name: str) -> str:
    """`título · marca` para o `<title>` (e o `og:title`), cortado em palavras.

    O título do documento pode ser tão longo quanto o autor quiser — o `<h1>` fica
    todo. O do `<head>` é que não pode passar dos ~70 caracteres: um artigo de 79
    caracteres virava 96 com a marca e o motor de busca mostrava uma frase cortada
    a meio. Encurta-se o título, nunca o sufixo da marca; sem espaço para os dois,
    fica só o título (a marca já vai no `og:site_name`).
    """
    titulo = re.sub(r"\s+", " ", str(title or "")).strip()
    if not titulo:
        return site_name
    if not site_name or site_name in titulo:
        return _cortar_em_palavras(titulo, LIMITE_TITULO_HEAD)
    espaco = LIMITE_TITULO_HEAD - len(site_name) - len(" · ")
    if espaco < MINIMO_TITULO_HEAD:
        return _cortar_em_palavras(titulo, LIMITE_TITULO_HEAD)
    return f"{_cortar_em_palavras(titulo, espaco)} · {site_name}"


def _titulo_visivel(doc: Dict[str, Any], alternativa: str = "") -> str:
    """Título que serve de `<h1>`: o de SEO quando existe, senão o do documento.

    É o mesmo valor que vai para o `<title>`, para o cabeçalho da página dizer
    o mesmo que o resultado na pesquisa.
    """
    seo = doc.get("seo") if isinstance(doc.get("seo"), dict) else {}
    return str(seo.get("title") or doc.get("title") or alternativa or "")


def _media(media_id: Optional[str]) -> Dict[str, Any]:
    if not media_id:
        return {}
    try:
        return store.get_item("media", media_id) or {}
    except KeyError:
        return {}


def _media_url(media_id: Optional[str]) -> str:
    return str(_media(media_id).get("url") or "")


def _variante_movel(media_id: Optional[str]) -> Tuple[str, str]:
    """URL e id da versão em coluna do mesmo gráfico, se ela existir.

    Um diagrama de 1100px de largura fica com o texto a 4px num telefone. Ao
    lado de `diagrama-x.svg` vive `diagrama-x-movel.svg`, desenhado em coluna, e
    é o `<picture>` que escolhe: o computador continua a ver o diagrama largo e
    o telefone vê o outro — sem o CMS ter de saber que os dois existem.
    """
    nome = str(_media(media_id).get("filename") or "")
    if not nome or nome.endswith("-movel.svg"):
        return "", ""
    raiz, ponto, extensao = nome.rpartition(".")
    if not ponto or not raiz:
        return "", ""
    alvo = f"{raiz}-movel.{extensao}"
    for item in store.list_items("media", limit=1000).get("items") or []:
        if str(item.get("filename") or "") == alvo:
            return str(item.get("url") or ""), str(item.get("id") or "")
    return "", ""


def _dimensoes(media_id: Optional[str]) -> str:
    """`width`/`height`, quando conhecidos.

    Sem eles o texto salta quando a figura acaba de carregar — e num telefone,
    onde a figura ocupa o ecrã todo, o salto é a página inteira.
    """
    media = _media(media_id)
    largura, altura = media.get("width"), media.get("height")
    if not largura or not altura:
        return ""
    return f' width="{int(largura)}" height="{int(altura)}"'


def _proporcao_movel(media_id: Optional[str]) -> str:
    """Proporção da variante em coluna, para o CSS reservar a altura certa.

    Vai como valor completo de `aspect-ratio` (e não só como a proporção) para o
    `var()` do CSS nunca ficar inválido. A variante em coluna é bem mais alta do
    que o gráfico largo — sem isto, num telefone a caixa reservava uma faixa
    baixa e a figura dava um salto de centenas de pixels ao aparecer.
    """
    media = _media(media_id)
    largura, altura = media.get("width"), media.get("height")
    if not largura or not altura:
        return ""
    return f' style="--proporcao-movel: auto {int(largura)} / {int(altura)}"'


def _absolute(url: str, base_url: str = "") -> str:
    if not url:
        return base_url
    if url.startswith(("http://", "https://")):
        return url
    return f"{base_url.rstrip('/')}{url}" if base_url else url


def _date(value: Optional[str], with_time: bool = False) -> str:
    if not value:
        return ""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.strftime("%d/%m/%Y %H:%M") if with_time else stamp.astimezone().strftime("%d/%m/%Y")


def _css(settings: Dict[str, Any]) -> str:
    """As variáveis do tema do site, em linha.

    O resto do CSS vive em `site-css/src/site.css` (Tailwind), compilado para
    `api/site_assets/site.css` e servido como ficheiro em `CSS_PATH`. Aqui fica
    só o que depende das definições do CMS e mudaria sem recompilar: a paleta do
    tema, a cor de destaque e o raio dos cantos.
    """
    theme_name = str(settings.get("theme") or "claro")
    if theme_name not in _THEMES:
        theme_name = "claro"
    palette = _THEMES[theme_name]
    accent = str(settings.get("accent") or "#0ea5a4")
    radius = int(settings.get("radius") or 14)
    return (
        ":root{"
        f"--bg:{palette['bg']};--surface:{palette['surface']};--text:{palette['text']};"
        f"--muted:{palette['muted']};--border:{palette['border']};--code:{palette['code']};"
        f"--shadow:{palette['shadow']};--accent:{accent};--radius:{radius}px"
        "}"
    )


# --------------------------------------------------------------------------
# Blocos
# --------------------------------------------------------------------------
def _render_content_block(content_id: str) -> str:
    try:
        content = store.get_item("contents", content_id)
    except KeyError:
        return ""
    kind = content.get("kind")
    body = _md(str(content.get("body") or ""))
    data = content.get("data") or {}
    if kind == "cta":
        return (
            f'<div class="cta"><div><h2>{_esc(data.get("title") or content.get("title"))}</h2>'
            f'<p>{_esc(data.get("text") or "")}</p></div>'
            f'<div class="actions">{_cta_botoes(data)}</div></div>'
        )
    if kind == "hero":
        return (
            f'<div class="hero"><h1>{_esc(data.get("title") or content.get("title"))}</h1>'
            f'<p class="lead">{_esc(data.get("subtitle") or "")}</p></div>'
        )
    if kind == "aviso":
        return f'<div class="aviso {_esc(data.get("tone") or "")}">{body}</div>'
    if kind == "contactos":
        parts = []
        if data.get("email"):
            parts.append(f'<div><strong>Email</strong><br><a href="mailto:{_esc(data["email"])}">{_esc(data["email"])}</a></div>')
        if data.get("phone"):
            parts.append(f'<div><strong>Telefone</strong><br>{_esc(data["phone"])}</div>')
        if data.get("address"):
            parts.append(f'<div><strong>Morada</strong><br>{_esc(data["address"])}</div>')
        return f'<div class="section"><div class="contactos">{"".join(parts)}</div></div>'
    if kind == "rodape":
        return f'<div class="prose">{body}</div>'
    return f'<div class="prose">{body}</div>'


def _render_library_block(data: Dict[str, Any], *, preview: bool = False) -> str:
    """Relatórios gratuitos e documentos já gerados, por área de trabalho.

    O conteúdo é lido a cada renderização (`reports_library`): publicar um
    relatório no Estúdio ou mudar um preço no catálogo muda a página sem a
    reabrir no CMS. Sem nada publicado (instalação nova), a pré-visualização
    mostra a explicação em vez de uma secção vazia.
    """
    from api import reports_library as library  # noqa: PLC0415 - import tardio: a loja é grande

    free_only = bool(data.get("free_only"))
    # As áreas podem vir como lista (editorial) ou como um texto do formulário.
    raw_areas = data.get("areas")
    if isinstance(raw_areas, str):
        areas = [part.strip() for part in raw_areas.replace(";", ",").split(",") if part.strip()]
    else:
        areas = [str(item) for item in (raw_areas or []) if str(item).strip()]
    limite = int(data.get("limit") or 24)
    dados = library.library(areas=areas or None, limit=limite, free_only=free_only)
    titulo = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
    intro = f'<p class="lead">{_esc(data.get("intro"))}</p>' if data.get("intro") else ""
    cta_label = _esc(data.get("cta_label") or "Pedir este relatório")
    cta_href = _esc(data.get("cta_href") or "/reports")

    if not dados["items"]:
        vazio = (
            "Ainda não há relatórios publicados. Os relatórios gratuitos do catálogo e os documentos "
            "gerados no Estúdio aparecem aqui automaticamente."
        )
        return f'<div class="section">{titulo}{intro}<p class="lead">{_esc(vazio)}</p></div>'

    resumo = (
        f'<p class="library-count">{dados["total"]} documento(s) em {dados["areas_total"]} área(s) — '
        f'{dados["free"]} gratuito(s), {dados["documents"]} já gerado(s).</p>'
    )
    secoes: List[str] = []
    for area in dados["areas"]:
        cartoes = []
        for item in area["items"]:
            etiquetas = []
            if item["free"]:
                etiquetas.append('<span class="tag tag-free">Grátis</span>')
            else:
                preco = f"{item['price']:.2f}".replace(".", ",")
                etiquetas.append(f'<span class="tag tag-price">{_esc(preco)} €</span>')
            etiquetas.append(f'<span class="tag">{_esc(item["kind_label"])}</span>')
            if item.get("badge"):
                etiquetas.append(f'<span class="tag tag-auto">{_esc(item["badge"])}</span>')
            if item.get("delivery_days"):
                prazo = "1 dia" if int(item["delivery_days"]) == 1 else f'{int(item["delivery_days"])} dias'
                etiquetas.append(f'<span class="tag">{_esc(prazo)}</span>')

            descricao = item.get("subtitle") or item.get("note")
            detalhe = f'<p>{_esc(descricao)}</p>' if descricao else ""
            itens = [
                f'<li>{_esc(feature)}</li>' for feature in (item.get("features") or [])[:4]
            ]
            lista = f'<ul class="library-list">{"".join(itens)}</ul>' if itens else ""

            if item.get("download"):
                # `download` para o browser guardar o ficheiro em vez de o abrir
                # na própria página (o nome vem do cabeçalho da resposta).
                acao = (
                    f'<a class="btn" href="{_esc(item["download"])}" download>'
                    "Descarregar PDF</a>"
                )
            else:
                acao = f'<a class="btn ghost" href="{cta_href}">{cta_label}</a>'
            cartoes.append(
                f'<article class="card library-card">'
                f'<div class="library-tags">{"".join(etiquetas)}</div>'
                f'<h3>{_esc(item["title"])}</h3>{detalhe}{lista}'
                f'<div class="library-actions">{acao}</div>'
                f"</article>"
            )
        cabeca = (
            f'<div class="library-area-head"><h3>{_esc(area["label"])}</h3>'
            + (f'<p>{_esc(area["hint"])}</p>' if area.get("hint") else "")
            + f'<span class="library-area-count">{area["total"]}</span></div>'
        )
        secoes.append(f'<section class="library-area">{cabeca}<div class="cards">{"".join(cartoes)}</div></section>')

    return f'<div class="section">{titulo}{intro}{resumo}{"".join(secoes)}</div>'


def _render_blog_block(data: Dict[str, Any], *, preview: bool) -> str:
    limit = int(data.get("limit") or 3)
    category_id = data.get("category_id") or None
    posts = store.published_posts(category_id=str(category_id) if category_id else None, limit=limit)
    if preview and not posts:
        posts = [post for post in (store.list_items("posts", limit=limit)["items"]) if not post.get("markdown")]
    title = str(data.get("title") or "")
    head = f"<h2>{_esc(title)}</h2>" if title else ""
    if not posts:
        return f'<div class="section">{head}<p class="lead">Ainda não há artigos publicados.</p></div>'
    cards = "".join(_post_card(post) for post in posts)
    return f'<div class="section">{head}<div class="posts">{cards}</div></div>'


# --------------------------------------------------------------------------
# Formulário de contacto
# --------------------------------------------------------------------------
#: Campos do formulário, pela ordem em que aparecem. Cada campo leva: `nome`,
#: `etiqueta`, `tipo`, `obrigatorio`, `autocomplete`, `linhas` (textarea),
#: `ajuda` (linha de apoio, ligada ao campo por `aria-describedby`), `larga`
#: (ocupa as duas colunas da grelha) e `sugestoes` (valores oferecidos por um
#: `datalist` — sugerem os assuntos que tratamos sem impedir outra resposta).
CAMPOS_CONTACTO: List[Dict[str, Any]] = [
    {"nome": "nome", "etiqueta": "Nome", "obrigatorio": True, "autocomplete": "name"},
    {"nome": "email", "etiqueta": "Email", "tipo": "email", "obrigatorio": True, "autocomplete": "email"},
    {"nome": "organizacao", "etiqueta": "Organização", "autocomplete": "organization"},
    {
        "nome": "assunto",
        "etiqueta": "Assunto",
        "sugestoes": ("Análise à medida", "Correção de um número", "Dados e cobertura", "Imprensa"),
    },
    {
        "nome": "mensagem",
        "etiqueta": "Mensagem",
        "obrigatorio": True,
        "linhas": 6,
        "larga": True,
        "ajuda": "Diga o que quer saber, para quando e sobre que entidade ou concelho — o NIF ajuda a não trocar de empresa.",
    },
]

FORMULARIO_ACTION_PADRAO = "/site/contacto"


def _campo_do_formulario(campo: Dict[str, Any], valor: str = "", erro: str = "") -> str:
    nome = str(campo["nome"])
    ident = f"contacto-{nome}"
    atributos = ""
    if campo.get("obrigatorio"):
        atributos += ' required aria-required="true"'
    if campo.get("autocomplete"):
        atributos += f' autocomplete="{_esc(campo["autocomplete"])}"'
    limite = store.CONTACTO_LIMITES.get(nome)
    if limite:
        # O mesmo limite que o servidor aplica (`cms_store.CONTACTO_LIMITES`):
        # sem ele, um pedido longo só era recusado depois de escrito.
        atributos += f' maxlength="{int(limite)}"'
    ajuda = ""
    if campo.get("ajuda"):
        ajuda = f'<small class="ajuda" id="{ident}-ajuda">{_esc(campo["ajuda"])}</small>'
        atributos += f' aria-describedby="{ident}-ajuda"'
    sugestoes = "".join(f'<option value="{_esc(item)}"></option>' for item in (campo.get("sugestoes") or ()))
    if campo.get("linhas"):
        controlo = f'<textarea id="{ident}" name="{nome}" rows="{int(campo["linhas"])}"{atributos}>{_esc(valor)}</textarea>'
    else:
        if sugestoes:
            atributos += f' list="{ident}-sugestoes"'
        controlo = f'<input id="{ident}" name="{nome}" type="{_esc(campo.get("tipo") or "text")}" value="{_esc(valor)}"{atributos}>'
        if sugestoes:
            controlo += f'<datalist id="{ident}-sugestoes">{sugestoes}</datalist>'
    nota = f'<small class="erro" role="alert">{_esc(erro)}</small>' if erro else ""
    # A marca de obrigatório fica fora da leitura em voz alta: quem usa leitor de
    # ecrã ouve «obrigatório» pelo próprio campo, não um asterisco.
    etiqueta = _esc(campo["etiqueta"]) + (' <span class="marca" aria-hidden="true">*</span>' if campo.get("obrigatorio") else "")
    classe = "campo larga" if campo.get("larga") else "campo"
    return f'<div class="{classe}"><label for="{ident}">{etiqueta}</label>{controlo}{ajuda}{nota}</div>'


def _campo_do_captcha(desafio: Dict[str, str], erro: str = "") -> str:
    """Desafio anti-robô: a pergunta é legível e o testemunho vai escondido.

    A pergunta é o próprio rótulo do campo — quem usa leitor de ecrã ouve «Quanto
    dá sete mais cinco?» antes de responder, sem precisar de uma imagem (que não
    se ouve) nem de JavaScript (que o site não pede).
    """
    ident = f"contacto-{captcha.CAMPO_RESPOSTA}"
    nota = f'<small class="erro" role="alert">{_esc(erro)}</small>' if erro else ""
    return (
        '<div class="campo captcha">'
        f'<label for="{ident}">{_esc(desafio.get("pergunta") or "")}</label>'
        f'<input id="{ident}" name="{captcha.CAMPO_RESPOSTA}" type="text" value="" inputmode="numeric"'
        f' autocomplete="off" required aria-required="true" aria-describedby="{ident}-ajuda" maxlength="4">'
        f'<small class="ajuda" id="{ident}-ajuda">Responda em algarismos. É só para confirmar que é uma pessoa.</small>'
        f'<input type="hidden" name="{captcha.CAMPO_TESTEMUNHO}" value="{_esc(desafio.get("token") or "")}">'
        f"{nota}</div>"
    )


def formulario_contacto(
    data: Dict[str, Any],
    *,
    valores: Optional[Dict[str, str]] = None,
    erros: Optional[Dict[str, str]] = None,
    aviso: str = "",
    desafio: Optional[Dict[str, str]] = None,
) -> str:
    """Formulário de contacto (grava em `/site/contacto`, sem depender de JS).

    Os campos vão em grelha — uma coluna no telefone, duas a partir de 700px — e
    o que acontece depois do envio fica na linha do botão, não depois dele: quem
    está a decidir se escreve vê a mesma informação que quem já escreveu.

    O `desafio` anti-robô é sempre novo a cada renderização: um testemunho que
    falhou não se repete, e quem volta à página responde a outra conta.
    """
    valores = valores or {}
    erros = erros or {}
    desafio = desafio or captcha.desafio()
    action = str(data.get("action") or FORMULARIO_ACTION_PADRAO)
    ancora = str(data.get("anchor") or "").strip()
    ident = f' id="{_esc(ancora)}"' if ancora else ""
    titulo = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
    intro = f'<p class="lead">{_esc(data.get("intro"))}</p>' if data.get("intro") else ""
    legenda = (
        '<p class="ajuda-formulario">Os campos com <span class="marca" aria-hidden="true">*</span> são '
        "obrigatórios. Os restantes ajudam-nos a responder com mais precisão.</p>"
    )
    corpo = "".join(_campo_do_formulario(campo, valores.get(str(campo["nome"]), ""), erros.get(str(campo["nome"]), "")) for campo in CAMPOS_CONTACTO)
    erro_consentimento = f'<small class="erro" role="alert">{_esc(erros["consentimento"])}</small>' if erros.get("consentimento") else ""
    nota = f'<div class="nota-formulario">{_md(str(data.get("note") or ""))}</div>' if data.get("note") else ""
    return (
        f'<div class="section formulario"{ident}>{titulo}{intro}{legenda}'
        + (f'<div class="aviso red">{_esc(aviso)}</div>' if aviso else "")
        + f'<form method="post" action="{_esc(action)}">'
        + f'<div class="campos">{corpo}</div>'
        + '<div class="campo consentimento">'
        + '<input id="contacto-consentimento" name="consentimento" type="checkbox" value="sim"'
        + (' checked' if valores.get("consentimento") else "")
        + ' required aria-required="true">'
        + '<label for="contacto-consentimento">Autorizo que me contactem por email sobre este pedido. '
        + "Os dados são usados só para responder e podem ser apagados a pedido.</label>"
        + "</div>"
        + erro_consentimento
        + _campo_do_captcha(desafio, erros.get(captcha.CAMPO_RESPOSTA, ""))
        + '<div class="hp"><label for="contacto-website">Não preencher</label>'
        + '<input id="contacto-website" name="website" type="text" tabindex="-1" autocomplete="off"></div>'
        + '<div class="acao"><button class="btn" type="submit">'
        + f'{_esc(data.get("button_label") or "Enviar mensagem")}</button>{nota}'
        + "</div></form></div>"
    )


def render_contacto(
    *,
    ok: bool,
    valores: Optional[Dict[str, str]] = None,
    erros: Optional[Dict[str, str]] = None,
    aviso: str = "",
    settings: Optional[Dict[str, Any]] = None,
    voltar_para: str = "/site/contactos",
) -> str:
    """Resposta do formulário de contacto: agradecimento ou erros a corrigir."""
    settings = settings or store.get_settings()
    if ok:
        corpo = (
            '<div class="section contacto-ok"><h1>Mensagem recebida</h1>'
            "<p class=\"lead\">Obrigado. O pedido ficou registado e respondemos para o email indicado — "
            "pedidos simples, em dias úteis.</p>"
            "<p class=\"ajuda-formulario\">Se precisar de acrescentar algo, responda ao email que receber ou "
            'escreva para <a href="mailto:suporte@sabemos.studio">suporte@sabemos.studio</a>.</p>'
            f'<div class="actions"><a class="btn" href="{_esc(voltar_para)}">Voltar aos contactos</a>'
            '<a class="btn ghost" href="/site/blog">Ler o blog</a></div></div>'
        )
        return _layout(
            title="Mensagem recebida",
            description="Pedido de contacto registado.",
            body=corpo,
            current_path="/site/contacto",
            settings=settings,
            canonical="/site/contacto",
            noindex=True,
        )
    corpo = formulario_contacto(
        {"title": "Fale connosco", "intro": "Corrija o que falta e volte a enviar."},
        valores=valores,
        erros=erros,
        aviso=aviso,
    )
    return _layout(
        title="Fale connosco",
        description="Formulário de contacto.",
        body=corpo,
        current_path="/site/contacto",
        settings=settings,
        canonical="/site/contacto",
        noindex=True,
    )


def _cta_botoes(data: Dict[str, Any]) -> str:
    """Botões de uma chamada à ação: o principal e os secundários (`buttons`)."""
    botoes = [
        f'<a class="btn" href="{_esc(data.get("button_href") or "#")}">'
        f'{_esc(data.get("button_label") or "Saber mais")}</a>'
    ]
    for extra in data.get("buttons") or []:
        if not isinstance(extra, dict):
            continue
        botoes.append(
            f'<a class="btn ghost" href="{_esc(extra.get("href") or "#")}">'
            f'{_esc(extra.get("label") or "Saber mais")}</a>'
        )
    return "".join(botoes)


def _grafico_numero(valor: Any) -> Optional[float]:
    """Valor de uma barra, ou `None` quando não há número nenhum para desenhar."""
    if isinstance(valor, str):
        # «1 234,5» e «1,234.5» chegam os dois: aceita-se o que o CMS gravar.
        valor = valor.strip().replace(" ", "").replace("€", "")
        if "," in valor and "." in valor:
            valor = valor.replace(".", "").replace(",", ".")
        else:
            valor = valor.replace(",", ".")
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _grafico_rotulo(valor: float, formato: str) -> str:
    if formato == "percentagem":
        return f"{valor:.1f}".replace(".", ",") + " %"
    if formato == "numero":
        return _numero(round(valor))
    # A partir dos mil milhões o «2 543,3 M€» deixa de se ler: passa a «2,54 mil M€».
    if abs(valor) >= 1_000_000_000:
        return f"{valor / 1_000_000_000:.2f}".replace(".", ",") + " mil M€"
    return _euros_curto(valor)


def _grafico_barras(data: Dict[str, Any]) -> str:
    """Barras horizontais em HTML/CSS puro — sem JavaScript nem bibliotecas.

    O valor vai sempre **escrito** ao lado do nome, por isso o gráfico é legível
    por quem usa leitor de ecrã, por quem imprime e por quem abre a página sem
    CSS. Cada item pode ter uma segunda série (`value2`), desenhada na mesma
    escala — é o que permite comparar, lado a lado, o peso no número de
    contratos e o peso no valor.
    """
    itens: List[Dict[str, Any]] = []
    for item in data.get("series") or []:
        if not isinstance(item, dict):
            continue
        principal = _grafico_numero(item.get("value"))
        if principal is None:
            continue
        itens.append({"nome": str(item.get("label") or ""), "value": principal, "value2": _grafico_numero(item.get("value2")), "nota": str(item.get("note") or "")})
    if not itens:
        return ""

    formato = str(data.get("format") or "euros").strip().lower()
    if formato not in ("euros", "numero", "percentagem"):
        formato = "euros"
    medido = [abs(item["value"]) for item in itens] + [abs(item["value2"]) for item in itens if item["value2"] is not None]
    maximo = _grafico_numero(data.get("max"))
    if not maximo or maximo <= 0:
        maximo = max(medido) if medido else 0.0

    def largura(valor: Optional[float]) -> int:
        if valor is None or maximo <= 0:
            return 0
        return max(2, round(abs(valor) / maximo * 100))

    tem_segunda = any(item["value2"] is not None for item in itens)

    def linha(item: Dict[str, Any]) -> str:
        principal, secundaria = item["value"], item["value2"]
        barras = f'<span class="grafico-barra"><span style="width:{largura(principal)}%"></span></span>'
        if item["value2"] is not None and tem_segunda:
            barras += f'<span class="grafico-barra secundaria"><span style="width:{largura(secundaria)}%"></span></span>'
        nota = f'<p class="grafico-item-nota">{_esc(item["nota"])}</p>' if item["nota"] else ""
        regua = ""
        if item["value2"] is not None and tem_segunda:
            regua = f'<span class="grafico-item-regua">{_grafico_rotulo(secundaria or 0.0, formato)}</span>'
        return (
            f'<li class="grafico-item"><div class="grafico-topo">'
            f'<span class="grafico-nome">{_esc(item["nome"])}</span>'
            f'<span class="grafico-valores"><span class="grafico-valor">{_grafico_rotulo(principal, formato)}</span>{regua}</span>'
            f"</div>{barras}{nota}</li>"
        )

    titulo = f'<h2>{_esc(data.get("title"))}</h2>' if data.get("title") else ""
    nota = f'<p class="grafico-nota">{_esc(data.get("note"))}</p>' if data.get("note") else ""
    legenda = ""
    rotulos = [str(item) for item in (data.get("legend") or [])]
    if tem_segunda and rotulos:
        entradas = [
            f'<li class="{classe}"><span class="grafico-ponto"></span>{_esc(nome)}</li>'
            for classe, nome in (("", rotulos[0]), ("secundaria", rotulos[1] if len(rotulos) > 1 else ""))
            if nome
        ]
        legenda = f'<ul class="grafico-legenda">{"".join(entradas)}</ul>' if entradas else ""
    fonte = f'<p class="grafico-fonte">{_esc(data.get("source"))}</p>' if data.get("source") else ""
    return (
        f'<div class="section">{titulo}{nota}{legenda}'
        f'<ul class="grafico-lista">{"".join(linha(item) for item in itens)}</ul>{fonte}</div>'
    )


def _render_block(block: Dict[str, Any], *, preview: bool = False) -> str:
    if block.get("hidden"):
        return ""
    block_type = str(block.get("type") or "texto")
    data = block.get("data") or {}

    if block_type == "hero":
        title = _esc(data.get("title") or "")
        subtitle = _esc(data.get("subtitle") or "")
        image = _media_url(data.get("image_id"))
        style = str(data.get("style") or "simples").strip().lower()
        if style not in store.HERO_STYLE_IDS:
            style = "simples"
        tone = str(data.get("tone") or "acento").strip().lower()
        if tone not in store.HERO_TONE_IDS:
            tone = "acento"
        classes = [f"hero hero--{style}", f"hero--tom-{tone}"]
        if str(data.get("align") or "") == "centro":
            classes.append("centro")
        if not image:
            classes.append("sem-imagem")
        actions = ""
        if data.get("cta_label"):
            actions = (
                f'<div class="actions"><a class="btn" href="{_esc(data.get("cta_href") or "#")}">'
                f'{_esc(data.get("cta_label"))}</a></div>'
            )
        heading = f"<h1>{title}</h1>" if title else ""
        copy = f'<div class="hero-copy">{heading}<p class="lead">{subtitle}</p>{actions}</div>'
        # Com «imagem de fundo» a fotografia cobre o bloco, com um véu por cima.
        if style == "imagem" and image:
            return (
                f'<div class="{" ".join(classes)}">'
                f'<img class="hero-bg" src="{_esc(image)}" alt="" aria-hidden="true">'
                f"{copy}</div>"
            )
        cover = f'<figure class="cover"><img src="{_esc(image)}" alt=""></figure>' if image else ""
        return f'<div class="{" ".join(classes)}">{copy}{cover}</div>'

    if block_type == "texto":
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section prose">{title}{_md(str(data.get("markdown") or data.get("body") or ""))}</div>'

    if block_type == "imagem":
        media_id = data.get("media_id")
        url = _media_url(media_id) or str(data.get("url") or "")
        if not url:
            return ""
        caption = f"<figcaption>{_esc(data.get('caption'))}</figcaption>" if data.get("caption") else ""
        alt = _esc(data.get("alt"))
        medidas = _dimensoes(media_id)
        movel, movel_id = _variante_movel(media_id)
        if movel:
            imagem = (
                f'<picture><source media="(max-width: 899px)" srcset="{_esc(movel)}">'
                f'<img src="{_esc(url)}" alt="{alt}"{medidas}{_proporcao_movel(movel_id)} loading="lazy" decoding="async"></picture>'
            )
        else:
            imagem = f'<img src="{_esc(url)}" alt="{alt}"{medidas} loading="lazy" decoding="async">'
        return f"<figure>{imagem}{caption}</figure>"

    if block_type == "galeria":
        urls = [_media_url(item) for item in (data.get("media_ids") or [])]
        urls = [url for url in urls if url]
        if not urls:
            return ""
        images = "".join(f'<img src="{_esc(url)}" alt="" loading="lazy" decoding="async">' for url in urls)
        return f'<div class="grelha galeria">{images}</div>'

    if block_type == "destaques":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        if not items:
            return ""
        tiles = []
        for item in items:
            href = str(item.get("href") or "").strip()
            # Ícone opcional: sem imagem o cartão fica como sempre foi, para o
            # conteúdo escrito antes dos ícones continuar a servir.
            icone_url = _media_url(item.get("icon_id"))
            icone = (
                f'<img class="tile-icon" src="{_esc(icone_url)}" alt="" width="44" height="44" loading="lazy">'
                if icone_url
                else ""
            )
            corpo = f'{icone}<h3>{_esc(item.get("title"))}</h3><p>{_esc(item.get("text"))}</p>'
            if href:
                tiles.append(f'<a class="tile link" href="{_esc(href)}">{corpo}</a>')
            else:
                tiles.append(f'<div class="tile">{corpo}</div>')
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        # A grelha sabe quantos cartões tem: três, quatro ou seis alinham sem
        # deixar uma linha órfã de um cartão (era o que acontecia com o
        # `auto-fit` genérico).
        colunas = f" grelha--n{len(items)}" if len(items) in (3, 4, 6) else ""
        return f'<div class="section">{title}<div class="grelha{colunas}">{"".join(tiles)}</div></div>'

    if block_type == "numeros":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        if not items:
            return ""
        cartoes = "".join(
            f'<div class="kpi"><span>{_esc(item.get("label"))}</span><strong>{_esc(item.get("value"))}</strong>'
            + (f'<small>{_esc(item.get("note"))}</small>' if item.get("note") else "")
            + "</div>"
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="kpis">{cartoes}</div></div>'

    if block_type == "cta":
        return (
            f'<div class="section cta"><div><h2>{_esc(data.get("title"))}</h2>'
            f'<p>{_esc(data.get("text") or "")}</p></div>'
            f'<div class="actions">{_cta_botoes(data)}</div></div>'
        )

    if block_type == "faq":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        details = "".join(
            f'<details><summary>{_esc(item.get("question") or item.get("title"))}</summary>'
            f'<div>{_md(str(item.get("answer") or item.get("text") or ""))}</div></details>'
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section faq">{title}{details}</div>'

    if block_type == "passos":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        steps = "".join(
            f'<div class="step"><h3>{_esc(item.get("title"))}</h3>{_md(str(item.get("text") or ""))}</div>'
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="steps">{steps}</div></div>'

    if block_type == "tabela":
        head = [str(cell) for cell in (data.get("head") or [])]
        rows = [row for row in (data.get("rows") or []) if isinstance(row, list)]
        if not head and not rows:
            return ""
        thead = f"<tr>{''.join(f'<th>{_esc(cell)}</th>' for cell in head)}</tr>" if head else ""
        tbody = "".join(f"<tr>{''.join(f'<td>{_esc(cell)}</td>' for cell in row)}</tr>" for row in rows)
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        classe = "tabela-rolavel larga" if len(head) >= 4 else "tabela-rolavel"
        return (
            f'<div class="section prose">{title}<div class="{classe}">'
            f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table></div></div>"
        )

    if block_type == "grafico":
        return _grafico_barras(data)

    if block_type == "citacao":
        author = f"<footer>— {_esc(data.get('author'))}</footer>" if data.get("author") else ""
        return f'<blockquote>{_esc(data.get("quote") or "")}{author}</blockquote>'
    if block_type == "aviso":
        tone = str(data.get("tone") or "")
        tone = f" {tone}" if tone in ("amber", "red", "green") else ""
        return f'<div class="aviso{tone}">{_md(str(data.get("text") or ""))}</div>'

    if block_type == "codigo":
        language = _esc(data.get("language") or "")
        code = html.escape(str(data.get("code") or ""))
        return f'<pre><code class="language-{language}">{code}</code></pre>'

    if block_type == "contactos":
        parts = []
        if data.get("email"):
            parts.append(f'<div><strong>Email</strong><br><a href="mailto:{_esc(data["email"])}">{_esc(data["email"])}</a></div>')
        if data.get("phone"):
            parts.append(f'<div><strong>Telefone</strong><br>{_esc(data["phone"])}</div>')
        if data.get("address"):
            parts.append(f'<div><strong>Morada</strong><br>{_esc(data["address"])}</div>')
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="contactos">{"".join(parts)}</div></div>'

    if block_type == "formulario":
        return formulario_contacto(data)

    if block_type == "conteudo":
        return f'<div class="section">{_render_content_block(str(data.get("content_id") or ""))}</div>'

    if block_type == "blog":
        return _render_blog_block(data, preview=preview)

    if block_type == "relatorios":
        return _render_library_block(data, preview=preview)

    if block_type == "divisor":
        return '<hr class="hr">'

    return ""


def _acrescentar_classes(html_text: str, classes: str) -> str:
    """Acrescenta classes à raiz do bloco, sem tocar no resto da marcação."""
    match = re.match(r"<([A-Za-z][\w:-]*)([^>]*)>", html_text)
    if not match:
        return html_text
    tag, attrs = match.group(1), match.group(2)
    class_match = re.search(r'class="([^"]*)"', attrs)
    if class_match:
        attrs = (
            f'{attrs[: class_match.start()]}class="{class_match.group(1)} {classes}"'
            f"{attrs[class_match.end() :]}"
        )
    else:
        attrs = f'{attrs} class="{classes}"'
    return f"<{tag}{attrs}>" + html_text[match.end() :]


def _acrescentar_atributo(html_text: str, nome: str, valor: str) -> str:
    """Acrescenta um atributo à raiz do bloco, sem tocar no resto da marcação."""
    match = re.match(r"<([A-Za-z][\w:-]*)([^>]*)>", html_text)
    if not match:
        return html_text
    tag, attrs = match.group(1), match.group(2)
    if re.search(rf"\b{re.escape(nome)}=", attrs):
        return html_text
    return f'<{tag}{attrs} {nome}="{_esc(valor)}">' + html_text[match.end() :]


_APARENCIA_FUNDOS = frozenset({"sem", "cartao", "destaque", "suave"})
_APARENCIA_ESPACAMENTOS = frozenset({"normal", "compacto", "amplo"})


def _aplicar_aparencia(block: Dict[str, Any], html_text: str) -> str:
    """Veste um bloco com o fundo, a cor, o alinhamento e o espaçamento do CMS.

    A configuração vive em `data.appearance` para não colidir com campos
    próprios dos blocos (`tone` do «aviso», `align` do hero, etc.).
    """
    if not html_text or block.get("type") == "hero":
        return html_text
    data = block.get("data") or {}
    aparencia = data.get("appearance")
    if not isinstance(aparencia, dict):
        return html_text
    fundo = str(aparencia.get("surface") or "sem").strip().lower()
    tom = str(aparencia.get("tone") or "acento").strip().lower()
    alinhamento = str(aparencia.get("align") or "esquerda").strip().lower()
    espacamento = str(aparencia.get("density") or "normal").strip().lower()
    if fundo not in _APARENCIA_FUNDOS:
        fundo = "sem"
    if tom not in store.HERO_TONE_IDS:
        tom = "acento"
    if espacamento not in _APARENCIA_ESPACAMENTOS:
        espacamento = "normal"
    classes = ["bloco"]
    if fundo != "sem":
        classes.append(f"bloco--{fundo}")
    if tom != "acento":
        classes.append(f"bloco--tom-{tom}")
    if alinhamento == "centro":
        classes.append("bloco--centro")
    if espacamento != "normal":
        classes.append(f"bloco--{espacamento}")
    if len(classes) == 1:
        return html_text
    return _acrescentar_classes(html_text, " ".join(classes))


def blocks_to_html(blocks: Iterable[Dict[str, Any]], *, preview: bool = False) -> str:
    parts = []
    for block in blocks or []:
        html_text = _render_block(block, preview=preview)
        if html_text:
            # A raiz de cada bloco leva o tipo (`data-bloco="hero"`, …): o CSS
            # consegue assim tratar a abertura, os números ou a galeria sem
            # depender da ordem nem de uma classe genérica partilhada. Vai como
            # atributo (e não como classe) para não alterar o contrato das
            # classes que o CMS e os testes já conhecem.
            tipo = re.sub(r"[^\w-]", "", str(block.get("type") or "texto"))
            html_text = _acrescentar_atributo(html_text, "data-bloco", tipo)
            parts.append(_aplicar_aparencia(block, html_text))
    return "".join(parts)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
def _menu_theme_classes(menu: Dict[str, Any]) -> str:
    """Classes CSS que combinam o tema e a variação do menu."""
    theme = str(menu.get("menu_theme") or "pastilhas").strip()
    template = str(menu.get("menu_template") or "padrao").strip()
    valid_themes = {"pastilhas", "linha", "central"}
    if theme not in valid_themes:
        theme = "pastilhas"
    classes = [f"tema-{theme}"]
    if template != "padrao":
        classes.append(f"template-{template}")
    return " ".join(classes)


#: Ícones do menu: geometria do Lucide (https://lucide.dev, licença ISC), copiada
#: de `chat-ui/node_modules/lucide-react@1.39.0/dist/esm/icons/*.mjs` — os dois
#: lados da plataforma ficam com os mesmos desenhos. Poucos: um desenho diferente
#: por entrada cansa mais do que ajuda a ler. Aqui só o conteúdo; a moldura (que é
#: igual em todos) fica em `_svg`.
_ICONES: Dict[str, str] = {
    "inicio": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "seccao": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "documento": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "estudo": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "base": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    "blog": '<path d="M15 18h-5"/><path d="M18 14h-8"/><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9a2 2 0 0 1 2-2h2"/><rect width="8" height="4" x="10" y="6" rx="1"/>',
    "contacto": '<path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="4" width="20" height="16" rx="2"/>',
    "informacao": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "conta": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "registar": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/>',
    "loja": '<path d="M16 10a4 4 0 0 1-8 0"/><path d="M3.103 6.034h17.794"/><path d="M3.4 5.467a2 2 0 0 0-.4 1.2V20a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6.667a2 2 0 0 0-.4-1.2l-2-2.667A2 2 0 0 0 17 2H7a2 2 0 0 0-1.6.8z"/>',
    "pesquisa": '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
    "seta": '<path d="m6 9 6 6 6-6"/>',
}

#: Ícone por destino conhecido: vale a primeira palavra que apareça no caminho ou
#: no rótulo do item; o que não se conhece fica com o ícone genérico. É um mapa
#: (e não um campo do CMS) para os ícones aparecerem sem ninguém os configurar.
_ICONE_POR_PALAVRA: Tuple[Tuple[str, str], ...] = (
    ("inicio", "inicio"),
    ("home", "inicio"),
    ("solucoes", "seccao"),
    ("servicos", "seccao"),
    ("base-de-dados", "base"),
    ("fonte", "base"),
    ("dados", "base"),
    ("estudo", "estudo"),
    ("benchmark", "estudo"),
    ("relatorio", "documento"),
    ("documento", "documento"),
    ("dossie", "documento"),
    ("blog", "blog"),
    ("artigo", "blog"),
    ("noticia", "blog"),
    ("contacto", "contacto"),
    ("sobre", "informacao"),
    ("ajuda", "informacao"),
    ("loja", "loja"),
    ("carrinho", "loja"),
    ("regist", "registar"),
    ("criar-conta", "registar"),
    ("entrar", "conta"),
    ("login", "conta"),
    ("conta", "conta"),
    ("pesquisa", "pesquisa"),
    ("busca", "pesquisa"),
)


def _svg(desenho: str, tamanho: int = 18, classe: Optional[str] = "menu-icone") -> str:
    """SVG com a moldura do Lucide: quadro de 24, traço de 2, `currentColor`."""
    atributo = f' class="{classe}"' if classe else ""
    return (
        f'<svg{atributo} viewBox="0 0 24 24" width="{tamanho}" height="{tamanho}" '
        'aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{desenho}</svg>'
    )


def _icone(nome: str) -> str:
    """SVG de um ícone do menu (vazio quando o nome não existe)."""
    desenho = _ICONES.get(nome)
    if not desenho:
        return ""
    return _svg(desenho)


def _icone_do_item(item: Dict[str, Any]) -> str:
    """Ícone do item pelo destino que ele abre (caminho ou rótulo)."""
    alvo = _chave_nome(f"{item.get('href') or ''} {item.get('label') or ''}")
    for palavra, nome in _ICONE_POR_PALAVRA:
        if palavra in alvo:
            return _icone(nome)
    return _icone("seccao")


def _botao_do_submenu(label: str) -> str:
    """Botão que abre e fecha o submenu no telemóvel (no ecrã grande não aparece).

    O rótulo do item continua a ser o link para a sua página: quem quer navegar
    toca no rótulo, quem quer ver o que está lá dentro toca na seta.
    """
    nome = " ".join(str(label or "").split())
    return (
        '<button type="button" class="menu-abre" aria-expanded="false" '
        f'aria-label="Abrir {_esc(nome)}">'
        f"{_svg(_ICONES['seta'], 16, classe=None)}</button>"
    )


def _form_de_pesquisa(termo: str = "", *, classe: str = "pesquisa-form") -> str:
    """Campo de pesquisa do site (o menu do telemóvel e a página de resultados).

    A lupa não leva a classe dos ícones do menu: essa é escondida no ecrã grande,
    e aqui ela aparece no telemóvel e no computador.
    """
    return (
        f'<form class="{_esc(classe)}" action="/site/pesquisa" method="get" role="search">'
        f'<span class="pesquisa-icone" aria-hidden="true">{_svg(_ICONES["pesquisa"], classe=None)}</span>'
        f'<input type="search" name="q" value="{_esc(termo)}" placeholder="Pesquisar no site" '
        'aria-label="Pesquisar no site" autocomplete="off" enterkeyhint="search">'
        "<button type=\"submit\">Pesquisar</button></form>"
    )


def _menu_conta() -> str:
    """Entrar e criar conta no menu do telemóvel (no ecrã grande há `Entrar` na fila)."""
    return (
        '<div class="menu-conta">'
        f'<a class="btn ghost" href="/login">{_icone("conta")}Entrar</a>'
        f'<a class="btn" href="/register">{_icone("registar")}Criar conta</a>'
        "</div>"
    )


#: Destinos que o bloco de conta do telemóvel (`_menu_conta`) já dá. No painel, as
#: entradas do CMS que levam lá não se repetem; no ecrã grande a fila fica como o
#: editor a deixou (quem manda é o CMS).
_DESTINOS_DA_CONTA: Set[str] = {"/login", "/register"}


def _igual_ao_bloco_de_conta(item: Dict[str, Any]) -> bool:
    """O item do menu leva a um destino que o bloco de conta já mostra?"""
    href = str(item.get("href") or "").strip().lower().rstrip("/")
    return href in _DESTINOS_DA_CONTA


def _menu_link(
    item: Dict[str, Any], current_path: str, *, com_icone: bool = False, classe: str = ""
) -> str:
    """Link de um item do menu (no topo ou dentro de um submenu)."""
    href = str(item.get("href") or "")
    active = ' aria-current="page"' if href and href in (current_path, f"/site{current_path}") else ""
    target = ' target="_blank" rel="noopener"' if item.get("new_tab") else ""
    icone = _icone_do_item(item) if com_icone else ""
    atributo = f' class="{classe}"' if classe else ""
    return f'<a{atributo} href="{_esc(href)}"{active}{target}>{icone}{_esc(item.get("label"))}</a>'


def _menu_gatilho(item: Dict[str, Any], current_path: str, *, com_icone: bool = False) -> str:
    """O que abre o submenu: a página do item ou, sem página, o próprio rótulo.

    Quem abre o submenu é a seta que vem a seguir (`_botao_do_submenu`); o rótulo
    continua a ser o link. O rótulo sem destino é um `<span>` que não navega.
    """
    href = str(item.get("href") or "")
    label = _esc(item.get("label"))
    icone = _icone_do_item(item) if com_icone else ""
    if href:
        active = ' aria-current="page"' if href in (current_path, f"/site{current_path}") else ""
        target = ' target="_blank" rel="noopener"' if item.get("new_tab") else ""
        return f'<a class="menu-pai" href="{_esc(href)}"{active}{target}>{icone}{label}</a>'
    return f'<span class="menu-pai" tabindex="0">{icone}{label}</span>'


def _submenu(items: List[Dict[str, Any]], current_path: str, depth: int) -> str:
    """Lista de um submenu, com os submenus aninhados que houver."""
    partes: List[str] = []
    for item in items:
        filhos = item.get("children") or []
        if filhos:
            partes.append(
                f'<li class="tem-submenu nivel-{depth}">'
                f'{_menu_gatilho(item, current_path)}{_botao_do_submenu(str(item.get("label") or ""))}'
                f'{_submenu(filhos, current_path, depth + 1)}'
                "</li>"
            )
        else:
            partes.append(f"<li>{_menu_link(item, current_path)}</li>")
    return f'<ul class="submenu nivel-{depth}">{"".join(partes)}</ul>'


def _itens_principais(items: List[Dict[str, Any]], current_path: str) -> str:
    """Itens de topo: links soltos e entradas que abrem um submenu."""
    partes: List[str] = []
    for item in items:
        filhos = item.get("children") or []
        # `menu-igual-conta` fica no HTML (o ecrã grande mostra a entrada) e é o
        # CSS do painel do telemóvel que a esconde, para não repetir os botões.
        # Só nas entradas de topo: dentro de um submenu a entrada não se repete
        # ao lado dos botões e escondê-la podia deixar o grupo vazio.
        igual = " menu-igual-conta" if _igual_ao_bloco_de_conta(item) else ""
        if filhos:
            partes.append(
                f'<div class="menu-item tem-submenu nivel-0{igual}">'
                f'{_menu_gatilho(item, current_path, com_icone=True)}'
                f'{_botao_do_submenu(str(item.get("label") or ""))}'
                f'{_submenu(filhos, current_path, 1)}'
                "</div>"
            )
        else:
            partes.append(_menu_link(item, current_path, com_icone=True, classe=igual.strip()))
    return "".join(partes)


def _header(settings: Dict[str, Any], *, current_path: str, preview: bool = False) -> str:
    menu = store.menu_for("header")
    links = _itens_principais(menu.get("items") or [], current_path)
    tagline = f'<small>{_esc(settings.get("tagline"))}</small>' if settings.get("tagline") else ""
    # Com logótipo na biblioteca, o cabeçalho mostra a imagem (que já traz o
    # nome); sem ele, fica o nome em texto, como antes.
    logo = _media_url(settings.get("logo_id"))
    if logo:
        brand = (
            f'<img class="brand-mark" src="{_esc(logo)}" alt="{_esc(settings.get("site_name"))}" width="320" height="72">'
            + tagline
        )
    else:
        brand = f'{_esc(settings.get("site_name"))}{tagline}'
    banner = '<div class="draft-banner">Pré-visualização — este conteúdo ainda não está publicado</div>' if preview else ""
    theme_classes = _menu_theme_classes(menu)
    return (
        banner
        + f'<header class="site-header {theme_classes}"><div class="wrap">'
        + f'<a class="brand" href="/site">{brand}</a>'
        # Menu de telefone sem JavaScript: a caixa escondida guarda o estado e o
        # `:checked` mostra a lista. No ecrã grande o botão desaparece e a lista
        # volta a ser uma fila de pastilhas (ver o `@media (min-width: 800px)`).
        + '<input type="checkbox" id="menu-estado" class="menu-estado" aria-label="Abrir o menu">'
        + '<label class="menu-botao" for="menu-estado"><span class="menu-barras" aria-hidden="true"></span>Menu</label>'
        # O painel do telemóvel abre com a pesquisa e a conta à frente da lista
        # (é o que se procura primeiro), e as entradas do CMS que levam aos mesmos
        # sítios saem daqui (`menu-igual-conta`). No ecrã grande as duas
        # desaparecem e a lista volta a ser uma fila de pastilhas.
        + (
            '<nav class="main" aria-label="Navegação principal">'
            + _form_de_pesquisa(classe="menu-pesquisa")
            + _menu_conta()
            + links
            + "</nav>"
        )
        + "</div></header>"
    )


def _social_links(settings: Dict[str, Any]) -> str:
    labels = {"email": "Email", "linkedin": "LinkedIn", "x": "X", "github": "GitHub"}
    parts = []
    for key, label in labels.items():
        value = str((settings.get("social") or {}).get(key) or "").strip()
        if not value:
            continue
        href = f"mailto:{value}" if key == "email" else value
        parts.append(f'<a href="{_esc(href)}">{label}</a>')
    return "".join(parts)


def _footer_links(items: List[Dict[str, Any]]) -> str:
    """Links do rodapé: os submenus aparecem lado a lado, sem painéis."""
    partes: List[str] = []
    for item in items:
        href = str(item.get("href") or "")
        if href:
            partes.append(f'<a href="{_esc(href)}">{_esc(item.get("label"))}</a>')
        partes.append(_footer_links(item.get("children") or []))
    return "".join(partes)


def _footer(settings: Dict[str, Any]) -> str:
    menu = store.menu_for("footer")
    links = _footer_links(menu.get("items") or [])
    footer_text = _esc(settings.get("footer_text") or "")
    site_name = _esc(settings.get("site_name") or "")
    theme_classes = _menu_theme_classes(menu)
    return (
        f'<footer class="site-footer {theme_classes}"><div class="wrap">'
        f'<div><strong>{site_name}</strong><br>{footer_text}</div>'
        f'<nav>{links}{_social_links(settings)}</nav>'
        "</div></footer>"
    )


def _breadcrumb(dados: Optional[List[Dict[str, str]]]) -> str:
    """Trilha de navegação («Início › Secção › Página»).

    O último passo é sempre o texto da página (sem link); os anteriores levam a
    `href` quando existe. Uma secção sem índice próprio (as pesquisas guardadas,
    por exemplo) fica sem link — é o que o `href` em falta diz.
    """
    if not dados or len(dados) < 2:
        return ""
    passos: List[str] = []
    for posicao, passo in enumerate(dados, start=1):
        etiqueta = _esc(str(passo.get("label") or ""))
        href = str(passo.get("href") or "").strip()
        if href and posicao < len(dados):
            passos.append(f'<li><a href="{_esc(href)}">{etiqueta}</a></li>')
        else:
            passos.append(f'<li><span aria-current="page">{etiqueta}</span></li>')
    return f'<nav class="breadcrumb" aria-label="Caminho"><ol>{"".join(passos)}</ol></nav>'


def _breadcrumb_json_ld(dados: List[Dict[str, str]], base_url: str) -> Dict[str, Any]:
    """A mesma trilha em `BreadcrumbList`, para os motores de busca."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": posicao,
                "name": str(passo.get("label") or ""),
                **({"item": _absolute(str(passo["href"]), base_url)} if passo.get("href") else {}),
            }
            for posicao, passo in enumerate(dados, start=1)
        ],
    }


# --------------------------------------------------------------------------
# Sitemap, RSS e robots
# --------------------------------------------------------------------------
#: Origem canónica, usada quando as definições do site não têm `base_url`. Um
#: `<loc>` relativo é inválido num sitemap (o motor de busca rejeita o ficheiro
#: inteiro), e sem origem não se escreve a linha `Sitemap:` no `robots.txt`.
DEFAULT_BASE_URL = "https://sabemos.studio"


# --------------------------------------------------------------------------
# PWA (site instalável)
# --------------------------------------------------------------------------
#: Ícones do PWA, gerados por `scripts/generate_site_pwa_icons.py` e servidos em
#: `/site/pwa/<ficheiro>`. Um caminho fixo é o que permite ao manifesto
#: referenciá-los: os ids da biblioteca de media são aleatórios em cada
#: instalação.
PWA_ICONS: Dict[str, Dict[str, str]] = {
    "pwa-icone-192.png": {"sizes": "192x192", "purpose": "any"},
    "pwa-icone-512.png": {"sizes": "512x512", "purpose": "any"},
    "pwa-icone-maskable-512.png": {"sizes": "512x512", "purpose": "maskable"},
}

#: Ícone tocado com o dedo em ecrãs iOS (o manifest não precisa dele).
PWA_IOS_ICON = "pwa-icone-180.png"
PWA_ICON_PATH = "/site/pwa/"
MANIFEST_PATH = "/site/manifest.webmanifest"
SW_PATH = "/site/sw.js"
OFFLINE_PATH = "/site/offline"

#: Folha de estilo do site, compilada pelo Tailwind (`site-css/`). Igual em todas
#: as páginas, por isso saiu do HTML: é descarregada uma vez e reutilizada.
CSS_PATH = "/site/site.css"

#: Nome das caches do site e versão do service worker. O prefixo é o que
#: permite apagar só as caches do site na ativação — o PWA da plataforma, que
#: vive no mesmo domínio, não é tocado. Ao mudar a estratégia, subir a versão.
PWA_CACHE_PREFIX = "sabemos-site-"
# v2: nova folha do site (página inicial). Sem o salto de versão, quem já tinha
# a cache antiga via o desenho anterior na primeira visita depois da publicação.
PWA_SW_VERSION = "v2"


def _pwa_cores(settings: Dict[str, Any]) -> Dict[str, str]:
    """Cor da barra de estado (destaque) e fundo do ecrã de arranque."""
    theme_name = str(settings.get("theme") or "claro")
    palette = _THEMES.get(theme_name) or _THEMES["claro"]
    return {
        "accent": str(settings.get("accent") or "#0ea5a4"),
        "background": palette["bg"],
    }


def _pwa_atalhos() -> List[Dict[str, str]]:
    """Atalhos do manifest: os primeiros itens do menu principal do cabeçalho."""
    atalhos: List[Dict[str, str]] = []
    for item in store.menu_for("header").get("items") or []:
        href = str(item.get("href") or "")
        label = str(item.get("label") or "")
        if not label or not href.startswith("/site"):
            continue
        atalhos.append({"name": label, "url": href})
        if len(atalhos) == 4:
            break
    return atalhos


def render_manifest(settings: Optional[Dict[str, Any]] = None) -> str:
    """Manifesto do PWA: é o que faz o browser oferecer "instalar"."""
    settings = settings or store.get_settings()
    cores = _pwa_cores(settings)
    nome = str(settings.get("site_name") or "Site")
    # O `short_name` fica debaixo do ícone no ecrã inicial: sendo o nome
    # comprido, só a primeira palavra ("Sabemos Studio" → "Sabemos").
    curto = nome if len(nome) <= 12 else nome.split()[0]
    manifest: Dict[str, Any] = {
        "id": "/site/",
        "name": nome,
        "short_name": curto,
        "description": str(settings.get("description") or settings.get("tagline") or ""),
        "lang": str(settings.get("language") or "pt-PT"),
        "dir": "ltr",
        "start_url": "/site/",
        "scope": "/site/",
        "display": "standalone",
        "background_color": cores["background"],
        "theme_color": cores["accent"],
        "icons": [
            {"src": f"{PWA_ICON_PATH}{ficheiro}", "type": "image/png", **dados}
            for ficheiro, dados in PWA_ICONS.items()
        ],
        "categories": ["finance", "news", "education"],
    }
    atalhos = _pwa_atalhos()
    if atalhos:
        manifest["shortcuts"] = atalhos
    return json.dumps(manifest, ensure_ascii=False, indent=2)


#: Service worker do site. Escrito como modelo (e não como f-string) porque o
#: corpo é JavaScript, cheio de chaves.
_SW_TEMPLATE = """/**
 * Service worker do site público (Sabemos Studio).
 *
 * Estratégia:
 * - Navegações: rede primeiro, porque as páginas são geradas pelo CMS e mudam
 *   com frequência; sem ligação, abre a última cópia guardada dessa página e,
 *   em último recurso, a página offline.
 * - Imagens do CMS e ícones do site: cache com revalidação em segundo plano —
 *   responde já com a cópia guardada e atualiza-a para a visita seguinte.
 * - A área de gestão (`/cms/`) e a API (`/api/`) nunca passam pelo cache: o
 *   painel e os dados não podem ficar presos numa versão antiga.
 * - Tudo o resto segue direto para a rede.
 *
 * Ao alterar este ficheiro, subir PWA_SW_VERSION em `api/cms_render.py`.
 */
const VERSAO = "__VERSAO__";
const CACHE_PAGINAS = "__CACHE_PAGINAS__";
const CACHE_RECURSOS = "__CACHE_RECURSOS__";
const OFFLINE = "__OFFLINE__";

const PAGINAS = ["/site/", "__OFFLINE__"];
const RECURSOS = [__RECURSOS__];

/** Pedidos que nunca devem vir do cache. */
const BYPASS = ["/api/", "/cms/", "/lp/", "/landing"];

/** Exceções ao BYPASS: conteúdo público do site, seguro de guardar. */
const GUARDAVEIS = ["/cms/media/", "/site/pwa/", "__CSS__"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const paginas = await caches.open(CACHE_PAGINAS);
      const recursos = await caches.open(CACHE_RECURSOS);
      // Um recurso em falta não pode impedir a instalação: guarda um a um.
      // O `cache: "reload"` salta o cache HTTP (as páginas só valem 15 s lá).
      await Promise.all(
        PAGINAS.map((url) => paginas.add(new Request(url, { cache: "reload" })).catch(() => undefined)),
      );
      await Promise.all(
        RECURSOS.map((url) => recursos.add(new Request(url, { cache: "reload" })).catch(() => undefined)),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const chaves = await caches.keys();
      await Promise.all(
        chaves
          .filter(
            (chave) =>
              chave.startsWith("__PREFIXO__") && chave !== CACHE_PAGINAS && chave !== CACHE_RECURSOS,
          )
          .map((chave) => caches.delete(chave)),
      );
      // Sem isto, a primeira visita só ficaria servida pelo worker na seguinte.
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

function ignorar(pathname) {
  if (GUARDAVEIS.some((prefixo) => pathname.startsWith(prefixo))) return false;
  if (pathname === "__SW__") return true;
  return BYPASS.some((prefixo) => pathname.startsWith(prefixo));
}

/** Navegação: rede primeiro, com a cópia guardada como reserva. */
async function pagina(request) {
  const cache = await caches.open(CACHE_PAGINAS);
  try {
    const resposta = await fetch(request);
    if (resposta && resposta.ok) await cache.put(request, resposta.clone());
    return resposta;
  } catch {
    const guardada = await cache.match(request);
    if (guardada) return guardada;
    return (
      (await cache.match(OFFLINE)) ||
      new Response(
        "<!doctype html><meta charset=\\"utf-8\\"><title>Sem ligação</title><p>Sem ligação.</p>",
        { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
      )
    );
  }
}

/** Imagem ou ícone: responde do cache e revalida em segundo plano. */
async function revalidar(request) {
  const cache = await caches.open(CACHE_RECURSOS);
  const guardada = await cache.match(request);
  const rede = fetch(request)
    .then((resposta) => {
      if (resposta && resposta.ok) cache.put(request, resposta.clone());
      return resposta;
    })
    .catch(() => undefined);
  return guardada || (await rede) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Outros domínios (o email, as redes sociais) não passam por aqui.
  if (url.origin !== self.location.origin) return;
  if (ignorar(url.pathname)) return;

  if (request.mode === "navigate") {
    event.respondWith(pagina(request));
    return;
  }
  if (GUARDAVEIS.some((prefixo) => url.pathname.startsWith(prefixo))) {
    event.respondWith(revalidar(request));
  }
});
"""


def render_service_worker(settings: Optional[Dict[str, Any]] = None) -> str:
    """Service worker do site: cache das páginas visitadas e leitura sem rede."""
    settings = settings or store.get_settings()
    recursos = [MANIFEST_PATH, CSS_PATH] + [f"{PWA_ICON_PATH}{ficheiro}" for ficheiro in PWA_ICONS]
    valores = {
        "__VERSAO__": PWA_SW_VERSION,
        "__CACHE_PAGINAS__": f"{PWA_CACHE_PREFIX}paginas-{PWA_SW_VERSION}",
        "__CACHE_RECURSOS__": f"{PWA_CACHE_PREFIX}recursos-{PWA_SW_VERSION}",
        "__PREFIXO__": PWA_CACHE_PREFIX,
        "__OFFLINE__": OFFLINE_PATH,
        "__SW__": SW_PATH,
        "__CSS__": CSS_PATH,
        "__RECURSOS__": ", ".join(f'"{caminho}"' for caminho in recursos),
    }
    js = _SW_TEMPLATE
    for chave, valor in valores.items():
        js = js.replace(chave, valor)
    return js


def render_offline(*, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página de recurso, mostrada pelo service worker quando não há ligação.

    A ilustração vai embutida no HTML: sem rede, um `src` externo não aparecia.
    """
    settings = settings or store.get_settings()
    body = _pagina_de_sistema(
        etiqueta="Sem ligação · modo offline",
        titulo="Sem rede — o que já visitou continua aqui",
        lead="Não foi possível chegar ao servidor. As páginas que já abriu ficaram guardadas "
        "neste dispositivo e continuam a abrir.",
        nota="Um arquivo a sério também não se queixa quando a luz falha: mostra o que tem. "
        "Quando a rede voltar, os números atualizam-se sozinhos — não é preciso fazer nada.",
        ilustracao=_ILUSTRACOES_DE_SISTEMA["sem-ligacao"],
        legenda="Ligação interrompida entre o dispositivo e o servidor: o que está em cache "
        "continua disponível.",
        acoes=(
            '<a class="btn" href="/site/">Voltar ao início</a>'
            '<a class="btn ghost" href="/site/relatorios-gratuitos">Ver relatórios</a>'
        ),
    )
    return _layout(
        title="Sem ligação",
        description="Sem ligação à rede.",
        body=body,
        current_path=OFFLINE_PATH,
        settings=settings,
        canonical=OFFLINE_PATH,
        breadcrumb=[{"label": "Início", "href": "/site"}, {"label": "Sem ligação"}],
        noindex=True,
    )


def _layout(
    *,
    title: str,
    description: str,
    body: str,
    current_path: str,
    settings: Dict[str, Any],
    canonical: str = "",
    og_type: str = "website",
    og_image: str = "",
    keywords: Optional[List[str]] = None,
    json_ld: Optional[Dict[str, Any]] = None,
    preview: bool = False,
    noindex: bool = False,
    extra_css: str = "",
    breadcrumb: Optional[List[Dict[str, str]]] = None,
    wrap_class: str = "",
) -> str:
    base_url = str(settings.get("base_url") or "")
    site_name = _esc(settings.get("site_name") or "Site")
    full_title = _titulo_do_head(title, site_name)
    canonical_url = _absolute(canonical or current_path, base_url)
    robots = "noindex, nofollow" if (noindex or preview) else str(settings.get("robots") or "index, follow")
    meta = [
        f'<meta name="description" content="{_esc(description)}">',
        f'<meta name="robots" content="{_esc(robots)}">',
        f'<link rel="canonical" href="{_esc(canonical_url or "/")}">',
        f'<link rel="alternate" type="application/rss+xml" title="{site_name} — RSS" href="/site/rss.xml">',
        f'<meta property="og:type" content="{_esc(og_type)}">',
        f'<meta property="og:site_name" content="{site_name}">',
        f'<meta property="og:title" content="{_esc(full_title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        f'<meta property="og:url" content="{_esc(canonical_url or "/")}">',
        f'<meta property="og:locale" content="{_esc(str(settings.get("language") or "pt-PT").replace("-", "_"))}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_esc(full_title)}">',
        f'<meta name="twitter:description" content="{_esc(description)}">',
    ]
    if og_image:
        # Open Graph e Twitter só aceitam URLs absolutos: um caminho relativo
        # (`/cms/media/...`) é ignorado e a partilha fica sem imagem.
        imagem = _absolute(og_image, base_url)
        meta.append(f'<meta property="og:image" content="{_esc(imagem)}">')
        meta.append(f'<meta name="twitter:image" content="{_esc(imagem)}">')
    if keywords:
        meta.append(f'<meta name="keywords" content="{_esc(", ".join(keywords))}">')
    analytics = str(settings.get("analytics_id") or "").strip()
    if analytics and not preview:
        meta.append(
            "<script async src=\"https://www.googletagmanager.com/gtag/js?id="
            + _esc(analytics)
            + '"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag("js",new Date());gtag("config","'
            + _esc(analytics)
            + '");</script>'
        )
    # Apoio ao cliente nas páginas públicas. A pré-visualização é do editor, não
    # de quem visita o site: aí o widget não entra.
    if not preview:
        meta.append(tawk.TAWK_SNIPPET)
    if json_ld:
        meta.append(f'<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>')
    if breadcrumb and len(breadcrumb) >= 2:
        meta.append(
            f'<script type="application/ld+json">'
            f'{json.dumps(_breadcrumb_json_ld(breadcrumb, base_url), ensure_ascii=False)}</script>'
        )
    favicon = _media_url(settings.get("favicon_id"))
    if favicon:
        meta.append(f'<link rel="icon" href="{_esc(favicon)}">')
    cores = _pwa_cores(settings)
    meta.extend(
        [
            f'<link rel="manifest" href="{MANIFEST_PATH}">',
            # Cor da barra do sistema: a do destaque, igual à do logótipo.
            f'<meta name="theme-color" content="{_esc(cores["accent"])}">',
            f'<link rel="apple-touch-icon" href="{_esc(PWA_ICON_PATH + PWA_IOS_ICON)}">',
            # Instalado no ecrã inicial (iOS e Android), abre sem a barra do browser.
            '<meta name="mobile-web-app-capable" content="yes">',
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            f'<meta name="apple-mobile-web-app-title" content="{site_name}">',
            '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
        ]
    )
    return (
        "<!doctype html><html lang=\""
        + _esc(str(settings.get("language") or "pt-PT"))
        + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        + f"<title>{_esc(full_title)}</title>"
        + "".join(meta)
        # O CSS do site é um ficheiro à parte (compilado pelo Tailwind, ver
        # `site-css/`): é o mesmo em todas as páginas e não se repete no HTML. Em
        # linha ficam só as variáveis do tema, que vêm das definições do CMS, e o
        # CSS próprio da página (`extra_css`), que não passa pelo compilador.
        + f'<link rel="stylesheet" href="{CSS_PATH}">'
        + f"<style>{_css(settings)}{extra_css}</style></head><body>"
        # Ligação de salto: quem navega por teclado chega ao conteúdo sem
        # percorrer o menu inteiro em todas as páginas.
        + '<a class="skip-link" href="#conteudo">Saltar para o conteúdo</a>'
        + _header(settings, current_path=current_path, preview=preview)
        + f"<main id=\"conteudo\"><div class=\"{(f'wrap {wrap_class}').strip()}\">"
        + f"{_breadcrumb(breadcrumb)}{body}</div></main>"
        + _footer(settings)
        # Registo do service worker (dá o funcionamento sem ligação e o cache
        # das imagens). Falha em silêncio: sem HTTPS ou num browser antigo, o
        # site continua a funcionar normalmente.
        + (
            ""
            if preview
            else "<script>if(\"serviceWorker\" in navigator){window.addEventListener(\"load\","
            "function(){navigator.serviceWorker.register(\"" + SW_PATH + "\")"
            ".catch(function(){});});}</script>"
        )
        # Media em falta no disco não pode deixar uma caixa vazia (ou o ícone de
        # imagem quebrada) no meio da página: a imagem sai e, quando não sobra
        # nenhuma na galeria ou na figura, sai também o espaço dela.
        + '<script>(function(){function falhou(i){i.style.display="none";i.setAttribute("data-falhou","");'
        'var f=i.closest("figure");if(f&&!f.querySelector("img:not([data-falhou])"))f.style.display="none";'
        'var g=i.closest(".galeria");if(g&&!g.querySelector("img:not([data-falhou])"))g.style.display="none";'
        'var p=i.closest(".post-card");if(p)p.classList.add("sem-imagem");}'
        'document.querySelectorAll("img").forEach(function(i){if(i.classList.contains("brand-mark"))return;'
        'if(i.complete&&i.naturalWidth===0)falhou(i);i.addEventListener("error",function(){falhou(i);});});})();</script>'
        + (
            ""
            if preview
            else (
                # Menu: cada item com submenu abre e fecha pela seta (o rótulo
                # continua a ser o link), no telemóvel e no computador. Fechar o
                # painel, clicar fora ou carregar em Esc fecha tudo, para a
                # próxima abertura não aparecer a lista a meio.
                '<script>(function(){var c=document.getElementById("menu-estado"),b=document.querySelector(".menu-botao"),'
                'n=document.querySelector("nav.main");if(!c||!n)return;'
                'function rotulo(i){var g=i.querySelector(".menu-pai");return g?g.textContent.trim():"";}'
                'function fechar(){n.querySelectorAll(".tem-submenu.aberto").forEach(function(i){i.classList.remove("aberto");'
                'var t=i.querySelector(".menu-abre");if(t){t.setAttribute("aria-expanded","false");'
                't.setAttribute("aria-label","Abrir "+rotulo(i));}});}'
                'function update(){var o=c.checked;b.setAttribute("aria-expanded",o?"true":"false");'
                'n.setAttribute("aria-expanded",o?"true":"false");b.setAttribute("aria-controls","menu-principal");'
                'n.id="menu-principal";if(!o)fechar();}'
                'n.querySelectorAll(".menu-abre").forEach(function(t){t.addEventListener("click",function(){'
                'var i=t.parentElement,a=i.classList.toggle("aberto");t.setAttribute("aria-expanded",a?"true":"false");'
                't.setAttribute("aria-label",(a?"Fechar ":"Abrir ")+rotulo(i));});});'
                'c.addEventListener("change",update);'
                'n.querySelectorAll("a").forEach(function(a){a.addEventListener("click",function(){'
                'c.checked=false;update();});});'
                # O clique no rótulo chega duas vezes ao `document` (o rótulo e a
                # caixa que ele liga): a caixa fica de fora, senão o painel abria
                # e fechava no mesmo toque.
                'document.addEventListener("click",function(e){'
                'if(e.target===c||n.contains(e.target)||b.contains(e.target))return;'
                'if(c.checked){c.checked=false;update();}else{fechar();}});'
                'document.addEventListener("keydown",function(e){if(e.key==="Escape")fechar();});update();})();</script>'
                # Um submenu dentro de outro abre ao lado; no fim da fila (o menu
                # vive à direita) não cabe e sai do ecrã. Aqui vira-se para a
                # esquerda, no momento em que a seta o abre.
                '<script>(function(){document.querySelectorAll("nav.main .submenu .submenu").forEach(function(sub){var item=sub.parentElement;function ajustar(){sub.classList.remove("abre-esquerda");if(sub.getBoundingClientRect().right>window.innerWidth-8){sub.classList.add("abre-esquerda");}}var t=item.querySelector(".menu-abre");if(t)t.addEventListener("click",ajustar);item.addEventListener("focusin",ajustar);});})();</script>'
            )
        )
        + "</body></html>"
    )


# --------------------------------------------------------------------------
# Páginas, artigos e blog
# --------------------------------------------------------------------------
def _page_description(page: Dict[str, Any]) -> str:
    seo = page.get("seo") or {}
    return str(seo.get("description") or page.get("excerpt") or _plain_excerpt(page))


def _plain_excerpt(doc: Dict[str, Any]) -> str:
    text = doc.get("excerpt") or doc.get("markdown") or ""
    plain = re.sub(r"[#*`>_|]", " ", str(text))
    return re.sub(r"\s+", " ", plain).strip()[:200]


def _trilha_da_pagina(page: Dict[str, Any]) -> List[Dict[str, str]]:
    """«Início › Secção › Página»: sobe pelos ascendentes da página.

    A página inicial não leva trilha (é o próprio «Início»).
    """
    settings = store.get_settings()
    if page.get("id") and str(page.get("id")) == str(settings.get("home_page_id") or ""):
        return []
    trilha: List[Dict[str, str]] = [{"label": "Início", "href": "/site"}]
    acima: List[Dict[str, str]] = []
    parent_id = page.get("parent_id")
    vistos: set = set()
    while parent_id and parent_id not in vistos:
        vistos.add(parent_id)
        try:
            pai = store.get_item("pages", str(parent_id))
        except KeyError:
            break
        caminho = str(pai.get("path") or "")
        acima.insert(
            0,
            {
                "label": str(pai.get("menu_label") or pai.get("title") or ""),
                "href": f"/site/{caminho}" if caminho else "/site",
            },
        )
        parent_id = pai.get("parent_id")
    trilha.extend(acima)
    if page.get("title"):
        trilha.append({"label": str(page["title"])})
    return trilha


def _site_home_url(settings: Dict[str, Any]) -> str:
    """O endereço da página inicial (serve de base aos `@id` do JSON-LD)."""
    return _absolute("/site/", str(settings.get("base_url") or ""))


def _caminho_da_pagina(page: Dict[str, Any]) -> str:
    """Endereço público de uma página.

    A inicial acaba em `/` porque é assim que o URL responde 200 (o `/site` sem
    barra é um redireccionamento) — a canónica tem de ser o endereço servido.
    """
    caminho = str(page.get("path") or "")
    return f"/site/{caminho}" if caminho else "/site/"


def _organization_json_ld(settings: Dict[str, Any]) -> Dict[str, Any]:
    """A entidade por trás do site, para o grafo de conhecimento dos motores.

    Os perfis das definições entram como `sameAs`: é assim que as redes sociais
    e o Google ligam o site às páginas oficiais da marca.
    """
    base_url = str(settings.get("base_url") or "")
    casa = _site_home_url(settings)
    dados: Dict[str, Any] = {
        "@type": "Organization",
        "@id": f"{casa}#organizacao",
        "name": str(settings.get("site_name") or ""),
        "url": casa,
    }
    descricao = str(settings.get("description") or (settings.get("seo") or {}).get("description") or "")
    if descricao:
        dados["description"] = descricao
    logo = _media_url(settings.get("logo_id"))
    if logo:
        dados["logo"] = {"@type": "ImageObject", "url": _absolute(logo, base_url)}
    perfis = [
        str(valor).strip()
        for chave, valor in (settings.get("social") or {}).items()
        if chave != "email" and str(valor or "").strip()
    ]
    if perfis:
        dados["sameAs"] = perfis
    return dados


def _website_json_ld(settings: Dict[str, Any]) -> Dict[str, Any]:
    casa = _site_home_url(settings)
    return {
        "@type": "WebSite",
        "@id": f"{casa}#site",
        "name": str(settings.get("site_name") or ""),
        "url": casa,
        "inLanguage": str(settings.get("language") or "pt-PT"),
        "publisher": {"@id": f"{casa}#organizacao"},
    }


def _faq_json_ld(blocks: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """`FAQPage` a partir do bloco de perguntas frequentes (dá rich results)."""
    perguntas: List[Dict[str, Any]] = []
    for block in blocks or []:
        if str(block.get("type") or "") != "faq" or block.get("hidden"):
            continue
        for item in (block.get("data") or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            pergunta = str(item.get("question") or item.get("title") or "").strip()
            resposta = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _md(str(item.get("answer") or item.get("text") or "")))).strip()
            if pergunta and resposta:
                perguntas.append(
                    {
                        "@type": "Question",
                        "name": pergunta,
                        "acceptedAnswer": {"@type": "Answer", "text": resposta},
                    }
                )
    if not perguntas:
        return None
    return {"@type": "FAQPage", "mainEntity": perguntas}


def render_page(
    page: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
    blog_post_count: int = 0,
) -> str:
    settings = settings or store.get_settings()
    seo = page.get("seo") or {}
    body = blocks_to_html(page.get("blocks") or [], preview=preview)
    if not body.strip():
        body = f'<div class="section prose">{_md(str(page.get("markdown") or page.get("excerpt") or ""))}</div>' or ""
    body = _garantir_h1(body, _titulo_visivel(page))
    base_url = str(settings.get("base_url") or "")
    path = _caminho_da_pagina(page)
    casa = _site_home_url(settings)
    imagem = _media_url(seo.get("image_id")) or _media_url((settings.get("seo") or {}).get("image_id"))
    # Bloco «@graph»: além da página, o site e a organização que o publica. O
    # motor passa a ter a marca ligada ao domínio, e não só uma página solta.
    grafo: List[Dict[str, Any]] = [_website_json_ld(settings), _organization_json_ld(settings)]
    pagina_ld: Dict[str, Any] = {
        "@type": "WebPage",
        "@id": f"{_absolute(path, base_url)}#pagina",
        "name": page.get("title"),
        "description": _page_description(page),
        "url": _absolute(path, base_url),
        "inLanguage": str(settings.get("language") or "pt-PT"),
        "isPartOf": {"@id": f"{casa}#site"},
        "publisher": {"@id": f"{casa}#organizacao"},
    }
    if imagem:
        pagina_ld["primaryImageOfPage"] = {
            "@type": "ImageObject",
            "url": _absolute(imagem, base_url),
        }
    if page.get("updated_at"):
        pagina_ld["dateModified"] = page.get("updated_at")
    grafo.append(pagina_ld)
    faq = _faq_json_ld(page.get("blocks") or [])
    if faq:
        grafo.append(faq)
    json_ld: Dict[str, Any] = {"@context": "https://schema.org", "@graph": grafo}
    # A página inicial recebe uma classe própria: o desenho de abertura (faixa
    # escura, números sobrepostos, ritmo mais amplo) não se aplica às restantes.
    wrap_class = "pagina-inicial" if str(page.get("template") or "") == "pagina-inicial" else ""
    return _layout(
        title=str(seo.get("title") or page.get("title") or ""),
        description=_page_description(page),
        body=body,
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=imagem,
        keywords=seo.get("keywords") or (settings.get("seo") or {}).get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=_trilha_da_pagina(page),
        wrap_class=wrap_class,
    )


# --------------------------------------------------------------------------
# Ficha pública de um município
# --------------------------------------------------------------------------
def _euros(valor: Any) -> str:
    """Valor em euros à portuguesa («317 577 000 €»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    return f"{numero:,.0f}".replace(",", " ") + " €"


def _euros_curto(valor: Any) -> str:
    """Valor em euros compacto, para os destaques («317,6 M€»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    if abs(numero) >= 1_000_000:
        return f"{numero / 1_000_000:.1f}".replace(".", ",") + " M€"
    if abs(numero) >= 1_000:
        return f"{numero / 1_000:.0f} mil €"
    return _euros(numero)


def _numero(valor: Any) -> str:
    try:
        return f"{int(valor or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _para_float(valor: Any) -> float:
    """Converte para número sem rebentar (o que chega pode ser nulo ou texto)."""
    try:
        return float(valor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tabela_nua(
    cabecalho: List[str],
    linhas: List[List[str]],
    *,
    classe: str = "",
    atributos: Optional[List[Dict[str, str]]] = None,
) -> str:
    """A tabela sem título — para quem já desenha o cabeçalho da secção.

    A rolagem horizontal e o `prose` (bordas, sombreado do cabeçalho) são os
    mesmos da `_tabela`; o que fica de fora é o `<h2>` e o `section`. Os
    `atributos` (uma lista alinhada com as linhas) saem como `data-*` na linha —
    é por aí que a pesquisa das tabelas filtra (ver `_tabela_filtravel`).
    """
    if not linhas:
        return ""
    head = "".join(f"<th>{_esc(celula)}</th>" for celula in cabecalho)
    corpo = []
    for indice, linha in enumerate(linhas):
        dados = (atributos[indice] if atributos and indice < len(atributos) else None) or {}
        extra = "".join(
            f' data-{_esc(chave)}="{_esc(valor)}"' for chave, valor in dados.items() if str(valor or "")
        )
        corpo.append(
            f"<tr{extra}>" + "".join(f"<td>{_esc(celula)}</td>" for celula in linha) + "</tr>"
        )
    extra_classe = f" {classe}" if classe else ""
    return (
        f'<div class="tabela-rolavel larga{extra_classe} prose"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(corpo)}</tbody></table></div>"
    )


def _tabela(
    titulo: str,
    cabecalho: List[str],
    linhas: List[List[str]],
    *,
    atributos: Optional[List[Dict[str, str]]] = None,
) -> str:
    if not linhas:
        return ""
    return (
        f'<div class="section prose"><h2>{_esc(titulo)}</h2>'
        f"{_tabela_nua(cabecalho, linhas, atributos=atributos)}</div>"
    )


def _kpis_do_municipio(dados: Dict[str, Any]) -> str:
    ano = dados.get("ano_despesas")
    contratos = dados.get("contratos") or {}
    cartoes = [
        ("Despesa total", _euros_curto(dados.get("despesas_total")), f"Execução de {ano}" if ano else ""),
        ("Despesas correntes", _euros_curto(dados.get("despesas_correntes")), "Funcionamento corrente"),
        ("Despesas de capital", _euros_curto(dados.get("despesas_capital")), "Investimento e outros"),
        ("Despesa com pessoal", _euros_curto(dados.get("despesas_pessoal")), "Rubrica D11"),
        ("Bens e serviços", _euros_curto(dados.get("despesas_bens_servicos")), "Rubrica D12"),
    ]
    if contratos.get("total"):
        cartoes.append((
            "Contratos celebrados",
            _numero(contratos.get("total")),
            f"{_euros_curto(contratos.get('valor'))} em aquisições",
        ))
    abertos = "".join(
        f'<div class="kpi"><span>{_esc(titulo)}</span><strong>{_esc(valor)}</strong>'
        + (f"<small>{_esc(nota)}</small>" if nota else "")
        + "</div>"
        for titulo, valor, nota in cartoes
    )
    return f'<div class="section kpis">{abertos}</div>'


def _corpo_do_municipio(dados: Dict[str, Any], doc: Dict[str, Any], *, preview: bool) -> str:
    """Blocos editoriais + os dados oficiais que os sustentam."""
    corpo: List[str] = [_kpis_do_municipio(dados), blocks_to_html(doc.get("blocks") or [], preview=preview)]

    classificadores = dados.get("por_classificador") or []
    if classificadores:
        corpo.append(_tabela(
            f"Despesa por classificador económico ({dados.get('ano_despesas')})",
            ["Classificador", "Valor"],
            [[item.get("etiqueta") or item.get("codigo") or "", _euros(item.get("valor"))] for item in classificadores],
        ))

    contratos = dados.get("contratos") or {}
    por_ano = contratos.get("por_ano") or {}
    if por_ano:
        linhas = [
            [str(ano), _numero((valores or {}).get("contratos")), _euros((valores or {}).get("valor"))]
            for ano, valores in sorted(por_ano.items())
            if isinstance(valores, dict)
        ]
        corpo.append(_tabela(
            "Contratação pública por ano (Portal BASE)",
            ["Ano", "Contratos", "Valor"],
            list(reversed(linhas)),
        ))

    fornecedores = contratos.get("fornecedores") or []
    if fornecedores:
        corpo.append(_tabela(
            "Principais fornecedores",
            ["Fornecedor", "Contratos", "Valor"],
            [[item.get("nome") or "", _numero(item.get("contratos")), _euros(item.get("valor"))] for item in fornecedores],
        ))

    fontes = [fonte.get("documento") for fonte in (dados.get("fontes") or []) if fonte.get("documento")]
    if fontes:
        recolhido = _date(dados.get("recolhido_em")) if dados.get("recolhido_em") else ""
        nota = " · ".join(fontes)
        if recolhido:
            nota += f" · dados recolhidos a {recolhido}"
        corpo.append(f'<div class="section aviso">{_esc(nota)}</div>')

    return _garantir_h1(
        "".join(bloco for bloco in corpo if bloco),
        _titulo_visivel(doc, str(dados.get("municipio") or "")),
    )


def render_municipio(
    doc: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Ficha pública de um município: texto editorial e os números oficiais."""
    settings = settings or store.get_settings()
    seo = doc.get("seo") or {}
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    municipio = str(doc.get("municipio") or dados.get("municipio") or doc.get("title") or "")
    path = f"/site/municipio/{doc.get('slug')}" if doc.get("slug") else "/site"
    base_url = str(settings.get("base_url") or "")
    descricao = str(seo.get("description") or doc.get("excerpt") or "").strip() or (
        f"Despesa e contratação pública da Câmara Municipal de {municipio}."
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": doc.get("title") or municipio,
        "description": descricao,
        "url": _absolute(path, base_url),
        "about": {"@type": "GovernmentOrganization", "name": f"Câmara Municipal de {municipio}"},
        "isBasedOn": [fonte.get("url") for fonte in (dados.get("fontes") or []) if fonte.get("url")],
    }
    return _layout(
        title=str(seo.get("title") or doc.get("title") or municipio),
        description=descricao,
        body=_corpo_do_municipio(dados, doc, preview=preview),
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Municípios", "href": "/site/solucoes/municipios"},
            {"label": municipio},
        ],
    )


# --------------------------------------------------------------------------
# Página de uma pesquisa (entidade `pesquisas`)
# --------------------------------------------------------------------------
_CSS_PESQUISA = """
.pesquisa-marca { display: flex; align-items: center; gap: 14px; margin: 0 0 16px; }
.pesquisa-marca img { max-height: 54px; width: auto; }
.pesquisa-capa { margin: 0 0 22px; }
.pesquisa-capa img { width: 100%; border-radius: var(--radius); border: 1px solid var(--border); }
.pesquisa-tabela { overflow-x: auto; }
.pesquisa-tabela th, .pesquisa-tabela td { white-space: nowrap; }
.pesquisa-anos { color: var(--muted); font-size: .85rem; }
.grafico { margin: 0 0 26px; }
.grafico h3 { margin: 0 0 2px; font-size: 1rem; }
.grafico p.sub { margin: 0 0 12px; color: var(--muted); font-size: .82rem; }
.barras { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.barras li { display: grid; grid-template-columns: minmax(90px, 190px) 1fr auto; align-items: center; gap: 10px; font-size: .88rem; }
.barras .rotulo { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.barras .barra { background: color-mix(in srgb, var(--muted) 22%, transparent); border-radius: 999px; height: 9px; }
.barras .barra i { display: block; height: 9px; border-radius: 999px; background: var(--accent); min-width: 2px; }
.barras .valor { font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.barras .valor small { display: block; color: var(--muted); font-weight: 400; font-size: .78rem; }
/* Municípios clicáveis: a barra é o botão que filtra a tabela e abre o gráfico do município. */
.barras li.clicavel > button {
  grid-column: 1 / -1; display: grid; grid-template-columns: minmax(90px, 190px) 1fr auto;
  align-items: center; gap: 10px; width: 100%; padding: 3px 6px; margin: -3px -6px;
  border: 0; border-radius: 8px; background: none; color: inherit; font: inherit;
  text-align: left; cursor: pointer;
}
.barras li.clicavel > button:hover { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.barras li.clicavel > button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.barras li.clicavel > button[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 16%, transparent); }
.barras li.clicavel > button[aria-pressed="true"] .rotulo { color: var(--accent); font-weight: 600; }
.pesquisa-detalhes { margin: 0 0 26px; }
.pesquisa-detalhes-cabeca { display: flex; justify-content: flex-end; margin: 0 0 10px; }
.pesquisa-limpar {
  min-height: 40px; padding: 8px 14px; border-radius: 999px; border: 1px solid var(--border);
  background: transparent; color: var(--accent); font: inherit; font-size: .88rem; font-weight: 600; cursor: pointer;
}
.pesquisa-limpar:hover { border-color: var(--accent); }
/* Linhas escondidas pelo município escolhido (classe, e não `hidden`: vale para `<tr>`). */
.pesquisa-linha { display: none; }
"""


def _com_ano_despesas(ano: Any) -> str:
    return f"Despesa {ano}" if ano else "Despesa"


def _marca_da_pesquisa(doc: Dict[str, Any]) -> str:
    """Logótipo e imagem de capa **da página** (não das definições do site)."""
    partes: List[str] = []
    logo = _media_url(doc.get("logo_id"))
    if logo:
        partes.append(
            f'<div class="pesquisa-marca"><img src="{_esc(logo)}" '
            f'alt="{_esc(str(doc.get("title") or "Logótipo"))}"></div>'
        )
    capa = _media_url(doc.get("capa_id"))
    if capa:
        partes.append(
            f'<figure class="pesquisa-capa"><img src="{_esc(capa)}" '
            f'alt="{_esc(str(doc.get("title") or ""))}"></figure>'
        )
    return "".join(partes)


def _kpis_da_pesquisa(dados: Dict[str, Any]) -> str:
    ano = dados.get("ano_contratos")
    cartoes = [
        ("Municípios no filtro", _numero(dados.get("total")), "depois dos filtros aplicados"),
        (
            "Despesa somada",
            _euros_curto(dados.get("despesas_somadas")),
            f"INE · ano {dados.get('ano_despesas')}" if dados.get("ano_despesas") else "INE",
        ),
        ("Contratado", _euros_curto(dados.get("contratos_somados")), "Portal BASE · 2012→hoje"),
    ]
    if ano:
        cartoes.append(
            (
                f"Contratado em {ano}",
                _euros_curto(dados.get("contratos_ano_somados")),
                f"{_numero(dados.get('contratos_ano_total_somados'))} contratos",
            )
        )
    abertos = "".join(
        f'<div class="kpi"><span>{_esc(titulo)}</span><strong>{_esc(valor)}</strong>'
        + (f"<small>{_esc(nota)}</small>" if nota else "")
        + "</div>"
        for titulo, valor, nota in cartoes
    )
    return f'<div class="section kpis">{abertos}</div>'


def _tabela_da_pesquisa(dados: Dict[str, Any]) -> str:
    itens = dados.get("itens") or []
    if not itens:
        return '<div class="section aviso">Nenhum município com estes filtros.</div>'
    ano = dados.get("ano_contratos")
    ano_despesas = dados.get("ano_despesas")
    cabecalho = ["Município", "Distrito", _com_ano_despesas(ano_despesas), "Contratado (total)", "Anos recentes"]
    if ano:
        cabecalho = [
            "Município",
            "Distrito",
            _com_ano_despesas(ano_despesas),
            f"Contratos {ano}",
            f"Contratado {ano}",
            "Anos recentes",
        ]
    linhas: List[List[str]] = []
    atributos: List[Dict[str, str]] = []
    for item in itens:
        anos_recentes = " · ".join(
            str(registro.get("ano") or "") for registro in (item.get("anos_recentes") or [])[:5]
        )
        linha = [
            str(item.get("nome") or ""),
            str(item.get("distrito") or "—"),
            _euros_curto(item.get("despesas_total")),
        ]
        if ano:
            linha += [_numero(item.get("contratos_ano_total")), _euros_curto(item.get("contratos_ano_valor"))]
        else:
            linha += [_euros_curto(item.get("contratos_valor"))]
        linha.append(anos_recentes)
        linhas.append(linha)
        # O nome na linha é a chave do clique no gráfico (`_JS_PESQUISA_MUNICIPIO`).
        atributos.append({"municipio": str(item.get("nome") or "")})
    tabela = _tabela("Municípios do filtro", cabecalho, linhas, atributos=atributos)
    nota = f"{_numero(dados.get('linhas'))} de {_numero(dados.get('total'))} municípios"
    return (
        f'<div class="pesquisa-tabela" data-pesquisa-tabela data-total="{_esc(dados.get("total"))}">'
        f"{tabela}</div>"
        f'<div class="section"><p class="meta">'
        f'<span data-papel="conta-municipios" aria-live="polite">{_esc(nota)}</span> · '
        f'{_esc(str(dados.get("descricao") or ""))}</p></div>'
    )


def _series_da_contratacao(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A contratação do Portal BASE nos anos recentes de um município, ano a ano.

    Sai do mais antigo para o mais recente — a mesma leitura do gráfico «Contratado
    por ano» — e só leva anos com valor: um ano sem contratação não é uma barra de zero.
    """
    series = [
        {
            "rotulo": str(registo.get("ano") or ""),
            "valor": _para_float(registo.get("valor")),
            "nota": f"{_numero(registo.get('contratos'))} contratos",
        }
        for registo in item.get("anos_recentes") or []
        if str(registo.get("ano") or "") and _para_float(registo.get("valor")) > 0
    ]
    return sorted(series, key=lambda ponto: ponto["rotulo"])


def _municipios_escolhiveis(dados: Dict[str, Any]) -> List[str]:
    """Os municípios que o gráfico mostra **e** que têm linha na tabela.

    São estes — e só estes — que se podem escolher: uma barra sem linha ao lado não
    teria tabela para filtrar, e uma linha sem série anual não teria gráfico para abrir.
    A ordem é a do gráfico (a ordenação que o editor congelou na pesquisa).
    """
    grafico = next((g for g in dados.get("graficos") or [] if g.get("id") == "municipios"), None)
    if not grafico:
        return []
    por_nome = {str(item.get("nome") or ""): item for item in dados.get("itens") or []}
    nomes: List[str] = []
    for barra in grafico.get("itens") or []:
        nome = str(barra.get("rotulo") or "")
        if not nome or nome in nomes:
            continue
        item = por_nome.get(nome)
        if item and _series_da_contratacao(item):
            nomes.append(nome)
    return nomes


def _detalhes_da_pesquisa(dados: Dict[str, Any], escolhiveis: List[str]) -> str:
    """O gráfico de cada município escolhível, escondido até se clicar na barra dele.

    Fica **por cima da tabela** e é escrito aqui, no servidor: os valores têm o
    mesmo formato do resto da página e não dependem de JavaScript para existir.
    """
    if not escolhiveis:
        return ""
    por_nome = {str(item.get("nome") or ""): item for item in dados.get("itens") or []}
    ano_despesas = dados.get("ano_despesas")
    paineis: List[str] = []
    for nome in escolhiveis:
        item = por_nome.get(nome) or {}
        nota = "Contratado por ano (Portal BASE)"
        if ano_despesas:
            nota += f" · despesa total de {ano_despesas}: {_euros_curto(item.get('despesas_total'))}"
        paineis.append(
            f'<section class="section grafico" data-detalhe="{_esc(nome)}" hidden>'
            f'<h2 class="seccao-titulo">{_esc(nome)}</h2>'
            f'<p class="sub">{_esc(nota)}</p>'
            f"{_barras(_series_da_contratacao(item))}</section>"
        )
    return (
        '<div class="pesquisa-detalhes" data-pesquisa-detalhes hidden>'
        '<div class="pesquisa-detalhes-cabeca">'
        '<button type="button" class="pesquisa-limpar" data-papel="limpar-municipios">Limpar filtro</button>'
        "</div>" + "".join(paineis) + "</div>"
    )


#: Município escolhido no gráfico: filtra a tabela e abre o gráfico anual dele.
#: Vai no fim da página (precisa da tabela já no HTML) e escreve-se em JavaScript
#: simples porque a página sai do servidor como um só ficheiro, sem build.
_JS_PESQUISA_MUNICIPIO = """
<script>(function(){
var botoes=Array.prototype.slice.call(document.querySelectorAll('[data-escolher]'));
var caixa=document.querySelector('[data-pesquisa-tabela]');
if(!botoes.length||!caixa)return;
var linhas=Array.prototype.slice.call(caixa.querySelectorAll('tbody tr'));
var paineis=Array.prototype.slice.call(document.querySelectorAll('[data-detalhe]'));
var detalhes=document.querySelector('[data-pesquisa-detalhes]');
var conta=document.querySelector('[data-papel="conta-municipios"]');
var limpar=document.querySelector('[data-papel="limpar-municipios"]');
var semEscolha=conta?conta.textContent:'';
var total=caixa.getAttribute('data-total')||String(linhas.length);
var escolhido='';
function aplicar(){
  var visiveis=0;
  linhas.forEach(function(linha){
    var mostra=!escolhido||linha.getAttribute('data-municipio')===escolhido;
    linha.classList.toggle('pesquisa-linha',!mostra);
    if(mostra)visiveis+=1;
  });
  botoes.forEach(function(botao){
    var ativo=!!escolhido&&botao.getAttribute('data-escolher')===escolhido;
    botao.setAttribute('aria-pressed',ativo?'true':'false');
  });
  paineis.forEach(function(painel){
    painel.hidden=!escolhido||painel.getAttribute('data-detalhe')!==escolhido;
  });
  if(detalhes)detalhes.hidden=!escolhido;
  if(conta)conta.textContent=escolhido?visiveis+' de '+total+' municípios':semEscolha;
}
botoes.forEach(function(botao){
  botao.addEventListener('click',function(){
    var nome=botao.getAttribute('data-escolher')||'';
    escolhido=escolhido===nome?'':nome;
    aplicar();
  });
});
if(limpar)limpar.addEventListener('click',function(){escolhido='';aplicar();});
aplicar();
})();</script>
"""


def _corpo_da_pesquisa(dados: Dict[str, Any], doc: Dict[str, Any], *, preview: bool) -> str:
    """Marca + texto editorial + os números que a pesquisa devolveu."""
    marca = _marca_da_pesquisa(doc)
    partes: List[str] = []
    if doc.get("intro"):
        partes.append(f'<div class="section prose">{_md(str(doc["intro"]))}</div>')
    if dados.get("descricao"):
        partes.append(
            f'<div class="section"><p class="pill">{_esc(str(dados["descricao"]))}</p></div>'
        )
    partes.append(_kpis_da_pesquisa(dados))
    partes.append(blocks_to_html(doc.get("blocks") or [], preview=preview))
    # Quem se pode escolher no gráfico: filtra a tabela e abre o gráfico anual do município.
    escolhiveis = _municipios_escolhiveis(dados)
    partes.append(_graficos_da_pesquisa(dados, escolhiveis=set(escolhiveis)))
    partes.append(_detalhes_da_pesquisa(dados, escolhiveis))
    partes.append(_tabela_da_pesquisa(dados))
    partes.append(_adjudicatarios_da_pesquisa(dados))

    fontes = [fonte.get("documento") for fonte in (dados.get("fontes") or []) if fonte.get("documento")]
    if fontes:
        nota = " · ".join(fontes)
        recolhido = _date(dados.get("gerado_em")) if dados.get("gerado_em") else ""
        if recolhido:
            nota += f" · valores lidos a {recolhido}"
        partes.append(f'<div class="section aviso">{_esc(nota)}</div>')
    corpo = _garantir_h1("".join(parte for parte in partes if parte), _titulo_visivel(doc))
    # O filtro do gráfico é um só script, no fim: tem de vir depois da tabela.
    if escolhiveis:
        corpo += _JS_PESQUISA_MUNICIPIO
    return marca + corpo


def _barra_de_valor(valor: float, maximo: float) -> int:
    """A largura da barra, em percentagem do maior valor da série."""
    if maximo <= 0 or valor <= 0:
        return 0
    return max(2, int(round(100 * valor / maximo)))


def _barras(
    itens: List[Dict[str, Any]],
    *,
    unidade: Optional[str] = None,
    formatador: Optional[Any] = None,
    escolher: Optional[Set[str]] = None,
) -> str:
    """Gráfico de barras em HTML/CSS.

    Não é uma imagem nem um canvas: o valor e o rótulo ficam **em texto**, por
    isso o gráfico lê-se (e imprime-se) sem cor, e o que está escrito é o mesmo
    número que a tabela mostra.

    O `formatador` deixa quem chama escolher a escala do valor: as despesas
    municipais são milhões (formato curto), mas uma remuneração base mostra-se
    com cêntimos («1 442,57 €»).

    Os rótulos em `escolher` saem como **botões** (`data-escolher`): são as
    barras que filtram a página (ver `_JS_PESQUISA_MUNICIPIO`).
    """
    valores = [_para_float(item.get("valor")) for item in itens]
    maximo = max(valores) if valores else 0.0
    linhas = []
    for item, valor in zip(itens, valores):
        nota = str(item.get("nota") or "")
        if formatador is not None:
            texto = formatador(valor)
        else:
            texto = _numero(valor) if unidade == "contratos" else _euros_curto(valor)
        rotulo = _esc(item.get("rotulo"))
        conteudo = (
            f'<span class="rotulo">{rotulo}</span>'
            f'<span class="barra"><i style="width:{_barra_de_valor(valor, maximo)}%"></i></span>'
            f'<span class="valor">{_esc(texto)}'
            + (f"<small>{_esc(nota)}</small>" if nota else "")
            + "</span>"
        )
        if escolher and str(item.get("rotulo") or "") in escolher:
            linhas.append(
                f'<li class="clicavel">'
                f'<button type="button" data-escolher="{rotulo}" aria-pressed="false">{conteudo}</button>'
                "</li>"
            )
        else:
            linhas.append(f"<li>{conteudo}</li>")
    return f'<ul class="barras">{"".join(linhas)}</ul>'


def _graficos_da_pesquisa(dados: Dict[str, Any], escolhiveis: Optional[Set[str]] = None) -> str:
    """As séries da pesquisa: municípios do topo, contratado e despesa por ano.

    Os municípios em `escolhiveis` saem como **barras clicáveis** (`data-escolher`).
    """
    partes = []
    for grafico in dados.get("graficos") or []:
        itens = grafico.get("itens") or []
        if not itens:
            continue
        clicaveis = escolhiveis if grafico.get("id") == "municipios" else None
        partes.append(
            f'<section class="section grafico"><h2 class="seccao-titulo">{_esc(grafico.get("titulo"))}</h2>'
            f'<p class="sub">{_esc(grafico.get("subtitulo") or "")}</p>'
            f'{_barras(itens, unidade=grafico.get("unidade"), escolher=clicaveis)}</section>'
        )
    return "".join(partes)


def _adjudicatarios_da_pesquisa(dados: Dict[str, Any]) -> str:
    """Os maiores adjudicatários do filtro: barras por cima, tabela por baixo."""
    bloco = dados.get("adjudicatarios") or {}
    itens = bloco.get("itens") or []
    if not itens:
        return ""
    ano = bloco.get("ano")
    titulo = "Principais adjudicatários" + (f" em {ano}" if ano else "")
    considerados = _numero(bloco.get("municipios"))
    subtitulo = (
        f"{_numero(bloco.get('total'))} adjudicatários"
        + (f" nos contratos dos {considerados} municípios considerados" if bloco.get("municipios") else "")
        + f" · {_euros_curto(bloco.get('valor'))} adjudicados · "
        "um contrato com vários adjudicatários conta em cada um"
    )
    cabecalho = ["Adjudicatário", "Contratos", "Valor"]
    linhas = [
        [str(item.get("nome") or ""), _numero(item.get("contratos")), _euros_curto(item.get("valor"))]
        for item in itens
    ]
    barras = [
        {
            "rotulo": item.get("nome"),
            "valor": _para_float(item.get("valor")),
            "nota": f"{_numero(item.get('contratos'))} contratos",
        }
        for item in itens[:12]
    ]
    return (
        '<section class="section grafico"><h2 class="seccao-titulo">'
        + _esc(titulo)
        + f'</h2><p class="sub">{_esc(subtitulo)}</p>'
        + _barras(barras)
        + "</section>"
        # A tabela é o detalhe do mesmo bloco: leva o `h2` da secção acima, não
        # um título próprio repetido (`_tabela_nua`).
        + f'<div class="section prose">{_tabela_nua(cabecalho, linhas)}</div>'
    )


def render_pesquisa(
    doc: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Página pública de uma pesquisa de despesas municipais (filtros congelados)."""
    settings = settings or store.get_settings()
    seo = doc.get("seo") or {}
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    titulo = str(doc.get("title") or "Pesquisa de despesas municipais")
    path = f"/site/pesquisa/{doc.get('slug')}" if doc.get("slug") else "/site"
    base_url = str(settings.get("base_url") or "")
    descricao = str(seo.get("description") or doc.get("excerpt") or "").strip() or (
        f"{titulo}: {dados.get('descricao') or 'despesa e contratação dos municípios'}"
        f" (INE e Portal BASE)."
    )
    cor = str(doc.get("cor") or "").strip()
    extra_css = _CSS_PESQUISA + (f":root {{ --accent: {cor}; }}" if cor else "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": titulo,
        "description": descricao,
        "url": _absolute(path, base_url),
        "spatialCoverage": {"@type": "Place", "name": "Portugal"},
        "creator": {"@type": "Organization", "name": str(settings.get("site_name") or "")},
        "isBasedOn": [fonte.get("url") for fonte in (dados.get("fontes") or []) if fonte.get("url")],
    }
    if dados.get("ano_contratos") or dados.get("ano_despesas"):
        json_ld["temporalCoverage"] = str(dados.get("ano_contratos") or dados.get("ano_despesas"))
    return _layout(
        title=str(seo.get("title") or titulo),
        description=descricao,
        body=_corpo_da_pesquisa(dados, doc, preview=preview),
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id") or doc.get("capa_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        extra_css=extra_css,
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Pesquisas"},
            {"label": titulo},
        ],
    )


# --------------------------------------------------------------------------
# Página do modelo de remunerações da Administração Pública (`remuneracoes`)
#
# A página é feita de **secções** (`cms_store.SECCOES_REMUNERACOES`): cada uma
# tem título e subtítulo editáveis no CMS, pode ser desligada (`mostrar`) e
# entra na ordem que o editor escolheu (`ordem`). O estilo (`estilo`) decide só
# a superfície — cartões, linhas de separação ou cabeçalhos em faixa —, e o
# acento do documento (`cor`) pinta os números e as âncoras.
# --------------------------------------------------------------------------
_CSS_REMUNERACOES = """
.rem-marca { display: flex; align-items: center; gap: 14px; margin: 0 0 16px; }
.rem-marca img { max-height: 54px; width: auto; }
.rem-capa { margin: 0 0 22px; }
.rem-capa img { width: 100%; border-radius: var(--radius); border: 1px solid var(--border); }
/* Um quadro com oito secções precisa de um mapa no topo. */
.rem-indice { margin: 0 0 18px; }
.rem-indice ol { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.rem-indice a {
  display: inline-flex; align-items: center; gap: 7px; min-height: 40px; padding: 8px 13px;
  border: 1px solid var(--border); border-radius: 999px; background: var(--surface);
  color: var(--text); font-size: .88rem; font-weight: 600;
}
.rem-indice a:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
.rem-indice .num { color: var(--muted); font-size: .8rem; font-variant-numeric: tabular-nums; }
/* Cada secção: cabeçalho editável (título e subtítulo) e âncora própria. */
.rem-sec { scroll-margin-top: 92px; }
.rem-sec-cabeca { display: grid; gap: 6px; margin: 0 0 14px; }
.rem-sec h2 { margin: 0; }
.rem-sec h2::before { content: ""; display: block; width: 36px; height: 3px; border-radius: 3px; background: var(--accent); margin: 0 0 10px; }
.rem-sec .sub { margin: 0; color: var(--muted); font-size: .93rem; }
.rem-sec h3 { margin: 0 0 2px; }
.rem-carreira { margin: 0 0 22px; }
.rem-tabela { overflow-x: auto; }
.rem-tabela th, .rem-tabela td { white-space: nowrap; }
.rem-niveis { max-height: 420px; overflow: auto; }
.rem-niveis thead th { position: sticky; top: 0; z-index: 1; }
/* Pesquisa e filtros das tabelas: quem lê filtra as linhas sem voltar ao servidor. */
.rem-filtro-campos { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; margin: 0 0 10px; }
.rem-filtro-campos input[type="search"], .rem-filtro-campos select {
  min-height: 40px; padding: 8px 11px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit; font-size: .9rem;
}
.rem-filtro-campos input[type="search"] { flex: 1 1 220px; min-width: 170px; }
.rem-filtro-campos select { max-width: 320px; }
.rem-filtro-campos :focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.rem-filtro-campo { display: grid; gap: 4px; }
.rem-filtro-campo > span { color: var(--muted); font-size: .72rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.rem-filtro-limpar {
  min-height: 40px; padding: 8px 14px; border-radius: 999px; border: 1px solid var(--border);
  background: transparent; color: var(--accent); font: inherit; font-size: .88rem; font-weight: 600; cursor: pointer;
}
.rem-filtro-limpar:hover { border-color: var(--accent); }
.rem-filtro-conta { margin-left: auto; color: var(--muted); font-size: .84rem; font-variant-numeric: tabular-nums; }
.rem-filtro-vazio { margin: 10px 0 0; }
/* Linhas escondidas pelos filtros (classe, e não `hidden`: vale para `<tr>`). */
.rem-filtro-linha { display: none; }
/* Os números do quadro ganham o acento da página: é o que liga a marca ao dado. */
.rem-sec .kpi { border-left: 3px solid var(--accent); }
.rem-sec .kpi strong { color: var(--accent); }
.rem-sim { display: grid; gap: 12px; grid-template-columns: minmax(180px, 260px) 1fr; align-items: start; }
.rem-sim .campos { display: grid; gap: 10px; }
.rem-sim .saida { display: flex; flex-wrap: wrap; gap: 18px; }
.rem-sim .saida strong { display: block; font-size: 1.5rem; color: var(--accent); font-variant-numeric: tabular-nums; }
.rem-sim .saida em { display: block; font-style: normal; font-variant-numeric: tabular-nums; }
.rem-sim select, .rem-sim input { width: 100%; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: transparent; color: inherit; }
.rem-notas summary { cursor: pointer; font-weight: 600; }
/* Estilo das secções, escolhido no editor: cada um muda só a superfície. */
.rem-estilo-cartoes .rem-sec { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px 16px; }
.rem-estilo-plano .rem-sec { border-top: 1px solid var(--border); padding-top: 20px; }
.rem-estilo-plano .rem-sec h2::before { display: none; }
.rem-estilo-destaque .rem-sec { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.rem-estilo-destaque .rem-sec-cabeca {
  margin: 0; padding: 16px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 16%, var(--surface)), var(--surface));
}
.rem-estilo-destaque .rem-sec-corpo { padding: 16px; }
@media (min-width: 700px) {
  .rem-estilo-cartoes .rem-sec { padding: 24px 22px; }
  .rem-estilo-destaque .rem-sec-cabeca { padding: 22px 24px; }
  .rem-estilo-destaque .rem-sec-corpo { padding: 22px 24px; }
}
@media (max-width: 640px) { .rem-sim { grid-template-columns: 1fr; } }
"""


def _tabela_filtravel(
    cabecalho: List[str],
    linhas: List[List[str]],
    *,
    busca: str,
    atributos: Optional[List[Dict[str, str]]] = None,
    filtros: Optional[List[Dict[str, Any]]] = None,
    classe: str = "",
    unidade: str = "linhas",
    unidade_singular: str = "",
) -> str:
    """Tabela com **pesquisa e filtros**, feitos pela própria página.

    Quem lê filtra as linhas no browser (o JavaScript vai no fim da página, ver
    `_JS_FILTROS_TABELAS`): a tabela é a fotografia publicada e não se volta a
    ler do servidor a cada tecla.

    Os filtros comparam **atributos da linha** (`data-*`), não o texto das
    células — é o que permite filtrar por «secção» sem mostrar a coluna, e por
    «com/sem valor publicado» sem depender do formato do número. As opções saem
    dos valores que a tabela tem; quando o rótulo importa, são dadas à mão.
    """
    if not linhas:
        return ""
    atributos = atributos or []
    singular = unidade_singular or unidade
    rotulo = singular if len(linhas) == 1 else unidade
    campos = [
        f'<input type="search" data-papel="busca" placeholder="{_esc(busca)}" aria-label="{_esc(busca)}">'
    ]
    for filtro in filtros or []:
        atributo = str(filtro.get("atributo") or "")
        opcoes = filtro.get("opcoes")
        if not opcoes:
            valores: List[str] = []
            for linha in atributos:
                valor = str(linha.get(atributo) or "")
                if valor and valor not in valores:
                    valores.append(valor)
            opcoes = [(valor, valor) for valor in sorted(valores, key=str.lower)]
        if not opcoes or not atributo:
            continue
        itens = "".join(
            f'<option value="{_esc(valor)}">{_esc(rotulo_opcao)}</option>' for valor, rotulo_opcao in opcoes
        )
        campos.append(
            f'<label class="rem-filtro-campo"><span>{_esc(filtro.get("rotulo") or atributo)}</span>'
            f'<select data-filtro="{_esc(atributo)}">'
            f'<option value="">{_esc(filtro.get("todos") or "Todos")}</option>{itens}</select></label>'
        )
    campos.append(f'<span class="rem-filtro-conta" data-papel="conta">{len(linhas)} {_esc(rotulo)}</span>')
    campos.append('<button type="button" class="rem-filtro-limpar" data-papel="limpar" hidden>Limpar</button>')
    return (
        f'<div class="rem-filtro" data-tabela-filtro data-unidade="{_esc(unidade)}" '
        f'data-unidade-singular="{_esc(singular)}">'
        f'<div class="rem-filtro-campos">{"".join(campos)}</div>'
        f"{_tabela_nua(cabecalho, linhas, classe=classe, atributos=atributos)}"
        '<p class="rem-filtro-vazio meta" data-papel="vazio" hidden>Nenhuma linha corresponde à pesquisa.</p>'
        "</div>"
    )


#: Pesquisa e filtros das tabelas: um só script para todas (vai no fim da página,
#: depois das tabelas que ele filtra). Escreve-se em JavaScript simples porque não
#: há build nem dependências: é o mesmo ficheiro HTML que sai do servidor.
_JS_FILTROS_TABELAS = r"""
<script>(function(){
var caixas=document.querySelectorAll('[data-tabela-filtro]');
function semAcentos(valor){return (valor||'').toString().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');}
Array.prototype.forEach.call(caixas,function(caixa){
  var tabela=caixa.querySelector('table');
  if(!tabela||!tabela.tBodies.length)return;
  var linhas=Array.prototype.slice.call(tabela.tBodies[0].rows);
  var busca=caixa.querySelector('[data-papel="busca"]');
  var limpar=caixa.querySelector('[data-papel="limpar"]');
  var conta=caixa.querySelector('[data-papel="conta"]');
  var vazio=caixa.querySelector('[data-papel="vazio"]');
  var unidade=caixa.getAttribute('data-unidade')||'linhas';
  var singular=caixa.getAttribute('data-unidade-singular')||unidade;
  var campos=Array.prototype.slice.call(caixa.querySelectorAll('[data-filtro]'));
  var textos=linhas.map(function(linha){return semAcentos(linha.textContent);});
  function aplicar(){
    var termo=semAcentos(busca?busca.value.trim():'');
    var escolhas=campos.map(function(campo){return [campo.getAttribute('data-filtro'),campo.value];});
    var ativos=0;
    linhas.forEach(function(linha,indice){
      var mostra=!termo||textos[indice].indexOf(termo)>=0;
      if(mostra){
        escolhas.forEach(function(escolha){
          if(!escolha[1])return;
          if((linha.getAttribute('data-'+escolha[0])||'')!==escolha[1])mostra=false;
        });
      }
      linha.classList.toggle('rem-filtro-linha',!mostra);
      if(mostra)ativos+=1;
    });
    if(conta)conta.textContent=ativos+' de '+linhas.length+' '+(linhas.length===1?singular:unidade);
    if(vazio)vazio.hidden=ativos>0;
    if(limpar){
      var aFiltrar=!!termo;
      escolhas.forEach(function(escolha){if(escolha[1])aFiltrar=true;});
      limpar.hidden=!aFiltrar;
    }
  }
  if(busca)busca.addEventListener('input',aplicar);
  campos.forEach(function(campo){campo.addEventListener('change',aplicar);});
  if(limpar)limpar.addEventListener('click',function(){
    if(busca)busca.value='';
    campos.forEach(function(campo){campo.value='';});
    aplicar();
    if(busca)busca.focus();
  });
  aplicar();
});
})();</script>
"""


def _rem_euros(valor: Any) -> str:
    """Euros com cêntimos, à portuguesa («1 442,57 €»).

    A página das remunerações não pode arredondar: o quadro da DGAEP publica
    valores exatos com cêntimos (934,99 €, 1 442,57 €), e é isso que quem lê
    compara. O `_euros` do site é para os grandes números dos contratos.
    """
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    return f"{numero:,.2f}".replace(",", " ").replace(".", ",") + " €"


def _rem_barras(itens: List[Dict[str, Any]]) -> str:
    """Barras das remunerações: euros exatos, como nas tabelas."""
    return _barras(itens, formatador=_rem_euros)


def _rem_seccao(chave: str, seccao: Dict[str, Any], corpo: str) -> str:
    """Uma secção da página: cabeçalho editável, âncora e corpo.

    Sem corpo não há secção — o quadro de um ano pode não trazer, por exemplo,
    a série entre anos, e um cabeçalho sem nada por baixo seria um erro.
    """
    if not corpo:
        return ""
    cabeca = f'<h2>{_esc(seccao.get("titulo"))}</h2>'
    sub = str(seccao.get("sub") or "").strip()
    if sub:
        cabeca += f'<p class="sub">{_esc(sub)}</p>'
    return (
        f'<section class="section rem-sec" id="rem-{_esc(chave)}">'
        f'<header class="rem-sec-cabeca">{cabeca}</header>'
        f'<div class="rem-sec-corpo">{corpo}</div></section>'
    )


def _rem_indice(secoes: List[Tuple[str, str, str]]) -> str:
    """Índice das secções da página (só quando há mapa que justifique um)."""
    if len(secoes) < 3:
        return ""
    itens = "".join(
        f'<li><a href="#rem-{_esc(chave)}"><span class="num">{posicao}</span>{_esc(titulo)}</a></li>'
        for posicao, (chave, titulo, _) in enumerate(secoes, start=1)
    )
    return f'<nav class="rem-indice" aria-label="Secções do quadro"><ol>{itens}</ol></nav>'


def _rem_marca(doc: Dict[str, Any]) -> str:
    """Logótipo e imagem de capa da página (não os das definições do site)."""
    partes: List[str] = []
    logo = _media_url(doc.get("logo_id"))
    if logo:
        partes.append(
            f'<div class="rem-marca"><img src="{_esc(logo)}" '
            f'alt="{_esc(str(doc.get("title") or "Logótipo"))}"></div>'
        )
    capa = _media_url(doc.get("capa_id"))
    if capa:
        partes.append(
            f'<figure class="rem-capa"><img src="{_esc(capa)}" alt="{_esc(str(doc.get("title") or ""))}"></figure>'
        )
    return "".join(partes)


def _rem_kpis(dados: Dict[str, Any]) -> str:
    """Os números que resumem o quadro do ano."""
    contagens = dados.get("contagens") or {}
    parametros = dados.get("parametros") or {}
    cartoes = [
        ("BRAP", _rem_euros(parametros.get("brap")), f"nível 5 da TRU em {dados.get('ano')}"),
        ("Níveis da TRU", _numero(contagens.get("niveis")), "do nível 5 ao 115"),
        ("Posições remuneratórias", _numero(contagens.get("posicoes")), f"{_numero(contagens.get('carreiras'))} carreiras/categorias"),
        ("Cargos dirigentes", _numero(contagens.get("dirigentes")), "índice, nível e remuneração"),
    ]
    abertos = "".join(
        f'<div class="kpi"><span>{_esc(titulo)}</span><strong>{_esc(valor)}</strong>'
        f'<small>{_esc(nota)}</small></div>'
        for titulo, valor, nota in cartoes
        if valor
    )
    return f'<div class="kpis">{abertos}</div>' if abertos else ""


def _rem_tru(dados: Dict[str, Any]) -> str:
    """Tabela Remuneratória Única: nível, valor mensal e nota.

    São 115 linhas: quem procura um nível escreve-o na pesquisa, e o filtro
    «com/sem valor publicado» separa os níveis que o quadro não valoriza (têm
    nota em vez de valor).
    """
    niveis = [item for item in (dados.get("niveis") or []) if item.get("nivel")]
    if not niveis:
        return ""
    linhas = [
        [_numero(item.get("nivel")), _rem_euros(item.get("valor")) if item.get("valor") else "—", str(item.get("nota") or "")]
        for item in niveis
    ]
    return _tabela_filtravel(
        ["Nível", "Remuneração base mensal", "Nota"],
        linhas,
        atributos=[{"valor": "sim" if item.get("valor") else "nao"} for item in niveis],
        busca="Pesquisar por nível, valor ou nota…",
        filtros=[
            {
                "rotulo": "Remuneração",
                "atributo": "valor",
                "todos": "Todas",
                "opcoes": [("sim", "Com valor publicado"), ("nao", "Sem valor publicado")],
            }
        ],
        classe="rem-tabela rem-niveis",
        unidade="níveis",
        unidade_singular="nível",
    )


def _rem_serie(dados: Dict[str, Any]) -> str:
    """A TRU entre anos: o nível 5 (BRAP) e o último nível da tabela."""
    serie = dados.get("serie") or []
    if not serie:
        return ""
    anos = sorted({str(ano) for linha in serie for ano in (linha.get("valores") or {})})
    if len(anos) < 2:
        return ""
    ultimo = max(serie, key=lambda linha: int(linha.get("nivel") or 0))
    brap = next((linha for linha in serie if int(linha.get("nivel") or 0) == 5), None)
    linhas = []
    for ano in anos:
        brap_ano = (brap or {}).get("valores", {}).get(str(ano))
        ultimo_ano = (ultimo.get("valores") or {}).get(str(ano))
        linhas.append([ano, _rem_euros(brap_ano) if brap_ano else "—", _rem_euros(ultimo_ano) if ultimo_ano else "—"])
    pontos = [
        {"rotulo": ano, "valor": (brap or {}).get("valores", {}).get(str(ano))}
        for ano in anos
        if (brap or {}).get("valores", {}).get(str(ano))
    ]
    # Sem dois anos com BRAP publicado não há evolução para desenhar: fica a
    # tabela, em vez de barras todas a zero.
    barras = _rem_barras(pontos) if len(pontos) >= 2 else ""
    return barras + _tabela_nua(
        ["Ano", "Nível 5 (BRAP)", f"Nível {_numero(ultimo.get('nivel'))}"],
        linhas,
        classe="rem-tabela",
    )


def _rem_carreiras(dados: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """As carreiras com as suas posições remuneratórias.

    O editor escolhe quais detalhar (`destacar`): o resto fica na tabela-resumo
    (primeira posição, última posição e amplitude), que se pesquisa por carreira
    e se filtra por secção (Carreiras Gerais, Especiais, …).
    """
    carreiras = dados.get("carreiras") or []
    if not carreiras:
        return ""
    destacar = {_chave_nome(valor) for valor in (doc.get("destacar") or [])}
    linhas = [
        [
            str(item.get("carreira") or ""),
            str(item.get("categoria") or ""),
            _numero((item.get("posicoes") or [{}])[0].get("posicao")) if item.get("posicoes") else "",
            _rem_euros(item.get("minimo")),
            _rem_euros(item.get("maximo")),
            str(item.get("seccao") or ""),
        ]
        for item in carreiras
    ]
    blocos: List[str] = []
    for item in carreiras:
        chaves = {_chave_nome(item.get("carreira")), _chave_nome(item.get("categoria"))}
        if destacar and not (chaves & destacar):
            continue
        posicoes = item.get("posicoes") or []
        if not posicoes:
            continue
        barras = _rem_barras(
            [
                {
                    "rotulo": f"{posicao.get('posicao')} (nível {posicao.get('niveis_texto') or posicao.get('nivel')})",
                    "valor": posicao.get("remuneracao") or 0.0,
                }
                for posicao in posicoes
            ]
        )
        titulo = str(item.get("carreira") or "")
        if item.get("categoria") and item.get("categoria") != item.get("carreira"):
            titulo += f" · {item.get('categoria')}"
        subtitulo = " · ".join(
            parte
            for parte in (str(item.get("seccao") or ""), "posição remuneratória e remuneração base mensal")
            if parte
        )
        blocos.append(
            f'<div class="rem-carreira"><h3>{_esc(titulo)}</h3>'
            f'<p class="sub">{_esc(subtitulo)}</p>{barras}</div>'
        )
    tabela = _tabela_filtravel(
        ["Carreira", "Categoria", "1.ª posição", "Valor mínimo", "Valor máximo", "Secção"],
        linhas,
        atributos=[{"seccao": str(item.get("seccao") or "")} for item in carreiras],
        busca="Pesquisar por carreira, categoria ou valor…",
        filtros=[{"rotulo": "Secção", "atributo": "seccao", "todos": "Todas"}],
        classe="rem-tabela",
        unidade="carreiras/categorias",
        unidade_singular="carreira/categoria",
    )
    return "".join(blocos) + tabela


def _rem_dirigentes(dados: Dict[str, Any]) -> str:
    """Cargos dirigentes: âmbito, serviço, cargo, índice, nível e remuneração.

    Lista longa e heterogénea: pesquisa pelo cargo ou serviço e filtra-se por
    âmbito (universidades, polícia judiciária, …) e por grupo.
    """
    dirigentes = dados.get("dirigentes") or []
    if not dirigentes:
        return ""
    linhas = [
        [
            str(item.get("ambito") or ""),
            str(item.get("grupo") or ""),
            str(item.get("cargo") or ""),
            _numero(item.get("indice")) if item.get("indice") else "—",
            str(item.get("niveis_texto") or ""),
            _rem_euros(item.get("remuneracao")),
        ]
        for item in dirigentes
    ]
    return _tabela_filtravel(
        ["Âmbito", "Serviço", "Cargo", "Índice", "Nível da TRU", "Remuneração base"],
        linhas,
        atributos=[
            {"ambito": str(item.get("ambito") or ""), "grupo": str(item.get("grupo") or "")}
            for item in dirigentes
        ],
        busca="Pesquisar por cargo, serviço, índice ou valor…",
        filtros=[
            {"rotulo": "Âmbito", "atributo": "ambito", "todos": "Todos"},
            {"rotulo": "Grupo", "atributo": "grupo", "todos": "Todos"},
        ],
        classe="rem-tabela",
        unidade="cargos",
        unidade_singular="cargo",
    )


def _rem_simulador(dados: Dict[str, Any]) -> str:
    """Simulador da posição remuneratória (nível da TRU ou cargo dirigente).

    O valor anual são os 14 pagamentos (12 mensalidades, subsídio de férias e
    subsídio de Natal); as componentes que o quadro não publica ficam de fora e
    a nota di-lo. O título e o subtítulo da secção vêm de fora (`_rem_seccao`).
    """
    niveis = {str(item["nivel"]): item["valor"] for item in (dados.get("niveis") or []) if item.get("valor")}
    if not niveis:
        return ""
    cargos: Dict[str, float] = {}
    for registo in dados.get("dirigentes") or []:
        valor = registo.get("remuneracao")
        if not valor:
            continue
        etiqueta = " · ".join(
            str(parte) for parte in (registo.get("cargo"), registo.get("grupo"), registo.get("ambito")) if parte
        )
        if registo.get("indice"):
            etiqueta += f" (índice {registo['indice']})"
        cargos.setdefault(etiqueta, float(valor))
    opcoes = "".join(
        f'<option value="{_esc(nivel)}">{_esc(nivel)} — {_rem_euros(valor)}</option>'
        for nivel, valor in sorted(niveis.items(), key=lambda par: int(par[0]))
    )
    opcoes_cargos = "".join(
        f'<option value="{_esc(etiqueta)}">{_esc(etiqueta)} — {_rem_euros(valor)}</option>'
        for etiqueta, valor in cargos.items()
    )
    atual = next(iter(sorted(niveis, key=lambda chave: int(chave))), "")
    dados_json = _esc(json.dumps(niveis, ensure_ascii=False))
    cargos_json = _esc(json.dumps(cargos, ensure_ascii=False))
    campos = f'<label>Nível da TRU<select data-papel="nivel">{opcoes}</select></label>'
    if cargos:
        campos += f'<label>Cargo dirigente<select data-papel="cargo"><option value="">— usar o nível —</option>{opcoes_cargos}</select></label>'
    return (
        f'<div class="rem-sim" data-niveis="{dados_json}" data-cargos="{cargos_json}" data-pagamentos="{PAGAMENTOS_PUBLICO}">'
        f'<div class="campos">{campos}</div>'
        '<div class="saida">'
        f'<div><span>Remuneração base mensal</span><strong data-papel="mensal">{_rem_euros(niveis.get(atual))}</strong></div>'
        f'<div><span>Valor anual ({PAGAMENTOS_PUBLICO} pagamentos)</span><strong data-papel="anual">{_rem_euros((niveis.get(atual) or 0) * PAGAMENTOS_PUBLICO)}</strong></div>'
        '<div><span>O que está a ser simulado</span><em data-papel="origem">Nível '
        f"{_esc(atual)} da TRU</em></div>"
        "</div></div>"
        '<p class="meta">O quadro da DGAEP não publica suplementos nem subsídio de refeição: a conta é só a '
        "remuneração base do nível ou do cargo escolhido.</p>"
        "<script>(function(){var c=document.currentScript.parentNode.querySelector('.rem-sim');"
        "if(!c)return;var n=JSON.parse(c.getAttribute('data-niveis')||'{}');"
        "var g=JSON.parse(c.getAttribute('data-cargos')||'{}');"
        "var p=parseInt(c.getAttribute('data-pagamentos')||'14',10);"
        "var s=c.querySelector('[data-papel=\"nivel\"]');var k=c.querySelector('[data-papel=\"cargo\"]');"
        "var o=c.querySelector('[data-papel=\"origem\"]');"
        "function f(v){return v.toLocaleString('pt-PT',{minimumFractionDigits:2,maximumFractionDigits:2})+' \u20ac'}"
        "function u(){var v=0;if(k&&k.value){v=g[k.value]||0;if(o)o.textContent='Cargo dirigente: '+k.value}"
        "else{v=n[s.value]||0;if(o)o.textContent='Nível '+s.value+' da TRU'}"
        "c.querySelector('[data-papel=\"mensal\"]').textContent=f(v);"
        "c.querySelector('[data-papel=\"anual\"]').textContent=f(v*p)}"
        "if(s)s.addEventListener('change',function(){if(k)k.value='';u()});"
        "if(k)k.addEventListener('change',function(){u()});u()})();</script>"
    )


def _rem_notas(dados: Dict[str, Any]) -> str:
    """Notas da DGAEP por secção (recolhidas, para não haver dúvidas de leitura)."""
    notas = dados.get("notas") or []
    if not notas:
        return ""
    blocos = []
    for nota in notas:
        texto = " ".join(nota.get("texto") or [])
        if not texto:
            continue
        blocos.append(
            f'<details class="rem-notas"><summary>{_esc(nota.get("seccao"))}</summary>'
            f'<p class="meta">{_esc(texto)}</p></details>'
        )
    return "".join(blocos)


def _rem_base_legal(dados: Dict[str, Any]) -> str:
    """Base legal por carreira (estrutura da carreira, remuneratória e outras).

    As linhas vêm de nove quadros do documento: o filtro por secção é o que
    separa, por exemplo, «Carreiras Gerais» de «Cargos Dirigentes».
    """
    tabelas = dados.get("base_legal") or []
    linhas: List[List[str]] = []
    atributos: List[Dict[str, str]] = []
    for tabela in tabelas:
        seccao = str(tabela.get("seccao") or "")
        for linha in tabela.get("linhas") or []:
            linhas.append(
                [
                    str(linha.get("carreira") or ""),
                    str(linha.get("grau") or ""),
                    str(linha.get("estrutura_carreira") or ""),
                    str(linha.get("estrutura_remuneratoria") or ""),
                    str(linha.get("outras_componentes") or ""),
                ]
            )
            atributos.append({"seccao": seccao})
    return _tabela_filtravel(
        ["Carreira", "Grau", "Estrutura da carreira", "Estrutura remuneratória", "Outras componentes"],
        linhas,
        atributos=atributos,
        busca="Pesquisar por carreira, grau ou legislação…",
        filtros=[{"rotulo": "Secção", "atributo": "seccao", "todos": "Todas"}],
        classe="rem-tabela",
        unidade="linhas",
        unidade_singular="linha",
    )


def _chave_nome(texto: Any) -> str:
    """Chave de comparação de nomes (sem acentos, minúsculas, espaços colapsados)."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    limpo = "".join(caractere for caractere in base if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", limpo.lower()).strip()


def _rem_cabecalho(doc: Dict[str, Any], chave: str) -> Dict[str, str]:
    """Título e subtítulo de uma secção: o que o editor escreveu ou o do modelo."""
    seccoes = doc.get("seccoes") if isinstance(doc.get("seccoes"), dict) else {}
    atual = seccoes.get(chave) if isinstance(seccoes.get(chave), dict) else {}
    padrao = store.SECCOES_REMUNERACOES_PADRAO.get(chave) or {"titulo": "", "sub": ""}
    return {
        "titulo": str(atual.get("titulo") or padrao["titulo"]),
        "sub": str(atual.get("sub") or padrao["sub"]),
    }


def _rem_ordem(doc: Dict[str, Any]) -> List[str]:
    """Ordem das secções guardada no documento, com as que faltarem no fim."""
    guardada = doc.get("ordem") if isinstance(doc.get("ordem"), list) else []
    ordem = [str(chave) for chave in guardada if str(chave) in store.SECCOES_REMUNERACOES_IDS]
    ordem = list(dict.fromkeys(ordem))
    ordem.extend(chave for chave in store.SECCOES_REMUNERACOES_IDS if chave not in ordem)
    return ordem


def _corpo_do_modelo(dados: Dict[str, Any], doc: Dict[str, Any], *, preview: bool) -> str:
    """Marca + texto editorial + os quadros do modelo, secção a secção.

    A ordem, os cabeçalhos e o que está ligado vêm do documento; o estilo
    (`cartoes`, `plano` ou `destaque`) decide como as secções se apresentam. Os
    blocos editoriais (imagens incluídas) entram entre o índice e os quadros.
    """
    mostrar = doc.get("mostrar") if isinstance(doc.get("mostrar"), dict) else {}
    ligado = lambda chave: mostrar.get(chave, True)  # noqa: E731

    construtores = {
        "kpis": lambda: _rem_kpis(dados),
        "niveis": lambda: _rem_tru(dados),
        "serie": lambda: _rem_serie(dados),
        "carreiras": lambda: _rem_carreiras(dados, doc),
        "dirigentes": lambda: _rem_dirigentes(dados),
        "simulador": lambda: _rem_simulador(dados),
        "notas": lambda: _rem_notas(dados),
        "parametros": lambda: _rem_base_legal(dados),
    }

    seccoes: List[Tuple[str, str, str]] = []
    for chave in _rem_ordem(doc):
        if not ligado(chave):
            continue
        construtor = construtores.get(chave)
        if construtor is None:
            continue
        cabecalho = _rem_cabecalho(doc, chave)
        html = _rem_seccao(chave, cabecalho, construtor())
        if html:
            seccoes.append((chave, cabecalho["titulo"], html))

    estilo = str(doc.get("estilo") or "")
    if estilo not in store.ESTILOS_REMUNERACOES_IDS:
        estilo = store.ESTILO_REMUNERACOES_PADRAO

    partes: List[str] = []
    if doc.get("intro"):
        partes.append(f'<div class="section prose">{_md(str(doc["intro"]))}</div>')
    partes.append(_rem_indice(seccoes))
    partes.append(blocks_to_html(doc.get("blocks") or [], preview=preview))
    partes.extend(html for _, _, html in seccoes)

    fonte = dados.get("fonte") or {}
    if fonte.get("documento"):
        nota = f"{fonte['documento']} · {fonte.get('ficheiro') or ''}".strip(" ·")
        recolhido = _date(dados.get("gerado_em")) if dados.get("gerado_em") else ""
        if recolhido:
            nota += f" · valores lidos a {recolhido}"
        partes.append(f'<div class="section aviso">{_esc(nota)}</div>')
    corpo = _garantir_h1("".join(parte for parte in partes if parte), _titulo_visivel(doc))
    # A pesquisa das tabelas é um só script, no fim: tem de vir depois delas.
    if "data-tabela-filtro" in corpo:
        corpo += _JS_FILTROS_TABELAS
    return f'<div class="rem-pagina rem-estilo-{_esc(estilo)}">{_rem_marca(doc)}{corpo}</div>'


def render_remuneracao(
    doc: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Página pública do modelo de remunerações da Administração Pública."""
    settings = settings or store.get_settings()
    seo = doc.get("seo") or {}
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    titulo = str(doc.get("title") or "Remunerações da Administração Pública")
    path = f"/site/remuneracoes/{doc.get('slug')}" if doc.get("slug") else "/site"
    base_url = str(settings.get("base_url") or "")
    parametros = dados.get("parametros") or {}
    contagens = dados.get("contagens") or {}
    descricao = str(seo.get("description") or doc.get("excerpt") or "").strip() or (
        f"Remunerações da Administração Pública em {dados.get('ano')}: Tabela Remuneratória Única "
        f"({_numero(contagens.get('niveis'))} níveis, BRAP de {_euros(parametros.get('brap'))}), "
        f"carreiras e posições remuneratórias e cargos dirigentes, a partir do quadro da DGAEP."
    )
    cor = str(doc.get("cor") or "").strip()
    extra_css = _CSS_REMUNERACOES + (f":root {{ --accent: {cor}; }}" if cor else "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": str(seo.get("title") or titulo),
        "description": descricao,
        "url": _absolute(path, base_url),
        "spatialCoverage": {"@type": "Place", "name": "Portugal"},
        "creator": {"@type": "Organization", "name": str(settings.get("site_name") or "")},
        "isBasedOn": [url for url in [(dados.get("fonte") or {}).get("url"), (dados.get("fonte") or {}).get("catalogo")] if url],
        "variableMeasured": "Remuneração base mensal por nível e posição remuneratória",
    }
    if dados.get("ano"):
        json_ld["temporalCoverage"] = str(dados.get("ano"))
    return _layout(
        title=str(seo.get("title") or titulo),
        description=descricao,
        body=_corpo_do_modelo(dados, doc, preview=preview),
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id") or doc.get("capa_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        extra_css=extra_css,
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Remunerações AP"},
            {"label": titulo},
        ],
    )


def _post_card(post: Dict[str, Any]) -> str:
    href = f"/site/blog/{post.get('slug')}"
    cover = _media_url(post.get("cover_id"))
    image = f'<img src="{_esc(cover)}" alt="" loading="lazy" decoding="async">' if cover else ""
    category = ""
    return (
        f'<article class="card post-card">{image}<div class="body">'
        + (f'<span class="pill">{_esc(post.get("category"))}</span>' if post.get("category") else "")
        # `h2`: o título do artigo é o primeiro nível abaixo do título da página
        # (com `h3` havia um salto de nível e a lista não tinha cabeçalho próprio).
        + f'<h2><a href="{_esc(href)}">{_esc(post.get("title"))}</a></h2>'
        + f'<p>{_esc(post.get("excerpt") or _plain_excerpt(post))}</p>'
        + '<div class="meta">'
        + (f"<span>{_esc(_date(post.get('published_at')))}</span>" if post.get("published_at") else "")
        + (f"<span>{int(post.get('reading_minutes') or 1)} min de leitura</span>" if post.get("reading_minutes") else "")
        + "</div></div></article>"
    )


def _posts_with_meta(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    categories = {item.get("id"): item.get("name") for item in store.taxonomy()["categories"]}
    enriched = []
    for post in posts:
        item = dict(post)
        names = [categories.get(cid) for cid in (post.get("category_ids") or [])]
        item["category"] = ", ".join(name for name in names if name)
        enriched.append(item)
    return enriched


def _acoes_do_artigo(post: Dict[str, Any], path: str, settings: Dict[str, Any], *, preview: bool) -> str:
    """Ações do artigo: descarregar o relatório (PDF) e partilhar.

    Valem só no site: num rascunho (pré-visualização) o artigo ainda não está
    publicado, a rota do relatório não o serve e não há endereço público para
    partilhar. O PDF é opcional por artigo (`report_pdf`) — um texto sem números
    próprios não ganha um botão que descarrega o que já está à vista. A partilha
    usa a Web Share API do sistema e, onde ela não existe, copia o endereço;
    sem nenhuma das duas o botão não chega a aparecer.
    """
    if preview:
        return ""
    botoes = []
    if post.get("report_pdf", True):
        botoes.append(f'<a class="btn ghost" href="{_esc(path)}/pdf" download>Descarregar o relatório (PDF)</a>')
    botoes.append(
        # Nasce escondido: quem o mostra é o script, que é quem sabe se este
        # browser partilha ou copia. Um botão que não faz nada é pior do que
        # nenhum — e sem JavaScript a página continua legível.
        '<button type="button" class="btn ghost" data-partilhar hidden'
        f' data-url="{_esc(_absolute(path, str(settings.get("base_url") or "")))}"'
        f' data-titulo="{_esc(post.get("title") or "")}">Partilhar</button>'
    )
    return (
        f'<div class="artigo-acao">{"".join(botoes)}</div>'
        # O script fica ao lado do que comanda: `currentScript.parentNode` é o
        # artigo, e não é preciso procurar o botão no documento todo.
        "<script>(function(){"
        "var b=document.currentScript.parentNode.querySelector('[data-partilhar]');if(!b)return;"
        "var u=b.getAttribute('data-url')||location.href;"
        "var t=b.getAttribute('data-titulo')||document.title;var r=b.textContent;"
        "var c=navigator.clipboard&&navigator.clipboard.writeText;"
        "if(!navigator.share&&!c)return;b.hidden=false;"
        "function dito(m){b.textContent=m;setTimeout(function(){b.textContent=r},2400)}"
        "b.addEventListener('click',function(){"
        "if(navigator.share){navigator.share({title:t,url:u}).catch(function(){});return;}"
        "navigator.clipboard.writeText(u).then(function(){dito('Ligação copiada')},"
        "function(){dito('Não foi possível copiar')});});"
        "})();</script>"
    )


def render_post(post: Dict[str, Any], *, preview: bool = False, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    seo = post.get("seo") or {}
    categorias = store.taxonomy()["categories"]
    por_id = {item.get("id"): item for item in categorias}
    names = [str((por_id.get(cid) or {}).get("name") or "") for cid in (post.get("category_ids") or [])]
    names = [name for name in names if name]
    cover = _media_url(post.get("cover_id"))
    hero = ""
    if cover:
        hero = f'<figure><img src="{_esc(cover)}" alt="" ></figure>'
    tags = "".join(f'<a class="pill" href="/site/etiqueta/{quote(tag)}">{_esc(tag)}</a> ' for tag in (post.get("tags") or []))
    meta_bits = []
    if post.get("author"):
        meta_bits.append(f'<span>{_esc(post.get("author"))}</span>')
    if post.get("published_at"):
        meta_bits.append(f'<span>{_esc(_date(post.get("published_at")))}</span>')
    if post.get("reading_minutes"):
        meta_bits.append(f"<span>{int(post['reading_minutes'])} min de leitura</span>")
    for name in names:
        meta_bits.append(f'<span class="pill">{_esc(name)}</span>')
    path = f"/site/blog/{post.get('slug')}"
    acoes = _acoes_do_artigo(post, path, settings, preview=preview)
    body = (
        '<article class="section">'
        f'<h1>{_esc(post.get("title"))}</h1>'
        f'<div class="meta">{"".join(meta_bits)}</div>'
        f'{acoes}'
        f'{hero}'
        f'<div class="prose">{_md(str(post.get("markdown") or ""))}</div>'
        + blocks_to_html(post.get("blocks") or [], preview=preview)
        + (f'<div class="meta" style="margin-top:22px">{tags}</div>' if tags else "")
        + "</article>"
    )
    base_url = str(settings.get("base_url") or "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.get("title"),
        "description": post.get("excerpt") or _plain_excerpt(post),
        "datePublished": post.get("published_at"),
        "dateModified": post.get("updated_at") or post.get("published_at"),
        "author": {"@type": "Organization" if not post.get("author") else "Person", "name": post.get("author") or settings.get("site_name")},
        "publisher": {"@type": "Organization", "name": settings.get("site_name")},
        "mainEntityOfPage": _absolute(path, base_url),
        "url": _absolute(path, base_url),
    }
    if cover:
        json_ld["image"] = _absolute(cover, base_url)
    trilha: List[Dict[str, str]] = [
        {"label": "Início", "href": "/site"},
        {"label": "Blog", "href": "/site/blog"},
    ]
    primeira = next((item for item in categorias if item.get("name") == names[0]), None) if names else None
    if primeira and primeira.get("slug"):
        trilha.append({"label": names[0], "href": f"/site/categoria/{primeira['slug']}"})
    trilha.append({"label": str(post.get("title") or "")})
    return _layout(
        title=str(seo.get("title") or post.get("title") or ""),
        description=str(seo.get("description") or post.get("excerpt") or _plain_excerpt(post)),
        body=body,
        current_path=path,
        settings=settings,
        canonical=path,
        og_type="article",
        og_image=_media_url(seo.get("image_id")) or cover,
        keywords=(seo.get("keywords") or post.get("tags") or None),
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=trilha,
    )


# --------------------------------------------------------------------------
# Pesquisa do site
# --------------------------------------------------------------------------
def _seccao_dos_estudos(pages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Página-mãe dos estudos de benchmark (a que os estudos têm por ascendente).

    Sai da própria árvore de páginas — não há caminho escrito à mão — e sem
    estudos publicados não há grupo nenhum para mostrar.
    """
    por_id = {str(page.get("id")): page for page in pages}
    for page in pages:
        mae = por_id.get(str(page.get("parent_id") or ""))
        if mae and _chave_nome(mae.get("slug")) == "benchmarks":
            return mae
    return None


def _resultados_da_pesquisa(termo: str, *, limite: int = 40) -> List[Dict[str, Any]]:
    """Resultados agrupados: estudos de benchmark, páginas, artigos e relatórios.

    Só entra o que está publicado (`published_pages`/`published_posts` e a
    biblioteca pública), e a comparação ignora acentos e maiúsculas: quem escreve
    «telemoveis» encontra «Telemóveis».
    """
    agulha = _chave_nome(termo)
    if not agulha:
        return []

    pages = store.published_pages()
    secao = _seccao_dos_estudos(pages)
    estudos: List[Dict[str, str]] = []
    paginas: List[Dict[str, str]] = []
    for page in pages:
        if agulha not in _chave_nome(
            " ".join([str(page.get("title") or ""), str(page.get("excerpt") or ""), str(page.get("path") or "")])
        ):
            continue
        caminho = str(page.get("path") or "").strip("/")
        achado = {
            "title": str(page.get("title") or ""),
            "href": f"/site/{caminho}" if caminho else "/site",
            "text": str(page.get("excerpt") or ""),
        }
        if secao is not None and str(page.get("parent_id") or "") == str(secao.get("id")):
            estudos.append(achado)
        else:
            paginas.append(achado)

    artigos = [
        {
            "title": str(post.get("title") or ""),
            "href": f"/site/blog/{post.get('slug')}",
            "text": str(post.get("excerpt") or ""),
        }
        for post in store.published_posts()
        if agulha
        in _chave_nome(
            " ".join([str(post.get("title") or ""), str(post.get("excerpt") or ""), str(post.get("markdown") or "")])
        )
    ]

    from api import reports_library  # noqa: PLC0415 - import tardio: a loja é grande

    relatorios = [
        {
            "title": str(item["title"]),
            "href": str(item.get("download") or item.get("href") or "/reports"),
            "text": str(item.get("subtitle") or item.get("note") or ""),
        }
        for item in reports_library.items()
        if agulha
        in _chave_nome(
            " ".join([item["title"], item["subtitle"], item["note"], item["area_label"], " ".join(item["tags"])])
        )
    ]

    def ordem(item: Dict[str, str]) -> Tuple[bool, str]:
        """O que casa no título vem primeiro; dentro disso, por título."""
        return (agulha not in _chave_nome(item["title"]), _chave_nome(item["title"]))

    grupos: List[Dict[str, Any]] = []
    for rotulo, achados in (
        ("Estudos de benchmark", estudos),
        ("Páginas", paginas),
        ("Artigos do blog", artigos),
        ("Relatórios e documentos", relatorios),
    ):
        if not achados:
            continue
        achados.sort(key=ordem)
        grupos.append({"label": rotulo, "items": achados[:limite]})
    return grupos


def render_search(query: str = "", *, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página de resultados da pesquisa do site (`/site/pesquisa?q=`)."""
    settings = settings or store.get_settings()
    termo = " ".join(str(query or "").split())
    grupos = _resultados_da_pesquisa(termo)
    total = sum(len(grupo["items"]) for grupo in grupos)

    if not termo:
        resumo = (
            '<p class="lead">Escreva o que procura: encontra páginas do site, artigos do blog, '
            "estudos de benchmark e relatórios publicados.</p>"
        )
    elif total:
        resumo = f'<p class="library-count">{total} resultado(s) para «{_esc(termo)}».</p>'
    else:
        resumo = (
            f'<p class="lead">Não encontrámos nada para «{_esc(termo)}». Tente outra palavra, veja o '
            '<a href="/site/blog">blog</a> ou os <a href="/site/relatorios-gratuitos">relatórios</a>.</p>'
        )

    secoes = "".join(
        f'<section class="section"><h2>{_esc(grupo["label"])}</h2><div class="cards">'
        + "".join(
            f'<article class="card"><h3><a href="{_esc(item["href"])}">{_esc(item["title"])}</a></h3>'
            + (f'<p>{_esc(item["text"])}</p>' if item["text"] else "")
            + "</article>"
            for item in grupo["items"]
        )
        + "</div></section>"
        for grupo in grupos
    )
    body = (
        '<section class="section"><h1>Pesquisar no site</h1>'
        + _form_de_pesquisa(termo)
        + resumo
        + "</section>"
        + secoes
    )
    return _layout(
        title="Pesquisar no site",
        description=(
            "Pesquisa no site: páginas, artigos do blog, estudos de benchmark e relatórios publicados "
            "a partir de dados abertos."
        ),
        body=body,
        current_path="/site/pesquisa",
        settings=settings,
        canonical="/site/pesquisa",
        noindex=True,
        breadcrumb=[{"label": "Início", "href": "/site"}, {"label": "Pesquisar"}],
    )


def render_blog(
    *,
    page_no: int = 1,
    category: Optional[Dict[str, Any]] = None,
    tag: Optional[str] = None,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    settings = settings or store.get_settings()
    per_page = int(settings.get("posts_per_page") or 9)
    posts = store.published_posts(
        category_id=str(category.get("id")) if category else None,
        tag=tag,
    )
    total_pages = max(1, (len(posts) + per_page - 1) // per_page)
    page_no = max(1, min(page_no, total_pages))
    window = _posts_with_meta(posts[(page_no - 1) * per_page : page_no * per_page])

    if category:
        title = f'Blog · {category.get("name")}'
    elif tag:
        title = f"Blog · {tag}"
    else:
        title = "Blog"
    intro = str((category or {}).get("description") or "") or (
        f"Artigos com a etiqueta «{tag}»." if tag else "Análises, método e novidades da plataforma."
    )

    base_path = "/site/blog"
    if category:
        base_path = f"/site/categoria/{category.get('slug')}"
    elif tag:
        base_path = f"/site/etiqueta/{quote(tag)}"

    taxonomy = store.taxonomy()
    filters = ""
    if taxonomy["categories"] or taxonomy["tags"]:
        chips = [
            f'<a class="pill" href="/site/categoria/{_esc(item.get("slug"))}">{_esc(item.get("name"))} · {item.get("posts")}</a>'
            for item in taxonomy["categories"]
        ]
        chips += [
            f'<a class="pill" href="/site/etiqueta/{quote(item.get("tag"))}">{_esc(item.get("tag"))} · {item.get("posts")}</a>'
            for item in taxonomy["tags"][:12]
        ]
        filters = f'<div class="meta" style="flex-wrap:wrap;gap:8px">{ " ".join(chips) }</div>'

    if window:
        cards = f'<div class="posts">{"".join(_post_card(post) for post in window)}</div>'
    else:
        cards = '<p class="lead">Ainda não há artigos publicados.</p>'

    pager = ""
    if total_pages > 1:
        links = []
        for number in range(1, total_pages + 1):
            href = base_path + (f"?page={number}" if number > 1 else "")
            if number == page_no:
                links.append(f"<span class=\"current\">{number}</span>")
            else:
                links.append(f'<a href="{_esc(href)}">{number}</a>')
        pager = f'<div class="pager">{"".join(links)}</div>'

    body = (
        f'<section class="section"><h1>{_esc(title)}</h1><p class="lead">{_esc(intro)}</p>{filters}</section>'
        f'<section class="section">{cards}</section>{pager}'
    )
    path = base_path + (f"?page={page_no}" if page_no > 1 else "")
    trilha: List[Dict[str, str]] = [{"label": "Início", "href": "/site"}]
    if category or tag:
        trilha.append({"label": "Blog", "href": "/site/blog"})
        trilha.append({"label": str((category or {}).get("name") or tag or "")})
    else:
        trilha.append({"label": "Blog"})
    return _layout(
        title=title,
        description=str((category or {}).get("description") or intro),
        body=body,
        current_path=path,
        settings=settings,
        canonical=base_path if page_no == 1 else base_path,
        preview=preview,
        breadcrumb=trilha,
    )


def render_index(*, preview: bool = False, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página de entrada quando ainda não há página inicial definida."""
    settings = settings or store.get_settings()
    pages = store.published_pages()
    posts = _posts_with_meta(store.published_posts(limit=6))
    tiles = "".join(
        f'<div class="tile"><h3><a href="/site/{_esc(page.get("path"))}">{_esc(page.get("title"))}</a></h3>'
        f'<p>{_esc(page.get("excerpt") or "")}</p></div>'
        for page in pages
        if page.get("path")
    )
    body = (
        f'<section class="section hero"><h1>{_esc(settings.get("site_name"))}</h1>'
        f'<p class="lead">{_esc(settings.get("description"))}</p></section>'
        + (f'<section class="section"><h2>Páginas</h2><div class="grelha">{tiles}</div></section>' if tiles else "")
        + f'<section class="section"><h2>Blog</h2><div class="posts">{"".join(_post_card(post) for post in posts)}</div></section>'
    )
    return _layout(
        title=str(settings.get("site_name") or "Site"),
        description=str(settings.get("description") or ""),
        body=body,
        current_path="/site",
        settings=settings,
        preview=preview,
    )


#: Ilustrações das páginas de sistema. São embutidas no HTML (e não pedidas por
#: `src`): a página «sem ligação» tem de aparecer sem rede nenhuma, e assim não
#: depende de cache nem de um pedido que falharia.
_ILUSTRACOES_DE_SISTEMA: Dict[str, str] = {
    "nao-encontrada": "ilustracao-pagina-nao-encontrada.svg",
    "erro-interno": "ilustracao-erro-interno.svg",
    "sem-ligacao": "ilustracao-sem-ligacao.svg",
}

#: Destinos que valem a pena em qualquer página de sistema: o que a plataforma
#: faz, o que se pode ler já e como falar com quem a mantém.
_DESTINOS_UTEIS: Tuple[Tuple[str, str, str], ...] = (
    ("/site/solucoes", "Soluções", "as áreas de trabalho e o que cada uma responde"),
    ("/site/relatorios-gratuitos", "Relatórios", "documentos prontos a descarregar, sem custo"),
    ("/site/fontes", "Fontes", "de onde vem cada número e com que cobertura"),
    ("/site/blog", "Blog", "análises e notas de método"),
    ("/site/contactos", "Contactos", "falar com quem faz"),
)


@functools.lru_cache(maxsize=8)
def _ilustracao_de_sistema(nome: str) -> str:
    """Markup de uma ilustração de `site_assets` (vazio se o ficheiro faltar)."""
    caminho = store.SITE_ASSETS_DIR / nome
    try:
        return caminho.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Ilustração de sistema em falta: %s", caminho)
        return ""


def _pagina_de_sistema(
    *,
    etiqueta: str,
    titulo: str,
    lead: str,
    nota: str,
    ilustracao: str,
    legenda: str,
    acoes: str = "",
    com_pesquisa: bool = False,
) -> str:
    """Corpo partilhado das páginas de sistema.

    Todas dizem o mesmo em três tempos: o que aconteceu, o que se pode fazer
    agora (as ações e, quando faz sentido, a pesquisa) e o que é a plataforma.
    A `nota` é onde entra o humor — seco, do lado dos dados, sem troçar de quem
    chegou aqui.
    """
    imagem = _ilustracao_de_sistema(ilustracao)
    # Sem o ficheiro da ilustração, a legenda continua a explicar o que se passa.
    alternativa = f'<p class="card">{_esc(legenda)}</p>'
    figura = (
        '<figure class="sistema-imagem">'
        f"{imagem or alternativa}"
        f"<figcaption>{_esc(legenda)}</figcaption></figure>"
    )
    destinos = "".join(
        f'<li><a href="{_esc(href)}">{_esc(rotulo)}</a><span>{_esc(descricao)}</span></li>'
        for href, rotulo, descricao in _DESTINOS_UTEIS
    )
    return (
        '<section class="section sistema">'
        '<div class="sistema-texto">'
        f'<p class="sistema-etiqueta">{_esc(etiqueta)}</p>'
        f"<h1>{_esc(titulo)}</h1>"
        f'<p class="lead">{_esc(lead)}</p>'
        f'<p class="sistema-nota">{_esc(nota)}</p>'
        + (f'<div class="actions">{acoes}</div>' if acoes else "")
        + (_form_de_pesquisa() if com_pesquisa else "")
        + "</div>"
        + figura
        + "</section>"
        + '<section class="section sistema-plataforma">'
        "<h2>O que é o Sabemos Studio</h2>"
        "<p>Contratos públicos, empresas, municípios e mercados — a partir de fontes públicas, "
        "com a origem de cada número à vista. O site mostra o que está publicado; a plataforma "
        "responde às perguntas que se fazem por cima disso.</p>"
        f'<ul class="sistema-links">{destinos}</ul>'
        "</section>"
    )


def render_not_found(*, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página 404: endereço que não existe (ou que mudou de sítio)."""
    settings = settings or store.get_settings()
    body = _pagina_de_sistema(
        etiqueta="Erro 404 · endereço não encontrado",
        titulo="Este endereço não consta do cadastro",
        lead="A página que pediu não existe — ou mudou de sítio e ficou um link a apontar para o vazio.",
        nota="Procurámos duas vezes. Ao contrário de um contrato com aditivos, este caminho não "
        "tem versão anterior para consultar. Se chegou aqui por um link nosso, diga qual: "
        "gostamos de saber onde é que os links se perdem.",
        ilustracao=_ILUSTRACOES_DE_SISTEMA["nao-encontrada"],
        legenda="Lupa sobre o registo de páginas: o endereço pedido não está lá.",
        acoes=(
            '<a class="btn" href="/site">Ir para o início</a>'
            '<a class="btn ghost" href="/site/contactos">Reportar o link</a>'
        ),
        com_pesquisa=True,
    )
    return _layout(
        title="Página não encontrada",
        description="Conteúdo inexistente ou não publicado.",
        body=body,
        current_path="/site/404",
        settings=settings,
        breadcrumb=[{"label": "Início", "href": "/site"}, {"label": "Página não encontrada"}],
        noindex=True,
    )


def render_erro_interno(*, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página 500: falha do lado do serviço (não do utilizador)."""
    settings = settings or store.get_settings()
    body = _pagina_de_sistema(
        etiqueta="Erro 500 · falha do serviço",
        titulo="Falhou do nosso lado, não do seu",
        lead="Alguma coisa correu mal a montar esta página. O pedido chegou, a resposta é que não.",
        nota="Fica no registo do servidor, com hora e tudo — tratamos disto como qualquer "
        "inconsistência nos dados: primeiro perceber, depois corrigir. Os números continuam "
        "guardados: uma falha na montra não estraga o arquivo.",
        ilustracao=_ILUSTRACOES_DE_SISTEMA["erro-interno"],
        legenda="Painel do serviço com uma peça solta e a placa de aviso à vista.",
        acoes=(
            '<a class="btn" href="/site">Voltar ao início</a>'
            '<a class="btn ghost" href="/site/contactos">Dizer o que se passou</a>'
        ),
    )
    return _layout(
        title="Erro do serviço",
        description="Falha interna ao servir a página.",
        body=body,
        current_path="/site/erro",
        settings=settings,
        breadcrumb=[{"label": "Início", "href": "/site"}, {"label": "Erro do serviço"}],
        noindex=True,
    )


# --------------------------------------------------------------------------
# RSS, sitemap e robots
# --------------------------------------------------------------------------
def render_rss(settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base_url = str(settings.get("base_url") or "").rstrip("/")
    posts = store.published_posts(limit=50)
    items = []
    for post in posts:
        link = _absolute(f"/site/blog/{post.get('slug')}", base_url)
        items.append(
            "<item>"
            f"<title>{_esc(post.get('title'))}</title>"
            f"<link>{_esc(link)}</link>"
            f"<guid isPermaLink=\"true\">{_esc(link)}</guid>"
            + (f"<pubDate>{_esc(_rfc822(post.get('published_at')))}</pubDate>" if post.get("published_at") else "")
            + f"<description>{_esc(post.get('excerpt') or _plain_excerpt(post))}</description>"
            + "".join(f"<category>{_esc(tag)}</category>" for tag in (post.get("tags") or []))
            + "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{_esc(settings.get('site_name'))}</title>"
        f"<link>{_esc(base_url or '/site')}</link>"
        f"<description>{_esc(settings.get('description'))}</description>"
        f"<language>{_esc(str(settings.get('language') or 'pt-PT'))}</language>"
        + (f'<atom:link href="{_esc(_absolute("/site/rss.xml", base_url))}" rel="self" type="application/rss+xml"/>' if base_url else "")
        + "".join(items)
        + "</channel></rss>"
    )


def _rfc822(value: Optional[str]) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def render_sitemap(settings: Optional[Dict[str, Any]] = None) -> str:
    """Sitemap do site: **tudo** o que está publicado em `/site/…`.

    Páginas do CMS, artigos e índice do blog, municípios, páginas de pesquisa de
    dados, remunerações e estudos de benchmark publicados. Um endereço entra uma
    só vez, mesmo quando duas regras o pedem — `/site/blog` é uma página do CMS
    *e* o índice do blog, e `<loc>` repetido é um aviso no Search Console.
    """
    settings = settings or store.get_settings()
    # Sem `base_url` configurado os `<loc>` sairiam relativos, e um sitemap com
    # endereços relativos é inválido (o motor de busca rejeita-o por inteiro).
    base_url = str(settings.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    # `loc` → (lastmod, prioridade). Quando duas regras apontam para o mesmo
    # endereço fica a de maior prioridade (e o `lastmod` dela).
    entradas: Dict[str, Tuple[str, float]] = {}

    def juntar(caminho: str, lastmod: str, prioridade: float) -> None:
        loc = _absolute(caminho, base_url)
        anterior = entradas.get(loc)
        if anterior and anterior[1] >= prioridade:
            return
        entradas[loc] = (lastmod, prioridade)

    for page in store.published_pages():
        if (page.get("seo") or {}).get("noindex"):
            continue
        juntar(_caminho_da_pagina(page), str(page.get("updated_at") or "")[:10], 0.9)
    juntar("/site/blog", "", 0.8)
    for municipio in store.published_municipios():
        if (municipio.get("seo") or {}).get("noindex"):
            continue
        slug = str(municipio.get("slug") or "")
        if not slug:
            continue
        juntar(
            f"/site/municipio/{slug}",
            str(municipio.get("updated_at") or municipio.get("published_at") or "")[:10],
            0.8,
        )
    for post in store.published_posts(limit=500):
        if (post.get("seo") or {}).get("noindex"):
            continue
        juntar(
            f"/site/blog/{post.get('slug')}",
            str(post.get("updated_at") or post.get("published_at") or "")[:10],
            0.7,
        )
    for pesquisa in store.published_pesquisas():
        if (pesquisa.get("seo") or {}).get("noindex"):
            continue
        slug = str(pesquisa.get("slug") or "")
        if not slug:
            continue
        juntar(
            f"/site/pesquisa/{slug}",
            str(pesquisa.get("updated_at") or pesquisa.get("published_at") or "")[:10],
            0.8,
        )
    for remuneracao in store.published_remuneracoes():
        if (remuneracao.get("seo") or {}).get("noindex"):
            continue
        slug = str(remuneracao.get("slug") or "")
        if not slug:
            continue
        juntar(
            f"/site/remuneracoes/{slug}",
            str(remuneracao.get("updated_at") or remuneracao.get("published_at") or "")[:10],
            0.8,
        )
    # Estudos de benchmark publicados: a página do estudo entra aqui por ser uma
    # página do CMS; a versão com a pesquisa agregada tem endereço próprio
    # (`/site/benchmarks/<slug>/pesquisa`) e também é pública — ficava de fora.
    try:
        from api import benchmarks_store  # noqa: PLC0415 - import tardio: ciclo

        for benchmark in benchmarks_store.publicos():
            slug = str(benchmark.get("slug") or "")
            if slug:
                juntar(f"/site/benchmarks/{slug}/pesquisa", str(benchmark.get("public_at") or "")[:10], 0.6)
    except Exception:  # noqa: BLE001 - o sitemap do site não pode cair por causa dos benchmarks
        logger.warning("Sitemap do site: não foi possível ler os benchmarks publicados", exc_info=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(
            f"<url><loc>{_esc(loc)}</loc>"
            + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
            + f"<priority>{prioridade:.1f}</priority></url>"
            for loc, (lastmod, prioridade) in entradas.items()
        )
        + "</urlset>"
    )


def render_robots(settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base_url = str(settings.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /site/",
        "Disallow: /cms/",
        "",
    ]
    if base_url:
        lines.append(f"Sitemap: {base_url}/site/sitemap.xml")
    return "\n".join(lines) + "\n"
