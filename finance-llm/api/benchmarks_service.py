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

import hashlib
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
from api import site_acoes

logger = logging.getLogger(__name__)

_SIMBOLOS_MOEDA = {"EUR": "€", "USD": "$", "GBP": "£"}


def _formatar_moeda(valor: Any, moeda: str = "EUR") -> str:
    """Preço à portuguesa: «1 174,99 €» (espaço firme nos milhares)."""
    if valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    texto = f"{numero:,.2f}".replace(",", "\u00a0").replace(".", ",")
    simbolo = _SIMBOLOS_MOEDA.get(str(moeda or "EUR").upper())
    return f"{texto} {simbolo}" if simbolo else f"{texto} {moeda}"


def _data_recolha(valor: Any) -> str:
    """«2026-10-15 17:00:45» → «15/10/2026 às 17:00»."""
    texto = str(valor or "").strip()
    if not texto:
        return "sem registo"
    try:
        momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return texto
    return momento.strftime("%d/%m/%Y às %H:%M")


def _ancora_produto(produto: Dict[str, Any], posicao: int) -> str:
    """Identificador curto e estável de um produto (âncora e favorito)."""
    base = str(produto.get("product_key") or produto.get("product_name") or posicao)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]


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

#: Tipo que fica quando o nome e a categoria não dizem que peça é.
TIPO_PECA_PADRAO = "Outros"

#: Padrões (texto já sem acentos) que identificam cada tipo de peça. A **ordem
#: manda**: o primeiro que casa vence, por isso o específico (`sapatilhas`,
#: `jeans`) vem antes do genérico (`sapatos`, `calças`) e `vestido` antes de
#: `vest` (colete), que é o mesmo radical.
_TIPOS_PECA_PADROES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Sapatilhas", ("sapatilha", "sapatilhas", "sneaker", "sneakers", "tenis", "trainer", "trainers")),
    ("Botas", ("bota", "botas", "botim", "botins", "boot", "boots")),
    ("Sandálias", ("sandalia", "sandalias", "chinelo", "chinelos", "sandal", "sandals", "slides", "flip flop")),
    (
        "Sapatos",
        (
            "sapato", "sapatos", "mocassim", "mocassins", "bailarina", "bailarinas", "sabrina", "sabrinas",
            "loafer", "loafers", "shoe", "shoes",
        ),
    ),
    ("Calções", ("calcao", "calcoes", "short", "shorts", "bermuda", "bermudas")),
    (
        "Calças",
        ("calca", "calcas", "pantalon", "pantalons", "trouser", "trousers", "pants", "jogger", "joggers", "legging", "leggings"),
    ),
    # `ganga`/`jeans` só depois das calças e dos calções: «calças de ganga» é uma
    # calça (o tecido não muda a peça) e «calções de ganga» é um calção.
    ("Jeans", ("jeans", "ganga")),
    ("Saias", ("saia", "saias", "skirt", "skirts")),
    ("Vestidos", ("vestido", "vestidos", "dress", "dresses")),
    ("Macacões", ("macacao", "macacoes", "jumpsuit", "jumpsuits")),
    ("Conjuntos", ("conjunto", "conjuntos", "jogging set", "tracksuit", "fato de treino")),
    ("T-shirts", ("t shirt", "tshirt", "tshirts", "tee", "tees", "camiseta", "camisetas", "top", "tops", "polo", "polos")),
    (
        "Camisolas",
        ("camisola", "camisolas", "sweater", "sweaters", "pullover", "pull", "malha", "cardigan", "cardigans", "tricot", "knit", "sweatshirt"),
    ),
    ("Camisas", ("camisa", "camisas", "blusa", "blusas", "shirt", "shirts", "blouse", "blouses")),
    (
        "Casacos",
        (
            "casaco", "casacos", "blusao", "blusoes", "blazao", "blazoes", "blazer", "blazers", "jacket", "jackets",
            "parka", "parkas", "trench", "gabardina", "gabardinas", "capa", "cape", "sobretudo", "sobretudos", "coat",
            "coats", "anorak", "colete", "coletes", "gilet", "vest",
        ),
    ),
    ("Fatos de banho", ("fato de banho", "biquini", "biquinis", "swimsuit", "swimwear", "bikini")),
    (
        "Roupa interior",
        ("cueca", "cuecas", "boxer", "boxers", "soutien", "soutiens", "lingerie", "meia", "meias", "socks", "collants"),
    ),
    ("Pijamas", ("pijama", "pijamas", "pajama", "pajamas", "pyjama", "pyjamas")),
    (
        "Acessórios",
        (
            "cinto", "cintos", "belt", "lenco", "lencos", "cachecol", "cachecois", "gorro", "gorros", "chapeu", "luva",
            "luvas", "diadema", "alice band", "wand", "mala", "malas", "bag", "bags", "carteira", "carteiras", "wallet",
            "oculos", "sunglasses", "relogio", "relogios", "watch", "brinco", "brincos", "colar", "colares", "pulseira",
            "pulseiras", "anel", "aneis",
        ),
    ),
)

#: Os padrões já compilados, com fronteira de palavra (o texto é normalizado:
#: só `[a-z0-9 ]`, por isso `\b` separa as palavras como se espera).
_TIPOS_PECA: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    (tipo, re.compile(r"\b(?:" + "|".join(padroes) + r")\b")) for tipo, padroes in _TIPOS_PECA_PADROES
)


