"""Templates de dashboards do Visualizador.

Cada template é um **dashboard completo** (visuais, dimensões, medidas, filtros)
para um dataset, escrito à mão a partir do que a plataforma tem de facto: serve
de ponto de partida para quem não quer construir o primeiro ecrã a partir do zero.

Os templates são validados contra o catálogo em tempo de execução
(`resolve_templates`): se um campo ou medida deixar de existir (a ontologia mudou,
o índice ganhou outro nome), esse campo é retirado e fica um aviso no template —
nunca se devolve uma definição que dê gráficos vazios sem explicação.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import visualizador_service as service
from api.elasticsearch_client import get_es_client

logger = logging.getLogger(__name__)

# Volume das fontes (para avisar quando um dashboard nasceria vazio). O valor é
# cacheado porque a galeria pede todos os templates de uma vez.
_volume_cache: Dict[str, Tuple[float, int]] = {}
_VOLUME_TTL = 120
#: Abaixo deste número de registos, o template é marcado como «escasso».
SPARSE_THRESHOLD = 25


def _visual(visual_id: str, title: str, chart: str, dimensions: Sequence[Any], measures: Sequence[Any],
            *, formulas: Optional[Sequence[Dict[str, Any]]] = None, limit: int = 25, top_n: int = 0,
            others: bool = False, sort: Optional[Dict[str, str]] = None, width: int = 6) -> Dict[str, Any]:
    """Constrói um visual (mesma forma que o cliente guarda)."""
    return {
        "id": visual_id,
        "title": title,
        "chart": chart,
        "dimensions": [entry if isinstance(entry, dict) else {"id": entry} for entry in dimensions],
        "measures": list(measures),
        "formulas": list(formulas or []),
        "limit": limit,
        "top_n": top_n,
        "others": others,
        "sort": sort or {"by": "", "order": "desc"},
        "width": width,
    }


def _sum(prop: str, field: str, label: str, unit: Optional[str] = None) -> Dict[str, Any]:
    return {"kind": "soma", "field": prop, "label": label, "format": "currency" if unit == "€" else "number"}


# ---------------------------------------------------------------------------
# Catálogo de templates
# ---------------------------------------------------------------------------
TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "contratos_visao_geral",
        "name": "Contratos Públicos — Visão geral",
        "description": "Indicadores, evolução anual, regiões, tipo de contrato, procedimento e maiores adjudicatários.",
        "domain": "contratacao",
        "dataset": "contrato",
        "icon": "file-text",
        "tags": ["executivo", "contratação"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores gerais", "kpi", [], ["contagem", "soma_preco", "media_preco"],
                    formulas=[{"id": "ticket_medio", "label": "Ticket médio", "expression": "[Soma de Preço contratual] / [Contagem]", "format": "currency"}],
                    width=12),
            _visual("evolucao", "Evolução por ano", "area", ["ano"], ["soma_preco"], width=8),
            _visual("regioes", "Valor por região", "bar-h", ["regiao"], ["soma_preco"], top_n=12, width=4),
            _visual("tipos", "Tipo de contrato", "donut", ["tipo_contrato"], ["contagem"], width=4),
            _visual("procedimentos", "Tipo de procedimento", "donut", ["procedimento"], ["contagem"], width=4),
            _visual("adjudicatarios", "Maiores adjudicatários", "bar-h", ["adjudicatario"], ["contagem", "soma_preco"],
                    top_n=10, width=4),
            _visual("tabela", "Detalhe por ano e tipo", "matrix", ["ano", "tipo_contrato"], ["contagem", "soma_preco"], width=12),
        ],
    },
    {
        "id": "contratos_cpv",
        "name": "Contratação por CPV",
        "description": "Onde está o dinheiro por classificação europeia: top CPV, valor médio e distribuição por região.",
        "domain": "contratacao",
        "dataset": "cpv",
        "icon": "tags",
        "tags": ["compras", "cpv"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "valor", "valor_medio"], width=12),
            _visual("top_cpv", "Top 15 CPV por valor", "bar-h", ["cpv"], ["valor"], top_n=15, width=6),
            _visual("cpv_contratos", "Top 15 CPV por contratos", "bar-h", ["cpv"], ["contagem"], top_n=15, width=6),
            _visual("regioes", "Valor por região (desses CPV)", "donut", ["regiao"], ["valor"], top_n=8, width=6),
            _visual("anos", "Evolução anual", "line", ["ano"], ["valor"], width=6),
        ],
    },
    {
        "id": "mercados_noticias",
        "name": "Mercados — Notícias e sentimento",
        "description": "Volume de notícias por mês, publicadores, instrumentos e sentimento associado.",
        "domain": "mercados",
        "dataset": "noticia",
        "icon": "newspaper",
        "tags": ["notícias", "sentimento"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", {"kind": "distintos", "field": "titulo", "label": "Títulos distintos"}], width=12),
            _visual("meses", "Notícias por mês", "line", [{"id": "publicado", "interval": "mes"}], ["contagem"], width=8),
            _visual("publicadores", "Publicadores", "donut", ["publicador"], ["contagem"], top_n=8, width=4),
            _visual("tickers", "Instrumentos mais mencionados", "bar-h", ["ticker"], ["contagem"], top_n=12, width=6),
            _visual("sentimento", "Sentimento", "donut", ["sentimento"], ["contagem"], width=6),
            _visual("temas", "Temas", "bar-h", ["topicos"], ["contagem"], top_n=12, width=12),
        ],
    },
    {
        "id": "mercados_cotacoes",
        "name": "Mercados — Cotações",
        "description": "Séries de fecho e volume por instrumento, com mínimos, médias e máximos.",
        "domain": "mercados",
        "dataset": "cotacao",
        "icon": "trending-up",
        "tags": ["trading", "séries"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "soma_volume", "media_fecho", "maximo_fecho"], width=12),
            _visual("serie", "Fecho médio por mês", "line", [{"id": "data", "interval": "mes"}], ["media_fecho"], width=8),
            _visual("volume", "Volume por instrumento", "bar-h", ["ticker"], ["soma_volume"], top_n=12, width=4),
            _visual("instrumentos", "Fecho médio por instrumento", "bar-h", ["ticker"], ["media_fecho"], top_n=12, width=6),
            _visual("periodos", "Registos por período", "donut", ["periodo"], ["contagem"], width=6),
        ],
    },
    {
        "id": "marcas_inpi",
        "name": "Marcas (INPI)",
        "description": "Marcas por tipo, modalidade, fase processual e evolução dos pedidos.",
        "domain": "contratacao",
        "dataset": "marca",
        "icon": "badge-check",
        "tags": ["propriedade industrial"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem",
                                                       {"kind": "distintos", "field": "titular", "label": "Titulares distintos"},
                                                       {"kind": "distintos", "field": "nome", "label": "Marcas distintas"}], width=12),
            _visual("pedidos", "Pedidos por ano", "line", [{"id": "data_pedido", "interval": "ano"}], ["contagem"], width=8),
            _visual("tipos", "Tipo de marca", "donut", ["tipo"], ["contagem"], width=4),
            _visual("fases", "Fase atual", "bar-h", ["fase"], ["contagem"], top_n=12, width=6),
            _visual("titulares", "Maiores titulares", "bar-h", ["titular"], ["contagem"], top_n=12, width=6),
        ],
    },
    {
        "id": "firmas_rnpc",
        "name": "Firmas (RNPC)",
        "description": "Firmas admitidas por concelho, situação, CAE principal e score de semelhança.",
        "domain": "contratacao",
        "dataset": "firma",
        "icon": "scroll-text",
        "tags": ["registos", "empresas"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "media_score", "maximo_score"], width=12),
            _visual("concelhos", "Firmas por concelho", "bar-h", ["concelho"], ["contagem"], top_n=15, width=6),
            _visual("situacoes", "Situação", "donut", ["situacao"], ["contagem"], width=6),
            _visual("cae", "CAE principal", "bar-h", ["cae"], ["contagem"], top_n=15, width=12),
        ],
    },
    {
        "id": "crm_pipeline",
        "name": "CRM — Pipeline comercial",
        "description": "Oportunidades por fase, valor, probabilidade e fecho previsto (dados privados do utilizador).",
        "domain": "crm",
        "dataset": "oportunidade",
        "icon": "target",
        "tags": ["crm", "comercial"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "soma_valor", "soma_valor_ponderado", "media_probabilidade"], width=12),
            _visual("fases", "Valor por fase", "donut", ["fase"], ["soma_valor"], width=4),
            _visual("origens", "Origem das oportunidades", "bar-h", ["origem"], ["contagem"], top_n=10, width=4),
            _visual("fecho", "Fecho previsto", "line", [{"id": "fecho_previsto", "interval": "mes"}], ["soma_valor"], width=4),
            _visual("tabela", "Oportunidades por fase e mês", "matrix", ["fase", {"id": "fecho_previsto", "interval": "mes"}],
                    ["contagem", "soma_valor"], width=12),
        ],
    },
    {
        "id": "recolha_fontes",
        "name": "Recolha — Fontes e volume",
        "description": "Itens recolhidos por fonte, etiqueta e mês, para acompanhar a atualidade da recolha.",
        "domain": "scraper",
        "dataset": "recolha",
        "icon": "database",
        "tags": ["scraping", "monitorização"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem"], width=12),
            _visual("fontes", "Itens por fonte", "bar-h", ["fonte"], ["contagem"], top_n=15, width=6),
            _visual("meses", "Itens por mês", "line", [{"id": "recolhido_em", "interval": "mes"}], ["contagem"], width=6),
            _visual("etiquetas", "Etiquetas", "donut", ["etiqueta"], ["contagem"], top_n=10, width=6),
            _visual("acionadores", "Acionador da recolha", "donut", ["acionador"], ["contagem"], width=6),
        ],
    },
    {
        "id": "office_documentos",
        "name": "Office — Documentos",
        "description": "Documentos escritos na plataforma por tipo, pasta e autor, com volume de palavras.",
        "domain": "office",
        "dataset": "documento",
        "icon": "book-open",
        "tags": ["office", "conteúdos"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "palavras", "palavras_media"], width=12),
            _visual("tipos", "Documentos por tipo", "donut", ["tipo"], ["contagem"], width=4),
            _visual("pastas", "Documentos por pasta", "bar-h", ["pasta"], ["contagem", "palavras"], top_n=12, width=4),
            _visual("autores", "Autores", "bar-h", ["autor"], ["contagem"], top_n=10, width=4),
            _visual("tempo", "Documentos por mês", "line", [{"id": "atualizado_em", "interval": "mes"}], ["contagem"], width=12),
        ],
    },
    {
        "id": "dossies_360",
        "name": "Dossiês 360 — Volumetria",
        "description": "Dossiês por projeto, tema e etiqueta, com itens recolhidos, evidências e sentimento médio.",
        "domain": "search360",
        "dataset": "dossie",
        "icon": "telescope",
        "tags": ["pesquisa 360", "dossiês"],
        "filters": {},
        "visuals": [
            _visual("kpis", "Indicadores", "kpi", [], ["contagem", "itens", "evidencias", "sentimento_medio"], width=12),
            _visual("projetos", "Dossiês por projeto", "bar-h", ["projeto"], ["contagem", "itens"], top_n=12, width=6),
            _visual("temas", "Temas mais trabalhados", "bar-h", ["termo"], ["contagem"], top_n=12, width=6),
            _visual("sentimento", "Sentimento dos dossiês", "donut", ["sentimento"], ["contagem"], width=6),
            _visual("meses", "Dossiês por mês", "line", [{"id": "atualizado_em", "interval": "mes"}], ["contagem"], width=6),
        ],
    },
]


def template_ids() -> List[str]:
    return [template["id"] for template in TEMPLATES]


def get_template(template_id: str) -> Dict[str, Any]:
    for template in TEMPLATES:
        if template["id"] == template_id:
            return template
    raise KeyError(f"Template desconhecido: {template_id}")


# ---------------------------------------------------------------------------
# Validação contra o catálogo (à prova de mudanças na ontologia)
# ---------------------------------------------------------------------------
def _validate_visual(dataset: Dict[str, Any], visual: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Retira campos que já não existem no dataset e reporta o que foi retirado."""
    warnings: List[str] = []
    dimension_ids = {entry["id"] for entry in dataset.get("dimensions") or []}
    measure_ids = {entry["id"] for entry in dataset.get("measures") or []}

    dimensions: List[Dict[str, Any]] = []
    for entry in visual.get("dimensions") or []:
        key = entry["id"] if isinstance(entry, dict) else str(entry)
        if key in dimension_ids:
            dimensions.append(entry if isinstance(entry, dict) else {"id": key})
        else:
            warnings.append(f"«{visual['title']}»: dimensão `{key}` não existe em `{dataset['id']}`.")

    measures: List[Any] = []
    for entry in visual.get("measures") or []:
        if isinstance(entry, str):
            if entry in measure_ids or entry == "contagem":
                measures.append(entry)
            else:
                warnings.append(f"«{visual['title']}»: medida `{entry}` não existe em `{dataset['id']}`.")
            continue
        if not isinstance(entry, dict):
            continue
        spec = dict(entry)
        field = spec.get("field")
        if spec.get("kind") and spec.get("kind") != "contagem":
            if field and field not in dimension_ids:
                warnings.append(f"«{visual['title']}»: campo `{field}` da medida personalizada não existe.")
                continue
        elif spec.get("id") and spec["id"] not in measure_ids:
            warnings.append(f"«{visual['title']}»: medida `{spec['id']}` não existe.")
            continue
        measures.append(spec)

    resolved = {**visual, "dimensions": dimensions, "measures": measures}
    return resolved, warnings


