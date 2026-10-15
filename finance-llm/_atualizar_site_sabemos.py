"""Publica o site do «Sabemos Studio» numa instalação em uso.

O deploy de código **não** envia a pasta `data/`, por isso o CMS de uma
instalação antiga (produção incluída) não recebe nem as imagens de marca nem o
conteúdo novo. Isto aplica as duas coisas pela API do próprio `cms_store`, para
as alterações ficarem com revisão e atividade, como se tivessem sido feitas no
CMS.

    python _atualizar_site_sabemos.py

Pode ser corrido mais de uma vez: as imagens não duplicam, as páginas que já
estejam iguais não voltam a ser gravadas e os menus não ganham itens repetidos.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from api import cms_editorial as editorial
from api import cms_store as store

AUTOR = "migracao@sabemos.studio"
BASE_URL = "https://sabemos.studio"


def _alterados(atual: Dict[str, Any], novo: Dict[str, Any]) -> List[str]:
    """Campos de `novo` que diferem de `atual`, ignorando o que o `_normalise` acrescenta."""
    return [chave for chave, valor in novo.items() if _comparavel(atual.get(chave)) != _comparavel(valor)]


def _comparavel(valor: Any) -> Any:
    """Versão comparável de um valor, sem os `hidden: false` que o `_normalise`
    põe em todos os blocos — sem isto a página era regravada a cada execução."""
    if isinstance(valor, list):
        return [_comparavel(item) for item in valor]
    if isinstance(valor, dict):
        return {chave: _comparavel(item) for chave, item in valor.items() if not (chave == "hidden" and not item)}
    return valor


def _aplicar_pagina(page_id: str, campos: Dict[str, Any]) -> str:
    """Guarda uma página (se algo mudou) e devolve o id com que ficou na loja."""
    try:
        atual = store.get_item("pages", page_id)
    except KeyError:
        atual = {}
        campos = {**campos, "status": "publicado"}
    if atual and not _alterados(atual, campos):
        print(f"  página {page_id}: já estava atualizada")
        return str(atual["id"])
    guardada = store.save_item("pages", {**atual, **campos}, AUTOR)
    print(f"  página {guardada['id']}: gravada ({len(campos.get('blocks') or [])} blocos)")
    return str(guardada["id"])


def _pagina_por_caminho(caminho: str) -> Optional[Dict[str, Any]]:
    for pagina in store.list_items("pages")["items"]:
        if str(pagina.get("path") or "") == caminho:
            return pagina
    return None


def _localizar_pagina(caminho: str, page_id: str, slug: str) -> Optional[Dict[str, Any]]:
    """Página já instalada: pelo caminho, pelo id declarado ou pelo `slug`.

    O `slug` de cada página tem de ser único no CMS, e o caminho é montado a
    partir da hierarquia — por isso procurar só pelo caminho, numa segunda
    passagem, criava uma página nova ao lado da que já existia.
    """
    paginas = store.list_items("pages")["items"]
    for campo, valor in (("path", caminho), ("id", page_id), ("slug", slug)):
        for pagina in paginas:
            if str(pagina.get(campo) or "") == valor:
                return pagina
    return None


def _aplicar_paginas_do_site(media: Dict[str, str]) -> None:
    """Cria/actualiza as páginas de soluções, fontes e contactos.

    O `parent_id` do editorial é **simbólico** (o `pag_solucoes` só existe na
    semente): aqui traduz-se para o id real da instalação, senão as páginas
    filhas ficavam sem ascendente e o caminho público perdia o prefixo.
    """
    ids_reais: Dict[str, str] = {}
    for pagina in editorial.paginas_do_site(media):
        existente = _localizar_pagina(str(pagina["path"]), str(pagina["id"]), str(pagina["slug"]))
        page_id = str(existente["id"]) if existente else str(pagina["id"])
        campos = {chave: valor for chave, valor in pagina.items() if chave != "id"}
        pai = campos.get("parent_id")
        if pai:
            campos["parent_id"] = ids_reais.get(str(pai), pai)
        ids_reais[str(pagina["id"])] = _aplicar_pagina(page_id, campos)


def _aplicar_menus() -> None:
    """Reconstrói os menus a partir da ordem editorial, sem perder itens próprios."""
    for localizacao, nome in (("header", "Menu principal"), ("footer", "Menu de rodapé")):
        desejados = store.itens_de_menu(localizacao)
        pagina_por_id = {str(item.get("page_id")): item.get("label") for item in desejados}
        menu = next((item for item in store.list_menus() if item.get("location") == localizacao), None)
        if menu is None:
            store.save_item("menus", {"name": nome, "location": localizacao, "items": desejados}, AUTOR)
            print(f"  menu {localizacao}: criado com {len(desejados)} itens")
            continue
        atuais = menu.get("items") or []
        # Itens que já existem e não estão na ordem editorial (ex.: uma página
        # própria, como «Benchmarks» numa instalação que a tenha criado) ficam
        # no fim, para a migração não apagar trabalho de ninguém. Links directos
        # também são comparados pela assinatura, por isso ajustam-se automaticamente.
        extras = [item for item in atuais if str(item.get("page_id") or "") not in pagina_por_id]
        items = desejados + extras
        if _comparavel([_assinatura(item) for item in atuais]) == _comparavel([_assinatura(item) for item in items]):
            print(f"  menu {localizacao}: já estava atualizado")
            continue
        store.save_item("menus", {**menu, "items": items}, AUTOR)
        print(f"  menu {localizacao}: {len(items)} itens")


def _assinatura(item: Dict[str, Any]) -> Dict[str, Any]:
    """O que identifica um item de menu (o `id` é gerado a cada reconstrução)."""
    return {
        "label": item.get("label"),
        "href": item.get("href"),
        "page_id": item.get("page_id"),
        "new_tab": bool(item.get("new_tab")),
    }


def _aplicar_posts(media: Dict[str, str]) -> None:
    """Põe capa nos artigos de exemplo e acerta o nome da equipa autora."""
    campos_por_slug: Dict[str, Dict[str, Any]] = {
        "bem-vindo-ao-blog": {
            "cover_id": media.get("capa-post-bemvindo.svg"),
            "title": "Bem-vindo ao blog do Sabemos Studio",
        },
        "contratos-publicos-2026": {
            "cover_id": media.get("capa-post-contratos-2026.svg"),
        },
    }
    for slug, campos in campos_por_slug.items():
        post = store.resolve_post_by_slug(slug, published_only=False)
        if not post:
            continue
        campos = {chave: valor for chave, valor in campos.items() if valor}
        if str(post.get("author") or "").strip() in ("", "Equipa IQ OS"):
            campos["author"] = "Equipa Sabemos Studio"
        if not _alterados(post, campos):
            print(f"  artigo {slug}: já estava atualizado")
            continue
        store.save_item("posts", {**post, **campos}, AUTOR)
        print(f"  artigo {slug}: " + ", ".join(sorted(campos)))


def _aplicar_conteudos() -> None:
    """Acerta o nome da marca no conteúdo reutilizável do rodapé."""
    try:
        rodape = store.get_item("contents", "ctd_rodape")
    except KeyError:
        return
    corpo = str(rodape.get("body") or "")
    if "IQ OS" not in corpo:
        print("  conteúdo ctd_rodape: já estava atualizado")
        return
    store.save_item("contents", {**rodape, "body": corpo.replace("IQ OS", "Sabemos Studio")}, AUTOR)
    print("  conteúdo ctd_rodape: marca atualizada")


#: Diagrama e ilustração que as páginas de benchmark recebem por acréscimo.
DIAGRAMA_BENCHMARK = "diagrama-comparacao-lojas.svg"
ILUSTRACAO_BENCHMARK = "ilustracao-benchmarks.svg"


def _referencias_de_media(blocos: List[Dict[str, Any]]) -> set:
    """Id de todo o media já usado pelos blocos de uma página."""
    referencias = {str((bloco.get("data") or {}).get("media_id") or "") for bloco in blocos}
    referencias |= {
        str(media_id) for bloco in blocos for media_id in ((bloco.get("data") or {}).get("media_ids") or [])
    }
    return referencias


def _aplicar_paginas_de_benchmarks(media: Dict[str, str]) -> None:
    """Acrescenta o diagrama de leitura às páginas de benchmark.

    Estas páginas não vêm do `editorial` — nascem no `benchmarks_service`, na
    primeira publicação de um estudo —, por isso o diagrama entra por
    acréscimo: o que lá estiver fica como está e cada bloco novo só entra uma
    vez, para correr isto duas vezes não duplicar nada.
    """
    diagrama = media.get(DIAGRAMA_BENCHMARK) or ""
    ilustracao = media.get(ILUSTRACAO_BENCHMARK) or ""
    for pagina in store.list_items("pages")["items"]:
        caminho = str(pagina.get("path") or "")
        if caminho != "benchmarks" and not caminho.startswith("benchmarks/"):
            continue
        blocos = list(pagina.get("blocks") or [])
        referencias = _referencias_de_media(blocos)
        novos: List[Dict[str, Any]] = []
        if diagrama and diagrama not in referencias:
            novos.append(
                {
                    "id": f"blk_{str(pagina.get('slug') or 'benchmark')}_imagem",
                    "type": "imagem",
                    "data": {
                        "media_id": diagrama,
                        "alt": "Índice de preço por loja, com 100 a valer a média do estudo",
                        "caption": "Como se lê um benchmark: dispersão entre lojas e melhor preço assinalado.",
                    },
                }
            )
        # A ilustração da área é da página-mãe: em cada estudo seria repetição.
        if caminho == "benchmarks" and ilustracao and ilustracao not in referencias:
            novos.append(
                {"id": "blk_benchmarks_galeria", "type": "galeria", "data": {"media_ids": [ilustracao]}}
            )
        if not novos:
            print(f"  página {caminho}: já estava atualizada")
            continue
        store.save_item("pages", {**pagina, "blocks": blocos + novos}, AUTOR)
        print(f"  página {caminho}: {len(novos)} blocos acrescentados")


def _aplicar_templates() -> None:
    """Acrescenta os modelos de página que a instalação ainda não tenha.

    O deploy de código não leva a pasta `data/`, por isso uma instalação antiga
    não recebe sozinha o modelo «Biblioteca de relatórios». Um modelo que já
    exista fica como está — quem o tenha editado não o perde.
    """
    novos = store.instalar_templates_editoriais()
    if novos:
        print(f"  modelos acrescentados: {', '.join(novos)}")
    else:
        print("  modelos: já estavam todos instalados")


def main() -> None:
    media = store.instalar_media_de_marca()
    print(f"media de marca instalados: {len(media)} ficheiros")

    definicoes = {
        "site_name": "Sabemos Studio",
        "tagline": "Inteligência financeira e contratual",
        "description": "Plataforma de inteligência financeira: contratos públicos, empresas, mercado e investigação assistida.",
        "footer_text": "© Sabemos Studio — todos os direitos reservados.",
        "base_url": BASE_URL,
        "logo_id": media.get("logo-sabemos-studio.svg"),
        "favicon_id": media.get("icone-sabemos-studio.svg"),
        "seo": {
            "title": "",
            "description": "Sabemos Studio: contratos públicos, empresas e investigação a partir de dados abertos.",
            "image_id": media.get("capa-sabemos-studio.svg"),
            "keywords": ["Sabemos Studio", "contratos públicos", "dados abertos"],
        },
    }
    if _alterados(store.get_settings(), definicoes):
        store.save_settings(definicoes, AUTOR)
        print("definições do site atualizadas")
    else:
        print("definições do site já estavam atualizadas")

    capa = media.get("capa-sabemos-studio.svg")
    home_id = str(store.get_settings().get("home_page_id") or "") or editorial.INICIO_ID
    _aplicar_pagina(
        home_id,
        {
            "title": "Início",
            "slug": "inicio",
            "path": "",
            "template": "pagina-inicial",
            "show_in_menu": True,
            "menu_order": 1,
            "menu_label": "Início",
            "excerpt": editorial.INICIO_EXCERPT,
            "blocks": editorial.conteudo_da_inicio(media),
            "seo": {**editorial.INICIO_SEO, "image_id": capa},
        },
    )

    sobre = _pagina_por_caminho("sobre")
    if sobre:
        _aplicar_pagina(
            str(sobre["id"]),
            {"blocks": editorial.conteudo_da_sobre(media), "seo": editorial.SOBRE_SEO, "menu_order": 6},
        )

    _aplicar_paginas_do_site(media)
    _aplicar_paginas_de_benchmarks(media)
    _aplicar_templates()
    _aplicar_menus()
    _aplicar_posts(media)
    _aplicar_conteudos()
    print("concluído")


if __name__ == "__main__":
    main()