def tipo_de_peca(nome: str = "", categoria: str = "") -> str:
    """Tipo de peça de um produto (`Camisolas`, `Calças`, `Vestidos`…).

    Lê primeiro o **nome** (é o que vem sempre preenchido) e só depois a
    categoria. Serve para o resumo «preço por tipo de peça» do estudo, onde se
    comparam médias de peças de marcas diferentes — o produto a produto só é
    possível quando as lojas vendem o mesmo artigo.
    """
    for texto in (nome, categoria):
        chave = _chave(texto)
        if not chave:
            continue
        for tipo, padrao in _TIPOS_PECA:
            if padrao.search(chave):
                return tipo
    return TIPO_PECA_PADRAO


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
        "garment_type": tipo_de_peca(nome, str(categoria or "")),
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
                str(corrida.get("run_id") or ""), source_id, limit=max(1, limite)
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
    tipos_peca = esc.benchmark_garment_stats(slug)
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
            # Tipos de peça com ofertas (o «Outros» fica de fora: não é um tipo).
            "garment_types": len([t for t in tipos_peca if t.get("garment_type") not in (None, "", TIPO_PECA_PADRAO)]),
        },
        "stores": lojas,
        "garment_types": tipos_peca,
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
        return _formatar_moeda(valor, moeda)

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
                    {"title": f"{kpis.get('garment_types', 0)}", "text": "tipos de peça"},
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
    tipos_peca = [t for t in (estudo.get("garment_types") or []) if t.get("garment_type")]
    if tipos_peca:
        # Quando as lojas são marcas diferentes não há o mesmo produto dos dois
        # lados; o tipo de peça é o nível em que a comparação ainda é honesta.
        blocos.append(
            {
                "type": "tabela",
                "data": {
                    "title": "Preço por tipo de peça",
                    "head": ["Tipo de peça", "Ofertas", "Lojas", "Média", "Mínimo", "Máximo", "Loja mais barata"],
                    "rows": [
                        [
                            str(t.get("garment_type")),
                            str(int(t.get("offers") or 0)),
                            str(int(t.get("stores") or 0)),
                            _eur(t.get("price_avg")),
                            _eur(t.get("price_min")),
                            _eur(t.get("price_max")),
                            str(t.get("cheapest_store") or "—"),
                        ]
                        for t in tipos_peca
                    ],
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
/* ==========================================================================
   Estudo de preços (`/site/benchmarks/<slug>/pesquisa`)
   Desenho de montra: abertura com as ações, números do estudo, melhor preço
   em destaque, filtros à esquerda e produtos em cartões (imagem, «desde»,
   nº de lojas), como numa loja de comparação de preços.
   ========================================================================== */
.bench-wrap { max-width: 1120px; margin: 0 auto; }
.bench-wrap > * + * { margin-top: 28px; }

/* ---------- Abertura ---------- */
.bench-hero {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 20px 28px; align-items: start;
  padding: 26px 28px; border: 1px solid var(--border); border-radius: calc(var(--radius) + 6px);
  background: linear-gradient(135deg, rgba(14,165,164,.10), rgba(14,165,164,0) 58%), var(--surface);
  box-shadow: var(--shadow);
}
.bench-kicker {
  display: inline-flex; align-items: center; gap: 8px; margin: 0 0 10px;
  color: var(--accent); font-size: .72rem; font-weight: 800; letter-spacing: .14em;
  text-transform: uppercase;
}
.bench-kicker::before { content: ""; width: 26px; height: 3px; border-radius: 999px; background: var(--accent); }
.bench-hero h1 { margin: 0 0 10px; font-size: clamp(1.65rem, 3.4vw, 2.25rem); line-height: 1.12; letter-spacing: -.02em; }
.bench-lead { margin: 0 0 16px; max-width: 68ch; color: var(--muted); font-size: 1rem; }
.bench-hero-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; margin: 0; color: var(--muted); font-size: .84rem; }
.bench-hero-meta b { color: var(--text); font-size: .95rem; }
.bench-hero-acoes { display: flex; justify-content: flex-end; align-items: flex-start; }

/* ---------- Números ---------- */
.bench-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.bench-kpi {
  display: flex; flex-direction: column; gap: 3px; padding: 15px 17px;
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow);
}
.bench-kpi b { font-size: 1.5rem; line-height: 1.1; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.bench-kpi span { color: var(--muted); font-size: .78rem; line-height: 1.3; }
.bench-kpi--destaque {
  grid-column: span 2;
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, var(--surface)), var(--surface));
}
.bench-kpi--destaque b { color: var(--accent); }

/* ---------- Melhor preço ---------- */
.bench-destaque {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 16px 26px;
  padding: 20px 24px; border-radius: calc(var(--radius) + 4px);
  border: 1px solid color-mix(in srgb, var(--accent) 32%, var(--border));
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 12%, var(--surface)), var(--surface) 70%);
  box-shadow: var(--shadow);
}
.bench-destaque-preco {
  display: flex; flex-direction: column; gap: 2px; padding-right: 24px;
  border-right: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border));
}
.bench-destaque-preco span.bench-rotulo {
  color: var(--muted); font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;
}
.bench-destaque-valor {
  color: var(--accent); font-size: clamp(1.7rem, 3.6vw, 2.35rem); font-weight: 800;
  line-height: 1; letter-spacing: -.02em; font-variant-numeric: tabular-nums;
}
.bench-destaque-loja { color: var(--text); font-weight: 700; font-size: .9rem; }
.bench-destaque-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.bench-destaque-nome { margin: 0; font-weight: 700; font-size: 1rem; line-height: 1.35; }
.bench-destaque-nota { margin: 0; color: var(--muted); font-size: .85rem; }
.bench-cta {
  display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 10px 22px;
  border-radius: 999px; background: var(--accent); color: #fff; font-weight: 700; font-size: .9rem;
  white-space: nowrap;
}
.bench-cta:hover { filter: brightness(1.08); text-decoration: none; }

