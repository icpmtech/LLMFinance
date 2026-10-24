"""Cria a página «Pesquisar» no CMS da instalação em uso (uma vez).

A página nasce com uma instalação nova (vive em
`cms_editorial.paginas_do_site`), mas o deploy não leva a pasta `data/`: numa
instalação em uso faltam a página e as entradas de menu. Isto aplica as duas
coisas pela API do `cms_store`, como se fossem feitas no CMS (com revisão e
atividade).

    python _criar_pagina_pesquisar.py
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from api import cms_editorial as editorial
from api import cms_store as store

AUTOR = "migracao@sabemos.studio"


def _modelo() -> Dict[str, Any]:
    for pagina in editorial.paginas_do_site({}):
        if str(pagina.get("path")) == "pesquisar":
            return pagina
    raise SystemExit("A página «Pesquisar» não está no editorial.")


def _existente(modelo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return store.get_item("pages", str(modelo["id"]))
    except KeyError:
        pass
    for pagina in store.list_items("pages")["items"]:
        if str(pagina.get("path") or "") in ("pesquisar", "/pesquisar"):
            return pagina
        if str(pagina.get("slug") or "") == "pesquisar":
            return pagina
    return None


def _menus(pagina: Dict[str, Any]) -> None:
    rotulo = str(pagina.get("menu_label") or pagina.get("title") or "Sabemos")
    for localizacao in ("header", "footer"):
        menu = next((item for item in store.list_menus() if item.get("location") == localizacao), None)
        if not menu:
            continue
        itens = list(menu.get("items") or [])
        existente = [item for item in itens if str(item.get("page_id") or "") == str(pagina["id"])]
        if existente:
            # O rótulo do menu é do item, não da página: um «Pesquisar» antigo
            # ficaria a apontar para a página «Sabemos» sem ninguém dar por isso.
            if all(str(item.get("label") or "") == rotulo for item in existente):
                print(f"  menu {localizacao}: já tem «{rotulo}»")
                continue
            for item in existente:
                item["label"] = rotulo
            store.save_item("menus", {**menu, "items": itens}, AUTOR)
            print(f"  menu {localizacao}: «{rotulo}» acertado")
            continue
        # Cabeçalho: logo a seguir a «Início»; rodapé: à frente de tudo.
        posicao = 1 if localizacao == "header" else 0
        itens.insert(min(posicao, len(itens)), {"label": rotulo, "href": "", "page_id": pagina["id"], "new_tab": False})
        store.save_item("menus", {**menu, "items": itens}, AUTOR)
        print(f"  menu {localizacao}: «{rotulo}» acrescentado")


def main() -> None:
    modelo = _modelo()
    campos = {chave: valor for chave, valor in modelo.items() if chave != "id"}
    atual = _existente(modelo)
    if atual is None:
        # `save_item` recusa um `id` que ainda não exista: a página nova recebe
        # um id gerado (a partir daqui é encontrada pelo `slug`/caminho).
        campos.pop("id", None)
        guardada = store.save_item("pages", {**campos, "status": "publicado"}, AUTOR)
        print(f"página criada: {guardada['id']} (/{guardada['path']})")
    else:
        guardada = store.save_item("pages", {**atual, **campos}, AUTOR)
        print(f"página atualizada: {guardada['id']} (/{guardada['path']})")
    _menus(guardada)


if __name__ == "__main__":
    sys.exit(main())
