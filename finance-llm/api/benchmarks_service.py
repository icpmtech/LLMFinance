"""Serviço dos **benchmarks de produtos** (recolha, comparação e publicação).

O que o módulo faz, do princípio ao fim:

1. **Recolha** — cada loja do benchmark é recolhida com o motor do módulo de
   scraping (`scraper_service`): o serviço cria/actualiza uma *fonte* escondida
   por loja (id `bench-<slug>-<loja>`) e corre-a (`execute_run_sync`). Os campos
   extraídos são normalizados para **ofertas** (preço, nome, marca, EAN/SKU…),
   que são indexadas no **índice próprio do benchmark** (`finance_bench_<slug>`
   via `elasticsearch_client`).
2. **Comparação** — `analise()` agrega por chave de produto e responde às
   perguntas do estudo: onde está mais barato, qual a dispersão de preço, quanto
   se poupa e que lojas são mais caras/baratas em média.
3. **Publicação** — `publicar()` cria/actualiza uma **página no CMS** (site
   público) com os resultados do estudo e liga-a à pesquisa ao vivo servida por
   `html_publico()` em `/site/benchmarks/<slug>/pesquisa`.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

from api import benchmarks_store as store
from api import cms_render as render
from api import cms_store as cms
from api import elasticsearch_client as esc
from api import scraper_ai
from api import scraper_service

logger = logging.getLogger(__name__)

#: Nomes de campo que o serviço reconhece automaticamente quando a definição não
#: traz um `field_map` explícito (comparação insensível a acentos/maiúsculas).
_ALIASES_PRECO = ("preco", "preço", "price", "preco_final", "preco_promo", "pvp", "valor")
_ALIASES_PRECO_ANTIGO = ("preco_antigo", "preco_original", "price_original", "preco_sem_desconto")
_ALIASES_NOME = ("nome", "produto", "titulo", "título", "title", "name", "descricao", "descrição")
_ALIASES_DESCRICAO = (
    "descricao",
    "descrição",
    "description",
    "resumo",
    "summary",
    "sinopse",
    "subtitulo",
    "subtítulo",
    "subtitle",
)
_ALIASES_MARCA = ("marca", "brand", "fabricante")
_ALIASES_EAN = ("ean", "gtin", "codigo_barras", "código_de_barras", "barcode")
_ALIASES_SKU = ("sku", "referencia", "referência", "ref", "codigo", "código", "mpn")
_ALIASES_URL = ("url", "link", "href")
_ALIASES_IMAGEM = ("imagem", "image", "foto", "img", "thumbnail")
_ALIASES_DISPONIBILIDADE = ("disponibilidade", "availability", "stock", "estado")
_ALIASES_CATEGORIA = ("categoria", "category", "tipo", "seccao", "secção")

_SEM_ACENTOS = str.maketrans(
    "áàâãäçéèêëíìîïñóòôõöúùûüýÿ", "aaaaaceeeeiiiinooooouuuuyy"
)


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _chave(texto: str) -> str:
    """Chave de comparação: sem acentos, minúsculas e sem pontuação."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    base = "".join(ch for ch in base if not unicodedata.combining(ch)).lower()
    base = re.sub(r"[^a-z0-9]+", " ", base)
    return re.sub(r"\s+", " ", base).strip()


# ---------------------------------------------------------------------------
# Extração de valores
# ---------------------------------------------------------------------------
#: Preço dentro de um texto livre (a moeda antes ou depois, com espaços).
_PRECO_NO_TEXTO = re.compile(
    r"(?:€|EUR|R\$|US\$|\$|£)\s*\d{1,3}(?:[.\s]\d{3})*(?:\s*[.,]\s*\d{1,2})?"
    r"|\d{1,3}(?:[.\s]\d{3})*(?:\s*[.,]\s*\d{1,2})?\s*(?:€|EUR|R\$|US\$|\$|£)",
    re.IGNORECASE,
)


