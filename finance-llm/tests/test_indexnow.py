"""IndexNow: publicar uma página avisa o motor de busca do endereço que mudou.

O que se testa aqui, por ordem de importância:

* **quem decide o que é público são os sitemaps** — o inventário sai do sitemap do
  site, do da loja e do da aplicação, e endereços de outro host ficam de fora
  (o motor recusa um lote com hosts misturados);
* o que se **anuncia é a diferença** desde o último anúncio: página nova, página
  cujo `lastmod` mudou e página que desapareceu do sitemap;
* **sem chave não se anuncia nada** (é o que impede uma instalação de
  desenvolvimento de falar pelo domínio público), e a chave tanto pode vir do
  `.env` como do índice da administração;
* uma chave inválida ou um lote recusado **não ficam registados como anunciados**,
  senão a página nunca mais era anunciada;
* publicar no CMS ou na loja chega ao anúncio (o ponto de escrita é o gancho).

Nenhum teste fala com o motor: a fixture `isolado` substitui o POST por omissão,
para que o anúncio em fundo disparado por um `save_item` nunca saia para a rede.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cms_store  # noqa: E402
from api import indexnow  # noqa: E402
from api import main  # noqa: E402
from api import shop_store  # noqa: E402
from api.admin_routes import require_admin  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse  # noqa: E402

CHAVE = "chave-de-teste-123456"
SITE = "https://sabemos.studio"
#: O envio verdadeiro e o anúncio verdadeiro, guardados antes de a fixture
#: `isolado` os substituir (os testes que os exercitam precisam do original).
PEDIDO_REAL = indexnow._pedido  # noqa: SLF001 - o teste do pedido precisa do original
ANUNCIAR_REAL = indexnow.anunciar_em_fundo


@pytest.fixture()
def isolado(tmp_path, monkeypatch):
    """Índice, estado e lojas isolados: nada é lido nem escrito em `data/`."""
    cms = tmp_path / "cms"
    monkeypatch.setattr(cms_store, "CMS_DIR", cms)
    monkeypatch.setattr(cms_store, "CMS_PATH", cms / "cms.json")
    monkeypatch.setattr(cms_store, "MEDIA_DIR", cms / "media")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    loja = tmp_path / "shop"
    monkeypatch.setattr(shop_store, "SHOP_DIR", loja)
    monkeypatch.setattr(shop_store, "SHOP_PATH", loja / "shop.json")
    monkeypatch.setattr(shop_store, "FILES_DIR", loja / "files")
    monkeypatch.setattr(shop_store, "_cache", None)
    monkeypatch.setattr(shop_store, "_cache_mtime", None)

    pasta = tmp_path / "indexnow"
    monkeypatch.setattr(indexnow, "INDEXNOW_DIR", pasta)
    monkeypatch.setattr(indexnow, "ESTADO_PATH", pasta / "estado.json")
    monkeypatch.setattr(indexnow, "REGISTO_PATH", pasta / "submissoes.jsonl")
    monkeypatch.setattr(indexnow, "_cache_chave", (0.0, ("", "")))
    # Rede: por omissão nenhum envio sai daqui (os testes que o querem ver
    # instalam o seu próprio `_pedido`).
    monkeypatch.setattr(indexnow, "_pedido", lambda urls: {"estado": 200, "resposta": ""})
    # Threads: um anúncio em fundo deixado a correr de um teste para o outro
    # consumia a diferença que o teste seguinte queria observar. Por omissão, o
    # anúncio é registado e não executado; os testes que precisam do verdadeiro
    # repõem o original.
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", lambda motivo: None)
    return tmp_path


@pytest.fixture()
def com_chave(monkeypatch):
    """Chave resolvida e interruptor ligado, sem falar com o Elasticsearch."""
    monkeypatch.setattr(indexnow, "chave_e_origem", lambda *, fresco=False: (CHAVE, "teste"))
    monkeypatch.setattr(indexnow, "ligado", lambda: True)
    return CHAVE


@pytest.fixture()
def sem_anuncio(monkeypatch):
    """Desliga o anúncio em fundo.

    O teste quer ver o que ficou **pendente**; uma thread a anunciar em paralelo
    consumia a diferença a meio da asserção.
    """
    motivos = []
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", lambda motivo: motivos.append(motivo))
    return motivos


def _sitemap_app(tmp_path: Path, monkeypatch, locs) -> None:
    """O sitemap da aplicação é um ficheiro do build: aqui, um ficheiro à medida."""
    caminho = tmp_path / "sitemap-app.xml"
    caminho.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset>'
        + "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
        + "</urlset>",
        encoding="utf-8",
    )
    monkeypatch.setattr(indexnow, "SITEMAPS_DA_APP", (caminho,))


def _pedido_falso(monkeypatch, *, estado: int = 200, resposta: str = ""):
    """Substitui o POST ao motor e devolve a lista dos lotes enviados."""
    lotes = []

    def falso(urls):
        lotes.append(list(urls))
        return {"estado": estado, "resposta": resposta}

    monkeypatch.setattr(indexnow, "_pedido", falso)
    return lotes


def _publicos(monkeypatch, urls: dict) -> None:
    """Inventário fixo, para o teste não depender do que está semeado."""
    monkeypatch.setattr(indexnow, "urls_publicas", lambda: dict(urls))
    monkeypatch.setattr(
        indexnow,
        "inventario",
        lambda: {"urls": dict(urls), "por_fonte": {"teste": len(urls)}, "fora_do_host": [], "host": "sabemos.studio"},
    )


def _publicar_pagina(titulo: str = "Quem somos", slug: str = "quem-somos") -> dict:
    return cms_store.save_item("pages", {"title": titulo, "slug": slug, "status": "publicado", "blocks": []})


# ---------------------------------------------------------------------------
# Inventário: quem decide o que é público
# ---------------------------------------------------------------------------
def test_inventario_junta_os_tres_sitemaps(isolado, monkeypatch):
    _sitemap_app(isolado, monkeypatch, [f"{SITE}/", f"{SITE}/benchmark"])
    pagina = _publicar_pagina()

    urls = indexnow.urls_publicas()
    assert f"{SITE}/benchmark" in urls
    assert any(url.endswith(f"/{pagina['slug']}") for url in urls)
    fontes = indexnow.inventario()["por_fonte"]
    assert fontes["app"] == 2
    assert fontes["site"] >= 1


def test_endereco_de_outro_host_fica_de_fora(isolado, monkeypatch):
    _sitemap_app(isolado, monkeypatch, [f"{SITE}/", "https://outro.example/"])
    inventario = indexnow.inventario()
    assert "https://outro.example/" not in inventario["urls"]
    assert inventario["fora_do_host"] == ["https://outro.example/"]


def test_produto_da_loja_entra_no_inventario(isolado, monkeypatch):
    _sitemap_app(isolado, monkeypatch, [])
    produto = shop_store.save_item("products", {"name": "Relatório anual", "price": 10, "status": "publicado"})
    urls = indexnow.urls_publicas()
    assert any(str(produto["slug"]) in url for url in urls)


# ---------------------------------------------------------------------------
# O que se anuncia: a diferença
# ---------------------------------------------------------------------------
def test_primeiro_anuncio_envia_tudo_e_o_segundo_nao_envia_nada(isolado, com_chave, monkeypatch):
    _publicos(monkeypatch, {f"{SITE}/": "", f"{SITE}/x": ""})
    lotes = _pedido_falso(monkeypatch)

    primeiro = indexnow.sincronizar(motivo="teste")
    assert primeiro["submetidos"] == 2
    assert primeiro["novos"] == 2
    assert len(lotes) == 1

    segundo = indexnow.sincronizar(motivo="teste")
    assert segundo["submetidos"] == 0
    assert segundo["detalhe"].startswith("Nada mudou")
    assert len(lotes) == 1


def test_comparar_distingue_novo_alterado_e_desaparecido():
    novos, alterados, removidos = indexnow._comparar(  # noqa: SLF001 - a regra é o coração do módulo
        {"a": "2026-01-01", "b": "2026-02-02", "c": ""},
        {"b": "2026-01-01", "c": "", "d": "2026-01-01"},
    )
    assert novos == ["a"]
    assert alterados == ["b"]
    assert removidos == ["d"]


def test_pagina_nova_e_anunciada(isolado, com_chave, sem_anuncio, monkeypatch):
    _sitemap_app(isolado, monkeypatch, [])
    lotes = _pedido_falso(monkeypatch)
    # Um anúncio do que já era público: a partir daqui só o que muda interessa.
    indexnow.sincronizar(motivo="arranque")
    enviados_no_arranque = len(lotes)
    assert enviados_no_arranque == 1

    pagina = _publicar_pagina("Preços", "precos")
    pendentes = indexnow.pendentes()
    assert len(pendentes["novos"]) == 1 and "precos" in pendentes["novos"][0]

    resultado = indexnow.sincronizar(motivo="publicação")
    assert resultado["submetidos"] == 1
    assert any("precos" in url for url in lotes[-1])

    cms_store.unpublish_item("pages", pagina["id"])


def test_pagina_editada_por_fora_e_anunciada(isolado, com_chave, sem_anuncio, monkeypatch):
    """Uma alteração feita fora do processo muda o `lastmod` e é detetada."""
    _sitemap_app(isolado, monkeypatch, [])
    _pedido_falso(monkeypatch)
    indexnow.sincronizar(motivo="arranque")
    pagina = _publicar_pagina("Preços", "precos")
    assert indexnow.sincronizar(motivo="publicação")["submetidos"] == 1
    assert indexnow.pendentes()["alterados"] == []

    dados = json.loads(cms_store.CMS_PATH.read_text(encoding="utf-8"))
    for doc in dados["pages"]:
        if doc.get("id") == pagina["id"]:
            doc["updated_at"] = "2020-05-05T10:00:00+00:00"
    cms_store.CMS_PATH.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cms_store, "_cache", None)
    monkeypatch.setattr(cms_store, "_cache_mtime", None)

    alterados = indexnow.pendentes()["alterados"]
    assert len(alterados) == 1 and "precos" in alterados[0]
    assert indexnow.sincronizar(motivo="edição")["submetidos"] == 1


def test_pagina_despublicada_e_anunciada_como_remocao(isolado, com_chave, sem_anuncio, monkeypatch):
    _sitemap_app(isolado, monkeypatch, [])
    lotes = _pedido_falso(monkeypatch)
    indexnow.sincronizar(motivo="arranque")
    pagina = _publicar_pagina("Aviso", "aviso")
    assert indexnow.sincronizar(motivo="publicação")["submetidos"] == 1
    assert len(lotes) == 2

    cms_store.unpublish_item("pages", pagina["id"])
    pendentes = indexnow.pendentes()
    assert len(pendentes["removidos"]) == 1 and "aviso" in pendentes["removidos"][0]

    resultado = indexnow.sincronizar(motivo="despublicação")
    assert resultado["removidos"] == 1
    assert resultado["submetidos"] == 1
    assert any("aviso" in url for url in lotes[2])


def test_forcar_reenvia_tudo_mesmo_sem_alteracoes(isolado, com_chave, monkeypatch):
    _publicos(monkeypatch, {f"{SITE}/a": ""})
    lotes = _pedido_falso(monkeypatch)
    indexnow.sincronizar(motivo="teste")
    indexnow.sincronizar(motivo="teste")
    assert len(lotes) == 1

    forcado = indexnow.sincronizar(motivo="forçar", forcar=True)
    assert forcado["submetidos"] == 1
    assert len(lotes) == 2


# ---------------------------------------------------------------------------
# Chave: o interruptor
# ---------------------------------------------------------------------------
def test_sem_chave_nao_anuncia_nem_serve_ficheiro(isolado, monkeypatch):
    monkeypatch.setattr(indexnow, "chave_e_origem", lambda *, fresco=False: ("", "ausente"))
    lotes = _pedido_falso(monkeypatch)

    resultado = indexnow.sincronizar(motivo="teste")
    assert resultado["ativo"] is False
    assert resultado["submetidos"] == 0
    assert lotes == []
    assert indexnow.ficheiro_chave("qualquer") is None
    assert indexnow.estado()["ativo"] is False


def test_interruptor_desligado_nao_anuncia(isolado, monkeypatch):
    """Com chave, mas com o interruptor desligado (o caso do desenvolvimento)."""
    monkeypatch.setattr(indexnow, "chave_e_origem", lambda *, fresco=False: (CHAVE, "teste"))
    monkeypatch.setattr(indexnow, "ligado", lambda: False)
    lotes = _pedido_falso(monkeypatch)

    resultado = indexnow.sincronizar(motivo="teste")
    assert resultado["ativo"] is False
    assert resultado["detalhe"] == "Indexação em tempo real desligada."
    assert lotes == []
    # O ficheiro da chave continua a ser servido: é público e permite verificar
    # a posse do domínio antes de ligar o interruptor.
    assert indexnow.ficheiro_chave(CHAVE) == CHAVE
    assert indexnow.estado()["ligado"] is False


def test_interruptor_ligado_por_ambiente(isolado, monkeypatch):
    monkeypatch.setenv("INDEXNOW_ENABLED", "true")
    assert indexnow.ligado() is True
    monkeypatch.setenv("INDEXNOW_ENABLED", "0")
    assert indexnow.ligado() is False
    monkeypatch.delenv("INDEXNOW_ENABLED")
    assert indexnow.ligado() is False


def test_chave_invalida_e_ignorada(isolado, monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "curta")
    monkeypatch.setattr(indexnow, "_da_administracao", lambda: None)
    monkeypatch.setattr(indexnow, "NOMES_DA_CHAVE", ("INDEXNOW_KEY",))
    monkeypatch.setattr(indexnow, "_cache_chave", (0.0, ("", "")))

    valor, origem = indexnow.chave_e_origem(fresco=True)
    assert valor == ""
    assert origem.endswith("invalida")
    assert indexnow.ativo() is False


def test_chave_do_env_file_e_da_administracao(isolado, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OUTRA=1\nINDEXNOW_KEY=do-ficheiro-env-123\n", encoding="utf-8")
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    monkeypatch.setattr(indexnow, "_ENV_FILES", (env,))
    monkeypatch.setattr(indexnow, "NOMES_DA_CHAVE", ("INDEXNOW_KEY",))
    monkeypatch.setattr(indexnow, "_da_administracao", lambda: None)

    assert indexnow.chave_e_origem(fresco=True) == ("do-ficheiro-env-123", f"env_file:{env.name}")

    # O índice da administração ganha ao `.env`: é o que permite trocar a chave
    # sem mexer na configuração da máquina.
    monkeypatch.setattr(indexnow, "_da_administracao", lambda: "do-indice-123456")
    assert indexnow.chave_e_origem(fresco=True) == ("do-indice-123456", "indice")


def test_ficheiro_da_chave(isolado, com_chave):
    assert indexnow.ficheiro_chave(CHAVE) == CHAVE
    assert indexnow.ficheiro_chave("robots") is None


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def test_pedido_leva_host_chave_e_local_do_ficheiro(isolado, com_chave, monkeypatch):
    _publicos(monkeypatch, {f"{SITE}/a": "2026-01-01"})
    capturado = {}

    class Resposta:
        status = 200

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(pedido, timeout=None):
        capturado["url"] = pedido.full_url
        capturado["corpo"] = json.loads(pedido.data.decode("utf-8"))
        capturado["cabecalho"] = pedido.get_header("Content-type")
        return Resposta()

    monkeypatch.setattr(indexnow.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(indexnow, "_pedido", PEDIDO_REAL)
    indexnow.sincronizar(motivo="teste")

    assert capturado["url"] == indexnow.endpoint()
    assert capturado["corpo"]["host"] == "sabemos.studio"
    assert capturado["corpo"]["key"] == CHAVE
    assert capturado["corpo"]["keyLocation"] == f"{SITE}/{CHAVE}.txt"
    assert capturado["corpo"]["urlList"] == [f"{SITE}/a"]
    assert "json" in (capturado["cabecalho"] or "")


def test_lote_recusado_nao_conta_como_anunciado(isolado, com_chave, monkeypatch):
    _publicos(monkeypatch, {f"{SITE}/a": ""})
    lotes = _pedido_falso(monkeypatch, estado=422, resposta="Key not found on host")

    resultado = indexnow.sincronizar(motivo="teste")
    assert resultado["submetidos"] == 0
    assert resultado["respostas"][0]["estado"] == 422
    assert len(lotes) == 1
    # Continua pendente: uma falha de configuração não pode fazer uma página
    # nunca mais ser anunciada.
    assert indexnow.pendentes()["novos"] == [f"{SITE}/a"]


def test_lotes_de_dez_mil(isolado, com_chave, monkeypatch):
    urls = {f"{SITE}/p/{indice}": "" for indice in range(indexnow.LOTE_MAXIMO + 1)}
    _publicos(monkeypatch, urls)
    lotes = _pedido_falso(monkeypatch)

    indexnow.sincronizar(motivo="teste")
    assert [len(lote) for lote in lotes] == [indexnow.LOTE_MAXIMO, 1]


def test_registo_guarda_a_tentativa(isolado, com_chave, monkeypatch):
    _publicos(monkeypatch, {f"{SITE}/a": ""})
    _pedido_falso(monkeypatch, estado=403, resposta="Unauthorized")

    indexnow.sincronizar(motivo="publicação")
    linhas = [json.loads(linha) for linha in indexnow.REGISTO_PATH.read_text(encoding="utf-8").splitlines()]
    assert linhas and linhas[0]["estado"] == 403
    assert linhas[0]["motivo"] == "publicação"
    assert linhas[0]["amostra"] == [f"{SITE}/a"]
    assert indexnow.registos(3)[0]["estado"] == 403


# ---------------------------------------------------------------------------
# Gancho na escrita do CMS e da loja
# ---------------------------------------------------------------------------
def test_publicar_no_cms_anuncia(isolado, sem_anuncio):
    cms_store.get_settings()  # a semente conta como escrita: consome-a primeiro
    sem_anuncio.clear()

    _publicar_pagina("Nota", "nota")
    assert sem_anuncio == ["escrita do CMS"]


def test_escrever_na_loja_anuncia(isolado, sem_anuncio):
    shop_store.get_settings()
    sem_anuncio.clear()

    shop_store.save_item("products", {"name": "Curso", "price": 25, "status": "publicado"})
    assert sem_anuncio.count("escrita da loja") == 1


def test_despublicar_tambem_anuncia(isolado, sem_anuncio):
    cms_store.get_settings()
    pagina = _publicar_pagina("Nota", "nota")
    sem_anuncio.clear()
    cms_store.unpublish_item("pages", pagina["id"])
    assert sem_anuncio == ["escrita do CMS"]


# ---------------------------------------------------------------------------
# Anúncio em fundo: quem publica não espera pela rede
# ---------------------------------------------------------------------------
def test_anuncio_em_fundo_corre_fora_do_pedido(isolado, com_chave, monkeypatch):
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", ANUNCIAR_REAL)
    feito = threading.Event()
    motivos = []

    def sincronizar(*, motivo="", forcar=False):
        motivos.append(motivo)
        feito.set()
        return {"ativo": True, "submetidos": 0}

    monkeypatch.setattr(indexnow, "sincronizar", sincronizar)
    indexnow.anunciar_em_fundo("teste")

    assert feito.wait(5), "o anúncio não chegou a correr"
    time.sleep(0.05)  # deixa o trabalhador fechar antes de o teste sair
    assert motivos[0] == "teste"
    assert indexnow._a_sincronizar is False  # noqa: SLF001 - estado interno relevante


def test_anuncio_sem_chave_nao_lanca_trabalhador(isolado, monkeypatch):
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", ANUNCIAR_REAL)
    monkeypatch.setattr(indexnow, "chave_e_origem", lambda *, fresco=False: ("", "ausente"))
    correu = []
    monkeypatch.setattr(indexnow, "_trabalhar", lambda motivo: correu.append(motivo))

    indexnow.anunciar_em_fundo("teste")
    time.sleep(0.2)

    assert correu == []
    assert indexnow._a_sincronizar is False  # noqa: SLF001


def test_anuncio_a_meio_nao_se_perde(isolado, com_chave, monkeypatch):
    """Um anúncio pedido durante outro fica marcado, em vez de ser ignorado."""
    monkeypatch.setattr(indexnow, "anunciar_em_fundo", ANUNCIAR_REAL)
    primeiro = threading.Event()
    liberta = threading.Event()
    chamadas = []

    def sincronizar(*, motivo="", forcar=False):
        chamadas.append(motivo)
        if len(chamadas) == 1:
            primeiro.set()
            liberta.wait(5)
        return {"ativo": True, "submetidos": 0}

    monkeypatch.setattr(indexnow, "sincronizar", sincronizar)
    indexnow.anunciar_em_fundo("a")
    assert primeiro.wait(5)
    indexnow.anunciar_em_fundo("b")  # chega enquanto o primeiro corre
    liberta.set()

    limite = time.time() + 5
    while len(chamadas) < 2 and time.time() < limite:
        time.sleep(0.02)
    assert chamadas == ["a", "a"]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _sessao(papel: str = "admin") -> CurrentSession:
    return CurrentSession(
        user=UserResponse(
            id="u1",
            email="admin@exemplo.pt",
            name="Admin",
            role=papel,
            initials="AD",
            status="active",
            locale="pt-PT",
            timezone="Europe/Lisbon",
        ),
        session_id="s-prova",
        token="t-prova",
    )


@pytest.fixture()
def cliente_admin():
    main.app.dependency_overrides[require_admin] = lambda: _sessao()
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(require_admin, None)


def test_estado_exige_administracao(isolado, com_chave):
    cliente = TestClient(main.app)
    assert cliente.get("/indexnow/state").status_code == 401
    assert cliente.post("/indexnow/sync").status_code == 401


def test_estado_e_sincronizacao_pela_rota(isolado, com_chave, monkeypatch, cliente_admin):
    _publicos(monkeypatch, {f"{SITE}/a": ""})
    lotes = _pedido_falso(monkeypatch)

    estado = cliente_admin.get("/indexnow/state").json()
    assert estado["ativo"] is True
    assert estado["host"] == "sabemos.studio"
    assert estado["key_location"] == f"{SITE}/{CHAVE}.txt"
    assert estado["pendentes"]["total"] == 1

    resultado = cliente_admin.post("/indexnow/sync").json()
    assert resultado["submetidos"] == 1
    assert lotes == [[f"{SITE}/a"]]
    assert cliente_admin.get("/indexnow/state").json()["pendentes"]["total"] == 0


def test_ficheiro_da_chave_e_servido_na_raiz(isolado, com_chave):
    cliente = TestClient(main.app)
    resposta = cliente.get(f"/{CHAVE}.txt")
    assert resposta.status_code == 200
    assert resposta.text == CHAVE
    assert resposta.headers["content-type"].startswith("text/plain")
    assert cliente.get("/nao-e-a-chave.txt").status_code == 404
