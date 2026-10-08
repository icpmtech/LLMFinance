"""Pesquisa profunda (estilo *Perplexity*) sobre os dados do IQ OS.

O motor faz três coisas, por esta ordem:

1. **Recupera** candidatos dos índices do Elasticsearch (contratos, empresas,
   pessoas, imprensa, recolha, contratos de Espanha, redes sociais, …) através
   do `search_service.unified_search` — a mesma pesquisa federada da página
   «Pesquisa total», para não haver duas verdades sobre os dados;
2. **Numera** os melhores candidatos como fontes `[1]`, `[2]`, … (com título,
   excerto, data e ligação), removendo repetidos;
3. **Pede a resposta** ao modelo configurado pelo utilizador (ou ao indicado no
   pedido), com a instrução de citar as fontes no formato `[n]`, e transmite-a
   token a token em SSE (o mesmo transporte do chat).

Sem fontes não há resposta gerada: é devolvida uma mensagem que o diz, para
nunca se inventar contratação pública que não esteja nos dados.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Sequence, Tuple

from api import providers_service as providers
from api import search_service
from api import vector_service as vectors

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- fontes

#: Catálogo dos âmbitos que podem alimentar a resposta. `weight` desempata a
#: fusão entre âmbitos (contratação pública vale mais do que uma notícia).
#: Todos entram por omissão: a pergunta é do utilizador e o motor deve procurar
#: em **todos** os dados — quem quiser afinar desliga os interruptores.
SOURCES: List[Dict[str, Any]] = [
    {"id": "contracts", "label": "Contratos", "hint": "Contratação pública portuguesa (portal BASE)", "default": True, "weight": 1.0},
    {"id": "entities", "label": "Empresas", "hint": "Cadastro de entidades (NIF, CAE, contactos)", "default": True, "weight": 0.95},
    {"id": "contracts_es", "label": "Contratos ES", "hint": "Contratação pública de Espanha (PLACSP)", "default": True, "weight": 0.9},
    {"id": "pessoas", "label": "Pessoas", "hint": "Fichas de pessoas (CIRE, registo societário)", "default": True, "weight": 0.9},
    {"id": "imprensa", "label": "Imprensa", "hint": "Notícias recolhidas dos jornais", "default": True, "weight": 0.85},
    {"id": "scraped", "label": "Recolha", "hint": "Dados recolhidos de sites (scraping)", "default": True, "weight": 0.8},
    {"id": "entities_es", "label": "Entidades ES", "hint": "Órgãos adjudicantes e empresas de Espanha", "default": True, "weight": 0.8},
    {"id": "news", "label": "Notícias", "hint": "Índice de notícias de mercado (`finance_news`)", "default": True, "weight": 0.75},
    {"id": "social", "label": "Redes sociais", "hint": "Publicações de LinkedIn, TikTok, Reddit e Facebook", "default": True, "weight": 0.7},
    {"id": "politicos", "label": "Políticos", "hint": "Políticos portugueses (Wikipédia e parlamento)", "default": True, "weight": 0.7},
    {"id": "wikipedia", "label": "Wikipédia", "hint": "Enciclopédia livre (PT e EN)", "default": True, "weight": 0.65},
    {"id": "trademarks", "label": "Marcas", "hint": "Marcas registadas (INPI)", "default": True, "weight": 0.6},
    {"id": "firmas", "label": "Firmas", "hint": "Firmas e denominações (RNPC)", "default": True, "weight": 0.6},
    {"id": "market", "label": "Mercado", "hint": "Tickers e cotações indexadas", "default": True, "weight": 0.55},
    {"id": "crm", "label": "CRM", "hint": "Contas, contactos e oportunidades internas", "default": True, "weight": 0.55, "session_scope": True},
]
SOURCES_BY_ID = {entry["id"]: entry for entry in SOURCES}
SOURCE_IDS = [entry["id"] for entry in SOURCES]
DEFAULT_SOURCE_IDS = [entry["id"] for entry in SOURCES if entry.get("default")]

#: Modos de recuperação. «Híbrido» junta palavras-chave (BM25, todos os âmbitos)
#: com vizinhos semânticos (kNN) fundidos por *Reciprocal Rank Fusion* — os scores
#: de BM25 e de coseno não são comparáveis directamente, por isso fundem-se por
#: posição (a mesma técnica do `vector_service.hybrid_search_contracts`).
MODES: List[Dict[str, Any]] = [
    {"id": "hybrid", "label": "Híbrido", "hint": "Palavras-chave + semântica (recommendado)"},
    {"id": "text", "label": "Palavras-chave", "hint": "Só BM25 (termos exactos: CPV, NIF, nomes)"},
    {"id": "vector", "label": "Semântica", "hint": "Só vizinhos semânticos (kNN)"},
]
MODE_IDS = [entry["id"] for entry in MODES]
DEFAULT_MODE = "hybrid"

#: Âmbitos com `dense_vector` (`embedding`, 384 dims) já preparado no Elasticsearch
#: pelo `vector_service`. Os restantes âmbitos só têm pesquisa por palavras.
VECTOR_INDEXES: Dict[str, str] = {
    "contracts": vectors.CONTRACTS_INDEX,
    "entities": vectors.ENTITIES_INDEX,
}
#: Cobertura mínima de embeddings para um âmbito valer a pena em kNN. Com 510
#: vectores em 2,25 M de contratos (0,02%) o kNN só trazia ruído: o âmbito fica
#: de fora até a indexação o tornar representativo.
MIN_VECTOR_PERCENT = 1.0
MIN_VECTOR_DOCS = 100

RRF_K = 60

#: Perguntas de exemplo (aparecem na página e quando uma busca não devolve nada).
EXAMPLES: List[str] = [
    "Quais os maiores contratos de 2025 na área da saúde?",
    "Que empresas ganharam mais contratos com a Comunidade Intermunicipal da Região de Leiria?",
    "Resume os contratos de videovigilância adjudicados no último ano e diz quem concorreu.",
    "Que notícias recentes ligam a EDP a contratação pública?",
]

#: A cobertura vectorial só muda quando corre a indexação: cache de 5 minutos
#: evita repetir as contagens do Elasticsearch a cada `/deep-search/meta`.
VECTOR_STATUS_TTL = 300.0
_vector_cache: Optional[Tuple[float, Dict[str, Any]]] = None

PER_SOURCE_DEFAULT = 6
#: O `unified_search` aceita no máximo 50 resultados por âmbito.
PER_SOURCE_MIN, PER_SOURCE_MAX = 2, 50
MAX_SOURCES_DEFAULT = 12
MAX_SOURCES_MIN, MAX_SOURCES_MAX = 4, 120

#: `max_sources = 0` significa «sem limite»: recolhe-se tudo o que cada âmbito
#: devolver. O prompt do modelo recebe só as melhores `CITABLE_MAX` fontes (o
#: resto fica listado na interface), para a resposta não se perder em contexto.
UNLIMITED = 0
CITABLE_MAX = 60

#: O modelo recebe no máximo este número de caracteres por excerto.
SNIPPET_LIMIT = 320

SYSTEM_PROMPT = (
    "És o motor de resposta do IQ OS para contratação pública. Respondes em português de Portugal, "
    "usando **apenas** as fontes numeradas que recebes. Citas sempre a fonte a seguir à afirmação, "
    "no formato [n], e nunca inventas valores, entidades, datas ou procedimentos que não estejam "
    "nessas fontes. Quando as fontes não chegarem para responder, dizes exatamente o que falta."
)


def vector_coverage(refresh: bool = False) -> Dict[str, Any]:
    """Cobertura de embeddings por âmbito (cache curta: são várias contagens no ES)."""
    global _vector_cache
    now = time.monotonic()
    if not refresh and _vector_cache and (now - _vector_cache[0]) < VECTOR_STATUS_TTL:
        return _vector_cache[1]

    try:
        status = vectors.vector_search_status()
    except Exception as exc:  # noqa: BLE001 - degradar sem derrubar a página
        status = {"error": f"{type(exc).__name__}: {exc}"}

    indices = (status or {}).get("indices") or {}
    scopes: Dict[str, Any] = {}
    for scope_id, index in VECTOR_INDEXES.items():
        info = indices.get(index) or {}
        total = int(info.get("total") or 0)
        with_embedding = int(info.get("with_embedding") or 0)
        scopes[scope_id] = {
            "index": index,
            "total": total,
            "with_embedding": with_embedding,
            "ready": with_embedding > 0,
            "percent": round(100.0 * with_embedding / total, 2) if total else 0.0,
        }
        scopes[scope_id]["usable"] = (
            with_embedding > 0 and with_embedding >= MIN_VECTOR_DOCS and float(scopes[scope_id]["percent"]) >= MIN_VECTOR_PERCENT
        )

    payload = {
        "scopes": scopes,
        "model": vectors.DEFAULT_MODEL_NAME,
        "dims": vectors.EMBEDDING_DIM,
        "error": (status or {}).get("error"),
    }
    _vector_cache = (now, payload)
    return payload


def _vector_is_usable(coverage: Dict[str, Any]) -> bool:
    """Um âmbito só entra em kNN se tiver vectores suficientes para ser fiável."""
    return (
        bool(coverage.get("ready"))
        and int(coverage.get("with_embedding") or 0) >= MIN_VECTOR_DOCS
        and float(coverage.get("percent") or 0.0) >= MIN_VECTOR_PERCENT
    )


def suggest_terms(question: str, *, limit: int = 8, session_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sugestões para a caixa da pergunta (empresas, contratos ES, recolha, mercado).

    Reutiliza o `search_service.suggest` — a mesma fonte de sugestões da barra de
    pesquisa —, para não haver duas ideias diferentes de «o que existe nos dados».
    """
    try:
        result = search_service.suggest(question, limit=limit, session_scope=session_scope)
    except Exception as exc:  # noqa: BLE001 - sugestões não podem bloquear a pergunta
        logger.debug("Sugestões da pesquisa profunda falharam: %s", exc)
        return {"query": (question or "").strip(), "items": []}
    items = [
        {
            "text": str(entry.get("text") or ""),
            "scope": str(entry.get("scope") or ""),
            "kind": str(entry.get("kind") or ""),
            "hint": str(entry.get("hint") or ""),
            "arg": str(entry.get("arg") or ""),
        }
        for entry in (result.get("items") or [])
        if entry.get("text")
    ]
    return {"query": result.get("query") or (question or "").strip(), "items": items[:limit]}