/* ---------- Secções e gráficos ---------- */
.bench-seccao-topo {
  display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
  gap: 10px 20px; margin-bottom: 14px;
}
.bench-seccao-topo h2 { margin: 0; font-size: 1.25rem; letter-spacing: -.01em; }
.bench-seccao-topo p { margin: 4px 0 0; max-width: 70ch; color: var(--muted); font-size: .88rem; }
.bench-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.bench-card {
  padding: 18px 20px; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow);
}
.bench-card-topo {
  display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between;
  gap: 4px 12px; margin-bottom: 14px;
}
.bench-card h2 { margin: 0; font-size: 1rem; }
.bench-card-nota { color: var(--muted); font-size: .76rem; }
.bench-barras { display: flex; flex-direction: column; gap: 9px; }
.bench-barra {
  display: grid; grid-template-columns: 106px minmax(0, 1fr) 78px;
  column-gap: 10px; row-gap: 2px; align-items: center;
}
.bench-barra-rotulo { font-size: .85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bench-barra-trilho { position: relative; height: 12px; border-radius: 999px; background: var(--code); }
.bench-barra-fill { display: block; height: 100%; border-radius: 999px; background: #94a3b8; min-width: 4px; }
.bench-barra-fill.best { background: var(--accent); }
.bench-barra-marca {
  position: absolute; top: -4px; bottom: -4px; width: 2px; border-radius: 2px;
  background: color-mix(in srgb, var(--text) 45%, transparent);
}
.bench-barra-valor {
  text-align: right; font-size: .86rem; font-weight: 800; font-variant-numeric: tabular-nums;
}
.bench-barra-nota { grid-column: 2; color: var(--muted); font-size: .72rem; }
.bench-eixo {
  display: grid; grid-template-columns: 106px minmax(0, 1fr) 78px; column-gap: 10px;
  margin-top: 8px; color: var(--muted); font-size: .68rem;
}
.bench-eixo-trilho { position: relative; height: 14px; }
.bench-eixo-trilho i { position: absolute; transform: translateX(-50%); font-style: normal; white-space: nowrap; }
.bench-eixo-trilho i:first-child { transform: none; }
.bench-eixo-trilho i:last-child { transform: translateX(-100%); }
.bench-tabela-scroll { overflow-x: auto; }

/* ---------- Filtros + resultados ---------- */
.bench-lista { display: grid; grid-template-columns: 264px minmax(0, 1fr); gap: 26px; align-items: start; }
.bench-filtros {
  position: sticky; top: 16px; display: flex; flex-direction: column; gap: 14px; padding: 18px;
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow);
}
.bench-filtros h2 { margin: 0; font-size: 1rem; }
.bench-filtros form { display: flex; flex-direction: column; gap: 12px; }
.bench-campo { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.bench-campo > span {
  color: var(--muted); font-size: .72rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
}
.bench-campo input, .bench-campo select {
  width: 100%; min-width: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg); color: var(--text); font: inherit; font-size: .9rem;
}
.bench-campo input:focus, .bench-campo select:focus {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset: 1px; border-color: var(--accent);
}
.bench-botao {
  min-height: 44px; padding: 10px 18px; border: 1px solid var(--accent); border-radius: 999px;
  background: var(--accent); color: #fff; font: inherit; font-weight: 700; font-size: .9rem; cursor: pointer;
}
.bench-botao:hover { filter: brightness(1.07); }
.bench-limpar { color: var(--muted); font-size: .82rem; text-align: center; }
.bench-limpar:hover { color: var(--accent); }
.bench-lojas { display: flex; flex-direction: column; gap: 2px; padding-top: 14px; border-top: 1px solid var(--border); }
.bench-lojas h3 {
  margin: 0 0 6px; color: var(--muted); font-size: .72rem; letter-spacing: .05em; text-transform: uppercase;
}
.bench-lojas a {
  display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 36px;
  padding: 6px 9px; border-radius: 8px; color: var(--text); font-size: .87rem;
}
.bench-lojas a:hover, .bench-lojas a[aria-current="true"] { background: var(--code); color: var(--accent); text-decoration: none; }
.bench-lojas a[aria-current="true"] { font-weight: 700; }
.bench-lojas a em { font-style: normal; color: var(--muted); font-size: .77rem; }
.bench-resultados { min-width: 0; }
.bench-view-header {
  display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
  gap: 12px 20px; margin-bottom: 16px;
}
.bench-section-title { margin: 0; font-size: 1.25rem; letter-spacing: -.01em; }
.bench-resultados-nota { margin: 4px 0 0; color: var(--muted); font-size: .85rem; }
.bench-view-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.bench-view-actions > .bench-view-btn { border: 1px solid var(--border); background: var(--surface); }
.bench-view-toggle {
  display: inline-flex; gap: 4px; padding: 4px;
  border: 1px solid var(--border); border-radius: 999px; background: var(--surface);
}
.bench-view-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 36px;
  padding: 7px 14px; border: 0; border-radius: 999px; background: none; color: var(--muted);
  font: inherit; font-size: .84rem; font-weight: 600; cursor: pointer;
}
.bench-view-btn:hover { background: var(--code); color: var(--text); text-decoration: none; }
.bench-view-btn.active { background: var(--accent); color: #fff; }
.bench-view-panel[hidden] { display: none; }

/* ---------- Cartões de produto ---------- */
.bench-items-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(224px, 1fr)); gap: 14px; }
.bench-item {
  display: flex; flex-direction: column; overflow: hidden;
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow);
  transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease;
}
.bench-item:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  box-shadow: 0 2px 4px rgba(16,24,40,.06), 0 12px 28px rgba(16,24,40,.09);
}
.bench-item-figura {
  position: relative; display: flex; align-items: center; justify-content: center;
  aspect-ratio: 4 / 3; padding: 14px; background: var(--bg); border-bottom: 1px solid var(--border);
}
.bench-item-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.bench-item-semimagem { width: 100%; height: 100%; border-radius: 10px; border: 1px dashed var(--border); }
.bench-item-fav { position: absolute; top: 8px; right: 8px; box-shadow: 0 1px 4px rgba(16,24,40,.14); }
.bench-item-poupanca {
  position: absolute; top: 8px; left: 8px; padding: 3px 8px; border-radius: 999px;
  background: #16a34a; color: #fff; font-size: .71rem; font-weight: 800;
}
.bench-item-corpo { display: flex; flex-direction: column; gap: 5px; flex: 1; padding: 12px 14px 14px; }
.bench-item-marca {
  color: var(--muted); font-size: .71rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
}
.bench-item-nome {
  margin: 0; font-size: .92rem; font-weight: 600; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.bench-item-nome a { color: var(--text); }
.bench-item-nome a:hover { color: var(--accent); }
.bench-item-preco { display: flex; align-items: baseline; gap: 5px; margin: 4px 0 0; }
.bench-item-preco span { color: var(--muted); font-size: .72rem; }
.bench-item-preco strong { font-size: 1.22rem; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.bench-item-lojas { margin: 0; color: var(--muted); font-size: .78rem; }
.bench-item-cta {
  display: inline-flex; align-items: center; justify-content: center; min-height: 40px;
  margin-top: auto; padding: 8px 14px; border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border));
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
  color: color-mix(in srgb, var(--accent) 72%, #0b1220); font-size: .85rem; font-weight: 700;
}
.bench-item-corpo .bench-item-cta { margin-top: 10px; }
.bench-item-cta:hover { background: var(--accent); color: #fff; text-decoration: none; }
.bench-item-cta--off { border-style: dashed; color: var(--muted); background: none; }

/* ---------- Tabela ---------- */
.bench-table-wrap {
  overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow);
}
.bench-table { width: 100%; min-width: 760px; border-collapse: separate; border-spacing: 0; font-size: .9rem; }
.bench-table th, .bench-table td {
  padding: 12px 14px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border);
}
.bench-table th {
  position: sticky; top: 0; z-index: 1; background: var(--surface); color: var(--muted);
  font-size: .7rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
}
.bench-table tbody tr:nth-child(even) { background: color-mix(in srgb, var(--code) 55%, var(--surface)); }
.bench-table tbody tr:hover { background: color-mix(in srgb, var(--accent) 7%, var(--surface)); }
.bench-table td:nth-child(2), .bench-table td:nth-child(7) { white-space: nowrap; }
.bench-table td:nth-child(3), .bench-table td:nth-child(4),
.bench-table td:nth-child(5), .bench-table td:nth-child(6) {
  text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums;
}
.bench-table th[data-sort] { cursor: pointer; user-select: none; }
.bench-table th[data-sort]:hover { background: var(--code); }
.bench-sort-icon::after { content: "↕"; color: var(--muted); font-size: .78rem; margin-left: 4px; }
.bench-table th.sort-asc .bench-sort-icon::after { content: "↑"; }
.bench-table th.sort-desc .bench-sort-icon::after { content: "↓"; }
.bench-produto { display: flex; gap: 12px; align-items: flex-start; }
.bench-thumb {
  width: 48px; height: 48px; flex: none; object-fit: contain; border-radius: 10px;
  border: 1px solid var(--border); background: var(--bg);
}
.bench-thumb.vazio { border-style: dashed; }
.bench-nome { font-weight: 700; font-size: .9rem; line-height: 1.35; }
.bench-nome a { color: var(--text); }
.bench-nome a:hover { color: var(--accent); }
.bench-descricao {
  display: -webkit-box; margin-top: 3px; overflow: hidden; color: var(--muted); font-size: .8rem;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-height: 1.4;
}
.bench-tag {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  background: var(--code); color: var(--muted); font-size: .72rem; font-weight: 700;
}
.bench-stores { font-weight: 700; }
.bench-min { color: #16a34a; font-weight: 800; font-variant-numeric: tabular-nums; }
.bench-max { color: #dc2626; font-weight: 700; font-variant-numeric: tabular-nums; }
.bench-avg { font-weight: 600; font-variant-numeric: tabular-nums; }
.bench-store-best { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; }
.bench-store-best::before {
  content: ""; width: 7px; height: 7px; border-radius: 50%; background: #16a34a;
}
.bench-vazio {
  padding: 30px 24px; border: 1px dashed var(--border); border-radius: var(--radius);
  background: var(--surface); color: var(--muted); text-align: center;
}

/* ---------- Nota legal ---------- */
.bench-nota {
  display: flex; flex-direction: column; gap: 12px; margin-top: 34px; padding: 18px 20px;
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface);
}
.bench-nota-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.bench-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
  background: var(--code); color: var(--text); font-size: .74rem; font-weight: 700;
}
.bench-chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.bench-nota p { margin: 0; color: var(--muted); font-size: .82rem; line-height: 1.55; }