def _sem_tags(valor: Any) -> str:
    """Texto sem etiquetas HTML.

    Rede de segurança: um seletor de **elemento** (em vez de `::text`) devolve o
    HTML do nó, e os `data-v-981a3c18` trazem dígitos que estragavam o preço
    («9813 18 799 , 99»). Recorre-se a isto sobre o que vier do scraper.
    """
    texto = str(valor if valor is not None else "")
    if "<" in texto and ">" in texto:
        texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def preco_para_float(valor: Any) -> Optional[float]:
    """Converte `1.234,56 €`, `€ 12,50` ou `1234.56` em `1234.56`/`12.5`.

    Regra: quando existem **os dois** separadores, o último é o decimal; com um
    só, decide-se pelo número de dígitos à direita (3 dígitos = milhares).

    Quando o texto traz **vários** preços colados (o preço atual e o riscado, como
    a Worten devolve: «€ 799 , 99 € 999 ,99»), fica o primeiro — que é o preço a
    pagar. Sem isto, os separadores de dois números juntavam-se num só
    («799,99999,99») e o valor saía absurdo.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    texto = _sem_tags(valor).strip()
    if not texto:
        return None
    encontrados = _PRECO_NO_TEXTO.findall(texto)
    if len(encontrados) > 1:
        texto = _PRECO_NO_TEXTO.search(texto).group(0)
    texto = re.sub(r"[^\d.,\-]", "", texto).replace(" ", "")
    if not texto or texto in {"-", ".", ","}:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".") if texto.rindex(",") > texto.rindex(".") else texto.replace(",", "")
    elif "," in texto:
        partes = texto.split(",")
        texto = texto.replace(",", ".") if len(partes[-1]) != 3 else texto.replace(",", "")
    elif "." in texto:
        partes = texto.split(".")
        if len(partes) > 2 or len(partes[-1]) == 3:
            texto = texto.replace(".", "")
    try:
        return round(float(texto), 2)
    except ValueError:
        return None


def _campo(campos: Dict[str, Any], *, mapa: Dict[str, Any], chave: str, aliases: Iterable[str]) -> Any:
    """Valor de um campo: primeiro pelo `field_map`, depois por nome conhecido."""

    def limpo(valor: Any) -> Any:
        return _sem_tags(valor) if isinstance(valor, str) else valor

    explicito = mapa.get(chave)
    if explicito and campos.get(explicito) not in (None, ""):
        return limpo(campos[explicito])
    normalizados = {_chave(k): v for k, v in campos.items()}
    for alias in aliases:
        valor = normalizados.get(_chave(alias))
        if valor not in (None, ""):
            return limpo(valor)
    return None


def _chave_produto(
    *, match_on: str, ean: Optional[str], sku: Optional[str], nome: str, url: str, item_id: str
) -> str:
    """O que faz «o mesmo produto» entre lojas (EAN → SKU → nome → URL)."""
    if match_on == "ean" and ean:
        digitos = re.sub(r"\D", "", str(ean))
        if len(digitos) >= 8:
            return f"ean:{digitos}"
    if match_on == "sku" and sku:
        return f"sku:{_chave(sku)}"
    if match_on == "url" and url:
        return f"url:{url.strip()}"
    if nome:
        return f"nome:{_chave(nome)[:80]}"
    return f"item:{_chave(item_id)[:80]}"


def normalizar_oferta(
    item: Dict[str, Any], *, loja: Dict[str, Any], benchmark: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Converte um item recolhido numa oferta comparável (ou `None` se sem preço)."""
    campos = item.get("data") if isinstance(item.get("data"), dict) else {}
    mapa = benchmark.get("field_map") or {}

    preco = preco_para_float(_campo(campos, mapa=mapa, chave="price", aliases=_ALIASES_PRECO))
    if preco is None:
        # Último recurso: procurar um número com «€» no resumo/título.
        for texto in (item.get("summary"), item.get("title")):
            if texto and "€" in str(texto):
                preco = preco_para_float(str(texto).split("€")[-2] if str(texto).count("€") > 1 else str(texto))
                if preco is not None:
                    break
    if preco is None or preco <= 0:
        return None

    nome = str(_campo(campos, mapa=mapa, chave="product_name", aliases=_ALIASES_NOME) or item.get("title") or "").strip()
    if not nome:
        return None
    descricao = _campo(campos, mapa=mapa, chave="description", aliases=_ALIASES_DESCRICAO)
    if not descricao and item.get("summary"):
        descricao = item.get("summary")
    marca = _campo(campos, mapa=mapa, chave="brand", aliases=_ALIASES_MARCA)
    ean = _campo(campos, mapa=mapa, chave="ean", aliases=_ALIASES_EAN)
    sku = _campo(campos, mapa=mapa, chave="sku", aliases=_ALIASES_SKU)
    url = str(_campo(campos, mapa=mapa, chave="url", aliases=_ALIASES_URL) or item.get("url") or "").strip()
    imagem = _campo(campos, mapa=mapa, chave="image", aliases=_ALIASES_IMAGEM)
    disponibilidade = _campo(campos, mapa=mapa, chave="availability", aliases=_ALIASES_DISPONIBILIDADE)
    categoria = _campo(campos, mapa=mapa, chave="category", aliases=_ALIASES_CATEGORIA)
    original = preco_para_float(_campo(campos, mapa=mapa, chave="price_original", aliases=_ALIASES_PRECO_ANTIGO))

    item_id = str(item.get("item_id") or url or f"{nome}|{preco}")
    disponibilidade_txt = _chave(disponibilidade) if disponibilidade else ""
    em_stock = not any(palavra in disponibilidade_txt for palavra in ("esgotado", "indisponivel", "sem stock", "out of stock"))

    # Os sites devolvem muitas vezes caminhos relativos (`/media/x.jpg`): sem os
    # tornar absolutos, a imagem e a ligação não abrem a partir da plataforma.
    base = str(loja.get("url") or item.get("url") or "")
    if url and base and not url.lower().startswith(("http://", "https://")):
        url = urljoin(base, url)
    imagem_abs = str(imagem).strip() if imagem else ""
    if imagem_abs and base and not imagem_abs.lower().startswith(("http://", "https://")):
        imagem_abs = urljoin(base, imagem_abs)

    oferta: Dict[str, Any] = {
        "item_id": item_id,
        "product_key": _chave_produto(
            match_on=str(benchmark.get("match_on") or "nome"),
            ean=str(ean) if ean else None,
            sku=str(sku) if sku else None,
            nome=nome,
            url=url,
            item_id=item_id,
        ),
        "product_name": nome[:512],
        "description": str(descricao).strip()[:2000] if descricao else None,
        "brand": str(marca).strip()[:120] if marca else None,
        "category": str(categoria).strip()[:120] if categoria else None,
        "sku": str(sku).strip()[:80] if sku else None,
        "ean": str(ean).strip()[:40] if ean else None,
        "store_id": loja.get("id"),
        "store_name": loja.get("name"),
        "url": url,
        "image": imagem_abs or None,
        "availability": str(disponibilidade).strip()[:120] if disponibilidade else None,
        "in_stock": em_stock,
        "currency": benchmark.get("currency") or "EUR",
        "price": preco,
        "price_original": original if original and original > preco else None,
        "source_id": item.get("source_id"),
        "run_id": item.get("run_id"),
        "collected_at": item.get("scraped_at") or _agora(),
        "extra": {k: v for k, v in campos.items() if isinstance(v, (str, int, float, bool))},
    }
    if oferta["price_original"]:
        oferta["discount_pct"] = round(100.0 * (oferta["price_original"] - preco) / oferta["price_original"], 2)
    return oferta


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def _fonte_da_loja(benchmark: Dict[str, Any], loja: Dict[str, Any]) -> Optional[str]:
    """Garante a fonte de scraping da loja e devolve o seu id.

    Se a loja aponta para uma fonte já existente (`source_id`), usa-se essa; caso
    contrário cria-se/actualiza uma fonte própria do benchmark, com id estável
    (`bench-<slug>-<loja>`) para as recolhas seguintes actualizarem a mesma.
    """
    apontada = str(loja.get("source_id") or "").strip()
    if apontada:
        if scraper_service.get_source(apontada):
            return apontada
        logger.warning("Benchmark %s: a fonte %s não existe; a usar a definição da loja", benchmark["slug"], apontada)

    config = loja.get("scraper") if isinstance(loja.get("scraper"), dict) else {}
    url = str(loja.get("url") or config.get("url") or "").strip()
    if not url:
        return None
    campos = config.get("fields")
    if not campos:
        raise ValueError(
            f"A loja «{loja.get('name')}» não tem campos a extrair. Escolha um modelo de recolha "
            "ou indique os seletores dos preços."
        )
    identificador = f"bench-{benchmark['slug']}-{loja.get('id')}"
    payload = {
        "id": identificador,
        "name": f"{benchmark.get('name')} · {loja.get('name')}",
        "description": f"Recolha criada pelo benchmark «{benchmark.get('name')}».",
        "url": url,
        "fetcher": config.get("fetcher") or "http",
        "list": config.get("list") or {},
        "fields": campos,
        "pagination": config.get("pagination") or {},
        "options": config.get("options") or {},
        "respect_robots": config.get("respect_robots", True),
        "tags": ["benchmark", benchmark["slug"], str(loja.get("id"))],
        "id_fields": config.get("id_fields") or ["url"],
        "title_field": config.get("title_field") or (campos[0].get("name") if campos else ""),
        "text_field": config.get("text_field") or "",
        "detail": config.get("detail") or {"enabled": False},
        "enabled": True,
        # Sem `sink_index`: o benchmark indexa as ofertas normalizadas no índice dele.
        "sink_index": "",
    }
    fonte = scraper_service.upsert_source(payload)
    return str(fonte.get("id") or identificador)