def _party_from_subtitle(subtitle: str) -> str:
    """Nome do adjudicatário a partir do subtítulo de um contrato.

    O subtítulo é construído em camadas (`_subtitle` junta o campo `subtitle`
    com o `extra` por `·`), pelo que o adjudicatário pode aparecer repetido:
    `"Município de X → CLARANET · CLARANET"`. Aqui fica só o primeiro nome.
    """
    text = str(subtitle or "").strip()
    if not text:
        return ""
    tail = text.split("→")[-1].strip() if "→" in text else ""
    if not tail:
        match = re.search(r"adjudicat[áa]ri[oa][:\s]+([^·]+)", text, re.IGNORECASE)
        tail = match.group(1).strip() if match else ""
    if not tail:
        return ""
    name = re.sub(r"\s+", " ", tail.split("·")[0]).strip()  # primeiro campo, sem o resto
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # tira «(Iten Solutions)»
    name = name.split(",")[0].strip()  # «NOME, S.A.» → «NOME»
    return name.strip(" .;:-–—")


def followups(
    question: str,
    sources: Sequence[Dict[str, Any]],
    *,
    limit: int = 4,
) -> List[str]:
    """Perguntas de seguimento a partir das fontes encontradas.

    São determinísticas (não gastam uma chamada ao modelo): aproveitam o que já
    apareceu — entidades, adjudicatários — para sugerir o passo seguinte mais
    óbvio de quem analisa contratação pública.
    """
    entity = next((source for source in sources if source.get("scope") == "entities"), None)
    contract = next((source for source in sources if source.get("scope") == "contracts"), None)

    out: List[str] = []
    if entity:
        name = str(entity.get("title") or "").strip()
        if name:
            name = name if len(name) <= 70 else name[:69].rstrip() + "…"
            out.append(f"Quantos contratos tem {name} e qual o valor total adjudicado?")
            out.append(f"Quais os contratos mais recentes de {name} e a quem foram adjudicados?")
    if contract:
        # O subtítulo tem a forma «adjudicantes → adjudicatários» (e pode trazer
        # mais campos a seguir, juntos por «·»).
        adjudicatario = _party_from_subtitle(str(contract.get("subtitle") or ""))
        if adjudicatario and _fold(adjudicatario) != _fold(str(contract.get("title") or "")):
            out.append(f"Que outros contratos foram adjudicados a {adjudicatario}?")
        out.append("Compara o valor destes contratos com contratos semelhantes no mercado.")

    if not out:
        out = [
            "Que entidades adjudicaram mais contratos com estes termos?",
            "Como evoluiu o valor destes contratos por ano?",
        ]

    unique: List[str] = []
    for suggestion in out:
        if suggestion and suggestion not in unique:
            unique.append(suggestion)
    return unique[:limit]


