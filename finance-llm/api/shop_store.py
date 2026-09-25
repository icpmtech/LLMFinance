"""Loja online IQ OS — catálogo, encomendas, clientes, promoções e envios.

A loja é o **balcão** da plataforma: vende **produtos** (físicos, digitais ou
serviços) organizados por **categorias**, recebe **encomendas** (com carrinho e
finalização na vitrine pública `/loja`), guarda os **clientes**, aplica
**promoções** (cupões), calcula **portes** e recolhe **avaliações**.

Tudo vive num único documento JSON (`data/shop/shop.json`) com escrita atómica —
o ficheiro é a fonte de verdade e pode ser versionado, exatamente como o CMS.

Estados de publicação dos produtos (`status`): `rascunho`, `agendado`,
`publicado`, `arquivado`. Os agendamentos publicam-se sozinhos: `_apply_schedule`
corre a cada leitura, pelo que não é preciso um processo à parte.

Ciclo de vida de uma encomenda (`status`):

    pendente → pago → em_preparacao → enviado → entregue
    (a qualquer momento) cancelado | reembolsado

O **pagamento** é registado à mão (MB Way, transferência, numerário, …): a loja
não tem gateway externo. `register_payment` soma o valor recebido, marca a
encomenda como paga quando o total está coberto e deixa tudo no histórico.

O stock é descontado na criação da encomenda (`stock_reserved`) e devolvido
quando a encomenda é cancelada ou reembolsada.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SHOP_DIR = ROOT / "data" / "shop"
SHOP_PATH = SHOP_DIR / "shop.json"
SHOP_VERSION = 1

# Entidades da loja: as listas dentro do documento.
ENTITIES: Tuple[str, ...] = ("products", "categories", "customers", "orders", "coupons", "shipping", "reviews")
SINGULAR: Dict[str, str] = {
    "products": "produto",
    "categories": "categoria",
    "customers": "cliente",
    "orders": "encomenda",
    "coupons": "cupão",
    "shipping": "método de envio",
    "reviews": "avaliação",
}
ID_PREFIX: Dict[str, str] = {
    "products": "prd",
    "categories": "cat",
    "customers": "cli",
    "orders": "enc",
    "coupons": "cup",
    "shipping": "env",
    "reviews": "avl",
}

# --------------------------------------------------------------------------
# Catálogos
# --------------------------------------------------------------------------
PRODUCT_STATUSES: Tuple[str, ...] = ("rascunho", "agendado", "publicado", "arquivado")
STATUS_LABELS: Dict[str, str] = {
    "rascunho": "Rascunho",
    "agendado": "Agendado",
    "publicado": "Publicado",
    "arquivado": "Arquivado",
}
STATUS_STYLE: Dict[str, str] = {
    "rascunho": "slate",
    "agendado": "amber",
    "publicado": "emerald",
    "arquivado": "zinc",
}

PRODUCT_TYPES: List[Dict[str, str]] = [
    {"id": "fisico", "label": "Produto físico", "hint": "Tem stock, peso e envio"},
    {"id": "digital", "label": "Produto digital", "hint": "Download ou acesso — sem portes"},
    {"id": "servico", "label": "Serviço", "hint": "Prestação, formação ou subscrição"},
]

ORDER_STATUSES: Tuple[str, ...] = ("pendente", "pago", "em_preparacao", "enviado", "entregue", "cancelado", "reembolsado")
ORDER_LABELS: Dict[str, str] = {
    "pendente": "Pendente",
    "pago": "Pago",
    "em_preparacao": "Em preparação",
    "enviado": "Enviado",
    "entregue": "Entregue",
    "cancelado": "Cancelado",
    "reembolsado": "Reembolsado",
}
ORDER_STYLE: Dict[str, str] = {
    "pendente": "amber",
    "pago": "sky",
    "em_preparacao": "violet",
    "enviado": "indigo",
    "entregue": "emerald",
    "cancelado": "rose",
    "reembolsado": "zinc",
}
# Estados seguintes sugeridos em cada passo (o gestor pode saltar passos).
ORDER_FLOW: Dict[str, List[str]] = {
    "pendente": ["pago", "cancelado"],
    "pago": ["em_preparacao", "cancelado", "reembolsado"],
    "em_preparacao": ["enviado", "cancelado", "reembolsado"],
    "enviado": ["entregue", "reembolsado"],
    "entregue": ["reembolsado"],
    "cancelado": [],
    "reembolsado": [],
}
# Estados em que a encomenda deixa de contar para as vendas.
ORDER_CLOSED_LOST: Tuple[str, ...] = ("cancelado", "reembolsado")

PAYMENT_STATUSES: Tuple[str, ...] = ("pendente", "parcial", "pago", "reembolsado")
PAYMENT_LABELS: Dict[str, str] = {
    "pendente": "Pendente",
    "parcial": "Parcial",
    "pago": "Pago",
    "reembolsado": "Reembolsado",
}
PAYMENT_STYLE: Dict[str, str] = {
    "pendente": "amber",
    "parcial": "sky",
    "pago": "emerald",
    "reembolsado": "zinc",
}

PAYMENT_METHODS: List[Dict[str, str]] = [
    {"id": "mbway", "label": "MB Way", "hint": "Transferência imediata por telemóvel"},
    {"id": "multibanco", "label": "Referência Multibanco", "hint": "Pagamento por referência"},
    {"id": "transferencia", "label": "Transferência bancária", "hint": "IBAN enviado com a encomenda"},
    {"id": "numerario", "label": "Numerário", "hint": "Pagamento na entrega ou ao balcão"},
    {"id": "cartao", "label": "Cartão (terminal)", "hint": "Registado à mão após pagamento"},
    {"id": "outro", "label": "Outro", "hint": "Pagamento combinado com o cliente"},
]

COUPON_TYPES: List[Dict[str, str]] = [
    {"id": "percentagem", "label": "% de desconto", "hint": "Percentagem sobre o subtotal"},
    {"id": "valor", "label": "Valor fixo (€)", "hint": "Valor descontado no subtotal"},
    {"id": "portes_gratis", "label": "Portes grátis", "hint": "Anula o custo de envio"},
]

CUSTOMER_STATUSES: Tuple[str, ...] = ("ativo", "bloqueado")
CUSTOMER_LABELS: Dict[str, str] = {"ativo": "Ativo", "bloqueado": "Bloqueado"}

REVIEW_STATUSES: Tuple[str, ...] = ("pendente", "aprovada", "rejeitada")
REVIEW_LABELS: Dict[str, str] = {"pendente": "Pendente", "aprovada": "Aprovada", "rejeitada": "Rejeitada"}
REVIEW_STYLE: Dict[str, str] = {"pendente": "amber", "aprovada": "emerald", "rejeitada": "rose"}

PRODUCT_UNITS: List[str] = ["un", "h", "dia", "mês", "kg", "licença", "subscrição"]
SORT_OPTIONS: List[Dict[str, str]] = [
    {"id": "destaque", "label": "Destaques primeiro"},
    {"id": "novidade", "label": "Mais recentes"},
    {"id": "preco", "label": "Preço (menor primeiro)"},
    {"id": "preco-desc", "label": "Preço (maior primeiro)"},
    {"id": "nome", "label": "Nome (A→Z)"},
]

MAX_REVISIONS = 30
MAX_ACTIVITY = 400
MAX_ORDER_ITEMS = 60
PER_PAGE = 12

DEFAULT_SETTINGS: Dict[str, Any] = {
    "store_name": "Loja IQ OS",
    "tagline": "Produtos e serviços de inteligência financeira",
    "description": "Loja da plataforma: relatórios, dossiês, dados e formação para decisões informadas.",
    "base_url": "",
    "language": "pt-PT",
    "currency": "EUR",
    "prices_include_tax": True,
    "default_tax_rate": 23.0,
    "email": "",
    "phone": "",
    "address": "",
    "tax_id": "",
    "min_order": 0,
    "low_stock_threshold": 5,
    "order_prefix": "EN",
    "payments": {"mbway": True, "multibanco": True, "transferencia": True, "numerario": False, "cartao": False, "outro": True},
    "payment_instructions": {
        "mbway": "Envie o valor por MB Way para o número indicado, usando o número da encomenda como referência.",
        "multibanco": "Será enviada a referência Multibanco por email depois de confirmarmos a encomenda.",
        "transferencia": "Transferência bancária para o IBAN indicado, com o número da encomenda no descritivo.",
        "numerario": "Pagamento em numerário na entrega ou ao balcão.",
        "cartao": "Pagamento por cartão no terminal, no ato da entrega.",
        "outro": "Combinamos consigo o melhor modo de pagamento — responda ao email de confirmação.",
    },
    "terms_url": "",
    "footer_text": "© Loja IQ OS — todos os direitos reservados.",
    "theme": "claro",
    "accent": "#0ea5a4",
    "radius": 14,
    "show_stock": True,
    "allow_reviews": True,
    "seo": {"title": "", "description": "", "keywords": []},
    "robots": "index, follow",
    "analytics_id": "",
    "social": {"email": "", "linkedin": "", "x": "", "github": ""},
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slug(value: str, fallback: str = "artigo") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-+", "-", text)
    return text[:72] or fallback


def _keywords(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n;]", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def money(value: Any) -> float:
    """Arredonda um valor monetário a cêntimos."""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(minimum, number) if minimum is not None else number


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(value)


def _excerpt(text: str, limit: int = 190) -> str:
    plain = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[#*`>_|]", " ", plain)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit]


def line_amounts(price: Any, quantity: Any, tax_rate: Any, discount: Any = 0, *, prices_include_tax: bool = True) -> Dict[str, float]:
    """Valores de uma linha da encomenda (bruto, líquido e IVA).

    Com `prices_include_tax` (o habitual no retalho português) o preço é o preço
    final de venda: o IVA sai de dentro dele. Sem essa opção, o IVA acresce.
    """
    amount = money(money(price) * max(0, _int(quantity)) - money(discount))
    if amount < 0:
        amount = 0.0
    rate = max(0.0, money(tax_rate))
    if prices_include_tax:
        net = amount / (1 + rate / 100) if rate else amount
    else:
        net = amount
    return {"gross": money(amount), "net": money(net), "tax": money(amount - net)}


def _date(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone().strftime("%d/%m/%Y")


def order_totals(doc: Dict[str, Any]) -> Dict[str, float]:
    """Totais de uma encomenda (API pública para as rotas e a vitrine)."""
    return _order_totals(doc)


def tags_index() -> Dict[str, Any]:
    """Etiquetas em uso nos produtos publicados, com contagem."""
    data = _load()
    counts: Dict[str, int] = {}
    for product in data["products"]:
        if product.get("status") != "publicado":
            continue
        for tag in product.get("tags") or []:
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    return {"tags": [{"tag": tag, "products": count} for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]}


# --------------------------------------------------------------------------
# Alias públicos dos utilitários internos (a vitrine e as rotas usam-nos).
# --------------------------------------------------------------------------
to_int = _int
to_bool = _bool
text_excerpt = _excerpt


# --------------------------------------------------------------------------
# Persistência
# --------------------------------------------------------------------------
def _empty_settings() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_SETTINGS)


def _empty_store() -> Dict[str, Any]:
    store: Dict[str, Any] = {"version": SHOP_VERSION}
    for entity in ENTITIES:
        store[entity] = []
    store["revisions"] = []
    store["activity"] = []
    store["settings"] = _empty_settings()
    store["updated_at"] = _now()
    return store


def _read_store() -> Dict[str, Any]:
    if not SHOP_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(SHOP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro da loja ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for entity in ENTITIES + ("revisions", "activity"):
        value = raw.get(entity)
        if isinstance(value, list):
            store[entity] = [item for item in value if isinstance(item, dict)]
    settings = raw.get("settings")
    if isinstance(settings, dict):
        store["settings"].update({key: value for key, value in settings.items() if value is not None})
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_mtime
    store["version"] = SHOP_VERSION
    store["updated_at"] = _now()
    SHOP_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp = SHOP_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    # No Windows, o antivírus ou o indexador podem segurar o ficheiro por uns
    # milissegundos logo após a criação: tenta-se algumas vezes antes de desistir.
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(SHOP_PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover - depende do sistema
        raise last if last else OSError(f"Não foi possível gravar {SHOP_PATH}.")
    _cache = store
    _cache_mtime = _file_mtime()


def _file_mtime() -> Optional[int]:
    try:
        return SHOP_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _load() -> Dict[str, Any]:
    """Documento da loja, com publicação automática dos agendamentos vencidos.

    Se o ficheiro mudou fora deste processo (CLI, testes, edição manual), a cópia
    em memória é descartada — sem isto a escrita seguinte repunha dados velhos.
    """
    global _cache, _cache_mtime
    stamp = _file_mtime()
    if _cache is not None and stamp != _cache_mtime:
        _cache = None
    if _cache is None:
        _cache = _read_store()
        if not _cache["products"] and not _cache["categories"] and not _cache["orders"]:
            _seed(_cache)
            _write_store(_cache)
        else:
            _cache_mtime = _file_mtime()
    if _apply_schedule(_cache):
        _write_store(_cache)
    return _cache


# --------------------------------------------------------------------------
# Revisões e atividade
# --------------------------------------------------------------------------
def _snapshot(store: Dict[str, Any], entity: str, doc: Dict[str, Any], author: str = "", note: str = "") -> None:
    revision = {
        "id": _new_id("rev"),
        "entity": entity,
        "entity_id": doc.get("id") or "",
        "title": doc.get("name") or doc.get("number") or doc.get("code") or "",
        "snapshot": copy.deepcopy(doc),
        "author": author or doc.get("updated_by") or "",
        "note": note,
        "at": _now(),
    }
    revisions = store["revisions"]
    revisions.insert(0, revision)
    same = [item for item in revisions if item.get("entity") == entity and item.get("entity_id") == revision["entity_id"]]
    for extra in same[MAX_REVISIONS:]:
        revisions.remove(extra)


def _log(store: Dict[str, Any], action: str, entity: str, doc: Dict[str, Any], actor: str = "", detail: str = "") -> None:
    store["activity"].insert(
        0,
        {
            "id": _new_id("act"),
            "at": _now(),
            "action": action,
            "entity": entity,
            "entity_id": doc.get("id") or "",
            "label": doc.get("name") or doc.get("number") or doc.get("code") or doc.get("title") or "",
            "actor": actor or "plataforma",
            "detail": detail,
        },
    )
    del store["activity"][MAX_ACTIVITY:]


def activity(limit: int = 40) -> List[Dict[str, Any]]:
    return _load()["activity"][: max(1, min(limit, MAX_ACTIVITY))]


def revisions_of(entity: str, entity_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    _check_entity(entity)
    store = _load()
    items = [rev for rev in store["revisions"] if rev.get("entity") == entity and rev.get("entity_id") == entity_id]
    return [
        {key: value for key, value in item.items() if key != "snapshot"} | {"fields": sorted((item.get("snapshot") or {}).keys())}
        for item in items[:limit]
    ]


def get_revision(revision_id: str) -> Dict[str, Any]:
    store = _load()
    for revision in store["revisions"]:
        if revision.get("id") == revision_id:
            return revision
    raise KeyError(f"Revisão {revision_id} não encontrada.")


def restore_revision(revision_id: str, author: str = "") -> Dict[str, Any]:
    store = _load()
    revision = get_revision(revision_id)
    entity = revision["entity"]
    entity_id = revision["entity_id"]
    current = _find(store, entity, entity_id)
    if current is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {entity_id} já não existe.")
    _snapshot(store, entity, current, author, note=f"antes de restaurar {revision_id}")
    restored = copy.deepcopy(revision["snapshot"])
    restored["id"] = entity_id
    restored["updated_at"] = _now()
    restored["updated_by"] = author
    store[entity][store[entity].index(current)] = restored
    _after_write(store, entity, restored)
    _log(store, "restaurar", entity, restored, author, f"revisão {revision_id}")
    _write_store(store)
    return restored


# --------------------------------------------------------------------------
# Índices e normalização
# --------------------------------------------------------------------------
def _check_entity(entity: str) -> None:
    if entity not in ENTITIES:
        raise KeyError(f"Entidade desconhecida: {entity}. Válidas: {', '.join(ENTITIES)}.")


def _find(store: Dict[str, Any], entity: str, item_id: str) -> Optional[Dict[str, Any]]:
    _check_entity(entity)
    for item in store[entity]:
        if item.get("id") == item_id:
            return item
    return None


def _unique(store: Dict[str, Any], entity: str, slug: str, ignore_id: Optional[str] = None) -> str:
    taken = {item.get("slug") for item in store[entity] if item.get("id") != ignore_id}
    candidate = slug
    index = 2
    while candidate in taken:
        candidate = f"{slug}-{index}"
        index += 1
    return candidate


def _status(value: Any, fallback: str = "rascunho") -> str:
    status = str(value or fallback).strip().lower()
    return status if status in PRODUCT_STATUSES else fallback


def _after_write(store: Dict[str, Any], entity: str, doc: Dict[str, Any]) -> None:
    if entity in ("reviews", "products"):
        _refresh_ratings(store)
    if entity in ("orders", "customers"):
        _refresh_customer_stats(store)


def _refresh_ratings(store: Dict[str, Any]) -> None:
    """Nota média e número de avaliações aprovadas, por produto."""
    totals: Dict[str, List[int]] = {}
    for review in store["reviews"]:
        if review.get("status") != "aprovada":
            continue
        product_id = str(review.get("product_id") or "")
        if not product_id:
            continue
        bucket = totals.setdefault(product_id, [])
        bucket.append(_int(review.get("rating"), 0))
    for product in store["products"]:
        ratings = totals.get(str(product.get("id")), [])
        product["rating_count"] = len(ratings)
        product["rating_avg"] = money(sum(ratings) / len(ratings)) if ratings else 0
    for review in store["reviews"]:
        review["rating"] = max(1, min(5, _int(review.get("rating"), 5, minimum=1)))


def _refresh_customer_stats(store: Dict[str, Any]) -> None:
    stats: Dict[str, Dict[str, Any]] = {}
    for order in store["orders"]:
        customer_id = str(order.get("customer_id") or "")
        if not customer_id:
            continue
        bucket = stats.setdefault(customer_id, {"orders_count": 0, "total_spent": 0.0, "last_order_at": ""})
        bucket["orders_count"] += 1
        if order.get("status") not in ORDER_CLOSED_LOST:
            bucket["total_spent"] = money(bucket["total_spent"] + money(order.get("total")))
        stamp = str(order.get("placed_at") or order.get("created_at") or "")
        if stamp > str(bucket["last_order_at"] or ""):
            bucket["last_order_at"] = stamp
    for customer in store["customers"]:
        bucket = stats.get(str(customer.get("id")), {})
        customer["orders_count"] = _int(bucket.get("orders_count"), 0)
        customer["total_spent"] = money(bucket.get("total_spent"))
        customer["last_order_at"] = bucket.get("last_order_at") or ""


def _normalise(entity: str, payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None, store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Campos conhecidos de cada entidade (o resto é ignorado).

    `store` é opcional e serve apenas para resolver referências (o cupão de uma
    encomenda passa a ser uma cópia, para o desconto não mudar depois).
    """
    existing = existing or {}
    doc: Dict[str, Any] = copy.deepcopy(existing)

    def pick(field: str, default: Any = None) -> Any:
        return payload[field] if field in payload else existing.get(field, default)

    if entity == "products":
        doc["name"] = str(pick("name") or "").strip()
        doc["slug"] = _slug(str(pick("slug") or doc["name"]), "produto")
        doc["sku"] = str(pick("sku") or "").strip().upper()
        kind = str(pick("type") or "fisico").strip().lower()
        doc["type"] = kind if kind in {item["id"] for item in PRODUCT_TYPES} else "fisico"
        doc["status"] = _status(pick("status"))
        doc["scheduled_at"] = pick("scheduled_at") or None
        doc["featured"] = _bool(pick("featured"), False)
        doc["order"] = _int(pick("order"), 0)
        doc["short_description"] = str(pick("short_description") or "")
        doc["description"] = str(pick("description") or "")
        doc["price"] = money(pick("price"))
        doc["compare_at_price"] = money(pick("compare_at_price"))
        if doc["compare_at_price"] and doc["compare_at_price"] <= doc["price"]:
            doc["compare_at_price"] = 0.0
        doc["cost"] = money(pick("cost"))
        doc["tax_rate"] = money(pick("tax_rate", 23.0))
        doc["stock"] = _int(pick("stock"), 0)
        doc["stock_min"] = _int(pick("stock_min"), 0)
        doc["track_stock"] = _bool(pick("track_stock", doc["type"] == "fisico"), doc["type"] == "fisico")
        doc["allow_backorder"] = _bool(pick("allow_backorder"), False)
        doc["unit"] = str(pick("unit") or "un")
        doc["category_ids"] = [str(item) for item in (pick("category_ids", []) or []) if item]
        doc["tags"] = _keywords(pick("tags", []))
        doc["image_ids"] = [str(item) for item in (pick("image_ids", []) or []) if item]
        doc["image_urls"] = [str(item).strip() for item in (pick("image_urls", []) or []) if str(item).strip()]
        attributes = pick("attributes", []) or []
        doc["attributes"] = [
            {"label": str(item.get("label") or "").strip(), "value": str(item.get("value") or "").strip()}
            for item in attributes
            if isinstance(item, dict) and (str(item.get("label") or "").strip() or str(item.get("value") or "").strip())
        ]
        doc["weight_kg"] = money(pick("weight_kg"))
        doc["length_cm"] = money(pick("length_cm"))
        doc["width_cm"] = money(pick("width_cm"))
        doc["height_cm"] = money(pick("height_cm"))
        doc["internal_notes"] = str(pick("internal_notes") or "")
        doc["seo"] = _normalise_seo(pick("seo"))

    if entity == "categories":
        doc["name"] = str(pick("name") or "").strip()
        doc["slug"] = _slug(str(pick("slug") or doc["name"]), "categoria")
        doc["description"] = str(pick("description") or "")
        doc["parent_id"] = pick("parent_id") or None
        doc["status"] = _status(pick("status"), "publicado")
        doc["featured"] = _bool(pick("featured"), False)
        doc["order"] = _int(pick("order"), 0)
        doc["image_id"] = pick("image_id") or None
        doc["image_url"] = str(pick("image_url") or "")
        doc["seo"] = _normalise_seo(pick("seo"))

    if entity == "customers":
        email = str(pick("email") or "").strip().lower()
        doc["email"] = email
        doc["name"] = str(pick("name") or "").strip() or (email.split("@")[0] if email else "")
        doc["phone"] = str(pick("phone") or "")
        doc["tax_id"] = str(pick("tax_id") or "")
        doc["company"] = str(pick("company") or "")
        status = str(pick("status") or "ativo").strip().lower()
        doc["status"] = status if status in CUSTOMER_STATUSES else "ativo"
        doc["tags"] = _keywords(pick("tags", []))
        doc["notes"] = str(pick("notes") or "")
        doc["billing"] = _normalise_address(pick("billing"))
        doc["shipping_address"] = _normalise_address(pick("shipping_address") or pick("shipping"))
        doc["marketing"] = _bool(pick("marketing"), False)
        doc["source"] = str(pick("source") or existing.get("source") or "loja")
        doc["crm_account_id"] = pick("crm_account_id") or None

    if entity == "orders":
        doc["number"] = str(pick("number") or "").strip().upper()
        status = str(pick("status") or "pendente").strip().lower()
        doc["status"] = status if status in ORDER_STATUSES else "pendente"
        payment = pick("payment", {}) or {}
        method = str(payment.get("method") or "transferencia").strip().lower()
        allowed_methods = {item["id"] for item in PAYMENT_METHODS}
        doc["payment"] = {
            "method": method if method in allowed_methods else "transferencia",
            "status": str(payment.get("status") or "pendente").strip().lower() if str(payment.get("status") or "pendente").strip().lower() in PAYMENT_STATUSES else "pendente",
            "reference": str(payment.get("reference") or ""),
            "amount": money(payment.get("amount")),
            "paid_at": payment.get("paid_at") or None,
            "note": str(payment.get("note") or ""),
            "history": list(payment.get("history") or []) if isinstance(payment.get("history"), list) else [],
        }
        doc["customer_id"] = pick("customer_id") or None
        doc["customer"] = _normalise_person(pick("customer"))
        doc["billing"] = _normalise_address(pick("billing"))
        doc["shipping_address"] = _normalise_address(pick("shipping_address") or pick("shipping"))
        doc["shipping_method_id"] = pick("shipping_method_id") or None
        doc["shipping_method"] = _normalise_shipping_snapshot(pick("shipping_method"))
        doc["coupon_id"] = pick("coupon_id") or None
        doc["coupon_code"] = str(pick("coupon_code") or "").strip().upper()
        doc["notes"] = str(pick("notes") or "")
        doc["internal_notes"] = str(pick("internal_notes") or "")
        doc["source"] = str(pick("source") or existing.get("source") or "loja")
        doc["items"] = _normalise_items(pick("items", []) or [])
        # O cupão é guardado como cópia: o desconto não muda se o cupão mudar de
        # valor (ou for apagado) depois de a encomenda ter sido feita.
        chosen = None
        if store is not None:
            if doc.get("coupon_id"):
                chosen = _find(store, "coupons", str(doc["coupon_id"]))
            if chosen is None and doc.get("coupon_code"):
                chosen = next((item for item in store["coupons"] if str(item.get("code")) == doc["coupon_code"]), None)
        if chosen is not None:
            doc["coupon_id"] = chosen.get("id")
            doc["coupon"] = {"id": chosen.get("id"), "code": chosen.get("code"), "type": chosen.get("type"), "value": money(chosen.get("value"))}
        elif isinstance(payload.get("coupon"), dict) and payload.get("coupon"):
            doc["coupon"] = payload["coupon"]
        else:
            doc["coupon_id"] = doc.get("coupon_id") or None
            doc["coupon"] = None
        if isinstance(pick("timeline"), list):
            doc["timeline"] = [item for item in pick("timeline") if isinstance(item, dict)]
        doc["stock_reserved"] = _bool(pick("stock_reserved"), bool(existing.get("stock_reserved")))
        doc["placed_at"] = pick("placed_at") or existing.get("placed_at") or None
        doc["tracking"] = str(pick("tracking") or "")

    if entity == "coupons":
        doc["code"] = str(pick("code") or "").strip().upper().replace(" ", "")
        kind = str(pick("type") or "percentagem").strip().lower()
        doc["type"] = kind if kind in {item["id"] for item in COUPON_TYPES} else "percentagem"
        doc["value"] = money(pick("value"))
        if doc["type"] == "percentagem":
            doc["value"] = max(0.0, min(100.0, doc["value"]))
        doc["description"] = str(pick("description") or "")
        doc["active"] = _bool(pick("active", True), True)
        doc["min_subtotal"] = money(pick("min_subtotal"))
        doc["starts_at"] = pick("starts_at") or None
        doc["ends_at"] = pick("ends_at") or None
        doc["max_uses"] = _int(pick("max_uses"), 0)
        doc["uses"] = _int(pick("uses"), _int(existing.get("uses"), 0))
        doc["product_ids"] = [str(item) for item in (pick("product_ids", []) or []) if item]
        doc["category_ids"] = [str(item) for item in (pick("category_ids", []) or []) if item]

    if entity == "shipping":
        doc["name"] = str(pick("name") or "").strip()
        doc["description"] = str(pick("description") or "")
        doc["price"] = money(pick("price"))
        doc["free_above"] = money(pick("free_above"))
        doc["days_min"] = _int(pick("days_min"), 1, minimum=0)
        doc["days_max"] = _int(pick("days_max"), 3, minimum=0)
        if doc["days_max"] and doc["days_max"] < doc["days_min"]:
            doc["days_max"] = doc["days_min"]
        doc["zone"] = str(pick("zone") or "Portugal Continental")
        doc["active"] = _bool(pick("active", True), True)
        doc["digital"] = _bool(pick("digital"), False)
        doc["order"] = _int(pick("order"), 0)

    if entity == "reviews":
        doc["product_id"] = pick("product_id") or None
        doc["customer_id"] = pick("customer_id") or None
        doc["customer_name"] = str(pick("customer_name") or "").strip()
        doc["email"] = str(pick("email") or "").strip().lower()
        doc["rating"] = max(1, min(5, _int(pick("rating"), 5, minimum=1)))
        doc["title"] = str(pick("title") or "").strip()
        doc["body"] = str(pick("body") or "").strip()
        status = str(pick("status") or "pendente").strip().lower()
        doc["status"] = status if status in REVIEW_STATUSES else "pendente"
        doc["reply"] = str(pick("reply") or "")
        doc["order_id"] = pick("order_id") or None
        doc["verified"] = _bool(pick("verified"), False)

    return doc


