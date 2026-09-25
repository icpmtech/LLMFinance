"""Conjuntos de dados analíticos do CRM (a base dos gráficos e dos quadros).

Cada **dataset** é uma tabela: uma dimensão (o eixo) e várias métricas. Os
números são calculados a partir dos registos reais do CRM, dentro do âmbito do
perfil — quem não pode ler as encomendas não vê as vendas, ponto final.

Alimenta duas coisas:

* os gráficos do painel de **Analytics** (vendas por utilizador, encomendas,
  compras, operação…);
* o **construtor de quadros** (`dashboards`), onde o utilizador escolhe o
  dataset, a métrica e o tipo de gráfico.

Acrescentar um dataset = acrescentar uma entrada em `DATASETS` e um construtor em
`_BUILDERS`. Nada mais (o frontend descobre-o pelo catálogo da API).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from api import crm_analytics as analytics
from api import crm_registry as registry
from api import crm_suite as suite

logger = logging.getLogger(__name__)

# Tipos de métrica (o frontend formata e desenha conforme o tipo).
MONEY = "money"
NUMBER = "number"
COUNT = "int"
PERCENT = "percent"
TEXT = "text"

# Tipos de gráfico aceites pelos widgets dos quadros.
CHARTS = ("barras", "colunas", "linhas", "circular", "tabela", "kpi")

DEFAULT_MONTHS = 12
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class Metric:
    """Uma coluna numérica (ou textual) de um dataset."""

    key: str
    label: str
    kind: str = NUMBER

    def to_public(self) -> Dict[str, str]:
        return {"key": self.key, "label": self.label, "kind": self.kind}


@dataclass(frozen=True)
class Dataset:
    """Tabela analítica: dimensão + métricas, com as fontes que precisa de ler."""

    id: str
    label: str
    description: str
    group: str
    sources: Tuple[str, ...]
    dimension: Tuple[str, str]
    metrics: Tuple[Metric, ...]
    chart: str = "barras"
    limit: int = DEFAULT_LIMIT
    sort_metric: str = ""

    def metric_keys(self) -> Tuple[str, ...]:
        return tuple(metric.key for metric in self.metrics)

    def to_public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "group": self.group,
            "sources": list(self.sources),
            "dimension": {"key": self.dimension[0], "label": self.dimension[1]},
            "metrics": [metric.to_public() for metric in self.metrics],
            "chart": self.chart,
            "limit": self.limit,
        }


# --------------------------------------------------------------------- catálogo
def _m(key: str, label: str, kind: str = NUMBER) -> Metric:
    return Metric(key=key, label=label, kind=kind)


DATASETS: Tuple[Dataset, ...] = (
    # ------------------------------------------------------------------ vendas
    Dataset(
        id="vendas-utilizador",
        label="Vendas por utilizador",
        description="Receita, encomendas, margem e ticket médio de cada responsável comercial.",
        group="Vendas",
        sources=("orders", "order-lines"),
        dimension=("responsavel", "Responsável"),
        metrics=(
            _m("receita", "Receita", MONEY),
            _m("encomendas", "Encomendas", COUNT),
            _m("ticket_medio", "Ticket médio", MONEY),
            _m("unidades", "Unidades", NUMBER),
            _m("margem", "Margem", MONEY),
            _m("margem_pct", "Margem (%)", PERCENT),
        ),
        chart="colunas",
        sort_metric="receita",
    ),
    Dataset(
        id="vendas-cliente",
        label="Vendas por cliente",
        description="Receita e margem por conta, com a data da última encomenda.",
        group="Vendas",
        sources=("orders", "order-lines", "accounts"),
        dimension=("cliente", "Cliente"),
        metrics=(
            _m("receita", "Receita", MONEY),
            _m("encomendas", "Encomendas", COUNT),
            _m("ticket_medio", "Ticket médio", MONEY),
            _m("margem", "Margem", MONEY),
            _m("ultima_encomenda", "Última encomenda", TEXT),
        ),
        sort_metric="receita",
    ),
    Dataset(
        id="vendas-produto",
        label="Vendas por produto",
        description="Receita, unidades e margem de cada produto vendido.",
        group="Vendas",
        sources=("orders", "order-lines", "products"),
        dimension=("produto", "Produto"),
        metrics=(
            _m("receita", "Receita", MONEY),
            _m("unidades", "Unidades", NUMBER),
            _m("margem", "Margem", MONEY),
            _m("margem_pct", "Margem (%)", PERCENT),
        ),
        sort_metric="receita",
    ),
    Dataset(
        id="vendas-categoria",
        label="Vendas por categoria de produto",
        description="Receita, unidades e margem agregadas por categoria do catálogo.",
        group="Vendas",
        sources=("orders", "order-lines", "products"),
        dimension=("categoria", "Categoria"),
        metrics=(
            _m("receita", "Receita", MONEY),
            _m("unidades", "Unidades", NUMBER),
            _m("margem", "Margem", MONEY),
            _m("margem_pct", "Margem (%)", PERCENT),
        ),
        sort_metric="receita",
    ),
    Dataset(
        id="vendas-mes",
        label="Vendas por mês",
        description="Evolução mensal da receita realizada, faturada e do ticket médio.",
        group="Vendas",
        sources=("orders",),
        dimension=("mes", "Mês"),
        metrics=(
            _m("receita", "Receita", MONEY),
            _m("encomendas", "Encomendas", COUNT),
            _m("faturada", "Faturada", MONEY),
            _m("ticket_medio", "Ticket médio", MONEY),
        ),
        chart="linhas",
        limit=24,
        sort_metric="",
    ),
    # -------------------------------------------------------------- encomendas
    Dataset(
        id="encomendas-estado",
        label="Encomendas por estado",
        description="Quantas encomendas e que valor estão em cada estado do ciclo de venda.",
        group="Encomendas",
        sources=("orders",),
        dimension=("estado", "Estado"),
        metrics=(_m("encomendas", "Encomendas", COUNT), _m("valor", "Valor", MONEY)),
        chart="colunas",
        sort_metric="encomendas",
    ),
    Dataset(
        id="encomendas-mes",
        label="Encomendas por mês",
        description="Encomendas criadas por mês, com o valor pendente e as já faturadas.",
        group="Encomendas",
        sources=("orders",),
        dimension=("mes", "Mês"),
        metrics=(
            _m("encomendas", "Encomendas", COUNT),
            _m("valor", "Valor", MONEY),
            _m("pendentes", "Pendentes", COUNT),
            _m("faturadas", "Faturadas", COUNT),
        ),
        chart="linhas",
        limit=24,
        sort_metric="",
    ),
    Dataset(
        id="encomendas-cliente",
        label="Encomendas por cliente",
        description="Encomendas e valor por conta, com as que já passaram a data de entrega.",
        group="Encomendas",
        sources=("orders", "accounts"),
        dimension=("cliente", "Cliente"),
        metrics=(
            _m("encomendas", "Encomendas", COUNT),
            _m("valor", "Valor", MONEY),
            _m("atrasadas", "Atrasadas", COUNT),
            _m("ticket_medio", "Ticket médio", MONEY),
        ),
        sort_metric="valor",
    ),
    Dataset(
        id="entregas-mes",
        label="Entregas previstas por mês",
        description="Valor e número de encomendas com entrega prevista em cada mês (carga futura).",
        group="Encomendas",
        sources=("orders",),
        dimension=("mes_entrega", "Mês de entrega"),
        metrics=(
            _m("encomendas", "Encomendas", COUNT),
            _m("valor", "Valor", MONEY),
            _m("pendentes", "Por entregar", COUNT),
        ),
        chart="colunas",
        limit=24,
        sort_metric="",
    ),
    # ------------------------------------------------------------------ clientes
    Dataset(
        id="clientes-estado",
        label="Clientes por estado",
        description="Contas ativas, em risco e inativas, com a receita e o valor de vida (CLV).",
        group="Clientes",
        sources=("accounts", "orders"),
        dimension=("estado", "Estado do cliente"),
        metrics=(
            _m("clientes", "Clientes", COUNT),
            _m("receita", "Receita", MONEY),
            _m("clv", "CLV", MONEY),
        ),
        sort_metric="clientes",
    ),
    Dataset(
        id="clientes-setor",
        label="Clientes por setor",
        description="Distribuição das contas por setor de atividade e receita associada.",
        group="Clientes",
        sources=("accounts",),
        dimension=("setor", "Setor"),
        metrics=(_m("clientes", "Clientes", COUNT), _m("receita_potencial", "Volume de negócios", MONEY)),
        sort_metric="clientes",
    ),
    Dataset(
        id="clientes-segmento",
        label="Clientes por segmento",
        description="Contas por segmento (chave, empresa, PME) e valor de negócio declarado.",
        group="Clientes",
        sources=("accounts",),
        dimension=("segmento", "Segmento"),
        metrics=(_m("clientes", "Clientes", COUNT), _m("receita_potencial", "Volume de negócios", MONEY)),
        chart="circular",
        sort_metric="clientes",
    ),
    # ----------------------------------------------------------------- operação
    Dataset(
        id="ordens-equipa",
        label="Ordens de trabalho por equipa",
        description="Carga por equipa/técnico: abertas, concluídas, horas, custo e SLA incumprido.",
        group="Operação",
        sources=("work-orders", "teams"),
        dimension=("equipa", "Equipa"),
        metrics=(
            _m("total", "Ordens", COUNT),
            _m("abertas", "Abertas", COUNT),
            _m("concluidas", "Concluídas", COUNT),
            _m("horas", "Horas", NUMBER),
            _m("custo", "Custo", MONEY),
            _m("sla_incumprido", "SLA incumprido", COUNT),
        ),
        sort_metric="total",
    ),
    Dataset(
        id="ordens-tipo",
        label="Ordens por tipo de trabalho",
        description="Instalações, manutenções e reparações: volume, horas e custo por tipo.",
        group="Operação",
        sources=("work-orders",),
        dimension=("tipo", "Tipo"),
        metrics=(
            _m("total", "Ordens", COUNT),
            _m("abertas", "Abertas", COUNT),
            _m("horas", "Horas", NUMBER),
            _m("custo", "Custo", MONEY),
        ),
        chart="circular",
        sort_metric="total",
    ),
    Dataset(
        id="ordens-sla",
        label="Ordens por estado de SLA",
        description="Cumprimento do SLA: ordens cumpridas, em risco e incumpridas.",
        group="Operação",
        sources=("work-orders",),
        dimension=("sla", "Estado do SLA"),
        metrics=(_m("ordens", "Ordens", COUNT), _m("custo", "Custo", MONEY)),
        chart="circular",
        sort_metric="ordens",
    ),
    Dataset(
        id="casos-prioridade",
        label="Casos de apoio por prioridade",
        description="Casos abertos e fechados por prioridade, com escalated e satisfação média.",
        group="Operação",
        sources=("cases",),
        dimension=("prioridade", "Prioridade"),
        metrics=(
            _m("casos", "Casos", COUNT),
            _m("abertos", "Abertos", COUNT),
            _m("escalados", "Escalados", COUNT),
            _m("satisfacao_media", "Satisfação média", NUMBER),
        ),
        chart="colunas",
        sort_metric="casos",
    ),
    # ------------------------------------------------------------------ compras
    Dataset(
        id="compras-fornecedor",
        label="Compras por fornecedor",
        description="Custo de aquisição, unidades e margem associada a cada fornecedor.",
        group="Compras",
        sources=("suppliers", "order-lines"),
        dimension=("fornecedor", "Fornecedor"),
        metrics=(
            _m("custo", "Custo de aquisição", MONEY),
            _m("linhas", "Linhas", COUNT),
            _m("unidades", "Unidades", NUMBER),
            _m("receita", "Receita atribuída", MONEY),
            _m("margem", "Margem", MONEY),
            _m("margem_pct", "Margem (%)", PERCENT),
        ),
        sort_metric="custo",
    ),
    Dataset(
        id="compras-mes",
        label="Compras por mês",
        description="Evolução mensal do custo de aquisição (linhas de encomenda por fornecedor).",
        group="Compras",
        sources=("suppliers", "order-lines", "orders"),
        dimension=("mes", "Mês"),
        metrics=(
            _m("custo", "Custo de aquisição", MONEY),
            _m("unidades", "Unidades", NUMBER),
            _m("linhas", "Linhas", COUNT),
        ),
        chart="linhas",
        limit=24,
        sort_metric="",
    ),
    Dataset(
        id="compras-categoria",
        label="Compras por categoria de fornecedor",
        description="Custo de aquisição por categoria de fornecedor e número de fornecedores.",
        group="Compras",
        sources=("suppliers", "order-lines"),
        dimension=("categoria", "Categoria"),
        metrics=(
            _m("custo", "Custo de aquisição", MONEY),
            _m("fornecedores", "Fornecedores", COUNT),
            _m("margem", "Margem", MONEY),
        ),
        sort_metric="custo",
    ),
    # ----------------------------------------------------------------- comercial
    Dataset(
        id="oportunidades-fase",
        label="Oportunidades por fase",
        description="Pipeline por fase: número de oportunidades, valor e valor ponderado.",
        group="Comercial",
        sources=("opportunities",),
        dimension=("fase", "Fase"),
        metrics=(
            _m("oportunidades", "Oportunidades", COUNT),
            _m("valor", "Valor", MONEY),
            _m("ponderado", "Valor ponderado", MONEY),
        ),
        chart="colunas",
        sort_metric="valor",
    ),
    Dataset(
        id="pipeline-responsavel",
        label="Pipeline por responsável",
        description="Por responsável: negócio aberto, valor em previsão, ganhos e taxa de fecho.",
        group="Comercial",
        sources=("opportunities",),
        dimension=("responsavel", "Responsável"),
        metrics=(
            _m("abertas", "Abertas", COUNT),
            _m("valor", "Valor em pipeline", MONEY),
            _m("ponderado", "Valor ponderado", MONEY),
            _m("ganhas", "Ganhas", COUNT),
            _m("taxa_ganho", "Taxa de ganho (%)", PERCENT),
        ),
        chart="colunas",
        sort_metric="valor",
    ),
    Dataset(
        id="leads-origem",
        label="Leads por origem",
        description="Leads captados por origem, quantos foram convertidos e a pontuação média.",
        group="Comercial",
        sources=("leads",),
        dimension=("origem", "Origem"),
        metrics=(
            _m("leads", "Leads", COUNT),
            _m("convertidos", "Convertidos", COUNT),
            _m("taxa_conversao", "Taxa de conversão (%)", PERCENT),
            _m("pontuacao_media", "Pontuação média", NUMBER),
        ),
        sort_metric="leads",
    ),
    Dataset(
        id="campanhas-retorno",
        label="Campanhas: investimento e retorno",
        description="Custo, receita esperada ganha, ROI e leads gerados por campanha.",
        group="Comercial",
        sources=("campaigns",),
        dimension=("campanha", "Campanha"),
        metrics=(
            _m("custo", "Custo", MONEY),
            _m("receita_esperada", "Receita esperada", MONEY),
            _m("receita_ganha", "Receita ganha", MONEY),
            _m("roi", "ROI (%)", PERCENT),
            _m("leads", "Leads gerados", COUNT),
        ),
        sort_metric="custo",
    ),
)

DATASET_BY_ID: Dict[str, Dataset] = {dataset.id: dataset for dataset in DATASETS}


# ----------------------------------------------------------------- utilitários
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(order: Dict[str, Any], index: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
    return index.get(str(order.get(key) or "")) or {}


def _label(value: Any, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


def _option_label(module_slug: str, field_key: str, value: Any, fallback: str = "") -> str:
    """Etiqueta legível de um valor de opção (`faturada` → «Faturada»).

    Usa as opções declaradas no registo, para os gráficos mostrarem a mesma
    linguagem da lista e do formulário do módulo.
    """
    text = str(value or "").strip()
    if not text:
        return fallback or "—"
    module = registry.MODULE_BY_SLUG.get(module_slug)
    spec = module.field_map.get(field_key) if module else None
    if spec:
        for option, label in spec.options:
            if option == text:
                return label
    return text


class _Table:
    """Acumulador de linhas: dimensão + somas de métricas."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def add(self, key: str, label: str, **values: float) -> Dict[str, Any]:
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = {"key": key, "label": _label(label)}
        for name, value in values.items():
            row[name] = row.get(name, 0.0) + value
        return row

    def ratio(self, key: str, numerator: str, denominator: str, *, scale: float = 100.0) -> None:
        for row in self.rows.values():
            base = row.get(denominator) or 0.0
            row[key] = round((row.get(numerator) or 0.0) / base * scale, 1) if base else 0.0

    def average(self, key: str, source: str, count: str) -> None:
        """Média = soma / número (ex.: satisfação média por prioridade)."""
        for row in self.rows.values():
            total = row.get(count) or 0.0
            row[key] = round((row.get(source) or 0.0) / total, 1) if total else 0.0

    def values(self) -> List[Dict[str, Any]]:
        return list(self.rows.values())