def source_catalog() -> Dict[str, Any]:
    """Catálogo de âmbitos, modos de recuperação e limites para a interface."""
    return {
        "sources": [
            {
                "id": entry["id"],
                "label": entry["label"],
                "hint": entry["hint"],
                "default": bool(entry.get("default")),
                "kind": "interno" if entry.get("session_scope") else "elastic",
                "vector": entry["id"] in VECTOR_INDEXES,
            }
            for entry in SOURCES
        ],
        "modes": [{"id": mode["id"], "label": mode["label"], "hint": mode["hint"]} for mode in MODES],
        "default_mode": DEFAULT_MODE,
        "examples": list(EXAMPLES),
        "vector": vector_coverage(),
        "defaults": list(DEFAULT_SOURCE_IDS),
        "limits": {
            "per_source": {"default": PER_SOURCE_DEFAULT, "min": PER_SOURCE_MIN, "max": PER_SOURCE_MAX},
            "max_sources": {"default": MAX_SOURCES_DEFAULT, "min": MAX_SOURCES_MIN, "max": MAX_SOURCES_MAX},
            "unlimited": UNLIMITED,
            "citable_max": CITABLE_MAX,
        },
    }


def _clamp(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


#: Palavras que não ajudam a pesquisa por palavras-chave. A pergunta é escrita em
#: linguagem natural mas o BM25 (`match` com OR) casa qualquer termo: sem esta
#: limpeza, «quanto contratos?» enche os resultados de contratos que só partilham
#: essas palavras. Verificado: `"CLARANET II SOLUTIONS quanto contratos?"` não
#: devolvia a entidade; `"CLARANET II SOLUTIONS"` devolve-a em 1.º lugar.
QUESTION_STOPWORDS = frozenset(
    """a ao aos as ate até com como da das de do dos e em entre era eram essa esse esta este eu
    foi foram ha há isso isto ja já mais mas me mesmo meu minha muito na nas no nos o os ou
    para pela pelo por porque porquê qual quais quando quanta quantas quanto quantos que quem
    sao são se sem ser seu sua tem têm ter tinha tu um uma umas uns vai vou
    consegue consegues diz dizer ganha ganham ganhou ganharam haja havia houve existe existem
    pode podem podes recebeu receberam sabe sabes teve tiveram
    and de do em for how in many of on the to what with""".split()
)


#: Palavras que, **neste corpus**, aparecem em quase todos os documentos.
#: O `_text_search` do cliente Elasticsearch exige todos os termos
#: (`operator: and`), por isso mantê-las transforma a pergunta num filtro que
#: exclui os documentos certos. Medido: «Quantos contratos tem a CLARANET II
#: SOLUTIONS e qual o valor total adjudicado?» atirava a entidade CLARANET para
#: 10.º lugar (a 1.ª era uma empresa sueca sem relação nenhuma) e reduzia a
#: recuperação a 2 âmbitos; só «CLARANET II SOLUTIONS» a punha em 1.º lugar e
#: devolvia contratos da própria CLARANET.
CORPUS_GENERIC = frozenset(
    """adjudicacao adjudicação adjudicado adjudicados adjudicante adjudicantes adjudicataria
    adjudicataria adjudicatarias adjudicatario adjudicataria adjudicatario adjudicatarios
    adjudicatária adjudicatárias adjudicatário adjudicatários ano anos contrato contratos
    contratacao contratação contratual dado dados data datas euro euros informacao informação
    lista listar montante mostrar numero número periodo período preco preço precos preços
    quantia soma total totais valor valores""".split()
)


def keywords(question: str) -> str:
    """Termos da pergunta, sem palavras interrogativas nem termos genéricos.

    É esta a consulta do BM25: símbolos (`?`, `»`) e palavras de uma letra caem,
    porque só diluem o `match`.
    """
    uteis: List[str] = []
    genericos: List[str] = []
    for raw in re.split(r"[^0-9A-Za-zÀ-ÿ]+", question or ""):
        term = raw.strip()
        if len(term) < 2:
            continue
        chave = _fold(term)
        if chave in QUESTION_STOPWORDS:
            continue
        destino = genericos if chave in CORPUS_GENERIC else uteis
        if term not in destino:
            destino.append(term)
    # Pergunta só com termos genéricos («quantos contratos?»): mais vale usá-los
    # do que mandar uma consulta vazia para o Elasticsearch.
    return " ".join(uteis or genericos)


def _fold(value: str) -> str:
    """Chave de comparação: minúsculas, sem acentos e sem pontuação."""
    import unicodedata

    text = unicodedata.normalize("NFKD", (value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _snippet(item: Dict[str, Any]) -> str:
    text = str(item.get("snippet") or "").strip()
    if not text:
        extra = item.get("extra") or {}
        if isinstance(extra, dict):
            text = str(extra.get("description") or extra.get("summary") or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > SNIPPET_LIMIT:
        text = text[: SNIPPET_LIMIT - 1].rstrip() + "…"
    return text


def _subtitle(item: Dict[str, Any]) -> str:
    """Linha secundária da fonte (entidade, adjudicatário, jornal…)."""
    parts: List[str] = []
    subtitle = str(item.get("subtitle") or "").strip()
    if subtitle:
        parts.append(subtitle)
    extra = item.get("extra") or {}
    if isinstance(extra, dict):
        for key in ("adjudicante", "adjudicatario", "entidade", "nif", "fonte", "publicacao"):
            value = extra.get(key)
            if value and str(value).strip():
                parts.append(str(value).strip())
    return " · ".join(dict.fromkeys(parts))[:200]


#: Campos do `extra` dos resultados que valem a pena levar ao modelo. Sem isto
#: ele não vê **nenhum** valor de contrato: o preço vive no `extra` (o
#: `_search_contracts_group` põe-no em `preco`) e o `_as_source` deitava-o fora,
#: pelo que a resposta era «as fontes não indicam o valor de nenhum dos
#: contratos» e a comparação de montantes era impossível.
_META_KEYS = (
    "preco",
    "valor",
    "contratos",
    "cpv",
    "adjudicante",
    "adjudicatario",
    "adjudicatario_nif",
    "entidade",
    "nif",
    "sector",
    "pais",
)


def _euros(valor: Any, *, zero: bool = False) -> str:
    """Valor em euros legível («1 234 567 €», «1 234,56 €»).

    `zero=True` para extremos estatísticos (o mínimo de um CPV é muitas vezes
    0 € — há contratos sem preço contratual), onde mostrar «0 €» é informação.
    """
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""
    if numero < 0 or (numero == 0 and not zero):
        return ""
    if abs(numero - round(numero)) < 0.01:
        return f"{round(numero):,}".replace(",", " ") + " €"
    return f"{numero:,.2f}".replace(",", " ").replace(".", ",") + " €"


def _meta(item: Dict[str, Any]) -> Dict[str, Any]:
    """Campos estruturados da fonte (valores, CPV, partes) que o modelo deve ver."""
    extra = item.get("extra") or {}
    if not isinstance(extra, dict):
        return {}
    return {chave: extra[chave] for chave in _META_KEYS if extra.get(chave) not in (None, "", [])}


def _meta_linha(meta: Dict[str, Any]) -> str:
    """Linha «valor · CPV · adjudicatário» para o modelo poder comparar montantes."""
    partes: List[str] = []
    preco = _euros(meta.get("preco"))
    if preco:
        partes.append(f"valor {preco}")
    if meta.get("cpv"):
        partes.append(f"CPV {meta['cpv']}")
    if meta.get("adjudicatario"):
        partes.append(f"adjudicatário {meta['adjudicatario']}")
    if meta.get("adjudicante"):
        partes.append(f"adjudicante {meta['adjudicante']}")
    if meta.get("contratos") is not None:
        partes.append(f"{meta['contratos']} contratos")
    total = _euros(meta.get("valor"))
    if total:
        partes.append(f"total agregado {total}")
    return " · ".join(partes)


def _as_source(n: int, scope_id: str, item: Dict[str, Any], score: float) -> Dict[str, Any]:
    """Normaliza um resultado (BM25 ou kNN) numa fonte citável."""
    return {
        "n": n,
        "id": str(item.get("id") or ""),
        "scope": scope_id,
        "scope_label": (SOURCES_BY_ID.get(scope_id) or {}).get("label") or scope_id,
        "title": str(item.get("title") or "").strip() or "(sem título)",
        "subtitle": _subtitle(item),
        "snippet": _snippet(item),
        # Valores e códigos: a interface mostra-os e o prompt usa-os para
        # comparar montantes (ver `_meta_linha` e `mercado_por_cpv`).
        "meta": _meta(item),
        "url": str(item.get("url") or ""),
        "date": item.get("date"),
        "badges": [str(badge) for badge in (item.get("badges") or []) if badge][:4],
        "image": str(item.get("image") or ""),
        "open": item.get("open") or None,
        "score": round(float(score), 4),
    }


def _vector_item(scope_id: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converte um vizinho semântico no mesmo formato dos resultados da pesquisa.

    Os documentos vêm dos índices com `dense_vector` (`contratos` e
    `finance_entities`) e são normalizados com o `_item` do `search_service`,
    para os cartões da interface ficarem iguais aos das palavras-chave.
    """
    item_fn = getattr(search_service, "_item", None)
    if item_fn is None:  # pragma: no cover - proteção contra renomeações
        return None

    if scope_id == "contracts":
        adjudicantes = search_service._party_names(row.get("adjudicantes"))
        adjudicatarios = search_service._party_names(row.get("adjudicatarios"))
        parsed_adj = row.get("adjudicatarios") if isinstance(row.get("adjudicatarios"), dict) else {}
        primeira = (parsed_adj.get("parsed") or [{}])[0] if parsed_adj else {}
        return item_fn(
            "contracts",
            row.get("idcontrato") or row.get("doc_id") or "",
            row.get("objectoContrato") or row.get("descContrato") or "Contrato",
            subtitle=" → ".join(filter(None, [", ".join(adjudicantes[:2]), ", ".join(adjudicatarios[:2])])),
            snippet=row.get("descContrato") or row.get("objectoContrato") or "",
            date=row.get("dataPublicacao") or row.get("dataCelebracaoContrato"),
            badges=[
                row.get("Ano"),
                search_service._flat(row.get("tipoContrato")),
                search_service._flat(row.get("NUTs")),
            ],
            extra={
                "preco": row.get("precoContratual"),
                "cpv": search_service._cpv_code(row.get("cpv")),
                "adjudicatario": primeira.get("nome") or (adjudicatarios[0] if adjudicatarios else None),
                "adjudicatario_nif": primeira.get("nif"),
            },
            open_view={"view": "contract-detail", "arg": str(row.get("idcontrato") or "")},
            score=row.get("vector_score"),
        )

    if scope_id == "entities":
        nif = row.get("nif")
        return item_fn(
            "entities",
            nif or row.get("name") or row.get("doc_id") or "",
            row.get("name") or "(sem nome)",
            subtitle=row.get("country") or "",
            snippet=f"{row.get('contracts_count') or 0} contratos · {row.get('total_value') or 0:,.0f} €".replace(",", " "),
            badges=[row.get("source"), f"NIF {nif}" if nif else None],
            extra={
                "contratos": row.get("contracts_count"),
                "valor": row.get("total_value"),
                "adjudicante": row.get("as_adjudicante_count"),
                "adjudicatario": row.get("as_adjudicatario_count"),
            },
            open_view={"view": "company-detail", "arg": str(nif)} if nif else None,
            score=row.get("vector_score"),
        )

    return None


def mercado_por_cpv(cpvs: Iterable[Any], *, limite: int = 12) -> List[Dict[str, Any]]:
    """Preços de referência de mercado para os CPV dos contratos encontrados.

    É isto que permite «comparar com contratos semelhantes no mercado»: sem uma
    referência **externa** ao lote encontrado, o modelo só compara os contratos
    entre si — e, se as fontes não trouxerem valores, não compara nada. Uma
    única agregação resolve todos os códigos: `cpv` é `nested` (com `code`
    `keyword`) e o preço é `double` em `precoContratual`. `limite` é o número
    máximo de códigos cobertos (os CPV distintos de uma resposta raramente
    passam de uma dúzia).
    """
    codigos = [codigo for codigo in dict.fromkeys(str(c or "").strip() for c in cpvs) if codigo]
    if not codigos:
        return []
    es = search_service.get_es_client()
    if es is None:
        return []

    corpo = {
        "size": 0,
        "query": {"bool": {"filter": [{"exists": {"field": "precoContratual"}}]}},
        "aggs": {
            "cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codigos": {
                        # `include` já limita aos nossos códigos: o `size` só tem
                        # de ser grande o suficiente para não cortar nenhum.
                        "terms": {
                            "field": "cpv.code",
                            "size": min(len(codigos), max(1, limite)),
                            "include": codigos,
                        },
                        "aggs": {
                            "contratos": {
                                "reverse_nested": {},
                                "aggs": {
                                    "preco": {
                                        "percentiles": {
                                            "field": "precoContratual",
                                            "percents": [25, 50, 75],
                                        }
                                    },
                                    "minimo": {"min": {"field": "precoContratual"}},
                                    "maximo": {"max": {"field": "precoContratual"}},
                                },
                            }
                        },
                    }
                },
            }
        },
    }
    try:
        resposta = es.search(index=vectors.CONTRACTS_INDEX, body=corpo, request_timeout=20)
    except Exception as exc:  # noqa: BLE001 - a referência é um extra, nunca deve derrubar a resposta
        logger.debug("Referência de mercado indisponível: %s", exc)
        return []

    baldes = (((resposta.get("aggregations") or {}).get("cpv") or {}).get("codigos") or {}).get("buckets") or []
    referencias: List[Dict[str, Any]] = []
    for balde in baldes:
        grupo = balde.get("contratos") or {}
        valores = (grupo.get("preco") or {}).get("values") or {}
        mediana = _euros(valores.get("50.0"))
        if not mediana:
            continue
        referencias.append(
            {
                "cpv": balde.get("key"),
                "contratos": grupo.get("doc_count") or 0,
                "minimo": _euros((grupo.get("minimo") or {}).get("value"), zero=True),
                "p25": _euros(valores.get("25.0")),
                "mediana": mediana,
                "p75": _euros(valores.get("75.0")),
                "maximo": _euros((grupo.get("maximo") or {}).get("value"), zero=True),
            }
        )
    return referencias


def _mercado_linha(ref: Dict[str, Any]) -> str:
    """Uma linha de referência: «CPV X: N contratos · mediana … · p25 … · p75 …»."""
    quantos = f"{int(ref.get('contratos') or 0):,}".replace(",", " ")
    return (
        f"- CPV {ref.get('cpv')}: {quantos} contratos adjudicados · "
        f"mediana {ref.get('mediana')} · p25 {ref.get('p25')} · p75 {ref.get('p75')} · "
        f"mínimo {ref.get('minimo')} · máximo {ref.get('maximo')}"
    )


def _mercado_bloco(referencias: Sequence[Dict[str, Any]]) -> str:
    """Secção «Referência de mercado» que entra no prompt antes da pergunta."""
    if not referencias:
        return ""
    linhas = [_mercado_linha(ref) for ref in referencias]
    return (
        "### Referência de mercado (preços adjudicados no mesmo CPV, todos os anos)\n"
        + "\n".join(linhas)
        + "\n\n"
    )


def retrieve(
    question: str,
    *,
    sources: Optional[Sequence[str]] = None,
    per_source: int = PER_SOURCE_DEFAULT,
    max_sources: int = MAX_SOURCES_DEFAULT,
    session_scope: Optional[Dict[str, Any]] = None,
    mode: str = DEFAULT_MODE,
) -> Dict[str, Any]:
    """Recolhe e numera as fontes que sustentam a resposta.

    `mode` escolhe a recuperação: `hybrid` (BM25 em todos os âmbitos + kNN nos que
    têm `embedding`, fundidos por RRF), `text` (só palavras-chave) ou `vector`
    (só semântica, com queda para palavras-chave se não houver vectores).

    Devolve `{"question", "sources", "took_ms", "searched", "mode", "error"}` —
    com `sources` já numerado (`n`) e pronto a citar.
    """
    query = (question or "").strip()
    if not query:
        return {"question": "", "sources": [], "searched": [], "took_ms": 0, "mode": mode, "error": "Pergunta vazia."}

    mode = mode if mode in MODE_IDS else DEFAULT_MODE

    chosen = [scope for scope in (sources or DEFAULT_SOURCE_IDS) if scope in SOURCES_BY_ID]
    if not chosen:
        chosen = list(DEFAULT_SOURCE_IDS)
    if not session_scope:
        chosen = [scope for scope in chosen if not SOURCES_BY_ID[scope].get("session_scope")]
        if not chosen:
            chosen = [scope for scope in DEFAULT_SOURCE_IDS if not SOURCES_BY_ID[scope].get("session_scope")]

    per_source = _clamp(per_source, PER_SOURCE_MIN, PER_SOURCE_MAX, PER_SOURCE_DEFAULT)
    if int(max_sources or 0) <= UNLIMITED:
        # «Sem limite»: fica-se com tudo o que os âmbitos devolverem.
        max_sources = 0
    else:
        max_sources = _clamp(max_sources, MAX_SOURCES_MIN, MAX_SOURCES_MAX, MAX_SOURCES_DEFAULT)

    # Cada lista é um ranking independente (uma por âmbito e por tipo de pesquisa);
    # fundem-se por posição, porque os scores de BM25 e de coseno não são comparáveis.
    ranked: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    inicio = time.perf_counter()
    es_took_ms = 0
    vector_error: Optional[str] = None
    vector_skipped: Dict[str, str] = {}
    text_query = keywords(query) or query

    if mode in ("hybrid", "text"):
        result = search_service.unified_search(text_query, scope="all", size=per_source, session_scope=session_scope)
        if result.get("error"):
            return {
                "question": query,
                "sources": [],
                "searched": chosen,
                "took_ms": 0,
                "mode": mode,
                "error": str(result["error"]),
            }
        es_took_ms = int(result.get("took_ms") or 0)
        groups = {group.get("scope"): group for group in result.get("groups") or []}
        for scope_id in chosen:
            items = [item for item in (groups.get(scope_id) or {}).get("items") or [] if isinstance(item, dict)]
            if items:
                ranked[f"text:{scope_id}"] = [(scope_id, item) for item in items]

    if mode in ("hybrid", "vector"):
        coverage = (vector_coverage().get("scopes") or {})
        pesquisaveis: List[Tuple[str, str]] = []
        for scope_id in chosen:
            index = VECTOR_INDEXES.get(scope_id)
            if not index:
                continue
            info = coverage.get(scope_id) or {}
            if not _vector_is_usable(info):
                vector_skipped[scope_id] = (
                    f"{info.get('with_embedding') or 0} vectores de {info.get('total') or 0} "
                    f"({info.get('percent') or 0}%)"
                )
                continue
            pesquisaveis.append((scope_id, index))

        # As pesquisas vetoriais são independentes entre âmbitos e o embedding da
        # consulta já vem de cache, portanto fazem-se em paralelo (antes era uma
        # a seguir à outra).
        resultados: Dict[str, Dict[str, Any]] = {}
        if pesquisaveis:
            with ThreadPoolExecutor(max_workers=min(4, len(pesquisaveis))) as pool:
                futuros = {
                    pool.submit(vectors.vector_search, index, text_query, per_source): scope_id
                    for scope_id, index in pesquisaveis
                }
                for futuro, scope_id in futuros.items():
                    try:
                        resultados[scope_id] = futuro.result(timeout=60)
                    except Exception as exc:  # noqa: BLE001 - modelo indisponível não pode derrubar a página
                        vector_error = f"{type(exc).__name__}: {exc}"

        for scope_id, _index in pesquisaveis:
            res = resultados.get(scope_id)
            if not res:
                continue
            if res.get("error"):
                vector_error = str(res["error"])
                continue
            mapped = [item for item in (_vector_item(scope_id, row) for row in res.get("items") or []) if item]
            if mapped:
                ranked[f"vec:{scope_id}"] = [(scope_id, item) for item in mapped]

    # Sem vectores utilizáveis, o modo «Semântica» não pode ficar sem resposta.
    if not ranked and mode == "vector":
        result = search_service.unified_search(text_query, scope="all", size=per_source, session_scope=session_scope)
        if result.get("error"):
            return {
                "question": query,
                "sources": [],
                "searched": chosen,
                "took_ms": 0,
                "mode": mode,
                "error": str(result["error"]),
            }
        es_took_ms = int(result.get("took_ms") or 0)
        groups = {group.get("scope"): group for group in result.get("groups") or []}
        for scope_id in chosen:
            items = [item for item in (groups.get(scope_id) or {}).get("items") or [] if isinstance(item, dict)]
            if items:
                ranked[f"text:{scope_id}"] = [(scope_id, item) for item in items]
        mode = "text"

    fused: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for list_key, entries in ranked.items():
        for rank, (scope_id, item) in enumerate(entries):
            identity = (scope_id, str(item.get("id") or ""))
            weight = float(SOURCES_BY_ID.get(scope_id, {}).get("weight") or 0.5)
            entry = fused.get(identity)
            if entry is None:
                entry = {"item": item, "scope": scope_id, "score": 0.0, "lists": []}
                fused[identity] = entry
            entry["score"] += weight * (1.0 / (RRF_K + rank + 1.0))
            entry["lists"].append(list_key)
            # Fica com a versão que traz excerto (a do BM25 costuma ser mais rica).
            if not entry["item"].get("snippet") and item.get("snippet"):
                entry["item"] = item

    ordered = sorted(
        fused.values(),
        key=lambda entry: (-entry["score"], entry["scope"], str(entry["item"].get("title") or "")),
    )

    picked: List[Dict[str, Any]] = []
    seen_ids: set = set()
    seen_titles: set = set()
    for entry in ordered:
        scope_id = entry["scope"]
        item = entry["item"]
        identity = (scope_id, str(item.get("id") or ""))
        title_key = _fold(str(item.get("title") or ""))
        if identity in seen_ids:
            continue
        if title_key and title_key in seen_titles:
            continue
        seen_ids.add(identity)
        if title_key:
            seen_titles.add(title_key)
        picked.append(_as_source(len(picked) + 1, scope_id, item, entry["score"]))
        if max_sources and len(picked) >= max_sources:
            break

    return {
        "question": query,
        "text_query": text_query,
        "sources": picked,
        "searched": chosen,
        # Tempo **total** da recuperação (é o que a página mostra como «a
        # procurar»). `es_took_ms` é o que o Elasticsearch reporta para a
        # pesquisa textual — antes, no modo «Semântica», este campo vinha 0.
        "took_ms": max(es_took_ms, int((time.perf_counter() - inicio) * 1000)),
        "es_took_ms": es_took_ms,
        "mode": mode,
        "citable_max": CITABLE_MAX,
        "unlimited": max_sources == 0,
        "suggestions": followups(query, picked),
        "text_lists": len([key for key in ranked if key.startswith("text:")]),
        "vector_lists": len([key for key in ranked if key.startswith("vec:")]),
        "vector_skipped": vector_skipped,
        "vector_error": vector_error,
        "error": None,
    }


# ----------------------------------------------------------------------------- resposta

def resolve_backend(backend: str, user_id: Optional[str]) -> Dict[str, Any]:
    """Resolve o backend do pedido, caindo nas predefinições do utilizador."""
    chosen = (backend or "").strip()
    if not chosen and user_id:
        defaults = (providers.load_user_config(user_id).get("defaults") or {})
        provider = defaults.get("provider")
        if provider:
            model = defaults.get("model") or ""
            chosen = f"{provider}:{model}" if model else provider
    if not chosen:
        chosen = "gpt2"
    parsed = providers.parse_backend(chosen)
    label = chosen
    if parsed.get("kind") == "cloud":
        model = parsed.get("model") or parsed.get("spec", {}).get("default_model") or ""
        label = f"{parsed.get('provider')}:{model}".rstrip(":")
    return {**parsed, "backend": chosen, "label": label}


def build_messages(
    question: str,
    sources: Sequence[Dict[str, Any]],
    history: Optional[Sequence[Dict[str, str]]] = None,
    mercado: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Mensagens para o modelo: fontes numeradas + pergunta + histórico curto.

    Cada fonte leva o seu **valor** (€) e **CPV** na linha de detalhe — sem isso
    o modelo não tinha por onde comparar montantes e respondia que as fontes não
    indicavam valores. `mercado` acrescenta a referência de preços do CPV.
    """
    blocks: List[str] = []
    for source in sources:
        head = f"[{source.get('n')}] {source.get('scope_label')} · {source.get('title')}"
        detalhe = [part for part in (source.get("subtitle"), source.get("date"), source.get("url")) if part]
        if detalhe:
            head += "\n    " + " | ".join(str(part) for part in detalhe)
        linha = _meta_linha(source.get("meta") or {})
        if linha:
            head += "\n    " + linha
        body = source.get("snippet") or ""
        blocks.append(f"{head}\n    {body}" if body else head)

    context = "\n\n".join(blocks) if blocks else "(sem fontes)"
    prompt = (
        f"### Fontes\n{context}\n\n"
        + _mercado_bloco(list(mercado or ()))
        + f"### Pergunta\n{question}\n\n"
        "### Regras de resposta\n"
        "- Responde em português de Portugal, de forma direta e factual.\n"
        "- Sustenta cada afirmação com a fonte numerada correspondente, no formato [1], [2]…\n"
        "- Usa apenas o que está nas fontes; se algo não estiver lá, di-lo em vez de supor.\n"
        "- Quando as fontes trouxerem «valor», compara montantes em euros e diz qual é maior ou menor.\n"
        "- Quando houver «Referência de mercado», compara os valores das fontes com a mediana/p75 desse CPV "
        "e conclui se estão acima ou abaixo do habitual para aquele tipo de contrato.\n"
        "- Podes usar uma tabela ou bullets quando ajudar a comparar contratos, entidades ou valores.\n"
        "- Termina com uma secção curta «**Notas**» quando houver limitações dos dados (ex.: anos em falta).\n"
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-4:]:
        role = "assistant" if str(turn.get("role")) == "assistant" else "user"
        content = str(turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt})
    return messages


def _no_sources_answer(question: str) -> str:
    return (
        "Não encontrei nada nos dados indexados que responda a esta pergunta.\n\n"
        "Sugestões: reformule com o nome da entidade, o NIF ou o número do contrato; "
        "ligue mais âmbitos de pesquisa (por exemplo **Imprensa** ou **Contratos ES**); "
        "ou confirme que os dados do tema já foram recolhidos."
    )


def _prompt_para_modelo_local(prompt: str, limite: int = 3000) -> str:
    """Prompt que caiba na janela de um modelo local (o gpt2 tem 1024 tokens).

    As fontes vêm primeiro e a pergunta/regras no fim: corta-se o **meio**, para
    preservar os primeiros excertos (os mais relevantes) e, claro, a pergunta e
    as regras. Sem isto, o prompt ultrapassa a janela e a geração rebenta.
    """
    if len(prompt) <= limite:
        return prompt
    marcador = "\n\n### Pergunta"
    if marcador in prompt:
        cauda = prompt[prompt.index(marcador) :]
        cabeca = prompt[: max(1, limite - len(cauda))]
        return cabeca + cauda
    return prompt[-limite:]


async def _stream_model(
    messages: List[Dict[str, str]],
    *,
    backend: Dict[str, Any],
    user_id: Optional[str],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    """Fragmentos de resposta do backend escolhido (cloud ou modelo local)."""
    if backend.get("kind") == "cloud":
        from api import cloud_chat

        provider = str(backend.get("provider") or "")
        spec = backend.get("spec") or {}
        model = backend.get("model") or providers.resolve_provider_model(user_id, provider) or spec.get("default_model") or ""
        api_key, _ = providers.resolve_key(user_id, provider)
        if not api_key and not spec.get("key_optional"):
            raise RuntimeError(
                f"O fornecedor {spec.get('label') or provider} ainda não tem chave de API. "
                "Configura-a em Definições → Fornecedores de IA."
            )
        async for chunk in cloud_chat.stream_answer(
            provider=provider,
            spec=spec,
            model=model,
            messages=messages,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk
        return

    # Modelos locais do IQ OS: geram num thread e devolvem a resposta em pedaços.
    from api.agent import get_inference_model

    model_name = str(backend.get("backend") or "gpt2")
    prompt = "\n\n".join(message.get("content", "") for message in messages)
    # Uma janela pequena (o gpt2 tem 1024 tokens) não aguenta 60 fontes nem 1400
    # tokens de resposta: corta-se o prompt e limita-se o que se pede ao modelo.
    prompt = _prompt_para_modelo_local(prompt)
    max_tokens = min(max_tokens, 400)

    def _generate() -> str:
        generator = get_inference_model(model_name)
        return generator.generate(prompt, max_new_tokens=max_tokens, temperature=temperature)

    text = await asyncio.to_thread(_generate)
    if not (text or "").strip():
        # Um modelo local que devolve vazio (pesos em falta, contexto demasiado
        # longo) ficava a pagina com uma resposta em branco e sem explicacao.
        raise RuntimeError(
            f"O modelo local «{model_name}» não devolveu texto. "
            "Escolhe outro modelo ou configura um fornecedor com chave em Definições → Fornecedores de IA."
        )
    # O gerador devolve o prompt **mais** a continuação; sem isto a resposta
    # começava por repetir a lista de fontes.
    if text.startswith(prompt):
        text = text[len(prompt) :]
    if not text.strip():
        raise RuntimeError(
            f"O modelo local «{model_name}» não acrescentou nada à pergunta. "
            "Escolhe outro modelo ou configura um fornecedor com chave em Definições → Fornecedores de IA."
        )
    for token in re.split(r"(\s+)", text):
        if token:
            yield token


def sse(event: str, payload: Dict[str, Any]) -> str:
    """Linha SSE no formato do chat (`event:` + `data:`)."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_answer(
    question: str,
    *,
    backend: str = "",
    user_id: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
    per_source: int = PER_SOURCE_DEFAULT,
    max_sources: int = MAX_SOURCES_DEFAULT,
    temperature: float = 0.2,
    max_tokens: int = 1400,
    history: Optional[Sequence[Dict[str, str]]] = None,
    session_scope: Optional[Dict[str, Any]] = None,
    mode: str = DEFAULT_MODE,
) -> AsyncIterator[str]:
    """Fluxo SSE: fontes (cedo) → tokens → fim.

    As fontes vão à frente da resposta para a interface as poder mostrar
    enquanto o modelo ainda está a escrever.
    """
    yield ":keep-alive\n\n"

    resolved = resolve_backend(backend, user_id)
    try:
        collected = await asyncio.to_thread(
            retrieve,
            question,
            sources=sources,
            per_source=per_source,
            max_sources=max_sources,
            session_scope=session_scope,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 - a interface mostra o motivo
        logger.exception("Pesquisa profunda: falha a recuperar fontes")
        yield sse("error", {"message": f"Falha a pesquisar nos dados: {type(exc).__name__}: {exc}"})
        return

    if collected.get("error"):
        yield sse("error", {"message": str(collected["error"])})
        return

    found = collected["sources"]
    yield sse(
        "sources",
        {
            "question": collected["question"],
            "sources": found,
            "searched": collected["searched"],
            "took_ms": collected["took_ms"],
            "es_took_ms": collected.get("es_took_ms"),
            "model": resolved["label"],
            "mode": collected.get("mode") or DEFAULT_MODE,
            "text_lists": collected.get("text_lists"),
            "vector_lists": collected.get("vector_lists"),
            "vector_error": collected.get("vector_error"),
            "citable_max": collected.get("citable_max"),
            "unlimited": collected.get("unlimited"),
            "suggestions": collected.get("suggestions") or [],
        },
    )
    yield sse("meta", {"model": resolved["label"], "backend": resolved["backend"], "kind": resolved.get("kind")})

    if not found:
        text = _no_sources_answer(question)
        for token in re.split(r"(\s+)", text):
            if token:
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
        yield sse("done", {"sources": [], "tools": [], "answer": text, "citations": [], "suggestions": list(EXAMPLES)})
        return

    # Referência de mercado dos CPV encontrados: é o que permite comparar os
    # valores das fontes com contratos semelhantes (e não apenas entre si).
    cpvs = [(src.get("meta") or {}).get("cpv") for src in found[:CITABLE_MAX]]
    mercado: List[Dict[str, Any]] = []
    if any(cpvs):
        try:
            mercado = await asyncio.to_thread(mercado_por_cpv, cpvs)
        except Exception as exc:  # noqa: BLE001 - a resposta não depende disto
            logger.debug("Pesquisa profunda: referência de mercado falhou: %s", exc)

    messages = build_messages(question, found[:CITABLE_MAX], history, mercado=mercado)
    written: List[str] = []
    try:
        async for chunk in _stream_model(
            messages,
            backend=resolved,
            user_id=user_id,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            written.append(chunk)
            yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 - erro do fornecedor/modelo
        logger.warning("Pesquisa profunda: falha do modelo %s: %s", resolved["label"], exc)
        message = f"⚠️ {exc}"
        written.append(message)
        yield f"data: {json.dumps({'token': message}, ensure_ascii=False)}\n\n"

    if not "".join(written).strip():
        # Rede de seguranca: mesmo com um fornecedor externo que devolva um
        # fluxo vazio, o utilizador tem de perceber porque e que nao ha resposta.
        logger.warning("Pesquisa profunda: %s nao devolveu texto", resolved["label"])
        message = (
            f"⚠️ O modelo «{resolved['label']}» não devolveu texto. "
            "Escolhe outro modelo ou configura a chave em Definições → Fornecedores de IA."
        )
        written.append(message)
        yield f"data: {json.dumps({'token': message}, ensure_ascii=False)}\n\n"

    answer = "".join(written)
    yield sse(
        "done",
        {
            "sources": found,
            "tools": [],
            "answer": answer,
            "citations": _cited_numbers(answer, len(found)),
            "suggestions": collected.get("suggestions") or [],
            "mercado": mercado,
        },
    )


def _cited_numbers(answer: str, total: int) -> List[int]:
    """Números de fonte efetivamente citados na resposta (`[1]`, `[2,4]`…)."""
    numbers: List[int] = []
    for match in re.finditer(r"\[([0-9,\s]+)\]", answer or ""):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                value = int(part)
                if 1 <= value <= total and value not in numbers:
                    numbers.append(value)
    return sorted(numbers)


def cited_sources(answer: str, sources: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fontes que a resposta citou (pela ordem do texto); todas, se não citou nenhuma."""
    cited = set(_cited_numbers(answer, len(sources)))
    if not cited:
        return list(sources)
    return [source for source in sources if int(source.get("n") or 0) in cited]


def referenced_ids(answer: str, sources: Iterable[Dict[str, Any]]) -> List[str]:
    """Identificadores das fontes citadas (útil para registo/analítica)."""
    return [str(source.get("id") or "") for source in cited_sources(answer, list(sources))]