def _normalise_seo(value: Any) -> Dict[str, Any]:
    seo = value if isinstance(value, dict) else {}
    return {
        "title": str(seo.get("title") or "").strip(),
        "description": str(seo.get("description") or "").strip(),
        "keywords": _keywords(seo.get("keywords")),
        "noindex": _bool(seo.get("noindex")),
    }


def _normalise_address(value: Any) -> Dict[str, str]:
    address = value if isinstance(value, dict) else {}
    return {
        "name": str(address.get("name") or "").strip(),
        "line1": str(address.get("line1") or address.get("address") or "").strip(),
        "line2": str(address.get("line2") or "").strip(),
        "postal_code": str(address.get("postal_code") or "").strip(),
        "city": str(address.get("city") or "").strip(),
        "country": str(address.get("country") or "Portugal").strip() or "Portugal",
        "phone": str(address.get("phone") or "").strip(),
    }


def _normalise_person(value: Any) -> Dict[str, str]:
    person = value if isinstance(value, dict) else {}
    return {
        "name": str(person.get("name") or "").strip(),
        "email": str(person.get("email") or "").strip().lower(),
        "phone": str(person.get("phone") or "").strip(),
        "tax_id": str(person.get("tax_id") or "").strip(),
        "company": str(person.get("company") or "").strip(),
    }


