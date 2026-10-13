"""Aplica a página inicial e a marca «Sabemos Studio» a uma instalação em uso.

O deploy de código **não** envia a pasta `data/`, por isso o CMS de uma
instalação antiga (produção incluída) não recebe nem as imagens de marca nem o
conteúdo novo. Isto aplica as duas coisas pela API do próprio `cms_store`, para
as alterações ficarem com revisão e atividade, como se tivessem sido feitas no
CMS.

    python _atualizar_inicio_sabemos.py

Pode ser corrido mais de uma vez: as imagens não duplicam e as páginas que já
estejam iguais não voltam a ser gravadas.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from api import cms_store as store

AUTOR = "migracao@sabemos.studio"
BASE_URL = "https://sabemos.studio"


def _sem_hidden(valor: Any) -> Any:
    """Versão comparável de um valor, sem os `hidden: false` que o `_normalise`
    acrescenta a todos os blocos — sem isto a página era regravada a cada execução."""
    if isinstance(valor, list):
        return [_sem_hidden(item) for item in valor]
    if isinstance(valor, dict):
        return {chave: _sem_hidden(item) for chave, item in valor.items() if not (chave == "hidden" and not item)}
    return valor


def _alterados(atual: Dict[str, Any], novo: Dict[str, Any]) -> List[str]:
    """Campos de `novo` que diferem de `atual`."""
    return [chave for chave, valor in novo.items() if _sem_hidden(atual.get(chave)) != _sem_hidden(valor)]


def _aplicar_pagina(page_id: str, campos: Dict[str, Any]) -> None:
    """Guarda uma página, saltando a escrita quando nada mudou."""
    try:
        atual = store.get_item("pages", page_id)
    except KeyError:
        atual = {}
        campos = {**campos, "status": "publicado"}
    if atual and not _alterados(atual, campos):
        print(f"  página {page_id}: já estava atualizada")
        return
    store.save_item("pages", {**atual, **campos}, AUTOR)
    print(f"  página {page_id}: gravada ({len(campos.get('blocks') or [])} blocos)")


def _pagina_por_caminho(caminho: str) -> Optional[Dict[str, Any]]:
    for pagina in store.list_items("pages")["items"]:
        if str(pagina.get("path") or "") == caminho:
            return pagina
    return None


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
    home_id = str(store.get_settings().get("home_page_id") or "") or "pag_inicio"
    _aplicar_pagina(
        home_id,
        {
            "id": home_id,
            "title": "Início",
            "slug": "inicio",
            "path": "",
            "template": "pagina-inicial",
            "show_in_menu": True,
            "menu_order": 1,
            "menu_label": "Início",
            "excerpt": store.INICIO_EXCERPT,
            "blocks": store.conteudo_da_inicio(media),
            "seo": {**store.INICIO_SEO, "image_id": capa},
        },
    )

    sobre = _pagina_por_caminho("sobre")
    if sobre:
        _aplicar_pagina(
            str(sobre["id"]),
            {
                "blocks": store.conteudo_da_sobre(),
                "seo": store.SOBRE_SEO,
            },
        )

    _aplicar_posts(media)
    _aplicar_conteudos()
    print("concluído")


if __name__ == "__main__":
    main()
