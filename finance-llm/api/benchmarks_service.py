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
import unicodedata
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

from api import benchmarks_store as store
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
    texto = str(valor).strip()
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
    explicito = mapa.get(chave)
    if explicito and campos.get(explicito) not in (None, ""):
        return campos[explicito]
    normalizados = {_chave(k): v for k, v in campos.items()}
    for alias in aliases:
        valor = normalizados.get(_chave(alias))
        if valor not in (None, ""):
            return valor
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
    limite_por_loja: int = 500,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Corre a recolha das lojas do benchmark e indexa as ofertas no índice dele."""
    benchmark = store.obter(slug)
    if not benchmark:
        return {"error": "Benchmark não encontrado"}
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
    fetcher: str = "http",
    hint: str = "",
    use_ai: bool = True,
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
    """
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
        "currency": "EUR",
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
_ESTILO = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0f1115; color: #e5e7eb;
       font: 15px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif; }
a { color: #5eead4; text-decoration: none; }
a:hover { text-decoration: underline; }
header { padding: 28px 22px 18px; border-bottom: 1px solid #1f2937;
         background: linear-gradient(180deg, #0b1220, #0f1115); }
h1 { margin: 0 0 6px; font-size: 26px; }
h2 { margin: 30px 0 10px; font-size: 18px; }
.lead { color: #94a3b8; margin: 0; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 22px 60px; }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); margin: 22px 0; }
.kpi { background: #161c28; border: 1px solid #24303f; border-radius: 12px; padding: 14px 16px; }
.kpi b { display: block; font-size: 22px; color: #5eead4; }
.kpi span { color: #94a3b8; font-size: 12px; }
form.pesquisa { display: flex; flex-wrap: wrap; gap: 10px; align-items: end;
                background: #161c28; border: 1px solid #24303f; border-radius: 12px; padding: 14px; }
form.pesquisa label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #94a3b8; }
input, select, button { font: inherit; color: #e5e7eb; background: #0f1115;
                        border: 1px solid #2b3648; border-radius: 8px; padding: 8px 10px; }
button { background: #0d9488; border-color: #0d9488; color: #04211d; font-weight: 600; cursor: pointer; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13.5px; }
th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid #1f2937; vertical-align: top; }
th { color: #94a3b8; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
tr:hover td { background: #141a25; }
.min { color: #34d399; font-weight: 600; }
.max { color: #f87171; }
.tag { display: inline-block; padding: 1px 7px; border-radius: 999px; background: #1f2937; color: #cbd5e1; font-size: 11px; }
footer { color: #64748b; font-size: 12px; padding: 24px 22px 40px; border-top: 1px solid #1f2937; }
.vazio { background: #161c28; border: 1px dashed #334155; border-radius: 12px; padding: 18px; color: #94a3b8; }
"""


def html_publico(
    slug: str,
    *,
    q: str = "",
    loja: str = "",
    ordem: str = "dispersao",
    pagina: int = 0,
    tamanho: int = 50,
) -> Tuple[int, str]:
    """Página pública do benchmark, com pesquisa (sem sessão).

    Devolve `(estado_http, html)`: 404 quando o benchmark não existe ou não está
    publicado — um estudo não publicado não deve aparecer no site.
    """
    benchmark = store.obter(slug)
    if not benchmark or not benchmark.get("public"):
        return 404, _pagina_erro("Este benchmark não está publicado.")

    estudo = analise(slug)
    kpis = estudo.get("kpis") or {}
    moeda = benchmark.get("currency") or "EUR"

    def _eur(valor: Any) -> str:
        return f"{float(valor):,.2f} {moeda}".replace(",", " ") if valor is not None else "—"

    comparacao = esc.benchmark_product_comparison(
        slug, q=q or None, store_id=loja or None, order=ordem, size=tamanho, from_=pagina, min_stores=1
    )
    produtos = comparacao.get("items") or []

    opcoes_loja = "".join(
        f'<option value="{escape(str(l.get("store_id")))}"{" selected" if str(l.get("store_id")) == loja else ""}>'
        f'{escape(str(l.get("store_name") or l.get("store_id")))} ({int(l.get("produtos") or 0)} produtos)</option>'
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

    linhas = []
    for produto in produtos:
        melhor = produto.get("best") or {}
        link = str(melhor.get("url") or "")
        nome = escape(str(produto.get("product_name") or ""))
        nome_html = f'<a href="{escape(link)}" target="_blank" rel="noopener nofollow">{nome}</a>' if link else nome
        marca = escape(str(produto.get("brand") or "sem marca"))
        dispersao = f"{produto['spread_pct']}%" if produto.get("spread_pct") is not None else "—"
        loja_barata = escape(str(melhor.get("store_name") or "—"))
        linhas.append(
            "<tr>"
            f"<td>{nome_html}<br><span class='tag'>{marca}</span></td>"
            f"<td>{int(produto.get('stores') or 0)}</td>"
            f"<td class='min'>{_eur(produto.get('price_min'))}</td>"
            f"<td class='max'>{_eur(produto.get('price_max'))}</td>"
            f"<td>{_eur(produto.get('price_avg'))}</td>"
            f"<td>{dispersao}</td>"
            f"<td>{loja_barata}</td>"
            "</tr>"
        )
    corpo_tabela = "".join(linhas) or (
        "<tr><td colspan='7'>Sem ofertas para os filtros escolhidos.</td></tr>"
    )

    recolha_em = ((benchmark.get("last_run") or {}).get("at") or "")[:19].replace("T", " ")
    dispersao_media = f"{kpis['avg_spread_pct']}%" if kpis.get("avg_spread_pct") is not None else "—"
    return 200, f"""<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(str(benchmark.get('name') or 'Benchmark'))} — comparação de preços</title>
<meta name="description" content="{escape(str(benchmark.get('description') or 'Comparação de preços entre lojas.'))}">
<style>{_ESTILO}</style>
</head>
<body>
<header><div class="wrap">
  <h1>{escape(str(benchmark.get('name') or 'Benchmark'))}</h1>
  <p class="lead">{escape(str(benchmark.get('description') or 'O mesmo produto comparado entre lojas.'))}</p>
</div></header>
<div class="wrap">
  <div class="grid">
    <div class="kpi"><b>{kpis.get('offers', 0)}</b><span>ofertas recolhidas</span></div>
    <div class="kpi"><b>{kpis.get('products', 0)}</b><span>produtos</span></div>
    <div class="kpi"><b>{kpis.get('stores', 0)}</b><span>lojas</span></div>
    <div class="kpi"><b>{kpis.get('comparable_products', 0)}</b><span>produtos em 2+ lojas</span></div>
    <div class="kpi"><b>{dispersao_media}</b><span>dispersão média</span></div>
    <div class="kpi"><b>{_eur(kpis.get('potential_saving_eur'))}</b><span>poupança se escolher sempre o mínimo</span></div>
  </div>

  <h2>Pesquisar</h2>
  <form class="pesquisa" method="get" action="/site/benchmarks/{escape(str(benchmark.get('slug')))}/pesquisa">
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

  <h2>Onde está mais barato ({int(comparacao.get('total') or 0)} produtos)</h2>
  <table>
    <thead><tr>
      <th>Produto</th><th>Lojas</th><th>Mínimo</th><th>Máximo</th><th>Média</th><th>Dispersão</th><th>Loja mais barata</th>
    </tr></thead>
    <tbody>{corpo_tabela}</tbody>
  </table>
</div>
<footer>
  <div class="wrap">
    Dados recolhidos automaticamente dos sites das lojas. Última recolha: {escape(recolha_em or 'sem registo')}.
    Os preços podem estar desactualizados — confirme sempre na loja. Este estudo não é uma recomendação de compra.
  </div>
</footer>
</body>
</html>"""


def _pagina_erro(mensagem: str) -> str:
    return f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><title>Não disponível</title><style>{_ESTILO}</style></head>
<body><div class="wrap"><h1>Não disponível</h1><p class="vazio">{escape(mensagem)}</p>
<p><a href="/site">Voltar ao site</a></p></div></body></html>"""