def recolher(
    slug: str,
    *,
    lojas: Optional[List[str]] = None,
    limite_por_loja: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Corre a recolha das lojas do benchmark e indexa as ofertas no índice dele."""
    benchmark = store.obter(slug)
    if not benchmark:
        return {"error": "Benchmark não encontrado"}
    # Sem limite indicado vale o da configuração do módulo (é lá que se evita
    # trazer 5 000 ofertas sem querer de uma listagem com paginação infinita).
    configuracao = store.obter_configuracao()
    limite = int(limite_por_loja or configuracao.get("limite_por_loja") or 500)
    pausa = float(configuracao.get("pausa_segundos") or 0)
    esc.ensure_benchmark_items_index(slug)

    selecionadas = {str(x).strip() for x in (lojas or []) if str(x).strip()}
    detalhes: List[Dict[str, Any]] = []
    total_ofertas = 0
    total_indexadas = 0
    erros: List[str] = []

    for loja in benchmark.get("stores") or []:
        loja_id = str(loja.get("id") or "")
        if selecionadas and loja_id not in selecionadas:
            continue
        if not loja.get("enabled", True):
            detalhes.append({"store_id": loja_id, "store_name": loja.get("name"), "status": "desativada"})
            continue
        registo: Dict[str, Any] = {"store_id": loja_id, "store_name": loja.get("name")}
        try:
            source_id = _fonte_da_loja(benchmark, loja)
            if not source_id:
                registo.update({"status": "erro", "error": "Loja sem URL de recolha."})
                detalhes.append(registo)
                erros.append(f"{loja.get('name')}: sem URL.")
                continue
            corrida = scraper_service.execute_run_sync(source_id, trigger="benchmark", user_id=user_id)
            registo.update(
                {
                    "source_id": source_id,
                    "run_id": corrida.get("run_id"),
                    "items": corrida.get("items_count", 0),
                    "recolha": corrida.get("status"),
                }
            )
            lidos = scraper_service.read_run_items(
                str(corrida.get("run_id") or ""), source_id, limit=max(1, int(limite_por_loja))
            )
            ofertas = []
            for item in lidos.get("items") or []:
                bruto = dict(item)
                bruto.setdefault("source_id", source_id)
                bruto.setdefault("run_id", corrida.get("run_id"))
                oferta = normalizar_oferta(bruto, loja=loja, benchmark=benchmark)
                if oferta:
                    ofertas.append(oferta)
            # Recolha de uma loja substitui o que essa loja tinha (sem duplicar).
            esc.delete_benchmark_items(slug, store_id=loja_id)
            resultado = esc.index_benchmark_items(slug, ofertas)
            indexadas = int(resultado.get("indexed") or 0)
            total_ofertas += len(ofertas)
            total_indexadas += indexadas
            registo.update({"ofertas": len(ofertas), "indexadas": indexadas, "status": "ok"})
            if resultado.get("error"):
                registo["index_error"] = resultado["error"]
        except Exception as exc:  # noqa: BLE001 - uma loja má não trava o benchmark
            logger.exception("Recolha da loja %s do benchmark %s falhou", loja_id, slug)
            registo.update({"status": "erro", "error": f"{type(exc).__name__}: {exc}"})
            erros.append(f"{loja.get('name')}: {exc}")
        detalhes.append(registo)
        if pausa:
            # Respiro entre lojas (configurável): recolhas seguidas do mesmo site
            # são a forma mais rápida de apanhar um bloqueio.
            time.sleep(pausa)

    resumo = {
        "slug": slug,
        "at": _agora(),
        "stores": detalhes,
        "offers": total_ofertas,
        "indexed": total_indexadas,
        "errors": erros,
    }
    store.marcar_recolha(slug, resumo)
    return resumo


#: Símbolo monetário → código ISO. Evita mostrar «51,77 EUR» numa loja inglesa.
_MOEDA_POR_SIMBOLO = (
    ("R$", "BRL"),
    ("US$", "USD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("$", "USD"),
)


def _moeda_da_amostra(previsao: Dict[str, Any]) -> Optional[str]:
    """Deduz a moeda a partir do símbolo que aparece nos preços da página."""
    for item in (previsao.get("items") or [])[:10]:
        dados = item.get("data") if isinstance(item.get("data"), dict) else {}
        for valor in dados.values():
            texto = str(valor or "")
            for simbolo, moeda in _MOEDA_POR_SIMBOLO:
                if simbolo in texto:
                    return moeda
    return None


# ---------------------------------------------------------------------------
# Sonda de uma loja (com IA opcional)
# ---------------------------------------------------------------------------
def robots_permite(url: str, agente: str = "IQOSBenchmarkBot/1.0") -> Dict[str, Any]:
    """Diz se o `robots.txt` do site permite recolher este endereço.

    É um aviso ao utilizador (a recolha também respeita o ficheiro por si): sem
    isto, uma sonda «bem-sucedida» num caminho proibido dava a ideia errada.
    """
    import urllib.robotparser
    from urllib.parse import urlparse

    partes = urlparse(url)
    if not partes.scheme.startswith("http"):
        return {"permitido": None, "detalhe": "Endereço sem http(s)."}
    try:
        import httpx

        resposta = httpx.get(f"{partes.scheme}://{partes.netloc}/robots.txt", timeout=15, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return {"permitido": None, "detalhe": f"robots.txt inacessível ({type(exc).__name__})."}
    if resposta.status_code >= 400:
        return {"permitido": None, "detalhe": f"sem robots.txt (HTTP {resposta.status_code})."}
    leitor = urllib.robotparser.RobotFileParser()
    leitor.parse(resposta.text.splitlines())
    permitido = leitor.can_fetch(agente, url)
    return {
        "permitido": permitido,
        "detalhe": "permitido pelo robots.txt" if permitido else "PROIBIDO pelo robots.txt — não recolher este caminho.",
    }


async def sondar_loja(
    url: str,
    *,
    fetcher: Optional[str] = None,
    hint: str = "",
    use_ai: Optional[bool] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
    benchmark: Optional[str] = None,
    nome_loja: str = "",
) -> Dict[str, Any]:
    """Analisa uma página de loja e devolve tudo o que é preciso para a recolher.

    Devolve a definição de recolha **pronta a guardar numa loja do benchmark**,
    o mapa de campos (preço/título/imagem/descrição/…) e uma **amostra de
    ofertas** já normalizadas — é o que a interface mostra antes de o utilizador
    aceitar a proposta.

    O que não vier indicado toma o valor da **configuração do módulo** (fetcher,
    usar IA, fornecedor/modelo, contexto): evita repetir a mesma escolha em cada
    sonda.
    """
    configuracao = store.obter_configuracao()
    fetcher = fetcher or str(configuracao.get("fetcher") or "dynamic")
    use_ai = bool(configuracao.get("use_ai", True)) if use_ai is None else use_ai
    provider = provider or (str(configuracao.get("provider") or "") or None)
    model = model or (str(configuracao.get("model") or "") or None)
    hint = hint or str(configuracao.get("hint") or "")

    aviso_robots = robots_permite(url)
    resultado = await scraper_ai.suggest_product_source(
        url,
        hint=hint,
        fetcher=fetcher or "http",
        user_id=user_id,
        provider=provider,
        model=model,
        use_ai=use_ai,
    )
    definicao = resultado.get("definition") or {}
    campos = [str(campo.get("name") or "") for campo in (definicao.get("fields") or [])]
    # Mapa campo do benchmark → campo extraído, pela ordem em que o módulo os conhece.
    mapa: Dict[str, str] = {}
    equivalencias = {
        "price": "preco",
        "price_original": "preco_antigo",
        "product_name": "titulo",
        "description": "descricao",
        "brand": "marca",
        "category": "categoria",
        "ean": "ean",
        "sku": "sku",
        "url": "url",
        "image": "imagem",
        "availability": "disponibilidade",
    }
    for chave, campo in equivalencias.items():
        if campo in campos:
            mapa[chave] = campo

    # Amostra normalizada: é isto que o estudo vai mostrar depois de recolher.
    loja_teste = {"id": "sonda", "name": nome_loja or url, "url": url}
    benchmark_teste = {
        "slug": benchmark or "sonda",
        "match_on": "nome",
        "currency": _moeda_da_amostra(resultado.get("preview") or {}) or "EUR",
        "field_map": mapa,
    }
    amostra: List[Dict[str, Any]] = []
    previsao = resultado.get("preview") or {}
    for item in (previsao.get("items") or [])[:6]:
        oferta = normalizar_oferta(item, loja=loja_teste, benchmark=benchmark_teste)
        if oferta:
            amostra.append(
                {
                    "product_name": oferta.get("product_name"),
                    "price": oferta.get("price"),
                    "currency": oferta.get("currency"),
                    "image": oferta.get("image"),
                    "url": oferta.get("url"),
                    "description": oferta.get("description"),
                    "brand": oferta.get("brand"),
                    "availability": oferta.get("availability"),
                    "product_key": oferta.get("product_key"),
                }
            )

    encontrados = resultado.get("heuristic_fields") or {}
    avisos: List[str] = []
    if aviso_robots.get("permitido") is False:
        avisos.append(str(aviso_robots.get("detalhe")))
    if not amostra and resultado.get("ok"):
        avisos.append(
            "A proposta não devolveu ofertas normalizadas: falta o preço ou o nome do produto nos campos."
        )
    if resultado.get("ai_error"):
        avisos.append(f"IA indisponível: {resultado['ai_error']}")

    return {
        "ok": bool(resultado.get("ok")) and bool(amostra),
        "url": url,
        "titulo_pagina": resultado.get("title"),
        "origem": resultado.get("origin"),
        "ai": resultado.get("ai"),
        "robots": aviso_robots,
        "http_status": resultado.get("http_status"),
        "bloqueado": bool(resultado.get("blocked")),
        "campos": campos,
        "field_map": mapa,
        "campos_detetados": {
            chave: (valor or {}).get("selector") if isinstance(valor, dict) else None
            for chave, valor in encontrados.items()
        },
        "candidatos_lista": resultado.get("analysis") or [],
        "tentativas": resultado.get("tried") or [],
        "amostra": amostra,
        "loja_sugerida": {
            "name": nome_loja or (resultado.get("title") or "").split("|")[0].strip() or url,
            "url": url,
            "scraper": {
                "fetcher": fetcher or "http",
                "list": definicao.get("list") or {},
                "fields": definicao.get("fields") or [],
                "pagination": definicao.get("pagination") or {"max_pages": 1},
                "respect_robots": True,
                "id_fields": definicao.get("id_fields") or ["url"],
                "title_field": definicao.get("title_field") or "titulo",
            },
        },
        "notas": (resultado.get("ai") or {}).get("notes") or "",
        "avisos": avisos,
        "erro": None if resultado.get("ok") else resultado.get("error"),
    }


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def analise(slug: str, *, tamanho: int = 200) -> Dict[str, Any]:
    """KPIs, ranking de lojas e oportunidades de poupança do benchmark."""
    benchmark = store.obter(slug)
    if not benchmark:
        return {"error": "Benchmark não encontrado"}

    lojas = esc.benchmark_store_stats(slug)
    comparacao = esc.benchmark_product_comparison(slug, order="dispersao", size=tamanho, from_=0, min_stores=1)
    if comparacao.get("error"):
        return {"error": comparacao["error"], "benchmark": benchmark}
    produtos = comparacao.get("items") or []
    comparaveis = [p for p in produtos if int(p.get("stores") or 0) >= 2]
    exclusivos = [p for p in produtos if int(p.get("stores") or 0) == 1]

    dispersoes = [p["spread_pct"] for p in comparaveis if p.get("spread_pct") is not None]
    poupanca = [p["saving_abs"] for p in comparaveis if p.get("saving_abs") is not None]
    media_global = (
        round(sum(l["preco_medio"] for l in lojas if l.get("preco_medio")) / len([l for l in lojas if l.get("preco_medio")]), 2)
        if any(l.get("preco_medio") for l in lojas)
        else None
    )
    for loja in lojas:
        # Índice de preço: 100 = média do benchmark; abaixo disso é mais barata.
        loja["indice_preco"] = round(100.0 * loja["preco_medio"] / media_global, 1) if (media_global and loja.get("preco_medio")) else None

    return {
        "benchmark": {
            "slug": benchmark.get("slug"),
            "name": benchmark.get("name"),
            "category": benchmark.get("category"),
            "currency": benchmark.get("currency"),
            "match_on": benchmark.get("match_on"),
            "public": benchmark.get("public"),
            "public_path": benchmark.get("public_path"),
            "last_run": benchmark.get("last_run"),
            "stores_defined": len(benchmark.get("stores") or []),
        },
        "kpis": {
            "stores": len(lojas),
            "offers": sum(int(l.get("ofertas") or 0) for l in lojas),
            "products": len(produtos),
            "comparable_products": len(comparaveis),
            "single_store_products": len(exclusivos),
            "avg_spread_pct": round(sum(dispersoes) / len(dispersoes), 2) if dispersoes else None,
            "max_spread_pct": max(dispersoes) if dispersoes else None,
            "potential_saving_eur": round(sum(poupanca), 2) if poupanca else None,
            "avg_price": media_global,
        },
        "stores": lojas,
        "opportunities": comparaveis[:15],
        "exclusives": exclusivos[:10],
    }


# ---------------------------------------------------------------------------
# Publicação no site (CMS) e página pública com pesquisa
# ---------------------------------------------------------------------------
def _parent_page(autor: str) -> Dict[str, Any]:
    """Página-mãe «Benchmarks» no CMS (criada à primeira publicação)."""
    for pagina in (cms.list_items("pages").get("items") or []):
        if str(pagina.get("slug") or "").strip() == "benchmarks":
            return pagina
    return cms.save_item(
        "pages",
        {
            "title": "Benchmarks",
            "slug": "benchmarks",
            "status": "publicado",
            "show_in_menu": True,
            "menu_order": 30,
            "excerpt": "Estudos de preço: o mesmo produto comparado em várias lojas.",
            "blocks": [
                {
                    "type": "hero",
                    "data": {
                        "title": "Benchmarks de produtos",
                        "subtitle": "O mesmo produto comparado entre lojas, com o preço e a data de recolha à vista.",
                    },
                },
                {
                    "type": "texto",
                    "data": {
                        "title": "Como ler estes estudos",
                        "markdown": (
                            "Cada benchmark recolhe os preços publicados por várias lojas, normaliza-os para o "
                            "mesmo produto e mostra o melhor preço, a dispersão entre lojas e quanto se poupa ao "
                            "escolher a oferta mais barata. Os dados são recolhidos automaticamente dos sites e "
                            "podem estar desactualizados — confirme sempre na loja antes de decidir."
                        ),
                    },
                },
            ],
        },
        author=autor,
    )


def _media_por_ficheiro(nome: str) -> str:
    """Id do media com este ficheiro na biblioteca do CMS (vazio se não existir).

    Os diagramas entram com o código (`editorial.SEED_MEDIA`) mas o id é gerado
    por instalação — por isso procura-se pelo nome do ficheiro e não por id.
    """
    for item in (cms.list_items("media").get("items") or []):
        if str(item.get("filename") or "") == nome:
            return str(item.get("id") or "")
    return ""


def _pagina_existe(page_id: str) -> bool:
    """`True` se a página do CMS existir **nesta** instalação.

    O `cms_page_id` guardado num benchmark pode ter vindo de outra instalação
    (a definição foi migrada do PC para a VM, com o id do CMS do PC): aqui não
    há página nenhuma com ele, e passá-lo ao `save_item`/`publish_item` levanta
    `KeyError` — que o painel mostrava como 500. Sem página, publica-se uma nova.
    """
    if not page_id:
        return False
    try:
        cms.get_item("pages", page_id)
    except KeyError:
        return False
    return True


def publicar(slug: str, *, autor: str = "") -> Dict[str, Any]:
    """Publica o benchmark: página no CMS + marca-o como público."""
    estudo = analise(slug)
    if estudo.get("error"):
        return estudo
    benchmark = estudo["benchmark"]
    kpis = estudo["kpis"]
    moeda = benchmark.get("currency") or "EUR"
    caminho = f"benchmarks/{benchmark['slug']}"
    ligacao = f"/site/benchmarks/{benchmark['slug']}/pesquisa"

    def _eur(valor: Any) -> str:
        return f"{float(valor):,.2f} {moeda}".replace(",", " ") if valor is not None else "—"

    linhas: List[List[str]] = []
    for produto in estudo["opportunities"][:25]:
        melhor = produto.get("best") or {}
        linhas.append(
            [
                str(produto.get("product_name") or "")[:70],
                str(produto.get("brand") or "—"),
                _eur(produto.get("price_min")),
                _eur(produto.get("price_max")),
                f"{produto.get('spread_pct')}%" if produto.get("spread_pct") is not None else "—",
                str(melhor.get("store_name") or "—"),
                f"{int(produto.get('stores') or 0)} lojas",
            ]
        )

    blocos: List[Dict[str, Any]] = [
        {
            "type": "hero",
            "data": {
                "title": benchmark.get("name") or "Benchmark",
                "subtitle": f"{kpis['products']} produtos em {kpis['stores']} lojas"
                + (f" · dispersão média de {kpis['avg_spread_pct']}%" if kpis.get("avg_spread_pct") else ""),
            },
        },
        {
            "type": "destaques",
            "data": {
                "title": "O que este estudo mostra",
                "items": [
                    {"title": f"{kpis['offers']}", "text": "ofertas recolhidas"},
                    {"title": f"{kpis['products']}", "text": "produtos no estudo"},
                    {"title": f"{kpis['comparable_products']}", "text": "produtos em duas ou mais lojas"},
                    {
                        "title": _eur(kpis.get("potential_saving_eur")),
                        "text": "poupança somada escolhendo sempre o mais barato",
                    },
                ],
            },
        },
    ]
    # Sem o diagrama instalado, o estudo sai sem figura em vez de rebentar.
    diagrama = _media_por_ficheiro("diagrama-comparacao-lojas.svg")
    if diagrama:
        blocos.append(
            {
                "type": "imagem",
                "data": {
                    "media_id": diagrama,
                    "alt": "Índice de preço por loja, com 100 a valer a média do estudo",
                    "caption": "Como se lê um benchmark: dispersão entre lojas e melhor preço assinalado.",
                },
            }
        )
    if linhas:
        blocos.append(
            {
                "type": "tabela",
                "data": {
                    "title": "Onde está mais barato",
                    "head": ["Produto", "Marca", "Mínimo", "Máximo", "Dispersão", "Loja mais barata", "Cobertura"],
                    "rows": linhas,
                },
            }
        )
    if estudo.get("stores"):
        blocos.append(
            {
                "type": "tabela",
                "data": {
                    "title": "Lojas (índice de preço: 100 = média do estudo)",
                    "head": ["Loja", "Ofertas", "Produtos", "Preço médio", "Índice"],
                    "rows": [
                        [
                            str(loja.get("store_name") or loja.get("store_id")),
                            str(loja.get("ofertas") or 0),
                            str(loja.get("produtos") or 0),
                            _eur(loja.get("preco_medio")),
                            f"{loja.get('indice_preco')}" if loja.get("indice_preco") is not None else "—",
                        ]
                        for loja in estudo["stores"]
                    ],
                },
            }
        )
    if not linhas:
        blocos.append(
            {
                "type": "aviso",
                "data": {
                    "tone": "amber",
                    "text": "Ainda não há ofertas recolhidas neste benchmark. Corra a recolha antes de publicar.",
                },
            }
        )
    recolha_em = ((benchmark.get("last_run") or {}).get("at") or "")[:19]
    blocos.extend(
        [
            {
                "type": "texto",
                "data": {
                    "title": "Metodologia",
                    "markdown": (
                        f"Os preços são recolhidos automaticamente dos sites das lojas e normalizados por "
                        f"**{benchmark.get('match_on')}**. Última recolha: **{recolha_em or 'sem registo'}**. "
                        "Preços com IVA incluído quando o site o indica. Este estudo não é uma recomendação de compra."
                    ),
                },
            },
            {
                "type": "cta",
                "data": {
                    "title": "Comparar ao vivo",
                    "text": "Filtre por loja, procure um produto e veja todas as ofertas recolhidas.",
                    "button_label": "Abrir a pesquisa do benchmark",
                    "button_href": ligacao,
                },
            },
        ]
    )

    mae = _parent_page(autor)
    # Reaproveitar a página já publicada (por id, ou pelo caminho, quando o
    # benchmark foi apagado e recriado): sem isto, o CMS acrescenta «-2» ao slug e
    # o site fica com duas páginas para o mesmo estudo.
    definicao = store.obter(slug) or {}
    page_id = str(definicao.get("cms_page_id") or "")
    if page_id and not _pagina_existe(page_id):
        logger.warning(
            "A página %s do benchmark %s não existe nesta instalação (id de outra origem); "
            "a publicação resolve a página pelo caminho.",
            page_id,
            slug,
        )
        page_id = ""
    if not page_id:
        orfa = cms.resolve_page_by_path(caminho, published_only=False)
        page_id = str((orfa or {}).get("id") or "") if isinstance(orfa, dict) else ""
    payload_pagina: Dict[str, Any] = {
        "title": benchmark.get("name") or "Benchmark",
        "slug": benchmark.get("slug"),
        "parent_id": mae.get("id"),
        # Publica-se logo: a chamada a `publish_item` a seguir é o que deixa o
        # registo de auditoria e a data de publicação no CMS.
        "status": "publicado",
        "excerpt": f"Comparação de preços: {kpis['products']} produtos em {kpis['stores']} lojas.",
        "seo": {
            "description": f"Benchmark de preços de {benchmark.get('name')}: melhor loja, dispersão e poupança.",
            "keywords": ["benchmark", "preços", str(benchmark.get("category") or "produtos")],
        },
        "blocks": blocos,
    }
    if page_id:
        payload_pagina["id"] = page_id
    pagina = cms.save_item("pages", payload_pagina, author=autor)
    if pagina.get("error"):
        return pagina
    publicado = cms.publish_item("pages", pagina.get("id"), author=autor)
    if publicado.get("error"):
        return publicado

    # O caminho público é o que o **CMS** calculou (normaliza o slug à maneira
    # dele, com o slug do ascendente à frente). Construí-lo aqui dava ligações
    # partidas sempre que as duas normalizações divergissem.
    final = cms.get_item("pages", str(pagina.get("id"))) or publicado
    caminho = str(final.get("path") or caminho)

    guardado = store.marcar_publicacao(
        slug, page_id=str(pagina.get("id") or ""), caminho=caminho, publico=True
    )
    return {
        "slug": slug,
        "public": True,
        "page_id": pagina.get("id"),
        "path": caminho,
        "url": f"/site/{caminho}",
        "search_url": ligacao,
        "benchmark": guardado or {},
    }


def despublicar(slug: str, *, autor: str = "") -> Dict[str, Any]:
    """Retira o benchmark do site (a página do CMS fica arquivada)."""
    benchmark = store.obter(slug)
    if not benchmark:
        return {"error": "Benchmark não encontrado"}
    page_id = str(benchmark.get("cms_page_id") or "")
    if page_id and not _pagina_existe(page_id):
        logger.warning(
            "A página %s do benchmark %s não existe nesta instalação (id de outra origem); "
            "retira-se só a marca de público.",
            page_id,
            slug,
        )
        page_id = ""
    if page_id:
        cms.unpublish_item("pages", page_id, author=autor)
        resultado = cms.save_item("pages", {"id": page_id, "status": "arquivado"}, author=autor)
        if resultado.get("error"):
            logger.warning("Não foi possível arquivar a página %s: %s", page_id, resultado["error"])
    guardado = store.marcar_publicacao(slug, page_id=page_id, caminho=str(benchmark.get("public_path") or ""), publico=False)
    return {"slug": slug, "public": False, "benchmark": guardado or {}}


# ---------------------------------------------------------------------------
# Página pública com pesquisa (HTML servido pelo módulo)
# ---------------------------------------------------------------------------
# Estilos do **conteúdo** da página. O cabeçalho, rodapé e envolvente do site
# vêm do `_layout()` do CMS (`cms_render.py`), para a página pública do
# benchmark usar o mesmo menu de navegação e rodapé das restantes páginas.
# Os estilos abaixo usam as variáveis do CMS (--bg, --surface, --text, etc.)
# para integrar-se no tema claro/escuro escolhido no site.
_ESTILO = """
.bench-wrap { max-width: 1200px; margin: 0 auto; }
.bench-hero { padding: 32px 0 22px; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
.bench-hero h1 { margin: 0 0 10px; font-size: 2rem; letter-spacing: -0.02em; }
.bench-hero .lead { color: var(--muted); margin: 0; font-size: 1.05rem; }
.bench-grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 26px 0; }
.bench-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
             box-shadow: var(--shadow); padding: 18px; transition: transform .12s ease, box-shadow .12s ease; }