class _Data:
    """Vista sobre os dados do CRM, já limitada ao âmbito do perfil."""

    def __init__(self, perm: Dict[str, Any], months: int) -> None:
        self.perm = perm
        self.months = max(1, min(36, int(months or DEFAULT_MONTHS)))
        self.raw = analytics.dataset(perm)
        self.since = _now() - timedelta(days=31 * self.months)
        self.products = analytics._index(self.raw["products"])
        self.accounts = analytics._index(self.raw["accounts"])
        self.suppliers = analytics._index(self.raw["suppliers"])
        self.teams = analytics._index(analytics._read("teams", perm, 200)) if suite.can_read(perm, "teams") else {}
        self.orders = self.raw["orders"]
        self.lines = self.raw["lines"]
        self.work_orders = self.raw["work_orders"]
        self.opportunities = self.raw["opportunities"]
        self.leads = analytics._read("leads", perm, 4000) if suite.can_read(perm, "leads") else []
        self.cases = analytics._read("cases", perm, 4000) if suite.can_read(perm, "cases") else []
        self.campaigns = analytics._read("campaigns", perm, 1000) if suite.can_read(perm, "campaigns") else []
        self.order_index = analytics._index(self.orders)
        self.orders_by_month: Dict[str, List[Dict[str, Any]]] = {}
        for order in self.orders:
            moment = analytics._moment(order.get("order_date"))
            if moment:
                self.orders_by_month.setdefault(analytics._month_key(moment), []).append(order)

    # ------------------------------------------------------------------ filtros
    def realized(self) -> List[Dict[str, Any]]:
        """Encomendas realizadas (confirmadas, em produção, enviadas ou faturadas)."""
        return [order for order in self.window() if str(order.get("status")) in analytics.STATUS_REALIZADA]

    def window(self) -> List[Dict[str, Any]]:
        return [order for order in self.orders if (analytics._moment(order.get("order_date")) or _now()) >= self.since]

    def lines_of(self, orders: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ids = {str(order.get("id")) for order in orders}
        return [line for line in self.lines if str(line.get("order_id")) in ids and str(line.get("status")) != "cancelada"]

    def period(self) -> Dict[str, Any]:
        return {
            "meses": self.months,
            "desde": self.since.date().isoformat(),
            "encomendas": len(self.orders),
            "linhas": len(self.lines),
            "contas": len(self.accounts),
            "produtos": len(self.products),
            "fornecedores": len(self.suppliers),
            "ordens_trabalho": len(self.work_orders),
            "oportunidades": len(self.opportunities),
        }


# ------------------------------------------------------------- construtores
# Cada construtor recebe os dados já filtrados e o limite de linhas e devolve a
# lista de linhas do dataset (a ordenação/limite final é feita em `rows`).


def _vendas_utilizador(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    orders = data.realized()
    for order in orders:
        table.add(
            _label(order.get("owner_email"), "Sem responsável"),
            _label(order.get("owner_email"), "Sem responsável"),
            receita=analytics._number(order.get("total")),
            encomendas=1.0,
        )
    sellers = {str(order.get("id")): _label(order.get("owner_email"), "Sem responsável") for order in orders}
    for line in data.lines_of(orders):
        seller = sellers.get(str(line.get("order_id")))
        if not seller:
            continue
        quantity = analytics._number(line.get("quantity"))
        table.add(
            seller,
            seller,
            unidades=quantity,
            margem=analytics._number(line.get("line_total")) - analytics._number(line.get("unit_cost")) * quantity,
        )
    rows = table.values()
    for row in rows:
        orders_count = row.get("encomendas") or 0.0
        row["ticket_medio"] = round((row.get("receita") or 0.0) / orders_count, 2) if orders_count else 0.0
    table.ratio("margem_pct", "margem", "receita")
    return rows


def _vendas_cliente(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    orders = data.realized()
    for order in orders:
        account = _get(order, data.accounts, "account_id")
        key = str(order.get("account_id") or "sem-conta")
        row = table.add(
            key,
            _label(account.get("name"), "Sem conta"),
            receita=analytics._number(order.get("total")),
            encomendas=1.0,
        )
        stamp = str(order.get("order_date") or "")[:10]
        if stamp > str(row.get("ultima_encomenda") or ""):
            row["ultima_encomenda"] = stamp
    sellers = {str(order.get("id")): str(order.get("account_id") or "sem-conta") for order in orders}
    for line in data.lines_of(orders):
        key = sellers.get(str(line.get("order_id")))
        if not key:
            continue
        quantity = analytics._number(line.get("quantity"))
        table.add(
            key,
            (data.accounts.get(key) or {}).get("name") or "Sem conta",
            margem=analytics._number(line.get("line_total")) - analytics._number(line.get("unit_cost")) * quantity,
        )
    for row in table.values():
        count = row.get("encomendas") or 0.0
        row["ticket_medio"] = round((row.get("receita") or 0.0) / count, 2) if count else 0.0
    return table.values()


def _vendas_produto(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for line in data.lines_of(data.realized()):
        product = _get(line, data.products, "product_id")
        key = str(line.get("product_id") or "sem-produto")
        quantity = analytics._number(line.get("quantity"))
        table.add(
            key,
            _label(product.get("name"), _label(line.get("description"), "Sem produto")),
            receita=analytics._number(line.get("line_total")),
            unidades=quantity,
            margem=analytics._number(line.get("line_total")) - analytics._number(line.get("unit_cost")) * quantity,
        )
    table.ratio("margem_pct", "margem", "receita")
    return table.values()


def _vendas_categoria(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for line in data.lines_of(data.realized()):
        product = _get(line, data.products, "product_id")
        category = _option_label("products", "category", product.get("category"), "Sem categoria")
        quantity = analytics._number(line.get("quantity"))
        table.add(
            category,
            category,
            receita=analytics._number(line.get("line_total")),
            unidades=quantity,
            margem=analytics._number(line.get("line_total")) - analytics._number(line.get("unit_cost")) * quantity,
        )
    table.ratio("margem_pct", "margem", "receita")
    return table.values()


def _vendas_mes(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for month, orders in data.orders_by_month.items():
        realized = [order for order in orders if str(order.get("status")) in analytics.STATUS_REALIZADA]
        if not realized:
            continue
        value = sum(analytics._number(order.get("total")) for order in realized)
        billed = sum(
            analytics._number(order.get("total"))
            for order in orders
            if str(order.get("status")) in analytics.STATUS_FATURADA
        )
        table.add(month, month, receita=value, encomendas=float(len(realized)), faturada=billed)
    for row in table.values():
        count = row.get("encomendas") or 0.0
        row["ticket_medio"] = round((row.get("receita") or 0.0) / count, 2) if count else 0.0
    return sorted(table.values(), key=lambda row: row["key"])


def _encomendas_estado(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for order in data.window():
        state = str(order.get("status") or "")
        label = _option_label("orders", "status", state, "Sem estado")
        table.add(label, label, encomendas=1.0, valor=analytics._number(order.get("total")))
    return table.values()


def _encomendas_mes(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for month, orders in data.orders_by_month.items():
        pending = [order for order in orders if str(order.get("status")) in analytics.STATUS_ABERTA]
        billed = [order for order in orders if str(order.get("status")) in analytics.STATUS_FATURADA]
        table.add(
            month,
            month,
            encomendas=float(len(orders)),
            valor=sum(analytics._number(order.get("total")) for order in orders),
            pendentes=float(len(pending)),
            faturadas=float(len(billed)),
        )
    return sorted(table.values(), key=lambda row: row["key"])


def _encomendas_cliente(data: _Data, limit: int) -> List[Dict[str, Any]]:
    today = _now().date().isoformat()
    table = _Table()
    for order in data.window():
        account = _get(order, data.accounts, "account_id")
        key = str(order.get("account_id") or "sem-conta")
        late = (
            1.0
            if str(order.get("status")) in analytics.STATUS_ABERTA
            and str(order.get("delivery_date") or "")[:10]
            and str(order["delivery_date"])[:10] < today
            else 0.0
        )
        table.add(
            key,
            _label(account.get("name"), "Sem conta"),
            encomendas=1.0,
            valor=analytics._number(order.get("total")),
            atrasadas=late,
        )
    for row in table.values():
        count = row.get("encomendas") or 0.0
        row["ticket_medio"] = round((row.get("valor") or 0.0) / count, 2) if count else 0.0
    return table.values()


def _entregas_mes(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for order in data.orders:
        moment = analytics._moment(order.get("delivery_date"))
        if not moment:
            continue
        month = analytics._month_key(moment)
        table.add(
            month,
            month,
            encomendas=1.0,
            valor=analytics._number(order.get("total")),
            pendentes=1.0 if str(order.get("status")) in analytics.STATUS_ABERTA else 0.0,
        )
    return sorted(table.values(), key=lambda row: row["key"])


def _clientes_estado(data: _Data, limit: int) -> List[Dict[str, Any]]:
    # Reutiliza o cálculo de clientes do painel (CLV, inatividade) e agrega por estado.
    blocks = analytics._customer_blocks(
        data.raw,
        months=data.months,
        top=5000,
        days_without_purchase=analytics.DEFAULT_DAYS_WITHOUT_PURCHASE,
    )
    every: List[Dict[str, Any]] = [
        *(blocks.get("top_clv") or []),
        *(blocks.get("nunca_compraram") or []),
    ]
    table = _Table()
    for row in every:
        state = _label(row.get("estado"), "sem histórico")
        table.add(
            state,
            state,
            clientes=1.0,
            receita=analytics._number(row.get("receita_periodo")),
            clv=analytics._number(row.get("clv")),
        )
    return table.values()


def _clientes_campo(data: _Data, field: str, fallback: str, value_field: Optional[str] = None) -> List[Dict[str, Any]]:
    table = _Table()
    for account in data.accounts:
        key = _label(account.get(field), fallback)
        table.add(key, key, clientes=1.0, receita_potencial=analytics._number(account.get(value_field or "annual_revenue")))
    return table.values()


def _clientes_setor(data: _Data, limit: int) -> List[Dict[str, Any]]:
    return _clientes_campo(data, "industry", "Sem setor")


def _clientes_segmento(data: _Data, limit: int) -> List[Dict[str, Any]]:
    tiers = {"A": "Conta-chave (A)", "B": "Empresa (B)", "C": "PME (C)"}
    table = _Table()
    for account in data.accounts:
        raw = _label(account.get("tier"), "")
        key = tiers.get(raw, _label(account.get("tier"), "Sem segmento"))
        table.add(key, key, clientes=1.0, receita_potencial=analytics._number(account.get("annual_revenue")))
    return table.values()


def _ordens_equipa(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for item in data.work_orders:
        key = str(item.get("team_id") or item.get("technician_email") or "sem-equipa")
        label = (
            (data.teams.get(key) or {}).get("name")
            or item.get("technician_email")
            or ("Sem equipa atribuída" if key == "sem-equipa" else key)
        )
        state = str(item.get("status"))
        table.add(
            key,
            label,
            total=1.0,
            abertas=1.0 if state in analytics.WORK_OPEN else 0.0,
            concluidas=1.0 if state in analytics.WORK_DONE else 0.0,
            horas=analytics._number(item.get("actual_hours")),
            custo=analytics._number(item.get("cost")),
            sla_incumprido=1.0 if str(item.get("sla_state")) == "incumprido" else 0.0,
        )
    return table.values()


def _ordens_tipo(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for item in data.work_orders:
        kind = _option_label("work-orders", "work_type", item.get("work_type"), "Sem tipo")
        table.add(
            kind,
            kind,
            total=1.0,
            abertas=1.0 if str(item.get("status")) in analytics.WORK_OPEN else 0.0,
            horas=analytics._number(item.get("actual_hours")),
            custo=analytics._number(item.get("cost")),
        )
    return table.values()


def _ordens_sla(data: _Data, limit: int) -> List[Dict[str, Any]]:
    labels = {"cumprido": "Cumprido", "em-risco": "Em risco", "incumprido": "Incumprido"}
    table = _Table()
    for item in data.work_orders:
        state = str(item.get("sla_state") or "sem-sla")
        table.add(state, labels.get(state, "Sem SLA definido"), ordens=1.0, custo=analytics._number(item.get("cost")))
    return table.values()


def _casos_prioridade(data: _Data, limit: int) -> List[Dict[str, Any]]:
    closed = ("resolvido", "fechado", "cancelado")
    table = _Table()
    for case in data.cases:
        priority = _option_label("cases", "priority", case.get("priority"), "Sem prioridade")
        table.add(
            priority,
            priority,
            casos=1.0,
            abertos=0.0 if str(case.get("status")) in closed else 1.0,
            escalados=1.0 if analytics._number(case.get("escalated")) else 0.0,
            satisfacao=analytics._number(case.get("satisfaction")),
        )
    table.average("satisfacao_media", "satisfacao", "casos")
    for row in table.values():
        row.pop("satisfacao", None)
    return table.values()


def _compras_fornecedor(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for line in data.lines:
        supplier_id = str(line.get("supplier_id") or "")
        if not supplier_id:
            continue
        quantity = analytics._number(line.get("quantity"))
        cost = analytics._number(line.get("unit_cost")) * quantity
        revenue = analytics._number(line.get("line_total"))
        table.add(
            supplier_id,
            _label((data.suppliers.get(supplier_id) or {}).get("name"), supplier_id),
            custo=cost,
            linhas=1.0,
            unidades=quantity,
            receita=revenue,
            margem=revenue - cost,
        )
    table.ratio("margem_pct", "margem", "receita")
    return table.values()


def _compras_mes(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for line in data.lines:
        if not line.get("supplier_id"):
            continue
        order = data.order_index.get(str(line.get("order_id")))
        moment = analytics._moment((order or {}).get("order_date"))
        if not moment:
            continue
        month = analytics._month_key(moment)
        table.add(
            month,
            month,
            custo=analytics._number(line.get("unit_cost")) * analytics._number(line.get("quantity")),
            unidades=analytics._number(line.get("quantity")),
            linhas=1.0,
        )
    return sorted(table.values(), key=lambda row: row["key"])


def _compras_categoria(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    categories: Dict[str, set] = {}
    for line in data.lines:
        supplier_id = str(line.get("supplier_id") or "")
        if not supplier_id:
            continue
        supplier = data.suppliers.get(supplier_id) or {}
        category = _option_label("suppliers", "category", supplier.get("category"), "Sem categoria")
        quantity = analytics._number(line.get("quantity"))
        cost = analytics._number(line.get("unit_cost")) * quantity
        revenue = analytics._number(line.get("line_total"))
        table.add(category, category, custo=cost, margem=revenue - cost)
        categories.setdefault(category, set()).add(supplier_id)
    for key, suppliers in categories.items():
        if key in table.rows:
            table.rows[key]["fornecedores"] = float(len(suppliers))
    return table.values()


def _oportunidades_fase(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for deal in data.opportunities:
        stage = _option_label("opportunities", "stage", deal.get("stage"), "Sem fase")
        table.add(
            stage,
            stage,
            oportunidades=1.0,
            valor=analytics._number(deal.get("amount")),
            ponderado=analytics._number(deal.get("weighted_amount")),
        )
    return table.values()


def _pipeline_responsavel(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for deal in data.opportunities:
        owner = _label(deal.get("owner_email"), "Sem responsável")
        stage = str(deal.get("stage"))
        open_deal = stage not in ("ganho", "perdido")
        table.add(
            owner,
            owner,
            abertas=1.0 if open_deal else 0.0,
            valor=analytics._number(deal.get("amount")) if open_deal else 0.0,
            ponderado=analytics._number(deal.get("weighted_amount")) if open_deal else 0.0,
            ganhas=1.0 if stage == "ganho" else 0.0,
            fechadas=1.0 if stage in ("ganho", "perdido") else 0.0,
        )
    table.ratio("taxa_ganho", "ganhas", "fechadas")
    for row in table.values():
        row.pop("fechadas", None)
    return table.values()


def _leads_origem(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for lead in data.leads:
        source = _option_label("leads", "source", lead.get("source"), "Sem origem")
        converted = 1.0 if str(lead.get("status")) == "convertido" else 0.0
        table.add(source, source, leads=1.0, convertidos=converted, pontuacao=analytics._number(lead.get("score")))
    table.ratio("taxa_conversao", "convertidos", "leads")
    table.average("pontuacao_media", "pontuacao", "leads")
    for row in table.values():
        row.pop("pontuacao", None)
    return table.values()


def _campanhas_retorno(data: _Data, limit: int) -> List[Dict[str, Any]]:
    table = _Table()
    for campaign in data.campaigns:
        name = _label(campaign.get("name"), "Sem nome")
        cost = analytics._number(campaign.get("actual_cost") or campaign.get("budget"))
        won = analytics._number(campaign.get("won_revenue"))
        table.add(
            str(campaign.get("id") or name),
            name,
            custo=cost,
            receita_esperada=analytics._number(campaign.get("expected_revenue")),
            receita_ganha=won,
            roi=0.0,
            leads=analytics._number(campaign.get("leads_generated")),
        )
    # O ROI é um valor calculado por campanha (não uma soma).
    for row in table.values():
        cost = row.get("custo") or 0.0
        row["roi"] = round(((row.get("receita_ganha") or 0.0) - cost) / cost * 100.0, 1) if cost else 0.0
    return table.values()


_BUILDERS: Dict[str, Callable[[_Data, int], List[Dict[str, Any]]]] = {
    "vendas-utilizador": _vendas_utilizador,
    "vendas-cliente": _vendas_cliente,
    "vendas-produto": _vendas_produto,
    "vendas-categoria": _vendas_categoria,
    "vendas-mes": _vendas_mes,
    "encomendas-estado": _encomendas_estado,
    "encomendas-mes": _encomendas_mes,
    "encomendas-cliente": _encomendas_cliente,
    "entregas-mes": _entregas_mes,
    "clientes-estado": _clientes_estado,
    "clientes-setor": _clientes_setor,
    "clientes-segmento": _clientes_segmento,
    "ordens-equipa": _ordens_equipa,
    "ordens-tipo": _ordens_tipo,
    "ordens-sla": _ordens_sla,
    "casos-prioridade": _casos_prioridade,
    "compras-fornecedor": _compras_fornecedor,
    "compras-mes": _compras_mes,
    "compras-categoria": _compras_categoria,
    "oportunidades-fase": _oportunidades_fase,
    "pipeline-responsavel": _pipeline_responsavel,
    "leads-origem": _leads_origem,
    "campanhas-retorno": _campanhas_retorno,
}


# ----------------------------------------------------------------- API interna
def _allowed(dataset: Dataset, perm: Dict[str, Any]) -> bool:
    return all(suite.can_read(perm, slug) for slug in dataset.sources)


def catalogue(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Datasets que o perfil pode usar (todos os que consegue ler por inteiro)."""
    available = [dataset for dataset in DATASETS if _allowed(dataset, perm)]
    groups: List[str] = []
    for dataset in available:
        if dataset.group not in groups:
            groups.append(dataset.group)
    return {
        "datasets": [dataset.to_public() for dataset in available],
        "groups": groups,
        "total": len(available),
        "ignorados": [dataset.id for dataset in DATASETS if not _allowed(dataset, perm)],
        "charts": list(CHARTS),
        "gerado_em": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _round(row: Dict[str, Any], dataset: Dataset) -> Dict[str, Any]:
    label = row.get("label") if row.get("label") not in (None, "") else "—"
    formatted: Dict[str, Any] = {"key": row.get("key"), "label": label}
    # A dimensão aparece também com o seu próprio nome (`responsavel`, `mes`…),
    # para um gráfico poder referi-la sem saber que a chave é «label».
    formatted[dataset.dimension[0]] = label
    for metric in dataset.metrics:
        value = row.get(metric.key)
        if metric.kind == TEXT:
            formatted[metric.key] = value if value not in (None, "") else "—"
        elif metric.kind == COUNT:
            formatted[metric.key] = int(round(float(value or 0.0)))
        else:
            formatted[metric.key] = round(float(value or 0.0), 2)
    return formatted


def rows(
    dataset_id: str,
    perm: Dict[str, Any],
    *,
    months: int = DEFAULT_MONTHS,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Linhas de um dataset, já ordenadas e limitadas (dados reais do CRM)."""
    dataset = DATASET_BY_ID.get(dataset_id)
    if dataset is None:
        return {"error": f"Conjunto de dados desconhecido: {dataset_id}"}
    missing = [slug for slug in dataset.sources if not suite.can_read(perm, slug)]
    if missing:
        return {"error": f"O perfil não tem acesso aos dados de {', '.join(missing)}"}
    builder = _BUILDERS.get(dataset.id)
    if builder is None:  # pragma: no cover - proteção contra registo incompleto
        return {"error": f"Conjunto de dados sem construtor: {dataset.id}"}

    data = _Data(perm, months)
    try:
        built = builder(data, dataset.limit)
    except Exception as exc:  # pragma: no cover - dados heterogéneos
        logger.warning("CRM datasets: falha a calcular %s: %s", dataset.id, exc)
        return {"error": f"Não foi possível calcular «{dataset.label}»: {exc}"}

    metric = dataset.sort_metric
    if metric:
        built = [row for row in built if row.get(metric) is not None]
        built.sort(key=lambda row: (row.get(metric) or 0.0, str(row.get("label") or "")), reverse=True)
    elif dataset.chart == "linhas":
        built = sorted(built, key=lambda row: str(row.get("key") or ""))
    else:
        built = sorted(built, key=lambda row: (row.get("label") or ""))

    size = max(1, min(MAX_LIMIT, int(limit or dataset.limit)))
    shown = built[:size]
    formatted = [_round(row, dataset) for row in shown]

    totals: Dict[str, Any] = {}
    for spec in dataset.metrics:
        if spec.kind == TEXT:
            continue
        if spec.kind == PERCENT:
            values = [analytics._number(row.get(spec.key)) for row in built]
            totals[spec.key] = round(sum(values) / len(values), 1) if values else 0.0
        else:
            total = sum(analytics._number(row.get(spec.key)) for row in built)
            totals[spec.key] = int(round(total)) if spec.kind == COUNT else round(total, 2)

    return {
        "id": dataset.id,
        "label": dataset.label,
        "description": dataset.description,
        "group": dataset.group,
        "dimension": {"key": dataset.dimension[0], "label": dataset.dimension[1]},
        "metrics": [metric.to_public() for metric in dataset.metrics],
        "chart": dataset.chart,
        "rows": formatted,
        "totals": totals,
        "linhas_totais": len(built),
        "linhas_mostradas": len(formatted),
        "filtros": data.period(),
        "gerado_em": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def widget_rows(widgets: Sequence[Dict[str, Any]], perm: Dict[str, Any], *, months: int) -> Dict[str, Any]:
    """Calcula de uma vez as linhas de vários widgets (um quadro completo).

    Cada widget referencia um dataset; datasets repetidos são lidos uma só vez.
    """
    results: Dict[str, Any] = {}
    for widget in widgets:
        dataset_id = str((widget or {}).get("dataset") or "")
        if not dataset_id or dataset_id in results:
            continue
        limit = (widget or {}).get("limit")
        results[dataset_id] = rows(
            dataset_id,
            perm,
            months=months,
            limit=int(limit) if isinstance(limit, (int, float)) and limit else None,
        )
    return results
