"""Rotas do CMS (`/cms/*`) e do site público (`/site/*`).

**Gestão** (requer sessão para escrever):

- `GET  /cms/catalogue` — tudo o que o editor precisa (blocos, estados, listas)
- `GET  /cms/overview` — panorama, agendamentos e atividade
- `GET  /cms/search?q=` — pesquisa global no CMS
- `GET|PUT /cms/settings` — aparência e ligações do site
- `GET|POST|PATCH|DELETE /cms/menus…`
- `GET|POST /cms/{entidade}` e `GET|PATCH|DELETE /cms/{entidade}/{id}`
  (`pages`, `posts`, `contents`, `media`, `categories`, `templates`, `menus`;
  `contactos` — as mensagens do formulário do site — só se **leem** com sessão)
- `POST /cms/{entidade}/{id}/duplicate`
- `POST /cms/{entidade}/{id}/publish|unpublish|status` — publicar, despublicar,
  agendar (`{"at": "…"}`) ou mudar o estado
- `GET  /cms/{entidade}/{id}/revisions` e `POST /cms/revisions/{id}/restore`
- `POST /cms/media` — carregar ficheiro (base64) ou registar URL externo
- `GET  /cms/media/{id}/raw` — servir o binário
- `GET  /cms/preview/{entidade}/{id}` — pré-visualização HTML do rascunho

**Fichas de município** (o `municipios` é uma entidade do CMS, com o seu editor):

- `GET  /cms/municipios/opcoes` — os 308 municípios, com a ficha que já existe
- `POST /cms/municipios` — cria a ficha (os dados da despesa/contratação entram já)
- `PATCH /cms/municipios/{id}` — altera título, texto, blocos e SEO
- `POST /cms/municipios/{id}/dados` — volta a ler os dados oficiais para a ficha
- `POST /cms/municipios/{id}/texto` — rascunho do texto escrito pela IA com os números

**Páginas de pesquisa** (entidade `pesquisas` — uma consulta congelada sobre os
municípios, com filtros, SEO, marca e imagens):

- `GET  /cms/pesquisas/opcoes` — filtros disponíveis (distritos, anos, ordenações)
- `POST /cms/pesquisas` — cria a página (os números entram já lidos da pesquisa)
- `PATCH /cms/pesquisas/{id}` — altera título, filtros, texto, marca e SEO
- `POST /cms/pesquisas/{id}/dados` — volta a correr a pesquisa e guarda-a

**Páginas do modelo de remunerações** (entidade `remuneracoes` — o quadro da
DGAEP de um ano, com as secções editáveis, o texto, os blocos e a marca):

- `GET  /cms/remuneracoes/opcoes` — anos recolhidos, secções (com os títulos por
  omissão) e estilos de apresentação
- `POST /cms/remuneracoes` — cria a página (o modelo do ano entra já lido)
- `PATCH /cms/remuneracoes/{id}` — altera título, ano, texto, blocos, secções,
  marca e SEO
- `POST /cms/remuneracoes/{id}/modelo` — volta a ler o quadro da DGAEP
- `POST /cms/remuneracoes/{id}/artigo` — cria no blog o rascunho que anuncia a página

**Site público** (sem sessão):

- `GET /site` — página inicial
- `GET /site/blog`, `/site/blog/{slug}`, `/site/categoria/{slug}`, `/site/etiqueta/{tag}`
- `GET /site/blog/{slug}/pdf` — relatório PDF do artigo (mesmos números e fontes)
- `GET /site/municipio/{slug}` — ficha pública de um município
- `GET /site/pesquisa/{slug}` — página pública de uma pesquisa
- `GET /site/rss.xml`, `/site/sitemap.xml`, `/site/robots.txt`
- `POST /site/contacto` — formulário de contacto (grava na entidade `contactos`)
- `GET /site/{caminho}` — qualquer página publicada
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response

from api import captcha
from api import cms_post_report
from api import cms_render as render
from api import cms_store as store
from api import municipios_publicos as publicos
from api import notification_email
from api import pesquisas_publicas as pesquisas
from api import remuneracoes_publicas as remuneracoes_publicas
from api import reports_store as relatorios_store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cms"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

# Os pedidos de escrita identificam quem escreveu (revisões e auditoria).
def _writer(session: Optional[CurrentSession]) -> str:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para escrever no CMS.")
    return session.user.email


def _author(session: Optional[CurrentSession]) -> str:
    return session.user.email if session else ""


def _entity(entity: str) -> str:
    if entity not in store.ENTITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Entidade «{entity}» não existe no CMS. Válidas: {', '.join(store.ENTITIES)}.",
        )
    return entity


def _ip_do_pedido(request: Request) -> str:
    """IP de quem enviou: o proxy (nginx/Caddy) deixa-o no `X-Forwarded-For`."""
    encaminhado = str(request.headers.get("x-forwarded-for") or "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else ""


def _privado(entity: str, session: Optional[CurrentSession]) -> None:
    """Entidades com dados pessoais (contactos) só se leem com sessão.

    A leitura do CMS é aberta de propósito — o conteúdo do site é público — mas
    isso não pode incluir quem escreveu pelo formulário.
    """
    if entity in store.PRIVATE_ENTITIES and not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para ler os contactos recebidos.")


# Secções da interface do CMS: `/cms/paginas`, `/cms/media`, `/cms/blog`… Estas
# rotas colidem com `GET /cms/{entidade}` (e `/cms/media` com a listagem dos
# media), pelo que uma **navegação do browser** (que pede HTML) tem de devolver a
# SPA construída — senão recarregar a página dava JSON em vez da aplicação.
UI_SECTION_SLUGS = frozenset({"paginas", "conteudos", "blog", "municipios", "pesquisas", "remuneracoes", "contactos", "media", "taxonomia", "modelos", "aparencia"})


def _is_browser_navigation(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _spa_response() -> Response:
    """A SPA construída (import tardio: `api.main` importa este módulo)."""
    from api.main import spa_index_response

    return spa_index_response()


# ==========================================================================
# Catálogo, panorama e pesquisa
# ==========================================================================
@router.get("/cms/catalogue")
def cms_catalogue() -> Dict[str, Any]:
    """Tipos de bloco, estados, listas de páginas/categorias/media e URLs do site."""
    return store.catalogue()


@router.get("/cms/overview")
def cms_overview() -> Dict[str, Any]:
    """Panorama do CMS: contagens, agendamentos, alterações recentes e atividade."""
    return store.overview()


@router.get("/cms/taxonomy")
def cms_taxonomy() -> Dict[str, Any]:
    """Categorias e etiquetas do blog, com contagem de artigos publicados."""
    return store.taxonomy()


@router.get("/cms/tree")
def cms_tree(published: bool = Query(False, description="Só páginas publicadas.")) -> Dict[str, Any]:
    """Árvore de páginas (ascendentes → descendentes)."""
    return {"items": store.page_tree(published_only=published)}


@router.get("/cms/activity")
def cms_activity(limit: int = Query(40, ge=1, le=400)) -> Dict[str, Any]:
    """Registo de atividade do CMS (mais recente primeiro)."""
    items = store.activity(limit)
    return {"total": len(items), "items": items}


@router.get("/cms/search")
def cms_search(q: str = Query("", description="Texto a procurar (título, slug, corpo, etiquetas)."), limit: int = Query(30, ge=1, le=100)) -> Dict[str, Any]:
    """Pesquisa global no CMS."""
    return store.search(q, limit=limit)


# ==========================================================================
# Definições do site
# ==========================================================================
@router.get("/cms/settings")
def cms_get_settings() -> Dict[str, Any]:
    """Definições do site: nome, descrição, aparência, SEO e ligações."""
    return {"settings": store.get_settings(), "menus": [_menu_summary(menu) for menu in store.list_menus()]}


@router.put("/cms/settings")
def cms_put_settings(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Guarda as definições do site (só os campos enviados são alterados)."""
    author = _writer(session)
    return {"saved": True, "settings": store.save_settings(payload, author)}