.bench-kpi:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,.08); }
.bench-kpi b { display: block; font-size: 1.7rem; color: var(--accent); margin-bottom: 4px; }
.bench-kpi span { color: var(--muted); font-size: .82rem; }
form.bench-pesquisa { display: flex; flex-wrap: wrap; gap: 14px; align-items: end;
                      background: var(--surface); border: 1px solid var(--border);
                      border-radius: var(--radius); box-shadow: var(--shadow); padding: 18px; }
form.bench-pesquisa label { display: flex; flex-direction: column; gap: 6px; font-size: .86rem; color: var(--muted); font-weight: 500; }
.bench-pesquisa input, .bench-pesquisa select { font: inherit; color: var(--text); background: var(--bg);
                        border: 1px solid var(--border); border-radius: 12px; padding: 11px 14px; min-width: 180px; }
.bench-pesquisa input:focus, .bench-pesquisa select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(13,148,136,.12); }
.bench-pesquisa button { background: var(--accent); border: 1px solid var(--accent); color: #fff;
                         font-weight: 700; border-radius: 999px; padding: 11px 24px; cursor: pointer; transition: filter .15s ease; }
.bench-pesquisa button:hover { filter: brightness(1.08); }
.bench-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow); }
.bench-table { width: 100%; min-width: 760px; border-collapse: separate; border-spacing: 0; font-size: .94rem; }
.bench-table th, .bench-table td { text-align: left; padding: 14px 16px; border-bottom: 1px solid var(--border); vertical-align: top; }
.bench-table th { position: sticky; top: 0; background: var(--surface); color: var(--muted); font-weight: 700; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; z-index: 1; }
.bench-table tbody tr { transition: background .1s ease; }
.bench-table tbody tr:nth-child(even) { background: rgba(0,0,0,.02); }
.bench-table tbody tr:hover { background: rgba(13,148,136,.06); }
.bench-table td:first-child { width: 38%; min-width: 260px; }
.bench-table td:nth-child(2), .bench-table td:nth-child(7) { white-space: nowrap; }
.bench-table td:nth-child(3), .bench-table td:nth-child(4), .bench-table td:nth-child(5), .bench-table td:nth-child(6) { text-align: right; white-space: nowrap; }
.bench-min { color: #16a34a; font-weight: 800; }
.bench-max { color: #dc2626; font-weight: 700; }
.bench-avg { color: var(--text); font-weight: 600; }
.bench-tag { display: inline-block; padding: 3px 10px; border-radius: 999px; background: var(--code); color: var(--text); font-size: .76rem; font-weight: 600; }
.bench-produto { display: flex; gap: 14px; align-items: flex-start; }
.bench-thumb { width: 56px; height: 56px; flex: 0 0 56px; border-radius: 12px; object-fit: contain;
               background: var(--bg); border: 1px solid var(--border); }
.bench-thumb.vazio { display: block; border-style: dashed; }
.bench-nome { font-weight: 700; font-size: .98rem; line-height: 1.35; }
.bench-nome a { color: var(--text); text-decoration: none; }
.bench-nome a:hover { color: var(--accent); text-decoration: underline; }
.bench-descricao { display: block; margin-top: 5px; color: var(--muted); font-size: .84rem;
                   max-width: 520px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2;
                   -webkit-box-orient: vertical; line-height: 1.4; }
.bench-stores { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; color: var(--text); }
.bench-store-best { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; }
.bench-store-best::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #16a34a; }
.bench-rodape { color: var(--muted); font-size: .86rem; margin-top: 24px; line-height: 1.5; }
.bench-vazio { background: var(--surface); border: 1px dashed var(--border); border-radius: var(--radius); padding: 28px; text-align: center; color: var(--muted); }
.bench-cards { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); margin: 24px 0; }
.bench-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
              box-shadow: var(--shadow); padding: 22px; }
