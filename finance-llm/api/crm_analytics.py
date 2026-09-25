"""Analytics do CRM e ações de inteligência sobre os dados de venda e operação.

Responde a três perguntas de negócio — **vendas**, **clientes** e **operações** —
e fecha o ciclo «perceção → ação» do CRM:

```
Contas · Produtos · Encomendas · Linhas · Ordens de trabalho · Oportunidades
                                │
                                ▼
                    analytics (agregações reais)
                                │
                ┌───────────────┴────────────────┐
                ▼                                ▼
        painel de analytics          agente de IA (perguntas/ações)
                │                                │
                └───────────────► ação no CRM ◄──┘
                          (criar oportunidades)
```

Tudo é calculado a partir dos registos reais do CRM (nada é inventado) e dentro
do âmbito do perfil: as contas, encomendas e linhas que o utilizador não pode ler
não entram em nenhum número. O motor agrega em Python sobre uma leitura limitada
(os volumes de um CRM são de milhares, não de milhões) e expõe os limites de
leitura para que um dia possam ser substituídos por agregações do Elasticsearch.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from api import crm_registry as registry
from api import crm_suite as suite

logger = logging.getLogger(__name__)

# Limites de leitura (o CRM agrega em memória; estes tetos mantêm a resposta rápida).
MAX_ORDERS = 4000
MAX_LINES = 8000
MAX_PRODUCTS = 1000
MAX_ACCOUNTS = 2000
MAX_WORK_ORDERS = 4000
MAX_OPPORTUNITIES = 2000
MAX_CREATE = 25

# Estados das encomendas por significado de negócio.
STATUS_FATURADA = ("faturada",)
STATUS_REALIZADA = ("confirmada", "em-producao", "enviada", "faturada")
STATUS_ABERTA = ("rascunho", "aguarda-aprovacao", "confirmada", "em-producao", "enviada")
# Estados das ordens de trabalho considerados "em curso".
WORK_OPEN = ("aberta", "planeada", "em-curso", "aguarda-pecas", "aguarda-cliente")
WORK_DONE = ("concluida",)

DEFAULT_MONTHS = 12
DEFAULT_DAYS_WITHOUT_PURCHASE = 90


# ------------------------------------------------------------------ utilitários
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _moment(value: Any) -> Optional[datetime]:
    """Converte uma data ISO (com ou sem fuso) num `datetime` com fuso."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _money(value: float) -> float:
    return round(float(value or 0.0), 2)


def _eur(value: Any) -> str:
    """Valor em euros no formato português (10 000,00 €)."""
    text = f"{_number(value):,.2f}"
    return text.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".") + " €"


def _pct_text(value: Any) -> str:
    """Percentagem sem casas decimais desnecessárias (40%, 12,5%)."""
    return _num_text(value) + "\u00a0%"


def _num_text(value: Any, decimals: int = 1) -> str:
    """Número com vírgula decimal, sem casas decimais desnecessárias (30, 12,5)."""
    text = f"{_number(value):.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100.0, 1) if whole else 0.0


def _fold(text: Any) -> str:
    """Texto sem acentos, minúsculas e espaços colapsados (para comparar nomes)."""
    raw = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip().lower()


def _month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


# --------------------------------------------------------------------- leitura
def _read(slug: str, perm: Dict[str, Any], size: int) -> List[Dict[str, Any]]:
    """Lê um módulo dentro do âmbito do perfil (vazio quando não tem acesso)."""
    module = registry.MODULE_BY_SLUG.get(slug)
    if module is None or not suite.can_read(perm, slug):
        return []
    listed = suite.list_module(module, perm, size=min(size, suite.MAX_SIZE))
    items: List[Dict[str, Any]] = list(listed.get("items") or [])
    total = _int(listed.get("total"))
    if total > len(items):
        listed = suite.list_module(module, perm, size=suite.MAX_SIZE)
        items = list(listed.get("items") or [])
        if total > len(items):
            logger.info("CRM analytics: %s limitado a %d de %d registos", slug, len(items), total)
    return items