/* ---------- Ecrãs estreitos ---------- */
@media (max-width: 980px) {
  .bench-lista { grid-template-columns: 1fr; }
  .bench-filtros { position: static; }
  .bench-filtros form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: end; }
  .bench-filtros form .bench-campo:first-of-type { grid-column: 1 / -1; }
  .bench-lojas { border-top: 1px solid var(--border); }
}
@media (max-width: 900px) {
  .bench-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bench-hero { grid-template-columns: 1fr; }
  .bench-hero-acoes { justify-content: flex-start; }
  .bench-cards { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .bench-hero { padding: 20px; }
  .bench-destaque { grid-template-columns: 1fr; }
  .bench-destaque-preco { padding-right: 0; border-right: 0; }
  .bench-cta { width: 100%; }
  .bench-items-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
  .bench-item-corpo { padding: 10px 12px 12px; }
  .bench-item-nome { font-size: .87rem; }
  .bench-item-preco strong { font-size: 1.08rem; }
}
@media (max-width: 620px) {
  .bench-barra, .bench-eixo { grid-template-columns: 84px minmax(0, 1fr) 66px; }
  .bench-filtros form { grid-template-columns: 1fr; }
  .bench-item-cta { min-height: 44px; }
  .bench-view-btn { min-height: 44px; }
}
@media (max-width: 420px) {
  .bench-kpis { grid-template-columns: 1fr; }
  .bench-kpi--destaque { grid-column: auto; }
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
        return _formatar_moeda(valor, moeda)

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

    recolha_em = ((benchmark.get("last_run") or {}).get("at") or "")[:19]
    recolha_txt = _data_recolha(recolha_em)
    dispersao_media = f"{kpis['avg_spread_pct']}%" if kpis.get("avg_spread_pct") is not None else "—"
    titulo = str(benchmark.get("name") or "Benchmark")
    descricao = str(benchmark.get("description") or "O mesmo produto comparado entre lojas.")
    caminho = f"/site/benchmarks/{benchmark.get('slug')}/pesquisa"
    view = "table" if str(view or "card") == "table" else "card"

    cards_lista: List[str] = []
    linhas_tabela: List[str] = []
    for posicao, produto in enumerate(produtos):
        dados = _render_linha_produto(produto)
        melhor = produto.get("best") or {}
        marca_card = str(produto.get("brand") or "").strip()
        imagem = str(melhor.get("image") or "").strip()
        chave = _ancora_produto(produto, posicao)
        lojas_count = int(produto.get("stores") or 0)
        economia = produto.get("saving_abs") if lojas_count > 1 else None
        selo = f'<span class="bench-item-poupanca">poupa {_eur(economia)}</span>' if economia else ""
        figura = (
            f'<img class="bench-item-img" src="{escape(imagem, quote=True)}" alt="" loading="lazy" '
            'referrerpolicy="no-referrer">'
            if imagem
            else '<span class="bench-item-semimagem"></span>'
        )
        estrela = site_acoes.botao_favorito(
            chave=f"{caminho}#{chave}",
            url=f"{caminho}#p-{chave}",
            titulo=str(produto.get("product_name") or ""),
            tipo="produto",
            imagem=imagem,
            preco=_eur(produto.get("price_min")),
            nota=str(melhor.get("store_name") or ""),
            classe="bench-item-fav",
        )
        link_loja = str(melhor.get("url") or "").strip()
        cta = (
            f'<a class="bench-item-cta" href="{escape(link_loja, quote=True)}" target="_blank" '
            'rel="noopener nofollow">Ver preços</a>'
            if link_loja
            else '<span class="bench-item-cta bench-item-cta--off">Sem ligação à loja</span>'
        )
        lojas_label = f"{lojas_count} {'loja' if lojas_count == 1 else 'lojas'}"
        cards_lista.append(
            f'<article class="bench-item" id="p-{chave}">'
            f'<div class="bench-item-figura">{figura}{selo}{estrela}</div>'
            '<div class="bench-item-corpo">'
            + (f'<span class="bench-item-marca">{escape(marca_card)}</span>' if marca_card else "")
            + f'<h3 class="bench-item-nome">{dados["nome_html"]}</h3>'
            f'<p class="bench-item-preco"><span>desde</span><strong>{dados["price_min"]}</strong></p>'
            f'<p class="bench-item-lojas">em {lojas_label} · até {dados["price_max"]}</p>'
            f"{cta}"
            "</div></article>"
        )
        linhas_tabela.append(
            "<tr>"
            f'<td data-label="Produto"><div class="bench-produto">{dados["miniatura"]}<div>'
            f'<span class="bench-nome">{dados["nome_html"]}</span> '
            f'<span class="bench-tag">{dados["lojas_label"]}</span>{dados["descricao"]}'
            "</div></div></td>"
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

    def _url(**mudancas: Any) -> str:
        """O endereço da página com os filtros atuais e as mudanças pedidas.

        Um valor vazio tira o parâmetro — é assim que «todas as lojas» e a
        vista de cartões voltam ao endereço limpo.
        """
        params: Dict[str, str] = {}
        if q:
            params["q"] = q
        if loja:
            params["loja"] = loja
        if ordem != "dispersao":
            params["ordem"] = ordem
        if view != "card":
            params["view"] = view
        for nome, valor in mudancas.items():
            if valor:
                params[nome] = str(valor)
            else:
                params.pop(nome, None)
        query = "&amp;".join(
            f"{nome}={escape(str(valor), quote=True)}" for nome, valor in params.items()
        )
        return f"{caminho}?{query}" if query else caminho

    def _view_url(novo_view: str) -> str:
        return _url(view="" if novo_view == "card" else novo_view)

    def _loja_url(loja_id: str) -> str:
        return _url(loja="" if loja_id == loja else loja_id)

    # Lojas do estudo na barra lateral: um atalho por loja, com o nº de produtos.
    lojas_ligacoes: List[str] = []
    loja_nome = ""
    for item_loja in estudo.get("stores") or []:
        nome_loja = str(item_loja.get("store_name") or item_loja.get("store_id") or "Loja")
        id_loja = _store_id(item_loja)
        if id_loja == loja:
            loja_nome = nome_loja
        atual = ' aria-current="true"' if id_loja == loja else ""
        lojas_ligacoes.append(
            f'<a href="{_loja_url(id_loja)}"{atual}>'
            f"<span>{escape(nome_loja)}</span><em>{int(item_loja.get('produtos') or 0)}</em></a>"
        )
    lojas_html = (
        '<div class="bench-lojas"><h3>Lojas no estudo</h3>' + "".join(lojas_ligacoes) + "</div>"
        if lojas_ligacoes
        else ""
    )

    # -----------------------------------------------------------------------
    # Gráficos: índice de preço e preço médio por loja
    # -----------------------------------------------------------------------
    lojas_stats = estudo.get("stores") or []
    lojas_ordenadas = sorted(lojas_stats, key=lambda item: float(item.get("indice_preco") or 9999))

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

    def _eixo(marcas: List[Tuple[float, str]]) -> str:
        pontos = "".join(
            f'<i style="left:{posicao:.1f}%">{escape(rotulo)}</i>' for posicao, rotulo in marcas
        )
        return (
            '<div class="bench-eixo" aria-hidden="true"><span></span>'
            f'<span class="bench-eixo-trilho">{pontos}</span><span></span></div>'
        )

    marker_pct = 100.0 * 100.0 / 140.0  # posição do marcador «100» no trilho
    linhas_indice: List[str] = []
    for idx, item_loja in enumerate(lojas_ordenadas[:8]):
        nome = escape(str(item_loja.get("store_name") or item_loja.get("store_id") or "Loja"))
        indice = item_loja.get("indice_preco")
        valor = f"{indice:.0f}" if indice is not None else "—"
        pct = _bar_width_index(indice)
        linhas_indice.append(
            '<div class="bench-barra">'
            f'<span class="bench-barra-rotulo" title="{nome}">{nome}</span>'
            '<span class="bench-barra-trilho">'
            f'<span class="bench-barra-fill{" best" if idx == 0 else ""}" style="width:{pct:.1f}%"></span>'
            f'<span class="bench-barra-marca" style="left:{marker_pct:.1f}%"></span>'
            "</span>"
            f'<span class="bench-barra-valor">{valor}</span>'
            "</div>"
        )

    precos_validos = [
        float(item_loja.get("preco_medio") or 0)
        for item_loja in lojas_stats
        if item_loja.get("preco_medio")
    ]
    max_preco = max(precos_validos) if precos_validos else 0
    lojas_preco = sorted(lojas_stats, key=lambda item: float(item.get("preco_medio") or 0))
    linhas_preco: List[str] = []
    for idx, item_loja in enumerate(lojas_preco[:8]):
        nome = escape(str(item_loja.get("store_name") or item_loja.get("store_id") or "Loja"))
        preco = item_loja.get("preco_medio")
        pct = _bar_width_price(preco, max_preco)
        ofertas_loja = int(item_loja.get("ofertas") or 0)
        linhas_preco.append(
            '<div class="bench-barra">'
            f'<span class="bench-barra-rotulo" title="{nome}">{nome}</span>'
            '<span class="bench-barra-trilho">'
            f'<span class="bench-barra-fill{" best" if idx == 0 else ""}" style="width:{pct:.1f}%"></span>'
            "</span>"
            f'<span class="bench-barra-valor">{_eur(preco)}</span>'
            f'<span class="bench-barra-nota">{ofertas_loja} {"oferta" if ofertas_loja == 1 else "ofertas"}</span>'
            "</div>"
        )

    graficos_html = ""
    if lojas_stats:
        bloco_indice = (
            '<div class="bench-barras">' + "".join(linhas_indice) + "</div>"
            if linhas_indice
            else '<p class="bench-card-nota">Sem dados por loja.</p>'
        )
        bloco_preco = (
            '<div class="bench-barras">' + "".join(linhas_preco) + "</div>"
            if linhas_preco
            else '<p class="bench-card-nota">Sem preços por loja.</p>'
        )
        graficos_html = (
            '<section class="bench-seccao" aria-labelledby="bench-graficos">'
            '<div class="bench-seccao-topo"><div>'
            '<h2 id="bench-graficos">Onde se poupa mais</h2>'
            "<p>O índice compara cada loja com a média do estudo (100). O preço médio "
            "mostra quanto custa, em média, comprar nessa loja.</p>"
            "</div></div>"
            '<div class="bench-cards">'
            '<div class="bench-card">'
            '<div class="bench-card-topo"><h2>Índice de preço</h2>'
            '<span class="bench-card-nota">100 = média do estudo</span></div>'
            + bloco_indice
            + _eixo([(57.1, "80"), (71.4, "100"), (85.7, "120")])
            + "</div>"
            '<div class="bench-card">'
            '<div class="bench-card-topo"><h2>Preço médio por loja</h2>'
            '<span class="bench-card-nota">barra = preço médio</span></div>'
            + bloco_preco
            + _eixo([(0.0, "0"), (100.0, _eur(max_preco))])
            + "</div></div></section>"
        )

    # -----------------------------------------------------------------------
    # Melhor preço do estudo — sempre com uma oferta, mesmo quando o resumo
    # (`opportunities`) vem vazio: a ficha não pode dizer que não há comparações
    # com a lista cheia de produtos por baixo.
    # -----------------------------------------------------------------------
    oportunidades = estudo.get("opportunities") or []
    melhor_geral = (
        min(oportunidades, key=lambda item: item.get("price_min") or float("inf"))
        if oportunidades
        else None
    )
    if not melhor_geral:
        candidatos = [item for item in produtos if item.get("price_min") is not None]
        melhor_geral = min(candidatos, key=lambda item: item["price_min"]) if candidatos else None
    destaque_html = ""
    if melhor_geral:
        melhor_oferta = melhor_geral.get("best") or {}
        economia = melhor_geral.get("saving_abs")
        nota_preco = (
            f"Poupa até {_eur(economia)} face ao preço mais alto"
            if economia
            else "O preço mais baixo recolhido neste estudo"
        )
        lojas_melhor = int(melhor_geral.get("stores") or 0)
        if lojas_melhor > 1:
            nota_preco += f" · {lojas_melhor} lojas a vender"
        destaque_html = (
            '<section class="bench-destaque" aria-label="Melhor preço do estudo">'
            '<div class="bench-destaque-preco">'
            '<span class="bench-rotulo">Melhor preço</span>'
            f'<strong class="bench-destaque-valor">{_eur(melhor_geral.get("price_min"))}</strong>'
            f'<span class="bench-destaque-loja">{escape(str(melhor_oferta.get("store_name") or "—"))}</span>'
            "</div>"
            '<div class="bench-destaque-info">'
            f'<p class="bench-destaque-nome">{escape(str(melhor_geral.get("product_name") or ""))}</p>'
            f'<p class="bench-destaque-nota">{escape(nota_preco)}</p>'
            "</div>"
            '<a class="bench-cta" href="#lista-completa">Ver todos os produtos</a>'
            "</section>"
        )

    # Preço por tipo de peça — o resumo que continua a fazer sentido quando as
    # lojas vendem marcas diferentes.
    tipos_peca = [item for item in (estudo.get("garment_types") or []) if item.get("garment_type")]
    linhas_tipos = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('garment_type')))}</td>"
        f"<td>{int(item.get('offers') or 0)}</td>"
        f"<td>{int(item.get('stores') or 0)}</td>"
        f"<td>{_eur(item.get('price_avg'))}</td>"
        f"<td>{_eur(item.get('price_min'))}</td>"
        f"<td>{_eur(item.get('price_max'))}</td>"
        f"<td>{escape(str(item.get('cheapest_store') or '—'))} {_eur(item.get('cheapest_price'))}</td>"
        "</tr>"
        for item in tipos_peca
    )
    tipos_html = ""
    if linhas_tipos:
        tipos_html = (
            '<section class="bench-seccao" aria-labelledby="bench-tipos">'
            '<div class="bench-seccao-topo"><div>'
            '<h2 id="bench-tipos">Preço por tipo de peça</h2>'
            "<p>Média das ofertas recolhidas em cada tipo. Compara marcas diferentes; "
            "a comparação produto a produto só existe quando as lojas vendem o mesmo artigo.</p>"
            "</div></div>"
            '<div class="bench-table-wrap"><table class="bench-table"><thead><tr>'
            "<th>Tipo de peça</th><th>Ofertas</th><th>Lojas</th><th>Média</th><th>Mínimo</th>"
            "<th>Máximo</th><th>Loja mais barata</th>"
            f"</tr></thead><tbody>{linhas_tipos}</tbody></table></div>"
            "</section>"
        )

    base_url = str(cms.get_settings().get("base_url") or "").rstrip("/")
    acoes = site_acoes.barra_acoes(
        url=f"{base_url}{caminho}" if base_url else caminho,
        titulo=titulo,
        tipo="estudo",
        chave=caminho,
    )

    nota_filtros = f"{int(comparacao.get('total') or 0)} produtos"
    if q:
        nota_filtros += f" para «{q}»"
    if loja_nome:
        nota_filtros += f" · loja: {loja_nome}"
    limpar = (
        f'<a class="bench-limpar" href="{escape(caminho)}">Limpar filtros</a>'
        if (q or loja or ordem != "dispersao")
        else ""
    )
    ativa_card = " active" if view == "card" else ""
    ativa_table = " active" if view == "table" else ""

    corpo = f"""<div class="bench-wrap">
<header class="bench-hero">
  <div class="bench-hero-texto">
    <p class="bench-kicker">Benchmark de preços</p>
    <h1>{escape(titulo)}</h1>
    <p class="bench-lead">{escape(descricao)}</p>
    <p class="bench-hero-meta">
      <span><b>{int(kpis.get('offers') or 0)}</b> ofertas recolhidas</span>
      <span><b>{int(kpis.get('stores') or 0)}</b> lojas</span>
      <span><b>{int(kpis.get('products') or 0)}</b> produtos</span>
      <span>Recolha automática de {escape(recolha_txt)}</span>
    </p>
  </div>
  <div class="bench-hero-acoes">{acoes}</div>
</header>

<section class="bench-kpis" aria-label="Números do estudo">
  <div class="bench-kpi"><b>{int(kpis.get('offers') or 0)}</b><span>ofertas recolhidas</span></div>
  <div class="bench-kpi"><b>{int(kpis.get('products') or 0)}</b><span>produtos no estudo</span></div>
  <div class="bench-kpi"><b>{int(kpis.get('stores') or 0)}</b><span>lojas comparadas</span></div>
  <div class="bench-kpi"><b>{int(kpis.get('garment_types') or 0)}</b><span>tipos de peça</span></div>
  <div class="bench-kpi"><b>{int(kpis.get('comparable_products') or 0)}</b><span>produtos em 2+ lojas</span></div>
  <div class="bench-kpi"><b>{dispersao_media}</b><span>dispersão média</span></div>
  <div class="bench-kpi bench-kpi--destaque"><b>{_eur(kpis.get('potential_saving_eur'))}</b><span>poupança se escolher sempre o mínimo</span></div>
</section>

{destaque_html}

{graficos_html}

{tipos_html}

<section class="bench-lista" aria-labelledby="lista-completa">
  <aside class="bench-filtros" aria-label="Filtros do estudo">
    <h2>Filtrar</h2>
    <form method="get" action="{escape(caminho)}">
      <label class="bench-campo"><span>Produto ou marca</span>
        <input type="search" name="q" value="{escape(q)}" placeholder="Ex.: sapatilhas running">
      </label>
      <label class="bench-campo"><span>Loja</span>
        <select name="loja"><option value="">todas as lojas</option>{opcoes_loja}</select>
      </label>
      <label class="bench-campo"><span>Ordenar por</span>
        <select name="ordem">{opcoes_ordem}</select>
      </label>
      <input type="hidden" name="view" value="{view}">
      <button type="submit" class="bench-botao">Aplicar filtros</button>
      {limpar}
    </form>
    {lojas_html}
  </aside>

  <div class="bench-resultados">
    <div class="bench-view-header">
      <div>
        <h2 id="lista-completa" class="bench-section-title">Onde está mais barato</h2>
        <p class="bench-resultados-nota">{escape(nota_filtros)}</p>
      </div>
      <div class="bench-view-actions">
        <button type="button" class="bench-view-btn" data-bench-sort-dir title="Inverter a ordem dos resultados">
          Inverter ordem
        </button>
        <div class="bench-view-toggle" role="group" aria-label="Tipo de visualização" data-bench-toggle>
          <a class="bench-view-btn{ativa_card}" href="{_view_url('card')}" data-view="card">Cartões</a>
          <a class="bench-view-btn{ativa_table}" href="{_view_url('table')}" data-view="table">Tabela</a>
        </div>
      </div>
    </div>
    <div class="bench-view-panel" data-view="card"{'' if view == 'card' else ' hidden'}>
      <div class="bench-items-grid" data-bench-items="card">{corpo_cards}</div>
    </div>
    <div class="bench-view-panel" data-view="table"{'' if view == 'table' else ' hidden'}>
      <div class="bench-table-wrap">
        <table class="bench-table" data-bench-table>
          <thead><tr>
            <th data-sort="text">Produto <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="number">Lojas <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="price">Mínimo <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="price">Máximo <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="price">Média <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="percent">Dispersão <span class="bench-sort-icon" aria-hidden="true"></span></th>
            <th data-sort="text">Loja mais barata <span class="bench-sort-icon" aria-hidden="true"></span></th>
          </tr></thead>
          <tbody>{corpo_tabela}</tbody>
        </table>
      </div>
    </div>
  </div>
</section>

<div class="bench-nota">
  <div class="bench-nota-chips">
    <span class="bench-chip">Melhor preço assinalado</span>
    <span class="bench-chip">Recolha automática</span>
    <span class="bench-chip">Preço publicado não é preço final</span>
  </div>
  <p>Dados recolhidos automaticamente dos sites das lojas. Última recolha: {escape(recolha_txt)}.
  Os preços podem estar desactualizados — confirme sempre na loja. Este estudo não é uma
  recomendação de compra.</p>
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

    const sortDirBtn = document.querySelector('[data-bench-sort-dir]');
    if (sortDirBtn) {{
      sortDirBtn.addEventListener('click', function(){{
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

    const table = document.querySelector('[data-bench-table]');
    if (table) {{
      const tbody = table.querySelector('tbody');
      const headers = table.querySelectorAll('thead th[data-sort]');
      headers.forEach(function(header){{
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
</script>"""

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