.bench-card h2 { margin: 0 0 18px; font-size: 1.08rem; letter-spacing: -.01em; }
.bench-card .muted { color: var(--muted); font-size: .85rem; }
.bench-bar-row { display: grid; grid-template-columns: 100px 1fr 46px; gap: 10px; align-items: center; margin-bottom: 12px; }
.bench-bar-row .label { font-size: .88rem; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bench-bar-track { background: var(--code); border-radius: 999px; height: 18px; position: relative; }
.bench-bar-fill { height: 100%; border-radius: 999px; background: #94a3b8; min-width: 4px; }
.bench-bar-fill.best { background: var(--accent); }
.bench-bar-marker { position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--text); border-radius: 2px; }
.bench-bar-value { font-size: .82rem; color: var(--muted); text-align: right; font-weight: 700; }
.bench-index-axis { display: flex; justify-content: space-between; font-size: .75rem; color: var(--muted); margin: 8px 0 16px; padding: 0 90px 0 100px; }
.bench-price-row { display: grid; grid-template-columns: 100px 1fr 90px; gap: 10px; align-items: center; margin-bottom: 12px; }
.bench-price-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), #0d9488); min-width: 4px; }
.bench-price-fill.second { background: linear-gradient(90deg, #14b8a6, #0ea5a9); opacity: .85; }
.bench-price-fill.third { background: linear-gradient(90deg, #38bdf8, #0ea5e4); }
.bench-price-fill.rest { background: #94a3b8; }
.bench-price-value { font-size: .92rem; font-weight: 800; color: var(--text); text-align: right; }
.bench-highlight { display: flex; flex-direction: column; gap: 6px; }
.bench-highlight .price { font-size: 2.1rem; font-weight: 800; color: var(--accent); line-height: 1; }
.bench-highlight .price-label { color: var(--muted); font-size: .9rem; }
.bench-highlight .price-store { font-size: .95rem; color: var(--text); font-weight: 700; }
.bench-cta { display: inline-flex; align-items: center; justify-content: center; min-height: 44px;
              padding: 10px 22px; border-radius: 999px; background: var(--text); color: var(--surface);
              font-weight: 700; margin-top: 14px; transition: filter .15s ease; }
.bench-cta:hover { text-decoration: none; filter: brightness(1.15); }
.bench-banner { background: linear-gradient(90deg, var(--text), #334155); color: var(--surface); border-radius: var(--radius);
                padding: 14px 18px; text-align: center; font-size: .9rem; margin-top: 28px; }
.bench-section-title { font-size: 1.35rem; margin: 0; letter-spacing: -0.01em; }
.bench-view-header { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: center; margin: 32px 0 16px; }
.bench-view-toggle { display: inline-flex; gap: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 4px; box-shadow: var(--shadow); }
.bench-view-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 999px; font-size: .86rem; font-weight: 600; color: var(--muted); text-decoration: none; transition: background .15s ease, color .15s ease; }
.bench-view-btn:hover { background: var(--code); color: var(--text); }
.bench-view-btn.active { background: var(--accent); color: #fff; }
.bench-view-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.bench-view-panel[hidden] { display: none; }
.bench-items-grid { display: grid; gap: 18px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); margin: 18px 0 28px; }
.bench-sort-icon { font-size: .8rem; color: var(--muted); margin-left: 4px; }
.bench-table th[data-sort] { cursor: pointer; user-select: none; }
.bench-table th[data-sort]:hover { background: var(--code); }
.bench-table th.sort-asc .bench-sort-icon::after { content: " ↑"; }
.bench-table th.sort-desc .bench-sort-icon::after { content: " ↓"; }
.bench-item-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);
                   padding: 18px; display: flex; flex-direction: column; gap: 14px; transition: transform .12s ease, box-shadow .12s ease; }
.bench-item-card:hover { transform: translateY(-3px); box-shadow: 0 10px 28px rgba(0,0,0,.1); }
.bench-item-header { display: flex; gap: 14px; align-items: flex-start; }
.bench-item-meta { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.bench-item-meta .bench-nome { font-size: 1.05rem; font-weight: 700; line-height: 1.35; }
.bench-item-meta .bench-nome a { color: var(--text); }
.bench-item-meta .bench-nome a:hover { color: var(--accent); }
.bench-item-prices { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.bench-price-pill { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
.bench-price-pill .label { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 700; }
.bench-price-pill .value { font-size: 1rem; font-weight: 800; color: var(--text); }
.bench-price-pill.best { border-color: rgba(22,163,74,.35); background: rgba(22,163,74,.08); }
.bench-price-pill.best .value { color: #16a34a; }
.bench-price-pill .value.max { color: #dc2626; }
.bench-card-saving { display: inline-flex; align-items: center; gap: 6px; color: #16a34a; font-weight: 700; font-size: .9rem; }
@media (max-width: 760px) {
  .bench-hero h1 { font-size: 1.5rem; }
  .bench-pesquisa input, .bench-pesquisa select, .bench-pesquisa button { width: 100%; }
  /* Alvos de toque de 44px: no telemóvel os botões pequenos da barra de
     resultados ficavam abaixo disso (35-39px). */
  .bench-pesquisa button, .bench-view-btn { min-height: 44px; }
  .bench-items-grid { grid-template-columns: 1fr; }
  .bench-thumb { width: 46px; height: 46px; flex-basis: 46px; }
  .bench-cards { grid-template-columns: 1fr; }
  .bench-bar-row, .bench-price-row { grid-template-columns: 80px 1fr 46px; }
  .bench-index-axis { padding: 0 70px 0 80px; }
}
"""


def html_publico(
    slug: str,
    *,
    q: str = "",
    loja: str = "",
    ordem: str = "dispersao",
    pagina: int = 0,
    tamanho: int = 50,
    view: str = "card",
) -> Tuple[int, str]:
    """Página pública do benchmark, com pesquisa (sem sessão).

    Devolve `(estado_http, html)`: 404 quando o benchmark não existe ou não está
    publicado — um estudo não publicado não deve aparecer no site.
    """
    benchmark = store.obter(slug)
    if not benchmark or not benchmark.get("public"):
        return 404, _pagina_erro("Este benchmark não está publicado.")

    # Normalizar loja: por vezes chega um dicionário serializado em vez do ID.
    if loja and isinstance(loja, dict):
        loja = str(loja.get("store_id") or "")
    elif loja and isinstance(loja, str) and (loja.startswith("{") or loja.startswith("'{")):
        try:
            import ast
            parsed = ast.literal_eval(loja)
            loja = str(parsed.get("store_id") or "") if isinstance(parsed, dict) else str(parsed)
        except Exception:
            loja = ""
    loja = (loja or "").strip()

    estudo = analise(slug)
    kpis = estudo.get("kpis") or {}
    moeda = benchmark.get("currency") or "EUR"

    def _eur(valor: Any) -> str:
        return f"{float(valor):,.2f} {moeda}".replace(",", " ") if valor is not None else "—"

    comparacao = esc.benchmark_product_comparison(
        slug, q=q or None, store_id=loja or None, order=ordem, size=tamanho, from_=pagina, min_stores=1
    )
    produtos = comparacao.get("items") or []

    def _store_id(loja_dict: Any) -> str:
        if isinstance(loja_dict, dict):
            return str(loja_dict.get("store_id") or "")
        return str(loja_dict or "")

    opcoes_loja = "".join(
        f'<option value="{escape(_store_id(l))}"{" selected" if _store_id(l) == loja else ""}>'
        f'{escape(str(l.get("store_name") or _store_id(l) if isinstance(l, dict) else l))} ({int(l.get("produtos") or 0) if isinstance(l, dict) else 0} produtos)</option>'
        for l in estudo.get("stores") or []
    )
    ordem_opcoes = [
        ("dispersao", "maior dispersão de preço"),
        ("poupanca", "maior poupança"),
        ("lojas", "mais lojas a vender"),
        ("preco", "preço mais baixo"),
        ("nome", "nome"),
    ]
    opcoes_ordem = "".join(
        f'<option value="{valor}"{" selected" if ordem == valor else ""}>{rotulo}</option>'
        for valor, rotulo in ordem_opcoes
    )

    def _render_linha_produto(produto: Dict[str, Any]) -> Dict[str, str]:
        melhor = produto.get("best") or {}
        link = str(melhor.get("url") or "")
        nome = escape(str(produto.get("product_name") or ""))
        nome_html = f'<a href="{escape(link)}" target="_blank" rel="noopener nofollow">{nome}</a>' if link else nome
        marca = escape(str(produto.get("brand") or "sem marca"))
        dispersao = f"{produto['spread_pct']}%" if produto.get("spread_pct") is not None else "—"
        loja_barata = escape(str(melhor.get("store_name") or "—"))
        imagem = str(melhor.get("image") or "").strip()
        miniatura = (
            f'<img class="bench-thumb" src="{escape(imagem, quote=True)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
            if imagem
            else '<span class="bench-thumb vazio"></span>'
        )
        descricao_bruta = str(melhor.get("description") or "").strip()
        descricao = f'<span class="bench-descricao">{escape(descricao_bruta[:240])}</span>' if descricao_bruta else ""
        stores_count = int(produto.get('stores') or 0)
        return {
            "miniatura": miniatura,
            "nome_html": nome_html,
            "marca": marca,
            "descricao": descricao,
            "stores_count": str(stores_count),
            "lojas_label": f"{stores_count} loja{'s' if stores_count != 1 else ''}",
            "price_min": _eur(produto.get("price_min")),
            "price_max": _eur(produto.get("price_max")),
            "price_avg": _eur(produto.get("price_avg")),
            "dispersao": dispersao,
            "loja_barata": loja_barata,
            "economia": f"Poupa até {_eur(produto.get('saving_abs'))}" if produto.get('saving_abs') else "",
        }

    cards_lista = []
    linhas_tabela = []
    for produto in produtos:
        dados = _render_linha_produto(produto)
        stores_badge = f'<span class="bench-stores"><span class="bench-tag">{dados["lojas_label"]}</span></span>'
        cards_lista.append(
            '<article class="bench-item-card">'
            f'<div class="bench-item-header">{dados["miniatura"]}<div class="bench-item-meta">'
            f'<span class="bench-nome">{dados["nome_html"]}</span>'
            f'<span class="bench-tag">{dados["marca"]}</span>'
            f'{dados["descricao"]}</div></div>'
            '<div class="bench-item-prices">'
            '<div class="bench-price-pill best">'
            '<span class="label">Mais barato</span>'
            f'<span class="value">{dados["price_min"]}</span>'
            f'<span class="store">{dados["loja_barata"]}</span></div>'
            f'<div class="bench-price-pill"><span class="label">Máximo</span><span class="value max">{dados["price_max"]}</span></div>'
            f'<div class="bench-price-pill"><span class="label">Média</span><span class="value">{dados["price_avg"]}</span></div>'
            f'<div class="bench-price-pill"><span class="label">Lojas</span><span class="value">{dados["lojas_label"]}</span></div>'
            f'<div class="bench-price-pill"><span class="label">Dispersão</span><span class="value">{dados["dispersao"]}</span></div>'
            '</div>'
            + (f'<span class="bench-card-saving">{dados["economia"]}</span>' if dados["economia"] else "")
            + '</article>'
        )
        linhas_tabela.append(
            "<tr>"
            f'<td data-label="Produto"><div class="bench-produto">{dados["miniatura"]}<div><span class="bench-nome">{dados["nome_html"]}</span>'
            f"{stores_badge}{dados['descricao']}</div></div></td>"
            f'<td data-label="Lojas"><span class="bench-stores">{dados["stores_count"]}</span></td>'
            f'<td data-label="Mínimo" class="bench-min">{dados["price_min"]}</td>'
            f'<td data-label="Máximo" class="bench-max">{dados["price_max"]}</td>'
            f'<td data-label="Média" class="bench-avg">{dados["price_avg"]}</td>'
            f'<td data-label="Dispersão">{dados["dispersao"]}</td>'
            f'<td data-label="Loja mais barata"><span class="bench-store-best">{dados["loja_barata"]}</span></td>'
            "</tr>"
        )
    corpo_cards = "".join(cards_lista) or '<p class="bench-vazio">Sem ofertas para os filtros escolhidos.</p>'
    corpo_tabela = "".join(linhas_tabela) or "<tr><td colspan='7'>Sem ofertas para os filtros escolhidos.</td></tr>"

    recolha_em = ((benchmark.get("last_run") or {}).get("at") or "")[:19].replace("T", " ")
    dispersao_media = f"{kpis['avg_spread_pct']}%" if kpis.get("avg_spread_pct") is not None else "—"
    titulo = str(benchmark.get('name') or 'Benchmark')
    descricao = str(benchmark.get('description') or 'O mesmo produto comparado entre lojas.')
    caminho = f"/site/benchmarks/{benchmark.get('slug')}/pesquisa"
    view = str(view or "card")

    def _view_url(novo_view: str) -> str:
        params: Dict[str, str] = {}
        loja_limpa = ""
        if loja:
            if isinstance(loja, dict):
                loja_limpa = str(loja.get("store_id") or "")
            else:
                loja_limpa = str(loja).strip()
                if loja_limpa.startswith("{"):
                    try:
                        import ast
                        parsed = ast.literal_eval(loja_limpa)
                        loja_limpa = str(parsed.get("store_id") or "") if isinstance(parsed, dict) else ""
                    except Exception:
                        loja_limpa = ""
        if q:
            params["q"] = q
        if loja_limpa:
            params["loja"] = loja_limpa
        if ordem != "dispersao":
            params["ordem"] = ordem
        if novo_view != "card":
            params["view"] = novo_view
        query = "&".join(f"{k}={escape(str(v))}" for k, v in params.items())
        return f"{caminho}?{query}" if query else caminho

    # -----------------------------------------------------------------------
    # Secções visuais: índice de preço, preço por loja e melhor preço destacado
    # -----------------------------------------------------------------------
    lojas_stats = estudo.get("stores") or []
    lojas_ordenadas = sorted(lojas_stats, key=lambda l: float(l.get("indice_preco") or 9999))

    def _bar_width_index(indice: Any) -> float:
        try:
            return max(4.0, min(100.0, float(indice) * 100.0 / 140.0))
        except (TypeError, ValueError):
            return 0.0

    def _bar_width_price(preco: Any, max_preco: float) -> float:
        try:
            return max(4.0, min(100.0, float(preco) * 100.0 / max_preco)) if max_preco else 0.0
        except (TypeError, ValueError):
            return 0.0

    # Índice de preço por loja (100 = média do estudo)
    linhas_indice = []
    marker_pct = 100.0 * 100.0 / 140.0  # posição do marcador "100"
    for idx, loja in enumerate(lojas_ordenadas[:8]):
        nome = escape(str(loja.get("store_name") or loja.get("store_id") or "Loja"))
        indice = loja.get("indice_preco")
        valor = f"{indice:.0f}" if indice is not None else "—"
        pct = _bar_width_index(indice)
        best_class = " best" if idx == 0 else ""
        linhas_indice.append(
            f'<div class="bench-bar-row">'
            f'<div class="label" title="{nome}">{nome}</div>'
            f'<div class="bench-bar-track">'
            f'<div class="bench-bar-fill{best_class}" style="width:{pct:.1f}%"></div>'
            f'<div class="bench-bar-marker" style="left:{marker_pct:.1f}%"></div>'
            f'</div>'
            f'<div class="bench-bar-value">{valor}</div>'
            f'</div>'
        )
    indice_html = "".join(linhas_indice) if linhas_indice else '<p class="muted">Sem dados por loja.</p>'

    # Preço por loja
    precos_validos = [float(l.get("preco_medio") or 0) for l in lojas_stats if l.get("preco_medio")]
    max_preco = max(precos_validos) if precos_validos else 0
    lojas_preco = sorted(lojas_stats, key=lambda l: float(l.get("preco_medio") or 0))
    linhas_preco = []
    for idx, loja in enumerate(lojas_preco[:8]):
        nome = escape(str(loja.get("store_name") or loja.get("store_id") or "Loja"))
        preco = loja.get("preco_medio")
        pct = _bar_width_price(preco, max_preco)
        classe = "best" if idx == 0 else ("second" if idx == 1 else ("third" if idx == 2 else "rest"))
        ofertas = int(loja.get("ofertas") or 0)
        linhas_preco.append(
            f'<div class="bench-price-row">'
            f'<div class="label" title="{nome}">{nome}</div>'
            f'<div class="bench-bar-track"><div class="bench-price-fill {classe}" style="width:{pct:.1f}%"></div></div>'
            f'<div class="bench-price-value">{_eur(preco)}</div>'
            f'</div>'
            f'<div class="muted" style="margin-top:-8px;margin-bottom:10px;padding-left:100px;">{ofertas} ofertas</div>'
        )
    preco_html = "".join(linhas_preco) if linhas_preco else '<p class="muted">Sem preços por loja.</p>'

    # Melhor preço / ficha comparada
    oportunidades = estudo.get("opportunities") or []
    melhor_geral = min(oportunidades, key=lambda p: p.get("price_min") or float("inf")) if oportunidades else None
    melhor_oferta = melhor_geral.get("best") or {} if melhor_geral else {}
    ficha_html = (
        '<div class="bench-highlight">'
        f'<span class="price-label">Melhor preço</span>'
        f'<span class="price">{_eur(melhor_oferta.get("price"))}</span>'
        f'<span class="price-store">{escape(str(melhor_oferta.get("store_name") or "—"))}</span>'
        f'<span class="muted">{escape(str(melhor_geral.get("product_name") or "")[:60])}</span>'
        f'<a class="bench-cta" href="#lista-completa">Ver a lista completa</a>'
        '</div>'
    ) if melhor_geral else '<p class="muted">Sem comparações disponíveis.</p>'

    cards_html = f"""
<div class="bench-cards">
  <div class="bench-card">
    <h2>Índice de preço · 100 = média do estudo</h2>
    {indice_html}
    <div class="bench-index-axis"><span>80</span><span>média</span><span>120</span></div>
  </div>
  <div class="bench-card">
    <h2>Preço por loja</h2>
    {preco_html}
    <p class="muted">Comparação automática entre lojas</p>
  </div>
  <div class="bench-card">
    <h2>Ficha comparada</h2>
    {ficha_html}
  </div>
</div>
""" if lojas_stats else ""

    corpo = f"""<div class="bench-hero"><div class="bench-wrap">
  <h1>{escape(titulo)}</h1>
  <p class="lead">{escape(descricao)}</p>
</div></div>
<div class="bench-wrap">
  <div class="bench-grid">
    <div class="bench-kpi"><b>{kpis.get('offers', 0)}</b><span>ofertas recolhidas</span></div>
    <div class="bench-kpi"><b>{kpis.get('products', 0)}</b><span>produtos</span></div>
    <div class="bench-kpi"><b>{kpis.get('stores', 0)}</b><span>lojas</span></div>
    <div class="bench-kpi"><b>{kpis.get('comparable_products', 0)}</b><span>produtos em 2+ lojas</span></div>
    <div class="bench-kpi"><b>{dispersao_media}</b><span>dispersão média</span></div>
    <div class="bench-kpi"><b>{_eur(kpis.get('potential_saving_eur'))}</b><span>poupança se escolher sempre o mínimo</span></div>
  </div>

  {cards_html}

  <h2>Pesquisar</h2>
  <form class="bench-pesquisa" method="get" action="{escape(caminho)}">
    <label>Produto ou marca
      <input type="search" name="q" value="{escape(q)}" placeholder="ex.: portátil 16GB">
    </label>
    <label>Loja
      <select name="loja"><option value="">todas</option>{opcoes_loja}</select>
    </label>
    <label>Ordenar por
      <select name="ordem">{opcoes_ordem}</select>
    </label>
    <button type="submit">Procurar</button>
  </form>

  <div class="bench-view-header">
    <h2 id="lista-completa" class="bench-section-title">Onde está mais barato ({int(comparacao.get('total') or 0)} produtos)</h2>
    <div class="bench-view-actions">
      <button type="button" class="bench-view-btn" data-bench-sort-dir title="Inverter ordem dos resultados">
        <span data-sort-label>Ordem: crescente</span>
      </button>
      <div class="bench-view-toggle" role="group" aria-label="Tipo de visualização" data-bench-toggle>
        <a class="bench-view-btn{' active' if view == 'card' else ''}" href="{escape(_view_url('card'))}" data-view="card" title="Cards">Cards</a>
        <a class="bench-view-btn{' active' if view == 'table' else ''}" href="{escape(_view_url('table'))}" data-view="table" title="Tabela">Tabela</a>
      </div>
    </div>
  </div>
  <div class="bench-view-panel" data-view="card"{' hidden' if view != 'card' else ''}>
    <div class="bench-items-grid" data-bench-items="card">{corpo_cards}</div>
  </div>
  <div class="bench-view-panel" data-view="table"{' hidden' if view != 'table' else ''}>
    <div class="bench-table-wrap">
      <table class="bench-table" data-bench-table>
        <thead><tr>
          <th data-sort="text">Produto <span class="bench-sort-icon">↕</span></th>
          <th data-sort="number">Lojas <span class="bench-sort-icon">↕</span></th>
          <th data-sort="price">Mínimo <span class="bench-sort-icon">↕</span></th>
          <th data-sort="price">Máximo <span class="bench-sort-icon">↕</span></th>
          <th data-sort="price">Média <span class="bench-sort-icon">↕</span></th>
          <th data-sort="percent">Dispersão <span class="bench-sort-icon">↕</span></th>
          <th data-sort="text">Loja mais barata <span class="bench-sort-icon">↕</span></th>
        </tr></thead>
        <tbody>{corpo_tabela}</tbody>
      </table>
    </div>
  </div>
  <script>
    (function(){{
      const toggle = document.querySelector('[data-bench-toggle]');
      if (toggle) {{
        const buttons = toggle.querySelectorAll('[data-view]');
        const panels = document.querySelectorAll('.bench-view-panel');
        buttons.forEach(function(btn){{
          btn.addEventListener('click', function(e){{
            e.preventDefault();
            const view = btn.getAttribute('data-view');
            buttons.forEach(function(b){{ b.classList.toggle('active', b.getAttribute('data-view') === view); }});
            panels.forEach(function(p){{ p.hidden = p.getAttribute('data-view') !== view; }});
            const url = new URL(btn.getAttribute('href'), window.location.href);
            history.replaceState(null, '', url.toString());
          }});
        }});
      }}

      // Inverter ordem dos cards (global, mantém o primeiro/último)
      const sortDirBtn = document.querySelector('[data-bench-sort-dir]');
      if (sortDirBtn) {{
        let ascending = true;
        sortDirBtn.addEventListener('click', function(){{
          ascending = !ascending;
          sortDirBtn.querySelector('[data-sort-label]').textContent = ascending ? 'Ordem: crescente' : 'Ordem: decrescente';
          const grid = document.querySelector('[data-bench-items="card"]');
          if (grid) {{
            const items = Array.from(grid.children);
            grid.innerHTML = '';
            items.reverse().forEach(function(item){{ grid.appendChild(item); }});
          }}
          const tbody = document.querySelector('[data-bench-table] tbody');
          if (tbody) {{
            const rows = Array.from(tbody.querySelectorAll('tr'));
            tbody.innerHTML = '';
            rows.reverse().forEach(function(row){{ tbody.appendChild(row); }});
          }}
        }});
      }}

      // Ordenação por coluna na tabela
      const table = document.querySelector('[data-bench-table]');
      if (table) {{
        const tbody = table.querySelector('tbody');
        const headers = table.querySelectorAll('thead th[data-sort]');
        headers.forEach(function(header){{
          header.style.cursor = 'pointer';
          header.addEventListener('click', function(){{
            const col = Array.from(header.parentNode.children).indexOf(header);
            const type = header.getAttribute('data-sort');
            const currentDir = header.getAttribute('data-dir') || 'asc';
            const dir = currentDir === 'asc' ? 'desc' : 'asc';
            headers.forEach(function(h){{ h.removeAttribute('data-dir'); h.classList.remove('sort-asc','sort-desc'); }});
            header.setAttribute('data-dir', dir);
            header.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');

            const rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function(a, b){{
              let av = a.children[col].textContent.trim();
              let bv = b.children[col].textContent.trim();
              if (type === 'text' && a.children[col].querySelector('.bench-nome')) {{
                av = a.children[col].querySelector('.bench-nome').textContent.trim();
                bv = b.children[col].querySelector('.bench-nome').textContent.trim();
              }}
              if (type === 'number') {{
                av = parseFloat(av) || 0;
                bv = parseFloat(bv) || 0;
              }} else if (type === 'price') {{
                av = parseFloat(av.replace(/[^0-9,]/g, '').replace(',', '.')) || 0;
                bv = parseFloat(bv.replace(/[^0-9,]/g, '').replace(',', '.')) || 0;
              }} else if (type === 'percent') {{
                av = parseFloat(av.replace('%','')) || 0;
                bv = parseFloat(bv.replace('%','')) || 0;
              }}
              if (typeof av === 'string') {{ av = av.toLocaleLowerCase('pt'); bv = bv.toLocaleLowerCase('pt'); }}
              if (av < bv) return dir === 'asc' ? -1 : 1;
              if (av > bv) return dir === 'asc' ? 1 : -1;
              return 0;
            }});
            tbody.innerHTML = '';
            rows.forEach(function(row){{ tbody.appendChild(row); }});
          }});
        }});
      }}
    }})();
  </script>
  <p class="bench-rodape" style="color:#64748b;font-size:12px;margin-top:24px;">
    Dados recolhidos automaticamente dos sites das lojas. Última recolha: {escape(recolha_em or 'sem registo')}.
    Os preços podem estar desactualizados — confirme sempre na loja. Este estudo não é uma recomendação de compra.
  </p>
  <div class="bench-banner">
    Melhor preço assinalado · data de recolha à vista · preço publicado não é preço final
  </div>
</div>"""

    html = render._layout(
        title=titulo,
        description=descricao,
        body=corpo,
        current_path=caminho,
        settings=cms.get_settings(),
        canonical=caminho,
        extra_css=_ESTILO,
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Benchmarks", "href": "/site/benchmarks"},
            {"label": titulo},
        ],
    )
    return 200, html


def _pagina_erro(mensagem: str) -> str:
    return f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><title>Não disponível</title><style>{_ESTILO}</style></head>
<body><div class="bench-wrap"><h1>Não disponível</h1><p class="bench-vazio">{escape(mensagem)}</p>
<p><a href="/site">Voltar ao site</a></p></div></body></html>"""