def dataset(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Conjunto de dados base das análises (já filtrado pelo âmbito do perfil)."""
    return {
        "orders": _read("orders", perm, MAX_ORDERS),
        "lines": _read("order-lines", perm, MAX_LINES),
        "products": _read("products", perm, MAX_PRODUCTS),
        "suppliers": _read("suppliers", perm, MAX_PRODUCTS),
        "accounts": _read("accounts", perm, MAX_ACCOUNTS),
        "work_orders": _read("work-orders", perm, MAX_WORK_ORDERS),
        "opportunities": _read("opportunities", perm, MAX_OPPORTUNITIES),
    }


def _index(items: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(item.get("id")): item for item in items if item.get("id")}


def _by(records: Iterable[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        value = str(record.get(key) or "")
        if value:
            grouped.setdefault(value, []).append(record)
    return grouped


def _rank(values: Dict[str, Dict[str, Any]], field: str, top: int) -> List[Dict[str, Any]]:
    rows = list(values.values())
    rows.sort(key=lambda row: row.get(field) or 0, reverse=True)
    return rows[:top]


# ------------------------------------------------------------------- vendas
def _revenue_blocks(data: Dict[str, Any], *, months: int, top: int) -> Dict[str, Any]:
    since = _now() - timedelta(days=31 * months)
    products = _index(data["products"])
    accounts = _index(data["accounts"])

    window = [order for order in data["orders"] if (_moment(order.get("order_date")) or _now()) >= since]
    without_date = len(data["orders"]) - len([o for o in data["orders"] if _moment(o.get("order_date"))])
    realized = [order for order in window if str(order.get("status")) in STATUS_REALIZADA]
    billed = [order for order in window if str(order.get("status")) in STATUS_FATURADA]
    pending = [order for order in window if str(order.get("status")) in STATUS_ABERTA]

    realized_ids = {str(order.get("id")) for order in realized}
    realized_lines = [line for line in data["lines"] if str(line.get("order_id")) in realized_ids]

    by_account: Dict[str, Dict[str, Any]] = {}
    for order in realized:
        key = str(order.get("account_id") or "sem-conta")
        row = by_account.setdefault(
            key,
            {
                "account_id": key,
                "name": (accounts.get(key) or {}).get("name") or "Sem conta",
                "revenue": 0.0,
                "orders": 0,
                "last_order": "",
            },
        )
        row["revenue"] += _number(order.get("total"))
        row["orders"] += 1
        stamp = str(order.get("order_date") or "")[:10]
        if stamp > row["last_order"]:
            row["last_order"] = stamp
    for row in by_account.values():
        row["revenue"] = _money(row["revenue"])
        row["ticket_medio"] = _money(row["revenue"] / row["orders"]) if row["orders"] else 0.0

    by_product: Dict[str, Dict[str, Any]] = {}
    by_seller: Dict[str, Dict[str, Any]] = {}
    by_month: Dict[str, Dict[str, Any]] = {}
    margin_total = 0.0
    for line in realized_lines:
        if str(line.get("status")) == "cancelada":
            continue
        quantity = _number(line.get("quantity"))
        revenue = _number(line.get("line_total"))
        cost = _number(line.get("unit_cost")) * quantity
        margin = revenue - cost
        margin_total += margin

        product_id = str(line.get("product_id") or "")
        key = product_id or "sem-produto"
        row = by_product.setdefault(
            key,
            {
                "product_id": key,
                "name": (products.get(key) or {}).get("name") or str(line.get("description") or "Sem produto"),
                "category": (products.get(key) or {}).get("category") or "",
                "revenue": 0.0,
                "units": 0.0,
                "margin": 0.0,
            },
        )
        row["revenue"] += revenue
        row["units"] += quantity
        row["margin"] += margin

    for order in realized:
        seller = str(order.get("owner_email") or "sem-responsavel")
        row = by_seller.setdefault(seller, {"owner": seller, "revenue": 0.0, "orders": 0})
        row["revenue"] += _number(order.get("total"))
        row["orders"] += 1

        moment = _moment(order.get("order_date"))
        if moment:
            month = by_month.setdefault(_month_key(moment), {"month": _month_key(moment), "revenue": 0.0, "orders": 0})
            month["revenue"] += _number(order.get("total"))
            month["orders"] += 1

    for row in by_product.values():
        row["revenue"] = _money(row["revenue"])
        row["margin"] = _money(row["margin"])
        row["margin_pct"] = _pct(row["margin"], row["revenue"])
    for row in by_seller.values():
        row["revenue"] = _money(row["revenue"])
        row["ticket_medio"] = _money(row["revenue"] / row["orders"]) if row["orders"] else 0.0
    for row in by_month.values():
        row["revenue"] = _money(row["revenue"])

    revenue_realized = _money(sum(_number(order.get("total")) for order in realized))
    revenue_billed = _money(sum(_number(order.get("total")) for order in billed))
    open_value = _money(sum(_number(order.get("total")) for order in pending))
    revenue_lines = _money(sum(row["revenue"] for row in by_product.values()))
    margin_base = revenue_lines or revenue_realized

    months_list = sorted(by_month.values(), key=lambda row: row["month"])

    return {
        "filtros": {"meses": months, "desde": since.date().isoformat(), "encomendas_sem_data": without_date},
        "receita": {
            "realizada": revenue_realized,
            "faturada": revenue_billed,
            "em_aberto": open_value,
            "encomendas": len(realized),
            "encomendas_em_aberto": len(pending),
            "ticket_medio": _money(revenue_realized / len(realized)) if realized else 0.0,
            "margem": _money(margin_total),
            "margem_pct": _pct(margin_total, margin_base),
            "variacao_periodo_pct": _growth(by_month, months),
        },
        "por_cliente": _rank(by_account, "revenue", top),
        "por_produto": _rank(by_product, "revenue", top),
        "por_vendedor": _rank(by_seller, "revenue", top),
        "por_periodo": months_list,
        "mais_vendidos": sorted(by_product.values(), key=lambda row: row["units"], reverse=True)[:top],
    }


def _growth(by_month: Dict[str, Dict[str, Any]], months: int) -> Optional[float]:
    """Variação da receita nos últimos N meses face aos N anteriores."""
    if not by_month:
        return None
    ordered = sorted(by_month.values(), key=lambda row: row["month"])
    half = max(1, min(months, 6))
    recent = sum(row["revenue"] for row in ordered[-half:])
    previous = sum(row["revenue"] for row in ordered[-2 * half : -half])
    if not previous:
        return None
    return _pct(recent - previous, previous)


# ------------------------------------------------------------------- clientes
def _customer_blocks(data: Dict[str, Any], *, months: int, top: int, days_without_purchase: int) -> Dict[str, Any]:
    now = _now()
    since = now - timedelta(days=31 * months)
    previous_since = now - timedelta(days=31 * 2 * months)

    accounts = _index(data["accounts"])
    products = _index(data["products"])
    orders = [order for order in data["orders"] if str(order.get("status")) in STATUS_REALIZADA]

    orders_by_account = _by(orders, "account_id")
    lines_by_order = _by([line for line in data["lines"] if str(line.get("status")) != "cancelada"], "order_id")

    rows: List[Dict[str, Any]] = []
    for account_id, account in accounts.items():
        account_orders = orders_by_account.get(account_id, [])
        revenue = _money(sum(_number(order.get("total")) for order in account_orders))
        recent = 0.0
        previous = 0.0
        last_order: Optional[datetime] = None
        bought: Dict[str, Dict[str, Any]] = {}
        for order in account_orders:
            moment = _moment(order.get("order_date")) or _moment(order.get("created_at"))
            amount = _number(order.get("total"))
            if moment:
                if moment >= since:
                    recent += amount
                elif moment >= previous_since:
                    previous += amount
                if last_order is None or moment > last_order:
                    last_order = moment
            for line in lines_by_order.get(str(order.get("id")), []):
                key = str(line.get("product_id") or "") or f"texto:{line.get('description')}"
                entry = bought.setdefault(
                    key,
                    {
                        "product_id": str(line.get("product_id") or ""),
                        "name": (products.get(str(line.get("product_id"))) or {}).get("name") or str(line.get("description") or ""),
                        "units": 0.0,
                        "revenue": 0.0,
                    },
                )
                entry["units"] += _number(line.get("quantity"))
                entry["revenue"] += _number(line.get("line_total"))

        days_since = (now - last_order).days if last_order else None
        if not account_orders:
            state = "sem-compras"
        elif days_since is not None and days_since >= 2 * days_without_purchase:
            state = "inativo"
        elif days_since is not None and days_since >= days_without_purchase:
            state = "em risco"
        else:
            state = "ativo"

        rows.append(
            {
                "account_id": account_id,
                "name": account.get("name") or account_id,
                "status": account.get("status") or "",
                "clv": revenue,
                "orders": len(account_orders),
                "ticket_medio": _money(revenue / len(account_orders)) if account_orders else 0.0,
                "frequencia_anual": round(len(account_orders) / max(1, months) * 12, 2) if account_orders else 0.0,
                "ultima_encomenda": last_order.date().isoformat() if last_order else "",
                "dias_sem_compra": days_since,
                "produtos": sorted(bought.values(), key=lambda item: item["revenue"], reverse=True)[:top],
                "produtos_total": len(bought),
                "receita_periodo": _money(recent),
                "variacao_pct": _pct(recent - previous, previous) if previous else None,
                "estado": state,
            }
        )

    with_orders = [row for row in rows if row["orders"]]
    without_orders = [row for row in rows if not row["orders"]]
    at_risk = [row for row in with_orders if row["dias_sem_compra"] is not None and row["dias_sem_compra"] >= days_without_purchase]
    growing = [row for row in with_orders if (row["variacao_pct"] or 0) >= 20]
    shrinking = [row for row in with_orders if (row["variacao_pct"] or 0) <= -20]

    return {
        "resumo": {
            "clientes": len(rows),
            "clientes_com_compra": len(with_orders),
            "clientes_sem_compra": len(without_orders),
            "frequencia_media_anual": round(
                sum(row["frequencia_anual"] for row in with_orders) / len(with_orders), 2
            )
            if with_orders
            else 0.0,
            "clv_medio": _money(sum(row["clv"] for row in with_orders) / len(with_orders)) if with_orders else 0.0,
            "clv_total": _money(sum(row["clv"] for row in with_orders)),
            "a_crescer": len(growing),
            "a_encolher": len(shrinking),
            "sem_compra_ha_dias": len(at_risk),
        },
        "top_clv": sorted(with_orders, key=lambda row: row["clv"], reverse=True)[:top],
        "sem_compra": sorted(at_risk, key=lambda row: row["dias_sem_compra"] or 0, reverse=True)[:top],
        "a_crescer": sorted(growing, key=lambda row: row["variacao_pct"] or 0, reverse=True)[:top],
        "a_encolher": sorted(shrinking, key=lambda row: row["variacao_pct"] or 0)[:top],
        "nunca_compraram": sorted(without_orders, key=lambda row: row["name"])[:top],
        "dias_sem_compra": days_without_purchase,
    }


# ------------------------------------------------------------------ operações
def _operation_blocks(data: Dict[str, Any], perm: Dict[str, Any], *, top: int) -> Dict[str, Any]:
    now = _now()
    today = now.date().isoformat()
    accounts = _index(data["accounts"])
    teams = _index(_read("teams", perm, 200)) if suite.can_read(perm, "teams") else {}

    orders = data["orders"]
    pending = [order for order in orders if str(order.get("status")) in STATUS_ABERTA]
    by_status: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        key = str(order.get("status") or "sem-estado")
        row = by_status.setdefault(key, {"key": key, "count": 0, "value": 0.0})
        row["count"] += 1
        row["value"] += _number(order.get("total"))
    late_orders = [
        order
        for order in pending
        if str(order.get("delivery_date") or "")[:10] and str(order["delivery_date"])[:10] < today
    ]

    work_orders = data["work_orders"]
    open_work = [item for item in work_orders if str(item.get("status")) in WORK_OPEN]
    done_work = [item for item in work_orders if str(item.get("status")) in WORK_DONE]

    durations: List[float] = []
    for item in work_orders:
        started = _moment(item.get("started_at"))
        finished = _moment(item.get("finished_at"))
        if started and finished:
            durations.append((finished - started).total_seconds() / 3600.0)
        elif started:
            durations.append((now - started).total_seconds() / 3600.0)

    sla_states: Dict[str, int] = {"cumprido": 0, "em-risco": 0, "incumprido": 0}
    for item in work_orders:
        state = str(item.get("sla_state") or "")
        if state in sla_states:
            sla_states[state] += 1
    with_sla = sum(sla_states.values())

    late_work = [
        item
        for item in open_work
        if str(item.get("sla_state")) == "incumprido"
        or (
            str(item.get("scheduled_end") or "")[:10]
            and str(item["scheduled_end"])[:10] < today
        )
    ]

    capacity: Dict[str, Dict[str, Any]] = {}
    for item in work_orders:
        key = str(item.get("team_id") or item.get("technician_email") or "sem-equipa")
        row = capacity.setdefault(
            key,
            {
                "team_id": key,
                "label": (teams.get(key) or {}).get("name")
                or item.get("technician_email")
                or ("Sem equipa atribuída" if key == "sem-equipa" else key),
                "abertas": 0,
                "concluidas": 0,
                "horas": 0.0,
                "tecnicos": set(),
            },
        )
        if str(item.get("status")) in WORK_OPEN:
            row["abertas"] += 1
        if str(item.get("status")) in WORK_DONE:
            row["concluidas"] += 1
        row["horas"] += _number(item.get("actual_hours"))
        if item.get("technician_email"):
            row["tecnicos"].add(str(item["technician_email"]))
    for row in capacity.values():
        row["horas"] = round(row["horas"], 2)
        row["tecnicos"] = len(row["tecnicos"])

    by_type: Dict[str, Dict[str, Any]] = {}
    for item in work_orders:
        key = str(item.get("work_type") or "sem-tipo")
        row = by_type.setdefault(key, {"key": key, "count": 0, "abertas": 0, "horas": 0.0, "custo": 0.0})
        row["count"] += 1
        if str(item.get("status")) in WORK_OPEN:
            row["abertas"] += 1
        row["horas"] += _number(item.get("actual_hours"))
        row["custo"] += _number(item.get("cost"))

    billable = _money(sum(_number(item.get("billing_amount")) for item in work_orders if item.get("billable")))
    cost_total = _money(sum(_number(item.get("cost")) for item in work_orders))

    return {
        "encomendas": {
            "total": len(orders),
            "pendentes": len(pending),
            "valor_pendente": _money(sum(_number(order.get("total")) for order in pending)),
            "atrasadas": len(late_orders),
            "por_estado": sorted(by_status.values(), key=lambda row: row["count"], reverse=True),
            "exemplos_atrasadas": [
                {
                    "id": order.get("id"),
                    "numero": order.get("order_number") or order.get("title"),
                    "conta": (accounts.get(str(order.get("account_id"))) or {}).get("name") or "",
                    "entrega": order.get("delivery_date"),
                    "valor": _money(_number(order.get("total"))),
                }
                for order in late_orders[:top]
            ],
        },
        "ordens": {
            "total": len(work_orders),
            "abertas": len(open_work),
            "concluidas": len(done_work),
            "atrasadas": len(late_work),
            "taxa_conclusao_pct": _pct(len(done_work), len(work_orders)),
            "tempo_medio_horas": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "horas_totais": round(sum(_number(item.get("actual_hours")) for item in work_orders), 1),
            "sla": {
                "cumprido": sla_states["cumprido"],
                "em_risco": sla_states["em-risco"],
                "incumprido": sla_states["incumprido"],
                "cumprimento_pct": _pct(sla_states["cumprido"], with_sla),
            },
            "custo": cost_total,
            "valor_faturavel": billable,
            "margem_servico": _money(billable - cost_total),
            "exemplos_atrasadas": [
                {
                    "id": item.get("id"),
                    "numero": item.get("number") or item.get("title"),
                    "conta": (accounts.get(str(item.get("account_id"))) or {}).get("name") or "",
                    "estado": item.get("status"),
                    "sla_state": item.get("sla_state"),
                    "inicio_previsto": item.get("scheduled_start"),
                    "tecnico": item.get("technician_email") or "",
                }
                for item in late_work[:top]
            ],
        },
        "capacidade": sorted(capacity.values(), key=lambda row: row["abertas"], reverse=True)[:top],
        "por_tipo": sorted(by_type.values(), key=lambda row: row["count"], reverse=True)[:top],
    }


# --------------------------------------------------------- compras / fornecedores
def _supplier_blocks(data: Dict[str, Any], *, top: int) -> Dict[str, Any]:
    """Fornecedores: carteira, condições, custo de aquisição e risco de dependência.

    O custo por fornecedor vem das linhas de encomenda que o referenciam
    (`supplier_id` × quantidade × custo unitário) — é a ligação
    encomenda → linha → fornecedor que fecha o ciclo de compras.
    """
    suppliers = data["suppliers"]
    purchases: Dict[str, Dict[str, Any]] = {}
    for line in data["lines"]:
        if str(line.get("status")) == "cancelada":
            continue
        supplier_id = str(line.get("supplier_id") or "")
        if not supplier_id:
            continue
        quantity = _number(line.get("quantity"))
        row = purchases.setdefault(
            supplier_id,
            {"supplier_id": supplier_id, "name": "", "lines": 0, "units": 0.0, "cost": 0.0, "revenue": 0.0},
        )
        row["lines"] += 1
        row["units"] += quantity
        row["cost"] += _number(line.get("unit_cost")) * quantity
        row["revenue"] += _number(line.get("line_total"))

    names = {str(item.get("id")): item.get("name") for item in suppliers}
    for key, row in purchases.items():
        row["name"] = names.get(key) or key
        row["cost"] = _money(row["cost"])
        row["revenue"] = _money(row["revenue"])
        row["margin"] = _money(row["revenue"] - row["cost"])
        row["margin_pct"] = _pct(row["margin"], row["revenue"])

    by_status: Dict[str, Dict[str, Any]] = {}
    by_type: Dict[str, Dict[str, Any]] = {}
    for item in suppliers:
        state = str(item.get("status") or "sem-estado")
        by_status.setdefault(state, {"key": state, "count": 0})["count"] += 1
        kind = str(item.get("supplier_type") or "sem-tipo")
        by_type.setdefault(kind, {"key": kind, "count": 0})["count"] += 1

    def _average(field: str) -> Optional[float]:
        values = [
            _number(item.get(field))
            for item in suppliers
            if item.get(field) not in (None, "") and str(item.get(field)) != ""
        ]
        return round(sum(values) / len(values), 1) if values else None

    risks: List[Dict[str, Any]] = []
    for item in suppliers:
        reasons: List[str] = []
        if str(item.get("status")) == "suspenso":
            reasons.append("fornecedor suspenso")
        if str(item.get("criticality")) == "fonte-unica":
            reasons.append("fonte única")
        if item.get("on_time_pct") not in (None, "") and _number(item.get("on_time_pct")) < 80:
            reasons.append(f"entregas a tempo {_pct_text(item.get('on_time_pct'))}")
        if reasons:
            risks.append(
                {
                    "supplier_id": item.get("id"),
                    "name": item.get("name") or item.get("id"),
                    "criticality": item.get("criticality") or "",
                    "status": item.get("status") or "",
                    "on_time_pct": item.get("on_time_pct"),
                    "lead_time_days": item.get("lead_time_days"),
                    "motivo": "; ".join(reasons),
                }
            )

    attributed = set(purchases)
    return {
        "total": len(suppliers),
        "por_estado": sorted(by_status.values(), key=lambda row: row["count"], reverse=True),
        "por_tipo": sorted(by_type.values(), key=lambda row: row["count"], reverse=True),
        "custo_aquisicao": _money(sum(row["cost"] for row in purchases.values())),
        "receita_atribuida": _money(sum(row["revenue"] for row in purchases.values())),
        "margem_bruta": _money(sum(row["margin"] for row in purchases.values())),
        "prazos": {
            "lead_time_medio_dias": _average("lead_time_days"),
            "pontualidade_media_pct": _average("on_time_pct"),
            "qualidade_media": _average("quality_score"),
            "cumprimento_prazos_medio": _average("delivery_score"),
        },
        "compras": sorted(purchases.values(), key=lambda row: row["cost"], reverse=True)[:top],
        "sem_linhas_atribuidas": len([item for item in suppliers if str(item.get("id")) not in attributed]),
        "risco": risks[:top],
        "criticos": len(risks),
    }


# ---------------------------------------------------------------------- painel
def snapshot(
    perm: Dict[str, Any],
    *,
    months: int = DEFAULT_MONTHS,
    top: int = 10,
    days_without_purchase: int = DEFAULT_DAYS_WITHOUT_PURCHASE,
) -> Dict[str, Any]:
    """Painel de analytics: vendas, clientes e operações (dados reais e no âmbito do perfil)."""
    data = dataset(perm)
    blocks: Dict[str, Any] = {
        "gerado_em": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "filtros": {"meses": months, "top": top, "dias_sem_compra": days_without_purchase},
        "fontes": {
            "encomendas": len(data["orders"]),
            "linhas": len(data["lines"]),
            "produtos": len(data["products"]),
            "fornecedores": len(data["suppliers"]),
            "contas": len(data["accounts"]),
            "ordens_trabalho": len(data["work_orders"]),
        },
        "acesso": {
            "vendas": suite.can_read(perm, "orders"),
            "clientes": suite.can_read(perm, "accounts"),
            "operacoes": suite.can_read(perm, "work-orders"),
            "compras": suite.can_read(perm, "suppliers"),
        },
    }
    if suite.can_read(perm, "orders") or suite.can_read(perm, "order-lines"):
        blocks["vendas"] = _revenue_blocks(data, months=months, top=top)
    if suite.can_read(perm, "accounts"):
        blocks["clientes"] = _customer_blocks(data, months=months, top=top, days_without_purchase=days_without_purchase)
    if suite.can_read(perm, "work-orders") or suite.can_read(perm, "orders"):
        blocks["operacoes"] = _operation_blocks(data, perm, top=top)
    if suite.can_read(perm, "suppliers"):
        blocks["fornecedores"] = _supplier_blocks(data, top=top)
    return blocks


# --------------------------------------------------------- cross-sell / upsell
def product_catalogue(perm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Catálogo de produtos que o perfil pode ler (base das análises de carteira)."""
    return _read("products", perm, MAX_PRODUCTS)


def match_product(text: str, products: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Encontra, no catálogo real, o produto referido num texto livre.

    Só devolve produtos que existem (nunca inventa): escolhe a designação mais
    longa que caiba no texto — «Produto Premium Plus» ganha a «Produto Premium».
    """
    needle = _fold(text)
    if not needle:
        return None
    best: Optional[Dict[str, Any]] = None
    best_length = 0
    for product in products:
        for candidate in (product.get("name"), product.get("sku")):
            label = _fold(candidate)
            if not label or len(label) < 3:
                continue
            if label in needle and len(label) > best_length:
                best = product
                best_length = len(label)
    if best:
        return best
    # Sem referência exata: tenta o nome do produto contido no texto ao contrário
    # (o utilizador escreveu «premium» e o produto é «Licença Premium»).
    for product in products:
        label = _fold(product.get("name"))
        words = [word for word in label.split() if len(word) > 4]
        if words and all(word in needle for word in words):
            return product
    return None


def _parse_amount(text: str) -> Optional[float]:
    match = re.search(r"(?:mais de|acima de|superior(?:es)? a|>=?)\s*(?:€|eur)?\s*([\d][\d\s.,]*)", text)
    if not match:
        match = re.search(r"([\d][\d\s.,]*)\s*(?:€|eur|euros)", text)
    if not match:
        return None
    raw = match.group(1).strip().replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_months(text: str) -> int:
    if "trimestre" in text or "3 meses" in text or "90 dias" in text:
        return 3
    if "semestre" in text or "6 meses" in text or "180 dias" in text:
        return 6
    if "24 meses" in text or "2 anos" in text or "dois anos" in text:
        return 24
    if "ano" in text or "12 meses" in text or "365 dias" in text:
        return 12
    return DEFAULT_MONTHS


def parse_request(question: str, products: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Interpreta um pedido de cross-sell/upsell escrito em linguagem natural.

    Devolve sempre uma estrutura com o que conseguiu extrair; o que não for
    reconhecido fica a `None` (nunca se inventa um produto nem um valor).
    """
    text = _fold(question)
    request: Dict[str, Any] = {
        "criar": bool(re.search(r"\b(cria|criar|gere|gerar|abre|abrir)\b.*\boportunidade", text)),
        "meses": _parse_months(text),
        "min_spend": _parse_amount(text),
        "have_product": None,
        "missing_product": None,
        "account": None,
    }

    # «compraram A mas não B» / «comprou A e não tem B»
    pair = re.search(
        r"comprar\w*\s+(?:o\s+|a\s+)?(.+?)\s+(?:mas|e)\s+n[aã]o\s+(?:comprar\w*\s+|tem\s+|têm\s+|adquirir\w*\s+)?(.+?)(?:$|\?|,|\.| este| no | em )",
        text,
    )
    if pair:
        have = match_product(pair.group(1), products)
        missing = match_product(pair.group(2), products)
        request["have_product"] = have
        request["missing_product"] = missing

    if request["missing_product"] is None:
        gap = re.search(
            r"(?:n[aã]o\s+(?:compra|compram|compraram|tem|t[eê]m|possui|possuem)|sem)\s+(?:o\s+|a\s+|os\s+|as\s+)?(.+?)(?:$|\?|,|\.| este| no | em )",
            text,
        )
        if gap:
            request["missing_product"] = match_product(gap.group(1), products)

    # «Que produtos o cliente ACME ainda não compra?» — lacuna de um cliente.
    account_hint = re.search(r"(?:cliente|conta|empresa)\s+([\w&.\- ]{2,60}?)(?:\s+ainda|\s+nao|\s+não|\s+ja|\s+já|\?|$|,|\.)", text)
    if account_hint and request["missing_product"] is None:
        request["account"] = account_hint.group(1).strip()

    # «quais/todos os produtos» sem produto identificado → modo carteira do cliente.
    request["mode"] = (
        "account"
        if request["account"] and not request["missing_product"]
        else "pair"
        if request["have_product"] and request["missing_product"]
        else "missing"
        if request["missing_product"]
        else "all"
    )
    return request


def _account_index(perm: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _read("accounts", perm, MAX_ACCOUNTS)


def find_account(text: str, accounts: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Conta a partir de um nome (ou NIF) referido em texto livre."""
    needle = _fold(text)
    if len(needle) < 2:
        return None
    best: Optional[Dict[str, Any]] = None
    best_length = 0
    for account in accounts:
        for candidate in (account.get("name"), account.get("nif")):
            label = _fold(candidate)
            if not label or len(label) < 3:
                continue
            if label in needle and len(label) > best_length:
                best = account
                best_length = len(label)
    return best


def cross_sell(
    perm: Dict[str, Any],
    *,
    have_product_id: Optional[str] = None,
    missing_product_id: Optional[str] = None,
    min_spend: Optional[float] = None,
    months: int = DEFAULT_MONTHS,
    limit: int = 50,
    exclude_with_open_opportunity: bool = True,
) -> Dict[str, Any]:
    """Clientes que compraram (ou não) determinados produtos, com receita do período.

    É o motor que responde a «quem comprou A mas não B?» e a
    «quem gastou mais de X e não tem o produto Y?».
    """
    data = dataset(perm)
    products = _index(data["products"])
    accounts = _index(data["accounts"])
    since = _now() - timedelta(days=31 * months)

    orders_ok = {
        str(order.get("id")): order
        for order in data["orders"]
        if str(order.get("status")) in STATUS_REALIZADA and (_moment(order.get("order_date")) or _now()) >= since
    }
    revenue: Dict[str, float] = {}
    orders_count: Dict[str, int] = {}
    last_order: Dict[str, str] = {}
    bought: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for order_id, order in orders_ok.items():
        account_id = str(order.get("account_id") or "")
        if not account_id:
            continue
        revenue[account_id] = revenue.get(account_id, 0.0) + _number(order.get("total"))
        orders_count[account_id] = orders_count.get(account_id, 0) + 1
        stamp = str(order.get("order_date") or "")[:10]
        if stamp > last_order.get(account_id, ""):
            last_order[account_id] = stamp
    for line in data["lines"]:
        if str(line.get("status")) == "cancelada":
            continue
        order = orders_ok.get(str(line.get("order_id")))
        if order is None:
            continue
        account_id = str(order.get("account_id") or "")
        product_id = str(line.get("product_id") or "")
        if not account_id or not product_id:
            continue
        entry = bought.setdefault(account_id, {}).setdefault(
            product_id,
            {"product_id": product_id, "units": 0.0, "revenue": 0.0},
        )
        entry["units"] += _number(line.get("quantity"))
        entry["revenue"] += _number(line.get("line_total"))

    open_opportunities: Dict[str, set] = {}
    if exclude_with_open_opportunity:
        for opportunity in data["opportunities"]:
            if str(opportunity.get("stage")) in ("ganho", "perdido"):
                continue
            account_id = str(opportunity.get("account_id") or "")
            if account_id:
                open_opportunities.setdefault(account_id, set()).add(_fold(opportunity.get("title")))

    rows: List[Dict[str, Any]] = []
    for account_id, product_map in bought.items():
        total = revenue.get(account_id, 0.0)
        if min_spend is not None and total < min_spend:
            continue
        if have_product_id and have_product_id not in product_map:
            continue
        if missing_product_id and missing_product_id in product_map:
            continue
        if not (have_product_id or missing_product_id or min_spend is not None) and len(product_map) < 2:
            # Sem filtros: só interessam clientes com mais de um produto (potencial de cross-sell).
            continue

        candidate = {
            "account_id": account_id,
            "name": (accounts.get(account_id) or {}).get("name") or account_id,
            "revenue": _money(total),
            "orders": orders_count.get(account_id, 0),
            "ultima_encomenda": last_order.get(account_id, ""),
            "produtos": len(product_map),
            "comprados": [
                {
                    "product_id": key,
                    "name": (products.get(key) or {}).get("name") or key,
                    "revenue": _money(value["revenue"]),
                }
                for key, value in sorted(product_map.items(), key=lambda item: item[1]["revenue"], reverse=True)
            ],
            "falta": (products.get(missing_product_id) or {}).get("name") if missing_product_id else "",
            "ja_tem_oportunidade": False,
        }
        if missing_product_id:
            candidate["ja_tem_oportunidade"] = any(
                _fold(f"cross-sell: {(products.get(missing_product_id) or {}).get('name')}") in title
                for title in open_opportunities.get(account_id, set())
            )
        rows.append(candidate)

    rows.sort(key=lambda row: row["revenue"], reverse=True)
    if exclude_with_open_opportunity and missing_product_id:
        rows = [row for row in rows if not row["ja_tem_oportunidade"]]

    return {
        "filtros": {
            "compraram": (products.get(have_product_id) or {}).get("name") if have_product_id else "",
            "nao_tem": (products.get(missing_product_id) or {}).get("name") if missing_product_id else "",
            "min_spend": min_spend,
            "meses": months,
        },
        "catalogo": len(data["products"]),
        "total": len(rows),
        "valor_potencial": _money(sum(row["revenue"] for row in rows[:limit])),
        "accounts": rows[:limit],
    }


def products_without_purchase(perm: Dict[str, Any], account_id: str, *, months: int = DEFAULT_MONTHS, limit: int = 20) -> Dict[str, Any]:
    """Produtos do catálogo (ativos) que uma conta ainda não comprou."""
    data = dataset(perm)
    products = _index(data["products"])
    orders_ok = {
        str(order.get("id"))
        for order in data["orders"]
        if str(order.get("account_id")) == account_id and str(order.get("status")) in STATUS_REALIZADA
    }
    owned = {
        str(line.get("product_id"))
        for line in data["lines"]
        if str(line.get("order_id")) in orders_ok and line.get("product_id") and str(line.get("status")) != "cancelada"
    }
    missing = [
        {
            "product_id": product_id,
            "name": product.get("name"),
            "sku": product.get("sku"),
            "category": product.get("category") or "",
            "price": _number(product.get("price")),
        }
        for product_id, product in products.items()
        if product_id not in owned and str(product.get("status") or "ativo") != "descontinuado"
    ]
    missing.sort(key=lambda row: row["price"], reverse=True)
    return {
        "account_id": account_id,
        "comprados": len(owned),
        "catalogo": len(products),
        "total": len(missing),
        "produtos": missing[:limit],
        "valor_potencial": _money(sum(row["price"] for row in missing[:limit])),
        "meses": months,
    }


# ------------------------------------------------------------------ ação no CRM
def create_opportunities(
    perm: Dict[str, Any],
    *,
    audience: Sequence[Dict[str, Any]],
    title: str,
    amount: Optional[float] = None,
    amount_from: str = "revenue_pct",
    stage: str = "prospeccao",
    expected_days: int = 60,
    source: str = "ia-cross-sell",
    dry_run: bool = False,
    limit: int = MAX_CREATE,
) -> Dict[str, Any]:
    """Cria oportunidades para um conjunto de contas (o «Insight → Ação» do CRM).

    Cada oportunidade nasce com o valor da conta no período (ou um valor fixo) e
    com as notas a explicar porque foi criada — rasto para o comercial avaliar.
    """
    if not suite.can(perm, "opportunities", "create"):
        return {"error": "O seu perfil não permite criar oportunidades"}

    module = registry.MODULE_BY_SLUG["opportunities"]
    existing = _read("opportunities", perm, MAX_OPPORTUNITIES)
    existing_titles = {(_fold(item.get("account_id")), _fold(item.get("title"))) for item in existing}

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    close_date = (_now() + timedelta(days=expected_days)).date().isoformat()

    for row in list(audience)[:limit]:
        account_id = str(row.get("account_id") or "")
        if not account_id:
            continue
        if (_fold(account_id), _fold(title)) in existing_titles:
            skipped.append({"account_id": account_id, "name": row.get("name"), "motivo": "já existe uma oportunidade com este título"})
            continue
        if amount is not None:
            value = _number(amount)
        elif amount_from == "revenue_pct":
            value = round(_number(row.get("revenue")) * 0.25, 2)
        else:
            value = _number(row.get("revenue"))
        if dry_run:
            created.append(
                {
                    "account_id": account_id,
                    "name": row.get("name"),
                    "title": title,
                    "amount": value,
                    "dry_run": True,
                }
            )
            continue

        payload = {
            "title": title,
            "account_id": account_id,
            "amount": value,
            "currency": "EUR",
            "stage": stage,
            "source": source,
            "expected_close_date": close_date,
            "notes": (
                f"Oportunidade criada pelo motor de IA a partir dos dados de compra: "
                f"{row.get('reason') or row.get('falta') or 'candidato a cross-sell'}. "
                f"Receita da conta no período: {_money(_number(row.get('revenue'))):.2f} €."
            ),
        }
        result = suite.save_module(module, payload, perm)
        if result.get("error"):
            skipped.append({"account_id": account_id, "name": row.get("name"), "motivo": result["error"]})
            continue
        created.append(
            {
                "account_id": account_id,
                "name": row.get("name"),
                "title": title,
                "amount": value,
                "opportunity_id": result["item"].get("id"),
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "criadas": created,
        "ignoradas": skipped,
        "total_criadas": len(created),
        "valor_total": _money(sum(row.get("amount") or 0 for row in created)),
    }


def summary_answer(question: str, perm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resposta a perguntas de indicadores: vendas, clientes e/ou operações.

    Escolhe os blocos a apresentar pelo tema da pergunta e devolve sempre os
    números reais (com os limites do âmbito do perfil).
    """
    text = _fold(question)
    months = _parse_months(text)
    board = snapshot(perm, months=months, top=10)

    topics: List[str] = []
    if any(word in text for word in ("venda", "receita", "produto", "ticket", "margem", "vendedor", "fatura", "faturado")):
        topics.append("vendas")
    # «comprou/compraram» é análise de clientes; «compra/compras» é análise de
    # fornecedores — a distinção evita responder com o bloco errado.
    if any(word in text for word in ("cliente", "clv", "lifetime", "frequencia", "carteira", "comprou", "compraram")):
        topics.append("clientes")
    if any(word in text for word in ("ordem", "encomenda", "sla", "operac", "capacidade", "atrasad", "execucao")):
        topics.append("operacoes")
    if any(word in text for word in ("fornecedor", "compra", "aquisic", "lead time", "incoterm")):
        topics.append("compras")
    if not topics:
        topics = ["vendas", "clientes", "operacoes"]

    lines: List[str] = [f"Indicadores do CRM (últimos {months} meses):"]
    for topic in topics:
        if topic == "vendas" and board.get("vendas"):
            block = board["vendas"]
            receita = block["receita"]
            lines.append(
                f"\n**Vendas** — receita {_eur(receita['realizada'])} em {receita['encomendas']} encomenda(s), "
                f"ticket médio {_eur(receita['ticket_medio'])}, margem {_eur(receita['margem'])} "
                f"({_pct_text(receita['margem_pct'])}); em aberto {_eur(receita['em_aberto'])}."
            )
            if block["por_produto"]:
                lines.append(
                    "Produtos com mais receita: "
                    + "; ".join(f"{row['name']} ({_eur(row['revenue'])})" for row in block["por_produto"][:5])
                    + "."
                )
            if block["por_cliente"]:
                lines.append(
                    "Clientes com mais receita: "
                    + "; ".join(f"{row['name']} ({_eur(row['revenue'])})" for row in block["por_cliente"][:5])
                    + "."
                )
            if block["por_vendedor"]:
                lines.append(
                    "Vendedores: "
                    + "; ".join(f"{row['owner']} ({_eur(row['revenue'])})" for row in block["por_vendedor"][:5])
                    + "."
                )
        elif topic == "clientes" and board.get("clientes"):
            block = board["clientes"]
            resumo = block.get("resumo") or {}
            lines.append(
                f"\n**Clientes** — {resumo.get('clientes_com_compra', 0)} com compras e {resumo.get('clientes_sem_compra', 0)} sem nenhuma; "
                f"CLV médio {_eur(resumo.get('clv_medio'))}, frequência média {_num_text(resumo.get('frequencia_media_anual'))} encomenda(s)/ano; "
                f"{resumo.get('sem_compra_ha_dias', 0)} sem comprar há mais de {block.get('dias_sem_compra', DEFAULT_DAYS_WITHOUT_PURCHASE)} dias."
            )
            if block["top_clv"]:
                lines.append(
                    "Maior valor: "
                    + "; ".join(
                        f"{row['name']} ({_eur(row['clv'])}, último pedido {row['ultima_encomenda'] or '—'})"
                        for row in block["top_clv"][:5]
                    )
                    + "."
                )
            if block["sem_compra"]:
                lines.append(
                    "Em risco de inatividade: "
                    + "; ".join(f"{row['name']} ({row['dias_sem_compra']} dias)" for row in block["sem_compra"][:5])
                    + "."
                )
        elif topic == "operacoes" and board.get("operacoes"):
            block = board["operacoes"]
            orders = block["encomendas"]
            work = block["ordens"]
            lines.append(
                f"\n**Operações** — {orders['pendentes']} encomenda(s) pendentes ({_eur(orders['valor_pendente'])}), "
                f"{orders['atrasadas']} atrasada(s); {work['abertas']} ordem(ns) de trabalho abertas, "
                f"{work['atrasadas']} atrasada(s), SLA cumprido em {_pct_text(work['sla']['cumprimento_pct'])}, "
                f"tempo médio de execução {_num_text(work['tempo_medio_horas'])} h."
            )
            if block["capacidade"]:
                lines.append(
                    "Carga por equipa: "
                    + "; ".join(
                        f"{row['label']} ({row['abertas']} abertas, {_num_text(row['horas'])} h)" for row in block["capacidade"][:5]
                    )
                    + "."
                )
        elif topic == "compras" and board.get("fornecedores"):
            block = board["fornecedores"]
            prazos = block["prazos"]
            lines.append(
                f"\n**Compras** — {block['total']} fornecedor(es); custo de aquisição atribuído "
                f"{_eur(block['custo_aquisicao'])}, margem bruta {_eur(block['margem_bruta'])}; "
                f"prazo médio de entrega {_num_text(prazos['lead_time_medio_dias']) if prazos.get('lead_time_medio_dias') is not None else '—'} dias, "
                f"pontualidade média {_pct_text(prazos.get('pontualidade_media_pct') or 0)}."
            )
            if block["compras"]:
                lines.append(
                    "Maior custo: "
                    + "; ".join(f"{row['name']} ({_eur(row['cost'])})" for row in block["compras"][:5])
                    + "."
                )
            if block["risco"]:
                lines.append(
                    "Em risco: "
                    + "; ".join(f"{row['name']} ({row['motivo']})" for row in block["risco"][:5])
                    + "."
                )

    if len(lines) == 1:
        return None
    return {"answer": "\n".join(lines), "intent": f"analise-{topics[0]}", "data": board}


# ------------------------------------------------------------------- agente IA
def suggest_title(missing_name: str) -> str:
    """Título por omissão das oportunidades criadas a partir de um público."""
    return f"Cross-sell: {missing_name}" if missing_name else "Campanha de cross-sell"


def answer(question: str, perm: Dict[str, Any], *, create: bool = False) -> Optional[Dict[str, Any]]:
    """Responde a um pedido de cross-sell/upsell com dados reais e, se pedido, age.

    Devolve `None` quando a pergunta não é deste tipo (o assistente genérico trata).
    """
    data = dataset(perm)
    products = data["products"]
    accounts = data["accounts"]
    request = parse_request(question, products)

    # Sem produto identificado, sem limite de valor e sem conta concreta, a
    # pergunta não é suficientemente específica para o motor de carteira: deixa-se
    # para o assistente genérico (que responde com o resumo do CRM).
    if request["mode"] == "all" and request["min_spend"] is None and not request["account"]:
        return None

    if request["mode"] == "account":
        account = find_account(str(request["account"]), accounts)
        if account is None:
            return {
                "answer": (
                    f"Não encontrei nenhuma conta que corresponda a «{request['account']}» no CRM. "
                    "Confirme o nome (ou indique o NIF)."
                ),
                "intent": "cross-sell",
                "data": {"mode": "account", "encontrada": False},
            }
        gap = products_without_purchase(perm, str(account.get("id")), months=request["meses"])
        linhas = [
            f"• {item['name']}"
            + (f" ({item['category']})" if item["category"] else "")
            + (f" — {_eur(item['price'])}" if item["price"] else "")
            for item in gap["produtos"][:15]
        ]
        answer = (
            f"O cliente {account.get('name')} comprou {gap['comprados']} de {gap['catalogo']} produtos do catálogo.\n"
            f"Ainda não comprou {gap['total']} produto{'s' if gap['total'] != 1 else ''}"
            + (f", num valor de referência de {_eur(gap['valor_potencial'])}" if gap["valor_potencial"] else "")
            + (":\n" + "\n".join(linhas) if linhas else ".")
        )
        return {
            "answer": answer,
            "intent": "cross-sell",
            "data": {"mode": "account", "account": {"id": account.get("id"), "name": account.get("name")}, **gap},
        }

    analysis = cross_sell(
        perm,
        have_product_id=(request["have_product"] or {}).get("id"),
        missing_product_id=(request["missing_product"] or {}).get("id"),
        min_spend=request["min_spend"],
        months=request["meses"],
        limit=25,
    )

    if analysis["total"] == 0 and not request["missing_product"] and not request["min_spend"] and not request["have_product"]:
        return None

    filters = analysis["filtros"]
    descricao: List[str] = []
    if filters["compraram"]:
        descricao.append(f"compraram {filters['compraram']}")
    if filters["nao_tem"]:
        descricao.append(f"não têm {filters['nao_tem']}")
    if filters["min_spend"]:
        descricao.append(f"gastaram mais de {_eur(filters['min_spend'])}")
    titulo = "Clientes" + (" que " + " e ".join(descricao) if descricao else " com potencial de cross-sell")

    linhas = [
        f"{index + 1}. {row['name']} — {_eur(row['revenue'])} em {row['orders']} encomenda(s)"
        + (f", último pedido em {row['ultima_encomenda']}" if row["ultima_encomenda"] else "")
        + (f", falta {row['falta']}" if row["falta"] else "")
        for index, row in enumerate(analysis["accounts"][:15])
    ]
    answer = (
        f"{titulo}: {analysis['total']} conta(s)"
        + (f" nos últimos {filters['meses']} meses" if filters["meses"] else "")
        + ".\n"
        + ("\n".join(linhas) if linhas else "Sem contas a cumprir estes critérios.")
    )

    result: Dict[str, Any] = {
        "answer": answer,
        "intent": "cross-sell",
        "data": {"mode": request["mode"], **analysis},
    }

    if create:
        title = suggest_title(str(filters["nao_tem"]))
        action = create_opportunities(
            perm,
            audience=analysis["accounts"],
            title=title,
            amount=None,
            amount_from="revenue_pct",
        )
        if action.get("error"):
            result["answer"] = answer + f"\n\nNão foi possível criar as oportunidades: {action['error']}."
        elif action["total_criadas"]:
            result["answer"] = (
                answer
                + f"\n\nCriei {action['total_criadas']} oportunidade(s) «{title}», "
                + f"num valor total de {_eur(action['valor_total'])}, na fase de prospeção (fonte: motor de IA)."
            )
            if action["ignoradas"]:
                result["answer"] += f" {len(action['ignoradas'])} conta(s) já tinham uma oportunidade igual."
            result["intent"] = "criar-oportunidade"
        else:
            result["answer"] = answer + "\n\nNão havia contas novas para criar oportunidade."
        result["action"] = action
    return result