# ==========================================================================
# Menus
# ==========================================================================
def _menu_summary(menu: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in menu.items() if key != "items"} | {"items": len(menu.get("items") or [])}


@router.get("/cms/menus")
def cms_list_menus() -> Dict[str, Any]:
    """Menus do site (cabeçalho e rodapé) e o resultado já resolvido."""
    menus = store.list_menus()
    return {
        "total": len(menus),
        "items": menus,
        "resolved": {
            location["id"]: store.menu_for(location["id"])
            for location in store.MENU_LOCATIONS
        },
        "locations": store.MENU_LOCATIONS,
        "themes": store.menu_themes(),
    }


@router.post("/cms/menus")
def cms_create_menu(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria um menu."""
    author = _writer(session)
    try:
        return {"saved": True, "menu": store.save_item("menus", payload, author)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/cms/menus/{menu_id}")
def cms_patch_menu(menu_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera um menu (nome, local e itens)."""
    author = _writer(session)
    try:
        return {"saved": True, "menu": store.save_item("menus", {**payload, "id": menu_id}, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/cms/menus/{menu_id}")
def cms_delete_menu(menu_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um menu."""
    _writer(session)
    try:
        return store.delete_item("menus", menu_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# Fichas de município (entidade `municipios` do CMS)
# ==========================================================================
@router.get("/cms/municipios/opcoes")
def cms_municipios_opcoes() -> Dict[str, Any]:
    """Os 308 municípios que se podem publicar, e a ficha que já existe de cada um."""
    return publicos.opcoes()


@router.post("/cms/municipios")
def cms_create_municipio(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria a ficha pública de um município.

    O editor escolhe o município e o texto; os **números entram já lidos** da ficha
    das despesas e da contratação, para o documento não nascer vazio.
    """
    author = _writer(session)
    nome = str(payload.get("municipio") or "").strip()
    if not nome:
        raise HTTPException(status_code=422, detail="Escolha o município da ficha.")

    existente = store.municipio_by_name(nome)
    if existente:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe uma ficha de {existente.get('municipio') or nome}.",
        )

    corpo = dict(payload)
    corpo.setdefault("title", f"Despesas da Câmara Municipal de {nome}")
    # O endereço público é o nome do município (`/site/municipio/porto`): é o que
    # se partilha e o que o Google indexa, não o título inteiro.
    corpo.setdefault("slug", nome)
    if not corpo.get("dados"):
        dados = publicos.dados_do_municipio(nome)
        if dados.get("error"):
            raise HTTPException(status_code=404, detail=dados["error"])
        corpo["dados"] = dados
        corpo.setdefault("geocod", dados.get("geocod"))
    try:
        return {"saved": True, "item": store.save_item("municipios", corpo, author)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/cms/municipios/{item_id}")
def cms_patch_municipio(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera a ficha de um município (título, texto, blocos, SEO)."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.save_item("municipios", {**payload, "id": item_id}, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cms/municipios/{item_id}/dados")
def cms_municipio_dados(item_id: str, session: Session = None) -> Dict[str, Any]:
    """Volta a ler a ficha oficial (INE + Portal BASE) e guarda-a no documento.

    A página publicada usa sempre a fotografia guardada: é este passo que a
    actualiza, para que a recolha seguinte não mude uma página já publicada.
    """
    author = _writer(session)
    try:
        doc = store.get_item("municipios", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    dados = publicos.dados_do_municipio(str(doc.get("municipio") or doc.get("title") or ""))
    if dados.get("error"):
        raise HTTPException(status_code=404, detail=dados["error"])
    item = store.save_item(
        "municipios",
        {**doc, "id": item_id, "dados": dados, "geocod": dados.get("geocod")},
        author,
    )
    return {"saved": True, "item": item, "resumo_dos_dados": publicos.resumo_dos_dados(dados)}


@router.post("/cms/municipios/{item_id}/texto")
def cms_municipio_texto(
    item_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Rascunho do texto escrito pela IA com os números da ficha à frente.

    Devolve o rascunho **sem gravar**: quem escreve revê-o no editor e é a gravar
    que ele passa a ser o texto da ficha — a IA ajuda, não publica.
    """
    _writer(session)
    try:
        doc = store.get_item("municipios", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    utilizador = getattr(session, "user", None) if session else None
    resultado = publicos.texto_com_ia(
        str(doc.get("municipio") or doc.get("title") or ""),
        dados=doc.get("dados") if isinstance(doc.get("dados"), dict) else None,
        instrucoes=str(payload.get("instrucoes") or ""),
        user_id=getattr(utilizador, "id", None),
        provider=payload.get("provider"),
        model=payload.get("model"),
    )
    if not resultado.get("ok"):
        raise HTTPException(status_code=502, detail=resultado.get("error"))
    return resultado


# ==========================================================================
# Páginas de pesquisa (entidade `pesquisas` do CMS)
# ==========================================================================
@router.get("/cms/pesquisas/opcoes")
def cms_pesquisas_opcoes() -> Dict[str, Any]:
    """Filtros disponíveis para montar uma pesquisa (distritos, anos, ordenações)."""
    return pesquisas.opcoes()


@router.post("/cms/pesquisas")
def cms_create_pesquisa(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria uma página de pesquisa.

    Os filtros vêm do editor e os números entram já lidos (`dados_da_pesquisa`),
    para o documento não nascer vazio e a pré-visualização ter o que mostrar.
    """
    author = _writer(session)
    corpo = dict(payload)
    filtros = store.normalizar_filtros(corpo.get("filtros"))
    corpo["filtros"] = filtros
    corpo.setdefault("descricao_filtros", pesquisas.descricao_dos_filtros(filtros))
    if not corpo.get("title"):
        corpo["title"] = f"Despesas municipais — {corpo['descricao_filtros']}"
    if not corpo.get("slug"):
        corpo["slug"] = corpo["title"]
    if not corpo.get("dados"):
        corpo["dados"] = pesquisas.dados_da_pesquisa(filtros)
    try:
        return {"saved": True, "item": store.save_item("pesquisas", corpo, author)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/cms/pesquisas/{item_id}")
def cms_patch_pesquisa(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera a página de pesquisa (título, filtros, texto, marca, blocos e SEO)."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.save_item("pesquisas", {**payload, "id": item_id}, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cms/pesquisas/{item_id}/dados")
def cms_pesquisa_dados(
    item_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Volta a correr a pesquisa guardada e grava a fotografia nova.

    O corpo pode trazer `filtros` (para experimentar sem guardar à mão) e/ou
    `guardar_filtros` — a página publicada usa sempre a fotografia guardada.
    """
    author = _writer(session)
    try:
        doc = store.get_item("pesquisas", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    filtros = store.normalizar_filtros(payload.get("filtros") or doc.get("filtros"))
    dados = pesquisas.dados_da_pesquisa(filtros)
    if dados.get("error"):
        raise HTTPException(status_code=502, detail=dados["error"])

    corpo = {**doc, "id": item_id, "dados": dados}
    if payload.get("guardar_filtros"):
        corpo["filtros"] = filtros
    if payload.get("guardar_descricao", True):
        corpo["descricao_filtros"] = pesquisas.descricao_dos_filtros(filtros)
    item = store.save_item("pesquisas", corpo, author)
    return {"saved": True, "item": item, "resumo_dos_dados": pesquisas.resumo_dos_dados(dados)}


# Páginas do modelo de remunerações da Administração Pública (entidade
# `remuneracoes`): o quadro consolidado da DGAEP de um ano, editável e publicável
# como as restantes páginas do site.
# ==========================================================================
@router.get("/cms/remuneracoes/opcoes")
def cms_remuneracoes_opcoes() -> Dict[str, Any]:
    """Anos recolhidos, secções de carreiras e o que a página pode mostrar."""
    return remuneracoes_publicas.opcoes()


@router.post("/cms/remuneracoes")
def cms_create_remuneracao(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria a página do modelo de remunerações.

    O ano vem do editor e o modelo (**fotografia** do quadro desse ano) entra já
    lido, para o documento não nascer vazio e a pré-visualização ter o que
    mostrar. O endereço público é o ano quando o editor não escolhe outro.
    """
    author = _writer(session)
    corpo = dict(payload)
    ano = store._ano_valido(corpo.get("ano"))
    if not ano:
        raise HTTPException(status_code=422, detail="Escolha o ano do quadro da DGAEP.")
    corpo["ano"] = ano
    corpo.setdefault("title", f"Remunerações da Administração Pública {ano}")
    corpo.setdefault("slug", f"administracao-publica-{ano}")
    if not corpo.get("dados"):
        dados = remuneracoes_publicas.dados_do_ano(ano)
        if dados.get("error"):
            raise HTTPException(status_code=404, detail=dados["error"])
        corpo["dados"] = dados
    try:
        return {"saved": True, "item": store.save_item("remuneracoes", corpo, author)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/cms/remuneracoes/{item_id}")
def cms_patch_remuneracao(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera a página do modelo (título, ano, texto, blocos, marca e SEO)."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.save_item("remuneracoes", {**payload, "id": item_id}, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cms/remuneracoes/{item_id}/modelo")
def cms_remuneracao_modelo(
    item_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Volta a ler o quadro da DGAEP (do ano pedido ou do que está guardado).

    É este passo que atualiza a página publicada: a fotografia só muda quando o
    editor manda ler outra vez.
    """
    author = _writer(session)
    try:
        doc = store.get_item("remuneracoes", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ano = store._ano_valido(payload.get("ano"), doc.get("ano"))
    if not ano:
        raise HTTPException(status_code=422, detail="Escolha o ano do quadro da DGAEP.")
    dados = remuneracoes_publicas.dados_do_ano(ano)
    if dados.get("error"):
        raise HTTPException(status_code=404, detail=dados["error"])
    corpo = {**doc, "id": item_id, "ano": ano, "dados": dados}
    if payload.get("guardar_ano"):
        corpo["ano"] = ano
    item = store.save_item("remuneracoes", corpo, author)
    return {
        "saved": True,
        "item": item,
        "ano": ano,
        "resumo_dos_dados": remuneracoes_publicas.resumo_dos_dados(dados),
    }


@router.post("/cms/remuneracoes/{item_id}/artigo")
def cms_remuneracao_artigo(
    item_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Cria o artigo de blog que anuncia a página do modelo.

    O artigo nasce **rascunho** (publica-se no editor do blog), com a capa, o
    resumo e as etiquetas do modelo, e o corpo escrito a partir dos números
    lidos — o quadro continua a ser a página: o artigo diz o que o ano traz e
    liga para lá. O `artigo_id` fica guardado na página, para o editor não o
    perder de vista nem o criar duas vezes.
    """
    author = _writer(session)
    try:
        doc = store.get_item("remuneracoes", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    sugestao = remuneracoes_publicas.artigo_do_modelo(doc)
    corpo = {
        "title": str(payload.get("title") or sugestao["title"]).strip() or sugestao["title"],
        "slug": str(payload.get("slug") or sugestao["slug"]),
        "status": "rascunho",
        "excerpt": str(payload.get("excerpt") or sugestao["excerpt"]),
        "markdown": str(payload.get("markdown") or sugestao["markdown"]),
        "cover_id": payload.get("cover_id") or doc.get("capa_id"),
        "category_ids": [str(valor) for valor in (payload.get("category_ids") or []) if str(valor).strip()],
        "tags": payload.get("tags") or sugestao["tags"],
        "author": author,
    }
    try:
        artigo = store.save_item("posts", corpo, author)
        item = store.save_item("remuneracoes", {**doc, "id": item_id, "artigo_id": artigo["id"]}, author)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "saved": True,
        "item": item,
        "artigo": artigo,
        "url": f"/cms/blog?id={artigo['id']}",
        "resumo": f"Artigo «{artigo['title']}» criado como rascunho.",
    }


# ==========================================================================
# CRUD genérico por entidade
# ==========================================================================
@router.get("/cms/{entity}")
def cms_list(
    entity: str,
    request: Request,
    status: Optional[str] = Query(None, description="`all` ou lista separada por vírgulas."),
    q: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    full: bool = Query(True, description="Incluir os blocos/corpo (False = resumo)."),
    session: Session = None,
) -> Any:
    """Lista uma entidade do CMS, com filtros por estado, pesquisa, categoria e etiqueta."""
    if entity in UI_SECTION_SLUGS and _is_browser_navigation(request):
        return _spa_response()
    _entity(entity)
    _privado(entity, session)
    return store.list_items(entity, status=status, query=q, category_id=category_id, tag=tag, limit=limit, with_blocks=full)


@router.post("/cms/{entity}")
def cms_create(entity: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria um documento do CMS (no caso dos media, carrega o ficheiro)."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_media(payload, author) if entity == "media" else store.save_item(entity, payload, author)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"saved": True, "item": doc}


@router.get("/cms/{entity}/{item_id}")
def cms_get(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Documento completo do CMS."""
    _entity(entity)
    _privado(entity, session)
    try:
        return {"item": store.get_item(entity, item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/cms/{entity}/{item_id}")
def cms_patch(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Alteração parcial de um documento do CMS."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_media({**payload, "id": item_id}, author) if entity == "media" else store.save_item(entity, {**payload, "id": item_id}, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": doc}


@router.delete("/cms/{entity}/{item_id}")
def cms_delete(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um documento do CMS."""
    _entity(entity)
    author = _writer(session)
    try:
        return store.delete_item(entity, item_id, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/cms/{entity}/{item_id}/duplicate")
def cms_duplicate(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Duplica um documento do CMS (a cópia nasce como rascunho)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.duplicate_item(entity, item_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# Publicação, revisões e pré-visualização
# ==========================================================================
@router.post("/cms/{entity}/{item_id}/publish")
def cms_publish(
    entity: str,
    item_id: str,
    payload: Optional[Dict[str, Any]] = Body(None),
    session: Session = None,
) -> Dict[str, Any]:
    """Publica agora ou agenda (`{"at": "2026-10-01T09:00"}`)."""
    _entity(entity)
    author = _writer(session)
    body = payload or {}
    try:
        doc = store.publish_item(entity, item_id, author, at=body.get("at") or body.get("scheduled_at"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": doc}


@router.post("/cms/{entity}/{item_id}/unpublish")
def cms_unpublish(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Devolve o documento a rascunho (sai imediatamente do site)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.unpublish_item(entity, item_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cms/{entity}/{item_id}/status")
def cms_status(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Muda o estado de publicação (`rascunho`, `agendado`, `publicado`, `arquivado`)."""
    _entity(entity)
    author = _writer(session)
    target = str(payload.get("status") or "")
    if target not in store.STATUSES:
        raise HTTPException(status_code=422, detail=f"Estado inválido «{target}». Válidos: {', '.join(store.STATUSES)}.")
    try:
        return {"saved": True, "item": store.set_status(entity, item_id, target, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/cms/{entity}/{item_id}/revisions")
def cms_revisions(entity: str, item_id: str, limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Histórico de revisões de um documento."""
    _entity(entity)
    items = store.revisions_of(entity, item_id, limit=limit)
    return {"total": len(items), "items": items}


@router.post("/cms/revisions/{revision_id}/restore")
def cms_restore(revision_id: str, session: Session = None) -> Dict[str, Any]:
    """Restaura um documento a partir de uma revisão."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.restore_revision(revision_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/cms/media/{item_id}/usage")
def cms_media_usage(item_id: str) -> Dict[str, Any]:
    """Onde é que este media é usado."""
    try:
        store.get_item("media", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    items = store.media_usage(item_id)
    return {"total": len(items), "items": items}


@router.get("/cms/media/{item_id}/raw")
def cms_media_raw(item_id: str) -> Response:
    """Serve o binário de um media (ficheiro local ou reencaminha para o URL externo)."""
    try:
        doc = store.get_item("media", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if doc.get("storage") == "externo":
        url = str(doc.get("url") or "")
        if not url:
            raise HTTPException(status_code=404, detail="Media sem URL.")
        return RedirectResponse(url)
    try:
        path, mime = store.media_file(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=600"})


@router.get("/cms/preview/{entity}/{item_id}")
def cms_preview(entity: str, item_id: str, session: Session = None) -> HTMLResponse:
    """Pré-visualização HTML do rascunho (iframe do editor)."""
    _entity(entity)
    if entity not in store.PUBLISHABLE:
        raise HTTPException(status_code=422, detail="Só páginas, artigos e municípios têm pré-visualização.")
    try:
        doc = store.get_item(entity, item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    settings = store.get_settings()
    if entity == "pages":
        html = render.render_page(doc, preview=True, settings=settings)
    elif entity == "posts":
        html = render.render_post(doc, preview=True, settings=settings)
    elif entity == "pesquisas":
        html = render.render_pesquisa(doc, preview=True, settings=settings)
    elif entity == "remuneracoes":
        html = render.render_remuneracao(doc, preview=True, settings=settings)
    else:
        html = render.render_municipio(doc, preview=True, settings=settings)
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


# ==========================================================================
# Site público
# ==========================================================================
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=15, must-revalidate"}


def _home_page() -> Optional[Dict[str, Any]]:
    settings = store.get_settings()
    home_id = settings.get("home_page_id")
    if home_id:
        try:
            page = store.get_item("pages", str(home_id))
        except KeyError:
            page = None
        if page and page.get("status") == "publicado":
            return page
    pages = store.published_pages()
    for page in pages:
        if page.get("template") == "pagina-inicial":
            return page
    for page in pages:
        if not page.get("path"):
            return page
    return pages[0] if pages else None


@router.get("/site", response_class=HTMLResponse)
def site_home() -> HTMLResponse:
    """Página inicial do site."""
    settings = store.get_settings()
    page = _home_page()
    html = render.render_page(page, settings=settings) if page else render.render_index(settings=settings)
    return HTMLResponse(html, headers=_PUBLIC_HEADERS)


@router.get("/site/blog", response_class=HTMLResponse)
def site_blog(page: int = Query(1, ge=1)) -> HTMLResponse:
    """Índice do blog (ou a página «Blog» definida no CMS, na primeira página)."""
    settings = store.get_settings()
    blog_page_id = settings.get("blog_page_id")
    if blog_page_id and page == 1:
        try:
            doc = store.get_item("pages", str(blog_page_id))
        except KeyError:
            doc = None
        if doc and doc.get("status") == "publicado" and doc.get("path"):
            return HTMLResponse(render.render_page(doc, settings=settings), headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_blog(page_no=page, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/blog/{slug}", response_class=HTMLResponse)
def site_post(slug: str) -> HTMLResponse:
    """Artigo de blog publicado."""
    settings = store.get_settings()
    post = store.resolve_post_by_slug(slug, published_only=True)
    if not post:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_post(post, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/blog/{slug}/pdf")
def site_post_pdf(slug: str) -> Response:
    """Relatório PDF do artigo, com os mesmos números e a mesma fonte da página."""
    store.get_settings()
    post = store.resolve_post_by_slug(slug, published_only=True)
    if not post:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")
    if not post.get("report_pdf", True):
        # O relatório é opcional e decide-se no artigo: sem ele não há botão na
        # página nem ficheiro para descarregar (nem por um endereço guardado).
        raise HTTPException(status_code=404, detail="Este artigo não tem relatório em PDF.")
    nome, conteudo, media_type = cms_post_report.artigo_pdf(post, store.get_settings())
    return Response(
        conteudo,
        media_type=media_type,
        headers={**_PUBLIC_HEADERS, "Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/site/categoria/{slug}", response_class=HTMLResponse)
def site_category(slug: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """Artigos de uma categoria."""
    settings = store.get_settings()
    category = store.category_by_slug(slug)
    if not category:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_blog(page_no=page, category=category, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/etiqueta/{tag}", response_class=HTMLResponse)
def site_tag(tag: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """Artigos com uma etiqueta."""
    settings = store.get_settings()
    return HTMLResponse(render.render_blog(page_no=page, tag=tag, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/municipio/{slug}", response_class=HTMLResponse)
def site_municipio(slug: str) -> HTMLResponse:
    """Ficha pública de um município (despesa e contratação, com o texto publicado)."""
    settings = store.get_settings()
    doc = store.municipio_by_slug(slug, published_only=True)
    if not doc:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_municipio(doc, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/pesquisa", response_class=HTMLResponse)
def site_search(q: str = Query("", description="Texto a procurar no site.")) -> HTMLResponse:
    """Pesquisa no site: páginas, artigos, estudos de benchmark e relatórios.

    Não se confunde com `/site/pesquisa/{slug}`, que serve uma **página
    editorial** de uma pesquisa guardada: aqui são resultados de texto, sem
    índice próprio (por isso não se indexa — `noindex`).
    """
    return HTMLResponse(render.render_search(q), headers=_PUBLIC_HEADERS)


@router.get("/site/pesquisa/{slug}", response_class=HTMLResponse)
def site_pesquisa(slug: str) -> HTMLResponse:
    """Página pública de uma pesquisa (a fotografia guardada, com marca e SEO)."""
    settings = store.get_settings()
    doc = store.pesquisa_by_slug(slug, published_only=True)
    if not doc:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_pesquisa(doc, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/remuneracoes/{slug}", response_class=HTMLResponse)
def site_remuneracoes(slug: str) -> HTMLResponse:
    """Página pública do modelo de remunerações da Administração Pública."""
    settings = store.get_settings()
    doc = store.remuneracao_by_slug(slug, published_only=True)
    if not doc:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_remuneracao(doc, settings=settings), headers=_PUBLIC_HEADERS)


@router.post("/site/contacto", response_class=HTMLResponse)
async def site_contacto(request: Request, background: BackgroundTasks) -> HTMLResponse:
    """Recebe o formulário do site: guarda a mensagem no CMS e avisa a caixa de apoio.

    Responde sempre com HTML do próprio site (sem JavaScript): agradecimento,
    ou o formulário outra vez com os erros assinalados. O aviso por email sai
    **depois** da resposta (`BackgroundTasks`, numa thread): o SMTP pode demorar
    segundos e quem escreveu não fica à espera dele.
    """
    settings = store.get_settings()
    sem_cache = {"Cache-Control": "no-store, must-revalidate"}
    form = await request.form()
    valores = {campo: str(form.get(campo) or "").strip() for campo in store.CONTACTO_LIMITES}
    valores["consentimento"] = "sim" if form.get("consentimento") else ""
    if str(form.get("website") or "").strip():
        # Campo-armadilha preenchido: é um robô. Recebe o mesmo agradecimento e
        # nada é guardado (não vale a pena ensinar-lhe o que falhou).
        return HTMLResponse(render.render_contacto(ok=True, settings=settings), headers=sem_cache)
    if not store.contacto_permitido(_ip_do_pedido(request)):
        html = render.render_contacto(
            ok=False,
            valores=valores,
            aviso="Recebemos vários pedidos seguidos deste endereço. Tente novamente daqui a pouco.",
            settings=settings,
        )
        return HTMLResponse(html, status_code=429, headers=sem_cache)
    erros = store.validar_contacto({**valores, "consentimento": bool(valores["consentimento"])})
    # O desafio anti-robô junta-se aos erros dos campos: quem falhou os dois vê
    # os dois, em vez de corrigir um para descobrir o outro à segunda tentativa.
    desafio_erro = captcha.erro(form.get(captcha.CAMPO_RESPOSTA), form.get(captcha.CAMPO_TESTEMUNHO))
    if desafio_erro:
        erros[captcha.CAMPO_RESPOSTA] = desafio_erro
    if erros:
        html = render.render_contacto(
            ok=False,
            valores=valores,
            erros=erros,
            aviso="Confira os campos assinalados.",
            settings=settings,
        )
        return HTMLResponse(html, status_code=422, headers=sem_cache)
    store.save_item(
        "contactos",
        {
            **valores,
            "consentimento": True,
            "estado": "novo",
            "origem": str(request.headers.get("referer") or "")[:120],
        },
        "",
    )
    # A caixa de apoio (a que o «Correio da plataforma» lê por IMAP) recebe o
    # aviso; o pedido já está guardado, por isso um problema de correio não o
    # pode perder — `send_contact_email` registra o erro e devolve `ok: False`.
    base_url = str(settings.get("base_url") or "").rstrip("/")
    background.add_task(
        notification_email.send_contact_email,
        to=str(relatorios_store.settings().get("support_email") or "").strip() or relatorios_store.DEFAULT_SUPPORT_EMAIL,
        nome=valores["nome"],
        email=valores["email"],
        organizacao=valores["organizacao"],
        assunto=valores["assunto"],
        mensagem=valores["mensagem"],
        registo_url=f"{base_url}/cms/contactos" if base_url else "",
    )
    logger.info("Contacto recebido pelo site.")
    return HTMLResponse(render.render_contacto(ok=True, settings=settings), headers=sem_cache)


@router.get("/site/rss.xml")
def site_rss() -> Response:
    """Feed RSS dos artigos publicados."""
    return Response(render.render_rss(store.get_settings()), media_type="application/rss+xml; charset=utf-8", headers=_PUBLIC_HEADERS)


@router.get("/site/sitemap.xml")
def site_sitemap() -> Response:
    """Sitemap XML de **tudo** o que está publicado no site: páginas, artigos e
    índice do blog, municípios, páginas de pesquisa de dados, remunerações e os
    estudos de benchmark publicados (a página do estudo e a pesquisa agregada)."""
    return Response(render.render_sitemap(store.get_settings()), media_type="application/xml; charset=utf-8", headers=_PUBLIC_HEADERS)


@router.get("/site/robots.txt", response_class=PlainTextResponse)
def site_robots() -> PlainTextResponse:
    """`robots.txt` do site (bloqueia a área de gestão)."""
    return PlainTextResponse(render.render_robots(store.get_settings()), headers=_PUBLIC_HEADERS)


@router.get("/site/manifest.webmanifest")
def site_manifest() -> Response:
    """Manifesto do PWA do site (nome, ícones e destino da aplicação instalada)."""
    return Response(
        render.render_manifest(store.get_settings()),
        media_type="application/manifest+json; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/site/sw.js")
def site_service_worker() -> Response:
    """Service worker do site: cache das páginas visitadas e leitura sem rede."""
    return Response(
        render.render_service_worker(store.get_settings()),
        media_type="text/javascript; charset=utf-8",
        headers={
            # Um worker antigo preso no cache do browser nunca mais é substituído.
            "Cache-Control": "no-cache, must-revalidate",
            "Service-Worker-Allowed": "/site/",
        },
    )


@router.get("/site/pwa/{ficheiro}")
def site_pwa_icon(ficheiro: str) -> Response:
    """Ícones do PWA (PNG gerados por `scripts/generate_site_pwa_icons.py`).

    A lista de nomes aceites é fixa — é o que impede que o caminho sirva
    qualquer ficheiro da pasta de imagens.
    """
    if ficheiro not in render.PWA_ICONS and ficheiro != render.PWA_IOS_ICON:
        raise HTTPException(status_code=404, detail="Ícone inexistente.")
    caminho = store.SITE_ASSETS_DIR / ficheiro
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Ícone inexistente.")
    return FileResponse(caminho, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/site/offline", response_class=HTMLResponse)
def site_offline() -> HTMLResponse:
    """Página de recurso, mostrada pelo service worker quando não há ligação."""
    return HTMLResponse(render.render_offline(settings=store.get_settings()), headers={"Cache-Control": "no-cache"})


@router.get("/site/site.css")
def site_css(request: Request) -> Response:
    """Folha de estilo do site, compilada pelo Tailwind (`site-css/`).

    Vive fora do HTML porque é a mesma em todas as páginas: assim é descarregada
    uma vez e reaproveitada. O `ETag` é o resumo do conteúdo — quando nada mudou,
    o browser fica com a cópia que já tem e leva um `304` sem corpo. O
    `must-revalidate` evita que uma versão antiga fique presa depois de uma
    publicação nova.
    """
    caminho = store.SITE_ASSETS_DIR / "site.css"
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Folha de estilo em falta.")
    dados = caminho.read_bytes()
    etiqueta = '"' + hashlib.sha256(dados).hexdigest()[:32] + '"'
    cabecalhos = {
        "ETag": etiqueta,
        "Cache-Control": "public, max-age=600, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etiqueta:
        return Response(status_code=304, headers=cabecalhos)
    return Response(dados, media_type="text/css; charset=utf-8", headers=cabecalhos)


@router.get("/site/documento/{document_id}")
def site_documento(document_id: str) -> Response:
    """PDF de um documento **gratuito e publicado** (biblioteca pública).

    É o download da página de relatórios gratuitos. A fronteira está em
    `reports_library.document_for_download`: documento inexistente, não
    publicado, sem PDF ou com preço responde 404 — esses pedem-se no catálogo,
    como qualquer relatório pago.
    """
    from api import reports_library as library  # noqa: PLC0415 - import tardio: a loja é grande

    encontrado = library.document_for_download(document_id)
    if encontrado is None:
        raise HTTPException(status_code=404, detail="Documento inexistente ou não disponível para download.")
    nome, conteudo, mime = encontrado
    # O nome vem do Estúdio; o cabeçalho é construído aqui, com o que ficar
    # depois de tirar aspas e separadores de caminho.
    seguro = re.sub(r"[^A-Za-z0-9._-]+", "-", nome).strip("-") or "documento.pdf"
    # `attachment` e não `inline`: o botão diz «Descarregar PDF» e um PDF
    # navegado abre (ou falha) no leitor do browser — em webviews fica em branco.
    return Response(
        content=conteudo,
        media_type=mime or "application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{seguro}"',
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/site/{path:path}", response_class=HTMLResponse)
def site_page(path: str) -> HTMLResponse:
    """Qualquer página publicada, pelo seu caminho (pode ter várias pastas)."""
    settings = store.get_settings()
    page = store.resolve_page_by_path(path, published_only=True)
    if not page:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_page(page, settings=settings), headers=_PUBLIC_HEADERS)