def _dataset_volume(dataset: Dict[str, Any], es: Any = None) -> Optional[int]:
    """Quantos registos tem a fonte agora (ou `None` se não for possível saber)."""
    key = dataset["id"]
    now = time.time()
    cached = _volume_cache.get(key)
    if cached and now - cached[0] < _VOLUME_TTL:
        return cached[1]
    volume: Optional[int] = None
    try:
        if dataset["kind"] == "local":
            volume = len(service._local_rows(dataset["id"], None))  # noqa: SLF001 (leitura direta do ficheiro)
        elif dataset.get("index"):
            client = es or get_es_client()
            if client:
                query: Dict[str, Any] = dataset.get("filter") or {"match_all": {}}
                volume = client.count(index=dataset["index"], body={"query": query})["count"]
    except Exception as exc:
        logger.debug("Não foi possível contar os registos de %s: %s", key, exc)
        volume = None
    if volume is not None:
        _volume_cache[key] = (now, volume)
    return volume


def resolve_templates(scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Templates validados contra o catálogo atual (para a página de dashboards)."""
    datasets: Dict[str, Dict[str, Any]] = {}
    items: List[Dict[str, Any]] = []
    for template in TEMPLATES:
        warnings: List[str] = []
        try:
            dataset = service.get_dataset(template["dataset"])
        except KeyError:
            logger.warning("Template %s aponta para dataset inexistente: %s", template["id"], template["dataset"])
            continue
        datasets[dataset["id"]] = dataset

        visuals: List[Dict[str, Any]] = []
        for visual in template["visuals"]:
            resolved, visual_warnings = _validate_visual(dataset, visual)
            warnings.extend(visual_warnings)
            if not resolved["measures"]:
                warnings.append(f"«{resolved['title']}» foi retirado por não ter medidas válidas.")
                continue
            visuals.append(resolved)

        summary = service._dataset_summary(dataset, scope)  # noqa: SLF001 (resumo reutilizado)
        volume = _dataset_volume(dataset) if summary["available"] else None
        sparse = volume is not None and volume < SPARSE_THRESHOLD
        data_note = None
        if sparse:
            data_note = (
                f"Esta fonte tem apenas {volume} registo(s) indexado(s): o dashboard vai aparecer praticamente vazio. "
                "Carregue dados no módulo respetivo (ou use outro dataset) antes de o usar como exemplo."
            )
        items.append({
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "domain": template.get("domain"),
            "icon": template.get("icon"),
            "tags": template.get("tags") or [],
            "dataset": dataset["id"],
            "dataset_label": summary["label"],
            "requires_session": summary["requires_session"],
            "available": bool(summary["available"] and visuals),
            "note": summary.get("note"),
            "records": volume,
            "sparse": sparse,
            "data_note": data_note,
            "visuals": visuals,
            "filters": template.get("filters") or {},
            "warnings": warnings,
        })
    items.sort(key=lambda item: (not item["available"], item["domain"] or "", item["name"]))
    return {
        "total": len(items),
        "items": items,
        "domains": [
            {"id": domain["id"], "label": domain["label"], "templates": [item["id"] for item in items if item["domain"] == domain["id"]]}
            for domain in _domains_with_templates(items)
        ],
    }


def _domains_with_templates(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    domains: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in items:
        key = entry.get("domain") or "outros"
        if key in seen:
            continue
        seen.add(key)
        domains.append({"id": key, "label": _DOMAIN_LABELS.get(key, key)})
    return domains


_DOMAIN_LABELS = {
    "contratacao": "Contratação Pública",
    "mercados": "Mercados Financeiros",
    "crm": "CRM",
    "office": "Office",
    "search360": "Pesquisa 360",
    "scraper": "Recolha",
    "email": "Email",
    "pessoas": "Pessoas e Cargos",
    "outros": "Outros",
}


def as_dashboard(template: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    """Converte um template num dashboard (pronto a guardar ou a abrir no editor)."""
    return {
        "id": None,
        "name": (name or template["name"])[:120],
        "description": template.get("description"),
        "dataset": template["dataset"],
        "filters": template.get("filters") or {},
        "visuals": template["visuals"],
        "theme": "iqos",
        "tags": template.get("tags") or [],
    }