def _normalise_shipping_snapshot(value: Any) -> Dict[str, Any]:
    method = value if isinstance(value, dict) else {}
    return {
        "id": method.get("id") or None,
        "name": str(method.get("name") or ""),
        "price": money(method.get("price")),
        "days_min": _int(method.get("days_min"), 0),
        "days_max": _int(method.get("days_max"), 0),
    }


def _normalise_items(value: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not isinstance(value, list):
        return items
    for raw in value[:MAX_ORDER_ITEMS]:
        if not isinstance(raw, dict):
            continue
        quantity = _int(raw.get("quantity"), 0)
        if quantity <= 0:
            continue
        items.append(
            {
                "id": str(raw.get("id") or _new_id("lin")),
                "product_id": raw.get("product_id") or None,
                "name": str(raw.get("name") or "").strip(),
                "sku": str(raw.get("sku") or ""),
                "unit": str(raw.get("unit") or "un"),
                "quantity": quantity,
                "unit_price": money(raw.get("unit_price")),
                "tax_rate": money(raw.get("tax_rate")),
                "discount": money(raw.get("discount")),
                "image_url": str(raw.get("image_url") or ""),
            }
        )
    return items


def _order_totals(doc: Dict[str, Any], store_settings: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Totais de uma encomenda (subtotal, descontos, portes, IVA e total)."""
    settings = store_settings or get_settings()
    inclusive = _bool(settings.get("prices_include_tax", True), True)
    subtotal = 0.0
    tax_total = 0.0
    for item in doc.get("items") or []:
        amounts = line_amounts(item.get("unit_price"), item.get("quantity"), item.get("tax_rate"), item.get("discount"), prices_include_tax=inclusive)
        subtotal = money(subtotal + amounts["gross"])
        tax_total = money(tax_total + amounts["tax"])
    coupon_type = str((doc.get("coupon") or {}).get("type") or "")
    coupon_value = money((doc.get("coupon") or {}).get("value"))
    discount = 0.0
    free_shipping = False
    if coupon_type == "percentagem":
        discount = money(subtotal * coupon_value / 100)
    elif coupon_type == "valor":
        discount = money(min(coupon_value, subtotal))
    elif coupon_type == "portes_gratis":
        free_shipping = True
    shipping = money((doc.get("shipping_method") or {}).get("price"))
    if free_shipping:
        shipping = 0.0
    taxable = money(max(0.0, subtotal - discount))
    # O IVA acompanha o desconto concedido sobre as mercadorias.
    if subtotal:
        tax_total = money(tax_total * (taxable / subtotal))
    total = money(taxable + shipping)
    shipping_tax = money(shipping - (shipping / (1 + money(settings.get("default_tax_rate", 23)) / 100) if inclusive and money(settings.get("default_tax_rate")) else shipping))
    return {
        "subtotal": subtotal,
        "discount_total": discount,
        "shipping_total": shipping,
        "tax_total": money(tax_total + max(0.0, shipping_tax)),
        "total": total,
        "items_count": sum(_int(item.get("quantity")) for item in doc.get("items") or []),
    }


def _generate_order_number(store: Dict[str, Any]) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", str(store["settings"].get("order_prefix") or "EN").upper())[:4] or "EN"
    year = datetime.now(timezone.utc).year
    head = f"{prefix}{year}-"
    used = 0
    for order in store["orders"]:
        number = str(order.get("number") or "")
        if number.startswith(head):
            try:
                used = max(used, int(number.rsplit("-", 1)[-1]))
            except ValueError:
                continue
    return f"{head}{used + 1:04d}"


def _sku_for(store: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """SKU automático (`SLUG-001`) quando o produto não traz um."""
    if doc.get("sku"):
        return str(doc["sku"])
    base = re.sub(r"[^A-Z0-9]", "", str(doc.get("slug") or "PRD").upper())[:10] or "PRD"
    used = {str(item.get("sku") or "") for item in store["products"]}
    index = 1
    while f"{base}-{index:03d}" in used:
        index += 1
    return f"{base}-{index:03d}"


# --------------------------------------------------------------------------
# Leitura (gestão)
# --------------------------------------------------------------------------
def _summary(entity: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    item = {key: value for key, value in doc.items() if key not in ("description", "items", "timeline")}
    item["entity"] = entity
    item["entity_label"] = SINGULAR[entity]
    if entity == "products":
        item["image_url"] = first_image_url(doc)
        item["available"] = is_available(doc)
        item["short_description"] = doc.get("short_description") or _excerpt(doc.get("description") or "")
    if entity == "orders":
        item["items_count"] = sum(_int(line.get("quantity")) for line in doc.get("items") or [])
        item["items_summary"] = ", ".join(str(line.get("name") or "") for line in (doc.get("items") or [])[:3])
    if entity == "reviews":
        item["product_name"] = product_name(doc.get("product_id"))
    return item


def list_items(
    entity: str,
    status: Optional[str] = None,
    query: Optional[str] = None,
    category_id: Optional[str] = None,
    tag: Optional[str] = None,
    product_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    payment_status: Optional[str] = None,
    stock: Optional[str] = None,
    limit: int = 300,
    light: bool = False,
) -> Dict[str, Any]:
    """Lista uma entidade, com filtros por estado, texto, categoria e etiqueta."""
    _check_entity(entity)
    store = _load()
    items: List[Dict[str, Any]] = list(store[entity])

    if status and status != "all":
        wanted = {part.strip() for part in status.split(",") if part.strip()}
        items = [item for item in items if str(item.get("status")) in wanted]

    if payment_status and payment_status != "all":
        wanted_payment = {part.strip() for part in payment_status.split(",") if part.strip()}
        items = [item for item in items if str((item.get("payment") or {}).get("status")) in wanted_payment]

    if category_id:
        items = [item for item in items if category_id in (item.get("category_ids") or [])]

    if product_id:
        items = [item for item in items if str(item.get("product_id")) == product_id]

    if customer_id:
        items = [item for item in items if str(item.get("customer_id")) == customer_id]

    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]

    if stock:
        threshold = _int(get_settings().get("low_stock_threshold"), 5)

        def matches_stock(item: Dict[str, Any]) -> bool:
            quantity = _int(item.get("stock"))
            if stock == "out":
                return quantity <= 0
            if stock == "low":
                return 0 < quantity <= max(threshold, _int(item.get("stock_min")))
            return True

        items = [item for item in items if matches_stock(item)]

    if query:
        needle = query.strip().lower()

        def matches(item: Dict[str, Any]) -> bool:
            haystack = " ".join(
                str(item.get(field) or "")
                for field in ("name", "title", "slug", "sku", "number", "code", "email", "description", "short_description", "notes", "body", "internal_notes", "zone")
            )
            haystack += " " + " ".join(str(tag) for tag in (item.get("tags") or []))
            haystack += " " + " ".join(str((item.get("customer") or {}).get(field) or "") for field in ("name", "email", "phone"))
            return needle in haystack.lower()

        items = [item for item in items if matches(item)]

    if entity == "products":
        items.sort(key=lambda item: (_int(item.get("order")), str(item.get("name") or "").lower()))
    elif entity == "shipping":
        items.sort(key=lambda item: (_int(item.get("order")), str(item.get("name") or "").lower()))
    else:
        items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)

    total = len(items)
    items = items[: max(1, min(limit, 500))]
    payload_items = [_summary(entity, item) for item in items] if light else [copy.deepcopy(item) for item in items]
    if not light:
        for item in payload_items:
            if entity == "products":
                item["image_url"] = first_image_url(item)
                item["available"] = is_available(item)
            if entity == "orders":
                item["totals"] = _order_totals(item)
                item["items_count"] = sum(_int(line.get("quantity")) for line in item.get("items") or [])
    return {"total": total, "count": len(payload_items), "items": payload_items}


def get_item(entity: str, item_id: str) -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
    payload = copy.deepcopy(doc)
    if entity == "orders":
        payload["totals"] = _order_totals(payload)
        payload["items_count"] = sum(_int(line.get("quantity")) for line in payload.get("items") or [])
    if entity == "products":
        payload["image_url"] = first_image_url(payload)
        payload["available"] = is_available(payload)
    return payload


def find_order_by_number(number: str) -> Optional[Dict[str, Any]]:
    wanted = str(number or "").strip().upper()
    if not wanted:
        return None
    store = _load()
    for order in store["orders"]:
        if str(order.get("number") or "").upper() == wanted:
            return copy.deepcopy(order)
    return None


def customer_by_email(email: str) -> Optional[Dict[str, Any]]:
    wanted = str(email or "").strip().lower()
    if not wanted:
        return None
    store = _load()
    for customer in store["customers"]:
        if str(customer.get("email") or "").lower() == wanted:
            return copy.deepcopy(customer)
    return None


def product_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    wanted = str(slug or "").strip().lower()
    store = _load()
    for product in store["products"]:
        if published_only and product.get("status") != "publicado":
            continue
        if str(product.get("slug") or "").lower() == wanted:
            return copy.deepcopy(product)
    return None


def category_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    wanted = str(slug or "").strip().lower()
    store = _load()
    for category in store["categories"]:
        if str(category.get("slug") or "").lower() == wanted:
            return copy.deepcopy(category)
    return None


def product_name(product_id: Optional[str]) -> str:
    if not product_id:
        return ""
    store = _load()
    product = _find(store, "products", str(product_id))
    return str((product or {}).get("name") or "")


def customer_name(customer_id: Optional[str]) -> str:
    if not customer_id:
        return ""
    store = _load()
    customer = _find(store, "customers", str(customer_id))
    return str((customer or {}).get("name") or "")


# --------------------------------------------------------------------------
# Imagens, stock e disponibilidade
# --------------------------------------------------------------------------
def _cms_media_url(media_id: str) -> str:
    """URL de um media do CMS (a loja reutiliza a biblioteca do CMS)."""
    try:
        from api import cms_store  # import tardio: a loja funciona sem o CMS carregado

        return cms_store.media_url(media_id)
    except Exception as exc:  # pragma: no cover - CMS é opcional
        logger.debug("Não foi possível resolver o media %s (%s)", media_id, exc)
        return ""


def first_image_url(doc: Dict[str, Any]) -> str:
    for media_id in doc.get("image_ids") or []:
        url = _cms_media_url(str(media_id))
        if url:
            return url
    for url in doc.get("image_urls") or []:
        if str(url).strip():
            return str(url).strip()
    return ""


def image_urls(doc: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for media_id in doc.get("image_ids") or []:
        url = _cms_media_url(str(media_id))
        if url:
            urls.append(url)
    for url in doc.get("image_urls") or []:
        if str(url).strip():
            urls.append(str(url).strip())
    return urls


def is_available(doc: Dict[str, Any]) -> bool:
    if doc.get("status") and doc.get("status") != "publicado":
        return False
    if not _bool(doc.get("track_stock"), False):
        return True
    if _int(doc.get("stock")) > 0:
        return True
    return _bool(doc.get("allow_backorder"), False)


def stock_label(doc: Dict[str, Any], threshold: int = 5) -> str:
    if not _bool(doc.get("track_stock"), False):
        return "Disponível"
    quantity = _int(doc.get("stock"))
    if quantity <= 0:
        return "Sob encomenda" if _bool(doc.get("allow_backorder"), False) else "Esgotado"
    if quantity <= max(threshold, _int(doc.get("stock_min"))):
        return f"Últimas {quantity} unidades"
    return "Em stock"


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------
def save_item(entity: str, payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    """Cria ou altera um documento da loja (com revisão e registo de atividade)."""
    _check_entity(entity)
    store = _load()
    item_id = payload.get("id")
    existing = _find(store, entity, str(item_id)) if item_id else None
    if item_id and existing is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")

    doc = _normalise(entity, {**payload, "updated_by": author or payload.get("updated_by")}, existing, store)

    if entity == "products":
        if not doc.get("name"):
            raise ValueError("O nome do produto é obrigatório.")
        if doc.get("price") is None or doc.get("price") < 0:
            raise ValueError("O preço não pode ser negativo.")
    if entity == "categories" and not doc.get("name"):
        raise ValueError("O nome da categoria é obrigatório.")
    if entity == "customers" and not doc.get("email"):
        raise ValueError("O email do cliente é obrigatório.")
    if entity == "coupons":
        if not doc.get("code"):
            raise ValueError("O código do cupão é obrigatório.")
        if doc.get("type") in ("percentagem", "valor") and doc.get("value") <= 0:
            raise ValueError("Um cupão de desconto precisa de um valor maior do que zero.")
    if entity == "shipping" and not doc.get("name"):
        raise ValueError("O nome do método de envio é obrigatório.")
    if entity == "reviews":
        if not doc.get("product_id"):
            raise ValueError("A avaliação tem de indicar o produto.")
        if not doc.get("customer_name"):
            raise ValueError("A avaliação tem de indicar o nome de quem avalia.")
    if entity == "orders" and not doc.get("items"):
        raise ValueError("Uma encomenda tem de ter pelo menos uma linha.")

    if entity in ("products", "categories"):
        doc["slug"] = _unique(store, entity, str(doc.get("slug") or ""), ignore_id=str(existing.get("id")) if existing else None)
    if entity == "products":
        doc["sku"] = _sku_for(store, doc)
    if entity == "coupons":
        for coupon in store["coupons"]:
            if str(coupon.get("code")) == doc["code"] and (existing is None or coupon.get("id") != existing.get("id")):
                raise ValueError(f"Já existe um cupão com o código «{doc['code']}».")

    if entity == "orders":
        if not doc.get("number"):
            doc["number"] = _generate_order_number(store)
        if existing and str(existing.get("number")) != str(doc.get("number")):
            for order in store["orders"]:
                if order.get("id") != (existing or {}).get("id") and str(order.get("number")) == str(doc["number"]):
                    raise ValueError(f"Já existe a encomenda «{doc['number']}».")
        totals = _order_totals(doc)
        doc.update({key: value for key, value in totals.items() if key != "items_count"})
        doc["items_count"] = totals["items_count"]

    totals_view: Dict[str, Any] = {}
    if entity == "orders":
        totals_view = _order_totals(doc)

    if existing:
        _snapshot(store, entity, existing, author, note="antes de guardar")
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or _now()
        doc["updated_at"] = _now()
        store[entity][store[entity].index(existing)] = doc
        action = "alterar"
    else:
        doc["id"] = doc.get("id") or _new_id(ID_PREFIX[entity])
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        if entity == "products":
            doc["published_at"] = _now() if doc.get("status") == "publicado" else None
        if entity == "orders":
            doc["placed_at"] = doc.get("placed_at") or _now()
            doc.setdefault("timeline", [{"at": doc["placed_at"], "status": doc.get("status") or "pendente", "note": "Encomenda criada na plataforma", "actor": author or "plataforma"}])
            doc["source"] = doc.get("source") or "plataforma"
        store[entity].insert(0, doc)
        action = "criar"

    _after_write(store, entity, doc)
    _log(store, action, entity, doc, author)
    _write_store(store)
    payload_doc = copy.deepcopy(doc)
    if entity == "orders":
        payload_doc["totals"] = totals_view or _order_totals(payload_doc)
    return payload_doc


def delete_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de apagar")
    store[entity].remove(doc)
    if entity == "categories":
        for product in store["products"]:
            if item_id in (product.get("category_ids") or []):
                product["category_ids"] = [value for value in product["category_ids"] if value != item_id]
        for category in store["categories"]:
            if category.get("parent_id") == item_id:
                category["parent_id"] = None
    if entity == "products":
        for review in store["reviews"]:
            if str(review.get("product_id")) == item_id:
                review["product_id"] = None
    if entity == "shipping":
        for order in store["orders"]:
            if str(order.get("shipping_method_id")) == item_id:
                order["shipping_method_id"] = None
    if entity == "coupons":
        for order in store["orders"]:
            if str(order.get("coupon_id")) == item_id:
                order["coupon_id"] = None
    _after_write(store, entity, doc)
    _log(store, "apagar", entity, doc, author)
    _write_store(store)
    return {"deleted": True, "id": item_id}


def duplicate_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    if entity in ("orders", "customers"):
        raise ValueError("Encomendas e clientes não se duplicam.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
    clone = copy.deepcopy(doc)
    clone["id"] = _new_id(ID_PREFIX[entity])
    clone["created_at"] = _now()
    clone["updated_at"] = _now()
    clone["updated_by"] = author
    base = str(doc.get("name") or doc.get("code") or "")
    if entity == "coupons":
        clone["code"] = f"{base}-COPIA"
        clone["uses"] = 0
        clone["active"] = False
    else:
        clone["name"] = f"{base} (cópia)"
    if entity in ("products", "categories"):
        clone["slug"] = _unique(store, entity, _slug(f"{doc.get('slug') or base}-copia"), ignore_id=None)
    if entity == "products":
        clone["status"] = "rascunho"
        clone["published_at"] = None
        clone["scheduled_at"] = None
        clone["sku"] = ""
    if entity == "reviews":
        clone["status"] = "pendente"
    store[entity].insert(0, clone)
    _after_write(store, entity, clone)
    _log(store, "duplicar", entity, clone, author, f"a partir de {item_id}")
    _write_store(store)
    return copy.deepcopy(clone)


# --------------------------------------------------------------------------
# Publicação
# --------------------------------------------------------------------------
def _apply_schedule(store: Dict[str, Any]) -> bool:
    """Publica os produtos agendados que já venceram. Devolve True se mudou algo."""
    now = datetime.now(timezone.utc)
    changed = False
    for product in store["products"]:
        if product.get("status") != "agendado":
            continue
        stamp = product.get("scheduled_at")
        if not stamp:
            continue
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when <= now:
            product["status"] = "publicado"
            product["published_at"] = product.get("published_at") or _now()
            product["updated_at"] = _now()
            _log(store, "publicar (agendado)", "products", product, "agendador")
            changed = True
    return changed


def publish_item(entity: str, item_id: str, author: str = "", at: Optional[str] = None) -> Dict[str, Any]:
    """Publica agora, ou agenda para `at` (ISO 8601)."""
    _check_entity(entity)
    if entity not in ("products", "categories"):
        raise ValueError("Só produtos e categorias têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de publicar")
    if at:
        doc["status"] = "agendado"
        doc["scheduled_at"] = at
        action = "agendar"
    else:
        doc["status"] = "publicado"
        doc["scheduled_at"] = None
        doc["published_at"] = doc.get("published_at") or _now()
        action = "publicar"
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _log(store, action, entity, doc, author, f"para {at}" if at else "")
    _write_store(store)
    return copy.deepcopy(doc)


def unpublish_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    if entity not in ("products", "categories"):
        raise ValueError("Só produtos e categorias têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
    doc["status"] = "rascunho"
    doc["scheduled_at"] = None
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _log(store, "despublicar", entity, doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def set_status(entity: str, item_id: str, status: str, author: str = "") -> Dict[str, Any]:
    value = _status(status)
    if value == "publicado":
        return publish_item(entity, item_id, author)
    if value == "agendado":
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
        return publish_item(entity, item_id, author, at=str(doc.get("scheduled_at") or _now()))
    if value == "arquivado":
        _check_entity(entity)
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR[entity]} {item_id} não encontrado.")
        doc["status"] = "arquivado"
        doc["updated_at"] = _now()
        _log(store, "arquivar", entity, doc, author)
        _write_store(store)
        return copy.deepcopy(doc)
    return unpublish_item(entity, item_id, author)


# --------------------------------------------------------------------------
# Encomendas: estados, pagamento e notas
# --------------------------------------------------------------------------
def _restore_stock(store: Dict[str, Any], order: Dict[str, Any]) -> None:
    if not _bool(order.get("stock_reserved"), False):
        return
    for line in order.get("items") or []:
        product = _find(store, "products", str(line.get("product_id") or ""))
        if product is None or not _bool(product.get("track_stock"), False):
            continue
        product["stock"] = _int(product.get("stock")) + _int(line.get("quantity"))
        product["updated_at"] = _now()
    order["stock_reserved"] = False


def set_order_status(order_id: str, status: str, author: str = "", note: str = "", actor: str = "") -> Dict[str, Any]:
    """Muda o estado da encomenda e deixa o passo no histórico."""
    value = str(status or "").strip().lower()
    if value not in ORDER_STATUSES:
        raise ValueError(f"Estado inválido «{status}». Válidos: {', '.join(ORDER_STATUSES)}.")
    store = _load()
    order = _find(store, "orders", order_id)
    if order is None:
        raise KeyError(f"Encomenda {order_id} não encontrada.")
    if value == order.get("status"):
        return get_item("orders", order_id)
    _snapshot(store, "orders", order, author, note="antes de mudar o estado")
    if value in ORDER_CLOSED_LOST:
        _restore_stock(store, order)
    # Cancelar/reembolsar uma encomenda já paga marca o pagamento como devolvido.
    if value in ORDER_CLOSED_LOST and (order.get("payment") or {}).get("status") == "pago":
        order.setdefault("payment", {})["status"] = "reembolsado"
        order["payment"]["history"] = list(order["payment"].get("history") or []) + [
            {"at": _now(), "status": "reembolsado", "amount": money((order.get("payment") or {}).get("amount")), "note": f"Anulado com o estado «{ORDER_LABELS[value]}»", "actor": author}
        ]
    order["status"] = value
    order["updated_at"] = _now()
    order["updated_by"] = author
    order["timeline"] = list(order.get("timeline") or []) + [
        {"at": _now(), "status": value, "note": note or f"Estado alterado para {ORDER_LABELS[value]}", "actor": actor or author or "plataforma"}
    ]
    _log(store, "estado", "orders", order, actor or author, ORDER_LABELS[value])
    _write_store(store)
    return get_item("orders", order_id)


def register_payment(order_id: str, payload: Dict[str, Any], author: str = "", actor: str = "") -> Dict[str, Any]:
    """Regista um pagamento manual (MB Way, transferência, numerário…)."""
    store = _load()
    order = _find(store, "orders", order_id)
    if order is None:
        raise KeyError(f"Encomenda {order_id} não encontrada.")
    payment = order.setdefault("payment", {})
    method = str(payload.get("method") or payment.get("method") or "transferencia").strip().lower()
    allowed = {item["id"] for item in PAYMENT_METHODS}
    if method not in allowed:
        raise ValueError(f"Método de pagamento inválido «{method}».")
    amount = money(payload.get("amount"))
    total = money(order.get("total"))
    received = money(payment.get("amount")) + amount if amount else total
    status = str(payload.get("status") or "").strip().lower()
    if status not in PAYMENT_STATUSES:
        status = "pago" if received >= total and total > 0 else "parcial" if received > 0 else "pendente"
    if amount < 0:
        raise ValueError("O valor recebido não pode ser negativo.")
    _snapshot(store, "orders", order, author, note="antes de registar pagamento")
    payment["method"] = method
    payment["amount"] = money(received)
    payment["status"] = status
    payment["reference"] = str(payload.get("reference") or payment.get("reference") or "")
    payment["note"] = str(payload.get("note") or payment.get("note") or "")
    if status == "pago":
        payment["paid_at"] = payment.get("paid_at") or str(payload.get("paid_at") or _now())
    payment["history"] = list(payment.get("history") or []) + [
        {"at": _now(), "status": status, "amount": money(amount or total), "method": method, "note": str(payload.get("note") or ""), "actor": actor or author or "plataforma"}
    ]
    order["updated_at"] = _now()
    order["updated_by"] = author
    order["timeline"] = list(order.get("timeline") or []) + [
        {"at": _now(), "status": order.get("status"), "note": f"Pagamento registado ({PAYMENT_LABELS.get(status, status)})", "actor": actor or author or "plataforma"}
    ]
    # Cobrir o total faz a encomenda avançar para «pago», se ainda estava pendente.
    if status == "pago" and order.get("status") == "pendente":
        order["status"] = "pago"
    _log(store, "pagamento", "orders", order, actor or author, f"{PAYMENT_LABELS.get(status, status)} · {amount or total} €")
    _write_store(store)
    return get_item("orders", order_id)


def add_order_note(order_id: str, note: str, author: str = "", internal: bool = True) -> Dict[str, Any]:
    store = _load()
    order = _find(store, "orders", order_id)
    if order is None:
        raise KeyError(f"Encomenda {order_id} não encontrada.")
    text = str(note or "").strip()
    if not text:
        raise ValueError("A nota não pode estar vazia.")
    field = "internal_notes" if internal else "notes"
    current = str(order.get(field) or "").strip()
    stamp = _date(_now())
    order[field] = f"{current}\n[{stamp} · {author or 'plataforma'}] {text}".strip()
    order["updated_at"] = _now()
    order["updated_by"] = author
    _log(store, "nota", "orders", order, author, text[:120])
    _write_store(store)
    return get_item("orders", order_id)


# --------------------------------------------------------------------------
# Cupões
# --------------------------------------------------------------------------
def _coupon_discount(coupon: Dict[str, Any], subtotal: float, items: List[Dict[str, Any]]) -> Tuple[float, bool, str]:
    """Desconto de um cupão sobre as linhas elegíveis. Devolve (desconto, portes grátis, erro)."""
    products = {str(item.get("product_id")): item for item in items}
    allowed_ids = {str(value) for value in (coupon.get("product_ids") or [])}
    allowed_categories = {str(value) for value in (coupon.get("category_ids") or [])}
    eligible = 0.0
    store = _load()
    for product_id, item in products.items():
        product = _find(store, "products", product_id)
        if allowed_ids or allowed_categories:
            in_ids = product_id in allowed_ids
            in_categories = bool(product and allowed_categories & {str(value) for value in (product.get("category_ids") or [])})
            if not (in_ids or in_categories):
                continue
        eligible = money(eligible + money(item.get("unit_price")) * _int(item.get("quantity")))
    if coupon.get("min_subtotal") and subtotal < money(coupon["min_subtotal"]):
        return 0.0, False, f"O cupão exige um subtotal mínimo de {money(coupon['min_subtotal'])} €."
    if not allowed_ids and not allowed_categories:
        eligible = subtotal
    if eligible <= 0:
        return 0.0, False, "Este cupão não se aplica aos produtos do carrinho."
    kind = str(coupon.get("type") or "percentagem")
    if kind == "percentagem":
        return money(eligible * money(coupon.get("value")) / 100), False, ""
    if kind == "valor":
        return money(min(money(coupon.get("value")), eligible)), False, ""
    return 0.0, True, ""


def validate_coupon(
    code: str,
    items: List[Dict[str, Any]],
    subtotal: Optional[float] = None,
    *,
    increment: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Valida um cupão para um conjunto de linhas. Devolve o desconto e a mensagem."""
    store = _load()
    wanted = str(code or "").strip().upper()
    if not wanted:
        return {"valid": False, "error": "Indique o código do cupão.", "code": wanted, "discount": 0.0, "free_shipping": False}
    coupon = next((item for item in store["coupons"] if str(item.get("code") or "").upper() == wanted), None)
    if coupon is None:
        return {"valid": False, "error": f"O cupão «{wanted}» não existe.", "code": wanted, "discount": 0.0, "free_shipping": False}
    if not _bool(coupon.get("active"), True):
        return {"valid": False, "error": "Este cupão já não está ativo.", "code": wanted, "discount": 0.0, "free_shipping": False}
    now = datetime.now(timezone.utc)

    def stamp_is_past(value: Optional[str]) -> bool:
        if not value:
            return False
        try:
            when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when < now

    if stamp_is_past(coupon.get("starts_at")):
        return {"valid": False, "error": "Este cupão ainda não começou.", "code": wanted, "discount": 0.0, "free_shipping": False}
    if stamp_is_past(coupon.get("ends_at")):
        return {"valid": False, "error": "Este cupão já expirou.", "code": wanted, "discount": 0.0, "free_shipping": False}
    max_uses = _int(coupon.get("max_uses"))
    if max_uses and _int(coupon.get("uses")) >= max_uses:
        return {"valid": False, "error": "Este cupão já atingiu o número máximo de utilizações.", "code": wanted, "discount": 0.0, "free_shipping": False}
    base = money(subtotal if subtotal is not None else sum(money(line.get("unit_price")) * _int(line.get("quantity")) for line in items))
    discount, free_shipping, error = _coupon_discount(coupon, base, items)
    if error:
        return {"valid": False, "error": error, "code": wanted, "discount": 0.0, "free_shipping": False}
    if increment:
        coupon["uses"] = _int(coupon.get("uses")) + 1
        if persist:
            _write_store(store)
    return {
        "valid": True,
        "error": "",
        "code": wanted,
        "coupon_id": coupon.get("id"),
        "type": coupon.get("type"),
        "value": money(coupon.get("value")),
        "discount": money(discount),
        "free_shipping": bool(free_shipping),
        "description": str(coupon.get("description") or ""),
    }


# --------------------------------------------------------------------------
# Vitrine pública
# --------------------------------------------------------------------------
def get_settings() -> Dict[str, Any]:
    store = _load()
    settings = copy.deepcopy(store["settings"])
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, copy.deepcopy(value))
    return settings


def save_settings(payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    store = _load()
    current = store["settings"]
    allowed = set(DEFAULT_SETTINGS)
    for key, value in (payload or {}).items():
        if key not in allowed:
            continue
        if key in ("payments", "seo", "social", "payment_instructions"):
            base = copy.deepcopy(current.get(key) or {})
            if isinstance(value, dict):
                base.update(value)
            current[key] = base
            continue
        current[key] = value
    current["updated_at"] = _now()
    current["updated_by"] = author
    _log(store, "definições", "settings", {"id": "settings", "name": "Definições da loja"}, author)
    _write_store(store)
    return get_settings()


def public_categories() -> List[Dict[str, Any]]:
    store = _load()
    counts: Dict[str, int] = {}
    for product in store["products"]:
        if product.get("status") != "publicado":
            continue
        for category_id in product.get("category_ids") or []:
            counts[str(category_id)] = counts.get(str(category_id), 0) + 1
    items = [category for category in store["categories"] if category.get("status") == "publicado"]
    items.sort(key=lambda item: (_int(item.get("order")), str(item.get("name") or "").lower()))
    return [
        {
            "id": category.get("id"),
            "name": category.get("name"),
            "slug": category.get("slug"),
            "description": category.get("description") or "",
            "image_url": _cms_media_url(str(category.get("image_id") or "")) or str(category.get("image_url") or ""),
            "products": counts.get(str(category.get("id")), 0),
            "featured": _bool(category.get("featured"), False),
        }
        for category in items
    ]


def public_products(
    *,
    category_id: Optional[str] = None,
    query: Optional[str] = None,
    sort: str = "destaque",
    tag: Optional[str] = None,
    featured_only: bool = False,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Produtos publicados, prontos para a vitrine (com imagem, preço e disponibilidade)."""
    store = _load()
    settings = get_settings()
    threshold = _int(settings.get("low_stock_threshold"), 5)
    items = [product for product in store["products"] if product.get("status") == "publicado"]
    if category_id:
        items = [product for product in items if category_id in (product.get("category_ids") or [])]
    if tag:
        items = [product for product in items if tag in (product.get("tags") or [])]
    if featured_only:
        items = [product for product in items if _bool(product.get("featured"), False)]
    if query:
        needle = str(query).strip().lower()

        def matches(product: Dict[str, Any]) -> bool:
            haystack = " ".join(str(product.get(field) or "") for field in ("name", "sku", "short_description", "description"))
            haystack += " " + " ".join(str(value) for value in (product.get("tags") or []))
            return needle in haystack.lower()

        items = [product for product in items if matches(product)]

    if sort == "preco":
        items.sort(key=lambda item: money(item.get("price")))
    elif sort == "preco-desc":
        items.sort(key=lambda item: money(item.get("price")), reverse=True)
    elif sort == "nome":
        items.sort(key=lambda item: str(item.get("name") or "").lower())
    elif sort == "novidade":
        items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    else:
        items.sort(key=lambda item: (0 if _bool(item.get("featured"), False) else 1, _int(item.get("order")), str(item.get("name") or "").lower()))

    payload = []
    for product in items[:limit]:
        item = copy.deepcopy(product)
        item["image_url"] = first_image_url(product)
        item["images"] = image_urls(product)
        item["available"] = is_available(product)
        item["stock_label"] = stock_label(product, threshold)
        item["url"] = f"/loja/produto/{product.get('slug')}"
        item["short_description"] = str(product.get("short_description") or _excerpt(str(product.get("description") or ""), 160))
        item["on_sale"] = bool(money(product.get("compare_at_price")) > money(product.get("price")))
        payload.append(item)
    return payload


def product_payload(product: Dict[str, Any]) -> Dict[str, Any]:
    """Produto como a vitrine e o carrinho (JavaScript) precisam dele."""
    settings = get_settings()
    threshold = _int(settings.get("low_stock_threshold"), 5)
    return {
        "id": product.get("id"),
        "slug": product.get("slug"),
        "name": product.get("name"),
        "sku": product.get("sku"),
        "price": money(product.get("price")),
        "compare_at_price": money(product.get("compare_at_price")),
        "tax_rate": money(product.get("tax_rate")),
        "unit": product.get("unit") or "un",
        "type": product.get("type"),
        "stock": _int(product.get("stock")),
        "track_stock": _bool(product.get("track_stock"), False),
        "allow_backorder": _bool(product.get("allow_backorder"), False),
        "available": is_available(product),
        "stock_label": stock_label(product, threshold),
        "short_description": str(product.get("short_description") or _excerpt(str(product.get("description") or ""), 160)),
        "image_url": first_image_url(product),
        "url": f"/loja/produto/{product.get('slug')}",
        "rating_avg": money(product.get("rating_avg")),
        "rating_count": _int(product.get("rating_count")),
    }


def public_shipping_methods(digital_only: bool = False) -> List[Dict[str, Any]]:
    store = _load()
    items = [method for method in store["shipping"] if _bool(method.get("active"), True)]
    wanted = [method for method in items if _bool(method.get("digital"), False) is digital_only]
    # Numa loja só com produtos físicos pode não haver método «não digital»:
    # nesse caso mostram-se todos os métodos ativos.
    items = wanted or items
    items.sort(key=lambda item: (_int(item.get("order")), money(item.get("price"))))
    return [
        {
            "id": method.get("id"),
            "name": method.get("name"),
            "description": method.get("description") or "",
            "price": money(method.get("price")),
            "free_above": money(method.get("free_above")),
            "days_min": _int(method.get("days_min")),
            "days_max": _int(method.get("days_max")),
            "zone": method.get("zone") or "",
            "digital": _bool(method.get("digital"), False),
        }
        for method in items
    ]


def shipping_price(method: Dict[str, Any], subtotal: float) -> float:
    price = money(method.get("price"))
    free_above = money(method.get("free_above"))
    if free_above and money(subtotal) >= free_above:
        return 0.0
    return price


def approved_reviews(product_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    store = _load()
    items = [review for review in store["reviews"] if str(review.get("product_id")) == str(product_id) and review.get("status") == "aprovada"]
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items[:limit])


def related_products(product: Dict[str, Any], limit: int = 4) -> List[Dict[str, Any]]:
    """Outros produtos publicados: primeiro os da mesma categoria."""
    store = _load()
    categories = {str(value) for value in (product.get("category_ids") or [])}
    published = [item for item in store["products"] if item.get("status") == "publicado" and item.get("id") != product.get("id")]
    same = [item for item in published if categories & {str(value) for value in (item.get("category_ids") or [])}]
    chosen = same or published
    return [product_payload(item) for item in chosen[:limit]]


# --------------------------------------------------------------------------
# Finalização de compra (checkout)
# --------------------------------------------------------------------------
def _resolve_customer(store: Dict[str, Any], payload: Dict[str, Any], person: Dict[str, str], author: str) -> Optional[Dict[str, Any]]:
    email = str(person.get("email") or "").strip().lower()
    if not email:
        return None
    customer = None
    for item in store["customers"]:
        if str(item.get("email") or "").lower() == email:
            customer = item
            break
    address = _normalise_address(payload.get("shipping_address") or payload.get("billing"))
    billing = _normalise_address(payload.get("billing") or payload.get("shipping_address"))
    if customer is None:
        customer = {
            "id": _new_id(ID_PREFIX["customers"]),
            "email": email,
            "name": person.get("name") or email.split("@")[0],
            "phone": person.get("phone") or address.get("phone") or "",
            "tax_id": person.get("tax_id") or "",
            "company": person.get("company") or "",
            "status": "ativo",
            "tags": [],
            "notes": "",
            "billing": billing,
            "shipping_address": address,
            "marketing": _bool(payload.get("marketing"), False),
            "source": "loja",
            "crm_account_id": None,
            "created_at": _now(),
            "updated_at": _now(),
            "updated_by": author,
        }
        store["customers"].insert(0, customer)
        _log(store, "criar", "customers", customer, author, "cliente criado no checkout da loja")
    else:
        for field, value in (("name", person.get("name")), ("phone", person.get("phone") or address.get("phone")), ("tax_id", person.get("tax_id")), ("company", person.get("company"))):
            if value:
                customer[field] = value
        if address.get("line1"):
            customer["shipping_address"] = address
        if billing.get("line1"):
            customer["billing"] = billing
        if _bool(payload.get("marketing"), False):
            customer["marketing"] = True
        customer["updated_at"] = _now()
    return customer


def _crm_account_for(customer: Dict[str, Any]) -> str:
    """Liga o cliente a uma conta do CRM (integração opcional, nunca falha a compra)."""
    if not customer or customer.get("crm_account_id"):
        return str((customer or {}).get("crm_account_id") or "")
    try:
        from api import crm_store  # noqa: F401  (só existe se o CRM estiver instalado)
    except Exception:
        return ""
    try:  # pragma: no cover - depende do módulo de CRM
        from api import crm_store as crm  # type: ignore

        account = crm.save_item(
            "accounts",
            {
                "name": customer.get("company") or customer.get("name") or customer.get("email"),
                "email": customer.get("email"),
                "phone": customer.get("phone"),
                "notes": f"Cliente da loja ({customer.get('email')})",
            },
            "loja",
        )
        return str(account.get("id") or "")
    except Exception as exc:
        logger.debug("CRM indisponível para ligar o cliente %s (%s)", customer.get("email"), exc)
        return ""


def checkout(payload: Dict[str, Any], actor: str = "loja") -> Dict[str, Any]:
    """Converte um carrinho numa encomenda, com preços e stock validados pelo servidor.

    Os preços vêm sempre do catálogo — o carrinho do browser só envia identificadores
    e quantidades. É esta função que desconta o stock e conta a utilização do cupão.
    """
    store = _load()
    settings = get_settings()
    inclusive = _bool(settings.get("prices_include_tax", True), True)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("O carrinho está vazio.")

    lines: List[Dict[str, Any]] = []
    for raw in raw_items[:MAX_ORDER_ITEMS]:
        if not isinstance(raw, dict):
            continue
        reference = str(raw.get("product_id") or raw.get("id") or raw.get("slug") or "").strip()
        if not reference:
            continue
        product = _find(store, "products", reference)
        if product is None:
            product = next((item for item in store["products"] if str(item.get("slug")) == reference), None)
        if product is None:
            raise ValueError(f"Produto «{reference}» não encontrado.")
        if product.get("status") != "publicado":
            raise ValueError(f"O produto «{product.get('name')}» já não está à venda.")
        quantity = _int(raw.get("quantity"), 1, minimum=1)
        if _bool(product.get("track_stock"), False) and not _bool(product.get("allow_backorder"), False):
            if quantity > _int(product.get("stock")):
                raise ValueError(f"Stock insuficiente para «{product.get('name')}» (disponível: {_int(product.get('stock'))}).")
        amounts = line_amounts(product.get("price"), quantity, product.get("tax_rate"), 0, prices_include_tax=inclusive)
        lines.append(
            {
                "id": _new_id("lin"),
                "product_id": product.get("id"),
                "name": product.get("name"),
                "sku": product.get("sku"),
                "unit": product.get("unit") or "un",
                "quantity": quantity,
                "unit_price": money(product.get("price")),
                "tax_rate": money(product.get("tax_rate")),
                "discount": money(raw.get("discount")),
                "image_url": first_image_url(product),
                "_amounts": amounts,
            }
        )
    if not lines:
        raise ValueError("O carrinho está vazio.")

    person = _normalise_person(payload.get("customer") or payload)
    if not person.get("email"):
        raise ValueError("Indique o email para receber a confirmação da encomenda.")
    raw_address = payload.get("shipping_address") if isinstance(payload.get("shipping_address"), dict) else payload.get("billing")
    if not isinstance(raw_address, dict) or not str(raw_address.get("line1") or raw_address.get("address") or "").strip():
        raise ValueError("Indique a morada de entrega (ou de faturação, nos produtos digitais).")

    subtotal = money(sum(line["_amounts"]["gross"] for line in lines))
    minimum = money(settings.get("min_order"))
    if minimum and subtotal < minimum:
        raise ValueError(f"O valor mínimo de encomenda é {minimum} €.")

    coupon: Dict[str, Any] = {}
    code = str(payload.get("coupon_code") or "").strip().upper()
    if code:
        result = validate_coupon(code, [dict(line) for line in lines], subtotal)
        if not result.get("valid"):
            raise ValueError(result.get("error") or "Cupão inválido.")
        coupon = {"id": result.get("coupon_id"), "code": code, "type": result.get("type"), "value": money(result.get("value"))}

    # Carrinho só com produtos digitais → sugere-se o método de entrega digital.
    digital_only = all(
        not _bool((_find(store, "products", str(line.get("product_id") or "")) or {}).get("track_stock"), False) for line in lines
    )
    method_id = str(payload.get("shipping_method_id") or "").strip()
    method = _find(store, "shipping", method_id) if method_id else None
    if method is None:
        candidates = [item for item in store["shipping"] if _bool(item.get("active"), True)]
        preferred = [item for item in candidates if _bool(item.get("digital"), False) is digital_only]
        method = (preferred or candidates or [None])[0]
    if method is not None:
        shipping_snapshot = {
            "id": method.get("id"),
            "name": method.get("name"),
            "price": shipping_price(method, subtotal),
            "days_min": _int(method.get("days_min")),
            "days_max": _int(method.get("days_max")),
        }
    else:
        shipping_snapshot = {"id": None, "name": "Portes a combinar", "price": 0.0, "days_min": 0, "days_max": 0}

    payment_method = str(payload.get("payment_method") or "transferencia").strip().lower()
    if payment_method not in {item["id"] for item in PAYMENT_METHODS}:
        payment_method = "transferencia"
    if not _bool((settings.get("payments") or {}).get(payment_method, True), True):
        raise ValueError(f"O método de pagamento «{payment_method}» não está disponível.")

    customer = _resolve_customer(store, payload, person, actor)
    if customer and not customer.get("crm_account_id"):
        account_id = _crm_account_for(customer)
        if account_id:
            customer["crm_account_id"] = account_id

    order = {
        "id": _new_id(ID_PREFIX["orders"]),
        "number": _generate_order_number(store),
        "status": "pendente",
        "payment": {"method": payment_method, "status": "pendente", "reference": "", "amount": 0.0, "paid_at": None, "note": "", "history": []},
        "customer_id": (customer or {}).get("id"),
        "customer": {key: person.get(key) or "" for key in ("name", "email", "phone", "tax_id", "company")},
        "billing": _normalise_address(payload.get("billing") or payload.get("shipping_address")),
        "shipping_address": _normalise_address(payload.get("shipping_address") or payload.get("billing")),
        "shipping_method_id": (method or {}).get("id"),
        "shipping_method": shipping_snapshot,
        "coupon_id": coupon.get("id"),
        "coupon_code": coupon.get("code") or "",
        "coupon": coupon or None,
        "items": [{key: value for key, value in line.items() if not key.startswith("_")} for line in lines],
        "notes": str(payload.get("notes") or ""),
        "internal_notes": "",
        "source": "loja",
        "stock_reserved": False,
        "placed_at": _now(),
        "tracking": "",
        "timeline": [{"at": _now(), "status": "pendente", "note": "Encomenda recebida na loja online", "actor": "loja"}],
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": actor,
    }
    totals = _order_totals(order, settings)
    order.update({key: value for key, value in totals.items() if key != "items_count"})
    order["items_count"] = totals["items_count"]

    # Stock: desconta agora e marca a encomenda para reposição em caso de anulação.
    for line in order["items"]:
        product = _find(store, "products", str(line.get("product_id") or ""))
        if product is None or not _bool(product.get("track_stock"), False):
            continue
        product["stock"] = _int(product.get("stock")) - _int(line.get("quantity"))
        product["updated_at"] = _now()
        order["stock_reserved"] = True

    store["orders"].insert(0, order)
    if coupon.get("code"):
        # Conta a utilização do cupão sem gravar: quem grava é o fim desta função.
        validate_coupon(coupon["code"], order["items"], totals["subtotal"], increment=True, persist=False)
    _after_write(store, "orders", order)
    _log(store, "encomenda", "orders", order, actor, f"{order['number']} · {order['total']} €")
    _write_store(store)
    return public_order_view(order, settings=settings)


def public_order_view(order: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Encomenda sem notas internas nem histórico completo (para o comprador)."""
    settings = settings or get_settings()
    payload = copy.deepcopy(order)
    payload.pop("internal_notes", None)
    payload["totals"] = _order_totals(payload, settings)
    payload["payment_label"] = PAYMENT_LABELS.get(str((payload.get("payment") or {}).get("status")), "")
    payload["status_label"] = ORDER_LABELS.get(str(payload.get("status")), "")
    instructions = (settings.get("payment_instructions") or {}).get(str((payload.get("payment") or {}).get("method") or ""), "")
    payload["payment_instructions"] = str(instructions)
    payload["currency"] = settings.get("currency") or "EUR"
    payload["store"] = {"name": settings.get("store_name"), "email": settings.get("email"), "phone": settings.get("phone")}
    return payload


def create_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Avaliação enviada na vitrine (entra sempre como pendente de moderação)."""
    doc = _normalise("reviews", {**payload, "status": "pendente"})
    product: Optional[Dict[str, Any]] = None
    if doc.get("product_id"):
        try:
            product = get_item("products", str(doc["product_id"]))
        except KeyError:
            product = None
    if product is None and payload.get("product_slug"):
        product = product_by_slug(str(payload["product_slug"]), published_only=False)
    if product is None:
        raise ValueError("Produto não encontrado.")
    if not doc.get("customer_name"):
        raise ValueError("Indique o seu nome.")
    if not _bool(get_settings().get("allow_reviews", True), True):
        raise ValueError("As avaliações estão desativadas nesta loja.")
    doc["product_id"] = product.get("id")
    doc["product_slug"] = product.get("slug")
    doc["product_name"] = product.get("name")
    store = _load()
    doc["id"] = _new_id(ID_PREFIX["reviews"])
    doc["created_at"] = _now()
    doc["updated_at"] = _now()
    store["reviews"].insert(0, doc)
    _after_write(store, "reviews", doc)
    _log(store, "avaliação", "reviews", doc, "loja", f"{product.get('name')} · {doc.get('rating')}/5")
    _write_store(store)
    return copy.deepcopy(doc)


# --------------------------------------------------------------------------
# Catálogo, panorama e pesquisa (gestão)
# --------------------------------------------------------------------------
def catalogue() -> Dict[str, Any]:
    """Tudo o que o gestor da loja precisa para desenhar o ecrã."""
    store = _load()
    settings = get_settings()
    products_index = []
    for product in store["products"]:
        products_index.append(
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "slug": product.get("slug"),
                "sku": product.get("sku"),
                "price": money(product.get("price")),
                "stock": _int(product.get("stock")),
                "status": product.get("status"),
                "type": product.get("type"),
                "image_url": first_image_url(product),
            }
        )
    categories_index = [
        {"id": category.get("id"), "name": category.get("name"), "slug": category.get("slug"), "parent_id": category.get("parent_id"), "status": category.get("status")}
        for category in sorted(store["categories"], key=lambda item: (_int(item.get("order")), str(item.get("name") or "").lower()))
    ]
    media_index: List[Dict[str, Any]] = []
    try:  # a loja reutiliza a biblioteca de media do CMS
        from api import cms_store

        media = cms_store.list_items("media", limit=400, with_blocks=False)
        media_index = [
            {
                "id": item.get("id"),
                "title": item.get("title") or item.get("filename"),
                "url": item.get("url"),
                "kind": item.get("kind"),
                "mime": item.get("mime"),
                "size": item.get("size"),
                "storage": item.get("storage"),
            }
            for item in media.get("items", [])
        ]
    except Exception as exc:  # pragma: no cover - CMS é opcional
        logger.debug("Biblioteca de media do CMS indisponível (%s)", exc)

    return {
        "product_types": PRODUCT_TYPES,
        "product_statuses": [{"id": item, "label": STATUS_LABELS[item], "style": STATUS_STYLE[item]} for item in PRODUCT_STATUSES],
        "order_statuses": [{"id": item, "label": ORDER_LABELS[item], "style": ORDER_STYLE[item], "next": ORDER_FLOW.get(item, [])} for item in ORDER_STATUSES],
        "payment_statuses": [{"id": item, "label": PAYMENT_LABELS[item], "style": PAYMENT_STYLE[item]} for item in PAYMENT_STATUSES],
        "payment_methods": PAYMENT_METHODS,
        "coupon_types": COUPON_TYPES,
        "review_statuses": [{"id": item, "label": REVIEW_LABELS[item], "style": REVIEW_STYLE[item]} for item in REVIEW_STATUSES],
        "customer_statuses": [{"id": item, "label": CUSTOMER_LABELS[item]} for item in CUSTOMER_STATUSES],
        "units": PRODUCT_UNITS,
        "sort_options": SORT_OPTIONS,
        "entities": list(ENTITIES),
        "products_index": products_index,
        "categories_index": categories_index,
        "customers_index": [
            {"id": item.get("id"), "name": item.get("name"), "email": item.get("email"), "orders_count": _int(item.get("orders_count"))}
            for item in sorted(store["customers"], key=lambda item: str(item.get("name") or "").lower())
        ],
        "shipping_index": [
            {"id": item.get("id"), "name": item.get("name"), "price": money(item.get("price")), "active": _bool(item.get("active"), True)}
            for item in sorted(store["shipping"], key=lambda item: (_int(item.get("order")), money(item.get("price"))))
        ],
        "coupons_index": [
            {"id": item.get("id"), "code": item.get("code"), "type": item.get("type"), "value": money(item.get("value")), "active": _bool(item.get("active"), True)}
            for item in store["coupons"]
        ],
        "media_index": media_index,
        "settings": settings,
        "store_url": "/loja",
        "cart_url": "/loja/carrinho",
        "products_url": "/loja/produtos",
    }


def overview() -> Dict[str, Any]:
    """Panorama da loja: vendas, encomendas por estado, stock e atividade."""
    store = _load()
    settings = get_settings()
    threshold = _int(settings.get("low_stock_threshold"), 5)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def stamp_of(order: Dict[str, Any]) -> datetime:
        try:
            value = datetime.fromisoformat(str(order.get("placed_at") or order.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            return now - timedelta(days=3650)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    orders_by_status = {status: 0 for status in ORDER_STATUSES}
    revenue_total = 0.0
    revenue_month = 0.0
    revenue_pending = 0.0
    paid_orders = 0
    units_sold: Dict[str, int] = {}
    revenue_by_product: Dict[str, float] = {}
    sales_by_day: Dict[str, float] = {}
    for order in store["orders"]:
        status = str(order.get("status") or "pendente")
        if status in orders_by_status:
            orders_by_status[status] += 1
        payment_status = str((order.get("payment") or {}).get("status") or "pendente")
        total = money(order.get("total"))
        if payment_status == "pago":
            revenue_total = money(revenue_total + total)
            paid_orders += 1
            placed = stamp_of(order)
            if placed >= month_start:
                revenue_month = money(revenue_month + total)
            day = placed.strftime("%Y-%m-%d")
            sales_by_day[day] = money(sales_by_day.get(day, 0.0) + total)
        elif status not in ORDER_CLOSED_LOST:
            revenue_pending = money(revenue_pending + total)
        if status not in ORDER_CLOSED_LOST:
            for line in order.get("items") or []:
                product_id = str(line.get("product_id") or "")
                units_sold[product_id] = units_sold.get(product_id, 0) + _int(line.get("quantity"))
                revenue_by_product[product_id] = money(revenue_by_product.get(product_id, 0.0) + money(line.get("unit_price")) * _int(line.get("quantity")))

    low_stock = []
    out_of_stock = []
    for product in store["products"]:
        if not _bool(product.get("track_stock"), False):
            continue
        quantity = _int(product.get("stock"))
        entry = {"id": product.get("id"), "name": product.get("name"), "sku": product.get("sku"), "stock": quantity, "status": product.get("status")}
        if quantity <= 0:
            out_of_stock.append(entry)
        elif quantity <= max(threshold, _int(product.get("stock_min"))):
            low_stock.append(entry)
    low_stock.sort(key=lambda item: item["stock"])

    top_products = []
    for product_id, units in sorted(units_sold.items(), key=lambda item: -item[1])[:6]:
        product = _find(store, "products", product_id)
        top_products.append(
            {
                "id": product_id,
                "name": (product or {}).get("name") or "(produto apagado)",
                "sku": (product or {}).get("sku") or "",
                "units": units,
                "revenue": money(revenue_by_product.get(product_id, 0.0)),
                "image_url": first_image_url(product or {}),
            }
        )

    recent_orders = [
        {
            "id": order.get("id"),
            "number": order.get("number"),
            "customer": (order.get("customer") or {}).get("name") or (order.get("customer") or {}).get("email"),
            "total": money(order.get("total")),
            "status": order.get("status"),
            "payment_status": (order.get("payment") or {}).get("status"),
            "at": order.get("placed_at") or order.get("created_at"),
        }
        for order in sorted(store["orders"], key=lambda item: str(item.get("placed_at") or item.get("created_at") or ""), reverse=True)[:8]
    ]

    pending_reviews = [review for review in store["reviews"] if review.get("status") == "pendente"]
    series = []
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        series.append({"day": day, "revenue": money(sales_by_day.get(day, 0.0))})

    average = money(revenue_total / paid_orders) if paid_orders else 0.0
    return {
        "revenue": {"total": revenue_total, "month": revenue_month, "pending": revenue_pending, "average_ticket": average, "paid_orders": paid_orders},
        "orders": {
            "total": len(store["orders"]),
            "by_status": orders_by_status,
            "pending": orders_by_status.get("pendente", 0),
            "open": sum(orders_by_status.get(status, 0) for status in ("pendente", "pago", "em_preparacao", "enviado")),
        },
        "products": {
            "total": len(store["products"]),
            "published": len([item for item in store["products"] if item.get("status") == "publicado"]),
            "drafts": len([item for item in store["products"] if item.get("status") == "rascunho"]),
            "featured": len([item for item in store["products"] if _bool(item.get("featured"), False)]),
            "low_stock": low_stock[:8],
            "out_of_stock": out_of_stock[:8],
        },
        "customers": {
            "total": len(store["customers"]),
            "new_month": len([item for item in store["customers"] if str(item.get("created_at") or "") >= month_start.isoformat()]),
            "top": [
                {"id": item.get("id"), "name": item.get("name"), "email": item.get("email"), "spent": money(item.get("total_spent")), "orders": _int(item.get("orders_count"))}
                for item in sorted(store["customers"], key=lambda item: -money(item.get("total_spent")))[:5]
            ],
        },
        "coupons": {
            "total": len(store["coupons"]),
            "active": len([item for item in store["coupons"] if _bool(item.get("active"), True)]),
            "uses": sum(_int(item.get("uses")) for item in store["coupons"]),
        },
        "reviews": {
            "total": len(store["reviews"]),
            "pending": len(pending_reviews),
            "approved": len([item for item in store["reviews"] if item.get("status") == "aprovada"]),
            "average": money(sum(_int(item.get("rating")) for item in store["reviews"]) / len(store["reviews"])) if store["reviews"] else 0.0,
        },
        "shipping": len([item for item in store["shipping"] if _bool(item.get("active"), True)]),
        "top_products": top_products,
        "recent_orders": recent_orders,
        "series": series,
        "activity": store["activity"][:12],
        "store": {"url": "/loja", "cart_url": "/loja/carrinho", "settings": settings},
    }


def search(query: str, limit: int = 30) -> Dict[str, Any]:
    """Pesquisa global na loja (produtos, encomendas, clientes, cupões e avaliações)."""
    needle = (query or "").strip().lower()
    if not needle:
        return {"query": query, "total": 0, "items": []}
    store = _load()
    hits: List[Dict[str, Any]] = []
    for entity in ("products", "orders", "customers", "coupons", "reviews", "categories", "shipping"):
        for doc in store[entity]:
            haystack = " ".join(
                str(doc.get(field) or "")
                for field in ("name", "title", "slug", "sku", "number", "code", "email", "description", "short_description", "notes", "body", "internal_notes", "zone")
            ).lower()
            haystack += " " + " ".join(str((doc.get("customer") or {}).get(field) or "") for field in ("name", "email"))
            haystack += " " + " ".join(str(value) for value in (doc.get("tags") or []))
            # Encomendas: o método de pagamento e o envio também são pesquisáveis
            # («mbway», «correio registado»), tal como o número e o cliente.
            if entity == "orders":
                haystack += " " + str((doc.get("payment") or {}).get("method") or "")
                haystack += " " + str((doc.get("shipping_method") or {}).get("name") or "")
            if needle not in haystack:
                continue
            hits.append(
                {
                    "entity": entity,
                    "id": doc.get("id"),
                    "title": doc.get("name") or doc.get("number") or doc.get("code") or doc.get("title") or "",
                    "subtitle": doc.get("sku") or doc.get("email") or doc.get("slug") or "",
                    "status": doc.get("status") or ("ativo" if _bool(doc.get("active"), True) else "inativo"),
                    "updated_at": doc.get("updated_at") or doc.get("created_at") or "",
                }
            )
    hits.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"query": query, "total": len(hits), "items": hits[:limit]}


def link_customer_to_crm(customer_id: str, account_id: Optional[str] = None, author: str = "") -> Dict[str, Any]:
    """Liga (ou cria) a conta de CRM de um cliente da loja."""
    store = _load()
    customer = _find(store, "customers", customer_id)
    if customer is None:
        raise KeyError(f"Cliente {customer_id} não encontrado.")
    account = str(account_id or "").strip()
    if not account:
        account = _crm_account_for(customer)
    if not account:
        raise ValueError("Não foi possível criar a conta no CRM (módulo indisponível).")
    customer["crm_account_id"] = account
    customer["updated_at"] = _now()
    _log(store, "crm", "customers", customer, author, f"conta {account}")
    _write_store(store)
    return get_item("customers", customer_id)


def reset_seed() -> Dict[str, Any]:
    """Repõe o conteúdo de demonstração da loja (apaga o que existir)."""
    global _cache, _cache_mtime
    with _lock:
        store = _empty_store()
        _seed(store)
        _write_store(store)
        _cache = store
        _cache_mtime = _file_mtime()
    return {"reset": True, "products": len(store["products"]), "orders": len(store["orders"])}


# --------------------------------------------------------------------------
# Conteúdo de demonstração
# --------------------------------------------------------------------------
def _seed(store: Dict[str, Any]) -> None:
    """Catálogo, clientes e encomendas de exemplo (para a loja não nascer vazia)."""
    settings = store["settings"]
    settings["email"] = "loja@iqos.pt"
    settings["phone"] = "+351 210 000 000"
    settings["address"] = "Av. da Liberdade 100, 1250-146 Lisboa"
    settings["tax_id"] = "500 000 000"

    categories = [
        ("Relatórios", "relatorios", "Relatórios prontos a usar sobre contratos, empresas e mercados.", True, 1),
        ("Dossiês de empresa", "dossies-de-empresa", "Dossiês completos com contratação, contas e riscos.", True, 2),
        ("Dados e API", "dados-e-api", "Acesso a dados normalizados e à API da plataforma.", False, 3),
        ("Formação", "formacao", "Sessões de formação e acompanhamento especializado.", False, 4),
    ]
    for name, slug, description, featured, order in categories:
        store["categories"].append(
            {
                "id": _new_id("cat"),
                "name": name,
                "slug": slug,
                "description": description,
                "parent_id": None,
                "status": "publicado",
                "featured": featured,
                "order": order,
                "image_id": None,
                "image_url": "",
                "seo": {"title": "", "description": "", "keywords": [], "noindex": False},
                "created_at": _now(),
                "updated_at": _now(),
                "updated_by": "plataforma",
            }
        )
    by_slug = {category["slug"]: category["id"] for category in store["categories"]}

    products = [
        {
            "name": "Relatório de contratação pública — Portugal",
            "slug": "relatorio-contratacao-publica-portugal",
            "sku": "REL-CP-PT",
            "category_ids": [by_slug["relatorios"]],
            "short_description": "Panorama do último trimestre: adjudicantes, valores e concorrência, com séries prontas a apresentar.",
            "description": "## O que inclui\n\n- Top 50 adjudicantes e adjudicatários do período\n- Concentração por CPV e por distrito\n- Séries temporais comparáveis\n- Ficheiro XLSX e PDF, com nota metodológica\n\nAtualizado a cada trimestre.",
            "price": 249.0,
            "compare_at_price": 320.0,
            "tax_rate": 23.0,
            "type": "digital",
            "status": "publicado",
            "featured": True,
            "order": 1,
            "track_stock": False,
            "stock": 0,
            "tags": ["contratos", "relatório", "trimestral"],
            "attributes": [
                {"label": "Formato", "value": "PDF + XLSX"},
                {"label": "Periodicidade", "value": "Trimestral"},
                {"label": "Atualização", "value": "12 meses"},
            ],
        },
        {
            "name": "Dossiê de empresa — investigação completa",
            "slug": "dossie-de-empresa",
            "sku": "DOS-EMP",
            "category_ids": [by_slug["dossies-de-empresa"]],
            "short_description": "Um dossiê de 30 a 50 páginas sobre uma empresa: contratos, sócios, contas, insolvências e reputação.",
            "description": "Pedido à medida: investigamos a empresa, cruzamos registos públicos e entregamos um dossiê pronto a decidir.\n\n**Prazo:** 5 dias úteis.\n\nInclui sessão de apresentação de 1 hora.",
            "price": 780.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "servico",
            "status": "publicado",
            "featured": True,
            "order": 2,
            "track_stock": False,
            "stock": 0,
            "tags": ["due diligence", "dossiê"],
            "attributes": [
                {"label": "Prazo", "value": "5 dias úteis"},
                {"label": "Extensão", "value": "30–50 páginas"},
                {"label": "Sessão", "value": "1 hora incluída"},
            ],
        },
        {
            "name": "Assinatura IQ OS — Analista (mensal)",
            "slug": "assinatura-analista",
            "sku": "SUB-ANL",
            "category_ids": [by_slug["dados-e-api"]],
            "short_description": "Acesso mensal à plataforma: pesquisa 360, dossiês, grafo de entidades e exportações.",
            "description": "Subscrição mensal, sem fidelização.\n\n- 3 utilizadores\n- Exportações ilimitadas\n- Recarga de investigações incluída",
            "price": 149.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "digital",
            "status": "publicado",
            "featured": True,
            "order": 3,
            "track_stock": False,
            "stock": 0,
            "tags": ["subscrição", "plataforma"],
            "attributes": [
                {"label": "Utilizadores", "value": "3"},
                {"label": "Fidelização", "value": "Sem fidelização"},
            ],
        },
        {
            "name": "Créditos de investigação (pacote 25)",
            "slug": "creditos-investigacao-25",
            "sku": "CRE-25",
            "category_ids": [by_slug["dados-e-api"]],
            "short_description": "25 investigações assistidas para usar quando precisar, sem prazo de validade.",
            "description": "Cada crédito dá direito a uma investigação assistida (Hermes) com evidências citadas.\n\nOs créditos não caducam e são acumuláveis.",
            "price": 290.0,
            "compare_at_price": 375.0,
            "tax_rate": 23.0,
            "type": "digital",
            "status": "publicado",
            "featured": False,
            "order": 4,
            "track_stock": False,
            "stock": 0,
            "tags": ["créditos", "investigação"],
            "attributes": [{"label": "Validade", "value": "Sem limite"}],
        },
        {
            "name": "Formação — Contratação pública em 1 dia",
            "slug": "formacao-contratacao-publica",
            "sku": "FRM-CP1",
            "category_ids": [by_slug["formacao"]],
            "short_description": "Formação intensiva, presencial ou online, para equipas comerciais e de compras.",
            "description": "Programa de 8 horas (ou 2 manhãs):\n\n1. Onde está a oportunidade\n2. Como ler um anúncio\n3. Preparar proposta e preço\n4. Casos reais dos participantes",
            "price": 420.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "servico",
            "status": "publicado",
            "featured": False,
            "order": 5,
            "track_stock": True,
            "stock": 6,
            "stock_min": 2,
            "unit": "h",
            "tags": ["formação", "contratação"],
            "attributes": [
                {"label": "Duração", "value": "8 horas"},
                {"label": "Turma", "value": "até 12 pessoas"},
            ],
        },
        {
            "name": "Relatório de mercados — Iberia mensal",
            "slug": "relatorio-mercados-iberia",
            "sku": "REL-MKT-IB",
            "category_ids": [by_slug["relatorios"]],
            "short_description": "Síntese mensal dos mercados ibéricos: setores, cotações e notícias que mexeram com o mês.",
            "description": "12 páginas por mês, com leitura de 15 minutos e gráficos prontos a reutilizar.",
            "price": 89.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "digital",
            "status": "publicado",
            "featured": False,
            "order": 6,
            "track_stock": False,
            "stock": 0,
            "tags": ["mercados", "ibéria"],
            "attributes": [{"label": "Periodicidade", "value": "Mensal"}],
        },
        {
            "name": "Manual impresso — Inteligência de contratos",
            "slug": "manual-inteligencia-contratos",
            "sku": "MAN-ICP",
            "category_ids": [by_slug["formacao"]],
            "short_description": "Edição impressa de 180 páginas, com fichas de trabalho destacáveis.",
            "description": "Manual de referência para equipas que trabalham contratos públicos, com exemplos do mercado português.",
            "price": 45.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "fisico",
            "status": "publicado",
            "featured": False,
            "order": 7,
            "track_stock": True,
            "stock": 4,
            "stock_min": 5,
            "weight_kg": 0.6,
            "length_cm": 24.0,
            "width_cm": 17.0,
            "height_cm": 2.0,
            "tags": ["manual", "impresso"],
            "attributes": [{"label": "Páginas", "value": "180"}],
        },
        {
            "name": "Dossiê de mercado — setor à escolha",
            "slug": "dossie-de-mercado",
            "sku": "DOS-MKT",
            "category_ids": [by_slug["dossies-de-empresa"]],
            "short_description": "Estudo de um setor: dimensão, operadores, contratos e tendências.",
            "description": "Escolha o setor (CPV ou CAE) e recebemos um estudo com os principais operadores, quota de contratação e evolução.",
            "price": 640.0,
            "compare_at_price": 0,
            "tax_rate": 23.0,
            "type": "servico",
            "status": "publicado",
            "featured": False,
            "order": 8,
            "track_stock": False,
            "stock": 0,
            "tags": ["mercado", "setor"],
            "attributes": [{"label": "Prazo", "value": "7 dias úteis"}],
        },
        {
            "name": "Mala de arquivo IQ OS",
            "slug": "mala-de-arquivo",
            "sku": "MAL-ARQ",
            "category_ids": [by_slug["formacao"]],
            "short_description": "Mala de arquivo com lombada, para guardar dossiês impressos.",
            "description": "Capa rígida, fecho elástico e etiqueta para identificar o processo.",
            "price": 19.9,
            "compare_at_price": 24.9,
            "tax_rate": 23.0,
            "type": "fisico",
            "status": "rascunho",
            "featured": False,
            "order": 9,
            "track_stock": True,
            "stock": 25,
            "weight_kg": 0.4,
            "tags": ["acessório"],
            "attributes": [{"label": "Cor", "value": "Preto"}],
        },
    ]
    for index, product in enumerate(products):
        doc = _normalise("products", product)
        doc["id"] = _new_id("prd")
        doc["sku"] = _sku_for(store, doc)
        doc["slug"] = _unique(store, "products", str(doc["slug"]))
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        doc["updated_by"] = "plataforma"
        doc["published_at"] = _now() if doc.get("status") == "publicado" else None
        doc["rating_avg"] = 0.0
        doc["rating_count"] = 0
        store["products"].append(doc)

    shipping = [
        {"name": "Correio registado", "description": "Entrega em 3 a 5 dias úteis.", "price": 4.9, "free_above": 60.0, "days_min": 3, "days_max": 5, "zone": "Portugal Continental", "order": 2},
        {"name": "Entrega digital", "description": "Acesso imediato após confirmação do pagamento.", "price": 0.0, "free_above": 0.0, "days_min": 0, "days_max": 0, "zone": "Online", "digital": True, "order": 1},
        {"name": "Recolha na agência", "description": "Levantamento em Lisboa (Av. da Liberdade).", "price": 0.0, "free_above": 0.0, "days_min": 1, "days_max": 2, "zone": "Lisboa", "order": 3},
    ]
    for method in shipping:
        doc = _normalise("shipping", method)
        doc["id"] = _new_id("env")
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        doc["updated_by"] = "plataforma"
        store["shipping"].append(doc)

    coupons = [
        {"code": "BEMVINDO10", "type": "percentagem", "value": 10.0, "description": "10% na primeira encomenda.", "min_subtotal": 50.0, "active": True, "max_uses": 200},
        {"code": "PORTES2026", "type": "portes_gratis", "value": 0.0, "description": "Portes grátis em 2026.", "min_subtotal": 30.0, "active": True, "max_uses": 0},
    ]
    for coupon in coupons:
        doc = _normalise("coupons", coupon)
        doc["id"] = _new_id("cup")
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        doc["updated_by"] = "plataforma"
        store["coupons"].append(doc)

    customers = [
        {"name": "Ana Ribeiro", "email": "ana.ribeiro@exemplo.pt", "phone": "+351 912 000 001", "tax_id": "123456789", "company": "Ribeiro & Filhos, Lda.", "billing": {"line1": "Rua do Comércio 12", "postal_code": "1100-148", "city": "Lisboa"}, "shipping_address": {"line1": "Rua do Comércio 12", "postal_code": "1100-148", "city": "Lisboa"}},
        {"name": "Carlos Mendes", "email": "carlos.mendes@exemplo.pt", "phone": "+351 913 000 002", "company": "Mendes Consultores", "billing": {"line1": "Av. dos Aliados 45", "postal_code": "4000-064", "city": "Porto"}, "shipping_address": {"line1": "Av. dos Aliados 45", "postal_code": "4000-064", "city": "Porto"}},
        {"name": "Sofia Lopes", "email": "sofia.lopes@exemplo.pt", "phone": "+351 914 000 003", "billing": {"line1": "Rua da Sofia 8", "postal_code": "3000-390", "city": "Coimbra"}, "shipping_address": {"line1": "Rua da Sofia 8", "postal_code": "3000-390", "city": "Coimbra"}},
    ]
    for customer in customers:
        doc = _normalise("customers", customer)
        doc["id"] = _new_id("cli")
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        doc["updated_by"] = "plataforma"
        doc["orders_count"] = 0
        doc["total_spent"] = 0.0
        store["customers"].append(doc)

    by_sku = {product["sku"]: product for product in store["products"]}
    digital_method = next((item for item in store["shipping"] if item.get("digital")), store["shipping"][0])
    physical_method = next((item for item in store["shipping"] if not item.get("digital")), store["shipping"][0])
    demos = [
        {
            "customer": store["customers"][0],
            "status": "entregue",
            "payment": {"method": "transferencia", "status": "pago", "amount": 249.0},
            "shipping": digital_method,
            "items": [("REL-CP-PT", 1)],
            "days_ago": 26,
        },
        {
            "customer": store["customers"][1],
            "status": "enviado",
            "payment": {"method": "mbway", "status": "pago", "amount": 780.0},
            "shipping": physical_method,
            "coupon": "BEMVINDO10",
            "items": [("DOS-EMP", 1)],
            "days_ago": 9,
        },
        {
            "customer": store["customers"][2],
            "status": "pendente",
            "payment": {"method": "multibanco", "status": "pendente", "amount": 0.0},
            "shipping": physical_method,
            "items": [("MAN-ICP", 2), ("FRM-CP1", 1)],
            "days_ago": 3,
        },
        {
            "customer": store["customers"][0],
            "status": "pago",
            "payment": {"method": "cartao", "status": "pago", "amount": 149.0},
            "shipping": digital_method,
            "items": [("SUB-ANL", 1)],
            "days_ago": 1,
        },
    ]
    for demo in demos:
        customer = demo["customer"]
        items = []
        for sku, quantity in demo["items"]:
            product = by_sku.get(sku)
            if product is None:
                continue
            items.append(
                {
                    "id": _new_id("lin"),
                    "product_id": product["id"],
                    "name": product["name"],
                    "sku": product["sku"],
                    "unit": product.get("unit") or "un",
                    "quantity": quantity,
                    "unit_price": money(product.get("price")),
                    "tax_rate": money(product.get("tax_rate")),
                    "discount": 0.0,
                    "image_url": "",
                }
            )
        placed = (datetime.now(timezone.utc) - timedelta(days=demo["days_ago"], hours=3)).isoformat()
        items_total = money(sum(money(item["unit_price"]) * _int(item["quantity"]) for item in items))
        coupon_code = str(demo.get("coupon") or "")
        coupon = next((item for item in store["coupons"] if str(item.get("code")) == coupon_code), None) if coupon_code else None
        order = {
            "number": "",
            "status": demo["status"],
            "payment": {**demo["payment"], "history": [], "paid_at": placed if demo["payment"]["status"] == "pago" else None, "reference": "", "note": ""},
            "customer_id": customer["id"],
            "customer": {"name": customer["name"], "email": customer["email"], "phone": customer["phone"], "tax_id": customer.get("tax_id") or "", "company": customer.get("company") or ""},
            "billing": customer["billing"],
            "shipping_address": customer["shipping_address"],
            "shipping_method_id": demo["shipping"]["id"],
            "shipping_method": {
                "id": demo["shipping"]["id"],
                "name": demo["shipping"]["name"],
                # O mesmo cálculo do checkout: acima do limite de portes grátis, é zero.
                "price": shipping_price(demo["shipping"], items_total),
                "days_min": _int(demo["shipping"]["days_min"]),
                "days_max": _int(demo["shipping"]["days_max"]),
            },
            "coupon_id": (coupon or {}).get("id"),
            "coupon_code": coupon_code,
            "items": items,
            "notes": "",
            "internal_notes": "",
            "source": "loja",
            "placed_at": placed,
            "tracking": "",
            "timeline": [{"at": placed, "status": "pendente", "note": "Encomenda recebida na loja online", "actor": "loja"}],
            "created_at": placed,
            "updated_at": placed,
            "updated_by": "plataforma",
        }
        doc = _normalise("orders", order, None, store)
        doc["id"] = _new_id("enc")
        doc["number"] = _generate_order_number(store)
        totals = _order_totals(doc, settings)
        doc.update({key: value for key, value in totals.items() if key != "items_count"})
        doc["items_count"] = totals["items_count"]
        if coupon is not None:
            coupon["uses"] = _int(coupon.get("uses")) + 1
        if doc["status"] != "pendente":
            doc["timeline"] = list(doc["timeline"]) + [{"at": placed, "status": doc["status"], "note": "Estado definido no conteúdo de exemplo", "actor": "plataforma"}]
        store["orders"].append(doc)

    reviews = [
        ("REL-CP-PT", "Ana Ribeiro", 5, "Muito completo", "Cruzámos o relatório com a nossa base e bate tudo. O XLSX poupou-nos dias de trabalho."),
        ("REL-CP-PT", "Carlos Mendes", 4, "Bom, mas queria mais detalhe", "Excelente panorama; gostava de ver também as prorrogações por concelho."),
        ("DOS-EMP", "Sofia Lopes", 5, "Decisão tomada com confiança", "O dossiê trouxe coisas que não encontrávamos: insolvências de fornecedores e ligações societárias."),
        ("MAN-ICP", "Ana Ribeiro", 4, "Útil no dia a dia", "Fichas de trabalho muito práticas. A capa podia ser mais resistente."),
    ]
    for sku, who, rating, title, body in reviews:
        product = by_sku.get(sku)
        if product is None:
            continue
        doc = _normalise(
            "reviews",
            {"product_id": product["id"], "customer_name": who, "rating": rating, "title": title, "body": body, "status": "aprovada"},
        )
        doc["id"] = _new_id("avl")
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        doc["updated_by"] = "plataforma"
        store["reviews"].append(doc)
    doc = _normalise(
        "reviews",
        {"product_id": by_sku["SUB-ANL"]["id"], "customer_name": "João Cunha", "rating": 5, "title": "Vale o preço", "body": "Em duas semanas encontrámos três oportunidades que não conhecíamos.", "status": "pendente"},
    )
    doc["id"] = _new_id("avl")
    doc["created_at"] = _now()
    doc["updated_at"] = _now()
    doc["updated_by"] = "plataforma"
    store["reviews"].append(doc)

    _refresh_ratings(store)
    _refresh_customer_stats(store)
    _log(store, "conteúdo", "settings", {"id": "settings", "name": "Loja de demonstração"}, "plataforma", "conteúdo inicial")
