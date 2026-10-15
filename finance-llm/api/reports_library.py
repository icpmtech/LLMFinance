"""Biblioteca pública de relatórios e documentos já gerados.

O site público (`/site/...`) mostra uma **área de relatórios gratuitos** com o
que a plataforma já tem pronto: os pacotes do catálogo que não se pagam e os
documentos do **Estúdio** que estão publicados e já têm PDF. É a montra do
trabalho feito — e o sítio por onde um visitante começa.

Regras desta área, para não expor o que é de clientes:

* um pacote do catálogo entra se estiver **ativo** e for **grátis** (preço 0);
* um relatório do Estúdio entra se estiver **publicado na plataforma** e tiver
  **PDF gerado**; o PDF só é descarregável quando o preço publicado é 0
  (`document_for_download`) — os pagos encaminham para o catálogo;
* o agrupamento por **área** sai da área do pacote ou das etiquetas do relatório
  do Estúdio (ver `AREAS`), com uma área final para o que não encaixa.

O módulo não fala com o Elasticsearch nem com sessões: lê os dois documentos
(`reports.json` e o do catálogo, que é o mesmo) e devolve o que a página precisa.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import reports_store as store

logger = logging.getLogger(__name__)

#: Áreas da biblioteca pública, pela ordem em que aparecem na página. `tags` são
#: as etiquetas (dos pacotes e dos relatórios do Estúdio) que caem em cada área.
AREAS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "contratacao",
        "label": "Contratação pública",
        "hint": "Quem compra, com quem, por quanto e por que procedimento.",
        "tags": {
            "contratação",
            "contratacao",
            "contratos",
            "compras",
            "cpv",
            "procedimento",
            "séries",
            "series",
            "regiões",
            "regioes",
            "território",
            "territorio",
            "entidades",
            "grafo",
            "pme",
            "benchmark",
        },
    },
    {
        "id": "empresas",
        "label": "Empresas e risco",
        "hint": "Cadastro, CAE, sócios e gerentes, insolvências e sinais de risco.",
        "tags": {
            "empresa",
            "empresas",
            "concorrência",
            "concorrencia",
            "risco",
            "cae",
            "insolvência",
            "insolvencia",
            "societário",
            "societario",
            "corporativo",
            "financeiro",
            "contabilístico",
            "contabilistico",
            "balanço",
            "balanco",
        },
    },
    {
        "id": "mercados",
        "label": "Mercados e notícias",
        "hint": "Instrumentos, cotações, imprensa e sentimento.",
        "tags": {"mercados", "mercado", "notícias", "noticias", "sentimento", "ticker", "cotações", "cotacoes"},
    },
    {
        "id": "setor-publico",
        "label": "Setor público",
        "hint": "Municípios, subvenções, partidos e contas públicas.",
        "tags": {"setor público", "setor publico", "municípios", "municipios", "autarquias", "subvenções", "subvencoes", "partidos", "remunerações", "remuneracoes"},
    },
    {
        "id": "documentos",
        "label": "Documentos e dossiês",
        "hint": "Documentos de referência, dossiês e notas de método.",
        "tags": {"completo", "referência", "referencia", "dossiê", "dossie", "executivo", "metodologia", "livre"},
    },
)
AREAS_BY_ID: Dict[str, Dict[str, Any]] = {area["id"]: area for area in AREAS}

#: Área de recurso: um documento sem etiquetas conhecidas não desaparece da página.
FALLBACK_AREA: Dict[str, Any] = {
    "id": "outros",
    "label": "Outros documentos",
    "hint": "Documentos e relatórios das restantes áreas de trabalho.",
    "tags": set(),
}

#: Área declarada por omissão para cada pacote de origem (`reports_store`). É o
#: último recurso do `area_of`: uma instalação antiga tem os pacotes guardados
#: sem `area`, e sem isto os relatórios financeiros e o corporativo caíam todos
#: em «Outros documentos».
AREAS_POR_OMISSAO: Dict[str, str] = {
    str(item.get("id")): str(item.get("area"))
    for item in store.DEFAULT_CATALOGUE
    if item.get("area")
}

#: Título e descrição por omissão do bloco (o CMS pode mudar os dois).
DEFAULT_TITLE = "Relatórios gratuitos e documentos já gerados"
DEFAULT_SUBTITLE = (
    "O que a plataforma já produziu, por área de trabalho: relatórios de leitura rápida e documentos "
    "gerados a partir de dados abertos. Os gratuitos descarregam-se aqui; os restantes pedem-se no catálogo."
)

MAX_ITEMS = 60


def _text(value: Any, limit: int = 0) -> str:
    result = " ".join(str(value or "").split())
    if limit and len(result) > limit:
        result = result[:limit].rstrip()
    return result


def _tags(value: Any) -> List[str]:
    if isinstance(value, str):
        items: Sequence[Any] = [part for part in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = []
    out: List[str] = []
    for item in items:
        text = _text(item, 40).lower()
        if text and text not in out:
            out.append(text)
    return out


def area_of(package: Dict[str, Any]) -> Dict[str, Any]:
    """Área de um pacote ou relatório: pela área declarada ou pelas etiquetas.

    A **primeira** etiqueta que conhece uma área decide: nos modelos do Estúdio a
    primeira etiqueta é a matéria principal do relatório (ex.: `empresa` na
    concorrência, `cae` na área de atividade), e é isso que se quer mostrar na
    montra, em vez de a primeira área que calhe ter uma etiqueta qualquer.
    """
    declared = _text(package.get("area"), 40).lower()
    if declared in AREAS_BY_ID:
        return AREAS_BY_ID[declared]
    for tag in _tags(package.get("tags")):
        for area in AREAS:
            if tag in area["tags"]:
                return area
    # Sem área nem etiquetas conhecidas: o identificador ainda ajuda (ex.: `concorrencia`).
    identificador = _text(package.get("id") or package.get("code"), 40).lower()
    for area in AREAS:
        if any(tag in identificador for tag in area["tags"]):
            return area
    # Último recurso: a área com que este pacote nasceu no catálogo por omissão.
    # Serve as instalações que já existiam antes deste campo existir — o deploy
    # de código não lhes leva o `data/`, por isso os pacotes guardados não têm
    # `area` gravada.
    por_omissao = AREAS_POR_OMISSAO.get(_text(package.get("id"), 40).lower())
    if por_omissao:
        return AREAS_BY_ID[por_omissao]
    return FALLBACK_AREA


def _package_item(package: Dict[str, Any], report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    price = store.money(package.get("price"))
    # Um pacote criado ao publicar no Estúdio (`estudio:<id>`) não guarda área nem
    # etiquetas: herda as do relatório, senão caía em «Outros documentos».
    area_source: Dict[str, Any] = dict(package)
    if report and not _text(package.get("area")) and not _tags(package.get("tags")):
        area_source["tags"] = report.get("tags")
    area = area_of(area_source)
    return {
        "id": f"pacote:{package.get('id')}",
        "ref": _text(package.get("id"), 80),
        "kind": "relatorio",
        "kind_label": "Relatório",
        "title": _text(package.get("title"), 120),
        "subtitle": _text(package.get("subtitle"), 160),
        "note": _text(package.get("note"), 200),
        "area": area["id"],
        "area_label": area["label"],
        "price": price,
        "list_price": store.money(package.get("list_price")),
        "free": price <= 0,
        "badge": _text(package.get("badge"), 24),
        "delivery_days": int(package.get("delivery_days") or 0),
        "features": [_text(item, 200) for item in (package.get("features") or [])][:8],
        "auto": _text(package.get("auto"), 80),
        "tags": _tags(package.get("tags")),
        # Sem PDF próprio: pede-se no catálogo (grátis ou pago).
        "href": "/reports",
        "download": "",
        "at": "",
    }


def _studio_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    publication = (doc.get("publication") or {}).get("site") or {}
    price = store.money(publication.get("price"))
    area = area_of({"tags": doc.get("tags"), "id": doc.get("id")})
    files = [item for item in (doc.get("files") or []) if isinstance(item, dict)]
    pdf = files[0] if files else None
    return {
        "id": f"documento:{doc.get('id')}",
        "ref": _text(doc.get("id"), 80),
        "kind": "documento",
        "kind_label": "Documento",
        "title": _text(doc.get("title"), 140),
        "subtitle": _text(doc.get("subtitle"), 160) or _text(doc.get("description"), 200),
        "note": _text(doc.get("summary") or doc.get("description"), 300),
        "area": area["id"],
        "area_label": area["label"],
        "price": price,
        "list_price": store.money(publication.get("list_price")),
        "free": price <= 0,
        "badge": "",
        "delivery_days": 0,
        "features": [_text(item, 200) for item in (doc.get("tags") or [])][:8],
        "auto": "",
        "tags": _tags(doc.get("tags")),
        "href": "/reports",
        "download": f"/site/documento/{doc.get('id')}" if (pdf and price <= 0) else "",
        "pages": int(pdf.get("pages") or 0) if pdf else 0,
        "size": int(pdf.get("size") or 0) if pdf else 0,
        "at": _text(publication.get("at") or doc.get("updated_at"), 40),
    }


def items(include_paid: bool = True) -> List[Dict[str, Any]]:
    """Tudo o que a biblioteca pode mostrar (pacotes grátis + documentos gerados)."""
    out: List[Dict[str, Any]] = []
    documentos: List[Dict[str, Any]] = []
    relatorios: Dict[str, Dict[str, Any]] = {}
    for doc in store.load().get("studio_reports") or []:
        if not isinstance(doc, dict):
            continue
        relatorios[str(doc.get("id"))] = doc
        publication = (doc.get("publication") or {}).get("site") or {}
        if not publication.get("published") or not (doc.get("files") or []):
            continue
        if store.money(publication.get("price")) > 0 and not include_paid:
            continue
        documentos.append(_studio_item(doc))
    # Publicar no site cria **também** um pacote no catálogo (`auto=estudio:<id>`):
    # sem isto, o mesmo relatório aparecia duas vezes na página — uma como pacote
    # e outra como documento. Fica o documento, que é o que tem o PDF.
    documentos_por_id = {item["ref"] for item in documentos}
    for package in store.catalogue(only_active=True):
        auto = _text(package.get("auto"), 80)
        report_id = ""
        if auto.lower().startswith("estudio:"):
            report_id = auto.split(":", 1)[1].strip()
            if report_id in documentos_por_id:
                continue
        if store.money(package.get("price")) > 0 and not include_paid:
            continue
        out.append(_package_item(package, relatorios.get(report_id)))
    out.extend(documentos)
    out.sort(key=lambda item: (not item["free"], item["area"], item["title"]))
    return out[:MAX_ITEMS]


def library(
    *,
    areas: Optional[Sequence[str]] = None,
    limit: int = 0,
    grouped: bool = True,
    free_only: bool = False,
) -> Dict[str, Any]:
    """Biblioteca pronta a desenhar: itens e (por omissão) agrupados por área."""
    wanted = {_text(item, 40).lower() for item in (areas or []) if _text(item, 40)}
    todos = [item for item in items(include_paid=not free_only) if not wanted or item["area"] in wanted]
    if limit:
        todos = todos[: max(1, int(limit))]
    grupos: List[Dict[str, Any]] = []
    for area in (*AREAS, FALLBACK_AREA):
        membros = [item for item in todos if item["area"] == area["id"]]
        if not membros:
            continue
        grupos.append(
            {
                "id": area["id"],
                "label": area["label"],
                "hint": area.get("hint") or "",
                "items": membros,
                "free": sum(1 for item in membros if item["free"]),
                "total": len(membros),
            }
        )
    resultado: Dict[str, Any] = {
        "items": todos,
        "total": len(todos),
        "free": sum(1 for item in todos if item["free"]),
        "documents": sum(1 for item in todos if item["kind"] == "documento"),
        "areas": grupos,
        "areas_total": len(grupos),
        "title": DEFAULT_TITLE,
        "subtitle": DEFAULT_SUBTITLE,
    }
    if not grouped:
        resultado["areas"] = []
    return resultado


def document_for_download(document_id: str) -> Optional[Tuple[str, bytes, str]]:
    """PDF de um documento **gratuito e publicado** (para o site público).

    Devolve `None` quando o documento não existe, não está publicado, não tem
    PDF ou tem preço — nesse caso pede-se no catálogo, como qualquer relatório
    pago. É esta a fronteira entre a montra e o que é de clientes.
    """
    from api import reports_studio as studio  # noqa: PLC0415 - ciclo: o estúdio importa a loja

    key = _text(document_id, 80)
    if not key:
        return None
    doc = studio.get_report(key)
    if doc is None:
        return None
    publication = (doc.get("publication") or {}).get("site") or {}
    if not publication.get("published") or store.money(publication.get("price")) > 0:
        return None
    first = next((item for item in (doc.get("files") or []) if isinstance(item, dict)), None)
    if first is None:
        return None
    encontrado = studio.file_of(doc, str(first.get("id")))
    if encontrado is None:
        return None
    path, item = encontrado
    try:
        conteudo = path.read_bytes()
    except OSError as exc:
        logger.warning("Biblioteca: PDF de %s ilegível (%s)", key, exc)
        return None
    return str(item.get("name") or "documento.pdf"), conteudo, str(item.get("mime") or "application/pdf")
