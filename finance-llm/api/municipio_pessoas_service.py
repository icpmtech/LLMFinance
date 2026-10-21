"""Executivos das **308 câmaras municipais**.

O módulo constrói uma ficha por pessoa × concelho × cargo. A base é o **Mapa
Oficial n.º 2-B/2025 da CNE** — o documento que legalmente fixa quem foi eleito
para cada câmara (o presidente e os vereadores, com o partido por que foram
eleitos) — e é dele que saem os nomes dos **308 concelhos**. Por cima, o que só
existe nos sites das câmaras (`cm-*.pt`) acrescenta o resto: pelouros, fotografia
e a página de cada eleito.

Cada documento representa uma pessoa num cargo numa câmara num dado momento, e é
guardado no índice `finance_municipio_pessoas` para ser pesquisável no PessoasIQ.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from api.elasticsearch_client import (
    MUNICIPIO_PESSOAS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipio_pessoas"
CACHE_TTL_SECONDS = 24 * 60 * 60
_LOCK = threading.Lock()

USER_AGENT = "IQOS/1.0 (analise politica; contacto@icpm.tech)"

#: Eleição e mandato a que pertencem os executivos recolhidos.
ELEICAO = "Autárquicas 2025"
MANDATO = "2025-2029"

#: Proveniência da ficha. O identificador curto aparece no cartão da pessoa; o
#: documento é o que se cita quando se diz de onde vem o nome.
FONTE_CNE = "cne-mapa-oficial"
FONTE_CNE_DOCUMENTO = "CNE · Mapa Oficial n.º 2-B/2025 (mapa_3_eleitos)"

#: Cargos canónicos. É este o vocabulário do filtro de cargo do PessoasIQ: os
#: sites escrevem «Vereadora», «Vice-Presidente da Câmara Municipal», «Presidente
#: da Câmara Municipal» — sem os juntar, o filtro tinha uma entrada por forma de
#: escrever o mesmo cargo.
CARGO_PRESIDENTE = "Presidente"
CARGO_VICE_PRESIDENTE = "Vice-Presidente"
CARGO_VEREADOR = "Vereador"


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(name: str) -> Path:
    return _data_dir() / f"{name}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fold(value: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de pessoas e de concelhos."""
    sem_acentos = unicodedata.normalize("NFKD", value or "")
    sem_acentos = "".join(ch for ch in sem_acentos if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _split_pelouros(pelouro_part: str) -> List[str]:
    """Divide pelouros pelo padrão 'Pelouro do/da/de...'.

    O texto vem como 'Pelouro da X, Pelouro da Y e Pelouro da Z'. Separamos
    por vírgula e por 'e' antes de 'Pelouro'.
    """
    # Normaliza separadores para vírgula.
    text = re.sub(r"\s+e\s+(?=Pelouro)", ", ", pelouro_part, flags=re.IGNORECASE)
    return [p.strip() for p in text.split(",") if p.strip().lower().startswith("pelouro")]


def _normalize_party(raw: str) -> str:
    """Normaliza siglas/partidos extraídos do texto do site."""
    if not raw:
        return ""
    # Corrige extrações truncadas como "PP.IL" vindas de `[^-]+$` no fim.
    raw = raw.strip()
    if raw.lower() in ("pp.il", "pp.il."):
        return "PPD/PSD.CDS-PP.IL"
    if raw == "PP" or raw == "PP.":
        return "PS"
    return raw


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")


def _cargo_canonico(cargo: Optional[str], base: Optional[str] = None) -> str:
    """Cargo reduzido ao vocabulário do módulo (presidente, vice, vereador)."""
    texto = _fold(cargo or "")
    if texto.startswith("vice"):
        return CARGO_VICE_PRESIDENTE
    if texto.startswith("president"):
        return CARGO_PRESIDENTE
    if texto.startswith("vereador"):
        return CARGO_VEREADOR
    return base or CARGO_VEREADOR


def _pelouros_de(atribuicoes: Any) -> List[str]:
    """Pelouros de um membro, venham já em lista ou no texto do site.

    Os sites guardam-nos de duas maneiras: uma lista, ou uma frase do género
    «Pelouro da Segurança e Pelouro das Finanças» que é preciso partir. Quando o
    texto não segue essa forma, guarda-se tal como foi lido — mais vale o que o
    município escreveu do que nada.
    """
    if not atribuicoes:
        return []
    if isinstance(atribuicoes, (list, tuple)):
        return [str(p).strip() for p in atribuicoes if str(p).strip()]
    texto = str(atribuicoes).strip()
    return _split_pelouros(texto) or ([texto] if texto else [])


def _fetch_html(url: str, timeout: float = 30.0) -> Optional[str]:
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("Falha a obter %s: %s", url, exc)
        return None


def _parse_executivo_cm_porto(html: str, source_url: str) -> List[Dict[str, Any]]:
    """Extrai membros do executivo da página `/executivo` da Câmara do Porto."""
    soup = BeautifulSoup(html, "html.parser")
    base_url = "{0.scheme}://{0.netloc}".format(urlparse(source_url))
    items: List[Dict[str, Any]] = []

    for content in soup.select(".content.col-md-4"):
        text = content.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        name = _normalize_name(lines[0])
        role_line = lines[1] if len(lines) > 1 else ""

        role = "Vereador"
        party = ""
        pelouros: List[str] = []

        if "Presidente da Câmara Municipal" in role_line:
            role = "Presidente"
        elif "Vice-Presidente" in role_line:
            role = "Vice-Presidente"

        if " - " in role_line:
            party = _normalize_party(role_line.rsplit(" - ", 1)[-1].strip())

        # Remove o prefixo do cargo/pelouro para extrair só os pelouros.
        pelouro_part = re.sub(
            r"^(Vereador[oa]?|Presidente da Câmara Municipal|Vice-Presidente da Câmara Municipal),?\s*",
            "",
            role_line.split(" - ")[0],
            flags=re.IGNORECASE,
        ).strip()
        if pelouro_part:
            pelouros = [
                p for p in _split_pelouros(pelouro_part)
                if p.lower().startswith("pelouro")
            ]

        # Procura foto no elemento ou no link individual: o site usa `imageBg`
        # com `background-image:url("...")` em vez de `<img>`.
        photo_url = None
        profile_url = None
        for link in content.find_all("a", href=re.compile(r"executivo/")):
            href = link.get("href", "")
            if not profile_url and href:
                profile_url = urljoin(base_url, href)
            style = link.get("style") or ""
            m = re.search(r'background-image\s*:\s*url\("?([^"\)]+)"?\)', style)
            if m and not photo_url:
                photo_url = urljoin(base_url, m.group(1).strip().replace("&quot;", "").replace("\"", ""))
            if profile_url and photo_url:
                break

        if not photo_url:
            img = content.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    photo_url = urljoin(base_url, src)

        items.append({
            "name": name,
            "role": role,
            "party": party,
            "pelouros": pelouros,
            "concelho": "Porto",
            "district": "Porto",
            "source_url": source_url,
            "profile_url": profile_url,
            "photo_url": photo_url,
            "source": "cm-porto",
            "raw_role": role_line,
        })

    return items


def _build_doc_id(item: Dict[str, Any]) -> str:
    """Identificador estável de uma pessoa no executivo de um concelho.

    Leva o distrito porque o nome do concelho não chega: «Lagoa» é concelho no
    Algarve e nos Açores, e «Calheta» na Madeira e nos Açores. Não leva a
    proveniência porque a mesma pessoa é enriquecida ao longo do tempo (o site da
    câmara acrescenta-lhe pelouros e fotografia) e um identificador que mudasse com
    a fonte deixaria duas fichas da mesma pessoa no índice.
    """
    return (
        f"municipio-{_slug(item.get('district') or '')}"
        f"-{_slug(item['concelho'])}-{_slug(item['name'])}"
    )


def _remuneracoes() -> Any:
    """Serviço das remunerações (import tardio: evita um ciclo entre serviços)."""
    from api import remuneracoes_service

    return remuneracoes_service


def _mapa_oficial() -> Dict[str, Any]:
    """Nomes de todos os eleitos para as câmaras (Mapa Oficial da CNE)."""
    try:
        return _remuneracoes().nomes_eleitos()
    except Exception as exc:
        logger.warning("Mapa Oficial da CNE indisponível: %s", exc)
        return {}


def _doc_do_mapa(
    registo: Dict[str, Any],
    nome: str,
    cargo: str,
    sigla: Optional[str],
    cargo_original: Optional[str],
) -> Dict[str, Any]:
    """Ficha, ainda sem os detalhes do site, de quem o Mapa Oficial diz eleito."""
    nome = _normalize_name(nome)
    return {
        "doc_id": _build_doc_id({
            "district": registo.get("distrito"),
            "concelho": registo["concelho"],
            "name": nome,
        }),
        "name": nome,
        "name_keyword": nome.lower(),
        "role": cargo,
        "role_keyword": cargo.lower(),
        "party": sigla or "",
        "party_keyword": (sigla or "").lower(),
        "concelho": registo["concelho"],
        "concelho_keyword": registo["concelho"].lower(),
        "district": registo.get("distrito") or "",
        "district_keyword": (registo.get("distrito") or "").lower(),
        "concelho_id": registo.get("concelho_id"),
        "codigo_ine": registo.get("codigo_ine"),
        "election": ELEICAO,
        "mandato": MANDATO,
        "pelouros": [],
        "photo_url": None,
        "profile_url": None,
        "email": None,
        "curriculo_url": None,
        "source": FONTE_CNE,
        "source_url": None,
        "raw_role": (cargo_original or cargo).strip(),
    }


def _pessoas_do_mapa(registo: Dict[str, Any]) -> List[Dict[str, Any]]:
    """O presidente e os vereadores eleitos para a câmara de um concelho."""
    if not (registo.get("concelho") or "").strip():
        return []
    pessoas: List[Dict[str, Any]] = []
    presidente = registo.get("presidente") or {}
    if (presidente.get("nome") or "").strip():
        pessoas.append(_doc_do_mapa(
            registo,
            presidente["nome"],
            CARGO_PRESIDENTE,
            presidente.get("sigla"),
            presidente.get("cargo"),
        ))
    for vereador in registo.get("vereadores") or []:
        if (vereador.get("nome") or "").strip():
            pessoas.append(_doc_do_mapa(
                registo,
                vereador["nome"],
                CARGO_VEREADOR,
                vereador.get("sigla"),
                vereador.get("cargo"),
            ))
    return pessoas


def _site_do_url(url: Optional[str]) -> Optional[str]:
    """Nome curto da câmara a partir do URL da sua página («cm-porto»).

    O domínio das câmaras é do género `www.cm-porto.pt`, pelo que o primeiro
    rótulo é já o nome curto — e é o mesmo que o scraper escreve no `source`, sem
    o que a mesma câmara apareceria com duas proveniências diferentes.
    """
    host = urlparse(url or "").netloc.lower()
    if not host:
        return None
    return host[4:].split(".")[0] if host.startswith("www.") else host.split(".")[0]


def _indice_concelhos(concelhos: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Nome do concelho → id, com `None` onde o nome é ambíguo.

    «Lagoa» é concelho no Algarve e nos Açores, e «Calheta» na Madeira e nos
    Açores: um nome repetido não identifica um concelho. Fica com `None` para que
    quem só saiba o nome — o scraper do Porto, por exemplo — não enriqueça as
    pessoas do concelho errado.
    """
    ids: Dict[str, set] = {}
    for registo in concelhos.values():
        nome = _slug(registo.get("concelho") or "")
        if nome:
            ids.setdefault(nome, set()).add(registo.get("concelho_id"))
    return {
        nome: (next(iter(valores)) if len(valores) == 1 else None)
        for nome, valores in ids.items()
    }


def _membro_do_site(
    item: Dict[str, Any],
    site: Optional[str] = None,
    site_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Membro lido de um site de câmara, na forma comum do módulo.

    As proveniências de detalhes escrevem os campos de maneiras diferentes — o
    ficheiro curado das remunerações em português, o scraper do Porto em inglês —
    e é aqui que passam a ter todos a mesma forma.
    """
    return {
        "nome": _normalize_name(item.get("nome") or item.get("name") or ""),
        "cargo": item.get("cargo") or item.get("raw_role") or item.get("role") or "",
        "partido": item.get("partido") or item.get("party") or "",
        "pelouros": _pelouros_de(item.get("pelouros") or item.get("atribuicoes")),
        "url": item.get("url") or item.get("profile_url"),
        "photo_url": item.get("photo_url") or item.get("foto_url"),
        "email": item.get("email"),
        "curriculo_url": item.get("curriculo_url"),
        "site": site or item.get("source"),
        "site_url": site_url or item.get("source_url"),
    }


def _detalhes_dos_sites(
    concelhos: Dict[str, Any],
    refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Detalhes de executivos lidos dos sites das câmaras, por concelho.

    São duas proveniências: o ficheiro curado das remunerações, onde cada município
    já lido guarda os seus membros com pelouros e páginas, e a página do executivo
    da Câmara do Porto, que é a única que traz fotografias.
    """
    entradas: List[Dict[str, Any]] = []
    fontes: List[Dict[str, Any]] = []
    por_nome = _indice_concelhos(concelhos)

    def entrada(nome: Optional[str], concelho_id: Optional[int], membros: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        alvo = concelho_id or por_nome.get(_slug(nome or ""))
        if alvo is None:
            logger.warning("Detalhes de %r sem concelho identificável: ignorados", nome)
            return None
        return {"concelho_id": alvo, "concelho": nome, "membros": membros}

    try:
        dados = _remuneracoes().executivos()
    except Exception as exc:
        logger.warning("Executivos dos municípios indisponíveis: %s", exc)
        dados = {}

    importados: List[str] = []
    for registo in (dados.get("concelhos") or {}).values():
        membros = [
            membro
            for membro in (
                _membro_do_site(m, _site_do_url(registo.get("fonte_url")), registo.get("fonte_url"))
                for m in (registo.get("membros") or [])
            )
            if membro["nome"]
        ]
        if not membros:
            continue
        registo_entrada = entrada(registo.get("nome"), registo.get("concelho_id"), membros)
        if registo_entrada:
            entradas.append(registo_entrada)
            importados.append(registo.get("nome"))
    if importados:
        fontes.append({
            "documento": (dados.get("fonte") or {}).get("documento") or "sites das câmaras municipais",
            "nota": (dados.get("fonte") or {}).get("nota"),
            "concelhos": importados,
        })

    porto = scrape_cm_porto(refresh=refresh)
    if not porto.get("error") and porto.get("items"):
        membros = [
            _membro_do_site(m, porto.get("source") or "cm-porto", porto.get("url"))
            for m in porto["items"]
        ]
        registo_entrada = entrada(porto.get("concelho") or "Porto", None, membros)
        if registo_entrada:
            entradas.append(registo_entrada)
            fontes.append({
                "documento": "cm-porto.pt · página do executivo",
                "url": porto.get("url"),
                "concelhos": [porto.get("concelho") or "Porto"],
            })

    return entradas, fontes


def _doc_extra(registo: Dict[str, Any], membro: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ficha de quem o site da câmara tem no executivo e o Mapa Oficial não.

    Ao longo do mandato há substituições — renúncias, falecimentos, mudanças de
    pelouro — que só o site do município publica: o mapa diz quem foi **eleito**,
    não quem está no cargo hoje. Sem esta ficha, quem substituiu um eleito
    desaparecia da lista dos executivos.
    """
    nome = membro.get("nome")
    if not nome:
        return None
    doc = _doc_do_mapa(
        registo,
        nome,
        _cargo_canonico(membro.get("cargo")),
        membro.get("partido"),
        membro.get("cargo"),
    )
    doc["source"] = membro.get("site") or FONTE_CNE
    doc["source_url"] = membro.get("site_url")
    return doc


def _aplicar_membro(item: Dict[str, Any], membro: Dict[str, Any]) -> None:
    """Acrescenta a uma ficha o que o site da câmara sabe dela."""
    item["role"] = _cargo_canonico(membro.get("cargo"), item["role"])
    item["role_keyword"] = item["role"].lower()
    if membro.get("partido"):
        item["party"] = membro["partido"]
        item["party_keyword"] = item["party"].lower()
    if membro.get("pelouros"):
        item["pelouros"] = membro["pelouros"]
    if membro.get("url"):
        item["profile_url"] = membro["url"]
    if membro.get("photo_url"):
        item["photo_url"] = membro["photo_url"]
    if membro.get("email"):
        item["email"] = membro["email"]
    if membro.get("curriculo_url"):
        item["curriculo_url"] = membro["curriculo_url"]
    if membro.get("site"):
        item["source"] = membro["site"]
        item["source_url"] = membro.get("site_url") or item["source_url"]


def _aplicar_detalhes(
    itens: List[Dict[str, Any]],
    entradas: List[Dict[str, Any]],
    registos: Dict[Any, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Cola os detalhes de cada site ao eleito do Mapa Oficial com o mesmo nome.

    O casamento é feito **dentro do mesmo concelho** (pelo id, que só ele
    distingue as duas «Lagoa») e por palavras, não por igualdade: os municípios
    abreviam os nomes («Pedro Duarte» para «Pedro Miguel de Azeredo Duarte»).
    Quem o site tenha e o mapa não é acrescentado, não descartado.
    """
    por_concelho: Dict[Any, List[Dict[str, Any]]] = {}
    for entrada in entradas:
        por_concelho.setdefault(entrada.get("concelho_id"), []).extend(entrada.get("membros") or [])

    itens_por_concelho: Dict[Any, List[Dict[str, Any]]] = {}
    for item in itens:
        itens_por_concelho.setdefault(item.get("concelho_id"), []).append(item)

    nomes_iguais = _remuneracoes().nomes_da_mesma_pessoa
    extras: List[Dict[str, Any]] = []
    for concelho_id, membros in por_concelho.items():
        registo = registos.get(concelho_id)
        if not registo:
            continue
        pessoas = itens_por_concelho.setdefault(concelho_id, [])
        for membro in membros:
            alvo = next(
                (pessoa for pessoa in pessoas if nomes_iguais(membro.get("nome"), pessoa["name"])),
                None,
            )
            if alvo is None:
                alvo = _doc_extra(registo, membro)
                if alvo is None:
                    continue
                extras.append(alvo)
                pessoas.append(alvo)
            _aplicar_membro(alvo, membro)
    return [*itens, *extras]


def collect_executivos(refresh: bool = False) -> Dict[str, Any]:
    """Junta o executivo dos 308 concelhos: quem foi eleito e o que diz o site.

    Os nomes e os partidos vêm do Mapa Oficial da CNE, a única fonte que os traz
    todos; os pelouros, a fotografia e a página de cada eleito vêm dos sites das
    câmaras e existem só para os concelhos já lidos. Um concelho sem site lido não
    fica de fora: fica com a ficha do mapa. Quem o site tenha no executivo e o mapa
    não (substituições a meio do mandato) entra com o site como proveniência.
    """
    mapa = _mapa_oficial()
    concelhos = mapa.get("concelhos") or {}
    if not concelhos:
        return {"error": "Mapa Oficial da CNE indisponível", "concelhos": 0, "total": 0, "items": []}

    itens: List[Dict[str, Any]] = []
    for registo in concelhos.values():
        itens.extend(_pessoas_do_mapa(registo))

    fonte_mapa = {
        "documento": FONTE_CNE_DOCUMENTO,
        "url": mapa.get("fonte_pagina") or mapa.get("fonte_url"),
        "nota": mapa.get("nota"),
        "recolhido_em": mapa.get("cached_at"),
        "concelhos": len(concelhos),
    }
    for item in itens:
        item["source_url"] = fonte_mapa["url"]

    entradas, fontes_sites = _detalhes_dos_sites(concelhos, refresh=refresh)
    if entradas:
        registos = {registo.get("concelho_id"): registo for registo in concelhos.values()}
        itens = _aplicar_detalhes(itens, entradas, registos)

    agora = _now_iso()
    for item in itens:
        item["ingested_at"] = agora
        item["updated_at"] = agora

    return {
        "concelhos": len({(item["district"], item["concelho"]) for item in itens}),
        "total": len(itens),
        "fontes": [fonte_mapa, *fontes_sites],
        "items": itens,
    }


def _read_cache(name: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", "")
        if cached_at:
            try:
                dt = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > CACHE_TTL_SECONDS:
                    return None
            except Exception:
                return None
        return data
    except Exception as exc:
        logger.debug("Cache %s inválida: %s", name, exc)
        return None


def _write_cache(name: str, payload: Dict[str, Any]) -> None:
    path = _cache_path(name)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Não foi possível guardar cache %s: %s", name, exc)


def scrape_cm_porto(refresh: bool = False) -> Dict[str, Any]:
    """Recolhe o executivo da Câmara Municipal do Porto."""
    cache_name = "cm_porto_executivo"
    if not refresh:
        cached = _read_cache(cache_name)
        if cached:
            return cached

    url = "https://www.cm-porto.pt/executivo"
    html = _fetch_html(url)
    if not html:
        return {"error": "Não foi possível obter a página", "url": url}

    items = _parse_executivo_cm_porto(html, url)
    now = _now_iso()
    for item in items:
        item["doc_id"] = _build_doc_id(item)
        item["ingested_at"] = now
        item["updated_at"] = now

    payload = {
        "cached_at": now,
        "url": url,
        "source": "cm-porto",
        "concelho": "Porto",
        "district": "Porto",
        "total": len(items),
        "items": items,
    }
    _write_cache(cache_name, payload)
    return payload


def _reset_index(client: Any) -> None:
    """Apaga o índice: uma recolha nova não pode deixar lá o que já não é verdade."""
    try:
        client.indices.delete(index=MUNICIPIO_PESSOAS_INDEX, ignore_unavailable=True)
    except Exception as exc:
        logger.warning("Não foi possível limpar %s: %s", MUNICIPIO_PESSOAS_INDEX, exc)


def index_municipio_pessoas(
    items: Iterable[Dict[str, Any]],
    es: Optional[Any] = None,
    substituir: bool = False,
) -> Dict[str, Any]:
    """Indexa documentos no índice `finance_municipio_pessoas`.

    Com `substituir`, o índice é esvaziado primeiro. É o que se quer quando a
    recolha é completa (os 308 concelhos): os nomes podem aparecer escritos de
    outra maneira — «Pedro Duarte» passa a «Pedro Miguel de Azeredo Duarte» — e a
    ficha antiga ficaria no índice como se fosse outra pessoa.
    """
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    if substituir:
        _reset_index(client)
    ensure_indices(client)

    actions = []
    now = _now_iso()
    for item in items:
        doc = dict(item)
        doc.setdefault("ingested_at", now)
        doc.setdefault("updated_at", now)
        doc_id = doc.get("doc_id") or _build_doc_id(doc)
        actions.append({
            "_op_type": "index",
            "_index": MUNICIPIO_PESSOAS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=MUNICIPIO_PESSOAS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}


def search_municipio_pessoas(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    role: Optional[str] = None,
    size: int = 50,
    page: int = 1,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pesquisa no índice `finance_municipio_pessoas`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"name": {"query": q, "boost": 6}}},
                    {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
                    {"wildcard": {"party.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"role": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"role_keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"concelho.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"pelouros": {"value": f"*{q}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if district:
        filters.append({"wildcard": {"district.keyword": {"value": f"*{district}*", "case_insensitive": True}}})
    if concelho:
        filters.append({"wildcard": {"concelho.keyword": {"value": f"*{concelho}*", "case_insensitive": True}}})
    if party:
        filters.append({"wildcard": {"party.keyword": {"value": f"*{party}*", "case_insensitive": True}}})
    if role:
        filters.append({"wildcard": {"role": {"value": f"*{role}*", "case_insensitive": True}}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters

    query = {"bool": bool_query} if bool_query else {"match_all": {}}
    from_ = max(0, (page - 1) * size)

    body = {
        "query": query,
        "from": from_,
        "size": max(1, min(size, 500)),
        "sort": [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}],
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=MUNICIPIO_PESSOAS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def stats(es: Optional[Any] = None) -> Dict[str, Any]:
    """Resumo do índice de executivos municipais."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=MUNICIPIO_PESSOAS_INDEX).get("count", 0)
        if not count:
            return {"index": MUNICIPIO_PESSOAS_INDEX, "documents": 0}
        resp = client.search(
            index=MUNICIPIO_PESSOAS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    # Os 308 concelhos e as ~100 siglas partem dos limites por
                    # omissão das agregações (10): é o filtro do PessoasIQ que
                    # depende de virem todos. Os concelhos vêm dentro do seu
                    # distrito para o filtro não ter de carregar o país inteiro
                    # antes de se escolher o distrito.
                    "by_concelho": {"terms": {"field": "concelho.keyword", "size": 400}},
                    "by_district": {
                        "terms": {"field": "district.keyword", "size": 30},
                        "aggs": {"concelhos": {"terms": {"field": "concelho.keyword", "size": 40}}},
                    },
                    "by_party": {"terms": {"field": "party.keyword", "size": 200}},
                    # `role` é `keyword`: é no próprio campo que se agrega, não em
                    # `role.keyword`, que não existe (e deixava o filtro de cargo vazio).
                    "by_role": {"terms": {"field": "role", "size": 20}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        return {
            "index": MUNICIPIO_PESSOAS_INDEX,
            "documents": count,
            "by_concelho": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_concelho", {}).get("buckets", [])],
            "by_district": [
                {
                    "key": b["key"],
                    "count": b["doc_count"],
                    "concelhos": [
                        {"key": c["key"], "count": c["doc_count"]}
                        for c in b.get("concelhos", {}).get("buckets", [])
                    ],
                }
                for b in aggs.get("by_district", {}).get("buckets", [])
            ],
            "by_party": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_party", {}).get("buckets", [])],
            "by_role": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_role", {}).get("buckets", [])],
        }
    except Exception as exc:
        return {"error": str(exc)}


def refresh_executivos(refresh: bool = True) -> Dict[str, Any]:
    """Recolhe e reindexa o executivo de todos os concelhos.

    O índice é substituído por inteiro: é uma vista derivada do Mapa Oficial e dos
    sites das câmaras, pelo que o que lá estiver a mais é lixo de uma recolha
    anterior (nomes escritos de outra maneira, pessoas que já deixaram o cargo).
    """
    dados = collect_executivos(refresh=refresh)
    if dados.get("error"):
        return dados
    itens = dados.get("items") or []
    resultado = index_municipio_pessoas(itens, substituir=True)
    return {
        "refreshed_at": _now_iso(),
        "concelhos": dados.get("concelhos"),
        "total": len(itens),
        "indexed": resultado.get("indexed"),
        "errors": resultado.get("errors"),
        "fontes": [fonte.get("documento") for fonte in dados.get("fontes") or []],
    }
